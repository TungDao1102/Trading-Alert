---
phase: 12-fee-cost-model-correctness
plan: 06
subsystem: risk-pipeline
tags: [risk, sizing, cost-guards, adverse-edge, decimal, fail-closed]
status: complete

requires:
  - phase: 12-01
    provides: RejectionReason STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED, glossary entries
  - phase: 12-03
    provides: CostRates, per_unit_round_trip_cost
  - phase: 12-04
    provides: guard threshold registry keys (consumed by callers in wave 4)
provides:
  - src/risk/gating.py size_and_quantize (shared size + guards + quantize step)
  - src/risk/gating.py evaluate_risk with required cost_rates, min_stop_distance_rate, max_cost_to_risk
  - src/risk/cost_guards.py validate_guard_rates, check_cost_guards
  - SizedResult optional cost trail fields (cost, sizing entry, stop distance rate, ratio, fee rates, fee source)
affects: [12-07 (simulator), 12-08 (paper loop / execution manager), 12-09 (test and fixture migration), 12-11 (DECISIONS D046)]

actuals:
  tokens: 9500
  tasks: 2
  commits: 4

commits: 4
plan_head_before: 1635b96af80be1fa222cb44f7c55cf37406e848a
plan_head_after: 0c2ddd63e94b3143c1ac7afc2c962d8d4520cb47

tech-stack:
  added: []
  patterns:
    - "One producer of the cost per unit inside the pipeline; callers pass rates, never a pre-computed cost"
    - "Required, Decimal-only, range-validated guard thresholds (no defaults) so a guard cannot be disabled"
    - "Local structlog import at the lineage call site keeps src/risk module-level purity"

key-files:
  created:
    - src/risk/cost_guards.py
    - tests/test_risk_cost_guards.py
  modified:
    - src/risk/gating.py
    - src/risk/types.py
    - src/risk/sizing.py
    - src/risk/__init__.py

key-decisions:
  - "Sizing entry is the adverse zone edge (LONG entry_max, SHORT entry_min); zone mid remains the quantizer notional reference (supersedes Phase 5 D-02 for risk sizing; pinned as DECISIONS D046 by plan 12-11)."
  - "check_cost_guards is exported from the risk barrel because the barrel already exports helpers (per_unit_round_trip_cost)."
  - "risk.cost_rates lineage fires once per call that reaches the ratio computation (not when size_position already failed closed on zero distance, where no ratio exists)."

requirements-completed: [RISK-01]

coverage:
  - deliverable: "evaluate_risk computes cost itself from CostRates; modeled_costs_per_unit removed"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_risk_cost_guards.py#test_removed_modeled_costs_keyword_raises_type_error"
        status: pass
  - deliverable: "Adverse-edge sizing proven by BTC LONG/SHORT and XRP oracles and worst-case fill test"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_risk_cost_guards.py#test_btc_long_oracle"
        status: pass
      - kind: test
        ref: "tests/test_risk_cost_guards.py#test_worst_case_loss_at_stop_within_budget"
        status: pass
  - deliverable: "STOP_TOO_TIGHT then COST_TO_RISK_EXCEEDED before quantize, exact boundaries"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_risk_cost_guards.py#test_cost_to_risk_boundary_equality_passes"
        status: pass
      - kind: test
        ref: "tests/test_risk_cost_guards.py#test_guards_run_before_quantize"
        status: pass
  - deliverable: "Cost trail on SizedResult and risk.cost_rates / risk.cost_guard lineage events"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_risk_cost_guards.py#test_cost_rates_lineage_event_emitted_once_with_string_values"
        status: pass
---

# Phase 12 Plan 06: Shared risk pipeline cost cutover Summary

The shared risk step now sizes at the adverse edge of the entry zone with a price-aware cost computed inside `evaluate_risk`, rejects too-tight or cost-dominated plans before any quantity is rounded, and records the rates it used.

## Accomplishments

