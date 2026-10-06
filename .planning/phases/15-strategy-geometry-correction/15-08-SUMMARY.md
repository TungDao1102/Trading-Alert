---
phase: 15-strategy-geometry-correction
plan: 08
subsystem: parameter-registry
tags: [parameters, rationale, baseline-v6, checkpoint, ratification, placeholder]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-02 rationale record and check_rationale, 15-03 registry keys (geometry_version, pivot widths, tp_mode, min_stop_atr), 15-07 census and checkpoint inputs"
provides:
  - "params/trend-pullback/baseline-v6.toml, params/breakout-retest/baseline-v6.toml, params/range-mr/baseline-v6.toml: three candidate sets at strategy_version v5.0.0, geometry_version 1, one rationale table per parameter"
  - "Pins for the three sets in tests/fixtures/phase4/parameters.json (23 pins), counted as candidate sets of their family"
  - "PHASE15_SETS and PHASE15_PLACEHOLDERS in tests/test_rationale.py (real-set rationale, PLACEHOLDER refusal and Family A plan test)"
  - "The user-ratified key | family | value | basis | ref table that plan 15-09 reads for the two -v4 baselines"
affects: [15-09, 15-13]

actuals:
  tokens: 14300
  tasks: 3
  commits: 4
plan_head_before: 748ce8164887d543a24692b7cb406152f53e9d5a
plan_head_after: 57891733f80c17bbbde8b4e8fe4350cdd9d4772f

key-files:
  created:
    - params/trend-pullback/baseline-v6.toml
    - params/breakout-retest/baseline-v6.toml
    - params/range-mr/baseline-v6.toml
  modified:
    - tests/fixtures/phase4/parameters.json
    - tests/test_rationale.py
    - tests/test_decision_alignment_params.py
    - tests/test_analytics_files.py
    - tests/test_registry.py
    - scripts/geometry_census.py
    - tests/test_geometry_census.py

key-decisions:
  - "Every value, basis and ref of the three sets is the user's answer 'ratify' to checkpoint 15-08-01; the executor chose no value"
  - "risk_rate, breakout_volume_threshold (B) and breakout_confirmation_bars (A, C) are omitted because no module under src/ reads them"
  - "Sets stay research-only: 16 (A), 17 (B) and 22 (C) PLACEHOLDER keys, so pin_stream_epoch refuses all three"

requirements-completed: [STRAT-02]

duration: ~1h
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 08: baseline-v6 candidate sets, ratified by the user Summary

**Three baseline-v6 parameter sets (trend-pullback, breakout-retest, range-mr) at strategy_version v5.0.0 with geometry_version 1, written exactly as the user ratified at checkpoint 15-08-01, each value justified by an in-file machine-checked rationale table, pinned and registered; PLACEHOLDER values keep them research-only.**

## Accomplishments

- Task 1 (checkpoint, blocking-human): answered by the user with the single word `ratify`; recorded verbatim under "Ratified parameter values" before any set file was written (commit becae26).
- Task 2 (tracer): `params/trend-pullback/baseline-v6.toml` with 29 parameters and 29 `[rationale.<key>]` tables, pinned (hash `2c4f1528...`), candidate id added, pin count 21. The real-set test shows `check_rationale` empty, `placeholder_keys` equal to the ratified PLACEHOLDER keys, `pin_stream_epoch` raising `UnrationalizedParameterSet`, and `evaluate` plus `plan` on the Family A hand-built window returning a plan whose stop is below `entry_min_price`. Tracer gate: the `<verify>` set re-run end to end passed before expansion (commit ce80a0c).
- Task 3: `params/breakout-retest/baseline-v6.toml` (31 parameters) and `params/range-mr/baseline-v6.toml` (36 parameters), pinned, candidate ids added, pin count 23, both ids in `PHASE15_SETS` (commit 5789173). PA-01..PA-07 pass on the real repository (`python -m scripts.decision_alignment.params`).
- Every value and basis of the three set files was compared programmatically with the table below: 29, 31 and 36 keys, no mismatch, and the key sets are identical to the table's key sets.
- baseline-v1..v5 and the other committed sets are untouched (`git diff` shows only the three new files under `params/`).

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

File value next to ratified value: the programmatic comparison described under Accomplishments found every `[parameters]` value of the three files equal to the "value" column above and every `[rationale.<key>]` basis and ref equal to the "basis" and "ref" columns (29 trend-pullback, 31 breakout-retest, 36 range-mr keys).

PLACEHOLDER keys per set (these block `pin_stream_epoch`, so the sets are research-only until a later successor set carries EXPERIMENT bases):

