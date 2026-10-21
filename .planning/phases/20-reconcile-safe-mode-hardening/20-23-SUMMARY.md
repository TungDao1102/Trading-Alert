---
phase: 20-reconcile-safe-mode-hardening
plan: 23
subsystem: drills-and-phase-gate
tags: [drills, F-604, D-27, D-28, G2-016, narrowed-placement-rule, phase-gate, OPS-01, EXEC-02, RISK-03, tdd]
requires: [20-11, 20-12, 20-15, 20-16, 20-19, 20-21, 20-22, 20-25]
provides:
  - "src.ops.drills: RETIRED_OUTCOMES; OUTCOME_NO_PLACE_ORDER_INVARIANT removed from ALL_OUTCOMES and from src"
  - "make_unprotected_drill / make_stale_feed_drill take a real ReconcileLoop and emit OUTCOME_SAFE_MODE_BLOCKED"
  - "make_manual_close_drill takes close_control (emergency_manual_close) and read_truth, rehearses both G4-035 answers"
  - "tests/test_phase20_gate.py: PHASE20_PURE_MODULES, PHASE20_ORCHESTRATOR_MODULES, PHASE20_RECONCILE_MODULES, PHASE20_LIMIT_KEYS, REQUIREMENT_TESTS"
affects: [20-24, 20-26]
key-files:
  created:
    - tests/test_phase20_gate.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-23-SUMMARY.md
  modified:
    - src/ops/drills.py
    - tests/test_drills.py
    - tests/test_reconcile.py
    - tests/test_phase8_audit_reviewfix.py
    - tests/fixtures/phase8/drill_log/expected.json
key-decisions:
  - "The old rule 'no drill places anything' is replaced by the narrowed rule in two halves: src/reconcile and src/ops never call a placement method (static guard kept, AST gate added), and a delegated protective action is placed by the coordinator in src/execution with the plan's own price and deterministic id (asserted on a real ProtectionCoordinator)."
  - "Fake adapter placement methods record the calling module (sys._getframe(1) in a plain wrapper) and no longer raise; the tests assert on the recorded callers."
  - "The MANUAL_CLOSE drill does not enter SAFE_MODE itself: emergency_manual_close does, the drill checks the controller afterwards. The variant (auto-cancel or orphan) follows the data the fake exchange returns, not a flag."
requirements-addressed: []
status: complete
duration: about 2h
completed: 2026-10-21
estimate:
  tokens: 100000
  tasks: 3
actuals:
  tokens: 36000
  tasks: 3
  commits: 3
plan_head_before: 3f61bcdd32476a3d8b11d252e05b64009931a0f9
plan_head_after: 922e8a2933d692e476d8a6bf63ffb0a72ee89c70
---

# Phase 20 Plan 23: Drills through the Phase 20 components and the Phase 20 gate Summary

The UNPROTECTED, STALE_FEED and MANUAL_CLOSE drills (G2-016) now run through the real Phase 20 components instead of hand-wired compare calls, the outcome that encoded the pre-D034 rule is retired, every test that asserted "the reconciler never places" now asserts the narrowed rule, and `tests/test_phase20_gate.py` pins the phase invariants.

Base commit `3f61bcdd` (develop). `commits: 3` is the measured `git rev-list --count 3f61bcdd..HEAD` at SUMMARY write, before the SUMMARY commit itself. No requirement is marked complete (`requirements-addressed` empty on purpose, as in 20-08 and 20-11). All drill and gate evidence is fake-exchange rehearsal; the real-stack RUNBOOK rehearsal stays Phases 25/26 `[NOT_TESTED on Demo]`; no `[DEMO]` claim.

## What was built

- `src/ops/drills.py`
  - `make_unprotected_drill(loop, safe_mode_controller, now_utc)`: runs one `ReconcileLoop.tick`; requires a compared tick, a `POSITION_WITHOUT_STOP` divergence, the plan in `TickReport.delegated`, SAFE_MODE with that reason in the tick's reasons, and `guard_new_entries` answering `RECONCILIATION_REQUIRED`; outcome `OUTCOME_SAFE_MODE_BLOCKED`.
  - `make_stale_feed_drill(loop, safe_mode_controller, now_utc)`: one tick with a stale `FeedSource`; requires a stale symbol or silent user-data feed, an alert sent, reason `STALE_FEED`, entries blocked; outcome `OUTCOME_SAFE_MODE_BLOCKED`.
  - `make_manual_close_drill(close_control, read_truth, sweeper, safe_mode_controller, local_intent, position_verifier, compare_fn=None)`: runs the control (which enters SAFE_MODE `MANUAL_CLOSE`), reads the exchange afterwards, compares, sweeps. No orphan: outcome `OUTCOME_SAFE_MODE_ENTERED` (nothing swept); orphans: sweeper cancels after two zero reads and verifies, outcome `OUTCOME_ORPHAN_SWEPTED`. Never exits SAFE_MODE.
  - `RETIRED_OUTCOMES` (`MappingProxyType`): `"no_place_order_invariant_held"` -> "encoded the pre-D034 rule (08-REVIEW IN-08); replaced by the narrowed static guard". The constant `OUTCOME_NO_PLACE_ORDER_INVARIANT` is gone from `ALL_OUTCOMES`, `__all__` and src. `DRILL_NAMES` (8) and `DRILL_RUNBOOK_SECTION` are unchanged. The restore drill is unchanged (plan 20-15); `tests/test_safe_mode_exit_operator.py::test_the_restore_drill_exits_with_an_operator_id` already pins the operator id.
