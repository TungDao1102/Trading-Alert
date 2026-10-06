# Phase 15: Strategy Geometry Correction - Context

**Gathered:** 2026-10-06
**Status:** Ready for planning
**Mode:** `--auto` (Claude chose the recommended option for every gray area; each choice is logged in 15-DISCUSSION-LOG.md and can be overridden before planning). Money-relevant numeric values are marked **PROPOSED**: the planner surfaces them to the user in a `checkpoint:decision` with worked examples before freezing (project rule: AI does not silently pick money or safety numbers).

<domain>
## Phase Boundary

Each family's implemented trade geometry (entry zone, stop, target) matches its family sheet's Stage baseline, or a DECISIONS entry records the deviation, and is economically sane before any research run is trusted. The headline defect (F-301) is that the trend-pullback stop sits inside its own entry zone and the swing it keys off includes the bar being evaluated.

Delivers: a confirmed-pivot feature that excludes the evaluated bar; corrected trend-pullback geometry with the planner invariant "stop outside the whole entry zone, else NO_TRADE"; a minimum stop distance in ATR; a geometry audit of all three families against their sheets with each difference either fixed or recorded; new versioned parameter sets with a rationale for every value; hand-derived geometry tests; and a "ready to re-run" check under protocol v2.0.0 on the Phase-14 engine.

Out of scope: the research re-run itself (a research activity); the cost guards and the sizing math (Phase 12, unchanged, reused); backtest causality (Phase 14, done); paper runtime (Phase 16); live exit-ladder producer (F-103); tuning any parameter from results.

Requirements: STRAT-01, STRAT-02 (already Complete in Phase 4; this phase corrects their implementation, no status change). Audit refs: F-301, F-113, F-909.
</domain>

<decisions>
## Implementation Decisions

### Confirmed pivots (F-301 part 2)
- **D-01:** Replace the trailing-window extreme (`features.py` `_swing_series`, window `candles[i-lookback+1..i]`, includes bar `i`) as the *setup level* with a **confirmed fractal pivot**, per the trend-pullback sheet section 5 rows 1-3: a pivot low (high) at bar `t` is the lowest low (highest high) over `[t-L, t+R]`, and it is known only at the close of bar `t+R`. The setup level is the **most recent confirmed pivot inside `swing_lookback` bars**, and the evaluated bar is never part of it. A pullback bar that makes a new N-bar low can therefore no longer fire a "pullback to support" signal. — **Reversibility:** costly — changes every Family A signal id, fingerprint, golden fixture and the meaning of all earlier experiment hashes (already void after Phase 14).
- **D-02:** The two pivot widths are new registry keys `pivot_left_bars` and `pivot_right_bars` (added to `STRATEGY_KEYS`, optional so every older set keeps loading and keeps its `parameter_set_hash`, same pattern as Phase 12 keys). **PROPOSED** defaults: 3 and 3 on the 1H setup stream (a pivot is confirmed 3 hours late; a 20-bar `swing_lookback` still bounds how old a pivot may be). The planner records the confirmation lag in the plan's rationale and shows the user the numbers.
- **D-03:** No pivot found inside the lookback is `NO_TRADE` with the existing warm-up or "no setup" reason, never a fallback to the old trailing extreme. Warm-up requires `L + R + 1` bars plus ATR warm-up.
- **D-04:** Prefix-invariance is a tested property: appending later bars never changes a pivot that was already confirmed, and a pivot is never reported before bar `t+R` has closed. Pivots use closed candles only (AGENTS.md no-repaint rule). The trailing-window helper may stay for Families B/C only if the audit in D-13 shows they do not leak the evaluated bar; otherwise they move to the same pivot function.

