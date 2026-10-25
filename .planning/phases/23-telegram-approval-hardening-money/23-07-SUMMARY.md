---
phase: 23-telegram-approval-hardening-money
plan: 07
subsystem: telegram-adapter
status: complete
tags: [telegram, finalize, keyboard-removal, retry-after, error-handler, already-decided]
requirements-addressed: [APRV-02]
requires: [23-01]
provides:
  - "src/adapters/telegram_notify.py: build_removed_keyboard, EDIT_MAX_ATTEMPTS, RETRY_AFTER_CAP_SECONDS, BoundedOutcome, call_bounded, send_text_bounded, FinalizeOutcome, finalize_decided_message, edit_reply_markup, TelegramTextBot.edit_message_reply_markup"
  - "src/adapters/telegram_callbacks.py: FinalizeHook, finalize_message and error_journal on on_callback / build_application, make_application_error_handler, EVENT_TYPE_CALLBACK_HANDLER_FAILED, DispatchResult.already_decided"
  - "src/approval/replay.py: ApprovalDecidedDifferently(ApprovalRejected) carrying existing"
  - "tests/shadow_fakes.py: FakeBot(text_check=...), FakeBot.for_mode, assert_live_text, edit_message_reply_markup -> markup_edits"
affects: [23-10, 23-11, 23-12, 23-13]
tech-stack:
  added: []
  patterns:
    - "one bounded message helper (RetryAfter honoured inside the paper-notify bound), messages only"
    - "outcome returned, never raised: a failed keyboard removal never rolls back a decision"
    - "already_decided derived from stored state (save callable did not write), not from a local guess"
key-files:
  created:
    - tests/test_telegram_decided_message.py
    - tests/test_telegram_error_handler.py
  modified:
    - src/adapters/telegram_notify.py
    - src/adapters/telegram_callbacks.py
    - src/approval/replay.py
    - tests/shadow_fakes.py
    - tests/test_paper_shadow_telegram_failures.py
key-decisions:
  - "RETRY_AFTER_CAP_SECONDS = 30 and EDIT_MAX_ATTEMPTS = 3 restate src.paper.notify NOTIFY_MAX_DELAY_SECONDS / NOTIFY_MAX_ATTEMPTS (the adapter must not import the paper package); a test pins the equality. No new number."
  - "finalize_decided_message falls back to a keyboard-only edit only after a REJECTED text edit; a rate-limit or transient exhaustion reports done False without a second call."
  - "make_application_error_handler is registered in addition to the SHADOW runtime's own on_telegram_error (PTB keeps both); shadow_runtime.py is not edited."
metrics:
  completed: 2026-10-25
commits: 6
plan_head_before: 766bc2332153f6bdde7d8ab4d0d22027daab61a7
plan_head_after: a7e7d6633946de5f6278216fbc9105ec4faf1fe8
actuals:
  tokens: 21000
  tasks: 3
  commits: 6
---

# Phase 23 Plan 07: Final decided message, bounded edits, error handling Summary

The Telegram adapter can now make any decided message final (final text and no keyboard in one `editMessageText` call, one keyboard-only fallback), recognises a stale tap from stored state, and no longer loses a press to an unhandled exception or an expired query; every default is None, so nothing changes until a composer passes a hook.

## What was built

- **Task 1 (tracer; RED `71e907ff`, GREEN `1772531e`).** `telegram_notify.py`: `build_removed_keyboard()` (an explicit empty `InlineKeyboardMarkup`), `edit_reply_markup`, `call_bounded` (RetryAfter slept inside the cap and the remaining window, no sleep after the last attempt, TRANSIENT retried without a sleep, "message is not modified" is success, a refusal is never retried, ValueError/KeyError/TypeError propagate), `send_text_bounded`, `finalize_decided_message` returning a `FinalizeOutcome` (never raising), and `edit_message_reply_markup` on the `TelegramTextBot` protocol. `telegram_callbacks.py`: `FinalizeHook`, an optional `finalize_message` keyword on `on_callback` and `build_application`, run after the reply of every press past both gates (APR, SKP, CNF, CXL; never for a gate refusal), error logged by class name and correlation id only. `tests/shadow_fakes.py`: `FakeBot(text_check=assert_shadow_text)`, `FakeBot.for_mode("DEMO"/"LIVE")`, `assert_live_text`, `edit_message_reply_markup` into `markup_edits` with its own error queue; the SHADOW recording is unchanged.
- **Task 2 (RED `aa8b5424`, GREEN `1ba3250f`).** `ApprovalDecidedDifferently(ApprovalRejected)` with `existing`, raised by `resolve_callback` in the "decided with a different outcome" branch (same reason code and message). `dispatch_callback` sets `DispatchResult.already_decided` (last field) when the save callable did not write: a replay, a lost race that resolved to the same decision, and a sibling-button tap (ok False, INVALIDATED, journal unchanged, `approval` = stored row). `_render_outcome_text` and the SHADOW texts are not touched.
- **Task 3 (RED `58ea5c49`, GREEN `a7e7d663`).** `make_application_error_handler()` (one line: exception class and `cbq:<id>`, never the text, never raises) registered by `build_application` via `add_error_handler`. `on_callback` catches an exception after the gates: logs, journals `CALLBACK_HANDLER_FAILED` (short id, kind, error class, correlation id) through the optional `error_journal` (its own failure logged and swallowed), sends one neutral text ("... Do not tap again; check the journal.") to the authorized chat only, and returns `ok=False` with `CALLBACK_HANDLER_ERROR`. `CancelledError` still propagates; malformed updates still raise `ValueError` before any correlation exists. `answer_callback_safely` logs "Query is too old" at debug (`telegram.callback.answer_expired`), everything else keeps the warning.

