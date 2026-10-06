---
phase: 15-strategy-geometry-correction
fixed_at: 2026-10-06T00:00:00Z
review_path: .planning/phases/15-strategy-geometry-correction/15-REVIEW.md
iteration: 1
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 15: Code Review Fix Report

**Fixed at:** 2026-10-06
**Source review:** .planning/phases/15-strategy-geometry-correction/15-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 1
- Fixed: 1
- Skipped: 0

## Fixed Issues

### WR-01: Registry accepts a range-mr geometry set whose `regime_filter_lookback` is below `pivot_right_bars + 1`

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** e0593a6
**Applied fix:** Added a cross-key rule to `_check_geometry_keys`. A range-mr set that has `pivot_right_bars` and `regime_filter_lookback` is rejected at load with `StrategyKeyOutsideRegistry` when `pivot_right_bars + 1 > regime_filter_lookback`. The rule is validation only. No parameter value, `params/*.toml` file or strategy behavior changed, and the key is optional, so no existing `parameter_set_hash` moved. Tests were written first and failed with "DID NOT RAISE". They are `test_range_mr_regime_filter_lookback_below_pivot_right_plus_one_is_rejected` (lookback 3 with right width 3 is rejected) and `test_range_mr_regime_filter_lookback_equal_to_pivot_right_plus_one_loads` (lookback 4 loads, the boundary). The optional defense-in-depth mapping of `ValueError` to `NO_TRADE_REGIME` in `evaluate` was not applied, to keep the change validation-only.

Status note: this is a validation rule, not a logic change in the decision path.

## Verification

Run in the main checkout (`workflow.use_worktrees=false`, no worktree), so the numbers are reproducible from the current tree.

- `tests/test_registry.py`, `tests/test_registry_gate.py`, `tests/test_decision_alignment_params.py`, `tests/test_rationale.py`: all pass (run file by file).
- `scripts.decision_alignment.params.run()`: PA-01..PA-08 all ok.
- `ruff check` and `ruff format --check` on the changed files: clean. `mypy src`: no issues in 149 files.

---

_Fixed: 2026-10-06_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
