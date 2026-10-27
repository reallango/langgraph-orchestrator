#!/bin/bash
# Restarts bench3.py if it crashes; stops once the workflow search reports DONE. bench3.py is resumable.
cd ~/orch-bench
while true; do
  python3 bench3.py >> bench.out 2>&1
  ph=$(python3 -c "import json;print(json.load(open('state.json')).get('phase',''))" 2>/dev/null)
  case "$ph" in DONE|ABORTED*) echo "[$(date +%T)] supervisor3: finished ($ph)" >> bench.out; break;; esac
  echo "[$(date +%T)] supervisor3: exited in phase '$ph'; restarting in 60s" >> bench.out
  sleep 60
done
