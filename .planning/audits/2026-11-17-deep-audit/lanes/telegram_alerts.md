# Lane M08: telegram_alerts

## Scope
`src/adapters/telegram_*.py`, `src/ops/{alerts,alert_wording}.py`, `src/live/{approval_sender,telegram_runner,alerts}.py`,
`src/paper/notify.py`; plus (left unread by M02) `src/execution/confirm_flow.py:470-894` and the send/reply/finalize parts of
`src/execution/approval_desk.py`. Finding IDs G-0800..0899.

## Coverage
| File | Level | Note |
|---|---|---|
| src/adapters/telegram_callbacks.py | DEEP_READ | all 1472 lines |
| src/adapters/telegram_notify.py | DEEP_READ | all 1157 lines |
| src/live/telegram_runner.py | DEEP_READ | |
| src/live/alerts.py | DEEP_READ | |
| src/live/approval_sender.py | DEEP_READ | |
| src/ops/alerts.py | DEEP_READ | sink, sender, observer; OPS05_MATRIX rows NORMAL_READ |
| src/execution/confirm_flow.py | DEEP_READ 1-894 | includes the 470-894 part M02 left |
| src/execution/approval_desk.py | DEEP_READ 160-1025 | send, resolve, dispatch, reply_fn, finalize_hook, finalize_expired_requests |
| src/live/operator.py | NORMAL_READ 130-520 | only the command gate `_authorize` and the token book (the rest belongs to the live lane) |
| src/live/execution_service.py | NORMAL_READ 150-420 | only to see what the operator is told after CONFIRM |
| src/ops/alert_wording.py | DEEP_READ | all 489 lines |
| src/paper/notify.py | NORMAL_READ 115-367 | SIMULATE renderer and bounded send; no approval path |
| src/live/wiring.py | NORMAL_READ 836-935, 1028-1135, 1250-1295 | bot, runner, sender, pump, alert drain, start order |
| src/live/health.py | METADATA_ONLY 205-245 | `TelegramDeliveryObserver` only |
| src/persistence/risk_reservations.py | METADATA_ONLY 96-112, 395-455 | only which refusal an APPROVE can meet |
| src/risk/money_at_stake.py | METADATA_ONLY | outline; entry price = `sizing_entry_price` |
| src/live/signal_source.py | METADATA_ONLY 600-625 | `exposure_quote`, leverage source of the only live source |
| docs/integration/TELEGRAM.md | NORMAL_READ | sections 1-6 and "Phase 24: the live bot" |

## Verified Safe Areas

