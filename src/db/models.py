"""SQLAlchemy 2.0 async ORM — Phase 2 operational state + Phase 3 domain mirror.

Per D-05, this package owns *operational* state in PostgreSQL 17:
  - symbol_metadata           (versioned, never UPDATE — RESEARCH §Pattern 4)
  - collector_watermarks      (D-08 — last successful tick per symbol/class)
  - collector_gaps            (D-09 — flag-never-fabricate gap journal)
  - coverage_windows          (DATA_PIPELINE §10 — per-symbol effective range)

Phase 17 additions (plan 17-01, first slice of migration 0004):
  - approvals.consumption_status / consumed_at_utc  (explicit durable consumption)
  - execution_intents         (ExecutionIntentRow — write-ahead entry/leg intents)

Phase 17 additions (plan 17-02, rest of migration 0004): named enum/quantity CHECKs,
unique and partial unique indexes, RESTRICT foreign keys, widened status columns,
`plan_constraint_snapshots` and `system_state_events`. Every NEW 0004 constraint and
index is PostgreSQL-only (`ddl_if`) so SQLite `create_all` suites keep their DDL; the 18
indexes from migrations 0001-0003 are declared plainly under their exact names. Append-only
and terminal-state triggers live in the migration only (not ORM objects).

Phase 3 additions (plans 03-01 + 03-04, D-02):
  - signals                   (SignalRow — content-hash PK, explicit status)
  - trade_plans               (TradePlanRow — content-hash PK, explicit status)
  - approvals                 (ApprovalRow — action + result + explicit status)
  - orders                    (OrderRow — three independent identifier fields)
  - fills                     (FillRow — event, no status; unique on order+trade)
  - positions                 (PositionRow — content-hash PK, explicit status)
  - journal_events            (JournalEventRow — append-only audit events)

No OHLCV rows live here (D-05 one-way; candles live in Parquet + DuckDB).

All timestamps are `TIMESTAMPTZ` (UTC enforced at the ORM boundary).
All tick/step/notional values are `NUMERIC(38, 18)` (ENGINEERING_PRINCIPLES
Python rule — no float for exchange-sensitive values).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Single declarative base for every model in `src/db/`.

    The Alembic env (src/db/alembic/env.py) binds this Base.metadata as
    `target_metadata` so a single source of schema truth covers the
    baseline migration and every later reviewed migration.
    """


# ---------- symbol_metadata ---------------------------------------------------


class SymbolMetadata(Base):
    """Versioned snapshot of a symbol's exchangeInfo filters.

    Version key: `metadata_observed_at_utc` (PK part). Readers pin
    `observed_at <= dataset_date` to reconstruct the rules in force at
    a backtest time (RESEARCH §Pattern 4).
    """

    __tablename__ = "symbol_metadata"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    metadata_observed_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )

    # exchangeInfo status (TRADING / HALT / etc.). Source of truth: live /exchangeInfo.
    # Widened to 32 by migration 0004 (D-09, F-403): TRADIFI_PERPETUAL is 17 characters
    # and TRADING_CANCEL_ONLY 19, both real Binance values.
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Onboard time as UTC ms epoch (matches exchangeInfo.onboardDate).
    onboard_time_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Tick / step / quantity / notional — Decimal only (DATA_MODEL §5 + Pitfall 4).
    price_tick_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity_step_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    min_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    max_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    min_notional: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)

    # JSON-as-text blobs keep the schema portable across PG versions; the
    # adapter layer owns the canonical shape (RESEARCH §Pattern 1).
    notional_constraints_json: Mapped[str] = mapped_column(String, nullable=False)
    order_capabilities_json: Mapped[str] = mapped_column(String, nullable=False)
    position_mode_snapshot_json: Mapped[str] = mapped_column(String, nullable=False)

    # Asset identifiers (mirrors DATA_MODEL §2.11 — base/quote/margin assets).
    base_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    margin_asset: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (Index("ix_symbol_metadata_observed", "symbol", "metadata_observed_at_utc"),)


# ---------- collector_watermarks ---------------------------------------------


class CollectorWatermark(Base):
    """Last successful tick per (symbol, data_class) — D-08.

    `data_class` is one of: 'oi', 'funding', 'klines' (the in-house
    collector families). Atomic advance happens in the same transaction
    as the snapshot insert (RESEARCH §Pattern 3 watermark atomicity).
    """

    __tablename__ = "collector_watermarks"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    data_class: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_tick_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------- collector_gaps ---------------------------------------------------


