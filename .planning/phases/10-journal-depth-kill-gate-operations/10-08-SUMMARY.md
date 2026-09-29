---
phase: 10-journal-depth-kill-gate-operations
plan: 08
subsystem: analytics
tags: [report-model, provenance, kill-gate-section, incomplete-ledger, live-posture, determinism, evidence-separation, tdd, tracer]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-01 analytics core (EvidenceKind, TradeOutcome, IncompleteReason, stats helpers, purity/typing guards); 10-03/10-04/10-06 sections (core metrics, excursion, execution quality, approval delay, slices, dual universe, NO_TRADE counts, live outcomes); 10-05/10-07 kill-gate evaluate(), family facts, gate cells, sticky/reset inputs"
provides:
  - "src/analytics/report.py: EvidenceInputs, InputNote, ReportInputs, EvidenceBlock, IncompleteEntry, FamilyGateRow, KillGateSection, JournalDepthReport, build_evidence_block, build_kill_gate_section, build_incomplete_ledger, live_posture_from_events, build_journal_depth_report"
  - "src/analytics/provenance.py: ExperimentIdentity, KindProvenance, ProvenanceBlock, build_provenance"
  - "One pure function composing three unpooled evidence blocks (BACKTEST, PAPER, LIVE), the kill-gate section, INCOMPLETE ledger, provenance and live posture under a single report digest"
  - "Golden fixture report_composite (input + pinned report digest) and structural/determinism/secret-posture guards"
affects: [10-09, 10-10, 10-11, 10-12]

actuals:
  tokens: 21000
  tasks: 3
  commits: 5
plan_head_before: b31015b5dff9e8812fb284ed0bed1d213cf0dd00
plan_head_after: e04bf76634c65814d641e4b5cf1f03dbb8045013

tech-stack:
  added: []
  patterns:
    - "Frozen input dataclasses freeze sequences to tuples and mappings to read-only sorted-key copies at construction; every output is built by sorted total keys, so shuffled inputs give an equal report tree"
    - "Ledger inputs are structured (InputNote: identifier + fixed reason vocabulary + count), never free text, so the report cannot carry exception text or payloads"
    - "Live posture derived by string-literal event types only; the module imports no enablement code (AST-tested)"
    - "Structural no-pooling test walks the whole dataclass tree for aggregate-looking field names and is proven by a synthetic pooled-dataclass mutation self-check"

key-files:
  created:
    - src/analytics/report.py
    - src/analytics/provenance.py
    - tests/test_analytics_report.py
    - tests/test_analytics_provenance.py
    - tests/fixtures/phase10/report_composite/input.json
    - tests/fixtures/phase10/report_composite/expected.json
  modified: []

key-decisions:
  - "ReportInputs.clock (ClockStart) is a required field: the kill-gate verdict is always evaluated inside the report at the single injected as_of_utc, and a report without a clock provenance would be unreadable"
  - "Provenance keeps BACKTEST/PAPER/LIVE identity separately (by_evidence) in addition to the flat union fields the plan lists, and tags every ExperimentIdentity with the evidence slot it came from"
  - "A family with no recorded gate facts gets all-False facts (never a fabricated pass); gate facts for a family id that does not exist raise AnalyticsInputError instead of being silently dropped"
  - "At an identical instant the total ordering key places LIVE_ORDERS_ENABLED after LIVE_ORDERS_DISABLED (alphabetical event_type), so a same-microsecond tie displays ENABLED; the plan fixes this key and the posture is display-only, so it is recorded here rather than changed"
  - "Ledger input names are structured identifiers (core_metrics, excursion, execution_quality.<LEG>, execution_quality.deviation, approval_delay.<REPORT>, approval_delay.delay, plus caller note names); the only secret-looking field name in the whole tree is SliceRow.key and is allow-listed by name in the test, never by value"

patterns-established:
  - "Composite golden fixture: one input.json (trades, candles, paper rows, families, gate facts, events, notes, experiments) with one pinned report digest plus a few key numeric pins"
  - "Sections are never re-computed in the report: the ledger only re-labels counters already present in section dataclasses"

requirements-completed: []

