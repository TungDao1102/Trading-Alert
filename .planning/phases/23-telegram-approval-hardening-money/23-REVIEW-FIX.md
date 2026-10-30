---
phase: 23-telegram-approval-hardening-money
fixed_at: 2026-10-30T00:00:00Z
review_path: .planning/phases/23-telegram-approval-hardening-money/23-REVIEW.md
iteration: 1
fix_scope: critical_warning
findings_in_scope: 11
fixed: 8
skipped: 3
status: partial
---

# Phase 23: Code Review Fix Report

**Fixed at:** 2026-10-30
**Source review:** .planning/phases/23-telegram-approval-hardening-money/23-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (WR-01 .. WR-11; there are no Critical findings)
- Fixed: 8
- Skipped: 3 (WR-03, WR-05, WR-06)
- Info findings (IN-01 .. IN-06): out of scope by the owner's instruction, none touched, no Info commit exists.

**Where verification ran:** the main checkout (`workflow.use_worktrees` is `false`, so no
worktree was created and every commit is on `develop`). Per-fix gates: the affected test files,
`uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, run with
`TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` from the process environment (set). The full
`-m "not docker" -n 4` run is recorded at the end of this file.

## Fixed Issues

### WR-01: `dispatch_callback` skipped the user gate when `authorized_user_ids` was omitted

**Files modified:** `src/adapters/telegram_callbacks.py`, `src/execution/approval_desk.py`, `src/paper/shadow.py`, `tests/support/press_identity.py` (new), and the call sites in `tests/test_approval_message.py`, `tests/test_approval_replay_pg.py`, `tests/test_journal_ids.py`, `tests/test_paper_shadow_buttons.py`, `tests/test_paper_shadow_messages.py`, `tests/test_paper_shadow_telegram_failures.py`, `tests/test_persistence_approvals_pg.py`, `tests/test_phase8_audit_reviewfix.py`, `tests/test_telegram_authorization.py`
**Commit:** 9ff1f653
**Status:** fixed: requires human verification (safety-path logic)
**Applied fix:** `from_user_id`, `chat_type` and `authorized_user_ids` are now required keywords of `dispatch_callback`; the gate always runs and `authorized_user_gate` raises `ValueError` on a missing or empty allow-list. `ApprovalDesk.dispatch` and `ShadowApprovalBook.dispatch` raise `ValueError("authorized_user_ids is required")` before any lookup. The review said every production path already forwarded the keywords; that was not true for the chat-gate refusal branch of `_answer_press`, which dispatched without them. That branch now passes them too (it would otherwise have raised). The old test that asserted "dispatch without an allow-list skips the gate" now asserts the opposite (TypeError / ValueError, nothing journaled). The shared test identity is `tests/support/press_identity.py::OWNER_PRESS` (user id 4242, equal to the shadow fakes `CHAT_ID`, so existing `actor_id == str(CHAT_ID)` assertions hold).
**Tests run:** test_approval_message, test_approval_replay_pg, test_journal_ids, test_paper_shadow_buttons, test_paper_shadow_messages, test_paper_shadow_telegram_failures, test_persistence_approvals_pg, test_phase8_audit_reviewfix, test_telegram_authorization, test_approval_desk, test_telegram_decided_message, test_telegram_error_handler, test_phase23_gate, test_confirm_flow, test_demo_rehearsal_flow, test_paper_shadow_confirm, test_paper_shadow_runtime, test_agents_md: all passed. ruff, ruff format, mypy clean.

### WR-02: Confirm token bound to the pressing user of the replay press

**Files modified:** `src/execution/confirm_flow.py`, `src/paper/shadow_confirm.py`, `tests/test_confirm_flow.py`
**Commit:** 2ff583d5
**Status:** fixed: requires human verification (safety-path logic)
**Applied fix:** `_approved` (DEMO/LIVE flow) and `approved_handler` (SHADOW) create the confirm entry only when the stored `result.approval.actor_id` equals `str(press.from_user_id)`; otherwise they return False (no confirm, the desk answers) and the flow logs `confirm_not_bound_to_stored_actor`. New test: first APPROVE stored but its handler fails, a second allow-listed user's APPROVE and CONFIRM create nothing, the stored approver's retry gets the confirm bound to them. The test fails without the fix (checked by stashing the source file).
**Tests run:** test_confirm_flow, test_paper_shadow_confirm, test_paper_shadow_buttons, test_paper_shadow_runtime, test_demo_rehearsal_flow, test_phase23_gate, test_paper_shadow_telegram_failures, test_telegram_decided_message: passed. ruff, ruff format, mypy clean.

### WR-04: Confirmation card showed the stored money block without re-checking it

**Files modified:** `src/adapters/telegram_notify.py`, `src/paper/notify.py`, `src/execution/approval_desk.py`, `src/execution/confirm_flow.py`, `src/risk/money_at_stake.py`, `tests/test_approval_message.py`, `tests/test_confirm_flow.py`, `tests/test_money_at_stake.py`
**Commit:** 83e8034c
**Status:** fixed: requires human verification (safety-path logic)
**Applied fix:** `require_money_consistent` now also requires `entry_min <= money.entry_price <= entry_max` (new required keywords `entry_min`, `entry_max`; both callers updated; the sizing entry is the adverse zone edge, so real blocks always pass). New `ApprovalDesk.checked_money_for(signal, plan)` re-runs it against the plan's quantity, stop, take-profit prices and entry zone; `ConfirmFlow._render_card` uses it (a mismatch raises and fails closed as before) and `_final_text` uses it (a mismatch is logged and no final text is built). `MoneyAtStake.__post_init__` checks `notional == quantity * entry_price` and `sum(leg_quantity) == quantity` (same 38-digit truncating context as the builder). One existing test that built deliberately odd amounts with `dataclasses.replace` now sets them on a copy with `object.__setattr__` (it tests printing, not the invariant). New tests: card refuses a tampered stored block (fails without the fix), entry outside zone, notional and leg-quantity invariants. The margin cross-check from the review was not added (no single exact definition at the post-init level; `required_initial_margin` truncates).
**Tests run:** test_money_at_stake, test_approval_message, test_confirm_flow, test_approval_desk, test_phase23_gate, test_paper_shadow_confirm, test_paper_shadow_messages, test_paper_notify, test_demo_rehearsal_flow, test_telegram_decided_message, plus `-k "money or phase23 or confirm or notify or shadow or desk or rehearsal or approval"` over the whole suite with `-n 4`: passed. `gen_phase23_fixtures.py --check` rc 0 (goldens unchanged). ruff, ruff format, mypy clean.

### WR-07: Raw one-time tokens in dataclass reprs and the undocumented confirm capability

**Files modified:** `src/approval/confirm_core.py`, `src/execution/approval_desk.py`, `src/approval/binding.py`, `tests/test_confirm_flow.py`
**Commit:** 24cb1cab
**Status:** fixed (partial by design, see below)
**Applied fix:** `ConfirmEntry.raw_token`, `_Request.approve_token`, `_Request.skip_token` and `Callback.raw_token` are `field(repr=False)`. The `ConfirmEntry` docstring now states that the capability is the in-memory entry looked up by short id, that `raw_token` is held but never compared, and that replay protection is the entry state. The review's alternative of deleting `raw_token` or binding it into callback data was not done (design change on the callback format).
**Tests run:** test_confirm_flow (new repr test), test_confirm_core, test_approval_desk, test_approval_message, test_phase8_audit_reviewfix, test_paper_shadow_confirm, test_telegram_authorization: passed. ruff, ruff format, mypy clean.

### WR-08: CONFIRMED final text said "handed to the execution step" after `on_confirmed` raised

**Files modified:** `src/approval/confirm_core.py`, `src/execution/confirm_flow.py`, `tests/test_confirm_flow.py`
**Commit:** b39b26ef
**Status:** fixed: requires human verification (wording and state)
**Applied fix:** `ConfirmEntry.hand_off_failed` is set by `_run_confirmed_hooks` when the hook raises. `ConfirmFlow._placement_lines` then returns `PLACEMENT_HAND_OFF_FAILED` ("Placement: HAND-OFF FAILED; it is not known that anything was sent. Check the journal.") plus the reconciliation words, but only when no entry intent is stored (a stored intent is better evidence and still wins). `PLACEMENT_NOT_RECORDED` and the SHADOW text are unchanged, so no golden changed (`--check` rc 0).
**Tests run:** test_confirm_flow (extended `test_a_failing_on_confirmed...`), test_confirm_core, test_paper_shadow_confirm, test_phase23_gate, test_demo_rehearsal_flow: passed. ruff, ruff format, mypy clean.

### WR-09: `ACKED` described as "already executed"

**Files modified:** `src/execution/prior_outcome.py`, `tests/test_prior_outcome_reply.py`, `tests/test_approval_desk.py`, `tests/test_confirm_flow.py`, `tests/fixtures/phase23/DERIVATIONS.md`, `docs/integration/TELEGRAM.md`
**Commit:** 3f2505fa
**Status:** fixed
**Applied fix:** the label of `PriorOutcome.ALREADY_EXECUTED` is now "already placed (acknowledged by the exchange; fill state is in the journal)". The enum member keeps its name (a rename is a wider change). The tests that pinned the old label were updated, and the two prose lines that quoted it (fixture DERIVATIONS and the TELEGRAM integration doc) follow. No generated golden contained the old text (`--check` rc 0); `verify_decision_alignment.py all` is ALL_PASS. `docs/DECISIONS.md` untouched.
**Tests run:** test_prior_outcome_reply, test_approval_desk, test_confirm_flow, test_phase23_gate, test_agents_md: passed. ruff, ruff format, mypy clean.

### WR-10: Missing invalidation fields rendered as "None at None"

**Files modified:** `src/execution/approval_desk.py`, `tests/test_approval_desk.py`
**Commit:** 554be8e3
**Status:** fixed
**Applied fix:** `_request_text_for` raises `ValueError("invalidation_rule_json needs a text basis and level")` unless both are non-empty strings, before any write. Five parametrised cases (missing, null, empty, non-string level) assert nothing is stored or journaled.
**Tests run:** test_approval_desk, test_confirm_flow, test_phase23_gate, test_demo_rehearsal_flow: passed. ruff, ruff format, mypy clean.

### WR-11: TTL, plan expiry and re-check judged at the press-receipt instant

**Files modified:** `src/execution/confirm_flow.py`, `tests/test_confirm_flow.py`
**Commit:** 1ea8e274
**Status:** fixed: requires human verification (timing logic)
**Applied fix:** `ConfirmFlow._confirm` passes `max(press.callback_at_utc, self._clock())`, read after the awaited prefetch, to `handle_confirm`. New test: a tap at second 59 whose prefetch ends at second 64 is refused with CONFIRM_TTL_ELAPSED (fails without the fix). The SHADOW confirm handler has no prefetch and is unchanged.
**Tests run:** test_confirm_flow, test_confirm_recheck, test_phase23_gate, test_demo_rehearsal_flow: passed. ruff, ruff format, mypy clean.

## Skipped Issues

### WR-03: `_later()` launders a stale pre-fetched snapshot into a "fresh" one

**File:** `src/execution/confirm_recheck.py:80-102`
**Reason:** skipped: the finding's premise does not hold in the code, no change made. `check_mark_price` and `check_last_price` measure the age as `mark_checked_at_utc - mark_time_utc` (and the same for the last price). Moving `mark_checked_at_utc` FORWARD to the press instant therefore makes the reading look older, not fresher: a stale leftover snapshot is refused (`MARK_PRICE_UNAVAILABLE`), which `test_price_age_is_measured_at_the_press_instant` in `tests/test_confirm_recheck.py` already pins (a snapshot pressed 10 s later is refused). `_later` never moves backwards, so a press instant before the fetch does not make a reading fresher either. The remaining case (a leftover snapshot of the same plan inside the 5 s price-age bound) is a genuinely fresh reading. The suggested `fetched_at_utc` field and `holder.take` discard are not needed and would change the `ConfirmInputs` shape for Phase 24. The one-line module docstring wording "never backwards" is accurate.
**Original issue:** restamping the checked-at instants erases the real age of a pre-fetched snapshot.

### WR-05: Check-then-act in `PgApprovalStore._decide` for the EXPIRED path

**File:** `src/persistence/approvals.py:254-274`
**Reason:** skipped: needs a design decision (row-lock strategy on the plan, and the APPROVE/SKIP decision path must take the same lock, or a trigger/constraint with a migration). Not applied by instruction. Today the only EXPIRED writer is the startup sweep under the instance lease; the plan 24 expiry policy should decide the serialisation before it adds writers.
**Original issue:** migration 0014 moved the "no EXPIRED next to a decided row" rule from the unique index to a SELECT followed by an UPDATE under READ COMMITTED.

### WR-06: Orphan sweep and stranded-approval assertion are not scoped to the book's mode

**File:** `src/approval/confirm_core.py:1288-1355`, `src/persistence/shadow_stores.py:83-88`
**Reason:** skipped (code fix): scoping `list_approved_approvals` by mode needs a stored mode or a new store method (and possibly a migration), a design decision. Only the review's interim advice was applied, as a comment on the `ConfirmStores.list_approved_approvals` protocol member (commit 1ece5572, documentation only): one database must serve one mode until a mode-scoped reader exists. This should be carried into Phase 24 composition.
**Original issue:** a DEMO/LIVE book would sweep and assert over SHADOW approvals of the same database.

## Out of scope (Info, owner instruction)

IN-01 .. IN-06 were not attempted. No Info fix was committed.

## Full-suite run

`TRADING_CI_STRICT=1 uv run pytest -m "not docker" -n 4` on the main checkout after the last
commit (1ece5572), `TEST_DATABASE_URL` set: every test passed except one,
`tests/test_phase21_fixtures.py::test_generator_rerun_is_byte_identical`. That failure is not
caused by these fixes: the test asserts the Phase 21 generator writes no `\r`, the generator
(`scripts/gen_phase21_fixtures.py`) and the test are unchanged since the review base commit
(`git diff 9f19c500 HEAD -- scripts tests/test_phase21_fixtures.py` is empty), and the generator
imports nothing from `src`. It looks like the known Windows CRLF behaviour of the dev machine
(see `.planning/WINDOWS.md`); it was not investigated further. The run is one `-n 4` run, not
the sequential recorded-gate form, so it is not gate evidence. `uv run ruff check`,
`ruff format --check` and `mypy src` are clean; `gen_phase23_fixtures.py --check` rc 0;
`verify_decision_alignment.py all` ALL_PASS.

---

_Fixed: 2026-10-30_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
