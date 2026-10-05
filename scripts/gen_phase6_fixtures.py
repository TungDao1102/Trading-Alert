"""Helper script to generate Phase 6 backtest fixture data deterministically.

Phase 14 (plan 14-12, D-24, D-25): every output is a case-input v2 dict
("backtest-case/2"), driven through the event-loop engine
(`src.backtest.engine.simulate`) via `src.backtest.simulator.run`. The 1H and 4H
geometry is unchanged from Phase 12:

  - trend-pullback (Family A) baseline-v5 parameters produce a known setup
  - 4H context confirms the regime
  - bar 249 (the trigger bar) closes at 2026-09-11 09:59:59 UTC and creates the plan
  - the plan RESTS from bar 250 onward and is filled, stopped, expired or cancelled by
    the 1m trade and mark minutes of this script

The generator NEVER places 1m data inside the signal bar: the first minute of every case
opens at 10:00:00 UTC, the first minute after the trigger bar close (D-24, F-602). A case
whose scenario needs a strategy bar N+1 (the missing-mark fallback and the invalidation
case) carries bar 250 as an extra 1H row.

Phase 12 (F-002, F-608): the 1H bars carry a realistic half-range (BAR_HALF_RANGE = 0.80)
so the ATR-derived stop sits about 1.1 percent from entry instead of 0.06 to 0.26
percent. That clears the minimum-stop (0.3 percent) and cost-to-risk (0.15) guards with
margin. The plan geometry is DERIVED by the planner from the bars; the numbers quoted in
the docstrings below are illustrations from the planning-time prototype, and
tests/test_phase6_fixture_geometry.py recomputes and checks them with independent
arithmetic. For the LONG case the zone is 120.4586 to 122.5414 (limit 121.50, the zone
mid), the stop 121.1529 (trigger 121.2 after the tick snap), TP1 125.60 and TP2 129.70;
the SHORT mirror has limit 128.50, stop 128.8471, TP1 124.40 and TP2 120.30. The tick is
0.10, so a LONG limit fills only on a trade-price low of 121.40 or lower (a SHORT: a high
of 128.60 or higher); a low of exactly 121.50 is a touch without a fill (D-07).

The expected outputs of these cases are regression snapshots (D-25, F-608): they are pinned
from the v2 engine, not hand-derived. Hand-derived goldens live in tests/fixtures/phase14.

This script is committed for reproducibility - re-running it regenerates
byte-identical fixtures. It imports nothing from src/.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "phase6"
PHASE7_FIXTURE_ROOT = FIXTURE_ROOT.parent / "phase7"
SYMBOL = "BTCUSDT"

# 1H bar half-range (high = close + half, low = close - half) for bars
# 0..248. Larger half-range -> larger ATR -> wider stop -> lower
# cost-to-risk. Never tune a guard or registry value instead (Phase 12).
BAR_HALF_RANGE = Decimal("0.80")

# Base epoch for fixture candles (deterministic, stable across runs).
BASE_OPEN = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

# The trigger (signal) bar is bar 249; its close is 09:59:59 on 2026-09-11. The first 1m
# minute of every case opens one second later, at 10:00:00 (D-24).
FIRST_MINUTE_OPEN = BASE_OPEN + timedelta(hours=250)
# Strategy bars before the data window are warm-up; the window starts at midnight UTC of the
# trigger day, a funding instant, so the funding history covers it from its first row.
DATA_START = BASE_OPEN + timedelta(hours=240)
# One hour of minutes (10:00 to 10:59), or four hours (10:00 to 13:59) for the cases that run
# up to the plan expiry at 13:59:59.
HOUR_MINUTES = 60
EXPIRY_MINUTES = 240
HOUR_DATA_END = FIRST_MINUTE_OPEN + timedelta(hours=1)
EXPIRY_DATA_END = FIRST_MINUTE_OPEN + timedelta(hours=4)


def _fmt(dt: datetime) -> str:
    """Format datetime as ISO 8601 with +00:00 suffix."""
    return dt.astimezone(UTC).isoformat()


def _make_1h_candles_long_setup() -> list[dict]:
    """250 1H bars trending up; the last bar dips to touch the support zone.

    Bars 0..248: smooth uptrend from 100.00 to 124.80 (delta 0.10/bar), each bar
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

    Bars 0..248: smooth downtrend from 150.00 to 125.20 (delta -0.10/bar), each
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
    """250 4H bars trending up; last bar close > EMA50 -> BULLISH regime.

    The 4H bars are anchored to end at the last 1H trigger bar, so the
    engine's closed-context window always sees >=250 bars (enough
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
    """250 4H bars trending down; last bar close < EMA50 -> BEARISH regime.

    Same anchoring as the LONG variant - bars end at the last 1H trigger
    bar so the closed-context window always sees >=250 bars.
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