1. **User-id authorisation on every callback.** `on_callback` validates a non-empty frozenset of ints (`telegram_callbacks.py:1100`), then `_answer_press` runs the chat gate and `authorized_user_gate` (user id present, chat type exactly `private`, membership) before any lookup, confirm handler or dispatch (`1233-1287`). `dispatch_callback` repeats both gates with mandatory keywords (`411-464`), and `ApprovalDesk.dispatch` refuses a call without the allow-list (`approval_desk.py:666`). The live runner uses only `functools.partial(on_callback, ...)` (`telegram_runner.py:143`) and validates the list at construction (`94`). An empty list, a plain set, a bool or a str member raises.
2. **User-id authorisation on every command.** `OperatorCommands._authorize` and the Demo injection `_authorize` run the same two gates before any action (`src/live/operator.py:440-470`, `src/live/smoke_injection.py:195-225`); each handler returns at once on None. `/safemode_exit` and `/close` need a one-time token bound to the asking user, 60 s, single use, hash only in memory (`operator.py:475-505`). `ALLOWED_UPDATES = ["callback_query", "message"]` (`telegram_runner.py:64`), so edited messages and channel posts never arrive.
3. **callback_data size and shape.** The payload is a 4-byte prefix plus 32 hex = 36 bytes, re-checked against 64 (`telegram_notify.py:167-193`); the parser refuses anything over 64 bytes, an unknown prefix, a wrong length or non-lowercase-hex before any state is touched (`telegram_callbacks.py:170-216`). No token travels in callback data (`approval_desk.py:561-576`).
4. **Replay and duplicates.** The correlation id is Telegram's `callback_query.id`; journal ids are pure functions of it, so a redelivery writes the same rows (`telegram_callbacks.py:1142-1147, 700-720`). A repeat of a decided press returns the stored row with `already_decided=True`; the sibling button raises `ApprovalDecidedDifferently` (`590-615`). A repeated APPROVE never issues a second confirm (`confirm_flow.py:262-270`); a repeated CONFIRM answers "Already confirmed. Nothing changed." (`471`). CONFIRM/CANCEL can never be read as an approval (`147-152, 478-492`). SIM:/SKIP: never move state.
5. **A notification failure never approves.** `ApprovalDesk.send` only journals and returns (`approval_desk.py:540-557`); the Signal moves to NOTIFIED only after a successful send (`approval_sender.py:343-350`); a card that cannot be delivered after APPROVE expires the confirm with CARD_DELIVERY_FAILED (`confirm_flow.py:367-382`). No path from a send or edit failure reaches `on_confirmed`.
6. **Only messages are retried.** `call_bounded`, `send_text_bounded`, `finalize_decided_message` and `_send_bounded` wrap bot send and edit calls only; no module in scope imports the manager or the Binance adapter. A refusal (BadRequest, Forbidden, InvalidToken) is not retried; a RetryAfter above 30 s stops without sleeping (`telegram_notify.py:514-544`).
7. **The card shows what will be executed.** The request text is built from the plan and the STORED money block; `require_money_consistent` compares side, quantity, stop, TP prices and shares and the entry zone at issue time and again before the confirm card and every final text (`telegram_notify.py:860-905`, `approval_desk.py:616-644`, `confirm_flow.py:229, 555`). `approved_quantity` on both rows is the plan's `quantity_after_rounding`, and the approval is bound to `plan.plan_hash` (`approval_desk.py:398-400`). The loss at SL is computed at the sizing entry price (the adverse zone edge per M02), an upper bound for a limit fill before slippage on the stop. The executed quantity may be lower, never higher (M02).
8. **Stale card after a plan change.** One request per short id per process (`approval_desk.py:381-383`); the binding context carries the plan hash, strategy version and parameter set hash of the request, and the expiry is the plan expiry (`561-576`). After a restart the memory is empty: APPROVE is refused INVALIDATED (`telegram_callbacks.py:520-535`), CONFIRM finds no context, and the keyboard is removed. A changed plan cannot be approved through an old card.
9. **Keyboard removal and edit failures.** A decided message is edited to its final text with an empty keyboard in one call, with one keyboard-only fallback; a failure is journaled and never changes a decision (`telegram_notify.py:578-620`). The guard against a stale tap is the stored state. Whether an empty `InlineKeyboardMarkup` removes the buttons on the live API is the project's own open assumption A1.
10. **Handler errors.** An exception after the gates is caught, journaled by class name and answered neutrally in the authorized chat only; `CancelledError` propagates (`telegram_callbacks.py:1149-1215`). No exception text, token or callback data is logged.
11. **The alert contract is closed and every raise site is inside it.** All raise sites (`daily_stop.py:217`, `emergency_close.py:947,998`, `manager.py:1687,1719,2998`, `protection.py:1872,2673,2769,2780`, `scheduled_cancel.py:293`, `wiring_parts.py:302`, `reconcile/loop.py:750,947,1153,1370`) use constants whose values are keys of `ALERT_EVENTS`. Free text cannot reach a message: subject, reason, symbol and plan hash are regex-checked and replaced (`alerts.py:142-150, 262-281`). Journal first, then queue, even when the journal write raises (`505-509`). A SAFE_MODE entry with no dedicated producer alerts `SAFE_MODE_ENTERED` (`800-815`).
12. **Start order.** Undelivered alerts are re-queued, then the bot starts, then the scheduler (`wiring.py:1256-1260`), so the first drain has a bound bot.
13. **A press from a foreign chat.** Reachable only if the bot posted a keyboard there, which it does not. The refusal is journaled; the bot answers "Rejected" in that chat (`telegram_callbacks.py:1253-1257`), with no state effect.

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| Phase 23 D-01/D-02: chat gate AND user allow-list AND private chat, never allow-all | SOUND | Telegram semantics (a group press carries the group chat id), fail closed | Two independent gates; the list is mandatory at every entry point. |
| callback_data = prefix + sha256(signal_id)[:32], no token in it | SOUND | Bot API limit of 64 bytes (from memory; core.telegram.org not fetched in this run) | 36 bytes; the secret stays server side. |
| D-04: raw tokens, request text, message ids in memory only | SOUND for safety, costly in use | fail closed vs owner goal | A restart kills every outstanding card; the PENDING rows then block their symbols until plan expiry. |
| D041 two-step APPROVE then CONFIRM, 60 s, bound to the approving user | SOUND | practice | See M02; here: the card is rebuilt from stored money and re-checked. |
| D-13 / F-015: money shown from the stored block, never recomputed | SOUND | arithmetic, logic | One source for request, card and finals; consistency is re-checked. |
| Q5 / D080: only messages are retried | SOUND | owner rule | Verified by imports and call sites. |
| `drop_pending_updates=False` (P-5) | SOUND | logic | A replay is answered from stored state; with tokens in memory an old press cannot decide anything. |
| D103: one bot token per process | SOUND | one getUpdates consumer per token | A Conflict is logged once (`telegram_runner.py:253-256`). |
| D-23: dedupe window 300000 ms on (event, subject, reason), started whether or not the alert was delivered | DOUBTFUL | probe, practice | Labelled DECISION with no derivation; the key ignores the plan and the delivery state (G-0801). |
| NOTIFY budget 3 attempts / 30 s for CRITICAL alerts | DOUBTFUL | practice | Taken from the paper SIMULATE notifier; sized for a courtesy message, not a safety alert. |
| WR-C6 / R-02 "owner decision, later plan" | WRONG to leave open before mainnet | owner goal (fail closed, part-time) | A problem closed by marking it an owner item (G-0801). |
| D-14 plain-word alerts | SOUND where done, incomplete | owner goal (little trading expertise) | 13 of 23 events, three CRITICAL, are still raw codes (G-0804). |
| D025 / O-3 local +07 time first, UTC in brackets | SOUND for cards; not applied to alerts | consistency | Alerts print UTC only (G-0804). |
| TELEGRAM.md "The final text states what the stored entry intent says" | DOUBTFUL | logic (ordering) | True in the fake-driven test; in the composed process the text is built before the placement task runs (G-0802). |
| A refusal makes the request final unless it is a store or handler error | DOUBTFUL | logic | The list of curable reasons is too short (G-0803). |

