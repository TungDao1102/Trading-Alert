"""Tests for the cutover verifier (Phase 13.1, plan 07; D-14, D-15, D-22).

Fixtures are real Parquet tick files written by the collector's own production
writer (`_write_oi_snapshot`), and a real SQLite database whose tables come from
`Base.metadata`, so the verifier is exercised against the exact on-disk layout it
will see on the two hosts.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.adapters.binance_usdm import OiSnapshot
from src.data.collector import _write_oi_snapshot
from src.db.models import Base, CollectorWatermark
from src.ops import cutover

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def _tick(root: Path, symbol: str, at: datetime) -> Path:
    return _write_oi_snapshot(
        OiSnapshot(symbol=symbol, observed_at_utc=at, open_interest=Decimal("1234.5")),
        root,
    )


def _ticks(root: Path, symbols: tuple[str, ...], start: datetime, end: datetime) -> None:
    """Write a 5-minute tick for every symbol from `start` to `end` inclusive."""
    at = start
    while at <= end:
        for symbol in symbols:
            _tick(root, symbol, at)
        at += timedelta(minutes=5)


def _db(tmp_path: Path, name: str, rows: dict[tuple[str, str], datetime]) -> str:
    url = f"sqlite:///{(tmp_path / name).as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for (symbol, data_class), tick in rows.items():
            session.add(
                CollectorWatermark(
                    symbol=symbol,
                    data_class=data_class,
                    last_tick_utc=tick,
                    updated_at_utc=tick,
                )
            )
        session.commit()
    engine.dispose()
    return url


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, str]) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# fingerprint
# --------------------------------------------------------------------------- #


def test_fingerprint_hashes_parquet_and_skips_atomic_tmp(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    files = [_tick(root, "BTCUSDT", T0 + timedelta(minutes=5 * i)) for i in range(3)]
    stray = files[0].with_name(".tick-x.parquet.123.tmp")
    stray.write_bytes(b"half written")

    result = cutover.fingerprint(root)

    expected = {p.relative_to(root).as_posix(): _sha256(p) for p in files}
    assert result == expected
    assert len(result) == 3
    assert all("\\" not in key for key in result)


def test_fingerprint_missing_root_is_empty(tmp_path: Path) -> None:
    assert cutover.fingerprint(tmp_path / "nope") == {}


# --------------------------------------------------------------------------- #
# watermark_snapshot
# --------------------------------------------------------------------------- #


def test_watermark_snapshot_renders_iso_utc_z(tmp_path: Path) -> None:
    url = _db(
        tmp_path,
        "a.db",
        {("BTCUSDT", "oi"): T0, ("ETHUSDT", "funding"): T0 + timedelta(hours=8)},
    )

    snap = cutover.watermark_snapshot(url)

    assert snap == {
        "BTCUSDT|oi": "2026-10-01T10:00:00Z",
        "ETHUSDT|funding": "2026-10-01T18:00:00Z",
    }


# --------------------------------------------------------------------------- #
# compare_*
# --------------------------------------------------------------------------- #


def test_compare_files_sets_of_path_and_hash() -> None:
    old = {"a": "1", "b": "2", "c": "3"}
    new = {"a": "1", "b": "X", "d": "4"}

    diff = cutover.compare_files(old, new)

    assert diff.missing == ("c",)
    assert diff.changed == ("b",)
    assert diff.added == ("d",)


def test_compare_watermarks_lost_and_regressed() -> None:
    old = {
        "A|oi": "2026-10-01T10:00:00Z",
        "B|oi": "2026-10-01T10:00:00Z",
        "C|oi": "2026-10-01T10:00:00Z",
    }
    new = {
        "A|oi": "2026-10-01T10:05:00Z",
        "B|oi": "2026-10-01T09:55:00Z",
        "D|oi": "2026-10-01T10:00:00Z",
    }

    diff = cutover.compare_watermarks(old, new)

    assert diff.lost == ("C|oi",)
    assert diff.regressed == ("B|oi",)


# --------------------------------------------------------------------------- #
# CLI tracer: fingerprint x2, watermarks x2, report
# --------------------------------------------------------------------------- #


class _Scenario:
    """Old root/new root (copy plus one extra tick) and old/new watermark files."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.old_root = tmp_path / "old_raw"
        self.new_root = tmp_path / "new_raw"
        _ticks(self.old_root, ("BTCUSDT",), T0, T0 + timedelta(minutes=10))
        shutil.copytree(self.old_root, self.new_root)
        _tick(self.new_root, "BTCUSDT", T0 + timedelta(minutes=15))
        self.last_old = T0 + timedelta(minutes=10)
        self.old_db = _db(tmp_path, "old.db", {("BTCUSDT", "oi"): self.last_old})
        self.new_db = _db(
            tmp_path, "new.db", {("BTCUSDT", "oi"): self.last_old + timedelta(minutes=5)}
        )

    def capture(self) -> None:
        t = self.tmp
        assert (
            cutover.main(
                ["fingerprint", "--raw-root", str(self.old_root), "--out", str(t / "fp_old.json")]
            )
            == 0
        )
        assert (
            cutover.main(
                ["fingerprint", "--raw-root", str(self.new_root), "--out", str(t / "fp_new.json")]
            )
            == 0
        )
        assert (
            cutover.main(
                ["watermarks", "--database-url", self.old_db, "--out", str(t / "wm_old.json")]
            )
            == 0
        )
        assert (
            cutover.main(
                ["watermarks", "--database-url", self.new_db, "--out", str(t / "wm_new.json")]
            )
            == 0
        )

    def report(self, *extra: str) -> int:
        t = self.tmp
        return cutover.main(
            [
                "report",
                "--old-fingerprint",
                str(t / "fp_old.json"),
                "--new-fingerprint",
                str(t / "fp_new.json"),
                "--old-watermarks",
                str(t / "wm_old.json"),
                "--new-watermarks",
                str(t / "wm_new.json"),
                "--raw-root",
                str(self.new_root),
                "--window-end",
                "2026-10-01T10:16:00Z",
                *extra,
            ]
        )


