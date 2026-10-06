"""Plan 15-02: machine-checked, hash-neutral parameter rationale (D-16, D-27).

A parameter set file may carry one `[rationale.<key>]` table per `[parameters]`
key. The tables are metadata: they never enter the canonical hash payload
(strategy_id, strategy_version, parameter_set_id, parameters), so adding them
leaves `parameter_set_hash` unchanged.

Sets are written into pytest tmp_path registries only; nothing here creates a
file under params/ (PA-01 reads every params/**/*.toml as a set).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, MarketSnapshot
from src.domain import registry
from src.domain.rationale import (
    RationaleEntry,
    UnrationalizedParameterSet,
    check_rationale,
    load_rationale,
    placeholder_keys,
)
from src.domain.registry import load_parameter_set, verify_parameter_set
from src.paper.freeze import pin_stream_epoch

from tests import geometry_builders

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_SET = REPO_ROOT / "params" / "trend-pullback" / "baseline-v5.toml"
PINS_PATH = REPO_ROOT / "tests" / "fixtures" / "phase4" / "parameters.json"

STRATEGY_ID = "trend-pullback"
SET_ID = "baseline-v5"

RationaleSpec = dict[str, dict[str, str]]


# --------------------------------------------------------------------------- #
# Helpers (imported by tests/test_paper_freeze.py).
# --------------------------------------------------------------------------- #


def parsed_params(path: Path) -> dict[str, Any]:
    """Normalized [parameters] of a set file via the registry's own parse path."""
    text = path.read_bytes().decode("utf-8")
    _version, params = registry._parse_and_validate(text, path, path.parent.name, path.stem)
    return params


def complete_rationale(
    params: dict[str, Any],
    *,
    basis: str = "DECISION",
    ref: str | None = "D046",
) -> RationaleSpec:
    """One entry per parameter key; value is the parsed parameter as a string."""
    spec: RationaleSpec = {}
    for key, value in params.items():
        entry = {"basis": basis, "value": str(value), "text": f"why {key}"}
        if ref is not None:
            entry["ref"] = ref
        spec[key] = entry
    return spec


def render_rationale(spec: RationaleSpec) -> str:
    """Render rationale tables as TOML text (JSON strings are valid TOML basic strings)."""
    blocks: list[str] = []
    for key, entry in spec.items():
        lines = [f"[rationale.{key}]"]
        for field, value in entry.items():
            lines.append(f"{field} = {json.dumps(value)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def write_set(
    root: Path,
    *,
    spec: RationaleSpec | None,
    strategy_id: str = STRATEGY_ID,
    set_id: str = SET_ID,
) -> Path:
    """Copy baseline-v5 into root/<strategy_id>/<set_id>.toml and append rationale tables."""
    base_text = BASE_SET.read_bytes().decode("utf-8")
    if spec is not None:
        base_text = base_text.rstrip("\n") + "\n\n" + render_rationale(spec)
    path = root / strategy_id / f"{set_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base_text.encode("utf-8"))
    return path


def write_rationalized_set(
    root: Path,
    *,
    placeholder_key: str | None = None,
    set_id: str = SET_ID,
) -> Path:
    """Write a fully rationalized copy of baseline-v5, optionally with one PLACEHOLDER key."""
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    if placeholder_key is not None:
        spec[placeholder_key] = {
            "basis": "PLACEHOLDER",
            "value": str(params[placeholder_key]),
            "text": "seed value, not yet justified",
        }
    return write_set(root, spec=spec, set_id=set_id)


# --------------------------------------------------------------------------- #
# Task 1 tracer behaviors.
# --------------------------------------------------------------------------- #


