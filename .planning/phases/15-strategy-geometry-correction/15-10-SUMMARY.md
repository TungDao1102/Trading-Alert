---
phase: 15-strategy-geometry-correction
plan: 10
subsystem: backtest-fixtures
tags: [fixtures, geometry, pivots, phase6, phase7, tdd, tracer]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-08 ratified baseline-v6 values, 15-09 -v4 baselines, 15-03/15-04 pivot geometry in strategy and planner"
provides:
  - "scripts/gen_phase6_fixtures.py build_v6_payloads(): the nine Phase 6 cases and the Phase 7 parity input on the corrected Family A geometry (V-dip pivot history), pure, writers and main() unchanged"
  - "tests/test_phase6_fixture_geometry.py: independent v6 geometry arithmetic and the CRLF-normalized committed comparison (F12)"
  - "tests/test_phase6_fixture_scenarios.py: V6_SCENARIOS and consumer-fact proof of every payload"
  - "'## v6 fixture facts' below: the only source of new consumer literals in plan 15-12"
affects: [15-12]

actuals:
  tokens: 13071
  tasks: 2
  commits: 2
plan_head_before: d4a8f24c2515812f9f53d0b0e24eae9990c72874
plan_head_after: 72c72f59132c87b891b9df425ce2856c2364894c

key-files:
  created:
    - tests/test_phase6_fixture_scenarios.py
  modified:
    - scripts/gen_phase6_fixtures.py
    - tests/test_phase6_fixture_geometry.py

key-decisions:
  - "No ratified or registry value was chosen or tuned: the payload bars and minute paths were designed to fit the ratified baseline-v6 / -v4 values, never the reverse (Phase 12 rule, D-17)"
  - "The SHORT case is the exact mirror of the LONG bars around 250.00 (price' = 250.00 - price, high' = 250.00 - low, low' = 250.00 - high), so its geometry check is the same arithmetic with the roles swapped"
  - "Every case keeps FILL_MINUTE 5 and EXIT_MINUTE 6, so consumer edits that address minute 10:06 keep their meaning"

requirements-completed: [STRAT-02]

duration: ~1h
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 10: v6 fixture payloads Summary

**`build_v6_payloads()` builds every Phase 6 case and the Phase 7 parity input on the corrected pivot geometry (a V-shaped dip gives a confirmed pivot low, the stop sits beyond the outer zone edge), each proven in memory by independent arithmetic, the real planner and its named scenario, while no committed fixture and no existing consumer moved; the CRLF comparison failure (F12) is fixed.**

## Accomplishments

- Task 1 (tracer, commit a410cc3): the LONG trigger payload end to end. The 1H history is a smooth uptrend (bars 0..234), a fall in 0.80 steps to a dip bottom at bar 240 (low 117.80), a recovery to a peak at bar 244 (high 123.20) and a slow pullback; bar 249 (open 121.00, high 121.10, low 118.00, close 119.60) touches the pivot zone. A monotonic uptrend has no confirmed pivot low (15-RESEARCH section 6), so the dip is what makes the geometry testable. The tracer gate (`<verify>` end to end) passed before expansion.
- Task 2 (commit 72c72f5): the SHORT mirror, the missing-mark fallback, invalidation, expiry, partial fill, touch-without-fill, the two -v4 baselines and the parity input; V6_SCENARIOS for all nine cases; the mirrored geometry check, the baseline tests and the hand-derived fact tests.
- Candidate cases carry `baseline-v6` / `v5.0.0`; the baselines carry `baseline-no-trade-v4` / `baseline-simple-trend-v4` at `v5.0.0` (D-26). The nine-key `COST_MODEL` literal is unchanged and equals the ratified cost values of all three sets (asserted against the TOML files).
- F12: the committed-fixture comparison replaces `b"\r\n"` with `b"\n"` on both sides; `test_generator_is_deterministic_and_matches_committed_fixtures`, which failed on this Windows checkout since 15-04, now passes (see deferred-items.md).
- Running `scripts/gen_phase6_fixtures.py` leaves `tests/fixtures/phase6` and `tests/fixtures/phase7` unchanged (`git diff --quiet` exits 0); the generator imports nothing from `src/` or `tests/`.

