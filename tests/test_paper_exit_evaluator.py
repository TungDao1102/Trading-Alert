"""Trial exit-criteria evaluator (Phase 16, plan 16-25; D-23, L-04, REV-01, REV-17, REV-18).

Task 1 (tracer): a fixture bundle of a 14-day trial is loaded, verified against the manifest
sha256 values and evaluated criterion by criterion with the ratified constants and the
user-owned thresholds only. The fixture is built here, from the same line shapes the exporter of
plan 16-30 writes; its proof class is FAKE because its manifest source is "fixture".
"""

from __future__ import annotations

import ast
import dataclasses
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
from src.core.types import Candle
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
    BackfillRule,
    ParityReplay,
    ProofClass,
    TrialEvaluation,
    evaluate_trial,
    parity_criterion,
    read_backfill_rule,
)
from src.paper.runtime_state import RuntimeRecord
from src.paper.surface import context_record, gate_record
from src.paper.vocabulary import GapReason, RuntimeEventType

from tests.test_paper_decision_surface import _bar_context, _case_input, _per_bar_context
from tests.test_paper_runtime_pipeline import Fixture as PipelineFixture

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "evaluate_trial_soak.py"
QD_DECISION = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "16-paper-runtime-composition"
    / "decisions"
    / "16-DEC-Q-D.md"
)

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


def _candle(close: datetime, interval: str) -> Candle:
    open_time = close + ONE_MS - timedelta(hours=1 if interval == "1h" else 4)
    return Candle(
        symbol=SYMBOL,
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=close,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
    )


def _bar_payload(close: datetime, tick: datetime, interval: str) -> dict[str, Any]:
    """A processed-bar payload as the pipeline writes it. With fewer than 200 4h bars the
    warm-up gate rejects every 1h bar, so the recorded surface is a feed-gate record."""
    candle = _candle(close, interval)
    surface = (
        gate_record(candle, "WARMUP_INSUFFICIENT") if interval == "1h" else context_record(candle)
    )
    return {
        "source": "LIVE_WS",
        "tick_time_utc": _iso(tick),
        "bar": {
            "symbol": SYMBOL,
            "interval": interval,
            "open_time_utc": _iso(candle.open_time_utc),
            "close_time_utc": _iso(close),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "10",
        },
        "stage": surface.stage,
        "reason_code": surface.reason_code,
        "plan_hash": None,
        "surface": surface.to_dict(),
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
    stop_at = pin + (STOP_AT - PIN)
    restart_at = pin + (RESTART_AT - PIN)
    drop_at = pin + (DROP_AT - PIN)
    reconnect_at = pin + (RECONNECT_AT - PIN)
    records: list[dict[str, Any]] = [
        record_row(RuntimeEventType.RUNTIME_START, pin, epoch_id=epoch_id),
        record_row(RuntimeEventType.WS_RECONNECT, pin, epoch_id=epoch_id),
    ]
    for k in range(1, hours + 1):
        tick = pin + timedelta(hours=k)
        close = tick - ONE_MS
        down = with_disturbances and (drop_at < tick <= reconnect_at)
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
        records.append(record_row(RuntimeEventType.RUNTIME_STOP, stop_at, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.RUNTIME_START, restart_at, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.WS_RECONNECT, restart_at, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.WS_DISCONNECT, drop_at, epoch_id=epoch_id))
        records.append(record_row(RuntimeEventType.WS_RECONNECT, reconnect_at, epoch_id=epoch_id))

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


_PARITY: list[ParityReplay] = []


def fixture_parity() -> ParityReplay:
    """Replay inputs for the synthetic fixture: any context of the symbol (the fixture never
    leaves the warm-up gate, so the context is read for its symbol only)."""
    if not _PARITY:
        case = _case_input()
        context = _bar_context(case, PIN)
        _PARITY.append(ParityReplay(context=lambda _candle: context))
    return _PARITY[0]


def _evaluate(
    bundle: EvidenceBundle,
    *,
    thresholds: HealthThresholds = THRESHOLDS,
    backfill_rule: BackfillRule = BackfillRule.HISTORY_ONLY,
    parity: ParityReplay | None = None,
) -> TrialEvaluation:
    return evaluate_trial(
        bundle,
        thresholds=thresholds,
        cron=CRON,
        symbols=(SYMBOL,),
        backfill_rule=backfill_rule,
        parity=fixture_parity() if parity is None else parity,
    )


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
    for name in ("thresholds", "cron", "symbols", "backfill_rule", "parity"):
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
            "--q-d-decision",
            str(QD_DECISION),
            "--out",
            str(out),
        ],
        parity=fixture_parity(),
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
            "--q-d-decision",
            str(QD_DECISION),
            "--out",
            str(out),
        ],
        parity=fixture_parity(),
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
            "--q-d-decision",
            str(QD_DECISION),
            "--out",
            str(tmp_path / "evaluation.txt"),
        ]
    )
    assert code == 2
    assert "runtime_records.jsonl" in capsys.readouterr().err
    assert not (tmp_path / "evaluation.txt").exists()


