# Hand arithmetic behind the Phase 14 golden cases

Plan 14-13 (D-24, F-602, F-805, F-608). Every expected value comes from an independent
Decimal computation with no project imports, never from the output of the code under test.
The numbers in this file were produced by the standalone one-liners pasted into each section
(plain `python -c` with `from decimal import Decimal`, nothing from `src/`, `tests/` or
`scripts/`), and the `expected.json` of every case was then written by hand from the section.
Nothing in the repository writes an `expected.json`: `scripts/gen_phase14_fixtures.py` writes
`input.json` files only, and `tests/test_phase14_fixture_generator.py` fails if it ever
writes anything else. Any change to a number needs a new derivation in this file first; do not
regenerate an expectation by running the simulator and pasting the result.

Each golden test runs `src.backtest.simulator.run` on `input.json` and compares the listed
fields of every trade record, and the listed `run_summary` counters, with `expected.json`
numerically (Decimal equality for amounts, parsed datetimes for times), so the scale spelling
of a Decimal (`98` versus `98.00`) can never cause a false failure.

## Common inputs

| Symbol | Value |
|--------|-------|
| symbols | synthetic `BTCUSDT` at prices around 100 (the daily-loss case adds ADAUSDT, BNBUSDT, DOGEUSDT, LTCUSDT) |
| parameter set | `trend-pullback` / `baseline-v5` (strategy v4.0.0), plans are scripted (the strategy front end is bypassed) |
| equity / risk_rate | 10000 / 0.005, so allowed_risk = 50 |
| fee_rate_entry / fee_rate_exit | 0.0005 / 0.0005 (taker, D036) |
| expected_slippage | 0.0001 (entry leg, TP1 leg, TP2 leg) |
| exit_slippage_rate | 0.0003 (stop exits and END_OF_DATA closes, D-10) |
| min_stop_distance_rate / max_cost_to_risk | 0.003 / 0.15 |
| minimum_risk_utilization_after_rounding | 0.6 |
| price tick / quantity step / min quantity / min notional | 0.10 / 0.001 / 0.001 / 5 |
| TP1 quantity fraction | 0.5 of the filled quantity, floored to the step (D-27); TP2 closes the remainder; the stop never moves |
| partial_fill_fraction | 1.0 (D038), so the filled quantity equals the planned quantity |
| signal close S | 2026-01-05 09:59:59.999 UTC (close of the 1h bar 09:00 to 09:59:59.999) |
| 1m rows | the minute opening `hh:mm:00` closes `hh:mm:59.999`; the first minute of every case opens at 10:00:00 or later |
| data window | 2026-01-05 00:00 to 12:00 UTC unless a case says otherwise |
| funding rows | 2026-01-04 16:00, 2026-01-05 00:00, 08:00 and 16:00 at rate 0.0001 mark 100 (all outside every holding window), plus the instants a case lists |
| LONG base plan | zone 99.00 to 101.00, stop 98.00, TP1 104.00, TP2 108.00, expiry 4 h |
| SHORT base plan | zone 99.00 to 101.00, stop 102.00, TP1 96.00, TP2 92.00, expiry 4 h |

## Formulas (all Decimal)

- Limit price = zone mid = (entry_min + entry_max) / 2 = 100.00, already on the tick grid
  (LONG floors to the tick, SHORT ceils; both give 100.0).
- Sizing entry = the adverse zone edge (LONG entry_max = 101, SHORT entry_min = 99); stop
  distance = |sizing entry - stop|; cost per unit = sizing entry x 0.0006 + stop x 0.0008;
  risk_per_unit = stop distance + cost per unit; raw quantity = allowed_risk / risk_per_unit;
  quantity = floor(raw / 0.001) x 0.001; realized_risk = quantity x risk_per_unit. The notional
  check (quantity x zone mid 100 >= 5) and the utilization check (realized_risk / 50 >= 0.6) pass in
  every case. The guards pass: stop distance / sizing entry >= 0.003 and cost / risk_per_unit <= 0.15.
- Trade-through (D-07): a LONG fills on the first trade-price minute whose low is at or below
  limit - tick (99.9); a SHORT on the first minute whose high is at or above limit + tick (100.1).
  A minute that only reaches the limit (low or high exactly 100.0) is a touch: it adds 1 to
  `touch_no_fill_count` and never fills. The fill price is the limit, with no improvement even when
  the minute opens beyond it; the fill time is the close of the deciding minute (D-08).
