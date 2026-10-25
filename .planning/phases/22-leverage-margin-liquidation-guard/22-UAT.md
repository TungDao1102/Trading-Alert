---
status: partial
phase: 22-leverage-margin-liquidation-guard
source: [22-01-SUMMARY.md, 22-02-SUMMARY.md, 22-03-SUMMARY.md, 22-04-SUMMARY.md, 22-05-SUMMARY.md, 22-06-SUMMARY.md, 22-07-SUMMARY.md, 22-08-SUMMARY.md, 22-09-SUMMARY.md, 22-10-SUMMARY.md, 22-11-SUMMARY.md, 22-12-SUMMARY.md, 22-13-SUMMARY.md, 22-14-SUMMARY.md, 22-15-SUMMARY.md, 22-16-SUMMARY.md]
started: 2026-10-25T00:00:00Z
updated: 2026-10-25T00:00:00Z
---

Auto-answered by the assistant at the owner's request (2026-10-25) from test and code evidence; not a human observation.

Evidence run in this session (`TRADING_CI_STRICT=1`, `-m "not docker"`, `-p no:xdist -o addopts=""`, `TEST_DATABASE_URL` set, PostgreSQL up): 19 files (phase22 gate, symbol config guard, margin guard, liquidation watch, bracket cache, liquidation price + 300-case oracle, margin check, protection liquidation + rebuild, leverage/margin adapter, snapshot margin/leverage, phase22 fixtures, risk reservations, `test_risk_reservation_margin_pg.py`, demo rehearsal flow + safety, execution limits, exchange errors) = **1470 passed in 17.68s**, no failure, no error, no skip under strict mode; `tests/test_execution_manager.py -k "5f2 or 5f3 or 5f4 or margin or leverage or liquidation or mark_price"` = **9 passed, 180 deselected**. The full suite was not run. Nothing here touched the exchange; every `pass` is a library-level result (fakes, recorded Demo payloads, local PostgreSQL), not a Demo-through-the-guard result.

## Current Test

[testing complete]

## Tests

### 1. Symbol config set to ISOLATED x5, one POST per kind, the verification read decides
expected: A flat CROSSED x20 symbol gets at most one margin-type POST and one leverage POST (never retried); a failed margin POST stops the leverage POST; a POST answer never decides, one final symbolConfig read does; anything else is MARGIN_CONFIG_UNVERIFIED; a matching config costs one read and no POST; a non-flat symbol is refused with zero POSTs.
result: pass
source: assistant-evidence
evidence: tests/test_symbol_config_guard.py::test_tracer_the_recorded_crossed_x20_flat_symbol_becomes_isolated_x5, ::test_a_configuration_that_already_matches_costs_one_read, ::test_a_failed_margin_post_ends_the_mutations_and_the_read_decides, ::test_a_post_that_answers_200_without_changing_the_state_is_unverified, ::test_no_branch_sends_two_posts_of_one_kind_or_sleeps, ::test_a_non_flat_crossed_symbol_is_refused_with_zero_posts (within 1470 passed); src/execution/symbol_config_guard.py

### 2. Leverage above the D035 cap of 5 is refused (MarginGuard and SymbolConfigGuard)
expected: Construction of either guard with a target above 5 (or below 1, or not a plain int) fails; a port that verifies 50x is refused even if it reports a 5x target.
result: pass
source: assistant-evidence
evidence: tests/test_symbol_config_guard.py::test_a_target_above_the_d035_cap_is_refused_at_construction, ::test_a_target_up_to_the_d035_cap_is_accepted; tests/test_margin_guard.py::test_construction_refuses_a_target_leverage_above_the_d035_cap, ::test_a_port_that_verifies_fifty_x_is_refused_even_if_it_reports_a_5x_target; tests/test_phase22_gate.py::test_invariant_2_the_target_is_the_d035_cap_and_isolated (all passed)

