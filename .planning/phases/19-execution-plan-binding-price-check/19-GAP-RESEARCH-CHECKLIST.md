# Phase 19: checklist to close the research gaps (owner, on a connected machine)

Source: `19-RESEARCH.md` section "Network gaps (owner follow-up)" and the Assumptions Log (A1-A10). Written 2026-10-19.

Base URL: `https://developers.binance.com/docs/derivatives/usds-margined-futures/`
The paths below are inferred from the documentation layout and were not re-opened; if a page was renamed, search by the page name.

Rules for the owner:
- Record for each item: URL, date read, and the verbatim excerpt. Do not rely on a tool's summary (the first pass used WebFetch summaries, which is why confidence stayed MEDIUM).
- Then change the matching label in `19-RESEARCH.md` from `[UNVERIFIED]` to `[DOC]`, or report that the fact differs from the assumption.
- If a page still says nothing, leave the item to the Demo probes in `19-NOTES.md` (probe numbers given below).

## A. User-data event pages (most important)
Pages: `user-data-streams/Event-Order-Update`, `user-data-streams/Event-Algo-Order-Update`.

- [ ] A1. Full list of execution types (`x`) and order statuses (`X`) of ORDER_TRADE_UPDATE.
- [ ] A2. Is the trade id `t` present on every partial fill?
- [ ] A3. The statuses of ALGO_UPDATE and what each means, including the rejection reason field `o.rm`.
- [ ] A4. Which event and status arrives when a GTD order expires.

Compare with: `OrderUpdateEvent`, `AlgoUpdateEvent`, `ORDER_STATUS_VOCABULARY` in `src/adapters/binance_userdata_events.py`.
Affects: plans 19-11 and 19-14 (fill detection, stop confirmation). Research item B12.

## B. New Order page
Page: `trade/rest-api/New-Order` (the first pass got it truncated; read the end of the page).

- [ ] B1. MARKET with `reduceOnly`: how Binance rejects it when the position is flat or smaller than the quantity, and the error code (the repo assumes -2022 and -2024).
- [ ] B2. The order-type rules table.
- [ ] B3. GTD: `goodTillDate` must be greater than now + 600 seconds, second precision (confirm the wording).
- [ ] B4. Does `GTE_GTC` exist?

Affects: plans 19-05 (GTD), 19-08 (`place_market_close`), 19-12 (emergency close). Assumptions A4 and A8.

## C. New Algo Order page
Page: `trade/rest-api/New-Algo-Order`.

- [ ] C1. Does `closePosition=true` require an open position? (Demo answered -4509 while flat.) If the page is silent: Demo probe 1.
- [ ] C2. `GTE_GTC`.

## D. Account Trade List page
Page: `trade/rest-api/Account-Trade-List`.

- [ ] D1. Is `realizedPnl` net of commission? This decides whether live R can leave INCOMPLETE (assumption A9). If silent, there is no probe for it yet.

## E. Optional
- [ ] E1. exchangeInfo `MARKET_LOT_SIZE`: is the step measured from its own `minQty` like `LOT_SIZE` (assumption A7)?
- [ ] E2. Mark-price stream `<symbol>@markPrice` (not needed; the plan uses a REST read).

## Result of the research pass (2026-10-19, Claude via WebFetch; second, deeper pass)
Detail: `19-RESEARCH.md` section "Gap pass results". The paths above are stale for the event pages (they return the portal landing page). Current URLs: index `https://developers.binance.com/en/docs/llms.txt`; user-data events (one page, raw markdown) `https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams.md`; errors `.../derivatives-trading-usds-futures/error-code.md`. The REST pages under `docs/derivatives/usds-margined-futures/trade/rest-api/` still work.

- A1 DONE [DOC]: x = NEW, CANCELED, CALCULATED, EXPIRED, TRADE, AMENDMENT; X = NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, EXPIRED_IN_MATCH.
- A2 OPEN (types confirmed from SDK models: `t` int "Trade Id", `gtd` int, `er` string, `rm` string "Algo order failed reason"; all Optional, presence rule still unproven): `t` is only an example-frame comment ("Trade Id", legacy page); the field schema is embedded OpenAPI the tool cannot render. Owner: open `/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/~schemas#ordertradeupdate` in a browser, or probe 3.
- A3 DONE [DOC] for the 7 statuses; `o.rm` exists (example "Reduce Only reject"), full value list not documented. Note: the page still documents `CONDITIONAL_ORDER_TRIGGER_REJECT`, which AGENTS.md says is gone: owner to confirm against the changelog.
- A4 DONE for what the docs say: `er` codes 0-9 (6 = "expired as GTE condition unsatisfied", 8 = "initial order expired after the stop order is triggered"); EXPIRED as x and X. GTD expiry is not named explicitly; the event page's time-in-force list omits GTD.
- B1 CLOSED AS "DOC IS SILENT": the New Order notes end after the RESULT / STP / GTD-delay bullets; nothing on reduce-only with a flat or smaller position. Error page: -2022 = "conflicts with existing open orders", -2024 = "Position is not sufficient". Which code a flat MARKET reduce-only returns is Demo-probe only.
- B2 DONE: the mandatory-parameter table shows only LIMIT and MARKET. B3 DONE: "greater than the current time plus 600 seconds and smaller than 253402300799000" (server time not stated). B4 DONE: no `GTE_GTC` (enum GTC, IOC, FOK, GTX, GTD, RPI).
- C1 OPEN (page silent; -4137/-4138 only cover closePosition vs quantity/reduceOnly; -4509 is not on the error page): Demo probe 1. C2 DONE: no `GTE_GTC` in New Algo Order; it appears only in the ALGO_UPDATE EXPIRED example.
- D1 OPEN: `realizedPnl` = "Realized Pnl.", no commission statement; no probe exists.
- E1, E2 not read.

Owner browser pass still needed: A2 (schema), `rm` values, `CONDITIONAL_ORDER_TRIGGER_REJECT` status, E1.

## After the pass
Tell Claude which items changed. Items that stay unresolved remain in `19-OWNER-GAPS.md` (plan 19-17) and must be closed or accepted by the owner before LIVE is enabled.
