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
| `TRIGGERED` | the order has been successfully placed into the matching engine |
| `FINISHED` | the triggered conditional order has been filled or canceled in the matching engine: filled OR canceled, so FINISHED alone does not prove that the protective exit executed |
| `CANCELED` | the conditional order has been canceled |
| `REJECTED` | denied by the matching engine at trigger, for example a margin check failure |
| `EXPIRED` | canceled by the system |

Consequences for the execution layer (F-054):

- FINISHED does not mean filled: Binance defines FINISHED as filled or canceled in the matching engine, so a FINISHED stop proves neither a fill nor protection. The resulting order state and the position must be read from the exchange before the protective exit is treated as executed.
- REJECTED and EXPIRED can occur at trigger time, after the stop-loss was accepted at placement. "SL accepted" therefore never means "SL will execute"; reconciliation and the D034 ladder in section 9 must cover a stop that fails at trigger.
- The failure reason is carried in `o.rm` on `ALGO_UPDATE`. A search summary of the change-log reports that the old `CONDITIONAL_ORDER_TRIGGER_REJECT` event was deprecated on 2025-12-15 in favour of `ALGO_UPDATE`; that date was not confirmed on the fetched change-log page, so parse `ALGO_UPDATE` and do not depend on the old event.
- For trailing stops before trigger the status remains `NEW` and two `NEW` events can arrive (`ia` false, then true); the change-log entry of 2026-08-21 (read 2026-10-16) says ALGO_UPDATE events for trailing stop orders may arrive twice, once with `ia:false` and again with `ia:true`, so the event router must deduplicate them.

Grounding and confidence: the official Event-Algo-Order-Update page could not be retrieved on 2026-09-30 (only the documentation shell), and neither the Phase 18 research (2026-10-15, the tool returned the documentation landing page) nor the plan 18-01 executor (2026-10-16, every request was answered by a WAF challenge) could read it. Later on 2026-10-16 the page was read at its new location, the Algo Order Update section of the user-data-streams page, with WebFetch, as recorded in `SOURCES.md`, section "Facts read for Phase 18": the seven status values and the `NEW`, `TRIGGERING`, `TRIGGERED`, `FINISHED`, `CANCELED` and `REJECTED` meanings above follow that read, and `EXPIRED` (canceled by the system, with a GTE_GTC example) is the tool's paraphrase, not a quotation. WebFetch passes the page through a small summarising model, so the wording is not guaranteed to be character-exact. The read agrees with the earlier sources: the Phase 18 research search summary of the page (2026-10-15) and the Phase 9 transcription of an archived copy dated 2026-01-13 (`09-EXCHANGE-FACTS.md` Fact 2). The payload field table did not render, so the field names still come from the installed SDK model `algo_update_o.py` (`X` "Algo Status", `rm` "Algo order failed reason", `ia` "Is activated or not, only meaningful for trailing order"). Nothing here is verified live: the connected-machine smoke (plan 18-18) captures real events before the status list and the fields are treated as confirmed; verify against current Binance docs before implementation.

## 7. Idempotency

All order requests require deterministic client identifiers (`src/execution/order_ids.py`).

Repeated execution of the same approved plan must not create duplicate entry orders. The guarantee comes from a durable write-ahead record in PostgreSQL (`execution_intents`, `DATA_MODEL.md` section 2.14), not from the exchange.

### 7.1 The exchange does not deduplicate

Binance documents `newClientOrderId` and `clientAlgoId` as a unique id among open orders, and a duplicate raises `-4116 DUPLICATED_CLIENT_ORDER_ID`; the id is unique only among open orders, so a FILLED or CANCELED order frees its id and the exchange would accept a second order with the same id (`BINANCE.md` section 6.1; provenance and confidence in `SOURCES.md`, "Facts verified for Phase 17"). The Phase 08 D-04 premise that the exchange deduplicates a replayed `clientOrderId` therefore held only while the first entry was still open; after a fill or a cancel a replay would have placed a second entry (audit F-126, F-951). This section retires that premise. The deterministic id is kept because it lets a query by client id find the order after an ambiguous response or a restart, not because the exchange will reject a duplicate.

