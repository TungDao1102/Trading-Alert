---
phase: 14-backtest-causality-rewrite
fixed_at: 2026-10-05T00:00:00Z
review_path: .planning/phases/14-backtest-causality-rewrite/14-REVIEW.md
iteration: 1
findings_in_scope: 13
fixed: 13
skipped: 0
status: all_fixed
---

# Phase 14: Code Review Fix Report

**Fixed at:** 2026-10-05
**Source review:** .planning/phases/14-backtest-causality-rewrite/14-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 13 (2 Critical, 11 Warning; Info excluded by `fix_scope: critical_warning`)
- Fixed: 13
- Skipped: 0

**Verification:** `workflow.use_worktrees` is `false`, so every fix was edited, tested and committed in the main checkout (no worktree, no recovery sentinel). After each fix the relevant pytest subsets (`tests/test_backtest_*.py`, analytics, case-input, phase 6 geometry) and `ruff check` / `ruff format` were run. Every new regression test was confirmed to fail without its fix (CR-01, WR-09). A full-suite run was not possible on this machine: unrelated tests (`tests/test_deploy_backup_scripts.py` and another native-code test) crash the Python process with a Windows access violation, so the suite was run in scoped subsets that exclude them. The unrelated working-tree changes (`.planning/config.json`, `.gsd/`, `package*.json`) were never staged.

## Fixed Issues

### CR-01: END_OF_DATA exit can be dated before the plan's own TP1 leg
**Files modified:** `src/backtest/exits.py`, `tests/test_backtest_exits.py`
**Commit:** c7fa4c2
**Applied fix:** `end_of_data_exit` now floors the leg time at `max(entry_time, state.tp1_time_utc)`, so the forced close is never dated before an event the position already produced. Added a regression test (mark hole in the last bar plus a fallback-booked TP1 touch, validated through `validate_trade_record`).

### CR-02: `assemble` does not bind the engine run to the identity it attests
**Files modified:** `src/backtest/experiment.py`, `tests/backtest_case_helpers.py`, `tests/test_backtest_experiment.py`
**Commit:** 1c15d56
**Applied fix:** `assemble` takes a new required keyword `run_identity` (the engine output, which already carries `strategy_version`, `parameter_set_hash`, `cost_model_hash` and `symbols`). New `_check_run_identity` raises `IncompleteExperimentRecord` unless the registry set's `strategy_version` equals the caller's, and the run's strategy version, parameter-set hash, cost-model hash and sorted symbols equal the record's. The test helper `assemble_kwargs` derives a consistent identity by default; `_simple_trend_record` passes the real engine output. New tests cover each mismatch, including the bogus-version case from the review.
**Note:** this changes the public signature of `assemble` (all callers in the repo were updated; there are no production callers yet).

### WR-01: Trade-record validator misses most cross-field invariants
**Files modified:** `src/backtest/validator.py`, `src/backtest/records.py`, `src/backtest/engine.py`, `src/backtest/experiment.py`, `tests/test_trade_record_validator.py`, `tests/test_backtest_engine.py`
**Commit:** dade3bf
**Applied fix:** `validate_trade_record` gains `strict: bool = False`. Strict mode checks: filled kind <=> entry fill; `PARTIAL_FILL` exactly when `quantity < planned_quantity`; entry price present; an `OK` filled record has exit kind/price/time, realized PnL and realized risk; an unfilled record has every fill-derived field `None`. Strict is used where the engine builds or reloads its own records (record builders, `engine._close`, `_trade_from_dict`).
**Deviation from the review (human attention advised):** strict mode is opt-in rather than always on, because the analytics boundary (`analytics/inputs.py`, phase 10 fixtures and about a dozen analytics tests) intentionally accepts filled records with a missing exit time or missing risk and reports them as incomplete outcomes. Making the checks unconditional breaks that documented behaviour. Records reaching `report.build` or the evidence loader from the engine path are now fully validated; the analytics normalizer remains lenient.
**Status:** fixed: requires human verification (logic change).

### WR-02: Evidence loader accepts trades that do not belong to the experiment
**Files modified:** `src/adapters/analytics_files.py`, `src/backtest/experiment.py`, `tests/test_analytics_files.py`
**Commit:** effd3fa
**Applied fix:** `_load_backtest_entry` now calls `_check_trades_belong_to_experiment`: trade strategy version and parameter-set hash must match, signal/entry/exit times must lie inside the experiment time range, the `fallback_applied` and `END_OF_DATA` counts must equal the typed counts, and a stored `trades_digest` (when present) must equal the digest of the trades in engine order. `load_evidence_file` also requires every trade symbol to be in `research_universe`. Added public `trades_digest` and `stored_trades_digest` helpers to `experiment.py`; `verify_experiment` uses `trades_digest`. Parametrized refusal tests added; one existing test was updated to keep its record consistent with the sample trades.
**Status:** fixed: requires human verification (logic change).

