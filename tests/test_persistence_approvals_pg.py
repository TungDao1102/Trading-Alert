"""PostgreSQL approval store: DB-enforced single decision and race-safe replay (Phase 17-09).

`PgApprovalStore` is the durable implementation behind the Telegram callback callables
(`LookupByTokenHash`, `SaveApproval`, `SaveAtomic`, `LookupByShortId`). The behaviors pinned
here (APRV-02, F-404, D-06, D-17, D-26, research C15/C16):

  - round trip through the approval mappers; `insert_pending` is idempotent, a reused token
    hash is a `RowConflict`;
  - `save_atomic` decides a PENDING approval and records the short-id mapping in ONE
    transaction; a second decision raises `ApprovalAlreadyDecided` carrying the stored row;
  - one decision per plan: deciding APPROVE then the sibling SKIP row raises
    `ApprovalAlreadyDecided`, the SKIP row stays PENDING, and raw SQL cannot bypass it;
  - a mapping that would rebind a short id raises `ShortIdRebindingRefused` and rolls the
    decision back;
  - two threads, each with its own engine, deciding the same approval: exactly one wins;
  - `resolve_callback` and `dispatch_callback` work end to end against PostgreSQL.

Every test runs on a generated `t17_<hex>_test` database cloned from an alembic-built
template (`tests/pg_support.py`).
"""

from __future__ import annotations

import random
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.adapters.telegram_callbacks import (
    CallbackKind,
    ParsedCallback,
    dispatch_callback,
)
from src.approval.binding import ApprovalRejected, Callback
from src.approval.mapping import ShortIdMapping, derive_short_id, make_short_id_mapping
from src.approval.replay import ApprovalAlreadyDecided, resolve_callback
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.db.mappers import short_id_mapping_from_row
from src.db.models import ShortIdMappingRow
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalConsumptionStatus,
    ApprovalResult,
    OrderRole,
    RejectionReason,
)
from src.execution.order_ids import derive_client_order_id
from src.persistence.approvals import PgApprovalStore
from src.persistence.engine import make_sync_engine
from src.persistence.errors import (
    ParentRowMissing,
    PrecisionError,
    RowConflict,
    ShortIdRebindingRefused,
)
from src.persistence.execution_state import PgExecutionStateStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import (
    T0,
    T1,
    expect_db_error,
    hexid,
    insert_and_commit,
    make_approval,
    make_plan,
    make_signal,
)

ONE_DECIDED = "uq_approvals_one_decided_per_plan"
CHAT_ID = 4242
PLAN_HASH = "9" * 64
PARAM_HASH = "b" * 64
T_DECIDED = T0 + timedelta(minutes=5)
T_CALLBACK = T0 + timedelta(minutes=6)
SIGNAL_ID = hexid(1)
PLAN_ID = hexid(0x1001)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> OperationalDatabase:
    return OperationalDatabase(engine)


@pytest.fixture
def store(db: OperationalDatabase) -> PgApprovalStore:
    return PgApprovalStore(db)


@pytest.fixture
def seeded(engine: Engine) -> Engine:
    """Signal 1 and trade plan 1 committed (parents first)."""
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))
    return engine


def _pending(
    n: int = 1,
    *,
    plan_n: int = 1,
    signal_n: int = 1,
    action: ApprovalAction = ApprovalAction.APPROVE,
    raw_token: str | None = None,
    **overrides: Any,
) -> Approval:
    token_hash = token_hash_of(raw_token) if raw_token is not None else hexid(0x3000 + n)
    values: dict[str, Any] = {
        "approval_id": hexid(0x2000 + n),
        "trade_plan_id": hexid(0x1000 + plan_n),
        "signal_id": hexid(signal_n),
        "action": action,
        "result": ApprovalResult.PENDING,
        "status": ApprovalResult.PENDING,
        "approval_token_hash": token_hash,
        "requested_at_utc": T0,
        "acted_at_utc": None,
        "actor_id": "operator",
        "telegram_message_id": None,
        "request_hash": PLAN_HASH,
    }
    values.update(overrides)
    return Approval(**values)


