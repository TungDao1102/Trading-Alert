"""Schema parity, reversibility and data-safe upgrade of the Alembic chain (D-11, D-24, F-411).

Every database here is built by `alembic upgrade` (never from ORM metadata, D-23):

  * `compare_metadata` diffs the migrated database against `Base.metadata` with
    `compare_type`, `compare_server_default` and the opt-in
    `alembic.ext.checkconstraint_byname` plugin, so drift in indexes, constraints,
    types or widths fails.
  * `compare_metadata` is blind to partial-index predicates and compares CHECKs by
    name only (research Pitfall 4), so catalog assertions cover the predicates, the
    enum CHECK literals and the triggers.
  * The chain must be reversible (upgrade head, downgrade base, upgrade head) and a
    data-bearing upgrade 0003 -> 0004 and 0004 -> 0005 must keep every pre-existing row.
  * Migration 0005 (Phase 19, D-22, G4-008) adds the nullable `sized_realized_risk` column
    and its named CHECK to `execution_intents`.
  * Migration 0006 (Phase 19 review-fix batch 4, D078, 19-REVIEW WR-01) adds the nullable
    `approved_quantity` column and its named CHECK to `approvals`.
  * Migration 0007 (Phase 20, plan 20-03, T-B) adds the nullable `resolution_reason_code`
    column and its named CHECK to `execution_intents`.
  * Migration 0008 (Phase 20, plan 20-14, D-19, Q4) adds the `pending_protective_actions` table.
  * Migration 0009 (Phase 20, plan 20-18, Q3, D-21) adds the `validated_lot_filters` table.
  * Migration 0010 (Phase 21, plan 21-09, D-07, D-14) adds the `daily_risk_days` and
    `daily_loss_components` tables.
  * Migration 0011 (Phase 21, plan 21-12, D-16) adds the `risk_reservations` table.
  * Migration 0012 (Phase 22, plan 22-08, D-14) adds the three nullable margin columns and their
    two named CHECKs to `risk_reservations`.
  * Migration 0013 (Phase 23, plan 23-04, D-13) adds the nullable `money_json` column and its
    named CHECK to `approvals`.
  * Migration 0014 (Phase 23, plan 23-08, G4-042) recreates `uq_approvals_one_decided_per_plan`
    with the predicate `status NOT IN ('PENDING','EXPIRED')`; its downgrade refuses when a plan
    holds more than one non-PENDING row.
  * Migration 0015 (Phase 24, plan 24-07, D-10) adds the nullable `orders.exchange_event_time_utc`
    and `positions.snapshot_event_time_utc` columns; its downgrade refuses when any row holds an
    event time. The head test pins 0015.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from src.db.models import (
    Base,
    CollectorGap,
    CollectorWatermark,
    CoverageWindow,
    ExecutionIntentRow,
    ShortIdMappingRow,
)
from src.domain.enums import (
    ApprovalAction,
    ApprovalConsumptionStatus,
    ApprovalResult,
    Direction,
    EntryModel,
    ExecutionIntentStatus,
    LiveInputsStatus,
    OrderRole,
    OrderStatus,
    PositionStatus,
    SetupType,
    SignalStatus,
    SourceTimeframe,
    SystemStateKey,
    TradePlanStatus,
)
from src.domain.registry import WORKING_TYPE_VALUES
from src.execution.pending_actions import PendingKind, PendingState
from src.persistence.engine import make_sync_engine

from tests.pg_support import alembic_head_revision, run_alembic
from tests.support.ast_guards import forbidden_imports
from tests.support.pg_rows import (
    T0,
    expect_db_error,
    hexid,
    insert_and_commit,
    make_approval,
    make_fill,
    make_journal,
    make_order,
    make_plan,
    make_position,
    make_signal,
    make_symbol_metadata,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REVISION_0003 = "0003_callback_mapping"
REVISION_0004 = "0004_persistence_integrity"
REVISION_0005 = "0005_live_sized_risk"
MIGRATION_0005 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0005_live_sized_risk.py"
REVISION_0006 = "0006_approval_quantity"
MIGRATION_0006 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0006_approval_quantity.py"
REVISION_0007 = "0007_intent_resolution_reason"
MIGRATION_0007 = (
    REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0007_intent_resolution_reason.py"
)
REVISION_0008 = "0008_pending_protective_actions"
MIGRATION_0008 = (
    REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0008_pending_protective_actions.py"
)
REVISION_0009 = "0009_validated_lot_filters"
MIGRATION_0009 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0009_validated_lot_filters.py"
REVISION_0010 = "0010_daily_risk_state"
MIGRATION_0010 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0010_daily_risk_state.py"
REVISION_0011 = "0011_risk_reservations"
MIGRATION_0011 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0011_risk_reservations.py"
REVISION_0012 = "0012_reservation_margin"
MIGRATION_0012 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0012_reservation_margin.py"
REVISION_0013 = "0013_approval_money"
MIGRATION_0013 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0013_approval_money.py"
REVISION_0014 = "0014_decided_excl_expired"
MIGRATION_0014 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0014_decided_excl_expired.py"
REVISION_0015 = "0015_order_event_time"
MIGRATION_0015 = REPO_ROOT / "src" / "db" / "alembic" / "versions" / "0015_order_event_time.py"
_CHECK_VIOLATION = "23514"

_AUTOGENERATE_PLUGINS = [
    "alembic.autogenerate.*",
    "alembic.ext.checkconstraint_byname",
]
_QUOTED_LITERAL = re.compile(r"'((?:[^']|'')*)'")


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


# --------------------------------------------------------------------------------------
# Alembic floor (D-11, research C19 / Pitfall 16)
# --------------------------------------------------------------------------------------
def test_alembic_floor_guarantees_the_opt_in_check_constraint_plugin() -> None:
    """The plugin `alembic.ext.checkconstraint_byname` ships with Alembic >= 1.19.2."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    assert "alembic>=1.19.2" in dependencies, dependencies
    assert not (REPO_ROOT / "scripts" / "check_migration_parity.py").exists()


# --------------------------------------------------------------------------------------
# compare_metadata parity (Pattern 5)
# --------------------------------------------------------------------------------------
def test_migrated_database_matches_orm_metadata(engine: Engine) -> None:
    opts = {
        "compare_type": True,
        "compare_server_default": True,
        "autogenerate_plugins": _AUTOGENERATE_PLUGINS,
    }
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts=opts), Base.metadata)
    assert diff == [], f"ORM metadata and the migrated database differ: {diff!r}"


