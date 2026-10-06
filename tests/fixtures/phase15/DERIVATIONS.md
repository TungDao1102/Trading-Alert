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

## b_short_worked

The exact mirror p -> 200 - p of `b_long_worked` (highs and lows swap, times unchanged) under a
BEARISH 4h context (250 bars falling 1.00 per bar), so every bar still has range 2.00 and true
range 2.00 and ATR = 2.00. Test-local `breakout_confirmation_bars = 1` (proposed baseline, sheet
B1); all other test-local values as in the common inputs.

Breakout end bar i = 246 (close 97 < the edge), ref_prev = 244. Swing low over bars 225..244 =
200 - 101 = 99, swing high = 200 - 98 = 102 (bar 245, high 100 after mirroring, is outside the
window). Edge (SHORT, `zone_lower`) = 99 - 0.5 x 2.00 = 98.00, `zone_upper` = 102 + 1.00 = 103.00,
`sr_far_edge` = swing_low_ref + 0.5 x ATR_ref = 99 + 1.00 = 100.00. Retest band [97.40, 98.60]
(0.3 x 2.00 = 0.60): bars 247 and 248 have high 97 (outside), bar 249 has high 98 (inside), so the
retest is the evaluated bar. The stop is the far edge plus the buffer: 100.00 + 0.40 = 100.40,
strictly above entry_max. TP1 is the measured move down: edge - (zone_upper - zone_lower).

```
python -c "from decimal import Decimal as D; sl=D('200')-D('101'); sh=D('200')-D('98'); atr=D('2'); t=D('0.5'); edge=sl-t*atr; zu=sh+t*atr; far=sl+t*atr; h=zu-edge; print(sl, sh, edge, zu, far, h, edge-h)"
99 102 98.0 103.0 100.0 5.0 93.0
python -c "from decimal import Decimal as D; edge=D('98'); eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); far=D('100'); print(edge-eb, edge+eb, (edge-eb+edge+eb)/2, far+sb)"
97.8 98.2 98.0 100.4
python -c "from decimal import Decimal as D; ref=D('98'); stop=D('100.4'); tp1=D('93'); print(stop-ref, ref-tp1, (ref-tp1)/(stop-ref), ref-2*(ref-tp1))"
2.4 5 2.083333333333333333333333333 88
```

| Field | Value |
|-------|-------|
| swing_low_ref / swing_high_ref / ATR_ref | 99 / 102 / 2.00 |
| zone_lower = edge | 98.00 |
| zone_upper | 103.00 |
| sr_far_edge | 100.00 |
| entry_min / entry_max | 97.80 / 98.20 |
| entry_ref | 98.00 |
| stop_loss | 100.40, strictly above entry_max |
| TP1 / TP2 | 93.00 / 88.00 |
| risk / reward | 2.40 / 5.00 |
| RR to TP1 | 2.083333333333333333333333333 |

## b_long_legacy_confirm3

legacy value, not the baseline to be ratified. This case uses the legacy implementation value
`breakout_confirmation_bars = 3` (baseline-v5 carries it; it matches no sheet row, B4 is two
consecutive closes) test-locally, with every other test-local value as in `b_long_worked`. The
edge, zone, `sr_far_edge` and stop formulas contain no `breakout_confirmation_bars`; the value
only selects the reference bar and how many closes must clear the edge.

Window (`family_b_confirm3_window`, first_breakout 245, plateau 3): bars 0..243 alternate close
99 / 100 with bar 243 at 100, bar 244 closes 101 (high 102), bar 245 is the breakout-run bar (open
101, low 101, high 103, close 103), bars 246, 247 and 248 close 104 (low 103, high 105), the
evaluated bar 249 closes 103 (low 102). True range is 2.00 everywhere, ATR = 2.00.

