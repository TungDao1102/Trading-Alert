# Phase 15 geometry audit: family sheets versus code

**Status:** final (plan 15-15). The table was written before any Phase 15 geometry change (plan 15-01, wave 1) and finished after the parameter ratification of plan 15-08: every cell is resolved, no PARAMETER verdict remains, and each FIX row names the implementing function.
**Scope:** the three family sheets under `docs/research/families/` (A trend-pullback, B breakout-retest, C range-mr), their Stage baseline rows, and the code that implements them.

## Purpose

CONTEXT decision D-10 requires a geometry audit table before any geometry code changes in Phase 15. ROADMAP criterion 2 (audit finding F-113) requires that every implemented geometry matches its sheet's Stage baseline, or that a DECISIONS entry records the deviation. This document is the input for the DECISIONS entry D054 (plan 15-15) and for the "implemented as" lines of the family sheets (plan 15-14). A machine check lives in `tests/test_geometry_audit_doc.py`.

Where D-22 to D-27 (the user decisions after research) conflict with D-10 or D-11, D-22 to D-27 win. The rows below already use the later decisions.

None of the figures here is a tuning input. Survival and arithmetic figures are consequences of a stated reading of a sheet cell; no value is chosen or adjusted from them (D-17).

## Verdict vocabulary

- **MATCH**: the code equals the sheet Stage baseline for this cell.
- **FIX**: Phase 15 changes the code to the sheet; the Decision column names the deciding decision.
- **DEVIATION**: the code keeps a different rule from the sheet; the reason is recorded in D054.
- **PARAMETER**: the cell is decided by a registry value that is ratified in the plan 15-08 checkpoint; plan 15-15 converted every such row to MATCH or DEVIATION, so the final table holds none (the word stays in this vocabulary list only).

## Audit table

Line numbers refer to the code before Phase 15 (`src/core/strategy.py`, `src/core/planner.py`, `src/core/features.py`).