_DRIFTS = {
    "dropped_named_check": "ALTER TABLE signals DROP CONSTRAINT ck_signals_direction",
    "widened_column": "ALTER TABLE signals ALTER COLUMN status TYPE VARCHAR(64)",
    "dropped_index": "DROP INDEX uq_orders_client_order_id",
    "dropped_foreign_key": "ALTER TABLE orders DROP CONSTRAINT fk_orders_trade_plan_id",
}


@pytest.mark.parametrize("drift", sorted(_DRIFTS))
def test_parity_check_detects_drift(engine: Engine, drift: str) -> None:
    """Sensitivity: the diff is non-empty once the database drifts from the ORM."""
    opts = {
        "compare_type": True,
        "compare_server_default": True,
        "autogenerate_plugins": _AUTOGENERATE_PLUGINS,
    }
    with engine.begin() as conn:
        conn.execute(text(_DRIFTS[drift]))
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts=opts), Base.metadata)
    assert diff, f"drift {drift!r} went undetected"


# --------------------------------------------------------------------------------------
# Catalog assertions for what compare_metadata cannot see (Pitfall 4)
# --------------------------------------------------------------------------------------
def _normalize(sql: str) -> str:
    """Lowercase and drop whitespace, parentheses and `::type` casts of a catalog predicate."""
    sql = re.sub(r"::[a-z_ ]+(\[\])?", "", sql.lower())
    return re.sub(r"[\s()]", "", sql)


PARTIAL_INDEX_PREDICATES = {
    # 0014 (G4-042): PostgreSQL stores `NOT IN ('PENDING','EXPIRED')` as `<> ALL (ARRAY[...])`.
    "uq_approvals_one_decided_per_plan": "status<>allarray['pending','expired']",
    "uq_orders_client_order_id": "client_order_idisnotnull",
    "uq_orders_algo_client_id": "algo_client_idisnotnull",
    "uq_execution_intents_client_order_id": "client_order_idisnotnull",
    "uq_execution_intents_algo_client_id": "algo_client_idisnotnull",
    "uq_pending_protective_actions_open": "state='pending'",
}


@pytest.mark.parametrize(("index", "predicate"), sorted(PARTIAL_INDEX_PREDICATES.items()))
def test_partial_unique_index_states_its_exact_predicate(
    engine: Engine, index: str, predicate: str
) -> None:
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": index}
        ).scalar_one()
    assert definition.startswith("CREATE UNIQUE INDEX"), definition
    assert " WHERE " in definition, definition
    where = definition.split(" WHERE ", 1)[1]
    assert _normalize(where) == predicate, definition


# constraint name -> the exact value set the CHECK must list
ENUM_CHECKS: dict[str, set[str]] = {
    "ck_signals_status": {m.value for m in SignalStatus},
    "ck_signals_direction": {m.value for m in Direction},
    "ck_signals_setup_type": {m.value for m in SetupType},
    "ck_signals_source_timeframe": {m.value for m in SourceTimeframe},
    "ck_trade_plans_status": {m.value for m in TradePlanStatus},
    "ck_trade_plans_entry_model": {m.value for m in EntryModel},
    "ck_approvals_action": {m.value for m in ApprovalAction},
    "ck_approvals_result": {m.value for m in ApprovalResult},
    "ck_approvals_status": {m.value for m in ApprovalResult},
    "ck_approvals_consumption_status": {m.value for m in ApprovalConsumptionStatus},
    "ck_orders_local_status": {m.value for m in OrderStatus},
    "ck_positions_status": {m.value for m in PositionStatus},
    "ck_execution_intents_role": {m.value for m in OrderRole},
    "ck_execution_intents_status": {m.value for m in ExecutionIntentStatus},
    "ck_plan_constraint_snapshots_live_inputs_status": {m.value for m in LiveInputsStatus},
    "ck_plan_constraint_snapshots_working_type": set(WORKING_TYPE_VALUES),
    "ck_system_state_events_state_key": {m.value for m in SystemStateKey},
    "ck_pending_protective_actions_kind": {m.value for m in PendingKind},
    "ck_pending_protective_actions_state": {m.value for m in PendingState},
}

# every table the plan names for an enum CHECK
ENUM_CHECK_TABLES = {
    "signals",
    "trade_plans",
    "approvals",
    "orders",
    "positions",
    "execution_intents",
    "plan_constraint_snapshots",
    "system_state_events",
    "pending_protective_actions",
}


def test_enum_check_inventory_covers_every_enum_table() -> None:
    covered = {
        next(table for table in ENUM_CHECK_TABLES if name.startswith(f"ck_{table}_"))
        for name in ENUM_CHECKS
    }
    assert covered == ENUM_CHECK_TABLES


@pytest.mark.parametrize(("name", "values"), sorted(ENUM_CHECKS.items()))
def test_enum_check_lists_exactly_the_current_enum_values(
    engine: Engine, name: str, values: set[str]
) -> None:
    with engine.connect() as conn:
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = :n AND contype = 'c'"
            ),
            {"n": name},
        ).scalar_one()
    literals = {match.replace("''", "'") for match in _QUOTED_LITERAL.findall(definition)}
    assert literals == values, (name, definition)


APPEND_ONLY_TABLES = ("journal_events", "system_state_events", "plan_constraint_snapshots")
TERMINAL_STATUS_TABLES = (
    "signals",
    "trade_plans",
    "approvals",
    "orders",
    "positions",
    "execution_intents",
)


def _triggers(engine: Engine) -> set[tuple[str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal"
            )
        ).all()
    return {(str(row[0]), str(row[1])) for row in rows}


def test_append_only_and_terminal_status_triggers_are_all_present(engine: Engine) -> None:
    expected = {
        (table, f"trg_{table}_{kind}")
        for table in APPEND_ONLY_TABLES
        for kind in ("append_only", "no_truncate")
    } | {(table, f"trg_{table}_terminal_status") for table in TERMINAL_STATUS_TABLES}
    assert _triggers(engine) == expected


# --------------------------------------------------------------------------------------
# Reversibility (D-24)
# --------------------------------------------------------------------------------------
def _public_tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).all()
    return {str(row[0]) for row in rows}


def _public_functions(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public'"
            )
        ).all()
    return {str(row[0]) for row in rows}


