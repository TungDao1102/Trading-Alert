---
phase: 05-risk-engine
plan: 01
subsystem: risk-engine
tags: [risk, sizing, quantization, parity, tdd, d-01, d-02, d-05]
dependency_graph:
  requires: [phase-04-pure-core-feature-strategy-planner]
  provides: [src.risk.size_position, src.risk.quantize, src.risk.evaluate_risk, baseline-v2 parameter sets, D-05 reason-code vocabulary, DailyState enum]
  affects: [phase-06-backtest, phase-07-paper, phase-08-approval, phase-09-live]
tech-stack:
  added: []
  patterns: [pure-package, decimal-only, pinned-prec-28, fail-closed, parity-fixture, enum-promotion, versioned-toml-sets]
key-files:
  created:
    - src/risk/__init__.py
    - src/risk/types.py
    - src/risk/sizing.py
    - src/risk/quantization.py
    - src/risk/gating.py
    - params/trend-pullback/baseline-v2.toml
    - params/breakout-retest/baseline-v2.toml
    - params/range-mr/baseline-v2.toml
    - tests/test_risk_sizing.py
    - tests/test_risk_quantization.py
    - tests/test_risk_parity.py
    - tests/fixtures/phase5/happy_path_long/input.json
    - tests/fixtures/phase5/happy_path_long/expected.json
    - tests/fixtures/phase5/happy_path_short/input.json
    - tests/fixtures/phase5/happy_path_short/expected.json
    - tests/fixtures/phase5/utilization_reject_edge/input.json
    - tests/fixtures/phase5/utilization_reject_edge/expected.json
    - tests/fixtures/phase5/min_qty_reject/input.json
    - tests/fixtures/phase5/min_qty_reject/expected.json
    - tests/fixtures/phase5/notional_reject/input.json
    - tests/fixtures/phase5/notional_reject/expected.json
  modified:
    - src/domain/enums.py
    - src/domain/registry.py
    - docs/GLOSSARY.md
    - tests/conftest.py
    - tests/test_domain_no_float.py
    - tests/test_domain_enums.py
    - tests/test_registry.py
decisions:
  - id: 05-01-D-01
    summary: RejectionReason enum promotion + GLOSSARY §9 update (one-way, locked in plan 05-01 checkpoint:decision)
  - id: 05-01-D-02
    summary: Utilization gate = realized_risk / allowed_risk >= 0.6 (Pitfall 2 distinguishing case pinned by parity fixture)
  - id: 05-01-D-03
    summary: Notional-check reference price = zone-mid entry_ref (consistent with SL-distance basis)
  - id: 05-01-D-04
    summary: Candidate-plan risk ADDED to cap sums in aggregate/cluster caps (Pitfall 6 — exact-cap equality PASSES)
  - id: 05-01-D-05
    summary: New versioned parameter sets named baseline-v2.toml per family at strategy_version v2.0.0 (never ambient v1 edits)
  - id: 05-01-D-06
    summary: src/risk/ is dependency-free (stdlib + Decimal + src/core/_decimal.py only); no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic
  - id: 05-01-D-07
    summary: ConstraintSnapshot type guard rejects zero/negative step_size at construction (fail-closed at type level, not runtime)
metrics:
  duration: ~25 min
  completed_date: 2026-09-25
  tasks: 3
  commits: 2
status: complete
actuals:
  tokens: 74000
  tasks: 3
  commits: 2
---

# Phase 5 Plan 1: Risk Engine Tracer Slice Summary

## One-liner

Pure dependency-free `src/risk/` package (sizing + quantization + gating) with byte-identical parity fixture green, D-05 reason-code vocabulary promoted to `RejectionReason`, new `DailyState` enum, and three `baseline-v2.toml` parameter sets at `strategy_version v2.0.0`.

## Tasks Done

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Lock D-02 one-way quantization semantics (checkpoint:decision) | (orchestrator) | — |
| 2 | RED: failing sizing, quantization, parity tests + 5 input.json fixtures | `c39f070` | 8 files |
| 3 | GREEN: src/risk/ + vocabulary + registry + v2 sets + parity green | `74a04b8` | 23 files |

