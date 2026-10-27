"""Thin OpenAI-compatible client (LiteLLM or Ollama's /v1), plus tolerant JSON extraction."""
from __future__ import annotations

import json
import re

import httpx

from .config import S

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.M)


def chat(alias: str, messages: list[dict], temperature: float = 0.2,
         base: str | None = None, key: str | None = None) -> str:
    r = httpx.post(
        f"{base or S.llm_base}/chat/completions",
        headers={"Authorization": f"Bearer {S.llm_key if key is None else key}"},
        json={"model": alias, "messages": messages, "temperature": temperature, "stream": False},
        timeout=S.llm_timeout,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"].get("content") or ""
    return _THINK.sub("", content).strip()


def chat_stream(alias: str, messages: list[dict], temperature: float = 0.3,
                base: str | None = None, key: str | None = None):
    """Yield the answer text as it is generated. Reasoning (Ollama's `reasoning` field or <think> blocks) is dropped."""
    body = {"model": alias, "messages": messages, "temperature": temperature, "stream": True}
    with httpx.stream("POST", f"{base or S.llm_base}/chat/completions", json=body, timeout=S.llm_timeout,
                      headers={"Authorization": f"Bearer {S.llm_key if key is None else key}"}) as r:
        r.raise_for_status()
        thinking, buf = False, ""
        for line in r.iter_lines():
            if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                continue
            try:
                buf += json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
            except (ValueError, KeyError, IndexError):
                continue
            while buf:                        # strip <think>...</think>, holding back a tag split across chunks
                tag = "</think>" if thinking else "<think>"
                at = buf.find(tag)
                if at >= 0:
                    if not thinking and at:
                        yield buf[:at]
                    thinking, buf = not thinking, buf[at + len(tag):]
                    continue
                keep = next((n for n in range(len(tag) - 1, 0, -1) if buf.endswith(tag[:n])), 0)
                if not thinking and len(buf) > keep:
                    yield buf[:len(buf) - keep]
                buf = buf[len(buf) - keep:] if keep else ""
                break
        if buf and not thinking:
            yield buf


_BAD_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


def _loads(candidate: str) -> dict:
    """json.loads, retrying with stray backslashes (regexes like \\w that models put in strings) escaped."""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(_BAD_ESCAPE.sub(r"\\\\", candidate))


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
                        return _loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no valid JSON object found")


def chat_json(alias: str, messages: list[dict], retries: int = 2,
              base: str | None = None, key: str | None = None) -> tuple[dict, str]:
    """Chat and parse a JSON object, re-asking on malformed output. Returns (obj, raw_text)."""
    msgs = list(messages)
    raw = ""
    for _ in range(retries + 1):
        raw = chat(alias, msgs, base=base, key=key)
        try:
            return extract_json(raw), raw
        except ValueError:
            msgs += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That was not valid JSON. Reply with ONLY the JSON object, no prose."},
            ]
    raise ValueError(f"{alias} did not return valid JSON after {retries + 1} attempts:\n{raw[:500]}")
