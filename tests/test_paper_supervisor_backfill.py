"""Supervisor backfill-return pins (Phase 7 REVIEW CR-03 + CR-02).

CR-03 (fix commit 9d636c2): _resubscribe_and_backfill previously surfaced
backfilled closes only via log.info — the closes were dropped on the floor
and resync was a silent no-op end to end. The fix returns backfilled closes
per (symbol, interval) pair so the caller can persist/dispatch them, and
logs paper.supervisor.no_last_close at ERROR when a pair has no recorded
close (loud, not silent skip).

CR-02 (fix commit 49636f7): on_disconnect(scheduled=False) used to let a
reconnect-exhaustion exception escape before backfill ran — the worst
outages skipped the REST backfill that mattered most. The fix falls
through to _resubscribe_and_backfill regardless.

All tests use injected fakes; no network is touched.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import tenacity


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: Any) -> None:
    """Bypass production retry sleeps (Group A option 1).

    The supervisor reconnect path (7 attempts, exponential backoff)
    and the resync backfill path (7 attempts, exponential backoff)
    sleep ~30-50s on the failing path. Unit tests must assert the
    fail-closed logic (reconnect attempted, backfill still runs, gap
    journaled) without burning the production sleep budget.
    """
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )


def _make_rest_kline(symbol: str, interval: str, open_utc: datetime, close_utc: datetime) -> Any:
    from src.adapters.binance_usdm import Kline

    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=open_utc,
        close_time_utc=close_utc,
        open=Decimal("100.00"),
        high=Decimal("100.10"),
        low=Decimal("99.95"),
        close=Decimal("100.05"),
        volume=Decimal("1.0"),
        quote_volume=Decimal("0"),
        trade_count=0,
    )


class _FakeWsAdapter:
    def __init__(
        self,
        *,
        raise_on_reconnect: Exception | None = None,
        calls: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.subscribe_calls: list[tuple[str, str]] = []
        self.reconnect_calls: list[Any] = []
        self.close_calls: list[Any] = []
        self._raise_on_reconnect = raise_on_reconnect
        # Optional shared call log (D-20): the WS and REST fakes append to
        # ONE list so the test can assert cross-adapter ORDER by index.
        self.calls: list[tuple[Any, ...]] = calls if calls is not None else []

    def subscribe(self, *, symbol: str, interval: str, on_kline: Any, stream_id: Any = None) -> Any:
        self.subscribe_calls.append((symbol, interval))
        self.calls.append(("subscribe", symbol, interval))
        return (symbol, interval)

    def reconnect(self, handle: Any) -> None:
        self.reconnect_calls.append(handle)
        self.calls.append(("reconnect", handle))
        if self._raise_on_reconnect is not None:
            raise self._raise_on_reconnect

    def close(self, handle: Any) -> None:
        self.close_calls.append(handle)
        self.calls.append(("close", handle))


class _FakeRestAdapter:
    def __init__(
        self,
        *,
        pages: dict[tuple[str, str], list[Any] | Exception] | None = None,
        calls: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self._pages = pages or {}
        self.klines_calls: list[tuple[str, str]] = []
        self.calls: list[tuple[Any, ...]] = calls if calls is not None else []

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        self.klines_calls.append((symbol, interval))
        self.calls.append(("klines", symbol, interval, start_ms))
        key = (symbol, interval)
        if key in self._pages:
            response = self._pages[key]
            if isinstance(response, Exception):
                raise response
            return list(response)
        return []


def _make_supervisor(*, ws: _FakeWsAdapter, rest: _FakeRestAdapter, now: datetime) -> Any:
    from src.paper.supervisor import PaperSupervisor

    return PaperSupervisor(
        ws_adapter=ws,  # type: ignore[arg-type]
        rest_adapter=rest,  # type: ignore[arg-type]
        on_closed_candle=lambda _k: None,
        symbols=("BTCUSDT",),
        intervals=("1h",),
        clock=lambda: now,
    )


# --------------------------------------------------------------------------- #
# CR-03a: backfilled closes are RETURNED per pair, not log-only.
# --------------------------------------------------------------------------- #


def test_resubscribe_and_backfill_returns_closes_per_pair() -> None:
    """Backfilled closes come back keyed per pair for caller dispatch."""
    last = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    closes = [
        _make_rest_kline("BTCUSDT", "1h", last + i * hour, last + (i + 1) * hour) for i in range(3)
    ]

    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter(pages={("BTCUSDT", "1h"): closes})
    supervisor = _make_supervisor(ws=ws, rest=rest, now=now)
    supervisor.start()
    supervisor.record_close("BTCUSDT", "1h", last)

    backfilled, _outage_gaps = asyncio.run(
        supervisor._resubscribe_and_backfill(journal_outage_gaps=False)
    )

    assert ("BTCUSDT", "1h") in backfilled, (
        "backfilled closes must be returned per pair, not log-only"
    )
    returned = backfilled[("BTCUSDT", "1h")]
    assert len(returned) == 3
    assert [k.close_time_utc for k in returned] == sorted(k.close_time_utc for k in returned)


def test_closed_kline_handler_records_last_close_for_backfill() -> None:
    """The live dispatch path records _last_close (resync is wired, live)."""
    from src.adapters.paper_ws import Kline as WsKline

    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter()
    supervisor = _make_supervisor(ws=ws, rest=rest, now=datetime(2026, 9, 19, 13, 0, tzinfo=UTC))
    supervisor.start()

    assert supervisor._last_close == {}
    close_utc = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    handler = supervisor._make_kline_handler("BTCUSDT", "1h")
    handler(
        WsKline(
            symbol="BTCUSDT",
            interval="1h",
            open_time_utc=datetime(2026, 9, 19, 11, 0, tzinfo=UTC),
            close_time_utc=close_utc,
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=Decimal("1"),
            quote_volume=Decimal("1"),
            trade_count=1,
            is_closed=True,
        )
    )
    assert supervisor._last_close[("BTCUSDT", "1h")] == close_utc

    # A forming kline must NOT advance the backfill cursor.
    handler(
        WsKline(
            symbol="BTCUSDT",
            interval="1h",
            open_time_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
            close_time_utc=datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=Decimal("1"),
            quote_volume=Decimal("1"),
            trade_count=1,
            is_closed=False,
        )
    )
    assert supervisor._last_close[("BTCUSDT", "1h")] == close_utc


# --------------------------------------------------------------------------- #
# CR-03b: missing last-close is LOUD (ERROR), pairs without closes omitted.
# --------------------------------------------------------------------------- #


def test_missing_last_close_is_loud_and_pair_omitted(
    monkeypatch: Any,
) -> None:
    """A pair with no recorded close is omitted AND errors loudly."""
    import src.paper.supervisor as supervisor_mod

    errors: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real_log = supervisor_mod.log

    class _SpyLog:
        def __getattr__(self, name: str) -> Any:
            return getattr(real_log, name)

        def error(self, *args: Any, **kwargs: Any) -> Any:
            errors.append((args, kwargs))
            return real_log.error(*args, **kwargs)

    monkeypatch.setattr(supervisor_mod, "log", _SpyLog())

    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter()
    supervisor = _make_supervisor(ws=ws, rest=rest, now=now)
    supervisor.start()
    # Deliberately: NO record_close call — dispatch never saw this pair.

    backfilled, outage_gaps = asyncio.run(
        supervisor._resubscribe_and_backfill(journal_outage_gaps=False)
    )

    assert backfilled == {}, "pair with no last close contributes no entry"
    assert rest.klines_calls == [], "no backfill without a cursor"
    assert any(args and args[0] == "paper.supervisor.no_last_close" for args, _ in errors), (
        "missing last close must log paper.supervisor.no_last_close at ERROR"
    )


# --------------------------------------------------------------------------- #
# CR-02: reconnect exhaustion still falls through to REST backfill.
# --------------------------------------------------------------------------- #


def test_reconnect_exhaustion_still_runs_backfill() -> None:
    """An unrecoverable WS drop still backfills via REST (never raises)."""
    last = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    closes = [
        _make_rest_kline("BTCUSDT", "1h", last + i * hour, last + (i + 1) * hour) for i in range(3)
    ]

    ws = _FakeWsAdapter(raise_on_reconnect=ConnectionError("ws dead"))
    rest = _FakeRestAdapter(pages={("BTCUSDT", "1h"): closes})
    supervisor = _make_supervisor(ws=ws, rest=rest, now=now)
    supervisor.start()
    supervisor.record_close("BTCUSDT", "1h", last)

    # Must not raise despite total reconnect failure (7 attempts exhausted
    # internally against the always-failing fake).
    asyncio.run(supervisor.on_disconnect(scheduled=False))

    assert len(ws.reconnect_calls) > 0, "reconnect must have been attempted"
    assert ("BTCUSDT", "1h") in [(c[0], c[1]) for c in rest.klines_calls] or len(
        rest.klines_calls
    ) >= 1, "REST backfill must run even when reconnect is exhausted"


def test_backfill_exception_yields_outage_gap_not_silence() -> None:
    """A failing pair returns a CollectorGap-shaped outage gap (WR-09)."""
    last = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)

    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter(pages={("BTCUSDT", "1h"): RuntimeError("adapter down")})
    supervisor = _make_supervisor(ws=ws, rest=rest, now=now)
    supervisor.start()
    supervisor.record_close("BTCUSDT", "1h", last)

    backfilled, outage_gaps = asyncio.run(
        supervisor._resubscribe_and_backfill(journal_outage_gaps=True)
    )

    assert backfilled == {}
    assert len(outage_gaps) == 1
    gap = outage_gaps[0]
    assert gap["symbol"] == "BTCUSDT"
    assert gap["data_class"] == "paper-1h"
    assert gap["expected_utc"] == last
    assert gap["observed_utc"] == now
    assert gap["reason"].startswith("backfill_exception:")


# --------------------------------------------------------------------------- #
# Plan 13-03 Task 1 (D-16, D-20, F-413): backfill BEFORE resubscribe.
# --------------------------------------------------------------------------- #

_T0 = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
_HOUR = timedelta(hours=1)


def _three_bars() -> list[Any]:
    return [
        _make_rest_kline("BTCUSDT", "1h", _T0 + i * _HOUR, _T0 + (i + 1) * _HOUR) for i in range(3)
    ]


def _indices(calls: list[tuple[Any, ...]], kind: str) -> list[int]:
    return [i for i, c in enumerate(calls) if c[0] == kind]


def _seam_setup(
    *, pages: Any = None, now: datetime | None = None
) -> tuple[Any, _FakeWsAdapter, _FakeRestAdapter, list[tuple[Any, ...]]]:
    calls: list[tuple[Any, ...]] = []
    ws = _FakeWsAdapter(calls=calls)
    rest = _FakeRestAdapter(
        pages=pages if pages is not None else {("BTCUSDT", "1h"): _three_bars()},
        calls=calls,
    )
    supervisor = _make_supervisor(
        ws=ws, rest=rest, now=now or datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    )
    supervisor.start()
    supervisor.record_close("BTCUSDT", "1h", _T0)
    # Only the resubscribe sequence is under test, not the initial start().
    calls.clear()
    return supervisor, ws, rest, calls


def test_backfill_runs_before_resubscribe_on_unsolicited_drop() -> None:
    """close -> klines -> subscribe by index in one shared call log (D-20)."""
    supervisor, _ws, _rest, calls = _seam_setup()

    asyncio.run(supervisor.on_disconnect(scheduled=False))

    closes = _indices(calls, "close")
    klines = _indices(calls, "klines")
    subscribes = _indices(calls, "subscribe")
    assert closes and klines and subscribes, calls
    assert max(closes) < min(klines), "old handles close before the backfill"
    # First-pass klines entry precedes the first subscribe entry.
    assert klines[0] < subscribes[0], "backfill must run BEFORE resubscribe (D-16, F-413)"


def test_backfill_runs_before_resubscribe_on_rotation() -> None:
    """Scheduled rotation: same order, and no reconnect entry."""
    supervisor, _ws, _rest, calls = _seam_setup()

    asyncio.run(supervisor.on_disconnect(scheduled=True))

    assert _indices(calls, "reconnect") == []
    closes = _indices(calls, "close")
    klines = _indices(calls, "klines")
    subscribes = _indices(calls, "subscribe")
    assert closes and klines and subscribes, calls
    assert max(closes) < min(klines)
    assert klines[0] < subscribes[0]


def test_backfilled_closes_advance_last_close() -> None:
    """The last-close state moves to the latest backfilled bar's close."""
    supervisor, _ws, _rest, _calls = _seam_setup()

    backfilled, _gaps = asyncio.run(supervisor._resubscribe_and_backfill(journal_outage_gaps=False))

    assert len(backfilled[("BTCUSDT", "1h")]) == 3
    assert supervisor._last_close[("BTCUSDT", "1h")] == _T0 + 3 * _HOUR


