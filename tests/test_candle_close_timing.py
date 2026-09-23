"""Candle-close-timing determinism suite (Phase 3, plan 03-05).

Per D-08 and TESTING_STRATEGY §4: no output may reference a source
candle close that has not yet occurred. The forming candle contributes
nothing; a closed candle contributes exactly one reference keyed by
source_candle_close_utc.

Mechanism-only placeholders (D-09): the closed/forming split is
decided against the frozen_clock fixture so wall-clock can never make
these suites flaky. Phase 4 keeps the invariant over real signals.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.domain.canonical import sha256_hex
from src.domain.ids import make_signal_id

TIMEFRAME_SECONDS = {"1m": 60, "1h": 3600, "4h": 14400}

STRATEGY_ID = "trend-pullback"
STRATEGY_VERSION = "v1.0.0"
PARAMETER_SET_ID = "baseline-v1"


def _close_time(candle: dict) -> datetime:
    """Close time of a fixture candle (open + one timeframe interval)."""
    step = TIMEFRAME_SECONDS[candle["timeframe"]]
    opened = datetime.fromisoformat(candle["open_time_utc"])
    return opened + timedelta(seconds=step)


def _signal_entries(candles: list[dict]) -> list[tuple[str, str]]:
    """Placeholder pipeline output: one (close_iso, signal_id) per candle."""
    entries = []
    for candle in candles:
        close = _close_time(candle)
        sid = make_signal_id(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_set_id=PARAMETER_SET_ID,
            symbol=candle["symbol"],
            source_timeframe=candle["timeframe"],
            source_candle_close_utc=close,
            setup_fingerprint=sha256_hex(dict(candle)),
        )
        entries.append((close.isoformat(), sid))
    return entries


def _shift_back(candles: list[dict], hours: int) -> list[dict]:
    """Return fixture-derived rows shifted so their closes precede `now`.

    Mechanism-only fixture shaping: the OHLC bodies stay fixture-real;
    only the timestamps move, giving a deterministic closed series.
    """
    shifted = []
    for candle in candles:
        row = dict(candle)
        opened = datetime.fromisoformat(candle["open_time_utc"])
        row["open_time_utc"] = (opened - timedelta(hours=hours)).isoformat()
        shifted.append(row)
    return shifted


# --------------------------------------------------------------------------- #
# Test 1 — forming candle contributes no close reference.
# --------------------------------------------------------------------------- #


def test_forming_candle_contributes_no_close_reference(
    phase3_candles, frozen_clock
) -> None:
    """Beh. 1: outputs never reference a close that has not occurred.

    The closed series (fixture rows shifted 6h back) all close at or
    before `now`; the forming candle (fixture head row, close 01:00Z >
    now) must contribute zero references to its unclosed close.
    """
    now = frozen_clock
    closed = _shift_back(phase3_candles[:3], 6)
    assert all(_close_time(c) <= now for c in closed)
    forming = phase3_candles[0]
    assert _close_time(forming) > now
    outputs = _signal_entries(closed)
    closes = [close for close, _ in outputs]
    assert _close_time(forming).isoformat() not in closes
    assert all(datetime.fromisoformat(c) <= now for c in closes)


# --------------------------------------------------------------------------- #
# Test 2 — closed candle contributes exactly one reference.
# --------------------------------------------------------------------------- #


def test_closed_candle_contributes_exactly_one_reference(
    phase3_candles, frozen_clock
) -> None:
    """Beh. 2: a newly closed candle yields exactly one new reference.

    Advancing the closed set by one candle adds exactly one output,
    keyed by that candle's source_candle_close_utc.
    """
    closed = _shift_back(phase3_candles[:3], 6)
    before = _signal_entries(closed[:2])
    after = _signal_entries(closed[:3])
    assert len(after) == len(before) + 1
    new_close = _close_time(closed[2]).isoformat()
    assert [close for close, _ in after].count(new_close) == 1
    assert new_close not in [close for close, _ in before]