# Sentinel symbol for tick-wide gap rows (the whole poll missed rather
# than one specific symbol). PostgreSQL implicitly forces PK columns NOT
# NULL, so a NULL symbol in the (symbol, data_class, expected_utc) PK
# would be rejected on PG (SQLite tolerates it and masked the bug).
TICK_WIDE_SYMBOL = "__TICK__"


class CollectorGap(Base):
    """Explicit gap row when a scheduled tick fails — D-09.

    Downstream MUST treat gap rows as missing, NEVER as zero / interpolated
    values. Idempotent inserts: a second gap for the same expected tick is
    a no-op via the (symbol, data_class, expected_utc) PK. Tick-wide
    failures use `TICK_WIDE_SYMBOL` (never NULL) as the symbol.
    """

    __tablename__ = "collector_gaps"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    data_class: Mapped[str] = mapped_column(String(16), primary_key=True)
    expected_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    observed_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    recorded_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_collector_gaps_class_expected", "data_class", "expected_utc"),)


# ---------- coverage_windows --------------------------------------------------


class CoverageWindow(Base):
    """PG-side authoritative per-symbol effective range (DATA_PIPELINE §10).

    The DuckDB view joins Parquet files with this table for the
    `onboard_time_utc` + status-history context that the raw store cannot
    provide on its own.
    """

    __tablename__ = "coverage_windows"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    interval: Mapped[str] = mapped_column(String(8), primary_key=True)
    historical_data_start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    historical_data_end_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    onboard_time_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status_history_json: Mapped[str] = mapped_column(String, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------- signals (Phase 3, plan 03-01) ------------------------------------


class SignalRow(Base):
    """ORM mirror of the domain Signal entity (D-02).

    PK is the content-hash `signal_id` from `ids.make_signal_id` (D-03).
    `status` stores `SignalStatus.value` (explicit, never inferred — D-11).
    `invalidated_at_utc` is nullable: NULL means "transition never happened".
    """

    __tablename__ = "signals"

    signal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parameter_set_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    setup_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    source_candle_close_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    detected_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Pre-existing indexes (0002) are declared plainly; the 0004 CHECKs are PostgreSQL-only
    # (`ddl_if`) so SQLite `create_all` suites keep their pre-0004 DDL. Names match 0004.
    __table_args__ = (
        Index("ix_signals_symbol_close", "symbol", "source_candle_close_utc"),
        Index("ix_signals_parameter_set", "parameter_set_id", "parameter_set_hash"),
        CheckConstraint(
            "status IN ('DETECTED', 'NOTIFIED', 'VIEWED', 'APPROVED', 'SKIPPED_USER', "
            "'SKIPPED_BUSY', 'EXPIRED', 'INVALIDATED')",
            name="ck_signals_status",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("direction IN ('LONG', 'SHORT')", name="ck_signals_direction").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint(
            "setup_type IN ('TREND_PULLBACK_LONG', 'TREND_PULLBACK_SHORT', "
            "'BREAKOUT_RETEST_LONG', 'BREAKOUT_RETEST_SHORT', 'RANGE_MR_LONG', 'RANGE_MR_SHORT')",
            name="ck_signals_setup_type",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "source_timeframe IN ('1m', '1h', '4h')", name="ck_signals_source_timeframe"
        ).ddl_if(dialect="postgresql"),
    )


# ---------- trade_plans (Phase 3, plan 03-04) -------------------------------


class TradePlanRow(Base):
    """ORM mirror of the domain TradePlan entity (D-02).

    PK is the content-hash `trade_plan_id` from `ids.derive_child_id` with
    discriminator `trade_plan:v1` (D-03). `status` stores
    `TradePlanStatus.value` (explicit, never inferred — D-11).
    """

    __tablename__ = "trade_plans"

    trade_plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trade_plan_version: Mapped[str] = mapped_column(String(32), nullable=False)
    entry_model: Mapped[str] = mapped_column(String(32), nullable=False)
    entry_min_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_max_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    stop_loss_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    take_profit_json: Mapped[str] = mapped_column(String, nullable=False)
    invalidation_rule_json: Mapped[str] = mapped_column(String, nullable=False)
    expiry_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_rr_json: Mapped[str] = mapped_column(String, nullable=False)
    risk_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    risk_budget: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    suggested_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity_before_rounding: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity_after_rounding: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantization_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_trade_plans_signal_id", "signal_id"),
        ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_trade_plans_signal_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "status IN ('READY', 'APPROVAL_PENDING', 'APPROVED', 'EXPIRED', 'INVALIDATED', "
            "'SUPERSEDED')",
            name="ck_trade_plans_status",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "entry_model IN ('LIMIT_ZONE', 'MARKET')", name="ck_trade_plans_entry_model"
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "entry_min_price > 0 AND entry_max_price > 0 AND stop_loss_price > 0",
            name="ck_trade_plans_prices_positive",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "risk_rate > 0 AND risk_budget > 0", name="ck_trade_plans_risk_positive"
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "suggested_quantity >= 0 AND quantity_before_rounding >= 0 "
            "AND quantity_after_rounding >= 0",
            name="ck_trade_plans_quantities_nonnegative",
        ).ddl_if(dialect="postgresql"),
    )


