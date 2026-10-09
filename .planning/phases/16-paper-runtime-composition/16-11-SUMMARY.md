---
phase: 16-paper-runtime-composition
plan: 11
subsystem: paper / shadow approval / telegram adapter
tags: [shadow, telegram, confirm, d041, cnf-cxl-buttons, single-use-token, ttl, fail-closed, answer-callback-query]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-04: ShadowApprovalBook, render_shadow_message, ShadowStores port, TelegramFailureKind/send_text/edit_text, tests/shadow_fakes.py"
provides:
  - "src/paper/shadow_confirm.py: CONFIRM_TTL_SECONDS_DEFAULT (60), ConfirmBook (issue, handle_confirm, handle_cancel, expire_due, expire_on_restart, record_issued, abort_delivery, take_last_result), render_confirm_card, deliver_confirm_card, assert_no_stranded_approvals, StrandedApprovals, make_confirm_callbacks, ConfirmStores, event types SHADOW_CONFIRM_ISSUED / SHADOW_CONFIRMED / SHADOW_CONFIRM_CANCELLED / SHADOW_CONFIRM_EXPIRED plus SHADOW_CONFIRM_REJECTED and SHADOW_CONFIRM_NOTICE_FAILED"
  - "src/paper/shadow.py: ShadowMessageKind CONFIRM_CARD / CONFIRM_RESULT / CARD_DELIVERY_FAILED, ConfirmOutcome, ConfirmCardFields, ConfirmRecord, ShadowApprovalBook.plan_context, make_shadow_reply_fn(confirm_book=)"
  - "src/adapters/telegram_callbacks.py: CallbackKind.CONFIRM / CANCEL, CNF:/CXL: parsing, CallbackPress, ConfirmReply, on_callback(confirm_handler, approved_handler, clock), answer_callback_safely"
  - "src/adapters/telegram_notify.py: CNF_PREFIX, CXL_PREFIX, build_confirm_keyboard, edit_to_confirm_card"
  - "tests/test_paper_shadow_confirm.py, tests/test_paper_shadow_pg.py, tests/test_paper_shadow_telegram_failures.py; tests/shadow_fakes.py gains message ids, user ids, answer injection and the two sweep readers"
affects: [16-31 runtime composition (wires on_confirmed to the SHADOW fill driver, adds list_approved_approvals / journal_for_correlation to the PG composition, calls expire_due periodically and expire_on_restart at startup), 16-35 attribution (CARD_DELIVERY_FAILED reason), 16-38 isolation closure (behaviour spy), 16-40 real taps, 16-17 SOURCES (Bot API wording), Phase 23 (user-id authorization, money amounts, keyboard removal)]

actuals:
  tokens: 31900
  tasks: 4
  commits: 5
plan_head_before: 2a8839e4a601a4967252929aed106f17b789d1aa
plan_head_after: 015453e83f75ab02735a5ca3c0076494dfafb38f
commits: 5

tech-stack:
  added: []
  patterns:
    - "Confirm token is an in-memory capability keyed by the alert short id (the callback data carries no secret); PostgreSQL and the journal see only a 16-hex hash prefix"
    - "Terminal confirm state is journaled FIRST, then the in-memory state moves; deterministic correlated ids (one per approval and step) make every replay an idempotent no-op"
    - "Telegram edit retried only for RATE_LIMITED inside the remaining confirm TTL; any other failure goes straight to exactly one fallback send"
    - "One reply_text_fn path for all presses: the confirm book hands its last result to make_shadow_reply_fn, as the approval book does for decisions"

key-files:
  created:
    - src/paper/shadow_confirm.py
    - tests/test_paper_shadow_confirm.py
    - tests/test_paper_shadow_pg.py
    - tests/test_paper_shadow_telegram_failures.py
  modified:
    - src/paper/shadow.py
    - src/adapters/telegram_callbacks.py
    - src/adapters/telegram_notify.py
    - tests/shadow_fakes.py
    - tests/test_paper_shadow_messages.py

