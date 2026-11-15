---
phase: 23-telegram-approval-hardening-money
plan: 01
subsystem: approval
status: complete
tags: [telegram, authorization, allow-list, private-chat, actor-id, reason-codes, fail-closed]
requirements-addressed: [APRV-02, PAPER-02]
requires: []
provides:
  - "src/approval/reason_codes.py: plain-string edge codes and PHASE23_EDGE_CODES"
  - "authorized_user_gate, _build_user_reject_receipt and required authorized_user_ids on on_callback / build_application"
  - "resolve_callback(..., actor_id) sets the decider in the PENDING-to-decided transition"
  - "TELEGRAM_AUTHORIZED_USER_IDS in ALLOWED_ENV_NAMES, parse_authorized_user_ids, start refusal, ShadowWiring / ShadowCoordinator / RehearsalSettings.authorized_user_ids"
affects: [23-02, 23-04, 23-07, 23-11, 23-13]
tech-stack:
  added: []
  patterns:
    - "second independent gate after the chat gate, before any lookup (D-01)"
    - "plain-string reason codes next to the 21-member RejectionReason (orchestrator resolution 7)"
    - "required keyword-only allow-list, no default anywhere (D-02)"
key-files:
  created:
    - src/approval/reason_codes.py
    - tests/test_telegram_authorization.py
  modified:
    - src/adapters/telegram_callbacks.py
    - src/approval/replay.py
    - src/paper/runtime_config.py
    - src/paper/runtime.py
    - src/paper/shadow_runtime.py
    - src/paper/rehearsal.py
    - scripts/shadow_rehearsal.py
    - scripts/demo_rehearsal.py
    - .env.example
    - deploy/soak.env.example
    - tests/shadow_fakes.py
    - tests/test_journal_ids.py
    - tests/test_phase8_audit_reviewfix.py
    - tests/test_demo_rehearsal_flow.py
    - tests/test_demo_rehearsal_safety.py
    - tests/test_paper_shadow_buttons.py
    - tests/test_paper_shadow_confirm.py
    - tests/test_paper_shadow_telegram_failures.py
    - tests/test_paper_runtime_env.py
    - tests/test_env_example.py
    - tests/test_paper_shadow_runtime.py
    - tests/test_paper_test_signal_rehearsal.py
    - tests/test_approval_replay.py
key-decisions:
  - "New refusal codes are plain strings, not RejectionReason members; len(RejectionReason) stays 21 and DispatchResult.reason_code is RejectionReason | str | None (orchestrator resolution 7, an amendment of the D-15 wording)."
  - "authorized_user_ids is validated in three places (the pure gate, on_callback / build_application entry, ShadowCoordinator.__init__): non-empty frozenset of int, bool excluded, members never in a message."
  - "dispatch_callback skips the user gate when authorized_user_ids is None (direct library callers only); on_callback always passes it and builds its own refusal, so the gate holds with a dispatcher that ignores the keywords."
  - "shadow.py is not edited: the actor is now set from the user id in resolve_callback, so its chat-id stamp (only when the actor is empty) no longer fires on the on_callback path."
metrics:
  completed: 2026-10-25
commits: 4
plan_head_before: 33f925ca471ca1fa0d8f1c91126eacc42f170a14
plan_head_after: b7e0fc85a128d7618569925c2ae847e402616181
actuals:
  tokens: 22400
  tasks: 3
  commits: 4
---

# Phase 23 Plan 01: Authorized Telegram user and private chat Summary

Only a listed Telegram user in a private chat that is the authorized chat can decide an approval: every other press is refused before any short-id or token lookup, journaled with only the presser's id, and the decider is recorded as `actor_id`; a configured Telegram without `TELEGRAM_AUTHORIZED_USER_IDS` cannot start.

## What was built

