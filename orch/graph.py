"""LangGraph pipeline: preflight -> plan -> code -> check -> review -> (repair loop) -> finalize."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from . import aider_runner, checks, health, llm, repo
from .audit import Run
from .config import S

PLAN_SYSTEM = """You are the planner in a plan/code/review pipeline. A separate, weaker coding model will
implement your plan, so be concrete and keep the change minimal.
Reply with ONLY a JSON object with these keys:
  "summary": one sentence,
  "files_to_edit": repo-relative paths to modify or create (at most {max_files}),
  "context_files": existing repo-relative paths worth reading but not editing,
  "steps": ordered, specific implementation steps,
  "acceptance_criteria": checkable statements (each one verifiable from the diff or a command),
  "risks": list of strings.
If the task cannot be done within {max_files} files, still list what is needed; the pipeline will escalate."""

REVIEW_SYSTEM = """You review a diff against acceptance criteria. Judge ONLY the listed criteria and the check results;
do not make general style comments. Reply with ONLY a JSON object:
  "verdict": "pass" or "fail",
  "findings": [{{"criterion": str, "problem": str, "fix": str}}]  (empty when verdict is pass)."""


class State(TypedDict, total=False):
    run: Run
    task: str
    repo: str
    base_ref: str
    check_cmds: list[str]
    hint_files: list[str]
    max_repairs: int
    wt: Path
    branch: str
    base_sha: str
    reasoner: str
    coder: str
    plan: dict
    cycle: int
    findings: str
    verified: bool
    last_fp: str
    status: str
    reason: str


def _fp(text: str) -> str:
    return hashlib.sha1(re.sub(r"\d+", "#", text).strip().encode()).hexdigest()


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"\n...[truncated {len(text) - n} chars]"


def preflight(s: State) -> dict:
    run = s["run"]
    reasoner, coder = health.pick_alias("reasoner"), health.pick_alias("coder")
    wt, branch, base_sha = repo.create_worktree(s["repo"], run.dir, run.id, s.get("base_ref", "HEAD"))
    run.event("preflight", reasoner=reasoner, coder=coder, branch=branch, base=base_sha)
    run.save_meta(branch=branch, base_sha=base_sha, reasoner=reasoner, coder=coder, worktree=str(wt))
    return {"wt": wt, "branch": branch, "base_sha": base_sha, "reasoner": reasoner, "coder": coder, "cycle": 0}


def plan(s: State) -> dict:
    run, wt = s["run"], s["wt"]
    tracked = repo.tracked_files(wt)
    hints = [h for h in (repo.safe_rel(wt, h) for h in s.get("hint_files", [])) if h]
    listing = "\n".join(tracked[:400])
    user = (
        f"TASK:\n{s['task']}\n\nREPO FILES:\n{listing}\n\n"
        f"FILE CONTENTS (hinted by user):\n{repo.read_capped(wt, hints, S.context_chars)}"
    )
    msgs = [{"role": "system", "content": PLAN_SYSTEM.format(max_files=S.max_files)},
            {"role": "user", "content": user}]
    run.log("plan-prompt.md", user)
    p, raw = llm.chat_json(s["reasoner"], msgs)
    run.log("plan-response.md", raw)

    edit = [f for f in (repo.safe_rel(wt, f) for f in p.get("files_to_edit", [])) if f]
    ctx = [f for f in (repo.safe_rel(wt, f) for f in p.get("context_files", [])) if f and f in tracked and f not in edit]
    p["files_to_edit"], p["context_files"] = edit, ctx
    p.setdefault("steps", []), p.setdefault("acceptance_criteria", [])
    run.log("plan.json", json.dumps(p, indent=2))
    if not edit:
        return {"plan": p, "status": "escalated", "reason": "planner named no files to edit"}
    if len(edit) > S.max_files:
        return {"plan": p, "status": "escalated", "reason": f"plan touches {len(edit)} files (limit {S.max_files})"}
    return {"plan": p}


def code(s: State) -> dict:
    run, wt, p = s["run"], s["wt"], s["plan"]
    steps = "\n".join(f"{i}. {t}" for i, t in enumerate(p["steps"], 1))
    crit = "\n".join(f"- {c}" for c in p["acceptance_criteria"])
    instruction = (
        f"Implement this task with the smallest correct change. Only edit the files given.\n\n"
        f"TASK: {s['task']}\n\nPLAN:\n{steps}\n\nACCEPTANCE CRITERIA:\n{crit}"
    )
    if s.get("findings"):
        instruction += f"\n\nYour previous attempt failed. Fix these problems:\n{s['findings']}"
    run.log(f"code-instruction-c{s['cycle']}.md", instruction)
    rc, out = aider_runner.run_aider(wt, s["coder"], instruction, p["files_to_edit"], p["context_files"], run.dir)
    run.log(f"aider-output-c{s['cycle']}.txt", out)
    committed = repo.commit_all(wt, f"orch {run.id} cycle {s['cycle']}: {p.get('summary', s['task'])[:60]}")
    run.event("code", cycle=s["cycle"], aider_rc=rc, committed=committed)
    if not repo.changed_files(wt, s["base_sha"]):
        return {"status": "failed", "reason": f"coder produced no changes (aider rc={rc})"}
    return {}


def check(s: State) -> dict:
    run, wt = s["run"], s["wt"]
    changed = repo.changed_files(wt, s["base_sha"])
    ok, verified, report = checks.run_checks(wt, s.get("check_cmds", []), changed)
    run.log(f"checks-c{s['cycle']}.txt", report)
    run.event("check", cycle=s["cycle"], passed=ok, verified=verified)
    out: dict[str, Any] = {"verified": verified}
    if not ok:
        out["findings"] = f"Checks failed:\n{report}"
    else:
        out["findings"] = ""
    return out


def review(s: State) -> dict:
    run, wt, p = s["run"], s["wt"], s["plan"]
    diff = _clip(repo.diff_since(wt, s["base_sha"]), S.diff_chars)
    crit = "\n".join(f"- {c}" for c in p["acceptance_criteria"]) or "- (none given; judge against the task)"
    user = f"TASK:\n{s['task']}\n\nACCEPTANCE CRITERIA:\n{crit}\n\nDIFF:\n{diff}"
    run.log(f"review-prompt-c{s['cycle']}.md", user)
    v, raw = llm.chat_json(s["reasoner"], [{"role": "system", "content": REVIEW_SYSTEM},
                                          {"role": "user", "content": user}])
    run.log(f"review-response-c{s['cycle']}.md", raw)
    if str(v.get("verdict", "")).lower() == "pass":
        return {"findings": ""}
    lines = [f"- [{f.get('criterion', '?')}] {f.get('problem', '')} -> {f.get('fix', '')}"
             for f in v.get("findings", []) if isinstance(f, dict)]
    return {"findings": "Reviewer findings:\n" + ("\n".join(lines) or "- reviewer failed the change without detail")}


def repair_gate(s: State) -> dict:
    """Bounded repair: stop on max cycles or on a repeated identical finding."""
    fp = _fp(s["findings"])
    if s["cycle"] >= s.get("max_repairs", S.max_repairs):
        return {"status": "failed", "reason": f"still failing after {s['cycle']} repair cycle(s)"}
    if fp == s.get("last_fp"):
        return {"status": "failed", "reason": "same findings repeated; coder is not making progress"}
    return {"cycle": s["cycle"] + 1, "last_fp": fp}


def finalize(s: State) -> dict:
    run = s["run"]
    status = s.get("status") or "passed"
    reason = s.get("reason", "")
    p = s.get("plan", {})
    unverified = status == "passed" and not s.get("verified", False)
    summary = [
        f"# Run {run.id}: {status.upper()}{' (UNVERIFIED: no checks ran)' if unverified else ''}",
        f"Task: {s['task']}", f"Branch: {s.get('branch')} (base {s.get('base_sha', '')[:10]})",
        f"Models: reasoner={s.get('reasoner')} coder={s.get('coder')}",
        f"Repair cycles used: {s.get('cycle', 0)}", f"Reason: {reason or 'n/a'}",
        f"Plan summary: {p.get('summary', 'n/a')}",
        f"Files: {', '.join(p.get('files_to_edit', [])) or 'n/a'}",
    ]
    if s.get("findings"):
        summary.append(f"\nOutstanding findings:\n{s['findings']}")
    text = "\n".join(summary)
    (run.dir / "summary.md").write_text(text, encoding="utf-8")
    run.save_meta(status=status, reason=reason, verified=s.get("verified", False), cycles=s.get("cycle", 0))
    return {"status": status}


def _after_plan(s: State) -> str:
    return "finalize" if s.get("status") else "code"


def _after_code(s: State) -> str:
    return "finalize" if s.get("status") else "check"


def _after_check(s: State) -> str:
    return "repair_gate" if s.get("findings") else "review"


def _after_review(s: State) -> str:
    return "repair_gate" if s.get("findings") else "finalize"


def _after_gate(s: State) -> str:
    return "finalize" if s.get("status") else "code"


def build():
    g = StateGraph(State)
    for name, fn in [("preflight", preflight), ("plan", plan), ("code", code), ("check", check),
                     ("review", review), ("repair_gate", repair_gate), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.set_entry_point("preflight")
    g.add_edge("preflight", "plan")
    g.add_conditional_edges("plan", _after_plan, {"code": "code", "finalize": "finalize"})
    g.add_conditional_edges("code", _after_code, {"check": "check", "finalize": "finalize"})
    g.add_conditional_edges("check", _after_check, {"repair_gate": "repair_gate", "review": "review"})
    g.add_conditional_edges("review", _after_review, {"repair_gate": "repair_gate", "finalize": "finalize"})
    g.add_conditional_edges("repair_gate", _after_gate, {"code": "code", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()


def run_task(repo_path: str, task: str, check_cmds: list[str] | None = None,
             hint_files: list[str] | None = None, max_repairs: int | None = None,
             base_ref: str = "HEAD") -> dict:
    run = Run(task, repo_path)
    state: State = {"run": run, "task": task, "repo": repo_path, "base_ref": base_ref,
                    "check_cmds": check_cmds or [], "hint_files": hint_files or [],
                    "max_repairs": S.max_repairs if max_repairs is None else max_repairs}
    try:
        build().invoke(state, {"recursion_limit": 60})
    except Exception as e:  # infrastructure failure: record it, don't lose the audit trail
        run.save_meta(status="error", reason=f"{type(e).__name__}: {e}")
        run.event("error", error=str(e))
    return run.meta
