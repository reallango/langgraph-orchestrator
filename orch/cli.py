"""CLI: `python -m orch run ...` and `python -m orch health`. Exit codes: 0 passed, 1 failed/error, 2 escalated."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import S

EXIT = {"passed": 0, "escalated": 2}


def check_repo_allowed(repo: str) -> str:
    p = Path(repo).resolve()
    root = Path(S.allowed_root).resolve()
    if root != p and root not in p.parents:
        raise SystemExit(f"repo {p} is outside ORCH_ALLOWED_ROOT ({root})")
    return str(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="plan -> code -> check -> review on a throwaway git branch")
    r.add_argument("--repo", required=True)
    r.add_argument("--task", required=True)
    r.add_argument("--check", action="append", default=[], help="shell command that must exit 0 (repeatable)")
    r.add_argument("--files", nargs="*", default=[], help="files the planner should read first")
    r.add_argument("--max-repairs", type=int, default=None)
    r.add_argument("--base-ref", default="HEAD")
    sub.add_parser("health", help="show which worker each role would use")
    args = ap.parse_args(argv)

    if args.cmd == "health":
        from . import health
        print(json.dumps(health.status(), indent=2))
        return 0

    if not S.llm_key:
        print("LITELLM_API_KEY is not set", file=sys.stderr)
        return 1
    from .graph import run_task
    meta = run_task(check_repo_allowed(args.repo), args.task, args.check, args.files,
                    args.max_repairs, args.base_ref)
    meta["run_dir"] = str(Path(S.runs_dir) / meta["id"])
    print(json.dumps(meta, indent=2))
    return EXIT.get(meta.get("status", "error"), 1)
