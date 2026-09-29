---
phase: 10-journal-depth-kill-gate-operations
plan: 07
subsystem: governance
tags: [kill-gate, sticky-terminal, human-reset, clock-parser, gate-cells, enablement, registration-tripwire, tdd, tracer]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "Plan 05: evaluate(), KillGateVerdict with fixed 24-key payload, ClockStart, FamilyEvidence, KILL_GATE_EVALUATION event"
  - phase: 09-live-execution
    provides: "LiveEnablementController.enable() journal-first flip (Phase 9 D-04)"
provides:
  - "src/analytics/killgate.py: sticky INSUFFICIENT_EDGE with explicit human reset (PriorEvaluation, ResetRecord, prior_from_event, reset_from_event, priors_from_events, resets_from_events, build_question_approved_event), post-reset budget restart, registration_allowed(state)"
  - "src/analytics/clock.py: FROZEN_ON_PATTERN (identical to research-gate CI regex + date capture), PROTOCOL_FREEZE_COMMIT/AUTHOR_DATE provenance, parse_frozen_on, clock_start_from_protocol"
  - "src/analytics/gates.py: GATE_IDS, GATE_LABELS, GateCell, FamilyGateFacts, derive_gate_cells, gate_cells_digest (no fabricated pass)"
  - "src/execution/enablement.py: enable() with required kill_gate_state keyword; refusal of INSUFFICIENT_EDGE and non-KillGateState values before any journal write"
  - "docs/research/kill_gate_decisions.json + tests/test_kill_gate_registration.py: CI tripwire blocking new params/ family directories under a recorded terminal state"
affects: [10-08, 10-09, 10-10, 10-11, 10-12]

actuals:
  tokens: 21000
  tasks: 3
  commits: 6
plan_head_before: 820b3e601802d2650db651596753f2a698d04387
plan_head_after: 5e9dbb371f8ea900eab8ccc95b3ebc296a438bbb

tech-stack:
  added: []
  patterns:
    - "Sticky inputs join the evidence digest only when present, so evaluations without priors/resets keep the byte-identical plan-05 digests and event ids"
    - "Prior evaluations count only when strictly earlier than the evaluated-at, making same-instant replay idempotent"
    - "CI-readable mirror of a journal-only terminal state: committed decision record plus a params/ directory tripwire with a tmp-dir self-test"

key-files:
  created:
    - src/analytics/gates.py
    - docs/research/kill_gate_decisions.json
    - tests/test_kill_gate_sticky.py
    - tests/test_kill_gate_clock.py
    - tests/test_kill_gate_gates.py
    - tests/test_kill_gate_registration.py
    - tests/fixtures/phase10/kill_sticky_reset/input.json
    - tests/fixtures/phase10/kill_sticky_reset/expected.json
    - tests/fixtures/phase10/idempotent_replay/input.json
    - tests/fixtures/phase10/idempotent_replay/expected.json
    - tests/fixtures/phase10/clock_start_provenance/input.json
    - tests/fixtures/phase10/clock_start_provenance/expected.json
  modified:
    - src/analytics/killgate.py
    - src/analytics/clock.py
    - src/execution/enablement.py
    - tests/test_execution_enablement.py
    - tests/test_execution_health.py
    - tests/test_execution_manager.py

key-decisions:
  - "Post-reset semantics (flagged planner decision, needs user review; D013 is silent): the cycle clock restarts at the latest applicable reset time, only family decisions dated on or after it count, and the reopening decision_ref/operator/time are recorded in every later verdict"
  - "A reset is applicable only with non-empty operator_id and decision_ref, occurring not later than evaluated-at and strictly after some prior terminal; the state stays sticky unless a reset is strictly later than the LATEST prior terminal"
  - "prior_terminal_count = number of prior INSUFFICIENT_EDGE evaluations strictly earlier than evaluated-at (in the reopened fixture step this is 2, because both earlier terminal events are fed back)"
  - "enable() gained a required kill_gate_state keyword; refusal checks run after operator/UTC/health validation and before the journal write; the kill-gate state is NOT added to the enable journal payload"
  - "Registration block is CI-enforced through the committed decision record (recorded_terminal null today) because CI cannot read the journal; params/ directory names must equal families_at_record once a terminal is recorded"

patterns-established:
  - "Evaluator reads, humans write: KILL_GATE_QUESTION_APPROVED is produced only by build_question_approved_event (test/operator tooling), never by evaluate()"
  - "Gate cells: judgement gates always PENDING_THRESHOLD_TBD, G01/G02 always NOT_EVALUATED, only recorded-fact gates (G03, G07, G08, G10) can be MET"

requirements-completed: []

