---
phase: quick-261014-nnl
plan: 03
subsystem: backtest engine / terminal settlement
tags: [s-b-interval, settlement, funding-clip, lifecycle, tdd]
requires: ["01"]
provides:
  - "optional backtest-case/2 key terminal_settlements, TerminalSettlementRow, ParsedCase.terminal_settlements (default empty)"
  - "lifecycle.settle_at_terminal (OPEN -> SETTLEMENT exit at the adverse bound; RESTING -> SETTLEMENT_CANCEL; CLOSED unchanged)"
  - "semantics vocabulary: EXIT_SETTLEMENT, SETTLEMENT_CANCEL, NO_TRADE_TERMINAL, TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES, TERMINAL_EVALUATION_UNION_ADVERSE_BOUND, SETTLEMENT_NOTE_PREFIX"
  - "funding_events / check_funding_coverage optional keyword terminal_at_utc (default None)"
affects: [quick-261014-nnl plans 02, 04, 05]
key-files:
  created:
    - tests/test_backtest_terminal_settlement.py
    - tests/test_backtest_terminal_funding.py
  modified:
    - src/backtest/semantics.py
    - src/backtest/case.py
    - src/backtest/lifecycle.py
    - src/backtest/records.py
    - src/backtest/engine.py
    - src/backtest/funding.py
decisions:
  - "SETTLEMENT leg slippage is zero in the one shared rule _exit_slippage_rate, so booking_for_event and build_trade_record cannot disagree"
  - "The funding clip is the keyword terminal_at_utc on the pure funding functions; shadow_fill.py and shadow_runtime.py are untouched and undeclared cases call the old path unchanged"
  - "A funding row of a declared symbol at or after T raises FundingCoverageError (also from the engine slice, which carries one neighbour row beyond its upper edge)"
requirements-completed: []
status: complete
commits: 6
plan_head_before: b81e87abd81f9b7d0ce57f6db890117eea53c5e1
plan_head_after: aa5d13dbb7c064ccc5653887f4ac7b6e9dd33e62
actuals:
  tokens: 14600   # chars/4 over the diff b81e87a..HEAD (src and tests)
  tasks: 3
  commits: 6
metrics:
  completed: 2026-10-14
---

# Phase quick-261014-nnl Plan 03: Terminal-settlement tracer, OPEN side and funding clip Summary

A case with the optional `terminal_settlements` key now closes an OPEN position of the declared symbol at exactly T at the adverse bound (LONG at price_lower, SHORT at price_upper), books it as one SETTLEMENT exit with the exit fee and zero slippage, cancels a RESTING plan with SETTLEMENT_CANCEL, and stops funding coverage at T; a case without the key runs through the old code paths unchanged.

## Task results

| Task | Name | Commits | Result |
|------|------|---------|--------|
| 1 | Tracer: OPEN LONG settled at T through case, engine, lifecycle, records | 0428f19 (RED), 65d0746 (GREEN) | RED: ImportError at collection; GREEN: tracer, empty-tuple and vocabulary tests pass |
| 2 | OPEN-side semantics, RESTING branch, case refusals | 2959a14 (RED), 8be45d9 (GREEN) | RED: resting-cancel test fails; GREEN: every test in the file passes |
| 3 | Funding clip, engine wiring, design test 4 | 94bcab0 (RED), aa5d13d (GREEN) | RED: 8 failures (missing keyword); GREEN: 11 tests pass |

## What was built

- `semantics.py`: `EXIT_SETTLEMENT` (added to `EXIT_KINDS`), `SETTLEMENT_CANCEL` (added to `ENTRY_KINDS`), `NO_TRADE_TERMINAL`, the two terminal vocabulary strings, `SETTLEMENT_NOTE_PREFIX`. `SIMULATOR_SEMANTICS_VERSION` stays 2.0.0.
- `case.py`: `terminal_settlements` in `OPTIONAL_KEYS`, frozen `TerminalSettlementRow`, `_parse_terminal_settlements` (non-empty list, exactly six string keys, symbol declared and unique, T UTC minute-aligned strictly inside the data window, canonical decimal text, 0 < lower < upper, the two vocabulary strings), `ParsedCase.terminal_settlements` as the last field with default `()`.
- `lifecycle.py`: `settle_at_terminal`; OPEN builds an `ExitLeg(EXIT_SETTLEMENT, bound by side, remaining quantity, T)` through `_apply_leg` and appends the fixed note (no trailing mark span); RESTING goes through `cancel_plan(SETTLEMENT_CANCEL)` and appends the fixed RESTING note; `SETTLEMENT_CANCEL` joined `_CANCEL_KINDS`.
- `records.py`: `_exit_slippage_rate` returns zero for SETTLEMENT; docstrings name it.
- `engine.py`: `self.terminals`; in `_process_window`, for a declared symbol with `advanced_to < T <= window_end`, `advance(end=T)`, then `settle_at_terminal`, events concatenated before the `final` branch and before `_push_funding`; `_push_funding` passes `terminal_at_utc`; `_funding_slice` clips `high` to T for declared symbols.
- `funding.py`: keyword-only `terminal_at_utc=None` on `check_funding_coverage` and `funding_events`; with a value the loaded end is `min(loaded_end, T)` and any own row at or after T raises `FundingCoverageError`.

