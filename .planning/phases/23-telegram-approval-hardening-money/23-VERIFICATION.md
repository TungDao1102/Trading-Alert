---
phase: 23-telegram-approval-hardening-money
verified: 2026-10-27T00:00:00Z
status: human_needed
score: 5/6 must-haves verified
covered_files:
  - ".planning/phases/23-telegram-approval-hardening-money/23-01-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-01-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-02-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-02-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-03-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-03-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-04-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-04-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-05-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-05-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-06-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-06-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-07-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-07-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-08-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-08-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-09-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-09-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-10-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-10-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-11-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-11-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-12-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-12-SUMMARY.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-13-PLAN.md"
  - ".planning/phases/23-telegram-approval-hardening-money/23-13-SUMMARY.md"
  - "docs/integration/TELEGRAM.md"
  - "src/adapters/telegram_callbacks.py"
  - "src/adapters/telegram_notify.py"
  - "src/approval/confirm_core.py"
  - "src/approval/reason_codes.py"
  - "src/approval/replay.py"
  - "src/db/alembic/versions/0013_approval_money.py"
  - "src/db/alembic/versions/0014_decided_excl_expired.py"
  - "src/execution/approval_desk.py"
  - "src/execution/confirm_flow.py"
  - "src/execution/confirm_recheck.py"
  - "src/paper/runtime_config.py"
  - "src/paper/shadow_confirm.py"
  - "src/persistence/approvals.py"
  - "src/risk/money_at_stake.py"
covered_digest: "v3:sha256:a9afb3245999615e7063c5e02c921eab199c37e4af8defcb6ecd301fb91c87a3"
behavior_unverified: 0
overrides_applied: 0
gaps: []
human_verification:
  - test: "Decide whether the SHADOW approval alert must carry the money block (owner question R-1, OPEN in 23-OWNER-CHECKS.md)"
    expected: "Either the owner accepts that SHADOW alerts stay without money (then add an override for ROADMAP criterion 2, see Gaps Summary) or the owner asks for a follow-up plan that stores a money block with SHADOW approvals and renders it in the SHADOW alert"
    why_human: "ROADMAP criterion 2 and the goal say 'every SIMULATE/APPROVE message'. The SHADOW alert is an APPROVE message and is the only approval message a running process sends today; it shows no money. Phase 23 left it unchanged on purpose (orchestrator resolution 1). Whether SHADOW (a no-order-path mode, D040) is in scope of the criterion is a scope decision, not something code can settle"
  - test: "Resolve the time-zone conflict (owner question O-3): docs/DECISIONS.md D025 names Asia/Ho_Chi_Minh the canonical presentation zone, DEMO/LIVE/SIMULATE messages and the confirm card show UTC with an explicit suffix (D-14)"
    expected: "Owner either amends D025 to allow UTC in these messages, or asks for local time in the messages"
    why_human: "AGENTS.md ranks DECISIONS.md above .planning. The code follows CONTEXT D-14 and does not edit D025, so a canonical decision and the shipped text disagree until the owner answers. ROADMAP criterion 5 only demands that the note and the times agree, and they do"
  - test: "A1: on the live Bot API an editMessageText with an empty inline keyboard removes the keyboard (fallback edit_message_reply_markup is in the code)"
    expected: "Buttons disappear from a decided message; if not, the fallback call is tried and the result written down"
    why_human: "Needs a real bot and chat. Registered as an owner-run check for Phase 24/25. NOT a gap: stale taps are refused from stored state whatever the keyboard does"
  - test: "G2-014: a tap on APPROVE from a second Telegram account and from a group chat"
    expected: "USER_NOT_AUTHORIZED / CHAT_NOT_PRIVATE, stored approval unchanged, journal row holds only the presser's id"
    why_human: "Needs a second account and a group. Registered as owner-run, NOT_REHEARSED. Proven with fakes in tests/test_telegram_authorization.py"
  - test: "A2: exact live text of the Bot API error for an expired callback query"
    expected: "The text contains 'Query is too old' so the debug-level path is taken; any other answer error keeps the warning"
    why_human: "Needs a callback query older than the Telegram limit. Registered as owner-run"