Breakout end bar i = 247: the three bars 245, 246, 247 close 103, 104, 104, all above the edge. The
reference bar is ref_prev = i - 3 - 1 = 243 (not 244: bar 244, high 102, is outside the window
224..243, so swing_high_ref = 101; it would be 102 and the edge 103.00 if the reference were 244).
Edge = 101 + 1.00 = 102.00, swing_low_ref = 98, zone_lower = 97.00, `sr_far_edge` = 101 - 1.00 =
100.00. Band [101.40, 102.60]: bar 248 has low 103 (outside), bar 249 low 102 (inside), so the
first retest is the evaluated bar. i = 248 is scanned first (ref_prev 244, swing high 102, edge
103.00, closes of bars 246..248 are 104, above it), but its retest band is [102.40, 103.60] and bar
249 has low 102, outside it, so it does not match. The plan numbers are those of `b_long_worked`.

```
python -c "from decimal import Decimal as D; sh=D('100')+D('1'); sl=D('99')-D('1'); atr=D('2'); t=D('0.5'); edge=sh+t*atr; zl=sl-t*atr; sr=sh-t*atr; print(edge, zl, sr, edge+(edge-zl))"
102.0 97.0 100.0 107.0
python -c "from decimal import Decimal as D; print(D('102')+D('0.5')*D('2'), D('0.3')*D('2'))"
103.0 0.6
```

With only one close above the edge (`family_b_confirm3_one_close_window`: bars 244, 245, 246 close
101, 101, 102, bar 247 closes 104, bar 248 closes 104, bar 249 closes 103) the same set gives no
signal: for i = 247 (edge 102.00) bar 246 closes 102, not above it; for i = 248 (ref_prev 244,
swing high 102, edge 103.00) bar 246 closes 102, not above it; lower i have closes at or below 102.

## Family B anchoring windows

All use the `b_long_worked` parameters (breakout_confirmation_bars 1, tolerance 0.5, window 5,
depth 0.3) with geometry_version 1, and the b_long_worked bar vocabulary (breakout bar custom with
close 103; plateau bars close 104; retest bar close 103 with low 102; every true range 2.00).

Stale breakout (`family_b_stale_window`): first_breakout 206, plateau 2, retest bar 209, then 40
bars (210..249) closing 104. The v1 scan covers i = 248 down to 244 only. For each of them the
swing window contains plateau highs 105, so the edge is at least 106.00 and no close of 104 clears
it. No signal under geometry_version 1 (NO_TRADE_REGIME). The legacy scan from n - 1 finds i =
207 (ref_prev 205, swing high 102, edge 103.00, close 104 above it) with the retest bar 208 (low 103
in [102.40, 103.60]), so the legacy set still signals.

Not the first retest (`family_b_not_first_retest_window`): first_breakout 246, plateau 1, retest
bar 248 (close 103, low 102), tail bar 249 closes 103 (low 102, inside the band again). For i =
246 the first retest is bar 248, not 249. i = 247 (edge 103.00, close 104 above it) has the band
[102.40, 103.60] and lows 102 at 248 and 249 are outside it. i = 248 closes at 103, below its edge
104. No signal.

Retest outside the window (`family_b_late_retest_window`): first_breakout 246, plateau 5 (bars
247..251 close 104), retest bar 252 (n = 253, n - 1 = 252). The scan covers i = 251 down to
max(2, 252 - 5) = 247, so i = 246 (the breakout whose first retest is 252, six bars after it, past
the five-bar window) is not scanned. i = 247 has edge 103.00 and the band [102.40, 103.60] holds
the lows 103 of bars 248..251, so its first retest is bar 248, not 252. i = 248 and above have
swing highs of 103 or 105 and edges of 104.00 or more, which a close of 104 does not clear. No
signal.

Counter-regime: the `b_long_worked` setup with a BEARISH 4h context (250 bars falling 1.00 per
bar). Under geometry_version 1 the scan is restricted to SHORT and no close is below any edge
(closes are 99..104 against SHORT edges of 97 or below), so NO_TRADE_REGIME with regime BEARISH.
The legacy set ignores the regime for Family B and signals LONG (edge 103.00 at i = 247, as in
`b_long_legacy_contrast`).

## Family B leakage and validator cases

