"""Edge adapter: read-only journal / entity / candle access for the analytics phase (plan 10-09).

D-01/D-05: all database and Parquet access for the analytics phase lives here, so the pure
`src/analytics` modules never touch a session, a frame or the filesystem.

- The journal and live-entity readers only build and execute SELECT statements. Rows are
  converted through the existing domain mappers; a row that cannot be converted is counted,
  never raised and never silently skipped. Journal events are returned in the total key
  order (occurred_at_utc, event_type, entity_id, journal_event_id).
- The single write anywhere in the phase is `append_kill_gate_event`: one KILL_GATE_EVALUATION
  journal event, inserted with ON CONFLICT DO NOTHING on the content-hash primary key so a
  replay is a no-op. Any other event type is refused before a statement is built.
- Candles come from the immutable Hive-partitioned 1m Parquet store, read-only. A missing
  partition yields an empty result; candles are never fabricated or forward-filled.

No network, no exchange access, no float; errors carry names and counts only.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Insert
from src.analytics.killgate import KILL_GATE_EVENT_TYPE
from src.core.types import Candle
from src.data.store import partition_file
from src.db.mappers import (
    approval_from_row,
    fill_from_row,
    journal_from_row,
    order_from_row,
    position_from_row,
    signal_from_row,
    trade_plan_from_row,
)
from src.db.models import (
    ApprovalRow,
    FillRow,
    JournalEventRow,
    OrderRow,
    PositionRow,
    SignalRow,
    TradePlanRow,
)
from src.domain.approval import Approval
from src.domain.fill import Fill
from src.domain.journal import JournalEvent
from src.domain.order import Order
from src.domain.position import Position
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

__all__ = [
    "CandleReadResult",
    "JournalReadResult",
    "LiveRows",
    "append_kill_gate_event",
    "build_append_stmt",
    "journal_rows_to_events",
    "read_candles",
    "read_journal_events",
    "read_live_rows",
    "select_journal_events_stmt",
]

_SYMBOL = re.compile(r"[A-Z0-9]{5,20}")
_ONE_DAY = timedelta(days=1)
_CANDLE_INTERVAL = "1m"
_CONVERSION_ERRORS = (ValueError, TypeError, KeyError, AttributeError)
_JOURNAL_COLUMNS = (
    "journal_event_id",
    "occurred_at_utc",
    "event_type",
    "entity_type",
    "entity_id",
    "correlation_id",
    "signal_id",
    "trade_plan_id",
    "approval_id",
    "order_id",
    "position_id",
    "payload_json",
    "created_at_utc",
)


@dataclass(frozen=True)
class JournalReadResult:
    """Journal events in total-key order plus the count of rows that could not be converted."""

    events: tuple[JournalEvent, ...]
    rejected: int


@dataclass(frozen=True)
class LiveRows:
    """Live operational entities (sorted by primary key) and per-table rejected counts."""

    signals: tuple[Signal, ...]
    plans: tuple[TradePlan, ...]
    approvals: tuple[Approval, ...]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    positions: tuple[Position, ...]
    rejected: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class CandleReadResult:
    """1m candles sorted by open time plus the count of rejected rows / unreadable partitions."""

    candles: tuple[Candle, ...]
    rejected: int


# --------------------------------------------------------------------------- #
# Journal reader (SELECT only)
# --------------------------------------------------------------------------- #


def _event_sort_key(event: JournalEvent) -> tuple[datetime, str, str, str]:
    return (event.occurred_at_utc, event.event_type, event.entity_id, event.journal_event_id)


def select_journal_events_stmt(
    event_types: Sequence[str] | None = None,
) -> Select[tuple[JournalEventRow]]:
    """SELECT over journal_events ordered by the total key, optionally filtered by type."""
    stmt = select(JournalEventRow)
    if event_types is not None:
        stmt = stmt.where(JournalEventRow.event_type.in_(list(event_types)))
    return stmt.order_by(
        JournalEventRow.occurred_at_utc,
        JournalEventRow.event_type,
        JournalEventRow.entity_id,
        JournalEventRow.journal_event_id,
    )


def journal_rows_to_events(
    rows: Iterable[JournalEventRow],
) -> tuple[tuple[JournalEvent, ...], int]:
    """Convert rows to events (total-key order); malformed rows are counted, never raised."""
    events: list[JournalEvent] = []
    rejected = 0
    for row in rows:
        try:
            events.append(journal_from_row(row))
        except _CONVERSION_ERRORS:
            rejected += 1
    return tuple(sorted(events, key=_event_sort_key)), rejected


async def _fetch_rows[Row](session: AsyncSession, stmt: Select[tuple[Row]]) -> list[Row]:
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def read_journal_events(
    session: AsyncSession, *, event_types: Sequence[str] | None = None
) -> JournalReadResult:
    """Read journal events with a single SELECT (no writes, no transaction control)."""
    rows = await _fetch_rows(session, select_journal_events_stmt(event_types))
    events, rejected = journal_rows_to_events(rows)
    return JournalReadResult(events=events, rejected=rejected)


def _convert_rows[Row, Domain](
    rows: Iterable[Row], converter: Callable[[Row], Domain]
) -> tuple[list[Domain], int]:
    converted: list[Domain] = []
    rejected = 0
    for row in rows:
        try:
            converted.append(converter(row))
        except _CONVERSION_ERRORS:
            rejected += 1
    return converted, rejected


async def read_live_rows(session: AsyncSession) -> LiveRows:
    """Read the six live entity tables with SELECT statements (sorted by primary key)."""
    signals, bad_signals = _convert_rows(
        await _fetch_rows(session, select(SignalRow).order_by(SignalRow.signal_id)),
        signal_from_row,
    )
    plans, bad_plans = _convert_rows(
        await _fetch_rows(session, select(TradePlanRow).order_by(TradePlanRow.trade_plan_id)),
        trade_plan_from_row,
    )
    approvals, bad_approvals = _convert_rows(
        await _fetch_rows(session, select(ApprovalRow).order_by(ApprovalRow.approval_id)),
        approval_from_row,
    )
    orders, bad_orders = _convert_rows(
        await _fetch_rows(session, select(OrderRow).order_by(OrderRow.order_id)),
        order_from_row,
    )
    fills, bad_fills = _convert_rows(
        await _fetch_rows(session, select(FillRow).order_by(FillRow.fill_id)),
        fill_from_row,
    )
    positions, bad_positions = _convert_rows(
        await _fetch_rows(session, select(PositionRow).order_by(PositionRow.position_id)),
        position_from_row,
    )
    return LiveRows(
        signals=tuple(sorted(signals, key=lambda item: item.signal_id)),
        plans=tuple(sorted(plans, key=lambda item: item.trade_plan_id)),
        approvals=tuple(sorted(approvals, key=lambda item: item.approval_id)),
        orders=tuple(sorted(orders, key=lambda item: item.order_id)),
        fills=tuple(sorted(fills, key=lambda item: item.fill_id)),
        positions=tuple(sorted(positions, key=lambda item: item.position_id)),
        rejected=(
            ("signals", bad_signals),
            ("trade_plans", bad_plans),
            ("approvals", bad_approvals),
            ("orders", bad_orders),
            ("fills", bad_fills),
            ("positions", bad_positions),
        ),
    )


# --------------------------------------------------------------------------- #
# The single guarded write: idempotent KILL_GATE_EVALUATION append
# --------------------------------------------------------------------------- #


def build_append_stmt(event: JournalEvent, dialect_name: str) -> Insert:
    """INSERT ... ON CONFLICT DO NOTHING on the content-hash primary key (idempotent replay)."""
    values: dict[str, Any] = {name: getattr(event, name) for name in _JOURNAL_COLUMNS}
    if dialect_name == "postgresql":
        return (
            pg_insert(JournalEventRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["journal_event_id"])
        )
    if dialect_name == "sqlite":
        return (
            sqlite_insert(JournalEventRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["journal_event_id"])
        )
    raise ValueError(f"unsupported dialect {dialect_name!r} for the journal append")


async def append_kill_gate_event(session: AsyncSession, event: JournalEvent) -> None:
    """Append one KILL_GATE_EVALUATION event; any other event type is refused up front."""
    if event.event_type != KILL_GATE_EVENT_TYPE:
        raise ValueError(f"only {KILL_GATE_EVENT_TYPE} events may be appended by analytics")
    statement = build_append_stmt(event, session.get_bind().dialect.name)
    await session.execute(statement)
    await session.commit()


# --------------------------------------------------------------------------- #
# 1m candle reader (immutable Parquet store, read-only)
# --------------------------------------------------------------------------- #


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _decimal(value: Any, name: str) -> Decimal:
    """Parquet decimal / integer cell to Decimal; any other cell type is refused."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise TypeError(f"{name} must be a decimal or integer cell")
    return Decimal(str(value))


