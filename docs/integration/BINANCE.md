# Binance Integration

## 1. Product

Target integration: Binance USDⓈ-M Futures (`fapi`).

Always re-check the official USDⓈ-M docs before implementation because endpoints and order semantics can change.

Official documentation entry points:

- [USDⓈ-M Futures API](https://developers.binance.com/docs/derivatives/usds-margined-futures/)
- [New Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)
- [Market Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api)

## 2. Python SDK

Use the current official Binance Python connector for USDⓈ-M Futures where its supported API surface matches the requirement. The current SDK family supports REST, WebSocket API and WebSocket Streams and documents Python 3.10+ support.

Wrap SDK clients behind project adapters. Do not let SDK-generated/Pydantic response models become domain entities.

The dependency version must be pinned/locked by the project environment and re-verified during upgrades.

## 3. Market data

Use:

- REST for bootstrap/history/reconciliation.
- WebSocket for realtime market events.

Binance is believed to document a 24-hour validity for a single market WebSocket connection, ping/pong requirements, stream limits, and to recommend WebSocket user data for order/position status when REST may be delayed under volatility. [Binance WebSocket market streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market-data-streams) These statements were not confirmed on a fetched page on 2026-09-30; verify against current Binance docs before implementation.

WebSocket URL paths (F-053): streams are served on separate paths of `wss://fstream.binance.com`:

- `/public`: order-book style streams such as bookTicker and depth;
- `/market`: aggTrade, markPrice, kline, ticker and similar market streams;
- `/private`: user data streams, connected with a listenKey.

The legacy single `/ws` endpoint was scheduled for retirement on 2026-04-23 ("permanently decommissioned" after that date), and a connection that was not migrated only receives `/public` data. The adapter must therefore open the path that matches each stream family and treat a silent socket on the legacy URL as a defect. Sources: [Important WebSocket Change Notice](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice) and the [Futures change log](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log) (2026-03-05 new URL path sections, 2026-04-02 decommissioning date); verify against current Binance docs before implementation.

## 4. Kline processing

Strategy should normally evaluate only closed candles.

For WebSocket kline streams, implement and test the closed-candle state rather than recalculating a live strategy from an unfinished candle.

## 5. User data

Use the user-data stream to receive order/position/account events. It is consumed on the `/private` path with a listenKey (section 3, F-053); verify against current Binance docs before implementation.

Binance currently documents `ORDER_TRADE_UPDATE` events and statuses such as `NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, and `EXPIRED`. [Binance user data streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/user-data-streams)

## 6. Orders

The execution layer must support only the order types explicitly required by the frozen strategy.

Do not implement every Binance order type preemptively.

Conditional orders such as `STOP_MARKET` / `TAKE_PROFIT_MARKET` were migrated to the USDⓈ-M Algo Order service. The implementation must use the current Algo Order endpoints and `ALGO_UPDATE` lifecycle for these order types; do not assume the legacy normal-order endpoint accepts them. Flags such as `reduceOnly`, `closePosition`, position side, working type, and GTD must be verified against the current Algo Order API. [Binance Futures changelog](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log)

Working type (D037): protective triggers use the mark-price series, so `workingType` must be sent explicitly as `MARK_PRICE` on every protective order. The Algo Order API default is `CONTRACT_PRICE`, so the adapter must never rely on the default. The audit's alternative `CONTRACT_PRICE` recommendation is not adopted. [Binance New Algo Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order) Verify against current Binance docs before implementation.

## 7. Position mode

The application must read and record:

- One-way/Hedge mode,
- Multi-Assets/Single-Asset mode where relevant,
- leverage/configuration,
- symbol filters, read from `exchangeInfo` and never hard-coded.

Symbol filters that constrain sizing (F-056): besides the price, lot and minimum-notional filters, read `MARKET_LOT_SIZE` (the quantity rules for MARKET orders: quantity within minQty and maxQty on the stepSize grid) and `PERCENT_PRICE` (the valid price range relative to the mark price: a BUY price at most markPrice times multiplierUp, a SELL price at least markPrice times multiplierDown). [Binance common definitions](https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition) The page describing them is otherwise stale on the conditional-order limit (see `SOURCES.md`); verify against current Binance docs before implementation.

Unverified audit claims (F-056): that a triggered `*_MARKET` protective exit with an explicit quantity falls under `MARKET_LOT_SIZE`, and that reduce-only legs skip `MIN_NOTIONAL`, come from the audit and are not confirmed by the fetched pages. They are unverified and must be confirmed on the demo environment before Phase 19; until then treat both as possible rejection causes.

## 8. OI

Current OI endpoint is available for a symbol. Historical Open Interest Statistics are documented as limited to the latest month; use a collector for long-term research data. [Binance Open Interest](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)

## 9. Conditional/algo orders

Track normal orders and algo/conditional orders separately. On reconnect or recovery, query both sets before resuming live approval. Binance documents separate current-open-algo-order endpoints and an `ALGO_UPDATE` event family. The `ALGO_UPDATE` statuses and the trigger-time failure modes (FINISHED does not mean filled; REJECTED and EXPIRED can occur after the stop was accepted) are specified in `EXECUTION_SPEC.md` section 6.1 (F-054), and the 200 open conditional-order limit is account-wide (`EXECUTION_SPEC.md` section 12).

## 10. Reconciliation

Startup:

```text
connect
→ bootstrap orders/positions
→ start user data stream
→ compare state
→ only then enable live approval
```

After disconnect:

```text
reconnect
→ query authoritative state
→ replay/refresh local state
→ resume
```

## 11. Security

API key must not have withdrawal permissions.

Prefer IP restrictions and secret storage outside source control.
