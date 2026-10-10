"""Trial exit-criteria evaluator (Phase 16, plan 16-25; D-23, L-04, REV-01, REV-17, REV-18).

Task 1 (tracer): a fixture bundle of a 14-day trial is loaded, verified against the manifest
sha256 values and evaluated criterion by criterion with the ratified constants and the
user-owned thresholds only. The fixture is built here, from the same line shapes the exporter of
plan 16-30 writes; its proof class is FAKE because its manifest source is "fixture".
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.paper import coverage as coverage_module
from src.paper import evidence_bundle as bundle_module
from src.paper import exit_criteria as exit_module
from src.paper.coverage import HealthThresholds
from src.paper.evidence_bundle import (
    BUNDLE_SCHEMA,
    BundleError,
    EvidenceBundle,
    load_evidence_bundle,
)
from src.paper.exit_criteria import (
    MIN_COVERAGE_FRACTION,
    PARITY_TOLERANCE,
    TRIAL_CALENDAR_DAYS,
    ProofClass,
    TrialEvaluation,
    evaluate_trial,
)
from src.paper.runtime_state import RuntimeRecord
from src.paper.vocabulary import GapReason, RuntimeEventType

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "evaluate_trial_soak.py"

EPOCH_ID = "e" * 64
OTHER_EPOCH_ID = "d" * 64
PARAMETER_HASH = "b" * 64
STRATEGY_ID = "trend-pullback"
PARAMETER_SET_ID = "test-set-v1"
SYMBOL = "BTCUSDT"
CRON = "17 * * * *"
PIN = datetime(2026, 11, 1, tzinfo=UTC)
WINDOW_END = PIN + timedelta(days=14)
ONE_MS = timedelta(milliseconds=1)

THRESHOLDS = HealthThresholds(
    max_ws_message_silence_seconds=5400,
    max_closed_bar_lateness_seconds=60,
    continuous_uncovered_ceiling_seconds=4 * 3600,
    freeze_tick_grace_seconds=300,
)

# The fixture's planned restart (30 minutes) and websocket disconnect (2 hours).
STOP_AT = PIN + timedelta(days=2, hours=10)
RESTART_AT = STOP_AT + timedelta(minutes=30)
DROP_AT = PIN + timedelta(days=7, hours=4)
RECONNECT_AT = DROP_AT + timedelta(hours=2)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    return text.encode("utf-8")


# --------------------------------------------------------------------------- #
# Fixture builder: the line shapes of the exporter (plan 16-30).
# --------------------------------------------------------------------------- #


@dataclass
class TrialFixture:
    """Everything a bundle holds, as plain rows, so a test can change one thing and re-write."""

    epoch_id: str = EPOCH_ID
    pin: datetime = PIN
    window_end: datetime = WINDOW_END
    source: str = "fixture"
    cron: str = CRON
    parameter_hash: str = PARAMETER_HASH
    records: list[dict[str, Any]] = field(default_factory=list)
    diff_lines: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    analytics: dict[str, Any] | None = None

    def pinned_row(self) -> dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "strategy_id": STRATEGY_ID,
            "parameter_set_id": PARAMETER_SET_ID,
            "parameter_set_hash": self.parameter_hash,
            "opened_at_utc": _iso(self.pin),
            "evidence_claim_open": True,
        }

    def write(self, directory: Path, *, tamper: str | None = None) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        files: dict[str, bytes] = {
            "pinned_epoch.json": json.dumps(self.pinned_row(), sort_keys=True).encode("utf-8"),
            "registry_diff.jsonl": _jsonl(self.diff_lines),
            "github_runs.json": json.dumps({"workflow_runs": self.runs}).encode("utf-8"),
            "runtime_records.jsonl": _jsonl(self.records),
            "evidence_gaps.jsonl": _jsonl(self.gaps),
        }
        if self.analytics is not None:
            files["analytics_evidence.json"] = json.dumps(self.analytics).encode("utf-8")
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "epoch_id": self.epoch_id,
            "window_start_utc": _iso(self.pin),
            "window_end_utc": _iso(self.window_end),
            "source": self.source,
            "files": {name: _sha(data) for name, data in files.items()},
        }
        for name, data in files.items():
            (directory / name).write_bytes(data)
        (directory / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
        )
        if tamper is not None:
            target = directory / tamper
            target.write_bytes(target.read_bytes() + b" ")
        return directory


def record_row(
    event_type: RuntimeEventType,
    at: datetime,
    *,
    epoch_id: str = EPOCH_ID,
    symbol: str | None = None,
    interval: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_type": event_type.value,
        "epoch_id": epoch_id,
        "occurred_at_utc": _iso(at),
        "symbol": symbol,
        "interval": interval,
        "payload": dict(payload or {}),
    }


def _bar_payload(close: datetime, tick: datetime, interval: str) -> dict[str, Any]:
    open_time = close + ONE_MS - timedelta(hours=1 if interval == "1h" else 4)
    return {
        "source": "LIVE_WS",
        "tick_time_utc": _iso(tick),
        "bar": {
            "symbol": SYMBOL,
            "interval": interval,
            "open_time_utc": _iso(open_time),
            "close_time_utc": _iso(close),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "10",
        },
        "stage": "feed_gate" if interval == "1h" else "context",
        "reason_code": "WARMUP_INSUFFICIENT" if interval == "1h" else "CONTEXT_BAR",
        "plan_hash": None,
    }


def trial_rows(
    *,
    epoch_id: str = EPOCH_ID,
    pin: datetime = PIN,
    cron: str = CRON,
    hours: int = 336,
    with_disturbances: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Runtime records, diff lines and runs of a 14-day trial with one restart and one drop.

    A bar is processed exactly at its close + 1 ms (the next whole hour). The 30-minute planned
    restart spans no close; the 2-hour disconnect swallows two 1h closes, each recorded as a
    PAPER_GAP with its reason.
    """
    records: list[dict[str, Any]] = [
        record_row(RuntimeEventType.RUNTIME_START, pin, epoch_id=epoch_id),
        record_row(RuntimeEventType.WS_RECONNECT, pin, epoch_id=epoch_id),
    ]
    for k in range(1, hours + 1):
        tick = pin + timedelta(hours=k)
        close = tick - ONE_MS
        down = with_disturbances and (DROP_AT < tick <= RECONNECT_AT)
        if down:
            for interval in ("1h", "4h") if k % 4 == 0 else ("1h",):
                records.append(
                    record_row(
                        RuntimeEventType.PAPER_GAP,
                        tick,
                        epoch_id=epoch_id,
                        symbol=SYMBOL,
                        interval=interval,
                        payload={
                            "expected_close_utc": _iso(close),
                            "reason": GapReason.WS_DISCONNECTED.value,
                            "source": "WS_DISCONNECTED",
                        },
                    )
                )
            continue
        for interval in ("1h", "4h") if k % 4 == 0 else ("1h",):
            records.append(
                record_row(
                    RuntimeEventType.PAPER_BAR_PROCESSED,
                    close,
                    epoch_id=epoch_id,
                    symbol=SYMBOL,
                    interval=interval,
                    payload=_bar_payload(close, tick, interval),
                )
            )
        records.append(
            record_row(
                RuntimeEventType.PAPER_TICK_STATS,
                tick,
                epoch_id=epoch_id,
                payload={
                    "batch_seq": k,
                    "duration_ms": 5 + (k % 7),
                    "queue_depth_before": k % 3,
                    "dropped_total": 0,
                    "dropped_by_reason": {},
                },
            )
        )
    if with_disturbances:
        records.append(record_row(RuntimeEventType.RUNTIME_STOP, STOP_AT, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.RUNTIME_START, RESTART_AT, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.WS_RECONNECT, RESTART_AT, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.WS_DISCONNECT, DROP_AT, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.WS_RECONNECT, RECONNECT_AT, epoch_id=epoch_id))

    minute = int(cron.split()[0])
    diff_lines: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    slot = pin.replace(minute=minute, second=0, microsecond=0)
    if slot <= pin:
        slot += timedelta(hours=1)
    run_id = 1000
    while slot <= pin + timedelta(hours=hours):
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
                "head_sha": "c" * 40,
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
                    "schedule": cron,
                    "commit": "c" * 40,
                },
            }
        )
        run_id += 1
        slot += timedelta(hours=1)
    return records, diff_lines, runs