def test_without_the_replay_seam_the_command_line_does_not_pass_parity(
    trial_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command line has no replay context of its own: parity is NOT EVALUATED, never PASS."""
    script = _load_script()
    config = tmp_path / "paper-runtime.toml"
    config.write_text(RATIFIED_CONFIG, encoding="utf-8")
    code = script.main(
        [
            "--bundle",
            str(trial_dir),
            "--config",
            str(config),
            "--workflow",
            str(_workflow(tmp_path)),
            "--q-d-decision",
            str(QD_DECISION),
            "--out",
            str(tmp_path / "evaluation.txt"),
        ]
    )
    printed = capsys.readouterr().out
    assert code == 1
    assert "FAIL  parity" in printed
    assert "NOT EVALUATED" in printed


def test_the_command_line_requires_the_q_d_decision_file(trial_dir: Path, tmp_path: Path) -> None:
    script = _load_script()
    config = tmp_path / "paper-runtime.toml"
    config.write_text(RATIFIED_CONFIG, encoding="utf-8")
    with pytest.raises(SystemExit) as raised:
        script.main(
            [
                "--bundle",
                str(trial_dir),
                "--config",
                str(config),
                "--workflow",
                str(_workflow(tmp_path)),
                "--out",
                str(tmp_path / "evaluation.txt"),
            ]
        )
    assert raised.value.code == 2


# =========================================================================== #
# Task 2: parity, gap, restart, duplicate, missing-row, test-signal and epoch checks.
# =========================================================================== #


def _names(evaluation: TrialEvaluation) -> list[str]:
    return [r.name for g in evaluation.groups for r in g.results]


def _evaluated_with(tmp_path: Path, mutate: Any = None, **kwargs: Any) -> TrialEvaluation:
    fixture = make_fixture()
    if mutate is not None:
        mutate(fixture)
    return _evaluate(_write_and_load(fixture, tmp_path / "bundle"), **kwargs)


def _row(
    fixture: TrialFixture, event_type: RuntimeEventType, k: int, interval: str
) -> dict[str, Any]:
    """The record row of an event type at the close of the k-th hour of the trial."""
    close = _iso(PIN + timedelta(hours=k) - ONE_MS)
    matches = [
        r
        for r in fixture.records
        if r["event_type"] == event_type.value
        and r["interval"] == interval
        and (r["payload"].get("expected_close_utc") or r["occurred_at_utc"]) == close
    ]
    assert len(matches) == 1
    return matches[0]


def test_the_all_pass_fixture_passes_every_criterion_of_every_group(
    trial_bundle: EvidenceBundle,
) -> None:
    evaluation = _evaluate(trial_bundle)
    failing = [r.name for g in evaluation.groups for r in g.results if not r.passed]
    assert failing == []
    assert evaluation.passed
    for expected in (
        "gaps explained",
        "restart warm-up",
        "no duplicate signal",
        "no missing journal row",
        "no test signal",
        "runtime records of one epoch",
        "parity",
    ):
        assert any(expected in name for name in _names(evaluation)), expected


# ---- Test 1: parity, tolerance zero --------------------------------------------------------- #


@pytest.fixture(scope="module")
def parity_world() -> tuple[PipelineFixture, tuple[RuntimeRecord, ...], ParityReplay]:
    from tests.test_paper_decision_surface import PASSING_BAR

    fx = PipelineFixture()
    fx.warm_up()
    fx.pipeline.handle([fx.live()], now_utc=fx.now)
    records = tuple(fx.bar_records())
    replay = ParityReplay(
        context=_per_bar_context(fx.case),
        history_bars=(*fx.setup[:PASSING_BAR], *fx.context),
    )
    return fx, records, replay


def _with_payload(record: RuntimeRecord, **changes: Any) -> RuntimeRecord:
    payload = dict(record.payload)
    payload.update(changes)
    return RuntimeRecord(
        event_type=record.event_type,
        epoch_id=record.epoch_id,
        occurred_at_utc=record.occurred_at_utc,
        symbol=record.symbol,
        interval=record.interval,
        payload=payload,
    )


def test_parity_replays_the_recorded_bars_and_matches_the_live_surface(
    parity_world: tuple[PipelineFixture, tuple[RuntimeRecord, ...], ParityReplay],
) -> None:
    _, records, replay = parity_world
    result = parity_criterion(records, replay)
    assert result.passed, result.evidence
    text = "\n".join(result.evidence)
    assert "risk_passed" in text
    assert f"tolerance {PARITY_TOLERANCE}" in text


def test_one_altered_recorded_feature_digest_fails_parity_and_names_the_bar_close(
    parity_world: tuple[PipelineFixture, tuple[RuntimeRecord, ...], ParityReplay],
) -> None:
    fx, records, replay = parity_world
    [record] = records
    surface = dict(record.payload["surface"])
    surface["feature_digest"] = "0" * 64
    altered = _with_payload(record, surface=surface)
    result = parity_criterion((altered,), replay)
    assert not result.passed
    text = "\n".join(result.evidence)
    assert fx.last_1h.close_time_utc.isoformat() in text
    assert "feature_digest" in text


def test_parity_without_a_replay_context_is_not_evaluated_and_never_passes(
    parity_world: tuple[PipelineFixture, tuple[RuntimeRecord, ...], ParityReplay],
) -> None:
    _, records, _ = parity_world
    result = parity_criterion(records, None)
    assert not result.passed
    assert "NOT EVALUATED" in "\n".join(result.evidence)
    empty = parity_criterion((), fixture_parity())
    assert not empty.passed
    assert "no processed bar" in "\n".join(empty.evidence)


def test_a_stale_tick_is_replayed_from_the_recorded_tick_time(
    parity_world: tuple[PipelineFixture, tuple[RuntimeRecord, ...], ParityReplay],
) -> None:
    fx, records, replay = parity_world
    [record] = records
    late_tick = (fx.last_1h.close_time_utc + timedelta(seconds=61)).isoformat()
    stale_surface = gate_record(fx.last_1h, "DATA_STALE").to_dict()
    honest = _with_payload(record, tick_time_utc=late_tick, surface=stale_surface)
    assert parity_criterion((honest,), replay).passed
    # The same late tick with an evaluated surface is a decision the freshness gate forbids.
    dishonest = _with_payload(record, tick_time_utc=late_tick)
    result = parity_criterion((dishonest,), replay)
    assert not result.passed
    assert "DATA_STALE" in "\n".join(result.evidence)


# ---- Test 2: gaps, no fabricated bar -------------------------------------------------------- #


@pytest.mark.parametrize("reason", ["UNKNOWN", "SOMETHING_ELSE", None])
def test_a_gap_without_a_real_reason_code_fails(tmp_path: Path, reason: str | None) -> None:
    def mutate(fixture: TrialFixture) -> None:
        gap = _row(fixture, RuntimeEventType.PAPER_GAP, 173, "1h")
        if reason is None:
            del gap["payload"]["reason"]
        else:
            gap["payload"]["reason"] = reason

    evaluation = _evaluated_with(tmp_path, mutate)
    result = _result(evaluation, "gaps explained")
    assert not result.passed
    assert (PIN + timedelta(hours=173) - ONE_MS).isoformat() in "\n".join(result.evidence)


@pytest.mark.parametrize("source", ["REST_WARMUP", "REST_BACKFILL", "SOMEWHERE"])
def test_an_evaluated_bar_from_warmup_or_backfill_is_late_or_fabricated(
    tmp_path: Path, source: str
) -> None:
    def mutate(fixture: TrialFixture) -> None:
        _row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, 40, "1h")["payload"]["source"] = source

    result = _result(_evaluated_with(tmp_path, mutate), "gaps explained")
    assert not result.passed
    assert "late or fabricated bar" in "\n".join(result.evidence)


def test_a_bar_processed_before_it_closed_is_fabricated(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        row = _row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, 40, "1h")
        row["payload"]["tick_time_utc"] = _iso(PIN + timedelta(hours=40) - timedelta(minutes=5))

    result = _result(_evaluated_with(tmp_path, mutate), "gaps explained")
    assert not result.passed
    assert "late or fabricated bar" in "\n".join(result.evidence)


def test_the_q_d_rule_is_read_from_the_decision_file_and_never_defaulted(tmp_path: Path) -> None:
    assert read_backfill_rule(QD_DECISION) is BackfillRule.HISTORY_ONLY
    fresh = tmp_path / "q-d.md"
    fresh.write_text("option: fresh-within-bound\ndecided by: user\n", encoding="utf-8")
    assert read_backfill_rule(fresh) is BackfillRule.FRESH_WITHIN_BOUND
    for text in ("decided by: user\n", "option: something-else\n", ""):
        bad = tmp_path / "bad.md"
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="option"):
            read_backfill_rule(bad)
    with pytest.raises(FileNotFoundError):
        read_backfill_rule(tmp_path / "missing.md")
    assert inspect.signature(read_backfill_rule).parameters["path"].default is (
        inspect.Parameter.empty
    )


def test_a_backfill_bar_is_not_accepted_under_fresh_within_bound_without_a_ratified_bound(
    tmp_path: Path,
) -> None:
    def mutate(fixture: TrialFixture) -> None:
        row = _row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, 40, "1h")
        row["payload"]["source"] = "REST_BACKFILL"

    evaluation = _evaluated_with(tmp_path, mutate, backfill_rule=BackfillRule.FRESH_WITHIN_BOUND)
    result = _result(evaluation, "gaps explained")
    assert not result.passed
    assert "no ratified bound" in "\n".join(result.evidence)


# ---- Test 3: restart, duplicates, missing rows ---------------------------------------------- #


def test_a_bar_that_closed_while_the_process_was_down_is_never_evaluated(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        close = RESTART_AT - timedelta(minutes=10)
        tick = RESTART_AT + timedelta(minutes=1)
        payload = _bar_payload(close, tick, "1h")
        payload["stage"] = "risk_passed"
        payload["reason_code"] = "OK"
        fixture.records.append(
            record_row(
                RuntimeEventType.PAPER_BAR_PROCESSED,
                close,
                symbol=SYMBOL,
                interval="1h",
                payload=payload,
            )
        )

    result = _result(_evaluated_with(tmp_path, mutate), "restart warm-up")
    assert not result.passed
    assert "closed while the process was down" in "\n".join(result.evidence)


def test_an_evaluated_bar_after_the_restart_passes_the_restart_check(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        row = _row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, 100, "1h")
        row["payload"]["stage"] = "risk_passed"
        row["payload"]["reason_code"] = "OK"

    result = _result(_evaluated_with(tmp_path, mutate), "restart warm-up")
    assert result.passed, result.evidence


def test_two_records_for_one_bar_are_a_duplicate_signal(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        original = _row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, 10, "1h")
        fixture.records.append(json.loads(json.dumps(original)))

    result = _result(_evaluated_with(tmp_path, mutate), "no duplicate signal")
    assert not result.passed
    assert "duplicate signal" in "\n".join(result.evidence)


def test_one_signal_id_on_two_bars_is_a_duplicate_signal(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        for k in (10, 11):
            row = _row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, k, "1h")
            row["payload"]["surface"]["signal_id"] = "sig-1"

    result = _result(_evaluated_with(tmp_path, mutate), "no duplicate signal")
    assert not result.passed
    assert "sig-1" in "\n".join(result.evidence)


def test_an_expected_close_with_neither_a_bar_nor_a_gap_is_a_missing_journal_row(
    tmp_path: Path,
) -> None:
    def mutate(fixture: TrialFixture) -> None:
        fixture.records.remove(_row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, 50, "1h"))
        fixture.records.remove(_row(fixture, RuntimeEventType.PAPER_GAP, 173, "1h"))

    result = _result(_evaluated_with(tmp_path, mutate), "no missing journal row")
    assert not result.passed
    text = "\n".join(result.evidence)
    assert "missing journal row" in text
    assert (PIN + timedelta(hours=50) - ONE_MS).isoformat() in text
    assert (PIN + timedelta(hours=173) - ONE_MS).isoformat() in text


# ---- Test 4: REV-03, REV-18, SC8 ------------------------------------------------------------ #


def test_a_test_only_record_inside_the_soak_window_fails_the_trial(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        row = _row(fixture, RuntimeEventType.PAPER_BAR_PROCESSED, 60, "1h")
        row["payload"]["test_only"] = True

    evaluation = _evaluated_with(tmp_path, mutate)
    result = _result(evaluation, "no test signal")
    assert not result.passed
    assert "test signal inside the soak window" in "\n".join(result.evidence)
    assert not evaluation.passed


def test_an_evidence_gap_record_fails_freeze_and_names_the_restart_rule(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        fixture.gaps.append(
            {
                "slot_utc": _iso(PIN + timedelta(days=3, minutes=17)),
                "schedule": CRON,
                "reason": "NO_RUN_FOUND",
                "detected_at_utc": _iso(PIN + timedelta(days=3, hours=2)),
                "run_id": None,
            }
        )

    result = _result(_evaluated_with(tmp_path, mutate), "freeze continuity")
    assert not result.passed
    assert "qualifying trial restarts with a new epoch pin (D065 item 4)" in "\n".join(
        result.evidence
    )


def test_a_runtime_record_of_another_epoch_inside_the_window_fails(tmp_path: Path) -> None:
    def mutate(fixture: TrialFixture) -> None:
        fixture.records.append(
            record_row(
                RuntimeEventType.WS_RECONNECT, PIN + timedelta(days=5), epoch_id=OTHER_EPOCH_ID
            )
        )

    result = _result(_evaluated_with(tmp_path, mutate), "runtime records of one epoch")
    assert not result.passed
    assert OTHER_EPOCH_ID in "\n".join(result.evidence)


# ---- Test 5: two separate result groups ----------------------------------------------------- #


def test_freeze_and_runtime_criteria_read_disjoint_inputs() -> None:
    freeze_fields = {f.name for f in dataclasses.fields(exit_module._FreezeInputs)}
    runtime_fields = {f.name for f in dataclasses.fields(exit_module._RuntimeInputs)}
    runtime_only = {"records", "coverage", "parity", "backfill_rule", "symbols"}
    freeze_only = {"diff_records", "report", "pinned_hash", "pinned_epoch_id"}
    assert runtime_only <= runtime_fields and not (runtime_only & freeze_fields)
    assert freeze_only <= freeze_fields and not (freeze_only & runtime_fields)


def test_removing_all_runtime_records_changes_no_freeze_result_and_the_reverse(
    trial_bundle: EvidenceBundle,
) -> None:
    base = {g.name: g for g in _evaluate(trial_bundle).groups}

    no_runtime = {
        g.name: g for g in _evaluate(dataclasses.replace(trial_bundle, records=())).groups
    }
    assert no_runtime["freeze integrity"] == base["freeze integrity"]
    assert not no_runtime["runtime health"].results[0].passed

    stripped = dataclasses.replace(
        trial_bundle, freeze_lines=(), diff_records=(), runs=(), evidence_gaps=()
    )
    no_freeze = _evaluate(stripped)
    assert {g.name: g for g in no_freeze.groups}["runtime health"] == base["runtime health"]
    assert not no_freeze.freeze.qualifying_from_pin


def test_the_grace_reaches_only_the_freeze_reconciler() -> None:
    source = Path(inspect.getsourcefile(exit_module) or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    uses = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "freeze_tick_grace_seconds"
    ]
    assert len(uses) == 1
    calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "freeze_evidence_report"
        and any(kw.value is uses[0] for kw in call.keywords)
    ]
    assert len(calls) == 1


# ---- Test 6: earlier epoch is auxiliary (REV-18) -------------------------------------------- #

E1 = "1" * 64
E2 = "2" * 64
E2_PIN = PIN + timedelta(days=20)


def _two_epoch_fixture(epoch: str) -> tuple[TrialFixture, dict[str, Any]]:
    """Inputs holding E1 (ended by a missing freeze tick) and E2 (pinned 20 days later)."""
    records1, lines1, runs1 = trial_rows(epoch_id=E1, pin=PIN)
    missing = runs1.pop(100)
    lines1 = [ln for ln in lines1 if ln["run_metadata"]["run_id"] != str(missing["id"])]
    records2, lines2, runs2 = trial_rows(epoch_id=E2, pin=E2_PIN)
    for run in runs2:
        run["id"] += 5000
    for line in lines2:
        line["run_metadata"]["run_id"] = str(int(line["run_metadata"]["run_id"]) + 5000)
    slot1 = datetime.fromisoformat(missing["created_at"]) - timedelta(seconds=20)
    gap1 = {
        "slot_utc": _iso(slot1),
        "schedule": CRON,
        "reason": "NO_RUN_FOUND",
        "detected_at_utc": _iso(slot1 + timedelta(hours=2)),
        "run_id": None,
    }
    pin = PIN if epoch == E1 else E2_PIN
    fixture = TrialFixture(
        epoch_id=epoch,
        pin=pin,
        window_end=pin + timedelta(days=14),
        records=records1 + records2,
        diff_lines=lines1 + lines2,
        runs=runs1 + runs2,
        gaps=[gap1],
    )
    return fixture, gap1


def _bytes_of(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def test_earlier_epoch_evidence_is_auxiliary_and_never_qualifies_the_new_trial(
    tmp_path: Path,
) -> None:
    fixture, _ = _two_epoch_fixture(E2)
    directory = fixture.write(tmp_path / "e2")
    before = _bytes_of(directory)
    bundle = load_evidence_bundle(directory)
    snapshot = (bundle.records, bundle.freeze_lines, bundle.runs, bundle.evidence_gaps)

    evaluation = _evaluate(bundle)
    assert evaluation.passed, [
        (r.name, r.evidence) for g in evaluation.groups for r in g.results if not r.passed
    ]
    text = evaluation.render()
    assert "auxiliary evidence (not qualifying)" in text
    assert f"runtime records of earlier epoch {E1}" in text
    assert "EVIDENCE_GAP records of earlier epochs: 1" in text
    assert "freeze lines at or before the pin: 335" in text
    assert "earlier-epoch evidence cannot complete the freeze criterion of the new trial" in text
    # Nothing was dropped or edited: the files and the parsed inputs are unchanged.
    assert _bytes_of(directory) == before
    assert (bundle.records, bundle.freeze_lines, bundle.runs, bundle.evidence_gaps) == snapshot
    # No E1 item satisfied a slot or coloured an interval of E2.
    assert evaluation.freeze.satisfied_slots[0] > E2_PIN
    assert len(evaluation.freeze.slots) == 336
    assert evaluation.coverage.window_start_utc == E2_PIN


def test_evaluating_the_same_inputs_as_epoch_e1_reproduces_its_evidence_gap(
    tmp_path: Path,
) -> None:
    fixture, gap1 = _two_epoch_fixture(E1)
    evaluation = _evaluate(_write_and_load(fixture, tmp_path / "e1"))
    freeze = _result(evaluation, "freeze continuity")
    assert not freeze.passed
    assert [g.slot_utc for g in evaluation.freeze.gaps] == [
        datetime.fromisoformat(gap1["slot_utc"])
    ]
    assert "qualifying trial restarts with a new epoch pin (D065 item 4)" in "\n".join(
        freeze.evidence
    )
    # E2's lines and records are auxiliary to E1 and do not break E1's other criteria.
    assert _result(evaluation, "single epoch").passed
    assert _result(evaluation, "runtime records of one epoch").passed


# ---- Test 7: observations are report-only --------------------------------------------------- #


def test_observations_are_report_only_and_change_no_verdict(tmp_path: Path) -> None:
    loaded_base = _write_and_load(make_fixture(), tmp_path / "base")
    changed = make_fixture()
    ticks = [
        row
        for row in changed.records
        if row["event_type"] == RuntimeEventType.PAPER_TICK_STATS.value
    ]
    for row in ticks:
        row["payload"]["duration_ms"] = 9000
        row["payload"]["queue_depth_before"] = 40
    ticks[0]["payload"]["dropped_total"] = 1
    ticks[0]["payload"]["dropped_by_reason"] = {"FUTURE_CLOSE": 1}
    loaded_changed = _write_and_load(changed, tmp_path / "changed")

    first, second = _evaluate(loaded_base), _evaluate(loaded_changed)
    assert first.groups == second.groups
    assert first.observations != second.observations
    assert any("FUTURE_CLOSE=1" in line for line in second.observations)
    assert any("max 9000" in line for line in second.observations)
    assert "observations (not criteria)" in second.render()
    assert first.passed and second.passed