- Triggers (D-10, D-12, D-33): stop and take-profit are judged on mark-price minutes. A LONG stop
  triggers when the mark low is at or below the stop, a SHORT stop when the mark high is at or above
  it; take-profit uses the other extreme. The stop is judged first, so a minute that reaches both
  the stop and a take-profit stops the whole position. On the fill minute only the stop can trigger.
  Exit price = the trigger price; a stop priced from a minute that opens beyond the trigger books
  the adverse of trigger and minute open and raises `gap_through_stop`.
- TP1 quantity = floor(0.5 x quantity / 0.001) x 0.001 booked at the TP1 trigger; the remainder is
  closed by TP2 at its trigger or by the unchanged stop (D-11, D-27).
- Per-leg costs: fee = price x leg quantity x 0.0005 on every leg; slippage = price x leg quantity x
  0.0001 on the entry, TP1 and TP2 legs and x 0.0003 on a stop or END_OF_DATA leg.
- Gross = sign x (exit price - entry price) x leg quantity per leg, sign +1 LONG and -1 SHORT.
- Funding (D-14, D-36): funding = -sign x open quantity x row mark price x row rate at every actual
  funding instant with fill time <= instant < exit time, using the quantity open at that instant
  (the post-TP1 remainder after TP1). A LONG pays a positive rate and receives a negative one.
- realized_pnl = gross - entry fee - exit fees - slippage + funding. R = realized_pnl / realized_risk
  (D-20; the filled quantity equals the planned one, so realized_risk is the sized figure).

## signal_bar_touch_no_fill

LONG, base plan, expiry 4 h. The 1h signal bar (09:00 to 09:59:59.999) has open 100.5, high
101.5, low 97.5, close 100.4: its own range spans the limit 100.0 and the stop 98.0. A simulator that
examined the signal bar would fill and stop the plan inside it (the audit worked example, F-120);
the engine must book neither, because the first 1m minute opens at 10:00 and every minute of the
plan starts at bar N+1.

1. Limit = 100.0. Sizing entry 101; stop distance 3; cost = 101 x 0.0006 + 98 x 0.0008 = 0.0606 +
   0.0784 = 0.1390; risk_per_unit = 3.1390; raw = 50 / 3.1390 = 15.92863969...; quantity 15.928.
2. realized_risk = 15.928 x 3.1390 = 49.997992; utilization 0.99995984; stop rate 3/101 = 0.0297;
   cost ratio 0.1390/3.1390 = 0.04428. All guards pass. TP1 quantity = floor(7.964) = 7.964 (unused).
3. Trade minute 10:10 has low 99.9 = 100.0 - 0.1: fill at 100.0, time 10:10:59.999. The minutes
   10:00 to 10:09 have low 100.6, above the limit. The fill minute's mark low is 99.95, above the stop
   98.0, so nothing triggers on it.
4. Mark minute 10:11 has open 100.2 and low 97.9 <= 98.0: stop at 98.0 (no gap: 100.2 > 98.0), time
   10:11:59.999. The 1h bar 10:00 to 10:59:59.999 closes after the position is closed.
5. Costs: gross = (98 - 100) x 15.928 = -31.856; entry fee = 100 x 15.928 x 0.0005 = 0.7964; exit fee
   = 98 x 15.928 x 0.0005 = 0.780472; slippage = 100 x 15.928 x 0.0001 + 98 x 15.928 x 0.0003 =
   0.15928 + 0.4682832 = 0.6275632; funding 0 (the 08:00 and 16:00 rows are outside the 1 minute hold,
   count 0).
6. realized_pnl = -31.856 - 0.7964 - 0.780472 - 0.6275632 = -34.0604352; R = -34.0604352 / 49.997992 =
   -0.68123606...

Check (standalone):

