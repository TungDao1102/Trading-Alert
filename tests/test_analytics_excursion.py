"""Excursion (MFE/MAE) tracer and expansion tests (Phase 10, plan 10-01).

Task 1 tracer: one LONG backtest TradeRecord flows
normalize_backtest -> compute_trade_excursion -> build_excursion_section and
yields MFE/MAE in price and R plus time-to-extreme, pinned by a golden fixture.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from src.analytics.excursion import (
    ExcursionSection,
    TradeExcursion,
    build_excursion_section,
    compute_trade_excursion,
)
from src.analytics.inputs import normalize_backtest
from src.analytics.types import AnalyticsInputError, EvidenceKind, TradeOutcome
from src.core.types import Candle

from tests.phase10_helpers import D, load_expected, load_input, make_candles, make_trade_record

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_tracer_long_trade_end_to_end() -> None:
    data = load_input("complete_trade")
    expected = load_expected("complete_trade")
    record = make_trade_record(**data["trade"])
    candles = make_candles(data["candles"])

    normalized = normalize_backtest([record])
    assert normalized.rejects == ()
    assert len(normalized.outcomes) == 1
    outcome = normalized.outcomes[0]
    assert outcome.evidence is EvidenceKind.BACKTEST
    assert outcome.strategy_version == "v2.0.0"
    assert outcome.parameter_set_hash == "a" * 64

    excursion = compute_trade_excursion(outcome, candles)
    assert excursion.incomplete_reason is None
    assert excursion.mfe_price == D(expected["mfe_price"])
    assert excursion.mae_price == D(expected["mae_price"])
    assert excursion.mfe_r == D(expected["mfe_r"])
    assert excursion.mae_r == D(expected["mae_r"])
    assert excursion.time_to_mfe_s == D(expected["time_to_mfe_s"])
    assert excursion.time_to_mae_s == D(expected["time_to_mae_s"])
    assert excursion.holding_s == D(expected["holding_s"])
    assert excursion.realized_r == D(expected["realized_r"])
    assert excursion.r_excluded_zero_risk is False

    section = build_excursion_section(
        normalized.outcomes,
        {"BTCUSDT": candles},
        evidence=EvidenceKind.BACKTEST,
        resamples=100,
    )
    assert section.evidence is EvidenceKind.BACKTEST
    assert section.n_outcomes == expected["section"]["n_outcomes"] == 1
    assert section.n_measured == expected["section"]["n_measured"] == 1
    assert section.n_zero_risk_excluded == expected["section"]["n_zero_risk_excluded"] == 0
    for stat in section.measure_stats:
        assert stat.mean.n == 1
        assert stat.mean.n_valued == 1
        assert stat.mean.interval_absent is True
        assert stat.mean.value is not None
    assert isinstance(section.digest(), str)
    assert HEX64.match(section.digest())
    assert section.digest() == expected["section_digest"]


def test_tracer_names_importable() -> None:
    """Every name the objective lists resolves (artifact contract)."""
    import src.analytics.excursion as excursion
    import src.analytics.inputs as inputs
    import src.analytics.stats as stats
    import src.analytics.types as types

    for name in (
        "EvidenceKind",
        "IncompleteReason",
        "TradeOutcome",
        "OutcomeContext",
        "NoTradeRecord",
        "BacktestNormalization",
        "Estimate",
        "DistStat",
        "AnalyticsInputError",
        "ANALYTICS_SCHEMA_VERSION",
        "LOW_N_THRESHOLD",
        "DEFAULT_RESAMPLES",
        "MIN_RESAMPLES",
        "BOOTSTRAP_BLOCK_P",
        "DEFAULT_BASE_SEED",
    ):
        assert hasattr(types, name), name
    for name in (
        "r_value",
        "is_zero_risk",
        "seed_for",
        "seconds_between",
        "percent",
        "estimate_mean",
        "dist_stat",
        "percentile",
        "is_low_n",
        "ordered_r_values",
    ):
        assert hasattr(stats, name), name
    assert hasattr(inputs, "normalize_backtest")
    for name in (
        "EXCURSION_WINDOW_CONVENTION",
        "EXCURSION_MEASURES",
        "TradeExcursion",
        "ExcursionSection",
        "compute_trade_excursion",
        "build_excursion_section",
    ):
        assert hasattr(excursion, name), name
    assert types.ANALYTICS_SCHEMA_VERSION == "analytics-schema/1"
    assert types.LOW_N_THRESHOLD == 30
    assert types.DEFAULT_RESAMPLES == 1000
    assert types.MIN_RESAMPLES == 100
    assert types.BOOTSTRAP_BLOCK_P == Decimal("0.1")
    assert types.DEFAULT_BASE_SEED == 20260929
    assert {m.name for m in types.EvidenceKind} == {"BACKTEST", "PAPER", "LIVE"}
    assert len(list(types.IncompleteReason)) == 17


# --------------------------------------------------------------------------- #
# Task 2 - expansion: SHORT, zero-risk, bootstrap aggregates, diagnostics.
# --------------------------------------------------------------------------- #


def _measured_excursion(case: str) -> tuple[TradeOutcome, TradeExcursion]:
    data = load_input(case)
    outcome = normalize_backtest([make_trade_record(**data["trade"])]).outcomes[0]
    return outcome, compute_trade_excursion(outcome, make_candles(data["candles"]))


def test_short_trade_mirrors_long_excursions() -> None:
    _, excursion = _measured_excursion("short_trade")
    expected = load_expected("short_trade")
    assert excursion.incomplete_reason is None
    assert excursion.direction == "SHORT"
    assert excursion.mfe_price == D(expected["mfe_price"])
    assert excursion.mae_price == D(expected["mae_price"])
    assert excursion.mfe_r == D(expected["mfe_r"])
    assert excursion.mae_r == D(expected["mae_r"])
    assert excursion.time_to_mfe_s == D(expected["time_to_mfe_s"])
    assert excursion.time_to_mae_s == D(expected["time_to_mae_s"])
    assert excursion.holding_s == D(expected["holding_s"])
    assert excursion.realized_r == D(expected["realized_r"])


def test_zero_risk_trade_excluded_from_r_but_counted() -> None:
    outcome, excursion = _measured_excursion("zero_risk_excluded")
    expected = load_expected("zero_risk_excluded")
    assert isinstance(excursion.mfe_price, Decimal)
    assert excursion.mfe_price == D(expected["mfe_price"])
    assert excursion.mae_price == D(expected["mae_price"])
    assert excursion.mfe_r is None
    assert excursion.mae_r is None
    assert excursion.realized_r is None
    assert excursion.r_excluded_zero_risk is True

    data = load_input("zero_risk_excluded")
    section = build_excursion_section(
        [outcome],
        {"BTCUSDT": make_candles(data["candles"])},
        evidence=EvidenceKind.BACKTEST,
        resamples=100,
    )
    assert section.n_zero_risk_excluded == expected["section"]["n_zero_risk_excluded"] == 1
    assert section.n_outcomes == expected["section"]["n_outcomes"] == 1
    assert section.n_measured == 1
    assert section.stat("mfe_r").mean.n_valued == 0
    assert section.stat("mfe_r").mean.value is None
    assert section.stat("mfe_price").mean.n_valued == 1


def _four_trade_outcomes() -> tuple[tuple[TradeOutcome, ...], dict[str, list[Candle]]]:
    """LONG/SHORT x TP1/SL over the same candles; all share one exit instant."""
    long_data = load_input("complete_trade")
    short_data = load_input("short_trade")
    records = []
    for tag, base, exit_kind, pnl in (
        ("A", long_data["trade"], "TP1", "8.00"),
        ("B", long_data["trade"], "SL", "-10.00"),
        ("C", short_data["trade"], "TP1", "8.00"),
        ("D", short_data["trade"], "SL", "-10.00"),
    ):
        records.append(
            make_trade_record(
                **{**base, "trade_id": f"T-{tag}", "exit_kind": exit_kind, "realized_pnl": pnl}
            )
        )
    return normalize_backtest(records).outcomes, {"BTCUSDT": make_candles(long_data["candles"])}


def test_bootstrap_aggregates_carry_interval_when_two_or_more_valued() -> None:
    outcomes, candles = _four_trade_outcomes()
    section = build_excursion_section(
        outcomes, candles, evidence=EvidenceKind.BACKTEST, resamples=100
    )
    assert section.n_measured == 4
    for stat in section.measure_stats:
        assert stat.mean.n == 4
        assert stat.mean.n_valued >= 2
        assert stat.mean.interval_absent is False
        assert stat.mean.lo is not None
        assert stat.mean.hi is not None
        assert stat.mean.lo <= stat.mean.hi
        assert stat.mean.n_resamples == 100


def test_same_seed_same_digest_different_seed_different_digest() -> None:
    outcomes, candles = _four_trade_outcomes()

    def build(seed: int) -> ExcursionSection:
        return build_excursion_section(
            outcomes, candles, evidence=EvidenceKind.BACKTEST, base_seed=seed, resamples=100
        )

    first, second, other = build(7), build(7), build(8)
    assert first.digest() == second.digest()
    assert first.stat("mfe_r").mean.digest() == second.stat("mfe_r").mean.digest()
    assert first.digest() != other.digest()
    assert first.stat("mfe_r").mean.digest() != other.stat("mfe_r").mean.digest()


def test_diagnostics_are_descriptive_distributions() -> None:
    outcomes, candles = _four_trade_outcomes()
    section = build_excursion_section(
        outcomes, candles, evidence=EvidenceKind.BACKTEST, resamples=100
    )
    # SL exits: B (LONG: mfe_r 1) and D (SHORT: mfe_r 0.16).
    sl = section.mfe_r_of_sl_exits
    assert sl.n == 2
    assert sl.minimum == D("0.16")
    assert sl.maximum == D("1")
    assert sl.median == D("0.58")
    # TP exits: A (LONG: mae_r 0.16) and C (SHORT: mae_r 1).
    tp = section.mae_r_of_tp_exits
    assert tp.n == 2
    assert tp.minimum == D("0.16")
    assert tp.maximum == D("1")
    # give-back = mfe_r - realized_r: A 0.2, B 2, C -0.64, D 1.16.
    gb = section.give_back
    assert gb.n == 4
    assert gb.minimum == D("-0.64")
    assert gb.maximum == D("2")
    # Holding distribution reuses the holding measure (all 160 s).
    assert section.stat("holding").median == D("160")


def test_mixed_evidence_kind_raises() -> None:
    outcomes, candles = _four_trade_outcomes()
    with pytest.raises(AnalyticsInputError):
        build_excursion_section(outcomes, candles, evidence=EvidenceKind.PAPER, resamples=100)


def test_empty_outcomes_yield_valid_no_data_section() -> None:
    section = build_excursion_section([], {}, evidence=EvidenceKind.PAPER, resamples=100)
    assert section.evidence is EvidenceKind.PAPER
    assert section.n_outcomes == 0
    assert section.n_measured == 0
    assert section.incomplete == ()
    for stat in (
        *section.measure_stats,
        section.mfe_r_of_sl_exits,
        section.mae_r_of_tp_exits,
        section.give_back,
    ):
        assert stat.n == 0
        assert stat.mean.value is None
        assert stat.mean.interval_absent is True
        assert stat.median is None
    assert len(section.digest()) == 64