- **Task 1 (tracer, RED `70caeb5e`, GREEN `d5da3faf`).** `src/approval/reason_codes.py` (six `Final` strings plus `PHASE23_EDGE_CODES`). In `telegram_callbacks.py`: pure `authorized_user_gate` (order: user id, chat type exactly `"private"`, membership), `_build_user_reject_receipt` (CALLBACK_RECEIVED, step `user_reject`, `user_gate_rejected` true, only the presser's id), required keyword-only `authorized_user_ids` on `on_callback` and `build_application`, optional `from_user_id` / `chat_type` / `authorized_user_ids` on `dispatch_callback`, `DispatchResult.reason_code` widened, `_reason_label` for the journal and the reply text. `resolve_callback(..., actor_id)` sets the decider in the transition (max 64 characters) and a replay keeps the first actor.
- **Task 2 (`55930bb7`).** All direct `on_callback` callers in six test files pass the allow-list; local fakes carry a listed `from_user` and a private chat type; one `on_callback`-level test asserts `actor_id == str(USER_ID)`. The store-failure branch returns `APPROVAL_STORE_FAILURE` instead of `INVALIDATED` (the STATE.md item from plan 16-58); the matching assertion in `test_paper_shadow_telegram_failures.py` was changed on purpose and says so.
- **Task 3 (`b7e0fc85`).** `TELEGRAM_AUTHORIZED_USER_IDS` added to `ALLOWED_ENV_NAMES`; `parse_authorized_user_ids` (ASCII digits, positive, no leading zero, no empty item, no duplicate; the error names the variable only). `_shadow_from_env` raises `ConfigNotRatified` (`... (missing)` / `... (must be comma-separated positive integers)`) only when token and chat are set; `ShadowWiring`, `ShadowCoordinator`, `RehearsalSettings` and `callback_kwargs()` carry the set. Both rehearsal scripts refuse without it (names only). Env examples name the variable without a value.

## Verification

- Plan verification command (19 test files, plus `test_paper_test_signal_rehearsal.py` and `test_rehearsal_compose.py`): 685 passed. A wider run over the 52 test files that mention the touched modules: 1635 passed after the one deviation below.
- `uv run mypy src/approval src/adapters/telegram_callbacks.py src/paper/runtime.py src/paper/runtime_config.py src/paper/shadow_runtime.py src/paper/rehearsal.py`: no issues. Scoped `ruff check` and `ruff format --check` on every Python file of the plan: clean. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- pyproject.toml uv.lock src/domain/enums.py docs/GLOSSARY.md params config`: exit 0. `grep -rn "authorized_user_ids: frozenset\[int\] = \|authorized_user_ids=None" src scripts`: nothing.
- Line endings kept per file (`git ls-files --eol` unchanged for every edited file; no whole-file rewrite, largest diff 221 changed lines in a 1,100-line file).
- Evidence label: executed tests with fakes [DESIGN]. Nothing is composed into a running process (D-17); the live second-account / group refusal (G2-014) stays an owner-run item for plan 23-13.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `src/paper/rehearsal.py` constructs `RehearsalCoordinator(ShadowCoordinator)`**
- **Found during:** Task 3
- **Issue:** the required `authorized_user_ids` made the rehearsal coordinator unbuildable; the plan listed the file only as one to grep.
- **Fix:** `RehearsalSettings.authorized_user_ids` (required) passed to the coordinator; both rehearsal paths of `scripts/shadow_rehearsal.py` fill it (dry run: `AUTHORIZED_USER_IDS`; live: the parsed environment value).
- **Files modified:** src/paper/rehearsal.py, scripts/shadow_rehearsal.py
- **Commit:** b7e0fc85

**2. [Rule 1 - Bug] `test_no_synonym_reason_strings_in_src_approval` scans every `src/approval/*.py` for non-enum reason literals**
- **Found during:** wider regression run after Task 3
- **Issue:** the new `reason_codes.py` (placement required by the plan) is by design the one module of plain-string codes, so the scan failed.
- **Fix:** the scan skips `reason_codes.py` with a comment citing resolution 7; GLOSSARY 9.3 rows come with plan 23-13.
- **Files modified:** tests/test_approval_replay.py
- **Commit:** b7e0fc85

**3. [Rule 3 - Blocking] `scripts/demo_rehearsal.py` read `result.reason_code.value`**
- **Found during:** Task 3 (mypy on a `RejectionReason | str | None` value)
- **Fix:** `_reason()` returns the enum value or the plain string; the second-chat check uses `_reason(result) == "INVALIDATED"`.
- **Files modified:** scripts/demo_rehearsal.py
- **Commit:** b7e0fc85

**4. [Process] Task 2 changed `src/adapters/telegram_callbacks.py` already in Task 1**
- The `APPROVAL_STORE_FAILURE` branch is in the Task 1 GREEN commit because the new module and the `DispatchResult` widening landed together; Task 2 carries only its test-side effect (the changed assertion).

### Additional test files updated (not listed in files_modified)
`tests/test_paper_test_signal_rehearsal.py` (live env fixture gains `TELEGRAM_AUTHORIZED_USER_IDS`; one new refusal test) and `tests/test_approval_replay.py` (deviation 2).

## Notes for later plans

- SHADOW `Detail:` line on a store failure now names `APPROVAL_STORE_FAILURE` (classified REJECTED_OTHER as before): the deliberate change of the STATE.md item from plan 16-58.
- `ShadowApprovalBook.dispatch` still stamps `actor_id = str(callback_chat_id)` for presses that reach it without a user id (direct dispatch calls); on the `on_callback` path the actor is the user id. Plan 23-04 persists it.
- `ALREADY_DECIDED` and `CALLBACK_HANDLER_ERROR` are defined here but used by plans 23-07 and 23-11.
- A parallel quirk worth knowing: Python source edited through the tool layer loses doubled backslashes (`"\\t"` became a real tab); a corrupted `strip(" \t\r\n")` was caught by collection errors and fixed before any commit.

## Known Stubs

None.

## Threat Flags

None. The threat register items T-23-01 to T-23-05 are mitigated as planned (stranger, group and missing-user tests; no default and empty set refused; no allow-list value in payloads or messages; actor recorded; dispatcher-ignores-keywords test); T-23-SC: no dependency change.

## Self-Check: PASSED

- FOUND: src/approval/reason_codes.py, tests/test_telegram_authorization.py
- FOUND commits: 70caeb5e, d5da3faf, 55930bb7, b7e0fc85 (ancestors of HEAD)
