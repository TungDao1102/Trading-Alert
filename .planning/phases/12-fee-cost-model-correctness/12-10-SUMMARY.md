---
phase: 12-fee-cost-model-correctness
plan: 10
subsystem: risk-tests
tags: [property-test, mutation-check, cost-parity, decimal, risk-budget]
status: complete

requires:
  - phase: 12-05
    provides: resolve_live_cost_rates, AccountCommission
  - phase: 12-06
    provides: evaluate_risk with cost_rates and the two cost guards
  - phase: 12-07
    provides: shared cost producer wired into the registry and cost model
  - phase: 12-09
    provides: simulator and paper loop on the shared cost path
provides:
  - Grid property test proving loss at the stop, fees and slippage included, is at most allowed_risk (tolerance zero)
  - Old-formula mutation check that fails on BTC and XRP and a vacuity guard on the harness
  - Cross-call-site cost parity and one-producer delegation tests
affects: [12-11]

actuals:
  tokens: 7700
  tasks: 3
  commits: 3

commits: 3
plan_head_before: 648a267183d749dc4f644b8beef6453be20976e4
plan_head_after: 1df545b8bc08366150957af1ab1743a7e9069f2c

tech-stack:
  added: []
  patterns:
    - "Loss arithmetic in tests is plain Decimal with literal rates and never calls the producer, modeled_costs_per_unit or _apply_costs"
    - "A mutation harness raises a vacuity error when it finds no violation, and a test feeds it a correct quantity to prove that path"
    - "Spy wrappers on the module-level evaluate_risk name compare full kwargs between the simulator and the paper loop"

key-files:
  created:
    - tests/test_sl_loss_property.py
    - tests/test_cost_parity.py
  modified: []

key-decisions:
  - "Zero loss tolerance: quantity is floored to the step and every product is exact at the default Decimal precision for these magnitudes, so no slack is needed or granted."
  - "The vacuity proof is a permanent test (harness fed the corrected quantity must raise 'vacuous') instead of a one-off temporary edit."

requirements-completed: [RISK-01, BKTS-01]

coverage:
  - deliverable: "Loss at the stop within allowed_risk for every accepted plan over the 60-plan grid (BTC, ETH, XRP; five widths; both sides; equity 10000 and 800; five fill fractions), tolerance zero"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_accepted_plans_never_lose_more_than_allowed_risk_at_the_stop"
        status: pass
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_corrected_xrp_long_quantity_at_the_narrowest_width"
        status: pass
  - deliverable: "The old rate-sum formula violates the budget on BTC and XRP through the same harness, and its cost term is wrong in both directions"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_old_formula_violates_the_budget_on_btc_and_xrp"
        status: pass
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_old_cost_term_ran_in_both_directions"
        status: pass
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_harness_reports_vacuity_when_fed_a_correct_quantity"
        status: pass
  - deliverable: "STOP_TOO_TIGHT below 0.3 percent, COST_TO_RISK_EXCEEDED at 0.4 to 0.7 percent, pass from 0.8 percent, both sides, BTC and XRP"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_widths_below_the_stop_floor_are_stop_too_tight"
        status: pass
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_widths_past_the_floor_but_costly_are_cost_to_risk_exceeded"
        status: pass
      - kind: test
        ref: "tests/test_sl_loss_property.py#test_width_0_8_percent_passes_both_guards"
        status: pass
  - deliverable: "Producer, backtest helper and evaluate_risk agree (83.0840, 0.000695); simulator and paper pass identical kwargs; both wrappers delegate to one producer; live rates match parameter rates below and exceed them above"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_cost_parity.py#test_four_way_equality_btc_long"
        status: pass
      - kind: test
        ref: "tests/test_cost_parity.py#test_four_way_equality_xrp_long"
        status: pass
      - kind: test
        ref: "tests/test_cost_parity.py#test_simulator_and_paper_call_evaluate_risk_with_identical_arguments"
        status: pass
      - kind: test
        ref: "tests/test_cost_parity.py#test_patching_the_producer_changes_both_wrappers"
        status: pass
      - kind: test
        ref: "tests/test_cost_parity.py#test_account_taker_above_parameter_raises_the_recorded_fee_and_never_grows_the_size"
        status: pass
---

# Phase 12 Plan 10: SL-loss property test and cost parity Summary

