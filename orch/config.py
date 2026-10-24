"""Runtime settings. Everything is overridable by environment variable."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    # LiteLLM (OpenAI-compatible) endpoint and virtual key
    llm_base: str = field(default_factory=lambda: _env("LITELLM_BASE_URL", "http://192.168.1.161:4000/v1"))
    llm_key: str = field(default_factory=lambda: _env("LITELLM_API_KEY", ""))
    llm_timeout: float = field(default_factory=lambda: float(_env("ORCH_LLM_TIMEOUT", "900")))

    # Ordered (alias, ollama_base_url) candidates per role. First healthy one wins.
    reasoner_candidates: list = field(default_factory=lambda: [
        ("reasoner", _env("HOST_REASONER", "http://192.168.1.15:11434")),
        ("reasoner-backup", _env("HOST_REASONER_BACKUP", "http://192.168.1.131:11434")),
    ])
    coder_candidates: list = field(default_factory=lambda: [
        ("coder-pro", _env("HOST_CODER", "http://192.168.1.131:11434")),
        ("coder-pro-backup", _env("HOST_CODER_BACKUP", "http://192.168.1.15:11434")),
    ])

    runs_dir: str = field(default_factory=lambda: _env("ORCH_RUNS_DIR", "/app/.orch-runs"))
    allowed_root: str = field(default_factory=lambda: _env("ORCH_ALLOWED_ROOT", "/app"))

    max_files: int = field(default_factory=lambda: int(_env("ORCH_MAX_FILES", "5")))
    max_repairs: int = field(default_factory=lambda: int(_env("ORCH_MAX_REPAIRS", "2")))
    check_timeout: int = field(default_factory=lambda: int(_env("ORCH_CHECK_TIMEOUT", "600")))
    aider_timeout: int = field(default_factory=lambda: int(_env("ORCH_AIDER_TIMEOUT", "1800")))
    context_chars: int = field(default_factory=lambda: int(_env("ORCH_CONTEXT_CHARS", "60000")))
    diff_chars: int = field(default_factory=lambda: int(_env("ORCH_DIFF_CHARS", "40000")))


S = Settings()
