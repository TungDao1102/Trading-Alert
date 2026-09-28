# Phase 9: Live Execution Rollout — API Coverage Matrix

**Authored:** 2026-09-28 (planner, per api-integration contribution checkpoint)
**SDK:** `binance-sdk-derivatives-trading-usds-futures` 17.4.0 installed and introspected (09-RESEARCH.md)
**Rule:** Full API coverage by default. Every placement-relevant capability is INTEGRATE or OPT-OUT with a one-line reason.
Executor task in 09-01 re-verifies each INTEGRATE row against the installed SDK signatures at implementation time (D-01) and updates this file on any delta.

**Re-verified 2026-09-28 (09-01 execution):** Rows 1, 2, 4, 5, 8 re-verified against installed SDK 17.4.0 via introspection (`python -c "import binance_sdk_derivatives_trading_usds_futures as m; ..."`). No signature delta — all four placement methods (`new_order`, `new_algo_order`, `query_order`, `get_current_position_mode`) and the existing `query_algo_order` retain their 17.3.1 signatures. Adapter docstring table updated with the four new rows.

| # | Capability (SDK method / endpoint) | Disposition | Reason / Plan |
|---|------------------------------------|-------------|---------------|
| 1 | `new_order` LIMIT entries (`POST /fapi/v1/order`, GTC, deterministic `x-` client ID) | INTEGRATE | Core D-01 entry path — 09-01 tracer |
| 2 | `new_algo_order` CONDITIONAL SL leg STOP_MARKET (`POST /fapi/v1/algoOrder`, `algoType=CONDITIONAL`, deterministic `xa-` ID) | INTEGRATE | Core D-01 protective path — 09-01 tracer |
| 3 | `new_algo_order` CONDITIONAL TP1/TP2 legs (TAKE_PROFIT_MARKET, TP1 explicit qty + reduceOnly one-way / explicit qty + positionSide hedge, TP2 close-all) | INTEGRATE | D-01/D-02 full protection — 09-02 |
| 4 | `query_order` by `orig_client_order_id` | INTEGRATE | No-blind-recovery probe before any entry retry (EXECUTION_SPEC §10) — 09-01 |
| 5 | `query_algo_order` by `client_algo_id` | INTEGRATE | No-blind-recovery probe before any protective retry; already in adapter (`query_algo_order_by_client`) — 09-01/09-03 |
| 6 | `cancel_order` by `orig_client_order_id` (entry expiry / manual-close) | INTEGRATE | EXECUTION_SPEC §4 expiry (never leave LIMIT open) + §11 emergency manual-close — 09-04 |
| 7 | `cancel_algo_order` by `client_algo_id` | INTEGRATE | Already in adapter; expiry-cancel of untriggered protectives + sweeper path reuse — 09-04 |
| 8 | `get_current_position_mode` (one-way vs hedge) | INTEGRATE | D-02 dynamic detection at startup + re-check at placement — 09-01 |
| 9 | `current_all_open_orders` (open normal orders, per symbol) | INTEGRATE | Three-source reconciler truth already in adapter (`snapshot_open_normal_orders`); live loop feeds it — 09-03/09-04 |
| 10 | `current_all_algo_open_orders` (open algo orders, per symbol) | INTEGRATE | Headroom count vs 200-per-symbol limit (D-03) + reconciler truth — 09-03 |
| 11 | `position_information_v3` (live positions incl. `position_amt`) | INTEGRATE | Reconciled-state DAILY_STOP/caps (D-03) + fill-monitor cross-check — 09-03 |
| 12 | `exchangeInfo` constraint reads (tickSize, stepSize, min/max qty, min notional) at placement time | INTEGRATE | D-03 placement-time revalidation with `metadata_observed_at_utc` TTL — 09-03 |
| 13 | User-data stream `ALGO_UPDATE` incl. `o.rm` rejection reasons | INTEGRATE | Preferred realtime fill/reject source; `CONDITIONAL_ORDER_TRIGGER_REJECT` is gone (Dec-2025 migration) — 09-04 fill monitor |
| 14 | User-data streams for orders/fills/positions (listen-key lifecycle) | INTEGRATE | D002 posture: WS preferred realtime, REST fallback + periodic authoritative tick — 09-04 |
| 15 | TWAP/VP execution algos (`binance-sdk-algo`, `/sapi/v1/algo/futures/*`) | OPT-OUT | Deferred: execution algos, not protective SL/TP; V1 protectives use CONDITIONAL algo orders in the futures SDK (CONTEXT Deferred Ideas) |
| 16 | `goodTillDate` (GTD) entry expiry | OPT-OUT | Manual expiry-cancel is the EXECUTION_SPEC §4-explicit path; GTD (`goodTillDate` > now+600s) stays a planner-documented alternative, not wired in V1 |
| 17 | Legacy `/fapi/v1/order` conditional assumption (STOP_MARKET via normal endpoint) | OPT-OUT | Superseded by Dec-2025 Algo migration; D-01 forbids the legacy assumption |
| 18 | `MAX_NUM_ALGO_ORDERS` exchangeInfo filter | OPT-OUT | Filter removed Dec 2025; headroom counted live via row 10, never read from a filter (D-03) |
| 19 | `CONDITIONAL_ORDER_TRIGGER_REJECT` WS event | OPT-OUT | Event removed; rejections arrive in `ALGO_UPDATE.o.rm` (row 13) |
| 20 | FastAPI inbound webhook receiver for Telegram callbacks | OPT-OUT | Deferred (V1 uses PTB polling; CONTEXT Deferred Ideas) |

**Scope lock:** live-5 universe only (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT), smallest capital, per D-04.
