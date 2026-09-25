---
phase: 05-risk-engine
plan: 02
subsystem: risk-engine
tags: [risk, portfolio, dailystop, fail-closed, parity, tdd, d-03, d-04]
dependency_graph:
  requires: [phase-05-risk-engine-plan-01]
  provides: [src.risk.check_portfolio, src.risk.OpenPosition, src.risk.PortfolioVerdict, evaluate_risk portfolio pipeline, 6 portfolio parity cases]
  affects: [phase-06-backtest, phase-07-paper, phase-08-approval, phase-09-live]
tech-stack:
  added: []
  patterns: [pure-package, decimal-only, pinned-prec-28, fail-closed, parity-fixture, first-failure-wins, sorted-iteration, utc-aware-subtraction]
key-files:
  created:
    - src/risk/portfolio.py
    - tests/test_risk_portfolio.py
    - tests/fixtures/phase5/cluster_cap_reject/input.json
    - tests/fixtures/phase5/cluster_cap_reject/expected.json
    - tests/fixtures/phase5/aggregate_cap_reject/input.json
    - tests/fixtures/phase5/aggregate_cap_reject/expected.json
    - tests/fixtures/phase5/max_positions_reject/input.json
    - tests/fixtures/phase5/max_positions_reject/expected.json
    - tests/fixtures/phase5/daily_stop_block/input.json
    - tests/fixtures/phase5/daily_stop_block/expected.json
    - tests/fixtures/phase5/stale_constraints/input.json
    - tests/fixtures/phase5/stale_constraints/expected.json
    - tests/fixtures/phase5/uncertain_account_state/input.json
    - tests/fixtures/phase5/uncertain_account_state/expected.json
  modified:
    - src/risk/__init__.py
    - src/risk/gating.py
    - src/risk/types.py
    - tests/test_domain_no_float.py
decisions:
  - id: 05-02-D-01
    summary: Gate order is fixed (cluster → aggregate → count → daily) with first-failure-wins reason code preservation (D-03)
  - id: 05-02-D-02
    summary: V1 conservative cluster rule: directionally-aligned BTC/ETH/SOL/XRP counted as one cluster (D-03 + RESEARCH A3)
  - id: 05-02-D-03
    summary: Candidate risk ADDED to cluster and aggregate sums; candidate NOT counted in position count (Pitfall 6 — 05-01 checkpoint lock)
  - id: 05-02-D-04
    summary: Open positions sorted by (symbol, position_side) before any aggregation for deterministic iteration (Pitfall 4)
  - id: 05-02-D-05
    summary: TTL subtraction between UTC-aware datetimes only; boundary at exactly TTL is PASS, one second over is STALE_CONSTRAINTS (Pitfall 3)
  - id: 05-02-D-06
    summary: Daily state machine NORMAL → WARNING → DAILY_STOP with inclusive boundaries; DAILY_STOP blocks, WARNING passes with state reported
  - id: 05-02-D-07
    summary: Fail-closed on None daily_loss_quote, positions_reconciled=False, stale constraint snapshot, missing stepSize metadata (D-04)
  - id: 05-02-D-08
    summary: parameter_set values are ABSOLUTE quote amounts in check_portfolio; caller (evaluate_risk or Phase-7+) converts registry rates to absolute amounts
metrics:
  duration: ~25 min
  completed_date: 2026-09-25
  tasks: 3
  commits: 2
status: complete
actuals:
  tokens: 55000
  tasks: 3
  commits: 2
---

# Phase 5 Plan 2: Portfolio Gates + DAILY_STOP + Fail-Closed Summary

## One-liner

Ordered portfolio gates (cluster → aggregate → count → daily) with first-failure-wins reason codes, DAILY_STOP state machine, fail-closed input validation, and 6 byte-exact portfolio parity cases — completing the Phase 5 risk engine.

## Tasks Done

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED: failing portfolio gate and fail-closed tests + 6 input.json fixtures | `80d26cc` | 7 files |
| 2 | GREEN: check_portfolio + PortfolioVerdict + evaluate_risk pipeline + 6 expected.json | `4f6d968` | 13 files |
| 3 | Phase gate: full suite + ruff + mypy strict clean | (this commit) | — |

