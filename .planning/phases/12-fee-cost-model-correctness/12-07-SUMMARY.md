---
phase: 12-fee-cost-model-correctness
plan: 07
subsystem: risk-fixtures
tags: [risk, golden-fixtures, parity, cost-model, hand-derived, decimal]
status: complete

requires:
  - phase: 12-06
    provides: size_and_quantize, evaluate_risk with cost_rates / min_stop_distance_rate / max_cost_to_risk
provides:
  - Phase 5 fixtures (11 inputs, 5 sizing expectations) on the shared cost pipeline
  - tests/fixtures/phase5/DERIVATIONS.md (independent hand arithmetic for all cases)
  - tests/test_risk_parity.py running size_and_quantize with numeric comparison
  - tests/test_risk_portfolio.py on the new contract plus a STOP_TOO_TIGHT flow-through test
affects: [12-08, 12-09, 12-11]

actuals:
  tokens: 12100
  tasks: 3
  commits: 5

commits: 5
plan_head_before: 9eb7df990189ca5221043c4c8c34b54dc9127b7c
plan_head_after: b94f555025b7430e5df2d09c6cc279e33edb4228

tech-stack:
  added: []
  patterns:
    - "Fixtures carry literal rates; the pipeline produces the cost (no hand-typed cost per unit)"
    - "Golden expectations compared numerically (Decimal equality) so trailing-zero spelling cannot mask a result"
    - "Expected numbers live in DERIVATIONS.md, computed independently of the code under test"

key-files:
  created:
    - tests/fixtures/phase5/DERIVATIONS.md
  modified:
    - tests/test_risk_parity.py
    - tests/test_risk_portfolio.py
    - tests/fixtures/phase5/*/input.json (11)
    - tests/fixtures/phase5/{happy_path_long,happy_path_short,utilization_reject_edge,min_qty_reject,notional_reject}/expected.json

key-decisions:
  - "Portfolio unit-test helper _size_and_quantize now calls the shared size_and_quantize; candidate risks are hand-derived constants (29.619879, 19.746586, 9.873293, 4.676823) so exact-boundary cap tests stay exact."
  - "New fixture keys are top-level in input.json: candidate_position_side, cost_rates{4 rates, fee_source}, min_stop_distance_rate, max_cost_to_risk, minimum_risk_utilization_after_rounding."

requirements-completed: [RISK-01]

coverage:
  - deliverable: "Eleven Phase 5 fixtures carry rates instead of modeled_costs_per_unit"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_risk_parity.py#test_phase5_pipeline_matches_expected"
        status: pass
      - kind: test
        ref: "tests/test_risk_portfolio.py#test_portfolio_case_matches_expected_json"
        status: pass
  - deliverable: "Hand-derived expectations, numeric comparison"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_risk_parity.py#test_phase5_pipeline_matches_expected"
        status: pass
  - deliverable: "Too-tight stop flows through the portfolio verdict as STOP_TOO_TIGHT"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_risk_portfolio.py#test_evaluate_risk_too_tight_stop_returns_stop_too_tight_verdict"
        status: pass
---

# Phase 12 Plan 07: Phase 5 fixtures and risk suites on the corrected pipeline Summary

The eleven Phase 5 golden cases now derive their cost from four literal rates through the shared pipeline, and every expected number traces to independent arithmetic in DERIVATIONS.md.

## Accomplishments

- **Parity suite**: `_run_pipeline` builds typed arguments and calls `size_and_quantize` (no re-implemented sizing math). Comparison is Decimal equality per numeric field, exact for reason code, decision and `is_no_trade`; a run-twice sha256 test keeps byte determinism.
- **Sizing fixtures** (hand-derived, matched on first run): happy_path_long 0.042 / 49.10892, happy_path_short 0.042 / 49.17108, utilization_reject_edge (equity 117, utilization 0.58786 below 0.6, UTILIZATION_REJECT), min_qty_reject (0.004 below 0.01), notional_reject (0.089 x 100 = 8.9 below 50).
- **Portfolio fixtures**: cluster/aggregate/max-positions cases moved to zone 49995-50005 with stop 49555 (guards pass with margin); daily_stop, stale and uncertain cases keep the happy-path geometry. All six `expected.json` files are unchanged and match.
- **DERIVATIONS.md**: step-by-step arithmetic for all eleven cases, why the old numbers moved (old happy_path_long would lose 57.29 at the adverse fill against a 50 budget), plus the hand-built candidates used by the portfolio unit tests and the too-tight stop case.
- **Portfolio unit tests**: helper runs `size_and_quantize`; guard-clearing geometry (stop 49555); exact-boundary tests use derived open risks (30.253414 for the cluster equality, 70.380121 for the aggregate equality). A mutation check (one micro-unit off) fails both boundary tests, so equality is really exercised. Zero-distance test keeps a genuinely zero distance (LONG stop = entry_max 50100). New test: stop 0.1 percent returns NO_TRADE `STOP_TOO_TIGHT` with `sized` None.

## Verification

- `pytest tests/test_risk_portfolio.py tests/test_risk_parity.py tests/test_risk_cost_guards.py`: 96 passed.
- `ruff check tests/test_risk_parity.py tests/test_risk_portfolio.py`: clean.
- No `modeled_costs_per_unit` key remains in any Phase 5 input.json or in the two test files.

## Deviations from Plan

**1. [Interpretation] Portfolio test call sites.** The plan describes twelve `evaluate_risk` call sites; the file has exactly one (`_run_evaluate_risk`). The other tests build a `SizedResult` through a local `_size_and_quantize` helper that hand-copied `size_position` + `quantize`. I migrated that helper to the shared `size_and_quantize` (matching the plan's guard-clearing-geometry intent). Consequence: the hand-built candidate risks changed from round numbers (20, 30, 10, 5) to derived figures, so the tests' realized-risk assertions and the two exact-boundary open-risk values were updated. Gate assertions (reason codes, daily states) are unchanged.

Tests whose stop was widened (49990 -> 49555): cluster exact pass / one over, aggregate exact pass / one over, first-failure-wins, max-positions, order independence, candidate-risk-added. Default-geometry tests (daily stop, warning, normal, ttl, None loss, unreconciled, envelope guards) needed no geometry change; the zero-distance test moved from stop 50000 (zone mid) to 50100 (LONG sizing entry).

**2. [Process] RED for Tasks 2 and 3 folded.** RED was committed and demonstrated once (`986e370`, all six parity tests failing on missing keys); the fixture edits for all eleven cases were produced by one script, then committed per task. The pre-plan failure of the portfolio file was already recorded in 12-06's summary.

**3. [Process] Master branch.** Commits landed on `master` as directed by the orchestrator (sequential run on the main working tree), consistent with the plan 12-06 history.

None of the numeric expectations were taken from pipeline output: the pipeline matched the DERIVATIONS.md numbers on the first run.

## Known Stubs

None.

## Deferred / out of scope

- `ruff format --check tests/test_risk_portfolio.py` reports pre-existing formatting differences (unchanged lines); not part of this plan's verify.
- Full suite remains red for plans 12-08/12-09 callers (simulator, paper loop, execution manager) as expected.

## Threat Flags

None.

## Self-Check: PASSED

- tests/fixtures/phase5/DERIVATIONS.md, tests/test_risk_parity.py, tests/test_risk_portfolio.py present; commits 986e370, 7a8f823, b722b8d, fbe8bae, b94f555 exist.
