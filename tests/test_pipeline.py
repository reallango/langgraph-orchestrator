"""Pipeline tests with the LLM and Aider faked. Run inside the container: `pytest -q`."""
import json
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
    def chat_json(alias, messages, retries=2, **kw):
        if "planner" in messages[0]["content"]:
            return {"summary": "s", "files_to_edit": list(plan_files), "context_files": [],
                    "steps": ["do it"], "acceptance_criteria": ["file says good"]}, "{}"
        return {"verdict": review_verdict, "findings": [{"criterion": "c", "problem": "p", "fix": "f"}]}, "{}"
    return chat_json


def fake_aider(contents):
    calls = {"n": 0}

    def run_aider(wt, alias, instruction, files, read_only, log_dir, **kw):
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


def test_repairs_use_repair_coder(env, monkeypatch):
    monkeypatch.setattr(S, "coder_candidates", [("cheap", "http://x")])
    monkeypatch.setattr(S, "repair_coder_candidates", [("strong", "http://y")])
    monkeypatch.setattr(health, "pick_alias", lambda role: {"coder": "cheap", "repair_coder": "strong"}.get(role, role))
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    seen, inner = [], fake_aider(["bad\n", "good\n"])

    def spy(wt, alias, *a, **k):
        seen.append(alias)
        return inner(wt, alias, *a, **k)
    monkeypatch.setattr(aider_runner, "run_aider", spy)
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"])
    assert meta["status"] == "passed" and seen == ["cheap", "strong"]


def test_coder_only_mode_makes_no_llm_calls(env, monkeypatch):
    monkeypatch.setattr(S, "use_planner", False)
    monkeypatch.setattr(S, "use_reviewer", False)

    def boom(*a, **k):
        raise AssertionError("reasoner must not be called")
    monkeypatch.setattr(llm, "chat_json", boom)
    monkeypatch.setattr(llm, "chat", boom)
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["good\n"]))
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"], hint_files=["README.md"])
    assert meta["status"] == "passed"


def test_diagnosis_is_fed_to_the_repair(env, monkeypatch):
    monkeypatch.setattr(S, "diagnose", True)
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "ROOT CAUSE: contents must be good")
    instructions = []
    inner = fake_aider(["bad\n", "good\n"])

    def spy(wt, alias, instruction, *a, **k):
        instructions.append(instruction)
        return inner(wt, alias, instruction, *a, **k)
    monkeypatch.setattr(aider_runner, "run_aider", spy)
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"])
    assert meta["status"] == "passed"
    assert "ROOT CAUSE" in instructions[1] and "ROOT CAUSE" not in instructions[0]


def _cascade(monkeypatch, names=("c1", "c2")):
    monkeypatch.setattr(S, "cascade_candidates", [(n, f"http://{n}") for n in names])
    monkeypatch.setattr(health, "worker_up", lambda *a, **k: True)
    monkeypatch.setattr(llm, "chat_json", fake_llm())


def test_cascade_restarts_from_scratch_with_next_coder(env, monkeypatch):
    _cascade(monkeypatch)
    calls = []

    def aider(wt, alias, instruction, *a, **k):
        calls.append((alias, (wt / "hello.txt").exists()))
        (wt / "hello.txt").write_text("good\n" if alias == "c2" else "bad\n")
        return 0, "ok"
    monkeypatch.setattr(aider_runner, "run_aider", aider)
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"])
    assert meta["status"] == "passed"
    # c1 first try, c1 repair (sees its own file), then c2 starts from the original files
    assert calls == [("c1", False), ("c1", True), ("c2", False)]


def test_cascade_exhausted_fails_cleanly(env, monkeypatch):
    _cascade(monkeypatch)
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["bad\n"]))
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"])
    assert meta["status"] == "failed" and "cascade coders failed" in meta["reason"]


def test_cascade_hands_over_when_a_coder_makes_no_edits(env, monkeypatch):
    _cascade(monkeypatch)
    seen = []

    def aider(wt, alias, *a, **k):
        seen.append(alias)
        if alias == "c2":
            (wt / "hello.txt").write_text("good\n")
        return 0, "ok"
    monkeypatch.setattr(aider_runner, "run_aider", aider)
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"])
    assert meta["status"] == "passed" and seen == ["c1", "c2"]


@pytest.mark.parametrize("on", [True, False])
def test_language_hints_only_when_enabled(env, monkeypatch, on):
    monkeypatch.setattr(S, "hints", on)
    monkeypatch.setattr(llm, "chat_json", fake_llm(plan_files=("x.ps1",)))
    texts = []
    inner = fake_aider(["good\n"])

    def spy(wt, alias, instruction, *a, **k):
        texts.append(instruction)
        return inner(wt, alias, instruction, *a, **k)
    monkeypatch.setattr(aider_runner, "run_aider", spy)
    meta = graph.run_task(str(env), "t", ["grep -q good hello.txt"])
    assert meta["status"] == "passed"
    assert ("PowerShell pitfalls" in texts[0]) is on


