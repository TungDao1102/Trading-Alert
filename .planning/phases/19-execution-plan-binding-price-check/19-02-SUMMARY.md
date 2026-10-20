---
phase: 19-execution-plan-binding-price-check
plan: 02
subsystem: execution
tags: [binding, plan-hash, decimal, tick-snap, fail-closed]
status: complete

requires:
  - phase: 04-planner
    provides: "_plan_hash algorithm, TradePlan and Signal entities"
  - phase: 09-execution
    provides: "quantize_price, entry_limit_rounding, sl_trigger_rounding (frozen helpers)"
provides:
  - "Public plan_hash_from_fields in src/core/planner.py, behavior-identical to _plan_hash"
  - "src/execution/binding.py: BoundPlan, BindingVerdict, recompute_plan_hash, bind_plan, check_quantity_bound, check_snapped_geometry, check_working_type, take_profit_levels, PROTECTIVE_WORKING_TYPE and the reason-code constants"
affects: [19-13 manager wiring, 19-16 attach_protectives_to_fill, 19-17 GLOSSARY 9.3]

actuals:
  tokens: 9300
  tasks: 3
  commits: 6
plan_head_before: 28e7f284da9b142f31b97d68a3400475dd8a2944
plan_head_after: 7b04ccdb2f4c422881e9a07b6310e81aee9d99ff

tech-stack:
  added: []
  patterns:
    - "Plain-string reason codes outside RejectionReason, never routed through PlacementGateVerdict (P13)"
    - "First-failure-wins ordered verdict: hash, signal, symbol, side"

key-files:
  created:
    - src/execution/binding.py
    - tests/test_execution_binding.py
  modified:
    - src/core/planner.py
    - tests/test_core_planner.py

key-decisions:
  - "Symbol and side come from the persisted Signal reached by plan.signal_id, never from the caller; plan_hash is unchanged (D051 c)"
  - "Quantity is accepted unchanged or refused; no clipping helper exists (D-02)"
  - "binding.py does not import src.execution.placement: the snap helpers are exercised in tests only, so the module stays dependency-light"

requirements-completed: [APRV-01, APRV-02, EXEC-01, RISK-04]
---

# Phase 19 Plan 02: Plan Binding Core Summary

**Pure binding core: the plan hash is re-derived with the planner's frozen algorithm, symbol and side come from the persisted Signal and are cross-checked against geometry, snapshot, approval and caller, and quantity, snapped geometry and working type each have a named refusal.**

## What was built

- `plan_hash_from_fields` in `src/core/planner.py`: the algorithm moved verbatim into a public function; `_plan_hash` now delegates to it. Hashed field set and key names are unchanged (D051 item c), so every Phase 4 golden test passes untouched. Added to `__all__`.
- `src/execution/binding.py` (pure: stdlib, `src.core.planner`, `src.domain`):
  - `bind_plan(...)` returns a `BindingVerdict`; first failure wins: hash (recomputed vs stored vs callback vs approval request) -> `STALE_SETUP`; signal id, strategy version, parameter set id/hash -> `PLAN_SIGNAL_MISMATCH`; snapshot plan id, snapshot symbol, caller symbol -> `PLAN_SYMBOL_MISMATCH`; Signal direction not LONG/SHORT, geometry-implied side (stop below zone LONG, above SHORT, inside none) or caller side differing -> `PLAN_SIDE_MISMATCH`. On success a `BoundPlan` carries symbol and side from the Signal, entry/exit sides and the approved quantity.
  - `check_quantity_bound` (D-02), `check_working_type` against `PROTECTIVE_WORKING_TYPE = "MARK_PRICE"` (D-04), `check_snapped_geometry` (D-03, G4-020) and `take_profit_levels` (fail-closed parser, ValueError on any missing/non-string/non-finite/non-positive/invalid JSON).
- `tests/test_execution_binding.py`: tracer on real `evaluate()`/`plan()` output for LONG and SHORT; one case per mismatch; first-failure-order tests; quantity and working-type tests; tick grid (0.01, 0.1, 0.5 x three zones x six stop offsets x both sides) asserting both refused and accepted cases exist; take-profit failure grid; AST purity guard with a planted-float negative control.
- `tests/test_core_planner.py`: golden test that the public wrapper equals `_plan_hash` on the three spellings and equals the stored hash of the planner fixture plan.

## Reason-code list for GLOSSARY 9.3 (plan 19-17)

| Code | Meaning |
|------|---------|
| STALE_SETUP (existing RejectionReason) | recomputed, stored, callback or approval-request plan hash disagree |
| PLAN_SIGNAL_MISMATCH | Signal id differs from plan.signal_id, or strategy version / parameter set id / hash differ from the approval |
| PLAN_SYMBOL_MISMATCH | snapshot trade_plan_id, snapshot symbol or caller symbol differs from the Signal |
| PLAN_SIDE_MISMATCH | Signal direction not LONG/SHORT, contradicts the stop geometry, or differs from the caller side |
| QUANTITY_ABOVE_APPROVED | placement quantity above the approved quantity_after_rounding (never clipped) |
| GEOMETRY_INVALID_AFTER_SNAP | after the tick snap the limit left the zone or the stop reached the zone edge / limit |
| WORKING_TYPE_NOT_MARK_PRICE | plan constraint snapshot working type is not MARK_PRICE |

## Commits

Tracer: RED `623c732`, GREEN `9b28ac0`. Task 2: RED `b784858`, GREEN `cadbb84`. Task 3: RED `deadf44`, GREEN `7b04ccd`. No REFACTOR commit was needed.

## Deviations from Plan

None. The plan's files_modified list was respected.

Notes: the plan says binding.py may import `src.execution.placement`; it does not need to, so the import was left out (the purity test still allows it). `_plan_hash` was kept as a thin delegate rather than removed so existing callers and tests are untouched.

## Known Stubs

None.

## Threat Flags

None. No new endpoints, auth paths or schema; T-19-04, T-19-05 and T-19-06 are mitigated by `bind_plan`, the hash re-derivation and `check_quantity_bound`.

## Verification

- `uv run pytest -m "not docker" tests/test_execution_binding.py tests/test_core_planner.py tests/test_execution_price_ticks.py`: passed.
- `uv run mypy src`: no issues (203 files). `uv run ruff check`: all checks passed. `uv run ruff format --check`: 633 files already formatted.

## Self-Check: PASSED

Files exist: src/execution/binding.py, tests/test_execution_binding.py. All six commits are ancestors of HEAD.
