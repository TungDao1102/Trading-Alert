# Verification V2_execution

| ID | Outcome | Final severity | Duplicate of | One-line reason |
|---|---|---|---|---|
| F-501 | INSUFFICIENT_EVIDENCE | HIGH if testnet shows a code other than -2011 (provisional) | — | The code does map only `-2011` to not-found, and the docs do define -2011 as CANCEL_REJECTED and -2013 as NO_SUCH_ORDER. What Binance returns for a missing algo order is undocumented, so "every live entry fails" needs a testnet call to confirm. |
| F-502 | DOWNGRADED | MEDIUM | — | Confirmed that -2011 on the entry cancel is logged as `post_cancel`. But SAFE_MODE(ENTRY_WITHOUT_PROTECTIVE) is entered before the cancel, the outcome is ENTRY_WITHOUT_PROTECTIVE (not a quiet success), and compare.py flags positions/entries that have no protective order. The exposure comes from the SL failure. This defect is a false "canceled" audit record plus no fill check. |
| F-126 | CONFIRMED | HIGH | — | Probe: calling `execute_approved_plan` twice with the same approval makes 2 `place_entry` calls with the same `x-…EN` id. Binance documents newClientOrderId as "unique id among open orders", so once the first order has filled or been canceled, nothing stops a second entry. |
| F-951 | CONFIRMED | HIGH | F-126 | 08-RESEARCH:283 ("exchange dedups") and :303 (rejects local "already-sent" flags) contradict the documented open-orders-only uniqueness. This is the design root of F-126. |
| F-603 | DOWNGRADED | MEDIUM | F-126 | Real: EXEC-03 validation (8-0X-04) runs only test_order_ids determinism tests, and FakeExecutionAdapter.place_entry never rejects a duplicate id. It is the test gap behind F-126, not a separate runtime defect. |
| F-702 | CONFIRMED | HIGH | — | Probe with a raising journal: no cancel calls from expire_pending_entry, cancel_untriggered_protectives or emergency_manual_close. Enablement stays enabled. execute_approved_plan raises before cancelling an acknowledged entry that has no SL. |
| F-104 | CONFIRMED | HIGH | — | The adapter has no listenKey, user-data WS, ORDER_TRADE_UPDATE/ALGO_UPDATE/ACCOUNT_UPDATE or userTrades code. Nothing in src feeds `fill_events`. No REQ-ID covers it. Phase 12 mentions the user-data stream only for equity. |

Common context (all findings): no production code path calls `execute_approved_plan`, `attach_protectives_to_fill`, `expire_pending_entry` or `emergency_manual_close`. They are called only from tests; `grep` over src/ found no composition root. There is also no concrete production journal class, only duck-typed `JournalLike` protocols. So every defect below is latent in the live-order core and is not yet reachable by a running process. Severities are judged for when this core is wired for Phase 3 live, which is its only purpose.

Binance documentation facts (developers.binance.com, fetched 2026-09-29):
- Error-code page, documented:
  - `-2011 CANCEL_REJECTED`: "Cancel request failure as open order not found in the orderbook: 'Unknown order sent'."
  - `-2013 NO_SUCH_ORDER`: "Order does not exist."
  - `-4116 DUPLICATED_CLIENT_ORDER_ID`: "clientOrderId is duplicated".
  - `-4015`: client order id max 36 chars.
  - No code is documented as "UNKNOWN_ORDER". Binance never sends that string, so the `"UNKNOWN_ORDER" in str(exc)` branch is dead.
- New Order, documented: `newClientOrderId` is "A unique id among open orders", regex `^[\.A-Z\:/a-z0-9_-]{1,36}$`.
- Query Order / Query Algo Order / Cancel Algo Order, documented: retention rules only. CANCELED/EXPIRED with no fills are not found after 3 days; any order is not found after 90 days. Query Algo Order and Cancel Algo Order document no not-found or already-finished error code. **Undocumented:** the code returned for a never-placed or finished `clientAlgoId` on GET and DELETE `/fapi/v1/algoOrder`. The clientAlgoId uniqueness scope is also undocumented on the algo pages.
- Installed SDK (`binance_common` 4.4.0, utils.py:472-475) passes Binance's code through verbatim: `BadRequestError(error_message=data.get("msg"), status_code=data.get("code"))`, and `str(exc)` is `"(-2013, 'Order does not exist.')"`. The adapter docstring says "the SDK normalizes not-found as a generic API error with code -2011". The SDK does no such normalization; the code is whatever Binance sends.

