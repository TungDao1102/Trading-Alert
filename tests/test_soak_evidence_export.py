"""Soak evidence export (Phase 16, plan 16-30; D-22, L-01, REV-02, REV-18, T-16-68 to T-16-70).

`scripts/export_soak_evidence.py` writes one `soak-evidence-bundle/1` directory per epoch that
`load_evidence_bundle` (plan 16-25) accepts. Every test builds its inputs here from fakes: no
network, no Binance, no Telegram. The PostgreSQL test reaches the database only through
`TEST_DATABASE_URL` (the `pg_db` fixture) and skips without it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate_trial_soak as evaluate
from scripts import export_soak_evidence as export
from sqlalchemy.engine import Engine
from src.adapters.analytics_files import load_evidence_file
from src.analytics.lifecycle import exclude_test_only
from src.paper.coverage import freeze_evidence_report, parse_freeze_log, parse_github_runs
from src.paper.evidence_bundle import (
    BUNDLE_SCHEMA,
    FILE_ANALYTICS,
    FILE_DIFF,
    FILE_GAPS,
    FILE_MISSING_TICKS,
    FILE_PINNED,
    FILE_RECORDS,
    FILE_RUNS,
    REQUIRED_FILES,
    EvidenceBundle,
    load_evidence_bundle,
    runtime_record_line,
)
from src.paper.runtime_state import (
    InMemoryRuntimeState,
    RuntimeRecord,
    runtime_event_id,
)
from src.paper.vocabulary import RuntimeEventType
from src.persistence.engine import make_sync_engine
from src.persistence.paper_runtime_state import PgRuntimeState
from src.persistence.uow import OperationalDatabase

from tests.test_paper_exit_evaluator import QD_DECISION, RATIFIED_CONFIG, _workflow
from tests.test_paper_replay_inputs import World, with_digest
from tests.test_paper_shadow_evidence_export import _backtest_part, _shadow_rows

CRON = "17 * * * *"
E1 = "a" * 64
E2 = "b" * 64
PARAMETER_HASH = "c" * 64
P1 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
SIX_HOURS = timedelta(hours=6)
GRACE_SECONDS = 300  # freeze_tick_grace_seconds of the ratified test configuration
SYMBOL = "BTCUSDT"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")


# --------------------------------------------------------------------------- #
# Fake sessions.
# --------------------------------------------------------------------------- #


def sample_records(epoch_id: str, at: datetime) -> list[RuntimeRecord]:
    """One record of every RuntimeEventType (PAPER_REPLAY_INPUTS and PAPER_HISTORY_BARS too)."""
    keyed = (
        RuntimeEventType.PAPER_BAR_PROCESSED,
        RuntimeEventType.PAPER_REPLAY_INPUTS,
        RuntimeEventType.PAPER_GAP,
    )
    out: list[RuntimeRecord] = []
    for index, event_type in enumerate(RuntimeEventType):
        when = at + timedelta(seconds=index, milliseconds=500)
        payloads: dict[RuntimeEventType, dict[str, Any]] = {
            RuntimeEventType.PAPER_GAP: {"expected_close_utc": when, "reason": "CRASH"},
            RuntimeEventType.PAPER_TICK_STATS: {"batch_seq": 3, "dropped_by_reason": {}},
            RuntimeEventType.PAPER_HISTORY_BARS: {
                "history_seq": 2,
                "entries": [{"accept_seq": 0, "window_digest": "d" * 64}],
            },
            RuntimeEventType.PAPER_REPLAY_INPUTS: {
                "schema": "paper-replay-inputs/1",
                "ttl_seconds": 5,
                "context_digest": "e" * 64,
            },
        }
        out.append(
            RuntimeRecord(
                event_type=event_type,
                epoch_id=epoch_id,
                occurred_at_utc=when,
                symbol=SYMBOL if event_type in keyed else None,
                interval="1h" if event_type in keyed else None,
                payload=payloads.get(event_type, {"note": "cafe"}),
            )
        )
    return out


def freeze_rows(
    epoch_id: str,
    pin: datetime,
    *,
    hours: int,
    first_run_id: int,
    skip_hours: Collection[int] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Clean freeze lines and the matching schedule runs; `skip_hours` omit a tick (a gap)."""
    diff_lines: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    slot = pin.replace(minute=17, second=0, microsecond=0)
    if slot <= pin:
        slot += timedelta(hours=1)
    run_id = first_run_id
    hour = 1
    while slot <= pin + timedelta(hours=hours):
        run_id += 1
        if hour not in skip_hours:
            created = slot + timedelta(seconds=20)
            runs.append(
                {
                    "id": run_id,
                    "event": "schedule",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": _iso(created),
                    "run_started_at": _iso(created),
                    "run_attempt": 1,
                    "head_sha": "f" * 40,
                }
            )
            diff_lines.append(
                {
                    "checked_at_utc": _iso(created + timedelta(seconds=30)),
                    "epoch_id": epoch_id,
                    "pinned_hash": PARAMETER_HASH,
                    "current_hash": PARAMETER_HASH,
                    "outcome": "clean",
                    "run_metadata": {
                        "run_id": str(run_id),
                        "run_attempt": "1",
                        "event_name": "schedule",
                        "schedule": CRON,
                        "commit": "f" * 40,
                    },
                }
            )
        slot += timedelta(hours=1)
        hour += 1
    return diff_lines, runs


def pinned_row(epoch_id: str, pin: datetime) -> dict[str, Any]:
    return {
        "epoch_id": epoch_id,
        "strategy_id": "trend-pullback",
        "parameter_set_id": "test-set-v1",
        "parameter_set_hash": PARAMETER_HASH,
        "opened_at_utc": _iso(pin),
        "evidence_claim_open": True,
    }


def record_rows(records: Sequence[RuntimeRecord]) -> list[dict[str, Any]]:
    return [json.loads(runtime_record_line(r)) for r in records]


@dataclass
class Inputs:
    """The input files of one export, written once; the exporter must never touch them."""

    root: Path
    records: Path
    pinned: list[Path]
    diff: Path
    runs: Path
    config: Path
    workflow: Path
    analytics: Path | None = None
    paths: list[Path] = field(default_factory=list)

    def snapshot(self) -> dict[Path, bytes]:
        every = [self.records, *self.pinned, self.diff, self.runs, self.config, self.workflow]
        if self.analytics is not None:
            every.append(self.analytics)
        return {path: path.read_bytes() for path in every}

    def argv(
        self,
        *,
        source: str,
        epoch: str,
        start: datetime,
        end: datetime,
        out: Path,
        with_records: bool = True,
        as_of: datetime | None = None,
        omit_as_of: bool = False,
        diff_logs: Sequence[Path] | None = None,
    ) -> list[str]:
        """The export arguments. Unless `omit_as_of`, `--as-of` is given: `as_of`, or by default
        the end of the window plus the ratified freeze-tick grace (a final bundle)."""
        argv = ["--source", source]
        if with_records:
            argv += ["--records", str(self.records)]
        for pinned in self.pinned:
            argv += ["--pinned", str(pinned)]
        for diff in [self.diff] if diff_logs is None else diff_logs:
            argv += ["--diff-log", str(diff)]
        argv += [
            "--github-runs",
            str(self.runs),
            "--config",
            str(self.config),
            "--workflow",
            str(self.workflow),
            "--epoch",
            epoch,
            "--window-start",
            _iso(start),
            "--window-end",
            _iso(end),
            "--out",
            str(out),
        ]
        if not omit_as_of:
            moment = end + timedelta(seconds=GRACE_SECONDS) if as_of is None else as_of
            argv += ["--as-of", _iso(moment)]
        if self.analytics is not None:
            argv += ["--analytics-inputs", str(self.analytics)]
        return argv


