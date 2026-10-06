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
