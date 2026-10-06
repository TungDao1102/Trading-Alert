# Hand arithmetic behind the Phase 15 geometry cases

Plan 15-03 (D-01, D-05, F-301, F-608). Every expected value comes from an independent
Decimal computation with no project imports, never from the output of the code under test.
The numbers in this file were produced by the standalone one-liners pasted into each section
(plain `python -c` with `from decimal import Decimal as D`, nothing from `src/`, `tests/` or
`scripts/`), and `geometry_cases.json` was then written by hand from the section. Nothing in
the repository writes an expectation: do not regenerate a number by running the planner and
pasting the result; change the derivation here first.

Every parameter value in these cases is test-local. None of them is a proposed or ratified
strategy parameter (ratification is plan 15-08).

## Common inputs

| Symbol | Value |
|--------|-------|
| symbol / streams | synthetic `BTCUSDT`, 250 closed 1h bars (setup) and 250 closed 4h bars (context) |
| bar shape | every bar has high - low = 2.00 (high = close + 1.00, low = close - 1.00), open = previous close, consecutive closes differ by at most 1.00, so every true range is 2.00 and ATR(14) = 2.00 exactly |
| zone_tolerance_atr | 0.5 (half = 0.5 x 2.00 = 1.00) |
| entry_buffer_atr | 0.1 (entry buffer = 0.20) |
| sl_buffer_atr | 0.2 (stop buffer = 0.40) |
| minimum_rr | 2 |
| swing_lookback | 20 |
| pivot_left_bars / pivot_right_bars | 3 / 3 |
| geometry_version | 1 (the legacy contrast case omits it and the pivot keys) |
| equity / risk_rate | 10000 / 0.005 |
| setup stream | bar k (0-based) closes 44.25 + 0.25 k for k = 0..235 (bar 235 closes 103.00), then bars 236..249 close 102, 101, 100, 101, 102, 103, 104, 105, 104, 103, 102, 101, 100, 99 |
| context stream | 250 bars rising 1.00 per bar (BULLISH: last close above EMA50) |

Bar indices used below: the evaluated bar is i = 249; the pivot low bar is t = 238 (close
100.00, low 99.00); the pivot high bar is 243 (close 105.00, high 106.00).

## a_long_worked

Pivot low. Lows of bars 235..241 are 102, 101, 100, 99, 100, 101, 102. Bar 238 has the lowest
low of [235, 241], the left side non-strict and the right side strict, and it is confirmed once
bar 241 has closed. It is the most recent confirmed pivot low inside the last 20 bars, so
P = 99.00. The evaluated bar 249 closes 99.00, so its low is 98.00, and it is never a candidate
(it would be confirmed only at bar 252).

Pivot high. Highs of bars 240..246 are 103, 104, 105, 106, 105, 104, 103. Bar 243 is the most
recent confirmed pivot high, so TP1 = 106.00.

Zone and plan, with half = 0.5 x 2.00 = 1.00, entry buffer 0.1 x 2.00 = 0.20, stop buffer
0.2 x 2.00 = 0.40:

```
python -c "from decimal import Decimal as D; P=D('99'); h=D('0.5')*D('2'); print(P-h, P+h)"
98.0 100.0
python -c "from decimal import Decimal as D; zl=D('98'); zu=D('100'); eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); print(zl-eb, zu+eb, zl-eb-sb, ((zl-eb)+(zu+eb))/2)"
97.8 100.2 97.4 99.0
python -c "from decimal import Decimal as D; ref=D('99'); stop=D('97.4'); tp1=D('106'); print(ref-stop, (tp1-ref)/(ref-stop), ref+2*(tp1-ref))"
1.6 4.375 113.0
```

| Field | Value |
|-------|-------|
| zone_upper / zone_lower | 100.00 / 98.00 |
| entry_min | 97.80 |
| entry_max | 100.20 |
| entry_ref | 99.00 |
| stop_loss | 97.40, strictly below entry_min |
| TP1 | 106.00 |
| TP2 | 113.00 |
| risk | 1.60 |
| RR to TP1 | 4.375 |