def write_inputs(
    root: Path,
    *,
    records: Sequence[Mapping[str, Any]],
    pinned: Sequence[Mapping[str, Any]],
    diff_lines: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
) -> Inputs:
    root.mkdir(parents=True, exist_ok=True)
    records_path = root / "runtime_records_input.jsonl"
    records_path.write_bytes(_jsonl(records))
    pinned_paths: list[Path] = []
    for index, row in enumerate(pinned):
        path = root / f"pinned_{index}.json"
        path.write_text(json.dumps(row, sort_keys=True, indent=2), encoding="utf-8")
        pinned_paths.append(path)
    diff_path = root / "diff_input.jsonl"
    diff_path.write_bytes(_jsonl(diff_lines))
    runs_path = root / "runs_input.json"
    runs_path.write_text(json.dumps({"workflow_runs": list(runs)}), encoding="utf-8")
    config = root / "paper-runtime.toml"
    config.write_text(RATIFIED_CONFIG, encoding="utf-8")
    return Inputs(
        root=root,
        records=records_path,
        pinned=pinned_paths,
        diff=diff_path,
        runs=runs_path,
        config=config,
        workflow=_workflow(root),
    )


def one_epoch_inputs(root: Path, **kwargs: Any) -> Inputs:
    diff_lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000)
    return write_inputs(
        root,
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=diff_lines,
        runs=runs,
        **kwargs,
    )


def shadow_document(epoch_id: str) -> dict[str, Any]:
    """The analytics inputs file: real and `test_only` SHADOW rows plus the backtest part."""
    rows = [
        dataclasses.replace(row, epoch_id=epoch_id)
        for row in [*_shadow_rows(), *_shadow_rows(test_only=True, tag="-T")]
    ]
    backtest, universe = _backtest_part()
    return {
        "rows": [
            {
                "epoch_id": row.epoch_id,
                "signal": dict(row.signal),
                "trade_plan": dict(row.trade_plan),
                "approval": None if row.approval is None else dict(row.approval),
                "order": None if row.order is None else dict(row.order),
                "fill": None if row.fill is None else dict(row.fill),
                "confirm": None if row.confirm is None else dict(row.confirm),
                "test_only": row.test_only,
                "shadow_outcome": dataclasses.asdict(row.shadow_outcome),
            }
            for row in rows
        ],
        "backtest": backtest,
        "research_universe": universe,
    }


def manifest_of(directory: Path) -> dict[str, Any]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)
    return manifest


