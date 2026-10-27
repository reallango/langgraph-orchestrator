#!/usr/bin/env python3
"""Round 2: single-pass screening of additional models, plus whole-file edit-format retests. Resumable and pausable.
Single pass = coder only (no planner/reviewer), max_repairs=0. Controls re-run the earlier winners the same way.
Pause: ~/orch-bench/pause.sh [--now]; resume: ~/orch-bench/resume.sh"""
import os, sys, time

sys.path.insert(0, os.path.expanduser("~/orch-bench"))
import bench
from bench import Prep, Task, cfg, run_jobs, set_phase, log, sh, B

SMOKE = os.environ.get("BENCH2_SMOKE") == "1"
TASKS = ["t1"] if SMOKE else ["t1", "t2", "t8", "t3", "t9", "t6"]
GB, BIG = "gamebed", "big131"

# (host, tag, edit_format)   controls first (already downloaded), then new models, then whole-format retests
BIG_RUNS = [
    (BIG, "ornith:35b", "diff"), (BIG, "gpt-oss:20b", "diff"), (BIG, "ornith:35b", "whole"),
    (BIG, "jetbrains/mellum2-instruct-q4_k_m", "diff"), (BIG, "lfm2.5:24b", "diff"), (BIG, "qwen3-coder:30b", "diff"),
    (BIG, "north-mini-code-1.0", "diff"), (BIG, "laguna-xs-2.1", "diff"), (BIG, "ornith-1.5:35b", "diff"),
    (BIG, "flint:40b", "diff"),
    (BIG, "gemma4:12b", "whole"), (BIG, "nemotron-3.5-lightning:30b", "whole"),
]
SMALL_RUNS = [
    (GB, "gemma4:e4b", "diff"), (GB, "gemma4:e4b", "whole"),
    (GB, "ornith-1.5:9b", "diff"), (GB, "nemotron-3.5-bolt:e4b", "diff"),
    (GB, "lfm2.5:8b", "whole"), (GB, "granite4.2:8b", "whole"),
]
if SMOKE:
    BIG_RUNS, SMALL_RUNS = [], [(GB, "gemma4:e4b", "diff"), (GB, "gemma4:e4b", "whole")]


def main():
    bench.HARD = time.time() + 7 * 3600     # the earlier 19 h budget is spent; this round gets its own window
    set_phase("R2 single-pass screening")
    runs = BIG_RUNS + SMALL_RUNS
    preps = [Prep(h, t) for h, t in dict.fromkeys((h, t) for h, t, _ in runs)]
    jobs = []
    for h, tag, edit in runs:
        c = cfg(f"R2|{h}|{tag}|{edit}", coder=(h, tag), planner=False, reviewer=False, edit=edit, repairs=0)
        jobs += [Task("R2", c, t) for t in TASKS]
    run_jobs(preps + jobs, time.time() + 5.5 * 3600, "R2")
    set_phase("DONE")
    sh([sys.executable, str(B / "report.py")])
    log("round 2 complete")


if __name__ == "__main__":
    main()
