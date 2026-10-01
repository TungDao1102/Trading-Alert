"""Append-only and terminal-state trigger tests, plus the two new tables (D-10, D-18..D-22).

Every statement here is raw or ORM SQL that bypasses the Python repositories on purpose:
the database itself must refuse to rewrite an audit row or to move a status out of a
terminal state. Each test uses a fresh `pg_db` clone (the append-only triggers forbid row
cleanup, so truncating between tests is impossible by design).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.db.models import (
    ExecutionIntentRow,
    PlanConstraintSnapshotRow,
    SystemStateEventRow,
)
from src.persistence.engine import make_sync_engine

from tests.support.pg_rows import (
    T0,
    expect_db_error,
    hexid,
    insert_and_commit,
    make_approval,
    make_journal,
    make_order,
    make_plan,
    make_position,
    make_signal,
)

_CHECK_VIOLATION = "23514"
_FK_VIOLATION = "23503"
_UNIQUE_VIOLATION = "23505"
_RAISE = "P0001"
_SHA = "a" * 64


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


def make_snapshot(n: int = 1, **overrides: Any) -> PlanConstraintSnapshotRow:
    values: dict[str, Any] = {
        "trade_plan_id": hexid(0x1000 + n),
        "symbol": "BTCUSDT",
        "working_type": "MARK_PRICE",
        "margin_type": "ISOLATED",
        "leverage": "5",
        "equity_used": "1000",
        "live_inputs_status": "COMPLETE",
        "constraints_observed_at_utc": T0,
        "captured_at_utc": T0 + timedelta(seconds=1),
        "snapshot_json": '{"symbol":"BTCUSDT"}',
        "snapshot_sha256": _SHA,
    }
    values.update(overrides)
    return PlanConstraintSnapshotRow(**values)


def make_state_event(n: int = 1, **overrides: Any) -> SystemStateEventRow:
    values: dict[str, Any] = {
        "state_event_id": hexid(0x8000 + n),
        "state_key": "SAFE_MODE",
        "state_version": 1,
        "state_json": '{"active":true}',
        "journal_event_id": hexid(0x7001),
        "recorded_at_utc": T0,
    }
    values.update(overrides)
    return SystemStateEventRow(**values)


def make_intent(n: int = 1, **overrides: Any) -> ExecutionIntentRow:
    values: dict[str, Any] = {
        "approval_id": hexid(0x2000 + n),
        "role": "ENTRY",
        "trade_plan_id": hexid(0x1000 + n),
        "plan_hash": "d" * 64,
        "client_order_id": f"x-{n:032x}EN",
        "algo_client_id": None,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "intended_quantity": Decimal("0.08"),
        "intended_price": Decimal("50050"),
        "intent_status": "INTENDED",
        "outcome_recorded": False,
        "intended_at_utc": T0,
        "updated_at_utc": T0,
    }
    values.update(overrides)
    return ExecutionIntentRow(**values)


def _exec(engine: Engine, sql: str, **params: Any) -> None:
    with Session(engine) as session:
        session.execute(text(sql), params)
        session.commit()


# --------------------------------------------------------------------------- #
# append-only: journal_events, system_state_events, plan_constraint_snapshots
# --------------------------------------------------------------------------- #


def _seed_append_only(engine: Engine) -> None:
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_journal(1),
        make_state_event(1),
        make_snapshot(1),
    )


_APPEND_ONLY = [
    ("journal_events", "event_type = 'X'", "journal_event_id"),
    ("system_state_events", "state_version = 99", "state_event_id"),
    ("plan_constraint_snapshots", "symbol = 'ETHUSDT'", "trade_plan_id"),
]


@pytest.mark.parametrize(("table", "assignment", "_key"), _APPEND_ONLY)
def test_update_is_rejected(engine: Engine, table: str, assignment: str, _key: str) -> None:
    _seed_append_only(engine)
    with expect_db_error(_RAISE) as info:
        _exec(engine, f"UPDATE {table} SET {assignment}")  # noqa: S608 - literals above
    assert "append-only" in info.message and "UPDATE" in info.message and table in info.message


@pytest.mark.parametrize(("table", "_assignment", "_key"), _APPEND_ONLY)
def test_delete_is_rejected(engine: Engine, table: str, _assignment: str, _key: str) -> None:
    _seed_append_only(engine)
    with expect_db_error(_RAISE) as info:
        _exec(engine, f"DELETE FROM {table}")  # noqa: S608 - literals above
    assert "append-only" in info.message and "DELETE" in info.message and table in info.message


@pytest.mark.parametrize(("table", "_assignment", "_key"), _APPEND_ONLY)
def test_truncate_is_rejected(engine: Engine, table: str, _assignment: str, _key: str) -> None:
    _seed_append_only(engine)
    # CASCADE: journal_events is referenced by system_state_events and plan_constraint_
    # snapshots by nothing, but a plain TRUNCATE of a referenced table is refused by PostgreSQL
    # for the foreign key, which would hide whether the trigger exists. CASCADE reaches the
    # BEFORE TRUNCATE trigger of every table in the set; the message must name append-only.
    with expect_db_error(_RAISE) as info:
        _exec(engine, f"TRUNCATE TABLE {table} CASCADE")  # noqa: S608 - literals above
    assert "append-only" in info.message and "TRUNCATE" in info.message


@pytest.mark.parametrize(("table", "_assignment", "_key"), _APPEND_ONLY)
def test_append_only_triggers_are_present_and_enabled(
    engine: Engine, table: str, _assignment: str, _key: str
) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tgname, tgenabled FROM pg_trigger "
                "WHERE tgrelid = CAST(:t AS regclass) AND NOT tgisinternal"
            ),
            {"t": table},
        ).all()
    assert {r[0] for r in rows} == {f"trg_{table}_append_only", f"trg_{table}_no_truncate"}
    assert {r[1] for r in rows} == {"O"}  # 'O' = enabled in origin/local mode


# --------------------------------------------------------------------------- #
# terminal-state rule: a terminal status never changes (D-20 database rule)
# --------------------------------------------------------------------------- #

# (table, status column, terminal values, non-terminal pair (old, new), a legal value to
#  attempt from a terminal row, non-status column update on a terminal row)
_TERMINAL = [
    (
        "signals",
        "status",
        ["APPROVED", "SKIPPED_USER", "SKIPPED_BUSY", "EXPIRED", "INVALIDATED"],
        ("DETECTED", "NOTIFIED"),
        "DETECTED",
        "invalidated_at_utc = now()",
    ),
    (
        "trade_plans",
        "status",
        ["EXPIRED", "INVALIDATED", "SUPERSEDED"],
        ("READY", "APPROVAL_PENDING"),
        "READY",
        "trade_plan_version = 'v1.0.1'",
    ),
    (
        "orders",
        "local_status",
        ["FILLED", "CANCELED", "EXPIRED", "REJECTED"],
        ("NEW", "PARTIALLY_FILLED"),
        "NEW",
        "updated_at_utc = now()",
    ),
    (
        "positions",
        "status",
        ["CLOSED"],
        ("OPEN", "CLOSING"),
        "OPEN",
        "updated_at_utc = now()",
    ),
    (
        "approvals",
        "status",
        ["APPROVED", "SKIPPED", "EXPIRED"],
        ("PENDING", "APPROVED"),
        "PENDING",
        "telegram_message_id = '42'",
    ),
    (
        "execution_intents",
        "intent_status",
        ["ACKED", "REJECTED"],
        ("INTENDED", "SENT"),
        "INTENDED",
        "updated_at_utc = now()",
    ),
]
_TERMINAL_CASES = [
    (table, column, terminal, legal)
    for table, column, terminals, _pair, legal, _other in _TERMINAL
    for terminal in terminals
]


def _insert_with_status(engine: Engine, table: str, column: str, status: str) -> None:
    """Insert one parent-complete row of `table` carrying `status`."""
    if table == "signals":
        insert_and_commit(engine, make_signal(1, **{column: status}))
        return
    base = (make_signal(1), make_plan(1, 1))
    if table == "trade_plans":
        insert_and_commit(engine, make_signal(1), make_plan(1, 1, **{column: status}))
    elif table == "orders":
        insert_and_commit(engine, *base, make_order(1, 1, **{column: status}))
    elif table == "positions":
        insert_and_commit(engine, make_position(1, **{column: status}))
    elif table == "approvals":
        insert_and_commit(
            engine, *base, make_approval(1, 1, 1, **{column: status, "result": status})
        )
    elif table == "execution_intents":
        # CONSUMED needs an APPROVED approval; the intent row itself carries `status`.
        insert_and_commit(
            engine,
            *base,
            make_approval(1, 1, 1, status="APPROVED", result="APPROVED"),
            make_intent(1, **{column: status}),
        )
    else:  # pragma: no cover - table list above is closed
        raise AssertionError(table)


@pytest.mark.parametrize(
    ("table", "column", "terminal", "legal"),
    _TERMINAL_CASES,
    ids=[f"{t}:{v}" for t, _c, v, _l in _TERMINAL_CASES],
)
def test_terminal_status_cannot_change(
    engine: Engine, table: str, column: str, terminal: str, legal: str
) -> None:
    _insert_with_status(engine, table, column, terminal)
    with expect_db_error(_RAISE) as info:
        _exec(engine, f"UPDATE {table} SET {column} = :v", v=legal)  # noqa: S608
    assert "terminal" in info.message and table in info.message


@pytest.mark.parametrize(
    ("table", "column", "terminals", "pair", "_legal", "other"),
    _TERMINAL,
    ids=[row[0] for row in _TERMINAL],
)
def test_non_terminal_transitions_and_other_columns_are_allowed(
    engine: Engine,
    table: str,
    column: str,
    terminals: list[str],
    pair: tuple[str, str],
    _legal: str,
    other: str,
) -> None:
    old, new = pair
    _insert_with_status(engine, table, column, old)
    _exec(engine, f"UPDATE {table} SET {column} = :v", v=new)  # noqa: S608
    # Move to a terminal value (legal: old was non-terminal), then touch another column and
    # re-assert the SAME status (no change): both must be allowed on a terminal row.
    terminal = terminals[0]
    _exec(engine, f"UPDATE {table} SET {column} = :v", v=terminal)  # noqa: S608
    _exec(engine, f"UPDATE {table} SET {other}")  # noqa: S608
    _exec(engine, f"UPDATE {table} SET {column} = :v", v=terminal)  # noqa: S608


def test_approval_consumption_is_allowed_on_a_decided_approval(engine: Engine) -> None:
    """The write-ahead consume stamps consumption columns on an APPROVED row (plan 01)."""
    _insert_with_status(engine, "approvals", "status", "APPROVED")
    _exec(
        engine,
        "UPDATE approvals SET consumption_status = 'CONSUMED', consumed_at_utc = now()",
    )


def test_terminal_status_triggers_are_present(engine: Engine) -> None:
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg_%_terminal_status'")
            )
        }
    assert names == {
        "trg_signals_terminal_status",
        "trg_trade_plans_terminal_status",
        "trg_orders_terminal_status",
        "trg_positions_terminal_status",
        "trg_approvals_terminal_status",
        "trg_execution_intents_terminal_status",
    }


# --------------------------------------------------------------------------- #
# plan_constraint_snapshots (D-18, D-19)
# --------------------------------------------------------------------------- #


def _seed_plan(engine: Engine) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))


def test_snapshot_complete_row_inserts(engine: Engine) -> None:
    _seed_plan(engine)
    insert_and_commit(engine, make_snapshot(1))


def test_snapshot_is_one_row_per_trade_plan(engine: Engine) -> None:
    _seed_plan(engine)
    insert_and_commit(engine, make_snapshot(1))
    with expect_db_error(_UNIQUE_VIOLATION) as info:
        insert_and_commit(engine, make_snapshot(1))
    assert info.constraint == "pk_plan_constraint_snapshots"


def test_snapshot_requires_an_existing_plan(engine: Engine) -> None:
    with expect_db_error(_FK_VIOLATION) as info:
        insert_and_commit(engine, make_snapshot(5))
    assert info.constraint == "fk_plan_constraint_snapshots_trade_plan_id"


def test_snapshot_blocks_deleting_its_plan(engine: Engine) -> None:
    _seed_plan(engine)
    insert_and_commit(engine, make_snapshot(1))
    with expect_db_error(_FK_VIOLATION) as info:
        _exec(engine, "DELETE FROM trade_plans")
    assert info.constraint == "fk_plan_constraint_snapshots_trade_plan_id"


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"snapshot_sha256": "A" * 64}, "ck_plan_constraint_snapshots_sha256_hex"),
        ({"snapshot_sha256": "a" * 63}, "ck_plan_constraint_snapshots_sha256_hex"),
        ({"snapshot_sha256": "g" * 64}, "ck_plan_constraint_snapshots_sha256_hex"),
        ({"live_inputs_status": "MAYBE"}, "ck_plan_constraint_snapshots_live_inputs_status"),
        ({"working_type": "CONTRACT_PRICE"}, "ck_plan_constraint_snapshots_working_type"),
        (
            {"margin_type": "UNKNOWN"},
            "ck_plan_constraint_snapshots_complete_has_live_inputs",
        ),
        ({"leverage": "UNKNOWN"}, "ck_plan_constraint_snapshots_complete_has_live_inputs"),
        ({"equity_used": "UNKNOWN"}, "ck_plan_constraint_snapshots_complete_has_live_inputs"),
    ],
)
def test_snapshot_checks(engine: Engine, overrides: dict[str, str], constraint: str) -> None:
    _seed_plan(engine)
    with expect_db_error(_CHECK_VIOLATION) as info:
        insert_and_commit(engine, make_snapshot(1, **overrides))
    assert info.constraint == constraint


def test_incomplete_snapshot_with_unknown_sentinels_is_accepted(engine: Engine) -> None:
    _seed_plan(engine)
    insert_and_commit(
        engine,
        make_snapshot(
            1,
            live_inputs_status="INCOMPLETE",
            margin_type="UNKNOWN",
            leverage="UNKNOWN",
            equity_used="UNKNOWN",
        ),
    )


def test_snapshot_live_input_columns_are_not_null(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'plan_constraint_snapshots'"
            )
        ).all()
    nullable = {name: flag for name, flag in rows}
    assert nullable, "plan_constraint_snapshots does not exist"
    assert set(nullable.values()) == {"NO"}  # explicit sentinels, never NULL (D-19)


# --------------------------------------------------------------------------- #
# system_state_events (D-21, D-22)
# --------------------------------------------------------------------------- #


def _seed_journal(engine: Engine) -> None:
    insert_and_commit(engine, make_journal(1))


@pytest.mark.parametrize("key", ["SAFE_MODE", "LIVE_ENABLEMENT", "KILL_GATE"])
def test_state_event_accepts_every_key(engine: Engine, key: str) -> None:
    _seed_journal(engine)
    insert_and_commit(engine, make_state_event(1, state_key=key))


def test_state_event_rejects_unknown_key(engine: Engine) -> None:
    _seed_journal(engine)
    with expect_db_error(_CHECK_VIOLATION) as info:
        insert_and_commit(engine, make_state_event(1, state_key="OTHER"))
    assert info.constraint == "ck_system_state_events_state_key"


def test_state_event_version_must_be_positive(engine: Engine) -> None:
    _seed_journal(engine)
    with expect_db_error(_CHECK_VIOLATION) as info:
        insert_and_commit(engine, make_state_event(1, state_version=0))
    assert info.constraint == "ck_system_state_events_version_positive"


def test_state_event_key_version_is_unique(engine: Engine) -> None:
    _seed_journal(engine)
    insert_and_commit(engine, make_state_event(1))
    with expect_db_error(_UNIQUE_VIOLATION) as info:
        insert_and_commit(engine, make_state_event(2))  # same key and version
    assert info.constraint == "uq_system_state_events_key_version"
    # a different version, or the same version under another key, is fine
    insert_and_commit(
        engine,
        make_state_event(3, state_version=2),
        make_state_event(4, state_key="KILL_GATE", state_version=1),
    )


def test_state_event_requires_an_existing_journal_event(engine: Engine) -> None:
    with expect_db_error(_FK_VIOLATION) as info:
        insert_and_commit(engine, make_state_event(1, journal_event_id=hexid(0x7999)))
    assert info.constraint == "fk_system_state_events_journal_event_id"


def test_state_event_blocks_deleting_its_journal_event(engine: Engine) -> None:
    _seed_journal(engine)
    insert_and_commit(engine, make_state_event(1))
    # The journal append-only trigger fires first (BEFORE ROW); either way the delete fails.
    with expect_db_error():
        _exec(engine, "DELETE FROM journal_events")
