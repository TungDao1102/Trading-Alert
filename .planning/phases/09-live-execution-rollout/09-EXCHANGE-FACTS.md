# Phase 9 Exchange Facts: Verdicts Against Official Binance Docs

**Purpose.** 09-REVIEW-FIX.md left six Binance exchange facts unconfirmed (items 1 to 6 under "Exchange facts that still need checking against the current Binance docs"). This file records a verdict for each, plus two addenda the Demo rehearsal runner (`scripts/demo_rehearsal.py`) depends on. Nothing in `src/` or the tests was changed by this task. Where a verdict implies a code change, the change is described under "Code impact" and is not made here.

**Prepared on:** 2026-10-05 (quick task 261005-tx9, Task 2).

**How the pages were fetched (read this before trusting a verdict).** The live pages at `developers.binance.com` answered every request from this environment with HTTP 202 and an empty body (a bot-protection challenge that a plain HTTP client cannot pass), and the legacy `binance-docs.github.io` site only redirects to the same host. Every quotation below therefore comes from the Internet Archive (Wayback Machine) snapshot of the official page at the same URL path, fetched on 2026-10-05. The snapshot date is given in each Source line. The newest snapshot used is from 2026-06-17, so a docs change after that date is not seen here. The Source line names the official page and gives the snapshot URL that was actually read. Nothing was taken from SDK models, third-party mirrors, search snippets or memory. The orchestrator should re-check any verdict that matters against the live page before a code change.

**Verdict legend.**

- CONFIRMED: an official page states the fact explicitly.
- CONTRADICTED: an official page states the opposite of what the code assumes.
- UNCONFIRMED: no official page states it, or the page could not be retrieved or parsed, or only part of the claim is stated.

**Demo cross-check.** Every entry carries a "Demo cross-check" line that reads NOT YET OBSERVED. The orchestrator fills it in from the operator's Demo evidence file after the user runs the rehearsal. This task never fills it in.

## The six facts

### Fact 1: Query-order "not found" code

**Claim:** `query_order_by_client` treats `-2011 UNKNOWN_ORDER` as "order not found" (found=False) and deliberately does not map `-2013 NO_SUCH_ORDER`; `query_algo_order_by_client` uses the same `-2011` mapping.

**Verdict:** CONFIRMED for Query Algo Order (Demo-observed -2013); Query Order -2013 documented but not Demo-observed

