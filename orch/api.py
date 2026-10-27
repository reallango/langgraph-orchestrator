"""HTTP front door: `uvicorn orch.api:app --host 0.0.0.0 --port 8099`. One job at a time (GPUs are serial).

Besides the native /runs API it speaks enough of the OpenAI API (`/v1/models`, `/v1/chat/completions`, streaming or
not) to be added as an OpenAI connection in Open WebUI or any OpenAI client. A chat is a design discussion with the
planner model, which reads the repo files named at the top of a message:

    repo: myproject                 (a git repo under ORCH_ALLOWED_ROOT; relative names resolve inside it)
    files: src/a.py, src/b.py       (optional: files to read)
    check: pytest -q                (optional, repeatable: commands that must exit 0)

A last line `review` turns the discussion into a task description and shows it to each coding model for its view
(best option, risks, ambiguities); nothing is coded. A last line `go` turns the discussion (including that feedback)
into the task and runs the consensus pipeline; a first message ending in `go` is run as written. Directive lines may
also sit in a system message (e.g. an Open WebUI model preset that pins the repo); later ones win. A run's reply streams
progress and ends with the result, the branch and its diff stat. Nothing is merged: the work stays on branch
orch/<run-id> in that repo. The chat history Open WebUI resends each turn is the only state."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import llm
from . import repo as gitrepo
from .audit import Run
from .cli import check_repo_allowed
from .config import S
from .graph import run_task

app = FastAPI(title="orch")
pool = ThreadPoolExecutor(max_workers=1)
_gpu = threading.Lock()          # the OpenAI path and /runs share the GPUs: one task at a time
_busy: dict = {}


def _auth(authorization: str = Header(default="")):
    if S.api_key and authorization != f"Bearer {S.api_key}":
        raise HTTPException(401, "missing or wrong API key")


class RunRequest(BaseModel):
    repo: str
    task: str
    checks: list[str] = []
    files: list[str] = []
    max_repairs: int | None = None


def _locked_run(*args, **kw) -> dict:
    with _gpu:
        return run_task(*args, **kw)


@app.post("/runs", dependencies=[Depends(_auth)])
def submit(req: RunRequest):
    repo = _allowed(req.repo)
    pool.submit(_locked_run, repo, req.task, req.checks, req.files, req.max_repairs)
    return {"queued": True}


@app.get("/runs", dependencies=[Depends(_auth)])
def list_runs():
    out = []
    for p in sorted(Path(S.runs_dir).glob("*/run.json"), reverse=True)[:50]:
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


@app.get("/runs/{run_id}", dependencies=[Depends(_auth)])
def get_run(run_id: str):
    p = Path(S.runs_dir) / Path(run_id).name / "run.json"
    if not p.is_file():
        raise HTTPException(404)
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    from . import health as h
    return {**h.status(), "busy": _busy.get("run")}


# ---------------------------------------------------------------- OpenAI-compatible chat
_DIRECTIVE = re.compile(r"^\s*(repo|files?|checks?)\s*:\s*(.*?)\s*$", re.I)
_COMMAND = re.compile(r"^\s*/?(go|review)\s*[.!]*\s*$", re.I)


def parse_request(messages: list[dict]) -> dict:
    """Read a chat: directives (repo/files/check lines at the top of system and user messages; later ones win),
    the command on the last line of the last user message (`go` or `review`, else None), that message's remaining
    text (`task`), and the conversation with directives stripped (`discussion`) for the planner."""
    out: dict = {"repo": None, "files": [], "checks": [], "task": "", "command": None, "discussion": []}

    def take(text: str) -> str:
        rest, head, checks = [], True, []
        for line in text.splitlines():
            m = _DIRECTIVE.match(line) if head else None
            if m:
                key, val = m.group(1).lower(), m.group(2)
                if key == "repo":
                    out["repo"] = val
                elif key.startswith("file"):
                    out["files"] = [f.strip() for f in val.split(",") if f.strip()]
                else:
                    checks.append(val)
                continue
            if head and not line.strip():
                continue
            head = False
            rest.append(line)
        if checks:
            out["checks"] = checks
        return "\n".join(rest).strip()

    for m in messages:
        if m.get("role") == "system":
            take(_text(m.get("content")))
    convo = [m for m in messages if m.get("role") in ("user", "assistant")]
    for i, m in enumerate(convo):
        text = _text(m.get("content"))
        if m["role"] == "user":
            text = take(text)
            if i == len(convo) - 1:
                lines = text.splitlines()
                cmd = _COMMAND.match(lines[-1]) if lines else None
                if cmd:
                    out["command"], text = cmd.group(1).lower(), "\n".join(lines[:-1]).strip()
                out["task"] = text
        if text:
            out["discussion"].append({"role": m["role"], "content": text})
    return out


def _text(content) -> str:
    if isinstance(content, list):          # OpenAI content parts
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content or ""


def _allowed(repo: str) -> str:
    p = Path(repo)
    if not p.is_absolute():
        p = Path(S.allowed_root) / p
    try:
        path = check_repo_allowed(str(p))
    except SystemExit as e:
        raise HTTPException(400, str(e))
    if not (Path(path) / ".git").exists():
        raise HTTPException(400, f"{path} is not a git repository")
    return path


def _repos() -> list[str]:
    root = Path(S.allowed_root)
    return sorted(str(p.parent.relative_to(root)) for p in root.glob("*/.git")) + \
        sorted(str(p.parent.relative_to(root)) for p in root.glob("*/*/.git"))


USAGE = """Before anything is coded, a `repo:` line is needed. Put these at the top of a message:

    repo: <git repo under {root}>
    files: <optional, comma-separated files to read first>
    check: <optional command that must pass; repeatable>

