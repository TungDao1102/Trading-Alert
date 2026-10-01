"""Insert-every-enum-member tests for the migration 0004 enum CHECKs (D-08, D-09, F-403).

For every (table, column, enum) pair the database must accept EVERY member of the
Python enum and reject any other value with the named CHECK. Members are iterated
programmatically, so a new enum member without a matching CHECK update fails here.
Widths (D-09): values wider than the old VARCHAR(16) must insert untruncated.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from enum import Enum
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.db.models import OrderRow, PositionRow, SignalRow, SymbolMetadata, TradePlanRow
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    Direction,
    EntryModel,
    OrderStatus,
    PositionStatus,
    SetupType,
    SignalStatus,
    SourceTimeframe,
    TradePlanStatus,
)
from src.persistence.engine import make_sync_engine

from tests.support.pg_rows import (
    expect_db_error,
    insert_and_commit,
    make_approval,
    make_order,
    make_plan,
    make_position,
    make_signal,
    make_symbol_metadata,
)

_CHECK_VIOLATION = "23514"


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


def _build_signal(n: int, **kw: Any) -> tuple[object, ...]:
    return (make_signal(n, **kw),)


def _build_plan(n: int, **kw: Any) -> tuple[object, ...]:
    return (make_signal(n), make_plan(n, n, **kw))


def _build_approval(n: int, **kw: Any) -> tuple[object, ...]:
    return (make_signal(n), make_plan(n, n), make_approval(n, n, n, **kw))


def _build_order(n: int, **kw: Any) -> tuple[object, ...]:
    return (make_signal(n), make_plan(n, n), make_order(n, n, **kw))


def _build_position(n: int, **kw: Any) -> tuple[object, ...]:
    return (make_position(n, **kw),)


# (table, column, enum, builder). `signal` ids come from `n`, so each member gets its own
# parent chain (no cross-member unique/partial-unique interference).
ENUM_COLUMNS: list[tuple[str, str, type[Enum], Callable[..., tuple[object, ...]]]] = [
    ("signals", "status", SignalStatus, _build_signal),
    ("signals", "direction", Direction, _build_signal),
    ("signals", "setup_type", SetupType, _build_signal),
    ("signals", "source_timeframe", SourceTimeframe, _build_signal),
    ("trade_plans", "status", TradePlanStatus, _build_plan),
    ("trade_plans", "entry_model", EntryModel, _build_plan),
    ("approvals", "action", ApprovalAction, _build_approval),
    ("approvals", "result", ApprovalResult, _build_approval),
    ("approvals", "status", ApprovalResult, _build_approval),
    ("orders", "local_status", OrderStatus, _build_order),
    ("positions", "status", PositionStatus, _build_position),
]


def _ids() -> list[str]:
    return [f"{table}.{column}" for table, column, _enum, _b in ENUM_COLUMNS]


@pytest.mark.parametrize(("table", "column", "enum", "builder"), ENUM_COLUMNS, ids=_ids())
def test_every_enum_member_inserts(
    engine: Engine,
    table: str,
    column: str,
    enum: type[Enum],
    builder: Callable[..., tuple[object, ...]],
) -> None:
    members = list(enum)
    assert members, "enum has no members"
    for index, member in enumerate(members, start=1):
        rows = builder(index, **{column: member.value})
        insert_and_commit(engine, *rows)
    with engine.connect() as conn:
        stored = {
            row[0]
            for row in conn.execute(
                text(f"SELECT DISTINCT {column} FROM {table}")  # noqa: S608 - literals above
            )
        }
    assert {member.value for member in members} <= stored


@pytest.mark.parametrize(("table", "column", "enum", "builder"), ENUM_COLUMNS, ids=_ids())
def test_value_outside_enum_is_rejected_with_named_check(
    engine: Engine,
    table: str,
    column: str,
    enum: type[Enum],
    builder: Callable[..., tuple[object, ...]],
) -> None:
    rows = builder(1, **{column: "BAD"})
    with expect_db_error(_CHECK_VIOLATION) as info:
        insert_and_commit(engine, *rows)
    assert info.constraint == f"ck_{table}_{column}"


def test_wide_values_insert_without_truncation(engine: Engine) -> None:
    """D-09 / F-403: the six widened columns hold values longer than 16 characters."""
    tradifi = "TRADIFI_PERPETUAL"  # 17
    cancel_only = "TRADING_CANCEL_ONLY"  # 19
    assert len(tradifi) > 16 and len(cancel_only) > 16
    insert_and_commit(
        engine,
        make_symbol_metadata(contract_type=tradifi, status=cancel_only),
        make_position(1, status=PositionStatus.LIQUIDATION_REPORTED.value),
    )
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT contract_type, status FROM symbol_metadata WHERE symbol = 'BTCUSDT'")
        ).one()
    assert tuple(row) == (tradifi, cancel_only)


def test_widened_columns_are_varchar_32(engine: Engine) -> None:
    columns = [
        ("signals", "status"),
        ("trade_plans", "status"),
        ("orders", "local_status"),
        ("positions", "status"),
        ("symbol_metadata", "contract_type"),
        ("symbol_metadata", "status"),
    ]
    with engine.connect() as conn:
        for table, column in columns:
            length = conn.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            ).scalar_one()
            assert length == 32, (table, column, length)


def test_orm_widths_match_database() -> None:
    """The ORM declares the same 32-character widths the migration applies."""
    for model, column in [
        (SignalRow, "status"),
        (TradePlanRow, "status"),
        (OrderRow, "local_status"),
        (PositionRow, "status"),
        (SymbolMetadata, "contract_type"),
        (SymbolMetadata, "status"),
    ]:
        assert model.__table__.c[column].type.length == 32, (model.__name__, column)  # type: ignore[attr-defined]
