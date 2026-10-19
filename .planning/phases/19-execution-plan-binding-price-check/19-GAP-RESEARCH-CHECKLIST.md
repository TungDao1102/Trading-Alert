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

## After the pass
Tell Claude which items changed. Items that stay unresolved remain in `19-OWNER-GAPS.md` (plan 19-17) and must be closed or accepted by the owner before LIVE is enabled.