The stop-loss-within-budget invariant is now a permanent 60-plan Decimal grid test that includes the low-price XRP case, and it fails on the old rate-sum formula. A second module enforces that the producer, the backtest helper, `evaluate_risk`, the simulator and the paper loop share one cost path.

## Accomplishments

- **Task 1 (tracer)**: `stop_loss_exit_loss` is written once with literal rates. It returns 49.10794 for the earlier BTC LONG edge geometry (60100 / 58780 / 0.035). The single BTC LONG grid point (zone 59940-60060, width 2.2 percent, stop 58738.68) passes through `evaluate_risk`, the loss at five fills stays within 50, and the edge loss equals `quantity x risk_per_unit` and the recorded `realized_risk`. Tracer gate (auto mode): verify re-run, passed, expansion continued.
- **Task 2**: 60 plans (3 prices x 5 widths x 2 sides x 2 equities), five fill fractions each. Every accepted plan has loss at most `allowed_risk` with `LOSS_TOLERANCE = 0`; the pipeline quantity also equals an independently floored `allowed_risk / risk_per_unit`. All 60 plans were accepted (at least 24 required, at least one per price and side); no rejection reason falls outside the three quantity reasons. Flooring is material for BTC/ETH; XRP LONG at 0.8 percent and equity 10000 sizes 10634.9. Guard regions hold on both sides for BTC and XRP: 0.1, 0.2, 0.29 percent give STOP_TOO_TIGHT; 0.4, 0.6, 0.7 percent give COST_TO_RISK_EXCEEDED; 0.8 percent passes. The old formula (`|zone mid - stop| + 0.0011`) through the same harness gives BTC LONG 0.02 -> 0.043 losing 55.2259, BTC LONG 0.008 -> 0.118 losing 66.5732, BTC SHORT 0.02 -> 55.1980, XRP LONG 0.008 -> 10860.1 losing 51.0587. The old term 0.0011 overstates the XRP round-trip cost (0.000695) and understates the BTC one (83.084).
- **Task 3**: Four-way equality for BTC (83.0840) and XRP (0.000695); identity of `per_unit_round_trip_cost` across `cost_rates`, `costs` and `gating`; patching the producer in `costs` changes only `modeled_costs_per_unit`, patching it in `gating` changes `evaluate_risk`. A spy on each module's `evaluate_risk` shows exactly one risk call each in the simulator and the paper replay of the parity fixture, with fully equal kwargs and equal verdict quantity (32.071) and cost (0.1704471428...); the simulator trade record carries that cost. Account taker 0.0004 gives the parameter quantity 0.035 and cost 83.0840 with fee_source ACCOUNT_MAX; taker 0.0007 records fee 0.0007 on both sides, cost 106.860 and a quantity not above the parameter one.

## Verification

- `pytest tests/test_sl_loss_property.py tests/test_cost_parity.py -q -p no:cacheprovider`: 46 passed in about 5 seconds (39 property tests, 7 parity tests).
- `ruff check` on both files: clean.
- Non-vacuity, checked by runtime patching from the scratchpad without touching source: replacing the pipeline cost term with the constant 0.0011 makes the property, guard-region and vacuity tests fail; altering the paper loop's exit slippage fails the call-site parity test; freezing the gating producer to a constant fails the four-way XRP, identity, parity and live tests.
- No production file was changed; no packages installed (hypothesis intentionally not added).

## Deviations from Plan

**1. [Process] Vacuity proof made permanent.** The plan asked for a one-off run with `old_formula_quantity` temporarily returning the corrected quantity. The harness is instead fed the corrected pipeline quantity by `test_harness_reports_vacuity_when_fed_a_correct_quantity`, which asserts the "vacuous" error is raised. Same evidence, and it stays in the suite.

**2. [Process] Master branch.** Commits landed on `master` as directed (sequential run on the main working tree).

No Rule 1-4 deviations. No pipeline defect found: every accepted grid plan and every parity check passed on first run.

## Known Stubs

None.

## Threat Flags

None. T-12-20 (vacuous property test) is mitigated by independent Decimal arithmetic with literal rates, the old-formula mutation check requiring a BTC violation, the minimum accepted-plan count, and the spy and delegation parity tests. T-12-SC: no packages installed.

## Self-Check: PASSED

- `tests/test_sl_loss_property.py` and `tests/test_cost_parity.py` exist; commits 533590d, d7e63d7, 1df545b exist; `git rev-list --count` from the ledger base gives 3.
