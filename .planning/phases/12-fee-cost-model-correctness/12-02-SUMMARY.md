---
phase: 12-fee-cost-model-correctness
plan: 02
subsystem: parameter-registry
tags: [registry, parameter-sets, unit-guard, cost-guards, decision-alignment-gates]
status: complete

requires:
  - phase: 11
    provides: baseline-v4 / no-trade-v2 / simple-trend-v2 sets, PA-01..PA-06 gates, pin file
provides:
  - Four optional registry keys (exit_slippage_rate, min_stop_distance_rate, max_cost_to_risk, commission_rate_ttl_seconds)
  - Loader unit guard: fee/slippage rates outside 0..0.01 refused, naming the key
  - Five v4.0.0 parameter sets carrying the frozen Phase 12 values, all pinned (20 pins)
  - Gate PA-07 and dispatcher params minimum 7
affects: [12-03 cost model, 12-06 cost guards, 12-11 decision rows (D046)]

actuals:
  tokens: 10950
  tasks: 3
  commits: 6

commits: 6
plan_head_before: 7a1b8485a1e04b7318db7829877e0fbe4d9762f3
plan_head_after: 9a169ec6a25e832b8b9b7e1a9535013a43a1aa83

tech-stack:
  added: []
  patterns:
    - "Optional registry key (working_type precedent): absent in old sets, so old hashes never move"
    - "New superseding set per change; existing TOML files never edited (F-810)"

key-files:
  created:
    - params/trend-pullback/baseline-v5.toml
    - params/breakout-retest/baseline-v5.toml
    - params/range-mr/baseline-v5.toml
    - params/trend-pullback/baseline-no-trade-v3.toml
    - params/trend-pullback/baseline-simple-trend-v3.toml
  modified:
    - src/domain/registry.py
    - tests/fixtures/phase4/parameters.json
    - tests/test_registry.py
    - tests/test_analytics_files.py
    - scripts/decision_alignment/params.py
    - scripts/verify_decision_alignment.py
    - tests/test_decision_alignment_params.py

key-decisions:
  - "exit_slippage_rate is whitelisted in STRATEGY_KEYS but deliberately not in the 7-key COST_KEYS tuple; plan 12-03 adds it presence-driven, so cost_model_hash of every existing set is unchanged."
  - "Frozen values 0.0003 / 0.003 / 0.15 / 3600 are pinned by hash and asserted by PA-07; the 0.79 percent minimum-stop implication of max_cost_to_risk 0.15 is stated in every v5 header for ratification in D046."

requirements-completed: [DOMN-02, RISK-01]

coverage:
  - deliverable: "Registry whitelists the four keys with INT/Decimal typing; unit errors and out-of-range guard values refused at load"
    verification:
      - kind: test
        ref: "tests/test_registry.py#test_rate_key_unit_error_raises_naming_key"
        status: pass
      - kind: test
        ref: "tests/test_registry.py#test_guard_keys_range_checked"
        status: pass
    human_judgment: false
  - deliverable: "Five v4.0.0 sets equal predecessor plus four keys, pinned, existing files untouched"
    verification:
      - kind: test
        ref: "tests/test_registry.py#test_baseline_v5_matches_phase12"
        status: pass
      - kind: test
        ref: "tests/test_registry.py#test_every_params_toml_has_a_pin_that_verifies"
        status: pass
      - kind: command
        ref: "git diff --name-status 7a1b848..HEAD -- params/ (five A lines, no M or D)"
        status: pass
    human_judgment: false
  - deliverable: "PA-07 gate and dispatcher minimum 7"
    verification:
      - kind: command
        ref: ".venv/Scripts/python scripts/verify_decision_alignment.py params (PA-01..PA-07, ALL_PASS params)"
        status: pass
      - kind: test
        ref: "tests/test_decision_alignment_params.py#test_pa07_passes_on_copy"
        status: pass
    human_judgment: false
---

# Phase 12 Plan 02: Registry cost-guard keys and v5 parameter sets Summary

**Four optional Phase 12 registry keys (stop-exit slippage, minimum stop distance, cost-to-risk ceiling, commission TTL) with a loader that refuses fee/slippage unit errors above 0.01, carried by five new pinned v4.0.0 sets and a new PA-07 gate; all earlier sets stay byte- and hash-identical.**

## Performance

- Tasks: 3 (1 tracer, 2 auto), all TDD with separate RED commits
- Commits: 6 (measured from the ledger)
- Files: 5 created, 7 modified

## Accomplishments

