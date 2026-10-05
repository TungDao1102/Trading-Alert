"""Deterministic INPUT generator for the Phase 14 golden cases (plan 14-13, D-24, F-602, F-805).

Writes `<out>/<case>/input.json` for the sixteen golden cases of the causal simulator and
NOTHING else. The expected outputs are never produced here: every `expected.json` is written
by hand from a section of `tests/fixtures/phase14/DERIVATIONS.md`, whose numbers come from an
independent Decimal computation (see that file), never from the output of the code under test.
This script imports nothing from `src/` or `tests/`, so it cannot even reach the simulator.

Every case is a case-input v2 dict ("backtest-case/2") with a scripted plan (the strategy
front-end is bypassed, so the plan geometry is a round number the derivation can do by hand).
The common inputs are:

  - BTCUSDT-style synthetic prices around 100, baseline-v5 cost slice with the funding
    convention, equity 10000, risk_rate 0.005;
  - zone 99.00 to 101.00 (limit = mid 100.00), stop 98.00, TP1 104.00, TP2 108.00 for the LONG
    base case, the mirror zone with stop 102.00, TP1 96.00, TP2 92.00 for the SHORT base case;
  - tick 0.10, step 0.001, min quantity 0.001, min notional 5, constraint row observed
    2025-12-01;
  - the plan is created at the close of the 1h bar that ends 2026-01-05 09:59:59.999 UTC, and
    the 1m trade and mark minutes of a case open at 10:00:00 or later (D-24).

STRUCTURAL GUARD: the minute builder `_minute_rows` raises `ValueError` for any minute whose
open time is at or before the close of the scripted plan it belongs to, so this script cannot
place 1m data inside the signal bar. It also raises for a minute whose OHLC is not coherent
(low above open/close, high below open/close).

Running it twice gives byte-identical files (sorted keys, LF line endings, no clock).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "phase14"

Ohlc = tuple[str, str, str, str]

DAY = datetime(2026, 1, 5, tzinfo=UTC)
SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)
DATA_START = DAY
DEFAULT_DATA_END = DAY + timedelta(hours=12)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
MS = timedelta(milliseconds=1)

# baseline-v5 cost slice (strings) incl. the funding convention (D-16, D-36).
COST_MODEL: dict[str, str] = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1.0",
    "exit_slippage_rate": "0.0003",
    "funding_convention": "MARK_NOTIONAL_SIGNED_V1",
}

# Flat price paths. A resting LONG sits above its limit (100.0), a resting SHORT below it.
LONG_FLAT: Ohlc = ("101.0", "101.2", "100.6", "101.0")
SHORT_FLAT: Ohlc = ("99.0", "99.4", "98.8", "99.0")


# --------------------------------------------------------------------------- #
# time and row helpers
# --------------------------------------------------------------------------- #


def _clock(hhmm: str) -> datetime:
    """UTC instant of `HH:MM` on the fixture day."""
    hour, minute = hhmm.split(":")
    return DAY + timedelta(hours=int(hour), minutes=int(minute))


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat()


def _minute_close(open_time: datetime) -> datetime:
    return open_time + timedelta(seconds=59, milliseconds=999)


def _check_ohlc(label: str, ohlc: Ohlc) -> None:
    o, h, lo, c = (Decimal(x) for x in ohlc)
    if not (lo <= min(o, c) and h >= max(o, c) and lo <= h):
        raise ValueError(f"{label}: incoherent OHLC {ohlc}")


def _span(first: str, last: str, ohlc: Ohlc) -> dict[str, Ohlc]:
    """Overrides for every minute from `first` to `last` inclusive (both `HH:MM`)."""
    out: dict[str, Ohlc] = {}
    cursor, end = _clock(first), _clock(last)
    while cursor <= end:
        out[f"{cursor.hour:02d}:{cursor.minute:02d}"] = ohlc
        cursor += MINUTE
    return out


def _minute_rows(
    symbol: str,
    kind: str,
    *,
    first: str,
    count: int,
    base: Ohlc,
    overrides: Mapping[str, Ohlc] | None = None,
    holes: Sequence[str] = (),
    not_before: datetime,
) -> list[dict[str, str]]:
    """`count` consecutive 1m rows from `first`, `base` OHLC unless overridden.

    `not_before` is the close of the scripted plan the minutes belong to. A minute whose
    OPEN time is at or before it is refused: 1m data starts at bar N+1 (D-24, F-602). Rows in
    `holes` (`HH:MM`) are left out, an explicit data hole. Trade rows carry a volume, mark
    rows do not.
    """
    if kind not in ("trade", "mark"):
        raise ValueError(f"kind must be trade or mark, got {kind!r}")
    override_map = dict(overrides or {})
    unknown = sorted(set(override_map) - {_label(_clock(first) + MINUTE * i) for i in range(count)})
    if unknown:
        raise ValueError(f"overrides outside the generated range: {unknown}")
    hole_set = set(holes)
    rows: list[dict[str, str]] = []
    for index in range(count):
        opened = _clock(first) + MINUTE * index
        label = _label(opened)
        if label in hole_set:
            continue
        if opened <= not_before:
            raise ValueError(
                f"{symbol} {kind} minute {opened.isoformat()} opens at or before the plan's "
                f"bar close {not_before.isoformat()}: 1m data must start at bar N+1"
            )
        ohlc = override_map.get(label, base)
        _check_ohlc(f"{symbol} {kind} {label}", ohlc)
        row = {
            "symbol": symbol,
            "interval": "1m",
            "open_time_utc": _iso(opened),
            "close_time_utc": _iso(_minute_close(opened)),
            "open": ohlc[0],
            "high": ohlc[1],
            "low": ohlc[2],
            "close": ohlc[3],
        }
        if kind == "trade":
            row["volume"] = "1"
        rows.append(row)
    return rows


def _label(when: datetime) -> str:
    return f"{when.hour:02d}:{when.minute:02d}"


def _hour_bar(symbol: str, hour_open: datetime, ohlc: Ohlc) -> dict[str, str]:
    """One 1h strategy bar row; the close is 1 ms before the next open."""
    _check_ohlc(f"{symbol} bar {hour_open.isoformat()}", ohlc)
    return {
        "symbol": symbol,
        "interval": "1h",
        "open_time_utc": _iso(hour_open),
        "close_time_utc": _iso(hour_open + HOUR - MS),
        "open": ohlc[0],
        "high": ohlc[1],
        "low": ohlc[2],
        "close": ohlc[3],
        "volume": "1",
    }


def _bar_from_trade_minutes(
    symbol: str, hour_open: datetime, trade_rows: Sequence[Mapping[str, str]]
) -> dict[str, str]:
    """The 1h bar whose OHLC is the aggregate of the hour's trade minutes (consistent by design)."""
    inside = [
        r
        for r in trade_rows
        if r["symbol"] == symbol
        and hour_open <= datetime.fromisoformat(r["open_time_utc"]) < hour_open + HOUR
    ]
    if not inside:
        raise ValueError(f"no trade minutes for {symbol} in the hour of {hour_open.isoformat()}")
    highs = [Decimal(r["high"]) for r in inside]
    lows = [Decimal(r["low"]) for r in inside]
    return _hour_bar(
        symbol,
        hour_open,
        (inside[0]["open"], str(max(highs)), str(min(lows)), inside[-1]["close"]),
    )


