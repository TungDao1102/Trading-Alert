"""Paper-loop resync tests (Phase 7 plan 07-02 task 1, extended in Phase 16 plan 16-08).

Per D-01 (flag-never-fabricate): the resync module REST-backfills missed closes and reports any
hole the exchange cannot fill as an explicit `GapRecord`. The module NEVER synthesizes a candle
for a window the exchange did not return.

Phase 16 (plan 16-08, research Pitfall P1): real Binance rows close at open + interval - 1 ms,
so a backfill that anchored its expected slots on `last_close_utc` itself reported one phantom
gap per returned bar. Every test below builds rows with the real shape; the Phase 7 golden
fixtures (`tests/fixtures/phase7/reconnect_resync`, `unrecoverable_gap`) were re-shaped to match.
No network is touched.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import tenacity
from src.adapters.binance_public import Kline, _row_to_kline
from src.paper.resync import backfill_missed_closes, expected_close_times
from src.paper.vocabulary import GapReason, GapRecord, SourceTag, TaggedBar

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Live GET /fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2, 2026-10-07 (research
# "Real-shaped fixture rows for backfill tests"; prices are exchange data).
ROW0 = [
    1791360000000,
    "84094.70",
    "84139.20",
    "83902.50",
    "83909.90",
    "5844.590",
    1791363599999,
    "490868445.00560",
    179437,
    "2473.352",
    "207729461.40190",
    "0",
]
ROW1 = [
    1791363600000,
    "83909.90",
    "83965.50",
    "83603.00",
    "83749.00",
    "7821.908",
    1791367199999,
    "655296503.76730",
    125134,
    "3519.234",
    "294835835.39980",
    "0",
]


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: Any) -> None:
    """Bypass production retry sleeps (Group A option 1).

    The resync backfill path (7 attempts, exponential backoff) sleeps ~40-50s when the adapter
    raises a transient error. Unit tests must assert the isolation logic without burning the
    production sleep budget.
    """
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )


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


def _ms(value: datetime) -> int:
    """Exact integer milliseconds since the epoch (never a float round trip)."""
    delta = value - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _build_kline(symbol: str, interval: str, row: dict[str, Any]) -> Kline:
    """Build a frozen Kline from a fixture row dict."""
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_parse_utc(row["open_time_utc"]),
        close_time_utc=_parse_utc(row["close_time_utc"]),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
        quote_volume=Decimal("0"),
        trade_count=0,
    )


class FakeAdapter:
    """Fake public-data adapter for resync tests.

    Records every `klines` call's `start_ms` argument and returns the pre-configured page.
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


def _run(
    adapter: Any, symbol: str, interval: str, last_close_utc: datetime, now_utc: datetime
) -> tuple[list[TaggedBar], list[GapRecord]]:
    """Run the async resync entry point synchronously."""

    async def _call() -> tuple[list[TaggedBar], list[GapRecord]]:
        return await backfill_missed_closes(
            adapter,
            symbol=symbol,
            interval=interval,
            last_close_utc=last_close_utc,
            now_utc=now_utc,
        )

    return asyncio.run(_call())


# --------------------------------------------------------------------------- #
# Golden fixtures (re-shaped to the real close = open + interval - 1 ms).
# --------------------------------------------------------------------------- #


def test_reconnect_resync_returns_missed_closes_with_zero_gaps() -> None:
    """A complete page returns the missed closes in order and no gap."""
    case_dir = PHASE7_FIXTURES_DIR / "reconnect_resync"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    symbol = case_input["symbol"]
    interval = case_input["interval"]
    last_close_utc = _parse_utc(case_input["last_close_utc"])
    now_utc = _parse_utc(case_input["now_utc"])

    page = [_build_kline(symbol, interval, r) for r in case_input["missed_closes"]]
    adapter = FakeAdapter(page=page)

    closes, gaps = _run(adapter, symbol, interval, last_close_utc, now_utc)

    assert len(gaps) == expected["gaps_count"], f"expected no gap, got {gaps}"
    assert len(closes) == expected["closes_count"]
    assert closes[0].close_time_utc == _parse_utc(expected["first_close_utc"])
    assert closes[-1].close_time_utc == _parse_utc(expected["last_close_utc"])

    # The adapter is called with start_ms = ms(last_close_utc).
    assert len(adapter.klines_calls) == 1
    call = adapter.klines_calls[0]
    assert call[0] == symbol
    assert call[1] == interval
    assert call[2] == _ms(last_close_utc)
    assert call[4] == 1500  # limit