## a_long_legacy_contrast

The same candles with the same parameters minus geometry_version and the pivot keys. The
trailing 20-bar swing low includes the evaluated bar: min low over bars 230..249 = 98.00, and
the swing high is max high = 106.00.

```
python -c "from decimal import Decimal as D; sl=D('98'); h=D('1'); eb=D('0.2'); sb=D('0.4'); lo=sl-h-eb; hi=sl+h+eb; print(sl-h, sl+h, lo, hi, sl-sb, (lo+hi)/2)"
97.0 99.0 96.8 99.2 97.6 98.0
python -c "from decimal import Decimal as D; ref=D('98'); stop=D('97.6'); tp1=D('106'); print((tp1-ref)/(ref-stop), ref+2*(tp1-ref))"
20 114.0
```

| Field | Value |
|-------|-------|
| zone | 99.00 / 97.00 |
| entry_min / entry_max | 96.80 / 99.20 |
| entry_ref | 98.00 |
| stop_loss | 97.60, inside the entry zone (the defect Phase 15 corrects) |
| TP1 / TP2 | 106.00 / 114.00 |

## tp_loss_side

Plan 15-04 Task 1 (F6). Parameters as in a_long_worked except `minimum_rr` 0.1, so the RR gate
cannot be the thing that rejects. Setup closes: bars 0..239 close 44.25 + 0.25 k (bar 239
closes 104.00), then bars 240..257 close 103, 102, 101, 102, 103, 104, 105, 106, 107, 108, 108,
107.5, 107, 108, 108.5, 109, 108.5, 107.5. The evaluated bar is 257.

Pivot low: bar 252 (close 107, low 106.00) has lows 107, 107, 106.5 on its left (bars 249..251)
and 107, 107.5, 108 on its right (bars 253..255), so it is confirmed at bar 255 and P = 106.00.
The evaluated bar 257 has low 106.50, inside 105.00-107.00. No later pivot low exists (the
newest candidate is bar 254).

Pivot high: candidates run from bar 238 to bar 254. Bar 239 (close 104, high 105.00) has rising
highs on its left and strictly lower highs 104, 103, 102 on its right, so it is a confirmed
pivot high. Every candidate after it fails the right-side test: bars 240..248 are followed by
a higher high, bar 249 (high 109) by an equal high at bar 250, bar 250 by the equal high 109 at
bar 253, bars 251 and 252 by the higher 109 at bar 253, and bars 253 and 254 by the higher
highs 109.5 and 110 at bars 254 and 255. The peak at bar 255 (high 110.00) has only two bars to
its right, so it is not yet confirmed. So TP1 = 105.00, which is below entry_ref.

```
python -c "from decimal import Decimal as D; P=D('107')-D('1'); h=D('0.5')*D('2'); zl=P-h; zu=P+h; eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); print(P, zl, zu, zl-eb, zu+eb, zl-eb-sb, ((zl-eb)+(zu+eb))/2)"
106 105.0 107.0 104.8 107.2 104.4 106.0
python -c "from decimal import Decimal as D; print(D('104')+1, D('105')-D('106'))"
105 -1
```

| Field | Value |
|-------|-------|
| zone | 107.00 / 105.00 |
| entry_min / entry_max | 104.80 / 107.20 |
| entry_ref | 106.00 |
| stop_loss | 104.40, strictly below entry_min |
| TP1 | 105.00, signed profit-side leg -1.00 (loss side) |
| expected plan() result | NO_TRADE, RR_TOO_LOW (abs() used to give RR 0.625 and a plan) |

## a_short_worked

