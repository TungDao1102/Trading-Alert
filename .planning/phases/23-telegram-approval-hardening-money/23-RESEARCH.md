# Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts - Research

**Researched:** 2026-10-25
**Domain:** Telegram approval path (python-telegram-bot 22.8), shared two-step confirm core, money block carried with the approval
**Confidence:** MEDIUM-HIGH. Every code seam below was opened with Read this session. Three Telegram Bot API behaviours could not be confirmed from an authoritative page and are tagged `[ASSUMED]` (see Assumptions Log); the plan is designed so none of them can cause a wrong order.

<user_constraints>
## User Constraints (from CONTEXT.md)

Source: `23-CONTEXT.md` (gathered 2026-10-25 with `--auto`). D-01..D-17 are locked defaults; O-1..O-4 are OWNER-OPEN and must not be implemented with a number. Condensed, nothing added:

### Locked Decisions
- **D-01** Pure gate BEFORE any state lookup, after the existing chat gate: `from_user.id` in an allow-list AND `chat.type == private`. Missing `from_user`, non-private chat, or id not listed: refused, no state change, journaled (shape of `_build_chat_reject_receipt`), plain reason code (D-15). `authorized_chat_gate` stays.
- **D-02** Allow-list from env `TELEGRAM_AUTHORIZED_USER_IDS` (comma-separated ints) read by `runtime_config`/`runtime` beside `TELEGRAM_AUTHORIZED_CHAT_ID`; missing or unparsable is a startup refusal (`ConfigNotRatified`), never allow-all. Never printed in full in logs/journals; journal stores only the pressing actor's id.
- **D-03** `Approval.actor_id` = Telegram `from_user.id` (text) at APPROVE and SKIP; CONFIRM/CANCEL journal events carry it; replays keep the first actor.
- **D-04** Token trust model (F-127) documented in `docs/integration/TELEGRAM.md`, not changed in code.
- **D-05** One message carries APPROVE + SKIP in LIVE and DEMO as SHADOW already does (`build_shadow_decision_keyboard`); single-button and SIMULATE builders stay for wire stability but are not sent by any production path; a test pins SKIP recorded as `SKIPPED` (F-405), not SIMULATE_RECORDED.
- **D-06** After any decision (APPROVE to card, SKIP, CONFIRM, CANCEL, expiry) edit to final text and remove the keyboard in the same edit; stale tap answered "already decided", no state change; replays stay idempotent; a failed keyboard removal does not roll the decision back (journal it; the stale-tap refusal is the backstop).
- **D-07** `RetryAfter` and other Telegram errors via `classify_telegram_error`/`TelegramFailureKind`: sleep `retry_after` (bounded by a named cap), retry the MESSAGE at most `NOTIFY_MAX_ATTEMPTS`; never retry anything that places an order (Q5, D080); no auto-approve on notification failure.
- **D-08** Application error handler; "Query is too old" `BadRequest` swallowed (debug log) by `answer_callback_safely`, never stops the press; any other handler exception journaled with the correlation id and answered neutrally; no traceback loop, no unanswered spinner.
- **D-09** Extract `ConfirmBook`'s mode-independent core (token issue, single use, user+plan-hash binding, 60 s TTL, journaled CANCEL/expiry, replay-to-existing, restart expiry `RUNTIME_RESTART`) into a shared module used by SHADOW, DEMO and LIVE; SHADOW keeps its no-placement guarantee via `on_confirmed` (imports nothing from `src.execution`); in DEMO/LIVE `on_confirmed` stays an injected callable (Phase 24 connects `execute_approved_plan`); SHADOW behaviour byte-identical.
- **D-10** TTL 60 s configurable (not a strategy parameter); confirm token distinct, single-use, bound to same `from_user.id` + plan hash. Other user, double tap, replay, after TTL, after plan expiry, after price crossed SL: each a journaled refusal, no placement.
- **D-11** Pre-placement checks re-run at CONFIRM via `src/execution/pre_placement.py` fed fresh inputs; confirm core takes ONE injected callable returning a reason code or None; stale/missing mark = refusal; card shows the same minimum-validity rule the gate applies (Phase 19 D-05/D-09; criterion 3, F-016).
- **D-12** Ambiguous entry (intent `UNKNOWN` + SAFE_MODE) shown as "needs reconciliation", never "rejected"; G4-032: a redelivered APPROVE after expiry reads the stored outcome through `PgExecutionStateStore.get_entry` and says "already executed"/"needs reconciliation" instead of `APPROVAL_EXPIRED`.
- **D-13** After `Quantity:`: notional; margin at the verified leverage (Phase 22 snapshot); estimated loss at SL and profit at each TP, gross and net of modeled costs; equity used with source and timestamp (Phase 21). Read from stored pipeline output; renderer does arithmetic only to format; missing field refuses to render/send. Money fields join the hashed or stored approval payload; planner decides carrier and whether a migration is needed. Fixed-point Decimal text, never rounded up, quote asset named.
- **D-14** SIMULATE also shows the money block plus the quantity line it lacks. Times shown as UTC with explicit suffix `UTC`; delete the "Asia/Ho_Chi_Minh" display note. Operator-alert wording: one pure formatter per event with golden tests, reason codes verbatim (`CLOSE_REQUIRED` B1-B5/`NO_POSITION_ON_STOP_BUT_EXPOSED`, `TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED`, `EMERGENCY_CLOSE_NOT_SENT`, `ENTRY_STATE_UNKNOWN`, `PROTECTION_HANDOFF_FAILED`, `DB_FAILURE`, `RECONCILIATION_REQUIRED`).
- **D-15** New plain reason codes added deliberately; `RejectionReason` is pinned by `tests/test_phase21_gate.py` invariant 3 and listed in GLOSSARY; plan updates both in the same change; no existing code reused with a changed meaning.
- **D-16** P16R-02: `_deferred_confirmed` becomes a LIST, `on_confirmed` once per adopted confirm, test with two adoptions in one sweep mandatory. G4-042: exclude `EXPIRED` from the unique-index predicate (OWNER-OPEN O-2), DATA_MODEL line, Alembic migration. G4-032 per D-12. P20-OPS-REMOTE deferred, but allow-list and confirm built reusable.
- **D-17** Nothing composed into a running process (Phase 24). Proven with fakes (`tests/support/`), local PostgreSQL where approval/index changes, PTB-free surfaces. `build_application` not called from unit tests. G2-014 (second account / group tap) is an owner-run item for Phase 24/25. `LIVE_ORDERS_DISABLED` stays.

### Claude's Discretion
Module placement and names (shared confirm core, user-id gate, money carrier and formatter), migration design for the carrier and the index predicate, exact refusal texts (English, plain), the `RetryAfter` cap, fixtures and fakes, plan and wave split.

### Deferred Ideas (OUT OF SCOPE)
Remote operator commands (P20-OPS-REMOTE), local-time display preference (O-3), second-account/group live check (G2-014), multiple operators with roles. OWNER-OPEN: O-1 allow-list content, O-2 G4-042 rule, O-3 local time, O-4 relaxing `private`.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| APRV-01 | Alerts carry the 12 fields (+ quantity, + money block this phase) | `format_approve` is the single APPROVE renderer; `format_simulate` (`src/paper/notify.py`) the SIMULATE one; money carrier section |
| APRV-02 | Approval bound to signal, version, plan hash, expiry, authorized chat, one-time token; idempotent; no auto-approve on notify failure | `check_binding_full`, `resolve_callback`; user-id gate seam; confirm core binds user id + plan hash |
| PAPER-02 | system vs user-executed vs opportunity attribution; skipped/expired recorded | SKIP via `build_shadow_decision_keyboard` resolves `ApprovalAction.SKIP_USER` -> `SKIPPED`; `actor_id` persisted by `_decide` (currently NOT); `src/paper/attribution.py` consumes `SHADOW_CONFIRM*` names |
</phase_requirements>

## Summary

The phase is mostly plumbing on four existing seams, plus one genuinely new thing (the money block) and two persistence changes. The biggest findings, all verified by reading the code:

1. **`actor_id` is never persisted by Postgres.** `PgApprovalStore._decide` updates only `result`, `status`, `acted_at_utc` (`src/persistence/approvals.py:245-249`). So the live finding "actor_id is empty" is a store bug, not only a missing value. SHADOW stamps `actor_id` with the CHAT id (`src/paper/shadow.py:549-553`), and that stamp is also dropped by `_decide`. D-03 needs three changes: carry `from_user_id` from `_answer_press` into dispatch (it is not passed today), set it inside the PENDING-to-decided `replace` in `resolve_callback`, and add `actor_id` to the `_decide` UPDATE. No migration (`approvals.actor_id` is `String(64)` NOT NULL already, `src/db/models.py:352`).
2. **`chat.type` is never read anywhere**, and there is no keyboard removal and no error handler (`build_application` registers only `CallbackQueryHandler`). `answer_callback_safely` already swallows every exception from `query.answer()`, so the "Query is too old" part of D-08 is already satisfied for that call; the missing part is the Application-level error handler for exceptions raised from `on_callback` itself (`ValueError`s at lines 774-796).
3. **The money block cannot be "read, not recomputed" from today's pipeline output alone.** The risk pipeline already yields quantity, `realized_risk` (net of modeled costs, adverse edge), `modeled_costs_per_unit`, `sizing_entry_price`, fee rates; Phase 22 yields `leverage` and `equity_used` (no source, no timestamp) in `PlanConstraintSnapshot`; Phase 21 yields equity + `observed_at_utc`. Notional, margin, gross/net loss at SL and gross/net profit per TP are NOT produced anywhere (profit at TP not at all). They must be computed ONCE, in a new pure risk-layer function at plan-issue time, stored with the approval, and only formatted by Telegram code. This satisfies F-015 ("never recomputed" = not recomputed by the messaging layer) and must be called out to the owner in the plan.
4. **Shared confirm core: SHADOW is welded to the module** (`require_shadow` at 7 sites, `SHADOW_*` event names consumed by `src/paper/attribution.py`, entity type `ShadowConfirm`, id prefix `shadow-cnf`, SHADOW time-pair wording pinned by many tests). Extraction must parametrize names by a mode profile whose SHADOW values are today's literals.
5. **Do not add `RejectionReason` members.** ~9 test files pin `len(RejectionReason) == 21` and the GLOSSARY 9.1 block equals the enum (gate GL-03). All 18+ existing pre-placement/binding codes are plain strings in GLOSSARY 9.3 (precedent: Phase 22 amendment A3). Use plain strings + 9.3 rows. D-15's "plain reason codes" reads that way.
6. **Migration head pins:** `tests/test_phase21_gate.py:247-253` and `tests/test_phase22_gate.py:383-389` assert head `0012_reservation_margin`; `tests/test_persistence_migration_pg.py` has 0012 constants. Any 0013 must update these on purpose.

**Primary recommendation:** Build in four waves: (A) pure pieces with no persistence (user/private gate, stale-tap/keyboard removal, error handler, RetryAfter wrapper, alert wording formatters); (B) shared confirm core extraction + P16R-02 list fix, SHADOW tests unchanged and green; (C) persistence (actor_id write, G4-042 index migration, money carrier column + store) with PG tests; (D) money block builder + renderers + DEMO/LIVE card + G4-032 reply + docs/GLOSSARY/DOC_STATUS. Keep SHADOW output byte-identical; DEMO/LIVE get new composers.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| User-id allow-list + private-chat gate | Adapter edge (`telegram_callbacks`) pure predicate | Runtime config (env parse) | Must run before any state lookup; config only supplies the set |
| actor_id recording | Approval core (`resolve_callback`) | Persistence (`_decide`) | Actor belongs to the transition; store must write it |
| Keyboard removal, stale-tap refusal, RetryAfter | Adapter edge (`telegram_notify` + `on_callback`) | Confirm core (state says "decided") | Telegram-specific I/O; core only reports state |
| Confirm state machine (token, TTL, bindings, journal) | Shared pure core (new module, `src/approval/` or `src/paper/`-neutral) | Mode profile (SHADOW/DEMO/LIVE names) | Mode independent (D-09) |
| Pre-placement re-run at CONFIRM | Injected callable (composition, Phase 24) | `src/execution/pre_placement.py` pure functions | Core must stay free of exchange imports (D-11) |
| Money numbers | Risk layer (new pure builder next to `src/risk/margin_check.py`/`sizing.py`) | Persistence (stored with approval) | Computed once from pipeline outputs; Telegram only formats |
| Money text | Adapter edge renderers | - | Arithmetic-free formatting of stored Decimal text |
| Operator-alert wording | Ops (`src/ops/`, pure formatter) | `JournalFirstAlertSink`/`TelegramAlertSender` (Phase 20) | Phase 20 owns sink/retry; this phase owns the words |
| Outcome after expiry (G4-032) | Composition reply function | `PgExecutionStateStore.get_entry` | Binding gate cannot know execution state |

## Standard Stack

No new dependency. `uv add` is not needed. `[VERIFIED: uv.lock]` `python-telegram-bot` version = `22.8` (`uv.lock` line 812: `version = "22.8"`), installed at `.venv/Lib/site-packages/python_telegram_bot-22.8.dist-info`. Existing in-repo libraries to reuse: `structlog`, `tenacity` (already used in `src/paper/shadow.py` and `src/ops/alerts.py` for bounded retry), SQLAlchemy 2 + Alembic (hand-written migrations, last `0012_reservation_margin`).

### Package Legitimacy Audit
No external package is installed by this phase. Table not applicable. `python-telegram-bot` 22.8 is already locked and in use.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New `RejectionReason` members | Plain-string codes in GLOSSARY 9.3 | Enum change breaks ~9 pin tests and GL-03; plain strings are the established pattern (`pre_placement.py`, `binding.py`) |
| Money fields as columns on `approvals` | One nullable `money_json` TEXT column + hash, or a journal payload | Columns ripple into `Approval`, mappers, `tests/test_domain_entities.py`; a single JSON column mirrors `PlanConstraintSnapshot.canonical_json` |
| PTB `RetryAfter` handling inline | Reuse `classify_telegram_error` + the pattern of `deliver_confirm_card` | Already tested; do not hand-roll |

## Architecture Patterns

### System Architecture Diagram

```
Telegram update (callback_query)
   |
   v
PTB Application --(error)--> app error handler: journal(correlation) + neutral answer   [NEW, D-08]
   |
   v
on_callback (telegram_callbacks.py:741)
   1 answer_callback_safely   (already swallows all)
   2 parse_callback_data      (APR/SKP/CNF/CXL; SIM/SKIP inert)
   3 chat gate (authorized_chat_gate)
   4 USER+PRIVATE gate  [NEW]  -- refuse: journal receipt + plain reason, no lookup, keyboard untouched
   5 kind routing
        APR/SKP --> dispatch_callback --> resolve_callback --> store._decide(+actor_id) [NEW]
                        |                        |
                        |                        +-- decided row (APPROVED|SKIPPED)
                        v
                 approved_handler (APPROVE)  --> confirm core.issue --> edit msg into card + CONFIRM/CANCEL
                 SKIP                        --> edit msg to final text, keyboard removed [NEW]
        CNF/CXL --> confirm_handler --> confirm core.handle_confirm / handle_cancel
                        |  press gate (chat, user) -> TTL -> binding gate -> injected recheck(pre_placement) -> journal terminal
                        v  on_confirmed(approval, plan, at)  [injected; Phase 24 -> execute_approved_plan]
   6 stale tap on a decided message --> short "already decided" answer, no state change [NEW]
   7 final edit: text + empty keyboard (same edit) ; failure journaled, decision stands [NEW]
Money: risk pipeline output -> build_money_at_stake (pure, risk layer) -> stored with approval PENDING rows
       -> format_approve / confirm card / SIMULATE render stored Decimal text only
```

### Recommended Project Structure
```
src/approval/confirm_core.py     # NEW shared ConfirmBook core (no telegram, no src.execution, no src.paper imports)
src/paper/shadow_confirm.py      # SHADOW profile + card delivery; thin over confirm_core, public names unchanged
src/adapters/telegram_callbacks.py  # user/private gate, stale-tap, error handler registration
src/adapters/telegram_notify.py     # remove-keyboard helper, DEMO/LIVE renderers (money block, UTC)
src/risk/money_at_stake.py       # NEW pure builder (Decimal-only, no clock); next to margin_check.py
src/ops/alert_wording.py         # NEW pure per-event formatters (Phase 20 sink untouched except one call site)
src/db/alembic/versions/0013_*.py  # money_json (+ G4-042 index predicate, possibly 0014)
```

