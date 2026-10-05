"""Hand-derived golden cases of the causal simulator (Phase 14, plan 14-13, D-24, F-805).

Every directory under `tests/fixtures/phase14` that holds both `input.json` and `expected.json`
is one case. The test runs the PUBLIC entry point `src.backtest.simulator.run` on `input.json`
and compares the fields listed in `expected.json` with the trade records and the run summary,
field by field. The expectations are written by hand from `DERIVATIONS.md` (an independent
Decimal computation with no project imports); they are never produced by the code under test.

Comparison is numeric: amounts compare as `Decimal` and times as parsed datetimes, so a scale-8
spelling of a number can never cause a false failure. A field that `expected.json` omits is not
compared; a field it lists as `null` must be `None`. The number of trade records must match.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.simulator import run

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "phase14"

# Cases the plan requires; the list grows with each task of plan 14-13 and is checked in full
# by `test_every_required_case_is_present`.
REQUIRED_CASES: tuple[str, ...] = ("signal_bar_touch_no_fill",)

DECIMAL_FIELDS = frozenset(
    {
        "entry_price",
        "quantity",
        "planned_quantity",
        "exit_price",
        "tp1_quantity",
        "tp1_price",
        "gross_pnl",
        "entry_fee",
        "exit_fee",
        "slippage_amount",
        "funding_amount",
        "realized_pnl",
        "realized_risk",
    }
)
TIME_FIELDS = frozenset(
    {
        "signal_close_utc",
        "entry_time_utc",
        "exit_time_utc",
        "tp1_time_utc",
        "resolved_at_utc",
    }
)
# Substring checks for free-text fields whose full spelling is documentation, not arithmetic.
CONTAINS_SUFFIX = "_contains"


def _case_dirs() -> list[Path]:
    return sorted(
        path
        for path in FIXTURE_ROOT.iterdir()
        if path.is_dir() and (path / "input.json").is_file() and (path / "expected.json").is_file()
    )


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _diff_field(where: str, name: str, expected: Any, actual: Any) -> list[str]:
    """Return one message per mismatch of a single listed field (empty when equal)."""
    if name.endswith(CONTAINS_SUFFIX):
        field = name[: -len(CONTAINS_SUFFIX)]
        text = actual.get(field) if isinstance(actual, dict) else None
        if not isinstance(text, str) or expected not in text:
            return [f"{where}.{field}: expected a text containing {expected!r}, actual {text!r}"]
        return []
    if expected is None or actual is None:
        if expected is None and actual is None:
            return []
        return [f"{where}.{name}: expected {expected!r}, actual {actual!r}"]
    if name in DECIMAL_FIELDS:
        if Decimal(str(actual)) != Decimal(str(expected)):
            return [f"{where}.{name}: expected {expected}, actual {actual}"]
        return []
    if name in TIME_FIELDS:
        if datetime.fromisoformat(str(actual)) != datetime.fromisoformat(str(expected)):
            return [f"{where}.{name}: expected {expected}, actual {actual}"]
        return []
    if actual != expected:
        return [f"{where}.{name}: expected {expected!r}, actual {actual!r}"]
    return []


def _diff_trade(index: int, expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    where = f"trades[{index}]"
    for name, want in expected.items():
        if name.endswith(CONTAINS_SUFFIX):
            problems += _diff_field(where, name, want, actual)
            continue
        if name not in actual:
            problems.append(f"{where}.{name}: the record has no such field")
            continue
        problems += _diff_field(where, name, want, actual[name])
    return problems


def diff_output(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """List every mismatch between a hand-written expectation and a simulator output."""
    problems: list[str] = []
    want_trades = expected["trades"]
    got_trades = actual["trades"]
    if len(want_trades) != len(got_trades):
        problems.append(f"trade count: expected {len(want_trades)}, actual {len(got_trades)}")
    for index, (want, got) in enumerate(zip(want_trades, got_trades, strict=False)):
        problems += _diff_trade(index, want, got)
    summary = actual["run_summary"]
    for name, want_value in expected.get("run_summary", {}).items():
        if name not in summary:
            problems.append(f"run_summary.{name}: the summary has no such key")
        elif summary[name] != want_value:
            problems.append(
                f"run_summary.{name}: expected {want_value!r}, actual {summary[name]!r}"
            )
    return problems


def test_cases_were_found() -> None:
    assert _case_dirs(), (
        f"no golden case with both input.json and expected.json under {FIXTURE_ROOT}"
    )


def test_every_required_case_is_present() -> None:
    present = {path.name for path in _case_dirs()}
    missing = sorted(set(REQUIRED_CASES) - present)
    assert not missing, f"golden cases missing input.json or expected.json: {missing}"


@pytest.mark.parametrize("case_dir", _case_dirs(), ids=lambda path: path.name)
def test_golden_case(case_dir: Path) -> None:
    case_input = _load(case_dir / "input.json")
    expected = _load(case_dir / "expected.json")
    actual = run(case_input)
    problems = diff_output(expected, actual)
    assert not problems, (
        f"{case_dir.name} differs from its hand-derived expectation:\n" + "\n".join(problems)
    )
