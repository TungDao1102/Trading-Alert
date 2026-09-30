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

### 6.1 Algo-order status semantics at trigger time

Conditional (algo) orders live in the Binance Algo Service until their condition is met, and only then reach the matching engine. Binance performs no margin check before a conditional order triggers (change-log 2025-11-06), so a stop that was accepted at placement can still fail at trigger. The lifecycle arrives as `ALGO_UPDATE` events; the status field is `X` and the failure reason field is `rm` (`o.rm` on the event payload).

| Status | Meaning |
| --- | --- |
| `NEW` | placed in the Algo Service, not yet triggered |
| `TRIGGERING` | condition met, forwarded to the matching engine |
| `FINISHED` | the triggered conditional order was filled or canceled in the matching engine |
| `REJECTED` | denied by the matching engine at trigger, for example a margin check failure |
| `EXPIRED` | canceled by the system |

Consequences for the execution layer (F-054):

- FINISHED does not mean filled: the resulting order state and the position must be read from the exchange before the protective exit is treated as executed.
- REJECTED and EXPIRED can occur at trigger time, after the stop-loss was accepted at placement. "SL accepted" therefore never means "SL will execute"; reconciliation and the D034 ladder in section 9 must cover a stop that fails at trigger.
- The failure reason is carried in `o.rm` on `ALGO_UPDATE`. A search summary of the change-log reports that the old `CONDITIONAL_ORDER_TRIGGER_REJECT` event was deprecated on 2025-12-15 in favour of `ALGO_UPDATE`; that date was not confirmed on the fetched change-log page, so parse `ALGO_UPDATE` and do not depend on the old event.
- For trailing stops before trigger the status remains `NEW` and two `NEW` events can arrive (`ia` false, then true).

Grounding and confidence: the official Event-Algo-Order-Update page could not be retrieved on 2026-09-30 (only the documentation shell). The field names come from the installed SDK model `algo_update_o.py` (`X` "Algo Status", `rm` "Algo order failed reason", `ia` "Is activated or not, only meaningful for trailing order") and the status meanings from a search summary of that page, recorded in `SOURCES.md`; verify against current Binance docs before implementation and re-confirm the status list before Phase 18.

## 7. Idempotency

All order requests require deterministic client identifiers.

Repeated execution of the same approved plan must not create duplicate entry orders.

## 8. Position modes

The tool must explicitly detect and support the chosen Binance position mode.

Do not assume One-way Mode or Hedge Mode.

Binance documents that position-mode changes have account-level restrictions and can be rejected when open orders/positions exist (error -4067 for open orders, -4068 for an open position, per the installed SDK docstring for `POST /fapi/v1/positionSide/dual`). [Binance Change Position Mode](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Position-Mode) The page text itself was not retrievable on 2026-09-30; verify against current Binance docs before implementation (F-057).

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

A protective stop paired with a still-working ENTRY order is not an orphan: the position is zero only because the entry has not filled yet, so the sweeper leaves that stop in place (F-401).

When a protective stop is missing (canceled, expired, or never acknowledged) while the position is open, the reconciler re-places it at the original plan stop-loss, never wider. This supersedes the earlier cancel-only reconciler decision (Phase 08 D-03 / Phase 09 D-02), per D034; if the re-placed stop is rejected or unacknowledged, the ladder continues with a reduce-only close and a HIGH-priority alert (see `SECURITY_AND_OPERATIONS.md` section 7).

Do not rely only on the WebSocket event stream. Periodic authoritative reconciliation is required.

## 10. No blind recovery

If placement response is ambiguous due to timeout/network failure:

1. do not immediately retry blindly;
2. query/reconcile by client order ID where supported;
3. only retry if absence is confirmed.

## 11. Manual emergency controls

Must provide a safe way to:

- cancel pending entry orders (protective stops and take-profits are never cancelled by this control),
- disable new entry orders (orders that can open or increase a position),
- close strategy-generated positions according to explicit user action,
- an explicit protect action (re-place the stop-loss at the original plan stop-loss),
- switch system to `SAFE_MODE`.

Per D034, protective and reduce-only orders are never blocked by a disable. A disable never blocks or cancels a protective or reduce-only order; closing a position and protecting a position are separate, explicit actions, and cancelling a protective stop is never part of any control above. The disable controls only stop the system from opening or adding to risk.

## 12. Algo-order capacity

Do not read or depend on a `MAX_NUM_ALGO_ORDERS` exchangeInfo filter. Binance removed that filter from `GET /fapi/v1/exchangeInfo` on 2025-12-29 and documents the limit as 200 open conditional orders across all symbols (account-wide, not per symbol). The common-definition page may still describe a per-symbol filter; the dated change-log entry governs (see the Phase 11 register in `SOURCES.md`); verify against current Binance docs before implementation (F-051). [Binance Futures changelog](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log)

The risk/execution layer should track the current open algo-order count account-wide (no symbol filter) and leave operational headroom rather than assuming unlimited protective orders. Per D031 the documents follow the accepted decision and the current official facts.