Probe: `tmp\verify_V2_execution\probe.py`. It uses the snapshot on PYTHONPATH, the repo venv, `-B`, no network and no DB, and reuses `tests/test_execution_manager.py` helpers and fakes.

## F-501
- **Outcome:** INSUFFICIENT_EVIDENCE. Provisional HIGH if confirmed.
- **Independent evidence:**
  - `src/adapters/binance_usdm.py:864-873` matches only `"UNKNOWN_ORDER" in str(exc) or "-2011" in str(exc)` to `found=False`, and otherwise `raise`.
  - `src/execution/manager.py:733-736` (`_place_protective_leg`): when the probe raises, it returns `(False, "...probe <Type>")`. It never calls `place_algo_protective`.
  - manager.py ~546-562 then enters SAFE_MODE(ENTRY_WITHOUT_PROTECTIVE) and cancels the entry.
  - Probe output with the real adapter and a fake SDK:
    - `-2011 query_algo -> AlgoOrderProbe(found=False)`
    - `-2013 query_algo RAISES BadRequestError (-2013, 'Order does not exist.')`
  - Probe output with the manager and a -2013 probe: `ENTRY_WITHOUT_PROTECTIVE`, safe_mode `['ENTRY_WITHOUT_PROTECTIVE']`, calls `[get_position_mode, place_entry, query_algo_order_by_client, cancel_normal_order]`. The SL is never placed.
- **Documented vs undocumented:**
  - Documented: -2011 = CANCEL_REJECTED (a cancel-path code), -2013 = NO_SUCH_ORDER ("Order does not exist.").
  - Undocumented: the response for a missing algo order.
  - The team's own 09-REVIEW.md:204 and 09-REVIEW-FIX.md:42 already call -2013 the query not-found code for normal orders and deliberately left it unmapped. The algo probe was never re-checked the same way.
- **What would decide it:** On testnet, call GET `/fapi/v1/algoOrder?clientAlgoId=<never-placed xa- id>` and record the HTTP status and body `code`/`msg`. Also cover a fresh id versus an id past the 3-day retention.
  - If the code is anything other than -2011 (for example -2013, or HTTP 200 with an empty body), the claim is CONFIRMED HIGH: every live entry is cancelled with SAFE_MODE.
  - If it is -2011, the claim reduces to "mapping unverified" (LOW).
- **Counter-checks:**
  - No other not-found path exists: `_place_protective_leg` is the only caller path before `place_algo_protective`, and it is used by both `execute_approved_plan` and `attach_protectives_to_fill`.
  - No recorded fixture of the real algo not-found response exists in tests/ or docs/. The -2011/-2013 hits are only in planning reviews and in test_execution_manager/test_phase8_audit_reviewfix fakes.
- **Notes:** Failure is fail-closed, but there is a window between entry acknowledgement and the cancel. If the LIMIT fills in that window, see F-502.
  - Minor: 08-REVIEW IN-10 notes that the substring match `-2011` also matches `-20110…`.

## F-502
- **Outcome:** DOWNGRADED to MEDIUM.
- **Independent evidence:**
  - `binance_usdm.py:933-942` and `:993-1000`: `_is_already_canceled_message` (`:1257-1265`, `"UNKNOWN_ORDER" in message or "-2011" in message`) leads to a log "already_canceled" and `return`. The retry predicate (`:140-143`) also stops on it.
  - Probe: `cancel_normal_order(-2011) -> None`. `expire_pending_entry` with that adapter journals phases `['pre_cancel', 'post_cancel']`.
  - The docs define -2011 as "open order not found in the orderbook". A FILLED order is not open in the order book, so the documented text covers FILLED and EXPIRED orders. The adapter cannot tell "already canceled" from "already filled".
