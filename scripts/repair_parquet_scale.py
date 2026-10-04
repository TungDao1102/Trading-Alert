"""Repair mixed-scale Decimal partitions by writing pinned COPIES (CR-03).

Partitions published before the writer pinned `Decimal(38, 8)` carry a Decimal
scale inferred from their own values. Published Parquet is immutable (D-04), so
this tool NEVER rewrites a file in place. It has two modes:

  * default (dry run): list every partition whose price / volume columns are
    not `Decimal(38, 8)`. Writes nothing.
  * `--apply --output-root NEW_ROOT`: write a corrected copy of every deviating
    partition under NEW_ROOT (same relative path). The input root is only read.
    NEW_ROOT must not exist or must be empty, and must not be inside the input
    root. Swapping the repaired copy in, or publishing it as a new dataset
    version, is a separate, deliberate step for the operator.

Casting to scale 8 is exact: the quality gate rejects any value with more than
8 fractional digits, and widening a scale never changes the value. A file
whose cast would lose a digit is reported and skipped, never written.

Usage:
    uv run python scripts/repair_parquet_scale.py --raw-root data/raw
    uv run python scripts/repair_parquet_scale.py --raw-root data/raw \\
        --apply --output-root data/raw_repaired
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from src.data.quality import PRICE_DECIMAL
from src.data.store import atomic_write_parquet

PRICE_COLUMNS = ("open", "high", "low", "close", "volume", "quote_volume")


@dataclass(frozen=True)
class Deviation:
    """One partition whose price columns are not the pinned Decimal type."""

    path: Path
    columns: tuple[str, ...]


def find_deviations(raw_root: Path) -> list[Deviation]:
    """Scan `raw_root` (read-only) for partitions not on `Decimal(38, 8)`."""
    out: list[Deviation] = []
    for path in sorted(raw_root.rglob("part.parquet")):
        schema = pl.read_parquet_schema(path)
        bad = tuple(
            name
            for name in PRICE_COLUMNS
            if name in schema
            and isinstance(schema[name], pl.Decimal)
            and schema[name] != PRICE_DECIMAL
        )
        if bad:
            out.append(Deviation(path=path, columns=bad))
    return out


def _is_inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def repair_copies(raw_root: Path, output_root: Path) -> tuple[int, list[Path]]:
    """Write pinned copies of every deviating partition. Returns `(written, skipped)`."""
    if _is_inside(output_root, raw_root):
        raise ValueError("--output-root must not be the input root or inside it")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("--output-root must not exist or must be empty")
    written = 0
    skipped: list[Path] = []
    for deviation in find_deviations(raw_root):
        frame = pl.read_parquet(deviation.path, hive_partitioning=False)
        fixed = frame.with_columns([pl.col(c).cast(PRICE_DECIMAL) for c in deviation.columns])
        # Exactness guard: widening must round-trip to the identical value.
        if any(not fixed[c].cast(frame.schema[c]).equals(frame[c]) for c in deviation.columns):
            skipped.append(deviation.path)
            continue
        target = output_root / deviation.path.relative_to(raw_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_parquet(fixed, target)
        written += 1
    return written, skipped


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-root", type=Path, default=Path("data") / "raw")
    parser.add_argument("--apply", action="store_true", help="write corrected copies")
    parser.add_argument("--output-root", type=Path, help="required with --apply")
    args = parser.parse_args(argv)

    deviations = find_deviations(args.raw_root)
    for deviation in deviations:
        print(f"deviates: {deviation.path} columns={','.join(deviation.columns)}")
    print(f"{len(deviations)} deviating partition(s) under {args.raw_root}")
    if not args.apply:
        print("dry run: nothing written (pass --apply --output-root NEW_ROOT to write copies)")
        return 0
    if args.output_root is None:
        print("--apply requires --output-root", file=sys.stderr)
        return 2
    written, skipped = repair_copies(args.raw_root, args.output_root)
    for path in skipped:
        print(f"skipped (cast not exact): {path}", file=sys.stderr)
    print(f"wrote {written} corrected copy(ies) under {args.output_root}")
    return 1 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
