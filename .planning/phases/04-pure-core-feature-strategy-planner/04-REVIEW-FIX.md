---
phase: 04-pure-core-feature-strategy-planner
fixed_at: 2026-09-25T00:00:00Z
review_path: .planning/phases/04-pure-core-feature-strategy-planner/04-REVIEW.md
iteration: 1
findings_in_scope: 24
fixed: 24
skipped: 0
status: all_fixed
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-09-25T00:00:00Z
**Source review:** `.planning/phases/04-pure-core-feature-strategy-planner/04-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 24 (8 Critical + 16 Warning; 7 Info out of scope, untouched)
- Fixed: 24
- Skipped: 0

All fixes were applied to current source (read before each edit), verified
per-fix (re-read + `mypy src/core/` + affected tests), and committed
atomically. Four findings carry documented adaptations where the review's
suggested fix conflicted with tests that pin intended behavior or with
D-04 hash permanence — each adaptation is noted on its entry.

## Fixed Issues

### CR-01: Strategy-semantic knobs outside the registry with silent defaults

**Files modified:** `src/domain/registry.py`, `params/breakout-retest/baseline-v1.toml`, `params/range-mr/baseline-v1.toml`, `src/core/strategy.py`
**Commit:** bd12652
**Applied fix:** Promoted `atr_period` (INT) and `touch_tolerance_atr`
(DECIMAL) into `STRATEGY_KEYS`; added `atr_period = 14` to both Family
B/C TOMLs and `touch_tolerance_atr = 0.3` to the range-mr TOML; detectors
now read `parameter_set.params[...]` directly (KeyError, never silent
`.get()`). `params/trend-pullback/baseline-v1.toml` intentionally
untouched so its published hash (`e1579900…`) — pinned by
`tests/fixtures/phase3/parameters.json` — is preserved; the feature
layer falls back to 14 for legacy sets (see WR-13).

### CR-02: Planner raises instead of returning NO_TRADE

**Files modified:** `src/core/planner.py`
**Commit:** e0bde92
**Applied fix:** All three crash paths return NO_TRADE: empty
`setup_candles` → `DATA_STALE` (checked before `setup_candles[0]`);
invalid features → NO_TRADE carrying the first invalid feature's reason
(`GAP_IN_SOURCE` mapped to `DATA_STALE`, mirroring the strategy gate);
`risk <= 0` → `RR_TOO_LOW`. Mixed-symbol/interval streams that raise
inside `compute_features` are caught (`ValueError` → `DATA_STALE`).

### CR-03: Planner RR gate is vacuous

**Files modified:** `src/core/planner.py`, `tests/test_core_planner.py`
**Commit:** e0bde92 (geometry + gate), 2e19c5a (Family B stop correction), 70d190b (tests)
**Applied fix:** TP1 is structure-derived, `minimum_rr` is purely an
acceptance threshold: Family A TP1 = opposing swing extreme, Family B
TP1 = breakout edge ± range-height measured move, Family C TP1 =
opposing range edge; TP2 extends the structure leg (`entry ± 2·(TP1−entry)`).
Proven meaningful by new test `test_rr_gate_fires_on_structure_tp_below_minimum`
(`minimum_rr = 1000` → `RR_TOO_LOW`). Follow-up correction (2e19c5a):
Family B stops sit under the retest edge, not under support — a
support-based stop makes `height/(height+buffer) < 1`, so NO B plan
could ever clear the gate.
**Human verification requested:** TP/SL construction is a strategy-semantics
choice (edge-based stops, measured-move targets); suite is green but the
geometry should be confirmed against `docs/research/families/*.md` intent.

### CR-04: Precision-context violation (three domains)

**Files modified:** `src/core/strategy.py`
**Commit:** f0c6a5f (Family B), cdc3afa (Family C)
**Applied fix:** Deleted the prec-50 `localcontext` block; every Family B
edge/band op and every Family C band/buffer/comparison op routes through
the pinned prec-28 helpers from the new shared module (WR-16), including
precomputed comparison bounds (no ambient `-` inside predicates). Removed
the now-unused `localcontext` import and the orphaned `FeatureOutput`
import.

### CR-05: Planner prices plans off a different zone than the detector fired on

**Files modified:** `src/core/planner.py`
**Commit:** e0bde92
**Applied fix:** Full threading without a signal-schema change: the
planner re-derives the detector zone from the same candles —
`_detect_breakout_retest_setup` / `_detect_range_mr_setup` for Families
B/C (direction must match the signal, else `STALE_SETUP`), per-side
support/resistance zones for Family A. `compute_features` remains the
validity gate only. A setup that vanished at plan time yields
`STALE_SETUP`, never a repriced plan.
**Human verification requested:** re-derived (not carried) zone —
equivalent only when plan-time candles equal signal-time candles, which
the CR-08 correspondence checks enforce.

### CR-06: Family A touch predicate spans the full range for both directions

**Files modified:** `src/core/strategy.py`, `tests/test_core_planner.py`, `tests/test_no_lookahead.py`
**Commit:** 87f3ab8 (source), 70d190b (tests)
**Applied fix:** `_detect_setup` takes `zone_tolerance_atr` and checks
per-side zones: LONG iff BULLISH and low within
`swing_low ± tolerance`; SHORT iff BEARISH and high within
`swing_high ± tolerance`. Returns the touched side's zone (bound into
the fingerprint). Tests updated: planner fixture patches the last bar
onto the trailing swing low; entry-zone math test asserts support-based
geometry; no-lookahead Beh 4 patches its final prefix bar likewise so
the leaky-regime-flip still moves a real decision.
**Human verification requested:** the old tracer-window LONG is now
NO_TRADE (it never touched support — the exact CR-06 false positive);
confirm the corrected predicate matches trend-pullback.md §3 intent.

### CR-07: range-mr has no NEUTRAL-only gate

**Files modified:** `src/core/strategy.py`
**Commit:** 87f3ab8
**Applied fix:** `range-mr` with regime `!= NEUTRAL` returns
`NO_TRADE_REGIME`, making the detector docstring's claimed guard real.
Range-mr family tests (NEUTRAL contexts) stay green.

### CR-08: Planner returns READY plans for expired/stale signals

**Files modified:** `src/core/planner.py`, `tests/test_core_planner.py`
**Commit:** e0bde92 (source), 70d190b (tests)
**Applied fix:** `plan()` enforces symbol, interval-vs-`source_timeframe`,
`strategy_id`, `parameter_set_id`, last-close-vs-`source_candle_close_utc`
(`STALE_SETUP`), and `expiry_utc > created_at_utc`
(`APPROVAL_EXPIRED`). Planner tests now create plans at
`source_close + 1h` (inside the 4h window); new tests pin empty-stream,
expired-signal, and foreign-symbol NO_TRADE paths.

### WR-01: Planner entry zone is direction-invariant

**Files modified:** `src/core/planner.py`
**Commit:** e0bde92
**Applied fix:** Resolved with CR-05/CR-06 geometry: LONG entries Off
support (Family A support zone / B-C edge-centered), SHORT off
resistance. No shared full-range path remains.

### WR-02: Family C zone has no tolerance band and eligibility is asymmetric

**Files modified:** `src/core/strategy.py`
**Commit:** cdc3afa
**Applied fix:** One band convention: historical touches and the current
bar use the same within-band predicate; the scan covers bars strictly
before the reference window (`range(swing_lookback, ref_idx -
swing_lookback + 1)`); edges stay raw extremes with the band applied
uniformly. Added nearest-edge disambiguation (a wide band can place one
bar within both edges — the setup fades the near edge; ties keep LONG),
which the symmetric predicate otherwise leaves ambiguous (found live:
the SHORT fixture bar touched both bands and LONG-first ordering stole
it).
**Human verification requested:** tie-keeps-LONG and near-edge choice;
all four Family C behaviors stay pinned by tests.

### WR-03: `account_state` is dead in `evaluate`; two risk_rate sources of truth

**Files modified:** `src/core/planner.py`
**Commit:** e0bde92
**Applied fix (adapted):** Planner sizes from `account_state.risk_rate`
as the single source of truth; the registry copy is no longer read for
sizing. `evaluate` keeps its `account_state` parameter by design
(interface stability; strategy needs no account data — sizing is
planner-owned, Phase 5 expands) — documented here instead of threaded.

### WR-04: Gap inference blind spot at stream start

**Files modified:** `src/core/features.py`
**Commit:** 01de493
**Applied fix:** Gap expectation anchors on the interval-declared
duration (`_INTERVAL_BAR_DURATIONS`) and on `prev.open_time_utc +
expected` (no baked-in `-1s` convention). A leading gap (first two bars
disagreeing with the declared duration) flags bar 1, failing the whole
stream closed. Unknown intervals raise `ValueError`, mapped to NO_TRADE
by both callers.

### WR-05: Forming-bar gate covers only the setup stream and only for len >= 2

**Files modified:** `src/core/strategy.py`
**Commit:** 01de493
**Applied fix (adapted):** Both setup and context last bars are gated;
unknown intervals are pre-validated to `DATA_STALE` before any
`_interval_duration` call can raise. Single-bar streams skip the gate
(no chaining evidence either way) and fall through to the feature gate,
which rejects them fail-closed with `WARMUP_INSUFFICIENT` — pinned by
`test_domain_boundary.py` Beh 2, so the code keeps that exact behavior.

### WR-06: Non-RejectionReason codes leak into the SetupResult envelope

**Files modified:** `src/core/types.py`
**Commit:** ec18776
**Applied fix (adapted):** `SetupResult.__post_init__` enforces a closed
`_SETUP_REASONS` vocabulary (all `RejectionReason` values + `OK` +
`WARMUP_INSUFFICIENT` / `GAP_IN_SOURCE` / `INVALID_INPUT`) so unknown
codes fail at the boundary, never in a downstream consumer. Full
remapping to canonical codes was NOT applied: `test_domain_boundary.py`
Beh 2/3 and `test_core_features.py` Beh 2b pin verbatim
`WARMUP_INSUFFICIENT` propagation from `evaluate`.

### WR-07: Setup interval vs `source_timeframe` never cross-checked

**Files modified:** `src/core/strategy.py`
**Commit:** 01de493
**Applied fix:** `evaluate` returns `DATA_STALE` when
`setup_candles[0].interval != snapshot.source_timeframe`, before any
feature computation (paired with the planner-side check from CR-08).

### WR-08: Dead `_regime_from_context` with misleading R1 docstring

**Files modified:** `src/core/strategy.py`
**Commit:** 01de493
**Applied fix:** Deleted (zero callers, verified by grep); the R1/EMA50
rationale paragraph moved onto `_resolve_regime`.

### WR-09: FeatureOutput allows a stale value to ride along on invalid

**Files modified:** `src/core/types.py`
**Commit:** ec18776
**Applied fix:** `__post_init__` raises when `valid is False` and
`value is not None`; adapters needing last-known values must use their
own local type.

### WR-10: Whitelisted-but-never-read parameters suggest unimplemented gates

**Files modified:** `params/trend-pullback/baseline-v1.toml`, `params/breakout-retest/baseline-v1.toml`, `params/range-mr/baseline-v1.toml`
**Commit:** d0d1bbb
**Applied fix (adapted):** Keys NOT removed (removal would mutate
published sets and fork their D-04 hashes). Instead each unimplemented
key (`breakout_volume_threshold`, `regime_filter_lookback`,
`minimum_risk_utilization_after_rounding`) carries a `RESERVED` comment
with its owning-phase pointer. Verified: TOML comments do not change
hashes (trend hash still `e1579900…`). The range TOML keeps
`breakout_confirmation_bars` / `zone_tolerance_atr` (shared feature
path via `compute_features` requires them).

### WR-11: Unknown strategy_id silently falls through to Family A

**Files modified:** `src/core/strategy.py`
**Commit:** 87f3ab8
**Applied fix:** Explicit `trend-pullback` branch; the `else` returns
`DATA_STALE` NO_TRADE. Unknown families can never emit a setup under
another family's name.

### WR-12: Cross-bar ATR mixing

**Files modified:** `src/core/strategy.py`
**Commit:** f0c6a5f (Family B), cdc3afa (Family C)
**Applied fix:** One `(zone, atr_ref)` pair per candidate:
`_find_retest_bar` takes the reference bar's ATR (signature changed from
`atr_series`); Family C touch band and break buffer both derive from
the reference bar's ATR instead of the last bar's.

### WR-13: `compute_features` hardcodes EMA 20/50/200 and ATR 14

**Files modified:** `src/core/features.py`
**Commit:** 01de493
**Applied fix:** ATR period threaded from the versioned registry knob via
`_atr_period_from_params` (legacy sets without the key fall back to 14,
reproducing the previously hardcoded ATR-14 exactly — required for the
untouched trend-pullback hash). EMA 20/50/200 are named fixed-by-design
constants (`_EMA_FAST/MID/SLOW_PERIOD`) per the review's "explicit fixed
by design" option.

### WR-14: Planner never validates signal-vs-candles correspondence

**Files modified:** `src/core/planner.py`
**Commit:** e0bde92
**Applied fix:** All four correspondences asserted at the top of `plan()`
(symbol, interval-vs-timeframe, `strategy_id`, `parameter_set_id`) with
NO_TRADE on any mismatch — see CR-08 entry.

### WR-15: Family B warm-up gate overstates required history

**Files modified:** `src/core/strategy.py`
**Commit:** f0c6a5f
**Applied fix:** `min_bars = breakout_confirmation_bars +
swing_lookback`; the forward retest window no longer gates history. The
scan's validity checks handle short windows naturally.

### WR-16: Decimal helpers triplicated across three modules

**Files modified:** `src/core/_decimal.py` (new), `src/core/features.py`, `src/core/strategy.py`, `src/core/planner.py`
**Commit:** eb5af58
**Applied fix:** Single shared `src/core/_decimal.py` (`_PREC = 28`,
`_q`/`_div`/`_mul`/`_add`/`_sub`); the three modules import and
re-export the names (backward-compatible `from .x import ...`).

## Fixture regeneration (behavior-changing fixes)

Regenerated with `scripts/_regen_phase4_expectations.py` (new, kept for
provenance — the 04-04 one-off generators were deleted after use, which
is why reconstruction was needed):
- `tests/fixtures/phase4/parameters.json` — B/C hashes changed by CR-01
  (`breakout-retest 4a8ee77e…`, `range-mr 060fc447…`; trend unchanged).
- `tests/fixtures/phase4/expected_signals.json` — all three signal IDs
  changed (zone/fingerprint geometry + hashes).
- `tests/fixtures/phase4/expected_plans.json` — full geometry change
  (per-side entry, structure TP1/TP2, `created_at` inside the expiry
  window — the old file's `created_at` values were past expiry, the
  CR-08 bug exhibit).
- `tests/fixtures/phase4/expected_features.json` — ATR/zone values
  shifted (patched support-touch last bar in the trend window).
- `candles.csv` untouched (market inputs unchanged by review fixes).
- Regen is byte-identical across runs (verified via file hashes).
- No test consumes these files (verified by grep — only `conftest.py`
  loaders reference them); no digest tripwire covers phase4 (the
  tripwire in `test_fixture_harness.py` covers phase3 only, still green).

**Commit:** 1c3c187 (fixtures + generator)

## Verification

Ran in the main checkout (no isolated worktree in this environment):

- `uv run pytest tests/ -q`: **278 passed, 5 skipped** (baseline was 274
  passed / 5 skipped; +4 new tests: RR-gate-fires + 3 fail-closed planner
  cases). No test deleted, no failure suppressed.
- `uv run ruff check` on all touched files (`src/core/`,
  `src/domain/registry.py`, both touched test files, regen script):
  **clean** — including the pre-existing `types.py` I001, fixed
  incidentally via `ruff --fix` while the file was open for WR-06/WR-09.
- `uv run mypy src/core/`: **clean (6 files)** — the 04-04 mypy-strict
  gate holds with the new `_decimal.py`, geometry helpers, and detector
  rewrites.
- Determinism invariants preserved: stdlib+Decimal only in `src/core`
  (purity AST test green), no float literals (`test_planner_has_no_float_literals`
  plus repo-wide no-float suites green), `from __future__ import
  annotations` headers intact, canonical-hash paths unchanged
  (`canonical.sha256_hex` still the single hash route), regen script
  byte-identical across runs.
- No-winner rule: grepped the full diff for comparative/ranking
  language — no hits (only the standing D-08 rule statement itself).
- Per-fix rollback was never needed: no fix broke the suite in a way
  that survived adaptation (the Family C SHORT-steal and Family B
  support-stop findings above were caught by tests pre-commit and
  corrected in-tree).

## Skipped Issues

None — all 24 in-scope findings fixed. Info findings IN-01..IN-07 were
out of scope and left untouched per instructions.

---

_Fixed: 2026-09-25T00:00:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
