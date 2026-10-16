---
phase: 16-paper-runtime-composition
plan: 58
subsystem: paper-shadow-locking-and-reservations
status: complete
tags: [paper-runtime, shadow, lock-order, reservations, confirm, telegram-callbacks, B2-CR-01, B2-CR-03, B2-CR-02, B2-WR-01, B2-WR-02, B2-WR-03, B2-WR-04, B2-WR-08]
requires: [16-57]
requirements: [PAPER-02]
requirements-completed: []
provides:
  - lock order of the SHADOW chain; ShadowReservations.active (one ledger-lock snapshot), documented in the shadow_runtime module docstring
  - ConfirmBook runs every CONFIRM-finishing path in one section runner and calls on_confirmed after the section and the book lock are released
  - coordinator open check (ShadowCoordinator._open_check) as the CONFIRM re-check, ShadowOpenRefused, ShadowReservations.refuse (journaled SHADOW_RESERVATION_REFUSED with the driver reject code)
  - release_expired receives the data horizon (now minus the minute close lag); ReservationEndedError for a FILL of an ended key
  - ShadowLedger.admit and risk_inputs judge on a rolled copy (_view_at); the stored ledger moves only through bookings
  - CANCEL, expire_if_due and expire_due reconcile an unknown CONFIRM append against the journal first
  - ConfirmBook.take_result(correlation_id) and telegram_callbacks.current_press_correlation (per-press reply records)
  - SHADOW_CONFIRM_REJECTED payloads without a wall-clock instant
  - an error line (class name and correlation id) for an infrastructure exception in dispatch_callback
affects: [16-43, 16-59, 16-62]
tech-stack:
  added: []
  patterns:
    - "snapshot under one lock, act under another: the two locks are never nested coordinator-then-ledger"
    - "deferred hook: a callback that takes another lock is fired after the section that decided it"
    - "judge on a rolled copy, never store a read-time roll"
    - "reply records keyed by the press correlation id through a ContextVar set by on_callback"
key-files:
  created:
    - tests/test_paper_shadow_lock_order.py
  modified:
    - src/paper/shadow_runtime.py
    - src/paper/shadow_ledger.py
    - src/paper/shadow_confirm.py
    - src/paper/shadow.py
    - src/adapters/telegram_callbacks.py
    - tests/test_paper_shadow_runtime.py
    - tests/test_paper_shadow_reservations.py
    - tests/test_paper_shadow_ledger.py
    - tests/test_paper_shadow_confirm.py
    - tests/test_paper_shadow_telegram_failures.py
    - tests/test_paper_shadow_runtime_pg.py
key-decisions:
  - "A pending reservation the fill driver cannot open is released with SHADOW_RESERVATION_REFUSED (reason = the driver reject code, occurred_at = the CONFIRM instant). A reservation that already became a position and cannot be rebuilt stays loud (ValueError / ShadowOpenRefused): its SHADOW_POSITION_OPENED cannot be undone."
  - "Expiry follows the data horizon: release_expired(now - minute_close_lag), the same value the minute poller settles through. No new number."
  - "ShadowLedger never stores a roll made by admit or risk_inputs. A time before the stored day judges the stored ledger instead of raising."
  - "An unreadable journal after an unknown CONFIRM append makes CANCEL, expire_if_due and expire_due raise (nothing written). In the poller this ends the loop like any other poll error."
  - "No RejectionReason member is added. A distinct canonical reason for store failures is left for Phase 23."
duration: about 1 h 10 min (16 min of it the full suite)
completed: 2026-10-16
commits: 4
plan_head_before: f332cc782ce72626ed137fa5d2acf9eda8524636
plan_head_after: 7231654fb40ce6361f5e8e8212bb2849a99d3dda
actuals:
  tokens: 16700
  tasks: 4
  commits: 4
---

# Phase 16 Plan 58: SHADOW locking and reservations Summary

Plan 16-58 removes the deadlock between a CONFIRM press and a poll step, and keeps one unsizable plan or one late fill from crash-looping the runtime or fabricating an outcome.