## Findings

### G-0801
- **Severity:** MEDIUM now / HIGH mainnet · **Confidence:** CONFIRMED · **Classification:** DESIGN · **Category:** alert delivery
- **Component:** operator alerts · **File:** `src/ops/alerts.py` · **Lines:** 733-772
- **Rule:** OPS-05; D-23; KNOWN: 20-DEFERRED WR-C6, 24-DEFERRED R-02 (deferred to the owner, no severity recorded) · **Known-prior:** KNOWN:20-DEFERRED.md:117 (WR-C6), 24-DEFERRED.md:101 (R-02), src/live/alerts.py:30-31. Reported because it is closed by deferral and described too mildly (docs/integration/TELEGRAM.md, Delivery: "a failed send is retried by the alert requeue at the next start").
- **Summary:** A CRITICAL alert whose Telegram send fails (3 attempts, at most 30 s) is dropped for the life of the process, and the 5 minute dedupe window also swallows its repeats, including a different plan on the same symbol.
- **Evidence:** `drain`: `alert = self._queue.popleft()`; on failure only `EVENT_ALERT_SEND_FAILED` is journaled (alerts.py:737-763) and nothing appends the alert again. `_accept` dedupes on `key = (alert.event, alert.subject, alert.reason)` whether or not the first alert was delivered (alerts.py:489-510). Budget `NOTIFY_MAX_ATTEMPTS = 3`, `NOTIFY_MAX_DELAY_SECONDS = 30` (src/paper/notify.py:115-116); `dedupe_window_ms = 300000` (config/execution/execution-limits-v1.toml:68). Probe tmp/telegram_alerts/probe_alert_lost.py: `drain while Telegram is down: SendReport(delivered=0, failed=1, audit_lost=0) queue left: 0` / `drain after recovery: delivered=0 ... sent: 0` / `repeat at +2 min ... sent: 0` / `other plan at +4 min ... sent: 0` / `repeat at +6 min: delivered=1`.
- **Expected:** An alert that says a position may be unprotected reaches the operator once Telegram is reachable again (in a human-in-the-loop system, fail closed includes telling the human).
- **Actual:** One-shot producers (CLOSE_REQUIRED once per plan, protection.py:2769; EMERGENCY_CLOSE_FAILED / NOT_SENT, emergency_close.py:947,998; the SAFE_MODE on_enter observer; the first DAILY_STOP alert) are never heard unless the process restarts. Repeating producers come back only after the window. The only in-process trace is the health item `telegram_delivery` (src/live/health.py:223-228), which messages nobody.
- **Reproduction:** PYTHONPATH=snapshot python -B tmp/telegram_alerts/probe_alert_lost.py
- **Impact:** The failures that raise these alerts (network loss, exchange or API trouble) are the same that make a Telegram send fail, so the alert most likely to be lost is the one for a real incident. Now (Demo): a missed drill message. Mainnet: a position with no stop after a failed emergency close can stay open with the owner unaware.
- **Why tests miss it:** Tests pin the ALERT_SEND_FAILED row and the restart re-queue; none asserts that a failed CRITICAL alert is delivered later in the same process, because the behaviour was accepted as a known limit.
- **Remediation:** Keep a failed CRITICAL/HIGH alert queued and try again on later drains until delivered (original time in the text); do not suppress repeats while the first alert of the episode is undelivered; add the plan hash to the dedupe key of per-plan events. Consider a second channel or a check for "alert undelivered for N minutes".