- `size_and_quantize` (new public step): validates side, `CostRates` type and both guard rates, sizes at the adverse zone edge, computes the cost per unit via `per_unit_round_trip_cost`, runs `STOP_TOO_TIGHT` then `COST_TO_RISK_EXCEEDED`, then `quantize` with the zone mid as the notional reference. `evaluate_risk` is that step followed by `check_portfolio`.
- `modeled_costs_per_unit` is gone from `evaluate_risk`; `cost_rates`, `min_stop_distance_rate`, `max_cost_to_risk` are required keywords with no defaults.
- Oracles (independent hand-derived literals) match exactly: BTC LONG 0.035 / 49.10794, BTC SHORT 0.033 / 49.00434, XRP LONG 5750.4 / 49.999728. Loss at the stop for fills at fractions 0, 0.5, 1 of the zone is at most 50; the zone-mid counterfactual (0.038) loses 53.3171920.
- Notional gate reference proven to be the zone mid (min_notional 2102 rejects BTC LONG, 1978 passes BTC SHORT).
- Guard boundaries: 0.003 equality passes, 0.0031 rejects; the ratio literal passes, one ulp below rejects; ordering, before-quantize, zero-distance (`EXCHANGE_CONSTRAINT`), reject shape, verdict shape and lineage events tested.
- `SizedResult` gained seven optional cost-trail fields (default None), validated when present.

## Verification

- `pytest tests/test_risk_cost_guards.py tests/test_risk_sizing.py tests/test_risk_quantization.py`: all pass (72 tests).
- `mypy src/risk`: Success, no issues found in 9 source files.
- `verify_decision_alignment.py glossary`: ALL_PASS glossary.
- `ruff check src/risk tests/test_risk_cost_guards.py`: my files clean. Two pre-existing F841 findings remain in `src/risk/portfolio.py` (lines 312-313, unused locals); the plan requires portfolio.py stay unchanged, so they are deferred (see below).
- `src/risk/quantization.py` and `src/risk/portfolio.py` unchanged since the plan base (`git diff --name-only` empty for both).

## Deviations from Plan

None - plan executed exactly as written.

**Deferred (out of scope, pre-existing):** ruff F841 `warning_threshold_quote` / `stop_threshold_quote` in `src/risk/portfolio.py:312-313`. The plan's acceptance criteria forbid touching portfolio.py; the `ruff check src/risk` verify command therefore reports 2 pre-existing errors even though every file this plan touched is clean.

## Known red (expected until wave 4, plans 12-07/08/09)

Callers still on the removed `modeled_costs_per_unit` contract:

- `src/backtest/simulator.py:807`, `src/paper/loop.py:508`, `src/execution/manager.py:418` (call `evaluate_risk`).
- Tests failing today: `tests/test_risk_portfolio.py` (12: `test_portfolio_case_matches_expected_json` and `test_portfolio_case_byte_identical_across_runs` x6 fixtures), `tests/test_backtest_simulator.py` (13), `tests/test_backtest_experiment.py` (2), `tests/test_execution_manager.py` (15), `tests/test_paper_parity.py` (3). Other possibly affected fixtures/helpers reference the old keyword: `tests/fixtures/phase5/*/input.json`, `tests/phase10_helpers.py`, `scripts/gen_phase6_fixtures.py`, `src/backtest/costs.py`, `src/backtest/experiment.py`.
- Passing: `tests/test_risk_parity.py`, `test_risk_sizing.py`, `test_risk_quantization.py`, `test_cost_per_unit.py`, `test_execution_gates.py`, `test_backtest_report.py`, `test_paper_closed_candle.py` in the scoped run.

## Threat Flags

None. No new network, auth, file or schema surface.

## Known Stubs

None.

## Self-Check: PASSED

- `src/risk/cost_guards.py`, `tests/test_risk_cost_guards.py` exist; commits 4a69e25, d6c94fc, 5cb9147, 0c2ddd6 present.
