"""Pure-function quality gate for backfilled candle batches (D-10).

Fail-closed posture per DATA_PIPELINE.md §6 and ENGINEERING_PRINCIPLES.md §9:
  - Structural corruption (duplicate timestamps, impossible OHLC, timestamp
    regressions, negative values, more than 8 fractional digits or a
    non-finite Decimal) → reject the batch, NO overwrite.
  - Continuity gaps (missing sequence) → publish the batch but record a
    warning; downstream coverage tracking will flag it.
  - Zero-trade bars (volume 0, trade_count 0) are VALID: an illiquid minute is
    real data, counted as telemetry (`zero_trade_bars`), never rejected
    (D-15). A missing bar is still a gap, never a zero-trade bar.

Inputs are plain `Kline` dataclasses projected to a Polars frame so the
pure-function surface is testable without network or DB dependencies
(PATTERNS §8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import polars as pl
from src.adapters.binance_usdm import Kline

# Interval → millisecond duration. Single source of truth for the
# quality + paginator math; later phases extend the table when 15m
# arrives.
INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# The Parquet schema stores prices/volumes as Decimal(scale=8). Polars rounds
# (or re-scales the column) when a value carries more fractional digits, which
# would silently change hashed, immutable data — so it is a structural reject.
MAX_FRACTION_DIGITS = 8


def _is_bad_decimal(value: Decimal) -> bool:
    """True for a non-finite Decimal or one with more than 8 fractional digits."""
    if not value.is_finite():
        return True
    exponent = value.as_tuple().exponent
    return isinstance(exponent, int) and exponent < -MAX_FRACTION_DIGITS


def _has_bad_decimal(kline: Kline) -> bool:
    return any(
        _is_bad_decimal(v)
        for v in (
            kline.open,
            kline.high,
            kline.low,
            kline.close,
            kline.volume,
            kline.quote_volume,
        )
    )


@dataclass(frozen=True)
class QualityVerdict:
    """Result of one batch quality check.

    `structural_ok` is the gate: False ⇒ caller MUST NOT publish the batch
    (D-10 fail-closed). The other counters are telemetry for the
    coverage layer to report. `zero_trade_bars` is telemetry only (D-15);
    `bad_decimals` counts rows with a non-finite value or more than 8
    fractional digits and DOES fail the gate.
    """

    structural_ok: bool
    duplicates: int
    ohlc_violations: int
    timestamp_regressions: int
    gap_count: int
    negative_values: int = 0
    bad_durations: int = 0
    mixed_keys: int = 0
    zero_trade_bars: int = 0
    bad_decimals: int = 0


def klines_to_frame(klines: list[Kline]) -> pl.DataFrame:
    """Project a list of `Kline` to a Polars frame.

    The schema is the canonical candle schema used by the paginator
    (backfill), the quality gate, and the Parquet store.
    """
    if not klines:
        return pl.DataFrame(
            schema={
                "open_time_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
                "close_time_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
                "open": pl.Decimal(scale=8),
                "high": pl.Decimal(scale=8),
                "low": pl.Decimal(scale=8),
                "close": pl.Decimal(scale=8),
                "volume": pl.Decimal(scale=8),
                "quote_volume": pl.Decimal(scale=8),
                "trade_count": pl.Int64,
                "interval": pl.Utf8,
                "symbol": pl.Utf8,
            }
        )
    return pl.DataFrame(
        {
            "open_time_utc": [k.open_time_utc for k in klines],
            "close_time_utc": [k.close_time_utc for k in klines],
            "open": [k.open for k in klines],
            "high": [k.high for k in klines],
            "low": [k.low for k in klines],
            "close": [k.close for k in klines],
            "volume": [k.volume for k in klines],
            "quote_volume": [k.quote_volume for k in klines],
            "trade_count": [k.trade_count for k in klines],
            "interval": [k.interval for k in klines],
            "symbol": [k.symbol for k in klines],
        },
        schema_overrides={
            "open_time_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
            "close_time_utc": pl.Datetime(time_unit="ms", time_zone="UTC"),
        },
    )


def check_batch(klines: list[Kline], interval: str) -> QualityVerdict:
    """Return a quality verdict for one batch.

    The batch is expected to be sorted by `open_time_utc` ascending — the
    paginator enforces this on every publish. Out-of-order rows are still
    caught as `timestamp_regressions` so the test surface covers the
    pathological case.
    """
    if interval not in INTERVAL_MS:
        raise ValueError(
            f"unsupported interval {interval!r}; expected one of {sorted(INTERVAL_MS)}"
        )
    # Rows with a non-finite Decimal or excess precision are a structural
    # reject. They are counted here and excluded from every other predicate:
    # a NaN cannot be compared (raises) or projected to a Polars Decimal
    # column (panics), and excess precision would be silently rounded.
    bad_decimals = sum(1 for k in klines if _has_bad_decimal(k))
    if bad_decimals:
        klines = [k for k in klines if not _has_bad_decimal(k)]
        if not klines:
            return QualityVerdict(
                structural_ok=False,
                duplicates=0,
                ohlc_violations=0,
                timestamp_regressions=0,
                gap_count=0,
                bad_decimals=bad_decimals,
            )
    df = klines_to_frame(klines)
    if df.is_empty():
        return QualityVerdict(
            structural_ok=True,
            duplicates=0,
            ohlc_violations=0,
            timestamp_regressions=0,
            gap_count=0,
        )

    duplicates = df.filter(pl.col("open_time_utc").is_duplicated()).height

    # OHLC violations: high must be ≥ open, close, low; low must be ≤ open,
    # close, high. None of these may be violated.
    ohlc_violations = df.filter(
        (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("high") < pl.col("low"))
    ).height

    # Timestamp regression: open_time_utc must be strictly ascending. A
    # `diff == 0` is reported as a DUPLICATE (above), not as a regression —
    # conflating the two would force the test for a duplicate batch to also
    # see a non-zero regression count, which hides the separate failure modes
    # the paginator logs downstream.
    diffs = df["open_time_utc"].diff()
    ts_regression_count = 0
    if diffs.len() > 0:
        for v in diffs.to_list():
            if v is None:
                continue
            # Strict backwards step: each diff must be > 0. A zero diff is
            # a duplicate (counted above), not a regression.
            if v.total_seconds() * 1000 < 0:
                ts_regression_count += 1
    timestamp_regressions = ts_regression_count

    # Continuity: how many rows are missing between the first and last
    # open_time_utc if the batch were dense at the requested interval?
    # This is warn-only — batches publish with flags, never reject.
    interval_ms = INTERVAL_MS[interval]
    max_t = df["open_time_utc"].max()
    min_t = df["open_time_utc"].min()
    # Polars types the extrema as a broad scalar union; narrow to the
    # datetimes the Datetime column guarantees. Anything else is schema
    # drift — reject loudly (fail closed) instead of guessing gap math.
    if not isinstance(max_t, datetime) or not isinstance(min_t, datetime):
        raise ValueError(
            "quality gate: open_time_utc extrema are not datetimes "
            f"({max_t!r}, {min_t!r}) — schema drift, refusing batch"
        )
    span_ms = (max_t - min_t).total_seconds() * 1000
    if span_ms:
        expected = int(span_ms // interval_ms) + 1
    else:
        expected = df.height
    gap_count = max(0, expected - df.height)

    # Exchange-data structural rejects (checked on the raw rows so
    # Decimal comparisons stay in Python, never in frame SQL):
    # negative prices/volumes/trade counts, inverted close-times, and rows
    # from more than one symbol/interval. A zero trade count is NOT negative:
    # zero-trade bars are valid data (D-15) and only counted as telemetry.
    negative_values = sum(
        1
        for k in klines
        if k.open < 0
        or k.high < 0
        or k.low < 0
        or k.close < 0
        or k.volume < 0
        or k.quote_volume < 0
        or k.trade_count < 0
    )
    zero_trade_bars = sum(1 for k in klines if k.trade_count == 0)
    bad_durations = sum(
        1 for k in klines if k.close_time_utc <= k.open_time_utc
    )
    first_key = (klines[0].symbol, klines[0].interval)
    mixed_keys = sum(
        1 for k in klines if (k.symbol, k.interval) != first_key
    )

    structural_ok = (
        duplicates == 0
        and ohlc_violations == 0
        and timestamp_regressions == 0
        and negative_values == 0
        and bad_durations == 0
        and mixed_keys == 0
        and bad_decimals == 0
    )
    return QualityVerdict(
        structural_ok=structural_ok,
        duplicates=duplicates,
        ohlc_violations=ohlc_violations,
        timestamp_regressions=int(timestamp_regressions),
        gap_count=gap_count,
        negative_values=negative_values,
        bad_durations=bad_durations,
        mixed_keys=mixed_keys,
        zero_trade_bars=zero_trade_bars,
        bad_decimals=bad_decimals,
    )
