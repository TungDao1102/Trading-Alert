---
phase: 20-reconcile-safe-mode-hardening
plan: 04
subsystem: reconcile
tags: [reconcile, compare, divergence, bound-check, order-ids, tdd]
requires: []
provides:
  - "compare v2: reverse pass, per-symbol signed bound check, STOP requirement, entry-aware orphan rule, duplicate-id and Hedge-row detection"
  - "eleven new DIVERGENCE_KIND_* constants (two are vocabulary only, for plan 20-16)"
  - "src.execution.order_ids: is_system_client_id, plan_hash_prefix_of, role_of_client_id, SYSTEM_ID_PREFIXES"
  - "optional carrier fields LocalOrderIntent/LocalAlgoIntent.plan_hash and LocalPositionIntent.plan_hash/expected_side/max_abs_amount"
affects: [20-10, 20-12, 20-20]
tech-stack:
  added: []
  patterns: ["pure transform with duck-typed carriers", "fail closed on missing local data"]
key-files:
  created:
    - tests/test_reconcile_compare_v2.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-04-SUMMARY.md
  modified:
    - src/reconcile/compare.py
    - src/execution/order_ids.py
    - tests/test_reconcile.py
    - tests/test_drills.py
    - tests/fixtures/phase8/orphan_divergence/input.json
decisions:
  - "Bound check is per symbol, sign before bound, strictly fail closed: it only adds divergences (D-01a, owner confirmation O-F still pending, so not described as owner-confirmed)."
  - "Exposure whose local owner lacks plan_hash, expected_side or a positive Decimal max_abs_amount is AMBIGUOUS_POSITION_OWNER, never an agreement (T-20-68)."
  - "TP_ONLY_POSITION means no system STOP_LOSS row at all but at least one TP leg; a system STOP_LOSS row that is not in the ACTIVE class gives POSITION_WITHOUT_STOP."
  - "The resting-entry exemption of the orphan rule covers local NEW / PARTIALLY_FILLED entries and any ENTRY open on the exchange; PLANNED / SUBMITTING are deliberately not exempted (the exemption only narrows what the sweeper may cancel)."
metrics:
  duration: "about 1h"
  completed: 2026-10-21
status: complete
actuals:
  tokens: 15400
  tasks: 3
  commits: 6
plan_head_before: 9d8a9b0e6b4b532b525c64424dd37bebb0b679d7
plan_head_after: 36c420d9927a43262ebd307b0fb1019c02efb936
---

# Phase 20 Plan 04: Compare v2 Summary

The pure three-source compare now sees what it was blind to: exchange orders nobody local owns, doubled or sign-flipped exposure (as a per-symbol bound check), positions with no ACTIVE system stop, TP-only positions, ambiguous owners, Hedge rows, duplicate exchange ids, and a resting entry's protective is no longer called an orphan. The five original kinds keep their names, meaning and string values.

All three tasks were finished. The Task 2 / Task 3 context-budget split was NOT used.

Base commit `9d8a9b0e`; branch `worktree-agent-afc6162ba67250ee6`; `commits: 6` is the measured `git rev-list --count 9d8a9b0e..HEAD` taken at SUMMARY write, before the SUMMARY commit itself.

## What was built

