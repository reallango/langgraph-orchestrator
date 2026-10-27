"""Consensus mode: two solvers on separate GPUs solve the task independently, each writes tests from the TASK text,
every solution is run against both test sets, and a solution is accepted only if it passes the visible checks and
every test set that both models consider valid. Disagreements get one repair round; otherwise the task is flagged."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import aider_runner, checks, health, langs, llm, repo
from .config import S

GEN_TESTS_SYSTEM = """You write tests for a programming TASK. You see the TASK and the starting source files, but NOT
anyone's solution. Write 4 to 8 tests for requirements stated in the TASK (main behaviour, edge cases, boundaries,
error handling, exact output formats). Base every expectation ONLY on the TASK text and the existing tests; skip
anything the task leaves ambiguous.
Reply with ONLY a JSON object: {{"content": "<the complete test file>"}}.
{rules}"""
JUDGE_SYSTEM = """A test file failed against a candidate solution. Using ONLY the TASK text as the source of truth, decide
whether the CODE is wrong or the TEST FILE is wrong. The test file is wrong if any failing assertion expects something
the task does not say, miscomputes an expected value, has a syntax error or misuses the test framework.
Reply with ONLY a JSON object: {"code_wrong": true or false, "explanation": "<the violated requirement and the fix; empty if the test is wrong>"}"""


def _instruction(s: dict, findings: str = "") -> str:
    p = s["plan"]
    text = f"Implement this task with the smallest correct change. Only edit the files given.\n\nTASK: {s['task']}"
    if p.get("steps"):
        text += "\n\nPLAN:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(p["steps"], 1))
    if p.get("acceptance_criteria"):
        text += "\n\nACCEPTANCE CRITERIA:\n" + "\n".join(f"- {c}" for c in p["acceptance_criteria"])
    if findings:
        text += ("\n\nThe current code in the files is a previous attempt that failed. Edit the EXISTING code in place to "
                 f"fix these problems. Never add a second copy of a function or class; replace it.\n{findings}")
    from .graph import _hints  # shared language notes (only when ORCH_HINTS=1)
    return text + _hints(p["files_to_edit"])


class Side:
    def __init__(self, key: str, alias: str, wt: Path):
        self.key, self.alias, self.wt = key, alias, wt
        self.visible_ok, self.report, self.calls, self.tests = False, "", 0, None

    def code(self, s: dict, findings: str = "") -> None:
        run, p = s["run"], s["plan"]
        base, key = health.base_for(self.alias)
        log_dir = run.dir / f"aider-{self.key}"
        log_dir.mkdir(exist_ok=True)
        rc, out = aider_runner.run_aider(self.wt, self.alias, _instruction(s, findings), p["files_to_edit"],
                                         p["context_files"], log_dir, base=base, key=key)
        run.log(f"{self.key}-aider-{self.calls}.txt", out)
        repo.commit_all(self.wt, f"consensus {self.key} call {self.calls}")
        self.calls += 1

    def check(self, s: dict) -> bool:
        changed = repo.changed_files(self.wt, s["base_sha"])
        if not changed:
            self.visible_ok, self.report = False, "No changes were made (no valid edit blocks)."
            return False
        ok, _, report = checks.run_checks(self.wt, s.get("check_cmds", []), changed)
        self.visible_ok, self.report = ok, report
        s["run"].log(f"{self.key}-checks-{self.calls - 1}.txt", report)
        return ok

    def solve(self, s: dict) -> "Side":
        self.code(s)
        for _ in range(S.solver_repairs):
            if self.check(s):
                break
            self.code(s, f"Checks failed:\n{self.report}")
        else:
            self.check(s)
        s["run"].event("solve", side=self.key, coder=self.alias, calls=self.calls, visible_ok=self.visible_ok)
        return self

    def write_tests(self, s: dict, lang: langs.Lang) -> "Side":
        p = s["plan"]
        base, key = health.base_for(self.alias)
        sources = repo.read_capped(s["wt0_base"], p["files_to_edit"] + p.get("context_files", []), S.context_chars)
        try:
            obj, _ = llm.chat_json(self.alias, [{"role": "system", "content": GEN_TESTS_SYSTEM.format(rules=lang.rules)},
                                               {"role": "user", "content": f"TASK:\n{s['task']}\n\nSTARTING FILES:\n{sources}"}],
                                   base=base, key=key)
            self.tests = str(obj["content"])
            s["run"].log(f"{self.key}-tests.txt", self.tests)
        except Exception as e:
            s["run"].event("consensus_error", stage="tests", side=self.key, error=str(e)[:200])
        return self


def _run_tests(side: Side, author: Side, lang: langs.Lang) -> tuple[bool, str]:
    name = lang.test_file(author.key)
    (side.wt / name).write_text(author.tests, encoding="utf-8")
    try:
        rc, out = repo.sh(lang.command(side.wt, name), side.wt, timeout=S.check_timeout)
    finally:
        (side.wt / name).unlink(missing_ok=True)
    return rc == 0, out


def _judge(s: dict, judge: Side, code_side: Side, author: Side, out: str) -> dict:
    base, key = health.base_for(judge.alias)
    diff = repo.diff_since(code_side.wt, s["base_sha"])[:S.diff_chars]
    user = (f"TASK:\n{s['task']}\n\nCANDIDATE SOLUTION (diff):\n{diff}\n\nTEST FILE:\n{author.tests}\n\n"
            f"FAILING OUTPUT:\n{out[-3000:]}")
    try:
        v, _ = llm.chat_json(judge.alias, [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}],
                             base=base, key=key)
        return v
    except Exception as e:
        s["run"].event("consensus_error", stage="judge", side=judge.key, error=str(e)[:200])
        return {"code_wrong": True, "explanation": "judge unavailable; keeping the test"}   # conservative


def consensus(s: dict) -> dict:
    run, p = s["run"], s["plan"]
    hosts = {a: health.resolve(a, url) for a, url in S.solvers}   # a solver whose host is down moves to a live one
    names = [a for a, h in hosts.items() if h]
    if len(names) < 2:
        return {"status": "failed", "reason": f"consensus needs two healthy solvers, have {names}"}
    width = 2 if hosts[names[0]] != hosts[names[1]] else 1   # one GPU: take turns instead of thrashing it
    wt_b = run.dir / "work_b"
    repo.add_worktree(s["repo"], wt_b, f"{s['branch']}-b", s["base_sha"])
    a, b = Side("A", names[0], s["wt"]), Side("B", names[1], wt_b)
    s = dict(s, wt0_base=run.dir / "base_snapshot")   # untouched copy of the starting files, for writing tests
    repo.add_worktree(s["repo"], s["wt0_base"], f"{s['branch']}-base", s["base_sha"])
    lang = langs.detect(p["files_to_edit"])
    if width == 2:
        with ThreadPoolExecutor(2) as ex:   # independent work on two GPUs
            list(ex.map(lambda side: side.solve(s), (a, b)))
            if lang:
                list(ex.map(lambda side: side.write_tests(s, lang), (a, b)))
    else:   # finish each model's work before switching, so each model loads once
        for side in (a, b):
            side.solve(s)
            if lang:
                side.write_tests(s, lang)
    sides, authors = (a, b), [x for x in (a, b) if x.tests]
    info = {"solvers": [a.alias, b.alias], "hosts": [hosts[a.alias], hosts[b.alias]],
            "mode": "parallel" if width == 2 else "single-host", "visible": {x.key: x.visible_ok for x in sides},
            "outcome": ""}

    def evaluate():
        res = {}
        for side in sides:
            if side.visible_ok:
                for author in authors:
                    res[(side.key, author.key)] = _run_tests(side, author, lang)
        return res

    valid = {x.key: True for x in authors}
    for round_no in range(S.consensus_repairs + 1):
        res = evaluate() if lang else {}
        # judge every test set that fails on some visible-passing solution; it stays valid unless BOTH models call it wrong
        for author in authors:
            if not valid[author.key]:
                continue
            fails = [(side, res[(side.key, author.key)][1]) for side in sides
                     if (side.key, author.key) in res and not res[(side.key, author.key)][0]]
            if not fails:
                continue
            side, out = fails[0]
            with ThreadPoolExecutor(width) as ex:
                verdicts = list(ex.map(lambda j: _judge(s, j, side, author, out), (a, b)))
            run.event("judge", tests=author.key, code=side.key, verdicts=[v.get("code_wrong") for v in verdicts])
            if all(v.get("code_wrong") is False for v in verdicts):
                valid[author.key] = False
        winners = [side for side in sides if side.visible_ok and all(
            res.get((side.key, au.key), (True, ""))[0] for au in authors if valid[au.key])]
        if winners:
            win = winners[0]
            info["outcome"] = ("agree" if len(winners) == 2 else "one-sided") + (f" after {round_no} repair round(s)" if round_no else "")
            break
        if round_no == S.consensus_repairs:
            win = None
            break
        # repair: every solution gets the valid tests it fails (or its visible failure) as findings
        def repair(side):
            if not side.visible_ok:
                side.code(s, f"Checks failed:\n{side.report}")
            else:
                outs = [res[(side.key, au.key)][1][-1500:] for au in authors
                        if valid[au.key] and not res[(side.key, au.key)][0]]
                side.code(s, "Independent tests written from the task text fail:\n" + "\n----\n".join(outs))
            side.check(s)
            return side
        with ThreadPoolExecutor(width) as ex:
            list(ex.map(repair, sides))
    info.update(valid_tests={k: v for k, v in valid.items()}, calls={x.key: x.calls for x in sides},
                winner=win.key if win else None, failovers=health.failovers())
    run.save_meta(consensus=info)
    run.event("consensus", **info)
    calls = sum(x.calls for x in sides)
    if not win:
        return {"status": "failed", "reason": "no consensus: no solution passed the visible checks and all valid tests",
                "cycle": calls - 2, "verified": True}
    if win is b:
        repo.take_from_branch(a.wt, s["base_sha"], f"{s['branch']}-b")
        repo.commit_all(a.wt, "consensus: adopt solver B's solution")
    return {"findings": "", "cycle": calls - 2, "verified": True}