- **Why downgraded:**
  - In `execute_approved_plan` (manager.py ~546-562), `safe_mode_controller.enter_safe_mode(reason=ENTRY_WITHOUT_PROTECTIVE)` runs BEFORE `expire_pending_entry`. The returned outcome is `ENTRY_WITHOUT_PROTECTIVE`, not a plain NO_TRADE success, so the system is already blocked and flagged.
  - The reconciler compare (`src/reconcile/compare.py:396`, `:425`, `:461`) emits ENTRY_WITHOUT_PROTECTIVE and UNSYNCED_POSITION divergences, which would surface the live position.
  - The unprotected position is caused by the SL failure (see F-501), not by the -2011 handling.
  - What is real: the journal records a false `post_cancel` for a filled entry, which misleads the operator audit trail. There is also no query-after-(-2011) to detect FILLED/PARTIALLY_FILLED.
  - The "reduce-only close / protect" remedy the claimant expects conflicts with D-02 (no rescue placement). An operator alert plus correct classification is the in-policy fix.
- **Counter-checks:**
  - `cancel_algo_order` has the same mapping. For algo orders the -2011 semantics are undocumented, and a TRIGGERED SL would also read as "canceled".
  - No `query_order_by_client` follow-up exists after a cancel in `expire_pending_entry` (`manager.py:1012-1050`).

## F-126
- **Outcome:** CONFIRMED, HIGH.
- **Independent evidence:**
  - `manager.py:231-233` docstring: "consuming the approval … needs persisted execution state and is NOT handled here".
  - `check_binding_full` (`src/approval/binding.py` ~167-211) validates the token hash but has no used/consumed state.
  - `src/approval/replay.py` (via `telegram_callbacks.py:274-281`) returns the existing APPROVED row on replay. Any wiring that runs execute for a resolved APPROVED callback would run it again.
  - Probe: two `_run_plan` calls produced `OK, OK`, `place_entry calls: 2`, with the same id `x-33333333333333333333333333333333EN`.
  - Binance docs: the uniqueness scope is "among open orders". Once the first entry is FILLED or CANCELED (including expiry cancels by `expire_pending_entry`), the same id is accepted again.
- **Counter-checks:**
  - Gates (`src/execution/gates.py:220-236` `check_portfolio`) enforce cluster/aggregate/position-count caps. They may coincidentally block a replay when a position already exists and the caps are tight, but there is no same-plan or same-symbol dedup.
  - After an unfilled-then-cancelled entry, no position exists, so nothing blocks the replay.
  - The replay window is bounded only by the plan's `expiry_utc`.
  - While the first order is still OPEN, a duplicate would be rejected (documented -4116). The manager then probes, finds `ENTRY_EXISTS`, and continues, so that case is safe.
- **Notes:** This breaks EXECUTION_SPEC §7 ("Repeated execution of the same approved plan must not create duplicate entry orders") and TELEGRAM.md:32 ("Replaying an old approval must not place a fresh order").

## F-951
- **Outcome:** CONFIRMED, HIGH. DUPLICATE_OF F-126 (design root).
- **Independent evidence:**
  - `.planning/phases/08-approval-reconciliation-hardening/08-RESEARCH.md:283`: "Same approved plan retried/restarted/replayed → same IDs → exchange dedups".
  - `:303`: "Exchange ID dedup bookkeeping | Local 'already-sent' boolean flags | Deterministic client/algo IDs (exchange is the dedup authority) | Flags die on restart; the exchange remembers".
  - The official New Order doc says "A unique id among open orders". The exchange does not remember filled or cancelled ids for dedup, so the design premise is false as documented.
- **Counter-checks:** No later plan or summary in phases 08-10 adds a durable execution-intent record (F-126 probe).

