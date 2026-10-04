---
status: complete
phase: 12-fee-cost-model-correctness
source: [12-01-SUMMARY.md, 12-02-SUMMARY.md, 12-03-SUMMARY.md, 12-04-SUMMARY.md, 12-05-SUMMARY.md, 12-06-SUMMARY.md, 12-07-SUMMARY.md, 12-08-SUMMARY.md, 12-09-SUMMARY.md, 12-10-SUMMARY.md, 12-11-SUMMARY.md]
started: 2026-10-04
updated: 2026-10-04
---

## Current Test

[testing complete]

## Tests

### 1. [12-01] rejection reason values match glossary section 9
expected: Behaviour covered by test_rejection_reason_values_match_glossary_section_9
result: pass
verified: "Ran tests/test_domain_enums.py#test_rejection_reason_values_match_glossary_section_9 in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 2. [12-01] sized result accepts new cost guard codes
expected: Behaviour covered by test_sized_result_accepts_new_cost_guard_codes; test_portfolio_verdict_accepts_new_cost_guard_codes
result: pass
verified: "Ran tests/test_domain_enums.py#test_sized_result_accepts_new_cost_guard_codes; tests/test_domain_enums.py#test_portfolio_verdict_accepts_new_cost_guard_codes in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 3. [12-01] retired alias added to enum values fails gl03
expected: Behaviour covered by test_retired_alias_added_to_enum_values_fails_gl03; .venv/Scripts/python scripts/verify_decision_alignment.py glossary
result: pass
verified: "Ran tests/test_decision_alignment_bookkeeping.py#test_retired_alias_added_to_enum_values_fails_gl03; .venv/Scripts/python scripts/verify_decision_alignment.py glossary in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 4. [12-02] rate key unit error raises naming key
expected: Behaviour covered by test_rate_key_unit_error_raises_naming_key; test_guard_keys_range_checked
result: pass
verified: "Ran tests/test_registry.py#test_rate_key_unit_error_raises_naming_key; tests/test_registry.py#test_guard_keys_range_checked in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 5. [12-02] baseline v5 matches phase12
expected: Behaviour covered by test_baseline_v5_matches_phase12; test_every_params_toml_has_a_pin_that_verifies; git diff --name-status 7a1b848..HEAD -- params/ (five A lines, no M or D)
result: pass
verified: "Ran tests/test_registry.py#test_baseline_v5_matches_phase12; tests/test_registry.py#test_every_params_toml_has_a_pin_that_verifies; git diff --name-status 7a1b848..HEAD -- params/ (five A lines, no M or D) in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 6. [12-02] .venv/Scripts/python scripts/verify decision alignment.py params (PA-01..PA-07, 
expected: Behaviour covered by .venv/Scripts/python scripts/verify_decision_alignment.py params (PA-01..PA-07, ALL_PASS params); test_pa07_passes_on_copy
result: pass
verified: "Ran .venv/Scripts/python scripts/verify_decision_alignment.py params (PA-01..PA-07, ALL_PASS params); tests/test_decision_alignment_params.py#test_pa07_passes_on_copy in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 7. [12-03] btc long oracle
expected: Behaviour covered by test_btc_long_oracle; test_doubling_prices_doubles_cost
result: pass
verified: "Ran tests/test_cost_per_unit.py#test_btc_long_oracle; tests/test_cost_per_unit.py#test_doubling_prices_doubles_cost in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 8. [12-03] cost rates from legacy model refused
expected: Behaviour covered by test_cost_rates_from_legacy_model_refused; test_cost_model_rejects_rate_above_ceiling
result: pass
verified: "Ran tests/test_cost_per_unit.py#test_cost_rates_from_legacy_model_refused; tests/test_cost_per_unit.py#test_cost_model_rejects_rate_above_ceiling in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 9. [12-03] legacy registry cost hashes do not move
expected: Behaviour covered by test_legacy_registry_cost_hashes_do_not_move; test_partial_fill_fraction_one_spellings_hash_equal
result: pass
verified: "Ran tests/test_cost_per_unit.py#test_legacy_registry_cost_hashes_do_not_move; tests/test_cost_per_unit.py#test_partial_fill_fraction_one_spellings_hash_equal in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 10. [12-03] binding v5 set refuses seven key model
expected: Behaviour covered by test_binding_v5_set_refuses_seven_key_model; test_freeze_v5_set_pins_and_refuses_seven_key_model
result: pass
verified: "Ran tests/test_cost_per_unit.py#test_binding_v5_set_refuses_seven_key_model; tests/test_cost_per_unit.py#test_freeze_v5_set_pins_and_refuses_seven_key_model in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 11. [12-04] fixture carries phase12 identity
expected: Behaviour covered by test_fixture_carries_phase12_identity
result: pass
verified: "Ran tests/test_phase6_fixture_geometry.py#test_fixture_carries_phase12_identity in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 12. [12-04] fixture clears both cost guards
expected: Behaviour covered by test_fixture_clears_both_cost_guards; test_simple_trend_baseline_clears_both_cost_guards
result: pass
verified: "Ran tests/test_phase6_fixture_geometry.py#test_fixture_clears_both_cost_guards; tests/test_phase6_fixture_geometry.py#test_simple_trend_baseline_clears_both_cost_guards in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 13. [12-04] no trade baseline is rejected by the planner rr gate
expected: Behaviour covered by test_no_trade_baseline_is_rejected_by_the_planner_rr_gate; test_cr03b_reproduced_trades_carry_typed_decimal_datetime_fields; test_cr11_baseline_tomls_carry_detector_and_cost_keys
result: pass
verified: "Ran tests/test_phase6_fixture_geometry.py#test_no_trade_baseline_is_rejected_by_the_planner_rr_gate; tests/test_backtest_experiment.py#test_cr03b_reproduced_trades_carry_typed_decimal_datetime_fields; tests/test_backtest_experiment.py#test_cr11_baseline_tomls_carry_detector_and_cost_keys in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 14. [12-04] generator is deterministic and matches committed fixtures
expected: Behaviour covered by test_generator_is_deterministic_and_matches_committed_fixtures
result: pass
verified: "Ran tests/test_phase6_fixture_geometry.py#test_generator_is_deterministic_and_matches_committed_fixtures in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 15. [12-05] account taker below parameter keeps parameter
expected: Behaviour covered by test_account_taker_below_parameter_keeps_parameter; test_account_taker_above_parameter_wins_on_both_sides; test_account_taker_zero_is_a_real_rate_floored_by_parameter
result: pass
verified: "Ran tests/test_commission_rates.py#test_account_taker_below_parameter_keeps_parameter; tests/test_commission_rates.py#test_account_taker_above_parameter_wins_on_both_sides; tests/test_commission_rates.py#test_account_taker_zero_is_a_real_rate_floored_by_parameter in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 16. [12-05] stale by one second fails closed
expected: Behaviour covered by test_stale_by_one_second_fails_closed; test_future_dated_by_one_second_fails_closed; test_age_exactly_equal_to_ttl_passes
result: pass
verified: "Ran tests/test_commission_rates.py#test_stale_by_one_second_fails_closed; tests/test_commission_rates.py#test_future_dated_by_one_second_fails_closed; tests/test_commission_rates.py#test_age_exactly_equal_to_ttl_passes in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 17. [12-05] user commission rate projects frozen dataclass
expected: Behaviour covered by test_user_commission_rate_projects_frozen_dataclass; test_user_commission_rate_raises_on_malformed_response; test_user_commission_rate_propagates_sdk_exception
result: pass
verified: "Ran tests/test_adapter_strictness.py#test_user_commission_rate_projects_frozen_dataclass; tests/test_adapter_strictness.py#test_user_commission_rate_raises_on_malformed_response; tests/test_adapter_strictness.py#test_user_commission_rate_propagates_sdk_exception in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 18. [12-05] python scripts/verify decision alignment.py docs
expected: Behaviour covered by python scripts/verify_decision_alignment.py docs
result: pass
verified: "Ran python scripts/verify_decision_alignment.py docs in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 19. [12-06] removed modeled costs keyword raises type error
expected: Behaviour covered by test_removed_modeled_costs_keyword_raises_type_error
result: pass
verified: "Ran tests/test_risk_cost_guards.py#test_removed_modeled_costs_keyword_raises_type_error in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 20. [12-06] btc long oracle
expected: Behaviour covered by test_btc_long_oracle; test_worst_case_loss_at_stop_within_budget
result: pass
verified: "Ran tests/test_risk_cost_guards.py#test_btc_long_oracle; tests/test_risk_cost_guards.py#test_worst_case_loss_at_stop_within_budget in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 21. [12-06] cost to risk boundary equality passes
expected: Behaviour covered by test_cost_to_risk_boundary_equality_passes; test_guards_run_before_quantize
result: pass
verified: "Ran tests/test_risk_cost_guards.py#test_cost_to_risk_boundary_equality_passes; tests/test_risk_cost_guards.py#test_guards_run_before_quantize in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 22. [12-06] cost rates lineage event emitted once with string values
expected: Behaviour covered by test_cost_rates_lineage_event_emitted_once_with_string_values
result: pass
verified: "Ran tests/test_risk_cost_guards.py#test_cost_rates_lineage_event_emitted_once_with_string_values in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 23. [12-07] phase5 pipeline matches expected
expected: Behaviour covered by test_phase5_pipeline_matches_expected; test_portfolio_case_matches_expected_json
result: pass
verified: "Ran tests/test_risk_parity.py#test_phase5_pipeline_matches_expected; tests/test_risk_portfolio.py#test_portfolio_case_matches_expected_json in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 24. [12-07] phase5 pipeline matches expected
expected: Behaviour covered by test_phase5_pipeline_matches_expected
result: pass
verified: "Ran tests/test_risk_parity.py#test_phase5_pipeline_matches_expected in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 25. [12-07] evaluate risk too tight stop returns stop too tight verdict
expected: Behaviour covered by test_evaluate_risk_too_tight_stop_returns_stop_too_tight_verdict
result: pass
verified: "Ran tests/test_risk_portfolio.py#test_evaluate_risk_too_tight_stop_returns_stop_too_tight_verdict in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 26. [12-08] happy path places one entry and one sl leg
expected: Behaviour covered by test_happy_path_places_one_entry_and_one_sl_leg
result: pass
verified: "Ran tests/test_execution_manager.py#test_happy_path_places_one_entry_and_one_sl_leg in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 27. [12-08] parameter fee source is no trade before risk and adapter
expected: Behaviour covered by test_parameter_fee_source_is_no_trade_before_risk_and_adapter
result: pass
verified: "Ran tests/test_execution_manager.py#test_parameter_fee_source_is_no_trade_before_risk_and_adapter in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 28. [12-08] missing or wrong typed cost rates raises type error
expected: Behaviour covered by test_missing_or_wrong_typed_cost_rates_raises_type_error; test_legacy_modeled_costs_per_unit_keyword_raises_type_error
result: pass
verified: "Ran tests/test_execution_manager.py#test_missing_or_wrong_typed_cost_rates_raises_type_error; tests/test_execution_manager.py#test_legacy_modeled_costs_per_unit_keyword_raises_type_error in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 29. [12-09] apply costs books slippage per leg in quote currency
expected: Behaviour covered by test_apply_costs_books_slippage_per_leg_in_quote_currency; test_apply_costs_tp1_uses_entry_slippage_rate_not_the_exit_rate
result: pass
verified: "Ran tests/test_backtest_simulator.py#test_apply_costs_books_slippage_per_leg_in_quote_currency; tests/test_backtest_simulator.py#test_apply_costs_tp1_uses_entry_slippage_rate_not_the_exit_rate in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 30. [12-09] end to end sl loss including costs is within allowed risk
expected: Behaviour covered by test_end_to_end_sl_loss_including_costs_is_within_allowed_risk; test_end_to_end_modeled_costs_are_quote_per_unit_at_the_sizing_edge
result: pass
verified: "Ran tests/test_backtest_simulator.py#test_end_to_end_sl_loss_including_costs_is_within_allowed_risk; tests/test_backtest_simulator.py#test_end_to_end_modeled_costs_are_quote_per_unit_at_the_sizing_edge in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 31. [12-09] run refuses legacy registry set without guard rates
expected: Behaviour covered by test_run_refuses_legacy_registry_set_without_guard_rates; test_run_refuses_cost_dict_without_exit_slippage_rate; test_guard_reason_flows_from_the_shared_helper_into_a_reject_record
result: pass
verified: "Ran tests/test_backtest_simulator.py#test_run_refuses_legacy_registry_set_without_guard_rates; tests/test_backtest_simulator.py#test_run_refuses_cost_dict_without_exit_slippage_rate; tests/test_backtest_simulator.py#test_guard_reason_flows_from_the_shared_helper_into_a_reject_record in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 32. [12-09] modeled costs per unit price aware oracles
expected: Behaviour covered by test_modeled_costs_per_unit_price_aware_oracles; test_cost_parity_simulator_matches_costs_module
result: pass
verified: "Ran tests/test_backtest_simulator.py#test_modeled_costs_per_unit_price_aware_oracles; tests/test_backtest_simulator.py#test_cost_parity_simulator_matches_costs_module in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 33. [12-09] paper replay digest equals simulator digest
expected: Behaviour covered by test_paper_replay_digest_equals_simulator_digest; test_simulator_and_paper_pass_identical_cost_inputs_to_evaluate_risk; test_parity_expected_documentary_fields_match_registry_and_simulator
result: pass
verified: "Ran tests/test_paper_parity.py#test_paper_replay_digest_equals_simulator_digest; tests/test_paper_parity.py#test_simulator_and_paper_pass_identical_cost_inputs_to_evaluate_risk; tests/test_paper_parity.py#test_parity_expected_documentary_fields_match_registry_and_simulator in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 34. [12-10] accepted plans never lose more than allowed risk at the stop
expected: Behaviour covered by test_accepted_plans_never_lose_more_than_allowed_risk_at_the_stop; test_corrected_xrp_long_quantity_at_the_narrowest_width
result: pass
verified: "Ran tests/test_sl_loss_property.py#test_accepted_plans_never_lose_more_than_allowed_risk_at_the_stop; tests/test_sl_loss_property.py#test_corrected_xrp_long_quantity_at_the_narrowest_width in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 35. [12-10] old formula violates the budget on btc and xrp
expected: Behaviour covered by test_old_formula_violates_the_budget_on_btc_and_xrp; test_old_cost_term_ran_in_both_directions; test_harness_reports_vacuity_when_fed_a_correct_quantity
result: pass
verified: "Ran tests/test_sl_loss_property.py#test_old_formula_violates_the_budget_on_btc_and_xrp; tests/test_sl_loss_property.py#test_old_cost_term_ran_in_both_directions; tests/test_sl_loss_property.py#test_harness_reports_vacuity_when_fed_a_correct_quantity in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 36. [12-10] widths below the stop floor are stop too tight
expected: Behaviour covered by test_widths_below_the_stop_floor_are_stop_too_tight; test_widths_past_the_floor_but_costly_are_cost_to_risk_exceeded; test_width_0_8_percent_passes_both_guards
result: pass
verified: "Ran tests/test_sl_loss_property.py#test_widths_below_the_stop_floor_are_stop_too_tight; tests/test_sl_loss_property.py#test_widths_past_the_floor_but_costly_are_cost_to_risk_exceeded; tests/test_sl_loss_property.py#test_width_0_8_percent_passes_both_guards in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 37. [12-10] four way equality btc long
expected: Behaviour covered by test_four_way_equality_btc_long; test_four_way_equality_xrp_long; test_simulator_and_paper_call_evaluate_risk_with_identical_arguments; test_patching_the_producer_changes_both_wrappers; test_account_taker_above_parameter_raises_the_recorded_fee_and_never_grows_the_size
result: pass
verified: "Ran tests/test_cost_parity.py#test_four_way_equality_btc_long; tests/test_cost_parity.py#test_four_way_equality_xrp_long; tests/test_cost_parity.py#test_simulator_and_paper_call_evaluate_risk_with_identical_arguments; tests/test_cost_parity.py#test_patching_the_producer_changes_both_wrappers; tests/test_cost_parity.py#test_account_taker_above_parameter_raises_the_recorded_fee_and_never_grows_the_size in the 2026-10-04 UAT run (17 test files, 0 failures, TEST_DATABASE_URL set; glossary/params/docs decision-alignment gates ALL_PASS)"

