"""Runtime settings. Everything is overridable by environment variable."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _candidates(name: str, default: list) -> list:
    """Role candidates as [[alias, ollama_base_url], ...], overridable via a JSON env var."""
    raw = os.environ.get(name)
    return [tuple(c) for c in json.loads(raw)] if raw else default


@dataclass
class Settings:
    # LiteLLM (OpenAI-compatible) endpoint and virtual key
    llm_base: str = field(default_factory=lambda: _env("LITELLM_BASE_URL", "http://192.168.1.161:4000/v1"))
    llm_key: str = field(default_factory=lambda: _env("LITELLM_API_KEY", ""))
    llm_timeout: float = field(default_factory=lambda: float(_env("ORCH_LLM_TIMEOUT", "900")))

    # Ordered (alias, ollama_base_url) candidates per role. First healthy one wins.
    # Override wholesale with ORCH_REASONER_CANDIDATES / ORCH_CODER_CANDIDATES (JSON list of [alias, url]).
    reasoner_candidates: list = field(default_factory=lambda: _candidates("ORCH_REASONER_CANDIDATES", [
        ("reasoner", _env("HOST_REASONER", "http://192.168.1.15:11434")),
        ("reasoner-backup", _env("HOST_REASONER_BACKUP", "http://192.168.1.131:11434")),
    ]))
    coder_candidates: list = field(default_factory=lambda: _candidates("ORCH_CODER_CANDIDATES", [
        ("coder-gamebed", _env("HOST_CODER_GAMEBED", "http://192.168.1.171:11434")),
        ("coder-pro", _env("HOST_CODER", "http://192.168.1.131:11434")),
        ("coder-pro-backup", _env("HOST_CODER_BACKUP", "http://192.168.1.15:11434")),
    ]))

    # Stronger coder used for repair cycles (after the cheap first attempt failed). Optional.
    repair_coder_candidates: list = field(default_factory=lambda: _candidates("ORCH_REPAIR_CODER_CANDIDATES", [
        ("coder-pro", _env("HOST_CODER", "http://192.168.1.131:11434")),
        ("coder-pro-backup", _env("HOST_CODER_BACKUP", "http://192.168.1.15:11434")),
    ]))

    # Hosts a role may move to when its own host is down (JSON list of Ollama base urls). Empty = no failover.
    fallback_hosts: list = field(default_factory=lambda: json.loads(_env("ORCH_FALLBACK_HOSTS", "[]")))

    # OpenAI-compatible front door (api.py): bearer key (empty = no auth) and the model id it advertises.
    api_key: str = field(default_factory=lambda: _env("ORCH_API_KEY", ""))
    api_model: str = field(default_factory=lambda: _env("ORCH_API_MODEL", "orch-consensus"))

    # Experiment switches. direct=1 calls Ollama's /v1 on each candidate's host (aliases are Ollama model names).
    direct: bool = field(default_factory=lambda: _env("ORCH_DIRECT", "0") == "1")
    use_planner: bool = field(default_factory=lambda: _env("ORCH_PLANNER", "1") == "1")
    use_reviewer: bool = field(default_factory=lambda: _env("ORCH_REVIEWER", "1") == "1")
    diagnose: bool = field(default_factory=lambda: _env("ORCH_DIAGNOSE", "0") == "1")

    # Workflow options (all off by default)
    hints: bool = field(default_factory=lambda: _env("ORCH_HINTS", "0") == "1")          # language pitfall notes in coder prompts
    verify: bool = field(default_factory=lambda: _env("ORCH_VERIFY", "0") == "1")        # reasoner-written extra tests + adjudication
    cascade_candidates: list = field(default_factory=lambda: _candidates("ORCH_CASCADE_CODERS", []))  # ordered coders, fresh start each
    attempt_repairs: int = field(default_factory=lambda: int(_env("ORCH_ATTEMPT_REPAIRS", "1")))     # repairs per cascade attempt
    max_total: int = field(default_factory=lambda: int(_env("ORCH_MAX_TOTAL", "8")))                 # cap on total coder calls - 1

    # Consensus mode: two solvers work independently, cross-check with each other's spec-derived tests, and a
    # solution is accepted only when it passes the visible checks and every test both models consider valid.
    solvers: list = field(default_factory=lambda: _candidates("ORCH_SOLVERS", []))
    solver_repairs: int = field(default_factory=lambda: int(_env("ORCH_SOLVER_REPAIRS", "2")))        # per solver, visible checks
    consensus_repairs: int = field(default_factory=lambda: int(_env("ORCH_CONSENSUS_REPAIRS", "1")))  # after cross-testing

    # Aider edit format: "diff" (search/replace blocks) or "whole" (rewrite whole files; friendlier to weaker models)
    edit_format: str = field(default_factory=lambda: _env("ORCH_EDIT_FORMAT", "diff"))

    runs_dir: str = field(default_factory=lambda: _env("ORCH_RUNS_DIR", "/app/.orch-runs"))
    allowed_root: str = field(default_factory=lambda: _env("ORCH_ALLOWED_ROOT", "/app"))

    max_files: int = field(default_factory=lambda: int(_env("ORCH_MAX_FILES", "5")))
    max_repairs: int = field(default_factory=lambda: int(_env("ORCH_MAX_REPAIRS", "2")))
    check_timeout: int = field(default_factory=lambda: int(_env("ORCH_CHECK_TIMEOUT", "600")))
    aider_timeout: int = field(default_factory=lambda: int(_env("ORCH_AIDER_TIMEOUT", "420")))
    context_chars: int = field(default_factory=lambda: int(_env("ORCH_CONTEXT_CHARS", "60000")))
    diff_chars: int = field(default_factory=lambda: int(_env("ORCH_DIFF_CHARS", "40000")))


S = Settings()
