---
phase: 04-pure-core-feature-strategy-planner
verified: 2026-10-03T00:00:00Z
status: passed
score: 14/14 must-haves verified
covered_files:
  - .planning/phases/04-pure-core-feature-strategy-planner/04-01-PLAN.md
  - .planning/phases/04-pure-core-feature-strategy-planner/04-01-SUMMARY.md
  - .planning/phases/04-pure-core-feature-strategy-planner/04-02-PLAN.md
  - .planning/phases/04-pure-core-feature-strategy-planner/04-02-SUMMARY.md
  - .planning/phases/04-pure-core-feature-strategy-planner/04-03-PLAN.md
  - .planning/phases/04-pure-core-feature-strategy-planner/04-03-SUMMARY.md
  - .planning/phases/04-pure-core-feature-strategy-planner/04-04-PLAN.md
  - .planning/phases/04-pure-core-feature-strategy-planner/04-04-SUMMARY.md
  - params/breakout-retest/baseline-v1.toml
  - params/range-mr/baseline-v1.toml
  - params/trend-pullback/baseline-v1.toml
  - src/core/__init__.py
  - src/core/_decimal.py
  - src/core/features.py
  - src/core/planner.py
  - src/core/strategy.py
  - src/core/types.py
  - src/domain/__init__.py
  - src/domain/canonical.py
  - src/domain/enums.py
  - src/domain/registry.py
  - tests/conftest.py
  - tests/fixtures/phase4/candles.csv
  - tests/fixtures/phase4/expected_features.json
  - tests/fixtures/phase4/expected_plans.json
  - tests/fixtures/phase4/expected_signals.json
  - tests/fixtures/phase4/parameters.json
  - tests/test_candle_close_timing.py
  - tests/test_core_features.py
  - tests/test_core_planner.py
  - tests/test_core_strategy_breakout_retest.py
  - tests/test_core_strategy_range_mr.py
  - tests/test_core_tracer.py
  - tests/test_domain_boundary.py
  - tests/test_domain_enums.py
  - tests/test_domain_no_float.py
  - tests/test_fixture_harness.py
  - tests/test_no_lookahead.py
  - tests/test_prefix_invariance.py
  - tests/test_registry.py
  - tests/test_registry_gate.py
covered_digest: "v2:sha256:6f7ea98e982212793892b90dc33f55940c1400f6c3d84fcff156d75c27b5a39f"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 14/14
  gaps_closed: []
  gaps_remaining: []
  regressions: []
deferred:
  - truth: "Trend-pullback geometry (SL outside zone, confirmed pivots, minimum stop distance) matches the family sheet"
    addressed_in: "Phase 15"
    evidence: "ROADMAP Phase 15 'Strategy Geometry Correction: Trend-pullback SL outside zone, confirmed pivots, min stop distance; families match their sheets'. Phase 4 goal is determinism/no-look-ahead/plan contract, which still holds."
---

# Phase 04: Pure Core — Feature + Strategy + Planner Verification Report

