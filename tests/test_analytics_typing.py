"""Strict-typing guard for the analytics core (Phase 10, plan 10-01).

Runs mypy (strict, per pyproject) via subprocess and fails only on error lines
that name the analytics paths: mypy currently reports one pre-existing error in
src/adapters/telegram_notify.py, which is out of scope for this guard. Fails
closed when mypy's summary line is absent (mypy did not actually run).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ADAPTER_MODULES = ("src/adapters/analytics_store.py", "src/adapters/analytics_files.py")
_SUMMARY = re.compile(r"^(Success: no issues found|Found \d+ errors? in)", re.MULTILINE)
_ANALYTICS_PATH = re.compile(
    r"^(src[\\/]analytics[\\/]|src[\\/]adapters[\\/]analytics_(store|files)\.py)"
)


def analytics_error_lines(stdout: str) -> list[str]:
    """mypy error lines that name an analytics path (either slash style)."""
    return [
        line
        for line in stdout.splitlines()
        if ": error:" in line and _ANALYTICS_PATH.match(line.strip())
    ]


def has_summary(stdout: str) -> bool:
    """True when mypy printed its final Success/Found summary line."""
    return _SUMMARY.search(stdout) is not None


def _targets() -> list[str]:
    targets = ["src/analytics"]
    targets.extend(rel for rel in _ADAPTER_MODULES if (REPO_ROOT / rel).is_file())
    return targets


def test_analytics_is_mypy_strict_clean() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-color-output", *_targets()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert has_summary(result.stdout), (
        "mypy summary line missing - mypy did not run:\n" + result.stdout + result.stderr
    )
    errors = analytics_error_lines(result.stdout)
    assert not errors, "mypy strict errors in analytics paths:\n" + "\n".join(errors)


def test_filter_selects_only_analytics_paths() -> None:
    out = (
        "src/adapters/telegram_notify.py:10: error: something  [misc]\n"
        "src\\analytics\\stats.py:5: error: bad  [arg-type]\n"
        "src/analytics/excursion.py:9: error: worse  [return-value]\n"
        "src/adapters/analytics_store.py:3: error: store  [misc]\n"
        "Found 4 errors in 4 files (checked 9 source files)\n"
    )
    assert analytics_error_lines(out) == [
        "src\\analytics\\stats.py:5: error: bad  [arg-type]",
        "src/analytics/excursion.py:9: error: worse  [return-value]",
        "src/adapters/analytics_store.py:3: error: store  [misc]",
    ]


def test_missing_summary_line_is_detected() -> None:
    assert has_summary("Success: no issues found in 5 source files\n")
    assert has_summary("Found 1 error in 1 file (checked 3 source files)\n")
    assert not has_summary("")
    assert not has_summary("Traceback (most recent call last):\n")