### Trend-pullback geometry (F-301 part 1)
- **D-05:** The setup level is the confirmed pivot `P` (LONG: pivot low; SHORT: pivot high). Entry zone = `P ± zone_tolerance_atr * ATR` widened by `entry_buffer_atr * ATR` on each side (unchanged entry-zone semantics, entry_ref stays the zone mid per Phase 12 note). The stop is placed **beyond the outer edge of the whole entry zone**: LONG `SL = entry_min - sl_buffer_atr * ATR`, SHORT `SL = entry_max + sl_buffer_atr * ATR` (sheet S2: structure + ATR buffer). The buffer is measured from the outer zone edge, not from the pivot.
- **D-06:** Hard planner invariant, applied to **all three families**, checked after quantization to storage scale: LONG requires `SL < entry_min`, SHORT requires `SL > entry_max`; otherwise `NO_TRADE`. The reason code reuses an existing `RejectionReason` if one fits; if a new value is needed the planner checks the persistence and enum-parity tests first and records it. A pre-existing plan or fixture violating the invariant is a bug, not data.
- **D-07:** Setup already invalidated at signal time: if the signal bar's own low (LONG) or high (SHORT) already trades through the planned SL, the plan is `NO_TRADE` (a stop that the signal bar already hit is not a stop). This closes the p9 case (signal on a bar 150 below every prior low).
- **D-08:** Minimum stop distance in ATR, a **planner-level** check before the Phase 12 guards: `|entry_ref - SL| >= min_stop_atr * ATR`, else `NO_TRADE` (reason: the existing `STOP_TOO_TIGHT` family if reusable). New optional registry key `min_stop_atr`. **PROPOSED** 0.5 for Family A. With the D-05 geometry and baseline buffers the distance is about 0.8 ATR by construction, so this is a backstop, not the binding constraint. The Phase 12 money guards (`min_stop_distance_rate`, `max_cost_to_risk`, implied minimum stop about 0.79 percent of price) remain the binding economic filter and are not edited.
- **D-09:** Take-profit for Family A: keep the structure-derived TP1 (opposite confirmed pivot, now also confirmed-only) and TP2 = entry +/- 2 x (TP1 - entry). This **deviates from the sheet's T1 fixed-R** on purpose (CR-03: a TP built from `minimum_rr` makes the RR gate vacuous). Record the deviation in DECISIONS (D-14). The RR gate stays an acceptance threshold only.