Plan 15-04 Task 2 (D-05 mirrored). The a_long_worked setup path mirrored through 200: bar k
closes 200 - c_k, so the ramp falls from 155.75 to 97.00 and the tail closes 98, 99, 100, 99,
98, 97, 96, 95, 96, 97, 98, 99, 100, 101. The 4h context falls 1.00 per bar (BEARISH: last
close below EMA50). Same parameters as a_long_worked.

Pivot high: bar 238 (close 100, high 101.00) is the highest high of bars 235..241 (left
non-strict, right strict) and is confirmed at bar 241, so H = 101.00. The evaluated bar 249
closes 101, high 102.00, inside 100.00-102.00 (upper edge inclusive). Pivot low: bar 243
(close 95, low 94.00) is the newest confirmed pivot low, so TP1 = 94.00.

```
python -c "from decimal import Decimal as D; H=D('200')-D('99'); h=D('0.5')*D('2'); zl=H-h; zu=H+h; eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); emin=zl-eb; emax=zu+eb; print(H, zl, zu, emin, emax, emax+sb, (emin+emax)/2)"
101 100.0 102.0 99.8 102.2 102.6 101.0
python -c "from decimal import Decimal as D; ref=D('101'); stop=D('102.6'); tp1=D('200')-D('106'); print(tp1, ref-stop, stop-ref, (ref-tp1)/(stop-ref), ref-2*(ref-tp1))"
94 -1.6 1.6 4.375 87
```

| Field | Value |
|-------|-------|
| zone_upper / zone_lower | 102.00 / 100.00 |
| entry_min / entry_max | 99.80 / 102.20 |
| entry_ref | 101.00 |
| stop_loss | 102.60, strictly above entry_max |
| TP1 / TP2 | 94.00 / 87.00 |
| risk / RR to TP1 | 1.60 / 4.375 |

## a_long_audit_60000

Audit anchor (CONTEXT, RESEARCH F5): pivot 60,000 and ATR 400. The a_long_worked path mapped
through close' = 200 c + 40,200 (so every bar has range 400, the 0.25 ramp steps become 50,
and the pivot low 99.00 becomes 60,000). Parameters unchanged (they are ATR multiples):
half = 0.5 x 400 = 200, entry buffer 0.1 x 400 = 40, stop buffer 0.2 x 400 = 80.

```
python -c "from decimal import Decimal as D; atr=D('400'); P=D('60000'); h=D('0.5')*atr; zl=P-h; zu=P+h; eb=D('0.1')*atr; sb=D('0.2')*atr; emin=zl-eb; emax=zu+eb; print(zl, zu, emin, emax, (emin+emax)/2, emin-sb)"
59800.0 60200.0 59760.0 60240.0 60000.0 59680.0
python -c "from decimal import Decimal as D; a=D('200'); b=D('60000')-D('99')*a; tp1=a*D('106')+b; ref=D('60000'); print(tp1, ref+2*(tp1-ref), (tp1-ref)/(ref-D('59680')))"
61400 62800 4.375
```

| Field | Value |
|-------|-------|
| zone_upper / zone_lower | 60200 / 59800 |
| entry_min / entry_max | 59760 / 60240 |
| entry_ref | 60000 |
| stop_loss | 59680, strictly below entry_min 59760 (no stop inside 59760-60240) |
| TP1 / TP2 | 61400 / 62800 |

## a_long_audit_59000

Audit anchor 1 (CONTEXT): pivot 59,000 and ATR 300. The same path mapped through
close' = 150 c + 44,150 (bar range 300, pivot low 99.00 becomes 59,000). Old geometry put the
stop at 58,940, inside the entry zone; the corrected stop lies below entry_min 58,820.

```
python -c "from decimal import Decimal as D; atr=D('300'); P=D('59000'); h=D('0.5')*atr; zl=P-h; zu=P+h; eb=D('0.1')*atr; sb=D('0.2')*atr; emin=zl-eb; emax=zu+eb; print(zl, zu, emin, emax, (emin+emax)/2, emin-sb)"
58850.0 59150.0 58820.0 59180.0 59000.0 58760.0
python -c "from decimal import Decimal as D; a=D('150'); b=D('59000')-D('99')*a; tp1=a*D('106')+b; ref=D('59000'); print(tp1, ref+2*(tp1-ref), (tp1-ref)/(ref-D('58760')))"
60050 61100 4.375
```