- `registry.py`: four names added to `STRATEGY_KEYS`; `commission_rate_ttl_seconds` in `INT_KEYS`, the other three Decimal. New `RATE_UNIT_KEYS` / `MAX_RATE` constants and `_check_value_range`, called from `_check_param_types`: a fee or slippage rate that is negative or above 0.01 raises `StrategyKeyOutsideRegistry` naming the key and "unit error" (a fee of 2 is refused); `min_stop_distance_rate` must lie in (0, 1), `max_cost_to_risk` in (0, 1], `commission_rate_ttl_seconds` above 0. Hashing and `_normalize_value` untouched. Ambient config named after any of the four keys is rejected like every strategy key.
- Five new sets, each predecessor plus the four keys and `strategy_version = "v4.0.0"`, headers naming what they supersede: trend-pullback/baseline-v5, breakout-retest/baseline-v5, range-mr/baseline-v5, trend-pullback/baseline-no-trade-v3, trend-pullback/baseline-simple-trend-v3. `minimum_rr` 100 and the simple-trend zone/RR values are preserved.
- Five pin entries appended (20 in total). Pinned hashes: trend-pullback/baseline-v5 41ed39d4..., breakout-retest/baseline-v5 5737e9cd..., range-mr/baseline-v5 40a7ce92..., no-trade-v3 9efd3504..., simple-trend-v3 17016aeb....
- PA-07 `check_phase12_set_facts` (over `PHASE12_SET_IDS`): file exists and loads, version v4.0.0, four frozen values with exact types, Supersedes header, rates within 0..0.01, and one identical value for each of the eight cost keys (the 7 `COST_KEYS` plus `exit_slippage_rate`) across the five sets. PA-04 and PA-05 constants untouched. Dispatcher `EXPECTED_MIN["params"]` raised 6 to 7.

## Task Commits

1. Task 1 RED: `b653423` test(12-02) - unit guard, range, key typing, baseline-v5 facts
2. Task 1 GREEN: `45075b9` feat(12-02) - registry changes, trend-pullback baseline-v5, first pin
3. Task 2 RED: `0fd3f98` test(12-02) - facts test over three families, v5 candidate ids
4. Task 2 GREEN: `9830a3d` feat(12-02) - breakout-retest and range-mr baseline-v5, pins
5. Task 3 RED: `74fbae0` test(12-02) - PA-07 positive and negative tests, 20 pins
6. Task 3 GREEN: `9a169ec` feat(12-02) - baseline sets, PA-07, dispatcher minimum

## Verification

- Step 0 (before any change): PA-01..PA-03 green on the untouched tree, i.e. the ten pre-Phase-11 hashes, file digests and fifteen pins verified.
- `pytest tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py tests/test_backtest_binding.py tests/test_backtest_experiment.py tests/test_decision_alignment_params.py tests/test_decision_alignment.py tests/test_paper_freeze.py`: pass
- `scripts/verify_decision_alignment.py params`: seven PASS lines, `ALL_PASS params`
- Full `pytest tests`: green
- `mypy src/domain/registry.py scripts/decision_alignment/params.py`: clean; `ruff check` on all touched files: clean
- `git diff --name-status 7a1b848..HEAD -- params/`: five `A` lines, no `M` or `D`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Keep intermediate commits green**
- **Found during:** Task 1 GREEN
- **Issue:** Adding a pin and a new candidate set made `test_tracer_real_repo_scan_feeds_evaluator` (analytics candidate ids) and `test_reference_tables_cover_ten_old_and_five_new_sets` (pin count) fail one task earlier than the plan scheduled those edits.
- **Fix:** Updated the trend-pullback candidate tuple and the pin count (16, then 18 in Task 2, 20 in Task 3) in the task that adds the set; moved the unpinned-extra-file negative test to a `baseline-v9` name in Task 1 (the plan scheduled it for Task 3) because Task 2 makes `range-mr/baseline-v5` a real file.
- **Files modified:** tests/test_analytics_files.py, tests/test_decision_alignment_params.py
- **Commits:** 45075b9, 9830a3d

Otherwise the plan executed as written. No other test enumerates the params directory beyond those listed.

## Known Stubs

None.

## Threat Flags

None. No new network, auth or file-access surface; T-12-03, T-12-04 and T-12-05 mitigations are in place (loader unit and range checks, pins plus PA-01..PA-03, PA-07).

## Notes

- Pre-existing dirty files (`.planning/config.json`, `milestone.lock`, `state.json`, `.gsd/`) were not staged.
- `ruff check .` over the whole repo reports 36 pre-existing findings in files this plan does not touch (scripts/_compute_phase4_fixtures.py, src/ops/drills.py and others); out of scope.
- Nothing yet reads the four keys: plan 12-03 (cost model) and 12-06 (guards) consume them.

## Self-Check: PASSED

All five new TOML files and the SUMMARY exist; commits b653423, 45075b9, 0fd3f98, 9830a3d, 74fbae0, 9a169ec found in `git log`.
