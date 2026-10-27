"""LangGraph pipeline: preflight -> plan -> code -> check -> review -> (diagnose -> repair loop) -> finalize."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from . import aider_runner, checks, health, langs, llm, repo
from .audit import Run
from .config import S

PLAN_SYSTEM = """You are the planner in a plan/code/review pipeline. A separate, weaker coding model will
implement your plan, so be concrete and keep the change minimal.
Describe WHAT the code must do (behaviour, edge cases, exact output formats) in plain language.
Do NOT write code, regexes, format strings or code fences in any field: you cannot run it, and
the coder will copy your mistakes verbatim.
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

DIAGNOSE_SYSTEM = """A coding model's attempt failed. You are given the task, its current diff and the failing output.
Explain the ROOT CAUSE and the precise change needed, in plain English, naming the specific function,
line or construct involved. If the cause is a wrong calling convention or API misuse, state the correct usage.
Do not rewrite whole files. At most 10 sentences."""

GEN_TESTS_SYSTEM = """You write extra verification tests for a finished change. You see the TASK, the source files and the existing tests.
Write 4 to 8 NEW tests for requirements stated in the TASK that the existing tests do not cover (edge cases, boundaries,
error handling, exact output formats). Base every expectation ONLY on the TASK text, never on how the code happens to
behave, and skip anything the task leaves ambiguous.
Reply with ONLY a JSON object: {{"content": "<the complete test file>"}}.
{rules}"""
ADJUDICATE_SYSTEM = """Extra tests failed against a change. Decide whether the CODE is wrong or the TESTS are wrong, using only the TASK
text as the source of truth. A test is wrong if it expects something the task does not say, miscomputes an expected value,
has a syntax error or misuses the test framework. Reply with ONLY a JSON object:
{"code_wrong": true or false, "explanation": "<which requirement the code violates and what to change; empty if the tests are wrong>"}"""

PS_HINTS = """PowerShell pitfalls to avoid:
- Every un-captured expression writes to the output stream; suppress stray values with `$null = ...` or `| Out-Null`.
- `return $array` unrolls it. To return an array of arrays, or a one-element array, use `return ,$array`.
- Wrap command results in `@(...)` before using .Count or indexing; one-element results are not arrays otherwise.
- `foreach ($x in <pipeline that yields one array>)` iterates the array's elements; use a `for` loop with an index when items are arrays.
- Call script blocks positionally (`& $sb $arg`) and declare `param($x)` inside; do not pass named arguments.
- Use `$script:name` for state shared between a test and the script blocks it passes in.
- Parameter rules belong in attributes: [ValidateRange()], [ValidateSet()], [Parameter(Mandatory)].
- Format with the -f operator: '{0:00}' zero-pads, '{0:F1}' gives one fixed decimal. Not '{0:.1f}'.
- -eq/-ne/-like are case-insensitive; use -ceq for exact case. Hashtable .Keys order is not guaranteed, so Sort-Object.
- Pester 6: BeforeAll/AfterEach go inside Describe; assertions are `| Should -Be`, `-BeExactly`, `-Throw`.
- Closures over loop variables need `.GetNewClosure()`. Methods on objects are added with Add-Member -MemberType ScriptMethod."""
PY_HINTS = """Python notes:
- Match the exact output formats and error types in the task (for example ValueError for invalid input).
- Handle the edge cases: empty input, zero, boundaries, repeated values, negative numbers.
- Never delete or rename existing functions; edit in place and keep unrelated code unchanged."""
TS_HINTS = """TypeScript notes:
- strict mode is on: no implicit any, handle undefined and null explicitly, keep exported types accurate.
- Keep every existing export and its signature; add new exports instead of changing what callers use.
- Do not import packages that are not already in package.json.
- CommonJS .js files keep using require/module.exports; add new functions to module.exports when the task exports them."""
GENERAL_HINTS = "Never delete or rename existing functions. Do not edit test files. Keep the change as small as the task allows."


def _hints(files: list[str]) -> str:
    if not S.hints:
        return ""
    parts = [GENERAL_HINTS]
    if any(f.lower().endswith((".ps1", ".psm1")) for f in files):
        parts.append(PS_HINTS)
    if any(f.endswith(".py") for f in files):
        parts.append(PY_HINTS)
    if any(f.lower().endswith(langs.TS_EXT) for f in files):
        parts.append(TS_HINTS)
    return "\n\n" + "\n\n".join(parts)


_TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*$)|\.tests?\.[a-z0-9]+$|_test\.[a-z0-9]+$", re.I)


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
    repair_coder: str
    cascade: list
    attempt: int
    attempt_repairs: int
    fresh: bool
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
    reasoner = health.pick_alias("reasoner") if (S.use_planner or S.use_reviewer or S.diagnose) else ""
    coder = health.pick_alias("coder")
    try:  # optional stronger coder for repairs; fall back to the primary coder if none is up
        repair_coder = health.pick_alias("repair_coder")
    except RuntimeError:
        repair_coder = coder
    cascade = [a for a, url in S.cascade_candidates if health.resolve(a, url)]
    if S.cascade_candidates and not cascade:
        raise RuntimeError("no healthy worker for any cascade coder")
    if cascade:
        coder = cascade[0]
    wt, branch, base_sha = repo.create_worktree(s["repo"], run.dir, run.id, s.get("base_ref", "HEAD"))
    cfg = {"planner": S.use_planner, "reviewer": S.use_reviewer, "diagnose": S.diagnose, "direct": S.direct,
           "hints": S.hints, "verify": S.verify, "cascade": cascade}
    run.event("preflight", reasoner=reasoner, coder=coder, repair_coder=repair_coder, branch=branch,
              base=base_sha, config=cfg)
    run.save_meta(branch=branch, base_sha=base_sha, reasoner=reasoner, coder=coder,
                  repair_coder=repair_coder, worktree=str(wt), config=cfg)
    return {"wt": wt, "branch": branch, "base_sha": base_sha, "reasoner": reasoner, "coder": coder,
            "repair_coder": repair_coder, "cascade": cascade, "attempt": 0, "attempt_repairs": 0,
            "fresh": False, "cycle": 0}


def plan(s: State) -> dict:
    run, wt = s["run"], s["wt"]
    tracked = repo.tracked_files(wt)
    hints = [h for h in (repo.safe_rel(wt, h) for h in s.get("hint_files", [])) if h]
    if not S.use_planner:  # control: the coder gets the task and the files directly
        edit = [h for h in hints if not _TEST_PATH.search(h)]
        ctx = [h for h in hints if _TEST_PATH.search(h)]
        p = {"summary": s["task"], "files_to_edit": edit, "context_files": ctx, "steps": [], "acceptance_criteria": []}
        run.log("plan.json", json.dumps(p, indent=2))
        run.event("plan", planner=False)
        return {"plan": p} if edit else {"plan": p, "status": "escalated", "reason": "no editable hint files"}
    listing = "\n".join(tracked[:400])
    user = (
        f"TASK:\n{s['task']}\n\nREPO FILES:\n{listing}\n\n"
        f"FILE CONTENTS (hinted by user):\n{repo.read_capped(wt, hints, S.context_chars)}"
    )
    msgs = [{"role": "system", "content": PLAN_SYSTEM.format(max_files=S.max_files)},
            {"role": "user", "content": user}]
    run.log("plan-prompt.md", user)
    base, key = health.base_for(s["reasoner"])
    p, raw = llm.chat_json(s["reasoner"], msgs, base=base, key=key)
    run.log("plan-response.md", raw)

    edit = [f for f in (repo.safe_rel(wt, f) for f in p.get("files_to_edit", [])) if f]
    ctx = [f for f in (repo.safe_rel(wt, f) for f in p.get("context_files", [])) if f and f in tracked and f not in edit]
    p["files_to_edit"], p["context_files"] = edit, ctx
    p.setdefault("steps", []), p.setdefault("acceptance_criteria", [])
    run.log("plan.json", json.dumps(p, indent=2))
    run.event("plan", planner=True)
    if not edit:
        return {"plan": p, "status": "escalated", "reason": "planner named no files to edit"}
    if len(edit) > S.max_files:
        return {"plan": p, "status": "escalated", "reason": f"plan touches {len(edit)} files (limit {S.max_files})"}
    return {"plan": p}


