---
phase: 16-paper-runtime-composition
plan: 04
subsystem: paper / shadow approval / telegram adapter
tags: [shadow, telegram, approval, apr-skp-buttons, retry-after, message-composer, fail-closed]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plans 16-01 to 16-03 (no code dependency); existing dispatch_callback, on_callback, src.approval replay/binding, notify_simulate retry constants"
provides:
  - "src/paper/shadow.py: Mode, SHADOW_LABEL, ShadowMessageKind, ShadowDecisionOutcome, format_time_pair, render_shadow_message (the one composer), format_shadow_alert, ShadowStores port, ShadowApprovalBook (issue, resolve, dispatch, take_last_decision), send_shadow_alert, make_shadow_reply_fn, invalidate_pending_on_restart"
  - "src/adapters/telegram_notify.py: build_shadow_decision_keyboard, TelegramFailureKind, TelegramFailure, TelegramSendError, classify_telegram_error, TelegramTextBot, send_text, edit_text (the only PTB-aware wrappers)"
  - "tests/shadow_fakes.py: InMemoryShadowStores (parent rows, one decision per plan), FakeBot (asserts label, mode and both zones on every text), RecordingSleep, make_callback_update, signal/plan fixtures"
affects: [16-11 confirm kinds and edit_text reuse, 16-31 runtime composition (wires the PG stores, adds list_pending_approvals), 16-35, 16-38 isolation closure, 16-39, 16-40 real taps, 16-17 SOURCES entry for the Telegram error classification]

actuals:
  tokens: 22900
  tasks: 3
  commits: 4
plan_head_before: da0a576af03c1edaa3ff91490c9381a1a17d64f6
plan_head_after: fa2d0c26dc6ba2317b76f45b2b4bc4c60cbc6ab4
commits: 4

tech-stack:
  added: []
  patterns:
    - "One composer for all SHADOW text; the fake bot asserts label, mode and both time zones on every call"
    - "Telegram failures classified once in the adapter; src/paper never sees a python-telegram-bot class"
    - "notify_simulate tenacity pattern reused with an injectable sleep, a retry_after-aware wait and a stop that never waits past the budget"
    - "Two PENDING approval rows per plan (APPROVE and SKIP_USER) sharing one short id, token chosen per button by the book's dispatch wrapper"

key-files:
  created:
    - src/paper/shadow.py
    - tests/shadow_fakes.py
    - tests/test_paper_shadow_messages.py
    - tests/test_paper_shadow_buttons.py
  modified:
    - src/adapters/telegram_notify.py

key-decisions:
  - "Two approval rows per plan: dispatch_callback/resolve_callback reject a button whose action differs from the stored row (CR-01), and on_callback gives the resolver only the short id, so APPROVE and SKIP_USER are separate PENDING rows with separate tokens; ShadowApprovalBook.dispatch picks the token by button kind. resolve(short_id) returns the APPROVE context plus a skip_raw_token key"
  - "On restart the sweep decides EXPIRED at most one approval per plan, because PostgreSQL allows one decided approval per plan (uq_approvals_one_decided_per_plan); the sibling stays PENDING with a lost token and is reported in RestartReport.left_pending. Deterministic tokens that survive a restart were not taken (needs its own decision)"
  - "actor_id on a decision is str(callback_chat_id): dispatch_callback carries no user id. User-id authorization is Phase 23 (stated in the module docstring)"
  - "A failed send is journaled (SHADOW_ALERT_FAILED with kind, retry_after_seconds and a labelled notice_text) and returned in ShadowSendOutcome; no further Telegram text is sent after a failure"
  - "Retry policy: RATE_LIMITED, TRANSIENT and UNKNOWN are retried inside the existing NOTIFY_* budget; REJECTED, MESSAGE_NOT_MODIFIED and ValueError/KeyError/TypeError fail at once"

