"""SQLAlchemy 2.0 async ORM — Phase 2 operational state only.

Per D-05, this package owns *operational* state in PostgreSQL 17:
  - symbol_metadata           (versioned, never UPDATE — RESEARCH §Pattern 4)
  - collector_watermarks      (D-08 — last successful tick per symbol/class)
  - collector_gaps            (D-09 — flag-never-fabricate gap journal)
  - coverage_windows          (DATA_PIPELINE §10 — per-symbol effective range)

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
from typing import Any

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.ext.asyncio import (
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
    max_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 18), nullable=True
    )
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
    last_tick_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


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
    expected_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    observed_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    recorded_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


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
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ---------- engine factory ---------------------------------------------------


# One shared async engine per URL: repeated `make_session_factory` calls
# (tests, CLI, collector restarts) must not leak a pool per call.
_ENGINE_CACHE: dict[str, Any] = {}


def make_engine(database_url: str):
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
        _ENGINE_CACHE[database_url] = create_async_engine(
            database_url, future=True, echo=False
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
