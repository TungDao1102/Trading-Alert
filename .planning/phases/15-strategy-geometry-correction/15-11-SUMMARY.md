---
phase: 15-strategy-geometry-correction
plan: 11
subsystem: planner-tests-and-phase4-snapshots
tags: [tests, planner, geometry, regression-snapshot, postgresql, tracer]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-08 ratified baseline-v6 sets, 15-03/15-04 corrected geometry in strategy and planner, tests/geometry_builders.py windows (15-03, 15-05, 15-06)"
provides:
  - "tests/test_core_planner.py: all 17 planner unit tests on baseline-v6 and the a_long_worked confirmed-pivot window, every original intent kept"
  - "scripts/_regen_phase4_expectations.py: pin-safe regeneration (writes only expected_signals.json and expected_plans.json), plans built from baseline-v6 on the three geometry_builders windows"
  - "tests/fixtures/phase4/expected_signals.json and expected_plans.json: regression snapshots (D-19, Phase 14 D-25) of three v6 plans"
  - "tests/test_plan_hash_roundtrip_pg.py: all five windows and both directions on baseline-v6, compared with the regenerated snapshot"
affects: [15-13]

actuals:
  tokens: 9600
  tasks: 2
  commits: 2
plan_head_before: 96262d130e765187fc21a1ff62e4582cb302779f
plan_head_after: 15fbaf8bd730d04d660b58de8b9e39e10a628198

key-files:
  created: []
  modified:
    - tests/test_core_planner.py
    - scripts/_regen_phase4_expectations.py
    - tests/fixtures/phase4/expected_signals.json
    - tests/fixtures/phase4/expected_plans.json
    - tests/test_plan_hash_roundtrip_pg.py

key-decisions:
  - "No parameter value was chosen or tuned: every set is the registered baseline-v6; the only overrides are single in-memory minimum_rr copies in the RR gate tests, derived from the plan's own hand-derived RR 4.375 (and 1000 as before)"
  - "tests/geometry_builders.py needed no new window: family_a_long_window, family_b_long_window/short_window and range_mr_long_window/short_window already plan on baseline-v6"
  - "The regeneration script no longer writes tests/fixtures/phase4/parameters.json or expected_features.json: the pin file belongs to the PA-01 gate (T-15-19) and the legacy features did not change"
  - "Snapshot files are written with LF line endings (newline='\\n') so a regeneration on any platform gives the same bytes"

requirements-completed: [STRAT-02]

duration: ~40min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 11: planner tests and Phase 4 snapshots on baseline-v6 Summary

**The 17 planner unit tests, the Phase 4 plan snapshots and the PostgreSQL plan-hash test now plan from the registered baseline-v6 sets on confirmed-pivot, anchored-retest and pivot-NEUTRAL windows, and the regeneration script can no longer overwrite the pin file.**

## Accomplishments

- Task 1 (tracer, commit 358fdf6): `tests/test_core_planner.py` loads `trend-pullback/baseline-v6` and builds its window with `geometry_builders.family_a_long_window()` (the a_long_worked case: pivot low 99.00, ATR 2.00, zone 98.00-100.00, entry 97.80-100.20, stop 97.40, TP1 106.00, RR 4.375). The phase4 CSV window, the `_with_support_touch_last_bar` patch and every `baseline-v1` reference are gone (`grep -c baseline-v1` prints 0). The tracer gate (`<verify>` end to end: 17 planner tests plus tests/test_planner_geometry.py, 96 passed) held before the expansion task.
- Task 2 (commit 15fbaf8): `scripts/_regen_phase4_expectations.py` builds trend-pullback, breakout-retest LONG and range-mr LONG on `family_a_long_window`, `family_b_long_window` and `range_mr_long_window` with baseline-v6, and writes only `expected_signals.json` and `expected_plans.json`. `git diff --quiet` on `parameters.json` and `expected_features.json` exits 0 after running it; two consecutive runs give byte-identical files. `tests/test_plan_hash_roundtrip_pg.py` takes its five windows (trend-pullback, breakout-retest LONG/SHORT, range-mr LONG/SHORT) from the same builders with baseline-v6, no longer needs the phase4 CSV, and `test_planner_hashes_equal_the_pinned_phase4_fixture` passes against the regenerated snapshot.

## Regeneration inventory

Phase 4 snapshot (the three plans, equity 10000.00, risk rate 0.005, `created_at = source_close + 1h`). Old values come from baseline-v1 on the legacy windows, new values from baseline-v6 on the geometry_builders windows.

| Strategy | Old signal_id | New signal_id |
| --- | --- | --- |
| trend-pullback LONG | 39a81ffcaa8db4fe07fef8b5e41b1c86dfd03d97e08965c865244af3b0a80766 | d7e34148c595633cc460cfebe4c13a29dece9aa0ac3e98046d94434b09733352 |
| breakout-retest LONG | bffcc6a24417850c9b9125a7e4ad7947ee91cf5ab19bad0a65a4c1c747d2ca90 | d5121fe65deada8abb1cb7509a4e49290bb484661166469e9353f7c9b09befa4 |
| range-mr LONG | 43765c0e8515ed1833bc1349185a20e791172ce0630c3ed7fa479216d9618144 | b4858298e73a402132264ffb8e1d8223ea9987d67933c2f8841f5c4e12f1e2fb |

