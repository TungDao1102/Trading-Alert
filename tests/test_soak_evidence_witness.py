"""Exporter input `--host-witness` (quick task 261114-12e; 16-DEC-HOST-TICK).

The exporter reads the witness objects of one epoch from the evidence remote, by SERVER time
(`rclone lsjson --use-server-modtime`), judges them with the GitHub ticks and writes bundle schema
`soak-evidence-bundle/2`. Every test runs against an injected reader or a fake rclone runner: no
network, no rclone binary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import export_soak_evidence as export
from src.paper.coverage import HostTick
from src.paper.evidence_bundle import load_evidence_bundle

from tests.test_paper_freeze_host_witness import _lsjson_time, host_line_bytes, host_path
from tests.test_soak_evidence_export import (
    CLOCK_AFTER_EVERY_WINDOW,
    CRON,
    E1,
    EVIDENCE_ENV,
    GRACE_SECONDS,
    P1,
    PARAMETER_HASH,
    SECRET_KEY,
    SIX_HOURS,
    Inputs,
    freeze_rows,
    manifest_of,
    pinned_row,
    record_rows,
    sample_records,
    write_inputs,
)

SLOT_3 = P1.replace(minute=17) + timedelta(hours=2)  # the slot of hour 3 (cron minute 17)
TICK = "ab" * 16
WITNESS_ENV = {**EVIDENCE_ENV, "EVIDENCE_S3_WITNESS_PREFIX": "witness"}
WITNESS_BASE = "EVIDENCES3:evidence-bucket/witness"


@pytest.fixture(autouse=True)
def _fixed_export_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export, "_system_now", lambda: CLOCK_AFTER_EVERY_WINDOW)


# --------------------------------------------------------------------------- #
# Fakes and helpers.
# --------------------------------------------------------------------------- #


def _inputs(root: Path) -> Inputs:
    """Six hourly ticks of epoch E1 with the GitHub tick of hour 3 missing (a gap)."""
    diff_lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000, skip_hours={3})
    return write_inputs(
        root,
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=diff_lines,
        runs=runs,
    )


def _host_object(slot: datetime, witnessed_after: timedelta) -> tuple[str, tuple[bytes, datetime]]:
    """(path, (bytes, server ModTime)) of a clean host line for `slot`."""
    data = host_line_bytes(
        slot + timedelta(seconds=40),
        epoch_id=E1,
        pinned_hash=PARAMETER_HASH,
        current_hash=PARAMETER_HASH,
        meta={"schedule": CRON, "source": "host", "tick_id": TICK},
    )
    return host_path(slot, TICK), (data, slot + witnessed_after)


def _argv(inputs: Inputs, out: Path) -> list[str]:
    return [
        *inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out),
        "--host-witness",
    ]


class FakeWitnessReader:
    """A `WitnessReader` over a path -> (bytes, server ModTime) mapping."""

    def __init__(
        self,
        objects: Mapping[str, tuple[bytes, datetime]],
        *,
        change_modtime_on_second_listing: bool = False,
        short_read: bool = False,
    ) -> None:
        self.objects = dict(objects)
        self.change = change_modtime_on_second_listing
        self.short_read = short_read
        self.listings = 0

    def listing(self, epoch_id: str) -> bytes:
        self.listings += 1
        entries: list[dict[str, Any]] = []
        for path, (data, modtime) in sorted(self.objects.items()):
            if self.change and self.listings >= 2:
                modtime += timedelta(seconds=1)
            entries.append(
                {
                    "Path": path,
                    "Name": path,
                    "Size": len(data),
                    "ModTime": _lsjson_time(modtime),
                    "IsDir": False,
                }
            )
        return json.dumps(entries).encode("utf-8")

    def read(self, epoch_id: str, path: str) -> bytes:
        data = self.objects[path][0]
        return data[:-1] if self.short_read else data


class FakeWitnessRclone:
    """A fake rclone runner serving `lsjson` and `cat` of one witness directory."""

    def __init__(
        self,
        objects: Mapping[str, tuple[bytes, datetime]],
        *,
        fail_lsjson: bool = False,
        fail_cat: bool = False,
    ) -> None:
        self.objects = dict(objects)
        self.fail_lsjson = fail_lsjson
        self.fail_cat = fail_cat
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], stdin: bytes | None) -> tuple[int, bytes, bytes]:
        self.calls.append(list(argv))
        target = argv[-1]
        if argv[0] == "lsjson":
            if self.fail_lsjson:
                return 1, b"", b"boom: the remote is unreachable"
            if not self.objects:
                return 3, b"", b"directory not found"
            rows = [
                {"Path": p, "Name": p, "Size": len(d), "ModTime": _lsjson_time(m), "IsDir": False}
                for p, (d, m) in sorted(self.objects.items())
            ]
            return 0, json.dumps(rows).encode("utf-8"), b""
        if argv[0] == "cat":
            if self.fail_cat:
                return 1, b"", b"boom"
            path = target.rsplit("/", 1)[-1]
            return 0, self.objects[path][0], b""
        return 1, b"", b"unknown verb"


def _patched_rclone(
    monkeypatch: pytest.MonkeyPatch, runner: FakeWitnessRclone
) -> list[Mapping[str, str]]:
    seen: list[Mapping[str, str]] = []

    def fake_run(
        argv: Sequence[str], stdin: bytes | None, env: Mapping[str, str]
    ) -> tuple[int, bytes, bytes]:
        seen.append(env)
        return runner(argv, stdin)

    monkeypatch.setattr(export, "_run_rclone", fake_run)
    return seen


def _gaps(out: Path) -> list[str]:
    return [line for line in (out / "evidence_gaps.jsonl").read_text().splitlines() if line]


# --------------------------------------------------------------------------- #
# Test 1 (export tracer) and Tests 2, 3.
# --------------------------------------------------------------------------- #


def test_tracer_export_with_a_witnessed_host_tick_fills_the_gap_and_writes_schema_2(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    path, obj = _host_object(SLOT_3, timedelta(seconds=50))
    reader = FakeWitnessReader({path: obj})

    code = export.main(_argv(inputs, out), witness=reader)

    assert code == export.EXIT_OK
    manifest = manifest_of(out)
    assert manifest["schema"] == "soak-evidence-bundle/2"
    assert "host_witness_listing.json" in manifest["files"]
    assert "host_ticks.jsonl" in manifest["files"]
    assert manifest["host_witness"]["object_count"] == 1
    assert (out / "host_witness_listing.json").read_bytes() == reader.listing(E1)
    assert _gaps(out) == []
    bundle = load_evidence_bundle(out)
    assert len(bundle.host_ticks) == 1
    assert isinstance(bundle.host_ticks[0], HostTick)
    assert bundle.host_ticks[0].path == path


def test_without_host_witness_the_bundle_stays_schema_1_with_the_gap(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out)

    assert export.main(argv) == export.EXIT_OK

    manifest = manifest_of(out)
    assert manifest["schema"] == "soak-evidence-bundle/1"
    assert "host_witness" not in manifest
    assert not (out / "host_witness_listing.json").exists()
    assert not (out / "host_ticks.jsonl").exists()
    assert len(_gaps(out)) == 1


def test_a_witness_beyond_the_grace_leaves_the_gap(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    path, obj = _host_object(SLOT_3, timedelta(seconds=GRACE_SECONDS + 1))

    code = export.main(_argv(inputs, out), witness=FakeWitnessReader({path: obj}))

    assert code == export.EXIT_OK
    assert len(_gaps(out)) == 1


# --------------------------------------------------------------------------- #
# Test 4: every inconsistent or unreachable witness refuses the export.
# --------------------------------------------------------------------------- #


def _assert_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], run: Any, *, environ: Any = None
) -> None:
    inputs = _inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    code = run(_argv(inputs, out), environ)
    captured = capsys.readouterr()
    assert code == export.EXIT_INPUT
    assert not out.exists(), "nothing is written"
    text = captured.out + captured.err
    assert SECRET_KEY not in text
    assert "evidence-bucket" not in text


def test_an_unreachable_witness_remote_exits_2_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patched_rclone(monkeypatch, FakeWitnessRclone({}, fail_lsjson=True))
    _assert_refused(
        tmp_path, capsys, lambda argv, environ: export.main(argv, environ=dict(WITNESS_ENV))
    )


def test_a_listing_that_changes_between_the_two_reads_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, obj = _host_object(SLOT_3, timedelta(seconds=50))
    reader = FakeWitnessReader({path: obj}, change_modtime_on_second_listing=True)
    _assert_refused(tmp_path, capsys, lambda argv, environ: export.main(argv, witness=reader))
    assert reader.listings == 2


def test_an_object_whose_byte_count_differs_from_the_listing_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, obj = _host_object(SLOT_3, timedelta(seconds=50))
    reader = FakeWitnessReader({path: obj}, short_read=True)
    _assert_refused(tmp_path, capsys, lambda argv, environ: export.main(argv, witness=reader))


def test_a_failed_read_of_a_witness_object_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, obj = _host_object(SLOT_3, timedelta(seconds=50))
    _patched_rclone(monkeypatch, FakeWitnessRclone({path: obj}, fail_cat=True))
    _assert_refused(
        tmp_path, capsys, lambda argv, environ: export.main(argv, environ=dict(WITNESS_ENV))
    )


# --------------------------------------------------------------------------- #
# Test 5: an epoch directory that does not exist.
# --------------------------------------------------------------------------- #


def test_an_absent_witness_directory_gives_an_empty_witness_and_the_github_only_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "in")
    runner = FakeWitnessRclone({})  # lsjson answers exit 3: the directory does not exist
    _patched_rclone(monkeypatch, runner)
    out = tmp_path / "with-witness"
    plain = tmp_path / "plain"

    assert export.main(_argv(inputs, out), environ=dict(WITNESS_ENV)) == export.EXIT_OK
    argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=plain)
    assert export.main(argv) == export.EXIT_OK

    manifest = manifest_of(out)
    assert manifest["schema"] == "soak-evidence-bundle/2"
    assert manifest["host_witness"]["object_count"] == 0
    assert (out / "host_witness_listing.json").read_bytes() == b"[]"
    assert (out / "evidence_gaps.jsonl").read_bytes() == (
        plain / "evidence_gaps.jsonl"
    ).read_bytes()
    assert load_evidence_bundle(out).host_ticks == ()


# --------------------------------------------------------------------------- #
# Test 6: the rclone argv and the environment.
# --------------------------------------------------------------------------- #


def test_the_rclone_witness_reader_lists_by_server_time_and_reads_by_path() -> None:
    path, obj = _host_object(SLOT_3, timedelta(seconds=50))
    runner = FakeWitnessRclone({path: obj})
    reader = export.RcloneWitnessReader(WITNESS_BASE, runner=runner)

    listing = reader.listing(E1)
    data = reader.read(E1, path)

    assert json.loads(listing)[0]["Path"] == path
    assert data == obj[0]
    assert runner.calls[0] == [
        "lsjson",
        "--use-server-modtime",
        "--files-only",
        "--recursive",
        "--no-mimetype",
        f"{WITNESS_BASE}/{E1}/",
    ]
    assert runner.calls[1] == ["cat", f"{WITNESS_BASE}/{E1}/{path}"]
    assert not any(SECRET_KEY in " ".join(call) for call in runner.calls)


def test_witness_credentials_reach_rclone_only_in_the_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, obj = _host_object(SLOT_3, timedelta(seconds=50))
    runner = FakeWitnessRclone({path: obj})
    seen = _patched_rclone(monkeypatch, runner)
    inputs = _inputs(tmp_path / "in")
    out = tmp_path / "bundle"

    code = export.main(_argv(inputs, out), environ=dict(WITNESS_ENV))

    captured = capsys.readouterr()
    assert code == export.EXIT_OK, captured
    assert runner.calls
    for argv in runner.calls:
        text = " ".join(argv)
        assert SECRET_KEY not in text
        assert f"{WITNESS_BASE}/{E1}/" in text
        if argv[0] == "lsjson":
            assert "--use-server-modtime" in argv
    for env in seen:
        assert env["RCLONE_CONFIG_EVIDENCES3_SECRET_ACCESS_KEY"] == SECRET_KEY
        assert env["RCLONE_CONFIG_EVIDENCES3_TYPE"] == "s3"
    assert SECRET_KEY not in captured.out + captured.err
    assert "host witness: 1 object(s) read" in captured.out


# --------------------------------------------------------------------------- #
# Test 7: the witness prefix name.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value",
    [
        None,  # unset
        "",
        "paper",  # equal to EVIDENCE_S3_PREFIX
        "paper/witness",  # inside it
        "/",  # an empty segment
        "two words",
        "a/../b",
        "token-in-the-prefix",
    ],
)
def test_a_missing_overlapping_or_unsafe_witness_prefix_exits_2_before_any_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str | None
) -> None:
    environ = dict(EVIDENCE_ENV)
    if value is not None:
        environ["EVIDENCE_S3_WITNESS_PREFIX"] = value
    inputs = _inputs(tmp_path / "in")
    out = tmp_path / "bundle"

    code = export.main(_argv(inputs, out), environ=environ)

    captured = capsys.readouterr()
    assert code == export.EXIT_INPUT
    assert "EVIDENCE_S3_WITNESS_PREFIX" in captured.err
    if value and len(value) > 3:
        assert value not in captured.out + captured.err
    assert SECRET_KEY not in captured.out + captured.err
    assert not out.exists()


def test_a_witness_prefix_that_contains_the_evidence_prefix_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    environ = {
        **EVIDENCE_ENV,
        "EVIDENCE_S3_PREFIX": "paper/soak",
        "EVIDENCE_S3_WITNESS_PREFIX": "paper",
    }
    inputs = _inputs(tmp_path / "in")

    code = export.main(_argv(inputs, tmp_path / "bundle"), environ=environ)

    assert code == export.EXIT_INPUT
    assert "EVIDENCE_S3_WITNESS_PREFIX" in capsys.readouterr().err
