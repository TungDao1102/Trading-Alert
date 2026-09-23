"""Prefix-invariance determinism suite (Phase 4, plan 04-02 — real family behavior).

Per D-08: the same candle prefix embedded in two different longer
inputs must yield byte-identical prefix decisions (NO_TRADE or SETUP
with identical signal_id). The Phase-3 placeholder mapping has been
replaced with real `compute_features` + `evaluate` calls; the
prefix-invariance invariant must hold over real family behavior.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from src.core.strategy import evaluate
from src.core.types import (
    AccountState,
    Candle,
    MarketSnapshot,
    SetupResult,
)
from src.domain.registry import ParameterSet, load_parameter_set

TIMEFRAME_SECONDS = {"1m": 60, "1h": 3600, "4h": 14400}

ACCOUNT_STATE = AccountState(
    equity=Decimal("10000.00"),
    risk_rate=Decimal("0.005"),
)


def _row_to_candle(row: dict) -> Candle:
    """Build a Candle from a phase3_candles fixture row."""
    step = TIMEFRAME_SECONDS[row["timeframe"]]
    open_time = datetime.fromisoformat(row["open_time_utc"])
    close_time = open_time + timedelta(seconds=step) - timedelta(seconds=1)
    return Candle(
        symbol=row["symbol"],
        interval=row["timeframe"],
        open_time_utc=open_time,
        close_time_utc=close_time,
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        volume=Decimal(row["volume"]),
    )


def _split_phase4_by_timeframe(
    phase4_candles: list[dict],
) -> tuple[list[Candle], list[Candle]]:
    """Split the phase4 fixture into 1H setup candles and 4H context candles."""
    setup: list[Candle] = []
    context: list[Candle] = []
    for row in phase4_candles:
        if row["timeframe"] == "1h":
            setup.append(_row_to_candle(row))
        elif row["timeframe"] == "4h":
            context.append(_row_to_candle(row))
    return setup, context


def _snapshot_for(
    candles_1h: list[Candle],
    candles_4h: list[Candle],
) -> MarketSnapshot:
    """Build the MarketSnapshot the strategy.evaluate expects."""
    return MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h,
        context_candles=candles_4h,
        source_timeframe="1h",
    )


def _decisions(
    candles_1h: list[Candle],
    candles_4h: list[Candle],
    parameter_set: ParameterSet,
) -> list[tuple[datetime, SetupResult]]:
    """Run evaluate on each prefix of candles_1h; return (source_close, SetupResult)."""
    decisions: list[tuple[datetime, SetupResult]] = []
    for i in range(len(candles_1h)):
        prefix_1h = candles_1h[: i + 1]
        snapshot = _snapshot_for(prefix_1h, candles_4h)
        result = evaluate(
            snapshot=snapshot,
            account_state=ACCOUNT_STATE,
            strategy_version=parameter_set.strategy_version,
            parameter_set=parameter_set,
        )
        decisions.append((candles_1h[i].close_time_utc, result))
    return decisions


def _decision_key(result: SetupResult) -> tuple[str, str | None]:
    """Return a stable decision representation: (kind, signal_id_or_reason)."""
    if result.is_no_trade:
        return ("NO_TRADE", result.reason_code)
    assert result.signal is not None
    return ("SETUP", result.signal.signal_id)


def _synthetic_bar(symbol: str, opened: datetime, price: str) -> dict:
    """Build a bar continuing the fixture series shape."""
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "open_time_utc": opened.isoformat(),
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": "1.0",
    }


# --------------------------------------------------------------------------- #
# Test 1 — shared prefix embedded in two longer inputs.
# --------------------------------------------------------------------------- #


def test_shared_prefix_embedded_in_two_inputs(
    phase4_candles,
) -> None:
    """Beh. 1: one shared prefix in two longer inputs, identical decisions.

    The prefix sits at the same offset in both inputs (the entire
    input up to some point); its decisions must compare byte-identical
    regardless of what comes after the prefix.
    """
    setup_1h, context_4h = _split_phase4_by_timeframe(phase4_candles)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
    # Use the last 200 bars as the prefix so EMA200(1H) has warmed up.
    prefix = setup_1h[-200:]
    tail_open = prefix[-1].open_time_utc
    tail_a = [
        _row_to_candle(
            _synthetic_bar("BTCUSDT", tail_open + timedelta(hours=1), "63000.00")
        )
    ]
    tail_b = [
        _row_to_candle(
            _synthetic_bar("BTCUSDT", tail_open + timedelta(hours=1), "55000.00")
        )
    ]
    input_a = prefix + tail_a
    input_b = prefix + tail_b
    out_a = _decisions(input_a, context_4h, parameter_set)
    out_b = _decisions(input_b, context_4h, parameter_set)
    # Prefix occupies positions 0..199 in both A and B.
    for i in range(len(prefix)):
        assert _decision_key(out_a[i][1]) == _decision_key(out_b[i][1]), (
            f"prefix decision at bar {i} differs between inputs: "
            f"a={out_a[i][1]}, b={out_b[i][1]}"
        )


# --------------------------------------------------------------------------- #
# Test 2 — full-run digest stability over identical input.
# --------------------------------------------------------------------------- #


def test_full_run_digest_stable_over_identical_input(
    phase4_candles,
) -> None:
    """Beh. 2: two runs over the same input are decision-identical.

    Pins determinism of the mapping itself (no wall-clock, no ordering
    nondeterminism) so the prefix comparisons above are meaningful.
    """
    setup_1h, context_4h = _split_phase4_by_timeframe(phase4_candles)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
    first = _decisions(setup_1h, context_4h, parameter_set)
    second = _decisions(setup_1h, context_4h, parameter_set)
    assert [_decision_key(r) for _, r in first] == [
        _decision_key(r) for _, r in second
    ]


# --------------------------------------------------------------------------- #
# Test 3 — stateful variant is detected by digest comparison.
# --------------------------------------------------------------------------- #


def test_stateful_variant_is_detected_by_digest_comparison(
    phase4_candles,
) -> None:
    """Beh. 3: hidden run-to-run state changes decisions.

    A deliberately stateful helper (module-global call counter folded
    into the regime gate) yields DIFFERENT decisions across two runs
    over identical input — proving the prefix-invariance comparison
    is sensitive to the nondeterminism bug class.
    """
    setup_1h, context_4h = _split_phase4_by_timeframe(phase4_candles)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
    calls = {"n": 0}

    def _stateful_decisions(
        candles_1h: list[Candle],
        candles_4h: list[Candle],
    ) -> list[tuple[datetime, SetupResult]]:
        """Deliberately stateful: bind a module-global counter into the setup gate.

        A real-world bug class is a hidden module-global that leaks
        across calls. The stateful helper perturbs the last 1H candle's
        close by an amount depending on the call counter — a fingerprint
        of run-to-run state that flips the setup gate.
        """
        decisions: list[tuple[datetime, SetupResult]] = []
        for i in range(len(candles_1h)):
            prefix_1h = candles_1h[: i + 1]
            calls["n"] += 1
            # Stateful: shift the last 1H candle's close by an amount
            # depending on the call counter — a fingerprint of run-to-run
            # state that flips the setup gate. Expand high/low so the
            # Candle OHLC validator accepts the perturbed close.
            leaky_1h = list(prefix_1h)
            if leaky_1h:
                last = leaky_1h[-1]
                shift = Decimal(str(calls["n"] * 1000))
                leaky_1h[-1] = Candle(
                    symbol=last.symbol,
                    interval=last.interval,
                    open_time_utc=last.open_time_utc,
                    close_time_utc=last.close_time_utc,
                    open=last.open + shift,
                    high=last.high + shift,
                    low=last.low + shift,
                    close=last.close + shift,
                    volume=last.volume,
                )
            snapshot = _snapshot_for(leaky_1h, candles_4h)
            result = evaluate(
                snapshot=snapshot,
                account_state=ACCOUNT_STATE,
                strategy_version=parameter_set.strategy_version,
                parameter_set=parameter_set,
            )
            decisions.append((candles_1h[i].close_time_utc, result))
        return decisions

    first = _stateful_decisions(setup_1h, context_4h)
    second = _stateful_decisions(setup_1h, context_4h)
    # At least one decision must differ — the stateful helper binds
    # run-to-run state into the regime gate.
    diffs = [
        i
        for i in range(len(first))
        if _decision_key(first[i][1]) != _decision_key(second[i][1])
    ]
    assert len(diffs) > 0, (
        "stateful variant should change at least one decision; "
        "the prefix-invariance comparison would be insensitive to the bug class"
    )