def _plan(
    symbol: str,
    *,
    signal_id: str,
    direction: str = "LONG",
    close: datetime = SIGNAL_CLOSE,
    zone: tuple[str, str] = ("99.00", "101.00"),
    stop: str = "98.00",
    tp1: str = "104.00",
    tp2: str = "108.00",
    expiry_hours: int = 4,
) -> dict[str, object]:
    """One scripted plan row scheduled at the close of the strategy bar `close`."""
    return {
        "symbol": symbol,
        "bar_close_utc": _iso(close),
        "signal_id": signal_id,
        "direction": direction,
        "entry_min_price": zone[0],
        "entry_max_price": zone[1],
        "stop_loss_price": stop,
        "tp1": tp1,
        "tp2": tp2,
        "expiry_hours": expiry_hours,
    }


def _short_plan(
    symbol: str, *, signal_id: str, close: datetime = SIGNAL_CLOSE
) -> dict[str, object]:
    """The SHORT base plan: zone 99.00 to 101.00, stop 102.00, TP1 96.00, TP2 92.00."""
    return _plan(
        symbol,
        signal_id=signal_id,
        direction="SHORT",
        close=close,
        stop="102.00",
        tp1="96.00",
        tp2="92.00",
    )


def _funding_rows(
    symbols: Sequence[str], extra: Sequence[tuple[str, str, str, str]] = ()
) -> list[dict[str, str | None]]:
    """Funding history: 8 h grid rows outside every holding window plus `extra` actual instants.

    `extra` rows are `(symbol, "HH:MM", rate, mark)`. They are synthetic instants a few minutes
    apart, chosen so a position held for tens of minutes crosses two or three of them (D-14
    allows any actual `fundingTime`, there is no fixed grid).
    """
    rows: list[dict[str, str | None]] = []
    grid = [
        datetime(2026, 1, 4, 16, 0, tzinfo=UTC),
        DAY,
        DAY + timedelta(hours=8),
        DAY + timedelta(hours=16),
    ]
    for symbol in symbols:
        for when in grid:
            rows.append(
                {
                    "symbol": symbol,
                    "funding_time_utc": _iso(when),
                    "funding_rate": "0.0001",
                    "mark_price": "100",
                }
            )
    for symbol, hhmm, rate, mark in extra:
        rows.append(
            {
                "symbol": symbol,
                "funding_time_utc": _iso(_clock(hhmm)),
                "funding_rate": rate,
                "mark_price": mark,
            }
        )
    return rows


