---
phase: 20-reconcile-safe-mode-hardening
plan: 09
subsystem: execution-protection
tags: [protection, stop-supervision, d077, reconcile-hooks, fail-closed, tdd]

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: plan 20-02 PROTECTION transition guard, clearing rules and replay validator
provides:
  - "Stop supervision after PROTECTED: every step of PROTECTED, COMPLETE and TP_UNAVAILABLE reads the stop by its deterministic id (D-07); a confirmed stop that reads ABSENT or NOT_ACTIVE goes through the existing D077 decision by the position"
  - "PROTECTION table edges PROTECTED/COMPLETE/TP_UNAVAILABLE -> CLOSE_REQUIRED and -> UNPROTECTED (docstring, table and EXPECTED table together)"
  - "ProtectionCoordinator.protections(), notify_divergence(plan_hash, kind), restore_complete (reconcile hooks for plans 20-10, 20-19)"
  - "PlanProtection fields approval_id, side, entry_quantity, entry_client_order_id"
  - "tests/test_protection_supervision.py (27 tests) with a StopPlacementGuard that checks every STOP_MARKET placement (RISK-03)"
affects: [20-10, 20-17, 20-19, 20-24]

plan_head_before: 6ef390216a3fd3005614ff7e5fc8fb7efa15fc3f
plan_head_after: f7b4fe696d15b28079adb77afe192f3c2bf22575

actuals:
  tokens: 11909   # chars/4 over `git diff 6ef39021 HEAD -- src tests` (47639 chars)
  tasks: 3
  commits: 6      # MEASURED: git rev-list --count 6ef39021..HEAD (3 test + 3 feat), before the docs commit

tech-stack:
  added: []
  patterns:
    - "a supervised state first reads the stop and hands a lost stop to the one D077 decision path (_on_stop_lost); nothing new decides"
    - "a reconcile notice only marks a re-check and journals; the coordinator's own step acts"
    - "execution keeps divergence-kind literals and a parity test against src.reconcile.compare (execution never imports reconcile)"

key-files:
  created:
    - tests/test_protection_supervision.py
  modified:
    - src/execution/protection.py
    - src/execution/protection_replay.py
    - src/domain/transitions.py
    - tests/test_transitions.py
    - tests/test_protection_take_profits.py

key-decisions:
  - "From a supervised state a lost stop beside a flat position (two zero reads, entry terminal) ends FLAT with reason POSITION_CLOSED (as before this plan), not STOP_CONSUMED_FLAT; the latter stays for UNPROTECTED and PROTECTED_ENTRY_OPEN. Evidence REST_FLAT_TWO_READS_ENTRY_TERMINAL is journaled either way."
  - "An unreadable stop answer in PROTECTED / COMPLETE / TP_UNAVAILABLE keeps the state and ends the step (journal REST_FAILED with the exception type name only); the next step reads again. It is never read as lost or as ACTIVE."
  - "notify_divergence accepts five kinds (POSITION_WITHOUT_STOP, TP_ONLY_POSITION, SIGN_FLIPPED_POSITION, DOUBLED_POSITION, ENTRY_WITHOUT_PROTECTIVE) as text literals; src.execution does not import src.reconcile, and a test pins the literals to src/reconcile/compare.py."

requirements-addressed: [RISK-03, EXEC-02]  # copied from the plan frontmatter; REQUIREMENTS.md is NOT edited and no requirement is marked complete (wording checkpoint O-A is open)