- trend-pullback baseline-v6 (16): cluster_cap, constraint_snapshot_ttl_seconds, entry_buffer_atr, funding_treatment, max_aggregate_open_risk, max_open_positions, min_stop_atr, minimum_rr, pivot_left_bars, pivot_right_bars, signal_expiry_hours, sl_buffer_atr, slippage_model, spread_fill_assumptions, swing_lookback, zone_tolerance_atr.
- breakout-retest baseline-v6 (17): the Phase 3 seed and portfolio and declared-cost placeholders above, min_stop_atr, plus atr_period, retest_depth_atr, retest_window_bars.
- range-mr baseline-v6 (22): the same common placeholders plus pivot_left_bars, pivot_right_bars, atr_period, range_break_buffer_atr, regime_filter_lookback, touch_tolerance_atr, zone_aging_bars, zone_min_touches.

## Omitted keys (no reader in src/)

| key | omitted from | reason |
|---|---|---|
| breakout_volume_threshold | breakout-retest baseline-v6 | no module under src/ reads it (research Pitfall 7) |
| breakout_confirmation_bars | trend-pullback and range-mr baseline-v6 | read only by the Family B detector in src/core/strategy.py |
| risk_rate | all three baseline-v6 sets | the account risk rate (AccountState) is the sizing source, WR-03; no src/ module reads the set key |

## Post-ratification census

The ratified values equal the 15-07 draft values for every key that any module reads: a parsed comparison of each written set with its draft (baseline-v5 content plus the draft geometry keys of 15-07 "Draft values used") differs only in the omitted unread keys above (risk_rate in all three, breakout_volume_threshold in B, breakout_confirmation_bars 3 in A and C). So no ratified value differs from its draft and the 15-07 draft counts stand.

As a confirmation that omitting the unread keys changes nothing, `scripts/geometry_census.py` was run once on each written set (`--registry-root params --parameter-set-id baseline-v6 --symbols BTCUSDT,ETHUSDT,SOLUSDT --days 30 --end-day 2026-10-01`, same window, equity 1,000 and warm-up as 15-07). Counts are information only; no value was or will be changed because of them (D-17). Every run exited 0, `invariant_violations` 0, `guard_other` empty.

| family | symbol | setups | plans | planner rejects | guard rejects | guard pass | invariant_violations |
|---|---|---|---|---|---|---|---|
| trend-pullback | BTCUSDT | 148 | 123 | RR_TOO_LOW 24, STALE_SETUP 1 | COST_TO_RISK_EXCEEDED 68, STOP_TOO_TIGHT 1 | 54 | 0 |
| trend-pullback | ETHUSDT | 155 | 112 | RR_TOO_LOW 42, STALE_SETUP 1 | COST_TO_RISK_EXCEEDED 8 | 104 | 0 |
| trend-pullback | SOLUSDT | 143 | 96 | RR_TOO_LOW 40, STALE_SETUP 7 | COST_TO_RISK_EXCEEDED 3 | 93 | 0 |
| trend-pullback | TOTAL | 446 | 331 | RR_TOO_LOW 106, STALE_SETUP 9 | COST_TO_RISK_EXCEEDED 79, STOP_TOO_TIGHT 1 | 251 | 0 |
| breakout-retest | BTCUSDT | 20 | 20 | none | COST_TO_RISK_EXCEEDED 16, STOP_TOO_TIGHT 1 | 3 | 0 |
| breakout-retest | ETHUSDT | 12 | 12 | none | COST_TO_RISK_EXCEEDED 5 | 7 | 0 |
| breakout-retest | SOLUSDT | 19 | 19 | none | COST_TO_RISK_EXCEEDED 4 | 15 | 0 |
| breakout-retest | TOTAL | 51 | 51 | none | COST_TO_RISK_EXCEEDED 25, STOP_TOO_TIGHT 1 | 25 | 0 |
| range-mr | BTCUSDT | 19 | 14 | RR_TOO_LOW 5 | COST_TO_RISK_EXCEEDED 12, STOP_TOO_TIGHT 2 | 0 | 0 |
| range-mr | ETHUSDT | 32 | 29 | RR_TOO_LOW 3 | COST_TO_RISK_EXCEEDED 28, STOP_TOO_TIGHT 1 | 0 | 0 |
| range-mr | SOLUSDT | 15 | 10 | RR_TOO_LOW 5 | COST_TO_RISK_EXCEEDED 4 | 6 | 0 |
| range-mr | TOTAL | 66 | 53 | RR_TOO_LOW 13 | COST_TO_RISK_EXCEEDED 44, STOP_TOO_TIGHT 3 | 6 | 0 |

These are identical to the 15-07 draft-v6 tables, symbol by symbol.

## Regeneration inventory

New pins appended to `tests/fixtures/phase4/parameters.json` (list now 23 entries; `scripts/_regen_phase4_expectations.py` was not run):

| strategy_id | parameter_set_id | strategy_version | parameter_set_hash |
|---|---|---|---|
| trend-pullback | baseline-v6 | v5.0.0 | 2c4f1528b00f1b1e48c76040bbd6cc218a25eec21c521d8b68da86ee4811360f |
| breakout-retest | baseline-v6 | v5.0.0 | 289d47ac5a77fd67d0551e0cb004e29562755b9455e7f9161567e7957746174d |
| range-mr | baseline-v6 | v5.0.0 | c9023e476e762fc56c993f3e920133d84a8d5700ec20805e9e85135148324100 |