- A press and a poll step at the same time always finish. The two locks are never nested in the coordinator-then-ledger order.
- A confirmed plan the fill driver cannot open is refused before reservation. A stored one is released with a journaled SHADOW_RESERVATION_REFUSED and never stops the poller, start or restore.
- A reservation expires by the data horizon, so a fill in the last minutes before the plan expiry is journaled as SHADOW_POSITION_OPENED and never as SHADOW_PLAN_EXPIRED_UNFILLED.
- A CONFIRM after midnight no longer rolls the stored ledger past a pending 23:59 booking.
- An unknown CONFIRM append is settled against the journal before CANCEL or a TTL sweep writes a second terminal event.
- Replies belong to their press, a redelivered rejection replays, and an infrastructure error in dispatch is logged by class.

## Tasks

| Task | Name | Commit |
| --- | --- | --- |
| 1 | Tracer: a CONFIRM and a poll step at the same time always finish (B2-CR-01) | 0d15413 |
| 2 | An unsizable confirmed plan never stops the chain, and expiry follows the data horizon (B2-CR-03, B2-CR-02) | 9d4227e |
| 3 | B2-WR-01 and B2-WR-02 | 03420f9 |
| 4 | B2-WR-03, B2-WR-04 and B2-WR-08 | 7231654 |

Commit count, measured: `git rev-list --count f332cc7..HEAD` is 4 before this metadata commit. Each commit holds the tests and the fix of its task. The failing runs on the parent are recorded below (the tests were written first and run against the parent code; for Task 3 the parent was restored with `git checkout -- <file>` and the fix re-applied from a saved patch).

## Re-check outcomes

All eight findings held. No finding was closed with a note.

- **B2-CR-01 (deadlock).** Reproduced with real threads and tracked locks. The press waited inside the ledger section for the poll step to hold the coordinator lock and wait for the ledger lock. Result on the parent: `['press waits for coordinator', 'asyncio_0 waits for ledger']`. The lock-order graph also showed both `coordinator -> ledger` and `ledger -> coordinator` edges, and the restart rebuild had the second one too (the `driver_for` callback took the coordinator lock inside `rebuild_from_records`).
- **B2-CR-03 (unsizable plan).** With a 0.05 minimum quantity and a planned 0.08, the TP1 leg cannot be sized and `open_confirmed` returns `MIN_QTY_REJECT`. On the parent the CONFIRM was journaled, the reservation was taken and the log showed `paper.shadow.driver_failed ShadowRuntimeError`. `poll_once` and `restore()` then raised `ShadowRuntimeError`, every time.
- **B2-CR-02 (false expiry).** The fill minute 06:59 (closing 06:59:59.999, plan expiry 07:00) with a poll at 07:00:02 and a 5 s lag: the parent journaled SHADOW_PLAN_EXPIRED_UNFILLED at once. The no-fill variant failed the same way. The ValueError of the later EXIT could not be reached on the parent because the first assertion failed; the mechanism (EXIT on an unregistered exposure) is covered by the new `ReservationEndedError` test.
- **B2-WR-01 (midnight roll).** On the parent `admit` at 00:00:30 moved the stored ledger to the next day, and the next booking dated 23:59:59.999 raised "cannot roll the ledger backwards" (3 ledger tests). The second claim also held: after an unknown append, a retry adopting the stored CONFIRM instant once the ledger day had moved on was refused with UNCERTAIN_ACCOUNT_STATE and a SHADOW_RESERVATION_REFUSED row, although SHADOW_CONFIRMED was journaled.
- **B2-WR-02 (unknown append).** The CONFIRM append committed but its read-back failed. On the parent a CANCEL press journaled SHADOW_CONFIRM_CANCELLED after SHADOW_CONFIRMED, and a TTL sweep (`expire_if_due`) journaled a second terminal event.
- **B2-WR-03 (stale reply).** After `expire_due` expired plan 1's confirm, the SKIP reply for an unrelated plan 2 was the TTL message of plan 1 ("Confirm: EXPIRED_TTL / Detail: CONFIRM_TTL_ELAPSED").
- **B2-WR-04 (conflict on replay).** The same callback query id processed at two times raised `JournalConflict` for both the USER_MISMATCH rejection and the unknown-context rejection, on a store with the journal rule of `PgJournalStore` (same id, other payload).
- **B2-WR-08 (silent INVALIDATED).** A store exception in `save_atomic` ended in INVALIDATED with zero log records.