def _constraint_rows(symbols: Sequence[str]) -> list[dict[str, str]]:
    return [
        {
            "symbol": symbol,
            "metadata_observed_at_utc": _iso(datetime(2025, 12, 1, tzinfo=UTC)),
            "price_tick_size": "0.10",
            "quantity_step_size": "0.001",
            "min_quantity": "0.001",
            "min_notional": "5",
        }
        for symbol in symbols
    ]


def _case(
    *,
    symbols: Sequence[str],
    plans: Sequence[dict[str, object]],
    trade: Sequence[dict[str, str]],
    mark: Sequence[dict[str, str]],
    strategy_bars: Sequence[dict[str, str]] = (),
    funding_extra: Sequence[tuple[str, str, str, str]] = (),
    data_end: datetime = DEFAULT_DATA_END,
) -> dict[str, object]:
    """Assemble a case-input v2 dict. Every number is a string (the parser refuses floats)."""
    return {
        "case_input_schema": "backtest-case/2",
        "strategy_id": "trend-pullback",
        "strategy_version": "v4.0.0",
        "parameter_set_id": "baseline-v5",
        "symbols": list(symbols),
        "strategy_bars": list(strategy_bars),
        "context_bars": [],
        "trade_bars_1m": list(trade),
        "mark_bars_1m": list(mark),
        "funding": _funding_rows(symbols, funding_extra),
        "constraint_history": _constraint_rows(symbols),
        "account_state": {"equity": "10000", "risk_rate": "0.005"},
        "cost_model": dict(COST_MODEL),
        "data_window": {"start_utc": _iso(DATA_START), "end_utc": _iso(data_end)},
        "allowed_gaps": [],
        "scripted_plans": list(plans),
    }


def _single(
    plan: dict[str, object],
    *,
    first: str = "10:00",
    count: int = 60,
    flat: Ohlc = LONG_FLAT,
    trade: Mapping[str, Ohlc] | None = None,
    mark: Mapping[str, Ohlc] | None = None,
    mark_holes: Sequence[str] = (),
    strategy_bars: Sequence[dict[str, str]] = (),
    funding_extra: Sequence[tuple[str, str, str, str]] = (),
    data_end: datetime = DEFAULT_DATA_END,
) -> dict[str, object]:
    """A one-symbol, one-plan case (the shape of most goldens)."""
    symbol = str(plan["symbol"])
    close = datetime.fromisoformat(str(plan["bar_close_utc"]))
    trade_rows = _minute_rows(
        symbol, "trade", first=first, count=count, base=flat, overrides=trade, not_before=close
    )
    mark_rows = _minute_rows(
        symbol,
        "mark",
        first=first,
        count=count,
        base=flat,
        overrides=mark,
        holes=mark_holes,
        not_before=close,
    )
    return _case(
        symbols=[symbol],
        plans=[plan],
        trade=trade_rows,
        mark=mark_rows,
        strategy_bars=strategy_bars,
        funding_extra=funding_extra,
        data_end=data_end,
    )


