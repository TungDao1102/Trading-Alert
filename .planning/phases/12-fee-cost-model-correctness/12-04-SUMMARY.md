---
phase: 12-fee-cost-model-correctness
plan: 04
subsystem: backtest-fixtures
tags: [fixtures, candle-geometry, cost-guards, pre-flight-test, baselines]
status: complete

requires:
  - phase: 12-02
    provides: baseline-v5 and baseline-no-trade-v3 / baseline-simple-trend-v3 registry sets
  - phase: 12-03
    provides: 8-key cost identity binding (exit_slippage_rate)
provides:
  - scripts/gen_phase6_fixtures.py with BAR_HALF_RANGE geometry, v5/v3 ids, 8-key COST_MODEL, baseline writers
  - Seven regenerated simulator fixtures and two regenerated baseline fixtures with stops about 1.1 percent (simple-trend 1.83 percent) from entry
  - tests/test_phase6_fixture_geometry.py (permanent independent-arithmetic guard-clearance pre-flight)
affects: [12-06 (guards go live), 12-07, 12-09 (simulator cutover), 12-11 (D048 decision row)]

actuals:
  tokens: 31900
  tasks: 2
  commits: 4

commits: 4
plan_head_before: f899c9752dc0da006f00a720178458a7c17e690b
plan_head_after: 94de95cee5b3f72b3a5270c32067d54e7adf24b1

tech-stack:
  added: []
  patterns:
    - "Fixture geometry parameterised by one named constant (BAR_HALF_RANGE), regenerated deterministically"
    - "Pre-flight test recomputes plan geometry with the existing strategy/planner and checks guard thresholds with inline literal arithmetic (never the project producer)"

key-files:
  created:
    - tests/test_phase6_fixture_geometry.py
  modified:
    - scripts/gen_phase6_fixtures.py
    - tests/fixtures/phase6/intrabar_both_touched/input.json
    - tests/fixtures/phase6/intrabar_both_touched_short/input.json
    - tests/fixtures/phase6/intrabar_missing_fallback/input.json
    - tests/fixtures/phase6/limit_touch_no_fill/input.json
    - tests/fixtures/phase6/limit_partial_fill/input.json
    - tests/fixtures/phase6/limit_expiry/input.json
    - tests/fixtures/phase6/invalidation_cancels_entry/input.json
    - tests/fixtures/phase6/baselines/no_trade/input.json
    - tests/fixtures/phase6/baselines/simple_trend/input.json
    - tests/test_backtest_experiment.py
    - tests/test_backtest_binding.py
  deleted:
    - tests/fixtures/phase6/baselines/no_trade/expected.json
    - tests/fixtures/phase6/baselines/simple_trend/expected.json

key-decisions:
  - "Half-range 0.80 (planning-time prototype value) was kept unchanged: every fixture cleared both guards on the first regeneration, so no geometry retuning and no guard or registry value was touched."
  - "The stale baselines/*/expected.json files were removed: no test or source module reads an expected file under a baselines directory (the unused _load_expected helper in test_backtest_experiment.py is generic and never called with a baselines path)."

requirements-completed: [BKTS-01]

coverage:
  - deliverable: "Seven simulator fixtures regenerated on baseline-v5 / v4.0.0 with the 8-key cost dict"
    verification:
      - kind: test
        ref: "tests/test_phase6_fixture_geometry.py#test_fixture_carries_phase12_identity"
        status: pass
    human_judgment: false
  - deliverable: "All fixtures clear stop >= 0.3 percent (and >= 0.79 percent) and cost-to-risk <= 0.15 by independent literal arithmetic"
    verification:
      - kind: test
        ref: "tests/test_phase6_fixture_geometry.py#test_fixture_clears_both_cost_guards"
        status: pass
      - kind: test
        ref: "tests/test_phase6_fixture_geometry.py#test_simple_trend_baseline_clears_both_cost_guards"
        status: pass
    human_judgment: false
  - deliverable: "Baselines on the v3 sets; no-trade rejected by the planner RR gate; experiment tests bind fixtures directly"
    verification:
      - kind: test
        ref: "tests/test_phase6_fixture_geometry.py#test_no_trade_baseline_is_rejected_by_the_planner_rr_gate"
        status: pass
      - kind: test
        ref: "tests/test_backtest_experiment.py#test_cr03b_reproduced_trades_carry_typed_decimal_datetime_fields"
        status: pass
      - kind: test
        ref: "tests/test_backtest_experiment.py#test_cr11_baseline_tomls_carry_detector_and_cost_keys"
        status: pass
    human_judgment: false
  - deliverable: "Generator is deterministic and matches the committed fixtures byte for byte"
    verification:
      - kind: test
        ref: "tests/test_phase6_fixture_geometry.py#test_generator_is_deterministic_and_matches_committed_fixtures"
        status: pass
    human_judgment: false
---

# Phase 12 Plan 04: Phase 6 fixture regeneration with realistic geometry Summary

**The Phase 6 simulator and baseline fixtures are regenerated with a 0.80 1H half-range so ATR-derived stops sit about 1.1 percent from entry (was 0.06 to 0.26 percent), on the baseline-v5 / v3 sets with the 8-key cost dict, guarded by a permanent pre-flight test that checks both cost-guard thresholds with independent literal arithmetic.**

## Performance

- Tasks: 2 (1 tracer, 1 auto), both TDD with separate RED commits
- Commits: 4 (measured from the ledger)
- Files: 1 created, 12 modified, 2 deleted; no `src/` file touched