### 3. A plan refused by a pure check sends no config POST (WR-01 order)
expected: Liquidation, margin and notional checks run before any account mutation; a refused plan leaves the recorded account untouched, and repeated refused attempts never POST.
result: pass
source: assistant-evidence
evidence: tests/test_margin_guard.py::test_a_plan_refused_by_a_pure_check_leaves_the_recorded_account_untouched, ::test_a_repeated_refused_attempt_never_posts_while_the_plan_stays_unplaceable, ::test_the_first_refusal_in_the_fixed_order_wins, ::test_every_refusal_has_its_exact_plain_code_and_touches_nothing_later (passed)

### 4. Liquidation price beyond the stop with the 300 bps strict buffer, LONG and SHORT
expected: Long passes only if LP < stop - buffer, short only if LP > stop + buffer, buffer = entry x 300 / 10000; equality refuses; margin.liquidation_buffer_bps is 300 (DECISION) in the limits file.
result: pass
source: assistant-evidence
evidence: tests/test_liquidation_price.py::test_long_boundary_is_strict, ::test_short_boundary_is_strict, ::test_verdict_too_close_when_the_stop_minus_buffer_is_below_the_liquidation, ::test_short_verdict_ok_and_too_close; tests/test_margin_guard.py::test_the_short_mirror_passes_and_fails_on_the_other_side_of_the_stop; tests/test_phase22_gate.py::test_invariant_5_the_margin_limits_are_required_and_hold_the_owner_numbers; config/execution/execution-limits-v1.toml:58-61 (liquidation_buffer_bps = 300, max_bracket_age_ms = 60000, headroom_bps = 1000)

### 5. Bracket tier chosen by Q x LP; 300-case oracle agrees
expected: The maintenance tier is the bracket containing the liquidation notional, not the entry notional; the table is continuous at every edge; the closed form agrees with an independent first-crossing oracle on 300 cases; malformed or over-cap tables fail closed.
result: pass
source: assistant-evidence
evidence: tests/test_liquidation_price.py::test_g3_long_uses_the_bracket_of_the_liquidation_notional_not_of_the_entry, ::test_continuity_of_the_demo_table_at_every_bracket_edge, ::test_malformed_bracket_lists_are_unavailable, ::test_entry_notional_above_the_top_cap_is_refused; tests/test_liquidation_price_oracle.py::test_liquidation_price_agrees_with_the_first_crossing_oracle_on_300_cases (passed). The oracle proves agreement with the formula's own condition, not with the exchange (22-VALIDATION Manual-Only).

### 6. Entry fee is netted in the isolated wallet and comes from the request
expected: entry_fee_rate is a required argument with no default; the guard passes request.fee_rate_entry to the liquidation function (not 0 or a constant); the recorded Demo long (exchange 64968.85) is reproduced within the rounded-wallet difference.
result: pass
source: assistant-evidence
evidence: tests/test_margin_guard.py::test_the_entry_fee_of_the_request_decides_the_liquidation_price, ::test_the_guard_passes_request_fee_rate_entry_to_the_liquidation_function; tests/test_liquidation_price.py::test_there_is_no_default_for_leverage_buffer_fee_or_brackets; tests/test_liquidation_watch.py::test_the_recorded_demo_isolated_long_differs_by_the_rounded_wallet_only (passed)

### 7. Margin check: free margin, headroom 1000 bps, claims of other approved plans, unknown claim refuses
expected: need = initial margin + entry/exit fees + open loss + other claims; required = need x (1 + 1000/10000); equality passes, one unit below fails; the candidate's own claim is excluded; a claim with unknown required_margin gives UNCERTAIN_ACCOUNT_STATE; the recorded -2019 shape is INSUFFICIENT_MARGIN; the netting constant is True since D085 (a PLACED claim at or before the reading is not counted twice).
result: pass
source: assistant-evidence
evidence: tests/test_margin_check.py::test_passing_plan_needs_margin_fees_and_headroom_equality_passes, ::test_verdict_with_other_claims_adds_them_to_the_need, ::test_unknown_other_claims_are_uncertain_account_state_not_insufficient, ::test_recorded_demo_2019_shape_is_refused_insufficient_margin, ::test_other_claims_margin_netting; tests/test_margin_guard.py::test_the_headroom_boundary_equal_passes_and_one_unit_below_fails, ::test_the_candidates_own_claim_is_excluded, ::test_the_netting_constant_is_the_switch_and_the_guard_passes_the_module_constant; tests/test_phase22_gate.py::test_invariant_3_the_netting_constant_is_true_since_d085 (passed)

