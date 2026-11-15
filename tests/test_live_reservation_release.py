"""The release of reservations that will never be placed (plan 24-37, finding F4; D095).

TEST_ONLY: in-memory store doubles (tests/support/live_store_set.py) and the composed process on
the Binance-semantics fake. No PostgreSQL, no network. The pure mappings under test
(`release_reason_for_plan`, `release_reason_for_placement_refusal`) are pinned by their own tests;
here they are driven through the sweep, the refusal hook and the composed process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.domain.enums import ExecutionIntentStatus, TradePlanStatus
from src.live.execution_service import (
    PlacementRefusal,
)
from src.live.reservation_release import (
    EVENT_RESERVATION_RELEASED,
    ReservationReleaser,
    ReservationSweepIncomplete,
)
from src.live.wiring import TASK_RESERVATION_SWEEP, TASK_SIGNAL_PUMP
from src.persistence.errors import StoreUnavailable
from src.risk.reservations import ReleaseReason, ReservationRequest, ReservationStatus

from tests.support.live_composed_rig import ComposedRig, make_composed_rig
from tests.support.live_rig import forbid_real_sleep
from tests.support.live_store_set import InMemoryReservations

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
EXPIRY = T0 + timedelta(minutes=15)
HASH = "a" * 64


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


class _Executor:
    """`StoreExecutor` without threads: the reads and writes run in place."""

    async def read(self, fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    async def write(self, fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)


class _Entities:
    def __init__(self) -> None:
        self.plans: dict[str, Any] = {}
        self.fail_for: set[str] = set()

    def put(self, plan_id: str, status: TradePlanStatus, expiry: datetime = EXPIRY) -> None:
        self.plans[plan_id] = SimpleNamespace(status=status, expiry_utc=expiry, plan_hash=HASH)

    def get_trade_plan(self, trade_plan_id: str) -> Any:
        if trade_plan_id in self.fail_for:
            raise StoreUnavailable("down")
        return self.plans.get(trade_plan_id)


class _Intents:
    def __init__(self) -> None:
        self.entries: dict[str, Any] = {}

    def get_entry(self, *, approval_id: str) -> Any:
        return self.entries.get(approval_id)


class _Journal:
    """`PgJournalStore.list_by_correlation` for the protection transitions of a plan."""

    def __init__(self) -> None:
        self.by_correlation: dict[str, list[Any]] = {}

    def transition(self, plan_hash: str, to: str) -> None:
        event = SimpleNamespace(
            event_type="PROTECTION_TRANSITION", payload_json=json.dumps({"to": to})
        )
        self.by_correlation.setdefault(f"protection_{plan_hash}", []).append(event)

    def list_by_correlation(self, correlation_id: str) -> list[Any]:
        return self.by_correlation.get(correlation_id, [])


@dataclass
class Harness:
    reservations: InMemoryReservations
    entities: _Entities
    intents: _Intents
    journal: _Journal
    rows: list[Any]
    releaser: ReservationReleaser

    def request(self, plan_id: str, *, reserved: bool = True) -> str:
        """Register (and, by default, reserve) a plan's risk; returns its approval id."""
        self.reservations.register_request(
            ReservationRequest(
                trade_plan_id=plan_id,
                plan_hash=HASH,
                symbol="BTCUSDT",
                position_side="LONG",
                quantity=Decimal("0.006"),
                realized_risk=Decimal("22.9"),
            ),
            now_utc=T0,
        )
        approval_id = f"approval-{plan_id}"
        if reserved:
            self.reservations.reserve_in(
                None,
                approval=SimpleNamespace(trade_plan_id=plan_id, approval_id=approval_id),  # type: ignore[arg-type]
                now_utc=T0,
                daily_loss_quote=None,
                parameter_set=None,
            )
        return approval_id

    def status(self, plan_id: str) -> tuple[str, ReleaseReason | None]:
        record = self.reservations.get(plan_id)
        assert record is not None
        return record.status.value, record.release_reason


@pytest.fixture
def harness() -> Harness:
    rows: list[Any] = []

    async def record(event: Any) -> None:
        rows.append(event)

    reservations, entities, intents = InMemoryReservations(), _Entities(), _Intents()
    journal = _Journal()
    releaser = ReservationReleaser(
        reservations=reservations,
        entities=entities,
        intents=intents,
        events_for_correlation=journal.list_by_correlation,
        executor=_Executor(),
        record=record,
    )
    return Harness(reservations, entities, intents, journal, rows, releaser)


# --------------------------------------------------------------------------- #
# The sweep: release_reason_for_plan over the unplaced rows.
# --------------------------------------------------------------------------- #


