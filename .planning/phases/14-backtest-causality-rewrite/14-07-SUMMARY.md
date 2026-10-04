---
phase: 14-backtest-causality-rewrite
plan: 07
subsystem: backtest
tags: [backtest, causality, exits, tp-ladder, stop-first, fallback, end-of-data, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "plans 14-01/14-02: PlanState, advance(), LifecycleEvent, booking_for_event/build_trade_record, resting-entry state machine, finalize_at_data_end (RESTING half); plan 14-03: OpenSegment contract for funding"
provides:
  - "src/backtest/exits.py: protective_levels_for_fill, ProtectiveReject, ExitLeg, LEG_TP1, resolve_mark_minute, resolve_fallback_hour, FallbackResolution, end_of_data_exit, take_profit_levels, is_tp_touched"
  - "src/backtest/lifecycle.py: OPEN branch (stop-first TP1/TP2 ladder, fill-minute rule, stop gaps, hole fallback at the bar close), _apply_leg/_apply_legs, finalize_at_data_end closing OPEN positions as END_OF_DATA, new_plan_state(levels=...)"
  - "src/backtest/records.py: per-leg cost booking (TP1 leg and final leg), BOOKING_TP1, BOOKING_CANCEL, BOOKING_PENDING, booking_for_event for TP1/CANCEL/PENDING"
  - "tests/test_backtest_exits.py (32 tests) and tests/test_backtest_records.py (24 parametrized cases)"
affects: [14-08, 14-09, 14-11, 14-16]

actuals:
  tokens: 19000
  tasks: 3
  commits: 6
plan_head_before: edb8672ce2c7c6128c55f1711045203897c97c0f
plan_head_after: 54ccf33af041eb3d28009cb1ae3afe9fa2c313d1

tech-stack:
  added: []
  patterns:
    - "Exit legs are data (ExitLeg), resolved by pure functions and applied through one _apply_leg, so lifecycle, fallback and END_OF_DATA share one state transition"
    - "Stop decided before any take-profit; on the fill minute only the stop is eligible; stop legs book the adverse of trigger and mark-minute open"
    - "Live helper reuse: TP1 quantity and snapped triggers come only from size_protectives_to_filled_qty with ProtectiveTemplate(tp1_quantity_fraction=TP1_QUANTITY_FRACTION); no rounding is re-derived in src/backtest"

key-files:
  created:
    - tests/test_backtest_exits.py
    - tests/test_backtest_records.py
  modified:
    - src/backtest/exits.py
    - src/backtest/lifecycle.py
    - src/backtest/records.py
    - tests/test_backtest_entry.py

key-decisions:
  - "new_plan_state takes the sized levels as an optional `levels` argument (the engine passes protective_levels_for_fill's result, plan 14-08 text); without it the state is stop-only and only its stop can exit it. A ProtectiveReject is the engine's NO_TRADE (D-27)"
  - "Hole detection only happens in a window that ends at a strategy bar close (bar passed). Expected mark minutes run from max(window start, first whole minute after entry, bar open) to the last minute of the bar; the walk stops at the first missing minute (minutes after the hole are not used) and the rest of the bar resolves once at the bar close from the trade-price bar range, stop-first"
  - "Fallback legs book the stop trigger (no gap rule, the open of a strategy bar is not a mark minute open) and take-profit triggers; when the position was filled inside the bar being resolved the range also contains pre-fill minutes, so only the stop may be resolved there (the take-profit is deferred to the next bar, the fallback analogue of the fill-minute rule)"
  - "finalize_at_data_end gained a keyword `source: MinuteSource | None = None`; an OPEN position without it raises ValueError naming END_OF_DATA. end_of_data_exit reads the mark series backward in doubling look-back windows (1 h start) from the data end down to the fill minute, so a long holding period is never loaded whole; no mark minute raises"
  - "booking_for_event books CANCEL and PENDING events as zero-amount bookings (kinds BOOKING_CANCEL, BOOKING_PENDING) at their own time, so the engine can book every lifecycle event uniformly"
  - "Final-leg cost validation goes through _exit_slippage_rate only (SL, END_OF_DATA: exit_slippage_rate; TP2: expected_slippage; any other kind, including TP1, raises ValueError); the TP1 partial is costed through its own helper at expected_slippage"

patterns-established:
  - "Test modules reuse helpers across files by importing from tests.test_backtest_exits (flat-minute builders, strategy-bar builder, hole sets, hand oracles)"

requirements-completed: [BKTS-01]

duration: 36min
completed: 2026-10-04
status: complete
---

# Phase 14 Plan 07: Exit Ladder, Stop-First Ties, Fallback and END_OF_DATA Summary

**The simulator now mirrors the live exit policy: a live-sized TP1 half (floor to step, min-qty/min-notional gated) then TP2, mark-price triggers at live-snapped levels, stop-first ties, adverse stop gaps, a bar-close fallback for mark holes and an END_OF_DATA close, all costed leg by leg so ledger bookings equal `realized_pnl` exactly (audit F-102).**

## Performance

- **Duration:** about 36 min (15:04Z to 15:40Z)
- **Completed:** 2026-10-04
- **Tasks:** 3 (1 tracer, 2 auto, all tdd), 6 task commits
- **Files:** 2 created, 4 modified

## Accomplishments

- F-102 closed. LONG filled 0.5 at 100.00, SL 98.00, TP1 104.00, TP2 108.00, tick 0.10, step 0.001: TP1 books 0.250 at 104.00 on bar N+2 (quantity from `size_protectives_to_filled_qty`), the stop stays 98.00, TP2 books 0.250 at 108.00 on bar N+4 although the mark high is 108.05 (no price improvement). Record: gross 3.00, exit_fee 0.0265, slippage 0.0206, realized_pnl 2.9279; bookings -0.0350 + 0.9818 + 1.9811 equal it exactly. The F-102 worked example (TP1 then SL on the remainder) gives gross 0.50 and realized 0.41005, not the v1 +2.00 whole-position win.
- Unsizeable TP1 is reported with the live reason: filled 0.001 gives MIN_QTY_REJECT (half floors to 0), filled 0.002 gives NOTIONAL_REJECT (0.001 x 104.00 below min notional 5); TP triggers snap toward the entry (LONG 104.05 to 104.00, SHORT 96.05 to 96.10).
- Stop-first (D-12): a minute touching SL and TP1 exits the whole 0.5 at the stop with no TP1 leg; SL and TP2 after a TP1 exits only the remainder at the stop; TP1 and TP2 in one minute with no SL books TP1 then TP2 at that minute close; SHORT mirror proven for the tie, the gap and a full TP1/TP2 ladder.
- Fill-minute rule (D-33): a TP touch on the fill minute is deferred (it books on the next minute if touched again); SL on the fill minute exits with exit_time equal to entry_time.
- Stop gaps (D-33): a minute opening at 97.50 below SL 98.00 books 97.50 and sets `gap_through_stop`; a minute opening above the stop and trading through it books 98.00 with the flag False; after a TP1 the remainder gaps at the adverse open; SHORT books the higher of trigger and open (102.50 over 102.00).
- Fallback (D-12, D-33): hole from 12:15 in the 12:00 bar with bar low 97.90 gives SL at 98.00 with exit_time equal to the bar close 12:59:59.999, `fallback_applied` True and a coverage_note naming 2026-01-05T12:15:00+00:00. A bar range that touches only TP1 books TP1 at the bar close and the position stays OPEN; TP2 in range books TP1 then TP2; minutes before the hole are walked and minutes after it are not used; a mid-bar window (bar None) resolves nothing and a later bar-close window resolves the hour; full mark coverage never uses the fallback even when the bar range is wide; a fill-bar fallback resolves only the stop.
- END_OF_DATA (D-06, D-34): an OPEN LONG at data end 12:00 closes at the last mark close (11:59:59.999, price 100.40) with exit_kind END_OF_DATA, gross 0.20, slippage 0.0602 (exit leg at exit_slippage_rate), realized 0.0897, and passes `validate_trade_record` with the data window; after a TP1 only the remainder closes (realized 1.00915). A trailing mark hole (series ends 10:30, data ends 13:00) uses the 10:30 close via the doubling look-back; no source or no mark minute raises.
- Reconciliation: for SL, TP2, END_OF_DATA, TP1-then-SL and TP1-then-END_OF_DATA, with funding 0, +0.0052 and -0.0031, `sum(bookings) + funding == record.realized_pnl` exactly. Cancel and pending events book zero.

## Task Commits

1. **Task 1 (tracer): live TP1/TP2 ladder with per-leg record** - `ee0cabc` (test, RED), `074ee97` (feat, GREEN)
2. **Task 2: stop-first ties, fill-minute rule, adverse gaps** - `27c5917` (test, RED), `8d6d349` (feat, GREEN)
3. **Task 3: bar-close fallback, END_OF_DATA, per-kind bookings** - `ce66e34` (test, RED), `54ccf33` (feat, GREEN)

**Plan metadata:** committed separately after this file (docs: complete plan).

## Files Created/Modified

- `src/backtest/exits.py` - levels via the live sizing helper, leg resolution (`resolve_mark_minute`, `resolve_fallback_hour`, `end_of_data_exit`), `LEG_TP1`, `ExitLeg`
- `src/backtest/lifecycle.py` - OPEN-branch walk with hole detection, `_apply_leg`, `finalize_at_data_end` OPEN close, `new_plan_state(levels=)`
- `src/backtest/records.py` - per-leg cost helpers, TP1/CANCEL/PENDING bookings, per-leg `build_trade_record`
- `tests/test_backtest_exits.py` - 32 tests (ladder, ties, gaps, fallback, END_OF_DATA) with hand oracles in the docstrings and comments
- `tests/test_backtest_records.py` - 5 test functions, 24 cases (reconciliation across exit kinds, slippage rate per leg kind, legacy-model and exit-kind refusals, zero cancel/pending bookings)
- `tests/test_backtest_entry.py` - one 14-02 fixture completed (see Deviations) and one test renamed

## Decisions Made

See `key-decisions` in the frontmatter. For plan 14-16 (BACKTEST_SPEC): TP1 is half the fill (D-27) floored by the live helper; fallback resolves the rest of a holed bar once at the bar close from the trade-price bar range, stop-first, and defers TPs when the fill is inside that bar; a stop gap books the adverse of trigger and mark-minute open; END_OF_DATA uses the last mark close and `exit_slippage_rate`.

## Time-stop search (D-06)

No time stop or maximum holding rule exists, so none was added. Searched (grep, case-insensitive, patterns `time.stop|max.hold|holding time|hold.*bars|max_bars|time-based exit|exit after|bars held|max_holding|time_stop`) in `src/`, `docs/` and `params/`: the only hits are `docs/backtest/METRICS.md:122` ("holding time is excessive", a reporting remark), `src/data/sufficiency.py` (flat zero-trade bars) and `src/paper/loop.py` (`WARMUP_MIN_BARS` in `__all__`), none an exit rule. Also read: `docs/strategy/TRADING_STRATEGY_SPEC.md` sections 6-9 (invalidation, stop loss, take profit, expiry: all `TBD`), `docs/trading/EXECUTION_SPEC.md` and `src/execution/*.py` (grep for time stop, max hold, position expiry: none; the only expiry language is for approvals and plans), and every `params/*/*.toml` (no key matches). A position is therefore carried until SL, TP2 or data end.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] A plan 14-02 test fixture produced a mark hole after a fill and tripped the new fallback**
- **Found during:** Task 3 GREEN (full backtest test run)
- **Issue:** `test_fill_is_evaluated_first_so_a_filling_bar_is_never_invalidated` (plan 14-02) fills at 10:30 inside a 1h bar with low 97.00 and supplies mark minutes only for the trade minutes (10:00 to 10:30). Under the D-12/D-33 rule introduced here the rest of that bar resolves at the bar close, stop-first, so the position stopped out and the assertion `phase == OPEN` failed. The test's intent (a filling bar is never invalidated) is unrelated to mark coverage.
- **Fix:** the fixture now supplies benign mark minutes for the whole hour; the assertions are unchanged. Also renamed `test_finalize_at_data_end_refuses_an_open_position_until_plan_14_07` to `..._without_a_minute_source` (it still passes and now pins the no-source refusal).
- **Files modified:** tests/test_backtest_entry.py
- **Commit:** `54ccf33`