def _decided(approval: Approval, result: ApprovalResult, at: datetime = T_DECIDED) -> Approval:
    return replace(approval, result=result, status=result, acted_at_utc=at)


def _mapping(signal_n: int = 1, plan_n: int = 1, created: datetime = T0) -> ShortIdMapping:
    return make_short_id_mapping(
        signal_id=hexid(signal_n), trade_plan_id=hexid(0x1000 + plan_n), created_at_utc=created
    )


def _approval_status(engine: Engine, approval_id: str) -> str:
    with Session(engine) as session:
        return str(
            session.execute(
                text("SELECT status FROM approvals WHERE approval_id = :id"), {"id": approval_id}
            ).scalar_one()
        )


def _count(engine: Engine, table: str) -> int:
    with Session(engine) as session:
        return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


# --------------------------------------------------------------------------- #
# insert_pending / lookups.
# --------------------------------------------------------------------------- #


def test_insert_pending_round_trips_by_token_hash_and_id(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1, telegram_message_id="77")
    store.insert_pending(approval)

    assert store.lookup_by_token_hash(approval.approval_token_hash) == approval
    assert store.get(approval.approval_id) == approval
    assert store.lookup_by_token_hash("0" * 64) is None
    assert store.get(hexid(0x9999)) is None


def test_insert_pending_replay_is_a_noop(seeded: Engine, store: PgApprovalStore) -> None:
    approval = _pending(1)
    store.insert_pending(approval)
    store.insert_pending(approval)

    assert _count(seeded, "approvals") == 1


def test_insert_pending_replay_after_decision_does_not_rewrite_the_decision(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1)
    store.insert_pending(approval)
    store.save_atomic(_decided(approval, ApprovalResult.APPROVED), None)

    store.insert_pending(approval)  # the sender replays its own request

    stored = store.get(approval.approval_id)
    assert stored is not None
    assert stored.status is ApprovalResult.APPROVED


def test_insert_pending_with_reused_token_hash_is_a_row_conflict(
    seeded: Engine, store: PgApprovalStore
) -> None:
    first = _pending(1)
    store.insert_pending(first)
    other = _pending(2, approval_token_hash=first.approval_token_hash)

    with pytest.raises(RowConflict):
        store.insert_pending(other)
    assert _count(seeded, "approvals") == 1


def test_insert_pending_same_id_different_request_is_a_row_conflict(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1)
    store.insert_pending(approval)

    with pytest.raises(RowConflict, match="request_hash"):
        store.insert_pending(replace(approval, request_hash="1" * 64))


def test_insert_pending_requires_pending_status(seeded: Engine, store: PgApprovalStore) -> None:
    with pytest.raises(ValueError, match="PENDING"):
        store.insert_pending(_decided(_pending(1), ApprovalResult.APPROVED))


def test_insert_pending_without_parents_is_parent_row_missing(
    engine: Engine, store: PgApprovalStore
) -> None:
    with pytest.raises(ParentRowMissing):
        store.insert_pending(_pending(1))


# --------------------------------------------------------------------------- #
# approved_quantity (19-REVIEW WR-01, D078).
# --------------------------------------------------------------------------- #


def _stored_quantity(engine: Engine, approval_id: str) -> Decimal | None:
    with Session(engine) as session:
        value = session.execute(
            text("SELECT approved_quantity FROM approvals WHERE approval_id = :id"),
            {"id": approval_id},
        ).scalar_one()
    return None if value is None else Decimal(value)


def test_insert_pending_persists_the_approved_quantity(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1, approved_quantity=Decimal("2.415"))
    store.insert_pending(approval)

    by_token = store.lookup_by_token_hash(approval.approval_token_hash)
    assert by_token is not None
    assert by_token.approved_quantity == Decimal("2.415")
    assert store.get(approval.approval_id) == approval
    assert _stored_quantity(seeded, approval.approval_id) == Decimal("2.415")


