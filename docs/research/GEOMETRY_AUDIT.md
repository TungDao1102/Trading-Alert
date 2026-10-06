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