### 8. Bracket cache: max age 60000 ms, no stale fallback
expected: A second read inside the bound makes no call (boundary inclusive); a read slower than the bound returns None and keeps nothing; a failed read drops the cache and is never retried; notionalCoef other than 1 makes the set unusable; the age bound comes from the limit key and construction refuses while it is NOT_CONFIGURED.
result: pass
source: assistant-evidence
evidence: tests/test_bracket_cache.py::test_a_second_get_inside_the_bound_makes_no_call_and_the_boundary_is_inclusive, ::test_a_read_slower_than_the_bound_returns_none_and_keeps_nothing, ::test_a_failure_drops_the_cache_and_a_later_success_clears_the_error, ::test_a_notional_coefficient_other_than_one_makes_the_set_unusable, ::test_the_age_bound_comes_from_the_limit_key, ::test_a_backwards_clock_forces_a_refresh (passed)

### 9. Hedge and multi-asset accounts are refused before any mutation
expected: The guard reads one fresh account snapshot first and refuses hedge (HEDGE_MODE_UNSUPPORTED) and multi-asset (MARGIN_MODE_UNSUPPORTED) before the configuration guard can POST; stale, future-dated or mismatching readings are refused.
result: pass
source: assistant-evidence
evidence: tests/test_margin_guard.py::test_a_hedge_or_multi_asset_account_is_refused_before_anything_is_mutated, ::test_each_blocked_value_of_the_account_judgement_maps_to_its_code, ::test_a_reading_that_ages_during_the_bracket_and_configuration_reads_is_refused (passed); src/execution/margin_guard.py (step 0)

### 10. Post-fill LiquidationWatch: CLOSE_POSITION, ALERT_ONLY, restored plan without leverage
expected: Inside the buffer or an unknown exchange value closes under CLOSE_POSITION (stop kept, one reduce-only close); ALERT_ONLY alerts once and never closes; OK_DIFFERS journals both prices and raises no alert; a restored plan without leverage is not closed when the exchange value is far away but is closed when inside the buffer; the policy is a required keyword with no default; without a watch the journal is unchanged.
result: pass
source: assistant-evidence
evidence: tests/test_protection_liquidation.py::test_close_verdict_with_the_real_closer_ends_flat_through_one_reduce_only_close, ::test_alert_only_with_the_real_watch_alerts_once_inside_the_buffer_and_never_closes, ::test_alert_only_policy_alerts_instead_of_closing_on_the_error_paths, ::test_ok_differs_journals_both_exact_prices_and_raises_no_alert, ::test_a_plan_without_a_leverage_is_not_closed_when_the_value_is_far_away, ::test_a_plan_restored_through_the_rebuild_path_without_a_leverage_is_not_closed, ::test_no_watch_means_no_new_event_and_an_identical_happy_path_journal; tests/test_liquidation_watch.py::test_the_policy_is_a_required_keyword_with_no_default, ::test_a_missing_leverage_does_not_decide_a_passing_exchange_value (passed)

