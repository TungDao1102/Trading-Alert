# Phase 18: Binance User-Data Stream + Exchange Error Taxonomy - Research

**Researched:** 2026-10-15
**Domain:** Binance USDⓈ-M Futures user-data stream (listenKey, ORDER_TRADE_UPDATE, ALGO_UPDATE, ACCOUNT_UPDATE), exchange-error taxonomy by int code, client configuration (timeouts, keys, Demo/testnet/live, recvWindow, clock drift), Demo probe design
**Confidence:** MEDIUM overall. The SDK surface and the in-repo integration points are HIGH (installed source and repository files read this session). Binance documentation facts are MEDIUM at best: every page was read through WebFetch summaries (a small model summarises the page), four event pages could not be read at all, and nothing was verified live (this machine has no Binance connectivity).

**Machine rule applied (user, 2026-10-15):** no Binance or Telegram endpoint was called. Documentation pages were read with WebFetch (documentation host only). A failed read was retried once and then recorded as UNVERIFIED (see "Fetch log"). No Wayback, mirror, or alternative host was used for Binance facts. Installed SDK source (`binance-sdk-derivatives-trading-usds-futures` 17.4.0, `binance-common` 4.4.0 in `C:\Users\admin\Music\Trading\.venv\Lib\site-packages`) was READ, never executed.

<user_constraints>
## User Constraints (from CONTEXT.md)

Copied verbatim from `18-CONTEXT.md` (gathered 2026-10-15, mode --auto). The planner MUST honor these.

### Locked Decisions

#### Stream architecture
- **D-01:** The stream lives in a new adapter module `src/adapters/binance_userdata.py` behind a project-owned interface (Protocol) in the style of `src/adapters/paper_ws.py`. SDK response and event models never leave the adapter; it emits frozen, SDK-free dataclasses (Decimal for money and quantity, UTC-aware datetimes, non-empty strings) exactly like the Phase 8 snapshots in `binance_usdm.py`. — **Reversibility:** costly — every Phase 19, 20 and 24 consumer will import these event types.
- **D-02:** Use the official SDK `binance-sdk-derivatives-trading-usds-futures` (17.4.0 in `uv.lock`) for the `/private` socket and for the listenKey REST calls; direct HTTP/WS only for a gap the SDK cannot cover, and the research must say which of the two the SDK offers today (listenKey REST vs WS API user-data subscription). The listenKey lifecycle (start, keepalive, close, expiry handling) is implemented as documented on the live page at plan time, not from memory. SDK internals the stream depends on are pinned by a contract test in the style of `tests/test_paper_ws_contract.py`.
- **D-03:** One supervisor coroutine owns connect, keepalive, the 24-hour rotation, reconnect with bounded backoff (tenacity, capped attempts, never infinite on an order-relevant path), and a clean stop. It follows the structure of the Phase 16 `PaperSupervisor` where that fits, without importing from `src/paper`. A reconnect, a rotation or a missed keepalive marks the stream UNKNOWN for the duration of the gap and triggers a REST snapshot before any event after the gap is trusted.
- **D-04:** Composition into a running process is NOT in this phase. Phase 18 ships the library, a fake-driven test rig, and a connected-machine smoke script (`scripts/`), as Phase 16 did with `paper_ws_smoke.py`. Process wiring belongs to the phases that compose the runtime (24, 25).

#### Event handling and state authority
- **D-05:** The stream is a low-latency hint plus evidence; Binance REST snapshots remain the authority (AGENTS.md exchange authority). Events never fabricate state: an event for an unknown order, a malformed payload, an unknown `algoStatus`, or a field that fails Decimal/UTC validation is journaled as a stream anomaly and surfaced as a divergence for the reconciler; it is never silently dropped or coerced (09-REVIEW WR-04 precedent in `fold_fills`).
- **D-06:** `ORDER_TRADE_UPDATE` becomes `FillEvent`s consumed by the existing `fold_fills` (`src/execution/fill_monitor.py`) with the unique key `(order_id, exchange_trade_id)`, so replays and out-of-order delivery stay idempotent. `commission` and `commissionAsset` are parsed and carried through (G3-009) so Phase 21 can use them; Phase 18 does not compute daily loss.
- **D-07:** `ALGO_UPDATE` is parsed into an algo-order event carrying `X` (algo status), `rm` (reject reason, the replacement for the removed `CONDITIONAL_ORDER_TRIGGER_REJECT`) and `ia`. The algo status classification (G2-028) is a documented table covering NEW, TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED: each value is classified ACTIVE, TERMINAL_OK, TERMINAL_FAILED or UNKNOWN and used by attach, reconcile and the sweeper; today `_ACTIVE_ALGO_STATUSES` is `{"NEW"}` only. An unseen status value classifies UNKNOWN (fail closed), never ACTIVE.
- **D-08:** `ACCOUNT_UPDATE` is parsed into balance and position deltas as events only. Wiring them into equity, margin or the position view is Phases 20 to 22. Moving an Order or Position out of UNKNOWN requires Binance evidence and the journal records the evidence source, REST reconcile or user-data event (G4-034); Order `exchange_status` and `exchange_order_id` updates get their store methods together with this first caller (G4-043). Persisted stream events use the existing append-only journal; no new table unless the planner shows the journal cannot hold them.

