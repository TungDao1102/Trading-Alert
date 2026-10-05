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
