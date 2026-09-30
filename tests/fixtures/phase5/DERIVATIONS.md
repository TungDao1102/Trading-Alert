# Phase 5 Fixture Derivations (plan 12-07)

Hand arithmetic behind the eleven Phase 5 golden cases. The numbers below came
from a standalone Decimal computation (28-digit context, no project imports)
written independently of `src/risk`. The expected values in `expected.json`
and the candidate-risk figures used by the portfolio cases are copied from
here, never from the output of the code under test. Any change to a number in
a fixture needs a new derivation in this file first; do not regenerate an
expectation by running the pipeline and pasting the result.

## Common inputs

| Symbol | Value |
|--------|-------|
| fee_rate_entry | 0.0005 |
| fee_rate_exit | 0.0005 |
| entry_slippage_rate | 0.0001 |
| exit_slippage_rate | 0.0003 |
| fee_source | PARAMETER |
| min_stop_distance_rate | 0.003 |
| max_cost_to_risk | 0.15 |
| minimum_risk_utilization_after_rounding | 0.6 |
| quantity_step_size / min_quantity / min_notional | 0.001 / 0.001 / 50 (unless a case says otherwise) |

## Formulas (all Decimal)

- Sizing entry: the adverse edge of the zone. LONG uses entry_max, SHORT uses
  entry_min. The notional reference is the zone mid, (entry_min + entry_max) / 2.
- stop distance = |sizing entry - stop|.
- cost per unit = sizing entry x (fee_rate_entry + entry_slippage_rate)
  + stop x (fee_rate_exit + exit_slippage_rate)
  = sizing entry x 0.0006 + stop x 0.0008.
- risk_per_unit = stop distance + cost per unit.
- allowed_risk = equity x risk_rate.
- raw quantity = allowed_risk / risk_per_unit.
- quantity after floor = floor(raw / step) x step.
- realized_risk = quantity after floor x risk_per_unit.
- utilization = realized_risk / allowed_risk (must be at least 0.6).
- notional check = quantity after floor x zone mid (must be at least min_notional).
- guards (both run before any rounding): stop rate = stop distance / sizing entry
  must be at least 0.003; cost ratio = cost per unit / risk_per_unit must be at
  most 0.15.

## Why the old numbers moved

Before Phase 12 the fixtures carried a hand-typed `modeled_costs_per_unit`
(1.0 for the happy paths) and measured the stop distance from the zone mid.
happy_path_long sized 0.049 (allowed 50 / (|50000 - 49000| + 1.0) = 0.04995,
floored to 0.049). At the adverse fill of 50100 the loss at the stop would be
0.049 x 1169.26 = 57.29374 against a 50 budget. Sizing now starts from the
adverse edge and derives the cost from the four literal rates, so the accepted
quantity falls to 0.042 and the loss at the stop stays inside the budget.

## Sizing cases (five)

### happy_path_long

LONG, zone 49900-50100, stop 49000, equity 10000, risk_rate 0.005.

1. sizing entry = 50100; zone mid = 50000.
2. stop distance = 50100 - 49000 = 1100.
3. cost = 50100 x 0.0006 + 49000 x 0.0008 = 30.06 + 39.2 = 69.26.
4. risk_per_unit = 1100 + 69.26 = 1169.26.
5. allowed_risk = 10000 x 0.005 = 50.
6. raw = 50 / 1169.26 = 0.04276208884251577921078288832.
7. floor to 0.001 -> 0.042.
8. realized_risk = 0.042 x 1169.26 = 49.10892.
9. utilization = 49.10892 / 50 = 0.9821784 (at least 0.6, pass).
10. notional = 0.042 x 50000 = 2100 (at least 50, pass).
11. guards: stop rate = 1100 / 50100 = 0.02195608782 (at least 0.003, pass);
    cost ratio = 69.26 / 1169.26 = 0.05923404546 (at most 0.15, pass).

Result: ACCEPTED, quantity 0.042, reason OK.

### happy_path_short

SHORT, zone 49900-50100, stop 51000, equity 10000, risk_rate 0.005.

1. sizing entry = 49900 (entry_min); zone mid = 50000.
2. stop distance = 51000 - 49900 = 1100.
3. cost = 49900 x 0.0006 + 51000 x 0.0008 = 29.94 + 40.8 = 70.74.
4. risk_per_unit = 1100 + 70.74 = 1170.74.
5. allowed_risk = 50.
6. raw = 50 / 1170.74 = 0.04270803081811503835181167467.
7. floor -> 0.042.
8. realized_risk = 0.042 x 1170.74 = 49.17108.
9. utilization = 49.17108 / 50 = 0.9834216; notional = 0.042 x 50000 = 2100.
10. guards: stop rate = 1100 / 49900 = 0.02204408818; cost ratio =
    70.74 / 1170.74 = 0.06042332200.

Result: ACCEPTED, quantity 0.042, reason OK.

### utilization_reject_edge

LONG, zone 49900-50100, stop 49000, equity 117, risk_rate 0.017.

1. sizing entry = 50100; stop distance = 1100; cost = 69.26; risk_per_unit = 1169.26
   (same geometry as happy_path_long).
2. allowed_risk = 117 x 0.017 = 1.989.
3. raw = 1.989 / 1169.26 = 0.001701075894155277697004943297.
4. floor -> 0.001 (equal to min_quantity 0.001, pass).
5. realized_risk = 0.001 x 1169.26 = 1.16926.
6. notional = 0.001 x 50000 = 50, equal to min_notional 50 (passes: the check is
   strictly below).
