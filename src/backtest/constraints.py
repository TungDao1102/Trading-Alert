"""Point-in-time exchange constraints for the causal backtest (Phase 14, plan 14-05, D-17, D-30).

A backtest bar must be sized with the tick, step, minimum quantity and minimum notional
that were in force at that bar, not with today's. `select_constraints` picks, for one
symbol and one bar close, the latest metadata row with `observed_at <= bar close`
(a binary search over the sorted observation times). A bar that closes before the first
recorded row uses the earliest row back-extrapolated and says so (`extrapolated=True`, D-30:
these filters rarely change, and failing closed would produce zero trades); the engine counts
the flag in the report.

The live risk pipeline checks metadata freshness against a wall-clock window. History has no
wall clock (D-17), so the returned `ConstraintSnapshot` carries
`metadata_observed_at_utc` clamped to the bar close: evaluated at `now_utc = bar close` with a
zero-length freshness window the age is exactly 0 and the gate passes without any special case
in `src/risk`. The true observation time travels separately in `PitConstraint.observed_at_utc`.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic and reads
no clock: stdlib + Decimal + the pure `src.risk.types` snapshot only. History rows are frozen
values and a `ConstraintHistory` is never mutated after construction.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from src.risk.types import ConstraintSnapshot

_DECIMAL_FIELDS = ("price_tick_size", "quantity_step_size", "min_quantity", "min_notional")
_TIMESTAMP_KEY = "metadata_observed_at_utc"


class ConstraintHistoryError(ValueError):
    """The constraint history is missing, duplicated or malformed (fail closed)."""


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


@dataclass(frozen=True)
class ConstraintRow:
    """One versioned `symbol_metadata` observation (the fields the risk pipeline reads)."""

    symbol: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("symbol must be a non-empty string")
        for name in _DECIMAL_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
            if not value.is_finite() or value <= Decimal("0"):
                raise ValueError(f"{name} must be a finite number > 0, got {value}")
        if not isinstance(self.observed_at_utc, datetime):
            raise TypeError(
                f"observed_at_utc must be datetime, got {type(self.observed_at_utc).__name__}"
            )
        _require_utc(self.observed_at_utc, "observed_at_utc")


@dataclass(frozen=True)
class PitConstraint:
    """The constraint selected for one bar.

    `snapshot` is ready for `evaluate_risk` (its `metadata_observed_at_utc` is the bar
    close); `observed_at_utc` is the true observation time of the chosen row; `extrapolated`
    is True when the bar closed before the first recorded row (D-30).
    """

    snapshot: ConstraintSnapshot
    observed_at_utc: datetime
    extrapolated: bool


def _decimal_from(raw: object, field_name: str) -> Decimal:
    """Accept a Decimal or a decimal string; refuse floats, ints, bools and garbage."""
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, str):
        try:
            return Decimal(raw)
        except InvalidOperation:
            raise ValueError(f"{field_name} is not a decimal string: {raw!r}") from None
    raise TypeError(f"{field_name} must be a Decimal or decimal string, got {type(raw).__name__}")


def _timestamp_from(raw: object) -> datetime:
    """Accept an aware UTC datetime or an ISO-8601 UTC string; refuse everything else."""
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise ValueError(f"{_TIMESTAMP_KEY} is not an ISO-8601 timestamp: {raw!r}") from None
    raise TypeError(f"{_TIMESTAMP_KEY} must be an ISO string, got {type(raw).__name__}")


def parse_constraint_row(row: Mapping[str, Any]) -> ConstraintRow:
    """Parse one metadata mapping (decimal strings, ISO UTC timestamp) into a `ConstraintRow`.

    Raises:
        ConstraintHistoryError: a required key is missing.
        TypeError: a numeric value is a float, int or bool.
        ValueError: a value is not a finite positive decimal, or the timestamp is naive or
            not UTC.
    """
    for key in ("symbol", *_DECIMAL_FIELDS, _TIMESTAMP_KEY):
        if key not in row:
            raise ConstraintHistoryError(f"constraint row is missing {key!r}")
    symbol = row["symbol"]
    if not isinstance(symbol, str):
        raise TypeError(f"symbol must be str, got {type(symbol).__name__}")
    return ConstraintRow(
        symbol=symbol,
        price_tick_size=_decimal_from(row["price_tick_size"], "price_tick_size"),
        quantity_step_size=_decimal_from(row["quantity_step_size"], "quantity_step_size"),
        min_quantity=_decimal_from(row["min_quantity"], "min_quantity"),
        min_notional=_decimal_from(row["min_notional"], "min_notional"),
        observed_at_utc=_timestamp_from(row[_TIMESTAMP_KEY]),
    )


@dataclass(frozen=True)
class ConstraintHistory:
    """Per-symbol constraint rows sorted by observation time (never mutated)."""

    rows_by_symbol: dict[str, tuple[ConstraintRow, ...]]
    observed_by_symbol: dict[str, tuple[datetime, ...]]

    @classmethod
    def from_rows(cls, rows: Iterable[ConstraintRow]) -> ConstraintHistory:
        """Group by symbol and sort by `observed_at_utc`; refuse a repeated observation time.

        Raises:
            ConstraintHistoryError: two rows of one symbol share an `observed_at_utc`.
        """
        grouped: dict[str, list[ConstraintRow]] = {}
        for row in rows:
            grouped.setdefault(row.symbol, []).append(row)
        rows_by_symbol: dict[str, tuple[ConstraintRow, ...]] = {}
        observed_by_symbol: dict[str, tuple[datetime, ...]] = {}
        for symbol in sorted(grouped):
            ordered = sorted(grouped[symbol], key=lambda r: r.observed_at_utc)
            for earlier, later in zip(ordered, ordered[1:], strict=False):
                if earlier.observed_at_utc == later.observed_at_utc:
                    raise ConstraintHistoryError(
                        f"duplicate observed_at {later.observed_at_utc.isoformat()} "
                        f"for symbol {symbol!r}"
                    )
            rows_by_symbol[symbol] = tuple(ordered)
            observed_by_symbol[symbol] = tuple(r.observed_at_utc for r in ordered)
        return cls(rows_by_symbol=rows_by_symbol, observed_by_symbol=observed_by_symbol)


def select_constraints(
    history: ConstraintHistory, *, symbol: str, bar_close_utc: datetime
) -> PitConstraint:
    """Select the row in force at `bar_close_utc`: the latest with `observed_at <= bar close`.

    Before the first row the earliest row is returned with `extrapolated=True` (D-30). The
    snapshot's `metadata_observed_at_utc` is clamped to `bar_close_utc` so the live freshness
    gate sees age 0 (D-17); the true observation time is `PitConstraint.observed_at_utc`.

    Raises:
        ConstraintHistoryError: the history has no row for `symbol`.
        ValueError: `bar_close_utc` is naive or not UTC.
    """
    _require_utc(bar_close_utc, "bar_close_utc")
    rows = history.rows_by_symbol.get(symbol)
    if not rows:
        raise ConstraintHistoryError(f"no constraint rows for symbol {symbol!r}")
    index = bisect_right(history.observed_by_symbol[symbol], bar_close_utc) - 1
    extrapolated = index < 0
    row = rows[0] if extrapolated else rows[index]
    snapshot = ConstraintSnapshot(
        symbol=row.symbol,
        price_tick_size=row.price_tick_size,
        quantity_step_size=row.quantity_step_size,
        min_quantity=row.min_quantity,
        min_notional=row.min_notional,
        metadata_observed_at_utc=bar_close_utc,
    )
    return PitConstraint(
        snapshot=snapshot, observed_at_utc=row.observed_at_utc, extrapolated=extrapolated
    )


__all__ = [
    "ConstraintHistory",
    "ConstraintHistoryError",
    "ConstraintRow",
    "PitConstraint",
    "parse_constraint_row",
    "select_constraints",
]