def test_insert_pending_replay_with_the_same_quantity_is_a_noop(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1, approved_quantity=Decimal("2.415"))
    store.insert_pending(approval)
    store.insert_pending(replace(approval, approved_quantity=Decimal("2.4150")))

    assert _count(seeded, "approvals") == 1


def test_insert_pending_replay_with_a_different_quantity_is_a_row_conflict(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1, approved_quantity=Decimal("2.415"))
    store.insert_pending(approval)

    with pytest.raises(RowConflict, match="approved_quantity"):
        store.insert_pending(replace(approval, approved_quantity=Decimal("2.416")))
    with pytest.raises(RowConflict, match="approved_quantity"):
        store.insert_pending(replace(approval, approved_quantity=None))
    assert _stored_quantity(seeded, approval.approval_id) == Decimal("2.415")


def test_insert_pending_refuses_more_than_18_fractional_digits_and_never_rounds(
    seeded: Engine, store: PgApprovalStore
) -> None:
    too_precise = Decimal("1.0000000000000000019")  # 19 fractional digits
    with pytest.raises(PrecisionError, match="approved_quantity"):
        store.insert_pending(_pending(1, approved_quantity=too_precise))
    assert _count(seeded, "approvals") == 0

    exact = Decimal("1.000000000000000001")  # 18 fractional digits survive
    store.insert_pending(_pending(1, approved_quantity=exact))
    assert _stored_quantity(seeded, hexid(0x2001)) == exact


def test_a_decision_write_never_changes_the_stored_quantity(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1, approved_quantity=Decimal("2.415"))
    store.insert_pending(approval)
    inflated = replace(_decided(approval, ApprovalResult.APPROVED), approved_quantity=Decimal("99"))

    store.save_atomic(inflated, None)

    assert _stored_quantity(seeded, approval.approval_id) == Decimal("2.415")
    stored = store.get(approval.approval_id)
    assert stored is not None
    assert stored.status is ApprovalResult.APPROVED
    assert stored.approved_quantity == Decimal("2.415")


def test_a_row_written_without_a_quantity_reads_back_none(
    seeded: Engine, store: PgApprovalStore
) -> None:
    insert_and_commit(seeded, make_approval(1, 1, 1))

    stored = store.get(hexid(0x2001))
    assert stored is not None
    assert stored.approved_quantity is None


# --------------------------------------------------------------------------- #
# save_atomic: decision + mapping in one transaction.
# --------------------------------------------------------------------------- #


def test_save_atomic_commits_decision_and_mapping(seeded: Engine, store: PgApprovalStore) -> None:
    approval = _pending(1)
    store.insert_pending(approval)
    decided = _decided(approval, ApprovalResult.APPROVED)
    mapping = _mapping()

    store.save_atomic(decided, mapping)

    assert store.get(approval.approval_id) == decided
    assert store.lookup_by_short_id(mapping.short_id) == (mapping.signal_id, mapping.trade_plan_id)
    assert store.lookup_by_short_id("f" * 32) is None


def test_save_delegates_to_save_atomic_without_mapping(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1)
    store.insert_pending(approval)

    store.save(_decided(approval, ApprovalResult.SKIPPED))

    assert _approval_status(seeded, approval.approval_id) == "SKIPPED"
    assert _count(seeded, "short_id_mapping") == 0


def test_save_atomic_rejects_a_pending_approval(seeded: Engine, store: PgApprovalStore) -> None:
    approval = _pending(1)
    store.insert_pending(approval)

    with pytest.raises(ValueError, match="decided"):
        store.save_atomic(approval, None)


def test_save_atomic_on_a_missing_row_is_a_row_conflict(
    seeded: Engine, store: PgApprovalStore
) -> None:
    with pytest.raises(RowConflict):
        store.save_atomic(_decided(_pending(1), ApprovalResult.APPROVED), _mapping())
    assert _count(seeded, "short_id_mapping") == 0