def code(s: State) -> dict:
    run, wt, p = s["run"], s["wt"], s["plan"]
    steps = "\n".join(f"{i}. {t}" for i, t in enumerate(p["steps"], 1))
    crit = "\n".join(f"- {c}" for c in p["acceptance_criteria"])
    instruction = f"Implement this task with the smallest correct change. Only edit the files given.\n\nTASK: {s['task']}"
    if steps:
        instruction += f"\n\nPLAN:\n{steps}"
    if crit:
        instruction += f"\n\nACCEPTANCE CRITERIA:\n{crit}"
    fresh = bool(s.get("fresh"))
    if fresh:  # new cascade attempt: start again from the original files, learn from the last failure
        repo.reset_to_base(wt, s["base_sha"])
        if s.get("findings"):
            instruction += ("\n\nA previous attempt by another model, started from scratch, failed. Do not repeat its "
                            f"mistakes:\n{_clip(s['findings'], 4000)}")
    elif s.get("findings"):
        instruction += (
            "\n\nThe current code in the files is a previous attempt that failed. Edit the EXISTING code in "
            "place to fix these problems. Never add a second copy of a function or class; replace it.\n"
            f"{s['findings']}"
        )
    instruction += _hints(p["files_to_edit"])
    if s.get("cascade"):
        alias = s["cascade"][s.get("attempt", 0)]
    else:
        alias = s["repair_coder"] if s["cycle"] >= 1 and s.get("repair_coder") else s["coder"]
    base, key = health.base_for(alias)
    run.log(f"code-instruction-c{s['cycle']}.md", f"[coder alias: {alias}]\n{instruction}")
    rc, out = aider_runner.run_aider(wt, alias, instruction, p["files_to_edit"], p["context_files"], run.dir,
                                     base=base, key=key)
    run.log(f"aider-output-c{s['cycle']}.txt", out)
    committed = repo.commit_all(wt, f"orch {run.id} cycle {s['cycle']}: {p.get('summary', s['task'])[:60]}")
    run.event("code", cycle=s["cycle"], aider_rc=rc, committed=committed, coder=alias, attempt=s.get("attempt", 0))
    if not repo.changed_files(wt, s["base_sha"]):
        if s.get("cascade") and s.get("attempt", 0) + 1 < len(s["cascade"]):
            # this model produced nothing; hand the task to the next one rather than giving up
            return {"findings": "The coder produced no changes at all (no valid edit blocks).", "fresh": True,
                    "attempt": s.get("attempt", 0) + 1, "attempt_repairs": 0, "cycle": s["cycle"] + 1}
        return {"status": "failed", "reason": f"coder produced no changes (aider rc={rc})"}
    return {"fresh": False}


def check(s: State) -> dict:
    run, wt = s["run"], s["wt"]
    changed = repo.changed_files(wt, s["base_sha"])
    ok, verified, report = checks.run_checks(wt, s.get("check_cmds", []), changed)
    run.log(f"checks-c{s['cycle']}.txt", report)
    run.event("check", cycle=s["cycle"], passed=ok, verified=verified)
    out: dict[str, Any] = {"verified": verified}
    out["findings"] = "" if ok else f"Checks failed:\n{report}"
    return out


def review(s: State) -> dict:
    run, wt, p = s["run"], s["wt"], s["plan"]
    diff = _clip(repo.diff_since(wt, s["base_sha"]), S.diff_chars)
    crit = "\n".join(f"- {c}" for c in p["acceptance_criteria"]) or "- (none given; judge against the task)"
    user = f"TASK:\n{s['task']}\n\nACCEPTANCE CRITERIA:\n{crit}\n\nDIFF:\n{diff}"
    run.log(f"review-prompt-c{s['cycle']}.md", user)
    base, key = health.base_for(s["reasoner"])
    v, raw = llm.chat_json(s["reasoner"], [{"role": "system", "content": REVIEW_SYSTEM},
                                          {"role": "user", "content": user}], base=base, key=key)
    run.log(f"review-response-c{s['cycle']}.md", raw)
    run.event("review", cycle=s["cycle"], verdict=str(v.get("verdict", "")).lower())
    if str(v.get("verdict", "")).lower() == "pass":
        return {"findings": ""}
    lines = [f"- [{f.get('criterion', '?')}] {f.get('problem', '')} -> {f.get('fix', '')}"
             for f in v.get("findings", []) if isinstance(f, dict)]
    return {"findings": "Reviewer findings:\n" + ("\n".join(lines) or "- reviewer failed the change without detail")}


