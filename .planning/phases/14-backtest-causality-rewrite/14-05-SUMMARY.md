---
phase: 14-backtest-causality-rewrite
plan: 05
subsystem: backtest
tags: [backtest, ledger, daily-stop, point-in-time, constraints, causality, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "Booking and booking_for_event (14-01 records.py), tests/backtest_plan_helpers.py, src/backtest purity and no-float globs"
  - phase: 05-risk-pipeline
    provides: "resolve_absolute_thresholds, derive_daily_state, check_portfolio, evaluate_risk, OpenPosition, ConstraintSnapshot (consumed unchanged)"
provides:
  - "src/backtest/ledger.py: frozen Ledger, Exposure, apply_booking, roll_to, daily_loss_quote, daily_state, cancel_resting_required, register/update/remove_exposure, open_positions_for_risk, equity_positive"
  - "src/backtest/constraints.py: ConstraintRow, parse_constraint_row, ConstraintHistory, select_constraints returning PitConstraint(snapshot, observed_at_utc, extrapolated), ConstraintHistoryError"
affects: [14-08, 14-09, 14-10, 14-11, 14-12, 14-13, 14-15, 14-16]

actuals:
  tokens: 11850
  tasks: 3
  commits: 6
plan_head_before: 2d8fbb141d837bb4194f4bcbbd50915c3a6decc5
plan_head_after: cadcece22a6270533d8ee53780c274898e4f4005

tech-stack:
  added: []
  patterns:
    - "Event-sourced ledger: every function takes a frozen Ledger and returns a new one; only dated Bookings move equity"
    - "Risk state is derived, never copied: derive_daily_state and resolve_absolute_thresholds from src/risk, zero change under src/risk"
    - "Wall-clock-free freshness: snapshot metadata_observed_at_utc clamped to the bar close, evaluated at ttl timedelta(0), true observed_at returned apart"
    - "RED skeleton: a behavior-less module committed with the RED tests so the failures are assertions, not ImportError"

key-files:
  created:
    - src/backtest/ledger.py
    - src/backtest/constraints.py
    - tests/test_backtest_ledger.py
    - tests/test_backtest_pit_constraints.py
  modified: []

key-decisions:
  - "Exhausted equity (<= 0) at a day roll resolves the four rate thresholds to 0 instead of raising, so daily_state is DAILY_STOP and every cap rejects (fail closed); equity_positive lets the engine stop before AccountState would raise"
  - "Ledger.start refuses non-positive equity (ValueError), mirroring AccountState and resolve_absolute_thresholds"
  - "Exposures are an immutable tuple sorted by trade_plan_id; update_exposure always scales from the registered initial_risk (initial x remaining / filled), so repeated updates cannot compound rounding"
  - "open_positions_for_risk breaks (symbol, side) ties by trade_plan_id so the projection is byte-stable"
  - "parse_constraint_row accepts Decimal or decimal strings and aware-UTC datetimes or ISO strings only; float, int, bool, naive or non-UTC timestamps, NaN and non-positive values are refused"
  - "A booking dated before the current UTC day, or before the previous booking, raises ValueError; roll_to inside the current day is a no-op and an earlier day raises"

patterns-established:
  - "Hand-derived oracle numbers in test docstrings: equity 9899.50, day loss 100.50, day-2 thresholds 98.80 and 49.40"
  - "Module-attribute calls (ledger_mod.roll_to) in RED tests so one missing function fails one test, not collection"

requirements-completed: [BKTS-01]

duration: 25min
completed: 2026-10-04
status: complete
---

# Phase 14 Plan 05: Simulated Ledger and Point-in-Time Constraints Summary

**A pure event-sourced ledger (realized-only equity, UTC-day loss through the unchanged `derive_daily_state`, resting and post-TP1 exposure projection, DAILY_STOP cancellation signal) plus bisect-based point-in-time constraint selection that back-extrapolates with a flag and clamps the snapshot so the live freshness gate passes at ttl 0 with no wall clock.**

## Performance

- **Duration:** about 25 min (clock not recorded at start; estimated from commit timestamps and the initial reading)
- **Completed:** 2026-10-04
- **Tasks:** 3 (1 tracer, 2 auto, all tdd)
- **Files:** 4 created, 0 modified (nothing under `src/risk`)

## Accomplishments

- Tracer verified end to end on hand arithmetic (initial equity 10000, baseline-v5 rates): bookings -2.50 at 10:01:59.999 and -98.00 at 10:40:59.999 give equity 9899.50, `daily_loss_quote` 100.50 >= 100, state DAILY_STOP, `cancel_resting_required` True; the real `evaluate_risk` then returns `is_no_trade` with `DAILY_STOP_BLOCK`. After only the first booking (loss 2.50, state NORMAL) the same call is not blocked and passes.
- UTC day roll (D033): a 120 loss on day 1 leaves equity 9880 and DAILY_STOP; `roll_to(day 2 00:00:00Z)` zeroes the day PnL, sets `equity_at_day_start` 9880 and re-resolves thresholds to 98.80 stop and 49.40 warning. A booking exactly at midnight belongs to day 2; one millisecond earlier stays on day 1. Thresholds are re-resolved only at a roll, never per booking.
- Exposure projection (D-18, D035): a resting plan projects an `OpenPosition` with its sized risk and `daily_pnl_contribution` 0; after TP1 (filled 0.5, remaining 0.25, initial 50) the open risk is 25; projections sort by (symbol, position_side) regardless of registration order; a resting 50 plus the candidate trips `CLUSTER_CAP_REJECT` in the real pipeline.
- Point-in-time constraints (D-17, D-30): for BTCUSDT rows 2026-03-01 (tick 0.10) and 2026-06-01 (tick 0.20), a 2026-04-10 bar selects March, a bar closing exactly 2026-06-01T00:00:00Z selects June, one millisecond earlier selects March, and 2025-12-31 selects March with `extrapolated=True`. The snapshot has `metadata_observed_at_utc` equal to the bar close; `evaluate_risk` with `ttl=timedelta(0)` and `now_utc` = bar close returns OK (also for the extrapolated row), and the true observed_at is returned separately.
- Fail-closed edges: missing symbol and duplicate `observed_at` raise `ConstraintHistoryError` naming the symbol; floats, ints, bools, NaN, non-positive values, naive and non-UTC timestamps are refused at parse time.

## Task Commits

1. **Task 1: Tracer (ledger bookings to DAILY_STOP_BLOCK)** - `209c0a3` (test, RED), `9fccf1f` (feat, GREEN)
2. **Task 2: UTC day roll, exposure projection, equity_positive** - `f95d752` (test, RED), `8c51046` (feat, GREEN)
3. **Task 3: Point-in-time constraint selection** - `8f7b4d5` (test, RED), `cadcece` (feat, GREEN)

**Plan metadata:** committed separately after this file (docs: complete plan, STATE and ROADMAP).

## Files Created/Modified

- `src/backtest/ledger.py` - Ledger, Exposure and the pure booking, day-roll, exposure and risk-projection functions
- `src/backtest/constraints.py` - ConstraintRow, parse_constraint_row, ConstraintHistory, select_constraints, PitConstraint
- `tests/test_backtest_ledger.py` - 26 tests: tracer chain, day roll, exposures, exhausted equity
- `tests/test_backtest_pit_constraints.py` - 20 tests: selection, boundary, extrapolation, clamp plus live freshness gate, parse refusals, no-TTL-in-module

## Decisions Made

See `key-decisions` in the frontmatter. The notable one beyond the plan text: when equity is exhausted at a day roll the thresholds resolve to zero (DAILY_STOP, all caps reject) because `resolve_absolute_thresholds` refuses non-positive equity and an uncaught raise mid-run would be the worse failure.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Exhausted-equity roll resolves zero thresholds**
- **Found during:** Task 1 (design of `_roll`), pinned in Task 2
- **Issue:** `resolve_absolute_thresholds` raises for equity <= 0, so a booking on the next UTC day after a ruinous loss would crash the run instead of failing closed
- **Fix:** `_resolve_thresholds` returns the four rate keys as 0 when equity <= 0; covered by `test_roll_to_with_exhausted_equity_fails_closed_to_daily_stop`
- **Files modified:** src/backtest/ledger.py, tests/test_backtest_ledger.py
- **Committed in:** 9fccf1f, f95d752, 8c51046

**2. [Rule 2 - Missing critical] Ledger.start refuses non-positive equity**
- **Found during:** Task 2 RED (the test failed with DID NOT RAISE against the Task 1 implementation)
- **Issue:** with the zero-threshold fallback above, `Ledger.start(equity=0)` would silently succeed
- **Fix:** explicit `ValueError` for equity <= 0 in `Ledger.start`
- **Files modified:** src/backtest/ledger.py
- **Committed in:** 8c51046

### Plan-text interpretations (not defects)

- `roll_to` is implemented as the public name in Task 2 over the private `_roll` that Task 1's `apply_booking` already needed; Task 1 `apply_booking` therefore rolls days as the plan specifies, and Task 2's day-roll tests pin it.
- Task 1's `evaluate_risk` tracer passes `open_positions=[]`; `open_positions_for_risk` arrives in Task 2 (as the plan's task split states) and is exercised against `evaluate_risk` in `test_resting_exposure_counts_toward_the_portfolio_gates_in_evaluate_risk`.

