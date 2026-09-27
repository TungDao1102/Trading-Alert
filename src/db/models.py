"""SQLAlchemy 2.0 async ORM — Phase 2 operational state + Phase 3 domain mirror.

Per D-05, this package owns *operational* state in PostgreSQL 17:
  - symbol_metadata           (versioned, never UPDATE — RESEARCH §Pattern 4)
  - collector_watermarks      (D-08 — last successful tick per symbol/class)
  - collector_gaps            (D-09 — flag-never-fabricate gap journal)
  - coverage_windows          (DATA_PIPELINE §10 — per-symbol effective range)

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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, UniqueConstraint
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
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(16), nullable=False)

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
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------- approvals (Phase 3, plan 03-04) ---------------------------------


class ApprovalRow(Base):
    """ORM mirror of the domain Approval entity (D-02).

    PK is the content-hash `approval_id`. Carries `action` (ApprovalAction),
    `result` (ApprovalResult), and explicit `status` (ApprovalResult) —
    `status` alone answers state (D-11). `acted_at_utc` and
    `telegram_message_id` are nullable: NULL means "transition never
    happened" / "no Telegram message yet".
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
    local_status: Mapped[str] = mapped_column(String(16), nullable=False)
    submitted_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    canceled_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    status: Mapped[str] = mapped_column(String(16), nullable=False)


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


# ---------- engine factory ---------------------------------------------------


# One shared async engine per URL: repeated `make_session_factory` calls
# (tests, CLI, collector restarts) must not leak a pool per call.
_ENGINE_CACHE: dict[str, AsyncEngine] = {}


def make_engine(database_url: str) -> AsyncEngine:
    """Return the shared async engine for `database_url`.

    Accepts `postgresql+psycopg://...` or bare `postgresql://...` (libpq
    scheme, normalized to `+psycopg`); the synchronous form remains the
    contract for Alembic (env.py). The resolved URL must name an async
    driver — handing a sync-scheme string to `create_async_engine`
    without validation is refused loudly.
    """
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if "+psycopg" not in database_url and "+asyncpg" not in database_url:
        raise ValueError(
            f"refusing engine: {database_url!r} names no async driver "
            "(expected postgresql+psycopg:// or postgresql+asyncpg://)"
        )
    if database_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[database_url] = create_async_engine(database_url, future=True, echo=False)
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