def _verify_llm(code_wrong):
    base = fake_llm(plan_files=("m.py",))

    def chat_json(alias, messages, retries=2, **kw):
        sysmsg = messages[0]["content"]
        if "extra verification tests" in sysmsg:
            return {"content": "def test_x():\n    assert 'good' in open('m.py').read()\n"}, "{}"
        if "Extra tests failed" in sysmsg:
            return {"code_wrong": code_wrong, "explanation": "m.py must contain good"}, "{}"
        return base(alias, messages, retries)
    return chat_json


def _m_aider(contents):
    calls = {"n": 0}

    def aider(wt, alias, instruction, *a, **k):
        (wt / "m.py").write_text(contents[min(calls["n"], len(contents) - 1)])
        calls["n"] += 1
        return 0, "ok"
    return aider


def test_verify_defect_triggers_a_repair(env, monkeypatch):
    monkeypatch.setattr(S, "verify", True)
    monkeypatch.setattr(llm, "chat_json", _verify_llm(True))
    monkeypatch.setattr(aider_runner, "run_aider", _m_aider(["bad\n", "good\n"]))
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "passed" and meta["cycles"] == 1
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", meta["branch"]], cwd=env,
                           capture_output=True, text=True).stdout.split()
    assert not any(f.startswith("_orch_extra") for f in files)


def test_verify_ignores_a_wrong_generated_test(env, monkeypatch):
    monkeypatch.setattr(S, "verify", True)
    monkeypatch.setattr(llm, "chat_json", _verify_llm(False))
    monkeypatch.setattr(aider_runner, "run_aider", _m_aider(["bad\n"]))
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "passed" and meta["cycles"] == 0


GOOD_TEST = "def test_m():\n    assert 'good' in open('m.py').read()\n"
WRONG_TEST = "def test_m():\n    assert 'nonsense' in open('m.py').read()\n"


def _consensus_env(monkeypatch, writes, tests=None, code_wrong=True):
    """writes: alias -> list of contents per call; tests: alias -> test file content."""
    tests = tests or {"sa": GOOD_TEST, "sb": GOOD_TEST}
    monkeypatch.setattr(S, "solvers", [("sa", "http://a"), ("sb", "http://b")])
    monkeypatch.setattr(health, "worker_up", lambda *a, **k: True)
    base = fake_llm(plan_files=("m.py",))

    def chat_json(alias, messages, retries=2, **kw):
        sysmsg = messages[0]["content"]
        if "You write tests for a programming TASK" in sysmsg:
            return {"content": tests[alias]}, "{}"
        if "A test file failed against a candidate solution" in sysmsg:
            return {"code_wrong": code_wrong, "explanation": "needs good"}, "{}"
        return base(alias, messages, retries)
    monkeypatch.setattr(llm, "chat_json", chat_json)
    calls = {}

    def aider(wt, alias, instruction, *a, **k):
        n = calls.get(alias, 0)
        calls[alias] = n + 1
        seq = writes[alias]
        (wt / "m.py").write_text(seq[min(n, len(seq) - 1)])
        return 0, "ok"
    monkeypatch.setattr(aider_runner, "run_aider", aider)
    return calls


def _branch_file(env, branch, path="m.py"):
    return subprocess.run(["git", "show", f"{branch}:{path}"], cwd=env, capture_output=True, text=True).stdout


def test_consensus_both_agree(env, monkeypatch):
    _consensus_env(monkeypatch, {"sa": ["good\n"], "sb": ["good\n"]})
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "passed"
    assert meta["consensus"]["outcome"] == "agree" and meta["consensus"]["winner"] == "A"


def test_consensus_adopts_the_other_solution_when_valid_tests_reject_one(env, monkeypatch):
    _consensus_env(monkeypatch, {"sa": ["bad\n"], "sb": ["good\n"]})
    monkeypatch.setattr(S, "consensus_repairs", 0)
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "passed" and meta["consensus"]["winner"] == "B"
    assert _branch_file(env, meta["branch"]) == "good\n"


def test_consensus_drops_a_test_both_models_call_wrong(env, monkeypatch):
    _consensus_env(monkeypatch, {"sa": ["good\n"], "sb": ["good\n"]},
                   tests={"sa": WRONG_TEST, "sb": GOOD_TEST}, code_wrong=False)
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "passed"
    assert meta["consensus"]["valid_tests"] == {"A": False, "B": True}


