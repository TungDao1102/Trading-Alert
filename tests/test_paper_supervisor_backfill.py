"""Paper supervisor on the real adapter shape (Phase 16, plan 16-08, D-05 / D-06 / D-08).

History: the Phase 7 supervisor tests (REVIEW CR-02 / CR-03, plan 13-03) ran against a fictional
synchronous WS adapter (`subscribe` returned a sentinel, `reconnect(handle)` and `close(handle)`
existed). The installed SDK has none of that: every call is a coroutine, a stream handle exposes
only `on` and `unsubscribe`, and the SDK owns rotation. These tests drive the real
`PaperWsAdapter` over the SDK-shaped fake client of `tests/paper_ws_fakes.py` (bound to the
installed SDK by `tests/test_paper_ws_contract.py`), with a REST fake that serves rows shaped like
the live Binance rows (close = open + interval - 1 ms).

No network is touched.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import tenacity
from src.adapters.binance_public import Kline
from src.adapters.paper_ws import PaperWsAdapter
from src.paper.supervisor import PaperSupervisor
from src.paper.vocabulary import (
    GapRecord,
    SourceTag,
    TaggedBar,
)
from structlog.testing import capture_logs

from tests.paper_ws_fakes import FakeSdkWsClient, fresh_sdk_stream_map, make_kline_model

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_HOUR_MS = 3_600_000
# Open time of the first live row recorded on 2026-10-07 (research "Real-shaped fixture rows").
_ROW0_OPEN_MS = 1_791_360_000_000


def _dt(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def _ms(value: datetime) -> int:
    delta = value - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _open_ms(slot: int) -> int:
    """Open time of the hourly slot `slot` (slot 0 is the first live row)."""
    return _ROW0_OPEN_MS + slot * _HOUR_MS


def _close_dt(slot: int) -> datetime:
    """Close time of slot `slot`, shaped like Binance: open + interval - 1 ms."""
    return _dt(_open_ms(slot) + _HOUR_MS - 1)


@pytest.fixture(autouse=True)
def _isolated_sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the SDK module-global stream map per test (research D7)."""
    return fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass production retry sleeps so the fail-closed logic runs without the sleep budget."""
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )


def _rest_bar(symbol: str, interval: str, slot: int) -> Kline:
    open_ms = _open_ms(slot)
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_dt(open_ms),
        close_time_utc=_dt(open_ms + _HOUR_MS - 1),
        open=Decimal("100.00"),
        high=Decimal("100.10"),
        low=Decimal("99.95"),
        close=Decimal("100.05"),
        volume=Decimal("1.0"),
        quote_volume=Decimal("0"),
        trade_count=0,
    )


class _FakeRest:
    """REST fake serving rows like the exchange: rows with open time >= `start_ms`."""

    def __init__(
        self,
        pages: dict[tuple[str, str], list[Kline] | Exception] | None = None,
        *,
        ignore_start: bool = False,
    ) -> None:
        self.pages = pages or {}
        self.ignore_start = ignore_start
        self.klines_calls: list[tuple[str, str, int | None]] = []

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.klines_calls.append((symbol, interval, start_ms))
        response = self.pages.get((symbol, interval), [])
        if isinstance(response, Exception):
            raise response
        if self.ignore_start or start_ms is None:
            return list(response)
        return [row for row in response if _ms(row.open_time_utc) >= start_ms]


@dataclass
class _Rig:
    supervisor: PaperSupervisor
    adapter: PaperWsAdapter
    clients: list[FakeSdkWsClient]
    rest: _FakeRest
    live: list[TaggedBar] = field(default_factory=list)
    backfilled: list[TaggedBar] = field(default_factory=list)
    gaps: list[GapRecord] = field(default_factory=list)
    events: list[tuple[str, datetime]] = field(default_factory=list)
    order: list[tuple[str, datetime]] = field(default_factory=list)

    @property
    def fake(self) -> FakeSdkWsClient:
        return self.clients[0]


def _make_rig(
    *,
    rest: _FakeRest | None = None,
    symbols: tuple[str, ...] = ("BTCUSDT",),
    intervals: tuple[str, ...] = ("1h",),
    now: datetime | None = None,
    factory_error: Exception | None = None,
) -> _Rig:
    """Build a supervisor over the real adapter and an SDK-shaped fake client.

    `clients` collects every fake client the adapter builds (the first is injected, later ones
    come from `rebuild`). `factory_error` makes every rebuild attempt fail.
    """
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = [first]

    def _factory(_configuration: Any) -> Any:
        if factory_error is not None:
            raise factory_error
        client = FakeSdkWsClient()
        clients.append(client)
        return client

    adapter = PaperWsAdapter(ws_client=first, client_factory=_factory)  # type: ignore[arg-type]
    fake_rest = rest if rest is not None else _FakeRest()
    live: list[TaggedBar] = []
    backfilled: list[TaggedBar] = []
    gaps: list[GapRecord] = []
    events: list[tuple[str, datetime]] = []
    order: list[tuple[str, datetime]] = []
    clock_now = now if now is not None else _close_dt(6) + timedelta(seconds=2)

    def _on_live(bar: TaggedBar) -> None:
        live.append(bar)
        order.append(("live", bar.close_time_utc))

    def _on_backfill(bar: TaggedBar) -> None:
        backfilled.append(bar)
        order.append(("backfill", bar.close_time_utc))

    supervisor = PaperSupervisor(
        ws_adapter=adapter,  # type: ignore[arg-type]
        rest_adapter=fake_rest,  # type: ignore[arg-type]
        symbols=symbols,
        intervals=intervals,
        on_closed_bar=_on_live,
        on_backfill=_on_backfill,
        on_gap=gaps.append,
        on_connection_event=lambda event, at: events.append((str(event), at)),
        clock=lambda: clock_now,
    )
    return _Rig(
        supervisor=supervisor,
        adapter=adapter,
        clients=clients,
        rest=fake_rest,
        live=live,
        backfilled=backfilled,
        gaps=gaps,
        events=events,
        order=order,
    )


def _emit(
    rig: _Rig,
    symbol: str,
    interval: str,
    slot: int,
    *,
    is_closed: bool = True,
    client_index: int = 0,
) -> None:
    """Deliver one SDK kline model through the stream handle of (symbol, interval)."""
    stream = f"{symbol.lower()}@kline_{interval}"
    client = rig.clients[client_index]
    handle = next(h for h in reversed(client.handles) if h._stream == stream)
    handle._emit(
        make_kline_model(
            symbol=symbol,
            interval=interval,
            open_time_ms=_open_ms(slot),
            close_time_ms=_open_ms(slot) + _HOUR_MS - 1,
            is_closed=is_closed,
        )
    )


# --------------------------------------------------------------------------- #
# Task 1 (tracer): awaited start, closed bars only, LIVE_WS tag.
# --------------------------------------------------------------------------- #


async def test_start_connects_once_and_subscribes_every_symbol_interval_pair() -> None:
    rig = _make_rig(symbols=("BTCUSDT", "ETHUSDT"), intervals=("1h", "4h"))

    await rig.supervisor.start()

    assert rig.fake.create_connection_calls == 1
    assert [call[0] for call in rig.fake.kline_calls] == [
        "btcusdt",
        "btcusdt",
        "ethusdt",
        "ethusdt",
    ]
    assert [call[1] for call in rig.fake.kline_calls] == ["1h", "4h", "1h", "4h"]
    with pytest.raises(RuntimeError, match="called twice"):
        await rig.supervisor.start()
    assert rig.fake.create_connection_calls == 1, "a rejected second start touches nothing"


def test_symbols_and_intervals_are_required_explicitly() -> None:
    """There is no Live-5 default: the composition root names the symbols and intervals."""
    with pytest.raises(TypeError):
        PaperSupervisor(  # type: ignore[call-arg]
            ws_adapter=object(),  # type: ignore[arg-type]
            rest_adapter=object(),  # type: ignore[arg-type]
            on_closed_bar=lambda _bar: None,
            on_backfill=lambda _bar: None,
            on_gap=lambda _gap: None,
            on_connection_event=lambda _event, _at: None,
        )


async def test_closed_kline_reaches_the_sink_once_as_a_live_ws_tagged_bar() -> None:
    rig = _make_rig()
    await rig.supervisor.start()

    _emit(rig, "BTCUSDT", "1h", 0)

    assert len(rig.live) == 1
    bar = rig.live[0]
    assert isinstance(bar, TaggedBar)
    assert bar.source is SourceTag.LIVE_WS
    assert bar.symbol == "BTCUSDT"
    assert bar.interval == "1h"
    assert bar.open_time_utc == _dt(_open_ms(0))
    assert bar.close_time_utc == _close_dt(0)
    assert bar.open == Decimal("84094.70")
    assert bar.high == Decimal("84139.20")
    assert bar.low == Decimal("83902.50")
    assert bar.close == Decimal("83909.90")
    assert bar.volume == Decimal("5844.590")
    assert rig.backfilled == []


async def test_forming_kline_never_reaches_the_sink_nor_moves_the_cursor() -> None:
    rig = _make_rig()
    await rig.supervisor.start()

    _emit(rig, "BTCUSDT", "1h", 0, is_closed=False)

    assert rig.live == []
    assert rig.supervisor._last_close == {}


async def test_duplicate_closed_kline_is_dropped_with_the_existing_warning() -> None:
    rig = _make_rig()
    await rig.supervisor.start()
    _emit(rig, "BTCUSDT", "1h", 0)

    with capture_logs() as captured:
        _emit(rig, "BTCUSDT", "1h", 0)

    assert len(rig.live) == 1
    assert any(entry["event"] == "paper.supervisor.duplicate_close_dropped" for entry in captured)


async def test_older_closed_kline_than_the_last_close_is_dropped() -> None:
    rig = _make_rig()
    await rig.supervisor.start()
    _emit(rig, "BTCUSDT", "1h", 2)

    _emit(rig, "BTCUSDT", "1h", 1)

    assert [bar.close_time_utc for bar in rig.live] == [_close_dt(2)]


async def test_start_failure_rolls_back_and_allows_a_retry() -> None:
    """IN-03: a partial subscribe failure unsubscribes the created handles so start() can retry."""

    class _FlakyClient(FakeSdkWsClient):
        fail_on_call = 2

        async def kline_candlestick_streams(
            self, symbol: str | None, interval: Any, id: str | None = None
        ) -> Any:
            if len(self.kline_calls) + 1 == self.fail_on_call:
                self.fail_on_call = -1
                raise RuntimeError("subscribe down")
            return await super().kline_candlestick_streams(symbol, interval, id)

    rig = _make_rig(symbols=("BTCUSDT", "ETHUSDT"))
    flaky = _FlakyClient()
    rig.clients[0] = flaky
    rig.adapter._ws = flaky  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="subscribe down"):
        await rig.supervisor.start()

    assert flaky.handles[0]._unsubscribed == 1, "the created handle is unsubscribed"
    assert flaky.close_calls == 1, "the connection opened by the failed start is closed"
    assert rig.supervisor._handles == []

    await rig.supervisor.start()  # a retry must not raise "called twice"
    assert len(rig.supervisor._handles) == 2


# --------------------------------------------------------------------------- #
# Kept from Phase 7 (D-28, T-13-10): the last-close cursor is monotonic and atomic.
# --------------------------------------------------------------------------- #


async def test_record_close_never_moves_backwards() -> None:
    rig = _make_rig()

    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(2))
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(1))

    assert rig.supervisor._last_close[("BTCUSDT", "1h")] == _close_dt(2)


async def test_advance_last_close_is_atomic_under_threads() -> None:
    """32 concurrent claims of the same bar produce exactly one True."""
    rig = _make_rig()
    barrier = threading.Barrier(32)
    results: list[bool] = []
    results_lock = threading.Lock()

    def _claim() -> None:
        barrier.wait()
        won = rig.supervisor._advance_last_close("BTCUSDT", "1h", _close_dt(5))
        with results_lock:
            results.append(won)

    threads = [threading.Thread(target=_claim) for _ in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 32
    assert results.count(True) == 1
    assert rig.supervisor._last_close[("BTCUSDT", "1h")] == _close_dt(5)
