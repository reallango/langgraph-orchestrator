#!/bin/bash
# (Re)build and (re)start the orch-api container on ai-nuc. Run from ~/orch-dev: ./deploy/run-orch-api.sh
# Leaves the old `orchestrator` and `litellm` containers alone. API key: ~/orch-api/api-key (created once, mode 600).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p ~/orch-api/runs
[ -s ~/orch-api/api-key ] || { umask 077; openssl rand -hex 24 > ~/orch-api/api-key; }
docker build -q -f deploy/Dockerfile.api -t langgraph-orchestrator:api . >/dev/null
docker rm -f orch-api >/dev/null 2>&1 || true
docker run -d --name orch-api --restart unless-stopped --network ainet -p 8099:8099 \
  --user "$(id -u):$(id -g)" \
  --env-file deploy/orch-api.env -e ORCH_API_KEY="$(cat ~/orch-api/api-key)" \
  -v /srv/shared/projects:/projects -v ~/orch-api/runs:/runs \
  langgraph-orchestrator:api >/dev/null
sleep 4
curl -s -m 5 localhost:8099/health
echo