def test_cli_report_clean_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sc = _Scenario(tmp_path)
    sc.capture()
    capsys.readouterr()

    assert sc.report() == 0

    assert "CLEAN" in capsys.readouterr().out


def test_cli_output_files_use_lf_and_sorted_keys(tmp_path: Path) -> None:
    sc = _Scenario(tmp_path)
    sc.capture()

    raw = (tmp_path / "fp_old.json").read_bytes()
    assert b"\r" not in raw
    keys = list(json.loads(raw))
    assert keys == sorted(keys)


def test_cli_report_missing_file_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sc = _Scenario(tmp_path)
    victim = next(sc.new_root.rglob("*.parquet"))
    rel = victim.relative_to(sc.new_root).as_posix()
    victim.unlink()
    sc.capture()
    capsys.readouterr()

    assert sc.report() == 1

    out = capsys.readouterr().out
    assert rel in out
    assert "CLEAN" not in out


def test_cli_report_changed_file_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sc = _Scenario(tmp_path)
    victim = next(sc.new_root.rglob("*.parquet"))
    rel = victim.relative_to(sc.new_root).as_posix()
    data = bytearray(victim.read_bytes())
    data[-1] ^= 0xFF
    victim.write_bytes(bytes(data))
    sc.capture()
    capsys.readouterr()

    assert sc.report() == 1

    out = capsys.readouterr().out
    assert "changed" in out.lower()
    assert rel in out


def test_cli_report_lost_watermark_exits_one(tmp_path: Path) -> None:
    sc = _Scenario(tmp_path)
    sc.new_db = _db(tmp_path, "new2.db", {})
    sc.capture()

    assert sc.report() == 1


