# Data Pipeline

## 1. Canonical source

Primary trading market data source: Binance USDⓈ-M Futures.

TradingView is optional for visualization/research/webhook experiments; it is not the canonical execution data source.

## 2. Data classes

### Historical / realtime candles

Required initially:

- 1m for execution simulation.
- 1H for setup logic.
- 4H for regime/context.

Later if strategy requires:

- 15m.

Binance USDⓈ-M provides kline/candlestick data through the Futures API; current documentation should be checked again before implementation because endpoints and schemas can change. [Binance API](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)

## 3. Futures context

Initial optional features:

- mark price,
- funding rate,
- open interest,
- taker buy/sell volume.

Open interest:

- current OI endpoint: `/fapi/v1/openInterest`;
- historical statistics endpoint: `/futures/data/openInterestHist`;
- Binance currently documents historical OI statistics as limited to the latest 1 month.

Therefore, an `OpenInterestCollector` should persist snapshots independently if OI becomes a feature.

## 4. WebSocket requirements

- Use closed candle events for strategy decisions.
- Maintain connection heartbeat/reconnect.
- Detect gaps.
- Re-bootstrap after reconnect if local state is uncertain.
- Do not assume a WebSocket connection is permanent.

## 5. Warm-up

On service startup:

```text
REST historical candles
    ↓
validate continuity
    ↓
seed indicator state
    ↓
start/attach WS
    ↓
verify latest closed candle
```

Indicators such as EMA200 on 4H require sufficient history before strategy evaluation.

## 6. Data quality rules

Reject/flag:

- duplicate candle timestamps,
- impossible OHLC relationships,
- timestamp regressions,
- missing sequence where continuity is required,
- stale feed,
- symbol metadata mismatch.

## 7. Storage timestamps

All DB timestamps UTC.

UI may display `Asia/Ho_Chi_Minh`.

## 8. Raw vs derived data

Persist enough raw market observations to reproduce important strategy calculations.

Derived features should include:

- calculation timestamp,
- source candle close time,
- algorithm version where relevant.

## 9. OI collector

Recommended immediately, even before OI is used by strategy:

```text
Every N minutes
  → GET current OI
  → persist timestamp + symbol + OI
```

Sampling interval must be chosen based on research need and API/rate limits rather than arbitrary high frequency.

## 10. Historical coverage and universe normalization

The research universe must record per-symbol availability using exchange metadata rather than assuming all symbols have equal history.

For each symbol, persist:

```text
onboard_time_utc
status_history
historical_data_start_utc
historical_data_end_utc
```

Backtest reports must state the effective date range per symbol. Do not compare a 3-year BTC sample directly to a shorter-alt sample without showing the difference.

## 11. Storage and partitioning

For an illustrative 5-symbol × 3-year 1m dataset:

```text
5 × 3 × 365 × 24 × 60 ≈ 7.9 million candles
```

PostgreSQL can handle this scale, but the design should support monthly partitioning by `open_time_utc` and an index such as:

```text
(symbol, open_time_utc)
```

Partitioning is a storage/query optimization, not a reason to split the core into microservices.

## 12. Phase-0 data acquisition

The OI collector must begin as soon as practical during research.

Historical candles and historical funding can be backfilled later; OI history outside Binance's documented API window cannot be recreated from that API. The collector is therefore an explicit Phase-0 workstream.

## 13. Storage architecture

Separate analytical and operational storage:

```text
Binance raw data
    ↓
Parquet (immutable research/raw)
    ↓
DuckDB / Polars / pandas (analysis)

Operational events / orders / positions
    ↓
PostgreSQL
```

Do not make PostgreSQL the only storage layer for the historical market dataset. Partition large candle datasets by symbol/date where practical and index operational tables by the lookup paths defined in `data/DATA_MODEL.md`.

## 14. Python implementation rule

The collector may use the Binance Python SDK and asyncio, but the normalized domain data passed to the strategy must be project-defined types/models. SDK classes and raw JSON must not leak into the strategy layer.