## Verification

- `pytest tests/test_backtest_terminal_settlement.py tests/test_backtest_terminal_funding.py`: 59 passed.
- Existing engine, lifecycle, records, funding and paper fill tests pass unedited (`tests/test_backtest_engine.py`, `test_backtest_lifecycle.py`, `test_backtest_records.py`, `test_backtest_funding.py`, `test_paper_shadow_fill.py`).
- Whole suite `pytest -m "not docker"` (including the AST purity and no-float guards): no failure and no error; the expected DB-dependent tests skip without `TEST_DATABASE_URL`. The repository's `addopts` carry `-q`, so the run printed no final count line.
- `mypy src`: no issues in 185 files. `ruff check`: clean. `ruff format --check`: clean.
- `git diff --quiet HEAD -- src/paper tests/test_backtest_funding.py tests/test_paper_shadow_fill.py`: clean. `git diff --name-status b81e87a HEAD` shows only the six `src/backtest` modifications and the two added test files; no deletions; no existing test file touched; nothing under params/, src/paper/, docs/, .planning/ (apart from this summary), .gsd/ or package files.
- Hand oracles pinned in the tests: LONG realized_pnl -96.1525, SHORT -106.0525, TP1 remainder -28.68825; booking totals equal record realized_pnl in all three.

## Deviations from Plan

1. [Sequencing] The case refusals and all of the OPEN-side behaviour already existed after Task 1's GREEN commit (the parser was written whole, as the plan's Task 1 action describes). Task 2's RED commit therefore contains one failing test (the RESTING cancel) instead of RESTING plus refusals; the other new Task 2 tests passed on first run, which is evidence the Task 1 build was complete rather than a skipped RED.
2. [Process] For Task 3 the implementation was written before its tests by mistake; to keep the history RED then GREEN the two source files were set aside, the tests committed and shown failing (8 failures, missing keyword), and the files restored byte for byte for the GREEN commit. No `git stash` was used.
3. [Naming] Test 4b is `test_last_row_0800_terminal_0900_position_open_at_terminal_is_covered_funding_stops` (the planned name does not fit the 100-column limit); it asserts both coverage and that funding stops at T.
4. [Scope] `settle_at_terminal` also validates `kind` and `recorded_evaluation` against the two constants (ValueError), beyond the plan's list, so the pure function cannot write a note for an unknown evidence kind. Task 3 also added two tests of the pure funding functions beyond the listed names (charge only rows before T; hole before T with the keyword).
5. [Judgement] Engine RESTING-at-T interplay (`window.dropped`, DAILY_STOP) is not exercised in the engine here (plan 04); the hook calls the pure function for any phase, and the RESTING pure behaviour is tested at the lifecycle level only.
6. The branch is `develop`, which the generic executor protected-branch assertion lists; committing there was directed by the caller and the plan, on the main tree with no worktree.

No auto-fix rules triggered. No stubs. No threat flags beyond the plan's threat model.

## Not done (by scope)

Plans 02 and 04-10, `window.dropped`, the no-plan rule, data-after-T checks for bars and minutes, `settlement_count`, consumers (report, feasibility, analytics), manifest and runner, version bump, protocol text, `holdout_consumed.json`, ROADMAP and STATE updates.

## Self-Check: PASSED

Created files exist (`tests/test_backtest_terminal_settlement.py`, `tests/test_backtest_terminal_funding.py`), the six commits are present in `git log`, and `commits: 6` was measured with `git rev-list --count` from the persisted ledger.
