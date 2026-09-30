# Lane A2: docs_exchange_facts

Finding ID range: F-051..F-099. Audit date: 2026-09-29. Snapshot commit: 63ca176.
I read all web sources on **2026-09-29**. I read the installed SDK read-only: `binance_sdk_derivatives_trading_usds_futures` 17.4.0 with `binance_common` 4.4.0. The uv.lock pins the same versions.

## Scope

This lane checks the factual external claims (Binance, Telegram, TradingView, package versions) in these files:
- `docs/integration/BINANCE.md`, `docs/integration/TELEGRAM.md`, `docs/integration/TRADINGVIEW.md`
- `docs/TECHNOLOGY_STACK.md`, `docs/SOURCES.md`
- the stack section in `AGENTS.md` (lines 40–130)
- the exchange facts in `docs/trading/EXECUTION_SPEC.md` and `docs/trading/RISK_MANAGEMENT.md`
- the fee parameters in `params/*/*.toml`

I checked each claim against two sources:
- current official web docs: developers.binance.com, tradingview.com support, and core.telegram.org (the core.telegram.org fetch returned 403, so I used a search snippet plus the installed PTB 22.8 constants);
- the installed SDK.

I opened a few code locations only to point the code lanes at them. They are not judged here.

## Coverage

| File | Level | Note |
|---|---|---|
| docs/integration/BINANCE.md | DEEP_READ | every claim checked |
| docs/integration/TELEGRAM.md | DEEP_READ | |
| docs/integration/TRADINGVIEW.md | DEEP_READ | |
| docs/TECHNOLOGY_STACK.md | DEEP_READ | |
| docs/SOURCES.md | DEEP_READ | links checked |
| AGENTS.md (stack section) | DEEP_READ | via system context plus snapshot grep (L77) |
| docs/trading/EXECUTION_SPEC.md | DEEP_READ | |
| docs/trading/RISK_MANAGEMENT.md | DEEP_READ | |
| params/*/*.toml (fee lines) | NORMAL_READ | grep of fee/slippage/funding |
| pyproject.toml, uv.lock | NORMAL_READ | dependency pins vs claims |
| tests/fixtures/exchange_info_sample.json | NORMAL_READ | recorded filters (commit 53fdfce, 2026-09-19) |
| src/execution/gates.py L20–45 | NORMAL_READ | 200-limit comment (cross-reference only) |
| src/execution/manager.py L505–560 | METADATA_ONLY | entry TIF / workingType (cross-reference) |
| src/execution/placement.py L320–450 | METADATA_ONLY | leg flags (cross-reference) |
| src/adapters/binance_usdm.py L30–55, L790–830 | METADATA_ONLY | SDK method table, algo open-order call |
| src/adapters/paper_ws.py (grep) | METADATA_ONLY | uses SDK `kline_candlestick_streams` |
| SDK rest_api/api/{trade,account,market_data,user_data_streams}_api.py | NORMAL_READ | method names, paths, weights, docstrings |
| SDK rest_api/models/enums.py, *algo*, exchange_information_*, position_information_v3_*, user_commission_rate_response.py, symbol_configuration_response_inner.py | NORMAL_READ | enums, field aliases |
| SDK websocket_streams/models/{algo_update*,order_trade_update_o,kline_*_k,user_data_stream_events_response}.py, websocket_streams.py | NORMAL_READ | event fields, WS path routing |
| binance_common/utils.py, constants.py, websocket.py (grep) | NORMAL_READ | serialization, retry policy, base URLs |
| telegram/constants.py (PTB 22.8) | NORMAL_READ | callback-data and answer-length limits, Bot API version |
| INVARIANTS.md (INV-080..095, INV-112, AMB-005/027/032) | NORMAL_READ | IDs |

## Claim verification table

Status values:
- CORRECT: matches the current official source.
- STALE: was true, but the source has changed since.
- WRONG: contradicts the official source.
- UNVERIFIABLE: I could not check it with the allowed sources.

| # | Claim | Doc location | Official URL / SDK file | Status |
|---|---|---|---|---|
| 1 | Target is USDⓈ-M `fapi`, base `https://fapi.binance.com` | BINANCE.md §1 | binance_common/constants.py L65; Exchange-Information page | CORRECT |
| 2 | The official SDK supports REST, WS API and WS Streams, on Python 3.10+ | BINANCE.md §2; TECH_STACK §2, §4; AGENTS | SDK METADATA `Requires-Python: >=3.10,<3.15`; PyPI JSON | CORRECT |
| 3 | A market WS connection is valid for 24h; ping/pong rules apply; there are stream limits | BINANCE.md §3 | …/websocket-market-streams/Connect: "only valid for 24 hours", ping every 3 min, pong within 10 min, 10 msgs/s, 1024 streams | CORRECT |
| 4 | The WS base URL shape (implied: `wss://fstream.binance.com/ws/...`) | BINANCE.md §3, §5, §10 (silent) | Important-WebSocket-Change-Notice: `/public`, `/market`, `/private`; legacy URLs removed **2026-04-23** | STALE (omission) → F-053 |
| 5 | `ORDER_TRADE_UPDATE` with NEW/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED | BINANCE.md §5 | SDK order_trade_update_o.py (`x`, `X`, `n`, `N`, `rp`, `er`); changelog 2025-10-20 adds `er`, 2026-07-21 adds `M` | CORRECT (incomplete: `er`, `M`, commission asset `N`) |
| 6 | STOP_MARKET/TAKE_PROFIT_MARKET were migrated to the Algo Order service; the legacy endpoint rejects them | BINANCE.md §6; EXEC_SPEC §2; AGENTS | changelog 2025-11-06 (effective 2025-12-09; legacy endpoint returns `-4120 STOP_ORDER_SWITCH_ALGO`) | CORRECT |
| 7 | `CONDITIONAL_ORDER_TRIGGER_REJECT` is gone; the reason is in `ALGO_UPDATE.o.rm` | AGENTS | changelog 2025-12-10 (deprecated from 2025-12-15). The SDK 17.4.0 still ships a `ConditionalOrderTriggerReject` model in its user-data oneOf | CORRECT (web). The SDK carries a legacy model; do not rely on it |
| 8 | Protective orders use `POST /fapi/v1/algoOrder`, `algoType=CONDITIONAL`; query with `GET /fapi/v1/algoOrder`; cancel with `DELETE /fapi/v1/algoOrder` | AGENTS; INV-080 | New-Algo-Order page; SDK trade_api.py `new_algo_order` L1335, `query_algo_order` L1805, `cancel_algo_order` L316 | CORRECT |
| 9 | New algo order weight: 1 on the order-count limits, 0 on IP weight | AGENTS | SDK docstring L1368–1370; New-Algo-Order page; changelog 2026-06-20 | CORRECT. Note: cancel/query carry **IP weight 1** (SDK) |
| 10 | The legacy `/fapi/v1/order` does not accept conditional types | EXEC_SPEC §2 | changelog 2025-11-06 (`-4120`) | CORRECT |
| 11 | `closePosition=true` works only on STOP_MARKET/TAKE_PROFIT_MARKET, cannot go with `quantity` or `reduceOnly`, and has hedge-mode limits | EXEC_SPEC §2; INV-082 | SDK trade_api.py L1393–1398, L1413–1415; web New-Algo-Order | CORRECT |
| 12 | One-way pattern: SL closePosition, TP1 reduceOnly with a quantity, TP2 closePosition | EXEC_SPEC §5 | same; `reduceOnly` "cannot be sent in Hedge Mode" | CORRECT (valid in one-way mode) |
| 13 | Protective stop "exists and is active" is enough to call the position protected | EXEC_SPEC §6 | changelog 2025-11-06 "No margin check before the conditional order gets triggered"; ALGO_UPDATE statuses TRIGGERING/TRIGGERED/FINISHED/REJECTED/EXPIRED | INCOMPLETE → F-054 |
| 14 | Position-mode change is rejected when open orders or positions exist | EXEC_SPEC §8 | SDK `change_position_mode` docstring: `-4067` (open orders), `-4068` (position) | CORRECT (the doc cites the New-Order page, which is the wrong page → F-057) |
| 15 | Deterministic client IDs; query by client ID before any retry | EXEC_SPEC §7, §10 | general-info: HTTP 503 "Unknown error…" means execution status UNKNOWN; `newClientOrderId`/`clientAlgoId` regex `^[\.A-Z\:/a-z0-9_-]{1,36}$` | CORRECT |
| 16 | `MAX_NUM_ALGO_ORDERS` was removed from exchangeInfo in Dec 2025 | EXEC_SPEC §12 | changelog **2025-12-29**; the recorded fixture has no such filter | CORRECT |
| 17 | "200-open-conditional-order limit **per symbol**" | EXEC_SPEC §12; INV-090; gates.py L27 | changelog 2025-12-29: "The conditional order limits is 200 **across all symbols**" | WRONG → F-051 |
| 18 | "200-conditional-order headroom … must be dynamic via `exchangeInfo`/account queries, never hard-coded" | AGENTS L51 | no endpoint exposes the limit after 2025-12-29 | WRONG (not possible) → F-051 |
| 19 | exchangeInfo has symbol filters for price and quantity; read them, do not hard-code them | RISK §11 | Exchange-Information page; SDK filters model (`tickSize`, `stepSize`, `minQty`, `maxQty`, `notional`, `multiplierUp/Down`) | CORRECT |
| 20 | One `quantity_step_size` / `min_quantity` for every order type | RISK §11, §12 | exchangeInfo has separate `LOT_SIZE` and `MARKET_LOT_SIZE` filters (fixture: BTC LOT maxQty 1000 vs MARKET maxQty 120) | INCOMPLETE → F-056 |
| 21 | Minimum notional rule ("below min notional → reject") | RISK §11 | error `-4164`: "notional must be no smaller than %s (unless reduce only)"; filter key is `notional` (not `minNotional`) | CORRECT (reduce-only orders are exempt) |
| 22 | Leverage and margin constraints are read before placement | RISK §9, §12 | `GET /fapi/v3/positionRisk` v3 has **no** `leverage` or `marginType` fields (SDK model). Use `GET /fapi/v1/symbolConfig` (weight 5) and `GET /fapi/v1/leverageBracket` | CORRECT as intent; see the facts section for the endpoint |
| 23 | Historical OI statistics cover only the latest month | BINANCE.md §8 | Open-Interest-Statistics: "Only the data of the latest 1 month is available"; `/futures/data/openInterestHist`, limit 500 | CORRECT |
| 24 | Separate endpoints for current open algo orders exist | BINANCE.md §9 | SDK `current_all_algo_open_orders` → `GET /fapi/v1/openAlgoOrders` (weight 1 with a symbol, **40** without) | CORRECT |
| 25 | The API key must not have withdrawal permission; prefer IP restriction | BINANCE.md §11 | general best practice | CORRECT (sound) |
| 26 | Fee `fee_rate_entry=0.0002` (maker), `fee_rate_exit=0.0005` (taker) | params/*/baseline-*.toml | VIP0 USDT-M 0.02%/0.05%: secondary sources only; binance.com/en/fee/futureFee does not render. SDK `user_commission_rate` → `GET /fapi/v1/commissionRate` returns fractions (`"0.0002"`) | CORRECT for VIP0 USDT-M (MEDIUM confidence). The maker assumption does not match GTC entries → F-055 |
| 27 | USDC-M VIP0 fees; BNB 10% discount | (not in docs) | secondary sources: 10% BNB discount on USDT-M/USDC-M; the USDC-M rate is not confirmed from an official page | UNVERIFIABLE |
| 28 | Telegram `callback_data` is 1–64 bytes | INV-045/046 context; L5 scope | core.telegram.org/bots/api (search snippet): "1-64 bytes"; PTB 22.8 `MAX_CALLBACK_DATA = 64` | CORRECT |
| 29 | `answerCallbackQuery` must be called | TELEGRAM.md (implicit) | Bot API: "necessary to react by calling answerCallbackQuery even if no notification…"; text ≤200 chars (PTB) | CORRECT |
| 30 | Callback delivery is treated as at-least-once | TELEGRAM.md §6 | Bot API gives no exactly-once guarantee; webhook requests are retried on failure | CORRECT (a conservative design assumption) |
| 31 | python-telegram-bot 22.8 / Bot API 10.0 | AGENTS | PTB constants `BOT_API_VERSION_INFO(major=10, minor=0)` | CORRECT |
| 32 | TradingView strategy alerts run a server-side copy of the strategy; chart edits do not change existing alerts | TRADINGVIEW.md §6 | tradingview.com/support/solutions/43000481368: quoted verbatim | CORRECT |
| 33 | TradingView warns against putting credentials in the webhook body | TRADINGVIEW.md §5 | 43000529348: "don't include sensitive information such as login credentials or passwords in the webhook body" | CORRECT |
| 34 | The webhook is "HMAC-checked" | AGENTS L77 | 43000529348: no custom headers or signing; only ports 80/443, 3 s timeout, 4 source IPs, 2FA required | WRONG → F-052 |
| 35 | TradingView supports strategies, backtesting and forward testing | TRADINGVIEW.md §2 | 43000562362 (not fetched) | UNVERIFIABLE (low stakes) |
| 36 | `binance-futures-connector` 4.2.0 was archived on 2026-04-30 | AGENTS | pypi.org/project/binance-futures-connector: "archived… April 30, 2026", 4.2.0 | CORRECT (`binance-connector` 3.13.0 not fetched) |
| 37 | The SDK is at 17.3.1 (released 2026-09-10); "PyPI 17.2.1 listing" | AGENTS | PyPI JSON: 17.3.1 2026-09-10 ✓; the latest is **17.5.0 (2026-09-23)**; lock/installed 17.4.0 | STALE (harmless; inside `>=17.3,<18`) |
| 38 | Other versions (DuckDB 1.5.5, Polars 1.44.x, SQLAlchemy 2.0.x, Alembic 1.19.1, psycopg 3.3.x, httpx 0.28.1) | AGENTS | uv.lock: duckdb 1.5.5, polars 1.44.2, sqlalchemy 2.0.54, alembic 1.20.0, psycopg 3.3.6, httpx 0.28.1 | CORRECT within the pins (release dates not checked) |
| 39 | Python 3.14 is the latest stable; 3.15 is pre-release as of 2026-09-19; "Python 3.14.7 release" link | TECH_STACK §2; SOURCES | not fetched | UNVERIFIABLE (not exchange-critical) |
| 40 | SOURCES "WebSocket Market Streams" link | SOURCES.md L134 | the URL path is `…/derivatives-trading-coin-futures/…` (**COIN-M**, the wrong product) | WRONG → F-057 |
| 41 | Link hosts `developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/…` | BINANCE.md §3, §5; SOURCES | WebFetch returns only the portal landing page (JS-rendered). The SDK docstrings use the same catalog URLs, so the links are probably valid | UNVERIFIABLE (not a defect) |
| 42 | `recvWindow`/timestamp rules | (docs silent) | general-info: recvWindow default 5000 ms (max 60000); server accepts if `timestamp < serverTime+1000 && serverTime-timestamp <= recvWindow`; `-1021` otherwise | fact only |
| 43 | Rate limits: 429 / 418 | (docs silent; AGENTS mentions tenacity) | general-info: 429 means back off; 418 means IP ban, 2 min up to 3 days; 2400 REQUEST_WEIGHT/min (exchangeInfo example) | fact only |

