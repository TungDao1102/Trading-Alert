"""Meta-tests of the Phase 14 golden generator and fixtures (plan 14-13, D-24, F-602, F-805).

The golden oracles are only worth something if they cannot be produced by the code they
test and cannot contain the future. These tests pin that:

- the generator is deterministic and its output equals the committed `input.json` files;
- it writes `input.json` files only (never an `expected.json`) and imports nothing from the
  project, so it cannot reach the simulator;
- no 1m trade or mark minute of any case opens at or before the scripted plan's bar close,
  and the minute builder itself refuses to build one;
- every case has both files and a DERIVATIONS section, and the expectations are the
  hand-written subset of fields (never a dump of a simulator output);
- the research-gate traps are avoided: no fixture file name starts with `experiment` or
  `backtest`, and no JSON key is named `parameters` or `parameters_json`.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.test_backtest_goldens import REQUIRED_CASES

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPO_ROOT / "scripts" / "gen_phase14_fixtures.py"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "phase14"
DERIVATIONS = FIXTURE_ROOT / "DERIVATIONS.md"

# Fields a hand-written expected.json may list (anything else, such as a trade id or a
# hash, can only come from a simulator output).
HAND_FIELDS = frozenset(
    {
        "signal_id",
        "symbol",
        "direction",
        "outcome_kind",
        "reason_code",
        "signal_close_utc",
        "entry_kind",
        "entry_time_utc",
        "entry_price",
        "quantity",
        "planned_quantity",
        "exit_kind",
        "exit_price",
        "exit_time_utc",
        "resolved_at_utc",
        "tp1_quantity",
        "tp1_price",
        "tp1_time_utc",
        "gross_pnl",
        "entry_fee",
        "exit_fee",
        "slippage_amount",
        "funding_amount",
        "funding_event_count",
        "realized_pnl",
        "realized_risk",
        "touch_no_fill_count",
        "gap_through_stop",
        "fallback_applied",
        "coverage_note_contains",
    }
)
SUMMARY_FIELDS = frozenset(
    {
        "end_of_data_count",
        "fallback_count",
        "gap_through_stop_count",
        "pending_at_data_end_count",
        "touch_no_fill_total",
        "no_trade_counts",
    }
)
FORBIDDEN_KEYS = frozenset({"parameters", "parameters_json"})
FORBIDDEN_NAME_PREFIXES = ("experiment", "backtest")


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_phase14_fixtures", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _lf(data: bytes) -> bytes:
    """Line endings normalised: git on Windows may check committed files out as CRLF."""
    return data.replace(b"\r\n", b"\n")


def _committed_cases() -> list[Path]:
    return sorted(path for path in FIXTURE_ROOT.iterdir() if path.is_dir())


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _walk_keys(item)
    return keys


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- determinism


def test_generator_rerun_is_byte_identical(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path / "first")]) == 0
    assert generator.main(["--out", str(tmp_path / "second")]) == 0
    first = _snapshot(tmp_path / "first")
    assert first, "the generator wrote nothing"
    assert first == _snapshot(tmp_path / "second")


def test_regenerated_inputs_equal_the_committed_inputs(tmp_path: Path) -> None:
    generator = _load_generator()
    generator.main(["--out", str(tmp_path)])
    generated = _snapshot(tmp_path)
    for relative, content in generated.items():
        committed = FIXTURE_ROOT / relative
        assert committed.is_file(), f"{relative} is not committed"
        assert _lf(committed.read_bytes()) == content, f"{relative} differs from a fresh run"


def test_generator_writes_input_json_files_only(tmp_path: Path) -> None:
    generator = _load_generator()
    generator.main(["--out", str(tmp_path)])
    written = _snapshot(tmp_path)
    assert {name.split("/")[-1] for name in written} == {"input.json"}
    assert {name.split("/")[0] for name in written} == set(generator.CASES)
    assert set(generator.CASES) == set(REQUIRED_CASES)


def test_generator_imports_nothing_from_the_project() -> None:
    tree = ast.parse(GENERATOR_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"src", "tests", "scripts"}, f"project imports: {sorted(roots)}"


# --------------------------------------------------------------------------- causal placement


def test_no_minute_opens_at_or_before_its_plans_bar_close() -> None:
    checked = 0
    for case_dir in _committed_cases():
        case = _json(case_dir / "input.json")
        closes: dict[str, list[datetime]] = {}
        for plan in case["scripted_plans"]:
            closes.setdefault(plan["symbol"], []).append(
                datetime.fromisoformat(plan["bar_close_utc"])
            )
        assert closes, f"{case_dir.name} has no scripted plan"
        first_close = min(min(values) for values in closes.values())
        for key in ("trade_bars_1m", "mark_bars_1m"):
            for row in case[key]:
                opened = datetime.fromisoformat(row["open_time_utc"])
                symbol_closes = closes.get(row["symbol"])
                assert symbol_closes, f"{case_dir.name}: minute for {row['symbol']} without a plan"
                assert opened > min(symbol_closes), (
                    f"{case_dir.name} {key} {row['symbol']} minute {row['open_time_utc']} opens at "
                    f"or before the plan's bar close {min(symbol_closes).isoformat()}"
                )
                assert opened > first_close
                checked += 1
    assert checked > 0


def test_minute_builder_refuses_a_minute_inside_the_signal_bar() -> None:
    generator = _load_generator()
    close = generator.SIGNAL_CLOSE
    with pytest.raises(ValueError, match="bar N\\+1"):
        generator._minute_rows(
            "BTCUSDT", "trade", first="09:30", count=60, base=generator.LONG_FLAT, not_before=close
        )
    with pytest.raises(ValueError, match="bar N\\+1"):
        generator._minute_rows(
            "BTCUSDT", "mark", first="09:59", count=2, base=generator.LONG_FLAT, not_before=close
        )
    # The whole-case helper refuses it too, so no case builder can slip a minute in.
    plan = generator._plan("BTCUSDT", signal_id="G14-BAD-MINUTE")
    with pytest.raises(ValueError, match="bar N\\+1"):
        generator._single(plan, first="09:59", count=2)
    # The first minute after the bar close (10:00:00) is accepted.
    rows = generator._minute_rows(
        "BTCUSDT", "trade", first="10:00", count=1, base=generator.LONG_FLAT, not_before=close
    )
    assert [row["open_time_utc"] for row in rows] == ["2026-01-05T10:00:00+00:00"]


def test_minute_builder_refuses_an_incoherent_minute() -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match="incoherent"):
        generator._minute_rows(
            "BTCUSDT",
            "trade",
            first="10:00",
            count=1,
            base=("101.0", "100.0", "100.6", "101.0"),
            not_before=generator.SIGNAL_CLOSE,
        )


# --------------------------------------------------------------------------- oracles


def test_every_case_has_both_files_and_a_derivation_heading() -> None:
    derivations = DERIVATIONS.read_text(encoding="utf-8")
    headings = {line[3:].strip() for line in derivations.splitlines() if line.startswith("## ")}
    case_names = {path.name for path in _committed_cases()}
    assert case_names == set(REQUIRED_CASES)
    for name in sorted(case_names):
        assert (FIXTURE_ROOT / name / "input.json").is_file(), f"{name}: input.json is missing"
        assert (FIXTURE_ROOT / name / "expected.json").is_file(), (
            f"{name}: expected.json is missing"
        )
        assert name in headings, f"{name}: DERIVATIONS.md has no '## {name}' section"


def test_derivations_states_the_independence_rule() -> None:
    text = DERIVATIONS.read_text(encoding="utf-8")
    assert "never from the output of the code under test" in text
    assert "python -c" in text


def test_expected_json_lists_hand_written_fields_only() -> None:
    for case_dir in _committed_cases():
        expected = _json(case_dir / "expected.json")
        assert set(expected) <= {"derivation", "trades", "run_summary"}, case_dir.name
        assert expected["trades"], f"{case_dir.name}: no expected trade"
        for trade in expected["trades"]:
            extra = set(trade) - HAND_FIELDS
            assert not extra, (
                f"{case_dir.name}: fields only a simulator output has: {sorted(extra)}"
            )
        assert set(expected["run_summary"]) <= SUMMARY_FIELDS, case_dir.name
        assert expected["derivation"].endswith(f"#{case_dir.name}")


# --------------------------------------------------------------------------- research-gate traps


def test_no_fixture_file_name_starts_with_experiment_or_backtest() -> None:
    names = [path.name for path in FIXTURE_ROOT.rglob("*") if path.is_file()]
    assert names
    bad = [name for name in names if name.lower().startswith(FORBIDDEN_NAME_PREFIXES)]
    assert not bad, f"research-gate identity-tuple trap: {bad}"
    # The same prefixes are refused for a directory (the gate matches on the file name only,
    # but a directory called experiment_x would invite a file called the same).
    bad_dirs = [
        path.name
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_dir() and path.name.lower().startswith(FORBIDDEN_NAME_PREFIXES)
    ]
    assert not bad_dirs, bad_dirs


def test_no_json_key_is_named_parameters_or_parameters_json() -> None:
    files = sorted(FIXTURE_ROOT.rglob("*.json"))
    assert files
    for path in files:
        keys = _walk_keys(_json(path))
        assert not keys & FORBIDDEN_KEYS, (
            f"{path}: research-gate tripwire keys {keys & FORBIDDEN_KEYS}"
        )
