"""Phase 7 paper-loop resync tests (plan 07-02, task 1).

Per D-01: the paper loop's resync module REST-backfills missed closes
after a disconnect or 24h rotation, and journals any holes the exchange
cannot fill as explicit gap records. The module NEVER synthesizes a
candle for a window the exchange did not return (flag-never-fabricate).

Three behaviors pinned here:
  1. Clean backfill: a FakeAdapter page containing the missed closes
     returns exactly those closes in order and emits zero gap records.
  2. Unrecoverable gap: a FakeAdapter page with a hole the exchange
     cannot fill returns the available closes and journals exactly one
     gap record with symbol, data_class paper-1h, expected_utc,
     observed_utc, and a non-empty reason.
  3. Forming-candle drop: a still-forming candle (close_time_utc after
     now_utc) in the REST page is dropped before any downstream use.

The test loads the golden fixture pair (input.json + expected.json)
from `tests/fixtures/phase7/reconnect_resync/` and
`tests/fixtures/phase7/unrecoverable_gap/`, feeds the sequence through
the resync entrypoint with an injected FakeAdapter, and asserts the
outcome matches the expected counts and gap-record shape.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _parse_utc(raw: str) -> datetime:
    """Parse an ISO-8601 string into a UTC-aware datetime."""
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


def _build_kline(symbol: str, interval: str, row: dict[str, Any]) -> Any:
    """Build a frozen Kline from a fixture row dict.

    Mirrors the adapter's `_row_to_kline` shape: open_time, open, high,
    low, close, volume, close_time, quote_volume, trade_count.
    """
    from src.adapters.binance_usdm import Kline

    open_ms = int(_parse_utc(row["open_time_utc"]).timestamp() * 1000)
    close_ms = int(_parse_utc(row["close_time_utc"]).timestamp() * 1000)
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        close_time_utc=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
        quote_volume=Decimal("0"),
        trade_count=0,
    )


class FakeAdapter:
    """Fake Binance adapter for resync tests.

    Records every `klines` call's `start_ms` argument and returns the
    pre-configured page of Klines. Tests inject this in place of the
    real adapter so unit tests never touch the network.
    """

    def __init__(self, *, page: list[Any] | None = None) -> None:
        self._page = list(page or [])
        self.klines_calls: list[tuple[str, str, int | None, int | None, int]] = []

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        self.klines_calls.append((symbol, interval, start_ms, end_ms, limit))
        return list(self._page)


# --------------------------------------------------------------------------- #
# Test 1 — clean backfill returns exactly the missed closes, zero gaps.
# --------------------------------------------------------------------------- #


def test_reconnect_resync_returns_missed_closes_with_zero_gaps() -> None:
    """Beh. 1: a complete page returns the missed closes in order.

    The fixture pins a 3-close hole (10:00 → 13:00) that the FakeAdapter
    fills completely. The resync module must return all 3 closes in
    close_time_utc order and emit zero gap records.
    """
    from src.paper.resync import backfill_missed_closes

    case_dir = PHASE7_FIXTURES_DIR / "reconnect_resync"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    symbol = case_input["symbol"]
    interval = case_input["interval"]
    last_close_utc = _parse_utc(case_input["last_close_utc"])
    now_utc = _parse_utc(case_input["now_utc"])

    page = [_build_kline(symbol, interval, r) for r in case_input["missed_closes"]]
    adapter = FakeAdapter(page=page)

    closes, gaps = _run(backfill_missed_closes, adapter, symbol, interval, last_close_utc, now_utc)

    assert len(closes) == expected["closes_count"], (
        f"expected {expected['closes_count']} closes, got {len(closes)}"
    )
    assert len(gaps) == expected["gaps_count"], (
        f"expected {expected['gaps_count']} gaps, got {len(gaps)}"
    )
    assert closes[0].close_time_utc == _parse_utc(expected["first_close_utc"])
    assert closes[-1].close_time_utc == _parse_utc(expected["last_close_utc"])

    # The adapter must have been called with start_ms = ms(last_close_utc).
    assert len(adapter.klines_calls) == 1
    call = adapter.klines_calls[0]
    assert call[0] == symbol
    assert call[1] == interval
    assert call[2] == int(last_close_utc.timestamp() * 1000)
    assert call[4] == 1500  # limit


# --------------------------------------------------------------------------- #
# Test 2 — unrecoverable gap journals exactly one gap record.
# --------------------------------------------------------------------------- #


def test_unrecoverable_gap_journals_exactly_one_gap_record() -> None:
    """Beh. 2: a hole the exchange cannot fill becomes one gap record.

    The fixture pins a 3-close hole (10:00 → 13:00) where the
    FakeAdapter returns only 2 closes (11:00 and 13:00), missing the
    12:00 close. The resync module must return the 2 available closes
    and journal exactly one gap record with the canonical CollectorGap
    field shape.
    """
    from src.paper.resync import backfill_missed_closes

    case_dir = PHASE7_FIXTURES_DIR / "unrecoverable_gap"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    symbol = case_input["symbol"]
    interval = case_input["interval"]
    last_close_utc = _parse_utc(case_input["last_close_utc"])
    now_utc = _parse_utc(case_input["now_utc"])

    page = [_build_kline(symbol, interval, r) for r in case_input["missed_closes"]]
    adapter = FakeAdapter(page=page)

    closes, gaps = _run(backfill_missed_closes, adapter, symbol, interval, last_close_utc, now_utc)

    assert len(closes) == expected["closes_count"], (
        f"expected {expected['closes_count']} closes, got {len(closes)}"
    )
    assert len(gaps) == expected["gaps_count"], (
        f"expected {expected['gaps_count']} gaps, got {len(gaps)}"
    )

    gap = gaps[0]
    expected_gap = expected["gap"]
    assert gap["symbol"] == expected_gap["symbol"]
    assert gap["data_class"] == expected_gap["data_class"]
    assert gap["expected_utc"] == _parse_utc(expected_gap["expected_utc"])
    assert gap["observed_utc"] == _parse_utc(expected_gap["observed_utc"])
    assert gap["reason"] == expected_gap["reason"]
    assert gap["reason"] != "", "gap reason must be non-empty"


# --------------------------------------------------------------------------- #
# Test 3 — forming candle (close_time_utc > now_utc) is dropped.
# --------------------------------------------------------------------------- #


def test_forming_candle_in_page_is_dropped_before_use() -> None:
    """Beh. 3: a still-forming candle in the REST page is dropped.

    The FakeAdapter returns 2 closes: one closed (close_time_utc <=
    now_utc) and one forming (close_time_utc > now_utc). The resync
    module must drop the forming candle and return only the closed one.
    """
    from src.paper.resync import backfill_missed_closes

    symbol = "BTCUSDT"
    interval = "1h"
    last_close_utc = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    now_utc = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

    closed_open = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    closed_close = datetime(2026, 9, 19, 11, 0, tzinfo=UTC)
    forming_open = datetime(2026, 9, 19, 11, 0, tzinfo=UTC)
    forming_close = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)  # == now_utc, NOT after

    # Make the second candle strictly forming: close_time > now_utc.
    forming_close = now_utc + timedelta(seconds=1)

    closed_kline = _build_kline(
        symbol,
        interval,
        {
            "open_time_utc": closed_open.isoformat(),
            "close_time_utc": closed_close.isoformat(),
            "open": "100.00",
            "high": "100.10",
            "low": "99.95",
            "close": "100.05",
            "volume": "1.0",
        },
    )
    forming_kline = _build_kline(
        symbol,
        interval,
        {
            "open_time_utc": forming_open.isoformat(),
            "close_time_utc": forming_close.isoformat(),
            "open": "100.05",
            "high": "100.15",
            "low": "100.00",
            "close": "100.10",
            "volume": "1.0",
        },
    )
    adapter = FakeAdapter(page=[closed_kline, forming_kline])

    closes, gaps = _run(
        backfill_missed_closes, adapter, symbol, interval, last_close_utc, now_utc
    )

    # Only the closed candle survives; the forming one is dropped.
    assert len(closes) == 1, f"expected 1 close (forming dropped), got {len(closes)}"
    assert closes[0].close_time_utc == closed_close
    # No gap for the dropped forming candle — it was never expected to
    # be closed at now_utc.
    assert len(gaps) == 0, f"forming candle must not produce a gap, got {gaps}"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _run(func: Any, adapter: Any, symbol: str, interval: str,
         last_close_utc: datetime, now_utc: datetime) -> tuple[list[Any], list[dict[str, Any]]]:
    """Run an async resync function synchronously via asyncio.run."""
    import asyncio

    async def _call() -> tuple[list[Any], list[dict[str, Any]]]:
        return await func(
            adapter,
            symbol=symbol,
            interval=interval,
            last_close_utc=last_close_utc,
            now_utc=now_utc,
        )

    return asyncio.run(_call())