def test_rationale_tables_do_not_change_parameter_set_hash(tmp_path: Path) -> None:
    from src.paper.freeze import _load_parameter_set_with_root

    bare_root = tmp_path / "bare"
    rich_root = tmp_path / "rich"
    bare = write_set(bare_root, spec=None)
    rich = write_rationalized_set(rich_root)
    assert "[rationale." not in bare.read_bytes().decode("utf-8")
    assert "[rationale." in rich.read_bytes().decode("utf-8")

    bare_set = _load_parameter_set_with_root(STRATEGY_ID, SET_ID, bare_root)
    rich_set = _load_parameter_set_with_root(STRATEGY_ID, SET_ID, rich_root)
    assert bare_set.parameter_set_hash == rich_set.parameter_set_hash
    assert bare_set.params == rich_set.params


def test_check_rationale_clean_for_complete_set(tmp_path: Path) -> None:
    path = write_rationalized_set(tmp_path)
    assert check_rationale(path) == []


def test_check_rationale_reports_missing_entry(tmp_path: Path) -> None:
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    del spec["swing_lookback"]
    path = write_set(tmp_path, spec=spec)
    problems = check_rationale(path)
    assert len(problems) == 1
    assert "swing_lookback" in problems[0]
    assert "missing" in problems[0]


def test_check_rationale_reports_every_key_when_no_rationale_at_all(tmp_path: Path) -> None:
    path = write_set(tmp_path, spec=None)
    problems = check_rationale(path)
    assert len(problems) == len(parsed_params(path))
    assert problems == sorted(problems)


def test_check_rationale_reports_extra_entry(tmp_path: Path) -> None:
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    spec["not_a_parameter"] = {"basis": "STRUCTURAL", "value": "1", "text": "stray"}
    path = write_set(tmp_path, spec=spec)
    problems = check_rationale(path)
    assert len(problems) == 1
    assert "not_a_parameter" in problems[0]


def test_placeholder_keys_returns_sorted_placeholder_keys(tmp_path: Path) -> None:
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    for key in ("sl_buffer_atr", "minimum_rr"):
        spec[key] = {"basis": "PLACEHOLDER", "value": str(params[key]), "text": "seed"}
    path = write_set(tmp_path, spec=spec)
    assert placeholder_keys(path) == ("minimum_rr", "sl_buffer_atr")


def test_placeholder_keys_empty_without_rationale(tmp_path: Path) -> None:
    path = write_set(tmp_path, spec=None)
    assert placeholder_keys(path) == ()


# --------------------------------------------------------------------------- #
# Task 2 - the remaining rules, hash neutrality on every committed set.
# --------------------------------------------------------------------------- #


def _problems_with(tmp_path: Path, key: str, entry: dict[str, str]) -> list[str]:
    """check_rationale problems after replacing one key's entry in a complete set."""
    spec = complete_rationale(parsed_params(BASE_SET))
    spec[key] = entry
    return check_rationale(write_set(tmp_path, spec=spec))


def test_check_rationale_reports_empty_text(tmp_path: Path) -> None:
    problems = _problems_with(
        tmp_path,
        "swing_lookback",
        {"basis": "STRUCTURAL", "value": "20", "text": "   "},
    )
    assert len(problems) == 1
    assert "swing_lookback" in problems[0]
    assert "text" in problems[0]


def test_check_rationale_reports_unknown_basis(tmp_path: Path) -> None:
    problems = _problems_with(
        tmp_path,
        "swing_lookback",
        {"basis": "INERT", "value": "20", "text": "x"},
    )
    assert len(problems) == 1
    assert "swing_lookback" in problems[0]
    assert "INERT" in problems[0]


def test_check_rationale_reports_missing_basis(tmp_path: Path) -> None:
    problems = _problems_with(tmp_path, "swing_lookback", {"value": "20", "text": "x"})
    assert len(problems) == 1
    assert "swing_lookback" in problems[0]
    assert "basis" in problems[0]