async def test_an_approved_plan_that_was_never_placed_is_released_when_its_expiry_passes(
    harness: Harness,
) -> None:
    harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)

    early = await harness.releaser.sweep_once(EXPIRY - timedelta(seconds=1))
    assert (early.examined, early.released) == (1, 0), "a plan that can still be confirmed stays"
    assert harness.status("p1") == ("RESERVED", None)

    report = await harness.releaser.sweep_once(EXPIRY)
    assert report.released == 1
    assert harness.status("p1") == ("RELEASED", ReleaseReason.PLAN_EXPIRED)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (TradePlanStatus.EXPIRED, ReleaseReason.PLAN_EXPIRED),
        (TradePlanStatus.INVALIDATED, ReleaseReason.PLAN_INVALIDATED),
        (TradePlanStatus.SUPERSEDED, ReleaseReason.PLAN_SUPERSEDED),
    ],
)
async def test_a_terminal_plan_status_releases_before_the_expiry_time(
    harness: Harness, status: TradePlanStatus, reason: ReleaseReason
) -> None:
    harness.request("p1")
    harness.entities.put("p1", status)
    await harness.releaser.sweep_once(T0 + timedelta(seconds=1))
    assert harness.status("p1") == ("RELEASED", reason)


async def test_a_requested_row_of_an_expired_plan_is_released_too(harness: Harness) -> None:
    harness.request("p1", reserved=False)
    harness.entities.put("p1", TradePlanStatus.APPROVAL_PENDING)
    await harness.releaser.sweep_once(EXPIRY + timedelta(seconds=1))
    assert harness.status("p1") == ("RELEASED", ReleaseReason.PLAN_EXPIRED)


async def test_the_reservation_of_a_live_entry_is_never_released_by_the_plan_expiry(
    harness: Harness,
) -> None:
    """An executed plan stays APPROVED (D051 item i): its entry may be live. The plan expiry must
    not release it, even a day later; only the entry or position outcome does."""
    approval_id = harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)
    harness.intents.entries[approval_id] = SimpleNamespace(
        intent_status=ExecutionIntentStatus.ACKED
    )
    harness.journal.transition(HASH, "PROTECTED")
    report = await harness.releaser.sweep_once(EXPIRY + timedelta(days=1))
    assert (report.consumed_skipped, report.released) == (1, 0)
    assert harness.status("p1") == ("RESERVED", None)


@pytest.mark.parametrize("status", [ExecutionIntentStatus.UNKNOWN, ExecutionIntentStatus.SENT])
async def test_an_entry_that_may_still_fill_stays_counted(
    harness: Harness, status: ExecutionIntentStatus
) -> None:
    approval_id = harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)
    harness.intents.entries[approval_id] = SimpleNamespace(intent_status=status)
    await harness.releaser.sweep_once(EXPIRY + timedelta(days=1))
    assert harness.status("p1") == ("RESERVED", None)


async def test_a_rejected_entry_releases_as_entry_rejected(harness: Harness) -> None:
    approval_id = harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)
    harness.intents.entries[approval_id] = SimpleNamespace(
        intent_status=ExecutionIntentStatus.REJECTED
    )
    report = await harness.releaser.sweep_once(T0 + timedelta(seconds=1))
    assert report.released_executed == 1
    assert harness.status("p1") == ("RELEASED", ReleaseReason.ENTRY_REJECTED)
    (row,) = harness.rows
    assert json.loads(row.payload_json) == {"reason": "ENTRY_REJECTED", "source": "SWEEP_EXECUTED"}


@pytest.mark.parametrize(
    ("ended", "reason"),
    [
        ("FLAT", ReleaseReason.POSITION_CLOSED),
        ("ENTRY_ENDED_NO_FILL", ReleaseReason.ENTRY_ENDED_NO_FILL),
    ],
)
async def test_an_ended_plan_releases_a_reserved_row_through_placed(
    harness: Harness, ended: str, reason: ReleaseReason
) -> None:
    """RESERVED to PLACED to RELEASED in one pass (the store permits both reasons only from
    PLACED or OPEN). The journal, not the coordinator, says the plan ended, so a plan that ended
    before a restart is released too."""
    approval_id = harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)
    harness.intents.entries[approval_id] = SimpleNamespace(
        intent_status=ExecutionIntentStatus.ACKED
    )
    harness.journal.transition(HASH, "PROTECTED")
    await harness.releaser.sweep_once(T0 + timedelta(minutes=1))
    assert harness.status("p1") == ("RESERVED", None), "a live protection state is not an end"

    harness.journal.transition(HASH, ended)
    report = await harness.releaser.sweep_once(T0 + timedelta(minutes=2))
    assert report.released_executed == 1
    assert harness.status("p1") == ("RELEASED", reason)
    assert harness.reservations.get("p1").placed_at_utc == T0 + timedelta(minutes=2)  # type: ignore[union-attr]
    assert harness.reservations.list_counted() == ()