**Source:** https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code (snapshot http://web.archive.org/web/20260616115238/https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code), https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Order (snapshot http://web.archive.org/web/20260617202104/...), https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Algo-Order (snapshot http://web.archive.org/web/20260422084421/...), https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Cancel-Algo-Order (snapshot http://web.archive.org/web/20260616114853/...)

**Fetched:** 2026-10-05 (snapshots dated 2026-06-16, 2026-06-17, 2026-04-22, 2026-06-16)

**Evidence:** Error Code page: "-2011 CANCEL_REJECTED ... Cancel request failure as open order not found in the orderbook: "Unknown order sent"." and "-2013 NO_SUCH_ORDER  Order does not exist." Query Order and Query Algo Order pages: "These orders will not be found: order status is CANCELED or EXPIRED AND order has NO filled trade AND created time + 3 days < current time" and "order create time + 90 days < current time"; neither page names an error code for a missing order. Cancel Algo Order lists no error codes.

**Code impact:** None made here. Two observations for the orchestrator. (a) No official page ties either code to Query Order or Query Algo Order, so the `-2011` mapping in `BinanceUsdmAdapter.query_order_by_client` and `query_algo_order_by_client` is unconfirmed, and so is the decision not to map `-2013`. (b) The docs name `-2011` `CANCEL_REJECTED`; the text `UNKNOWN_ORDER` does not appear for it. The adapter matches `"UNKNOWN_ORDER" in str(exc) or "-2011" in str(exc)`, so only the `-2011` branch can match a documented code, and that depends on the SDK exception text carrying the numeric code. If the Demo run shows `-2013` for an unknown client id, the mapping in those two adapter methods is the place that would change, and only after a deliberate decision (a wrong mapping enables a retry and risks a duplicate order). Fail-closed behaviour stays as it is.

**Demo cross-check:** OBSERVED 2026-10-05 (read-only probe, one signed `GET /fapi/v1/algoOrder` on `demo-fapi.binance.com` with a client id that cannot exist; nothing placed or cancelled). The SDK raised `binance_common.errors.BadRequestError` with `status_code=-2013`, `error_message='Order does not exist.'`, `str(exc) == "(-2013, 'Order does not exist.')"`. So Demo answers a missing algo order with `-2013 NO_SUCH_ORDER`, not `-2011`, and the pre-fix mapping raised, ending the `far` dry-run in ENTRY_WITHOUT_PROTECTIVE. Not observed: Query Order (`GET /fapi/v1/order`) on Demo; the docs list `-2013` for it, and it is mapped on that documentary basis.

**Resolution (quick 261005-vb2):** `_is_order_not_found_error` in `src/adapters/binance_usdm.py` keys on the int `status_code` (`-2013`, `-2011`) and falls back to message text only when no int code exists; both `query_algo_order_by_client` and `query_order_by_client` use it. Every other code still raises (fail closed). Cancel paths are unchanged.

### Fact 2: Active algo statuses

**Claim:** `_ACTIVE_ALGO_STATUSES` in `src/execution/manager.py` is `{"NEW"}`; every other `algoStatus` is treated as "not confirmed active" (fail closed).

**Verdict:** UNCONFIRMED

**Source:** https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update (snapshot http://web.archive.org/web/20260113091316/https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update)

**Fetched:** 2026-10-05 (snapshot dated 2026-01-13)

**Evidence:** The ALGO_UPDATE page defines seven values. "NEW : ... the conditional order was successfully placed into the Algo Service but has not yet been triggered." "TRIGGERING : ... the order has met the triggering condition and has been forwarded to the matching engine." "TRIGGERED : ... the order has been successfully placed into the matching engine." "FINISHED : ... the triggered conditional order has been filled or canceled in the matching engine." The other three are CANCELED, REJECTED ("denied by the matching engine, such as in scenarios of margin check failures") and EXPIRED ("canceled by the system"). The REST pages (New, Query, Current-All-Algo-Open-Orders) show only example values (NEW, CANCELED) and list no enum.

**Code impact:** None made here, and none required: the allow-list is fail-closed. The value list is documented, but the docs never label a status "active" or "terminal". They do imply TRIGGERING and TRIGGERED are in-flight, non-terminal states, because FINISHED is described as the end state after TRIGGERED. Whether a protective in TRIGGERING or TRIGGERED should count as "exists and active" is a design decision for the orchestrator, not a documented fact. If it is decided yes, `_ACTIVE_ALGO_STATUSES` is the constant to change.

**Demo cross-check:** NOT YET OBSERVED

### Fact 3: reduceOnly on CONDITIONAL algo orders

**Claim:** `reduceOnly=true` is accepted on a one-way TAKE_PROFIT_MARKET algo order that carries an explicit quantity, and is mutually exclusive with `closePosition=true` (the adapter sends reduceOnly only for explicit-quantity legs and never together with closePosition).

**Verdict:** CONFIRMED

**Source:** https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order (snapshot http://web.archive.org/web/20260519005421/https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order)

**Fetched:** 2026-10-05 (snapshot dated 2026-05-19)

**Evidence:** Parameter table: "reduceOnly STRING NO "true" or "false". default "false". Cannot be sent in Hedge Mode; cannot be sent with closePosition = true". Notes for STOP_MARKET and TAKE_PROFIT_MARKET with closePosition=true: "Cannot be used with quantity paremeter. Cannot be used with reduceOnly parameter."

**Code impact:** None. Scope of this verdict: it covers which parameter combinations are valid. The page does not describe trigger-time behaviour of a reduce-only conditional leg, so that remains for the Demo cross-check. One conflicting line was seen on the Error Code page: "-4138 REDUCE_ONLY_MUST_BE_TRUE  Reduce only must be true with closePosition equals true". That text predates the Algo Service migration and contradicts the New Algo Order page, which governs the algo endpoint; if Demo rejects a closePosition leg for this reason, `place_algo_protective` is where it would show.

**Demo cross-check:** NOT YET OBSERVED

### Fact 4: MIN_NOTIONAL on reduce-only or close legs

**Claim:** The MIN_NOTIONAL filter applies to reduce-only TP1 legs (the TP1 notional gate `quantize_protective_qty` in `src/execution/placement.py` assumes it does).

**Verdict:** CONTRADICTED

**Source:** https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code (snapshot http://web.archive.org/web/20260616115238/https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code); the filter definition is at https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition (snapshot http://web.archive.org/web/20260612145533/https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition)

**Fetched:** 2026-10-05 (snapshots dated 2026-06-16 and 2026-06-12)

**Evidence:** Error Code page: "-4164 MIN_NOTIONAL  Order's notional must be no smaller than %s (unless you choose reduce only)". Common Definition page, MIN_NOTIONAL: "The MIN_NOTIONAL filter defines the minimum notional value allowed for an order on a symbol. An order's notional value is the price * quantity." The filter definition itself carries no reduce-only exemption.

**Code impact:** None made here. The only statement is in the generic error-code text, not on the New Algo Order page, and it does not say whether the Algo Service applies the same exemption to a conditional reduce-only leg; closePosition legs are not mentioned at all. The TP1 gate is therefore stricter than the docs require for a reduce-only leg, which is the safe direction. Do not relax it until the Demo cross-check observes a below-minimum-notional reduce-only algo order being accepted. The place that would change is `quantize_protective_qty` (gate 2, the `notional < constraint_snapshot.min_notional` check) and the `NOTIONAL_REJECT` path in `src/execution/placement.py`.

**Demo cross-check:** NOT YET OBSERVED

### Fact 5: MAX_NUM_ALGO_ORDERS semantics and the literal 200

**Claim:** `HEADROOM_LIMIT = 200` in `src/execution/gates.py` is a per-symbol conditional-order limit that should become dynamic by reading the exchangeInfo `MAX_NUM_ALGO_ORDERS` filter (WR-06).

**Verdict:** CONFIRMED

**Source:** https://developers.binance.com/docs/derivatives/change-log (snapshot http://web.archive.org/web/20260616125320/https://developers.binance.com/docs/derivatives/change-log); the older description is at https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition (snapshot http://web.archive.org/web/20260612145533/https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition)

**Fetched:** 2026-10-05 (snapshots dated 2026-06-16 and 2026-06-12)

**Evidence:** Change log, 2025-12-29, USDⓈ-M Futures: "The parameter "filterType": "MAX_NUM_ALGO_ORDERS" has been removed from the endpoint GET /fapi/v1/exchangeInfo . The condtional order limits is 200 across all symbols." Common Definition page (still listing the removed filter): "The MAX_NUM_ALGO_ORDERS filter defines the maximum number of all kinds of algo orders an account is allowed to have open on a symbol. The algo orders include STOP , STOP_MARKET , TAKE_PROFIT , TAKE_PROFIT_MARKET , and TRAILING_STOP_MARKET orders." with an example `"limit" : 100`.

**Code impact:** None made here. The literal 200 corresponds to a documented limit, but the limit is 200 conditional orders across all symbols, not per symbol, and the exchangeInfo filter no longer exists. Consequences for the orchestrator: the "KNOWN GAP" comment in `src/execution/gates.py` (which says per symbol and says the limit should come from exchangeInfo) is out of date, and `open_algo_count` must be the account-wide algo count, which is what the runner passes. The Common Definition page conflicts with the change log (it still describes a per-symbol filter, example limit 100); the dated change-log entry is treated as governing, matching the earlier note in docs/SOURCES.md. Making the limit dynamic is impossible from exchangeInfo; keeping a documented constant is the correct reading.

**Demo cross-check:** NOT YET OBSERVED

### Fact 6: closePosition=true STOP_MARKET with no open position

**Claim:** The exchange accepts, rejects or later cancels a `closePosition=true` STOP_MARKET algo order that is placed while no position exists (this decides how the orphaned entry-time SL in WR-07 behaves).

**Verdict:** RESOLVED on Demo: the exchange rejects it (-4509)

**Source:** https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order (snapshot http://web.archive.org/web/20260519005421/https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order), https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update (snapshot http://web.archive.org/web/20260113091316/...)

**Fetched:** 2026-10-05 (snapshots dated 2026-05-19 and 2026-01-13)

**Evidence:** New Algo Order: "STOP_MARKET , TAKE_PROFIT_MARKET with closePosition = true : ... If triggered， close all current long position( if SELL ) or current short position( if BUY )." ALGO_UPDATE page, EXPIRED: "the conditional order has been canceled by the system. An example would be when a user places a GTE_GTC Time-In-Force conditional order but then closes all positions on that symbol, resulting in system-led cancellation of the conditional order." Neither page, nor the Error Code page, says what happens when such an order is placed with no open position.

**Code impact:** None made here. The EXPIRED example concerns a GTE_GTC time-in-force order, not a plain closePosition STOP_MARKET, so it is not evidence for this case. The runner's far scenario places exactly this order (entry-time SL while the LIMIT entry is unfilled), so the Demo cross-check will answer it: placement accepted or rejected, and whether the order stays NEW afterwards.

**Demo cross-check:** OBSERVED 2026-10-05 (`--execute far`, evidence `09-DEMO-REHEARSAL-EVIDENCE-far-20261005T154847Z.json`). With the LIMIT entry resting unfilled and no position, placing the `closePosition=true` STOP_MARKET algo order failed with `BadRequestError`, `binance code -4509: Time in Force (TIF) GTE can only be used with open positions. Please ensure that positions are available.` So the exchange REJECTS it at placement; it is not accepted and later cancelled. The manager then ended ENTRY_WITHOUT_PROTECTIVE, cancelled the entry and entered SAFE_MODE (fail closed, nothing left on the account).

## Addendum

### Addendum A: Demo Trading REST base URL and algo endpoint support

**Claim:** The Demo Trading REST base URL is `https://demo-fapi.binance.com`, and the algo-order endpoints (`/fapi/v1/algoOrder`, `/fapi/v1/openAlgoOrders`) work on it.

**Verdict:** UNCONFIRMED

**Source:** https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info (snapshot http://web.archive.org/web/20260617194634/https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)

**Fetched:** 2026-10-05 (snapshot dated 2026-06-17)

**Evidence:** General Info, "Testnet API Information": "Most of the endpoints can be used in the testnet platform. The REST base url for testnet is " https://demo-fapi.binance.com "". The Websocket base url is given as "wss://fstream.binancefuture.com".

**Code impact:** None. The base URL is confirmed in substance (the docs call the environment "testnet" and give the Demo host), which matches the SDK constant the runner uses. The verdict is UNCONFIRMED because the page says only "Most of the endpoints" work there and lists neither the supported nor the unsupported ones, so algo endpoint support on Demo is not documented. The rehearsal itself is the test: an algo placement rejected on Demo for being unsupported would show in the evidence file as a failure with the exception type name.

**Demo cross-check:** NOT YET OBSERVED

### Addendum B: PERCENT_PRICE filter semantics for LIMIT orders

**Claim:** For a LIMIT order the PERCENT_PRICE filter bounds price relative to the mark price: BUY price <= markPrice * multiplierUp and SELL price >= markPrice * multiplierDown (the runner's far-entry and fill-entry prices are derived from this).

**Verdict:** CONFIRMED

**Source:** https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition (snapshot http://web.archive.org/web/20260612145533/https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition)

**Fetched:** 2026-10-05 (snapshot dated 2026-06-12)

**Evidence:** "The PERCENT_PRICE filter defines valid range for a price based on the mark price. In order to pass the percent price , the following must be true for price : BUY: price <= markPrice * multiplierUp  SELL: price >= markPrice * multiplierDown". Example filter: `{ "filterType" : "PERCENT_PRICE" , "multiplierUp" : "1.1500" , "multiplierDown" : "0.8500" , "multiplierDecimal" : 4 }`.

**Code impact:** None. Note for the runner design: for a BUY the documented bound is an upper one only, so a far BUY LIMIT below the mark is not constrained by `multiplierDown` on this page; pricing it inside the band on both sides (as planned) is safe either way. The fill scenario's BUY LIMIT above the mark must stay at or below `markPrice * multiplierUp`. The multipliers are read from exchangeInfo at run time, never hard-coded.

**Demo cross-check:** NOT YET OBSERVED

## Summary of verdicts

| Entry | Topic | Verdict | Official page used |
|-------|-------|---------|--------------------|
| Fact 1 | Query-order and algo not-found code | CONFIRMED (algo, Demo); query-order by docs | error-code, Query-Order, Query-Algo-Order, Cancel-Algo-Order |
| Fact 2 | Active algo statuses | UNCONFIRMED | user-data-streams/Event-Algo-Order-Update |
| Fact 3 | reduceOnly on CONDITIONAL algo orders | CONFIRMED | trade/rest-api/New-Algo-Order |
| Fact 4 | MIN_NOTIONAL on reduce-only legs | CONTRADICTED | error-code, common-definition |
| Fact 5 | MAX_NUM_ALGO_ORDERS and the literal 200 | CONFIRMED | change-log, common-definition |
| Fact 6 | closePosition STOP_MARKET with no position | REJECTED on Demo (-4509) | New-Algo-Order, Event-Algo-Order-Update |
| Addendum A | Demo REST URL and algo endpoint support | UNCONFIRMED | general-info |
| Addendum B | PERCENT_PRICE semantics | CONFIRMED | common-definition |

## Open items

- Fact 1: settled for Query Algo Order (Demo returns `-2013`, mapped). Query Order on Demo is still unobserved; one more read-only probe would close it.
- Fact 2: whether TRIGGERING and TRIGGERED should count as active; the docs list the values but do not classify them.
- Fact 6: behaviour of a closePosition STOP_MARKET placed with no open position; not documented.
- Addendum A: whether the algo endpoints are supported on Demo; the docs say only "Most of the endpoints".
- Not UNCONFIRMED but worth a re-check against the live pages: every verdict here rests on Wayback snapshots dated between 2026-01-13 and 2026-06-17, and Fact 5 rests on a change-log entry that conflicts with the Common Definition page.