# ---------- approvals (Phase 3, plan 03-04) ---------------------------------


class ApprovalRow(Base):
    """ORM mirror of the domain Approval entity (D-02).

    PK is the content-hash `approval_id`. Carries `action` (ApprovalAction),
    `result` (ApprovalResult), and explicit `status` (ApprovalResult) —
    `status` alone answers state (D-11). `acted_at_utc` and
    `telegram_message_id` are nullable: NULL means "transition never
    happened" / "no Telegram message yet". `approved_quantity` is the quantity of
    the plan the request was issued for; NULL means "not recorded" (D078).
    """

    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    trade_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acted_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    telegram_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Phase 17 (D-16, D-21, research C8): explicit durable consumption state. The
    # ENTRY execution intent row is the authority; `consumed_at_utc` is the nullable
    # "transition never happened" timestamp tied to the status by a CHECK.
    consumption_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="UNCONSUMED",
        server_default=text("'UNCONSUMED'"),
    )
    consumed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Quantity of the plan the request was issued for (Phase 19 review-fix batch 4, D078,
    # migration 0006). Written once with the PENDING row; NULL = not recorded (pre-0006 rows).
    approved_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    # PostgreSQL-only integrity objects: SQLite `create_all` keeps its pre-0004 DDL
    # (`ddl_if`), PostgreSQL (alembic 0004) enforces everything. Names match the migration.
    __table_args__ = (
        Index("ix_approvals_trade_plan_id", "trade_plan_id"),
        Index("ix_approvals_signal_id", "signal_id"),
        Index("uq_approvals_token_hash", "approval_token_hash", unique=True).ddl_if(
            dialect="postgresql"
        ),
        Index(
            "uq_approvals_one_decided_per_plan",
            "trade_plan_id",
            unique=True,
            postgresql_where=text("status <> 'PENDING'"),
            sqlite_where=text("status <> 'PENDING'"),
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["trade_plan_id"],
            ["trade_plans.trade_plan_id"],
            name="fk_approvals_trade_plan_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_approvals_signal_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "action IN ('SIMULATE', 'APPROVE', 'SKIP_USER', 'SKIP_BUSY', 'CANCEL')",
            name="ck_approvals_action",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "result IN ('PENDING', 'APPROVED', 'SKIPPED', 'EXPIRED')",
            name="ck_approvals_result",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'SKIPPED', 'EXPIRED')",
            name="ck_approvals_status",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "consumption_status IN ('UNCONSUMED', 'CONSUMED')",
            name="ck_approvals_consumption_status",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(consumption_status = 'UNCONSUMED' AND consumed_at_utc IS NULL) "
            "OR (consumption_status = 'CONSUMED' AND consumed_at_utc IS NOT NULL "
            "AND status = 'APPROVED')",
            name="ck_approvals_consumption_coherent",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "approved_quantity IS NULL OR approved_quantity > 0",
            name="ck_approvals_approved_quantity",
        ).ddl_if(dialect="postgresql"),
    )


# ---------- orders (Phase 3, plan 03-04) -------------------------------------