**Total deviations:** 1 auto-fixed (1 stale test fixture). **Impact:** none on the contract; every 14-02 behavior assertion still holds.

Judgement calls inside the plan's latitude are recorded as key-decisions (the `levels` argument on `new_plan_state`, hole-detection window rules, the fill-bar fallback restriction, the `source` argument on `finalize_at_data_end`, zero bookings for CANCEL/PENDING).

## TDD Gate Compliance

All three tasks have a `test(14-07)` RED commit before their `feat(14-07)` GREEN commit; no refactor commits. `gsd_run check tdd-red-evidence` was not run; RED evidence, stated honestly:
- Task 1 RED (`ee0cabc`): the RED commit carries a stop-only `protective_levels_for_fill` skeleton and the real `levels` argument on `new_plan_state`, so the 7 new tests failed on assertions (`None == Decimal('104.00')` for the levels, `isinstance(..., ProtectiveReject)` False, `tp1_quantity None != 0.250`, bookings `['FILL'] != ['FILL','TP1','EXIT']`) and one on `ValueError: build_trade_record needs a CLOSED state` because the ladder never closed the plan.
- Task 2 RED (`27c5917`): with a `resolve_mark_minute` skeleton returning no legs, 6 of 13 new tests failed on assertions (empty leg lists, `98.00 != 97.50` and `102.00 != 102.50` for the gap cases). The other 7 (tie-break through the inline Task 1 loop, TP1-then-SL costs, same-minute TP1+TP2, fill-minute SL and deferral, no-gap trade-through, SHORT ladder) already held and are pinning tests.
- Task 3 RED (`ce66e34`): 11 of 12 new exits tests failed on assertions (`exit_kind None != 'SL'`, `fallback_applied False`, `[] != [('SL', 98.00, 0.5)]`, regex mismatch for the not-implemented END_OF_DATA skeleton) or on the missing OPEN close (`ValueError` from `finalize_at_data_end`); in `tests/test_backtest_records.py` 10 of 24 cases failed (END_OF_DATA cases raised the missing-close `ValueError`, exit kind "TP1" was accepted by the cost step and only the validator refused it, CANCEL events could not be booked). The remaining new tests pinned behavior already held (SL and TP2 reconciliation, legacy-model refusals for SL, unknown exit kinds EOD/TP3/STOP).

