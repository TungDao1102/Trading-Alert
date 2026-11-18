# Lane M07: binance_adapters

## Scope
`src/adapters/binance_*.py`, `src/domain/{exchange_errors,algo_status,stream_records}.py`, `config/binance/*`
at snapshot `55885b9`. Finding IDs G-0700..0799. Exchange facts already checked by lane X10
(`lanes/exchange_facts.md`, F01..F30) are reused, not redone.

## Coverage
| File | Level | Note |
|---|---|---|
| src/adapters/binance_errors.py | DEEP_READ | whole file; mapping exercised by `tmp/binance_adapters/probe_wire.py errors` |
| src/domain/exchange_errors.py | DEEP_READ | whole table and `classify` / `retry_eligible` / `rate_limit_decision`; code-vs-doc text already done by X10 (F04..F16) |
| src/adapters/binance_client.py | DEEP_READ | whole file |
| src/adapters/binance_ratelimit_gate.py | DEEP_READ | whole file; probe `probe_wire.py gate` |
| config/binance/binance-limits-v1.toml | DEEP_READ | all 27 keys |
| src/adapters/binance_usdm.py | DEEP_READ (lines 100-280, 676-930, 983-1660, 2062-2516) / NORMAL_READ (dataclasses 280-676, account/income readers 1657-2060) | every order-path method traced to the wire with a fake HTTP session |
| src/adapters/binance_clock.py | DEEP_READ | whole file; arithmetic compared with X10 F01 |
| src/adapters/binance_limits.py | NORMAL_READ | docstring, policy dataclasses, loader outline; values read from the TOML |
| src/adapters/binance_public.py | DEEP_READ (gate wrapper 300-460, mark/last price 547-631, server_time, exchange_info 743-885) / NORMAL_READ (klines, OI, funding, filter helpers 893-1033) | market-data history readers belong to the data lane |
| src/adapters/binance_userdata.py | DEEP_READ (1-290, 440-867) / NORMAL_READ (log bridge and noise guard 290-440) | SDK receive loop read in `binance_common/websocket.py:272-410` |
| src/adapters/binance_userdata_events.py | DEEP_READ (vocabularies, builders 935-1185, routing 1187-1446) / NORMAL_READ (event dataclasses 360-735) | probe `probe_events.py`: 25 wire payloads through the SDK model and the parser |
| src/adapters/binance_userdata_router.py | DEEP_READ (326-375, 496-727, 804-940) / NORMAL_READ (value types, journal helpers) | |
| src/adapters/binance_userdata_supervisor.py | DEEP_READ (100-160, 386-914) / NORMAL_READ (commands, constructor 200-385) | no probe run (asyncio state machine; read only) |
| src/adapters/binance_probe.py | NORMAL_READ (docstring, 733-862, method list) | Demo-probe tool; built in the live process but only used for a gate identity check (`src/live/wiring.py:1457`) |
| src/domain/algo_status.py | DEEP_READ | whole file; statuses compared with the official page text saved by X10 (`f_userdata.md:366-384`) |
| src/domain/stream_records.py | NORMAL_READ | docstring and outline (journal record builders) |
| config/binance/README.md | NORMAL_READ | file format section |
<!-- COVERAGE-END -->

## Verified Safe Areas
Probe for all rows below: `tmp/binance_adapters/probe_wire.py` (fake `requests.Session.request`, no network), output in `tmp/binance_adapters/probe_wire.out`.