| Family | Cell | Sheet Stage baseline | Code before Phase 15 | Phase 15 resolution | Verdict | Decision |
|---|---|---|---|---|---|---|
| A | regime | R1 structure-only 4H regime (trend-pullback.md section 2.1) | EMA50(4H) close compare in `_resolve_regime` (strategy.py:98-120); its own comment calls it an R2-style proxy | Keep the EMA50 proxy for Families A and B and record the deviation from R1 in D054 | DEVIATION | D-22, D054 |
| A | pullback | P1 zone touch: bar low inside the zone (section 2.2) | `support_lower <= low <= support_upper` in `_detect_setup` (strategy.py:157) | Predicate unchanged; the level it is measured against changes (see level) | MATCH | n/a |
| A | level | Confirmed pivots only (section 5 rows 1-3): a pivot is known at the close of bar t+R | Trailing 20-bar extreme that includes the evaluated bar: window `candles[i-lookback+1 : i+1]` in `_swing_series` (features.py:187) | Most recent confirmed pivot inside `swing_lookback`; evaluated bar never part of it; no pivot means NO_TRADE; prefix-invariance tested Implemented in `pivot_at` (src/core/pivots.py) and `_detect_pivot_setup` (src/core/strategy.py). | FIX | D-01, D-02, D-03, D-04 |
| A | zone | Zones with merge, collide and separate semantics and `zone_min_touches` (section 5.1) | A single level plus or minus `zone_tolerance_atr` x ATR (planner.py:109-118) | Single pivot zone kept; the merge/collide/separate rules stay a research variant and the deviation is recorded | DEVIATION | D-05, D054 |
| A | entry | E2 zone plus or minus an ATR buffer | Zone plus or minus `entry_buffer_atr` x ATR, entry reference at the zone midpoint (planner.py:382-389) | Unchanged | MATCH | n/a |
| A | stop | S2 structure minus k ATR | `swing_low - sl_buffer`, which sits inside the entry zone (planner.py:116 against the zone edge at planner.py:382) | Stop beyond the outer edge of the whole entry zone: LONG `entry_min - sl_buffer_atr` x ATR, SHORT `entry_max + sl_buffer_atr` x ATR. Measuring the buffer from the outer zone edge (not from the pivot) is a recorded reading of S2. Shared invariant: SL strictly outside the zone after quantization, and a minimum stop distance in ATR Implemented in `_pivot_geometry` and checked by `_geometry_rejection` (src/core/planner.py). | FIX | D-05, D-06, D-08 |
| A | target | T1 fixed R multiple | TP1 is the opposing swing, TP2 is entry plus or minus 2 x the TP1 leg (planner.py:109-118, 402) | Keep the structure target (opposite confirmed pivot) and TP2 = entry +/- 2 x (TP1 - entry). A target built from `minimum_rr` would make the RR gate vacuous (CR-03); the gate stays an acceptance threshold only | DEVIATION | D-09, D-14, D054 |
| B | regime | R1 structure-only 4H regime (breakout-retest.md section 2.3 and Q1 pointer) | EMA50(4H) close compare in `_resolve_regime` (strategy.py:98-120) | Keep the EMA50 proxy for Families A and B and record the deviation from R1 in D054 | DEVIATION | D-22, D054 |
| B | direction | Section 2.4: the breakout direction must agree with the 4H regime (with-direction only) | Any non-NEUTRAL regime is admitted; the direction comes from the breakout side, so counter-trend breakouts signal (strategy.py:583) | Trade only with-direction: the breakout direction must equal the regime direction. Behind the optional `geometry_version` key, absent means legacy Implemented in `_detect_breakout_retest_levels` (src/core/strategy.py). | FIX | D-24, D-25 |
| B | breakout | B1 single close outside the zone (section 2.1) | `breakout_confirmation_bars = 3` in the legacy sets (strategy.py:236, 257-262); this matches no sheet row, because B4 is two consecutive closes | Ratified at the plan 15-08 checkpoint (user reply `ratify`): `breakout_confirmation_bars` = 1 (basis STRUCTURAL, sheet B1) in breakout-retest baseline-v6. The legacy implementation value 3 is written in no new set, so no deviation is recorded for it. | MATCH | D-16, D-17 |
| B | retest | R1 touch: the bar low is inside the broken zone (section 2.2) | A band of `retest_depth_atr` x ATR around the outer edge `zone_upper` in `_find_retest_bar` (strategy.py:327-356) | Band rule kept; the deviation from R1 is recorded | DEVIATION | D-14, D054 |
| B | anchoring | The retest is confirmed at the close of the retest bar (the sheet look-ahead table) | Any breakout plus retest anywhere in the 1000-bar window signals (strategy.py:257 scans the whole history, the retest search starts at i + 1 on line 293 with no end condition); retest bar median age 37 bars on real data | The first retest after the breakout must be the evaluated bar n-1; an older retest produces no signal. Behind `geometry_version` Implemented in `_detect_breakout_retest_levels` and `_find_retest_bar` (src/core/strategy.py). | FIX | D-24, D-25 |
| B | entry | E2 zone plus or minus an ATR buffer | Degenerate zone at the broken edge plus or minus `entry_buffer_atr` x ATR (planner.py:119-136) | Unchanged | MATCH | n/a |
| B | stop | S3 zone invalidation: the other side of the broken support/resistance zone (Q6) | `zone_upper - sl_buffer` for LONG, `zone_lower + sl_buffer` for SHORT (planner.py:131-136, 180-185), so the stop is 0.2 ATR under the retest edge | Stop beyond the far edge of the narrow S/R zone (swing plus or minus `zone_tolerance_atr` x ATR), then `sl_buffer_atr` x ATR. The D-10 bullet "keep the code stop" is superseded by D-23. Decision basis as D-23 records it: the sheet text alone (breakout-retest.md section 2.2 zone bounds, Q6, section 6 parameter rows). Behind `geometry_version` Implemented in `_breakout_retest_geometry` (src/core/planner.py) from the `sr_far_edge` of `_detect_breakout_retest_levels`. | FIX | D-23, D-25 |
| B | target | T1 fixed R multiple | Measured move: edge plus or minus the range height (planner.py:135, 184) | Measured move kept; a target built from `minimum_rr` would make the RR gate vacuous (CR-03). Recorded as a deviation from T1 | DEVIATION | D-23, D-10, D-14, D054 |
| C | regime | R1 range detection with the regime filter ON (range-mr.md section 3, row 133 binding rule 2) | NEUTRAL only on exact equality of the 4H close and EMA50 (strategy.py:116-120, gate at strategy.py:592): 0 of 4,380 4H bars per symbol, so Family C can never signal | NEUTRAL means neither HH+HL nor LH+LL on confirmed 4H pivots inside `regime_filter_lookback` 4H bars (the D-01 pivot function on the context stream, closed bars only). Behind `geometry_version` Implemented in `_resolve_regime_pivots` (src/core/strategy.py). | FIX | D-22, D-25 |
| C | range | Merged zones, and every closed 4H bar over `regime_filter_lookback` agrees on range (row 133 rule 2) | A 20-bar swing at bar n-2 with touches counted before it (strategy.py:400-437); `regime_filter_lookback` is read nowhere | Range construction kept. Phase 15 reads `regime_filter_lookback` as the pivot window of the regime verdict at the last closed 4H bar. The remaining difference is recorded | DEVIATION | D-14, D054 |
| C | entry | E2 zone plus or minus an ATR buffer | Range edge plus or minus `entry_buffer_atr` x ATR, degenerate zone (planner.py:137-147) | Unchanged | MATCH | n/a |
| C | stop | S3 zone invalidation outside the range edge | `zone_lower - sl_buffer`, about 0.2 ATR from the entry reference (planner.py:145, 194) | Stop beyond the far edge of the narrow S/R zone around the range edge, then `sl_buffer_atr` x ATR; must satisfy the shared stop invariant Implemented in `_range_mr_geometry` (src/core/planner.py) from the `sr_far_edge` of `_detect_range_mr_levels`. | FIX | D-22, D-23 |
| C | target | T-mid: take profit at the range midpoint (Stage C baseline) | The opposite boundary (`zone_upper` for LONG, `zone_lower` for SHORT), which is the sheet's T-opposite variant (planner.py:146, 195) | Optional key `tp_mode` with T_MID for the Stage C set; T_OPPOSITE stays as the named variant that needs its own parameter set later Implemented in `_range_mr_geometry` (src/core/planner.py), `tp_mode` T_MID. | FIX | D-10, D-25 |

