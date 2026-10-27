"""Host health and failover. Every role names a home host; when that host is down the role moves to the first host in
ORCH_FALLBACK_HOSTS that is up and has the model, and moves back as soon as the home host answers again. Hosts are
re-checked on every model call (cached for a few seconds), so a machine going down mid-task is noticed at the next call.
A gaming machine is taken out of use by stopping its Ollama service: an unreachable API is the "do not use" signal."""
from __future__ import annotations

import threading
import time

import httpx

from .config import S

_TTL = 5.0
_cache: dict[str, tuple[float, set | None]] = {}
_events: list[dict] = []
_active: dict[tuple[str, str], str] = {}
_lock = threading.Lock()


def _norm(base: str) -> str:
    return base.strip().rstrip("/")


def _models(base: str, timeout: float = 3.0) -> set | None:
    """Model names on an Ollama host, or None if it is down. /api/tags does not load a model, so it never evicts one."""
    with _lock:
        hit = _cache.get(base)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    try:
        r = httpx.get(f"{base}/api/tags", timeout=timeout)
        names = {m.get("name", "") for m in r.json().get("models", [])} if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        names = None
    with _lock:
        _cache[base] = (time.time(), names)
    return names


def worker_up(base: str, timeout: float = 3.0) -> bool:
    return _models(base, timeout) is not None


def _has(base: str, alias: str) -> bool:
    names = _models(base) or set()
    return alias in names or f"{alias}:latest" in names


def resolve(alias: str, home: str) -> str | None:
    """The host to use for `alias` right now: home if up (and, when other hosts could stand in, if it has the model),
    else a live fallback host that has the model, else None."""
    others = [o for o in S.fallback_hosts if _norm(o) != _norm(home)]
    if worker_up(home) and (not others or _has(home, alias)):
        return _note(alias, home, home)
    for other in others:
        if worker_up(other) and _has(other, alias):
            return _note(alias, home, other)
    return None


def _note(alias: str, home: str, using: str) -> str:
    """Record each move of an alias to another host (and back), so runs can report failovers."""
    with _lock:
        was = _active.get((alias, home), home)
        if was != using:
            _events.append({"alias": alias, "from": was, "to": using, "t": round(time.time())})
        _active[(alias, home)] = using
    return using


def failovers() -> list[dict]:
    with _lock:
        return list(_events)


def pick_alias(role: str) -> str:
    candidates = {"reasoner": S.reasoner_candidates, "repair_coder": S.repair_coder_candidates}.get(
        role, S.coder_candidates)
    for alias, base in candidates:
        if resolve(alias, base):
            return alias
    raise RuntimeError(f"no healthy worker for role '{role}': {[b for _, b in candidates]}")


def base_for(alias: str) -> tuple[str, str]:
    """(openai-compatible base url, api key) for an alias. Direct mode talks to Ollama's /v1, bypassing LiteLLM."""
    if S.direct:
        for cands in (S.reasoner_candidates, S.coder_candidates, S.repair_coder_candidates, S.cascade_candidates,
                      S.solvers):
            for a, url in cands:
                if a == alias:
                    return (resolve(a, url) or url).rstrip("/") + "/v1", "ollama"
    return S.llm_base, S.llm_key


def status() -> dict:
    out = {}
    for role, cands in (("reasoner", S.reasoner_candidates), ("coder", S.coder_candidates), ("solver", S.solvers)):
        out[role] = [{"alias": a, "host": b, "up": worker_up(b), "using": resolve(a, b)} for a, b in cands]
    return out