def test_consensus_repair_round_then_agree(env, monkeypatch):
    calls = _consensus_env(monkeypatch, {"sa": ["bad\n", "good\n"], "sb": ["bad\n", "good\n"]})
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "passed" and meta["consensus"]["outcome"].startswith("agree after 1")
    assert calls == {"sa": 2, "sb": 2}


def test_consensus_flags_when_no_solution_survives(env, monkeypatch):
    _consensus_env(monkeypatch, {"sa": ["bad\n"], "sb": ["bad\n"]})
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "failed" and "no consensus" in meta["reason"]


def test_consensus_on_one_host_takes_turns(env, monkeypatch):
    _consensus_env(monkeypatch, {"sa": ["good\n"], "sb": ["good\n"]})
    monkeypatch.setattr(S, "solvers", [("sa", "http://one"), ("sb", "http://one")])
    order = []
    inner_aider, inner_chat = aider_runner.run_aider, llm.chat_json
    monkeypatch.setattr(aider_runner, "run_aider", lambda wt, alias, *a, **k: order.append(alias) or inner_aider(wt, alias, *a, **k))
    monkeypatch.setattr(llm, "chat_json", lambda alias, m, *a, **k: (order.append(alias) if "TASK" in m[0]["content"] else None)
                        or inner_chat(alias, m, *a, **k))
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    assert meta["status"] == "passed" and meta["consensus"]["mode"] == "single-host"
    assert order == ["sa", "sa", "sb", "sb"]   # each model finishes its work before the GPU switches


def test_consensus_fails_over_to_the_surviving_host(env, monkeypatch):
    _consensus_env(monkeypatch, {"sa": ["good\n"], "sb": ["good\n"]})
    monkeypatch.setattr(S, "fallback_hosts", ["http://a", "http://b"])
    monkeypatch.setattr(health, "worker_up", lambda url, *a, **k: url != "http://b")
    monkeypatch.setattr(health, "_has", lambda url, alias: True)
    meta = graph.run_task(str(env), "t", ["test -f m.py"])
    c = meta["consensus"]
    assert meta["status"] == "passed" and c["mode"] == "single-host" and c["hosts"] == ["http://a", "http://a"]
    assert {"alias": "sb", "from": "http://b", "to": "http://a"}.items() <= c["failovers"][-1].items()


def test_resolve_moves_back_when_home_returns(monkeypatch):
    monkeypatch.setattr(S, "fallback_hosts", ["http://spare"])
    monkeypatch.setattr(health, "_has", lambda url, alias: True)
    up = {"http://home": False, "http://spare": True}
    monkeypatch.setattr(health, "worker_up", lambda url, *a, **k: up[url])
    assert health.resolve("m-back", "http://home") == "http://spare"
    up["http://home"] = True
    assert health.resolve("m-back", "http://home") == "http://home"
    up.update({"http://home": False, "http://spare": False})
    assert health.resolve("m-back", "http://home") is None
    moves = [(e["from"], e["to"]) for e in health.failovers() if e["alias"] == "m-back"]
    assert moves == [("http://home", "http://spare"), ("http://spare", "http://home")]


def test_typescript_tests_and_checks(tmp_path, monkeypatch):
    from orch import checks, langs
    lang = langs.detect(["src/lib/x.ts"])
    assert lang.name == "ts" and lang.test_file("A") == "_orch_extra_a.test.ts"
    shared = tmp_path / "shared_nm"
    (shared / ".bin").mkdir(parents=True)
    (shared / ".bin" / "tsc").write_text("")
    monkeypatch.setenv("ORCH_NODE_MODULES", str(shared))
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / "src" / "x.ts").write_text("export const x = 1;\n")
    (wt / "tsconfig.json").write_text("{}")
    assert lang.command(wt, "t.test.ts")[0] == "./node_modules/.bin/vitest"
    assert (wt / "node_modules").is_symlink()
    assert "typescript (tsc --noEmit)" in dict(checks.auto_checks(wt, ["src/x.ts"]))


def test_powershell_lint_check_is_errors_only(tmp_path):
    from orch import checks
    (tmp_path / "A.ps1").write_text("function Get-Things { 1 }\n")
    jobs = dict(checks.auto_checks(tmp_path, ["A.ps1"]))
    script = jobs["PSScriptAnalyzer (changed files)"][-1]
    assert "-Severity Error }" in script and "Warning" not in script


