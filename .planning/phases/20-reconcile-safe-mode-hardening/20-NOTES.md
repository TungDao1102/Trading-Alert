# Phase 20 notes (carried from Phase 17)

Input for `/gsd-discuss-phase 20` and the researcher. Not a decision record.

## Verify against current Binance docs and Demo (do not assume)

- When a position is closed manually (outside this system), do the protective SL/TP orders
  (STOP_MARKET and TAKE_PROFIT_MARKET with `closePosition`, placed through
  `POST /fapi/v1/algoOrder`) cancel automatically, or do they stay on the exchange as orphans?
  The answer decides what the orphan sweeper and reconcile must do after a manual close.
  Re-read the live Binance pages and prove the behavior on Binance Demo (Phase 25) before
  relying on either answer. AGENTS.md requires exchange facts to be re-verified, not recalled.

## Other items carried from Phase 17 (see D051 items (h) and (i))

- Crash right after the STOP_LOSS intent leaves an acknowledged entry without a stop, and restart
  does not place one (reconcile must close this gap).
- Journal-outage behavior of controller `disable`, `expire_pending_entry`,
  `cancel_untriggered_protectives` and `emergency_manual_close` (F-702).
- Every Order/Position move out of `UNKNOWN` needs Binance evidence (reconcile over REST or a
  user-data event). Record the evidence source in the journal when the first caller exists.
- An executed TradePlan stays `APPROVED`; its `expiry_utc` governs only an unfilled entry. Do not
  write code that moves an executed plan to `EXPIRED`.

## From the Phase 18 code review (2026-10-19)

Source: `18-user-data-stream-error-taxonomy/18-REVIEW.md` and `18-REVIEW-FIX.md`. Not decided.

- **Map `StreamDivergenceKind.SINK_FAILURE` (new, from fix src/WR-04).** The router now emits it when a sink fails; the reconciler must handle it as a divergence (a lost fill or ALGO_UPDATE is routed again on redelivery, but the divergence itself must be acted on). Also from Phase 18: the supervisor can halt as `TASK_DIED` (src/WR-05), and the sweeper failure events carry the exception type only (src/WR-07).
- **src/WR-03, event ordering.** `ExchangeStateUpdate` carries processing time, not exchange event time; `update_order_exchange_state` overwrites unconditionally and the algo lifecycle key has no ordering, so an out-of-order or duplicated event can move an order backwards. Needs an event-time field (schema migration) and a monotonic rule in the stores; the consumers are here and in Phase 19.
- **src/WR-12, a 429 pause blocks protection and cancels.** While the gate pauses REST after a 429, protective placement and entry cancel are refused, and the manager swallows the cancel failure. A resting GTC entry can fill with no stop until this phase's reconciler re-places it (D034). Owner decision needed: a reduce-risk exemption from the pause, or a durable pending-cancel record that the reconciler works off first.
- **Related, Phase 19 notes:** src/WR-01, WR-02, WR-08, WR-10 and the rest of src/CR-02 are recorded in `19-execution-plan-binding-price-check/19-NOTES.md`.

## From Phase 19 (2026-10-20)

Source: `19-execution-plan-binding-price-check/` (19-14, 19-15 and 19-16 SUMMARY files), quick task `.planning/quick/261020-jua-q5-remove-entry-placement-retry-unknown-/` and `19-DEC-Q5-DRAFT.md`. Input for `/gsd-discuss-phase 20`. Not decided unless a line says so. All evidence is fake-exchange agreement, not Demo or mainnet.