## F-603
- **Outcome:** DOWNGRADED to MEDIUM. DUPLICATE_OF F-126 (test gap for the same root).
- **Independent evidence:**
  - `08-VALIDATION.md:49` (8-0X-04, EXEC-03) runs only `tests/test_order_ids.py` (ID determinism, 21 tests). ROADMAP.md:259 SC4 claims "never create duplicate entry orders".
  - `tests/test_execution_manager.py:128-134`: `FakeExecutionAdapter.place_entry` records the call and returns the canned response. It never rejects a repeated `new_client_order_id`.
  - grep for twice/double/replay in test_execution_manager.py found no double-invoke test.
  - The probe reproduces the two-entry result using these fakes.
- **Why downgraded:** This is a coverage gap. The runtime defect and its severity belong to F-126.

## F-702
- **Outcome:** CONFIRMED, HIGH.
- **Independent evidence (probe with `journal.record` raising RuntimeError):**
  - `expire_pending_entry` raised and `cancel_untriggered_protectives` raised. Cancel calls sent: `[]`. The pre_cancel `journal.record` (`manager.py:1012-1022`, and in the SL/TP loop `~1083-1094`) sits outside any try.
  - `LiveEnablementController.disable` raised, and `guard_placement` still PASSES. `enablement.py:235-242` journals before `self._disabled = True`.
  - `emergency_manual_close` raised an ExceptionGroup with 4 errors. Cancels sent: `[]`. Enablement disabled: `False`.
  - `execute_approved_plan` with a real `SafeModeController(journal=raising)` and a REJECTED SL leg raised `RuntimeError DB down`. The calls were `[get_position_mode, place_entry, query_algo_order_by_client, place_algo_protective]` with no `cancel_normal_order`, so the acknowledged entry stays live without an SL.
- **Nuance:**
  - `SafeModeController.enter_safe_mode` (`safe_mode.py:205-212`) sets `_in_safe_mode = True` BEFORE journaling. In-memory SAFE_MODE does take effect, and the probe shows `safe flag: True`, but the exception still aborts the cancel.
  - Emergency close isolates steps, yet every step fails at its own journal write.
- **Counter-checks:** Searched for a fallback or best-effort journal wrapper and found none. No concrete journal implementation exists in src. Only Protocols exist in `execution/enablement.py:35`, `reconcile/safe_mode.py:71` and `reconcile/sweeper.py:52`. The DB-backed behavior is therefore by contract, not observed.

## F-104
- **Outcome:** CONFIRMED, HIGH.
- **Independent evidence:**
  - The `BinanceUsdmAdapter` method list (`binance_usdm.py:526-1256`) has klines, open_interest(_statistics), funding_rate, exchange_info, snapshot_open_normal_orders, snapshot_open_algo_orders, snapshot_positions, query_algo_order_by_client, cancel_normal_order, cancel_algo_order, place_entry, place_algo_protective, query_order_by_client and get_position_mode. There is no listenKey, WS, userTrades or account-trade method.
  - grep over src/ for `listenKey|listen_key|ORDER_TRADE_UPDATE|ALGO_UPDATE|ACCOUNT_UPDATE|user_trades|userTrades` matched only a docstring comment at `binance_usdm.py:58`.
  - `fold_fills` and `fill_events` have no callers outside `execution/manager.py` and `execution/fill_monitor.py`.
- **Requirements:**
  - REQUIREMENTS.md has EXEC-01/02/03 and no user-data-stream REQ.
  - ROADMAP phases 11-17 have no order/fill user-data item. Phase 12 (ROADMAP.md:368) mentions the "user-data stream" only as an equity source. This nuance should be noted, but it does not cover fills or orders.
  - Spec anchors are present: EXECUTION_SPEC.md:22 "Monitor user-data events", AGENTS.md:15/50 and PROJECT.md:52.
- **Counter-checks / mitigation:**
  - The entry-time SL is `close_position=True` and placed before any fill (manager.py ~527-545), so a filled entry still has a stop if F-501 does not bite.
  - REST snapshots allow periodic reconciliation.
  - What is missing: TP1/TP2 are never attached in production, fill-sized protectives (EXEC-01 "partial-fill protective sizing") have no data source, and ALGO_UPDATE rejection reasons are never parsed.
