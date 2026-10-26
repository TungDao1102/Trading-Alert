---
phase: 23-telegram-approval-hardening-money
plan: 10
subsystem: paper-shadow
status: complete
tags: [shadow, telegram, keyboard-removal, ttl-sweep, error-journal, d-06, d-08]
requirements-addressed: [APRV-02]
requires: [23-06, 23-07]
provides:
  - "src/paper/shadow_confirm.py: ConfirmCallbacks.finalize_message (the SHADOW keyboard rule), EVENT_SHADOW_KEYBOARD_REMOVAL_FAILED, finalize_expired_cards, ConfirmBook.entry_for_approval, make_confirm_callbacks(stores=)"
  - "src/paper/shadow_runtime.py: callback_kwargs() adds finalize_message and error_journal; poll_once awaits finalize_expired_cards after expire_due"
  - "tests/test_paper_shadow_decided_message.py: 26 tests (keyboard removed or kept per outcome, failure journaled, sweep, no text change)"
affects: [23-13]
tech-stack:
  added: []
  patterns:
    - "keyboard-only edit (finalize_decided_message text=None) keeps every pinned SHADOW text byte-identical"
    - "the keyboard rule reads stored state (ConfirmBook entry), never a local guess"
    - "a failed removal is journaled with the classified kind only and never changes a decision"
key-files:
  created:
    - tests/test_paper_shadow_decided_message.py
  modified:
    - src/paper/shadow_confirm.py
    - src/paper/shadow_runtime.py
key-decisions:
  - "The SHADOW keyboard rule. APR/SKP press: keep when the press failed transiently (APPROVAL_STORE_FAILURE, CALLBACK_HANDLER_ERROR) or the entry is a delivered PENDING card; otherwise remove. CNF/CXL press: keep while the entry is PENDING, remove when it is missing or terminal."
  - "The journal row of a failed removal uses the confirm entity (ShadowConfirm, shadow-confirm:<approval_id>) when an entry or approval is known, else Approval / short:<id> with the press correlation id; event id prefix shadow-kbd, step press:<correlation> or ttl_expiry, so a redelivered press writes the same id."
  - "_BotProxy.edit_message_reply_markup was already present in HEAD (commit 0e159e1b, a pre-plan fix); nothing to add."
metrics:
  completed: 2026-10-26
commits: 4
plan_head_before: 752c35a0920aa04a214960a33fb3b93f7a71c680
plan_head_after: b2da5642f64da0c2e3752392b44eec26beb1fd64
actuals:
  tokens: 7300
  tasks: 2
  commits: 4
---

# Phase 23 Plan 10: SHADOW decided messages lose their keyboard Summary

A decided SHADOW message now loses its buttons with a keyboard-only edit (text byte-identical), the keyboard stays wherever a decision can still follow, a failed removal is journaled and never changes a decision, and a handler exception in SHADOW is journaled with its correlation id.

## What was built

