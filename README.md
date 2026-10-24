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

Optional HTTP API: `uvicorn orch.api:app --host 0.0.0.0 --port 8099`.

## Delegating from Claude Code

See `CLAUDE-SNIPPET.md`.
