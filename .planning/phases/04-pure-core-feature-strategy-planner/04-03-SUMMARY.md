---
phase: 04-pure-core-feature-strategy-planner
plan: 03
type: execute
subsystem: src/core (pure deterministic strategy core)
tags: [phase-4, planner-contract, registry-extension, family-b, family-c, d-05, d-08, d-09]
dependency_graph:
  requires:
    - src/core/planner.py (tracer interim TP2 rule)
    - src/domain/registry.py (STRATEGY_KEYS whitelist)
    - params/trend-pullback/baseline-v1.toml (tracer seed)
    - tests/fixtures/phase4/candles.csv (tracer fixture)
  provides:
    - PlanResult frozen dataclass (discriminated NO_TRADE-or-TradePlan envelope)
    - Full D-08/D-09 planner contract (RR gate, hash, expiry, invalidation, deferred quantization)
    - Extended STRATEGY_KEYS with 7 family B/C keys (D-05)
    - params/breakout-retest/baseline-v1.toml (Family B baseline)
    - params/range-mr/baseline-v1.toml (Family C baseline)
    - tests/fixtures/phase4/parameters.json (pins all three sets)
    - tests/fixtures/phase4/expected_plans.json (byte-exact TradePlan with new invalidation schema)
  affects:
    - src/core/types.py (PlanResult added)
    - src/core/planner.py (returns PlanResult; invalidation schema updated)
    - src/domain/registry.py (STRATEGY_KEYS + INT_KEYS extended)
    - tests/test_core_tracer.py (handles PlanResult return type)
    - tests/test_core_planner.py (new — 11 RED→GREEN tests)
tech-stack:
  added: []
  patterns:
    - PlanResult discriminated union (NO_TRADE | TradePlan)
    - Hard RR gate returning NO_TRADE (never a downgraded plan)
    - Invalidation JSON schema: basis=CANDLE_CLOSE + level + break_distance_atr
    - entry_ref = zone mid for LIMIT_ZONE (04-03 checkpoint:decision option A)
    - TP2 extension = 2 * minimum_rr (04-03 option A)
    - Registry whitelist extension via reviewed change (D-05)
key-files:
  created:
    - tests/test_core_planner.py
    - params/breakout-retest/baseline-v1.toml
    - params/range-mr/baseline-v1.toml
  modified:
    - src/core/types.py
    - src/core/planner.py
    - src/domain/registry.py
    - tests/test_core_tracer.py
    - tests/fixtures/phase4/parameters.json
    - tests/fixtures/phase4/expected_plans.json
decisions:
  - TP2 rule (04-03 checkpoint:decision option A): TP2 = entry_ref + 2 * minimum_rr * risk, where entry_ref = zone mid for LIMIT_ZONE plans. TP1 = entry_ref + minimum_rr * risk.
  - Setup fingerprint key list (04-03 checkpoint:decision): family id, variant codes, regime verdict + confirming 4H bar closes, trigger 1H bar close, zone bounds, ATR value at decision time.
  - source_timeframe spelling (04-03 checkpoint:decision): setup timeframe using exact spelling from tests/fixtures/phase3/candles.csv (lowercase "1h", "4h", "1m"); 4H context folded into fingerprint, never a composite string.
  - SetupType tokens (04-03 checkpoint:decision): TREND_PULLBACK_LONG/SHORT, BREAKOUT_RETEST_LONG/SHORT, RANGE_MR_LONG/SHORT (six values from 04-01).
  - Invalidation JSON schema: basis=CANDLE_CLOSE, level=stop_loss_price, break_distance_atr=sl_buffer_atr*ATR (family-specific break distance).
  - RR gate is a hard gate returning PlanResult(is_no_trade=True, reason_code=RR_TOO_LOW) — never a downgraded TP1-only plan.
  - PlanResult envelope: is_no_trade=True requires trade_plan=None; is_no_trade=False requires a TradePlan.
  - Registry whitelist extended with 7 family B/C keys (D-05); 4 keys assigned to INT_KEYS, rest to DECIMAL_KEYS.
metrics:
  duration: ~20 min
  completed_date: 2026-09-23
status: complete