def test_check_rationale_reports_non_string_value_field(tmp_path: Path) -> None:
    path = write_set(tmp_path, spec=complete_rationale(parsed_params(BASE_SET)))
    text = path.read_bytes().decode("utf-8")
    needle = '[rationale.swing_lookback]\nbasis = "DECISION"\nvalue = "20"'
    assert needle in text
    path.write_bytes(
        text.replace(needle, '[rationale.swing_lookback]\nbasis = "DECISION"\nvalue = 20').encode()
    )
    problems = check_rationale(path)
    assert len(problems) == 1
    assert "swing_lookback" in problems[0]
    assert "value" in problems[0]


def test_check_rationale_reports_value_mismatch(tmp_path: Path) -> None:
    problems = _problems_with(
        tmp_path,
        "zone_tolerance_atr",
        {"basis": "DECISION", "value": "0.6", "text": "x", "ref": "D046"},
    )
    assert len(problems) == 1
    assert "zone_tolerance_atr" in problems[0]
    assert "0.6" in problems[0]


def test_check_rationale_accepts_numerically_equal_value_spelling(tmp_path: Path) -> None:
    # minimum_rr = 2.0 normalizes to int 2; partial_fill_fraction = 1.0 to int 1.
    spec = complete_rationale(parsed_params(BASE_SET))
    spec["minimum_rr"] = {"basis": "DECISION", "value": "2.0", "text": "x", "ref": "D046"}
    spec["partial_fill_fraction"] = {"basis": "STRUCTURAL", "value": "1.00", "text": "x"}
    assert check_rationale(write_set(tmp_path, spec=spec)) == []


def test_check_rationale_reports_unparseable_numeric_value(tmp_path: Path) -> None:
    problems = _problems_with(
        tmp_path,
        "zone_tolerance_atr",
        {"basis": "DECISION", "value": "half", "text": "x", "ref": "D046"},
    )
    assert len(problems) == 1
    assert "zone_tolerance_atr" in problems[0]
    assert "half" in problems[0]


def test_check_rationale_compares_string_parameters_exactly(tmp_path: Path) -> None:
    bad = _problems_with(
        tmp_path / "bad",
        "funding_treatment",
        {"basis": "STRUCTURAL", "value": "additive", "text": "x"},
    )
    assert len(bad) == 1
    assert "funding_treatment" in bad[0]
    good = _problems_with(
        tmp_path / "good",
        "funding_treatment",
        {"basis": "STRUCTURAL", "value": "ADDITIVE", "text": "x"},
    )
    assert good == []


def test_check_rationale_reports_experiment_without_ref(tmp_path: Path) -> None:
    problems = _problems_with(
        tmp_path,
        "swing_lookback",
        {"basis": "EXPERIMENT", "value": "20", "text": "x"},
    )
    assert len(problems) == 1
    assert "swing_lookback" in problems[0]
    assert "ref" in problems[0]


def test_check_rationale_accepts_experiment_with_ref(tmp_path: Path) -> None:
    problems = _problems_with(
        tmp_path,
        "swing_lookback",
        {"basis": "EXPERIMENT", "value": "20", "text": "x", "ref": "EXP-15-A"},
    )
    assert problems == []


def test_check_rationale_reports_decision_and_cost_guard_without_d_number(
    tmp_path: Path,
) -> None:
    for basis in ("DECISION", "COST_GUARD"):
        for ref in (None, "046", "D46", "D0461", "decision 46"):
            entry = {"basis": basis, "value": "20", "text": "x"}
            if ref is not None:
                entry["ref"] = ref
            problems = _problems_with(tmp_path / f"{basis}-{ref}", "swing_lookback", entry)
            assert len(problems) == 1, (basis, ref, problems)
            assert "swing_lookback" in problems[0]
            assert "ref" in problems[0]


def test_check_rationale_structural_and_placeholder_need_no_ref(tmp_path: Path) -> None:
    for basis in ("STRUCTURAL", "PLACEHOLDER"):
        problems = _problems_with(
            tmp_path / basis,
            "swing_lookback",
            {"basis": basis, "value": "20", "text": "x"},
        )
        assert problems == []


