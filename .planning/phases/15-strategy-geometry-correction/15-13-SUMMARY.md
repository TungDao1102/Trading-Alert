---
phase: 15-strategy-geometry-correction
plan: 13
subsystem: core-planner
tags: [planner, geometry-validator, legacy-sets, property-test, tdd, tracer]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-04 _geometry_rejection and its gated call; 15-07 property grid; 15-12 consumers moved to the v6 sets"
provides:
  - "plan() calls _geometry_rejection exactly once for every parameter set (legacy and geometry_version 1) and all three families; no geometry_version condition around the call"
  - "legacy regression tests: legacy Family A is STOP_TOO_TIGHT end to end, legacy B and C are INVALIDATED when the signal bar is through the stop, passing legacy B/C plans keep their plan_hash (pre-change literals)"
  - "AST guard: no enclosing if of the single call (and no plan()-level early return before it) tests geometry_version"
  - "property test legacy dimension (486 cells, three families, both directions), non-vacuous"
affects: [15-15]

actuals:
  tokens: 14500
  tasks: 2
  commits: 2
plan_head_before: 8d39405af82c68fa74b1215226bb51e45eddd3ac
plan_head_after: 3d3a0723babf69a01aaa392c74c9f6657a552777
commits: 2

key-files:
  modified:
    - src/core/planner.py
    - tests/test_planner_geometry.py
    - tests/test_geometry_property.py

key-decisions:
  - "No parameter, guard or registry value was chosen or tuned. The only production change is the removal of the geometry_version condition around the validator call (and the plan() docstring)."
  - "Legacy Family A stays able to emit its legacy signal (evaluate unchanged) but can never produce a plan whose stop is inside the zone (research A4, D-06)."
  - "Two sidecar legacy-contrast tests were migrated, not deleted, because their old assertion (a READY legacy plan with the stop inside the zone / signal bar below the stop) is now exactly the bug D-06 forbids; their sidecar numbers are kept as the stated reason."

requirements-completed: [STRAT-02]

duration: ~55min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 13: Validator universal, legacy consequences pinned, suite green Summary

**The shared structural validator (D-06/D-07/D-08/F6, fixed order before the RR gate) now runs for every parameter set; a legacy Family A plan is STOP_TOO_TIGHT, a legacy B/C signal bar through the stop is INVALIDATED, passing legacy B/C plans keep their exact plan_hash, and the file-by-file suite shows 0 failures.**

## Accomplishments

- Task 1 (tracer, c505040): RED first. The new tests were written against the old gated call site and captured the pre-change plan hashes of three passing legacy windows as literals (they passed before and after, which is the point of a pin). Eight tests were red for the right reasons (validator not called on legacy sets). GREEN: `src/core/planner.py` plan() lost the `if geometry_version(parameter_set) is not None:` wrapper; `min_stop_atr` is read with `params.get` (legacy sets carry none, so D-08 is skipped for them as before). The docstring now states the universal contract. Tracer command from the plan (`test_planner_geometry`, `test_core_planner`, `test_core_tracer`, `test_core_strategy_geometry`) is green, as are the breakout-retest and range-mr strategy files whose legacy plan_hash pins did not move.
- Task 2 (3d3a072): `tests/test_geometry_property.py` gained a legacy dimension (`LEGACY_FAMILIES`, `_legacy_grid`, shared `_assert_invariants`; the v1 grid, its 972 cells and its tests are unchanged). The full suite was then run file by file; no residue test outside the two sidecar contrast tests needed migration.

## Test names required by the plan (all in tests/test_planner_geometry.py)

