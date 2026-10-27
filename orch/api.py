"""HTTP front door: `uvicorn orch.api:app --host 0.0.0.0 --port 8099`. One job at a time (GPUs are serial).

Besides the native /runs API it speaks enough of the OpenAI API (`/v1/models`, `/v1/chat/completions`, streaming or
not) to be added as an OpenAI connection in Open WebUI or any OpenAI client. Each chat message is one coding task:

    repo: myproject                 (a git repo under ORCH_ALLOWED_ROOT; relative names resolve inside it)
    files: src/a.py, src/b.py       (optional: files the planner should read first)
    check: pytest -q                (optional, repeatable: commands that must exit 0)
    <the task, in plain words>

Directive lines may also sit in a system message (e.g. an Open WebUI model preset that pins the repo); the user
message overrides them. The reply streams progress and ends with the result, the branch and its diff stat. Nothing is
merged: the work stays on branch orch/<run-id> in that repo."""
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


def parse_request(messages: list[dict]) -> dict:
    """{repo, files, checks, task} from chat messages: directives from system messages, then the last user message."""
    out: dict = {"repo": None, "files": [], "checks": [], "task": ""}

    def take(text: str, is_user: bool) -> str:
        lines, rest, head = text.splitlines(), [], True
        checks: list[str] = []
        for line in lines:
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
            take(_text(m.get("content")), False)
    users = [m for m in messages if m.get("role") == "user"]
    if users:
        out["task"] = take(_text(users[-1].get("content")), True)
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


USAGE = """I run a coding task through the local consensus pipeline (two models solve it independently, test each other's work, and only agreed, tested code is accepted). Start your message with:

    repo: <git repo under {root}>
    files: <optional, comma-separated files to read first>
    check: <optional command that must pass; repeatable>

then describe the task. Work lands on a branch `orch/<run-id>`; nothing is merged.

Repositories I can see: {repos}"""


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


@app.post("/v1/chat/completions", dependencies=[Depends(_auth)])
def chat(body: ChatRequest):
    cid = "chatcmpl-" + uuid.uuid4().hex[:12]
    req = parse_request(body.messages)
    if not req["repo"] or not req["task"]:
        text = USAGE.format(root=S.allowed_root, repos=", ".join(_repos()) or "(none)")
        if body.stream:
            return StreamingResponse(iter([_chunk(cid, text), _chunk(cid, finish="stop"), "data: [DONE]\n\n"]),
                                     media_type="text/event-stream")
        return _complete(cid, text)
    repo = _allowed(req["repo"])
    run = Run(req["task"], repo)

    if not body.stream:
        return _complete(cid, _result(_execute(req, repo, run), repo))

    def gen():
        fut = pool.submit(_execute, req, repo, run)
        head = f"Working in `{repo}` (run `{run.id}`)"
        if _busy.get("run"):
            head += f"; queued behind run `{_busy['run']}`"
        yield _chunk(cid, head + "\n\n")
        seen, last = 0, time.time()
        while not fut.done():
            time.sleep(2)
            lines, seen = _progress(run, seen)
            if lines:
                yield _chunk(cid, "\n".join(lines) + "\n")
                last = time.time()
            elif time.time() - last > 20:         # keep proxies and clients from timing out a 10-20 minute task
                yield ": keep-alive\n\n"
                last = time.time()
        lines, seen = _progress(run, seen)
        try:
            meta = fut.result()
        except Exception as e:                    # infrastructure failure outside run_task's own handling
            meta = {**run.meta, "status": "error", "reason": f"{type(e).__name__}: {e}"}
        yield _chunk(cid, ("\n".join(lines) + "\n" if lines else "") + "\n" + _result(meta, repo))
        yield _chunk(cid, finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