### WR-03: Reproducibility checks can pass vacuously
**Files modified:** `src/backtest/experiment.py`, `tests/test_backtest_experiment.py`, `tests/backtest_case_helpers.py`
**Commit:** 3377bd0
**Applied fix:** `reproduce` (and so `verify_experiment`) raises `ExperimentReproducibilityBroken` for empty inputs. `_check_inputs_bind_record` reports missing `strategy_id` / `parameter_set_id` / `cost_model` / `symbols` as `ExperimentReproducibilityBroken` instead of `KeyError`, and checks `symbols` against `universe_hash`. `assemble` and `_check_run_binds_record` now require a non-null `dataset_id` equal to `data_snapshot_id`. Tests that relied on the empty-input shortcut now reproduce a real simple-trend run (the test case input carries a dataset id); new tests cover the refusals.
**Status:** fixed: requires human verification (logic change).

### WR-04: Mark-hole fallback prices stops optimistically and never flags gaps
**Files modified:** `src/backtest/exits.py`, `tests/test_backtest_exits.py`
**Commit:** b658e35
**Applied fix:** In `resolve_fallback_hour`, a stop touched in the fallback bar books the adverse of trigger and bar open (and sets `gap_through_stop`) when the position was already open at the bar open (`entry_time < bar.open_time_utc`); a fill inside the bar still books the trigger. Test covers a gap-down and a non-gap bar.
**Status:** fixed: requires human verification (logic change).

### WR-05: Acknowledged allowed gaps of non-funding series leave no trace
**Files modified:** `src/backtest/engine.py`, `src/backtest/experiment.py`, `tests/test_backtest_run_summary.py`, `tests/test_backtest_experiment.py`
**Commit:** 6661928
**Applied fix:** The engine's `allowed_gaps_used` now lists used funding gaps plus every acknowledged non-funding gap of the case. `RecordedGap` accepts any non-empty series name, allows `end_utc == start_utc` (a single missing bar), and sorts by `(symbol, start, end, series)`.
**Note:** the field keeps its name; it now means "gaps the run carried" (documented on `RecordedGap`). No fixture changed because existing goldens have only funding gaps.

### WR-06: Drawdown, bootstrap and stability use signal-close order
**Files modified:** `src/backtest/report.py`, `tests/test_backtest_report.py`
**Commit:** bc2f86e
**Applied fix:** `report.build` sorts closed trades by `(exit_time_utc, trade_id)` before computing R values. Test shows a drawdown of 6 in exit order versus 3 in signal order.

### WR-07: Funding rows and minute rows accept non-finite values
**Files modified:** `src/backtest/funding.py`, `src/backtest/series.py`, `tests/test_backtest_funding.py`, `tests/test_backtest_series.py`
**Commit:** fa95793
**Applied fix:** `_parse_decimal` (funding) and `_parse_money` (series) reject NaN/Infinity (`ValueError` / `MinuteSeriesError`); `parse_funding_row` also requires `mark_price > 0` when present.

### WR-08: `weak_live_universe_rejection` false when live-5 has no trades
**Files modified:** `src/backtest/report.py`, `tests/test_backtest_report.py`
**Commit:** eca9862
**Applied fix:** the flag is now true when the research mean R is positive and the live-5 slice has no mean (no R-valued trades) or a non-positive mean.
**Status:** fixed: requires human verification (logic change).

### WR-09: Mark holes outside the closing-bar window and on the fill minute are ignored
**Files modified:** `src/backtest/lifecycle.py`, `tests/test_backtest_exits.py`
**Commit:** 81dac4e
**Applied fix:** the hole scan (`_first_missing_mark_open`) now reads the whole bar's mark minutes (not only the advanced window) and starts at the later of the bar open and the fill minute itself, so a hole in an earlier mid-bar window of the closing bar, or on the fill minute, triggers the bar-close fallback and the `fallback_applied` flag. Two regression tests were confirmed to fail without the change.
**Remaining gap (human attention advised):** a window that ends at a close where this symbol has no strategy bar (an allowed gap in the bar series) still passes `bar=None`; holes in those hours are not scanned and no coverage note is recorded, because the plan state does not track "scanned up to". Closing that needs a new state field and a scan-from marker; it was left out of this fix to avoid a broader lifecycle change.
**Status:** fixed: requires human verification (partial coverage as described).

### WR-10: `dataset_id` need not cover the 1m files the engine reads
**Files modified:** `src/data/case_input.py`, `tests/test_case_input_builder.py`
**Commit:** 4c3ab4e
**Applied fix:** `CaseInputData.to_case_input` (the producer of engine cases) raises `CaseInputError` unless the data was built with all of `ENGINE_SERIES` (`trade`, `intrabar_1m`, `mark_1m`, `funding`). The funding-only builder path remains available for non-engine use; the one test that exported a case from funding-only data now asserts the refusal and exercises the export shape on a copy with the full series.

### WR-11: Phase 6 fixture generator output is platform-dependent
**Files modified:** `scripts/gen_phase6_fixtures.py`, ten regenerated fixture files (`tests/fixtures/phase6/**/input.json` x9, `tests/fixtures/phase7/parity_overlapping_history/input.json`)
**Commit:** 461477b
**Applied fix:** `_write` now writes LF bytes with a trailing newline. The generator was re-run once; the only diff in every fixture is the added trailing newline. `tests/test_phase6_fixture_geometry.py` (generator bytes versus committed bytes) and the backtest suites pass afterwards.

## Skipped Issues

None.

---

_Fixed: 2026-10-05_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
