---
phase: 04-pure-core-feature-strategy-planner
reviewed: 2026-09-24T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - src/core/__init__.py
  - src/core/types.py
  - src/core/features.py
  - src/core/strategy.py
  - src/core/planner.py
  - src/domain/enums.py
  - src/domain/registry.py
  - src/domain/__init__.py
  - params/breakout-retest/baseline-v1.toml
  - params/range-mr/baseline-v1.toml
  - tests/test_domain_boundary.py
  - tests/test_domain_no_float.py
findings:
  critical: 4
  warning: 10
  info: 4
  total: 18
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-09-24T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the Phase 04 pure core (`src/core/` — features, strategy, planner, types),
the D-06 enum promotion + registry whitelist extension, the two new family TOMLs,
and the determinism/boundary/no-float suites. No wall-clock reads, no randomness,
no float literals, no dict-order dependence, and UTC guards are all intact —
the determinism scaffolding is genuinely good.

That said, adversarial reading found four correctness/contract defects that must
be fixed before this ships (strategy knobs living outside the registry with
silent defaults, planner raising instead of returning NO_TRADE, a vacuous RR
gate, and a precision-context violation that makes signal-time and plan-time
zones disagree), plus ten warnings led by a direction-invariant planner entry
zone and an asymmetric Family C zone definition. Details below.

## Critical Issues

### CR-01: Strategy-semantic knobs outside the registry with silent defaults

**File:** `src/core/strategy.py:287,433-436`
**Issue:** `_detect_breakout_retest_setup` reads `parameter_set.params.get("atr_period", 14)`
and `_detect_range_mr_setup` reads `params.get("atr_period", 14)` and
`params.get("touch_tolerance_atr", "0.3")`. Neither `atr_period` nor
`touch_tolerance_atr` is in `STRATEGY_KEYS` (`src/domain/registry.py:60-81`), so
neither can ever appear in a TOML — writing one raises
`StrategyKeyOutsideRegistry`. The detector's ATR period and Family C's entire
touch-tolerance band are therefore fixed code defaults, not versioned
parameters. This is a D-06 violation (strategy semantics must live ONLY in the
registry) and a fail-open pattern: a reader of the TOML believes they see the
full parameter set, but two knobs that change setups are invisible.
**Fix:**
```python
# Option A — promote to the registry (preferred):
# registry.py STRATEGY_KEYS += {"atr_period", "touch_tolerance_atr"}
# + INT/DECIMAL classification + both baseline TOMLs, then:
atr_period = int(parameter_set.params["atr_period"])  # KeyError, never silent .get()
# Option B — if intentionally fixed, name them MODULE constants, not params.get():
_ATR_PERIOD = 14  # fixed by design, not a parameter
```

### CR-02: Planner raises instead of returning NO_TRADE (fail-closed envelope broken)

**File:** `src/core/planner.py:152,157-161,191-194`
**Issue:** `plan()` has three crash paths where the contract (`PlanResult`
discriminated NO_TRADE-or-TradePlan envelope, D-08) demands NO_TRADE:
1) `setup_candles[0]` (line 152) — empty list raises `IndexError`, not
`PlanResult`.
2) invalid features (lines 157-161) — raises `ValueError`. The exact scenario
this must survive is real: strategy emits SETUP at bar N, one more bar arrives
(or a gap is discovered) making features invalid at plan time, and the planner
crashes the caller instead of declining.
3) `risk <= 0` (lines 191-194, e.g. degenerate zero-ATR stream) — raises
`ValueError` where `RR_TOO_LOW`/`DATA_STALE` NO_TRADE belongs.
**Fix:**
```python
if not setup_candles:
    return PlanResult(is_no_trade=True, trade_plan=None,
                      reason_code=RejectionReason.DATA_STALE.value)
# ... and for both invalid-features and risk <= 0:
return PlanResult(is_no_trade=True, trade_plan=None,
                  reason_code=RejectionReason.DATA_STALE.value)
```

### CR-03: Planner RR gate is vacuous — TP1 is built FROM minimum_rr