# Reusable minute shapes. A trade-through for the LONG base case is a low of limit - tick
# (99.9); the deciding mark minute keeps its low above the stop 98.0 (only SL can trigger on
# the fill minute, D-33).
LONG_FILL_TRADE: Ohlc = ("100.6", "100.8", "99.9", "100.2")
LONG_FILL_MARK: Ohlc = ("100.6", "100.8", "99.95", "100.2")
LONG_STOP_MARK: Ohlc = ("100.2", "100.3", "97.9", "98.0")  # low 97.9 reaches the stop 98.0
LONG_TICK_TOUCH: Ohlc = ("100.6", "100.8", "100.0", "100.4")  # low exactly the limit: touch only
SHORT_FILL_TRADE: Ohlc = ("99.9", "100.1", "99.7", "100.0")  # high = limit + tick
SHORT_STOP_MARK: Ohlc = ("99.0", "102.2", "98.9", "102.0")  # high 102.2 reaches the stop 102.0


# --------------------------------------------------------------------------- #
# the sixteen cases
# --------------------------------------------------------------------------- #


def signal_bar_touch_no_fill() -> dict[str, object]:
    """The signal bar's own range touches the limit and the stop; nothing happens on that bar.

    The 1h signal bar (09:00 to 09:59:59.999) has high 101.5 and low 97.5, so its range spans
    the limit 100.0 and the stop 98.0. The first 1m minute opens at 10:00. A trade-through on
    10:10 fills the plan, a mark minute at 10:11 stops it (D-01, F-120, F-602).
    """
    plan = _plan("BTCUSDT", signal_id="G14-SIGNAL-BAR-TOUCH")
    close = SIGNAL_CLOSE
    trade = _minute_rows(
        "BTCUSDT",
        "trade",
        first="10:00",
        count=60,
        base=LONG_FLAT,
        overrides={"10:10": LONG_FILL_TRADE, "10:11": ("100.2", "100.3", "97.9", "98.0")},
        not_before=close,
    )
    mark = _minute_rows(
        "BTCUSDT",
        "mark",
        first="10:00",
        count=60,
        base=LONG_FLAT,
        overrides={"10:10": LONG_FILL_MARK, "10:11": LONG_STOP_MARK},
        not_before=close,
    )
    bars = [
        _hour_bar("BTCUSDT", _clock("09:00"), ("100.5", "101.5", "97.5", "100.4")),
        _bar_from_trade_minutes("BTCUSDT", _clock("10:00"), trade),
    ]
    return _case(symbols=["BTCUSDT"], plans=[plan], trade=trade, mark=mark, strategy_bars=bars)


CASES: dict[str, Callable[[], dict[str, object]]] = {
    "signal_bar_touch_no_fill": signal_bar_touch_no_fill,
}


def render(payload: Mapping[str, object]) -> bytes:
    """Canonical bytes of one input: sorted keys, two-space indent, LF, trailing newline."""
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_all(out: Path, only: Sequence[str] | None = None) -> list[Path]:
    """Write `<out>/<case>/input.json` for every case (or `only`) and return the paths."""
    written: list[Path] = []
    for name, builder in CASES.items():
        if only is not None and name not in only:
            continue
        target = out / name / "input.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(render(builder()))
        written.append(target)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the Phase 14 golden case inputs.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output root directory")
    args = parser.parse_args(argv)
    written = write_all(args.out)
    print(f"Phase 14 golden inputs written: {len(written)} cases under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