- **Alerts have an interface and no sender.** `CriticalAlertSink` (`src/execution/protection.py`, "Telegram UX is Phase 23") is called by the protection coordinator and the emergency closer, but only `scripts/demo_rehearsal.py` implements it (it writes evidence, it sends nothing). Phase 20 owns the real sink. Events already emitted by code: `CLOSE_REQUIRED` (the reason carries the branch code B1 to B5 or `NO_POSITION_ON_STOP_BUT_EXPOSED`), `TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED`, `EMERGENCY_CLOSE_NOT_SENT`. Write the alert to the journal first; a Telegram send failure needs its own handling (the network to Telegram is unreliable on the owner machine). Retrying a message is fine; retrying an order is not (see Q5 below).
- **The entry path emits no alert at all.** `execute_approved_plan` enters SAFE_MODE with reasons `ENTRY_STATE_UNKNOWN`, `PROTECTION_HANDOFF_FAILED` and `DB_FAILURE` and returns `RECONCILIATION_REQUIRED`, and nothing tells the operator. Decide which of these, and which NO_TRADE outcomes (`ENTRY_REFUSED_BEFORE_SEND`, `EXCHANGE_CONSTRAINT`), deserve an alert. OPS-05 already asks for "a rejected protective action" and "a duplicate execution attempt" (T-05 above).
- **Q5 is decided by the owner (2026-10-20): a placement is never re-sent.** After an ambiguous entry failure the order is probed once; found hands off, anything else (not found, probe error, indeterminate) leaves the ENTRY intent `UNKNOWN` plus SAFE_MODE `ENTRY_STATE_UNKNOWN`. Not-found right after an ambiguous error is not proof of absence (`newClientOrderId` is unique only among OPEN orders, no documented idempotency or query visibility, `-1007` says "execution status unknown"). The DECISIONS row is still a draft: `19-DEC-Q5-DRAFT.md`.
- **Phase 20 must close what Q5 leaves `UNKNOWN`.** Open conflict: `resolve_unresolved_intents` (`src/execution/intent_recovery.py`, `EXECUTION_SPEC.md` 10.1 step 4) records a not-found intent younger than 3 days as `REJECTED`. For an entry that went `UNKNOWN` after an ambiguous error that is exactly the conclusion Q5 refused. Decide when an UNKNOWN entry may be closed (repeated probes, the GTD expiry passing, a position and open-order reconciliation). The numbers (windows, probe counts) are the owner's (O-04); invent none. Since 19-REVIEW WR-05 (owner, review-fix batch 1) the manager hands the UNKNOWN entry to the protection coordinator, which protects a fill it finds, never re-sends and never drops the record; never found by GTD plus `protection.entry_unknown_grace_ms` (NOT_CONFIGURED, O-04) it becomes the protection state `ENTRY_UNRESOLVED` and is queried only every Nth step. Resolving and closing that record (and the intent) is still this phase's decision.
- **Q5 also governs the emergency close (19-REVIEW WR-03, owner, review-fix batch 2).** `MarketEmergencyCloser` never sends a second close while the previous attempt is not proven terminal: an ACK is PENDING, found=False after an ambiguous send is UNKNOWN, and `discover_next_attempt_no` refuses a new number while a found attempt is not terminal. Past `protection.emergency_close_poll_timeout_ms` (NOT_CONFIGURED, O-04) a still-active attempt is held UNKNOWN with SAFE_MODE `EMERGENCY_CLOSE_FAILED` and one critical alert per attempt. The pending attempt lives in process memory only: after a restart, an ambiguous attempt the exchange does not show is forgotten and its number could be handed out again. Restart rebuild of the closer's pending attempt (for example from the `EMERGENCY_CLOSE` journal rows `pre_send`/`ambiguous`) belongs with the coordinator rebuild (G4-029).
- **A lost stop is never re-placed (19-REVIEW WR-04, owner, review-fix batch 3; DECISIONS D077).** In `PROTECTED_ENTRY_OPEN`, a stop that REST confirmed ACTIVE and later reads absent or not active is decided by the position: confirmed exposure is B4 (CLOSE_REQUIRED, MARKET close); unreadable, or flat while the entry can still fill, moves the plan back to `UNPROTECTED` (blocking) with `stop_lost_at` set once; `protection.max_unprotected_ms` (NOT_CONFIGURED, O-04) from `stop_lost_at` without position zero AND entry terminal escalates to CLOSE_REQUIRED (`B4_STOP_LOST_UNRESOLVED`). `stop_lost_at` lives in process memory only, like the rest of the coordinator state: the restart rebuild (G4-029) must not restart that clock or re-place the stop. D077 is worded for any stop that was confirmed and later is absent or not active, while ROADMAP criterion 2 says "a missing SL is re-placed"; reconcile the criterion wording with D077 in the Phase 20 discussion (P6 is still not observed on Demo).
- **No stop supervision after `PROTECTED`.** Once a plan is `PROTECTED`, `COMPLETE` or `TP_UNAVAILABLE`, the coordinator does not re-check that the stop is still ACTIVE while the position is open. A stop that is cancelled or lost later stays invisible until reconcile finds it. Criterion 2 (a missing SL is re-placed or the position closed) must cover plans in these three states.
- **`TP_UNAVAILABLE` is terminal for the plan**, including after a 418/429 pre-send refusal (Q4 / src/WR-12 above). It keeps the stop, enters SAFE_MODE and alerts; it never flattens by itself. With real data it is the normal result until Phases 21 and 22 deliver a complete constraint snapshot (see their notes).
- **Entry-time stop wording.** Criterion 2 speaks of "the entry-time SL of a resting entry". Phase 19 removed the entry-time stop (D-10): the stop is placed after the first fill. This stays tied to the open D055 closure (inherited item [D055]).

## Owner decisions Q3 and Q4, implementation deferred to Phase 20 (2026-10-20)

