#!/bin/bash
# 3080 Ti overnight run. Stops launching jobs at 13:00 CDT on 2026-10-27 (pausing does not move that).
cd ~/orch-bench
UNTIL=$(date -d '2026-10-27 18:00 UTC' +%s)
while true; do
  BENCH_IMAGE=langgraph-orchestrator:orch-ts BENCH5_UNTIL=$UNTIL python3 bench5.py >> bench.out 2>&1
  ph=$(python3 -c "import json;print(json.load(open('state.json')).get('phase',''))" 2>/dev/null)
  case "$ph" in DONE|ABORTED*) echo "[$(date +%T)] supervisor5: finished ($ph)" >> bench.out; break;; esac
  [ "$(date +%s)" -gt "$UNTIL" ] && { echo "[$(date +%T)] supervisor5: past the deadline, stopping" >> bench.out; break; }
  echo "[$(date +%T)] supervisor5: exited in phase '$ph'; restarting in 60s" >> bench.out
  sleep 60
done
