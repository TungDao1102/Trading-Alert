---
phase: quick-261014-nnl
plan: 04
subsystem: backtest engine / terminal settlement interplay
tags: [s-b-interval, engine, dropped, daily-stop, no-plan-rule, data-after-t, settlement-count, tdd]
requires: ["03"]
provides:
  - "src/backtest/engine.py: a booked SETTLEMENT exit or SETTLEMENT_CANCEL adds the symbol to window.dropped before the DAILY_STOP check"
  - "src/backtest/engine.py: _terminal_blocks (no plan when signal_close + 1 minute > T) at the pinned label position in both front-ends"
  - "src/backtest/engine.py: _check_terminal_inputs (data beyond T of a declared symbol raises in __init__)"
  - "run_summary.settlement_count, present only when the case declares a settlement"
affects: [quick-261014-nnl plans 05, 06]
key-files:
  created:
    - tests/test_backtest_terminal_engine.py
  modified:
    - src/backtest/engine.py
decisions:
  - "Label position (planner choice, confirmed in the index): equity check -> strategy evaluate -> conflict check -> terminal check -> plan build; scripted: equity -> conflict -> terminal -> sizing. Every existing label keeps its count"
  - "settlement_count is conditional on the case declaring a settlement, so every undeclared run_summary keeps its 18 keys"
  - "Input checks run once in _Engine.__init__ (end of _index_inputs), before the first window is processed"
requirements-completed: []
status: complete
commits: 6
plan_head_before: 0bf7a2930cc7465d9419b97c9639882e569c45cd
plan_head_after: 996462d8ed7a0c4b2a913dbbac86b4153b25dd90
actuals:
  tokens: 8600   # chars/4 over the diff 0bf7a29..HEAD (src and tests)
  tasks: 3
  commits: 6
metrics:
  completed: 2026-10-14
---

# Phase quick-261014-nnl Plan 04: Engine interplay of the terminal settlement Summary

A symbol settled or cancelled at its terminal instant T is now dropped from the window before any DAILY_STOP check (one terminal booking per entity), a declared symbol gets no plan that could not become active before T (label `TERMINAL_BEFORE_ACTIVATION`, counted after the equity and conflict checks), data beyond T of a declared symbol raises before the simulation, and `run_summary` carries `settlement_count` only for cases that declare a settlement.

## Task results

| Task | Name | Commits | Result |
|------|------|---------|--------|
| 1 | RESTING at T, window.dropped and DAILY_STOP (design tests 6 and 11) | 95824dd (RED), 9854659 (GREEN) | RED: 2 of 8 failed (ledger `ValueError: unknown exposure` on the second cancel of an already cancelled plan); GREEN: 8 passed |
| 2 | No-plan rule with pinned label position; inputs after T raise (design tests 7 and 8) | 1e6eab4 (RED), 4eb39dc (GREEN) | RED: 10 failures (missing `_terminal_blocks`, no label, 7 x DID NOT RAISE); GREEN: all 22 tests of the file passed |
| 3 | settlement_count only when the case declares a settlement | 8046558 (RED), 996462d (GREEN) | RED: 2 failures (key missing / present check); GREEN: 24 passed |

## What was built

- `_drain`: after `_book` and `_update_exposure`, an event with `exit_kind == EXIT_SETTLEMENT` or `entry_kind == SETTLEMENT_CANCEL` adds the symbol to `window.dropped`, before the `cancel_resting_required` check. `_cancel_resting` therefore skips it and no later heap item of it is booked. Nothing else in `_drain` changed.
- `_terminal_blocks(symbol, close)`: true for a declared symbol when `close + 1 minute > T`. `_evaluate_scripted`: equity -> conflict -> terminal -> sizing. `_evaluate_strategy`: equity -> `evaluate` (its no-trade reason counted as before) -> conflict -> terminal -> plan build. The count goes under `NO_TRADE_TERMINAL`.
- `_check_terminal_inputs` (called at the end of `_index_inputs`): for each declared symbol raises `ValueError` (naming symbol, series and T) for a 1h strategy bar closing after T, a context bar opening at or after T, a funding row at or after T, or a trade or mark minute closing after T (`source.trade_minutes/mark_minutes(symbol, T, data_end)` non-empty). A 4h context bar opening before T is allowed; undeclared symbols are not looked at.
- `_output`: `settlement_count = sum(exit_kind == SETTLEMENT)` added to the summary only when `parsed.terminal_settlements` is non-empty; the `simulate` docstring names the conditional key.

## Test coverage (tests/test_backtest_terminal_engine.py, 24 tests)