```bash
python -c "from decimal import Decimal as D;e=D('101');s=D('98');rpu=e-s+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');g=(s-D(100))*q;ef=D(100)*q*D('0.0005');xf=s*q*D('0.0005');sl=D(100)*q*D('0.0001')+s*q*D('0.0003');p=g-ef-xf-sl;print(rpu,q,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: ACCEPTED, one record: ENTRY_FILLED 100.0 x 15.928 at 10:10:59.999, SL 98.0 at 10:11:59.999,
gross -31.856, entry fee 0.7964, exit fee 0.780472, slippage 0.6275632, funding 0, realized_pnl
-34.0604352, realized_risk 49.997992, touch_no_fill_count 0, fallback_applied false. Run summary:
all counters 0, no NO_TRADE counts.

## trade_through_vs_touch

SHORT, base SHORT plan (zone 99.00 to 101.00, stop 102.00), expiry 4 h. Two minutes only touch the
limit, the third trades through it by exactly one tick (D-07).

1. Limit = 100.0 (the mid, ceiled to the tick). Sizing entry = entry_min 99; stop distance =
   102 - 99 = 3; cost = 99 x 0.0006 + 102 x 0.0008 = 0.0594 + 0.0816 = 0.1410; risk_per_unit =
   3.1410; raw = 50 / 3.1410 = 15.91849729...; quantity 15.918; realized_risk = 15.918 x 3.1410 =
   49.998438; utilization 0.99996876; stop rate 3/99 = 0.0303; cost ratio 0.1410/3.1410 = 0.04489.
2. Trade minutes 10:00 to 10:04 have a high of 99.4, below the limit. Minute 10:05 has a high of
   exactly 100.0 (touch 1) and minute 10:06 a high of exactly 100.0 (touch 2): neither fills, because
   a SHORT needs a high of at least limit + tick = 100.1. Minute 10:07 has a high of 100.1: fill at
   100.0, time 10:07:59.999. The fill minute's mark high is 100.05, below the stop 102.0.
3. Mark minute 10:08 has open 99.0 and high 102.2 >= 102.0: stop at max(102.0, 99.0) = 102.0, time
   10:08:59.999 (no gap).
4. gross = (100 - 102) x 15.918 = -31.836; entry fee = 100 x 15.918 x 0.0005 = 0.7959; exit fee =
   102 x 15.918 x 0.0005 = 0.811818; slippage = 100 x 15.918 x 0.0001 + 102 x 15.918 x 0.0003 =
   0.15918 + 0.4870908 = 0.6462708; funding 0 (no instant in the 1 minute hold).
5. realized_pnl = -31.836 - 0.7959 - 0.811818 - 0.6462708 = -34.0899888; R = -34.0899888 / 49.998438
   = -0.68182107...

Check (standalone):

```bash
python -c "from decimal import Decimal as D;e=D('99');s=D('102');rpu=s-e+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');g=(D(100)-s)*q;ef=D(100)*q*D('0.0005');xf=s*q*D('0.0005');sl=D(100)*q*D('0.0001')+s*q*D('0.0003');p=g-ef-xf-sl;print(rpu,q,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: one record, ENTRY_FILLED 100.0 x 15.918 at 10:07:59.999, SL 102.0 at 10:08:59.999, touch_no_fill_count
2, realized_pnl -34.0899888. Run summary: touch_no_fill_total 2, everything else 0.

## hold_to_sl

LONG, base plan, with 1h strategy bars N+1 to N+4 (10:00, 11:00, 12:00, 13:00) in the input and a
continuous minute series 10:00 to 13:59 (240 minutes) on both trade and mark prices. The
position is carried across three bar closes before the stop (no time stop, D-06).

1. Sizing as in `signal_bar_touch_no_fill`: quantity 15.928, realized_risk 49.997992.
2. Minutes 10:00 to 10:29 have a trade low of 100.6; minute 10:30 has a low of 99.9: fill at 100.0,
   time 10:30:59.999 (bar N+1). The fill minute's mark low is 99.95 (above the stop).
3. The mark series stays between 100.6 and 101.2 from 10:31 to 13:19: below TP1 104.0 and above the
   stop 98.0, so nothing triggers at the closes of bars N+1 (10:59:59.999), N+2 (11:59:59.999) and N+3
   (12:59:59.999).
4. Mark minute 13:20 (bar N+4) has open 100.0 and low 97.9: stop at min(98.0, 100.0) = 98.0, time
   13:20:59.999. The funding rows at 08:00 and 16:00 are outside [10:30:59.999, 13:20:59.999): funding 0.
5. Same costs as `signal_bar_touch_no_fill`: gross -31.856, entry fee 0.7964, exit fee 0.780472,
   slippage 0.6275632, realized_pnl -34.0604352.

Check (standalone):