coverage:
  - id: D1
    description: "INSUFFICIENT_EDGE is sticky: new passing evidence never clears it; only a valid human KILL_GATE_QUESTION_APPROVED after the latest terminal reopens research; reset before terminal, empty operator_id, empty decision_ref, future reset and same-instant prior are ignored"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_sticky.py#test_tracer_sticky_sequence_terminal_then_sticky_then_reopened"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_sticky.py#test_sticky_ignored_reset_cases_stay_sticky"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_sticky.py#test_sticky_prior_at_the_same_instant_is_ignored"
        status: pass
  - id: D2
    description: "Replay idempotence: identical inputs, and the same instant with the evaluation's own persisted event as a prior, give the identical digest and content-hash event id; payload key set unchanged from plan 05"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_sticky.py#test_replay_own_persisted_event_at_the_same_instant_gives_the_same_event_id"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_sticky.py#test_sticky_payload_key_set_matches_the_plan_05_allow_list"
        status: pass
  - id: D3
    description: "Clock start parsed from the protocol header with the exact research-gate regex (00:00Z of Frozen-on) with freeze-commit provenance; gate cells never fabricate a pass (exhaustive 48-combination test)"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_clock.py#test_frozen_on_pattern_is_the_research_gate_regex_with_a_date_capture_group"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_clock.py#test_real_protocol_file_gives_the_expected_clock_start"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_gates.py#test_exhaustive_combinations_never_yield_met_for_judgement_or_unverifiable_gates"
        status: pass
  - id: D4
    description: "enable() refuses INSUFFICIENT_EDGE, None and plain strings before any journal write or flag flip; WITHIN_BUDGET and PASSING_CANDIDATE permit; enable payload key set unchanged; 7 call sites updated"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_execution_enablement.py#test_enable_refuses_insufficient_edge_before_journal_or_flag"
        status: pass
      - kind: test
        ref: "tests/test_execution_enablement.py#test_enable_refuses_unevaluated_or_non_state_kill_gate_values"
        status: pass
      - kind: test
        ref: "tests/test_execution_enablement.py#test_enable_journal_payload_key_set_is_unchanged_by_the_kill_gate_gate"
        status: pass
  - id: D5
    description: "Registration tripwire: a new params/ family directory fails CI under a recorded terminal state (tmp-dir self-test) and the committed repo state passes"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_kill_gate_registration.py#test_tripwire_fires_when_a_family_directory_is_added_under_a_terminal_record"
        status: pass
      - kind: test
        ref: "tests/test_kill_gate_registration.py#test_committed_repo_state_passes_the_registration_tripwire"
        status: pass
  - id: D6
    description: "Whether the post-reset budget-restart semantics (cycle clock restarts at the reset time; only later decisions count) match the user's intent for D013"
    human_judgment: true
    rationale: "D013 does not specify post-reset behavior; this is a flagged planner decision that only the user can confirm"

duration: 12 min
completed: 2026-09-29
---

# Phase 10 Plan 07: Sticky Kill-Gate Terminal, Enablement Refusal and Registration Tripwire Summary

**Sticky INSUFFICIENT_EDGE that only an explicit human KILL_GATE_QUESTION_APPROVED event can reopen (with a deterministic post-reset budget restart and same-instant replay idempotence), a protocol-header clock parser sharing the research-gate CI regex, non-fabricating gate cells, an `enable()` that refuses the terminal state before any journal write, and a CI tripwire blocking new strategy-family directories under a recorded terminal.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-09-29T07:01:00Z
- **Completed:** 2026-09-29T07:13:00Z
- **Tasks:** 3 (1 tracer, 2 auto; all TDD)
- **Files:** 12 created, 6 modified

## Accomplishments

- `evaluate()` takes `prior_evaluations` and `resets`. Priors count only when strictly earlier than the evaluated-at. A prior INSUFFICIENT_EDGE stays the verdict (sticky, counts still reported) unless a valid reset is strictly later than the latest prior terminal. After a reset the cycle clock restarts at the reset time, families decided earlier stop counting, and the reopening decision ref, operator and time are recorded. Fixture sequence pinned: INSUFFICIENT_EDGE, then INSUFFICIENT_EDGE sticky (a fourth passing family does not clear it), then WITHIN_BUDGET reopened (cycle start 2027-06-01, earliest terminal 2027-12-01). Step-1 digests equal the plan-05 pins, so the 24-key payload contract is untouched.
- `prior_from_event` / `reset_from_event` never raise on malformed events; `build_question_approved_event` (id prefix `kill_gate_reset`) rejects empty operator_id/decision_ref and is a builder only, never a write path of the evaluator.
- `FROZEN_ON_PATTERN` is the research-gate CI regex with one date capture group; a test extracts the CI text from the workflow and asserts identity. The real protocol file parses to 2026-09-19T00:00:00Z (earliest terminal 2027-03-19T00:00:00Z); freeze commit 281ccd0894ea35717cc741788b6133cfb202af82 / 2026-09-19T14:08:12+07:00 re-verified with `git show -s --format=%H%n%aI 281ccd0`.
- `derive_gate_cells`: G01/G02 always NOT_EVALUATED, G04/G05/G06/G09 always PENDING_THRESHOLD_TBD, G03/G07/G08/G10 MET only from recorded facts; exhaustive test over 48 fact combinations.
- `enable(..., kill_gate_state)` refuses INSUFFICIENT_EDGE and any non-`KillGateState` value (None, plain string) after the operator/UTC/health checks and before the journal write; controller stays disabled with zero events. Enable journal payload keys unchanged. Module imports `src.domain.enums` only (AST test proves no analytics/SDK/SQLAlchemy/Pydantic/Polars import).
- `docs/research/kill_gate_decisions.json` (`recorded_terminal: null` today) plus `tests/test_kill_gate_registration.py`: schema validation, forbidden identity-key scan, and a tmp-dir self-test proving a new family directory fails under a terminal record.

