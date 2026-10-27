#!/usr/bin/env python3
"""Overnight run on the 3080 Ti alone (AtomEve is not used). Resumable and pausable.
  S1F  failover check: the planner/solver role whose home host is down moves to the 3080 Ti
  TS   TypeScript pilot on 5 Bosun tasks: S1 vs W4R, 2 reps each
  S1R  S1 on the 18 Python/PowerShell tasks (compare with last run's C1 = same pair on two GPUs, and W4R)
  S2   consensus with ornith:35b + qwen3-coder (the planned hybrid's agents) on TS + holdout, if time is left
  S1C  second rep of S1 on the holdout, if time is left
S1 = consensus gpt-oss:20b + qwen3-coder:30b taking turns on one GPU (planner gpt-oss).
Env: BENCH5_UNTIL = unix time to stop launching jobs (wall clock; pausing does NOT extend it).  BENCH5_SMOKE=1."""
import json, os, sys, time

sys.path.insert(0, os.path.expanduser("~/orch-bench"))
import bench
from bench import Task, cfg, run_jobs, set_phase, log, sh, B, HOSTS

SMOKE = os.environ.get("BENCH5_SMOKE") == "1"
UNTIL = float(os.environ.get("BENCH5_UNTIL", time.time() + 8 * 3600))
OSS, QC, ORN = ("big131", "gpt-oss:20b"), ("big131", "qwen3-coder:30b"), ("big131", "ornith:35b")
TS = ["ts1", "ts2", "ts3", "ts4", "ts5"]
TUNE = ["t3", "t9", "t10", "t4", "t5", "t6", "t11", "t12", "t7", "t13"]
HOLD = ["t14", "t15", "t16", "t17", "t18", "t19", "t20", "t21"]
DEAD = "http://192.168.1.131:11999"          # nothing listens here: stands in for "AtomEve is down"
G131 = HOSTS["big131"]

S1 = cfg("S1 consensus gpt-oss + qwen3-coder, one GPU", coder=OSS, reasoner=OSS, reviewer=False, solvers=[OSS, QC])
S1F = dict(cfg("S1F failover: gpt-oss host down -> 3080Ti", coder=OSS, reasoner=OSS, reviewer=False, solvers=[OSS, QC]),
           env={"ORCH_REASONER_CANDIDATES": json.dumps([["bench-gpt-oss-20b", DEAD]]),
                "ORCH_SOLVERS": json.dumps([["bench-gpt-oss-20b", DEAD], ["bench-qwen3-coder-30b", G131]]),
                "ORCH_FALLBACK_HOSTS": json.dumps([G131])})
W4R = cfg("W4R big-only cascade + verify (lint fixed)", coder=QC, reasoner=OSS, hints=True, verify=True,
          cascade=[QC, ORN, OSS])
S2 = cfg("S2 consensus ornith + qwen3-coder, one GPU", coder=ORN, reasoner=OSS, reviewer=False, solvers=[ORN, QC])


def main():
    bench.HARD = UNTIL            # wall-clock stop: the user needs the GPU back after lunch
    stages = [("S1F", [Task("S1F", S1F, t) for t in (["ts1"] if SMOKE else ["ts1", "t15"])]),
              ("TS", [Task("TS", c, t, rep) for rep in (1, 2) for t in TS for c in (S1, W4R)]),
              ("S1R", [Task("S1R", S1, t) for t in HOLD + TUNE]),
              ("S2", [Task("S2", S2, t) for t in TS + HOLD]),
              ("S1C", [Task("S1C", S1, t, 2) for t in HOLD])]
    if SMOKE:
        stages = stages[:1] + [("TS", [Task("TS", S1, "ts1")])]
    for name, jobs in stages:
        if time.time() > UNTIL - 15 * 60:
            log(f"== {name}: skipped, too close to the deadline")
            continue
        set_phase(name)
        run_jobs(jobs, UNTIL, name)
    set_phase("DONE")
    sh([sys.executable, str(B / "report.py")])
    log("3080 Ti overnight run complete")


if __name__ == "__main__":
    main()
