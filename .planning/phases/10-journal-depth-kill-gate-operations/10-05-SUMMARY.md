---
phase: 10-journal-depth-kill-gate-operations
plan: 05
subsystem: governance
tags: [kill-gate, d013, d030, evaluator, journal-event, clock, family-independence, tdd, tracer]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "Plan 02: D030 firing rule, KillGateState enum (GLOSSARY 8.2), RESEARCH_PROTOCOL v1.0.1"
  - phase: 10-journal-depth-kill-gate-operations
    provides: "Plan 01: pure analytics package guards (purity AST scan, strict mypy), phase10 fixture layout"
provides:
  - "src/analytics/clock.py: ClockStart provenance, exact calendar-month arithmetic with day clamping, earliest_terminal_utc"
  - "src/analytics/family.py: FamilyEvidence (human-decision-only TESTED_* status), KillGateInputError, independent_family_ids by facts, is_baseline_parameter_set_id"
  - "src/analytics/killgate.py: pure evaluate() to KillGateVerdict, build_kill_gate_event / record_kill_gate_evaluation (journal-first KILL_GATE_EVALUATION, content-hash id)"
  - "Four golden fixtures pinning verdict digest, evidence digest and journal_event_id, including the exact 6-month boundary"
affects: [10-07, 10-06]

actuals:
  tokens: 14000
  tasks: 3
  commits: 4
plan_head_before: 1d6442c4126b1d648e2a366cd468fb4480c56480
plan_head_after: 3480bfa54f2b83c2ebf09e733f1209a9c144eefc

tech-stack:
  added: []
  patterns:
    - "Constant payload key set: reopen/sticky fields exist (null/False) from the first event so the one-way contract never changes shape"
    - "Evidence digest covers full per-family facts plus independence/counted flags plus clock provenance, not just the emitted rows"
    - "Boundary fixture with two evaluated-at instants one second apart pins both sides of an inclusive limit"

key-files:
  created:
    - src/analytics/clock.py
    - src/analytics/family.py
    - src/analytics/killgate.py
    - tests/test_kill_gate_state.py
    - tests/test_kill_gate_event.py
    - tests/test_kill_gate_families.py
    - tests/fixtures/phase10/kill_within_budget/input.json
    - tests/fixtures/phase10/kill_within_budget/expected.json
    - tests/fixtures/phase10/kill_passing_candidate/input.json
    - tests/fixtures/phase10/kill_passing_candidate/expected.json
    - tests/fixtures/phase10/kill_insufficient_edge/input.json
    - tests/fixtures/phase10/kill_insufficient_edge/expected.json
    - tests/fixtures/phase10/kill_clock_boundary/input.json
    - tests/fixtures/phase10/kill_clock_boundary/expected.json
  modified: []

key-decisions:
  - "Decision checkpoint (Task 1) auto-approved: pre-approved by locked CONTEXT D-03, gate=blocking with auto_select=option-deterministic-journaled; recorded as the one-way door for the KILL_GATE_EVALUATION event contract"
  - "Only counted families (independent, TESTED_*, decided_at >= cycle start) contribute to families_tested, pass_count and decision_refs; non-independent or pre-cycle decisions are recorded in rows but never counted"
  - "decision_refs in the verdict is the sorted unique set of counted families' refs (audit set matches the evaluator's own decision basis)"
  - "evidence_digest hashes full family evidence (hashes, experiment ids, decided_at, independence, counted) plus clock provenance, so any input change alters it"
  - "Independence check treats sheet_slots_present order-insensitively (sorted equals REQUIRED_SLOTS); duplicates fail"

patterns-established:
  - "Recorded-human-decision status: TESTED_* cannot be constructed without decision_ref, UTC decided_at and Development/Validation ids that are subsets of the family experiments"
  - "Evaluator/recorder split: evaluate() and build_kill_gate_event() are pure; only record_kill_gate_evaluation() touches the journal, exactly once"

requirements-completed: [GOV-01]

