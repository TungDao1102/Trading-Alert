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
    ) -> list[str]:
        argv = ["--source", source]
        if with_records:
            argv += ["--records", str(self.records)]
        for pinned in self.pinned:
            argv += ["--pinned", str(pinned)]
        argv += [
            "--diff-log",
            str(self.diff),
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
    assert set(manifest["files"]) == {*REQUIRED_FILES, FILE_ANALYTICS}
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
        detected_at_utc=P1 + SIX_HOURS,
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