def directory_bytes(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def _artifact_names(manifest: Mapping[str, Any]) -> set[str]:
    """The names of the original freeze artifacts a bundle keeps next to the derived log."""
    return {name for name in manifest["files"] if name.startswith("freeze_artifact_")}


def _prefix(directory: Path, epoch: str = E1) -> str:
    """The create-only key prefix of a bundle: `<epoch>/<as_of>-<sha12 of the manifest>`."""
    manifest_bytes = (directory / "manifest.json").read_bytes()
    as_of = datetime.fromisoformat(json.loads(manifest_bytes)["as_of_utc"]).astimezone(UTC)
    return f"{epoch}/{as_of.strftime('%Y%m%dT%H%M%SZ')}-{_sha(manifest_bytes)[:12]}"


class RecordingPort(InMemoryRuntimeState):
    """An in-memory port that remembers how `records` was asked."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, Collection[RuntimeEventType] | None]] = []

    def records(
        self, epoch_id: str, event_types: Collection[RuntimeEventType] | None = None
    ) -> Sequence[RuntimeRecord]:
        self.calls.append((epoch_id, event_types))
        return super().records(epoch_id, event_types)


# --------------------------------------------------------------------------- #
# Test 1: the tracer.
# --------------------------------------------------------------------------- #


def test_tracer_a_fixture_session_exports_to_a_bundle_the_evaluator_accepts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    inputs.analytics = tmp_path / "in" / "analytics_inputs.json"
    inputs.analytics.write_text(json.dumps(shadow_document(E1)), encoding="utf-8")
    out = tmp_path / "bundle"

    code = export.main(
        inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out)
    )

    assert code == export.EXIT_OK, capsys.readouterr()
    bundle = load_evidence_bundle(out)
    manifest = manifest_of(out)
    assert manifest["schema"] == BUNDLE_SCHEMA
    assert manifest["source"] == "fixture" == bundle.source
    assert manifest["epoch_id"] == E1
    assert set(manifest["files"]) - _artifact_names(manifest) == {
        *REQUIRED_FILES,
        FILE_MISSING_TICKS,
        FILE_ANALYTICS,
    }
    for name, digest in manifest["files"].items():
        assert _sha((out / name).read_bytes()) == digest

    originals = sample_records(E1, P1)
    assert {r.event_type for r in bundle.records} == set(RuntimeEventType)
    assert {RuntimeEventType.PAPER_REPLAY_INPUTS, RuntimeEventType.PAPER_HISTORY_BARS} <= {
        r.event_type for r in bundle.records
    }
    assert sorted(r.payload_json for r in bundle.records) == sorted(
        r.payload_json for r in originals
    )

    # The SHADOW analytics file: test_only rows are kept with their flag and counted by the
    # existing normalizer, never silently dropped by the exporter.
    evidence = load_evidence_file(out / FILE_ANALYTICS)
    kept, dropped = exclude_test_only(evidence.paper)
    assert dropped == 7
    assert len(kept) == 7
    assert bundle.analytics is not None
    assert bundle.analytics["schema"] == "analytics-evidence/2"


def test_without_analytics_inputs_the_bundle_has_no_analytics_file(tmp_path: Path) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    assert (
        export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
        == export.EXIT_OK
    )
    assert FILE_ANALYTICS not in manifest_of(out)["files"]
    assert not (out / FILE_ANALYTICS).exists()
    assert load_evidence_bundle(out).analytics is None


# --------------------------------------------------------------------------- #
# Test 2: the source decides the proof class.
# --------------------------------------------------------------------------- #


def test_the_pg_source_reads_every_record_through_the_port_and_writes_source_pg(
    tmp_path: Path,
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    port = RecordingPort()
    originals = sample_records(E1, P1)
    for record in originals:
        port.record(record)
    out = tmp_path / "bundle"

    code = export.main(
        inputs.argv(
            source="pg", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out, with_records=False
        ),
        state=port,
    )

    assert code == export.EXIT_OK
    assert manifest_of(out)["source"] == "pg"
    assert port.calls == [(E1, None)], "no event-type filter: every RuntimeEventType is exported"
    bundle = load_evidence_bundle(out)
    assert {r.event_type for r in bundle.records} == set(RuntimeEventType)
    assert sorted(runtime_event_id(r) for r in bundle.records) == sorted(
        runtime_event_id(r) for r in originals
    )
    assert sorted(r.payload_json for r in bundle.records) == sorted(
        r.payload_json for r in originals
    )


def test_no_argument_flag_or_variable_turns_a_fixture_source_into_a_pg_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    port = RecordingPort()
    for record in sample_records(E1, P1):
        port.record(record)
    for name in ("SOAK_SOURCE", "PAPER_SOURCE", "EVIDENCE_SOURCE", "SOURCE"):
        monkeypatch.setenv(name, "pg")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:pw-not-used@127.0.0.1:1/none")

    out = tmp_path / "fixture-bundle"
    code = export.main(
        inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out)
    )
    assert code == export.EXIT_OK
    assert manifest_of(out)["source"] == "fixture"

    # A state port cannot back a fixture bundle, and a records file cannot back a pg bundle.
    refused = tmp_path / "refused-fixture"
    assert (
        export.main(
            inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=refused),
            state=port,
        )
        == export.EXIT_INPUT
    )
    assert not refused.exists()
    refused_pg = tmp_path / "refused-pg"
    assert (
        export.main(
            inputs.argv(source="pg", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=refused_pg),
            state=port,
        )
        == export.EXIT_INPUT
    )
    assert not refused_pg.exists()

    # An unknown source name is refused by the parser; the script has no third value.
    with pytest.raises(SystemExit):
        export.main(
            inputs.argv(source="soak", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=tmp_path / "x")
        )
    capsys.readouterr()


def test_the_pg_source_without_a_database_url_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    code = export.main(
        inputs.argv(
            source="pg", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out, with_records=False
        ),
        environ={},
    )
    assert code == export.EXIT_INPUT
    assert not out.exists()
    assert "DATABASE_URL" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Test 3: EVIDENCE_GAP records live in their own file.
# --------------------------------------------------------------------------- #


def test_evidence_gap_records_go_to_their_own_file_and_no_input_is_touched(
    tmp_path: Path,
) -> None:
    diff_lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000, skip_hours={3})
    inputs = write_inputs(
        tmp_path / "in",
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=diff_lines,
        runs=runs,
    )
    before = inputs.snapshot()
    out = tmp_path / "bundle"

    assert (
        export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
        == export.EXIT_OK
    )

    bundle = load_evidence_bundle(out)
    expected = freeze_evidence_report(
        pin_utc=P1,
        window_end_utc=P1 + SIX_HOURS,
        cron=CRON,
        lines=parse_freeze_log(inputs.diff.read_text(encoding="utf-8")),
        runs=parse_github_runs(inputs.runs.read_text(encoding="utf-8")),
        grace_seconds=300,
        detected_at_utc=P1 + SIX_HOURS + timedelta(seconds=GRACE_SECONDS),
    ).gaps
    assert len(expected) == 1
    assert bundle.evidence_gaps == expected
    assert bundle.evidence_gaps[0].reason.value == "NO_RUN_FOUND"
    gap_lines = (out / FILE_GAPS).read_text(encoding="utf-8").splitlines()
    assert len(gap_lines) == 1
    assert set(json.loads(gap_lines[0])) == {
        "slot_utc",
        "schedule",
        "reason",
        "detected_at_utc",
        "run_id",
    }

    # registry_diff.jsonl is the input, byte for byte: nothing about the gap is written into it.
    assert (out / FILE_DIFF).read_bytes() == inputs.diff.read_bytes()
    assert b"EVIDENCE_GAP" not in (out / FILE_DIFF).read_bytes()
    assert (out / FILE_RUNS).read_bytes() == inputs.runs.read_bytes()
    assert (out / FILE_PINNED).read_bytes() == inputs.pinned[0].read_bytes()
    assert inputs.snapshot() == before


def test_a_session_without_gaps_writes_an_empty_gap_file(tmp_path: Path) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
    assert (out / FILE_GAPS).read_bytes() == b""
    assert load_evidence_bundle(out).evidence_gaps == ()


# --------------------------------------------------------------------------- #
# As-of exports (plan 16-59, B2-WR-06): only a slot that is already due can be a gap.
# --------------------------------------------------------------------------- #

FOURTEEN_DAYS = timedelta(days=14)


def _empty_freeze_inputs(root: Path) -> Inputs:
    """A fixed 14-day trial with no freeze line and no run yet."""
    return write_inputs(
        root,
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=[],
        runs=[],
    )


def _export(argv: list[str]) -> int:
    """`export.main` with an argparse refusal reported as its exit code (never a crash)."""
    try:
        return export.main(argv)
    except SystemExit as stop:
        return -1 if not isinstance(stop.code, int) else stop.code


def _gap_slots(directory: Path) -> list[str]:
    rows = [json.loads(r) for r in (directory / FILE_GAPS).read_text(encoding="utf-8").splitlines()]
    return [row["slot_utc"] for row in rows]


def test_an_export_three_hours_into_a_14_day_trial_records_only_the_slots_already_due(
    tmp_path: Path,
) -> None:
    inputs = _empty_freeze_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    as_of = P1 + timedelta(hours=3)

    code = _export(
        inputs.argv(
            source="fixture", epoch=E1, start=P1, end=P1 + FOURTEEN_DAYS, out=out, as_of=as_of
        )
    )

    assert code == export.EXIT_OK
    slots = _gap_slots(out)
    # 00:17, 01:17 and 02:17 are due (slot + 300 s <= 03:00); 03:17 and every later slot are not.
    assert slots == [_iso(P1 + timedelta(hours=h, minutes=17)) for h in (0, 1, 2)]
    for line in (out / FILE_GAPS).read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["detected_at_utc"] == _iso(as_of)
        assert json.loads(line)["reason"] == "NO_RUN_FOUND"
    assert manifest_of(out)["as_of_utc"] == _iso(as_of)
    assert load_evidence_bundle(out).as_of_utc == as_of


def test_a_slot_is_due_exactly_when_the_grace_after_it_has_passed(tmp_path: Path) -> None:
    inputs = _empty_freeze_inputs(tmp_path / "in")
    due = P1 + timedelta(hours=2, minutes=17, seconds=GRACE_SECONDS)
    at_boundary = tmp_path / "at-boundary"
    just_before = tmp_path / "just-before"

    for out, moment in ((at_boundary, due), (just_before, due - timedelta(seconds=1))):
        argv = inputs.argv(
            source="fixture", epoch=E1, start=P1, end=P1 + FOURTEEN_DAYS, out=out, as_of=moment
        )
        assert _export(argv) == export.EXIT_OK

    assert _iso(P1 + timedelta(hours=2, minutes=17)) in _gap_slots(at_boundary)
    assert _iso(P1 + timedelta(hours=2, minutes=17)) not in _gap_slots(just_before)


def test_the_due_bound_follows_the_ratified_grace_and_no_number_of_its_own(
    tmp_path: Path,
) -> None:
    inputs = _empty_freeze_inputs(tmp_path / "in")
    text = inputs.config.read_text(encoding="utf-8")
    assert "freeze_tick_grace_seconds = 300" in text
    inputs.config.write_text(
        text.replace("freeze_tick_grace_seconds = 300", "freeze_tick_grace_seconds = 120"),
        encoding="utf-8",
    )
    out = tmp_path / "bundle"
    # 02:19 is 120 s after the 02:17 slot: due under a 120 s grace, not under 300 s.
    as_of = P1 + timedelta(hours=2, minutes=19)

    code = _export(
        inputs.argv(
            source="fixture", epoch=E1, start=P1, end=P1 + FOURTEEN_DAYS, out=out, as_of=as_of
        )
    )

    assert code == export.EXIT_OK
    assert _iso(P1 + timedelta(hours=2, minutes=17)) in _gap_slots(out)


def test_an_as_of_before_the_pin_or_after_the_window_end_plus_grace_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = _empty_freeze_inputs(tmp_path / "in")
    end = P1 + FOURTEEN_DAYS
    for name, moment in (
        ("before-pin", P1 - timedelta(seconds=1)),
        ("after-end", end + timedelta(seconds=GRACE_SECONDS + 1)),
    ):
        out = tmp_path / name
        code = _export(
            inputs.argv(source="fixture", epoch=E1, start=P1, end=end, out=out, as_of=moment)
        )
        assert code == export.EXIT_INPUT, name
        assert not out.exists(), name
        err = capsys.readouterr().err
        assert "cannot export" in err and "--as-of" in err
    not_utc = tmp_path / "naive"
    argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=end, out=not_utc)
    argv[argv.index("--as-of") + 1] = "2026-11-01T03:00:00"
    assert _export(argv) == export.EXIT_INPUT
    assert not not_utc.exists()


def test_without_an_as_of_the_injected_now_bounds_the_export(tmp_path: Path) -> None:
    inputs = _empty_freeze_inputs(tmp_path / "in")
    end = P1 + FOURTEEN_DAYS
    early = tmp_path / "early"
    late = tmp_path / "late"
    now = P1 + timedelta(hours=3)

    assert (
        export.main(
            inputs.argv(source="fixture", epoch=E1, start=P1, end=end, out=early, omit_as_of=True),
            now=lambda: now,
        )
        == export.EXIT_OK
    )
    assert manifest_of(early)["as_of_utc"] == _iso(now)
    assert len(_gap_slots(early)) == 3

    # A final export made long after the window is judged as of window end plus grace.
    assert (
        export.main(
            inputs.argv(source="fixture", epoch=E1, start=P1, end=end, out=late, omit_as_of=True),
            now=lambda: end + timedelta(days=3),
        )
        == export.EXIT_OK
    )
    assert manifest_of(late)["as_of_utc"] == _iso(end + timedelta(seconds=GRACE_SECONDS))
    assert len(_gap_slots(late)) == 336


def test_the_hour_three_export_and_the_final_export_differ_only_in_what_is_due(
    tmp_path: Path,
) -> None:
    """Slots after the as-of time are neither satisfied nor gaps; the data stays in the bundle."""
    diff_lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000)
    inputs = write_inputs(
        tmp_path / "in",
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=diff_lines,
        runs=runs,
    )
    out = tmp_path / "bundle"
    assert (
        _export(
            inputs.argv(
                source="fixture",
                epoch=E1,
                start=P1,
                end=P1 + SIX_HOURS,
                out=out,
                as_of=P1 + timedelta(hours=3),
            )
        )
        == export.EXIT_OK
    )
    assert _gap_slots(out) == []
    assert (out / FILE_DIFF).read_bytes() == inputs.diff.read_bytes()


# --------------------------------------------------------------------------- #
# Merged freeze log and missing ticks (plan 16-59, B2-WR-05; 16-59 Q2 = B, correction 3).
# --------------------------------------------------------------------------- #


def _artifact(root: Path, name: str, lines: Sequence[Mapping[str, Any]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(_jsonl(lines))
    return path


@dataclass
class MergeWorld:
    inputs: Inputs
    lines: list[dict[str, Any]]  # the six clean lines of runs 1001 to 1006
    runs: list[dict[str, Any]]
    first: Path  # runs 1001 to 1003
    second: Path  # runs 1001, 1002 and 1004 (run 1003 was lost by an overlap)
    third: Path  # runs 1004 to 1006


def _merge_world(tmp_path: Path) -> MergeWorld:
    lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000)
    inputs = write_inputs(
        tmp_path / "in",
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=lines,
        runs=runs,
    )
    root = tmp_path / "artifacts"
    return MergeWorld(
        inputs=inputs,
        lines=lines,
        runs=runs,
        first=_artifact(root, "x.jsonl", lines[0:3]),
        second=_artifact(root, "y.jsonl", [*lines[0:2], lines[3]]),
        third=_artifact(root, "z.jsonl", lines[3:6]),
    )


def _merged_argv(world: MergeWorld, out: Path, artifacts: Sequence[Path]) -> list[str]:
    return world.inputs.argv(
        source="fixture",
        epoch=E1,
        start=P1,
        end=P1 + SIX_HOURS,
        out=out,
        diff_logs=artifacts,
    )


def test_the_exporter_merges_every_run_artifact_into_one_derived_log_with_provenance(
    tmp_path: Path,
) -> None:
    world = _merge_world(tmp_path)
    out = tmp_path / "bundle"
    artifacts = [world.first, world.second, world.third]

    assert export.main(_merged_argv(world, out, artifacts)) == export.EXIT_OK

    # Every line of every artifact is there once, in time order: the lost line of run 1003 too.
    assert (out / FILE_DIFF).read_bytes() == _jsonl(world.lines)
    bundle = load_evidence_bundle(out)
    assert len(bundle.freeze_lines) == 6
    assert bundle.evidence_gaps == ()
    manifest = manifest_of(out)
    log = manifest["freeze_log"]
    assert log["derived"] is True and log["file"] == FILE_DIFF
    assert "not a byte copy of one artifact" in log["merge"]
    by_sha = {entry["sha256"]: entry for entry in log["inputs"]}
    assert [entry["sha256"] for entry in log["inputs"]] == sorted(by_sha), "listed in sha256 order"
    expected_runs = {
        world.first: ["1001", "1002", "1003"],
        world.second: ["1001", "1002", "1004"],
        world.third: ["1004", "1005", "1006"],
    }
    for path, run_ids in expected_runs.items():
        data = path.read_bytes()
        entry = by_sha[_sha(data)]
        assert entry["run_ids"] == run_ids
        assert entry["file"] == f"freeze_artifact_{_sha(data)[:16]}.jsonl"
        assert (out / entry["file"]).read_bytes() == data, "the original is kept byte for byte"
        assert manifest["files"][entry["file"]] == _sha(data)
    assert _artifact_names(manifest) == {entry["file"] for entry in log["inputs"]}


def test_the_derived_log_does_not_depend_on_the_order_of_the_artifacts(tmp_path: Path) -> None:
    world = _merge_world(tmp_path)
    orders = {
        "a": [world.first, world.second, world.third],
        "b": [world.third, world.first, world.second],
        "c": [world.second, world.third, world.first, world.first],  # one given twice
    }
    for name, artifacts in orders.items():
        assert export.main(_merged_argv(world, tmp_path / name, artifacts)) == export.EXIT_OK
    assert directory_bytes(tmp_path / "a") == directory_bytes(tmp_path / "b")
    assert directory_bytes(tmp_path / "a") == directory_bytes(tmp_path / "c")


def test_overlapping_runs_lose_a_line_in_the_newest_artifact_and_the_merge_recovers_it(
    tmp_path: Path,
) -> None:
    """B2-WR-05 model: the restore-keys cache hands the next run the newest cache only."""
    world = _merge_world(tmp_path)
    caches: list[tuple[str, list[dict[str, Any]]]] = [("paper-freeze-0", world.lines[0:2])]

    def restore() -> list[dict[str, Any]]:
        newest = [c for c in caches if c[0].startswith("paper-freeze-")][-1]
        return list(newest[1])

    run_a = [*restore(), world.lines[2]]  # runs 1003 and 1004 overlap: same state restored
    run_b = [*restore(), world.lines[3]]
    caches += [("paper-freeze-1003", run_a), ("paper-freeze-1004", run_b)]
    run_c = [*restore(), world.lines[4]]
    assert world.lines[2] not in run_c, "the newest artifact alone has lost the line of run 1003"

    root = tmp_path / "model"
    artifacts = [
        _artifact(root, "a.jsonl", run_a),
        _artifact(root, "b.jsonl", run_b),
        _artifact(root, "c.jsonl", run_c),
    ]
    out = tmp_path / "bundle"
    assert export.main(_merged_argv(world, out, artifacts)) == export.EXIT_OK
    assert _jsonl(world.lines[0:5]) == (out / FILE_DIFF).read_bytes()


def test_two_different_lines_of_one_run_identity_are_refused_and_a_rerun_is_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = _merge_world(tmp_path)
    conflicting = dict(world.lines[1])
    conflicting["checked_at_utc"] = _iso(P1 + timedelta(hours=1, minutes=40))
    other = _artifact(tmp_path / "conflict", "w.jsonl", [conflicting])
    out = tmp_path / "refused"

    code = export.main(_merged_argv(world, out, [world.first, other]))

    assert code == export.EXIT_PUBLISH == 4
    assert not out.exists()
    err = capsys.readouterr().err
    assert "1002" in err and "different" in err

    rerun = dict(world.lines[1])
    rerun["run_metadata"] = {**rerun["run_metadata"], "run_attempt": "2"}
    rerun["checked_at_utc"] = _iso(P1 + timedelta(hours=7))
    kept = _artifact(tmp_path / "rerun", "r.jsonl", [rerun])
    out2 = tmp_path / "kept"
    assert export.main(_merged_argv(world, out2, [world.first, kept])) == export.EXIT_OK
    assert len(load_evidence_bundle(out2).freeze_lines) == 4, "attempt 2 is not attempt 1"


def test_a_line_without_run_metadata_is_deduplicated_by_its_exact_bytes(tmp_path: Path) -> None:
    world = _merge_world(tmp_path)
    skipped = {
        "checked_at_utc": _iso(P1 - timedelta(hours=1)),
        "outcome": "SKIPPED",
        "reason": "allowlist empty",
    }
    one = _artifact(tmp_path / "s", "one.jsonl", [skipped, *world.lines[0:1]])
    two = _artifact(tmp_path / "s", "two.jsonl", [skipped, *world.lines[1:2]])
    out = tmp_path / "bundle"

    assert export.main(_merged_argv(world, out, [one, two])) == export.EXIT_OK

    text = (out / FILE_DIFF).read_text(encoding="utf-8")
    assert text.count("allowlist empty") == 1
    assert len(text.splitlines()) == 3


def test_an_artifact_that_cannot_be_read_is_a_refusal_never_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = _merge_world(tmp_path)
    missing = tmp_path / "artifacts" / "does-not-exist.jsonl"
    binary = tmp_path / "artifacts" / "binary.jsonl"
    binary.write_bytes(b"\xff\xfe not text\n")
    for name, bad in (("missing", missing), ("binary", binary)):
        out = tmp_path / name
        assert export.main(_merged_argv(world, out, [world.first, bad])) == export.EXIT_INPUT
        assert not out.exists()
        assert bad.name in capsys.readouterr().err


def test_a_single_artifact_gives_a_derived_log_equal_to_it_and_is_kept_as_well(
    tmp_path: Path,
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    assert (
        export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
        == export.EXIT_OK
    )
    data = inputs.diff.read_bytes()
    assert (out / FILE_DIFF).read_bytes() == data
    manifest = manifest_of(out)
    assert [e["sha256"] for e in manifest["freeze_log"]["inputs"]] == [_sha(data)]
    assert (out / f"freeze_artifact_{_sha(data)[:16]}.jsonl").read_bytes() == data


def _missing_rows(directory: Path) -> list[dict[str, Any]]:
    text = (directory / FILE_MISSING_TICKS).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_a_slot_without_a_usable_line_is_a_gap_and_a_missing_tick_though_every_artifact_is_clean(
    tmp_path: Path,
) -> None:
    diff_lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000, skip_hours={3})
    inputs = write_inputs(
        tmp_path / "in",
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=diff_lines,
        runs=runs,
    )
    out = tmp_path / "bundle"
    assert (
        export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
        == export.EXIT_OK
    )

    slot = _iso(P1 + timedelta(hours=2, minutes=17))
    assert _gap_slots(out) == [slot]
    rows = _missing_rows(out)
    assert rows == [
        {
            "slot_utc": slot,
            "run_id": None,
            "status": None,
            "conclusion": None,
            "reason": "NO_RUN_FOUND",
        }
    ]
    bundle = load_evidence_bundle(out)
    assert [(t.slot_utc, t.run_id, t.reason) for t in bundle.missing_ticks] == [
        (P1 + timedelta(hours=2, minutes=17), None, "NO_RUN_FOUND")
    ]


def test_a_run_cancelled_before_it_produced_a_line_is_recorded_with_its_conclusion(
    tmp_path: Path,
) -> None:
    diff_lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000, skip_hours={3})
    created = P1 + timedelta(hours=2, minutes=17, seconds=20)
    runs.append(
        {
            "id": 9999,
            "event": "schedule",
            "status": "completed",
            "conclusion": "cancelled",
            "created_at": _iso(created),
            "run_started_at": _iso(created),
            "run_attempt": 1,
            "head_sha": "f" * 40,
        }
    )
    inputs = write_inputs(
        tmp_path / "in",
        records=record_rows(sample_records(E1, P1)),
        pinned=[pinned_row(E1, P1)],
        diff_lines=diff_lines,
        runs=runs,
    )
    out = tmp_path / "bundle"
    assert (
        export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
        == export.EXIT_OK
    )

    slot = _iso(P1 + timedelta(hours=2, minutes=17))
    assert _gap_slots(out) == [slot], "an absent artifact is never read as clean"
    assert _missing_rows(out) == [
        {
            "slot_utc": slot,
            "run_id": "9999",
            "status": "completed",
            "conclusion": "cancelled",
            "reason": "RUN_WITHOUT_LINE",
        }
    ]


def test_a_session_without_a_missing_tick_writes_an_empty_missing_tick_file(
    tmp_path: Path,
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
    assert (out / FILE_MISSING_TICKS).read_bytes() == b""
    assert load_evidence_bundle(out).missing_ticks == ()


# --------------------------------------------------------------------------- #
# Test 4: the redaction scan.
# --------------------------------------------------------------------------- #


def _inputs_with_note(root: Path, note: str) -> Inputs:
    records = sample_records(E1, P1)
    records.append(
        RuntimeRecord(
            event_type=RuntimeEventType.WS_RECONNECT,
            epoch_id=E1,
            occurred_at_utc=P1 + timedelta(hours=1),
            payload={"detail": note},
        )
    )
    diff_lines, runs = freeze_rows(E1, P1, hours=6, first_run_id=1000)
    return write_inputs(
        root,
        records=record_rows(records),
        pinned=[pinned_row(E1, P1)],
        diff_lines=diff_lines,
        runs=runs,
    )


def test_a_clean_bundle_with_64_hex_digests_passes_the_scan(tmp_path: Path) -> None:
    inputs = _inputs_with_note(tmp_path / "in", "reconnected after a normal close")
    out = tmp_path / "bundle"
    assert (
        export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out))
        == export.EXIT_OK
    )
    text = (out / FILE_RECORDS).read_text(encoding="utf-8")
    assert "context_digest" in text and "e" * 64 in text and "window_digest" in text


@pytest.mark.parametrize(
    ("note", "environ", "needle"),
    [
        ("see https://alice:Zq9-hunter-Pw@db.example/trading", {}, "Zq9-hunter-Pw"),
        ("key AKIAABCDEFGHIJKLMNOP leaked", {}, "AKIAABCDEFGHIJKLMNOP"),
        ("value hunter2hunter2 in a note", {"DB_PASSWORD": "hunter2hunter2"}, "hunter2hunter2"),
    ],
)
def test_a_secret_looking_value_aborts_removes_the_partial_bundle_and_prints_no_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    note: str,
    environ: dict[str, str],
    needle: str,
) -> None:
    inputs = _inputs_with_note(tmp_path / "in", note)
    out = tmp_path / "bundle"

    code = export.main(
        inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out),
        environ=environ,
    )

    captured = capsys.readouterr()
    assert code == export.EXIT_SECRET
    assert needle not in captured.out and needle not in captured.err
    assert FILE_RECORDS in captured.err, "the file is named, the value is not"
    assert not out.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in"], "no partial bundle is left"


# --------------------------------------------------------------------------- #
# Test 5: bundles are per epoch and earlier evidence is retained (REV-18).
# --------------------------------------------------------------------------- #


def test_two_epochs_give_two_complete_bundles_and_no_export_drops_or_edits_evidence(
    tmp_path: Path,
) -> None:
    p2 = P1 + timedelta(hours=8)
    diff1, runs1 = freeze_rows(E1, P1, hours=6, first_run_id=1000, skip_hours={3})
    diff2, runs2 = freeze_rows(E2, p2, hours=6, first_run_id=2000)
    records = [*sample_records(E1, P1), *sample_records(E2, p2)]
    inputs = write_inputs(
        tmp_path / "in",
        records=record_rows(records),
        pinned=[pinned_row(E1, P1), pinned_row(E2, p2)],
        diff_lines=[*diff1, *diff2],
        runs=[*runs1, *runs2],
    )
    before = inputs.snapshot()

    first = tmp_path / "bundle-e1"
    second = tmp_path / "bundle-e2"
    assert (
        export.main(
            inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=first)
        )
        == export.EXIT_OK
    )
    assert (
        export.main(
            inputs.argv(source="fixture", epoch=E2, start=p2, end=p2 + SIX_HOURS, out=second)
        )
        == export.EXIT_OK
    )

    bundles: dict[str, EvidenceBundle] = {
        E1: load_evidence_bundle(first),
        E2: load_evidence_bundle(second),
    }
    for epoch, bundle in bundles.items():
        assert bundle.epoch_id == epoch
        assert bundle.pinned.epoch_id == epoch
        assert {r.epoch_id for r in bundle.records} == {epoch}
        assert len(bundle.records) == len(RuntimeEventType)
        # The freeze lines and the run list are copied whole, whatever the epoch.
        assert (bundle.path / FILE_DIFF).read_bytes() == inputs.diff.read_bytes()
        assert (bundle.path / FILE_RUNS).read_bytes() == inputs.runs.read_bytes()
        assert len(bundle.freeze_lines) == len(diff1) + len(diff2)
        assert len(bundle.runs) == len(runs1) + len(runs2)
    assert (first / FILE_PINNED).read_bytes() == inputs.pinned[0].read_bytes()
    assert (second / FILE_PINNED).read_bytes() == inputs.pinned[1].read_bytes()
    assert len(bundles[E1].evidence_gaps) == 1
    assert bundles[E2].evidence_gaps == ()
    assert inputs.snapshot() == before, "no export edits, drops or filters an input"

    # Exporting the earlier epoch again, now that a newer pin exists, gives the same bytes.
    again = tmp_path / "bundle-e1-again"
    assert (
        export.main(
            inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=again)
        )
        == export.EXIT_OK
    )
    assert directory_bytes(again) == directory_bytes(first)
    assert inputs.snapshot() == before


def test_an_epoch_without_its_pinned_file_is_refused(tmp_path: Path) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    code = export.main(
        inputs.argv(source="fixture", epoch=E2, start=P1, end=P1 + SIX_HOURS, out=out)
    )
    assert code == export.EXIT_INPUT
    assert not out.exists()


def test_an_existing_output_directory_is_never_overwritten(tmp_path: Path) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out)
    assert export.main(argv) == export.EXIT_OK
    kept = directory_bytes(out)
    assert export.main(argv) == export.EXIT_INPUT
    assert directory_bytes(out) == kept


def test_a_window_that_ends_before_it_starts_is_refused(tmp_path: Path) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    code = export.main(inputs.argv(source="fixture", epoch=E1, start=P1, end=P1, out=out))
    assert code == export.EXIT_INPUT
    assert not out.exists()


# --------------------------------------------------------------------------- #
# Test 6: parity is rebuilt from the exported bundle alone (plan 16-51).
# --------------------------------------------------------------------------- #


def _session_inputs(world: World, epoch_id: str, root: Path) -> Inputs:
    """Pinned file, empty freeze evidence and config for the world's session."""
    pin = world.started_at
    pinned = {
        **pinned_row(epoch_id, pin),
        "parameter_set_id": world.case["parameter_set_id"],
        "parameter_set_hash": world.parameter_set.parameter_set_hash,
    }
    return write_inputs(root, records=[], pinned=[pinned], diff_lines=[], runs=[])


def _evaluate_cli(bundle_dir: Path, inputs: Inputs, tmp_path: Path) -> list[str]:
    return [
        "--bundle",
        str(bundle_dir),
        "--config",
        str(inputs.config),
        "--workflow",
        str(inputs.workflow),
        "--q-d-decision",
        str(QD_DECISION),
        "--out",
        str(tmp_path / "evaluation.txt"),
    ]


def test_parity_is_rebuilt_from_the_exported_bundle_and_one_altered_input_fails_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.test_paper_runtime_pipeline import EPOCH_ID

    world = World()
    world.run_tracer_session()
    inputs = _session_inputs(world, EPOCH_ID, tmp_path / "in")
    start = world.started_at
    end = start + timedelta(days=14)

    good = tmp_path / "good"
    assert (
        export.main(
            inputs.argv(
                source="pg", epoch=EPOCH_ID, start=start, end=end, out=good, with_records=False
            ),
            state=world.state,
        )
        == export.EXIT_OK
    )
    capsys.readouterr()
    evaluate.main(_evaluate_cli(good, inputs, tmp_path))
    printed = capsys.readouterr().out
    assert "PASS  parity (tolerance zero)" in printed

    # The same session with one recorded input altered (digest recomputed, so the record stays
    # self-consistent) is a parity difference that names the bar close.
    altered = InMemoryRuntimeState()
    changed = False
    for record in world.state.records(EPOCH_ID):
        if record.event_type is RuntimeEventType.PAPER_REPLAY_INPUTS:
            payload = json.loads(record.payload_json)
            payload["constraint_snapshot"]["min_notional"] = "1000000"
            record = RuntimeRecord(
                event_type=record.event_type,
                epoch_id=record.epoch_id,
                occurred_at_utc=record.occurred_at_utc,
                symbol=record.symbol,
                interval=record.interval,
                payload=with_digest(payload, world.parameter_set),
            )
            changed = True
        altered.record(record)
    assert changed

    bad = tmp_path / "bad"
    assert (
        export.main(
            inputs.argv(
                source="pg", epoch=EPOCH_ID, start=start, end=end, out=bad, with_records=False
            ),
            state=altered,
        )
        == export.EXIT_OK
    )
    capsys.readouterr()
    evaluate.main(_evaluate_cli(bad, inputs, tmp_path))
    printed = capsys.readouterr().out
    assert "FAIL  parity (tolerance zero)" in printed
    assert world.fx.last_1h.close_time_utc.isoformat() in printed


# --------------------------------------------------------------------------- #
# PostgreSQL: the real port.
# --------------------------------------------------------------------------- #


def test_the_pg_source_exports_every_record_stored_on_postgresql(
    pg_db: str, tmp_path: Path
) -> None:
    engine: Engine = make_sync_engine(pg_db)
    try:
        state = PgRuntimeState(OperationalDatabase(engine))
        originals = sample_records(E1, P1)
        for record in originals:
            state.record(record)
        inputs = one_epoch_inputs(tmp_path / "in")
        out = tmp_path / "bundle"
        code = export.main(
            inputs.argv(
                source="pg", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out, with_records=False
            ),
            state=state,
        )
        assert code == export.EXIT_OK
        bundle = load_evidence_bundle(out)
        assert bundle.source == "pg"
        assert sorted(runtime_event_id(r) for r in bundle.records) == sorted(
            runtime_event_id(r) for r in originals
        )
        assert sorted(r.payload_json for r in bundle.records) == sorted(
            r.payload_json for r in originals
        )
    finally:
        engine.dispose()


def test_shadow_rows_are_filtered_to_the_epoch_of_the_bundle(tmp_path: Path) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    inputs.analytics = tmp_path / "in" / "analytics_inputs.json"
    document = shadow_document(E2)  # every SHADOW row belongs to another epoch
    inputs.analytics.write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "bundle"
    code = export.main(
        inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out)
    )
    assert code == export.EXIT_OK
    evidence = load_evidence_file(out / FILE_ANALYTICS)
    assert evidence.paper == ()


