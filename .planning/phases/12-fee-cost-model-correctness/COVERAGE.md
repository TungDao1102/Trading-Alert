# API Coverage - Binance USDⓈ-M Futures User Commission Rate (`GET /fapi/v1/commissionRate`)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

Scope: Phase 12 integrates one external endpoint through the official SDK (`binance-sdk-derivatives-trading-usds-futures`, `rest_api.user_commission_rate`) behind `BinanceUsdmAdapter.user_commission_rate` (plan 12-05). Source facts and provenance: `docs/SOURCES.md` (Facts verified for Phase 12) and `12-RESEARCH.md` section "Live commissionRate". Runtime wiring (scheduler, cache refresh) is Phase 24 (D-13).

| capability | decision | reason |
|---|---|---|
| request parameter `symbol` (required) | INTEGRATE | |
| response field `symbol` (identity check) | INTEGRATE | |
| response field `takerCommissionRate` (per-side sizing rate) | INTEGRATE | |
| response field `makerCommissionRate` | INTEGRATE | parsed, range-checked and carried in CommissionRates; not used for sizing because V1 entries and stop exits are taker (D036) |
| request parameter `recvWindow` (optional) | OPT-OUT | SDK default is used; timestamp and clock-skew handling is Phase 18 |
| response field `rpiCommissionRate` (RPI orders) | OPT-OUT | V1 places no RPI orders; the adapter deliberately depends on no field beyond symbol, taker and maker |
| BNB burn status read and BNB burn toggle | OPT-OUT | BNB fee discount is ignored in sizing (F-031, D-10); toggling an account setting is an account write outside this phase |
| user-data stream commission fields on order trade updates | OPT-OUT | realized-fee accounting arrives with the user-data stream in Phase 18 and live outcome accounting in Phases 21 and 24 |
| account fee tier field on account information | OPT-OUT | not needed: the per-symbol commissionRate response is the authoritative rate for sizing |
| Demo or testnet behavior of the endpoint | OPT-OUT | not documented in any retrieved material; verified in the Phase 24 demo stage (assumption A1) |
| periodic refresh, caching and scheduler wiring | OPT-OUT | runtime composition belongs to Phase 24 (D-13); this phase ships the adapter method, the pure resolver and the fail-closed rules only |