coverage:
  - id: D1
    description: "One pure function composes exactly three per-kind evidence blocks (BACKTEST, PAPER, LIVE, always present and ordered; empty kinds are valid no-data blocks) with one digest; cross-kind elements raise"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_report.py#test_tracer_composes_three_kinds_and_digest"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_cross_kind_elements_raise"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_empty_evidence_is_a_valid_no_data_block"
        status: pass
  - id: D2
    description: "Backtest, paper and live evidence are never pooled: no aggregate field anywhere in the tree, blocks built from own-kind inputs only, blocks sum to the input total, and a PAPER-only change leaves the other block digests untouched"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_report.py#test_structural_no_pooling_of_evidence_kinds"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_no_pooling_mutation_self_check_catches_a_synthetic_pooled_dataclass"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_each_block_counts_only_its_own_kind_and_blocks_sum_to_the_input_total"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_changing_only_paper_inputs_changes_only_the_paper_block"
        status: pass
  - id: D3
    description: "Full evidence provenance: strategy versions, parameter-set ids/hashes, experiment identity fields, universe hash with VERIFIED/UNVERIFIED_UNIVERSE/NOT_APPLICABLE status, snapshot and epoch ids, vocabulary constants and which kinds are present"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_provenance.py#test_provenance_lists_the_experiment_identity_fields_and_evidence_tag"
        status: pass
      - kind: test
        ref: "tests/test_analytics_provenance.py#test_research_universe_status_verified_unverified_and_not_applicable"
        status: pass
      - kind: test
        ref: "tests/test_analytics_provenance.py#test_provenance_states_constants_and_kinds_present"
        status: pass
  - id: D4
    description: "Live-orders posture is read-only from the latest LIVE_ORDERS_ENABLED/DISABLED event by a total key, UNKNOWN when none, shuffle-invariant, and the module imports no enablement code"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_report.py#test_live_posture_is_disabled_for_the_fixture_and_unknown_when_empty"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_live_posture_is_unchanged_under_shuffled_events"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_live_posture_helper_does_not_touch_enablement_code"
        status: pass
  - id: D5
    description: "Kill-gate section wraps the evaluated verdict with fixed-order family rows (trend-pullback, breakout-retest, range-mr, then others alphabetically), gate cells that never fabricate a pass, and live-5/research counts"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_report.py#test_kill_gate_section_carries_the_verdict_and_ordered_family_rows"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_family_rows_put_the_three_fixed_families_first_then_others_alphabetically"
        status: pass
  - id: D6
    description: "Every INCOMPLETE bucket, ZERO_RISK exclusion, rejected row and unmatched join surfaces in one sorted, zero-omitting ledger with a fixed reason vocabulary"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_report.py#test_incomplete_ledger_is_sorted_omits_zero_and_surfaces_notes_and_zero_risk"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_input_note_rejects_free_text_and_unknown_reasons"
        status: pass
  - id: D7
    description: "Reproducibility and secret posture: pinned report digest, shuffled inputs give an equal report, seed/resamples/as_of change the digest, no secret-looking substrings or free text or journal payload in the canonical dump"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_report.py#test_report_digest_is_reproducible_and_input_order_independent"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_report_digest_changes_with_seed_resamples_and_as_of"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_report_has_no_secret_substrings_outside_the_documented_allow_list"
        status: pass
      - kind: test
        ref: "tests/test_analytics_report.py#test_report_carries_no_journal_payload_or_free_text"
        status: pass
  - id: D8
    description: "Whether the report's section vocabulary and per-kind provenance layout are what the operator-facing renderer and the future amendment citations need (renderer plans 10 and 11 consume this schema)"
    human_judgment: true
    rationale: "The composed dataclass tree is a costly-to-reverse schema whose adequacy for the operator layout is only judgeable once the renderer consumes it"

duration: 12 min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 08: Composed Journal-Depth Report Model Summary

**One pure `build_journal_depth_report` that assembles three never-pooled BACKTEST/PAPER/LIVE analytics blocks, the evaluated kill-gate section with per-family gate cells, a sorted INCOMPLETE ledger, full evidence provenance and a read-only live-orders posture under a single reproducible digest.**

## Performance

- **Duration:** 12 min (07:16Z to 07:29Z)
- **Tasks:** 3 (1 tracer, 2 auto; all TDD)
- **Files:** 6 created, 0 modified (2 source modules, 2 test modules, 2 fixture files)