def test_failing_pair_is_still_resubscribed_with_outage_gap() -> None:
    """A raising pair still resubscribes and yields one outage gap (T-13-12)."""
    supervisor, ws, _rest, calls = _seam_setup(
        pages={("BTCUSDT", "1h"): RuntimeError("adapter down")}
    )

    backfilled, outage_gaps = asyncio.run(
        supervisor._resubscribe_and_backfill(journal_outage_gaps=True)
    )

    assert backfilled == {}
    assert len(outage_gaps) == 1
    gap = outage_gaps[0]
    assert gap["symbol"] == "BTCUSDT"
    assert gap["data_class"] == "paper-1h"
    assert gap["reason"].startswith("backfill_exception:")
    assert _indices(calls, "subscribe"), "pair must be resubscribed regardless"
    assert ws.subscribe_calls[-1] == ("btcusdt", "1h")


def test_record_close_never_moves_backwards() -> None:
    """record_close is monotonic: an earlier close leaves the stored one."""
    supervisor, _ws, _rest, _calls = _seam_setup()
    later = _T0 + 2 * _HOUR

    supervisor.record_close("BTCUSDT", "1h", later)
    supervisor.record_close("BTCUSDT", "1h", _T0 + _HOUR)

    assert supervisor._last_close[("BTCUSDT", "1h")] == later