key-decisions:
  - "APPROVE confirms nothing: on_callback's approved_handler edits the alert into the card (SHADOW label, symbol, side, quantity, notional and loss at the adverse entry edge, mark price or 'mark price unavailable', plan expiry as UTC + Asia/Ho_Chi_Minh next to remaining seconds, confirm window); CONFIRM / CANCEL are CNF:<short> / CXL:<short> on the same short id"
  - "The confirm is bound to the Telegram user id captured from the APPROVE callback (query.from_user.id) and to the plan hash; a press from another user or chat is journaled SHADOW_CONFIRM_REJECTED and leaves the token usable by its owner; a missing user id at APPROVE expires the confirm at once (USER_ID_UNAVAILABLE); allow-list authorization of user ids stays Phase 23"
  - "Terminal outcomes are exactly one of SHADOW_CONFIRMED, SHADOW_CONFIRM_CANCELLED, SHADOW_CONFIRM_EXPIRED (reason: CONFIRM_TTL_ELAPSED, a RejectionReason value for a gate or re-check refusal at CONFIRM, CARD_DELIVERY_FAILED, RUNTIME_RESTART, USER_ID_UNAVAILABLE); the TTL boundary is inclusive (now >= issued + ttl), as binding.py"
  - "CNF:/CXL: never enter dispatch_callback: on_callback routes them to confirm_handler after the chat gate, dispatch_callback fails closed on them, and _callback_kind_to_action raises (the stock mapping would have read a CNF as a SKIP)"
  - "Card delivery fails closed: edit (a 429 honoured inside the REMAINING confirm TTL, anchor = issue time), exactly one fallback send of the same card on any other failure, then EXPIRED CARD_DELIVERY_FAILED with a best-effort notice; a 429 longer than the remaining window sends nothing at all while Telegram says to wait; 'message is not modified' is success"
  - "answerCallbackQuery is cosmetic: answer_callback_safely calls it once, without text, first, logs only the exception class on failure and never retries or aborts the gates"

patterns-established:
  - "Every confirm-chain text is a ShadowMessageKind rendered by render_shadow_message; test_the_catalogue_covers_every_confirm_message_kind_and_outcome plus the 16-04 catalogue together fail when a kind has no row"
  - "Sweeps are state-based and idempotent (expire_due, expire_on_restart): they act only on APPROVED approvals with no terminal confirm event and no token in memory"

requirements-completed: [PAPER-02]