class OrderRow(Base):
    """ORM mirror of the domain Order entity (D-02).

    PK is the content-hash `order_id`. Three independent identifier
    fields (client_order_id, exchange_order_id, algo_client_id) are
    independently nullable because Binance may use different identifiers
    for normal and algo orders (DATA_MODEL §2.7). `local_status` stores
    `OrderStatus.value`; `exchange_status` is a raw string from Binance.
    """

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    trade_plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    position_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_role: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    position_side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    close_position: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    client_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    algo_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_status: Mapped[str] = mapped_column(String(32), nullable=False)
    local_status: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    canceled_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # No CHECK on `order_role` (free-string domain field) - research A3.
    __table_args__ = (
        Index("ix_orders_trade_plan_id", "trade_plan_id"),
        Index("ix_orders_position_id", "position_id"),
        Index("ix_orders_symbol_submitted", "symbol", "submitted_at_utc"),
        Index(
            "uq_orders_client_order_id",
            "client_order_id",
            unique=True,
            postgresql_where=text("client_order_id IS NOT NULL"),
            sqlite_where=text("client_order_id IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_orders_algo_client_id",
            "algo_client_id",
            unique=True,
            postgresql_where=text("algo_client_id IS NOT NULL"),
            sqlite_where=text("algo_client_id IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["trade_plan_id"],
            ["trade_plans.trade_plan_id"],
            name="fk_orders_trade_plan_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["position_id"],
            ["positions.position_id"],
            name="fk_orders_position_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["parent_order_id"],
            ["orders.order_id"],
            name="fk_orders_parent_order_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "local_status IN ('PLANNED', 'SUBMITTING', 'NEW', 'PARTIALLY_FILLED', 'FILLED', "
            "'CANCELED', 'EXPIRED', 'REJECTED', 'UNKNOWN')",
            name="ck_orders_local_status",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("quantity >= 0", name="ck_orders_quantity_nonnegative").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint("price IS NULL OR price > 0", name="ck_orders_price_positive").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint(
            "stop_price IS NULL OR stop_price > 0", name="ck_orders_stop_price_positive"
        ).ddl_if(dialect="postgresql"),
    )


# ---------- execution_intents (Phase 17, plan 17-01) -------------------------


class ExecutionIntentRow(Base):
    """Write-ahead execution intent: one row per (approval_id, role) (D-13, D-14).

    Consuming an approval means inserting its ENTRY row in the same transaction that
    stamps `approvals.consumption_status`; a second attempt hits the primary key and
    returns the stored result. The exchange's clientOrderId dedup is NOT relied on:
    Binance only rejects a duplicate while the earlier order is still open (F-126).

    `role` carries the real `OrderRole` values (research C2). Close-position legs carry
    NULL quantity (research C4). The outcome columns hold the persisted
    `ExecutionOutcome` of an ENTRY row, with an explicit `outcome_recorded` flag (C8).
    """

    __tablename__ = "execution_intents"

    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    client_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    algo_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    intended_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    intended_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    intent_status: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome_recorded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    outcome_is_no_trade: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Sizing-time realized risk of a live entry (Phase 19, D-22, G4-008, migration 0005).
    # Written once with the ENTRY INSERT; NULL when never recorded and on protective rows.
    sized_realized_risk: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    # Why a reconciliation closed the row (Phase 20, plan 20-03, T-B, migration 0007): written only
    # by `finalize_reconciled_resolution`; NULL for every row the exchange's own answer closed.
    resolution_reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intended_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("approval_id", "role", name="pk_execution_intents"),
        UniqueConstraint("trade_plan_id", "role", name="uq_execution_intents_plan_role"),
        ForeignKeyConstraint(
            ["approval_id"],
            ["approvals.approval_id"],
            name="fk_execution_intents_approval_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["trade_plan_id"],
            ["trade_plans.trade_plan_id"],
            name="fk_execution_intents_trade_plan_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_execution_intents_client_order_id",
            "client_order_id",
            unique=True,
            postgresql_where=text("client_order_id IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_execution_intents_algo_client_id",
            "algo_client_id",
            unique=True,
            postgresql_where=text("algo_client_id IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "role IN ('ENTRY', 'STOP_LOSS', 'TAKE_PROFIT_1', 'TAKE_PROFIT_2')",
            name="ck_execution_intents_role",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "intent_status IN ('INTENDED', 'SENT', 'ACKED', 'REJECTED', 'UNKNOWN')",
            name="ck_execution_intents_status",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(role = 'ENTRY' AND client_order_id IS NOT NULL AND algo_client_id IS NULL) "
            "OR (role <> 'ENTRY' AND algo_client_id IS NOT NULL AND client_order_id IS NULL)",
            name="ck_execution_intents_client_id_by_role",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "intended_quantity IS NULL OR intended_quantity > 0",
            name="ck_execution_intents_quantity",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "intended_price IS NULL OR intended_price > 0",
            name="ck_execution_intents_price",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(outcome_recorded AND outcome_reason_code IS NOT NULL "
            "AND outcome_is_no_trade IS NOT NULL AND role = 'ENTRY') "
            "OR (NOT outcome_recorded AND outcome_reason_code IS NULL "
            "AND outcome_is_no_trade IS NULL)",
            name="ck_execution_intents_outcome",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "sized_realized_risk IS NULL OR (role = 'ENTRY' AND sized_realized_risk > 0)",
            name="ck_execution_intents_sized_realized_risk",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "resolution_reason_code IS NULL OR (intent_status = 'REJECTED' "
            "AND resolution_reason_code IN ('RECONCILED_ABSENT', 'NEVER_SENT'))",
            name="ck_execution_intents_resolution_reason",
        ).ddl_if(dialect="postgresql"),
    )


# ---------- fills (Phase 3, plan 03-04) --------------------------------------


class FillRow(Base):
    """ORM mirror of the domain Fill entity (D-02).

    PK is the content-hash `fill_id`. Fills are events with no status
    field (DATA_MODEL §2.8). Unique constraint on
    `(order_id, exchange_trade_id)` protects against duplicate fill
    ingestion.
    """

    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("order_id", "exchange_trade_id", name="uq_fills_order_trade"),
        Index("ix_fills_order_id", "order_id"),
        Index("ix_fills_symbol_time", "symbol", "fill_time_utc"),
        ForeignKeyConstraint(
            ["order_id"],
            ["orders.order_id"],
            name="fk_fills_order_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "fill_price > 0 AND fill_quantity > 0", name="ck_fills_price_quantity_positive"
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("commission >= 0", name="ck_fills_commission_nonnegative").ddl_if(
            dialect="postgresql"
        ),
    )

    fill_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    exchange_trade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    position_side: Mapped[str] = mapped_column(String(8), nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fill_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quote_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    commission: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    commission_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fill_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_maker: Mapped[bool] = mapped_column(Boolean, nullable=False)


# ---------- positions (Phase 3, plan 03-04) ----------------------------------


class PositionRow(Base):
    """ORM mirror of the domain Position entity (D-02).

    PK is the content-hash `position_id`. `status` stores
    `PositionStatus.value` (explicit, never inferred — D-11).
    `closed_at_utc` is nullable: NULL means "transition never happened".
    """

    __tablename__ = "positions"

    position_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    position_side: Mapped[str] = mapped_column(String(8), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    break_even_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # `quantity` has NO sign CHECK: position_amt is signed (negative for SHORT in one-way
    # mode), so `>= 0` would reject a legal short (research C4 refinement, recorded for D051).
    __table_args__ = (
        Index("ix_positions_symbol_status", "symbol", "status"),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSING', 'CLOSED', 'LIQUIDATION_REPORTED', 'UNKNOWN')",
            name="ck_positions_status",
        ).ddl_if(dialect="postgresql"),
    )


# ---------- journal_events (Phase 3, plan 03-04) -----------------------------


class JournalEventRow(Base):
    """ORM mirror of the domain JournalEvent entity (D-02).

    PK is the content-hash `journal_event_id`. Append-only operational
    events; never substitutes for current-state tables (DATA_MODEL §2.10).
    All linkage ids are nullable except `correlation_id` (every event
    must be correlatable).
    """

    __tablename__ = "journal_events"

    journal_event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    occurred_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trade_plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    position_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_json: Mapped[str] = mapped_column(String, nullable=False)
    created_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_journal_events_correlation", "correlation_id"),
        Index("ix_journal_events_occurred", "occurred_at_utc"),
        ForeignKeyConstraint(
            ["signal_id"],
            ["signals.signal_id"],
            name="fk_journal_events_signal_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["trade_plan_id"],
            ["trade_plans.trade_plan_id"],
            name="fk_journal_events_trade_plan_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["approval_id"],
            ["approvals.approval_id"],
            name="fk_journal_events_approval_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["order_id"],
            ["orders.order_id"],
            name="fk_journal_events_order_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["position_id"],
            ["positions.position_id"],
            name="fk_journal_events_position_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
    )


# ---------- short_id_mapping (Phase 8, plan 08-02) ----------------------------


class ShortIdMappingRow(Base):
    """Server-side short→full id mapping (D-02, 08-02).

    Telegram `callback_data` is capped at 64 bytes. The Phase-7 sender
    embedded a 32-hex-char prefix (`sha256(signal_id)[:32]`) inside
    the callback payload. Phase 8 binds real handlers, so the
    receiver must reverse the mapping deterministically across
    process restarts.

    PK is the deterministic `short_id`. The full `signal_id` and
    `trade_plan_id` are non-nullable. `created_at_utc` is UTC-aware
    (TIMESTAMPTZ at the PG boundary) and non-nullable. The receiver
    persists this row in the SAME transaction as the Approval row
    transition (atomic write — never in a separate commit).

    No auto-increment anywhere (D-03). The row exists on the single
    existing `Base`; no second declarative base is introduced.
    """

    __tablename__ = "short_id_mapping"

    short_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trade_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # No FK to trade_plans by design (0003): the mapping must survive a plan supersede.
    __table_args__ = (
        Index("ix_short_id_mapping_signal_id", "signal_id"),
        Index("ix_short_id_mapping_trade_plan_id", "trade_plan_id"),
        Index("uq_short_id_mapping_signal_trade_plan", "signal_id", "trade_plan_id", unique=True),
    )


# ---------- plan_constraint_snapshots (Phase 17, plan 17-02) -------------------


class PlanConstraintSnapshotRow(Base):
    """Write-once exchange-constraint snapshot per trade plan (D-18, D-19, EXEC-04).

    One row per `trade_plan_id` (PK and FK RESTRICT). `snapshot_json` is the canonical
    JSON and `snapshot_sha256` its digest; the digest is plan EVIDENCE, never part of
    `plan_hash`. Live inputs (margin type, leverage, equity) are NOT NULL text carrying
    the explicit sentinel `UNKNOWN` until supplied, so `live_inputs_status` says
    INCOMPLETE rather than a NULL hiding the gap. Append-only (trigger in 0004).
    """

    __tablename__ = "plan_constraint_snapshots"

    trade_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    working_type: Mapped[str] = mapped_column(String(16), nullable=False)
    margin_type: Mapped[str] = mapped_column(String(16), nullable=False)
    leverage: Mapped[str] = mapped_column(String(16), nullable=False)
    equity_used: Mapped[str] = mapped_column(String(64), nullable=False)
    live_inputs_status: Mapped[str] = mapped_column(String(16), nullable=False)
    constraints_observed_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    captured_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("trade_plan_id", name="pk_plan_constraint_snapshots"),
        ForeignKeyConstraint(
            ["trade_plan_id"],
            ["trade_plans.trade_plan_id"],
            name="fk_plan_constraint_snapshots_trade_plan_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_plan_constraint_snapshots_sha256_hex",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "live_inputs_status IN ('COMPLETE', 'INCOMPLETE')",
            name="ck_plan_constraint_snapshots_live_inputs_status",
        ).ddl_if(dialect="postgresql"),
        # Mirrors WORKING_TYPE_VALUES (src/domain/registry.py, D037): widen both together.
        CheckConstraint(
            "working_type IN ('MARK_PRICE')",
            name="ck_plan_constraint_snapshots_working_type",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "live_inputs_status <> 'COMPLETE' OR (margin_type <> 'UNKNOWN' "
            "AND leverage <> 'UNKNOWN' AND equity_used <> 'UNKNOWN')",
            name="ck_plan_constraint_snapshots_complete_has_live_inputs",
        ).ddl_if(dialect="postgresql"),
    )


# ---------- system_state_events (Phase 17, plan 17-02) --------------------------


class SystemStateEventRow(Base):
    """Append-only durable system-state event log (D-21, D-22).

    One row per state change of a `SystemStateKey` with a per-key `state_version`
    (UNIQUE with the key) and a link to the journal event that recorded it. "Latest per
    key" is a query (plan 13), not a view, so the ORM parity check covers every object.
    """

    __tablename__ = "system_state_events"

    state_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state_key: Mapped[str] = mapped_column(String(32), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    journal_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("state_event_id", name="pk_system_state_events"),
        UniqueConstraint("state_key", "state_version", name="uq_system_state_events_key_version"),
        ForeignKeyConstraint(
            ["journal_event_id"],
            ["journal_events.journal_event_id"],
            name="fk_system_state_events_journal_event_id",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "state_key IN ('SAFE_MODE', 'LIVE_ENABLEMENT', 'KILL_GATE')",
            name="ck_system_state_events_state_key",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "state_version >= 1", name="ck_system_state_events_version_positive"
        ).ddl_if(dialect="postgresql"),
    )


# ---------- pending_protective_actions (Phase 20, plan 20-14, migration 0008) ------


class PendingProtectiveActionRow(Base):
    """The durable INTENT of a protective action the REST gate refused (D-19, Q4).

    One row per episode of a refused stop, entry-remainder cancel or emergency close. It stores
    the intent and never a payload: there is no price, quantity or side column, so a stale
    request cannot be replayed from it. At most one row per (plan_hash, pending_kind) is open
    (`state = 'PENDING'`); a closed row is RESOLVED or SUPERSEDED with a fixed-text note.
    """

    __tablename__ = "pending_protective_actions"

    pending_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    pending_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    first_blocked_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_blocked_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_after_until_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("pending_id", name="pk_pending_protective_actions"),
        Index(
            "uq_pending_protective_actions_open",
            "plan_hash",
            "pending_kind",
            unique=True,
            postgresql_where=text("state = 'PENDING'"),
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "pending_kind IN ('STOP_NOT_SENT', 'PROTECTION_ENTRY_CANCEL_NOT_SENT', "
            "'CLOSE_NOT_SENT')",
            name="ck_pending_protective_actions_kind",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "state IN ('PENDING', 'RESOLVED', 'SUPERSEDED')",
            name="ck_pending_protective_actions_state",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "block_count >= 1", name="ck_pending_protective_actions_block_count"
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "last_blocked_at_utc >= first_blocked_at_utc",
            name="ck_pending_protective_actions_time_order",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(state = 'PENDING' AND resolved_at_utc IS NULL AND resolution_note IS NULL) "
            "OR (state <> 'PENDING' AND resolved_at_utc IS NOT NULL "
            "AND resolution_note IS NOT NULL)",
            name="ck_pending_protective_actions_resolution",
        ).ddl_if(dialect="postgresql"),
    )


# ---------- engine factory ---------------------------------------------------


# One shared async engine per URL: repeated `make_session_factory` calls
# (tests, CLI, collector restarts) must not leak a pool per call.
_ENGINE_CACHE: dict[str, AsyncEngine] = {}


def _utc_connect_args(database_url: str) -> dict[str, Any]:
    """Driver connect args that pin every session to `TimeZone=UTC` (F-406).

    psycopg returns `timestamptz` in the session zone and the domain constructors
    reject non-UTC offsets, so a database whose default zone is not UTC must not leak
    into application sessions.
    """
    if "+asyncpg" in database_url:
        return {"server_settings": {"timezone": "UTC"}}
    return {"options": "-c timezone=UTC"}


def _scheme_class(database_url: str) -> str:
    """The URL scheme only (no userinfo, host or path), safe to put in an error message."""
    scheme, separator, _rest = database_url.partition("://")
    if separator and re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]{0,31}", scheme):
        return scheme
    return "<unrecognized>"


def make_engine(database_url: str) -> AsyncEngine:
    """Return the shared async engine for `database_url`.

    Accepts `postgresql+psycopg://...` or bare `postgresql://...` (libpq
    scheme, normalized to `+psycopg`); the synchronous form remains the
    contract for Alembic (env.py). The resolved URL must name an async
    driver — handing a sync-scheme string to `create_async_engine`
    without validation is refused loudly. Every session is pinned to
    `timezone=UTC` (F-406), whatever the database default is.
    """
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if "+psycopg" not in database_url and "+asyncpg" not in database_url:
        # Never interpolate the URL: it carries the password (T-17-03, 17-REVIEW WR-04).
        raise ValueError(
            f"refusing engine: scheme {_scheme_class(database_url)!r} names no async driver "
            "(expected postgresql+psycopg:// or postgresql+asyncpg://)"
        )
    if database_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[database_url] = create_async_engine(
            database_url,
            future=True,
            echo=False,
            connect_args=_utc_connect_args(database_url),
        )
    return _ENGINE_CACHE[database_url]


async def dispose_engine(database_url: str) -> None:
    """Drop the cached engine for `database_url`, closing its pool."""
    engine = _ENGINE_CACHE.pop(database_url, None)
    if engine is not None:
        await engine.dispose()


def make_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Return an `async_sessionmaker` bound to the shared engine above."""
    engine = make_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Async context manager for short-lived sessions (collector ticks, CLI)."""
    async with factory() as session:
        yield session