def _bar_250(open_: str, high: str, low: str, close: str) -> dict:
    """The strategy bar N+1 (10:00 to 10:59:59), for the cases whose scenario needs it."""
    return {
        "symbol": SYMBOL,
        "interval": "1h",
        "open_time_utc": _fmt(FIRST_MINUTE_OPEN),
        "close_time_utc": _fmt(FIRST_MINUTE_OPEN + timedelta(hours=1) - timedelta(seconds=1)),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": "1.0",
    }


# --------------------------------------------------------------------------- #
# 1m minute paths. A path maps a minute index (0 = 10:00) to (open, high, low, close).
# Trade rows carry a volume, mark rows do not (the real mark klines have none).
# --------------------------------------------------------------------------- #

Ohlc = tuple[str, str, str, str]
Path1m = Callable[[int], Ohlc]


def _minute_rows(
    kind: str,
    count: int,
    path: Path1m,
    holes: frozenset[int] = frozenset(),
) -> list[dict]:
    """`count` consecutive minutes from 10:00 following `path`; indexes in `holes` are absent."""
    rows: list[dict] = []
    for i in range(count):
        if i in holes:
            continue
        open_t = FIRST_MINUTE_OPEN + timedelta(minutes=i)
        close_t = open_t + timedelta(minutes=1) - timedelta(seconds=1)
        o, h, lo, c = path(i)
        row = {
            "symbol": SYMBOL,
            "interval": "1m",
            "open_time_utc": _fmt(open_t),
            "close_time_utc": _fmt(close_t),
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
        }
        if kind == "trade":
            row["volume"] = "1.0"
        rows.append(row)
    return rows


FILL_MINUTE = 5  # 10:05, the minute that trades through the limit
EXIT_MINUTE = 6  # 10:06, the first minute after the fill minute


def _long_resting(i: int) -> Ohlc:
    """LONG price above the limit (121.50): never reaches it."""
    return ("123.00", "123.05", "122.95", "123.00")


def _long_both_touched(kind: str) -> Path1m:
    """LONG: rest, trade through the limit at 10:05, then one minute touching SL and TP1.

    Minute 5 (10:05) trade low 121.40 trades through the 121.50 limit by one tick (fill at
    the close of the minute); its mark minute low 121.45 stays above the stop trigger 121.2,
    so the fill minute does not stop out. Minute 6 (10:06) low 121.10 touches the stop and
    high 125.70 touches TP1 (125.60): the stop wins (stop-first, D-12).
    """

    def path(i: int) -> Ohlc:
        if i < FILL_MINUTE:
            return _long_resting(i)
        if i == FILL_MINUTE:
            low = "121.40" if kind == "trade" else "121.45"
            return ("121.80", "121.90", low, "121.60")
        if i == EXIT_MINUTE:
            return ("121.60", "125.70", "121.10", "121.50")
        return ("121.55", "121.60", "121.50", "121.55")

    return path


def _short_resting(i: int) -> Ohlc:
    """SHORT price below the limit (128.50): never reaches it."""
    return ("126.00", "126.05", "125.95", "126.00")


def _short_both_touched(kind: str) -> Path1m:
    """SHORT mirror: trade high 128.60 trades through the 128.50 limit; stop 128.8, TP1 124.40."""

    def path(i: int) -> Ohlc:
        if i < FILL_MINUTE:
            return _short_resting(i)
        if i == FILL_MINUTE:
            high = "128.60" if kind == "trade" else "128.55"
            return ("128.20", high, "128.10", "128.30")
        if i == EXIT_MINUTE:
            return ("128.30", "128.90", "124.30", "128.50")
        return ("128.45", "128.50", "128.40", "128.45")

    return path