coverage:
  - id: D1
    description: "APPROVE edits the alert into a SHADOW confirmation card (label, mode, symbol, side, quantity, notional, estimated loss at SL, mark price, plan expiry in both zones with remaining seconds, confirm window) with CNF:/CXL: buttons of the same short id; nothing is confirmed or simulated by APPROVE; the text is exactly the composer's output"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_approve_edits_the_alert_into_a_shadow_confirmation_card"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_the_card_says_when_the_mark_price_is_unavailable"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_parse_accepts_confirm_and_cancel_payloads"
        status: pass
    human_judgment: false
  - id: D2
    description: "The confirm token is separate, single use, bound to the approving user id and plan hash, expires at the configurable 60 s TTL (inclusive boundary); a replayed CONFIRM replays the existing outcome and calls on_confirmed once; a CONFIRM within the TTL journals SHADOW_CONFIRMED with confirm_requested_at_utc and confirmed_at_utc"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_confirm_within_the_ttl_journals_confirmed_with_both_timestamps"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_a_second_confirm_replays_the_existing_outcome"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_a_confirm_from_another_user_is_rejected_and_journaled"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_a_confirm_at_the_ttl_boundary_is_expired_and_nothing_is_simulated"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_the_ttl_is_configurable_through_the_constructor"
        status: pass
    human_judgment: false
  - id: D3
    description: "CANCEL and expiry are journaled and simulate nothing; a cancel after a decision cannot flip it; a restart expires outstanding confirms (RUNTIME_RESTART) and a later press is rejected"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_cancel_is_journaled_and_nothing_is_simulated"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_expire_due_expires_every_outstanding_token_past_the_ttl"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_a_restart_expires_outstanding_confirms_and_rejects_a_later_press"
        status: pass
    human_judgment: false
  - id: D4
    description: "At CONFIRM the binding gate (chat, plan expiry with APPROVAL_EXPIRED, plan hash, version / row identity) and an injected risk re-check re-run before CONFIRMED; a refusal is journaled with its reason; the module imports no exchange adapter and no execution code and its handlers receive no exchange object"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_a_plan_past_its_expiry_is_rejected_at_confirm"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_an_injected_recheck_can_reject_the_confirm_and_its_reason_is_journaled"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_the_confirm_module_imports_no_exchange_adapter_and_no_execution"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_the_confirm_path_receives_no_exchange_object"
        status: pass
    human_judgment: false
  - id: D5
    description: "On the real PgApprovalStore, PgTradingEntityStore and PgJournalStore the APPROVE then CONFIRM chain writes parents first, one decided approval per plan and the confirm rows; replaying every callback writes no new row and raises no JournalConflict; a CONFIRM after a restart is rejected with the RUNTIME_RESTART row present; a CARD_DELIVERY_FAILED expiry replays idempotently"
    requirement: PAPER-02
    verification:
      - kind: integration
        ref: "tests/test_paper_shadow_pg.py#test_alert_approve_confirm_writes_parents_one_decision_and_the_confirm_rows"
        status: pass
      - kind: integration
        ref: "tests/test_paper_shadow_pg.py#test_replaying_every_callback_writes_no_new_row"
        status: pass
      - kind: integration
        ref: "tests/test_paper_shadow_pg.py#test_confirm_after_a_restart_is_rejected_and_the_expiry_row_exists"
        status: pass
      - kind: integration
        ref: "tests/test_paper_shadow_pg.py#test_a_card_delivery_failed_expiry_replays_without_a_new_row"
        status: pass
    human_judgment: false
  - id: D6
    description: "Every confirm-chain text (card, CONFIRMED, CANCELLED, expiry, rejections, delivery-failure notice) is built by the one composer and carries the label, the mode and both time zones; the fake bot asserts it on every call; the catalogue test fails when a ShadowMessageKind has no row; a non-SHADOW mode cannot render"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_every_confirm_message_carries_label_mode_and_both_time_zones"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_the_catalogue_covers_every_confirm_message_kind_and_outcome"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_confirm.py#test_every_reply_of_the_confirm_chain_passes_the_fake_bot_guard"
        status: pass
    human_judgment: false
  - id: D7
    description: "A Telegram failure after APPROVE never leaves an approved plan with neither a card nor a journaled outcome: edit failure then exactly one fallback send; both failing journals EXPIRED CARD_DELIVERY_FAILED with the last failure kind and kills the token; the repair sweep and assert_no_stranded_approvals; not-modified on replay is success; a 429 is honoured inside the remaining TTL; answerCallbackQuery is called once without text and its failure never aborts processing"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_telegram_failures.py#test_a_failed_edit_is_followed_by_exactly_one_fallback_send_of_the_same_card"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_telegram_failures.py#test_when_the_fallback_fails_too_the_confirm_expires_with_card_delivery_failed"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_telegram_failures.py#test_a_crash_between_approved_and_the_card_is_repaired_by_the_sweep"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_telegram_failures.py#test_not_modified_on_a_replayed_approve_is_success_and_issues_nothing_new"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_telegram_failures.py#test_a_rate_limited_edit_waits_retry_after_inside_the_window_and_succeeds"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_telegram_failures.py#test_a_failed_answer_never_stops_the_press_from_going_through_the_gates"
        status: pass
    human_judgment: false
  - id: D8
    description: "Real Telegram delivery of the card, real CONFIRM / CANCEL taps, and the live Bot API wording behind 'message is not modified', the callback validity window and the edit limits (G7, G8 are UNVERIFIED)"
    requirement: PAPER-02
    verification: []
    human_judgment: true
    rationale: "Needs a real bot and operator taps (plan 16-40) and a live check of the error wording recorded in docs/SOURCES.md by plan 16-17; everything here uses the fake bot and nothing touches the network"

