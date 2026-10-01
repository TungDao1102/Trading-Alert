"""Extend phase4 candles.csv additively with gap, warm-up-short, and setup blocks.

Per plan 04-02 task 3: extend candles.csv only additively (no existing
row modified) with:
  1. A gap-injection block (consecutive missing hours in the 1H stream)
  2. A warm-up-short prefix block (insufficient history for EMA200)
  3. A clean trend-pullback setup window with regime-confirming 4H structure

The new blocks use timestamps AFTER the existing fixture's last bar so
they don't interfere with the existing 250-bar 1H + 250-bar 4H series.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

FIXTURES_DIR = Path("tests/fixtures/phase4")
CSV_PATH = FIXTURES_DIR / "candles.csv"


def _build_gap_block() -> list[dict]:
    """Build a 1H gap-injection block: 10 bars with a 5-hour gap in the middle.

    Bars 0..4 are continuous; bar 5 is missing (gap); bars 5..9 continue
    after the gap. The gap means features spanning it must report
    GAP_IN_SOURCE.
    """
    base = datetime(2026, 10, 21, 0, 0, 0, tzinfo=UTC)
    rows: list[dict] = []
    for i in range(10):
        if i >= 5:
            # Skip 5 hours to create the gap.
            offset = i + 5
        else:
            offset = i
        open_time = base + timedelta(hours=offset)
        close = Decimal("63000.00") + Decimal(str(i * 10))
        rows.append(
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "open_time_utc": open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": str(close - Decimal("10.00")),
                "high": str(close + Decimal("50.00")),
                "low": str(close - Decimal("60.00")),
                "close": str(close),
                "volume": "100.00",
            }
        )
    return rows


def _build_warmup_short_block() -> list[dict]:
    """Build a 1H warm-up-short block: 50 bars (insufficient for EMA200).

    With only 50 bars, EMA200(1H) is WARMUP_INSUFFICIENT. The strategy
    must NO_TRADE with WARMUP_INSUFFICIENT.
    """
    base = datetime(2026, 10, 22, 0, 0, 0, tzinfo=UTC)
    rows: list[dict] = []
    for i in range(50):
        open_time = base + timedelta(hours=i)
        close = Decimal("64000.00") + Decimal(str(i * 10))
        rows.append(
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "open_time_utc": open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": str(close - Decimal("10.00")),
                "high": str(close + Decimal("50.00")),
                "low": str(close - Decimal("60.00")),
                "close": str(close),
                "volume": "100.00",
            }
        )
    return rows


def _build_setup_window_1h() -> list[dict]:
    """Build a 1H clean trend-pullback setup window: 250 bars with a clear pullback.

    190 bars of gentle uptrend (warm-up), 30 bars of continued uptrend,
    20 bars of pullback, 1 swing-low bar, 8 bars of slow recovery,
    1 reversal confirmation bar at index 249.
    """
    base = datetime(2026, 10, 25, 0, 0, 0, tzinfo=UTC)
    rows: list[dict] = []
    for i in range(250):
        if i < 190:
            close = Decimal("65000.00") + Decimal(str(i * 5 + 50))
        elif i < 220:
            close = Decimal("65000.00") + Decimal(str(190 * 5 + 50 + (i - 189) * 100))
        elif i < 240:
            close = Decimal("65000.00") + Decimal(str(190 * 5 + 50 + 30 * 100 - (i - 219) * 110))
        elif i == 240:
            close = Decimal("65900.00")
        elif i < 249:
            close = Decimal("65900.00") + Decimal(str((i - 240) * 80))
        else:
            close = Decimal("66620.00")
        open_time = base + timedelta(hours=i)
        rows.append(
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "open_time_utc": open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": str(close - Decimal("10.00")),
                "high": str(close + Decimal("50.00")),
                "low": str(close - Decimal("60.00")),
                "close": str(close),
                "volume": "100.00",
            }
        )
    return rows


def _build_setup_window_4h() -> list[dict]:
    """Build a 4H regime-confirming context for the setup window: 250 bars uptrend.

    Starts at 2026-10-20T16:00:00Z to maintain continuity with the
    existing 4H series (whose last bar opens at 2026-10-20T12:00:00Z).
    The 4H close prices continue the existing uptrend pattern
    (65000 + i*50 + 30) so the EMA50(4H) stays valid (no GAP_IN_SOURCE).
    """
    base = datetime(2026, 10, 20, 16, 0, 0, tzinfo=UTC)
    rows: list[dict] = []
    for i in range(250):
        close = Decimal("65000.00") + Decimal(str(i * 50 + 30))
        open_time = base + timedelta(hours=4 * i)
        rows.append(
            {
                "symbol": "BTCUSDT",
                "timeframe": "4h",
                "open_time_utc": open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": str(close - Decimal("20.00")),
                "high": str(close + Decimal("40.00")),
                "low": str(close - Decimal("40.00")),
                "close": str(close),
                "volume": "500.00",
            }
        )
    return rows


def main() -> None:
    # Read existing rows.
    with CSV_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_rows = list(reader)
        fieldnames = reader.fieldnames

    print(f"Existing rows: {len(existing_rows)}")

    # Build new blocks.
    gap_block = _build_gap_block()
    warmup_short_block = _build_warmup_short_block()
    setup_1h = _build_setup_window_1h()
    setup_4h = _build_setup_window_4h()

    new_rows = gap_block + warmup_short_block + setup_1h + setup_4h
    print(f"New rows to append: {len(new_rows)}")
    print(f"  gap block: {len(gap_block)}")
    print(f"  warm-up-short block: {len(warmup_short_block)}")
    print(f"  setup window 1H: {len(setup_1h)}")
    print(f"  setup window 4H: {len(setup_4h)}")

    # Append additively (no existing row modified).
    with CSV_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            writer.writerow(row)

    print(f"Total rows after append: {len(existing_rows) + len(new_rows)}")


if __name__ == "__main__":
    main()
