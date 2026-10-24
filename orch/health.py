"""Explicit primary/backup alias selection (LiteLLM does not do this for role-pinned aliases)."""
from __future__ import annotations

import httpx

from .config import S


def worker_up(base: str, timeout: float = 3.0) -> bool:
    # /api/tags does not load a model, so this never evicts a warm one.
    try:
        return httpx.get(f"{base}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def pick_alias(role: str) -> str:
    candidates = S.reasoner_candidates if role == "reasoner" else S.coder_candidates
    for alias, base in candidates:
        if worker_up(base):
            return alias
    raise RuntimeError(f"no healthy worker for role '{role}': {[b for _, b in candidates]}")


def status() -> dict:
    out = {}
    for role, cands in (("reasoner", S.reasoner_candidates), ("coder", S.coder_candidates)):
        out[role] = [{"alias": a, "host": b, "up": worker_up(b)} for a, b in cands]
    return out
