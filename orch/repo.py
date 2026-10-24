"""Git helpers. Work happens in a throwaway worktree so the user's checkout is never touched."""
from __future__ import annotations

import subprocess
from pathlib import Path


def sh(cmd, cwd, timeout: int = 120, shell: bool = False, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=cwd, shell=shell, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=env,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
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
    git(["add", "-A", "--", ".", ":(exclude).aider*"], wt)  # keep Aider's cache files out of the branch
    rc, _ = sh(["git", "diff", "--cached", "--quiet"], wt)
    if rc == 0:
        return False
    git(["commit", "-q", "-m", message], wt)
    return True


def diff_since(wt: Path, base_sha: str) -> str:
    return git(["diff", base_sha, "HEAD"], wt)


def changed_files(wt: Path, base_sha: str) -> list[str]:
    return [f for f in git(["diff", "--name-only", base_sha, "HEAD"], wt).splitlines() if f]