- **Task 1 (tracer; RED `19888f06`, GREEN `e1d45473`).** `make_confirm_callbacks(..., stores=None)` returns a third hook, `finalize_message`, which `ShadowCoordinator.callback_kwargs()` now passes to `on_callback`/`build_application` together with `error_journal=stores.record_journal`. The hook runs only for presses past both gates (a stranger's tap or a wrong-chat tap never reaches it) and removes the keyboard of `press.message_id` with `finalize_decided_message(..., text=None)`. A not-done outcome is logged and journaled as `SHADOW_KEYBOARD_REMOVAL_FAILED` (payload: short_id, message_id, trigger, failure_kind, attempts, mode SHADOW; never the error text).
- **Task 2 (RED `9bb5ee98`, GREEN `b2da5642`).** `finalize_expired_cards(confirm, bot, chat_id, approval_ids, sleep, stores)` removes the keyboard of each delivered, EXPIRED card with a message id that `expire_due` just returned (trigger `ttl_expiry`); `poll_once` awaits it right after the unchanged synchronous `expire_due(now)`. A second tick does nothing because `expire_due` returns a card once. No startup sweep (raw tokens and message ids do not survive a restart).
- The 26 tests cover every bullet of the plan's behaviour list plus a parametrized check over seven flows that every SHADOW text (`sent` and `edited`) equals the text produced with the hook removed from `callback_kwargs`.

## Verification

- `tests/test_paper_shadow_decided_message.py`, `test_paper_shadow_confirm.py`, `test_paper_shadow_telegram_failures.py`, `test_paper_shadow_lock_order.py`, `test_paper_shadow_isolation.py`, `test_paper_shadow_runtime.py`, `test_paper_test_signal_rehearsal.py`, `test_paper_shadow_buttons.py`, `test_paper_shadow_messages.py`, `test_rehearsal_compose.py`: 317 passed (`-m "not docker"`), every pre-existing SHADOW test unedited.
- With TEST_DATABASE_URL in the process env and `TRADING_CI_STRICT=1`: `tests/test_paper_shadow_runtime_pg.py` and `tests/test_paper_shadow_pg.py`: 7 passed.
- `uv run mypy src/paper/shadow_confirm.py src/paper/shadow_runtime.py`: no issues. Scoped `ruff check` and `ruff format --check` on the three files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock src/execution`: exit 0. `git log --grep="^[a-z]*(23-10):"` over the pinned SHADOW test files and `src/paper/shadow.py`: nothing.
- Evidence label: executed tests with fakes [DESIGN]. Whether an empty markup removes the keyboard on the live Bot API (A1) is an owner-run check registered by plan 23-13. No Telegram or Binance connection was made.

## Deviations from Plan

**1. [Rule 1 - Bug in the plan] `expire_due` returns approval ids, not short ids**
- **Found during:** Task 2
- **Issue:** the plan says `finalize_expired_cards(..., short_ids, ...)` for "the short ids `expire_due` returned", but `ConfirmBook.expire_due` returns the sorted approval ids (core docstring and code), and orphan sweeps return approval ids that have no entry.
- **Fix:** the parameter is `approval_ids`; a new `ConfirmBook.entry_for_approval(approval_id)` (lock-protected lookup in the SHADOW subclass) maps an id to its entry; ids without a delivered EXPIRED entry that has a message id are skipped.
- **Files modified:** src/paper/shadow_confirm.py, src/paper/shadow_runtime.py
- **Commits:** e1d45473, b2da5642

**2. [Process] Task 1 GREEN holds the whole rule, the sweep wiring is in Task 2 GREEN**
- The CNF/CXL and failure cases of the keyboard rule were implemented in the Task 1 hook (the rule is one function), so the Task 2 tests for them passed on first run. The sweep wiring was held back so the Task 2 RED commit showed three real failures (TTL sweep removal, sweep failure journaled, text-parity for the sweep flow); `finalize_expired_cards` itself already sat in the Task 1 commit, unused until the Task 2 GREEN.

**3. [Process] Interleaved commits**
- The working tree is shared with wave-3 siblings; `git rev-list 752c35a0..HEAD` also counts five 23-08 commits. `commits: 4` counts this plan's commits (`19888f06`, `e1d45473`, `9bb5ee98`, `b2da5642`).

## Notes for later plans

- 23-13: register A1 (live behaviour of an empty `reply_markup`) for the owner; the glossary/doc rows for `SHADOW_KEYBOARD_REMOVAL_FAILED` (free-string event type, no schema change). The comment at `shadow_runtime.py` ~1121 about one decided approval per plan is left as is (plan 23-08 changed that rule).
- 23-11/23-12 build their finals on `finalize_decided_message` with text; SHADOW stays keyboard-only by design (D-09).

## Known Stubs

None.

## Threat Flags

None. T-23-30 (stale button after a decision) and T-23-31 (keyboard removed from a still-open decision or touched by a stranger) are mitigated and tested; T-23-SC: no dependency change.

## Self-Check: PASSED

- FOUND: tests/test_paper_shadow_decided_message.py, EVENT_SHADOW_KEYBOARD_REMOVAL_FAILED, finalize_expired_cards, "finalize_message" in callback_kwargs
- FOUND commits (ancestors of HEAD): 19888f06, e1d45473, 9bb5ee98, b2da5642