---

# Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts - Verification Report

**Phase Goal:** Only the authorized user in a private chat can approve. SKIP works. An APPROVE tap alone never places an order: a second CONFIRM step on a confirmation card is required (D041). Decided messages cannot be tapped again. Every SIMULATE/APPROVE message shows the money at stake.
**Verified:** 2026-10-27
**Status:** human_needed
**Re-verification:** No, initial verification

## Evidence label

Everything below is [DESIGN]: proven by code reading and executed tests with fakes and a local PostgreSQL. Nothing of Phase 23 is composed into a running process: `ApprovalDesk` and `ConfirmFlow` are constructed only in tests (grep of `src` and `scripts` for `ApprovalDesk(`, `make_confirm_flow`, `ConfirmFlow(` finds only the definitions), `on_confirmed` is a required injected callable that nothing connects to, `build_money_at_stake` has no caller in `src`, and live placement stays disabled. The only Phase 23 code that runs in a live process today is the SHADOW runtime (allow-list, error handler, decided-message keyboard removal, CONFIRM core profile). This matches the docs (`docs/integration/TELEGRAM.md` "Not composed yet", `23-OWNER-CHECKS.md`).

## Goal Achievement

### Observable Truths (ROADMAP success criteria + the honesty rule)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1. `from_user.id` allow-list AND private chat enforced before any lookup; APPROVE/SKIP distinct prefixes so SKIP is recorded as SKIPPED; message edited and keyboard removed after a decision, stale taps refused; RetryAfter honored; error handler / "Query is too old"; token trust model documented | VERIFIED | see "Criterion 1" below |
| 2 | SC2. Messages show quantity, notional, margin at leverage, loss at SL and profit per TP gross/net, equity with source and timestamp, all from the risk pipeline output, never recomputed | UNCERTAIN (WARNING, human decision R-1) | Verified for the DEMO/LIVE request and SIMULATE message; the SHADOW approval alert carries no money block (open owner question R-1). See "Criterion 2" |
| 3 | SC3. Expiry window shown and remaining-validity rule match Phase 19 | VERIFIED | `src/adapters/telegram_notify.py:1036-1049` (card line), `src/execution/confirm_flow.py:203-211` (verdict from the injected placement rule), `src/execution/pre_placement.py:254-276` (`check_remaining_validity` is the rule, `LIMITS_NOT_CONFIGURED` when the owner minimum is unset); tests `test_the_card_names_a_missing_owner_limit_and_never_invents_a_minimum`, `test_the_card_shows_the_gate_verdict_for_a_plan_that_is_too_short_lived` pass |
| 4 | SC4. APPROVE edits into a card; only CONFIRM reaches `on_confirmed`; token single-use, user + plan-hash bound, 60 s TTL; CANCEL/expiry journaled; checks re-run at CONFIRM; criterion matrix tested | VERIFIED | see "Criterion 4" below |
| 5 | SC5. Live-test findings closed: keyboard removed and later taps refused; `actor_id` recorded; CONFIRM step for DEMO/LIVE; error handler and "Query is too old"; UTC note fixed; APPROVE+SKIP in one message | VERIFIED (A1/A2 live behavior registered as owner checks) | see "Criterion 5" below |
| 6 | Honest labels: nothing wired into a running process, live placement disabled, PAPER-02 stated correctly | VERIFIED | see "Honest labels" below |

**Score:** 5/6 truths verified (1 UNCERTAIN routed to the owner, 0 present-but-behavior-unverified, 0 failed).

### Criterion 1 (authorization, SKIP, final messages, trust model)

