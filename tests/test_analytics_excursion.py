"""Excursion (MFE/MAE) tracer and expansion tests (Phase 10, plan 10-01).

Task 1 tracer: one LONG backtest TradeRecord flows
normalize_backtest -> compute_trade_excursion -> build_excursion_section and
yields MFE/MAE in price and R plus time-to-extreme, pinned by a golden fixture.
"""

from __future__ import annotations

import re
from decimal import Decimal

from tests.phase10_helpers import D, load_expected, load_input, make_candles, make_trade_record

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_tracer_long_trade_end_to_end() -> None:
    from src.analytics.excursion import build_excursion_section, compute_trade_excursion
    from src.analytics.inputs import normalize_backtest
    from src.analytics.types import EvidenceKind

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
