---
phase: 15-strategy-geometry-correction
plan: 08
status: in-progress
---

# Phase 15 Plan 08: Ratified parameter sets (in progress)

This file is completed at the end of the plan. The section below is the user's answer to checkpoint 15-08-01 and is the precondition of Tasks 2 and 3.

## Ratified parameter values

Ratified-by: user (verbatim reply to checkpoint 15-08-01)
ratify

Reading of the reply: option "ratify" of the plan's Task 1 (accept the proposed table exactly as written in the plan's Task 1 context; no edits). breakout_confirmation_bars is 1 (STRUCTURAL, sheet B1); min_stop_atr is 0.5 (PLACEHOLDER) for all three sets; every other value and basis is as listed below. The legacy breakout_confirmation_bars value 3 is not written anywhere and no deviation is recorded in D054 for it.

Notes on how the table is derived from the ratified proposal:

- A DECISION or COST_GUARD row carries its DECISIONS id in ref. STRUCTURAL and PLACEHOLDER rows carry no ref (their source document is named in the rationale text of the set file).
- The -v4 baselines of plan 15-09 take the trend-pullback baseline-v6 values with these overrides, as ratified: baseline-no-trade-v4 minimum_rr 100; baseline-simple-trend-v4 zone_tolerance_atr 1.0 and minimum_rr 0.5. The checkpoint text gives no basis for the three overridden values; the DECISION basis with ref D054 is taken from the wording of plan 15-09 ("DECISION with ref D054 for the degenerate minimum_rr 100") and is flagged for the user's attention in the plan report.
- Keys omitted because no module under src/ reads them (research Pitfall 7, re-confirmed with codegraph and grep before writing): breakout_volume_threshold (breakout-retest), breakout_confirmation_bars (trend-pullback and range-mr), risk_rate (all three sets; the account risk rate is the sizing source, WR-03).