async def test_a_placed_or_open_row_of_an_ended_plan_is_released_without_a_second_advance(
    harness: Harness,
) -> None:
    for plan_id, advance in (("p1", ("placed",)), ("p2", ("placed", "open"))):
        approval_id = harness.request(plan_id)
        harness.entities.put(plan_id, TradePlanStatus.APPROVED)
        harness.intents.entries[approval_id] = SimpleNamespace(
            intent_status=ExecutionIntentStatus.ACKED
        )
        harness.reservations.mark_placed(plan_id, now_utc=T0)
        if "open" in advance:
            harness.reservations.mark_open(plan_id, now_utc=T0)
    harness.journal.transition(HASH, "FLAT")
    report = await harness.releaser.sweep_once(T0 + timedelta(minutes=2))
    assert report.released_executed == 2
    assert harness.status("p1")[1] is ReleaseReason.POSITION_CLOSED
    assert harness.status("p2")[1] is ReleaseReason.POSITION_CLOSED


async def test_a_placed_row_without_an_entry_intent_is_a_skip_never_forced(
    harness: Harness,
) -> None:
    harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)
    harness.reservations.mark_placed("p1", now_utc=T0)
    report = await harness.releaser.sweep_once(EXPIRY + timedelta(days=1))
    assert (report.released, report.conflicts) == (0, 1)
    assert harness.status("p1") == ("PLACED", None)


async def test_the_sweep_is_idempotent_and_journals_one_row_with_codes_only(
    harness: Harness,
) -> None:
    harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)
    await harness.releaser.sweep_once(EXPIRY)
    again = await harness.releaser.sweep_once(EXPIRY + timedelta(seconds=30))
    assert again.examined == 0
    (row,) = harness.rows
    assert row.event_type == EVENT_RESERVATION_RELEASED
    assert row.trade_plan_id == "p1"
    assert json.loads(row.payload_json) == {"reason": "PLAN_EXPIRED", "source": "SWEEP"}


async def test_a_failing_read_keeps_that_row_counted_and_the_others_are_still_released(
    harness: Harness,
) -> None:
    for plan_id in ("p1", "p2"):
        harness.request(plan_id)
        harness.entities.put(plan_id, TradePlanStatus.APPROVED)
    harness.entities.fail_for.add("p1")
    with pytest.raises(ReservationSweepIncomplete):
        await harness.releaser.sweep_once(EXPIRY)
    assert harness.status("p1") == ("RESERVED", None), "fail closed: still counted"
    assert harness.status("p2") == ("RELEASED", ReleaseReason.PLAN_EXPIRED)


async def test_a_reservation_whose_plan_cannot_be_found_stays_counted_and_is_reported(
    harness: Harness,
) -> None:
    harness.request("p1")
    with pytest.raises(ReservationSweepIncomplete):
        await harness.releaser.sweep_once(EXPIRY + timedelta(days=1))
    assert harness.status("p1") == ("RESERVED", None)


# --------------------------------------------------------------------------- #
# The refusal hook: release_reason_for_placement_refusal.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "code", ["PLAN_STATUS_INVALID", "PLAN_INVALIDATED_BEFORE_PLACEMENT", "VALIDITY_TOO_SHORT"]
)
async def test_a_final_refusal_releases_the_reservation_at_once(
    harness: Harness, code: str
) -> None:
    approval_id = harness.request("p1")
    released = await harness.releaser.release_refused(approval_id, "p1", code, T0)
    assert released
    assert harness.status("p1") == ("RELEASED", ReleaseReason.PLACEMENT_REFUSED)
    (row,) = harness.rows
    assert json.loads(row.payload_json) == {"reason": "PLACEMENT_REFUSED", "source": "REFUSAL"}


@pytest.mark.parametrize(
    "code", ["SAFE_MODE_ACTIVE", "DISABLED", "LIMITS_NOT_CONFIGURED", "STALE_SETUP", "anything"]
)
async def test_a_non_final_refusal_keeps_the_reservation_counted_until_the_expiry(
    harness: Harness, code: str
) -> None:
    """The documented, conservative rule: SAFE_MODE can clear and the owner may press again."""
    approval_id = harness.request("p1")
    harness.entities.put("p1", TradePlanStatus.APPROVED)
    assert not await harness.releaser.release_refused(approval_id, "p1", code, T0)
    assert harness.status("p1") == ("RESERVED", None)
    assert harness.rows == []
    await harness.releaser.sweep_once(EXPIRY)
    assert harness.status("p1") == ("RELEASED", ReleaseReason.PLAN_EXPIRED)