actuals:
  tokens: 52000
  tasks: 3
  commits: 2
---

# Phase 4 Plan 03: Full Planner Contract + Registry Extension Summary

## One-liner

Frozen TradePlan output contract per D-08/D-09 with PlanResult envelope, hard RR gate returning NO_TRADE, and registry whitelist extended with 7 family B/C keys plus two new baseline TOMLs.

## Checkpoint:decision Record (Task 1)

Auto-selected **option A** (auto mode active, gate=non-blocking):

| Decision | Value |
|----------|-------|
| **TP2 rule** | TP2 = entry_ref + 2 * minimum_rr * risk, where entry_ref = zone mid for LIMIT_ZONE plans. TP1 = entry_ref + minimum_rr * risk. |
| **Fingerprint key list** | family id, variant codes, regime verdict + confirming 4H bar closes, trigger 1H bar close, zone bounds, ATR value at decision time |
| **source_timeframe spelling** | setup timeframe using exact spelling from tests/fixtures/phase3/candles.csv (lowercase "1h", "4h", "1m"); 4H context folded into fingerprint, never a composite string |
| **SetupType tokens** | TREND_PULLBACK_LONG, TREND_PULLBACK_SHORT, BREAKOUT_RETEST_LONG, BREAKOUT_RETEST_SHORT, RANGE_MR_LONG, RANGE_MR_SHORT |

## What was built

### `src/core/types.py` — PlanResult envelope

New frozen dataclass `PlanResult` (discriminated NO_TRADE-or-TradePlan envelope):

```python
@dataclass(frozen=True)
class PlanResult:
    is_no_trade: bool
    trade_plan: TradePlan | None = None
    reason_code: str = "OK"
```

Construction-time guards enforce `is_no_trade=True` requires `trade_plan=None` and vice versa.

### `src/core/planner.py` — Full D-08/D-09 contract

- **Return type changed**: `plan()` now returns `PlanResult` instead of `TradePlan` directly.
- **RR gate**: Returns `PlanResult(is_no_trade=True, reason_code=RR_TOO_LOW)` instead of raising `ValueError`. Hard gate — never a downgraded TP1-only plan.
- **Invalidation JSON schema** (D-08):
  ```json
  {"basis": "CANDLE_CLOSE", "level": "<stop_loss_price>", "break_distance_atr": "<sl_buffer_atr * ATR>"}
  ```
- **entry_ref**: Zone mid for LIMIT_ZONE plans (04-03 option A).
- **TP2 extension**: 2 * minimum_rr (04-03 option A).
- **plan_hash**: SHA256 over canonical JSON of `signal_id`, `entry_min_price`, `entry_max_price`, `stop_loss_price`, `take_profit_json`, `invalidation_rule_json`, `expiry_utc` — recomputable by hand.
- **trade_plan_id**: `derive_child_id(signal_id, "trade_plan:v1")`.
- **Quantization**: `quantity_after_rounding == quantity_before_rounding`, `quantization_decision = "DEFERRED_TO_RISK"` (D-09; Phase 5 owns stepSize math).

### `src/domain/registry.py` — Whitelist extension (D-05)

Extended `STRATEGY_KEYS` with 7 new family B/C keys:

| Key | Family | Type |
|-----|--------|------|
| `retest_window_bars` | B (breakout-retest) | INT |
| `retest_depth_atr` | B | DECIMAL |
| `breakout_volume_threshold` | B | DECIMAL |
| `zone_min_touches` | C (range-mr) | INT |
| `zone_aging_bars` | C | INT |
| `range_break_buffer_atr` | C | DECIMAL |
| `regime_filter_lookback` | C | INT |

Extended `INT_KEYS` with 4 new int keys; rest assigned to `DECIMAL_KEYS` via `STRATEGY_KEYS - INT_KEYS`.

### `params/breakout-retest/baseline-v1.toml` — Family B baseline

Schema_version 1, strategy_id "breakout-retest", strategy_version "v1.0.0". Nine shared keys at tracer values plus three Family B keys: `retest_window_bars=5`, `retest_depth_atr=0.3`, `breakout_volume_threshold=1.5`.

### `params/range-mr/baseline-v1.toml` — Family C baseline

