---
phase: 23-telegram-approval-hardening-money
plan: 12
subsystem: execution-approval
status: complete
tags: [telegram, confirm, d041, two-step, demo, live, card, recheck, prefetch, fail-closed]
requirements-addressed: [APRV-02, APRV-01]
requires:
  - phase: 23-05
    provides: "make_confirm_recheck, PrefetchedConfirmInputs, prefetched_provider, describe_prior_outcome, reconciliation_required_text"
  - phase: 23-06
    provides: "the shared confirm core (ConfirmBook, DEMO_/LIVE_CONFIRM_PROFILE)"
  - phase: 23-07
    provides: "call_bounded, send_text_bounded, finalize_decided_message"
  - phase: 23-11
    provides: "ApprovalDesk (plan_context, money_for, resolve, dispatch, reply_fn, finalize_hook, take_decision, intent_reader)"
provides:
  - "src/execution/confirm_flow.py: ConfirmFlow, make_confirm_flow, ValidityRule, PrefetchFn, PLACEMENT_NOT_RECORDED, VALIDITY_RULE_ERROR"
  - "src/adapters/telegram_notify.py: format_live_confirm_card, format_live_confirm_final, LiveConfirmOutcome"
  - "tests/fixtures/phase23/messages/confirm_card_demo.txt, confirm_final_confirmed_demo.txt, confirm_final_expired_demo.txt (generated) and the DERIVATIONS.md section 'Confirm card'"
affects: [23-13, phase-24]
tech-stack:
  added: []
  patterns:
    - "one core ConfirmBook per flow, the card renderer is a closure over the desk's STORED money"
    - "the composition awaits prefetch(signal, plan) before the synchronous handle_confirm; the core calls the injected recheck"
    - "the single seam to placement is the required injected on_confirmed; the module imports nothing order-capable (AST-tested)"
    - "the final text is derived from the STORED entry state and the stored entry intent, edited once per message"
key-files:
  created:
    - src/execution/confirm_flow.py
    - tests/test_confirm_flow.py
    - tests/fixtures/phase23/messages/confirm_card_demo.txt
    - tests/fixtures/phase23/messages/confirm_final_confirmed_demo.txt
    - tests/fixtures/phase23/messages/confirm_final_expired_demo.txt
  modified:
    - src/adapters/telegram_notify.py
    - scripts/gen_phase23_fixtures.py
    - tests/fixtures/phase23/DERIVATIONS.md
    - tests/test_phase23_fixtures.py
key-decisions:
  - "validity_rule is called with keywords, validity_rule(expiry_utc=..., now_utc=...), so that functools.partial(check_remaining_validity, min_remaining_validity_seconds=..., gtd_clock_margin=...) can be passed unchanged (the plan wrote both 'validity_rule(plan, now)' and 'a partial over check_remaining_validity'; only the keyword form satisfies both)."
  - "A CONFIRM that is refused before the recheck (another user or chat, after the 60 s window, after the plan expiry) does not await the prefetch: no exchange read for a press that cannot succeed."
  - "A fresh CONFIRMED or CANCELLED sends no reply message (the final card carries the decision, as the desk does for SKIP); a replayed one, and every refusal, is answered. If the final edit fails (journaled), the outcome is sent once as a message so the operator is never left without an answer."
  - "A handler that raised (on_confirmed down, store failure) is answered with the adapter's neutral 'internal error' text plus the Mode line, not the desk's 'Refused. Nothing changed.'."
  - "A card edit that ends RATE_LIMITED is not followed by a fallback send or a notice (Telegram is throttling us); the confirm is journaled EXPIRED with CARD_DELIVERY_FAILED. Any other edit failure gets exactly one fallback send of the same card."
  - "The confirm core was not changed: no defect was found by these tests (SHADOW set untouched)."
metrics:
  completed: 2026-10-26
commits: 6
plan_head_before: 8e364e322d66a51386c67fed25f8c5be50e164f4
plan_head_after: c0f455cd112f6e31d40eda49cc0a60af82b66307
actuals:
  tokens: 21400
  tasks: 3
  commits: 6
---

# Phase 23 Plan 12: DEMO/LIVE two-step confirm flow Summary

