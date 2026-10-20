# Binance Integration

## 1. Product

Target integration: Binance USDⓈ-M Futures (`fapi`).

Always re-check the official USDⓈ-M docs before implementation because endpoints and order semantics can change.

Official documentation entry points:

- [USDⓈ-M Futures API](https://developers.binance.com/docs/derivatives/usds-margined-futures/)
- [New Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)
- [Market Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api)

## 2. Python SDK

Use the current official Binance Python connector for USDⓈ-M Futures where its supported API surface matches the requirement. The current SDK family supports REST, WebSocket API and WebSocket Streams and documents Python 3.10+ support.

Wrap SDK clients behind project adapters. Do not let SDK-generated/Pydantic response models become domain entities.

The dependency version must be pinned/locked by the project environment and re-verified during upgrades.

### Environments and client configuration (Phase 18)

The environment is chosen explicitly: `DEMO`, `TESTNET` or `LIVE`, matched exactly, with no default and nothing inferred from a host name (`parse_environment` in `src/adapters/binance_client.py`). Each environment has one row of URLs (`ENVIRONMENT_ROWS` in the same module). The owner-open parts of the rows are the user's decision recorded in `.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md`, and tests compare the rows with that record:

- DEMO is the smoke and probe environment. REST uses the SDK's Demo constant; the WebSocket Streams URL is the user's recorded value `wss://demo-fstream.binance.com`; the WebSocket API is NOT_CONFIGURED (the phase uses the REST listenKey and WebSocket Streams). The Demo smoke of 2026-10-16 (plan 18-18) observed that Demo serves a listenKey and a user-data stream at that URL through the SDK route; that is demo-observed, not mainnet, and no documentation page says it (section 5); verify against current Binance docs before implementation.
- TESTNET is NOT_CONFIGURED: by the user's decision the legacy testnet stays unconfigured.
- LIVE uses the SDK production constants for all three surfaces and additionally requires the live enablement state to be enabled; nothing in the client enables LIVE.
- Selecting a surface that is NOT_CONFIGURED raises `EnvironmentNotConfigured` before any SDK object is built.

One factory: `build_sdk_client` is the only place in `src` that constructs a `DerivativesTradingUsdsFutures` client able to sign requests. It builds the REST, WebSocket Streams and WebSocket API configurations from the one row, gives every surface that was not requested an inert `.invalid` URL, and runs `assert_environment`, which re-reads every surface and accepts only the exact row URL (a host suffix, userinfo, a port, another path or another scheme raises `EndpointViolation`). The guard can be re-run on a built client before use.

Credentials: the variable names per environment are the user's (`CREDENTIAL_SPECS`). DEMO and LIVE have distinct names, and TESTNET has none (asking for them raises `CredentialNamesNotRatified`). Each value is read from the named environment variable or from the file named by `<NAME>_FILE` (an absolute path outside the repository), never from the command line or the repository; setting both is refused. Loaded values are registered with the process redactor.

Client limits and signed calls: the REST timeout, the SDK's own retries and backoff, the explicit recvWindow, the rate-limit waits, the drift limits and the stream limits are the user's values in `config/binance/binance-limits-v1.toml`, loaded by `load_binance_limits` (`src/adapters/binance_limits.py`). This document and the code carry none of the numbers; `config/binance/README.md` explains each key. recvWindow is sent explicitly on every signed call. The clock-drift guard (`ClockDriftGuard`, `src/adapters/binance_clock.py`) fails closed: a missing measurement, a failed measurement, an out-of-limit offset or a stale verdict blocks new entries. An HTTP 418 is never retried and bans REST; a 429 retries no call and pauses every REST call of the process; the end of either wait proves nothing about any order. The decision row is D072 in `DECISIONS.md` ("Phase 18 client configuration, user-data stream and exchange error taxonomy"), which carries the sha256 of the limits file. The recvWindow and rate-limit statements rest on WebFetch summaries of 2026-10-16 (`SOURCES.md`, "Facts read for Phase 18"), not on a live check; verify against current Binance docs before implementation.

## 3. Market data

Use:

- REST for bootstrap/history/reconciliation.
- WebSocket for realtime market events.

Binance is believed to document a 24-hour validity for a single market WebSocket connection, ping/pong requirements, stream limits, and to recommend WebSocket user data for order/position status when REST may be delayed under volatility. [Binance WebSocket market streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market-data-streams) These statements were not confirmed on a fetched page on 2026-09-30; verify against current Binance docs before implementation.

WebSocket URL paths (F-053): streams are served on separate paths of `wss://fstream.binance.com`:

- `/public`: order-book style streams such as bookTicker and depth;
- `/market`: aggTrade, markPrice, kline, ticker and similar market streams;
- `/private`: user data streams, connected with a listenKey.

The legacy single `/ws` endpoint was scheduled for retirement on 2026-04-23 ("permanently decommissioned" after that date), and a connection that was not migrated only receives `/public` data. The adapter must therefore open the path that matches each stream family and treat a silent socket on the legacy URL as a defect. Sources: [Important WebSocket Change Notice](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice) and the [Futures change log](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log) (2026-03-05 new URL path sections, 2026-04-02 decommissioning date); verify against current Binance docs before implementation.

## 4. Kline processing

Strategy should normally evaluate only closed candles.

For WebSocket kline streams, implement and test the closed-candle state rather than recalculating a live strategy from an unfinished candle.

## 5. User data

Use the user-data stream to receive order/position/account events. It is consumed on the `/private` path with a listenKey (section 3, F-053); verify against current Binance docs before implementation.

Stream lifecycle as documented (Phase 18, D-19 and D-20). The URL, read date and method of every statement below, and the remaining gap of every page that is still unread, are in `SOURCES.md`, section "Facts read for Phase 18". The statements rest on WebFetch reads of 2026-10-16 at the current documentation locations: the user-data-streams page ([Binance user data streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/user-data-streams)), the REST `user-data-streams` group, the WebSocket API general-info page and the change-log. WebFetch passes a page through a small summarising model, so a quoted sentence is not guaranteed to be character-exact. None of these documentation statements is verified on mainnet; what the Demo smoke (plan 18-18) and the Demo probe (plan 18-20) observed on 2026-10-16 is listed after the lifecycle list, labelled demo-observed, not mainnet.

- listenKey lifecycle: `POST /fapi/v1/listenKey` starts a user-data stream and returns `{"listenKey": "..."}`; on an account that already has an active listenKey the existing key is returned and its validity is extended by 60 minutes, so there is one key per account. `PUT /fapi/v1/listenKey` extends the validity by 60 minutes and `DELETE /fapi/v1/listenKey` closes the stream (200 OK, no data). Each call has IP weight 1 and sends only the API-key header.
- Validity: "A User Data Stream listenKey is valid for 60 minutes after creation"; the REST page says the stream closes after 60 minutes unless a keepalive is sent and recommends a ping about every 60 minutes.
- URL: the base URL is `wss://fstream.binance.com/private` and user data streams are accessed at `/ws/<listenKey>`, so a connection opens `wss://fstream.binance.com/private/ws/<listenKey>`. The page shows no `?listenKey=` query form and no `events=` parameter. This contradicts the Phase 18 research baseline, which recorded `wss://fstream.binance.com/private/ws?listenKey=<listenKey>&events=ORDER_TRADE_UPDATE/ACCOUNT_UPDATE` from the Important WebSocket Change Notice page (not re-read). The adapter must not assume the query form; plan 18-18 confirms the accepted form live.
- Connection lifetime: "A single connection is only valid for 24 hours; expect to be disconnected at the 24 hour mark" (user-data-streams page). Ping and pong: the WebSocket API general-info page says the server sends a ping every 3 minutes and disconnects a connection that sends no pong within a 10 minute period, with at most 5 ping or pong frames per second. That page describes the WebSocket API; the market-streams Connect page, which the research read as stating the same rule for streams, was not re-read, so applying the rule to a `/private` connection is a reading, not a separate statement.
- Ordering: for one user on one connection, messages of the same event type are strictly ordered by `T` (transaction time) and `E` (event time). Nothing is documented about the order between different event types, for example `ACCOUNT_UPDATE` versus `ORDER_TRADE_UPDATE`.
- `ORDER_TRADE_UPDATE` (orders and fills): execution type `x` NEW, CANCELED, CALCULATED (liquidation execution), EXPIRED, TRADE, AMENDMENT (order modified); order status `X` NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, EXPIRED_IN_MATCH. A liquidation carries a client id `autoclose-...` and an ADL the client id `adl_autoclose`, both with `X` NEW; the expiry reason `er` has codes 0 to 9. The page has no `settlement_autoclose` prefix, although the research search summary listed one.
- `ALGO_UPDATE` (conditional-order lifecycle): statuses NEW, CANCELED, TRIGGERING, TRIGGERED, FINISHED, REJECTED, EXPIRED, with their meanings in `EXECUTION_SPEC.md` section 6.1; FINISHED means filled or canceled in the matching engine. The change-log entry of 2026-08-21 says ALGO_UPDATE events for trailing stop orders may arrive twice, once with `ia:false` and again with `ia:true`, so the event router must deduplicate them.
- `ACCOUNT_UPDATE` (balance and position changes): reason `m` DEPOSIT, WITHDRAW, ORDER, FUNDING_FEE, WITHDRAW_REJECT, ADJUSTMENT, INSURANCE_CLEAR, ADMIN_DEPOSIT, ADMIN_WITHDRAW, MARGIN_TRANSFER, MARGIN_TYPE_CHANGE, ASSET_TRANSFER, OPTIONS_PREMIUM_FEE, OPTIONS_SETTLE_PROFIT, AUTO_EXCHANGE, COIN_SWAP_DEPOSIT, COIN_SWAP_WITHDRAW; only symbols whose position changed are pushed.
- `listenKeyExpired`: unrelated to a WebSocket disconnection; it fires only when a valid listenKey on the connection expires, and no further user data is pushed until a new valid listenKey is used. Its schema keys are `e`, `E` and `listenKey`.
- The page also has sections for Margin Call, Account Configuration Update (`ac.s` symbol, `ac.l` leverage, `ai.j` Multi-Assets margin mode), Trade Lite, Conditional Order Trigger Reject, Strategy Update and Grid Update (Deprecated).

Demo-observed (live Demo smoke of 2026-10-16, user-run, BTCUSDT; every statement is demo-observed, not mainnet, not verified on mainnet; the rows, evidence file names and check-file items are in `SOURCES.md`, subsection "Demo-observed facts" of the section "Facts read for Phase 18"):

- Demo serves `POST /fapi/v1/listenKey` and a user-data socket (`wss://demo-fstream.binance.com`, reached through the SDK `user_data` route; private connections: 1). Typed `ORDER_TRADE_UPDATE` events NEW and CANCELED were delivered by that route, so the transport decision is `sdk` and no direct transport (plan 18-19) was needed.
- The listenKey keepalive (`PUT`) passed. A forced transport drop took the stream UNKNOWN, then SYNCING, then LIVE (gap_ms=1431, one REST snapshot after the drop).
- A `PUT` after a `DELETE` of the listenKey answered HTTP class BAD_REQUEST with code -1125, the code that was assumed before the smoke. No other keepalive-of-an-expired-key case was observed.
- Not recorded by the smoke check file: which URL form the server accepted for a connection (the `events` parameter and the query form stay as stated above), the payload field tables, and anything on mainnet.

Still UNVERIFIED, and not to be read as confirmed: the payload field tables of `ORDER_TRADE_UPDATE` (`o.*`, including the meaning of `t` for events that are not TRADE), `ALGO_UPDATE` (`o.*`, including `o.rm` and the child-order identity after a trigger) and `ACCOUNT_UPDATE` (`a.*`, `B`, `P`), which did not render, so field names and types rest on the installed SDK models; whether a FUNDING_FEE event on a cross position carries `P` (the summary names `P` for an isolated position only, the research summary said a cross position carries `B` and `P`); the JSON `SUBSCRIBE` parameter format for a listenKey on `/private`, the message envelope, and whether the `events` URL parameter is accepted at all; whether any documentation page states that Demo Trading serves `POST /fapi/v1/listenKey` and a user-data stream (the Demo smoke observed it, demo-observed, not mainnet; `wss://demo-fstream.binance.com` comes from the user's record and a single tool summary); the error a keepalive of an expired key returns on a documentation page (-1125 "This listenKey does not exist" is on the error-code page and was observed on Demo for a PUT after a DELETE, demo-observed, not mainnet, but the listenKey endpoint pages list no errors); the REST `algoStatus` value list (Query Algo Order does not enumerate it; the Demo probe saw only NEW, demo-observed, not mainnet); a limit on new connections. Verify against current Binance docs before implementation.

## 6. Orders

The execution layer must support only the order types explicitly required by the frozen strategy.

Do not implement every Binance order type preemptively.

Conditional orders such as `STOP_MARKET` / `TAKE_PROFIT_MARKET` were migrated to the USDⓈ-M Algo Order service. The implementation must use the current Algo Order endpoints and `ALGO_UPDATE` lifecycle for these order types; do not assume the legacy normal-order endpoint accepts them. Flags such as `reduceOnly`, `closePosition`, position side, working type, and GTD must be verified against the current Algo Order API. [Binance Futures changelog](https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log)

Working type (D037): protective triggers use the mark-price series, so `workingType` must be sent explicitly as `MARK_PRICE` on every protective order. The Algo Order API default is `CONTRACT_PRICE`, so the adapter must never rely on the default. The audit's alternative `CONTRACT_PRICE` recommendation is not adopted. [Binance New Algo Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order) Verify against current Binance docs before implementation.

### 6.1 Client order id uniqueness (Phase 17, D051)

Binance documents `newClientOrderId` (normal orders) and `clientAlgoId` (Algo Orders) as "A unique id among open orders", automatically generated if not sent, matching `^[.A-Z:/a-z0-9_-]{1,36}$`. A duplicate id raises error `-4116 DUPLICATED_CLIENT_ORDER_ID` ("clientOrderId is duplicated") for normal orders; the Algo Order page names no error code for a duplicate `clientAlgoId`, so none may be assumed. [Binance New Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order), [Binance New Algo Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order), [Binance error codes](https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code) The provenance (which pages could be read, snapshot dates, SDK docstring fallback) and the confidence are recorded in `SOURCES.md`, section "Facts verified for Phase 17"; verify against current Binance docs before implementation.

Consequence: the id is unique only among open orders, so once an order is FILLED or CANCELED its id is free again and the exchange would accept a second order with the same id. The exchange therefore cannot be relied on to deduplicate a replayed entry; the persisted execution intent is the guard (`EXECUTION_SPEC.md` section 7). The earlier Phase 08 premise that the exchange rejects a replayed `clientOrderId` was true only while the first entry was still open (audit F-126, F-951). The deterministic ids from `src/execution/order_ids.py` still matter, but for a different reason: they let a query by client id find the order after an ambiguous response or a restart.

Query Order (`GET /fapi/v1/order`, weight 1) does not find an order when its status is CANCELED or EXPIRED with no filled trade and it was created more than 3 days ago, or when it was created more than 90 days ago. A "not found" answer is therefore a definitive absence only for an intent younger than 3 days (`EXECUTION_SPEC.md` section 10). The retention of the algo-order query is not documented and is treated as unknown. [Binance Query Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Order)

### 6.2 Exchange error classification (Phase 18)

Every failed Binance REST call is classified into one category from the triple (SDK error class, integer Binance code, call kind) and from nothing else; the message text is never read or parsed (D-10). The classifier and its code table are in `src/domain/exchange_errors.py` (`ERROR_CODE_TABLE`, `classify`, `retry_eligible`, `safe_mode_eligible`, `rate_limit_decision`). The categories are ORDER_ABSENT, DUPLICATE_CLIENT_ID, REJECTED_DEFINITIVE, PRECONDITION_NO_POSITION, CLOCK_SKEW, AUTH_OR_SIGNATURE, RATE_LIMITED, IP_BANNED, SYSTEM_THROTTLED, STATUS_UNKNOWN, INVALID_LISTEN_KEY, POSITION_MODE and UNKNOWN_EXCHANGE_ERROR. Which code is which category on which call kind, and the evidence label of each code (documented, demo-observed), are not repeated here, so that this document cannot disagree with the code: read the table and the error-code row of the section "Facts read for Phase 18" in `SOURCES.md` (documentation read 2026-10-16, with the second read of 2026-10-17 for four codes under the owner's decision `.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-TAXONOMY-CODES.md`). The call kind matters: the same code can be a definitive rejection on a placement and unknown on another call kind.

- Unknown-code rule: a code or class that is not in the table, a missing code, and a code not expected on that call kind are UNKNOWN_EXCHANGE_ERROR: ambiguous, never read as "order absent", never retried, and the only category that is SAFE_MODE-eligible by the taxonomy (D-10). The taxonomy does not decide SAFE_MODE for a rejected protective order: the execution manager enters SAFE_MODE on any protective leg it cannot confirm, whatever the category, and a rejection is never evidence that an order is protected.
- Retry rules (D-11; the user's record `18-DEC-O-18-01.md` and its amendment of 2026-10-16): a placement is never retried because of a classification; only a STATUS_UNKNOWN failure of a query, cancel, time or listenKey call may be retried, within a bounded project retry (the SDK's own retries are off); an HTTP 418 is never retried and blocks REST for a valid Retry-After or, without one, for the ratified 418 fallback; no call is retried because of an HTTP 429, which pauses every REST call of the process for a valid Retry-After or, without one, for the ratified 429 fallback (user amendment of 2026-10-16); one process-wide gate holds the ban and the pause, and while it holds every REST call of every holder is refused without being sent; every wait is capped by the ratified cap; the numbers live only in `config/binance/binance-limits-v1.toml` (section 2) and not in this document or in the classifier. A body code -1008 under a 400 is SYSTEM_THROTTLED, not RATE_LIMITED (quick task 261020-g1a): Binance documents it as the node's system-level overload protection, not counted toward rate limits, with reduce-only and close-position orders exempt; it is never recorded in the gate (nothing else of the process is paused) and the call that got it is never retried (a placement is never re-sent).
- A protective order that cannot be placed or confirmed because of a pause or a ban is reported as an unprotected position for Phases 19 and 20 to handle; it is never swallowed and never retried silently.
- The end of a wait proves nothing about an order, a cancel, a fill or a protective stop, and never by itself restores protection status or allows entries while account state is unknown; the state stays fail-closed and goes through reconciliation.

The classification rests on documentation reads (WebFetch summaries, not character-exact) and on the answers of the Demo probe of 2026-10-16 (demo-observed, not mainnet, `SOURCES.md`, subsection "Demo-observed facts"); mainnet answers are not verified. The documentation page lists more codes than the table holds on purpose: a code that is not in the table is UNKNOWN_EXCHANGE_ERROR until the owner decides otherwise. Verify against current Binance docs before implementation; the error-code page changes over time.

## 7. Position mode

The application must read and record:

- One-way/Hedge mode,
- Multi-Assets/Single-Asset mode where relevant,
- leverage/configuration,
- symbol filters, read from `exchangeInfo` and never hard-coded.

Symbol filters that constrain sizing (F-056): besides the price, lot and minimum-notional filters, read `MARKET_LOT_SIZE` (the quantity rules for MARKET orders: quantity within minQty and maxQty on the stepSize grid) and `PERCENT_PRICE` (the valid price range relative to the mark price: a BUY price at most markPrice times multiplierUp, a SELL price at least markPrice times multiplierDown). [Binance common definitions](https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition) The page describing them is otherwise stale on the conditional-order limit (see `SOURCES.md`); verify against current Binance docs before implementation.

Unverified audit claims (F-056): that a triggered `*_MARKET` protective exit with an explicit quantity falls under `MARKET_LOT_SIZE`, and that reduce-only legs skip `MIN_NOTIONAL`, come from the audit and are not confirmed by the fetched documentation pages. The Demo probe of 2026-10-16 answered part of the questions on the Demo environment only (demo-observed, not mainnet; rows in `SOURCES.md`, subsection "Demo-observed facts"), and Phase 19 must not rely on either claim on that basis:

- Minimum notional of a reduce-only conditional leg: with the position open, a reduce-only `STOP_MARKET` of quantity 0.0001 (notional 7.890670 against a `MIN_NOTIONAL` of 50) was accepted at placement (status NEW). That is a placement answer on Demo only. Whether such a leg triggers and executes was not observed (the triggered-lifecycle case was NOT_OBSERVED), so the exemption stays unverified on mainnet.
- `MARKET_LOT_SIZE` on a triggered market exit: the market lot filters read on Demo were min 0.0001, max 120, step 0.0001. Whether a triggered market exit above the maximum is rejected was not observed (the optional probe case was off). This claim stays unverified.

Until both are confirmed on mainnet, treat each as a possible rejection cause; verify against current Binance docs before implementation.

## 8. OI

Current OI endpoint is available for a symbol. Historical Open Interest Statistics are documented as limited to the latest month; use a collector for long-term research data. [Binance Open Interest](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)

## 9. Conditional/algo orders

Track normal orders and algo/conditional orders separately. On reconnect or recovery, query both sets before resuming live approval. Binance documents separate current-open-algo-order endpoints and an `ALGO_UPDATE` event family. The `ALGO_UPDATE` statuses and the trigger-time failure modes (FINISHED does not mean filled; REJECTED and EXPIRED can occur after the stop was accepted) are specified in `EXECUTION_SPEC.md` section 6.1 (F-054), and the 200 open conditional-order limit is account-wide (`EXECUTION_SPEC.md` section 12).

## 10. Reconciliation

Startup:

```text
connect
→ bootstrap orders/positions
→ start user data stream
→ compare state
→ only then enable live approval
```

After disconnect:

```text
reconnect
→ query authoritative state
→ replay/refresh local state
→ resume
```

## 11. Security

API key must not have withdrawal permissions.

Prefer IP restrictions and secret storage outside source control.

## 12. Account commission rate

Live sizing must not use a modeled fee that could sit below the account's real fee tier (F-962). The adapter reads the account's rate per symbol with `GET /fapi/v1/commissionRate` (USER_DATA, signed; request weight 20 on the IP limit; parameters `symbol` required and `recvWindow` optional; response fields `symbol`, `makerCommissionRate`, `takerCommissionRate` and `rpiCommissionRate`, all strings) through the official SDK method `user_commission_rate`. [Binance User Commission Rate](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate) Verify against current Binance docs before implementation: the official page was reached only through search-result text, the installed SDK 17.4.0 and the change-log (see `SOURCES.md`, "Facts verified for Phase 12"), and the behavior of the endpoint on Binance Demo or testnet is not documented in any retrieved material and is verified in the Phase 24 demo stage.

Sizing rule (D-10, D036): live sizing uses `max(parameter rate, account taker rate)` per side. Entry and the protective stop exit are both taker fills, so the account taker rate applies to both sides; the maker rate is read and validated but not used for sizing, and the `rpiCommissionRate` field is ignored. The BNB fee discount is ignored in sizing (F-031): the modeled cost is never reduced below the versioned parameter rate. A real account rate of 0 is legitimate and is floored by the parameter rate. The resulting rates carry the fee source `ACCOUNT_MAX`.

Fail-closed rule (D-11): if the account rate is missing, older than `commission_rate_ttl_seconds` (baseline 3600 seconds), dated in the future, for a different symbol, or malformed, live entries are NO_TRADE with reason `UNCERTAIN_ACCOUNT_STATE`. The adapter raises on any malformed field and never returns 0 for an unknown rate; the resolver never sizes with zero and never silently falls back to the parameter rate, because the parameter rate is a floor and not a substitute for an unknown account state.

Backtest and paper keep the versioned parameter fees so a run stays reproducible from the parameter-set hash (D-12). The scheduler and cache refresh loop that keep the account rate fresh at runtime are Phase 24 work (D-13); Phase 12 adds only the adapter method and the pure resolution.

## 13. Historical market data (Phase 13)

Mark-price klines (D-11, D-12): `GET /fapi/v1/markPriceKlines` (weight 1, 2, 5 or 10 by `limit`; page size 1000 costs weight 5; the maximum is 1500) is stored as its own Parquet dataset under `data/raw/dataset=mark_klines`, never mixed into the trade-candle store. The volume fields are always `"0"` and the count field is a price-update count, so the dataset has no volume and no trade count; the count is kept as `price_tick_count`. The series is a trigger series for the Phase 14 simulator (D037), where protective triggers use the mark price; Phase 13 only collects it. Sources: [Mark Price Kline/Candlestick Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data), registered in `SOURCES.md` ("Facts verified for Phase 13"). The page itself could not be read in the verifying run (WAF challenge); the facts come from the installed SDK docstring and live requests, so verify against current Binance docs before implementation of anything that depends on them.

Endpoints used by the backfill, the freeze tool and the collector (all public, unsigned, through `BinanceUsdmAdapter`; the register with URL, fetch date, method and confidence is `SOURCES.md`, "Facts verified for Phase 13"):

| Endpoint | Weight | Phase 13 use |
| --- | --- | --- |
| `GET /fapi/v1/klines` | 1, 2, 5 or 10 by `limit` (page size 1000 costs 5) | trade candles for 1m, 1h and 4h; freeze ranking uses 1d |
| `GET /fapi/v1/markPriceKlines` | same tiers | mark-price series, separate dataset |
| `GET /fapi/v1/exchangeInfo` | 1 | `status`, `contractType`, `onboardDate`, `deliveryDate`, symbol filters |
| `GET /fapi/v1/fundingRate` | shared 500 requests per 5 minutes per IP | funding history (limit at most 1000 per page) |
| `GET /futures/data/openInterestHist` | 0 (1000 requests per 5 minutes) | only the latest month is served, so long OI history exists only if the collector has been running |
| `GET /fapi/v1/ticker/24hr` | 1 per symbol, 40 without a symbol | collect-list proposal by 24h quote volume |
| `GET /fapi/v1/time` | 1 | warn-only clock probe |

Pacing: the backfill walks symbols and intervals sequentially with page size 1000 (weight 5 per page) and a default pause of 0.25 seconds between pages (`--pace-seconds`), which stays far below the 2400 per minute request-weight limit that exchangeInfo reports. Rate-limit responses are retried a bounded number of times with backoff; every other error fails the run instead of being classified as missing data.

Delisted and delivered contracts (D-06 to D-09, D-26). exchangeInfo lists contracts with status `SETTLING` (delivered or delisted) and `PENDING_TRADING` besides `TRADING`, and the live response also carries `contractType` `TRADIFI_PERPETUAL`, which the documented enum page does not list; Phase 13 uses only `PERPETUAL` contracts quoted in USDT. A `TRADING` perpetual carries a far-future `deliveryDate` sentinel, so only a non-`TRADING` contract has a real delivery time. Observed by live probe only (MEDIUM confidence): REST still serves klines for many delisted contracts, answers -1121 `Invalid symbol.` for others, and serves flat bars with volume 0 and 0 trades after `deliveryDate`. The backfill therefore never assumes availability:

1. REST first. A window is `max(depth start, onboardDate)` to `min(run day floor, deliveryDate)`; a non-`TRADING` contract without a `deliveryDate`, or a symbol exchangeInfo no longer lists, gets no window from REST (cause `DELIVERY_UNKNOWN`) and is never fetched up to today, because the exchange would serve invented flat bars.
2. Archive fallback. Only a REST -1121, or a symbol absent from exchangeInfo, moves that symbol to data.binance.vision, capped at its delivery time or its last archive day. Mark-price klines have no archive source here: the mark dataset for such a symbol is REST-only or `UNAVAILABLE`, and is never derived from trade data.
3. Unavailable symbols are listed in the sufficiency report and the freeze report (cause `UNAVAILABLE`), never dropped silently and never guessed.

Archive fallback (D-08). The archive is `https://data.binance.vision/data/futures/um/{monthly,daily}/klines/<SYMBOL>/<interval>/<SYMBOL>-<interval>-<period>.zip`, each zip with a `<name>.zip.CHECKSUM` file holding `<sha256 hex>  <zip name>`. The reader downloads a monthly zip, falls back to its daily zips when the month is absent (404), verifies the sha256 before parsing, caps download and member size, reads the single expected member in memory and never extracts to disk, then feeds the rows through the same paginator, quality gate, closed-day rule and atomic publisher as REST data. The `.CHECKSUM` file is served by the same origin as the zip, so the check proves transport integrity only and is not an authenticity control; the quality gate still applies to every archive row. Archive-only symbols are discovered from the bucket listing (`https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/`), an S3 `ListBucketResult` that is truncated at 1000 keys and must be paged with its marker. Archived files may be replaced later by Binance (the public-data README keeps an updates table), which is why a re-written dataset gets a new identity (`DATA_MODEL.md` section 2.13). Verify against current Binance docs before implementation: none of the data.binance.vision layout or listing behavior above is documented for USD-M futures beyond the README mapping, and it was established by live requests on 2026-09-30.

Funding and open interest. Funding history is paginated with `startTime` and at most 1000 rows per call (about 333 days of 8-hour ticks); `fundingTime` can differ from the 8-hour grid by a few milliseconds, and historical rows before 2024 can carry an empty `markPrice`, stored as null. Open-interest statistics are limited to the latest month by the API, so the collector is the only long-term OI source (F-107); the funding and OI collector polls the versioned collect list (`CONFIGURATION.md` section 3), not the five live symbols.