**Phase Goal:** Closed candles in, deterministic setups out — the pure core simulators will consume is fixture-green. (1) Feature engine computes indicators/structure/zones from closed candles only, long-warm-up features report invalid until history suffices. (2) Same snapshot+account+version+config yields byte-identical decision with deterministic SignalId, prefix-invariance passes. (3) Every valid setup becomes a plan with entry zone, SL, TP(s), invalidation, expiry, expected RR, plan hash. (4) No family declared winner — all three remain hypotheses.
**Verified:** 2026-10-03T00:00:00Z
**Status:** passed
**Re-verification:** Yes — the earlier report (2026-09-24) went stale because covered files changed. Later phases did change the core: Phase 4 review fixes (CR-/WR-*), Phase 17-05 canonical decimal hashing and storage-scale quantization of plan Decimals, Phase 13.1 repo-wide ruff reflow, and registry/enum growth (Phases 5, 10, 11, 12, 17). The goal was re-judged against the current tree rather than the old claims.
**Requirements in scope:** STRAT-01, STRAT-02, STRAT-03

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Closed 1H candles through features, trend-pullback evaluate and planner yield byte-identical Signal + TradePlan on repeated runs | ✓ VERIFIED | `test_core_tracer.py` green in this run (238-test gate). Fixtures `expected_signals.json` / `expected_plans.json` were regenerated in 17-05 for the canonical hash and still match byte-exactly |
| 2 | SETUP carries deterministic SignalId via `make_signal_id`, `detected_at_utc` equals source candle close | ✓ VERIFIED | `strategy.py:37,670` import and call `make_signal_id`; tracer and determinism suites green |
| 3 | Plan carries entry zone, SL, TP1/TP2, invalidation, expiry, expected RR, plan_hash, DEFERRED_TO_RISK | ✓ VERIFIED | `planner.py` (502 lines): per-family geometry helpers, invalidation `basis=CANDLE_CLOSE`, `quantization_decision="DEFERRED_TO_RISK"` at line 489; `test_core_planner.py` green. TP1 is now structure-derived (CR-03), and `minimum_rr` is only an acceptance threshold. This is an intentional later change that preserves the contract |
| 4 | Signals/TradePlans use promoted enums with verbatim values; unknown values raise at load | ✓ VERIFIED | `test_domain_enums.py` green (enums file has since grown, with no Phase 4 enum changed) |
| 5 | Every feature output carries valid + reason_code; long-warm-up features report WARMUP_INSUFFICIENT; strategy NO_TRADEs on any required-feature-invalid | ✓ VERIFIED | `features.py:75-225` emit `_invalid(WARMUP_INSUFFICIENT)` before first-emission index; `strategy.py:537-563` gate; `test_core_features.py` and `test_core_tracer.py` green |
| 6 | Missing-candle gaps never synthesize values: GAP_IN_SOURCE becomes DATA_STALE and strategy NO_TRADEs | ✓ VERIFIED | `features.py:392-406`, `strategy.py:559-563`, `planner.py:321`; gap tests green |
| 7 | Duplicates, OHLC violations and timestamp regressions fail closed before any feature computes | ✓ VERIFIED | `compute_features` validation + `Candle.__post_init__`; `test_core_features.py` and `test_domain_boundary.py` green |
| 8 | No-lookahead, prefix-invariance and candle-close-timing suites pass against real `evaluate` behavior | ✓ VERIFIED | All three suites green. `_swing_series` is a trailing window (`candles[i-lookback+1..i]`), so no future bar enters a feature. Forming-bar gate `_is_forming_bar` (`strategy.py:79,604-607`) is intact |
| 9 | 1H setup and 4H context computed independently, with no interpolation or forward-fill | ✓ VERIFIED | `evaluate` calls `compute_features` per stream; multi-timeframe tests green |
| 10 | RR below minimum_rr yields NO_TRADE RR_TOO_LOW, never a downgraded plan | ✓ VERIFIED | `planner.py:397,414` return `PlanResult(is_no_trade=True, reason_code=RR_TOO_LOW)`; boundary tests green. Stale, foreign or empty-stream signals also return NO_TRADE rather than raising (CR-02/08, WR-14) |
| 11 | plan_hash is a recomputable single-hasher digest over (signal_id + entry + SL + TPs + invalidation + expiry) | ✓ VERIFIED | `_plan_hash` (`planner.py:71`) calls `sha256_hex`. Since 17-05 the three Decimals are hashed as `canonical_decimal_text`, so the hash is spelling-invariant and re-derivable from the stored PG row. `test_plan_hash_recomputable_from_payload` green |
| 12 | breakout-retest emits deterministic SETUP/NO_TRADE with retest countdown from breakout-bar close | ✓ VERIFIED | `test_core_strategy_breakout_retest.py` green; fixture signal and plan present |
| 13 | range-mr emits deterministic SETUP/NO_TRADE; range-break invalidates, never redraws | ✓ VERIFIED | `test_core_strategy_range_mr.py` green; fixture signal and plan present |
| 14 | No family declared winner; all three share one harness | ✓ VERIFIED | `strategy.py:26` carries the only winner statement (the no-winner declaration). Families B/C route through shared `compute_features` and the single `plan()` |

