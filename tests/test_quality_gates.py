"""Tests for the pure-function quality gate + immutable Parquet store.

This file lands the test surface the 02-03 plan calls out as the six
behaviors (02-03-PLAN §tasks[1].behavior):

  1. Duplicated `open_time_utc` rows yield structural failure with the
     duplicate count.
  2. `high < open` OR `low > close` yields structural failure with the
     OHLC violation count.
  3. Shuffled timestamps yield structural failure with the regression
     count.
  4. Missing middle row keeps structural pass and reports `gap_count == 1`
     (warn-only continuity flag — D-10).
  5. Dense ordered batch passes with all counters zero.
  6. Publishing to an existing per-day partition path raises
     `FileExistsError` instead of silently overwriting (D-04 immutability).

Tests 1-5 exercise `src.data.quality.check_batch` (the Polars pure-function
surface from 02-RESEARCH §Code Examples); test 6 exercises
`src.data.store.publish_batch`. The adapter and paginator are NOT tested
here — they live in `tests/test_tracer_slice.py` (Tracer Slice) and
`tests/test_backfill.py` (Live-5 Bootstrap).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from src.adapters.binance_usdm import Kline
from src.data.quality import QualityVerdict, check_batch
from src.data.store import partition_file, publish_batch

# --------------------------------------------------------------------------- #
# Test scaffold.
# --------------------------------------------------------------------------- #


INTERVAL = "1m"
INTERVAL_MS = 60_000
# Fixed reference instant (2023-11-14T22:13:20Z) — chosen so every test
# resolves to a stable UTC timestamp without depending on wall-clock.
BASE_OPEN_MS = 1_700_000_000_000


def _mk_kline(
    *,
    open_ms: int,
    close_ms: int,
    symbol: str = "BTCUSDT",
    interval: str = INTERVAL,
    open: str = "100.00",
    high: str = "100.00",
    low: str = "100.00",
    close: str = "100.00",
) -> Kline:
    """Build a Kline with explicit OHLC — defaults are valid (high ≥ all, low ≤ all)."""
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        close_time_utc=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1.0"),
        quote_volume=Decimal("100.00"),
        trade_count=10,
    )


def _three_minute_bars(
    *,
    ohlc_valid: bool = True,
    oh: tuple[str, str, str, str] | None = None,
) -> list[Kline]:
    """Build three consecutive 1m bars starting at `BASE_OPEN_MS`.

    Each bar spans `[open_ms, open_ms + INTERVAL_MS - 1]`. By default the
    bars are dense and OHLC-valid. Pass `ohlc_valid=False` to make the
    middle bar violate high/open relationship (high < open).
    """
    o0, h0, l0, c0 = ("100.00", "100.00", "100.00", "100.00")
    o1, h1, l1, c1 = ("101.00", "101.00", "101.00", "101.00")
    o2, h2, l2, c2 = ("102.00", "102.00", "102.00", "102.00")
    if oh is not None:
        o1, h1, l1, c1 = oh
    elif not ohlc_valid:
        # Make the middle bar violate: high below open.
        o1, h1, l1, c1 = "101.00", "99.00", "101.00", "100.00"
    return [
        _mk_kline(
            open_ms=BASE_OPEN_MS,
            close_ms=BASE_OPEN_MS + INTERVAL_MS - 1,
            open=o0,
            high=h0,
            low=l0,
            close=c0,
        ),
        _mk_kline(
            open_ms=BASE_OPEN_MS + INTERVAL_MS,
            close_ms=BASE_OPEN_MS + 2 * INTERVAL_MS - 1,
            open=o1,
            high=h1,
            low=l1,
            close=c1,
        ),
        _mk_kline(
            open_ms=BASE_OPEN_MS + 2 * INTERVAL_MS,
            close_ms=BASE_OPEN_MS + 3 * INTERVAL_MS - 1,
            open=o2,
            high=h2,
            low=l2,
            close=c2,
        ),
    ]


# --------------------------------------------------------------------------- #
# Test 1 — duplicated open_time yields structural failure with duplicate count.
# --------------------------------------------------------------------------- #


def test_duplicate_open_time_yields_structural_failure() -> None:
    """Two rows sharing `open_time_utc` are counted as duplicates and the
    batch is rejected (`structural_ok == False`).

    Per D-10: duplicate timestamps are a structural-corruption event; the
    paginator MUST NOT publish the batch.
    """
    base = _three_minute_bars()
    # Re-emit the middle bar so we have two rows at `BASE_OPEN_MS + 1m`.
    duplicate = base[1]
    batch = [base[0], base[1], duplicate, base[2]]

    verdict = check_batch(batch, INTERVAL)

    assert isinstance(verdict, QualityVerdict)
    assert verdict.structural_ok is False, (
        "duplicated open_time must reject the batch (D-10 fail-closed)"
    )
    # Polars' `is_duplicated()` marks every occurrence of a duplicated
    # value, so two rows sharing `open_time` => duplicates == 2.
    assert verdict.duplicates == 2
    # No other failure modes in this batch.
    assert verdict.ohlc_violations == 0
    assert verdict.timestamp_regressions == 0


# --------------------------------------------------------------------------- #
# Test 2 — high < open OR low > close yields structural failure with violation count.
# --------------------------------------------------------------------------- #


def test_high_below_open_yields_structural_failure() -> None:
    """A row whose `high < open` is an impossible OHLC relationship (DATA_PIPELINE §6)."""
    batch = _three_minute_bars(ohlc_valid=False)

    verdict = check_batch(batch, INTERVAL)

    assert verdict.structural_ok is False
    assert verdict.ohlc_violations == 1
    # No other failure modes — only the middle bar is malformed.
    assert verdict.duplicates == 0
    assert verdict.timestamp_regressions == 0


def test_low_above_close_yields_structural_failure() -> None:
    """A row whose `low > close` is symmetric to `high < open` — same gate."""
    # middle bar: open=100, high=101, low=101, close=100  → low (101) > close (100)
    batch = _three_minute_bars(oh=("100.00", "101.00", "101.00", "100.00"))

    verdict = check_batch(batch, INTERVAL)

    assert verdict.structural_ok is False
    assert verdict.ohlc_violations == 1
    assert verdict.duplicates == 0
    assert verdict.timestamp_regressions == 0


# --------------------------------------------------------------------------- #
# Test 3 — shuffled timestamps yield structural failure with regression count.
# --------------------------------------------------------------------------- #


def test_shuffled_timestamps_yield_structural_failure() -> None:
    """Bars that are not strictly ascending violate D-10.

    Reorder the dense batch to [middle, first, last] so the cursor would
    step backwards if we let it through. The quality gate MUST flag the
    regression before the paginator advances.
    """
    base = _three_minute_bars()
    shuffled = [base[1], base[0], base[2]]

    verdict = check_batch(shuffled, INTERVAL)

    assert verdict.structural_ok is False
    # The diff at index 1 is negative (middle.open < first.open ⇒ diff < 0)
    # ⇒ exactly one regression counted.
    assert verdict.timestamp_regressions == 1
    assert verdict.duplicates == 0
    assert verdict.ohlc_violations == 0


# --------------------------------------------------------------------------- #
# Test 4 — missing middle row keeps structural pass and reports gap_count == 1.
# --------------------------------------------------------------------------- #


def test_missing_middle_row_is_warn_only_continuity_flag() -> None:
    """A gap is continuity-only — `structural_ok` stays True; `gap_count == 1`.

    The plan §tasks[1].behavior[4] is explicit: gaps publish with flags,
    they are never silent failures. Downstream coverage tracking flags
    the gap (D-11) but the batch itself is not rejected.
    """
    full = _three_minute_bars()
    gap = [full[0], full[2]]  # drop the middle bar

    verdict = check_batch(gap, INTERVAL)

    assert verdict.structural_ok is True, (
        "continuity gap must NOT reject the batch (D-10 warn-only)"
    )
    assert verdict.gap_count == 1
    assert verdict.duplicates == 0
    assert verdict.ohlc_violations == 0
    assert verdict.timestamp_regressions == 0


# --------------------------------------------------------------------------- #
# Test 5 — dense ordered batch passes with all counts zero.
# --------------------------------------------------------------------------- #


def test_dense_ordered_batch_passes_with_zero_counts() -> None:
    """A fully dense, ordered, OHLC-valid batch is the baseline."""
    batch = _three_minute_bars()

    verdict = check_batch(batch, INTERVAL)

    assert verdict.structural_ok is True
    assert verdict.duplicates == 0
    assert verdict.ohlc_violations == 0
    assert verdict.timestamp_regressions == 0
    assert verdict.gap_count == 0


def test_empty_batch_is_structural_pass() -> None:
    """An empty list short-circuits to a clean verdict (no rows ⇒ no faults)."""
    verdict = check_batch([], INTERVAL)

    assert verdict.structural_ok is True
    assert verdict.duplicates == 0
    assert verdict.ohlc_violations == 0
    assert verdict.timestamp_regressions == 0
    assert verdict.gap_count == 0


def test_unsupported_interval_raises_value_error() -> None:
    """The gate refuses to interpret an unknown timeframe.

    This is a hard contract — feeding `check_batch` an unsupported
    interval would silently emit a meaningless `gap_count`.
    """
    batch = _three_minute_bars()
    with pytest.raises(ValueError, match="unsupported interval"):
        check_batch(batch, "7z")


# --------------------------------------------------------------------------- #
# Test 6 — publishing to an existing partition path raises (no overwrite).
# --------------------------------------------------------------------------- #


def test_publishing_to_existing_partition_path_raises(
    tmp_path: Path,
) -> None:
    """Immutability rule (D-04): republishing the same partition raises.

    The store is the immutable raw layer; repairs publish a NEW version
    and supersede the manifest entry, they never silently overwrite.
    """
    batch = _three_minute_bars()
    interval = INTERVAL
    symbol = "BTCUSDT"

    # First publish lands the per-day partition file.
    written = publish_batch(batch, interval=interval, symbol=symbol, raw_root=tmp_path)
    assert len(written) == 1
    expected_path = partition_file(
        tmp_path, interval, symbol, datetime.fromtimestamp(BASE_OPEN_MS / 1000, tz=UTC).date()
    )
    assert written[0] == expected_path
    assert expected_path.exists()

    # Second publish to the same target path MUST raise (no silent overwrite).
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable Parquet"):
        publish_batch(batch, interval=interval, symbol=symbol, raw_root=tmp_path)


# --------------------------------------------------------------------------- #
# Zero-trade bars (D-15, F-409) and the no-silent-rounding precision guard.
# --------------------------------------------------------------------------- #


def _zero_trade(bar: Kline) -> Kline:
    """An illiquid minute: flat price, no volume, no trades."""
    return replace(
        bar,
        open=bar.close,
        high=bar.close,
        low=bar.close,
        volume=Decimal("0"),
        quote_volume=Decimal("0"),
        trade_count=0,
    )


def test_zero_trade_bar_is_accepted_and_counted() -> None:
    """A bar with volume 0 and trade_count 0 is real data, not corruption (D-15).

    It passes the gate and is counted as telemetry only; a missing bar stays
    a gap (see `test_missing_middle_row_is_warn_only_continuity_flag`).
    """
    bars = _three_minute_bars()
    bars[1] = _zero_trade(bars[1])

    verdict = check_batch(bars, INTERVAL)

    assert verdict.structural_ok is True
    assert verdict.zero_trade_bars == 1
    assert verdict.negative_values == 0
    assert verdict.gap_count == 0


def test_negative_trade_count_is_rejected() -> None:
    bars = _three_minute_bars()
    bars[1] = replace(bars[1], trade_count=-1)

    verdict = check_batch(bars, INTERVAL)

    assert verdict.structural_ok is False
    assert verdict.negative_values == 1


def test_negative_volume_is_still_rejected() -> None:
    bars = _three_minute_bars()
    bars[1] = replace(bars[1], volume=Decimal("-1"))

    verdict = check_batch(bars, INTERVAL)

    assert verdict.structural_ok is False
    assert verdict.negative_values == 1


def test_missing_bar_is_a_gap_not_a_zero_trade_bar() -> None:
    full = _three_minute_bars()

    verdict = check_batch([full[0], full[2]], INTERVAL)

    assert verdict.gap_count == 1
    assert verdict.zero_trade_bars == 0


def test_excess_precision_is_rejected() -> None:
    """More than 8 fractional digits would be silently rounded by Polars."""
    bars = _three_minute_bars()
    bars[1] = replace(bars[1], low=Decimal("100"), close=Decimal("100.123456789"))

    verdict = check_batch(bars, INTERVAL)

    assert verdict.structural_ok is False
    assert verdict.bad_decimals == 1


def test_eight_fractional_digits_pass() -> None:
    bars = _three_minute_bars()
    bars[1] = replace(bars[1], low=Decimal("100"), close=Decimal("100.12345678"))

    verdict = check_batch(bars, INTERVAL)

    assert verdict.structural_ok is True
    assert verdict.bad_decimals == 0


def test_non_finite_decimal_is_rejected_without_raising() -> None:
    bars = _three_minute_bars()
    bars[1] = replace(bars[1], volume=Decimal("NaN"))

    verdict = check_batch(bars, INTERVAL)

    assert verdict.structural_ok is False
    assert verdict.bad_decimals == 1