## Leakage verdicts (D-13)

Question: does any detector let the evaluated bar (the last closed bar n-1) feed the reference level that it is then compared with? Family A leaks (see the `level` row, features.py:187). Families B and C do not.

**Family B: no leakage of the evaluated bar.** The scan loop starts at `i = n - 1` (strategy.py:257) and sets `ref_bar = i - breakout_confirmation_bars` and `ref_prev = ref_bar - 1` (strategy.py:258-259), so `ref_prev = i - breakout_confirmation_bars - 1`. The level `swing_high_series[ref_prev]` and the ATR `atr_series[ref_prev]` (strategy.py:262, WR-12) cover only bars up to `ref_prev`. The retest search starts at `i + 1` (strategy.py:293). The evaluated bar is `n - 1 >= i + 1 > ref_prev`, so neither the evaluated bar nor any breakout bar enters the level or the ATR. The existing test for the reference-bar offset is in `tests/test_core_strategy_breakout_retest.py`. Family B is not anchored to the evaluated bar; that defect is the `anchoring` row, not a leak.

**Family C: no leakage of the evaluated bar.** `ref_idx = last_idx - 1` (strategy.py:401); the level and ATR come from `swing_high_series[ref_idx]`, `swing_low_series[ref_idx]` and `atr_series[ref_idx]` (strategy.py:402-404). The window covers bars `ref_idx - 19` to `ref_idx = n - 2`, so the evaluated bar `n - 1` is excluded from the level and the ATR. Touches are scanned in `range(swing_lookback, ref_idx - swing_lookback + 1)` (strategy.py:433), strictly before the bars that define the level. Caveat recorded, not fixed here: the level can be set by bar n-2, an extreme that is only one bar old and not pivot-confirmed. That is a design choice of the detector, not a leak.

