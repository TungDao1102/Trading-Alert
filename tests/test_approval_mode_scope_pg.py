"""SHADOW and DEMO approvals on one PostgreSQL database stay invisible to each other's sweep.

Plan 24-08 (research C-7, OQ-6; owner answer 24-01 Q8): the confirm sweeps judge every APPROVED
approval their store lists, so `PgShadowStores(db, confirm_mode=...)` writes a mode marker (the
journal event `APPROVAL_MODE_RECORDED`) in the same transaction as the PENDING row and lists only
approvals of its own mode. A row without a marker is a Phase 16 SHADOW row: the SHADOW scope lists
it, the DEMO and LIVE scopes never do.

Every test runs on a generated database cloned from the alembic-built template
(`tests/pg_support.py`). Without `TEST_DATABASE_URL` the tests skip locally and fail under
`TRADING_CI_STRICT=1`. No network.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult
from src.persistence.engine import make_sync_engine
from src.persistence.shadow_stores import (
    EVENT_APPROVAL_MODE_RECORDED,
    PgShadowStores,
    approval_mode_correlation,
    approval_mode_event,
)
from src.persistence.uow import OperationalDatabase

from tests.shadow_fakes import T0, USER_ID, make_shadow_plan, make_shadow_signal


@contextmanager
def two_processes(url: str) -> Iterator[tuple[Engine, dict[str | None, PgShadowStores]]]:
    """One engine per scope, as the paper and the live process would each hold one."""
    engine = make_sync_engine(url)
    try:
        db = OperationalDatabase(engine)
        yield (
            engine,
            {
                mode: PgShadowStores(db, confirm_mode=mode)
                for mode in (None, "SHADOW", "DEMO", "LIVE")
            },
        )
    finally:
        engine.dispose()


def approve(stores: PgShadowStores, n: int) -> Approval:
    """Insert plan n's rows and a PENDING approval through `stores`, then decide it APPROVED."""
    signal = make_shadow_signal(n)
    plan = make_shadow_plan(signal, plan_hash=f"{n:x}".rjust(64, "d"))
    stores.insert_signal(signal)
    stores.insert_trade_plan(plan)
    base: dict[str, Any] = {
        "approval_id": f"apr-{n}",
        "trade_plan_id": plan.trade_plan_id,
        "signal_id": signal.signal_id,
        "action": ApprovalAction.APPROVE,
        "approval_token_hash": hashlib.sha256(f"approval-token-{n}".encode()).hexdigest(),
        "requested_at_utc": T0,
        "request_hash": plan.plan_hash,
    }
    stores.insert_pending(
        Approval(**base, result=ApprovalResult.PENDING, status=ApprovalResult.PENDING, actor_id="")
    )
    approved = Approval(
        **base,
        result=ApprovalResult.APPROVED,
        status=ApprovalResult.APPROVED,
        acted_at_utc=T0,
        actor_id=str(USER_ID),
    )
    stores.save_atomic(approved, None)
    return approved


def ids(approvals: list[Approval]) -> list[str]:
    return sorted(a.approval_id for a in approvals)


def marker_payloads(engine: Engine, approval_id: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT payload_json FROM journal_events WHERE correlation_id = :c"),
            {"c": approval_mode_correlation(approval_id)},
        ).all()
    return [str(r[0]) for r in rows]


def test_a_shadow_and_a_demo_approval_on_one_database_are_invisible_to_each_other(
    pg_db: str,
) -> None:
    with two_processes(pg_db) as (_engine, stores):
        approve(stores["SHADOW"], 1)
        approve(stores["DEMO"], 2)

        assert ids(stores["SHADOW"].list_approved_approvals()) == ["apr-1"]
        assert ids(stores["DEMO"].list_approved_approvals()) == ["apr-2"]
        assert ids(stores["LIVE"].list_approved_approvals()) == []
        assert ids(stores[None].list_approved_approvals()) == ["apr-1", "apr-2"]