# --------------------------------------------------------------------------- #
# Plan 16-47, Task 1: publish to the recorded O-01 destination (option a: an S3 evidence
# prefix outside the backup crypt remote; versioning enabled, no Object Lock; the user alone
# reads it; written by the exporter on the operator's schedule). Everything runs against an
# injected uploader: no network, no AWS, no rclone binary.
# --------------------------------------------------------------------------- #

DESTINATION = "EVIDENCES3:evidence-bucket/paper"

# The fixed evidence configuration names (src/ops/evidence_remote.py); values are fake.
SECRET_KEY = "Zq9-evidence-secret-KEY-value"
ACCESS_ID = "EVID-access-id-0001"
EVIDENCE_ENV = {
    "EVIDENCE_S3_PROVIDER": "AWS",
    "EVIDENCE_S3_ENDPOINT": "",
    "EVIDENCE_S3_REGION": "ap-southeast-1",
    "EVIDENCE_S3_BUCKET": "evidence-bucket",
    "EVIDENCE_S3_PREFIX": "paper",
    "EVIDENCE_S3_ACCESS_KEY_ID": ACCESS_ID,
    "EVIDENCE_S3_SECRET_ACCESS_KEY": SECRET_KEY,
}


class FakeUploader:
    """An in-memory object store with the three operations the publisher uses."""

    def __init__(
        self,
        *,
        objects: Mapping[str, bytes] | None = None,
        corrupt: Collection[str] = (),
        fail_put: Collection[str] = (),
        error_text: str = "put failed",
    ) -> None:
        self.objects: dict[str, bytes] = dict(objects or {})
        self.corrupt = set(corrupt)
        self.fail_put = set(fail_put)
        self.error_text = error_text
        self.puts: list[str] = []

    def listing(self, prefix: str) -> frozenset[str]:
        head = prefix.rstrip("/") + "/"
        return frozenset(k[len(head) :] for k in self.objects if k.startswith(head))

    def put(self, key: str, data: bytes) -> None:
        if key in self.fail_put:
            raise export.PublishError(self.error_text)
        self.puts.append(key)
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        data = self.objects[key]
        return data + b"x" if key.rsplit("/", 1)[-1] in self.corrupt else data