- **The SDK never re-sends a request (placement included).** `config/binance/binance-limits-v1.toml:12` `sdk_retries = 0` → `build_sdk_client` passes `retries=limits.sdk_retries` (`src/adapters/binance_client.py:462`). In the installed SDK (`binance_common/utils.py:449` `while attempt <= retries`, `:314-338` `should_retry_request`) a retry needs `retries_left > 0` AND method GET/DELETE, so a POST is never retried by the SDK at any setting, and with 0 nothing is. Probe: every error case shows `posts=1`.
- **One POST per placement call in the adapter.** `place_entry`, `place_market_close`, `place_algo_protective` each call `_sdk_call` once (`binance_usdm.py:1378,1467,1563`); `_sdk_call` (`:883-916`) has no loop and re-raises the original exception. Only the two cancels use tenacity, and only for `STATUS_UNKNOWN` (`:252-262`, `:918-930`).
- **Wire parameters match the endpoint and SDK names.** Captured query strings: `POST /fapi/v1/order ? symbol,side,type=LIMIT,positionSide,timeInForce=GTD,quantity=0.010,price=84000.10,newClientOrderId,goodTillDate,recvWindow=5000`; `POST /fapi/v1/algoOrder ? algoType=CONDITIONAL,...,triggerPrice=83000.00,workingType=MARK_PRICE,closePosition=true,clientAlgoId`; a partial TP carries `quantity=0.005&closePosition=false&reduceOnly=true`; emergency close `type=MARKET&positionSide=BOTH&reduceOnly=true&quantity=0.010`; `DELETE /fapi/v1/algoOrder ? clientAlgoId`; `GET /fapi/v3/positionRisk`; `GET /fapi/v1/openAlgoOrders`. `recvWindow=5000` is on every signed call. Decimals go out as fixed-point text (`Decimal("1E-3")` → `quantity=0.001`, `Decimal("8.4E+4")` → `price=84000`), never as float or exponent (`_decimal_to_wire`, `:678-696`).
- **No "definitive" class is given to an ambiguous answer.** Probe `errors`: 5xx (also a 503 whose body says -1008), 408, a read timeout → `STATUS_UNKNOWN`; a 400 with an unlisted code (-9999, -4131, -2025), a 400 whose `code` is text or whose body is HTML, a 200 with a non-JSON body (`JSONDecodeError`) and a 200 that does not fit the strict SDK model (`AttributeError`) → not `REJECTED_DEFINITIVE` and not `ORDER_ABSENT` (`UNKNOWN_EXCHANGE_ERROR` / a non-SDK exception). `REJECTED_DEFINITIVE` is reached only through an HTTP 400/404 with a listed int code (`exchange_errors.py:749,782-786`); an HTTP 400 is a refusal by the exchange, so no listed code can hide a live order.
- **"Absent" is never inferred from text or from an unknown answer.** `_is_order_absent` (`binance_usdm.py:234-244`) needs category `ORDER_ABSENT`, which exists only for -2011/-2013 on QUERY and CANCEL (`exchange_errors.py:249,357-375`); the same codes on a PLACEMENT classify `UNKNOWN_EXCHANGE_ERROR`.
- **Exception text does not steer a decision.** `error_facts_from_exception` reads class, int `status_code`, int `retry_after` (`binance_errors.py:96-113`); the one text read (`_ban_until_epoch_ms`, `:77-93`) is fenced to 418 + code -1003 and yields a number that only the gate uses, and only when the owner margin is set.
- **No silent mainnet default for a signing client.** `build_sdk_client` gives an unrequested surface an `.invalid` URL (`binance_client.py:177-180,411-424`) and `assert_environment` re-reads every surface (`:549-586`); LIVE needs `is_disabled is False` (`:406-408`). There is no default environment (`parse_environment`, `:118-127`).
- **A signed call cannot run without the ratified recvWindow and the shared gate.** `_require_signed_policy` (`binance_usdm.py:860-866`) raises a `PreSendRefusal` first; constructor refuses a policy without a gate or with a different policy (`:818-830`).
- **A missing amount is never read as zero / flat.** `_row_to_position_snapshot` raises on a missing `positionAmt` (`:2144-2148`); `_require_quantity` raises on a missing quantity; identity fields are required on every row and every placement answer (`:2072,2102,2215,2239,2263`).
- **Clock-drift limits sit inside the exchange rule.** Exchange rule (X10 F01): refuse when `timestamp >= serverTime + 1000` or `serverTime - timestamp > recvWindow` (5000). Project: ahead limit 500 ms, behind limit 1000 ms, half the round trip added (`binance_clock.py:124-129`, TOML `[drift]`). Worst accepted case: host ahead 500 ms incl. uncertainty < 1000; host behind 1000 ms < 5000. A never-measured, failed, out-of-limit, stale (300 s) or -1021-contradicted verdict blocks NEW entries only (`:239-257`, `binance_usdm.py:868-881`); stops, cancels and closes are not blocked by the clock guard.
- **User-data events: documented vocabulary only, nothing coerced.** Probe `probe_events.py` (wire dict → SDK `parse_user_event` → `parse_stream_message`, output `probe_events.out`): NEW / TRADE / EXPIRED / EXPIRED_IN_MATCH become `OrderUpdateEvent`; only `x=TRADE` with a positive `l` becomes a fill; an unknown order status, an unknown algo status, an unknown event name, a liquidation (`x=CALCULATED`), a forced close (`c` = `autoclose-…` / `adl_autoclose`) and MARGIN_CALL become anomalies, never events; a crossed FUNDING_FEE `ACCOUNT_UPDATE` without `P` parses. The lists equal the official page (`f_userdata.md:147-161,372-384`). The recorded Demo `ALGO_UPDATE` shape (`tests/fixtures/phase18/recorded_demo/probe/*-ALGO_UPDATE.json`: `ai: ""`, no `rm`) parses.
- **Only a resting stop confirms protection.** `is_protection_confirmed` is true for `NEW` only (`algo_status.py`, `classify_algo_status` / `is_protection_confirmed`); TRIGGERING / TRIGGERED / FINISHED / CANCELED are UNKNOWN, REJECTED / EXPIRED are TERMINAL_FAILED, anything unseen is UNKNOWN.
- **A gap in the stream is never silently bridged.** Close, SDK reconnect, listenKey expiry, keepalive failure (tolerance 1), queue overflow → state UNKNOWN; items received while not LIVE are held and released only after a REST snapshot, flagged `after_gap` (`binance_userdata_supervisor.py:550-559,706-714,768-818`). An overflow during the snapshot fails that attempt (`:788-791`). A dead pump/timer/control task halts instead of staying LIVE (`:449-461`).
- **listenKey handling.** The key is registered with the redactor before any use (`binance_userdata.py:271,565,598,627`); a rebuild proves the stored key with a keepalive and takes a new key on -1125 (`:758-776`); no listenKey call is retried in the port (`:239-263`).
- **Fills are idempotent on the stream path.** A fill is keyed `(exchange order id, trade id)` (`binance_userdata_events.py:1419-1446`); the accumulated quantity `z` is cross-checked against the unique `l` sum and a mismatch is journaled and surfaced (`binance_userdata_router.py:346-364,615-666`).
- **No timeout wrapper cancels an in-flight placement.** `grep "wait_for(|asyncio.timeout("` over `src/execution`, `src/live`, `src/reconcile`: no hit; the only time bound of a REST call is the SDK's 5 s `requests` timeout inside the worker thread.
- **Demo-only observations coded as facts (list asked by the lane; each is labelled as such in the code):** -4509 for a closePosition stop while flat (`exchange_errors.py:404-416`); -4116 for a duplicate `clientAlgoId` (`:377-387`); -2011 / -2013 on the algo endpoints (`:357-375`); -1125 on a keepalive after a delete (`:343-355`); -1106 for reduceOnly together with closePosition (`:441-458`); the Demo stream host `wss://demo-fstream.binance.com` (`binance_client.py:157`); the `ALGO_UPDATE` frame shape (recorded fixtures); the income paging behaviour ("Demo answered the same rows to every page", `binance_usdm.py:2044-2048`); FUNDING_FEE income "UNVERIFIED on Demo (0 rows)" (`:2007-2008`). Never observed anywhere: the 13-digit form of the 418 ban end (`binance_errors.py:59`) and a Futures `Retry-After` header (X10 F03).
<!-- SAFE-END -->

