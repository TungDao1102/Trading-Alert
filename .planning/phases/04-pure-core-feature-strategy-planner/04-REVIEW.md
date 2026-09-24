---
phase: 04-pure-core-feature-strategy-planner
reviewed: 2026-09-24T05:00:00Z
depth: deep
files_reviewed: 24
files_reviewed_list:
  - params/breakout-retest/baseline-v1.toml
  - params/range-mr/baseline-v1.toml
  - src/core/__init__.py
  - src/core/features.py
  - src/core/planner.py
  - src/core/strategy.py
  - src/core/types.py
  - src/domain/__init__.py
  - src/domain/enums.py
  - src/domain/registry.py
  - tests/conftest.py
  - tests/test_candle_close_timing.py
  - tests/test_core_features.py
  - tests/test_core_planner.py
  - tests/test_core_strategy_breakout_retest.py
  - tests/test_core_strategy_range_mr.py
  - tests/test_core_tracer.py
  - tests/test_domain_boundary.py
  - tests/test_domain_enums.py
  - tests/test_domain_no_float.py
  - tests/test_no_lookahead.py
  - tests/test_prefix_invariance.py
  - tests/test_registry.py
  - tests/test_registry_gate.py
findings:
  critical: 8
  warning: 16
  info: 7
  total: 31
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-09-24T05:00:00Z
**Depth:** deep
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Deep review of the Phase 04 pure core (`src/core/` — features, strategy,
planner, types), the `src/domain` registry/enums/ids/canonical boundary, the
two Family B/C TOMLs, and all 14 test files in scope — with cross-file tracing
of the `evaluate → compute_features → detectors → make_signal_id` and
`plan → compute_features → hash/expiry` call chains, plus re-verification of
every prior finding (CR-01..CR-04, WR-01..WR-10, IN-01..IN-04) against current
source after the 04-04 family B/C landing.

**All four prior criticals are still open, unchanged** — the 04-04 landing did
not touch any of them (same line-number neighborhoods, same defective code).
All ten prior warnings and all four prior infos also still hold.

Deep cross-file analysis adds four new criticals: the planner prices plans off
a Family-A zone that is structurally different from the zone the Family B/C
detector actually fired on (CR-05); the Family A touch predicate spans the full
support-to-resistance range for both directions, so LONGs can fire on
resistance touches (CR-06); range-mr has no NEUTRAL-only gate and emits
mean-reversion setups inside trends (CR-07); the planner returns READY plans
for expired/stale signals with no expiry-vs-created or signal-vs-candles
correspondence check (CR-08). Six new warnings cover the unknown-strategy-id
fallthrough, cross-bar ATR mixing, hardcoded indicator periods vs the
`atr_period` knob, planner-side signal correspondence, an overstated Family B
warm-up gate, and the triplicated Decimal helpers whose drift produced CR-04.

Determinism scaffolding remains genuinely good: no wall-clock reads, no
randomness, no float literals, no dict-order dependence in `src/core`, UTC
guards intact, single canonical-hash path (`canonical.sha256_hex`) shared by
registry, signal IDs, fingerprints, and plan hashes.

## Critical Issues

### CR-01: Strategy-semantic knobs outside the registry with silent defaults (still open)

**File:** `src/core/strategy.py:287,433-436`
**Issue:** Unchanged since the prior review. `_detect_breakout_retest_setup`
reads `parameter_set.params.get("atr_period", 14)` (line 287) and
`_detect_range_mr_setup` reads `params.get("atr_period", 14)` and
`params.get("touch_tolerance_atr", "0.3")` (lines 433-436). Neither key is in
`STRATEGY_KEYS` (`src/domain/registry.py:60-81`) — verified again this pass —
so neither can ever appear in a TOML (writing one raises
`StrategyKeyOutsideRegistry`). The detector ATR period and Family C's entire
touch-tolerance band remain fixed code defaults, not versioned parameters.
D-06 violation + fail-open: TOML readers see an incomplete parameter set.
**Fix:**
```python
# Promote to the registry (preferred): STRATEGY_KEYS += {"atr_period", "touch_tolerance_atr"}
# + INT/DECIMAL classification + both baseline TOMLs, then:
atr_period = int(parameter_set.params["atr_period"])  # KeyError, never silent .get()
```

