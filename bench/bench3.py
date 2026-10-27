#!/usr/bin/env python3
"""Overnight workflow search: can extra cycles / error checking push the true-pass rate to ~90%?
Stages (all adaptive, resumable, pausable; ~8 h budget starting when the first job actually runs):
  W1T  tune     W0 baseline vs +hints vs +cascade vs big-only cascade (+ verify on the better cascade), 10 tasks, rep 1
  W1H  holdout  baseline + top-2 workflows on 8 UNSEEN tasks (t14-t21), then a 2nd repetition of baseline + best
  W1C  confirm  best workflow once more on the tuning tasks + the 3 easy ones
Start paused by creating ~/orch-bench/PAUSE first; resume.sh begins the run and starts the clock.
BENCH3_SMOKE=1 runs a tiny GPU smoke test of the new workflow options (3 jobs)."""
import os, sys, time

sys.path.insert(0, os.path.expanduser("~/orch-bench"))
import bench
from bench import Task, cfg, run_jobs, set_phase, log, sh, B, load_rows, jload, STATE, PAUSE, by_config

SMOKE = os.environ.get("BENCH3_SMOKE") == "1"
HOURS = float(os.environ.get("BENCH3_HOURS", "8"))
OSS, QC, ORN, E4B = ("big131", "gpt-oss:20b"), ("big131", "qwen3-coder:30b"), ("big131", "ornith:35b"), ("gamebed", "gemma4:e4b")
TUNE = ["t3", "t9", "t10", "t4", "t5", "t6", "t11", "t12", "t7", "t13"]
EASY = ["t1", "t2", "t8"]
HOLD = ["t14", "t15", "t16", "t17", "t18", "t19", "t20", "t21"]
if SMOKE:
    TUNE, EASY, HOLD = ["t1"], [], []

W0 = cfg("W0 baseline (e4b draft, gpt-oss review, qwen3-coder repairs)", coder=E4B, reasoner=OSS, repair=QC)
W1 = cfg("W1 baseline + language hints", coder=E4B, reasoner=OSS, repair=QC, hints=True)
W2 = cfg("W2 hints + cascade e4b>qwen3c>ornith>gptoss", coder=E4B, reasoner=OSS, hints=True, cascade=[E4B, QC, ORN, OSS])
W3 = cfg("W3 big-only cascade qwen3c>ornith>gptoss", coder=QC, reasoner=OSS, hints=True, cascade=[QC, ORN, OSS])
CONFIGS = {c["name"]: c for c in (W0, W1, W2, W3)}
if SMOKE:
    W3v = dict(W3, name="W4 smoke big-only cascade + verify", verify=True)
    CONFIGS[W3v["name"]] = W3v


def start_time():
    p = B / "t0_w"
    if not p.exists():
        p.write_text(str(time.time()))
    return float(p.read_text())


def score(rows, names, phase, tasks=None):
    """[(true passes, -avg seconds, name)] best first, for configs among `names` on rows of `phase`."""
    out = []
    for n in names:
        rs = [r for r in rows if r["phase"] == phase and r["config"] == n and (tasks is None or r["task"] in tasks)]
        if rs:
            out.append((sum(r["true_pass"] for r in rs) / len(rs), -sum(r["elapsed"] for r in rs) / len(rs), n))
    return [n for _, _, n in sorted(out, reverse=True)]


def main():
    set_phase("W1 waiting to start")
    if PAUSE.exists():
        log("W1: starting paused - waiting for resume.sh (the clock starts when it is resumed)")
        while PAUSE.exists():
            time.sleep(15)
    t0 = start_time()
    end = t0 + HOURS * 3600
    bench.HARD = end + 3 * 3600

    def dl(frac_hours):   # stage deadline = start + offset, shifted by any time spent paused
        return min(end, t0 + frac_hours * 3600) + bench.PAUSED_S

    set_phase("W1 tune")
    run_jobs([Task("W1T", c, t) for c in (W0, W1, W2, W3) for t in TUNE], dl(0.5 if SMOKE else 4.0), "W1 tune")

    rows = load_rows()
    casc = score(rows, [W2["name"], W3["name"]], "W1T")
    if casc:
        base = CONFIGS[casc[0]]
        W4 = dict(base, name=f"W4 {base['name'].split()[0]} + verify (extra tests)", verify=True)
        CONFIGS[W4["name"]] = W4
        run_jobs([Task("W1T", W4, t) for t in TUNE], dl(0.7 if SMOKE else 4.8), "W1 tune verify")
    rows = load_rows()
    ranked = score(rows, [n for n in CONFIGS if not n.startswith("W0")], "W1T")
    finalists = ranked[:2]
    set_phase("W1 holdout", tune_ranking=ranked, finalists=finalists)
    if not HOLD:
        set_phase("DONE")
        sh([sys.executable, str(B / "report.py")])
        log("workflow search complete (smoke)")
        return

    hold_cfgs = [W0] + [CONFIGS[n] for n in finalists]
    # task-major so every workflow gets the same tasks first; a time cap then cannot starve the candidates
    run_jobs([Task("W1H", c, t) for t in HOLD for c in hold_cfgs], dl(HOURS), "W1 holdout rep1")
    rows = load_rows()
    hranked = score(rows, [c["name"] for c in hold_cfgs[1:]], "W1H")
    winner = CONFIGS[hranked[0]] if hranked else (CONFIGS[finalists[0]] if finalists else W0)
    set_phase("W1 holdout rep2", winner=winner["name"])
    run_jobs([Task("W1H", c, t, 2) for t in HOLD for c in (W0, winner)], dl(HOURS - 0.25), "W1 holdout rep2")
    set_phase("W1 confirm", winner=winner["name"])
    run_jobs([Task("W1C", winner, t) for t in TUNE + EASY], dl(HOURS), "W1 confirm")
    set_phase("DONE")
    sh([sys.executable, str(B / "report.py")])
    log("workflow search complete")


if __name__ == "__main__":
    main()
