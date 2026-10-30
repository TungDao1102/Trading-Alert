# Telegram Integration

## 1. Purpose

Telegram is the human approval/notification channel, not the strategy engine.

## 2. Required actions

Minimum message actions:

- `SIMULATE`
- `APPROVE`
- `SKIP`

Later:

- `CANCEL ENTRY`
- `CLOSE POSITION`
- `SAFE MODE`

## 3. Approval security

An approval must be bound to:

- SignalId,
- strategy version,
- exact trade plan hash,
- expiry time,
- user identity / authorized chat,
- one-time approval token.

Replaying an old approval must not place a fresh order.

Phase 23 (D-01, D-02, D-03) adds a second gate that is independent of the chat gate, so the two fail independently. After the chat gate and before any short-id or token lookup, a press must come from:

- a Telegram user id that is in `TELEGRAM_AUTHORIZED_USER_IDS` (a comma-separated list of positive integers; it is required and has no default, an empty or missing list never means "allow all"), and
- a chat whose type is exactly `private`.

The checks run in this order: the press has a user id (`USER_ID_UNAVAILABLE`), the chat type is `private` (`CHAT_NOT_PRIVATE`), the user is listed (`USER_NOT_AUTHORIZED`). A refused press is answered with the generic text "Rejected", changes nothing and is journaled with only the presser's id (never a token, never the allow-list). The user who decides is stored as the approval's `actor_id` (DATA_MODEL section 2.5). The runtime refuses to start when Telegram is configured (a token and `TELEGRAM_AUTHORIZED_CHAT_ID`) without `TELEGRAM_AUTHORIZED_USER_IDS`. The owner sets the value in `.env` and never in the repository (owner question O-1: the default built is one id). A group chat is never accepted, even when its chat id is the authorized one (owner question O-4: the private-chat rule is not relaxed). The refusal codes are plain strings listed in GLOSSARY section 9.3. Whether a press from a second Telegram account or from a group is refused on the live Bot API has not been checked: it is the owner-run check G2-014 (`23-OWNER-CHECKS.md`).

### Token trust model (F-127)

Documented here, not changed in code (D-04). What a leaked or forwarded `callback_data` can and cannot do:

1. `callback_data` carries only a prefix and a short id (`APR:`, `SKP:`, `CNF:` or `CXL:` followed by the short id; 36 bytes for the APPROVE and SKIP buttons). It carries no token, no plan hash and no amount. A press with it still needs all of the following: the authorized chat, a listed user in a private chat, the one-time token that the sending process holds in memory for that short id, the exact plan hash the request was issued for, and an unexpired plan. A string copied from a screenshot or a forwarded message therefore decides nothing for someone else.
2. The user-id allow-list is still required. The chat gate compares only the chat id; in a group every member's press carries the group's chat id, and a chat id alone does not say who pressed. The user gate checks the person.
3. The approval token's raw value never reaches PostgreSQL or the journal. Only its hash is stored (`approvals.approval_token_hash`); the raw value and the short-id mapping live in the memory of the process that sent the message.
4. The confirm token of the two-step flow (section 6) lives in memory only. It is single use, valid for 60 seconds, and bound to the approving user id and the plan hash.
5. A restart expires every outstanding confirm (`RUNTIME_RESTART`): its token died with the process. After a restart an old request or card cannot be decided any more: the tap is refused (`NO_CONFIRM_CONTEXT` for a confirm card, `INVALIDATED` for a request) and the message loses its keyboard.

## 4. Message contents

At minimum:

- symbol,
- direction,
- setup,
- entry,
- SL,
- TP(s),
- R:R,
- risk percentage,
- expiry,
- invalidation,
- current exposure,
- clear reason codes.

The APPROVE message also shows the approved quantity on a `Quantity:` line: the plan's `quantity_after_rounding`, the same value that is stored on the approval row as `approved_quantity` (D078 item (6)), written in fixed-point notation with every digit of the Decimal and never rounded. A message without it is refused and not sent. The SIMULATE message carries the same `Quantity:` line and the same money block as the DEMO and LIVE request (Phase 23; the earlier statement that SIMULATE does not carry the quantity no longer holds). It has no approval row, so its values come from the payload the sender is given, and a payload without them is refused (FAILED with zero attempts, no bot call).

Phase 23 (D-13) adds the money at stake to the DEMO and LIVE APPROVE request and to SIMULATE. The block is built once from the risk pipeline output (`src/risk/money_at_stake.py`) and stored as `approvals.money_json` (DATA_MODEL section 2.5); the renderers only format the stored values and do no arithmetic. The lines come directly after `Quantity:`, in this order:

- `Notional:` the quantity times the entry price;
- `Margin:` the initial margin, with the leverage and the source of that leverage;
- `Loss at SL:` gross and net of modeled costs;
- one `Profit at TPn (share of quantity):` line per take-profit leg, gross and net (an estimate per leg: the live leg is floored to the step size, so a real leg can be smaller);
- `Equity used:` the equity, its source label and the time it was observed.

Every value is written in fixed-point notation with every digit of the stored Decimal. A request whose money is missing, or disagrees with the plan (direction, quantity, stop, the number of take-profits, a take-profit price or share), is refused before anything is written or sent (`MONEY_AT_STAKE_MISSING`, the field is named). The SHADOW alert does not carry the money block (owner question: not built).

