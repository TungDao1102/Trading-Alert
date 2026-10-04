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

## 15. Phase 13 research data rules

These rules describe what the Phase 13 code enforces (D049). File layouts are in `data/DATA_MODEL.md` section 2.13 and exchange facts in `integration/BINANCE.md` section 13.

Publishing candles:

- Closed-day publish (D-13): the paginator clamps the window end to the start of the current UTC day and publishes a day file only when the whole day lies inside the window (or it is the terminal day of a delivered contract). A partly covered day is held back, logged and never advances the cursor, so the current forming day is never written.
- Atomic, immutable publish (D-14): every file is written to a temporary file in the same directory, flushed, and moved into place with `os.replace` (up to five attempts, because Windows can refuse a replace while another process holds the file). An existing file is never overwritten; a crash leaves neither a torn `part.parquet` nor a temporary file that a `date=*/part.parquet` glob could pick up. The OI and funding tick writers use the same routine.
- Zero-trade acceptance and precision (D-15): a bar with zero trades is valid telemetry (delisted contracts serve such flat bars) and is counted, not rejected; a negative trade count is rejected. A price or quantity that is not finite or has more than 8 fractional digits is rejected and counted, because the Parquet scale is 8 and rounding would change stored values silently.

History windows and sources:

- Delivery cap (D-26): each symbol's window is `max(depth start, onboard time)` to `min(run day floor, deliveryDate)`. A contract that is not TRADING and has no `deliveryDate`, or a symbol exchangeInfo no longer lists, gets no REST window (`DELIVERY_UNKNOWN`) and is refused instead of being fetched up to today, because the exchange serves invented flat bars after delivery.
- Archive fallback (D-08): REST is tried first per symbol; only a REST -1121 or a symbol absent from exchangeInfo moves it to data.binance.vision, whose zips are sha256-checked (transport integrity only), size-capped and read in memory, then pass through the same paginator, quality gate, closed-day rule and atomic publisher. Mark klines are REST-only and become `UNAVAILABLE` otherwise; a symbol no source serves is `UNAVAILABLE` in the sufficiency report and unrankable in the freeze report, never silently dropped.
- Resume: one cursor file per dataset, symbol and interval (`<cursor-root>/<SYMBOL>_<interval>.cursor` for trade data, a `mark__` prefix for the mark dataset), plus a store floor at the day after the latest published partition, so an interrupted run resumes without publishing any day twice. A store that already holds a short recent bootstrap for a symbol starts its resume after that bootstrap, so the depth run should start from an empty raw root or be read against the sufficiency report, where the missing history shows as `GAP`.
- Depth and funding: 1m defaults to 12 months and 1h and 4h to 24 months before the run date (D-04; the Phase 13 research store was backfilled with `--depth-1m-months 24` after the user's D-21 decision); funding history is collected over the 1h/4h range per symbol, and a funding failure records a `collector_gaps` row instead of stopping the run.

Building backtest inputs:

- The case-input builder (D-19, `src/data/case_input.py`) reads an explicit per-day file list, refuses an unresolved gap with `CaseInputGapError` before any row is produced, and never pads, forward-fills or interpolates. A gap is one shared definition (`src/data/coverage.py`): a hole between consecutive rows larger than the maximum step, a first row later than the start allowance, or an end more than the maximum step after the last row; funding tolerates 8 hours plus 60 seconds and open interest twice its 5-minute cadence. A caller may pass `allow_gaps` entries equal to real gaps; those are recorded on the output. The range must end on or before an explicit `as_of_day_utc`; the module reads no wall clock.
- The builder returns the `dataset_id` (`DATA_MODEL.md` section 2.13) that the backtest assembly takes as `data_snapshot_id`.

Realtime seam (D-16, D-28), for the paper supervisor: on reconnect or scheduled rotation the order is close the old stream, backfill the missed closed candles, record them, start the new subscription, then run one verification backfill after it is attached. A single lock-guarded monotonic last-close cursor gates both the WebSocket handler and the backfill, so a close at or before the last processed close is dropped and no close is delivered twice or skipped across a reconnect. A pair whose first backfill failed is journaled once as an outage gap and still resubscribes.

Collector (D-25): the loop sleeps to the next 5-minute grid boundary so a slow tick cannot stretch the period; a warn-only exchange-clock probe logs the offset at start and never blocks. Fail-closed clock checks belong to Phase 18 and the deployment-level time synchronization to Phase 13.1.