def test_upgrade_downgrade_upgrade_cycle_is_clean(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        full_schema = _public_tables(engine)
        assert {"signals", "execution_intents", "journal_events"} <= full_schema
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", "base")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == {"alembic_version"}
        assert _public_functions(engine) == set()
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Data-bearing upgrade 0003 -> 0004 (D-24)
# --------------------------------------------------------------------------------------
def _collector_rows() -> list[object]:
    return [
        CollectorWatermark(
            symbol="BTCUSDT", data_class="klines", last_tick_utc=T0, updated_at_utc=T0
        ),
        CollectorGap(
            symbol="BTCUSDT",
            data_class="klines",
            expected_utc=T0,
            observed_utc=T0,
            reason="missed tick",
            recorded_at_utc=T0,
        ),
        CoverageWindow(
            symbol="BTCUSDT",
            interval="1h",
            historical_data_start_utc=datetime(2026, 1, 1, tzinfo=UTC),
            historical_data_end_utc=T0,
            onboard_time_utc=None,
            status_history_json="[]",
            updated_at_utc=T0,
        ),
    ]


def _rows_at_0003() -> list[Any]:
    """One valid row per pre-existing table, parents first."""
    return [
        make_symbol_metadata(),
        *_collector_rows(),
        make_signal(1),
        make_plan(1, 1),
        make_position(1),
        make_order(1, 1),
        make_approval(1, 1, 1),
        make_fill(1, 1),
        make_journal(1),
        ShortIdMappingRow(
            short_id="ab" * 16,
            signal_id=make_signal(1).signal_id,
            trade_plan_id=make_plan(1, 1).trade_plan_id,
            created_at_utc=T0,
        ),
    ]


def _present_columns(engine: Engine) -> Callable[[str], set[str]]:
    def columns(table: str) -> set[str]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            ).all()
        return {str(row[0]) for row in rows}

    return columns


def _values(row: Any, allowed: set[str]) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key in allowed}


def test_data_bearing_upgrade_keeps_every_row(pg_empty_db: str) -> None:
    # Tables are REFLECTED from the 0003 database: the ORM declares 0004-only columns
    # (and Python-side defaults for them) that a 0003 INSERT must not mention.
    run_alembic(pg_empty_db, "upgrade", REVISION_0003)
    engine = make_sync_engine(pg_empty_db)
    try:
        columns_of = _present_columns(engine)
        assert "consumption_status" not in columns_of("approvals")
        rows = _rows_at_0003()
        inserted: list[tuple[Any, dict[str, Any]]] = []
        with engine.begin() as conn:
            for row in rows:
                name = row.__table__.name
                table = Table(name, MetaData(), autoload_with=engine)
                values = _values(row, columns_of(name))
                assert values, name
                conn.execute(table.insert().values(values))
                inserted.append((table, values))
        assert {t.name for t, _ in inserted} == {
            "symbol_metadata",
            "collector_watermarks",
            "collector_gaps",
            "coverage_windows",
            "signals",
            "trade_plans",
            "approvals",
            "orders",
            "fills",
            "positions",
            "journal_events",
            "short_id_mapping",
        }
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")

    engine = make_sync_engine(pg_empty_db)
    try:
        with engine.connect() as conn:
            for table, values in inserted:
                keys = list(values)
                head_table = Table(table.name, MetaData(), autoload_with=conn)
                stored = conn.execute(select(*[head_table.c[k] for k in keys])).all()
                assert len(stored) == 1, table.name
                assert dict(zip(keys, stored[0], strict=True)) == values, table.name
            consumption = conn.execute(
                text("SELECT consumption_status, consumed_at_utc FROM approvals")
            ).all()
        assert [tuple(row) for row in consumption] == [
            (ApprovalConsumptionStatus.UNCONSUMED.value, None)
        ]
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0005: sized_realized_risk (Phase 19, D-22, G4-008)
# --------------------------------------------------------------------------------------
def test_migrated_database_is_at_the_script_directory_head(pg_db: str) -> None:
    assert alembic_head_revision() == REVISION_0015
    eng = make_sync_engine(pg_db)
    try:
        with eng.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == alembic_head_revision()
    finally:
        eng.dispose()


def test_migration_0005_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0005, ("src", "tests")) == []


def test_sized_realized_risk_column_and_check_catalog(engine: Engine) -> None:
    with engine.connect() as conn:
        column = conn.execute(
            text(
                "SELECT data_type, numeric_precision, numeric_scale, is_nullable "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'execution_intents' AND column_name = 'sized_realized_risk'"
            )
        ).one()
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_execution_intents_sized_realized_risk' AND contype = 'c'"
            )
        ).scalar_one()
    assert tuple(column) == ("numeric", 38, 18, "YES")
    assert _normalize(definition) == _normalize(
        "CHECK (sized_realized_risk IS NULL OR (role = 'ENTRY' AND sized_realized_risk > 0))"
    )


def _seed_parents(engine: Engine) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1), make_approval(1, 1, 1))


def _intent(role: str = "ENTRY", **overrides: Any) -> ExecutionIntentRow:
    is_entry = role == "ENTRY"
    values: dict[str, Any] = {
        "approval_id": hexid(0x2001),
        "role": role,
        "trade_plan_id": hexid(0x1001),
        "plan_hash": "d" * 64,
        "client_order_id": f"x-{1:032x}EN" if is_entry else None,
        "algo_client_id": None if is_entry else f"x-{1:032x}{role[:2]}",
        "symbol": "BTCUSDT",
        "side": "BUY" if is_entry else "SELL",
        "intended_quantity": Decimal("0.08"),
        "intended_price": Decimal("50050"),
        "intent_status": "INTENDED",
        "outcome_recorded": False,
        "intended_at_utc": T0,
        "updated_at_utc": T0,
    }
    values.update(overrides)
    return ExecutionIntentRow(**values)


def test_entry_intent_accepts_a_positive_sized_realized_risk(engine: Engine) -> None:
    _seed_parents(engine)
    insert_and_commit(engine, _intent("ENTRY", sized_realized_risk=Decimal("12.5")))
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT sized_realized_risk FROM execution_intents WHERE role = 'ENTRY'")
        ).scalar_one()
    assert stored == Decimal("12.5")


def test_intent_without_a_sized_figure_stores_null(engine: Engine) -> None:
    _seed_parents(engine)
    insert_and_commit(engine, _intent("ENTRY"), _intent("STOP_LOSS"))
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT sized_realized_risk FROM execution_intents")).all()
    assert [row[0] for row in stored] == [None, None]