## Standalone derivation commands

Every fact below is recomputed by one of these three standalone Decimal commands (no import from `src/` or `tests/`; the default prec-28 context equals the pinned context of the product code, and the operation order follows the same formulas). In the tables, `G 0.5 long` means `bash geom.sh 0.5 long` where `geom.sh` holds the first block, and likewise `Q` (qty.sh) and `B` (book.sh).

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

Common to every row: the strategy bars are the V-dip history above (LONG) or its mirror (SHORT); the trigger bar 249 closes 2026-09-11T09:59:59+00:00, so `signal_close_utc` is `2026-09-11T09:59:59+00:00`; the first minute opens 10:00:00 (D-24); a minute opening at 10:MM:00 closes at 10:MM:59, so a fill in minute 10:05 is dated 10:05:59 and an exit in minute 10:06 is dated 10:06:59; the plan expiry is 09:59:59 plus `signal_expiry_hours` 4 = 13:59:59; equity 10000, account risk rate 0.005 (allowed risk 50.000), step 0.001, tick 0.10, fees 0.0005, entry slippage 0.0001, stop slippage 0.0003.

Geometry (command `G 0.5 long`, baseline-v6 values: zone_tolerance_atr 0.5, entry_buffer_atr 0.1, sl_buffer_atr 0.2, pivot widths 3, swing_lookback 20):

| Figure | Value |
| --- | --- |
| confirmed pivot low P, bar | 117.80, bar 240 (confirmed at bar 243, inside the search window 230..246) |
| confirmed opposite pivot high (TP1), bar | 123.20, bar 244 (confirmed at bar 247; no later than bar 248) |
| ATR (Wilder 14, bar 249) | 1.732700754093602462847992746 |
| zone P +/- 0.5 ATR | 116.9336496229531987685760036 to 118.6663503770468012314239964 |
| entry_min / entry_max | 116.760379547543838522 / 118.839620452456161478 |
| entry reference (mid) and limit (floor to tick) | 117.800000000000000000 / 117.80 |
| stop / stop trigger (ceil to tick for LONG) | 116.413839396725118030 / 116.50 |
| TP1 / TP2 | 123.20 / 128.60 (TP2 = ref + 2 x (TP1 - ref)) |
| RR to TP1 | 3.895652485896798619547327287 (>= minimum_rr 2.0) |
| entry-ref to stop distance in ATR | 0.8 (>= min_stop_atr 0.5) |
| SHORT (command `G 0.5 short`) | P 132.20, TP1 126.80, entry_min / entry_max 131.160379547543838522 / 133.239620452456161478, stop 133.586160603274881970 (trigger 133.50, floor to tick), TP2 121.40, limit 132.20 |
| simple-trend (command `G 1.0 long`) | entry_min / entry_max 115.894029170497037291 / 119.705970829502962709, stop 115.547489019678316798 (trigger 115.60), TP1 123.20, TP2 128.60, RR 2.397324606705722226615522470 (>= minimum_rr 0.5), stop at 1.3 ATR |

Per case (first record; every case produces exactly one record). Quantities come from command Q, bookings from command B.