def _publish_args(inputs: Inputs, out: Path) -> list[str]:
    return [
        *inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out),
        "--publish",
    ]


def test_tracer_publish_uploads_the_files_then_the_manifest_and_verifies_the_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    uploader = FakeUploader()

    code = export.main(_publish_args(inputs, out), uploader=uploader)

    assert code == export.EXIT_OK, capsys.readouterr()
    manifest = manifest_of(out)
    prefix = _prefix(out)
    keys = [f"{prefix}/{name}" for name in manifest["files"]]
    assert uploader.puts[-1] == f"{prefix}/manifest.json", "the manifest is published last"
    assert sorted(uploader.puts[:-1]) == sorted(keys)
    assert len(uploader.puts) == len(set(uploader.puts)), "every object once"
    for name in [*manifest["files"], "manifest.json"]:
        assert uploader.objects[f"{prefix}/{name}"] == (out / name).read_bytes()
    assert "published" in capsys.readouterr().out


def test_hourly_and_final_bundles_of_one_epoch_each_publish_under_their_own_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """B2-CR-04: the second hourly publish and the final one no longer collide (16-59 Q1 = A)."""
    inputs = one_epoch_inputs(tmp_path / "in")
    uploader = FakeUploader()
    moments = {
        "hour-1": P1 + timedelta(hours=1),
        "hour-2": P1 + timedelta(hours=2),
        "final": P1 + SIX_HOURS + timedelta(seconds=GRACE_SECONDS),
    }
    prefixes: dict[str, str] = {}
    for name, as_of in moments.items():
        out = tmp_path / name
        argv = inputs.argv(
            source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out, as_of=as_of
        )
        assert export.main([*argv, "--publish"], uploader=uploader) == export.EXIT_OK, name
        prefixes[name] = _prefix(out)
        compact = as_of.strftime("%Y%m%dT%H%M%SZ")
        assert re.fullmatch(rf"{E1}/{compact}-[0-9a-f]{{12}}", prefixes[name])
    assert len(set(prefixes.values())) == 3
    capsys.readouterr()

    # Nothing was replaced: every object of every bundle is still there with its own bytes.
    for name, prefix in prefixes.items():
        for file_name in [*manifest_of(tmp_path / name)["files"], "manifest.json"]:
            local = (tmp_path / name / file_name).read_bytes()
            assert uploader.objects[f"{prefix}/{file_name}"] == local
    assert len(uploader.puts) == len(set(uploader.puts)), "no key was written twice"


