---
phase: 19-execution-plan-binding-price-check
plan: 03
subsystem: execution
tags: [pre-placement, mark-price, goodTillDate, invalidation, fail-closed, tdd]
requires:
  - phase: 14
    provides: "backtest invalidation_level / is_invalidated (parity oracle, test-only import)"
provides:
  - "Pure pre-placement refusals: evaluate_pre_placement plus check_plan_status, check_invalidation, check_remaining_validity, check_symbol_free, check_mark_price, check_position_mode"
  - "good_till_date_ms and GTD_MIN_AHEAD_SECONDS (Binance goodTillDate floor) for plans 19-05 and 19-15"
affects: [19-05, 19-13, 19-15]
tech-stack:
  added: []
  patterns: ["keyword-only first-failure-wins pure checks returning a reason code or None"]
key-files:
  created: [src/execution/pre_placement.py, tests/test_pre_placement.py]
  modified: []
key-decisions:
  - "Status check is a deny-list (EXPIRED, INVALIDATED, SUPERSEDED refuse) so an executed APPROVED plan is never contradicted (D-09, F5)"
  - "PLAN_INVALIDATED_BEFORE_PLACEMENT is a new string distinct from RejectionReason.INVALIDATED; the enum keeps 20 members (D-08)"
  - "Remaining validity is measured to the floored goodTillDate second and must exceed both the owner minimum and 600 s plus the clock margin"
  - "Position-mode strings are duplicated as private constants (no manager import) and pinned equal to src.execution.manager by a test"
patterns-established:
  - "Backtest parity pinned in the test only; src.execution never imports src.backtest"
requirements-completed: [EXEC-01, RISK-04]
status: complete
commits: 6
plan_head_before: 28e7f284da9b142f31b97d68a3400475dd8a2944
plan_head_after: 77d3885a0a03a94fe016e35cfba8c2a19dbfdbc5
actuals:
  tokens: 9650
  tasks: 3
  commits: 6
completed: 2026-10-19
---

# Phase 19 Plan 03: Pre-placement refusals Summary

**Pure, ordered pre-placement verdict (status, invalidation, validity with the Binance 600 s goodTillDate floor, symbol free, mark price) plus a separate hedge-mode refusal, all fail closed and parity-pinned to the backtest invalidation rule.**

## Performance

- **Tasks:** 3 (1 tracer, 2 auto TDD), each with a RED and a GREEN commit
- **Files:** 2 created (`src/execution/pre_placement.py`, `tests/test_pre_placement.py`)

## Accomplishments

- `evaluate_pre_placement(PrePlacementInputs)` returns `None` or the first reason in the fixed order status -> invalidation -> validity -> symbol free -> mark price; a test makes each of the five fail in turn and a second test pins that the earliest failing check wins.
- `check_mark_price`: LONG mark <= stop (SHORT >=) is MARK_PRICE_CROSSED_STOP, a mark outside the inclusive zone is MARK_PRICE_OUTSIDE_ZONE, and a missing, future-dated or too-old reading or an unset age bound is MARK_PRICE_UNAVAILABLE. Age is whole milliseconds from timedelta floor division (no float).
- `check_remaining_validity` measures to the floored `good_till_date_ms` second and refuses at or below the owner minimum or at or below 600 s + margin; an unset owner minimum is LIMITS_NOT_CONFIGURED.
- `check_invalidation` re-implements the CANDLE_CLOSE rule; a 66-triple (close, level, side) grid equals `src.backtest.entry.invalidation_level` / `is_invalidated`.
- `check_symbol_free` (unprotected anywhere, position, unreadable order state, open order) and `check_position_mode` (HEDGE refused, unknown raises).
- RISK-04 test (`-k risk04`) scans every public signature and the inputs fields for loss, pnl, target, drawdown, streak; a purity test enforces stdlib + `src.domain` imports only, no float constructor, no wall clock.

## Task Commits

1. Task 1 tracer: `a88a573` test (RED), `6a9ed4a` feat (GREEN)
2. Task 2: `c8aa60c` test (RED), `2e6b1c3` feat (GREEN)
3. Task 3: `c9bf1a1` test (RED), `77d3885` feat (GREEN)

## Recorded dispositions (not decided here)

- **Q2:** only mark price is read; last price (`/fapi/v1/ticker/price`) deliberately not added because the stop triggers on MARK_PRICE (D037).
- **Q6:** the latest closed strategy-bar close is a required injected value (`None` refuses INVALIDATION_INPUT_UNAVAILABLE); its producer is Phase 24.
- **Q7:** the exchange open-order snapshot is the authority; an intent-store cross-check needs a new store query and is not built.
- **O-04 (numbers):** `min_remaining_validity_seconds`, `max_mark_price_age_ms` and `gtd_clock_margin` are injected by the caller; no value is chosen here. `GTD_MIN_AHEAD_SECONDS = 600` is the structural Binance constant (New Order page, research B6), documented as separate from the owner limits. Assumption A1 (the page's "current time" is server time) remains covered only by the margin argument.

## Deviations from Plan

None - plan executed as written. Two notes: the Task 1 "stubs" were realised as the composite initially calling only `check_mark_price` and gaining each check in the task that owns it (no stub function survives). The full `pytest -m "not docker"` suite exceeded the shell timeout and was not completed; instead the execution, placement, gates, manager, ast-guard and backtest-purity test files were run and passed.

## Known Stubs

None.

## Threat Flags

None. The module adds no network, auth or file surface.

## Verification

- `uv run pytest -m "not docker" tests/test_pre_placement.py tests/test_backtest_entry.py -x`: passed
- `uv run mypy src`: Success, no issues in 203 source files
- `uv run ruff check`: all checks passed
- `uv run ruff format --check`: 633 files already formatted

## Self-Check: PASSED

- src/execution/pre_placement.py and tests/test_pre_placement.py exist; all six task commits are ancestors of HEAD on p19-03.
