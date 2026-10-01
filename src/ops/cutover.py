"""Cutover verifier: did a host switch lose data, and how long was OI collection down?

Phase 13.1 (D-14, D-15, D-22). The migration script captures a fingerprint of the
raw Parquet tree and a snapshot of the ``collector_watermarks`` table on the OLD
host before the stop and on the NEW host after the start, then runs ``report``.

  python -m src.ops.cutover fingerprint --raw-root R --out F
  python -m src.ops.cutover watermarks  --out F [--database-url URL]
  python -m src.ops.cutover report --old-fingerprint F --new-fingerprint F
        --old-watermarks F --new-watermarks F --raw-root R [--max-gap-minutes 60]
        [--window-end ISO] [--json-out F]

Exit codes of ``report``: 0 clean, 1 data loss (a missing or changed old file, a lost
or regressed watermark row), 3 OI gap above the threshold, 2 usage or input errors.
Data loss outranks the gap.

Two fingerprints are compared as sets of ``(path, sha256)``, never by byte counts.
The module imports no strategy code and never prints a database URL: errors print
only the exception type name, through ``scrub()``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.ops.backup import _database_url_from_env, _is_atomic_tmp, _sha256_file, _sqlalchemy_url
from src.ops.redaction import configure_logging, scrub

EXIT_CLEAN = 0
EXIT_DATA_LOSS = 1
EXIT_USAGE = 2
EXIT_GAP = 3

DEFAULT_MAX_GAP_MINUTES = 60


# --------------------------------------------------------------------------- #
# Time helpers (UTC everywhere, ISO-8601 with a trailing Z)
# --------------------------------------------------------------------------- #


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes (SQLite round-trips) are UTC, like collector._tick_epoch_ms."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_iso_utc(text: str) -> datetime:
    return _as_utc(datetime.fromisoformat(text))


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #


def fingerprint(raw_root: Path) -> dict[str, str]:
    """Map every Parquet file under ``raw_root`` (posix path, relative) to its sha256.

    Atomic-write temp files (``.<name>.<pid>.tmp``) are in-flight writes and are skipped.
    """
    result: dict[str, str] = {}
    if not raw_root.is_dir():
        return result
    for path in sorted(raw_root.rglob("*.parquet")):
        if not path.is_file() or _is_atomic_tmp(path.name):
            continue
        result[path.relative_to(raw_root).as_posix()] = _sha256_file(path)
    return result


def watermark_snapshot(database_url: str) -> dict[str, str]:
    """Every ``collector_watermarks`` row as ``"SYMBOL|data_class" -> last_tick_utc`` (ISO Z)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from src.db.models import CollectorWatermark

    engine = create_engine(_sqlalchemy_url(database_url))
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(
                    CollectorWatermark.symbol,
                    CollectorWatermark.data_class,
                    CollectorWatermark.last_tick_utc,
                )
            ).all()
    finally:
        engine.dispose()
    return {f"{symbol}|{data_class}": _iso_z(tick) for symbol, data_class, tick in rows}


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FileDiff:
    """Old files absent (``missing``) or altered (``changed``) on the new side; new-only ``added``.

    ``added`` files are the ticks collected after the switch, never loss.
    """

    missing: tuple[str, ...]
    changed: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def lost_data(self) -> bool:
        return bool(self.missing or self.changed)


@dataclass(frozen=True)
class WatermarkDiff:
    """Watermark rows gone from the new side (``lost``) or moved backwards (``regressed``)."""

    lost: tuple[str, ...]
    regressed: tuple[str, ...]

    @property
    def lost_data(self) -> bool:
        return bool(self.lost or self.regressed)


def compare_files(old: Mapping[str, str], new: Mapping[str, str]) -> FileDiff:
    """Compare two fingerprints as sets of ``(path, sha256)``."""
    new_set = set(new.items())
    missing = sorted(path for path in old if path not in new)
    changed = sorted(path for path in old if path in new and (path, old[path]) not in new_set)
    added = sorted(path for path in new if path not in old)
    return FileDiff(tuple(missing), tuple(changed), tuple(added))


