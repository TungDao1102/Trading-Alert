"""Helper script to generate Phase 6 backtest fixture data deterministically.

Per D-01/D-02: each fixture drives the simulator end-to-end through
strategy.evaluate → planner.plan → evaluate_risk. The candles are
designed so:
  - trend-pullback (Family A) baseline-v5 parameters produce a known setup
  - 4H context confirms the regime
  - The last 1H bar is the trigger bar (touches the zone)
  - 1m intrabar data resolves the exit

Phase 12 (F-002, F-608): the 1H bars carry a realistic half-range
(BAR_HALF_RANGE = 0.80) so the ATR-derived stop sits about 1.1 percent from
entry instead of 0.06 to 0.26 percent. That clears the minimum-stop (0.3
percent) and cost-to-risk (0.15) guards with margin. The plan geometry is
DERIVED by the planner from the bars; the numbers quoted in the docstrings
below are illustrations from the planning-time prototype, and
tests/test_phase6_fixture_geometry.py recomputes and checks them with
independent arithmetic.

This script is committed for reproducibility — re-running it regenerates
byte-identical fixtures.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "phase6"
SYMBOL = "BTCUSDT"

# 1H bar half-range (high = close + half, low = close - half) for bars
# 0..248. Larger half-range -> larger ATR -> wider stop -> lower
# cost-to-risk. Never tune a guard or registry value instead (Phase 12).
BAR_HALF_RANGE = Decimal("0.80")

# Base epoch for fixture candles (deterministic, stable across runs).
BASE_OPEN = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


def _fmt(dt: datetime) -> str:
    """Format datetime as ISO 8601 with +00:00 suffix."""
    return dt.astimezone(UTC).isoformat()


def _make_1h_candles_long_setup() -> list[dict]:
    """250 1H bars trending up; the last bar dips to touch the support zone.

    Bars 0..248: smooth uptrend from 100.00 to 124.80 (Δ 0.10/bar), each bar
    spanning close +/- BAR_HALF_RANGE.
    Bar 249 (trigger): bullish bar that dips to touch the support zone
    and closes above its open (close >= open) so the invalidation gate
    does not fire.
    """
    rows: list[dict] = []
    for i in range(250):
        open_t = BASE_OPEN + timedelta(hours=i)
        close_t = open_t + timedelta(hours=1) - timedelta(seconds=1)
        if i < 249:
            price = Decimal("100.00") + Decimal(str(i)) * Decimal("0.10")
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": f"{price:.2f}",
                    "high": f"{price + BAR_HALF_RANGE:.2f}",
                    "low": f"{price - BAR_HALF_RANGE:.2f}",
                    "close": f"{price:.2f}",
                    "volume": "1.0",
                }
            )
        else:
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": "121.50",
                    "high": "125.00",
                    "low": "121.50",
                    "close": "124.50",
                    "volume": "1.0",
                }
            )
    return rows


def _make_1h_candles_short_setup() -> list[dict]:
    """250 1H bars trending down; the last bar spikes to touch the resistance zone.

    Bars 0..248: smooth downtrend from 150.00 to 125.20 (Δ -0.10/bar), each
    bar spanning close +/- BAR_HALF_RANGE.
    Bar 249 (trigger): bearish bar that spikes to touch the resistance
    zone and closes below its open (close <= open) so the invalidation
    gate does not fire.
    """
    rows: list[dict] = []
    for i in range(250):
        open_t = BASE_OPEN + timedelta(hours=i)
        close_t = open_t + timedelta(hours=1) - timedelta(seconds=1)
        if i < 249:
            price = Decimal("150.00") - Decimal(str(i)) * Decimal("0.10")
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": f"{price:.2f}",
                    "high": f"{price + BAR_HALF_RANGE:.2f}",
                    "low": f"{price - BAR_HALF_RANGE:.2f}",
                    "close": f"{price:.2f}",
                    "volume": "1.0",
                }
            )
        else:
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": "128.50",
                    "high": "128.50",
                    "low": "125.00",
                    "close": "125.00",
                    "volume": "1.0",
                }
            )
    return rows


def _make_4h_context_bars_long() -> list[dict]:
    """250 4H bars trending up; last bar close > EMA50 → BULLISH regime.

    The 4H bars are anchored to end at the last 1H trigger bar, so the
    simulator's closed-context filter always sees >=250 bars (enough
    for EMA200). Each 4H bar spans a proper 4-hour period.

    Bars 0..248: smooth uptrend ending at the trigger-bar window.
    Bar 249 (last): the trigger bar itself (close aligned to last 1H).
    """
    rows: list[dict] = []
    last_1h_close = BASE_OPEN + timedelta(hours=250) - timedelta(seconds=1)
    for i in range(250):
        open_t = last_1h_close - timedelta(hours=(250 - i) * 4) + timedelta(seconds=1)
        close_t = open_t + timedelta(hours=4) - timedelta(seconds=1)
        if i < 249:
            price = Decimal("100.00") + Decimal(str(i)) * Decimal("0.40")
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "4h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": f"{price:.2f}",
                    "high": f"{price + Decimal('0.05'):.2f}",
                    "low": f"{price - Decimal('0.05'):.2f}",
                    "close": f"{price:.2f}",
                    "volume": "1.0",
                }
            )
        else:
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "4h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(last_1h_close),
                    "open": "199.60",
                    "high": "199.80",
                    "low": "196.30",
                    "close": "199.30",
                    "volume": "1.0",
                }
            )
    return rows


def _make_4h_context_bars_short() -> list[dict]:
    """250 4H bars trending down; last bar close < EMA50 → BEARISH regime.

    Same anchoring as the LONG variant — bars end at the last 1H trigger
    bar so the closed-context filter always sees >=250 bars.
    """
    rows: list[dict] = []
    last_1h_close = BASE_OPEN + timedelta(hours=250) - timedelta(seconds=1)
    for i in range(250):
        open_t = last_1h_close - timedelta(hours=(250 - i) * 4) + timedelta(seconds=1)
        close_t = open_t + timedelta(hours=4) - timedelta(seconds=1)
        if i < 249:
            price = Decimal("250.00") - Decimal(str(i)) * Decimal("0.40")
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "4h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": f"{price:.2f}",
                    "high": f"{price + Decimal('0.05'):.2f}",
                    "low": f"{price - Decimal('0.05'):.2f}",
                    "close": f"{price:.2f}",
                    "volume": "1.0",
                }
            )
        else:
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "4h",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(last_1h_close),
                    "open": "150.20",
                    "high": "153.50",
                    "low": "150.00",
                    "close": "150.50",
                    "volume": "1.0",
                }
            )
    return rows


def _make_1m_intrabar_long_both_touched() -> list[dict]:
    """60 1m candles for the LONG trigger bar; first candle hits SL before TP.

    Trigger bar range: low=121.50, high=125.00.
    Plan geometry is computed by the planner from BAR_HALF_RANGE bars; the
    planning-time prototype gave entry zone 120.4586 to 122.5414, SL about
    121.1529, TP1 about 125.60 (stop about 1.13 percent of the zone top).
    1m candle 1: low=121.10 (below the SL), high=125.70 (above TP1).
    Per D-01 SL-first ordering: SL wins.
    """
    rows: list[dict] = []
    trigger_open = BASE_OPEN + timedelta(hours=249)
    for i in range(60):
        open_t = trigger_open + timedelta(minutes=i)
        close_t = open_t + timedelta(minutes=1) - timedelta(seconds=1)
        if i == 0:
            # The decisive 1m candle: SL and TP both touched in this candle.
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1m",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": "121.80",
                    "high": "125.70",
                    "low": "121.10",
                    "close": "121.50",
                    "volume": "0.5",
                }
            )
        else:
            # Remaining 1m candles: narrow range above SL.
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1m",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": "121.55",
                    "high": "121.60",
                    "low": "121.50",
                    "close": "121.55",
                    "volume": "0.1",
                }
            )
    return rows


def _make_1m_intrabar_short_both_touched() -> list[dict]:
    """60 1m candles for the SHORT trigger bar; first candle hits SL before TP.

    Trigger bar range: low=125.00, high=128.50.
    Plan geometry is computed by the planner from BAR_HALF_RANGE bars; the
    planning-time prototype gave entry zone 127.459 to 129.541, SL about
    128.847, TP1 about 124.40 (stop about 1.09 percent from the zone bottom).
    1m candle 1: low=124.30 (below TP1), high=128.90 (above the SL).
    Per D-01 SL-first ordering: SL wins.
    """
    rows: list[dict] = []
    trigger_open = BASE_OPEN + timedelta(hours=249)
    for i in range(60):
        open_t = trigger_open + timedelta(minutes=i)
        close_t = open_t + timedelta(minutes=1) - timedelta(seconds=1)
        if i == 0:
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1m",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": "128.20",
                    "high": "128.90",
                    "low": "124.30",
                    "close": "128.10",
                    "volume": "0.5",
                }
            )
        else:
            rows.append(
                {
                    "symbol": SYMBOL,
                    "interval": "1m",
                    "open_time_utc": _fmt(open_t),
                    "close_time_utc": _fmt(close_t),
                    "open": "128.10",
                    "high": "128.15",
                    "low": "128.05",
                    "close": "128.10",
                    "volume": "0.1",
                }
            )
    return rows


# Shared base inputs for trend-pullback baseline-v5 (Phase 12 cost identity).
ACCOUNT_STATE = {"equity": "10000.00", "risk_rate": "0.005"}
CONSTRAINT_SNAPSHOT = {
    "symbol": SYMBOL,
    "price_tick_size": "0.10",
    "quantity_step_size": "0.001",
    "min_quantity": "0.001",
    "min_notional": "50",
    "metadata_observed_at_utc": _fmt(BASE_OPEN + timedelta(hours=249)),
}
COST_MODEL = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "exit_slippage_rate": "0.0003",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1.0",
}
TTL_SECONDS = "3600"
OPEN_POSITIONS: list[dict] = []
DAILY_LOSS_QUOTE = "0"
NOW_UTC = _fmt(BASE_OPEN + timedelta(hours=250))
PARAMETER_SET_ID = "baseline-v5"
STRATEGY_ID = "trend-pullback"
STRATEGY_VERSION = "v4.0.0"


def _build_input(
    *,
    strategy_bars: list[dict],
    context_bars: list[dict],
    intrabar_key: str,
    intrabar_value: list[dict] | None,
) -> dict:
    """Build the canonical input.json shape for Phase 6 cases."""
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "parameter_set_id": PARAMETER_SET_ID,
        "strategy_bars": strategy_bars,
        "context_bars": context_bars,
        "intrabar_1m_map": {intrabar_key: intrabar_value},
        "account_state": ACCOUNT_STATE,
        "constraint_snapshot": CONSTRAINT_SNAPSHOT,
        "cost_model": COST_MODEL,
        "open_positions": OPEN_POSITIONS,
        "daily_loss_quote": DAILY_LOSS_QUOTE,
        "now_utc": NOW_UTC,
        "ttl_seconds": TTL_SECONDS,
    }


def _trigger_bar_close_key() -> str:
    """Return the ISO close_time_utc of the trigger bar (used as 1m map key)."""
    return _fmt(BASE_OPEN + timedelta(hours=249) + timedelta(hours=1) - timedelta(seconds=1))


def write_intrabar_both_touched() -> None:
    """LONG setup; 1m path resolves SL-first (D-01)."""
    bars = _make_1h_candles_long_setup()
    context = _make_4h_context_bars_long()
    key = SYMBOL + "|" + _trigger_bar_close_key()
    payload = _build_input(
        strategy_bars=bars,
        context_bars=context,
        intrabar_key=key,
        intrabar_value=_make_1m_intrabar_long_both_touched(),
    )
    path = FIXTURE_ROOT / "intrabar_both_touched" / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_intrabar_both_touched_short() -> None:
    """SHORT setup; 1m path resolves SL-first (D-01)."""
    bars = _make_1h_candles_short_setup()
    context = _make_4h_context_bars_short()
    key = SYMBOL + "|" + _trigger_bar_close_key()
    payload = _build_input(
        strategy_bars=bars,
        context_bars=context,
        intrabar_key=key,
        intrabar_value=_make_1m_intrabar_short_both_touched(),
    )
    path = FIXTURE_ROOT / "intrabar_both_touched_short" / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_intrabar_missing_fallback() -> None:
    """LONG setup; 1m missing → SL-first fallback + flag (D-01)."""
    bars = _make_1h_candles_long_setup()
    context = _make_4h_context_bars_long()
    key = SYMBOL + "|" + _trigger_bar_close_key()
    payload = _build_input(
        strategy_bars=bars,
        context_bars=context,
        intrabar_key=key,
        intrabar_value=None,
    )
    path = FIXTURE_ROOT / "intrabar_missing_fallback" / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_limit_touch_no_fill() -> None:
    """LONG setup; bar touches zone but partial_fill_fraction=0 → TOUCH_NO_FILL.

    The trigger bar is the standard pullback bar (touches the entry zone).
    The cost model's partial_fill_fraction is set to 0 so the simulator
    emits TOUCH_NO_FILL (filled_quantity <= 0) even though the zone was
    touched. This tests the partial-fill-zero edge case.
    """
    bars = _make_1h_candles_long_setup()
    cost = dict(COST_MODEL)
    cost["partial_fill_fraction"] = "0"
    context_bars = _make_4h_context_bars_long()
    key = SYMBOL + "|" + _trigger_bar_close_key()
    payload = {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "parameter_set_id": PARAMETER_SET_ID,
        "strategy_bars": bars,
        "context_bars": context_bars,
        "intrabar_1m_map": {key: None},
        "account_state": ACCOUNT_STATE,
        "constraint_snapshot": CONSTRAINT_SNAPSHOT,
        "cost_model": cost,
        "open_positions": OPEN_POSITIONS,
        "daily_loss_quote": DAILY_LOSS_QUOTE,
        "now_utc": NOW_UTC,
        "ttl_seconds": TTL_SECONDS,
    }
    path = FIXTURE_ROOT / "limit_touch_no_fill" / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_limit_partial_fill() -> None:
    """LONG setup; partial-fill fraction < 1.0 applied to quantity."""
    bars = _make_1h_candles_long_setup()
    cost = dict(COST_MODEL)
    cost["partial_fill_fraction"] = "0.5"
    context_bars = _make_4h_context_bars_long()
    key = SYMBOL + "|" + _trigger_bar_close_key()
    payload = {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "parameter_set_id": PARAMETER_SET_ID,
        "strategy_bars": bars,
        "context_bars": context_bars,
        "intrabar_1m_map": {key: _make_1m_intrabar_long_both_touched()},
        "account_state": ACCOUNT_STATE,
        "constraint_snapshot": CONSTRAINT_SNAPSHOT,
        "cost_model": cost,
        "open_positions": OPEN_POSITIONS,
        "daily_loss_quote": DAILY_LOSS_QUOTE,
        "now_utc": NOW_UTC,
        "ttl_seconds": TTL_SECONDS,
    }
    path = FIXTURE_ROOT / "limit_partial_fill" / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_limit_expiry() -> list[dict]:
    """LONG setup; now_utc past expiry → EXPIRED (no retroactive fill).

    The trigger bar is the standard pullback bar (touches the entry zone).
    now_utc is set past the signal's expiry_utc (source_close +
    signal_expiry_hours = 4h) so the expiry gate fires before any
    zone-touch check.
    """
    bars = _make_1h_candles_long_setup()
    context_bars = _make_4h_context_bars_long()
    key = SYMBOL + "|" + _trigger_bar_close_key()
    expired_now = _fmt(BASE_OPEN + timedelta(hours=260))
    payload = {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "parameter_set_id": PARAMETER_SET_ID,
        "strategy_bars": bars,
        "context_bars": context_bars,
        "intrabar_1m_map": {key: None},
        "account_state": ACCOUNT_STATE,
        "constraint_snapshot": CONSTRAINT_SNAPSHOT,
        "cost_model": COST_MODEL,
        "open_positions": OPEN_POSITIONS,
        "daily_loss_quote": DAILY_LOSS_QUOTE,
        "now_utc": expired_now,
        "ttl_seconds": TTL_SECONDS,
    }
    path = FIXTURE_ROOT / "limit_expiry" / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return bars


def write_invalidation_cancels_entry() -> None:
    """LONG setup; bar closes below SL before any fill → INVALIDATION_CANCEL.

    The trigger bar's range still overlaps the entry zone (so the strategy
    produces a signal and the planner/risk pipeline runs), but bar.close
    sits below the SL level (swing_low - sl_buffer_atr * ATR). The
    invalidation gate fires before the zone-touch check, so the entry
    is cancelled. The trigger bar's low is kept above the previous
    swing_low so the Candle validation (close >= low) is satisfied.
    """
    bars = _make_1h_candles_long_setup()
    bars[-1] = {
        "symbol": SYMBOL,
        "interval": "1h",
        "open_time_utc": bars[-1]["open_time_utc"],
        "close_time_utc": bars[-1]["close_time_utc"],
        "open": "123.50",
        "high": "124.00",
        "low": "122.50",
        "close": "122.50",
        "volume": "1.0",
    }
    context_bars = _make_4h_context_bars_long()
    key = SYMBOL + "|" + _trigger_bar_close_key()
    payload = {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "parameter_set_id": PARAMETER_SET_ID,
        "strategy_bars": bars,
        "context_bars": context_bars,
        "intrabar_1m_map": {key: None},
        "account_state": ACCOUNT_STATE,
        "constraint_snapshot": CONSTRAINT_SNAPSHOT,
        "cost_model": COST_MODEL,
        "open_positions": OPEN_POSITIONS,
        "daily_loss_quote": DAILY_LOSS_QUOTE,
        "now_utc": NOW_UTC,
        "ttl_seconds": TTL_SECONDS,
    }
    path = FIXTURE_ROOT / "invalidation_cancels_entry" / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    write_intrabar_both_touched()
    write_intrabar_both_touched_short()
    write_intrabar_missing_fallback()
    write_limit_touch_no_fill()
    write_limit_partial_fill()
    write_limit_expiry()
    write_invalidation_cancels_entry()
    print("Phase 6 fixtures written.")


if __name__ == "__main__":
    main()