## Verify Evidence

### RED gate (Task 2)

```
$ uv run pytest tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_risk_parity.py -q
ERROR collecting tests/test_risk_sizing.py
  ModuleNotFoundError: No module named 'src.risk'
ERROR collecting tests/test_risk_quantization.py
  ModuleNotFoundError: No module named 'src.risk'
ERROR collecting tests/test_risk_parity.py
  ModuleNotFoundError: No module named 'src.risk'
```

RED proven: all three test files fail with `ModuleNotFoundError` on `src.risk` imports (collection error is the expected RED gate per plan 05-01 verify).

### GREEN gate (Task 3)

```
$ uv run pytest tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_risk_parity.py tests/test_domain_no_float.py tests/test_registry.py -v
collected 47 items
tests\test_risk_sizing.py ....                                           [  8%]
tests\test_risk_quantization.py ........                                 [ 25%]
tests\test_risk_parity.py .......                                        [ 40%]
tests\test_domain_no_float.py ..                                         [ 44%]
tests\test_registry.py ..........................                        [100%]
============================= 47 passed in 0.29s ==============================
```

### Full suite (excluding tests requiring native deps not in venv)

```
$ uv run pytest tests/ --ignore=tests/test_adapter_strictness.py --ignore=tests/test_backfill.py --ignore=tests/test_backup.py --ignore=tests/test_collector.py --ignore=tests/test_metadata.py --ignore=tests/test_quality_gates.py --ignore=tests/test_domain_mappers.py --ignore=tests/test_domain_mappers_pg.py --ignore=tests/test_registry_gate.py --ignore=tests/test_coverage.py --ignore=tests/test_tracer_slice.py
191 passed in 67.56s
```

### Ruff

```
$ uv run --python 3.13 --with ruff ruff check src/risk/ tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_risk_parity.py tests/test_domain_no_float.py tests/test_registry.py tests/test_domain_enums.py tests/conftest.py
All checks passed!
```

### Mypy strict

```
$ uv run --python 3.13 --with mypy mypy src/
Success: no issues found in 40 source files
```

### Parity fixture hand-verification

| Case | raw_quantity | rounded | realized_risk | utilization | reason_code |
|------|--------------|---------|---------------|-------------|-------------|
| happy_path_long | 0.04995004995004995004995004995 | 0.049 | 49.04900 | 0.98098 | OK (ACCEPTED) |
| happy_path_short | 0.04995004995004995004995004995 | 0.049 | 49.04900 | 0.98098 | OK (ACCEPTED) |
| utilization_reject_edge | 0.0017 | 0.001 | 1.00000 | 0.58824 | UTILIZATION_REJECT |
| min_qty_reject | 0.005 | 0.005 | 5.00000 | 1.00000 | MIN_QTY_REJECT |
| notional_reject | 0.10 | 0.100 | 1.00000 | 1.00000 | NOTIONAL_REJECT |

All values computed by the implementation, hand-verified against the §11 algorithm.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Zero SL distance fail-closed semantics**
- **Found during:** Task 3 GREEN (test_size_position_zero_sl_distance_fails_closed failed)
- **Issue:** Original implementation only checked `risk_per_unit <= 0`, but the test expected fail-closed when `sl_distance == 0` even with positive costs (degenerate zone → infinite quantity).
- **Fix:** Added explicit `sl_distance <= 0` check in `src/risk/sizing.py:size_position` before the `risk_per_unit` check. Both conditions now fail closed with `EXCHANGE_CONSTRAINT`.
- **Files modified:** `src/risk/sizing.py`
- **Commit:** `74a04b8`

**2. [Rule 1 - Bug] Zero step_size fail-closed at type level**
- **Found during:** Task 3 GREEN (test_quantize_zero_step_size_fails_closed failed)
- **Issue:** Original test expected `EXCHANGE_CONSTRAINT` return from `quantize()` when `quantity_step_size == 0`, but the `ConstraintSnapshot.__post_init__` guard rejects zero with `ValueError` first.
- **Fix:** Renamed test to `test_constraint_snapshot_zero_step_size_rejected` and updated assertion to verify the type-level `ValueError` (which is a stronger fail-closed — invalid exchange metadata fails at construction, never reaches `quantize()`).
- **Files modified:** `tests/test_risk_quantization.py`
- **Commit:** `74a04b8`