## Accomplishments

- `build_evidence_block` composes one section of each analytics module (core metrics, excursion, execution quality, approval delay, slices, dual universe, NO_TRADE counts) for exactly one evidence kind; an all-empty kind is a valid no-data block, and an element of another kind raises `AnalyticsInputError`. `build_journal_depth_report` returns exactly three blocks in the fixed BACKTEST, PAPER, LIVE order with a digest over schema version, injected `as_of_utc`, seed, resamples, block digests, live posture, kill-gate section, ledger and provenance.
- `KillGateSection` wraps the verdict evaluated inside the report at the injected instant (`evaluate(... evaluated_at_utc=as_of_utc ...)`; nothing is ever written or recorded). Family rows are ordered trend-pullback, breakout-retest, range-mr, then others alphabetically; gate cells come only from `derive_gate_cells` (judgement gates always PENDING_THRESHOLD_TBD, a family without recorded facts never gets a fabricated pass); each row carries live-5 and research-universe counts of BACKTEST outcomes matching its candidate parameter-set hashes.
- The INCOMPLETE ledger re-labels counters already present in the sections (core-metrics ZERO_RISK and NOT_R_VALUED, excursion incompletes and zero-risk exclusions, per-leg and deviation incompletes, the three approval-delay reports and delay exclusions) plus structured caller notes (`InputNote`), sorted by (evidence order, input name, reason), zero counts omitted. In the composite fixture it lists the rejected-row note, the BACKTEST not-measured latency legs, and the PAPER approval-delay reasons.
- `ProvenanceBlock` states strategy versions, parameter-set ids/hashes, experiment identities tagged by evidence slot (all identity fields plus universe hash and run type), the research-universe hash with VERIFIED / UNVERIFIED_UNIVERSE / NOT_APPLICABLE status via the shared `verify_research_universe`, data-snapshot ids, paper epoch ids, the imported vocabulary constants (approval-delay lag, LOW_N_THRESHOLD, resamples, base_seed, slice vocabulary version, session bands), which kinds have data, the live-net-PnL-semantics flag and `("funding",)` as the live-R exclusion, and per-kind identity (`by_evidence`).
- `live_posture_from_events` picks the latest LIVE_ORDERS_ENABLED/DISABLED event by the total key (occurred_at_utc, event_type, entity_id, journal_event_id) or `UNKNOWN`; the module imports nothing from `src.execution` (AST-tested) and journal payload text never enters the report (leak-marker test).
- Pinned composite digest `57bcaab6d328210b2484b20d98250c9b63e8d65628ffb68d8fb5e418744535ee`: BACKTEST core n 2 (mean R 0.8), PAPER 2 NO_TRADE rows, LIVE no data, verdict INSUFFICIENT_EDGE at 2027-04-01, posture LIVE_ORDERS_DISABLED, VERIFIED research universe.

## Task Commits

1. **Task 1 (tracer) RED:** `b58a5c7` test(10-08): failing composite three-kind report and digest tracer tests
2. **Task 1 GREEN:** `a37d798` feat(10-08): compose per-kind evidence blocks into a digest-stamped journal-depth report
3. **Task 2 RED:** `4b91c8b` test(10-08): failing provenance, INCOMPLETE ledger, live posture and kill-gate section tests
4. **Task 2 GREEN:** `a2f455c` feat(10-08): provenance block, INCOMPLETE ledger, live posture and kill-gate section
5. **Task 3:** `e04bf76` test(10-08): evidence-separation, determinism and secret-posture guards for the composed report

Tracer gate: the tracer `<verify>` is automated-only; it was re-run after the GREEN commit and passed with the purity guard, so expansion proceeded (no checkpoint).

**Plan metadata:** docs(10-08) commit follows this summary.

## Files Created/Modified

- `src/analytics/report.py` - input dataclasses, evidence block, kill-gate section, ledger, posture and the report builder.
- `src/analytics/provenance.py` - experiment identity, per-kind provenance and the report-wide provenance block.
- `tests/test_analytics_report.py`, `tests/test_analytics_provenance.py` - tracer, ledger, posture, kill-gate, provenance, separation, determinism and secret-posture tests.
- `tests/fixtures/phase10/report_composite/{input,expected}.json` - hand-authored composite fixture and pins.