### Families B and C against their sheets (F-113)
- **D-10:** The planner produces a **geometry audit table** (family x entry zone x SL x TP, sheet Stage baseline vs code, with a verdict per cell) as the first plan, before changing code. Known differences to resolve:
  - Family B stop: sheet Stage B is S3 (zone invalidation on the other side of the broken zone); code puts the stop `sl_buffer_atr * ATR` under the retest edge. Aligning to the sheet makes `RR = height / (height + buffer) < 1` against the measured-move TP, so every plan would be `RR_TOO_LOW`. **Auto choice: keep the code stop and record the deviation** in DECISIONS with that arithmetic, and add a sheet amendment note stating the implemented baseline. Do not silently flip the sheet.
  - Family B target: sheet T1 fixed-R vs code measured move. Same CR-03 reason as D-09; record.
  - Family C target: sheet Stage C is T-mid (range midpoint); code targets the opposite boundary (that is the sheet's T-opposite variant). **Auto choice: align code to T-mid** and keep T-opposite as a named variant that needs its own parameter set later. The planner shows how many sample setups drop below `minimum_rr` with the midpoint target before freezing.
  - Family C stop: S3 outside the range edge by `sl_buffer_atr`; confirm the code matches and record.
- **D-11:** B and C stops are about 0.2 ATR from the entry reference with baseline buffers. Together with the D-06 invariant and the Phase 12 guards this may reject nearly every B/C setup. The planner **measures this on sample data and reports the count to the user**; it does not loosen a guard or tune a buffer to rescue signal volume (D-17).
- **D-12:** Whichever way a cell is resolved, the family sheets get an "implemented as" line, the Status stays HYPOTHESIS/NOT FROZEN (no sheet becomes frozen here), and the F-113 "implemented: NO" wording is corrected.
- **D-13:** Leakage audit for B/C: `_detect_breakout_retest_setup` and `_detect_range_mr_setup` use `_swing_series` at `ref_prev` and `ref_idx`. The planner proves per detector, with a test, that the evaluated bar is excluded from the reference level, or moves it to the confirmed-pivot function (D-04).

### Parameter sets, rationale, versioning (F-909)
- **D-14:** One DECISIONS entry (next id D054, status Accepted with the auto-mode note) records: the geometry audit outcome, each kept deviation with its reason, the new keys, the new set ids, and the regeneration inventory (fixtures, pins, hashes that moved), in the style of D048/D053.
- **D-15:** New sets `params/<family>/baseline-v6.toml` for each family whose geometry or keys change, with `strategy_version` bumped to `v5.0.0` for those families (new behavior means a new set and a new strategy version; Phase 12 D-04/D-06 pattern). Existing sets stay byte-identical (F-810). `baseline-no-trade-*` and `baseline-simple-trend-*` degenerate sets are re-issued only if the planner finds they must follow the version bump; their independence rules in `src/analytics/family.py` must keep passing.
- **D-16:** **Every value in a new set carries a recorded rationale**; no value is inherited silently from the Phase 3 / 04-01 seed set. Rationale lives where it is machine-checkable (planner picks: a rationale table consumed by a test that fails when a key has none, or a structured comment block parsed by a test) and must not change the hash of any existing set. A value with no empirical or structural basis is marked `PLACEHOLDER`, and a `PLACEHOLDER` set cannot be frozen for paper (the Phase 16 freeze path must refuse it; the planner adds the refusal or records where it will live).
- **D-17:** No value is chosen or adjusted after looking at backtest results. Values come from declared ranges and structural arithmetic (ATR multiples tied to the geometry, cost ratios tied to Phase 12 guards). The user ratifies the final numbers in the planner's `checkpoint:decision`.

### Tests and readiness
- **D-18:** Geometry is verified by **hand-derived expected values** in committed sidecars (same discipline as Phase 14 D-24), not regenerated from `src/`. Required cases per family: LONG and SHORT worked example with real numbers; SL outside zone; signal bar already through the stop; stop below minimum ATR distance; no confirmed pivot; pivot confirmed exactly at `t+R` and not before; prefix-invariance of pivots; a new-N-bar-low bar that must NOT signal (the p9 reproduction at `tmp/business_invariants/p9_trend_pullback_new_low.py` in the audit snapshot becomes a regression test); a property test over a grid of ATR, tolerance and buffer values asserting the D-06 invariant for all three families.
- **D-19:** Deliberate regeneration: golden planner outputs, Phase 6 fixtures built by `scripts/gen_phase6_fixtures.py`, signal ids and plan hashes that move are listed once in the DECISIONS entry (D-14). Fixtures not rebuilt are relabeled regression snapshots, consistent with Phase 14 D-25.
- **D-20:** Criterion 4 (research re-run readiness) is a verifiable check, not a run: the new sets load and register under protocol v2.0.0, the Phase-14 engine runs a small real-data smoke (`scripts/smoke_backtest_realdata.py`) on them end to end with zero invariant violations, and the planner states what a re-run still needs (candidate-set freeze step per RESEARCH_PROTOCOL, data window, universe). The planner checks whether the protocol needs another version bump and records the answer; the default expectation is that it does not (protocol governs method, not strategy values).
- **D-21:** Determinism stays strict: Decimal only via `src/core/_decimal.py`, no float, no wall clock, sorted iteration, byte-identical reruns. `src/core` stays free of Polars and FastAPI.

### Claude's Discretion
- Module placement of the pivot function (`features.py` vs a new `pivots.py`), names of the new reason codes if any, internal helper names, and test file layout, provided the D-06 invariant lives in one place shared by all families.
- Format of the rationale record (D-16) as long as it is machine-checked and hash-neutral.
- Whether the geometry audit table is a doc under `docs/research/families/` or a section of the DECISIONS entry.

### Folded Todos
None. The todo cross-reference found no matching pending todo for this phase.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authority and decisions
- `AGENTS.md` - Decimal-only, determinism, no-lookahead, prefix-invariance, fail closed, no AI in the decision path
- `docs/DECISIONS.md` - D031 (quantization), D037 (mark-price triggers), D046 (cost guards), D047, D048 and D053 (regeneration inventory style), D052 (protocol v2.0.0 frozen); next free id is D054
- `.planning/ROADMAP.md` - "Phase 15" goal and criteria 1-4
- `.planning/REQUIREMENTS.md` - STRAT-01, STRAT-02
- `.planning/phases/12-fee-cost-model-correctness/12-CONTEXT.md` - D-04, D-06, D-07 (versioned sets, guards, never tuned after results)
- `.planning/phases/14-backtest-causality-rewrite/14-CONTEXT.md` - D-24, D-25 (hand-derived goldens, regression snapshots), D-26 (determinism)

### Audit
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` section 6.4 (F-301 numeric scenarios and fix list) and `findings.json` - F-301, F-113, F-909
- Audit snapshot probes (outside the repo): `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\tmp\business_invariants\p2_geometry.py` and `p9_trend_pullback_new_low.py`

### Family sheets and specs
- `docs/research/families/trend-pullback.md` - sections 2.2, 3 (Stage A baseline: R1 + P1 + E2 + S2 + T1), 5 (confirmed-pivot rules), 6 (parameters)
- `docs/research/families/breakout-retest.md` - section 3 (Stage B baseline: S3 stop, T1), Q6
- `docs/research/families/range-mr.md` - section 3 (Stage C baseline: S3 stop, T-mid)
- `docs/research/RESEARCH_PROTOCOL.md` (v2.0.0) - candidate-set freeze, closed-candle rule
- `docs/strategy/TRADING_STRATEGY_SPEC.md` - slot template
- `docs/research/TRADING_STRATEGY_RESEARCH.md` sections 4.2, 6 (zones, entry/SL/TP candidates)
- `docs/trading/RISK_MANAGEMENT.md` - costs, guards, corrected rules 2, 3 and 6

### Code
- `src/core/planner.py` - `_long_geometry`, `_short_geometry` (lines ~91-197), `plan` (entry zone and SL assembly ~340-420)
- `src/core/features.py` - `_swing_series` (~166-193), `_zone_series`, `compute_features`
- `src/core/strategy.py` - `_detect_setup` (~128-160), `_detect_breakout_retest_setup` (~208), `_detect_range_mr_setup` (~364)
- `src/domain/registry.py` - `STRATEGY_KEYS` and per-key validators (add optional keys the Phase 12 way)
- `src/risk/cost_guards.py`, `src/risk/gating.py` - Phase 12 guards (reused, not edited)
- `params/<family>/baseline-v5.toml` - the sets this phase supersedes
- `scripts/gen_phase6_fixtures.py`, `tests/fixtures/phase5/`, `tests/fixtures/phase6/`, `scripts/smoke_backtest_realdata.py`
- `src/analytics/family.py` - independence rules the new set ids must keep satisfying
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_mul/_add/_sub/_div/_q` in `src/core/_decimal.py` and `quantize_for_storage`: the only arithmetic allowed in geometry.
- Phase 12 guards (`evaluate_cost_guards`, `guard_rates_from_params`): already reject too-tight stops and high cost-to-risk after sizing; the planner invariant is an earlier, family-agnostic structural check.
- Registry optional-key pattern (`working_type`, `min_stop_distance_rate`): copy it for `pivot_left_bars`, `pivot_right_bars`, `min_stop_atr`.
- `scripts/gen_phase6_fixtures.py` and `scripts/smoke_backtest_realdata.py`: fixture builder and real-data smoke for criterion 4.

### Established Patterns
- Frozen artifacts are versioned, never edited in place (params, protocol); new behavior = new set + strategy version bump.
- Deliberate regeneration gets one DECISIONS entry listing every moved fixture and hash.
- Planner never rounds against stepSize; exchange quantization stays in the risk layer (D031).
- Fail closed: ambiguous or invalid geometry is NO_TRADE with a reason code, never a repaired plan.

### Integration Points
- `plan()` feeds `evaluate_risk`, the Phase-14 backtest engine, and the paper loop; a geometry change flows to all three through the same function.
- `compute_features` output feeds `_detect_setup`; the new pivot features must keep `features_valid` semantics so warm-up gates still work.
- Signal ids and plan hashes depend on zone and fingerprint values, so every consumer fixture moves together (D-19).
</code_context>

<specifics>
## Specific Ideas

- The audit's worked numbers are the acceptance anchors: LONG zone 58820-59180 with SL 58940 (inside the zone) must become NO_TRADE or a corrected plan with SL below 58820; the S=60,000, ATR=400 example (stop 0.133 percent of price, RR 25, cost about 60 percent of risk) must no longer produce a plan.
- Show the user, per family, one plain-language before/after example with numbers at equity 500 and 1,000 (the user is not a trading specialist).
</specifics>

<deferred>
## Deferred Ideas

- Family C T-opposite target and other sheet variants (A1-A6, B-retest-2, C-pullback-2..4) as candidate sets: research phase, not this phase.
- Regime detector alternatives R2/R3 and pullback variants P2-P4: research.
- Live producer for TP1 quantity split and exit ladder (F-103): later phase.
- Incremental feature series (performance): already deferred past Phase 15 by Phase 14 D-31.
- Freezing any family sheet: only after real research evidence.

None of these were scope additions from discussion; they are carried over so they are not lost.
</deferred>

---

*Phase: 15-strategy-geometry-correction*
*Context gathered: 2026-10-06*