duration: 24min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 11: SHADOW CONFIRM step Summary

**D041's two-step flow runs in SHADOW: APPROVE edits the alert into a confirmation card, and only a CONFIRM by the same user within a 60 s single-use TTL is journaled as confirmed (the injected `on_confirmed` is its only side effect); CANCEL, expiry, every refusal and every Telegram failure are journaled, so an approved plan can never sit with no card and no outcome.**

## Performance

- **Duration:** about 24 min (05:31Z to 05:55Z)
- **Tasks:** 4 (Task 1 tracer, Tasks 2 to 4 auto/TDD)
- **Files:** 9 (4 created, 5 modified)

## Accomplishments

- Tracer: `on_callback` gained `approved_handler`, `confirm_handler` and `clock`. An APPROVED press makes the approval layer issue a confirm token and edit the alert into the card (`render_confirm_card` calls `render_shadow_message(CONFIRM_CARD)`); `CNF:` / `CXL:` presses reach `ConfirmBook` after the chat gate and never `dispatch_callback`.
- `ConfirmBook`: the confirm token is a fresh one-time secret held in memory only, keyed by the alert short id, bound to the approving `query.from_user.id`, the plan hash and the issue time. Gate order at CONFIRM: chat, user, TTL (inclusive), plan expiry (REV-12), plan hash and approved-row identity, injected re-check; journal first, then state, then `on_confirmed`.
- Journal contract: ISSUED (delivery mode, message id, issue and expiry time), then exactly one terminal CONFIRMED / CANCELLED / EXPIRED, with REJECTED for refused presses; ids come from `correlated_event_id`, so a redelivered callback writes nothing new (also proven on PostgreSQL).
- Failure handling (Task 4): edit with a 429 honoured inside the remaining TTL, one fallback send, fail-closed EXPIRED `CARD_DELIVERY_FAILED`, best-effort notice, `expire_due` repair sweep, `expire_on_restart`, `assert_no_stranded_approvals`, guarded `answer_callback_safely`.
- PostgreSQL: the chain runs on `PgApprovalStore`, `PgTradingEntityStore` and `PgJournalStore` through a small adapter in the test (the PG approval store has no list readers yet; plan 16-31 adds them to the runtime composition).

## RED Evidence

- **Tasks 1 and 2** (`b94fa72`, one joint RED commit): `tests/test_paper_shadow_confirm.py` failed at collection with `ImportError: cannot import name 'ConfirmCardFields' from 'src.paper.shadow'`.
- **Task 3**: test-only. The tests passed on first run against the Task 1 and 2 code (characterisation of already built behaviour); no RED exists. They ran against real PostgreSQL, not skipped.
- **Task 4** (`674961c`): `tests/test_paper_shadow_telegram_failures.py` failed at collection with `ImportError: cannot import name 'EVENT_SHADOW_CONFIRM_NOTICE_FAILED' from 'src.paper.shadow_confirm'`; the PG module failed to import `assert_no_stranded_approvals` the same way.

## Task Commits

1. **Tasks 1 and 2: confirm card, token binding, TTL, cancel, re-checks** - `b94fa72` (test, RED), `46933a9` (feat, GREEN)
2. **Task 3: PostgreSQL integration** - `05c5ec1` (test)
3. **Task 4: Telegram failure handling** - `674961c` (test, RED), `015453e` (feat, GREEN)

**Plan metadata:** committed separately (docs: complete plan).

## Verification