Schema_version 1, strategy_id "range-mr", strategy_version "v1.0.0". Nine shared keys at tracer values plus four Family C keys: `zone_min_touches=2`, `zone_aging_bars=50`, `range_break_buffer_atr=0.2`, `regime_filter_lookback=50`.

### `tests/fixtures/phase4/parameters.json` — Three-set pin

Pins all three parameter sets with their `parameter_set_hash`:

| Strategy | Hash |
|----------|------|
| trend-pullback/baseline-v1 | `e1579900b1be20b8a6db76c554255cbec8125d5d317f6df7dadd5de78d2afae5` |
| breakout-retest/baseline-v1 | `dbcf730f2f9e5585b3661331f7738334d26341cc28fc170754a2168498dab56d` |
| range-mr/baseline-v1 | `2997f262349da8e5ba7af7837820a7a47fd9e83d6adcf3d316b0e19272f1c1c0` |

### `tests/fixtures/phase4/expected_plans.json` — Byte-exact TradePlan

Regenerated with new invalidation JSON schema. `plan_hash` updated to `032808e3f1df892cc75197383251e8386d78b1531cf7232246c90ed17d06c870` (was `a33e7c21635ba27605a7d369869104c3b6a310647a4aa0e6ad9f263fd912a1f7`).

### `tests/test_core_planner.py` — 11 RED→GREEN tests

| Test | Behavior |
|------|----------|
| `test_entry_zone_math_long` | entry_max = zone_upper + entry_buffer_atr * ATR; entry_min = zone_lower - entry_buffer_atr * ATR; stop = swing_low - sl_buffer_atr * ATR |
| `test_rr_gate_exact_equality_passes` | TP1 RR exactly equal to minimum_rr is admitted |
| `test_rr_gate_one_tick_above_passes` | RR one tick above minimum_rr is admitted |
| `test_rr_gate_below_returns_no_trade_with_rr_too_low` | RR below minimum_rr returns NO_TRADE with RR_TOO_LOW |
| `test_plan_hash_recomputable_from_payload` | plan_hash equals sha256_hex over documented payload |
| `test_trade_plan_id_derives_from_signal_id` | trade_plan_id = derive_child_id(signal_id, "trade_plan:v1") |
| `test_expiry_equals_source_close_plus_signal_expiry_hours` | expiry_utc = source_candle_close_utc + signal_expiry_hours |
| `test_invalidation_json_schema` | invalidation JSON carries basis=CANDLE_CLOSE, level, break_distance_atr |
| `test_deferred_quantization_equality` | quantity_after_rounding == quantity_before_rounding, DEFERRED_TO_RISK |
| `test_planner_has_no_float_literals` | AST guard: no float literals or float() calls in planner.py |
| `test_plan_result_envelope_validation` | PlanResult enforces is_no_trade/trade_plan consistency |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Registry.py reverted by concurrent commit**

- **Found during:** Task 3 (registry extension)
- **Issue:** A concurrent commit (2d27ed7, feat(04-02)) had reset `src/domain/registry.py` to the pre-extension state, causing `load_parameter_set` to raise `StrategyKeyOutsideRegistry` for the new family B/C keys.
- **Fix:** Re-applied the STRATEGY_KEYS and INT_KEYS extensions. Verified all three parameter sets load with stable hashes.
- **Files modified:** `src/domain/registry.py`

**2. [Rule 3 - Blocking issue] Fixture files reverted by concurrent commit**

- **Found during:** Task 3 (fixture update)
- **Issue:** The `expected_plans.json` and `parameters.json` fixture updates were lost when the concurrent commit reset the working tree.
- **Fix:** Re-wrote both fixtures with the new content (three-set pin in parameters.json; new invalidation JSON schema in expected_plans.json).
- **Files modified:** `tests/fixtures/phase4/parameters.json`, `tests/fixtures/phase4/expected_plans.json`

**3. [Rule 3 - Blocking issue] Test file deleted by `rm` command**