- Design test 6: RESTING at T ends SETTLEMENT_CANCEL at T, fill fields None, RESTING note, one CANCEL booking, no exposure left.
- Design test 11: a DAILY_STOP after T from another symbol (SOLUSDT stop-out at 10:15) neither cancels nor books again the cancelled plan (RED proof) or the settled position; DAILY_STOP before T (both window shapes) wins with DAILY_STOP_CANCEL and no SETTLEMENT_CANCEL; at the T instant the heap order (time, symbol, rank) decides: BTCUSDT before REEFUSDT cancels REEF DAILY_STOP_CANCEL at T, SOLUSDT after it does not; an OPEN position keeps its stop through an earlier DAILY_STOP and settles at T.
- Design test 7: signal close 08:59:59.999 creates no plan, no exposure, risk gate never called, `TERMINAL_BEFORE_ACTIVATION == 1`; 07:59:59.999 still plans; the boundary `close + 1 minute` is pinned on `_terminal_blocks`; label position pinned for both front-ends (exhausted equity -> UNCERTAIN_ACCOUNT_STATE only, active plan -> CONFLICT_WITH_OPEN_POSITION only, strategy no-signal reason counted as before).
- Design test 8: each of the five defect kinds raises (trade and mark both), the 4h context bar opening before T and undeclared symbols with data after another symbol's T are unaffected.
- Summary key: undeclared run keeps the 18 keys, declared run adds `settlement_count`; counts settlement exits, not cancels; `end_of_data_count` unaffected.

## Verification

- `pytest tests/test_backtest_terminal_engine.py`: 24 passed. The plan's three automated verify groups (6, 9 and the whole file) pass.
- Neighbouring suites unedited and green: `test_backtest_engine.py`, `test_backtest_engine_strategy.py`, `test_backtest_terminal_settlement.py`, `test_backtest_terminal_funding.py`, `test_research_terminal_settlement_manifest.py`.
- `uv run pytest -m "not docker"` (whole suite, AST purity and no-float guards included): 6570 passed, 459 skipped (DB-dependent tests without `TEST_DATABASE_URL`), 28 deselected, pytest exit 0.
- `mypy src`: no issues in 185 files. `ruff check` and `ruff format --check` (540 files): clean. `uv lock --check`: resolved, no change.
- `git diff --name-status 0bf7a29 HEAD`: `M src/backtest/engine.py`, `A tests/test_backtest_terminal_engine.py`; no deletion; no existing test file touched; nothing under params/, src/paper/, docs/, .gsd/, package files, `holdout_consumed.json` or any manifest. Undeclared inputs run through unchanged code paths: no existing label count, digest or golden moved (full suite green).

## Deviations from Plan

1. [Judgement] Task 1 behaviour list asked for a conditional clamp of `_cancel_resting` re-advance to `min(at_utc, T)` "if a test shows" it is needed. No test showed it: with the dropped rule in place no declared RESTING plan is re-advanced past T. No clamp added.
2. [Test structure] The conflict and equity cases of the label-position test call the engine's private `_evaluate_signal` on a `_Engine` built from a parsed case (the strategy path needs an active entity and exhausted equity, which cannot be produced through public input without a long scripted run). The boundary of `close + 1 minute` is pinned on `_terminal_blocks` directly. The strategy front-end uses a monkeypatched `engine.evaluate` and forbids `build_trade_plan` (as the existing engine-strategy tests monkeypatch `evaluate`).
3. [Process] Four of the 24 tests (`one_hour_earlier`, `context_bar_before_terminal_allowed`, `undeclared_symbol_unaffected`, `strategy_no_signal_reason`) and the DAILY_STOP-before-T / settled-position / RESTING-cancel tests passed already at RED: they pin behaviour that must not change (or that plan 03 already delivered). The RED evidence is the failing tests listed in the table (2 + 10 + 2).
4. [Environment] `src/backtest/engine.py` is CRLF in the working tree (`core.autocrlf=true`, index is LF); edits kept the working-tree line endings, the commits are LF. The new test file is LF.
5. The branch is `develop`, which the generic executor protected-branch assertion lists; committing there was directed by the caller and the plan, on the main tree with no worktree.

No auth gates. No stubs. No threat flags beyond the plan's threat model (T-nnl-10 mitigated by the dropped rule and tests 6/11, T-nnl-11 by the init check, T-nnl-12 by the pinned label position).

## Observations for later plans

- A declared symbol whose `ListMinuteSource` has no trade or mark series at all now fails in `__init__` with the source's own `MinuteSeriesError` ("no trade-price minute series for X"), a ValueError that does not name T. Real run cases always carry minutes for a declared symbol (plan 02 builder), so no change was made.
- A scripted plan of a declared symbol whose bar close is after T is counted `TERMINAL_BEFORE_ACTIVATION`, not refused; only strategy bars, context bars, funding and minutes are refused (as the plan specifies).

## Not done (by scope)

Plans 05 to 10: consumers (report, feasibility, analytics), integration through `run_research`, version bump (2.0.0 stays), protocol text, `holdout_consumed.json`, manifest files, ROADMAP and STATE updates.

## Self-Check: PASSED

`tests/test_backtest_terminal_engine.py` exists, the six commits (95824dd, 9854659, 1e6eab4, 4eb39dc, 8046558, 996462d) are in `git log`, and `commits: 6` was measured with `git rev-list --count` from the persisted ledger (base 0bf7a29).