**Consequence (D-04).** Because both detectors pass, the trailing-window helper `_swing_series` stays for Families B and C. Plan 15-05 and plan 15-06 add one test per detector that appends an extreme bar and shows the returned zone is unchanged by it.

## Universal planner invariants

These apply to all families, are checked after quantization to storage scale, and live in one shared function in the planner. They are fixed in this order, invariants before the RR gate (D-26):

| Order | Invariant | Decision | Reason code |
|---|---|---|---|
| 1 | SL strictly outside the whole entry zone: LONG `SL < entry_min`, SHORT `SL > entry_max` | D-06 | STOP_TOO_TIGHT |
| 2 | The signal bar has not already traded through the stop (LONG low at or below SL, SHORT high at or above SL gives INVALIDATED) | D-07 | INVALIDATED |
| 3 | `abs(entry_ref - SL) >= min_stop_atr` x ATR, when the key is present | D-08 | STOP_TOO_TIGHT |
| 4 | TP1 on the profit side of the entry reference (the RR gate uses `abs()` today, planner.py:409, so a loss-side TP1 passes it) | F6, D-27 | RR_TOO_LOW |
| 5 | The RR gate itself (unchanged, an acceptance threshold only) | D-09 | RR_TOO_LOW |

No new `RejectionReason` member is added (D-27); the three codes already exist.

## Research flags and their disposition

Every research flag F1 to F12 (15-RESEARCH.md) has a disposition and an owning plan, so none is dropped silently.

| Flag | Finding | Disposition | Plan |
|---|---|---|---|
| F1 | Family C regime is unsatisfiable: NEUTRAL needs the 4H close to equal EMA50 exactly (0 of 4,380 4H bars per symbol) | Sheet-conformant range regime on confirmed 4H pivots (D-22) | 15-06 |
| F2 | Family B is not anchored: any breakout plus retest in the 1000-bar window signals (retest bar median age 37 bars) | Retest bar must be the evaluated bar n-1 (D-24), behind `geometry_version` | 15-05 |
| F3 | The D-10 "RR below 1" claim holds only for S3 read as the far end of the whole range | S3 on the narrow S/R zone (D-23); the D-10 Family B bullet is superseded | 15-05 |
| F4 | D-07 is vacuous for Family A under the D-05 geometry and bites only B and C | D-07 kept as defense in depth; tested on B and C, and on the legacy sets | 15-05, 15-06, 15-13 |
| F5 | The acceptance anchor "S=60,000, ATR=400 produces no plan" is wrong: the same inputs yield a corrected plan | Acceptance reworded to "no plan with SL inside the zone" (D-27) | 15-04 |
| F6 | The RR gate uses `abs()`, so a TP1 on the loss side passes it | Profit-side check added to the shared validator | 15-04 |
| F7 | The degenerate baselines (simple-trend, no-trade) run the Family A path and break under the invariant | Re-issued as `-v4` baselines; invariants checked before RR and the no-trade assertion updated (D-26) | 15-09, 15-10 |
| F8 | No measure exists for "zero invariant violations": trade records carry no stop or zone fields | Defined through the geometry census and the readiness check | 15-07, 15-15 |
| F9 | Editing the sheets changes `sheet_sha256`, which D030 independence uses | Sheets are edited before any CANDIDATE experiment is recorded | 15-14 |
| F10 | Sheet deviations beyond D-10: regime proxy, B1 versus 3 confirmation bars, retest band, with-direction rule, zone semantics, unread keys | One audit row per cell (this document) and the deviations recorded in D054 | 15-01, 15-15 |
| F11 | B and C behavior changes under an unchanged `strategy_version` break the Phase 12 versioning rule | Optional integer `geometry_version` key, absent means legacy (D-25) | 15-03 |
| F12 | The Phase 6 fixture comparison already fails on a CRLF working tree | Line endings normalized in the comparison; not a Phase 15 regression | 15-10 |