### Pattern 1 - SHADOW-neutral confirm core
**What:** `ConfirmBook` + `ConfirmEntry` + press gate + binding gate + TTL/restart sweeps move to `confirm_core.ConfirmBook(profile: ConfirmProfile, ...)`. `ConfirmProfile` carries the strings that are pinned today for SHADOW: event names `SHADOW_CONFIRM_ISSUED/CONFIRMED/CONFIRM_CANCELLED/CONFIRM_EXPIRED/CONFIRM_REJECTED/CONFIRM_NOTICE_FAILED`, entity type `ShadowConfirm`, correlation `shadow-confirm:<approval_id>`, journal id prefix `shadow-cnf`, payload key `"mode"`. `shadow_confirm.ConfirmBook` stays importable as a subclass/alias with SHADOW profile and keeps `require_shadow` there.
**When to use:** all three modes. DEMO/LIVE profiles use their own event names (planner decides, e.g. `DEMO_CONFIRM*`); `src/paper/attribution.py` currently reads only the SHADOW names (lines 74-76) so DEMO/LIVE attribution is a later consumer.
**Source:** `[VERIFIED: src/paper/shadow_confirm.py:93-100, 342, 410-426]` quoted below.

### Pattern 2 - Gate before lookup, journal via the injected `dispatch`
`on_callback` has no journal handle (the journal lives in the `dispatch` closure, `ShadowApprovalBook.dispatch` passes `journal_receipt=self._stores.record_journal`). So the user/private rejection receipt must be built by a new `_build_user_reject_receipt` (sibling of `_build_chat_reject_receipt`, distinct `step` label so `correlated_event_id` stays unique) and written by `dispatch_callback` through new OPTIONAL kwargs (`from_user_id`, `chat_type`, `authorized_user_ids`). `on_callback` ALSO evaluates the pure predicate itself first, fail closed, so the gate cannot be skipped by a dispatcher that ignores the kwargs. Existing direct callers of `dispatch_callback` (tests) omit the kwargs; `on_callback`/`build_application` take `authorized_user_ids` as REQUIRED keyword-only (no default = never allow-all).

### Anti-Patterns to Avoid
- **Money arithmetic in `telegram_*`**: today `render_confirm_card` multiplies (`notional = quantity * entry_ref`, `estimated_loss = quantity * abs(entry_ref - plan.stop_loss_price)`, `src/paper/shadow_confirm.py:231-232`) and `shadow_runtime.on_outcome` computes `exposure_quote=verdict.sized.quantity * _adverse_entry(signal, plan)`. Keep these for SHADOW (byte-identical); DEMO/LIVE must take stored values.
- **Importing `src.execution.manager` (or the Binance adapter) from the core or from any module in a SHADOW entrypoint closure**: `tests/test_paper_shadow_isolation.py` walks the import closure and bans order modules; only `PURE_EXECUTION_HELPERS` are allowed.
- **Changing the plan hash to cover money/quantity**: the field set is frozen (D051 (c)); store money beside the approval, not in the hash.
- **Treating `expiry_utc` as governing a filled entry**: Phase 19 D-09; only an unfilled entry expires.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telegram error classes, RetryAfter seconds (int or timedelta in PTB 22.x) | New exception parsing | `classify_telegram_error`, `TelegramFailureKind`, `_whole_seconds` (`telegram_notify.py:325-355`) | Already handles the 22.2 timedelta change and "message is not modified" |
| Edit-with-RetryAfter loop inside the TTL window | New loop | Copy the structure of `deliver_confirm_card` (`shadow_confirm.py:1362-1383`) into a generic `edit_final_text_bounded` | Tested; honors `NOTIFY_MAX_ATTEMPTS = 3` (`src/paper/notify.py:111`) |
| One-time token, hash, verify | Own crypto | `issue_one_time_token`, `token_hash_of`, `verify_token_hash` (`src/approval/tokens.py`) | Existing and tested |
| Initial margin | `qty*price/leverage` inline | `required_initial_margin(*, quantity, price, leverage)` (`src/risk/margin_check.py:148`) | One definition, `[CITED: FAQ-margin]` in its docstring |
| Round-trip fee estimate / cost per unit | New cost model | `estimated_fees` (`margin_check.py:159`), `per_unit_round_trip_cost` (`src/risk/cost_rates.py:122`) | Cost parity tests exist (`tests/test_cost_parity.py`) |
| Canonical JSON + sha256 of a value object | Ad-hoc `json.dumps` | The pattern of `src/execution/constraint_snapshot.py` (`canonical_json`, `snapshot_sha256`, `parse_snapshot_json` rejecting floats) | Float-rejecting decode already written |
| Pre-placement refusals | Re-implement price/validity/invalidation checks | `evaluate_pre_placement(PrePlacementInputs)` and the single checks (`pre_placement.py:174-523`) | Order and codes pinned by Phase 19 gate |
| Exactly-once journal ids | Random ids | `correlated_event_id(...)` | Redelivery-safe |

**Key insight:** every hard piece already exists in a tested form; this phase moves it behind a mode-neutral seam and adds persistence for two facts (actor, money).

## Runtime State Inventory

Not a rename phase. Included only for the two persistence changes.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `approvals` rows written before this phase have `actor_id = ''` and no money; index `uq_approvals_one_decided_per_plan` counts every non-PENDING status | New columns nullable, no backfill (same rule as 0006); NULL money = "not recorded" = never renderable/placeable; index migration is a drop + recreate of a partial index |
| Live service config | None - verified: nothing is composed into a running process (D-17) | none |
| OS-registered state | None | none |
| Secrets/env vars | New name `TELEGRAM_AUTHORIZED_USER_IDS`; `ALLOWED_ENV_NAMES` frozenset in `runtime_config.py:73-86` must gain it or the runtime refuses it | add to `ALLOWED_ENV_NAMES`, `.env.example`, `deploy/soak.env.example`; update `tests/test_env_example.py` (line ~151 list), `tests/test_paper_runtime_env.py` |
| Build artifacts | None | none |

## Verified code seams

All claims below read in full this session; values quoted verbatim.

### 1. Authorization, actor, keyboard, error handler (`src/adapters/telegram_callbacks.py`, 1016 lines)
- Gate today: `return callback_chat_id == authorized_chat_id` (`:250`). `chat.type` is not read anywhere. `[VERIFIED: whole-file Read]`
- `_answer_press` passes to `dispatch` only `callback_chat_id, authorized_chat_id, callback_at_utc, raw_token, correlation_id, binding_context` (`:883-892`); the pressing user exists only in `CallbackPress.from_user_id` (`:855-866`) which is used for CONFIRM/CANCEL and `approved_handler`. This is the seam to thread `from_user_id` into dispatch.
- Wrong-chat path replies via `reply_text_fn(int(chat_id), "Rejected")` (`:848-851`); every reply is a NEW message (send), never an edit. No `edit_message_*` anywhere in the module.
- `answer_callback_safely` (`:728-738`): `except Exception as exc: ... log.warning("telegram.callback.answer_failed: %s", type(exc).__name__)` - already swallows everything.
- `build_application` (`:927-969`): `app.add_handler(CallbackQueryHandler(_handler))` only; no `add_error_handler`.
- `dispatch_callback` returns `RejectionReason.INVALIDATED` for wrong chat (`:352`), unknown short id, no binding context, CONFIRM/CANCEL reaching it. All new refusals are plain-string codes, so `DispatchResult.reason_code: RejectionReason | None` must widen to `RejectionReason | str | None` (or a new field `refusal_code: str | None`); this touches `_journal_outcome` (`reason_code.value`) and `_render_outcome_text`. Plan this explicitly.

### 2. `actor_id` write path
- `Approval.actor_id: str = ""` (`src/domain/approval.py:62`).
- `resolve_callback`: `new_approval = replace(approval, result=new_result, status=new_result, acted_at_utc=effective_now)` (`src/approval/replay.py:240-245`) - set `actor_id` here (add `actor_id` to `Callback` or a parameter of `resolve_callback`); replays return the stored row (`:205-206`) so the first actor is kept.
- SHADOW stamp: `stamped = approval if approval.actor_id else replace(approval, actor_id=actor_id)` with `actor_id = str(kwargs["callback_chat_id"])` (`src/paper/shadow.py:549-553`). The pin `assert result.approval.actor_id == str(CHAT_ID)` is `tests/test_paper_shadow_buttons.py:130`; in a private chat user id == chat id numerically so the test can keep passing by passing equal ids, but the intent changes: switch it to the user id.
- **Persistence gap:** `_decide` `.values(result=approval.result.value, status=approval.status.value, acted_at_utc=approval.acted_at_utc)` (`src/persistence/approvals.py:245-249`) - no `actor_id`. Add `actor_id=approval.actor_id` and a PG test (`tests/test_persistence_approvals_pg.py`).
- Also `invalidate_pending_on_restart` sets `actor_id=pending.actor_id or REASON_RUNTIME_RESTART` (`shadow.py:991`), which suggests the author believed it persisted. After the fix this becomes visible in PG: `String(64)` fits `RUNTIME_RESTART`.

