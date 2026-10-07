---
status: complete
phase: 06-backtest-simulator-experiment-registry
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md, 06-03-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 06-02 D1: ExperimentRecord frozen dataclass six-field identity + validation
expected: ExperimentRecord frozen dataclass six-field identity + validation
result: pass
source: automated
coverage_id: 06-02/D1
verified: test_experiment_assemble_stable_64_hex_identity, test_experiment_assemble_missing_field_raises pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 2. 06-02 D2: reproduce()/verify_experiment() byte-identical reproduction
expected: reproduce()/verify_experiment() byte-identical reproduction
result: pass
source: automated
coverage_id: 06-02/D2
verified: test_experiment_reproduce_byte_identical, test_verify_experiment_returns_none_when_reproducible, test_run_twice_record_stability pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 3. 06-02 D3: Unregistered parameterSetId fails closed
expected: Unregistered parameterSetId fails closed
result: pass
source: automated
coverage_id: 06-02/D3
verified: test_experiment_unregistered_set_fails_closed pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 4. 06-02 D4: No-trade baseline returns empty trade list
expected: No-trade baseline returns empty trade list
result: pass
source: automated
coverage_id: 06-02/D4
verified: test_baseline_no_trade_returns_empty_trades pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 5. 06-02 D5: Simple-trend baseline single-direction trades
expected: Simple-trend baseline single-direction trades
result: pass
source: automated
coverage_id: 06-02/D5
verified: test_baseline_simple_trend_returns_single_direction pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 6. 06-02 D6: costModelHash trailing-precision discipline
expected: costModelHash trailing-precision discipline
result: pass
source: automated
coverage_id: 06-02/D6
verified: test_cost_model_hash_precision_discipline pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 7. 06-02 D7: Empty simulator input yields valid record
expected: Empty simulator input yields valid record
result: pass
source: automated
coverage_id: 06-02/D7
verified: test_empty_input_yields_valid_record_with_zero_trades pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 8. 06-02 D8: Universe order stability
expected: Universe order stability
result: pass
source: automated
coverage_id: 06-02/D8
verified: test_universe_order_stability pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 9. 06-03 D1: Report pinned digest equality, seed-stable rebuild
expected: Report pinned digest equality, seed-stable rebuild
result: pass
source: automated
coverage_id: 06-03/D1
verified: test_build_returns_report_with_pinned_digest, test_build_seed_stable_rebuild_returns_identical_digest, test_bootstrap_uses_recorded_seed pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 10. 06-03 D2: Nine mandatory report sections present
expected: Nine mandatory report sections present
result: pass
source: automated
coverage_id: 06-03/D2
verified: test_build_includes_all_nine_sections pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 11. 06-03 D3: Intrabar coverage percentages
expected: Intrabar coverage percentages
result: pass
source: automated
coverage_id: 06-03/D3
verified: test_intrabar_coverage_exact_percentages pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 12. 06-03 D4: Dual-universe slices
expected: Dual-universe slices
result: pass
source: automated
coverage_id: 06-03/D4
verified: test_dual_universe_includes_research_and_live5 pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 13. 06-03 D5: Report edge cases: empty and single trade
expected: Report edge cases: empty and single trade
result: pass
source: automated
coverage_id: 06-03/D5
verified: test_build_with_empty_list_returns_valid_report, test_build_with_single_trade_returns_valid_report_without_interval pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 14. 06-03 D6: Zero-R counted as neither win nor loss
expected: Zero-R counted as neither win nor loss
result: pass
source: automated
coverage_id: 06-03/D6
verified: test_zero_r_counted_as_neither_wins_nor_losses pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 15. 06-03 D7: Quarter derivation from exit time
expected: Quarter derivation from exit time
result: pass
source: automated
coverage_id: 06-03/D7
verified: test_quarter_is_derived_deterministically_from_exit_time pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 16. 06-03 D8: No-float guard covers src/backtest
expected: No-float guard covers src/backtest
result: pass
source: automated
coverage_id: 06-03/D8
verified: test_domain_mapper_registry_path_has_no_float_call pass (re-run 2026-10-04, 93 passed across simulator/experiment/report/no-float suites)

### 17. 06-01 Simulator resolves SL-first via 1m intrabar (long, short, missing-data fallback with flag)
expected: Both-touched bars resolve SL via 1m data; missing/empty 1m falls back to SL-first with flag
result: pass
verified: test_intrabar_both_touched_long/short_resolves_sl_via_1m, test_intrabar_missing_fallback_resolves_sl_with_flag, test_cr01_empty_intrabar_list_resolves_sl_first_fallback pass (checked 2026-10-04)

### 18. 06-01 Registry-parameterized costs applied from run #1
expected: Realized PnL differs from gross; simulator costs match costs module
result: pass
verified: test_costs_apply_from_run_1_realized_pnl_differs_from_gross, test_cost_parity_simulator_matches_costs_module, test_apply_costs_* and modeled_costs_per_unit tests pass (checked 2026-10-04)

### 19. 06-01 Risk reject is a first-class outcome
expected: Risk-rejected plans recorded as outcome, not dropped
result: pass
verified: test_risk_reject_is_first_class_outcome pass (checked 2026-10-04)

### 20. 06-01 Limit entry state machine (touch-no-fill, partial fill, invalidation cancel)
expected: Each entry outcome modeled correctly
result: pass
verified: test_limit_touch_no_fill, test_limit_partial_fill, test_invalidation_cancels_entry pass (checked 2026-10-04)

### 21. 06-01 Determinism, no-lookahead and unique trade ids
expected: Run twice byte-identical; appending later 1m candle changes nothing; trade ids unique; float JSON/naive datetime rejected
result: pass
verified: test_run_twice_byte_identical, test_no_lookahead_appending_1m_candle_changes_nothing, test_cr02_trade_id_unique..., test_wr14_float_json_numbers_and_naive_datetimes_rejected, test_phase6_fixtures_exist pass (checked 2026-10-04)

### 22. 06-03 D9 Phase gate: mypy strict, ruff, test suite
expected: mypy --strict src/backtest clean, ruff clean, tests green
result: pass
verified: uv run mypy src/backtest/ --strict: Success no issues in 6 source files; uv run ruff check src/backtest/: All checks passed; targeted backtest suites 93 passed ; full-suite rerun completed with 2 failures outside Phase 6 scope (tests/test_deploy_docs.py::test_refresh_pins_lookup_is_read_only_and_reports_moves, tests/test_docker_cutover.py::test_the_reported_oi_gap_is_the_engineered_forty_five_minutes), no src/backtest failures; summary line truncated so exact pass count unconfirmed (checked 2026-10-04)

### 23. Entry-expiry clock uses simulated bar time (G3)
expected: Limit expiry resolved against the replayed bar's time, not a single fixture now_utc
result: pass
source: closed by Phase 14 (success criterion 6), checked 2026-10-07
reason_before: Known gap G3 (CR-04): simulator.py ~758/881 still used the fixture single now_utc; owned by Phase 14.
evidence: 14-VERIFICATION.md criterion 6: `_entry_now_utc` is gone and expiry is judged per minute (`close_time <= expiry_utc`); tests `test_plan_a_fills_on_bar_n_plus_2_before_expiry`, `test_plan_b_expires...` and goldens `g3_fill_before_expiry`, `g3_expire_after` pass. Note: the Phase 6 evidence itself stays VOID (D052); this only closes the G3 item.

## Summary

total: 23
passed: 23
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