- `src/execution/order_ids.py`: `is_system_client_id`, `plan_hash_prefix_of` (the 29 plan-hash characters shared by the x-, xa- and xc- families), `role_of_client_id` (ENTRY / STOP_LOSS / TAKE_PROFIT_1 / TAKE_PROFIT_2 for x- and xa- ids, None for xc- and foreign), `SYSTEM_ID_PREFIXES`. Built only from the existing prefix constants, slice lengths and `ROLE_CODES`; no new prefix or role-code literal.
- `src/reconcile/compare.py`:
  - eleven new `DIVERGENCE_KIND_*` constants in the vocabulary (STREAM_SINK_FAILURE and STREAM_TASK_DIED are vocabulary only, emitted by plan 20-16);
  - reverse pass: FOREIGN_ORDER (id lacks this system's prefix, or no id) and UNTRACKED_SYSTEM_ORDER (prefix present, no local intent); neither enters `orphan_protectives`;
  - DUPLICATE_EXCHANGE_ID for a repeated client_order_id or client_algo_id in the exchange truth (first row kept for lookups, one divergence per id);
  - per exchange position: Hedge row (position_side LONG or SHORT) is UNSUPPORTED_POSITION_SIDE; a position with no local intent keeps UNSYNCED_POSITION; otherwise ownership, sign check, bound check; then the STOP requirement;
  - entry-aware orphan rule (D-05 code part), `None` source raises `TypeError`, non-Decimal or non-finite exchange `position_amt` raises (`TypeError` / `ValueError`).
- `compare.py` imports only stdlib, `src.domain` (enums, algo_status) and the pure id predicates; no prefix literal (AST-tested); no float constructor, no wall clock (AST-tested).

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 3 - Blocking] The plan documents were not in the worktree base**
- **Found during:** read-first. Base `9d8a9b0e` predates the Phase 20 documents (they are on `develop`).
- **Fix:** read 20-04-PLAN.md, 20-REVIEW-RESOLUTIONS.md and 20-CONTEXT.md read-only with `git show develop:<path>`, as the orchestrator confirmed. Nothing was checked out and the base was not changed. Nothing built differs from those versions.

**2. [Rule 3 - Blocking] `tests/fixtures/phase8/orphan_divergence/input.json` edited although not in the plan's `files_modified`**
- **Found during:** Task 3. The fixture models a local protective with its plan's ENTRY open locally (NEW) and on the exchange, and asserts ORPHAN_PROTECTIVE. By D-05 that is exactly the case that is no longer an orphan, so the stricter rule turned `test_orphan_protective_divergence_classified_and_swept` and `test_transient_position_gap_blocks_premature_sweep` red.
- **Fix:** fixture only. The resting ENTRY was removed from `local_intent.open_orders` and `exchange_truth.normal_orders` (the scenario is "the entry is gone, the protective is left over") and the description was reworded. `expected.json` and every assertion are unchanged.
- **Commit:** 36c420d9

**3. [Rule 1 - Bug in fixtures] Split state failed for a second reason than the plan predicted**
- The plan predicted the known-red consumer tests would fail through AMBIGUOUS_POSITION_OWNER (position intents lacking the new fields). After Task 2 the two failing tests actually failed because their positions carry `position_side: "LONG"`, which is a Hedge row (UNSUPPORTED_POSITION_SIDE). Same fix class: fixture only (below).

## TDD Gate Compliance

Tracer first, then two RED/GREEN pairs. Commits in order: `72f6cbf1` test, `83d01578` feat (Task 1); `28b7502d` test, `667334ba` feat (Task 2); `1944a686` test, `36c420d9` feat (Task 3). No REFACTOR commit.

RED evidence (pytest failures seen before each GREEN commit; `gsd_run check tdd-red-evidence` does not parse pytest output and was not run):
- Task 1 RED: new-name tests failed with `AttributeError` on the not-yet-existing predicates / constants and on `SYSTEM_ID_PREFIXES`; the reverse-pass tests failed on `assert diff.agreement is False` (compare returned agreement True). The tests use module attribute access so collection does not error. The five-original-kinds test, the clean fixture and the import-purity test passed in RED by design (regression guards).
- Task 2 RED: most tests failed with `TypeError` constructing `LocalPositionIntent` with the not-yet-existing fields; Hedge, None-source, duplicate-id, TP-only and non-Decimal tests failed on their own assertions. This is partly "TypeError from a missing field" rather than a pure assertion failure; stated honestly.
- Task 3 RED: 12 parametrized `test_protective_of_a_resting_entry_is_never_an_orphan` cases and `..._only_on_the_exchange...` failed on assertion; terminal / absent / other-plan entry tests passed in RED (regression guards for the narrower side of the rule).

Tracer feedback gate: re-ran the Task 1 verify after the tracer commit (45 passed, consumer suites passed); no `gate="blocking-human"` on the task.

## D-01a bound check evidence