- `test_legacy_family_a_stop_too_tight_end_to_end`, `test_legacy_family_a_registry_baseline_v5_never_plans`
- `test_legacy_b_invalidated_when_the_signal_bar_is_through_the_stop`, `test_legacy_b_touching_the_stop_is_invalidated_and_above_it_plans`
- `test_legacy_c_invalidated_when_the_signal_bar_is_through_the_stop`, `test_legacy_c_above_the_stop_still_plans`
- `test_legacy_plan_hash_unchanged_for_plans_that_satisfy_the_invariants`
- `test_legacy_tp1_on_the_loss_side_is_rr_too_low_through_plan[b|c]` (spy on `_geometry_rejection` feeding a loss-side TP1: proves the call happens exactly once on legacy B and C and that F6 maps to RR_TOO_LOW; legacy geometry cannot produce a loss-side TP1 on its own windows, so the real validator verdict is exercised through the spy)
- `test_geometry_rejection_call_is_not_gated_by_geometry_version` (AST)

## Legacy consequences (D-06, D-07, F4, F6), hand facts

| Legacy case | Window | Before | After |
| --- | --- | --- | --- |
| Family A, baseline-v5 style (sidecar a_long_legacy_contrast) | family_a_long_window: stop 97.60, entry zone 96.80..99.20 | READY plan, plan_hash 821f8f85...2cc2 | signal unchanged, plan NO_TRADE STOP_TOO_TIGHT |
| Family B (sidecar b_long_legacy_contrast) | evaluated bar low 102, legacy stop 102.60 | READY plan, plan_hash df3d040d...e6b3 | signal unchanged, plan NO_TRADE INVALIDATED |
| Family B, bar low 102.5 (stop 102.607) | | READY | INVALIDATED (touching counts) |
| Family B, bar low 102.7 (stop 102.61) | | plan_hash 4c998fb7...a595 | same hash (pre-change literal) |
| Family C legacy (flat 4h), crash bar low 95, touch tolerance 2.0, stop 97.557 | | READY plan, plan_hash f8f0cc6c...e12af1e5 | INVALIDATED |
| Family C legacy base (low 98, stop 97.60) | | plan_hash 4b849e87...da28 | same hash |
| Family C legacy, low 97.7 | | plan_hash 523151f7...ebd5 | same hash |

The legacy plan_hash pins in `tests/test_core_strategy_breakout_retest.py` (baseline-v1 and baseline-v5, long and short) did not move: those plans already satisfy the invariants.

## Property test (D-18)

Legacy grid: 3 families x 2 directions x 3 tolerances x 3 entry buffers x 3 stop buffers x 3 ATRs = 486 cells, legacy parameter shapes (`geometry_version` and `min_stop_atr` asserted absent per cell). Outcome counts: Family A 12 plans and 150 refused (STOP_TOO_TIGHT); Family B 18 plans, 54 INVALIDATED, 36 STOP_TOO_TIGHT, 54 NO_TRADE_REGIME at the strategy stage; Family C 72 plans, 36 STOP_TOO_TIGHT, 54 NO_TRADE_REGIME. Every produced plan satisfies the literal Decimal invariants; every refusal reason is in the closed set.

Non-vacuity: with `_geometry_rejection` replaced by a function returning None (one-off script, not committed), 222 of the legacy grid plans violate the invariants, so the legacy tests fail without the universal call. Legacy Family A plans exist only where `sl_buffer_atr > zone_tolerance_atr + entry_buffer_atr` (stated and asserted; the test does not require any, 12 happen to exist at sl_buffer 0.5).

## Regeneration inventory

- **Hashes that moved:** none among committed pins, fixtures or digests. The only changed outcomes are the sidecar legacy contrast cases for Families A and B (above), which are computed in tests, not pinned in a committed file.
- **Residue tests migrated (2, both in tests/test_planner_geometry.py, assertions kept as facts and re-pointed at the new verdict):**
  - `test_a_long_legacy_contrast_keeps_the_stop_inside_the_zone` became `test_a_long_legacy_contrast_stop_inside_the_zone_is_now_stop_too_tight` (sidecar facts stop 97.60 > entry_min 96.80 retained; plan is STOP_TOO_TIGHT).
  - `test_b_long_legacy_contrast_keeps_the_code_stop_edge_minus_sl_buffer` became `test_b_long_legacy_contrast_signal_bar_through_the_code_stop_is_now_invalidated` (sidecar stop 102.60 retained; bar low 102 asserted; plan INVALIDATED; signal identity assertion unchanged).
  - `test_legacy_set_is_not_subject_to_the_validator` was removed: it asserted the behavior this plan removes, and its job is taken by the new legacy tests.