- `tests/test_phase20_gate.py` (23 tests): pure modules (9) have no wall clock, float or SDK/network/DB import; orchestrators (6) no wall clock and no SDK; `src/reconcile` (9 modules, glob-checked against the list) has no placement call or import (AST, `place_*`, `new_order`, `new_algo_order`; armed by a sample file and by finding the call in `protection.py`); the seven Phase 20 limit keys are `NOT_CONFIGURED` in value and provenance, have a field, and both spellings are in `GUARDED_NAMES`; `RejectionReason` has 21 members and GLOSSARY 9.1 lists exactly them; `REQUIREMENT_TESTS` maps EXEC-02, OPS-01, RISK-03, EXEC-06 and OPS-05 to named tests resolved with `ast`; `docs/DECISIONS.md` last row is D078 and D055 still says "stays OPEN". The ROADMAP criteria pin stays in `tests/test_phase19_gate.py`.

## Rewritten old-rule tests

- `tests/test_reconcile.py::FakeReconcileAdapter` (place_order / place_algo_order no longer raise; they record the caller module; new `placements_from_reconcile()`)
- `tests/test_reconcile.py::test_orphan_protective_divergence_classified_and_swept` (`place_order_calls == 0` now also asserts no placement from `src.reconcile`)
- `tests/test_reconcile.py::test_divergence_forces_safe_mode_without_cancel` (same)
- `tests/test_reconcile.py::test_fake_adapter_records_the_calling_module_and_does_not_raise` (new, arms the recording so the two rewritten assertions are not vacuous)
- `tests/test_reconcile.py::test_no_place_order_path_in_src_reconcile`: unchanged (the narrowed static guard, kept)
- `tests/test_drills.py::_FakeReconcileAdapter` (raising place methods replaced by caller-recording ones)
- `tests/test_drills.py::test_no_place_order_invariant_across_all_drills` -> `test_reconcile_never_places_and_delegated_stops_keep_the_plan_price` (F-604, D034/D077): half 1 over the full drill run, half 2 on a real `ProtectionCoordinator`: the loop tick places nothing, `coordinator.step()` then places one `place_algo_protective` from `src.execution.protection`, `STOP_MARKET`, `trigger_price == entry.sl_trigger_price`, id equal to the deterministic STOP_LOSS client id
- `tests/test_drills.py::test_eight_drills_rehearse_with_injected_faults`, `test_drill_log_matches_golden_fixture`, `test_safe_mode_exit_only_via_restore_drill` (expected outcomes follow the new drills)
- `tests/test_drills.py::test_no_place_order_path_in_src_ops` (logic unchanged, comments no longer claim a raising fake)
- `tests/test_phase8_audit_reviewfix.py::test_wr28_manual_close_uses_injected_compare` (new factory signature, same intent: the injected compare is observed)
- New in `tests/test_drills.py`: `test_placement_methods_of_the_drill_and_reconcile_fakes_do_not_raise` (AST, armed), `test_no_place_order_invariant_outcome_is_retired`, `test_safe_mode_blocked_outcome_is_emitted_by_the_entry_guard_drills`, `test_unprotected_drill_blocks_entries_through_the_loop`, `test_unprotected_drill_fails_when_the_scenario_has_no_divergence`, `test_stale_feed_drill_enters_safe_mode_through_the_loops_feed_check`, `test_stale_feed_drill_fails_when_the_feed_is_fresh`, `test_manual_close_drill_orphan_variant_sweeps_the_legs_that_stayed`, `test_manual_close_drill_auto_cancel_variant_has_nothing_to_sweep`, `test_manual_close_drill_with_the_position_still_open_never_cancels_the_stop`, `test_loop_drills_never_exit_safe_mode`
- Golden fixture `tests/fixtures/phase8/drill_log/expected.json`: outcomes of drills 1 and 5 are `safe_mode_blocked_entries`, faults of drills 1, 5 and 7 follow the new fault strings (hand-derived from the run; a hand-kept Phase 8 file, not generator-owned).

