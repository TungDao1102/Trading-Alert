# Phase 15: Strategy Geometry Correction - Research

**Researched:** 2026-10-06
**Domain:** deterministic trading-core geometry (pure Python core, Decimal only), parameter registry, research governance
**Confidence:** HIGH for code facts and consumer/ripple inventories (files read and tests run this session); MEDIUM for the feasibility numbers (float prototypes on the local 1H/4H store, indicative only); MEDIUM for design recommendations that are Claude's discretion.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Confirmed pivots (F-301 part 2)**
- **D-01:** Replace the trailing-window extreme (`features.py` `_swing_series`, window `candles[i-lookback+1..i]`, includes bar `i`) as the *setup level* with a **confirmed fractal pivot**, per the trend-pullback sheet section 5 rows 1-3: a pivot low (high) at bar `t` is the lowest low (highest high) over `[t-L, t+R]`, and it is known only at the close of bar `t+R`. The setup level is the **most recent confirmed pivot inside `swing_lookback` bars**, and the evaluated bar is never part of it. A pullback bar that makes a new N-bar low can therefore no longer fire a "pullback to support" signal. — **Reversibility:** costly — changes every Family A signal id, fingerprint, golden fixture and the meaning of all earlier experiment hashes (already void after Phase 14).
- **D-02:** The two pivot widths are new registry keys `pivot_left_bars` and `pivot_right_bars` (added to `STRATEGY_KEYS`, optional so every older set keeps loading and keeps its `parameter_set_hash`, same pattern as Phase 12 keys). **PROPOSED** defaults: 3 and 3 on the 1H setup stream (a pivot is confirmed 3 hours late; a 20-bar `swing_lookback` still bounds how old a pivot may be). The planner records the confirmation lag in the plan's rationale and shows the user the numbers.
- **D-03:** No pivot found inside the lookback is `NO_TRADE` with the existing warm-up or "no setup" reason, never a fallback to the old trailing extreme. Warm-up requires `L + R + 1` bars plus ATR warm-up.
- **D-04:** Prefix-invariance is a tested property: appending later bars never changes a pivot that was already confirmed, and a pivot is never reported before bar `t+R` has closed. Pivots use closed candles only (AGENTS.md no-repaint rule). The trailing-window helper may stay for Families B/C only if the audit in D-13 shows they do not leak the evaluated bar; otherwise they move to the same pivot function.

**Trend-pullback geometry (F-301 part 1)**
- **D-05:** The setup level is the confirmed pivot `P` (LONG: pivot low; SHORT: pivot high). Entry zone = `P ± zone_tolerance_atr * ATR` widened by `entry_buffer_atr * ATR` on each side (unchanged entry-zone semantics, entry_ref stays the zone mid per Phase 12 note). The stop is placed **beyond the outer edge of the whole entry zone**: LONG `SL = entry_min - sl_buffer_atr * ATR`, SHORT `SL = entry_max + sl_buffer_atr * ATR` (sheet S2: structure + ATR buffer). The buffer is measured from the outer zone edge, not from the pivot.
- **D-06:** Hard planner invariant, applied to **all three families**, checked after quantization to storage scale: LONG requires `SL < entry_min`, SHORT requires `SL > entry_max`; otherwise `NO_TRADE`. The reason code reuses an existing `RejectionReason` if one fits; if a new value is needed the planner checks the persistence and enum-parity tests first and records it. A pre-existing plan or fixture violating the invariant is a bug, not data.
- **D-07:** Setup already invalidated at signal time: if the signal bar's own low (LONG) or high (SHORT) already trades through the planned SL, the plan is `NO_TRADE` (a stop that the signal bar already hit is not a stop). This closes the p9 case (signal on a bar 150 below every prior low).
- **D-08:** Minimum stop distance in ATR, a **planner-level** check before the Phase 12 guards: `|entry_ref - SL| >= min_stop_atr * ATR`, else `NO_TRADE` (reason: the existing `STOP_TOO_TIGHT` family if reusable). New optional registry key `min_stop_atr`. **PROPOSED** 0.5 for Family A. With the D-05 geometry and baseline buffers the distance is about 0.8 ATR by construction, so this is a backstop, not the binding constraint. The Phase 12 money guards (`min_stop_distance_rate`, `max_cost_to_risk`, implied minimum stop about 0.79 percent of price) remain the binding economic filter and are not edited.
- **D-09:** Take-profit for Family A: keep the structure-derived TP1 (opposite confirmed pivot, now also confirmed-only) and TP2 = entry +/- 2 x (TP1 - entry). This **deviates from the sheet's T1 fixed-R** on purpose (CR-03: a TP built from `minimum_rr` makes the RR gate vacuous). Record the deviation in DECISIONS (D-14). The RR gate stays an acceptance threshold only.

