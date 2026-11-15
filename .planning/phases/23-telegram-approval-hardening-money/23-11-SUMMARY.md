---
phase: 23-telegram-approval-hardening-money
plan: 11
subsystem: execution-approval
status: complete
tags: [telegram, approval-desk, demo, live, skip, money-at-stake, g4-032, keyboard-removal, fail-closed]
requirements-addressed: [APRV-01, APRV-02, PAPER-02]
requires:
  - phase: 23-01
    provides: "user/chat gates, actor_id from the user id, ALREADY_DECIDED / APPROVAL_STORE_FAILURE codes"
  - phase: 23-04
    provides: "Approval.money_json, actor_id persisted"
  - phase: 23-05
    provides: "prior_outcome_for_expired_redelivery"
  - phase: 23-06
    provides: "DEMO_CONFIRM_PROFILE / LIVE_CONFIRM_PROFILE"
  - phase: 23-07
    provides: "send_text_bounded, finalize_decided_message, FinalizeHook, DispatchResult.already_decided"
  - phase: 23-09
    provides: "format_approval_request, build_decision_keyboard, format_utc"
provides:
  - "src/execution/approval_desk.py: ApprovalDesk (issue, send, resolve, plan_context, money_for, request_text, message_id, dispatch, take_decision, reply_fn, finalize_hook, finalize_expired_requests, confirmation_attached), DeskStores, IssuedRequest, RequestSendOutcome, DeskDecisionRecord, DeskOutcome, NO_HANDLER_REPLY, the <MODE>_APPROVAL_REQUEST_* and <MODE>_DECIDED_MESSAGE_EDIT_FAILED event names"
  - "scripts/demo_rehearsal.py: send_approval sends one message with build_decision_keyboard"
affects: [23-12, 23-13, phase-24]
tech-stack:
  added: []
  patterns:
    - "desk record per press, keyed by the press correlation id: the reply and the final edit read the same record"
    - "the final text is derived from the STORED rows (decision, actor, UTC time), never from a local guess"
    - "take-profit shares come from the stored money block, not from a constant (no src.backtest import in src.execution)"
key-files:
  created:
    - src/execution/approval_desk.py
    - tests/test_approval_desk.py
    - .planning/phases/23-telegram-approval-hardening-money/deferred-items.md
  modified:
    - scripts/demo_rehearsal.py
    - tests/test_demo_rehearsal_flow.py
key-decisions:
  - "TP fractions of the request come from money.take_profits (the block built for those legs), because Phase 19 invariant 7 forbids any src.execution import of src.backtest. require_money_consistent still compares prices and the number of legs; a money block without exactly two legs is refused before any write."
  - "A press that the desk cannot attribute to a known request (a restart lost the in-memory short id) is answered 'Refused: INVALIDATED' and loses its keyboard only (the raw tokens are gone, so the buttons are dead)."
  - "An unreadable entry intent on an APPROVED expired redelivery is answered 'needs reconciliation' (never 'expired' or 'rejected'): the conservative reading under Q5."
  - "confirmation_attached (plain attribute, default False) lets plan 23-12 switch the wording from 'no confirmation card handler is attached' to 'Nothing was placed.'"
  - "The same final text is edited once per request (finalized_text); a failed edit is retried by the next tap."
metrics:
  completed: 2026-10-26
commits: 6
plan_head_before: d0ecc2c2b7331b3415cc5a5fc4e736aa44cdee5c
plan_head_after: d0e4f86e6ed54bd24fe1bbda62cc513b6823ce37
actuals:
  tokens: 17900
  tasks: 3
  commits: 6
---

# Phase 23 Plan 11: DEMO/LIVE approval desk Summary

A DEMO or LIVE approval request is now ONE message with APPROVE and SKIP and the stored money block; a SKIP tap is recorded with its decider and the message becomes final without buttons; every stale tap and every failed send leaves state unchanged and is answered truthfully. The desk is a library piece (D-17): no running process uses it until Phase 24.

## What was built