### 11. Manager gate order 5f2 / 5f3 / 5f4 and the clock recheck
expected: Gate 5f2 (guard) sits after the position-mode gate and before the hand-off record; a refusal consumes nothing; 5f3 refuses a sizing equity above the live equity; 5f4 re-reads the clock after the guard so an aged mark price is refused before the consume; remaining validity is measured after the guard; a raising guard fails closed without leaking its text.
result: pass
source: assistant-evidence
evidence: tests/test_execution_manager.py -k "5f2 or 5f3 or 5f4 or margin or leverage or liquidation or mark_price" = 9 passed, 180 deselected (this filter selects test_gate_5f2_orders_the_position_mode_the_guard_and_the_placement, test_gate_5f3_refuses_a_sizing_equity_above_the_live_equity_the_guard_read and others, not every guard test of that file individually); tests/test_phase22_gate.py::test_invariant_12_gate_5f2_sits_after_the_position_mode_and_before_the_hand_off_record (passed); src/execution/manager.py:622 and :1135 (read, gate 5f4 comment and code)

### 12. required_margin consistency at the DB reader and migration 0012
expected: required_margin = quantity x price / leverage; a stored margin that differs from the derived one reads as an unknown claim; a consistent peer reduces the next plan's headroom; a peer with no or inconsistent margin gives UNCERTAIN_ACCOUNT_STATE; the migration head is 0012_reservation_margin.
result: pass
source: assistant-evidence
evidence: PostgreSQL (TEST_DATABASE_URL set, strict mode, no skip): tests/test_risk_reservation_margin_pg.py::test_an_approved_peer_with_a_consistent_margin_reduces_the_headroom_of_the_next_plan, ::test_a_peer_with_no_stored_margin_makes_the_next_verdict_uncertain, ::test_a_peer_with_an_inconsistent_stored_margin_makes_the_next_verdict_uncertain, ::test_a_stored_margin_that_differs_from_the_derived_one_reads_as_an_unknown_claim, ::test_a_request_with_an_understated_margin_is_refused_before_anything_is_written; tests/test_phase22_gate.py::test_invariant_7_the_migration_head_is_0012_reservation_margin (all within the 1470 passed)

### 13. DRY_RUN rehearsal sends no config POST and MARGIN_GUARD_NOT_GUARDED
expected: A real guard built over the GuardedAdapter in DRY_RUN sends no POST; main() builds the guard once over the guarded adapter; a rehearsal given an unguarded margin guard aborts with MARGIN_GUARD_NOT_GUARDED.
result: pass
source: assistant-evidence
evidence: tests/test_demo_rehearsal_flow.py::test_a_real_guard_over_the_guarded_adapter_sends_no_post_in_a_dry_run, ::test_main_in_dry_run_builds_the_guard_once_over_the_guarded_adapter_and_sends_no_post, and the pytest.raises match "MARGIN_GUARD_NOT_GUARDED" at line 1992; tests/test_demo_rehearsal_safety.py::test_dry_run_never_reaches_mutating_methods (passed); scripts/demo_rehearsal.py:235,1383

### 14. RejectionReason stays 21 members; Phase 22 codes are plain strings
expected: len(RejectionReason) == 21; the new refusal codes are plain strings defined in their modules and listed once in the glossary.
result: pass
source: assistant-evidence
evidence: tests/test_phase22_gate.py::test_invariant_6_the_rejection_reason_enum_still_has_21_members, ::test_invariant_6b_every_plain_code_is_defined_in_its_module, ::test_invariant_6c_glossary_93_lists_every_plain_code_once_with_its_module; tests/test_margin_guard.py::test_the_refusal_codes_are_the_plain_strings_of_the_contract, ::test_the_rejection_reason_enum_is_unchanged (passed)

### 15. Demo-recorded facts reproduce from the committed fixtures
expected: Fixtures regenerate byte-identically; the recorded Demo symbolConfig (CROSSED x20, ISOLATED upper case) and bracket table carry the capture values; the -2019 shape maps to INSUFFICIENT_MARGIN and -4046 to a typed exchange error; the watch reproduces the recorded long liquidation 64968.85 within the rounded-wallet difference.
result: pass
source: assistant-evidence
evidence: tests/test_phase22_fixtures.py::test_generator_rerun_is_byte_identical, ::test_recorded_demo_symbol_config_carries_the_capture_values, ::test_recorded_demo_leverage_brackets_carry_the_capture_values; tests/test_margin_check.py::test_recorded_demo_2019_shape_is_refused_insufficient_margin; tests/test_exchange_errors.py (whole file passed, incl. the -4046 mapping at line 565); tests/test_liquidation_watch.py::test_the_recorded_demo_isolated_long_differs_by_the_rounded_wallet_only (passed). The codes -4047 and -4028 are covered by tests/test_leverage_margin_adapter.py (whole file passed) and recorded in 22-DEMO-RESULTS.md R-2, R-3; those two tests were not individually named in this run.