| Field | Value |
|-------|-------|
| zone_upper / zone_lower | 59150 / 58850 |
| entry_min / entry_max | 58820 / 59180 |
| entry_ref | 59000 |
| stop_loss | 58760, strictly below entry_min 58820 |
| TP1 / TP2 | 60050 / 61100 |

## a_long_no_opposite_pivot

Plan 15-04 Task 2 (D-03, D-09). Bars 0..220 close 44.25 + 0.25 k (bar 220 closes 99.25, the
peak), bars 221..246 close 99.25 - 0.25 j for j = 1..26 (bar 246 closes 92.75), then bars
247..249 close 93.00, 93.25, 93.00. Same parameters as a_long_worked, rising 4h context.

Pivot low: bar 246 (low 91.75) has strictly higher lows on its right (92.00, 92.25, 92.00) and
higher lows on its left, so it is confirmed at bar 249 and P = 91.75. The evaluated bar 249 has
low 92.00, inside 90.75-92.75, so evaluate emits a LONG signal.

Pivot high: candidates inside the last 20 bars are bars 230..246. Every one of them has higher
highs on its left (the series falls 0.25 per bar there), so none qualifies, and the 99.25 peak at
bar 220 is outside the lookback. There is no TP1, so plan() returns NO_TRADE with STALE_SETUP.

## p9_regression

Plan 15-04 Task 3 (D-01, D-07, F4). Same parameters as a_long_worked (zone_tolerance_atr 0.5, so
tolerance = 0.5 x 2.00 = 1.00 = 0.5 ATR). Setup path: bars 0..247 close 44.25 + 0.25 k (bar 247
closes 106.00), then bars 248..257 close 105, 104, 103, 102, 101, 100.5, 100, 100.5, 101, 101.5.
The 4h context rises (BULLISH).

Pivot low: bar 254 (close 100, low 99.00) has lows 101, 100, 99.5 on its left and 99.5, 100,
100.5 on its right, confirmed at bar 257, so P = 99.00. Pivot highs: bar 257 (high 102.50, right
bars 258..260 are lower in both windows) and bar 247 (high 107.00). The newest is 102.50, so
TP1 = 102.50.

Beyond tolerance (evaluated bar 262): bars 258..262 close 100.5, 99.5, 98.5, 97.5, 97. The last
bar has low 96.00 = P - 1.5 x 2.00, below the zone 98.00-100.00, so there is no signal. (The
legacy trailing 20-bar swing low includes the evaluated bar, becomes 96.00 and signals.)

Inside tolerance (evaluated bar 260): bars 258..260 close 100.5, 99.7, 99.2. The last bar has
low 98.20 = P - 0.4 x 2.00, a new low but inside 98.00-100.00, so it signals.

```
python -c "from decimal import Decimal as D; P=D('99'); h=D('0.5')*D('2'); zl=P-h; zu=P+h; eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); emin=zl-eb; emax=zu+eb; ref=(emin+emax)/2; tp1=D('102.5'); print(zl, zu, emin, emax, ref, emin-sb, tp1-ref, (tp1-ref)/(ref-(emin-sb)), ref+2*(tp1-ref))"
98.0 100.0 97.8 100.2 99.0 97.4 3.5 2.1875 106.0
python -c "from decimal import Decimal as D; P=D('99'); print(P-D('1.5')*D('2'), P-D('0.4')*D('2'))"
96.0 98.2
```