### 7.2 Write-ahead order

`execute_approved_plan` runs these steps in this order; every `COMMIT` is a separate durable transaction that lands before the adapter call that follows it:

```text
argument validation
identity checks (chat, plan hash, version/parameter set, token)     -> INVALIDATED / STALE_SETUP
stored-outcome lookup for this approval                              -> return the stored outcome, zero adapter calls
expiry and the remaining gates (binding, approval-authorizes-plan,
  enablement, SAFE_MODE, cost-rate, risk, placement, position mode)  -> NO_TRADE, approval stays unconsumed
CONSUME: one transaction inserts the ENTRY intent (INTENDED) and
  stamps the approval CONSUMED                                       -> COMMIT
ENTRY SENT                                                           -> COMMIT
place_entry
ENTRY result: ACKED / REJECTED / UNKNOWN                             -> COMMIT
STOP_LOSS intent INTENDED, then SENT                                 -> COMMIT
place_algo_protective
STOP_LOSS result: ACKED (confirmed) / UNKNOWN (not confirmed)        -> COMMIT
ENTRY outcome (is_no_trade, reason_code) recorded                    -> COMMIT
```

A crash between any two steps leaves a readable row. An intent left INTENDED or SENT is never re-sent blindly (section 10).

- Consumption happens only at placement. A NO_TRADE decided before placement (binding, enablement, SAFE_MODE, cost, risk, placement gates, position mode) does not consume the approval, so a later retry of the same approved plan re-runs every gate until the plan expires. A store failure before the entry is sent returns `RECONCILIATION_REQUIRED` and places nothing; a second approval of the same plan (`uq_execution_intents_plan_role`) returns `INVALIDATED` and places nothing.
- The loser of a concurrent consume of the same approval gets `False` from the store (it read the winner's row) and returns the winner's stored outcome or, if none is recorded yet, `RECONCILIATION_REQUIRED`; it never places an order and never raises.
- Gate order is identity, then stored outcome, then expiry (D-16). The identity checks run first so that a wrong token or wrong chat never sees the stored state; the stored outcome is looked up before the expiry gate so that a replay after the plan's expiry of a plan that was already executed returns the stored result instead of `APPROVAL_EXPIRED`. A plan that was never executed still expires.
- One entry per plan is enforced by the database, not only by this code: primary key `(approval_id, role)`, `uq_execution_intents_plan_role (trade_plan_id, role)`, partial unique `client_order_id` and `algo_client_id`, and at most one decided approval per plan.
- A replay returns the stored `ExecutionOutcome` with zero adapter calls, in the same process and after a restart, because the state is read from PostgreSQL. An ENTRY row without a recorded outcome (a crash after the entry was sent) replays as `RECONCILIATION_REQUIRED`.
- Callers: after the plan's expiry the Telegram callback layer (`check_binding_full`) still answers a redelivered APPROVE with `APPROVAL_EXPIRED` even when the plan was executed, because the callback layer keeps its expiry gate. The stored outcome is returned only when `execute_approved_plan` is handed the stored approval. Both paths place nothing; Phase 23 and 24 must read `PgExecutionStateStore.get_entry` if the message should say "already executed".

### 7.3 Failure policy for the intent writes

- Before the entry may exist (lookup, consume, ENTRY SENT): a store failure is NO_TRADE (`RECONCILIATION_REQUIRED`), nothing is placed and SAFE_MODE is not entered. A failed ENTRY SENT write leaves the consumed INTENDED row, so every replay returns `RECONCILIATION_REQUIRED` until reconciliation resolves it.
- After the entry may exist (the STOP_LOSS intent or any later write fails): the first failure enters SAFE_MODE with reason `DB_FAILURE` (once), every later store write is skipped, the stop-loss is still placed by its deterministic algo id, and the outcome is `RECONCILIATION_REQUIRED`. Protection outranks the audit row (section 6, D034): the SAFE_MODE entry is journaled through the same database, so a failing journal write is swallowed (the controller sets its flag before journaling, only the audit row is lost) and the stop-loss and the unprotected-entry cancel still run (17-REVIEW CR-01). The unconfirmed-stop path (SAFE_MODE `ENTRY_WITHOUT_PROTECTIVE` plus entry cancel) still runs when the stop-loss is not confirmed.
- Only the typed persistence errors are caught; every database error that is not an integrity violation (read-only transaction after a failover, trigger `RAISE EXCEPTION`, out-of-range value) is mapped to the typed `StoreFailure` by `OperationalDatabase.transaction` (17-REVIEW WR-01). A crash (any `BaseException`) propagates untouched, so a simulated or real crash is never mistaken for a handled failure.
- The STOP_LOSS row keeps `exchange_order_id` and `exchange_status` empty until reconciliation fills them; a confirmed placement is recorded as ACKED.

## 8. Position modes

The tool must explicitly detect and support the chosen Binance position mode.

Do not assume One-way Mode or Hedge Mode.

Binance documents that position-mode changes have account-level restrictions and can be rejected when open orders/positions exist (error -4067 for open orders, -4068 for an open position). [Binance Change Position Mode](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Position-Mode) The page text was not retrievable on 2026-09-30 nor by the plan 18-01 executor on 2026-10-16; later on 2026-10-16 it was read at its new location (the Change Position Mode section of the REST `trade` group) with WebFetch, a small-model summary that is not character-exact (`SOURCES.md`, section "Facts read for Phase 18"): `POST /fapi/v1/positionSide/dual` has weight 1, `dualSidePosition` is required and `recvWindow` is at most 60000; after the CM migration UM and CM share the same setting, so one change flips both; the change is rejected when either side has an open order (-4067) or an open position (-4068). The Phase 18 research summary (2026-10-15) and the installed SDK docstring for the endpoint state the same. Not verified live; verify against current Binance docs before implementation (F-057).

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

### 10.1 Restart recovery of execution intents

After a restart every intent that is INTENDED, SENT or UNKNOWN is unresolved (`list_unresolved_intents`). `resolve_unresolved_intents` (`src/execution/intent_recovery.py`) resolves them by query only; it takes a two-method probe (`query_order_by_client`, `query_algo_order_by_client`), so placing an order is structurally impossible:

1. INTENDED and SENT intents are first recorded as UNKNOWN;
2. each is probed by its deterministic client id (ENTRY by client order id, protective legs by algo client id);
3. found: ACKED (at any age), with the exchange order id for an ENTRY;
4. definitively absent and intended less than the lookup window ago: REJECTED. The window is 3 days (default `lookup_window`), because Binance Query Order does not find a CANCELED or EXPIRED order without a fill after 3 days (`BINANCE.md` section 6.1), so "not found" proves absence only for a younger intent; exactly 3 days old is not young;
5. a probe error, an indeterminate answer (anything but a literal true or false) or an absent order at or past the window: the intent stays UNKNOWN.

Anything that stays UNKNOWN, or whose status write fails, enters SAFE_MODE with reason `UNRESOLVED_EXECUTION_INTENT` exactly once per pass (`GLOSSARY.md` section 9.4); an unreadable store enters SAFE_MODE `DB_FAILURE` and re-raises, so "nothing to resolve" is never confused with "could not look". Entries stay blocked until the intent is resolved; the exit rules are Phase 20. A later `execute_approved_plan` for the same approval returns the stored state (`RECONCILIATION_REQUIRED` when no outcome was recorded) and never calls `place_entry`.

Implementation status (Phase 17): the store, the recovery function and the write-ahead flow exist and are proven on PostgreSQL (crash injection after each step, two-thread races, restart on a fresh engine), but nothing calls `resolve_unresolved_intents` or reads the persisted SAFE_MODE state at startup yet: that wiring is Phase 20 (SAFE_MODE, reconciliation) and Phase 24 (composition). Known gap owned by Phase 20: a crash after the STOP_LOSS intent was written leaves an acknowledged entry without a stop, and a restart does not place one (the intent rows ENTRY ACKED and STOP_LOSS INTENDED or SENT are what reconciliation reads); until then the operator uses `RUNBOOK.md` section 3.

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