## Arithmetic

Worked numbers for Family A, from RESEARCH section 4 (Decimal arithmetic; BTCUSDT-style inputs, zone tolerance 0.5 ATR, entry buffer 0.1 ATR, stop buffer 0.2 ATR, minimum RR 2.0; quantity floored to step 0.001; risk budget 0.5 percent of equity).

**Old plan (swing S = 60,000, ATR = 400).** Support zone 59,800 to 60,200, entry zone (widened by the 0.1 ATR entry buffer) 59,760 to 60,240. Stop 59,920 sits inside the entry zone. Risk from the zone midpoint is 80 (0.133 percent of price), reported RR 25, adverse distance 320 (0.53 percent), cost-to-risk 0.2081 so the Phase 12 guard rejects it as COST_TO_RISK_EXCEEDED. The geometry itself is the defect: a stop inside the entry zone can be hit by a fill that the plan counts as valid.

**New LONG (pivot P = 60,000, ATR = 400).**

| Item | Value |
|---|---|
| Entry zone | 59,760 to 60,240 (pivot plus or minus 0.5 ATR tolerance plus 0.1 ATR entry buffer; the support zone alone is 59,800 to 60,200) |
| Entry reference (zone midpoint) | 60,000 |
| Stop loss | 59,680 (entry_min 59,760 minus 0.2 ATR = 80) |
| TP1 | 61,600 |
| RR to the reference | 5.00 |
| Adverse distance (adverse edge to stop) | 560 = 0.930 percent of price |
| Cost-to-risk | 0.1303 (passes both Phase 12 guards) |
| Equity 500 | quantity 0.003, notional 180, realized risk 1.932 (77.3 percent of the budget) |
| Equity 1000 | quantity 0.007, notional 420, realized risk 4.507 (90.1 percent of the budget) |

The SHORT mirror (stop 60,320) gives the same RR, adverse distance 560 (0.937 percent), cost-to-risk 0.1306, and realized risk 1.932 at equity 500 and 4.509 at equity 1000.

**Acceptance wording (D-27, research flag F5).** With the corrected geometry the same inputs produce a corrected plan, not a rejection. The acceptance test is therefore "no plan with SL inside the zone" (and no plan with the old stop at 80), not "no plan".

**Families B and C arithmetic (research section 4).** These rows are arithmetic consequences of a stated reading of each sheet cell. They are not the basis of D-23; its basis is the sheet text alone. ATR is the 1H ATR; costs are the Phase 12 rates (guards use the adverse zone edge).