def test_pyc_not_committed(env, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm())

    def aider(wt, *a, **k):
        (wt / "hello.txt").write_text("good\n")
        (wt / "__pycache__").mkdir()
        (wt / "__pycache__" / "x.cpython-311.pyc").write_bytes(b"\0")
        return 0, "ok"
    monkeypatch.setattr(aider_runner, "run_aider", aider)
    meta = graph.run_task(str(env), "t")
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", meta["branch"]], cwd=env,
                           capture_output=True, text=True).stdout.split()
    assert "hello.txt" in files and not any(f.endswith(".pyc") for f in files)


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


def test_candidates_env_override(monkeypatch):
    from orch.config import Settings
    assert Settings().coder_candidates[0][0] == "coder-gamebed"
    monkeypatch.setenv("ORCH_CODER_CANDIDATES", '[["x", "http://h:1"]]')
    assert Settings().coder_candidates == [("x", "http://h:1")]


def test_extract_json_tolerates_regex_backslashes():
    got = extract_json('{"fix": "use \\w+(?:\'[a-z]+)? here", "n": 1}')  # a lone backslash, invalid JSON
    assert got["n"] == 1 and "\\w+" in got["fix"]


def test_chat_stream_drops_reasoning(monkeypatch):
    import httpx
    events = [{"content": "<thi"}, {"content": "nk>hidden"}, {"content": "</think>Hi"}, {"reasoning": "x"},
              {"content": " there"}]
    body = "".join(f"data: {json.dumps({'choices': [{'delta': d}]})}\n\n" for d in events) + "data: [DONE]\n\n"
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    monkeypatch.setattr(httpx, "stream", lambda method, url, **k: client.stream(method, url, json=k["json"]))
    assert "".join(llm.chat_stream("m", [], base="http://x")) == "Hi there"


def test_extract_json_handles_fences_and_prose():
    assert extract_json('Sure!\n```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}


def test_resolve_skips_a_home_host_without_the_model(monkeypatch):
    monkeypatch.setattr(S, "fallback_hosts", ["http://gpu1", "http://gpu2"])
    monkeypatch.setattr(health, "worker_up", lambda url, *a, **k: True)
    monkeypatch.setattr(health, "_has", lambda url, alias: url == "http://gpu1")
    assert health.resolve("m-missing", "http://gpu2") == "http://gpu1"


def test_parse_chat_directives():
    from orch.api import parse_request
    req = parse_request([
        {"role": "system", "content": "repo: base\ncheck: make lint"},
        {"role": "user", "content": "old"},
        {"role": "user", "content": [{"type": "text", "text":
            "repo: proj\nfiles: a.py, b.py\ncheck: pytest -q\ncheck: ruff .\n\nAdd a flag.\nrepo: not-a-directive"}]}])
    assert req["repo"] == "proj" and req["files"] == ["a.py", "b.py"]
    assert req["checks"] == ["pytest -q", "ruff ."]
    assert req["task"] == "Add a flag.\nrepo: not-a-directive" and req["command"] is None
    assert [m["content"] for m in req["discussion"]] == ["old", "Add a flag.\nrepo: not-a-directive"]
    req = parse_request([{"role": "system", "content": "repo: base\ncheck: x"},
                         {"role": "user", "content": "files: f.py\nlet's add a flag"},
                         {"role": "assistant", "content": "Sure: plan..."},
                         {"role": "user", "content": "sounds good\nGo!"}])
    assert (req["repo"], req["files"], req["checks"], req["command"], req["task"]) == \
        ("base", ["f.py"], ["x"], "go", "sounds good")
    assert [m["role"] for m in req["discussion"]] == ["user", "assistant", "user"]
    assert parse_request([{"role": "user", "content": "x\n/review"}])["command"] == "review"
    assert parse_request([{"role": "user", "content": "go ahead and refactor"}])["command"] is None


def _client(monkeypatch, tmp_path, key=""):
    from fastapi.testclient import TestClient
    from orch import api
    monkeypatch.setattr(S, "api_key", key)
    monkeypatch.setattr(S, "allowed_root", str(tmp_path))
    return TestClient(api.app), api


def test_openai_models_and_auth(env, monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path, key="k1")
    assert client.get("/v1/models").status_code == 401
    r = client.get("/v1/models", headers={"Authorization": "Bearer k1"})
    assert r.json()["data"][0]["id"] == S.api_model


def test_openai_go_without_repo_explains_usage(env, monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "add a flag\ngo"}]})
    text = r.json()["choices"][0]["message"]["content"]
    assert "repo:" in text and "proj" in text          # lists the repos it can see


def _streamed(client, messages) -> str:
    with client.stream("POST", "/v1/chat/completions", json={"stream": True, "messages": messages}) as r:
        return "".join(json.loads(l[6:])["choices"][0]["delta"].get("content", "")
                       for l in r.iter_lines() if l.startswith("data: {"))