patterns-established:
  - "Any later SHADOW text (plan 16-11 confirm card) must be a new ShadowMessageKind rendered by render_shadow_message; test_the_catalogue_names_every_message_kind_and_every_outcome fails until it has a catalogue row"

requirements-completed: [PAPER-02]

coverage:
  - id: D1
    description: "A SHADOW alert is labelled 'SHADOW — no real order', shows mode SHADOW and the detected, expiry and send times in UTC and Asia/Ho_Chi_Minh, and is backed by a signal row, plan row, two PENDING approvals and a short-id mapping written parents first with the journal row committed before the send; the keyboard has exactly the APR: and SKP: buttons for one short id"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_messages.py#test_alert_text_carries_label_mode_and_both_time_zones"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_messages.py#test_send_shadow_alert_writes_parents_journal_then_sends_two_live_buttons"
        status: pass
    human_judgment: false
  - id: D2
    description: "An APR: press through the existing dispatch_callback reaches APPROVED with requested_at_utc, acted_at_utc and actor recorded; an SKP: press reaches SKIPPED with SKIP_USER; a replay returns the existing decision with one write; SKIP after APPROVE cannot flip the decision"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_messages.py#test_approve_callback_moves_approval_to_approved_with_timestamps"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_messages.py#test_the_resolve_context_works_with_the_stock_dispatch_callback"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_skp_callback_skips_with_action_and_timestamp"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_replayed_approve_returns_the_existing_decision_without_a_second_write"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_skip_after_approve_cannot_flip_the_decision"
        status: pass
    human_judgment: false
  - id: D3
    description: "An APPROVE at or after the TradePlan expiry is rejected APPROVAL_EXPIRED, journaled (CALLBACK_REJECTED and APPROVAL_EXPIRED events) and never revives; one second before expiry is still approvable (REV-12, no new TTL)"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_approve_at_or_after_the_plan_expiry_is_journaled_and_never_revives"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_one_second_before_expiry_is_still_approvable"
        status: pass
    human_judgment: false
  - id: D4
    description: "A send failure after the bounded retries, a refusal and a non-Telegram exception leave every approval PENDING, are journaled with their classified kind, and approve nothing"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_send_failure_after_bounded_retries_leaves_pending_and_is_journaled"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_a_non_telegram_send_exception_is_retried_then_journaled_as_unknown"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_a_rejected_send_is_not_retried"
        status: pass
    human_judgment: false
  - id: D5
    description: "A Telegram 429 is honoured inside the existing retry budget: one retry no earlier than retry_after, no retry and no sleep when retry_after exceeds the budget; exhaustion is journaled as RATE_LIMITED with the retry_after seconds and a labelled notice"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_retry_after_is_honoured_with_exactly_one_retry"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_retry_after_is_honoured_when_it_fits_the_budget"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_retry_after_beyond_the_budget_stops_at_once_and_approves_nothing"
        status: pass
    human_judgment: false
  - id: D6
    description: "Telegram errors are classified once in the adapter (RATE_LIMITED with whole seconds from int or timedelta, MESSAGE_NOT_MODIFIED, TRANSIENT, REJECTED, UNKNOWN), the detail holds the class name only, send_text and edit_text convert them, and src/paper/shadow.py imports nothing from telegram or src.execution and never references the inert SIMULATE keyboard"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_classification_table"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_send_and_edit_wrappers_convert_telegram_errors"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_shadow_module_imports_no_telegram_and_no_execution"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_shadow_module_never_references_the_inert_simulate_keyboard"
        status: pass
    human_judgment: false
  - id: D7
    description: "Every SHADOW text (alert, APPROVED, SKIPPED, REPLAYED, expired and other rejections, unauthorized chat, send-failure notice) carries the exact label, the mode and every time in both zones; the real on_callback entry sends exactly one such reply per press; only Mode.SHADOW is constructible"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_messages.py#test_every_message_kind_carries_label_mode_and_both_time_zones"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_messages.py#test_the_catalogue_names_every_message_kind_and_every_outcome"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_every_outcome_reply_is_one_labelled_shadow_message"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_demo_and_live_cannot_reach_the_alert_path"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_messages.py#test_the_fake_bot_guard_rejects_unlabelled_or_single_zone_text"
        status: pass
    human_judgment: false
  - id: D8
    description: "Pending approvals are expired on restart with reason RUNTIME_RESTART because raw tokens do not survive it; a later callback finds no binding context and is rejected; the sweep is idempotent"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_buttons.py#test_restart_expires_pending_approvals_and_later_callbacks_are_rejected"
        status: pass
    human_judgment: false
  - id: D9
    description: "Real Telegram delivery, real button taps and the live Bot API error texts behind the classification (fake-bot evidence never closes PAPER-02, SC9)"
    requirement: PAPER-02
    verification: []
    human_judgment: true
    rationale: "Needs a real bot and operator taps (plan 16-40) and a live check of the error wording, recorded in docs/SOURCES.md by plan 16-17; nothing here touches the network"

