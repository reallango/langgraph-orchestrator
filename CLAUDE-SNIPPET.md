## Local offload (add to a project's CLAUDE.md)

A local agent pipeline can take well-specified work off Claude. It runs on a home GPU cluster and
works on its own git branch; nothing lands in the working tree.

Delegate when the task is mechanical, touches at most ~5 files, and a command can verify it
(unit tests, boilerplate, docs, renames, small refactors, PSScriptAnalyzer-clean script changes).
Do NOT delegate ambiguous, cross-cutting, or security-sensitive work.

    ssh ai-nuc docker exec aider python -m orch run --repo /app/<proj> \
      --task "<precise task with acceptance criteria>" --files <relevant files> --check "<verify cmd>"

Always supply a `--check`. Exit 0 = passed, 1 = failed, 2 = escalated (do it yourself).
After it returns, review `git diff <base>...orch/<run-id>` before merging; treat the result as an
untrusted first draft. If `verified` is false, nothing was actually tested.
