---
phase: 14-backtest-causality-rewrite
plan: 09
subsystem: backtest
tags: [backtest, causality, engine, run-summary, regime, determinism, prefix-invariance, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-08 engine.simulate, case-input v2, tests/backtest_case_helpers.py; 14-01 records.build_trade_record/build_reject_record (regime parameter already present)"
provides:
  - "src/core/types.py: SetupResult.regime (optional trailing field, validated non-empty when given)"
  - "src/core/strategy.py: evaluate sets regime on the SETUP result and on every NO_TRADE result past the regime gate"
  - "src/backtest/engine.py: regime copied onto every filled and REJECT record; typed, sorted, JSON-native run_summary"
  - "src/backtest/case.py: optional 'regime' key on scripted plans (ScriptedPlan.regime)"
  - "tests/test_backtest_run_summary.py, tests/test_backtest_determinism.py: BKTS-04 producer and DOMN-03 simulator-level suites"
affects: [14-10, 14-11, 14-12, 14-13, 14-15, 14-16]

requirements-completed: [BKTS-02, DOMN-03, BKTS-04]

actuals:
  tokens: 58000
  tasks: 3
  commits: 5
plan_head_before: 40bd7502104b80a5936cf9aeec78ecd560a3a6fe
plan_head_after: 5d79b707d216d3220e4de60479a8e61ee26b45db

tech-stack:
  added: []
  patterns:
    - "Report-only metadata rides the SetupResult envelope, never the persisted Signal, so no signal id, fingerprint or plan hash can move (D-38)"
    - "Run-summary counts are recomputed from the emitted records at output time, so they cannot drift from the trades list"
    - "Order-sensitive stand-in risk function (refuses a fourth open entry) makes a determinism suite prove the (time, symbol) ordering rule, not only output stability"

key-files:
  created:
    - tests/test_backtest_run_summary.py
    - tests/test_backtest_determinism.py
  modified:
    - src/core/types.py
    - src/core/strategy.py
    - src/backtest/engine.py
    - src/backtest/case.py
    - tests/test_backtest_engine_strategy.py
    - tests/test_backtest_engine.py
    - tests/backtest_case_helpers.py

key-decisions:
  - "Regime lives on SetupResult only. Signal, signal_id, fingerprint and plan hashes are untouched; src/domain/signal.py and tests/fixtures/phase4 are unchanged and tests/test_fixture_harness.py passes"
  - "A NO_TRADE result names the regime once the 4H verdict is BULLISH/BEARISH/NEUTRAL (regime-family mismatch, forming bar, unknown family, no setup); the invalid-context verdict 'NO_TRADE' names none (regime None)"
  - "Planner, risk and TP1-sizing rejects now also count under no_trade_counts (as well as being REJECT records); the conflict skip and UNCERTAIN_ACCOUNT_STATE stay counter-only, as before"
  - "run_summary keys are built in sorted order; allowed_gaps_used keeps its 14-08 meaning (gaps that actually covered a funding hole)"
  - "tie_order_note is a fixed constant string naming the (time, symbol) order bias (Pitfall 12)"

duration: about 35 min
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 09: Regime on Records, Typed Run Summary and Determinism Suites Summary

**The strategy regime now flows evaluate -> SetupResult -> engine -> every TradeRecord (filled, non-filled and REJECT) without touching a single hash; the engine emits an 18-key sorted JSON-native run_summary recomputed from its own records; and rerun, shuffle, prefix-invariance, 1m no-lookahead and window-equivalence suites prove the engine's determinism at simulator level.**

## Accomplishments

- `SetupResult.regime: str | None = None` (trailing, default None, non-empty when given). `strategy.evaluate` passes the resolved regime on the SETUP result and on NO_TRADE results past the regime gate. Persisted `Signal` and all hashes are unchanged; the phase 4 golden suite passes with no fixture change.
- Engine: `_Entity.regime` and a `regime` argument on `_reject`/`_size_and_register` put the signal's regime on filled records and on every REJECT record (planner reject, risk reject, MIN_QTY/NOTIONAL TP1 sizing reject). Scripted plans accept an optional `regime` row key, else None.
- Typed run summary (see key list). Counts come from the emitted records (`exit_kind == END_OF_DATA`, `entry_kind == PENDING_AT_DATA_END`, `gap_through_stop`, `fallback_applied`, `constraints_extrapolated`, `touch_no_fill_count`) plus the engine's NO_TRADE counter.
- Determinism (16 tests, all green on first run): rerun on the 5-symbol scripted case and the 250-bar strategy case; seeded shuffles of strategy/context/funding/constraint/scripted rows and symbols; prefix P (cut 11:45) versus extended E (to 14:00) with the D-34 exclusion (END_OF_DATA, PENDING_AT_DATA_END) and a non-vacuity test showing exactly the excluded records move (ETH END_OF_DATA time changes, ADA PENDING_AT_DATA_END becomes EXPIRED); minutes appended after the prefix; seeded noise replacing every BTC minute after its stop-out; minutes beyond the data end never read; a window larger than the case equals the default windows.

## Final run_summary key list (18, sorted)

`allowed_gaps_used`, `constraints_extrapolated_count`, `context_timeframe` ("4h"), `context_window_bars` (300), `data_window` ({start_utc, end_utc}), `dataset_id` (64-hex or None), `end_of_data_count`, `fallback_count`, `gap_through_stop_count`, `intrabar_tie_break` ("STOP_FIRST"), `no_trade_counts` (sorted reason -> count), `pending_at_data_end_count`, `plan_source` ("STRATEGY" | "SCRIPTED"), `simulator_semantics_version` ("2.0.0"), `strategy_window_bars` (1000), `tie_order_note` (fixed string), `timeframe` ("1h"), `touch_no_fill_total`. No `parameters`/`parameters_json` key. Output top level is unchanged: `trades`, `run_summary`, `strategy_version`, `parameter_set_hash`, `cost_model_hash`, `symbols`.

## Task Commits

1. **Task 1 (tracer)**: `796c1f3` (test, RED: six regime tests fail with AttributeError/KeyError on the missing field), `380381f` (feat, GREEN)
2. **Task 2**: `4e42ec6` (test, RED: six of eight tests fail on missing keys, rejects missing from no_trade_counts, unsorted keys), `f8b4678` (feat, GREEN)
3. **Task 3**: `5d79b70` (test: determinism suites)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Scripted rows needed an optional `regime` key**
- **Found during:** Task 1
- **Issue:** The plan says a scripted-plan record carries "the scripted plan's regime if given", but the closed case-input v2 key set had no way to give one. `src/backtest/case.py` is not in the plan's file list.
- **Fix:** Added optional `regime` to the scripted row keys and `ScriptedPlan.regime` (default None); `regime` param on the `scripted_plan` test helper.
- **Files modified:** src/backtest/case.py, tests/backtest_case_helpers.py
- **Commit:** 380381f (code), 796c1f3 (helper)

**2. [Rule 1 - Bug] Rejects were missing from no_trade_counts**
- **Found during:** Task 2
- **Issue:** Plan 14-08's `_reject` wrote a REJECT record but never incremented the NO_TRADE counter, so planner, risk and TP1-sizing rejects were absent from `no_trade_counts`, contradicting the Task 2 behavior (and the protocol's NO_TRADE categories).
- **Fix:** `_reject` now calls `_count(reason_code)`. The 14-08 assertion `no_trade_counts == {}` in `tests/test_backtest_engine.py` (TP1 sizing reject case, two rejects) was updated to `{reason: 2}`; its point (not a CONFLICT) is unchanged.
- **Files modified:** src/backtest/engine.py, tests/test_backtest_engine.py
- **Commit:** f8b4678

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug). **Impact:** none on hashes or fixtures; one 14-08 test expectation corrected to the new, plan-mandated counting.

