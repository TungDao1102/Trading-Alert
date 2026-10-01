"""ORM row builders for the Phase 17 PostgreSQL integrity tests.

Rows are built directly (not through the domain mappers) because several tests need
values the domain constructors would refuse (a zero stop-loss, an out-of-enum status);
the point of those tests is that PostgreSQL refuses what a bypassing writer sends.

Every builder has GLOSSARY-valid defaults and takes keyword overrides. `hexid(n)`
produces a stable 64-hex identifier so parents and children can reference each other.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from psycopg import Error as PsycopgError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from src.db.models import (
    ApprovalRow,
    FillRow,
    JournalEventRow,
    OrderRow,
    PositionRow,
    SignalRow,
    SymbolMetadata,
    TradePlanRow,
)

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 19, 16, 0, tzinfo=UTC)


def hexid(n: int, width: int = 64) -> str:
    """Deterministic lowercase-hex identifier of `width` characters from an int."""
    return f"{n:x}".rjust(width, "0")


def make_signal(n: int = 1, **overrides: Any) -> SignalRow:
    values: dict[str, Any] = {
        "signal_id": hexid(n),
        "strategy_id": "trend-pullback",
        "strategy_version": "v1.0.0",
        "parameter_set_id": "baseline-v1",
        "parameter_set_hash": "b" * 64,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup_type": "TREND_PULLBACK_LONG",
        "source_timeframe": "1h",
        "source_candle_close_utc": T0,
        "detected_at_utc": T0,
        "status": "DETECTED",
        "expires_at_utc": T1,
        "invalidated_at_utc": None,
    }
    values.update(overrides)
    return SignalRow(**values)


def make_plan(n: int = 1, signal_n: int = 1, **overrides: Any) -> TradePlanRow:
    values: dict[str, Any] = {
        "trade_plan_id": hexid(0x1000 + n),
        "signal_id": hexid(signal_n),
        "trade_plan_version": "v1.0.0",
        "entry_model": "LIMIT_ZONE",
        "entry_min_price": Decimal("50000"),
        "entry_max_price": Decimal("50100"),
        "stop_loss_price": Decimal("49500"),
        "take_profit_json": "[]",
        "invalidation_rule_json": "{}",
        "expiry_utc": T1,
        "expected_rr_json": "{}",
        "risk_rate": Decimal("0.005"),
        "risk_budget": Decimal("4"),
        "suggested_quantity": Decimal("0.08"),
        "quantity_before_rounding": Decimal("0.08"),
        "quantity_after_rounding": Decimal("0.08"),
        "quantization_decision": "ACCEPTED",
        "plan_hash": "d" * 64,
        "status": "READY",
        "created_at_utc": T0,
    }
    values.update(overrides)
    return TradePlanRow(**values)


def make_approval(
    n: int = 1, plan_n: int = 1, signal_n: int = 1, **overrides: Any
) -> ApprovalRow:
    values: dict[str, Any] = {
        "approval_id": hexid(0x2000 + n),
        "trade_plan_id": hexid(0x1000 + plan_n),
        "signal_id": hexid(signal_n),
        "action": "APPROVE",
        "result": "PENDING",
        "status": "PENDING",
        "approval_token_hash": hexid(0x3000 + n),
        "requested_at_utc": T0,
        "acted_at_utc": None,
        "actor_id": "operator",
        "telegram_message_id": None,
        "request_hash": "e" * 64,
    }
    values.update(overrides)
    return ApprovalRow(**values)


def make_position(n: int = 1, **overrides: Any) -> PositionRow:
    values: dict[str, Any] = {
        "position_id": hexid(0x4000 + n),
        "symbol": "BTCUSDT",
        "position_side": "BOTH",
        "mode": "ONE_WAY",
        "quantity": Decimal("0.08"),
        "entry_price": Decimal("50050"),
        "break_even_price": Decimal("50060"),
        "unrealized_pnl": Decimal("0"),
        "realized_pnl": Decimal("0"),
        "opened_at_utc": T0,
        "updated_at_utc": T0,
        "closed_at_utc": None,
        "status": "OPEN",
    }
    values.update(overrides)
    return PositionRow(**values)


def make_order(n: int = 1, plan_n: int | None = 1, **overrides: Any) -> OrderRow:
    values: dict[str, Any] = {
        "order_id": hexid(0x5000 + n),
        "trade_plan_id": hexid(0x1000 + plan_n) if plan_n is not None else None,
        "position_id": None,
        "parent_order_id": None,
        "order_role": "ENTRY",
        "exchange": "BINANCE_USDM",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "order_type": "LIMIT",
        "time_in_force": "GTC",
        "quantity": Decimal("0.08"),
        "price": Decimal("50050"),
        "stop_price": None,
        "close_position": False,
        "reduce_only": False,
        "client_order_id": f"x-{n:032x}EN",
        "exchange_order_id": None,
        "algo_client_id": None,
        "exchange_status": "NEW",
        "local_status": "NEW",
        "submitted_at_utc": T0,
        "updated_at_utc": T0,
        "canceled_at_utc": None,
    }
    values.update(overrides)
    return OrderRow(**values)


def make_fill(n: int = 1, order_n: int = 1, **overrides: Any) -> FillRow:
    values: dict[str, Any] = {
        "fill_id": hexid(0x6000 + n),
        "order_id": hexid(0x5000 + order_n),
        "exchange_trade_id": f"trade-{n}",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "fill_price": Decimal("50050"),
        "fill_quantity": Decimal("0.08"),
        "quote_quantity": Decimal("4004"),
        "commission": Decimal("0.00008"),
        "commission_asset": "USDT",
        "realized_pnl": Decimal("0"),
        "fill_time_utc": T0,
        "is_maker": False,
    }
    values.update(overrides)
    return FillRow(**values)


def make_journal(n: int = 1, **overrides: Any) -> JournalEventRow:
    values: dict[str, Any] = {
        "journal_event_id": hexid(0x7000 + n),
        "occurred_at_utc": T0,
        "event_type": "SIGNAL_DETECTED",
        "entity_type": "signal",
        "entity_id": hexid(1),
        "correlation_id": "corr-1",
        "signal_id": None,
        "trade_plan_id": None,
        "approval_id": None,
        "order_id": None,
        "position_id": None,
        "payload_json": "{}",
        "created_at_utc": T0,
    }
    values.update(overrides)
    return JournalEventRow(**values)


def make_symbol_metadata(**overrides: Any) -> SymbolMetadata:
    values: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "metadata_observed_at_utc": T0,
        "status": "TRADING",
        "contract_type": "PERPETUAL",
        "onboard_time_utc": None,
        "price_tick_size": Decimal("0.1"),
        "quantity_step_size": Decimal("0.001"),
        "min_quantity": Decimal("0.001"),
        "max_quantity": None,
        "min_notional": Decimal("5"),
        "notional_constraints_json": "{}",
        "order_capabilities_json": "{}",
        "position_mode_snapshot_json": "{}",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "margin_asset": "USDT",
    }
    values.update(overrides)
    return SymbolMetadata(**values)


def insert_and_commit(engine: Engine, *rows: object) -> None:
    """Insert `rows` in one transaction (dependency order = argument order)."""
    with Session(engine, expire_on_commit=False) as session:
        for row in rows:
            session.add(row)
            session.flush()
        session.commit()


def seed_chain(engine: Engine) -> None:
    """Signal 1 -> plan 1 -> approval 1 -> position 1 -> order 1 (entry) committed."""
    insert_and_commit(
        engine,
        make_signal(1),
        make_plan(1, 1),
        make_approval(1, 1, 1),
        make_position(1),
        make_order(1, 1, position_id=hexid(0x4001)),
    )


class ViolationInfo:
    """Name, SQLSTATE and message of the PostgreSQL error a statement raised."""

    def __init__(self) -> None:
        self.constraint: str | None = None
        self.sqlstate: str | None = None
        self.message: str = ""


@contextmanager
def expect_db_error(sqlstate: str | None = None) -> Iterator[ViolationInfo]:
    """Assert the block raises a DB error; expose its constraint name and SQLSTATE.

    Works for IntegrityError (constraint violations), InternalError / DataError and
    trigger-raised errors alike (all are `sqlalchemy.exc.DBAPIError`).
    """
    info = ViolationInfo()
    try:
        yield info
    except DBAPIError as exc:
        orig = exc.orig
        assert isinstance(orig, PsycopgError), type(orig)
        info.constraint = orig.diag.constraint_name
        info.sqlstate = orig.sqlstate
        info.message = orig.diag.message_primary or str(orig)
        if sqlstate is not None:
            assert info.sqlstate == sqlstate, (info.sqlstate, info.message)
    else:
        raise AssertionError("expected a database error, none was raised")