coverage:
  - id: C1
    description: "A stop confirmed ACTIVE and later cancelled with exposure open is seen on the next step and handled per D077 (B4 CLOSE_REQUIRED, one reduce-only MARKET close, one alert), in PROTECTED, COMPLETE and TP_UNAVAILABLE, and is never re-placed"
    requirement: "RISK-03"
    verification:
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_protected_stop_cancelled_with_exposure_closes_and_never_replaces"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_a_cancelled_stop_with_exposure_is_b4_in_every_supervised_state"
        status: pass
    human_judgment: false
  - id: C2
    description: "Flat exit after TP2 with the stop left as an orphan or auto-cancelled (both A3 outcomes against the fake), unreadable position escalates from stop_lost_at, a late ACTIVE answer never restores PROTECTED, an unreadable stop answer keeps the state"
    requirement: "RISK-03"
    verification:
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_complete_tp2_triggered_flat_on_two_reads_ends_flat_without_a_close"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_tp_unavailable_stop_not_active_position_unreadable_escalates_from_stop_lost_at"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_a_lost_stop_that_reads_active_again_does_not_restore_protected"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_an_unreadable_stop_answer_keeps_the_state_and_the_next_step_reads_again"
        status: pass
    human_judgment: false
  - id: C3
    description: "Every STOP_MARKET placement of the coordinator tests carries trigger_price == entry.sl_trigger_price, close_position True and the deterministic STOP_LOSS id (RISK-03 never wider); the only re-placement left is the never-confirmed, proven-absent one"
    requirement: "RISK-03"
    verification:
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_every_stop_placement_carries_the_plan_stop_price_and_the_deterministic_id"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_a_guard_violation_would_be_seen"
        status: pass
    human_judgment: false
  - id: C4
    description: "protections(), notify_divergence and restore_complete: read-only sorted view, one journal note, forced re-read on the next step, no exchange call by the notice, unknown plan False, unknown kind ValueError, kinds pinned to compare.py, AST guard on the method body"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_protections_is_a_read_only_sorted_view_of_every_tracked_plan"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_notify_divergence_journals_once_and_places_and_cancels_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_notify_divergence_makes_the_next_step_read_the_stop_and_the_position"
        status: pass
      - kind: unit
        ref: "tests/test_protection_supervision.py#test_notify_divergence_never_calls_a_placement_cancel_or_close_method"
        status: pass
    human_judgment: false
  - id: C5
    description: "Whether Binance auto-cancels a closePosition stop when the position closes (A3 / G4-035) and how a real lost stop behaves on Demo; both outcomes are handled and tested against the fake only"
    verification: []
    human_judgment: true
    rationale: "Every test runs against the project fake exchange. No Demo observation exists for this plan; the Phase 19 probes (A3, probe 6) and the owner's D055 closure decide whether the modelled exchange behavior is right."

duration: 40min
completed: 2026-10-21
status: complete
---

# Phase 20 Plan 09: Stop Supervision After PROTECTED Summary

**A stop that was confirmed ACTIVE and is later cancelled or lost is now seen on the next step in PROTECTED, COMPLETE and TP_UNAVAILABLE and decided by the position as in D077 (B4 CLOSE_REQUIRED plus a reduce-only MARKET close, UNPROTECTED with `stop_lost_at` once, or FLAT on two zero reads), never re-placed; the coordinator also exposes `protections()`, `notify_divergence()` and `restore_complete` for the reconcile loop.**

Evidence label: executed unit tests with the project fake exchange, the real `MarketEmergencyCloser` and virtual time, plus `[DOC]` code reading. No `[DEMO]` observation exists for this plan. Binance auto-cancel of `closePosition` legs (A3) is NOT observed; both outcomes are handled `[DESIGN]`. LIVE stays blocked (`LIVE_ORDERS_DISABLED`).

## Performance

- **Duration:** about 40 min (dev machine clock)
- **Completed:** 2026-10-21T09:05Z (last code commit; the docs commit follows)
- **Tasks:** 3 (tracer, auto, auto), each RED then GREEN
- **Files:** 1 created, 5 modified

## Accomplishments