- **Task 1 (tracer; RED `409f4d7f`, GREEN `0646bb3d`).** `ApprovalDesk.issue` refuses a missing or disagreeing money before any write, then writes signal, plan, the APPROVE and SKIP_USER rows (both with `approved_quantity` and the same `money_json`), the short-id mapping and the `<MODE>_APPROVAL_REQUEST_ISSUED` row, in that order. `send` uses `send_text_bounded` with `build_decision_keyboard` (one row, `APR:` and `SKP:` over one short id); success journals `..._SENT` with the message id, failure journals `..._SEND_FAILED` with the classified kind and the exception class only, and approves nothing. `resolve`, `dispatch`, `reply_fn` and `finalize_hook` plug into `on_callback`: SKP by the listed user gives SKIPPED with `SKIP_USER` and `actor_id` "777001", and the request message is edited once to the request text plus `Decision: SKIPPED by user 777001 at <UTC>` with an empty keyboard.
- **Task 2 (tests `97b79293`).** Same module: RetryAfter honoured; Forbidden leaves both rows PENDING; three SKP taps give one transition and one final edit (taps 2 and 3 answer `Already decided: SKIPPED. Nothing changed. [ALREADY_DECIDED]`); APR after SKP refused; a fresh APPROVE without a card handler is recorded, answered with `NO_HANDLER_REPLY`, and the final text says nothing can be confirmed or placed; G4-032 for all five `ExecutionIntentStatus` members (ACKED "already executed", UNKNOWN / SENT / INTENDED "needs reconciliation" plus `reconciliation_required_text()`, REJECTED "rejected", no intent "Refused: APPROVAL_EXPIRED"), the reader never called for a PENDING approval; a store failure keeps the keyboard; a tap after expiry on a PENDING request finalizes it as EXPIRED; `finalize_expired_requests` edits each sent, untapped, expired request once and writes no approval row; a failed final edit is journaled as `..._DECIDED_MESSAGE_EDIT_FAILED` and changes no decision; strangers, groups and wrong chats get "Refused. Nothing changed." with no edit of the operator's message; a restart-lost short id loses only its keyboard; LIVE labels. 30 tests in `tests/test_approval_desk.py`.
- **Task 3 (RED `d535c790`, GREEN `e99646db`).** `PtbApprovalChannel.send_approval` sends `build_decision_keyboard(signal_id)` for every step kind; the now-unused imports are gone. 6 added and 7 removed lines in the script (CRLF kept). Two new tests: the real channel sent through a recording bot (APPROVE and SKIP kinds, one row, `APR:`/`SKP:`), and an AST check that the script no longer names `build_approve_keyboard` / `build_skip_keyboard`.
- **Fix `d0e4f86e`.** See deviation 1.

## Verification

