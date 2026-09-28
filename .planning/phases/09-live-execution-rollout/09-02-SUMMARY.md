---
phase: 09-live-execution-rollout
plan: "02"
subsystem: execution
tags: [tdd, mode-branch, partial-fill, fill-monitor, protective-sizing, idempotent-folding]
dependency_graph:
  requires:
    - phase: 09-01
      provides: execution-manager, placement-surface, sdk-17.4.0-verified
  provides:
    - size-protectives-to-filled-qty
    - quantize-protective-qty
    - fold-fills
    - protective-template-dataclass
    - protective-sizing-dataclass
    - fill-event-dataclass
    - current-position-view-dataclass
    - folded-position-view-dataclass
    - entry-without-protective-divergence
  affects:
    - 09-03
    - 09-04
tech-stack:
  added: []
  patterns: [mode-branch-protective-sizing, idempotent-fill-folding, duck-typed-field-reads, fail-closed-quantization]
key-files:
  created:
    - src/execution/fill_monitor.py
    - tests/test_execution_modes.py
    - tests/test_execution_partials.py
    - tests/fixtures/phase9/mode_branches/one_way/input.json
    - tests/fixtures/phase9/mode_branches/one_way/expected.json
    - tests/fixtures/phase9/mode_branches/hedge/input.json
    - tests/fixtures/phase9/mode_branches/hedge/expected.json
    - tests/fixtures/phase9/partial_fills/input.json
    - tests/fixtures/phase9/partial_fills/expected.json
  modified:
    - src/execution/placement.py
decisions:
  - "Mode-branch protective sizing: one-way SL close-all + TP1 qty+reduceOnly + TP2 close-all; hedge same legs + positionSide LONG/SHORT with reduceOnly omitted everywhere (D-02, EXECUTION_SPEC §5)"
  - "Protective quantities derive from actual filled quantity, never planned quantity, with Decimal floor-to-stepSize quantization and min-qty/notional fail-closed gates (D-02)"
  - "Fill monitor keys idempotently by (order_id, exchange_trade_id) mirroring the FillRow unique constraint precedent (STATE.md 03-04 decision)"
  - "Entry-without-protective surfaces as ENTRY_WITHOUT_PROTECTIVE divergence for the Phase-8 reconciler SAFE_MODE composition; the monitor never places rescue protection per D-02"
  - "Duck-typed field reads in fold_fills accept both attribute-style objects (FillEvent dataclass) and dict-style payloads (test fixture format) — mirrors src/reconcile/compare.py pattern"
key-decisions:
  - "ProtectiveSizing and FoldedPositionView are frozen dataclasses with __post_init__ guards enforcing is_no_trade/leg-population invariants"
  - "quantize_protective_qty mirrors src/risk/quantization.py gate order: floor to stepSize → min_qty reject → notional reject → EXCHANGE_CONSTRAINT on zero/negative inputs"
  - "FoldedPositionView.position_amt = current_position_view.position_amt + filled_quantity (the new position after folding)"
patterns-established:
  - "Pattern: Mode-branch protective sizing — one branch per position mode with mode-correct parameter matrix (closePosition/reduceOnly/positionSide rules)"
  - "Pattern: Idempotent fill folding — keyed by (order_id, exchange_trade_id), sorted by (symbol, order_id, trade_id), deterministic across runs"
  - "Pattern: Duck-typed field reads — _get_field helper accepts both attribute objects and dict payloads for test fixture compatibility"