coverage:
  - id: D1
    description: "Pure D013/D030 evaluator: INSUFFICIENT_EDGE iff >=3 counted independent families AND >=6 calendar months AND no pass; PASSING_CANDIDATE on any recorded pass; else WITHIN_BUDGET"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_state.py#test_tracer_insufficient_edge_state"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_state.py#test_tracer_within_budget_state"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_state.py#test_passing_candidate_records_evidence_without_authorizing_live"
        status: pass
  - id: D2
    description: "Exact inclusive 6-month boundary with day clamping (2027-03-18T23:59:59Z WITHIN_BUDGET, 2027-03-19T00:00:00Z INSUFFICIENT_EDGE)"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_state.py#test_boundary_one_second_before_six_months_is_within_budget"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_state.py#test_boundary_exactly_six_months_is_eligible_and_inclusive"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_state.py#test_add_months_clamps_to_last_day_of_target_month"
        status: pass
  - id: D3
    description: "Family independence decided by facts (7-slot sheet, distinct sheet hash, disjoint param-set hashes); fabricated pass cannot be constructed"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_families.py#test_shared_sheet_hash_marks_the_later_sorted_family_non_independent"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_families.py#test_tested_status_without_decision_ref_cannot_be_constructed"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_state.py#test_non_independent_tested_family_is_not_counted"
        status: pass
  - id: D4
    description: "Append-only KILL_GATE_EVALUATION event: exact allow-listed constant key set, content-hash id, idempotent replay, secret-free, journal-first single write"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_event.py#test_tracer_insufficient_edge_to_journal_event"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_event.py#test_tracer_record_is_journal_first_single_write"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_event.py#test_payload_is_secret_free_for_every_fixture_verdict"
        status: pass
  - id: D5
    description: "Whether a recorded INSUFFICIENT_EDGE terminal outcome is the right permanent audit posture (one-way door, locked D-03)"
    human_judgment: true
    rationale: "One-way reversibility of the recorded event contract is a governance judgment already pre-approved by locked decision D-03; no test can assert it is the right call"

duration: 5 min
completed: 2026-09-29
---

# Phase 10 Plan 05: Kill-Gate Evaluator and Journal Event Summary

**Pure D013/D030 kill-gate evaluator (families x research clock x injected evaluated-at) with an exact inclusive 6-month boundary, fact-based family independence, human-decision-only pass status, and a journal-first allow-listed KILL_GATE_EVALUATION event with a content-hash id.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-09-29T06:41:24Z
- **Completed:** 2026-09-29T06:46:00Z
- **Tasks:** 3 (1 decision checkpoint auto-approved, 1 tracer, 1 auto)
- **Files created:** 14 (3 source modules, 3 test modules, 8 fixture files)

## Accomplishments

- `evaluate(families, clock, evaluated_at_utc)` returns a frozen `KillGateVerdict` (state, budgets, whole months, extra days, display-only months_elapsed, pass count, decision refs, evidence digest, sorted family rows) with no wall-clock read, no float, no metric-to-threshold comparison.
- Boundary is exact: with clock start 2026-09-19T00:00:00Z, 2027-03-18T23:59:59Z is WITHIN_BUDGET (5 months 27 days) and 2027-03-19T00:00:00Z is INSUFFICIENT_EDGE (6 months 0 days). `add_months` clamps 2026-01-31 + 1 month to 2026-02-28 and 2024-01-31 + 1 month to 2024-02-29.
- `FamilyEvidence` makes fabricated passes unconstructible: TESTED_* needs a non-empty decision_ref, UTC decided-at, and Development + Validation experiment ids that are subsets of the family experiments. Independence uses sheet presence, full 7-slot template, distinct sheet hash and disjoint parameter-set hashes (processed in family-id order).
- `build_kill_gate_event` emits a 24-key constant payload (reopen/sticky fields present as null/False so plan 07 never changes the key set), `journal_event_id = kill_gate_<sha256>`, correlation `analytics_kill_gate`, entity `KillGate/KILL_GATE_D013`; identical inputs give identical id, digest and payload.

## Task Commits

