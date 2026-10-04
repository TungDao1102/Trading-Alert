---
phase: 14-backtest-causality-rewrite
plan: 01
subsystem: backtest
tags: [backtest, causality, lifecycle, trade-through, mark-price-stop, validator, tdd, decimal]

requires:
  - phase: 12-fee-cost-model-correctness
    provides: CostModel with exit_slippage_rate, per-leg fee and slippage booking
  - phase: 13-research-data-foundation-fixes
    provides: mark-kline and 1m trade row shapes (mark rows have no volume)
provides:
  - "src/backtest/semantics.py: SIMULATOR_SEMANTICS_VERSION 2.0.0, TP1_QUANTITY_FRACTION Decimal('0.5') (D-27), POSITION_MODE, TIE_BREAK, funding/window constants, entry and exit kind vocabularies"
  - "src/backtest/series.py: MinuteSource protocol, ListMinuteSource, validate_minute_series, parse_minute_row, MinuteSeriesError"
  - "src/backtest/entry.py and exits.py: live-snapped limit and SL trigger, one-tick trade-through, mark-price stop touch"
  - "src/backtest/lifecycle.py: PlanState, LifecycleEvent, new_plan_state and the pure window-parameterized advance()"
  - "src/backtest/records.py: TradeRecord v2 (moved, trailing fields), Booking, booking_for_event, build_trade_record"
  - "src/backtest/validator.py: validate_trade_record and TradeRecordInvariantError (D-23)"
  - "src/risk/realized_risk.py: realized_risk_for_fill, the single R-denominator function (D-20)"
  - "tests/backtest_plan_helpers.py: make_trade_plan, make_minute, make_record shared by every later Phase 14 plan"
affects: [14-02, 14-03, 14-04, 14-05, 14-06, 14-07, 14-08, 14-09, 14-10, 14-11, 14-12, 14-13, 14-15, 14-16]

actuals:
  tokens: 25000
  tasks: 3
  commits: 7
plan_head_before: 630a8fd51ded10747a5b9b7b688b9c9c22475ac2
plan_head_after: cd86e975f4c0f3f770c7448d89c7f286f0ca3af5

tech-stack:
  added: []
  patterns:
    - "Pure window-parameterized lifecycle driver: advance(state, source, start_exclusive, end_inclusive, bar) -> (state, events), no clock, no I/O, no float"
    - "Lazy MinuteSource protocol selecting minutes by close time in (start_exclusive, end_inclusive]; holes stay absent"
    - "Record builder and ledger booking sum the same per-leg numbers so they cannot disagree"
    - "Purity guard by src/backtest/*.py glob (reusing the analytics AST walker) plus a glob scan in the no-float guard"

key-files:
  created:
    - src/backtest/semantics.py
    - src/backtest/series.py
    - src/backtest/entry.py
    - src/backtest/exits.py
    - src/backtest/lifecycle.py
    - src/backtest/records.py
    - src/backtest/validator.py
    - src/risk/realized_risk.py
    - tests/backtest_plan_helpers.py
    - tests/test_backtest_lifecycle.py
    - tests/test_trade_record_validator.py
    - tests/test_backtest_series.py
    - tests/test_realized_risk.py
    - tests/test_backtest_purity.py
  modified:
    - src/backtest/simulator.py
    - tests/test_domain_no_float.py

key-decisions:
  - "D-27 is a code constant: TP1_QUANTITY_FRACTION = Decimal('0.5') in semantics.py, covered by SIMULATOR_SEMANTICS_VERSION 2.0.0; not a registry tunable, no params/ change"
  - "validate_trade_record also requires planned_quantity on a filled record (fail closed: filled <= planned cannot be checked without it)"
  - "ListMinuteSource raises MinuteSeriesError for a symbol with no series instead of returning an empty window, so a missing symbol never reads as 'no price moves'"
  - "Overlap is checked before alignment in validate_minute_series so an off-grid minute after a valid one is reported as an overlap"
  - "advance() resolves the fill-minute stop by matching the mark minute on open time; a missing fill-minute mark minute checks nothing (fallback is plan 14-07)"
  - "The tracer lifecycle deliberately has no expiry, invalidation, TP ladder or END_OF_DATA yet (plans 14-02 and 14-07); the bar argument is reserved"

patterns-established:
  - "Shared test helpers in tests/backtest_plan_helpers.py (strings only, never floats)"
  - "Hand-derived oracle numbers written in test docstrings, not read from the code under test"

requirements-completed: [BKTS-01]

duration: 20min
completed: 2026-10-04
status: complete
---

# Phase 14 Plan 01: Causal Tracer Slice Summary

**A hand-built LONG plan now rests from bar N+1, fills only on a one-tick trade-through of the tick-snapped limit on a trade-price 1m minute, stops out on a mark-price minute, and becomes a validated v2 TradeRecord whose R comes from one shared function.**

