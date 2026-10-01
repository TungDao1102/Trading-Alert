"""No-lookahead determinism suite (Phase 4, plan 04-02 — real family behavior).

Per D-08 and TESTING_STRATEGY §3: appending arbitrary bars after time T
must never change the decisions (NO_TRADE or SETUP signal_id) at or
before T. The Phase-3 placeholder mapping has been replaced with real
`compute_features` + `evaluate` calls against the trend-pullback family;
the no-lookahead invariant must hold over real family behavior.
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


def _first_gap_index_rows(rows: list[dict], interval: str) -> int:
    """Return the index of the first gap in time-ordered rows.

    Plan 04-04 appended family B/C windows (with intentional gap blocks
    per D-04) to the shared candles.csv. Determinism suites pin the
    tracer window, so each stream is truncated to its first contiguous
    block (1H: 250 bars, 4H: 500 bars — the pre-04-04 layout).
    """
    step = TIMEFRAME_SECONDS[interval]
    ordered = sorted(rows, key=lambda r: r["open_time_utc"])
    for i in range(1, len(ordered)):
        prev = datetime.fromisoformat(ordered[i - 1]["open_time_utc"])
        curr = datetime.fromisoformat(ordered[i]["open_time_utc"])
        if (curr - prev).total_seconds() > step:
            return i
    return len(ordered)


def _split_phase4_by_timeframe(
    phase4_candles: list[dict],
) -> tuple[list[Candle], list[Candle]]:
    """Split the phase4 fixture into 1H setup candles and 4H context candles.

    Sorts each timeframe's candles by open_time_utc so the concatenated
    setup+context sequences are independently ordered (D-02). Truncates
    each stream to its first contiguous block (D-04): later family
    windows carry intentional gaps that must not poison the tracer
    decision window.
    """
    setup: list[Candle] = []
    context: list[Candle] = []
    rows_1h = [r for r in phase4_candles if r["timeframe"] == "1h"]
    rows_4h = [r for r in phase4_candles if r["timeframe"] == "4h"]
    rows_1h = sorted(rows_1h, key=lambda r: r["open_time_utc"])
    rows_4h = sorted(rows_4h, key=lambda r: r["open_time_utc"])
    rows_1h = rows_1h[: _first_gap_index_rows(rows_1h, "1h")]
    rows_4h = rows_4h[: _first_gap_index_rows(rows_4h, "4h")]
    for row in rows_1h:
        setup.append(_row_to_candle(row))
    for row in rows_4h:
        context.append(_row_to_candle(row))
    setup.sort(key=lambda c: c.open_time_utc)
    context.sort(key=lambda c: c.open_time_utc)
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
    """Run evaluate on each prefix of candles_1h; return (source_close, SetupResult).

    Each SetupResult is either a NO_TRADE (with reason_code) or a SETUP
    (with a Signal whose detected_at_utc equals the source close per
    D-07). The list length equals len(candles_1h): one decision per bar.
    """
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
    """Build a post-T bar continuing the fixture series shape."""
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
# Test 1 — appended bars never change prefix decisions.
# --------------------------------------------------------------------------- #


def test_appended_bars_never_change_prefix_decisions(
    phase4_candles,
) -> None:
    """Beh. 1: decisions at or before T are byte-identical after appends.

    Evaluating the prefix alone vs the prefix plus extra trailing bars
    must yield identical decisions (NO_TRADE or SETUP with identical
    signal_id) for every bar in the prefix.
    """
    setup_1h, context_4h = _split_phase4_by_timeframe(phase4_candles)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
    # Use the last 200 bars as the prefix so EMA200(1H) has warmed up.
    prefix = setup_1h[-200:]
    last_open = prefix[-1].open_time_utc
    extra_candles = [
        _row_to_candle(_synthetic_bar("BTCUSDT", last_open + timedelta(hours=1), "62000.00")),
        _row_to_candle(_synthetic_bar("BTCUSDT", last_open + timedelta(hours=2), "62500.00")),
    ]
    before = _decisions(prefix, context_4h, parameter_set)
    after = _decisions(prefix + extra_candles, context_4h, parameter_set)

    # Prefix decisions match position-by-position.
    for i in range(len(before)):
        assert _decision_key(before[i][1]) == _decision_key(after[i][1]), (
            f"prefix decision at bar {i} changed after append: "
            f"before={before[i][1]}, after={after[i][1]}"
        )


# --------------------------------------------------------------------------- #
# Test 2 — same prefix under different suffixes stays identical.
# --------------------------------------------------------------------------- #


def test_same_prefix_different_suffixes_identical(
    phase4_candles,
) -> None:
    """Beh. 2: the same prefix yields identical decisions under any suffix."""
    setup_1h, context_4h = _split_phase4_by_timeframe(phase4_candles)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
    prefix = setup_1h[-200:]
    last_open = prefix[-1].open_time_utc
    suffix_a = [
        _row_to_candle(_synthetic_bar("BTCUSDT", last_open + timedelta(hours=1), "63000.00"))
    ]
    suffix_b = [
        _row_to_candle(_synthetic_bar("BTCUSDT", last_open + timedelta(hours=1), "55000.00"))
    ]
    out_a = _decisions(prefix + suffix_a, context_4h, parameter_set)
    out_b = _decisions(prefix + suffix_b, context_4h, parameter_set)
    # Prefix decisions match.
    for i in range(len(prefix)):
        assert _decision_key(out_a[i][1]) == _decision_key(out_b[i][1]), (
            f"prefix decision at bar {i} differs between suffixes: a={out_a[i][1]}, b={out_b[i][1]}"
        )


# --------------------------------------------------------------------------- #
# Test 3 — appending 10 future bars changes zero historical decisions.
# --------------------------------------------------------------------------- #


def test_appending_ten_future_bars_changes_zero_historical_decisions(
    phase4_candles,
) -> None:
    """Beh. 3: appending 10 future bars changes zero historical decisions.

    Full equality of the decision list (not just a sample) across the
    prefix boundary — pins the invariant under a longer tail.
    """
    setup_1h, context_4h = _split_phase4_by_timeframe(phase4_candles)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
    prefix = setup_1h[-200:]
    last_open = prefix[-1].open_time_utc
    extra_candles = [
        _row_to_candle(
            _synthetic_bar(
                "BTCUSDT",
                last_open + timedelta(hours=i + 1),
                str(62000 + (i + 1) * 100),
            )
        )
        for i in range(10)
    ]
    before = _decisions(prefix, context_4h, parameter_set)
    after = _decisions(prefix + extra_candles, context_4h, parameter_set)
    # All prefix decisions match.
    for i in range(len(before)):
        assert _decision_key(before[i][1]) == _decision_key(after[i][1])


# --------------------------------------------------------------------------- #
# Test 4 — leaky variant: a future-bar-binding fingerprint is detected.
# --------------------------------------------------------------------------- #


def _with_support_touch_last_bar(
    candles: list[Candle], parameter_set: ParameterSet
) -> list[Candle]:
    """Patch the last bar's low onto the trailing swing low (CR-06 setup)."""
    from src.core.features import compute_features

    frame = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=candles,
        parameter_set=parameter_set,
    )
    assert frame.features_valid
    assert frame.swing_low.value is not None
    swing_low = frame.swing_low.value
    last = candles[-1]
    assert last.open >= swing_low and last.close >= swing_low
    patched = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open,
        high=max(last.high, last.open, last.close),
        low=swing_low,
        close=last.close,
        volume=last.volume,
    )
    return [*candles[:-1], patched]


