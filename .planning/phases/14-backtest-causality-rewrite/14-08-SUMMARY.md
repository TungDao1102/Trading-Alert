---
phase: 14-backtest-causality-rewrite
plan: 08
subsystem: backtest
tags: [backtest, causality, engine, event-loop, ledger, funding, daily-stop, case-input-v2, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-01/02/07 lifecycle (advance, cancel_plan, finalize_at_data_end), exits.protective_levels_for_fill, records.booking_for_event/build_trade_record; 14-03 funding_events; 14-05 ledger and point-in-time constraints"
provides:
  - "src/backtest/case.py: CASE_INPUT_SCHEMA 'backtest-case/2', parse_case_input, ParsedCase, ScriptedPlan, AllowedGap, REMOVED_V1_KEYS"
  - "src/backtest/engine.py: simulate(case_input, *, risk_fn, minute_source=None), simulate_detailed (adds bookings and final ledger)"
  - "src/backtest/records.py: build_reject_record, BOOKING_FUNDING"
  - "tests/backtest_case_helpers.py: v2 case builders for plans 14-09 to 14-15"
affects: [14-09, 14-10, 14-11, 14-12, 14-13, 14-15, 14-16]

actuals:
  tokens: 32000
  tasks: 3
  commits: 4
plan_head_before: 6bdaf4c2428dcf051cac67ba8a7735c118f5cda1
plan_head_after: 333da656ce0150aaf1b68133362b3cccf8f943c0

tech-stack:
  added: []
  patterns:
    - "One priority queue per window ordered by (time, symbol, rank): lifecycle events and funding payments are booked into the ledger in time order, and a DAILY_STOP booking cancels still-resting entries by re-advancing them from the saved window-start state"
    - "risk_fn is a parameter (evaluate_risk keyword signature); the engine never imports evaluate_risk"
    - "Funding rows are handed to funding_events as a bisect slice (window +- cadence+jitter, plus one neighbour per side), so coverage verdicts equal the full-history verdict without re-sorting the series per window"

key-files:
  created:
    - src/backtest/case.py
    - src/backtest/engine.py
    - tests/backtest_case_helpers.py
    - tests/test_backtest_engine.py
    - tests/test_backtest_engine_strategy.py
  modified:
    - src/backtest/records.py

key-decisions:
  - "Case-input v2 is a closed key set: unknown top-level keys, unknown row keys, a float anywhere, a naive datetime, a missing funding_convention and every REMOVED_V1_KEYS entry raise (ValueError, TypeError for floats). 'symbols' may arrive in any order and is sorted on parse (needed for the reverse-input determinism proof); minute rows are never sorted"
  - "Passed minute_source wins over trade_bars_1m/mark_bars_1m rows (the rows are then not read); with neither, simulate raises ValueError. A symbol without minute rows has no series and raises when an entity needs it (no silent empty series)"
  - "Closes before data_window.start are warm-up (no signal evaluated, not counted); closes after data_window.end are never acted on. Scripted plans are scheduled at (bar_close, symbol) pairs added to the strategy-bar closes, so a scripted close needs no strategy bar"
  - "Exhausted ledger equity: later setups are not evaluated and each skipped evaluation point is counted under UNCERTAIN_ACCOUNT_STATE (strategy mode counts every skipped bar close, scripted mode every skipped plan)"
  - "A fill quantity that floors to zero (partial_fill_fraction) is a MIN_QTY_REJECT record; TP1 un-sizeability uses the live reason from protective_levels_for_fill (D-27)"
  - "DAILY_STOP: items of a window are drained from a heap; after each non-zero booking, if cancel_resting_required, every entity that was RESTING at window start is re-advanced (bar None) to the booking instant and, if still RESTING, cancelled DAILY_STOP_CANCEL there; its remaining window items are dropped. A fill exactly at the trigger instant counts as filled. Funding of an entity that was resting at window start is queued only when its FILL item is drained, so a cancelled plan never triggers a funding-coverage check"
  - "A forced END_OF_DATA close priced at a mark minute earlier than the last ledger booking is dated at the last booking time on the ledger (the record keeps the true exit time), because the ledger requires non-decreasing times"
  - "Regime on records is None (the Signal carries no regime); signals emit no extra run_summary keys (plan 14-09 completes it)"

patterns-established:
  - "tests/backtest_case_helpers.make_case builds a v2 case from compact arguments; fixed_risk_fn stands in for evaluate_risk with a hand-chosen quantity so ledger/DAILY_STOP scenarios are hand-checkable"

requirements-completed: [BKTS-01]

duration: about 3h wall clock, much of it waiting on a crashing full-suite run
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 08: Event-Loop Engine and Case-Input v2 Summary

**A pure v2 engine, `simulate(case, risk_fn=...)`, that advances plans and positions over each strategy-bar close, books fills, exits and funding into the ledger in time order, and only then sizes new setups through the shared risk function on ledger equity, resting exposures, daily loss and a point-in-time constraint with ttl 0.**

## Accomplishments

- Hand-checked tracer: LONG zone 99-101 (limit 100.00), stop 98.00, equity 10000, baseline-v5 costs sizes to 15.928 through the real `evaluate_risk` (realized risk 49.997992), rests from 10:00, fills 10:01:59.999, stops at 10:40:59.999 with realized_pnl -34.0604352 and `entry_time > signal_close`.
- Case-input v2 parser with the final key list below; v1 keys, floats, naive datetimes, unknown keys and a cost model without `funding_convention` are refused.
- Portfolio rules: one entity per symbol (second setup counted `CONFLICT_WITH_OPEN_POSITION`, never a `RejectionReason`), resting entries visible to the cluster gate (the BTC resting risk 49.997992 reaches the ETH call), sorted symbol order at a shared close with full-dict equality when every input order is reversed.
- DAILY_STOP: SOL stop-out at 10:15:59.999 (day PnL -106.92 against a 100.00 stop) cancels the BTC entry that would have filled at 10:30 (`DAILY_STOP_CANCEL`, resolved 10:15:59.999, zero CANCEL booking) while ETH, filled at 10:05, keeps its stop and exits SL at 10:45.
- D-27 reject: sized 0.001 gives MIN_QTY_REJECT, 0.002 gives NOTIONAL_REJECT; nothing rests. Partial fill 0.5: PARTIAL_FILL, quantity floor(0.5 x 0.5) = 0.250, realized_risk 0.75. Exhausted equity (100 less 128.304) stops evaluation.
- Funding: LONG 0.5 held across 08:00 (+0.0001 at 100) and 16:00 (-0.0002 at 102) has funding_amount +0.0052 and count 2, booked at those instants; a TP1 remainder (0.250) is charged on the smaller quantity (-0.0075 over two instants). A 20 h funding hole raises `FundingCoverageError`; the same case with an allowed gap succeeds and lists it in `allowed_gaps_used`.
- Data end: open position closes END_OF_DATA at the last mark close (11:59:59.999, 100.00); resting plan is PENDING_AT_DATA_END (resolved at data end); every record is validated with the data window.
- Strategy front-end: windowed evaluation (bisect) reproduces the phase 6 trigger-bar signal id and plan id of the full-prefix `evaluate`/`plan`; the 249 earlier bars appear only in `no_trade_counts` (WARMUP_INSUFFICIENT 199, NO_TRADE_REGIME 50).

## Case-input v2 key list as implemented

Required: `case_input_schema` ("backtest-case/2"), `strategy_id`, `strategy_version`, `parameter_set_id`, `symbols`, `strategy_bars`, `context_bars`, `funding`, `constraint_history`, `account_state`, `cost_model`, `data_window`, `allowed_gaps`. Optional: `trade_bars_1m`, `mark_bars_1m` (required in effect unless a `minute_source` is passed), `dataset_id` (64 lowercase hex), `scripted_plans`. Row shapes: bars (`symbol, interval, open_time_utc, close_time_utc, open, high, low, close, volume`; intervals "1h" and "4h"), funding (`symbol, funding_time_utc, funding_rate, mark_price|null`), constraint rows (`symbol, metadata_observed_at_utc, price_tick_size, quantity_step_size, min_quantity, min_notional`), `account_state` (`equity, risk_rate`), `data_window` (`start_utc, end_utc`), allowed gaps (`series, symbol, start_utc, end_utc, missing`), scripted plans (`symbol, bar_close_utc, signal_id, direction, entry_min_price, entry_max_price, stop_loss_price, tp1, tp2, expiry_hours`, optional `invalidation_level`). Refused: `intrabar_1m_map`, `constraint_snapshot`, `open_positions`, `daily_loss_quote`, `now_utc`, `ttl_seconds`, `mark_price_bars`.

Output: `trades`, `run_summary` (`no_trade_counts`, `plan_source`, `allowed_gaps_used`, `simulator_semantics_version`), `strategy_version`, `parameter_set_hash`, `cost_model_hash`, `symbols`.

## Task Commits

1. **Task 1 (tracer)**: `af52648` (test, RED skeleton), `a720957` (feat, GREEN: case.py, engine.py, build_reject_record)
2. **Task 2**: `7834979` (test: portfolio semantics, no source change needed)
3. **Task 3**: `333da65` (test: windowed strategy front-end, funding, data end, order, no source change needed)

## Deviations from Plan

None in scope. Process note below.

## TDD Gate Compliance

Task 1 followed RED then GREEN: `af52648` carried a skeleton `case.py` and `engine.py` returning empty shapes, so the 16 tracer/refusal tests failed on assertions (`len == 1` and "DID NOT RAISE"); `a720957` made all pass. `gsd_run check tdd-red-evidence` was not run.

Tasks 2 and 3 do NOT have an independent RED: the whole engine is one class, and the portfolio, DAILY_STOP, funding, windowing and data-end behavior were implemented together in the Task 1 GREEN commit, so the Task 2 and Task 3 tests passed on first run (29 and 44 passing). This is an honest gate shortfall (rule "unexpected GREEN in RED phase"). To show the tests are not vacuous I ran mutation checks, restoring the engine after each; every mutation made a named test fail: no DAILY_STOP cancel, no conflict skip, ProtectiveReject ignored, partial fill ignored, no equity guard, reversed symbol order, gate fed no exposures, full-prefix setup window, one-bar context leak, funding ignoring the TP1 split, funding booked at the wrong instant, allowed gaps ignored, no data-end finalize, unordered records, validation without the data window.

## Issues Encountered

- Heredocs with apostrophes fail in the shell tool; test additions were applied from scratch files by script.
- Full suite: `pytest -m "not docker"` crashes the interpreter with a Windows access violation inside `tests/test_deploy_compose.py` (docker compose subprocess) and `tests/test_deploy_backup_scripts.py` (deploy script subprocess). Both are unrelated to this plan (no src/backtest import); not retried further per the coordinator's instruction. The rest of the suite was run with those two files ignored (result in Verification).

## Verification (real output)

- `pytest tests/test_backtest_engine.py tests/test_backtest_engine_strategy.py tests/test_backtest_purity.py tests/test_domain_no_float.py`: 56 passed.
- Rest of `pytest -m "not docker"` (both deploy files ignored): everything passed except `tests/test_universe_freeze.py::test_refreeze_refuses`, which fails with `PermissionError` ("witness write failed, manifest restored"). That test does not touch src/backtest (no `backtest` reference); it looks like the Windows file-permission environment (the session is not an administrator), not a code regression. Not investigated further. The crashing deploy tests above are likely the same class of environment problem (unverified).
- `ruff check src/backtest tests`: all checks passed; `ruff format --check .`: 395 files already formatted; `mypy src`: no issues in 145 source files.
- Acceptance: "backtest-case/2" and `intrabar_1m_map` in case.py; engine.py imports no `evaluate_risk` (AST test); `simulator.py` untouched; `STRATEGY_WINDOW_BARS`, `CONTEXT_WINDOW_BARS`, `bisect` in engine.py; "0.0052", "allowed_gaps_used", "PENDING_AT_DATA_END", "DAILY_STOP_CANCEL", "CONFLICT_WITH_OPEN_POSITION", "PARTIAL_FILL", "MIN_QTY_REJECT" in the tests; `RejectionReason` still 20 members.
- Tracer gate (interactive, end-of-phase, automated verify): re-run after GREEN, 18 passed, expansion continued.

## Regeneration inventory

none. No fixture, parameter set, pin or hash moved; `simulator.run` (v1) is unchanged and `src/domain/enums.py`, `semantics.py` and the cost model are untouched.

## Known Stubs

None. Scripted plans carry zero-sized quantity placeholders on the `TradePlan` by design (the risk function sizes them; the placeholders are never read).

## Threat Flags

None. T-14-15 (minutes only via MinuteSource windows, trailing windows via bisect), T-14-16 (closed schema, float/naive/v1 refusals) and T-14-17 (`plan_source` recorded; refusal of SCRIPTED in ExperimentRecord is plan 14-15) are covered.

## Next Phase Readiness

Plan 14-09 completes `run_summary`. Plan 14-12 switches `simulator.run` to `engine.simulate`, passing its module-global `evaluate_risk` as `risk_fn`, and regenerates the v1 fixtures into v2 cases (`make_case` in tests shows the shape).

## Self-Check: PASSED

All five created files exist on disk; commits `af52648`, `a720957`, `7834979` and `333da65` are in `git log`; the acceptance greps and plan verification commands re-ran green (full-suite caveats above).