## Issues Encountered

- Heredocs containing apostrophes or triple quotes failed to parse through the shell tool (as in plans 14-02 and 14-03); patches were applied from script files instead, with no effect on the result.
- `ruff format` rewrote files between my reads, so the harness reported them as changed and I re-read before editing.
- The first RED version of `test_backtest_exits.py` tripped ruff B008 (a call in an argument default); fixed before the RED commit.

## Verification (real output)

- Plan verification pytest (`tests/test_backtest_exits.py tests/test_backtest_records.py tests/test_backtest_entry.py tests/test_backtest_lifecycle.py tests/test_trade_record_validator.py`): all passed (56 in the two new modules, the rest unchanged). A wider backtest run (exits, records, entry, lifecycle, validator, expiry clock, funding, purity, no-float, ledger, simulator, series, experiment, report, binding): all passed (about 320 tests).
- Full suite (`pytest tests -q -x`): exit code 0, 26 skipped (pre-existing skips, none mine).
- `ruff check .`: all checks passed; `ruff format --check .`: 390 files already formatted; `mypy src`: no issues found in 143 source files.
- Acceptance greps all green: `size_protectives_to_filled_qty` and `TP1_QUANTITY_FRACTION` in exits.py; "0.250" and "TP2" in the exits tests; `def resolve_mark_minute`, `def resolve_fallback_hour`, `def end_of_data_exit`; `gap_through_stop` and a SHORT tie case in the exits tests; "END_OF_DATA" and `realized_pnl` in the records tests. exits.py imports its quantize helpers only from `src.execution.placement`; no TP quantity flooring exists in `src/backtest`.
- Tracer gate (auto mode): the tracer verify was re-run after the GREEN commit, passed, then expansion continued.