**Score:** 14/14 truths verified (0 present-but-behavior-unverified; every behavior-dependent truth has a passing behavioral test)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|--------------|----------|
| 1 | Trend-pullback SL outside zone, confirmed pivots, min stop distance, families matching their sheets | Phase 15 | ROADMAP Phase 15 goal. This is a geometry-quality concern, not a Phase 4 determinism/contract criterion |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/core/__init__.py` | Barrel re-export | ✓ VERIFIED | 41 lines, re-exports only |
| `src/core/_decimal.py` | Single pinned-prec Decimal helpers (WR-16) | ✓ VERIFIED | 61 lines; strings/ints only, never floats |
| `src/core/types.py` | Frozen dataclasses with guards | ✓ VERIFIED | 358 lines; PlanResult consistency guard |
| `src/core/features.py` | EMA/ATR/swing/zone, validity flags, gap and quality gates | ✓ VERIFIED | 445 lines, Decimal-only |
| `src/core/strategy.py` | Pure evaluate + 3 families + SignalId | ✓ VERIFIED | 704 lines; no I/O, clock, randomness or env reads |
| `src/core/planner.py` | Full plan contract, RR gate, hash | ✓ VERIFIED | 502 lines |
| `src/domain/enums.py`, `registry.py`, `canonical.py` | Promoted enums, family B/C keys, canonical decimal text | ✓ VERIFIED | Tests green |
| `params/*/baseline-v1.toml` | Phase 4 baselines (v2 to v5 added later, v1 retained) | ✓ VERIFIED | All three present; registry tests green |
| `tests/fixtures/phase4/*` | candles, parameters, expected features/signals/plans | ✓ VERIFIED | Present; regenerated in 17-05 and consumed byte-exactly by tests |
| Core and determinism test files | Real-expectation suites | ✓ VERIFIED | 14 files, all green |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `strategy.evaluate` | `ids.make_signal_id` | SignalId | ✓ WIRED | `strategy.py:37,670` |
| `planner.plan` | `canonical.sha256_hex` and `canonical_decimal_text` | plan_hash | ✓ WIRED | `planner.py:28,71` |
| `planner.plan` | `strategy._detect_*_setup` | Families B/C re-derive zone edge from the same candles | ✓ WIRED | `planner.py` geometry helpers |
| `planner.plan` | `derive_child_id` | `trade_plan:v1` | ✓ WIRED | tracer test equality |
| strategy/planner | `registry.ParameterSet` | Sole parameter source | ✓ WIRED | grep for `float`, `getenv`, `open(`, `datetime.now`, `utcnow` and `import random/os/time` over `src/core`: zero matches |
| Downstream consumers | `src.core` | backtest, paper, execution import the core | ✓ WIRED | Consumed by `src/backtest/*`, `src/paper/*`, `src/execution/placement.py` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `strategy.evaluate` | Signal fields | Closed-candle features + registry params | Yes (tracer and fixture suites) | ✓ FLOWING |
| `planner.plan` | Entry/SL/TP/RR/hash | Recomputed features + detector zones + signal | Yes (byte-exact fixture plans) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 4 test gate | `pytest tests/test_core_*.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_domain_{boundary,enums,no_float}.py tests/test_registry*.py tests/test_fixture_harness.py` (.venv, offline) | 238 passed, 0 failed | ✓ PASS |
| Lint | `ruff check src/core src/domain` | All checks passed | ✓ PASS |
| Types | `mypy src/core src/domain` | Success: no issues in 19 source files | ✓ PASS |
| Purity scan | grep over `src/core` for float, env, clock, random and file I/O | 0 matches | ✓ PASS |
| No-float guard covers the core | `tests/test_domain_no_float.py` lists `src/core/*` | Green | ✓ PASS |

### Probe Execution

No phase-declared or conventional probes exist for this phase. Skipped.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| STRAT-01 | 04-01, 04-02 | Feature engine, closed candles only, warm-up gates | ✓ SATISFIED | Truths 5-9 |
| STRAT-02 | 04-01, 04-02, 04-04 | Pure strategy, deterministic SignalIds, NO_TRADE/SETUP | ✓ SATISFIED | Truths 1, 2, 8, 12, 13 |
| STRAT-03 | 04-01, 04-03, 04-04 | Planner: zone, SL, TPs, invalidation, expiry, RR, hash | ✓ SATISFIED | Truths 3, 10, 11 |

No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/core/*.py` | — | `TBD/FIXME/XXX/TODO/HACK` scan | ℹ️ Info | Zero matches. Debt-marker gate clean |
| `src/core/planner.py` | 41 | `# noqa: F401` re-export of `_decimal` helpers (compat shim) | ℹ️ Info | Intentional and documented |

### Notes

- The ROADMAP marks Phase 4 `mode: mvp` but its goal is not in "As a ..., I want ..., so that ..." form, so the user-story guard does not apply. Verification used the standard goal-backward method, as in the prior report.
- ROADMAP checkbox for Phase 4 is still `[ ]`. That is bookkeeping and does not affect goal achievement.
- Later phases (14, 15) are scheduled to correct backtest causality and strategy geometry. The audit's look-ahead findings concerned the simulator, not `src/core`. Core remains trailing-window and closed-candle-only.

### Human Verification Required

None.

### Gaps Summary

No gaps. The Phase 4 goal still holds on the current repo: deterministic, look-ahead-free, Decimal-only pure core, fixture-green after the later changes.

---

_Verified: 2026-10-03T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