### CR-02: Planner raises instead of returning NO_TRADE (still open)

**File:** `src/core/planner.py:152,157-161,191-194`
**Issue:** Unchanged. Three crash paths where the D-08 envelope demands
NO_TRADE: (1) `setup_candles[0]` (line 152) raises `IndexError` on an empty
list — note `compute_features` itself raises `ValueError` on empty input, so
an empty plan request can never even reach the feature gate; (2) invalid
features (lines 157-161) raise `ValueError` — the exact real scenario (SETUP at
bar N, one more bar/gap arrives making features invalid at plan time) crashes
the caller; (3) `risk <= 0` (lines 191-194) raises `ValueError` where an
`RR_TOO_LOW`/`DATA_STALE` NO_TRADE belongs.
**Fix:**
```python
if not setup_candles:
    return PlanResult(is_no_trade=True, trade_plan=None,
                      reason_code=RejectionReason.DATA_STALE.value)
# ... and for both invalid-features and risk <= 0: return NO_TRADE, never raise.
```

### CR-03: Planner RR gate is vacuous — TP1 is built FROM minimum_rr (still open)

**File:** `src/core/planner.py:197-211`
**Issue:** Unchanged. TP1 is constructed as `entry_ref ± minimum_rr * risk`
(lines 197-202), so `realized_rr = |tp1 - entry_ref| / risk` (line 205) equals
`minimum_rr` by construction and the gate `if realized_rr < minimum_rr` (line
206) can only fire on Decimal last-digit rounding noise. The "second line of
defense" never defends; any caller relying on the planner to catch
below-minimum-RR geometry gets a plan every time.
**Fix:** Derive TP levels from market structure (zone edge / swing projection)
independently of `minimum_rr`, keep `minimum_rr` purely as the acceptance
threshold — or delete the gate and its docstring claim so no caller relies on it.

### CR-04: Precision-context violation — Family B at prec-50, Family C at ambient, everything else at prec-28 (still open, wider than reported)

**File:** `src/core/strategy.py:298-299,318-319,392-398,464,469-481`
**Issue:** Unchanged, and the prior report understated it. The prec-50
`localcontext` block (lines 298-299) is still there with raw `+`/`*` ops at
lines 318-319; `_find_retest_bar` raw ops at line 392 are outside ANY pinned
context (they run at ambient `getcontext().prec`, not even prec-50); and the
entire Family C computation (lines 464, 469, 471, 474, 478, 480 — `band`,
`abs()` touches, `breakout_buffer`, invalidation comparisons) runs at ambient
precision with no `localcontext` at all. So there are now THREE precision
domains (50 / 28 / ambient), and the zone values bound into the setup
fingerprint (prec-50 / ambient paths) are recomputed by the planner at prec-28
— signal-time zone and plan-time zone can differ in trailing digits, forking
fingerprints and plan hashes across processes with different ambient contexts.
**Fix:**
```python
# Route every op through the pinned prec-28 helpers; delete the prec-50 block:
zone_upper = _add(sh_ref_out.value, _mul(zone_tolerance_atr, atr_ref_out.value))
band = _mul(retest_depth_atr, atr_out.value)
```

### CR-05: Planner prices plans off a different zone than the detector fired on (Families B/C)

