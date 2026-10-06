# Phase 15 geometry audit: family sheets versus code

**Status:** audit of the code as it stood before any Phase 15 geometry change (plan 15-01, wave 1).
**Scope:** the three family sheets under `docs/research/families/` (A trend-pullback, B breakout-retest, C range-mr), their Stage baseline rows, and the code that implements them.

## Purpose

CONTEXT decision D-10 requires a geometry audit table before any geometry code changes in Phase 15. ROADMAP criterion 2 (audit finding F-113) requires that every implemented geometry matches its sheet's Stage baseline, or that a DECISIONS entry records the deviation. This document is the input for the DECISIONS entry D054 (plan 15-15) and for the "implemented as" lines of the family sheets (plan 15-14). A machine check lives in `tests/test_geometry_audit_doc.py`.

Where D-22 to D-27 (the user decisions after research) conflict with D-10 or D-11, D-22 to D-27 win. The rows below already use the later decisions.

None of the figures here is a tuning input. Survival and arithmetic figures are consequences of a stated reading of a sheet cell; no value is chosen or adjusted from them (D-17).

## Verdict vocabulary

- **MATCH**: the code equals the sheet Stage baseline for this cell.
- **FIX**: Phase 15 changes the code to the sheet; the Decision column names the deciding decision.
- **DEVIATION**: the code keeps a different rule from the sheet; the reason is recorded in D054.
- **PARAMETER**: the cell is decided by a registry value that is ratified in the plan 15-08 checkpoint; plan 15-15 converts it to MATCH or DEVIATION.

## Audit table

Line numbers refer to the code before Phase 15 (`src/core/strategy.py`, `src/core/planner.py`, `src/core/features.py`).