| Case | Scenario tuple | Dir | Limit / entry price and time | Stop trigger / exit price and time | TP1 / TP2 | Planned / filled / TP1 qty | Touches | resolved_at | Command(s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| intrabar_both_touched | ("ENTRY_FILLED", "SL", False, 0) | LONG | 117.80 / 117.80 at 10:05:59 (trade low 117.70 = limit - tick; mark low 117.75 stays above the stop) | 116.50 / 116.50 at 10:06:59 (mark low 116.40 reaches the stop, mark open 117.90 above it, so no gap; stop-first although high 123.30 also reaches TP1) | 123.20 / 128.60 | 19.303 / 19.303 / 9.651 (never booked) | 0 | 10:06:59 | G 0.5 long; Q 118.839620452456161478 116.413839396725118030 1.0 |
| intrabar_both_touched_short | ("ENTRY_FILLED", "SL", False, 0) | SHORT | 132.20 / 132.20 at 10:05:59 (trade high 132.30) | 133.50 / 133.50 at 10:06:59 (mark high 133.60) | 126.80 / 121.40 | 19.147 / 19.147 / 9.573 | 0 | 10:06:59 | G 0.5 short; Q 131.160379547543838522 133.586160603274881970 1.0 |
| intrabar_missing_fallback | ("ENTRY_FILLED", "SL", True, 0) | LONG | 117.80 / 117.80 at 10:05:59 | 116.50 / 116.50 at 10:59:59 (mark minutes missing from 10:06; bar 250 range low 116.20 reaches the stop; filled inside the bar, so the price is the trigger) | 123.20 / 128.60 | 19.303 / 19.303 / 9.651 | 0 | 10:59:59 | as row 1 |
| limit_touch_no_fill | ("EXPIRED", None, False, 3) | LONG | 117.80 / none (trade low 117.80 at minutes 10, 11 and 30 equals the limit, not limit - tick) | none | 123.20 / 128.60 | 19.303 / none / none | 3 (run_summary touch_no_fill_total 3) | 13:59:59 | G 0.5 long; Q as row 1 |
| limit_partial_fill | ("PARTIAL_FILL", "TP2", False, 0) | LONG | 117.80 / 117.80 at 10:05:59 | 116.50 / TP2 128.60 at 10:07:59 (TP1 123.20 at 10:06:59: mark high 123.30, low 117.80 above the stop; TP2: mark high 128.90) | 123.20 / 128.60 | 19.303 / 9.651 / 4.825 (remainder 4.826), partial_fill_fraction 0.5 | 0 | 10:07:59 | Q 118.839620452456161478 116.413839396725118030 0.5 |
| limit_expiry | ("EXPIRED", None, False, 0) | LONG | 117.80 / none (minutes rest at 119.50) | none | 123.20 / 128.60 | 19.303 / none / none | 0 | 13:59:59 | as row 4 |
| invalidation_cancels_entry | ("INVALIDATION_CANCEL", None, False, 0) | LONG | 117.80 / none | none (bar 250 closes 116.00, below the CANDLE_CLOSE level = stop 116.413839396725118030) | 123.20 / 128.60 | 19.303 / none / none | 0 | 10:59:59 | as row 4 |
| baselines/no_trade (baseline-no-trade-v4) | ("REJECT", None, False, 0), reason RR_TOO_LOW | LONG | no plan | no plan | TP1 123.20 gives RR 3.8956 < minimum_rr 100 | none | 0 | 09:59:59 (the signal close) | G 0.5 long (invariants and RR) |
| baselines/simple_trend (baseline-simple-trend-v4) | ("ENTRY_FILLED", "SL", False, 0) | LONG | 117.80 / 117.80 at 10:05:59 | 115.60 / 115.60 at 10:06:59 (mark low 115.50) | 123.20 / 128.60 | 11.566 / 11.566 / 5.783 | 0 | 10:06:59 | G 1.0 long; Q 119.705970829502962709 115.547489019678316798 1.0 |
| phase7/parity_overlapping_history | ("ENTRY_FILLED", "SL", False, 0) | LONG | identical payload to intrabar_both_touched (asserted equal in a test) | identical | identical | identical | 0 | 10:06:59 | as row 1 |

Fallback coverage-note timestamp (intrabar_missing_fallback): the first mark minute that is missing opens at `2026-09-11T10:06:00+00:00` (minute 6 of the hour), so the note is `mark_price_1m_missing_from_2026-09-11T10:06:00+00:00; resolved_at_strategy_bar_close_2026-09-11T10:59:59+00:00 from the trade-price bar range, stop first`; `run_summary.fallback_count` is 1.

Sizing note: the SHORT quantity (19.147) is smaller than the LONG one (19.303) although the geometry mirrors, because sizing uses the adverse zone edge (LONG entry_max 118.84, SHORT entry_min 131.16) and the modeled cost is price-aware (the SHORT prices are higher). Command Q takes the edge as its first argument.

Money per case (command B; the booked `Booking` amounts and the trade record fields):

| Case | Command | FILL booking | Exit booking(s) | gross_pnl | entry_fee | exit_fee | slippage_amount | realized_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| intrabar_both_touched, intrabar_missing_fallback, parity | `B long 19.303 117.80 116.50:19.303:stop` | -1.364336040 | EXIT -26.892939600 | -25.09390 | 1.136946700 | 1.124399750 | 0.902029190 | -28.257275640 |
| intrabar_both_touched_short | `B short 19.147 132.20 133.50:19.147:stop` | -1.518740040 | EXIT -26.935999600 | -24.89110 | 1.265616700 | 1.278062250 | 1.019960690 | -28.454739640 |
| limit_partial_fill (TP ladder) | `B long 9.651 117.80 123.20:4.825:limit 128.60:4.826:limit` | -0.682132680 | TP1 25.698336000, EXIT 51.748425840 | 78.17580 | 0.568443900 | 0.607531800 | 0.235195140 | 76.764629160 |
| baselines/simple_trend | `B long 11.566 117.80 115.60:11.566:stop` | -0.817484880 | EXIT -26.514823680 | -25.44520 | 0.681237400 | 0.668514800 | 0.537356360 | -27.332308560 |

The no-trade baseline needs no money row (one REJECT record, no plan). `funding_amount` is 0 in every filled case: no funding instant (00:00, 08:00, 16:00 UTC) falls inside a position's open stretch.

### What changed against the baseline-v5 fixtures (for 15-12)

| Consumer literal today | New value |
| --- | --- |
| entry 121.50 / stop 121.20 / planned 32.071 (simulator, cost parity) | 117.80 / 116.50 / 19.303 |
| SHORT limit 128.50, stop 128.80 | 132.20, 133.50 (planned 19.147) |
| partial fill 16.035 of 32.071, TP1 qty 8.017, TP1 125.60, TP2 129.70 (TP2 qty 8.018) | 9.651 of 19.303, TP1 qty 4.825, TP1 123.20, TP2 128.60 (TP2 qty 4.826) |
| `limit_touch_no_fill` planned_quantity 32.071, 3 touches | 19.303, 3 touches |
| `intrabar_missing_fallback` and `invalidation_cancels_entry` have two records (the second a PENDING_AT_DATA_END follow-up) | one record each: the stop now lies beyond the zone edge, so a bar range that reaches the stop is outside the zone and bar 250 cannot raise a follow-up setup; the scenario tuples (first record) keep their meaning |
| experiment drift test sets the 10:06 mark low to "121.50" to avoid the stop | any value above the new stop trigger 115.60, for example "117.80" |
| `parameter_set_id == "baseline-simple-trend-v3"`, `baseline-no-trade-v3`, `baseline-v5`, `v4.0.0` in fixture identity tests | `baseline-simple-trend-v4`, `baseline-no-trade-v4`, `baseline-v6`, `v5.0.0` |

Engine-derived regression pins (NOT facts: they come from the engine, and 15-12 re-pins `REGRESSION_SNAPSHOTS` and the parity digest from the files it writes; listed only so a reader can see the payloads are stable). sha256 of the whole `run` output:

| Payload | Digest |
| --- | --- |
| intrabar_both_touched and parity_overlapping_history | 04db4983b254951ec0eba4946787d415b0d9471ed259e6aec5ce88bb664433c3 |
| intrabar_both_touched_short | 0d50102b4b8a567bc014f6b015ebb796e51611dd6dfd43d53c0874f95c40ee94 |
| intrabar_missing_fallback | 7c7b3bf2dcf231eaf7c7fee43e9bbf6857195b80027eb80e6d1f1b66b5516a30 |
| limit_touch_no_fill | 7458ac0e6f34cb50317e225bb004b55edeac97720193347c5ae06209c7f50c8c |
| limit_partial_fill | 3a7039dcf55851952dcc57918983a457d49710e12dd5534979477b340597f24a |
| limit_expiry | fb60c4d61514ba557659de1ec713f5f5579b8fd60b1ec9b64a4d4a9e47120002 |
| invalidation_cancels_entry | 74cea2d2bce3fee34ead91b2e568db41492ff391212eb82c9505f211ec22833e |
| baselines/no_trade | 79621110930faa9a355d087849a301b9b0dee105330397206d9213efb8c766c1 |
| baselines/simple_trend | 15f56a1a524d3c2361ac6cf077c82478c03446380bdaf0ed702cb5fb95689a41 |

## Regeneration inventory

none in this plan: no committed fixture moved (`git diff --quiet -- tests/fixtures/phase6 tests/fixtures/phase7` exits 0 after running the generator); the regeneration, the consumer updates and the re-pinning of the digests above are in 15-12. No pin in `tests/fixtures/phase4/parameters.json`, no params file and no src file changed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Plan imprecision] The NO_TRADE count identity**
- **Found during:** Task 1
- **Issue:** the plan states "sum of no_trade_counts = number of strategy bars - 1". The engine evaluates only the closes inside the data window (bars 240..249, plus bar 250 where present); closes before the window start are warm-up and not counted, so the sum is 9 (10 with bar 250), not 249.
- **Fix:** the test asserts `sum(no_trade_counts) == evaluated closes - 1 + rejects` (the RR_TOO_LOW reject of the no-trade baseline adds its own count), and proves the stronger claim "NO_TRADE on every earlier bar" two ways: an independent own-loop scan of every bar 14..248 (no bar's extreme lies inside the zone of the pivot known at its close) and the real `evaluate` on the prefixes of bars 230..248.
- **Files modified:** tests/test_phase6_fixture_scenarios.py, tests/test_phase6_fixture_geometry.py
- **Commit:** a410cc3, 72c72f5

**2. [Rule 3 - Missing referenced helper] No independent Wilder ATR in the geometry test file**
- **Found during:** Task 1
- **Issue:** the plan names "the independent Wilder ATR already in the file"; `tests/test_phase6_fixture_geometry.py` had none (it read plan prices from the real planner).
- **Fix:** wrote `_own_atr_series` (SMA seed of 14 true ranges, then (n-1)/n smoothing) in the test module; it imports nothing from `src.core`.
- **Commit:** a410cc3

**3. [Explained, not a defect] Record counts of two cases**
- `intrabar_missing_fallback` and `invalidation_cancels_entry` now produce one record instead of two; see "What changed" above. The scenario tuple of the first record keeps its meaning.

## Auth gates

None.

## Known Stubs

None.

## Threat Flags

None. T-15-27 (self-certified facts) mitigated: independent pivot, ATR, zone, stop, TP1, RR and guard arithmetic with TOML-read parameter values; every price, quantity and money fact recomputed by a quoted standalone command and then compared to engine output (not the reverse); scenario tuples held to today's per-case meaning; 15-12 writes the files from the same `build_v6_payloads()` and the LF-normalized generator comparison binds files to payloads. T-15-SC accepted (no installs).

## Verification

- `pytest tests/test_phase6_fixture_scenarios.py tests/test_phase6_fixture_geometry.py tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_determinism.py tests/test_backtest_engine_strategy.py tests/test_paper_parity.py tests/test_cost_parity.py`: 355 passed.
- `python scripts/gen_phase6_fixtures.py` then `git diff --quiet -- tests/fixtures/phase6 tests/fixtures/phase7`: exit 0 (the generator rewrites the working-tree fixture files with LF; git stores LF, so content is identical).
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 388 files formatted; `mypy src`: no issues in 149 source files.
- The scenario test collects 10 parametrized cases (nine Phase 6 cases plus the parity key); `V6_SCENARIOS` has nine entries.
- Targeted suites only, foreground, no background process left.

## Self-Check: PASSED

- FOUND: scripts/gen_phase6_fixtures.py (def build_v6_payloads), tests/test_phase6_fixture_geometry.py, tests/test_phase6_fixture_scenarios.py (V6_SCENARIOS), this SUMMARY with "## v6 fixture facts"
- FOUND: commits a410cc3, 72c72f5
- `git diff --stat` of the two task commits lists only the generator, the two test files and this SUMMARY