| Case | Zone, reference, SL, TP1 | RR to the reference | Adverse distance | Cost-to-risk | Phase 12 guards |
|---|---|---|---|---|---|
| B code today (swing high 60,600, range low 59,000, ATR 360) | zone_upper 60,780, height 1,960; entry 60,744 to 60,816, reference 60,780, SL 60,708, TP1 62,740 | 27.2 | 108 (0.178 percent) | 0.4406 | STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED |
| B, S3 read as the far end of the whole range | SL = 58,820 - 72 = 58,748 | 0.96 = height / (height + buffer), below 1 | 2,068 (3.4 percent) | 0.0388 | pass the guards, fail RR_TOO_LOW at equity 500 and 1000 |
| B, S3 on the narrow S/R zone (D-23 reading) | SL = (60,780 - 360) - 72 = 60,348, TP1 62,740 | 4.54 (about 4.5) | 468 (0.770 percent) | 0.1534 | COST_TO_RISK_EXCEEDED at this ATR; passes when ATR/price is about 0.61 percent or more |
| C code today (range 59,000 to 61,000, ATR 400) | entry 58,960 to 59,040, reference 59,000, SL 58,920; T-opposite 61,000, T-mid 60,000 | 25.0 (T-opposite), 12.5 (T-mid) | 120 (0.203 percent) | 0.4076 | STOP_TOO_TIGHT |
| C, stop beyond the 0.5 ATR tolerance zone (D-23 reading) | SL 58,720 (0.5 + 0.2 ATR below the edge), T-mid 60,000 | 3.57 | 320 (0.542 percent) | 0.2048 | COST_TO_RISK_EXCEEDED at this ATR |

Reading of the table: under the whole-range reading Family B can never reach `minimum_rr`; under the narrow-zone reading the RR is about 4.5. For Family C the midpoint target cuts the RR from 25.0 to 12.5 on the old geometry and gives 3.57 on the corrected stop. None of these figures chooses a parameter.

## Re-run readiness (criterion 4)

ROADMAP criterion 4 asks that a research re-run under protocol v2.0.0 is ready to start; the re-run itself is not part of Phase 15. Readiness is verified here by running the three `baseline-v6` sets (plan 15-08) on the Phase-14 engine, not asserted.

**F8 definition of "zero invariant violations" (research flag F8).** A set is ready when all of the following hold: (1) `scripts/smoke_backtest_realdata.py` runs the Phase-14 `simulator.run` twice on the same real-data window, exits 0 and prints `digests_match=true` (two equal sha256 digests); (2) every key of the printed `no_trade_counts` is a canonical `RejectionReason` value, a feature-layer code (`WARMUP_INSUFFICIENT`, `GAP_IN_SOURCE`, `INVALID_INPUT`) or the engine's one documented counter `CONFLICT_WITH_OPEN_POSITION` (D-32, `semantics.NO_TRADE_CONFLICT`, deliberately not a `RejectionReason`), checked programmatically against the enum; (3) `scripts/geometry_census.py` on the same set reports `invariant_violations 0` (its checker compares stored plan fields with literal comparisons and does not import the planner validator); (4) the property test over the parameter grid (plans 15-07 and 15-13, `tests/test_geometry_property.py`) is green.

**Inputs.** Local published store `data/raw` (1h, 4h, 1m trade, 1m mark and funding partitions), symbol BTCUSDT, 30 closed UTC days ending 2026-10-01 (2026-09-02 to 2026-10-01). Constraint history: the one-row BTCUSDT export recorded in `14-14-SUMMARY.md` (tick 0.10, step 0.001, min_qty 0.001, min_notional 50, observed 2026-10-05T08:18:37+00:00), written to a JSON file outside the repository; the database was not touched. Equity 1000 and risk rate 0.005 (the script defaults). The constraint row is observed after the window start, so the engine back-extrapolates it (D-30): the run is valid as a plumbing and invariant check, NOT as strategy evaluation.

**These counts are plumbing and invariant evidence only.** Trade and NO_TRADE counts are never strategy performance, and no parameter was or will be changed because of them (D-17).

Smoke command (per family): `.venv/Scripts/python scripts/smoke_backtest_realdata.py --symbol BTCUSDT --days 30 --end-day 2026-10-01 --strategy-id <family> --parameter-set-id baseline-v6 --constraints-json <scratch file>`. Census command (per family): `.venv/Scripts/python scripts/geometry_census.py --strategy-id <family> --parameter-set-id baseline-v6 --symbols BTCUSDT --days 30 --end-day 2026-10-01` (the census reads 50 extra warm-up days before the window so every evaluated bar sees full strategy and context windows).

