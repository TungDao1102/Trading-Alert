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

import ast
import asyncio
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import tenacity
from src.adapters.binance_public import Kline
from src.adapters.paper_ws import PaperWsAdapter
from src.paper.supervisor import PaperSupervisor
from src.paper.vocabulary import (
    GapReason,
    GapRecord,
    RuntimeEventType,
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
    live_sink_error: Exception | None = None,
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
        if live_sink_error is not None:
            raise live_sink_error
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


# --------------------------------------------------------------------------- #
# Task 3: SDK connection events, one rotation owner, backfill and gap sinks.
# --------------------------------------------------------------------------- #

_NOW3 = _close_dt(3) + timedelta(seconds=2)


def _fire(rig: _Rig, event: str, *, client_index: int = 0) -> None:
    """Fire an SDK connection event on a fake client (the SDK runs these on the loop thread)."""
    client = rig.clients[client_index]
    for callback in list(client.connection_callbacks[event]):
        callback()


def _pages(*slots: int, symbol: str = "BTCUSDT", interval: str = "1h") -> _FakeRest:
    return _FakeRest({(symbol, interval): [_rest_bar(symbol, interval, slot) for slot in slots]})


def _gap(slot: int, reason: GapReason, *, at: datetime = _NOW3, symbol: str = "BTCUSDT") -> Any:
    return GapRecord(
        symbol=symbol,
        interval="1h",
        expected_close_utc=_close_dt(slot),
        reason=reason,
        detected_at_utc=at,
    )


async def test_reconnect_event_backfills_from_the_last_close_into_the_sinks() -> None:
    """The SDK rotation arrives as a 'reconnect' event: REST verification, nothing only logged."""
    rig = _make_rig(rest=_pages(1, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    _fire(rig, "reconnect")
    await rig.supervisor.wait_idle()

    assert rig.rest.klines_calls == [("BTCUSDT", "1h", _ms(_close_dt(0)))]
    assert [bar.close_time_utc for bar in rig.backfilled] == [_close_dt(1), _close_dt(3)]
    assert all(bar.source is SourceTag.REST_BACKFILL for bar in rig.backfilled)
    assert all(bar.interval == "1h" for bar in rig.backfilled)
    assert rig.gaps == [_gap(2, GapReason.WS_RECONNECT_WINDOW)]
    assert rig.live == []
    assert rig.events == [(str(RuntimeEventType.WS_RECONNECT), _NOW3)]


async def test_open_event_triggers_the_same_verification_without_a_reconnect_record() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    _fire(rig, "open")
    await rig.supervisor.wait_idle()

    assert len(rig.rest.klines_calls) == 1
    assert [bar.close_time_utc for bar in rig.backfilled] == [_close_dt(i) for i in (1, 2, 3)]
    assert rig.gaps == []
    assert rig.events == [], "an open event with no preceding drop is not a reconnect"


async def test_unsolicited_close_rebuilds_then_backfills_and_records_both_events() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    rig.fake.simulate_unsolicited_close()
    await rig.supervisor.wait_idle()

    assert len(rig.clients) == 2, "rebuild builds a fresh SDK client"
    assert rig.adapter.last_rebuild is not None
    assert rig.adapter.last_rebuild.stale_stream_names_found == ("btcusdt@kline_1h",)
    assert rig.events == [
        (str(RuntimeEventType.WS_DISCONNECT), _NOW3),
        (str(RuntimeEventType.WS_RECONNECT), _NOW3),
    ]
    assert [bar.close_time_utc for bar in rig.backfilled] == [_close_dt(i) for i in (1, 2, 3)]
    assert rig.gaps == []
    # The rebuilt stream resumes: a live closed bar on the new client reaches the sink.
    _emit(rig, "BTCUSDT", "1h", 4, client_index=1)
    assert [bar.close_time_utc for bar in rig.live] == [_close_dt(4)]


async def test_error_event_also_rebuilds() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    _fire(rig, "error")
    await rig.supervisor.wait_idle()

    assert len(rig.clients) == 2
    assert [name for name, _at in rig.events] == ["WS_DISCONNECT", "WS_RECONNECT"]


async def test_rebuild_exhaustion_still_backfills_and_reports_ws_disconnected_gaps() -> None:
    """CR-02 kept: an unrecoverable WS still runs the REST backfill; unrecovered closes are gaps."""
    rest = _FakeRest({("BTCUSDT", "1h"): RuntimeError("rest down")})
    rig = _make_rig(rest=rest, now=_NOW3, factory_error=ConnectionError("ws dead"))
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    with capture_logs() as captured:
        rig.fake.simulate_unsolicited_close()
        await rig.supervisor.wait_idle()

    assert any(entry["event"] == "paper.supervisor.reconnect_exhausted" for entry in captured)
    assert rig.events == [(str(RuntimeEventType.WS_DISCONNECT), _NOW3)], "no reconnect happened"
    assert len(rest.klines_calls) >= 1, "the backfill ran despite the exhausted rebuild"
    assert rig.gaps == [_gap(i, GapReason.WS_DISCONNECTED) for i in (1, 2, 3)]
    assert rig.backfilled == []


async def test_rebuild_exhaustion_with_a_working_rest_recovers_the_bars() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3, factory_error=ConnectionError("ws dead"))
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    rig.fake.simulate_unsolicited_close()
    await rig.supervisor.wait_idle()

    assert [bar.close_time_utc for bar in rig.backfilled] == [_close_dt(i) for i in (1, 2, 3)]
    assert rig.gaps == []


async def test_a_close_event_fired_during_our_own_rebuild_does_not_rebuild_again() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()
    original_rebuild = rig.adapter.rebuild

    async def _rebuild_that_closes_the_old_client() -> None:
        _fire(rig, "close")  # the SDK reports the old connection closing during our rebuild
        await original_rebuild()

    rig.adapter.rebuild = _rebuild_that_closes_the_old_client  # type: ignore[method-assign]

    rig.fake.simulate_unsolicited_close()
    await rig.supervisor.wait_idle()

    assert len(rig.clients) == 2, "exactly one rebuild"
    assert [name for name, _at in rig.events] == ["WS_DISCONNECT", "WS_RECONNECT"]


# --------------------------------------------------------------------------- #
# One rotation owner (P3): the SDK rotates, the supervisor only reacts.
# --------------------------------------------------------------------------- #


def test_no_scheduled_rotation_path_remains() -> None:
    for name in ("on_disconnect", "_reconnect_with_retry", "_resubscribe_and_backfill"):
        assert not hasattr(PaperSupervisor, name), name
    tree = ast.parse(Path("src/paper/supervisor.py").read_text(encoding="utf-8"))
    timers = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"call_later", "call_at"}
    }
    assert timers == set(), "the supervisor must not run its own rotation timer"