## Verified Safe Areas

- **INV-080 (algo endpoints).** Paths, method names and the `algoType=CONDITIONAL` enum in the docs and AGENTS match SDK 17.4.0 (`NewAlgoOrderAlgoTypeEnum.CONDITIONAL`) and the live web page. Legacy conditional types on `/fapi/v1/order` now return `-4120`.
- **INV-082 (closePosition rules).** The EXECUTION_SPEC wording matches both the web page and the SDK docstring (`trade_api.py` L1393–1398, L1415). This includes the hedge-mode limits.
- **CONDITIONAL_ORDER_TRIGGER_REJECT removal (AGENTS).** Confirmed by the changelog entry of 2025-12-10.
- **EXEC_SPEC §12 "filter removed".** Confirmed by the changelog entry of 2025-12-29 and by the recorded `exchange_info_sample.json` (2026-09-19). The fixture has only these filters: PRICE_FILTER, LOT_SIZE, MARKET_LOT_SIZE, MAX_NUM_ORDERS, MIN_NOTIONAL, PERCENT_PRICE, POSITION_RISK_CONTROL. There is no MAX_NUM_ALGO_ORDERS.
- **SDK retry policy is safe for order placement.** `binance_common/utils.py` `should_retry_request` retries only GET/DELETE on 5xx. POST (new order or new algo order) is never retried automatically. This fits EXEC_SPEC §10 (no blind retry).
- **SDK WS routing.** `websocket_streams.py` L57 opens `url_paths=["market","public","private"]`, and user data uses `stream_url="private"` (L146). The post-2026-04-23 URL split is handled when the SDK is used. `paper_ws.py` uses the SDK `kline_candlestick_streams`, and src/ has no hard-coded `wss://` or `fstream` URL.
- **Kline closed flag.** The SDK model `kline_candlestick_streams_response_k.py` L43 has `x: "Is this kline closed?"`, which supports BINANCE.md §4.
- **Telegram limits.** `callback_data` is 1–64 bytes and `answerCallbackQuery` is required. Both are confirmed.
- **Fee values.** 0.0002/0.0005 match the common VIP0 USDT-M schedule, and they are fractions, the same unit as `makerCommissionRate`/`takerCommissionRate`.