## Performance

- **Duration:** 20 min of recorded execution (clock started after the initial read of the plan and context, about 8 min earlier)
- **Started:** 2026-10-04T13:19:39Z
- **Completed:** 2026-10-04T13:39:40Z
- **Tasks:** 3 (1 tracer, 2 auto, all tdd)
- **Files modified:** 16 (14 created, 2 modified)

## Accomplishments

- Tracer verified end to end on the hand oracle (LONG, zone 99-101, tick 0.10, limit 100.00, stop 98.00, qty 0.5): the 10:00 minute only touches (touch counter 1), the 10:01 minute fills at 100.00 with entry time 10:01:59.999, the 10:01 mark minute triggers the stop on the fill minute (exit 98.00 at 10:01:59.999). gross_pnl -1.00, realized_pnl -1.0741 (entry fee 0.0200, exit fee 0.0196, slippage 0.0345, hand-derived in the test docstring), realized_risk 1.50.
- Signal-bar minutes (low 90, far below limit and stop) provably never change the result; a start before the signal close is clamped to it (T-14-01).
- Contracts of the Interfaces section exist with the stated names: semantics constants (including the user-resolved TP1 fraction 0.5), `MinuteSource`/`ListMinuteSource`, `snapped_limit_price`/`is_trade_through`, `ProtectiveLevels`/`sl_trigger_price`/`is_sl_touched`, `PlanState`/`LifecycleEvent`/`new_plan_state`/`advance`, `TradeRecord` with the 11 v2 trailing fields, `Booking`/`booking_for_event`/`build_trade_record`, `validate_trade_record`, `realized_risk_for_fill`.
- Shared validator raises `TradeRecordInvariantError` (never warns) for: entry_time <= signal_close, missing signal close, exit < entry, exit outside the data window, filled quantity > planned or <= 0, TP1 leg outside the holding window or >= total quantity, unknown entry/exit kinds, exit fields on a never-filled record. `build_trade_record` validates before returning (T-14-03).
- Minute series validated on load (duplicate, decreasing, overlap, off-grid open, close outside the minute, symbol/interval mismatch); holes stay absent; rows reject floats and naive datetimes.
- `src/backtest/*.py` is purity-guarded by glob (no Polars, no `src.data`, no wall clock, no float) and float-scanned by glob, closing the registration trap for modules later plans add (T-14-02).

## Task Commits

1. **Task 1: Tracer** - `20112f1` (test, RED), `bf1b5ff` (feat, GREEN)
2. **Task 2: Validator contract + shared helpers** - `202a367` (test, RED), `62ae4cd` (feat, GREEN), `cd86e97` (style, ruff format of the new test)
3. **Task 3: Series validation, R pins, purity guards** - `170fe20` (test, RED), `a542ce9` (feat, GREEN)

**Plan metadata:** committed separately after this file (docs: complete plan).

## Files Created/Modified

- `src/backtest/semantics.py` - phase constants, kind vocabularies, D-27 TP1 fraction
- `src/backtest/series.py` - MinuteSource protocol, in-memory source, series and row validation
- `src/backtest/entry.py` - live-snapped limit, trade-through and touch-only rules
- `src/backtest/exits.py` - ProtectiveLevels, live-snapped SL trigger, mark-price stop touch
- `src/backtest/lifecycle.py` - PlanState, LifecycleEvent, new_plan_state, advance
- `src/backtest/records.py` - TradeRecord (moved, v2 fields), Booking, booking_for_event, build_trade_record
- `src/backtest/validator.py` - validate_trade_record, TradeRecordInvariantError
- `src/risk/realized_risk.py` - realized_risk_for_fill
- `src/backtest/simulator.py` - TradeRecord class replaced by `from .records import TradeRecord` (v1 logic untouched)
- `tests/backtest_plan_helpers.py` - make_trade_plan, make_minute, make_record
- `tests/test_backtest_lifecycle.py`, `test_trade_record_validator.py`, `test_backtest_series.py`, `test_realized_risk.py`, `test_backtest_purity.py` - contract tests
- `tests/test_domain_no_float.py` - realized_risk.py in the explicit list, src/backtest glob scan

## Decisions Made

See `key-decisions` in the frontmatter. Notable beyond the plan text: planned_quantity is required on a filled record; ListMinuteSource refuses an unknown symbol; the tracer lifecycle intentionally stops at the stop exit.

## Deviations from Plan

### Auto-fixed Issues

None needed for correctness. Two small choices go beyond the literal plan text and are recorded here for 14-02 and later:

**1. [Rule 2 - Missing critical] Required `planned_quantity` on filled records in the validator**
- **Found during:** Task 2
- **Issue:** the plan checks "filled quantity > planned" but a v2 filled record without a planned quantity cannot be checked; failing open would let a record skip D-23
- **Fix:** `validate_trade_record` raises when `planned_quantity` is None on a filled record; covered by `test_filled_record_without_planned_quantity_raises`
- **Files modified:** src/backtest/validator.py, tests/test_trade_record_validator.py
- **Committed in:** 202a367 (test), 62ae4cd (feat)

