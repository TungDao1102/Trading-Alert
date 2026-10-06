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