@pytest.mark.parametrize(
    ("role", "value"),
    [
        ("STOP_LOSS", Decimal("12.5")),
        ("TAKE_PROFIT_1", Decimal("1")),
        ("ENTRY", Decimal("0")),
        ("ENTRY", Decimal("-3")),
    ],
)
def test_sized_realized_risk_check_rejects_protective_zero_and_negative(
    engine: Engine, role: str, value: Decimal
) -> None:
    _seed_parents(engine)
    with pytest.raises(IntegrityError) as raised:
        insert_and_commit(engine, _intent(role, sized_realized_risk=value))
    orig: Any = raised.value.orig
    assert orig.sqlstate == _CHECK_VIOLATION
    assert orig.diag.constraint_name == "ck_execution_intents_sized_realized_risk"


# --------------------------------------------------------------------------------------
# Reversible chain and data-bearing upgrade 0004 -> 0005 (Phase 19, D-22)
# --------------------------------------------------------------------------------------
def _reflected_inserts(engine: Engine, rows: list[Any]) -> list[tuple[Table, dict[str, Any]]]:
    """Insert `rows` through reflected tables, with explicit non-NULL column subsets.

    Reflection (not the ORM insert) keeps a 0004 INSERT from mentioning the 0005-only
    column; NULL-valued attributes are left out so server defaults apply.
    """
    columns_of = _present_columns(engine)
    inserted: list[tuple[Table, dict[str, Any]]] = []
    with engine.begin() as conn:
        for row in rows:
            name = row.__table__.name
            table = Table(name, MetaData(), autoload_with=engine)
            present = columns_of(name)
            values = {
                c.key: getattr(row, c.key)
                for c in row.__table__.columns
                if c.key in present and getattr(row, c.key) is not None
            }
            assert values, name
            conn.execute(table.insert().values(values))
            inserted.append((table, values))
    return inserted


def _assert_rows_intact(engine: Engine, inserted: list[tuple[Table, dict[str, Any]]]) -> None:
    with engine.connect() as conn:
        for table, values in inserted:
            keys = list(values)
            reflected = Table(table.name, MetaData(), autoload_with=conn)
            stored = conn.execute(select(*[reflected.c[k] for k in keys])).all()
            assert any(dict(zip(keys, row, strict=True)) == values for row in stored), table.name


def test_data_bearing_upgrade_0004_to_0005_keeps_every_row(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", REVISION_0004)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert "sized_realized_risk" not in _present_columns(engine)("execution_intents")
        inserted = _reflected_inserts(
            engine,
            [
                make_signal(1),
                make_plan(1, 1),
                make_approval(1, 1, 1),
                _intent("ENTRY"),
                _intent("STOP_LOSS"),
            ],
        )
        assert [t.name for t, _ in inserted] == [
            "signals",
            "trade_plans",
            "approvals",
            "execution_intents",
            "execution_intents",
        ]
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")

    engine = make_sync_engine(pg_empty_db)
    try:
        _assert_rows_intact(engine, inserted)
        with engine.connect() as conn:
            figures = conn.execute(
                text("SELECT role, sized_realized_risk FROM execution_intents ORDER BY role")
            ).all()
        assert [tuple(row) for row in figures] == [("ENTRY", None), ("STOP_LOSS", None)]
    finally:
        engine.dispose()


def test_downgrade_0005_keeps_rows_and_removes_only_the_column(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        insert_and_commit(
            engine,
            make_signal(1),
            make_plan(1, 1),
            make_approval(1, 1, 1),
            _intent("ENTRY", sized_realized_risk=Decimal("12.5")),
            _intent("STOP_LOSS"),
        )
        before = _present_columns(engine)("execution_intents")
        assert "sized_realized_risk" in before
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0004)

    engine = make_sync_engine(pg_empty_db)
    try:
        after = _present_columns(engine)("execution_intents")
        # Downgrading from head to 0004 also passes through 0007, which owns the second column.
        assert before - after == {"sized_realized_risk", "resolution_reason_code"}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            roles = (
                conn.execute(text("SELECT role FROM execution_intents ORDER BY role"))
                .scalars()
                .all()
            )
            check = conn.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = 'ck_execution_intents_sized_realized_risk'"
                )
            ).scalar_one()
        assert version == REVISION_0004
        assert list(roles) == ["ENTRY", "STOP_LOSS"]
        assert check == 0
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0006: approved_quantity (Phase 19 review-fix batch 4, D078, 19-REVIEW WR-01)
# --------------------------------------------------------------------------------------
def test_migration_0006_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0006, ("src", "tests")) == []


def test_approved_quantity_column_and_check_catalog(engine: Engine) -> None:
    with engine.connect() as conn:
        column = conn.execute(
            text(
                "SELECT data_type, numeric_precision, numeric_scale, is_nullable "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'approvals' AND column_name = 'approved_quantity'"
            )
        ).one()
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_approvals_approved_quantity' AND contype = 'c'"
            )
        ).scalar_one()
    assert tuple(column) == ("numeric", 38, 18, "YES")
    assert _normalize(definition) == _normalize(
        "CHECK (approved_quantity IS NULL OR approved_quantity > 0)"
    )


def test_approved_quantity_accepts_null_and_a_positive_value(engine: Engine) -> None:
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_approval(1, 1, 1),
        make_approval(2, 1, 1, approved_quantity=Decimal("2.415")),
    )
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT approval_id, approved_quantity FROM approvals ORDER BY approval_id")
        ).all()
    assert [row[1] for row in stored] == [None, Decimal("2.415")]


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1")])
def test_approved_quantity_check_rejects_zero_and_negative(engine: Engine, value: Decimal) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))
    with pytest.raises(IntegrityError) as raised:
        insert_and_commit(engine, make_approval(1, 1, 1, approved_quantity=value))
    orig: Any = raised.value.orig
    assert orig.sqlstate == _CHECK_VIOLATION
    assert orig.diag.constraint_name == "ck_approvals_approved_quantity"


def test_data_bearing_upgrade_0005_to_0006_keeps_every_row_with_null(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", REVISION_0005)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert "approved_quantity" not in _present_columns(engine)("approvals")
        inserted = _reflected_inserts(
            engine, [make_signal(1), make_plan(1, 1), make_approval(1, 1, 1)]
        )
        assert [t.name for t, _ in inserted] == ["signals", "trade_plans", "approvals"]
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")

    engine = make_sync_engine(pg_empty_db)
    try:
        _assert_rows_intact(engine, inserted)
        with engine.connect() as conn:
            figures = conn.execute(text("SELECT approved_quantity FROM approvals")).all()
        assert [tuple(row) for row in figures] == [(None,)]
    finally:
        engine.dispose()


def test_downgrade_0006_keeps_rows_and_removes_only_the_column_and_the_check(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        insert_and_commit(
            engine,
            make_signal(1),
            make_plan(1, 1),
            make_approval(1, 1, 1, approved_quantity=Decimal("2.415")),
        )
        before = _present_columns(engine)("approvals")
        assert "approved_quantity" in before
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0005)

    engine = make_sync_engine(pg_empty_db)
    try:
        after = _present_columns(engine)("approvals")
        # Going below 0006 also passes 0013, so its later column leaves with it.
        assert before - after == {"approved_quantity", "money_json"}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            approvals = conn.execute(text("SELECT count(*) FROM approvals")).scalar_one()
            check = conn.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = 'ck_approvals_approved_quantity'"
                )
            ).scalar_one()
        assert version == REVISION_0005
        assert approvals == 1
        assert check == 0
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0007: resolution_reason_code (Phase 20, plan 20-03, T-B, D-11)
# --------------------------------------------------------------------------------------
def test_migration_0007_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0007, ("src", "tests")) == []