In DEMO and LIVE an APPROVE tap now only turns the request message into a confirmation card (stored money, mark price against entry and SL, the placement gate's validity verdict, the 60 s window) with CONFIRM and CANCEL; only a valid CONFIRM by the approving user reaches the injected `on_confirmed` seam, once. The flow is a library piece (D-17): `on_confirmed` is connected to nothing until Phase 24, and nothing here can place an order.

## What was built

- **Task 1 (tracer; RED `c8398580`, GREEN `a107fc18`).** `make_confirm_flow(*, desk, profile, stores, clock, bot, sleep, mark_price, validity_rule, recheck, on_confirmed, prefetch=None, ttl_seconds=60)` builds one core `ConfirmBook` (DEMO or LIVE profile, the desk must share it) with a card renderer closed over `desk.money_for`. `approved_handler` issues the confirm (stamped no earlier than the approval's `acted_at_utc`), edits the request into the card inside the remaining TTL window through `call_bounded`, makes one fallback send on any non-throttle failure, else `abort_delivery` (CARD_DELIVERY_FAILED) plus a best-effort notice. `confirm_handler` awaits `prefetch(signal, plan)` and calls `handle_confirm` (the core runs the injected recheck and, once, `on_confirmed(approval, plan, confirmed_at)` after the press); CANCEL goes to `handle_cancel`. `format_live_confirm_card` and `format_live_confirm_final` in `telegram_notify.py` (stored values with `format(value, "f")`, UTC only, `Mark price: unavailable` when None, validity `passes` or `refused (<code>)`). The CONFIRMED final reads `desk.intent_reader(approval_id)` through `describe_prior_outcome`: ACKED "already executed", UNKNOWN, SENT and INTENDED "needs reconciliation" plus `reconciliation_required_text()`, REJECTED "rejected", no intent "handed to the execution step; no entry recorded yet".
- **Task 2 (tests `d18d5bd4`, GREEN `48e8db3b`).** The criterion-4 matrix through `on_callback` with `flow.callback_kwargs(...)`: double tap, redelivered CONFIRM, CONFIRM after the TTL (inclusive 60 s), by another allowed user (keyboard kept, the approving user can still confirm), by an unlisted user (refused by the user gate, no `DEMO_CONFIRM_*` row), at the plan expiry, four recheck failures (crossed stop, no prefetch, raising prefetch, raising recheck), CANCEL (and CONFIRM after CANCEL), CONFIRM after a restart (NO_CONFIRM_CONTEXT, keyboard removed), repeated APPROVE (card re-edited, one token), SKIP after APPROVE, stale APPROVE after CONFIRM (final card not undone), a failing `on_confirmed` (neutral answer, one call, replay on the next tap), a failed final edit (journaled, outcome sent once), and the delivery paths (fallback send, RetryAfter inside the window, no card at all, throttled). GREEN added the specific reply texts, the prefetch guard, the keyboard-only removal for a press without confirm context and for an old request message when the card was sent as a new message, and the final-edit fallback message.
- **Task 3 (tests `d2ad17a7`, GREEN `c0f455cd`).** `finalize_expired(now)` (core `expire_due`, then one final EXPIRED edit per delivered card, a second call does nothing) and `expire_on_restart(now)` (RUNTIME_RESTART, edits nothing). Tests: the validity line (`LIMITS_NOT_CONFIGURED` with no minimum printed, `VALIDITY_TOO_SHORT` for a 5-minute plan, `VALIDITY_RULE_ERROR` for a raising rule, `Mark price: unavailable`), the LIVE profile (`Mode: LIVE`, `LIVE_CONFIRM_ISSUED` and `LIVE_CONFIRMED`, no DEMO row), the AST import ban (no `src.execution.manager`, `enablement`, `src.adapters.binance_usdm`, `src.paper`, `src.backtest`, no `execute_approved_plan`), and the card/final goldens. Generator `_confirm_section()` writes the three goldens; DERIVATIONS.md has the "Confirm card" section (each line's source: stored money field, mark input, validity rule).

## Verification

- `uv run pytest -m "not docker"` on tests/test_confirm_flow.py (38 tests), test_confirm_core, test_confirm_recheck, test_approval_desk, test_prior_outcome_reply, test_telegram_authorization, test_telegram_decided_message, test_phase23_fixtures, test_paper_shadow_isolation, test_paper_shadow_confirm, plus test_phase19_gate, test_phase20_gate, test_phase22_gate, test_execution_enablement, test_binance_usdm_source_guard, test_domain_no_float, test_agents_md: all passed (the full list is 456 tests).
- `uv run python -m scripts.gen_phase23_fixtures --check`: exit 0. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- Scoped `ruff check`, `ruff format --check` on confirm_flow.py, telegram_notify.py, the generator, tests/test_confirm_flow.py, tests/test_phase23_fixtures.py: clean. `uv run mypy src/execution/confirm_flow.py src/adapters/telegram_notify.py`: no issues.
- `git diff --exit-code -- pyproject.toml uv.lock src/execution/enablement.py src/execution/manager.py src/paper`: exit 0; `git log --grep="^[a-z]*(23-12):"` on those paths: nothing. `grep` for the manager, Binance adapter, `src.paper` imports and for `execute_approved_plan` in confirm_flow.py: nothing.
- Line endings: `telegram_notify.py`, `gen_phase23_fixtures.py`, `DERIVATIONS.md` and `test_phase23_fixtures.py` stay `i/lf w/crlf` (bytes-aware edits; numstat 136/1, 78/2, 29/0, 3/0, no whole-file rewrite). New files are LF in the working tree like every other new file of this phase.
- Evidence label: executed tests with fakes [DESIGN]. No Telegram or Binance connection was made; `on_confirmed` is connected to nothing, the flow is composed into no running process.

## Deviations from Plan

**1. [Interface] `validity_rule` takes keywords.**
- The plan wrote `validity_rule(plan, now)` in the interfaces and `partial(check_remaining_validity, min_remaining_validity_seconds=600, gtd_clock_margin=...)` as the test binding. A partial over `check_remaining_validity` cannot be called with `(plan, now)`. The flow calls `validity_rule(expiry_utc=plan.expiry_utc, now_utc=now)` (`ValidityRule` Protocol), so Phase 24 binds the gate's rule directly with `functools.partial`. A raising rule shows as `refused (VALIDITY_RULE_ERROR)` on the card (fail closed).

**2. [Rule 2 - Correctness] Additions the plan did not list**
- No prefetch for a CONFIRM that is refused before the recheck (user, chat, TTL, plan expiry). A handler that raised is answered with the adapter's neutral text and the Mode line instead of the desk's "Refused. Nothing changed.". A failed final edit is journaled as `<MODE>_CONFIRM_MESSAGE_EDIT_FAILED` (classified kind only, like the desk's and SHADOW's) and, for CONFIRM and CANCEL, the outcome is sent once as a message. When the card was sent as a new message (fallback), the old request message loses its buttons on the next tap. Tests for each.

**3. [Process] RED/GREEN granularity.** Task 1's module already contains the general machinery (finalize rules, reply path), so the Task 2 matrix mostly passed on first run: of the 21 added tests, 6 were observed RED (reply texts, prefetch guard through the TTL and plan-expiry cases, restart keyboard removal, final-edit fallback, old-message keyboard) and were made green in `48e8db3b`; Task 3: 5 RED (sweep, restart, goldens, fixture file list). Two test-side mistakes of mine were fixed in the tests (a flow rebuilt after APPROVE has a new empty book; `ok` is False for a replayed CANCEL).

**4. [Environment] Generator rewrite of existing goldens.** Running the generator wrote LF over the 20 existing goldens whose working-tree copies are CRLF (git saw them stat-modified, content identical after normalization). They were restored with a targeted `git checkout -- <paths>`; only the three new goldens are in the commit.

**5. [Scope] Pre-existing guard failures found, not fixed** (already in `deferred-items.md`, unchanged by this plan): `tests/test_no_unratified_defaults.py` (`RETRY_AFTER_CAP_SECONDS`, plan 23-07) and `tests/test_modeled_costs_none_guard.py` (readers in `money_at_stake.py`, plan 23-02). Both still fail on the same lines; this plan adds no hit.

## Authentication gates

None.

## Notes for plan 23-13 and Phase 24

- **Composition (Phase 24).** `desk = ApprovalDesk(...)`; `flow = make_confirm_flow(desk=desk, profile=desk.profile, stores=..., clock=..., bot=..., mark_price=..., validity_rule=partial(check_remaining_validity, min_remaining_validity_seconds=<owner limit or None>, gtd_clock_margin=...), recheck=make_confirm_recheck(prefetched_provider(holder)), on_confirmed=<placement hand-off>, prefetch=<async put into holder>)`; then `build_application(token=..., **flow.callback_kwargs(authorized_chat_id=..., authorized_user_ids=..., error_journal=...))`. Timer: `await flow.finalize_expired(now)` and `await desk.finalize_expired_requests(bot, now_utc=now)`. Startup: `flow.expire_on_restart(now)` once, before polling.
- **`on_confirmed` is the core's synchronous callable** `(approval, plan, confirmed_at_utc) -> None` and `handle_confirm` runs inline on the event loop (journal writes included). The hook must hand off quickly (queue or task) and never re-send a placement (Q5). An exception from it is answered neutrally, the CONFIRM stays journaled and is never called again.
- **Register for 23-13.** Journal rows (core, plan 23-06): `DEMO_/LIVE_CONFIRM_ISSUED`, `_CONFIRMED`, `_CONFIRM_CANCELLED`, `_CONFIRM_EXPIRED` (reasons `CONFIRM_TTL_ELAPSED`, `CARD_DELIVERY_FAILED`, `RUNTIME_RESTART`, `APPROVAL_EXPIRED`, `USER_ID_UNAVAILABLE` or the recheck code), `_CONFIRM_REJECTED` (`USER_MISMATCH`, `CHAT_MISMATCH`, `NO_CONFIRM_CONTEXT`, `CONFIRM_ALREADY_EXPIRED`), `_CONFIRM_NOTICE_FAILED`; new in this plan: `DEMO_/LIVE_CONFIRM_MESSAGE_EDIT_FAILED` (entity type `DemoConfirm`/`LiveConfirm`, correlation `<mode>-confirm:<approval_id>`, id prefix `demo-cnf-edit`/`live-cnf-edit`; without a confirm entry entity `Approval`, id `short:<short_id>`). New plain-string code `VALIDITY_RULE_ERROR` (card only). Codes shown to the operator verbatim: `USER_MISMATCH`, `CONFIRM_TTL_ELAPSED`, `APPROVAL_EXPIRED`, `NO_CONFIRM_CONTEXT`, `CONFIRM_INPUTS_UNAVAILABLE`, `CONFIRM_INPUTS_MISMATCH`, `RECHECK_ERROR`, `LIMITS_NOT_CONFIGURED`, `VALIDITY_TOO_SHORT`, `MARK_PRICE_CROSSED_STOP` and the other Phase 19 codes. Reply texts: "Already confirmed. Nothing changed.", "Already cancelled. Nothing changed.", "Refused: <CODE>. Nothing was placed." (USER_MISMATCH: "Only the user who pressed APPROVE can confirm. Nothing changed.").
- **Known limits.** Cards, message ids, confirm tokens and the prefetch holder are memory only: after a restart old cards are dead (refused, keyboard removed on tap, no startup edit). A card sent as a fallback message leaves the old request buttons until someone taps them (refused by state). Whether an empty `reply_markup` removes the keyboard on the live Bot API (research A1) is still the owner-run check registered for 23-13. D025 (Asia/Ho_Chi_Minh) vs D-14 (UTC) stays open item O-3.
- **Owner question from 23-11 is answered (relayed by the orchestrator, owner reply 2026-10-26, option c):** retire the `far` and `fill` scenarios of `scripts/demo_rehearsal.py` once Phase 24 provides a composed Demo path; keep `taps`; no code change now. Until then `far`/`fill` are not evidence of the two-step flow. Plan 23-13 registers it in the owner register as decided (c), dated 2026-10-26. This plan does not change the script.

## Known Stubs

None. `prefetch`, `recheck`, `validity_rule`, `mark_price`, `on_confirmed` and `stores` are injected; no hardcoded empty data reaches a message. The 600 s minimum in the golden and the tests is a fixed test input (named in DERIVATIONS.md), not a ratified limit.

## Threat Flags

None. T-23-36 (APPROVE only issues a card; matrix asserts the `on_confirmed` count in every case), T-23-37 (prefetch + recheck at the press; missing inputs refuse; the card shows the gate's own verdict), T-23-38 (card amounts are the stored values; the CONFIRMED final reads the stored intent; UNKNOWN shown as needs reconciliation), T-23-39 (AST import ban, `on_confirmed` required, `enablement.py` and `manager.py` unchanged), T-23-40 (RUNTIME_RESTART journaled, a later tap is NO_CONFIRM_CONTEXT and loses its keyboard) are mitigated as planned. T-23-SC: no dependency change (`git diff --exit-code -- pyproject.toml uv.lock` exits 0).

## Self-Check: PASSED

- FOUND: src/execution/confirm_flow.py, tests/test_confirm_flow.py, tests/fixtures/phase23/messages/confirm_card_demo.txt, confirm_final_confirmed_demo.txt, confirm_final_expired_demo.txt
- FOUND commits (ancestors of HEAD): c8398580, a107fc18, d18d5bd4, 48e8db3b, d2ad17a7, c0f455cd
