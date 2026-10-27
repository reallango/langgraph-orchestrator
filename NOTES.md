# Where we left off (2026-10-27)

Notes for the next session. The code lives on GitHub `reallango/langgraph-orchestrator` (PUBLIC repo) branch
`feat/orch-api` (pushed 2026-10-27 at the user's request; builds on `feat/orch-pipeline`; `main` is older, no PR
yet). Working copy: `~/orch-dev` on ai-nuc (lango@192.168.1.161), on `feat/orch-api` tracking origin. ai-nuc can
fetch (public) but has NO push credentials; pushing works from the user's Windows PC (Git Bash + gh signed in as
reallango; clone to a short path like %TEMP%\claude\lgo, the scratchpad path is too long for git). Ask before
pushing. Keep secrets out: the repo is public.

## What is deployed

- Container `orch-api` (image `langgraph-orchestrator:api`, `deploy/run-orch-api.sh`), port 8099, network `ainet`,
  runs as lango (uid 1000) so branches it creates stay editable on the host. OpenAI-compatible: `/v1/models`,
  `/v1/chat/completions` (streaming). Usage in README.md. API key in `~/orch-api/api-key` (never print it in chat).
- Default workflow (`deploy/orch-api.env`) = benchmark config S2: consensus ornith:35b + qwen3-coder:30b, planner
  gpt-oss:20b, no reviewer. Models are the `bench-*` variants (num_ctx 16384, num_predict 8192 thinking / 3072).
- Chat flow (added 2026-10-27 at the user's request): a chat is a discussion with the planner (it reads the
  `files:`); last line `review` = planner writes the task description and both coders give their views (no code);
  last line `go` = discussion + feedback become the task and consensus codes it. A first message ending in `go` runs
  as written. Open WebUI background prompts (`### Task:` titles/tags) go straight to the planner.
- REMOVED 2026-10-27 (user asked; they will remap Open WebUI etc. themselves): containers `litellm` and
  `orchestrator`. Kept for rollback: images `ghcr.io/berriai/litellm:main-latest`, `langgraph-orchestrator:latest`,
  config `/srv/appdata/litellm/config.yaml` (+ .bak), data `/srv/appdata/langgraph/`. They were plain `docker run`
  (no compose). Open WebUI's only connection was LiteLLM, so it needs orch-api added (Admin Settings >
  Connections > OpenAI: URL `http://orch-api:8099/v1`, key from the file) and Ollama/other models remapped by the
  user. redis/postgres/cloudflared/portainer untouched. bosun-preview / fake-server / agitated_raman belong to the
  Bosun overhaul session.

Verified 2026-10-27: 41 unit tests pass; live: 401 without key, model list, usage reply, outside-root repo refused,
Open WebUI container reaches orch-api, health shows failover to .131 with AtomEve off. Live GPU chat test on
ps-scripts/test-script.ps1 (3080 Ti, AtomEve off): discussion reply 45 s (38 s of it loading gpt-oss), `review` 101 s
(spec + ornith + qwen3-coder views, all sensible), no branch created, repo untouched.
NOT yet verified: `go` (a real coding run) through the API, and Open WebUI's own request timeout on a 10-20 min
streamed reply (we send keep-alive comments every 20 s; if Open WebUI cuts off, set AIOHTTP_CLIENT_TIMEOUT on it).

## Machines and rules

- .131 = the user's Windows PC (3080 Ti 16 GB, Ollama as NSSM service, models C:\Ollama). It's the default GPU.
- AtomEve .15 = son's PC (5070 Ti 16 GB). The user stops its Ollama service in gaming mode: API down = do not use.
  It has gpt-oss:20b and probably `bench-gpt-oss-20b` (prep.json has an atomeve|gpt-oss:20b entry; unconfirmed,
  AtomEve was off on 2026-10-27), but no qwen3-coder. So when up, the planner runs there and both solvers stay on
  .131 (taking turns); `curl localhost:8099/health` shows the live placement. Two-GPU mode (parallel solvers) needs,
  on AtomEve (the user runs it; remote writes there need the user): `ollama pull qwen3-coder:30b`, then
  POST /api/create `{"model":"bench-qwen3-coder-30b","from":"qwen3-coder:30b","parameters":{"num_ctx":16384,"num_predict":3072}}`
  (and if missing `{"model":"bench-gpt-oss-20b","from":"gpt-oss:20b","parameters":{"num_ctx":16384,"num_predict":8192}}`).