## Findings

### F-051 — The 200 conditional-order limit is account-wide ("across all symbols"), not per symbol, and it cannot be read from any endpoint
- **Severity:** MEDIUM · **Confidence:** CONFIRMED (doc vs official changelog) · **Classification:** DRIFT (wrong external fact) · **Category:** exchange-facts
- **Component:** docs/trading/EXECUTION_SPEC.md §12, AGENTS.md stack notes, INVARIANTS INV-090 / AMB-032, src/execution/gates.py (comment and remediation plan)
- **File:** docs/trading/EXECUTION_SPEC.md · **Lines:** 153–155 (also AGENTS.md L51, src/execution/gates.py L27–41)
- **Invariant:** INV-090, AMB-032 · **Phase/commit:** docs e1ec86a (2026-09-19); gates.py phase 09
- **Known-prior:** KNOWN:09-REVIEW WR-06 (partial fix). WR-06 proposed reading "exchangeInfo `MAX_NUM_ALGO_ORDERS` per symbol", and that filter no longer exists.
- **Evidence:**
  - EXEC_SPEC L153: "documented a 200-open-conditional-order limit per symbol instead".
  - AGENTS: "200-conditional-order headroom … must be dynamic via `exchangeInfo`/account queries, never hard-coded".
  - gates.py L27: "200 conditional orders per symbol"; L33–35: "AGENTS.md requires this limit to be detected dynamically (exchangeInfo `MAX_NUM_ALGO_ORDERS` per symbol)".
  - Official changelog, 2025-12-29 (https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log, read 2026-09-29): "'filterType': 'MAX_NUM_ALGO_ORDERS' has been removed … The conditional order limits is 200 across all symbols."