## What changed

**Lock order (B2-CR-01).**
- `_ensure_drivers` takes `ShadowReservations.active()` (pending then positions, one ledger-lock acquisition) before it takes the coordinator lock.
- `ConfirmBook._in_section` runs `handle_confirm`, `handle_cancel`, `expire_if_due` and the in-memory part of `expire_due` under the book lock and the ledger section. `_finish_confirm` only records the pending `on_confirmed` call; `_in_section` fires it after the locks are released.
- The restart rebuild collects its drivers in a local dict and publishes them under the coordinator lock after `rebuild_from_records` returned.
- The order is documented in the module docstring of `shadow_runtime.py`.

**Refusal and horizon (B2-CR-03, B2-CR-02).**
- The ConfirmBook now gets `recheck=ShadowCoordinator._open_check`. It builds a throw-away driver with the plan's constraint snapshot and calls `open_confirmed` exactly like `_build_position`. A reject code ends the CONFIRM as a refused one (EXPIRED with `rejected_at_confirm`, reason = the code), and the operator reply names the code.
- `_build_position` raises `ShadowOpenRefused`. `_ensure_drivers` collects them, releases each pending reservation outside the coordinator lock with `ShadowReservations.refuse`, and logs `paper.shadow.reservation_refused`.
- `_sweep` passes `now - minute_close_lag_seconds` to `release_expired`.
- `_apply_new_events` raises `ReservationEndedError` for a FILL of a key in `_ended`.
- `_approved_records` treats a refused reservation as an ended plan: an opportunity with the reject code as the reason (it used to stay "confirmed and resting" forever).

**Rolled copy (B2-WR-01).** `ShadowLedger._view_at(at_utc)` rolls a copy forward and never stores it. `admit` and `risk_inputs` use it. A time inside or before the stored day judges the stored ledger. The no-op `risk_inputs` call at the end of `rebuild_from_records` was removed.

**Unknown append (B2-WR-02).** `_reconcile_unknown` is the one place that reads the journal for an entry with `confirm_append_unknown`. `handle_confirm`, `handle_cancel`, `expire_if_due` and `expire_due` call it before they write anything.

**Replies, replay, log (B2-WR-03/04/08).**
- `ConfirmBook` keeps its reply records in a bounded dict by press correlation id. `_result` stores one only inside a press. A body that raises purges its record. `take_last_result` is gone; `take_result(correlation_id)` replaces it.
- `on_callback` sets a ContextVar (`current_press_correlation`) for the duration of the press. `make_shadow_reply_fn` reads it.
- `rejected_at_utc` is out of both rejection payloads. The processing time is the event `occurred_at_utc`, which the journal does not compare.
- `dispatch_callback` logs `telegram.callback.dispatch_failed: <ClassName> correlation_id=cbq:<id>` for an unexpected exception. The press still returns INVALIDATED.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] A refused reservation had no attribution**
- **Found during:** Task 2
- **Issue:** `_approved_records` returned `[]` for a SHADOW_CONFIRMED plan with a SHADOW_RESERVATION_REFUSED event, so a refused plan was "confirmed and resting" forever and never became a paper record.
- **Fix:** a refusal counts as an ended plan; the reason is the journaled reject code.
- **Files modified:** `src/paper/shadow_runtime.py`
- **Commit:** 9d4227e

**2. [Rule 3 - Blocking] The tail of `on_callback` moved into `_answer_press`**
- **Found during:** Task 4
- **Issue:** the ContextVar must be reset on every return path of a long function with many returns.
- **Fix:** `on_callback` computes the correlation id, sets the variable and calls `_answer_press` (the unchanged body) inside try/finally.
- **Files modified:** `src/adapters/telegram_callbacks.py`
- **Commit:** 7231654