## Decision review
| Decision / doc rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D072 (5) / D-10: classify by (SDK class, int code, call kind), never by message text; unknown code → UNKNOWN_EXCHANGE_ERROR | SOUND | installed SDK (`binance_common/utils.py:461-505`), probe `errors` | text can change and can carry request data; every unlisted or malformed answer lands on the ambiguous side |
| D080 / CR-09: a placement is never re-sent; `sdk_retries = 0` | SOUND | SDK retry rule (`utils.py:314-338`); client ids are unique among OPEN orders only | a re-send after an ambiguous answer can double a filled order; the SDK itself never retries a POST |
| D072 (4): only algo status NEW confirms protection | SOUND | official status text (`f_userdata.md:372-384`); change-log 2025-11-06 "no margin check before the conditional order gets triggered" (X10 F30) | strictest reading; note that even NEW does not guarantee execution at trigger |
| D072 (1) drift limits 500 ms ahead / 1000 ms behind, recvWindow 5000 | SOUND | exchange rule X10 F01, arithmetic | both limits are inside the exchange window with margin |
| D072 (6) + D081 Q4: a 429 pauses EVERY REST call, protective stop, cancel and emergency close included, no exemption (120 s without Retry-After) | DOUBTFUL | exchange docs (`f_general.md:38-41,154-159`), probe `gate`, risk practice | see G-0701: self-imposed for twice the one-minute weight window and it covers risk-reducing calls; the alternative (let one risk-reducing call through) has its own cost. Owner decision |
| D072 (1) `rate_limit_418_no_retry_after_wait_seconds = 259200`, with D083 (body ban end) built but off until `rest_gate.ban_end_clock_margin_ms` is set | DOUBTFUL | exchange docs (bans "from 2 minutes to 3 days"), probe `gate` | see G-0700: the fallback is the longest possible ban; the refinement that would use the real end time ships switched off |
| D083 exception: one 13-digit number read from the 418 text | SOUND (as bounded) | code fence (`binance_errors.py:77-93`, `binance_ratelimit_gate.py:334-348`) | future-only, capped, never classifies; the 13-digit format itself is unverified |
| -1008 is SYSTEM_THROTTLED, never recorded in the gate (quick task 261020-g1a) | SOUND in effect / fact wrong | X10 F05-F06 (G-2200) | -1008 arrives under HTTP 503, so the table row is unreachable; a 503 classifies STATUS_UNKNOWN, which also pauses nothing. Not re-reported here |
| Stream is a hint, REST is the authority (D-05); events held over a gap until a REST snapshot | SOUND | official ordering guarantee (X10 F21), SDK receive loop | frames can be lost in the SDK and across reconnects; a snapshot is the only repair |
| A halted stream waits for an explicit `request_resync()`; no automatic resync (supervisor docstring; Phase 25 plan 25-29 Q-K `/resync_stream`) | DOUBTFUL | owner goals (part-time), limits 7 attempts / 120 s | see G-0702: every outage longer than about two minutes needs the owner |
| listenKey keepalive every 1800 s, tolerance 1 | SOUND | X10 F19 (key valid 60 min) | one failed keepalive still leaves 30 min before expiry and triggers a re-key |
| Forced-close / liquidation / MARGIN_CALL frames are anomalies that only trigger a REST query (`src/live/feeds.py:34-40`) | CANNOT_JUDGE | — | right only if the reconcile that follows treats a vanished position as closed by the exchange; that is the reconcile lane |
<!-- DECISIONS-END -->

