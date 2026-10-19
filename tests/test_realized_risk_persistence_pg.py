"""Sized realized risk and protective quantity persistence (Phase 19, plan 19-09, D-20, D-22).

The ENTRY intent stores the sizing-time realized risk at approval consumption (one INSERT,
migration 0005), protective intents can carry an explicit quantity (TP1), and analytics reads
the stored figure back so `NO_RISK_VALUE` goes away while live R stays
INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS).

Every PostgreSQL test runs on a generated `t17_<hex>_test` database cloned from an
alembic-built template (`tests/pg_support.py`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.analytics import live_outcomes
from src.analytics.live_outcomes import (
    SizedRisk,
    sized_risks_from_entry_intents,
)
from src.analytics.types import IncompleteReason
from src.domain.enums import ExecutionIntentStatus, OrderRole
from src.execution.intent_store import IntentRecord
from src.execution.order_ids import derive_algo_client_id

from tests.support.intent_store_fakes import (
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
