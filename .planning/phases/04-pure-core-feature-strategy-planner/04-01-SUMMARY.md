---
phase: 04-pure-core-feature-strategy-planner
plan: 01
type: execute
subsystem: src/core (pure deterministic strategy core)
tags: [phase-4, tracer, pure-core, features, strategy, planner, d-06-enums, fixtures]
dependency_graph:
  requires: []
  provides:
    - src/core/__init__.py
    - src/core/types.py
    - src/core/features.py
    - src/core/strategy.py
    - src/core/planner.py
    - D-06 enum promotions (Direction, SetupType, SourceTimeframe, EntryModel, OrderRole, QuantizationDecision)
    - tests/fixtures/phase4/ golden fixtures
    - conftest phase4_* loader fixtures
    - extended SCANNED_FILES for no-float AST guard
  affects:
    - src/domain/enums.py (6 new enums)
    - src/domain/__init__.py (re-exports)
    - tests/conftest.py (phase4_* fixtures)
    - tests/test_domain_no_float.py (SCANNED_FILES extension)
    - tests/test_domain_enums.py (14 new enum tests)
tech-stack:
  added: []
  patterns:
    - stdlib + Decimal only (D-10 purity)
    - frozen dataclasses with construction-time guards
    - canonical SHA256 hash identity (D-04/D-08)
    - per-feature validity flags (D-03)
    - fail-closed quality gates (D-04)
    - gap detection with flag-never-fabricate
    - GLOSSARY-consistent enum values (D-06)
key-files:
  created:
    - src/core/__init__.py
    - src/core/types.py
    - src/core/features.py
    - src/core/strategy.py
    - src/core/planner.py
    - tests/test_core_tracer.py
    - tests/fixtures/phase4/candles.csv
    - tests/fixtures/phase4/parameters.json
    - tests/fixtures/phase4/expected_features.json
    - tests/fixtures/phase4/expected_signals.json
    - tests/fixtures/phase4/expected_plans.json
    - scripts/_compute_phase4_fixtures.py
  modified:
    - src/domain/enums.py
    - src/domain/__init__.py
    - tests/conftest.py
    - tests/test_domain_no_float.py
    - tests/test_domain_enums.py
decisions:
  - EMA uses alpha=2/(n+1) TA-Lib convention, SMA-seeded, first emission at 0-based index period-1
  - ATR uses Wilder alpha=1/n, SMA-of-TR seeded, first emission at index period-1
  - Family A Stage A baseline: R1 structure-only regime (EMA50 proxy for byte-exact reproducibility) + P1 zone touch + E2 zone+ATR buffer entry + S2 structure+ATR buffer SL + T1 fixed-R TP
  - Regime gate only requires EMA50 validity (not all features); setup gate requires all features valid
  - TP2 extension = 2 * minimum_rr (simple documented rule; refined under 04-03 checkpoint)
  - Planner recomputes features on the setup stream (single deterministic computation path)
  - quantitization_decision = "DEFERRED_TO_RISK" string token (D-09; Phase 5 owns stepSize math)
  - Direction/SetupType/SourceTimeframe values copy GLOSSARY verbatim; SourceTimeframe uses lowercase "1h"/"4h"/"1m" matching phase-3 fixture spelling
metrics:
  duration: ~25 min
  completed_date: 2026-09-23
status: complete

actuals:
  tokens: 88000
  tasks: 3
  commits: 4
---

# Phase 4 Plan 01: Pure Core (Feature + Strategy + Planner) Summary

## One-liner

Tracer-first slice: dependency-free src/core (features + strategy + planner) wired to the trend-pullback/baseline-v1 registry set, emitting byte-exact Signal + TradePlan outputs on closed 1H + 4H candles, with D-06 enum promotions and phase4 golden fixtures in place.

## What was built

### `src/core/` — dependency-free pure core (D-10)

| File | Role |
|------|------|
| `src/core/__init__.py` | Barrel re-export; no logic |
| `src/core/types.py` | Frozen `Candle` (OHLCV validated at construction), `FeatureOutput` (valid + reason_code), `FeatureFrame` (whole-bar summary), `SetupResult` (NO_TRADE\|SETUP envelope), `MarketSnapshot`, `AccountState` |
| `src/core/features.py` | `compute_features`, `ema_update`, `true_range` — EMA(20/50/200) TA-Lib convention, ATR(14) Wilder convention, swing H/L trailing-window extrema, ATR-half-width zones, gap detection (flag-never-fabricate) |
| `src/core/strategy.py` | Pure `evaluate(snapshot, account_state, strategy_version, parameter_set) -> SetupResult` — 4H regime gate + 1H setup gate + SignalId via `make_signal_id` with `detected_at_utc = source_candle_close_utc` |
| `src/core/planner.py` | Pure `plan(signal, setup_candles, parameter_set, account_state, created_at_utc) -> TradePlan` — entry zone, SL, TP1/TP2, invalidation JSON, expiry, plan_hash via canonical SHA256, quantization_decision = DEFERRED_TO_RISK |

