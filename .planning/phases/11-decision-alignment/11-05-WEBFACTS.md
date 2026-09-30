# Plan 11-05 — Binance page fetches (orchestrator, WebFetch, 2026-09-30)

The gsd-executor agent has no WebFetch, so the orchestrator fetched these pages on 2026-09-30 and recorded the results here. Method to record in docs/SOURCES.md: "WebFetch (orchestrator, summarised by the tool's small model), 2026-09-30". Quotes are the tool's verbatim extracts; treat them as MEDIUM confidence and keep the "verify against current Binance docs before implementation" markers.

## https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log
- 2025-12-29: "The parameter 'filterType': 'MAX_NUM_ALGO_ORDERS' has been removed from the endpoint `GET /fapi/v1/exchangeInfo`. The conditional order limits is 200 across all symbols."
- 2025-11-06 (effective 2025-12-09): conditional orders migrate to the Algo Service. STOP_MARKET / TAKE_PROFIT_MARKET / STOP / TAKE_PROFIT / TRAILING_STOP_MARKET on the old endpoint are blocked with error -4120 STOP_ORDER_SWITCH_ALGO. "No margin check before the conditional order gets triggered."
- 2026-03-05: new WebSocket URL PATH sections: `/public`, `/market` for market streams; `/private` for user data streams.
- 2026-04-02: legacy WebSocket URL decommissioning date announced as 2026-04-23.
- 2026-08-21: ALGO_UPDATE `ia` (isActivated) is fully active; for trailing stops before trigger (status X remains NEW) two NEW events may arrive, `ia:false` then `ia:true`.

## https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update
- WebFetch returned only the generic docs landing shell again (no status table, no `o.rm`). FALLBACK per plan: the installed SDK model `.venv/Lib/site-packages/binance_sdk_derivatives_trading_usds_futures/websocket_streams/models/algo_update_o.py` field descriptions, plus the research file's search-snippet note (FINISHED = filled or canceled). Record the method honestly as "SDK model + search summary; official page not retrievable" and keep the verify marker on the FINISHED/REJECTED/EXPIRED wording.

## https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
- `workingType`: values MARK_PRICE / CONTRACT_PRICE; default CONTRACT_PRICE.
- `closePosition` (STOP_MARKET / TAKE_PROFIT_MARKET only): cannot be sent with `quantity`; cannot be used with `reduceOnly`; in Hedge Mode not with BUY on LONG side or SELL on SHORT side. When triggered it closes the whole current position.
- TRAILING_STOP_MARKET can be rejected at placement with -2021 "Order would immediately trigger".

## https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition
- MARKET_LOT_SIZE: rules for `quantity` of MARKET orders: quantity >= minQty, quantity <= maxQty, (quantity - minQty) % stepSize == 0.
- PERCENT_PRICE: valid range based on mark price. BUY: price <= markPrice * multiplierUp. SELL: price >= markPrice * multiplierDown.
- STALE PAGE: this page still describes MAX_NUM_ORDERS and MAX_NUM_ALGO_ORDERS as per-symbol. It contradicts the change-log entry of 2025-12-29 (limit 200 across all symbols, filter removed). Cite the change-log for the 200 limit and note the definitions page is stale.

## Not fetched here
- Change-Position-Mode page and the TradingView webhook page: the executor should attempt `curl`; if unreachable, add a verify marker and record "not fetched" in SOURCES.md rather than guessing (D-14).
