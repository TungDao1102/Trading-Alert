---
phase: 12-fee-cost-model-correctness
fixed_at: 2026-09-30T00:00:00Z
review_path: .planning/phases/12-fee-cost-model-correctness/12-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 12: Code Review Fix Report

**Fixed at:** 2026-09-30
**Source review:** .planning/phases/12-fee-cost-model-correctness/12-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (critical 0, warning 5; Info excluded by `fix_scope: critical_warning`)
- Fixed: 5
- Skipped: 0

Verification ran in the main checkout (no isolated worktree), because the run continued from uncommitted edits left by an interrupted fixer. After the last fix the full `pytest tests` run passed. Ruff check and mypy were clean on every touched source file. Ruff format and one mypy error (`src/adapters/telegram_notify.py:287`) were already failing before these commits and were left alone.

## Fixed Issues

### WR-01: Live cost-rate gate trusts a string label, not the resolver's verified output

**Files modified:** `src/execution/manager.py`, `src/risk/cost_rates.py`, `src/risk/live_commission.py`, `tests/test_execution_manager.py` (committed by the previous fixer before this run)
**Commit:** 8a0be9d
**Applied fix:** Bound the live cost-rate gate to commission provenance, so the manager no longer relies on the `fee_source` label alone. Not re-audited in this run. It was already committed when the run was resumed.

### WR-02: Adverse-edge sizing does not validate plan geometry

**Files modified:** `src/risk/gating.py`, `tests/test_risk_cost_guards.py`
**Commit:** ec4dccb
**Applied fix:** These were the uncommitted edits from the interrupted run. They matched WR-02, were correct, and were kept as they were. `size_and_quantize` now returns NO_TRADE with `EXCHANGE_CONSTRAINT` before sizing when `entry_min > entry_max`, when a LONG stop is not below `entry_max`, or when a SHORT stop is not above `entry_min`. The last two conditions also catch a candidate side that disagrees with the plan.
**Deviation from the review:** the suggested check required the stop to lie beyond the far edge of the zone (LONG `stop < entry_min`). The checks use the sizing (adverse) edge instead. The Phase 6 strategy fixtures emit plans whose stop sits inside the zone, and changing plan generation is outside this phase. This still removes the `abs()` masking: the signed stop distance at the sizing edge is always positive. Five parametrized tests cover both `size_and_quantize` and `evaluate_risk`.
**Status note:** logic change, so this is "fixed: requires human verification". Confirm that allowing a stop inside the zone is acceptable.

### WR-03: `simulator.run` and `run_paper_tick` size with a fixture cost model never bound to the registry

**Files modified:** `src/backtest/binding.py`, `src/backtest/simulator.py`, `src/paper/loop.py`, `tests/test_backtest_simulator.py`, `tests/test_paper_closed_candle.py`
**Commit:** fe830d6
**Applied fix:** Added `assert_sizing_costs_bind_registry`, called after `load_parameter_set` in both entry points and before any sizing. It raises `CostModelBindingMismatch` when the fixture's fee, slippage, `exit_slippage_rate`, funding or spread assumptions differ from the registry slice.
**Deviation from the review:** the review suggested calling `assert_cost_model_binds_registry` as is. That broke the `limit_touch_no_fill` and `limit_partial_fill` fixtures. They set `partial_fill_fraction` to 0 and 0.5 on purpose, and the field is applied to the filled quantity after sizing. The new function does the same hash comparison with `partial_fill_fraction` taken from the model, so no other key is exempt. `assert_cost_model_binds_registry` is unchanged for `experiment.assemble` and `paper.freeze`.
**Tests:** two legacy-refusal tests in `test_backtest_simulator.py` now expect `CostModelBindingMismatch`, because the binding fires before the later `ValueError`s. They still refuse the same inputs. Added tests: a divergent fee rate is refused in `run` and in `run_paper_tick`, and a divergent `partial_fill_fraction` is still accepted.
**Status note:** requires human verification that partial fill fraction should stay outside the binding.

### WR-04: Registry loader accepts NaN/Infinity for unranged decimal keys and raises the wrong exception for ranged ones

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** d18f514
**Applied fix:** `_check_value_range` now rejects any non-finite int or Decimal value with `StrategyKeyOutsideRegistry` ("must be finite") before the range checks. The change covers every numeric key, including the unranged `risk_rate` and `minimum_rr`. Parametrized tests cover NaN, Infinity and -Infinity across five keys.

### WR-05: Cost-guard input validation raises `InvalidOperation` and accepts floats/bools

**Files modified:** `src/risk/cost_guards.py`, `src/backtest/costs.py`, `tests/test_risk_cost_guards.py`, `tests/test_backtest_simulator.py`
**Commit:** e7599f6
**Applied fix:** `validate_guard_rates` now raises `ValueError` for non-finite values, including NaN and sNaN, as documented. `guard_rates_from_params` accepts only `Decimal` or `int` and raises `TypeError` for bool, float, str and None. It then calls `validate_guard_rates`, so range and finiteness failures use one exception type at the boundary. Two existing test inputs that passed strings such as `"0.15"` were changed to `Decimal`. New tests cover the type rejections and the NaN, Infinity and range cases.

---

_Fixed: 2026-09-30_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