| Check | Evidence |
|-------|----------|
| Pure gate: user id present, then chat type exactly `private`, then membership in a required non-empty frozenset | `src/adapters/telegram_callbacks.py:265-300` (`_validate_authorized_user_ids`, `authorized_user_gate`); empty set, plain set, bool/str member raise `ValueError` (no allow-all) |
| Runs BEFORE any lookup in the PTB entry | `_answer_press` (`:1182`): chat gate `:1200`, user gate `:1233-1258` return before `CallbackPress` (`:1261`), `confirm_handler` (`:1274`), `binding_context_resolver` (`:1283`) and dispatch with a token. The refusal is built inside `on_callback` itself, so it holds even if an injected dispatcher ignores the new keywords (`test_the_gate_holds_even_when_the_dispatcher_ignores_the_new_keywords`) |
| Same order inside `dispatch_callback` | `:437-464` (gate 2b after the chat gate, before the receipt, mapping and token lookups); journal row records only the presser id, never the list (`_build_user_reject_receipt :788-836`) |
| Allow-list is required at startup, never allow-all | `src/paper/runtime.py:523-531` raises `ConfigNotRatified` when Telegram is configured without it; `src/paper/runtime_config.py:130-147` strict parser; `on_callback :1070` and `build_application :1363` validate it |
| SKIP is recorded, distinct prefixes | `build_decision_keyboard` `telegram_notify.py:225-250` (`APR:` and `SKP:`, one row); `parse_callback_data :186-203` maps `SKP:` to `CallbackKind.SKIP`; `_callback_kind_to_action :140-147` maps it to `SKIP_USER`; `replay.py:262-274` transitions to SKIPPED; the desk issues two PENDING rows with separate tokens `approval_desk.py:386-418`. Tests `test_a_skip_tap_records_skipped_with_the_actor_and_makes_the_message_final`, `test_three_skip_taps_give_one_transition_and_one_final_edit` pass |
| Decider recorded | `replay.py:268-274` `actor_id=actor_id or approval.actor_id`; `telegram_callbacks.py:614-619`; `src/persistence/approvals.py:272` writes it; replay keeps the first actor (`test_an_allowed_press_is_decided_with_the_presser_as_actor_and_replay_keeps_it`) |
| Keyboard removed in the same edit as the final text, fallback to a keyboard-only edit | `telegram_notify.py:580-619` (`finalize_decided_message`, empty `InlineKeyboardMarkup([])`); desk hook `approval_desk.py:830-892`; flow `confirm_flow.py:542-579`; SHADOW `shadow_confirm.py:530,699`, wired in `shadow_runtime.py:497` |
| Stale taps refused from stored state, no state change | `approval_desk.py:646-674` (`_classify`), `:704-706` ("Already decided ... Nothing changed. [ALREADY_DECIDED]"); `DispatchResult.already_decided` derived from the store (`telegram_callbacks.py:699`); tests `test_approve_after_skip_changes_nothing_and_says_already_decided`, `test_a_short_id_lost_in_a_restart_loses_its_keyboard_only` |
| RetryAfter honored, messages only | `call_bounded telegram_notify.py:498-546` (sleep the server value, stop above 30 s cap or the window, 3 attempts, MESSAGE_NOT_MODIFIED is success, REJECTED never retried) |
| Error handler and "Query is too old" | `answer_callback_safely :974-992` (debug for expired query, never blocks the press), `make_application_error_handler :995-1018` (class name and correlation id only), registered in `build_application :1385`, press failures journaled `CALLBACK_HANDLER_FAILED` and answered neutrally `:1117-1179` |
| Token trust model documented (F-127) | `docs/integration/TELEGRAM.md:41-49` and the second gate at `:34-39`; `docs/GLOSSARY.md` 9.3 rows; gate test `tests/test_phase23_gate.py` |

### Criterion 2 (money at stake)

