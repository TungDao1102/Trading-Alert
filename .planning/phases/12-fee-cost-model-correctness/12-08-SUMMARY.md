---
phase: 12-fee-cost-model-correctness
plan: 08
subsystem: execution
tags: [execution, live-boundary, cost-rates, fail-closed, fixtures]
status: complete

requires:
  - phase: 12-06
    provides: evaluate_risk with cost_rates / min_stop_distance_rate / max_cost_to_risk
provides:
  - Live cost-rate gate in execute_approved_plan (ACCOUNT_MAX only, else NO_TRADE UNCERTAIN_ACCOUNT_STATE)
  - risk_kwargs contract for the live manager on the corrected pipeline
  - Phase 9 placement fixture carrying cost_rates and guard rates
affects: [12-09, 24]

actuals:
  tokens: 6500
  tasks: 2
  commits: 2

commits: 2
plan_head_before: 23868c888fff5e9f2ed076f70312d482297b7cd4
plan_head_after: 5fce621ebd1092d86b31fc40a976716993e69c0a

tech-stack:
  added: []
  patterns:
    - "Live boundary refuses to size from parameter fees: a PARAMETER fee_source is NO_TRADE, never a downgrade"
    - "Removed keywords are rejected explicitly with a TypeError naming the replacement"

key-files:
  created: []
  modified:
    - src/execution/manager.py
    - tests/test_execution_manager.py
    - tests/fixtures/phase9/placement_sequences/input.json

key-decisions:
  - "The legacy modeled_costs_per_unit key is rejected explicitly in the gate (not only by evaluate_risk's own unexpected-keyword error), so it fails before any fee-source decision and with a message that names cost_rates / resolve_live_cost_rates."

requirements-completed: []

coverage:
  - deliverable: "Manager passes the new evaluate_risk contract through; happy path places one entry and one SL leg"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_execution_manager.py#test_happy_path_places_one_entry_and_one_sl_leg"
        status: pass
  - deliverable: "PARAMETER fee source is NO_TRADE UNCERTAIN_ACCOUNT_STATE with zero adapter calls and no risk call"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_execution_manager.py#test_parameter_fee_source_is_no_trade_before_risk_and_adapter"
        status: pass
  - deliverable: "Missing, wrong-typed or legacy cost keywords raise TypeError before any adapter call"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_execution_manager.py#test_missing_or_wrong_typed_cost_rates_raises_type_error"
        status: pass
      - kind: test
        ref: "tests/test_execution_manager.py#test_legacy_modeled_costs_per_unit_keyword_raises_type_error"
        status: pass
---

# Phase 12 Plan 08: Live manager cost-rate gate Summary

The live execution manager now consumes the corrected `evaluate_risk` contract and refuses to size a real order from anything but account-sourced fee rates (D-11, D-12).

## Accomplishments

- **Task 1 (tracer)**: The Phase 9 placement fixture drops `modeled_costs_per_unit` and gains a `cost_rates` block (0.0005 fee each way, 0.0001 / 0.0003 slippage, `fee_source` ACCOUNT_MAX) plus `min_stop_distance_rate` 0.003 and `max_cost_to_risk` 0.15. `_build_risk_kwargs` builds a `CostRates` through a new `_build_cost_rates` helper. The happy path still places one entry (LIMIT, GTC, price 101.00) and one SL leg, and now also asserts the hand-derived quantity 2.415 (sizing entry 102, stop 98, cost 0.1396, floor(10 / 4.1396) at step 0.001). The `execute_approved_plan` docstring lists the new risk_kwargs keys. RED was demonstrated against the pre-change test and fixture in a scratch copy: `TypeError: evaluate_risk() got an unexpected keyword argument 'modeled_costs_per_unit'`, the intended kwarg error.
- **Task 2**: A rate gate sits immediately before the risk pipeline, after the binding, enablement and SAFE_MODE gates. It raises `TypeError` for the removed `modeled_costs_per_unit` key and for a missing or non-`CostRates` `cost_rates`, and returns NO_TRADE `UNCERTAIN_ACCOUNT_STATE` when `fee_source` is not ACCOUNT_MAX. Docstring gate list renumbered (7 gates). The manager diff versus the plan base is the import, the docstring and this gate only.
- **Tests**: three new tests. The PARAMETER-source test monkeypatches `evaluate_risk` to fail if invoked and asserts zero adapter calls. The other two cover missing / dict-typed `cost_rates` and the legacy keyword, each asserting zero adapter calls.

## Verification

- `pytest tests/test_execution_manager.py tests/test_execution_attach.py tests/test_execution_gates.py tests/test_execution_adapter_contract.py`: all pass (70 tests).
- `mypy src/execution/manager.py`: no issues. `ruff check` on the manager and its test: clean.
- Tracer gate: end-to-end verify re-run after the tracer commit, passes; expansion continued.

## Deviations from Plan

**1. [Rule 2 - Missing critical] Explicit legacy-key check.** The plan lists the removed keyword as a TypeError case; without an explicit check it would only fail inside `evaluate_risk`, and only if the fee source were ACCOUNT_MAX (a PARAMETER source would return NO_TRADE first and hide the stale caller). The gate checks it up front.

**2. [Process] RED for Task 1 is not a committed failing state.** Because `evaluate_risk` already accepts the new contract (12-06), the fixture and builder migration passes as soon as it lands; RED was shown against the old test and fixture in a scratch copy, then Task 1 committed green. Task 2 RED was observed in the working tree (two failing tests) before the gate was written.

**3. [Process] Master branch.** Commits landed on `master` as directed (sequential run on the main working tree).

## Known Stubs

None.

## Deferred / out of scope

- The full suite is still red for 12-09's callers (simulator, paper loop); not touched here.
- The commission adapter method and refresh loop stay in Phase 24 (D-13).
- REQUIREMENTS.md RISK-01 left as is (this plan is not the last to claim it).

## Threat Flags

None. T-12-23 (live order sized from parameter fees) is mitigated by the new gate and its tests.

## Self-Check: PASSED

- src/execution/manager.py, tests/test_execution_manager.py, tests/fixtures/phase9/placement_sequences/input.json present; commits eec6397 and 5fce621 exist.
