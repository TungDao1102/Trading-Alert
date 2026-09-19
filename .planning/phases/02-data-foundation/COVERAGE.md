---
phase: 02-data-foundation
plan: 01
subsystem: data-foundation
tags: [binance-sdk, market-data, oi, funding, exchangeInfo, coverage-matrix]
status: complete
sdk_reverified: 2026-09-19
sdk_version_pinned: "binance-sdk-derivatives-trading-usds-futures>=17.3,<18 (lockfile resolved 17.4.0)"
---

# Phase 2 — Binance Endpoint Coverage Matrix

> **Authority chain:** `docs/DECISIONS.md` → `docs/architecture/DATA_PIPELINE.md`
> → `docs/integration/BINANCE.md` → this matrix. Per D-03, SDK method names
> and response field names are re-verified at implementation start; this file
> records the verified names against the installed 17.x package and the
> current official Binance docs (fetched 2026-09-19).

## Re-verification method

The 17.x SDK (`binance-sdk_derivatives_trading_usds_futures`, lockfile
`17.4.0`) was installed via `uv sync` from the lockfile resolved by this
plan. Each method name + parameter list below was confirmed by introspecting
the installed package (`inspect.signature(...)`) and a live weight-1 call to
`GET /fapi/v1/time` succeeded with `X-MBX-USED-WEIGHT-1M: 1`.

| Endpoint | SDK client method | Verified parameters | Response model | Status |
|----------|-------------------|---------------------|----------------|--------|
| `GET /fapi/v1/time` | (no SDK helper; raw `requests` for weight-1 probe) | — | `{"serverTime": <ms>}` | VERIFIED weight-1 reachability today |
| `GET /fapi/v1/exchangeInfo` | `client.rest_api.exchange_information()` | none | `ExchangeInformationResponse` (`serverTime`, `timezone`, `symbols[]`, `rateLimits[]`) | VERIFIED; live BTCUSDT snapshot trimmed into `tests/fixtures/exchange_info_sample.json` |
| `GET /fapi/v1/klines` | `client.rest_api.kline_candlestick_data(symbol, interval, start_time?, end_time?, limit?)` | `symbol: str`, `interval: KlineCandlestickDataIntervalEnum`, `start_time: int?`, `end_time: int?`, `limit: int?` (max 1500) | `KlineCandlestickDataResponse` (array-of-arrays via `from_dict` → list of pydantic wrappers) | VERIFIED signature; per-row field order is Binance's documented `[openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, takerBuyBase, takerBuyQuote, ignore]` |
| `GET /fapi/v1/openInterest` | `client.rest_api.open_interest(symbol)` | `symbol: str` | `OpenInterestResponse` (`openInterest: str`, `symbol: str`, `time: int`) | VERIFIED signature + field shapes via `model_json_schema()` |
| `GET /fapi/v1/fundingRate` | `client.rest_api.get_funding_rate_history(symbol?, start_time?, end_time?, limit?)` | `symbol: str?`, `start_time: int?`, `end_time: int?`, `limit: int?` (max 1000) | `GetFundingRateHistoryResponseInner[]` (`symbol`, `fundingRate`, `fundingTime`, `markPrice?`, `rateType?`) | VERIFIED signature + field shapes via `model_json_schema()` |
| `GET /futures/data/openInterestHist` | `client.rest_api.open_interest_statistics(symbol, period, limit?)` | `symbol: str`, `period: OpenInterestStatisticsPeriodEnum` (5m/15m/30m/1h/2h/4h/6h/12h/1d), `limit: int?` (max 500, default 30) | `OpenInterestStatisticsResponseInner[]` (sumOpenInterest, sumOpenInterestValue, timestamp; **latest 1 month only** per official docs) | VERIFIED signature; **OPPORTUNISTIC ONLY** — self-collected `openInterest` is canonical (D-08) |

## Capability matrix