No assertion was deleted without a replacement: every `place_order_calls == 0` became a `placements_from_reconcile() == []` check that sits next to it, and the raising fakes became recording ones.

## Deviations from Plan

**1. [Rule 3 - ordering] Commit boundaries are not one-per-task.** Tasks 1 and 2 share `drills.py`, `test_drills.py` and the golden fixture and the AST test cross-references `test_reconcile.py`, so the commits are: `73307289` (the `test_reconcile.py` rewrite, Task 2 part), `49dea925` (all three drills, the retirement, `test_drills.py`, fixture, WR-28 test: Tasks 1 and 2), `922e8a29` (Task 3 gate). Each commit is green on its own tree.

**2. [Rule 3 - file outside `files_modified`] `tests/test_phase8_audit_reviewfix.py` and `tests/fixtures/phase8/drill_log/expected.json` were edited.** WR-28 called `make_manual_close_drill` with the removed `truth=` argument; the golden log pins outcomes and faults of drills that changed. The WR-25 test of that file still passes unchanged (the text `place_order_calls == 0` and `BUILT_DRILL_ADAPTERS` remain in `test_drills.py`).

**3. [Plan intent] `make_manual_close_drill` does not take `truth`.** The truth must be read after the control ran, so it takes `read_truth` (async) instead; local intent stays a dict. The two G4-035 variants are chosen by the fake exchange (`legs_auto_cancelled`), not by a flag in the drill. In the orphan variant the control keeps the legs (`PROTECTIVES_KEPT`, reason `ENTRY_NOT_TERMINAL`: the entry filled) and the sweeper removes them, as the `emergency_manual_close` docstring says.

**4. [TDD ordering slip] The drill factories were written before their tests.** I did not capture RED output for Tasks 1 and 2; the tests were written against the finished factories. The negative tests (`test_unprotected_drill_fails_when_the_scenario_has_no_divergence`, `test_stale_feed_drill_fails_when_the_feed_is_fresh`) and the armed AST/recording tests are there so the drills cannot pass vacuously. Tracer gate: Task 1's verify (`tests/test_drills.py`) passed end to end before expansion; no `gate="blocking-human"` on the task.

**5. [Scenario note] The coordinator scenario in the F-604 test enters SAFE_MODE `ENTRY_WITHOUT_PROTECTIVE`, not `POSITION_WITHOUT_STOP`,** as its final reason (most urgent reason wins, plan 20-12). The UNPROTECTED drill therefore checks that `POSITION_WITHOUT_STOP` is among the tick's reasons rather than the final `entered_reason`; the loop-rig test asserts the final reason where it is `POSITION_WITHOUT_STOP`.

### Not done / limits

- `[NOT_TESTED]` Real stack: OPS-01's RUNBOOK rehearsal on a real host/Demo is Phases 25/26. G4-035 (what Binance does with a closePosition leg when the position is closed outside the system) is modelled by the fake only, both outcomes.
- The gate does not claim any owner item solved: D055, the `NOT_CONFIGURED` limit keys and the 11 Demo probes stay with the owner.
- The Phase 20 requirements are not marked complete; verification and the orchestrator own that.

## TDD Gate Compliance

No RED evidence for Tasks 1-2 (see deviation 4). Task 3's gate tests passed on first run because they pin existing state; they were sanity-checked for armedness (`test_invariant_2b_the_placement_guard_is_armed`).

## Verification (this plan's tests and tests of touched modules only; the full suite is the orchestrator's)

- `uv run pytest -m "not docker" tests/test_drills.py tests/test_reconcile.py tests/test_phase20_gate.py tests/test_phase19_gate.py tests/test_phase8_audit_reviewfix.py`: all passed, sequential.
- Plus `tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_reconcile_loop.py tests/test_manual_controls.py tests/test_safe_mode_exit_operator.py tests/test_cancel_verification.py tests/test_feed_freshness.py tests/test_journal_ids.py` with `-n 4`: all passed.
- `uv run ruff check`: all checks passed. `uv run ruff format --check`: clean. `uv run mypy src`: no issues in 235 source files.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `git diff --exit-code -- pyproject.toml uv.lock`: exit 0 (T-20-SC, no package added).
- `tests/test_reconcile.py::test_no_place_order_path_in_src_reconcile` passes unchanged.
- Line endings: the four edited existing Python files were converted to LF for editing and restored to CRLF (they show as stat-dirty in `git status` only; `git diff` is empty). The new gate file is LF.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; tests and an in-process drill harness only.

## Self-Check: PASSED

- `tests/test_phase20_gate.py`, `src/ops/drills.py`, `tests/test_drills.py`, `tests/test_reconcile.py`, `tests/fixtures/phase8/drill_log/expected.json` exist.
- Commits `73307289`, `49dea925`, `922e8a29` are ancestors of HEAD.