7. utilization = 1.16926 / 1.989 = 0.5878632478632478632478632479, below 0.6.
8. guards: stop rate 0.02195608782 and cost ratio 0.05923404546 both pass.

Result: REJECTED, UTILIZATION_REJECT, quantity null.

### min_qty_reject

LONG, zone 49900-50100, stop 49000, equity 500, risk_rate 0.01, min_quantity 0.01.

1. sizing entry = 50100; risk_per_unit = 1169.26 (as above).
2. allowed_risk = 500 x 0.01 = 5.
3. raw = 5 / 1169.26 = 0.004276208884251577921078288832.
4. floor -> 0.004.
5. realized_risk = 0.004 x 1169.26 = 4.67704.
6. 0.004 is below min_quantity 0.01.
7. guards pass (same geometry: 0.02195608782, 0.05923404546).

Result: REJECTED, MIN_QTY_REJECT, quantity null.

### notional_reject

LONG, zone 99-101, stop 90, equity 100, risk_rate 0.01, tick 0.01.

1. sizing entry = 101; zone mid = 100.
2. stop distance = 101 - 90 = 11.
3. cost = 101 x 0.0006 + 90 x 0.0008 = 0.0606 + 0.072 = 0.1326.
4. risk_per_unit = 11 + 0.1326 = 11.1326.
5. allowed_risk = 100 x 0.01 = 1.
6. raw = 1 / 11.1326 = 0.08982627598225032786590733521.
7. floor -> 0.089 (at least min_quantity 0.001, pass).
8. realized_risk = 0.089 x 11.1326 = 0.9908014.
9. notional = 0.089 x 100 = 8.9, below min_notional 50.
10. guards: stop rate = 11 / 101 = 0.1089108911 (pass); cost ratio =
    0.1326 / 11.1326 = 0.01191096420 (pass).

Result: REJECTED, NOTIONAL_REJECT, quantity null.

## Portfolio cases (six)

The portfolio expectations are reason codes and daily states only (numeric
fields are null), so the numbers below prove that the candidate reaches the
intended gate and that the intended gate is the one that rejects.

### cluster_cap_reject, aggregate_cap_reject (shared candidate)

LONG, zone 49995-50005, stop 49555, equity 10000, risk_rate 0.003.

1. sizing entry = 50005; zone mid = 50000; stop distance = 50005 - 49555 = 450.
2. cost = 50005 x 0.0006 + 49555 x 0.0008 = 30.003 + 39.644 = 69.647.
3. risk_per_unit = 450 + 69.647 = 519.647.
4. allowed_risk = 10000 x 0.003 = 30.
5. raw = 30 / 519.647 = 0.05773149849801884740987631989; floor -> 0.057.
6. candidate realized_risk = 0.057 x 519.647 = 29.619879.
7. utilization = 29.619879 / 30 = 0.9873293; notional = 0.057 x 50000 = 2850.
8. guards: stop rate = 450 / 50005 = 0.008999100090 (0.8999 percent, at least
   0.003); cost ratio = 69.647 / 519.647 = 0.13402752253 (at most 0.15, margin
   0.016).

cluster_cap_reject: one open position (ETHUSDT LONG, open_risk 21.00).
21 + 29.619879 = 50.619879, above cluster_cap 50 -> CLUSTER_CAP_REJECT.
(Aggregate: 50.619879 is below max_aggregate_open_risk 100, so the cluster gate
is the one that trips.)

aggregate_cap_reject: one open position (BNBUSDT LONG, open_risk 71.00).
71 + 29.619879 = 100.619879, above max_aggregate_open_risk 100 ->
AGGREGATE_CAP_REJECT. (BNBUSDT is a different cluster from the candidate, so
the cluster cap is not the gate that trips.)

### max_positions_reject

LONG, zone 49995-50005, stop 49555, equity 10000, risk_rate 0.0005.

1. sizing entry, distance, cost, risk_per_unit as above (50005, 450, 69.647,
   519.647).
2. allowed_risk = 10000 x 0.0005 = 5.
3. raw = 5 / 519.647 = 0.009621916416336474568312719981; floor -> 0.009.
4. candidate realized_risk = 0.009 x 519.647 = 4.676823.
5. utilization = 4.676823 / 5 = 0.9353646; notional = 0.009 x 50000 = 450.
6. guards: identical to the cluster case (stop rate 0.8999 percent, cost ratio
   0.13403).

Two open positions (ETHUSDT and SOLUSDT, open_risk 10.00 each) reach the
max_concurrent_positions cap -> MAX_POSITIONS_REJECT.

### daily_stop_block, stale_constraints, uncertain_account_state

These use the happy_path_long geometry (zone 49900-50100, stop 49000, equity
10000, risk_rate 0.005): quantity 0.042, realized_risk 49.10892, guards pass
(see happy_path_long). They then reach their own gate:

- daily_stop_block: daily_loss_quote 100.00 -> DAILY_STOP_BLOCK, daily state
  DAILY_STOP.
- stale_constraints: constraint metadata observed at 2026-09-18T22:59:59, more
  than the freshness window before now (2026-09-19T00:00:00) -> STALE_CONSTRAINTS.
- uncertain_account_state: daily_loss_quote null -> UNCERTAIN_ACCOUNT_STATE.