### 3. G4-042 index
- Model: `Index("uq_approvals_one_decided_per_plan", "trade_plan_id", unique=True, postgresql_where=text("status <> 'PENDING'"), sqlite_where=text("status <> 'PENDING'")).ddl_if(dialect="postgresql")` (`src/db/models.py:378-383`); created in `0004_persistence_integrity.py:328-334`.
- Two approval rows per plan (APPROVE and SKIP_USER) exist for every SHADOW alert (`shadow.py:27-30`). A writer for EXPIRED exists already: `invalidate_pending_on_restart` (`shadow.py:977-1019`) decides each PENDING EXPIRED; the second sibling raises `ApprovalAlreadyDecided` and is recorded `LEFT_PENDING_SIBLING_DECIDED`. So G4-042 is a live, handled limitation, not latent (17-REVIEW IN-04 said no writer existed in Phase 17).
- Default O-2 fix: predicate `status NOT IN ('PENDING','EXPIRED')`. **Side effect to fix in the same change:** `_decide`'s race handler selects `ApprovalRow.status != PENDING` with `scalar_one_or_none()` (`approvals.py:257-262`); with EXPIRED allowed a plan may have EXPIRED rows plus one APPROVED/SKIPPED row, so this query must also exclude EXPIRED or it raises `MultipleResultsFound`. Also `risk_reservations.py:631` and `shadow_runtime.py:1121` read EXPIRED approvals; re-read both. `sqlite_where` mirror in `models.py` must change too. Migration is drop + `create_index` with the new `postgresql_where`; downgrade restores the old predicate and must fail clearly if two decided rows per plan exist (it cannot silently succeed).
- Semantics to put in DATA_MODEL/DECISIONS: "at most one APPROVED-or-SKIPPED row per plan; any number of EXPIRED rows". This permits an EXPIRED sibling and later a decision on the other sibling; since both tokens die at restart this is benign, but the planner should state it.

### 4. Confirm core (`src/paper/shadow_confirm.py`, 1585 lines)
- SHADOW-only guards: `require_shadow(mode)` at `:342` (ctor), `render_confirm_card` `:216`, `deliver_confirm_card` `:1355`, `make_confirm_callbacks` `:1480`; `render_shadow_message` `:233` (shadow.py).
- Journal constants: `EVENT_SHADOW_CONFIRMED: Final = "SHADOW_CONFIRMED"` etc. (`:93-100`); `_correlation(approval_id)` = `f"shadow-confirm:{approval_id}"` (`:298-299`); `_event(...)` uses `prefix="shadow-cnf"`, `entity_type="ShadowConfirm"` (`:410-426`).
- Reason constants (`:108-116`): `CONFIRM_TTL_ELAPSED, CARD_DELIVERY_FAILED, RUNTIME_RESTART, USER_ID_UNAVAILABLE, USER_MISMATCH, CHAT_MISMATCH, NO_CONFIRM_CONTEXT, RECHECK_ERROR, CONFIRM_ALREADY_EXPIRED`. These are plain strings; D-15's new codes follow this pattern.
- Token: raw token in memory only (`ConfirmEntry.raw_token`), lookup by short id; `_press_gate` checks chat then `from_user_id != entry.approving_user_id` (`:720-756`) - the "another user" refusal already exists for the approving user; the allow-list is an additional, earlier gate.
- `OnConfirmedFn = Callable[[Approval, TradePlan, datetime], None]` (`:131`), `RecheckFn = Callable[[Signal, TradePlan, datetime], RejectionReason | str | None]` (`:130`), `MarkPriceFn = Callable[[str], Decimal | None]` (`:132`). These are the D-11 injection points; a DEMO/LIVE composition builds `recheck` from `evaluate_pre_placement`. NOTE both are SYNCHRONOUS and run under `threading.RLock` (`:351`), whereas fresh exchange reads (mark, last price, position mode) are async in Phase 24; the plan must decide how the composition feeds fresh inputs (pre-fetch before calling `handle_confirm`, or run `handle_confirm` in `asyncio.to_thread` with a thread-safe sync reader). Do not make the core async.
- **P16R-02 site:** declaration `self._deferred_confirmed: tuple[Approval, TradePlan, datetime] | None = None` (`:360`); reset at `_in_section` start `self._deferred_confirmed = None` (`:895`); set in `_finish_confirm` `self._deferred_confirmed = (entry.approval, entry.plan, confirmed_at_utc)` (`:1077`); drained after the lock: `deferred, self._deferred_confirmed = self._deferred_confirmed, None` then `self._on_confirmed(*deferred)` (`:909-911`). Adoption in a sweep: `_expire_held_locked` (`:1211-1219`) -> `_reconcile_unknown` -> `_adopt_stored_confirm` -> `_finish_confirm`. Fix = `list`, append, drain in order. Sweeps via `expire_due` go through `_in_section(lambda: self._expire_held_locked(now_utc))` (`:1207`).
- Hook call is made OUTSIDE the book lock and the reservation section (B2-CR-01); keep that invariant in the extraction (lock-order test: `tests/test_paper_shadow_lock_order.py`).

### 5. Message renderers
- `format_approve` (`telegram_notify.py:416-535`): ends with `f"Display: Asia/Ho_Chi_Minh (UTC internally)"` (`:534`) and ISO UTC `Detected:`/`Expiry:` lines. `format_shadow_alert` removes exactly those three lines and raises `RuntimeError("format_approve no longer has the Detected/Expiry/Display lines")` if the count differs (`shadow.py:382-387`). Removing the Display line (D-14) therefore requires the same-change update of this guard; SHADOW output must stay identical.
- SHADOW times are `format_time_pair` = UTC + `Asia/Ho_Chi_Minh` (shadow.py:201-207) and are pinned by `tests/test_paper_shadow_messages.py:92,93,333-370`, `tests/test_paper_shadow_confirm.py:817-818`, and the helper `tests/shadow_fakes.py:44-56` (`assert text.count("Asia/Ho_Chi_Minh") == len(pairs)`; `FakeBot.send_message/edit_message_text` call `assert_shadow_text` on every text). **Conflict D-14 vs D-09:** D-14 says delete the local-time note; SHADOW tests pin local time pairs. Recommendation: apply D-14 only to the `format_approve` standalone (Demo rehearsal, SIMULATE) and to NEW DEMO/LIVE composers; leave SHADOW pairs untouched; record as an owner-visible note under O-3. A DEMO/LIVE `FakeBot` variant is needed because `FakeBot` asserts the SHADOW label.
- SIMULATE: `src/paper/notify.py:122` `format_simulate(...)` (12 fields, no quantity) and `build_simulate_keyboard` (`:256`). It is only reached from the Phase 7 notify function; no production composition sends it today.
- Production senders today: SHADOW `send_shadow_alert` uses `build_shadow_decision_keyboard` (`shadow.py:803`) so D-05 is already true there. The only other sender of APPROVE text is the owner-run script `scripts/demo_rehearsal.py` (`send_approval` uses `build_approve_keyboard` / `build_skip_keyboard`, i.e. two separate messages, and `render_approval_text` calls `format_approve`; it builds its application with NO `confirm_handler`). Planner must either update the script (and `tests/test_demo_rehearsal_flow.py`, `tests/test_demo_rehearsal_safety.py`) or record it as out of scope; it is an owner-run script and a consumer of the new required `authorized_user_ids` argument.