def _candle_from_row(row: dict[str, Any], symbol: str) -> Candle:
    if row["symbol"] != symbol or row["interval"] != _CANDLE_INTERVAL:
        raise ValueError("row symbol/interval does not match its partition")
    return Candle(
        symbol=symbol,
        interval=_CANDLE_INTERVAL,
        open_time_utc=row["open_time_utc"].astimezone(UTC),
        close_time_utc=row["close_time_utc"].astimezone(UTC),
        open=_decimal(row["open"], "open"),
        high=_decimal(row["high"], "high"),
        low=_decimal(row["low"], "low"),
        close=_decimal(row["close"], "close"),
        volume=_decimal(row["volume"], "volume"),
    )


def _days_between(first: date, last: date) -> Iterable[date]:
    day = first
    while day <= last:
        yield day
        day += _ONE_DAY


def read_candles(
    raw_root: Path, symbol: str, start_utc: datetime, end_utc: datetime
) -> CandleReadResult:
    """1m candles with open time in [floor-to-minute(start), end], sorted, from Parquet.

    Reads one partition file per UTC day. A missing partition contributes nothing (the pure
    core then reports the affected trades INCOMPLETE); an unreadable partition file or a row
    failing candle validation is counted in `rejected`. Nothing is ever fabricated.
    """
    if _SYMBOL.fullmatch(symbol) is None:
        raise ValueError("invalid symbol for candle read")
    _require_utc(start_utc, "start_utc")
    _require_utc(end_utc, "end_utc")
    first_minute = start_utc.replace(second=0, microsecond=0)
    if end_utc < first_minute:
        return CandleReadResult(candles=(), rejected=0)

    candles: list[Candle] = []
    rejected = 0
    for day in _days_between(first_minute.date(), end_utc.date()):
        path = partition_file(raw_root, _CANDLE_INTERVAL, symbol, day)
        if not path.is_file():
            continue
        try:
            frame = pl.read_parquet(path)
            rows = list(frame.iter_rows(named=True))
        except Exception:  # unreadable partition: counted, never fatal, never guessed
            rejected += 1
            continue
        for row in rows:
            try:
                opened = row["open_time_utc"].astimezone(UTC)
                if not first_minute <= opened <= end_utc:
                    continue
                candles.append(_candle_from_row(row, symbol))
            except _CONVERSION_ERRORS:
                rejected += 1
    candles.sort(key=lambda candle: candle.open_time_utc)
    return CandleReadResult(candles=tuple(candles), rejected=rejected)