#### Error taxonomy
- **D-09:** A pure module (placed under `src/adapters/` or `src/domain/`, planner's choice, no SDK import in the pure part) maps an int Binance `status_code` to a project category. Required codes: -2011, -2013, -2019, -4164, -1021, -2021 (ROADMAP criterion 2), plus -4116 and -4509 (known from Phase 17 and D055), 418 and 429 (rate limit and ban, reusing `is_rate_limit_error`, `is_rate_limit_ban_error`, `rate_limit_retry_after_seconds`), and -1022 (signature) if the docs list it. Each code carries its documentation source and read date, and codes seen only on Demo are labelled demo-observed (09-DEMO-REHEARSAL-FINDINGS finding 1: -2013 for GET algoOrder not found).
- **D-10:** Classification is by `status_code` only. The message-text and regex fallbacks (`_NOT_FOUND_MESSAGE`, `_is_already_canceled_message`) are removed or reduced to a logged diagnostic that cannot change a decision. A code that is not in the table is category UNKNOWN_EXCHANGE_ERROR and is treated as ambiguous: no retry on a placement path, SAFE_MODE-eligible, never mapped to "absent".
- **D-11:** Placement is never retried inside the adapter (09-REVIEW CR-09 stays). Retry is allowed only for read and cancel paths on transient categories, bounded by the existing reconciler ceilings (`_RECONCILER_CANCEL_*`). 418 never retries and waits `retry_after`; 429 honors `retry_after` and backs off. Timeout or 5xx on placement stays "execution status unknown" and goes to the probe-by-deterministic-client-id path (EXECUTION_SPEC section 10).

#### Client configuration and environment selection
- **D-12:** One configuration function builds the SDK client for an explicit environment value `DEMO | TESTNET | LIVE`, with hosts from a table verified against current docs (Demo is `demo-fapi.binance.com`, already used by `scripts/demo_rehearsal.py`). There is no default environment inferred from the host: a missing or unknown value raises. LIVE additionally requires the existing enablement state; this phase builds the selector, it does not enable live. The mainnet-host guard generalizes `assert_demo_sdk_client` from `scripts/demo_rehearsal.py` into a production module that the rehearsal and probe scripts reuse.
- **D-13:** API keys load from the environment or a file path, never from a CLI argument or the repository; key and secret are redacted in every log and exception path with a test that greps the structured output (OPS-02, SECURITY_AND_OPERATIONS). No-withdrawal permission and IP allowlisting are attested by the operator, not by code (stays a Phase 24 to 26 HUMAN item).
- **D-14:** Server-time drift is measured against `GET /fapi/v1/time` with a fail-closed outcome: drift beyond the limit, or a failed measurement, blocks new entries and is reported; a -1021 response triggers a re-measure and never an automatic retry of the order. `recvWindow` is set explicitly on every signed call. The numeric limits (timeouts, recvWindow, drift limit, keepalive and rotation margins, reconnect backoff caps, maximum stale-stream age) are SAFETY thresholds: see "Open, user-owned" O-18-01. The plan lists each as a named module constant with a provenance label (STRUCTURAL, COST_GUARD, DECISION or PLACEHOLDER) and never fills a number the user has not ratified.

#### Demo probe (D055 and inherited verification tasks)
- **D-15:** The probe is a script in the style of `scripts/demo_rehearsal.py`: Demo host asserted before any signed call, a dry-run mode that sends nothing, an `--execute` mode that needs the user to type the confirmation phrase themselves, evidence written as JSON with the schema name and version, every artifact scrubbed of secrets. It cleans up every order it opened and records the account state before and after. Results are labelled demo-observed, not mainnet, and are never used to choose a trading parameter.
- **D-16:** Probe cases, in this order of risk: read-only first (GET order and GET algoOrder not-found codes; the duplicate `clientAlgoId` code; id reuse after FILLED and after CANCELED), then the D055 cases (pre-placed STOP_MARKET with explicit quantity and reduceOnly with no position; an entry that never fills then cancelled, is the protective order orphaned and does it cancel cleanly; a full fill; a partial fill; a rejected protective order; reconciliation after each state), then the G2-029 additions (a below-minimum-notional reduce-only conditional leg; the MARKET_LOT_SIZE question for a triggered `*_MARKET` exit). The probe also records which `ALGO_UPDATE` and `ORDER_TRADE_UPDATE` frames arrive for each case, captured as redacted fixtures for the parser tests.
- **D-17:** The probe records facts and stops. It does not close D055: whether protection is placed after the fill or pre-placed stays OPEN until the user records a new DECISIONS row (D055 item 4: alternative (b) is UNVERIFIED on Demo). If the probe disagrees with `BinanceSemanticsFakeAdapter`, the fake is corrected in the same plan that consumes the evidence; if the probe has not run, the fake keeps its documented assumptions and the plan states that.
- **D-18:** Because this machine cannot reach Binance, the work splits into plans that need no network (parsers, taxonomy, supervisor logic against fakes, configuration, contract tests, probe script with a dry-run) and blocking-human plans that need a connected machine (the live smoke, the `--execute` probe). The blocking-human steps carry stated prerequisites and measurable acceptance, and the fixtures they produce feed a follow-up plan or task rather than being assumed in advance.

#### Documentation and fact re-verification (first task)
- **D-19:** First task of the first plan: re-read the official Binance pages for the ALGO_UPDATE status list, the 24-hour WS lifetime, the listenKey lifetime and keepalive rules, the `/private` path, and the Change-Position-Mode wording (G3-001), and update `docs/SOURCES.md` with URL, read date, method and a not-verified-live label. On this machine a failed fetch is retried once, then recorded as UNVERIFIED with the exact failure; the executor on a connected machine repeats it. No exchange fact is taken from memory.
- **D-20:** Doc updates that follow from the facts: the Binance integration doc and `docs/trading/EXECUTION_SPEC.md` where they describe the stream, the error codes and the environment selection; ROADMAP criterion text is corrected if a re-read shows it is wrong. A decision that changes behavior goes into `docs/DECISIONS.md` as a new row (D-number assigned by the planner, next free number), not into this file.

#### Test strategy
- **D-21:** Pure-function tests for the taxonomy and the algo status table; parser tests from recorded or documented sample frames for each of the three event types, including the malformed, unknown-status and duplicate-trade cases; supervisor tests with an injected clock and a scripted fake socket covering keepalive, rotation, reconnect, gap-then-snapshot and bounded backoff; a replay test proving `fold_fills` yields the same position view for a stream replayed, reordered and duplicated; secret-redaction tests. No test touches Binance or Telegram; every network step is blocking-human.
- **D-22:** Determinism and fail-closed rules stay: no float in any exchange-sensitive value, no wall-clock reads in pure code (clock injected), UTC-aware datetimes, byte-stable serialization for anything journaled.

### Claude's Discretion
- Module and file names inside `src/adapters/`, the exact Protocol shapes, the tenacity wiring, and the split of work into plans.
- Whether the taxonomy lives in `src/adapters/` or `src/domain/`, provided the pure part imports no SDK.
- Fixture file layout under `tests/` and the exact evidence JSON schema of the probe, following the Phase 9 and Phase 16 precedents.

### Open, user-owned (an agent must not decide these; D061 items H and I)
- **O-18-01 Safety thresholds.** REST timeouts, recvWindow, the server-time drift limit, the maximum stale-stream age before entries are blocked, keepalive cadence and rotation margin, reconnect backoff caps, and any "stream gap then SNAPSHOT" timing. The planner gathers the constants, the Binance documented limits and the project precedents (Phase 16 O-07 table) into one table with rationale and sources, and stops at a blocking-human checkpoint for the user to ratify before the code plan that needs them executes. No default is filled.
- **O-18-02 D055 execution model.** Protection after the fill versus pre-placed. Stays open; the probe supplies evidence only. The user records a new DECISIONS row after the probe.
- **O-18-03 Probe authorization.** Each `--execute` run is the user's explicit go-ahead on a connected machine; the user types the confirmation phrase. Account state and size limits for the probe (quantity, symbol) are the user's to approve at the checkpoint.
- **O-18-04 Environment choice for the probe.** Demo (`demo-fapi.binance.com`) versus testnet: ROADMAP says "demo or testnet". Recommended: Demo, because Phase 9 already used it and its not-found code is observed there; the user confirms at the probe checkpoint. LIVE is never used by this phase.

### Deferred Ideas (OUT OF SCOPE)
- Composing the stream supervisor into the running process and soak: Phases 24 and 25.
- Using `ACCOUNT_UPDATE` for equity, margin and position truth: Phases 20 to 22.
- Symbol/side/qty binding and live-price check: Phase 19.
- `binance-sdk-algo` TWAP/VP: Phase 3+ evaluation only, not V1.
- The D055 model choice and any change to `execute_approved_plan` ordering: a separate user decision and a new task after the probe.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (from `.planning/REQUIREMENTS.md`) | Research Support |
|----|-----------------------------------------------|------------------|
| EXEC-05 | The Binance user-data stream for order, algo-order, account and position events drives fills and state, with REST as fallback | F1 (listenKey + `/private` + SDK `user_data`), F2 (event schemas and domain mapping), F3 (ALGO_UPDATE status table), supervisor and gap-then-snapshot pattern, pitfalls P2 to P9 |
| EXEC-01 | Execution manager places LIMIT-zone entries and Algo-Order protective exits ... (Implemented and unit-tested, not Demo-proven; D055 open) | F3 (status classification used by attach), F6 (probe inputs for the D055 cases), F4 (error taxonomy on placement and cancel), integration map for `_ACTIVE_ALGO_STATUSES` |
| EXEC-02 | Reconciliation loop compares local state against open normal orders, open algo orders and positions ... (library level with fakes only) | F2/F3 (events as hints plus evidence), F7 (journal evidence for UNKNOWN exits G4-034, store methods G4-043), F4 (not-found and rate-limit handling in sweeper and probes) |
| OPS-02 | Live credentials use no-withdrawal keys, IP allowlisting, off-source secret storage, structured secret-free logging with health checks | F5 (key loading, environment guard, redaction gaps: listenKey not scrubbed, file-loaded keys invisible to `Redactor.from_environ`), Security Domain |
</phase_requirements>

## Summary

The listenKey mechanism is still the current one for USDⓈ-M futures: `POST/PUT/DELETE /fapi/v1/listenKey` (one account-level key, 60-minute validity, no parameters), and the events arrive on the `/private` routed WebSocket path [CITED: developers.binance.com Start/Keepalive User Data Stream and Important-WebSocket-Change-Notice pages, WebFetch 2026-10-15]. The installed SDK 17.4.0 offers exactly one supported route: the listenKey REST calls (`rest_api.start_user_data_stream`, `keepalive_user_data_stream`, `close_user_data_stream`; synchronous `requests`) or the WS-API equivalents (`userDataStream.start/ping/stop`), plus the streams client `DerivativesTradingUsdsFuturesWebSocketStreams.user_data(listenKey)` which opens `/private/stream` and sends `SUBSCRIBE` with the raw listenKey as the stream name. The SDK has no WS-API "subscribe" model for futures. Whether the server accepts a `SUBSCRIBE` that carries a bare listenKey, and whether events then arrive in a `{"stream", "data"}` envelope that the SDK can route to the callback, is UNVERIFIED: the docs only show the URL-parameter form `wss://fstream.binance.com/private/ws?listenKey=<k>&events=...`, and say that JSON `SUBSCRIBE` "may include ... listenKey event items" without giving the parameter format. If the envelope or parameter format differs, the SDK drops every event to an INFO log line. This is the single largest risk of the phase and decides the connected-machine smoke acceptance (first criterion: at least one `ORDER_TRADE_UPDATE` reaches the project callback after a Demo order).

The error surface is narrower than the CONTEXT assumes. In `binance_common` 4.4.0 the exception's `status_code` is the Binance JSON `code` (for HTTP 400/401/403/404/418/429) or the HTTP status (5xx); other 4xx become `ClientError` with `status_code=None`; HTTP 418 and 429 are identified by exception CLASS (`RateLimitBanError`, `TooManyRequestsError`), never by an int, and both carry `retry_after` from the `Retry-After` header. The 5xx body is discarded (`ServerError(error_message=f"Server error: {status}")`), so the documented 503 variants ("Unknown error ... execution may have succeeded" versus "Service Unavailable") cannot be told apart: every 5xx and every `NetworkError` on a placement path must be "status unknown". The taxonomy input is therefore a pair `(sdk error class, int code, retry_after)`, not an int alone.

Everything numeric in O-18-01 is user-owned; this document tabulates documented limits, SDK defaults and project precedents without choosing values. Two findings change how the table is read: (1) silence on the user-data stream is NORMAL (no orders, no events), so a "maximum stale-stream age" cannot be based on event silence; liveness has to come from ping/pong frames and successful listenKey keepalives; (2) the SDK REST client retries GET and DELETE on network errors by itself (`retries=3`, `backoff=1000` ms, `time.sleep` inside the worker thread) and its default timeout is 1000 ms, which stacks with the project's tenacity cancel retry unless the configuration layer sets it explicitly.

**Primary recommendation:** Build the phase as a pure core (event dataclasses, dict-based parsers, algo-status table, error taxonomy, drift and limits structures) tested offline with synthetic SDK-model frames, put every SDK touch behind two thin adapters (`binance_userdata`, `binance_client_config`), pin the SDK internals with offline contract tests (including a stub-session test of `send_request` that proves the HTTP-status to exception-class mapping), and make the first connected-machine smoke prove event delivery through the SDK `user_data` route before any parser is trusted; keep a direct `aiohttp` transport on the documented URL form as a conditional follow-up plan if the SDK route fails the smoke.

## Fetch log and Binance fact register

All fetches 2026-10-15 from this machine. Method "WebFetch" returns a model-written summary, not raw text (quotations are the tool's, not guaranteed character-exact). Every row is **not verified live** (no Binance connectivity). Tags follow the provenance legend: `[CITED]` documentation read this session through the tool; `[VERIFIED: file:lines]` installed source or repository file opened this session.

| # | Source URL (host: developers.binance.com) | Method / result | Facts taken | Confidence |
|---|---|---|---|---|
| B1 | `/docs/derivatives/usds-margined-futures/user-data-streams/Start-User-Data-Stream` | WebFetch OK | `POST /fapi/v1/listenKey`; "The stream will close after 60 minutes unless a keepalive is sent."; an existing active key is returned and its validity extended by 60 minutes; IP weight 1; header `X-MBX-APIKEY` only; response `{"listenKey": "..."}` (64-char example); page has no WebSocket URL form and no 24-hour statement | MEDIUM-HIGH |
| B2 | `/docs/derivatives/usds-margined-futures/user-data-streams/Keepalive-User-Data-Stream` and the landing path `/user-data-streams` | WebFetch OK (the landing path resolved to the REST listenKey page) | `PUT /fapi/v1/listenKey`: "Keepalive a user data stream to prevent a time out. User data streams will close after 60 minutes. It's recommended to send a ping about every 60 minutes."; `DELETE` = "Close out a user data stream."; weight 1; the pages list only 200 responses, no error codes; base URLs shown include `https://testnet.binancefuture.com` | MEDIUM-HIGH |
| B3 | `/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice` | WebFetch OK | Routed paths `/public`, `/market`, `/private` ("Private (user data)"); user-data form: `ws` mode `wss://fstream.binance.com/private/ws?listenKey=<listenKey1>&events=ORDER_TRADE_UPDATE/ACCOUNT_UPDATE`, `stream` mode `wss://fstream.binance.com/private/stream?listenKey=<listenKey1>&events=ORDER_TRADE_UPDATE&listenKey=<listenKey2>&events=ACCOUNT_UPDATE`; "JSON `SUBSCRIBE` messages are also supported, and their params may include market/public streams and listenKey event items" (format not given); legacy URLs "available until 2026-04-23", unmigrated connections only receive `/public`; the page contradicts itself about whether legacy `/ws` public feeds keep working; page footer "Last modified on October 14, 2026" | MEDIUM |
| B4 | `/docs/derivatives/usds-margined-futures/websocket-market-streams/Connect` | WebFetch OK | "A single connection is only valid for 24 hours; expect to be disconnected at the 24 hour mark"; server `ping frame` every 3 minutes, disconnect without a `pong` within 10 minutes, unsolicited pongs allowed; 10 incoming messages per second per connection, repeat offenders may be IP-banned; max 1024 streams per connection; `/private` listed only as "Private (user data)", no listenKey statement; no new-connection rate limit stated | MEDIUM-HIGH |
| B5 | `/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update`, `/Event-Order-Update`, `/Event-Balance-and-Position-Update`, `/Event-Listen-Key-Expired`, and the catalog page `/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/user-data-streams` | **UNVERIFIED (fetch failed: every attempt, plus one retry per page family, returned the Binance Developer Docs landing page shell with no event content; the tool reported "It's the Binance Developer Docs landing page")** | none from these fetches | n/a |
| B5a | same Event-Algo-Order-Update URL | WebSearch summary 2026-10-15 (search tool, `allowed_domains=developers.binance.com`) | statuses NEW, TRIGGERING, TRIGGERED, FINISHED, REJECTED, EXPIRED, CANCELED with the meanings quoted in F3; `rm` documented as "algo order failed reason" with example value `"Reduce Only reject"`; "When new algo order created, order status changed will push such event."; `CONDITIONAL_ORDER_TRIGGER_REJECT` deprecated effective 2025-12-15, rejection reasons now in `ALGO_UPDATE`. Agrees with the Wayback snapshot of 2026-01-13 recorded by an earlier session in `09-EXCHANGE-FACTS.md` Fact 2 | MEDIUM (search summary) |
| B5b | Event-Order-Update and Event-Balance-and-Position-Update URLs | WebSearch summaries 2026-10-15 | `ORDER_TRADE_UPDATE` execution types NEW, CANCELED, CALCULATED (liquidation), EXPIRED, TRADE, AMENDMENT; status `EXPIRED_IN_MATCH` when self-trade prevention ends an order; forced-close client ids start `autoclose-`, `adl_autoclose`, `settlement_autoclose-`; `er` expire-reason field from 2025-10-23. `ACCOUNT_UPDATE` reason `m` values DEPOSIT, WITHDRAW, ORDER, FUNDING_FEE (also WITHDRAW_REJECT, ADJUSTMENT, AUTO_EXCHANGE in older entries), pushed "only when update happens on user's account, including changes on balances, positions, or margin type"; a funding fee on a cross position arrives with `B` and `P` | LOW-MEDIUM (search summary; the order-status list "was not verified beyond what these pages show") |
| B6 | `/docs/derivatives/usds-margined-futures/change-log` (first 100000 of 154346 characters; newest first, range 2025-10-01 onward covered) | WebFetch OK | see F2/F3/F5: 2026-08-21 `ia` "now fully active"; 2026-08-07 ACCOUNT_UPDATE gains `S` for FUNDING_FEE; 2026-07-21 `modifyId` and ORDER_TRADE_UPDATE `x: AMENDMENT` with `M`; 2026-06-20 New Algo Order weight follows order rate limits (IP weight 0); 2026-03-05 `/private` path; 2026-04-02 legacy URL retirement 2026-04-23; 2025-12-29 `MAX_NUM_ALGO_ORDERS` removed, 200 across symbols; 2025-12-10 `CONDITIONAL_ORDER_TRIGGER_REJECT` deprecated; 2025-11-06 conditional orders moved to `/fapi/v1/algoOrder`, old endpoints return -4120; 2025-11-12 Options Demo API with keys created on the demo site; 2026-05-11 new -4531; 2026-09-28 new -4425. No listenKey change, no Retry-After entry, no recvWindow entry in the covered range | MEDIUM |
| B7 | `/docs/derivatives/usds-margined-futures/error-code` (two fetches, same page) | WebFetch OK | code table quoted in F4. Not on the page: -4509, -4510 to -4512, -4531, -4130, -4132, -4136; no HTTP status text and no Retry-After sentence on this page | MEDIUM |
| B8 | `/docs/derivatives/usds-margined-futures/general-info` | WebFetch OK | HTTP codes: 4XX sender error, 403 WAF limit, 408 backend timeout, 429 rate limit, 418 IP auto-banned after continuing past 429, 5XX Binance-side; 503 variants (see F4); ban durations "from 2 minutes to 3 days"; IP limits per IP not per key; `X-MBX-USED-WEIGHT-*` and `X-MBX-ORDER-COUNT-*` headers; timing security: `timestamp` in ms, `recvWindow` optional default 5000 ms, rule `if (timestamp < serverTime + 1000 && serverTime - timestamp <= recvWindow)`, no maximum stated on this page; base endpoints: production REST `https://fapi.binance.com`, "Testnet REST" `https://demo-fapi.binance.com`, "Testnet WebSocket" `wss://demo-fstream.binance.com`; "The page does not mention a Retry-After header" | MEDIUM |
| B9 | catalog trade page `/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade` (section New Algo Order; the direct `/trade/rest-api/New-Algo-Order` URL returned the New Order section instead, so this catalog page was the single retry) | WebFetch OK | `POST /fapi/v1/algoOrder`: `algoType` only `CONDITIONAL`; `timeInForce` `GTC, IOC, FOK, GTX, GTD, RPI` (default GTC for STOP/TAKE_PROFIT types; "GTE_GTC: Not present" in the parameter list); `recvWindow` "max 60000"; `workingType` default `CONTRACT_PRICE`; `closePosition` "Cannot be used with quantity or reduceOnly"; `reduceOnly` "cannot be sent in Hedge Mode, and cannot be sent with closePosition=true"; no minimum-notional statement in the section; -2021 documented for TRAILING_STOP_MARKET activatePrice | MEDIUM |
| B10 | `/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Algo-Order` | WebFetch OK | `GET /fapi/v1/algoOrder`, weight 1, `algoId` or `clientAlgoId`; "will not be found" rules (CANCELED or EXPIRED with no filled trade and created + 3 days < now; created + 90 days < now); response fields `algoStatus` (only example `CANCELED`, possible values not listed), `actualOrderId` ("Empty string if not triggered; orderId if triggered"), `actualPrice`, `actualType`, `actualQty`; "`algoId` is self-increment for each specific `symbol`" | MEDIUM |
| B11 | `/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Position-Mode` (G3-001) | WebFetch OK | `POST /fapi/v1/positionSide/dual`; "If either side has any open order or open position, the change is rejected."; -4067 open orders, -4068 open position; weight 1; `recvWindow` "max 60000"; UM and CM share one setting after CM migration (change-log also lists -4531 for the UM/CM sync) | MEDIUM |
| B12 | `/docs/derivatives/usds-margined-futures/websocket-market-streams/Live-Subscribing-Unsubscribing-to-streams` | WebFetch OK | generic `SUBSCRIBE {"method","params":[...],"id"}` / response `{"result": null, "id"}`; `id` "an unsigned INT"; nothing on `/private` or listenKey params | MEDIUM |
| B13 | WebSearch "Binance Demo Trading futures ... listenKey" | no official Demo statement found | whether Demo serves listenKey and user-data, and at which WS URL, is NOT documented in anything read | n/a |

**UNVERIFIED (consolidated, see also the Assumptions Log):** the `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE` and `listenKeyExpired` payload pages themselves (B5); the `SUBSCRIBE` parameter format and the event envelope on `/private`; whether `events=` is mandatory; whether Demo serves the user-data stream and at what URL; the REST `algoStatus` enumeration; a new-connection rate limit; the maximum recvWindow on endpoints other than algoOrder and positionSide/dual; the ordering of `ACCOUNT_UPDATE` versus `ORDER_TRADE_UPDATE`; whether `Retry-After` is sent by Binance at all.

## Architectural Responsibility Map

| Capability | Primary tier | Secondary tier | Rationale |
|------------|-------------|----------------|-----------|
| Authoritative order, algo order, position, balance state | Binance (REST snapshots) | Reconciler (Phase 20) | AGENTS.md exchange authority; D-05: the stream is a hint plus evidence |
| listenKey start, keepalive, close, event socket (`/private`) | Adapter (`src/adapters`, SDK-touching) | Supervisor coroutine in the same package | D-01 to D-03: SDK models never leave the adapter |
| Event parsing into frozen Decimal/UTC dataclasses | Pure SDK-free module (dict in, dataclass out) | Adapter (unwraps SDK model to dict) | One parser for the SDK-model path and the raw-dict fallback path (pitfall P4) |
| Exchange error classification by `(error class, int code)` | Pure module `src/domain` (no SDK) | Adapter normalizer (SDK exception to facts) | D-09/D-10; execution and reconcile import only the pure part |
| ALGO_UPDATE status classification table | Pure module `src/domain` | `src/execution/manager.py` consumer | Replaces `_ACTIVE_ALGO_STATUSES` (manager.py:1036) without an SDK import in execution |
| Environment selection, host table, mainnet-host guard, key loading | Adapter-side config module | Operator scripts reuse it | D-12/D-13; generalizes `assert_demo_sdk_client` |
| Server-time drift decision | Pure function (injected clock and measurement) | Adapter supplies `server_time` | D-22: no wall clock in pure code |
| Stream anomaly and evidence-source records | Append-only journal (`PgJournalStore`) | Order/intent stores (G4-043 methods) | D-08: existing journal, no new table |
| Demo probe and live smoke | Operator scripts under `scripts/` (connected machine) | Fake-driven rig for dry-run | D-04, D-15, D-18 |

## Standard Stack

No new runtime dependency is needed. Everything below is already pinned in `uv.lock` [VERIFIED: pyproject.toml `dependencies` block and uv.lock `name = "binance-sdk-derivatives-trading-usds-futures"` / `version = "17.4.0"`, `name = "binance-common"` / `version = "4.4.0"`].

### Core
| Library | Version | Purpose | Why standard |
|---------|---------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 (lock) | listenKey REST calls; `/private` socket via `websocket_streams.user_data` | Project-mandated official SDK (AGENTS.md); only module `binance_usdm.py`/`paper_ws.py` style adapters may import it |
| `binance-common` | 4.4.0 (lock, transitive) | error classes, `send_request`, websocket plumbing, constants | Imported already by `paper_ws.py` and `demo_rehearsal.py` |
| `tenacity` | >=9 (lock 9.1.4 per AGENTS.md) | bounded reconnect and read/cancel retry | Pinned; precedent in `binance_usdm.py` and `src/paper/supervisor.py` |
| `structlog` | >=25 | decision-lineage logs | Pinned; `src/ops/redaction.py` processors already apply |
| `pytest`, `pytest-asyncio` (auto mode), `respx` (not needed here), `ruff`, `mypy` | per lock | tests and gates | Project conventions (AGENTS.md) |

### Conditional (only if the SDK `/private` route fails the live smoke)
| Library | Version | Purpose | When |
|---------|---------|---------|------|
| `aiohttp` | 3.14.3 already locked as a dependency of `binance-common` [VERIFIED: uv.lock lines 15-17 `name = "aiohttp"`, `version = "3.14.3"`] | direct WebSocket client on the documented URL form `.../private/ws?listenKey=...&events=...` | Importing a transitive dependency directly requires declaring it in `pyproject.toml` (`aiohttp>=3.14,<4`) and `uv lock` in the same change; the planner makes this a gated task, not a default |

### Alternatives considered
| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| SDK `user_data` route | direct `aiohttp` on the documented URL | Direct route matches the one URL form the docs show but re-implements ping/pong, rotation and reconnect that the SDK already owns; keep as fallback (D-02) |
| WS-API `userDataStream.start/ping/stop` for listenKey | REST `start/keepalive/close_user_data_stream` | WS-API needs a second SDK client and connection; REST is already the adapter's style (`asyncio.to_thread`); recommend REST |
| tenacity for gap-snapshot retry | hand loops | tenacity is pinned and used in the same files; do not hand-roll |

**Installation:** none. `uv lock --check` must stay green.

## Package Legitimacy Audit

No package is added by this phase, so no `package-legitimacy check` run is required. `aiohttp` is already resolved in the lockfile as a dependency of `binance-common` (see above); promoting it to a direct dependency is a conditional, gated change.

| Package | Registry | Age | Downloads | Source repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none new) | - | - | - | - | - | - |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Findings

### F1. User-data stream mechanism and the SDK surface (research question 1)

1. **listenKey is still required** [CITED: B1, B2, B3]. One REST key per account: `POST /fapi/v1/listenKey` returns the existing active key and extends it 60 minutes; `PUT` extends; `DELETE` closes. The calls take no `listenKey` parameter (confirmed by the SDK signatures below), so the key is effectively a per-account singleton: a `DELETE` issued by the smoke or probe closes the stream of any supervisor using the same account (pitfall P7; the singleton reading is an inference from the "returns that key" sentence [ASSUMED]).
2. **Events travel on `/private`** [CITED: B3, B4]. Documented URL form: `wss://fstream.binance.com/private/ws?listenKey=<k>&events=<EVENT1>/<EVENT2>` (and `/private/stream?...`). JSON `SUBSCRIBE` is "also supported" for listenKey items; the parameter format is not documented in anything read (B3, B12). The `events=` list suggests the server filters by event name; whether omitting it delivers all events is UNVERIFIED.
3. **24-hour cap** [CITED: B4]: "A single connection is only valid for 24 hours; expect to be disconnected at the 24 hour mark." The listenKey lifetime (60 minutes, keepalive-extended) is independent of the connection lifetime.
4. **What the installed SDK offers** [VERIFIED: files read this session]:
   - REST (sync, `requests`): `DerivativesTradingUsdsFutures.rest_api.start_user_data_stream()`, `.keepalive_user_data_stream()`, `.close_user_data_stream()` (`rest_api/api/user_data_streams_api.py`, paths `POST/PUT/DELETE /fapi/v1/listenKey`; responses `StartUserDataStreamResponse` / `KeepaliveUserDataStreamResponse` with `listen_key` alias `listenKey`). Security type USER_STREAM: API key header, no signature.
   - WS API (async): `websocket_api/api/user_data_streams_api.py` exposes `start_user_data_stream`, `keepalive_user_data_stream`, `close_user_data_stream` as `/userDataStream.start`, `.ping`, `.stop`. There is no `userDataStream.subscribe`; the Spot-style session subscription does not exist for futures in this SDK.
   - Streams client: `DerivativesTradingUsdsFuturesWebSocketStreams.user_data(self, listenKey: str) -> RequestStreamHandle` (`websocket_streams/websocket_streams.py`, verbatim: `return await RequestStream(self, listenKey, response_model=UserDataStreamEventsResponse, stream_url="private")`). `RequestStream` calls `WebSocketStreamBase.subscribe(streams=[listenKey], response_model=..., stream_url="private")`, which sends `{"method": "SUBSCRIBE", "params": [listenKey], "id": <uuid string>}` on the `/private` connection and maps the listenKey into the module-global `global_stream_connections`. The handle exposes only `on("message", cb)` and `unsubscribe()`.
   - **Answer for D-02:** the SDK offers listenKey over REST or over the WS API, and event delivery only through `user_data(listenKey)` on the streams client. It does not offer a documented-URL-form connection (`?listenKey=&events=`). That form is the "gap" that a direct `aiohttp` transport would cover, only if the smoke shows the SUBSCRIBE route does not deliver.
5. **Connection plumbing facts** [VERIFIED: `binance_common/websocket.py`, `constants.py` read this session]:
   - `WebSocketStreamBase.__init__` appends `/stream` to `stream_url`; `init_connection` rewrites `/stream` to `/<url_path>/stream`, so the private socket is `<stream_url>/private/stream`. The streams client is built with `url_paths=["market", "public", "private"]` (always three sockets; the Phase 16 live smoke recorded `connection_count` 3 with `private_established: true`, `.planning/phases/16-paper-runtime-composition/evidence/16-21-ws-smoke-live.json`). A user-data-only client can instead call the public `connect(url, configuration, url_paths=["private"])` to open one socket (needs a contract test).
   - Rotation: `AUTO_RECONNECT_INTERVAL_SECONDS = 23 * 3600` (`binance_common/constants.py:16`, verbatim), applied per connection by `schedule_reconnect`; `reconnect()` closes the old socket, opens a replacement under the same connection id, emits `reconnect` then `open`, and re-sends `SUBSCRIBE` for every stream still mapped to the old connection (`_resubscribe_global_streams`). Events that occur between the old close and the new subscribe are lost (no replay is documented).
   - Reconnect defaults: `reconnect_delay=5000` ms, `reconnect_attempts=3`, allowed 1 to 10 (`ConfigurationWebSocketStreams`). After a failed reconnect the SDK emits `error` then `close` and calls `_forget_connection_streams`.
   - An unsolicited CLOSE/ERROR frame calls `_emit_close_event` and `_discard_connection` and ends the receive loop WITHOUT forgetting the stream names; a plain re-subscribe of the same name is then skipped by `subscribe` (it filters names already in the global map). `PaperWsAdapter._forget_own_streams` (`src/adapters/paper_ws.py:410-424`) is the existing remedy and must be copied for the listenKey name.
   - Callbacks run synchronously inside the SDK receive loop on the event-loop thread. A callback exception is caught, logged, and emitted as a connection `error` event (pitfall P5).
   - Event routing: `parse_user_event(payload, UserDataStreamEventsResponse)` resolves the model by `normalize_event_name(e)` (underscores and hyphens removed, lower-cased) against the class names `AccountConfigUpdate, AccountUpdate, AlgoUpdate, ConditionalOrderTriggerReject, GridUpdate, ListenKeyExpired, MarginCall, OrderTradeUpdate, StrategyUpdate, TradeLite`. On an unknown event name or a validation failure it logs a warning and returns `response_model.model_construct(actual_instance=<raw payload dict>)`.
6. **Reference precedent:** `src/adapters/paper_ws.py` (adapter with injected `ws_client`, `client_factory`, `on_connection`, `rebuild`, `_forget_own_streams`, `install_sdk_log_bridge`), `src/paper/supervisor.py` (bounded rebuild, `SUPERVISOR_MAX_ATTEMPTS: int = 7`, `SUPERVISOR_MAX_DELAY_SECONDS: int = 120`, `SUPERVISOR_WAIT_MULTIPLIER_SECONDS: int = 1`, `SUPERVISOR_WAIT_MAX_SECONDS: int = 60`, `_DROP_EVENTS = frozenset({"close", "error"})` at lines 63-69), `tests/paper_ws_fakes.py` and `tests/test_paper_ws_contract.py` (mirror-the-SDK fakes plus introspection tests; `fresh_sdk_stream_map(monkeypatch)` isolates the SDK module-global map).

### F2. Event schemas and the mapping to project types (research question 2)

SDK 17.4.0 models are the only field-level source this session (B5 unreadable). All fields are `Optional`, strings for money, ints for ids and times [VERIFIED: `websocket_streams/models/order_trade_update_o.py`, `algo_update_o.py`, `account_update*.py`, `listen_key_expired.py`, `margin_call*.py`, `trade_lite.py` read this session]. `E` event time, `T` transaction time (ms ints).

**ORDER_TRADE_UPDATE** (`OrderTradeUpdate{E, T, o}`; `o` = `OrderTradeUpdateO`): `s` symbol, `c` client order id, `S` side, `o` order type, `f` time in force, `q` original quantity, `p` original price, `ap` average price, `sp` stop price, `x` execution type, `X` order status, `i` order id (int), `M` modifyId (only with AMENDMENT), `l` last filled quantity, `z` accumulated filled quantity, `L` last filled price, `N` commission asset, `n` commission, `T` order trade time (int), `t` trade id (int), `b`/`a` bids/ask notional, `m` maker flag, `R` reduce only, `wt` stop-price working type, `ot` original order type, `ps` position side, `cp` close-all (conditional), `AP`/`cr` trailing only, `pP` price protect, `si`/`ss` "ignore", `rp` realized profit of the trade, `V` STP mode, `pm` price match, `gtd`, `er` expiry reason.

| Event field | Project target | Notes |
|---|---|---|
| `o.i` (int) | `FillEvent.order_id = str(i)` (exchange order id string) | existing usage: `scripts/demo_rehearsal.py` builds `order_id = probe.order_id` (exchange id string) |
| `o.t` (int) | `FillEvent.exchange_trade_id = str(t)` | only for `x == "TRADE"`; NEW/CANCELED/EXPIRED events carry no usable trade id (UNVERIFIED which value); never synthesize one |
| `o.s`, `o.S`, `o.ps` | `symbol`, `side`, `position_side` | `ps` is BOTH in one-way mode, LONG/SHORT in hedge mode; `fold_fills` rejects sides outside BUY/SELL |
| `o.L`, `o.l` | `fill_price`, `fill_quantity` as `Decimal(str)` | reject non-string, non-finite, `l <= 0` on a TRADE |
| `o.T` | `fill_time_utc` via ms to UTC | |
| `o.n`, `o.N`, `o.rp`, `o.m` | commission, commission asset, realized PnL, is_maker | `FillEvent` has no such fields today [VERIFIED: `src/execution/fill_monitor.py:63-90` fields are order_id, exchange_trade_id, symbol, side, position_side, fill_price, fill_quantity, fill_time_utc]; domain `Fill` already has `commission`, `commission_asset`, `realized_pnl`, `is_maker`, `quote_quantity` [VERIFIED: `src/domain/fill.py` class `Fill`]. G3-009: add optional defaulted fields to `FillEvent` and carry them through the `fold_fills` fill dict |
| `o.z` | integrity check, not a fill | per order, `z` must equal the sum of unique `l`; a mismatch means a missed TRADE event: raise a stream anomaly and read `GET userTrades` via `account_trade_list` (the REST key space equals the stream's `t`) |
| `o.c` | client order id for routing | forced-close ids start `autoclose-`, `adl_autoclose`, `settlement_autoclose-` [CITED: B5b]: not ours, surface as divergence |
| `o.x == "AMENDMENT"` + `M` | status-only event | added 2026-07-30 [CITED: B6]; the project never amends orders, so treat as anomaly |
| `o.X == "EXPIRED_IN_MATCH"` | terminal, not filled | self-trade prevention [CITED: B5b] |

**Identity trap for algo-triggered exits.** `ALGO_UPDATE.o` carries `caid` (client algo id), `aid` (algo id), `ai` ("Order Id" of the matching-engine order once triggered), `ap`/`aq` (average price / executed quantity in the matching engine, "only display when order is triggered") and `act` (actual order type). REST names the same data `actualOrderId`, `actualPrice`, `actualQty`, `actualType` [CITED: B10]. What `c` and `i` the child `ORDER_TRADE_UPDATE` carries (does `c` equal `caid`, a derived string, or random) is UNVERIFIED and decides how a protective-leg fill is attributed. This is a probe capture target (F6).

**ALGO_UPDATE** (`AlgoUpdate{T, E, o}`; `o` = `AlgoUpdateO`) [VERIFIED: `algo_update_o.py`]: `caid`, `aid` (int), `at` algo type, `o` order type, `s`, `S`, `ps`, `f`, `q`, `X` algo status, `ai`, `ap`, `aq`, `act`, `tp` trigger price, `p`, `V`, `wt`, `pm`, `cp`, `pP`, `R`, `tt` trigger time, `gtd`, `rm` failed reason (free text; example "Reduce Only reject" [CITED: B5a]), `ia` ("only meaningful for trailing order"; "now fully active" since 2026-08-21 [CITED: B6]). The SDK model has no `e` property: `AlgoUpdate.__properties = ["T", "E", "o"]`, so the event name only survives as the wrapper's `actual_instance` class. `rm` is human text: it is logged and journaled as a diagnostic and never decides anything (D-10 spirit).

**ACCOUNT_UPDATE** (`AccountUpdate{E, T, a}`; `a` = `m` reason, `B[]` {`a` asset, `wb` wallet balance, `cw` cross wallet balance, `bc` balance change}, `P[]` {`s`, `pa` position amount, `ep` entry price, `bep` breakeven price, `cr` accumulated realized, `up` unrealized PnL, `mt` margin type, `iw` isolated wallet, `ps`}, `S` symbol only for FUNDING_FEE) [VERIFIED: `account_update*.py`; `S` per B6]. `pa` is signed. D-08: parse into delta events only.

**Other events present in the SDK union:** `ListenKeyExpired{E, listenKey}` (event string spelled `listenKeyExpired` is [ASSUMED]; the SDK matches it case-insensitively), `MarginCall{E, cw, p[]}` (Phase 22), `AccountConfigUpdate{E, T, ac{s, l leverage}, ai{j multi-assets}}` (relevant to position-mode and leverage drift; parse and journal as hint), `TradeLite` (duplicates fills with `i`,`t`; ignore with a counter so there is a single fill source), `StrategyUpdate`/`GridUpdate` (not used by the project: count and ignore), `ConditionalOrderTriggerReject` (deprecated 2025-12-15 [CITED: B6]; if it ever arrives treat as an anomaly).

**SDK typing hazard (pitfall P4).** The models use `StrictStr`/`StrictInt`; any type surprise sends the frame down the raw-dict branch; unknown fields are silently dropped by `model_validate` (only `from_dict` keeps `additional_properties`). The parser therefore takes a plain dict, produced from the model by `to_dict()` (alias keys, None excluded) or taken as is when `actual_instance` is a dict, and validates every field itself.

### F3. ALGO_UPDATE status table (research question 3; G3-001, G2-028)

Sources: B5a (search summary 2026-10-15) agrees with the Wayback snapshot 2026-01-13 transcribed in `.planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md` Fact 2. The event page itself is UNVERIFIED (B5), so G3-001 is only partly closed: status list MEDIUM (two independent summaries agree), live page not read.

| `X` value | Documented meaning (paraphrased from B5a and 09-EXCHANGE-FACTS Fact 2) | Proposed D-07 class | Counts as "protection confirmed"? | Judgment flag |
|---|---|---|---|---|
| NEW | placed in the Algo Service, not yet triggered | ACTIVE | yes | none |
| TRIGGERING | condition met, forwarded to the matching engine | UNKNOWN (reason `IN_FLIGHT`) | no | **judgment**: in transit, neither confirmed nor failed; a fifth class `IN_FLIGHT` is the cleaner alternative to overloading UNKNOWN |
| TRIGGERED | placed in the matching engine | UNKNOWN (reason `IN_FLIGHT`) | no | same |
| FINISHED | the triggered order was filled or canceled in the matching engine | TERMINAL_OK | no (EXECUTION_SPEC 6.1: FINISHED does not mean filled; position must be read from the exchange) | **judgment**: lifecycle-complete, not "protection executed" |
| CANCELED | the conditional order was canceled | TERMINAL_OK | no | **judgment**: OK when the project canceled it, failure when it did not; origin is not in the event, so the reconciler's position-based check stays the arbiter |
| REJECTED | denied by the matching engine (e.g. margin check failure) | TERMINAL_FAILED | no | none |
| EXPIRED | canceled by the system (e.g. a GTE_GTC conditional order after all positions closed) | TERMINAL_FAILED | no | none |
| anything else, `""`, `None` | unseen | UNKNOWN | no | fail closed (D-07) |

The two consumers to change are exactly `_is_leg_confirmed` and the existing-leg adoption branch in `src/execution/manager.py` (`status in _ACTIVE_ALGO_STATUSES`, lines 1058 and 1096). `intent_recovery.py` reads `algo_status` only as a string for the intent record. Open facts: the REST `algoStatus` vocabulary is not enumerated on the REST pages (B10); equality with the WS `X` vocabulary is [ASSUMED] and is a probe capture. EXECUTION_SPEC 6.1 lists five statuses and omits CANCELED; section 6.1 also says "two NEW events can arrive (ia false, then true)" for trailing stops, which still holds. The Phase 18 doc task updates section 6.1 and BINANCE.md accordingly (D-20). Because "protection confirmed" is safety policy (D061 item H), the table above is a recommendation with the three flagged rows put to the user at the first checkpoint.

### F4. Error taxonomy inputs (research question 4)

**Documented codes** (error-code page, B7, WebFetch 2026-10-15; text quoted from the tool):

| Code | Name | Message / note | Needed for |
|---|---|---|---|
| -1003 | TOO_MANY_REQUESTS | "Too many requests; current limit is %s requests per minute." and "Way too many requests; IP banned until %s. ..." (same code for 429 and 418) | D-09 rate limit / ban |
| -1006 | UNEXPECTED_RESP | "... Execution status unknown." | placement ambiguity |
| -1007 | TIMEOUT | "Timeout waiting for response from backend server. Send status unknown; execution status unknown." | placement ambiguity |
| -1008 | Request Throttled | "Request throttled by system-level protection. Reduce-only/close-position orders are exempt." | transient, definite failure per B8 |
| -1015 | TOO_MANY_ORDERS | "Too many new orders; current limit is %s orders per %s." | order-rate limit |
| -1021 | INVALID_TIMESTAMP | "Timestamp for this request is outside of the recvWindow." / "... was 1000ms ahead of the server's time." | D-14 |
| -1022 | INVALID_SIGNATURE | "Signature for this request is not valid." | D-09 optional (docs list it) |
| -1125 | INVALID_LISTEN_KEY | "This listenKey does not exist. Please use `POST /fapi/v1/listenKey` to recreate `listenKey`" | listenKey expiry (association with PUT is [ASSUMED]; B2 lists no errors) |
| -2010 | NEW_ORDER_REJECTED | "NEW_ORDER_REJECTED" | placement rejection |
| -2011 | CANCEL_REJECTED | "Cancel request failure as open order not found in the orderbook: "Unknown order sent"." | cancel path absence |
| -2013 | NO_SUCH_ORDER | "Order does not exist." (Demo-observed for GET algoOrder 2026-10-05, 09-DEMO-REHEARSAL-FINDINGS finding 1) | query path absence |
| -2014 / -2015 / -2017 | BAD_API_KEY_FMT / REJECTED_MBX_KEY / API_KEYS_LOCKED | "API-key format invalid." / "Invalid API-key, IP, or permissions for action." / "API Keys are locked on this account." | auth |
| -2018 / -2019 | BALANCE_NOT_SUFFICIENT / margin insufficient (printed `MARGIN_NOT_SUFFICIEN`) | "Balance is insufficient." / "Margin is insufficient." | definite reject |
| -2021 | ORDER_WOULD_IMMEDIATELY_TRIGGER | "Order would immediately trigger." (documented in the New Algo Order section for TRAILING_STOP_MARKET; the error page lists it generally) | definite reject |
| -2022 | REDUCE_ONLY_REJECT | "ReduceOnly Order is rejected." ("conflicts with existing open orders") | D055 probe outcome |
| -2024 / -2026 | POSITION_NOT_SUFFICIENT / REDUCE_ONLY_ORDER_TYPE_NOT_SUPPORTED | "Position is not sufficient." / "This OrderType is not supported when reduceOnly." | D055 probe outcomes |
| -4003, -4004, -4005, -4014, -1111 | QTY_LESS_THAN_ZERO, QTY_LESS_THAN_MIN_QTY, QTY_GREATER_THAN_MAX_QTY, price tick, BAD_PRECISION | filter rejections | definite reject |
| -4067 / -4068 | position side change with open orders / with position | "Position side cannot be changed if there exists open orders." / "... position." | position-mode checks |
| -4116 | DUPLICATED_CLIENT_ORDER_ID | "clientOrderId is duplicated" | dedup; algo-id variant unknown |
| -4120 | STOP_ORDER_SWITCH_ALGO | "Order type not supported for this endpoint. Please use the Algo Order API endpoints instead." | wrong endpoint for conditional types |
| -4137 / -4138 | QUANTITY_EXISTS_WITH_CLOSE_POSITION / REDUCE_ONLY_MUST_BE_TRUE | "Quantity must be zero with closePosition equals true" / "Reduce only must be true with closePosition equals true" | note: -4138 text conflicts with the New Algo Order page (09-EXCHANGE-FACTS Fact 3) |
| -4142 | STRATEGY_INVALID_TRIGGER_PRICE | "REJECT: take profit or stop order will be triggered immediately" | would-trigger reject |
| -4164 | MIN_NOTIONAL | "Order's notional must be no smaller than %s (unless you choose reduce only)" | G2-029 |
| -4400, -4401 | quantitative rules / large position | "only reduceOnly order is allowed" | account restriction |
| **-4509** | (not on the page) | `Time in Force (TIF) GTE can only be used with open positions.` | **demo-observed only** (09-DEMO-REHEARSAL-FINDINGS finding 2); the error page summary lists no -4509 |

HTTP-level facts [CITED: B8]: 429 = rate limit exceeded; 418 = IP auto-banned after continuing past 429, ban "from 2 minutes to 3 days"; 403 = WAF limit; 408 = backend timeout; 5XX = Binance-side; the 503 variants: "Unknown error, please check your request or try again later." = the request was accepted but timed out, execution may have succeeded, "Don't treat it as a failure. Verify through WebSocket updates or orderId queries"; "Service Unavailable." = definite failure, retry with exponential backoff, not counted toward rate limits; "Internal error; unable to process your request. Please try again." = definite failure, can resend; -1008 = definite failure, retry with backoff.

**How the SDK surfaces them** [VERIFIED: `binance_common/utils.py` `send_request` lines 461-505 and `binance_common/errors.py` read this session]:

| HTTP status | Exception class | `status_code` attribute | Other |
|---|---|---|---|
| 400 | `BadRequestError` | Binance JSON `code` (e.g. -2013), or None if the body is not JSON | `error_message` = body `msg` |
| 401 | `UnauthorizedError` | body `code` | |
| 403 | `ForbiddenError` | body `code` | |
| 404 | `NotFoundError` | body `code` | |
| 418 | `RateLimitBanError` | body `code` (not 418) | `retry_after` from the `Retry-After` header, int or None |
| 429 | `TooManyRequestsError` | body `code` (not 429) | `retry_after` as above |
| 500-599 | `ServerError` | the HTTP status (503), body discarded | message fixed to `f"Server error: {status}"` |
| other 4xx (e.g. 408) | `ClientError` | **None** (constructed with `error_message` only) | |
| connect / read timeout / any `requests.RequestException` | `NetworkError` | no attribute | message `f"Network error: {str(e)}"` may embed the request URL including `signature=` |

Consequences: (a) "418/429 by int" in D-09 is only implementable by class; the pure taxonomy input must be `(http_class, code, retry_after)`; (b) `-1003` cannot separate throttle from ban; (c) 5xx, 408 and `NetworkError` on a placement path are "status unknown" (the fail-closed reading of the 503 sentence above); (d) the existing `is_rate_limit_ban_error` already uses `isinstance(exc, RateLimitBanError)` and `rate_limit_retry_after_seconds` rejects bool and negative values [VERIFIED: `src/adapters/binance_usdm.py:436-465`]; (e) the SDK retries inside `send_request` only on `requests.RequestException` for GET and DELETE (`should_retry_request`: `retriable_methods = ["GET", "DELETE"]`), never POST/PUT, with `time.sleep(backoff * attempt)` blocking the worker thread, default `retries=3`, `backoff=1000`, `timeout=1000` ms (`ConfigurationRestAPI` defaults).

**Existing helpers to replace or fold** [VERIFIED: `src/adapters/binance_usdm.py`]: line 160 `_NOT_FOUND_CODES: frozenset[int] = frozenset({-2013, -2011})`; line 161 `_NOT_FOUND_MESSAGE = re.compile(r"(?<!\d)-(?:2013|2011)(?!\d)")`; `_is_order_not_found_error` (message fallback when no int code); `_cancel_retry_predicate` (retries every exception except a message match and ValueError/KeyError/TypeError, so it also retries definitive rejections such as -2019); `_is_already_canceled_message` (`"UNKNOWN_ORDER" in message or "-2011" in message`); lines 125-128 `_RECONCILER_CANCEL_MAX_ATTEMPTS: int = 3`, `_RECONCILER_CANCEL_MAX_DELAY_SECONDS: int = 30`, `_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS: int = 1`, `_RECONCILER_CANCEL_WAIT_MAX_SECONDS: int = 10`. `is_invalid_symbol_error` (code -1121, line 472 `INVALID_SYMBOL_CODE: int = -1121`) and the rate-limit trio are used by `src/data/backfill.py` and `src/data/universe_freeze.py` and must keep their import names. `tests/test_adapter_not_found_mapping.py` pins the current not-found behavior including a "legacy message form still maps" test (`RuntimeError("-2011 UNKNOWN_ORDER")`) that D-10 deliberately reverses; that test must be rewritten, not deleted silently.

**Recommended category set** (descriptive; the planner owns names): ORDER_ABSENT (-2013 on query, -2011 on cancel), DUPLICATE_CLIENT_ID (-4116; algo duplicate code unknown, hence probe), REJECTED_DEFINITIVE (margin -2019, balance -2018, notional -4164, filters, would-trigger -2021/-4142, reduce-only -2022/-2024/-2026), PRECONDITION_NO_POSITION (-4509, demo-observed), CLOCK_SKEW (-1021, triggers a drift re-measure, never an order retry), AUTH_OR_SIGNATURE (-1022, -2014, -2015, -2017, 401/403 classes, never retried), RATE_LIMITED (class 429 and code -1003/-1015/-1008, honor `retry_after`), IP_BANNED (class 418, no retry), STATUS_UNKNOWN (-1006, -1007, 5xx, 408, `NetworkError`, `ClientError` without code), INVALID_LISTEN_KEY (-1125), POSITION_MODE (-4067, -4068, -4531), UNKNOWN_EXCHANGE_ERROR (everything else; ambiguous, no placement retry, SAFE_MODE-eligible).

### F5. Environments and client configuration (research question 5)

**Hosts.** SDK constants [VERIFIED: `binance_common/constants.py` read this session]: `DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL = "https://fapi.binance.com"`, `DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL = ("https://testnet.binancefuture.com")`, `DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL = "https://demo-fapi.binance.com"`, `DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL = "wss://fstream.binance.com"`, `DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_TESTNET_URL = ("wss://fstream.binancefuture.com")`. **There is no Demo WebSocket constant in the SDK.** The documentation read today calls `https://demo-fapi.binance.com` "Testnet REST" and `wss://demo-fstream.binance.com` "Testnet WebSocket" (B8), while the Keepalive page lists `https://testnet.binancefuture.com` as the testnet base (B2) and the Phase 9 snapshot of general-info gave the WS base as `wss://fstream.binancefuture.com` (09-EXCHANGE-FACTS Addendum A). The words DEMO and TESTNET are therefore ambiguous across sources. **Open decision for O-18-04 (not decided here):** what the enum value `TESTNET` denotes (legacy `testnet.binancefuture.com`, which this project has never used, versus a synonym of Demo), or whether to drop it until the owner has a testnet account. The Demo WS URL (`wss://demo-fstream.binance.com`) is a single-source MEDIUM fact and is a smoke prerequisite to confirm. Whether Demo serves `POST /fapi/v1/listenKey` and a user-data socket is UNVERIFIED (B13).

**Mixed-environment trap.** `DerivativesTradingUsdsFutures.__init__` takes three independent configurations; the `websocket_streams` property fills `stream_url` with the PROD URL when `config_ws_streams` is omitted [VERIFIED: `derivatives_trading_usds_futures.py`, property `websocket_streams`], and the `rest_api` property mutates `base_path` to PROD when None. The existing `build_demo_sdk_client` passes only `config_rest_api`, and `assert_demo_sdk_client` re-reads only `client.rest_api.configuration.base_path`. A user-data client built next to it would silently target mainnet WebSocket with a Demo REST key. The guard generalization (D-12) must assert REST base path AND the streams `stream_url` (after property access) AND, if used, the WS-API URL, per environment, before any call, and the construction must be funneled through one function (the AST test in `tests/test_demo_rehearsal_safety.py::test_runner_source_has_no_prod_host_or_default_client_construction` asserts `visitor.sdk_constructions == ["build_demo_sdk_client"]`; the rehearsal keeps that function name as a thin wrapper or the test is updated deliberately).

**Credentials.** Variable names already documented [VERIFIED: `scripts/demo_rehearsal.py:167-168`, verbatim] `ENV_BINANCE_KEY = "BINANCE_TESTNET_API_KEY"`, `ENV_BINANCE_SECRET = "BINANCE_TESTNET_API_SECRET"  # noqa: S105 - a variable NAME, not a secret`; `.env.example` reserves `BINANCE_LIVE_API_KEY` and `BINANCE_LIVE_API_SECRET` (Phase 24). SECURITY_AND_OPERATIONS keeps paper/test and live names different (OPS-06). Demo and legacy-testnet keys both fall under the TESTNET names today; whether Demo gets its own names is a small owner/planner choice. Binance changelog 2025-11-12 says keys for the Options Demo environment are created on the demo site [CITED: B6]; the futures Demo key provisioning is not documented in anything read [ASSUMED same].
Redaction gaps [VERIFIED: `src/ops/redaction.py` read this session]: `Redactor.from_environ` collects only environment values whose NAME contains `PASSWORD, SECRET, TOKEN, API_KEY, ACCESS_KEY, CRYPT, PRIVATE`; (1) a key loaded from a FILE (D-13) is invisible to it, so the loader must register the value with the active redactor (new API; the `_active` object is a frozen dataclass compiled once); (2) a listenKey (runtime value, 64 characters in the doc example) has no shape rule and is not in the environment, yet the SDK logs it (pitfall P3). The shape rules already cover `signature=<64 hex>` and `X-MBX-APIKEY`.

**Timeouts, retries, recvWindow, clock** [VERIFIED: `binance_common/configuration.py`, `utils.py`]: `ConfigurationRestAPI(api_key, api_secret, base_path, timeout=1000, proxy, keep_alive=True, compression=True, retries=3, backoff=1000, ...)`; `timeout` is milliseconds and is passed to `requests` as one number (connect and read together); no `recv_window` field exists: it is a per-method argument (`recv_window: Optional[int] = None`) on every signed method, and the project passes none today [VERIFIED: grep of `src` and `scripts` for `recv_window` finds only docstring text in `binance_usdm.py`]. The signed timestamp is `get_timestamp()` = `int(time.time() * 1000)` from the host clock. Docs (B8): default recvWindow 5000 ms, acceptance rule `timestamp < serverTime + 1000 && serverTime - timestamp <= recvWindow`, so a host clock AHEAD of Binance by more than 1000 ms is rejected regardless of recvWindow, while a host clock BEHIND is tolerated up to recvWindow; maximum 60000 is documented only on the New Algo Order and Change Position Mode parameter tables (B9, B11). Server time: `GET /fapi/v1/time` (`rest_api.check_server_time`, weight 1, unsigned); the project wrapper is `BinancePublicMarketData.server_time` (`asyncio.to_thread(self._sdk.rest_api.check_server_time)`).
Precedents for the drift measurement: `src/data/collector.py:102` `CLOCK_OFFSET_WARN_MS = 1000` (warn-only; its docstring assigns the fail-closed version to Phase 18); `src/paper/market_inputs.py` `measure_clock_skew` (midpoint of two injected-clock reads around one `server_time` call; Phase 18 must not import from `src/paper`). Phase 16 live smoke observation (not a threshold): host clock BEHIND Binance by 182 ms at start to 580 ms at the end including request latency (`16-O-07-table.md`, "Smoke caveat").

**Honoring 418/429.** The SDK parses `Retry-After` (`parse_retry_after`: int seconds, else None). Binance docs (B8) do not mention a `Retry-After` header [CITED: "The page does not mention a Retry-After header"], so whether it is sent is UNVERIFIED; the config layer must define the behavior when `retry_after is None` (a wait the owner sets; fail closed, entries blocked, no retry) and a cap for an absurd value.

### F6. Probe design inputs (research question 6)

Reusable pattern from `scripts/demo_rehearsal.py` [VERIFIED: lines 1-360, 396-533, 851-897 read]: host constants (`DEMO_HOST = "demo-fapi.binance.com"`, `SDK_TIMEOUT_MS = 10000`), `assert_demo_base_url` (exact scheme/host/no port/no userinfo/no query/path in ("", "/")), `load_credentials(environ)` that names the variable only in errors, `RehearsalCredentials` with `repr=False` secret fields, `EVIDENCE_SCHEMA = "demo-rehearsal-evidence/schema-1"`, `EvidenceRecorder` (atomic temp-file write, `Redactor.from_environ(...)` scrub before and re-check after write, LF-only, `sort_keys`), `GuardedAdapter` (explicit method list, no `__getattr__` passthrough, DRY_RUN never reaches a mutating method), exit codes 0/1/2/3, `required_phrase(scenario)` = `f"DEMO {scenario.upper()} {SYMBOL}"`, `_confirm_execute(is_tty, read_confirmation)` (interactive TTY plus exact phrase, else exit 2 before any network call). The new probe should reuse these by importing a shared module, not by copying.

| D055 / D-16 case | What the docs say | Candidate outcomes to record (hypotheses, not facts) | Frames to capture |
|---|---|---|---|
| not-found codes: GET order, GET algoOrder | -2013 documented; -2011 documented for cancel; Demo-observed -2013 for GET algoOrder | confirm -2013 for GET order on Demo (never observed) | none (REST) |
| duplicate `clientAlgoId` | -4116 only for `clientOrderId`; algo variant undocumented (SOURCES.md Phase 17) | -4116, another code, or accepted | REST error body code via `status_code` |
| id reuse after FILLED / CANCELED | "A unique id among open orders" (SOURCES.md rows) | second order accepted (fake's assumption) or rejected | ORDER_TRADE_UPDATE for both |
| STOP_MARKET + explicit `quantity` + `reduceOnly` with no position | `reduceOnly` cannot combine with `closePosition`; `-2022 REDUCE_ONLY_REJECT`; `-4509` seen for closePosition | accepted (stays NEW), -2022, -2024, -4509, -4164 | ALGO_UPDATE NEW or REJECTED with `rm`; REST algoStatus |
| entry never fills, then cancel | n/a | is the pre-placed protective orphaned; does `cancel_algo_order` clean it; any system EXPIRED event ("canceled by the system" example refers to a GTE_GTC order after positions closed) | ALGO_UPDATE status sequence, ORDER_TRADE_UPDATE x=CANCELED |
| full fill | n/a | does the pre-placed explicit-quantity reduce-only leg protect exactly the filled quantity | ORDER_TRADE_UPDATE x=TRADE (`i`,`t`,`l`,`L`,`n`,`N`,`rp`,`m`,`ps`), ACCOUNT_UPDATE m=ORDER, ordering between the two |
| partial fill | n/a | **may not be inducible on Demo** (a deep BTCUSDT book fills a marketable limit completely; self-trade prevention blocks a self-fill); the plan should allow `NOT_OBSERVED` with the reason and rely on `z` versus sum of `l` tests with synthetic frames | `z` and `l` progression |
| rejected protective order | -4509 observed with closePosition=true | record the exact `(class, code, message)` of each rejection variant | REST error; ALGO_UPDATE REJECTED + `rm` if it reaches the service |
| reconciliation after each state | | snapshot open orders, open algo orders, positions and compare with the expected state | REST snapshots |
| below-minimum-notional reduce-only conditional leg (G2-029) | -4164 text says "unless you choose reduce only"; MIN_NOTIONAL filter definition has no exemption; New Algo Order page states no minimum | accepted or -4164 | REST/ALGO_UPDATE |
| MARKET_LOT_SIZE for a triggered `*_MARKET` exit (G2-029) | MARKET_LOT_SIZE (min qty, max qty, step) applies to MARKET orders (SOURCES.md Phase 11 row) | needs an actual trigger: place the leg at a trigger price close to the mark on a small open position and capture TRIGGERING, TRIGGERED, FINISHED plus the child order | full ALGO_UPDATE lifecycle and child ORDER_TRADE_UPDATE (`c`, `i`) |

Additions the planner should put to the owner at O-18-03 (not in D-16 as written): (1) an explicit-`timeInForce` variant of the pre-placed leg, because -4509 reads "Time in Force (TIF) GTE can only be used with open positions", the REST parameter list shows `GTC, IOC, FOK, GTX, GTD, RPI` while the ALGO_UPDATE page's EXPIRED example mentions a GTE_GTC conditional order (so the server may apply a GTE default the parameter table does not list) [ASSUMED]; (2) a triggered-protective case (above) to capture the child-order identity and the full ALGO_UPDATE lifecycle, which no D-16 case otherwise produces; (3) a stream-gap case (kill the socket mid-case) to prove gap-then-snapshot against real events.
Cleanup toolbox in the installed SDK [VERIFIED: `rest_api/api/trade_api.py` method list]: `cancel_all_open_orders`, `cancel_all_algo_open_orders`, `cancel_order`, `cancel_algo_order`, `query_all_algo_orders`, `all_orders`, `account_trade_list`, `position_information_v3`, `current_all_open_orders`, `current_all_algo_open_orders`; account state via `account_information_v3` / `futures_account_balance_v3` (`account_api.py`). A residual position is closed with a reduce-only MARKET order (not a protective leg). Probe size limits (symbol, quantity, notional) are the owner's.
Capturing raw frames: the SDK callback only sees the parsed model (unknown fields are lost, pitfall P4). To save faithful fixtures the probe/smoke needs a raw tap: either wrap `binance_common.websocket.parse_user_event` (module-level name imported into `websocket.py`; pin with a contract test) or use the direct `aiohttp` transport for the probe. Recommended: raw tap by wrapping, since it keeps one code path with production.

### F7. Integration map (research question 7)

**Create** (names are the planner's; Discretion):

| File | Purpose |
|---|---|
| `src/domain/exchange_errors.py` (pure) | category enum, `(class, code)` table with source/read date/demo-observed label, `classify(...)`, retry-eligibility per call kind |
| `src/domain/algo_status.py` (pure) | F3 table, `classify_algo_status(value)`, `is_protection_confirmed(value)` |
| `src/adapters/binance_errors.py` | SDK exception to `(http_class, code, retry_after)` normalizer; keeps `is_rate_limit_error`, `is_rate_limit_ban_error`, `rate_limit_retry_after_seconds` names re-exported from `binance_usdm.py` |
| `src/adapters/binance_userdata_events.py` (SDK-free) | frozen event dataclasses (`OrderUpdateEvent`, `AlgoUpdateEvent`, `AccountUpdateEvent`, `ListenKeyExpiredEvent`, `StreamAnomaly`, connection-state values), dict-based strict parsers |
| `src/adapters/binance_userdata.py` | Protocol(s), SDK adapter (listenKey REST via `asyncio.to_thread`, `user_data` subscription, name forgetting, SDK log bridge reuse), supervisor (keepalive, rotation observation, bounded reconnect, UNKNOWN state, gap snapshot trigger) |
| `src/adapters/binance_client.py` | `Environment` enum, host table, `build_sdk_client(env, creds, limits)`, `assert_environment(client, env)` (REST + streams + WS-API URLs), credential loader (env or file path, registers values with the redactor), `ClientLimits` structure (no defaults), pure `evaluate_clock_drift(...)` |
| `scripts/user_data_smoke.py`, `scripts/demo_probe.py` | connected-machine smoke and probe; dry-run default; evidence schema; reuse the shared guard |
| tests: `tests/test_exchange_errors.py`, `test_algo_status.py`, `test_userdata_events.py`, `test_userdata_contract.py`, `test_userdata_supervisor.py`, `test_userdata_replay.py`, `test_binance_client_config.py`, `test_clock_drift.py`, `test_binance_secret_redaction.py`, `test_sdk_error_mapping_contract.py`, `test_demo_probe_dry_run.py`, `test_userdata_smoke_evidence.py`, `tests/userdata_fakes.py`, fixtures under `tests/fixtures/phase18/` | see Validation Architecture |

**Modify:**

| File | Change |
|---|---|
| `src/adapters/binance_usdm.py` | remove `_NOT_FOUND_MESSAGE`, message fallbacks and `_is_already_canceled_message`; route `_is_order_not_found_error` and `_cancel_retry_predicate` through the taxonomy; pass an explicit `recv_window` to every signed SDK call; keep rate-limit helper names |
| `src/execution/manager.py` | replace `_ACTIVE_ALGO_STATUSES` (line 1036) uses at lines 1058 and 1096 with the table |
| `src/execution/fill_monitor.py` | `FillEvent` optional `commission`, `commission_asset`, `realized_pnl`, `is_maker`; include them in the folded fill dict (existing constructors stay valid; `tests/test_execution_attach.py` and `tests/test_execution_partials.py` use `fold_fills`) |
| `src/persistence/entities.py` | new store method(s) for Order `exchange_status` / `exchange_order_id` (G4-043): both columns are already in the `_ORDER` spec's `evolving` set, and the terminal trigger only blocks `local_status` changes [VERIFIED: `src/db/alembic/versions/0004*.py`, `reject_terminal_status_change('local_status', 'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED')`], so an exchange-status write on a terminal order is allowed; no lookup by client id exists in `src/persistence` (client ids appear only in `execution_state.py` insert and mapping code), so stream routing needs a read method or a Protocol the later phases implement |
| `src/persistence/journal.py` / `src/domain/journal.py` | evidence-source and stream-anomaly events (`event_type` strings are free text; ids via `content_hash_event_id` or `correlated_event_id`; identical replay is a no-op in the store) |
| `src/ops/redaction.py` | runtime secret registration; listenKey shape rule or registration |
| `scripts/demo_rehearsal.py` | import the shared guard; keep `DEMO_HOST`, `assert_demo_base_url`, `build_demo_sdk_client` signature (`["api_key", "api_secret"]`, keyword-only) and `DemoHostViolation` names because `tests/test_demo_rehearsal_safety.py` pins them |
| `tests/support/fake_binance_exchange.py` | raise SDK-shaped `BadRequestError(status_code=...)` instead of `RuntimeError("-4116 ...")` once the taxonomy lands; correct the three assumptions only from probe evidence (D-17) |
| `docs/SOURCES.md`, `docs/integration/BINANCE.md` (sections 3, 5, 7), `docs/trading/EXECUTION_SPEC.md` 6.1, `docs/DECISIONS.md` (new row; D072 is the next free number as of this worktree: `D071` is the last row), `ROADMAP.md` criterion text if needed | D-19, D-20 |

Phase 16 continues on `develop` while this phase runs on branch `phase-18`: `docs/SOURCES.md` and `docs/DECISIONS.md` are the likely merge-conflict files and D-number collisions are possible; re-check the next free D-number at write time (pitfall P20).

### Ratification-table inputs for O-18-01 (no value is chosen)

Columns: documented limit or SDK default, project precedent (file), observation, options and trade-off. The user value column is left empty for the checkpoint, as `16-O-07-table.md` did.

| Constant (proposed name) | Documented / SDK default | Project precedent | Observation | Options and trade-offs | User value |
|---|---|---|---|---|---|
| REST timeout | SDK `timeout=1000` ms (single value for connect and read); 408 "timeout waiting for the backend" | `SDK_TIMEOUT_MS = 10000` (`demo_rehearsal.py:188`) | Phase 9 runs completed at 10000 | shorter: more ambiguous placements ("status unknown") and probes; longer: blocks a worker thread and the approval flow; may differ per call kind (reads vs placement) | |
| SDK `retries` / `backoff` | SDK defaults 3 / 1000 ms; applies to GET and DELETE on `requests.RequestException`, blocking `time.sleep` in the worker thread | `_RECONCILER_CANCEL_*` = 3 attempts, 30 s, multiplier 1, wait max 10 (`binance_usdm.py:125-128`) | stacking: with `retries=3` the `retries - attempt` test allows up to 3 SDK requests per call, inside each of 3 tenacity tries, so up to 9 requests for one cancel | `retries=0` (project tenacity is the only retry owner, visible and bounded) versus keep SDK retries (invisible to tests) | |
| `recvWindow` | default 5000 ms (B8); maximum 60000 on algoOrder and positionSide/dual tables (B9, B11) | none (never passed) | | smaller: stricter replay window but more -1021 under jitter; larger: tolerates slow hosts but widens the replay window; behind-clock tolerance equals recvWindow, ahead tolerance is a fixed 1000 ms | |
| clock drift limit (blocks entries) | ahead >1000 ms always rejected; behind > recvWindow rejected | `CLOCK_OFFSET_WARN_MS = 1000` (warn-only, `collector.py:102`) | dev host 182 to 580 ms behind incl. latency (Phase 16 smoke 2026-10-10) | one symmetric limit versus separate ahead/behind limits; include measurement uncertainty (half round trip) or not; a limit below ~600 ms fails on the observed dev host | |
| drift re-measure cadence and max age of a good measurement | n/a | `measure_clock_skew` measured once at start | | periodic versus on -1021 only (D-14 requires re-measure on -1021) | |
| listenKey keepalive cadence | validity 60 min from the last POST/PUT; "recommended ... about every 60 minutes" | none | | any value must be below 3600 s minus the longest tolerated retry window; shorter = more weight-1 calls and earlier detection of a dead key; at 3600 s a single late call loses the stream | |
| keepalive failure tolerance (consecutive failures before UNKNOWN / rebuild) | -1125 means the key is gone | none | | 1 (strict) versus N; -1125 should not be retried: recreate with POST | |
| connection rotation margin | docs 24 h cap; SDK rotates at 82800 s (23 h) per connection | `SDK_RECONNECT_FLOOR_SECONDS = 300` (`scripts/paper_ws_smoke.py`, smoke guard); Phase 16 O-07 "SDK connection rotation: ratify current" | Phase 16 smoke exercised 3600 s override | ratify the SDK's 23 h versus a project timer; either way a gap-then-snapshot follows | |
| reconnect backoff caps | SDK `reconnect_delay=5000`, `reconnect_attempts=3` (max 10) | supervisor 7 / 120 s / 1 / 60 s (`src/paper/supervisor.py:63-66`); Phase 16 ratified "current" | forced drop recovered in about 2.3 to 2.8 s | reuse the ratified paper values or separate order-path values; never infinite | |
| maximum stale-stream age (entries blocked) | server pings every 3 min, disconnect after 10 min without pong (B4); **no events is normal** | Phase 16 `max_ws_message_silence_seconds` 3900 is for hourly bar evidence, not for user data | | define staleness on liveness (last ping/pong frame or last successful keepalive) not on event silence; **overlaps Phase 20 T-06 / G2-026** (WS-silence threshold is owned there): Phase 18 may only expose the parameter | |
| gap-then-snapshot timing | no replay documented | none | | snapshot deadline, retries (tenacity), what happens on failure (stay UNKNOWN, entries blocked) | |
| default wait when 418/429 has no `retry_after`; cap on `retry_after` | ban "from 2 minutes to 3 days"; `Retry-After` unconfirmed | `rate_limit_retry_after_seconds` returns None for bool/negative/non-int | | fail closed with an owner-set wait; the cap protects against an absurd header | |
| event queue bound (adapter to consumer) | 10 incoming msg/s per connection (B4) | none | | bounded queue with overflow = anomaly + UNKNOWN versus unbounded | |
| probe size limits (symbol, quantity, notional, retries, cleanup timeout) | filters from exchangeInfo | rehearsal fixed `SYMBOL = "BTCUSDT"` | | owner approval at O-18-03 | |

Implementation shape that respects D-14 and "never fills a number": a frozen `ClientLimits` / `StreamLimits` dataclass with no field defaults plus module constants labelled PLACEHOLDER whose value is unusable until a ratified record is loaded, or a required constructor argument everywhere; the ratified values land in one reviewed file after the checkpoint. The planner chooses; the research only notes that a PLACEHOLDER label is an existing provenance category (AGENTS.md Conventions).

## Architecture Patterns

### System Architecture Diagram

```text
                       (connected machine only)
  Binance REST  ---------------------------------------------------------+
  /fapi/v1/listenKey (POST start, PUT keepalive, DELETE close)            |
  /fapi/v1/time, snapshots, userTrades, algoOrder queries                 |
        ^                                                                 |
        | asyncio.to_thread (sync SDK, requests)                          |
  +-----+-----------------------------------------------+                 |
  | src/adapters/binance_client.py                        |                 |
  |  Environment enum -> host table -> SDK client        |                 |
  |  guard: REST base_path + streams stream_url + WS-API  |                 |
  |  credentials (env | file) -> registered with Redactor |                 |
  |  ClientLimits (no defaults) ; drift fn (pure)         |                 |
  +-----+-----------------------------------------------+                 |
        |                                                                 |
  +-----v-----------------------------------------------+   Binance WS /private
  | src/adapters/binance_userdata.py                      |   (SUBSCRIBE listenKey via SDK
  |  Supervisor coroutine (injected clock)                |    OR documented ?listenKey= URL)
  |   start -> POST listenKey -> connect /private -> SYNCING --+
  |   keepalive timer (PUT)   rotation/reconnect observer      |
  |   state: CONNECTING | SYNCING | LIVE | UNKNOWN             |
  |   on any gap/reconnect/missed keepalive: UNKNOWN -> REST snapshot -> LIVE
  |  raw callback (event loop thread, never raises) -> bounded asyncio.Queue
  +-----+-----------------------------------------------+
        | SDK model or raw dict -> plain dict
  +-----v-----------------------------------------------+
  | src/adapters/binance_userdata_events.py (SDK-free)    |
  |  strict dict parsers -> frozen dataclasses            |
  |  OrderUpdate | AlgoUpdate | AccountUpdate |           |
  |  ListenKeyExpired | StreamAnomaly                     |
  +-----+--------------------------+----------------------+
        | fills (x=TRADE)          | anomalies, evidence
  +-----v----------+        +------v----------------------+
  | fold_fills     |        | journal (append-only)       |
  | (order_id,     |        | evidence_source = USER_DATA |
  |  trade_id) key |        | | REST_RECONCILE            |
  +-----+----------+        +------+----------------------+
        | position view            | divergences
        v                          v
   Phase 19/20/24 consumers  (reconciler is the authority; REST wins on disagreement)

  Pure core (no SDK): src/domain/exchange_errors.py, src/domain/algo_status.py
  Errors: SDK exception -> (http class, code, retry_after) -> category -> retry / SAFE_MODE decision
```

### Recommended structure

```text
src/domain/exchange_errors.py          # pure taxonomy (categories, code table, classify)
src/domain/algo_status.py              # pure ALGO_UPDATE status table
src/adapters/binance_errors.py         # SDK exception normalizer
src/adapters/binance_client.py         # environment, guard, credentials, limits, drift
src/adapters/binance_userdata_events.py# SDK-free events and parsers
src/adapters/binance_userdata.py       # adapter + supervisor
scripts/user_data_smoke.py             # connected-machine smoke (evidence JSON)
scripts/demo_probe.py                  # connected-machine D055 probe (dry-run default)
tests/userdata_fakes.py                # SDK-shaped fakes bound by contract tests
tests/fixtures/phase18/                # SYNTHETIC_FROM_SDK_MODEL first, RECORDED_DEMO later
```

### Pattern 1: SDK-free event types behind an SDK adapter
**What:** the adapter converts whatever the SDK hands to the callback (a `UserDataStreamEventsResponse` with `actual_instance` a pydantic model, or the same wrapper holding a raw dict) into one plain dict plus an event-type string, and a pure parser validates it into a frozen dataclass or a `StreamAnomaly`. **When:** always; it is the only way the strict-model fallback (pitfall P4) and unknown fields are handled by one code path.
**Example (sketch from installed source, not executed):**
```python
# Source: binance_common/utils.py parse_user_event / resolve_model_from_event (read 2026-10-15)
def unwrap(message: object) -> tuple[str | None, dict[str, object] | None]:
    inst = getattr(message, "actual_instance", message)
    if isinstance(inst, dict):                       # raw-dict fallback branch
        return (str(inst.get("e")) if inst.get("e") else None), inst
    to_dict = getattr(inst, "to_dict", None)         # pydantic model: alias keys, None excluded
    if callable(to_dict):
        return type(inst).__name__, to_dict()        # event name == SDK class name
    return None, None                                # -> StreamAnomaly(kind="UNRECOGNIZED_ENVELOPE")
```

### Pattern 2: Supervisor state machine with gap-then-snapshot (D-03)
States `CONNECTING -> SYNCING -> LIVE`, any reconnect, rotation event, missed keepalive or `listenKeyExpired` goes to `UNKNOWN`; events received while `SYNCING` or `UNKNOWN` are queued but flagged `post_gap=True` and are not trusted until a REST snapshot (open orders, open algo orders, positions, and `userTrades` for the fill key space) has been taken and compared. Follow `PaperSupervisor` (tasks spawned from synchronous SDK callbacks, `_spawn`/`_task_done`, bounded `tenacity` rebuild, stop that cancels tasks) but distinguish connection `error` from connection loss (pitfall P5).

### Pattern 3: Taxonomy input is a triple
`classify(http_class, code, call_kind)` where `http_class` is one of `BAD_REQUEST, UNAUTHORIZED, FORBIDDEN, NOT_FOUND, BANNED_418, TOO_MANY_429, SERVER_5XX, CLIENT_OTHER, NETWORK, NON_SDK` and `call_kind` one of `PLACEMENT, CANCEL, QUERY, LISTEN_KEY, TIME`. The same code means different things per call kind (-2011 on cancel versus -2013 on query), and a placement path never maps anything to "absent".

### Pattern 4: Pinned-contract tests for every SDK internal the code relies on
Same style as `tests/test_paper_ws_contract.py` (introspection only, no client constructed): `user_data` is a coroutine with parameter `listenKey`; `RequestStreamHandle` public members are `{on, unsubscribe}`; the `UserDataStreamEventsResponse.one_of_schemas` set; the alias set of `OrderTradeUpdateO`, `AlgoUpdateO`, `AccountUpdateA` fields the parser reads; `ConfigurationRestAPI` accepts `timeout`, `retries`, `backoff`, `base_path`; `binance_common.errors` classes expose `status_code` (and `retry_after` on the two rate-limit classes); `AUTO_RECONNECT_INTERVAL_SECONDS` equals `23 * 3600` and is read from the `binance_common.websocket` module namespace; `global_user_stream_connections` exists. Plus one behavior-pinning test with no network: call `binance_common.utils.send_request(session, configuration, ...)` with a stub session whose `request()` returns crafted responses (status 400/401/403/404/408/418/429/503, JSON and non-JSON bodies, a `Retry-After` header) and assert the exception class, `status_code` and `retry_after` for each row of the F4 table. The `requests.Session.request` monkeypatch in `tests/test_demo_rehearsal_safety.py::_patch_transport` is the precedent for transport-level proof.

### Anti-patterns to avoid
- **Deciding anything from `rm` or any `error_message` text** (D-10): it is diagnostic only.
- **Treating event silence as staleness**: on a user-data stream no orders means no events.
- **Using the stream as the only source of truth** (CONTEXT specifics): every decision needs a REST confirmation path.
- **Creating the streams client next to a REST-only Demo client without passing `config_ws_streams`** (P1).
- **Re-subscribing a name the SDK still has mapped** (P6).
- **Letting the SDK and tenacity both retry** (P9).
- **Importing `src.paper` from the new supervisor** (D-03).

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| WebSocket ping/pong, 23 h rotation, reconnect, resubscribe | own socket loop | SDK `WebSocketStreamBase` via `user_data` (observe `on_connection` events) | documented SDK behavior, contract-tested; direct `aiohttp` only as a gated fallback |
| HMAC signing, timestamping, query encoding | own signer | SDK `send_request` | already correct; only `recv_window` must be supplied |
| Bounded retry with jitter | `while`/`sleep` loops | `tenacity` (`AsyncRetrying`, `stop_after_attempt`, `wait_random_exponential`) as in `binance_usdm.py` | pinned dependency, existing pattern |
| Secret scrubbing | ad-hoc `replace` | `src/ops/redaction.py` `Redactor`/`RedactingFilter`/`redact_processor`, extended for runtime secrets | one shared redactor already applied to all output paths |
| Atomic scrubbed evidence file | custom writer | `EvidenceRecorder.write` pattern of `scripts/demo_rehearsal.py` (temp file, `os.replace`, post-write scan) | already proven; move to a shared module |
| Deterministic journal ids | uuid or time-based | `correlated_event_id` / `content_hash_event_id` (`src/domain/journal.py`) | identical replay is a no-op in the store (D051 b) |
| Decimal wire conversion | `float` or `str(Decimal)` | `_decimal_to_wire` (`format(value, "f")`) for outgoing; `Decimal(str)` with finite check for incoming | exponent notation is rejected by Binance |
| Host allow-list check | substring match | the exact-match logic of `assert_demo_base_url` (scheme, hostname, port, userinfo, query, path) generalized per environment | prefix/substring checks were the attack the tests enumerate (`demo-fapi.binance.com.evil.example`, `@evil.example`) |

**Key insight:** the dangerous parts of this phase are the seams (SDK silently dropping or reshaping frames, exceptions that hide the HTTP status, logs that carry credentials), not the algorithms; the code worth writing is small, pure and exhaustively tested, and everything else should stay SDK-owned.

## Runtime State Inventory

Not a rename, refactor or migration phase. Omitted. (The removal of the message-text fallbacks in `binance_usdm.py` changes behavior but not any stored string; no data migration, service configuration, OS registration, secret name or build artifact carries a renamed identifier.)

## Common Pitfalls

### P1. Mixed environment: REST on Demo, WebSocket on mainnet
**What goes wrong:** `DerivativesTradingUsdsFutures` fills a missing `config_ws_streams.stream_url` with `wss://fstream.binance.com` (mainnet). **Avoid:** build all three configurations from one environment row, assert REST `base_path`, streams `stream_url` (after property access) and WS-API URL against the row before any call, funnel construction through one function (AST test). **Warning sign:** `assert_demo_sdk_client` passes while the socket host is mainnet.

### P2. SUBSCRIBE with a bare listenKey may not deliver events
**What goes wrong:** the SDK subscribes by name and routes only messages whose `stream` field equals the registered name; a message without that envelope reaches `logging.info("Received message: ...")` and nothing else, so events (including account data) vanish and appear in the INFO log. **Avoid:** the smoke's first acceptance criterion is end-to-end delivery to the project callback; keep the direct-URL transport plan conditional on it; log an `unrouted_message` counter by wrapping the SDK fallback only if the smoke shows it is needed. **Status:** UNVERIFIED (B3, B12). Related detail: the SDK sends `SUBSCRIBE` with a uuid STRING `id` (`id_strict_int` defaults to False in `WebSocketStreamBase.__init__`) while the live-subscribing page describes `id` as "an unsigned INT"; string ids worked for the market/public kline subscriptions in the Phase 16 live smoke (`evidence/16-21-ws-smoke-live.json`, `ws_subscribe.status` "OK", read 2026-10-15), which says nothing about `/private`.

### P3. The listenKey is written to logs and is not scrubbed
**What goes wrong:** `WebSocketStreamBase.subscribe` logs `f"Subscribing to streams on WebSocket {connection.id}: {connection_streams}"` at INFO through the root logger, and `redact_sensitive_info` redacts only keys `apiKey` and `signature`. `Redactor` has no listenKey rule. A leaked listenKey exposes the account's order/position/balance stream. **Avoid:** register the key with the redactor on receipt, or add a 64-character alphanumeric shape rule guarded by context; test by grepping captured stdlib and structlog output for the key.

### P4. SDK models are strict, silent about unknown fields, and fall back to raw dicts
**What goes wrong:** `StrictStr`/`StrictInt` fields make a numeric money field fail validation, after which the callback receives a wrapper around the raw dict; `model_validate` drops fields the model lacks (a new Binance field is invisible). **Avoid:** one dict-based parser for both paths (Pattern 1); every money field must be `str` (reject `int`/`float` as an anomaly); raw-frame taps for fixtures (F6).

### P5. Callback exceptions are swallowed and surface as a connection `error` event
**What goes wrong:** the SDK catches an exception from the message callback, logs it and emits `error` to connection callbacks. `PaperSupervisor._DROP_EVENTS = frozenset({"close", "error"})` would then rebuild a healthy connection (rebuild storm) and the event is lost. **Avoid:** the raw callback only enqueues and never raises; the supervisor treats `error` as loss only when the connection list shows no open `/private` socket.

### P6. Stale stream names and the reused listenKey
**What goes wrong:** after an unsolicited close the SDK keeps the listenKey in `global_stream_connections`; `subscribe` skips names already mapped, so a re-subscribe of the same key sends nothing; `POST /listenKey` returns the SAME key while it is active. **Avoid:** forget the exact name before re-subscribing (copy `_forget_own_streams`); a second client in the same process shares the module-global map (test isolation: `fresh_sdk_stream_map`, plus `global_user_stream_connections`).

### P7. The listenKey is an account singleton
**What goes wrong:** the documented calls take no key argument and `POST` returns the active key, so the smoke or probe calling `DELETE` ends the stream of a running supervisor on the same account. **Avoid:** never run smoke/probe while a supervisor is live on the same account; the smoke's close step is explicit and last; the singleton reading is an inference [ASSUMED].

### P8. Rotation and reconnect gaps; the SDK resubscribes the OLD key
**What goes wrong:** every 23 h (SDK) and on any drop, events in the swap window are lost; `_resubscribe_global_streams` re-sends the listenKey it remembers, which is wrong if the project replaced the key after `-1125`. **Avoid:** on any `reconnect`/`open` after the first, go UNKNOWN and snapshot; if the key changed, unsubscribe/forget the old name and subscribe the new one before trusting events.

### P9. SDK REST timeouts, retries and threads
**What goes wrong:** default `timeout=1000` ms; `retries=3`/`backoff=1000` retry GET and DELETE inside `send_request` with blocking `time.sleep`, multiplying with tenacity (a cancel can make up to 9 requests: 3 tenacity tries times up to 3 SDK requests); one `requests.Session` is shared by concurrent `asyncio.to_thread` calls. **Avoid:** set `retries=0` and an explicit timeout in the configuration layer (values ratified at O-18-01), let tenacity be the only retry owner, bound concurrency.

### P10. `status_code` is not the HTTP status
See F4 table. 418 and 429 are classes; 5xx loses the body; other 4xx (408, 405, 413...) become `ClientError` with `status_code=None`; non-JSON error bodies give `None`. A taxonomy keyed on int alone mislabels these as "no code". **Avoid:** triple input and a stub-session contract test.

### P11. recvWindow and the clock
**What goes wrong:** nothing passes `recv_window` today, the server default of 5000 ms applies, and the signing clock is the host's `time.time()`. A host ahead of Binance by more than 1000 ms gets -1021 even with a large recvWindow. **Avoid:** explicit `recv_window` on every signed call (parametrized test over the adapter methods), drift measured with an injected clock and half-round-trip uncertainty, -1021 triggers re-measure not retry.

### P12. Event silence is not staleness
A quiet account produces no events for hours. Liveness is ping/pong frames (server ping every 3 minutes, pong deadline 10 minutes) and keepalive success. The SDK answers server pings automatically (`autoping=False` plus explicit `pong`), so a silent but healthy socket stays up.

### P13. Two fill key spaces
`scripts/demo_rehearsal.py` synthesizes `exchange_trade_id=f"position-view:{order_id}"` from a REST position view. Folding such a synthetic fill together with real stream fills double counts. **Avoid:** one source per order in a fold, and use `account_trade_list` (real trade ids) as the REST fallback so the key `(order_id, exchange_trade_id)` is identical across sources.

### P14. Triggered protective orders have an unknown child identity
See F2 identity trap. Until the probe records `c`/`i` of the child order, a protective-leg fill cannot be attributed from `ORDER_TRADE_UPDATE` alone; use `ALGO_UPDATE.ai`/`aq`/`ap` and REST `actualOrderId`/`actualQty`.

### P15. Ordering of ACCOUNT_UPDATE versus ORDER_TRADE_UPDATE is unverified
Do not let any state depend on which arrives first; both are hints, the snapshot decides.

### P16. Hedge mode and `ps`
`ps` is BOTH in one-way mode; in hedge mode `reduceOnly` cannot be sent and `positionSide` is mandatory (B9). `ACCOUNT_UPDATE.a.P` can carry several rows per symbol. Position mode is detected dynamically (`get_position_mode`), never assumed; -4067/-4068/-4531 govern changing it.

### P17. Decimal strictness
Money fields arrive as strings; a bare number in a raw-dict fallback must be rejected, not coerced (`Decimal(str(float))` would hide a float). Reject non-finite values, negative quantities, empty strings; never default to zero (09-REVIEW WR-04 precedent).

### P18. Windows, asyncio and test isolation
SDK module state (`global_stream_connections`, `global_user_stream_connections`) leaks across tests; the SDK creates `aiohttp.ClientSession` inside `connect` (needs a running loop; close with `close_connection(close_session=True)`); sync REST runs in `asyncio.to_thread`. The project's `asyncio_mode = "auto"` applies. Tests never construct a real SDK client (contract-test rule).

### P19. DEMO versus TESTNET naming and per-environment keys
See F5. A Demo key does not work on mainnet and vice versa; with three environments and two credential name pairs the loader must map environment to variable names explicitly and refuse a LIVE key for DEMO (and the reverse).

### P20. Parallel work on `develop` and document gates
Phase 16 keeps running on `develop`: `docs/SOURCES.md` and `docs/DECISIONS.md` are the likely conflict files and the next D-number can be taken; re-check at write time.

### P21. Probe feasibility and cleanliness
Partial fills may not be inducible; cleanup must cancel normal and algo orders and flatten with a reduce-only MARKET order; record account state before and after; remember the singleton listenKey (P7); never run two probe sessions in parallel.

### P22. Event kinds the project did not place
`x == "AMENDMENT"` (+`M`), `x == "CALCULATED"` (liquidation), client ids starting `autoclose-`, `adl_autoclose`, `settlement_autoclose-`, `X == "EXPIRED_IN_MATCH"`, `er` expiry reasons: all must classify as anomalies or terminal-not-filled, never be dropped (D-05).

### P23. `rm` is free text
Example value "Reduce Only reject". Journal it verbatim (scrubbed) for diagnosis; derive nothing from it.

### P24. The current cancel retry predicate retries definitive rejections
`_cancel_retry_predicate` retries every exception that is not a message-matched "already canceled" and not ValueError/KeyError/TypeError, which includes -2019 or auth failures. Replace with the taxonomy's `retry_eligible(category, call_kind)`.

### P25. Document gates pin wording
`scripts/decision_alignment/exchange.py` (tests in `tests/test_decision_alignment_exchange.py`) requires: EXECUTION_SPEC section 6.1 table rows `NEW, TRIGGERING, FINISHED, REJECTED, EXPIRED` and the phrases `FINISHED does not mean filled`, `ALGO_UPDATE`, `o.rm`, `no margin check before`, `verify against current Binance docs`, `F-054`; BINANCE.md sections 3, 5, 7, 9 phrases and at least three `verify against current Binance docs` markers; and every `developers.binance.com` URL cited in EXECUTION_SPEC.md must be a row of the "Facts verified for Phase 11 (2026-09-30)" section of SOURCES.md whose date cell contains `2026-09-30` (`FETCH_DATE`). New 2026-10-15 reads therefore go in a NEW SOURCES.md section ("Facts read for Phase 18 (2026-10-15)"), EXECUTION_SPEC.md must not cite new Binance URLs (cite the SOURCES.md section instead) unless the gate is deliberately amended with its tests, and adding rows TRIGGERED and CANCELED to the 6.1 table is allowed (the gate only requires the five names).

## Code Examples

Sketches from installed source and project files; none were executed.

### listenKey lifecycle through the SDK (REST, run in a thread)
```python
# Source: rest_api/api/user_data_streams_api.py (SDK 17.4.0, read 2026-10-15)
resp = await asyncio.to_thread(sdk.rest_api.start_user_data_stream)      # POST /fapi/v1/listenKey
key = resp.data().listen_key                                              # alias "listenKey"
await asyncio.to_thread(sdk.rest_api.keepalive_user_data_stream)          # PUT, no argument
await asyncio.to_thread(sdk.rest_api.close_user_data_stream)              # DELETE, ends the account's stream
```

### Event subscription through the SDK streams client
```python
# Source: websocket_streams/websocket_streams.py user_data + binance_common/websocket.py RequestStream
ws = DerivativesTradingUsdsFuturesWebSocketStreams(
    ConfigurationWebSocketStreams(stream_url=ENV_ROW.ws_streams_url, reconnect_attempts=3)
)
await ws.create_connection()            # swallows connect errors: check ws.connections afterwards (paper_ws.py:282-297)
handle = await ws.user_data(listen_key) # SUBSCRIBE params=[listen_key] on the /private connection
handle.on("message", on_message)        # synchronous callback on the event-loop thread; must enqueue only
ws.on_connection("reconnect", on_reconnect)   # applies to existing connections; copied to replacements
```

### Pure drift decision (no wall clock inside)
```python
# Design sketch: measured with an injected clock around one server_time() call
def evaluate_clock_drift(*, before_ms: int, server_ms: int, after_ms: int,
                         ahead_limit_ms: int, behind_limit_ms: int) -> DriftVerdict:
    mid = (before_ms + after_ms) // 2
    uncertainty = (after_ms - before_ms + 1) // 2
    offset = mid - server_ms            # positive: host clock ahead of Binance
    ok = (offset + uncertainty) <= ahead_limit_ms and (-offset + uncertainty) <= behind_limit_ms
    return DriftVerdict(offset_ms=offset, uncertainty_ms=uncertainty, within_limits=ok)
# a failed measurement is DriftVerdict(measurement_failed=True, within_limits=False)
```

## State of the Art

| Old approach | Current approach | When changed | Impact |
|--------------|------------------|--------------|--------|
| Conditional orders on `/fapi/v1/order`, `CONDITIONAL_ORDER_TRIGGER_REJECT` event | `/fapi/v1/algoOrder`, `ALGO_UPDATE` with `rm` | migration effective 2025-12-09; event deprecated 2025-12-15 | parse `ALGO_UPDATE`; old endpoints return -4120 |
| single `/ws` USDⓈ-M URL | routed `/public`, `/market`, `/private` | URLs announced 2026-03-05; legacy retired 2026-04-23 | user data only on `/private` |
| `ia` placeholder always false | `ia` fully active, trailing stops push NEW twice | 2026-08-21 | irrelevant for STOP/TP market legs |
| `MAX_NUM_ALGO_ORDERS` per-symbol filter | 200 conditional orders across all symbols | 2025-12-29 | already handled by Phase 11 |
| legacy connectors | official modular SDK 17.x | 2026-04-30 archive of old connectors | already adopted |

**Deprecated/outdated:** `CONDITIONAL_ORDER_TRIGGER_REJECT` (SDK model still present; treat arrival as an anomaly); the SDK `testnet.binancefuture.com` constants (docs now label `demo-fapi.binance.com` as "testnet").

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | The event string for listenKey expiry is `listenKeyExpired` | F2 | parser would not recognize the event (SDK match is case-insensitive, low risk) |
| A2 | `PUT /fapi/v1/listenKey` on an expired or closed key returns code -1125 | F4 | wrong keepalive failure handling; smoke "DELETE then PUT" records it |
| A3 | REST `algoStatus` values equal the WS `X` values | F3 | classification table misses a REST-only value (falls to UNKNOWN, fail closed) |
| A4 | The listenKey is per account (singleton) | F1, P7 | smoke/probe may or may not disturb a supervisor |
| A5 | Demo serves `POST /fapi/v1/listenKey` and a `/private` user-data socket at `wss://demo-fstream.binance.com` | F5 | the whole live smoke cannot run on Demo; fallback environment decision at O-18-04 |
| A6 | A bare listenKey in JSON `SUBSCRIBE` params is accepted on `/private` and events arrive in a `{"stream","data"}` envelope | F1, P2 | SDK route delivers nothing; direct-URL transport plan becomes mandatory |
| A7 | The `events=` URL parameter is optional | F1 | direct transport must list events explicitly |
| A8 | Default aiohttp TLS verification applies (`ssl=configuration.https_agent` is None) | Security | would only matter if someone passes `ssl=False`; add a test that no such argument exists |
| A9 | Binance sends `Retry-After` on 418/429 | F5 | `retry_after` is None in practice; owner-set fallback wait is then the only control |
| A10 | `ORDER_TRADE_UPDATE` x values and X values listed in B5b are complete | F2 | an unseen value must go to an anomaly, not be coerced (already required) |
| A11 | An explicit `timeInForce` on the pre-placed leg could change the -4509 outcome | F6 | wasted probe case; low cost |
| A12 | Futures Demo API keys are created on the demo site (only the Options Demo statement was read) | F5 | key provisioning instructions in the probe README would be wrong |
| A13 | The 24-hour connection cap applies to `/private` as to other routed paths | F1 | rotation handling still correct (SDK rotates at 23 h per connection) |
| A14 | `requests.Session` shared across `to_thread` calls is safe enough for sequential use | P9 | rare corrupted connection pool state; serialize signed calls if observed |

## Open Questions

1. **Does the SDK `/private` route deliver events?** Known: SDK subscribes by bare listenKey; docs show only the URL-parameter form. Unknown: parameter format, envelope, `events` requirement. Recommendation: first smoke criterion; conditional direct-transport plan prepared but gated.
2. **What does `TESTNET` mean in the `DEMO | TESTNET | LIVE` enum, and is the Demo WS URL `wss://demo-fstream.binance.com`?** Recommendation: put to the owner at O-18-04; until answered the TESTNET row raises "not configured".
3. **Classification of TRIGGERING, TRIGGERED, FINISHED, CANCELED (F3 flags).** Recommendation: user confirms at the first checkpoint together with O-18-01 (safety policy).
4. **Stale-stream age versus Phase 20 T-06.** Recommendation: Phase 18 exposes liveness inputs and a required parameter; the numeric value is either ratified in O-18-01 or explicitly deferred to T-06 by the owner.
5. **Extra probe cases** (explicit timeInForce variant, triggered protective, stream-gap case, `DELETE` then `PUT` to see -1125). Recommendation: list them at O-18-03 as optional; D-16 stays the minimum.
6. **Credential variable names for Demo** (reuse `BINANCE_TESTNET_*` or add `BINANCE_DEMO_*`). Recommendation: small planner/owner call at the config checkpoint.
7. **PLACEHOLDER constants versus required constructor arguments** for unratified limits. Recommendation: required arguments, so no unratified number can exist in code.
8. **Fill REST fallback key space**: confirm `account_trade_list` `id` equals stream `t` on Demo (probe capture).

## Environment Availability

| Dependency | Required by | Available (this machine) | Version | Fallback |
|------------|-------------|--------------------------|---------|----------|
| Python 3.13 (project `.venv` in the main checkout) | tests, scripts | yes | 3.13.15 | none needed |
| uv | `uv run`, `uv lock --check` | yes | 0.12.20 (lock pins 0.12.21 image) | none needed |
| Installed SDK 17.4.0 / binance-common 4.4.0 | contract tests, source reading | yes (main checkout `.venv`) | 17.4.0 / 4.4.0 | none |
| Binance REST/WS (Demo) | smoke, probe, live re-read of event pages | **no** (user rule: no Binance/Telegram from this machine) | - | blocking-human plans on a connected machine |
| PostgreSQL 17 (`TEST_DATABASE_URL`) | store-method tests (G4-043/G4-034) | not checked (not probed on this machine) | - | those tests skip without it; CI/executor machine runs them |
| Docker | `-m docker` tests | not needed for this phase | - | `-m "not docker"` |

**Missing dependencies with no fallback:** Binance connectivity for D-16 evidence, the live smoke and the doc re-read of the four event pages (all blocking-human by design).
**Missing dependencies with fallback:** PostgreSQL tests run on the executor machine.

## Validation Architecture

(`workflow.nyquist_validation` is `true` in `.planning/config.json`.)

### Test framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x with pytest-asyncio 1.4 (`asyncio_mode = "auto"`) [VERIFIED: pyproject.toml `[tool.pytest.ini_options]`] |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest -m "not docker" tests/<new_file>.py -x` |
| Full suite command | `uv run pytest -m "not docker"` |
| Other gates | `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check` (AGENTS.md Conventions) |
| Live-PostgreSQL tests | need `TEST_DATABASE_URL`, skip without it |

### Decision-to-test map

| Decision | Offline automated proof | Needs a connected machine (blocking-human) |
|---|---|---|
| D-01 SDK-free frozen events | `test_userdata_events.py`: construction rejects float, naive datetime, empty string; AST test that `binance_userdata_events.py` and `src/domain/exchange_errors.py`/`algo_status.py` import no `binance_*`/`requests`/`aiohttp` | design review of the event types before Phases 19/20 import them (one-way door) |
| D-02 SDK route, contract | `test_userdata_contract.py` (Pattern 4 list) + `test_sdk_error_mapping_contract.py` (stub-session `send_request`) | smoke criterion 1: event delivery through `user_data` on Demo |
| D-03 supervisor | `test_userdata_supervisor.py`: injected clock, scripted fake socket: keepalive cadence, `reconnect`/`open` sequence to UNKNOWN then snapshot then LIVE, key replaced after -1125, bounded tenacity (attempt count asserted, never infinite), clean stop cancels tasks, `error` event with open socket is not a loss | smoke: forced transport drop then recovery observed |
| D-04 no composition | grep/AST test: no module under `src/` other than scripts imports the supervisor for wiring; smoke script dry-run runs on the fake rig | none |
| D-05 anomalies | parser tests: unknown order id, malformed JSON types, non-string money, unknown `X`, bad ms time, `AMENDMENT`, `CALCULATED`, `autoclose-` id: each yields a `StreamAnomaly` that reaches the journal sink; nothing silently dropped | none |
| D-06 fills + commission | `x=TRADE` frames to `FillEvent` with commission, asset, realized PnL, maker flag; `z` equals sum of `l` check | none |
| D-06 replay | `test_userdata_replay.py`: the same fills replayed, reordered and duplicated fold to the same `FoldedPositionView` (property-style over permutations); mixed REST/stream key-space case documented as an expected-double-count negative control | none |
| D-07 status table | exhaustive over the seven values plus unseen/None/empty; `manager.py` adoption and confirmation tests updated; doc gate `tests/test_decision_alignment_exchange.py` still green | probe records REST `algoStatus` per state |
| D-08 ACCOUNT_UPDATE, evidence, store methods | parse tests (signed `pa`, `S` only for FUNDING_FEE); journal evidence-source events replay as no-ops; `exchange_status` update allowed on terminal order, `local_status` transition still blocked (PG tests, skip without `TEST_DATABASE_URL`) | none |
| D-09/D-10 taxonomy | table test for every code in F4 with `(class, code)` triples, one test per HTTP class, unknown code to UNKNOWN_EXCHANGE_ERROR, `status_code=None`, bool rejected; a source scan test that no `str(exc)`/regex/message branch decides in `src/adapters`/`src/execution`/`src/reconcile`; rewrite `tests/test_adapter_not_found_mapping.py` (legacy-message test reversed) | probe records -2013 on GET order, duplicate algo id code, -4509 variants |
| D-11 retry rules | placement called once on every error class; cancel retried only for transient categories up to `_RECONCILER_CANCEL_*`; 418 never retried and waits `retry_after` (injected sleep); 429 honors `retry_after`; timeout/5xx on placement returns "status unknown" to the manager probe path | none |
| D-12 environment selection | missing/unknown value raises; each environment row builds REST + streams + WS-API URLs; guard rejects every near-miss URL (reuse the parametrized list of `test_demo_rehearsal_safety.py`); transport-level test with patched `requests.Session.request` shows only the selected host; AST test: SDK client constructed only in the factory; LIVE refuses without enablement state | smoke confirms Demo WS URL |
| D-13 keys and redaction | key from env or file path only (no CLI option exists: parser test); file-loaded values registered with the redactor; captured stdlib and structlog output contains neither key, secret, signature nor listenKey; `NetworkError` text with `signature=` is scrubbed | none |
| D-14 drift and recvWindow | `evaluate_clock_drift` boundary tests (ahead 1000 ms rule, behind recvWindow rule, failed measurement blocks, uncertainty included); -1021 triggers re-measure and no order retry; parametrized test that every signed adapter method forwards a non-None `recv_window` to the SDK fake; configuration has no unratified default (required-argument test) | ratification checkpoint (O-18-01) |
| D-15 probe script | dry-run sends nothing (`GuardedAdapter` pattern), host asserted before the first signed call, evidence has `schema` name+version, scrub-before-and-after-write test, `--execute` without TTY/phrase exits 2 | `--execute` runs (O-18-03) |
| D-16 case order | dry-run enumerates cases in the D-16 order and writes `NOT_REHEARSED` steps | executed evidence |
| D-17 fake correction | test that the fake raises SDK-shaped errors (class + `status_code`) | correction from evidence only; plan states "fake unchanged" if the probe has not run |
| D-18 split | plan-structure check: every blocking-human plan lists prerequisites and measurable acceptance | the runs themselves |
| D-19/D-20 docs | `tests/test_decision_alignment_exchange.py` and the SOURCES register check; a new SOURCES section with URL, read date, method, not-verified-live label for each Phase 18 fact | executor repeats the page reads |
| D-21 test strategy | the list above | - |
| D-22 determinism | AST/grep: no `float(` on money paths in the new modules, no `datetime.now`/`time.time` in pure modules, journaled payloads use sorted-key JSON and canonical decimal text | none |

### Phase requirements to test map
| Req ID | Behavior | Test type | Automated command | File exists? |
|--------|----------|-----------|-------------------|--------------|
| EXEC-05 | stream events become fills/state hints with REST fallback | unit + fake rig + replay | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_userdata_supervisor.py tests/test_userdata_replay.py -x` | Wave 0 gap |
| EXEC-01 | status table drives attach/adoption; placement not retried | unit | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_execution_attach.py -x` | partial (attach exists) |
| EXEC-02 | not-found and rate-limit handling in probes/sweeper; evidence source | unit | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_reconcile.py -x` | partial |
| OPS-02 | no secret, signature or listenKey in any output | unit | `uv run pytest -m "not docker" tests/test_binance_secret_redaction.py tests/test_binance_client_config.py -x` | Wave 0 gap |

### Sampling rate
- **Per task commit:** the touched test file(s) with `-x`, then `uv run ruff check` and `uv run mypy src` on the touched modules.
- **Per wave merge:** `uv run pytest -m "not docker"`, `uv run ruff format --check`, `uv lock --check`.
- **Phase gate:** full suite green before `/gsd-verify-work`; blocking-human evidence files attached.

### Wave 0 gaps
- [ ] `tests/userdata_fakes.py` (SDK-shaped fake streams client and handle, mirrored by `test_userdata_contract.py` the way `paper_ws_fakes.py` is by `test_paper_ws_contract.py`)
- [ ] `tests/fixtures/phase18/` frames labelled `SYNTHETIC_FROM_SDK_MODEL` (built from the SDK models, field set from F2); replaced or complemented by `RECORDED_DEMO` frames after the probe
- [ ] all new test files listed in F7
- [ ] no framework install needed

### Blocking-human steps (connected machine), each with prerequisites and measurable acceptance
1. **C1 O-18-01 ratification** (this machine possible, human): table from the "Ratification-table inputs" section, user value column filled only with the user's words, record `decisions/18-DEC-O-18-01.md` in the style of `16-DEC-O-07.md`.
2. **C2 documentation re-read** (connected or fetch-capable machine): repeat B1 to B12 and read the four unreadable event pages; update the Phase 18 SOURCES section; failures recorded as UNVERIFIED with the exact error.
3. **C3 live smoke on Demo** (prerequisites: Demo key pair in the shell session, no other process on the account, Demo WS URL decision O-18-04, ratified limits). Acceptance: (a) listenKey POST returns a key; (b) SDK `user_data` subscription completes; (c) after the smoke places and cancels one far LIMIT order, at least one `ORDER_TRADE_UPDATE` with `x=NEW` and one with `x=CANCELED` reach the project callback and become typed events; (d) keepalive PUT returns; (e) a forced transport drop leads to UNKNOWN, a REST snapshot, then LIVE, with the measured gap in the evidence; (f) `DELETE` then `PUT` records the error code (A2); (g) captured logs contain no key, secret, signature or listenKey; (h) evidence JSON written with schema name and version.
4. **C4 probe `--execute`** per D-16 (O-18-03 phrase typed by the user; O-18-04 environment). Acceptance: every D-16 case is `OBSERVED` with the exact `(class, code, message)` and frames, or `NOT_OBSERVED` with the reason; cleanup leaves zero open orders, zero open algo orders and a flat position; before/after account state recorded.

## Security Domain

(`security_enforcement` is not set to false in `.planning/config.json`; section included.)

### Applicable ASVS categories
| ASVS category | Applies | Standard control |
|---------------|---------|------------------|
| V2 Authentication / credentials | yes | env or file-path loader, separate TESTNET/DEMO and LIVE names (OPS-06), no CLI arguments, `repr=False` secrets as in `RehearsalCredentials`, key permission attested by the operator (no withdrawal, IP allowlist) |
| V3 Session management | yes (listenKey) | the listenKey is a credential: never logged, never in evidence, closed on stop, recreated after -1125 |
| V4 Access control | partly | environment/host guard and LIVE enablement state; Demo and live keys cannot cross |
| V5 Input validation | yes | WebSocket frames are untrusted input: strict dict parsing, Decimal/UTC validation, anomalies journaled; SDK `max_msg_size` is 20 MB |
| V6 Cryptography | yes | HMAC signing and TLS stay in the SDK/aiohttp; do not pass `ssl=False` (test), no hand-rolled crypto |
| V7 Error handling and logging | yes | `src/ops/redaction.py` for every path; SDK root-logger INFO lines (listenKey, `Received message` frames with account data) must go through `RedactingFilter` or be silenced |
| V14 Configuration | yes | exact-match host table, one SDK construction site, no environment inferred from a host |

### Known threat patterns
| Pattern | STRIDE | Standard mitigation |
|---------|--------|---------------------|
| Mainnet/Demo mix-up (REST on one, WS on the other) | Tampering / EoP | guard asserts every URL of the client against one environment row; AST single-construction test; transport-level host test |
| Credential or listenKey leak through SDK logs and exception text (`NetworkError` embeds the URL incl. `signature=`) | Information disclosure | redactor extended with runtime registration; grep tests on captured output; evidence post-write scan |
| Replayed, duplicated or reordered frames | Tampering | idempotent key `(order_id, exchange_trade_id)`; `z` integrity check; REST authority |
| Fabricated state from a malformed or unknown event | Tampering | anomaly path, never coercion (D-05) |
| Blind retry of a placement after an ambiguous failure | Tampering (duplicate order) | placement never retried; status-unknown path to probe-by-client-id |
| IP ban from reconnect storms or polling | Denial of service | bounded backoff, no retry on 418, `retry_after` honored, keepalive cadence far below any rate limit (weight 1) |
| Evidence files leaking secrets into the repository | Information disclosure | scrub before and after write; probe writes under `.planning/phases/18-*/` only after scan |
| Exchange-supplied text (`rm`, error messages) treated as instructions | Spoofing / EoP | text is data: journaled scrubbed, never parsed for decisions |

## Recommended plan decomposition (for the planner; no owner decision is made here)

Parallelization is enabled in `.planning/config.json`; granularity is fine. Plans are self-contained for an executor on a connected machine and cite repository files only (the CONTEXT machine rule).

| Wave | Plan (suggested) | Network | Depends on | Notes |
|---|---|---|---|---|
| 0 | 18-01 Facts and docs: first task D-19 re-read (executor), new SOURCES.md section, BINANCE.md/EXECUTION_SPEC wording within the P25 gate constraints | fetch only | none | task 1 of the first plan, as D-19 requires |
| 0 | 18-02 O-18-01 table generation plus **blocking-human checkpoint C1** (also O-18-04 environment question and the F3 flagged rows) | none | none | gates 18-06 values, 18-07, 18-09 |
| 1 | 18-03 Error taxonomy, SDK normalizer, stub-session contract test, regex/message removal, category-based cancel retry, rewrite of the not-found tests | none | none | independent of numbers except the 418/429 fallback wait |
| 1 | 18-04 Algo status table, manager wiring (lines 1058, 1096), docs rows | none | none | |
| 1 | 18-05 Event dataclasses and dict parsers, `FillEvent` commission extension, replay test; **design-review gate** for the costly-to-reverse types (D-01) | none | none | keep types in a tracer-first slice, then parsers |
| 1 | 18-06 Client config layer: environment enum, host table, generalized guard (REST + streams + WS-API), credential loader + redactor registration, `ClientLimits` with no defaults, pure drift function; rehearsal script reuse | none | structure: none; values: 18-02 | |
| 2 | 18-07 SDK user-data adapter and supervisor, fakes bound by contract tests, name forgetting, SDK log bridge, redaction of listenKey | none | 18-05, 18-06, 18-02 | |
| 2 | 18-08 Persistence: G4-043 store methods, G4-034 journal evidence events | none (PG tests need `TEST_DATABASE_URL`) | 18-05 | |
| 2 | 18-09 `recv_window` and `retries=0`/timeout plumbing through `binance_usdm.py` and `binance_public.py` calls | none | 18-06, 18-02 | |
| 3 | 18-10 Smoke script and probe script (dry-run default, evidence schema, shared guard, raw-frame tap) with dry-run tests | none | 18-06, 18-07 | |
| 4 | 18-11 **blocking-human C2 + C3** doc re-read and live Demo smoke | yes | 18-10, 18-02 | acceptance listed under Validation Architecture |
| 4 | 18-12 **blocking-human C4** probe `--execute` | yes | 18-11 (SDK route proven or fallback chosen), O-18-03 | user types the phrase |
| 5 | 18-13 Evidence consumption: recorded fixtures into parser tests, `BinanceSemanticsFakeAdapter` correction (D-17), SOURCES/BINANCE updates, DECISIONS row text for the user (D055 stays OPEN), conditional direct-`aiohttp` transport task if C3 failed | none | 18-12 | |
| 5 | 18-14 Phase gate: traceability for EXEC-05/EXEC-01/EXEC-02/OPS-02 (evidence-level notes unchanged: Demo-proven evidence for EXEC-01/EXEC-02/OPS-02 stays with Phases 24 to 26), full suite | none | all | |

Dependencies that the planner must not break: nothing that needs a ratified number runs before C1; nothing assumes a probe fact before C4 (the fake keeps its documented assumptions until then, and the plan says so); smoke and probe never run concurrently with a live supervisor on the same account (P7).

## Sources

### Primary (HIGH for the SDK and repository facts)
- Installed SDK source read 2026-10-15: `binance_sdk_derivatives_trading_usds_futures/derivatives_trading_usds_futures.py`, `websocket_streams/websocket_streams.py`, `websocket_streams/models/{user_data_stream_events_response,order_trade_update,order_trade_update_o,algo_update,algo_update_o,account_update,account_update_a,account_update_ab_inner,account_update_ap_inner,listen_key_expired,margin_call,margin_call_p_inner,trade_lite,conditional_order_trigger_reject,account_config_update*}.py`, `rest_api/api/{user_data_streams_api,trade_api}.py`, `websocket_api/api/user_data_streams_api.py`; `binance_common/{websocket,utils,errors,configuration,constants}.py`.
- Repository files read: `src/adapters/binance_usdm.py`, `paper_ws.py`; `src/paper/supervisor.py`, `src/paper/market_inputs.py`; `src/execution/fill_monitor.py`, `manager.py` (ranges), `intent_recovery.py` (range); `src/persistence/entities.py`, `execution_state.py`, `src/domain/{journal,order,fill}.py`, `src/ops/redaction.py`, `src/ops/health.py` (range); `src/data/collector.py` (range); `scripts/demo_rehearsal.py` (ranges), `scripts/paper_ws_smoke.py` (ranges), `scripts/decision_alignment/exchange.py`; `tests/test_paper_ws_contract.py`, `tests/paper_ws_fakes.py` (range), `tests/support/fake_binance_exchange.py`, `tests/test_adapter_not_found_mapping.py`, `tests/test_demo_rehearsal_safety.py` (range); `docs/SOURCES.md`, `docs/DECISIONS.md` (D044, D051, D055, D061 rows), `docs/trading/EXECUTION_SPEC.md` (6.1, 9), `docs/integration/BINANCE.md` (greps), `docs/operations/SECURITY_AND_OPERATIONS.md` (greps); `.planning/phases/09-live-execution-rollout/09-DEMO-REHEARSAL-FINDINGS.md`, `09-EXCHANGE-FACTS.md`; `.planning/phases/16-paper-runtime-composition/decisions/16-O-07-table.md`, `16-DEC-O-07.md`, `evidence/16-21-ws-smoke-live.json`; `.planning/ROADMAP.md` Phase 18, `.planning/REQUIREMENTS.md`, `AGENTS.md`, `pyproject.toml`, `uv.lock` (greps).

### Secondary (MEDIUM): documentation read through WebFetch 2026-10-15
- developers.binance.com pages listed in the Fetch log B1 to B4, B6 to B12.

### Tertiary (LOW-MEDIUM): search summaries, flagged
- WebSearch summaries of the Event-Algo-Order-Update, Event-Order-Update and Event-Balance-and-Position-Update pages (B5a, B5b); an earlier-session Wayback transcription (09-EXCHANGE-FACTS Fact 2). No Binance fact comes from memory.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, no new dependency; versions from `uv.lock`.
- Architecture: MEDIUM-HIGH, SDK behavior read from source; the live delivery of `/private` events through the SDK route is the one structural unknown.
- Pitfalls: MEDIUM-HIGH, most derived from installed source; P2, P14, P15, P21 depend on live behavior.
- Binance documentation facts: MEDIUM, summaries only, four event pages unread, nothing verified live.

**Research date:** 2026-10-15
**Valid until:** 2026-10-22 for Binance documentation facts (the docs changed several times in 2026: 2026-03-05, 2026-07-21, 2026-08-07, 2026-08-21); SDK facts valid while `uv.lock` pins 17.4.0 / 4.4.0.

## UNVERIFIED register (consolidated; every item needs a connected-machine read or probe)

1. Payload pages for `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE` and `listenKeyExpired`: fetch failed (landing-page shell returned for `/user-data-streams/Event-Algo-Order-Update`, `/Event-Order-Update`, `/Event-Balance-and-Position-Update`, `/Event-Listen-Key-Expired` and the catalog `ws-streams/user-data-streams` page; one retry per family, same result). Status list and field facts rest on SDK models, a 2026-01-13 Wayback transcription from an earlier session and WebSearch summaries.
2. JSON `SUBSCRIBE` parameter format for a listenKey on `/private`, the message envelope, and whether `events=` is required.
3. Whether Demo serves `POST /fapi/v1/listenKey` and a user-data socket; the Demo WebSocket URL (`wss://demo-fstream.binance.com` is a single-source summary); what `TESTNET` denotes.
4. The REST `algoStatus` value list.
5. The error code returned by `PUT /fapi/v1/listenKey` for a closed or expired key (assumed -1125); the duplicate `clientAlgoId` code; id reuse after FILLED/CANCELED; the Demo behavior of every D055 case; -4509 is Demo-observed only and absent from the error-code page summary.
6. Child-order identity (`c`, `i`) of a triggered algo order.
7. A new-connection rate limit; ordering of `ACCOUNT_UPDATE` versus `ORDER_TRADE_UPDATE`; whether Binance sends `Retry-After`; the maximum `recvWindow` on endpoints other than algoOrder and positionSide/dual.
8. Whether a bare number (not a string) can arrive in money fields.
9. Futures Demo key provisioning steps.