Times in the DEMO, LIVE and SIMULATE messages and on the confirmation card are written as the local Vietnam time first and UTC in brackets, each with its suffix: `YYYY-MM-DD HH:MM:SS +07 (YYYY-MM-DD HH:MM:SS UTC)`, for example `2026-10-30 21:15:00 +07 (2026-10-30 14:15:00 UTC)` (owner item O-3, answered 2026-10-30). The local time follows `docs/DECISIONS.md` D025 and `docs/01_ENGINEERING_PRINCIPLES.md` section 8 (persist UTC, convert to Asia/Ho_Chi_Minh only in presentation); the UTC time stays in view because the daily-loss rule counts in the UTC day (D033). Vietnam has no daylight saving, so a fixed `+07` offset is exact and no time-zone database is used; the suffix is `+07`, not the zone name, and the earlier `Display: Asia/Ho_Chi_Minh` note (false) stays gone. Only the text changes: stored times stay UTC and D025 is not edited. SHADOW alerts keep their UTC and Asia/Ho_Chi_Minh pairs, byte for byte; the SHADOW alert also stays without the money block (owner item R-1, accepted 2026-10-30; composing one is a Phase 24 question).

## 5. Failure behavior

If Telegram is unavailable:

- signals must still be journaled;
- live order placement must not be inferred from missing notification;
- system must not auto-approve.

## 6. Callback delivery semantics

Treat Telegram callback delivery as **at-least-once**.

For a callback carrying an already-consumed approval token:

```text
lookup approval token
→ return current approval/order state
→ do not create a new order intent
```

The system must be idempotent across duplicate, delayed, or retried callbacks.

### Phase 23 rules

- **One message, two buttons.** A DEMO or LIVE request is one message with APPROVE and SKIP in one row (`APR:` and `SKP:` over one short id). SHADOW uses the same keyboard. A failed send never approves anything: both approval rows stay PENDING.
- **The decided message is final.** After a decision the request message is edited once: its final text (the request text plus the decision, the deciding user id and the time as local +07 with UTC in brackets) and an empty inline keyboard in one `editMessageText` call, with one keyboard-only edit as the fallback. SHADOW messages keep their text and lose only the keyboard. A failed edit is journaled and never changes a decision. Whether an empty `reply_markup` removes the keyboard on the live Bot API is unverified (research assumption A1): it is the owner-run check A1 in `23-OWNER-CHECKS.md`.
- **A stale tap is answered from stored state.** A replay or the other button of an already decided request is answered `Already decided: <status>. Nothing changed. [ALREADY_DECIDED]` and writes nothing. The answer is read from the stored approval row, never from memory. A tap after the expiry finalizes the request as expired. When the expired approval was APPROVED, the reply reads the stored entry intent: already placed (acknowledged by the exchange; the fill state is in the journal), needs reconciliation (an UNKNOWN, SENT or INTENDED entry is never reported as rejected), or rejected (G4-032).
- **Bounded Telegram calls.** `RetryAfter` is slept inside a cap of 30 seconds per wait and the remaining window, for at most 3 attempts (the existing notification bounds). "message is not modified" counts as success and a refusal (Forbidden, BadRequest) is never retried. These helpers send and edit messages only: a placement is never re-sent (D080).
- **Error handling.** An exception after the gates is logged by class name and correlation id (never its text), journaled as `CALLBACK_HANDLER_FAILED` and answered with one neutral text; the result is `CALLBACK_HANDLER_ERROR` and the keyboard is kept. `build_application` also registers an application-level error handler. An expired callback query ("Query is too old") is logged at debug level; its exact live text is unverified (research assumption A2, owner check A2).
- **Two-step confirm in DEMO and LIVE.** APPROVE only records the decision and turns the request message into a confirmation card with CONFIRM and CANCEL (D041). The card shows the mode, the quantity, the notional and the loss at the stop from the stored money block, the mark price against the entry and the stop, the verdict of the placement validity rule, and the time (local +07 with UTC in brackets) until which CONFIRM is valid. The confirm token is single use, valid for 60 seconds and bound to the approving user id and the plan hash; another listed user is refused (`USER_MISMATCH`) and the approving user can still confirm. At CONFIRM the pre-placement checks and the position mode are re-run once from a pre-fetched, single-use exchange snapshot (`CONFIRM_INPUTS_UNAVAILABLE`, `CONFIRM_INPUTS_MISMATCH` and the other refusal codes are shown verbatim, and an error in the re-check is a refusal, `RECHECK_ERROR`). Only a valid CONFIRM calls `on_confirmed`, once; it is the only seam to placement, it is injected, and in Phase 23 it is connected to nothing. The final text states what the stored entry intent says, and an entry that may or may not have reached the exchange reads "needs reconciliation", never "rejected". A confirm that is not completed ends EXPIRED (`CONFIRM_TTL_ELAPSED`, `CARD_DELIVERY_FAILED` or `RUNTIME_RESTART`). The mode-independent state machine is `src/approval/confirm_core.py`; SHADOW is a thin profile over it with unchanged texts.
- **Not composed yet.** The desk (`src/execution/approval_desk.py`), the confirm flow (`src/execution/confirm_flow.py`) and the alert wording are library pieces. No running process uses them until the Phase 24 composition; request text, message ids and raw tokens are memory only.