### G-0802
- **Severity:** MEDIUM now / MEDIUM mainnet · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** operator information
- **Component:** confirm flow / execution service · **File:** `src/execution/confirm_flow.py` · **Lines:** 525-629
- **Rule:** docs/integration/TELEGRAM.md Phase 23 rules ("The final text states what the stored entry intent says"); owner goal: part-time operator · **Known-prior:** none found
- **Summary:** After CONFIRM the operator is never told on Telegram what happened to the order: the card is frozen at "handed to the execution step; no entry recorded yet", and a refused placement, an acknowledged order, a fill, the stop being placed and the exit produce no message.
- **Evidence:** `finalize_message` edits the card once, right after the press (confirm_flow.py:625-629), from `_placement_lines`, which returns `PLACEMENT_NOT_RECORDED` when no intent is stored (541-544). `ExecutionService.on_confirmed` only schedules `_place` (execution_service.py:150-165); `_place` first awaits `self._inputs.for_plan(...)` before `execute_approved_plan`, so no intent exists when the text is built (ordering is a trace, not a run). `_edit_final` is called only from a press and from the TTL sweep for EXPIRED entries (confirm_flow.py:625, 796); the keyboard is gone, so no later press re-edits. A NO_TRADE outcome is only journaled (`payload={"is_no_trade": ..., "reason_code": ...}`) and the reservation released (execution_service.py:262-285). Grep of every send_text / send_text_bounded / send_message / edit_text / finalize_decided_message call in src: desk, confirm flow, alert sender, operator replies, health probe; none reports a placement outcome, a fill or an exit. The closed alert set (ops/alerts.py:96-133) has no such event.
- **Expected:** The human who pressed CONFIRM learns whether the entry was placed, refused (and why), filled, protected and closed, without reading the journal.
- **Actual:** The card reads CONFIRMED and "Placement: handed to the execution step; no entry recorded yet" for good. With LIVE_ORDERS_DISABLED, a price or margin refusal, or QUANTITY_ABOVE_APPROVED (lane M02, G-0202) the operator still sees CONFIRMED and nothing else. Only protection failures alert; a normal fill, a stop-out or a take-profit is silent. `/status` is the only pull.
- **Reproduction:** Trace above; tests/fixtures/phase23/messages/confirm_final_confirmed_demo.txt:7 and tests/test_confirm_flow.py:343 pin this text as the CONFIRMED final.
- **Impact:** Wrong picture for the operator: he may believe a position is open when nothing was placed, or miss a stop-out. No direct money path. Mainnet: the same with real positions; the owner has to watch the exchange app.
- **Why tests miss it:** The fixture pins the immediate text as correct; no test asks what the operator sees after the placement task ends.
- **Remediation:** When `_place` ends, send one message (or re-edit the card) with the outcome and reason code; add informational messages for entry filled, stop confirmed and position closed with realised PnL. Messages only, never a placement retry.

