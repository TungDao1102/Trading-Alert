"""Unique, partial-unique, RESTRICT foreign-key and quantity CHECK tests (D-06..D-08, F-404).

Every violation is provoked with ORM rows that bypass the Python approval/binding
checks on purpose: the database must refuse a duplicate decision, a duplicate client
id, an orphan or a non-positive price even when a caller skips its own validation.
Constraint names are read from the psycopg diagnostics (`diag.constraint_name`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from src.db.models import (
    ApprovalRow,
    OrderRow,
    PositionRow,
    SignalRow,
    TradePlanRow,
)
from src.persistence.engine import make_sync_engine

from tests.support.pg_rows import (
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
    seed_chain,
)

_UNIQUE_VIOLATION = "23505"
_FK_VIOLATION = "23503"
_CHECK_VIOLATION = "23514"


@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
# approvals: token hash unique, one decided approval per plan (D-06, F-404)
# --------------------------------------------------------------------------- #


def test_duplicate_approval_token_hash_is_rejected(engine: Engine) -> None:
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_plan(2, 1),
        make_approval(1, 1, 1, approval_token_hash="f" * 64),
    )
    with expect_db_error(_UNIQUE_VIOLATION) as info:
        insert_and_commit(engine, make_approval(2, 2, 1, approval_token_hash="f" * 64))
    assert info.constraint == "uq_approvals_token_hash"


def test_second_decided_approval_for_one_plan_is_rejected(engine: Engine) -> None:
    """Research A4 on a real server: the partial unique index guards UPDATEs too."""
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_approval(1, 1, 1),
        make_approval(2, 1, 1),
    )  # two PENDING rows for one plan coexist
    with Session(engine) as session:
        session.execute(
            update(ApprovalRow)
            .where(ApprovalRow.approval_id == hexid(0x2001))
            .values(status="APPROVED", result="APPROVED")
        )
        session.commit()  # first decision succeeds
    with expect_db_error(_UNIQUE_VIOLATION) as info, Session(engine) as session:
        session.execute(
            update(ApprovalRow)
            .where(ApprovalRow.approval_id == hexid(0x2002))
            .values(status="SKIPPED", result="SKIPPED")
        )
        session.commit()
    assert info.constraint == "uq_approvals_one_decided_per_plan"


def _decide_row(engine: Engine, approval_n: int, status: str) -> None:
    with Session(engine) as session:
        session.execute(
            update(ApprovalRow)
            .where(ApprovalRow.approval_id == hexid(0x2000 + approval_n))
            .values(status=status, result=status)
        )
        session.commit()


def test_both_pending_siblings_of_a_plan_may_be_expired(engine: Engine) -> None:
    """G4-042 (D-16): EXPIRED rows are outside the index, so the restart sweep can expire both."""
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_approval(1, 1, 1),
        make_approval(2, 1, 1),
    )

    _decide_row(engine, 1, "EXPIRED")
    _decide_row(engine, 2, "EXPIRED")  # would violate the 0004 predicate `status <> 'PENDING'`

    with Session(engine) as session:
        statuses = (
            session.execute(text("SELECT status FROM approvals ORDER BY approval_id"))
            .scalars()
            .all()
        )
    assert statuses == ["EXPIRED", "EXPIRED"]


def test_the_index_still_allows_only_one_approved_or_skipped_row_per_plan(
    engine: Engine,
) -> None:
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_approval(1, 1, 1),
        make_approval(2, 1, 1),
        make_approval(3, 1, 1),
    )
    _decide_row(engine, 1, "EXPIRED")
    _decide_row(engine, 2, "SKIPPED")  # an EXPIRED sibling does not count against the index

    with expect_db_error(_UNIQUE_VIOLATION) as info:
        _decide_row(engine, 3, "APPROVED")
    assert info.constraint == "uq_approvals_one_decided_per_plan"


def test_the_index_alone_does_not_refuse_an_expired_row_next_to_a_decided_one(
    engine: Engine,
) -> None:
    """That refusal is the store's rule (PgApprovalStore._decide), not the index's."""
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_approval(1, 1, 1),
        make_approval(2, 1, 1),
    )
    _decide_row(engine, 1, "APPROVED")

    _decide_row(engine, 2, "EXPIRED")  # accepted by the index; the store refuses it first


def test_decided_approvals_on_different_plans_coexist(engine: Engine) -> None:
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_plan(2, 1),
        make_approval(1, 1, 1, status="APPROVED", result="APPROVED"),
        make_approval(2, 2, 1, status="SKIPPED", result="SKIPPED"),
    )


# --------------------------------------------------------------------------- #
# orders: client ids unique when present (D-06)
# --------------------------------------------------------------------------- #


def _seed_plan(engine: Engine) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))


def test_duplicate_client_order_id_is_rejected(engine: Engine) -> None:
    _seed_plan(engine)
    insert_and_commit(engine, make_order(1, 1, client_order_id="dup-client"))
    with expect_db_error(_UNIQUE_VIOLATION) as info:
        insert_and_commit(engine, make_order(2, 1, client_order_id="dup-client"))
    assert info.constraint == "uq_orders_client_order_id"


def test_duplicate_algo_client_id_is_rejected(engine: Engine) -> None:
    _seed_plan(engine)
    insert_and_commit(engine, make_order(1, 1, client_order_id=None, algo_client_id="dup-algo"))
    with expect_db_error(_UNIQUE_VIOLATION) as info:
        insert_and_commit(engine, make_order(2, 1, client_order_id=None, algo_client_id="dup-algo"))
    assert info.constraint == "uq_orders_algo_client_id"


def test_null_client_ids_may_repeat(engine: Engine) -> None:
    _seed_plan(engine)
    insert_and_commit(
        engine,
        make_order(1, 1, client_order_id=None, algo_client_id=None),
        make_order(2, 1, client_order_id=None, algo_client_id=None),
    )


# --------------------------------------------------------------------------- #
# foreign keys: ON DELETE RESTRICT, orphans refused (D-07)
# --------------------------------------------------------------------------- #

_FK_NAMES = [
    "fk_trade_plans_signal_id",
    "fk_approvals_trade_plan_id",
    "fk_approvals_signal_id",
    "fk_orders_trade_plan_id",
    "fk_orders_position_id",
    "fk_orders_parent_order_id",
    "fk_fills_order_id",
    "fk_journal_events_signal_id",
    "fk_journal_events_trade_plan_id",
    "fk_journal_events_approval_id",
    "fk_journal_events_order_id",
    "fk_journal_events_position_id",
]


def test_all_listed_foreign_keys_exist_and_restrict_deletes(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conname, confdeltype FROM pg_constraint "
                "WHERE contype = 'f' AND conname = ANY(:names)"
            ),
            {"names": _FK_NAMES},
        ).all()
    assert {r[0] for r in rows} == set(_FK_NAMES)
    assert {r[1] for r in rows} == {"r"}  # 'r' = RESTRICT


def test_short_id_mapping_keeps_no_plan_foreign_key(engine: Engine) -> None:
    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE contype = 'f' AND conrelid = 'short_id_mapping'::regclass"
            )
        ).scalar_one()
    assert count == 0


_Orphan = Callable[[], tuple[object, ...]]
_ORPHANS: list[tuple[str, _Orphan]] = [
    ("fk_trade_plans_signal_id", lambda: (make_plan(9, 999),)),
    ("fk_approvals_trade_plan_id", lambda: (make_approval(9, 999, 1),)),
    ("fk_approvals_signal_id", lambda: (make_approval(9, 1, 999),)),
    ("fk_orders_trade_plan_id", lambda: (make_order(9, 999),)),
    (
        "fk_orders_position_id",
        lambda: (make_order(9, 1, position_id=hexid(0x4999)),),
    ),
    (
        "fk_orders_parent_order_id",
        lambda: (make_order(9, 1, parent_order_id=hexid(0x5999)),),
    ),
    ("fk_fills_order_id", lambda: (make_fill(9, 999),)),
    ("fk_journal_events_signal_id", lambda: (make_journal(9, signal_id=hexid(999)),)),
    (
        "fk_journal_events_trade_plan_id",
        lambda: (make_journal(9, trade_plan_id=hexid(0x1999)),),
    ),
    (
        "fk_journal_events_approval_id",
        lambda: (make_journal(9, approval_id=hexid(0x2999)),),
    ),
    ("fk_journal_events_order_id", lambda: (make_journal(9, order_id=hexid(0x5999)),)),
    (
        "fk_journal_events_position_id",
        lambda: (make_journal(9, position_id=hexid(0x4999)),),
    ),
]


@pytest.mark.parametrize(("constraint", "build"), _ORPHANS, ids=[n for n, _ in _ORPHANS])
def test_orphan_child_is_rejected(engine: Engine, constraint: str, build: _Orphan) -> None:
    insert_and_commit(engine, make_signal(1), make_plan(1, 1))
    with expect_db_error(_FK_VIOLATION) as info:
        insert_and_commit(engine, *build())
    assert info.constraint == constraint


_RestrictDelete = tuple[str, Callable[[], Any], str]
_PARENT_DELETES: list[_RestrictDelete] = [
    ("signal", lambda: delete(SignalRow).where(SignalRow.signal_id == hexid(1)), "fk_"),
    (
        "plan",
        lambda: delete(TradePlanRow).where(TradePlanRow.trade_plan_id == hexid(0x1001)),
        "fk_",
    ),
    (
        "approval",
        lambda: delete(ApprovalRow).where(ApprovalRow.approval_id == hexid(0x2001)),
        "fk_",
    ),
    (
        "position",
        lambda: delete(PositionRow).where(PositionRow.position_id == hexid(0x4001)),
        "fk_",
    ),
    (
        "order",
        lambda: delete(OrderRow).where(OrderRow.order_id == hexid(0x5001)),
        "fk_",
    ),
]


@pytest.mark.parametrize(
    ("label", "statement", "prefix"), _PARENT_DELETES, ids=[p[0] for p in _PARENT_DELETES]
)
def test_deleting_a_referenced_parent_is_restricted(
    engine: Engine, label: str, statement: Callable[[], Any], prefix: str
) -> None:
    seed_chain(engine)
    insert_and_commit(
        engine,
        make_order(2, 1, parent_order_id=hexid(0x5001)),
        make_fill(1, 1),
        make_journal(
            1,
            signal_id=hexid(1),
            trade_plan_id=hexid(0x1001),
            approval_id=hexid(0x2001),
            order_id=hexid(0x5001),
            position_id=hexid(0x4001),
        ),
    )
    with expect_db_error(_FK_VIOLATION) as info, Session(engine) as session:
        session.execute(statement())
        session.commit()
    assert info.constraint is not None and info.constraint.startswith(prefix), label


def test_short_id_mapping_for_unknown_plan_still_inserts(engine: Engine) -> None:
    from src.db.models import ShortIdMappingRow

    from tests.support.pg_rows import T0

    insert_and_commit(
        engine,
        ShortIdMappingRow(
            short_id="s" * 32,
            signal_id=hexid(404),
            trade_plan_id=hexid(0x1404),
            created_at_utc=T0,
        ),
    )


# --------------------------------------------------------------------------- #
# quantity and price CHECKs (D-08, research C4)
# --------------------------------------------------------------------------- #

_ZERO = Decimal("0")
_NEG = Decimal("-1")


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"stop_loss_price": _ZERO}, "ck_trade_plans_prices_positive"),
        ({"entry_min_price": _NEG}, "ck_trade_plans_prices_positive"),
        ({"entry_max_price": _ZERO}, "ck_trade_plans_prices_positive"),
        ({"risk_rate": _ZERO}, "ck_trade_plans_risk_positive"),
        ({"risk_budget": _ZERO}, "ck_trade_plans_risk_positive"),
        ({"suggested_quantity": _NEG}, "ck_trade_plans_quantities_nonnegative"),
        ({"quantity_before_rounding": _NEG}, "ck_trade_plans_quantities_nonnegative"),
        ({"quantity_after_rounding": _NEG}, "ck_trade_plans_quantities_nonnegative"),
    ],
)
def test_trade_plan_price_and_risk_checks(
    engine: Engine, overrides: dict[str, Decimal], constraint: str
) -> None:
    insert_and_commit(engine, make_signal(1))
    with expect_db_error(_CHECK_VIOLATION) as info:
        insert_and_commit(engine, make_plan(1, 1, **overrides))
    assert info.constraint == constraint


def test_zero_quantity_trade_plan_is_allowed(engine: Engine) -> None:
    """Quantities are >= 0: a NO_TRADE-style plan carries zero quantity (not rejected)."""
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(
            1,
            1,
            suggested_quantity=_ZERO,
            quantity_before_rounding=_ZERO,
            quantity_after_rounding=_ZERO,
        ),
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"quantity": _NEG}, "ck_orders_quantity_nonnegative"),
        ({"price": _ZERO}, "ck_orders_price_positive"),
        ({"stop_price": _ZERO}, "ck_orders_stop_price_positive"),
        ({"price": _NEG}, "ck_orders_price_positive"),
    ],
)
def test_order_quantity_and_price_checks(
    engine: Engine, overrides: dict[str, Decimal], constraint: str
) -> None:
    _seed_plan(engine)
    with expect_db_error(_CHECK_VIOLATION) as info:
        insert_and_commit(engine, make_order(1, 1, **overrides))
    assert info.constraint == constraint


def test_close_position_leg_with_zero_quantity_and_null_prices_is_allowed(
    engine: Engine,
) -> None:
    _seed_plan(engine)
    insert_and_commit(
        engine,
        make_order(
            1,
            1,
            order_role="STOP_LOSS",
            order_type="STOP_MARKET",
            quantity=_ZERO,
            price=None,
            stop_price=Decimal("49500"),
            close_position=True,
            reduce_only=False,
            client_order_id=None,
            algo_client_id="algo-1",
        ),
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"fill_quantity": _ZERO}, "ck_fills_price_quantity_positive"),
        ({"fill_price": _ZERO}, "ck_fills_price_quantity_positive"),
        ({"commission": _NEG}, "ck_fills_commission_nonnegative"),
    ],
)
def test_fill_checks(engine: Engine, overrides: dict[str, Decimal], constraint: str) -> None:
    seed_chain(engine)
    with expect_db_error(_CHECK_VIOLATION) as info:
        insert_and_commit(engine, make_fill(1, 1, **overrides))
    assert info.constraint == constraint


def test_zero_commission_fill_is_allowed(engine: Engine) -> None:
    seed_chain(engine)
    insert_and_commit(engine, make_fill(1, 1, commission=_ZERO))


def test_short_position_with_negative_quantity_is_allowed(engine: Engine) -> None:
    """C4 refinement (D051): position_amt is signed, so positions.quantity has no sign CHECK."""
    insert_and_commit(engine, make_position(1, position_side="BOTH", quantity=Decimal("-0.08")))
