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

Binance documents a 24-hour validity for a single market WebSocket connection, ping/pong requirements, stream limits, and recommends WebSocket user data for order/position status when REST may be delayed under volatility. [Binance WebSocket market streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market-data-streams)

## 4. Kline processing

Strategy should normally evaluate only closed candles.

For WebSocket kline streams, implement and test the closed-candle state rather than recalculating a live strategy from an unfinished candle.

## 5. User data

Use the user-data stream to receive order/position/account events.

Binance currently documents `ORDER_TRADE_UPDATE` events and statuses such as `NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, and `EXPIRED`. [Binance user data streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/user-data-streams)

## 6. Orders

The execution layer must support only the order types explicitly required by the frozen strategy.

Do not implement every Binance order type preemptively.

Conditional orders such as `STOP_MARKET` / `TAKE_PROFIT_MARKET` were migrated to the USDⓈ-M Algo Order service. The implementation must use the current Algo Order endpoints and `ALGO_UPDATE` lifecycle for these order types; do not assume the legacy normal-order endpoint accepts them. Flags such as `reduceOnly`, `closePosition`, position side, working type, and GTD must be verified against the current Algo Order API. [Binance Futures changelog](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log)

## 7. Position mode

The application must read and record:

- One-way/Hedge mode,
- Multi-Assets/Single-Asset mode where relevant,
- leverage/configuration,
- symbol filters.

## 8. OI

Current OI endpoint is available for a symbol. Historical Open Interest Statistics are documented as limited to the latest month; use a collector for long-term research data. [Binance Open Interest](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)

## 9. Conditional/algo orders

Track normal orders and algo/conditional orders separately. On reconnect or recovery, query both sets before resuming live approval. Binance documents separate current-open-algo-order endpoints and an `ALGO_UPDATE` event family.

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