requirements-completed: [EXEC-01]
coverage:
  - id: D1
    description: "size_protectives_to_filled_qty sizes protective legs to actual filled quantity with mode-correct parameters (one-way vs hedge)"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: tests/test_execution_modes.py#test_one_way_full_fill_yields_close_all_sl_tp1_qty_reduce_only_tp2_close_all
        status: pass
      - kind: unit
        ref: tests/test_execution_modes.py#test_one_way_partial_fill_sizes_all_legs_to_filled_qty
        status: pass
      - kind: unit
        ref: tests/test_execution_modes.py#test_hedge_full_fill_yields_position_side_no_reduce_only
        status: pass
      - kind: unit
        ref: tests/test_execution_modes.py#test_sub_minimum_filled_qty_returns_fail_closed_rejection
        status: pass
    human_judgment: false
  - id: D2
    description: "fold_fills folds fill events idempotently to a single deterministic position view"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: tests/test_execution_partials.py#test_out_of_order_fills_fold_to_same_view_as_in_order
        status: pass
      - kind: unit
        ref: tests/test_execution_partials.py#test_replayed_fills_count_exactly_once
        status: pass
      - kind: unit
        ref: tests/test_execution_partials.py#test_folded_view_sorts_deterministically
        status: pass
      - kind: unit
        ref: tests/test_execution_partials.py#test_entry_without_protective_yields_divergence
        status: pass
    human_judgment: false
  - id: D3
    description: "Purity: no float(), no Binance SDK / SQLAlchemy / Pydantic / Polars imports in execution core"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: tests/test_execution_modes.py#test_placement_module_has_no_float_in_math
        status: pass
      - kind: unit
        ref: tests/test_execution_modes.py#test_placement_module_does_not_import_binance_sdk
        status: pass
      - kind: unit
        ref: tests/test_execution_partials.py#test_fill_monitor_module_purity
        status: pass
    human_judgment: false
metrics:
  duration: ~25min
  completed_date: 2026-09-29
  tasks: 3
  commits: 3
status: complete
actuals:
  tokens: 12969
  tasks: 3
  commits: 3
---

# Phase 9 Plan 2: Mode-Correct Protective Sizing + Idempotent Fill Folding Summary

## One-liner

TDD feature: mode-correct protective sizing to filled quantity (one-way vs hedge) with idempotent fill-event folding keyed by (order_id, exchange_trade_id), plus ENTRY_WITHOUT_PROTECTIVE divergence for the Phase-8 reconciler SAFE_MODE path.

## Performance

- **Duration:** ~25min
- **Started:** 2026-09-29T00:30:00Z
- **Completed:** 2026-09-29T00:55:00Z
- **Tasks:** 3
- **Files modified:** 10 (2 source, 2 test, 6 fixture)

## Accomplishments

- `size_protectives_to_filled_qty` sizes protective legs to actual filled quantity with mode-correct parameters: one-way SL close-all + TP1 qty+reduceOnly + TP2 close-all; hedge same legs + positionSide LONG/SHORT with reduceOnly omitted everywhere
- `quantize_protective_qty` floors to stepSize then checks min_qty and min_notional with first-failure-wins reason codes mirroring `src/risk/quantization.py`
- `fold_fills` folds fill events idempotently keyed by (order_id, exchange_trade_id) to a single deterministic position view sorted by (symbol, order_id, trade_id)
- Entry-without-protective surfaces as `ENTRY_WITHOUT_PROTECTIVE` divergence for the Phase-8 reconciler SAFE_MODE composition; the monitor never places rescue protection per D-02
- Duck-typed field reads accept both attribute-style objects (FillEvent dataclass) and dict-style payloads (test fixture format)
- 8 byte-exact golden fixtures under `tests/fixtures/phase9/mode_branches/` and `tests/fixtures/phase9/partial_fills/`

## Task Commits

Each task was committed atomically:

1. **Task 1: RED mode-branch and partial-fill failing tests plus fixtures** - `b92778f` (test)
2. **Task 2: GREEN protective sizing to filled quantity in both modes** - `ee8fd24` (feat)
3. **Task 3: GREEN idempotent fill monitor folding to a single position view** - `d904441` (feat)

## Files Created/Modified

- `src/execution/placement.py` — Added `ProtectiveTemplate`, `ProtectiveSizing` frozen dataclasses; `quantize_protective_qty` helper; `size_protectives_to_filled_qty` function with mode-branch logic
- `src/execution/fill_monitor.py` — New module: `FillEvent`, `CurrentPositionView`, `FoldedPositionView` frozen dataclasses; `fold_fills` function with idempotent keying and deterministic sorting; `ENTRY_WITHOUT_PROTECTIVE` divergence reporting
- `tests/test_execution_modes.py` — 6 tests covering one-way full/partial fill, hedge full fill, sub-minimum rejection, and purity checks
- `tests/test_execution_partials.py` — 5 tests covering out-of-order folding, replay idempotency, deterministic sort, entry-without-protective divergence, and purity checks
- `tests/fixtures/phase9/mode_branches/{one_way,hedge}/{input,expected}.json` — Byte-exact golden fixtures for mode-branch matrices
- `tests/fixtures/phase9/partial_fills/{input,expected}.json` — Byte-exact golden fixture for partial-fill folding