def _long_missing_mark(kind: str) -> Path1m:
    """LONG fill at 10:05 and a hole in the mark series from 10:06 to the end of the hour.

    The trade series continues (its low 121.00 at 10:20 is what the bar 250 range carries).
    """

    def path(i: int) -> Ohlc:
        if i < FILL_MINUTE:
            return _long_resting(i)
        if i == FILL_MINUTE:
            low = "121.40" if kind == "trade" else "121.45"
            return ("121.80", "121.90", low, "121.60")
        if i == 20:
            return ("121.55", "121.60", "121.00", "121.50")
        return ("121.55", "121.60", "121.50", "121.55")

    return path


def _long_touch_only(kind: str) -> Path1m:
    """LONG minutes that reach the limit 121.50 exactly (a touch, no trade-through) three times."""

    def path(i: int) -> Ohlc:
        if i in (10, 11, 30):
            low = "121.50" if kind == "trade" else "121.52"
            return ("121.80", "121.90", low, "121.70")
        return _long_resting(i)

    return path


def _long_tp_ladder(kind: str) -> Path1m:
    """LONG: fill at 10:05, TP1 (125.60) at 10:06, TP2 (129.70) at 10:07."""

    def path(i: int) -> Ohlc:
        if i < FILL_MINUTE:
            return _long_resting(i)
        if i == FILL_MINUTE:
            low = "121.40" if kind == "trade" else "121.45"
            return ("121.80", "121.90", low, "121.60")
        if i == EXIT_MINUTE:
            return ("121.60", "125.70", "121.50", "125.60")
        if i == EXIT_MINUTE + 1:
            return ("125.60", "130.00", "125.40", "129.80")
        return ("129.80", "129.85", "129.75", "129.80")

    return path


def _long_invalidation(kind: str) -> Path1m:
    """LONG minutes stay above the limit until 10:49; the rest of the hour is a data hole."""
    return _long_resting


# Shared base inputs for trend-pullback baseline-v5 (Phase 12 cost identity).
ACCOUNT_STATE = {"equity": "10000.00", "risk_rate": "0.005"}
CONSTRAINT_HISTORY = [
    {
        "symbol": SYMBOL,
        "metadata_observed_at_utc": _fmt(BASE_OPEN),
        "price_tick_size": "0.10",
        "quantity_step_size": "0.001",
        "min_quantity": "0.001",
        "min_notional": "50",
    }
]
COST_MODEL = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "exit_slippage_rate": "0.0003",
    # Funding sign convention joins cost identity for sizeable sets (Phase 14,
    # D-16). Literal on purpose: this script imports nothing from src/. The
    # binding gate (cost_slice appends semantics.FUNDING_CONVENTION) refuses a
    # fixture whose value drifts from the code constant.
    "funding_convention": "MARK_NOTIONAL_SIGNED_V1",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1.0",
}
PARAMETER_SET_ID = "baseline-v5"
# Degenerated baseline sets (Phase 12 cost identity, same strategy version).
BASELINE_NO_TRADE_SET_ID = "baseline-no-trade-v3"
BASELINE_SIMPLE_TREND_SET_ID = "baseline-simple-trend-v3"
STRATEGY_ID = "trend-pullback"
STRATEGY_VERSION = "v4.0.0"


def _funding_rows() -> list[dict]:
    """Funding at 00:00, 08:00 and 16:00 UTC from 2026-09-10 16:00 to 2026-09-12 00:00.

    The rows cover every data window of this script (00:00 on the 11th to 14:00): the
    first row is at or before the window start and the last at or after its end, and no
    two rows are more than eight hours apart (D-36). The mark price rides on the row.
    """
    instants = [
        datetime(2026, 9, 10, 16, 0, tzinfo=UTC),
        datetime(2026, 9, 11, 0, 0, tzinfo=UTC),
        datetime(2026, 9, 11, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 11, 16, 0, tzinfo=UTC),
        datetime(2026, 9, 12, 0, 0, tzinfo=UTC),
    ]
    return [
        {
            "symbol": SYMBOL,
            "funding_time_utc": _fmt(when),
            "funding_rate": "0.0001",
            "mark_price": "121.50",
        }
        for when in instants
    ]


