# Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts - Context

**Gathered:** 2026-10-25
**Status:** Ready for planning (gathered with `--auto`, single pass; every decision is the recommended option or a direction already recorded by the owner. Items marked OWNER-OPEN must not be implemented with a number until the owner decides.)

<domain>
## Phase Boundary

Only the authorized user in a private chat can decide. SKIP is recorded. An APPROVE tap alone never places an order: it edits the message into a confirmation card and only CONFIRM (within a short TTL) triggers placement, in SHADOW, DEMO and LIVE (D041). A decided message loses its keyboard and later taps are refused. Every APPROVE / confirmation message shows the money at stake, taken from the risk pipeline output and never recomputed (F-015).

Requirements: APRV-01, APRV-02, PAPER-02 (ROADMAP Phase 23, five success criteria; audit refs F-508, F-707, F-405, F-509, F-127, F-015, F-016, D041). Depends on Phase 12, 21, 22.

Out of scope (stays elsewhere): wiring the bot into a running live process, the `execute_approved_plan` call from CONFIRM, schedulers and the live risk-input producer (Phase 24); the Demo campaign (25); the go-live gate (26); the Phase 20 alert sink, its event selection and bounded retry (built; this phase owns only the wording of the messages, see D-14); new Telegram commands (see Deferred, P20-OPS-REMOTE); any change to quantization, sizing or the strategy.

Inputs: ROADMAP Phase 23, `23-NOTES.md`, `22-CONTEXT.md`, `19-CONTEXT.md` (D-05, D-09), DECISIONS D041, D051, D078, D080, `docs/integration/TELEGRAM.md`, `src/adapters/telegram_callbacks.py`, `src/adapters/telegram_notify.py`, `src/paper/shadow_confirm.py`. Nothing here edits `docs/DECISIONS.md` or the parameter registry. No number is invented.
</domain>

<decisions>
## Implementation Decisions

All decisions are the recommended option or an owner direction. They are defaults the owner may override. Every Telegram Bot API fact (error classes, `RetryAfter`, "query is too old", `can_be_edited`, chat types, message-edit limits) is read from the official documentation by the researcher, not taken from this file or memory.

### Authorization (criterion 1, F-508, F-707)
- **D-01:** Authorization is a pure gate that runs BEFORE any state lookup, after the existing chat gate: `from_user.id` must be in an allow-list AND `chat.type` must be `private`. A missing `from_user`, a channel/group/supergroup chat, or an id not in the list is refused with no state change and a journaled rejection (the `chat_gate_rejected` receipt shape already exists in `_build_chat_reject_receipt`; the new reason is a plain code, see D-15). The existing `authorized_chat_gate` stays; in a private chat the chat id equals the user id, but both checks are kept because they fail independently (a group id is negative, a forwarded bot is not the user). — **Reversibility:** reversible — one pure predicate and its tests.
- **D-02:** The allow-list comes from a new env value `TELEGRAM_AUTHORIZED_USER_IDS` (comma-separated integers) read by `runtime_config`/`runtime` beside `TELEGRAM_AUTHORIZED_CHAT_ID`; missing or unparsable is a startup refusal (`ConfigNotRatified`), never "allow all". Default for the owner: one id. The list is never printed in logs or journals in full; the journal stores only the id of the actor who pressed. — **Reversibility:** costly — a new required secret-class env name that deploy files and `runtime_config` pin; follows the existing redaction rules.
- **D-03:** The decider id is recorded: `Approval.actor_id` (empty today on a decided approval) is set to the Telegram `from_user.id` (as text) at APPROVE and SKIP, and the CONFIRM/CANCEL journal events carry the same id (live-test finding: "the journal does not say who decided"). Replays to an existing decision keep the first actor. — **Reversibility:** reversible — a field that already exists.
- **D-04:** Token trust model (F-127) is documented, not changed: the approval is bound to chat, short id, plan hash and expiry; the one-time token's raw value never reaches PostgreSQL or the journal; the confirm token lives in memory only (current design of `ConfirmBook`). The doc goes into `docs/integration/TELEGRAM.md` (what a leaked `callback_data` can and cannot do, why a user-id allow-list is still required, and what a restart does to outstanding confirms: they expire). — **Reversibility:** reversible — documentation.

