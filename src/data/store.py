"""Immutable per-day Hive-partitioned Parquet publish (D-04).

Layout (per DATA_PIPELINE §11 + 02-PATTERNS §9):

    data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet

Files are append/immutable. Republishing an existing file raises — repairs
publish a new version and supersede the manifest entry (RESEARCH §Anti-Patterns).
The DuckDB coverage view reads the same layout via `hive_partitioning=true`
(see `src/sql/coverage_v1.sql`).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import polars as pl
from src.adapters.binance_usdm import Kline
from src.data.quality import klines_to_frame

# Default root for the immutable raw store. Tests inject a tmpdir via
# `RAW_ROOT` argument to `publish_batch`.
DEFAULT_RAW_ROOT = Path("data") / "raw"


def partition_path(raw_root: Path, interval: str, symbol: str, day: date) -> Path:
    """Resolve one per-day partition directory."""
    return (
        raw_root
        / f"interval={interval}"
        / f"symbol={symbol}"
        / f"date={day.isoformat()}"
    )


def partition_file(raw_root: Path, interval: str, symbol: str, day: date) -> Path:
    """Resolve the canonical Parquet file path for a per-day partition."""
    return partition_path(raw_root, interval, symbol, day) / "part.parquet"


def publish_batch(
    klines: Iterable[Kline],
    *,
    interval: str,
    symbol: str,
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> list[Path]:
    """Publish `klines` as one or more per-day Parquet files.

    Returns the list of file paths actually written. If a target file
    already exists, this function raises `FileExistsError` — the caller
    (the paginator) MUST treat that as a fail-closed event (no silent
    overwrite per D-04).
    """
    klines_list = list(klines)
    if not klines_list:
        return []

    df = klines_to_frame(klines_list)
    # Polars expresses `date` over a Datetime column with `dt.date()`.
    # Compute the partition day once per row, then group.
    df = df.with_columns(pl.col("open_time_utc").dt.date().alias("__day"))
    paths: list[Path] = []
    for day_value, group in df.group_by("__day", maintain_order=True):
        # `group_by` yields (key, frame) tuples; key is a Series — first elem is the date.
        day: date = day_value[0]
        path = partition_file(raw_root, interval, symbol, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(
                f"refusing to overwrite immutable Parquet at {path} "
                "(D-04 immutability rule). Repair flow publishes a new version."
            )
        group_to_write = group.drop("__day")
        group_to_write.write_parquet(path)
        paths.append(path)
    return paths
