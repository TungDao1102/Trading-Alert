"""Shared temporal trade-record validator (Phase 14, plan 14-01, D-23).

`validate_trade_record` asserts the causal and temporal invariants of one trade
record and RAISES `TradeRecordInvariantError` on a violation — it never warns and
never logs. It runs inside the record builder and, from plan 14-11, again at every
normalizer boundary (where no data window is known and the window check is skipped).

Invariants, on a record that filled:
  - it carries its `signal_close_utc` and `entry_time > signal_close` (F-120);
  - `exit_time >= entry_time` (equality is allowed: a stop can trigger on the fill
    minute) and, when a data window is given, `exit_time` lies inside it (F-804);
  - `0 < quantity <= planned_quantity`;
  - a TP1 leg, when present, happened inside the holding window and closed less than
    the whole position;
  - `entry_kind` and `exit_kind` come from the pinned vocabularies;
A record that never filled must have every exit field `None`.

Strict mode (`strict=True`, used where the engine builds or reloads its own records, WR-01)
adds the cross-field shape of an engine record: a filled record has `entry_kind`
`ENTRY_FILLED` (or `PARTIAL_FILL` exactly when quantity < planned_quantity), an entry price
and, when `OK`, a complete closed exit (kind, price, time, realized PnL, realized risk); an
unfilled record has a non-filled `entry_kind` and every fill-derived field `None`. The
analytics boundary stays non-strict because it reports incomplete filled records instead
of refusing them (phase 10).

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from .semantics import ENTRY_FILLED, ENTRY_KINDS, EXIT_KINDS, PARTIAL_FILL

if TYPE_CHECKING:
    from .records import TradeRecord

_ZERO = Decimal("0")


class TradeRecordInvariantError(Exception):
    """A trade record violates a causal or temporal invariant (D-23, F-804)."""


def _iso(value: datetime) -> str:
    return value.isoformat()


def _validate_vocabulary(record: TradeRecord) -> None:
    if record.entry_kind not in ENTRY_KINDS:
        raise TradeRecordInvariantError(
            f"entry_kind {record.entry_kind!r} is not one of {sorted(ENTRY_KINDS)}"
        )
    if record.exit_kind is not None and record.exit_kind not in EXIT_KINDS:
        raise TradeRecordInvariantError(
            f"exit_kind {record.exit_kind!r} is not one of {sorted(EXIT_KINDS)}"
        )


_FILLED_KINDS = frozenset({ENTRY_FILLED, PARTIAL_FILL})
_UNFILLED_FIELDS: tuple[str, ...] = (
    "entry_price",
    "quantity",
    "exit_kind",
    "exit_price",
    "exit_time_utc",
    "realized_pnl",
    "realized_risk",
    "gross_pnl",
    "entry_fee",
    "exit_fee",
    "funding_amount",
    "slippage_amount",
    "tp1_quantity",
    "tp1_price",
    "tp1_time_utc",
)


def _validate_unfilled(record: TradeRecord, *, strict: bool) -> None:
    if not strict:
        if (
            record.exit_kind is not None
            or record.exit_price is not None
            or record.exit_time_utc is not None
        ):
            raise TradeRecordInvariantError(
                "exit fields must be None on a record that never filled: "
                f"exit_kind={record.exit_kind!r}, exit_price={record.exit_price}, "
                f"exit_time={record.exit_time_utc}"
            )
        return
    if record.entry_kind in _FILLED_KINDS:
        raise TradeRecordInvariantError(
            f"entry_kind {record.entry_kind!r} needs a fill but entry_time is None"
        )
    present = [name for name in _UNFILLED_FIELDS if getattr(record, name) is not None]
    if present:
        raise TradeRecordInvariantError(
            "fill-derived and exit fields must be None on a record that never filled: "
            + ", ".join(f"{name}={getattr(record, name)!r}" for name in present)
        )


def _validate_filled_shape(record: TradeRecord) -> None:
    """A strict filled record has a filled kind, an entry price and a complete closed exit."""
    if record.entry_kind not in _FILLED_KINDS:
        raise TradeRecordInvariantError(
            f"a record with an entry_time must have entry_kind ENTRY_FILLED or PARTIAL_FILL, "
            f"got {record.entry_kind!r}"
        )
    if record.entry_price is None:
        raise TradeRecordInvariantError("entry_price is required on a filled record")
    quantity, planned = record.quantity, record.planned_quantity
    if quantity is not None and planned is not None:
        partial = quantity < planned
        if partial != (record.entry_kind == PARTIAL_FILL):
            raise TradeRecordInvariantError(
                f"entry_kind {record.entry_kind!r} disagrees with quantity {quantity} "
                f"against planned_quantity {planned}: PARTIAL_FILL exactly when quantity < planned"
            )
    if record.outcome_kind != "OK":
        return
    required = (
        "exit_kind",
        "exit_price",
        "exit_time_utc",
        "realized_pnl",
        "realized_risk",
    )
    missing = [name for name in required if getattr(record, name) is None]
    if missing:
        raise TradeRecordInvariantError(
            f"a filled OK record needs {', '.join(missing)} (closed trades only)"
        )


def _validate_quantities(record: TradeRecord) -> None:
    quantity = record.quantity
    if quantity is None or quantity <= _ZERO:
        raise TradeRecordInvariantError(f"quantity must be > 0 on a filled record, got {quantity}")
    planned = record.planned_quantity
    if planned is None:
        raise TradeRecordInvariantError(
            f"planned_quantity is required on a filled record (quantity {quantity})"
        )
    if quantity > planned:
        raise TradeRecordInvariantError(
            f"filled quantity {quantity} must be <= planned_quantity {planned}"
        )
    tp1_quantity = record.tp1_quantity
    if tp1_quantity is not None and not _ZERO < tp1_quantity < quantity:
        raise TradeRecordInvariantError(
            f"tp1_quantity {tp1_quantity} must be in (0, quantity {quantity})"
        )


def _validate_times(
    record: TradeRecord,
    entry_time: datetime,
    signal_close: datetime,
    data_start_utc: datetime | None,
    data_end_utc: datetime | None,
) -> None:
    if not entry_time > signal_close:
        raise TradeRecordInvariantError(
            f"entry_time {_iso(entry_time)} must be > signal_close {_iso(signal_close)}"
        )
    exit_time = record.exit_time_utc
    if exit_time is not None:
        if exit_time < entry_time:
            raise TradeRecordInvariantError(
                f"exit_time {_iso(exit_time)} must be >= entry_time {_iso(entry_time)}"
            )
        if data_start_utc is not None and exit_time < data_start_utc:
            raise TradeRecordInvariantError(
                f"exit_time {_iso(exit_time)} is before the data window start "
                f"{_iso(data_start_utc)}"
            )
        if data_end_utc is not None and exit_time > data_end_utc:
            raise TradeRecordInvariantError(
                f"exit_time {_iso(exit_time)} is after the data window end {_iso(data_end_utc)}"
            )
    tp1_time = record.tp1_time_utc
    if tp1_time is not None:
        if tp1_time < entry_time:
            raise TradeRecordInvariantError(
                f"tp1_time {_iso(tp1_time)} must be >= entry_time {_iso(entry_time)}"
            )
        if exit_time is not None and tp1_time > exit_time:
            raise TradeRecordInvariantError(
                f"tp1_time {_iso(tp1_time)} must be <= exit_time {_iso(exit_time)}"
            )


def validate_trade_record(
    record: TradeRecord,
    *,
    data_start_utc: datetime | None = None,
    data_end_utc: datetime | None = None,
    strict: bool = False,
) -> None:
    """Raise `TradeRecordInvariantError` unless `record` satisfies every invariant.

    `data_start_utc` / `data_end_utc` bound `exit_time` (inclusive); with both `None`
    the window check is skipped, which is the normalizer-boundary use. `strict` adds the
    engine-record cross-field shape described in the module docstring. Returns `None` on a
    valid record and never emits a warning.
    """
    _validate_vocabulary(record)
    entry_time = record.entry_time_utc
    if entry_time is None:
        _validate_unfilled(record, strict=strict)
        return
    signal_close = record.signal_close_utc
    if signal_close is None:
        raise TradeRecordInvariantError(
            f"signal_close_utc is required on a filled record (entry_time {_iso(entry_time)})"
        )
    if strict:
        _validate_filled_shape(record)
    _validate_times(record, entry_time, signal_close, data_start_utc, data_end_utc)
    _validate_quantities(record)
