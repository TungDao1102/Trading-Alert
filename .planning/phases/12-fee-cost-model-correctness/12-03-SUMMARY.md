---
phase: 12-fee-cost-model-correctness
plan: 03
subsystem: cost-model
tags: [cost-model, per-unit-cost, cost-hash, binding-gate, decimal]
status: complete

requires:
  - phase: 12-02
    provides: exit_slippage_rate registry key, v5 parameter sets, rate unit guard
provides:
  - src/risk/cost_rates.py (CostRates, per_unit_round_trip_cost, fee source constants)
  - CostModel.exit_slippage_rate (optional, presence-driven hash) and cost_rates_from_model
  - Canonical numeric text in cost_model_hash (spelling-independent, D-15)
  - cost_slice shared by the registry binding gate and the paper freeze
affects: [12-04, 12-05, 12-06, 12-09 (simulator/paper cutover), 12-11 decision rows]

actuals:
  tokens: 9800
  tasks: 2
  commits: 4

commits: 4
plan_head_before: 243cedd011e90a5ccd210bd9ca763e06918d95f9
plan_head_after: 6f2b10e4b83c5894593e59d4397a3eb305a6d147

tech-stack:
  added: []
  patterns:
    - "Optional trailing dataclass field participating in a hash by presence (legacy hashes stay byte-locked)"
    - "Canonical numeric text built from the Decimal digit tuple (independent of ambient context precision)"
    - "One registry slice builder (cost_slice) shared by binding and freeze"

key-files:
  created:
    - src/risk/cost_rates.py
    - tests/test_cost_per_unit.py
  modified:
    - src/backtest/costs.py
    - src/backtest/__init__.py
    - src/backtest/binding.py
    - src/risk/__init__.py
    - src/paper/freeze.py
    - tests/test_backtest_experiment.py
    - tests/test_backtest_binding.py

key-decisions:
  - "Per-unit cost is quote currency per unit of base: entry_price x (fee_entry + entry_slippage) + stop_price x (fee_exit + exit_slippage); one producer, explicit prices (D-01)."
  - "exit_slippage_rate is an optional trailing CostModel field that joins the hash by presence; COST_KEYS stays at 7 keys and no legacy hash moved (D-14 option B)."
  - "Cost hash canonicalizes numeric values to plain normalized text before hashing; the rule is local to CostModel and src/domain/canonical.py is untouched (D-15). Recorded as decision D047 for the phase decision rows."
  - "A legacy model without exit_slippage_rate is constructible but cost_rates_from_model refuses it (never defaulted to expected_slippage)."

requirements-completed: [RISK-01, DOMN-02]

coverage:
  - deliverable: "Price-aware per-unit producer matching hand-derived BTC/XRP oracles and linear in price"
    verification:
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_btc_long_oracle"
        status: pass
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_doubling_prices_doubles_cost"
        status: pass
    human_judgment: false
  - deliverable: "Legacy 7-key models refused for sizing; rate ceiling enforced on CostModel"
    verification:
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_cost_rates_from_legacy_model_refused"
        status: pass
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_cost_model_rejects_rate_above_ceiling"
        status: pass
    human_judgment: false
  - deliverable: "Spelling-independent cost hash; the eight legacy registry cost hashes reproduced exactly"
    verification:
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_legacy_registry_cost_hashes_do_not_move"
        status: pass
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_partial_fill_fraction_one_spellings_hash_equal"
        status: pass
    human_judgment: false
  - deliverable: "v5 sets bind and freeze only an 8-key model with the registry exit_slippage_rate"
    verification:
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_binding_v5_set_refuses_seven_key_model"
        status: pass
      - kind: test
        ref: "tests/test_cost_per_unit.py#test_freeze_v5_set_pins_and_refuses_seven_key_model"
        status: pass
    human_judgment: false
---

# Phase 12 Plan 03: Per-unit cost producer, 8-key cost identity Summary

**One pure price-aware producer returns the round-trip cost in quote per unit of base (BTC LONG 83.0840, XRP 0.000695); the cost model carries the stop-exit slippage rate by presence, hashes numerics as canonical text, and the binding and freeze gates attest it, with every legacy cost hash unchanged.**

## Performance

- Tasks: 2 (1 tracer, 1 auto), both TDD with separate RED commits
- Commits: 4 (measured from the ledger)
- Files: 2 created, 7 modified; `src/domain/canonical.py` untouched

## Accomplishments

