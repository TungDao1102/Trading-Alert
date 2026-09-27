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


def _make_rest_kline(
    symbol: str, interval: str, open_utc: datetime, close_utc: datetime
) -> Any:
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
    def __init__(self, *, raise_on_reconnect: Exception | None = None) -> None:
        self.subscribe_calls: list[tuple[str, str]] = []
        self.reconnect_calls: list[Any] = []
        self.close_calls: list[Any] = []
        self._raise_on_reconnect = raise_on_reconnect

    def subscribe(
        self, *, symbol: str, interval: str, on_kline: Any, stream_id: Any = None
    ) -> Any:
        self.subscribe_calls.append((symbol, interval))
        return object()

    def reconnect(self, handle: Any) -> None:
        self.reconnect_calls.append(handle)
        if self._raise_on_reconnect is not None:
            raise self._raise_on_reconnect

    def close(self, handle: Any) -> None:
        self.close_calls.append(handle)


class _FakeRestAdapter:
    def __init__(
        self,
        *,
        pages: dict[tuple[str, str], list[Any] | Exception] | None = None,
    ) -> None:
        self._pages = pages or {}
        self.klines_calls: list[tuple[str, str]] = []

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        self.klines_calls.append((symbol, interval))
        key = (symbol, interval)
        if key in self._pages:
            response = self._pages[key]
            if isinstance(response, Exception):
                raise response
            return list(response)
        return []


def _make_supervisor(
    *, ws: _FakeWsAdapter, rest: _FakeRestAdapter, now: datetime
) -> Any:
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
        _make_rest_kline("BTCUSDT", "1h", last + i * hour, last + (i + 1) * hour)
        for i in range(3)
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
    assert [k.close_time_utc for k in returned] == sorted(
        k.close_time_utc for k in returned
    )


def test_closed_kline_handler_records_last_close_for_backfill() -> None:
    """The live dispatch path records _last_close (resync is wired, live)."""
    from src.adapters.paper_ws import Kline as WsKline

    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter()
    supervisor = _make_supervisor(
        ws=ws, rest=rest, now=datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    )
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
    assert any(
        args and args[0] == "paper.supervisor.no_last_close" for args, _ in errors
    ), "missing last close must log paper.supervisor.no_last_close at ERROR"


# --------------------------------------------------------------------------- #
# CR-02: reconnect exhaustion still falls through to REST backfill.
# --------------------------------------------------------------------------- #


def test_reconnect_exhaustion_still_runs_backfill() -> None:
    """An unrecoverable WS drop still backfills via REST (never raises)."""
    last = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    closes = [
        _make_rest_kline("BTCUSDT", "1h", last + i * hour, last + (i + 1) * hour)
        for i in range(3)
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
    assert ("BTCUSDT", "1h") in [
        (c[0], c[1]) for c in rest.klines_calls
    ] or len(rest.klines_calls) >= 1, (
        "REST backfill must run even when reconnect is exhausted"
    )


def test_backfill_exception_yields_outage_gap_not_silence() -> None:
    """A failing pair returns a CollectorGap-shaped outage gap (WR-09)."""
    last = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)

    ws = _FakeWsAdapter()
    rest = _FakeRestAdapter(
        pages={("BTCUSDT", "1h"): RuntimeError("adapter down")}
    )
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