**File:** `src/core/planner.py:197-211`
**Issue:** TP1 is constructed as `entry_ref ± minimum_rr * risk` (lines 197-202),
so `realized_rr = |tp1 - entry_ref| / risk` (line 205) equals `minimum_rr` by
construction. The gate `if realized_rr < minimum_rr` (line 206) can only fire
on Decimal rounding noise in the last digit. The docstring's "second line of
defense" never defends; any caller relying on the planner to catch a
below-minimum-RR geometry gets a plan every time.
**Fix:** Derive TP levels from market structure (zone edge / swing projection)
independently of `minimum_rr`, keep `minimum_rr` purely as the acceptance
threshold — or delete the gate and its docstring claim so no caller relies on it:
```python
# TP from structure, gate against policy:
tp1 = _add(entry_ref, _mul(structure_extension, risk))  # NOT minimum_rr
realized_rr = _div(abs(_sub(tp1, entry_ref)), risk)
if realized_rr < minimum_rr:
    return PlanResult(is_no_trade=True, trade_plan=None,
                      reason_code=RejectionReason.RR_TOO_LOW.value)
```

### CR-04: Precision-context violation — Family B runs at prec=50, everything else at prec=28

**File:** `src/core/strategy.py:298-299,318-319,392,464,469-481`
**Issue:** `_detect_breakout_retest_setup` opens `localcontext() prec = 50`
while every helper in `features.py`/`planner.py` pins prec 28 (D-10). Inside
that block and in `_find_retest_bar` / `_detect_range_mr_setup`, arithmetic
uses raw `+`/`*`/`-` and `abs()` on Decimals outside any pinned helper
(`zone_upper = sh + tol*atr`, `band = depth*atr`, `abs(high - zone)`,
`zone_lower - breakout_buffer`). Two consequences: (a) results inherit ambient
`getcontext().prec` wherever raw ops run outside the prec-50 block, breaking
the byte-equivalence discipline; (b) the zone values bound into the setup
fingerprint (prec-50 path) are recomputed by the planner at prec-28, so
signal-time zone and plan-time zone can differ in trailing digits — the
fingerprint and the plan disagree about the same named level.
**Fix:**
```python
# Route every op through the pinned helpers; drop the prec-50 block:
zone_upper = _add(sh_ref_out.value, _mul(zone_tolerance_atr, atr_ref_out.value))
band = _mul(retest_depth_atr, atr_out.value)
```

## Warnings

### WR-01: Planner entry zone is direction-invariant (LONG == SHORT)

**File:** `src/core/planner.py:176-183`
**Issue:** The LONG and SHORT branches compute byte-identical
`entry_min`/`entry_max` (`zone_lower - buf` .. `zone_upper + buf`, spanning the
full support-to-resistance range). A SHORT entry keyed off the full range —
and an `entry_ref` midpoint sitting mid-range for both directions — contradicts
the Family A LONG-support / SHORT-resistance zone semantics in `features.py`.
Either the SHORT branch should key off resistance (`zone_upper ± buf`) or the
duplication should collapse with a comment; as written it reads as a
copy-paste logic error that widens every SHORT entry zone across the whole range.
**Fix:** Differentiate per direction or collapse:
```python
if signal.direction == "LONG":
    entry_min = _sub(zone_lower, entry_buffer); entry_max = _add(zone_lower, entry_buffer)
else:
    entry_min = _sub(zone_upper, entry_buffer); entry_max = _add(zone_upper, entry_buffer)
```

### WR-02: Family C zone has no tolerance band and eligibility is asymmetric

**File:** `src/core/strategy.py:461-492`
**Issue:** `zone_upper`/`zone_lower` are raw swing extremes (lines 461-462),
unlike Family A (swing ± `zone_tolerance_atr*ATR`). Historical touches are
counted within `±touch_tolerance_atr*ATR`, but current-bar eligibility demands
piercing the exact extreme (`last_low <= zone_lower`, `last_high >= zone_upper`,
lines 483-492). A bar that merely touches within the band — the same bar that
would count as a touch historically — does not qualify today. Additionally the
touch scan (line 468, `range(swing_lookback, last_idx)`) counts touches on bars
that define the reference level itself (self-referential: the level is fit on,
then confirmed by, the same bars).
**Fix:** Define the C zone with the same half-width convention as Family A and
use one predicate for historical touches and current-bar eligibility; count
touches only on bars strictly before the window that defines the reference level.