Command: `uv run pytest -m "not docker" tests/test_reconcile_compare_v2.py -rA` (pure unit tests, `[DESIGN]`, no exchange, no [DEMO] claim). All results below were executed in this worktree at `36c420d9`; full file 117 passed. D-01a is a review resolution the owner has not confirmed (O-F); this is the evidence plan 20-10 cites, and acceptance there is a policy acceptance, not a substitute for it.

| Test (tests/test_reconcile_compare_v2.py) | What it shows | Result |
|---|---|---|
| test_a_protected_in_bound_long_position_agrees | LONG +0.004 against intended 0.004 with ACTIVE system SL: agreement | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [LONG +0.004] | LONG, positive: agrees | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [LONG -0.004] | LONG, negative: SIGN_FLIPPED_POSITION | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [SHORT -0.004] | SHORT, negative: agrees | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [SHORT +0.004] | SHORT, positive: SIGN_FLIPPED_POSITION | PASSED |
| test_a_flipped_sign_that_also_exceeds_the_bound_is_sign_flipped_only | LONG -0.008 and SHORT +0.008: one kind, SIGN_FLIPPED_POSITION (sign before bound) | PASSED |
| test_bound_is_abs_exchange_at_most_intended_quantity [LONG 0.004 / SHORT -0.004] | equality agrees | PASSED (2 cases) |
| test_bound_is_abs_exchange_at_most_intended_quantity [LONG 0.005 / SHORT -0.005] | intended + 0.001: DOUBLED_POSITION | PASSED (2 cases) |
| test_bound_is_abs_exchange_at_most_intended_quantity [LONG 0.008 / SHORT -0.008] | 2x intended: DOUBLED_POSITION | PASSED (2 cases) |
| test_bound_check_cannot_see_an_overfill_below_the_intended_quantity | +0.003 against intended 0.004 AGREES: the documented limit (an over-fill below the bound is invisible) | PASSED |
| test_missing_local_bound_data_fails_closed [no-plan-hash, empty-plan-hash] | missing plan_hash: AMBIGUOUS_POSITION_OWNER, agreement False | PASSED (2 cases) |
| test_missing_local_bound_data_fails_closed [no-expected-side, unknown-expected-side] | missing / invalid expected_side: AMBIGUOUS_POSITION_OWNER | PASSED (2 cases) |
| test_missing_local_bound_data_fails_closed [max-none, max-zero, max-negative, max-str, max-float, max-int, max-nan] | max_abs_amount None / zero / negative / not a Decimal / NaN: AMBIGUOUS_POSITION_OWNER | PASSED (7 cases) |
| test_none_source_is_refused_not_read_as_empty [each of the six sources] | a None source raises TypeError naming the source, no CompareDiff returned | PASSED (6 cases) |
| test_two_local_plans_on_one_symbol_is_ambiguous_and_never_picks_one | two plan hashes on one symbol: only AMBIGUOUS_POSITION_OWNER, no DOUBLED / SIGN_FLIPPED | PASSED |
| test_one_plan_hash_repeated_consistently_is_one_owner | the same plan repeated with identical data agrees | PASSED |
| test_one_plan_hash_repeated_with_different_bounds_is_ambiguous | the same plan with conflicting bounds: AMBIGUOUS_POSITION_OWNER | PASSED |
| test_a_non_decimal_exchange_position_amount_raises_type_error [str, float, int, None] | exchange amount never converted: TypeError | PASSED (4 cases) |
| test_compare_v2_has_no_float_constructor_and_no_wall_clock | no `float(...)` call and no clock read in compare.py and order_ids.py | PASSED |

Not shown by any executed test, labelled `[NOT_TESTED]`:
- `[NOT_TESTED]` Behaviour against a real Binance position read or any Demo account: nothing here was run against Binance (no network, no [DEMO]).
- `[NOT_TESTED]` That the loop (plans 20-12, 20-20) refuses stale or unreadable local data before calling compare. compare has no clock and cannot judge data age; this is the caller's job and is covered by those plans, not by this one.
- `[NOT_TESTED]` Equivalence of the per-symbol check with a per-plan check; it holds only while the Phase 19 one-plan-per-symbol pre-placement rule holds (premise stated in the compare docstring, not tested here).

An over-fill still below the intended quantity is not detectable in Phase 20; exact fill-ledger reconciliation is Phase 24 (D-13).

