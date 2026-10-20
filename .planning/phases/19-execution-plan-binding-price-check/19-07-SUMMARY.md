---
phase: 19-execution-plan-binding-price-check
plan: 07
subsystem: execution
tags: [take-profit, lot-size, market-lot-size, decimal, one-way, hedge, tdd]
requires:
  - phase: 19-04
    provides: LotFilters and quantize_to_lot (LOT_SIZE x MARKET_LOT_SIZE floor)
provides:
  - TakeProfitSizing (is_no_trade, reason_code, tp1_leg, tp2_leg, tp1_quantity)
  - size_take_profits (live TP1/TP2 sizing from the reconciled position)
affects: [19-16 attach_protectives_to_fill]
tech-stack:
  added: []
  patterns:
    - "New live function pinned to a frozen one by a byte-identical regression on the overlapping input class"
key-files:
  created:
    - src/execution/tp_sizing.py
    - tests/test_tp_sizing.py
  modified: []
key-decisions:
  - "TP1 is floored with quantize_to_lot(market_exit=True), then capped at the position and re-expressed with the exponent of the LOT_SIZE step, so the payload equals the frozen function's (str() identical)"
  - "Gate order copies the frozen sizing: minimum quantity first (MIN_QTY_REJECT, also when no grid point fits), then notional at the snapped TP1 trigger (NOTIONAL_REJECT); no reduce-only exemption, no single-TP fallback (O-03)"
  - "working_type is an argument validated against MARK_PRICE / CONTRACT_PRICE and copied into both legs; the TP1 fraction is an argument validated in (0, 1] (EXEC-07 / O-02: no constant added in src/execution)"
patterns-established:
  - "Purity and no-fraction-constant guards by AST in the test file"
requirements-completed: [EXEC-01, EXEC-07]
status: complete
actuals:
  tokens: 9000
  tasks: 3
  commits: 5
plan_head_before: e48a5b5d503b020b2538ad2ec6fd1898faa91a73
plan_head_after: c160c73c1aa1a88fe6b81175694d37aae00fcf5b
---

# Phase 19 Plan 07: Live Take-Profit Sizing Summary

**`size_take_profits` sizes TP1 from the real reconciled position on the LOT_SIZE x MARKET_LOT_SIZE grid, refuses instead of falling back, and is byte-identical to the frozen `size_protectives_to_filled_qty` on every overlapping input.**

Note on requirements: EXEC-07 is listed in the plan frontmatter but stays Pending (the TP1 fraction stays the D052 item (c) code constant; plan 19-17 adds the note). The orchestrator should not mark it Complete from this plan.

## Accomplishments
- `size_take_profits` (keyword-only): TP1 = floor(position x fraction) on the intersection grid (the coarser step wins), capped at the position, fraction validated in (0, 1]. TP2 is `closePosition=true`, no quantity, no reduceOnly. Triggers snap toward the entry (LONG down, SHORT up) using the frozen `quantize_price` / `tp_trigger_rounding`.
- Refusals: TP1 below the lot or market minimum, or no grid point at or below it, is `MIN_QTY_REJECT`; TP1 x snapped trigger below `min_notional` is `NOTIONAL_REJECT`. Both return no legs. No single-TP fallback (O-03 auto default) and no MIN_NOTIONAL exemption for reduce-only legs.
- One-way: `positionSide BOTH`, TP1 `reduceOnly=true`. Hedge: explicit `positionSide`, `reduceOnly` None on both legs. Tested in separate functions for LONG and SHORT.
- Regression: 2 sides x 2 modes x 3 tick/step pairs x 5 quantities = 60 cases compare `is_no_trade`, `reason_code` and both legs (`==` and `str()` of every value) against the frozen function with `TP1_QUANTITY_FRACTION`; the grid includes accepts and refusals. No difference was found, so no production change was needed after the regression.
- EXEC-07 guard: `TP1_QUANTITY_FRACTION == Decimal("0.5")`, `ProtectiveTemplate` field names unchanged, `tp_sizing.py` has no float constant, no `Decimal("0.5")` and never references `TP1_QUANTITY_FRACTION`. Purity guard: no SDK, `src.backtest`, float(), wall clock.
- `git diff e48a5b5 -- src/execution/placement.py src/backtest/` is empty.

## Task Commits
1. Task 1 tracer: `40f21a9` test (RED), `8789a40` feat (GREEN)
2. Task 2 grid, refusals, Hedge: `a83820e` test (RED), `efdfc13` feat (GREEN)
3. Task 3 regression, EXEC-07 guard, purity: `c160c73` test (passed on first run, no production change)

Tracer gate: `<verify>` (tests plus `mypy src`) re-run after the tracer GREEN commit and passed before expansion.

## Verification (real output)
- `uv run pytest -m "not docker" tests/test_tp_sizing.py tests/test_execution_modes.py tests/test_backtest_exits.py -x`: 138 passed (96 in test_tp_sizing.py)
- `uv run mypy src`: Success, no issues found in 208 source files
- `uv run ruff check`: All checks passed
- `uv run ruff format --check`: 646 files already formatted
- `git diff --exit-code -- src/execution/placement.py src/backtest/`: exit 0

## Deviations from Plan

None - plan executed exactly as written. One test-fixture adjustment during GREEN: the default fake `min_notional` in `make_filters` was lowered to 0.1 because the plan's tracer values (0.005 x 106.00 = 0.53) would otherwise be a legitimate NOTIONAL_REJECT; tests that need the refusal pass `min_notional="5"` explicitly.

## Notes for downstream
- 19-16 must build `LotFilters` through `lot_filters_from_plan_snapshot` and treat `None` as "refuse, do not size from a guess"; it must pass `working_type` from the plan constraint snapshot (D-04) and the TP1 fraction from the backtest semantics constant.
- When the min quantity is not a multiple of the LOT_SIZE step the new function (grid measured from the minimum, per Binance) can differ from the frozen one (grid from zero); this is outside the overlap class and is intentional.
- Open, recorded not decided: O-02 / EXEC-07 / T-04 (fraction stays a code constant, EXEC-07 Pending), O-03 / G4-007 (refusal only; D-27 and the live rule must move together). G4-006 untouched.

## Known Stubs

None.

## Threat Flags

None. T-19-17 mitigated (floor-only, capped at the position, fraction in (0, 1]); T-19-18 mitigated (frozen files untouched, regression); T-19-SC: no package changed.

## Self-Check: PASSED
- src/execution/tp_sizing.py and tests/test_tp_sizing.py exist; commits 40f21a9, 8789a40, a83820e, efdfc13, c160c73 are ancestors of HEAD.