**File:** `src/core/planner.py:151-172`, `src/core/strategy.py:337,360-364,494-497`, `src/core/features.py:239-274`
**Issue:** New deep finding (cross-file). The signal carries no zone — the
detector's `(direction, setup_type, zone_upper, zone_lower)` tuple is consumed
only for the fingerprint, then discarded. The planner recomputes
`zone_upper`/`zone_lower` via `compute_features`, which ALWAYS builds Family-A
semantics (support centered on trailing swing-low, resistance on trailing
swing-high, `features.py:270-273`) at the LAST bar. But Family B fired on a
zone edge computed at a reference bar `i - confirmation - 1` bars back
(strategy.py:302,318-319), and Family C fired on RAW swing extremes with no
tolerance band (strategy.py:461-462). The planner's entry zone, SL
(`swing_low`/`swing_high` at the last bar), and hence every TP/RR derived from
them do not correspond to the levels that triggered the setup. For B/C the
plan is priced off structurally different levels, not just trailing-digit
disagreement (which is CR-04). The entry/SL/TP of a B/C plan cannot be traced
back to the detected setup.
**Fix:** Thread the detector's zone (and reference swing/ATR) through the
signal — e.g. extend the setup fingerprint payload or a plan-input struct with
`zone_upper`/`zone_lower`/reference levels — and have the planner build entry/SL
from THOSE levels, using `compute_features` only as the validity gate, not the
geometry source. Short-term alternative: document that the planner is Family-A
only and return NO_TRADE for B/C signals until the geometry is threaded.

### CR-06: Family A touch predicate spans the full range for both directions

**File:** `src/core/strategy.py:191-204`, `src/core/features.py:270-273`
**Issue:** New deep finding. `_zone_series` centers `zone_lower` on the swing
LOW (support) and `zone_upper` on the swing HIGH (resistance). But
`_detect_setup` checks LONG as `low <= zone_upper and low >= zone_lower` —
i.e. the 1H low ANYWHERE between the support bottom and the resistance top —
and SHORT symmetrically on the high. A BULLISH-regime bar whose low touches
RESISTANCE (but never comes near support) emits TREND_PULLBACK_LONG; the
predicate is near-tautological inside any normal range. Per
`trend-pullback.md §3` (single swing-low zone for LONG, cited in
`features.py:248-250`), LONG must key off the support zone and SHORT off the
resistance zone. The planner's direction-invariant full-range entry zone
(WR-01) is consistent with this predicate, which suggests the whole Family A
geometry drifted from "zone touch" to "range containment" without updating the
spec — either way, code and spec disagree about what a setup IS.
**Fix:**
```python
if regime == "BULLISH":
    if last_setup_candle.low <= support_upper and last_setup_candle.low >= support_lower:
        return ("LONG", "TREND_PULLBACK_LONG", ...)
elif regime == "BEARISH":
    if last_setup_candle.high >= resistance_lower and last_setup_candle.high <= resistance_upper:
        return ("SHORT", "TREND_PULLBACK_SHORT", ...)
```
using per-side zones, not the cross-range pair.

### CR-07: range-mr has no NEUTRAL-only gate — emits mean-reversion setups inside trends

**File:** `src/core/strategy.py:591-595,617-621`
**Issue:** New deep finding. The regime gate rejects NEUTRAL only for
non-range-mr families (line 591: `if parameter_set.strategy_id != "range-mr"
and regime == "NEUTRAL"`). Nothing rejects BULLISH/BEARISH for range-mr, yet
the detector's own docstring (lines 415-416) states "the 4H context must
resolve to NEUTRAL (handled by the caller — regime gate above rejects
BULLISH/BEARISH for this family)". The caller does no such thing: a
BULLISH-regime snapshot with a range-edge touch emits RANGE_MR_LONG/SHORT.
Fading an established trend as "mean reversion" is exactly the false-positive
class the NEUTRAL gate exists to prevent, and the code comment asserts a guard
that does not exist.
**Fix:**
```python
if parameter_set.strategy_id == "range-mr" and regime != "NEUTRAL":
    return SetupResult(is_no_trade=True, reason_code=RejectionReason.NO_TRADE_REGIME.value)
```

### CR-08: Planner returns READY plans for expired/stale signals with no signal-vs-candles check