D-13 deferred: positions/fills ledger and update_position_snapshot (G4-043) are Phase 24; exact signed comparison against fills attributed by client order id is Phase 24. Nothing of it was built (`git diff --stat -- src/persistence/entities.py` prints nothing).

## Consumer fixture edits

No assertion was removed or loosened. Each edit adds the missing carrier field or removes a state the stricter rule now classifies differently.

| File | Test / builder | Edit |
|---|---|---|
| tests/test_reconcile.py | test_clean_compare_yields_agreement_with_zero_divergences | local position gains `plan_hash` ("1"*64), `expected_side` LONG, `max_abs_amount` Decimal 0.010; local and exchange position_side LONG changed to BOTH (a LONG row is a Hedge row, UNSUPPORTED_POSITION_SIDE) |
| tests/test_reconcile.py | test_divergence_forces_safe_mode_without_cancel | phantom exchange position_side LONG changed to BOTH, so it is still the UNSYNCED_POSITION the test asserts (it now also carries POSITION_WITHOUT_STOP) |
| tests/fixtures/phase8/orphan_divergence/input.json | used by test_orphan_protective_divergence_classified_and_swept and test_transient_position_gap_blocks_premature_sweep | resting ENTRY removed from local open_orders and exchange normal_orders (D-05: with the entry open the protective is not an orphan); description reworded; expected.json untouched |
| tests/test_drills.py | _build_orphan_scenario (also reused by _build_manual_close_scenario) | same: no resting ENTRY locally or on the exchange; docstring updated |

No existing test asserted the old blind behavior on purpose, so none was rewritten to a new rule.

Not edited, observed: `_build_unprotected_scenario` in tests/test_drills.py still has position rows with position_side LONG. The drill only asserts ENTRY_WITHOUT_PROTECTIVE (still produced), so it passes with the extra new divergences; left as is. `tests/test_controller_rehydrate.py`, `tests/test_phase8_audit_reviewfix.py` and `tests/test_journal_failure_paths.py` needed no edit.

## Verification (only this plan's tests were run)

- `uv run pytest -m "not docker" tests/test_reconcile_compare_v2.py tests/test_reconcile.py tests/test_drills.py tests/test_controller_rehydrate.py tests/test_phase8_audit_reviewfix.py tests/test_journal_failure_paths.py` : 278 passed.
- Also run because they exercise the two touched modules: `tests/test_order_ids.py tests/test_phase19_gate.py` (53 passed); `tests/test_execution_secret_posture.py tests/test_execution_manager.py tests/test_paper_shadow_isolation.py` (197 passed). The full suite was not run (orchestrator).
- `uv run mypy src` : no issues in 214 source files. `uv run ruff check` and `uv run ruff format --check` : clean.
- `git diff --exit-code -- pyproject.toml uv.lock` : exit 0 (T-20-SC, no package added).
- Line endings preserved (working tree CRLF, index LF, as for the other files in this repo).

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or file access; compare stays a pure transform. T-20-08, T-20-10 and T-20-68 are mitigated as planned; T-20-09 is accepted (a UI order carrying this system's prefix is UNTRACKED_SYSTEM_ORDER, still a divergence, never sweepable).

## Notes for dependents

- 20-12 must build `LocalPositionIntent.plan_hash / expected_side / max_abs_amount` and pass real local algo intents for every confirmed system stop (an exchange algo with no local intent is UNTRACKED_SYSTEM_ORDER); it must refuse stale local data before calling compare.
- 20-20 owns the SAFE_MODE reason and policy for AMBIGUOUS_POSITION_OWNER (O-D) and the failed-local-read path.
- The source-position row of a One-way account is `position_side` BOTH; LONG / SHORT rows are refused.

## Self-Check: PASSED

- FOUND: src/reconcile/compare.py, src/execution/order_ids.py, tests/test_reconcile_compare_v2.py, tests/fixtures/phase8/orphan_divergence/input.json, tests/test_drills.py, tests/test_reconcile.py
- FOUND commits: 72f6cbf1, 83d01578, 28b7502d, 667334ba, 1944a686, 36c420d9
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, params/, pyproject.toml, uv.lock
