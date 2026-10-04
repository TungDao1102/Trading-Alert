"""Funding schedule and sign convention for the causal simulator (Phase 14, plan 14-03).

Sign convention (D-14, `FUNDING_CONVENTION` = `MARK_NOTIONAL_SIGNED_V1`):

    funding_pnl = -sign(position) x quantity x markPrice(fundingTime) x fundingRate

with sign +1 for LONG and -1 for SHORT, so a LONG with a positive rate pays and a
negative amount is a cost. The amount is booked at every *actual* `fundingTime` in the
funding history (no fixed 8 h grid; cadence differs per symbol) at which the position is
open: `segment.start <= fundingTime < segment.end` (half open). The quantity is the OPEN
quantity at that instant, so after a TP1 partial the remainder is charged (D-36), which
the caller expresses as one `OpenSegment` per constant-quantity stretch. Funding enters
net PnL and R only, never sizing (D-14).

Granularity: entries and exits happen at 1m bar closes (`...59.999`) while funding
instants jitter by milliseconds around the grid, so the window is judged at that
granularity. Binance's 15-second grace example (a position opened at 08:00:05 may still
be charged) is deliberately not modeled (RESEARCH Pitfall 9).

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent. There is no float anywhere,
including time arithmetic (datetimes and timedeltas are only compared and subtracted).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.backtest.series import MinuteSource
from src.core._decimal import _add, _mul

_DIRECTIONS = ("LONG", "SHORT")


@dataclass(frozen=True)
class FundingGap:
    """A stretch of one symbol's funding history with no usable row (or an allow-gap)."""

    symbol: str
    start_utc: datetime
    end_utc: datetime


class FundingCoverageError(ValueError):
    """The funding history cannot support a holding window (D-15): fail closed."""

    def __init__(self, message: str, holes: tuple[FundingGap, ...] = ()) -> None:
        super().__init__(message)
        self.holes = holes


def _require_decimal(value: object, field_name: str) -> Decimal:
    """Accept only a Decimal; floats, bools, ints and strings are refused, never coerced."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    return value


def _parse_decimal(value: object, field_name: str) -> Decimal:
    """Coerce a Decimal/str/int to Decimal; floats and bools are refused."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool | float):
        raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")
    if isinstance(value, int | str):
        return Decimal(value)
    raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")