def test_publishing_the_very_same_bundle_again_uploads_nothing_and_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    uploader = FakeUploader()
    assert export.main(_publish_args(inputs, tmp_path / "b1"), uploader=uploader) == 0
    puts_after_first = list(uploader.puts)
    capsys.readouterr()

    # The same inputs give the same bytes, hence the same key: identical bytes are a success.
    code = export.main(_publish_args(inputs, tmp_path / "b2"), uploader=uploader)
    assert code == export.EXIT_OK, capsys.readouterr()
    assert uploader.puts == puts_after_first, "nothing is uploaded a second time"
    assert directory_bytes(tmp_path / "b1") == directory_bytes(tmp_path / "b2")

    # So does the publish subcommand on the existing bundle.
    again = export.main(["publish", "--bundle", str(tmp_path / "b1")], uploader=uploader)
    assert again == export.EXIT_OK
    assert uploader.puts == puts_after_first


def test_different_bytes_at_an_existing_key_are_an_error_and_nothing_is_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    seed = tmp_path / "seed"
    argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=seed)
    assert export.main(argv) == export.EXIT_OK
    prefix = _prefix(seed)

    forged = FakeUploader(objects={f"{prefix}/manifest.json": b"{}"})
    code = export.main(_publish_args(inputs, tmp_path / "b1"), uploader=forged)
    assert code == export.EXIT_PUBLISH
    assert forged.puts == []
    assert forged.objects == {f"{prefix}/manifest.json": b"{}"}
    assert "different content" in capsys.readouterr().err

    partial = FakeUploader(objects={f"{prefix}/{FILE_PINNED}": b"different"})
    code = export.main(_publish_args(inputs, tmp_path / "b2"), uploader=partial)
    assert code == export.EXIT_PUBLISH
    assert FILE_PINNED in capsys.readouterr().err
    assert partial.objects == {f"{prefix}/{FILE_PINNED}": b"different"}, "never overwritten"
    assert f"{prefix}/manifest.json" not in partial.objects