- game-bed .171 (RTX 3060 6 GB) is out of the coding loop. ai-laptop .130 excluded.
- Never touch GPUs while the user games; benchmark has `~/orch-bench/pause.sh` / `resume.sh` (PAUSE file).
- Keep check-ins infrequent (Team plan limits). No Claude review step in the workflow (user's decision).
- .131 once lost 74 of 75 files in C:\Ollama\bin (2026-10-26 08:48); restored from the verified zip. Watch for it.

## Results that chose the default (one GPU = 3080 Ti; ~/orch-bench/report.md, sections S1F/TS/S1R/S2/S1C)

| workflow | tasks | true pass | precision | avg/task |
|---|---|---|---|---|
| S2 consensus ornith + qwen3-coder | 8 holdout + 5 TS, 1 rep | 12/13 | 92% | 10 min |
| S1 consensus gpt-oss + qwen3-coder | 18 py/ps | 10/18 (= two-GPU C1) | 89% | 13 min |
| W4R cascade qwen3-coder > ornith > gpt-oss + verify | 5 TS x2 | 9/10 | 88% | 11 min |

Caveat: S2 was never run on the 10 tuning tasks and only once per task. ts3 was a false pass.

## Next test (agreed with the user: verify speed + success + that the option truly works)

1. Smoke through the real API: discuss + `review` + `go` on a small task (e.g. the ErrorLines change to
   ps-scripts/test-script.ps1 used in the chat test, or a scratch repo), ideally from Open WebUI itself. Check the
   branch, diff, cleanup of worktrees and `-b`/`-base` branches, and that the spec written at `go` reflects the
   discussion. Uses the 3080 Ti for ~10-15 min: ask before GPU use.
   Also measure whether `review` improves pass rate (e.g. bench a few tasks with and without a review step).
2. Confirmation run: S2 config on all 31 tasks (TUNE t3..t13, HOLD t14..t21, TS ts1..ts5), 2 reps. Easiest: copy
   bench5.py to bench6.py with stage S2 over TUNE+HOLD+TS x2 (configs S2 already defined) and supervise like
   supervise5.sh (deadline + PAUSE aware). ~10 h on one GPU; ~half with AtomEve if variants exist there.
   Better still for "the option truly works": drive some of the tasks through orch-api itself.
3. If AtomEve is available: repeat a few tasks in two-GPU mode (parallel solvers) to measure the speedup.

## Benchmark harness

- `~/orch-bench`: bench.py (engine, resumable, results.jsonl), bench2..5.py stages, supervise*.sh, report.py,
  corpus/ (t1..t21 py/ps, ts1..ts5 Bosun TS; visible check + hidden tests + reference solutions),
  validate-corpus.sh. Images: `orch-test` (py/ps), `orch-ts` (+Node 22, /opt/tsdeps typescript+vitest).
- Jobs mount `~/orch-dev/orch` read-only, so code fixes deploy by copying files there.
- SSH from the Windows PC mangles quotes/$: write a script locally and pipe it:
  `[IO.File]::ReadAllText("<file>") | ssh lango@192.168.1.161 "sed '1s/^\xEF\xBB\xBF//' | tr -d '\r' | bash -s"`.
- git is not on PATH on the Windows PC; do git work on ai-nuc.

## Fixed during the 2026-10-27 night (in this code)

- TS commits failed: `:(exclude)node_modules` pathspec errors when .gitignore ignores it -> moved to info/exclude.
- `repo.sh` timeouts left grandchildren running (looping pwsh at 300% CPU) -> own process group, killpg on timeout.

## Open items

- Ollama 500 from .131 on ts4 for W4R (both reps): not investigated.
- gpt-oss failed to return valid JSON 3x on t14 (planner role!): watch in the S2 confirmation.
- ps-scripts has untracked leftovers from the OLD aider setup (root-owned `.gitignore`, `.aider*`, Sept 16); not ours.
- Later: Docker/Playwright end-to-end testing; IIS/SQL testing design (needs stack details from
  the user); clean up losing models; push this repo to GitHub (ask first).
- Bosun (separate): branch `overhaul/responsive-multinode` on reallango/Bosun, pushed via deploy key
  `~/.ssh/bosun_deploy` (Host alias `github-bosun`) on ai-nuc. Clone: `~/ts-src/Bosun`.