## Task Commits

1. **Task 1 (tracer) RED:** `56335f9` test(10-07): failing sticky INSUFFICIENT_EDGE, human reset and replay tests
2. **Task 1 GREEN:** `411b9e7` feat(10-07): sticky INSUFFICIENT_EDGE with explicit human reset and replay idempotence
3. **Task 2 RED:** `a06cceb` test(10-07): failing protocol clock parser, gate-cell and registration predicate tests
4. **Task 2 GREEN:** `5ffa855` feat(10-07): protocol-header clock parser, gate-cell derivation and registration predicate
5. **Task 3 RED:** `1caacd0` test(10-07): failing enable() kill-gate refusal tests, updated call sites and registration tripwire
6. **Task 3 GREEN:** `5e9dbb3` feat(10-07): enable() refuses INSUFFICIENT_EDGE and unevaluated kill-gate state

**Plan metadata:** docs(10-07) commit follows this summary.

Tracer gate: the tracer `<verify>` is automated-only; it was re-run after the GREEN commit and passed, so expansion proceeded (no checkpoint).

## Decisions Made

See key-decisions above. Confirmed production callers: `grep -rn "\.enable(" src scripts` returns no matches, so the seven call sites are all tests (5 in tests/test_execution_enablement.py, 1 in tests/test_execution_health.py, 1 in tests/test_execution_manager.py) and no production code needed a signature update.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Extra plural parsers and gate digest helper**
- **Found during:** Task 1 / Task 2
- **Issue:** The plan says both parsers "sort inputs by (occurred_at_utc, event_type, entity_id, journal_event_id) before use" but defines only single-event parsers; the plan's Task 2 also mentions "digest helpers" for gates without naming them.
- **Fix:** Added `priors_from_events` / `resets_from_events` (sorted, None-dropping) and `gate_cells_digest`; `evaluate()` itself is order-insensitive (tested).
- **Files modified:** src/analytics/killgate.py, src/analytics/gates.py
- **Commits:** 411b9e7, 5ffa855

**2. [Rule 1 - Bug in own tests] Test authoring corrections**
- **Found during:** Task 1 and Task 2 GREEN
- **Issue:** `JournalEvent` rejects non-JSON payloads at construction, so a "not json" parser case could not be built; one gate test expected G07 NOT_MET for a tested family with unknown reproducibility, contradicting the plan's rule (G07 is NOT_EVALUATED unless reproducibility is explicitly False).
- **Fix:** Replaced the case with an empty payload (also exercises the parse-failure branch) and corrected the test to use reproducibility False.
- **Commits:** 411b9e7, 5ffa855

**3. [Process] Accidental reformat reverted**
- `ruff format src/analytics` reformatted the untouched `src/analytics/stats.py`; it was reverted with `git checkout -- src/analytics/stats.py` before the next commit, so no unrelated change was committed.

**Total deviations:** 3 (1 Rule 2 addition, 1 Rule 1 test correction, 1 process revert). **Impact:** none on plan behavior or contract.

## TDD Gate Compliance

- Task 1: RED `56335f9` (ImportError on the new names, matching the plan-05 convention), GREEN `411b9e7`.
- Task 2: RED `a06cceb` (collection ImportError), GREEN `5ffa855`.
- Task 3: RED `1caacd0` (updated call sites raise TypeError against the old signature, new refusal and registration tests fail), GREEN `5e9dbb3`. No REFACTOR commits.
- RED for tasks 1 and 2 is a missing-name ImportError rather than an assertion failure; digest pins were added at GREEN as the plan specifies.

## Issues Encountered

None blocking. Baselines unchanged: mypy reports only the pre-existing `src/adapters/telegram_notify.py:287` error; `ruff format --check` on `src/execution/enablement.py` still reports two pre-existing formatting diffs (present at HEAD before this plan; not reformatted to keep the diff scoped).

## Verification

- Plan verification set (kill-gate state/sticky/clock/gates/registration/docs/event/families, execution enablement/health/gates/manager, analytics purity/typing): all pass.
- Full repo suite `pytest -q -x`: all pass.
- `ruff check` clean on the plan's file list; mypy clean on `src/analytics` and `src/execution/enablement.py`; `scripts/check_migration_parity.py` exits 0.

## Known Stubs

None.

## Threat Flags

None - no new network endpoints, auth paths or schema changes. The decision-record JSON and its tripwire were in the plan's threat model (T-10-22).

## Next Phase Readiness

Ready for the remaining Phase 10 plans. GOV-01 is shared with later plans in this phase, so completion is left to `requirements.ready-ids`.

## Self-Check: PASSED

- All created files exist on disk (src/analytics/gates.py, docs/research/kill_gate_decisions.json, four test modules, six fixture files); commits 56335f9, 411b9e7, a06cceb, 5ffa855, 1caacd0, 5e9dbb3 exist in `git log`.