def test_the_marker_is_one_journal_event_with_the_mode_in_its_payload(pg_db: str) -> None:
    with two_processes(pg_db) as (engine, stores):
        approve(stores["DEMO"], 1)

        (event,) = stores["DEMO"].journal_for_correlation(approval_mode_correlation("apr-1"))
        assert event.event_type == EVENT_APPROVAL_MODE_RECORDED == "APPROVAL_MODE_RECORDED"
        assert event.correlation_id == "approval-mode:apr-1"
        assert event.approval_id == "apr-1"
        assert marker_payloads(engine, "apr-1") == ['{"mode":"DEMO"}']


def test_an_approval_without_a_marker_is_shadow_only(pg_db: str) -> None:
    """Every row written before the scope existed is a SHADOW row (T-24-21)."""
    with two_processes(pg_db) as (engine, stores):
        approve(stores[None], 1)  # an unscoped insert writes no marker
        assert marker_payloads(engine, "apr-1") == []

        assert ids(stores["SHADOW"].list_approved_approvals()) == ["apr-1"]
        assert ids(stores["DEMO"].list_approved_approvals()) == []
        assert ids(stores["LIVE"].list_approved_approvals()) == []


def test_an_unreadable_marker_is_listed_by_no_scoped_store(pg_db: str) -> None:
    with two_processes(pg_db) as (_engine, stores):
        approved = approve(stores[None], 1)
        good = approval_mode_event(approved, "DEMO")
        stores[None].record_journal(replace(good, payload_json='{"mode":"PAPER"}'))

        for mode in ("SHADOW", "DEMO", "LIVE"):
            assert stores[mode].list_approved_approvals() == []


def test_the_marker_and_the_pending_row_commit_or_roll_back_together(pg_db: str) -> None:
    with two_processes(pg_db) as (engine, stores):
        demo = stores["DEMO"]
        signal = make_shadow_signal(1)
        plan = make_shadow_plan(signal)
        demo.insert_signal(signal)
        demo.insert_trade_plan(plan)
        pending = Approval(
            approval_id="apr-1",
            trade_plan_id=plan.trade_plan_id,
            signal_id=signal.signal_id,
            action=ApprovalAction.APPROVE,
            approval_token_hash="a" * 64,
            requested_at_utc=T0,
            request_hash=plan.plan_hash,
            result=ApprovalResult.PENDING,
            status=ApprovalResult.PENDING,
            actor_id="",
        )
        real_append = demo._journal.append

        def append_then_fail(tx: Any, event: Any) -> None:
            real_append(tx, event)  # the marker row is in the open transaction ...
            raise RuntimeError("forced failure after the marker")

        demo._journal.append = append_then_fail  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="forced failure"):
            demo.insert_pending(pending)

        # ... and neither it nor the PENDING row survived.
        assert demo.get_approval("apr-1") is None
        assert marker_payloads(engine, "apr-1") == []

        demo._journal.append = real_append  # type: ignore[method-assign]
        demo.insert_pending(pending)
        assert demo.get_approval("apr-1") is not None
        assert marker_payloads(engine, "apr-1") == ['{"mode":"DEMO"}']


def test_replaying_insert_pending_writes_one_marker_and_no_error(pg_db: str) -> None:
    with two_processes(pg_db) as (engine, stores):
        approved = approve(stores["DEMO"], 1)
        pending = Approval(
            approval_id=approved.approval_id,
            trade_plan_id=approved.trade_plan_id,
            signal_id=approved.signal_id,
            action=approved.action,
            approval_token_hash=approved.approval_token_hash,
            requested_at_utc=approved.requested_at_utc,
            request_hash=approved.request_hash,
            result=ApprovalResult.PENDING,
            status=ApprovalResult.PENDING,
            actor_id="",
        )
        stores["DEMO"].insert_pending(pending)  # replay: a no-op on a decided row's identity

        assert marker_payloads(engine, "apr-1") == ['{"mode":"DEMO"}']
