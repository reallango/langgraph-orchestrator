"""Verification: user-supplied commands plus cheap automatic checks scoped to changed files."""
from __future__ import annotations

from pathlib import Path

from . import langs
from .config import S
from .repo import sh

PS_EXT = (".ps1", ".psm1", ".psd1")
TAIL = 4000


def auto_checks(wt: Path, changed: list[str]) -> list[tuple[str, list[str]]]:
    existing = [f for f in changed if (wt / f).is_file()]
    out: list[tuple[str, list[str]]] = []
    py = [f for f in existing if f.endswith(".py")]
    if py:
        out.append(("python syntax", ["python", "-m", "py_compile", *py]))
    ps = [f for f in existing if f.lower().endswith(PS_EXT)]
    if ps:
        paths = ",".join("'" + f.replace("'", "''") + "'" for f in ps)
        # Errors only (syntax / parse problems). Warning-level rules are style: the task may mandate a name that trips
        # one (e.g. PSUseSingularNouns on Get-BusinessDays) and a lint nit must not reject working code.
        script = (
            f"$r = foreach ($p in @({paths})) {{ Invoke-ScriptAnalyzer -Path $p -Severity Error }}; "
            "if ($r) { $r | Format-Table -AutoSize | Out-String -Width 200 | Write-Output; exit 1 }"
        )
        out.append(("PSScriptAnalyzer (changed files)", ["pwsh", "-NoLogo", "-NonInteractive", "-Command", script]))
    if any(f.lower().endswith((".ts", ".tsx")) for f in existing) and (wt / "tsconfig.json").is_file():
        langs.ensure_node_modules(wt)
        if (wt / "node_modules" / ".bin" / "tsc").exists():
            out.append(("typescript (tsc --noEmit)", ["./node_modules/.bin/tsc", "--noEmit", "-p", "."]))
    return out


def run_checks(wt: Path, user_checks: list[str], changed: list[str]) -> tuple[bool, bool, str]:
    """Returns (passed, verified, report). verified is False when nothing was actually run."""
    jobs: list[tuple[str, object, bool]] = [(c, c, True) for c in user_checks]
    jobs += [(label, argv, False) for label, argv in auto_checks(wt, changed)]
    if not jobs:
        return True, False, "NO CHECKS RUN: result is unverified."
    ok, parts = True, []
    for label, cmd, use_shell in jobs:
        rc, out = sh(cmd, wt, timeout=S.check_timeout, shell=use_shell)
        ok &= rc == 0
        parts.append(f"$ {label}\nexit={rc}\n{out[-TAIL:]}")
    return ok, True, "\n\n".join(parts)