### APPROVE / SKIP buttons and decided messages (criterion 1 and 5, F-405, F-509)
- **D-05:** One message carries APPROVE and SKIP together in LIVE and DEMO, exactly as SHADOW already does (`build_shadow_decision_keyboard`: `APR:<short>` and `SKP:<short>` with distinct prefixes). The separate single-button keyboards (`build_approve_keyboard`, `build_skip_keyboard`) and the inert Phase-7 SIMULATE keyboard stay in the module for wire-format stability but are not sent by any production path. A test pins that the SKIP press is recorded as `SKIPPED` (F-405) and not collapsed into SIMULATE_RECORDED. — **Reversibility:** reversible — which builder the sender calls.
- **D-06:** After any decision (APPROVE → card, SKIP, CONFIRM, CANCEL, expiry) the message is edited to its final text and the keyboard is removed (`reply_markup` empty) in the same edit. A later tap on a stale button is answered with a short refusal ("already decided") and changes no state; replays stay idempotent (3 taps, 1 transition, as observed live). A failed keyboard removal does not roll back the decision: it is journaled and the stale-tap refusal (above) is the backstop. — **Reversibility:** reversible.
- **D-07:** `RetryAfter` and other Telegram send/edit errors are honored through the existing classifier (`classify_telegram_error`, `TelegramFailureKind`): sleep for the server's `retry_after` (bounded by a named cap), retry the MESSAGE at most the bound that `NOTIFY_MAX_ATTEMPTS` already defines; never retry anything that places an order (Q5, D080). No auto-approve on a notification failure (APRV-02 stays). — **Reversibility:** reversible.
- **D-08:** Callbacks queued during downtime: the application gets an error handler, and `query.answer()` failing with "Query is too old" (`BadRequest`) is swallowed after a debug log by `answer_callback_safely` (cosmetic call only) and never stops the press from being processed through the gates. An exception anywhere else in the handler is journaled with the correlation id and answered with a neutral message; it must not leave a traceback loop or an unanswered spinner. — **Reversibility:** reversible.

### Two-step confirm for DEMO and LIVE (criterion 4, D041)
- **D-09:** The `ConfirmBook` state machine of `src/paper/shadow_confirm.py` is the model, not a copy: the planner extracts its mode-independent core (token issue, single use, user+plan-hash binding, 60 s TTL, journaled CANCEL/expiry, replay-to-existing outcome, restart expiry `RUNTIME_RESTART`) into a shared module that SHADOW, DEMO and LIVE all use; SHADOW keeps its no-placement guarantee through its `on_confirmed` hook (it imports nothing from `src.execution`). In DEMO and LIVE `on_confirmed` is the single seam that Phase 24 later connects to `execute_approved_plan`; this phase leaves that seam as an injected callable and does not import `src.execution` placement from the confirm core. — **Reversibility:** costly — SHADOW tests, evidence and soak code (Phase 16) depend on the current module; the extraction must keep their behaviour byte-identical.
- **D-10:** The confirm TTL stays 60 s (configurable, not a strategy parameter). The confirm token is distinct from the approval token, single-use, bound to the same `from_user.id` and plan hash. CONFIRM by another user, a double tap, a replayed CONFIRM, a CONFIRM after the TTL and a CONFIRM after the plan expired or the price crossed the SL are each a refusal with a journaled reason and no placement. — **Reversibility:** reversible.
- **D-11:** Pre-placement checks re-run at CONFIRM time using the existing `src/execution/pre_placement.py` functions (`check_remaining_validity`, `check_mark_price`, `check_last_price`, invalidation, symbol free, position mode) fed fresh inputs; the confirm core takes them as one injected callable that returns a reason code or None, so it stays free of exchange imports. A stale or missing mark price is a refusal (fail closed, D058). Remaining validity follows Phase 19 D-05/D-09: `expiry_utc` governs only an unfilled entry; the card shows the same minimum-validity rule the gate applies, not a second one (criterion 3, F-016). — **Reversibility:** reversible.
- **D-12:** An ambiguous entry result (intent `UNKNOWN` + SAFE_MODE, Q5) is shown to the operator as "needs reconciliation", never "rejected", on the card and in any "already executed" reply. For G4-032: when a redelivered APPROVE arrives after expiry, the composition reads the stored outcome through `PgExecutionStateStore.get_entry` and the reply says "already executed" or "needs reconciliation" instead of `APPROVAL_EXPIRED`; criterion-4 tests cover it. — **Reversibility:** reversible.