**3. [Rule 1 - Bug] GLOSSARY §9 test out of sync with new D-05 codes**
- **Found during:** Task 3 GREEN (test_rejection_reason_values_match_glossary_section_9 failed)
- **Issue:** The pre-existing test asserted the exact set of `RejectionReason` values matched the old GLOSSARY §9 (14 codes). Adding 9 new D-05 codes broke the equality check.
- **Fix:** Updated the test's `expected` set to include the 9 new D-05 codes (verbatim from the updated GLOSSARY §9).
- **Files modified:** `tests/test_domain_enums.py`
- **Commit:** `74a04b8`

## Learnings

1. **Type-level guards vs runtime guards**: The `ConstraintSnapshot.__post_init__` guard rejecting zero `quantity_step_size` is a stronger fail-closed than runtime checks in `quantize()`. The plan's "Pitfall 1" intent is satisfied at construction time, not at quantize time. Tests should verify the type-level guard, not the runtime guard.

2. **Pitfall 2 distinguishing case**: The parity fixture's `utilization_reject_edge` case (nonzero costs, `realized_risk/allowed_risk = 0.588 < 0.6`) is mathematically equivalent to `rounded/raw_quantity` when both use the same `risk_per_unit`. The "distinguishing case" is really about ensuring the implementation uses `realized_risk = rounded * risk_per_unit` (including costs), not `raw * sl_distance` (excluding costs). The fixture pins this exact computation.

3. **Decimal boundary precision**: To hit `utilization == 0.6` exactly under prec-28, the inputs must be chosen so the division produces an exact result. `risk_per_unit = 600, allowed_risk = 1, raw = 1/600` works because `0.001 * 600 = 0.6` exactly, and `0.6 / 1 = 0.6` exactly.

4. **Registry type classification (Pitfall 5)**: The `INT_KEYS` vs `DECIMAL_KEYS` split is automatic via `DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS`, but `INT_KEYS` membership is manual. The new tests (`test_max_open_positions_int_key_rejects_decimal`, etc.) pin the classification so a future maintainer can't accidentally move `max_open_positions` to `DECIMAL_KEYS` and accept `2.5` as a valid value.

## Out of Scope (deferred to plan 05-02)

- Portfolio gates (`check_portfolio`): cluster cap, aggregate cap, position count, daily state
- `OpenPosition` frozen struct
- `PortfolioVerdict` envelope
- `tests/test_risk_portfolio.py`
- Portfolio-gate parity fixtures (`cluster_cap_reject`, `aggregate_cap_reject`, `max_positions_reject`, `daily_stop_block`, `stale_constraints`, `uncertain_account_state`)

## Self-Check

- [x] All 5 input.json fixtures exist
- [x] All 5 expected.json fixtures exist
- [x] All 3 test files exist
- [x] src/risk/ package exists with 5 modules
- [x] 3 baseline-v2.toml files exist
- [x] src/domain/enums.py extended with 9 D-05 codes + DailyState
- [x] src/domain/registry.py extended with 11 D-05 keys + 2 INT_KEYS
- [x] docs/GLOSSARY.md extended with §8.1 + §9 D-05 codes
- [x] tests/conftest.py extended with PHASE5_FIXTURES_DIR + loaders
- [x] tests/test_domain_no_float.py SCANNED_FILES extended with src/risk/*
- [x] tests/test_registry.py extended with 5 INT-vs-DECIMAL type tests
- [x] tests/test_domain_enums.py GLOSSARY §9 test extended with 9 D-05 codes
- [x] All 47 risk/registry/no-float tests pass
- [x] Full suite (191 tests) passes
- [x] Ruff clean on all changed files
- [x] Mypy strict clean on all 40 src/ files
- [x] 2 atomic commits (RED + GREEN)
- [x] No package installs (D-05 stdlib + in-repo only)
- [x] No DB migrations (deferred to Phase 7+)
- [x] No execution/backtest/Telegram work (out of scope)