| Field (inside-tolerance plan) | Value |
|-------|-------|
| zone_upper / zone_lower | 100.00 / 98.00 |
| entry_min / entry_max | 97.80 / 100.20 |
| entry_ref | 99.00 |
| stop_loss | 97.40, below the signal bar low 98.20 |
| TP1 / TP2 | 102.50 / 106.00 |
| RR to TP1 | 2.1875 (minimum_rr 2) |

# Family B (breakout-retest) cases, plan 15-05

Basis of the stop (D-23, sheet text alone): `docs/research/families/breakout-retest.md` section
2.2 (the broken zone has `resistance_zone_lower_bound` and `resistance_zone_upper_bound`), Q6
(Stage B baseline S3 = zone invalidation on the other side of the broken zone) and section 6
(`zone_tolerance_atr` is the zone half-width, `sl_buffer_atr` is the S3 buffer). So for a LONG
the stop sits one `sl_buffer_atr x ATR_last` beyond the LOWER bound of the broken resistance
zone, `swing_high_ref - zone_tolerance_atr x ATR_ref`. The measured-move TP1 is kept (D-23).

Same independence rule as above: every number comes from a standalone `python -c` Decimal
one-liner, never from the code under test. Every parameter value is test-local. None is a
proposed or ratified strategy parameter, with one labelled exception below
(`breakout_confirmation_bars = 1`, the proposed baseline of sheet Stage B B1, ratified only at
plan 15-08).

## Family B common inputs

| Symbol | Value |
|--------|-------|
| symbol / streams | synthetic `BTCUSDT`, 250 closed 1h bars (setup) and 250 closed 4h bars (context) |
| bar shape | high - low = 2.00 for every bar and the true range of every bar is 2.00 (the breakout bar is built so that close - previous close = 2.00 with low = previous close), so ATR(14) = 2.00 at every bar |
| zone_tolerance_atr | 0.5 (half-width 0.5 x 2.00 = 1.00) |
| entry_buffer_atr | 0.1 (entry buffer 0.20) |
| sl_buffer_atr | 0.2 (stop buffer 0.40, from ATR_last) |
| minimum_rr | 2 |
| swing_lookback | 20 |
| retest_window_bars / retest_depth_atr | 5 / 0.3 (band half-width 0.3 x ATR_ref = 0.60) |
| breakout_confirmation_bars | 1 (test-local, set explicitly in every ParameterSet of the main worked cases: the proposed baseline of sheet Stage B B1, ratified only at 15-08; the inherited baseline-v5 value 3 is the legacy implementation value and is covered separately by `b_long_legacy_confirm3`) |
| geometry_version | 1 (the legacy contrast sets omit it) |
| equity / risk_rate | 10000 / 0.005 |
| context stream | 250 bars rising 1.00 per bar (BULLISH), falling 1.00 per bar for the SHORT mirror (BEARISH) |

Bars used by `family_b_long_setup()` (first_breakout f = 246, plateau 2): bars 0..244 alternate
close 99 / 100 (even index 100, odd index 99: bar 244 closes 100); bar 245 closes 101; bar 246 is
the breakout bar (open 101, low 101, high 103, close 103); bars 247 and 248 close 104 (low 103,
high 105); the evaluated bar 249 closes 103 (open 104, low 102, high 104).

## b_long_worked

Test-local `breakout_confirmation_bars = 1` (proposed baseline, sheet B1). The edge, zone,
`sr_far_edge` and stop formulas below do not contain `breakout_confirmation_bars`: the value only
selects the reference bar `ref_prev = i - breakout_confirmation_bars - 1` and how many closes must
clear the edge.

Breakout end bar i = 246, reference bar ref_prev = 246 - 1 - 1 = 244. Window of the 20-bar swing
at bar 244 is bars 225..244: highs are 101 (close 100) or 100 (close 99), so swing_high_ref = 101;
lows are 99 or 98, so swing_low_ref = 98. Bar 245 (high 102) is NOT in that window, which is what
separates ref_prev 244 from 245. ATR_ref = ATR(244) = 2.00 and ATR_last = ATR(249) = 2.00.

