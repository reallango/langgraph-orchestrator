"""Pipeline tests with the LLM and Aider faked. Run inside the container: `pytest -q`."""
import subprocess

import pytest

from orch import aider_runner, graph, health, llm
from orch.config import S
from orch.llm import extract_json


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t")
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    monkeypatch.setattr(S, "runs_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(health, "pick_alias", lambda role: role)
    return repo


def fake_llm(plan_files=("hello.txt",), review_verdict="pass"):
    def chat_json(alias, messages, retries=2):
        if "planner" in messages[0]["content"]:
            return {"summary": "s", "files_to_edit": list(plan_files), "context_files": [],
                    "steps": ["do it"], "acceptance_criteria": ["file says good"]}, "{}"
        return {"verdict": review_verdict, "findings": [{"criterion": "c", "problem": "p", "fix": "f"}]}, "{}"
    return chat_json


def fake_aider(contents):
    calls = {"n": 0}

    def run_aider(wt, alias, instruction, files, read_only, log_dir):
        text = contents[min(calls["n"], len(contents) - 1)]
        calls["n"] += 1
        (wt / "hello.txt").write_text(text)
        return 0, "ok"
    return run_aider


def test_happy_path(env, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["good\n"]))
    meta = graph.run_task(str(env), "make it good", ["grep -q good hello.txt"])
    assert meta["status"] == "passed" and meta["verified"] is True
    out = subprocess.run(["git", "show", f"{meta['branch']}:hello.txt"], cwd=env, capture_output=True, text=True)
    assert out.stdout == "good\n"
    assert not (env / "hello.txt").exists()  # user checkout untouched


def test_repair_cycle(env, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["bad\n", "good\n"]))
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"])
    assert meta["status"] == "passed" and meta["cycles"] == 1


def test_stops_on_repeated_failure(env, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["bad\n"]))
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"], max_repairs=5)
    assert meta["status"] == "failed" and "repeated" in meta["reason"]


def test_escalates_wide_plan(env, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm(plan_files=[f"f{i}.py" for i in range(S.max_files + 1)]))
    meta = graph.run_task(str(env), "t")
    assert meta["status"] == "escalated"


def test_reviewer_fail_triggers_repair_then_stops(env, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm(review_verdict="fail"))
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["good\n"]))
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"], max_repairs=3)
    assert meta["status"] == "failed"


def test_unverified_when_no_checks(env, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["good\n"]))
    meta = graph.run_task(str(env), "t")
    assert meta["status"] == "passed" and meta["verified"] is False


def test_extract_json_handles_fences_and_prose():
    assert extract_json('Sure!\n```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}