def test_leaky_variant_is_detected_by_prefix_comparison(
    phase4_candles,
) -> None:
    """Beh. 4: a real-world lookahead leak (binding input length) is detected.

    A deliberately leaky helper (a fingerprint that binds the total
    number of candles) yields DIFFERENT prefix decisions after appends —
    proving the no-lookahead comparison is sensitive to the bug class.
    """
    setup_1h, context_4h = _split_phase4_by_timeframe(phase4_candles)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v1")
    prefix = setup_1h[-200:]
    # Review fix CR-06: the fixture's last prefix bar touches neither the
    # support nor the resistance zone, so a regime flip alone no longer
    # moves the decision (both sides stay NO_TRADE and the harness would
    # go insensitive). Patch the last prefix bar to touch SUPPORT so the
    # BULLISH side emits LONG while the perturbed (BEARISH) side stays
    # NO_TRADE — the leak still flips a real decision.
    prefix = _with_support_touch_last_bar(prefix, parameter_set)
    last_open = prefix[-1].open_time_utc
    extra_candles = [
        _row_to_candle(_synthetic_bar("BTCUSDT", last_open + timedelta(hours=1), "62000.00"))
    ]

    def _leaky_decisions(
        candles_1h: list[Candle],
        candles_4h: list[Candle],
    ) -> list[tuple[datetime, SetupResult]]:
        """Deliberately leaky: bind the 1H prefix length parity into the regime gate.

        A real-world bug class is a feature that reads the input length
        (e.g. a moving average that uses range-bound slicing). The leaky
        helper perturbs the last 4H candle's close by a large fixed
        amount when the 1H length is EVEN — a fingerprint of the future
        that flips the regime verdict. Adding one candle (changing
        parity) toggles the perturbation.
        """
        decisions: list[tuple[datetime, SetupResult]] = []
        for i in range(len(candles_1h)):
            prefix_1h = candles_1h[: i + 1]
            # Leaky: if the 1H length is even, shift the last 4H close
            # by a large amount — a fingerprint of the future that flips
            # the regime verdict.
            leaky_4h = list(candles_4h)
            if leaky_4h and len(candles_1h) % 2 == 0:
                last_4h = leaky_4h[-1]
                shift = Decimal("50000.00")
                leaky_4h[-1] = Candle(
                    symbol=last_4h.symbol,
                    interval=last_4h.interval,
                    open_time_utc=last_4h.open_time_utc,
                    close_time_utc=last_4h.close_time_utc,
                    open=last_4h.open - shift,
                    high=last_4h.high - shift,
                    low=last_4h.low - shift,
                    close=last_4h.close - shift,
                    volume=last_4h.volume,
                )
            snapshot = _snapshot_for(prefix_1h, leaky_4h)
            result = evaluate(
                snapshot=snapshot,
                account_state=ACCOUNT_STATE,
                strategy_version=parameter_set.strategy_version,
                parameter_set=parameter_set,
            )
            decisions.append((candles_1h[i].close_time_utc, result))
        return decisions

    before = _leaky_decisions(prefix, context_4h)
    after = _leaky_decisions(prefix + extra_candles, context_4h)
    # At least one prefix decision must differ — the leaky helper binds
    # future-bar length into the regime gate.
    diffs = [
        i for i in range(len(before)) if _decision_key(before[i][1]) != _decision_key(after[i][1])
    ]
    assert len(diffs) > 0, (
        "leaky variant should change at least one prefix decision; "
        "the no-lookahead comparison would be insensitive to the bug class"
    )