### Money amounts (criterion 2, F-015)
- **D-13:** The message shows, in this order after the existing `Quantity:` line: notional; margin at the configured leverage (the verified leverage from Phase 22's plan constraint snapshot, not a recomputed one); estimated loss at SL and profit at each TP, each as gross and net of modeled costs; and the equity used with its source and timestamp (Phase 21 equity record). Every value is read from the risk pipeline / cost model / constraint snapshot output stored with the approval; the renderer does arithmetic only to format (no multiplication, no cost model call inside Telegram code), and a missing field refuses to render and to send (same rule as `approved_quantity` today). The money fields join the hashed or stored approval payload so the card and the APPROVE message cannot disagree; the planner decides the carrier (new typed value object on the approval, or fields on the existing row) and whether it needs an Alembic migration. Amounts are fixed-point Decimal text, never rounded up, with the quote asset named (USDT today; Phase 27 makes it configurable). — **Reversibility:** costly — a typed carrier, possibly a migration, and a golden-text test that pins the message.
- **D-14:** The SIMULATE message also shows the money block (criterion text: "every SIMULATE/APPROVE message"); the SIMULATE message additionally gets the quantity line it lacks today (`23-NOTES.md` section 4). Time display: the "Asia/Ho_Chi_Minh" note is wrong while the times are UTC. Decision: show the times as UTC with the explicit suffix `UTC`, and delete the display note (changing the presentation to local time is a later owner preference, see Deferred). Operator-alert wording (`23-NOTES.md` sections 1 and 3): a message states in plain words what happened, whether a position may be open or unprotected, what the system already did, and what the operator must do, and uses the Phase 20 reason codes verbatim. Events with a code today: `CLOSE_REQUIRED` (B1–B5, `NO_POSITION_ON_STOP_BUT_EXPOSED`), `TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED`, `EMERGENCY_CLOSE_NOT_SENT`, `ENTRY_STATE_UNKNOWN`, `PROTECTION_HANDOFF_FAILED`, `DB_FAILURE`, `RECONCILIATION_REQUIRED`. Phase 20 keeps the sink and the retry; this phase supplies one pure formatter per event plus golden-text tests. — **Reversibility:** reversible — formatters and golden texts.

### Vocabulary and evidence
- **D-15:** New plain reason codes (for example for a user id not on the list, a non-private chat, a stale button, a confirm by another user) are added deliberately: `RejectionReason` is pinned by `tests/test_phase21_gate.py` (invariant 3) and the GLOSSARY lists the codes, so the plan updates both in the same change; no existing code is reused with a changed meaning. — **Reversibility:** costly — an enum other modules, the gate tests and the glossary pin.
- **D-16:** Inherited items are resolved here as follows. **P16R-02:** `ConfirmBook._deferred_confirmed` keeps a LIST of adopted confirms in one `expire_due` sweep and `on_confirmed` runs once per adopted confirm; a test with two adoptions in one sweep is mandatory (the hook may then use its arguments). **G4-042:** the one-decided-per-plan index excludes `EXPIRED` rows from its predicate (an expiring sibling row must never violate it); the rule is recorded in DATA_MODEL and needs an Alembic migration; this is flagged OWNER-OPEN O-2 because the alternative is plan-level expiry. **G4-032:** see D-12. **P20-OPS-REMOTE:** recorded as deferred, but this phase builds the allow-list and the two-step confirm in a form that a command can reuse (D-09, D-01). — **Reversibility:** costly for the migration, reversible otherwise.
- **D-17:** Nothing here is composed into a running process (Phase 24). Everything is proven with fakes (`tests/support/`), local PostgreSQL where the approval/index changes, and the existing PTB-free test surfaces (`parse_callback_data`, `dispatch_callback`, the pure gates). `build_application` is not called from unit tests (existing rule). The one live check that only the owner can produce (a tap by a second Telegram account or from a group, G2-014, NOT_REHEARSED) is registered as an owner-run item for Phase 24/25, not run by an agent. Live placement stays disabled (`LIVE_ORDERS_DISABLED`).

### OWNER-OPEN (record, do not implement with a number)
- **O-1:** The initial allow-list content (the owner's Telegram user id) and whether a second operator id may exist. Default: one id, set in `.env` by the owner.
- **O-2:** G4-042 expiry rule: exclude `EXPIRED` from the unique-index predicate (default) or move to plan-level expiry. A DATA_MODEL line and a DECISIONS row settle it before the migration is merged.
- **O-3:** Whether the card and messages should show local time (Asia/Ho_Chi_Minh) instead of UTC. Default: UTC with explicit suffix (D-14).
- **O-4:** Whether `chat.type == private` may be relaxed for an operator group later. Default: never.

### Claude's Discretion
- Module placement and names (the shared confirm core, the user-id gate, the money-block carrier and its formatter), the migration design for the approval carrier and the index predicate, the exact refusal texts (English, plain), the `RetryAfter` cap, the fixtures and fakes, and the plan and wave split. Respect AGENTS.md: Decimal-only, no wall clock in pure modules, `src/core` untouched, new parameters carry provenance, no pre-release dependency.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Decisions and rules
- `docs/DECISIONS.md` D041 — two-step confirm contract (card contents, token properties, TTL, SHADOW parity)
- `docs/DECISIONS.md` D051, D078 (item 6), D080 — approval persistence, quantity on the message, never re-send a placement
- `docs/integration/TELEGRAM.md` — message formats, callback wire format, trust model (to be extended, D-04)
- `docs/DOC_STATUS.md` — index line required when a canonical doc changes
- `AGENTS.md` — Decimal-only, no wall clock in pure modules, fail closed, gated file rules

### Planning artifacts
- `.planning/ROADMAP.md` Phase 23 section (criteria 1–5, inherited items G4-032, G4-042, P16R-02, P20-OPS-REMOTE)
- `.planning/phases/23-telegram-approval-hardening-money/23-NOTES.md` — alert wording, failed-alert rule, quantity line
- `.planning/phases/22-leverage-margin-liquidation-guard/22-CONTEXT.md` — verified leverage/margin in the constraint snapshot, reason-code discipline
- `.planning/phases/21-account-equity-daily-loss/21-CONTEXT.md` — equity record, source and timestamp
- `.planning/phases/19-execution-plan-binding-price-check/19-CONTEXT.md` — D-05 pre-placement refusals, D-09 executed plan stays APPROVED
- `.planning/phases/16-paper-runtime-composition/deferred-items.md` — P16R-02 detail
- `.planning/phases/17-operational-persistence-layer/17-14-SUMMARY.md` (G4-032), `17-REVIEW.md` (G4-042)
- `.planning/phases/20-reconcile-safe-mode-hardening/20-DEFERRED.md` — operator alert events, remote commands

### Code
- `src/adapters/telegram_callbacks.py` — parse, chat gate, `dispatch_callback`, `on_callback`, `build_application`
- `src/adapters/telegram_notify.py` — keyboards, `format_approve`, `edit_text`, `classify_telegram_error`
- `src/paper/shadow_confirm.py` — `ConfirmBook`, card delivery, restart expiry (D-09 model)
- `src/approval/` (`tokens.py`, `binding.py`, `replay.py`, `mapping.py`), `src/domain/approval.py` (`actor_id`)
- `src/execution/pre_placement.py`, `execution_limits.py`, `constraint_snapshot.py`, `account_equity.py`
- `src/paper/runtime.py` / `runtime_config.py` — `TELEGRAM_AUTHORIZED_CHAT_ID` handling
- `tests/test_phase21_gate.py` (RejectionReason pin), `tests/support/ast_guards.py`
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `build_shadow_decision_keyboard`: already one row with APPROVE (`APR:`) and SKIP (`SKP:`), the model for LIVE/DEMO.
- `ConfirmBook`, `deliver_confirm_card`, `make_confirm_callbacks`: full confirm state machine for SHADOW, in-memory token, TTL, journaled outcomes.
- `classify_telegram_error` / `TelegramSendError` / `edit_text` / `send_text`: classified Telegram failures including message-not-modified.
- `pre_placement.evaluate_pre_placement` and the single checks: the re-run at confirm time.
- `Approval.actor_id` field, `_build_chat_reject_receipt`, `CALLBACK_RESOLVED/REJECTED` journal events.

### Established Patterns
- PTB-free pure surfaces and PTB imports only inside `build_application` and keyboard builders; tests never build an Application.
- Hooks injected into `on_callback` (`confirm_handler`, `approved_handler`, `clock`); correlation id from `callback_query.id`.
- Fail closed with a plain reason code; new codes are pinned by gate tests and the GLOSSARY.
- Golden-text tests for messages; fixtures regenerated by scripts, never hand-typed.

### Integration Points
- Approval row and short-id mapping (Alembic): `actor_id`, money carrier, unique-index predicate (G4-042).
- `runtime_config` / `runtime`: the new `TELEGRAM_AUTHORIZED_USER_IDS` value.
- The `on_confirmed` seam that Phase 24 connects to `execute_approved_plan`.
- Phase 20 `CriticalAlertSink` (formatters plug in); Phase 21 equity and Phase 22 constraint snapshot (money inputs).
</code_context>

<specifics>
## Specific Ideas

- Live Telegram test of 2026-10-04 is the evidence base for criterion 5: 3 taps gave 1 transition but the button stayed; `actor_id` was empty; no CONFIRM step; no handler for "Query is too old"; no money; wrong timezone note; one message carried one button.
- SKIP must be recorded and visible in the attribution (PAPER-02: system vs user-executed vs opportunity).
</specifics>

<deferred>
## Deferred Ideas

- Remote operator commands over Telegram (SAFE_MODE exit, `rest_gate_cli status/clear`, EXEC-06 controls): P20-OPS-REMOTE, wired by Phase 24; this phase only provides the allow-list and confirm they will reuse.
- Local-time display preference (O-3).
- Second-account / group-chat live rejection check (G2-014): owner-run in Phase 24/25.
- Multiple operators with roles.

### Reviewed Todos (not folded)
None matched.
</deferred>

---

*Phase: 23-Telegram Approval Hardening + Two-Step Confirm + Money Amounts*
*Context gathered: 2026-10-25*
