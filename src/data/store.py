"""Immutable per-day Hive-partitioned Parquet publish (D-04).

Layout (per DATA_PIPELINE §11 + 02-PATTERNS §9):

    data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet

Files are append/immutable. Republishing an existing file raises — repairs
publish a new version and supersede the manifest entry (RESEARCH §Anti-Patterns).
The DuckDB coverage view reads the same layout via `hive_partitioning=true`
(see `src/sql/coverage_v1.sql`).

Writes are atomic (D-14, F-408): `atomic_write_parquet` writes a temporary
file in the same directory, fsyncs it and `os.replace`s it into place, so a
crash or kill mid-write leaves neither a torn `part.parquet` nor a stray
temporary file that a `date=*/part.parquet` glob could pick up.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import polars as pl
from src.adapters.binance_usdm import Kline
from src.data.quality import klines_to_frame

# Default root for the immutable raw store. Tests inject a tmpdir via
# `RAW_ROOT` argument to `publish_batch`.
DEFAULT_RAW_ROOT = Path("data") / "raw"

# Windows can refuse `os.replace` with PermissionError while an indexer or
# antivirus scanner briefly holds the freshly written temp file. Retry a
# bounded number of times, then fail closed (never loop forever).
REPLACE_MAX_ATTEMPTS = 5
REPLACE_RETRY_SLEEP_SECONDS = 0.1


def atomic_write_parquet(frame: pl.DataFrame, path: Path) -> None:
    """Write `frame` to `path` atomically and never overwrite (D-14, D-04).

    Sequence: temp file in the SAME directory (so the final rename never
    crosses a filesystem), fsync, existence check, `os.replace`. The temp name
    starts with "." and ends with ".tmp" so it can never match the
    `part.parquet` glob the readers use. On any failure the temp file is
    removed and `path` does not exist.

    `os.replace` overwrites silently on both Windows and POSIX, so the
    immutability rule needs the explicit `path.exists()` check: an existing
    file raises `FileExistsError` and is left byte-for-byte untouched. The
    check and the replace are not one atomic step; this is safe under the
    single-writer assumption (one collector/backfill process owns a symbol's
    partitions), which the cursor store and the per-process temp name share.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        frame.write_parquet(tmp)
        with open(tmp, "rb+") as handle:
            os.fsync(handle.fileno())
        if path.exists():
            raise FileExistsError(
                f"refusing to overwrite immutable Parquet at {path} "
                "(D-04 immutability rule). Repair flow publishes a new version."
            )
        for attempt in range(1, REPLACE_MAX_ATTEMPTS + 1):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == REPLACE_MAX_ATTEMPTS:
                    raise
                time.sleep(REPLACE_RETRY_SLEEP_SECONDS)
    finally:
        tmp.unlink(missing_ok=True)


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

    # Batch homogeneity: a batch mixing symbols/intervals — or rows that
    # do not match the caller's partition args — would cross-contaminate
    # the immutable partition. Reject instead of trusting caller args.
    row_symbols = {k.symbol for k in klines_list}
    row_intervals = {k.interval for k in klines_list}
    if row_symbols != {symbol} or row_intervals != {interval}:
        raise ValueError(
            f"refusing to publish heterogeneous batch under "
            f"({symbol}, {interval}): rows carry symbols={sorted(row_symbols)} "
            f"intervals={sorted(row_intervals)}"
        )

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
        atomic_write_parquet(group_to_write, path)
        paths.append(path)
    return paths