def test_second_decision_for_the_same_approval_raises_already_decided(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1)
    store.insert_pending(approval)
    first = _decided(approval, ApprovalResult.APPROVED)
    store.save_atomic(first, _mapping())

    later = _decided(approval, ApprovalResult.APPROVED, T_DECIDED + timedelta(minutes=1))
    with pytest.raises(ApprovalAlreadyDecided) as excinfo:
        store.save_atomic(later, _mapping())

    assert excinfo.value.existing == first


def test_expired_status_decision_is_persisted(seeded: Engine, store: PgApprovalStore) -> None:
    approval = _pending(1)
    store.insert_pending(approval)

    store.save_atomic(_decided(approval, ApprovalResult.EXPIRED), None)

    assert _approval_status(seeded, approval.approval_id) == "EXPIRED"


# --------------------------------------------------------------------------- #
# One decision per plan (Pitfall 13, D-26).
# --------------------------------------------------------------------------- #


def test_sibling_skip_row_cannot_decide_after_approve_won(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approve = _pending(1)
    skip = _pending(2, action=ApprovalAction.SKIP_USER)
    store.insert_pending(approve)
    store.insert_pending(skip)
    approved = _decided(approve, ApprovalResult.APPROVED)
    store.save_atomic(approved, _mapping())

    with pytest.raises(ApprovalAlreadyDecided) as excinfo:
        store.save_atomic(_decided(skip, ApprovalResult.SKIPPED), _mapping())

    assert excinfo.value.existing == approved
    assert _approval_status(seeded, skip.approval_id) == "PENDING"
    assert _approval_status(seeded, approve.approval_id) == "APPROVED"


def test_raw_sql_cannot_decide_a_second_approval_of_the_plan(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approve = _pending(1)
    skip = _pending(2, action=ApprovalAction.SKIP_USER)
    store.insert_pending(approve)
    store.insert_pending(skip)
    store.save_atomic(_decided(approve, ApprovalResult.APPROVED), None)

    with expect_db_error("23505") as info, Session(seeded) as session, session.begin():
        session.execute(
            text(
                "UPDATE approvals SET status = 'SKIPPED', result = 'SKIPPED', "
                "acted_at_utc = now() WHERE approval_id = :id"
            ),
            {"id": skip.approval_id},
        )

    assert info.constraint == ONE_DECIDED
    assert _approval_status(seeded, skip.approval_id) == "PENDING"


# --------------------------------------------------------------------------- #
# Short-id mapping: insert-then-verify (research C16).
# --------------------------------------------------------------------------- #


def test_record_short_id_mapping_same_pair_is_a_noop(
    seeded: Engine, store: PgApprovalStore
) -> None:
    store.record_short_id_mapping(_mapping(created=T0))
    store.record_short_id_mapping(_mapping(created=T1))  # replay with a new send time

    assert _count(seeded, "short_id_mapping") == 1
    with Session(seeded) as session:
        row = session.get(ShortIdMappingRow, derive_short_id(SIGNAL_ID))
        assert row is not None
        assert short_id_mapping_from_row(row) == _mapping(created=T0)


def test_record_short_id_mapping_refuses_to_rebind_to_another_plan(
    engine: Engine, store: PgApprovalStore
) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1), make_plan(2, 1))
    store.record_short_id_mapping(_mapping(plan_n=1))

    with pytest.raises(ShortIdRebindingRefused):
        store.record_short_id_mapping(_mapping(plan_n=2))

    assert store.lookup_by_short_id(derive_short_id(SIGNAL_ID)) == (SIGNAL_ID, PLAN_ID)


