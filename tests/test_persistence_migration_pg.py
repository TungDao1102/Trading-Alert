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
  * Migration 0008 (Phase 20, plan 20-14, D-19, Q4) adds the `pending_protective_actions` table;
    the head test pins 0008.
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
    "uq_approvals_one_decided_per_plan": "status<>'pending'",
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
    assert alembic_head_revision() == REVISION_0008
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
        assert before - after == {"approved_quantity"}
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
        assert _public_tables(engine) == full_schema - {"pending_protective_actions"}
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
