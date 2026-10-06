---
phase: 15-strategy-geometry-correction
plan: 10
status: in-progress
---

# Phase 15 Plan 10: v6 fixture payloads (Task 1 tracer in progress)

Work in progress record written with the Task 1 commit; replaced by the full summary when Task 2 completes.

## Standalone derivation commands

**G - geometry (pivot, Wilder ATR, zone, entry range, stop, TP1, TP2, limit, triggers)** - invoked as `bash geom.sh <zone_tolerance_atr> <long|short>`; the `"$@"` at the end passes the arguments to `python -c`.

```bash
python -c "
import sys
from decimal import Decimal as D, ROUND_HALF_EVEN as HE, ROUND_FLOOR as FL, ROUND_CEILING as CE
tol, eb, sl, short = D(sys.argv[1]), D('0.1'), D('0.2'), sys.argv[2] == 'short'
c = [D('100') + D(i) * D('0.1') for i in range(235)] + [D(x) for x in '122.6 121.8 121.0 120.2 119.4 118.6 119.6 120.6 121.6 122.4 122.2 121.8 121.4 121.0'.split()]
h = [x + D('0.8') for x in c] + [D('121.10')]; l = [x - D('0.8') for x in c] + [D('118.00')]; c.append(D('119.60'))
if short: c, h, l = [250 - x for x in c], [250 - x for x in l], [250 - x for x in h]
tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])) for i in range(1, 250)]
a = sum(tr[:14]) / 14
for t in tr[14:]: a = (13 * a + t) / 14
def piv(hi):
    v = h if hi else l
    for t in range(249 - 3, max(3, 249 - 20 + 1) - 1, -1):
        ok = all((v[t] >= v[j]) if hi else (v[t] <= v[j]) for j in range(t - 3, t)) and all((v[t] > v[j]) if hi else (v[t] < v[j]) for j in range(t + 1, t + 4))
        if ok: return t, v[t]
tp, P = piv(short); tt, T = piv(not short)
half = tol * a; q = lambda x: x.quantize(D('1e-18'), HE)
lo_, up_ = P - half, P + half
if short: emin, emax, stop = q(lo_ - eb * a), q(up_ + eb * a), q(up_ + eb * a + sl * a)
else: emin, emax, stop = q(lo_ - eb * a), q(up_ + eb * a), q(lo_ - eb * a - sl * a)
tp1 = q(T); ref = (emin + emax) / 2
leg = (ref - tp1) if short else (tp1 - ref); tp2 = q(ref - 2 * leg) if short else q(ref + 2 * leg)
tick = D('0.1'); fl = lambda x: (x / tick).to_integral_value(FL) * tick; ce = lambda x: (x / tick).to_integral_value(CE) * tick
lim = ce(ref) if short else fl(ref)
print('ATR', a); print('pivot idx/level', tp, P, 'opposite pivot idx/level', tt, T); print('zone', lo_, up_)
print('entry_min', emin, 'entry_max', emax, 'stop', stop, 'tp1', tp1, 'tp2', tp2); print('entry_ref', ref, 'limit', lim)
print('stop_trigger', fl(stop) if short else ce(stop), 'tp1_trigger', ce(tp1) if short else fl(tp1), 'tp2_trigger', ce(tp2) if short else fl(tp2))
print('RR', leg / abs(ref - stop), 'stop dist ATR', abs(ref - stop) / a)
" "$@"
```

**Q - sizing (adverse edge, stop, partial fraction)** - invoked as `bash qty.sh <sizing edge> <stop> <partial_fill_fraction>`; the `"$@"` at the end passes the arguments to `python -c`.

```bash
python -c "
import sys
from decimal import Decimal as D, ROUND_FLOOR as FL
edge, stop, frac = D(sys.argv[1]), D(sys.argv[2]), D(sys.argv[3])
fee, slip_in, slip_out, step = D('0.0005'), D('0.0001'), D('0.0003'), D('0.001')
fl = lambda x: (x / step).to_integral_value(FL) * step
costs = edge * (fee + slip_in) + stop * (fee + slip_out)
risk_per_unit = abs(edge - stop) + costs
raw = D('10000') * D('0.005') / risk_per_unit
planned = fl(raw); fill = fl(planned * frac); tp1q = fl(fill / 2)
print('costs_per_unit', costs, 'risk_per_unit', risk_per_unit, 'raw', raw)
print('planned', planned, 'fill', fill, 'tp1_qty', tp1q, 'tp2_qty', fill - tp1q)
" "$@"
```

**B - per-leg bookings (side, quantity, entry, then price:quantity:stop|limit legs)** - invoked as `bash book.sh <long|short> <qty> <entry> <price:qty:kind> ...`; the `"$@"` at the end passes the arguments to `python -c`.

```bash
python -c "
import sys
from decimal import Decimal as D
side, qty, entry = sys.argv[1], D(sys.argv[2]), D(sys.argv[3])
legs = [(D(a.split(':')[0]), D(a.split(':')[1]), a.split(':')[2]) for a in sys.argv[4:]]  # price:qty:stop|limit
fee, slip_in, slip_out = D('0.0005'), D('0.0001'), D('0.0003')
sgn = 1 if side == 'long' else -1
entry_leg = -(entry * qty * (fee + slip_in)); realized = entry_leg; gross = D(0); fees = entry * qty * fee; slips = entry * qty * slip_in
print('FILL booking', entry_leg)
for price, q, kind in legs:
    g = sgn * (price - entry) * q; rate = slip_out if kind == 'stop' else slip_in
    leg = g - price * q * (fee + rate); realized += leg; gross += g; fees += price * q * fee; slips += price * q * rate
    print(kind, 'leg', price, q, 'gross', g, 'booking', leg)
print('gross', gross, 'entry_fee', entry * qty * fee, 'exit_fee(s)', fees - entry * qty * fee, 'slippage', slips, 'realized', realized)
" "$@"
```

## v6 fixture facts

Every figure below was recomputed with the standalone Decimal commands G (geometry), Q (sizing) and B (bookings) quoted above; none was copied from simulator output.

### intrabar_both_touched (LONG trigger, baseline-v6 / v5.0.0)

| Fact | Value | Command |
| --- | --- | --- |
| scenario tuple | ("ENTRY_FILLED", "SL", False, 0) | by construction: fill minute 10:05, stop-and-TP1 minute 10:06, stop first |
| confirmed pivot low P / bar t | 117.80 / bar 240 (confirmed at bar 243) | G 0.5 long |
| ATR (Wilder 14, bar 249) | 1.732700754093602462847992746 | G 0.5 long |
| zone P +/- 0.5 ATR | 116.9336496229531987685760036 to 118.6663503770468012314239964 | G 0.5 long |
| entry_min / entry_max | 116.760379547543838522 / 118.839620452456161478 | G 0.5 long |
| limit (zone mid, floor to tick) | 117.80 | G 0.5 long |
| stop / trigger | 116.413839396725118030 / 116.50 | G 0.5 long |
| TP1 / TP2 (trigger) | 123.20 / 128.60 | G 0.5 long |
| planned quantity at equity 10000, risk 0.005 | 19.303 | Q 118.839620452456161478 116.413839396725118030 1.0 |
| entry price and time | 117.80 at 2026-09-11T10:05:59+00:00 (close of minute 10:05, trade low 117.70) | by construction |
| exit price and time | 116.50 (stop trigger, mark open 117.90 above it) at 2026-09-11T10:06:59+00:00 | by construction |