def test_migration_0007_revises_0006() -> None:
    text_of_migration = MIGRATION_0007.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0006}"' in text_of_migration
    assert f'revision: str = "{REVISION_0007}"' in text_of_migration


def test_resolution_reason_code_column_and_check_catalog(engine: Engine) -> None:
    with engine.connect() as conn:
        column = conn.execute(
            text(
                "SELECT data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'execution_intents' AND column_name = 'resolution_reason_code'"
            )
        ).one()
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_execution_intents_resolution_reason' AND contype = 'c'"
            )
        ).scalar_one()
    assert tuple(column) == ("character varying", 32, "YES")
    assert "resolution_reason_code IS NULL" in definition
    assert set(_QUOTED_LITERAL.findall(definition)) == {
        "REJECTED",
        "RECONCILED_ABSENT",
        "NEVER_SENT",
    }


def test_data_bearing_upgrade_0006_to_0007_keeps_every_row_with_null(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", REVISION_0006)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert "resolution_reason_code" not in _present_columns(engine)("execution_intents")
        inserted = _reflected_inserts(
            engine,
            [
                make_signal(1),
                make_plan(1, 1),
                make_approval(1, 1, 1),
                _intent("ENTRY"),
                _intent("STOP_LOSS"),
            ],
        )
        assert len(inserted) == 5
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")

    engine = make_sync_engine(pg_empty_db)
    try:
        _assert_rows_intact(engine, inserted)
        with engine.connect() as conn:
            reasons = conn.execute(
                text("SELECT role, resolution_reason_code FROM execution_intents ORDER BY role")
            ).all()
        assert [tuple(row) for row in reasons] == [("ENTRY", None), ("STOP_LOSS", None)]
    finally:
        engine.dispose()


def test_downgrade_0007_keeps_rows_and_removes_only_the_column_and_the_check(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        insert_and_commit(
            engine,
            make_signal(1),
            make_plan(1, 1),
            make_approval(1, 1, 1),
            _intent(
                "ENTRY",
                intent_status="REJECTED",
                resolution_reason_code="RECONCILED_ABSENT",
                resolved_at_utc=T0,
            ),
        )
        before = _present_columns(engine)("execution_intents")
        assert "resolution_reason_code" in before
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0006)

    engine = make_sync_engine(pg_empty_db)
    try:
        after = _present_columns(engine)("execution_intents")
        assert before - after == {"resolution_reason_code"}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            intents = conn.execute(text("SELECT count(*) FROM execution_intents")).scalar_one()
            check = conn.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = 'ck_execution_intents_resolution_reason'"
                )
            ).scalar_one()
        assert version == REVISION_0006
        assert intents == 1
        assert check == 0
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0008: pending_protective_actions (Phase 20, plan 20-14, D-19, Q4)
# --------------------------------------------------------------------------------------
def test_migration_0008_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0008, ("src", "tests")) == []


def test_migration_0008_revises_0007() -> None:
    text_of_migration = MIGRATION_0008.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0007}"' in text_of_migration
    assert f'revision: str = "{REVISION_0008}"' in text_of_migration


def test_migration_0008_has_no_price_quantity_or_side_column() -> None:
    """The table stores the intent, never a payload (D-19): no such column is declared."""
    source = MIGRATION_0008.read_text(encoding="utf-8")
    declared = re.findall(r'sa\.Column\(\s*"([a-z_]+)"', source)
    assert declared, "no column declaration found"
    for name in declared:
        assert not re.search(r"price|quantity|side", name), name


def test_downgrade_0008_drops_only_the_pending_table_and_upgrade_restores_it(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        full_schema = _public_tables(engine)
        assert "pending_protective_actions" in full_schema
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO pending_protective_actions (pending_id, plan_hash, "
                    "trade_plan_id, approval_id, symbol, pending_kind, state, gate_reason, "
                    "first_blocked_at_utc, last_blocked_at_utc, block_count) VALUES "
                    "('ppa_1', 'p', 't', 'a', 'BTCUSDT', 'STOP_NOT_SENT', 'PENDING', "
                    "'IP_BAN_418', :t0, :t0, 1)"
                ),
                {"t0": T0},
            )
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0007)
    engine = make_sync_engine(pg_empty_db)
    try:
        # Downgrading from head to 0007 also passes through 0009 (the filters table), 0010
        # (the day-state tables) and 0011 (the reservations table).
        assert _public_tables(engine) == full_schema - {
            "pending_protective_actions",
            "validated_lot_filters",
            "daily_risk_days",
            "daily_loss_components",
            "risk_reservations",
        }
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0007
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0009: validated_lot_filters (Phase 20, plan 20-18, Q3, D-21)
# --------------------------------------------------------------------------------------
def test_migration_0009_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0009, ("src", "tests")) == []


def test_migration_0009_revises_0008() -> None:
    text_of_migration = MIGRATION_0009.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0008}"' in text_of_migration
    assert f'revision: str = "{REVISION_0009}"' in text_of_migration


def test_downgrade_0009_drops_only_the_filters_table_and_upgrade_restores_it(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        full_schema = _public_tables(engine)
        assert "validated_lot_filters" in full_schema
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO validated_lot_filters (symbol, price_tick_size, "
                    "lot_min_quantity, lot_max_quantity, lot_step_size, "
                    "market_lot_min_quantity, market_lot_max_quantity, market_lot_step_size, "
                    "min_notional, fetched_at_utc, updated_at_utc) VALUES "
                    "('BTCUSDT', 0.1, 0.001, 1000, 0.001, 0.001, 120, 0.001, 100, :t0, :t0)"
                ),
                {"t0": T0},
            )
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0008)
    engine = make_sync_engine(pg_empty_db)
    try:
        # Downgrading from head to 0008 also passes through 0010 (the day-state tables) and
        # 0011 (the reservations table).
        assert _public_tables(engine) == full_schema - {
            "validated_lot_filters",
            "daily_risk_days",
            "daily_loss_components",
            "risk_reservations",
        }
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0008
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0015
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0010: daily_risk_days and daily_loss_components (Phase 21, plan 21-09, D-07, D-14)
# --------------------------------------------------------------------------------------
def test_migration_0010_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0010, ("src", "tests")) == []


