# Lane M02: exec_placement

## Scope
`src/execution/{manager,approval_desk,confirm_flow,confirm_recheck,pre_placement,placement,binding,gates,enablement,execution_limits,constraint_snapshot,order_ids,intent_store,intent_recovery,prior_outcome,lot_split,lot_filter_source,tp_sizing}.py`, `src/approval/*`.
Snapshot commit `55885b9`. Read-only. (Partial run in progress: sections are appended as file groups finish.)

## Progress notes (working, kept for a resumed run)
- [done] enablement.py, placement.py, gates.py, pre_placement.py, order_ids.py, intent_store.py (Protocol), manager.py lines 1-1790 (execute_approved_plan and helpers), caller `src/live/execution_service.py:213-274`.
- Only production caller of `execute_approved_plan`: `src/live/execution_service.py:246`. Only `place_entry` call site in src: `manager.py:376` (`_place_entry_no_blind_retry`). SDK `new_order` is referenced only in `src/adapters/binance_usdm.py:1380,1469`.
- [todo] intent_recovery, binding, approval/*, approval_desk, confirm_flow, confirm_recheck, execution_limits, constraint_snapshot, lot_*, tp_sizing, prior_outcome, manager 1790-3076, SQL store consume, enable() callers.

- [done 2] intent_recovery.py, binding.py (execution + approval), tokens.py, confirm_core.py (state machine 274-1408), live/enablement.py + live/config.py:185-207 (enable path).
- Leads so far (to be written as findings or safe areas): (a) manager identity/token gate is fed a Callback fabricated by `ExecutionService._place` (execution_service.py:223-232) so chat/token checks there are tautological, real gate = ConfirmBook; (b) `_replay` answers CONFIRMED for an entry whose reservation was refused (confirm_core.py:1147-1150 vs 734-735); (c) cancellation/BaseException between POST and `register_resting_entry` (manager.py:1337-1445) leaves a resting entry untracked until restart; (d) store exceptions that are not PersistenceError after POST skip the hand-off.

- [done 3] SQL consume (`src/persistence/execution_state.py:264-357`), `uow.py` error translation, SDK retry logic (`binance_common/utils.py:314-545`), adapter `place_entry`/`_sdk_call`, confirm_flow 146-470, approval_desk 1-445 + 556-745, replay.py, confirm_recheck.py, prior_outcome.py, limits file values. Probe `tmp/exec_placement/probe_qty.py` run. Write-up follows.

## Coverage
| File | Level | Note |
|---|---|---|
| src/execution/manager.py | DEEP_READ 1-1790; NORMAL_READ 1790-2040; METADATA_ONLY 2040-3076 | `execute_approved_plan` and every helper read line by line. The rest (take-profit attach, cancels, manual close) is protection/cancel code: outlined, adapter calls listed, no `place_entry` there. Left to M03. |
| src/execution/enablement.py | DEEP_READ | plus callers `src/live/enablement.py`, `src/live/config.py:185-207` |
| src/execution/placement.py | DEEP_READ | |
| src/execution/gates.py | DEEP_READ | |
| src/execution/pre_placement.py | DEEP_READ | |
| src/execution/binding.py | DEEP_READ | |
| src/execution/order_ids.py | DEEP_READ | |
| src/execution/intent_store.py | DEEP_READ | Protocol; PG implementation `src/persistence/execution_state.py` read for consume and `restorable_entries` only |
| src/execution/intent_recovery.py | DEEP_READ | |
| src/execution/confirm_recheck.py | DEEP_READ | |
| src/execution/prior_outcome.py | DEEP_READ | |
| src/execution/confirm_flow.py | NORMAL_READ 146-470; NOT_READ 470-894 | replies, final message edits, expiry sweeps not read |
| src/execution/approval_desk.py | NORMAL_READ 1-445, 556-745; NOT_READ rest | `send`, `reply_fn`, `finalize_hook`, `finalize_expired_requests` not read |
| src/execution/execution_limits.py | METADATA_ONLY | grep of NOT_CONFIGURED handling; values read from `config/execution/execution-limits-v1.toml` |
| src/execution/constraint_snapshot.py | METADATA_ONLY | outline + `snapshot_is_valid_for_live` read |
| src/execution/lot_split.py | METADATA_ONLY | outline only |
| src/execution/lot_filter_source.py | METADATA_ONLY | outline only |
| src/execution/tp_sizing.py | METADATA_ONLY | docstring + outline (no caller found in src besides its own module: see Open Questions) |
| src/approval/confirm_core.py | DEEP_READ 274-420, 500-620, 666-1408; NOT_READ 142-273, 420-500, 620-666 | state machine, gates, sweeps read |
| src/approval/binding.py | DEEP_READ | |
| src/approval/replay.py | DEEP_READ | |
| src/approval/tokens.py | DEEP_READ | |
| src/approval/mapping.py | NORMAL_READ | `derive_short_id` read |
| src/approval/reason_codes.py, src/approval/__init__.py | NOT_READ | constants |

Not run: no test file was executed (one arithmetic probe only). The consume transaction (`*_pg.py` territory) was read, not executed. No web page was fetched: exchange facts below rest on the installed SDK source and on the project's recorded Demo observations, marked as such.

## Verified Safe Areas
1. **One POST per approval, no retry at any layer (D080).** `place_entry` has one call site in `src`, `manager.py:376`, inside `_place_entry_no_blind_retry` (no loop, no recursion, `manager.py:340-410`). The adapter makes a single `_sdk_call` (`binance_usdm.py:1378`, `883-916`: "Never retries, never sleeps"; tenacity is used only for cancels, `918-930`). The SDK cannot resend a POST: `binance_common/utils.py:325-332` retries only `GET`/`DELETE`, and `config/binance/binance-limits-v1.toml:12` sets `sdk_retries = 0`. `ExecutionService._place` awaits the manager once (`execution_service.py:246`). Recovery uses `IntentProbeAdapter`, a Protocol with two query methods and no placement method (`intent_recovery.py:120-125`).
2. **Ambiguous placement => one probe => UNKNOWN + SAFE_MODE.** Any non-definitive exception or a `None` response goes to one `query_order_by_client`; a probe error or `found is not True` returns `ENTRY_STATE_UNKNOWN` (`manager.py:383-410`); the caller enters SAFE_MODE, writes UNKNOWN and still hands the entry to the protection registry flagged `entry_state_unknown` (`1351-1389`).
3. **Write-ahead order.** consume (INTENDED, one DB transaction with the approval stamp) -> plan snapshot -> `mark_sent` (SENT, committed) -> POST -> result -> hand-off -> outcome (`manager.py:1229-1461`). Crash before `mark_sent`: row INTENDED, recovery probes once, absent => REJECTED/NEVER_SENT (`intent_recovery.py:253-272`). Crash during the POST: row SENT => UNKNOWN, probe; found => ACKED; absent => stays UNKNOWN + SAFE_MODE (`294-343`, `386-388`), closed later only by `UnknownEntryResolver` on N clean probes + GTD + grace + flat + no open order (`578-631`; values 3 probes, 5 s apart, 30 min grace). SENT/UNKNOWN/ACKED entries are re-tracked at start (`execution_state.py:204-247`).
4. **The approval is consumed exactly once, arbitrated by the database.** `INSERT ... ON CONFLICT DO NOTHING (approval_id, role)` then `UPDATE approvals ... WHERE consumption_status = UNCONSUMED AND status = APPROVED AND approved_quantity = :bound AND approved_quantity >= :intended` in the same transaction; `rowcount != 1` rolls the insert back (`execution_state.py:313-350`). A replay returns the stored outcome with no adapter call (`manager.py:755-763`, `1259-1269`); an ENTRY row without outcome replays as RECONCILIATION_REQUIRED (`1731-1744`).
5. **Two presses racing / at-least-once callbacks.** APPROVE: conditional store write, the loser gets the stored row (`replay.py:278-289`). CONFIRM: book lock, state checked before anything, a non-PENDING entry replays (`confirm_core.py:1037-1044`), `on_confirmed` is appended once per CONFIRM (`1151-1153`). A second approval of the same symbol while one is placing is refused in-process (`manager.py:516-544`).
6. **Plan binding (D078).** Symbol and side sent to the exchange come from `bound` (the persisted Signal), never from caller values (`manager.py:928, 947-948, 1340-1341`); the hash is recomputed (`binding.py:147-153`); the Signal direction must agree with the stop/zone geometry (`176`); a quantity above the approved one is refused (`manager.py:953-960`) and the DB re-checks it at consume.
7. **`LIVE_ORDERS_DISABLED` is affirmative.** Controller default `_disabled = True` (`enablement.py:112`); every start builds a fresh disabled controller and overwrites a persisted "enabled" (`live/enablement.py:172-211`); the only `enable()` call in `src` is in `enable_demo`, which raises for any mode but DEMO (`234-237`; grep: one call site); `LIVE_RUNTIME_MODE=LIVE` is refused at admission because the class default is disabled (`live/config.py:200-208`); the REST URL comes from the environment row, not from a variable (`binance_client.py:151-158`). No env or config key flips the flag. (In DEMO the flag IS enabled automatically after a passing health verdict: intended.)
8. **No placement after a restart for an old CONFIRM.** `_sweep_orphans` skips approvals that already have a terminal confirm event and never calls `on_confirmed` (`confirm_core.py:1307-1345`); raw approve tokens are memory only, so `_place` refuses with TOKEN_UNAVAILABLE (`execution_service.py:214-217`).
9. **Price rounding never increases risk.** BUY limit floors, SELL ceils; the stop trigger rounds toward the entry; TP toward the entry (`placement.py:191-210`); post-snap geometry guard (`binding.py:232-256`).
10. **Fail-closed reads.** Each failed live read is `None` and refuses (`manager.py:1000-1057`, `1464-1469`); an unreadable registry counts as unprotected (`1014-1017`); an unknown position mode refuses (`1063-1071`); a sizing equity above the live equity refuses (`1136-1146`).

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D080 never re-send; ambiguous => probe once => UNKNOWN + SAFE_MODE | SOUND | exchange behaviour (client id unique only among open orders; -1007 "status unknown"), fail-closed goal | Worst case is a missed trade; a resend risks a double position. The code matches at every layer (safe areas 1-3). |
| D078 quantity bound stored on the approval row, `<= approved`, **refuse instead of clip** | DOUBTFUL | arithmetic (probe), owner goal | The bound is right; refusing a placement because the account could afford one more lot step reduces no risk and loses trades (G-0202). |
| D051(c) plan hash excludes symbol, direction, quantity | DOUBTFUL (mitigated) | logic | The identity hash does not cover what is traded; compensated by `signal_id` in the hash, the persisted Signal, the geometry cross-check and the approval-row quantity. I found no path around the compensations. |
| D041 APPROVE -> CONFIRM within 60 s, pre-placement checks re-run | SOUND | practice | A real two-step, user-bound, TTL judged at decision time (`confirm_flow.py:402`). The wording about a "confirm token" overstates (G-0204). |
| D079 (my part): GTD LIMIT entry, no entry-time stop | CANNOT_JUDGE here | exchange (Demo -4509 recorded, not mainnet) | Forced by the recorded Demo rejection; the residual risk (a fill while the process is down) belongs to M03. |
| `GTD_MIN_AHEAD_SECONDS = 600` + margin; `min_remaining_validity_seconds = 900` | SOUND | recorded Demo observation (-5040 at 599 s, `exchange_errors.py:419-428`) | Consistent with the goodTillDate rule; 900 s leaves room. Not re-read on the web in this run. |
| Zone-mid limit, sizing at the adverse zone edge | SOUND | arithmetic | Fill <= limit <= sizing entry for a LONG, so the realised stop distance is at most the sized one. |
| WR-06 "adverse side only" price refusal (a LONG above the zone may rest) | SOUND for safety; CANNOT_JUDGE for research parity | logic | A resting pullback limit is bounded by GTD. Whether the backtest fills the same way is another lane's question. |
| D-04 `LIVE_ORDERS_DISABLED` default, journal-first enable, act-first disable | SOUND | fail closed | See safe area 7. |
| Headroom literal 200 "account-wide" (`gates.py:27-42`) | CANNOT_JUDGE | exchange docs not fetched | The comment itself says "re-verify before wiring"; three legs per plan and a handful of plans keep the system far from it. |
| UNKNOWN entry closed on 3 not-found probes 5 s apart + GTD + 30 min grace + flat | SOUND | exchange retention rule, fail closed | Conservative; a filled order stays queryable, so a fill is not mistaken for absence. |
| "Gates run before the consume so a refusal can be retried" (manager docstring) | DOUBTFUL | logic | The CONFIRM is single use (`confirm_core.py:1037`), so the human has no retry; the claim holds only for a programmatic caller. Part of G-0202 and G-0205. |

## Findings

### G-0201
- **Severity:** LOW now / MEDIUM on mainnet with placement enabled · **Confidence:** PROBABLE (code path traced, no runtime probe) · **Classification:** GAP · **Category:** gate ordering / time of check
- **Component:** execution manager · **File:** `src/execution/manager.py` · **Lines:** 823-847, 1000-1165, 1229-1349
- **Rule:** AGENTS.md "SAFE_MODE blocks entries", "no new entry opens while any position is unprotected" (D-11), enablement gate 2 · **Known-prior:** partly: 22-REVIEW WR-02 closed the same window for the clock-dependent checks only (gate 5f4)
- **Evidence:** enablement is read once (`:823`), SAFE_MODE once (`:841`, `safe_mode_controller.guard_new_entries(...)`), the unprotected-position flag once (`:1015`, `blocks_new_entries()`). After that the function awaits five REST reads (`:1000-1013`), `get_position_mode` (`:1064`) and the margin guard (`:1105`; `margin_guard.py:342, 357, 393, 428` are four more awaits, one of which may POST a margin configuration). Gate 5f4 re-evaluates with `replace(pre_placement_inputs, now_utc=..., mark_checked_at_utc=..., last_checked_at_utc=...)` (`:1156-1163`) and its comment says "The readings themselves are unchanged": `any_unprotected` is the value from before the guard. Nothing between `:1165` and the POST at `:1337` reads enablement, SAFE_MODE or the registry again (grep: `guard_new_entries`, `guard_placement` and `blocks_new_entries` each occur once in the file).
- **Expected:** the three state gates hold at the moment the approval is consumed and the order is sent.
- **Actual:** they held some hundreds of milliseconds to several seconds earlier (bounded by the REST timeouts of about ten calls). SAFE_MODE entered, live orders disabled (kill gate, operator) or another position becoming unprotected inside that window does not stop the entry.
- **Reproduction:** a test with a fake margin guard whose `evaluate` calls `safe_mode_controller.enter_safe_mode(...)` (or `enablement.disable(...)`) before returning a pass should show outcome `OK` and one `place_entry` call. Not run in this audit.
- **Impact:** a new entry can be sent while SAFE_MODE is on or while a position on another symbol is unprotected. The entry is still handed to the protection coordinator, so this is an invariant breach in a narrow window, not an unmanaged order. It needs a SAFE_MODE or disable event within seconds of a human CONFIRM.
- **Why tests miss it:** the fakes change no state during the awaits; WR-02 was fixed and tested for price age and validity only.
- **Remediation:** run the three synchronous guards again immediately before `consume_and_record_entry_intent` (no await lies between the consume and the hand-over of the POST to the worker thread) and refuse without consuming.

### G-0202
- **Severity:** LOW now / MEDIUM on mainnet (missed trades and a selection effect, no loss) · **Confidence:** PROBABLE · **Classification:** DESIGN · **Category:** sizing vs approval bound
- **Component:** plan binding · **File:** `src/execution/manager.py`, `src/execution/binding.py`, `src/live/risk_inputs.py` · **Lines:** manager 953-960; binding 204-222; risk_inputs 631-638, 684-686
- **Rule:** D078, D-02 / RISK-04 ("refused, never clipped") · **Known-prior:** the coupling is acknowledged in `src/live/signal_source.py:487-491` ("the binding never clips ... so a request meant to be placed is sized from that same equity"); it is not recorded as a risk
- **Evidence:** the approved quantity is the plan's `quantity_after_rounding`, fixed when the request is issued (`approval_desk.py:399`). At CONFIRM the manager sizes again from equity refreshed at that moment (`risk_inputs.py:632-638`) and refuses when the new quantity is larger: `return ExecutionOutcome(is_no_trade=True, reason_code=QUANTITY_ABOVE_APPROVED)`. Probe `tmp/exec_placement/probe_qty.py` (risk rate 0.005, stop 1 %, the formula of `src/risk/sizing.py:45-48`, the real `check_quantity_bound`; step sizes are my assumptions):
  - `equity 1000 XRPUSDT: approved 181.9, +0.55 USDT (0.055 %) -> sized 182.0: QUANTITY_ABOVE_APPROVED`
  - `equity 1000 ETHUSDT: approved 0.129, +0.55 USDT (0.055 %) -> sized 0.130: QUANTITY_ABOVE_APPROVED`
  - `equity 500 XRPUSDT: approved 90.9, +0.28 USDT (0.056 %) -> sized 91.0: QUANTITY_ABOVE_APPROVED`
  - `equity 1000 BTCUSDT: approved 0.004, +99.50 USDT (9.950 %) -> sized 0.005` (coarse step: practically never)
- **Expected:** "quantity may be <= approved, never larger" (AGENTS.md): placing the approved quantity when the account allows more satisfies the rule.
- **Actual:** the placement is refused whole. Equity is the smaller of wallet and margin balance (D086), so it rises between the request and the CONFIRM whenever an open position's unrealised loss shrinks, a position closes in profit or funding is received. On fine-step symbols a rise of a few tenths of a USDT is enough. The CONFIRM is single use, so the human cannot press again; the plan is lost.
- **Reproduction:** `python -B probe_qty.py` in `tmp/exec_placement` (PYTHONPATH = snapshot).
- **Impact:** no money risk. Trades are skipped exactly when equity ticked up since the alert, which biases the set of live trades against the backtest/paper set and would show in the Phase 25 Demo campaign as unexplained NO_TRADE rows. How often it happens depends on which equity the real strategy producer sizes from; I could not check that, because `src/live` contains only the smoke signal source.
- **Why tests miss it:** tests pass the same equity at issue and at placement; the smoke source was changed to do the same (plan 24-27B).
- **Remediation (owner choice, see Owner decisions):** place `min(sized, approved)`, or keep the refusal and say so on the card.

### G-0203
- **Severity:** LOW now / MEDIUM on mainnet · **Confidence:** SUSPICIOUS (no concrete trigger found) · **Classification:** IMPROVEMENT · **Category:** exception / cancellation window
- **Component:** execution manager · **File:** `src/execution/manager.py` · **Lines:** 1291-1302, 1337-1349, 1425-1445
- **Rule:** D034 "protection outranks the audit row"; D-10 hand-off · **Known-prior:** none found
- **Evidence:** after the POST returns, the ACKED row is written through `_store_write`, which catches `PersistenceError` only (`:1296-1301`), and only then `register_resting_entry` runs (`:1445`). `adapter.place_entry` runs in a worker thread (`binance_usdm.py:897`, `asyncio.to_thread`), so a cancellation of the awaiting task does not stop the POST. Any other exception class from the store write, or a `CancelledError` at `:1337`, leaves the function before the hand-off. In the running process nothing re-tracks a SENT row: `restorable_entries` is a start-up read and `UnknownEntryResolver` takes UNKNOWN rows only (`intent_recovery.py:544-551`).
- **Expected:** once the entry may exist, the hand-off to protection happens whatever else fails.
- **Actual:** it depends on no unexpected exception class and no cancellation. `uow.py:44-58` translates the known SQLAlchemy families and the runtime drains placement tasks instead of cancelling them, so I found no trigger; the reconcile tick should report the order as untracked and enter SAFE_MODE.
- **Reproduction:** a fake store whose `record_result` raises `RuntimeError` after a successful `place_entry`: `register_resting_entry` is not called. Not run.
- **Impact:** a resting GTD entry that the coordinator does not watch until the reconcile notices it or the process restarts; a fill in between gets no stop from the coordinator.
- **Why tests miss it:** store fakes raise `PersistenceError` only.
- **Remediation:** hand off first, or put the post-POST section in `try/finally` and shield it from cancellation.

### G-0204
- **Severity:** INFO / INFO · **Confidence:** CONFIRMED · **Classification:** DRIFT · **Category:** documentation vs mechanism
- **Component:** approval / confirm · **File:** `src/approval/confirm_core.py`, `src/live/execution_service.py`, `src/approval/mapping.py`, `src/execution/intent_recovery.py` · **Lines:** confirm_core 285-287, 851-852; execution_service 214-232; mapping 44-55; intent_recovery 49-50
- **Rule:** D041 ("confirm token ... single-use, bound to the same authorized user id and plan hash"); manager gates 0 and 1 · **Known-prior:** review WR-07 is cited in the code
- **Evidence:** "`raw_token` is held but no press carries or compares it" (`confirm_core.py:285-287`); the buttons carry `sha256(signal_id)[:32]`, which is derivable, not secret (`mapping.py:44-55`). The manager's chat and token gates check a `Callback` that `ExecutionService._place` builds itself from `self._authorized_chat_id` and the desk's in-memory token (`execution_service.py:223-232`), so they cannot fail for a real press. Stale text: `intent_recovery.py:49-50` says the resolver is "not wired into a live process" while `src/reconcile/startup.py:56` and `src/live/reconcile.py:246` wire it; `confirm_recheck.py:3` names `src/paper/shadow_confirm.py` as the confirm core.
- **Expected:** the documents describe proof by token. · **Actual:** the real controls are the Telegram chat id, the user allow-list, the user bound at APPROVE, the in-memory entry state and the DB consume. Those are adequate for a private bot chat; the token adds nothing.
- **Reproduction:** read the cited lines.
- **Impact:** none on safety. A reader of D041 or of the manager docstring over-estimates what the binding gate proves.
- **Why tests miss it:** it is not a behaviour. · **Remediation:** reword D041 and the manager docstring; fix the two stale docstrings.

### G-0205
- **Severity:** LOW / LOW · **Confidence:** PROBABLE · **Classification:** IMPROVEMENT · **Category:** approval consumed without a send
- **Component:** execution manager · **File:** `src/execution/manager.py`, `src/adapters/binance_usdm.py` · **Lines:** manager 377-382, 1390-1406; adapter 1362-1363
- **Rule:** manager docstring "the new gates all run BEFORE the approval is consumed" · **Known-prior:** `_journal_entry_refused` exists because the first Demo rehearsal hit this (`manager.py:1588-1589`)
- **Evidence:** the clock-drift guard is consulted only inside `place_entry` (`self._require_entries_allowed()`), after the consume and `mark_sent`. A `PreSendRefusal` then closes the ENTRY row REJECTED and the approval stays consumed. The reads of gate 5e do not pass through the drift guard, so they do not catch it earlier.
- **Expected:** a condition known before sending refuses before the approval is spent. · **Actual:** the approval is spent and nothing is sent.
- **Reproduction:** drift guard that blocks entries + otherwise passing inputs: outcome `ENTRY_REFUSED_BEFORE_SEND`, ENTRY row REJECTED. Not run.
- **Impact:** a lost trade with a correct, fail-closed outcome. · **Why tests miss it:** it is the tested behaviour. · **Remediation:** expose the drift-guard verdict as a gate before the consume.

## Owner decisions
1. **Clip or refuse (G-0202).** Example: the XRPUSDT alert shows quantity 181.9 with equity 1000.00. Before you press CONFIRM, a funding payment or a recovering open position lifts equity to 1000.55 and the system now computes 182.0. Today nothing is placed (QUANTITY_ABOVE_APPROVED) and the card cannot be confirmed again. The alternative is to place 181.9, the quantity you approved (risk slightly below budget). Both respect "never more than approved".
2. **Disable or SAFE_MODE during an in-flight CONFIRM (G-0201).** Example: you press CONFIRM for ETHUSDT; one second later the kill gate disables live orders, or SAFE_MODE starts because of another position. Today the ETH entry is still sent. Decide whether that is acceptable or whether the check must be repeated at the last moment (cost: one more refusal reason).

## Open Questions
- (live lane) `src/live` has only the Demo smoke `signal_source.py` as a producer of approval requests. Where does a real strategy signal become a DEMO/LIVE request, and from which equity is its quantity sized? The frequency of G-0202 depends on it.
- (M03) `tp_sizing.size_take_profits` has no caller I could find outside its own module, while gate 5d and `attach_protectives_to_fill` use the frozen `size_protectives_to_filled_qty`. Is the "live take-profit sizing" of plan 19-07 dead code?
- (M03) A fill while the process is down has no stop until restart (D079). Not judged here.
- (adapter / taxonomy lane) `REJECTED_DEFINITIVE` on a placement skips the probe and SAFE_MODE (`manager.py:385-386`). Does `classify` look at the HTTP status, so that a 5xx carrying a listed code is not treated as definitive?
- (paper lane) With a `ReservationPort` (SHADOW), a CONFIRM whose reservation is refused leaves the entry CONFIRMED (`confirm_core.py:1146-1150`) and a second press answers "REPLAYED existing outcome (CONFIRMED)" (`734-735`). The DEMO/LIVE flow passes no port (`confirm_flow.py:182-191`), so it is outside my path.
- (live lane) Placement tasks are drained at shutdown; a forced loop close would cancel them (see G-0203).
- The 200 conditional-order limit and the goodTillDate rule were not re-read on developers.binance.com in this run.

## DONE