Leakage (D-13). For `b_long_worked` and its mirror the reference bar is ref_prev = 244 (end bar i
= 246, confirmation bars 1), so every level is a function of bars 0..244: swing_high_ref 101,
swing_low_ref 98, ATR_ref 2.00 give zone_upper 102.00, zone_lower 97.00 and `sr_far_edge` 100.00
(SHORT: 103.00, 98.00, 100.00). Bar 249 is read only for "does its low (high for SHORT) lie in the
band 101.40..102.60 (97.40..98.60)", so a replacement bar with a higher high, another low, or
extreme values on the far side leaves all three levels unchanged. The replacements used keep
the low (LONG) or the high (SHORT) inside the band: LONG (high 105, low 102.30, close 104), (high
130, low 102.00, close 103); SHORT (high 98.30, low 95, close 96.50), (high 98.20, low 60, close 97).
The legacy wrapper (confirmation bars 1, no geometry_version) stops at i = 247 on bar 248, so its
zone bounds do not depend on bar 249 either.

D-08 (`min_stop_atr`) on `b_long_worked`: the risk from entry_ref is the width of the narrow
S/R zone plus the buffer, 2 x 0.5 x 2.00 + 0.2 x 2.00 = 2.40 = 1.2 ATR (ATR = 2.00). With
`min_stop_atr` 2.0 the floor is 4.00 and the plan is STOP_TOO_TIGHT; 1.21 gives 2.42 (rejected);
1.2 gives exactly 2.40 (equality passes) and the plan keeps stop 99.60.

D-06 (stop inside the entry zone) on `b_long_worked` with `zone_tolerance_atr` 0 and
`sl_buffer_atr` 0.05: with tolerance 0 the edge is the swing high itself. i = 248 (ref_prev 246,
swing high 103, edge 103.00) has no retest on bar 249 (low 102 outside 102.40..103.60); i = 247
(ref_prev 245, swing high 102, edge 102.00, close 104 above it) has the retest on bar 249 (low 102
inside 101.40..102.60), so edge 102.00, swing_low_ref 98 and zone_lower 98.00, `sr_far_edge` =
102.00 - 0 = 102.00. Entry zone 102 -/+ 0.1 x 2.00 = 101.80..102.20; stop = 102.00 - 0.05 x 2.00 =
101.90, not below entry_min 101.80, so STOP_TOO_TIGHT.

```
python -c "from decimal import Decimal as D; edge=D('102'); far=edge-D('0')*D('2'); print(far, far-D('0.05')*D('2'), edge-D('0.1')*D('2'), edge+D('0.1')*D('2'))"
102 101.90 101.8 102.2
python -c "from decimal import Decimal as D; print(D('2')*D('0.5')*D('2')+D('0.2')*D('2'), (D('2')*D('0.5')*D('2')+D('0.2')*D('2'))/D('2'), D('1.2')*D('2'), D('1.21')*D('2'), D('2.0')*D('2'))"
2.4 1.2 2.4 2.42 4.0
```

## b_long_invalidated

D-07 on B (INVALIDATED). `b_long_worked` up to the breakout bar 246, then (`family_b_crash_window`)
bar 247 open 108, low 108, high 109, close 109; bar 248 open 109, low 108, high 110, close 109; the
evaluated bar 249 open 109, high 109, low 98.50, close 100. Test-local `retest_depth_atr` 2.0 (band
half-width 2.0 x ATR_ref = 4.00) and `breakout_confirmation_bars` 1; other values as in
`b_long_worked`.

Breakout end bar i = 246 (ref_prev 244: swing high 101, ATR_ref 2.00, edge 102.00, close 103
above). Band 102 -/+ 4.00 = [98.00, 106.00]: bars 247 and 248 have low 108 (outside), bar 249 has
low 98.50 (inside), the first retest. Other end bars: i = 248 (ref_prev 246, swing high 103, edge
104.00, close 109 above) has the band [100.00, 108.00], bar 249 low 98.50 is outside; i = 247
(ref_prev 245, swing high 102, edge 103.00, close 109 above) has the band [99.00, 107.00], bar 248
low 108 and bar 249 low 98.50 are both outside. So the detector returns i = 246.

True ranges: bar 247 max(1, |109 - 103|, |108 - 103|) = 6; bar 248 max(2, 1, 1) = 2; bar 249
max(10.5, 0, 10.5) = 10.5. ATR before them is 2.00 (every earlier true range is 2.00). Wilder:

```
python -c "
from decimal import Decimal as D
a=D('2')
for tr in ('6','2','10.5'):
    a=(D('13')*a+D(tr))/D('14'); print(a)
sb=D('0.2')*a; print(sb, D('100')-sb, D('102')-D('0.1')*a)
print(D('102')-D('2.0')*D('2'), D('102')+D('2.0')*D('2'))
"
2.285714285714285714285714286
2.265306122448979591836734694
2.853498542274052478134110787
0.5706997084548104956268221574 99.42930029154518950437317784 101.7146501457725947521865889
98.0 106.0
```

ATR_last = 2.853498542274052478134110787, stop = sr_far_edge - 0.2 x ATR_last =
99.42930029154518950437317784, which is below entry_min 101.7146501457725947521865889 (D-06 passes)
and above the signal bar low 98.50, so D-07 fires: INVALIDATED.

# Family C (range-mr) cases, plan 15-06

Basis (D-22, D-23, D-10, sheet text alone): `docs/research/families/range-mr.md` section 3
(S3: the stop lies beyond the far edge of the narrow S/R zone around the touched range edge,
`zone_tolerance_atr` is the zone half-width, `sl_buffer_atr` the buffer; `tp_mode` T-mid is the
range midpoint, T-opposite the opposite boundary) and `GEOMETRY_AUDIT.md` flag F1 (the legacy
EMA50-equality NEUTRAL gate fires on 0 of 4,380 4H bars). Under `geometry_version` 1 the regime
comes from confirmed 4H pivots (D-22): the two newest pivot highs and lows inside the last
`regime_filter_lookback` closed 4H bars, BULLISH = HH + HL, BEARISH = LH + LL, otherwise NEUTRAL,
and fewer than two of either kind is NO_TRADE. Family C trades only in NEUTRAL.

Same independence rule as above: every number comes from a standalone `python -c` Decimal
computation with no project imports. Every parameter value is test-local; none is a proposed or
ratified strategy parameter (ratification is plan 15-08).

## Family C common inputs

| Symbol | Value |
|--------|-------|
| symbol / streams | synthetic `BTCUSDT`, 250 closed 1h bars (setup) and 250 closed 4h bars (context) |
| bar shape | every bar has high - low = 2.00 (high = close + 1.00, low = close - 1.00), open = previous close, consecutive closes differ by at most 1.00, so every true range is 2.00 and ATR(14) = 2.00 at every bar (ATR_ref = ATR_last = 2.00) |
| zone_tolerance_atr | 0.5 (half-width 0.5 x 2.00 = 1.00) |
| entry_buffer_atr | 0.1 (entry buffer 0.20) |
| sl_buffer_atr | 0.2 (stop buffer 0.40, from ATR_last) |
| minimum_rr | 2 |
| swing_lookback | 20 |
| touch_tolerance_atr | 0.3 (band half-width 0.3 x ATR_ref = 0.60) |
| zone_min_touches / zone_aging_bars / range_break_buffer_atr | 2 / 50 / 0.2 (inherited baseline-v5 values; band break buffer 0.40) |
| regime_filter_lookback | 50 4h bars; pivot_left_bars / pivot_right_bars 3 / 3 |
| geometry_version / tp_mode | 1 / T_MID (the legacy contrast case omits all of the geometry keys) |
| equity / risk_rate | 10000 / 0.005 |

1h setup stream (`range_mr_closes`, half_period 6): closes are a triangle wave 99, 100, ..., 105,
104, ..., 100, 99, ... of period 12 that ends on a trough: bar 249 closes 99 (low 98.00, high
100.00), bar 248 closes 100, troughs (close 99, low 98) at bars 249 - 12 m and peaks (close 105,
high 106) at bars 243 - 12 m.

## c_long_worked

4h regime (`PIVOT_NEUTRAL_CONTRACTING`): closes are flat 100 up to bar 200, then linear through
(210, 110), (220, 100), (230, 108), (240, 102) and (249, 106.5), steps 1.00, 1.00, 0.80, 0.60,
0.50 per bar. The regime window of the last bar i = 249 is bars 200..249 (lookback 50), pivot
candidates t in [200, 246]. The confirmed pivots, by the definition (low[t] <= left lows and <
right lows; mirrored for highs) in an independent script:

```
python -c "
from decimal import Decimal as D
wp=[(0,'100'),(200,'100'),(210,'110'),(220,'100'),(230,'108'),(240,'102'),(249,'106.5')]
cl=[]
for (i0,a),(i1,b) in zip(wp,wp[1:]):
    a=D(a);b=D(b)
    if not cl: cl.append(a)
    for k in range(i0+1,i1+1): cl.append(a+(b-a)*(k-i0)/(i1-i0))
hi=[c+1 for c in cl]; lo=[c-1 for c in cl]
i=249;L=3;R=3;LB=50
def piv(arr,high):
    out=[]
    for t in range(i-R,max(L,i-LB+1)-1,-1):
        lv=arr[t]
        ok=all((lv>=arr[j]) if high else (lv<=arr[j]) for j in range(t-L,t))
        ok=ok and all((lv>arr[j]) if high else (lv<arr[j]) for j in range(t+1,t+R+1))
        if ok: out.append((t,lv))
    return out
print(piv(hi,True)); print(piv(lo,False))
"
[(230, Decimal('109')), (210, Decimal('111'))]
[(240, Decimal('101')), (220, Decimal('99')), (200, Decimal('99'))]
```

Pivot highs, newest first: bar 230 (109) and bar 210 (111): 109 < 111, a lower high (LH). Pivot
lows, newest first: bar 240 (101) and bar 220 (99): 101 > 99, a higher low (HL; bar 200 is an older
third pivot low). LH + HL is neither BULLISH nor BEARISH, so the regime is NEUTRAL (a contracting
structure, which is the Family C range regime).

1h range. Evaluated bar n - 1 = 249, reference bar ref_idx = 248. The 20-bar swing window of bar
248 is bars 229..248: its lowest low is 98 (troughs at bars 237, 249 - 12 = 237) and its highest
high is 106 (peak at bar 243, also bar 231), so zone_lower = 98.00 and zone_upper = 106.00, and
ATR_ref = 2.00. Touch band = 0.3 x 2.00 = 0.60: lower band [97.40, 98.60], upper band [105.40,
106.60]. The touch scan covers bars 20..(248 - 20) = 228. Lower touches (low 98) are bars 225, 213,
201, ... and the last is 225 >= 249 - 50 = 199 (aging passes), count well above 2. The evaluated
bar has low 98.00 in the lower band, close 99 above the break line 98.00 - 0.40 = 97.60 and below
106.40, and |98 - 98| = 0 <= |100 - 106| = 6 (near-edge test), so RANGE_MR_LONG.

```
python -c "from decimal import Decimal as D; zl=D('98'); zu=D('106'); atr=D('2'); t=D('0.5'); far=zl-t*atr; print(far, far-D('0.2')*atr)"
97.0 96.6
python -c "from decimal import Decimal as D; zl=D('98'); atr=D('2'); eb=D('0.1')*atr; print(zl-eb, zl+eb, ((zl-eb)+(zl+eb))/2)"
97.8 98.2 98.0
python -c "from decimal import Decimal as D; zl=D('98'); zu=D('106'); ref=D('98'); stop=D('96.6'); tp1=(zu+zl)/2; print(tp1, ref-stop, tp1-ref, (tp1-ref)/(ref-stop), ref+2*(tp1-ref))"
102 1.4 4 2.857142857142857142857142857 106
```

| Field | Value |
|-------|-------|
| regime | NEUTRAL |
| zone_upper / zone_lower | 106.00 / 98.00 |
| sr_far_edge | 97.00 (zone_lower - 0.5 x ATR_ref) |
| entry_min / entry_max | 97.80 / 98.20 (zone_lower -/+ 0.1 x ATR_last) |
| entry_ref | 98.00 |
| stop_loss | 96.60 = sr_far_edge - 0.2 x ATR_last, strictly below entry_min |
| TP1 (T_MID) | 102.00 = (106 + 98) / 2 |
| TP2 | 106.00 = entry_ref + 2 x (TP1 - entry_ref) |
| risk / reward | 1.40 / 4.00 |
| RR to TP1 | 2.857142857142857142857142857 (minimum_rr 2) |

## c_long_legacy_contrast