def test_migration_0010_revises_0009() -> None:
    text_of_migration = MIGRATION_0010.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0009}"' in text_of_migration
    assert f'revision: str = "{REVISION_0010}"' in text_of_migration


def test_downgrade_0010_drops_only_the_day_state_tables_and_upgrade_restores_them(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        full_schema = _public_tables(engine)
        assert {"daily_risk_days", "daily_loss_components"} <= full_schema
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO daily_risk_days (utc_day, equity_at_day_start, "
                    "base_observed_at_utc) VALUES ('2026-10-23', 1000, :t0)"
                ),
                {"t0": T0},
            )
            conn.execute(
                text(
                    "INSERT INTO daily_loss_components (utc_day, kind, source, source_key, "
                    "amount, asset, event_time_utc) VALUES "
                    "('2026-09-19', 'FILL_PNL', 'USER_DATA_EVENT', 'BTCUSDT:1:1', -1, 'USDT', :t0)"
                ),
                {"t0": T0},
            )
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0009)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema - {
            "daily_risk_days",
            "daily_loss_components",
            "risk_reservations",
        }
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0009
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0015
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0011: risk_reservations (Phase 21, plan 21-12, D-16)
# --------------------------------------------------------------------------------------
def test_migration_0011_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0011, ("src", "tests")) == []


def test_migration_0011_revises_0010() -> None:
    text_of_migration = MIGRATION_0011.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0010}"' in text_of_migration
    assert f'revision: str = "{REVISION_0011}"' in text_of_migration


def test_downgrade_0011_drops_only_the_reservations_table_and_upgrade_restores_it(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        full_schema = _public_tables(engine)
        assert "risk_reservations" in full_schema
        insert_and_commit(engine, make_signal(1), make_plan(1, 1))
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO risk_reservations (trade_plan_id, plan_hash, symbol, "
                    "position_side, quantity, realized_risk, status, requested_at_utc, "
                    "updated_at_utc) VALUES (:plan, :h, 'BTCUSDT', 'LONG', 0.001, 4, "
                    "'REQUESTED', :t0, :t0)"
                ),
                {"plan": hexid(0x1001), "h": "d" * 64, "t0": T0},
            )
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0010)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema - {"risk_reservations"}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0010
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0015
    finally:
        engine.dispose()


def test_risk_reservations_check_constraints_refuse_bad_rows(engine: Engine) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))
    base = {
        "plan": hexid(0x1001),
        "h": "d" * 64,
        "side": "LONG",
        "qty": Decimal("0.001"),
        "risk": Decimal("4"),
        "status": "REQUESTED",
        "reason": None,
        "released_at": None,
        "t0": T0,
    }
    sql = text(
        "INSERT INTO risk_reservations (trade_plan_id, plan_hash, symbol, position_side, "
        "quantity, realized_risk, status, release_reason, released_at_utc, requested_at_utc, "
        "updated_at_utc) VALUES (:plan, :h, 'BTCUSDT', :side, :qty, :risk, :status, :reason, "
        ":released_at, :t0, :t0)"
    )
    cases = {
        "ck_risk_reservations_release_reason": {
            "status": "RELEASED",
            "reason": "NOT_A_REASON",
            "released_at": T0,
        },
        "ck_risk_reservations_status": {"status": "DONE"},
        "ck_risk_reservations_side": {"side": "BOTH"},
        "ck_risk_reservations_quantity_positive": {"qty": Decimal("0")},
        "ck_risk_reservations_risk_positive": {"risk": Decimal("0")},
        # a reason and a release time on a row that is not RELEASED (the RELEASED row without a
        # reason is the last case below)
        "ck_risk_reservations_released_coherent": {"reason": "PLAN_EXPIRED", "released_at": T0},
        # a counted status without an approval id
        "ck_risk_reservations_approval_coherent": {"status": "RESERVED"},
    }
    for constraint, override in cases.items():
        with expect_db_error(_CHECK_VIOLATION) as info, engine.begin() as conn:
            conn.execute(sql, {**base, **override})
        assert info.constraint == constraint, (constraint, info.constraint)
    with expect_db_error(_CHECK_VIOLATION) as info, engine.begin() as conn:
        conn.execute(sql, {**base, "status": "RELEASED"})
    assert info.constraint == "ck_risk_reservations_released_coherent"


# --------------------------------------------------------------------------------------
# Migration 0012: reservation margin (Phase 22, plan 22-08, D-14)
# --------------------------------------------------------------------------------------
_MARGIN_COLUMNS = ("required_margin", "margin_entry_price", "margin_leverage")
_MARGIN_CHECKS = (
    "ck_risk_reservations_margin_coherent",
    "ck_risk_reservations_margin_positive",
)
_RESERVATION_INSERT = text(
    "INSERT INTO risk_reservations (trade_plan_id, plan_hash, symbol, position_side, quantity, "
    "realized_risk, status, requested_at_utc, updated_at_utc, required_margin, "
    "margin_entry_price, margin_leverage) VALUES (:plan, :h, 'BTCUSDT', 'LONG', 0.01, 4, "
    "'REQUESTED', :t0, :t0, :margin, :price, :leverage)"
)


def _reservation_columns(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'risk_reservations'"
            )
        ).all()
    return {str(row[0]) for row in rows}


def _reservation_checks(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'risk_reservations'::regclass AND contype = 'c'"
            )
        ).all()
    return {str(row[0]) for row in rows}


def test_migration_0012_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0012, ("src", "tests")) == []


def test_migration_0012_revises_0011() -> None:
    text_of_migration = MIGRATION_0012.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0011}"' in text_of_migration
    assert f'revision: str = "{REVISION_0012}"' in text_of_migration


def test_the_margin_columns_are_nullable_and_the_two_checks_exist(engine: Engine) -> None:
    with engine.connect() as conn:
        nullable = dict(
            conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'risk_reservations' "
                    "AND column_name IN ('required_margin', 'margin_entry_price', "
                    "'margin_leverage')"
                )
            ).all()
        )
    assert nullable == dict.fromkeys(_MARGIN_COLUMNS, "YES")
    assert set(_MARGIN_CHECKS) <= _reservation_checks(engine)