duration: 15min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 04: SHADOW approval front half Summary

**A TradePlan becomes a labelled SHADOW alert with live APR:/SKP: buttons backed by two PENDING approval rows; an APPROVE tap reaches APPROVED through the existing `dispatch_callback`, expiry, replay, restart and Telegram 429 paths fail closed and are journaled, and every SHADOW text comes from one composer that stamps the label, the mode and both time zones.**

## Performance

- **Duration:** about 15 min (start time not recorded; the pre-work ledger was written at 03:46Z and the last code commit followed at about 03:54Z)
- **Tasks:** 3 (Task 1 tracer, Task 2 auto, Task 3 auto; both TDD tasks have RED and GREEN commits)
- **Files:** 5 (4 created, 1 modified)

## Accomplishments

- Tracer: `send_shadow_alert` writes signal, plan, two PENDING approvals and the short-id mapping (parents first), commits the `SHADOW_ALERT_PENDING` journal row, then sends one message whose keyboard is exactly APPROVE (`APR:<32 hex>`) and SKIP (`SKP:<32 hex>`). The raw one-time tokens live only in `ShadowApprovalBook` memory; a test searches every stored approval, journal payload and sent text for them.
- `ShadowApprovalBook.dispatch` wraps the stock `dispatch_callback`: it chooses the APPROVE or SKIP token per button, stamps `actor_id`, journals `APPROVAL_EXPIRED` with the plan expiry, and records the outcome (APPROVED, SKIPPED, REPLAYED, expired, other) for the reply. `resolve(short_id)` is the `binding_context_resolver`; its context also works unchanged with the stock `dispatch_callback` for APPROVE (tested).
- Message catalogue: `render_shadow_message` is the only builder of SHADOW text (ALERT, DECISION_RESULT with five outcomes, SEND_FAILURE_NOTICE). `format_shadow_alert` still renders the 12 APRV-01 fields through `format_approve`, then replaces its ISO time lines and display note with UTC and Asia/Ho_Chi_Minh pairs. A test enumerates `ShadowMessageKind` and `ShadowDecisionOutcome` and fails when one lacks a row; the fake bot asserts label, mode and both zones (including the UTC+7 offset) on every text and has its own negative controls.
- Telegram 429: the retry reuses the `notify_simulate` constants (3 attempts, 30 s, jittered backoff) with an injectable sleep, a wait of max(backoff, retry_after) capped at the remaining budget, and a stop that fires when retry_after exceeds the remaining budget. Beyond-budget 429 makes one attempt, no sleep, a journaled `RATE_LIMITED` failure with the retry_after seconds and a labelled `notice_text`.
- `classify_telegram_error` lives in `src/adapters/telegram_notify.py` with `TelegramFailureKind`, `TelegramFailure`, `TelegramSendError`, `send_text` and `edit_text`; python-telegram-bot's `BadRequest`/`TimedOut` (subclasses of `NetworkError`) are tested before it, `RetryAfter` accepts int or timedelta, and the failure detail is the class name only. The PTB deprecation warning from reading `retry_after` is suppressed locally.
- `invalidate_pending_on_restart` decides pending approvals EXPIRED with reason `RUNTIME_RESTART` (one per plan, see decisions) and journals each; a fresh book then rejects any press for them.
- Task 3: the contract text (APR:/SKP: only, SIMULATE keyboard never sent by SHADOW code, user-id authorization is Phase 23) is in the `build_shadow_decision_keyboard` and `src/paper/shadow.py` docstrings (written with Task 1). The existing Telegram and approval suites pass unedited and `ruff`/`mypy` are clean.