- **Expected:**
  - The limit is an account-wide constant of 200, kept in config with a citation (AMB-032 option (a)).
  - The count comes from `GET /fapi/v1/openAlgoOrders` **without** `symbol` (weight 40), or from the sum over all symbols. It covers every algo order on the account, including manual ones.
- **Actual:** The docs say "per symbol". AGENTS demands dynamic discovery that is impossible. The open fix plan (WR-06) chases a filter that was removed.
- **Reproduction:** Compare the EXEC_SPEC L153 text with the changelog entry. Check `tests/fixtures/exchange_info_sample.json`: none of the five symbols has a `MAX_NUM_ALGO_ORDERS` filter.
- **Impact:**
  - If the caller counts only one symbol's open algo orders (`snapshot_open_algo_orders(symbol=…)`), the headroom gate can pass while the account is at its cap. Then the SL/TP placement fails after entry, and the position is left unprotected.
  - In V1 (2 positions × 3 legs) the cap is hard to reach unless other tools or manual orders share the account. So the practical severity is MEDIUM.
- **Why tests miss it:** Tests fix `open_algo_count` as an input. Nothing asserts the scope of the count.
- **Remediation:**
  - Fix EXEC_SPEC §12, INV-090 and the AGENTS wording to "200 across all symbols (changelog 2025-12-29), documented constant".
  - Resolve AMB-032 as option (a).
  - Code lanes (L3/L5) should check that `open_algo_count` is account-wide.
  - Drop the WR-06 plan to read `MAX_NUM_ALGO_ORDERS`.

### F-052 — "TradingView webhooks (HMAC-checked)" cannot be done; TradingView cannot sign requests or set headers
- **Severity:** LOW · **Confidence:** CONFIRMED · **Classification:** DRIFT (wrong external fact) · **Category:** exchange-facts / security design
- **Component:** AGENTS.md stack table (FastAPI row); INV-112 · **File:** AGENTS.md · **Lines:** 77
- **Invariant:** INV-112, AMB-039 · **Phase/commit:** 36fecfd · **Known-prior:** INVARIANTS INV-112 already marks this QUESTIONABLE (not yet a finding)
- **Evidence:**
  - AGENTS L77: "TradingView webhooks (HMAC-checked)".
  - TradingView's page (https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/, read 2026-09-29) documents no custom headers and no signing. It lists: "only ports 80 and 443 are accepted", a 3-second processing timeout, content type set automatically, four source IPs (52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7), and 2FA required. It also warns against credentials in the body.
- **Expected:** Authenticate with a high-entropy secret in the URL path (not the body), plus an allowlist of the four source IPs. Return 2xx within 3 s (enqueue, then process). Replay protection must come from payload dedupe, because there is no timestamped signature.
- **Actual:** HMAC is required but cannot be implemented. TRADINGVIEW.md §5 ("must be authenticated … must not accept secrets in the message body") leaves the URL-path secret as the only workable option, and no doc says so.
- **Reproduction:** Read the TradingView page. It has no header or signature configuration.
- **Impact:** No live impact, because no webhook exists in src/ (grep finds no `fastapi` import). A future implementer could either build something that cannot work or fall back to an unauthenticated endpoint.
- **Why tests miss it:** The feature is not implemented.
- **Remediation:** Replace "HMAC-checked" with "URL-path secret + TradingView IP allowlist + 3 s ack + payload dedupe" in AGENTS.md and TRADINGVIEW.md §5.

### F-053 — The docs do not mention the 2026-04-23 WebSocket base-URL split (/public, /market, /private)
- **Severity:** LOW · **Confidence:** CONFIRMED · **Classification:** GAP (stale external fact) · **Category:** exchange-facts
- **Component:** docs/integration/BINANCE.md §3/§5/§10; SOURCES.md · **File:** docs/integration/BINANCE.md · **Lines:** 23–42
- **Invariant:** INV-076 (stale feed), INV-095 · **Known-prior:** none
- **Evidence:**
  - Binance "Important WebSocket Change Notice" (https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice, read 2026-09-29) says:
    - New bases: `wss://fstream.binance.com/public` (book ticker, depth), `/market` (klines, markPrice, aggTrade, tickers), `/private` (user data: `…/private/ws?listenKey=…&events=ORDER_TRADE_UPDATE`).
    - "Legacy URLs will remain available until 2026-04-23." After that date, unmigrated connections get only `/public` data, and `/market` and `/private` "will cease data delivery".
  - BINANCE.md never mentions this change.
- **Expected:**
  - Klines must be consumed through `/market` and user data through `/private`, or through SDK ≥ the version that routes them (17.4.0 does; see Verified Safe Areas).
  - Stale-feed detection must treat "connected but silent" as stale.
- **Actual:** The docs are silent. The code uses the SDK, so the current risk is low. A hand-rolled client, or an old SDK pin, would connect fine and receive no klines (silent failure).
- **Reproduction:** n/a (documentation).
- **Impact:** If regressed, the live kline feed goes silent. It fails safe only if the stale-feed gate fires.
- **Why tests miss it:** There are no network tests, by design.
- **Remediation:** Add a paragraph to BINANCE.md §3/§5 with the three bases and the date. Pin the SDK floor at a version that routes them (≥17.x, already true). L5/L7 should confirm the stale-feed gate treats a connected socket with no messages as stale.