- `TRADING_CI_STRICT=1` with `TEST_DATABASE_URL` set (local dev PostgreSQL container, disposable `t17_*_test` databases): `tests/test_paper_shadow_telegram_failures.py tests/test_paper_shadow_pg.py tests/test_paper_shadow_confirm.py tests/test_approval_replay.py tests/test_approval_message.py`: 116 passed, none skipped (18 in the failures file, 4 in the PG file).
- `tests/test_paper_shadow_confirm.py tests/test_approval_message.py tests/test_approval_replay.py tests/test_paper_shadow_messages.py`: 118 passed. Also green, files unedited except as listed: the 16-04 suites, `test_paper_notify`, `test_phase8_audit_reviewfix`, `test_journal_ids`, `test_demo_rehearsal_flow`, `test_demo_rehearsal_safety`, `test_callback_redelivery_pg`, `test_approval_replay_pg`, `test_persistence_approvals_pg`, `test_persistence_journal_pg`, `test_domain_no_float`, `test_paper_*` (308 passed, 1 skipped), `test_execution_secret_posture`, `test_analytics_*`.
- `ruff check` (whole repo), `ruff format --check` (459 files), `mypy src` (160 files): clean. The whole `pytest -m "not docker"` suite was not run in one process (tool limit); targeted suites replace it.
- Without `TEST_DATABASE_URL` the PG tests skip locally (checked: 3 skipped before Task 4) and fail under `TRADING_CI_STRICT=1`.
- No network, no real Telegram, `.env` not read. The PG URL was assembled in memory from the dev PostgreSQL container's environment and never printed or stored; only generated `t17_*_test` databases were created and dropped.

## Decisions Made

See `key-decisions` above.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `on_callback` needs more than one hook**
- **Found during:** Task 1 design
- **Issue:** the plan names one optional `confirm_handler`; turning an APPROVED press into the card edit also needs a hook after dispatch (with the dispatch result, user id and message id), and tests need to control the press time.
- **Fix:** `confirm_handler` (CNF/CXL), `approved_handler` (after APPROVED; returns True when it delivered the card, which suppresses the generic reply) and `clock`, all optional with None keeping today's behaviour; `CallbackPress` and `ConfirmReply` carry chat id, authorized chat id, `from_user_id`, `message_id`, press time and correlation id.
- **Files modified:** src/adapters/telegram_callbacks.py
- **Commit:** 46933a9

**2. [Rule 1 - Bug] The stock mapping reads CNF/CXL as a SKIP**
- **Found during:** Task 1 (CallbackKind extension)
- **Issue:** `_callback_kind_to_action` returned SKIP_USER for every kind except APPROVE, so a CONFIRM reaching `dispatch_callback` would have been resolved as a SKIP.
- **Fix:** it raises for CONFIRM / CANCEL and `dispatch_callback` returns a journaled INVALIDATED rejection for them right after the receipt.
- **Commit:** 46933a9

**3. [Rule 3 - Blocking] `render_confirm_card(plan, ...)` also needs the signal**
- **Issue:** `TradePlan` carries no symbol or side.
- **Fix:** the signature is `render_confirm_card(signal, plan, *, mode, mark_price, now_utc, ttl_seconds)`; notional and loss use the adverse edge of the entry zone (LONG `entry_max`, SHORT `entry_min`), the sizing basis of RISK_MANAGEMENT.
- **Commit:** 46933a9

**4. [Rule 3 - Blocking] CNF/CXL replies go through the existing reply path**
- **Fix:** the confirm book keeps the last press result and `make_shadow_reply_fn(confirm_book=...)` renders a CONFIRM_RESULT (same pattern as the approval book), so replies to CNF/CXL pass through `on_callback` and the fake-bot guard exactly like APR/SKP replies.
- **Files modified:** src/paper/shadow.py
- **Commit:** 46933a9

**5. [Rule 2 - Missing critical] Two journal event types beyond the four named**
- **Fix:** `SHADOW_CONFIRM_REJECTED` (a refused press: another user or chat, no confirm context, a press on a dead token; non-terminal) and `SHADOW_CONFIRM_NOTICE_FAILED` (the best-effort notice failed; non-terminal). Terminal outcomes remain the three named ones, so `assert_no_stranded_approvals` counts exactly one of them.
- **Commit:** 46933a9, 015453e

**6. [Rule 1 - Bug] The Decimal-only guard of plan 16-10 flagged `float(` and `0.0`**
- **Found during:** Task 4 verification (`test_domain_no_float` failed on the new module)
- **Fix:** integer milliseconds (`elapsed_ms`) and `timedelta` comparison replace the float arithmetic; no exclusion was added to the guard.
- **Commit:** 015453e