| Strategy | Old trade_plan_id | New trade_plan_id |
| --- | --- | --- |
| trend-pullback | 232ad4c62fa194e5f7a4b08fc4aba59eeafcb8c35c4d53ff5bd9484657bb074d | 643a4cdc6bdf36881bc6310581a6cc7c1429f7b8b230b7059babee97b68f8d59 |
| breakout-retest | b629250f5103cdb5ac0b544b241621022efa7126b42bb209834d019e806cca85 | 9e577cbd2f2f0b1d3e7ec4f8532b2c2f63521b9e018a6ba72d14752919248a1b |
| range-mr | 9c41bdf7cbe0ead07414c21e2b2cda48b8bf58b6d809d9145fd32c93e2bea06d | fb8fcd85eca42f5deccf51e557fef08554b639dc4bdc2e52d39599c0c2fa225b |

| Strategy | Old plan_hash | New plan_hash |
| --- | --- | --- |
| trend-pullback | 99d38a1d1fec0eb273e15fd323099cfdfcb7700e1a7d1f06010088aae934a2c0 | d78022cf1716f5d7b2f754354e1e7147a06baa779d5b5ce9576d55a6d67c6807 |
| breakout-retest | 8b7b24eedd950b6b8326df44e17a3ea88d54dc61bc6062f5f95103f3066bda9d | 4774102307c2d83bfd6ce9ad7a441bc0a0d4c6059aa4eb9de844bde86141a432 |
| range-mr | d90a223225aa1a630cd360897867db8e68e3ed44b1a5d9958876b2d8feec01cf | 854396bdbfd2d099352c239dc160d2d6cf416b5b28e5d4d3ae62fd58ae4115bb |

New plan geometry (entry_min / entry_max / stop / quantity at equity 10000.00): trend-pullback 97.80 / 100.20 / 97.40 / 31.25 (stop strictly below entry_min); breakout-retest 101.80 / 102.20 / 99.60 / 20.833333333333333333; range-mr 97.80 / 98.20 / 96.60 / 35.714285714285714286. `parameter_set_id` of all three signals is now `baseline-v6`.

Git blob hashes (LF, `git hash-object`): expected_signals.json a55a7024... to 212f56a6abd98e5a00e9b880fb2ed9d38e4b4844, expected_plans.json 34ebf3f5... to d7547c8a6e73a974a5b195782485a850098ffc38. Not changed (verified with `git diff --quiet`): `tests/fixtures/phase4/parameters.json` (24390c78...), `expected_features.json` (b2ca7695...), `candles.csv`, and every file under `params/`.

Line endings: the script writes the two files with LF explicitly; on this Windows checkout (`core.autocrlf=true`) git prints the usual "LF will be replaced by CRLF" notice and stores LF, so the diff holds only the content changes (63 insertions, 63 deletions).

### Per-test before and after (tests/test_core_planner.py, 17 tests before and after; `pytest --collect-only` prints 17 both times)

| Test | Old fixture | New fixture | Assertion |
| --- | --- | --- | --- |
| test_entry_zone_math_long | phase4 CSV window, last bar patched onto the trailing swing low, baseline-v1 | a_long_worked window, baseline-v6 | rewritten: legacy priced zone off the swing low and put the stop inside the zone; now zone = P +/- zone_tolerance_atr x ATR, entry range widened by entry_buffer_atr, stop = entry_min - sl_buffer_atr x ATR strictly below entry_min, plus hand-derived literals 97.80 / 100.20 / 97.40 (D-05, D-06) |
| test_rr_gate_exact_equality_passes | CSV window, baseline-v1 default | a_long_worked, baseline-v6 | unchanged (READY) and strengthened: tp1_rr is 4.375 and an override minimum_rr = 4.375 (single in-memory copy, in the docstring) is admitted |
| test_rr_gate_one_tick_above_passes | CSV window, baseline-v1 default | a_long_worked, override minimum_rr = 4.374 | unchanged (admitted, trade_plan present); now really exercises the one-tick boundary |
| test_rr_gate_below_returns_no_trade_with_rr_too_low | last bar low lowered by 500, assertion only `if is_no_trade` | last bar high raised by 500 (ATR jumps, stop far below, RR collapses), plus override minimum_rr = 4.376 | rewritten with reason: a low below the stop is INVALIDATED under D-07, so the legacy deep-wick perturbation can no longer reach RR_TOO_LOW; the assertion is now unconditional (NO_TRADE, RR_TOO_LOW, trade_plan None) in both variants, which is stronger |
| test_rr_gate_fires_on_structure_tp_below_minimum | strict copy minimum_rr 1000 | same, via `_with_override` on baseline-v6 | unchanged |
| test_plan_empty_candles_returns_no_trade | CSV window | a_long_worked | unchanged (DATA_STALE) |
| test_plan_expired_signal_returns_no_trade | CSV window | a_long_worked | unchanged (APPROVAL_EXPIRED) |
| test_plan_symbol_mismatch_returns_no_trade | CSV window | a_long_worked | unchanged (DATA_STALE) |
| test_plan_hash_recomputable_from_payload | CSV window | a_long_worked | unchanged |
| test_persisted_decimals_fit_numeric_38_18 | CSV window | a_long_worked | unchanged |
| test_plan_hash_is_spelling_invariant | none | none | unchanged |
| test_trade_plan_id_derives_from_signal_id | CSV window | a_long_worked | unchanged |
| test_expiry_equals_source_close_plus_signal_expiry_hours | CSV window | a_long_worked | unchanged |
| test_invalidation_json_schema | CSV window | a_long_worked | unchanged |
| test_deferred_quantization_equality | CSV window | a_long_worked | unchanged |
| test_planner_has_no_float_literals | none | none | unchanged |
| test_plan_result_envelope_validation | none | none | unchanged |