## Regeneration inventory

none. No fixture, parameter set, pin or hash moved; `src/domain/enums.py`, `src/backtest/semantics.py` and the cost model are unchanged and no RejectionReason member was added.

## Known Stubs

None. Not wired into the engine yet (owned by later plans): the call to `protective_levels_for_fill` and the NO_TRADE reject for a `ProtectiveReject`, passing `levels=` to `new_plan_state`, per-bar `advance` calls with the closing bar, the `source=` argument to `finalize_at_data_end`, the funding segments split at the TP1 instant, and booking every event through `booking_for_event` (all plan 14-08).

## Threat Flags

None. T-14-13 (stop-first ordering, fill-minute SL-only rule, adverse gap pricing, no TP price improvement) and T-14-14 (fallback only on holes, resolved at the bar close, `fallback_applied` and `coverage_note` always set) are mitigated by unit tests.

## Next Phase Readiness

Ready for 14-08 (engine). Contract for the engine: size each plan with `exits.protective_levels_for_fill` at fill quantity and turn a `ProtectiveReject` into a NO_TRADE before creating the state; pass `levels=` to `new_plan_state`; call `advance` bar by bar with `bar=` only for a window ending exactly at that bar's close (a hole is judged only there); pass `source=` to `finalize_at_data_end`; split `OpenSegment`s at `state.tp1_time_utc`; book every event through `booking_for_event` (CANCEL and PENDING book zero).

## Self-Check: PASSED

`tests/test_backtest_exits.py` and `tests/test_backtest_records.py` exist on disk, all six task commits (`ee0cabc`, `074ee97`, `27c5917`, `8d6d349`, `ce66e34`, `54ccf33`) are in `git log`, and every acceptance criterion and plan verification command re-ran green.

---
*Phase: 14-backtest-causality-rewrite*
*Completed: 2026-10-04*
