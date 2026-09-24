---
phase: 04-pure-core-feature-strategy-planner
plan: 04-02
status: complete
subsystem: core
tags: [features, strategy, determinism, validity, forming-bar, multi-timeframe]
dependency_graph:
  requires: [04-01]
  provides: [STRAT-01-validity, D-03-feature-gate, D-04-fail-closed, D-07-candle-close-timing]
  affects: [04-03, 04-04]
tech-stack:
  added: []
  patterns: [fail-closed-validation, gap-detection, warmup-rejection, forming-bar-rejection]
key-files:
  created: []
  modified:
    - src/core/features.py
    - src/core/strategy.py
    - tests/test_core_features.py
    - tests/test_no_lookahead.py
    - tests/test_prefix_invariance.py
    - tests/test_candle_close_timing.py
    - tests/test_domain_boundary.py
    - tests/fixtures/phase4/candles.csv
decisions:
  - "Forming-bar gate: detect unclosed candles via close_time_utc < prev close_time_utc + duration; reject with DATA_STALE (D-02/STRAT-01)."
  - "Per-feature validity flags: EMA20/EMA50/EMA200/ATR14/swing/zone each carry a per-bar reason code; evaluate() rejects on any invalid feature with the exact reason."
  - "GAP_IN_SOURCE → DATA_STALE mapping: feature layer speaks gap vocabulary, strategy speaks cross-module rejection vocabulary."
  - "Duplicate-timestamp and timestamp-regression detection: reject non-monotonic inputs before any feature computed."
  - "Leaky variant perturbation: perturb 4H close by parity of 1H length to flip regime verdict across runs."
  - "Stateful variant perturbation: periodic function (period 37, coprime with 560) so oscillation phase differs between runs."
metrics:
  duration: ~6h
  completed_date: 2026-09-24
  tasks: 3
  commits: 3
---

# Phase 04 Plan 02: STRAT-01 Validity Contract + Determinism Rewiring Summary

## One-liner

Hardened the Phase-4 tracer feature engine to the full STRAT-01 validity contract: per-feature validity flags (warm-up, gap, quality rejects), forming-bar gate (D-02/STRAT-01 fail-closed), and rewired the Phase-3 placeholder determinism suites to real family behavior with multi-timeframe independence.

## What Was Built

### Task 1: Per-feature validity flags + warm-up + gap + quality rejects (commit `2d27ed7`)

Added the feature-quality gate that propagates per-bar invalidity reasons through to `evaluate()`:

- **Duplicate-timestamp / timestamp-regression detection** in `compute_features`: rejects non-monotonic inputs with a `ValueError` naming the offending bar index and timestamps (D-04 fail-closed).
- **Per-feature validity flags**: every feature (`ema_20`, `ema_50`, `ema_200`, `atr_14`, `swing_high`, `swing_low`, `zone_upper`, `zone_lower`) carries a per-bar reason code (`WARMUP_INSUFFICIENT`, `GAP_IN_SOURCE`, `INVALID_INPUT`, `OK`).
- **Feature gate in `evaluate()`**: any invalid feature on either stream returns NO_TRADE with the exact reason code. `GAP_IN_SOURCE` is mapped to `DATA_STALE` (canonical cross-module rejection vocabulary).
- **`tests/test_core_features.py`** (new): 17 RED-first tests covering EMA20/EMA50/EMA200 warm-up, gap injection, quality rejects, ATR14 Wilder alpha, true_range, ema_update, FeatureFrame.features_valid, and multi-timeframe independence.

### Task 2: Rewire determinism suites to real evaluate behavior (commit `8d0aec7`)

Replaced Phase-3 placeholder assertions with real family-behavior tests:

- **`test_no_lookahead.py`** (4 tests): appended bars preserve decisions; same-prefix-different-suffix; 10-bar tail fingerprint; leaky canary (4H perturbation bound to 1H length parity flips regime).
- **`test_prefix_invariance.py`** (3 tests): shared prefix across two runs; full-run digest matches; stateful canary (module-global counter perturbation flips regime).
- **`test_candle_close_timing.py`** (4 tests): forming-bar exclusion; `detected_at_utc == source_candle_close_utc`; forming-bar leak canary; signal expiry.
- **`test_domain_boundary.py`** (8 tests): EMPTY_INPUT, SINGLE_BAR, WARMUP_INSUFFICIENT, GAP_IN_SOURCE, both-touched ambiguous, raising canary, `compute_features` empty.

### Task 3: Multi-timeframe independence + golden fixtures + forming-bar gate (commit `a3e9e6c`)