def _commit(repo, name, text):
    (repo / name).write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", name], cwd=repo, check=True)


def test_openai_discussion_reads_the_repo_and_codes_nothing(env, monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    _commit(env, "lib.py", "def area(r):\n    return 3 * r\n")
    seen = {}

    def chat_stream(alias, messages, **kw):
        seen["messages"] = messages
        yield "Use math.pi; "
        yield "send `go` when ready."
    monkeypatch.setattr(llm, "chat_stream", chat_stream)
    text = _streamed(client, [{"role": "user", "content": "repo: proj\nfiles: lib.py\nFix area() precision?"}])
    assert text == "Use math.pi; send `go` when ready."
    context = "\n".join(m["content"] for m in seen["messages"] if m["role"] == "system")
    assert "return 3 * r" in context and "lib.py" in context
    assert seen["messages"][-1] == {"role": "user", "content": "Fix area() precision?"}
    assert "orch/" not in subprocess.run(["git", "branch"], cwd=env, capture_output=True, text=True).stdout


def test_openai_review_asks_each_coder_and_codes_nothing(env, monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(S, "solvers", [("bench-sa", "http://a"), ("bench-sb", "http://b")])
    monkeypatch.setattr(health, "resolve", lambda alias, home: home)
    monkeypatch.setattr(llm, "chat", lambda alias, messages, **kw: "Make area() use math.pi.")
    asked = []

    def chat_stream(alias, messages, **kw):
        asked.append((alias, messages[-1]["content"]))
        yield f"{alias} prefers math.pi"
    monkeypatch.setattr(llm, "chat_stream", chat_stream)
    text = _streamed(client, [{"role": "user", "content": "repo: proj\nfix area"},
                              {"role": "assistant", "content": "use math.pi?"},
                              {"role": "user", "content": "yes\nreview"}])
    assert "Make area() use math.pi." in text and "bench-sa prefers" in text and "bench-sb prefers" in text
    assert [a for a, _ in asked] == ["bench-sa", "bench-sb"]
    assert all("Make area() use math.pi." in prompt for _, prompt in asked)
    assert "orch/" not in subprocess.run(["git", "branch"], cwd=env, capture_output=True, text=True).stdout


def test_openai_go_after_discussion_codes_the_written_spec(env, monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(llm, "chat", lambda alias, messages, **kw: "Make hello.txt say good.")
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["good\n"]))
    text = _streamed(client, [{"role": "user", "content": "repo: proj\ncheck: grep -q good hello.txt\nhello?"},
                              {"role": "assistant", "content": "Say good?"},
                              {"role": "user", "content": "yes\ngo"}])
    assert "Task sent to the coders" in text and "Make hello.txt say good." in text
    assert "Result: PASSED" in text
    runs = list((tmp_path / "runs").glob("*/run.json"))
    assert json.loads(runs[0].read_text())["task"] == "Make hello.txt say good."


def test_openai_webui_background_prompts_go_straight_to_the_planner(env, monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    seen = {}

    def chat_stream(alias, messages, **kw):
        seen["messages"] = messages
        yield '{"title": "Error count"}'
    monkeypatch.setattr(llm, "chat_stream", chat_stream)
    msgs = [{"role": "user", "content": "### Task:\nGenerate a concise title.\n### Chat History:\nrepo: proj\nx\ngo"}]
    assert _streamed(client, msgs) == '{"title": "Error count"}'
    assert seen["messages"] == msgs                            # no planner prompt, no repo context, no run


def test_openai_chat_streams_a_run_and_cleans_up(env, monkeypatch, tmp_path):
    client, api = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(llm, "chat_json", fake_llm())
    monkeypatch.setattr(aider_runner, "run_aider", fake_aider(["good\n"]))
    text = _streamed(client, [{"role": "user", "content":
                               "repo: proj\ncheck: grep -q good hello.txt\nMake hello say good.\ngo"}])
    assert "Result: PASSED" in text and "hello.txt" in text   # diff stat of the result branch
    assert "Task sent to the coders" not in text               # a first message ending in go runs as written
    branches = subprocess.run(["git", "branch"], cwd=env, capture_output=True, text=True).stdout
    worktrees = subprocess.run(["git", "worktree", "list"], cwd=env, capture_output=True, text=True).stdout
    assert branches.count("orch/") == 1 and len(worktrees.splitlines()) == 1


def test_openai_chat_rejects_repo_outside_root(env, monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path / "proj" / "sub")
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "repo: ../..\nx"}]})
    assert r.status_code == 400