Moved digests: none. No existing pin, file byte lock or `parameter_set_hash` changed. The candidate hash list of each family in the analytics scan grew by its new set; `_EXPECTED_CANDIDATE_IDS` in tests/test_analytics_files.py was extended with "baseline-v6" for all three families, and no other pinned digest in the kill-gate and analytics tests moved.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] tests/test_registry.py guard forbade Phase 15 keys in every committed set**
- **Found during:** Task 2 (first run of the verify suite)
- **Issue:** `test_committed_sets_carry_no_phase15_key` (added in 15-03) failed as soon as the first set with geometry_version was committed.
- **Fix:** renamed to `test_committed_sets_carry_no_phase15_key_outside_the_phase15_sets`; the five Phase 15 set ids (the three baseline-v6 sets and the two -v4 baselines that plan 15-09 writes) must carry `geometry_version` 1, every other committed set must still carry none of the Phase 15 keys.
- **Files modified:** tests/test_registry.py
- **Commit:** ce80a0c

**2. [Rule 1 - Bug] tests/test_rationale.py hash-neutrality test appended a second rationale block to sets that already carry one**
- **Found during:** Task 2 (reading the test before running it; a duplicate `[rationale]` table is invalid TOML)
- **Fix:** for a pinned set whose file already contains `[rationale.` tables the test verifies the pin as written, requires the id to be in `PHASE15_SETS`, and counts it.
- **Files modified:** tests/test_rationale.py
- **Commit:** ce80a0c

**3. [Rule 3 - Blocking] scripts/geometry_census.py read `params["risk_rate"]`, which the ratified v6 sets omit**
- **Found during:** Task 3 (the post-ratification census would have exited with a KeyError)
- **Fix:** `params.get("risk_rate", ACCOUNT_RISK_RATE)` with `ACCOUNT_RISK_RATE = Decimal("0.005")`, the documented per-trade rate of RISK_MANAGEMENT.md section 1 (the value every earlier set carried); a test runs the census window on a set without the key and requires identical counts. RED confirmed (KeyError) before the fix.
- **Files modified:** scripts/geometry_census.py, tests/test_geometry_census.py
- **Commit:** 063e75f

### Notes

**1. [Interpretation, for the user's attention] Basis of the three overridden -v4 baseline values.** The checkpoint text lists the two comparison baselines as "A v6 values with minimum_rr 100" and "with zone_tolerance_atr 1.0 and minimum_rr 0.5" but names no basis for those three values. The table records DECISION with ref D054 for them, taken from the wording of plan 15-09 ("DECISION with ref D054 for the degenerate minimum_rr 100") and the D-26 role of the baselines. Plan 15-09 writes them from this table; if the user wants another basis it must be changed there before the files are written.

**2. D054 does not exist yet in docs/DECISIONS.md.** Rows with ref D054 (geometry_version and the three baseline override values) name the entry that a later plan of Phase 15 writes; `check_rationale` only requires the form D plus three digits. The pointer is valid once that entry lands.

**3. Pre-existing, out of scope.** `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` (CRLF vs LF) is unchanged and already in deferred-items.md.

## Verification

- `pytest tests/test_rationale.py tests/test_registry.py tests/test_registry_gate.py tests/test_decision_alignment_params.py tests/test_analytics_files.py tests/test_kill_gate_families.py tests/test_analytics_cli.py`: all pass (one skipped test is pre-existing). `pytest tests/test_decision_alignment.py tests/test_domain_no_float.py tests/test_sufficiency.py tests/test_paper_freeze.py tests/test_demo_rehearsal_safety.py tests/test_geometry_census.py tests/test_geometry_property.py`: all pass.
- `python -m scripts.decision_alignment.params`: PA-01 to PA-07 ok.
- `ruff check src tests scripts`: clean; `ruff format --check`: 387 files formatted; `mypy src`: no issues in 149 files.
- Targeted suites only, foreground (the three census runs included); no background process left.

## Known Stubs

None. The PLACEHOLDER values are ratified, labelled values, not stubs: they are recorded in each set's rationale and block paper pinning by design (D-27).

## Threat Flags

None. T-15-15 mitigated: the checkpoint was answered by the user (verbatim reply recorded, marker grep checked before each task) and every file value was compared with that record. T-15-16 mitigated: the three pins were appended, PA-01 verifies them, baseline-v1..v5 are byte-locked and unchanged. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: params/trend-pullback/baseline-v6.toml, params/breakout-retest/baseline-v6.toml, params/range-mr/baseline-v6.toml
- FOUND: commits becae26, ce80a0c, 063e75f, 5789173
- FOUND: "Ratified-by: user (verbatim reply to checkpoint 15-08-01)" followed by "ratify", "## Post-ratification census", "## Regeneration inventory"
- `grep -c baseline-v6 tests/fixtures/phase4/parameters.json` shows 3 pinned v6 sets in a 23-entry list