def test_unrecoverable_gap_yields_exactly_one_gap_record() -> None:
    """A hole the exchange cannot fill becomes one typed GapRecord."""
    case_dir = PHASE7_FIXTURES_DIR / "unrecoverable_gap"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    symbol = case_input["symbol"]
    interval = case_input["interval"]
    last_close_utc = _parse_utc(case_input["last_close_utc"])
    now_utc = _parse_utc(case_input["now_utc"])

    page = [_build_kline(symbol, interval, r) for r in case_input["missed_closes"]]
    closes, gaps = _run(FakeAdapter(page=page), symbol, interval, last_close_utc, now_utc)

    assert len(closes) == expected["closes_count"]
    assert len(gaps) == expected["gaps_count"]
    gap = gaps[0]
    expected_gap = expected["gap"]
    assert isinstance(gap, GapRecord)
    assert gap.symbol == expected_gap["symbol"]
    assert gap.interval == expected_gap["interval"]
    assert gap.expected_close_utc == _parse_utc(expected_gap["expected_close_utc"])
    assert gap.detected_at_utc == _parse_utc(expected_gap["detected_at_utc"])
    assert gap.reason is GapReason[expected_gap["reason"]]


# --------------------------------------------------------------------------- #
# Plan 16-08 Task 2, Test 1: real-shaped rows produce no phantom gap (Pitfall P1).
# --------------------------------------------------------------------------- #


def test_real_shaped_rows_produce_the_closes_and_zero_gaps() -> None:
    """Two live rows (close = open + interval - 1 ms) return both closes and no gap.

    The pre-fix code returned one phantom `exchange_returned_no_candle_for_expected_close`
    gap per returned bar here, because its expected slots started AT `last_close_utc`.
    """
    page = [_row_to_kline("BTCUSDT", "1h", ROW0), _row_to_kline("BTCUSDT", "1h", ROW1)]
    last_close_utc = datetime(2026, 10, 7, 7, 59, 59, 999000, tzinfo=UTC)
    now_utc = datetime(2026, 10, 7, 10, 0, 5, tzinfo=UTC)

    closes, gaps = _run(FakeAdapter(page=page), "BTCUSDT", "1h", last_close_utc, now_utc)

    assert gaps == [], f"phantom gaps for real-shaped rows: {gaps}"
    assert [bar.close_time_utc for bar in closes] == [
        datetime(2026, 10, 7, 8, 59, 59, 999000, tzinfo=UTC),
        datetime(2026, 10, 7, 9, 59, 59, 999000, tzinfo=UTC),
    ]
    assert closes[0].open == Decimal("84094.70")
    assert closes[1].close == Decimal("83749.00")


# --------------------------------------------------------------------------- #
# Test 2: a genuinely missing bar yields exactly one GapRecord.
# --------------------------------------------------------------------------- #


def test_a_missing_bar_between_two_returned_bars_is_one_exchange_no_candle_gap() -> None:
    row_after_gap = list(ROW1)
    row_after_gap[0] = ROW1[0] + 3_600_000  # slot 2 opens, slot 1 is missing
    row_after_gap[6] = ROW1[6] + 3_600_000
    page = [_row_to_kline("BTCUSDT", "1h", ROW0), _row_to_kline("BTCUSDT", "1h", row_after_gap)]
    last_close_utc = datetime(2026, 10, 7, 7, 59, 59, 999000, tzinfo=UTC)
    now_utc = datetime(2026, 10, 7, 11, 0, 5, tzinfo=UTC)

    closes, gaps = _run(FakeAdapter(page=page), "BTCUSDT", "1h", last_close_utc, now_utc)

    assert len(closes) == 2
    assert gaps == [
        GapRecord(
            symbol="BTCUSDT",
            interval="1h",
            expected_close_utc=datetime(2026, 10, 7, 9, 59, 59, 999000, tzinfo=UTC),
            reason=GapReason.EXCHANGE_NO_CANDLE,
            detected_at_utc=now_utc,
        )
    ]