1. **Task 1: Decision checkpoint** - no commit. Auto-approved: pre-approved by locked CONTEXT D-03 (gate `blocking`, `auto_select="option-deterministic-journaled"`); auto-selected option-deterministic-journaled and continued. Task 2 carries the one-way rating.
2. **Task 2 RED:** `64b9aaf` test(10-05): failing kill-gate evaluator and journal-event tracer tests (ImportError on the missing modules, as the plan specifies)
3. **Task 2 GREEN:** `496a7c1` feat(10-05): D013 kill-gate evaluator and journal-first KILL_GATE_EVALUATION event
4. **Task 3 RED:** `fd911a8` test(10-05): boundary, passing-candidate, independence and secret-scan tests
5. **Task 3 GREEN:** `3480bfa` feat(10-05): pin boundary and passing-candidate digests

**Plan metadata:** docs(10-05) commit follows this summary.

## Files Created/Modified

- `src/analytics/clock.py` - ClockStart, add_months, whole_months_between, extra_days_after, earliest_terminal_utc, REQUIRED_MONTHS
- `src/analytics/family.py` - FamilyEvidence, FamilyStatus, KillGateInputError, independent_family_ids, is_baseline_parameter_set_id, REQUIRED_SLOTS
- `src/analytics/killgate.py` - evaluate, KillGateVerdict, FamilyRow, build_kill_gate_event, record_kill_gate_evaluation, JournalLike, event constants
- `tests/test_kill_gate_state.py`, `tests/test_kill_gate_families.py`, `tests/test_kill_gate_event.py` - 53 tests
- `tests/fixtures/phase10/kill_{within_budget,passing_candidate,insufficient_edge,clock_boundary}/` - input.json and expected.json with pinned digests and journal_event_id

## Decisions Made

See key-decisions above. The one-way contract fixed by this plan: event type `KILL_GATE_EVALUATION`, entity id `KILL_GATE_D013`, id prefix `kill_gate`, and the 24-key payload set. Pinned insufficient-edge event id: `kill_gate_478fbb32017142b1e2e5bcf657ad52184268d7a4a6f91e5f173b6fce458c72ed`.

## Deviations from Plan

None - plan executed exactly as written, with these notes:

- Test helper functions (`build_clock`, `build_family`, `load_case`, `evaluate_case`, `evaluate_at`) live in `tests/test_kill_gate_state.py` and are imported by the event test, keeping all edits inside the plan's file list.
- Task 3's added semantic tests (boundary, independence, validation, secret scan) passed on first run because Task 2's GREEN implemented the full rule set exactly as the plan's Task 2 action describes; only the digest-pin assertions failed at Task 3 RED (missing keys in expected.json).

## TDD Gate Compliance

- Task 2: RED `64b9aaf` (collection ImportError, matching the plan's stated RED), GREEN `496a7c1`. The ImportError RED is a module-missing failure rather than an assertion failure; it follows the plan and the convention of prior Phase 10 plans and is flagged here for the verifier.
- Task 3: RED `fd911a8` (3 failing pin assertions; the other new tests were unexpected-greens because the rules already existed), GREEN `3480bfa` (pins only, no source change). No REFACTOR commit.

## Issues Encountered

None. mypy reports only the pre-existing `src/adapters/telegram_notify.py` error; analytics paths are strict-clean. ruff and `ruff format --check` clean on the created files.

## Verification

- `pytest tests/test_kill_gate_state.py tests/test_kill_gate_families.py tests/test_kill_gate_event.py tests/test_kill_gate_docs.py tests/test_analytics_purity.py tests/test_analytics_typing.py tests/test_execution_enablement.py -q` passes (enablement untouched).
- Tracer command `-k tracer` passes (8 tests); `ruff check src/analytics tests/test_kill_gate_*.py` clean.

## Known Stubs

None.

## Threat Flags

None - no new network endpoints, auth paths, file access or schema changes; the evaluator is pure and only the journal-recording wrapper writes (one event, journal-first).

## Next Phase Readiness

Ready for plan 10-06 and plan 10-07 (sticky/reset/enablement depth), which fill `sticky`, `reopened_*` and `prior_terminal_count` in the fixed payload without changing the key set. GOV-01 is shared with later plans; completion is decided by `requirements.ready-ids`.

## Self-Check: PASSED

- All 14 created files exist on disk; commits `64b9aaf`, `496a7c1`, `fd911a8`, `3480bfa` exist in `git log`.
