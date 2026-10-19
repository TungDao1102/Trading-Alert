"""Sized realized risk and protective quantity persistence (Phase 19, plan 19-09, D-20, D-22).

The ENTRY intent stores the sizing-time realized risk at approval consumption (one INSERT,
migration 0005), protective intents can carry an explicit quantity (TP1), and analytics reads
the stored figure back so `NO_RISK_VALUE` goes away while live R stays
INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS).

Every PostgreSQL test runs on a generated `t17_<hex>_test` database cloned from an
alembic-built template (`tests/pg_support.py`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import fields
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from src.analytics import live_outcomes
from src.analytics.live_outcomes import (
    SizedRisk,
    sized_risks_from_entry_intents,
)
from src.analytics.types import AnalyticsInputError, IncompleteReason
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.intent_store import ExecutionIntentStore, IntentRecord
from src.execution.order_ids import derive_algo_client_id

from tests.support.intent_store_fakes import (
    AlwaysWinsIntentStore,
    BarrierBeforeConsume,
    CrashAfter,
    FailingIntentStore,
    InMemoryExecutionIntentStore,
)
from tests.test_analytics_live_outcomes import _Rows
from tests.test_execution_exactly_once_pg import (
    APPROVAL_ID,
    CASE,
    ENTRY_CLIENT_ID,
    NOW_UTC,
    PLAN_HASH,
    _entry_row,
    _seed_parent_chain,
    _store_on,
)
from tests.test_execution_manager import FakeExecutionAdapter, _run_plan

SIZED = Decimal("9.876")
TP1_QUANTITY = Decimal("0.005")
SL_ALGO_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role=OrderRole.STOP_LOSS.value)
TP1_ALGO_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role=OrderRole.TAKE_PROFIT_1.value)


def _consume_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "approval_id": APPROVAL_ID,
        "trade_plan_id": CASE["trade_plan_id"],
        "plan_hash": PLAN_HASH,
        "client_order_id": ENTRY_CLIENT_ID,
        "symbol": CASE["symbol"],
        "side": "BUY",
        "intended_quantity": Decimal("2.415"),
        "intended_price": Decimal(str(CASE["expected_limit_price"])),
        "now_utc": NOW_UTC,
    }
    kwargs.update(overrides)
    return kwargs


def _protective_kwargs(role: str, algo_id: str, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "approval_id": APPROVAL_ID,
        "role": role,
        "trade_plan_id": CASE["trade_plan_id"],
        "plan_hash": PLAN_HASH,
        "algo_client_id": algo_id,
        "symbol": CASE["symbol"],
        "side": "SELL",
        "intended_price": Decimal("98"),
        "now_utc": NOW_UTC,
    }
    kwargs.update(overrides)
    return kwargs


def _plain_record(**overrides: Any) -> IntentRecord:
    fields: dict[str, Any] = {
        "approval_id": "A-1",
        "role": OrderRole.ENTRY.value,
        "trade_plan_id": "PLAN-A",
        "plan_hash": "h" * 64,
        "client_order_id": "x-1EN",
        "algo_client_id": None,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "intended_quantity": Decimal("2.0"),
        "intended_price": Decimal("100"),
        "intent_status": ExecutionIntentStatus.INTENDED,
        "exchange_order_id": None,
        "exchange_status": None,
        "outcome": None,
        "intended_at_utc": NOW_UTC,
        "sent_at_utc": None,
        "resolved_at_utc": None,
        "updated_at_utc": NOW_UTC,
        "sized_realized_risk": SIZED,
    }
    fields.update(overrides)
    return IntentRecord(**fields)


# --------------------------------------------------------------------------- #
# Task 1: the sized figure is written at consumption and read back.
# --------------------------------------------------------------------------- #


def test_consume_stores_sized_risk_and_get_entry_reads_it_back(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
        record = store.get_entry(approval_id=APPROVAL_ID)
        assert record is not None
        assert record.sized_realized_risk == SIZED
        assert _entry_row(engine)["sized_realized_risk"] == SIZED
        unresolved = store.list_unresolved_intents()
        assert [r.sized_realized_risk for r in unresolved] == [SIZED]


def test_consume_without_the_argument_stores_null(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs())
        record = store.get_entry(approval_id=APPROVAL_ID)
        assert record is not None
        assert record.sized_realized_risk is None
        assert _entry_row(engine)["sized_realized_risk"] is None


def test_replayed_consume_does_not_overwrite_the_stored_figure(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
        assert not store.consume_and_record_entry_intent(
            **_consume_kwargs(sized_realized_risk=Decimal("1.5"))
        )
        record = store.get_entry(approval_id=APPROVAL_ID)
        assert record is not None
        assert record.sized_realized_risk == SIZED


def test_stored_entry_rows_make_no_risk_value_go_away_but_live_r_stays_incomplete(
    pg_db: str,
) -> None:
    """Round trip: store -> IntentRecord -> SizedRisk -> normalize_live_outcomes."""
    rows = _Rows()
    # PLAN-A is the closed plan (2.0 filled): store its figure under its own plan id.
    plan_a = next(plan for plan in rows.plans if plan.trade_plan_id == "PLAN-A")
    assert plan_a.trade_plan_id != CASE["trade_plan_id"]
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        store.consume_and_record_entry_intent(
            **_consume_kwargs(
                intended_quantity=Decimal("2.0"), sized_realized_risk=Decimal("10.00")
            )
        )
        stored = store.get_entry(approval_id=APPROVAL_ID)
    assert stored is not None
    mapping = sized_risks_from_entry_intents([stored])
    assert mapping == {
        CASE["trade_plan_id"]: SizedRisk(
            realized_risk=Decimal("10.00"), planned_quantity=Decimal("2.0")
        )
    }
    # Re-key onto the analytics fixture's plan so the stored figure feeds the normalizer.
    rekeyed = {"PLAN-A": mapping[CASE["trade_plan_id"]]}
    with_figure = rows.run(sized_risks=rekeyed)
    assert ("SIG-A", IncompleteReason.NO_RISK_VALUE) not in with_figure.incomplete
    assert ("SIG-A", IncompleteReason.UNVERIFIED_EXCHANGE_SEMANTICS) in with_figure.incomplete
    assert live_outcomes.LIVE_NET_PNL_SEMANTICS_VERIFIED is False
    without = rows.run(sized_risks={})
    assert ("SIG-A", IncompleteReason.NO_RISK_VALUE) in without.incomplete


def test_sized_risks_from_entry_intents_skips_other_roles_and_missing_figures() -> None:
    entry = _plain_record()
    no_figure = _plain_record(trade_plan_id="PLAN-B", sized_realized_risk=None)
    no_quantity = _plain_record(trade_plan_id="PLAN-C", intended_quantity=None)
    stop = _plain_record(
        role=OrderRole.STOP_LOSS.value,
        trade_plan_id="PLAN-D",
        client_order_id=None,
        algo_client_id="x-1SL",
        sized_realized_risk=None,
    )
    mapping = sized_risks_from_entry_intents([entry, no_figure, no_quantity, stop])
    assert mapping == {
        "PLAN-A": SizedRisk(realized_risk=SIZED, planned_quantity=Decimal("2.0")),
    }


def test_normalize_without_the_mapping_still_reports_no_risk_value() -> None:
    result = _Rows().run(sized_risks={})
    assert ("SIG-A", IncompleteReason.NO_RISK_VALUE) in result.incomplete
    assert all(o.realized_risk is None for o in result.outcomes)


async def test_manager_passes_the_risk_verdicts_sized_realized_risk_to_consume() -> None:
    class _Recording(InMemoryExecutionIntentStore):
        def __init__(self) -> None:
            super().__init__()
            self.consume_kwargs: list[dict[str, Any]] = []

        def consume_and_record_entry_intent(self, **kwargs: Any) -> bool:
            self.consume_kwargs.append(dict(kwargs))
            return super().consume_and_record_entry_intent(**kwargs)

    store = _Recording()
    outcome = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    assert outcome.is_no_trade is False
    assert len(store.consume_kwargs) == 1
    passed = store.consume_kwargs[0]["sized_realized_risk"]
    assert isinstance(passed, Decimal)
    assert passed > 0
    entry = store.get_entry(approval_id=store.consume_kwargs[0]["approval_id"])
    assert entry is not None
    assert entry.sized_realized_risk == passed
    assert entry.intended_quantity is not None


# --------------------------------------------------------------------------- #
# Task 2: protective intents with an explicit quantity (D-20).
# --------------------------------------------------------------------------- #


def test_pg_protective_intent_stores_the_explicit_quantity_only_when_given(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs())
        assert store.record_protective_intent(
            **_protective_kwargs(
                OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID, intended_quantity=TP1_QUANTITY
            )
        )
        assert store.record_protective_intent(
            **_protective_kwargs(OrderRole.STOP_LOSS.value, SL_ALGO_ID)
        )
        with engine.connect() as conn:
            stored = dict(
                conn.execute(
                    text(
                        "SELECT role, intended_quantity FROM execution_intents "
                        "WHERE approval_id = :a"
                    ),
                    {"a": APPROVAL_ID},
                ).all()
            )
        assert stored[OrderRole.TAKE_PROFIT_1.value] == TP1_QUANTITY
        assert stored[OrderRole.STOP_LOSS.value] is None
        assert stored[OrderRole.ENTRY.value] == Decimal("2.415")
        # The unresolved listing (what recovery walks) carries the same quantities.
        by_role = {r.role: r.intended_quantity for r in store.list_unresolved_intents()}
        assert by_role[OrderRole.TAKE_PROFIT_1.value] == TP1_QUANTITY
        assert by_role[OrderRole.STOP_LOSS.value] is None


def test_pg_protective_quantity_must_be_positive(pg_db: str) -> None:
    from src.persistence.errors import IntentStateConflict

    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs())
        with pytest.raises(IntentStateConflict):
            store.record_protective_intent(
                **_protective_kwargs(
                    OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID, intended_quantity=Decimal("0")
                )
            )


def test_in_memory_store_keeps_both_new_fields() -> None:
    store = InMemoryExecutionIntentStore()
    assert store.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
    store.record_protective_intent(
        **_protective_kwargs(
            OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID, intended_quantity=TP1_QUANTITY
        )
    )
    store.record_protective_intent(**_protective_kwargs(OrderRole.STOP_LOSS.value, SL_ALGO_ID))
    entry = store.get_entry(approval_id=APPROVAL_ID)
    assert entry is not None and entry.sized_realized_risk == SIZED
    tp1 = store.get_intent(approval_id=APPROVAL_ID, role=OrderRole.TAKE_PROFIT_1.value)
    stop = store.get_intent(approval_id=APPROVAL_ID, role=OrderRole.STOP_LOSS.value)
    assert tp1 is not None and tp1.intended_quantity == TP1_QUANTITY
    assert tp1.sized_realized_risk is None
    assert stop is not None and stop.intended_quantity is None


class _SpyStore(InMemoryExecutionIntentStore):
    """Records the kwargs of the two methods that gained a parameter."""

    def __init__(self) -> None:
        super().__init__()
        self.consume_calls: list[dict[str, Any]] = []
        self.protective_calls: list[dict[str, Any]] = []

    def consume_and_record_entry_intent(self, **kwargs: Any) -> bool:
        self.consume_calls.append(dict(kwargs))
        return super().consume_and_record_entry_intent(**kwargs)

    def record_protective_intent(self, **kwargs: Any) -> bool:
        self.protective_calls.append(dict(kwargs))
        return super().record_protective_intent(**kwargs)


_WRAPPERS: dict[str, Callable[[ExecutionIntentStore], ExecutionIntentStore]] = {
    "CrashAfter": lambda inner: CrashAfter(inner, step="finalize"),
    "BarrierBeforeConsume": lambda inner: BarrierBeforeConsume(inner, barrier=threading.Barrier(1)),
    "FailingIntentStore": lambda inner: FailingIntentStore("mark_sent", OSError(), inner=inner),
}


@pytest.mark.parametrize("name", sorted(_WRAPPERS))
def test_wrapping_doubles_forward_both_new_arguments(name: str) -> None:
    spy = _SpyStore()
    store = _WRAPPERS[name](spy)
    assert store.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
    assert store.record_protective_intent(
        **_protective_kwargs(
            OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID, intended_quantity=TP1_QUANTITY
        )
    )
    assert spy.consume_calls[0]["sized_realized_risk"] == SIZED
    assert spy.protective_calls[0]["intended_quantity"] == TP1_QUANTITY
    entry = spy.get_entry(approval_id=APPROVAL_ID)
    assert entry is not None and entry.sized_realized_risk == SIZED


def test_always_wins_double_accepts_both_new_arguments() -> None:
    store = AlwaysWinsIntentStore()
    assert store.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
    assert store.record_protective_intent(
        **_protective_kwargs(
            OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID, intended_quantity=TP1_QUANTITY
        )
    )


async def test_manager_stop_loss_intent_is_a_close_position_leg_with_no_quantity() -> None:
    spy = _SpyStore()
    outcome = await _run_plan(FakeExecutionAdapter(), intent_store=spy)
    assert outcome.is_no_trade is False
    stops = [c for c in spy.protective_calls if c["role"] == OrderRole.STOP_LOSS.value]
    assert len(stops) == 1
    assert stops[0]["intended_quantity"] is None  # passed explicitly (D-10)
    assert spy.consume_calls[0]["sized_realized_risk"] > 0


# --------------------------------------------------------------------------- #
# Task 3: constraint, store parity and fail-closed read-back.
# --------------------------------------------------------------------------- #

_PROTECTIVE_INSERT_WITH_SIZED = text(
    "INSERT INTO execution_intents (approval_id, role, trade_plan_id, plan_hash, "
    "algo_client_id, symbol, side, intended_price, sized_realized_risk, "
    "intent_status, outcome_recorded, intended_at_utc, updated_at_utc) "
    "VALUES (:a, 'STOP_LOSS', :p, :h, :c, :s, 'SELL', 98, 5, 'INTENDED', false, :t, :t)"
)


def test_database_check_rejects_a_sized_figure_on_a_protective_row(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs())
        with pytest.raises(IntegrityError) as raised, engine.begin() as conn:
            conn.execute(
                _PROTECTIVE_INSERT_WITH_SIZED,
                {
                    "a": APPROVAL_ID,
                    "p": CASE["trade_plan_id"],
                    "h": PLAN_HASH,
                    "c": SL_ALGO_ID,
                    "s": CASE["symbol"],
                    "t": NOW_UTC,
                },
            )
        assert "ck_execution_intents_sized_realized_risk" in str(raised.value)


def test_store_never_writes_the_sized_figure_on_protective_rows(pg_db: str) -> None:
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
        for role, algo_id in (
            (OrderRole.STOP_LOSS.value, SL_ALGO_ID),
            (OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID),
        ):
            assert store.record_protective_intent(
                **_protective_kwargs(role, algo_id, intended_quantity=None)
            )
        with engine.connect() as conn:
            sized = conn.execute(
                text(
                    "SELECT count(*) FROM execution_intents "
                    "WHERE approval_id = :a AND role <> 'ENTRY' AND sized_realized_risk IS NOT NULL"
                ),
                {"a": APPROVAL_ID},
            ).scalar_one()
        assert sized == 0


def test_in_memory_and_pg_stores_return_equal_records_for_the_same_calls(pg_db: str) -> None:
    memory = InMemoryExecutionIntentStore()
    assert memory.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
    memory.record_protective_intent(
        **_protective_kwargs(
            OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID, intended_quantity=TP1_QUANTITY
        )
    )
    with _store_on(pg_db) as (engine, store):
        _seed_parent_chain(engine)
        assert store.consume_and_record_entry_intent(**_consume_kwargs(sized_realized_risk=SIZED))
        store.record_protective_intent(
            **_protective_kwargs(
                OrderRole.TAKE_PROFIT_1.value, TP1_ALGO_ID, intended_quantity=TP1_QUANTITY
            )
        )
        pg_rows = {r.role: r for r in store.list_unresolved_intents()}
    memory_rows = {r.role: r for r in memory.list_unresolved_intents()}
    assert pg_rows.keys() == memory_rows.keys() == {"ENTRY", "TAKE_PROFIT_1"}
    for role, pg_row in pg_rows.items():
        for field in fields(IntentRecord):
            assert getattr(pg_row, field.name) == getattr(memory_rows[role], field.name), (
                role,
                field.name,
            )


def test_two_entry_rows_of_one_plan_with_different_figures_fail_closed() -> None:
    first = _plain_record(approval_id="A-1", sized_realized_risk=Decimal("9.876"))
    same = _plain_record(approval_id="A-2", sized_realized_risk=Decimal("9.876000"))
    other = _plain_record(approval_id="A-3", sized_realized_risk=Decimal("9.877"))
    assert sized_risks_from_entry_intents([first, same]) == {
        "PLAN-A": SizedRisk(realized_risk=Decimal("9.876"), planned_quantity=Decimal("2.0"))
    }
    with pytest.raises(AnalyticsInputError):
        sized_risks_from_entry_intents([first, other])
