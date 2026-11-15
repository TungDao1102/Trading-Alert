# API Coverage — Binance USDⓈ-M Futures (Phase 25: Binance Demo Integration Test Campaign)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

**Status:** DRAFT for owner review (2026-11-07). This phase adds NO new Binance API capability: every row
below points at the Phase 24 matrix (`.planning/phases/24-live-runtime-composition-demo/COVERAGE.md`),
which stays the source of the decision and its reason. The INTEGRATE rows name the scenario ids
(S01-S20, `25-RESEARCH.md` "Scenario Catalog") that exercise the capability on Binance Demo; the
OPT-OUT rows are kept from Phase 24 with their reasons unchanged.
**Scope lock:** DEMO environment only, owner-run (AGENTS.md); live placement stays disabled
(`LIVE_ORDERS_DISABLED`). A real HTTP 418 is never provoked (owner decision 2026-10-22): 418/429 are
injected at the test-only exchange edge.
**Owner check:** a scenario id in a reason is a plan, not an observation; observations live in the
scenario evidence files once the owner has run them.

| capability | decision | reason |
|---|---|---|
| new_order LIMIT entry, GTD with goodTillDate | INTEGRATE | Phase 24 row; S01 S02 S05 S06 S07 (one POST per approval, never re-sent) |
| new_order LIMIT entry, GTC (deterministic client id) | INTEGRATE | Phase 24 row; not exercised by the campaign (GTD is the live entry) |
| new_order MARKET risk-reducing close | INTEGRATE | Phase 24 row; S03 S04 S11 S16 S18 (reduce-only close, `xc-` client ids) |
| new_algo_order CONDITIONAL STOP_MARKET and TAKE_PROFIT_MARKET | INTEGRATE | Phase 24 row; S01 S03 S04 S07 S18 (fill-driven stop, D079) |
| query_order by orig_client_order_id | INTEGRATE | Phase 24 row; S07 cut (a), the one D080 probe after an ambiguous placement |
| query_algo_order by client_algo_id | INTEGRATE | Phase 24 row; S01 S04 S07 (REST confirmation of the stop, B2/B3 table) |
| cancel_order by orig_client_order_id | INTEGRATE | Phase 24 row; S05 (cancel racing a fill), scheduled cancel at plan expiry |
| cancel_algo_order by client_algo_id | INTEGRATE | Phase 24 row; S16 cleanup after a manual close, sweeper |
| get_current_position_mode | INTEGRATE | Phase 24 row; every start sequence of every scenario |
| current_all_open_orders | INTEGRATE | Phase 24 row; S14 S15 (reconcile truth source, foreign order) |
| current_all_algo_open_orders | INTEGRATE | Phase 24 row; S04 S07 S15 (listing read of the B2/B3 table, headroom count) |
| position_information_v3 | INTEGRATE | Phase 24 row; S13 S15 S16 (liquidation price, doubled position, manual close) |
| exchange_information | INTEGRATE | Phase 24 row; every scenario start (stepSize, tickSize, min notional) |
| user_commission_rate | INTEGRATE | Phase 24 row; every scenario start (live commission refresh) |
| account_information_v3 | INTEGRATE | Phase 24 row; S12 S13 (equity, daily loss, available margin) |
| futures_account_balance_v3 | INTEGRATE | Phase 24 row; S12 S13 (equity source) |
| futures_account_configuration | INTEGRATE | Phase 24 row; start sequence (multiAssetsMargin, dualSidePosition reads) |
| account_trade_list (userTrades) | INTEGRATE | Phase 24 row; S12 (day-risk fills, loss injected at the edge) |
| get_income_history | INTEGRATE | Phase 24 row; S12 (funding and realized PnL for day-risk) |
| symbol_configuration | INTEGRATE | Phase 24 row; S13 (margin type and leverage guard input) |
| notional_and_leverage_brackets | INTEGRATE | Phase 24 row; S13 (liquidation guard input) |
| change_margin_type | INTEGRATE | Phase 24 row; S13 via the owner opt-in probe cases only |
| change_initial_leverage | INTEGRATE | Phase 24 row; S13 via the owner opt-in probe cases only |
| start / keepalive / close user data stream (listenKey) | INTEGRATE | Phase 24 row; S08 (stream rebuild, keepalive suppressed for listenKey expiry) |
| user-data event ORDER_TRADE_UPDATE | INTEGRATE | Phase 24 row; S01 S02 S05 S07 (fill source for the coordinator) |
| user-data event ALGO_UPDATE | INTEGRATE | Phase 24 row; S01 S04 (protective-leg status and rejection reasons) |
| user-data event ACCOUNT_UPDATE | INTEGRATE | Phase 24 row; S12 S16 (balance and position changes) |
| user-data event ACCOUNT_CONFIG_UPDATE | INTEGRATE | Phase 24 row; S13 (leverage or margin change seen at runtime) |
| user-data event listenKeyExpired | INTEGRATE | Phase 24 row; S08 (stream restart and reconcile) |
| check_server_time | INTEGRATE | Phase 24 row; S09 (clock-drift guard), every start sequence |
| mark_price (current mark) | INTEGRATE | Phase 24 row; S03 S17 (mark gate, stale feed injected at the public edge) |
| HTTP 418 / 429 rate-limit answers through the durable REST gate | INTEGRATE | Phase 24 gate; S10 S19 injected at the edge, never provoked (owner 2026-10-22) |
| kline_candlestick_data and mark_price_kline_candlestick_data | INTEGRATE | Phase 24 row; data layer, unchanged and not exercised by the campaign |
| get_funding_rate_history, open_interest, open_interest_statistics | INTEGRATE | Phase 24 row; data layer and cost model, unchanged, not exercised |
| countdown_cancel_all_open_orders (auto-cancel timer) | OPT-OUT | kept from Phase 24: expiry is the project scheduler (24-21) and the GTD backstop |
| cancel_all_open_orders and cancel_all_algo_open_orders | OPT-OUT | kept from Phase 24: blanket cancels could remove orders the system does not own |
| modify_order and order amend | OPT-OUT | kept from Phase 24: a placement is never re-sent or amended (D080) |
| new_order_test / order test endpoint | OPT-OUT | kept from Phase 24: no value over the Demo environment scenarios |
| change_position_mode and change_multi_assets_mode | OPT-OUT | kept from Phase 24: account settings are an owner attestation (OPS-02) |
| TRAILING_STOP_MARKET and other algo order types | OPT-OUT | kept from Phase 24: strategy spec uses fixed SL and TP only |
| TWAP / VP execution algos (/sapi/v1/algo/futures/*) | OPT-OUT | kept from Phase 24: not a protective leg; out of scope for V1 |
| legacy conditional orders via /fapi/v1/order | OPT-OUT | kept from Phase 24: replaced by the Algo Order service; Demo -4509, D079 |
| user-data events TRADE_LITE, STRATEGY_UPDATE, GRID_UPDATE | OPT-OUT | kept from Phase 24: ignored events; ORDER_TRADE_UPDATE carries the fill |
| user-data event MARGIN_CALL | OPT-OUT | kept from Phase 24: no typed handler; surfaced as an UNHANDLED_EVENT anomaly |
| FastAPI inbound webhook receiver | OPT-OUT | kept from Phase 24: not installed; Telegram uses polling (PTB) |
| mainnet (LIVE) REST and WebSocket endpoints | OPT-OUT | kept from Phase 24: no mainnet use in Phase 25; DEMO only (AGENTS.md) |