def _build_input(
    *,
    strategy_bars: list[dict],
    context_bars: list[dict],
    trade_bars_1m: list[dict],
    mark_bars_1m: list[dict],
    data_end: datetime,
    parameter_set_id: str = PARAMETER_SET_ID,
    cost_overrides: dict[str, str] | None = None,
) -> dict:
    """Build the canonical case-input v2 `input.json` shape for the Phase 6 cases."""
    cost_model = dict(COST_MODEL)
    if cost_overrides:
        cost_model.update(cost_overrides)
    return {
        "case_input_schema": "backtest-case/2",
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "parameter_set_id": parameter_set_id,
        "symbols": [SYMBOL],
        "strategy_bars": strategy_bars,
        "context_bars": context_bars,
        "trade_bars_1m": trade_bars_1m,
        "mark_bars_1m": mark_bars_1m,
        "funding": _funding_rows(),
        "constraint_history": CONSTRAINT_HISTORY,
        "account_state": ACCOUNT_STATE,
        "cost_model": cost_model,
        "data_window": {"start_utc": _fmt(DATA_START), "end_utc": _fmt(data_end)},
        "allowed_gaps": [],
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _long_case(
    *,
    path_for: Callable[[str], Path1m],
    count: int = HOUR_MINUTES,
    data_end: datetime = HOUR_DATA_END,
    trade_holes: frozenset[int] = frozenset(),
    mark_holes: frozenset[int] = frozenset(),
    extra_bar: dict | None = None,
    parameter_set_id: str = PARAMETER_SET_ID,
    cost_overrides: dict[str, str] | None = None,
) -> dict:
    bars = _make_1h_candles_long_setup()
    if extra_bar is not None:
        bars.append(extra_bar)
    return _build_input(
        strategy_bars=bars,
        context_bars=_make_4h_context_bars_long(),
        trade_bars_1m=_minute_rows("trade", count, path_for("trade"), trade_holes),
        mark_bars_1m=_minute_rows("mark", count, path_for("mark"), mark_holes),
        data_end=data_end,
        parameter_set_id=parameter_set_id,
        cost_overrides=cost_overrides,
    )


def write_intrabar_both_touched() -> None:
    """LONG setup; fill at 10:05, then a minute touching SL and TP1: stop-first (D-12)."""
    _write(
        FIXTURE_ROOT / "intrabar_both_touched" / "input.json",
        _long_case(path_for=_long_both_touched),
    )


def write_parity_overlapping_history() -> None:
    """Phase 7 backtest-to-paper parity input: the LONG both-touched payload (12-09).

    A copy of the `intrabar_both_touched` payload (baseline-v5 identity and the nine-key
    cost dict) written under the Phase 7 fixture root, so the parity fixture stays on the
    same registry set as the Phase 6 fixtures. It holds a single signal and a single plan,
    so the portfolio ledger never binds a later verdict (D-18, RESEARCH Q7). `expected.json`
    (digest and the documentary hashes) is pinned from the engine output through the
    computation in tests/test_paper_parity.py.
    """
    _write(
        PHASE7_FIXTURE_ROOT / "parity_overlapping_history" / "input.json",
        _long_case(path_for=_long_both_touched),
    )


def _write_baseline(case_name: str, parameter_set_id: str) -> None:
    """Baseline fixture: the LONG both-touched payload on a degenerated set."""
    _write(
        FIXTURE_ROOT / "baselines" / case_name / "input.json",
        _long_case(path_for=_long_both_touched, parameter_set_id=parameter_set_id),
    )


def write_baseline_no_trade() -> None:
    """No-trade baseline: minimum_rr=100 makes the planner reject (RR_TOO_LOW)."""
    _write_baseline("no_trade", BASELINE_NO_TRADE_SET_ID)


def write_baseline_simple_trend() -> None:
    """Simple-trend baseline: looser minimum_rr, wider zone; yields a real plan."""
    _write_baseline("simple_trend", BASELINE_SIMPLE_TREND_SET_ID)


def write_intrabar_both_touched_short() -> None:
    """SHORT setup; fill at 10:05, then a minute touching SL and TP1: stop-first (D-12)."""
    bars = _make_1h_candles_short_setup()
    payload = _build_input(
        strategy_bars=bars,
        context_bars=_make_4h_context_bars_short(),
        trade_bars_1m=_minute_rows("trade", HOUR_MINUTES, _short_both_touched("trade")),
        mark_bars_1m=_minute_rows("mark", HOUR_MINUTES, _short_both_touched("mark")),
        data_end=HOUR_DATA_END,
    )
    _write(FIXTURE_ROOT / "intrabar_both_touched_short" / "input.json", payload)


def write_intrabar_missing_fallback() -> None:
    """LONG setup; fill at 10:05, then the mark series has a hole from 10:06 (D-12).

    The strategy bar N+1 (bar 250, 10:00 to 10:59:59) has a low of 121.00 below the stop,
    so the rest of the hour resolves once at the bar close from the bar range, stop first,
    with `fallback_applied` set and a coverage note (never synthesized minute prices).
    """
    payload = _long_case(
        path_for=_long_missing_mark,
        mark_holes=frozenset(range(EXIT_MINUTE, HOUR_MINUTES)),
        extra_bar=_bar_250("123.00", "123.10", "121.00", "121.60"),
    )
    _write(FIXTURE_ROOT / "intrabar_missing_fallback" / "input.json", payload)


def write_limit_touch_no_fill() -> None:
    """LONG setup; three minutes reach the limit exactly but never trade through it.

    The plan rests until its expiry (13:59:59) and ends EXPIRED with
    `touch_no_fill_count` 3 (D-07, D-34). The 1m data covers every minute up to the expiry.
    """
    payload = _long_case(
        path_for=_long_touch_only,
        count=EXPIRY_MINUTES,
        data_end=EXPIRY_DATA_END,
    )
    _write(FIXTURE_ROOT / "limit_touch_no_fill" / "input.json", payload)


def write_limit_partial_fill() -> None:
    """LONG setup; partial_fill_fraction 0.5 fills half the planned size, then TP1 and TP2."""
    payload = _long_case(path_for=_long_tp_ladder, cost_overrides={"partial_fill_fraction": "0.5"})
    _write(FIXTURE_ROOT / "limit_partial_fill" / "input.json", payload)


def write_limit_expiry() -> None:
    """LONG setup; the limit is never reached and the plan expires at 13:59:59 (D-04)."""
    payload = _long_case(
        path_for=lambda kind: _long_resting,
        count=EXPIRY_MINUTES,
        data_end=EXPIRY_DATA_END,
    )
    _write(FIXTURE_ROOT / "limit_expiry" / "input.json", payload)


def write_invalidation_cancels_entry() -> None:
    """LONG setup; the bar after the trigger closes beyond the invalidation level (D-05, D-35).

    Bar 250 closes at 120.80, below the plan's CANDLE_CLOSE level (about 121.15), while the
    plan is still resting. The 1m data stops at 10:49: the last ten minutes of the hour are a
    data hole, because a real fall through the limit would show as a trade-through and fill
    the plan first. The case is therefore a synthetic regression snapshot of the precedence
    rule fill, then invalidation, then expiry; it is not a realistic price path.
    """
    holes = frozenset(range(50, HOUR_MINUTES))
    payload = _long_case(
        path_for=_long_invalidation,
        trade_holes=holes,
        mark_holes=holes,
        extra_bar=_bar_250("123.50", "123.60", "120.50", "120.80"),
    )
    _write(FIXTURE_ROOT / "invalidation_cancels_entry" / "input.json", payload)


def main() -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    write_intrabar_both_touched()
    write_parity_overlapping_history()
    write_intrabar_both_touched_short()
    write_intrabar_missing_fallback()
    write_limit_touch_no_fill()
    write_limit_partial_fill()
    write_limit_expiry()
    write_invalidation_cancels_entry()
    write_baseline_no_trade()
    write_baseline_simple_trend()
    print("Phase 6 fixtures written.")


if __name__ == "__main__":
    main()