Every arithmetic operation runs inside a pinned `localcontext(prec=28)`; every Decimal is built from a string (D-12). No third-party imports — stdlib + Decimal only.

### D-06 enum promotions (`src/domain/enums.py`)

Six new enums promoted with GLOSSARY-consistent values:

| Enum | Values |
|------|--------|
| `Direction` | `LONG`, `SHORT` |
| `SetupType` | `TREND_PULLBACK_LONG`, `TREND_PULLBACK_SHORT`, `BREAKOUT_RETEST_LONG`, `BREAKOUT_RETEST_SHORT`, `RANGE_MR_LONG`, `RANGE_MR_SHORT` |
| `SourceTimeframe` | `M1 = "1m"`, `H1 = "1h"`, `H4 = "4h"` |
| `EntryModel` | `LIMIT_ZONE`, `MARKET` |
| `OrderRole` | `ENTRY`, `STOP_LOSS`, `TAKE_PROFIT_1`, `TAKE_PROFIT_2` |
| `QuantizationDecision` | `DEFERRED_TO_RISK`, `ACCEPTED`, `REJECTED` |

Unknown values stay load-time errors via `Enum(value)` raising `ValueError`. All six re-exported from `src/domain/__init__.py`.

### Phase 4 fixtures (`tests/fixtures/phase4/`)

- `candles.csv` — 250 1H + 250 4H BTCUSDT closed candles (enough history to warm up EMA200 on both timeframes)
- `parameters.json` — pinned registry set with real `parameter_set_hash` from `load_parameter_set`
- `expected_features.json` — byte-exact expected feature values
- `expected_signals.json` — byte-exact expected Signal (signal_id recomputes via `make_signal_id`)
- `expected_plans.json` — byte-exact expected TradePlan (plan_hash matches canonical SHA256)

### Conftest loaders (`tests/conftest.py`)

Five new session fixtures mirroring the phase3 pattern: `phase4_candles`, `phase4_parameters`, `phase4_expected_features`, `phase4_expected_signals`, `phase4_expected_plans`.

### No-float guard extension (`tests/test_domain_no_float.py`)

`SCANNED_FILES` extended with the five `src/core/*` modules — the AST walker now flags any float shape (literal, `float()` call, `Decimal(float)` constructor) in the pure core, enforcing D-10.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed 4H context bar alignment for EMA200 warm-up**

- **Found during:** Task 3 (fixture generation)
- **Issue:** Initial fixture had only 60 4H bars; EMA200(4H) requires 200 bars to warm up, causing `features_valid=False` and forcing NO_TRADE.
- **Fix:** Extended 4H fixture to 250 bars (base date shifted from 2026-09-18 to 2026-09-09). Same uptrend pattern, just more history.
- **Files modified:** `scripts/_compute_phase4_fixtures.py`

**2. [Rule 1 - Bug] Extended 1H fixture to 250 bars for EMA200 warm-up**

- **Found during:** Task 3 (fixture generation)
- **Issue:** Initial 1H fixture had 60 bars; EMA200(1H) requires 200 bars, causing `features_valid=False` and forcing NO_TRADE even after the regime gate passed.
- **Fix:** Extended 1H fixture to 250 bars with a warm-up phase (190 bars of gentle uptrend) followed by the original pullback pattern. The pullback/zone-touch logic at the end is unchanged.
- **Files modified:** `scripts/_compute_phase4_fixtures.py`

**3. [Rule 2 - Missing critical functionality] Regime gate uses only EMA50 validity, not full features_valid**

- **Found during:** Task 1 (tracer implementation)
- **Issue:** The initial regime gate checked `context_frame.features_valid` (AND of all features), which forced NO_TRADE whenever EMA200(4H) was warming up — making the regime gate impractical for any realistic 4H history depth.
- **Fix:** The regime gate now checks only the features it needs (EMA50 for the BULLISH/BEARISH/NEUTRAL verdict). The whole-bar `features_valid` gate still applies to the setup gate (which requires EMA20, swing, zone, ATR).
- **Files modified:** `src/core/strategy.py`

**4. [Rule 3 - Blocking issue] Planner API needed setup_candles parameter**

- **Found during:** Task 1 (tracer test)
- **Issue:** The initial planner signature took pre-computed ATR/swing/zone values as parameters, but the test had no easy way to obtain those values from the feature computation without exposing internal state.
- **Fix:** Planner now takes `setup_candles` and recomputes features internally — same deterministic computation path as the strategy (single source of truth). Cleaner API; no double-computation cost since both paths are pure.
- **Files modified:** `src/core/planner.py`

**5. [Rule 1 - Bug] Test fixture type annotations updated from `list[dict]` to `list[Candle]`**