**2. [Rule 2 - Missing critical] Unknown symbol raises in ListMinuteSource**
- **Found during:** Task 1
- **Issue:** returning an empty window for a symbol with no series would read as "no price moves" and let a resting plan sit forever on missing data
- **Fix:** `trade_minutes`/`mark_minutes` raise `MinuteSeriesError`; covered by `test_unknown_symbol_is_a_data_error_not_an_empty_window`
- **Files modified:** src/backtest/series.py, tests/test_backtest_series.py
- **Committed in:** bf1b5ff / a542ce9

---

**Total deviations:** 2 additive fail-closed guards (Rule 2). **Impact on plan:** none on the Interfaces contract; later plans must supply `planned_quantity` on filled records (build_trade_record always does) and a series for every symbol.

## TDD Gate Compliance

All three tasks have a `test(14-01)` RED commit before the `feat(14-01)` GREEN commit (git log check above matches `^test\(14-01\)` x3 and `^feat\(14-01\)` x3, no refactor commit).

RED evidence, stated honestly:
- Task 1 RED failed with `ModuleNotFoundError` on `src.backtest.lifecycle` at collection. The plan explicitly sanctions "fails on the missing modules", but the stricter #3770 rule would classify a collection error as INVALID_RED. `gsd_run check tdd-red-evidence` was not run for any task.
- Task 2 RED: 9 of 15 validator cases failed with `DID NOT RAISE` assertions against the tracer-minimal validator (valid RED); the other 6 pinned behavior the minimal validator already had.
- Task 3 RED: 9 of 14 series cases failed on assertions (message and type mismatches against the minimal series validation); the realized-risk, purity and no-float tests pass on arrival by design (they pin code shipped in Task 1 or guard existing files).

## Issues Encountered

- `ruff format` rewrote a line in the validator test after the style pass was skipped once; fixed in `cd86e97`.
- The first `ruff check --fix` on the lifecycle test reordered imports; no behavior impact.

## Verification (real output)

- Plan verification pytest (lifecycle, validator, series, realized_risk, purity, no_float, simulator): `114 passed in 81.15s`.
- `ruff check`: all checks passed; `ruff format --check`: 379 files already formatted; `mypy src`: no issues found in 140 source files.
- Full suite excluding the docker marker and the simulator module (already counted above): `3331 passed, 423 skipped, 17 deselected in 469.88s` (skips are the pre-existing PostgreSQL/Docker-dependent tests).
- Acceptance greps: semantics constants, `from .records import` in simulator.py, no TradeRecord class in simulator.py, entry.py imports `src.execution.placement`, signal test present, `TradeRecord is records.TradeRecord`, no file under `params/` touched, validator has no `warnings`/`logging` import, validator tests 15 passed (>= 9), series tests 14 passed (>= 8), purity/no-float strings present.

## Regeneration inventory

none. No fixture, parameter set, pin or hash moved. `TradeRecord.to_dict()` now also emits the 11 trailing v2 keys (all default values on v1 records), but no existing test pins a digest over that output and the full suite is green. Follow-ups already owned by later plans: add the new fields to `experiment._DECIMAL_TRADE_FIELDS`/`_DATETIME_TRADE_FIELDS`, `src/adapters/analytics_files.py`, the `EVIDENCE_SCHEMA` bump and `tests/phase10_helpers.py` defaults (plans 14-11/14-12/14-15 per PATTERNS).

## Known Stubs

None that block the goal. Intentionally minimal pieces, each resolved by a named later plan: `ProtectiveLevels` TP fields stay `None` and the lifecycle has no TP ladder, stop gap, fallback or END_OF_DATA (14-07); no expiry, invalidation or cancel (14-02); `advance(..., bar=...)` ignores `bar` (14-02); `booking_for_event` raises for TP1/CANCEL/PENDING events (14-07); `modeled_costs_per_unit` is `None` on built records (engine, 14-08).

## Threat Flags

None. No new network endpoint, auth path, file access or schema change; the threat register items T-14-01 (signal-bar minutes clamped and test-proven), T-14-02 (purity and no-float globs) and T-14-03 (validator raises, builder validates) are mitigated.

## Next Phase Readiness

Ready for 14-02 (expiry, invalidation, touch counting, cancel API, PENDING_AT_DATA_END) and 14-03 (funding), which are independent of each other. No blockers.

## Self-Check: PASSED

All created files exist on disk, all seven task commits are present in `git log`, and every acceptance criterion and plan-level verification command re-ran green (see Verification).

---
*Phase: 14-backtest-causality-rewrite*
*Completed: 2026-10-04*