def test_check_rationale_output_is_sorted_and_deterministic(tmp_path: Path) -> None:
    spec = complete_rationale(parsed_params(BASE_SET))
    del spec["swing_lookback"]
    spec["zz_extra"] = {"basis": "STRUCTURAL", "value": "1", "text": "x"}
    spec["risk_rate"] = {"basis": "NOPE", "value": "0.005", "text": "x"}
    path = write_set(tmp_path, spec=spec)
    first = check_rationale(path)
    assert len(first) == 3
    assert first == sorted(first)
    assert check_rationale(path) == first


def test_load_rationale_reads_entries_and_rejects_malformed(tmp_path: Path) -> None:
    params = parsed_params(BASE_SET)
    entries = load_rationale(write_rationalized_set(tmp_path / "ok"))
    assert set(entries) == set(params)
    assert entries["minimum_rr"] == RationaleEntry(
        key="minimum_rr", basis="DECISION", value="2", text="why minimum_rr", ref="D046"
    )

    spec = complete_rationale(params)
    spec["minimum_rr"] = {"basis": "DECISION", "text": "x", "ref": "D046"}
    with pytest.raises(ValueError, match="minimum_rr"):
        load_rationale(write_set(tmp_path / "bad", spec=spec))


def test_rationale_hash_neutral_on_every_committed_set(tmp_path: Path) -> None:
    pins_doc = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    pins = pins_doc["parameter_sets"]
    assert pins, "no pinned sets collected"
    checked = 0
    for pin in pins:
        strategy_id = pin["strategy_id"]
        set_id = pin["parameter_set_id"]
        source = REPO_ROOT / "params" / strategy_id / f"{set_id}.toml"
        text = source.read_bytes().decode("utf-8")
        params = parsed_params(source)
        if "[rationale." in text:
            # Phase 15 sets carry their own rationale tables: the pin verifies as written.
            verify_parameter_set(source, pin["parameter_set_hash"])
            assert (strategy_id, set_id) in PHASE15_SETS
            checked += 1
            continue
        spec = {
            key: {"basis": "PLACEHOLDER", "value": str(value), "text": "seed"}
            for key, value in params.items()
        }
        target = tmp_path / strategy_id / f"{set_id}.toml"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = text.rstrip("\r\n") + "\n\n" + render_rationale(spec)
        target.write_bytes(body.encode("utf-8"))
        # The pinned hash must still verify with the rationale block appended.
        verify_parameter_set(target, pin["parameter_set_hash"])
        assert check_rationale(target) == []
        assert placeholder_keys(target) == tuple(sorted(params))
        checked += 1
    assert checked == len(pins)


# --------------------------------------------------------------------------- #
# Phase 15 sets (plan 15-08): the real files under params/, justified value by value.
# --------------------------------------------------------------------------- #

# The five Phase 15 sets: three baseline-v6 candidates and the two -v4 comparison baselines.
PHASE15_SETS: tuple[tuple[str, str], ...] = (
    ("trend-pullback", "baseline-v6"),
    ("breakout-retest", "baseline-v6"),
    ("range-mr", "baseline-v6"),
    ("trend-pullback", "baseline-no-trade-v4"),
    ("trend-pullback", "baseline-simple-trend-v4"),
)