def test_the_key_comes_from_the_manifest_only_and_a_bundle_without_as_of_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out)
    assert export.main(argv) == 0
    manifest = manifest_of(out)
    del manifest["as_of_utc"]
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    uploader = FakeUploader()

    code = export.main(["publish", "--bundle", str(out)], uploader=uploader)

    assert code == export.EXIT_INPUT
    assert uploader.puts == []
    assert "as_of_utc" in capsys.readouterr().err
    for flag in ("--key", "--prefix", "--as-of"):
        with pytest.raises(SystemExit):
            export.main(["publish", "--bundle", str(out), flag, "x"], uploader=uploader)
    capsys.readouterr()


def test_a_published_copy_that_differs_from_the_manifest_fails_naming_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    uploader = FakeUploader(corrupt={FILE_DIFF})

    code = export.main(_publish_args(inputs, out), uploader=uploader)

    captured = capsys.readouterr()
    assert code == export.EXIT_PUBLISH != export.EXIT_OK
    assert FILE_DIFF in captured.err
    assert _sha((out / FILE_DIFF).read_bytes()) not in captured.err + captured.out
    assert out.exists(), "the local bundle is kept for another attempt"


def test_a_missing_published_object_fails_the_verification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Dropping(FakeUploader):
        def put(self, key: str, data: bytes) -> None:
            if not key.endswith(FILE_GAPS):
                super().put(key, data)

        def get(self, key: str) -> bytes:
            if key not in self.objects:
                raise export.PublishError(f"{key.rsplit('/', 1)[-1]} cannot be read back")
            return super().get(key)

    inputs = one_epoch_inputs(tmp_path / "in")
    code = export.main(_publish_args(inputs, tmp_path / "bundle"), uploader=Dropping())
    assert code == export.EXIT_PUBLISH
    assert FILE_GAPS in capsys.readouterr().err


def test_an_interrupted_earlier_publish_is_resumed_only_over_identical_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    seed = tmp_path / "seed"
    seed_args = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=seed)
    assert export.main(seed_args) == export.EXIT_OK
    prefix = _prefix(seed)
    same = FakeUploader(objects={f"{prefix}/{FILE_PINNED}": (seed / FILE_PINNED).read_bytes()})
    assert export.main(_publish_args(inputs, tmp_path / "b1"), uploader=same) == export.EXIT_OK
    assert f"{prefix}/{FILE_PINNED}" not in same.puts, "an identical object is left alone"

    other = FakeUploader(objects={f"{prefix}/{FILE_PINNED}": b"different"})
    code = export.main(_publish_args(inputs, tmp_path / "b2"), uploader=other)
    assert code == export.EXIT_PUBLISH
    assert FILE_PINNED in capsys.readouterr().err
    assert other.objects[f"{prefix}/{FILE_PINNED}"] == b"different", "never overwritten"


def test_a_failed_export_publishes_nothing(tmp_path: Path) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    uploader = FakeUploader()
    args = _publish_args(inputs, tmp_path / "bundle")
    args[args.index("--epoch") + 1] = E2  # no --pinned file belongs to it
    assert export.main(args, uploader=uploader) == export.EXIT_INPUT
    assert uploader.puts == [] and uploader.objects == {}


def test_the_publish_subcommand_publishes_an_existing_bundle_after_loading_it(
    tmp_path: Path,
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    args = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=out)
    assert export.main(args) == export.EXIT_OK
    uploader = FakeUploader()
    argv = ["publish", "--bundle", str(out)]
    assert export.main(argv, uploader=uploader) == export.EXIT_OK
    assert uploader.puts[-1] == f"{_prefix(out)}/manifest.json"

    (out / FILE_DIFF).write_bytes(b"edited after export\n")
    again = FakeUploader()
    assert export.main(argv, uploader=again) == export.EXIT_INPUT
    assert again.puts == []


def test_option_a_writes_no_git_digest_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    assert export.main(_publish_args(inputs, out), uploader=FakeUploader()) == export.EXIT_OK
    found = [p.name for root in (tmp_path, work) for p in root.rglob("manifest.sha256")]
    assert found == [], "Git digests belong to options b and e, which are not recorded"
    assert not (work / "evidence").exists()