## Verification

- Plan verification set (11 test files) plus every other test file that imports the touched modules (25 files, run with `-n 4`): all passed. New tests: 56 in the two new files.
- `uv run mypy src/adapters src/approval`: no issues. Scoped `ruff check` and `ruff format --check` on the six plan files plus the one extra test file: clean.
- `git diff --exit-code -- pyproject.toml uv.lock src/execution src/paper`: exit 0. No `src.execution` import in either Telegram adapter (also pinned by a test).
- Line endings kept (working tree is CRLF for all of these files under autocrlf; index is LF); largest diff 195 added lines in `telegram_notify.py`, no whole-file rewrite.
- `tests/test_paper_shadow_messages.py` and `tests/test_paper_shadow_buttons.py` have no commit of this plan.
- Not run: `TEST_DATABASE_URL`-dependent `tests/test_approval_replay_pg.py` (no database in this worktree session); the change to `replay.py` is a subclass of the exception it replaces, so the PG path is unaffected by construction. The orchestrator's recorded gate covers it.
- Evidence label: executed tests with fakes [DESIGN]. Research assumption A1 (an empty `reply_markup` removes the keyboard on the live Bot API) and A2 (the exact live text of "Query is too old") are unverified live; owner-run check registered by plan 23-13. The state-based `already_decided` flag is the real guarantee.

## Deviations from Plan

**1. [Rule 1 - Bug] Existing SHADOW failure test asserted the class name at WARNING level for an expired query**
- **Found during:** wide regression run after Task 3
- **Issue:** `test_a_failed_answer_never_stops_the_press_from_going_through_the_gates[too_old]` captured at WARNING; D-08 moves the "Query is too old" case to debug, so the class name is no longer in a WARNING record.
- **Fix:** the test captures at DEBUG (comment cites D-08); every assertion is kept (the press still goes through the gates, the class name is logged, the text is not).
- **Files modified:** tests/test_paper_shadow_telegram_failures.py (not in `files_modified`)
- **Commit:** a7e7d663

**2. [Process] RED commits for tasks 2 and 3 were written together with their code**
- The tests and the implementation of each task were produced in one pass, then committed test-first (RED commit holds only the tests, GREEN the source). The RED state was observed for Tasks 1 and 3 (collection ImportError); Task 2's RED commit was not run in isolation.

**3. [Process] Tool-layer note**
- Python source was edited with bytes-aware scripts (CRLF to LF to CRLF) for the multi-hunk edits; no doubled-backslash content was involved.

## Notes for later plans

- Composers (23-10 SHADOW keyboard-only, 23-11 / 23-12 DEMO and LIVE final text) pass `finalize_message=` built on `finalize_decided_message` (use `asyncio.sleep` as `sleep`; `window_seconds` can carry the remaining TTL) and `error_journal=` (the journal's record function). `DispatchResult.already_decided` is available to them to answer "already decided".
- The hook receives `CallbackPress.message_id` (None when the message is inaccessible): a composer must handle None (nothing to edit).
- A reply failure inside `_answer_press` now also lands in the handler-failure path (journal plus neutral text), which is intended by D-08.
- SHADOW runtime keeps its own `on_telegram_error`; with `build_application` also registering `make_application_error_handler`, an escaped exception logs two lines (class only, no text).

## Known Stubs

None.

## Threat Flags

None. T-23-20..23 are mitigated as planned (state-based flag, bounded message-only helpers with no `src.execution` import, class-name-only logs and journal tested with a sensitive exception text, error handler plus journaled handler failure and debug-level expired query); T-23-SC: no dependency change.

## Self-Check: PASSED

- FOUND: tests/test_telegram_decided_message.py, tests/test_telegram_error_handler.py, def finalize_decided_message, def call_bounded, def build_removed_keyboard, class ApprovalDecidedDifferently, add_error_handler(make_application_error_handler())
- FOUND commits (ancestors of HEAD): 71e907ff, 1772531e, aa8b5424, 1ba3250f, 58ea5c49, a7e7d663
