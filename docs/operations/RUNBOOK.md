# Operations Runbook

## 1. Purpose

This is the operational response guide for incidents involving live approval mode, positions, orders, market data, or infrastructure.

The default objective is **preserve capital and state integrity**, not resume trading quickly.

## 2. Immediate emergency: SAFE_MODE

Trigger when:

- state cannot be reconciled;
- market data is stale;
- protective orders are missing or uncertain;
- duplicate execution is suspected;
- exchange/API behavior is unexpected;
- database state is corrupt or unavailable.

Actions:

```text
1. Set SAFE_MODE.
2. Block new live orders.
3. Verify Binance positions directly.
4. Verify open normal orders.
5. Verify open algo/conditional orders.
6. Verify each live position has the expected protection.
7. Reconcile local state.
8. Only then consider resuming.
```

## 3. Position without confirmed stop

```text
SAFE_MODE
→ alert immediately
→ query Binance authoritative position
→ query protective/algo orders
→ if stop is absent, submit protection only after risk validation
→ otherwise require explicit manual intervention
```

Never assume a locally stored order ID means the exchange order exists.

## 4. Orphan protective orders

Definition:

> A protective order remains active when its associated position is already zero or the plan is otherwise closed/invalid.

Action:

```text
identify orphan
→ verify position = zero
→ cancel associated protective/algo orders
→ journal cancellation
→ re-scan for remaining orphan orders
```

This must run both on event-driven reconciliation and periodic sweeps.

## 5. Suspected duplicate approval/order

```text
SAFE_MODE
→ do not retry blindly
→ look up approval token/hash
→ inspect clientOrderId/algoClientId/exchange order state
→ reconcile
→ continue only when unique execution intent is established
```

## 6. Telegram callback replay

A repeated callback for the same approval token must return the current state.

It must never create another execution intent.

## 7. Market feed stale

Trigger when:

```text
now - last_expected_closed_candle > configured freshness threshold
```

Action:

```text
NO NEW SIGNALS
NO NEW ORDERS
→ reconnect/re-bootstrap
→ validate candle continuity
→ resume only after health check
```

## 8. WebSocket disconnect

For every reconnect:

```text
reconnect
→ refresh server time if needed
→ bootstrap authoritative account/market state
→ compare local state
→ restore subscriptions
→ verify latest closed candle
→ resume
```

## 9. Database failure

```text
SAFE_MODE
→ block new orders
→ preserve existing exchange-side protection
→ restore DB or switch to read-only monitoring
→ reconcile after recovery
```

## 10. Binance API degradation

Do not infer absence of an order from a timeout.

Use query/reconciliation before retrying signed order requests.

## 11. Backup and restore

At minimum:

- automated PostgreSQL logical backup or equivalent;
- encrypted backup copy outside the primary VPS/host;
- retention policy;
- periodic restore drill.

The collected OI/time-series dataset is considered irreplaceable research data.

A backup is not considered valid until a restore test succeeds.

## 12. Manual close

A manual position close must be explicit and recorded as:

```text
ManualExit
actor
reason
requested_at_utc
exchange_confirmation
```

After manual close, the reconciliation process must cancel orphan protective orders.