**3. [Rule 1 - Bug] The CANCEL path and the TTL sweeps took no lock**
- **Found during:** Task 3
- **Issue:** the TTL sweep and the CANCEL path never held the book lock or the section, so reconciling an unknown append there would have raced with a CONFIRM on the ledger.
- **Fix:** all four paths run through `_in_section`; the orphan sweep of `expire_due` (journal I/O) stays outside the ledger section.
- **Commit:** 03420f9

**Total deviations:** 3 (1 missing functionality, 1 blocking, 1 bug). **Impact:** none on the scope of the plan.

## Requirements

PAPER-02 is declared by this plan and is not marked complete. `requirements.ready-ids` reports 0 of 1 ready: sibling plans of the phase that declare it have no SUMMARY yet, and the requirement text closes it only when Phase 16 criteria 3 and 5 hold on the rehearsal (plan 16-40), not on fake-level tests. The executor marked it once by mistake and the change to `.planning/REQUIREMENTS.md` was reverted before any commit.

## Remaining limitations

- **Phase 23.** A store failure ends in the canonical reason INVALIDATED. A distinct `RejectionReason` for it would change GLOSSARY section 9 and is not added here.
- **Approval decision slot.** `ShadowApprovalBook.take_last_decision` is still one slot. Its stale-record case is not the one B2-WR-03 describes (every dispatch writes it before its own reply), and the button tests read it directly. Only the confirm path is keyed by press.
- **Unreadable journal in the poller.** With a pending unknown CONFIRM append, `expire_due` raises while the journal cannot be read, which ends the poll loop like any other poll error (the runtime fails closed). The plan asks for exactly this; it means a journal outage longer than one TTL stops the poller.
- **An opened position that cannot be rebuilt** stays a loud error (`ShadowOpenRefused` out of `restore`, or `ValueError` from `refuse`). Its SHADOW_POSITION_OPENED is journaled, so releasing it as refused would contradict the journal. It cannot happen with the journaled plan context, which is what the rebuild uses.

## Verification

| Command | Result |
| --- | --- |
| `pytest tests/test_paper_shadow_lock_order.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_reservations.py` | pass |
| `pytest tests/test_paper_shadow_runtime.py tests/test_paper_shadow_reservations.py tests/test_paper_shadow_ledger.py tests/test_paper_shadow_fill.py tests/test_paper_shadow_runtime_pg.py` | pass |
| `pytest tests/test_paper_shadow_ledger.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_reservations.py tests/test_paper_attribution.py` | pass |
| `pytest tests/test_paper_shadow_confirm.py tests/test_paper_shadow_buttons.py tests/test_paper_shadow_telegram_failures.py tests/test_paper_shadow_messages.py tests/test_paper_shadow_isolation.py tests/test_paper_shadow_pg.py` | pass |
| `tests/test_domain_no_float.py` (D-12 guard, run before each commit) | pass |
| `ruff check` (whole repo), `ruff format --check` (617 files) | clean |
| `mypy src` | Success: no issues found in 202 source files |
| `pytest -m "not docker"` | 10071 collected; 10065 passed, 6 skipped, 0 failed (15 min 50 s). The run used `-q -q`, so the counts come from the progress markers; they add up to the collected count. |
| `git log --oneline --grep=16-58 -- src/backtest/` | empty: nothing under `src/backtest/` changed |

The PostgreSQL tests ran: `TEST_DATABASE_URL` was set in this shell and the database answered. `tests/test_paper_shadow_runtime_pg.py` passed 3 of 3, including the new `test_a_reservation_that_cannot_open_is_refused_once_on_postgresql`.

## Known Stubs

None.

## Threat Flags

None. No endpoint, auth path or schema was added. The new `SHADOW_RESERVATION_REFUSED` writer reuses the existing event type, id rule and entity type.

## Self-Check: PASSED

- `tests/test_paper_shadow_lock_order.py` exists; commits 0d15413, 9d4227e, 03420f9 and 7231654 are on `develop`.
- Every task command of the plan passed, and the plan-level `ruff check` and `mypy src` are clean.