# --------------------------------------------------------------------------- #
# Test 3: every returned bar is a REST_BACKFILL TaggedBar with the request's interval.
# --------------------------------------------------------------------------- #


def test_returned_bars_are_rest_backfill_tagged_with_the_request_interval() -> None:
    four_hours_ms = 14_400_000
    first_open = 1_791_360_000_000  # 08:00 UTC, on the 4h grid
    rows = [
        [
            first_open + i * four_hours_ms,
            "100.00",
            "100.10",
            "99.95",
            "100.05",
            "1.0",
            first_open + (i + 1) * four_hours_ms - 1,
            "0",
            0,
            "0",
            "0",
            "0",
        ]
        for i in range(2)
    ]
    page = [_row_to_kline("BTCUSDT", "4h", row) for row in rows]
    last_close_utc = datetime(2026, 10, 7, 7, 59, 59, 999000, tzinfo=UTC)
    now_utc = datetime(2026, 10, 7, 16, 0, 1, tzinfo=UTC)

    closes, gaps = _run(FakeAdapter(page=page), "BTCUSDT", "4h", last_close_utc, now_utc)

    assert gaps == []
    assert len(closes) == 2
    for bar in closes:
        assert isinstance(bar, TaggedBar)
        assert bar.source is SourceTag.REST_BACKFILL
        assert bar.interval == "4h"
        assert bar.symbol == "BTCUSDT"


# --------------------------------------------------------------------------- #
# Test 4: a forming last row is dropped, as before.
# --------------------------------------------------------------------------- #


def test_forming_last_row_is_dropped_before_use() -> None:
    page = [_row_to_kline("BTCUSDT", "1h", ROW0), _row_to_kline("BTCUSDT", "1h", ROW1)]
    last_close_utc = datetime(2026, 10, 7, 7, 59, 59, 999000, tzinfo=UTC)
    # 09:30: the 09:00 bar is still forming (closes at 09:59:59.999).
    now_utc = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)

    closes, gaps = _run(FakeAdapter(page=page), "BTCUSDT", "1h", last_close_utc, now_utc)

    assert [bar.close_time_utc for bar in closes] == [
        datetime(2026, 10, 7, 8, 59, 59, 999000, tzinfo=UTC)
    ]
    assert gaps == [], "a bar that has not closed yet is not an expected close"


def test_an_inconsistent_forming_row_for_a_due_slot_is_an_unknown_gap() -> None:
    """CR-09: a due slot whose only row is not closed leaves a visible hole, never silence."""
    anomalous = list(ROW0)
    anomalous[6] = ROW0[0] + 3_600_000  # close time one ms late: not closed at 08:59:59.999
    page = [_row_to_kline("BTCUSDT", "1h", anomalous)]
    last_close_utc = datetime(2026, 10, 7, 7, 59, 59, 999000, tzinfo=UTC)
    now_utc = datetime(2026, 10, 7, 8, 59, 59, 999000, tzinfo=UTC)

    closes, gaps = _run(FakeAdapter(page=page), "BTCUSDT", "1h", last_close_utc, now_utc)

    assert closes == []
    assert [(gap.expected_close_utc, gap.reason) for gap in gaps] == [
        (datetime(2026, 10, 7, 8, 59, 59, 999000, tzinfo=UTC), GapReason.UNKNOWN)
    ]


# --------------------------------------------------------------------------- #
# The expected-close grid.
# --------------------------------------------------------------------------- #


def test_expected_close_times_follow_the_exchange_grid() -> None:
    last_close_utc = datetime(2026, 10, 7, 7, 59, 59, 999000, tzinfo=UTC)

    due = expected_close_times(last_close_utc, datetime(2026, 10, 7, 10, 0, 5, tzinfo=UTC), "1h")

    assert due == [
        datetime(2026, 10, 7, 8, 59, 59, 999000, tzinfo=UTC),
        datetime(2026, 10, 7, 9, 59, 59, 999000, tzinfo=UTC),
    ]
    assert expected_close_times(last_close_utc, last_close_utc + timedelta(minutes=59), "1h") == []


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="UTC-aware"):
        _run(
            FakeAdapter(),
            "BTCUSDT",
            "1h",
            datetime(2026, 10, 7, 8, 0),
            datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
        )