```bash
python -c "from decimal import Decimal as D;e=D('101');s=D('98');rpu=e-s+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');g=(s-D(100))*q;ef=D(100)*q*D('0.0005');xf=s*q*D('0.0005');sl=D(100)*q*D('0.0001')+s*q*D('0.0003');p=g-ef-xf-sl;print(rpu,q,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: exactly one terminal record: ENTRY_FILLED at 10:30:59.999, SL 98.0 at 13:20:59.999, realized_pnl
-34.0604352.

## tp1_then_tp2

LONG, zone 99.00 to 101.00, stop 98.50, TP1 104.00, TP2 108.00. The stop 98.50 is chosen so the
quantity (18.943) has an odd number of steps and the TP1 half has to be floored (D-27).

1. Limit = 100.0. Sizing entry 101; stop distance 2.5; cost = 101 x 0.0006 + 98.5 x 0.0008 = 0.0606 +
   0.0788 = 0.1394; risk_per_unit = 2.6394; raw = 50 / 2.6394 = 18.94369932...; quantity 18.943;
   realized_risk = 18.943 x 2.6394 = 49.9981542; utilization 0.999963084; stop rate 2.5/101 = 0.02475;
   cost ratio 0.1394/2.6394 = 0.05282.
2. TP1 quantity = floor(0.5 x 18.943 = 9.4715 to the step 0.001) = 9.471; the remainder is 18.943 -
   9.471 = 9.472. Notional 104 x 9.471 is far above the minimum of 5.
3. Fill: trade minute 10:05 has low 99.9, time 10:05:59.999. Mark minute 10:15 has high 104.2 >= 104.0
   and low 101.4 above the stop 98.5, and a high below TP2 108.0: TP1 books 9.471 at 104.0 at
   10:15:59.999 and the stop level stays 98.5. Mark minutes 10:16 to 10:39 stay at 103.0 (+-0.2). Mark
   minute 10:40 has high 108.3 >= 108.0: TP2 books 9.472 at 108.0 at 10:40:59.999.
4. gross = (104 - 100) x 9.471 + (108 - 100) x 9.472 = 37.884 + 75.776 = 113.66.
   entry fee = 100 x 18.943 x 0.0005 = 0.94715.
   exit fees = 104 x 9.471 x 0.0005 + 108 x 9.472 x 0.0005 = 0.492492 + 0.511488 = 1.00398.
   slippage (entry, TP1 and TP2 all at 0.0001) = 100 x 18.943 x 0.0001 + 104 x 9.471 x 0.0001 +
   108 x 9.472 x 0.0001 = 0.18943 + 0.0984984 + 0.1022976 = 0.390226. Funding 0.
5. realized_pnl = 113.66 - 0.94715 - 1.00398 - 0.390226 = 111.318644; R = 111.318644 / 49.9981542 =
   2.22645507...

Check (standalone):

```bash
python -c "from decimal import Decimal as D;e=D('101');s=D('98.5');rpu=e-s+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');a=(q/2//D('0.001'))*D('0.001');b=q-a;g=(D(104)-D(100))*a+(D(108)-D(100))*b;ef=D(100)*q*D('0.0005');xf=(D(104)*a+D(108)*b)*D('0.0005');sl=D(100)*q*D('0.0001')+(D(104)*a+D(108)*b)*D('0.0001');p=g-ef-xf-sl;print(rpu,q,a,b,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: ENTRY_FILLED 100.0 x 18.943 at 10:05:59.999; TP1 9.471 at 104.0 at 10:15:59.999; final exit TP2 at
108.0 at 10:40:59.999; realized_pnl 111.318644.

## tp1_then_sl

LONG, base plan (the audit F-102 worked example): TP1 takes half, the stop does not move, and the
remainder stops out at the original stop.

1. Sizing as in `signal_bar_touch_no_fill`: quantity 15.928, realized_risk 49.997992. TP1 quantity =
   floor(7.964) = 7.964; the remainder is 7.964.
2. Fill at 100.0 at 10:05:59.999. Mark minute 10:15 has high 104.3 >= 104.0 (low 101.4): TP1 books 7.964
   at 104.0 at 10:15:59.999. Mark minutes 10:16 to 10:49 stay near 103.0. Mark minute 10:50 has open
   103.0 and low 97.9 <= 98.0: the remainder stops at min(98.0, 103.0) = 98.0 at 10:50:59.999 (the stop
   stayed at 98.0, it did not move to breakeven).