The same 1h window and the legacy parameter set (no `geometry_version`, `tp_mode` or pivot
widths) with a flat 4h window (250 bars closing 100, so the last close equals EMA50 and the legacy
equality regime is NEUTRAL). Legacy geometry: zone 106.00 / 98.00, entry 97.80..98.20, stop =
zone_lower - sl_buffer = 98.00 - 0.40 = 97.60 (above the far edge, only 0.20 below entry_min), TP1
= zone_upper = 106.00, TP2 = 98 + 2 x 8 = 114.

```
python -c "from decimal import Decimal as D; zl=D('98'); zu=D('106'); sb=D('0.2')*D('2'); print(zl-sb, zu, zl+2*(zu-zl), (zu-zl)/(zl-(zl-sb)))"
97.6 106 114 20
```

## c_short_worked

The exact mirror p -> 200 - p of the c_long_worked 1h window (highs and lows swap, times
unchanged), with the same contracting 4h window (NEUTRAL: the mirror of LH + HL is HL + LH, still
neither BULLISH nor BEARISH, and the context itself is unchanged), so every bar keeps true range
2.00 and ATR = 2.00. The evaluated bar 249 closes 101 (high 102.00, low 100.00). Reference bar 248:
swing high over bars 229..248 = 200 - 98 = 102 (the mirror of the trough), swing low = 200 - 106 =
94, so zone_upper = 102.00 and zone_lower = 94.00. Upper band [101.40, 102.60]: the evaluated bar's
high 102.00 is inside it, upper touches (high 102) are the mirrored troughs at bars 225, 213, ...
(the last, 225, is within 50 bars of bar 249), close 101 lies inside [93.60, 102.40] (no range
break), and |102 - 102| = 0 < |100 - 94| = 6 (strict near-edge test for SHORT), so RANGE_MR_SHORT.

```
python -c "from decimal import Decimal as D; zu=D('102'); zl=D('94'); atr=D('2'); far=zu+D('0.5')*atr; stop=far+D('0.2')*atr; eb=D('0.1')*atr; print(far, stop, zu-eb, zu+eb, (zu-eb+zu+eb)/2)"
103.0 103.4 101.8 102.2 102.0
python -c "from decimal import Decimal as D; zu=D('102'); zl=D('94'); ref=D('102'); stop=D('103.4'); tp1=(zu+zl)/2; print(tp1, stop-ref, ref-tp1, (ref-tp1)/(stop-ref), ref-2*(ref-tp1))"
98 1.4 4 2.857142857142857142857142857 94
```

| Field | Value |
|-------|-------|
| regime | NEUTRAL |
| zone_upper / zone_lower | 102.00 / 94.00 |
| sr_far_edge | 103.00 (zone_upper + 0.5 x ATR_ref) |
| entry_min / entry_max | 101.80 / 102.20 |
| entry_ref | 102.00 |
| stop_loss | 103.40 = sr_far_edge + 0.2 x ATR_last, strictly above entry_max |
| TP1 (T_MID) | 98.00 |
| TP2 | 94.00 |
| risk / reward | 1.40 / 4.00 |
| RR to TP1 | 2.857142857142857142857142857 |

## c_long_t_opposite

`c_long_worked` with `tp_mode` T_OPPOSITE (every other value and the window unchanged): TP1 is the
opposite boundary zone_upper = 106.00, so the TP1 leg is 106 - 98 = 8.00 against the same risk
1.40; TP2 = 98 + 2 x 8 = 114.00.

```
python -c "from decimal import Decimal as D; ref=D('98'); stop=D('96.6'); tp1=D('106'); print(tp1-ref, (tp1-ref)/(ref-stop), ref+2*(tp1-ref))"
8 5.714285714285714285714285714 114
```

## Family C narrow range and validator cases