## RED Evidence

- **Task 1** (`a822d97`): `tests/test_paper_shadow_messages.py` failed at collection with `ModuleNotFoundError: No module named 'src.paper.shadow'`.
- **Task 2** (`abd21c6`): `tests/test_paper_shadow_buttons.py` failed at collection with `ImportError: cannot import name 'TelegramFailureKind' from 'src.adapters.telegram_notify'`. Two guard tests (the fake-bot text guard controls and the no-SIMULATE-keyboard AST check) were added after RED, in the GREEN commit, and are characterisation tests of the plan's intent.

## Task Commits

1. **Task 1 (tracer): labelled alert, live buttons, APPROVE reaches APPROVED** - `a822d97` (test, RED), `faf2c44` (feat, GREEN)
2. **Task 2: SKIP, expiry, replay, send-failure, restart, 429** - `abd21c6` (test, RED), `fa2d0c2` (feat, GREEN)
3. **Task 3: existing suites and contract text** - no commit of its own (the docstrings landed in `faf2c44`; verification only)

**Plan metadata:** committed separately (docs: complete plan).

## Verification

- `.venv/Scripts/python -m pytest tests/test_paper_shadow_messages.py tests/test_paper_shadow_buttons.py -q -p no:cacheprovider`: 55 passed (plan threshold: 14).
- `.venv/Scripts/python -m pytest tests/test_paper_notify.py tests/test_approval_message.py tests/test_approval_replay.py -q -p no:cacheprovider`: all pass, files unedited.
- Also green: `test_phase8_audit_reviewfix`, `test_journal_ids`, `test_demo_rehearsal_flow`, `test_demo_rehearsal_safety`, `test_paper_reviewfix_pins`, `test_paper_start_gate`, `test_domain_no_float`, `test_execution_secret_posture`, `test_analytics_purity`, `test_backtest_purity`, `test_paper_attribution`.
- `ruff check src` plus the new test files, `ruff format --check` and `mypy src` (151 files) are clean. The whole `pytest -m "not docker"` suite was not run in one process (tool limit); targeted suites replace it.
- No file was deleted by any commit. No network, no real Telegram, `.env` not read.

## Decisions Made

See `key-decisions` above. The two that later plans must know: the pair of approval rows per plan (with `resolve` returning the APPROVE context plus `skip_raw_token`, and `ShadowApprovalBook.dispatch` required as the `dispatch` argument of `on_callback`), and the restart sweep leaving the SKIP sibling PENDING because of the one-decided-per-plan index.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] One approval row cannot back both buttons**
- **Found during:** Task 1 design
- **Issue:** the plan describes "a PENDING approval row" behind both APR: and SKP:. `resolve_callback` rejects a press whose action differs from the stored row (CR-01), the token hash is unique per row, and `on_callback` calls the resolver with the short id only, so a single row can never be SKIPPED.
- **Fix:** two PENDING rows (APPROVE, SKIP_USER) per plan with separate tokens; `ShadowApprovalBook.dispatch` selects the token by button kind. Test 3 of Task 1 still feeds the APR: payload and the `resolve` context to the stock `dispatch_callback` and passes.
- **Files modified:** src/paper/shadow.py
- **Commit:** faf2c44

