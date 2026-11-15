"""PgPendingActionStore against a real PostgreSQL server (Phase 20, plan 20-14, D-19, Q4).

Each test runs on a generated `t17_<hex>_test` clone built by `alembic upgrade head`. The table
stores the INTENT of a gate-refused protective action and never a payload: no price, quantity
or side column exists. The tracer test drives the protection coordinator over the Phase 19 fake
exchange into a real `RateLimitPauseActive` refusal and reads the row back through a NEW store
instance, as a restart would.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive
from src.execution.pending_actions import PendingKind, PendingState
from src.persistence.engine import make_sync_engine
from src.persistence.pending_actions import PgPendingActionStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import T0, expect_db_error
from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, make_rig

PLAN = "d" * 64
REASON = "RATE_LIMIT_PAUSE_429"
_CHECK_VIOLATION = "23514"
_UNIQUE_VIOLATION = "23505"


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> PgPendingActionStore:
    return PgPendingActionStore(OperationalDatabase(engine))


def _block(
    store: PgPendingActionStore,
    now: datetime,
    *,
    plan_hash: str = PLAN,
    kind: PendingKind = PendingKind.STOP_NOT_SENT,
    retry_after: datetime | None = None,
) -> object:
    return store.record_blocked(
        plan_hash=plan_hash,
        trade_plan_id="plan-0001",
        approval_id="approval-0001",
        symbol="BTCUSDT",
        kind=kind,
        gate_reason=REASON,
        retry_after_until_utc=retry_after,
        now_utc=now,
    )


def test_record_blocked_inserts_then_bumps_one_open_row(
    store: PgPendingActionStore, engine: Engine
) -> None:
    first = _block(store, T0, retry_after=T0 + timedelta(seconds=30))
    second = _block(store, T0 + timedelta(seconds=2), retry_after=T0 + timedelta(seconds=40))

    assert first.block_count == 1  # type: ignore[attr-defined]
    assert second.block_count == 2  # type: ignore[attr-defined]
    assert second.pending_id == first.pending_id  # type: ignore[attr-defined]
    assert second.first_blocked_at_utc == T0  # type: ignore[attr-defined]
    assert second.last_blocked_at_utc == T0 + timedelta(seconds=2)  # type: ignore[attr-defined]
    assert second.retry_after_until_utc == T0 + timedelta(seconds=40)  # type: ignore[attr-defined]
    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM pending_protective_actions")).scalar_one()
    assert count == 1


def test_list_open_from_a_new_store_instance_returns_the_row(engine: Engine) -> None:
    _block(PgPendingActionStore(OperationalDatabase(engine)), T0)

    fresh = PgPendingActionStore(OperationalDatabase(engine))
    rows = fresh.list_open()

    assert len(rows) == 1
    row = rows[0]
    assert row.kind is PendingKind.STOP_NOT_SENT
    assert row.state is PendingState.PENDING
    assert row.plan_hash == PLAN
    assert row.symbol == "BTCUSDT"
    assert row.gate_reason == REASON
    assert row.first_blocked_at_utc == T0
    assert row.resolved_at_utc is None
    assert row.resolution_note is None


def test_list_open_is_ordered_by_first_block_then_id(store: PgPendingActionStore) -> None:
    _block(store, T0 + timedelta(seconds=5), plan_hash="e" * 64)
    _block(store, T0, plan_hash=PLAN, kind=PendingKind.CLOSE_NOT_SENT)
    _block(store, T0, plan_hash=PLAN, kind=PendingKind.STOP_NOT_SENT)

    rows = store.list_open()

    assert [r.first_blocked_at_utc for r in rows] == [T0, T0, T0 + timedelta(seconds=5)]
    assert [r.pending_id for r in rows[:2]] == sorted(r.pending_id for r in rows[:2])


def test_resolve_and_supersede_close_only_the_open_row(store: PgPendingActionStore) -> None:
    _block(store, T0, kind=PendingKind.STOP_NOT_SENT)
    _block(store, T0, kind=PendingKind.PROTECTION_ENTRY_CANCEL_NOT_SENT)

    superseded = store.supersede(
        plan_hash=PLAN,
        kind=PendingKind.STOP_NOT_SENT,
        note="CLOSE_REQUIRED_BY_POLICY",
        now_utc=T0 + timedelta(seconds=3),
    )
    resolved = store.resolve(
        plan_hash=PLAN,
        kind=PendingKind.PROTECTION_ENTRY_CANCEL_NOT_SENT,
        note="ENTRY_TERMINAL",
        now_utc=T0 + timedelta(seconds=4),
    )
    again = store.resolve(
        plan_hash=PLAN, kind=PendingKind.STOP_NOT_SENT, note="X", now_utc=T0 + timedelta(seconds=9)
    )

    assert superseded is not None and superseded.state is PendingState.SUPERSEDED
    assert superseded.resolution_note == "CLOSE_REQUIRED_BY_POLICY"
    assert superseded.resolved_at_utc == T0 + timedelta(seconds=3)
    assert resolved is not None and resolved.state is PendingState.RESOLVED
    assert again is None  # nothing open any more
    assert store.list_open() == ()


def test_a_new_block_after_a_resolution_opens_a_new_row(
    store: PgPendingActionStore, engine: Engine
) -> None:
    first = _block(store, T0)
    store.resolve(plan_hash=PLAN, kind=PendingKind.STOP_NOT_SENT, note="X", now_utc=T0)
    later = _block(store, T0 + timedelta(minutes=1))

    assert later.pending_id != first.pending_id  # type: ignore[attr-defined]
    assert later.block_count == 1  # type: ignore[attr-defined]
    with engine.connect() as conn:
        states = (
            conn.execute(text("SELECT state FROM pending_protective_actions ORDER BY state"))
            .scalars()
            .all()
        )
    assert list(states) == ["PENDING", "RESOLVED"]


def test_the_table_has_no_price_quantity_or_side_column(engine: Engine) -> None:
    with engine.connect() as conn:
        columns = {
            str(row[0])
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'pending_protective_actions'"
                )
            ).all()
        }
    assert columns == {
        "pending_id",
        "plan_hash",
        "trade_plan_id",
        "approval_id",
        "symbol",
        "pending_kind",
        "state",
        "gate_reason",
        "first_blocked_at_utc",
        "last_blocked_at_utc",
        "block_count",
        "retry_after_until_utc",
        "resolved_at_utc",
        "resolution_note",
    }


_INSERT = text(
    "INSERT INTO pending_protective_actions (pending_id, plan_hash, trade_plan_id, approval_id, "
    "symbol, pending_kind, state, gate_reason, first_blocked_at_utc, last_blocked_at_utc, "
    "block_count, resolved_at_utc, resolution_note) VALUES (:id, :plan, 'p', 'a', 'BTCUSDT', "
    ":kind, :state, 'IP_BAN_418', :t0, :t0, :count, :resolved, :note)"
)


def _raw(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "id": "ppa_raw_1",
        "plan": PLAN,
        "kind": "STOP_NOT_SENT",
        "state": "PENDING",
        "t0": T0,
        "count": 1,
        "resolved": None,
        "note": None,
    }
    values.update(overrides)
    with engine.begin() as conn:
        conn.execute(_INSERT, values)


def test_the_partial_unique_index_allows_one_open_row_per_plan_and_kind(engine: Engine) -> None:
    _raw(engine, id="ppa_raw_1")
    with expect_db_error(_UNIQUE_VIOLATION) as info:
        _raw(engine, id="ppa_raw_2")
    assert info.constraint == "uq_pending_protective_actions_open"
    # A different kind, or a closed row, is fine.
    _raw(engine, id="ppa_raw_3", kind="CLOSE_NOT_SENT")
    _raw(engine, id="ppa_raw_4", state="RESOLVED", resolved=T0, note="DONE")


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"kind": "STOP_SENT"}, "ck_pending_protective_actions_kind"),
        ({"state": "DONE", "resolved": T0, "note": "X"}, "ck_pending_protective_actions_state"),
        ({"count": 0}, "ck_pending_protective_actions_block_count"),
        ({"state": "RESOLVED"}, "ck_pending_protective_actions_resolution"),
        ({"resolved": T0, "note": "X"}, "ck_pending_protective_actions_resolution"),
    ],
)
def test_the_check_constraints_refuse_a_malformed_row(
    engine: Engine, overrides: dict[str, object], constraint: str
) -> None:
    with expect_db_error(_CHECK_VIOLATION) as info:
        _raw(engine, **overrides)
    assert info.constraint == constraint


def test_a_naive_timestamp_is_refused_before_the_database(store: PgPendingActionStore) -> None:
    with pytest.raises(ValueError):
        _block(store, datetime(2026, 10, 21, 12, 0, 0))
    assert store.list_open() == ()


# --------------------------------------------------------------------------- #
# The tracer end to end: coordinator -> gate refusal -> durable row -> a new store reads it.
# --------------------------------------------------------------------------- #


async def test_a_gate_refused_stop_is_a_durable_row_a_restarted_store_reads(
    engine: Engine,
) -> None:
    rig = await make_rig(pending_actions=PgPendingActionStore(OperationalDatabase(engine)))
    rig.fake.fail_next("place_algo_protective", RateLimitPauseActive(30))
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))

    await rig.coordinator.step()

    restarted = PgPendingActionStore(OperationalDatabase(engine))
    rows = restarted.list_open()
    assert len(rows) == 1
    assert rows[0].kind is PendingKind.STOP_NOT_SENT
    assert rows[0].plan_hash == TEST_ONLY_PLAN_HASH
    assert rows[0].gate_reason == REASON
    assert rows[0].block_count == 1
    assert rows[0].retry_after_until_utc == rig.clock.now() + timedelta(seconds=30)
    assert rows[0].first_blocked_at_utc.tzinfo is not None
    assert rows[0].first_blocked_at_utc.utcoffset() == timedelta(0)


async def test_a_gate_refused_close_is_durable_and_resolved_once_it_goes_through(
    engine: Engine,
) -> None:
    store = PgPendingActionStore(OperationalDatabase(engine))
    rig = await make_rig(real_closer=True, pending_actions=store)
    rig.fake.reject_next_algo(-2021)
    rig.fake.fail_next("place_market_close", RateLimitPauseActive(60))
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))

    await rig.coordinator.step()

    restarted = PgPendingActionStore(OperationalDatabase(engine))
    rows = restarted.list_open()
    assert [r.kind for r in rows] == [PendingKind.CLOSE_NOT_SENT]
    assert rows[0].gate_reason == REASON
    assert rig.coordinator.blocks_new_entries() is True

    await rig.coordinator.step()  # the gate is open: the close goes out, the plan ends FLAT

    assert restarted.list_open() == ()
    with engine.connect() as conn:
        closed = conn.execute(
            text("SELECT state, resolution_note FROM pending_protective_actions")
        ).all()
    assert [tuple(row) for row in closed] == [("RESOLVED", "CLOSE_SENT_AFTER_GATE")]
    assert rig.coordinator.blocks_new_entries() is False


async def test_a_pending_stop_is_superseded_in_the_database_and_never_sent(
    engine: Engine,
) -> None:
    store = PgPendingActionStore(OperationalDatabase(engine))
    rig = await make_rig(pending_actions=store)
    for _ in range(10):
        rig.fake.fail_next("place_algo_protective", RateLimitPauseActive(600))
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))
    await rig.coordinator.step()
    assert len(store.list_open()) == 1

    await rig.clock.advance(7.777)  # max_unprotected_ms, TEST_ONLY 7777 ms of virtual time
    await rig.coordinator.step()
    sent = len(rig.fake.calls_to("place_algo_protective"))
    for _ in range(3):
        await rig.clock.advance(1)
        await rig.coordinator.step()

    assert store.list_open() == ()
    with engine.connect() as conn:
        closed = conn.execute(
            text("SELECT state, resolution_note, block_count FROM pending_protective_actions")
        ).all()
    assert [tuple(row) for row in closed] == [("SUPERSEDED", "CLOSE_REQUIRED_BY_POLICY", 2)]
    assert len(rig.fake.calls_to("place_algo_protective")) == sent
