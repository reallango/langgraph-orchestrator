"""Per-language test conventions shared by verification (graph) and consensus: how a generated test file is named,
how it is run, and what the test-writing model is told."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PY_RULES = "Write a pytest file. Import from the project modules directly (they sit in the working directory). Use plain functions named test_*."
PS_RULES = ("Write a Pester 6 file. Begin with: BeforeAll { . $PSScriptRoot/<script file name> } (dot-source every script the "
            "task touches, using the real file names from the file list). Use Describe/It with Should -Be, -BeExactly, -Throw. "
            "Put any BeforeEach/AfterEach INSIDE Describe.")
TS_RULES = ("Write a Vitest file in TypeScript. Import describe, it, expect (and vi when needed) from 'vitest'. The test file "
            "sits in the repository root: import the code under test with a relative path such as './src/lib/x' (no '@/' "
            "aliases, no file extension for .ts files). For a CommonJS .js module use: import mod from './src/lib/x.js' and "
            "call mod.fn. For time-dependent code use vi.useFakeTimers() and vi.setSystemTime(). Module-level state persists "
            "between tests, so use distinct keys per test.")

TS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


@dataclass
class Lang:
    name: str
    rules: str

    def test_file(self, key: str = "") -> str:
        k = f"_{key.lower()}" if key else ""
        return {"py": f"_orch_extra{k}_test.py", "ps": f"_orch_extra{k}.Tests.ps1",
                "ts": f"_orch_extra{k}.test.ts"}[self.name]

    def command(self, wt: Path, name: str) -> list[str]:
        if self.name == "py":
            return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", name]
        if self.name == "ps":
            return ["pwsh", "-NoProfile", "-Command", f"Invoke-Pester -Path ./{name} -CI -Output Minimal"]
        ensure_node_modules(wt)
        return ["./node_modules/.bin/vitest", "run", "--reporter=dot", name]


def detect(files: list[str]) -> Lang | None:
    if any(f.endswith(".py") for f in files):
        return Lang("py", PY_RULES)
    if any(f.lower().endswith((".ps1", ".psm1")) for f in files):
        return Lang("ps", PS_RULES)
    if any(f.lower().endswith(TS_EXT) for f in files):
        return Lang("ts", TS_RULES)
    return None


def ensure_node_modules(wt: Path) -> None:
    """Repos without their own node_modules borrow a shared toolchain (ORCH_NODE_MODULES) through a symlink, which the
    repo's .gitignore must exclude."""
    shared = os.environ.get("ORCH_NODE_MODULES", "")
    nm = wt / "node_modules"
    if shared and not nm.exists() and not nm.is_symlink():
        nm.symlink_to(shared)
