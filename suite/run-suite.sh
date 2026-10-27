#!/bin/bash
# Usage: run-suite.sh [t1 t2 ...]   Runs each task through the orchestrator and records results.
B=${ORCH_B:-~/orch-tests}
IMG=langgraph-orchestrator:orch-test
TESTS=${@:-t1 t2 t3 t4 t5 t6 t7}
LOG=$B/results/suite.log
: > $LOG
for t in $TESTS; do
  checks=()
  while IFS= read -r l; do [ -n "$l" ] && checks+=(--check "$l"); done < $B/spec/$t/check.txt
  start=$(date +%s)
  echo "[$(date +%T)] $t start" >> $LOG
  docker run --rm --env-file ~/orch.env \
    -e ORCH_RUNS_DIR=/runs -e ORCH_AIDER_TIMEOUT=900 -e ORCH_CHECK_TIMEOUT=240 \
    -v ~/orch-dev/orch:/opt/orch/orch:ro -v $B/work:/app -v $B/runs:/runs $IMG \
    python -m orch run --repo /app/$t --files $(cat $B/spec/$t/files.txt) "${checks[@]}" \
    --task "$(cat $B/spec/$t/task.txt)" > $B/results/$t.json 2> $B/results/$t.err
  rc=$?
  el=$(( $(date +%s) - start ))
  st=$(jq -r '.status' $B/results/$t.json 2>/dev/null || echo "?")
  cy=$(jq -r '.cycles' $B/results/$t.json 2>/dev/null || echo "?")
  br=$(jq -r '.branch' $B/results/$t.json 2>/dev/null || echo "")
  rs=$(jq -r '.reason' $B/results/$t.json 2>/dev/null | cut -c1-120)
  [ -n "$br" ] && [ "$br" != null ] && git -C $B/work/$t diff main...$br > $B/results/$t.diff 2>/dev/null
  echo "[$(date +%T)] $t done rc=$rc status=$st repairs=$cy elapsed=${el}s reason=$rs" >> $LOG
done
echo "ALL DONE" >> $LOG
