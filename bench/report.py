#!/usr/bin/env python3
"""Builds report.md from results.jsonl / prep.json / state.json."""
import json, os
from collections import Counter, defaultdict
from pathlib import Path

B = Path(os.environ.get("BENCH_DIR", Path.home() / "orch-bench"))
rows = [json.loads(l) for l in (B / "results.jsonl").read_text().splitlines() if l.strip()] if (B / "results.jsonl").exists() else []
prep = json.loads((B / "prep.json").read_text()) if (B / "prep.json").exists() else {}
state = json.loads((B / "state.json").read_text()) if (B / "state.json").exists() else {}


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def table(prefix=None, phase=None, strip=0):
    d = defaultdict(list)
    for r in rows:
        if (phase is None or r["phase"] == phase) and (prefix is None or r["config"].startswith(prefix)):
            d[r["config"]].append(r)
    out = ["| config | n | TRUE pass | orch pass | precision* | false pass | false fail | avg s | avg repairs | tokens out/job | top failure labels |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    order = sorted(d.items(), key=lambda kv: (-sum(r["true_pass"] for r in kv[1]) / len(kv[1]), sum(r["elapsed"] for r in kv[1]) / len(kv[1])))
    for name, rs in order:
        n = len(rs)
        labs = Counter(l for r in rs for l in r["labels"] if l not in ("false_pass", "false_fail"))
        cyc = [r["cycles"] for r in rs if isinstance(r.get("cycles"), int)]
        out.append(f"| {name.split('|', strip)[-1] if strip else name} | {n} | {sum(r['true_pass'] for r in rs)} ({pct(sum(r['true_pass'] for r in rs), n)}) "
                   f"| {sum(r['status'] == 'passed' for r in rs)} | {pct(sum(r['true_pass'] and r['status'] == 'passed' for r in rs), sum(r['status'] == 'passed' for r in rs))} "
                   f"| {sum('false_pass' in r['labels'] for r in rs)} | {sum('false_fail' in r['labels'] for r in rs)} "
                   f"| {sum(r['elapsed'] for r in rs) // n} | {sum(cyc) / len(cyc):.1f} | {sum(r['tokens_recv'] for r in rs) // n} "
                   f"| {', '.join(f'{k}:{v}' for k, v in labs.most_common(3)) or '-'} |"
                   if cyc else f"| {name} | {n} | - | - | - | - | - | - | - | - | - |")
    return "\n".join(out)


def tier_table(phase):
    d = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["phase"] == phase:
            d[r["config"]][r["tier"]].append(r["true_pass"])
    tiers = ["T1", "T2", "T3", "T4"]
    out = ["| config | " + " | ".join(tiers) + " |", "|---|" + "---|" * len(tiers)]
    for name, t in sorted(d.items()):
        out.append(f"| {name} | " + " | ".join(f"{sum(t[x])}/{len(t[x])}" if t[x] else "-" for x in tiers) + " |")
    return "\n".join(out)


def lang_table(phase):
    d = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["phase"] == phase:
            d[r["config"]][r["lang"]].append(r["true_pass"])
    out = ["| config | python | powershell | typescript |", "|---|---|---|---|"]
    for name, t in sorted(d.items()):
        out.append(f"| {name} | " + " | ".join(f"{sum(t[x])}/{len(t[x])}" if t[x] else "-" for x in ("py", "ps", "ts")) + " |")
    return "\n".join(out)


L = ["# Local model benchmark report", "", f"Jobs run: {len(rows)}   true passes: {sum(r['true_pass'] for r in rows)}",
     "", "TRUE pass = visible check AND hidden tests both pass on the final branch, whatever the pipeline said. "
     "False pass = pipeline said passed but hidden tests fail. False fail = pipeline said failed but the code was actually right (e.g. reviewer rejected good work).",
     "Small samples: treat differences of one or two tasks as noise.", "", "## Selections", "```", json.dumps(state.get("picks", {}), indent=1), "```", "",
     "## Model preparation (speed and GPU fit)", "", "| host | model | size GB | thinking | GPU pinned | on-GPU fraction | tok/s | note |", "|---|---|---|---|---|---|---|---|"]
for k, v in sorted(prep.items()):
    L.append(f"| {v.get('host')} | {v.get('tag')} | {v.get('size_gb', '-')} | {v.get('thinking', '-')} | {v.get('forced', '-')} | {v.get('gpu_frac', '-')} | {v.get('tps', '-')} | "
             f"{'unusable: ' + str(v.get('error', 'did not load')) if not v.get('ok') else ('too slow' if v.get('too_slow') else '')} |")
L += ["", "## P1: coder alone (no planner/reviewer), screening tasks", "", "### 6 GB game-bed models", table("P1|gamebed|", strip=2),
      "", "### 16 GB .131 models", table("P1|big131|", strip=2),
      "", "## P2: adding a reasoner (planner + reviewer) in front of the best small coder", "", "### Reasoner on .131", table("P2|R131|", strip=2),
      "", "### Reasoner on game-bed (small-only)", table("P2|Rgb|", strip=2),
      "", "## P3: full corpus, finalist architectures", "", table(phase="P3"), "", "### By difficulty tier (true passes / tasks)", tier_table("P3"),
      "", "### By language", lang_table("P3"), ""]
for ph, title in (("S1F", "3080 Ti night: failover check (gpt-oss's host down, its roles move to the 3080 Ti)"),
                  ("TS", "3080 Ti night: TypeScript pilot on 5 Bosun tasks (2 reps)"),
                  ("S1R", "3080 Ti night: one-GPU consensus on the 18 Python/PowerShell tasks"),
                  ("S2", "3080 Ti night: consensus with ornith + qwen3-coder"),
                  ("S1C", "3080 Ti night: S1 again on the holdout (rep 2)"),
                  ("C1R","Consensus run: two agents agreeing vs W4 (lint fixed), same tasks interleaved"),
                  ("W1T", "W1 tune: workflow variants on 10 tasks (1 run each)"),
                  ("W1H", "W1 holdout: 8 tasks the workflows were never tuned on"),
                  ("W1C", "W1 confirmation: the winning workflow again")):
    if any(r["phase"] == ph for r in rows):
        L += [f"## {title}", "", "*precision = of the runs the workflow ACCEPTED (said passed), the share that really pass hidden tests; "
              "coverage = accepted / all runs (the orch pass column). A workflow with high precision can be trusted, and the rest can go to Claude.", "",
              table(phase=ph), "", "### By difficulty tier", tier_table(ph), "", "### By language", lang_table(ph), ""]
if any(r["phase"] == "R2" for r in rows):
    L += ["## R2: single-pass screening of more models (coder only, no repairs, 6 tasks)", "",
          "Config name = host | model | edit format. `whole` = Aider whole-file edits, `diff` = search/replace blocks. "
          "Controls (gemma4:e4b, ornith:35b, gpt-oss:20b) were re-run single-pass so numbers compare directly.", "",
          table(phase="R2"), "", "### By language", lang_table("R2"), ""]
if any(r["phase"] == "P5" for r in rows):
    L += ["## P5: confirmation runs (gpt-oss:20b in more roles; 13 tasks x 2 reps)", "", table(phase="P5"), "",
          "### By difficulty tier", tier_table("P5"), "", "### By language", lang_table("P5"), ""]
(B / "report.md").write_text("\n".join(L))
print("wrote", B / "report.md")
