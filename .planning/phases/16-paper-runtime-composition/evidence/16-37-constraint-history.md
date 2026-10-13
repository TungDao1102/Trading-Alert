# 16-37 historical constraint source search (read-only, human decision pending)

Date of search: 2026-10-13. Window: [2024-10-03T00:00Z, 2026-10-03T00:00Z). Fields: price tick (tickSize), quantity step (stepSize), min quantity (minQty), min notional. No Binance API was called, no current exchangeInfo was used. Web lookups only (about 35). Nothing here is a decision.

Verification levels: CONFIRMED = an official Binance page (binance.com support announcement / developers.binance.com) I fetched states the value or change. REPORTED = secondary source only. NOT FOUND = no source found. "No change notice found" never means "unchanged".

## (a) Method and pages checked

Search tool results are search-engine summaries; official pages were opened with a fetch tool that summarises the page, so values below come from that summary, not from a raw copy.

Official pages fetched (all binance.com / developers.binance.com):
1. Updates on Minimum Notional Value for BTCUSDT and ETHUSDT Perpetual Contracts (published 2023-10-27, effective 2023-11-02 10:00 UTC): BTCUSDT 5 -> 100 USDT, ETHUSDT 5 -> 20 USDT. https://www.binance.com/en/support/announcement/updates-on-minimum-notional-value-for-btcusdt-and-ethusdt-perpetual-contracts-2023-11-02-e4384cba297a4bd2a154be644d5d76f9 (BEFORE window)
2. Updates on the Tick Size for BTC USDS-M Perpetual Futures Contracts (published 2021-12-31, effective 2022-02-15 03:30 UTC): BTCUSDT tick 0.01 -> 0.1. https://www.binance.com/el/support/announcement/updates-on-the-tick-size-for-btc-usd%E2%93%A2-m-perpetual-futures-contracts-81e6795b0bae49828cbd52479094a987 (BEFORE window)
3. Updates on Tick Size ... (2024-09-20, effective 06:30 UTC): APT, ASTR, JOE, KEY, XVG, BIGTIME, ILV, GLM, ETHFI, TURBO, ZRO, RPL. None of the 12 symbols. https://www.binance.com/en/support/announcement/updates-on-tick-size-for-multiple-usd%E2%93%A2-m-perpetual-futures-contracts-2024-09-20-fa192e78242d4d96be9562ab7d76a10a (before window, none of ours)
4. Updates on Tick Size ... (2024-02-05): LOOM, LSK, LEVER, APE, TLM, HIGH, POLYX, ACH, DODOX. None of ours; before window.
5. Updates on Tick Size ... (2021-11-15): OMG, REN. None of ours; before window.
6. Updates on Tick Size for Multiple USDS-M Perpetual Futures Contracts (published 2025-12-18, effective 2025-12-22 07:00 UTC = 15:00 UTC+8), zh-CN page https://www.binance.com/zh-CN/support/announcement/1cd08ee9bafd40a2a94e8dfc58408f82 : USELESS, NOM, EVAA, SLP, WAXP, POWR, SCR, S, AT, VTHO, VANRY, STABLE. None of the 12. IN window; a complete official list, no symbol of ours.
7. Binance Futures Will Delist and Update the Leverage & Margin Tiers of USDS-M REEFUSDT Perpetual Contract (2025-01-22) (see REEF section).
8. New Minimum Order Notional Limit Rule for USDS-M Futures (published 2021-01-21, effective 2021-01-25 07:00 UTC): generic min notional 1 USD at that time; says Binance may change thresholds without notice. https://www.binance.com/en/support/announcement/new-minimum-order-notional-limit-rule-for-usd%E2%93%A2-m-futures-76719bbaeeb847bbac4daa2906fcdcc0 (before window)
9. USDS-Margined Futures Contract Specifications FAQ (published 2019-09-09, updated 2026-01-02): lists no per-symbol values (image only), states "Binance Futures may adjust the minimum order threshold from time to time without prior notice". https://www.binance.com/en/support/faq/usd%E2%93%A2-margined-futures-contract-specifications-360033161972
10. developers.binance.com derivatives change-log (https://developers.binance.com/docs/derivatives/change-log), read fully by the fetch tool in two parts: no per-symbol tickSize/stepSize/minQty/minNotional value changes. Related: 2021-01-26 MIN_NOTIONAL filter introduced; 2025-12-29 MAX_NUM_ALGO_ORDERS filter removed; 2026-09-15 reduceOnly modify skips min_notional validation. The change-log is not a per-symbol history.
11. Announcement list https://www.binance.com/en/support/announcement/list/48 (new listings category, first page only): nothing relevant. The Delisting category (list/161) content was not available.

Not usable / not found:
- data.binance.vision / github.com/binance/binance-public-data: README covers klines, trades, aggTrades only; no exchangeInfo or filter history is described. NOT FOUND. (Directory listings of data.binance.vision itself were not fetched.)
- Internet Archive (web.archive.org): the fetch tool refused the domain, so no snapshot could be cited. NOT SEARCHABLE with the available tools.
- binance.com/en/futures/trading-rules (live page): returned only search metadata; it shows current values at best and is not history.
- blockchain.news pages (about 6 tick-size write-ups, 2024-07, 2024-11-04, 2024-11-28, 2025-04, 2025-06): fetch timed out each time; only search-snippet summaries seen, no symbol lists.
- Official pages for the tick-size announcements of 2024-11-04, 2024-11-28, 2024-11-29 (1000WHY, 1000CHEEMS reported), 2025-04-17 (20 contracts incl. VOXEL, MBOX, reported), 2025-06 (10 contracts incl. ME, SLERF, reported), 2026-03-05, 2026-04-02, 2026-04-06, 2026-06-04, 2026-06-08, 2026-08-06 were NOT opened; the symbol lists of these are unknown to me except the few names in secondary snippets. They are the main hole in the tick column (see gaps).

Secondary sources:
- Longbridge / CoinLive, 2026-04-09: BTCUSDT 100 -> 50 USDT and BTCUSDC 100 -> 50 USDC, effective 2026-04-14 06:30 UTC. https://longbridge.com/en/news/282143186 . The article links no Binance announcement; the official page was not found by two searches. REPORTED only.
- Tardis.dev roadmap page (undated; not fetchable) says Binance changed BTC perp min notional to 100; consistent with item 1, adds nothing.
- ChainCatcher 2025-12-18 (https://www.chaincatcher.com/en/article/2230639), TechFlow, Odaily: secondary copies of tick-size notices.
- KuCoin Futures REEFUSDT delist (2025-01-24) is a different exchange; ignore.

Queries run (web search): REEF settle/delist; tick size adjustment (several variants with symbol names, with 2024 Oct-Dec, 2025, 2026); minimum notional BTC/ETH (three variants); step size / minimum order quantity (two variants); data.binance.vision exchangeInfo history; BTC min notional 50 April 2026 (two variants).

## (b) Coverage table (window 2024-10-03 .. 2026-10-03)

Cell values: CONFIRMED-CHANGED (value, date, URL) / NO-CHANGE-NOTICE-FOUND / NOT-SEARCHABLE. "NCNF" below = NO-CHANGE-NOTICE-FOUND. Meaning of NCNF here: among the announcements I could open, none lists this symbol. It does NOT cover announcements I could not open (listed in (a)), so for tick it is a partial negative.

| Symbol | tick | step | min_qty | min_notional |
|---|---|---|---|---|
| 1000PEPEUSDT | NCNF in opened official lists (item 6, 3); unopened lists remain | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| BNBUSDT | NCNF (same); 2021 tick change is before window | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| BTCUSDT | NCNF in window (0.01->0.1 on 2022-02-15 is before window, CONFIRMED, item 2) | NOT-SEARCHABLE | NOT-SEARCHABLE | REPORTED-CHANGED 100 -> 50 USDT, 2026-04-14 06:30 UTC (secondary only, Longbridge link above); 5 -> 100 on 2023-11-02 CONFIRMED but before window. Stored 2026-10-03 value 50 is consistent with the report |
| DOGEUSDT | NCNF; 2021 tick change before window | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| DOGSUSDT | NCNF (listed 2024-08-26 per local table) | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| ETHUSDT | NCNF | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF in window; 5 -> 20 on 2023-11-02 CONFIRMED but before window; stored value 20 consistent |
| REEFUSDT | NCNF; contract ended 2025-01-22 | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| SOLUSDT | NCNF; 2021 tick change before window | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| SUIUSDT | NCNF | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| WIFUSDT | NCNF | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| WLDUSDT | NCNF (launch announcement states tick 0.0001, 2023; stored value 0.0001 matches) | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |
| XRPUSDT | NCNF | NOT-SEARCHABLE | NOT-SEARCHABLE | NCNF |

Zero cells are CONFIRMED-CHANGED inside the window. The only in-window change found at all is the REPORTED BTCUSDT min_notional change.

Known caveat: the tick-size changes of BNBUSDT, SOLUSDT and DOGEUSDT announced in 2021 (stated by the requester; I did not re-fetch those announcements) are before the window and by themselves show nothing inside it.

Consistency of the stored 2026-10-03 values with pre-window official facts: BTCUSDT tick 0.1 (item 2), ETHUSDT min_notional 20 (item 1). This is consistency, not proof of the window.

## REEFUSDT official announcement

- Title: "Binance Futures Will Delist and Update the Leverage & Margin Tiers of USDS-M REEFUSDT Perpetual Contract (2025-01-22)".
- URL: https://www.binance.com/en/support/announcement/binance-futures-will-delist-and-update-the-leverage-margin-tiers-of-usd%E2%93%A2-m-reefusdt-perpetual-contract-2025-01-22-572715f2d96e47769ebbb967c2a6e445 (URL first surfaced from the Bloomingbit article https://en.bloomingbit.io/feed/news/81714, then fetched successfully; CONFIRMED official).
- Published: 2025-01-15 08:00 (the page shows no time zone).
- Settlement: Binance Futures closes all REEFUSDT positions and settles them automatically at 2025-01-22 09:00 UTC; the contract is then delisted.
- No new positions from 2025-01-22 08:30 UTC.
- Leverage/margin tier change effective 2025-01-15 07:30 UTC (only the 2x and 1x tiers; 2x range 500,000 < P <= 600,000, 1x range 600,000 < P <= 650,000; maintenance rates unchanged; existing positions unaffected).
- Settlement price: NOT stated on the page. Not found elsewhere. (Secondary COINOTAG describes it as auto-deleveraging; the official page says "settle automatically". Do not claim a price.)
- Caveat: this is the fetch tool's summary of the page, not a raw copy.
- REEF other (secondary, not constraint fields): tier change 2024-10-16 06:30 UTC and funding interval to 4h the same day.

## (c) Gaps in evidence

1. step and min_qty: no announcement type for step/min quantity changes was found for any symbol; the change-log has no such entries. The whole window is without evidence for all 12 symbols. These values can change without a support announcement ("from time to time without prior notice" per the Contract Specifications FAQ), so no announcement does not imply no change.
2. min_notional: whole window without evidence for 11 symbols (no notice found; 5 USDT stored values have no dated source at all). BTCUSDT: only the secondary report for 2026-04-14; the period 2024-10-03 .. 2026-04-14 06:30 UTC is "100 USDT" only by inference from the 2023-11-02 official change plus the absence of a notice, and 2026-04-14 .. 2026-10-03 is "50" only by the secondary report and the stored value.
3. tick: the official lists of 2024-09-20 and 2025-12-22 were read in full and contain none of the 12. About 11 further tick-size announcement dates in the window (listed in (a)) were not opened, so their symbol lists are unknown. Tick coverage is therefore partial for every symbol, not complete.
4. No historical exchangeInfo source: data.binance.vision publishes no filter history; Wayback was inaccessible; no third-party archive was verified. The only stored observation is the 2026-10-03 local set (EC2 reportedly empty).
5. Anything before 2026-10-03 for step and min_qty, and before 2026-04-14 for BTCUSDT notional, is unevidenced.
6. REEF: settlement price not stated.

Full history for all 12 symbols and 4 fields CANNOT be established from the sources reachable here.

## (d) Options for the human decision (none chosen)

A. Extrapolate the single 2026-10-03 observation backwards, every bar flagged `extrapolated` (current runner behaviour). Consequence: simplest; known wrong for BTCUSDT min_notional before 2026-04-14 (reported 100, stored 50), so BTC plans and the 60% minimum-risk-utilisation / min-notional rejections would be evaluated with a looser limit than existed for ~18 of 24 months (secondary evidence only). Other symbols: unproven but no contrary notice found among opened sources. The extrapolated flag must be kept visible in the kill-gate report.

B. Use the dated history found plus a stated gap policy. What exists: BTCUSDT min_notional 100 before 2026-04-14 06:30 UTC and 50 after (from the secondary report; the reported change must be flagged REPORTED not CONFIRMED, and an official page should be sought first); ETHUSDT 20 and BTC tick 0.1 already hold at window start (official, pre-window). Gap policy needed for everything else (e.g. carry back the 2026-10-03 value, flagged). Consequence: changes one symbol's behaviour materially; adds a dated-constraint table that needs a manifest entry and hash; still extrapolated for step/min_qty and for unopened tick announcements. More lookups (opening the ~11 unopened tick announcements, the official April 2026 notional notice) could narrow the gaps but cannot close step/min_qty.

C. Fixed constraint set declared as a research assumption, plus sensitivity analysis (for example run BTCUSDT with min_notional 100 and 50, and tick/step at +/- one level). Consequence: honest about the evidence limit; results are labelled assumption-based; costs extra runs and a sensitivity section; does not rely on any single unverified source. Which values form the fixed set (the 2026-10-03 observation or another) is itself a human choice.

Not decided here: which option, whether the reported 2026-04-14 change is accepted without an official page, and whether more lookups are worth doing.