def make_fixture(**overrides: Any) -> TrialFixture:
    records, diff_lines, runs = trial_rows()
    base = TrialFixture(records=records, diff_lines=diff_lines, runs=runs)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@pytest.fixture(scope="module")
def trial_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_fixture().write(tmp_path_factory.mktemp("trial-bundle"))


@pytest.fixture(scope="module")
def trial_bundle(trial_dir: Path) -> EvidenceBundle:
    return load_evidence_bundle(trial_dir)


def _evaluate(
    bundle: EvidenceBundle, *, thresholds: HealthThresholds = THRESHOLDS
) -> TrialEvaluation:
    return evaluate_trial(bundle, thresholds=thresholds, cron=CRON, symbols=(SYMBOL,))


def _result(evaluation: TrialEvaluation, name_part: str) -> Any:
    matches = [r for g in evaluation.groups for r in g.results if name_part in r.name]
    assert len(matches) == 1, (name_part, [r.name for g in evaluation.groups for r in g.results])
    return matches[0]


# --------------------------------------------------------------------------- #
# Test 1: the tracer.
# --------------------------------------------------------------------------- #


def test_tracer_a_14_day_fixture_trial_is_judged_criterion_by_criterion(
    trial_bundle: EvidenceBundle,
) -> None:
    evaluation = _evaluate(trial_bundle)

    window = _result(evaluation, "trial window")
    assert window.passed, window.evidence
    assert any("14 calendar days" in line for line in window.evidence)

    coverage = _result(evaluation, "runtime coverage")
    assert coverage.passed, coverage.evidence
    text = "\n".join(coverage.evidence)
    assert "336" in text
    assert "319.2" in text
    assert "DERIVED" in text
    assert "not a threshold" in text
    # 336 h minus the 30-minute restart and the 2-hour disconnect (plus the 60 s lateness of the
    # last swallowed close): between 333 and 333.5 hours covered.
    assert any(re.search(r"333\.[0-4]", line) for line in coverage.evidence), coverage.evidence

    ceiling = _result(evaluation, "continuous uncovered")
    assert ceiling.passed, ceiling.evidence

    freeze = _result(evaluation, "freeze continuity")
    assert freeze.passed, freeze.evidence
    assert _result(evaluation, "single epoch").passed
    assert _result(evaluation, "pinned hash unchanged").passed

    # Time of day is reported as a distribution, never a pass condition.
    distribution = evaluation.time_of_day
    assert "reported, not a pass condition" in distribution.label
    assert len(distribution.covered_hours_by_hour_of_day) == 24
    covered_us = sum(distribution.covered_microseconds_by_hour_of_day.values())
    assert Decimal(covered_us) / Decimal(3_600_000_000) == evaluation.coverage.covered_hours
    assert evaluation.proof_class is ProofClass.FAKE