# --------------------------------------------------------------------------- #
# Plan 13-03 Task 2 (D-28): verification pass + monotonic WS guard.
# --------------------------------------------------------------------------- #


class _SequencedRestAdapter(_FakeRestAdapter):
    """REST fake whose Nth klines call returns responses[N] (last repeats)."""

    def __init__(
        self,
        responses: list[list[Any] | Exception],
        *,
        calls: list[tuple[Any, ...]] | None = None,
    ) -> None:
        super().__init__(calls=calls)
        self._responses = responses

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        index = min(len(self.klines_calls), len(self._responses) - 1)
        self.klines_calls.append((symbol, interval))
        self.calls.append(("klines", symbol, interval, start_ms))
        response = self._responses[index]
        if isinstance(response, Exception):
            raise response
        return list(response)


def _two_pass_supervisor(
    rest: _FakeRestAdapter, ws: _FakeWsAdapter, clock_values: list[datetime]
) -> Any:
    from src.paper.supervisor import PaperSupervisor

    values = iter(clock_values)
    supervisor = PaperSupervisor(
        ws_adapter=ws,  # type: ignore[arg-type]
        rest_adapter=rest,  # type: ignore[arg-type]
        on_closed_candle=lambda _k: None,
        symbols=("BTCUSDT",),
        intervals=("1h",),
        clock=lambda: next(values),
    )
    supervisor.start()
    supervisor.record_close("BTCUSDT", "1h", _T0)
    ws.calls.clear()
    return supervisor


