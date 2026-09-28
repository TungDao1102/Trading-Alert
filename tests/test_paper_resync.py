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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import tenacity

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: Any) -> None:
    """Bypass production retry sleeps (Group A option 1).

    The resync backfill path (7 attempts, exponential backoff) sleeps
    ~40-50s when the adapter raises a transient error. Unit tests must
    assert the per-symbol isolation logic without burning the
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
    # The dropped forming candle leaves a visible hole: the 11:00 slot
    # contributes no close, so exactly one forming_at_observed_time gap
    # is journaled (CR-09 — never silent coverage).
    assert len(gaps) == 1, f"forming slot must produce one gap, got {gaps}"
    assert gaps[0]["reason"] == "forming_at_observed_time"


# --------------------------------------------------------------------------- #
# Test 4 — rotation is treated as scheduled (no reconnect, no outage gap).
# --------------------------------------------------------------------------- #


def test_rotation_treated_as_scheduled_resubscribes_and_backfills() -> None:
    """Beh. 4: on_disconnect(scheduled=True) resubscribes + backfills.

    Per D-01: the 24h server-initiated rotation is scheduled, not an
    outage. The supervisor must resubscribe all pairs and backfill
    from the last-seen close per pair, but MUST NOT attempt a
    reconnect (the WS is still connected, just rotating) and MUST
    NOT journal an outage-class gap.
    """
    import asyncio

    from src.paper.supervisor import PaperSupervisor

    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter()
    dispatched: list[Any] = []
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)

    supervisor = PaperSupervisor(
        ws_adapter=ws,
        rest_adapter=rest,
        on_closed_candle=lambda k: dispatched.append(k),
        symbols=("BTCUSDT", "ETHUSDT"),
        intervals=("1h",),
        clock=lambda: now,
    )
    supervisor.start()
    # Simulate that we've seen closes for both pairs.
    supervisor.record_close("BTCUSDT", "1h", datetime(2026, 9, 19, 10, 0, tzinfo=UTC))
    supervisor.record_close("ETHUSDT", "1h", datetime(2026, 9, 19, 10, 0, tzinfo=UTC))

    # Reset call counters after start.
    initial_subscribe_count = len(ws.subscribe_calls)
    initial_reconnect_count = len(ws.reconnect_calls)
    initial_klines_count = len(rest.klines_calls)

    asyncio.run(supervisor.on_disconnect(scheduled=True))

    # No reconnect attempt (rotation is scheduled).
    assert len(ws.reconnect_calls) == initial_reconnect_count, (
        f"rotation must not trigger reconnect, got {len(ws.reconnect_calls)} calls"
    )
    # All pairs resubscribed (start was called again).
    assert len(ws.subscribe_calls) == initial_subscribe_count + 2, (
        f"expected 2 resubscribes, got {len(ws.subscribe_calls) - initial_subscribe_count}"
    )
    # Backfill called for each pair with the last-seen close.
    assert len(rest.klines_calls) == initial_klines_count + 2, (
        f"expected 2 backfill calls, got {len(rest.klines_calls) - initial_klines_count}"
    )
    for call in rest.klines_calls[initial_klines_count:]:
        assert call[2] == int(datetime(2026, 9, 19, 10, 0, tzinfo=UTC).timestamp() * 1000)


# --------------------------------------------------------------------------- #
# Test 5 — unsolicited disconnect triggers reconnect + resubscribe + backfill.
# --------------------------------------------------------------------------- #


def test_unsolicited_disconnect_reconnects_and_resyncs() -> None:
    """Beh. 5: on_disconnect(scheduled=False) reconnects + resyncs.

    Per D-01: an unsolicited drop is an outage. The supervisor must
    attempt a tenacity-bounded reconnect, resubscribe all pairs, and
    backfill from the last-seen close per pair.
    """
    import asyncio

    from src.paper.supervisor import PaperSupervisor

    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter()
    dispatched: list[Any] = []
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)

    supervisor = PaperSupervisor(
        ws_adapter=ws,
        rest_adapter=rest,
        on_closed_candle=lambda k: dispatched.append(k),
        symbols=("BTCUSDT", "ETHUSDT"),
        intervals=("1h",),
        clock=lambda: now,
    )
    supervisor.start()
    supervisor.record_close("BTCUSDT", "1h", datetime(2026, 9, 19, 10, 0, tzinfo=UTC))
    supervisor.record_close("ETHUSDT", "1h", datetime(2026, 9, 19, 10, 0, tzinfo=UTC))

    initial_reconnect_count = len(ws.reconnect_calls)
    initial_subscribe_count = len(ws.subscribe_calls)
    initial_klines_count = len(rest.klines_calls)

    asyncio.run(supervisor.on_disconnect(scheduled=False))

    # Reconnect attempted for each existing handle.
    assert len(ws.reconnect_calls) > initial_reconnect_count, (
        f"unsolicited drop must trigger reconnect, got {len(ws.reconnect_calls)} calls"
    )
    # All pairs resubscribed.
    assert len(ws.subscribe_calls) > initial_subscribe_count, (
        f"expected resubscribes after reconnect, got {len(ws.subscribe_calls)}"
    )
    # Backfill called for each pair.
    assert len(rest.klines_calls) == initial_klines_count + 2, (
        f"expected 2 backfill calls, got {len(rest.klines_calls) - initial_klines_count}"
    )


# --------------------------------------------------------------------------- #
# Test 6 — per-symbol isolation: one bad symbol does not block healthy ones.
# --------------------------------------------------------------------------- #


def test_one_bad_symbol_does_not_block_healthy_symbols() -> None:
    """Beh. 6: a failing pair journals its gap; healthy pairs still dispatch.

    Per D-01: per-symbol try-except isolation. If one symbol's backfill
    raises, the supervisor journals a gap for that symbol and continues
    with the remaining pairs. Healthy symbols' closes are still
    dispatched to the loop callback.
    """
    import asyncio

    from src.paper.supervisor import PaperSupervisor

    ws = _FakeWsAdapter()
    # Configure the REST adapter to raise for BTCUSDT but succeed for ETHUSDT.
    rest = _FakeRestAdapter(
        responses={
            ("BTCUSDT", "1h"): RuntimeError("adapter_error: simulated outage"),
            ("ETHUSDT", "1h"): [],
        }
    )
    dispatched: list[Any] = []
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)

    supervisor = PaperSupervisor(
        ws_adapter=ws,
        rest_adapter=rest,
        on_closed_candle=lambda k: dispatched.append(k),
        symbols=("BTCUSDT", "ETHUSDT"),
        intervals=("1h",),
        clock=lambda: now,
    )
    supervisor.start()
    supervisor.record_close("BTCUSDT", "1h", datetime(2026, 9, 19, 10, 0, tzinfo=UTC))
    supervisor.record_close("ETHUSDT", "1h", datetime(2026, 9, 19, 10, 0, tzinfo=UTC))

    # The supervisor must not raise even though BTCUSDT's backfill fails.
    asyncio.run(supervisor.on_disconnect(scheduled=True))

    # Both pairs were attempted (per-symbol isolation).
    btc_calls = [c for c in rest.klines_calls if c[0] == "BTCUSDT"]
    eth_calls = [c for c in rest.klines_calls if c[0] == "ETHUSDT"]
    assert len(btc_calls) >= 1, "BTCUSDT backfill must be attempted"
    assert len(eth_calls) >= 1, "ETHUSDT backfill must be attempted"


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


class _FakeWsAdapter:
    """Fake WS adapter for supervisor tests.

    Records subscribe/reconnect/close calls. Returns sentinel handles.
    """

    def __init__(self) -> None:
        self.subscribe_calls: list[tuple[str, str]] = []
        self.reconnect_calls: list[Any] = []
        self.close_calls: list[Any] = []

    def subscribe(
        self,
        *,
        symbol: str,
        interval: str,
        on_kline: Any,
        stream_id: str | None = None,
    ) -> Any:
        self.subscribe_calls.append((symbol, interval))
        return object()  # sentinel handle

    def reconnect(self, handle: Any) -> None:
        self.reconnect_calls.append(handle)

    def close(self, handle: Any) -> None:
        self.close_calls.append(handle)


class _FakeRestAdapter:
    """Fake REST adapter for supervisor tests.

    Configures per-(symbol, interval) responses. Each response is
    either a list of Klines or an Exception to raise.
    """

    def __init__(
        self,
        *,
        responses: dict[tuple[str, str], list[Any] | Exception] | None = None,
    ) -> None:
        self._responses = responses or {}
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
        key = (symbol, interval)
        if key in self._responses:
            response = self._responses[key]
            if isinstance(response, Exception):
                raise response
            return response
        return []
