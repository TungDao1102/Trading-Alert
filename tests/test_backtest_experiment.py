"""Tests for the Phase 6 experiment registry (plan 06-02) and the typed record (plan 14-15).

Per D-03 + BACKTEST_SPEC §11 + RESEARCH_PROTOCOL §5: every experiment
record carries the canonical six-field identity tuple
(`experimentId`, `strategyVersion`, `parameterSetHash` + runtime
`parameterSetId` alongside, `dataSnapshotId`, `codeVersion`,
`costModelHash`) plus dataset range, symbol universe, timeframe, full
parameters, cost assumptions, results, and notes. A record missing any
field fails the acceptance gate.

Phase 14 (plan 14-15, D-22, F-118, BKTS-04): the record also carries the typed,
validated fields (NO_TRADE counts, tie-break, timeframes, parameter and cost values,
semantics version, code commit and dirty flag, counts, windows, allowed gaps, split
role and boundaries). An invalid record cannot be constructed, and `experiment_id`
binds the semantics version and the split. Every record in this file comes from the
shared factory in `tests/backtest_case_helpers.py`.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.canonical import canonical_decimal_text, sha256_hex
from src.domain.registry import UnregisteredParameterSet, load_parameter_set

from tests.backtest_case_helpers import (
    CODE_COMMIT,
    DEFAULT_COST_MODEL,
    RECORD_END,
    RECORD_START,
    assemble_kwargs,
    make_experiment_record,
    strategy_run_summary,
)

PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"


# --------------------------------------------------------------------------- #
# Helpers — load input/expected pair from a phase6 case directory.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_bound_input(case_dir: Path) -> dict:
    """A case input that carries the dataset id `_simple_trend_record` binds (WR-03)."""
    return {**_load_input(case_dir), "dataset_id": "3" * 64}


def _load_expected(case_dir: Path) -> dict:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _build_cost_model(cost_dict: dict):
    """Build a CostModel from a dict (delegates to costs.build_cost_model)."""
    from src.backtest.costs import build_cost_model

    return build_cost_model(cost_dict)


def _assemble(**overrides: Any):
    """`assemble` over the shared valid baseline-v5 inputs, with keyword overrides."""
    from src.backtest.experiment import assemble

    return assemble(**assemble_kwargs(**overrides))


# --------------------------------------------------------------------------- #
# Test 1 — assemble with complete inputs returns stable 64-hex identity.
# --------------------------------------------------------------------------- #


def test_experiment_assemble_stable_64_hex_identity() -> None:
    """Beh. 1: assemble with complete inputs returns ExperimentRecord with
    six 64-hex identity fields and a stable experiment_id across reruns.

    Per D-03: every experiment record carries the canonical six-field
    identity tuple. All hash fields must be 64-hex strings; the
    experiment_id must be stable across reruns.
    """
    record_a = _assemble()
    record_b = _assemble()

    # All six identity fields must be 64-hex strings.
    for field in (
        "experiment_id",
        "parameter_set_hash",
        "data_snapshot_id",
        "cost_model_hash",
    ):
        value = getattr(record_a, field)
        assert isinstance(value, str), f"{field} must be str, got {type(value).__name__}"
        assert len(value) == 64, f"{field} must be 64-hex, got len={len(value)}"
        assert all(c in "0123456789abcdef" for c in value), (
            f"{field} must be lowercase hex, got {value!r}"
        )

    # experiment_id must be stable across reruns.
    assert record_a.experiment_id == record_b.experiment_id, (
        "experiment_id must be stable across reruns"
    )


# --------------------------------------------------------------------------- #
# Test 2 — assemble with missing identity field raises IncompleteExperimentRecord.
# --------------------------------------------------------------------------- #


def test_experiment_assemble_missing_field_raises() -> None:
    """Beh. 2: assemble with any missing identity field raises
    IncompleteExperimentRecord (D-03 acceptance gate).

    Per D-03: a record missing any field fails the acceptance gate.
    """
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord):
        _assemble(data_snapshot_id="")


# --------------------------------------------------------------------------- #
# Test 3 — reproduce with the recorded tuple returns byte-identical trades.
# --------------------------------------------------------------------------- #


def test_experiment_reproduce_byte_identical() -> None:
    """Beh. 3: reproduce with the recorded tuple returns byte-identical
    trade lists via canonical sha256 comparison (D-03 reproducibility).

    Per D-03: reproduction = re-running the recorded six-field tuple
    yields byte-identical trade lists.
    """
    from src.backtest.experiment import reproduce

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)

    # Reproduce twice — both runs must yield byte-identical trade lists.
    trades_a = reproduce(record, simulator_inputs=case)
    trades_b = reproduce(record, simulator_inputs=case)
    assert trades_a, "the simple-trend baseline must yield trades to compare"
    digest_a = sha256_hex({"trades": [t.to_dict() for t in trades_a]})
    digest_b = sha256_hex({"trades": [t.to_dict() for t in trades_b]})
    assert digest_a == digest_b, f"reproduce digests differ: {digest_a} != {digest_b}"


# --------------------------------------------------------------------------- #
# Test 4 — unregistered parameterSetId raises UnregisteredParameterSet.
# --------------------------------------------------------------------------- #


def test_experiment_unregistered_set_fails_closed() -> None:
    """Beh. 4: assemble with an unregistered parameterSetId raises
    UnregisteredParameterSet (Phase-1 D-07, Phase-3 D-05).

    Per D-03: any run without a registered parameterSetId + matching
    hash fails closed.
    """
    with pytest.raises(UnregisteredParameterSet):
        _assemble(parameter_set_id="does-not-exist")


# --------------------------------------------------------------------------- #
# Test 5 — baseline_no_trade returns an empty trade list.
# --------------------------------------------------------------------------- #


def test_baseline_no_trade_returns_empty_trades() -> None:
    """Beh. 5: baseline_no_trade over the fixture returns an empty
    trade list (minimum_rr=100 forces every plan to fail the RR gate).

    Per BACKTEST_SPEC §9: every candidate is compared against declared
    baselines (no-trade + simple-trend at minimum). The no-trade
    baseline degenerates minimum_rr so no filled trades occur.
    """
    from src.backtest.experiment import baseline_no_trade

    case_dir = PHASE6_FIXTURES_DIR / "baselines" / "no_trade"
    case_input = _load_input(case_dir)
    trades = baseline_no_trade(case_input)
    assert len(trades) == 0, (
        f"baseline_no_trade must return empty trade list, got {len(trades)} trades"
    )


# --------------------------------------------------------------------------- #
# Test 6 — baseline_simple_trend returns a single-direction trade list.
# --------------------------------------------------------------------------- #


def test_baseline_simple_trend_returns_single_direction() -> None:
    """Beh. 6: baseline_simple_trend over the fixture returns a
    deterministic single-direction trade list (looser minimum_rr +
    single-condition trend filter).

    Per BACKTEST_SPEC §9: the simple-trend baseline uses a single-
    condition trend filter so the simulator emits a deterministic
    single-direction trade list.
    """
    from src.backtest.experiment import baseline_simple_trend

    case_dir = PHASE6_FIXTURES_DIR / "baselines" / "simple_trend"
    case_input = _load_input(case_dir)
    trades = baseline_simple_trend(case_input)
    assert len(trades) >= 1, (
        f"baseline_simple_trend must return at least 1 trade, got {len(trades)}"
    )
    # All trades must be the same direction (single-direction).
    directions = {t.direction for t in trades}
    assert len(directions) == 1, (
        f"baseline_simple_trend must be single-direction, got directions={directions}"
    )


# --------------------------------------------------------------------------- #
# Test 7 — costModelHash is spelling-independent, value-sensitive (D-15).
# --------------------------------------------------------------------------- #


def test_cost_model_hash_precision_discipline() -> None:
    """Beh. 7: costModelHash is identical for equivalent spellings
    (fee_rate_entry 0.00020 vs 0.0002) and differs for a genuine value
    change (D-15 canonical numeric text).

    Supersedes the Phase 6 D-12 trailing-precision rule: cost identity is
    the VALUE, not its spelling, so a fixture spelling can never make a
    correct registry binding fail (F-608). Registry parameter_set_hash keeps
    trailing precision; only the cost hash canonicalizes.
    """
    from src.backtest.costs import build_cost_model

    cost_a = build_cost_model(
        {
            "fee_rate_entry": "0.00020",
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "1.0",
        }
    )
    cost_b = build_cost_model(
        {
            "fee_rate_entry": "0.0002",
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "1.0",
        }
    )
    assert cost_a.cost_model_hash == cost_b.cost_model_hash, (
        "costModelHash must be equal for equivalent spellings 0.00020 vs 0.0002"
    )
    cost_c = build_cost_model(
        {
            "fee_rate_entry": "0.0003",
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "1.0",
        }
    )
    assert cost_a.cost_model_hash != cost_c.cost_model_hash, (
        "costModelHash must differ for a genuine value change"
    )


# --------------------------------------------------------------------------- #
# Test 8 — verify_experiment returns None when reproducible.
# --------------------------------------------------------------------------- #


def test_verify_experiment_returns_none_when_reproducible() -> None:
    """Beh. 8: verify_experiment returns None when the recorded tuple
    reproduces byte-identically; raises ExperimentReproducibilityBroken
    on drift.

    Per D-03: verify_experiment is the runtime tripwire for
    reproducibility.
    """
    from src.backtest.experiment import verify_experiment

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)

    # verify_experiment must return None when reproducible.
    result = verify_experiment(record, simulator_inputs=case)
    assert result is None, f"verify_experiment must return None when reproducible, got {result!r}"


# --------------------------------------------------------------------------- #
# Test 9 — empty-input handling: zero strategy bars yields a valid record.
# --------------------------------------------------------------------------- #


def test_empty_input_yields_valid_record_but_cannot_be_reproduced_vacuously() -> None:
    """Beh. 9: a record over a run with no trades is valid, but empty simulator inputs are
    refused by reproduce/verify_experiment instead of reporting "reproducible" (WR-03).
    """
    from src.backtest.experiment import (
        ExperimentReproducibilityBroken,
        reproduce,
        verify_experiment,
    )

    record = _assemble(run_summary=strategy_run_summary(no_trade_counts={}, end_of_data_count=0))
    assert record.no_trade_counts == ()

    with pytest.raises(ExperimentReproducibilityBroken, match="empty"):
        reproduce(record, simulator_inputs={})
    with pytest.raises(ExperimentReproducibilityBroken, match="empty"):
        verify_experiment(record, simulator_inputs={})
    # A missing key is a typed failure, not a KeyError.
    partial = {key: value for key, value in _gap_simulator_inputs().items() if key != "cost_model"}
    with pytest.raises(ExperimentReproducibilityBroken, match="cost_model"):
        reproduce(record, simulator_inputs=partial)


# --------------------------------------------------------------------------- #
# Test 10 — run-twice record-stability: identical experiment_id across reruns.
# --------------------------------------------------------------------------- #


def test_run_twice_record_stability() -> None:
    """Beh. 10: two assemble() calls with the same inputs produce
    identical experiment_id (REFACTOR task).

    Per D-03: experiment_id is stable across reruns. The canonicalizer
    sorts dict keys before hashing, so the order in which inputs are
    provided does not affect the digest.
    """
    record_a = _assemble()
    record_b = _assemble()
    assert record_a.experiment_id == record_b.experiment_id, (
        "experiment_id must be stable across reruns"
    )
    assert record_a == record_b


# --------------------------------------------------------------------------- #
# Test 11 — universe-order stability: input order cannot change identity.
# --------------------------------------------------------------------------- #


def test_universe_order_stability() -> None:
    """Beh. 11: universe_hash sorts the symbol list before hashing so
    input order cannot change identity (REFACTOR task).

    Per D-03: the universe hash must be stable across input orderings.
    Symbols are sorted alphabetically before hashing.
    """
    record_a = _assemble(universe=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    record_b = _assemble(universe=["SOLUSDT", "BTCUSDT", "ETHUSDT"])
    record_c = _assemble(universe=["ETHUSDT", "SOLUSDT", "BTCUSDT"])
    assert record_a.experiment_id == record_b.experiment_id == record_c.experiment_id, (
        "experiment_id must be stable across universe orderings"
    )


# --------------------------------------------------------------------------- #
# Nyquist gap-fill (review-fix iteration 1): CR-03a/b/c, CR-05..CR-11.
# --------------------------------------------------------------------------- #


def _gap_cost_dict() -> dict:
    return {
        "fee_rate_entry": "0.0002",
        "fee_rate_exit": "0.0005",
        "funding_treatment": "ADDITIVE",
        "expected_slippage": "0.0001",
        "slippage_model": "FIXED_BPS",
        "spread_fill_assumptions": "FULL_FILL",
        "partial_fill_fraction": "0.5",
    }


def _gap_simulator_inputs() -> dict:
    return {
        "strategy_id": "trend-pullback",
        "parameter_set_id": "baseline-v5",
        "strategy_version": "v4.0.0",
        "cost_model": dict(DEFAULT_COST_MODEL),
        "data_window": {
            "start_utc": RECORD_START.isoformat(),
            "end_utc": RECORD_END.isoformat(),
        },
    }


def test_cr03a_reproduce_rejects_mismatched_simulator_inputs() -> None:
    """CR-03a: reproduce() rejects inputs mismatched to the record."""
    from src.backtest.experiment import (
        ExperimentReproducibilityBroken,
        reproduce,
    )

    record = _assemble()
    good = _gap_simulator_inputs()

    bad_set = dict(good, parameter_set_id="baseline-no-trade-v3")
    with pytest.raises(ExperimentReproducibilityBroken):
        reproduce(record, simulator_inputs=bad_set)

    bad_version = dict(good, strategy_version="v9.9.9")
    with pytest.raises(ExperimentReproducibilityBroken):
        reproduce(record, simulator_inputs=bad_version)

    bad_cost = dict(good, cost_model=dict(DEFAULT_COST_MODEL, fee_rate_entry="0.0099"))
    with pytest.raises(ExperimentReproducibilityBroken):
        reproduce(record, simulator_inputs=bad_cost)


def test_cr03b_reproduced_trades_carry_typed_decimal_datetime_fields() -> None:
    """CR-03b: reproduced TradeRecords hold typed Decimal/datetime fields."""
    from src.backtest.experiment import reproduce

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    assert case["parameter_set_id"] == "baseline-simple-trend-v3"
    record = _simple_trend_record(case)
    trades = reproduce(record, simulator_inputs=case)
    assert len(trades) >= 1, "simple-trend baseline must yield filled trades"
    decimal_fields = (
        "entry_price",
        "quantity",
        "exit_price",
        "realized_pnl",
        "realized_risk",
        "gross_pnl",
        "entry_fee",
        "exit_fee",
        "funding_amount",
        "slippage_amount",
        "modeled_costs_per_unit",
        "planned_quantity",
        "tp1_quantity",
        "tp1_price",
    )
    datetime_fields = (
        "entry_time_utc",
        "exit_time_utc",
        "signal_close_utc",
        "tp1_time_utc",
        "resolved_at_utc",
    )
    for trade in trades:
        for fname in decimal_fields:
            value = getattr(trade, fname)
            assert value is None or isinstance(value, Decimal), (
                f"{fname} must be Decimal|None, got {type(value).__name__} "
                f"({value!r}) — stringified rebuild corrupts types"
            )
        for fname in datetime_fields:
            value = getattr(trade, fname)
            assert value is None or isinstance(value, datetime), (
                f"{fname} must be datetime|None, got {type(value).__name__}"
            )
        for fname in ("touch_no_fill_count", "funding_event_count"):
            assert type(getattr(trade, fname)) is int
        for fname in ("fallback_applied", "gap_through_stop", "constraints_extrapolated"):
            assert type(getattr(trade, fname)) is bool
        assert not isinstance(trade.entry_price, str)
        assert not isinstance(trade.exit_time_utc, str)
        # The typed rebuild lets the causal order be read off the record itself.
        assert trade.signal_close_utc is not None
        assert trade.entry_time_utc is not None
        assert trade.entry_time_utc > trade.signal_close_utc


def test_cr03c_verify_experiment_detects_engine_drift_vs_stored_digest() -> None:
    """CR-03c: verify_experiment detects drift vs the stored result digest."""
    from src.backtest.experiment import (
        ExperimentReproducibilityBroken,
        reproduce,
        trades_digest,
        verify_experiment,
    )

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")

    # No stored digest: the determinism check over a real re-run passes.
    record = _simple_trend_record(case)
    assert verify_experiment(record, simulator_inputs=case) is None

    # Forged stored digest: drift detected.
    forged = _simple_trend_record(case, result_summary_json=json.dumps({"trades_digest": "f" * 64}))
    with pytest.raises(ExperimentReproducibilityBroken):
        verify_experiment(forged, simulator_inputs=case)

    # Matching stored digest: accepted.
    matching_digest = trades_digest(reproduce(record, simulator_inputs=case))
    matching = _simple_trend_record(
        case, result_summary_json=json.dumps({"trades_digest": matching_digest})
    )
    assert verify_experiment(matching, simulator_inputs=case) is None


def test_cr05_decimal_inputs_hash_identically_to_string_inputs() -> None:
    """CR-05: Decimal cost inputs hash identically to their string spellings."""
    from src.backtest.costs import build_cost_model

    string_cost = _gap_cost_dict()
    decimal_cost = {
        key: (
            Decimal(value)
            if key
            not in {
                "funding_treatment",
                "slippage_model",
                "spread_fill_assumptions",
            }
            else value
        )
        for key, value in string_cost.items()
    }
    assert build_cost_model(decimal_cost).cost_model_hash == (
        build_cost_model(string_cost).cost_model_hash
    ), "Decimal inputs must never round-trip through str() before hashing"

    # Equivalent spellings hash equally (D-15); a genuine change still differs.
    trailing = dict(string_cost, fee_rate_entry="0.00020")
    trimmed = dict(string_cost, fee_rate_entry="0.0002")
    assert build_cost_model(trailing).cost_model_hash == (build_cost_model(trimmed).cost_model_hash)
    assert (
        build_cost_model(dict(decimal_cost, fee_rate_entry=Decimal("0.00020"))).cost_model_hash
        == build_cost_model(trailing).cost_model_hash
    )
    changed = dict(string_cost, fee_rate_entry="0.0003")
    assert build_cost_model(changed).cost_model_hash != (build_cost_model(trimmed).cost_model_hash)


def test_cr06_experiment_id_differs_across_run_type_and_strategy_id() -> None:
    """CR-06: experiment_id binds run_type and strategy_id (no collisions)."""
    candidate = _assemble(run_type="CANDIDATE")
    baseline = _assemble(run_type="BASELINE_NO_TRADE")
    assert candidate.experiment_id != baseline.experiment_id, (
        "CANDIDATE vs BASELINE_NO_TRADE over identical inputs must differ"
    )

    trend = _assemble(strategy_id="trend-pullback")
    breakout = _assemble(
        strategy_id="breakout-retest",
        cost_model=_build_cost_model(_breakout_v5_cost_slice()),
    )
    assert trend.experiment_id != breakout.experiment_id, (
        "two strategies sharing a version string must never share experiment_id"
    )


def _breakout_v5_cost_slice() -> dict:
    from src.backtest.costs import cost_slice

    return cost_slice(load_parameter_set("breakout-retest", "baseline-v5").params)


def test_cr07_baselines_enforce_degenerated_minimum_rr() -> None:
    """CR-07: baseline runners fail closed on non-degenerated candidate params."""
    from src.backtest.experiment import baseline_no_trade, baseline_simple_trend

    candidate = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")
    with pytest.raises(ValueError, match="minimum_rr"):
        baseline_no_trade(candidate)

    no_trade_case = _load_input(PHASE6_FIXTURES_DIR / "baselines" / "no_trade")
    with pytest.raises(ValueError, match="minimum_rr"):
        baseline_simple_trend(no_trade_case)


def test_cr09_forged_cost_model_hash_rejected_at_assembly() -> None:
    """CR-09: a forged cost_model_hash inconsistent with params is rejected."""
    from src.backtest.costs import CostModel, build_cost_model

    good = build_cost_model(_gap_cost_dict())
    with pytest.raises(ValueError, match="mismatch"):
        CostModel(
            fee_rate_entry=good.fee_rate_entry,
            fee_rate_exit=good.fee_rate_exit,
            funding_treatment=good.funding_treatment,
            expected_slippage=good.expected_slippage,
            slippage_model=good.slippage_model,
            spread_fill_assumptions=good.spread_fill_assumptions,
            partial_fill_fraction=good.partial_fill_fraction,
            cost_model_hash="f" * 64,
        )
    # The verified hash round-trips cleanly and binds the experiment record.
    verified = CostModel(
        fee_rate_entry=good.fee_rate_entry,
        fee_rate_exit=good.fee_rate_exit,
        funding_treatment=good.funding_treatment,
        expected_slippage=good.expected_slippage,
        slippage_model=good.slippage_model,
        spread_fill_assumptions=good.spread_fill_assumptions,
        partial_fill_fraction=good.partial_fill_fraction,
        cost_model_hash=good.cost_model_hash,
    )
    assert verified.cost_model_hash == good.cost_model_hash
    record = _assemble()
    assert record.cost_model_hash == _build_cost_model(DEFAULT_COST_MODEL).cost_model_hash


def test_cr11_baseline_tomls_carry_detector_and_cost_keys() -> None:
    """CR-11: baseline TOMLs carry atr_period + 4 cost keys from COST_MODEL."""
    import ast
    from pathlib import Path

    from src.domain.registry import load_parameter_set

    repo_root = Path(__file__).resolve().parents[1]
    tree = ast.parse((repo_root / "scripts" / "gen_phase6_fixtures.py").read_text(encoding="utf-8"))
    canonical: dict | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "COST_MODEL" for target in node.targets
        ):
            canonical = ast.literal_eval(node.value)
    assert canonical is not None, "COST_MODEL canonical source must exist"
    # Phase 14 (D-16): the generator literal must equal the code constant.
    from src.backtest.semantics import FUNDING_CONVENTION

    assert canonical["funding_convention"] == FUNDING_CONVENTION

    for parameter_set_id in (
        "baseline-no-trade-v1",
        "baseline-simple-trend-v1",
        "baseline-no-trade-v3",
        "baseline-simple-trend-v3",
    ):
        parameter_set = load_parameter_set("trend-pullback", parameter_set_id)
        assert parameter_set.params["atr_period"] == 14, (
            f"{parameter_set_id}: atr_period must match sibling baseline-v2 sets"
        )
        for key in (
            "funding_treatment",
            "slippage_model",
            "spread_fill_assumptions",
        ):
            assert str(parameter_set.params[key]) == str(canonical[key]), (
                f"{parameter_set_id}: {key}={parameter_set.params[key]!r} != "
                f"COST_MODEL canonical {canonical[key]!r}"
            )
        # partial_fill_fraction: TOML whole-number rule normalizes 1.0 to
        # int 1 while the fixture spells "1.0" — value equality binds them.
        assert Decimal(str(parameter_set.params["partial_fill_fraction"])) == (
            Decimal(str(canonical["partial_fill_fraction"]))
        ), (
            f"{parameter_set_id}: partial_fill_fraction="
            f"{parameter_set.params['partial_fill_fraction']!r} != "
            f"COST_MODEL canonical {canonical['partial_fill_fraction']!r}"
        )
        # Phase 12: the v3 baselines carry the rate keys and the stop-exit
        # slippage rate; compare by value against the generator literal.
        if parameter_set_id.endswith("-v3"):
            for key in (
                "fee_rate_entry",
                "fee_rate_exit",
                "expected_slippage",
                "exit_slippage_rate",
            ):
                assert Decimal(str(parameter_set.params[key])) == Decimal(str(canonical[key])), (
                    f"{parameter_set_id}: {key}={parameter_set.params[key]!r} != "
                    f"COST_MODEL canonical {canonical[key]!r}"
                )


# --------------------------------------------------------------------------- #
# Phase 14 (plan 14-12): baselines, reproduce and verify_experiment run the v2 engine.
# --------------------------------------------------------------------------- #


def _simple_trend_record(case: dict, *, result_summary_json: str = "{}"):
    """Assemble a typed record bound to the regenerated simple-trend baseline case (v3 set).

    The run summary is the real engine output of that case, so the typed fields are the
    ones a reproduction of the case yields.
    """
    from src.backtest.experiment import CodeVersion, assemble
    from src.backtest.simulator import run

    start = datetime.fromisoformat(case["data_window"]["start_utc"])
    end = datetime.fromisoformat(case["data_window"]["end_utc"])
    output = run(case)
    return assemble(
        parameter_set_id=case["parameter_set_id"],
        strategy_id=case["strategy_id"],
        strategy_version=case["strategy_version"],
        data_snapshot_id="3" * 64,
        code_version=CodeVersion(commit=CODE_COMMIT, dirty=False),
        cost_model=_build_cost_model(dict(case["cost_model"])),
        time_range_start_utc=start,
        time_range_end_utc=end,
        universe=list(case["symbols"]),
        run_type="BASELINE_SIMPLE_TREND",
        run_summary=output["run_summary"],
        run_identity=output,
        split_role="DEVELOPMENT",
        split_start_utc=start,
        split_end_utc=end,
        notes="plan 14-12 v2 reproduce",
        result_summary_json=result_summary_json,
    )


def test_baseline_no_trade_runs_the_engine_and_drops_the_reject_record() -> None:
    """The v2 engine emits a first-class RR_TOO_LOW REJECT record; the baseline keeps filled
    trades only, so the no-trade baseline is still the empty list."""
    from src.backtest.experiment import baseline_no_trade
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / "baselines" / "no_trade")
    assert case_input["case_input_schema"] == "backtest-case/2"
    raw = run(case_input)["trades"]
    assert [(t["entry_kind"], t["reason_code"]) for t in raw] == [("REJECT", "RR_TOO_LOW")]
    assert baseline_no_trade(case_input) == []


def test_baseline_simple_trend_keeps_the_filled_trade_of_the_v2_engine() -> None:
    from src.backtest.experiment import baseline_simple_trend
    from src.backtest.simulator import run

    case_input = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    trades = baseline_simple_trend(case_input)
    assert len(trades) == 1
    (trade,) = trades
    assert trade.entry_kind == "ENTRY_FILLED"
    assert trade.exit_kind == "SL"
    assert trade.direction == "LONG"
    # The v2 trailing fields stay strings on the rebuilt record until plan 14-15 types them
    # (_trade_from_dict), so the causal order is read from the engine output itself.
    (raw,) = run(case_input)["trades"]
    assert raw["entry_time_utc"] > raw["signal_close_utc"]


def test_reproduce_reruns_the_v2_engine_and_reproduces_byte_identical_trades() -> None:
    from src.backtest.experiment import reproduce
    from src.backtest.simulator import run

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)
    first = reproduce(record, simulator_inputs=case)
    second = reproduce(record, simulator_inputs=case)
    assert [t.to_dict() for t in first] == [t.to_dict() for t in second]
    # The rebuilt records equal the engine output record for record.
    assert [t.to_dict() for t in first] == run(case)["trades"]


def test_verify_experiment_compares_the_v2_digest_and_detects_a_changed_minute_series() -> None:
    import json as _json

    from src.backtest.experiment import ExperimentReproducibilityBroken, verify_experiment
    from src.backtest.simulator import run

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    digest = sha256_hex({"trades": run(case)["trades"]})
    matching = _simple_trend_record(
        case, result_summary_json=_json.dumps({"trades_digest": digest})
    )
    assert verify_experiment(matching, simulator_inputs=case) is None

    forged = _simple_trend_record(
        case, result_summary_json=_json.dumps({"trades_digest": "f" * 64})
    )
    with pytest.raises(ExperimentReproducibilityBroken, match="trades_digest"):
        verify_experiment(forged, simulator_inputs=case)

    # Drift: the stop minute no longer reaches the stop, so the position runs to the data end.
    # The re-run summary (END_OF_DATA count) no longer matches the typed record, which trips
    # before the digest comparison is reached (plan 14-15).
    drifted = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    for row in drifted["mark_bars_1m"]:
        if row["open_time_utc"] == "2026-09-11T10:06:00+00:00":
            row["low"] = "121.50"
    with pytest.raises(ExperimentReproducibilityBroken, match="end_of_data_count"):
        verify_experiment(matching, simulator_inputs=drifted)


# --------------------------------------------------------------------------- #
# Phase 14 (plan 14-15, Task 1): typed ExperimentRecord, identity binding, assemble refusals.
# --------------------------------------------------------------------------- #


def _canonical_value_text(value: object) -> str:
    return canonical_decimal_text(value) if isinstance(value, Decimal) else str(value)


def test_assemble_binds_the_run_summary_into_typed_fields() -> None:
    record = _assemble()
    assert record.simulator_semantics_version == "2.0.0"
    assert record.intrabar_tie_break == "STOP_FIRST"
    assert record.no_trade_counts == (("CONFLICT_WITH_OPEN_POSITION", 3), ("RR_TOO_LOW", 5))
    assert (record.timeframe, record.context_timeframe) == ("1h", "4h")
    assert (record.fallback_count, record.end_of_data_count) == (2, 1)
    assert (record.strategy_window_bars, record.context_window_bars) == (1000, 300)
    assert record.allowed_gaps == ()
    assert record.split_role == "DEVELOPMENT"
    assert (record.split_start_utc, record.split_end_utc) == (RECORD_START, RECORD_END)
    assert record.code_commit == CODE_COMMIT
    assert record.code_dirty is False
    assert record.code_version == CODE_COMMIT


def test_dirty_code_version_is_the_commit_plus_dirty() -> None:
    from src.backtest.experiment import CodeVersion

    record = _assemble(code_version=CodeVersion(commit=CODE_COMMIT, dirty=True))
    assert record.code_commit == CODE_COMMIT
    assert record.code_dirty is True
    assert record.code_version == f"{CODE_COMMIT}-dirty"


def test_parameter_and_cost_values_are_canonical_text_with_sorted_keys() -> None:
    record = _assemble()
    params = load_parameter_set("trend-pullback", "baseline-v5").params
    assert record.parameter_values == tuple(
        (key, _canonical_value_text(params[key])) for key in sorted(params)
    )
    costs = dict(record.cost_values)
    assert list(costs) == sorted(costs)
    assert costs["funding_convention"] == "MARK_NOTIONAL_SIGNED_V1"
    assert costs["fee_rate_entry"] == "0.0005"
    assert costs["partial_fill_fraction"] == "1"
    assert "exit_slippage_rate" in costs


def test_allowed_gaps_used_become_sorted_typed_gaps() -> None:
    summary = strategy_run_summary(
        allowed_gaps_used=[
            {
                "series": "funding",
                "symbol": "ETHUSDT",
                "start_utc": "2026-01-03T00:00:00+00:00",
                "end_utc": "2026-01-03T16:00:00+00:00",
            },
            {
                "series": "funding",
                "symbol": "BTCUSDT",
                "start_utc": "2026-01-02T00:00:00+00:00",
                "end_utc": "2026-01-02T16:00:00+00:00",
            },
        ]
    )
    record = _assemble(run_summary=summary)
    assert [(g.symbol, g.start_utc, g.end_utc) for g in record.allowed_gaps] == [
        ("BTCUSDT", datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 2, 16, tzinfo=UTC)),
        ("ETHUSDT", datetime(2026, 1, 3, tzinfo=UTC), datetime(2026, 1, 3, 16, tzinfo=UTC)),
    ]
    assert all(g.series == "funding" for g in record.allowed_gaps)


def test_acknowledged_gaps_of_other_series_become_typed_gaps() -> None:
    summary = strategy_run_summary(
        allowed_gaps_used=[
            {
                "series": "trade",
                "symbol": "BTCUSDT",
                "start_utc": "2026-01-02T10:30:00+00:00",
                "end_utc": "2026-01-02T10:30:00+00:00",
            },
            {
                "series": "funding",
                "symbol": "BTCUSDT",
                "start_utc": "2026-01-02T10:30:00+00:00",
                "end_utc": "2026-01-02T16:00:00+00:00",
            },
        ]
    )
    record = _assemble(run_summary=summary)
    assert [g.series for g in record.allowed_gaps] == ["trade", "funding"]


def test_the_record_has_no_free_form_parameters_field() -> None:
    from src.backtest.experiment import ExperimentRecord

    names = {f.name for f in dataclasses.fields(ExperimentRecord)}
    assert "parameters" not in names and "parameters_json" not in names
    assert {
        "no_trade_counts",
        "intrabar_tie_break",
        "timeframe",
        "context_timeframe",
        "parameter_values",
        "cost_values",
        "simulator_semantics_version",
        "code_commit",
        "code_dirty",
        "fallback_count",
        "end_of_data_count",
        "strategy_window_bars",
        "context_window_bars",
        "allowed_gaps",
        "split_role",
        "split_start_utc",
        "split_end_utc",
    } <= names


def test_the_record_cannot_be_built_without_the_typed_fields() -> None:
    from src.backtest.experiment import ExperimentRecord

    with pytest.raises(TypeError):
        ExperimentRecord(  # type: ignore[call-arg]
            experiment_id="a" * 64,
            strategy_version="v4.0.0",
            parameter_set_id="baseline-v5",
            parameter_set_hash="b" * 64,
            data_snapshot_id="c" * 64,
            code_version="x",
            cost_model_hash="d" * 64,
            time_range_start_utc=RECORD_START,
            time_range_end_utc=RECORD_END,
            universe_hash="e" * 64,
            run_type="CANDIDATE",
            result_summary_json="{}",
            notes="",
        )


# ----- identity -------------------------------------------------------------


def test_experiment_id_changes_with_the_split_role_and_boundaries() -> None:
    base = _assemble()
    validation = _assemble(split_role="VALIDATION")
    holdout = _assemble(split_role="HOLDOUT")
    assert len({base.experiment_id, validation.experiment_id, holdout.experiment_id}) == 3

    wider_start = _assemble(split_start_utc=RECORD_START - timedelta(days=1))
    wider_end = _assemble(split_end_utc=RECORD_END + timedelta(days=1))
    assert len({base.experiment_id, wider_start.experiment_id, wider_end.experiment_id}) == 3
    assert base.experiment_id == _assemble().experiment_id


def test_experiment_id_binds_the_simulator_semantics_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _assemble()
    monkeypatch.setattr("src.backtest.experiment.SIMULATOR_SEMANTICS_VERSION", "2.0.1")
    bumped = _assemble(run_summary=strategy_run_summary(simulator_semantics_version="2.0.1"))
    assert bumped.simulator_semantics_version == "2.0.1"
    assert bumped.experiment_id != base.experiment_id
    # Everything else is identical, so the semantics version is the only moved input.
    moved = {key for key, value in bumped.to_dict().items() if value != base.to_dict()[key]}
    assert moved == {"experiment_id", "simulator_semantics_version"}


# ----- invalid construction -------------------------------------------------

_ONE_DAY = timedelta(days=1)


def _no_funding_convention_costs() -> tuple[tuple[str, str], ...]:
    return tuple(
        (k, v) for k, v in make_experiment_record().cost_values if k != "funding_convention"
    )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("simulator_semantics_version", "1.0.0"),
        ("intrabar_tie_break", "TP_FIRST"),
        ("split_role", "TRAIN"),
        ("split_start_utc", RECORD_START + _ONE_DAY),
        ("split_end_utc", RECORD_END - _ONE_DAY),
        ("fallback_count", -1),
        ("fallback_count", True),
        ("end_of_data_count", -1),
        ("no_trade_counts", (("RR_TOO_LOW", -1),)),
        ("no_trade_counts", (("RR_TOO_LOW", 1), ("RR_TOO_LOW", 2))),
        ("no_trade_counts", (("B", 1), ("A", 1))),
        ("code_version", "deadbeef"),
        ("code_dirty", "yes"),
        ("code_commit", "0123456789ABCDEF0123456789ABCDEF01234567"),
        ("code_commit", "abc"),
        ("parameter_values", ()),
        ("parameter_values", (("b", "1"), ("a", "2"))),
        ("cost_values", ()),
        ("strategy_window_bars", 0),
        ("context_window_bars", -5),
        ("timeframe", ""),
        ("context_timeframe", 4),
    ],
)
def test_an_invalid_value_cannot_construct_a_record(field: str, bad: object) -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match=field):
        make_experiment_record(**{field: bad})


def test_a_commit_that_is_not_40_hex_cannot_construct_a_record() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    for commit in ("abc", "g" * 40, "A" * 40, "a" * 41):
        with pytest.raises(IncompleteExperimentRecord, match="code_commit"):
            make_experiment_record(code_commit=commit, code_version=commit)


def test_code_version_must_match_the_commit_and_the_dirty_flag() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match="code_version"):
        make_experiment_record(code_dirty=True)  # code_version lacks the -dirty suffix
    with pytest.raises(IncompleteExperimentRecord, match="code_version"):
        make_experiment_record(code_version=f"{CODE_COMMIT}-dirty")  # flag says clean
    ok = make_experiment_record(code_dirty=True, code_version=f"{CODE_COMMIT}-dirty")
    assert ok.code_dirty is True


def test_cost_values_must_carry_the_funding_convention() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match="funding_convention"):
        make_experiment_record(cost_values=_no_funding_convention_costs())


def test_cost_values_must_hash_to_the_recorded_cost_model_hash() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    forged = tuple(
        (k, "0.0009" if k == "fee_rate_entry" else v)
        for k, v in make_experiment_record().cost_values
    )
    with pytest.raises(IncompleteExperimentRecord, match="cost_values"):
        make_experiment_record(cost_values=forged)
    # The shared factory can swap values and hash together; the record stays valid.
    other = make_experiment_record(cost_overrides={"fee_rate_entry": "0.0009"})
    assert dict(other.cost_values)["fee_rate_entry"] == "0.0009"
    assert other.cost_model_hash != make_experiment_record().cost_model_hash


def test_split_boundaries_must_contain_the_time_range() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match="split"):
        make_experiment_record(split_start_utc=RECORD_START + _ONE_DAY)
    with pytest.raises(IncompleteExperimentRecord, match="split"):
        make_experiment_record(split_end_utc=RECORD_END - _ONE_DAY)
    naive = datetime(2025, 12, 1)
    with pytest.raises(IncompleteExperimentRecord, match="split_start_utc"):
        make_experiment_record(split_start_utc=naive)


# ----- assemble refusals ----------------------------------------------------


def test_assemble_refuses_a_scripted_run() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match="plan_source"):
        _assemble(run_summary=strategy_run_summary(plan_source="SCRIPTED"))


def test_assemble_refuses_a_cost_model_without_the_funding_convention() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    # baseline-v3 is a legacy 7-key set: its registry slice binds, but it carries no
    # funding convention, so a record over it would hide the funding sign convention.
    with pytest.raises(IncompleteExperimentRecord, match="funding_convention"):
        _assemble(parameter_set_id="baseline-v3", cost_model=_build_cost_model(_gap_cost_dict()))


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("simulator_semantics_version", "1.0.0"),
        ("intrabar_tie_break", "TP_FIRST"),
    ],
)
def test_assemble_refuses_a_run_from_another_simulator_semantics(key: str, bad: str) -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match=key):
        _assemble(run_summary=strategy_run_summary(**{key: bad}))


def test_assemble_refuses_a_run_summary_missing_a_key() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    summary = strategy_run_summary()
    del summary["fallback_count"]
    with pytest.raises(IncompleteExperimentRecord, match="fallback_count"):
        _assemble(run_summary=summary)


def test_assemble_refuses_a_run_summary_for_another_time_range() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    other = strategy_run_summary(start=RECORD_START + _ONE_DAY)
    with pytest.raises(IncompleteExperimentRecord, match="data_window"):
        _assemble(run_summary=other)


def test_assemble_binds_the_run_to_the_identity_it_attests() -> None:
    # CR-02: the strategy version, parameter-set hash, cost-model hash and symbols of the
    # engine run must match the record's own identity inputs.
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match="strategy_version"):
        _assemble(strategy_version="v999.0.0-bogus")
    base = assemble_kwargs()["run_identity"]
    for key, bad in (
        ("strategy_version", "v999.0.0-bogus"),
        ("parameter_set_hash", "0" * 64),
        ("cost_model_hash", "0" * 64),
        ("symbols", ["ETHUSDT"]),
    ):
        with pytest.raises(IncompleteExperimentRecord, match=key):
            _assemble(run_identity={**base, key: bad})
    missing = {k: v for k, v in base.items() if k != "symbols"}
    with pytest.raises(IncompleteExperimentRecord, match="symbols"):
        _assemble(run_identity=missing)
    with pytest.raises(IncompleteExperimentRecord, match="universe"):
        _assemble(universe=["BTCUSDT", "ETHUSDT"], run_identity=base)


def test_assemble_refuses_a_run_over_another_or_no_dataset() -> None:
    from src.backtest.experiment import IncompleteExperimentRecord

    with pytest.raises(IncompleteExperimentRecord, match="dataset_id"):
        _assemble(run_summary=strategy_run_summary(dataset_id="9" * 64))
    with pytest.raises(IncompleteExperimentRecord, match="dataset_id is missing"):
        _assemble(run_summary=strategy_run_summary(dataset_id=None))
    ok = _assemble(data_snapshot_id="9" * 64, run_summary=strategy_run_summary(dataset_id="9" * 64))
    assert ok.data_snapshot_id == "9" * 64


def test_the_record_serializes_without_the_research_gate_keys() -> None:
    record = _assemble()
    document = record.to_dict()
    text = json.dumps(document)

    def keys(node: object) -> set[str]:
        if isinstance(node, dict):
            return set(node) | {k for child in node.values() for k in keys(child)}
        if isinstance(node, list):
            return {k for child in node for k in keys(child)}
        return set()

    assert not ({"parameters", "parameters_json"} & keys(document))
    assert document["simulator_semantics_version"] == "2.0.0"
    assert document["no_trade_counts"] == {"CONFLICT_WITH_OPEN_POSITION": 3, "RR_TOO_LOW": 5}
    assert json.loads(text) == document


# --------------------------------------------------------------------------- #
# Phase 14 (plan 14-15, Task 2): trade fan-out validation and the v2 run binding.
# --------------------------------------------------------------------------- #


def _engine_trade() -> dict[str, Any]:
    """The one filled trade dict the simple-trend baseline case produces (engine output)."""
    from src.backtest.simulator import run

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    (trade,) = run(case)["trades"]
    return dict(trade)


def test_trade_from_dict_round_trips_every_v2_field() -> None:
    from src.backtest.experiment import _trade_from_dict

    raw = _engine_trade()
    trade = _trade_from_dict(raw)
    assert trade.to_dict() == raw
    assert isinstance(trade.signal_close_utc, datetime)
    assert isinstance(trade.resolved_at_utc, datetime)
    assert trade.planned_quantity == Decimal("20.598")
    assert trade.regime == "BULLISH"
    assert type(trade.funding_event_count) is int
    assert type(trade.gap_through_stop) is bool


def test_trade_from_dict_rebuilds_the_tp1_leg_as_typed_values() -> None:
    from src.backtest.experiment import _trade_from_dict

    raw = _engine_trade()
    raw.update(
        exit_kind="TP2",
        exit_price="129.70",
        exit_time_utc="2026-09-11T10:30:00+00:00",
        tp1_quantity="10.299",
        tp1_price="125.60",
        tp1_time_utc="2026-09-11T10:20:00+00:00",
    )
    trade = _trade_from_dict(raw)
    assert trade.tp1_quantity == Decimal("10.299")
    assert trade.tp1_price == Decimal("125.60")
    assert trade.tp1_time_utc == datetime(2026, 9, 11, 10, 20, tzinfo=UTC)


def test_trade_from_dict_validates_every_trade() -> None:
    from src.backtest.experiment import _trade_from_dict
    from src.backtest.validator import TradeRecordInvariantError

    before_signal = _engine_trade()
    before_signal["entry_time_utc"] = "2026-09-11T09:59:00+00:00"  # before signal_close_utc
    with pytest.raises(TradeRecordInvariantError, match="entry_time"):
        _trade_from_dict(before_signal)

    no_signal_close = _engine_trade()
    del no_signal_close["signal_close_utc"]
    with pytest.raises(TradeRecordInvariantError, match="signal_close_utc"):
        _trade_from_dict(no_signal_close)

    over_planned = _engine_trade()
    over_planned["quantity"] = "99"
    with pytest.raises(TradeRecordInvariantError, match="planned_quantity"):
        _trade_from_dict(over_planned)

    exit_before_entry = _engine_trade()
    exit_before_entry["exit_time_utc"] = "2026-09-11T10:00:00+00:00"
    with pytest.raises(TradeRecordInvariantError, match="exit_time"):
        _trade_from_dict(exit_before_entry)


def test_trade_from_dict_refuses_a_v1_shaped_trade() -> None:
    from src.backtest.experiment import _trade_from_dict
    from src.backtest.validator import TradeRecordInvariantError

    v1 = _engine_trade()
    for key in (
        "signal_close_utc",
        "planned_quantity",
        "tp1_quantity",
        "tp1_price",
        "tp1_time_utc",
        "resolved_at_utc",
        "touch_no_fill_count",
        "gap_through_stop",
        "constraints_extrapolated",
        "regime",
        "funding_event_count",
    ):
        del v1[key]
    v1["exit_kind"] = "TP1"
    with pytest.raises(TradeRecordInvariantError, match="exit_kind"):
        _trade_from_dict(v1)

    v1_unfilled = _engine_trade()
    v1_unfilled.update(entry_kind="TOUCH_NO_FILL", exit_kind=None)
    with pytest.raises(TradeRecordInvariantError, match="entry_kind"):
        _trade_from_dict(v1_unfilled)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("touch_no_fill_count", "1"),
        ("touch_no_fill_count", True),
        ("funding_event_count", 1.5),
        ("gap_through_stop", 0),
        ("fallback_applied", "false"),
        ("constraints_extrapolated", None),
        ("regime", 7),
        ("coverage_note", ["x"]),
    ],
)
def test_trade_from_dict_refuses_mistyped_counters_flags_and_labels(
    field: str, bad: object
) -> None:
    from src.backtest.experiment import ExperimentReproducibilityBroken, _trade_from_dict

    raw = _engine_trade()
    raw[field] = bad
    with pytest.raises(ExperimentReproducibilityBroken, match=field):
        _trade_from_dict(raw)


def test_reproduce_binds_the_data_window_to_the_record_time_range() -> None:
    from src.backtest.experiment import ExperimentReproducibilityBroken, reproduce

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)
    shifted = dict(case, data_window=dict(case["data_window"], end_utc="2026-09-11T11:30:00+00:00"))
    with pytest.raises(ExperimentReproducibilityBroken, match="data_window"):
        reproduce(record, simulator_inputs=shifted)
    missing = {k: v for k, v in case.items() if k != "data_window"}
    with pytest.raises(ExperimentReproducibilityBroken, match="data_window"):
        reproduce(record, simulator_inputs=missing)


def test_verify_experiment_fails_closed_when_the_data_window_changes() -> None:
    from src.backtest.experiment import ExperimentReproducibilityBroken, verify_experiment

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)
    assert verify_experiment(record, simulator_inputs=case) is None
    shorter = dict(case, data_window=dict(case["data_window"], end_utc="2026-09-11T10:30:00+00:00"))
    with pytest.raises(ExperimentReproducibilityBroken, match="data_window"):
        verify_experiment(record, simulator_inputs=shorter)


def test_verify_experiment_fails_closed_when_the_simulator_semantics_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backtest.experiment import ExperimentReproducibilityBroken, verify_experiment

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)
    # The engine now reports a different semantics version than the record was made under.
    monkeypatch.setattr("src.backtest.engine.SIMULATOR_SEMANTICS_VERSION", "2.0.1")
    with pytest.raises(ExperimentReproducibilityBroken, match="simulator_semantics_version"):
        verify_experiment(record, simulator_inputs=case)


def test_reproduce_refuses_a_run_whose_typed_counts_differ_from_the_record() -> None:
    from src.backtest.experiment import ExperimentReproducibilityBroken, reproduce

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = dataclasses.replace(
        _simple_trend_record(case), no_trade_counts=(("NO_TRADE_REGIME", 1),)
    )
    with pytest.raises(ExperimentReproducibilityBroken, match="no_trade_counts"):
        reproduce(record, simulator_inputs=case)


def test_reproduce_refuses_to_replay_a_scripted_run() -> None:
    from src.backtest.experiment import ExperimentReproducibilityBroken, reproduce

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)
    scripted = dict(case, scripted_plans=[])
    with pytest.raises(ExperimentReproducibilityBroken, match="plan_source"):
        reproduce(record, simulator_inputs=scripted)


def test_reproduce_returns_validated_typed_trades_for_a_bound_record() -> None:
    from src.backtest.experiment import reproduce
    from src.backtest.simulator import run

    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    record = _simple_trend_record(case)
    trades = reproduce(record, simulator_inputs=case)
    assert [t.to_dict() for t in trades] == run(case)["trades"]
    assert record.no_trade_counts == (("NO_TRADE_REGIME", 9),)
    assert record.end_of_data_count == 0