def test_verification_pass_picks_up_bar_closed_in_seam() -> None:
    """A bar closing between the first backfill and the WS attach is kept."""
    t1 = _T0 + 3 * _HOUR
    t2 = t1 + _HOUR
    bars = _three_bars()
    seam_bar = _make_rest_kline("BTCUSDT", "1h", t1, t2)
    calls: list[tuple[Any, ...]] = []
    ws = _FakeWsAdapter(calls=calls)
    # First call: bars closing up to t1. Second call (verification): the
    # last bar again plus one extra bar that closed at t2.
    rest = _SequencedRestAdapter([bars, [bars[-1], seam_bar]], calls=calls)
    supervisor = _two_pass_supervisor(rest, ws, [t1, t2])

    backfilled, _gaps = asyncio.run(supervisor._resubscribe_and_backfill(journal_outage_gaps=False))

    returned = backfilled[("BTCUSDT", "1h")]
    closes = [k.close_time_utc for k in returned]
    assert closes == [_T0 + _HOUR, _T0 + 2 * _HOUR, t1, t2], (
        "every bar exactly once, in close order, ending with the seam bar"
    )
    klines = _indices(calls, "klines")
    subscribes = _indices(calls, "subscribe")
    assert len(klines) == 2, "one first-pass and one verification klines call"
    assert klines[0] < min(subscribes) < klines[1], (
        "verification pass must run after the subscribe entries"
    )
    assert supervisor._last_close[("BTCUSDT", "1h")] == t2


def test_same_bar_from_both_passes_returned_once() -> None:
    """A REST fake ignoring start_ms cannot produce a duplicate bar."""
    t1 = _T0 + 3 * _HOUR
    calls: list[tuple[Any, ...]] = []
    ws = _FakeWsAdapter(calls=calls)
    rest = _FakeRestAdapter(pages={("BTCUSDT", "1h"): _three_bars()}, calls=calls)
    supervisor = _two_pass_supervisor(rest, ws, [t1, t1])

    backfilled, _gaps = asyncio.run(supervisor._resubscribe_and_backfill(journal_outage_gaps=False))

    assert len(rest.klines_calls) == 2, "both passes ran"
    closes = [k.close_time_utc for k in backfilled[("BTCUSDT", "1h")]]
    assert closes == [_T0 + _HOUR, _T0 + 2 * _HOUR, _T0 + 3 * _HOUR]
    assert len(set(closes)) == len(closes)