| Family | Set | Smoke window | Smoke runtime run 1 / run 2 (s) | Smoke digest (both runs equal) | trade_count | no_trade_counts | Census (BTCUSDT) |
|---|---|---|---|---|---|---|---|
| trend-pullback | baseline-v6 | 30 days to 2026-10-01 | 123.118 / 78.919 | 52ae9d503a3ab28f5da96e765ee13550c67d7794c30ded9e2f09dd7a1badb5c3 | 0 | {"NO_TRADE_REGIME":3,"WARMUP_INSUFFICIENT":717} | setups 148, plans 123, planner RR_TOO_LOW 24 and STALE_SETUP 1, guard COST_TO_RISK_EXCEEDED 68 and STOP_TOO_TIGHT 1, guard pass 54, invariant_violations 0 |
| breakout-retest | baseline-v6 | 30 days to 2026-10-01 | 112.442 / 71.883 | cc5629fd6d2e6488206aa7345b1da46bf0e878fe683aa09756f49d3e297f0aef | 0 | {"NO_TRADE_REGIME":3,"WARMUP_INSUFFICIENT":717} | setups 20, plans 20, planner none, guard COST_TO_RISK_EXCEEDED 16 and STOP_TOO_TIGHT 1, guard pass 3, invariant_violations 0 |
| range-mr | baseline-v6 | 30 days to 2026-10-01 | 113.386 / 71.873 | dea333ac3e3f0e9fb167e0ae4e9975cdfd5828a93939ddd9fed98e9e8fb04cde | 0 | {"NO_TRADE_REGIME":3,"WARMUP_INSUFFICIENT":717} | setups 19, plans 14, planner RR_TOO_LOW 5, guard COST_TO_RISK_EXCEEDED 12 and STOP_TOO_TIGHT 2, guard pass 0, invariant_violations 0 |

For every family both smoke runs exited 0 with `digests_match=true` and the same `dataset_id` 3ba0132e1e3449dae18cea11d0e55cd35e3baac79ae854bad2233c839fb737e1 (the three digests differ because the set parameters differ, and each digest is equal across its two runs). Every key of `no_trade_counts` is canonical (`NO_TRADE_REGIME` is a `RejectionReason` value, `WARMUP_INSUFFICIENT` a feature-layer code). Each census total line reports `invariant_violations: 0`, `guard_other: {}` and `violation_kinds: {}`; the census parameter_set_hash values equal the pins (trend-pullback 2c4f1528..., breakout-retest 289d47ac..., range-mr c9023e47...) and its BTCUSDT counts equal the 15-08 post-ratification census rows. Census counts are information about plumbing and invariants only; the guard rejects are the Phase 12 money guards doing their job, not a finding about any strategy.

**Reading the smoke result.** The smoke script reads only the requested window and no history before it, so a 30-day window cannot fill the 1000-bar strategy window: 717 of 720 closed 1H bars are `WARMUP_INSUFFICIENT` and the three other bars are `NO_TRADE_REGIME`. The 30-day smoke therefore proves that the set loads, the case builds, the engine runs deterministically and only canonical codes appear; it does not drive any plan through the simulator. The geometry itself (setups, plans, guards, invariants) is exercised by the census, which does read the warm-up history, and by the supplementary 90-day smoke below. A zero trade count in a short window is a recorded finding, not a failure.

**Supplementary smoke on 90 days (plans flow through the simulator).** The same command with `--days 90` (2026-07-04 to 2026-10-01, the window of 14-14) fills the 1000-bar strategy window after about 42 days, so strategy bars, plans, guards and simulated fills all occur. Same constraint row, equity and risk rate; both runs of every family exited 0 with `digests_match=true` and `dataset_id` 2063b8caa9bdb2a6855ed0e538c1a1c923f3bf0d597b2c2fd1db1cd8793cdeb8; every `no_trade_counts` key is in the allowed set of the F8 definition. Three processes ran concurrently on one machine, so the runtimes are not comparable with 14-14 (tracemalloc was on). These counts are plumbing evidence only (D-17).

