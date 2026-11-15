"""The DEMO clear script closes stale plans the official way and nothing else."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from scripts import demo_clear
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    SystemStateKey,
    TradePlanStatus,
)
from src.live.approval_sender import make_open_demo_approvals_reader

from tests.test_live_approval_sender import NOW, DemoStores, FakeEntities, derive, new_source


class _Journal:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


class _StoresWithGet(DemoStores):
    def get_approval(self, approval_id: str) -> Approval | None:
        return self.approvals.get(approval_id)


def _open_card(stores: DemoStores, label: str) -> Any:
    request = derive(new_source(label))
    stores.insert_signal(request.signal)
    stores.insert_trade_plan(request.plan)
    stores.insert_pending(
        Approval(
            approval_id=f"apv-{label}",
            trade_plan_id=request.plan.trade_plan_id,
            signal_id=request.signal.signal_id,
            action=ApprovalAction.APPROVE,
            result=ApprovalResult.PENDING,
            status=ApprovalResult.PENDING,
            approval_token_hash="d" * 64,
            requested_at_utc=NOW,
            request_hash=request.plan.plan_hash,
        )
    )
    return request


def test_an_open_demo_plan_is_expired_journaled_and_no_longer_blocks() -> None:
    stores = _StoresWithGet(confirm_mode="DEMO")
    request = _open_card(stores, "stale")
    journal = _Journal()

    closed = demo_clear.clear_open_plans(
        shadow=stores,
        entities=FakeEntities(stores, []),
        journal=journal,
        now_utc=NOW + timedelta(minutes=1),
    )

    assert closed == [request.plan.trade_plan_id]
    assert stores.plans[request.plan.trade_plan_id].status is TradePlanStatus.EXPIRED
    assert [e.event_type for e in journal.events] == [demo_clear.EVENT_STALE_PLAN_CLEARED]
    assert make_open_demo_approvals_reader(stores)() == []


def test_nothing_open_means_nothing_closed_and_nothing_journaled() -> None:
    stores = _StoresWithGet(confirm_mode="DEMO")
    journal = _Journal()

    closed = demo_clear.clear_open_plans(
        shadow=stores, entities=FakeEntities(stores, []), journal=journal, now_utc=NOW
    )

    assert closed == [] and journal.events == []


class _SystemState:
    def __init__(self, in_safe_mode: bool) -> None:
        self.appended: list[dict[str, Any]] = []
        self._state = {"in_safe_mode": in_safe_mode}

    def latest(self, key: SystemStateKey) -> Any:
        assert key is SystemStateKey.SAFE_MODE
        return type("Row", (), {"state": self._state})()

    def append(self, key: SystemStateKey, state: dict[str, Any], *, now_utc: Any) -> None:
        self.appended.append(state)


def test_safe_mode_is_exited_with_the_clear_operator_only_when_it_was_set() -> None:
    set_state = _SystemState(in_safe_mode=True)
    assert demo_clear.exit_safe_mode(system_state=set_state, now_utc=NOW) is True
    assert set_state.appended[0]["in_safe_mode"] is False
    assert set_state.appended[0]["last_exit_operator_id"] == demo_clear.OPERATOR_ID

    clear_state = _SystemState(in_safe_mode=False)
    assert demo_clear.exit_safe_mode(system_state=clear_state, now_utc=NOW) is False
    assert clear_state.appended == []