| Family | Cell | Sheet Stage baseline | Code before Phase 15 | Phase 15 resolution | Verdict | Decision |
|---|---|---|---|---|---|---|
| A | regime | R1 structure-only 4H regime (trend-pullback.md section 2.1) | EMA50(4H) close compare in `_resolve_regime` (strategy.py:98-120); its own comment calls it an R2-style proxy | Keep the EMA50 proxy for Families A and B and record the deviation from R1 in D054 | DEVIATION | D-22 |
| A | pullback | P1 zone touch: bar low inside the zone (section 2.2) | `support_lower <= low <= support_upper` in `_detect_setup` (strategy.py:157) | Predicate unchanged; the level it is measured against changes (see level) | MATCH | n/a |
| A | level | Confirmed pivots only (section 5 rows 1-3): a pivot is known at the close of bar t+R | Trailing 20-bar extreme that includes the evaluated bar: window `candles[i-lookback+1 : i+1]` in `_swing_series` (features.py:187) | Most recent confirmed pivot inside `swing_lookback`; evaluated bar never part of it; no pivot means NO_TRADE; prefix-invariance tested | FIX | D-01, D-02, D-03, D-04 |
| A | zone | Zones with merge, collide and separate semantics and `zone_min_touches` (section 5.1) | A single level plus or minus `zone_tolerance_atr` x ATR (planner.py:109-118) | Single pivot zone kept; the merge/collide/separate rules stay a research variant and the deviation is recorded | DEVIATION | D-05, D054 |
| A | entry | E2 zone plus or minus an ATR buffer | Zone plus or minus `entry_buffer_atr` x ATR, entry reference at the zone midpoint (planner.py:382-389) | Unchanged | MATCH | n/a |
| A | stop | S2 structure minus k ATR | `swing_low - sl_buffer`, which sits inside the entry zone (planner.py:116 against the zone edge at planner.py:382) | Stop beyond the outer edge of the whole entry zone: LONG `entry_min - sl_buffer_atr` x ATR, SHORT `entry_max + sl_buffer_atr` x ATR. Measuring the buffer from the outer zone edge (not from the pivot) is a recorded reading of S2. Shared invariant: SL strictly outside the zone after quantization, and a minimum stop distance in ATR | FIX | D-05, D-06, D-08 |
| A | target | T1 fixed R multiple | TP1 is the opposing swing, TP2 is entry plus or minus 2 x the TP1 leg (planner.py:109-118, 402) | Keep the structure target (opposite confirmed pivot) and TP2 = entry +/- 2 x (TP1 - entry). A target built from `minimum_rr` would make the RR gate vacuous (CR-03); the gate stays an acceptance threshold only | DEVIATION | D-09, D-14 |
| B | regime | R1 structure-only 4H regime (breakout-retest.md section 2.3 and Q1 pointer) | EMA50(4H) close compare in `_resolve_regime` (strategy.py:98-120) | Keep the EMA50 proxy for Families A and B and record the deviation from R1 in D054 | DEVIATION | D-22 |
| B | direction | Section 2.4: the breakout direction must agree with the 4H regime (with-direction only) | Any non-NEUTRAL regime is admitted; the direction comes from the breakout side, so counter-trend breakouts signal (strategy.py:583) | Trade only with-direction: the breakout direction must equal the regime direction. Behind the optional `geometry_version` key, absent means legacy | FIX | D-24, D-25 |
| B | breakout | B1 single close outside the zone (section 2.1) | `breakout_confirmation_bars = 3` in the legacy sets (strategy.py:236, 257-262); this matches no sheet row, because B4 is two consecutive closes | Proposed baseline value 1 (sheet B1), ratified in the plan 15-08 checkpoint; 3 stays only as a recorded deviation if the user chooses to keep it. Plan 15-15 converts this row to MATCH or DEVIATION | PARAMETER | D-16, D-17 |
| B | retest | R1 touch: the bar low is inside the broken zone (section 2.2) | A band of `retest_depth_atr` x ATR around the outer edge `zone_upper` in `_find_retest_bar` (strategy.py:327-356) | Band rule kept; the deviation from R1 is recorded | DEVIATION | D-14, D054 |
| B | anchoring | The retest is confirmed at the close of the retest bar (the sheet look-ahead table) | Any breakout plus retest anywhere in the 1000-bar window signals (strategy.py:257 scans the whole history, the retest search starts at i + 1 on line 293 with no end condition); retest bar median age 37 bars on real data | The first retest after the breakout must be the evaluated bar n-1; an older retest produces no signal. Behind `geometry_version` | FIX | D-24, D-25 |
| B | entry | E2 zone plus or minus an ATR buffer | Degenerate zone at the broken edge plus or minus `entry_buffer_atr` x ATR (planner.py:119-136) | Unchanged | MATCH | n/a |
| B | stop | S3 zone invalidation: the other side of the broken support/resistance zone (Q6) | `zone_upper - sl_buffer` for LONG, `zone_lower + sl_buffer` for SHORT (planner.py:131-136, 180-185), so the stop is 0.2 ATR under the retest edge | Stop beyond the far edge of the narrow S/R zone (swing plus or minus `zone_tolerance_atr` x ATR), then `sl_buffer_atr` x ATR. The D-10 bullet "keep the code stop" is superseded by D-23. Decision basis as D-23 records it: the sheet text alone (breakout-retest.md section 2.2 zone bounds, Q6, section 6 parameter rows). Behind `geometry_version` | FIX | D-23, D-25 |
| B | target | T1 fixed R multiple | Measured move: edge plus or minus the range height (planner.py:135, 184) | Measured move kept; a target built from `minimum_rr` would make the RR gate vacuous (CR-03). Recorded as a deviation from T1 | DEVIATION | D-23, D-10, D-14 |
| C | regime | R1 range detection with the regime filter ON (range-mr.md section 3, row 133 binding rule 2) | NEUTRAL only on exact equality of the 4H close and EMA50 (strategy.py:116-120, gate at strategy.py:592): 0 of 4,380 4H bars per symbol, so Family C can never signal | NEUTRAL means neither HH+HL nor LH+LL on confirmed 4H pivots inside `regime_filter_lookback` 4H bars (the D-01 pivot function on the context stream, closed bars only). Behind `geometry_version` | FIX | D-22, D-25 |
| C | range | Merged zones, and every closed 4H bar over `regime_filter_lookback` agrees on range (row 133 rule 2) | A 20-bar swing at bar n-2 with touches counted before it (strategy.py:400-437); `regime_filter_lookback` is read nowhere | Range construction kept. Phase 15 reads `regime_filter_lookback` as the pivot window of the regime verdict at the last closed 4H bar. The remaining difference is recorded | DEVIATION | D-14, D054 |
| C | entry | E2 zone plus or minus an ATR buffer | Range edge plus or minus `entry_buffer_atr` x ATR, degenerate zone (planner.py:137-147) | Unchanged | MATCH | n/a |
| C | stop | S3 zone invalidation outside the range edge | `zone_lower - sl_buffer`, about 0.2 ATR from the entry reference (planner.py:145, 194) | Stop beyond the far edge of the narrow S/R zone around the range edge, then `sl_buffer_atr` x ATR; must satisfy the shared stop invariant | FIX | D-22, D-23 |
| C | target | T-mid: take profit at the range midpoint (Stage C baseline) | The opposite boundary (`zone_upper` for LONG, `zone_lower` for SHORT), which is the sheet's T-opposite variant (planner.py:146, 195) | Optional key `tp_mode` with T_MID for the Stage C set; T_OPPOSITE stays as the named variant that needs its own parameter set later | FIX | D-10, D-25 |

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