# PLACEHOLDER keys exactly as ratified at checkpoint 15-08-01 (recorded in 15-08-SUMMARY.md).
PHASE15_PLACEHOLDERS: dict[tuple[str, str], tuple[str, ...]] = {
    ("trend-pullback", "baseline-v6"): (
        "cluster_cap",
        "constraint_snapshot_ttl_seconds",
        "entry_buffer_atr",
        "funding_treatment",
        "max_aggregate_open_risk",
        "max_open_positions",
        "min_stop_atr",
        "minimum_rr",
        "pivot_left_bars",
        "pivot_right_bars",
        "signal_expiry_hours",
        "sl_buffer_atr",
        "slippage_model",
        "spread_fill_assumptions",
        "swing_lookback",
        "zone_tolerance_atr",
    ),
    # The -v4 baselines take the v6 values; the ratified overrides (D054) are DECISION rows,
    # so they leave the PLACEHOLDER list: minimum_rr (no-trade) and zone_tolerance_atr plus
    # minimum_rr (simple-trend).
    ("trend-pullback", "baseline-no-trade-v4"): (
        "cluster_cap",
        "constraint_snapshot_ttl_seconds",
        "entry_buffer_atr",
        "funding_treatment",
        "max_aggregate_open_risk",
        "max_open_positions",
        "min_stop_atr",
        "pivot_left_bars",
        "pivot_right_bars",
        "signal_expiry_hours",
        "sl_buffer_atr",
        "slippage_model",
        "spread_fill_assumptions",
        "swing_lookback",
        "zone_tolerance_atr",
    ),
    ("trend-pullback", "baseline-simple-trend-v4"): (
        "cluster_cap",
        "constraint_snapshot_ttl_seconds",
        "entry_buffer_atr",
        "funding_treatment",
        "max_aggregate_open_risk",
        "max_open_positions",
        "min_stop_atr",
        "pivot_left_bars",
        "pivot_right_bars",
        "signal_expiry_hours",
        "sl_buffer_atr",
        "slippage_model",
        "spread_fill_assumptions",
        "swing_lookback",
    ),
    ("breakout-retest", "baseline-v6"): (
        "atr_period",
        "cluster_cap",
        "constraint_snapshot_ttl_seconds",
        "entry_buffer_atr",
        "funding_treatment",
        "max_aggregate_open_risk",
        "max_open_positions",
        "min_stop_atr",
        "minimum_rr",
        "retest_depth_atr",
        "retest_window_bars",
        "signal_expiry_hours",
        "sl_buffer_atr",
        "slippage_model",
        "spread_fill_assumptions",
        "swing_lookback",
        "zone_tolerance_atr",
    ),
    ("range-mr", "baseline-v6"): (
        "atr_period",
        "cluster_cap",
        "constraint_snapshot_ttl_seconds",
        "entry_buffer_atr",
        "funding_treatment",
        "max_aggregate_open_risk",
        "max_open_positions",
        "min_stop_atr",
        "minimum_rr",
        "pivot_left_bars",
        "pivot_right_bars",
        "range_break_buffer_atr",
        "regime_filter_lookback",
        "signal_expiry_hours",
        "sl_buffer_atr",
        "slippage_model",
        "spread_fill_assumptions",
        "swing_lookback",
        "touch_tolerance_atr",
        "zone_aging_bars",
        "zone_min_touches",
        "zone_tolerance_atr",
    ),
}


def _phase15_path(strategy_id: str, set_id: str) -> Path:
    return REPO_ROOT / "params" / strategy_id / f"{set_id}.toml"


@pytest.mark.parametrize(("strategy_id", "set_id"), PHASE15_SETS)
def test_phase15_set_rationale_is_complete_and_placeholders_are_refused(
    strategy_id: str, set_id: str
) -> None:
    path = _phase15_path(strategy_id, set_id)
    assert check_rationale(path) == []
    assert set(load_rationale(path)) == set(parsed_params(path))
    assert placeholder_keys(path) == PHASE15_PLACEHOLDERS[(strategy_id, set_id)]
    assert placeholder_keys(path), "a PLACEHOLDER-free set would be pinnable for paper"
    with pytest.raises(UnrationalizedParameterSet, match="PLACEHOLDER keys"):
        pin_stream_epoch(
            strategy_id=strategy_id,
            parameter_set_id=set_id,
            opened_at_utc=datetime(2026, 10, 6, tzinfo=UTC),
        )


