# Phase 15: Strategy Geometry Correction - Pattern Map

**Mapped:** 2026-10-06
**Files analyzed:** 27 (new or modified)
**Analogs found:** 27 / 27 (all analogs are git-tracked; verified for params, tests, scripts, fixtures)

All line numbers refer to the working tree as read this session. Re-check after any merge touching `src/core` or `src/domain/registry.py`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/core/pivots.py` (new; or inside features.py) | utility (pure feature) | transform | `src/core/features.py` `_swing_series` (166-193) | role-match |
| `src/core/features.py` (add optional `pivot_high/low` to frame) | feature engine | transform | itself, `FeatureFrame(` single construction site (features.py:424) | exact |
| `src/core/planner.py` (shared `_geometry_rejection`, Family A geometry D-05) | service (pure) | request-response | itself, `_long_geometry` 91-148, gates 382-415 | exact |
| `src/core/strategy.py` (`_detect_setup` pivot level; B anchoring/direction; C regime on 4H pivots) | service (pure) | transform | itself, `_detect_setup` 128-162, `_resolve_regime` 98-120 | exact |
| `src/domain/registry.py` (keys `pivot_left_bars`, `pivot_right_bars`, `min_stop_atr`, `tp_mode`, `geometry_version`) | config/validator | validation | itself, Phase 12 keys (lines 105-130, 284-350) | exact |
| `src/domain/rationale.py` (new) | utility | file-I/O + validation | `src/domain/registry.py` TOML loader (`tomllib`, raw-string extraction) | role-match |
| `src/paper/freeze.py` (`pin_stream_epoch` PLACEHOLDER refusal) | service | request-response | itself, `pin_stream_epoch` 340-406 | exact |
| `params/trend-pullback/baseline-v6.toml` | config | static | `params/trend-pullback/baseline-v5.toml` | exact |
| `params/breakout-retest/baseline-v6.toml`, `params/range-mr/baseline-v6.toml` | config | static | same family `baseline-v5.toml` | exact |
| `params/trend-pullback/baseline-no-trade-v4.toml`, `baseline-simple-trend-v4.toml` | config | static | `baseline-no-trade-v3.toml`, `baseline-simple-trend-v3.toml` | exact |
| `tests/test_core_pivots.py` (new) | test | unit/property | `tests/test_prefix_invariance.py`, `tests/test_no_lookahead.py` | role-match |
| `tests/test_planner_geometry.py` (new) | test | unit | `tests/test_core_planner.py`, `tests/test_phase6_fixture_geometry.py` | role-match |
| `tests/test_geometry_property.py` (new) | test | property | `tests/test_prefix_invariance.py` | partial |
| `tests/test_core_strategy_geometry.py` (new) | test | unit | `tests/test_core_strategy_breakout_retest.py` | role-match |
| `tests/test_rationale.py` (new) | test | unit | `tests/test_registry.py` `_load_tmp` helpers (~855-990) | role-match |
| `tests/test_registry.py` (extend) | test | unit | itself, working_type tests | exact |
| `tests/test_paper_freeze.py` (extend) | test | unit | itself | exact |
| `tests/test_domain_no_float.py` (extend `SCANNED_FILES`) | test | scan | itself (list at ~30-60) | exact |
| `tests/fixtures/phase15/geometry_cases.json` + `DERIVATIONS.md` (new) | fixture | static | `tests/fixtures/phase14/DERIVATIONS.md` + `*/expected.json` | exact |
| `tests/fixtures/phase6/**`, `tests/fixtures/phase7/parity_overlapping_history/**` (regenerate) | fixture | generated | `scripts/gen_phase6_fixtures.py` | exact |
| `scripts/gen_phase6_fixtures.py` (V-shaped dip, v6 identity; CRLF fix) | script | batch | itself | exact |
| `scripts/decision_alignment/params.py` (PA-08) | script/gate | validation | itself, PA-07 `check_phase12_set_facts` (line ~262), `PHASE12_SET_IDS` (113) | exact |
| `tests/fixtures/phase4/parameters.json` (append pins) | fixture | static | itself (20 entries) | exact |
| `tests/test_decision_alignment_params.py`, `tests/test_analytics_files.py` (counts/ids) | test | unit | themselves | exact |
| `scripts/smoke_backtest_realdata.py` (default id to `baseline-v6`) | script | batch | itself (line ~93) | exact |
| `docs/research/families/{trend-pullback,breakout-retest,range-mr}.md`, `docs/DECISIONS.md` (D054), `docs/GLOSSARY.md` (line ~181) | docs | static | D048/D053 rows in `docs/DECISIONS.md` | role-match |
| migrated backtest/paper tests (simulator, experiment, determinism, engine_strategy, cost_parity, paper_parity, phase6_fixture_geometry) | test | unit | each existing file | exact |

## Pattern Assignments

### `src/core/pivots.py` (utility, transform)

**Analog:** `src/core/features.py` `_swing_series` (lines 166-193). Same helpers (`_ok`, `_invalid`, `REASON_WARMUP_INSUFFICIENT`), Decimal only, `candles: list[Candle]`, raises `ValueError` on bad lookback.

```python
def _swing_series(candles: list[Candle], lookback: int, *, high: bool) -> list[FeatureOutput]:
    if lookback <= 0:
        raise ValueError(f"swing lookback must be > 0, got {lookback}")
    out: list[FeatureOutput] = []
    for i in range(len(candles)):
        if i < lookback - 1:
            out.append(_invalid(REASON_WARMUP_INSUFFICIENT))
            continue
        window = candles[i - lookback + 1 : i + 1]   # line 187: INCLUDES bar i (the defect)
        ...
```

**Core pattern to implement** (RESEARCH "Code Examples", Pattern 1): `pivot_at(candles, i, *, lookback, left, right, high) -> Decimal | None`, scanning `t` from `i - right` down to `max(left, i - lookback + 1)`; window `[t-left, t+right]` never passes bar `i`; tie rule non-strict left, strict right (Assumption A1). Last-bar-only, not a full series (performance). Return `None` when none found (strategy then returns None, never falls back to the trailing extreme, D-03). Do not fold pivot validity into `features_valid` (Pitfall 2).

**No-float rule:** add `src/core/pivots.py` and `src/domain/rationale.py` to `SCANNED_FILES` in `tests/test_domain_no_float.py` (list contains `"src/core/features.py"`, `"src/core/strategy.py"`, `"src/core/planner.py"` at ~lines 35-37).

---

### `src/core/features.py` (add optional pivot fields)

**Analog:** itself. `FeatureFrame` constructed in exactly one place (features.py:424); `compute_features` at 320-438 calls `_swing_series`/`_zone_series` at 382-386 and AND-s 8 features into `features_valid` (412-422). Add defaulted optional `pivot_high`/`pivot_low` fields in `src/core/types.py` (FeatureFrame, lines 176-206) and leave legacy `swing_*`/`zone_*` untouched (B/C use them; Phase 4 fixtures and `test_core_features` stay valid).

---

### `src/core/planner.py` (service, request-response)

**Analog:** itself.

**Current Family A geometry to change** (lines 109-118, stop inside zone):
```python
if strategy_id == "trend-pullback":
    half = _mul(zone_tolerance_atr, atr)
    support_upper = _add(swing_low, half)
    support_lower = _sub(swing_low, half)
    return (support_upper, support_lower, _sub(swing_low, sl_buffer), swing_high)
```
D-05: replace `swing_low/high` with the confirmed pivot `P`; the stop becomes `entry_min - sl_buffer` (LONG) / `entry_max + sl_buffer` (SHORT). `entry_buffer` is only computed in `plan()` (line 341), so pass it into `_long_geometry/_short_geometry` or compute the stop after `entry_min`. TP1 = opposite confirmed pivot via `pivot_at` over `setup_candles`; missing pivot returns `STALE_SETUP`.

**Fail-closed return idiom** (reuse for every new rejection, lines 371-376, 393-398):
```python
return PlanResult(
    is_no_trade=True,
    trade_plan=None,
    reason_code=RejectionReason.STALE_SETUP.value,
)
```

**Insertion point for the shared validator** (after quantization, lines 382-392, before RR gate at 408):
```python
entry_min = quantize_for_storage(_sub(zone_lower, entry_buffer))
entry_max = quantize_for_storage(_add(zone_upper, entry_buffer))
stop_loss = quantize_for_storage(stop_loss)
take_profit_1 = quantize_for_storage(take_profit_1)
entry_ref = _div(_add(entry_min, entry_max), _q("2"))
risk = abs(_sub(entry_ref, stop_loss))
```
Validator sketch and fixed order (RESEARCH "Shared geometry validator"): SL outside whole zone -> `STOP_TOO_TIGHT`; signal bar through SL -> `INVALIDATED`; `|entry_ref-SL| < min_stop_atr*ATR` -> `STOP_TOO_TIGHT` (only when key present); TP1 on loss side (`leg <= 0`) -> `RR_TOO_LOW`; then the existing RR gate. One private function called by `plan()` for all families (D-06 "one place"). `signal_low/high` come from `setup_candles[-1]`.

**RR gate defect to fix** (line 409): `realized_rr = _div(abs(_sub(tp1, entry_ref)), risk)` uses `abs()`; keep the gate but add the profit-side check first (F6).

**Parameter pull idiom** (lines 264-279): optional new keys must be read with `parameter_set.params.get("min_stop_atr")` and wrapped in `Decimal(str(...))` like the existing Decimal coercion block; absent key = legacy behavior.

**B/C geometry changes** (gated by `geometry_version`, D-25): B stop moves to the narrow S/R zone far edge minus `sl_buffer` (D-23); C target to range midpoint when `tp_mode`/`geometry_version` set (D-10). Keep `_detect_breakout_retest_setup` / `_detect_range_mr_setup` re-derivation (CR-05) and the all-None -> `STALE_SETUP` convention.

---

### `src/core/strategy.py` (service, transform)

**Analog:** itself.

**`_detect_setup` to rewrite** (lines 128-162): currently reads `setup_frame.swing_low/high` (trailing, includes bar i) and tests `support_lower <= last_setup_candle.low <= support_upper` (157). Keep the touch test and return tuple `("LONG", "TREND_PULLBACK_LONG", support_upper, support_lower)`; change only the level source to the pivot, gated by presence of `pivot_left_bars` (legacy path kept for `baseline-v1..v5`, Assumption A4). `None` return maps to existing `NO_TRADE_REGIME`.

**Regime proxy to reuse for A/B** (lines 98-120, `_resolve_regime`): NEUTRAL only on exact EMA50 equality (Flag F1). For C (D-22), add a second resolver using confirmed 4H pivots (HH+HL = BULLISH, LH+LL = BEARISH, else NEUTRAL) built on `pivot_at`; keep `_resolve_regime` signature for A/B. Evaluate dispatch at strategy.py:592: `if parameter_set.strategy_id == "range-mr" and regime != "NEUTRAL":`.

**B anchoring (D-24):** `_detect_breakout_retest_setup` scans `for i in range(n - 1, breakout_confirmation_bars - 1, -1)` (257) and searches the retest from `i + 1` (293); require the retest bar index to equal `n - 1`, plus with-direction check against regime. Existing offset test at `tests/test_core_strategy_breakout_retest.py` ~700-733 ("Beh. 4c") shows how reference-bar offsets are asserted.

**Leakage proofs (D-13):** B reference `ref_prev = ref_bar - 1` (259-262), C `ref_idx = last_idx - 1` (401-404): both exclude the evaluated bar; tests append an extreme evaluated bar and assert the zone is unchanged.

---

### `src/domain/registry.py` (config/validator)

**Analog:** itself, the Phase 12 optional-key block.

**Key whitelist** (lines 116-129):
```python
# Phase 12 (D-06, D-07, D-11). Optional: absent in sets that predate
# Phase 12, like working_type, so every older set keeps loading and
# keeps its parameter_set_hash.
"exit_slippage_rate",
"min_stop_distance_rate",
"max_cost_to_risk",
"commission_rate_ttl_seconds",
```
Add `pivot_left_bars`, `pivot_right_bars`, `min_stop_atr`, `tp_mode`, `geometry_version` with the same comment style.

**Type sets** (284-316): int keys go in `INT_KEYS` (add `pivot_left_bars`, `pivot_right_bars`, `geometry_version`); string key `tp_mode` in `STRING_KEYS`; `DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS - STRING_KEYS` picks up `min_stop_atr` automatically.

**Range branch** (`_check_value_range`, 319-350):
```python
elif key == "min_stop_distance_rate":
    if not (Decimal(0) < number < Decimal(1)):
        raise StrategyKeyOutsideRegistry(
            f"{path}: parameter {key!r} = {value} must be within the open "
            f"interval (0, 1) as a fraction of price (D-07)"
        )
```
Closed-value-set check for string keys sits next to `if key == "working_type" and value not in WORKING_TYPE_VALUES:` (line 372). Cross-key rule (both pivot keys or neither; `pivot_right_bars + 1 <= swing_lookback`) goes in `_parse_and_validate`.

---

### `src/domain/rationale.py` (new utility)

**Analog:** `src/domain/registry.py` TOML loading (`tomllib`, `_extract_raw_param_strings` stops at the next `[` header, registry.py:217-219, hash payload only `[parameters]` at 471-477). Provide `check_rationale(path) -> list[str]` and `placeholder_keys(path) -> list[str]`; each `[rationale.<key>]` table has `basis` (STRUCTURAL | COST_GUARD | DECISION | EXPERIMENT | PLACEHOLDER), `text`, and `value` (compared with the parsed parameter, Pitfall 6). Hash neutrality verified in RESEARCH Pattern 4. Never create a separate `.toml` under `params/` (read as a set by PA-01).

---

### `src/paper/freeze.py` (`pin_stream_epoch`)

**Analog:** itself, lines 340-406. Signature today:
```python
def pin_stream_epoch(*, strategy_id: str, parameter_set_id: str, opened_at_utc: datetime,
                     cost_model: CostModel | None = None, registry_root: Path | None = None) -> StreamEpoch:
    _require_utc_aware(opened_at_utc, "opened_at_utc")
    root = registry_root if registry_root is not None else REGISTRY_ROOT
    parameter_set = _load_parameter_set_with_root(strategy_id, parameter_set_id, root)
```
Add `allow_unrationalized: bool = False`; after loading, call `placeholder_keys` / `check_rationale` on the set file and raise a typed exception (model on the existing `UnregisteredParameterSet`/`CostModelBindingMismatch` raise style) unless allowed. Legacy call sites to pass `True`: `tests/test_paper_freeze.py:122,178,213,276,357,412`, `tests/test_cost_per_unit.py:681,695`. Extend the Raises docstring.

---

### `params/<family>/baseline-v6.toml` (config)

**Analog:** `params/trend-pullback/baseline-v5.toml` (full file read). Copy the header-comment convention (Supersedes, "stays byte-identical (F-810)", "Changes versus baseline-v5" list), `schema_version = 1`, `[strategy]` with `strategy_version = "v5.0.0"`, `[parameters]` with inline per-line comments, then append `[rationale.<key>]` tables.

```toml
schema_version = 1

[strategy]
strategy_id = "trend-pullback"
strategy_version = "v4.0.0"      # -> "v5.0.0" in v6

[parameters]
swing_lookback = 20
zone_tolerance_atr = 0.5
...
```
Add `pivot_left_bars = 3`, `pivot_right_bars = 3`, `min_stop_atr = 0.5` (PROPOSED, ratify in `checkpoint:decision`); B/C add `geometry_version = 1`; omit or mark INERT the dead keys `regime_filter_lookback` and `breakout_volume_threshold` (Pitfall 7). `-v4` degenerate baselines follow the same prefix (`baseline-no-trade-`, `baseline-simple-trend-`, `src/analytics/family.py:22`) and must carry the pivot keys (F7).

---

### Tests

**`tests/test_core_planner.py`** (analog for `tests/test_planner_geometry.py`): imports block (lines 20-33):
```python
from src.core.features import compute_features
from src.core.planner import plan
from src.core.types import AccountState, Candle, PlanResult
from src.domain.canonical import canonical_decimal_text, quantize_for_storage, sha256_hex
from src.domain.enums import RejectionReason, TradePlanStatus
from src.domain.registry import ParameterSet, load_parameter_set
```
Candle builder pattern at lines 40-60 (`close_time = open_time + bar_duration - timedelta(seconds=1)`). Its last bar is "patched to touch support", which must migrate to a hand-built pivot structure plus `baseline-v6`.

**`tests/test_phase6_fixture_geometry.py`** (analog for independent literal arithmetic, cost facts lines ~59-69, no-trade assertion `RR_TOO_LOW` at 199-202 to update per F7, `test_fixture_carries_phase12_identity` asserts `baseline-v5` / `v4.0.0`, move to `baseline-v6` / `v5.0.0`).

**`tests/test_registry.py`** (analog for key tests, ~855-990): helper `_load_tmp(tmp_path, body)` writes a temp set and loads it with `registry.REGISTRY_ROOT = tmp_path`; copy the working_type trio (accepts / rejects parametrized literals / set-without-key still loads) for each new key, plus `NaN`/bool rejection and old-set hash unchanged.

**`tests/fixtures/phase15/DERIVATIONS.md` + `geometry_cases.json`:** copy `tests/fixtures/phase14/DERIVATIONS.md` discipline (header: every expected value from independent `Decimal` one-liners with no project imports; `expected.json` written by hand; nothing in the repo writes an expectation). Reuse its "Common inputs" table layout (symbol, parameter set, equity/risk_rate, fees, tick/step/min notional).

**Prefix-invariance / no-lookahead tests** (`tests/test_prefix_invariance.py`, `tests/test_no_lookahead.py`): analog for D-04 (pivot at `i` computed from `candles[:i+1]` equals full-series value; pivot absent at `t+R-1`, present at `t+R`).

---

### Gates and pins

**`scripts/decision_alignment/params.py`:** add `PHASE15_SET_IDS` next to `PHASE12_SET_IDS` (line 113) and a `check_phase15_set_facts` modeled on `check_phase12_set_facts` (~262); register in `run()` next to `_result("PA-07", ...)` (~336) as `PA-08`. Update docstring ("PA-01..PA-07").
**`tests/test_decision_alignment_params.py:44-48`** (`len(gate.load_pins()) == 20`) and **`tests/test_analytics_files.py:59-69`** (`_EXPECTED_CANDIDATE_IDS`) get the new ids and counts.

## Shared Patterns

### Decimal-only arithmetic
**Source:** `src/core/_decimal.py` (`_mul/_add/_sub/_div/_q`), `src/domain/canonical.py` `quantize_for_storage`
**Apply to:** pivots, planner geometry, validator. No `float`; `tests/test_domain_no_float.py` scans the listed files.

### Fail-closed NO_TRADE with existing reason codes
**Source:** `src/domain/enums.py:131-155` (`RejectionReason`, 20 members); `src/backtest/records.py:441` (`build_reject_record` raises on non-enum codes)
**Apply to:** every new rejection. Mapping: SL not outside zone and `min_stop_atr` -> `STOP_TOO_TIGHT`; signal bar through SL -> `INVALIDATED`; TP wrong side or RR low -> `RR_TOO_LOW`; vanished pivot at plan time -> `STALE_SETUP`. No enum member added (RESEARCH section 5); update only the GLOSSARY prose at line ~181.

### Optional presence-gated registry key (hash-neutral for old sets)
**Source:** `src/domain/registry.py:116-129, 284-350`
**Apply to:** `pivot_*`, `min_stop_atr`, `tp_mode`, `geometry_version`. Absent key = legacy path = identical `parameter_set_hash`.

### Versioned, never-edited param sets
**Source:** `params/trend-pullback/baseline-v5.toml` header ("stays byte-identical for reproducing past hashes (F-810)")
**Apply to:** all `baseline-v6` and `-v4` baseline files; never edit v1..v5.

### Hand-derived goldens
**Source:** `tests/fixtures/phase14/DERIVATIONS.md`
**Apply to:** all Phase 15 geometry expectations; regenerated Phase 6 fixtures keep generator-written `input.json` only.

### Single regeneration inventory in DECISIONS
**Source:** D048/D053 rows in `docs/DECISIONS.md` (single-line table row; next id D054)
**Apply to:** D054 listing moved fixtures, pins, signal ids, plan hashes, kept deviations, new keys and set ids.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| Range regime on confirmed 4H pivots (inside strategy.py, D-22) | service | transform | No structure-based regime exists; only the EMA50 proxy. Build on new `pivot_at`, per RESEARCH Open Question 2 |
| Rationale record (`[rationale.<key>]` tables + `rationale.py`) | utility | validation | No existing in-file metadata convention; use RESEARCH Pattern 4 and registry TOML parsing idioms |
| Geometry-violation counter for smoke (F8) | script | batch | `TradeRecord` has no stop/zone fields (records.py:80-120); define zero-violation as exit 0, equal digests, canonical reasons, plus planner property test |

## Notes for the planner

- Local env: `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` already fails on CRLF checkouts (F12); normalize line endings or add `.gitattributes` eol rule before regeneration.
- `scripts/gen_phase6_fixtures.py` builds a monotonic uptrend that has no confirmed pivot low; it needs a deliberate V-shaped dip before bar 249.
- `src/risk/gating.py:41-61` docstring says a stop inside the zone is deliberately not rejected; stale after this phase (optionally strengthen `_plan_geometry_is_valid`).
- Ripple estimate from RESEARCH section 6: about 72 failing tests with the invariant alone (simulator 30, planner 10, experiment 8, determinism 5, engine-strategy 4, paper parity 3, cost parity 3, phase6 geometry 9).

## Metadata

**Analog search scope:** `src/core`, `src/domain`, `src/paper`, `params/`, `tests/`, `tests/fixtures/phase14`, `scripts/decision_alignment`
**Files read directly:** planner.py (85-503), features.py (160-239), strategy.py (90-164), registry.py (105-350), freeze.py (340-410), baseline-v5.toml, test_core_planner.py (1-60), test_registry.py (855-935), phase14 DERIVATIONS.md (1-40), plus CONTEXT.md and RESEARCH.md in full
**Tool note:** ripgrep unavailable in the Grep tool (ENOENT); used `grep` via Bash. CodeGraph not consulted (no `.codegraph` check needed; direct reads sufficed).
**Pattern extraction date:** 2026-10-06