### 6. Config / runtime
- `ALLOWED_ENV_NAMES` (`src/paper/runtime_config.py:73-86`) is a closed frozenset including `TELEGRAM_BOT_TOKEN`, `TELEGRAM_AUTHORIZED_CHAT_ID`.
- `_shadow_from_env` (`src/paper/runtime.py:505-535`): returns `None` (SKIPPED start) when token OR chat is empty; raises `ConfigNotRatified([...])` for a non-integer chat. Add: when token and chat are both set, `TELEGRAM_AUTHORIZED_USER_IDS` missing/empty/any non-integer item -> `ConfigNotRatified(["TELEGRAM_AUTHORIZED_USER_IDS (...)"])`. Keep "no Telegram configured" a SKIPPED start (D-02's "startup refusal" applies when Telegram is configured; otherwise runs without Telegram would start refusing). Names-only in the refusal list (never the ids).
- `ShadowWiring(stores=..., chat_id=..., application_factory=...)` and `application_factory(callback_kwargs)` -> `build_application(token=token, **callback_kwargs)`: the allow-list must flow through `ShadowWiring`/callback_kwargs (find where `callback_kwargs` is assembled in `src/paper/shadow_runtime.py`; not yet read in full).
- Other readers of the chat id env: `scripts/shadow_rehearsal.py:331-340`, `scripts/demo_rehearsal.py:209-210`, `deploy/soak.env.example:39-40`, `.env.example:45-53`, `docs/operations/DEPLOY_GUIDE.vi.md:1615` (Vietnamese; `tests/test_deploy_guide_vi.py:944` pins a list of names).

### 7. Money inputs (where each value exists today)
| Needed | Exists today | Gap |
|--------|--------------|-----|
| quantity | `TradePlan.quantity_after_rounding`, `Approval.approved_quantity` (migration 0006) | none |
| sizing entry (adverse edge) | `SizedResult.sizing_entry_price` (`src/risk/types.py:131`) | SizedResult is not stored with the approval in SHADOW (only `quantity` and `realized_risk` go to the plan-context journal, `shadow_runtime.py:575`) |
| net loss at SL | `SizedResult.realized_risk` = `rounded x risk_per_unit` where `risk_per_unit = sl_distance + costs` (`src/risk/quantization.py` docstring, `gating.py:177-178`) | gross = `qty x sl_distance` not produced |
| modeled costs | `SizedResult.modeled_costs_per_unit`, `fee_rate_entry/exit`, `fee_source` | slippage rates are inside `CostRates` only, not in `SizedResult` |
| profit at TP1/TP2 gross/net | nothing | new pure function; TP prices in `plan.take_profit_json`, fractions `TP1_QUANTITY_FRACTION` (`src.backtest.semantics`, imported by `shadow.py:75`) |
| notional | not stored | `qty x entry` product, to compute once in the builder |
| margin at verified leverage | `required_initial_margin(...)`; leverage = `PlanConstraintSnapshot.leverage: int | None` (`constraint_snapshot.py:160`), reservation row `margin_leverage`, `required_margin` (migration 0012, `models.py:1147-1149`) | SHADOW has no exchange leverage; Phase 22 target leverage 5 (D085) is a config-guard value `target_leverage` (`margin_guard.py:248-254`) |
| equity used | `PlanConstraintSnapshot.equity_used`, `LiveEquityResult.equity`, `AccountEquityReading.observed_at_utc` (`src/risk/live_equity.py:73-99,156-166`), basis `min(totalWalletBalance, totalMarginBalance)` (D086) | **No "source" field exists.** SHADOW equity = `config.account.initial_equity` (`runtime_config.py:204,309-318`), no timestamp |

Carrier recommendation: frozen dataclass `MoneyAtStake` (Decimal fields + `quote_asset`, `equity_source` label constant, `equity_observed_at_utc`, `leverage` int, `leverage_source`) with `canonical_json`/`sha256` like `PlanConstraintSnapshot`; built by a pure function in `src/risk/` (no clock, no float; AST guards in `tests/support/ast_guards.py` apply); persisted as ONE nullable `approvals.money_json` TEXT column (+ `money_sha256` optional) written with the PENDING rows (APPROVE and SKIP rows identical, as `approved_quantity` is); NULL = not recorded = renderer refuses. This needs Alembic `0013` (money) and, separately, `0014` (index) so the owner decision O-2 does not block the carrier. Do NOT put money into the plan hash.

### 8. Pre-placement functions for the injected recheck
`evaluate_pre_placement(PrePlacementInputs)` order: status, invalidation, remaining validity, symbol free, mark price, last price (`pre_placement.py:466-523`); `check_position_mode` separate (`:454`). Reason strings are plain (`MARK_PRICE_UNAVAILABLE`, `MARK_PRICE_CROSSED_STOP`, `VALIDITY_TOO_SHORT`, `LIMITS_NOT_CONFIGURED`, `PLAN_INVALIDATED_BEFORE_PLACEMENT`, ... lines 44-62). `PrePlacementInputs` has 25 required fields (`:101-145`); the card's "remaining validity" line should call `check_remaining_validity(expiry_utc, now_utc, min_remaining_validity_seconds, gtd_clock_margin)` (`:254-276`) so the card and the gate cannot disagree (criterion 3). `min_remaining_validity_seconds` comes from `config/execution/execution-limits-v1.toml`, which still has `NOT_CONFIGURED` keys (AGENTS.md; owner register `19-OWNER-GAPS.md`): with it unset the card must show the refusal (`LIMITS_NOT_CONFIGURED`), not invent a number.

### 9. G4-032 and D-12 outcome
`check_binding_full` returns `APPROVAL_EXPIRED` once `now_utc >= expiry_utc`, before looking at the token (`binding.py:225-227`) - hence a redelivered APPROVE after expiry is answered `APPROVAL_EXPIRED` even if executed. `check_binding_identity` (`:140-182`) exists to prove identity without the expiry gate (used by the execution manager). `PgExecutionStateStore.get_entry(*, approval_id) -> IntentRecord | None` (`src/persistence/execution_state.py:158-166`); `IntentRecord.intent_status` is `ExecutionIntentStatus` with members `INTENDED, SENT, ACKED, REJECTED, UNKNOWN` (`src/domain/enums.py:273-277`). Recommended pure function `describe_prior_outcome(intent: IntentRecord | None) -> str | None` returning `already executed` (ACKED), `needs reconciliation` (UNKNOWN, SENT, INTENDED), `rejected` (REJECTED), None otherwise; the reply layer calls it only when dispatch returned `APPROVAL_EXPIRED` and the stored approval is APPROVED. Test double: `tests/support/intent_store_fakes.py::InMemoryExecutionIntentStore.get_entry`.

### 10. Operator alert wording seam
`ALERT_EVENTS` has 20 events (`src/ops/alerts.py:95-122`), all in the closed contract; `render_alert_text(alert)` is the single template (`:235-248`) called only at `:633` (`TelegramAlertSender.drain`) and pinned at `tests/test_alerts.py:292`. `OperationalAlert` carries only `event, severity, subject, reason, occurred_at_utc, plan_hash, symbol` - so "what the system already did / what to do" must come from a static per-event table, never from free text. `RECONCILIATION_REQUIRED` is NOT in `ALERT_EVENTS` (it is an outcome / `RejectionReason` member); D-14 lists it, so the formatter must accept it as an outcome label without extending Phase 20's closed contract, or the planner must ask. Recommend a new `format_operator_alert(alert)` that falls back to `render_alert_text` for events without wording, called from `drain`; `render_alert_text` stays untouched so its Phase 20 test keeps passing. The alert text must stay within the sanitisation regexes (`_CODE_RE`, `_SUBJECT_RE`) already enforced on the fields.

## Common Pitfalls

### Pitfall 1: Adding `RejectionReason` members
**What goes wrong:** `tests/test_phase21_gate.py:203`, `test_backtest_engine.py:535`, `test_daily_loss.py:563`, `test_domain_enums.py:239,312`, `test_decision_alignment_bookkeeping.py:84,87`, `test_geometry_audit_doc.py:246`, `test_margin_guard.py:1301`, GLOSSARY 9.1 (GL-03) all fail.
**How to avoid:** plain strings in a constants module + GLOSSARY 9.3 rows (GL-05 checks 9.3 names exist; `scripts/decision_alignment/bookkeeping.py:199-202`). If the owner insists on enum members, list all those files in the plan.

### Pitfall 2: Migration head pins
`tests/test_phase21_gate.py::test_invariant_6...` and `tests/test_phase22_gate.py::test_invariant_7...` assert `alembic_head_revision() == "0012_reservation_margin"` with a message telling the next migration to update them on purpose; `tests/test_persistence_migration_pg.py` has 0012 constants. Update all three with the new head.

### Pitfall 3: `make_callback_update` has no chat type
`tests/shadow_fakes.py:303-329` builds `effective_chat=SimpleNamespace(id=chat_id)`; other tests build their own (`tests/test_journal_ids.py:352`, `tests/test_phase8_audit_reviewfix.py:427`, `tests/test_demo_rehearsal_flow.py:650`). The gate must be fail-closed (`getattr(chat, "type", None) != "private"` refuses), so every fake must gain `type="private"` and `from_user.id` in the allow-list. Fix the shared fake first, then the three local ones.

### Pitfall 4: CRLF everywhere
Every file to edit is CRLF in the working tree: `telegram_callbacks.py` (1016/1016 lines contain `\r`), `telegram_notify.py`, `shadow_confirm.py`, `shadow.py`, `persistence/approvals.py`, `runtime.py`, `runtime_config.py`, `docs/integration/TELEGRAM.md`, `docs/GLOSSARY.md`, `docs/DOC_STATUS.md`, `docs/data/DATA_MODEL.md`, `.env.example`, `deploy/soak.env.example`, `tests/test_phase21_gate.py`. `.gitattributes` sets `deploy/** text eol=lf` yet the soak example reports CR in the working tree. Edit bytes-aware; after each edit check `git diff --stat` (a whole-file diff means the line endings were rewritten) and `grep -c $'\r'`.

### Pitfall 5: Decision-alignment gate on docs
Changing `docs/GLOSSARY.md`, `docs/integration/TELEGRAM.md`, `docs/data/DATA_MODEL.md` or adding a DECISIONS row requires a `docs/DOC_STATUS.md` index line and `uv run python scripts/verify_decision_alignment.py all`. `scripts/decision_alignment/ops_risk.py:171,316` pin "07:00 Asia/Ho_Chi_Minh" and `Asia/Ho_Chi_Minh` strings in `RISK_MANAGEMENT.md` - do not touch those docs' time wording. AGENTS.md is gated (AU-01..AU-06) and `tests/test_agents_md.py` caps its length: this phase should not edit it.

### Pitfall 6: Keyboard removal semantics unverified
Neither the PTB 22.8 docstrings nor a web search settled whether omitting `reply_markup` on `edit_message_text`, or passing `InlineKeyboardMarkup([])`, removes the keyboard on the live Bot API. `edit_text` passes `reply_markup=keyboard` straight through, and `keyboard=None` is PTB's default (`telegram_notify.py:378-393`). **Do not rely on memory.** Design: the removal helper sends text + an explicit empty `InlineKeyboardMarkup([])`; unit tests assert what the fake bot received; the stale-tap refusal (state-based, not UI-based) is the real guarantee (D-06); a live check by the owner is registered as NOT_REHEARSED for Phase 24/25. If `InlineKeyboardMarkup([])` is rejected by PTB or the API, fall back to a separate `edit_message_reply_markup` call (documented in PTB 22.8 docs: Context7 `/websites/python-telegram-bot_en_stable`, "Bot.edit_message_reply_markup"). Telegram's "message is not modified" arrives as `BadRequest` and is already classified `MESSAGE_NOT_MODIFIED`.

### Pitfall 7: Stale-tap on a card that is the same message
APPROVE edits the very message that carried APPROVE/SKIP into the confirm card (new CNF/CXL buttons). A later APR/SKP tap on it cannot happen (buttons replaced), but a tap on an OLD copy (client cache, forwarded) can. The stale-tap refusal must key on stored state (`status != PENDING` or an existing confirm entry), not on message ids, and must not re-edit a decided message back (`deliver_confirm_card(replay=True)` re-edits the card on a repeated APPROVE press today, `shadow_confirm.py:1489-1501`; keep that for a PENDING confirm only).

### Pitfall 8: Restart loses the confirm context
Raw confirm tokens and `ShadowApprovalBook._plans`/`_contexts` are memory-only; after a restart `plan_context(short_id)` returns None and a CNF tap is `NO_CONFIRM_CONTEXT`; `expire_on_restart` journals `RUNTIME_RESTART`. Keep this in DEMO/LIVE and document it (D-04).

### Pitfall 9: Money renderer silently rounding
`format_approve` already uses `format(approved_quantity, 'f')`; copy that, never `quantize`. SHADOW's `_plain` strips trailing zeros (different style); DEMO/LIVE money lines must use one declared style and a golden test.

## Code Examples

```python
# Source: src/approval/replay.py:240-245 [VERIFIED] - where the actor joins the transition
new_approval = replace(
    approval,
    result=new_result,
    status=new_result,
    acted_at_utc=effective_now,
)   # add: actor_id=<str(from_user_id)>  (Callback or resolve_callback param)
```

```python
# Source: src/persistence/approvals.py:245-249 [VERIFIED] - what _decide writes today
.values(
    result=approval.result.value,
    status=approval.status.value,
    acted_at_utc=approval.acted_at_utc,
)   # add: actor_id=approval.actor_id
```

```python
# Source: src/paper/shadow_confirm.py:1077 [VERIFIED] -> P16R-02 target shape
self._deferred_confirmed.append((entry.approval, entry.plan, confirmed_at_utc))
# _in_section: drained = list(self._deferred_confirmed); self._deferred_confirmed.clear()
# after the lock: for item in drained: self._on_confirmed(*item)
```

```python
# Pure user/private gate (new). Fail closed: any missing piece refuses.
def authorized_user_gate(*, from_user_id: int | None, chat_type: str | None,
                         allowed_user_ids: frozenset[int]) -> str | None:
    """None = allowed; else a plain reason code (GLOSSARY 9.3)."""
    if from_user_id is None or isinstance(from_user_id, bool):
        return "USER_ID_UNAVAILABLE"
    if chat_type != "private":            # telegram.constants.ChatType.PRIVATE == "private"
        return "CHAT_NOT_PRIVATE"
    if from_user_id not in allowed_user_ids:
        return "USER_NOT_AUTHORIZED"
    return None
```
`[VERIFIED: .venv/Lib/site-packages/telegram/_chat.py:140]` `PRIVATE: Final[str] = constants.ChatType.PRIVATE`. `REASON_USER_ID_UNAVAILABLE` already exists as a constant in `shadow_confirm.py:111` with the same text; reuse the string, not the module, from the shared constants file.

```python
# Application error handler (new). PTB 22.8 signature [VERIFIED: _application.py:1794-1824]
async def _on_error(update: object | None, context) -> None:
    log.error("telegram.handler_error: %s", type(context.error).__name__)  # class name only
    # journal with correlation_id if the update carries a callback query id; answer neutrally
app.add_error_handler(_on_error)
```
Do not log `str(context.error)`: a PTB `InvalidToken`/network error text can contain the bot token URL (see `classify_telegram_error` docstring: "never message text").

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `RetryAfter.retry_after` is `int` | `int | timedelta` (reading as int deprecated) | PTB v22.2 | already handled: `_whole_seconds` + `warnings.catch_warnings` in `classify_telegram_error` `[VERIFIED: error.py RetryAfter, telegram_notify.py:340-346]` |
| One keyboard per message | One row with APPROVE + SKIP | Phase 16 plan 16-04 | already in `build_shadow_decision_keyboard`; DEMO/LIVE reuse |
| APPROVE places | APPROVE edits to a card, CONFIRM places | D041 | SHADOW has it; DEMO/LIVE get it via the shared core |

**Deprecated/outdated:** the `Display: Asia/Ho_Chi_Minh (UTC internally)` line of `format_approve` (D-14); `build_simulate_keyboard` inert labels (stay, not sent).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The Telegram Bot API removes an inline keyboard when `editMessageText` is sent without `reply_markup`, and/or accepts `reply_markup` with an empty `inline_keyboard` array | Pitfall 6 | Keyboard stays visible; mitigated by state-based stale-tap refusal and by the fallback `edit_message_reply_markup` call; owner live check needed |
| A2 | The exact text of the expired-callback error is "Query is too old ..." and it surfaces as `telegram.error.BadRequest` | Seam 1 / D-08 | Low: `answer_callback_safely` swallows ALL exceptions, so the text is not relied on; the observed live error is recorded in ROADMAP Phase 23 criterion 5 (project evidence, not the API doc) |
| A3 | A 429 on `editMessageText` arrives as `telegram.error.RetryAfter` with seconds | D-07 | Low: `classify_telegram_error` and `deliver_confirm_card` already do this and are tested with real `telegram.error` classes (`FakeBot.queue_error`) |
| A4 | An EXPIRED sibling plus one later decided row is benign (both tokens die with the process) | Seam 3 | Medium: needs the O-2 owner decision recorded in DECISIONS/DATA_MODEL |
| A5 | `realized_risk` after quantization equals `rounded x (sl_distance + modeled_costs_per_unit)` so gross SL loss = `qty x sl_distance` | Seam 7 | Low: stated in `quantization.py` docstring (read) and `gating.py:177-178`; builder test recomputes independently from fixtures |
| A6 | Next free DECISIONS number is D088 | Docs | Low: last row seen is D087 (`docs/DECISIONS.md`); re-check at writing time |
| A7 | SHADOW alerts should not get the money block in this phase (byte-identical SHADOW, no exchange leverage in SHADOW) | Open Question 1 | Medium: criterion 2 says "every SIMULATE/APPROVE message"; the owner must say whether SHADOW shows paper money (config leverage 5, `initial_equity`) |

## Open Questions

1. **Does SHADOW get the money block?**
   - Known: criterion 2 and D-14 say every SIMULATE/APPROVE message; D-09 says SHADOW stays byte-identical; SHADOW has no verified leverage, equity is `initial_equity` with no timestamp.
   - Recommendation: build the money builder mode-agnostic with `leverage_source` and `equity_source` labels (`PAPER_CONFIG`/`ACCOUNT`), keep SHADOW text unchanged in this phase, and list "SHADOW money block" as an owner item. Planner must not silently change SHADOW goldens.
2. **Where does the "equity source" label come from?** No field exists; propose constants in the money module (`"ACCOUNT_LIVE:min(totalWalletBalance,totalMarginBalance)"`, `"PAPER_CONFIG:initial_equity"`) and show the observed-at timestamp in UTC.
3. **Async fresh inputs at CONFIRM** (Seam 4): sync core vs async exchange reads; planner chooses pre-fetch vs thread; Phase 24 completes it.
4. **`RECONCILIATION_REQUIRED` is not an `ALERT_EVENTS` member** but D-14 lists it; clarify whether it is only an outcome shown on the card/G4-032 reply (recommended) or a new alert event (Phase 20 contract change).
5. **Demo rehearsal script**: update to one-message keyboard + `authorized_user_ids`, or declare out of scope.
6. **O-2** needs the owner decision before the 0014 migration merges (CONTEXT already says so); the plan should make 0014 the last task of its wave and gate it on the DECISIONS row.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all Python commands | yes | 0.12.17 | - |
| Project Python | `uv run` | yes (via uv, 3.13 per project; the bare `python` on PATH is 3.14.3, which AGENTS.md forbids using directly) | - | always `uv run` |
| python-telegram-bot | adapters | yes | 22.8 (uv.lock) | - |
| Docker | `-m docker` tests | client present | 29.8.0 (daemon state not probed) | docker-marked tests are outside this phase |
| PostgreSQL for `*_pg.py` | G4-042, actor_id, money column | `TEST_DATABASE_URL` is set in this shell; server not probed (`pg_isready` not installed) | - | without it the `*_pg.py` files silently skip; use `TRADING_CI_STRICT=1` to see skips as failures |
| Telegram network / second account | G2-014 live check | not used | - | owner-run (D-17) |

**Missing dependencies with no fallback:** none for the plan. **The live Telegram checks (keyboard removal, group/second-account refusal, "Query is too old") are owner-run only.**

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`asyncio_mode = "auto"`, `pyproject.toml:49`), pytest-xdist in dev extra |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/test_paper_shadow_confirm.py tests/test_paper_shadow_buttons.py tests/test_paper_shadow_messages.py tests/test_paper_shadow_telegram_failures.py tests/test_approval_message.py tests/test_alerts.py -x -q` |
| Full suite command | `uv run pytest -m "not docker" -n 4` (about 9-10 min; the orchestrator runs it once per phase; recorded gate is sequential with `TEST_DATABASE_URL`) |
| Lint/type | `uv run ruff check && uv run ruff format --check`; `uv run mypy src`; `uv run python scripts/verify_decision_alignment.py all` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| APRV-02 / D-01 | user not on list, no `from_user`, group/supergroup/channel chat refused before lookup, journaled, no state change | unit (pure gate + `on_callback` with fake update) | `uv run pytest tests/test_telegram_authorization.py -x` | NEW (Wave 0) |
| APRV-02 / D-03 | `actor_id` = user id on APPROVE and SKIP, kept on replay, persisted by `_decide` | unit + PG | `uv run pytest tests/test_persistence_approvals_pg.py tests/test_paper_shadow_buttons.py -x` | exists; extend |
| PAPER-02 / D-05 | SKIP press records `SKIPPED` (not SIMULATE_RECORDED); one keyboard has APR and SKP | unit | `uv run pytest tests/test_telegram_decided_message.py -x` | NEW |
| D-06 | decided message edited with empty keyboard in the same edit; stale tap refused; failed removal journaled, decision stands | unit with FakeBot | same file | NEW |
| D-07 | RetryAfter honored, bounded by `NOTIFY_MAX_ATTEMPTS`, no retry of placement | unit | `uv run pytest tests/test_paper_shadow_telegram_failures.py tests/test_telegram_decided_message.py -x` | exists; extend |
| D-08 | error handler registered (assert via a fake app/`build_application` is NOT called; test the handler function directly); "Query is too old" does not stop the press | unit | `uv run pytest tests/test_telegram_error_handler.py -x` | NEW |
| D-09 / D-16 | SHADOW byte-identical after extraction; two adoptions in one sweep call `on_confirmed` twice, in order | unit | `uv run pytest tests/test_paper_shadow_confirm.py tests/test_paper_shadow_isolation.py tests/test_paper_shadow_lock_order.py tests/test_confirm_core.py -x` | exists + NEW |
| D-10 | DEMO/LIVE profile: double tap, replayed CONFIRM, after TTL, other user, after plan expiry, price crossed SL (injected recheck returns `MARK_PRICE_CROSSED_STOP`) | unit | `uv run pytest tests/test_confirm_core.py -x` | NEW |
| D-11 / crit 3 | card remaining-validity uses `check_remaining_validity`; unset limit shows `LIMITS_NOT_CONFIGURED` | unit | same | NEW |
| D-12 / G4-032 | `describe_prior_outcome` for ACKED, UNKNOWN, SENT, REJECTED, None | unit | `uv run pytest tests/test_prior_outcome_reply.py -x` | NEW |
| D-13 / crit 2 | money builder: every value from fixtures, independent recomputation in the test; missing field refuses to render/send; golden text | unit + golden | `uv run pytest tests/test_money_at_stake.py tests/test_approval_message.py -x` | NEW + extend |
| D-14 | UTC wording on `format_approve`; SIMULATE shows quantity + money; per-event alert golden texts | unit + golden | `uv run pytest tests/test_alert_wording.py tests/test_alerts.py -x` | NEW; `test_alerts.py` exists |
| D-15 | plain codes listed in GLOSSARY 9.3; `len(RejectionReason) == 21` unchanged | doc gate | `uv run python scripts/verify_decision_alignment.py all` ; `uv run pytest tests/test_domain_enums.py tests/test_phase21_gate.py -x` | exists |
| D-16 / G4-042 | PG: both siblings can reach EXPIRED; a second decided row still refused; `_decide` race query ignores EXPIRED; migration up/down | PG | `uv run pytest tests/test_persistence_constraints_pg.py tests/test_persistence_approvals_pg.py tests/test_persistence_migration_pg.py -x` | exist; extend |
| D-02 | missing/unparsable `TELEGRAM_AUTHORIZED_USER_IDS` => `ConfigNotRatified` names-only; no Telegram configured stays SKIPPED | unit | `uv run pytest tests/test_paper_runtime_env.py tests/test_paper_shadow_runtime.py tests/test_env_example.py -x` | exist; extend |
| Gate | Phase 23 structural invariants (enum still 21, head pin updated, no float, no wall clock, core imports nothing from `src.execution`) | gate | `uv run pytest tests/test_phase23_gate.py -x` | NEW (mirror `test_phase21_gate.py`) |

### Sampling Rate
- **Per task commit:** the quick command for the touched area plus `uv run ruff check <files>`.
- **Per wave merge:** SHADOW set (`tests/test_paper_shadow_*.py`, `tests/test_approval_*.py`, `tests/test_alerts.py`) and, for Wave C, the `*_pg.py` files with `TEST_DATABASE_URL` set.
- **Phase gate:** orchestrator-run full suite `-n 4`; recorded gate sequential and strict (`TRADING_CI_STRICT=1`).

### Wave 0 Gaps
- [ ] `tests/test_telegram_authorization.py`, `tests/test_telegram_decided_message.py`, `tests/test_telegram_error_handler.py`, `tests/test_confirm_core.py`, `tests/test_prior_outcome_reply.py`, `tests/test_money_at_stake.py`, `tests/test_alert_wording.py`, `tests/test_phase23_gate.py`.
- [ ] `tests/shadow_fakes.py`: `make_callback_update` gains `chat_type="private"`; a mode-parametrized `FakeBot` (today `assert_shadow_text` is called on every text); `USER_ID` allow-list constant. Also fix the three local fakes (`test_journal_ids.py:352`, `test_phase8_audit_reviewfix.py:427`, `test_demo_rehearsal_flow.py:650`).
- [ ] Golden-text fixtures for the money block and operator alerts: regenerate with a script, never hand-typed (AGENTS.md). Add `scripts/gen_phase23_fixtures.py` and `tests/fixtures/phase23/` with `DERIVATIONS.md`.
- [ ] Update migration-head pins: `tests/test_phase21_gate.py:247`, `tests/test_phase22_gate.py:383`, `tests/test_persistence_migration_pg.py` (0013/0014 constants).
- [ ] No new framework install.

### SHADOW tests/evidence that pin the extraction (must stay green and unedited unless named)
`tests/test_paper_shadow_confirm.py` (1007 lines, 36 tests), `tests/test_paper_shadow_messages.py`, `tests/test_paper_shadow_buttons.py` (line 130 asserts `actor_id == str(CHAT_ID)`: update intentionally), `tests/test_paper_shadow_telegram_failures.py`, `tests/test_paper_shadow_lock_order.py`, `tests/test_paper_shadow_isolation.py` (import-closure ban on order modules, lines 230-250; full SHADOW approve-then-confirm run at 573-596), `tests/test_paper_shadow_reservations*.py`, `tests/test_paper_shadow_runtime*.py`, `tests/test_paper_shadow_pg.py`, `tests/test_paper_shadow_evidence_export.py` (uses `actor_id` `"tg-user-1"`), `tests/test_paper_approval_delay_measured.py`, `tests/test_paper_test_signal_rehearsal.py`; consumers of the event names: `src/paper/attribution.py:74-76`, `src/paper/rehearsal.py`, `src/paper/shadow_ledger.py`, `scripts/shadow_rehearsal.py`. Phase 16 soak evidence is under `.planning/phases/16-paper-runtime-composition/` (not read in detail; reading it is a planner task before touching event names).

## Security Domain

`security_enforcement` is enabled (config.json `workflow.security_enforcement: true`, ASVS level 1, block on high).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Telegram user-id allow-list from env (D-01/D-02); no tokens in callback data |
| V3 Session Management | partial | one-time approval token + separate in-memory confirm token with TTL (existing) |
| V4 Access Control | yes | allow-list + private chat + chat id, each failing independently; fail closed on missing fields |
| V5 Input Validation | yes | strict `parse_callback_data` (existing); env list parsing: ints only, reject bool/empty/duplicates-with-garbage |
| V6 Cryptography | yes (no new) | `src/approval/tokens.py` only; never hand-roll |
| V7 Error handling/logging | yes | error handler logs exception CLASS NAME only; `src/ops/redaction.py` for any text with env values |
| V8 Data protection | yes | allow-list ids not logged in full; journal stores the pressing actor's id only |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Leaked/forwarded `callback_data` pressed by someone else (F-127) | Spoofing / Elevation | user-id allow-list + private chat + token hash bound to plan hash + expiry; confirm token bound to approving user id |
| Press from a group where the bot is a member (F-508/F-707) | Spoofing | `chat.type == "private"`; group ids are negative so the chat-id gate would also fail |
| Replay / double tap / redelivery | Tampering / Repudiation | replay-to-existing, `correlated_event_id` journal ids, single-use confirm token |
| Notification failure leading to an auto-approve | Elevation | none exists; keep test that a send failure leaves the approval PENDING/expired, never APPROVED |
| Stale card confirm after price crossed SL | Tampering | injected pre-placement recheck at CONFIRM; missing mark = refusal |
| Token/secret in exception text or log | Information disclosure | class-name-only logging (existing pattern, `B2-WR-08`), error handler must follow it |
| Order re-send after an ambiguous result | Tampering | never retry placement (Q5, D080); only messages are retried |
| Allow-list "allow all" through an empty/default | Elevation | required parameter, no default; env missing/unparsable refuses start |

## Plan shape suggested to the planner (not binding)

- **Wave 1 (parallel, no persistence):** (1a) user/private gate + stale-tap + keyboard removal + RetryAfter edit helper + error handler + required `authorized_user_ids` plumbing + fakes update; (1b) operator-alert wording formatters (`src/ops/alert_wording.py`) + goldens; (1c) docs skeleton for TELEGRAM.md trust model (D-04) and GLOSSARY 9.3 rows.
- **Wave 2:** extract `confirm_core` + P16R-02 list fix + DEMO/LIVE profiles; SHADOW tests unchanged and green; `describe_prior_outcome`.
- **Wave 3 (PG):** `actor_id` write in `_decide` + resolve_callback actor; money carrier column migration 0013 + store read/write; G4-042 migration 0014 + `_decide` race query fix; update three head pins.
- **Wave 4:** `money_at_stake` builder + DEMO/LIVE card and APPROVE/SIMULATE renderers + `format_approve` UTC/quantity changes + golden fixtures script; `TELEGRAM_AUTHORIZED_USER_IDS` in runtime/config/env examples; DATA_MODEL/DECISIONS/DOC_STATUS; `tests/test_phase23_gate.py`; decision-alignment run.

## Sources

### Primary (HIGH confidence)
- Repository code read in full this session: `src/adapters/telegram_callbacks.py`, `src/adapters/telegram_notify.py`, `src/paper/shadow_confirm.py`, `src/paper/shadow.py` (1-620, 965-1059), `src/approval/replay.py`, `src/approval/binding.py`, `src/domain/approval.py`, `src/persistence/approvals.py` (195-315), `src/execution/pre_placement.py` (1-60, 101-172, 254-276, 466-523), `src/execution/constraint_snapshot.py` (100-290), `src/risk/types.py`, `src/risk/sizing.py`, `src/risk/gating.py` (125-210), `src/risk/margin_check.py` (145-196), `src/risk/cost_rates.py`, `src/risk/live_equity.py`, `src/ops/alerts.py` (85-250, 600-672), `src/db/models.py` (330-422), `src/db/alembic/versions/0006*.py`, `0012*.py`, `0004*.py` (index), `tests/shadow_fakes.py`, `tests/test_phase21_gate.py`.
- `uv.lock` (python-telegram-bot 22.8); installed PTB source `.venv/Lib/site-packages/telegram/` (`_chat.py`, `error.py`, `_bot.py`, `ext/_application.py`, `_callbackquery.py`).
- Context7 `/websites/python-telegram-bot_en_stable` (edit_message_reply_markup, CallbackQuery shortcuts).

### Secondary (MEDIUM confidence)
- `.planning/ROADMAP.md` Phase 23 section (live Telegram test finding of 2026-10-04: `BadRequest: Query is too old`), `17-REVIEW.md` IN-04 (G4-042), `docs/GLOSSARY.md` 9.1-9.3, `docs/DECISIONS.md` D041/D078/D080/D085-D087 rows (titles only).

### Tertiary (LOW confidence, not authoritative)
- Web search on `editMessageText` and empty keyboards returned no source that settles it (tagged A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - nothing new; PTB 22.8 verified in `uv.lock`.
- Architecture / seams: HIGH - every file opened; line numbers quoted.
- Money carrier design: MEDIUM - the inputs are verified, the carrier shape is a recommendation, and the SHADOW question is open.
- Telegram live behaviours (keyboard removal): LOW-MEDIUM - unverified, mitigated by design.
- Pitfalls: HIGH - pins found by grep and Read.

**Research date:** 2026-10-25
**Valid until:** about 30 days; re-check the `RejectionReason` pins, migration head and `ALERT_EVENTS` if other phases land first (Phases 24+ touch the same files).
