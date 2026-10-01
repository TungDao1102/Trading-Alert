"""Deterministic stand-in for the collector, used only by the cutover docker test (13.1-09).

It runs inside the application image (``PYTHONPATH=/app``) and writes exactly what the real
collector writes, through the production writers: one Parquet tick per symbol via
``_write_oi_snapshot`` and the matching ``oi`` watermark via ``_advance_watermark`` in one
transaction. It never touches the network.

  fake_collector.py seed --symbols BTCUSDT ETHUSDT --start 2026-09-01T10:00:00Z --count 13
      one tick per 5 minutes per symbol, then the oi watermark at the last tick
  fake_collector.py tick
      one tick per symbol that already has an oi watermark, at FAKE_TICK_AT, watermark advanced;
      then sleep until terminated so ``up -d`` stays up and never ticks twice
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from src.adapters.binance_usdm import OiSnapshot
from src.data.collector import _advance_watermark, _make_sync_engine, _write_oi_snapshot
from src.db.models import CollectorWatermark

RAW_ROOT = Path(os.environ.get("FAKE_RAW_ROOT", "/app/data/raw"))
CADENCE = timedelta(minutes=5)


def _parse_utc(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _snapshot(symbol: str, at: datetime, index: int) -> OiSnapshot:
    return OiSnapshot(symbol=symbol, observed_at_utc=at, open_interest=Decimal(f"{1000 + index}.5"))


def seed(symbols: Sequence[str], start: datetime, count: int) -> None:
    last = start
    for index in range(count):
        last = start + CADENCE * index
        for symbol in symbols:
            _write_oi_snapshot(_snapshot(symbol, last, index), RAW_ROOT)
    engine = _make_sync_engine(None)
    with Session(engine) as session:
        for symbol in symbols:
            _advance_watermark(
                session,
                symbol=symbol,
                data_class="oi",
                last_tick_utc=last,
                updated_at_utc=last,
            )
        session.commit()
    engine.dispose()
    print(f"seeded {count} ticks for {len(symbols)} symbols, last {last.isoformat()}", flush=True)


def tick(at: datetime) -> list[str]:
    engine = _make_sync_engine(None)
    written: list[str] = []
    with Session(engine) as session:
        symbols = sorted(
            session.scalars(
                select(CollectorWatermark.symbol).where(CollectorWatermark.data_class == "oi")
            )
        )
        for index, symbol in enumerate(symbols):
            _write_oi_snapshot(_snapshot(symbol, at, 100 + index), RAW_ROOT)
            _advance_watermark(
                session,
                symbol=symbol,
                data_class="oi",
                last_tick_utc=at,
                updated_at_utc=at,
            )
            written.append(symbol)
        session.commit()
    engine.dispose()
    return written


def _sleep_until_terminated() -> None:
    def _stop(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while True:
        time.sleep(3600)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    seed_p = sub.add_parser("seed")
    seed_p.add_argument("--symbols", nargs="+", required=True)
    seed_p.add_argument("--start", required=True)
    seed_p.add_argument("--count", type=int, required=True)
    sub.add_parser("tick")
    args = parser.parse_args(argv)

    if args.mode == "seed":
        seed(args.symbols, _parse_utc(args.start), args.count)
        return 0
    raw = os.environ.get("FAKE_TICK_AT", "")
    if not raw:
        print("FAKE_TICK_AT is required in tick mode", file=sys.stderr)
        return 2
    written = tick(_parse_utc(raw))
    print(f"tick at {raw} for {','.join(written)}", flush=True)
    _sleep_until_terminated()
    return 0


if __name__ == "__main__":
    sys.exit(main())