def repair_gate(s: State) -> dict:
    """Bounded repair: stop on max cycles or on a repeated identical finding."""
    fp = _fp(s["findings"])
    if s.get("cascade"):
        # Cascade: patch the current attempt up to S.attempt_repairs times, then restart from scratch with the next coder.
        if s["cycle"] >= S.max_total:
            return {"status": "failed", "reason": f"still failing after {s['cycle'] + 1} coder calls"}
        att, ar = s.get("attempt", 0), s.get("attempt_repairs", 0)
        if ar < S.attempt_repairs and fp != s.get("last_fp"):
            return {"cycle": s["cycle"] + 1, "attempt_repairs": ar + 1, "last_fp": fp}
        if att + 1 >= len(s["cascade"]):
            return {"status": "failed", "reason": f"all {len(s['cascade'])} cascade coders failed"}
        return {"cycle": s["cycle"] + 1, "attempt": att + 1, "attempt_repairs": 0, "last_fp": fp, "fresh": True}
    if s["cycle"] >= s.get("max_repairs", S.max_repairs):
        return {"status": "failed", "reason": f"still failing after {s['cycle']} repair cycle(s)"}
    if fp == s.get("last_fp"):
        return {"status": "failed", "reason": "same findings repeated; coder is not making progress"}
    return {"cycle": s["cycle"] + 1, "last_fp": fp}


def diagnose(s: State) -> dict:
    """Optional: the reasoner turns raw failure output into a plain-language root cause for the coder."""
    if not S.diagnose or not s.get("reasoner"):
        return {}
    run, wt = s["run"], s["wt"]
    diff = _clip(repo.diff_since(wt, s["base_sha"]), S.diff_chars)
    user = f"TASK:\n{s['task']}\n\nCURRENT DIFF:\n{diff}\n\nFAILING OUTPUT:\n{_clip(s['findings'], 6000)}"
    base, key = health.base_for(s["reasoner"])
    try:
        text = llm.chat(s["reasoner"], [{"role": "system", "content": DIAGNOSE_SYSTEM},
                                        {"role": "user", "content": user}], base=base, key=key)
    except Exception as e:  # diagnosis is an optimisation; never fail the run over it
        run.event("diagnose_error", error=str(e))
        return {}
    run.log(f"diagnosis-c{s['cycle']}.md", text)
    run.event("diagnose", cycle=s["cycle"])
    return {"findings": s["findings"] + f"\n\nDiagnosis of the root cause:\n{text}"}


def verify(s: State) -> dict:
    """Optional: the reasoner writes extra tests from the TASK text; a failing one only counts if the reasoner then
    judges the code (not the test) to be wrong. Catches 'passes the visible tests but misses the spec' cases."""
    if not (S.verify and s.get("reasoner")):
        return {}
    run, wt, p = s["run"], s["wt"], s["plan"]
    edit = p["files_to_edit"]
    lang = langs.detect(edit)
    if not lang:
        return {}
    fname = lang.test_file()
    base, key = health.base_for(s["reasoner"])
    sources = repo.read_capped(wt, edit + p.get("context_files", []), S.context_chars)
    user = f"TASK:\n{s['task']}\n\nFILES:\n{sources}"
    try:
        obj, _ = llm.chat_json(s["reasoner"], [{"role": "system", "content": GEN_TESTS_SYSTEM.format(rules=lang.rules)},
                                               {"role": "user", "content": user}], base=base, key=key)
        content = str(obj["content"])
    except Exception as e:  # verification is an extra; never fail the run over it
        run.event("verify_error", stage="generate", error=str(e)[:200])
        return {}
    (wt / fname).write_text(content, encoding="utf-8")
    try:
        rc, out = repo.sh(lang.command(wt, fname), wt, timeout=S.check_timeout)
    finally:
        (wt / fname).unlink(missing_ok=True)
    run.log(f"extra-tests-c{s['cycle']}.txt", f"{content}\n---- exit {rc}\n{out[-3000:]}")
    if rc == 0:
        run.event("verify", cycle=s["cycle"], result="pass")
        return {}
    try:
        verdict, _ = llm.chat_json(s["reasoner"], [
            {"role": "system", "content": ADJUDICATE_SYSTEM},
            {"role": "user", "content": f"{user}\n\nEXTRA TESTS:\n{content}\n\nFAILING OUTPUT:\n{_clip(out, 3000)}"}],
            base=base, key=key)
    except Exception as e:
        run.event("verify_error", stage="adjudicate", error=str(e)[:200])
        return {}
    wrong = verdict.get("code_wrong") is True
    run.event("verify", cycle=s["cycle"], result="code_wrong" if wrong else "test_wrong")
    if not wrong:
        return {}
    return {"findings": f"Extra verification found a defect the existing tests miss:\n{verdict.get('explanation', '')}\n"
                        f"(failing output excerpt)\n{_clip(out, 1500)}"}