Edge: 101 + 0.5 x 2.00 = 102.00. Close of bar 246 = 103 > 102.00, a breakout. Retest band
(depth 0.3 x 2.00 = 0.60): [101.40, 102.60]. Bars 247 and 248 have low 103, outside the band; bar
249 has low 102 inside it, and it is the first bar of the band after the breakout, so the retest
is the evaluated bar n - 1 = 249 (within retest_window_bars of bar 246).

Other breakout end bars scanned from n - 2 = 248 down to max(1 + 1, n - 1 - 5) = 244:
i = 248: ref 246, swing high 103, edge 104.00, close 104 is not above it. i = 247: ref 245, swing
high 102, edge 103.00, close 104 clears it, but its first retest is bar 248 (low 103 in
[102.40, 103.60]), not bar 249, so it does not count. i = 246 is the first match.
i = 245 and 244 close at or below 101, no breakout.

```
python -c "from decimal import Decimal as D; sh=D('100')+D('1'); sl=D('99')-D('1'); atr=D('2'); t=D('0.5'); edge=sh+t*atr; zl=sl-t*atr; sr=sh-t*atr; h=edge-zl; print(sh, sl, edge, zl, sr, h, edge+h)"
101 98 102.0 97.0 100.0 5.0 107.0
python -c "from decimal import Decimal as D; edge=D('102'); eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); sr=D('100'); stop=sr-sb; print(edge-eb, edge+eb, (edge-eb+edge+eb)/2, stop)"
101.8 102.2 102.0 99.6
python -c "from decimal import Decimal as D; ref=D('102'); stop=D('99.6'); tp1=D('107'); print(ref-stop, tp1-ref, (tp1-ref)/(ref-stop), ref+2*(tp1-ref))"
2.4 5 2.083333333333333333333333333 112
python -c "from decimal import Decimal as D; print(D('102')-D('0.3')*D('2'), D('102')+D('0.3')*D('2'))"
101.4 102.6
```

| Field | Value |
|-------|-------|
| swing_high_ref / swing_low_ref / ATR_ref | 101 / 98 / 2.00 |
| zone_upper = edge | 102.00 |
| zone_lower | 97.00 (swing_low_ref - 1.00) |
| sr_far_edge | 100.00 (swing_high_ref - 0.5 x ATR_ref = 101 - 1.00) |
| entry_min / entry_max | 101.80 / 102.20 (edge -/+ 0.1 x ATR_last) |
| entry_ref | 102.00 |
| stop_loss | 99.60 = sr_far_edge - 0.2 x ATR_last, strictly below entry_min |
| TP1 (measured move) | 107.00 = edge + (edge - zone_lower) |
| TP2 | 112.00 |
| risk / reward | 2.40 / 5.00 |
| RR to TP1 | 2.083333333333333333333333333 (minimum_rr 2) |

## b_long_legacy_contrast

The same window under a set that omits `geometry_version` (test-local `breakout_confirmation_bars
= 1`, same other values). The legacy scan runs i from n - 1 down and accepts any retest within the
window, so it stops at i = 247 (edge 103.00 from ref_prev 245, swing high 102, swing low 98;
retest bar 248 with low 103 inside [102.40, 103.60]). zone_upper = 103.00, zone_lower = 98 - 1.00
= 97.00, height 6.00, TP1 = 109.00, entry 102.80 .. 103.20, stop = edge - sl_buffer = 102.60 (the
legacy `edge - sl_buffer_atr x ATR`, unchanged), TP2 = 103 + 2 x 6 = 115.

```
python -c "from decimal import Decimal as D; edge=D('102')+D('1'); zl=D('98')-D('1'); h=edge-zl; eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); print(edge, zl, h, edge+h, edge-eb, edge+eb, edge-sb, edge+2*h)"
103 97 6 109 102.8 103.2 102.6 115
```