- **No other test file needed a change.** `tests/test_core_strategy_breakout_retest.py` and `tests/test_core_strategy_range_mr.py` were not modified (their legacy builders already produce plans that satisfy the invariants).
- **Stale docstring for D054 (not edited, per the plan):** `src/risk/gating.py` `_plan_geometry_is_valid` docstring says "A stop inside the zone is deliberately NOT rejected here: the Phase 6 strategy fixtures emit such plans, and changing plan generation is outside the cost-model fix." Both halves are now untrue (the planner rejects a stop inside the zone for every set and the Phase 6 fixtures were regenerated in 15-12). The guard itself is unchanged and still correct as a defensive check.
- **Known limitation recorded for D054 (T-15-23, accepted):** the planner has no tick size; a stop within one price tick of the zone edge could be snapped by the risk layer. `sl_buffer_atr x ATR` is far above one tick on traded symbols (research Pitfall 3).
- **PostgreSQL-dependent tests (local environment, skipped without TEST_DATABASE_URL, left to CI):** 19 files, all skipped (not errored): test_approval_replay_pg, test_callback_redelivery_pg, test_constraint_snapshot_pg, test_domain_mappers_pg, test_execution_exactly_once_pg, test_execution_write_ahead_pg, test_intent_recovery_pg, test_persistence_approvals_pg, test_persistence_constraints_pg, test_persistence_engine_pg, test_persistence_enum_columns_pg, test_persistence_journal_pg, test_persistence_migration_pg, test_persistence_roundtrip_pg, test_persistence_transitions_pg, test_persistence_triggers_pg, test_persistence_uow_pg, test_plan_hash_roundtrip_pg, test_system_state_pg.
- **Excluded from local runs (Git Bash hang, per the executor brief):** tests/test_bootstrap.py, tests/test_deploy_backup_scripts.py, tests/test_docker_backup_drill.py, tests/test_docker_backup_remote.py, tests/test_docker_cutover.py, tests/test_docker_image.py.

## Full-suite result

File by file (`pytest <file> -o addopts= -q -p no:cacheprovider`, 194 files, 6 excluded): **4387 passed, 0 failed, 430 skipped, 0 errors**. The 15-12 baseline was 4292 passed, 0 failed, 430 skipped over 193 files; the difference is +95 passed (new legacy and property tests plus `tests/test_case_input_builder.py`, 23 tests, which ran to completion in this run rather than crashing with the access violation noted for the pre-plan baseline; the crash did not reproduce, nothing was changed for it).

Quality gates: `ruff check src tests scripts` clean, `ruff format --check src tests scripts` 388 files already formatted, `mypy src` no issues in 149 source files.

Skip/xfail markers: `grep -rhoE "pytest\.mark\.(skip|xfail)|pytest\.skip\(" tests --include=*.py | wc -l` is **15 before Task 1 and 15 after Task 2**. No test gained a skip or xfail.

## Deviations from Plan

None - plan executed exactly as written. (No Rule 1-4 deviation occurred; the migrated tests are the plan's own residue path.)

## Known Stubs

None.

## Threat Flags

None. T-15-22 is mitigated as planned (single unconditional call proven by AST test, legacy regression tests, property test over legacy and v1 shapes).

## Self-Check: PASSED

- src/core/planner.py, tests/test_planner_geometry.py, tests/test_geometry_property.py exist and carry the changes above.
- Commits c505040 (Task 1) and 3d3a072 (Task 2) exist on develop.
