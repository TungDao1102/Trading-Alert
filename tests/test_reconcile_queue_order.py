"""Order of work inside one reconcile tick (Phase 20, plan 20-21; D-20, D-21, Q4).

Two things are pinned here:

* the background refresh of the last validated lot filters runs LAST in a tick, only for tracked
  symbols, never under a gate restriction, and a refresher that fails never fails the tick (D-21);
* once the REST gate allows sending, open pending risk-reducing actions are handed to the injected
  `risk_reducer` BEFORE the compare is acted on and BEFORE background work (D-20, owner decision
  O-E "accept-queue-order"). That is queue ORDER only: a pause is never bypassed, no request
  weight is reserved, and the loop sends nothing itself.

Evidence label: executed unit tests with fakes and a shared call-order recorder. Nothing here
touches Binance, Telegram or a database, and nothing is a Demo observation.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from src.adapters.binance_ratelimit_gate import RATE_LIMIT_PAUSE_429, GateRestriction
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.execution.pending_actions import PendingAction, PendingKind, PendingState
from src.reconcile.loop import (
    RECONCILE_ACTION_FAILED,
    RECONCILE_BACKGROUND_SKIPPED,
    RECONCILE_READ_FAILED,
    RECONCILE_SKIPPED_GATE,
    TICK_COMPARED,
    TICK_SKIPPED_GATE,
    ReconcileLoop,
)
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
    make_algo_order,
    make_intent_record,
    make_plan_protection,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
H1 = "1" * 64
H2 = "2" * 64
SL_ID = derive_algo_client_id(plan_hash=H1, role=OrderRole.STOP_LOSS.value)


# --------------------------------------------------------------------------- #
# Fakes: every one appends to ONE shared order list.
# --------------------------------------------------------------------------- #


class OrderedAdapter(FakeReconcileAdapter):
    """The fake adapter; every REST read lands in the shared call-order recorder."""

    def __init__(self, order: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._order = order

    def _enter(self, name: str) -> None:
        self._order.append(f"read:{name}")
        super()._enter(name)


class OrderedSweeper:
    def __init__(self, order: list[str]) -> None:
        self._order = order

    async def sweep(self, diff: Any, *, position_verifier: Any, now_utc: datetime) -> Any:
        self._order.append("sweep")
        return None


class OrderedRefresher:
    """`LotFilterRefresher.refresh_if_due`; returns what the test set, or raises."""

    def __init__(
        self, order: list[str], *, result: bool = True, raises: BaseException | None = None
    ) -> None:
        self._order = order
        self._result = result
        self._raises = raises
        self.calls: list[tuple[str, datetime]] = []

    async def refresh_if_due(self, symbol: str, *, now_utc: datetime) -> bool:
        self._order.append(f"refresh:{symbol}")
        self.calls.append((symbol, now_utc))
        if self._raises is not None:
            raise self._raises
        return self._result


class OrderedPending:
    """`list_open()` that keeps its own queue; `resolve_all` simulates the reducer's success."""

    def __init__(
        self,
        order: list[str],
        rows: Sequence[PendingAction] = (),
        *,
        raises: BaseException | None = None,
        raises_after_reducer: bool = False,
    ) -> None:
        self._order = order
        self.rows = list(rows)
        self.raises = raises
        self.raises_after_reducer = raises_after_reducer
        self.reducer_ran = False
        self.calls = 0

    def list_open(self) -> tuple[PendingAction, ...]:
        self.calls += 1
        self._order.append("list_open")
        if self.raises is not None or (self.raises_after_reducer and self.reducer_ran):
            raise self.raises or RuntimeError("password=hunter2")
        return tuple(self.rows)

    def resolve_all(self) -> None:
        self.rows.clear()


@dataclass
class Reducer:
    """The injected `risk_reducer`; counts awaits and optionally resolves the rows."""

    order: list[str]
    pending: OrderedPending | None = None
    resolves: bool = False
    raises: BaseException | None = None
    awaits: int = 0
    seen_sizes: list[int] = field(default_factory=list)

    async def __call__(self) -> None:
        self.awaits += 1
        self.order.append("risk_reducer")
        if self.pending is not None:
            self.pending.reducer_ran = True
            if self.resolves:
                self.pending.resolve_all()
        if self.raises is not None:
            raise self.raises