### 16. No secrets or balances are logged
expected: Guard, cache and adapter paths log no exception text, no bracket value and no account figure; a failing port carries only its class name.
result: pass
source: assistant-evidence
evidence: tests/test_margin_guard.py::test_no_log_event_on_success_or_refusal, ::test_any_port_exception_is_uncertain_account_state_without_its_text; tests/test_symbol_config_guard.py::test_no_exception_message_reaches_the_result_or_the_logs; tests/test_bracket_cache.py::test_logs_carry_no_bracket_value_and_no_exception_text; tests/test_execution_manager.py::test_a_raising_guard_fails_closed_without_leaking_its_text (passed)

### 17. Criteria 1 to 3 through the guard against the Demo
expected: MarginGuard over a real adapter runs on the Demo for one symbol and shows the config set, the liquidation check and the margin check end to end.
result: blocked
blocked_by: prior-phase
reason: Nothing is composed into a running process until Phase 24 (22-VERIFICATION deferred row 1); the guard was built after the 2026-10-24 Demo run and has never run against Demo. Owner-run Demo case after Phase 24 composition.

### 18. SHORT and higher-tier exchange liquidationPrice; real -4048 / -4046 payloads
expected: A short and a position above bracket 1 on the Demo give an exchange liquidationPrice that matches the formula; -4048 (position open) and -4046 (no-op) answers are recorded.
result: blocked
blocked_by: third-party
reason: Exchange-only. 22-DEMO-RESULTS.md holds one long tier-1 sample and no -4048 or -4046 payload; the 300-case oracle proves the formula only against its own condition.

### 19. availableBalance netting beyond the 2 Demo samples
expected: availableBalance falls by exactly a resting order's initial margin on more than the two Demo samples and on mainnet (basis of the D085 flip of AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED).
result: blocked
blocked_by: third-party
reason: Exchange-only; two samples on one Demo host (R-4, R-5). A mainnet sample is planned for the Phase 26 canary; no mainnet use now.

### 20. Phase 24 composition: required_margin writer, mark_placed, CLOSE_POSITION passed
expected: Phase 24 writes required_margin on register_request, calls mark_placed at the exchange ack, constructs MarginGuard, SymbolConfigGuard, BracketCache and LiquidationWatch, and passes liquidation_watch with LiquidationFailurePolicy.CLOSE_POSITION to the ProtectionCoordinator.
result: blocked
blocked_by: prior-phase
reason: Not built. tests/test_phase22_gate.py::test_invariant_13_nothing_in_src_writes_required_margin and ::test_invariant_14_nothing_passes_liquidation_watch_to_a_coordinator_yet pin the gap (both passed); the effect today is fail-closed over-refusal. Deferred to Phase 24 (22-DEFERRED.md).

### 21. Owner approval of the probe-limits files
expected: The owner approves the Demo probe-limits files used for the 2026-10-24 run.
result: skipped
reason: Owner attestation; no code or test can stand in for it and an assistant cannot approve it. Left for the owner.

### 22. Mainnet behavior
expected: Any of the above on mainnet.
result: blocked
blocked_by: prior-phase
reason: No mainnet use; live placement is disabled (LIVE_ORDERS_DISABLED). Phase 26 canary.

## Summary

total: 22
passed: 16
issues: 0
pending: 0
skipped: 1
blocked: 5

## Gaps

[none yet]