**Total deviations:** 2 additive fail-closed guards (Rule 2). **Impact on plan:** none on the artifacts' contracts; plan 14-08 should call `equity_positive` before building an `AccountState` and `cancel_resting_required` after every booking.

## TDD Gate Compliance

All three tasks have a `test(14-05)` commit before the matching `feat(14-05)` commit (209c0a3 -> 9fccf1f, f95d752 -> 8c51046, 8f7b4d5 -> cadcece); no refactor commit.

RED evidence, stated honestly:
- A first Task 1 RED run failed with `ModuleNotFoundError` (collection error, INVALID_RED under #3770). To avoid committing that, each new module (`ledger.py`, `constraints.py`) was committed with the RED tests as a behavior-less skeleton (correct signatures, no behavior), so the committed RED fails on assertions. Task 1 RED: 10 of 10 tests failed on assertions or DID NOT RAISE (e.g. `CLUSTER_CAP_REJECT != DAILY_STOP_BLOCK` because the skeleton left thresholds as raw rates). Task 2 RED (re-run from the RED commit): 12 failed (11 `AttributeError` on the not-yet-existing functions in the targeted tests, plus `DID NOT RAISE ValueError` for `Ledger.start(equity=0)`), 14 passed because they pin behavior Task 1 already had. Task 3 RED (re-run from the RED commit): 16 failed, 4 passed, the failures being assertions or DID NOT RAISE (the tick, clamp, extrapolation, freshness and parse-refusal assertions).
- `gsd_run check tdd-red-evidence` was not run for any task.

## Issues Encountered

- A first attempt to patch `ledger.py` with an inline Python heredoc failed on shell quoting before touching the file; redone with the Edit tool. No repository impact.

## Verification (real output)

- `pytest tests/test_backtest_ledger.py tests/test_backtest_pit_constraints.py tests/test_backtest_purity.py tests/test_domain_no_float.py tests/test_backtest_lifecycle.py tests/test_trade_record_validator.py tests/test_risk_portfolio.py tests/test_risk_parity.py`: `121 passed in 0.80s` (ledger 26, constraints 20).
- `ruff check`: all checks passed; `ruff format --check`: 387 files already formatted; `mypy src`: no issues found in 143 source files.
- Acceptance: ledger.py contains derive_daily_state and resolve_absolute_thresholds; ledger test calls evaluate_risk and asserts DAILY_STOP_BLOCK; all six Task 2 function names defined; hand values 98.80 and 49.40 present; constraints.py defines select_constraints and ConstraintHistoryError; the constraints test asserts the extrapolated flag; `git diff --name-only 2d8fbb1..HEAD -- src/risk` is empty.
- Not run: the full repository suite (only the plan subset plus the neighbouring risk, lifecycle and validator suites); these two modules have no importers yet.

## Regeneration inventory

none. No fixture, parameter set, pin or hash moved; two new pure modules and their tests only, and `src/risk` is untouched.

## Known Stubs

None. The modules are fully implemented; they have no consumer until the engine (plan 14-08) wires `Ledger` and `select_constraints` into the loop. `Booking` kinds for TP1 legs and funding are not produced yet (14-07, 14-08); the ledger books any signed Decimal amount, so nothing here changes when they arrive.

## Threat Flags

None. T-14-10 (point-in-time selection, flagged extrapolation, clamped snapshot, no clock or freshness window in the module, enforced by the purity glob and `test_module_holds_no_ttl_value`) and T-14-11 (state from `derive_daily_state`, DAILY_STOP reported for resting cancellation, tracer proves `DAILY_STOP_BLOCK` through `evaluate_risk`) are mitigated. No new network, auth, file or schema surface.

## Next Phase Readiness

Ready for 14-08 (engine loop), which depends on this plan for `Ledger`, `apply_booking`, `register_exposure`/`update_exposure`/`remove_exposure`, `open_positions_for_risk`, `cancel_resting_required`, `equity_positive` and `select_constraints`. No blockers.

## Self-Check: PASSED

All four created files exist on disk, all six task commits are present in `git log`, and every acceptance criterion and plan-level verification command re-ran green (see Verification).

---
*Phase: 14-backtest-causality-rewrite*
*Completed: 2026-10-04*
