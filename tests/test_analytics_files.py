"""Edge-adapter tests for the analytics file loaders (Phase 10, plan 10-09, D-03).

Task 1 (tracer): the real registry (`params/<family>/*.toml`) and the real family sheets
(`docs/research/families/*.md`) yield the kill-gate independence facts with no free-text
flag, and the pure evaluator runs end to end against the committed repo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.adapters.analytics_files import (
    DecisionsFile,
    ExperimentFlags,
    FamilyDecision,
    FamilyScan,
    read_protocol_text,
    scan_family_facts,
)
from src.analytics.clock import clock_start_from_protocol
from src.analytics.family import (
    REQUIRED_SLOTS,
    FamilyStatus,
    independent_family_ids,
)
from src.analytics.killgate import evaluate
from src.backtest.experiment import ExperimentRecord
from src.domain.enums import KillGateState
from src.domain.registry import load_parameter_set

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEETS_ROOT = REPO_ROOT / "docs" / "research" / "families"
EVALUATED_AT = datetime(2026, 9, 29, tzinfo=UTC)
EMPTY_DECISIONS = DecisionsFile(families=(), resets=(), recorded_terminal=None)

_FAMILIES = ("breakout-retest", "range-mr", "trend-pullback")
_EXPECTED_CANDIDATE_IDS = {
    "breakout-retest": ("baseline-v1", "baseline-v2", "baseline-v3"),
    "range-mr": ("baseline-v1", "baseline-v2"),
    "trend-pullback": ("baseline-v1", "baseline-v2", "baseline-v3"),
}
_BASELINE_IDS = ("baseline-no-trade-v1", "baseline-simple-trend-v1")


def _scan(
    *,
    sheets_root: Path = SHEETS_ROOT,
    decisions: DecisionsFile = EMPTY_DECISIONS,
    experiments: tuple[ExperimentRecord, ...] = (),
    flags: dict[str, ExperimentFlags] | None = None,
) -> FamilyScan:
    return scan_family_facts(
        sheets_root=sheets_root,
        decisions=decisions,
        experiments=experiments,
        flags_by_experiment=flags or {},
    )


def _experiment(
    exp_char: str,
    *,
    parameter_set_hash: str,
    run_type: str = "CANDIDATE",
    cost_model_hash: str | None = None,
    parameter_set_id: str = "baseline-v1",
) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=exp_char * 64,
        strategy_version="v2.0.0",
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set_hash,
        data_snapshot_id="d" * 64,
        code_version="test-code",
        cost_model_hash=cost_model_hash if cost_model_hash is not None else "c" * 64,
        time_range_start_utc=datetime(2026, 1, 1, tzinfo=UTC),
        time_range_end_utc=datetime(2026, 2, 1, tzinfo=UTC),
        universe_hash="e" * 64,
        run_type=run_type,
        result_summary_json="{}",
        notes="",
    )


def _family(scan: FamilyScan, family_id: str) -> Any:
    return next(f for f in scan.families if f.family_id == family_id)


def _copy_sheets(target: Path, *, skip: tuple[str, ...] = ()) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for family_id in _FAMILIES:
        if family_id in skip:
            continue
        (target / f"{family_id}.md").write_bytes((SHEETS_ROOT / f"{family_id}.md").read_bytes())


# --------------------------------------------------------------------------- #
# Task 1 - tracer + scan behaviour
# --------------------------------------------------------------------------- #


def test_tracer_real_repo_scan_feeds_evaluator() -> None:
    scan = _scan()

    assert tuple(f.family_id for f in scan.families) == _FAMILIES
    for family in scan.families:
        assert family.sheet_slots_present == REQUIRED_SLOTS
        assert family.sheet_sha256 is not None
        assert family.status is FamilyStatus.NOT_TESTED
        assert family.decision_ref is None
        assert family.experiment_ids == ()
    assert len({f.sheet_sha256 for f in scan.families}) == 3

    all_hashes: list[str] = []
    for family_id, ids in _EXPECTED_CANDIDATE_IDS.items():
        expected = tuple(
            sorted(load_parameter_set(family_id, pid).parameter_set_hash for pid in ids)
        )
        assert _family(scan, family_id).candidate_param_set_hashes == expected
        all_hashes.extend(expected)
    assert len(all_hashes) == len(set(all_hashes)), "candidate hash sets must be disjoint"

    baseline_hashes = {
        load_parameter_set("trend-pullback", pid).parameter_set_hash for pid in _BASELINE_IDS
    }
    assert baseline_hashes.isdisjoint(all_hashes)

    independent, non_independent = independent_family_ids(scan.families)
    assert independent == _FAMILIES
    assert non_independent == ()

    assert tuple(fid for fid, _ in scan.gate_facts) == _FAMILIES
    assert scan.unknown_experiment_ids == ()

    clock = clock_start_from_protocol(read_protocol_text(REPO_ROOT))
    verdict = evaluate(families=scan.families, clock=clock, evaluated_at_utc=EVALUATED_AT)
    assert verdict.state is KillGateState.WITHIN_BUDGET
    assert verdict.families_tested == 0
    assert verdict.independent_family_ids == _FAMILIES


def test_read_protocol_text_reads_the_frozen_protocol() -> None:
    text = read_protocol_text(REPO_ROOT)
    assert "**Frozen on:**" in text
    assert text.startswith("# Research Protocol")


def test_scan_missing_sheet_breaks_independence(tmp_path: Path) -> None:
    _copy_sheets(tmp_path, skip=("range-mr",))
    scan = _scan(sheets_root=tmp_path)
    missing = _family(scan, "range-mr")
    assert missing.sheet_sha256 is None
    assert missing.sheet_slots_present == ()
    independent, non_independent = independent_family_ids(scan.families)
    assert non_independent == ("range-mr",)
    assert independent == ("breakout-retest", "trend-pullback")


def test_scan_partial_slots_break_independence(tmp_path: Path) -> None:
    _copy_sheets(tmp_path, skip=("range-mr",))
    (tmp_path / "range-mr.md").write_text(
        "# Range\n\n## 1. One\n\ntext\n\n## 2. Two\n\n## 3. Three\n", encoding="utf-8"
    )
    scan = _scan(sheets_root=tmp_path)
    partial = _family(scan, "range-mr")
    assert partial.sheet_slots_present == (1, 2, 3)
    assert partial.sheet_sha256 is not None
    independent, non_independent = independent_family_ids(scan.families)
    assert non_independent == ("range-mr",)
    assert "range-mr" not in independent


def test_scan_duplicate_sheet_content_breaks_the_later_family(tmp_path: Path) -> None:
    _copy_sheets(tmp_path, skip=("trend-pullback",))
    (tmp_path / "trend-pullback.md").write_bytes(
        (SHEETS_ROOT / "range-mr.md").read_bytes()
    )
    scan = _scan(sheets_root=tmp_path)
    assert _family(scan, "range-mr").sheet_sha256 == _family(scan, "trend-pullback").sheet_sha256
    independent, non_independent = independent_family_ids(scan.families)
    assert non_independent == ("trend-pullback",)
    assert independent == ("breakout-retest", "range-mr")


def test_scan_candidate_experiments_map_by_parameter_set_hash() -> None:
    trend_v1 = load_parameter_set("trend-pullback", "baseline-v1").parameter_set_hash
    range_v1 = load_parameter_set("range-mr", "baseline-v1").parameter_set_hash
    experiments = (
        _experiment("1", parameter_set_hash=trend_v1),
        _experiment("2", parameter_set_hash=range_v1, cost_model_hash="b" * 64),
    )
    scan = _scan(experiments=experiments)
    assert _family(scan, "trend-pullback").experiment_ids == ("1" * 64,)
    assert _family(scan, "range-mr").experiment_ids == ("2" * 64,)
    assert _family(scan, "breakout-retest").experiment_ids == ()
    assert scan.unknown_experiment_ids == ()
    facts = dict(scan.gate_facts)
    assert facts["trend-pullback"].cost_model_hash_present is True
    assert facts["breakout-retest"].cost_model_hash_present is False
    assert facts["breakout-retest"].tested is False


def test_scan_unknown_parameter_set_hash_is_listed_never_guessed() -> None:
    unknown = _experiment("3", parameter_set_hash="9" * 64)
    scan = _scan(experiments=(unknown,))
    assert scan.unknown_experiment_ids == ("3" * 64,)
    assert all(f.experiment_ids == () for f in scan.families)


def test_scan_baseline_experiments_are_excluded_and_not_unknown() -> None:
    baseline_hash = load_parameter_set("trend-pullback", "baseline-no-trade-v1").parameter_set_hash
    baseline = _experiment(
        "4",
        parameter_set_hash=baseline_hash,
        run_type="BASELINE_NO_TRADE",
        parameter_set_id="baseline-no-trade-v1",
    )
    scan = _scan(experiments=(baseline,))
    assert all(f.experiment_ids == () for f in scan.families)
    assert scan.unknown_experiment_ids == ()


def test_scan_flags_feed_gate_facts_and_decisions_set_status() -> None:
    trend_v1 = load_parameter_set("trend-pullback", "baseline-v1").parameter_set_hash
    dev = _experiment("5", parameter_set_hash=trend_v1)
    val = _experiment("6", parameter_set_hash=trend_v1)
    decided = datetime(2026, 12, 1, tzinfo=UTC)
    decisions = DecisionsFile(
        families=(
            FamilyDecision(
                family_id="trend-pullback",
                status=FamilyStatus.TESTED_FAIL,
                decision_ref="DEC-2026-12-trend-fail",
                decided_at_utc=decided,
                development_experiment_ids=("5" * 64,),
                validation_experiment_ids=("6" * 64,),
            ),
        ),
        resets=(),
        recorded_terminal=None,
    )
    flags = {
        "5" * 64: ExperimentFlags(
            reproducibility_verified=True,
            has_uncertainty_report=True,
            baseline_summaries_present=False,
        ),
        "6" * 64: ExperimentFlags(
            reproducibility_verified=True,
            has_uncertainty_report=False,
            baseline_summaries_present=True,
        ),
    }
    scan = _scan(decisions=decisions, experiments=(dev, val), flags=flags)
    trend = _family(scan, "trend-pullback")
    assert trend.status is FamilyStatus.TESTED_FAIL
    assert trend.decision_ref == "DEC-2026-12-trend-fail"
    assert trend.decided_at_utc == decided
    assert trend.development_experiment_ids == ("5" * 64,)
    assert trend.validation_experiment_ids == ("6" * 64,)
    facts = dict(scan.gate_facts)["trend-pullback"]
    assert facts.tested is True
    assert facts.reproducibility_verified is True
    assert facts.uncertainty_report_present is True
    assert facts.baseline_compared is True


def test_scan_missing_flags_default_to_none_reproducibility_and_false_others() -> None:
    trend_v1 = load_parameter_set("trend-pullback", "baseline-v1").parameter_set_hash
    scan = _scan(experiments=(_experiment("7", parameter_set_hash=trend_v1),))
    facts = dict(scan.gate_facts)["trend-pullback"]
    assert facts.reproducibility_verified is None
    assert facts.uncertainty_report_present is False
    assert facts.baseline_compared is False