- `src/risk/cost_rates.py`: frozen `CostRates` (four Decimal rates in [0, 0.01], fee_source PARAMETER or ACCOUNT_MAX) and `per_unit_round_trip_cost(side, entry_price, stop_price, rates)` built only from the pinned `_add` / `_mul` helpers. Non-Decimal prices raise TypeError, prices at or below zero and an unknown side raise ValueError. The module imports nothing from `src/backtest` (asserted in a fresh subprocess) and contains no float call or literal (asserted by AST).
- `CostModel.exit_slippage_rate`: optional trailing field (existing construction unchanged). `build_cost_model` reads the optional key; a fee, expected-slippage or exit-slippage rate above 0.01 is refused (defense in depth for D-04). `cost_rates_from_model` maps a model to `CostRates` and raises ValueError naming `exit_slippage_rate` for a legacy model.
- Canonical cost hash (D-15): `_canonical_decimal_text` renders zero (any spelling, negative zero included) as `0` and every other value as plain normalized text (`1`, `0.0002`, `100`, never `1E+2`), built from the digit tuple so the ambient context precision is irrelevant. One payload builder serves both construction and the CR-09 verify branch. The eight legacy registry cost hashes (v3, the v4 family, no-trade/simple-trend v1 and v2) are asserted as literal constants and did not move.
- `cost_slice(params)` (7 keys plus `exit_slippage_rate` by presence, bare KeyError for v1/v2 sets) now builds the registry side in `binding.py` and `freeze.py`. A v5 set binds only an 8-key model whose exit rate equals the registry value; a 7-key model or a disagreeing rate raises `CostModelBindingMismatch` in both assemble and pin_stream_epoch.
- Old trailing-precision tests rewritten, not deleted: equivalent spellings now hash equal and bind, genuine value changes still differ or are refused.

## Task Commits

1. Task 1 RED: `e0ecffa` test(12-03) - oracles, CostRates, exit_slippage_rate tests
2. Task 1 GREEN: `cc679bb` feat(12-03) - cost_rates.py, CostModel field, cost_rates_from_model
3. Task 2 RED: `d2703f4` test(12-03) - canonical text, spelling matrix, regression hashes, cost_slice, v5 binding and freeze
4. Task 2 GREEN: `6f2b10e` feat(12-03) - canonical hash, cost_slice, binding and freeze

## Verification

- `pytest tests/test_cost_per_unit.py tests/test_backtest_experiment.py tests/test_backtest_binding.py tests/test_paper_freeze.py tests/test_registry.py`: pass
- Full `pytest tests`: exit 0
- `mypy src/backtest/costs.py src/backtest/binding.py src/risk/cost_rates.py`: clean
- `ruff check` on all touched files: clean
- `modeled_costs_per_unit` and `COST_KEYS` unchanged (asserted by `test_old_modeled_costs_per_unit_untouched` and `test_cost_keys_tuple_unchanged`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] int-convergence test used fee 1**
- **Found during:** Task 1 GREEN
- **Issue:** The new [0, 0.01] range check on CostModel refused `fee_rate_entry=1` in `test_direct_int_cost_model_converges_with_builder_hash`.
- **Fix:** Use 0 for the three rate fields (partial_fill_fraction stays 1) in the same commit, as the plan allowed.
- **Files modified:** tests/test_backtest_binding.py
- **Commit:** cc679bb

Freeze coverage for the v5 set lives in `tests/test_cost_per_unit.py` (keeps the plan file list); `tests/test_paper_freeze.py` is only run. No other test outside the list encoded the old trailing-precision rule or a rate above 0.01.

Otherwise the plan executed as written. No fixture regeneration was needed: no fixture-spelled cost hash was pinned in an expected file, so the canonical text rule moved no committed hash.

## Known Stubs

None.

## Threat Flags

None. T-12-06 (spelling matrix, forged supplied hash, CR-09 tests), T-12-07 (legacy refusal test) and T-12-08 (v5 missing/disagreeing exit rate refused in assemble and freeze) mitigations are in place.

## Notes

- Deferred, pre-existing and unrelated: `mypy src/paper/freeze.py` follows imports into `src/adapters/telegram_notify.py:287` (datetime assigned to a Decimal-typed variable), and `ruff check src/risk` reports F841 in `src/risk/portfolio.py:312-313` and I001 in `src/risk/types.py`. None of these files were touched by this plan.
- The decision-row text for D047 (canonical cost-hash text) is left to plan 12-11.
- Pre-existing dirty files (`.planning/config.json`, `milestone.lock`, `state.json`, `.gsd/`) were not staged.
- The old `modeled_costs_per_unit` (rate-sum) still exists and is called by the simulator and paper loop; its cutover to `per_unit_round_trip_cost` is plan 12-09.

## Self-Check: PASSED

Created files exist (`src/risk/cost_rates.py`, `tests/test_cost_per_unit.py`); commits e0ecffa, cc679bb, d2703f4, 6f2b10e found in `git log`.