## Findings
### G-0700
- **ID:** G-0700 · **Severity:** LOW now (Demo, placement disabled) / HIGH on mainnet with placement enabled · **Confidence:** CONFIRMED for the code path (probe); PROBABLE for the trigger (it needs a 418 that carries no usable `Retry-After`, which the Futures docs neither promise nor exclude, X10 F03)
- **Classification:** DESIGN · **Category:** rate-limit gate / protection availability · **Component:** `RestRateLimitGate`, D083
- **File:** `src/adapters/binance_ratelimit_gate.py` · **Lines:** 334-348, 350-393 (also `config/binance/binance-limits-v1.toml:17`, `config/execution/execution-limits-v1.toml:80`, `src/live/exchange.py:195-200`)
- **Rule:** DECISIONS D072 (6), D083 (4); AGENTS.md "Fail closed" and the invariant "no new entry opens while any position is unprotected"
- **Known-prior:** KNOWN:D083 / AGENTS.md "Still open (owner): … `rest_gate.ban_end_clock_margin_ms`", but described there as harmless ("it only refines the 418 ban wait, so while it is NOT_CONFIGURED the ratified fallback wait applies and nothing else changes", `execution-limits-v1.toml:33-34`). Reported because the consequence is more severe than recorded.
- **Evidence:** `_body_ban_end`: `if margin is None or ban_until_epoch_ms is None or retry_after_seconds is not None: return None` (`:343-344`); the shipped margin is `"NOT_CONFIGURED"`. Then `end = now + timedelta(seconds=decision.wait_seconds)` with the 418 fallback `rate_limit_418_no_retry_after_wait_seconds = 259200`. `check()` "has no argument: no request category is exempt" (`:240-241`); "there is no method that clears a restriction" (`:33`); the deadline is persisted and restored at start (`:440-496`). Probe (`probe_wire.py gate`): a READ answered 418 with body "IP(…) banned until <now + 2 min>" and no `Retry-After` → `GateRestriction(reason='IP_BAN_418', … remaining_seconds=259200)`; 24 h later `place_market_close` and `place_algo_protective` → `RateLimitBanActive … retry_after_seconds=172800`, nothing sent.
- **Expected:** After a ban whose end the exchange states (official text "IP banned until %s"; bans last "from 2 minutes to 3 days"), the process regains REST shortly after that end, at least for risk-reducing calls.
- **Actual:** One 418 without a usable header stops every REST call of the process for 3 days: protective stop, entry cancel, emergency close, reconcile reads, clock measurement and the listenKey keepalive (so the user-data stream also dies after 60 min, `binance_userdata_supervisor.py:628-631`). A restart does not clear it. The code that would use the real end time exists but is switched off.
- **Reproduction:** `tmp/binance_adapters/probe_wire.py gate` (output in `probe_wire.out`, section `##### gate`).
- **Impact:** Example: a GTD entry rests on the exchange; a 418 arrives (the data jobs on the same IP "do not hold this gate", `:46-49`, so another process can earn the ban); the real ban ends after 2 minutes; the entry fills after 10 minutes. The fill-driven stop cannot be placed, the entry cannot be cancelled and the emergency close is refused, for up to 3 days, unless the owner acts by hand on Binance. Positions that already have a resting stop keep it.
- **Why tests miss it:** the tests pin the ratified behaviour (fallback wait, no exemption, margin off); none asks what the position state is while the gate is closed for the fallback time.
- **Remediation (owner decision, see Owner decisions 1):** set the margin so the body time is used; and/or lower the 418 fallback; and/or give the operator an audited way to clear a ban deadline after checking Binance; look for a Futures `Retry-After` in the first real 418 as D083 already asks.