## Verify Evidence

### RED gate (Task 1)

```
$ uv run pytest tests/test_risk_portfolio.py -q
ERROR collecting tests/test_risk_portfolio.py
  ModuleNotFoundError: No module named 'src.risk.portfolio'
```

RED proven: collection error on missing `src.risk.portfolio` module (expected per plan 05-02 verify).

### GREEN gate (Task 2)

```
$ uv run pytest tests/test_risk_portfolio.py tests/test_risk_parity.py -q
...............................                                          [100%]
```

24 portfolio tests + 7 parity tests all green.

### Phase gate (Task 3)

```
$ uv run pytest tests/ --tb=no
........................................................................ [ 43%]
...................................................................sssss [ 65%]
........................................................................ [ 87%]
...........................................                              [100%]
326 passed, 5 skipped in 81.05s (0:01:21)
```

```
$ uv run --python 3.13 --with ruff ruff check src/risk/ tests/test_risk_portfolio.py tests/test_risk_parity.py tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_domain_no_float.py tests/test_registry.py tests/test_domain_enums.py tests/conftest.py
All checks passed!
```

```
$ uv run --python 3.13 --with mypy mypy src/
Success: no issues found in 41 source files
```

### Phase-4 determinism suites (untouched)

```
$ uv run pytest tests/test_prefix_invariance.py tests/test_no_lookahead.py tests/test_candle_close_timing.py -v --tb=no
tests\test_prefix_invariance.py ...                                      [ 33%]
tests\test_no_lookahead.py ....                                          [ 77%]
tests\test_candle_close_timing.py ....                                   [100%]
======================== 11 passed in 64.33s (0:01:04) ========================
```

All Phase-4 determinism suites pass untouched — risk added no strategy-path regression.

### Phase 5 parity cases (11 total)

```
$ uv run python -c "from pathlib import Path; print(sorted([d.name for d in Path('tests/fixtures/phase5').iterdir() if d.is_dir()]))"
['aggregate_cap_reject', 'cluster_cap_reject', 'daily_stop_block', 'happy_path_long', 'happy_path_short', 'max_positions_reject', 'min_qty_reject', 'notional_reject', 'stale_constraints', 'uncertain_account_state', 'utilization_reject_edge']
```

11 phase5 cases (5 from 05-01 + 6 from 05-02). The conftest.py `phase5_parity_cases` fixture picks them all up via sorted directory iteration — no edit needed.

### Portfolio parity fixture hand-verification

| Case | reason_code | daily_state | is_no_trade |
|------|-------------|-------------|-------------|
| cluster_cap_reject | CLUSTER_CAP_REJECT | NORMAL | true |
| aggregate_cap_reject | AGGREGATE_CAP_REJECT | NORMAL | true |
| max_positions_reject | MAX_POSITIONS_REJECT | NORMAL | true |
| daily_stop_block | DAILY_STOP_BLOCK | DAILY_STOP | true |
| stale_constraints | STALE_CONSTRAINTS | NORMAL | true |
| uncertain_account_state | UNCERTAIN_ACCOUNT_STATE | NORMAL | true |

All values computed by the implementation, hand-verified against the gate arithmetic.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale constraints fixture timestamp off by one hour**
- **Found during:** Task 2 GREEN (parity test for stale_constraints returned PASS instead of STALE_CONSTRAINTS)
- **Issue:** Original fixture had `metadata_observed_at_utc = 2026-09-18T23:59:59+00:00` with `now_utc = 2026-09-19T00:00:00+00:00` and `ttl_seconds = 3600`. The age was 1 second, not > 3600 seconds, so the TTL check passed.
- **Fix:** Changed `metadata_observed_at_utc` to `2026-09-18T22:59:59+00:00` (1 hour and 1 second before now_utc), making age = 3601 > 3600 → STALE_CONSTRAINTS.
- **Files modified:** `tests/fixtures/phase5/stale_constraints/input.json`
- **Commit:** `4f6d968`