- **Found during:** Task 1 (test run)
- **Issue:** The test fixtures built candle dicts and passed them directly to `MarketSnapshot(setup_candles=...)`, but `MarketSnapshot.setup_candles` is typed `list[Candle]` — TypeError at runtime.
- **Fix:** Fixtures now convert dicts to `Candle(**row)` objects before passing to the core.
- **Files modified:** `tests/test_core_tracer.py`

**6. [Rule 3 - Blocking issue] Pure-function test was matching docstring text**

- **Found during:** Task 1 (test run)
- **Issue:** The pure-function test scanned the full file text for forbidden tokens, which matched the word "pandas" in a docstring describing what NOT to import.
- **Fix:** Test now uses `ast.walk` to inspect only `Import` and `ImportFrom` nodes — docstrings are correctly excluded.
- **Files modified:** `tests/test_core_tracer.py`

## Verification Results

All automated verify commands passed:

| Command | Result |
|---------|--------|
| `uv run pytest tests/test_core_tracer.py -q` | 5 passed |
| `uv run pytest tests/test_domain_enums.py -q` | 26 passed (12 existing + 14 new) |
| `uv run pytest tests/test_domain_no_float.py tests/test_fixture_harness.py -q` | 11 passed |
| `uv run pytest tests/ -q --ignore=tests/test_domain_mappers_pg.py` | 240 passed |
| `uv run ruff check src/core tests/test_core_tracer.py` | 0 findings |

The tracer happy-path test verified:
- `signal_id` matches `make_signal_id` with canonical inputs
- `entry_min_price < entry_max_price` (LONG setup)
- `stop_loss_price < entry_min_price` (LONG setup)
- `quantization_decision == "DEFERRED_TO_RISK"`
- `trade_plan_id == derive_child_id(signal_id, "trade_plan:v1")`
- Plan hash is byte-identical across reruns

## Acceptance Criteria

### Task 1 (tracer)

- [x] `src/core/` contains exactly `__init__.py`, `types.py`, `features.py`, `strategy.py`, `planner.py`, each opening with `from __future__ import annotations`
- [x] AST-walked import check: zero forbidden imports (polars, pandas, numpy, binance, sqlalchemy, pydantic)
- [x] `tests/test_core_tracer.py` passes with 5 tests covering happy-path, sensitivity, purity, warm-up, and SignalId

### Task 2 (D-06 enums)

- [x] Import of `Direction`, `SetupType`, `SourceTimeframe`, `EntryModel`, `OrderRole`, `QuantizationDecision` from `src.domain` succeeds
- [x] `Direction.LONG.value == "LONG"` and `Signal(direction=Direction.LONG, ...)` constructs (str-subclass compatibility)
- [x] `tests/test_domain_enums.py` passes with 14 new enum tests

### Task 3 (fixtures + guard)

- [x] `phase4_candles`, `phase4_parameters`, `phase4_expected_features`, `phase4_expected_signals`, `phase4_expected_plans` fixtures exist and load byte-exact
- [x] `SCANNED_FILES` contains the five `src/core/` entries; no-float guard passes
- [x] `expected_signals.json` signal_id matches `make_signal_id` canonical construction

## Key Trade-offs / Notes

- **TP2 extension rule (2 * minimum_rr)** is a simple documented constant; the reversibility note in the plan flags this for refinement under the 04-03 checkpoint before fixtures freeze. Acceptable for the tracer slice because D-08 says "never a downgraded plan" — the RR gate still enforces `minimum_rr` as a hard floor.
- **Family A Stage A baseline** uses EMA50 as a deterministic proxy for the R1 structure-only regime (rather than a full HH/HL/LH/LL structure detector). This keeps the regime gate byte-exact reproducible and testable; the full R1/R2/R3 alternatives land in family B/C slices (plans 04-03/04-04).
- **Planner recomputes features** rather than consuming pre-computed values — keeps a single deterministic computation path. The strategy and planner share the same `compute_features` function; no double-source-of-truth.

## Self-Check

- [x] All 5 src/core files exist
- [x] All 5 phase4 fixture files exist
- [x] All 4 commits recorded (RED test, GREEN impl, D-06 enums, fixtures+guard)
- [x] Full test suite green (240 tests)
- [x] Ruff clean on src/core + tests/test_core_tracer.py

## Self-Check: PASSED

**Commits:**
- `97d0e4e` — `test(04-01): RED tracer end-to-end test pins src/core contract`
- `df27af6` — `feat(04-01): GREEN src/core tracer slice (features + strategy + planner)`
- `35d3dbb` — `feat(04-01): D-06 enum promotion — Direction, SetupType, SourceTimeframe, EntryModel, OrderRole, QuantizationDecision`
- `44770c0` — `feat(04-01): phase4 fixtures plus conftest loaders plus no-float guard extension`