Source: the Phase 19 UAT session (`19-execution-plan-binding-price-check/19-UAT.md`, items 10 to 14) and the owner's answer after a reviewer's text was checked against the code and the Binance docs. These are DECIDED IN BEHAVIOR by the owner; the DECISIONS row is not written (the next free ids are blocked by the unwritten drafts D079 and D080, so write the row after them) and nothing below is implemented. Estimate when noted by the agent: Q3 is a medium task (about 20 to 30 minutes of agent work), Q4 is large (1 to 2 hours, probably two tasks, likely a migration).

### Q3: exchangeInfo cannot be read during an emergency close (owner: option (b), emergency close only)

- Use the last validated MARKET_LOT_SIZE filters stored earlier, carried with a `filters_stale` flag and the time they were fetched. Never for a new entry.
- No valid stored filters: do not guess stepSize, minQty or maxQty. Keep CLOSE_REQUIRED / SAFE_MODE, raise a critical alert, keep reconciling; never declare the position safe.
- The close quantity comes from the reconciled real exposure, floored to the available filters, never rounded up to reach minQty.
- A split close runs one part at a time: wait until the previous attempt is terminal, reconcile the position, then size the next part. This already holds in `src/execution/emergency_close.py` (WR-03); keep it.
- If Binance rejects because the filters are no longer right, do not resend the same payload; when exchangeInfo can be read again, fetch fresh filters and recompute.
- This is a best-effort close, not a guarantee that the exchange accepts it. It does not weaken WR-03: the result of the previous attempt is determined before the next one starts.
- What is missing in the code today: the closer only calls `symbol_lot_filters` and fails with `LOT_FILTERS_UNAVAILABLE`. `PlanConstraintSnapshot` (`src/execution/constraint_snapshot.py`) has the market-lot fields but they can be None and it has a TTL (`snapshot_is_valid_for_live`). Needed: a place to keep the last validated filters, the stale flag with the fetch time, and an explicit rule that the closer may ignore the TTL (and nobody else may). Check first whether the snapshot is persisted or only in memory.
- Interaction with Q4: the exchangeInfo read goes through the same REST gate, so during a 429/418 pause it is refused too. The stored-filters fallback only helps for a read that fails for another reason (timeout, 5xx).

### Q4: a 429/418 pause versus protection (owner: option (b), plus reserved priority for risk-reducing calls)

- Never bypass an HTTP 429/418 pause. Binance: failing to back off after 429 leads to an IP ban (418) of 2 minutes to 3 days. Retry-After is honoured when present; otherwise the configured cooldown applies; never assume the pause has ended.
- Before sending, durably record the intent of a protective stop, an entry cancel or an emergency close. When the gateway blocks it, record the explicit pending state (`STOP_NOT_SENT`, `PROTECTION_ENTRY_CANCEL_NOT_SENT`, `CLOSE_NOT_SENT`), not only an in-memory log line. Today these are journal rows only; the stop intent stays SENT and the coordinator retries from memory; after a restart `resolve_unresolved_intents` turns it into UNKNOWN plus SAFE_MODE. A durable queue that survives a restart does not exist yet.
- When sending is possible again, reconcile the current state first, then decide. Never replay an old payload blindly.
- If `max_unprotected_ms` (O-04, still NOT_CONFIGURED) runs out during the wait, the plan moves to CLOSE_REQUIRED. After the exchange allows sending again, handle the remaining entry and the emergency close first; do not send a queued old stop when the current policy already requires closing the position.
- Treat `-1008` apart from 429/418. Binance exempts reduce-only and close-position orders from `-1008`. The error-code page names only those two; the general-info page also says cancel orders are exempt. Do not rely on the cancel exemption. A `-1008` is not a rate-limit pause. This part is a defect fix, tracked by quick task 261020-g1a (the gate recorded `-1008` as a 429 pause of every REST call); check its SUMMARY for what was done.
- "Reserved priority for risk-reducing calls" was named by the owner and is NOT defined yet. Decide what it means before building it (for example, request-weight headroom kept for protective calls, or an ordering rule in the queue).
- The queue does not protect the position while the exchange forbids sending. In that window the plan stays in a dangerous state, the alert that must go out is recorded, and reconciliation continues when possible. Never claim that a position always has a stop under every rate-limit condition.
- This supersedes the line "Owner decision needed: a reduce-risk exemption from the pause, or a durable pending-cancel record" under src/WR-12 above: the owner chose the durable record and no exemption from a 429/418 pause.

### Related work done in Phase 19 follow-ups

- Last-price check (UAT item 10, WR-06 work item): quick task 261020-l4p.
- `-1008` no longer treated as a 429 pause: quick task 261020-g1a.