def test_freeze_and_runtime_groups_are_reported_separately(trial_bundle: EvidenceBundle) -> None:
    evaluation = _evaluate(trial_bundle)
    names = [group.name for group in evaluation.groups]
    assert "freeze integrity" in names
    assert "runtime health" in names


def test_the_rendered_evaluation_prints_pass_or_fail_per_criterion(
    trial_bundle: EvidenceBundle,
) -> None:
    text = _evaluate(trial_bundle).render()
    assert "PASS  trial window" in text
    assert "PASS  runtime coverage" in text
    assert "reported, not a pass condition" in text
    assert "proof class: FAKE" in text


# --------------------------------------------------------------------------- #
# Test 2: fail closed on a tampered bundle.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    ["pinned_epoch.json", "registry_diff.jsonl", "github_runs.json", "runtime_records.jsonl"],
)
def test_a_file_that_does_not_match_the_manifest_sha256_is_refused_by_name(
    tmp_path: Path, name: str
) -> None:
    make_fixture().write(tmp_path / "bundle", tamper=name)
    with pytest.raises(BundleError, match=re.escape(name)):
        load_evidence_bundle(tmp_path / "bundle")


def test_a_missing_listed_file_and_a_foreign_file_name_are_refused(tmp_path: Path) -> None:
    directory = make_fixture().write(tmp_path / "bundle")
    (directory / "runtime_records.jsonl").unlink()
    with pytest.raises(BundleError, match="runtime_records.jsonl"):
        load_evidence_bundle(directory)

    other = make_fixture().write(tmp_path / "other")
    manifest = json.loads((other / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["../outside.txt"] = "0" * 64
    (other / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="outside.txt"):
        load_evidence_bundle(other)


def test_an_unknown_schema_or_source_is_refused(tmp_path: Path) -> None:
    for key, value in (("schema", "soak-evidence-bundle/2"), ("source", "laptop")):
        directory = make_fixture().write(tmp_path / f"bundle-{key}")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifest[key] = value
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(BundleError, match=key):
            load_evidence_bundle(directory)


def test_the_loaded_bundle_exposes_the_manifest_and_the_parsed_files(
    trial_bundle: EvidenceBundle,
) -> None:
    assert trial_bundle.epoch_id == EPOCH_ID
    assert trial_bundle.window_start_utc == PIN
    assert trial_bundle.window_end_utc == WINDOW_END
    assert trial_bundle.source == "fixture"
    assert trial_bundle.pinned.parameter_set_hash == PARAMETER_HASH
    assert len(trial_bundle.runs) == 336
    assert len(trial_bundle.freeze_lines) == 336
    assert all(isinstance(r, RuntimeRecord) for r in trial_bundle.records)
    assert trial_bundle.evidence_gaps == ()
    assert "pinned_epoch.json" in trial_bundle.file_sha256


# --------------------------------------------------------------------------- #
# Test 3: labelled constants and the DECISIONS.md witness.
# --------------------------------------------------------------------------- #


def test_the_ratified_values_are_constants_labelled_decision_d061_item_d() -> None:
    assert TRIAL_CALENDAR_DAYS == 14
    assert MIN_COVERAGE_FRACTION == Decimal("0.95")
    assert PARITY_TOLERANCE == 0
    assert MIN_COVERAGE_FRACTION == coverage_module.CRITERION_MIN_FRACTION

    source = Path(inspect.getsourcefile(exit_module) or "").read_text(encoding="utf-8")
    lines = source.splitlines()
    for name in ("TRIAL_CALENDAR_DAYS", "MIN_COVERAGE_FRACTION", "PARITY_TOLERANCE"):
        index = next(i for i, line in enumerate(lines) if line.startswith(f"{name} "))
        assert "DECISION D061 item D, 2026-10-07" in lines[index - 1], name


def test_witness_decisions_md_still_carries_the_ratified_numbers() -> None:
    text = (REPO_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| D061 |"))
    assert "14 calendar days" in row
    assert "95 percent" in row
    assert "parity tolerance zero" in row


def test_the_module_source_has_no_numeric_literal_for_an_o07_threshold_name() -> None:
    names = {
        "max_ws_message_silence_seconds",
        "max_closed_bar_lateness_seconds",
        "continuous_uncovered_ceiling_seconds",
        "freeze_tick_grace_seconds",
        "grace_seconds",
    }
    for module in (exit_module, bundle_module):
        source = Path(inspect.getsourcefile(module) or "").read_text(encoding="utf-8")
        offenders: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.keyword) and node.arg in names:
                if isinstance(node.value, ast.Constant):
                    offenders.append(f"keyword {node.arg}")
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in names and node.value is not None:
                    offenders.append(f"field {node.target.id}")
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        offenders.append(f"assignment {target.id}")
            if isinstance(node, ast.FunctionDef):
                args = node.args
                positional = [*args.posonlyargs, *args.args]
                defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
                pairs = list(zip(positional, defaults, strict=True)) + list(
                    zip(args.kwonlyargs, args.kw_defaults, strict=True)
                )
                for arg, default in pairs:
                    if arg.arg in names and default is not None:
                        offenders.append(f"default {node.name}({arg.arg})")
        assert offenders == [], (module.__name__, offenders)


# --------------------------------------------------------------------------- #
# Test 4: the user's thresholds and the cron are required inputs.
# --------------------------------------------------------------------------- #


def test_evaluate_trial_requires_thresholds_and_cron_with_no_default(
    trial_bundle: EvidenceBundle,
) -> None:
    with pytest.raises(TypeError):
        evaluate_trial(trial_bundle, cron=CRON, symbols=(SYMBOL,))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_trial(trial_bundle, thresholds=THRESHOLDS, symbols=(SYMBOL,))  # type: ignore[call-arg]
    parameters = inspect.signature(evaluate_trial).parameters
    for name in ("thresholds", "cron", "symbols"):
        assert parameters[name].default is inspect.Parameter.empty


def test_a_tight_user_ceiling_fails_the_ceiling_criterion_only(
    trial_bundle: EvidenceBundle,
) -> None:
    tight = HealthThresholds(
        max_ws_message_silence_seconds=5400,
        max_closed_bar_lateness_seconds=60,
        continuous_uncovered_ceiling_seconds=3600,
        freeze_tick_grace_seconds=300,
    )
    evaluation = _evaluate(trial_bundle, thresholds=tight)
    assert not _result(evaluation, "continuous uncovered").passed
    assert _result(evaluation, "runtime coverage").passed


# --------------------------------------------------------------------------- #
# Criteria fail when the evidence says so.
# --------------------------------------------------------------------------- #


def _write_and_load(fixture: TrialFixture, directory: Path) -> EvidenceBundle:
    fixture.write(directory)
    return load_evidence_bundle(directory)


def test_a_window_that_is_not_14_calendar_days_from_the_pin_fails(tmp_path: Path) -> None:
    records, diff_lines, runs = trial_rows(hours=13 * 24)
    fixture = TrialFixture(
        records=records,
        diff_lines=diff_lines,
        runs=runs,
        window_end=PIN + timedelta(days=13),
    )
    evaluation = _evaluate(_write_and_load(fixture, tmp_path / "short"))
    assert not _result(evaluation, "trial window").passed


def test_coverage_below_95_percent_fails_and_says_so(tmp_path: Path) -> None:
    fixture = make_fixture()
    # The runtime stops for 20 hours (process down): about 94.05 percent covered.
    stop = PIN + timedelta(days=9)
    fixture.records = [
        row
        for row in fixture.records
        if not (stop < datetime.fromisoformat(row["occurred_at_utc"]) <= stop + timedelta(hours=20))
    ]
    fixture.records.append(record_row(RuntimeEventType.RUNTIME_STOP, stop))
    fixture.records.append(record_row(RuntimeEventType.RUNTIME_START, stop + timedelta(hours=20)))
    fixture.records.append(record_row(RuntimeEventType.WS_RECONNECT, stop + timedelta(hours=20)))
    evaluation = _evaluate(_write_and_load(fixture, tmp_path / "low"))
    coverage = _result(evaluation, "runtime coverage")
    assert not coverage.passed
    assert any("below" in line or "FAIL" in line for line in coverage.evidence)


def test_a_missing_scheduled_freeze_tick_fails_freeze_and_names_the_restart_rule(
    tmp_path: Path,
) -> None:
    fixture = make_fixture()
    missing_run = fixture.runs.pop(100)
    fixture.diff_lines = [
        line
        for line in fixture.diff_lines
        if line["run_metadata"]["run_id"] != str(missing_run["id"])
    ]
    evaluation = _evaluate(_write_and_load(fixture, tmp_path / "gap"))
    freeze = _result(evaluation, "freeze continuity")
    assert not freeze.passed
    assert "qualifying trial restarts with a new epoch pin (D065 item 4)" in "\n".join(
        freeze.evidence
    )


def test_a_changed_pinned_hash_or_a_second_epoch_id_fails(tmp_path: Path) -> None:
    changed = make_fixture()
    changed.diff_lines[200]["current_hash"] = "a" * 64
    evaluation = _evaluate(_write_and_load(changed, tmp_path / "hash"))
    assert not _result(evaluation, "pinned hash unchanged").passed

    second = make_fixture()
    second.diff_lines[300]["epoch_id"] = OTHER_EPOCH_ID
    evaluation = _evaluate(_write_and_load(second, tmp_path / "epoch"))
    assert not _result(evaluation, "single epoch").passed


def test_the_overall_verdict_needs_every_criterion(trial_bundle: EvidenceBundle) -> None:
    evaluation = _evaluate(trial_bundle)
    assert evaluation.passed == all(r.passed for g in evaluation.groups for r in g.results)


# --------------------------------------------------------------------------- #
# Test 5: the command line.
# --------------------------------------------------------------------------- #

RATIFIED_CONFIG = """\
[health]
max_ws_message_silence_seconds = 5400
max_closed_bar_lateness_seconds = 60
continuous_uncovered_ceiling_seconds = 14400
freeze_tick_grace_seconds = 300

[timing]
sibling_4h_wait_seconds = 30
constraint_snapshot_ttl_seconds = 600
exchange_info_refresh_seconds = 300
minute_poll_interval_seconds = 60
minute_close_lag_seconds = 0
healthcheck_max_bar_age_seconds = 7200
rest_backfill_depth_bars = 50

[account]
initial_equity = "1000"
risk_rate = "0.01"

[scope]
symbols = ["BTCUSDT"]
"""


def _load_script() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("evaluate_trial_soak", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow(tmp_path: Path) -> Path:
    path = tmp_path / "paper_freeze_check.yml"
    path.write_text(
        'name: Paper Freeze Check\non:\n  schedule:\n    - cron: "17 * * * *"\n'
        "  workflow_dispatch: {}\n",
        encoding="utf-8",
    )
    return path


def test_cli_writes_the_printed_lines_and_the_exit_code_follows_the_verdict(
    trial_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    config = tmp_path / "paper-runtime.toml"
    config.write_text(RATIFIED_CONFIG, encoding="utf-8")
    out = tmp_path / "evaluation.txt"
    code = script.main(
        [
            "--bundle",
            str(trial_dir),
            "--config",
            str(config),
            "--workflow",
            str(_workflow(tmp_path)),
            "--out",
            str(out),
        ]
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert out.read_text(encoding="utf-8") == printed
    assert "PASS  trial window" in printed


def test_cli_exits_one_when_a_criterion_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    fixture = make_fixture()
    fixture.diff_lines[10]["outcome"] = "REGISTRY_DIFF"
    bundle_dir = fixture.write(tmp_path / "bundle")
    config = tmp_path / "paper-runtime.toml"
    config.write_text(RATIFIED_CONFIG, encoding="utf-8")
    out = tmp_path / "evaluation.txt"
    code = script.main(
        [
            "--bundle",
            str(bundle_dir),
            "--config",
            str(config),
            "--workflow",
            str(_workflow(tmp_path)),
            "--out",
            str(out),
        ]
    )
    printed = capsys.readouterr().out
    assert code == 1
    assert out.read_text(encoding="utf-8") == printed
    assert "FAIL  freeze continuity" in printed


def test_cli_refuses_a_tampered_bundle_with_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    bundle_dir = make_fixture().write(tmp_path / "bundle", tamper="runtime_records.jsonl")
    config = tmp_path / "paper-runtime.toml"
    config.write_text(RATIFIED_CONFIG, encoding="utf-8")
    code = script.main(
        [
            "--bundle",
            str(bundle_dir),
            "--config",
            str(config),
            "--workflow",
            str(_workflow(tmp_path)),
            "--out",
            str(tmp_path / "evaluation.txt"),
        ]
    )
    assert code == 2
    assert "runtime_records.jsonl" in capsys.readouterr().err
    assert not (tmp_path / "evaluation.txt").exists()