### PostgreSQL tests (tests/test_plan_hash_roundtrip_pg.py, 22 tests)

Ran locally (2): `test_decimal_field_list_is_the_eight_persisted_plan_columns` and `test_planner_hashes_equal_the_pinned_phase4_fixture` (this one also builds all 15 plans of the module fixture, five windows at three equities, so every v6 window plans successfully).
Could not run locally (20, skipped with "TEST_DATABASE_URL is not set"): 15 `test_real_plan_round_trips_and_reproduces_its_plan_hash` cases, 3 `test_a_price_with_nineteen_fractional_digits_is_refused_by_the_guard` cases, `test_recomputed_hash_is_sensitive_to_a_changed_stored_value` and `test_integer_part_overflow_still_raises_a_database_error`. A Docker PostgreSQL container is up on this machine, but the test URL needs its credentials from `.env`, which this run must not read, so those 20 are left to CI. They do not depend on geometry beyond what the 15 built plans already show (prices at scale 18, hash recomputation).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Plan imprecision] The deep-wick RR_TOO_LOW test cannot keep its perturbation**
- **Found during:** Task 1
- **Issue:** the legacy test lowered the last bar's low by 500 and asserted RR_TOO_LOW only conditionally. On the corrected geometry that bar is INVALIDATED (signal low below the stop, D-07), not RR_TOO_LOW.
- **Fix:** the perturbation raises the last bar's high instead (same intent: widen the zone through ATR) and the assertion is unconditional; the one-tick-above-RR boundary (override 4.376) is added. Intent kept and strengthened; nothing weakened.
- **Files modified:** tests/test_core_planner.py
- **Commit:** 358fdf6

**2. [Rule 3 - Dead code] Legacy trend builders and feature writes removed from the regeneration script**
- **Found during:** Task 2
- **Issue:** `_build_trend_1h`, `_build_trend_4h`, `_with_support_touch_last_bar` and the `compute_features` block existed only to rewrite the legacy windows, `parameters.json` and `expected_features.json`.
- **Fix:** removed with the writes (the acceptance criteria require the writes gone); the CSV helpers `_build_candles_from_csv` and `_first_gap_index` left `tests/test_core_planner.py` for the same reason (their only other user was the PG test, migrated here).
- **Files modified:** scripts/_regen_phase4_expectations.py, tests/test_core_planner.py
- **Commit:** 15fbaf8, 358fdf6

**3. [Explained, not a defect] No new geometry_builders window**
- `tests/geometry_builders.py` is in the plan's file list but needed no change; the existing windows plan on baseline-v6.

## Auth gates

None.

## Known Stubs

None.

## Threat Flags

None. T-15-19 mitigated (the script has no write call for the pin file or the features file; `git diff --quiet` on both exits 0 after a run). T-15-20 mitigated (17 tests before and after, per-test table above, no assertion weakened). T-15-SC accepted (no installs).

## Verification

- `pytest tests/test_core_planner.py tests/test_planner_geometry.py tests/test_core_features.py tests/test_fixture_harness.py tests/test_decision_alignment_params.py`: 180 passed.
- `pytest tests/test_plan_hash_roundtrip_pg.py`: 2 passed, 20 skipped (no TEST_DATABASE_URL).
- `scripts/_regen_phase4_expectations.py` run twice: identical blob hashes; `git diff --quiet -- tests/fixtures/phase4/parameters.json tests/fixtures/phase4/expected_features.json` exits 0.
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 388 files formatted; `mypy src`: no issues in 149 source files.
- Targeted suites only, foreground, no background process left.

## Self-Check: PASSED

- FOUND: tests/test_core_planner.py, scripts/_regen_phase4_expectations.py, tests/fixtures/phase4/expected_signals.json, tests/fixtures/phase4/expected_plans.json, tests/test_plan_hash_roundtrip_pg.py
- FOUND: commits 358fdf6, 15fbaf8
- `git diff --stat` of the two task commits lists only those five files