**2. [Rule 1 - Bug] Test parameters were rates, not absolute amounts**
- **Found during:** Task 2 GREEN (cluster_cap_exact_pass test failed with CLUSTER_CAP_REJECT instead of PASS)
- **Issue:** Test PARAMETERS dict used registry rates (`cluster_cap=0.005`, `max_aggregate_open_risk=0.01`) but `check_portfolio` compares against absolute quote amounts. The 30+20=50 USDT sum exceeded the 0.005 USDT "cap" (literal interpretation).
- **Fix:** Updated test PARAMETERS to use absolute amounts (cluster_cap=50, max_aggregate_open_risk=100, daily_loss_warning_threshold=50, daily_loss_stop_threshold=100) for an equity of 10000 USDT. Added a comment documenting the rate-to-absolute conversion math.
- **Files modified:** `tests/test_risk_portfolio.py`
- **Commit:** `4f6d968`

**3. [Rule 1 - Bug] TTL test missing constraint_observed_at_utc parameter**
- **Found during:** Task 2 GREEN (test_ttl_one_second_over_rejects failed with PASS instead of STALE_CONSTRAINTS)
- **Issue:** The TTL test called `check_portfolio` without passing `constraint_observed_at_utc`, so the TTL check was skipped.
- **Fix:** Added `constraint_observed_at_utc=observed_at` to both TTL test calls.
- **Files modified:** `tests/test_risk_portfolio.py`
- **Commit:** `4f6d968`

## Learnings

1. **Rate vs absolute amount boundary**: The registry stores rates (e.g., `cluster_cap=0.005` = 0.5% of equity), but the gate math compares absolute quote amounts. The cleanest design is to have `check_portfolio` work in absolute amounts and let the caller (evaluate_risk or Phase-7+ caller) do the rate-to-absolute conversion. This keeps the gate math pure and the parity fixture byte-exact.

2. **TTL boundary semantics**: The TTL check uses `age > ttl` (strict greater-than), so `age == ttl` is PASS and `age == ttl + 1 second` is STALE_CONSTRAINTS. The boundary test at exactly TTL pins this inclusive boundary.

3. **Daily state machine boundaries**: WARNING and DAILY_STOP both use inclusive lower boundaries (`>=`). So `daily_loss == warning_threshold` is WARNING, `daily_loss == stop_threshold` is DAILY_STOP. The boundary tests pin this.

4. **First-failure-wins with sized short-circuit**: When `sized.is_no_trade=True` (e.g., EXCHANGE_CONSTRAINT from zero SL distance), `check_portfolio` preserves the upstream reason code rather than running the portfolio gates. This is the D-02 pipeline short-circuit discipline.

5. **Sorted iteration for determinism**: Sorting `open_positions` by `(symbol, position_side)` before any aggregation ensures that two position lists with different insertion orders yield identical verdicts. The order-independence test pins this.

## Out of Scope (deferred to future phases)

- Phase-7+ caller responsibility for rate-to-absolute conversion (evaluate_risk currently passes absolute amounts directly; Phase-7+ will load from registry and convert)
- Phase-8 SAFE_MODE interplay (DAILY_STOP_BLOCK is emitted; downstream consumer reads daily_state from verdict)
- Phase-9 placement-time revalidation (TTL check happens at sizing time; Phase-9 may add a second TTL check at placement time)

## Self-Check

- [x] All 6 input.json fixtures exist
- [x] All 6 expected.json fixtures exist
- [x] tests/test_risk_portfolio.py exists with 24 tests
- [x] src/risk/portfolio.py exists with check_portfolio()
- [x] src/risk/types.py extended with OpenPosition + PortfolioVerdict
- [x] src/risk/gating.py extended with portfolio pipeline
- [x] src/risk/__init__.py re-exports new symbols
- [x] tests/test_domain_no_float.py SCANNED_FILES extended with src/risk/portfolio.py
- [x] All 24 portfolio tests pass
- [x] All 7 parity tests pass
- [x] All 11 phase5 parity cases byte-exact
- [x] Full suite (326 tests) passes
- [x] Ruff clean on all changed files
- [x] Mypy strict clean on all 41 src/ files
- [x] Phase-4 determinism suites pass untouched
- [x] 2 atomic commits (RED + GREEN)
- [x] No package installs (D-05 stdlib + in-repo only)
- [x] No DB migrations (deferred to Phase 7+)
- [x] No execution/backtest/Telegram work (out of scope)