@pytest.mark.parametrize(
    "extra",
    [
        ["--publish-git", "x"],
        ["--publish-dir", "somewhere"],
        ["--git-digests"],
        ["--publish-github-artifact"],
    ],
)
def test_only_the_recorded_destination_flag_exists(tmp_path: Path, extra: list[str]) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    argv = inputs.argv(
        source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=tmp_path / "bundle"
    )
    with pytest.raises(SystemExit) as raised:
        export.main([*argv, *extra], uploader=FakeUploader())
    assert raised.value.code == 2
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize(
    "extra",
    [["--publish", "evidence:bucket/p"], ["--publish", "BACKUPS3CRYPT:bucket/p"]],
)
def test_publish_takes_no_free_form_destination(tmp_path: Path, extra: list[str]) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    argv = inputs.argv(
        source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=tmp_path / "bundle"
    )
    with pytest.raises(SystemExit) as raised:
        export.main([*argv, *extra], uploader=FakeUploader())
    assert raised.value.code == 2
    with pytest.raises(SystemExit) as raised_sub:
        export.main(["publish", "--bundle", str(tmp_path), "--destination", "evidence:b/p"])
    assert raised_sub.value.code == 2


def test_missing_or_empty_evidence_names_exit_naming_only_the_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    environ = {
        **EVIDENCE_ENV,
        "EVIDENCE_S3_REGION": "",  # empty counts as missing
        "EVIDENCE_S3_BUCKET": "evidence-bucket",
    }
    del environ["EVIDENCE_S3_SECRET_ACCESS_KEY"]

    code = export.main(_publish_args(inputs, out), environ=environ)

    err = capsys.readouterr().err
    assert code == export.EXIT_INPUT
    assert "EVIDENCE_S3_REGION" in err and "EVIDENCE_S3_SECRET_ACCESS_KEY" in err
    for present in ("EVIDENCE_S3_BUCKET", "EVIDENCE_S3_PREFIX", "EVIDENCE_S3_ACCESS_KEY_ID"):
        assert present not in err, "only the missing names are listed"
    assert ACCESS_ID not in err and "evidence-bucket" not in err
    assert not out.exists(), "refused before any export or upload"


def test_no_evidence_names_at_all_lists_the_required_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    code = export.main(_publish_args(inputs, tmp_path / "bundle"), environ={})
    err = capsys.readouterr().err
    assert code == export.EXIT_INPUT
    for name in (
        "EVIDENCE_S3_PROVIDER",
        "EVIDENCE_S3_REGION",
        "EVIDENCE_S3_BUCKET",
        "EVIDENCE_S3_PREFIX",
        "EVIDENCE_S3_ACCESS_KEY_ID",
        "EVIDENCE_S3_SECRET_ACCESS_KEY",
    ):
        assert name in err


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EVIDENCE_S3_PREFIX", "/absolute"),
        ("EVIDENCE_S3_PREFIX", "a/../b"),
        ("EVIDENCE_S3_PREFIX", "two words"),
        ("EVIDENCE_S3_PREFIX", "p?secret_access_key=abc"),
        ("EVIDENCE_S3_PREFIX", "/"),
        ("EVIDENCE_S3_BUCKET", "bucket/with/slash"),
        ("EVIDENCE_S3_BUCKET", "bucket:colon"),
        ("EVIDENCE_S3_PREFIX", "token-in-the-prefix"),
        ("EVIDENCE_S3_ACCESS_KEY_ID", "BACKUP-shared-id"),  # equal to the backup credential
    ],
)
def test_an_unusable_evidence_value_is_refused_before_any_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, value: str
) -> None:
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"
    environ = {**EVIDENCE_ENV, "BACKUP_S3_ACCESS_KEY_ID": "BACKUP-shared-id", name: value}
    code = export.main(_publish_args(inputs, out), environ=environ)
    captured = capsys.readouterr()
    assert code == export.EXIT_INPUT
    assert name in captured.err
    if len(value) > 3:
        assert value not in captured.out + captured.err, "the value is never printed"
    assert SECRET_KEY not in captured.out + captured.err
    assert not out.exists()


def test_publish_reaches_rclone_through_the_environment_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = FakeRclone()
    seen_env: list[Mapping[str, str]] = []

    def fake_run(
        argv: Sequence[str], stdin: bytes | None, env: Mapping[str, str]
    ) -> tuple[int, bytes, bytes]:
        seen_env.append(env)
        return runner(argv, stdin)

    monkeypatch.setattr(export, "_run_rclone", fake_run)
    inputs = one_epoch_inputs(tmp_path / "in")
    out = tmp_path / "bundle"

    code = export.main(_publish_args(inputs, out), environ=dict(EVIDENCE_ENV))

    captured = capsys.readouterr()
    assert code == export.EXIT_OK, captured
    assert runner.calls
    for argv, _ in runner.calls:
        text = " ".join(argv)
        assert SECRET_KEY not in text and ACCESS_ID not in text
        assert "EVIDENCES3:evidence-bucket/paper/" in text
    assert SECRET_KEY not in captured.out + captured.err
    for env in seen_env:
        assert env["RCLONE_CONFIG_EVIDENCES3_TYPE"] == "s3"
        assert env["RCLONE_CONFIG_EVIDENCES3_SECRET_ACCESS_KEY"] == SECRET_KEY
        assert env["RCLONE_CONFIG_EVIDENCES3_ACCESS_KEY_ID"] == ACCESS_ID
        assert env["RCLONE_CONFIG_EVIDENCES3_NO_CHECK_BUCKET"] == "true"
        assert not any("CRYPT" in key for key in env if key.startswith("RCLONE_CONFIG_EVIDENCES3"))
    assert len(runner.store) == len(manifest_of(out)["files"]) + 1


def test_no_credential_value_reaches_the_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "Zq9-hunter-Pw-evidence"
    environ = {"EVIDENCE_SECRET_ACCESS_KEY": secret}
    inputs = one_epoch_inputs(tmp_path / "in")
    seed = tmp_path / "seed"
    seed_argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + SIX_HOURS, out=seed)
    assert export.main(seed_argv) == 0
    prefix = _prefix(seed)
    uploader = FakeUploader(fail_put={f"{prefix}/{FILE_RUNS}"}, error_text=f"denied for {secret}")

    code = export.main(
        _publish_args(inputs, tmp_path / "bundle"), uploader=uploader, environ=environ
    )

    captured = capsys.readouterr()
    assert code == export.EXIT_PUBLISH
    assert secret not in captured.out + captured.err
    assert f"{prefix}/manifest.json" not in uploader.objects, (
        "a failed file stops before the manifest"
    )


class FakeRclone:
    """Records argv and the data given on standard input; serves a small object store."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bytes | None]] = []
        self.store: dict[str, bytes] = {}

    def __call__(self, argv: Sequence[str], stdin: bytes | None) -> tuple[int, bytes, bytes]:
        self.calls.append((list(argv), stdin))
        verb, *rest = argv
        target = rest[-1]
        if verb == "rcat":
            assert stdin is not None
            self.store[target] = stdin
            return 0, b"", b""
        if verb == "cat":
            if target not in self.store:
                return 3, b"", b"object not found"
            return 0, self.store[target], b""
        if verb == "lsf":
            head = target.rstrip("/") + "/"
            names = [k[len(head) :] for k in self.store if k.startswith(head)]
            if not names:
                return 3, b"", b""
            return 0, "".join(f"{n}\n" for n in names).encode(), b""
        return 1, b"", b"unknown verb"


def test_the_rclone_uploader_passes_only_the_destination_and_the_data() -> None:
    runner = FakeRclone()
    uploader = export.RcloneUploader(DESTINATION, runner=runner)

    assert uploader.listing(E1) == frozenset()
    uploader.put(f"{E1}/a.json", b"payload")
    assert uploader.get(f"{E1}/a.json") == b"payload"
    assert uploader.listing(E1) == frozenset({"a.json"})
    with pytest.raises(export.PublishError):
        uploader.get(f"{E1}/missing.json")

    for argv, stdin in runner.calls:
        text = " ".join(argv)
        assert DESTINATION in text
        assert "secret" not in text.lower() and "key" not in text.lower()
        if argv[0] == "rcat":
            assert "--immutable" in argv, "an object is never replaced"
            assert stdin == b"payload", "the data travels on standard input, not in argv"
        else:
            assert stdin is None
