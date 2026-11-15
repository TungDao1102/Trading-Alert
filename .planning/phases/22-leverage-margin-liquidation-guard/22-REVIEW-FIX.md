---
phase: 22-leverage-margin-liquidation-guard
fixed_at: 2026-10-25T00:00:00Z
review_path: .planning/phases/22-leverage-margin-liquidation-guard/22-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 22: Code Review Fix Report

**Fixed at:** 2026-10-25
**Source review:** `.planning/phases/22-leverage-margin-liquidation-guard/22-REVIEW.md`
**Iteration:** 1
**Branch / worktree:** `worktree-agent-a48479aa1c95a93e0`, fast-forwarded to `develop` at `f25d89ce` before
the first fix (the worktree had been cut from an older commit that did not contain Phase 20 to 22)

**Summary:**

- Findings in scope: 9 (WR-01 to WR-09; the review has zero Critical; Info only where trivial)
- Fixed: 9 (two of them partly: see "Left for the owner or Phase 24" under WR-04, WR-05, WR-06)
- Skipped: 0
- Owner decisions D085 and D086 untouched (x5 ISOLATED, buffer 300 bps, bracket age 60000 ms, headroom
  1000 bps, `CLOSE_POSITION`); no `params/**/*.toml` edit; no `float(`; no wall clock in a pure module;
  no new default of an owner number; **no migration** (the head stays `0012_reservation_margin`).

Verification: ran in the agent worktree, not in the main checkout (a worktree-env run is not reproducible
from the main checkout after teardown). `TEST_DATABASE_URL` was set in the environment, so the `*_pg.py`
file of the reservation fix ran against PostgreSQL and was not skipped. Not the full suite, not a recorded
gate. Files run: `test_margin_guard`, `test_symbol_config_guard`, `test_bracket_cache`,
`test_snapshot_margin_leverage`, `test_liquidation_watch`, `test_protection_liquidation`,
`test_risk_reservations`, `test_risk_reservation_margin_pg`, `test_margin_check`, `test_execution_manager`,
`test_demo_rehearsal_flow`, `test_demo_rehearsal_safety`, `test_paper_shadow_isolation`, `test_phase19_gate`,
`test_live_risk_inputs`, `test_manual_controls`, `test_modeled_costs_none_guard`, `test_phase22_gate`,
`test_decision_alignment_bookkeeping`: all passed. `ruff check`, `ruff format --check` on `src`, `scripts`
and the touched tests, and `mypy src` (253 files): clean. `scripts/verify_decision_alignment.py all`:
`ALL_PASS`.

## Fixed Issues

### WR-01: configuration POSTs sent for plans the guard then refuses

**Files modified:** `src/execution/margin_guard.py`, `src/execution/symbol_config_guard.py`,
`tests/support/margin_guard_fakes.py`, `tests/test_margin_guard.py`
**Commit:** `dd0c4758` (together with WR-09, one code path)
**Status:** fixed: requires human verification (ordering logic)
**Applied fix:** `MarginGuard.evaluate` now runs: account mode, bracket read plus `liquidation_verdict` at the
TARGET leverage, claims plus `margin_verdict` at the target leverage (all before any symbolConfig read or
POST), then `ConfigGuardPort.ensure` (the only mutating step), then the one comparison that needs the
verified configuration (notional within `maxNotionalValue`), then a third reading and bracket freshness
judgement after the configuration step. `ConfigGuardPort` exposes `target_leverage` (a property on
`SymbolConfigGuard`). The verified leverage must equal the target the checks were judged at. One POST per
kind, never retried, the verification read still decides. A refusal before the configuration step carries
no mutation evidence (`config_changed` False).
**Tests:** `test_a_plan_refused_by_a_pure_check_leaves_the_recorded_account_untouched` (5 cases on the
recorded CROSSED x20 symbol: no read of the configuration, no POST, symbol still CROSSED x20),
`test_a_repeated_refused_attempt_never_posts_while_the_plan_stays_unplaceable`,
`test_a_passing_plan_sends_each_post_once_and_the_verification_read_decides`,
`test_the_guard_judges_the_pure_checks_at_the_target_of_its_configuration_port`,
`test_a_refusal_after_a_post_carries_the_evidence_to_the_end_of_the_chain` (now a post-config
`NOTIONAL_ABOVE_MAX`); the line-184 test (`test_a_reading_that_ages_during_the_bracket_and_configuration_reads_is_refused`)
now documents the third judgement; the scenario matrix and `test_the_first_refusal_in_the_fixed_order_wins`
were rewritten for the new order (account mode, liquidation, margin, configuration).
**Observable change:** a plan that is both over `maxNotionalValue` and too close to liquidation is now
reported as the liquidation/margin refusal, not `NOTIONAL_ABOVE_MAX`; and `NOTIONAL_ABOVE_MAX` can only
come after a POST was sent when the symbol was not yet at the target.