Then talk the change through with me (I read those files). Send `review` to have the two coding models weigh in on the plan before anything is written. When we agree, send `go` and the local consensus pipeline codes it: the two models solve it independently, test each other's work, and only agreed, tested code is accepted. Work lands on a branch `orch/<run-id>`; nothing is merged. A first message that ends with a `go` line runs at once.

Repositories I can see: {repos}"""

DISCUSS = """You are the planning partner in a local coding pipeline. The user is deciding what change to make before \
it is handed to two local coding models (they solve it independently, test each other's work, and only agreed, \
tested code is accepted). Help the user pin the change down: ask about anything ambiguous, point out edge cases and \
risks in the code you were shown, propose a concrete approach, and say which files it touches. Keep replies short \
and concrete; show small snippets only when they clarify a point, do not write the whole implementation. Keep the \
change small enough for one task (at most {max_files} files). If the conversation contains feedback from the coding \
models (after a `review`), weigh it honestly and say which points you would adopt. When the plan is clear, end by \
summarising it in a few bullets and tell the user they can send `review` for the coders' views or `go` to start \
coding.{repo_note}"""

SPEC = """Turn this discussion into ONE self-contained task description for a coding model that will not see the \
discussion. State: the goal; the files to change; the exact behaviour, inputs/outputs and names agreed (function \
names, parameters, error handling); edge cases; and what to leave alone. Include only what was agreed; where the user \
overrode a suggestion, follow the user. Where coding models reviewed an earlier version, fold in the feedback the \
user accepted. Plain text, no preamble, no code fences, at most about 300 words."""

REVIEW = """You are one of the engineers who will implement the task below in this repository, working independently \
from another model; your work will be tested against tests written from the task text. Before anyone writes code, \
weigh in on the plan: which implementation option you think is best and why, risks or edge cases it misses, anything \
ambiguous you would otherwise have to guess, and whether a simpler or safer alternative exists. Short bullets, at \
most about 200 words. Do not write the implementation; a few lines of code only if they make a point clearer.

TASK:
{task}"""


def _repo_context(repo: str, files: list[str]) -> str:
    """File list plus the named files at HEAD (what the pipeline will start from), clipped to the context budget."""
    _, listing = gitrepo.sh(["git", "ls-files"], repo)
    names = listing.splitlines()
    parts = [f"Repository `{Path(repo).name}` ({len(names)} tracked files):\n" + "\n".join(names[:300])]
    budget = S.context_chars
    for f in files:
        rc, body = gitrepo.sh(["git", "show", f"HEAD:{f}"], repo)
        if rc != 0:
            parts.append(f"(file `{f}` not found at HEAD)")
            continue
        body = body if len(body) <= budget else body[:budget] + "\n... (clipped)"
        budget -= len(body)
        parts.append(f"--- {f} ---\n{body}")
        if budget <= 0:
            break
    return "\n\n".join(parts)


def _planner() -> tuple[str, str, str]:
    from . import health as h
    alias = h.pick_alias("reasoner")
    base, key = h.base_for(alias)
    return alias, base, key


def _discussion_messages(req: dict, repo: str | None, system: str) -> list[dict]:
    note = ("\n\nNo repository is selected yet: remind the user to add a `repo:` line before `go`. Repositories: "
            + (", ".join(_repos()) or "(none)")) if not repo else ""
    msgs = [{"role": "system", "content": system.format(max_files=S.max_files, repo_note=note)}]
    if repo:
        msgs.append({"role": "system", "content": _repo_context(repo, req["files"])})
    return msgs + req["discussion"]


@app.get("/v1/models", dependencies=[Depends(_auth)])
def models():
    return {"object": "list", "data": [{"id": S.api_model, "object": "model", "created": 0, "owned_by": "orch"}]}


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    stream: bool = False


_SAY = {
    "preflight": lambda e: f"models: planner {e.get('reasoner')}, coder {e.get('coder')}",
    "plan": lambda e: "plan ready",
    "solve": lambda e: f"solver {e.get('side')} ({e.get('coder')}) finished; visible checks "
                       f"{'pass' if e.get('visible_ok') else 'fail'}",
    "judge": lambda e: f"judged solver {e.get('tests')}'s tests that solver {e.get('code')}'s code fails",
    "consensus": lambda e: f"consensus: {e.get('outcome') or 'none reached'}"
                           + (f" ({e.get('mode')})" if e.get("mode") else ""),
    "check": lambda e: f"checks {'pass' if e.get('passed') else 'fail'}",
    "error": lambda e: f"error: {e.get('error', '')[:200]}",
}


def _progress(run: Run, seen: int) -> tuple[list[str], int]:
    f = run.dir / "events.jsonl"
    if not f.is_file():
        return [], seen
    lines = f.read_text(encoding="utf-8").splitlines()
    out = []
    for raw in lines[seen:]:
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        say = _SAY.get(e.get("kind"))
        if say:
            out.append(f"- {say(e)}")
    return out, len(lines)


def _result(meta: dict, repo: str) -> str:
    status = meta.get("status", "error")
    branch = meta.get("branch", "")
    unverified = status == "passed" and not meta.get("verified")
    lines = [f"**Result: {status.upper()}**" + (" (no checks ran)" if unverified else ""),
             f"Run: `{meta.get('id')}`"]
    if meta.get("reason"):
        lines.append(f"Reason: {meta['reason']}")
    if branch:
        rc, stat = gitrepo.sh(["git", "diff", "--stat", f"{meta.get('base_sha', 'HEAD')}..{branch}"], repo)
        lines += [f"Branch: `{branch}` in `{repo}`", "```", (stat.strip() if rc == 0 else stat.strip()[:500]) or
                  "(no changes)", "```",
                  f"Review: `git diff {meta.get('base_sha', '')[:10]}..{branch}`  Merge: `git merge {branch}`  "
                  f"Discard: `git branch -D {branch}`"]
    if status != "passed":
        lines.append("Not accepted locally: hand this task to Claude (the branch is kept for reference).")
    return "\n".join(lines)


def _cleanup(meta: dict, repo: str) -> None:
    """Drop the run's worktrees (their paths only exist inside this container) and the consensus scratch branches;
    the result branch stays in the repo."""
    run_dir = str(Path(S.runs_dir) / meta.get("id", "x"))
    _, out = gitrepo.sh(["git", "worktree", "list", "--porcelain"], repo)
    for line in out.splitlines():
        if line.startswith("worktree ") and line[9:].startswith(run_dir):
            gitrepo.sh(["git", "worktree", "remove", "--force", line[9:]], repo)
    gitrepo.sh(["git", "worktree", "prune"], repo)
    if meta.get("branch"):
        gitrepo.sh(["git", "branch", "-D", f"{meta['branch']}-b", f"{meta['branch']}-base"], repo)


def _execute(req: dict, repo: str, run: Run) -> dict:
    with _gpu:
        _busy["run"] = run.id
        try:
            meta = run_task(repo, req["task"], req["checks"], req["files"], run=run)
        finally:
            _busy.pop("run", None)
    _cleanup(meta, repo)
    return meta


def _chunk(cid: str, text: str = "", finish: str | None = None) -> str:
    body = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": S.api_model,
            "choices": [{"index": 0, "delta": {"content": text} if text else {}, "finish_reason": finish}]}
    return f"data: {json.dumps(body)}\n\n"


def _complete(cid: str, text: str) -> dict:
    return {"id": cid, "object": "chat.completion", "created": int(time.time()), "model": S.api_model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def _discuss(req: dict, repo: str | None):
    """Stream the planner's reply to the conversation so far."""
    if _busy.get("run"):
        yield "_(a coding run is using the GPU right now, so this reply may be slow)_\n\n"
    try:
        alias, base, key = _planner()
        yield from llm.chat_stream(alias, _discussion_messages(req, repo, DISCUSS), base=base, key=key)
    except Exception as e:
        yield f"\n\n(planner unavailable: {type(e).__name__}: {str(e)[:200]})"


def _spec(req: dict, repo: str, out: list):
    """Yield progress while the planner turns the discussion into a task description; the result goes into out[0]
    ("" on failure). A command message that is the whole conversation is taken as the task itself."""
    task = req["task"]
    if not req["discussion"]:
        out.append("")
        return
    if len(req["discussion"]) > 1 or not task:
        yield "Writing the task description from our discussion...\n\n"
        try:
            alias, base, key = _planner()
            msgs = _discussion_messages(req, repo, SPEC) + [
                {"role": "user", "content": "Write the task description now."}]
            task = llm.chat(alias, msgs, base=base, key=key)
        except Exception as e:
            yield f"(could not write the task description: {type(e).__name__}: {str(e)[:200]})\n\n"
            task = ""
    out.append(task)


def _quote(text: str) -> str:
    return "\n".join("> " + l for l in text.splitlines()) + "\n\n"


def _review(req: dict, repo: str):
    """Show the task description to each coding model and stream its view of the plan. Nothing is coded."""
    spec: list = []
    yield from _spec(req, repo, spec)
    if not spec[0]:
        yield "Nothing to review yet: describe the change first."
        return
    yield "**Task as it stands:**\n\n" + _quote(spec[0])
    from . import health as h
    context = _repo_context(repo, req["files"])
    for alias, home in S.solvers:
        yield f"**{alias.removeprefix('bench-')}:**\n\n"
        if not h.resolve(alias, home):
            yield "(not reachable on any host right now)\n\n"
            continue
        base, key = h.base_for(alias)
        msgs = [{"role": "system", "content": context},
                {"role": "user", "content": REVIEW.format(task=spec[0])}]
        try:
            yield from llm.chat_stream(alias, msgs, base=base, key=key)
        except Exception as e:
            yield f"(failed: {type(e).__name__}: {str(e)[:200]})"
        yield "\n\n"
    yield "_Discuss any of this with me, send `review` again after changes, or send `go` to start coding._"


def _code(req: dict, repo: str):
    """Write the task spec from the discussion (unless the go message is the whole conversation), then run it."""
    spec: list = []
    yield from _spec(req, repo, spec)
    task = spec[0]
    if not task:
        yield "No task description yet (describe the change first), so nothing was run."
        return
    if task != req["task"]:
        yield "**Task sent to the coders:**\n\n" + _quote(task)
    run = Run(task, repo)
    fut = pool.submit(_execute, dict(req, task=task), repo, run)
    head = f"Working in `{repo}` (run `{run.id}`)"
    if _busy.get("run"):
        head += f"; queued behind run `{_busy['run']}`"
    yield head + "\n\n"
    seen, last = 0, time.time()
    while not fut.done():
        time.sleep(2)
        lines, seen = _progress(run, seen)
        if lines:
            yield "\n".join(lines) + "\n"
            last = time.time()
        elif time.time() - last > 20:             # keep proxies and clients from timing out a 10-20 minute task
            yield None
            last = time.time()
    lines, seen = _progress(run, seen)
    try:
        meta = fut.result()
    except Exception as e:                        # infrastructure failure outside run_task's own handling
        meta = {**run.meta, "status": "error", "reason": f"{type(e).__name__}: {e}"}
    yield ("\n".join(lines) + "\n" if lines else "") + "\n" + _result(meta, repo)


@app.post("/v1/chat/completions", dependencies=[Depends(_auth)])
def chat(body: ChatRequest):
    """A conversation with the planner about the change. The last line of the last user message may be a command:
    `review` shows the task description to the coding models for their views; `go` codes it."""
    cid = "chatcmpl-" + uuid.uuid4().hex[:12]
    users = [m for m in body.messages if m.get("role") == "user"]
    if users and _text(users[-1].get("content")).lstrip().startswith("### Task:"):
        # Open WebUI's own background prompts (chat title, tags, follow-ups): answer them plainly with the planner
        alias, base, key = _planner()
        parts = llm.chat_stream(alias, body.messages, base=base, key=key)
        if not body.stream:
            return _complete(cid, "".join(parts))
        return StreamingResponse(_sse(cid, parts), media_type="text/event-stream")
    req = parse_request(body.messages)
    repo = _allowed(req["repo"]) if req["repo"] else None       # a bad repo is a 400 before anything starts
    usage = USAGE.format(root=S.allowed_root, repos=", ".join(_repos()) or "(none)")
    if req["command"]:
        parts = ({"go": _code, "review": _review}[req["command"]](req, repo)) if repo else iter([usage])
    else:
        parts = _discuss(req, repo) if req["discussion"] else iter([usage])

    if not body.stream:
        return _complete(cid, "".join(p for p in parts if p))
    return StreamingResponse(_sse(cid, parts), media_type="text/event-stream")


def _sse(cid: str, parts):
    for p in parts:
        yield _chunk(cid, p) if p else ": keep-alive\n\n"     # None = nothing new, keep the connection alive
    yield _chunk(cid, finish="stop")
    yield "data: [DONE]\n\n"