def _ws_kline(close_utc: datetime, *, is_closed: bool = True) -> Any:
    from src.adapters.paper_ws import Kline as WsKline

    return WsKline(
        symbol="BTCUSDT",
        interval="1h",
        open_time_utc=close_utc - _HOUR,
        close_time_utc=close_utc,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("1"),
        quote_volume=Decimal("1"),
        trade_count=1,
        is_closed=is_closed,
    )


def test_ws_duplicate_of_backfilled_close_is_not_dispatched(
    monkeypatch: Any,
) -> None:
    """The WS handler drops a closed kline at or before the last close."""
    import src.paper.supervisor as supervisor_mod
    from src.paper.supervisor import PaperSupervisor

    events: list[str] = []
    real_log = supervisor_mod.log

    class _SpyLog:
        def __getattr__(self, name: str) -> Any:
            return getattr(real_log, name)

        def info(self, event: str, *args: Any, **kwargs: Any) -> Any:
            events.append(event)
            return real_log.info(event, *args, **kwargs)

        def warning(self, event: str, *args: Any, **kwargs: Any) -> Any:
            events.append(event)
            return real_log.warning(event, *args, **kwargs)

    monkeypatch.setattr(supervisor_mod, "log", _SpyLog())

    dispatched: list[Any] = []
    supervisor = PaperSupervisor(
        ws_adapter=_FakeWsAdapter(),  # type: ignore[arg-type]
        rest_adapter=_FakeRestAdapter(),  # type: ignore[arg-type]
        on_closed_candle=dispatched.append,
        symbols=("BTCUSDT",),
        intervals=("1h",),
        clock=lambda: _T0 + 6 * _HOUR,
    )
    supervisor.start()
    last = _T0 + 3 * _HOUR
    supervisor.record_close("BTCUSDT", "1h", last)
    handler = supervisor._make_kline_handler("BTCUSDT", "1h")

    handler(_ws_kline(last))
    assert dispatched == [], "close equal to the last close is a duplicate"
    assert "paper.supervisor.duplicate_close_dropped" in events

    handler(_ws_kline(last - _HOUR))
    assert dispatched == [], "an older close is stale"

    handler(_ws_kline(last + 2 * _HOUR, is_closed=False))
    assert dispatched == [], "forming klines are ignored"

    handler(_ws_kline(last + _HOUR))
    assert len(dispatched) == 1
    assert dispatched[0].close_time_utc == last + _HOUR
    assert supervisor._last_close[("BTCUSDT", "1h")] == last + _HOUR


def test_advance_last_close_is_atomic_under_threads() -> None:
    """32 concurrent claims of the same bar produce exactly one True."""
    import threading

    supervisor, _ws, _rest, _calls = _seam_setup()
    close = _T0 + 5 * _HOUR
    barrier = threading.Barrier(32)
    results: list[bool] = []
    results_lock = threading.Lock()

    def _claim() -> None:
        barrier.wait()
        won = supervisor._advance_last_close("BTCUSDT", "1h", close)
        with results_lock:
            results.append(won)

    threads = [threading.Thread(target=_claim) for _ in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 32
    assert results.count(True) == 1
    assert supervisor._last_close[("BTCUSDT", "1h")] == close


def test_verification_failure_keeps_first_pass_closes() -> None:
    """A verification-pass exception adds a gap and keeps first-pass closes."""
    t1 = _T0 + 3 * _HOUR
    calls: list[tuple[Any, ...]] = []
    ws = _FakeWsAdapter(calls=calls)
    rest = _SequencedRestAdapter([_three_bars(), RuntimeError("verify down")], calls=calls)
    supervisor = _two_pass_supervisor(rest, ws, [t1, t1 + _HOUR])

    backfilled, outage_gaps = asyncio.run(
        supervisor._resubscribe_and_backfill(journal_outage_gaps=True)
    )

    assert len(backfilled[("BTCUSDT", "1h")]) == 3
    assert len(outage_gaps) == 1
    assert outage_gaps[0]["reason"].startswith("verify_backfill_exception:")
    assert _indices(calls, "subscribe"), "the pair is still resubscribed"