- **Found during:** Task 2 (TDD)
- **Issue:** An earlier `rm tests/test_core_planner.py` command (used to clear the file before rewriting) accidentally deleted the committed file from the working tree.
- **Fix:** Restored from HEAD via `git checkout HEAD -- tests/test_core_planner.py`.
- **Files modified:** `tests/test_core_planner.py`

## Verification Results

All automated verify commands passed:

| Command | Result |
|---------|--------|
| `uv run pytest tests/test_core_planner.py -q` | 11 passed |
| `uv run pytest tests/test_registry.py tests/test_registry_gate.py tests/test_core_tracer.py -q` | 33 passed |
| `uv run pytest tests/test_core_planner.py tests/test_registry.py tests/test_registry_gate.py tests/test_core_tracer.py -q` | 44 passed |
| `uv run pytest tests/ -q --ignore=tests/test_domain_mappers_pg.py` | 251 passed (1 pre-existing failure in test_no_lookahead.py from concurrent commit 2d27ed7, out of scope) |

The pre-existing test failure in `test_no_lookahead.py::test_leaky_variant_is_detected_by_prefix_comparison` is from the concurrent commit `2d27ed7` (feat(04-02)) and is out of scope for this plan per the deviation rules' scope boundary.

## Acceptance Criteria

### Task 1 (checkpoint:decision)

- [x] SUMMARY names the chosen TP2 formula with entry_ref definition, the exact fingerprint key list, the source_timeframe spelling, and the six SetupType tokens
- [x] At least one planner test recomputes plan_hash from the documented payload fields and matches (`test_plan_hash_recomputable_from_payload`)
- [x] No comparative winner language appears in code, comments, or fixtures

### Task 2 (TDD)

- [x] `tests/test_core_planner.py` contains named tests for entry-zone math, sl math, rr-gate exact-equality plus just-below plus just-above, plan-hash recomputation, expiry, invalidation schema, and deferred-quantization equality
- [x] A plan with TP1 RR exactly equal to minimum_rr is emitted while one Decimal tick below is rejected (both asserted)
- [x] No float literal, float() call, or Decimal float-arg exists in `src/core/planner.py` (guard test green)

### Task 3 (auto)

- [x] `load_parameter_set` for breakout-retest/baseline-v1 and range-mr/baseline-v1 succeeds and returns `parameter_set_hash` identical on repeat loads
- [x] Unknown-key and ambient-key negative gates still pass (existing registry gate tests green unmodified in behavior)
- [x] `params/trend-pullback/baseline-v1.toml` shows zero diff (git diff empty for that file)

## Key Trade-offs / Notes

- **PlanResult envelope** is a breaking change to the planner API. The previous `plan()` returned `TradePlan` directly; it now returns `PlanResult`. Callers must check `is_no_trade` before accessing `trade_plan`. This is necessary per D-08 ("never a downgraded plan") — the RR gate must return NO_TRADE, not raise an exception.
- **Invalidation JSON schema change** (from `basis: "structure_break_candle_close"` to `basis: "CANDLE_CLOSE"` + `level` + `break_distance_atr`) changes the `plan_hash`. The `expected_plans.json` fixture was regenerated to match. This is a one-way change per the plan's reversibility note.
- **TP2 extension rule** (2 * minimum_rr) is the simplest documented constant per 04-03 checkpoint:decision option A. Family C's T-mid vs T-opposite modes are deferred to a future plan when the range-mr strategy is implemented.
- **Concurrent commit 2d27ed7** (feat(04-02)) was made between my Task 2 commit and Task 3 work, resetting the registry and fixture files. I re-applied all changes and verified the final state.

## Self-Check

- [x] All 3 task files exist (planner.py, registry.py, two TOMLs)
- [x] All 2 commits recorded (Task 2 + Task 3)
- [x] Full test suite green for this plan's scope (44 tests)
- [x] Trend-pullback TOML unchanged (git diff empty)
- [x] All three parameter sets load with stable hashes

## Self-Check: PASSED

**Commits:**
- `882cc26` — `feat(04-03): full planner contract — PlanResult envelope, RR gate returns NO_TRADE, invalidation schema (basis=CANDLE_CLOSE + level + break_distance)`
- `efc30e1` — `feat(04-03): registry whitelist extension plus breakout-retest and range-mr baseline TOMLs`
