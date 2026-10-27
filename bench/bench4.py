#!/usr/bin/env python3
"""Daytime run: two-agent consensus vs last night's best workflow (W4, now with the lint fix). Resumable and pausable.
  C1   consensus: gpt-oss:20b on AtomEve and qwen3-coder:30b on the 3080 Ti solve independently, cross-test, agree
  W4R  W4 rerun: big-only cascade qwen3-coder > ornith > gpt-oss with verification, all on the 3080 Ti
Both run task-major on the same 18 tasks (10 tuning + 8 holdout) so a deadline cuts them equally.
If time is left: C2 = consensus with ornith:35b as the 3080 Ti solver, on the holdout tasks.
Env: BENCH4_UNTIL = unix time to stop launching jobs.  BENCH4_SMOKE=1 = 1 task per config."""
import os, sys, time

sys.path.insert(0, os.path.expanduser("~/orch-bench"))
import bench
from bench import Prep, Task, cfg, run_jobs, set_phase, log, sh, B

SMOKE = os.environ.get("BENCH4_SMOKE") == "1"
UNTIL = float(os.environ.get("BENCH4_UNTIL", time.time() + 4 * 3600))
OSS_AE, QC_AE = ("atomeve", "gpt-oss:20b"), ("atomeve", "qwen3-coder:30b")
OSS, QC, ORN = ("big131", "gpt-oss:20b"), ("big131", "qwen3-coder:30b"), ("big131", "ornith:35b")
TUNE = ["t3", "t9", "t10", "t4", "t5", "t6", "t11", "t12", "t7", "t13"]
HOLD = ["t14", "t15", "t16", "t17", "t18", "t19", "t20", "t21"]
TASKS = ["t1"] if SMOKE else HOLD + TUNE          # holdout first: those are the honest numbers

C1 = cfg("C1 consensus gpt-oss(AtomEve) + qwen3-coder(3080Ti)", coder=OSS_AE, reasoner=OSS_AE, reviewer=False,
         solvers=[OSS_AE, QC])
W4R = cfg("W4R big-only cascade + verify (lint fixed)", coder=QC, reasoner=OSS, hints=True, verify=True,
          cascade=[QC, ORN, OSS])
C2 = cfg("C2 consensus gpt-oss(AtomEve) + ornith(3080Ti)", coder=OSS_AE, reasoner=OSS_AE, reviewer=False,
         solvers=[OSS_AE, ORN])


def main():
    bench.HARD = UNTIL + 3600
    set_phase("C1 consensus vs W4R")
    preps = [Prep("atomeve", "gpt-oss:20b")]
    jobs = [Task("C1R", c, t) for t in TASKS for c in (C1, W4R)]
    run_jobs(preps + jobs, UNTIL, "consensus vs W4R")
    if not SMOKE and time.time() < UNTIL - 30 * 60:
        set_phase("C2 consensus with ornith")
        run_jobs([Task("C1R", C2, t) for t in HOLD], UNTIL, "C2")
    set_phase("DONE")
    sh([sys.executable, str(B / "report.py")])
    log("consensus run complete")


if __name__ == "__main__":
    main()