**File:** `src/core/planner.py:112-119,150-156,213-214,289`
**Issue:** New deep finding (fail-open). `plan()` never compares `expiry_utc`
(`signal.source_candle_close_utc + signal_expiry_hours`, line 214) against
`created_at_utc` — a signal expired days ago still yields a READY TradePlan
(line 292-296) with an already-past `expiry_utc`. It also never checks that
`signal.symbol` matches the candles' symbol, that
`setup_candles[0].interval` matches `signal.source_timeframe`, or that the
candles' last close corresponds to `signal.source_candle_close_utc` — a
week-old signal replayed against fresh candles (or 1H candles for a 4H signal)
plans without complaint. Combined with WR-07 (strategy never cross-checks
interval vs `source_timeframe` either), there is NO layer that binds a plan to
the market state its signal described. An approved stale plan executes at
levels the market left behind.
**Fix:**
```python
if signal.source_candle_close_utc != setup_candles[-1].close_time_utc:
    return PlanResult(is_no_trade=True, trade_plan=None,
                      reason_code=RejectionReason.STALE_SETUP.value)
if expiry_utc <= created_at_utc:
    return PlanResult(is_no_trade=True, trade_plan=None,
                      reason_code=RejectionReason.APPROVAL_EXPIRED.value)
if signal.symbol != setup_candles[0].symbol or signal.source_timeframe != setup_candles[0].interval:
    return PlanResult(is_no_trade=True, trade_plan=None,
                      reason_code=RejectionReason.DATA_STALE.value)
```

## Warnings

### WR-01: Planner entry zone is direction-invariant (LONG == SHORT) (still open)

**File:** `src/core/planner.py:176-183`
**Issue:** Unchanged — both branches compute byte-identical
`entry_min`/`entry_max` spanning the full support-to-resistance range, with a
mid-range `entry_ref` for both directions. Now reads as the plan-side half of
CR-06 rather than an isolated copy-paste slip.
**Fix:** Differentiate per direction (LONG off support, SHORT off resistance)
once CR-06 defines per-side zones — or collapse to one path with a comment if
full-range is intended.

### WR-02: Family C zone has no tolerance band and eligibility is asymmetric (still open)

**File:** `src/core/strategy.py:461-492`
**Issue:** Unchanged. `zone_upper`/`zone_lower` are raw swing extremes while
Family A uses swing ± tolerance; historical touches count within
`±touch_tolerance_atr*ATR` but current-bar eligibility demands piercing the
exact extreme; the touch scan (`range(swing_lookback, last_idx)`) counts bars
that define the reference level itself.
**Fix:** Same as prior: one band convention, one predicate for historical and
current bars, touches counted strictly before the reference window.

### WR-03: `account_state` is dead in `evaluate`; two risk_rate sources of truth (still open)

**File:** `src/core/strategy.py:506-512`, `src/core/planner.py:140,249`
**Issue:** Unchanged — grep confirms `account_state` appears in `strategy.py`
only in the signature/docstring; planner sizes from
`parameter_set.params["risk_rate"]` while `AccountState` carries its own
`risk_rate` with no consistency check.
**Fix:** Thread `account_state.risk_rate` into the planner as the sizing input,
or assert equality at the boundary and fail closed on mismatch.

### WR-04: Gap inference blind spot at stream start (still open)

**File:** `src/core/features.py:282-313`
**Issue:** Unchanged. `_expected_bar_duration` infers from the first two
candles, so a leading gap is invisible; close-time `-1s` convention is baked
into `expected_open = prev_close + expected` instead of the robust
`prev_open + expected`.
**Fix:** `expected_open = candles[i-1].open_time_utc + expected`, plus fail
closed when the first two bars disagree with the interval-declared duration.

### WR-05: Forming-bar gate covers only the setup stream and only for len >= 2 (still open)

**File:** `src/core/strategy.py:597-609`, `src/core/strategy.py:68-76`
**Issue:** Unchanged. Single-bar snapshots bypass the gate; the 4H context
stream is never examined; `_interval_duration` raises `ValueError` on unknown
intervals instead of NO_TRADE — a pure-core crash path on unexpected input.
**Fix:** Gate both streams, handle the single-bar case, map unknown intervals
to `DATA_STALE` NO_TRADE.

