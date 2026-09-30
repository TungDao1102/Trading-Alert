---
phase: 12-fee-cost-model-correctness
plan: 09
subsystem: backtest-paper
tags: [backtest, paper, cost-model, slippage, parity, fixtures, decimal]
status: complete

requires:
  - phase: 12-03
    provides: cost_rates_from_model, per_unit_round_trip_cost
  - phase: 12-04
    provides: baseline-v5 Phase 6 fixtures with the 8-key cost dict
  - phase: 12-06
    provides: evaluate_risk with cost_rates / min_stop_distance_rate / max_cost_to_risk
provides:
  - Simulated PnL with slippage booked per leg as fill_price x quantity x rate
  - guard_rates_from_params, the one helper both simulator and paper loop use to read the guard rates
  - Price-aware modeled_costs_per_unit (quote currency per unit)
  - Phase 7 parity fixture regenerated on baseline-v5
affects: [12-10, 12-11, 14]

actuals:
  tokens: 8100
  tasks: 3
  commits: 7

commits: 7
plan_head_before: 0155db7468c62fcbab4c00c0dcd2449c86e39083
plan_head_after: fa47fa4e996cfd0bfa80aa2e22405dd9e2e539e9

tech-stack:
  added: []
  patterns:
    - "One shared helper reads guard rates from the pinned registry set and fails closed on a legacy set"
    - "Expected cost oracles are hand-derived literals; end-to-end loss is recomputed from the trade record with literal rates"
    - "Documentary hashes in expected.json are asserted equal to registry-derived values, so they cannot drift"

key-files:
  created: []
  modified:
    - src/backtest/simulator.py
    - src/backtest/costs.py
    - src/paper/loop.py
    - tests/test_backtest_simulator.py
    - tests/test_cost_per_unit.py
    - tests/test_paper_parity.py
    - scripts/gen_phase6_fixtures.py
    - tests/fixtures/phase7/parity_overlapping_history/input.json
    - tests/fixtures/phase7/parity_overlapping_history/expected.json

key-decisions:
  - "EOD exits use exit_slippage_rate (market-style close, planning assumption A2 / D046); TP1 uses expected_slippage because a take-profit is a resting limit; an unknown exit_kind is refused rather than defaulted."
  - "guard_rates_from_params is called at the risk stage in both modes (not up front), so paper fixtures that never reach risk keep their legacy sets and pinned digests."
  - "The trade record's modeled_costs_per_unit is taken from sized.modeled_costs_per_unit, so the record shows what sizing used."

requirements-completed: [BKTS-01, RISK-01]

coverage:
  - deliverable: "Six hand-derived _apply_costs oracles (BTC LONG edge and mid, BTC SHORT, XRP LONG, BTC TP1, BTC EOD) match exactly"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_apply_costs_books_slippage_per_leg_in_quote_currency"
        status: pass
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_apply_costs_tp1_uses_entry_slippage_rate_not_the_exit_rate"
        status: pass
  - deliverable: "Simulated SL-exit loss including fees and slippage is at most 50 on the three regenerated fixtures; modeled_costs_per_unit is quote per unit at the sizing edge"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_end_to_end_sl_loss_including_costs_is_within_allowed_risk"
        status: pass
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_end_to_end_modeled_costs_are_quote_per_unit_at_the_sizing_edge"
        status: pass
  - deliverable: "Legacy registry set, legacy cost dict, unknown exit_kind and missing guard keys are refused; the guard reason reaches a REJECT record"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_run_refuses_legacy_registry_set_without_guard_rates"
        status: pass
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_run_refuses_cost_dict_without_exit_slippage_rate"
        status: pass
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_guard_reason_flows_from_the_shared_helper_into_a_reject_record"
        status: pass
  - deliverable: "Price-aware modeled_costs_per_unit (83.0840, 84.9800, 0.000695, doubling identity); Test 11 no longer recomputes the rate sum"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_modeled_costs_per_unit_price_aware_oracles"
        status: pass
      - kind: test
        ref: "tests/test_backtest_simulator.py#test_cost_parity_simulator_matches_costs_module"
        status: pass
  - deliverable: "Simulator and paper produce the identical verdict digest on the regenerated fixture; both pass identical cost inputs to evaluate_risk; documentary hashes equal registry-derived values"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_paper_parity.py#test_paper_replay_digest_equals_simulator_digest"
        status: pass
      - kind: test
        ref: "tests/test_paper_parity.py#test_simulator_and_paper_pass_identical_cost_inputs_to_evaluate_risk"
        status: pass
      - kind: test
        ref: "tests/test_paper_parity.py#test_parity_expected_documentary_fields_match_registry_and_simulator"
        status: pass
---

# Phase 12 Plan 09: Simulator and paper loop on the shared cost path Summary

Backtest and paper now size through the same corrected cost path, and the simulated PnL books slippage in quote currency per leg, with a worse stop-exit rate. The simulated stop-loss loss including fees and slippage stays within the 50 risk budget on all three end-to-end fixtures.

## Accomplishments

