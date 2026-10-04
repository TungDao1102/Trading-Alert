"""AST purity guard for the pure backtest package (Phase 14, plan 14-01, D-26, T-14-02).

Every `src/backtest/*.py` module, discovered by glob so later plans need no list
edits, must be free of: float shapes, ambient wall-clock reads, module-level
randomness, built-in `hash()`, `timedelta.total_seconds()`, and third-party /
adapter / DB / data imports (`src.data` is where the Polars-backed `MinuteSource`
lives; `src/backtest` must never import it).

The walker and the forbidden sets are the Phase 10 analytics ones
(`tests/test_analytics_purity.py`), so both packages enforce one definition of purity.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_analytics_purity import (
    FORBIDDEN_IMPORT_ROOTS,
    FORBIDDEN_INTERNAL_PREFIXES,
    find_violations,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_DIR = REPO_ROOT / "src" / "backtest"


def _backtest_modules() -> list[Path]:
    return sorted(BACKTEST_DIR.glob("*.py"))


def _rules(source: str) -> list[str]:
    return [rule for _, rule, _ in find_violations(source)]


def _has_rule(source: str, prefix: str) -> bool:
    return any(rule.startswith(prefix) for rule in _rules(source))


def test_forbidden_sets_cover_polars_and_the_data_package() -> None:
    assert "polars" in FORBIDDEN_IMPORT_ROOTS
    assert {"pandas", "numpy", "duckdb", "pyarrow", "sqlalchemy"} <= FORBIDDEN_IMPORT_ROOTS
    assert "src.data" in FORBIDDEN_INTERNAL_PREFIXES
    assert {"src.adapters", "src.db"} <= set(FORBIDDEN_INTERNAL_PREFIXES)


def test_guard_discovers_the_phase_14_modules() -> None:
    names = {p.name for p in _backtest_modules()}
    assert {
        "__init__.py",
        "simulator.py",
        "semantics.py",
        "series.py",
        "entry.py",
        "exits.py",
        "lifecycle.py",
        "records.py",
        "validator.py",
    } <= names


def test_every_backtest_module_is_pure() -> None:
    offenders: list[str] = []
    for path in _backtest_modules():
        for lineno, rule, text in find_violations(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: {rule}: {text}")
    assert not offenders, "backtest purity violated (D-26):\n" + "\n".join(offenders)


# --------------------------------------------------------------------------- #
# Self-tests: every rule fires on a synthetic offending snippet.
# --------------------------------------------------------------------------- #


def test_guard_flags_a_polars_import() -> None:
    assert _has_rule("import polars as pl\n", "forbidden-import")
    assert _has_rule("from polars import DataFrame\n", "forbidden-import")


def test_guard_flags_an_import_from_the_data_package() -> None:
    assert _has_rule("from src.data.case_input import build_case_input_data\n", "forbidden-import")
    assert _has_rule("import src.data.coverage\n", "forbidden-import")


def test_guard_flags_the_ambient_clock() -> None:
    assert _has_rule("from datetime import datetime\nx = datetime.now()\n", "ambient-clock")
    assert _has_rule("import datetime\nx = datetime.datetime.utcnow()\n", "ambient-clock")
    assert _has_rule("import time\nx = time.monotonic()\n", "ambient-clock")


def test_guard_flags_float_shapes() -> None:
    assert "float" in _rules("x = 0.5\n")
    assert "float" in _rules("x = float(1)\n")


def test_guard_flags_total_seconds_hash_and_module_level_random() -> None:
    assert "total_seconds" in _rules("x = (a - b).total_seconds()\n")
    assert "builtin-hash" in _rules("x = hash('a')\n")
    assert _has_rule("import random\nx = random.random()\n", "module-level-random")


def test_guard_allows_clean_pure_code() -> None:
    clean = (
        "from decimal import Decimal\n"
        "from src.core._decimal import _div\n"
        "from src.execution.placement import quantize_price\n"
        "x = Decimal('0.5')\n"
        "y = (b - a) // timedelta(microseconds=1)\n"
    )
    assert _rules(clean) == []