| Check | Evidence |
|-------|----------|
| One builder in the risk layer, from the risk pipeline output | `src/risk/money_at_stake.py:244-342`: quantity, entry and net loss are read from `SizedResult` (`loss_at_stop_net=sized.realized_risk :337`; `realized_risk = rounded x (sl_distance + costs)` in `src/risk/quantization.py:99`), margin is `required_initial_margin`, cost is `per_unit_round_trip_cost`; any missing input raises `MoneyAtStakeUnavailable` (nothing partial). Gross loss, notional and per-TP profit are computed once here because the pipeline produced none of them before; this is the reading recorded in 23-02 and open as owner question Q-TP |
| Stored with the approval, formatted only | `approvals.money_json` (migration `0013_approval_money.py`); `ApprovalDesk.issue approval_desk.py:365-399` stores the same canonical JSON on both rows; `money_for :577-594` re-reads the STORED row |
| Telegram code does no arithmetic | `render_money_block telegram_notify.py:836-860` is `format(value, "f")` and joins only; `require_money_consistent :863-901` refuses a block that disagrees with direction, quantity, stop, leg count, TP price or fraction; an AST test pins "no BinOp in the money renderers" (23-09 SUMMARY) |
| Lines and order (notional, margin with leverage and its source, SL loss gross/net, profit per TP gross/net, equity with source and UTC time) | `telegram_notify.py:851-860`; golden texts generated by `scripts/gen_phase23_fixtures.py`, `uv run pytest tests/test_phase23_fixtures.py` passes |
| DEMO/LIVE request and SIMULATE show it; money is required (missing or mismatching refuses before any write or send) | `format_approval_request :904-963`, `src/paper/notify.py` `format_simulate` (requires `approved_quantity` and `money`); `test_issue_refuses_missing_or_mismatching_money_before_any_write` |
| SHADOW approval alert | NOT shown. `grep money src/paper/shadow.py` finds nothing; `docs/integration/TELEGRAM.md:78` says so; owner question R-1 is OPEN. This is the one open scope item (WARNING, human decision) |
| No caller | `build_money_at_stake` has no caller in `src/`; no running process produces a money block until Phase 24 (declared in the CONTEXT boundary and in the docs) |

### Criterion 4 (two-step confirm), CONFIRM is the only path to `on_confirmed`

| Requirement | Evidence |
|-------------|----------|
| `on_confirmed` is the single seam to placement and is required | `confirm_flow.py:163-164` (ValueError if None), `:182`; `confirm_core.py:945-967` runs it only for entries finished by `_finish_confirm :1109-1135` (appended after `*_CONFIRMED` is journaled); the flow imports nothing that places an order (`test_the_flow_imports_nothing_that_places_an_order`, `tests/test_phase23_gate.py` import bans); no `execute_approved_plan` call exists in `src/` outside `src/execution/manager.py` and docstrings |
| APPROVE alone only records and shows the card | `approved_handler confirm_flow.py:238-287`: edits the request into the card, issues the confirm entry; without a handler the desk answers "APPROVED is recorded; no confirmation card handler is attached, so nothing can be confirmed or placed" (`approval_desk.py:131-135`) |
| CONFIRM needs an issued entry; no entry means refusal | `confirm_core.py:995-1003` -> `_reject_unknown` (`NO_CONFIRM_CONTEXT`), journaled; entry is created only in `issue` after an APPROVED press |
| Bound to the approving user | `confirm_core.py:739-775` (`_press_gate`: chat, then `from_user_id != entry.approving_user_id` gives `USER_MISMATCH`, token stays usable by its owner); `confirm_flow.py:279` binds to `press.from_user_id` |
| Bound to the plan hash, stored APPROVED row, identity | `confirm_core.py:830-853` (`_binding_gate`), `:840` plan expiry inclusive |
| Single use, replay returns the existing outcome | state machine `confirm_core.py:1015-1025`, `_replay :695-724`; hook deferred and called once per CONFIRM (`:373`, `:1134`); P16R-02 list, test `test_two_adoptions_in_one_sweep_reach_the_hook_once_each_in_order` |
| TTL 60 s, inclusive boundary | `CONFIRM_TTL_SECONDS_DEFAULT = 60` (`confirm_core.py:65`), `:1031` |
| Re-check at CONFIRM through the Phase 19 functions, fail closed | `src/execution/confirm_recheck.py:107-126` (`evaluate_pre_placement` then `check_position_mode`, clock rebound to the press instant, single-use snapshot, `CONFIRM_INPUTS_UNAVAILABLE` / `_MISMATCH`); `confirm_core.py:855-869` (a raising re-check is `RECHECK_ERROR`) |
| CANCEL and expiry journaled, place nothing | `confirm_core.py:1179-1229`, `_expire_ttl :726-737`; restart expiry `RUNTIME_RESTART` |
| Card contents | `format_live_confirm_card telegram_notify.py:1006-1051`: mode, symbol, side, quantity, notional, loss at SL, mark price vs entry/SL, remaining validity, confirm window |
| Matrix through `on_callback` | `tests/test_confirm_flow.py`: double-tap (`:412`), redelivered CONFIRM (`:429`), CONFIRM after TTL (`:441`), other listed user (`:461`), unlisted user never reaches the core (`:480`), CONFIRM at plan expiry (`:493`), mark price crossed the stop `MARK_PRICE_CROSSED_STOP` plus unavailable inputs and raising re-check (`:509-544`), CANCEL (`:547`), restart (`:567`), failing hook never called twice (`:610`) |

