# LangGraph Orchestrator

Local plan / code / check / review pipeline on top of LiteLLM + Ollama, built to take mechanical work off Claude.

```
preflight -> plan (reasoner) -> code (Aider, coder-pro) -> check -> review (reasoner)
                                   ^                          |
                                   +---- repair_gate <--------+   bounded, stops on repeated findings
```

- **Never touches your checkout.** Work happens in a git worktree on branch `orch/<run-id>`.
- **Explicit failover.** `reasoner`/`coder-pro` fall back to `-backup` aliases based on Ollama `/api/tags` health.
- **Edits, not tool calls.** Aider diff format; 14B models are unreliable at multi-step tool use.
- **Escalates** instead of guessing: plans over `ORCH_MAX_FILES` (5) files, no-op coder, or repeated findings.
- **Honest results:** `passed` with no checks is flagged `verified: false`.
- **Audit trail** per run in `$ORCH_RUNS_DIR/<run-id>/` (prompts, responses, aider output, check output, `summary.md`, `run.json`).

## Build and run

    docker build -t langgraph-orchestrator:latest .
    docker run -d --name aider \
      -e LITELLM_BASE_URL=http://192.168.1.161:4000/v1 \
      -e LITELLM_API_KEY=<dedicated virtual key: coder-pro, coder-pro-backup, reasoner, reasoner-backup> \
      -v /srv/shared/projects:/app \
      -v $(pwd):/opt/orch \
      -e PYTHONPATH=/opt/orch \
      langgraph-orchestrator:latest sleep infinity

(Better: `COPY orch /opt/orch/orch` in the Dockerfile and rebuild.)

## Use

    docker exec aider python -m orch health
    docker exec aider python -m orch run --repo /app/myproj \
      --task "Add -Verbose support to Get-Thing.ps1" \
      --files scripts/Get-Thing.ps1 \
      --check "pwsh -NoProfile -Command Invoke-Pester -CI"

Exit code: 0 passed, 1 failed/error, 2 escalated. Review with `git -C /app/myproj diff main...orch/<run-id>`,
merge or discard, then `git worktree remove --force <run>/work`.

Auto checks on changed files: `py_compile` for `.py`, PSScriptAnalyzer (Error/Warning) for `.ps1/.psm1/.psd1`.

## Tests

    docker exec aider sh -c 'cd /opt/orch && pytest -q'

## Default deployment: `orch-api` (OpenAI-compatible)

`deploy/run-orch-api.sh` (run on ai-nuc from `~/orch-dev`) builds `langgraph-orchestrator:api` and starts container
`orch-api` on network `ainet`, port 8099, with the default workflow in `deploy/orch-api.env`: consensus of
ornith:35b + qwen3-coder:30b, planner gpt-oss:20b, failover between the 3080 Ti (.131) and AtomEve (.15).
A machine whose Ollama service is stopped is simply not used.

- OpenAI base URL: `http://orch-api:8099/v1` from containers on `ainet` (Open WebUI), `http://192.168.1.161:8099/v1`
  on the LAN. Model id `orch-consensus`. Bearer key: `~/orch-api/api-key` on ai-nuc.
- A chat is a design discussion with the planner (gpt-oss), which reads the files named at the top of a message:
  `repo:` (git repo under `/srv/shared/projects`), optional `files:` and `check:` lines. Then, as the last line of a
  message:
  - `review`: the planner writes the task description and each coding model (ornith, qwen3-coder) gives its view
    (best option, risks, ambiguities). Nothing is coded; discuss the feedback and `review` again if you like.
  - `go`: the planner turns the whole discussion (including review feedback) into the task and the consensus
    pipeline codes it. A first message ending in `go` runs as written (handy for scripts).
- A run's reply streams progress and ends with the result, branch `orch/<run-id>` and its diff stat. Nothing is
  merged. Failed runs say to hand the task to Claude.
- Open WebUI's own background prompts (titles, tags; they start with `### Task:`) go straight to the planner.
- `GET /health` shows which host each role is using right now. Runs are audited in `~/orch-api/runs/<run-id>/`.
- Native API on the same port: `POST /runs`, `GET /runs`, `GET /runs/{id}`.

## Delegating from Claude Code

See `CLAUDE-SNIPPET.md`.