## Accomplishments

- `scripts/gen_phase6_fixtures.py`: new `BAR_HALF_RANGE = Decimal("0.80")` used for the 1H bars 0..248 in both builders (4H context bars keep 0.05); `PARAMETER_SET_ID = "baseline-v5"`, `STRATEGY_VERSION = "v4.0.0"`; `COST_MODEL` is the eight-key plain literal (fee entry/exit 0.0005, expected_slippage 0.0001, exit_slippage_rate 0.0003); decisive 1m candles rescaled (LONG low 121.10 / high 125.70, SHORT high 128.90 / low 124.30); docstrings state that geometry is planner-derived; `write_baseline_no_trade` and `write_baseline_simple_trend` added and called from `main()`.
- Measured geometry (independent arithmetic in the test): stop distance as a fraction of the adverse zone edge and cost-to-risk per fixture.

| Fixture | Stop rate | Cost-to-risk |
|---|---|---|
| LONG (intrabar_both_touched, missing_fallback, touch_no_fill, partial_fill, limit_expiry) | 1.133 percent | 0.1093 |
| SHORT (intrabar_both_touched_short) | 1.089 percent | 0.1145 |
| invalidation_cancels_entry | 1.072 percent | 0.1149 |
| baselines/simple_trend | 1.828 percent | 0.0704 |

  These match the planning-time prototype (LONG 1.133 percent, SHORT 1.089 percent, simple-trend about 1.83 percent). baselines/no_trade is rejected by the planner with `RR_TOO_LOW` as designed.
- `tests/test_phase6_fixture_geometry.py`: identity checks (set id, strategy version, exactly eight cost keys and values, per-fixture partial fill fraction), guard-clearance checks (stop >= 0.003 and >= 0.0079, cost-to-risk <= 0.15) with inline literals and no import of `src.risk.cost_rates` / `backtest.costs` for the expected values, a negative control showing the arithmetic rejects the old 0.06 percent geometry, a registry-binding check (fixture cost dict binds its named set without rebinding), and a generator determinism test that also compares generator output to the committed fixtures byte for byte.
- `tests/test_backtest_experiment.py`: `test_cr03b` now uses the baseline fixture's own set and cost dict (no rebinding to baseline-v3, no partial_fill_fraction respelling); `test_cr11` also covers baseline-no-trade-v3 and baseline-simple-trend-v3 and compares the four rate keys to the generator literal by value.
- `tests/test_backtest_binding.py`: D-05 grandfather log gains a Phase 12 (D048) paragraph; no test in that file changed.
- Old pipeline stays green: `tests/test_backtest_simulator.py` (SL exits, TOUCH_NO_FILL, PARTIAL_FILL, EXPIRED, INVALIDATION_CANCEL, exactly one trade each) passes on the regenerated fixtures before the plan 12-06 cutover.

## Task Commits

1. Task 1 RED: `372a589` test(12-04) - geometry pre-flight, identity, determinism
2. Task 1 GREEN: `b836d68` feat(12-04) - generator geometry, v5 ids, seven fixtures regenerated
3. Task 2 RED: `bc53b6a` test(12-04) - baseline cases, cr03b/cr11 rebound
4. Task 2 GREEN: `94de95c` feat(12-04) - baseline writers, baselines regenerated, expected.json removed, grandfather log

## Verification

- `pytest tests/test_phase6_fixture_geometry.py tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_binding.py tests/test_backtest_report.py`: pass
- Full `pytest tests`: exit 0
- `python scripts/gen_phase6_fixtures.py` run repeatedly: tree unchanged after the first regeneration
- `ruff check` on the generator and all touched tests: clean
- Task 1 acceptance: `git diff` after Task 1 showed only the seven listed input.json files under `tests/fixtures/phase6`; baselines untouched until Task 2.
- Tracer gate: verified end-to-end (geometry, simulator and experiment suites green) before expansion.

## Deviations from Plan

None - plan executed as written. The planning-time half-range (0.80) and decisive candle levels cleared the pre-flight on the first regeneration, so no retuning was needed.

Notes on wording: the plan and the grandfather-log text speak of "eight simulator fixtures"; the generator regenerates seven simulator fixtures plus two baselines. `registry_identity` was not touched (it is not a simulator input) and remains grandfathered. The log paragraph states this precisely.

## expected.json finding

No source or test reads an `expected.json` under `tests/fixtures/phase6/baselines` (searched `tests/`, `src/`, `scripts/` with Grep and CodeGraph; the only generic `_load_expected` helper in `tests/test_backtest_experiment.py` is defined but never called). Both files were removed with `git rm`.

## Known Stubs

None.

## Threat Flags

None. T-12-09 is mitigated: guard clearance is derived with independent literal arithmetic, and behavioural assertions in the simulator tests are unchanged.

## Notes

- Fixture line endings follow the platform (`write_text`); the determinism test compares working-tree bytes to generator output on the same platform.
- Pre-existing dirty files (`.planning/config.json`, `milestone.lock`, `state.json`, `.gsd/`) were not staged.
- The D048 decision-row text recording the deliberate fixture regeneration is left to plan 12-11.
- Ready for plan 12-05/12-06: the fixtures already satisfy both guards, so the risk-pipeline cutover can be verified against real trades.

## Self-Check: PASSED

Created and modified files exist (`tests/test_phase6_fixture_geometry.py`, generator, nine input.json files); the two expected.json files are absent; commits 372a589, b836d68, bc53b6a, 94de95c found in `git log`.
