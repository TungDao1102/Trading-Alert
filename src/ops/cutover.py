"""Cutover verifier: did a host switch lose data, and how long was OI collection down?

Phase 13.1 (D-14, D-15, D-22). The migration script captures a fingerprint of the
raw Parquet tree and a snapshot of the ``collector_watermarks`` table on the OLD
host before the stop and on the NEW host after the start, then runs ``report``.

  python -m src.ops.cutover fingerprint --raw-root R --out F
  python -m src.ops.cutover watermarks  --out F [--database-url URL]
  python -m src.ops.cutover report --old-fingerprint F --new-fingerprint F
        --old-watermarks F --new-watermarks F --raw-root R [--max-gap-minutes 60]
        [--window-end ISO] [--json-out F]
  python -m src.ops.cutover advanced --old-watermarks F --new-watermarks F

Exit codes of ``report``: 0 clean, 1 data loss (a missing or changed old file, a lost
or regressed watermark row), 3 OI gap above the threshold, 2 usage or input errors.
Data loss outranks the gap.

``advanced`` is the migration script's "first new tick" probe: exit 0 when every old OI
watermark has moved strictly forward in the new snapshot, 1 while one has not, 2 on input errors.

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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.data.coverage import (
    DEFAULT_OI_INTERVAL_MS,
    TICK_GAP_FACTOR,
    GapRange,
    gap_ranges_for_files,
)
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
# OI gaps (D-14: the single gap definition of coverage.py, D-19 of Phase 13)
# --------------------------------------------------------------------------- #

_MS = timedelta(milliseconds=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_OI_DATA_CLASS = "oi"


@dataclass(frozen=True)
class SymbolGap:
    """The OI holes of one symbol inside the cutover window and the longest one in minutes."""

    symbol: str
    max_gap_minutes: int
    ranges: tuple[GapRange, ...]


def _epoch_ms(value: datetime) -> int:
    return (value - _EPOCH) // _MS


def _hole_minutes(hole: GapRange, step_ms: int) -> int:
    """Minutes of one hole in integer epoch milliseconds: end - start + step."""
    return (_epoch_ms(hole.end_utc) - _epoch_ms(hole.start_utc) + step_ms) // 60_000


def _symbol_tick_files(
    raw_root: Path, symbol: str, window_start: datetime, window_end: datetime
) -> list[Path]:
    """Explicit tick-file list of one symbol whose ``date=`` partition touches the window."""
    base = raw_root / f"data_class={_OI_DATA_CLASS}" / f"symbol={symbol}"
    first_day = window_start.date().isoformat()
    last_day = window_end.date().isoformat()
    files: list[Path] = []
    for path in sorted(base.glob("date=*/tick-*.parquet")):
        day = path.parent.name.removeprefix("date=")
        if first_day <= day <= last_day and not _is_atomic_tmp(path.name):
            files.append(path)
    return files


def oi_gaps(
    raw_root: Path,
    symbols: Sequence[str],
    window_start_utc: datetime,
    window_end_utc: datetime,
) -> tuple[SymbolGap, ...]:
    """Per-symbol OI holes inside the window, using ``coverage.gap_ranges_for_files``.

    A trailing hole (no tick yet after the last one) counts, so an outage that is still
    going on is reported rather than hidden.
    """
    step_ms = DEFAULT_OI_INTERVAL_MS
    result: list[SymbolGap] = []
    for symbol in sorted(set(symbols)):
        holes = gap_ranges_for_files(
            _symbol_tick_files(raw_root, symbol, window_start_utc, window_end_utc),
            series=_OI_DATA_CLASS,
            symbol=symbol,
            interval="5m",
            time_column="observed_at_utc",
            step_ms=step_ms,
            start_utc=window_start_utc,
            end_utc=window_end_utc,
            max_step_ms=TICK_GAP_FACTOR * step_ms,
        )
        longest = max((_hole_minutes(h, step_ms) for h in holes), default=0)
        result.append(SymbolGap(symbol, longest, tuple(holes)))
    return tuple(result)


def _oi_symbols_and_window_start(
    old_watermarks: Mapping[str, str],
) -> tuple[list[str], datetime | None]:
    """Symbols with an old ``oi`` watermark, and window start = min tick minus 2 cadences."""
    symbols: list[str] = []
    ticks: list[datetime] = []
    for key, value in old_watermarks.items():
        symbol, _, data_class = key.rpartition("|")
        if data_class == _OI_DATA_CLASS and symbol:
            symbols.append(symbol)
            ticks.append(_parse_iso_utc(value))
    if not ticks:
        return [], None
    margin = timedelta(milliseconds=TICK_GAP_FACTOR * DEFAULT_OI_INTERVAL_MS)
    return sorted(symbols), min(ticks) - margin


def default_window_end(now: datetime | None = None) -> datetime:
    """Now floored to the 5-minute OI cadence (UTC)."""
    current = _as_utc(now or datetime.now(UTC))
    floored_ms = _epoch_ms(current) // DEFAULT_OI_INTERVAL_MS * DEFAULT_OI_INTERVAL_MS
    return _EPOCH + timedelta(milliseconds=floored_ms)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CutoverReport:
    files: FileDiff
    watermarks: WatermarkDiff
    gaps: tuple[SymbolGap, ...]
    max_gap_minutes_threshold: int
    window_start_utc: datetime | None
    window_end_utc: datetime | None
    gap_error: str | None = None

    @property
    def worst_gap_minutes(self) -> int:
        return max((g.max_gap_minutes for g in self.gaps), default=0)

    @property
    def exit_code(self) -> int:
        """1 (data loss) outranks 3 (gap above threshold) outranks 0."""
        if self.files.lost_data or self.watermarks.lost_data:
            return EXIT_DATA_LOSS
        if self.worst_gap_minutes > self.max_gap_minutes_threshold:
            return EXIT_GAP
        return EXIT_CLEAN

    def as_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "files": {
                "missing": list(self.files.missing),
                "changed": list(self.files.changed),
                "added_count": len(self.files.added),
            },
            "gap_error": self.gap_error,
            "max_gap_minutes_threshold": self.max_gap_minutes_threshold,
            "oi_gaps": [
                {
                    "symbol": g.symbol,
                    "max_gap_minutes": g.max_gap_minutes,
                    "ranges": [
                        {
                            "start_utc": _iso_z(r.start_utc),
                            "end_utc": _iso_z(r.end_utc),
                            "missing": r.missing,
                        }
                        for r in g.ranges
                    ],
                }
                for g in self.gaps
            ],
            "watermarks": {
                "lost": list(self.watermarks.lost),
                "regressed": list(self.watermarks.regressed),
            },
            "window_end_utc": None if self.window_end_utc is None else _iso_z(self.window_end_utc),
            "window_start_utc": (
                None if self.window_start_utc is None else _iso_z(self.window_start_utc)
            ),
        }


def build_report(
    old_files: Mapping[str, str],
    new_files: Mapping[str, str],
    old_watermarks: Mapping[str, str],
    new_watermarks: Mapping[str, str],
    *,
    raw_root: Path | None = None,
    max_gap_minutes: int = DEFAULT_MAX_GAP_MINUTES,
    window_end_utc: datetime | None = None,
) -> CutoverReport:
    """Compare both snapshots and measure the OI gap of the new side's tick files.

    Window: start = minimum old OI watermark minus 2 cadences; end = ``window_end_utc``
    (default now floored to the 5-minute cadence). Symbols are those with an old OI
    watermark; with none, there is no OI series to measure.
    """
    symbols, window_start = _oi_symbols_and_window_start(old_watermarks)
    files = compare_files(old_files, new_files)
    watermarks = compare_watermarks(old_watermarks, new_watermarks)
    gap_error: str | None = None
    gaps: tuple[SymbolGap, ...] = ()
    window_end: datetime | None = None
    if symbols and window_start is not None:
        if raw_root is None:
            raise ValueError("raw_root is required when the old side has OI watermarks")
        window_end = _as_utc(window_end_utc) if window_end_utc else default_window_end()
        if window_end <= window_start:
            raise ValueError("window end must be after the window start")
        try:
            gaps = oi_gaps(raw_root, symbols, window_start, window_end)
        except Exception as exc:
            # An unreadable tick file (for example a corrupted one) must not hide data
            # loss that is already proven; with no loss the gap cannot be judged: raise.
            if not (files.lost_data or watermarks.lost_data):
                raise
            gap_error = type(exc).__name__
    return CutoverReport(
        files=files,
        watermarks=watermarks,
        gaps=gaps,
        max_gap_minutes_threshold=max_gap_minutes,
        window_start_utc=window_start if symbols else None,
        window_end_utc=window_end,
        gap_error=gap_error,
    )


_VERDICTS = {
    EXIT_CLEAN: "CUTOVER VERDICT: CLEAN",
    EXIT_DATA_LOSS: "CUTOVER VERDICT: DATA LOSS",
    EXIT_GAP: "CUTOVER VERDICT: OI GAP ABOVE THRESHOLD",
}

_STATEMENTS = (
    "OI gap minutes are permanent loss: open-interest snapshots cannot be fetched later.",
    "Funding gaps are recoverable by the funding sweep.",
    "The old host is shut down only by a human, and only after a clean report.",
)


def render_text(report: CutoverReport) -> str:
    lines: list[str] = [_VERDICTS[report.exit_code]]
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
    if report.window_start_utc is not None and report.window_end_utc is not None:
        lines.append(
            f"oi gap window: {_iso_z(report.window_start_utc)} .. "
            f"{_iso_z(report.window_end_utc)} (threshold {report.max_gap_minutes_threshold} min)"
        )
    else:
        lines.append("oi gap: no OI watermark on the old side, nothing to measure")
    if report.gap_error is not None:
        lines.append(f"oi gap could not be measured: {report.gap_error}")
    for gap in report.gaps:
        lines.append(f"  oi {gap.symbol}: largest gap {gap.max_gap_minutes} min")
        lines.extend(
            f"    hole {_iso_z(r.start_utc)} .. {_iso_z(r.end_utc)} ({r.missing} slots)"
            for r in gap.ranges
        )
    lines.extend(_STATEMENTS)
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


def oi_advanced(old: Mapping[str, str], new: Mapping[str, str]) -> bool:
    """True when every old ``<SYMBOL>|oi`` watermark moved strictly forward in ``new``."""
    suffix = f"|{_OI_DATA_CLASS}"
    return all(
        key in new and _parse_iso_utc(new[key]) > _parse_iso_utc(old[key])
        for key in old
        if key.endswith(suffix)
    )


def _cmd_advanced(args: argparse.Namespace) -> int:
    old = _read_map(Path(args.old_watermarks))
    new = _read_map(Path(args.new_watermarks))
    return EXIT_CLEAN if oi_advanced(old, new) else EXIT_DATA_LOSS


def _cmd_report(args: argparse.Namespace) -> int:
    report = build_report(
        _read_map(Path(args.old_fingerprint)),
        _read_map(Path(args.new_fingerprint)),
        _read_map(Path(args.old_watermarks)),
        _read_map(Path(args.new_watermarks)),
        raw_root=Path(args.raw_root) if args.raw_root else None,
        max_gap_minutes=args.max_gap_minutes,
        window_end_utc=_parse_iso_utc(args.window_end) if args.window_end else None,
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

    adv = sub.add_parser("advanced", help="exit 0 once every old OI watermark moved forward")
    adv.add_argument("--old-watermarks", required=True)
    adv.add_argument("--new-watermarks", required=True)
    adv.set_defaults(func=_cmd_advanced)
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