### WR-06: Non-RejectionReason codes leak into the SetupResult envelope (still open)

**File:** `src/core/strategy.py:549-581`
**Issue:** Unchanged. Only `GAP_IN_SOURCE` is mapped (lines 572-573);
`WARMUP_INSUFFICIENT`/`INVALID_INPUT` propagate verbatim, so strict-enum
downstream consumers throw on the common warm-up path.
**Fix:** Map all feature-layer codes at this boundary and assert
`reason_code` membership in `SetupResult.__post_init__`.

### WR-07: Setup interval vs `source_timeframe` never cross-checked (still open)

**File:** `src/core/strategy.py:531-542,649-661`
**Issue:** Unchanged. Features compute on `setup_candles[0].interval` but the
signal is stamped with `snapshot.source_timeframe` unchecked — 1H candles
mislabeled `"4h"` corrupt signal IDs and expiry math. Now compounded by CR-08
(planner doesn't check either, so no layer catches it).
**Fix:** Return `DATA_STALE` NO_TRADE on mismatch at `evaluate`, plus the
planner-side correspondence check in CR-08.

### WR-08: Dead `_regime_from_context` with misleading R1 docstring (still open)

**File:** `src/core/strategy.py:133-152`
**Issue:** Unchanged — grep confirms zero callers; `evaluate` uses
`_resolve_regime`. Still carries the R1/EMA50 design rationale for a function
that decides nothing.
**Fix:** Delete; move the one-paragraph rationale onto `_resolve_regime`.

### WR-09: FeatureOutput allows a stale value to ride along on invalid (still open)

**File:** `src/core/types.py:139-152`
**Issue:** Unchanged. `__post_init__` documents the invariant then `pass`es —
the AND-gate's chokepoint type permits exactly the `.value`-without-`.valid`
bug class it warns about.
**Fix:** Enforce `value is None` when `valid is False`; move last-known-value
carriage to an adapter-local type.

### WR-10: Whitelisted-but-never-read parameters suggest unimplemented gates (still open)

**File:** `src/domain/registry.py:60-81`, `params/breakout-retest/baseline-v1.toml:35`, `params/range-mr/baseline-v1.toml:37`
**Issue:** Unchanged — grep confirms `breakout_volume_threshold`,
`regime_filter_lookback`, `minimum_risk_utilization_after_rounding` appear
nowhere in `src/` outside the registry/TOMLs; the range TOML also ships
`breakout_confirmation_bars` and `zone_tolerance_atr`, which the range
detector never reads. Operators believe a volume filter / regime lookback /
risk-utilization gate is active when no such code exists.
**Fix:** Wire the gates or remove the keys with a pointer to the owning phase.

### WR-11: Unknown strategy_id silently falls through to Family A

**File:** `src/core/strategy.py:611-623`
**Issue:** New deep finding (fail-open). The dispatch is `if breakout-retest /
elif range-mr / else: Family A`. Any other `strategy_id` — typo, retired
family, future family not yet implemented — silently runs trend-pullback logic
and can emit a fully valid-looking SETUP under the wrong family's name. The
registry whitelists parameter KEYS but never validates strategy identity
values, so nothing upstream catches this. An unknown family must be NO_TRADE,
never "default to A".
**Fix:**
```python
else:
    return SetupResult(is_no_trade=True, reason_code=RejectionReason.DATA_STALE.value)
# or validate strategy_id against {"trend-pullback", "breakout-retest", "range-mr"} at the top of evaluate.
```

### WR-12: Cross-bar ATR mixing — zone edges and bands use different bars' ATR

**File:** `src/core/strategy.py:318,388-392,447-464,474`
**Issue:** New deep finding. Family B builds the zone edge with ATR at the
reference bar (`atr_ref_out`, line 318) but sizes the retest band with ATR at
the retest bar (`atr_series[k]`, lines 389-392). Family C takes the zone from
the `last_idx - 1` reference bar (lines 447-462) but sizes both the touch band
(line 464) and the break buffer (line 474) with ATR at `last_idx`. ATR is
adaptive by construction, so edge and band are denominated in different
volatilities; on volatility expansions the band is systematically too wide or
too narrow relative to the edge it guards. Deterministic, but geometrically
incoherent — pick one reference bar per setup and use its ATR for both.
**Fix:** Capture one `(zone, atr_ref)` pair per candidate setup and derive
edge, band, and buffer from that single ATR.

### WR-13: `compute_features` hardcodes EMA 20/50/200 and ATR 14 while detectors take `atr_period`

**File:** `src/core/features.py:383-386`, `src/core/strategy.py:287,433`
**Issue:** New deep finding (dual source of truth, latent). The feature gate,
the fingerprint ATR/EMAs, and the entire planner geometry always use ATR-14,
while the B/C detectors compute their own `_atr_series(setup_candles,
atr_period)`. Today `atr_period` cannot be set (CR-01), so both are 14 by
accident; the moment CR-01 is fixed by promoting the knob, the gate ATR, the
fingerprint ATR, the planner ATR, and the detector ATR silently disagree and
every B/C setup is gated, fingerprinted, and priced on three different
volatilities. The hardcoded periods also mean `swing_lookback` is the only
parameterized feature input — EMA/ATR periods are invisible strategy semantics
outside the registry (CR-01's sibling).
**Fix:** With CR-01, thread `atr_period` (and any EMA-period knobs, or an
explicit "fixed by design" constant) into `compute_features` so gate,
fingerprint, planner, and detector share one ATR series.

### WR-14: Planner never validates signal-vs-candles correspondence

**File:** `src/core/planner.py:112-119,150-156`
**Issue:** New deep finding (companion to WR-07/CR-08, filed separately because
the fix location differs). `plan()` reads `signal.symbol` (line 152) but never
compares it to the candles' symbol, reads `setup_candles[0].interval` (line
153) but never compares it to `signal.source_timeframe`, and never checks
`signal.strategy_id`/`parameter_set_id` against the `parameter_set` it is
planned with. A signal planned with the wrong family's TOML (B signal × A
params) silently produces a geometrically meaningless but well-formed plan.
**Fix:** Assert all four correspondences at the top of `plan()` and return
NO_TRADE on any mismatch (concrete codes proposed in CR-08).

