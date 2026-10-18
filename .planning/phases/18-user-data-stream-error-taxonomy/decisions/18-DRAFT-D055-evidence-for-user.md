DRAFT FOR THE USER. NOT A DECISION. D055 stays OPEN until the user records a new DECISIONS row.

# 18-DRAFT-D055: what the Demo probe showed about the protective-stop execution model

Written by plan 18-25 on 2026-10-18. Every fact below is copied from `evidence/18-probe-check.txt` ("Facts for plan 18-21" and "SECOND RUN") without interpretation, and is demo-observed, not mainnet, not verified on mainnet. The raw evidence files are `evidence/demo-probe-EVIDENCE-20261016T142134Z.json` (first run) and `evidence/demo-probe-EVIDENCE-20261016T173612Z.json` (second run). Both runs: DEMO, BTCUSDT, quantity 0.0008, 16 required cases, optional cases off, transport sdk, cleanup FLAT. This file writes no DECISIONS row, edits no decision file and chooses nothing.

## The four items of D055 (docs/DECISIONS.md D055, read only)

1. The execution model is NOT chosen. The two candidates are (a) place protection after the entry fill and (b) pre-place a suitable protective STOP_MARKET before the entry fill. The choice waits for the Demo probe, then for a later user decision recorded as a new row.
2. Safety invariants that hold in every model: a position is never treated as healthy until Binance has confirmed the protective stop; no new entry opens while any position is unprotected; no LIVE execution until D055 is closed with a verified execution policy; a successful API call that placed a stop is not evidence that the position is protected.
3. The Demo probe cases (feasibility and safety verification only, never used to choose a trading parameter): pre-place a STOP_MARKET with an explicit quantity and reduceOnly while no position exists; an entry that never fills and is cancelled (is the protective order orphaned, does it cancel cleanly); a full fill (does the protective order protect exactly the filled quantity); a partial fill; a rejected protective order; reconciliation after each state.
4. Alternative (b) with explicit quantity was UNVERIFIED on Demo before the probe; nothing in D055 asserts it works.

## What the probe showed, per candidate model

### Model (a): place protection after the entry fill

| Question | What the probe showed (copied from the check file) |
| --- | --- |
| Accepted or rejected, exact answer | Close-position variant (`closePosition`) while flat: rejected (BAD_REQUEST, -4509, "Time in Force (TIF) GTE can only be used with open positions. Please ensure that positions are available."). With the position open, a reduce-only STOP_MARKET of quantity 0.0001 (notional 7.890670 against min_notional 50) was ACCEPTED (status NEW); GET order on its algo id: (BAD_REQUEST, -2013, "Order does not exist."). A close-position stop with the position open, and a stop of the full position quantity placed after the fill, were not cases of the probe and are not recorded in the check file. |
| Orphan behavior | Not applicable to this model in the check file (no entry rests unprotected in a case of this shape). |
| Quantity relation on a full fill | Not recorded for a stop placed after the fill. |
| Partial fill observed or not | Not observed (every marketable entry filled completely). |
| Effect on the invariants of D055 item 2 | Not interpreted by this draft. The recorded facts that bear on it: the stop that is rejected while flat is rejected with -4509; the stop placed with a position open was accepted at placement (status NEW); the check file records no case of a stop placed after a real full-size fill. |

### Model (b): pre-place a protective STOP_MARKET with an explicit quantity before the fill

| Question | What the probe showed (copied from the check file) |
| --- | --- |
| Accepted or rejected, exact answer | Pre-placed explicit-quantity reduce-only STOP_MARKET while flat: accepted (status NEW, quantity 0.0008); it stays listed as one open algo order; GET order on its algo id: (BAD_REQUEST, -2013, "Order does not exist."); reconciliation open_orders=0 open_algo_orders=1 position=0 matched. |
| Orphan behavior | The protective STOP_MARKET placed while the entry rests stayed status NEW after the entry was cancelled (leg_status_after_entry_cancel NEW), was still queried as NEW, and cancelled cleanly (leg_cancel_clean true); orphaned true; reconciliation open_orders=0 open_algo_orders=0 position=0 matched. |
| Quantity relation on a full fill | Entry FILLED at 0.0008 (average price 82254.4); the pre-placed reduce-only STOP_MARKET quantity 0.00080 equals the position amount 0.0008 (protective_quantity_equals_position true); leg status after the fill NEW; reconciliation open_orders=0 open_algo_orders=1 position=0.0008 matched. |
| Partial fill observed or not | Not observed (every marketable entry filled completely at the approved size). |
| Effect on the invariants of D055 item 2 | Not interpreted by this draft. The recorded facts that bear on it: the pre-placed leg stays NEW (an open algo order) when no position exists and when the entry is cancelled (it must be cancelled explicitly); after a full fill its quantity equals the position amount; the REST algoStatus values seen were NEW only. |

### Rejected protective variants (both models)

Close position while flat (BAD_REQUEST, -4509, same message as above); reduce-only together with close position (BAD_REQUEST, -1106, "Parameter 'reduceonly' sent when not required."); wrong-side trigger (BAD_REQUEST, -2021, "Order would immediately trigger."). The error category of each code is the one of `src/domain/exchange_errors.py` (the owner's taxonomy decision of 2026-10-17 is `decisions/18-DEC-TAXONOMY-CODES.md`); a rejected protective order is never evidence that the position is protected.

## What the probe could not observe

- A partial fill (every marketable entry filled completely): how quantity and protection behave on a partial fill is unknown.
- The triggered lifecycle of a conditional order (the trigger was not reached within case_timeout_seconds): the algo statuses seen by REST were NEW only; the child order identity (ai, aq, c and i) was not carried by any ALGO_UPDATE or child ORDER_TRADE_UPDATE frame; REST actual_order_id was empty. Whether a protective stop executes when triggered was not observed.
- A stop of the full position quantity placed after a real fill (model a as designed), and a close-position stop with a position open: no such case.
- What happens to a pre-placed leg when the position is closed by other means (the check file records no such case).
- MARKET_LOT_SIZE for a triggered market exit above the maximum (optional case off; Demo market lot filters min 0.0001, max 120, step 0.0001).
- Anything on mainnet, any other symbol, hedge mode, or any other day. Demo is not the production exchange.

## What this draft does not do

It chooses nothing. It does not close D055, writes no DECISIONS row and changes no execution code or document statement about the model: the execution model stays the user's open decision, and the invariants of D055 item 2 (including "no LIVE execution until D055 is closed with a verified execution policy") still hold.
