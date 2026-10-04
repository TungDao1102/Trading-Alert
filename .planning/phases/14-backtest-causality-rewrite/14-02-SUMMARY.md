---
phase: 14-backtest-causality-rewrite
plan: 02
subsystem: backtest
tags: [backtest, causality, expiry, invalidation, trade-through, lifecycle, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "plan 14-01 tracer: PlanState, advance(), is_trade_through, is_touch_only, MinuteSource, tests/backtest_plan_helpers.py"
provides:
  - "src/backtest/entry.py: is_minute_eligible, is_touch, invalidation_level, is_invalidated (is_touch_only now built on is_touch)"
  - "src/backtest/lifecycle.py: RESTING branch with simulated-minute expiry, CANDLE_CLOSE invalidation (fill, then invalidation, then expiry), cancel_plan, finalize_at_data_end (RESTING half)"
  - "tests/test_backtest_expiry_clock.py: the Phase 6 gap G3 multi-bar proof with boundary minutes"
  - "tests/test_backtest_entry.py: entry rule tests for both sides, gaps, holes, touches, invalidation, cancel, data end"
affects: [14-07, 14-08, 14-09, 14-16]

actuals:
  tokens: 12500
  tasks: 3
  commits: 6
plan_head_before: aeef5079219c7cf6d56a568f62dba5d57be1fd13
plan_head_after: 7ff2db4876bb223a1565f97b35f7b292c82e758e

tech-stack:
  added: []
  patterns:
    - "Resting-entry precedence inside one advance(): fill first, closed-candle invalidation second, expiry last"
    - "Expiry is a pure function of plan.expiry_utc and the minute close; advance has no clock parameter"
    - "Cancel/pending helpers return (state, events) tuples exactly like advance()"

key-files:
  created:
    - tests/test_backtest_expiry_clock.py
    - tests/test_backtest_entry.py
  modified:
    - src/backtest/entry.py
    - src/backtest/lifecycle.py

key-decisions:
  - "advance() raises ValueError when a bar is passed whose close_time_utc differs from end_inclusive; bar=None is the only legal mid-bar window (fail closed so a mis-windowed engine cannot invalidate on the wrong close)"
  - "Invalidation is skipped when end_inclusive is after expiry_utc: the plan expired first, so EXPIRED at expiry_utc wins over a late bar close"
  - "cancel_plan accepts only EXPIRED, INVALIDATION_CANCEL and DAILY_STOP_CANCEL; an OPEN, CLOSED or fill kind raises ValueError"
  - "finalize_at_data_end on a CLOSED plan returns it unchanged and on an OPEN plan raises naming END_OF_DATA (14-07 extends it)"

patterns-established:
  - "New-API RED tests reach the code through module attributes (entry_rules.x, lifecycle_api.x) so a missing function fails one test, not module collection"

requirements-completed: [BKTS-01, DOMN-03]

duration: 15min
completed: 2026-10-04
status: complete
---

# Phase 14 Plan 02: Resting-Entry State Machine Summary

**A resting limit now ends exactly one way (FILL, EXPIRED, INVALIDATION_CANCEL, DAILY_STOP_CANCEL or PENDING_AT_DATA_END) with expiry judged against the simulated minute and never a fixture clock, closing Phase 6 gap G3.**

## Performance

- **Duration:** about 15 min (start inferred from the first commit; the start timestamp was not recorded)
- **Completed:** 2026-10-04
- **Tasks:** 3 (1 tracer, 2 auto, all tdd)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- G3 closed at the lifecycle level. With `signal_expiry_hours` 4 (signal close 09:59:59.999, expiry 13:59:59.999): the limit first traded through at 11:20 (bar N+2) fills with entry_time 11:20:59.999; the limit first traded through at 14:05 (bar N+5) ends EXPIRED with resolved_at 13:59:59.999, no entry_time and no FILL event. The 13:59 minute (close exactly at expiry) still fills, the 14:00 minute cannot, and the second-resolution variant (closes at :59 s) behaves identically.
- Window composition proven: four hourly advance calls give the same state and events as one advance over the whole span, for both a fill and an expiry; a window that starts after expiry cannot fill a resting plan.
- `advance` has no clock parameter (acceptance signature check passes, no parameter containing "now" or "clock").
- Entry rules both sides: snapped limit LONG 100.00 / SHORT 100.10 for mid 100.05 at tick 0.10, trade-through thresholds 99.90 and 100.20, touch-only minutes counted (3 touches give `touch_no_fill_count` 3 and zero extra events), gaps through the limit fill at the limit (97.00 open fills at 100.00 LONG, 103.00 open fills at 100.10 SHORT), a hole in the trade series never fills and is never padded, signal-bar minutes never fill, the tick comes from `PlanState` (tick 0.10 vs 0.50 give different limits and different fill outcomes), and a touch after expiry is not counted.
- CANDLE_CLOSE invalidation: `invalidation_level` parses the planner rule and raises on bad JSON, wrong basis, missing level, float level or non-decimal level; a LONG bar close of 97.90 below level 98.00 ends INVALIDATION_CANCEL at the bar close, close exactly 98.00 does not; SHORT mirror at 102.10 over 102.00; a bar whose minute 10:30 trades through and that closes 97.90 FILLS; a bar closing exactly at expiry beyond the level is INVALIDATION_CANCEL (without a bar the same window is EXPIRED); a mid-bar window (bar None) never invalidates.
- `cancel_plan` ends a RESTING plan at an arbitrary instant (DAILY_STOP_CANCEL) and refuses an OPEN position (D033 keeps its stop). `finalize_at_data_end` turns a RESTING plan into PENDING_AT_DATA_END (never EXPIRED) and refuses an OPEN position naming END_OF_DATA, so none passes silently before plan 14-07.

## Task Commits

1. **Task 1: Tracer, G3 expiry clock** - `07e8a7d` (test, RED), `74661d2` (feat, GREEN)
2. **Task 2: Both-side entry rules, touch, gap, hole** - `7a9b49e` (test, RED), `b02a6a7` (feat, GREEN)
3. **Task 3: Invalidation, cancel, data end** - `2b5383b` (test, RED), `7ff2db4` (feat, GREEN)

**Plan metadata:** committed separately after this file (docs: complete plan).

## Files Created/Modified

- `src/backtest/entry.py` - `is_minute_eligible`, `is_touch`, `invalidation_level`, `is_invalidated`; `is_touch_only` rebuilt on `is_touch`
- `src/backtest/lifecycle.py` - eligibility skip, invalidation and expiry in the RESTING branch, `_close_resting`, `cancel_plan`, `finalize_at_data_end`, bar/window consistency check
- `tests/test_backtest_expiry_clock.py` - G3 proof (10 tests)
- `tests/test_backtest_entry.py` - entry rules, invalidation, cancel, data end (25 tests)

## Decisions Made

See `key-decisions` in the frontmatter. The invalidation rule change for plan 14-16 is recorded in the dedicated section below.

## Invalidation rule change (for BACKTEST_SPEC section 6, plan 14-16)

The v1 simulator (`src/backtest/simulator.py`, lines about 343 to 372) cancelled a resting entry with `INVALIDATION_CANCEL` when the entry bar's `close < open` (LONG) or `close > open` (SHORT), a bar-direction heuristic with no basis in the plan. It is not carried over. The v2 rule (D-05, D-35) is the plan's own `invalidation_rule_json` CANDLE_CLOSE rule: at each strategy-bar close, an unfilled plan is cancelled when the bar close is strictly beyond `level` (LONG close < level, SHORT close > level), where `level = stop_loss_price`. The fill is evaluated first on the bar's 1m minutes, invalidation second, expiry last; invalidation wins when the bar closes exactly at `expiry_utc`. Plan 14-16 should rewrite `docs/backtest/BACKTEST_SPEC.md` section 6 accordingly. The v1 simulator code itself is untouched here (it is retired by the engine plans).

## Deviations from Plan

None - plan executed as written. Judgement calls inside the plan's latitude (recorded as key-decisions): the bar/window consistency check, invalidation skipped when the window end is past expiry, the restricted `cancel_plan` kind set, and the `(state, events)` return shape of the two new functions (the plan did not fix it; plan 14-08 only names the call `cancel_plan(entry_kind=DAILY_STOP_CANCEL, at_utc=t)`).

## TDD Gate Compliance

All three tasks have a `test(14-02)` RED commit before their `feat(14-02)` GREEN commit, no refactor commits. RED evidence, stated honestly (`gsd_run check tdd-red-evidence` was not run):
- Task 1 RED: 6 of 10 tests failed on assertions (for example `ENTRY_FILLED` where `EXPIRED` was expected) and one failed on the missing `is_minute_eligible` import (imported inside that test so the others still ran). The fill-before-expiry, composition-for-a-fill and signature cases passed on arrival by design.
- Task 2 RED: only the `is_touch` unit test failed (ImportError inside the test); the other 9 behaviors (SHORT, gap through, holes, touch counting, signal bar, tick from state) already held because the tracer built them, so they were committed as pinning tests. No behavior change was needed besides `is_touch`.
- Task 3 RED: 11 of 15 new tests failed (AttributeError on the missing functions, and assertion failures such as `RESTING == CLOSED` / `None == INVALIDATION_CANCEL` / `EXPIRED == INVALIDATION_CANCEL` / `DID NOT RAISE` for the bar mismatch); four pinned behavior that already held (exact-level no-invalidation, fill-first, expiry beating a late bar, mid-bar window).

## Issues Encountered

- Heredoc edits through the shell tool failed twice on content with apostrophes; the edits were applied from a script file instead (no effect on the result).
- My first `_flat_minutes` fixture had an open outside its own [low, high] and the `Candle` guard rejected it; fixed in the RED commit before the commit was made.

## Verification (real output)

- Plan verification pytest (`test_backtest_entry`, `test_backtest_expiry_clock`, `test_backtest_lifecycle`): 44 passed. Wider set including purity, no-float, validator, series and realized-risk modules: all passed (92 tests).
- `ruff check`: all checks passed; `ruff format --check`: 381 files already formatted; `mypy src`: no issues found in 140 source files.
- Acceptance greps all green: "13:59:59.999" and "EXPIRED" in the expiry test, `now_utc` absent from the `advance` signature, `def is_touch` / `def is_trade_through` / `def invalidation_level` / `def is_invalidated` / `def cancel_plan` / `def finalize_at_data_end` present, SHORT and gap cases present, "PENDING_AT_DATA_END" and "INVALIDATION_CANCEL" in the entry tests, `src/domain/enums.py` not touched.

## Regeneration inventory

none. No fixture, parameter set, pin or hash moved; `src/domain/enums.py` is unchanged and no RejectionReason member was added.

## Known Stubs

None added. Still owned by later plans: TP ladder, stop gap, fallback and the OPEN-state END_OF_DATA close (14-07; `finalize_at_data_end` raises for OPEN until then), the DAILY_STOP orchestration that calls `cancel_plan` (14-08), `booking_for_event` for CANCEL/PENDING events (14-07).

## Threat Flags

None. T-14-04 (expiry compares the minute close with `expiry_utc` only, no clock parameter, signature acceptance check) and T-14-05 (holes are absent and never padded, hole test proves no fill) are mitigated by tests.

## Next Phase Readiness

Ready for 14-07 (exits and END_OF_DATA, extends `finalize_at_data_end`) and 14-08 (engine, uses `cancel_plan` and the bar-closing-at-window-end contract). The engine must pass `bar=` only for a window that ends exactly at that strategy bar's close time.

## Self-Check: PASSED

Created and modified files exist on disk, all six task commits are present in `git log`, and every acceptance criterion and plan verification command re-ran green.

---
*Phase: 14-backtest-causality-rewrite*
*Completed: 2026-10-04*