## TDD Gate Compliance

Task 1 and Task 2 each have a real RED commit (`test(14-09)`) that failed on the target tests before the `feat(14-09)` GREEN commit; `gsd_run check tdd-red-evidence` was not run. Task 3 is test-only: the determinism suites passed on first run, as the plan anticipated. To show they are not vacuous I mutated the engine and parser (removed the scripted-plan sort and the per-close symbol sort), which made `test_shuffled_scripted_rows_give_the_identical_output` fail; an earlier version of the suite did NOT detect that mutation (a fixed-size stand-in risk function is insensitive to order), so the scripted case now uses an order-sensitive `capped_risk_fn` (refuses a fourth open or resting entry). The mutation was reverted with `git checkout` of the two files. The D-34 non-vacuity is also asserted directly (the excluded records are exactly the ones that change).

## Issues Encountered

- Full `pytest -m "not docker"` (with the two known deploy files ignored) still crashes with a Windows access violation, early in the run (after ~18 tests, before any backtest file). I ran the whole suite twice by mistake while diagnosing (the first with `-x`); not retried further. The crashing file was not identified and is outside src/backtest scope. Instead the 62 test files that import `src.core`, `src.backtest`, `src.risk`, `src.domain`, plus all `test_analytics_*`, `test_paper_*` and `test_fixture_harness.py`, were run directly: all passed (5 pre-existing skips).
- `tests/test_universe_freeze.py::test_refreeze_refuses` PermissionError (known) was not part of the subset run.

