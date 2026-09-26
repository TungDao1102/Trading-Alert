# Phase 7 — COVERAGE: external API integration scan

Detector pre-run on the ROADMAP section alone returned `detected:false`; re-run on full scope (ROADMAP section plus the terms the PLAN bodies name: Binance WS Streams `kline_candlestick_streams`, `reconnect`, REST `klines`, `exchangeInfo`, `python-telegram-bot` `Bot.send_message`, `InlineKeyboardMarkup`) still returns `detected:false` — the keyword heuristic misses the SDK-class surface. The scope genuinely integrates two external APIs, so this file records the capability coverage matrix (INTEGRATE default) rather than a no-API declaration.

## Capability coverage matrix

| Capability (this phase) | External API | SDK / client | Plan | Mode |
|-------------------------|--------------|--------------|------|------|
| WS kline ingestion (1H setup, 4H regime, 1m fill-resolution) + reconnect / 24h rotation | Binance USDⓈ-M WS Market Streams (`<symbol>@kline_<interval>`, combined stream) | `binance-sdk-derivatives-trading-usds-futures` 17.4.0 WS Streams class, behind `src/adapters/paper_ws.py` only | 07-01, 07-02 | INTEGRATE |
| REST kline resync (missed-close backfill, `limit<=1500`) + exchangeInfo constraint snapshots | Binance USDⓈ-M REST (`GET /fapi/v1/klines`, `GET /fapi/v1/exchangeInfo`) | Same SDK via existing `BinanceUsdmAdapter.klines` + `src/data/metadata.py` | 07-02 | INTEGRATE |
| SIMULATE send-only notifications (12 APRV-01 fields, inert callback buttons) | Telegram Bot API (`sendMessage` + inline keyboard) | `python-telegram-bot>=22.8,<23` `Bot.send_message`, behind `src/adapters/telegram_notify.py` only | 07-04 | INTEGRATE (install behind blocking-human legitimacy checkpoint) |

## Opt-outs

None — every external capability in scope is integrated above. No direct `websockets` hand-roll, no raw-httpx Bot API calls, no `ccxt`, no legacy `binance-connector` / `binance-futures-connector` (archived 2026-04-30).

## Boundary rules (enforced by plans)

- SDK and Telegram types never cross the adapter edge: `src/paper/` core stays stdlib + Decimal only (no-float AST guard covers it).
- Paper approvals are simulated timestamps only; no order-placement endpoint is touched in any plan (order paths are Phase 9).
- SDK minor + Binance changelog re-verified at the 07-04 pre-soak smoke checkpoint (Dec-2025 Algo-migration precedent).