class SpyingSafeMode(SafeModeController):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.enter_calls: list[str] = []

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None:
        self.enter_calls.append(reason)
        super().enter_safe_mode(reason=reason, now_utc=now_utc)

    async def exit_safe_mode(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the reconcile loop must never exit SAFE_MODE")


def pending_row(kind: PendingKind, *, suffix: str = "a") -> PendingAction:
    return PendingAction(
        pending_id=f"pend-{kind.value}-{suffix}",
        plan_hash=H1,
        trade_plan_id="tp-1",
        approval_id="ap-1",
        symbol="BTCUSDT",
        kind=kind,
        state=PendingState.PENDING,
        gate_reason=RATE_LIMIT_PAUSE_429,
        first_blocked_at_utc=NOW,
        last_blocked_at_utc=NOW,
    )


@dataclass
class Rig:
    loop: ReconcileLoop
    order: list[str]
    adapter: OrderedAdapter
    gate: FakeGate
    safe_mode: SpyingSafeMode
    journal: RecordingJournal
    refresher: OrderedRefresher | None
    pending: OrderedPending | None
    reducer: Reducer | None

    def event_types(self) -> list[str]:
        return [e.event_type for e in self.journal.events]

    def payloads(self, event_type: str) -> list[dict[str, Any]]:
        return [
            json.loads(e.payload_json) for e in self.journal.events if e.event_type == event_type
        ]


def make_rig(
    *,
    plans: tuple[Any, ...] | None = None,
    orphan: bool = False,
    refresher: OrderedRefresher | None = None,
    pending: OrderedPending | None = None,
    reducer: Reducer | None = None,
    gate: FakeGate | None = None,
    order: list[str] | None = None,
) -> Rig:
    shared = order if order is not None else []
    if plans is None:
        plans = (
            make_plan_protection(H1, symbol="BTCUSDT", state="PROTECTED"),
            make_plan_protection(H2, symbol="ETHUSDT", state="PROTECTED"),
        )
    adapter = OrderedAdapter(
        shared, algo_orders=(make_algo_order(SL_ID, "BTCUSDT"),) if orphan else ()
    )
    safe_mode = SpyingSafeMode(
        adapter=adapter, journal=RecordingJournal(), state_store=InMemorySafeModeStore()
    )
    journal = RecordingJournal()
    gate_double = gate or FakeGate()
    intents = (
        FakeIntentStore([make_intent_record(H1, OrderRole.STOP_LOSS.value)])
        if orphan
        else FakeIntentStore()
    )
    kwargs: dict[str, Any] = {}
    if refresher is not None:
        kwargs["lot_filters"] = refresher
    if pending is not None:
        kwargs["pending_actions"] = pending
    if reducer is not None:
        kwargs["risk_reducer"] = reducer
    loop = ReconcileLoop(
        adapter=adapter,
        gate=gate_double,
        safe_mode=safe_mode,
        intent_store=intents,
        protection=FakeProtectionView(plans),
        sweeper=OrderedSweeper(shared),
        alerts=RecordingAlertSink(),
        journal=journal,
        limits=make_test_limits(),
        **kwargs,
    )
    return Rig(
        loop=loop,
        order=shared,
        adapter=adapter,
        gate=gate_double,
        safe_mode=safe_mode,
        journal=journal,
        refresher=refresher,
        pending=pending,
        reducer=reducer,
    )


def restricted_gate() -> FakeGate:
    return FakeGate(
        GateRestriction(reason=RATE_LIMIT_PAUSE_429, until_utc=None, remaining_seconds=30)
    )


# --------------------------------------------------------------------------- #
# Task 1: the background lot-filter refresh (D-21).
# --------------------------------------------------------------------------- #


async def test_lot_filter_refresh_is_background_work_last() -> None:
    order: list[str] = []
    refresher = OrderedRefresher(order)
    # The BTCUSDT stop has no tracked plan: an orphan, so the tick sweeps it. ETHUSDT is tracked.
    eth_plan = make_plan_protection(H2, symbol="ETHUSDT", state="PROTECTED")
    rig = make_rig(refresher=refresher, orphan=True, plans=(eth_plan,), order=order)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert [symbol for symbol, _ in refresher.calls] == ["ETHUSDT"]
    assert all(at == NOW for _, at in refresher.calls)
    refresh_positions = [i for i, step in enumerate(order) if step.startswith("refresh:")]
    other_positions = [i for i, step in enumerate(order) if not step.startswith("refresh:")]
    assert refresh_positions, "the refresher was never called"
    assert min(refresh_positions) > max(other_positions), order
    assert order.index("sweep") < min(refresh_positions)
    assert report.order[-1] == "background"
    assert "sweep" in report.order
    assert report.order.index("sweep") < report.order.index("background")
    assert report.order.index("compare") < report.order.index("sweep")


async def test_lot_filters_of_inactive_plans_are_not_refreshed() -> None:
    refresher = OrderedRefresher([])
    rig = make_rig(
        refresher=refresher,
        plans=(
            make_plan_protection(H1, symbol="BTCUSDT", state="PROTECTED"),
            make_plan_protection(
                H2, symbol="ETHUSDT", state="FLAT", stop_confirmed=False, first_fill=False
            ),
        ),
    )

    await rig.loop.tick(now_utc=NOW)

    assert [symbol for symbol, _ in refresher.calls] == ["BTCUSDT"]


async def test_no_refresher_means_no_background_phase() -> None:
    rig = make_rig()

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert "background" not in report.order
    assert RECONCILE_BACKGROUND_SKIPPED not in rig.event_types()


async def test_restricted_gate_makes_no_call_and_no_refresh() -> None:
    refresher = OrderedRefresher([])
    rig = make_rig(refresher=refresher, gate=restricted_gate())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_SKIPPED_GATE
    assert rig.adapter.calls == []
    assert refresher.calls == []
    assert report.order == ("gate",)
    assert RECONCILE_SKIPPED_GATE in rig.event_types()


async def test_gate_restricted_during_the_tick_stops_the_background_phase() -> None:
    order: list[str] = []
    refresher = OrderedRefresher(order)
    rig = make_rig(refresher=refresher, order=order)
    gate = rig.gate

    # The gate answers None for the first check of the tick and a restriction afterwards.
    answers: list[Any] = [None]

    def restriction() -> Any:
        if answers:
            return answers.pop(0)
        return GateRestriction(reason=RATE_LIMIT_PAUSE_429, until_utc=None, remaining_seconds=10)

    gate.restriction = restriction  # type: ignore[method-assign]

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert refresher.calls == []
    assert "background" not in report.order
    skipped = rig.payloads(RECONCILE_BACKGROUND_SKIPPED)
    assert skipped and skipped[0]["reason"] == "GATE_RESTRICTED"


@pytest.mark.parametrize(
    "refresher_kwargs",
    [{"result": False}, {"raises": RuntimeError("password=hunter2")}],
    ids=["returns_false", "raises"],
)
async def test_a_failing_refresher_never_fails_the_tick(refresher_kwargs: dict[str, Any]) -> None:
    refresher = OrderedRefresher([], **refresher_kwargs)
    rig = make_rig(refresher=refresher)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert sorted(symbol for symbol, _ in refresher.calls) == ["BTCUSDT", "ETHUSDT"]
    # No SAFE_MODE reason comes from the refresh, and the exception text is never journaled.
    assert "DB_FAILURE" not in rig.safe_mode.enter_calls
    assert "API_DEGRADATION" not in rig.safe_mode.enter_calls
    assert all("hunter2" not in e.payload_json for e in rig.journal.events)
    if "raises" in refresher_kwargs:
        failed = [
            p for p in rig.payloads(RECONCILE_ACTION_FAILED) if p["action"] == "lot_filter_refresh"
        ]
        assert failed and failed[0]["error_type"] == "RuntimeError"
        assert report.action_failures == ()


async def test_a_read_failed_tick_skips_the_background_phase() -> None:
    order: list[str] = []
    refresher = OrderedRefresher(order)
    rig = make_rig(refresher=refresher, order=order)
    rig.adapter.fail["snapshot_positions"] = RuntimeError("boom")

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome != TICK_COMPARED
    assert refresher.calls == []
    assert RECONCILE_READ_FAILED in rig.event_types()
