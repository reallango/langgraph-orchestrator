"""Edit engine: Aider in diff mode. The coder returns edits, not tool calls, which 14B models handle far better."""
from __future__ import annotations

import os
from pathlib import Path

from .config import S
from .repo import sh


def run_aider(wt: Path, alias: str, instruction: str, files: list[str], read_only: list[str],
              log_dir: Path, base: str | None = None, key: str | None = None) -> tuple[int, str]:
    cmd = [
        "aider",
        "--model", f"openai/{alias}",
        "--edit-format", S.edit_format,
        "--yes-always", "--no-auto-commits", "--no-stream", "--no-pretty",
        "--no-check-update", "--no-analytics", "--no-show-model-warnings", "--no-gitignore",
        "--no-suggest-shell-commands", "--map-tokens", "1024",
        "--chat-history-file", str(log_dir / "aider.chat.md"),
        "--input-history-file", str(log_dir / "aider.input"),
        "--llm-history-file", str(log_dir / "aider.llm.log"),
        "--message", instruction,
    ]
    for r in read_only:
        cmd += ["--read", r]
    cmd += files
    # Key goes via env, not argv, so it doesn't show up in `ps`.
    env = {**os.environ, "OPENAI_API_BASE": base or S.llm_base, "OPENAI_API_KEY": S.llm_key if key is None else key}
    return sh(cmd, wt, timeout=S.aider_timeout, env=env)
