# Lane 5: integrations_external_apis (stage C, code)

## Scope

**Inputs read:**
- LANE_BRIEF.md
- AUDIT_CHARTER §11
- LANES.md: L5 and the STAGE C NOTE
- docs_exchange_facts.md: the "Exchange Facts for Code Audit" section is the yardstick
- docs_trading_soundness.md: Corrected Rules 1-24
- The findings lists of planning_decisions_07_17, requirements_docs_plan and docs_exchange_facts

**Code audited (SNAPSHOT 63ca176):**
- src/adapters/binance_usdm.py (full)
- src/adapters/paper_ws.py (full)
- src/adapters/telegram_notify.py (full)
- src/adapters/telegram_callbacks.py (full)
- The adapter call sites in:
  - src/execution/manager.py
  - src/execution/placement.py
  - src/execution/gates.py
  - src/execution/fill_monitor.py
  - src/reconcile/safe_mode.py
  - src/reconcile/sweeper.py
  - src/paper/supervisor.py
  - src/paper/loop.py
  - src/paper/notify.py
  - src/data/backfill.py

**Docs:** docs/integration/BINANCE.md, TELEGRAM.md, TRADINGVIEW.md.

**Installed SDK, read-only:**
- `binance_sdk_derivatives_trading_usds_futures` 17.4.0:
  - DerivativesTradingUsdsFutures
  - rest_api signatures, enums and response models
  - websocket_streams
- `binance_common` 4.4.0:
  - configuration.ConfigurationRestAPI defaults
  - utils.send_request / should_retry_request / serialization
  - errors

**Web (read-only):**
- https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code (-2011, -2013 and others)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Algo-Order

No Binance or Telegram API was called.