- **Task 1 (tracer).** `_supervise_stop` runs first in the PROTECTED, COMPLETE and TP_UNAVAILABLE branches of `_step_plan`. It reads the stop by `derive_algo_client_id(plan_hash, STOP_LOSS)` and interprets it with the existing `_apply_stop_answer`. ABSENT or NOT_ACTIVE (the stop was confirmed earlier in these states, so it is a loss) calls the existing `_on_stop_lost`: exposure -> CLOSE_REQUIRED (B4) and the closer's MARKET close; position unreadable -> UNPROTECTED with reason `STOP_LOST_AFTER_PROTECTED` and `stop_lost_at` set once; two zero reads with the entry terminal -> FLAT. The six new edges are in the `ProtectionState` docstring, the `_PROTECTION` table and the `EXPECTED` table of `tests/test_transitions.py`. No edge out of CLOSE_REQUIRED/CLOSE_FAILED to a protected state was added (T-A).
- **Task 2.** Tests for each remaining D077 outcome in the three states, the A3 both-ways flat exit, the escalation at `stop_lost_at + max_unprotected_ms` (TEST_ONLY 7777 ms, no guessed-quantity close), a late ACTIVE answer not restoring PROTECTED, and the `StopPlacementGuard` (every STOP_MARKET placement: plan stop price, `close_position=True`, deterministic id). An unreadable stop answer keeps the state.
- **Task 3.** `PlanProtection` gains `approval_id`, `side`, `entry_quantity`, `entry_client_order_id` (defaults None). `protections()` returns a frozen tuple ordered by `(registered_at_utc, plan_hash)`. `notify_divergence` validates the kind, returns False for an unknown plan, otherwise sets `recheck_requested`, journals one `PROTECTION_DIVERGENCE_NOTIFIED` note and returns True; it is synchronous and calls no adapter method. `restore_complete` is True (plan 20-19 owns the rebuild).

## Task Commits

TDD, each task RED then GREEN (RED evidence is the pytest failure seen before the GREEN commit; `gsd_run check tdd-red-evidence` does not parse pytest output, as found in plans 20-01 and 20-02):

1. **Task 1: Tracer** - RED `5d46ae6f` (test), GREEN `1c34f02a` (feat)
2. **Task 2: Other D077 outcomes, RISK-03 guard** - RED `a50ebe2e` (test), GREEN `8685c9ec` (feat)
3. **Task 3: Reconcile hooks** - RED `62763712` (test), GREEN `f7b4fe69` (feat)

**Plan metadata:** the `docs(20-09)` commit that adds this file.

## Existing tests whose REST-call-count expectation changed

Reason for every entry: one supervision stop read per step (D-07).

| Test | Change |
|---|---|
| `tests/test_protection_take_profits.py::test_tp_legs_are_placed_exactly_once_when_step_runs_again` | the set of read-only calls allowed in the repeated steps of a COMPLETE plan is now `{snapshot_positions, query_algo_order_by_client}` (was `{snapshot_positions}`); a new assertion counts exactly one STOP_LOSS query per repeated step. The name is unchanged. |