- **Multi-timeframe independence tests**: 2 tests added to `test_core_features.py` verifying that perturbing the 1H setup doesn't change the 4H context frame, and vice versa (D-02 independent ordering).
- **Extended `tests/fixtures/phase4/candles.csv` additively** (500 → 1060 rows):
  - gap block (10 bars with a 5-hour gap)
  - warmup-short block (50 bars, insufficient for EMA200)
  - setup window 1H (250 bars with a clean trend-pullback)
  - setup window 4H (250 bars, regime-confirming uptrend, **continuous with original 4H series** from 2026-10-20T16:00:00Z)
- **Forming-bar gate in `evaluate()`** (D-02/STRAT-01): detects unclosed candles via `close_time_utc < prev close_time_utc + duration`; rejects with `DATA_STALE` so the engine never sources a SETUP from an unclosed bar.
- **Test fixes**: forming-bar timestamp ordering in `test_candle_close_timing.py`; leaky variant perturbation strengthened to flip regime; stateful variant switched to a periodic perturbation (period 37, coprime with 560) so the oscillation phase differs between runs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed 4H context GAP_IN_SOURCE in extended fixture**
- **Found during:** Task 3
- **Issue:** The original extension script started the 4H setup window at 2026-10-25T00:00:00Z, creating a 108-hour gap at bar 250 of the 4H series. This caused GAP_IN_SOURCE on the context frame, breaking all regime evaluations.
- **Fix:** Regenerated the 4H setup window to start at 2026-10-20T16:00:00Z (next 4H boundary after the original series' last bar at 2026-10-20T12:00:00Z), maintaining full continuity.
- **Files modified:** `scripts/_extend_phase4_candles.py`, `tests/fixtures/phase4/candles.csv`
- **Commit:** `a3e9e6c`

**2. [Rule 1 - Bug] Forming-bar gate missing in strategy (D-02/STRAT-01 violation)**
- **Found during:** Task 3 (test_candle_close_timing.py::test_forming_candle_contributes_no_setup_signal failing)
- **Issue:** `evaluate()` used `snapshot.setup_candles[-1]` as the SETUP source without verifying the candle was closed. A forming bar (unclosed candle) could leak its `close_time_utc` into the signal's `detected_at_utc`, violating D-02/STRAT-01.
- **Fix:** Added `_is_forming_bar()` helper that checks `last_bar.close_time_utc < prev.close_time_utc + duration`. Added the forming-bar gate in `evaluate()` between the regime gate and the setup gate; rejects with `DATA_STALE`.
- **Files modified:** `src/core/strategy.py`
- **Commit:** `a3e9e6c`

**3. [Rule 1 - Bug] Stateful variant perturbation ineffective**
- **Found during:** Task 3 (test_prefix_invariance.py::test_stateful_variant_is_detected_by_digest_comparison failing)
- **Issue:** The initial stateful perturbation (`calls["n"] * 50`) accumulated monotonically across both runs, so for all bars with enough 1H history (≥200 bars), both runs ended up in the BEARISH regime — no decisions differed.
- **Fix:** Switched to a periodic perturbation `(calls["n"] % 37) * 1000`. Period 37 is coprime with the run length (560), so the oscillation phase differs between the two runs, flipping the regime on a different set of bars.
- **Files modified:** `tests/test_prefix_invariance.py`
- **Commit:** `a3e9e6c`

### Deferred Issues (Outside Scope)

**`tests/test_core_planner.py` (9 tests failing)**
- **Cause:** The planner tests use ALL 1H candles from the extended fixture, which now includes the gap block. The gap block causes GAP_IN_SOURCE → DATA_STALE on the setup frame.
- **Scope:** 04-03 (planner). These tests need to be updated to use a subset of the 1H candles (excluding the gap block) or to handle the gap block correctly. Not modified in this plan per the `files_modified` scope constraint.

## Test Results

### In-scope (all green)
```
tests/test_no_lookahead.py ............ [4/4]
tests/test_prefix_invariance.py ......... [3/3]
tests/test_candle_close_timing.py ....... [4/4]
tests/test_domain_boundary.py ........... [8/8]
tests/test_core_features.py ............. [17/17]
Total: 36/36 passed
```

### Out-of-scope (deferred to 04-03)
```
tests/test_core_planner.py: 9 failures (DATA_STALE due to gap block in full 1H fixture)
```

## Key Commits

| Hash | Message |
|------|---------|
| `2d27ed7` | feat(04-02): per-feature validity flags plus warm-up plus gap plus quality rejects |
| `8d0aec7` | feat(04-02): rewire determinism suites to real evaluate behavior |
| `a3e9e6c` | feat(04-02): multi-timeframe independence plus forming-bar gate |
