# Sources

Core design uses current official documentation where available. Re-check API details immediately before implementation.

## Binance USDⓈ-M Futures

- [USDⓈ-M Futures API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures)
- [Exchange Information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)
- [Open Interest Statistics](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)
- [Trade / Algo Order documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)
- [WebSocket Market Streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Connect)
- [User Data Streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/user-data-streams)
- [Futures change log](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log)

## TradingView

- Strategy Tester / Backtesting / Forward Testing documentation.
- Strategy Alerts documentation.
- Webhook Alerts documentation.

TradingView is a research/cross-check tool in this project, not the canonical execution authority.


## Python / project tooling

- [Python version documentation](https://www.python.org/doc/versions/)
- [Python 3.14.7 release](https://www.python.org/downloads/release/python-3147/)
- [Binance modular Python connector](https://github.com/binance/binance-connector-python)
- [Binance USDⓈ-M Futures Python SDK](https://github.com/binance/binance-connector-python/tree/master/clients/derivatives_trading_usds_futures)

Python runtime/dependency compatibility should be re-checked before upgrades.

## Facts verified for Phase 11 (2026-09-30)

Every exchange fact edited in Phase 11 is grounded in a page listed here (D-14). Fetch date and retrieval method are recorded honestly; a fact whose page could not be retrieved carries a "verify against current Binance docs before implementation" marker in the document that states it.

| Source URL | Used for | Checked on | Method |
| --- | --- | --- | --- |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log | 200 conditional orders across all symbols (account-wide) and removal of the `MAX_NUM_ALGO_ORDERS` filter on 2025-12-29; no margin check before a conditional order triggers and the migration of conditional orders to the Algo Service (2025-11-06, effective 2025-12-09); `ALGO_UPDATE` migration; WebSocket URL path sections (2026-03-05) and legacy URL decommissioning date 2026-04-23 (announced 2026-04-02) | 2026-09-30 | WebFetch (orchestrator, summarised by the tool's small model); MEDIUM confidence, keep the verify markers |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition | `MARKET_LOT_SIZE` (quantity rules for MARKET orders: quantity >= minQty, quantity <= maxQty, (quantity - minQty) % stepSize == 0) and `PERCENT_PRICE` (valid price range based on the mark price: BUY price <= markPrice * multiplierUp, SELL price >= markPrice * multiplierDown). Note: this page still describes `MAX_NUM_ORDERS` and `MAX_NUM_ALGO_ORDERS` as per-symbol filters and is stale against the dated change-log entry of 2025-12-29, which governs | 2026-09-30 | WebFetch (orchestrator, summarised by the tool's small model) |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice | WebSocket URL split: `wss://fstream.binance.com/public`, `/market`, `/private`; legacy single `/ws` endpoint retired 2026-04-23, an unmigrated connection only receives `/public` data | 2026-09-30 | WebFetch (research session, recorded in 11-RESEARCH.md); not re-fetched by the executor |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order | `workingType` values `MARK_PRICE` / `CONTRACT_PRICE` with API default `CONTRACT_PRICE`; `closePosition` constraints (not with `quantity`, not with `reduceOnly`, whole current position when triggered); `TRAILING_STOP_MARKET` can be rejected at placement with -2021 | 2026-09-30 | WebFetch (orchestrator, summarised by the tool's small model) |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update | `ALGO_UPDATE` field names (`X` algo status, `rm` failed reason, `ia` is-activated) and the status meanings NEW / TRIGGERING / FINISHED / REJECTED / EXPIRED | 2026-09-30 | SDK model (installed `algo_update_o.py`, field descriptions only) plus a search summary of the page; the official page could not be retrieved (WebFetch returned only the documentation shell). The status wording needs re-confirmation on the official page before Phase 18 |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Connect | Connection behaviour of market streams, including the believed 24-hour connection lifetime | 2026-09-30 (not fetched) | Not fetched: curl with a browser user-agent got a 302 redirect for this path and then HTTP 202 with an empty body. The 24-hour figure is NOT confirmed by any fetched page and keeps its verify marker |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams | User-data stream landing page (keepalive/reconnect requirements, order/position updates preferred over REST under volatility) | 2026-09-30 (not fetched) | Not fetched: curl with a browser user-agent got a 302 redirect and then HTTP 202 with an empty body; the sibling page Event-Algo-Order-Update sits under this path. Statements citing it keep the verify marker |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Position-Mode | Position-mode change restrictions: rejected when open orders (-4067) or an open position (-4068) exist | 2026-09-30 (not fetched) | Not fetched: curl with a browser user-agent got a 302 redirect to the catalog anchor `#change-position-mode` and then HTTP 202 with an empty body. The wording is grounded in the installed SDK docstring of `POST /fapi/v1/positionSide/dual`; verify before implementation |
| https://www.tradingview.com/support/solutions/43000529348-about-webhooks/ | TradingView webhook behaviour used by TRADINGVIEW.md section 5 (plan 11-06, F-052): the page lists source IP addresses, a 2FA requirement and HTTP POST delivery | 2026-09-30 | curl by the executor (HTTP 200, page text searched for the listed items; no summarising tool) |

## Facts verified for Phase 12 (2026-09-30)

Every exchange fact used by the Phase 12 live commission-rate read is grounded in a source listed here (D-13). Fetch date and retrieval method are recorded honestly; a fact whose page could not be retrieved directly keeps the "verify against current Binance docs before implementation" marker in the document that states it.

| Source URL | Used for | Checked on | Method |
| --- | --- | --- | --- |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate | `GET /fapi/v1/commissionRate`, weight 20 (IP), security type USER_DATA (signed); parameters `symbol` (required) and `recvWindow` (optional); response fields `symbol` / `makerCommissionRate` / `takerCommissionRate` / `rpiCommissionRate`, all strings (example values 0.0002, 0.0004, 0.00005) | 2026-09-30 | WebSearch result text for the official page (research session, recorded in 12-RESEARCH.md); a direct WebFetch of the page returned another endpoint's content and curl returned an empty body, and a second curl attempt by the plan-05 executor got a redirect and no page text, so the official page was NOT read directly. Cross-checked against the installed SDK 17.4.0 method `rest_api.user_commission_rate(symbol, recv_window=None)` and the model `UserCommissionRateResponse` (all four fields Optional strings, docstring weight 20 and USER_DATA) and against the change-log entry that the RPI commission field is effective 2025-11-26. MEDIUM confidence; the exact field semantics and the weight need re-confirmation on the official page before Phase 24 wires it |
| https://developers.binance.com/docs/derivatives/change-log | The `rpiCommissionRate` response field of the User Commission Rate endpoint is effective 2025-11-26; the adapter ignores it (sizing uses the taker rate, D036) | 2026-09-30 | WebFetch (research session, summarised by the tool's small model); MEDIUM confidence |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate (Binance Demo / testnet behavior) | Whether the Demo or testnet environment serves `GET /fapi/v1/commissionRate` and what it returns | 2026-09-30 (not documented) | Not documented in any retrieved material (search summary, change-log, installed SDK). Unknown; it is verified in the Phase 24 demo stage. Until then no code depends on a Demo response and the resolver fails closed on any missing rate |