### G-0701
- **ID:** G-0701 · **Severity:** LOW now / MEDIUM on mainnet · **Confidence:** CONFIRMED (probe)
- **Classification:** DESIGN · **Category:** rate-limit gate / protection availability · **Component:** `BinanceUsdmAdapter._sdk_call`, `RestRateLimitGate`
- **File:** `src/adapters/binance_usdm.py` · **Lines:** 894-906 (also `src/domain/exchange_errors.py:257-289,863-870`, `config/binance/binance-limits-v1.toml:18`)
- **Rule:** DECISIONS D072 (6), D081 (Q4: "no bypass of a 429/418 pause")
- **Known-prior:** KNOWN:D081 / `19-OWNER-GAPS.md` row Q4 (decided: durable pending protective actions, no bypass). Two details are not in that record: the pause is also started by an HTTP **400** with code -1003 or -1015 (`_every(_C.RATE_LIMITED)`), and the 120 s fallback is twice the longest request-weight window the docs describe (one minute).
- **Evidence:** `gate.check()` is the first statement of every signed call (`:895`); `if category in _RATE_LIMIT_CATEGORIES: gate.record(...)` (`:901-906`). Probe: one 429 on `snapshot_positions` (a read) → one second later `place_algo_protective`, `place_market_close` and `cancel_normal_order` all raise `RateLimitPauseActive … retry_after_seconds=120`; a 400/-1015 ("Too many new orders", the per-account ORDER limit) on a placement → `gate=('RATE_LIMIT_PAUSE_429', 120)`.
- **Expected (yardstick):** risk practice puts risk-reducing orders ahead of every other traffic; the exchange itself exempts reduce-only / close-position orders from its -1008 overload throttle (`f_general.md:74-87`).
- **Actual:** any 429 met by any caller (a read, a keepalive, a mark refresh) delays the stop of a position that fills in that window, its entry cancel and its emergency close by up to 120 s (or the server's `Retry-After`).
- **Reproduction:** `probe_wire.py gate` and `probe_wire.py errors`.
- **Impact:** bounded but real: a position can be without a stop for two minutes for a reason that has nothing to do with that order. Counter-argument (why this is DOUBTFUL and not WRONG): after an IP-weight 429 the exchange would refuse the protective call too, and sending while limited is how a 429 becomes a 418.
- **Why tests miss it:** the tests assert the refusal as the wanted behaviour.
- **Remediation (owner decision 2):** choose between the present rule and one bounded risk-reducing attempt during a 429 pause (never during a 418); separate the order-count code -1015 from the IP pause; derive the fallback from the documented window.

### G-0702
- **ID:** G-0702 · **Severity:** LOW now / MEDIUM on mainnet · **Confidence:** CONFIRMED (no caller) / PROBABLE (operational consequence, composition not traced by this lane)
- **Classification:** GAP · **Category:** user-data stream recovery · **Component:** `UserDataSupervisor`
- **File:** `src/adapters/binance_userdata_supervisor.py` · **Lines:** 405-411, 820-831, 884-888 (limits: `config/binance/binance-limits-v1.toml:31-34`)
- **Rule:** supervisor contract "an exhausted retry leaves the state UNKNOWN, reports the failure and waits for an explicit `request_resync()`" (module docstring lines 12-14)
- **Known-prior:** KNOWN:`.planning/phases/25-demo-integration-test-campaign/25-29-PLAN.md` (Q-K `operator-resync`, owner 2026-11-08: a Telegram `/resync_stream` command is planned; the plan itself states "`git grep -n "request_resync" -- src/live` … baseline at HEAD: none"). Reported because at this snapshot the documented recovery path has no caller, and because the planned fix is manual only.
- **Evidence:** `grep -rn "request_resync" src scripts` returns only the supervisor's own definition and docstrings. A reconnect is bounded by `reconnect_max_attempts = 7` or `reconnect_max_delay_seconds = 120`, a snapshot by 7 attempts (`_bounded`, `:833-872`), after which `_halt` sets UNKNOWN and reports once. `src/live/feeds.py:26-33` states the loop turns a halt into SAFE_MODE `USER_DATA_STREAM_HALTED` and "only the operator leaves SAFE_MODE".
- **Expected:** a halted stream can be recovered without restarting the process, as the module documents.
- **Actual:** after any outage longer than about 120 s (or a ban, an internal error, a dead task, a listenKey failure) the stream stays UNKNOWN until the process is restarted.
- **Reproduction:** `grep -rn "request_resync" src scripts` in the snapshot.
- **Impact:** availability, not a direct loss (the halt fails closed). On a host whose network is recorded as flaky (AGENTS.md "Network is flaky") each such outage needs the owner: restart, then leave SAFE_MODE by hand. Whether stops and closes keep working from REST while the stream is halted was not traced here (see Open Questions).
- **Why tests miss it:** supervisor tests call `request_resync()` themselves; no test asserts that the composition has a caller.
- **Remediation:** wire a caller (the planned operator command at least); consider a slow automatic resync, since `_resync` already runs one bounded cycle and refuses during a ban (owner decision 3).

### G-0703
- **ID:** G-0703 · **Severity:** LOW now / MEDIUM on mainnet · **Confidence:** SUSPICIOUS (parser behaviour CONFIRMED by probe; that the exchange ever sends the shape is not observed)
- **Classification:** GAP · **Category:** user-data parser robustness · **Component:** `binance_userdata_events`
- **File:** `src/adapters/binance_userdata_events.py` · **Lines:** 807-819, 1060-1070, 1089
- **Rule:** D-05 "never coerces" (module docstring); EXECUTION_SPEC protection is fill-driven
- **Known-prior:** none found
- **Evidence:** `_text_value`: `if not isinstance(value, str) or value == "": raise _invalid(path, "a non-empty string", value)`; `_text_opt` uses it for every optional text (`rm`, `act`, `V`, `pm`, `wt`, `ot`, `N`, `M`, `er`). Only `ai` has an empty-string rule (`:1062-1067`, "the empty string means 'not triggered yet'"). The recorded Demo frames show that Binance does use `""` for "nothing" (`"ai": ""` in 16 of 16 recorded ALGO_UPDATE frames) and that `rm` is absent on Demo. Probe (`probe_events.py`): the recorded shape plus `"rm": ""` → `ANOMALY FIELD_VALIDATION field=o.rm`; plus `"act": ""` → `ANOMALY FIELD_VALIDATION field=o.act`.
- **Expected:** an empty optional diagnostic text does not discard the status of a stop or the fill of an order.
- **Actual:** the whole frame becomes an anomaly: an `ALGO_UPDATE` NEW (the stop confirmation) or an `ORDER_TRADE_UPDATE` TRADE (the fill) is not routed; the live queue treats a `STREAM_ANOMALY` item as "just triggers a REST query" (`src/live/feeds.py:34-35`).
- **Reproduction:** `tmp/binance_adapters/probe_events.py`, rows "algo NEW with rm empty text" / "with act empty text".
- **Impact:** if mainnet (or a later Demo release) sends one of these fields as `""`, every such event is lost from the stream path and the system runs on REST polling only; `fills_reader=None` in `src/live/wiring.py:805-812` says no REST read of the fills of one order exists. Demo evidence cannot exclude this (charter: what Demo cannot show).
- **Why tests miss it:** parser fixtures are the recorded Demo frames and synthetic frames written from the same reading; none has an empty optional text other than `ai`.
- **Remediation:** treat `""` like an absent value for optional free-text fields (as already done for `ai`), keep strictness for identity, status and money fields.

### G-0704
- **ID:** G-0704 · **Severity:** LOW now / LOW on mainnet · **Confidence:** CONFIRMED (code read)
- **Classification:** GAP · **Category:** user-data stream, silent frame loss · **Component:** `UserDataAdapter`, `UserDataSupervisor`, SDK receive loop
- **File:** `src/adapters/binance_userdata_supervisor.py` · **Lines:** 594-598 (also `src/adapters/binance_userdata.py:825-836`)
- **Rule:** router contract "Nothing is silently dropped or coerced" (`binance_userdata_router.py:22-24`); adapter contract "an exception inside the parser [becomes] a MALFORMED_PAYLOAD anomaly item" (`binance_userdata.py:665-667`)
- **Known-prior:** none found
- **Evidence:** (a) the SDK receive loop catches any exception raised while it prepares or delivers a frame, logs `Error in callback for key …` and emits the connection event `error` (`binance_common/websocket.py:383-385`); the supervisor ignores `error` while the socket is open: `if self._adapter.private_connection_open(): log.info("userdata.supervisor.error_on_open_connection_ignored"); return`. (b) `_on_raw_message` ends with `except Exception as exc: log.error("userdata.raw_callback_failed", …)`: no item is queued and the overflow flag is not set.
- **Expected:** a frame that could not be delivered marks a gap (state UNKNOWN → snapshot), like an overflow does.
- **Actual:** in both paths one frame is lost with a log line only; the stream stays LIVE.
- **Reproduction:** read the two code sites; no probe run.
- **Impact:** small: both need an unexpected exception (the normal parse errors are already turned into anomalies), and the periodic REST reconcile is the authority. It is the one place where the stream can lose a frame without the gap machinery noticing.
- **Why tests miss it:** tests inject parser failures (handled) rather than failures outside the parser.
- **Remediation:** count such a loss like an overflow (set the flag) so the supervisor resyncs.

### G-0705
- **ID:** G-0705 · **Severity:** INFO now / INFO on mainnet · **Confidence:** CONFIRMED
- **Classification:** DRIFT · **Category:** SDK boundary · **Component:** `src/live`
- **File:** `src/live/exchange.py` · **Lines:** 39 (also `src/live/stream.py:47`)
- **Rule:** AGENTS.md "`src/adapters/` | Binance + Telegram behind project-owned interfaces (SDK types never leave)"; `binance_usdm.py:761` "Adapter — single owner of SDK imports"
- **Known-prior:** none found
- **Evidence:** `from binance_common.configuration import ConfigurationWebSocketStreams` in both files (`grep -rn "^\s*(from|import) binance" src | grep -v "^src/adapters/"` gives exactly these two lines).
- **Expected / Actual:** the SDK configuration type is built outside `src/adapters`. No SDK response or model type leaves the adapters (checked: every adapter method returns a project dataclass).
- **Impact:** none on behaviour; the stated boundary is not exact and no guard test covers `src/live`.
- **Why tests miss it:** the import guards cover the pure packages, not `src/live`.
- **Remediation:** build the streams configuration behind a helper in `src/adapters`, or state the exception.
<!-- FINDINGS-END -->

## Owner decisions
1. **How long may the bot lock itself out after an IP ban (G-0700)?** Today: a 418 without a `Retry-After` header = 259200 s (3 days) with no REST at all, even when the answer itself says the ban ends in 2 minutes. Example: ban at 12:00 with body end 12:02; today the bot can next place a stop or close a position on day 4 at 12:00. With `rest_gate.ban_end_clock_margin_ms` set to, say, 60000 it would be 12:03. Options: set the margin (uses the exchange's own end time); lower the fallback; add an audited operator command that clears the deadline after the owner has checked Binance. The cost of a too-early return is a longer ban; the cost of a too-late one is an unprotected position.
2. **May a risk-reducing call go out during a 429 pause (G-0701)?** Today no: after one 429 anywhere, a stop, an entry cancel and an emergency close wait up to 120 s. Example: 0.01 BTC entry fills 5 s after a 429 that a read caused; the stop is sent up to 115 s later; a 1 % adverse move in that time is about 8.4 USDT on an 84,000 USDT price, with no stop behind it. The alternative (one attempt for a stop / reduce-only close during a 429 pause, never during a 418) risks turning the 429 into a ban. D081 chose the present rule; the numbers above were not part of that record.
3. **Should a halted user-data stream try again by itself (G-0702)?** Today: after 7 failed reconnects or 120 s the stream stops for good, the process enters SAFE_MODE and waits for a restart; Phase 25 plans a manual `/resync_stream`. Alternative: an automatic bounded resync every N minutes (the function already refuses during a ban). The owner is part-time; each halt otherwise costs the time until the owner sees the alert.
<!-- OWNER-END -->

## Open Questions
- **(exec_placement / exec_protection)** `cancel_normal_order` returns normally on -2011 / -2013 and logs `already_canceled` (`binance_usdm.py:1223-1235`). On the exchange -2011 on a cancel also means "already FILLED". The adapter result alone must never be read as "the entry did not fill"; `cancel_then_verify` exists in the execution layer, not checked here.
- **(exec_placement)** A successful POST whose answer does not fit the strict SDK model raises `AttributeError` from `place_entry` (probe `odd`: `'dict' object has no attribute 'symbol'`), and a 200 with a non-JSON body raises `JSONDecodeError`. Both are non-SDK exceptions (`NON_SDK` → `UNKNOWN_EXCHANGE_ERROR`), and the order may exist. The manager must treat every non-`PreSendRefusal` exception of a placement as ambiguous; verify there.
- **(exec_protection / live_composition)** While the gate is closed (G-0700, G-0701) and while the stream is halted (G-0702): what exactly keeps running for a position that fills in that window? `fills_reader=None` (`src/live/wiring.py:805-812`) says there is no REST read of the fills of one order.
- **(reconcile_safemode)** Liquidation, ADL and MARGIN_CALL frames only trigger a REST query (`src/live/feeds.py:34-40`). Does the reconcile that follows raise an alert that names a liquidation, or only a generic divergence? A `closePosition` stop that the exchange expires after a normal exit (EXPIRED = TERMINAL_FAILED, `binance_userdata_router.py:707-721`) emits `STREAM_ALGO_TERMINAL_FAILED` on every normal close: check that this is not noise that hides a real failed stop.
- **(live_composition)** `BinanceProbeAdapter` is built in the live process (`src/live/exchange.py:214`). It has unguarded `new_market_order`, `cancel_all_open_orders` and similar methods (no clock guard, no close-side check). Only `wiring.py:1457` reads it (gate identity). Confirm no other path reaches it.
- **(exchange_facts)** `symbol_lot_filters` downloads the whole `exchangeInfo` for one symbol on every call (`binance_usdm.py:1023`, `binance_public.py:769`) within the 5 s REST timeout; the response is strict-validated by the SDK for every listed contract, so one contract with a field of an unexpected type makes the SDK fall back to a raw dict and the adapter raise for the requested symbol too (same mechanism as probe `odd`). Not reproduced with real data.
- **(not a finding, edge)** `Retry-After: 0` on a 418 or 429 gives a zero-length restriction (`binance_ratelimit_gate.py:376-382`: `end = now`, `now < end` is false) while the `REST_GATE_BAN_ENTERED` alert is still sent. Not expected from the exchange.
- **Not inspected:** real mainnet answers (none exist); the 418 body and header on Futures; `binance_public.py` history readers and `binance_probe.py` in depth; the supervisor as a running state machine (read only, no probe); `scripts/demo_rehearsal.py` client builder (a second construction site named in `binance_client.py:7-8`).
<!-- OPEN-END -->

## DONE
