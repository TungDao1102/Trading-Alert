"""Pure recompute of the bounded terminal-settlement interval from committed kline bytes.

Quick 261014-nnl plan 01 (design `16-DRAFT-S-B-interval-design.md` section 2, decision
`16-DEC-S-B-interval.md` item 1). REEFUSDT stops trading at a declared terminal time `T`; Binance
published no settlement price. The settlement price is therefore carried as a bounded interval
that anyone can recompute from hashed evidence (Binance public klines committed under
`docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/`), not as numbers typed
into a manifest:

1. nominal index bounds: the exact mean of the per-minute index-price lows, and of the highs, over
   the 30 one-minute index klines of [window_start, T) (exact `Fraction`, never rounded);
2. tick-widened index bounds: the lower mean floored to the tick grid minus one tick, the upper
   mean ceiled to the tick grid plus one tick (finite, tick-aligned `Decimal` values);
3. the trade-candle bounds: low and high of the trade kline that opens exactly at `T`;
4. the union of (2) and (3): lower = min of the lowers, upper = max of the uppers.

This module NEVER chooses a settlement price. Decision item 1 forbids any proxy (flat 0.000880,
last mark close, OHLC average, midpoint); it only returns the interval ends. Which end applies to
which side of a position is the engine's concern (plans 03 and later), not this module's.

Stated assumptions (not facts, none is verified against an official Binance source):
- the settlement is the mean of per-second index values over 08:30-09:00 UTC;
- one index value per second, 60 samples per minute, so each minute has equal weight;
- the klines endpoints serve unrevised history (the committed bytes are the revision used);
- one tick of widening covers floor or nearest rounding to the tick grid, and the settlement is
  not truncated or ceiled beyond that.
Without the equal-weight rule only [min low, max high] of the window is assumption-free.

Pure: stdlib only (json, hashlib, fractions, decimal, datetime, dataclasses, math, re), no IO
(callers pass bytes), no clock, no binary float anywhere. This file sits under the Decimal-only
float scan of `src/research` (tests/test_domain_no_float.py).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, NoReturn

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MINUTE = timedelta(minutes=1)
_MIN_ROW_LENGTH = 5  # open time, open, high, low, close; Binance rows carry 12 elements
_FRACTION_TEXT = re.compile(r"[1-9][0-9]*/[1-9][0-9]*")


class SettlementEvidenceError(ValueError):
    """The settlement evidence is malformed, tampered with, or does not satisfy the rules."""


@dataclass(frozen=True)
class KlineRow:
    """One Binance kline: the open time (UTC) and the four prices as exact decimals."""

    open_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class RecomputedBounds:
    """Everything recomputed from the evidence; `price_lower` and `price_upper` are the union."""

    nominal_lower: Fraction
    nominal_upper: Fraction
    index_lower: Decimal
    index_upper: Decimal
    trade_low: Decimal
    trade_high: Decimal
    price_lower: Decimal
    price_upper: Decimal


def sha256_bytes(raw: bytes) -> str:
    """Lowercase hex sha256 of `raw`."""
    return hashlib.sha256(raw).hexdigest()


def _refuse_number(text: str) -> NoReturn:
    raise SettlementEvidenceError(
        "a JSON number with a fraction or exponent, NaN or Infinity is refused in kline evidence"
    )


def _price(value: object, what: str) -> Decimal:
    if not isinstance(value, str):
        raise SettlementEvidenceError(f"{what}: a price must be a JSON string")
    try:
        price = Decimal(value)
    except InvalidOperation:
        raise SettlementEvidenceError(f"{what}: a price is not a decimal number") from None
    if not price.is_finite() or price <= 0:
        raise SettlementEvidenceError(f"{what}: a price must be a finite positive decimal")
    return price


def _row(raw_row: object, what: str) -> KlineRow:
    if not isinstance(raw_row, list) or len(raw_row) < _MIN_ROW_LENGTH:
        raise SettlementEvidenceError(f"{what}: a kline row must be a list of at least 5 items")
    open_ms = raw_row[0]
    if isinstance(open_ms, bool) or not isinstance(open_ms, int):
        raise SettlementEvidenceError(f"{what}: the kline open time must be an integer")
    try:
        open_utc = _EPOCH + timedelta(milliseconds=open_ms)
    except OverflowError:
        raise SettlementEvidenceError(f"{what}: the kline open time is out of range") from None
    row = KlineRow(
        open_utc=open_utc,
        open=_price(raw_row[1], what),
        high=_price(raw_row[2], what),
        low=_price(raw_row[3], what),
        close=_price(raw_row[4], what),
    )
    if row.low > min(row.open, row.close) or row.high < max(row.open, row.close):
        raise SettlementEvidenceError(f"{what}: a kline row has low or high outside open/close")
    return row


def parse_klines(raw: bytes, *, what: str) -> tuple[KlineRow, ...]:
    """Parse a Binance kline array (list of lists); floats, NaN and non-string prices raise."""
    try:
        loaded: Any = json.loads(
            raw.decode("utf-8"), parse_float=_refuse_number, parse_constant=_refuse_number
        )
    except SettlementEvidenceError:
        raise
    except ValueError:
        raise SettlementEvidenceError(f"{what}: not valid UTF-8 JSON") from None
    if not isinstance(loaded, list) or not loaded:
        raise SettlementEvidenceError(f"{what}: must be a non-empty JSON array of klines")
    return tuple(_row(item, what) for item in loaded)


def _require_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise SettlementEvidenceError(f"{name} must be a UTC-aware datetime")
    return value


def _require_minute(value: datetime, name: str) -> None:
    if (value.second, value.microsecond) != (0, 0):
        raise SettlementEvidenceError(f"{name} must be minute-aligned")


def nominal_index_bounds(
    rows: tuple[KlineRow, ...], *, window_start_utc: datetime, window_end_utc: datetime
) -> tuple[Fraction, Fraction]:
    """Exact equal-weight mean of the minute lows and of the minute highs over [start, end).

    Requires exactly one row per minute of the window, in order, with no other row: a missing,
    duplicated, extra or reordered minute raises.
    """
    start = _require_utc(window_start_utc, "window_start_utc")
    end = _require_utc(window_end_utc, "window_end_utc")
    _require_minute(start, "window_start_utc")
    _require_minute(end, "window_end_utc")
    if end <= start:
        raise SettlementEvidenceError("the window must end after it starts")
    minutes = (end - start) // _MINUTE
    expected = [start + i * _MINUTE for i in range(minutes)]
    if [row.open_utc for row in rows] != expected:
        raise SettlementEvidenceError(
            "the index klines must hold exactly one row per minute of the window, in order"
        )
    lower = sum((Fraction(row.low) for row in rows), Fraction(0)) / minutes
    upper = sum((Fraction(row.high) for row in rows), Fraction(0)) / minutes
    return lower, upper


def tick_widened_bounds(
    nominal_lower: Fraction, nominal_upper: Fraction, *, tick: Decimal
) -> tuple[Decimal, Decimal]:
    """Floor the lower to the tick grid minus one tick; ceil the upper plus one tick (exact)."""
    if not isinstance(tick, Decimal) or not tick.is_finite() or tick <= 0:
        raise SettlementEvidenceError("tick must be a finite positive Decimal")
    if not isinstance(nominal_lower, Fraction) or not isinstance(nominal_upper, Fraction):
        raise SettlementEvidenceError("the nominal bounds must be Fractions")
    if nominal_lower <= 0 or nominal_upper < nominal_lower:
        raise SettlementEvidenceError("the nominal bounds must satisfy 0 < lower <= upper")
    tick_ratio = Fraction(tick)
    lower_steps = math.floor(nominal_lower / tick_ratio) - 1
    upper_steps = math.ceil(nominal_upper / tick_ratio) + 1
    if lower_steps < 1:
        raise SettlementEvidenceError("the widened lower bound would not be positive")
    return (Decimal(lower_steps) * tick).quantize(tick), (Decimal(upper_steps) * tick).quantize(
        tick
    )


def trade_candle_bounds(
    rows: tuple[KlineRow, ...], *, open_utc: datetime
) -> tuple[Decimal, Decimal]:
    """Low and high of the one trade kline that opens exactly at `open_utc`."""
    when = _require_utc(open_utc, "open_utc")
    opens = [row.open_utc for row in rows]
    if len(set(opens)) != len(opens):
        raise SettlementEvidenceError("the trade klines hold a duplicated minute")
    matches = [row for row in rows if row.open_utc == when]
    if len(matches) != 1:
        raise SettlementEvidenceError(
            "the trade klines must hold exactly one candle at the terminal"
        )
    return matches[0].low, matches[0].high


def union_bounds(
    index_lower: Decimal, index_upper: Decimal, trade_low: Decimal, trade_high: Decimal
) -> tuple[Decimal, Decimal]:
    """Lower = min of the lowers, upper = max of the uppers; no proxy price is chosen."""
    if index_lower > index_upper or trade_low > trade_high:
        raise SettlementEvidenceError("each interval must have lower <= upper")
    return min(index_lower, trade_low), max(index_upper, trade_high)


def recompute_settlement_bounds(
    *,
    index_klines: bytes,
    trade_kline: bytes,
    window_start_utc: datetime,
    terminal_at_utc: datetime,
    tick: Decimal,
) -> RecomputedBounds:
    """Recompute every bound from the two committed kline bodies; any inconsistency raises."""
    index_rows = parse_klines(index_klines, what="index klines")
    trade_rows = parse_klines(trade_kline, what="trade klines")
    nominal_lower, nominal_upper = nominal_index_bounds(
        index_rows, window_start_utc=window_start_utc, window_end_utc=terminal_at_utc
    )
    index_lower, index_upper = tick_widened_bounds(nominal_lower, nominal_upper, tick=tick)
    trade_low, trade_high = trade_candle_bounds(trade_rows, open_utc=terminal_at_utc)
    price_lower, price_upper = union_bounds(index_lower, index_upper, trade_low, trade_high)
    return RecomputedBounds(
        nominal_lower=nominal_lower,
        nominal_upper=nominal_upper,
        index_lower=index_lower,
        index_upper=index_upper,
        trade_low=trade_low,
        trade_high=trade_high,
        price_lower=price_lower,
        price_upper=price_upper,
    )


def fraction_text(value: Fraction) -> str:
    """Render a Fraction as the manifest text "p/q" (already reduced by Fraction)."""
    if not isinstance(value, Fraction) or value <= 0:
        raise SettlementEvidenceError("only a positive Fraction has a text form")
    return f"{value.numerator}/{value.denominator}"


def parse_fraction_text(text: str) -> Fraction:
    """Strict "p/q": positive integers without sign or padding, denominator nonzero, reduced."""
    if not isinstance(text, str) or _FRACTION_TEXT.fullmatch(text) is None:
        raise SettlementEvidenceError('a fraction text must look like "p/q" with positive integers')
    numerator_text, denominator_text = text.split("/")
    numerator, denominator = int(numerator_text), int(denominator_text)
    if math.gcd(numerator, denominator) != 1:
        raise SettlementEvidenceError("a fraction text must already be reduced")
    return Fraction(numerator, denominator)