### G-0803
- **Severity:** LOW now / MEDIUM mainnet · **Confidence:** PROBABLE · **Classification:** DEFECT · **Category:** approval UX / lost decision
- **Component:** approval desk · **File:** `src/execution/approval_desk.py` · **Lines:** 118-121
- **Rule:** approval_desk.py:118 comment: "Refusals a second tap can still cure: the keyboard stays" · **Known-prior:** none found
- **Summary:** An APPROVE refused for a curable cause other than the two listed (for example UNCERTAIN_ACCOUNT_STATE from the reservation gate) makes the request final and removes its buttons while both approvals stay PENDING, so the plan can never be approved and the symbol stays blocked until the plan expires.
- **Evidence:** `_TRANSIENT_REASONS = frozenset({APPROVAL_STORE_FAILURE, CALLBACK_HANDLER_ERROR})` (approval_desk.py:119). `ReservationRefused(ApprovalRejected)` carries a cap, DAILY_STOP_BLOCK or UNCERTAIN_ACCOUNT_STATE; the last is raised when the day row is missing, the thresholds are None or the gate says so (risk_reservations.py:101-110, 412-441). `dispatch_callback` returns `DispatchResult(ok=False, reason_code=exc.reason_code)` (telegram_callbacks.py:640-653); `_classify` gives `DeskOutcome.REFUSED` (approval_desk.py:730); `finalize_hook` builds `_state_text(request, now_utc=now, refused_code=refused)` = "Refused: <code>; no decision was taken." and `finalize_decided_message` removes the keyboard (903-935, 847-848). The save was rolled back, so the rows are PENDING and the open-approvals reader keeps the symbol in conflict until `plan.expiry_utc` (approval_sender.py:411-418, 538-556).
- **Expected:** A refusal that depends on a momentary state leaves the buttons so the operator can tap again; only a refusal that cannot change ends the card.
- **Actual:** One tap at a bad moment ends the request. The text says "no decision was taken" and offers no way to take one.
- **Reproduction:** Code trace only; a run needs the PostgreSQL reservation store, which this audit does not use.
- **Impact:** A valid plan is lost and its symbol blocked for the rest of the plan validity. No unsafe order. Mainnet: missed trades, and an operator who cannot tell a hard refusal (daily stop) from a passing one.
- **Why tests miss it:** Desk tests use fakes whose save succeeds or raises a store error; the reservation refusals are tested in the persistence layer without the Telegram finalize step.
- **Remediation:** Classify refusal reasons explicitly: keep the keyboard for UNCERTAIN_ACCOUNT_STATE and say so; end the card for caps and DAILY_STOP_BLOCK with a plain sentence.