### 38. [12-11] DECISIONS D046-D048 recorded with cost-ceiling ratification flag
expected: DECISIONS D046-D048 recorded with cost-ceiling ratification flag
result: pass
verified: "docs/DECISIONS.md contains D046 (Accepted, user ratification pending for item 6), D047, D048; witness-token tests in tests/test_decision_alignment_bookkeeping.py pass"

### 39. [12-11] RISK_MANAGEMENT and CONFIGURATION amendments pass decision-alignment docs gate
expected: RISK_MANAGEMENT and CONFIGURATION amendments pass decision-alignment docs gate
result: pass
verified: "verify_decision_alignment.py docs returned ALL_PASS docs"

### 40. [12-11] Full phase-12 regression green with MIN_LAST_DECISION 48
expected: Full phase-12 regression green with MIN_LAST_DECISION 48
result: pass
verified: "pytest over the 17 phase-12 test files passed against the PostgreSQL 17 test DB; glossary, params and docs gates ALL_PASS"

### 41. Live /fapi/v1/commissionRate fetch against Binance
expected: Account taker commission rate retrieved from the real exchange feeds ACCOUNT_MAX sizing
result: skipped
reason: needs signed Binance endpoint (forbidden in UAT); runtime wiring and Demo behaviour owned by Phase 24; adapter projection verified only against mocks

## Summary

total: 41
passed: 40
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

[]