def test_downgrade_0012_drops_only_the_margin_columns_and_checks_and_keeps_the_rows(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        full_schema = _public_tables(engine)
        columns_at_head = _reservation_columns(engine)
        checks_at_head = _reservation_checks(engine)
        assert set(_MARGIN_COLUMNS) <= columns_at_head
        assert set(_MARGIN_CHECKS) <= checks_at_head
        insert_and_commit(engine, make_signal(1), make_plan(1, 1))
        with engine.begin() as conn:
            conn.execute(
                _RESERVATION_INSERT,
                {
                    "plan": hexid(0x1001),
                    "h": "d" * 64,
                    "t0": T0,
                    "margin": Decimal("160"),
                    "price": Decimal("80000"),
                    "leverage": 5,
                },
            )
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0011)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema
        assert _reservation_columns(engine) == columns_at_head - set(_MARGIN_COLUMNS)
        assert _reservation_checks(engine) == checks_at_head - set(_MARGIN_CHECKS)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            kept = conn.execute(
                text(
                    "SELECT trade_plan_id, plan_hash, symbol, position_side, quantity, "
                    "realized_risk, status FROM risk_reservations"
                )
            ).all()
        assert version == REVISION_0011
        assert [tuple(row) for row in kept] == [
            (hexid(0x1001), "d" * 64, "BTCUSDT", "LONG", Decimal("0.01"), Decimal("4"), "REQUESTED")
        ]
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _reservation_columns(engine) == columns_at_head
        assert _reservation_checks(engine) == checks_at_head
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            restored = conn.execute(
                text(
                    "SELECT required_margin, margin_entry_price, margin_leverage "
                    "FROM risk_reservations"
                )
            ).all()
        assert version == REVISION_0015
        # The stored margin was lost by the downgrade: the restored columns are empty (unknown).
        assert [tuple(row) for row in restored] == [(None, None, None)]
    finally:
        engine.dispose()


def test_risk_reservations_margin_checks_refuse_bad_rows(engine: Engine) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))
    base: dict[str, Any] = {
        "plan": hexid(0x1001),
        "h": "d" * 64,
        "t0": T0,
        "margin": Decimal("160"),
        "price": Decimal("80000"),
        "leverage": 5,
    }
    cases = {
        "set margin, NULL leverage": (
            "ck_risk_reservations_margin_coherent",
            {"leverage": None},
        ),
        "set margin only": (
            "ck_risk_reservations_margin_coherent",
            {"price": None, "leverage": None},
        ),
        "NULL margin, set price": (
            "ck_risk_reservations_margin_coherent",
            {"margin": None},
        ),
        "negative margin": ("ck_risk_reservations_margin_positive", {"margin": Decimal("-1")}),
        "zero margin": ("ck_risk_reservations_margin_positive", {"margin": Decimal("0")}),
        "zero price": ("ck_risk_reservations_margin_positive", {"price": Decimal("0")}),
        "leverage 0": ("ck_risk_reservations_margin_positive", {"leverage": 0}),
    }
    for label, (constraint, override) in cases.items():
        with expect_db_error(_CHECK_VIOLATION) as info, engine.begin() as conn:
            conn.execute(_RESERVATION_INSERT, {**base, **override})
        assert info.constraint == constraint, (label, info.constraint)
    # The legacy form (all three NULL) is accepted.
    with engine.begin() as conn:
        conn.execute(_RESERVATION_INSERT, {**base, "margin": None, "price": None, "leverage": None})


# --------------------------------------------------------------------------------------
# Migration 0013: approvals.money_json (Phase 23, plan 23-04, D-13)
# --------------------------------------------------------------------------------------
_MONEY_CHECK = "ck_approvals_money_json"


def _approval_columns(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'approvals'"
            )
        ).all()
    return {str(row[0]) for row in rows}


def _approval_checks(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'approvals'::regclass AND contype = 'c'"
            )
        ).all()
    return {str(row[0]) for row in rows}


def test_migration_0013_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0013, ("src", "tests")) == []


def test_migration_0013_revises_0012() -> None:
    text_of_migration = MIGRATION_0013.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0012}"' in text_of_migration
    assert f'revision: str = "{REVISION_0013}"' in text_of_migration


def test_the_money_json_column_is_nullable_text_and_the_check_exists(engine: Engine) -> None:
    with engine.connect() as conn:
        column = conn.execute(
            text(
                "SELECT is_nullable, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'approvals' "
                "AND column_name = 'money_json'"
            )
        ).one()
    assert tuple(column) == ("YES", "text")
    assert _MONEY_CHECK in _approval_checks(engine)


def test_the_money_json_check_refuses_non_object_text_and_accepts_null_and_an_object(
    engine: Engine,
) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))
    for label, bad in {"empty": "", "word": "x", "array": "[1]", "open only": "{"}.items():
        with expect_db_error(_CHECK_VIOLATION) as info:
            insert_and_commit(engine, make_approval(1, 1, 1, money_json=bad))
        assert info.constraint == _MONEY_CHECK, (label, info.constraint)

    insert_and_commit(engine, make_approval(1, 1, 1, money_json=None))
    insert_and_commit(
        engine,
        make_approval(2, 1, 1, money_json='{"a":"1"}', action="SKIP_USER"),
    )
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT approval_id, money_json FROM approvals ORDER BY approval_id")
        ).all()
    assert [tuple(row) for row in stored] == [(hexid(0x2001), None), (hexid(0x2002), '{"a":"1"}')]


def test_downgrade_0013_drops_only_the_money_column_and_check_and_keeps_the_rows(
    pg_empty_db: str,
) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        full_schema = _public_tables(engine)
        columns_at_head = _approval_columns(engine)
        checks_at_head = _approval_checks(engine)
        assert "money_json" in columns_at_head
        assert _MONEY_CHECK in checks_at_head
        insert_and_commit(
            engine,
            make_signal(1),
            make_plan(1, 1),
            make_approval(1, 1, 1, actor_id="777001", money_json='{"a":"1"}'),
        )
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0012)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == full_schema
        assert _approval_columns(engine) == columns_at_head - {"money_json"}
        assert _approval_checks(engine) == checks_at_head - {_MONEY_CHECK}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            kept = conn.execute(
                text("SELECT approval_id, actor_id, status, request_hash FROM approvals")
            ).all()
        assert version == REVISION_0012
        assert [tuple(row) for row in kept] == [(hexid(0x2001), "777001", "PENDING", "e" * 64)]
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _approval_columns(engine) == columns_at_head
        assert _approval_checks(engine) == checks_at_head
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            restored = conn.execute(text("SELECT money_json FROM approvals")).all()
        assert version == REVISION_0015
        # The stored money was lost by the downgrade: the restored column is empty (not recorded).
        assert [tuple(row) for row in restored] == [(None,)]
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0014: EXPIRED leaves uq_approvals_one_decided_per_plan (Phase 23, plan 23-08, G4-042)
# --------------------------------------------------------------------------------------
_ONE_DECIDED_INDEX = "uq_approvals_one_decided_per_plan"