### WR-03: `account_state` is dead in `evaluate`; two risk_rate sources of truth

**File:** `src/core/strategy.py:509`
**Issue:** `evaluate()` takes `account_state` and never reads it (only the
signature and docstring mention it). Meanwhile the planner sizes from
`parameter_set.params["risk_rate"]` (`planner.py:140,249`) while `AccountState`
carries its own `risk_rate` — two canonical homes for the per-trade risk
fraction with no consistency check. A caller passing `risk_rate=0.01` in the
account state while the TOML says `0.005` gets silent TOML-wins behavior.
**Fix:** Either thread `account_state.risk_rate` into the planner as the sizing
input (params carry only `minimum_risk_utilization_after_rounding`-style policy)
or assert equality at the boundary and fail closed on mismatch.

### WR-04: Gap inference blind spot at stream start

**File:** `src/core/features.py:282-313`
**Issue:** `_expected_bar_duration` infers the bar length from the first two
candles. If bars 0-1 already span a gap, `expected` is 2× the true duration;
the first bar is never flagged and bar 1's open (`open0 + 2D`) is not `>`
`prev_close + 2D` (`open0 + 3D - 1s` under the -1s close convention), so a
leading gap is invisible and features compute over a fabricated-contiguous
prefix. The detector also leans on the `-1s` close-time convention
(`expected_open = prev_close + expected` only works because close trails open+D
by 1s) rather than the robust `prev_open + expected`.
**Fix:**
```python
expected_open = candles[i - 1].open_time_utc + expected  # not prev_close + expected
# plus: reject (fail closed) when expected is None or when the first two bars
# themselves disagree with the interval-declared duration
```

### WR-05: Forming-bar gate covers only the setup stream and only for len >= 2

**File:** `src/core/strategy.py:597-609`
**Issue:** The gate checks the last setup candle only when there are ≥ 2 setup
bars, and never examines the context stream — a forming 4H bar flows into
`_resolve_regime` unchecked. A single-bar snapshot bypasses the gate entirely.
Separately, `_interval_duration` (lines 68-76) raises `ValueError` on an
unknown interval string instead of returning NO_TRADE, giving the pure core a
crash path on unexpected input.
**Fix:** Apply `_is_forming_bar` to both streams, handle the single-bar case
(treat a lone bar with `close_time` in the future as forming), and map unknown
intervals to `NO_TRADE`/`DATA_STALE` rather than raising.

### WR-06: Non-RejectionReason codes leak into the SetupResult envelope

**File:** `src/core/strategy.py:566-577`
**Issue:** `WARMUP_INSUFFICIENT` / `INVALID_INPUT` propagate verbatim as
`SetupResult.reason_code`; only `GAP_IN_SOURCE` is mapped to `DATA_STALE`.
Documented, but every downstream consumer written against the
`RejectionReason` enum must now also parse additive feature-layer strings, and
nothing in `types.py` constrains the vocabulary. A strict enum parser
downstream throws on exactly the warm-up path that occurs most in production
(backfill catch-up).
**Fix:** Map all feature-layer codes at this boundary (e.g. warm-up →
`NO_TRADE_REGIME` is already the empty-input precedent; or extend
`RejectionReason`) and assert `reason_code` membership in `SetupResult.__post_init__`.

### WR-07: Setup interval vs `source_timeframe` never cross-checked

**File:** `src/core/strategy.py:531-542,649-661`
**Issue:** `evaluate()` uses `setup_candles[0].interval` for features but stamps
the signal with `snapshot.source_timeframe` without checking they agree. A
caller wiring 1H candles with `source_timeframe="4h"` produces a valid-looking
SETUP permanently mislabeled at the wrong timeframe — corrupting signal IDs and
expiry math downstream.
**Fix:**
```python
if snapshot.setup_candles and snapshot.setup_candles[0].interval != snapshot.source_timeframe:
    return SetupResult(is_no_trade=True, reason_code=RejectionReason.DATA_STALE.value)
```

### WR-08: Dead `_regime_from_context` with misleading R1 docstring