**7. [Rule 3 - Blocking] Files outside the plan's list**
- `tests/shadow_fakes.py` (message ids, user ids, answer injection, two sweep readers on the in-memory stores) and `tests/test_paper_shadow_messages.py` (its catalogue assertion now excludes the three confirm kinds; `test_the_catalogue_covers_every_confirm_message_kind_and_outcome` asserts the union names every `ShadowMessageKind`).

**Interpretation choices where the plan text was ambiguous** (all recorded in the code docstrings): the edit is retried only for a 429 (a network error or a bad request goes straight to the one fallback send, which is the only reading under which Test 1's `NetworkError` case yields exactly one fallback send); the fallback is a single attempt; a 429 whose retry_after exceeds the remaining window skips the fallback and the notice (nothing is sent while Telegram says to wait) and ends as Test 2 with last failure RATE_LIMITED; a press on a dead (EXPIRED) token is journaled as REJECTED reason CONFIRM_ALREADY_EXPIRED.

### TDD ordering

The RED commit for Tasks 1 and 2 is joint. The guarded `answer_callback_safely` was written in the Task 1 GREEN commit, before Task 4's tests; Task 4's Test 6 therefore passed on first run and is a characterisation test. The Task 4 delivery code was drafted before its RED tests, then removed from the Task 1/2 GREEN commit and restored in the Task 4 GREEN commit after the RED commit.

**Total deviations:** 7 (3 Rule 3, 2 Rule 1, 1 Rule 2, 1 file-list extension). **Impact:** all within the plan's intent; the interface names the plan lists are provided.

## Known Stubs

None. The card shows "mark price unavailable" only when the injected provider returns nothing; wiring the real mark-price provider and `on_confirmed` is plan 16-31.

## Threat Flags

None beyond the plan's register. T-16-26 (chat gate first, confirm bound to the approving user id, mismatch rejected and journaled), T-16-27 (single use, deterministic ids, PG replay test), T-16-28 (only side effect is `on_confirmed`; AST test forbids exchange / execution imports; handlers take no exchange object) and T-16-112 (edit then fallback, EXPIRED CARD_DELIVERY_FAILED, sweep, invariant, not-modified as success, answer failure never aborts) are covered by tests.

## Notes for later plans

- Plan 16-31 must pass `approved_handler=callbacks.approved_handler`, `confirm_handler=callbacks.confirm_handler` to `on_callback`, build `make_shadow_reply_fn(..., confirm_book=confirm)`, call `ConfirmBook.expire_on_restart(now)` at startup and `expire_due(now)` periodically (the invariant needs that sweep for confirms nobody pressed), and add `list_approved_approvals()` / `journal_for_correlation()` to its PG composition (the test adapter `PgShadowStores` shows the selects).
- `PgApprovalStore._decide` persists result, status and `acted_at_utc` only, so the `actor_id` stamped by `ShadowApprovalBook` (plan 16-04) is not stored on PostgreSQL; the confirm journal carries `approving_user_id` instead. Whether the approval row should persist the actor is a Phase 17 / 23 question.
- Plan 16-35 can read `reason: CARD_DELIVERY_FAILED` (and CONFIRM_TTL_ELAPSED, RUNTIME_RESTART, USER_ID_UNAVAILABLE) from the `SHADOW_CONFIRM_EXPIRED` payload to attribute a plan as an opportunity.
- Plan 16-17 should record in docs/SOURCES.md that "Message is not modified" matching, the callback validity window and the edit limits (research G7, G8) are not verified against the live Bot API.
- Phase 23 adds user-id authorization, money amounts on the card and keyboard removal; the result messages here are new messages and the buttons of the card stay on the chat (their tokens are dead).

## Self-Check: PASSED

- FOUND: src/paper/shadow_confirm.py, tests/test_paper_shadow_confirm.py, tests/test_paper_shadow_pg.py, tests/test_paper_shadow_telegram_failures.py
- FOUND commits: b94fa72, 46933a9, 05c5ec1, 674961c, 015453e