| Family | Set | Smoke window | Smoke runtime run 1 / run 2 (s) | Smoke digest (both runs equal) | trade_count | no_trade_counts | Geometry invariants |
|---|---|---|---|---|---|---|---|
| trend-pullback | baseline-v6 | 90 days to 2026-10-01 | 593.514 / 543.265 | 9473c7954fe44ec12924296713a466574575d3f39ff20a51e85cfd0888ab5f66 | 174 | {"CONFLICT_WITH_OPEN_POSITION":79,"COST_TO_RISK_EXCEEDED":88,"NO_TRADE_REGIME":1111,"RR_TOO_LOW":40,"STALE_SETUP":1,"STOP_TOO_TIGHT":15,"WARMUP_INSUFFICIENT":796} | invariant_violations 0 (census above) |
| breakout-retest | baseline-v6 | 90 days to 2026-10-01 | 678.508 / 551.333 | de9cc44f53479351baef90f00508e3601a2d81f364c859bd936b395a99a8d034 | 34 | {"CONFLICT_WITH_OPEN_POSITION":2,"COST_TO_RISK_EXCEEDED":25,"NO_TRADE_REGIME":1328,"STOP_TOO_TIGHT":2,"WARMUP_INSUFFICIENT":796} | invariant_violations 0 (census above) |
| range-mr | baseline-v6 | 90 days to 2026-10-01 | 578.400 / 524.868 | 6b7251a45262da10e925f3db2224078921819ff3ed2a5042de373e0db8e98723 | 39 | {"COST_TO_RISK_EXCEEDED":27,"NO_TRADE_REGIME":1325,"RR_TOO_LOW":7,"STOP_TOO_TIGHT":5,"WARMUP_INSUFFICIENT":796} | invariant_violations 0 (census above) |

**Protocol answer (RESEARCH_PROTOCOL v2.0.0).** No amendment is needed. The protocol governs method (the closed-candle rule including "No future swing confirmation leaks", the 40/40/20 split, the multiple-testing correction, the single-use holdout and the kill gate), not strategy values or geometry, and its v2.0.0 migration paragraph already names the new versioned Phase 15 sets as the evidence-bearing lineage ("the evidence-bearing strategy sets are the new versioned sets created in Phase 15"). The pivot detectors satisfy the closed-candle rule by construction: a pivot is known only at the close of bar t+R and the evaluated bar is never part of one (D-01, D-04, tested for prefix invariance).

**What a re-run still needs.** The re-run itself is not part of Phase 15; before it starts:

1. The candidate-set freeze step per RESEARCH_PROTOCOL for the three baseline-v6 sets (the sheets stay HYPOTHESIS and NOT FROZEN until then).
2. A data window and split, chosen under the protocol (the 30-day and 90-day windows here are plumbing checks only).
3. The frozen universe `research-universe-v1` (12 symbols, `docs/research/universe/research-universe-v1.toml`); this audit ran BTCUSDT only.
4. A measurement of trade-floor reachability, which is still unmeasured; the floor is never lowered to rescue signal volume (D-17).
5. Point-in-time exchange constraints for the window; this check used one BTCUSDT row observed on 2026-10-05, back-extrapolated (D-30), which is not valid for strategy evaluation.

**PLACEHOLDER values.** 16 (trend-pullback), 17 (breakout-retest) and 22 (range-mr) keys of the three baseline-v6 sets carry basis PLACEHOLDER, so `pin_stream_epoch` refuses them: baseline-v6 stays out of paper freezing until experiments supply an EXPERIMENT basis (D-16).