### F-054 — The docs miss key algo-order facts: no margin check before trigger, rejection at trigger, and FINISHED ≠ filled
- **Severity:** MEDIUM · **Confidence:** CONFIRMED (doc omission vs official sources) · **Classification:** GAP · **Category:** exchange-facts / protection
- **Component:** docs/trading/EXECUTION_SPEC.md §6, §9; BINANCE.md §6, §9 · **File:** docs/trading/EXECUTION_SPEC.md · **Lines:** 87–98
- **Invariant:** INV-085, INV-093, INV-094, INV-080 · **Known-prior:** none
- **Evidence:**
  - EXEC_SPEC §6 only says "After entry fill, the system must verify that the expected protective stop exists and is active".
  - The official changelog of 2025-11-06 says "No margin check before the conditional order gets triggered".
  - The Binance ALGO_UPDATE statuses (https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update, via search index, 2026-09-29) are:
    - NEW: in the Algo Service, not triggered.
    - TRIGGERING: forwarded to the matching engine.
    - TRIGGERED: placed in the matching engine.
    - FINISHED: the triggered order was **filled or canceled** in the matching engine.
    - REJECTED: rejected by the matching engine, "such as in scenarios of margin check failures".
    - CANCELED.
    - EXPIRED: "canceled by the system".
  - The SDK `algo_update_o.py` has `X`, `rm` ("Algo order failed reason"), `ai` (matching-engine order id), `aq`/`ap` (executed qty/avg price in the matching engine), and `act`.
- **Expected:** The docs should state all of these:
  - A NEW algo stop is only a *pending* protection.
  - At trigger it can be REJECTED or EXPIRED, which leaves the position unprotected. That must raise a HIGH alert or SAFE_MODE.
  - An exit fill must be confirmed from `ORDER_TRADE_UPDATE`/`aq` of the child order (`ai`), not from the algo status FINISHED.
- **Actual:** The docs are silent. A code path could treat TRIGGERED or FINISHED as "position closed", or ignore REJECTED at trigger.
  - The code allow-lists `NEW` as the only "active" status (`src/execution/manager.py` L683–704). That covers the pre-trigger check.
  - I did not trace post-trigger handling. It is left to L3/L5.
- **Reproduction:** n/a (documentation). The code lanes should grep fill_monitor/reconcile for how TRIGGERED, FINISHED, REJECTED and EXPIRED are interpreted after entry.
- **Impact:** A position could be silently unprotected, or an exit could be mis-journaled (PnL and daily-loss state).
- **Why tests miss it:** Fixtures probably cover NEW/CANCELED only.
- **Remediation:** Add an "Algo status semantics" subsection to EXEC_SPEC §6 and §9. Code lanes should verify the handling.

