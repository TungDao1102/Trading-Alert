"""Edge-adapter tests for the analytics file loaders (Phase 10, plan 10-09, D-03).

Task 1 (tracer): the real registry (`params/<family>/*.toml`) and the real family sheets
(`docs/research/families/*.md`) yield the kill-gate independence facts with no free-text
flag, and the pure evaluator runs end to end against the committed repo.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.analytics_files import (
    REPORTS_ROOT,
    DecisionsFile,
    DecisionsFileError,
    EvidenceFile,
    EvidenceFileError,
    ExperimentFlags,
    FamilyDecision,
    FamilyScan,
    PathConfinementError,
    confine_output_dir,
    load_decisions_file,
    load_evidence_file,
    load_universe_file,
    read_protocol_text,
    scan_family_facts,
)
from src.analytics.clock import clock_start_from_protocol
from src.analytics.family import (
    REQUIRED_SLOTS,
    FamilyStatus,
    independent_family_ids,
)
from src.analytics.killgate import ResetRecord, evaluate
from src.analytics.types import OutcomeContext
from src.backtest.experiment import ExperimentRecord
from src.backtest.validator import validate_trade_record
from src.domain.canonical import sha256_hex
from src.domain.enums import KillGateState
from src.domain.registry import load_parameter_set
from src.paper.attribution import AttributionKind

from tests.backtest_case_helpers import make_experiment_record

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEETS_ROOT = REPO_ROOT / "docs" / "research" / "families"
EVALUATED_AT = datetime(2026, 9, 29, tzinfo=UTC)
EMPTY_DECISIONS = DecisionsFile(families=(), resets=(), recorded_terminal=None)

_FAMILIES = ("breakout-retest", "range-mr", "trend-pullback")
_EXPECTED_CANDIDATE_IDS = {
    "breakout-retest": (
        "baseline-v1",
        "baseline-v2",
        "baseline-v3",
        "baseline-v4",
        "baseline-v5",
        "baseline-v6",
    ),
    "range-mr": ("baseline-v1", "baseline-v2", "baseline-v4", "baseline-v5", "baseline-v6"),
    "trend-pullback": (
        "baseline-v1",
        "baseline-v2",
        "baseline-v3",
        "baseline-v4",
        "baseline-v5",
        "baseline-v6",
    ),
}
# Plan 16-45: the 16 research-run-1 grid points of each family are registered candidate sets too.
_RESEARCH_RUN_1_LETTER = {"breakout-retest": "b", "range-mr": "c", "trend-pullback": "a"}
_EXPECTED_CANDIDATE_IDS = {
    family_id: (
        *ids,
        *(f"research-run-1-{_RESEARCH_RUN_1_LETTER[family_id]}{n:02d}" for n in range(1, 17)),
    )
    for family_id, ids in _EXPECTED_CANDIDATE_IDS.items()
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
    cost_overrides: dict[str, str] | None = None,
    parameter_set_id: str = "baseline-v1",
) -> ExperimentRecord:
    """A typed record from the shared factory (plan 14-15) with the scan-relevant identity."""
    record: ExperimentRecord = make_experiment_record(
        experiment_id=exp_char * 64,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set_hash,
        run_type=run_type,
        cost_overrides=cost_overrides,
    )
    return record


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
    (tmp_path / "trend-pullback.md").write_bytes((SHEETS_ROOT / "range-mr.md").read_bytes())
    scan = _scan(sheets_root=tmp_path)
    assert _family(scan, "range-mr").sheet_sha256 == _family(scan, "trend-pullback").sheet_sha256
    independent, non_independent = independent_family_ids(scan.families)
    assert non_independent == ("trend-pullback",)
    assert independent == ("breakout-retest", "range-mr")


def test_scan_sheet_hash_is_independent_of_line_endings(tmp_path: Path) -> None:
    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    _copy_sheets(lf_root)
    crlf_root.mkdir()
    for family_id in _FAMILIES:
        content = (lf_root / f"{family_id}.md").read_bytes().replace(b"\r\n", b"\n")
        (lf_root / f"{family_id}.md").write_bytes(content)
        (crlf_root / f"{family_id}.md").write_bytes(content.replace(b"\n", b"\r\n"))
    lf_hashes = [f.sheet_sha256 for f in _scan(sheets_root=lf_root).families]
    crlf_scan = _scan(sheets_root=crlf_root)
    assert lf_hashes == [f.sheet_sha256 for f in crlf_scan.families]
    assert [f.sheet_slots_present for f in crlf_scan.families] == [REQUIRED_SLOTS] * 3


def test_scan_candidate_experiments_map_by_parameter_set_hash() -> None:
    trend_v1 = load_parameter_set("trend-pullback", "baseline-v1").parameter_set_hash
    range_v1 = load_parameter_set("range-mr", "baseline-v1").parameter_set_hash
    experiments = (
        _experiment("1", parameter_set_hash=trend_v1),
        _experiment("2", parameter_set_hash=range_v1, cost_overrides={"fee_rate_entry": "0.0009"}),
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


@pytest.mark.parametrize("family_id", ["trend_pullback", "Trend-Pullback", "retired-family"])
def test_scan_decision_for_an_unregistered_family_fails_closed(family_id: str) -> None:
    """CR-02: a recorded decision matching no params/ directory is never silently dropped."""
    decisions = DecisionsFile(
        families=(
            FamilyDecision(
                family_id=family_id,
                status=FamilyStatus.TESTED_PASS,
                decision_ref="DEC-typo",
                decided_at_utc=datetime(2026, 12, 1, tzinfo=UTC),
                development_experiment_ids=("5" * 64,),
                validation_experiment_ids=("6" * 64,),
            ),
        ),
        resets=(),
        recorded_terminal=None,
    )
    with pytest.raises(DecisionsFileError, match="unregistered family") as info:
        _scan(decisions=decisions)
    assert family_id in str(info.value)


def test_scan_missing_flags_default_to_none_reproducibility_and_false_others() -> None:
    trend_v1 = load_parameter_set("trend-pullback", "baseline-v1").parameter_set_hash
    scan = _scan(experiments=(_experiment("7", parameter_set_hash=trend_v1),))
    facts = dict(scan.gate_facts)["trend-pullback"]
    assert facts.reproducibility_verified is None
    assert facts.uncertainty_report_present is False
    assert facts.baseline_compared is False


# --------------------------------------------------------------------------- #
# Task 2 - evidence / decisions / universe loaders (fail closed) and confinement
# --------------------------------------------------------------------------- #

LOADERS = REPO_ROOT / "tests" / "fixtures" / "phase10" / "loaders"
EVIDENCE_SAMPLE = LOADERS / "evidence_sample.json"
DECISIONS_SAMPLE = LOADERS / "decisions_sample.json"
UNIVERSE_SAMPLE = LOADERS / "universe_sample.json"
COMMITTED_DECISIONS = REPO_ROOT / "docs" / "research" / "kill_gate_decisions.json"


def _sample(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc: Any, name: str = "input.json") -> Path:
    target = tmp_path / name
    target.write_text(json.dumps(doc), encoding="utf-8")
    return target


def _evidence_with(tmp_path: Path, mutate: Any) -> Path:
    doc = copy.deepcopy(_sample(EVIDENCE_SAMPLE))
    mutate(doc)
    return _write(tmp_path, doc)


def _decisions_with(tmp_path: Path, mutate: Any) -> Path:
    doc = copy.deepcopy(_sample(DECISIONS_SAMPLE))
    mutate(doc)
    return _write(tmp_path, doc)


def test_evidence_sample_loads_into_typed_objects() -> None:
    evidence = load_evidence_file(EVIDENCE_SAMPLE)
    assert isinstance(evidence, EvidenceFile)
    assert len(evidence.backtest) == 1
    entry = evidence.backtest[0]
    assert entry.experiment.run_type == "CANDIDATE"
    assert entry.experiment.data_manifest_hash is None  # written before protocol v2.2.0
    assert entry.experiment.time_range_start_utc.tzinfo is not None
    assert [t.trade_id for t in entry.trades] == ["T-1", "T-2"]
    assert entry.trades[0].entry_price == Decimal("100.00")
    assert isinstance(entry.trades[0].entry_time_utc, datetime)
    assert entry.trades[1].outcome_kind == "REJECT"
    assert entry.contexts["T-1"] == OutcomeContext(
        intended_entry_price=Decimal("100.00"), regime="TREND", vol_regime=None
    )
    assert entry.flags == ExperimentFlags(
        reproducibility_verified=True,
        has_uncertainty_report=False,
        baseline_summaries_present=True,
    )
    assert [record.attribution for record in evidence.paper] == [
        AttributionKind.SYSTEM,
        AttributionKind.OPPORTUNITY,
    ]
    assert evidence.paper[1].approval_acted_at_utc is None
    assert evidence.research_universe == ("BTCUSDT", "ETHUSDT")


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda t, e, d: t[0].update(strategy_version="v9.9.9"), "strategy_version"),
        (lambda t, e, d: t[0].update(parameter_set_hash="b" * 64), "parameter_set_hash"),
        (
            lambda t, e, d: t[0].update(exit_time_utc="2026-04-01T00:00:00+00:00"),
            "time range",
        ),
        (lambda t, e, d: e.update(fallback_count=1), "fallback"),
        (lambda t, e, d: e.update(end_of_data_count=1), "END_OF_DATA"),
        (
            lambda t, e, d: e.update(result_summary_json=json.dumps({"trades_digest": "c" * 64})),
            "trades_digest",
        ),
        (lambda t, e, d: d.update(research_universe=["ETHUSDT"]), "research universe"),
    ],
)
def test_evidence_trades_that_do_not_belong_to_the_experiment_are_refused(
    tmp_path: Path, mutate: Any, match: str
) -> None:
    def apply(doc: dict[str, Any]) -> None:
        entry = doc["backtest"][0]
        mutate(entry["trades"], entry["experiment"], doc)

    with pytest.raises(EvidenceFileError, match=match):
        load_evidence_file(_evidence_with(tmp_path, apply))


def test_evidence_sample_universe_hash_matches_the_sorted_universe() -> None:
    evidence = load_evidence_file(EVIDENCE_SAMPLE)
    expected = sha256_hex({"universe": sorted(evidence.research_universe)})
    assert evidence.backtest[0].experiment.universe_hash == expected


def test_evidence_fixture_files_avoid_research_gate_tripwires() -> None:
    for path in LOADERS.glob("*.json"):
        assert not path.name.startswith(("experiment", "backtest"))
        assert '"parameters"' not in path.read_text(encoding="utf-8")


def test_evidence_wrong_schema_fails_closed(tmp_path: Path) -> None:
    path = _evidence_with(tmp_path, lambda doc: doc.update(schema="analytics-evidence/3"))
    with pytest.raises(EvidenceFileError, match="schema"):
        load_evidence_file(path)


# --------------------------------------------------------------------------- #
# Plan 14-15 Task 3 - analytics-evidence/2: typed experiment fields, v2 trades, v1 refused
# --------------------------------------------------------------------------- #

_TYPED_EXPERIMENT_KEYS = (
    "no_trade_counts",
    "intrabar_tie_break",
    "timeframe",
    "context_timeframe",
    "parameter_values",
    "cost_values",
    "simulator_semantics_version",
    "code_commit",
    "code_dirty",
    "fallback_count",
    "end_of_data_count",
    "strategy_window_bars",
    "context_window_bars",
    "allowed_gaps",
    "split_role",
    "split_start_utc",
    "split_end_utc",
)


def test_the_evidence_schema_is_version_two() -> None:
    from src.adapters.analytics_files import EVIDENCE_SCHEMA

    assert EVIDENCE_SCHEMA == "analytics-evidence/2"
    assert _sample(EVIDENCE_SAMPLE)["schema"] == "analytics-evidence/2"


def test_evidence_version_one_files_are_refused_naming_the_expected_schema(
    tmp_path: Path,
) -> None:
    path = _evidence_with(tmp_path, lambda doc: doc.update(schema="analytics-evidence/1"))
    with pytest.raises(EvidenceFileError, match="analytics-evidence/2"):
        load_evidence_file(path)


def test_the_v2_sample_carries_every_typed_experiment_field_and_validated_trades() -> None:
    document = _sample(EVIDENCE_SAMPLE)
    experiment = document["backtest"][0]["experiment"]
    for key in _TYPED_EXPERIMENT_KEYS:
        assert key in experiment, key
    evidence = load_evidence_file(EVIDENCE_SAMPLE)
    entry = evidence.backtest[0]
    record = entry.experiment
    assert record.simulator_semantics_version == "2.0.0"
    assert record.intrabar_tie_break == "STOP_FIRST"
    assert record.code_version == record.code_commit  # a clean tree
    assert record.code_dirty is False
    assert record.split_role in ("DEVELOPMENT", "VALIDATION", "HOLDOUT")
    assert dict(record.cost_values)["funding_convention"] == "MARK_NOTIONAL_SIGNED_V1"
    assert record.parameter_values and record.no_trade_counts
    assert record.time_range_start_utc >= record.split_start_utc
    for trade in entry.trades:
        validate_trade_record(trade)  # raises on any violated invariant
    filled = entry.trades[0]
    assert filled.signal_close_utc is not None and filled.entry_time_utc is not None
    assert filled.entry_time_utc > filled.signal_close_utc
    assert filled.planned_quantity == Decimal("1")
    assert filled.exit_kind == "TP2"
    assert entry.trades[1].entry_kind == "REJECT"


@pytest.mark.parametrize("key", _TYPED_EXPERIMENT_KEYS)
def test_evidence_experiment_missing_a_typed_field_fails_closed(tmp_path: Path, key: str) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        del doc["backtest"][0]["experiment"][key]

    with pytest.raises(EvidenceFileError, match=key):
        load_evidence_file(_evidence_with(tmp_path, mutate))


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("code_dirty", "yes"),
        ("split_role", "TRAIN"),
        ("simulator_semantics_version", "1.0.0"),
        ("intrabar_tie_break", "TP_FIRST"),
        ("fallback_count", -1),
        ("fallback_count", True),
        ("no_trade_counts", {"RR_TOO_LOW": -1}),
        ("no_trade_counts", [["RR_TOO_LOW", 1]]),
        ("parameter_values", {}),
        ("parameter_values", {"swing_lookback": 20}),
        ("cost_values", {"fee_rate_entry": "0.0009"}),
        ("code_commit", "abc"),
        ("split_start_utc", "2026-01-02T00:00:00+00:00"),
        ("split_end_utc", "2026-02-01T00:00:00"),
        ("allowed_gaps", [{"series": "funding"}]),
        ("allowed_gaps", "none"),
    ],
)
def test_evidence_experiment_invalid_typed_value_fails_closed(
    tmp_path: Path, key: str, bad: Any
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["experiment"][key] = bad

    with pytest.raises(EvidenceFileError, match="experiment"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_experiment_unexpected_key_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["experiment"]["parameters"] = {"swing_lookback": "20"}

    with pytest.raises(EvidenceFileError, match="parameters"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_a_v1_shaped_trade_in_a_v2_file_fails_closed(tmp_path: Path) -> None:
    def old_exit_kind(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][0]["exit_kind"] = "TP1"

    def old_entry_kind(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][1]["entry_kind"] = "TOUCH_NO_FILL"

    def no_signal_close(doc: dict[str, Any]) -> None:
        del doc["backtest"][0]["trades"][0]["signal_close_utc"]

    def entry_before_signal_close(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][0]["signal_close_utc"] = "2026-01-05T10:00:01+00:00"

    for mutate in (old_exit_kind, old_entry_kind, no_signal_close, entry_before_signal_close):
        with pytest.raises(EvidenceFileError, match="trade record"):
            load_evidence_file(_evidence_with(tmp_path, mutate))


@pytest.mark.parametrize(
    "key", ["planned_quantity", "tp1_quantity", "tp1_price", "tp1_time_utc", "signal_close_utc"]
)
def test_evidence_new_trade_fields_are_parsed_before_the_shared_parser(
    tmp_path: Path, key: str
) -> None:
    secret = "postgresql://user:hunter2@host/db"

    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][0][key] = secret

    with pytest.raises(EvidenceFileError, match=key) as info:
        load_evidence_file(_evidence_with(tmp_path, mutate))
    assert "hunter2" not in str(info.value)


def test_a_record_serialized_with_to_dict_loads_back_equal(tmp_path: Path) -> None:
    record = make_experiment_record(
        code_commit="a" * 40,
        code_version="a" * 40,
        split_role="VALIDATION",
        fallback_count=0,
        end_of_data_count=0,
    )

    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["experiment"] = record.to_dict()

    loaded = load_evidence_file(_evidence_with(tmp_path, mutate)).backtest[0].experiment
    assert loaded == record


def test_the_optional_manifest_hash_key_loads_and_is_validated(tmp_path: Path) -> None:
    def add(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["experiment"]["data_manifest_hash"] = "c" * 64

    loaded = load_evidence_file(_evidence_with(tmp_path, add)).backtest[0].experiment
    assert loaded.data_manifest_hash == "c" * 64

    secret = "C" * 64
    for bad in (None, 7, secret, "c" * 63):

        def mutate(doc: dict[str, Any], bad: object = bad) -> None:
            doc["backtest"][0]["experiment"]["data_manifest_hash"] = bad

        with pytest.raises(EvidenceFileError) as info:
            load_evidence_file(_evidence_with(tmp_path, mutate))
        assert secret not in str(info.value)

    def other_key(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["experiment"]["data_manifest_sha"] = "c" * 64

    with pytest.raises(EvidenceFileError, match="unexpected key"):
        load_evidence_file(_evidence_with(tmp_path, other_key))


@pytest.mark.parametrize("manifest_hash_value", ["d" * 64, None])
def test_a_record_with_or_without_the_manifest_hash_loads_back_equal(
    tmp_path: Path, manifest_hash_value: str | None
) -> None:
    record = make_experiment_record(
        code_commit="a" * 40,
        code_version="a" * 40,
        split_role="VALIDATION",
        fallback_count=0,
        end_of_data_count=0,
        data_manifest_hash=manifest_hash_value,
    )

    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["experiment"] = record.to_dict()

    loaded = load_evidence_file(_evidence_with(tmp_path, mutate)).backtest[0].experiment
    assert loaded == record
    assert loaded.data_manifest_hash == manifest_hash_value


def _json_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {key for child in node.values() for key in _json_keys(child)}
    if isinstance(node, list):
        return {key for child in node for key in _json_keys(child)}
    return set()


def test_the_evidence_sample_has_no_research_gate_keys_at_any_depth() -> None:
    keys = _json_keys(_sample(EVIDENCE_SAMPLE))
    assert not ({"parameters", "parameters_json"} & keys)
    assert "parameter_values" in keys


def test_evidence_missing_top_level_key_fails_closed(tmp_path: Path) -> None:
    path = _evidence_with(tmp_path, lambda doc: doc.pop("paper"))
    with pytest.raises(EvidenceFileError, match="paper"):
        load_evidence_file(path)


def test_evidence_unparseable_decimal_names_the_field_not_the_value(tmp_path: Path) -> None:
    secret = "postgresql://user:hunter2@host/db"

    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][0]["entry_price"] = secret

    with pytest.raises(EvidenceFileError, match="entry_price") as info:
        load_evidence_file(_evidence_with(tmp_path, mutate))
    assert secret not in str(info.value)
    assert "hunter2" not in str(info.value)


def test_evidence_negative_realized_risk_fails_closed(tmp_path: Path) -> None:
    """WR-15: risk is a magnitude; a negative value is malformed, never an R sign flip."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][0]["realized_risk"] = "-10.00"

    with pytest.raises(EvidenceFileError, match="realized_risk"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_naive_datetime_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][0]["entry_time_utc"] = "2026-01-05T10:00:00"

    with pytest.raises(EvidenceFileError, match="entry_time_utc"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_non_utc_datetime_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["paper"][0]["signal_detected_at_utc"] = "2026-02-01T08:00:00+07:00"

    with pytest.raises(EvidenceFileError, match="signal_detected_at_utc"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_unknown_attribution_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["paper"][0]["attribution"] = "mystery"

    with pytest.raises(EvidenceFileError, match="attribution"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_experiment_construction_error_is_wrapped(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["experiment"]["run_type"] = "LIVE"

    with pytest.raises(EvidenceFileError, match="experiment"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_paper_construction_error_is_wrapped(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["paper"][0]["epoch_id"] = ""

    with pytest.raises(EvidenceFileError, match="paper"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_duplicate_trade_id_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["backtest"][0]["trades"][1]["trade_id"] = "T-1"

    with pytest.raises(EvidenceFileError, match="trade_id"):
        load_evidence_file(_evidence_with(tmp_path, mutate))


def test_evidence_unreadable_or_non_json_file_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvidenceFileError):
        load_evidence_file(bad)
    with pytest.raises(EvidenceFileError):
        load_evidence_file(tmp_path / "missing.json")


def test_decisions_sample_loads_sorted_and_typed() -> None:
    decisions = load_decisions_file(DECISIONS_SAMPLE)
    assert isinstance(decisions, DecisionsFile)
    assert [d.family_id for d in decisions.families] == ["trend-pullback"]
    assert decisions.families[0].status is FamilyStatus.TESTED_FAIL
    assert decisions.families[0].decided_at_utc == datetime(2026, 3, 15, tzinfo=UTC)
    assert decisions.resets == (
        ResetRecord(
            operator_id="op-fixture",
            decision_ref="DEC-FIXTURE-reset-a",
            occurred_at_utc=datetime(2026, 4, 1, tzinfo=UTC),
        ),
        ResetRecord(
            operator_id="op-fixture",
            decision_ref="DEC-FIXTURE-reset-b",
            occurred_at_utc=datetime(2026, 5, 2, tzinfo=UTC),
        ),
    )
    assert decisions.recorded_terminal is not None
    assert decisions.recorded_terminal.state == "INSUFFICIENT_EDGE"
    assert decisions.recorded_terminal.families_at_record == (
        "breakout-retest",
        "range-mr",
        "trend-pullback",
    )


def test_committed_decision_record_loads_empty() -> None:
    decisions = load_decisions_file(COMMITTED_DECISIONS)
    assert decisions.families == ()
    assert decisions.resets == ()
    assert decisions.recorded_terminal is None


def test_decisions_wrong_schema_fails_closed(tmp_path: Path) -> None:
    path = _decisions_with(tmp_path, lambda doc: doc.update(schema="kill-gate-decisions/9"))
    with pytest.raises(DecisionsFileError, match="schema"):
        load_decisions_file(path)


def test_decisions_unknown_status_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["families"][0]["status"] = "PASSED"

    with pytest.raises(DecisionsFileError, match="status"):
        load_decisions_file(_decisions_with(tmp_path, mutate))


@pytest.mark.parametrize(
    "field",
    [
        "decision_ref",
        "decided_at_utc",
        "development_experiment_ids",
        "validation_experiment_ids",
    ],
)
def test_decisions_tested_without_required_field_fails_closed(tmp_path: Path, field: str) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        entry = doc["families"][0]
        entry[field] = [] if field.endswith("_ids") else None

    with pytest.raises(DecisionsFileError, match=field):
        load_decisions_file(_decisions_with(tmp_path, mutate))


def test_decisions_tested_with_blank_decision_ref_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["families"][0]["decision_ref"] = "   "

    with pytest.raises(DecisionsFileError, match="decision_ref"):
        load_decisions_file(_decisions_with(tmp_path, mutate))


def test_decisions_reset_without_operator_id_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["resets"][0]["operator_id"] = ""

    with pytest.raises(DecisionsFileError, match="operator_id"):
        load_decisions_file(_decisions_with(tmp_path, mutate))


def test_decisions_reset_without_decision_ref_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        del doc["resets"][0]["decision_ref"]

    with pytest.raises(DecisionsFileError, match="decision_ref"):
        load_decisions_file(_decisions_with(tmp_path, mutate))


def test_decisions_recorded_terminal_state_must_be_insufficient_edge(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["recorded_terminal"]["state"] = "WITHIN_BUDGET"

    with pytest.raises(DecisionsFileError, match="state"):
        load_decisions_file(_decisions_with(tmp_path, mutate))


def test_decisions_recorded_terminal_timestamp_is_parsed_as_utc() -> None:
    """CR-01: the committed terminal mirror carries a real UTC instant, not free text."""
    terminal = load_decisions_file(DECISIONS_SAMPLE).recorded_terminal
    assert terminal is not None
    assert terminal.recorded_at_utc == datetime(2026, 4, 1, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["2026-04-01T00:00:00", "2026-04-01T07:00:00+07:00", "soon"])
def test_decisions_recorded_terminal_non_utc_timestamp_fails_closed(
    tmp_path: Path, bad: str
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["recorded_terminal"]["recorded_at_utc"] = bad

    with pytest.raises(DecisionsFileError, match="recorded_at_utc"):
        load_decisions_file(_decisions_with(tmp_path, mutate))


def test_decisions_naive_datetime_fails_closed(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["families"][0]["decided_at_utc"] = "2026-03-15T00:00:00"

    with pytest.raises(DecisionsFileError, match="decided_at_utc"):
        load_decisions_file(_decisions_with(tmp_path, mutate))


def test_decisions_not_tested_entry_needs_no_decision_fields(tmp_path: Path) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["families"] = [
            {
                "family_id": "range-mr",
                "status": "NOT_TESTED",
                "decision_ref": None,
                "decided_at_utc": None,
                "development_experiment_ids": [],
                "validation_experiment_ids": [],
            }
        ]

    decisions = load_decisions_file(_decisions_with(tmp_path, mutate))
    assert decisions.families[0].status is FamilyStatus.NOT_TESTED


def test_universe_sample_is_sorted_and_deduplicated() -> None:
    assert load_universe_file(UNIVERSE_SAMPLE) == ("BTCUSDT", "ETHUSDT")


def test_universe_accepts_a_bare_array_and_an_empty_universe(tmp_path: Path) -> None:
    assert load_universe_file(_write(tmp_path, ["SOLUSDT", "BNBUSDT"])) == ("BNBUSDT", "SOLUSDT")
    assert load_universe_file(_write(tmp_path, {"research_universe": []}, "e.json")) == ()


@pytest.mark.parametrize("bad", ["btcusdt", "BTC", "BTC/USDT", "A" * 21, 5])
def test_universe_invalid_symbol_fails_closed(tmp_path: Path, bad: Any) -> None:
    with pytest.raises(EvidenceFileError, match="symbol"):
        load_universe_file(_write(tmp_path, {"research_universe": [bad]}))


def test_universe_wrong_shape_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(EvidenceFileError, match="research_universe"):
        load_universe_file(_write(tmp_path, {"other": []}))


def test_confine_default_is_the_reports_root() -> None:
    assert confine_output_dir(None) == REPORTS_ROOT
    assert REPORTS_ROOT == Path("data") / "reports"


def test_confine_accepts_the_root_and_paths_inside_it(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    assert confine_output_dir(root, reports_root=root) == root.resolve()
    inside = root / "run-1" / "nested"
    assert confine_output_dir(inside, reports_root=root) == inside.resolve()


def test_confine_rejects_dotdot_traversal(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    with pytest.raises(PathConfinementError):
        confine_output_dir(root / ".." / "elsewhere", reports_root=root)
    with pytest.raises(PathConfinementError):
        confine_output_dir(root / "run" / ".." / ".." / "x", reports_root=root)


def test_confine_rejects_absolute_path_outside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    outside = tmp_path / "outside"
    with pytest.raises(PathConfinementError):
        confine_output_dir(outside, reports_root=root)


def test_confine_rejects_sibling_with_shared_name_prefix(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    with pytest.raises(PathConfinementError):
        confine_output_dir(tmp_path / "reports-evil", reports_root=root)


def test_confine_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    link = root / "link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable on this platform: {type(exc).__name__}")
    with pytest.raises(PathConfinementError):
        confine_output_dir(link / "run", reports_root=root)