async def test_a_final_refusal_of_a_consumed_plan_releases_nothing(harness: Harness) -> None:
    approval_id = harness.request("p1")
    harness.intents.entries[approval_id] = SimpleNamespace(intent_status=ExecutionIntentStatus.SENT)
    assert not await harness.releaser.release_refused(approval_id, "p1", "VALIDITY_TOO_SHORT", T0)
    assert harness.status("p1") == ("RESERVED", None)


async def test_a_final_refusal_of_a_row_in_another_status_is_a_skip_not_a_forced_release(
    harness: Harness,
) -> None:
    approval_id = harness.request("p1")
    harness.reservations.mark_placed("p1", now_utc=T0)
    assert not await harness.releaser.release_refused(approval_id, "p1", "VALIDITY_TOO_SHORT", T0)
    assert harness.status("p1") == ("PLACED", None)


# --------------------------------------------------------------------------- #
# The execution service hands a refused CONFIRM to the hook.
# --------------------------------------------------------------------------- #


def _service(inputs: Any, calls: list[tuple[Any, ...]], *, failing: bool = False) -> Any:
    import asyncio

    from src.live.execution_service import ExecutionService
    from src.live.order_index import ClientIdIndex

    async def hook(*args: Any) -> None:
        calls.append(args)
        if failing:
            raise RuntimeError("release down")

    class _Journal:
        def record(self, event: Any) -> None:
            return None

    return ExecutionService(
        loop=asyncio.get_running_loop(),
        token_for=lambda _approval_id: "raw-token",
        inputs=inputs,
        adapter=object(),  # type: ignore[arg-type]
        safe_mode_controller=object(),
        journal=_Journal(),
        enablement=object(),
        intent_store=object(),  # type: ignore[arg-type]
        index=ClientIdIndex(),
        clock=lambda: T0,
        authorized_chat_id=1,
        on_refused=hook,
    )


def _approval_and_plan() -> tuple[Any, Any]:
    approval = SimpleNamespace(approval_id="ap-1", signal_id="sig-1")
    plan = SimpleNamespace(trade_plan_id="plan-1", plan_hash=HASH)
    return approval, plan


class _Inputs:
    def __init__(self, result: Any) -> None:
        self._result = result

    async def for_plan(self, approval: Any, plan: Any, confirmed_at: datetime) -> Any:
        return self._result


async def test_a_producer_refusal_reaches_the_release_hook_with_its_reason() -> None:
    calls: list[tuple[Any, ...]] = []
    service = _service(_Inputs(PlacementRefusal(reason="VALIDITY_TOO_SHORT")), calls)
    approval, plan = _approval_and_plan()
    await service._place(approval, plan, T0)
    assert calls == [("ap-1", "plan-1", "VALIDITY_TOO_SHORT", T0)]


async def test_a_manager_no_trade_reaches_the_release_hook_but_an_entry_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.execution.manager import ExecutionOutcome
    from src.live import execution_service

    resolved = SimpleNamespace(
        now_utc=T0,
        expiry_utc=EXPIRY,
        approval_strategy_version="s",
        approval_parameter_set_id="p",
        approval_parameter_set_hash="b" * 64,
        risk_kwargs={},
        gate_kwargs={},
        live_context=SimpleNamespace(signal=SimpleNamespace(symbol="BTCUSDT")),
    )
    outcomes = [ExecutionOutcome(is_no_trade=True, reason_code="VALIDITY_TOO_SHORT")]

    async def fake_execute(**_kwargs: Any) -> ExecutionOutcome:
        return outcomes[0]

    monkeypatch.setattr(execution_service, "execute_approved_plan", fake_execute)
    calls: list[tuple[Any, ...]] = []
    service = _service(_Inputs(resolved), calls)
    approval, plan = _approval_and_plan()
    await service._place(approval, plan, T0)
    assert calls == [("ap-1", "plan-1", "VALIDITY_TOO_SHORT", T0)]

    outcomes[0] = ExecutionOutcome(is_no_trade=False, reason_code="OK")
    await service._place(approval, plan, T0)
    assert len(calls) == 1, "a placed entry is not a refusal"