def test_trend_pullback_v6_plans_a_stop_below_the_entry_zone() -> None:
    parameter_set = load_parameter_set("trend-pullback", "baseline-v6")
    assert parameter_set.strategy_version == "v5.0.0"
    assert parameter_set.params["geometry_version"] == 1
    account = AccountState(equity=Decimal("1000"), risk_rate=Decimal("0.005"))
    setup, context = geometry_builders.family_a_long_window()
    result = evaluate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT", setup_candles=setup, context_candles=context, source_timeframe="1h"
        ),
        account_state=account,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.signal is not None, result.reason_code
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=setup[-1].close_time_utc,
    )
    assert planned.trade_plan is not None, planned.reason_code
    assert planned.trade_plan.stop_loss_price < planned.trade_plan.entry_min_price


# --------------------------------------------------------------------------- #
# Phase 15 comparison baselines (plan 15-09, D-26): -v4 under the corrected geometry.
# --------------------------------------------------------------------------- #

_V4_BASELINES: tuple[str, str] = ("baseline-no-trade-v4", "baseline-simple-trend-v4")
# Overrides versus trend-pullback baseline-v6, exactly as ratified at checkpoint 15-08-01.
_V4_OVERRIDES: dict[str, dict[str, Decimal | int]] = {
    "baseline-no-trade-v4": {"minimum_rr": 100},
    "baseline-simple-trend-v4": {
        "zone_tolerance_atr": Decimal("1.0"),
        "minimum_rr": Decimal("0.5"),
    },
}


@pytest.mark.parametrize("set_id", _V4_BASELINES)
def test_v4_baseline_equals_v6_values_except_the_ratified_overrides(set_id: str) -> None:
    v6 = parsed_params(_phase15_path("trend-pullback", "baseline-v6"))
    v4 = parsed_params(_phase15_path("trend-pullback", set_id))
    assert set(v4) == set(v6)
    assert "min_stop_atr" in v4
    differing = {key for key in v6 if v4[key] != v6[key]}
    assert differing == set(_V4_OVERRIDES[set_id])
    for key, value in _V4_OVERRIDES[set_id].items():
        assert Decimal(str(v4[key])) == Decimal(str(value))
    parameter_set = load_parameter_set("trend-pullback", set_id)
    assert parameter_set.strategy_version == "v5.0.0"
    assert parameter_set.params["geometry_version"] == 1


def _family_a_signal(parameter_set: Any, account: AccountState) -> tuple[Any, Any]:
    setup, context = geometry_builders.family_a_long_window()
    result = evaluate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT", setup_candles=setup, context_candles=context, source_timeframe="1h"
        ),
        account_state=account,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.signal is not None, result.reason_code
    return result.signal, setup


def test_no_trade_v4_is_rejected_by_the_rr_gate_on_a_family_a_window() -> None:
    parameter_set = load_parameter_set("trend-pullback", "baseline-no-trade-v4")
    account = AccountState(equity=Decimal("1000"), risk_rate=Decimal("0.005"))
    signal, setup = _family_a_signal(parameter_set, account)
    planned = plan(
        signal=signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=setup[-1].close_time_utc,
    )
    # The geometry invariants pass first (D-26): the only reason left is the RR floor.
    assert planned.trade_plan is None
    assert planned.reason_code == "RR_TOO_LOW"


def test_simple_trend_v4_plans_a_stop_below_the_entry_zone_on_a_family_a_window() -> None:
    parameter_set = load_parameter_set("trend-pullback", "baseline-simple-trend-v4")
    account = AccountState(equity=Decimal("1000"), risk_rate=Decimal("0.005"))
    signal, setup = _family_a_signal(parameter_set, account)
    planned = plan(
        signal=signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=setup[-1].close_time_utc,
    )
    assert planned.trade_plan is not None, planned.reason_code
    assert planned.trade_plan.stop_loss_price < planned.trade_plan.entry_min_price


@pytest.mark.parametrize("set_id", _V4_BASELINES)
def test_v4_baselines_are_not_candidates_of_the_trend_pullback_family(set_id: str) -> None:
    from src.analytics.family import is_baseline_parameter_set_id

    assert is_baseline_parameter_set_id(set_id) is True