def test_save_atomic_rebinding_rolls_the_decision_back(
    engine: Engine, store: PgApprovalStore
) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1), make_plan(2, 1))
    approval = _pending(1)
    store.insert_pending(approval)
    store.record_short_id_mapping(_mapping(plan_n=1))

    with pytest.raises(ShortIdRebindingRefused):
        store.save_atomic(_decided(approval, ApprovalResult.APPROVED), _mapping(plan_n=2))

    assert _approval_status(engine, approval.approval_id) == "PENDING"
    assert store.lookup_by_short_id(derive_short_id(SIGNAL_ID)) == (SIGNAL_ID, PLAN_ID)


def test_save_atomic_with_the_same_mapping_again_commits(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1)
    store.insert_pending(approval)
    store.record_short_id_mapping(_mapping())

    store.save_atomic(_decided(approval, ApprovalResult.APPROVED), _mapping(created=T1))

    assert _approval_status(seeded, approval.approval_id) == "APPROVED"
    assert _count(seeded, "short_id_mapping") == 1


# --------------------------------------------------------------------------- #
# Cross-process race (D-17, D-26).
# --------------------------------------------------------------------------- #


def test_two_threads_deciding_one_approval_produce_exactly_one_decision(
    pg_db: str, seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1)
    store.insert_pending(approval)
    decided = _decided(approval, ApprovalResult.APPROVED)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    guard = threading.Lock()

    def worker() -> None:
        engine = make_sync_engine(pg_db)
        try:
            racer = PgApprovalStore(OperationalDatabase(engine))
            barrier.wait(timeout=30)
            try:
                racer.save_atomic(decided, _mapping())
                result = "won"
            except ApprovalAlreadyDecided as exc:
                result = "lost" if exc.existing == decided else "lost-with-wrong-row"
        except Exception as exc:  # pragma: no cover - reported through the assertion below
            result = f"error:{type(exc).__name__}"
        finally:
            engine.dispose()
        with guard:
            outcomes.append(result)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(outcomes) == ["lost", "won"]
    assert _approval_status(seeded, approval.approval_id) == "APPROVED"


