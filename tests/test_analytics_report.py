"""Composed journal-depth report tests (Phase 10, plan 10-08, D-01, D-04, D-05).

RED first: these tests are authored before `src/analytics/report.py` exists. The report
is one pure function of frozen inputs: three fixed EvidenceBlocks (BACKTEST, PAPER, LIVE,
never pooled), stamped with a single digest. Fixture: `tests/fixtures/phase10/report_composite`.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from src.analytics.approval_delay import SYNTHETIC_LAG_LABEL
from src.analytics.clock import (
    PROTOCOL_CLOCK_SOURCE,
    PROTOCOL_FREEZE_COMMIT_AUTHOR_DATE,
    ClockStart,
)
from src.analytics.excursion import EXCURSION_WINDOW_CONVENTION
from src.analytics.family import FamilyEvidence, FamilyStatus
from src.analytics.gates import FamilyGateFacts, GateCell
from src.analytics.inputs import normalize_backtest
from src.analytics.lifecycle import normalize_backtest_lifecycle, normalize_paper_lifecycle
from src.analytics.no_trade import no_trade_from_paper
from src.analytics.report import (
    EvidenceBlock,
    EvidenceInputs,
    FamilyGateRow,
    IncompleteEntry,
    InputNote,
    JournalDepthReport,
    KillGateSection,
    ReportInputs,
    build_evidence_block,
    build_journal_depth_report,
    build_kill_gate_section,
    live_posture_from_events,
)
from src.analytics.stats import r_value
from src.analytics.types import (
    ANALYTICS_SCHEMA_VERSION,
    MIN_RESAMPLES,
    AnalyticsInputError,
    EvidenceKind,
    IncompleteReason,
    NoTradeRecord,
)
from src.backtest.experiment import ExperimentRecord
from src.domain.canonical import canonical_scalars
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent

from tests.phase10_helpers import (
    load_expected,
    load_input,
    make_candles,
    make_outcome,
    make_paper_record,
    make_trade_record,
    parse_utc,
)

CASE = "report_composite"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def build_clock(raw: dict[str, Any]) -> ClockStart:
    return ClockStart(
        start_utc=parse_utc(raw["start_utc"]),
        source=raw["source"],
        freeze_commit=raw["freeze_commit"],
        commit_author_date=raw["commit_author_date"],
    )


def build_backtest_inputs(raw: dict[str, Any]) -> EvidenceInputs:
    trades = [make_trade_record(**trade) for trade in raw["trades"]]
    normalized = normalize_backtest(trades)
    candles_by_symbol: dict[str, list[Any]] = {}
    for candle in make_candles(raw["candles"]):
        candles_by_symbol.setdefault(candle.symbol, []).append(candle)
    realized = {
        outcome.signal_id: value
        for outcome in normalized.outcomes
        if outcome.signal_id is not None
        and (value := r_value(outcome.realized_pnl, outcome.realized_risk)) is not None
    }
    return EvidenceInputs(
        kind=EvidenceKind.BACKTEST,
        outcomes=normalized.outcomes,
        lifecycle=normalize_backtest_lifecycle(normalized.outcomes),
        no_trades=normalized.rejects,
        candles_by_symbol=candles_by_symbol,
        realized_r_by_signal=realized,
        experiments=tuple(build_experiment(item) for item in raw.get("experiments", [])),
        notes=tuple(
            InputNote(item["input_name"], item["reason"], item["count"])
            for item in raw.get("notes", [])
        ),
    )


def build_experiment(raw: dict[str, Any]) -> ExperimentRecord:
    fields = dict(raw)
    for name in ("time_range_start_utc", "time_range_end_utc"):
        fields[name] = parse_utc(fields[name])
    return ExperimentRecord(**fields)


def build_family(raw: dict[str, Any]) -> FamilyEvidence:
    decided = raw["decided_at_utc"]
    return FamilyEvidence(
        family_id=raw["family_id"],
        sheet_sha256=raw["sheet_sha256"],
        sheet_slots_present=tuple(raw["sheet_slots_present"]),
        candidate_param_set_hashes=tuple(raw["candidate_param_set_hashes"]),
        experiment_ids=tuple(raw["experiment_ids"]),
        status=FamilyStatus(raw["status"]),
        decision_ref=raw["decision_ref"],
        decided_at_utc=None if decided is None else parse_utc(decided),
        development_experiment_ids=tuple(raw["development_experiment_ids"]),
        validation_experiment_ids=tuple(raw["validation_experiment_ids"]),
    )


def build_event(raw: dict[str, Any]) -> JournalEvent:
    fields = dict(raw)
    fields["occurred_at_utc"] = parse_utc(fields["occurred_at_utc"])
    return JournalEvent(**fields)


def build_paper_inputs(raw: dict[str, Any]) -> EvidenceInputs:
    records = [make_paper_record(row) for row in raw["records"]]
    return EvidenceInputs(
        kind=EvidenceKind.PAPER,
        lifecycle=normalize_paper_lifecycle(records),
        no_trades=tuple(no_trade_from_paper(records)),
        paper_epoch_ids=tuple(sorted({record.epoch_id for record in records})),
    )


def build_report_inputs(case: str = CASE) -> ReportInputs:
    data = load_input(case)
    return ReportInputs(
        as_of_utc=parse_utc(data["as_of_utc"]),
        backtest=build_backtest_inputs(data["backtest"]),
        paper=build_paper_inputs(data["paper"]),
        live=EvidenceInputs(kind=EvidenceKind.LIVE),
        research_symbols=tuple(data["research_symbols"]),
        expected_universe_hash=data.get("expected_universe_hash"),
        clock=build_clock(data["clock"]),
        journal_events=tuple(build_event(item) for item in data.get("journal_events", [])),
        families=tuple(build_family(item) for item in data.get("families", [])),
        family_gate_facts={
            family_id: FamilyGateFacts(tested=False, **facts)
            for family_id, facts in data.get("family_gate_facts", {}).items()
        },
    )


def build_report(case: str = CASE, *, resamples: int = MIN_RESAMPLES, base_seed: int | None = None):  # type: ignore[no-untyped-def]
    data = load_input(case)
    return build_journal_depth_report(
        build_report_inputs(case),
        base_seed=data["base_seed"] if base_seed is None else base_seed,
        resamples=resamples,
    )


def test_tracer_composes_three_kinds_and_digest() -> None:
    report = build_report()
    expected = load_expected(CASE)
    assert report.schema_version == ANALYTICS_SCHEMA_VERSION
    assert [block.kind for block in report.evidence] == [
        EvidenceKind.BACKTEST,
        EvidenceKind.PAPER,
        EvidenceKind.LIVE,
    ]
    assert [block.kind.value for block in report.evidence] == expected["evidence_kinds"]
    backtest, paper, live = report.evidence
    assert backtest.has_data is True
    assert paper.has_data is True
    assert live.has_data is False
    assert backtest.core.n == expected["backtest_core_n"] == 2
    assert backtest.core.n_r_valued == 2
    assert str(backtest.core.mean_r.value) == expected["backtest_mean_r"]
    assert paper.core.n == 0
    assert paper.no_trade.total.all_n == expected["paper_no_trade_total"] == 2
    # LIVE renders as a valid no-data block: n 0 everywhere.
    assert live.core.n == 0
    assert live.excursion.n_outcomes == 0
    assert live.execution_quality.n_records == 0
    assert live.dual_universe.live5_empty is True
    assert live.dual_universe.live5.n == 0
    assert live.dual_universe.research.n == 0
    assert live.no_trade.total.all_n == 0
    assert report.digest() == report.digest()
    assert HEX64.match(report.digest())
    assert report.digest() == expected["report_digest"]


def test_report_carries_injected_time_seed_and_resamples() -> None:
    data = load_input(CASE)
    report = build_report()
    assert report.as_of_utc == parse_utc(data["as_of_utc"])
    assert report.base_seed == data["base_seed"]
    assert report.resamples == MIN_RESAMPLES


def test_empty_evidence_is_a_valid_no_data_block() -> None:
    block = build_evidence_block(
        EvidenceInputs(kind=EvidenceKind.LIVE),
        research_symbols=("BTCUSDT",),
        expected_universe_hash=None,
        base_seed=1,
        resamples=MIN_RESAMPLES,
    )
    assert isinstance(block, EvidenceBlock)
    assert block.kind is EvidenceKind.LIVE
    assert block.has_data is False
    assert block.core.n == 0
    assert block.core.mean_r.value is None
    assert HEX64.match(block.digest())


def test_cross_kind_elements_raise() -> None:
    paper_outcome = make_outcome(evidence="PAPER", trade_id="P-1")
    with pytest.raises(AnalyticsInputError):
        build_evidence_block(
            EvidenceInputs(kind=EvidenceKind.BACKTEST, outcomes=(paper_outcome,)),
            research_symbols=("BTCUSDT",),
            expected_universe_hash=None,
            base_seed=1,
            resamples=MIN_RESAMPLES,
        )
    live_lifecycle = build_paper_inputs(load_input(CASE)["paper"]).lifecycle
    with pytest.raises(AnalyticsInputError):
        build_evidence_block(
            EvidenceInputs(kind=EvidenceKind.LIVE, lifecycle=live_lifecycle),
            research_symbols=("BTCUSDT",),
            expected_universe_hash=None,
            base_seed=1,
            resamples=MIN_RESAMPLES,
        )
    paper_no_trades = build_paper_inputs(load_input(CASE)["paper"]).no_trades
    with pytest.raises(AnalyticsInputError):
        build_evidence_block(
            EvidenceInputs(kind=EvidenceKind.BACKTEST, no_trades=paper_no_trades),
            research_symbols=("BTCUSDT",),
            expected_universe_hash=None,
            base_seed=1,
            resamples=MIN_RESAMPLES,
        )


def test_report_inputs_reject_a_mis_slotted_evidence_kind() -> None:
    data = load_input(CASE)
    with pytest.raises(AnalyticsInputError):
        ReportInputs(
            as_of_utc=parse_utc(data["as_of_utc"]),
            backtest=EvidenceInputs(kind=EvidenceKind.PAPER),
            paper=EvidenceInputs(kind=EvidenceKind.PAPER),
            live=EvidenceInputs(kind=EvidenceKind.LIVE),
            research_symbols=(),
            clock=build_clock(data["clock"]),
        )


# --------------------------------------------------------------------------- #
# Task 2: live posture, kill-gate section, INCOMPLETE ledger, provenance in the report
# --------------------------------------------------------------------------- #

KILL_FAMILY_ORDER = ["trend-pullback", "breakout-retest", "range-mr"]
JUDGEMENT_GATES = ("G04", "G05", "G06", "G09")


def _posture_event(event_type: str, at: str, event_id: str) -> JournalEvent:
    return JournalEvent(
        journal_event_id=event_id,
        occurred_at_utc=parse_utc(at),
        event_type=event_type,
        entity_type="LiveEnablement",
        entity_id="LIVE_ORDERS_DISABLED",
        correlation_id="execution_enablement",
        payload_json="",
    )


def test_live_posture_is_disabled_for_the_fixture_and_unknown_when_empty() -> None:
    inputs = build_report_inputs()
    assert live_posture_from_events(inputs.journal_events) == "LIVE_ORDERS_DISABLED"
    assert live_posture_from_events(()) == "UNKNOWN"
    assert build_report().live_posture == "LIVE_ORDERS_DISABLED"


def test_live_posture_takes_the_latest_event_and_ignores_other_event_types() -> None:
    events = [
        _posture_event("LIVE_ORDERS_DISABLED", "2027-01-01T00:00:00+00:00", "a"),
        _posture_event("LIVE_ORDERS_ENABLED", "2027-02-01T00:00:00+00:00", "b"),
        _posture_event("KILL_GATE_EVALUATION", "2027-03-01T00:00:00+00:00", "c"),
    ]
    assert live_posture_from_events(events) == "LIVE_ORDERS_ENABLED"
    events.append(_posture_event("LIVE_ORDERS_DISABLED", "2027-02-15T00:00:00+00:00", "d"))
    assert live_posture_from_events(events) == "LIVE_ORDERS_DISABLED"


def test_live_posture_is_unchanged_under_shuffled_events() -> None:
    events = [
        _posture_event("LIVE_ORDERS_DISABLED", "2027-01-01T00:00:00+00:00", "a"),
        _posture_event("LIVE_ORDERS_ENABLED", "2027-02-01T00:00:00+00:00", "b"),
        _posture_event("LIVE_ORDERS_DISABLED", "2027-02-01T00:00:00+00:00", "c"),
        _posture_event("LIVE_ORDERS_ENABLED", "2027-01-15T00:00:00+00:00", "d"),
    ]
    baseline = live_posture_from_events(events)
    for seed in range(8):
        shuffled = list(events)
        random.Random(seed).shuffle(shuffled)
        assert live_posture_from_events(shuffled) == baseline


def test_live_posture_helper_does_not_touch_enablement_code() -> None:
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "src/analytics/report.py").read_text(
        encoding="utf-8"
    )
    imported = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(module.startswith("src.execution") for module in imported)


def test_kill_gate_section_carries_the_verdict_and_ordered_family_rows() -> None:
    report = build_report()
    section = report.kill_gate
    assert isinstance(section, KillGateSection)
    assert section.verdict.state is KillGateState.INSUFFICIENT_EDGE
    assert section.verdict.evaluated_at_utc == report.as_of_utc
    assert [row.family_id for row in section.families] == KILL_FAMILY_ORDER
    assert all(isinstance(row, FamilyGateRow) for row in section.families)
    assert list(section.decision_refs) == sorted(set(section.decision_refs))
    assert len(section.decision_refs) == 3
    for row in section.families:
        assert row.status == "TESTED_FAIL"
        cells = dict(row.cells)
        assert list(cells) == [f"G{n:02d}" for n in range(1, 11)]
        for gate in JUDGEMENT_GATES:
            assert cells[gate] is GateCell.PENDING_THRESHOLD_TBD
        assert cells["G01"] is GateCell.NOT_EVALUATED
    trend = section.families[0]
    assert dict(trend.cells)["G03"] is GateCell.MET
    assert dict(trend.cells)["G07"] is GateCell.MET
    assert dict(section.families[1].cells)["G08"] is GateCell.NOT_MET
    # A family with no recorded facts never gets a fabricated pass.
    range_cells = dict(section.families[2].cells)
    assert range_cells["G03"] is GateCell.NOT_MET
    assert range_cells["G10"] is GateCell.NOT_MET
    # Dual-universe counts: both backtest trades carry the trend-pullback candidate hash.
    assert (trend.live5_n, trend.research_n) == (2, 2)
    assert (section.families[1].live5_n, section.families[1].research_n) == (0, 0)
    assert [block.evidence for block in section.no_trade] == [
        EvidenceKind.BACKTEST,
        EvidenceKind.PAPER,
        EvidenceKind.LIVE,
    ]


def _untested_family(family_id: str, hash_char: str) -> FamilyEvidence:
    return FamilyEvidence(
        family_id=family_id,
        sheet_sha256=None,
        sheet_slots_present=(),
        candidate_param_set_hashes=(hash_char * 64,),
        experiment_ids=(),
        status=FamilyStatus.NOT_TESTED,
        decision_ref=None,
        decided_at_utc=None,
        development_experiment_ids=(),
        validation_experiment_ids=(),
    )


def test_family_rows_put_the_three_fixed_families_first_then_others_alphabetically() -> None:
    inputs = build_report_inputs()
    extras = (_untested_family("zeta-x", "e"), _untested_family("alpha-x", "f"))
    shuffled = (extras[0], *reversed(inputs.families), extras[1])
    report = build_journal_depth_report(
        dataclasses.replace(inputs, families=shuffled), base_seed=1, resamples=MIN_RESAMPLES
    )
    assert [row.family_id for row in report.kill_gate.families] == [
        *KILL_FAMILY_ORDER,
        "alpha-x",
        "zeta-x",
    ]
    untested = report.kill_gate.families[3]
    assert untested.status == "NOT_TESTED"
    assert untested.independent is False
    assert all(cell is not GateCell.MET for _, cell in untested.cells)


def test_build_kill_gate_section_rejects_non_backtest_outcomes() -> None:
    inputs = build_report_inputs()
    report = build_report()
    with pytest.raises(AnalyticsInputError):
        build_kill_gate_section(
            report.kill_gate.verdict,
            inputs.families,
            inputs.family_gate_facts,
            [block.no_trade for block in report.evidence],
            [make_outcome(evidence="PAPER", trade_id="P-1")],
            inputs.research_symbols,
        )


def test_incomplete_ledger_is_sorted_omits_zero_and_surfaces_notes_and_zero_risk() -> None:
    inputs = build_report_inputs()
    zero_risk_trade = make_trade_record(
        trade_id="T-ZERO-RISK",
        signal_id="SIG-ZERO-RISK",
        entry_price="100.00",
        entry_time_utc="2026-01-05T10:00:30+00:00",
        quantity="1",
        exit_kind="TP2",
        exit_price="101.00",
        exit_time_utc="2026-01-05T10:03:10+00:00",
        realized_pnl="1.00",
        realized_risk="0",
    )
    extra = normalize_backtest([zero_risk_trade]).outcomes
    backtest = dataclasses.replace(inputs.backtest, outcomes=(*inputs.backtest.outcomes, *extra))
    report = build_journal_depth_report(
        dataclasses.replace(inputs, backtest=backtest), base_seed=1, resamples=MIN_RESAMPLES
    )
    ledger = report.incomplete_ledger
    assert all(isinstance(entry, IncompleteEntry) for entry in ledger)
    assert all(entry.count > 0 for entry in ledger)
    order = {EvidenceKind.BACKTEST: 0, EvidenceKind.PAPER: 1, EvidenceKind.LIVE: 2}
    keys = [(order[entry.evidence], entry.input_name, entry.reason) for entry in ledger]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    rejected = [entry for entry in ledger if entry.input_name == "adapter.rejected_rows"]
    assert [(e.evidence, e.reason, e.count) for e in rejected] == [
        (EvidenceKind.BACKTEST, "MALFORMED_ROW", 1)
    ]
    zero_risk = [entry for entry in ledger if entry.reason == "ZERO_RISK"]
    assert zero_risk and all(entry.evidence is EvidenceKind.BACKTEST for entry in zero_risk)
    assert ("core_metrics", 1) in [(entry.input_name, entry.count) for entry in zero_risk]
    allowed = {reason.value for reason in IncompleteReason} | {"ZERO_RISK", "NOT_R_VALUED"}
    assert {entry.reason for entry in ledger} <= allowed


def test_incomplete_ledger_has_no_entries_for_a_clean_empty_report() -> None:
    inputs = build_report_inputs()
    empty = dataclasses.replace(
        inputs,
        backtest=EvidenceInputs(kind=EvidenceKind.BACKTEST),
        paper=EvidenceInputs(kind=EvidenceKind.PAPER),
    )
    report = build_journal_depth_report(empty, base_seed=1, resamples=MIN_RESAMPLES)
    assert report.incomplete_ledger == ()


def test_input_note_rejects_free_text_and_unknown_reasons() -> None:
    with pytest.raises(AnalyticsInputError):
        InputNote("adapter.rejected_rows", "some free text reason", 1)
    with pytest.raises(AnalyticsInputError):
        InputNote("free text name!", "MALFORMED_ROW", 1)
    with pytest.raises(AnalyticsInputError):
        InputNote("adapter.rejected_rows", "MALFORMED_ROW", -1)


def test_report_digest_covers_kill_gate_ledger_posture_and_provenance() -> None:
    base = build_report()
    inputs = build_report_inputs()
    no_events = build_journal_depth_report(
        dataclasses.replace(inputs, journal_events=()), base_seed=base.base_seed, resamples=100
    )
    assert no_events.live_posture == "UNKNOWN"
    assert no_events.digest() != base.digest()
    no_note = build_journal_depth_report(
        dataclasses.replace(inputs, backtest=dataclasses.replace(inputs.backtest, notes=())),
        base_seed=base.base_seed,
        resamples=100,
    )
    assert no_note.digest() != base.digest()
    earlier = build_journal_depth_report(
        dataclasses.replace(inputs, as_of_utc=datetime(2026, 12, 1, tzinfo=UTC)),
        base_seed=base.base_seed,
        resamples=100,
    )
    assert earlier.kill_gate.verdict.state is KillGateState.WITHIN_BUDGET
    assert earlier.digest() != base.digest()
    assert base.provenance.research_universe_status == "VERIFIED"


# --------------------------------------------------------------------------- #
# Task 3: evidence separation, determinism and secret-posture guards (D-05, D-01)
# --------------------------------------------------------------------------- #

FORBIDDEN_POOLED_NAME_PARTS = ("pooled", "combined", "aggregate", "blended", "merged", "overall")
SECRET_SUBSTRINGS = ("key", "secret", "token", "signature")
# The only field name that legitimately contains a secret-looking substring: the slice-row
# label (`SliceRow.key`, e.g. "BTCUSDT" or "2026-Q1"). Values get no allowance at all.
ALLOWED_SECRET_LOOKING_FIELD_NAMES = frozenset({"key"})
# Fixed constant sentences (module constants / protocol header), the only strings that may
# contain whitespace; everything else in the report must be an id, enum value or count.
FIXED_SENTENCES = frozenset(
    {
        EXCURSION_WINDOW_CONVENTION,
        SYNTHETIC_LAG_LABEL,
        PROTOCOL_CLOCK_SOURCE,
        PROTOCOL_FREEZE_COMMIT_AUTHOR_DATE,
    }
)


def assert_no_pooled_fields(node: object, path: str = "report") -> None:
    """Walk a dataclass tree; fail on any field whose name implies a cross-kind aggregate."""
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for spec in dataclasses.fields(node):
            lowered = spec.name.lower()
            for part in FORBIDDEN_POOLED_NAME_PARTS:
                assert part not in lowered, f"pooled-looking field {path}.{spec.name}"
            assert_no_pooled_fields(getattr(node, spec.name), f"{path}.{spec.name}")
    elif isinstance(node, (tuple, list)):
        for index, item in enumerate(node):
            assert_no_pooled_fields(item, f"{path}[{index}]")


def plain(node: object) -> object:
    """JSON-safe plain form of a report tree (canonical scalars, no float allowed)."""
    return canonical_scalars(dataclasses.asdict(node))  # type: ignore[call-overload]


def secret_hits(node: object) -> list[str]:
    """Secret-looking substrings in field names (minus the allow-list) and in any value."""
    hits: list[str] = []
    if isinstance(node, dict):
        for name, value in node.items():
            lowered = str(name).lower()
            if name not in ALLOWED_SECRET_LOOKING_FIELD_NAMES:
                hits.extend(f"name:{name}" for needle in SECRET_SUBSTRINGS if needle in lowered)
            hits.extend(secret_hits(value))
    elif isinstance(node, list):
        for value in node:
            hits.extend(secret_hits(value))
    elif isinstance(node, str):
        lowered = node.lower()
        hits.extend(f"value:{node}" for needle in SECRET_SUBSTRINGS if needle in lowered)
    return hits


def string_leaves(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [leaf for value in node.values() for leaf in string_leaves(value)]
    if isinstance(node, list):
        return [leaf for value in node for leaf in string_leaves(value)]
    return []


def test_structural_no_pooling_of_evidence_kinds() -> None:
    report = build_report()
    names = [spec.name for spec in dataclasses.fields(JournalDepthReport)]
    assert not [n for n in names if any(p in n.lower() for p in FORBIDDEN_POOLED_NAME_PARTS)]
    assert len(report.evidence) == 3
    assert all(isinstance(block, EvidenceBlock) for block in report.evidence)
    assert [block.kind for block in report.evidence] == [
        EvidenceKind.BACKTEST,
        EvidenceKind.PAPER,
        EvidenceKind.LIVE,
    ]
    assert_no_pooled_fields(report)


def test_no_pooling_mutation_self_check_catches_a_synthetic_pooled_dataclass() -> None:
    pooled_report = dataclasses.make_dataclass(
        "PooledReport", [("evidence", tuple), ("pooled_core", int)]
    )(evidence=(), pooled_core=1)
    with pytest.raises(AssertionError, match="pooled-looking field"):
        assert_no_pooled_fields(pooled_report)
    nested = dataclasses.make_dataclass("Wrapper", [("blocks", tuple)])(
        blocks=(dataclasses.make_dataclass("Inner", [("all_kinds_aggregate", int)])(1),)
    )
    with pytest.raises(AssertionError, match="pooled-looking field"):
        assert_no_pooled_fields(nested)


def test_each_block_counts_only_its_own_kind_and_blocks_sum_to_the_input_total() -> None:
    def outcome(evidence: str, trade_id: str, exit_minute: int) -> Any:
        return make_outcome(
            evidence=evidence,
            trade_id=trade_id,
            signal_id=f"SIG-{trade_id}",
            entry_price="100",
            entry_time_utc="2026-01-05T10:00:30+00:00",
            exit_price="101",
            exit_time_utc=f"2026-01-05T10:{exit_minute:02d}:00+00:00",
            quantity="1",
            realized_pnl="1",
            realized_risk="1",
        )

    inputs = build_report_inputs()
    backtest = tuple(outcome("BACKTEST", f"B{i}", 10 + i) for i in range(2))
    paper = (outcome("PAPER", "P0", 20),)
    live = tuple(outcome("LIVE", f"L{i}", 30 + i) for i in range(3))
    mixed = dataclasses.replace(
        inputs,
        backtest=EvidenceInputs(kind=EvidenceKind.BACKTEST, outcomes=backtest),
        paper=EvidenceInputs(kind=EvidenceKind.PAPER, outcomes=paper),
        live=EvidenceInputs(kind=EvidenceKind.LIVE, outcomes=live),
    )
    report = build_journal_depth_report(mixed, base_seed=1, resamples=MIN_RESAMPLES)
    counts = [block.core.n for block in report.evidence]
    assert counts == [2, 1, 3]
    assert sum(counts) == len(backtest) + len(paper) + len(live)
    assert [block.excursion.n_outcomes for block in report.evidence] == counts
    assert [block.slices.tables[0].total_n for block in report.evidence] == counts
    assert_no_pooled_fields(report)


def test_changing_only_paper_inputs_changes_only_the_paper_block() -> None:
    base = build_report()
    inputs = build_report_inputs()
    extra_no_trade = NoTradeRecord(
        evidence=EvidenceKind.PAPER, symbol="SOLUSDT", reason_code="RR_TOO_LOW", source_id="N-EXTRA"
    )
    changed = dataclasses.replace(
        inputs,
        paper=dataclasses.replace(
            inputs.paper, no_trades=(*inputs.paper.no_trades, extra_no_trade)
        ),
    )
    other = build_journal_depth_report(changed, base_seed=base.base_seed, resamples=MIN_RESAMPLES)
    assert other.evidence[0].digest() == base.evidence[0].digest()
    assert other.evidence[2].digest() == base.evidence[2].digest()
    assert other.evidence[1].digest() != base.evidence[1].digest()
    assert other.digest() != base.digest()


def _shuffled(items: tuple[Any, ...], seed: int) -> tuple[Any, ...]:
    listed = list(items)
    random.Random(seed).shuffle(listed)
    return tuple(listed)


def _reversed_mapping(mapping: Any) -> dict[Any, Any]:
    return {key: mapping[key] for key in reversed(sorted(mapping))}


def _shuffle_inputs(inputs: ReportInputs, seed: int) -> ReportInputs:
    def shuffle_evidence(item: EvidenceInputs) -> EvidenceInputs:
        return dataclasses.replace(
            item,
            outcomes=_shuffled(item.outcomes, seed),
            lifecycle=_shuffled(item.lifecycle, seed + 1),
            no_trades=_shuffled(item.no_trades, seed + 2),
            experiments=_shuffled(item.experiments, seed + 3),
            notes=_shuffled(item.notes, seed + 4),
            candles_by_symbol=_reversed_mapping(item.candles_by_symbol),
            realized_r_by_signal=_reversed_mapping(item.realized_r_by_signal),
        )

    return dataclasses.replace(
        inputs,
        backtest=shuffle_evidence(inputs.backtest),
        paper=shuffle_evidence(inputs.paper),
        live=shuffle_evidence(inputs.live),
        journal_events=_shuffled(inputs.journal_events, seed + 5),
        families=_shuffled(inputs.families, seed + 6),
        family_gate_facts=_reversed_mapping(inputs.family_gate_facts),
        research_symbols=_shuffled(inputs.research_symbols, seed + 7),
    )


def test_report_digest_is_reproducible_and_input_order_independent() -> None:
    inputs = build_report_inputs()
    seed = load_input(CASE)["base_seed"]
    base = build_journal_depth_report(inputs, base_seed=seed, resamples=MIN_RESAMPLES)
    again = build_journal_depth_report(inputs, base_seed=seed, resamples=MIN_RESAMPLES)
    assert base.digest() == again.digest() == load_expected(CASE)["report_digest"]
    for shuffle_seed in range(4):
        shuffled = build_journal_depth_report(
            _shuffle_inputs(inputs, shuffle_seed), base_seed=seed, resamples=MIN_RESAMPLES
        )
        assert shuffled.digest() == base.digest()
        assert shuffled == base


def test_report_digest_changes_with_seed_resamples_and_as_of() -> None:
    inputs = build_report_inputs()
    seed = load_input(CASE)["base_seed"]
    base = build_journal_depth_report(inputs, base_seed=seed, resamples=MIN_RESAMPLES)
    other_seed = build_journal_depth_report(inputs, base_seed=seed + 1, resamples=MIN_RESAMPLES)
    other_resamples = build_journal_depth_report(inputs, base_seed=seed, resamples=150)
    other_as_of = build_journal_depth_report(
        dataclasses.replace(inputs, as_of_utc=datetime(2027, 4, 2, tzinfo=UTC)),
        base_seed=seed,
        resamples=MIN_RESAMPLES,
    )
    digests = {base.digest(), other_seed.digest(), other_resamples.digest(), other_as_of.digest()}
    assert len(digests) == 4


def test_report_has_no_secret_substrings_outside_the_documented_allow_list() -> None:
    assert secret_hits(plain(build_report())) == []


def test_secret_scan_mutation_self_check() -> None:
    assert secret_hits({"api_secret": "x"}) != []
    assert secret_hits({"note": "my-Token-1"}) != []
    assert secret_hits({"key": "BTCUSDT"}) == []
    assert secret_hits({"key": "apikey123"}) != []
    assert secret_hits({"nested": [{"Signature": 1}]}) != []


def test_report_carries_no_journal_payload_or_free_text() -> None:
    inputs = build_report_inputs()
    marker = "PAYLOAD_LEAK_MARKER"
    leaking = JournalEvent(
        journal_event_id="enablement-leak-1",
        occurred_at_utc=parse_utc("2027-03-15T00:00:00+00:00"),
        event_type="LIVE_ORDERS_ENABLED",
        entity_type="LiveEnablement",
        entity_id="LIVE_ORDERS_DISABLED",
        correlation_id="execution_enablement",
        payload_json=json.dumps({"operator_id": marker}),
    )
    report = build_journal_depth_report(
        dataclasses.replace(inputs, journal_events=(*inputs.journal_events, leaking)),
        base_seed=1,
        resamples=MIN_RESAMPLES,
    )
    assert report.live_posture == "LIVE_ORDERS_ENABLED"
    tree = plain(report)
    dump = json.dumps(tree, sort_keys=True)
    assert marker not in dump
    assert "Traceback" not in dump
    spaced = [
        leaf
        for leaf in string_leaves(tree)
        if any(ch.isspace() for ch in leaf) and leaf not in FIXED_SENTENCES
    ]
    assert spaced == [], f"free-text-looking strings in the report: {spaced}"