async def test_a_failing_release_hook_never_breaks_the_placement_task() -> None:
    calls: list[tuple[Any, ...]] = []
    service = _service(_Inputs(PlacementRefusal(reason="VALIDITY_TOO_SHORT")), calls, failing=True)
    approval, plan = _approval_and_plan()
    await service._place(approval, plan, T0)  # does not raise
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# The composed process: the scheduler task and the real stores' lifecycle.
# --------------------------------------------------------------------------- #


async def _approved(rig: ComposedRig) -> tuple[Any, Any, str]:
    wiring = await rig.prepare()
    request = await rig.derive_request()
    (pump,) = [s for s in wiring.specs if s.name == TASK_SIGNAL_PUMP]
    await pump.run()
    short_id = next(iter(rig.memory.shadow.mappings))
    assert (await rig.press("APR", short_id, query_id="q-apr")).ok
    return wiring, request, short_id


def _sweep_spec(wiring: Any) -> Any:
    (spec,) = [s for s in wiring.specs if s.name == TASK_RESERVATION_SWEEP]
    return spec


async def test_the_composed_sweep_releases_an_approved_plan_that_was_refused_and_expired(
    tmp_path: Path,
) -> None:
    """F4 on the composed process: SAFE_MODE refuses the CONFIRM (not a final refusal), the
    reservation stays counted, and the scheduler task releases it when the plan expires."""
    rig = make_composed_rig(tmp_path)
    wiring, request, short_id = await _approved(rig)
    wiring.safe_mode.enter_safe_mode(reason="DEMO_SMOKE_DRILL", now_utc=rig.clock.now())
    await rig.clock.advance(30)
    rig.set_prices()
    await rig.press("CNF", short_id, query_id="q-cnf")
    await wiring.service.drain()
    assert rig.fake.calls_to("place_entry") == []
    record = rig.memory.reservations.get(request.plan.trade_plan_id)
    assert record is not None and record.status is ReservationStatus.RESERVED

    spec = _sweep_spec(wiring)
    await spec.run()
    assert rig.memory.reservations.get(request.plan.trade_plan_id).status is (  # type: ignore[union-attr]
        ReservationStatus.RESERVED
    ), "the plan can still be confirmed"

    await rig.clock.advance((request.plan.expiry_utc - rig.clock.now()).total_seconds() + 1)
    await spec.run()
    released = rig.memory.reservations.get(request.plan.trade_plan_id)
    assert released is not None
    assert (released.status, released.release_reason) == (
        ReservationStatus.RELEASED,
        ReleaseReason.PLAN_EXPIRED,
    )
    assert rig.memory.reservations.list_counted() == ()
    (row,) = rig.memory.journal.by_type(EVENT_RESERVATION_RELEASED)
    assert json.loads(row.payload_json) == {"reason": "PLAN_EXPIRED", "source": "SWEEP"}


async def test_the_composed_sweep_leaves_a_live_entry_alone_and_releases_it_when_it_ends(
    tmp_path: Path,
) -> None:
    """The reservation of a placed entry is not the plan expiry's business. It is released when
    the journal says the plan ended (finding F5: before plan 24-37 nothing ever released it)."""
    rig = make_composed_rig(tmp_path)
    wiring, request, short_id = await _approved(rig)
    await rig.clock.advance(30)
    rig.set_prices()
    assert (await rig.press("CNF", short_id, query_id="q-cnf")).ok
    await wiring.service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1
    await rig.clock.advance((request.plan.expiry_utc - rig.clock.now()).total_seconds() + 60)
    await _sweep_spec(wiring).run()
    record = rig.memory.reservations.get(request.plan.trade_plan_id)
    assert record is not None and record.status is ReservationStatus.RESERVED
    assert rig.memory.journal.by_type(EVENT_RESERVATION_RELEASED) == []

    # The entry ends without a fill: the coordinator's own transition row is what the sweep reads.
    from src.domain.journal import JournalEvent

    rig.memory.journal.record(
        JournalEvent(
            journal_event_id="test-ended",
            occurred_at_utc=rig.clock.now(),
            event_type="PROTECTION_TRANSITION",
            entity_type="Protection",
            entity_id=request.plan.plan_hash,
            correlation_id=f"protection_{request.plan.plan_hash}",
            payload_json=json.dumps({"to": "ENTRY_ENDED_NO_FILL"}),
        )
    )
    await _sweep_spec(wiring).run()
    record = rig.memory.reservations.get(request.plan.trade_plan_id)
    assert record is not None
    assert (record.status, record.release_reason) == (
        ReservationStatus.RELEASED,
        ReleaseReason.ENTRY_ENDED_NO_FILL,
    )
