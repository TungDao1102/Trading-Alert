# Sources

Core design uses current official documentation where available. Re-check API details immediately before implementation.

## Binance USDⓈ-M Futures

- [USDⓈ-M Futures API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures)
- [Exchange Information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)
- [Open Interest Statistics](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)
- [Trade / Algo Order documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)
- [WebSocket Market Streams](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/websocket-market-streams/Connect)
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

| Source URL | Used for | Fetched | Method |
| --- | --- | --- | --- |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log | 200 conditional orders across all symbols (account-wide) and removal of the `MAX_NUM_ALGO_ORDERS` filter on 2025-12-29; no margin check before a conditional order triggers and the migration of conditional orders to the Algo Service (2025-11-06, effective 2025-12-09); `ALGO_UPDATE` migration; WebSocket URL path sections (2026-03-05) and legacy URL decommissioning date 2026-04-23 (announced 2026-04-02) | 2026-09-30 | WebFetch (orchestrator, summarised by the tool's small model); MEDIUM confidence, keep the verify markers |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition | Note: this page still describes `MAX_NUM_ORDERS` and `MAX_NUM_ALGO_ORDERS` as per-symbol filters and is stale against the dated change-log entry of 2025-12-29, which governs | 2026-09-30 | WebFetch (orchestrator, summarised by the tool's small model) |