### Criterion 5 (live-test findings, 2026-10-04)

| Finding | Closed by |
|---------|-----------|
| Decided message keeps its button, later taps answered | Final edit with empty keyboard, stored-state refusal (Criterion 1 rows) |
| `actor_id` empty | `replay.py:273`, `approvals.py:272` |
| APPROVE straight to APPROVED, no CONFIRM (DEMO/LIVE) | `confirm_flow.py` (Criterion 4) |
| No error handler, "Query is too old" | `telegram_callbacks.py:974-1018, 1385` |
| No money amounts, wrong time-zone note | Criterion 2 (DEMO/LIVE/SIMULATE); `format_utc telegram_notify.py:627-637` (`... UTC`), the `Display: Asia/Ho_Chi_Minh` line is gone (SHADOW keeps its UTC + Asia/Ho_Chi_Minh pair, so it is not false there). Conflict with D025 is human item 2 |
| One message carries one button | `build_decision_keyboard`; desk sends one message (`approval_desk.py:502-508`); `scripts/demo_rehearsal.py` updated; the single-button builders are not sent by any production path |

### Honest labels

| Check | Result |
|-------|--------|
| Nothing composed into a running process | Confirmed by grep (see Evidence label). Docs say so: `TELEGRAM.md:112`, `23-OWNER-CHECKS.md` header, every plan SUMMARY labels [DESIGN] |
| Live placement disabled | `src/execution/enablement.py` untouched by the phase (not in the Phase 23 `git diff --name-only` of `src`); `on_confirmed` connected to nothing |
| PAPER-02 | Stated correctly as Pending: `REQUIREMENTS.md:144`, `23-OWNER-CHECKS.md` "Requirement status". Phase 16 (unchecked in ROADMAP line 53) owns the closure rule (ROADMAP line 711). Phase 23 contributes SKIP recorded as SKIPPED with the actor (tests above), G4-042 (D088, migration 0014, PG tests pass under `TRADING_CI_STRICT=1`) and P16R-02. DEMO/LIVE confirm journal events are not read by `src/paper/attribution.py` (owner item Q-ATT, OPEN) |
| APRV-01 / APRV-02 | Stay Complete (Phase 8); Phase 23 hardens them at library level. Not reopened and not over-claimed |

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/adapters/telegram_callbacks.py` | VERIFIED | gate, finalize hook, error handler, press failure path, all wired through `on_callback` / `build_application` |
| `src/adapters/telegram_notify.py` | VERIFIED | keyboards, bounded calls, finalize, money renderers, card and finals |
| `src/approval/confirm_core.py`, `reason_codes.py`, `replay.py` | VERIFIED | shared state machine with SHADOW/DEMO/LIVE profiles; SHADOW tests pass unedited |
| `src/execution/approval_desk.py`, `confirm_flow.py`, `confirm_recheck.py`, `prior_outcome.py` | VERIFIED (library only) | substantive and tested; ORPHANED from any running process by design (Phase 24) |
| `src/risk/money_at_stake.py` | VERIFIED (library only) | no production caller by design |
| `src/db/alembic/versions/0013_approval_money.py`, `0014_decided_excl_expired.py`, `src/persistence/approvals.py` | VERIFIED | PG tests pass strict |
| `src/ops/alert_wording.py`, `src/ops/alerts.py` | VERIFIED | `worded_alert_text(alert) or render_alert_text(alert)` in the Phase 20 sender |
| `docs/integration/TELEGRAM.md`, `GLOSSARY.md` 9.3, `DECISIONS.md` D088, `DATA_MODEL.md` 2.5 | VERIFIED | trust model F-127 present |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `build_application` | `on_callback` allow-list + error handler | `authorized_user_ids` required, `add_error_handler` | WIRED |
| `SHADOW runtime callback_kwargs` | `on_callback` | allow-list, finalize hook (`shadow_runtime.py:482-499`); `runtime.py:523-544` supplies the list | WIRED (running path) |
| `ConfirmFlow.callback_kwargs` | `on_callback` | `approved_handler`, `confirm_handler`, `finalize_message`, desk `resolve`/`dispatch` | WIRED in the library, not started in any process |
| `ConfirmFlow` | placement | `on_confirmed` (required, injected) | NOT CONNECTED by design (Phase 24) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| request / card / finals | money block | stored `approvals.money_json` parsed strictly (`approval_desk.money_for`) | produced by `build_money_at_stake` from `SizedResult` in tests; no production producer yet | FLOWING in tests, producer is Phase 24 |

### Behavioral Spot-Checks (executed in this verification)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 23 suites (auth, core, flow, desk, decided message, error handler, money, gate, fixtures, recheck, prior outcome, wording): 353 tests | `uv run pytest -m "not docker" tests/test_telegram_authorization.py tests/test_confirm_core.py tests/test_confirm_flow.py tests/test_approval_desk.py tests/test_telegram_decided_message.py tests/test_telegram_error_handler.py tests/test_money_at_stake.py tests/test_phase23_gate.py tests/test_phase23_fixtures.py tests/test_confirm_recheck.py tests/test_prior_outcome_reply.py tests/test_alert_wording.py -q` | all passed | PASS |
| SHADOW unchanged + gates + guard tests the 23-OWNER-CHECKS file said fail | `... tests/test_paper_shadow_*.py tests/test_approval_message.py tests/test_paper_notify.py tests/test_alerts.py tests/test_demo_rehearsal_flow.py tests/test_phase21_gate.py tests/test_phase22_gate.py tests/test_no_unratified_defaults.py tests/test_modeled_costs_none_guard.py tests/test_agents_md.py tests/test_domain_no_float.py` | all passed (the two guard tests are green at HEAD; commit `1d62e1cb` fixed them, so the "still fail" text in 23-OWNER-CHECKS.md and 23-VALIDATION.md is stale) | PASS |
| PostgreSQL: approvals, migration chain to 0014, constraints | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_approvals_pg.py tests/test_persistence_migration_pg.py tests/test_persistence_constraints_pg.py -q` | all passed, no skips | PASS |
| Docs/code gate | `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS | PASS |
| Lint, types | `uv run ruff check`, `uv run mypy src` | clean, 263 files | PASS |

### Probe Execution

SKIPPED: the phase declares no probe scripts.

### Requirements Coverage

| Requirement | Source | Status | Evidence |
|-------------|--------|--------|----------|
| APRV-01 | all plans | SATISFIED at library level for DEMO/LIVE/SIMULATE; SHADOW alert has no money block (human item 1) | Criterion 2 |
| APRV-02 | 23-01, 06, 07, 10, 11, 12 | SATISFIED at library level; SHADOW runtime path live | Criteria 1, 4, 5 |
| PAPER-02 | 23-04, 08, 11 | CONTRIBUTED, correctly left Pending (Phase 16 owns closure) | Honest labels |
| ORPHANED requirements | none | `REQUIREMENTS.md` maps no other ID to Phase 23 | |

### Anti-Patterns Found

None blocking. `TBD|FIXME|XXX|TODO|HACK` grep over every source file the phase touched found nothing; no `float(` constructor in the money or confirm modules.

| File | Observation | Severity | Impact |
|------|-------------|----------|--------|
| `src/adapters/telegram_callbacks.py:381` `dispatch_callback(... authorized_user_ids=None)` | The pure dispatcher skips the user gate when the list is omitted (pinned by `test_dispatch_without_an_allow_list_skips_the_user_gate`). Every production path goes through `on_callback`, which always passes it and refuses first | Info | A future direct caller of `dispatch_callback` would bypass the user gate. Phase 24 should only compose through `on_callback` |
| `src/db/alembic/versions/0014_decided_excl_expired.py` docstring | Still says "pending owner decision O-2 ... not to be merged before the answer". The owner answered (D088) | Info | Stale wording only |
| `src/approval/confirm_core.py` / `telegram_notify.py:258-265` | The CNF/CXL callback carries the short id only; the "confirm token" is an in-memory entry keyed by it plus the user and plan-hash binding, not an unguessable value in the callback. This is the Phase 16 design, documented in TELEGRAM.md section 3 | Info | Security rests on the allow-list, private chat and approver binding, as documented |
| `scripts/demo_rehearsal.py` (`far` / `fill` scenarios, `execute_approved_plan` at `:2857`) | Places a Demo order after the approval without a CONFIRM step (owner question R-5, ANSWERED option (c): retire once Phase 24 provides a composed Demo path) | Warning (owner-accepted, Demo only) | These scenarios are not evidence of the two-step flow; labelled so in 23-OWNER-CHECKS.md |
| `23-OWNER-CHECKS.md`, `23-VALIDATION.md` | State that two guard tests "still fail on HEAD"; they pass at HEAD after commit `1d62e1cb` | Info | Stale documentation; correct it in the next doc touch |

Unrelated, already known: `tests/test_phase21_fixtures.py::test_generator_rerun_is_byte_identical` fails on this Windows checkout because of CRLF in recorded Demo captures; no Phase 23 commit touches those files (`git diff --name-only` over the Phase 23 range shows only `tests/test_phase21_gate.py` among Phase 21 names).

### Human Verification Required

See the frontmatter `human_verification` list. Items 1 and 2 are owner decisions that the code cannot settle (R-1, O-3). Items 3 to 5 (A1, G2-014, A2) are owner-run live checks registered in `23-OWNER-CHECKS.md`; they do not gate any success criterion because a stale tap is refused from stored state independent of the keyboard and the gates are proven with fakes.

### Gaps Summary

No code gap blocks the phase goal. One scope question decides between `passed` and a follow-up plan:

**R-1 (SHADOW alert has no money block).** ROADMAP criterion 2 and the goal say "every SIMULATE/APPROVE message". The DEMO/LIVE request, the SIMULATE message and the confirmation card meet it from the stored money block; the SHADOW approval alert (the only approval message a running process sends today) does not, by an orchestrator resolution that was never ratified by the owner. It is classified UNCERTAIN rather than FAILED because SHADOW has no order path (D040), the CONTEXT decision D-13 and the TELEGRAM.md money section are written for the DEMO/LIVE request, and the omission is stated in the docs and registered as OPEN. If the owner accepts the exemption, record it as an override in this file's frontmatter:

```yaml
overrides:
  - must_have: "Every SIMULATE/APPROVE message shows the money at stake (SHADOW alert excluded)"
    reason: "SHADOW is a no-order-path rehearsal mode (D040); the money block is built for DEMO/LIVE requests and SIMULATE"
    accepted_by: "{owner}"
    accepted_at: "{ISO timestamp}"
```

If the owner wants the literal reading, a follow-up plan must add a money block to SHADOW approvals (the SHADOW tests pin byte-identical text, so that is a deliberate pin change) and Phase 24 must supply the producer of the readings.

Everything else in the goal holds at the evidence level the phase claims: authorization before any lookup, SKIP recorded, decided messages final with stale taps refused from stored state, CONFIRM as the only route to the injected `on_confirmed`, and money values read from the stored risk-pipeline output. None of it is live.

---

_Verified: 2026-10-27_
_Verifier: Claude (gsd-verifier)_