### F-055 — The entry fee assumes maker (0.0002), but entries are sent as plain GTC LIMIT, which can fill as taker (0.0005)
- **Severity:** LOW · **Confidence:** PROBABLE · **Classification:** IMPROVEMENT (cost realism) · **Category:** fees
- **Component:** params/*/baseline-*.toml; src/execution/manager.py (`time_in_force: "GTC"`) · **File:** params/trend-pullback/baseline-v3.toml · **Lines:** 43–44
- **Invariant:** INV-054, INV-105, AMB-005 · **Known-prior:** KNOWN:ROADMAP phase 11 (real commission via `GET /fapi/v1/commissionRate`) covers the rate value, not the maker/taker assumption
- **Evidence:**
  - `fee_rate_entry = 0.0002   # 2 bps maker` and `fee_rate_exit = 0.0005   # 5 bps taker`.
  - `src/execution/manager.py` L515: `"time_in_force": "GTC"`.
  - A LIMIT order that is marketable when it arrives (for example, price has passed through the zone during the approval delay) executes as taker.
  - Binance offers `GTX` (post-only), which rejects with `-5022` instead of taking.
  - VIP0 USDT-M 0.02%/0.05% comes from secondary sources. The official fee page (https://www.binance.com/en/fee/futureFee) did not render its table, so this is MEDIUM confidence. The BNB 10% discount is not modeled (conservative).
  - Commission in `ORDER_TRADE_UPDATE.n` is paid in asset `N`, which can be BNB.
- **Expected:** Either use `GTX` so the maker fee holds, or model the entry fee as taker (or as the worse of maker and taker) when sizing.
- **Actual:** Sizing and backtest cost can understate the entry fee by 3 bps per trade when the entry crosses.
- **Impact:** A small cost understatement, larger for tight stops. Risk per trade is slightly higher than budgeted.
- **Why tests miss it:** No fill-liquidity model.
- **Remediation:** Decide the entry TIF in the docs (GTX vs GTC). Journal the fill `m` (maker flag) and the real `n`/`N`. Convert BNB commission to the quote asset.

### F-056 — Quantization docs ignore MARKET_LOT_SIZE and PERCENT_PRICE
- **Severity:** LOW · **Confidence:** CONFIRMED (doc) · **Classification:** GAP · **Category:** exchange-facts / quantization
- **Component:** docs/trading/RISK_MANAGEMENT.md §11–12 · **File:** docs/trading/RISK_MANAGEMENT.md · **Lines:** 257–296
- **Invariant:** INV-055, INV-057, INV-060, AMB-027 · **Known-prior:** none
- **Evidence:**
  - The docs list one `quantity_step_size` / `min_quantity`.
  - Binance has separate `LOT_SIZE` and `MARKET_LOT_SIZE` filters. The fixture shows BTCUSDT LOT maxQty 1000 vs MARKET maxQty 120, and SOL 1,000,000 vs 80,000.
  - A triggered `STOP_MARKET`/`TAKE_PROFIT_MARKET` with an explicit quantity (TP1) runs as a market order.
  - `PERCENT_PRICE` (multiplierUp/Down 1.05/0.95 in the fixture) bounds LIMIT prices against the mark. Error `-4131` covers the market counterpart.
  - `grep MARKET_LOT_SIZE src` finds nothing.
- **Expected:** Snapshot MARKET_LOT_SIZE and PERCENT_PRICE too, and validate TP1 quantity against MARKET_LOT_SIZE.
- **Actual:** Not specified. There is no effect for the live-5 at $500–1000 capital, because step and min are the same and max is far away.
- **Impact:** Latent only. It would matter only for other symbols or large sizes.
- **Remediation:** Add both filters to the RISK §12 constraint snapshot.

### F-057 — Wrong source links: the COIN-M WS page in SOURCES.md, and the New-Order page cited for position-mode rules
- **Severity:** INFO · **Confidence:** CONFIRMED · **Classification:** DRIFT · **Category:** docs hygiene
- **File:** docs/SOURCES.md L134; docs/trading/EXECUTION_SPEC.md L112
- **Evidence:**
  - SOURCES.md L134: `…/docs/products/derivatives-trading-coin-futures/websocket-market-streams/Connect` is the COIN-M product, not USDⓈ-M.
  - EXEC_SPEC L112 cites `trade/rest-api/New-Order` for position-mode change rules. The rule actually belongs to Change Position Mode (`POST /fapi/v1/positionSide/dual`, `-4067`/`-4068`).
- **Remediation:** Point both links at `…/usds-margined-futures/websocket-market-streams/Connect` and `…/trade/rest-api/Change-Position-Mode`.

### F-058 — The Decimal policy ends at the SDK: `quantity`/`price` are typed `float` and serialized with `str(float)`
- **Severity:** LOW · **Confidence:** CONFIRMED (SDK + probe) · **Classification:** GAP (docs silent) · **Category:** exchange-facts / precision
- **Component:** TECHNOLOGY_STACK §3 ("Decimal for exchange-sensitive …"); SDK boundary · **File:** binance_sdk…/rest_api/api/trade_api.py L1343–1345; binance_common/utils.py `make_serializable`
- **Invariant:** INV-011 · **Known-prior:** the adapter docstring (`src/adapters/binance_usdm.py` L50) knows about the float boundary ("string-mediated Decimal-to-edge")
- **Evidence:**
  - `new_algo_order(… quantity: Optional[float], price: Optional[float], trigger_price: Optional[float] …)`.
  - `make_serializable`: `if isinstance(val, float): return str(val)`.
  - Probe with the venv Python: `str(float(Decimal('0.00001234')))` → `'1.234e-05'`, while `0.0001` → `'0.0001'`. Binance rejects exponent notation (`-1100` illegal characters / `-1111` precision).
  - Passing a `Decimal` also falls through to `str()`, which gives an exponent below 1e-6.
- **Expected:** The docs should state the exact edge conversion: a tick-quantized Decimal is formatted as a fixed-point string (`format(d, 'f')`) and the float is built from it. Values below 1e-4 must never reach `str(float)`.
- **Actual:** Nothing is documented. There is no impact for the live-5 (tick ≥ 0.0001, step ≥ 0.001), but it is latent for low-price symbols.
- **Remediation:** Document the rule. L5 should confirm the adapter's conversion is exact and non-exponent.

## Exchange Facts for Code Audit

All of these facts were read on 2026-09-29. **W** = official web doc, **S** = installed SDK 17.4.0.

### Endpoints (USDⓈ-M, base `https://fapi.binance.com`)

| Purpose | Method + path | SDK method | Weight | Notes |
|---|---|---|---|---|
| Exchange info | GET /fapi/v1/exchangeInfo | `exchange_information` | 1 | filters below; `pricePrecision`/`quantityPrecision` must NOT be used as tick or step (W) |
| New order (entry) | POST /fapi/v1/order | `new_order` | order-count 1/1, IP 0 | LIMIT needs `timeInForce`, `quantity`, `price`; `newClientOrderId` `^[\.A-Z\:/a-z0-9_-]{1,36}$`; `newOrderRespType` ACK default; TIF enum GTC/IOC/FOK/GTX/GTD/RPI; conditional types return **-4120** here |
| New algo (SL/TP) | POST /fapi/v1/algoOrder | `new_algo_order(algo_type, symbol, side, type, position_side, time_in_force, quantity, price, trigger_price, working_type, price_match, close_position, price_protect, reduce_only, activate_price, callback_rate, client_algo_id, new_order_resp_type, self_trade_prevention_mode, good_till_date)` | order-count 1/1, IP 0 | `algoType=CONDITIONAL` only; types STOP_MARKET/TAKE_PROFIT_MARKET/STOP/TAKE_PROFIT/TRAILING_STOP_MARKET (the SDK enum also lists LIMIT/MARKET, but the web lists only the 5 conditional types). **`workingType` default = CONTRACT_PRICE** (W). `priceProtect` default false; with true, the trigger checks mark vs contract against the symbol's `triggerProtect`. `closePosition` is only for *_MARKET, never with quantity or reduceOnly; in hedge mode, not BUY+LONG or SELL+SHORT. `reduceOnly` is not allowed in hedge mode. `clientAlgoId` uses the same regex, 1–36 chars. GTD needs `goodTillDate` > now+600 s, second precision |
| Query algo | GET /fapi/v1/algoOrder | `query_algo_order(algo_id, client_algo_id)` | IP 1 | one of the two ids is required; `algoId` increments per symbol |
| Cancel algo | DELETE /fapi/v1/algoOrder | `cancel_algo_order(algo_id, client_algo_id)` | IP 1 | the SDK auto-retries DELETE on 5xx/no-response |
| Cancel all algo (symbol) | DELETE /fapi/v1/algoOpenOrders | `cancel_all_algo_open_orders(symbol)` | IP 1 | |
| Open algo orders | GET /fapi/v1/openAlgoOrders | `current_all_algo_open_orders(algo_type, symbol, algo_id)` | 1 with symbol / **40** without | without a symbol it returns all symbols; use this for the **account-wide 200 cap** |
| All algo orders (history) | GET (query_all_algo_orders) | `query_all_algo_orders` | — | active/CANCELED/TRIGGERED/FINISHED |
| Open normal orders | `current_all_open_orders` / `query_current_open_order` | | | |
| Query order | `query_order` (orderId / origClientOrderId) | | | use this for no-blind-retry |
| Positions | GET /fapi/v3/positionRisk | `position_information_v3(symbol)` | 5 | fields: `symbol`, `positionSide`, `positionAmt`, `entryPrice`, `breakEvenPrice`, `markPrice`, `unRealizedProfit`, `liquidationPrice`, `isolatedMargin`, `notional`, `marginAsset`, `isolatedWallet`, `initialMargin`, `maintMargin`, `positionInitialMargin`, `openOrderInitialMargin`, `adl`, `bidNotional`, `askNotional`, `updateTime`. **It has no `leverage` and no `marginType`.** The SDK note says to use it with `ACCOUNT_UPDATE` |
| Leverage / margin type (read) | GET /fapi/v1/symbolConfig | `symbol_configuration(symbol)` | 5 | fields `marginType`, `isAutoAddMargin`, `leverage` (int), `maxNotionalValue` |
| Leverage brackets | GET /fapi/v1/leverageBracket | `notional_and_leverage_brackets` | 1 | |
| Set leverage | POST /fapi/v1/leverage | `change_initial_leverage(symbol, leverage:int)` | 1 | |
| Set margin type | POST /fapi/v1/marginType | `change_margin_type(symbol, margin_type enum)` | 1 | `-4046` means already set |
| Position mode (read) | GET /fapi/v1/positionSide/dual | `get_current_position_mode` | **30** | response `dualSidePosition` (bool); applies to every symbol |
| Position mode (set) | POST /fapi/v1/positionSide/dual | `change_position_mode(dual_side_position)` | 1 | `-4067` open orders, `-4068` open position, `-4059` no change needed |
| Account config | GET /fapi/v1/accountConfig | `futures_account_configuration` | 5 | `feeTier`, `canTrade`, `multiAssetsMargin`, `dualSidePosition` |
| Account | GET /fapi/v3/account | `account_information_v3` | 5 | `totalWalletBalance`, `totalMarginBalance`, `totalUnrealizedProfit`, `availableBalance`, `maxWithdrawAmount`, `totalInitialMargin`, `totalMaintMargin`, … |
| Balance | GET /fapi/v3/balance | `futures_account_balance_v3` | 5 | per asset: `balance`, `crossWalletBalance`, `availableBalance` |
| Commission | GET /fapi/v1/commissionRate | `user_commission_rate(symbol)` (symbol required) | **20** | `makerCommissionRate`, `takerCommissionRate`, `rpiCommissionRate`: **fraction strings** (for example `"0.0002"` = 0.02%) |
| BNB fee burn | `get_bnb_burn_status` / `toggle_bnb_burn_on_futures_trade` | | | if on, fills report commission in BNB (`N`) |
| Income | GET /fapi/v1/income | `get_income_history` | 30 | FUNDING_FEE, COMMISSION, REALIZED_PNL …; new `SPECIAL_FUNDING_FEE` since 2026-09-10 |
| listenKey | POST / PUT / DELETE /fapi/v1/listenKey | `start_user_data_stream` / `keepalive_user_data_stream` / `close_user_data_stream` | 1 each | valid 60 min unless kept alive. POST on an existing key returns the same key and extends it. Keep alive about every 30 min (Binance says "about every 60 minutes", which is the edge) |
| OI history | GET /futures/data/openInterestHist | `open_interest_statistics` | 0 (limit 1000 req/5 min) | latest 1 month only; limit ≤ 500 |
| Server time | GET /fapi/v1/time | `check_server_time` | 1 | |

### exchangeInfo symbol filters (key names as sent by Binance)

| Filter | Fields |
|---|---|
| PRICE_FILTER | `minPrice`, `maxPrice`, `tickSize` |
| LOT_SIZE | `minQty`, `maxQty`, `stepSize` (LIMIT orders) |
| MARKET_LOT_SIZE | `minQty`, `maxQty`, `stepSize` (MARKET orders and triggered *_MARKET orders) |
| MIN_NOTIONAL | `notional` (note: not `minNotional`). Reduce-only orders are exempt (`-4164` "unless reduce only") |
| PERCENT_PRICE | `multiplierUp`, `multiplierDown`, `multiplierDecimal` |
| MAX_NUM_ORDERS | `limit` |
| POSITION_RISK_CONTROL | present in the fixture |
| MAX_NUM_ALGO_ORDERS | **Removed on 2025-12-29.** Do not read it |

- Symbol-level fields: `triggerProtect`, `marketTakeBound`, `liquidationFee`, `status`, `contractType`, `quoteAsset`, `marginAsset`, `orderTypes`, `timeInForce`, `underlyingType`.
- In the SDK, every filter value is a string (StrictStr). Convert with `Decimal(str)`.
- Recorded values (2026-09-19 fixture):

| Symbol | tick | step | minQty | MIN_NOTIONAL |
|---|---|---|---|---|
| BTCUSDT | 0.10 | 0.001 | 0.001 | **50** |
| ETHUSDT | – | 0.001 | – | **20** |
| BNB/SOL/XRP | – | 0.01 / 0.01 / 0.1 | – | 5 |

### Limits and constants
- **Conditional (algo) order cap: 200 across all symbols** (account-wide; changelog 2025-12-29). No endpoint exposes it, so keep it as a documented constant.
- REQUEST_WEIGHT is 2400/min per IP (exchangeInfo example). Order-count limits are per account, per 10 s and per 1 min. Response headers: `X-MBX-USED-WEIGHT-1M` and `X-MBX-ORDER-COUNT-10S`/`-1M`.
- HTTP 429 means back off. HTTP 418 means IP ban (2 min up to 3 days).
- HTTP 503 has three variants:
  - "Unknown error, please check your request or try again later": the execution status is **UNKNOWN**, so query before any retry.
  - "Service Unavailable": the request failed, so retry with backoff.
  - `-1008`: throttled.
- `recvWindow` defaults to 5000 ms (max 60000). The server accepts when `timestamp < serverTime+1000` and `serverTime − timestamp ≤ recvWindow`; otherwise it returns `-1021`.
- SDK auto-retry covers only GET/DELETE on 5xx or no response. POST is never auto-retried.

### Error codes the code should map
| Code | Meaning |
|---|---|
| -1003 | too many requests / IP banned |
| -1008 | throttled |
| -1021 | timestamp outside recvWindow |
| -1022 | bad signature |
| -1100 | illegal characters (for example exponent-notation numbers) |
| -1111 | bad precision |
| -2010 | new order rejected |
| -2011 | cancel rejected |
| -2013 | no such order |
| -2019 | margin insufficient |
| -2021 | order would immediately trigger |
| -2022 | reduceOnly rejected |
| -4003/-4004/-4005 | qty ≤ 0 / < min / > max |
| -4014 | price not a multiple of tick |
| -4015 | clientOrderId invalid / too long (>36) |
| -4023 | qty not a multiple of step |
| -4046 | margin type needs no change |
| -4059 | position side needs no change |
| -4061 | positionSide does not match the account mode |
| -4067/-4068 | cannot change position mode (open orders / open position) |
| -4120 | STOP_ORDER_SWITCH_ALGO: use the Algo API |
| -4131 | PERCENT_PRICE |
| -4164 | MIN_NOTIONAL |
| -4400 | quantitative rules: reduce-only allowed |
| -5022 | GTX (post-only) rejected |
| -4425 | multi-asset mode rejected (new 2026-09-28) |

### User-data events (WS `/private`, SDK `stream_url="private"`)

**ORDER_TRADE_UPDATE.o**

| Field | Meaning |
|---|---|
| `s` | symbol |
| `c` | client order id |
| `S` | side |
| `o` | type |
| `f` | TIF |
| `q` | original qty |
| `p` | price |
| `ap` | average price |
| `sp` | stop price |
| `x` | execution type |
| `X` | status: NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED (other values not verified this pass; treat unknown values as fail-closed) |
| `i` | order id |
| `l` | last filled qty |
| `z` | cumulative qty |
| `L` | last price |
| `N` | commission asset |
| `n` | commission |
| `T` | trade time |
| `t` | trade id |
| `m` | is maker |
| `R` | reduce-only |
| `wt` | working type |
| `ot` | original type |
| `ps` | position side |
| `cp` | close-all |
| `rp` | realized profit |
| `V` | STP mode |
| `pm` | price match |
| `gtd` | GTD time |
| `er` | expiry reason (since 2025-10-23) |
| `M` | modify id (since 2026-07-21) |

**ALGO_UPDATE.o**

| Field | Meaning |
|---|---|
| `caid` | clientAlgoId |
| `aid` | algoId |
| `at` | algo type |
| `o` | order type |
| `s` | symbol |
| `S` | side |
| `ps` | position side |
| `f` | TIF |
| `q` | quantity |
| `X` | algo status |
| `ai` | matching-engine order id |
| `ap` / `aq` | average price / executed qty in the matching engine |
| `act` | actual order type |
| `tp` | trigger price |
| `p` | price |
| `V` | STP mode |
| `wt` | working type |
| `pm` | price match |
| `cp` | close-all |
| `pP` | price protect |
| `R` | reduce-only |
| `tt` | trigger time |
| `gtd` | GTD time |
| `rm` | **failure reason** |
| `ia` | trailing activation |

Algo `X` values:

| Status | Meaning |
|---|---|
| NEW | pending, not triggered |
| TRIGGERING | forwarded to the matching engine |
| TRIGGERED | placed in the matching engine |
| FINISHED | the child order was **filled or canceled** (not proof of a fill) |
| REJECTED | rejected at trigger, for example a margin-check failure (no margin check before trigger) |
| CANCELED | canceled |
| EXPIRED | canceled by the system |

**ACCOUNT_UPDATE:** balances and positions. The `S` field (symbol) was added for FUNDING_FEE events on 2026-08-07.

**Other events:** listenKeyExpired, MARGIN_CALL, ACCOUNT_CONFIG_UPDATE, TRADE_LITE, STRATEGY_UPDATE, GRID_UPDATE. **CONDITIONAL_ORDER_TRIGGER_REJECT has been deprecated since 2025-12-15.** The SDK still has a model for it; do not depend on it.

### WebSocket
- Bases: `wss://fstream.binance.com/public` (book ticker, depth), `/market` (kline, markPrice, aggTrade, ticker), `/private` (user data: `?listenKey=…&events=…`). Legacy URLs were removed on 2026-04-23.
- A connection is valid for 24 h. The server pings every 3 min, and there must be a pong within 10 min. Limits: 10 incoming msgs/s and 1024 streams per connection.
- A kline is closed only when `k.x == true`.

### Telegram (Bot API 10.0, PTB 22.8)
- `callback_data` is 1–64 **bytes** (UTF-8 bytes, not characters).
- `answerCallbackQuery` must be called for every callback, even with no text. The text limit is 200 chars.
- sendMessage text is limited to 4096 chars (PTB 22.8 `MAX_TEXT_LENGTH = 4096`; not re-read on the web).
- Delivery is at-least-once in practice, so idempotency is required.

### TradingView webhooks
- POST to port 80 or 443 only. There is a 3 s timeout.
- The body is `application/json` if it is valid JSON, and text otherwise.
- There are no custom headers and no signing.
- Source IPs: 52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7.
- 2FA is required on the TradingView account.
- Delivery can fail, and no retry policy is documented.

### Fees
- VIP0 USDT-M: maker 0.0200%, taker 0.0500% (secondary sources; the official page did not render).
- BNB payment gives 10% off on USDT-M and USDC-M.
- Live code should read `GET /fapi/v1/commissionRate` (fractions). Journal `n`/`N` from fills, and convert BNB commission to the quote asset.

## Open Questions

1. **L3/L5:** Is `open_algo_count` passed to `decide_placement` taken account-wide (`current_all_algo_open_orders()` with no symbol) or per symbol? See F-051.
2. **L3/L5:** How do fill_monitor and reconcile handle algo `TRIGGERED`, `FINISHED`, `REJECTED` and `EXPIRED` after entry? Is a REJECTED SL at trigger raised as HIGH or SAFE_MODE? Is exit quantity taken from the child order (`ai`/`aq`/ORDER_TRADE_UPDATE)? See F-054.
3. **L2/L5:** src/ has no listenKey or user-data stream code (grep finds no `start_user_data_stream`/`listen_key`), although user-data WS is the "preferred realtime source". Is that intended (REST polling only)? Cross-reference v0.3 audit M1–M3.
4. **L3 / A1 (parity):** Live SL/TP use `working_type="MARK_PRICE"` (placement.py L325/L437/L450). Backtest intrabar fills use 1m candles, which are contract/last-price. Stops triggered by a wick on last price but not on mark price create a backtest-vs-live semantic gap (INV-058/INV-103).
5. **A1/L3:** At $500 equity × 0.5% = $2.50 risk, BTCUSDT MIN_NOTIONAL 50 USDT, and ETH 20, a BTC stop wider than about 5% gives notional under $50, which leads to MIN_NOTIONAL_REJECT. Check that the rejection rate is reported, not hidden.
6. **L5:** Check the exact Decimal→float edge conversion in `binance_usdm.py` against F-058 (no exponent strings; exact tick multiples).
7. **L5:** listenKey keepalive interval, and whether a `listenKeyExpired` event triggers reconnect plus reconcile.