### G-0804
- **Severity:** LOW now / MEDIUM mainnet · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** alert wording
- **Component:** alert wording · **File:** `src/ops/alert_wording.py` · **Lines:** 257-420
- **Rule:** Phase 23 D-14 (plain-word alerts); D025 / O-3 (local +07 time first) · **Known-prior:** none found
- **Summary:** 13 of the 23 alert events have no plain-word text, three of them CRITICAL (UNPROTECTED_POSITION, PROTECTIVE_REJECTED, DAILY_STOP); every alert shows UTC time only and no DEMO/LIVE mode line.
- **Evidence:** `EVENT_WORDING` holds TP_UNAVAILABLE, EMERGENCY_CLOSE_FAILED, EMERGENCY_CLOSE_NOT_SENT, ENTRY_STATE_UNKNOWN, PROTECTION_HANDOFF_FAILED, DB_FAILURE, REST_GATE_BAN_ENTERED, REST_GATE_RECOVERY_REQUIRED, TASK_STALLED, plus CLOSE_REQUIRED by branch (alert_wording.py:95-420); `wording_for` returns None otherwise and the sender falls back to `render_alert_text` (alerts.py:739). Probe output for UNPROTECTED_POSITION: `[CRITICAL] UNPROTECTED_POSITION / subject: ETHUSDT / reason: POSITION_WITHOUT_STOP / at: 2026-11-17T03:00:00Z`. `render_alert_text` uses `_iso_utc` only (alerts.py:305-318); the cards use `format_presentation_time` (+07 first).
- **Expected:** An owner with little trading experience is told, for the most serious alerts, what it means and what to do; times follow one presentation rule.
- **Actual:** Four code lines for a position without a stop, a rejected stop, the daily stop, a foreign order, stale data and an auth failure. The time is UTC while the cards are +07, which invites a 7 hour misreading.
- **Reproduction:** tmp/telegram_alerts/probe_alert_lost.py (last lines of the output).
- **Impact:** Slower or wrong reaction to the alerts that matter most. No code path is unsafe.
- **Why tests miss it:** A test pins that each worded event matches the emitting code; none requires every CRITICAL event to be worded.
- **Remediation:** Word at least every CRITICAL event, add the mode line, and print the time as the cards do.

### G-0805
- **Severity:** LOW now / LOW mainnet · **Confidence:** CONFIRMED · **Classification:** AMBIGUITY · **Category:** card content
- **Component:** approval request text · **File:** `src/execution/approval_desk.py` · **Lines:** 478-481
- **Rule:** docs/integration/TELEGRAM.md section 4 ("risk percentage", "current exposure") · **Known-prior:** none found
- **Summary:** The card prints the risk RATE under the risk percentage field ("Risk: 0.005" means 0.5 %), and the only live signal source always passes exposure 0 and a leverage taken from configuration.
- **Evidence:** `risk_pct=plan.risk_rate` (approval_desk.py:478); line `f"Risk: {risk_pct}"` (telegram_notify.py:742); `risk_rate = 0.005` (params/breakout-retest/baseline-v5.toml:41). `exposure_quote=_ZERO` and `leverage_source=LEVERAGE_SOURCE_PAPER_CONFIG` (src/live/signal_source.py:621-623).
- **Expected:** A percentage is shown with its unit; current exposure is the real open exposure; the leverage is the one set on the exchange for the symbol.
- **Actual:** `Risk: 0.005` with no unit; `Exposure: 0 quote` is a constant of the Demo smoke source (a later strategy source must supply it); the margin line uses a configured leverage that may differ from the exchange setting.
- **Reproduction:** Read the lines.
- **Impact:** The money block (loss at SL in USDT) carries the real figure, so the decision input is not wrong, only confusing. The margin figure can be wrong if the exchange leverage differs (cross-lane: margin check).
- **Why tests miss it:** The message fixtures pin the text as it is.
- **Remediation:** Print `Risk: 0.5 % of equity`; require a real exposure reader and the exchange leverage before a strategy source is wired.

