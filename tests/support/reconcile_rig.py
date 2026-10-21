"""A ready-made reconcile loop and the feed / stream doubles of plan 20-16.

Everything here is a fake: nothing touches Binance, Telegram or a database, and nothing is a Demo
observation. `build_rig` wires a real `ReconcileLoop` to the existing 20-12 doubles plus:

- `FakeFeedSource`: the `FeedSource` Protocol (`read_feed()`), returning a fixed `FeedReading`.
- `FakeStreamSource`: the `StreamDivergenceSource` Protocol (`drain()`, `halted_reason()`).
- `QueryingAdapter`: `FakeReconcileAdapter` plus `query_order_by_client` and the SDK-free
  `error_facts` of the real adapter, with every call recorded.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_usdm import OrderProbe
from src.execution.execution_limits import ExecutionLimits
from src.reconcile.feed_freshness import FeedReading
from src.reconcile.loop import ReconcileLoop
from src.reconcile.safe_mode import SafeModeController

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_doubles import (
    FakeGate,
    FakeIntentStore,
    FakeProtectionView,
    FakeReconcileAdapter,
    InMemorySafeModeStore,
    RecordingAlertSink,
    RecordingJournal,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)


class FakeFeedSource:
    """`FeedSource.read_feed()` over a fixed reading; `raises` makes the read fail."""

    def __init__(self, reading: FeedReading, *, raises: BaseException | None = None) -> None:
        self.reading = reading
        self.raises = raises
        self.calls = 0

    def read_feed(self) -> FeedReading:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.reading


@dataclass(frozen=True, kw_only=True)
class FakeStreamItem:
    """Duck-typed `StreamDivergence`: the loop matches `kind` by its string value."""

    kind: str
    symbol: str | None = None
    client_order_id: str | None = None
    client_algo_id: str | None = None
    reason: str = "fixed project text"
    anomaly_kind: str | None = None
    payload_sha256: str | None = None
    after_gap: bool = False


class FakeStreamSource:
    """`StreamDivergenceSource`: `drain()` hands the queued items over once, then is empty."""

    def __init__(
        self,
        items: Iterable[Any] = (),
        *,
        halted: str | None = None,
        drain_raises: BaseException | None = None,
        halted_raises: BaseException | None = None,
    ) -> None:
        self.items: list[Any] = list(items)
        self.halted = halted
        self.drain_raises = drain_raises
        self.halted_raises = halted_raises
        self.drain_calls = 0

    def drain(self) -> Sequence[Any]:
        self.drain_calls += 1
        if self.drain_raises is not None:
            raise self.drain_raises
        taken, self.items = tuple(self.items), []
        return taken

    def halted_reason(self) -> str | None:
        if self.halted_raises is not None:
            raise self.halted_raises
        return self.halted


class QueryingAdapter(FakeReconcileAdapter):
    """The 20-12 adapter double with the by-client order query and the real `error_facts`.

    `normal_probes` maps a client order id to its `OrderProbe`; an unknown id answers
    `found=False`. `query_order_by_client` calls are kept in `order_queries` as
    `(symbol, client order id)`; the algo queries are the inherited `query_algo_order_by_client`
    (recorded in `calls`) with the ids in `algo_queries`.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.order_queries: list[tuple[str, str]] = []
        self.algo_queries: list[str] = []

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> OrderProbe:
        self._enter("query_order_by_client")
        self.order_queries.append((symbol, orig_client_order_id))
        return OrderProbe(
            client_order_id=orig_client_order_id,
            found=False,
            order_id=None,
            status=None,
            update_time_utc=None,
        )

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
        self.algo_queries.append(client_algo_id)
        return await super().query_algo_order_by_client(client_algo_id=client_algo_id)

    @staticmethod
    def error_facts(exc: BaseException) -> Any:
        return error_facts_from_exception(exc)


class SpyingSafeMode(SafeModeController):
    """The real controller; keeps every entered reason and refuses any exit."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.enter_calls: list[str] = []

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None:
        self.enter_calls.append(reason)
        super().enter_safe_mode(reason=reason, now_utc=now_utc)

    async def exit_safe_mode(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the reconcile loop must never exit SAFE_MODE")


class NoopSweeper:
    """An orphan sweeper that is never expected to sweep."""

    def __init__(self) -> None:
        self.calls = 0

    async def sweep(self, diff: Any, *, position_verifier: Any, now_utc: datetime) -> Any:
        self.calls += 1
        return None


@dataclass
class Rig:
    loop: ReconcileLoop
    adapter: QueryingAdapter
    safe_mode: SpyingSafeMode
    protection: FakeProtectionView
    alerts: RecordingAlertSink
    journal: RecordingJournal
    feed: FakeFeedSource | None
    stream: FakeStreamSource | None

    def event_types(self) -> list[str]:
        return [e.event_type for e in self.journal.events]


def build_rig(
    *,
    plans: tuple[Any, ...] = (),
    normal: tuple[Any, ...] = (),
    algo: tuple[Any, ...] = (),
    positions: tuple[Any, ...] = (),
    adapter: QueryingAdapter | None = None,
    feed: FakeFeedSource | None = None,
    stream: FakeStreamSource | None = None,
    limits: ExecutionLimits | None = None,
    alerts: RecordingAlertSink | None = None,
    gate: Any = None,
    protection: FakeProtectionView | None = None,
) -> Rig:
    fake = adapter or QueryingAdapter(normal_orders=normal, algo_orders=algo, positions=positions)
    safe_mode = SpyingSafeMode(
        adapter=fake, journal=RecordingJournal(), state_store=InMemorySafeModeStore()
    )
    view = protection or FakeProtectionView(plans)
    sink = alerts or RecordingAlertSink()
    journal = RecordingJournal()
    loop = ReconcileLoop(
        adapter=fake,
        gate=gate or FakeGate(),
        safe_mode=safe_mode,
        intent_store=FakeIntentStore(),
        protection=view,
        sweeper=NoopSweeper(),
        alerts=sink,
        journal=journal,
        limits=limits or make_test_limits(),
        feeds=feed,
        **({"stream": stream} if stream is not None else {}),
    )
    return Rig(
        loop=loop,
        adapter=fake,
        safe_mode=safe_mode,
        protection=view,
        alerts=sink,
        journal=journal,
        feed=feed,
        stream=stream,
    )
