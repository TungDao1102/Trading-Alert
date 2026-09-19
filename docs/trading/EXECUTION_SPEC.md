# Execution Specification

## 1. Execution model

Initial live mode:

```text
Signal
  ↓
Trade Plan
  ↓
Telegram
  ↓
APPROVE
  ↓
Risk re-check
  ↓
Place entry
  ↓
Place/attach protective exits
  ↓
Monitor user-data events
```

The approval must expire; it must not be possible to approve an invalid or stale plan accidentally.

## 2. Preferred V1 order style

For swing-style setup research:

- entry: `LIMIT` or a defined limit-zone model;
- stop: Binance USDⓈ-M Algo/conditional order;
- take profit: Binance USDⓈ-M Algo/conditional order.

Important current Binance API detail: since late 2025, USDⓈ-M `STOP_MARKET` / `TAKE_PROFIT_MARKET` / related conditional orders were migrated to the Algo Order service. The implementation must use the current Algo Order endpoints rather than assuming these are ordinary `/fapi/v1/order` requests. [Binance Futures changelog](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log)

`closePosition=true` is only for supported market-triggered conditional types, cannot be combined with `quantity` or `reduceOnly`, and has position-mode-specific constraints. [Binance trade API](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order)

## 3. Entry order lifecycle

```text
PLANNED
  ↓
SUBMITTING
  ↓
NEW
  ├→ PARTIALLY_FILLED
  ├→ FILLED
  ├→ CANCELED
  └→ EXPIRED
```

An order enters `PLANNED` only after the upstream plan has been approved; approval lives on the signal and trade-plan machines (see `GLOSSARY.md` §2 and §3), not on the order state machine.

## 4. Pending-order expiry

An unfilled entry must be canceled when:

1. time expiry is reached;
2. strategy invalidation occurs;
3. portfolio/risk state changes and the order is no longer permitted;
4. symbol/market conditions make the plan stale;
5. user explicitly cancels.

Never leave an approved LIMIT order open indefinitely.

## 5. Partial fills

The execution manager must support:

- partial entry fill;
- remaining entry quantity cancellation;
- protective exits sized against the actual filled quantity;
- transition to fully filled position;
- reconciliation when fill events arrive out of order or are replayed.

A common One-way-Mode pattern may be:

```text
SL  : STOP_MARKET, closePosition=true
TP1 : TAKE_PROFIT_MARKET, reduceOnly=true, explicit quantity
TP2 : TAKE_PROFIT_MARKET, closePosition=true
```

This is **mode-dependent**, not a universal template. Hedge Mode has different parameter constraints and must be handled explicitly. Before implementation, verify the exact current Algo Order API semantics.

## 6. Protective-exit requirements

After entry fill, the system must verify that the expected protective stop exists and is active.

If protection cannot be confirmed:

```text
ALERT HIGH PRIORITY
→ do not assume position is protected
```

The system must reconcile with Binance rather than trusting local state.

## 7. Idempotency

All order requests require deterministic client identifiers.

Repeated execution of the same approved plan must not create duplicate entry orders.

## 8. Position modes

The tool must explicitly detect and support the chosen Binance position mode.

Do not assume One-way Mode or Hedge Mode.

Binance documents that position-mode changes have account-level restrictions and can be rejected when open orders/positions exist. [Binance Futures Trade API](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)

## 9. Reconciliation loop

On startup/reconnect and periodically:

```text
local state
   vs
Binance open normal orders
   vs
Binance open algo/conditional orders
   vs
Binance positions
```

Any divergence enters `RECONCILIATION_REQUIRED`.

The reconciliation job must explicitly detect **orphan protective orders**: active stop/TP orders whose associated position is already zero or whose plan is otherwise closed. Orphan orders must be canceled after authoritative position verification.

Do not rely only on the WebSocket event stream. Periodic authoritative reconciliation is required.

## 10. No blind recovery

If placement response is ambiguous due to timeout/network failure:

1. do not immediately retry blindly;
2. query/reconcile by client order ID where supported;
3. only retry if absence is confirmed.

## 11. Manual emergency controls

Must provide a safe way to:

- cancel pending strategy orders,
- disable new live orders,
- close strategy-generated positions according to explicit user action,
- switch system to `SAFE_MODE`.

## 12. Algo-order capacity

Do not read or depend on a `MAX_NUM_ALGO_ORDERS` exchangeInfo filter. Binance removed that filter from `GET /fapi/v1/exchangeInfo` in December 2025 and documented a 200-open-conditional-order limit per symbol instead. Current limits must still be verified before implementation. [Binance Futures changelog](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log)

The risk/execution layer should track current open algo-order count and leave operational headroom rather than assuming unlimited protective orders.