**Probes** (in `AUDIT\tmp\integrations_external_apis\`):
- `sdk_probe.py` / `sdk_probe_out.txt`: introspects every SDK method, enum and response model the adapter uses.
- `adapter_probe.py` / `adapter_probe_out.txt`: runs the real adapter against a fake rest_api that raises real `binance_common.errors.BadRequestError` objects.

## Coverage

| file | level | note |
|---|---|---|
| src/adapters/binance_usdm.py | DEEP_READ | every SDK call checked against the installed SDK |
| src/adapters/paper_ws.py | DEEP_READ | SDK WS kline model and `on()` API checked |
| src/adapters/telegram_notify.py | DEEP_READ | |
| src/adapters/telegram_callbacks.py | DEEP_READ | |
| src/execution/manager.py | NORMAL_READ | L120-L900 and L1040-L1215 (adapter consumers) |
| src/execution/placement.py | NORMAL_READ | leg parameter construction only (grep L199-L450) |
| src/execution/gates.py | METADATA_ONLY | headroom constant and comments |
| src/execution/fill_monitor.py | METADATA_ONLY | fill field names |
| src/reconcile/safe_mode.py, sweeper.py | METADATA_ONLY | adapter call sites |
| src/paper/supervisor.py | NORMAL_READ | L140-L200 |
| src/paper/loop.py | NORMAL_READ | L200-L225 closed gate |
| src/paper/notify.py | NORMAL_READ | L270-L320 send retry |
| src/data/backfill.py | NORMAL_READ | L150-L225 rate-limit retry |
| src/data/collector.py | METADATA_ONLY | adapter construction L879 |
| src/ops/health.py | METADATA_ONLY | telegram probe call site |
| docs/integration/BINANCE.md, TELEGRAM.md | DEEP_READ | |
| docs/integration/TRADINGVIEW.md | NORMAL_READ | |
| tests/fixtures/exchange_info_sample.json | METADATA_ONLY | filter coverage of 5 symbols |
| tests/test_execution_manager.py, test_phase8_audit_reviewfix.py, test_reconcile.py, test_drills.py | METADATA_ONLY | grep: fakes return `found=False` directly |
| .planning/phases/08*/08-REVIEW.md, 08-04-SUMMARY.md, 09*/09-REVIEW.md, 09-REVIEW-FIX.md | METADATA_ONLY | grep for prior -2011/-2013 handling |
| .planning/v0.3-MILESTONE-AUDIT.md | METADATA_ONLY | M1-M4 |
| .venv SDK packages (binance_sdk_derivatives_trading_usds_futures 17.4.0, binance_common 4.4.0) | NORMAL_READ | read-only introspection |

## Verified Safe Areas

- **SDK method existence and arguments.** Every adapter call resolves to an existing SDK 17.4.0 method with matching keyword names (sdk_probe_out.txt):
  - `kline_candlestick_data`, `open_interest`, `open_interest_statistics`, `get_funding_rate_history`, `exchange_information`
  - `current_all_open_orders(symbol)`, `current_all_algo_open_orders(symbol)`, `position_information_v3(symbol)`
  - `query_algo_order(client_algo_id)`, `cancel_order(symbol, orig_client_order_id)`, `cancel_algo_order(client_algo_id)`
  - `new_order(symbol, side, type, position_side, time_in_force, quantity, price, new_client_order_id)`
  - `new_algo_order(algo_type, symbol, side, type, position_side, trigger_price, close_position, quantity, working_type, reduce_only, client_algo_id)`
  - `query_order(symbol, orig_client_order_id)`, `get_current_position_mode()`

  Enum values used all exist:
  - NewOrderSideEnum / TimeInForceEnum (GTC) / TypeEnum.LIMIT
  - NewAlgoOrderAlgoTypeEnum.CONDITIONAL
  - ClosePosition / ReduceOnly TRUE/FALSE, which serialize as "true"/"false"
  - WorkingType MARK_PRICE/CONTRACT_PRICE

  Where the adapter passes a raw `str` for `interval`, `period` or `position_side`, `binance_common.utils.make_serializable` passes the str through unchanged, so the wire value is correct.
- **Response field access.** Every attribute read in `_row_to_*`, `_new_order_to_entry_result`, `_new_algo_order_to_algo_result`, `_query_order_to_probe` and `_algo_order_to_probe` exists on the SDK pydantic model, for example:
  - `un_realized_profit`, `break_even_price`, `algo_status`, `order_type`, `client_algo_id`, `trigger_time`, `update_time`
  - `filter_type`, `tick_size`, `step_size`, `min_qty`, `notional`, `dual_side_position`

  List endpoints come back through `from_dict(list)`, and the adapter's `raw if isinstance(raw, list) else [raw]` handles both shapes. If strict validation fails, the SDK falls back to raw dicts. The adapter then raises AttributeError, which fails closed.
- **MIN_NOTIONAL key.** binance_usdm.py:697,724 reads `f_min_notional.notional` (wire key `notional`), which is correct per A2. The code never reads MAX_NUM_ALGO_ORDERS, which was removed.
- **Decimal-to-wire (F-058).** `_decimal_to_wire` (binance_usdm.py:426-444) returns `format(value, "f")`, a fixed-point string that is never float or exponent. All prices and quantities go through it (L1070-1071, L1167, L1171). The F-058 float/exponent risk is closed at the code level.
- **Placement is never auto-retried.** Neither the adapter (L1054-1075, L1155-1175) nor the SDK retries a POST: `should_retry_request` only retries GET/DELETE on network errors (binance_common/utils.py:326-338). This matches the fact that "POST is never auto-retried". The manager retries only after a probe returns a definite `found=False` (manager.py:184-204).
- **closePosition exclusivity.** binance_usdm.py:1144-1152 rejects close_position together with quantity/reduce_only. placement.py L313-L325 and L421-L450 send `reduce_only=None` in hedge mode and on close-all legs, and `reduce_only=True` only on the one-way TP1 leg. This matches Binance's rules: reduceOnly is not allowed in hedge mode, and closePosition is not allowed with quantity/reduceOnly.
- **priceProtect.** It is never sent, so the Binance default `false` applies. This matches Corrected Rule 15.
- **Position mode.** It is re-read at placement (manager.py:496-502) through `get_current_position_mode` → `dual_side_position`, and fails closed to UNCERTAIN_ACCOUNT_STATE when it cannot be determined.
- **Reconcile algo snapshot is account-wide.** safe_mode.py:288 calls `snapshot_open_algo_orders()` without a symbol, so it hits the all-symbols endpoint (weight 40). That is the right source for the account-wide 200 cap (F-051). No production caller passes `open_algo_count` to the gates yet (M1/M2).
- **WS base URL.** The SDK WebSocketStreams class is built with `url_paths=["market","public","private"]` (websocket_streams.py:57), so the adapter does not hard-code the legacy URL (F-053 is doc-only).
- **Closed-kline detection.** It takes `x` verbatim (paper_ws.py:107), then applies:
  - supervisor gating on `kline.is_closed` (supervisor.py:163)
  - the loop's double gate `x==True and close_time<=now` (loop.py:205-219)

  Field names t/T/o/h/l/c/v/n/x/q match the SDK model `KlineCandlestickStreamsResponseK`. The paper WS path itself is broken (F-125).
- **Telegram callback_data.** It is `APR:`/`SKP:`/`SIM:` + 32 hex = 36 bytes, or `SKIP:` + 32 hex = 37 bytes. All are ≤ 64 bytes, and the check is in UTF-8 bytes at both build and parse (telegram_notify.py:112-116,167; telegram_callbacks.py:150-154).
- **Telegram callback handling:**
  - Strict prefix and hex parsing.
  - `query.answer()` is always called first (telegram_callbacks.py:635).
  - The chat gate runs before any state lookup.
  - Replay goes through `resolve_callback`.
- **Telegram plain text.** No `parse_mode` is used anywhere, so MarkdownV2 escaping is not needed and cannot break a send.
- **No auto-approve on notification failure.** paper/notify.py only journals a NotifyOutcome, and no path converts a send failure into an approval.
- **No direct HTTP.** There is no httpx, requests or aiohttp usage in src/, so there are no unbounded direct HTTP calls.
- **TradingView.** No webhook or FastAPI endpoint exists, so there is no unauthenticated inbound surface. The gap is already known (F-052, F-117).

## Findings

### F-501 · The first stop-loss placement depends on an unverified "algo order not found" error code (-2011 only)
- **Severity:** HIGH
- **Confidence:** PROBABLE (the code path is CONFIRMED; Binance's actual not-found code for GET /fapi/v1/algoOrder is UNVERIFIED)
- **Classification:** DEFECT
- **Category:** exchange-integration / protective-orders
- **Component:** adapter `query_algo_order_by_client` + manager `_place_protective_leg`
- **File:** src/adapters/binance_usdm.py, src/execution/manager.py
- **Lines:** binance_usdm.py:858-877; manager.py:741-752, 545-580
- **Invariant:** INV-084/INV-085 (post-fill protection), Corrected Rule 14
- **Phase/commit:** Phase 8 (08-04), Phase 9 CR-04 (probe-first)
- **Known-prior:** Partially known. 09-REVIEW-FIX.md:42 says "the existing -2011/UNKNOWN_ORDER mapping in ... `query_algo_order_by_client` should be re-checked too". That was never done, and it was not recognised that the mapping gates *every* SL.

**Evidence**

`_place_protective_leg` always probes before placing:

```
probe = await adapter.query_algo_order_by_client(client_algo_id=client_algo_id)
except Exception as exc: return (False, f"{role}: probe {type(exc).__name__}")
... if probe_found is not False: return (False, "probe outcome unknown")
```

The adapter maps only one form to not-found:

```
if "UNKNOWN_ORDER" in str(exc) or "-2011" in str(exc): return AlgoOrderProbe(found=False...)
raise
```

- Binance's error-code page defines -2011 as CANCEL_REJECTED ("Cancel request failure as open order not found in the orderbook"). The query not-found code is -2013 NO_SUCH_ORDER.
- The Query-Algo-Order page documents no not-found code at all.
- Probe (adapter_probe_out.txt): given the SDK's real `BadRequestError(-2013,'Order does not exist.')`, `query_algo_order_by_client` RAISES.
- Every test fake returns `found=False` directly (test_execution_manager.py:695, test_reconcile.py:246, test_drills.py:150). None uses real SDK error objects.

**Expected:** A never-placed `xa-` id is reliably classified as absent, using the code Binance actually returns (verified on testnet), so the SL gets placed.

**Actual:** If Binance answers the probe with anything other than an error containing "-2011" (for example -2013, or HTTP 200 with empty fields, which gives `found=True, status=None`), then:
- the SL is never placed;
- `execute_approved_plan` enters SAFE_MODE with ENTRY_WITHOUT_PROTECTIVE;
- it cancels the entry.

This happens on every live trade, including the attach path for TP1/TP2.

**Reproduction:**

```
PYTHONPATH=SNAPSHOT python -B tmp/integrations_external_apis/adapter_probe.py
```

Output line: `query_algo -2013 -> RAISES BadRequestError (-2013, 'Order does not exist.')`.

**Impact:**
- At best, no live trade can ever be protected, so live trading is unusable and SAFE_MODE fires on every approval.
- At worst, combined with F-502, an entry that filled immediately is left without a stop.

**Why tests miss it:** The fakes bypass the adapter's error mapping. The testnet rehearsal (09-04) is BLOCKED.

**Remediation:**
- Verify the real not-found response for GET /fapi/v1/algoOrder on testnet.
- Map it on a structured `exc.status_code`, not a substring.
- Alternatively, for a fresh plan, skip the probe and treat a duplicate-clientAlgoId rejection as "exists, then query".
- Add a test that uses real `binance_common.errors` objects.

### F-502 · A cancel that returns -2011 is treated as "already canceled" even when the order FILLED, so an unprotected filled entry is journaled as canceled
- **Severity:** HIGH
- **Confidence:** PROBABLE (code path CONFIRMED by probe; Binance semantics from the official error-code text; the live path is not yet wired, per M2)
- **Classification:** DEFECT
- **Category:** exchange-integration / order-state
- **Component:** adapter `cancel_normal_order` / `cancel_algo_order`; manager `expire_pending_entry`
- **File:** src/adapters/binance_usdm.py, src/execution/manager.py
- **Lines:** binance_usdm.py:933-943, 991-1001, 1257-1265; manager.py:561-580, 1103-1129
- **Invariant:** INV-084 (no unprotected exposure), INV-074 (SAFE_MODE / reconciliation), Corrected Rule 14
- **Phase/commit:** Phase 8 D-11 ("already-canceled-as-success", 08-04-SUMMARY:56)
- **Known-prior:** Not reported. Related: F-952 (cancel-only reconciler), F-104 (no user-data stream), F-127(a) (in-memory SAFE_MODE), F-106 (no alerts).

**Evidence**

- `_is_already_canceled_message` returns `"UNKNOWN_ORDER" in message or "-2011" in message`. On a match, `cancel_normal_order` logs `already_canceled` and returns normally.
- The official definition of -2011 is "open order not found in the orderbook". Binance returns it both for an already-canceled order and for an order that has already FILLED or expired.
- `expire_pending_entry` then journals `phase="post_cancel"` (manager.py:1119-1129).
- In `execute_approved_plan`, when the SL is not confirmed:
  - `enter_safe_mode(ENTRY_WITHOUT_PROTECTIVE)` is called;
  - then `expire_pending_entry(... trigger_reason="protective_unconfirmed")` is called;
  - the result is `NO_TRADE`.
- Probe output: `cancel filled order (-2011) -> returns None ... (treated as success, no fill check)`.

**Expected:**
- After -2011, query the order (`query_order_by_client`) to tell FILLED/PARTIALLY_FILLED from CANCELED/EXPIRED.
- If it filled, raise a HIGH-priority alert, flatten or protect the position (Corrected Rule 14: a reduce-only MARKET close), and never journal "post_cancel".

**Actual:**
- A marketable LIMIT entry fills at once and the SL fails (F-501, -2021, a timeout, and so on).
- The cancel returns -2011 and is logged as success.
- The journal says the entry was canceled, while a live position has no stop.
- Only in-memory SAFE_MODE remains. The reconciler is cancel-only and there is no alert.

The same substring rule makes `cancel_untriggered_protectives` count an SL that already triggered or finished as "canceled".

**Reproduction:** Same probe script (adapter_probe_out.txt, last line).

**Impact:** A real-money position with no protective stop and a journal that claims no exposure. At the chosen leverage, loss is unbounded until manual discovery.

**Why tests miss it:** The tests model -2011 only as "gone". No test gives the cancel of a filled order.

**Remediation:**
- Treat -2011 on cancel as UNKNOWN_FINAL_STATE, then query by client id and branch on status.
- Match on `exc.status_code == -2011` rather than a substring (also fixes 08-REVIEW IN-10).
- On a FILLED result, run the Corrected Rule 14 emergency path.

### F-503 · Entry-placement error handling has no error-code taxonomy: -2013 is not mapped, so every definite rejection leads to SAFE_MODE and ENTRY_ABSENT is unreachable
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DEFECT
- **Category:** exchange-integration / error-mapping
- **Component:** manager `_place_entry_no_blind_retry`; adapter `query_order_by_client`
- **File:** src/execution/manager.py, src/adapters/binance_usdm.py
- **Lines:** manager.py:184-204, 521-534; binance_usdm.py:1204-1229
- **Invariant:** INV-080-ish (fail closed without false SAFE_MODE), EXECUTION_SPEC §10
- **Phase/commit:** Phase 9 CR-09
- **Known-prior:** KNOWN, 09-REVIEW.md:204 and 09-REVIEW-FIX.md:42/140 ("-2013 deliberately not mapped"). Re-reported here with the wider scope below.

**Evidence**
- Any exception from `place_entry` is treated as ambiguous (`except Exception: response = None`), and then the order is queried.
- For an order Binance rejected (-2019 margin, -4164 MIN_NOTIONAL, -1021 timestamp, -4061 position side, -2010, -1111, -4014, -4023), no order exists. `query_order` then returns -2013, which the adapter does not map, so it raises and the result is `ENTRY_STATE_UNKNOWN` → `enter_safe_mode`.
- Probe: `query_order -2013 -> RAISES`.

**Expected** (the A2 error table):
- Classify definite 4xx rejections by `exc.status_code` as NO_TRADE with a reason code (for example -2019 → INSUFFICIENT_MARGIN, -4164 → NOTIONAL_REJECT). No SAFE_MODE for these.
- Probe only on network errors, timeouts and 5xx.
- Map -2013 to `found=False`, re-verified on testnet.

**Actual:**
- Every definite exchange rejection forces SAFE_MODE, which blocks all later entries until manual reconciliation.
- The `ENTRY_ABSENT` branch (manager.py:529-534) can never be reached against the real exchange.

**Reproduction:** adapter_probe.py, first result line.

**Impact:**
- An operational denial of service after any routine rejection.
- Rejection reasons are lost (no reason code), which breaks NO_TRADE rate reporting.
- It does not create unsafe orders.

**Why tests miss it:** The fakes inject `RuntimeError("-2013 ...")` and expect UNKNOWN (test_execution_manager.py:715), so they encode the current behaviour.

**Remediation:** Add an adapter-level typed error mapping (code → RejectionReason / Ambiguous) using the A2 error table, and a -2013 not-found mapping backed by testnet evidence.

### F-504 · The Binance REST client is built with SDK defaults: 1000 ms timeout, no credentials, no base-URL or testnet selection
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** exchange-integration / configuration
- **Component:** `BinanceUsdmAdapter.__init__`
- **File:** src/adapters/binance_usdm.py
- **Lines:** 526-527 (also src/data/collector.py:879)
- **Invariant:** INV-112-ish (ops posture), OPS-02
- **Phase/commit:** Phase 2 / Phase 9
- **Known-prior:** Credentials and testnet are KNOWN (F-128). The timeout is new.

**Evidence**
- The adapter uses `self._sdk = sdk_client or DerivativesTradingUsdsFutures()`.
- `ConfigurationRestAPI` defaults are `timeout: int = 1000`, `retries: int = 3`, `backoff: int = 1000` (binance_common/configuration.py:31-41).
- Probe output: `default REST config: timeout_ms= 1000 retries= 3 api_key= None`.
- No `ConfigurationRestAPI` is constructed anywhere in src/.

**Expected:**
- An explicit, audited REST configuration:
  - a timeout suited to order POSTs from the operator's host (several seconds);
  - API key and secret from the secret store;
  - a testnet or demo base_path for rehearsal;
  - retries documented.
- Signed endpoints must fail at start-up if no key is set, not per call.

**Actual:**
- Every order POST has a 1 s read timeout. Under volatility or from a distant host, many placements become ambiguous (NetworkError), which goes to probe, then F-503, then SAFE_MODE.
- All signed calls (orders, positions, position mode) fail with 401 because there is no key. `get_position_mode` then returns UNCERTAIN_ACCOUNT_STATE.

**Reproduction:** adapter_probe.py, line 1.

**Impact:** Live placement is unreliable or impossible, and ambiguous placements rise. With F-501/F-502, ambiguity is exactly where unprotected-position risk arises.

**Why tests miss it:** Tests always inject a fake sdk_client.

**Remediation:** Build `ConfigurationRestAPI` in one composition-root factory, with a timeout of about 5-10 s for POST, keys from env/secret, and a testnet URL switch. Log the effective configuration (without secrets) at start-up.

### F-505 · No clock-skew handling for signed requests (no recvWindow, no server-time offset)
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** exchange-integration / auth
- **Component:** adapter
- **File:** src/adapters/binance_usdm.py
- **Lines:** 761-1249 (no `recv_window` argument anywhere); binance_common/utils.py:116-119, 413
- **Invariant:** fail-closed on uncertain connection
- **Phase/commit:** Phase 8/9
- **Known-prior:** None.

**Evidence**
- The SDK stamps `timestamp = int(time.time()*1000)` from the local clock.
- The adapter never passes `recv_window` (default 5000 ms), never calls `check_server_time`, and has no drift health check.
- The target host is a Windows developer machine (AGENTS.md).

**Expected:**
- A start-up and periodic server-time drift check (`GET /fapi/v1/time`).
- Block entries (SAFE_MODE / NO_TRADE) if the drift exceeds about 500 ms.
- Map -1021 explicitly.

**Actual:** When the clock drifts, every signed call returns -1021. Placements go to F-503 and SAFE_MODE, and reconciliation snapshots fail.

**Reproduction:** Code reading: grep `recv_window|check_server_time` src gives only docstrings.

**Impact:** An availability problem. It fails closed, but the cause is not diagnosed.

**Why tests miss it:** Fakes.

**Remediation:** Add a drift health check and an explicit -1021 mapping.

### F-506 · Rate-limit and ban handling ignores Retry-After, retries on 418 IP-ban, and never reads the weight headers
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DEFECT
- **Category:** exchange-integration / rate-limits
- **Component:** backfill paginator; adapter cancel retry
- **File:** src/data/backfill.py, src/adapters/binance_usdm.py
- **Lines:** backfill.py:184-223; binance_usdm.py:129-143, 906-914, 965-973
- **Invariant:** —
- **Phase/commit:** Phase 2 / Phase 8
- **Known-prior:** 08-REVIEW (the entry just before IN-10) covers only the class-name fallback of `is_rate_limit_error`. F-122: backfill has no caller.

**Evidence**
- `fetch_page_with_retry` uses `retry_if_exception(_is_rate_limit)`. That covers both TooManyRequestsError (429) and RateLimitBanError (418), with `wait_exponential_jitter(initial=0.5, max=jitter_max_seconds*4)`. The SDK exposes `retry_after` on both errors (binance_common/errors.py:56-100), but it is never read.
- The cancel retry predicate `_cancel_retry_predicate` retries every non-programming exception, including 418, 429, 401 and -1021 (3 attempts within 30 s).
- `ApiResponse.rate_limits` (X-MBX-USED-WEIGHT / ORDER-COUNT) is never read.

**Expected** (A2 limits):
- On 429, back off for at least Retry-After.
- On 418, stop all requests until the ban expires. Retrying escalates the ban from 2 minutes up to 3 days.
- Track used weight.

**Actual:** Short jittered retries into a ban, and blind retries of non-transient cancel errors.

**Reproduction:** Code reading.

**Impact:**
- For a deep bootstrap backfill: a possible IP ban that also takes down the live and reconcile paths on the same IP.
- For cancels: wasted budget, and it is bounded.

**Why tests miss it:** Tests assert only that a retry happens.

**Remediation:**
- Honour `retry_after`.
- Never retry 418. Treat it as a global circuit breaker plus SAFE_MODE.
- Restrict the cancel retry to NetworkError, ServerError and 429 after Retry-After.

### F-507 · Live SL/TP use workingType=MARK_PRICE against Corrected Rule 15 (CONTRACT_PRICE, matching the backtest)
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DEFECT (root cause: planning decision F-958 and doc gap F-010)
- **Category:** exchange-integration / trigger semantics
- **Component:** execution placement
- **File:** src/execution/placement.py; src/execution/manager.py
- **Lines:** placement.py:325, 437, 450; manager.py:558
- **Invariant:** INV-058 / INV-103 (backtest-live parity), Corrected Rule 15
- **Phase/commit:** Phase 9 (09-01)
- **Known-prior:** KNOWN at planning level (F-958, F-010). Reported here as the code-level defect, as the STAGE C NOTE asks.

**Evidence:** Every protective leg hard-codes `"working_type": "MARK_PRICE"`, and the value is not recorded on the plan. The SDK and Binance default is CONTRACT_PRICE. Backtest and paper trigger on 1m last-price candles.

**Expected:** `workingType=CONTRACT_PRICE` and `priceProtect=false`, both recorded on the plan (Corrected Rule 15), or a mark-price backtest.

**Actual:** MARK_PRICE triggers.

**Reproduction:** grep `MARK_PRICE` src/execution.

**Impact:**
- Live stop behaviour differs from the evidence the kill gate was judged on: wick stops the backtest counted are not triggered live, and the reverse.
- Slippage differs on mark/last divergence.

**Why tests miss it:** The tests pin MARK_PRICE.

**Remediation:** Make the working type a registered parameter defaulting to CONTRACT_PRICE, and journal it on the plan.

### F-508 · Telegram approval authorises by chat id only, not by user id, and APPROVE/SKIP are built as separate keyboards
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** telegram / auth
- **Component:** telegram_callbacks / telegram_notify
- **File:** src/adapters/telegram_callbacks.py; src/adapters/telegram_notify.py
- **Lines:** telegram_callbacks.py:184-197, 642-656; telegram_notify.py:175-203
- **Invariant:** INV-047 / INV-050 (approval binding: "user identity / authorized chat", TELEGRAM.md §3)
- **Phase/commit:** Phase 8 (08-02)
- **Known-prior:** F-127(d) covers the token not being carried in the callback. This is a different gap.

**Evidence**
- The gate compares `update.effective_chat.id` with `authorized_chat_id`. `query.from_user.id` is never checked.
- If the authorised chat is a group or channel, any member can APPROVE.
- `build_approve_keyboard` and `build_skip_keyboard` each return a one-button `InlineKeyboardMarkup`. A single message can carry only one `reply_markup`, so one alert cannot offer both APPROVE and SKIP. No sender for the APPROVE alert exists (M2).

**Expected:**
- Check both `chat.id` and an authorised `from_user.id`, and/or reject non-private chats.
- One keyboard with both buttons.

**Actual:** A chat-only check, and split keyboards.

**Reproduction:** Code reading.

**Impact:** A low probability of unauthorised approval if the operator ever uses a group. There is UX friction too.

**Why tests miss it:** The tests use a private-chat fake.

**Remediation:** Add an `authorized_user_id` gate and `chat.type == "private"`. Build one two-button markup.

### F-509 · The Telegram callback and notify edge is fragile: the keyboard is not removed after a decision, synchronous DB I/O runs on the PTB loop, and flood-control Retry-After is ignored
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** IMPROVEMENT
- **Category:** telegram / reliability
- **Component:** telegram_callbacks.on_callback; paper/notify
- **File:** src/adapters/telegram_callbacks.py; src/paper/notify.py
- **Lines:** telegram_callbacks.py:657-699, 743-744; paper/notify.py:277-300
- **Invariant:** INV-048 (at-least-once callbacks idempotent)
- **Phase/commit:** Phase 7/8
- **Known-prior:** None. The runtime wiring gap is M2.

**Evidence**
- After dispatch, the handler only calls an optional `reply_text_fn(chat_id, text)`. The original message is never edited and its inline keyboard is never removed, so the APPROVE button stays pressable. Safety then rests entirely on replay-to-existing, which F-126 and F-127 show is in-process only.
- `dispatch(...)` is a synchronous function that performs the journal and DB saves inside the async PTB handler, which blocks the event loop.
- The send retry in notify retries on every non-programming error, including `telegram.error.TimedOut`, whose message may already have been delivered, and `RetryAfter`, whose `retry_after` is not honoured.

**Expected:**
- `edit_message_reply_markup` / `edit_message_text` to show the final state and remove the buttons.
- Offload DB work (`asyncio.to_thread`) or use the async engine.
- Honour `RetryAfter`.
- Treat `TimedOut` as possibly delivered, relying on idempotent SIMULATE.

**Actual:** As described above.

**Reproduction:** Code reading.

**Impact:**
- Double presses and stale buttons.
- Event-loop stalls while a WS or placement coroutine shares the loop.
- Possible duplicate alerts.

**Why tests miss it:** PTB surfaces are explicitly not unit-tested (telegram_callbacks.py:26-28, 722-726).

**Remediation:** As listed under Expected.

## Open Questions

1. **L3/L5, Corrected Rule 6.** SL trigger rounding (placement.py:204-210; manager.py:479-483) rounds the SL *toward* the entry ("tighter stop"). Rule 6 says the SL rounds away from entry, with qty computed from the rounded prices. L3 should check whether qty is sized on the unrounded SL, and what that means for realized risk.
2. **L3.** TP1 uses a LOT_SIZE-quantized quantity on a TAKE_PROFIT_MARKET algo leg, which is subject to MARKET_LOT_SIZE (F-056). No PERCENT_PRICE check is made on the LIMIT entry price. Both are known at the doc level.
3. **L4/L7.** `exchange_info()` has no production caller (F-127(c)). If it is wired, one symbol in the full ~600-symbol exchangeInfo that lacks a filter or fails strict pydantic validation aborts the whole refresh (binance_usdm.py:748-752). The fixture holds only 5 symbols. It needs verifying against a full real snapshot.
4. **L2.** There is no user-data stream: listenKey keepalive, `listenKeyExpired` handling and ALGO_UPDATE/ORDER_TRADE_UPDATE parsing are all absent (F-104). The Algo X statuses TRIGGERED/FINISHED/REJECTED/EXPIRED are therefore observed only via REST snapshot polling, which is not scheduled (M-series). `_ACTIVE_ALGO_STATUSES={"NEW"}` is correct for "active".
5. **Verification lane.** F-501 hinges on the real not-found code of GET /fapi/v1/algoOrder. A testnet call (outside this read-only audit) is the decisive check.
6. **L7.** `new_order` uses the default `newOrderRespType` (ACK). `_new_order_to_entry_result` requires `origQty` and `updateTime` in the response. If an ACK response omits them, the adapter raises, and the result is ambiguous → probe → F-503.