Narrow range (`range_mr_narrow_window`, `range_mr_closes(half_period=2)`): the 1h closes are a
triangle wave 99, 100, 101, 100, 99, ... of period 4 ending on a trough (bar 249 closes 99), with
the same contracting 4h window. Troughs (low 98) are bars 249 - 4 m and peaks (high 102) are bars
247 - 4 m, so zone_lower = 98.00, zone_upper = 102.00, the lower touches exist inside the aging
window and the evaluated bar touches the lower band: RANGE_MR_LONG with the same stop 96.60, entry
97.80..98.20 and risk 1.40 as c_long_worked. With T_MID the TP1 leg is (102 + 98) / 2 - 98 = 2.00,
which is below minimum_rr x risk = 2 x 1.40 = 2.80 (RR 1.428571428571428571428571429): RR_TOO_LOW.
With T_OPPOSITE the leg is 102 - 98 = 4.00 and the RR is 2.857142857142857142857142857 (TP1
102.00, TP2 106.00): a plan.

```
python -c "from decimal import Decimal as D; ref=D('98'); stop=D('96.6'); zu=D('102'); zl=D('98'); mid=(zu+zl)/2; print(mid, (mid-ref)/(ref-stop), D('2')*(ref-stop), (zu-ref)/(ref-stop), ref+2*(zu-ref))"
100 1.428571428571428571428571429 2.8 2.857142857142857142857142857 106
```

D-08 (`min_stop_atr`) on `c_long_worked`: the risk from entry_ref is 98.00 - 96.60 = 1.40 = 0.7 ATR
(ATR = 2.00). `min_stop_atr` 1.0 gives the floor 2.00 and the plan is STOP_TOO_TIGHT; 0.71 gives
1.42 (rejected); 0.7 gives exactly 1.40 (equality passes).

D-06 (stop inside the entry zone) on `c_long_worked` with `zone_tolerance_atr` 0 and `sl_buffer_atr`
0.05 (below `entry_buffer_atr` 0.1): sr_far_edge = 98.00 - 0 = 98.00, stop = 98.00 - 0.05 x 2.00 =
97.90, not below entry_min = 98.00 - 0.1 x 2.00 = 97.80, so STOP_TOO_TIGHT.

```
python -c "from decimal import Decimal as D; print(D('0.7')*D('2'), D('0.71')*D('2'), D('1.0')*D('2'), D('98')-D('96.6'))"
1.4 1.42 2.0 1.4
python -c "from decimal import Decimal as D; far=D('98')-D('0')*D('2'); print(far, far-D('0.05')*D('2'), D('98')-D('0.1')*D('2'))"
98 97.90 97.8
```

Leakage (D-13). Every Family C level is a function of the reference bar ref_idx = n - 2 = 248
(swing window bars 229..248 and ATR_ref = ATR(248) = 2.00), so zone_upper 106.00, zone_lower 98.00
and `sr_far_edge` 97.00 do not depend on bar 249. Bar 249 is read only for "is its low (high for
SHORT) inside the band [97.40, 98.60] ([101.40, 102.60])", the near-edge test and the range-break
line. The replacements used keep those true: LONG (high 100, low 97.50, close 99) and (high 105,
low 98.00, close 99); SHORT (mirror, zone 102 / 94, band [101.40, 102.60] on the high) (high
102.50, low 100, close 101) and (high 102, low 95, close 101). The levels are unchanged.

D-07 (INVALIDATED). `c_long_worked` up to bar 248, then the crash bar (`range_mr_crash_window`)
bar 249: open 100, high 100, low 95.00, close 98 (true range max(5, 0, 5) = 5). Test-local
`touch_tolerance_atr` 2.0 (band half-width 2.0 x ATR_ref = 4.00: lower band [94.00, 102.00], upper
band [102.00, 110.00]) lets the low 95.00 count as a lower-edge touch; the other detector tests
hold (close 98 above the break line 97.60, |95 - 98| = 3 <= |100 - 106| = 6, the high 100 is
below the upper band). The zone and sr_far_edge stay 98.00 / 106.00 / 97.00 (ATR_ref 2.00).
ATR_last = (13 x 2.00 + 5) / 14, so the stop = 97.00 - 0.2 x ATR_last, below entry_min (D-06
passes) and above the signal bar low 95.00, so D-07 fires: INVALIDATED.

```
python -c "from decimal import Decimal as D; a=(D('13')*D('2')+D('5'))/D('14'); print(a, D('0.2')*a, D('97')-D('0.2')*a, D('98')-D('0.1')*a)"
2.214285714285714285714285714 0.4428571428571428571428571428 96.55714285714285714285714286 97.77857142857142857142857143
```