def test_cli_report_regressed_watermark_exits_one(tmp_path: Path) -> None:
    sc = _Scenario(tmp_path)
    sc.new_db = _db(tmp_path, "new2.db", {("BTCUSDT", "oi"): sc.last_old - timedelta(minutes=5)})
    sc.capture()

    assert sc.report() == 1


def test_cli_usage_error_exits_two(tmp_path: Path) -> None:
    assert cutover.main(["report"]) == 2
    assert cutover.main([]) == 2


def test_cli_unreadable_input_exits_two_without_leaking_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_url = "postgresql+psycopg://trading:SuperSecretPw99@127.0.0.1:1/trading"

    rc = cutover.main(
        ["watermarks", "--database-url", secret_url, "--out", str(tmp_path / "w.json")]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "SuperSecretPw99" not in captured.out + captured.err
    assert "cutover:" in captured.err


# --------------------------------------------------------------------------- #
# OI gap minutes (Task 2)
# --------------------------------------------------------------------------- #

PAIR = ("BTCUSDT", "ETHUSDT")
LAST_OLD = T0 + timedelta(hours=1)  # 11:00
WINDOW_START = LAST_OLD - timedelta(minutes=10)  # minimum old OI tick minus 2 cadences
WINDOW_END = datetime(2026, 10, 1, 11, 46, tzinfo=UTC)


def _gap_setup(tmp_path: Path, *, new_tick: bool = True) -> tuple[Path, Path, dict[str, str]]:
    """Old 10:00-11:00 ticks, new side = copy plus (optionally) a 11:45 tick."""
    old_root = tmp_path / "old_raw"
    new_root = tmp_path / "new_raw"
    _ticks(old_root, PAIR, T0, LAST_OLD)
    shutil.copytree(old_root, new_root)
    if new_tick:
        for symbol in PAIR:
            _tick(new_root, symbol, T0 + timedelta(minutes=105))
    return old_root, new_root, {f"{s}|oi": "2026-10-01T11:00:00Z" for s in PAIR}


def _run_report(
    tmp_path: Path,
    old_root: Path,
    new_root: Path,
    old_wm: dict[str, str],
    new_wm: dict[str, str],
    *extra: str,
) -> int:
    assert (
        cutover.main(["fingerprint", "--raw-root", str(old_root), "--out", str(tmp_path / "fo")])
        == 0
    )
    assert (
        cutover.main(["fingerprint", "--raw-root", str(new_root), "--out", str(tmp_path / "fn")])
        == 0
    )
    _write_json(tmp_path / "wo", old_wm)
    _write_json(tmp_path / "wn", new_wm)
    return cutover.main(
        [
            "report",
            "--old-fingerprint",
            str(tmp_path / "fo"),
            "--new-fingerprint",
            str(tmp_path / "fn"),
            "--old-watermarks",
            str(tmp_path / "wo"),
            "--new-watermarks",
            str(tmp_path / "wn"),
            "--raw-root",
            str(new_root),
            "--window-end",
            "2026-10-01T11:46:00Z",
            *extra,
        ]
    )


def test_oi_gaps_interior_hole_is_45_minutes_for_both_symbols(tmp_path: Path) -> None:
    _, new_root, _ = _gap_setup(tmp_path)

    gaps = cutover.oi_gaps(new_root, PAIR, WINDOW_START, WINDOW_END)

    assert {g.symbol: g.max_gap_minutes for g in gaps} == {"BTCUSDT": 45, "ETHUSDT": 45}
    assert all(len(g.ranges) == 1 for g in gaps)


def test_oi_gaps_trailing_hole_without_new_tick_is_46_minutes(tmp_path: Path) -> None:
    _, new_root, _ = _gap_setup(tmp_path, new_tick=False)

    gaps = cutover.oi_gaps(new_root, ("BTCUSDT",), WINDOW_START, WINDOW_END)

    assert gaps[0].max_gap_minutes == 46


def test_oi_gaps_one_second_jitter_is_not_a_gap(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    at = T0
    while at <= LAST_OLD + timedelta(minutes=45):
        _tick(root, "BTCUSDT", at + timedelta(seconds=1 if (at.minute // 5) % 2 else 0))
        at += timedelta(minutes=5)

    gaps = cutover.oi_gaps(root, ("BTCUSDT",), WINDOW_START, WINDOW_END)

    assert gaps[0].max_gap_minutes == 0
    assert gaps[0].ranges == ()


def test_report_threshold_default_passes_and_30_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old_root, new_root, old_wm = _gap_setup(tmp_path)
    new_wm = {f"{s}|oi": "2026-10-01T11:45:00Z" for s in PAIR}

    assert _run_report(tmp_path, old_root, new_root, old_wm, new_wm) == 0
    assert "45" in capsys.readouterr().out
    assert _run_report(tmp_path, old_root, new_root, old_wm, new_wm, "--max-gap-minutes", "30") == 3


def test_report_trailing_hole_is_reported_not_hidden(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old_root, new_root, old_wm = _gap_setup(tmp_path, new_tick=False)

    rc = _run_report(tmp_path, old_root, new_root, old_wm, dict(old_wm), "--max-gap-minutes", "30")

    assert rc == 3
    assert "46" in capsys.readouterr().out


def test_report_data_loss_outranks_gap(tmp_path: Path) -> None:
    old_root, new_root, old_wm = _gap_setup(tmp_path)
    next(new_root.rglob("*.parquet")).unlink()
    new_wm = {f"{s}|oi": "2026-10-01T11:45:00Z" for s in PAIR}

    assert _run_report(tmp_path, old_root, new_root, old_wm, new_wm, "--max-gap-minutes", "30") == 1


def test_report_text_states_permanent_loss_recoverable_funding_and_human_shutdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old_root, new_root, old_wm = _gap_setup(tmp_path)
    new_wm = {f"{s}|oi": "2026-10-01T11:45:00Z" for s in PAIR}

    assert _run_report(tmp_path, old_root, new_root, old_wm, new_wm) == 0

    text = capsys.readouterr().out
    assert "permanent loss" in text
    assert "recoverable by the funding sweep" in text
    assert "only by a human" in text
    assert "clean report" in text


def test_report_json_out_matches_facts_with_sorted_keys(tmp_path: Path) -> None:
    old_root, new_root, old_wm = _gap_setup(tmp_path)
    new_wm = {f"{s}|oi": "2026-10-01T11:45:00Z" for s in PAIR}
    out = tmp_path / "report.json"

    rc = _run_report(tmp_path, old_root, new_root, old_wm, new_wm, "--json-out", str(out))

    raw = out.read_bytes()
    data = json.loads(raw)
    assert rc == 0 and data["exit_code"] == 0
    assert data["max_gap_minutes_threshold"] == 60
    assert {g["symbol"]: g["max_gap_minutes"] for g in data["oi_gaps"]} == {
        "BTCUSDT": 45,
        "ETHUSDT": 45,
    }
    assert data["files"]["missing"] == [] and b"\r" not in raw
    assert raw == (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()


def test_report_without_oi_watermarks_needs_no_raw_root_and_has_no_gaps(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "e", {})
    rc = cutover.main(
        [
            "report",
            "--old-fingerprint",
            str(tmp_path / "e"),
            "--new-fingerprint",
            str(tmp_path / "e"),
            "--old-watermarks",
            str(tmp_path / "e"),
            "--new-watermarks",
            str(tmp_path / "e"),
        ]
    )
    assert rc == 0


def test_report_window_end_before_window_start_is_a_usage_error(tmp_path: Path) -> None:
    old_root, new_root, old_wm = _gap_setup(tmp_path)
    rc = _run_report(
        tmp_path, old_root, new_root, old_wm, dict(old_wm), "--window-end", "2026-10-01T09:00:00Z"
    )
    assert rc == 2