- Plan verification set (`test_approval_desk`, `test_prior_outcome_reply`, `test_telegram_decided_message`, `test_telegram_authorization`, `test_demo_rehearsal_flow`, `test_demo_rehearsal_safety`, `test_paper_shadow_isolation`) plus `test_phase19_gate`, `test_phase20_gate`, `test_phase22_gate`, `test_execution_enablement`, `test_binance_usdm_source_guard`, `test_domain_no_float`, `test_agents_md`, `test_confirm_core`: 430 passed (`-m "not docker"`).
- `uv run mypy src/execution/approval_desk.py scripts/demo_rehearsal.py`: no issues. Scoped `ruff check` and `ruff format --check` on the four Python files: clean. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- pyproject.toml uv.lock src/execution/enablement.py src/execution/manager.py src/paper`: exit 0 (no dependency change; SHADOW modules and `LIVE_ORDERS_DISABLED` untouched). `grep -nE "^(from|import) src\.(execution\.manager|adapters\.binance_usdm|paper|backtest)"` and `grep execute_approved_plan` on the desk: nothing.
- Line endings: `scripts/demo_rehearsal.py` and `tests/test_demo_rehearsal_flow.py` stay `i/lf w/crlf` (bytes-aware edit; numstat 6/7 and 41/0). New files are LF in the working tree like every other new file of this phase (git warns, normalizes).
- Evidence label: executed tests with fakes [DESIGN]. No Telegram or Binance connection was made; the desk is composed into no running process until Phase 24.

## Deviations from Plan

**1. [Rule 1 - Bug] The first GREEN imported `src.backtest.semantics.TP1_QUANTITY_FRACTION`**
- **Found during:** wider guard run after Task 3 (`tests/test_phase19_gate.py::test_invariant_7_no_execution_module_imports_the_backtest`).
- **Issue:** the plan's analog (`format_shadow_alert`) takes the TP shares from the backtest constant; no `src/execution` module may import the backtest.
- **Fix:** the shares come from `money.take_profits` (the stored block built for these legs); a block without exactly two legs is refused before any write; test added.
- **Commit:** d0e4f86e

**2. [Process] RED/GREEN granularity**
- The module was written in one pass, so the Task 2 tests passed on first run (the one real RED was the Task 1 tracer, observed as a collection ImportError, and the Task 3 tests, observed failing against the unchanged script). Two test-side mistakes of mine (a fixture `realized_risk` below the gross loss; a FakeBot fallback that made a "failed edit" succeed) were fixed in the tests, not in the desk.

**3. [Scope] Pre-existing guard failures found, not fixed** (logged in `deferred-items.md`)
- `tests/test_no_unratified_defaults.py` fails on `RETRY_AFTER_CAP_SECONDS` in `telegram_notify.py` (plan 23-07).
- `tests/test_modeled_costs_none_guard.py` fails on the new readers in `money_at_stake.py` (plan 23-02).
- Neither file is touched by this plan; the orchestrator's full run will report both.

## Owner question

**The Demo rehearsal still places a Demo order after ONE tap on APPROVE (D041 says only CONFIRM may do that).**
- *What it is:* `scripts/demo_rehearsal.py` is the script the owner runs by hand against Binance Demo (never run by an assistant). In its `far` and `fill` scenarios, one tap on APPROVE leads straight to placing a Demo order. A typed phrase at the start of the run (`--execute`) is the only extra guard. Since Phase 16 the SHADOW flow and, with plans 23-11 and 23-12, the DEMO/LIVE desk use a second step: APPROVE only records the decision, a confirmation card follows, and only CONFIRM may lead to an order (decision D041).
- *What this plan did:* only the keyboard changed. The rehearsal now sends one message with APPROVE and SKIP, as the new desk does. The step text still says which button to tap. The APPROVE-to-placement path and the scenarios are unchanged (orchestrator resolution 5: minimal change).
- *Decision needed from the owner (to be registered by plan 23-13):* (a) leave the rehearsal as it is and write down that it is a Demo-only manual tool that predates the two-step rule; (b) add a CONFIRM step to the rehearsal so it exercises the same flow as production (more work, and the rehearsal then tests the real flow); (c) retire the APPROVE-to-placement scenarios once Phase 24 gives a composed Demo path.
- *Risk if left as is:* none for live trading (live placement is disabled and the script is Demo-only and owner-run), but the rehearsal would not prove the two-step flow.

## Notes for plan 23-13 and 23-12

- **For 23-12 (flow):** use `desk.confirmation_attached = True`; the desk's `reply_fn(bot, sleep=)` and `finalize_hook(bot, sleep=)` are the fallbacks and read the per-press record, so call them from the flow's own functions in the same press. `desk.take_decision(correlation_id)` pops the record: the finalize hook pops it, `reply_fn` only reads it (except for gate refusals, which it consumes). A flow that replaces the finalize hook for a press must still call `take_decision` or the record stays until the 256-entry cap evicts it.
- **Register for 23-13:** journal event names `DEMO_/LIVE_APPROVAL_REQUEST_ISSUED`, `_SENT`, `_SEND_FAILED`, `DEMO_/LIVE_DECIDED_MESSAGE_EDIT_FAILED` (entity type `ApprovalRequest`, correlation `<mode>-request:<signal_id>`, event-id prefix `demo-req` / `live-req`); the desk's reply texts (codes verbatim: `ALREADY_DECIDED`, `APPROVAL_EXPIRED`, `APPROVAL_STORE_FAILURE`, plain "Refused. Nothing changed." for gate refusals); `intent_reader` contract (approval id to `IntentRecord | None`, Phase 24 binds `store.get_entry(approval_id=...)`); the two pre-existing guard failures above; the owner question above.
- **Known limits (Phase 24 / owner):** request text, message id and raw tokens are memory-only, so after a restart old buttons are dead (refused, keyboard removed on tap); there is no startup sweep of old requests. The rows of an unanswered request are not expired by the desk (O-2 in 23-08 / Phase 24 policy). Whether an empty `reply_markup` removes the keyboard on the live Bot API (research A1) is still the owner-run check registered for 23-13.
- Times in desk texts are UTC with the suffix (D-14); D025 (Asia/Ho_Chi_Minh presentation) vs D-14 stays the open item O-3 recorded by plan 23-09.

## Known Stubs

None. `intent_reader` and `stores` are injected; no hardcoded empty data flows to a message.

## Threat Flags

None. T-23-32 (send failure never approves: Forbidden test, no code path decides on a send outcome), T-23-33 (money missing or mismatching refused before any write; both rows carry the same `money_json`; the text is rendered from it), T-23-34 (distinct `APR:`/`SKP:`, SKIP_USER -> SKIPPED with the actor, final edit removes the keyboard, stale taps refused from state), T-23-35 (every intent status mapped; an unreadable intent reads as reconciliation) are mitigated as planned. T-23-SC: no dependency change.

## Self-Check: PASSED

- FOUND: src/execution/approval_desk.py, tests/test_approval_desk.py, .planning/phases/23-telegram-approval-hardening-money/deferred-items.md
- FOUND commits (ancestors of HEAD): 409f4d7f, 0646bb3d, 97b79293, d535c790, e99646db, d0e4f86e
