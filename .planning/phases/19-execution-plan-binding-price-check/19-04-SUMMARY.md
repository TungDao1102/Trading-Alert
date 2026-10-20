---
phase: 19-execution-plan-binding-price-check
plan: 04
subsystem: execution
tags: [lot-size, market-lot-size, decimal, emergency-close, tp-quantization, tdd]
requires:
  - phase: 17-06
    provides: PlanConstraintSnapshot (tick, step, min/max quantity, MARKET_LOT_SIZE values)
provides:
  - LotFilters domain value (LOT_SIZE, MARKET_LOT_SIZE, tick, MIN_NOTIONAL as required positive Decimals)
  - next_close_part / plan_close_parts / CloseSplit (valid MARKET close parts, exact Decimal)
  - quantize_to_lot (floor-only, LOT_SIZE or LOT_SIZE x MARKET_LOT_SIZE intersection)
  - lot_filters_from_plan_snapshot (None when any filter is unknown)
affects: [19-07 TP sizing, 19-12 emergency close]
tech-stack:
  added: []
  patterns:
    - "Valid MARKET quantities as one arithmetic progression (CRT intersection of two filters) in exact integer units"
key-files:
  created:
    - src/domain/lot_filters.py
    - src/execution/lot_split.py
    - tests/test_market_lot_split.py
  modified: []
key-decisions:
  - "Tail avoidance is exact: a part is chosen only if the remaining tail is zero or itself a sum of valid parts (closed-form reachability), so a position like 9 with parts in [3,4] closes as 3+3+3 instead of stranding a tail"
  - "A remainder that cannot be closed exactly still yields the largest valid part (closing what can be closed reduces risk); plan_close_parts then reports complete=False and next_close_part gives None at the stuck step"
  - "quantize_to_lot also caps at the grid maximum so the result is always a valid order quantity and never above the input"
patterns-established:
  - "Exchange grid arithmetic on scaled integers, no float and no Decimal context rounding"
requirements-completed: [EXEC-01]
status: complete
actuals:
  tokens: 7450
  tasks: 3
  commits: 6
plan_head_before: 28e7f284da9b142f31b97d68a3400475dd8a2944
plan_head_after: 674150838b0664e613812c83acb62a531ccfb997
---

# Phase 19 Plan 04: Lot Filters and MARKET Close Splitting Summary

**Pure exact-Decimal lot arithmetic: a LotFilters value, a MARKET_LOT_SIZE-aware close part builder proven on an exhaustive fake-filter grid, and a floor-only TP quantizer.**

## Accomplishments
- `LotFilters` (frozen, kw_only): every price/quantity/notional value is a required finite positive Decimal, min <= max for both filters, errors name the field.
- `next_close_part` returns one MARKET part valid under LOT_SIZE and MARKET_LOT_SIZE, never above the remainder, avoiding a sub-minimum tail; `None` when no valid part exists (the caller turns it into SAFE_MODE, per D-16). `plan_close_parts` iterates it into a `CloseSplit(parts, complete)`.
- `quantize_to_lot` floors onto the LOT_SIZE grid, or the intersection with MARKET_LOT_SIZE for a triggered market exit; `lot_filters_from_plan_snapshot` maps `PlanConstraintSnapshot`, None when `max_quantity` or any market-lot value is unknown.
- Exhaustive grid test: 3 steps x 2 market minimums x 3 market maximums x 64 positions (1152 cases, count asserted), validity checked with an independent `is_valid_market_part`, completeness checked against a brute-force reachability DP.

## Task Commits
1. Task 1 tracer: `a339834` test (RED), `6e96c64` feat (GREEN)
2. Task 2 splitting: `ccf706a` test (RED), `f7cb6aa` feat (GREEN)
3. Task 3 quantizer/mapping/purity: `3ccd797` test (RED), `6741508` feat (GREEN)

## Verification (real output)
- `uv run pytest -m "not docker" tests/test_market_lot_split.py tests/test_constraint_snapshot.py -x`: 127 passed
- `uv run mypy src`: Success, no issues in 204 source files
- `uv run ruff check`: All checks passed; `uv run ruff format --check`: 634 files already formatted

## Deviations from Plan
None - plan executed exactly as written. Design additions inside the plan's scope: `quantize_to_lot` caps at the grid maximum (documented), and the splitter uses a closed-form representability test rather than the plan's "reduce by whole steps" loop, because the simple loop strands a tail in cases such as position 9 with parts in [3,4].

## Notes for downstream plans
- `next_close_part` takes explicit filters, so the owner's Q3 policy (live exchangeInfo vs plan-time snapshot) stays a caller choice. A `lot_filters_from_plan_snapshot` result of None must be handled as "cannot build" by plan 19-12.
- Filters in tests are fake; mainnet MARKET_LOT_SIZE values are not verified (research A7, E1 unread).
- `src/execution/placement.py` (frozen for backtest) was not touched.

## Known Stubs
None.

## Threat Flags
None. T-19-10 (explicit None/complete=False) and T-19-11 (floor-only, parts never exceed remainder, grid test) are mitigated.

## Self-Check: PASSED
Files `src/domain/lot_filters.py`, `src/execution/lot_split.py`, `tests/test_market_lot_split.py` exist; commits a339834, 6e96c64, ccf706a, f7cb6aa, 3ccd797, 6741508 are ancestors of HEAD on p19-04.