def finalize(s: State) -> dict:
    run = s["run"]
    status = s.get("status") or "passed"
    reason = s.get("reason", "")
    p = s.get("plan", {})
    unverified = status == "passed" and not s.get("verified", False)
    summary = [
        f"# Run {run.id}: {status.upper()}{' (UNVERIFIED: no checks ran)' if unverified else ''}",
        f"Task: {s['task']}", f"Branch: {s.get('branch')} (base {s.get('base_sha', '')[:10]})",
        f"Models: reasoner={s.get('reasoner')} coder={s.get('coder')} repair_coder={s.get('repair_coder')}",
        f"Repair cycles used: {s.get('cycle', 0)}", f"Reason: {reason or 'n/a'}",
        f"Plan summary: {p.get('summary', 'n/a')}",
        f"Files: {', '.join(p.get('files_to_edit', [])) or 'n/a'}",
    ]
    if s.get("findings"):
        summary.append(f"\nOutstanding findings:\n{s['findings']}")
    text = "\n".join(summary)
    (run.dir / "summary.md").write_text(text, encoding="utf-8")
    run.save_meta(status=status, reason=reason, verified=s.get("verified", False), cycles=s.get("cycle", 0),
                  attempts=s.get("attempt", 0) + 1)
    return {"status": status}


def _after_plan(s: State) -> str:
    if s.get("status"):
        return "finalize"
    return "consensus" if S.solvers else "code"


def consensus_node(s: State) -> dict:
    from .consensus import consensus
    return consensus(s)


def _after_code(s: State) -> str:
    if s.get("status"):
        return "finalize"
    return "code" if s.get("fresh") else "check"      # fresh=True here means: no edits, next cascade coder takes over


def _after_check(s: State) -> str:
    return "repair_gate" if s.get("findings") else "verify"


def _after_verify(s: State) -> str:
    if s.get("findings"):
        return "repair_gate"
    return "review" if S.use_reviewer and s.get("reasoner") else "finalize"


def _after_review(s: State) -> str:
    return "repair_gate" if s.get("findings") else "finalize"


def _after_gate(s: State) -> str:
    return "finalize" if s.get("status") else "diagnose"


def build():
    g = StateGraph(State)
    for name, fn in [("preflight", preflight), ("plan", plan), ("code", code), ("check", check),
                     ("verify", verify), ("review", review), ("repair_gate", repair_gate),
                     ("diagnose", diagnose), ("consensus", consensus_node), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.set_entry_point("preflight")
    g.add_edge("preflight", "plan")
    g.add_conditional_edges("plan", _after_plan, {"code": "code", "consensus": "consensus", "finalize": "finalize"})
    g.add_edge("consensus", "finalize")
    g.add_conditional_edges("code", _after_code, {"check": "check", "finalize": "finalize", "code": "code"})
    g.add_conditional_edges("check", _after_check, {"repair_gate": "repair_gate", "verify": "verify"})
    g.add_conditional_edges("verify", _after_verify,
                            {"repair_gate": "repair_gate", "review": "review", "finalize": "finalize"})
    g.add_conditional_edges("review", _after_review, {"repair_gate": "repair_gate", "finalize": "finalize"})
    g.add_conditional_edges("repair_gate", _after_gate, {"diagnose": "diagnose", "finalize": "finalize"})
    g.add_edge("diagnose", "code")
    g.add_edge("finalize", END)
    return g.compile()


def run_task(repo_path: str, task: str, check_cmds: list[str] | None = None,
             hint_files: list[str] | None = None, max_repairs: int | None = None,
             base_ref: str = "HEAD", run: Run | None = None) -> dict:
    run = run or Run(task, repo_path)        # callers that stream progress create the Run first to know its id
    state: State = {"run": run, "task": task, "repo": repo_path, "base_ref": base_ref,
                    "check_cmds": check_cmds or [], "hint_files": hint_files or [],
                    "max_repairs": S.max_repairs if max_repairs is None else max_repairs}
    try:
        build().invoke(state, {"recursion_limit": 80})
    except Exception as e:  # infrastructure failure: record it, don't lose the audit trail
        run.save_meta(status="error", reason=f"{type(e).__name__}: {e}")
        run.event("error", error=str(e))
    return run.meta