- **Task 1 (tracer)**: `_apply_costs` books `fill_price x quantity x rate` on each leg. The entry leg uses `expected_slippage`; SL and EOD exits use `exit_slippage_rate`; TP1 uses `expected_slippage`. A missing `exit_slippage_rate` or an exit kind other than SL/TP1/EOD raises `ValueError`; records that never filled pass through untouched. `run()` builds `CostRates` with `cost_rates_from_model` and reads the guard rates with the new `guard_rates_from_params`, and passes all three into `evaluate_risk`. The pre-computed cost and the removed keyword are gone. All six hand-derived oracles match exactly, including the TP1 discriminator (67.438, not 67.004). Previously BTC slippage was booked as roughly 0.0000035 in total.
- **Task 2**: `modeled_costs_per_unit` is now keyword-only `(cost_model, side, entry_price, stop_price)`, delegates to `per_unit_round_trip_cost` over `cost_rates_from_model`, and documents the unit (quote per unit of base). Oracles 83.0840, 84.9800, 0.000695 and the doubling identity pass. Test 11 no longer recomputes `fee_rate_entry + fee_rate_exit + expected_slippage`; it checks the record against the public helper and against literal arithmetic, with plan edge and stop from a re-run of the planner.
- **Task 3**: `run_paper_tick` builds the same three values the same way. The generator has a new `write_parity_overlapping_history` writer; the parity input was regenerated (a copy of the LONG both-touched payload on baseline-v5, 8-key cost dict) and `expected.json` was re-pinned: digest `d06c739a...`, `trade_count` 1, `strategy_version` v4.0.0, `parameter_set_hash` `41ed39d4...` (from the phase4 pin file), `cost_model_hash` `3063dc39...` (registry slice). Simulator digest equals paper digest equals the pinned digest; prefix invariance and the non-vacuous full projection hold.

## Verification

- `pytest tests -q -p no:cacheprovider`: exit 0, no failures (full suite green again after waves 3-4).
- `mypy src/backtest/simulator.py src/backtest/costs.py`: no issues. `ruff check` on all touched source, test and script files: clean.
- `mypy src/paper/loop.py` reports one error in `src/adapters/telegram_notify.py:287` (datetime assigned to a Decimal-typed variable), reached through imports; not touched by this plan (see Deferred).
- `git diff 0155db7..HEAD -- src/backtest/simulator.py` touches only the imports, `_apply_costs`, the risk call site and record stamping. `src/paper/loop.py` diff is the import and the risk call site only. No file deletions. The clean_run, feed_stale and warmup fixtures' expected.json files are unchanged.

## Deviations from Plan

**1. [Rule 2 - Missing critical] Old-call-form test in `tests/test_cost_per_unit.py`.** `test_old_modeled_costs_per_unit_untouched` (plan 12-03) pinned the removed two-argument call returning 0.0011. It would fail by design, so it was replaced with a test that the old call form raises `TypeError`. Not in the plan's file list but required by the signature change (D-01, D-18).

**2. [Process] Tracer gate with one known red test.** After the tracer commit, the only failing test in the verify set was `test_cost_parity_simulator_matches_costs_module` (Test 11), which the plan explicitly leaves for Task 2. All new tracer tests passed; expansion continued.

**3. [Process] Two RED commits for Task 2.** The second RED commit was needed because the first attempt at editing `tests/test_cost_per_unit.py` did not apply (line-ending mismatch in my edit script); the file was then fixed and committed separately. Commit count is 7 rather than 6.

**4. [Process] Ruff cleanup in the test file.** `ruff --fix` also removed three pre-existing unused imports / UTC alias hints in `tests/test_backtest_simulator.py` so the plan's ruff gate passes.

**5. [Process] Master branch.** Commits landed on `master` as directed (sequential run on the main working tree).

## Known Stubs

None.

## Deferred / out of scope

- `src/adapters/telegram_notify.py:287` mypy error (pre-existing, unrelated to this plan). Anyone running `mypy src/paper/loop.py` sees it via imports; needs a fix in the adapter owner's plan.
- Simulated fill price (zone mid) and `resolve_intrabar` are untouched by design; Phase 14 owns fill causality. Consequence: on the regenerated fixtures the fill is at the zone mid while sizing assumes the adverse edge, so the simulated SL loss is below the budget rather than at it. The edge-fill worst case (49.10794 for BTC) is covered by the direct oracle only.
- REQUIREMENTS.md: BKTS-01 marked complete via the helper; 12-10 and 12-11 also list BKTS-01 and RISK-01 and will re-confirm.

## Threat Flags

None. T-12-18 (slippage without price) is mitigated by the per-leg booking and six oracles; T-12-19 (legacy set or cost model silently simulated) by the ValueError refusals in `guard_rates_from_params` and `cost_rates_from_model` with tests for both.

## Self-Check: PASSED

- All nine modified files exist; commits 5260592, b25519d, 7263a3a, 1da7f4e, 2c13b87, 9d92ce3, fa47fa4 exist; `git rev-list --count` from the ledger base gives 7.