3. gross = (104 - 100) x 7.964 + (98 - 100) x 7.964 = 31.856 - 15.928 = 15.928.
   entry fee = 0.7964; exit fees = 104 x 7.964 x 0.0005 + 98 x 7.964 x 0.0005 = 0.414128 + 0.390236 =
   0.804364.
   slippage = entry 100 x 15.928 x 0.0001 = 0.15928; TP1 104 x 7.964 x 0.0001 = 0.0828256; stop
   98 x 7.964 x 0.0003 = 0.2341416; total 0.4762472. Funding 0.
4. realized_pnl = 15.928 - 0.7964 - 0.804364 - 0.4762472 = 13.8509888.
   R = 13.8509888 / 49.997992 = 0.27703090... (a half-size win and a half-size loss: about 0.28 R).

Check (standalone):

```bash
python -c "from decimal import Decimal as D;e=D('101');s=D('98');rpu=e-s+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');a=(q/2//D('0.001'))*D('0.001');b=q-a;g=(D(104)-D(100))*a+(s-D(100))*b;ef=D(100)*q*D('0.0005');xf=(D(104)*a+s*b)*D('0.0005');sl=D(100)*q*D('0.0001')+D(104)*a*D('0.0001')+s*b*D('0.0003');p=g-ef-xf-sl;print(rpu,q,a,b,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: ENTRY_FILLED at 10:05:59.999; TP1 7.964 at 104.0 at 10:15:59.999; final exit SL at 98.0 at
10:50:59.999; realized_pnl 13.8509888.

## expiry_before_fill

LONG, base plan with `expiry_hours` 1, so expiry = S + 1 h = 10:59:59.999. The limit is never traded through
while the plan is alive.

1. Sizing as in `signal_bar_touch_no_fill` (the plan is sized and rests): planned quantity 15.928.
2. Trade minutes 10:00 to 10:59 have a low of 100.6, above the limit 100.0 (no touch, no fill). The
   last eligible minute is 10:59: it closes at 10:59:59.999, equal to the expiry, and the rule is
   "minute close <= expiry". Minute 11:00 has a low of 99.8 and WOULD trade through, but it closes at
   11:00:59.999, after the expiry, so it is ignored (this is the boundary of D-04 and D-33).
3. The plan ends EXPIRED at the expiry instant 10:59:59.999. No entry, exit or cost fields exist.

No cost arithmetic applies; the sizing check is the same command as in `signal_bar_touch_no_fill`.

Result: one record, entry_kind EXPIRED, resolved at 10:59:59.999, every trade field null, planned
quantity 15.928, touch_no_fill_count 0. Run summary: all counters 0.

## g3_fill_before_expiry

Gap G3 (D-04): `signal_expiry_hours` 4, so the expiry is S + 4 h = 13:59:59.999. LONG, base plan.

1. Sizing as in `signal_bar_touch_no_fill`: quantity 15.928.
2. The trade-through is at minute 11:20 (bar N+2 = 11:00 to 11:59:59.999): low 99.9, which closes at
   11:20:59.999, before the expiry. Fill at 100.0 at 11:20:59.999.
3. Mark minute 11:40 has open 101.0 and low 97.9: stop at 98.0 at 11:40:59.999.
4. Same costs as `signal_bar_touch_no_fill`: realized_pnl -34.0604352.

Check (standalone), identical to the one in `signal_bar_touch_no_fill`:

```bash
python -c "from decimal import Decimal as D;e=D('101');s=D('98');rpu=e-s+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');g=(s-D(100))*q;ef=D(100)*q*D('0.0005');xf=s*q*D('0.0005');sl=D(100)*q*D('0.0001')+s*q*D('0.0003');p=g-ef-xf-sl;print(rpu,q,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: ENTRY_FILLED at 11:20:59.999, SL at 11:40:59.999, realized_pnl -34.0604352.

## g3_expire_after

The same plan as `g3_fill_before_expiry` (expiry 13:59:59.999), but the price first reaches the limit in bar
N+5 (14:00 to 14:59:59.999).

1. Sizing as in `signal_bar_touch_no_fill`: planned quantity 15.928.
2. Trade minutes 10:00 to 14:29 have a low of 100.6. Minute 14:30 has a low of 99.9 and would trade
   through, but it closes at 14:30:59.999, after the expiry 13:59:59.999, so it is ignored. The last
   eligible minute (13:59) closes exactly at the expiry.
