"""Thin OpenAI-compatible client for LiteLLM, plus tolerant JSON extraction."""
from __future__ import annotations

import json
import re

import httpx

from .config import S

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.M)


def chat(alias: str, messages: list[dict], temperature: float = 0.2) -> str:
    r = httpx.post(
        f"{S.llm_base}/chat/completions",
        headers={"Authorization": f"Bearer {S.llm_key}"},
        json={"model": alias, "messages": messages, "temperature": temperature, "stream": False},
        timeout=S.llm_timeout,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"].get("content") or ""
    return _THINK.sub("", content).strip()


def extract_json(text: str) -> dict:
    """Return the first balanced JSON object in text. Raises ValueError if none parses."""
    text = _FENCE.sub("", text)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no valid JSON object found")


def chat_json(alias: str, messages: list[dict], retries: int = 2) -> tuple[dict, str]:
    """Chat and parse a JSON object, re-asking on malformed output. Returns (obj, raw_text)."""
    msgs = list(messages)
    raw = ""
    for _ in range(retries + 1):
        raw = chat(alias, msgs)
        try:
            return extract_json(raw), raw
        except ValueError:
            msgs += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That was not valid JSON. Reply with ONLY the JSON object, no prose."},
            ]
    raise ValueError(f"{alias} did not return valid JSON after {retries + 1} attempts:\n{raw[:500]}")