## Decisions Made

See key-decisions above. The main ones needing a later look: the same-instant ENABLED/DISABLED tie ordering (display-only), and the shape of `by_evidence` provenance once the renderer exists.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Structured `InputNote` type for ledger notes**
- **Found during:** Task 2
- **Issue:** The plan names `EvidenceInputs.notes` entries (rejected rows, unmatched joins) without a shape; an unconstrained free-text note would let exception text or payload strings enter the report (T-10-26).
- **Fix:** `InputNote(input_name, reason, count)` validates a structured identifier, a reason from the fixed ledger vocabulary (every `IncompleteReason` value plus ZERO_RISK / NOT_R_VALUED) and a non-negative count.
- **Files modified:** src/analytics/report.py
- **Commit:** a2f455c

**2. [Rule 2 - Missing critical] Fail-closed handling of gate facts for unknown families and of unknown-kind evidence**
- **Found during:** Task 2
- **Issue:** Gate facts keyed by a family id that is not in the family list would be silently ignored (a typo would hide recorded facts).
- **Fix:** `build_kill_gate_section` raises `AnalyticsInputError` for such keys and for a verdict without a row for a supplied family.
- **Files modified:** src/analytics/report.py
- **Commit:** a2f455c

**3. Additions beyond the plan text (no behavior conflict):** `EvidenceInputs.has_data`, `build_incomplete_ledger`, `FIXED_FAMILY_ORDER`, the `KindProvenance` per-kind identity, and `ReportInputs.clock` as a required field. Task 1's RED `expected.json` deliberately lacked the digest (pinned at GREEN, the Phase 10 convention), and Task 3's guard tests passed against the Task 2 implementation immediately, so Task 3 has a single commit carrying the mutation self-checks instead of a separate GREEN commit.

**Total deviations:** 2 Rule 2 additions plus additive fields. **Impact:** none on plan intent or contracts; the composite digest was re-pinned once in Task 2 because the new fields joined the digest.

## TDD Gate Compliance

- Task 1: RED `b58a5c7` (ModuleNotFoundError for `src.analytics.report`), GREEN `a37d798`.
- Task 2: RED `4b91c8b` (ImportError on the new names), GREEN `a2f455c`.
- Task 3: guard tests written RED-first, all passing on the existing implementation; each structural/secret guard carries a mutation self-check proving it would fail on a pooled or secret-bearing synthetic. No REFACTOR commits.

## Issues Encountered

None blocking. Baselines unchanged: mypy on `src/analytics` reports only the pre-existing `src/adapters/telegram_notify.py:287` error; `ruff check` and `ruff format --check` are clean on the four new source/test modules. Full repo suite `pytest -q -x` passes.

## Verification

- `pytest tests/test_analytics_report.py tests/test_analytics_provenance.py tests/test_analytics_purity.py tests/test_analytics_typing.py`: pass.
- Earlier analytics suites (excursion, latency, slices, approval delay, dual universe, NO_TRADE, kill-gate state): pass.
- `ruff check src/analytics tests/test_analytics_report.py tests/test_analytics_provenance.py`: clean.

## Known Stubs

None.

## Threat Flags

None - the modules are pure (no network, auth, file or schema surface). T-10-24 to T-10-27 are covered by the structural no-pooling, ledger, secret-scan and shuffle/determinism tests above.

## Next Phase Readiness

Ready for 10-09. The renderer (plans 10 and 11) consumes `JournalDepthReport`; JRN-01 and GOV-01 are shared with later plans in this phase, so completion is left to `requirements.ready-ids`. Live R still renders as INCOMPLETE (UNVERIFIED_EXCHANGE_SEMANTICS) while `LIVE_NET_PNL_SEMANTICS_VERIFIED` is False (plan 06 open item).

## Self-Check: PASSED

- Created files exist on disk (src/analytics/report.py, src/analytics/provenance.py, tests/test_analytics_report.py, tests/test_analytics_provenance.py, tests/fixtures/phase10/report_composite/input.json and expected.json); commits b58a5c7, a37d798, 4b91c8b, a2f455c, e04bf76 exist in `git log`.