def compare_watermarks(old: Mapping[str, str], new: Mapping[str, str]) -> WatermarkDiff:
    """A row present in old but absent in new is lost; one with an earlier tick regressed."""
    lost = sorted(key for key in old if key not in new)
    regressed = sorted(
        key for key in old if key in new and _parse_iso_utc(new[key]) < _parse_iso_utc(old[key])
    )
    return WatermarkDiff(tuple(lost), tuple(regressed))


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CutoverReport:
    files: FileDiff
    watermarks: WatermarkDiff

    @property
    def exit_code(self) -> int:
        if self.files.lost_data or self.watermarks.lost_data:
            return EXIT_DATA_LOSS
        return EXIT_CLEAN

    def as_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "files": {
                "missing": list(self.files.missing),
                "changed": list(self.files.changed),
                "added_count": len(self.files.added),
            },
            "watermarks": {
                "lost": list(self.watermarks.lost),
                "regressed": list(self.watermarks.regressed),
            },
        }


def build_report(
    old_files: Mapping[str, str],
    new_files: Mapping[str, str],
    old_watermarks: Mapping[str, str],
    new_watermarks: Mapping[str, str],
) -> CutoverReport:
    return CutoverReport(
        files=compare_files(old_files, new_files),
        watermarks=compare_watermarks(old_watermarks, new_watermarks),
    )


def render_text(report: CutoverReport) -> str:
    lines: list[str] = []
    if report.exit_code == EXIT_CLEAN:
        lines.append("CUTOVER VERDICT: CLEAN")
    else:
        lines.append("CUTOVER VERDICT: DATA LOSS")
    lines.append(
        f"files: {len(report.files.missing)} missing, {len(report.files.changed)} changed, "
        f"{len(report.files.added)} added since the switch"
    )
    lines.extend(f"  missing: {path}" for path in report.files.missing)
    lines.extend(f"  changed: {path}" for path in report.files.changed)
    lines.append(
        f"watermarks: {len(report.watermarks.lost)} lost, "
        f"{len(report.watermarks.regressed)} regressed"
    )
    lines.extend(f"  lost: {key}" for key in report.watermarks.lost)
    lines.extend(f"  regressed: {key}" for key in report.watermarks.regressed)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))


def _read_map(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError("expected a JSON object of strings")
    return dict(data)


def _cmd_fingerprint(args: argparse.Namespace) -> int:
    _write_json(Path(args.out), fingerprint(Path(args.raw_root)))
    return EXIT_CLEAN


def _cmd_watermarks(args: argparse.Namespace) -> int:
    url = args.database_url or _database_url_from_env()
    if not url:
        raise ValueError("no database url")
    _write_json(Path(args.out), watermark_snapshot(url))
    return EXIT_CLEAN


def _cmd_report(args: argparse.Namespace) -> int:
    report = build_report(
        _read_map(Path(args.old_fingerprint)),
        _read_map(Path(args.new_fingerprint)),
        _read_map(Path(args.old_watermarks)),
        _read_map(Path(args.new_watermarks)),
    )
    sys.stdout.write(render_text(report))
    if args.json_out:
        _write_json(Path(args.json_out), report.as_dict())
    return report.exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.ops.cutover", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fp = sub.add_parser("fingerprint", help="sha256 of every Parquet file under a raw root")
    fp.add_argument("--raw-root", required=True)
    fp.add_argument("--out", required=True)
    fp.set_defaults(func=_cmd_fingerprint)

    wm = sub.add_parser("watermarks", help="snapshot of the collector_watermarks table")
    wm.add_argument("--out", required=True)
    wm.add_argument("--database-url", default=None)
    wm.set_defaults(func=_cmd_watermarks)

    rp = sub.add_parser("report", help="compare old and new snapshots")
    rp.add_argument("--old-fingerprint", required=True)
    rp.add_argument("--new-fingerprint", required=True)
    rp.add_argument("--old-watermarks", required=True)
    rp.add_argument("--new-watermarks", required=True)
    rp.add_argument("--raw-root", default=None)
    rp.add_argument("--max-gap-minutes", type=int, default=DEFAULT_MAX_GAP_MINUTES)
    rp.add_argument("--window-end", default=None)
    rp.add_argument("--json-out", default=None)
    rp.set_defaults(func=_cmd_report)
    return parser


def _exit_code_of(exc: SystemExit) -> int:
    code = exc.code
    return code if isinstance(code, int) else EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _exit_code_of(exc)
    func: Callable[[argparse.Namespace], int] = args.func
    try:
        return func(args)
    except Exception as exc:
        print(scrub(f"cutover: {type(exc).__name__}"), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