## Verification (real output)

- `pytest tests/test_backtest_determinism.py tests/test_backtest_engine.py tests/test_backtest_engine_strategy.py tests/test_backtest_run_summary.py`: 74 passed (16 determinism, 8 run summary).
- `pytest tests/test_backtest_engine_strategy.py tests/test_fixture_harness.py tests/test_core_planner.py tests/test_core_strategy_breakout_retest.py tests/test_core_strategy_range_mr.py tests/test_backtest_engine.py`: all passed.
- Wider subset described above: all passed.
- `mypy src`: no issues in 145 source files. `ruff check .`: all checks passed. `ruff format --check .`: 397 files already formatted.
- Acceptance: `regime: str | None` in src/core/types.py; src/domain/signal.py and tests/fixtures/phase4 not in the diff; "intrabar_tie_break", "no_trade_counts", "end_of_data_count" in tests/test_backtest_run_summary.py; "tie_order_note" in src/backtest/engine.py; "END_OF_DATA", "PENDING_AT_DATA_END" and "random.Random(" in tests/test_backtest_determinism.py.
- Tracer gate (interactive, end-of-phase, automated verify only): verify command re-run after GREEN, passed; expansion continued.

## Regeneration inventory

none. No fixture, parameter set, pin or hash moved. `Signal`, `signal_id`, fingerprints, plan hashes, `simulator.run` (v1), `src/domain/*` and the cost model are untouched.

## Known Stubs

None.

## Threat Flags

None. T-14-18 (output determinism as evidence) is mitigated by the rerun, shuffle, prefix and 1m no-lookahead suites, and the summary counts are recomputed from trades in tests.

## Next Phase Readiness

Plan 14-15 adds the typed `ExperimentRecord` fields from this summary (it must refuse `plan_source == "SCRIPTED"`). Plan 14-12 switches `simulator.run` to `engine.simulate` and regenerates the v1 fixtures into v2 cases; `tests/test_backtest_determinism.py` shows the case shapes and the order-sensitive risk stand-in.

## Self-Check: PASSED

Both created test files exist on disk; commits `796c1f3`, `380381f`, `4e42ec6`, `f8b4678` and `5d79b70` are in `git log`; acceptance greps and plan verification commands re-ran green (full-suite caveat above).