**Families B and C against their sheets (F-113)**
- **D-10:** The planner produces a **geometry audit table** (family x entry zone x SL x TP, sheet Stage baseline vs code, with a verdict per cell) as the first plan, before changing code. Known differences to resolve:
  - Family B stop: sheet Stage B is S3 (zone invalidation on the other side of the broken zone); code puts the stop `sl_buffer_atr * ATR` under the retest edge. Aligning to the sheet makes `RR = height / (height + buffer) < 1` against the measured-move TP, so every plan would be `RR_TOO_LOW`. **Auto choice: keep the code stop and record the deviation** in DECISIONS with that arithmetic, and add a sheet amendment note stating the implemented baseline. Do not silently flip the sheet.
  - Family B target: sheet T1 fixed-R vs code measured move. Same CR-03 reason as D-09; record.
  - Family C target: sheet Stage C is T-mid (range midpoint); code targets the opposite boundary (that is the sheet's T-opposite variant). **Auto choice: align code to T-mid** and keep T-opposite as a named variant that needs its own parameter set later. The planner shows how many sample setups drop below `minimum_rr` with the midpoint target before freezing.
  - Family C stop: S3 outside the range edge by `sl_buffer_atr`; confirm the code matches and record.
- **D-11:** B and C stops are about 0.2 ATR from the entry reference with baseline buffers. Together with the D-06 invariant and the Phase 12 guards this may reject nearly every B/C setup. The planner **measures this on sample data and reports the count to the user**; it does not loosen a guard or tune a buffer to rescue signal volume (D-17).
- **D-12:** Whichever way a cell is resolved, the family sheets get an "implemented as" line, the Status stays HYPOTHESIS/NOT FROZEN (no sheet becomes frozen here), and the F-113 "implemented: NO" wording is corrected.
- **D-13:** Leakage audit for B/C: `_detect_breakout_retest_setup` and `_detect_range_mr_setup` use `_swing_series` at `ref_prev` and `ref_idx`. The planner proves per detector, with a test, that the evaluated bar is excluded from the reference level, or moves it to the confirmed-pivot function (D-04).

**Parameter sets, rationale, versioning (F-909)**
- **D-14:** One DECISIONS entry (next id D054, status Accepted with the auto-mode note) records: the geometry audit outcome, each kept deviation with its reason, the new keys, the new set ids, and the regeneration inventory (fixtures, pins, hashes that moved), in the style of D048/D053.
- **D-15:** New sets `params/<family>/baseline-v6.toml` for each family whose geometry or keys change, with `strategy_version` bumped to `v5.0.0` for those families (new behavior means a new set and a new strategy version; Phase 12 D-04/D-06 pattern). Existing sets stay byte-identical (F-810). `baseline-no-trade-*` and `baseline-simple-trend-*` degenerate sets are re-issued only if the planner finds they must follow the version bump; their independence rules in `src/analytics/family.py` must keep passing.
- **D-16:** **Every value in a new set carries a recorded rationale**; no value is inherited silently from the Phase 3 / 04-01 seed set. Rationale lives where it is machine-checkable (planner picks: a rationale table consumed by a test that fails when a key has none, or a structured comment block parsed by a test) and must not change the hash of any existing set. A value with no empirical or structural basis is marked `PLACEHOLDER`, and a `PLACEHOLDER` set cannot be frozen for paper (the Phase 16 freeze path must refuse it; the planner adds the refusal or records where it will live).
- **D-17:** No value is chosen or adjusted after looking at backtest results. Values come from declared ranges and structural arithmetic (ATR multiples tied to the geometry, cost ratios tied to Phase 12 guards). The user ratifies the final numbers in the planner's `checkpoint:decision`.

**Tests and readiness**
- **D-18:** Geometry is verified by **hand-derived expected values** in committed sidecars (same discipline as Phase 14 D-24), not regenerated from `src/`. Required cases per family: LONG and SHORT worked example with real numbers; SL outside zone; signal bar already through the stop; stop below minimum ATR distance; no confirmed pivot; pivot confirmed exactly at `t+R` and not before; prefix-invariance of pivots; a new-N-bar-low bar that must NOT signal (the p9 reproduction at `tmp/business_invariants/p9_trend_pullback_new_low.py` in the audit snapshot becomes a regression test); a property test over a grid of ATR, tolerance and buffer values asserting the D-06 invariant for all three families.
- **D-19:** Deliberate regeneration: golden planner outputs, Phase 6 fixtures built by `scripts/gen_phase6_fixtures.py`, signal ids and plan hashes that move are listed once in the DECISIONS entry (D-14). Fixtures not rebuilt are relabeled regression snapshots, consistent with Phase 14 D-25.
- **D-20:** Criterion 4 (research re-run readiness) is a verifiable check, not a run: the new sets load and register under protocol v2.0.0, the Phase-14 engine runs a small real-data smoke (`scripts/smoke_backtest_realdata.py`) on them end to end with zero invariant violations, and the planner states what a re-run still needs (candidate-set freeze step per RESEARCH_PROTOCOL, data window, universe). The planner checks whether the protocol needs another version bump and records the answer; the default expectation is that it does not (protocol governs method, not strategy values).
- **D-21:** Determinism stays strict: Decimal only via `src/core/_decimal.py`, no float, no wall clock, sorted iteration, byte-identical reruns. `src/core` stays free of Polars and FastAPI.

### Claude's Discretion
- Module placement of the pivot function (`features.py` vs a new `pivots.py`), names of the new reason codes if any, internal helper names, and test file layout, provided the D-06 invariant lives in one place shared by all families.
- Format of the rationale record (D-16) as long as it is machine-checked and hash-neutral.
- Whether the geometry audit table is a doc under `docs/research/families/` or a section of the DECISIONS entry.

### Deferred Ideas (OUT OF SCOPE)
- Family C T-opposite target and other sheet variants (A1-A6, B-retest-2, C-pullback-2..4) as candidate sets: research phase, not this phase.
- Regime detector alternatives R2/R3 and pullback variants P2-P4: research.
- Live producer for TP1 quantity split and exit ladder (F-103): later phase.
- Incremental feature series (performance): already deferred past Phase 15 by Phase 14 D-31.
- Freezing any family sheet: only after real research evidence.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRAT-01 | Feature engine computes deterministic indicators/structure/zones from closed candles only, with warm-up gates (e.g. EMA200-4H invalid until history suffices) [VERIFIED: .planning/REQUIREMENTS.md:32] | Section 1 (confirmed-pivot feature, last-bar-only computation, frame fields), Section 2 (leakage audit), prefix-invariance test design |
| STRAT-02 | Strategy engine is a pure function (market snapshot + account state + strategy version + config -> NO_TRADE or SETUP) emitting deterministic SignalIds [VERIFIED: .planning/REQUIREMENTS.md:33] | Section 1 (`_detect_setup` rewrite, legacy-path policy), Section 6 (signal-id and fingerprint ripple) |

Both requirements are already "Complete" (Phase 4); this phase corrects their implementation and does not change their status. The planner geometry (STRAT-03) is touched too but is not a phase requirement ID.
</phase_requirements>

## Summary

The phase is mostly pure-core surgery plus governance. The headline defect (F-301) is confirmed in code: Family A's setup level is the trailing 20-bar extreme that includes the evaluated bar (`features.py:187`), and its stop sits inside its own entry zone (`planner.py:116` stop `swing_low - sl_buffer` vs `planner.py:382` `entry_min = zone_lower - entry_buffer`). On 2 years of local 1H data a float prototype shows 100 percent of old Family A signals have the stop inside the zone and about 41 percent fire on a bar that is itself the new 20-bar low (BTCUSDT: 1,111 of 2,722 per-bar signals). The fix as locked (D-01..D-09) is implementable without new packages: one pure pivot function evaluated for the last bar only, one shared geometry validator in the planner, three optional registry keys, a hash-neutral in-file `[rationale.*]` table, and `baseline-v6` sets at `strategy_version` `v5.0.0`.

The research found that CONTEXT premises need correction in several places that change plan content (see "Flags" below). The most important: (1) Family C can never emit a signal on real data because its regime gate requires the 4H close to equal EMA50 exactly (0 NEUTRAL bars in 17,520 4H closes across 4 symbols); (2) the Family B detector is not anchored to the evaluated bar, so it signals on essentially every bar from stale breakouts (retest bar median age 37 bars, only 10 percent within the 5-bar window) and ignores the 4H direction gate the sheet requires; (3) the Family B arithmetic in D-10 (`RR < 1`) holds only if "the other side of the broken zone" means the far end of the whole 20-bar range; with the sheet's narrow S/R zone, S3 gives RR about 4.5 and survives the Phase 12 guards on 75-88 percent of bars, whereas the kept code stop survives on 0-6.5 percent; (4) D-07 is vacuous for Family A under the D-05 geometry and only bites B/C; (5) the RR gate uses `abs()` so a TP on the wrong side of entry passes it.

The universal D-06 invariant is cheap in production code but expensive in tests: with the invariant alone (legacy swing semantics), 72 existing tests fail and 1 errors (backtest simulator 30, planner 10, experiment 8, determinism 5, engine-strategy 4, paper parity 3, cost parity 3, phase-6 fixture geometry 9 of which 1 is a pre-existing CRLF failure, plus a PG test). All of these ride on `baseline-v1..v5` trend-pullback plans from `gen_phase6_fixtures.py` or Phase 4 candles and must be migrated to hand-built pivot structures plus `baseline-v6`.

**Primary recommendation:** Implement D-01..D-09 as locked with these additions: pivots computed for the last bar only and gated by the presence of `pivot_left_bars`/`pivot_right_bars` (legacy sets keep their old signal path, but every plan from any set passes the new shared validator); reuse `STOP_TOO_TIGHT` (stop not outside zone, below `min_stop_atr`) and `INVALIDATED` (signal bar through stop) so no enum, GLOSSARY count or DB change is needed; keep rationale as `[rationale.<key>]` tables inside each set file (hash-neutral, verified); put the PLACEHOLDER refusal in `pin_stream_epoch`; and take the five open decisions in "Open Questions" to the user before freezing any number.

## FLAGS: CONTEXT premises that are contradicted, incomplete, or infeasible (read first)

| # | CONTEXT item | Finding | Evidence | Recommended handling |
|---|--------------|---------|----------|----------------------|
| F1 | D-10/D-11 (Family C), Success criterion 2 | **Family C is inert on real data.** `_resolve_regime` returns NEUTRAL only when `last_context_close == ema_50` exactly; `evaluate` requires NEUTRAL for `range-mr`. Measured: 0 NEUTRAL 4H bars of 4,380 each for BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT (BULL/BEAR split only). D-11's "measure the count on sample data" will report 0 for C. | [VERIFIED: strategy.py:116-120] `if last_context_close > context_frame.ema_50.value: return "BULLISH"` / `... < ...: return "BEARISH"` / `return "NEUTRAL"`; [VERIFIED: strategy.py:592] `if parameter_set.strategy_id == "range-mr" and regime != "NEUTRAL":`; [VERIFIED: scratch run neutral_count.py on data/raw 4h] | User decision needed (Open Question 2): record "Stage C skipped, regime gate unsatisfiable" per sheet 7.1, or implement a sheet-conformant range regime (R1 structure on confirmed 4H pivots, or an ATR band). Without it the D013 kill gate counts a third family that cannot trade. |
| F2 | D-13 (B/C leakage audit) | Neither detector leaks the evaluated bar into the reference level (proof in Section 2). But **B is not anchored to the evaluated bar**: it returns a setup if any breakout+retest exists anywhere in the 1000-bar window. Over 540 evaluated 1000-bar windows (BTCUSDT, last 2,160 bars, every 4th bar) it signalled in all 540; in a 68-window sample the retest-bar age (bars before the evaluated bar) had median 37, max 222, and only 10 percent were within the 5-bar `retest_window_bars`. | [VERIFIED: strategy.py:257] `for i in range(n - 1, breakout_confirmation_bars - 1, -1):` scans all history; [VERIFIED: strategy.py:293] retest search starts at `i + 1` with no requirement that it ends at the last bar; [VERIFIED: semantics.py:43] `STRATEGY_WINDOW_BARS = 1000`; [VERIFIED: scratch run famBC_real.py] | Add anchoring (retest bar must be the evaluated bar `n-1`) with a regression test; anchored count is about 30-50 setups per 2,160 bars per symbol. This is a behavior change: needs a version gate (Flag F11). |
| F3 | D-10 Family B stop arithmetic | The "RR < 1" claim is correct only for S3 read as "far end of the whole range" (code `zone_lower`). With the sheet's S/R zone (narrow, `swing_high +/- zone_tolerance_atr*ATR`) the far side is 1.0 ATR below the retest edge; stop 1.2 ATR from entry_ref; RR to the code's measured-move TP is about 4.5 (median real height 5.57 ATR / 1.2). | Section 4 worked numbers [VERIFIED: scratch geom_numbers.py, Decimal arithmetic]; S3 text: "SL = phía bên kia của support/resistance zone" [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:479-483] | Present both readings in the planner's `checkpoint:decision` (Open Question 1). Keeping the code stop (0.3 ATR adverse distance) is rejected by the Phase 12 guards on 93.5 percent of bars in the frozen universe (6.5 percent survive; BTC 0.0 percent). |
| F4 | D-07 "closes the p9 case" | Under D-05 the signal only fires when the bar low is inside the zone `[P - half, P + half]`; the stop is `P - half - entry_buffer - sl_buffer` below that, so the signal bar can never already be through the stop for Family A. p9 is closed by D-01 (pivot) alone. D-07 bites Family B (retest band 0.3 ATR deep vs stop 0.2 ATR) and Family C (touch band 0.3 ATR vs stop 0.2 ATR). Also D-01's "can no longer fire" has a nuance: a new low still fires if it lies within `zone_tolerance_atr*ATR` below the prior pivot. | [VERIFIED: strategy.py:157] `if support_lower <= last_setup_candle.low <= support_upper:`; [VERIFIED: strategy.py:351] B band `band_lo <= setup_candles[k].low <= band_hi` | Keep D-07 as defense in depth, test it on B and C; the p9 regression test must assert the concrete numbers (new low more than tolerance below the pivot gives no signal; inside tolerance gives a plan with SL below the bar low). |
| F5 | CONTEXT specifics: "S=60,000, ATR=400 must no longer produce a plan" | With D-05 geometry the same inputs produce a corrected plan (pivot 60,000: zone 59,760-60,240, SL 59,680, cost-to-risk 0.1303, passes both Phase 12 guards). The old stop-inside-zone plan (stop 80 = 0.133 percent, RR 25) is what must disappear. Note the old geometry at the adverse edge already fails COST_TO_RISK_EXCEEDED (0.2081) at the risk layer. | Section 4 [VERIFIED: scratch geom_numbers.py] | Phrase the acceptance test as "no plan with SL inside zone or stop 80", not "no plan". |
| F6 | D-06/D-09 RR gate | `realized_rr = _div(abs(_sub(tp1, entry_ref)), risk)` uses `abs()`, so a TP1 on the loss side of the entry passes the RR gate. With pivot-derived TP1 this occurs (2-4 per 17.5k bars per symbol in the prototype) and TP2 is then built on the wrong side. | [VERIFIED: planner.py:409] `realized_rr = _div(abs(_sub(tp1, entry_ref)), risk)`; [VERIFIED: planner.py:402] `tp1_leg = _sub(tp1, entry_ref) if signal.direction == "LONG" else _sub(entry_ref, tp1)` | Require `tp1_leg > 0` (profit side) in the shared validator; reason `RR_TOO_LOW`. |
| F7 | D-15 baselines | `baseline-simple-trend-v3` (zone_tolerance 1.0, minimum_rr 0.5) and `baseline-no-trade-v3` run the same Family A code path. With the universal invariant the simple-trend baseline produces zero plans, so protocol section 3 "Baselines" becomes unmeasurable. The no-trade baseline's reason changes from `RR_TOO_LOW` to the invariant's reason unless the RR gate is ordered first. | [VERIFIED: baseline-simple-trend-v3.toml diff vs baseline-v5: `zone_tolerance_atr = 1.0`, `minimum_rr = 0.5`]; [VERIFIED: tests/test_phase6_fixture_geometry.py:199-202] asserts `RR_TOO_LOW` for no-trade | Re-issue both degenerate baselines as `-v4` with the pivot keys (they MUST follow, not "only if"). Decide check order (invariants first, recommended) and update the no-trade assertion. |
| F8 | D-20 "zero invariant violations" | No existing measure: trade records carry no stop or zone fields, so a smoke run cannot count geometry violations. | [VERIFIED: records.py:80-120] TradeRecord fields (entry_price, exit_price, tp1_price... no stop_loss/zone) | Define it as: both smoke runs exit 0 with equal digests, only canonical reason codes appear, plus a separate planner-level property test. Optionally add a geometry counter via a thin wrapper script. |
| F9 | D-12 sheets | Editing the three family sheets changes `sheet_sha256`, which D030 independence uses. No test pins the digest (scan is dynamic) and no experiment evidence exists yet. | [VERIFIED: analytics_files.py:246-260] hash over LF-normalized bytes; [VERIFIED: docs/research/kill_gate_decisions.json] `"families": []`; no repo file other than audit OUTPUT_HASHES.txt contains the current digests | Edit the sheets before any CANDIDATE experiment is recorded; no test change. |
| F10 | Sheet deviations not listed in D-10 | The Stage baselines also fix the regime and detector choices. Family A/B/C Stage baselines say R1 (structure-only); code uses EMA50(4H) (a comment in `_resolve_regime` calls it an R2-style proxy). Family B sheet baseline is B1 (single close) and R1 retest "low inside the broken zone"; code uses `breakout_confirmation_bars = 3` and a band of `retest_depth_atr` around the outer edge. Family B must be with-direction only (sheet 2.4); code admits counter-trend breakouts. Family A zones have merge/collide/separate semantics and `zone_min_touches`; code uses a single pivot. Registry keys `regime_filter_lookback` and `breakout_volume_threshold` are never read. | [VERIFIED: strategy.py:98-120, 236, 583]; `grep` shows no reader for `regime_filter_lookback` or `breakout_volume_threshold` outside registry.py | Add these cells to the D-10 audit table; each is "fix" or "record deviation" in D054. Several are pure parameter choices (`breakout_confirmation_bars = 1` is B1). |
| F11 | D-15/F-810 vs behavior fixes in B/C | Anchoring (F2), direction gate (F10), T-mid (D-10) change B/C output under an unchanged `strategy_version`. Phase 12 rule: new behavior = new set + version bump. | [VERIFIED: baseline-v5.toml header] "New behaviour means a new set and a strategy-version bump (D-04, D-06)" | Gate each behavior by an optional key (`tp_mode` for C is already implied by D-10) or one optional integer `geometry_version` (absent = legacy). Planner decision (Open Question 5). |
| F12 | Local test environment | `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` already fails on this Windows checkout: working tree is CRLF (`git ls-files --eol`: `i/lf w/crlf`, `core.autocrlf=true`) while the generator writes LF. | [VERIFIED: pytest run this session; git ls-files --eol] | Regenerating Phase 6 fixtures will hit this again. Normalize line endings in the comparison or add `tests/fixtures/phase6/** text eol=lf` to `.gitattributes`; do not treat as a Phase 15 regression. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Confirmed pivot computation | Pure core (`src/core/features.py` or new `src/core/pivots.py`) | - | Pure function of closed candles; no I/O; Decimal only (D-21) |
| Family A setup detection from pivot | Pure core (`strategy._detect_setup`) | - | Strategy is a pure function (STRAT-02) |
| Geometry (zone, SL, TP) | Pure core (`planner._long_geometry/_short_geometry`) | - | CR-05: geometry priced from trigger levels |
| Shared geometry invariants (D-06/07/08 + TP side) | Pure core, one function in `planner.py` | Risk layer (`_plan_geometry_is_valid`, defense in depth) | One place for all families (Claude's discretion constraint) |
| Optional registry keys, cross-key checks | Domain (`src/domain/registry.py`) | - | Fail-closed loader owns key whitelist and ranges |
| Rationale record and PLACEHOLDER flag | Domain (new `src/domain/rationale.py`, reads set TOML) | Paper freeze (`pin_stream_epoch` refuses) | Hash-neutral metadata checked at pin time |
| Guards on money (min stop rate, cost-to-risk) | Risk layer (`src/risk/gating.py`, unchanged) | - | Phase 12 binding economic filter, not edited |
| Backtest consumption of plans | Backtest engine (`src/backtest/engine.py`, unchanged) | - | Calls `evaluate` then `plan` on 1000/300-bar windows |
| Fixtures, pins, decisions, sheets | Governance (tests, `scripts/`, `docs/`) | - | Regeneration inventory and D054 |

## Standard Stack

No new packages. Everything is existing project stack.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.13.15 [VERIFIED: `.venv/Scripts/python --version`] | Implementation language | Project baseline (AGENTS.md) |
| stdlib `decimal` via `src/core/_decimal.py` | - | All geometry arithmetic | D-21; `float` banned on the core path (`tests/test_domain_no_float.py` scans `src/core/*.py`) |
| stdlib `tomllib` | - | Registry and rationale table parsing | Already used by `src/domain/registry.py` |
| pytest | 9.1.1 [VERIFIED: `pytest --version`] | Tests | Project baseline |
| ruff / mypy | 0.16.8 / 2.3.1 [VERIFIED: tool versions]; `ruff check src tests scripts` and `mypy src` were green before changes (147 source files) | Lint, strict typing | Project quality gates |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-file `[rationale.<key>]` tables | Sidecar JSON under `docs/research/` | A new `.toml` under `params/` is read as a set by PA-01 (`rglob("*.toml")`) and by `analytics_files._candidate_hashes` (`glob("*.toml")`); a new directory under `params/` is read as a family. A docs sidecar is safe but can drift from the set it describes. In-file is verified hash-neutral and travels with the set. |
| New `RejectionReason` members | Reuse `STOP_TOO_TIGHT`, `INVALIDATED`, `RR_TOO_LOW`, `STALE_SETUP` | A new member touches enums, GLOSSARY 9.1 block and prose count, `test_domain_enums` (`len(RejectionReason) == 20`), three count asserts in `test_decision_alignment_bookkeeping`, `PHASE_12_CODES` superset test. Reuse touches only a GLOSSARY prose sentence. |

**Installation:** none. **Version verification:** not applicable (no packages added).

## Package Legitimacy Audit

No external packages are installed or recommended in this phase. `slopcheck`/registry checks not required. Packages removed due to [SLOP]: none. Packages flagged [SUS]: none.

## Architecture Patterns

### System Architecture Diagram

```
 closed 1H candles (last 1000)      closed 4H candles (last 300)
        |                                   |
        v                                   v
  compute_features (1H)              compute_features (4H) --> _resolve_regime (EMA50 proxy)
   |  ema/atr/legacy swing/zone          |                          |
   |  + NEW pivot_high/pivot_low         |                          v
   |    (last bar only, needs            |                   regime BULL/BEAR/NEUTRAL
   |    pivot_left/right keys)           |                          |
   v                                     +--------------------------+
 evaluate(): feature gate -> regime gate -> forming-bar gate -> detector
   |   A: _detect_setup(pivot level P, zone P +/- tol*ATR, low in zone?)
   |   B: _detect_breakout_retest_setup (+ NEW: retest bar == evaluated bar, direction == regime)
   |   C: _detect_range_mr_setup (regime gate: see Flag F1)
   v
 Signal (id binds zone, ATR, EMAs) --> plan(signal, setup_candles, params, account)
   |  recompute features + geometry (_long/_short_geometry)
   |  quantize_for_storage(entry_min, entry_max, SL, TP1)
   |  NEW shared validator, fixed order:
   |     1 SL outside whole zone            -> STOP_TOO_TIGHT
   |     2 signal bar not through SL        -> INVALIDATED
   |     3 |entry_ref-SL| >= min_stop_atr*ATR (if key present) -> STOP_TOO_TIGHT
   |     4 TP1 on profit side of entry      -> RR_TOO_LOW
   |     5 RR gate (unchanged)              -> RR_TOO_LOW
   v
 TradePlan (hash binds zone, SL, TPs) --> evaluate_risk (Phase 12 guards, adverse-edge sizing,
                                          STOP_TOO_TIGHT / COST_TO_RISK_EXCEEDED, quantization)
   --> backtest engine / paper loop
```

### Recommended Project Structure
```
src/core/pivots.py            # NEW (or inside features.py): pivot_at(), pure, Decimal
src/core/features.py          # FeatureFrame gains optional pivot_high / pivot_low (default None)
src/core/planner.py           # _geometry_rejection(...) shared by all families; Family A geometry change
src/core/strategy.py          # _detect_setup reads pivot level; B anchoring/direction gate if approved
src/domain/registry.py        # pivot_left_bars, pivot_right_bars, min_stop_atr (+ tp_mode) keys
src/domain/rationale.py       # NEW: load/check [rationale.*]; placeholder_keys(); pure, stdlib only
src/paper/freeze.py           # pin_stream_epoch refuses PLACEHOLDER / missing rationale
params/<family>/baseline-v6.toml  (+ trend-pullback baseline-no-trade-v4, baseline-simple-trend-v4)
tests/fixtures/phase15/       # hand-derived geometry cases + DERIVATIONS.md
tests/test_core_pivots.py, tests/test_planner_geometry.py, tests/test_geometry_property.py,
tests/test_rationale.py, tests/test_registry.py (extended), tests/test_decision_alignment_params.py (PA-08)
```
Add `src/core/pivots.py` and `src/domain/rationale.py` to `SCANNED_FILES` in `tests/test_domain_no_float.py` ("extend this list only").

### Pattern 1: Confirmed pivot for the last bar only
**What:** `pivot_at(candles, i, lookback, left, right, high)` returns the most recent confirmed pivot level whose index `t` satisfies `max(left, i - lookback + 1) <= t <= i - right`, scanning `t` from `i - right` downward. Window `[t-left, t+right]` is entirely `<= i`, so bar `i` is only ever a right-confirmer, never the level. Tie rule (Assumption A1): pivot low at `t` iff `low[t] <= low[j]` for `j` in `[t-left, t-1]` and `low[t] < low[j]` for `j` in `[t+1, t+right]` (mirror for highs), so equal extremes yield one deterministic pivot.
**When to use:** Family A setup level and TP1 (opposite pivot). Computing only the last bar costs O(lookback x (L+R)) per call instead of O(n x lookback x (L+R)); this matters because the engine calls `evaluate` and `plan` per bar on 1000-bar windows and a prior pass measured about 311 s per 75-day BTC smoke run on baseline-v5 [CITED: scratchpad smoke_v5_75d_time.txt, prior pass].
**Hand-derived micro example:** lows `t-3..t+3 = 105, 104, 103, 100, 103, 104, 105` (L=R=3). At `i = t+2` the pivot is not reported; at `i = t+3` it is, level 100. Appending later bars never changes the value reported at any earlier `i`.

### Pattern 2: One shared geometry validator
Single private function in `planner.py` called by `plan()` after quantization for every family, so the invariant cannot be skipped per family. Order is fixed and tested (see diagram). Run it BEFORE the RR gate (structural validity first); Flag F7 explains the consequence for the no-trade baseline assertion.

### Pattern 3: Optional presence-gated registry key (Phase 12 way)
`STRATEGY_KEYS` entry + `INT_KEYS` or `DECIMAL_KEYS` membership + `_check_value_range` branch + tests. Absent key = legacy behavior = identical hash. Cross-key check in `_parse_and_validate`: both pivot keys or neither; each >= 1; `pivot_right_bars + 1 <= swing_lookback` when `swing_lookback` is present.

### Pattern 4: Hash-neutral rationale table
```toml
[rationale.swing_lookback]
basis = "PLACEHOLDER"   # one of STRUCTURAL | COST_GUARD | DECISION | EXPERIMENT | PLACEHOLDER
text  = "20 one-hour bars, about 0.83 day. No empirical basis yet; declared range to be fixed before any sweep."
```
Verified: appending `[rationale.swing_lookback]` to a copy of `baseline-v5.toml` leaves `parameter_set_hash` `41ed39d4be10...` unchanged and `verify_parameter_set` passes [VERIFIED: scratch rationale_neutral.py]. Reason: the hash payload is `strategy_id`, `strategy_version`, `parameter_set_id` and the normalized `[parameters]` only [VERIFIED: registry.py:471-477], and `_extract_raw_param_strings` stops at the next `[` header [VERIFIED: registry.py:217-219].

### Anti-Patterns to Avoid
- **Fallback to the trailing extreme when no pivot exists** (forbidden by D-03). Return `None` from `_detect_setup` (existing "no setup" reason `NO_TRADE_REGIME`).
- **Adding pivot validity to `features_valid`.** It would turn "no pivot in the last 20 bars" into `WARMUP_INSUFFICIENT`, which is a lie; keep pivots optional on the frame.
- **Tuning buffers to rescue B/C signal volume** (D-11, D-17). The survival tables below are informational arithmetic about guard thresholds, not a selection criterion.
- **Putting any `.toml` rationale file or sub-directory under `params/`** (read as a set / family by PA-01, family scan, kill-gate tripwire; same reason the universe manifest lives under `docs/research/universe`).
- **Using `abs()` for the TP leg** (Flag F6).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Decimal arithmetic | local rounding helpers | `_add/_sub/_mul/_div/_q` from `src/core/_decimal.py`, `quantize_for_storage` | Pinned precision; `test_domain_no_float` scans these modules |
| Rejection vocabulary | new reason strings | existing `RejectionReason` members | `build_reject_record` raises if `reason_code not in _REJECT_REASONS` [VERIFIED: records.py:441] |
| Hash identity | custom file hashing | `load_parameter_set` / `verify_parameter_set` | Canonical, already pinned by PA-01 |
| Cost guards | new cost math in planner | `src/risk/cost_guards.py`, `gating.py` (unchanged) | Binding economic filter; Phase 12 owns it |
| Fixture expectations | `expected.json` produced by `src/` | hand-derived JSON + `DERIVATIONS.md` (Phase 14 D-24 style) | Regenerating from src re-blesses behavior (F-608) |

**Key insight:** the phase needs almost no new machinery; the risk is in what ripples (72 tests, fixtures, pins) and in premises (Flags F1-F3), not in the pivot code.

## 1. Current code paths and consumer inventory

**Planner (`src/core/planner.py`, 502 lines).** `_long_geometry` (91-148) and `_short_geometry` (151-197) return `(zone_upper, zone_lower, stop_loss, tp1)`. Family A LONG [VERIFIED: planner.py:109-118]: `half = _mul(zone_tolerance_atr, atr)`, `support_upper = _add(swing_low, half)`, `support_lower = _sub(swing_low, half)`, stop `_sub(swing_low, sl_buffer)`, TP1 `swing_high`. B LONG (119-136): zone edge from `_detect_breakout_retest_setup`; `height = _sub(zone_upper, zone_lower)`; returns `(zone_upper, zone_upper, _sub(zone_upper, sl_buffer), _add(zone_upper, height))`. C LONG (137-147): `(zone_lower, zone_lower, _sub(zone_lower, sl_buffer), zone_upper)`. `plan()` (205-499): features as validity gate (294-335), entry zone `entry_min = quantize_for_storage(_sub(zone_lower, entry_buffer))`, `entry_max = quantize_for_storage(_add(zone_upper, entry_buffer))` (382-383), `entry_ref = _div(_add(entry_min, entry_max), _q("2"))` (389), `risk = abs(_sub(entry_ref, stop_loss))` (392), RR gate (408-415), invalidation JSON `level = stop_loss` (428-439).

**Features (`src/core/features.py`, 445 lines).** `_swing_series` (166-193) window `candles[i - lookback + 1 : i + 1]` (line 187); `_zone_series` (201-236) builds `zone_lower = swing_low - half`, `zone_upper = swing_high + half`; `compute_features` (320-438) calls them at 382-386, gap-invalidates at 391-406, `features_valid` is the AND of 8 features (412-422). `FeatureFrame` is constructed in exactly one place (features.py:424) [VERIFIED: grep `FeatureFrame(`], so adding defaulted optional fields `pivot_high`, `pivot_low` is a one-site change.

**Strategy (`src/core/strategy.py`, 711 lines).** `_detect_setup` (128-162) reads `setup_frame.swing_low/high` and `zone_tolerance_atr`; LONG in BULLISH when `support_lower <= low <= support_upper` (157). `_detect_breakout_retest_setup` (208-324), `_find_retest_bar` (327-356), `_detect_range_mr_setup` (364-470). `evaluate` (478-708): feature gate (540-572), regime gate (574-597), forming-bar gate (599-618), family dispatch (620-651), fingerprint binds `zone_upper`, `zone_lower`, `atr`, EMAs (660-670).

**Consumers of `swing_high/swing_low/zone_*`:**

| Where | What reads it |
|-------|---------------|
| `src/core/types.py:176-206` | FeatureFrame fields and `features_valid` consistency check |
| `src/core/features.py` | `_swing_series`, `_zone_series`, `compute_features` (382-438) |
| `src/core/strategy.py:42,145-162,251-252,396-397,547-556` | import of `_swing_series`; `_detect_setup`; B and C detectors; evaluate gate loop |
| `src/core/planner.py:309-335` | gate loop and swing values passed to geometry |
| `scripts/_compute_phase4_fixtures.py:155-165`, `scripts/_regen_phase4_expectations.py:119-130,257-267` | frame values written to Phase 4 fixtures |
| tests | `test_core_features.py` (495-512, 576-577, 640-641), `test_core_planner.py` (143-157, 256-264), `test_core_tracer.py` (173-176), `test_no_lookahead.py` (269-281), `test_core_strategy_breakout_retest.py` (24, 711), comments only in `test_core_strategy_range_mr.py` |
| fixtures | `tests/fixtures/phase4/expected_features.json` keys `setup_swing_high/low`, `setup_zone_upper/lower`; read via `tests/conftest.py` fixture `phase4_expected_features`; `expected_plans.json` consumed only by `tests/test_plan_hash_roundtrip_pg.py` (needs PostgreSQL) |
| no other `src/` module | [VERIFIED: grep over `src/` found hits only in `src/core`] |

Therefore: keep the legacy `swing_*` and `zone_*` features and the `_swing_series` helper untouched (B/C use it), and add pivot features alongside. This leaves `test_core_features`, `test_core_tracer` feature checks, `expected_features.json` and both Phase 4 scripts valid without edits.

**Consumers of plans (all go through `plan()` unchanged in shape):** `src/backtest/engine.py:43` (`plan as build_trade_plan`), `src/paper/loop.py:29`, scripts. `scripts/demo_rehearsal.py` does not use the planner (its `derive_plan` is its own function).

**Legacy-path policy (Open Question 5).** Recommended: pivot mode is enabled only when `pivot_left_bars` is present in the set. Sets `baseline-v1..v5` keep their signal path (reproducible signal ids), but every plan goes through the new validator, so legacy Family A sets can emit signals and never plans. Alternatives: default 3/3 for all sets (changes every legacy signal id under an unchanged version) or fail closed when keys are absent (kills all legacy-set tests that evaluate signals, including `test_core_tracer`, `test_no_lookahead`, `test_prefix_invariance`, `test_candle_close_timing`, which pass today with the invariant alone).

## 2. Leakage audit for Families B and C

**Family B** [VERIFIED: strategy.py:257-262]:
```
for i in range(n - 1, breakout_confirmation_bars - 1, -1):
    ref_bar = i - breakout_confirmation_bars          # line 258
    ref_prev = ref_bar - 1                            # line 259
    sh_ref_out = swing_high_series[ref_prev]          # line 262
```
`i` is the last of the breakout bars, so `ref_prev = i - breakout_confirmation_bars - 1` (= `i - 4` with the registry value 3). `swing_high_series[ref_prev]` covers bars `ref_prev-19 .. ref_prev`. The retest search starts at `i + 1` (line 293), so the evaluated bar `n-1 >= i+1 > ref_prev`. The reference level and ATR (`atr_series[ref_prev]`, WR-12) never include the evaluated bar nor any breakout bar. Existing test `tests/test_core_strategy_breakout_retest.py:~700-733` already asserts the reference-bar offset ("Beh. 4c"). Verdict: **no leakage of the evaluated bar**; trailing helper may stay for B per D-04. The defect is anchoring (Flag F2).

**Family C** [VERIFIED: strategy.py:401-404]: `ref_idx = last_idx - 1`; `sh_ref_out = swing_high_series[ref_idx]`, `sl_ref_out = swing_low_series[ref_idx]`, `atr_ref_out = atr_series[ref_idx]`. Window covers `ref_idx-19 .. ref_idx = n-2`; the evaluated bar `n-1` is excluded from the level and the ATR. Touches are scanned in `range(swing_lookback, ref_idx - swing_lookback + 1)` (line 433), i.e. strictly before the 20 bars that define the level. Verdict: **no leakage of the evaluated bar**. Caveat: the level can be set by bar `n-2` (an unconfirmed extreme one bar old). That is a design choice, not a leak; record it in the audit table, do not "fix" it here.

**Required tests (D-13):** per detector, build candles where the evaluated bar sets a new extreme beyond the reference window and assert the zone/level is unchanged by that bar (append an extreme bar, compare the returned zone to the zone from the prefix). For B add the anchoring regression (a historical breakout+retest 40 bars ago must not signal).

## 3. Registry extension, hash neutrality, rationale and PLACEHOLDER

**Adding a key the Phase 12 way** [VERIFIED: registry.py:59-130, 284-316, 319-353, 356-383, 400-445]:
1. Add names to `STRATEGY_KEYS` (the Phase 12 block reads `"exit_slippage_rate", "min_stop_distance_rate", "max_cost_to_risk", "commission_rate_ttl_seconds"` at lines 125-128).
2. Integer keys (`pivot_left_bars`, `pivot_right_bars`) go in `INT_KEYS` (284-303); `DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS - STRING_KEYS` (316) picks up `min_stop_atr` automatically; a string key such as `tp_mode` goes in `STRING_KEYS` (308-315) with a closed value set check next to the `working_type` branch (372-376).
3. Range branches in `_check_value_range` (319-353): pivot widths `>= 1`; `min_stop_atr` finite and `> 0` (PROPOSED upper bound 10).
4. Cross-key rule in `_parse_and_validate` (after types): both pivot keys together; `pivot_right_bars + 1 <= swing_lookback`.
5. Tests copying `tests/test_registry.py:862-990`: whitelisted with expected types, a set with the keys loads, a set without them loads and keeps its hash, out-of-range and bool values rejected, NaN rejected.
6. `check_strategy_key_outside_registry` automatically rejects ambient config named like the new keys (`_is_strategy_key_name`, 529-542); grep found no runtime config with those names.

**Old sets stay hash-identical:** absent optional keys leave the normalized params unchanged; PA-02/PA-03 (`scripts/decision_alignment/params.py`) and PA-01 pins guard it. No test enumerates `STRATEGY_KEYS` exactly (only membership asserts at `tests/test_registry.py:890-892, 971-975`).

**Rationale record (recommended):** in-file `[rationale.<key>]` tables as in Pattern 4, covered by a new pure module `src/domain/rationale.py` with `check_rationale(path) -> list[str]` (every `[parameters]` key has an entry, no extra entries, non-empty `text`, `basis` in the closed vocabulary, `EXPERIMENT` basis must cite an experiment id) and `placeholder_keys(path)`. Add a "consumed by" note per key: `regime_filter_lookback` and `breakout_volume_threshold` are never read, and `breakout_confirmation_bars` is read only by Family B, so carrying them in A/C sets is dead weight (omit them in v6 or mark `INERT`). The PLACEHOLDER vocabulary is research-compatible: placeholders may run research, may not be paper-frozen.

**Where the refusal lives:** `pin_stream_epoch` in `src/paper/freeze.py:340-406` is the single pin entry point (Phase 16 composes it). Add: refuse when `placeholder_keys` is non-empty or the rationale is missing/incomplete, via a typed exception. Strict default breaks the existing pin tests that pin legacy sets (`tests/test_paper_freeze.py:122,178,213,276,357,412` and `tests/test_cost_per_unit.py:681,695` use `baseline-v3/v2/v5` or the parity fixture identity), so give the function an explicit `allow_unrationalized: bool = False` and pass `True` at those call sites. Because a baseline-v6 set will contain PLACEHOLDER values until an experiment supplies a basis, the paper freeze will correctly require a later successor set whose values carry `EXPERIMENT` bases.

**Pins and gates to extend:** append the new sets to `tests/fixtures/phase4/parameters.json` (20 entries today; `tests/test_decision_alignment_params.py:44-48` asserts `len(gate.load_pins()) == 20`), add `PHASE15_SET_IDS`, expected version `v5.0.0` and a PA-08 check in `scripts/decision_alignment/params.py` (pattern of PA-07), and update `_EXPECTED_CANDIDATE_IDS` in `tests/test_analytics_files.py:59-69`. `src/analytics/family.py:22` treats only `baseline-no-trade-` and `baseline-simple-trend-` prefixes as baselines, so `baseline-v6` is a candidate and `-v4` baselines are excluded automatically; `strategy_id` is inside the hash payload so cross-family hashes stay disjoint.

## 4. Sheet vs code geometry audit (A, B, C) with arithmetic

Cost facts used below [VERIFIED: src/risk/cost_rates.py:149-151, src/risk/gating.py:123-155, tests/test_phase6_fixture_geometry.py:59-69]: cost per unit `= entry*(fee_entry+slippage) + stop*(fee_exit+exit_slippage)` with `0.0005+0.0001 = 0.0006` and `0.0005+0.0003 = 0.0008`; sizing and both guards use the **adverse zone edge** (`entry_max` for LONG, `entry_min` for SHORT); `min_stop_distance_rate 0.003`, `max_cost_to_risk 0.15`; the cost ceiling binds at a stop distance of about 0.79 percent of price. So the binding quantity is `d_adv`, the adverse-edge-to-stop distance in ATR, and a setup survives only when `ATR/price >= 0.0079 / d_adv`.

**Audit table (verdicts proposed; every non-MATCH cell becomes "fix" or "recorded deviation" in D054):**

| Family / cell | Sheet Stage baseline | Code today | Verdict |
|---|---|---|---|
| A regime | R1 structure-only (4H HH/HL) | EMA50(4H) close compare (`strategy.py:98-120`) | DEVIATION, record |
| A pullback | P1 zone touch | `support_lower <= low <= support_upper` (157) | MATCH, but level source wrong |
| A level | confirmed swings only (sheet 5 rows 1-3) | trailing 20-bar extreme incl. evaluated bar (`features.py:187`) | FIX (D-01) |
| A zone | zones with merge/collide/separate, `zone_min_touches` | single swing +/- tol | DEVIATION, record |
| A entry | E2 zone +/- ATR buffer | `zone +/- entry_buffer`, limit at zone mid | MATCH |
| A stop | S2: swing low minus k ATR | `swing_low - sl_buffer` (inside zone) | FIX (D-05); note D-05 measures the buffer from the outer zone edge, which is itself a reading of S2 to record |
| A target | T1 fixed R | TP1 = opposing swing, TP2 = 2 x leg | DEVIATION by D-09, record |
| B regime/direction | R1; with-direction only (sheet 2.4) | any non-NEUTRAL regime; direction from breakout side | FIX or record (Flag F10) |
| B breakout | B1 single close | `breakout_confirmation_bars = 3` | parameter choice (set 1 for B1) |
| B retest | R1 low inside broken zone | band `retest_depth_atr` around outer edge `zone_upper` | DEVIATION, record |
| B anchoring | retest confirmed at close of the retest bar | any retest in window | FIX (Flag F2) |
| B entry | E2 | edge +/- entry_buffer (degenerate zone) | MATCH (degenerate) |
| B stop | S3 other side of broken zone | `zone_upper - sl_buffer` | see arithmetic; Open Question 1 |
| B target | T1 fixed R | measured move `zone_upper + height` | DEVIATION by D-10, record |
| C regime | R1 range detection, filter ON | NEUTRAL == exact equality, never true | FIX or record "skipped" (Flag F1) |
| C range/zone | zones merged, `regime_filter_lookback` | 20-bar swing at `n-2`, touches before it; `regime_filter_lookback` unread | DEVIATION, record |
| C entry | E2 | edge +/- entry_buffer | MATCH |
| C stop | S3 outside range edge | `zone_lower - sl_buffer` (0.2 ATR) | MATCH in form; economically dead (below) |
| C target | T-mid | `zone_upper` (T-opposite) | FIX to T-mid (D-10) via `tp_mode` |

**Worked numbers (BTCUSDT-style, tol 0.5, entry_buffer 0.1, sl_buffer 0.2, minimum_rr 2.0) [VERIFIED: scratch geom_numbers.py, Decimal arithmetic].** Qty is floored to step 0.001; risk budget is 0.5 percent of equity.

| Case | Zone / ref / SL / TP1 | RR (to ref) | Adverse dist | cost-to-risk | Guards | Equity 500 | Equity 1000 |
|---|---|---|---|---|---|---|---|
| A old (S=60,000, ATR=400) | zone 59,760-60,240, SL 59,920 (inside zone), risk 80 = 0.133 pct | 25 | 320 (0.53 pct) | 0.2081 | COST_TO_RISK_EXCEEDED | - | - |
| A new LONG (P=60,000, ATR=400) | 59,760-60,240 / 60,000 / SL 59,680 / TP1 61,600 | 5.00 | 560 (0.930 pct) | 0.1303 | pass | qty 0.003, notional 180, realized risk 1.932 (77.3 pct) | qty 0.007, notional 420, 4.507 (90.1 pct) |
| A new SHORT (P=60,000, ATR=400) | 59,760-60,240 / 60,000 / SL 60,320 / TP1 58,400 | 5.00 | 560 (0.937 pct) | 0.1306 | pass | qty 0.003, 1.932 (77.3 pct) | qty 0.007, 4.509 (90.2 pct) |
| A new LONG (ATR=240, 0.4 pct) | 59,856-60,144 / SL 59,808 / TP1 60,960 | 5.00 | 336 (0.559 pct) | 0.1999 | COST_TO_RISK_EXCEEDED | - | - |
| Audit anchor 1 corrected (P=59,000, ATR=300) | old zone 58,820-59,180 SL 58,940 -> new SL 58,760 | - | 420 (0.71 pct) | 0.1642 (hand: 82.516/502.516) | COST_TO_RISK_EXCEEDED | - | - |
| B code today (SH 60,600, low 59,000, ATR 360) | zone_upper 60,780, height 1,960; entry 60,744-60,816, ref 60,780, SL 60,708, TP1 62,740 | 27.2 | 108 (0.178 pct) | 0.4406 | STOP_TOO_TIGHT and COST_TO_RISK | dead | dead |
| B S3 far end of whole range | SL = 58,820 - 72 = 58,748 | 0.96 = height/(height+buffer) | 2,068 (3.4 pct) | 0.0388 | pass | RR_TOO_LOW | RR_TOO_LOW |
| B S3 narrow S/R zone | SL = (60,780 - 360) - 72 = 60,348, TP1 62,740 | 4.54 | 468 (0.770 pct) | 0.1534 | COST_TO_RISK_EXCEEDED at this ATR (passes when ATR/price >= about 0.61 pct) | - | - |
| C code today (range 59,000-61,000, ATR 400) | entry 58,960-59,040, ref 59,000, SL 58,920, TP opposite 61,000 / T-mid 60,000 | 25.0 / 12.5 | 120 (0.203 pct) | 0.4076 | STOP_TOO_TIGHT | dead | dead |
| C S3 beyond the +/-0.5 ATR tolerance zone | SL 58,720 (0.5+0.2 ATR below edge), T-mid 60,000 | 3.57 | 320 (0.542 pct) | 0.2048 | COST_TO_RISK_EXCEEDED | - | - |

For the three passing/near-passing A rows the equity-1000 and equity-500 sizing also clears the exchange-style floors used in fixtures (min qty 0.001, min notional 5; realized-risk utilization 77-90 percent against the 0.6 floor).

**Survival of the guards on real data (informational, not a tuning input).** Float ATR14 on all 17,520 hourly bars (2024-10-03 to 2026-10-02) per symbol, [VERIFIED: scratch grid.py on data/raw 1h]. Fraction of bars with `ATR/price >= 0.0079/d_adv`:

| d_adv (ATR) | needs ATR/price >= | BTC | ETH | SOL | XRP | DOGE | 12 frozen-universe symbols pooled | live-5 pooled |
|---|---|---|---|---|---|---|---|---|
| 0.3 (B/C code today) | 2.633 pct | 0.000 | 0.005 | 0.016 | 0.049 | 0.038 | 0.065 | 0.015 |
| 0.6 | 1.317 pct | 0.034 | 0.169 | 0.285 | 0.270 | 0.399 | 0.445 | 0.166 |
| 0.8 | 0.988 pct | 0.107 | 0.425 | 0.606 | 0.486 | 0.684 | 0.646 | 0.364 |
| 1.0 | 0.790 pct | 0.237 | 0.661 | 0.820 | 0.674 | 0.842 | 0.771 | 0.548 |
| 1.3 (B narrow-zone S3) | 0.608 pct | 0.489 | 0.865 | 0.936 | 0.866 | 0.948 | 0.878 | 0.745 |
| 1.4 (A, D-05) | 0.564 pct | 0.565 | 0.898 | 0.953 | 0.898 | 0.963 | 0.901 | 0.790 |

Family A under D-05 has `d_adv = 2*(tol + entry_buffer) + sl_buffer = 2*(0.5 + 0.1) + 0.2 = 1.4 ATR`; planner risk from `entry_ref` is `tol + entry_buffer + sl_buffer = 0.8 ATR`, so D-08's 0.5 ATR floor is a backstop as stated. The Family A prototype on the local data (per-bar raw signals, L=R=3, lookback 20, regime EMA50 4H, [VERIFIED: scratch famA_proto.py, float, indicative]): BTCUSDT old 2,722 signals, 100 percent stop-in-zone, 1,111 on a new 20-bar low; new 3,280 signals, 2,622 pass the RR gate, 1,412 pass RR plus both guards; ETHUSDT new 3,146 / 2,541 / 2,289; SOLUSDT 3,069 / 2,549 / 2,425. Anchored Family B (retest on the evaluated bar) gives 51 / 30 / 29 setups per 2,160 bars for BTC / ETH / SOL; guard survival with `d_adv` 0.3: 0 / 0 / 0; with 1.3: 14 / 23 / 20 [VERIFIED: scratch famB_anch.py, real detector with anchoring patch]. These are raw per-bar counts before the engine's one-plan-per-symbol rule.

## 5. RejectionReason: reuse, do not add

`RejectionReason` has 20 members [VERIFIED: enums.py:131-155], including `RR_TOO_LOW = "RR_TOO_LOW"` (132), `STALE_SETUP = "STALE_SETUP"` (133), `INVALIDATED = "INVALIDATED"` (134), `STOP_TOO_TIGHT = "STOP_TOO_TIGHT"` (154). The backtest engine records planner rejects through `build_reject_record`, which raises unless the code is a `RejectionReason` value (records.py:441), so planner codes must come from the enum.

Recommended mapping (no enum change):
- SL not strictly outside the whole zone (D-06): `STOP_TOO_TIGHT` (the limiting case of a too-tight stop).
- signal bar already through the SL (D-07): `INVALIDATED` (CONTEXT's own wording: setup already invalidated).
- `|entry_ref - SL| < min_stop_atr * ATR` (D-08): `STOP_TOO_TIGHT`.
- TP1 on the loss side, or RR below minimum: `RR_TOO_LOW`.
- no pivot found in lookback: strategy returns None, existing `NO_TRADE_REGIME`; planner-time vanished pivot: existing `STALE_SETUP`.
Ripple of the reuse: GLOSSARY section 9.1 prose sentence for `STOP_TOO_TIGHT` (line 181) should add the planner-level meaning; the 9.1 block, the "20 members" counts, `test_domain_enums` and `test_decision_alignment_bookkeeping` stay unchanged (`INVALIDATED` and `STOP_TOO_TIGHT` are already in the referenced-code sets; the superset test `referenced <= PRE_PHASE_12_REFERENCED | PHASE_12_CODES` still holds). `reason_code` columns are `String(64)` (no enum DB constraint) [VERIFIED: src/db/models.py:545]. `src/analytics/no_trade.py` maps only 9 codes; the two reused codes land in `UNMAPPED`, which is counted, never dropped (`category_for`). If the user prefers a dedicated code later, adding one touches: enums.py, GLOSSARY 9.1 block and the count sentences, `tests/test_domain_enums.py` (`len(RejectionReason) == 20` and the expected set), three `== 20` asserts in `tests/test_decision_alignment_bookkeeping.py`, and possibly `NO_TRADE_CATEGORY_BY_REASON`.

## 6. Regeneration impact inventory

**Measured ripple of the universal D-06 invariant alone** (pytest plugin wrapping `plan()` to return NO_TRADE when SL is not outside the zone; legacy swing semantics; the 25 test files that import core/backtest/paper) [VERIFIED: scratch run, inv_result.txt]: 72 failed, 1 error. Per file: `test_backtest_simulator` 30, `test_core_planner` 10, `test_phase6_fixture_geometry` 9 (one is the pre-existing CRLF failure, Flag F12), `test_backtest_experiment` 8, `test_backtest_determinism` 5, `test_backtest_engine_strategy` 4, `test_paper_parity` 3, `test_cost_parity` 3, `test_plan_hash_roundtrip_pg` 1 error (needs PostgreSQL). Not affected: `test_core_tracer`, `test_no_lookahead`, `test_prefix_invariance`, `test_candle_close_timing`, `test_backtest_chain`, `test_backtest_engine` (scripted plans), `test_minute_source`, `test_paper_closed_candle`, `test_paper_feed_gates`, `test_paper_resync`, `test_paper_reviewfix_pins`. A prior interrupted pass that also switched ALL sets to default pivots 3/3 [CITED: scratchpad proto2_full.txt, prior pass, not re-run] showed the same failure families plus 11 in `test_core_planner` and `test_prefix_invariance::test_stateful_variant...`; its non-test-logic failures (git/env tests) came from running outside a git checkout and should be ignored.

**Inventory to list once in D054 (D048/D053 style):**
- Generator and fixtures: `scripts/gen_phase6_fixtures.py` builds a smooth uptrend with BAR_HALF_RANGE 0.80 and a trigger bar 249 that "dips to touch the support zone"; a monotonic uptrend has no confirmed pivot low (lows increase, the minimum of every `[t-3, t+3]` window is its left end), so the generator needs a deliberate V-shaped dip before bar 249 and re-derived numbers. Outputs to regenerate: `tests/fixtures/phase6/` (7 simulator cases + `baselines/no_trade`, `baselines/simple_trend`, all `input.json`), `tests/fixtures/phase7/parity_overlapping_history/input.json` and its `expected.json`; they currently carry `baseline-v5` / `v4.0.0` (`test_fixture_carries_phase12_identity` asserts both) and move to the v6 / v5.0.0 identity.
- Pinned digests: `REGRESSION_SNAPSHOTS` in `tests/test_backtest_simulator.py:312`, the Phase 7 parity digest (`tests/test_paper_parity.py`), `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md`.
- Phase 4 artifacts: `tests/fixtures/phase4/expected_plans.json`, `expected_signals.json` (PG test only), produced by `scripts/_compute_phase4_fixtures.py` / `_regen_phase4_expectations.py`, which still import `compute_features` fields that are kept.
- Tests that must migrate from `baseline-v1..v5` Family A plans to hand-built pivot structures plus `baseline-v6`: `test_core_planner.py` (builds a last bar "patched to touch support"), `test_backtest_simulator.py`, `test_backtest_experiment.py`, `test_backtest_determinism.py`, `test_backtest_engine_strategy.py`, `test_cost_parity.py`, `test_paper_parity.py`, `test_phase6_fixture_geometry.py`, `test_plan_hash_roundtrip_pg.py`.
- Phase 14 fixtures (`tests/fixtures/phase14/*`) and Phase 5 fixtures use scripted/hand-built plans with the stop outside the zone and are unaffected [VERIFIED: phase5 `input.json` zones and stops checked].
- Pins and gates: `tests/fixtures/phase4/parameters.json` (append), `scripts/decision_alignment/params.py` (PA-08), `tests/test_decision_alignment_params.py` (`len(gate.load_pins()) == 20`, gate-name list), `tests/test_analytics_files.py:59-69`, `src/domain/registry.py` docs list in `docs/configuration/CONFIGURATION.md` section 3.
- Docs: three family sheets ("implemented as" line, status wording per D-12), `docs/GLOSSARY.md:181`, `docs/DECISIONS.md` row D054 (single-line table row; next id is 54 because 53 `| D0..` rows exist), `src/risk/gating.py:41-61` docstring that says a stop inside the zone is deliberately not rejected (stale after this phase; optionally strengthen `_plan_geometry_is_valid`).
- Defaults: `scripts/smoke_backtest_realdata.py:93` default `--parameter-set-id baseline-v5` becomes `baseline-v6`.
- Signal ids and fingerprints: Family A zone values change, so every Family A `signal_id` and `plan_hash` moves (the fingerprint binds `zone_upper`, `zone_lower`, `atr`, EMAs, `strategy.py:660-670`).
- strategy_version: nothing in `src/` hard-codes it; the engine requires the case's `strategy_version` to equal the registry's (`engine.py:855-860`), so v6 fixtures must carry `v5.0.0`.
- Family independence: `baseline-v6` counts as a candidate; baselines `-v4` are excluded by prefix; sheet hashes change (Flag F9).

## 7. Protocol and criterion 4 readiness

**Protocol bump:** none needed. v2.0.0 already says "No future swing confirmation leaks" (section 3), keeps strategy parameters as versioned registry values (section 0 numeric-gate status), and its migration paragraph states "the evidence-bearing strategy sets are the new versioned sets created in Phase 15" [VERIFIED: docs/research/RESEARCH_PROTOCOL.md §0, §3]. Record "no amendment required" in D054. New sets create a new lineage (strategy_id + strategy_version line); the holdout marker file is empty (`"entries": []`) so no lineage erosion yet; variant budget N = 25 per family counts evaluated combinations, not registered sets.

**What a re-run still needs (state this in D054 and the plan SUMMARY):** the frozen universe `research-universe-v1` (12 symbols, `status = "FROZEN"`, selection 2024-10-03) and the data (24 months of 1H/4H/1m, `missing_data false` in the sufficiency report) already exist; candidate registration is the existing registry plus pins; the pre-registered gates G1-G5, the 40/40/20 split and Holm correction are unchanged; trade-floor reachability is still unmeasured (the sufficiency report says it cannot be measured until the Phase 14 simulator runs; surface the shortfall, never lower the floor).

**Smoke:** `scripts/smoke_backtest_realdata.py` runs the engine twice on one symbol and compares digests (exit 0 / 1 digest mismatch / 2 usage / 3 failure). It needs `--constraints-json` (or a DB env), a closed UTC window, and a set id. A prior pass measured 311 s per run for 75 days of BTCUSDT on baseline-v5, 119 trades [CITED: scratchpad smoke_v5_75d.txt, prior pass]; use 30 days per family for readiness (about 2 minutes per run, two runs). Command shape:
```
.venv/Scripts/python scripts/smoke_backtest_realdata.py --symbol BTCUSDT --days 30 --end-day 2026-10-01 \
  --strategy-id trend-pullback --parameter-set-id baseline-v6 --constraints-json <file>
```
Repeat for `breakout-retest` and `range-mr` v6 sets (a Family C run will report zero setups unless Flag F1 is resolved; that is a finding, not a failure). A hand-written constraints file is acceptable for a smoke only; research runs must use the point-in-time constraint history. Define "zero invariant violations" as Flag F8 states.

## Common Pitfalls

### Pitfall 1: Pivot reported one bar early or computed from the evaluated bar
**What goes wrong:** off-by-one in `t + R <= i` lets bar `i` become the level or lets a pivot appear before `t+R` closes.
**How to avoid:** hand-derived micro example (Pattern 1), test at `i = t+R-1` (absent) and `i = t+R` (present), prefix-invariance property comparing frames from `candles[:i+1]` against the full-series value for every `i`.

### Pitfall 2: Treating "no pivot" as warm-up
**What goes wrong:** pivot validity folded into `features_valid` labels a quiet market as `WARMUP_INSUFFICIENT`, corrupting NO_TRADE reason counts in the experiment record.
**How to avoid:** pivots stay outside `features_valid`; strategy returns None.

### Pitfall 3: Rounding changes the invariant
**What goes wrong:** invariant checked on raw Decimals but plan stored after `quantize_for_storage`.
**How to avoid:** check after quantization (D-06). Note the risk layer later snaps the stop trigger to the tick (the Phase 6 generator docstring: stop 121.1529 becomes trigger 121.2); the planner has no tick, so a stop within one tick of the zone edge can cross it. Add a test with a stop one tick-scale outside the edge and consider strengthening `_plan_geometry_is_valid` to "stop outside the whole zone".

### Pitfall 4: Behavior change without a version gate
**What goes wrong:** B anchoring, direction gate or T-mid change legacy-set output under an unchanged `strategy_version`.
**How to avoid:** Flag F11; gate by optional key; test that a legacy set yields byte-identical signals before and after.

### Pitfall 5: Tests that bless the new code
**What goes wrong:** regenerating expectations from `src/` (what F-608 criticized).
**How to avoid:** hand-derived JSON with `DERIVATIONS.md`; the guard test must use independent literal arithmetic like `tests/test_phase6_fixture_geometry.py` does.

### Pitfall 6: Rationale metadata drifting from values
**What goes wrong:** a value changes (hash changes) but its rationale text still describes the old value.
**How to avoid:** the check also compares each rationale entry's recorded `value` string with the parsed parameter and fails on mismatch (add `value = "..."` to each table).

### Pitfall 7: Dead keys carried into new sets
`regime_filter_lookback` and `breakout_volume_threshold` are hashed but never read. Either omit them in v6 or mark them `INERT`; do not give them a "structural" rationale.

## Code Examples

### Pivot at the last bar (sketch; Decimal only, no float)
```python
# Source: derived from trend-pullback.md section 5 rows 1-3; Assumption A1 (tie rule), A2 (lookback bound)
def pivot_at(candles: list[Candle], i: int, *, lookback: int, left: int, right: int,
             high: bool) -> Decimal | None:
    lo = max(left, i - lookback + 1)
    for t in range(i - right, lo - 1, -1):          # t + right <= i: the window never passes bar i
        if high:
            ok = all(candles[t].high >= candles[j].high for j in range(t - left, t)) and \
                 all(candles[t].high > candles[j].high for j in range(t + 1, t + right + 1))
            if ok:
                return candles[t].high
        else:
            ok = all(candles[t].low <= candles[j].low for j in range(t - left, t)) and \
                 all(candles[t].low < candles[j].low for j in range(t + 1, t + right + 1))
            if ok:
                return candles[t].low
    return None
```

### Shared geometry validator (sketch)
```python
# Order is part of the contract; reasons are existing RejectionReason values.
def _geometry_rejection(*, direction: str, entry_min: Decimal, entry_max: Decimal,
                        entry_ref: Decimal, stop: Decimal, tp1: Decimal, atr: Decimal,
                        signal_low: Decimal, signal_high: Decimal,
                        min_stop_atr: Decimal | None) -> str | None:
    long = direction == "LONG"
    if (stop >= entry_min) if long else (stop <= entry_max):
        return RejectionReason.STOP_TOO_TIGHT.value            # D-06
    if (signal_low <= stop) if long else (signal_high >= stop):
        return RejectionReason.INVALIDATED.value               # D-07 (boundary counts as through)
    if min_stop_atr is not None and abs(_sub(entry_ref, stop)) < _mul(min_stop_atr, atr):
        return RejectionReason.STOP_TOO_TIGHT.value            # D-08
    leg = _sub(tp1, entry_ref) if long else _sub(entry_ref, tp1)
    if leg <= Decimal("0"):
        return RejectionReason.RR_TOO_LOW.value                # TP on the loss side (F6)
    return None
```

### Family A geometry change (D-05)
LONG: `zone_lower = P - half`, `zone_upper = P + half`; `entry_min = zone_lower - entry_buffer`; `stop = entry_min - sl_buffer`. SHORT: `entry_max = zone_upper + entry_buffer`; `stop = entry_max + sl_buffer`. TP1 = opposite confirmed pivot (planner calls `pivot_at` for the opposite side over `setup_candles`; missing pivot returns `STALE_SETUP`). Note `_long_geometry` currently gets `entry_buffer` only as a precomputed multiple inside `plan()`; pass `entry_buffer` into the geometry functions or compute the stop after `entry_min`.

### Smoke readiness and per-case sidecar layout
Sidecar `tests/fixtures/phase15/geometry_cases.json` holds candles (or a compact generator spec), expected zone, SL, TP1, RR, reason code, each with the derivation in `tests/fixtures/phase15/DERIVATIONS.md`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Trailing 20-bar extreme as support level (includes evaluated bar) | Confirmed fractal pivot excluding evaluated bar | Phase 15 | All Family A signal ids, fingerprints, plan hashes move |
| Stop at `swing_low - 0.2 ATR` inside a +/-0.6 ATR zone | Stop beyond the outer zone edge | Phase 15 | Stop distance from entry_ref 0.2 -> 0.8 ATR; adverse-edge distance 1.4 ATR |
| Phase 12 guards as only economic filter | Structural invariants (zone, ATR floor, TP side) before the guards | Phase 15 | Fewer degenerate plans reach risk layer |

**Deprecated/outdated:** `baseline-v1..v5`, `baseline-no-trade-v1..v3`, `baseline-simple-trend-v1..v3` for research (legacy geometry; kept byte-identical for hash reproduction, F-810).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pivot tie rule: non-strict on the left, strict on the right | Pattern 1 | Different tie handling changes which bar is the level in flat markets; record the rule in D054 and in the test fixtures |
| A2 | Lookback bound is `t in [i - swing_lookback + 1, i - R]` and `t - L` may reach before the lookback window | Pattern 1 | A narrower bound lowers signal counts; user ratifies `swing_lookback` anyway |
| A3 | Reusing `STOP_TOO_TIGHT` for "stop not outside zone" and `INVALIDATED` for "signal bar through stop" is acceptable to the user | Section 5 | If the user wants distinct codes, add the enum/GLOSSARY/test ripple listed in Section 5 |
| A4 | Pivot mode gated by presence of `pivot_left_bars` (legacy path retained) | Section 1 | Alternative policies change which tests break (Open Question 5) |
| A5 | `pin_stream_epoch` is the right place for the PLACEHOLDER refusal with a strict default | Section 3 | Phase 16 may prefer a different composition point; the pure `placeholder_keys` function is reusable either way |
| A6 | Feasibility counts (survival tables, Family A/B prototype counts) use float ATR14 and my own tie/lookback reading; indicative only | Section 4 | Counts could differ a few percent from the Decimal engine; none is used to choose a value (D-17) |
| A7 | Prior-pass artifacts in the scratchpad (smoke runtime, proto2 failure list) are accurate | Sections 6, 7 | Re-run before quoting in D054 |
| A8 | `min_stop_atr` upper bound 10 and pivot width upper bound are PROPOSED range limits | Section 3 | Too tight a bound blocks a later research sweep; widen via a new key release, not by editing sets |
| A9 | One `[rationale]` table per set file is acceptable to the user as the machine-checkable record | Section 3 | The alternative (docs sidecar) is documented and equally safe |

## Open Questions

1. **Family B stop (user checkpoint).** Keep the code stop (0.3 ATR adverse distance; 6.5 percent of bars survive the guards in the frozen universe, 0 percent for BTC) or align to S3 on the sheet's narrow S/R zone (1.3 ATR adverse distance, RR about 4.5, 88 percent survive in the universe, 75 percent in live-5, but a measured-move TP that deviates from T1)?
   - What we know: arithmetic in Section 4; CONTEXT's RR < 1 holds only for the far end of the whole range.
   - Recommendation: show both; do not choose by survival count (D-17).
2. **Family C regime gate (user checkpoint).** Record "Stage C skipped: range regime unsatisfiable under the EMA50 proxy" per sheet 7.1, or implement R1 (HH/HL, LH/LL on confirmed 4H pivots, reusing `pivot_at`) as the shared Stage regime for all three families, or an ATR band around EMA50 (new key, no empirical basis, would be PLACEHOLDER)?
   - What's unclear: effort and whether the user wants R1 for A/B too (it would change F10 for all three).
3. **B anchoring and direction gate.** Implement both (recommended; sheet-conformant, no leakage) with a version gate, or record as deviations?
4. **Numbers to ratify.** `pivot_left_bars`/`pivot_right_bars` 3/3 (confirmation lag 3 hours), `min_stop_atr` 0.5, `swing_lookback`, `zone_tolerance_atr`, `entry_buffer_atr`, `sl_buffer_atr`, `minimum_rr`, `signal_expiry_hours` (a structural candidate: 4 hours equals one 4H regime-bar duration). Present each with the PLACEHOLDER/STRUCTURAL/COST_GUARD basis and the worked numbers at equity 500 and 1,000.
5. **Gating mechanism for behavior changes in legacy sets.** Per-feature optional keys (`pivot_*`, `tp_mode`, ...) or one optional `geometry_version` integer (absent = legacy)? Recommendation: per-feature keys for A and C (already implied by D-02/D-10); one `geometry_version` only if B's anchoring/direction gate are approved, to avoid a key per fix.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | everything | yes | 3.13.15 | - |
| pytest / ruff / mypy | validation | yes | 9.1.1 / 0.16.8 / 2.3.1 | - |
| Local Parquet store `data/raw` (1h, 4h, 1m, mark, funding) | smoke, feasibility | yes | 19 symbols; BTCUSDT has 730 daily partitions for 1h and 4h (some symbols are shorter, for example REEFUSDT 2,673 hourly bars) | - |
| Constraint history for the smoke | smoke (D-17 fail closed) | hand-written JSON works; DB optional | - | `--constraints-json` |
| PostgreSQL / Docker | `test_plan_hash_roundtrip_pg` and other PG tests | not needed for this phase; those tests error or skip locally | - | accept error, record in D054 |
| Network | none | not needed | - | - |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (asyncio auto mode), `addopts = "-q"` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`; ruff `line-length = 100`; mypy strict |
| Quick run command | `.venv/Scripts/python -m pytest tests/test_core_features.py tests/test_core_planner.py tests/test_core_strategy_breakout_retest.py tests/test_core_strategy_range_mr.py tests/test_core_tracer.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_registry.py tests/test_registry_gate.py tests/test_decision_alignment_params.py tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py -q -p no:cacheprovider` (measured 65 s, 297 tests, green before changes) |
| Full suite command | `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider` (backtest/paper subset alone took 5 min 44 s) |
| Static gates | `.venv/Scripts/python -m ruff check src tests scripts`, `.venv/Scripts/python -m ruff format --check src tests scripts`, `.venv/Scripts/python -m mypy src` (mypy 6 s, green) |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STRAT-01 | pivot confirmed exactly at `t+R`, not before; level excludes evaluated bar | unit, hand-derived | `pytest tests/test_core_pivots.py -q -p no:cacheprovider` | Wave 0 |
| STRAT-01 | pivot prefix-invariance (value at `i` from `candles[:i+1]` equals full-series value) | property | same file | Wave 0 |
| STRAT-01 | no pivot in lookback -> `NO_TRADE_REGIME`; warm-up | unit | `pytest tests/test_core_strategy_geometry.py -q -p no:cacheprovider` | Wave 0 |
| STRAT-02 | Family A LONG and SHORT worked examples with signal id determinism | unit + sidecar | `pytest tests/test_planner_geometry.py -q -p no:cacheprovider` | Wave 0 |
| STRAT-02 | p9 regression: new low beyond tolerance gives no signal; within tolerance gives plan with SL below the bar low | unit | same | Wave 0 |
| STRAT-02 | shared invariant over a grid of ATR, tolerance, buffers for all three families (synthetic `ParameterSet`s) | property | `pytest tests/test_geometry_property.py -q -p no:cacheprovider` | Wave 0 |
| STRAT-02 | signal bar through stop -> `INVALIDATED` (B and C cases); stop below `min_stop_atr` -> `STOP_TOO_TIGHT`; TP on loss side -> `RR_TOO_LOW` | unit | `tests/test_planner_geometry.py` | Wave 0 |
| STRAT-01 | B and C leakage: appending an extreme evaluated bar leaves the reference level unchanged; B anchoring regression | unit | `tests/test_core_strategy_breakout_retest.py`, `tests/test_core_strategy_range_mr.py` extended | exists (extend) |
| F-909 | registry keys load, ranges, cross-key rule, hash neutrality for old sets | unit | `tests/test_registry.py` extended | exists (extend) |
| F-909 | every key in each v6 set has a rationale, `value` text matches, PLACEHOLDER detected, hash unchanged by the table | unit | `pytest tests/test_rationale.py -q -p no:cacheprovider` | Wave 0 |
| F-909 | `pin_stream_epoch` refuses PLACEHOLDER and missing rationale | unit | `tests/test_paper_freeze.py` extended | exists (extend) |
| F-113 | PA-08 gate: v6 sets pinned, version `v5.0.0`, headers say Supersedes; candidate ids list | unit | `tests/test_decision_alignment_params.py`, `tests/test_analytics_files.py` | exists (extend) |
| criterion 4 | smoke on v6 sets exits 0, digests equal | manual/slow | smoke command in Section 7 | script exists; default id to change |

### Sampling Rate
- **Per task commit:** the quick run command plus the new test file(s) of the task (target under 90 s).
- **Per wave merge:** quick run plus `tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_determinism.py tests/test_backtest_engine_strategy.py tests/test_paper_parity.py tests/test_cost_parity.py tests/test_phase6_fixture_geometry.py` (about 6 min), ruff and mypy.
- **Phase gate:** full suite green except the documented local environment items (CRLF generator test until fixed, PG-dependent tests), ruff, mypy, three smoke runs.

### Wave 0 Gaps
- [ ] `tests/test_core_pivots.py`, `tests/test_core_strategy_geometry.py`, `tests/test_planner_geometry.py`, `tests/test_geometry_property.py`, `tests/test_rationale.py`
- [ ] `tests/fixtures/phase15/geometry_cases.json` and `DERIVATIONS.md` (hand-derived, independent arithmetic)
- [ ] `src/core/pivots.py`, `src/domain/rationale.py` added to `tests/test_domain_no_float.py` `SCANNED_FILES`
- [ ] line-ending fix for the Phase 6 generator comparison (Flag F12) before regeneration

## Security Domain

### Applicable ASVS Categories (level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | no auth surface in this phase |
| V3 Session Management | no | - |
| V4 Access Control | no | - |
| V5 Input Validation | yes | registry validators: type, finite, range, cross-key, closed value sets; fail closed (`StrategyKeyOutsideRegistry`) |
| V6 Cryptography | no new use | existing `sha256_hex` canonical hashing only; never hand-roll |
| V14 Configuration | yes | hash-pinned sets (PA-01/PA-02/PA-03, registry-gate workflow); rationale table is hash-neutral metadata bound to the set by a recorded `value` per key |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent parameter change (value edited, hash same because only comments/metadata changed) | Tampering | rationale check compares recorded value with parsed value; PA-02 byte lock for old sets; pins for new |
| Unit or NaN values in new numeric keys | Tampering | `_check_value_range` finite + range; bool rejected |
| Plan with stop inside zone reaching approval | Tampering / Elevation of risk | shared planner validator plus risk-layer geometry check |
| PLACEHOLDER set pinned for paper | Repudiation (unjustified evidence) | `pin_stream_epoch` refusal |
| Strategy key smuggled through env config | Tampering | `check_strategy_key_outside_registry` covers new keys automatically |

## Sources

### Primary (HIGH confidence)
- Repository files read this session with line citations above: `src/core/planner.py`, `src/core/features.py`, `src/core/strategy.py`, `src/core/types.py`, `src/domain/registry.py`, `src/domain/enums.py`, `src/risk/cost_guards.py`, `src/risk/cost_rates.py`, `src/risk/gating.py`, `src/paper/freeze.py`, `src/backtest/engine.py`, `src/backtest/records.py`, `src/analytics/family.py`, `src/analytics/no_trade.py`, `src/adapters/analytics_files.py`, `scripts/decision_alignment/params.py`, `scripts/gen_phase6_fixtures.py`, `scripts/smoke_backtest_realdata.py`, `params/*/baseline-v5.toml`, `docs/research/families/*.md`, `docs/research/RESEARCH_PROTOCOL.md`, `docs/research/TRADING_STRATEGY_RESEARCH.md` section 6, `docs/GLOSSARY.md` section 9, `docs/DECISIONS.md`, audit `findings.json` (F-301, F-113, F-909), `DEEP_AUDIT_REPORT.md` section 6.4.
- Tool runs this session: pytest subset (baseline and with invariant plugin), mypy, ruff, scratch scripts `atr_stats.py`, `grid.py`, `famA_proto.py`, `famBC_real.py`, `famB_anch.py`, `neutral_count.py`, `geom_numbers.py`, `rationale_neutral.py` in the session scratchpad (data: local `data/raw` 1h/4h Parquet, 2024-10-03 to 2026-10-02).

### Secondary (MEDIUM confidence)
- Prior interrupted pass artifacts in the same scratchpad (`proto2_full.txt`, `smoke_v5_75d*.txt`, `patch_proto.py`), read but not re-run.

### Tertiary (LOW confidence)
- None; no web search was needed (no network use).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH (no new packages)
- Architecture: HIGH for code paths and ripple; MEDIUM for recommended gating/rationale/PLACEHOLDER placement (discretion areas)
- Pitfalls: HIGH for items verified by run or read; MEDIUM for tick-snap interaction (not tested)
- Feasibility numbers: MEDIUM (float prototypes, indicative)

**Research date:** 2026-10-06
**Valid until:** 2026-11-05 for code facts (repo moves fast; re-check line numbers after any merge touching `src/core` or `src/domain/registry.py`); the survival tables are valid for the local data snapshot only.