**2. [Rule 1 - Bug] Restart sweep cannot expire both rows of a plan**
- **Found during:** Task 2 design (reading `uq_approvals_one_decided_per_plan`)
- **Issue:** plan Test 5 says every PENDING approval is decided EXPIRED; PostgreSQL allows one decided approval per plan, so the second `save_atomic` would raise `ApprovalAlreadyDecided`.
- **Fix:** the sweep expires one approval per plan and reports the sibling in `RestartReport.left_pending` (journaled as `LEFT_PENDING_SIBLING_DECIDED`). The sibling's raw token is gone with the process, so it cannot be decided. The fake stores reproduce the index so the test exercises the real behaviour. Test 5 asserts one EXPIRED per plan, not two.
- **Files modified:** src/paper/shadow.py, tests/shadow_fakes.py, tests/test_paper_shadow_buttons.py
- **Commit:** fa2d0c2

**3. [Rule 3 - Blocking] `actor_id` cannot be the callback user id**
- **Found during:** Task 1
- **Issue:** `dispatch_callback` and `on_callback` carry only the chat id; plan Test 3 expects "the callback user id".
- **Fix:** `actor_id = str(callback_chat_id)` (equal to the user id in a private chat); user-id authorization stays Phase 23, as the plan says. Changing `telegram_callbacks.py` was outside the plan's file list.
- **Commit:** faf2c44

**4. [Rule 2 - Missing critical] Failure detail must not leak request text**
- **Found during:** Task 2
- **Issue:** chaining the original PTB exception onto `TelegramSendError` would carry its message (an `InvalidToken` message can contain the token) into logs.
- **Fix:** `send_text`/`edit_text` raise with `from None`; the failure detail is the class name only; tests assert a token-like message never reaches the detail or the journal payload.
- **Commit:** fa2d0c2

**Total deviations:** 4 (2 Rule 3, 1 Rule 1, 1 Rule 2). **Impact:** all within the planned files; the interface names the plan lists are all provided. Additions beyond the plan's artifact list: `RestartReport`, `DecisionRecord`, `IssuedApprovals`, `ShadowSendOutcome`, `ModeNotConstructible`, `TelegramTextBot`, and an optional `book` argument on `make_shadow_reply_fn` (needed to tell a replay from a first approval, which the adapter's outcome text cannot).

## Known Stubs

None.

## Threat Flags

None. No new endpoint or auth path; the only new surface is outbound Telegram text through the existing adapter. T-16-08 (authorized chat gate first, constant-time token compare) holds because every press still goes through `dispatch_callback`; T-16-09 (journal-first, deterministic ids, timestamps, actor) and T-16-10 (raw token memory-only, asserted absent from stored rows, journal and texts) are covered by tests; T-16-111 (single composer, guard on every call, catalogue enumeration, retry_after inside the budget) by the message and button suites.

## Notes for later plans

- Plan 16-31 must compose the PG stores into the `ShadowStores` port: `PgTradingEntityStore.insert_signal/insert_trade_plan`, `PgApprovalStore`, `PgJournalStore.record` (as `record_journal`), plus a new `list_pending_approvals()` reader (the PG approval store has none). The `on_callback` wiring must pass `book.resolve` as `binding_context_resolver`, `book.dispatch` as `dispatch` and `make_shadow_reply_fn(..., book=book)` as `reply_text_fn`.
- After a restart a plan's SKIP row can stay PENDING forever (see decisions); a later phase may want a cleanup status or a second pass, which needs a decision.
- Plan 16-17 should record the Telegram error classification (and `RetryAfter` int-or-timedelta behaviour, PTB 22.8) in docs/SOURCES.md as not verified against the live Bot API.
- `src/paper/__init__.py` was not changed; `src.paper.shadow` is imported by module path.

## Self-Check: PASSED

- FOUND: src/paper/shadow.py, src/adapters/telegram_notify.py, tests/shadow_fakes.py, tests/test_paper_shadow_messages.py, tests/test_paper_shadow_buttons.py
- FOUND commits: a822d97, faf2c44, abd21c6, fa2d0c2