async def test_supervisor_never_closes_or_resubscribes_on_its_own() -> None:
    rig = _make_rig(rest=_pages(), now=_NOW3)
    await rig.supervisor.start()
    subscribed = len(rig.fake.kline_calls)

    await asyncio.sleep(0.05)

    assert rig.fake.close_calls == 0
    assert all(handle._unsubscribed == 0 for handle in rig.fake.handles)
    assert len(rig.fake.kline_calls) == subscribed
    assert rig.fake.create_connection_calls == 1


async def test_sdk_rotation_is_one_verification_backfill_and_no_resubscribe() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()
    subscribed = len(rig.fake.kline_calls)

    _fire(rig, "reconnect")  # the SDK's 23 h replacement of the connection
    await rig.supervisor.wait_idle()

    assert len(rig.rest.klines_calls) == 1
    assert len(rig.fake.kline_calls) == subscribed, "no re-subscribe by the supervisor"
    assert rig.fake.close_calls == 0
    assert all(handle._unsubscribed == 0 for handle in rig.fake.handles)
    assert len(rig.clients) == 1, "no rebuild for a reconnect event"


# --------------------------------------------------------------------------- #
# P8: seeding the cursor before start.
# --------------------------------------------------------------------------- #


async def test_a_seeded_close_lets_a_cold_start_backfill_from_the_restored_close() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))  # restored state, before start()
    await rig.supervisor.start()

    with capture_logs() as captured:
        _fire(rig, "open")
        await rig.supervisor.wait_idle()

    assert rig.rest.klines_calls == [("BTCUSDT", "1h", _ms(_close_dt(0)))]
    assert not any(entry["event"] == "paper.supervisor.no_last_close" for entry in captured)


async def test_without_a_seed_the_missing_cursor_is_loud_and_nothing_is_fetched() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    await rig.supervisor.start()

    with capture_logs() as captured:
        _fire(rig, "open")
        await rig.supervisor.wait_idle()

    assert rig.rest.klines_calls == []
    errors = [e for e in captured if e["event"] == "paper.supervisor.no_last_close"]
    assert len(errors) == 1
    assert errors[0]["log_level"] == "error"


# --------------------------------------------------------------------------- #
# Sinks: gaps are records, never only logs (P9); no duplicate gaps, no duplicate bars (D-28).
# --------------------------------------------------------------------------- #


async def test_a_gap_seen_by_two_verifications_is_reported_once() -> None:
    rig = _make_rig(rest=_pages(1), now=_close_dt(2) + timedelta(seconds=2))
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    _fire(rig, "reconnect")
    await rig.supervisor.wait_idle()
    _fire(rig, "reconnect")
    await rig.supervisor.wait_idle()

    assert [gap.expected_close_utc for gap in rig.gaps] == [_close_dt(2)]