### WR-15: Family B warm-up gate overstates required history (forward window counted as history)

**File:** `src/core/strategy.py:289-292`
**Issue:** New deep finding (missed setups, conservative direction).
`min_bars = breakout_confirmation_bars + retest_window_bars + swing_lookback`
requires `retest_window_bars` of HISTORY, but the window extends FORWARD from
the breakout — it constrains future bars, not past ones. A series with enough
history for a valid breakout+retest but fewer than `min_bars` total bars
returns None without ever scanning. The cost is missed valid setups (fail-safe
direction, but a systematic blind spot in backtest coverage for short
histories), and the formula misleads readers about what the detector needs.
**Fix:** Gate history on `breakout_confirmation_bars + swing_lookback`
(plus ATR warm-up) and let the forward scan handle short windows naturally.

### WR-16: Decimal helpers triplicated across three modules — drift already produced CR-04

**File:** `src/core/features.py:43-83`, `src/core/strategy.py:93-125`, `src/core/planner.py:40-71`
**Issue:** New deep finding (maintainability with a body count). `_q`/`_div`/
`_mul`/`_add`/`_sub` are copy-pasted in all three modules with a comment
claiming "each Phase layer keeps its own guards" (types.py pattern
misapplied — these are identical arithmetic helpers, not layer-specific
validation). The copies already drifted: strategy's detector block uses
prec-50/raw ops while the helpers pin 28, which IS CR-04. Every future
precision change must land in three places or fork hashes again.
**Fix:** Single shared `_decimal.py` (or re-export from `features.py`) with
one `_PREC`; delete the copies. Keep the types.py guard duplication out of
this — construction guards are legitimately layer-local, arithmetic precision
is not.