### WR-02: gate 5f2 adds about eight REST calls before the consume

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** `9912b549`
**Status:** fixed (a)(b)(c in process); the DB-level arbiter is not built (see below)
**Applied fix:** (a)(b) new gate 5f4 (named 5f3 when written; renamed on 2026-10-25 because the
Phase 21 equity comparison already holds 5f3): after the guard passes, the same pure `evaluate_pre_placement` runs
again with a clock read after the guard (mark and last price age, remaining validity before the
`goodTillDate` floor); readings unchanged, so it can only tighten; an unreadable clock refuses like gate 5e.
(c) `_one_placement_per_symbol`, a decorator on `execute_approved_plan`: a SECOND approval of a symbol that
another approval is placing in this process is refused with the existing `SYMBOL_HAS_OPEN_ORDER` before any
gate; a replay of the SAME approval is not refused (it still reaches the stored-outcome replay and the
consume race exactly as before) and never frees another call's slot; the slot is freed in `finally`
(also on a `BaseException`). The claim is atomic on one event loop (no await between check and claim).
**Tests:** `test_a_mark_price_that_ages_during_the_guard_is_refused_before_the_consume`,
`test_the_remaining_validity_is_measured_after_the_guard`,
`test_a_guard_that_takes_no_time_still_places_with_the_recheck_in_place`,
`test_a_second_approval_of_the_symbol_is_refused_while_the_first_is_in_flight`,
`test_a_replay_of_the_same_approval_is_not_refused_by_the_symbol_slot`,
`test_the_symbol_slot_is_freed_when_the_placement_raises`; the two clock-count tests of CR-01 were updated
(the clock is now read twice: after the gate 5e reads and after the guard).
**Left for the owner or Phase 24:** a DB-level partial unique index on open entry intents per symbol (the
review's second arbiter) needs a migration; the in-process slot does not protect two processes. Not done.

### WR-03: a restored plan has no verified leverage, so the watch closes a healthy position

**Files modified:** `src/execution/liquidation_watch.py`, `tests/test_liquidation_watch.py`,
`tests/test_protection_liquidation.py`
**Commit:** `b372a89f`
**Status:** fixed: requires human verification
**Applied fix:** the persisted snapshot is write-once by design (append-only trigger, `UNKNOWN` leverage),
so nothing is persisted. `LiquidationWatch.check` no longer treats a missing leverage as an unknown input:
the strict predicate needs only the exchange value, the stop, the fill price and the buffer. `None`
leverage only skips the local comparison (`local_price` None, no bracket call); a leverage below one stays
unknown, and an unknown exchange value or a value inside the buffer still fails by policy.
**Tests:** `test_a_missing_leverage_does_not_decide_a_passing_exchange_value` (both policies),
`test_a_missing_leverage_still_fails_an_exchange_value_inside_the_buffer`,
`test_a_missing_leverage_does_not_soften_an_unknown_exchange_value`,
`test_a_plan_without_a_leverage_is_not_closed_when_the_value_is_far_away` (the real watch through the
coordinator hook with a snapshot whose leverage is `None`: no B6 transition, no close),
`test_a_plan_without_a_leverage_is_still_closed_when_the_value_is_inside_the_buffer`.

### WR-04: the coordinator closes on its own error paths under ALERT_ONLY

**Files modified:** `src/execution/protection.py`, `src/execution/liquidation_watch.py` (port docstring),
`tests/test_protection_liquidation.py`
**Commit:** `91de0b78`
**Status:** fixed: requires human verification (policy semantics, smallest change)
**Applied fix:** on the three error paths (watch raises, position row not convertible, wrong verdict type)
the coordinator reads `getattr(watch, "policy", None)`: only an EXPLICIT `LiquidationFailurePolicy.ALERT_ONLY`
journals `PROTECTION_LIQUIDATION_CHECK_ERROR` and raises the `LIQUIDATION_UNKNOWN_AFTER_FILL` alert, without
closing. `CLOSE_POSITION` (the owner's choice, D085) and a watch without a readable policy keep the
fail-closed close, so behaviour under D085 is unchanged.
**Tests:** `test_alert_only_policy_alerts_instead_of_closing_on_the_error_paths` (raises, wrong type,
bad row; once per plan), `test_close_position_policy_still_closes_on_the_error_paths`.

### WR-05: OK_DIFFERS raises a critical DIVERGENCE alert on the normal case

**Files modified:** `src/execution/protection.py`, `docs/GLOSSARY.md`, `tests/test_protection_liquidation.py`
**Commit:** `6eec1942`
**Status:** fixed: requires human verification (alerting policy, smallest change)
**Applied fix:** `OK_DIFFERS` is journal-only (`PROTECTION_LIQUIDATION_PRICE_DIFFERS` keeps both exact prices);
the `_liquidation_alert` call is removed. `ALERT_ONLY_FAILED` still alerts. GLOSSARY rows and the module
docstring state it. No tolerance number was invented.
**Left for the owner:** an alert on a difference needs an owner-set tolerance (a new `NOT_CONFIGURED`
key); until calibration data exists the journal row is the record. Needs-owner only if the owner wants the
alert back.
**Tests:** `test_ok_differs_journals_both_exact_prices_and_raises_no_alert` (replaces the test that pinned
the alert).

### WR-06: the margin-claims circuit is not closed

**Files modified:** `src/risk/reservations.py`, `src/persistence/risk_reservations.py`,
`src/risk/margin_check.py`, `tests/test_phase22_gate.py`
**Commit:** `749b32f4` (together with WR-07)
**Status:** fixed in part; the rest needs the owner or Phase 24 (below)
**Applied fix:** (a) the reader no longer returns an unknown claim for a Phase 22 row: `required_margin`
is derived from `quantity`, `margin_entry_price` and `margin_leverage` (see WR-07); a legacy row without a
trio stays UNKNOWN (never zero). (b) `placed_at_utc` is defined in code: it is the instant read from the
process clock AFTER the exchange acknowledged the entry (the POST answer or the probe that found it) and
never before the POST. Because `LiveEquitySource.refresh` stamps the reading from the same clock before its
first request, `placed_at_utc <= stamp` proves the exchange already held the order, so no skew number is
needed. Written into `PgRiskReservationStore.mark_placed`, `MarginClaim` and `list_margin_claims`.
**Tests:** `test_invariant_21_the_claim_amount_is_derived_and_the_placed_instant_is_the_ack` in
`test_phase22_gate.py` (docstring contract, derivation call, reading stamp), plus the existing netting
boundary `test_other_claims_margin_netting`.
**Left for the owner or Phase 24 (not done on purpose):**

- Release of a RESERVED row after an `INSUFFICIENT_MARGIN` / `LIQUIDATION_TOO_CLOSE` refusal (the
  review's (c)). `release_reason_for_placement_refusal` returns `None` for margin refusals because the
  refusal is retryable and a RELEASED row cannot be reserved again; changing that is a lifecycle decision.
  NEEDS-OWNER.
- A `set_margin` setter on the store: `register_request` is the only writer of the trio and the
  composition that issues it (and that picks the entry price and the target leverage for the claim) is
  Phase 24. Not added, because it would be new PostgreSQL write code with no composition to use it.

### WR-07: `required_margin` is not tied to `quantity x price / leverage`

**Files modified:** `src/risk/reservations.py`, `src/persistence/risk_reservations.py`,
`tests/test_risk_reservations.py`, `tests/test_risk_reservation_margin_pg.py`
**Commit:** `749b32f4`
**Status:** fixed (no migration)
**Applied fix:** new `margin_for_reservation(quantity, price, leverage)`: exact rational arithmetic, rounded
UP at the 18th digit (the `NUMERIC(38,18)` scale), so a claim is never understated. `ReservationRequest`
refuses any other `required_margin`; `_claim_margin` in the reader derives the figure from the row and
reads a stored amount that differs as UNKNOWN (fail closed). The review's CHECK constraint was not added
(it would need migration 0013 and an exact-division check in SQL; the validator and the reader cover both
writers of this code base).
**Tests:** `test_margin_for_reservation_is_quantity_times_price_over_leverage`,
`test_margin_for_reservation_refuses_malformed_inputs`,
`test_a_request_whose_required_margin_is_not_quantity_x_price_over_leverage_is_refused`,
`test_a_request_with_a_leverage_that_does_not_divide_evenly_carries_the_rounded_up_margin`,
and on PostgreSQL `test_a_request_with_an_understated_margin_is_refused_before_anything_is_written`,
`test_a_stored_margin_that_differs_from_the_derived_one_reads_as_an_unknown_claim`. Fixtures of the PG
file that stored an inconsistent amount (30 for 0.01 x 3000 / 10) were corrected, and the
more-than-18-digits case now uses the entry price (the margin is always rounded to 18 digits).

### WR-08: the rehearsal's `margin_guard` seam bypasses DRY_RUN and the Demo-host guard

**Files modified:** `scripts/demo_rehearsal.py`, `tests/test_demo_rehearsal_flow.py`
**Commit:** `ecf34a4e`
**Status:** fixed
**Applied fix:** `GuardedAdapter` gets the three account reads, `symbol_config_snapshot` and
`leverage_brackets_snapshot` (through the host guard, call count and error log) and the two configuration
POSTs (counted in `mutating_attempts`, only PLANNED in DRY_RUN, evidence-recorded). `main()` and
`build_context()` take `margin_guard_factory`, which receives the guarded adapter; a real `MarginGuard`
passed as `margin_guard` is refused with `MARGIN_GUARD_NOT_GUARDED` (as is passing both). Scripted test
guards are still accepted.
**Tests:** `test_a_real_guard_over_the_guarded_adapter_sends_no_post_in_a_dry_run`,
`test_a_real_guard_over_the_guarded_adapter_posts_through_the_host_guard`,
`test_build_context_refuses_a_real_margin_guard_that_was_handed_in_directly`,
`test_build_context_builds_the_guard_over_the_guarded_adapter_from_the_factory`,
`test_build_context_refuses_both_a_guard_and_a_factory`,
`test_a_scripted_margin_guard_is_still_accepted_directly`.

### WR-09: the 5x cap is enforced only inside `SymbolConfigGuard`

**Files modified:** `src/execution/margin_guard.py`, `tests/test_margin_guard.py`
**Commit:** `dd0c4758` (with WR-01)
**Status:** fixed
**Applied fix:** `MarginGuard` reads `config_guard.target_leverage` at construction (plain int, 1 to
`TARGET_LEVERAGE`, else `TypeError`/`ValueError`) and refuses a verified leverage above `TARGET_LEVERAGE` or
different from the target (`UNCERTAIN_ACCOUNT_STATE`, with the mutation evidence).
**Tests:** `test_construction_refuses_a_target_leverage_above_the_d035_cap`,
`test_construction_refuses_a_target_leverage_below_one`,
`test_construction_refuses_a_target_leverage_that_is_not_a_plain_int`,
`test_a_port_that_verifies_fifty_x_is_refused_even_if_it_reports_a_5x_target`, and the "above the cap" and
"not the target" cases of `test_a_malformed_or_unusable_configuration_answer_is_uncertain`.

## Info findings

- **IN-02** (done, trivial): addendum "as of D085 and the review fixes" appended to
  `22-VERIFICATION.md` (commit `662f14e6`). The D085 wording in `docs/DECISIONS.md` ("to
  `ProtectionCoordinator`") is not edited here (canonical and gated); correct it at the next DECISIONS
  touch.
- IN-01, IN-03 to IN-08: not in scope. IN-04 (drift guard on the two POSTs) and IN-05(c) (validate
  `buffer_bps` in `LiquidationWatch.__init__`) are small and safe; left for a later pass.

## Skipped Issues

None.

## Needs the owner

1. WR-06(c): whether a RESERVED row is released after a margin or liquidation refusal (retryability vs
   over-refusing peers).
2. WR-05: whether an alert on a liquidation-price difference is wanted, and at what tolerance (a new
   `NOT_CONFIGURED` limits key).
3. WR-02: a DB-level arbiter per symbol (migration) if more than one process can place.

## Merge notes

Files that the Phase 21 fix is also likely to touch: `src/execution/manager.py` (decorator and import near
`execute_approved_plan`, gate 5f4 after the guard and after gate 5f3, one `:=` at the gate 5e evaluation),
`src/risk/reservations.py` and `src/persistence/risk_reservations.py` (the claim derivation; Phase 21
files), `tests/test_execution_manager.py` (appended tests, two edited clock tests),
`tests/test_risk_reservations.py`, `tests/test_risk_reservation_margin_pg.py`, `docs/GLOSSARY.md`.

---

_Fixed: 2026-10-25_
_Fixer: Claude (gsd-code-fixer, Claude Sonnet 5.5)_
_Iteration: 1_