async def test_a_rest_fake_ignoring_start_ms_cannot_produce_a_duplicate_bar() -> None:
    rest = _FakeRest({("BTCUSDT", "1h"): [_rest_bar("BTCUSDT", "1h", i) for i in (1, 2, 3)]})
    rest.ignore_start = True
    rig = _make_rig(rest=rest, now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    _fire(rig, "reconnect")
    await rig.supervisor.wait_idle()
    _fire(rig, "reconnect")
    await rig.supervisor.wait_idle()

    closes = [bar.close_time_utc for bar in rig.backfilled]
    assert closes == [_close_dt(1), _close_dt(2), _close_dt(3)]
    assert rig.supervisor._last_close[("BTCUSDT", "1h")] == _close_dt(3)


async def test_one_failing_pair_reports_its_gaps_while_the_healthy_pair_still_dispatches() -> None:
    rest = _FakeRest(
        {
            ("BTCUSDT", "1h"): RuntimeError("adapter_error: simulated outage"),
            ("ETHUSDT", "1h"): [_rest_bar("ETHUSDT", "1h", i) for i in (1, 2, 3)],
        }
    )
    rig = _make_rig(rest=rest, symbols=("BTCUSDT", "ETHUSDT"), now=_NOW3)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rig.supervisor.record_close(symbol, "1h", _close_dt(0))
    await rig.supervisor.start()

    _fire(rig, "reconnect")
    await rig.supervisor.wait_idle()

    assert [(bar.symbol, bar.close_time_utc) for bar in rig.backfilled] == [
        ("ETHUSDT", _close_dt(i)) for i in (1, 2, 3)
    ]
    assert rig.gaps == [_gap(i, GapReason.WS_RECONNECT_WINDOW, symbol="BTCUSDT") for i in (1, 2, 3)]
    assert {call[0] for call in rest.klines_calls} == {"BTCUSDT", "ETHUSDT"}


async def test_a_failing_live_sink_is_logged_and_becomes_an_unknown_gap() -> None:
    rig = _make_rig(live_sink_error=RuntimeError("queue full"))
    await rig.supervisor.start()

    with capture_logs() as captured:
        _emit(rig, "BTCUSDT", "1h", 0)

    assert any(entry["event"] == "paper.supervisor.sink_failed" for entry in captured)
    assert rig.gaps == [
        GapRecord(
            symbol="BTCUSDT",
            interval="1h",
            expected_close_utc=_close_dt(0),
            reason=GapReason.UNKNOWN,
            detected_at_utc=rig.supervisor._clock(),
        )
    ]


# --------------------------------------------------------------------------- #
# Live bars arriving while a recovery is running are held, so none is skipped (D-28).
# --------------------------------------------------------------------------- #


class _GatedRest(_FakeRest):
    def __init__(self, pages: dict[tuple[str, str], list[Kline] | Exception]) -> None:
        super().__init__(pages)
        self.gate = asyncio.Event()

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        await self.gate.wait()
        return await super().klines(symbol, interval, start_ms, end_ms, limit)


async def test_a_live_bar_during_recovery_is_delivered_after_the_backfilled_bars() -> None:
    now = _close_dt(4) + timedelta(seconds=2)
    rest = _GatedRest({("BTCUSDT", "1h"): [_rest_bar("BTCUSDT", "1h", i) for i in (1, 2, 3)]})
    rig = _make_rig(rest=rest, now=now)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    _fire(rig, "reconnect")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    _emit(rig, "BTCUSDT", "1h", 4)  # WS resumed and delivered the next bar mid-recovery
    assert rig.order == [], "the live bar waits for the recovery"

    rest.gate.set()
    await rig.supervisor.wait_idle()

    assert rig.order == [
        ("backfill", _close_dt(1)),
        ("backfill", _close_dt(2)),
        ("backfill", _close_dt(3)),
        ("live", _close_dt(4)),
    ]
    assert rig.gaps == [], "the held live bar covers its own slot"


async def test_stop_unsubscribes_closes_and_ignores_later_events() -> None:
    rig = _make_rig(rest=_pages(1, 2, 3), now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()

    await rig.supervisor.stop()
    _fire(rig, "close")
    _fire(rig, "reconnect")
    await rig.supervisor.wait_idle()

    assert all(handle._unsubscribed == 1 for handle in rig.fake.handles)
    assert rig.fake.close_calls == 1
    assert rig.events == []
    assert rig.rest.klines_calls == []
    assert rig.supervisor._handles == []


async def test_stop_cancels_a_recovery_that_is_still_running() -> None:
    rest = _GatedRest({("BTCUSDT", "1h"): [_rest_bar("BTCUSDT", "1h", 1)]})
    rig = _make_rig(rest=rest, now=_NOW3)
    rig.supervisor.record_close("BTCUSDT", "1h", _close_dt(0))
    await rig.supervisor.start()
    _fire(rig, "reconnect")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    await asyncio.wait_for(rig.supervisor.stop(), timeout=2)

    assert rig.backfilled == []
    assert rig.supervisor._held == []