def _one_decided_index_sql(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                {"n": _ONE_DECIDED_INDEX},
            ).scalar_one()
        )


def test_migration_0014_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0014, ("src", "tests")) == []


def test_migration_0014_revises_0013() -> None:
    text_of_migration = MIGRATION_0014.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0013}"' in text_of_migration
    assert f'revision: str = "{REVISION_0014}"' in text_of_migration
    assert len(REVISION_0014) <= 32  # alembic_version.version_num is VARCHAR(32)


def test_the_head_index_predicate_excludes_pending_and_expired(engine: Engine) -> None:
    definition = _one_decided_index_sql(engine)
    assert "UNIQUE" in definition
    assert "NOT IN" in definition or "<> ALL" in definition
    assert "'PENDING'" in definition
    assert "'EXPIRED'" in definition


def test_downgrade_0014_restores_the_old_predicate_on_an_empty_table(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    run_alembic(pg_empty_db, "downgrade", REVISION_0013)
    engine = make_sync_engine(pg_empty_db)
    try:
        definition = _one_decided_index_sql(engine)
        assert "<> 'PENDING'" in definition
        assert "'EXPIRED'" not in definition
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0013
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        assert "'EXPIRED'" in _one_decided_index_sql(engine)
    finally:
        engine.dispose()


def test_downgrade_0014_refuses_when_a_plan_holds_two_expired_rows(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        insert_and_commit(
            engine,
            make_signal(1),
            make_plan(1, 1),
            make_approval(1, 1, 1, status="EXPIRED", result="EXPIRED"),
            make_approval(2, 1, 1, status="EXPIRED", result="EXPIRED", action="SKIP_USER"),
        )
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0014)  # 0015 holds no event time: passes
    with pytest.raises(RuntimeError, match="1 plans have more than one non-PENDING approval"):
        run_alembic(pg_empty_db, "downgrade", REVISION_0013)

    engine = make_sync_engine(pg_empty_db)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            statuses = (
                conn.execute(text("SELECT status FROM approvals ORDER BY approval_id"))
                .scalars()
                .all()
            )
        assert version == REVISION_0014
        assert list(statuses) == ["EXPIRED", "EXPIRED"]
        assert "'EXPIRED'" in _one_decided_index_sql(engine)
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Migration 0015: exchange event time on orders and positions (Phase 24, plan 24-07, D-10)
# --------------------------------------------------------------------------------------
_EVENT_TIME_COLUMNS = {"orders": "exchange_event_time_utc", "positions": "snapshot_event_time_utc"}
_TIMESTAMPTZ = ("YES", "timestamp with time zone")


def _event_time_column_info(engine: Engine, table: str, column: str) -> tuple[str, str] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT is_nullable, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).one_or_none()
    return None if row is None else (str(row[0]), str(row[1]))


def test_migration_0015_imports_no_project_module() -> None:
    assert forbidden_imports(MIGRATION_0015, ("src", "tests")) == []


def test_migration_0015_revises_0014() -> None:
    text_of_migration = MIGRATION_0015.read_text(encoding="utf-8")
    assert f'down_revision = "{REVISION_0014}"' in text_of_migration
    assert f'revision: str = "{REVISION_0015}"' in text_of_migration
    assert len(REVISION_0015) <= 32  # alembic_version.version_num is VARCHAR(32)


def test_the_two_event_time_columns_are_nullable_timestamptz(engine: Engine) -> None:
    for table, column in _EVENT_TIME_COLUMNS.items():
        assert _event_time_column_info(engine, table, column) == _TIMESTAMPTZ, (table, column)


def test_downgrade_0015_on_empty_columns_succeeds_and_restores_0014(pg_empty_db: str) -> None:
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        tables_at_head = _public_tables(engine)
        insert_and_commit(engine, make_signal(1), make_plan(1, 1), make_order(1, 1))
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "downgrade", REVISION_0014)
    engine = make_sync_engine(pg_empty_db)
    try:
        assert _public_tables(engine) == tables_at_head  # 0015 adds no table
        for table, column in _EVENT_TIME_COLUMNS.items():
            assert _event_time_column_info(engine, table, column) is None, (table, column)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            kept = conn.execute(text("SELECT order_id FROM orders")).scalars().all()
        assert version == REVISION_0014
        assert list(kept) == [hexid(0x5001)]  # the row stays; only the columns leave
    finally:
        engine.dispose()

    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        for table, column in _EVENT_TIME_COLUMNS.items():
            assert _event_time_column_info(engine, table, column) == _TIMESTAMPTZ
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_0015
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", sorted(_EVENT_TIME_COLUMNS))
def test_downgrade_0015_refuses_when_a_row_holds_an_event_time(
    pg_empty_db: str, table: str
) -> None:
    column = _EVENT_TIME_COLUMNS[table]
    key, key_value = {
        "orders": ("order_id", hexid(0x5001)),
        "positions": ("position_id", hexid(0x4001)),
    }[table]
    run_alembic(pg_empty_db, "upgrade", "head")
    engine = make_sync_engine(pg_empty_db)
    try:
        insert_and_commit(
            engine, make_signal(1), make_plan(1, 1), make_order(1, 1), make_position(1)
        )
        with engine.begin() as conn:
            conn.execute(
                text(f"UPDATE {table} SET {column} = :t WHERE {key} = :k"),
                {"t": T0, "k": key_value},
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="cannot drop event-time columns: 1 rows hold an event"):
        run_alembic(pg_empty_db, "downgrade", REVISION_0014)

    engine = make_sync_engine(pg_empty_db)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            stored = conn.execute(
                text(f"SELECT {column} FROM {table} WHERE {key} = :k"), {"k": key_value}
            ).scalar_one()
        assert version == REVISION_0015
        assert stored == T0  # the row is intact
        for t, c in _EVENT_TIME_COLUMNS.items():
            assert _event_time_column_info(engine, t, c) is not None, (t, c)
    finally:
        engine.dispose()
