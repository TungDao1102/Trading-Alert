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

from src.backtest.semantics import FUNDING_JITTER, FUNDING_MAX_CADENCE
from src.backtest.series import MinuteSeriesError, MinuteSource
from src.core._decimal import _add, _mul

_DIRECTIONS = ("LONG", "SHORT")
_MINUTE = timedelta(seconds=60)


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
    """Fail closed unless the funding history of `symbol` covers the holding window (D-36).

    With `G = FUNDING_MAX_CADENCE + FUNDING_JITTER` the window must lie inside
    `[loaded_start_utc, loaded_end_utc]` (the closed UTC days actually loaded). The
    checked points are `max(window_start - G, loaded_start)`, every funding instant of
    the symbol inside that extended range, and `min(window_end + G, loaded_end)`; every
    consecutive difference must be at most `G`. In effect there must be a funding
    instant at or before the window start and one at or after its end, and nothing
    longer than a cadence plus jitter between them, so a missed tick in a 4 h series
    that the 8 h grid test would hide is still found. A larger difference is a hole,
    reported with the real neighbouring instant where one exists (else the synthetic
    edge). A hole fully covered by a same-symbol allowed gap is accepted and returned;
    anything else raises.

    Returns:
        The allowed gaps that were actually needed, in order of first use.

    Raises:
        FundingCoverageError: the window leaves the loaded range or a hole is uncovered.
        ValueError: a duplicate `funding_time_utc` for the symbol, or an inverted window.
    """
    if window_end_utc < window_start_utc:
        raise ValueError("window_end_utc must not be before window_start_utc")
    if window_start_utc < loaded_start_utc or window_end_utc > loaded_end_utc:
        raise FundingCoverageError(
            f"{symbol} holding window {window_start_utc.isoformat()} to "
            f"{window_end_utc.isoformat()} lies outside the loaded range "
            f"{loaded_start_utc.isoformat()} to {loaded_end_utc.isoformat()}"
        )
    tolerance = FUNDING_MAX_CADENCE + FUNDING_JITTER
    low = max(window_start_utc - tolerance, loaded_start_utc)
    high = min(window_end_utc + tolerance, loaded_end_utc)
    times = [r.funding_time_utc for r in _symbol_rows(symbol, rows)]
    inside = [t for t in times if low <= t <= high]
    before = [t for t in times if t < low]
    after = [t for t in times if t > high]
    points = [low, *inside, high]
    holes: list[FundingGap] = []
    for index in range(len(points) - 1):
        start, end = points[index], points[index + 1]
        if end - start <= tolerance:
            continue
        if index == 0 and before:
            start = before[-1]
        if index == len(points) - 2 and after:
            end = after[0]
        holes.append(FundingGap(symbol=symbol, start_utc=start, end_utc=end))
    used: list[FundingGap] = []
    uncovered: list[FundingGap] = []
    for hole in holes:
        cover = next(
            (
                g
                for g in allowed_gaps
                if g.symbol == symbol
                and g.start_utc <= hole.start_utc
                and g.end_utc >= hole.end_utc
            ),
            None,
        )
        if cover is None:
            uncovered.append(hole)
        elif cover not in used:
            used.append(cover)
    if uncovered:
        listing = "; ".join(
            f"{h.start_utc.isoformat()} to {h.end_utc.isoformat()}" for h in uncovered
        )
        raise FundingCoverageError(
            f"{symbol} funding history has uncovered holes for the holding window "
            f"{window_start_utc.isoformat()} to {window_end_utc.isoformat()}: {listing}",
            holes=tuple(uncovered),
        )
    return tuple(used)


def _symbol_rows(symbol: str, rows: Sequence[FundingRow]) -> list[FundingRow]:
    """Rows of one symbol sorted by time; a duplicate `funding_time_utc` is refused."""
    own = sorted((r for r in rows if r.symbol == symbol), key=lambda r: r.funding_time_utc)
    for previous, current in zip(own, own[1:], strict=False):
        if previous.funding_time_utc == current.funding_time_utc:
            raise ValueError(
                f"duplicate funding_time_utc {current.funding_time_utc.isoformat()} for {symbol}"
            )
    return own


def _mark_from_kline(symbol: str, when: datetime, mark_source: MinuteSource) -> Decimal:
    """Open of the mark minute containing `when` (D-15, assumption A2); fail closed if absent.

    The minute with `open <= when < open + 60 s` is selected from a window wide enough
    to include it even when `when` falls in the last millisecond after its close time.
    A neighbouring minute is never used.
    """
    try:
        minutes = mark_source.mark_minutes(symbol, when - _MINUTE, when + _MINUTE)
    except MinuteSeriesError as exc:
        raise FundingCoverageError(
            f"{symbol} funding {when.isoformat()} has no mark price and no mark kline series: {exc}"
        ) from exc
    for minute in minutes:
        if minute.open_time_utc <= when < minute.open_time_utc + _MINUTE:
            return minute.open
    raise FundingCoverageError(
        f"{symbol} funding {when.isoformat()} has no mark price and no mark kline minute "
        "contains it"
    )


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
    own = _symbol_rows(symbol, rows)
    used: tuple[FundingGap, ...] = ()
    if segments:
        window_start = segments[0].start_utc
        window_end = segments[-1].end_utc
        # A zero-length window (fill and exit in the same minute) cannot contain an instant.
        if window_end > window_start:
            used = check_funding_coverage(
                symbol=symbol,
                rows=own,
                window_start_utc=window_start,
                window_end_utc=window_end,
                loaded_start_utc=loaded_start_utc,
                loaded_end_utc=loaded_end_utc,
                allowed_gaps=allowed_gaps,
            )
    events: list[FundingEvent] = []
    total = Decimal("0")
    for segment in segments:
        for row in own:
            if not (segment.start_utc <= row.funding_time_utc < segment.end_utc):
                continue
            from_kline = row.mark_price is None
            mark = (
                _mark_from_kline(symbol, row.funding_time_utc, mark_source)
                if row.mark_price is None
                else row.mark_price
            )
            amount = funding_pnl(
                direction=direction,
                quantity=segment.quantity,
                mark_price=mark,
                funding_rate=row.funding_rate,
            )
            events.append(
                FundingEvent(
                    symbol=symbol,
                    funding_time_utc=row.funding_time_utc,
                    funding_rate=row.funding_rate,
                    mark_price=mark,
                    quantity=segment.quantity,
                    amount=amount,
                    mark_from_kline=from_kline,
                )
            )
            total = _add(total, amount)
    return FundingResult(events=tuple(events), total=total, used_allowed_gaps=used)