def _require_utc(value: object, field_name: str) -> datetime:
    """Parse an ISO string or datetime into a UTC-aware datetime (naive refused)."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(f"{field_name} must be an ISO str or datetime, got {type(value).__name__}")
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {parsed.utcoffset()}")
    return parsed


@dataclass(frozen=True)
class FundingRow:
    """One funding-history row. `mark_price` is None when the exchange row had none (D-15)."""

    symbol: str
    funding_time_utc: datetime
    funding_rate: Decimal
    mark_price: Decimal | None


def parse_funding_row(row: Mapping[str, Any]) -> FundingRow:
    """Build a `FundingRow` from a JSON-like row (Phase 13 funding columns).

    Only `None` or an empty string maps to a missing mark price; anything else must be a
    Decimal/str/int. Floats and naive datetimes are refused.

    Raises:
        TypeError: a numeric field is a float/bool or a time field has the wrong type.
        ValueError: a time is naive or not UTC, or a column is missing.
    """
    missing = [c for c in ("symbol", "funding_time_utc", "funding_rate") if c not in row]
    if missing:
        raise ValueError(f"funding row is missing columns {missing}")
    raw_mark = row.get("mark_price")
    mark = None if raw_mark is None or raw_mark == "" else _parse_decimal(raw_mark, "mark_price")
    return FundingRow(
        symbol=str(row["symbol"]),
        funding_time_utc=_require_utc(row["funding_time_utc"], "funding_time_utc"),
        funding_rate=_parse_decimal(row["funding_rate"], "funding_rate"),
        mark_price=mark,
    )


def funding_pnl(
    *, direction: str, quantity: Decimal, mark_price: Decimal, funding_rate: Decimal
) -> Decimal:
    """Signed funding for one instant: `-sign x quantity x mark_price x funding_rate` (D-14).

    Negative means the position pays. `quantity` must be positive (the open quantity).

    Raises:
        TypeError: any numeric argument is not a Decimal.
        ValueError: direction is not LONG/SHORT, or quantity/mark_price is not positive.
    """
    qty = _require_decimal(quantity, "quantity")
    mark = _require_decimal(mark_price, "mark_price")
    rate = _require_decimal(funding_rate, "funding_rate")
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    if qty <= 0:
        raise ValueError(f"quantity must be positive, got {qty}")
    if mark <= 0:
        raise ValueError(f"mark_price must be positive, got {mark}")
    notional_rate = _mul(_mul(qty, mark), rate)
    return -notional_rate if direction == "LONG" else notional_rate


@dataclass(frozen=True)
class OpenSegment:
    """A stretch of constant open quantity: `start_utc` inclusive, `end_utc` exclusive."""

    start_utc: datetime
    end_utc: datetime
    quantity: Decimal

    def __post_init__(self) -> None:
        _require_utc(self.start_utc, "start_utc")
        _require_utc(self.end_utc, "end_utc")
        _require_decimal(self.quantity, "quantity")
        if self.end_utc < self.start_utc:
            raise ValueError("segment end_utc must not be before start_utc")
        if self.quantity <= 0:
            raise ValueError(f"segment quantity must be positive, got {self.quantity}")


@dataclass(frozen=True)
class FundingEvent:
    """One booked funding instant."""

    symbol: str
    funding_time_utc: datetime
    funding_rate: Decimal
    mark_price: Decimal
    quantity: Decimal
    amount: Decimal
    mark_from_kline: bool


@dataclass(frozen=True)
class FundingResult:
    """All funding events of one holding window, their sum and the allow-gaps used."""

    events: tuple[FundingEvent, ...]
    total: Decimal
    used_allowed_gaps: tuple[FundingGap, ...]


def check_funding_coverage(
    *,
    symbol: str,
    rows: Sequence[FundingRow],
    window_start_utc: datetime,
    window_end_utc: datetime,
    loaded_start_utc: datetime,
    loaded_end_utc: datetime,
    allowed_gaps: Sequence[FundingGap],
) -> tuple[FundingGap, ...]:
    """RED skeleton: the coverage rule is not implemented yet."""
    return ()


def _check_segments(segments: Sequence[OpenSegment]) -> None:
    previous_end: datetime | None = None
    for segment in segments:
        if previous_end is not None and segment.start_utc < previous_end:
            raise ValueError("segments must be ascending and non-overlapping")
        previous_end = segment.end_utc


def funding_events(
    *,
    symbol: str,
    direction: str,
    segments: Sequence[OpenSegment],
    rows: Sequence[FundingRow],
    mark_source: MinuteSource,
    allowed_gaps: Sequence[FundingGap],
    loaded_start_utc: datetime,
    loaded_end_utc: datetime,
) -> FundingResult:
    """Book funding for every actual fundingTime inside the open segments (D-14, D-36).

    Rows of other symbols are ignored. For each segment the rows with
    `start <= fundingTime < end` are charged on that segment's open quantity, in time
    order. `allowed_gaps` and the loaded range feed the coverage rule.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be LONG or SHORT, got {direction!r}")
    _check_segments(segments)
    own = sorted((r for r in rows if r.symbol == symbol), key=lambda r: r.funding_time_utc)
    events: list[FundingEvent] = []
    total = Decimal("0")
    for segment in segments:
        for row in own:
            if not (segment.start_utc <= row.funding_time_utc < segment.end_utc):
                continue
            if row.mark_price is None:
                raise FundingCoverageError(
                    f"{symbol} funding row {row.funding_time_utc.isoformat()} has no mark price"
                )
            amount = funding_pnl(
                direction=direction,
                quantity=segment.quantity,
                mark_price=row.mark_price,
                funding_rate=row.funding_rate,
            )
            events.append(
                FundingEvent(
                    symbol=symbol,
                    funding_time_utc=row.funding_time_utc,
                    funding_rate=row.funding_rate,
                    mark_price=row.mark_price,
                    quantity=segment.quantity,
                    amount=amount,
                    mark_from_kline=False,
                )
            )
            total = _add(total, amount)
    return FundingResult(events=tuple(events), total=total, used_allowed_gaps=())
