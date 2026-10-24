"""Optional HTTP front door: `uvicorn orch.api:app --host 0.0.0.0 --port 8099`. One job at a time (GPUs are serial)."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .cli import check_repo_allowed
from .config import S
from .graph import run_task

app = FastAPI(title="orch")
pool = ThreadPoolExecutor(max_workers=1)


class RunRequest(BaseModel):
    repo: str
    task: str
    checks: list[str] = []
    files: list[str] = []
    max_repairs: int | None = None


@app.post("/runs")
def submit(req: RunRequest):
    repo = check_repo_allowed(req.repo)
    pool.submit(run_task, repo, req.task, req.checks, req.files, req.max_repairs)
    return {"queued": True}


@app.get("/runs")
def list_runs():
    out = []
    for p in sorted(Path(S.runs_dir).glob("*/run.json"), reverse=True)[:50]:
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    p = Path(S.runs_dir) / Path(run_id).name / "run.json"
    if not p.is_file():
        raise HTTPException(404)
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    from . import health as h
    return h.status()
