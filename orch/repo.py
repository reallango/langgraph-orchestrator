"""Git helpers. Work happens in a throwaway worktree so the user's checkout is never touched."""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path


def sh(cmd, cwd, timeout: int = 120, shell: bool = False, env: dict | None = None) -> tuple[int, str]:
    # Own process group, killed whole on timeout: otherwise a looping grandchild (sh -> pwsh) outlives it.
    p = subprocess.Popen(cmd, cwd=cwd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", env=env, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, (out or "") + (err or "")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        return 124, f"TIMEOUT after {timeout}s"


def git(args: list[str], cwd, timeout: int = 120) -> str:
    rc, out = sh(["git", *args], cwd, timeout)
    if rc != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({rc}): {out.strip()}")
    return out.strip()


def create_worktree(repo: str, run_dir: Path, run_id: str, base_ref: str = "HEAD") -> tuple[Path, str, str]:
    git(["rev-parse", "--git-dir"], repo)
    base_sha = git(["rev-parse", base_ref], repo)
    branch = f"orch/{run_id}"
    wt = run_dir / "work"
    git(["worktree", "add", "-b", branch, str(wt), base_sha], repo)
    return wt, branch, base_sha


def add_worktree(repo: str, path: Path, branch: str, base_sha: str) -> None:
    git(["worktree", "add", "-q", "-b", branch, str(path), base_sha], repo)


def take_from_branch(wt: Path, base_sha: str, branch: str) -> None:
    """Make wt's files equal to another branch's tip (used to adopt the other solver's solution)."""
    reset_to_base(wt, base_sha)
    git(["checkout", branch, "--", "."], wt)


def tracked_files(wt: Path) -> list[str]:
    return [f for f in git(["ls-files"], wt).splitlines() if f]


def safe_rel(wt: Path, rel: str) -> str | None:
    """Normalise a model-supplied path; None if it escapes the worktree."""
    rel = rel.strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    return rel


def read_capped(wt: Path, rels: list[str], budget: int) -> str:
    parts, used = [], 0
    for rel in rels:
        p = wt / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        chunk = f"--- {rel} ---\n{text}\n"
        if used + len(chunk) > budget:
            parts.append(f"--- {rel} --- (omitted: context budget exhausted)\n")
            continue
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)


def commit_all(wt: Path, message: str) -> bool:
    # Keep tool/runtime droppings (Aider caches, bytecode) out of the branch. node_modules goes through
    # info/exclude: an exclude pathspec naming a path .gitignore already ignores makes `git add` fail.
    rc, out = sh(["git", "rev-parse", "--git-path", "info/exclude"], wt)
    info = wt / out.strip()
    info.parent.mkdir(parents=True, exist_ok=True)
    if rc == 0 and "node_modules" not in (info.read_text() if info.exists() else ""):
        with info.open("a") as f:
            f.write("\nnode_modules\n*.tsbuildinfo\n")
    git(["add", "-A", "--", ".", ":(exclude).aider*", ":(exclude)**/__pycache__/**", ":(exclude)*.pyc",
                 ":(exclude)testResults.xml", ":(exclude)coverage.xml", ":(exclude).pytest_cache",
                 ":(exclude)_orch_extra*"], wt)
    rc, _ = sh(["git", "diff", "--cached", "--quiet"], wt)
    if rc == 0:
        return False
    git(["commit", "-q", "-m", message], wt)
    return True


def reset_to_base(wt: Path, base_sha: str) -> None:
    """Throw away every attempt so far (fresh start for the next model)."""
    git(["reset", "--hard", "-q", base_sha], wt)
    git(["clean", "-fdq"], wt)


def diff_since(wt: Path, base_sha: str) -> str:
    return git(["diff", base_sha, "HEAD"], wt)


def changed_files(wt: Path, base_sha: str) -> list[str]:
    return [f for f in git(["diff", "--name-only", base_sha, "HEAD"], wt).splitlines() if f]