| Capability | Endpoint | Disposition | Plan ref | Reason / notes |
|------------|----------|-------------|----------|----------------|
| **klines** | `GET /fapi/v1/klines` | **INTEGRATE** | 02-02, 02-03 | Candle backfill (1m/1H/4H) for the live-5 (D-01). Weight-aware pacing, deterministic windowed cursor, forming-candle drop, idempotent re-run (D-02, RESEARCH §Pitfall 1+5). |
| **exchangeInfo** | `GET /fapi/v1/exchangeInfo` | **INTEGRATE** | 02-03 | Versioned `symbol_metadata` snapshots — never hard-coded tick/step/notional (D-03, ENGINEERING_PRINCIPLES Decimal rule). New row per fetch, readers pin `observed_at ≤ dataset date` (RESEARCH Pattern 4). |
| **openInterest** | `GET /fapi/v1/openInterest` | **INTEGRATE** | 02-02 | Day-one 5-min self-collected snapshot stream (D-07). Canonical forward OI source — survives the 30-day `openInterestHist` window (D-09). |
| **openInterestHist** | `GET /futures/data/openInterestHist` | **INTEGRATE — opportunistic only** | 02-02 | Trailing-30d harvest at bootstrap, labeled `source=openInterestHist-v1`. Never relied upon as a backfill source (RESEARCH §Pitfall 3: `sumOpenInterest` ≠ `openInterest`; only latest 1 month available). |
| **fundingRate** | `GET /fapi/v1/fundingRate` | **INTEGRATE** | 02-02 | Backfill 2y once + daily catch-up sweep ongoing (D-08; RESEARCH §Open Q3 chose daily sweep + gap journal over 8h poll). 8h settlement cadence means missing a tick is a permanent hole — gap journal is mandatory (D-09). |

## SDK isolation (adapter boundary contract)

Per RESEARCH §Pattern 1 + `docs/integration/BINANCE.md` §2: the only module
allowed to import `binance_sdk_derivatives_trading_usds_futures` is
`src/adapters/binance_usdm.py` (Plan 02-02). Downstream code receives frozen
project dataclasses (`Kline`, `OiSnapshot`, `FundingTick`, `SymbolFilters`)
with `Decimal` for prices/quantities. SDK types must not leak into
domain/strategy code.

## Excluded surfaces (deferred or out-of-scope)

- **Algo Order endpoints** (`new_algo_order`, `query_algo_order`,
  `cancel_algo_order`) — V1 protective SL/TP wiring lands in Phase 9, not
  Phase 2. The SDK exposes them today (verified via `dir(client.rest_api)`
  above); they will be re-verified at Phase 9 implementation start per D-03.
- **User-data WS streams** — Phase 7 (paper) and Phase 9 (live) territory.
  SDK exposes `websocket_streams` and `websocket_api`; re-verify then.
- **`ccxt`** — explicitly forbidden for any order/data path in this phase
  (AGENTS.md / STACK.md). Listed here to document the decision in the
  coverage matrix.

## Verification log (this session)

- `uv python install 3.13` → 3.13.15 installed; `uv run python --version`
  → `Python 3.13.15`.
- `uv lock` resolved 59 packages; no pre-release (rc) markers; no archived
  package names; lockfile `binance-sdk-derivatives-trading-usds-futures`
  pinned at 17.4.0.
- `uv sync --frozen` succeeded; env usable.
- `requests.get("https://fapi.binance.com/fapi/v1/time")` → `200`,
  `X-MBX-USED-WEIGHT-1M: 1`. fapi reachable.
- `client.rest_api.exchange_information()` returned `ExchangeInformationResponse`;
  trimmed live-5 (`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT`) into
  `tests/fixtures/exchange_info_sample.json` (12 KB).
- `inspect.signature(...)` confirmed exact parameter names + types for
  `kline_candlestick_data`, `open_interest`, `get_funding_rate_history`,
  `open_interest_statistics`.

---

*File: `.planning/phases/02-data-foundation/COVERAGE.md`*
*Owner: Phase 2 — Data Foundation*
*Re-verify at: every SDK minor bump (>=17.3,<18) and at Phase 9 / 3-wire
implementation start.*
