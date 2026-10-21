---
phase: 20-reconcile-safe-mode-hardening
plan: 10
status: in-progress
requirements-addressed: [EXEC-02]
---

# Phase 20 Plan 10: UNKNOWN entry recovery (D-11) Summary

## Owner decision O-F

Recorded 2026-10-21 from the owner's answer given in the orchestrator session, after the orchestrator presented the D-01a evidence of plan 20-04 and explained D-11, D-15 and D-24. Four independent items, one line each; acceptance of one item never implies acceptance or verification of another. Plan 20-15 reads only the D-15 line; plan 20-22 reads only the D-24 line.

D-11: accept
D-15: accept
D-01a: accept
D-24: accept

The owner's own words, verbatim (Vietnamese):

> D-11 tôi accept, nhưng N lần ở đây là bao nhiêu lần, có thể recommend cho tôi 1 con số phù hợp được không

> D-15: ... (followed, after a further explanation, by:) D-15 accept

> D-24: accept

> D-01a: accept

The owner's D-11 question (how many probes N, `reconcile.entry_unknown_probe_count`) was answered by the orchestrator with a NON-BINDING suggestion of N = 3 with 5000 ms spacing. That suggestion is NOT applied: the numeric values of `reconcile.entry_unknown_probe_count` and `reconcile.entry_unknown_probe_interval_ms` stay `NOT_CONFIGURED` (owner decision O-G, after Demo evidence), and no number was written into `config/execution/execution-limits-v1.toml`. Tests use the TEST_ONLY values of plan 20-01 (3, 2345 ms, grace 9191 ms), which are not the owner's choice.

An owner accept of D-01a is a policy acceptance, not evidence. The evidence is the executed test result below.

### D-01a evidence (copied from 20-04-SUMMARY.md, section "D-01a bound check evidence")

Command: `uv run pytest -m "not docker" tests/test_reconcile_compare_v2.py -rA` (pure unit tests, `[DESIGN]`, no exchange, no [DEMO] claim). All results were executed in the plan 20-04 worktree at `36c420d9`; the full file: 117 passed.

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

- `[NOT_TESTED]` Behaviour against a real Binance position read or any Demo account: nothing was run against Binance (no network, no [DEMO]).
- `[NOT_TESTED]` That the loop (plans 20-12, 20-20) refuses stale or unreadable local data before calling compare. compare has no clock and cannot judge data age; this is the caller's job and is covered by those plans, not by plan 20-04.
- `[NOT_TESTED]` Equivalence of the per-symbol check with a per-plan check; it holds only while the Phase 19 one-plan-per-symbol pre-placement rule holds (premise stated in the compare docstring, not tested).

Documented limit: an over-fill still below the intended quantity is not detectable in Phase 20 (the check is a bound, `abs(exchange) <= intended_quantity`); exact fill-ledger reconciliation is Phase 24 (D-13).

<!-- gsd:write-continue -->