### G-0806
- **Severity:** LOW now / LOW mainnet · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** notification failure
- **Component:** approval request sender · **File:** `src/live/wiring.py` · **Lines:** 1117-1122
- **Rule:** docs/integration/TELEGRAM.md section 5; APRV-02 · **Known-prior:** none found
- **Summary:** When the approval card cannot be sent, the result is dropped by the pump: nothing is retried later, no alert exists for it, and the PENDING approvals block the symbol until the plan expires.
- **Evidence:** `await parts.sender.send_request(request)` ignores the `SendOutcome` (wiring.py:1122). A failed send returns `SendStatus.SEND_FAILED` after the desk journaled `*_APPROVAL_REQUEST_SEND_FAILED` (approval_sender.py:343-346; approval_desk.py:540-557); the rows written by `issue` stay PENDING and count as `SOURCE_OPEN_APPROVAL` (approval_sender.py:411-418). `ALERT_EVENTS` has no event for an undelivered request.
- **Expected:** Fail closed is kept (a send failure approves nothing). The operator should still learn, once Telegram is back, that a signal was missed.
- **Actual:** Silent. If Telegram delivered a message whose answer timed out, the card in the chat fails on every APPROVE tap with APPROVAL_STORE_FAILURE, because the Signal never moved to NOTIFIED (approval_sender.py:352-371, 585).
- **Reproduction:** Trace.
- **Impact:** A missed trade with no trace on the phone; no unsafe order.
- **Why tests miss it:** Tests assert that nothing is approved on a send failure, which holds.
- **Remediation:** Queue one informational alert for SEND_FAILED, or re-send the card while the plan is valid (a message retry, not an order retry).

## Owner decisions
1. **Redelivery of a failed safety alert (G-0801).** Today: Telegram is unreachable for 40 s at 03:00 while an emergency close fails; the alert is tried 3 times within 30 s, dropped, and the phone stays silent until the process is restarted. Options: (a) keep trying on every drain until delivered; (b) try for N minutes, then give up; (c) as today. Also: should a second plan on the same symbol within 5 minutes be suppressed as a repeat?
2. **Outcome messages after CONFIRM (G-0802).** Example: you confirm 0.129 ETH; the placement is refused 2 s later because the price left the zone. Today the card still says CONFIRMED and "handed to the execution step". Do you want one message per outcome (placed, refused with reason, filled, stop set, closed with PnL)?
3. **Buttons after a curable refusal (G-0803).** Example: you tap APPROVE while the account state is momentarily uncertain; the answer is "Refused: UNCERTAIN_ACCOUNT_STATE", the buttons are removed and the symbol is blocked until the plan expires. Keep the buttons for such reasons?
4. **Missed card (G-0806).** Tell the operator later that a signal could not be delivered, or stay silent?

## Open Questions
- (live lane) `finalize_message` reads the entry intent through `desk.intent_reader` on the event loop (`confirm_flow.py:535`), a synchronous store read outside the `run_sync` seam; `_state_text` and `finalize_expired_requests` do the same with `lookup_by_token_hash` (`approval_desk.py:829-832, 975-978`). Blocking only; not judged here.
- (live lane) PTB is built with defaults (`src/live/runtime.py:466`), so updates are handled one at a time: a CONFIRM waiting on its exchange prefetch, or a RetryAfter sleep of up to 30 s inside a handler, delays `/disable_entries` and every other press.
- (live lane) `ApprovalDesk._requests` and the `ConfirmFlow` maps are never evicted; the expiry sweep walks every request since start.
- (M02) After a restart a PENDING approval can never be decided (tokens lost) but keeps its symbol in `SOURCE_OPEN_APPROVAL` until plan expiry; documented as D-04, cost not quantified.
- (reconcile lane) Do the reconcile producers alert on every tick while a divergence lasts? If so they recover from G-0801 after the 5 minute window; I read only `_send_alert`, not the tick's own latch.
- Not verified: the offset handling of python-telegram-bot was not read in the installed package (by the trace above a lost update means no decision and a repeated one is idempotent); no core.telegram.org page was fetched; nothing ran against a database, so G-0803 is a code trace and the ordering claim in G-0802 is a trace too.
- The margin line uses a configured leverage (`LEVERAGE_SOURCE_PAPER_CONFIG`); whether it equals the exchange leverage belongs to the margin-check lane.

## DONE