## Decisions Made

- **Mode-branch protective sizing**: one-way SL close-all + TP1 qty+reduceOnly + TP2 close-all; hedge same legs + positionSide LONG/SHORT with reduceOnly omitted everywhere (D-02, EXECUTION_SPEC §5)
- **Protective quantities derive from actual filled quantity**, never planned quantity, with Decimal floor-to-stepSize quantization and min-qty/notional fail-closed gates (D-02)
- **Fill monitor keys idempotently by (order_id, exchange_trade_id)** mirroring the FillRow unique constraint precedent (STATE.md 03-04 decision)
- **Entry-without-protective surfaces as ENTRY_WITHOUT_PROTECTIVE divergence** for the Phase-8 reconciler SAFE_MODE composition; the monitor never places rescue protection per D-02
- **Duck-typed field reads** in fold_fills accept both attribute-style objects (FillEvent dataclass) and dict-style payloads (test fixture format) — mirrors `src/reconcile/compare.py` pattern
- **ProtectiveSizing and FoldedPositionView are frozen dataclasses** with `__post_init__` guards enforcing is_no_trade/leg-population invariants
- **quantize_protective_qty mirrors src/risk/quantization.py gate order**: floor to stepSize → min_qty reject → notional reject → EXCHANGE_CONSTRAINT on zero/negative inputs
- **FoldedPositionView.position_amt = current_position_view.position_amt + filled_quantity** (the new position after folding)

## Deviations from Plan

None — plan executed exactly as written.

## Threat Mitigations Applied

| Threat ID | Mitigation | Test |
|-----------|------------|------|
| T-9-05 | Idempotent keying on order id plus exchange trade id mirroring the FillRow unique precedent; replayed events counted once; deterministic sorted view | `test_replayed_fills_count_exactly_once`, `test_folded_view_sorts_deterministically` |
| T-9-06 | Hedge branch omits reduceOnly everywhere and forbids close-all on BUY-in-LONG / SELL-in-SHORT; mode suite asserts both branches | `test_hedge_full_fill_yields_position_side_no_reduce_only` |
| T-9-07 | Adapter-side assertion plus placement None-quantity convention: closePosition true never combined with quantity or reduceOnly | `test_one_way_full_fill_yields_close_all_sl_tp1_qty_reduce_only_tp2_close_all` |
| T-9-08 | Entry-without-protective yields divergence for reconciler SAFE_MODE plus HIGH alert; sweeper stays cancel-only and never places rescue protection | `test_entry_without_protective_yields_divergence` |

## Verification

- `uv run --python 3.13 pytest tests/test_execution_modes.py tests/test_execution_partials.py tests/test_execution_manager.py -q` → 18 passed
- `uv run ruff check src/execution/placement.py src/execution/fill_monitor.py tests/test_execution_modes.py tests/test_execution_partials.py` → All checks passed
- `grep float( src/execution/placement.py src/execution/fill_monitor.py` → zero matches
- `grep -E "binance_sdk|sqlalchemy|pydantic|polars" src/execution/fill_monitor.py` → zero matches
- Double-run determinism: `test_folded_view_sorts_deterministically` asserts byte-identical views across runs

## Self-Check

- [x] All 3 tasks executed
- [x] Each task committed individually with proper format (test/feat)
- [x] No deviations from plan
- [x] 18 tests pass (6 mode + 5 partials + 7 manager)
- [x] Ruff clean on all touched files
- [x] No float() in execution core
- [x] No Binance SDK / SQLAlchemy / Pydantic / Polars imports in fill_monitor
- [x] SUMMARY.md created

## Next Phase Readiness

- Mode-correct protective sizing ready for 09-03 (placement-time gates: headroom, DAILY_STOP, stale constraints)
- Idempotent fill folding ready for 09-04 (fill monitor integration with user-data WS + REST tick)
- ENTRY_WITHOUT_PROTECTIVE divergence ready for Phase-8 reconciler SAFE_MODE composition
- All purity contracts maintained: stdlib + Decimal + src/core/_decimal.py only in execution core