3. The plan ends EXPIRED at 13:59:59.999 (the data window runs to 15:00, the minutes to 14:35).

Result: one record, entry_kind EXPIRED, resolved at 13:59:59.999, every trade field null, planned
quantity 15.928, touch_no_fill_count 0. Together with `g3_fill_before_expiry` this is the multi-bar
test the Phase 6 gap G3 asked for: one limit entry fills before `signal_expiry_hours`, one expires after it.

## stop_first_tie

LONG, base plan. One mark minute reaches both the stop and TP1 (D-12).

1. Sizing as in `signal_bar_touch_no_fill`: quantity 15.928. Fill at 100.0 at 10:05:59.999 (trade low 99.9;
   the fill minute's mark low is 100.5).
2. Mark minute 10:06 has open 101.0, high 104.5 >= TP1 104.0 and low 97.9 <= stop 98.0. The stop is judged
   first, so the whole position of 15.928 exits at the stop min(98.0, 101.0) = 98.0 at 10:06:59.999. No TP1
   leg is booked (tp1 fields null).
3. Same costs as `signal_bar_touch_no_fill`: realized_pnl -34.0604352. No gap (101.0 > 98.0).

Check (standalone), identical to the one in `signal_bar_touch_no_fill`:

```bash
python -c "from decimal import Decimal as D;e=D('101');s=D('98');rpu=e-s+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');g=(s-D(100))*q;ef=D(100)*q*D('0.0005');xf=s*q*D('0.0005');sl=D(100)*q*D('0.0001')+s*q*D('0.0003');p=g-ef-xf-sl;print(rpu,q,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: ENTRY_FILLED, exit SL 98.0 at 10:06:59.999, tp1 fields null, realized_pnl -34.0604352.

## gap_through_limit

LONG, base plan. The fill minute gaps down through the limit (D-07): no price improvement.

1. Sizing as in `signal_bar_touch_no_fill`: quantity 15.928; TP1 quantity 7.964; remainder 7.964.
2. Trade minute 10:05 opens at 98.5 (1.5 below the limit 100.0) with a low of 98.4 <= 99.9: it trades
   through. The fill price is the limit, 100.0, not 98.5 (conservative: a gap through the limit gets no
   price improvement), at 10:05:59.999. The fill minute's mark low is 98.4, above the stop 98.0.
3. Mark minutes 10:06 to 10:19 stay near 99.0. Mark minute 10:20 has high 108.5, reaching TP1 104.0 and
   TP2 108.0 together (low 98.9, above the stop): TP1 books 7.964 at 104.0 and then TP2 books 7.964 at
   108.0, both at the minute close 10:20:59.999.
4. gross = (104 - 100) x 7.964 + (108 - 100) x 7.964 = 31.856 + 63.712 = 95.568.
   entry fee = 0.7964; exit fees = (104 + 108) x 7.964 x 0.0005 = 0.844184.
   slippage = 100 x 15.928 x 0.0001 + (104 + 108) x 7.964 x 0.0001 = 0.15928 + 0.1688368 = 0.3281168.
   Funding 0.
5. realized_pnl = 95.568 - 0.7964 - 0.844184 - 0.3281168 = 93.5992992; R = 93.5992992 / 49.997992 =
   1.87206116...

Check (standalone):

```bash
python -c "from decimal import Decimal as D;e=D('101');s=D('98');rpu=e-s+e*D('0.0006')+s*D('0.0008');q=(D(50)/rpu//D('0.001'))*D('0.001');a=(q/2//D('0.001'))*D('0.001');b=q-a;g=(D(104)-D(100))*a+(D(108)-D(100))*b;ef=D(100)*q*D('0.0005');xf=(D(104)*a+D(108)*b)*D('0.0005');sl=D(100)*q*D('0.0001')+(D(104)*a+D(108)*b)*D('0.0001');p=g-ef-xf-sl;print(rpu,q,a,b,q*rpu,g,ef,xf,sl,p,p/(q*rpu))"
```

Result: ENTRY_FILLED at 100.0 (not 98.5) at 10:05:59.999; TP1 7.964 at 104.0 at 10:20:59.999; final exit
TP2 at 108.0 at 10:20:59.999; realized_pnl 93.5992992.