**File:** `src/core/strategy.py:133-152`
**Issue:** `_regime_from_context` always returns `("OK", None)` when features
are valid, asserts on `ema_200` it never uses, and is never called — `evaluate`
uses `_resolve_regime`. Its docstring discusses R1-structure vs EMA50-proxy at
length for a function that decides nothing. Dead code carrying design
documentation rots: the next reader will cite it as the regime spec.
**Fix:** Delete the function; move the one-paragraph EMA50-proxy rationale onto
`_resolve_regime`.

### WR-09: FeatureOutput allows a stale value to ride along on invalid

**File:** `src/core/types.py:147-152`
**Issue:** `__post_init__` documents "value must be None when invalid" then
`pass`es on violation "so adapters can carry last-known values during
transitions". The validity gate is the single chokepoint the strategy trusts
(`features_valid` AND-gate); permitting `valid=False, value=<stale>` invites
exactly one bug class — a future reader using `.value` without checking
`.valid` — in exchange for adapter convenience that should live in the adapter,
not the core type.
**Fix:** Enforce `value is None` when `valid is False` (raise); move
last-known-value carriage to an adapter-local type.

### WR-10: Whitelisted-but-never-read parameters suggest unimplemented gates

**File:** `src/domain/registry.py:60-81`, `params/*/baseline-v1.toml`
**Issue:** `breakout_volume_threshold`, `regime_filter_lookback`, and
`minimum_risk_utilization_after_rounding` are whitelisted and present in both
TOMLs but never read anywhere in `src/core/`. Likewise `breakout_confirmation_bars`
and `zone_tolerance_atr` ship in the range-mr TOML although the range detector
uses neither. Dead config is a double hazard: operators believe a volume
filter / regime lookback / risk-utilization gate is active when no such code
exists, and future params risk silent shadowing.
**Fix:** Either wire the gates (volume filter for Family B, utilization check
for the planner) or remove the keys from the TOMLs/whitelist with a comment
pointing at the phase that will implement them.

## Info

### IN-01: `Decimal(str(x))` fallbacks silently bake float noise into Decimals

**File:** `src/core/features.py:378-379`, `src/core/strategy.py:282-285`, `src/core/planner.py:141-148`
**Issue:** Each `if not isinstance(v, Decimal): v = Decimal(str(v))` accepts a
float without complaint; `str(0.1)`-style spellings fossilize binary noise into
an exact-but-wrong Decimal. The registry already normalizes TOML floats, so any
float arriving here is a programming error worth failing on.
**Fix:** Raise `TypeError` on float instances at these boundaries instead of converting.

### IN-02: Bare `int(...)` truncations on Decimal params

**File:** `src/core/strategy.py:278-287,427-436`, `src/core/planner.py:139`
**Issue:** `int(params["swing_lookback"])` silently truncates `Decimal("20.9")`
to 20. The TOML path is protected by `INT_KEYS`, but a directly-constructed
`ParameterSet` bypasses it. Prefer an integral-value check that raises on
fractional input.
**Fix:** `v if isinstance(v, int) else (int(v) if v == int(v) else raise ...)`.

### IN-03: Float-based gap helper copy-pasted across four test files

**File:** `tests/test_no_lookahead.py:50-65`, `tests/test_prefix_invariance.py`, `tests/test_candle_close_timing.py`, `tests/test_core_planner.py:90-107`
**Issue:** Each suite carries its own `_first_gap_index` using
`.total_seconds()` float comparison, and the planner variant already drifted
(`replace("Z", "+00:00")` handling the others lack). Test-only, not counted
above — but the same leading-gap blind spot from WR-04 is duplicated four
times, so a fixture-layout change breaks suites inconsistently.
**Fix:** Single shared helper in `tests/conftest.py` or a fixture-loader module.

### IN-04: Duplicated LONG/SHORT entry-zone bodies

**File:** `src/core/planner.py:176-183`
**Issue:** Both branches are character-identical (see WR-01). Even if the
full-range zone turns out to be intended, the duplication must collapse to one
path so the intent is unambiguous.
**Fix:** Compute once outside the branch, with a comment stating the zone is direction-independent by design — or differentiate per WR-01.

---

_Reviewed: 2026-09-24T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
