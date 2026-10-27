#!/bin/bash
# Pause the benchmark so the GPUs can be used for something else (e.g. gaming).
#   pause.sh        let any running job finish (up to ~20 min), start nothing new, then unload the models from VRAM
#   pause.sh --now  kill running jobs immediately (their results are discarded and re-run later), then unload
# Resume with ~/orch-bench/resume.sh. Nothing is lost either way.
B=~/orch-bench
touch $B/PAUSE
if [ "$1" = "--now" ]; then
  touch $B/PAUSE_NOW
  docker ps -q --filter name=orchbench | xargs -r docker kill >/dev/null
  sleep 5
else
  echo "waiting for running jobs to finish..."
  for i in $(seq 1 120); do
    [ "$(docker ps -q --filter name=orchbench | wc -l)" = 0 ] && break
    sleep 10
  done
fi
for h in 192.168.1.131 192.168.1.171; do
  for m in $(curl -s -m 5 http://$h:11434/api/ps | jq -r '.models[].name' 2>/dev/null); do
    curl -s -m 20 http://$h:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null
  done
  echo "$h: $(curl -s -m 5 http://$h:11434/api/ps | jq -r '[.models[].name] | length') models still loaded"
done
echo "PAUSED. GPUs are free. Resume with: ~/orch-bench/resume.sh"