## Info

### IN-01: `Decimal(str(x))` fallbacks silently bake float noise into Decimals (still open)

**File:** `src/core/features.py:378-379`, `src/core/strategy.py:282-285`, `src/core/planner.py:141-148`
**Issue:** Unchanged. Each boundary converts non-Decimal via `Decimal(str(v))`
instead of rejecting floats; the registry already normalizes TOML floats, so a
float here is a programming error worth failing on.
**Fix:** Raise `TypeError` on float instances at these boundaries.

### IN-02: Bare `int(...)` truncations on Decimal params (still open)

**File:** `src/core/strategy.py:278-287,427-436`, `src/core/planner.py:139`
**Issue:** Unchanged. `int(Decimal("20.9"))` silently truncates; only the TOML
path is protected by `INT_KEYS`, direct `ParameterSet` construction bypasses it.
**Fix:** Integral-value check that raises on fractional input.

### IN-03: Float-based gap helper copy-pasted across four test files (still open)

**File:** `tests/test_no_lookahead.py:50-65`, `tests/test_prefix_invariance.py`, `tests/test_candle_close_timing.py`, `tests/test_core_planner.py:90-107`
**Issue:** Unchanged. Four local `_first_gap_index` variants using
`.total_seconds()` float comparison, already drifted (`replace("Z", "+00:00")`
handling differs).
**Fix:** Single shared helper in `tests/conftest.py`.

### IN-04: Duplicated LONG/SHORT entry-zone bodies (still open)

**File:** `src/core/planner.py:176-183`
**Issue:** Unchanged — character-identical branches (now tracked as CR-06/WR-01
semantics; this item tracks only the duplication itself).
**Fix:** Compute once outside the branch with an intent comment, or
differentiate per WR-01.

### IN-05: Redundant validity re-check on the Family B SHORT path

**File:** `src/core/strategy.py:339-343`
**Issue:** New. The SHORT branch re-checks `sl_ref_out.valid / is None` (lines
339-343), but the identical condition already gated `continue` at lines
309-316 — the re-check can never fire. Dead guard that suggests the author was
unsure of the invariant; harmless but rots (a future edit may "fix" the wrong
branch believing this one is load-bearing).
**Fix:** Delete lines 339-343; the lines 309-316 gate already covers both directions.

### IN-06: Range-mr neutral-regime fixture uses a different close-time convention

**File:** `tests/test_core_strategy_range_mr.py:211`
**Issue:** New (test reliability, not counted as product defect).
`_build_4h_candles_neutral` closes bars at `open + 4h - 1µs` while every other
builder in scope uses `- 1s`. A 999,999µs systematic offset in close times
flows into forming-bar math (`_is_forming_bar` compares close times) and
signal IDs keyed on `source_candle_close_utc`. Currently benign (consistent
within the file), but any cross-fixture close-time comparison involving these
bars is off by ~1s, and the suite cannot catch a forming-bar off-by-one that
lands inside that 1s skew.
**Fix:** Use `- timedelta(seconds=1)` like every other builder.

### IN-07: Signal direction/setup_type/source_timeframe are unvalidated plain strings

**File:** `src/domain/signal.py:52-54,61-73`
**Issue:** New deep finding (boundary). Phase 4 promoted `Direction`,
`SetupType`, `SourceTimeframe` enums (D-06), but `Signal.__post_init__` only
checks non-empty strings — `Signal(direction="LONGG", setup_type="whatever",
source_timeframe="4H")` constructs fine and flows into `make_signal_id`,
permanently forking IDs on casing/typo variants (`"1H"` vs `"1h"` hash
differently). The enums exist precisely to make unknown values a load-time
error; the entity that carries them doesn't use them.
**Fix:** Coerce via `Direction(value)`, `SetupType(value)`,
`SourceTimeframe(value)` in `__post_init__` (str-mixin preserves storage
compatibility, per `test_domain_enums.py:365-394`).

---

_Reviewed: 2026-09-24T05:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