def test_two_threads_deciding_sibling_rows_produce_exactly_one_decision(
    pg_db: str, seeded: Engine, store: PgApprovalStore
) -> None:
    approve = _pending(1)
    skip = _pending(2, action=ApprovalAction.SKIP_USER)
    store.insert_pending(approve)
    store.insert_pending(skip)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    guard = threading.Lock()

    def worker(decision: Approval) -> None:
        engine = make_sync_engine(pg_db)
        try:
            racer = PgApprovalStore(OperationalDatabase(engine))
            barrier.wait(timeout=30)
            try:
                racer.save_atomic(decision, None)
                result = "won"
            except ApprovalAlreadyDecided:
                result = "lost"
        except Exception as exc:  # pragma: no cover - reported through the assertion below
            result = f"error:{type(exc).__name__}"
        finally:
            engine.dispose()
        with guard:
            outcomes.append(result)

    threads = [
        threading.Thread(target=worker, args=(_decided(approve, ApprovalResult.APPROVED),)),
        threading.Thread(target=worker, args=(_decided(skip, ApprovalResult.SKIPPED),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(outcomes) == ["lost", "won"]
    with Session(seeded) as session:
        decided = session.execute(
            text("SELECT count(*) FROM approvals WHERE status <> 'PENDING'")
        ).scalar_one()
    assert decided == 1


# --------------------------------------------------------------------------- #
# resolve_callback / dispatch_callback against PostgreSQL.
# --------------------------------------------------------------------------- #


def _callback(raw_token: str, action: ApprovalAction | None = ApprovalAction.APPROVE) -> Callback:
    return Callback(
        raw_token=raw_token,
        chat_id=CHAT_ID,
        plan_hash=PLAN_HASH,
        strategy_version="v1.0.0",
        parameter_set_id="baseline-v1",
        parameter_set_hash=PARAM_HASH,
        callback_at_utc=T_CALLBACK,
        action=action,
    )


def _replay_kwargs() -> dict[str, Any]:
    return {
        "authorized_chat_id": CHAT_ID,
        "expiry_utc": T1,
        "approval_strategy_version": "v1.0.0",
        "approval_parameter_set_id": "baseline-v1",
        "approval_parameter_set_hash": PARAM_HASH,
        "now_utc": T_CALLBACK,
    }


def test_resolve_callback_decides_once_and_replays_to_the_stored_approval(
    seeded: Engine, store: PgApprovalStore
) -> None:
    raw = issue_one_time_token()
    store.insert_pending(_pending(1, raw_token=raw))

    first = resolve_callback(
        _callback(raw), store.lookup_by_token_hash, store.save, **_replay_kwargs()
    )
    replay = resolve_callback(
        _callback(raw), store.lookup_by_token_hash, store.save, **_replay_kwargs()
    )

    assert first.status is ApprovalResult.APPROVED
    assert first.acted_at_utc == T_CALLBACK
    assert replay == first
    assert store.get(first.approval_id) == first


def test_resolve_callback_wrong_token_is_invalidated(
    seeded: Engine, store: PgApprovalStore
) -> None:
    store.insert_pending(_pending(1, raw_token=issue_one_time_token()))

    with pytest.raises(ApprovalRejected) as excinfo:
        resolve_callback(
            _callback(issue_one_time_token()),
            store.lookup_by_token_hash,
            store.save,
            **_replay_kwargs(),
        )

    assert excinfo.value.reason_code is RejectionReason.INVALIDATED


def test_resolve_callback_after_another_process_decided_returns_the_stored_approval(
    seeded: Engine, store: PgApprovalStore
) -> None:
    raw = issue_one_time_token()
    pending = _pending(1, raw_token=raw)
    store.insert_pending(pending)
    # Another process decided between this process's lookup and its write.
    other_process = _decided(pending, ApprovalResult.APPROVED, T_DECIDED)
    store.save_atomic(other_process, None)

    result = resolve_callback(_callback(raw), lambda _hash: pending, store.save, **_replay_kwargs())

    assert result == other_process
    assert result.acted_at_utc == T_DECIDED


def test_resolve_callback_lost_race_with_a_different_outcome_is_invalidated(
    seeded: Engine, store: PgApprovalStore
) -> None:
    raw = issue_one_time_token()
    pending = _pending(1, raw_token=raw)
    skip = _pending(2, action=ApprovalAction.SKIP_USER)
    store.insert_pending(pending)
    store.insert_pending(skip)
    store.save_atomic(_decided(skip, ApprovalResult.SKIPPED), None)

    with pytest.raises(ApprovalRejected) as excinfo:
        resolve_callback(_callback(raw), lambda _hash: pending, store.save, **_replay_kwargs())

    assert excinfo.value.reason_code is RejectionReason.INVALIDATED
    assert _approval_status(seeded, pending.approval_id) == "PENDING"


class _Journal:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def test_dispatch_callback_resolves_an_approve_end_to_end(
    seeded: Engine, store: PgApprovalStore
) -> None:
    raw = issue_one_time_token()
    store.insert_pending(_pending(1, raw_token=raw))
    store.record_short_id_mapping(_mapping())
    short_id = derive_short_id(SIGNAL_ID)
    journal = _Journal()

    result = dispatch_callback(
        ParsedCallback(raw="APR:" + short_id, kind=CallbackKind.APPROVE, short_id=short_id),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=T_CALLBACK,
        raw_token=raw,
        correlation_id="cb:17-09",
        journal_receipt=journal.record,
        lookup_by_short_id=store.lookup_by_short_id,
        lookup_by_token_hash=store.lookup_by_token_hash,
        save_atomic=store.save_atomic,
        now_utc=T_CALLBACK,
        binding_context={
            "plan_hash": PLAN_HASH,
            "strategy_version": "v1.0.0",
            "parameter_set_id": "baseline-v1",
            "parameter_set_hash": PARAM_HASH,
            "expiry_utc": T1,
        },
    )

    assert result.ok is True
    assert result.approval is not None
    assert result.approval.status is ApprovalResult.APPROVED
    assert _approval_status(seeded, result.approval.approval_id) == "APPROVED"
    assert journal.events, "the callback receipt is journaled first"


# --------------------------------------------------------------------------- #
# Seeded round-trip property (random.Random(17), 25 cases).
# --------------------------------------------------------------------------- #


def test_seeded_round_trip_for_approvals_and_mappings_including_consumed(engine: Engine) -> None:
    db = OperationalDatabase(engine)
    store = PgApprovalStore(db)
    state = PgExecutionStateStore(db)
    rng = random.Random(17)
    consumed_cases = 0

    for case in range(1, 26):
        insert_and_commit(
            engine,
            make_signal(case),
            make_plan(case, case, plan_hash=hexid(0x500 + case)),
        )
        action = rng.choice([ApprovalAction.APPROVE, ApprovalAction.SKIP_USER])
        pending = _pending(
            case,
            plan_n=case,
            signal_n=case,
            action=action,
            actor_id=rng.choice(["operator", "ops-2", ""]),
            telegram_message_id=rng.choice([None, str(rng.randrange(1, 10**9))]),
            requested_at_utc=T0 + timedelta(seconds=rng.randrange(0, 3600)),
            request_hash=hexid(rng.randrange(1, 10**12)),
            # D078: the consume below re-reads this stored quantity (D078 (5)); every random
            # intended quantity (at most 0.999) stays at or below it. No rng draw is added.
            approved_quantity=Decimal("1"),
        )
        store.insert_pending(pending)
        assert store.get(pending.approval_id) == pending

        expected = pending
        if rng.random() < 0.8:
            result = (
                ApprovalResult.APPROVED
                if action is ApprovalAction.APPROVE
                else rng.choice([ApprovalResult.SKIPPED, ApprovalResult.EXPIRED])
            )
            expected = _decided(pending, result, T0 + timedelta(seconds=3600 + rng.randrange(600)))
            mapping = make_short_id_mapping(
                signal_id=hexid(case),
                trade_plan_id=hexid(0x1000 + case),
                created_at_utc=T0 + timedelta(seconds=rng.randrange(0, 3600)),
            )
            store.save_atomic(expected, mapping)
            with Session(engine) as session:
                row = session.get(ShortIdMappingRow, mapping.short_id)
                assert row is not None
                assert short_id_mapping_from_row(row) == mapping
            assert store.lookup_by_short_id(mapping.short_id) == (
                mapping.signal_id,
                mapping.trade_plan_id,
            )
            if result is ApprovalResult.APPROVED and rng.random() < 0.7:
                consumed_at = T0 + timedelta(seconds=7200 + rng.randrange(600))
                plan_hash = hexid(0x500 + case)
                assert state.consume_and_record_entry_intent(
                    approval_id=pending.approval_id,
                    trade_plan_id=pending.trade_plan_id,
                    plan_hash=plan_hash,
                    client_order_id=derive_client_order_id(
                        plan_hash=plan_hash, role=OrderRole.ENTRY.value
                    ),
                    symbol="BTCUSDT",
                    side="BUY",
                    intended_quantity=Decimal(rng.randrange(1, 1000)) / Decimal(1000),
                    intended_price=Decimal(rng.randrange(40000, 60000)) / Decimal(10),
                    approved_quantity=Decimal("1"),
                    now_utc=consumed_at,
                )
                expected = replace(
                    expected,
                    consumption_status=ApprovalConsumptionStatus.CONSUMED,
                    consumed_at_utc=consumed_at,
                )
                consumed_cases += 1

        assert store.get(pending.approval_id) == expected
        assert store.lookup_by_token_hash(pending.approval_token_hash) == expected

    assert consumed_cases > 0, "the property must exercise CONSUMED approvals"


# --------------------------------------------------------------------------- #
# actor_id and money_json (Phase 23, plan 23-04; D-03, D-13).
# --------------------------------------------------------------------------- #

MONEY_JSON = '{"schema":"money-at-stake/1","risk_amount":"10.5"}'


def _stored_text(engine: Engine, column: str, approval_id: str) -> str | None:
    with Session(engine) as session:
        value = session.execute(
            text(f"SELECT {column} FROM approvals WHERE approval_id = :id"),  # noqa: S608
            {"id": approval_id},
        ).scalar_one()
    return None if value is None else str(value)


def test_tracer_decided_actor_and_money_survive_a_new_store_instance(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1, approved_quantity=Decimal("0.08"), money_json=MONEY_JSON, actor_id="")
    store.insert_pending(approval)

    store.save_atomic(
        replace(_decided(approval, ApprovalResult.APPROVED), actor_id="777001"),
        None,
    )

    fresh = PgApprovalStore(OperationalDatabase(seeded))
    assert fresh is not store
    stored = fresh.get(approval.approval_id)
    assert stored is not None
    assert stored.actor_id == "777001"
    assert stored.money_json == MONEY_JSON
    assert stored.status is ApprovalResult.APPROVED
    assert _stored_text(seeded, "actor_id", approval.approval_id) == "777001"
    assert _stored_text(seeded, "money_json", approval.approval_id) == MONEY_JSON


def test_a_second_decision_keeps_the_first_actor(seeded: Engine, store: PgApprovalStore) -> None:
    approval = _pending(1, actor_id="")
    store.insert_pending(approval)
    decided = _decided(approval, ApprovalResult.APPROVED)
    store.save_atomic(replace(decided, actor_id="777001"), None)

    with pytest.raises(ApprovalAlreadyDecided):
        store.save_atomic(replace(decided, actor_id="777002"), None)

    assert _stored_text(seeded, "actor_id", approval.approval_id) == "777001"


def test_a_lost_race_to_a_sibling_row_never_overwrites_the_stored_actor(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approve = _pending(1, action=ApprovalAction.APPROVE, actor_id="")
    skip = _pending(2, action=ApprovalAction.SKIP_USER, actor_id="")
    store.insert_pending(approve)
    store.insert_pending(skip)
    store.save_atomic(replace(_decided(approve, ApprovalResult.APPROVED), actor_id="777001"), None)

    with pytest.raises(ApprovalAlreadyDecided):
        store.save_atomic(replace(_decided(skip, ApprovalResult.SKIPPED), actor_id="777002"), None)

    assert _stored_text(seeded, "actor_id", approve.approval_id) == "777001"
    assert _stored_text(seeded, "actor_id", skip.approval_id) == ""
    assert _approval_status(seeded, skip.approval_id) == "PENDING"


def test_money_json_is_part_of_the_insert_identity(seeded: Engine, store: PgApprovalStore) -> None:
    approval = _pending(1, money_json=MONEY_JSON)
    store.insert_pending(approval)
    store.insert_pending(approval)  # the same request again is a no-op
    assert _count(seeded, "approvals") == 1

    with pytest.raises(RowConflict, match="money_json"):
        store.insert_pending(replace(approval, money_json='{"schema":"other"}'))
    with pytest.raises(RowConflict, match="money_json"):
        store.insert_pending(replace(approval, money_json=None))
    assert _stored_text(seeded, "money_json", approval.approval_id) == MONEY_JSON


def test_a_decision_never_changes_the_stored_money(
    seeded: Engine, store: PgApprovalStore
) -> None:
    approval = _pending(1, money_json=MONEY_JSON)
    store.insert_pending(approval)

    store.save_atomic(
        replace(_decided(approval, ApprovalResult.APPROVED), money_json='{"tampered":"1"}'),
        None,
    )

    assert _stored_text(seeded, "money_json", approval.approval_id) == MONEY_JSON


def test_a_row_written_without_money_reads_back_none(
    seeded: Engine, store: PgApprovalStore
) -> None:
    insert_and_commit(seeded, make_approval(1, 1, 1))

    stored = store.get(hexid(0x2001))
    assert stored is not None
    assert stored.money_json is None