| key | family | value | basis | ref |
|---|---|---|---|---|
| geometry_version | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 1 | DECISION | D054 |
| pivot_left_bars | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 3 | PLACEHOLDER | - |
| pivot_right_bars | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 3 | PLACEHOLDER | - |
| min_stop_atr | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.5 | PLACEHOLDER | - |
| swing_lookback | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 20 | PLACEHOLDER | - |
| zone_tolerance_atr | trend-pullback baseline-v6 | 0.5 | PLACEHOLDER | - |
| zone_tolerance_atr | trend-pullback baseline-no-trade-v4 | 0.5 | PLACEHOLDER | - |
| zone_tolerance_atr | trend-pullback baseline-simple-trend-v4 | 1.0 | DECISION | D054 |
| entry_buffer_atr | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.1 | PLACEHOLDER | - |
| sl_buffer_atr | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.2 | PLACEHOLDER | - |
| minimum_rr | trend-pullback baseline-v6 | 2.0 | PLACEHOLDER | - |
| minimum_rr | trend-pullback baseline-no-trade-v4 | 100 | DECISION | D054 |
| minimum_rr | trend-pullback baseline-simple-trend-v4 | 0.5 | DECISION | D054 |
| signal_expiry_hours | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 4 | PLACEHOLDER | - |
| minimum_risk_utilization_after_rounding | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.6 | STRUCTURAL | - |
| max_open_positions | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 2 | PLACEHOLDER | - |
| max_aggregate_open_risk | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.01 | PLACEHOLDER | - |
| cluster_cap | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.005 | PLACEHOLDER | - |
| daily_loss_warning_threshold | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.005 | DECISION | D033 |
| daily_loss_stop_threshold | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.01 | DECISION | D033 |
| fee_rate_entry | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.0005 | DECISION | D036 |
| fee_rate_exit | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.0005 | DECISION | D036 |
| expected_slippage | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.0001 | DECISION | D046 |
| constraint_snapshot_ttl_seconds | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 3600 | PLACEHOLDER | - |
| funding_treatment | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | ADDITIVE | PLACEHOLDER | - |
| slippage_model | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | FIXED_BPS | PLACEHOLDER | - |
| spread_fill_assumptions | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | FULL_FILL | PLACEHOLDER | - |
| partial_fill_fraction | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 1.0 | DECISION | D038 |
| working_type | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | MARK_PRICE | DECISION | D037 |
| exit_slippage_rate | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.0003 | DECISION | D046 |
| min_stop_distance_rate | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.003 | COST_GUARD | D046 |
| max_cost_to_risk | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 0.15 | COST_GUARD | D046 |
| commission_rate_ttl_seconds | trend-pullback baseline-v6, baseline-no-trade-v4, baseline-simple-trend-v4 | 3600 | DECISION | D046 |
| geometry_version | breakout-retest baseline-v6 | 1 | DECISION | D054 |
| min_stop_atr | breakout-retest baseline-v6 | 0.5 | PLACEHOLDER | - |
| breakout_confirmation_bars | breakout-retest baseline-v6 | 1 | STRUCTURAL | - |
| swing_lookback | breakout-retest baseline-v6 | 20 | PLACEHOLDER | - |
| zone_tolerance_atr | breakout-retest baseline-v6 | 0.5 | PLACEHOLDER | - |
| entry_buffer_atr | breakout-retest baseline-v6 | 0.1 | PLACEHOLDER | - |
| sl_buffer_atr | breakout-retest baseline-v6 | 0.2 | PLACEHOLDER | - |
| minimum_rr | breakout-retest baseline-v6 | 2.0 | PLACEHOLDER | - |
| signal_expiry_hours | breakout-retest baseline-v6 | 4 | PLACEHOLDER | - |
| retest_window_bars | breakout-retest baseline-v6 | 5 | PLACEHOLDER | - |
| retest_depth_atr | breakout-retest baseline-v6 | 0.3 | PLACEHOLDER | - |
| atr_period | breakout-retest baseline-v6 | 14 | PLACEHOLDER | - |
| minimum_risk_utilization_after_rounding | breakout-retest baseline-v6 | 0.6 | STRUCTURAL | - |
| max_open_positions | breakout-retest baseline-v6 | 2 | PLACEHOLDER | - |
| max_aggregate_open_risk | breakout-retest baseline-v6 | 0.01 | PLACEHOLDER | - |
| cluster_cap | breakout-retest baseline-v6 | 0.005 | PLACEHOLDER | - |
| daily_loss_warning_threshold | breakout-retest baseline-v6 | 0.005 | DECISION | D033 |
| daily_loss_stop_threshold | breakout-retest baseline-v6 | 0.01 | DECISION | D033 |
| fee_rate_entry | breakout-retest baseline-v6 | 0.0005 | DECISION | D036 |
| fee_rate_exit | breakout-retest baseline-v6 | 0.0005 | DECISION | D036 |
| expected_slippage | breakout-retest baseline-v6 | 0.0001 | DECISION | D046 |
| constraint_snapshot_ttl_seconds | breakout-retest baseline-v6 | 3600 | PLACEHOLDER | - |
| funding_treatment | breakout-retest baseline-v6 | ADDITIVE | PLACEHOLDER | - |
| slippage_model | breakout-retest baseline-v6 | FIXED_BPS | PLACEHOLDER | - |
| spread_fill_assumptions | breakout-retest baseline-v6 | FULL_FILL | PLACEHOLDER | - |
| partial_fill_fraction | breakout-retest baseline-v6 | 1.0 | DECISION | D038 |
| working_type | breakout-retest baseline-v6 | MARK_PRICE | DECISION | D037 |
| exit_slippage_rate | breakout-retest baseline-v6 | 0.0003 | DECISION | D046 |
| min_stop_distance_rate | breakout-retest baseline-v6 | 0.003 | COST_GUARD | D046 |
| max_cost_to_risk | breakout-retest baseline-v6 | 0.15 | COST_GUARD | D046 |
| commission_rate_ttl_seconds | breakout-retest baseline-v6 | 3600 | DECISION | D046 |
| geometry_version | range-mr baseline-v6 | 1 | DECISION | D054 |
| pivot_left_bars | range-mr baseline-v6 | 3 | PLACEHOLDER | - |
| pivot_right_bars | range-mr baseline-v6 | 3 | PLACEHOLDER | - |
| tp_mode | range-mr baseline-v6 | T_MID | STRUCTURAL | - |
| min_stop_atr | range-mr baseline-v6 | 0.5 | PLACEHOLDER | - |
| swing_lookback | range-mr baseline-v6 | 20 | PLACEHOLDER | - |
| zone_tolerance_atr | range-mr baseline-v6 | 0.5 | PLACEHOLDER | - |
| entry_buffer_atr | range-mr baseline-v6 | 0.1 | PLACEHOLDER | - |
| sl_buffer_atr | range-mr baseline-v6 | 0.2 | PLACEHOLDER | - |
| minimum_rr | range-mr baseline-v6 | 2.0 | PLACEHOLDER | - |
| signal_expiry_hours | range-mr baseline-v6 | 4 | PLACEHOLDER | - |
| zone_min_touches | range-mr baseline-v6 | 2 | PLACEHOLDER | - |
| zone_aging_bars | range-mr baseline-v6 | 50 | PLACEHOLDER | - |
| range_break_buffer_atr | range-mr baseline-v6 | 0.2 | PLACEHOLDER | - |
| regime_filter_lookback | range-mr baseline-v6 | 50 | PLACEHOLDER | - |
| atr_period | range-mr baseline-v6 | 14 | PLACEHOLDER | - |
| touch_tolerance_atr | range-mr baseline-v6 | 0.3 | PLACEHOLDER | - |
| minimum_risk_utilization_after_rounding | range-mr baseline-v6 | 0.6 | STRUCTURAL | - |
| max_open_positions | range-mr baseline-v6 | 2 | PLACEHOLDER | - |
| max_aggregate_open_risk | range-mr baseline-v6 | 0.01 | PLACEHOLDER | - |
| cluster_cap | range-mr baseline-v6 | 0.005 | PLACEHOLDER | - |
| daily_loss_warning_threshold | range-mr baseline-v6 | 0.005 | DECISION | D033 |
| daily_loss_stop_threshold | range-mr baseline-v6 | 0.01 | DECISION | D033 |
| fee_rate_entry | range-mr baseline-v6 | 0.0005 | DECISION | D036 |
| fee_rate_exit | range-mr baseline-v6 | 0.0005 | DECISION | D036 |
| expected_slippage | range-mr baseline-v6 | 0.0001 | DECISION | D046 |
| constraint_snapshot_ttl_seconds | range-mr baseline-v6 | 3600 | PLACEHOLDER | - |
| funding_treatment | range-mr baseline-v6 | ADDITIVE | PLACEHOLDER | - |
| slippage_model | range-mr baseline-v6 | FIXED_BPS | PLACEHOLDER | - |
| spread_fill_assumptions | range-mr baseline-v6 | FULL_FILL | PLACEHOLDER | - |
| partial_fill_fraction | range-mr baseline-v6 | 1.0 | DECISION | D038 |
| working_type | range-mr baseline-v6 | MARK_PRICE | DECISION | D037 |
| exit_slippage_rate | range-mr baseline-v6 | 0.0003 | DECISION | D046 |
| min_stop_distance_rate | range-mr baseline-v6 | 0.003 | COST_GUARD | D046 |
| max_cost_to_risk | range-mr baseline-v6 | 0.15 | COST_GUARD | D046 |
| commission_rate_ttl_seconds | range-mr baseline-v6 | 3600 | DECISION | D046 |