No other existing assertion changed. `tests/test_transitions.py` `EXPECTED[PROTECTION]` gained the six edges (that is the T-A table update the plan asks for, not a call-count change).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] The replay validator did not know the new stop-lost reason**
- **Found during:** Task 1
- **Issue:** `replay_transitions` treats a history as stop-lost only when an UNPROTECTED row carries reason `STOP_LOST`. A history that goes PROTECTED -> UNPROTECTED (`STOP_LOST_AFTER_PROTECTED`) -> PROTECTED would then replay as valid, although the live guard forbids it (`stop_lost_at` set).
- **Fix:** `src/execution/protection_replay.py` (not in the plan's `files_modified`) defines `REASON_STOP_LOST_AFTER_PROTECTED` and treats both reasons as stop-lost; `protection.py` imports and re-exports the constant, so the plan's named constant exists there.
- **Files modified:** `src/execution/protection_replay.py`
- **Commit:** `1c34f02a`

### Design notes (no rule needed)

**2. FLAT reason from a supervised state stays `POSITION_CLOSED`.** `_on_stop_lost` ended FLAT with `STOP_CONSUMED_FLAT`. From PROTECTED/COMPLETE/TP_UNAVAILABLE the stop leaving the book beside a flat position is the position closing (stop or take profit fired, or A3 auto-cancel), so the reason there is `POSITION_CLOSED`, as before this plan. The pinned `tests/test_protection_transitions.py::test_a_real_run_replays_to_its_last_state` (which stops the position out of PROTECTED and expects `POSITION_CLOSED`) failed with the first implementation (`STOP_CONSUMED_FLAT`); the reason selection fixed it and no assertion was changed.

**3. An unreadable stop answer ends the step.** The plan says "keep the state (the next step reads again)". The first implementation carried on with the state's own work; the RED test `test_an_unreadable_stop_answer_keeps_the_state_and_the_next_step_reads_again` (failed: `COMPLETE is PROTECTED`, `FLAT is COMPLETE`) showed that, and `_supervise_stop` now returns True only for ACTIVE. Cost: TP attach or the flat exit waits one step when the stop query fails. Fail closed, no safety loss.

**4. `recheck_requested` has a small real effect.** In PROTECTED, COMPLETE and TP_UNAVAILABLE the ordinary step already reads the stop (and the position through the TP step or the exit watch), so a notice changes nothing there beyond the journal note. In UNPROTECTED (stop still trusted) and PROTECTED_ENTRY_OPEN the ordinary step reads the stop but not the position; a notice adds one position read (`_position_is_open`) whose result decides nothing (a failure is journaled by the helper). A lost-stop UNPROTECTED already reads the position every step and never reads the stop again. The decision stays with the existing paths (D-07 single decision path).

**5. Observed, not changed:** a PROTECTED step makes two STOP_LOSS queries (the supervision read and one inside `attach_protectives_to_fill`). The tests therefore count the supervision read only where the attach step is not reached.

---

**Total deviations:** 1 auto-fixed (Rule 2), 4 design/observation notes. **Impact on plan:** no scope creep; no deadline, branch decision or placement path changed; the only automatic stop placement left is the never-confirmed, proven-absent one (B2/B3).

## Re-placement cases after this plan (T-A table)

1. Stop never confirmed, REST proved it absent, inside `max_unprotected_ms`: re-placed under the same id from the plan (unchanged; guarded by `StopPlacementGuard`; the owner confirms or rejects it at O-A, it is not described here as owner-approved).
2. Stop confirmed ACTIVE then lost: never re-placed, now also in PROTECTED / COMPLETE / TP_UNAVAILABLE (D077).
3. Unconfirmed at the deadline after a positive fill with exposure not proven flat: CLOSE_REQUIRED (unchanged). A definitive stop rejection (B5) is never resent (unchanged).

## TDD Gate Compliance

RED commits `5d46ae6f`, `a50ebe2e`, `62763712` precede the GREEN commits `1c34f02a`, `8685c9ec`, `f7b4fe69` (`git log --grep` on `test(20-09)` precedes `feat(20-09)` each time).

- Task 1 RED: `test_protected_stop_cancelled_with_exposure_closes_and_never_replaces` failed on `At index 1 diff: 'TP_UNAVAILABLE' != 'CLOSE_REQUIRED'` (the target assertion); `test_tables_match_the_plan_objective[PROTECTION]` and `test_exhaustive_cross_product[PROTECTION]` failed on the added edges.
- Task 2 RED: both parametrizations of `test_an_unreadable_stop_answer_keeps_the_state_and_the_next_step_reads_again` failed (`COMPLETE is PROTECTED`, `FLAT is COMPLETE`). The other Task 2 tests (B4 in each state, A3 flat exit both ways, escalation, late ACTIVE, price guard) passed at RED because Task 1's supervision already satisfies them; they are regression pins for the plan's behavior bullets, not new behavior.
- Task 3 RED: 14 tests failed with `AttributeError` (`protections`, `restore_complete`, `notify_divergence`, `NOTIFIABLE_DIVERGENCE_KINDS` absent). Two of the first-run failures were test mistakes fixed before the GREEN commit (a stop-read count in PROTECTED that includes the attach step's own check, and `from src.reconcile import compare` returning a function).

## Verification (what was run, with results)

All `[executed]` on the dev machine; the full suite was NOT run (the orchestrator runs it once per phase):

- `uv run pytest -m "not docker" tests/test_protection_supervision.py tests/test_protection_take_profits.py tests/test_protection_coordinator.py tests/test_protection_branches.py tests/test_protection_stop_lost.py tests/test_protection_transitions.py tests/test_transitions.py tests/test_protection_unknown_entry.py`: 204 passed (`tests/test_protection_supervision.py` alone: 27 passed).
- Callers of the coordinator, as an impact check (same set as plan 20-02): `tests/test_demo_rehearsal_flow.py test_emergency_market_close.py test_exchange_error_rejections.py test_execution_attach.py test_execution_manager.py test_protection_router_rig.py test_system_throttle_protection.py test_phase19_gate.py test_binance_usdm_signed_calls.py test_execution_write_ahead_pg.py`: 597 passed.
- `uv run mypy src`: Success, no issues in 217 source files. `uv run ruff check`: all passed. `uv run ruff format --check`: 680 files already formatted.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- pyproject.toml uv.lock`: exit 0 (T-20-SC: no dependency added).
- AST guard `test_notify_divergence_never_calls_a_placement_cancel_or_close_method` passes (no attribute call starting `place_`, `cancel_`, `_place`, `_cancel`, `_sweep`, `_enter_`, `_attempt`; no `await`).

## Issues Encountered

- `src/execution/protection.py`, `src/execution/protection_replay.py`, `src/domain/transitions.py`, `tests/test_transitions.py` and `tests/test_protection_take_profits.py` are CRLF in the working tree; they were edited bytes-aware (a multi-edit helper kept in the scratchpad, not in the repo) and `file` still reports CRLF. The new test file is LF in the working tree (git normalizes it).
- The worktree had no `.codegraph/` index, so CodeGraph was skipped.

## Limits and open items

- `[NOT_TESTED]` Binance behavior for a `closePosition` stop when the position closes (A3, probe 6) and for a stop cancelled by the owner on Demo. The fake models both an orphaned and an auto-cancelled stop.
- `[DOC]` Between a stop trigger and the position reduction a supervision read can see the stop FINISHED while the position still reads open and so pick B4 (a reduce-only MARKET close); this is the same race `PROTECTED_ENTRY_OPEN` already had and is decided by the position, not the stop class. How the closer behaves when the position closes between the read and its order was not exercised by this plan.
- `notify_divergence` has no production caller yet; plan 20-10 (compare v2) and 20-12 are the callers. `restore_complete` is a constant True until plan 20-19.
- No alert is added at the stop-lost UNPROTECTED entry (19-REVIEW WR-04 owner choice 2 stands; alerts are plan 20-22).
- Not a Demo observation; not a D055 closure; not LIVE approval. Phase 20 criterion 2 wording (O-A) is untouched; `docs/DECISIONS.md`, ROADMAP, REQUIREMENTS and STATE were not edited.

## Known Stubs

None.

## Threat Flags

None. No network endpoint, auth path, file access or schema change was added. The new journal event `PROTECTION_DIVERGENCE_NOTIFIED` carries a fixed kind and a state name only.

## User Setup Required

None.

## Next Phase Readiness

- Plan 20-10 can call `protections()` as the local source for compare v2 and `notify_divergence` for stop divergences; plan 20-19 flips `restore_complete` to False until its rebuild finishes.
- Plan 20-17 (operator close) and plan 20-24 extend the same `_PROTECTION` table; any new edge needs an `EXPECTED` entry in `tests/test_transitions.py`.

---
*Phase: 20-reconcile-safe-mode-hardening*
*Completed: 2026-10-21*

## Self-Check: PASSED

Created file `tests/test_protection_supervision.py`, the six task commits (`5d46ae6f`, `1c34f02a`, `a50ebe2e`, `8685c9ec`, `62763712`, `f7b4fe69`) and the plan-level verification above were checked on disk and in git before this file was written.
