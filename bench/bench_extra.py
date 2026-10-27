#!/usr/bin/env python3
"""Phase P5: confirmation runs for gpt-oss:20b in more roles. Reuses bench.py (corpus, scoring, scheduler). Resumable."""
import os, sys, time

sys.path.insert(0, os.path.expanduser("~/orch-bench"))
import bench
from bench import Task, cfg, run_jobs, set_phase, log, FULL, HARD, sh, B

OSS = ("big131", "gpt-oss:20b")
SMALL = ("gamebed", "gemma4:e4b")

CONFIGS = [
    cfg("G1 gpt-oss all roles (16GB alone)", coder=OSS, reasoner=OSS),
    cfg("G2 gpt-oss coder only (16GB alone)", coder=OSS, planner=False, reviewer=False),
    cfg("G3 F5 with gpt-oss reviewer+repair", coder=SMALL, reasoner=OSS, repair=OSS),
]


def main():
    set_phase("P5 confirmation (gpt-oss roles)")
    deadline = min(HARD - 30 * 60, time.time() + 4.5 * 3600)
    for rep in (1, 2):
        jobs = [Task("P5", c, t, rep) for c in CONFIGS for t in FULL]
        run_jobs(jobs, deadline, f"P5 rep{rep}")
    set_phase("DONE")
    sh([sys.executable, str(B / "report.py")])
    log("extra phase complete")


if __name__ == "__main__":
    main()
