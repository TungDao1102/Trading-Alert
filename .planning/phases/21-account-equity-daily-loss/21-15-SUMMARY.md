---
phase: 21-account-equity-daily-loss
plan: 15
subsystem: persistence
tags: [postgres, approvals, reservations, portfolio-caps, risk-02]
requires:
  - phase: 21-12
    provides: "PgRiskReservationStore.reserve_in / release, ReservationRefused"
  - phase: 21-09
    provides: "PgDayRiskStore.lock_day"
provides:
  - "PgApprovalStore.save_atomic(approval, mapping, *, after_decide=None)"
  - "PgRiskReservationStore.release_requested_in(session, *, trade_plan_id, reason, now_utc)"
  - "make_reserving_save_atomic(*, approvals, reservations, parameter_set, daily_loss_quote) -> SaveAtomic"
affects: [21-14, phase-24]
tech-stack:
  added: []
  patterns: ["optional hook run inside the approval transaction", "decide first, then reserve under the single day-row lock; any refusal rolls the decision back"]
key-files:
  created:
    - tests/test_risk_reservation_approval_pg.py
  modified:
    - src/persistence/approvals.py
    - src/persistence/risk_reservations.py
    - tests/test_risk_reservations_pg.py
key-decisions:
  - "Decide first, then reserve: a lost race still surfaces as ApprovalAlreadyDecided and a refusal rolls the decision back, leaving the approval PENDING"
  - "daily_loss_quote(utc_day) is evaluated only for an APPROVED decision, before reserve_in takes the day-row lock (the quote is realized loss, which reservations do not change)"
status: complete
actuals:
  tokens: 8200
  tasks: 2
  commits: 2
plan_head_before: e3acba88b4f65aa02baf77b70f9171c716f7b296
plan_head_after: ba24e767f75f496ef1b22fa6ef27f20df8551057
requirements-completed: []
completed: 2026-10-23
---

# Phase 21 Plan 15: Atomic risk reservation at approval Summary

**An APPROVE decision and its risk reservation now commit in ONE PostgreSQL transaction under the day-row lock (`make_reserving_save_atomic`), so two concurrent approvals cannot both pass a cap; SKIP, CANCEL and EXPIRE release the request in the same transaction.**

## What was built

- `src/persistence/approvals.py` (CRLF kept): `save_atomic` gains the keyword-only `after_decide: Callable[[Session, Approval], None] | None = None`, called right after `_decide` and before the mapping insert. Default None, so paper SHADOW and every existing caller are unchanged; the mypy conformance block against `SaveAtomic` still type-checks. `SaveAtomic`, `dispatch_callback`, `resolve_callback` and `consume_and_record_entry_intent` are untouched.
- `src/persistence/risk_reservations.py`:
  - `release_requested_in`: only reasons whose `RELEASE_SOURCE_STATUSES` entry is exactly {REQUESTED} (APPROVAL_SKIPPED, APPROVAL_EXPIRED) are accepted, any other raises `ValueError`; a conditional UPDATE inside the caller's session; zero rows (no request, or already RELEASED such as by PLAN_EXPIRED) is a no-op.
  - `make_reserving_save_atomic`: returns a `SaveAtomic` that calls `approvals.save_atomic(..., after_decide=hook)`. APPROVED runs `reserve_in` with `now_utc = approval.acted_at_utc` and `daily_loss_quote(utc_day_of(acted_at_utc))`; SKIPPED releases with APPROVAL_SKIPPED; EXPIRED with APPROVAL_EXPIRED. No exception is swallowed: `ReservationRefused` (an `ApprovalRejected`) and `PersistenceError` propagate out of the outer transaction, so `dispatch_callback` reports `ok=False` with the cap reason without any signature change.
- Nothing composes the hook until Phase 24.

## Tests (executed against local PostgreSQL, TRADING_CI_STRICT=1)

`tests/test_risk_reservation_approval_pg.py` (21 tests): the tracer (A1 APPROVED and P1 RESERVED with `reserved_at_utc = acted_at_utc`); no-hook behaviour unchanged; a raising hook rolls the decision back; the two-thread race (BNBUSDT LONG/SHORT at 5.5 each: 5.5 + 5.5 = 11 > aggregate cap 10) where the first thread holds the day-row lock until `pg_stat_activity` shows the second connection waiting on `daily_risk_days`, the second raises `ReservationRefused(AGGREGATE_CAP_REJECT)`, its approval stays PENDING and its row REQUESTED; five refusals (no day row, no REQUESTED row, unknown loss, latched day, missing rate key); a failing quote (`StoreUnavailable`) and an unreachable database approve nothing; SKIP_USER, SKIP_BUSY, CANCEL and EXPIRE release with the right reason and `released_at_utc`; SKIP after RESERVED raises `ApprovalAlreadyDecided` and keeps RESERVED; SKIP after PLAN_EXPIRED keeps PLAN_EXPIRED; the same APPROVE twice raises `ApprovalAlreadyDecided`; `release_requested_in` ValueError and no-op cases; `resolve_callback` propagates `ApprovalRejected(AGGREGATE_CAP_REJECT)` with the approval PENDING.

Verification commands (all exit 0, 0 skipped, 0 failed):

- `tests/test_risk_reservation_approval_pg.py tests/test_risk_reservations_pg.py tests/test_persistence_approvals_pg.py tests/test_approval_replay_pg.py tests/test_paper_shadow_runtime_pg.py` plus the phase 18/19/20 gate files and `tests/test_persistence_exit_evidence_pg.py`: 192 passed in the final combined run.
- `uv run mypy src/persistence/approvals.py src/persistence/risk_reservations.py`, `ruff check` and `ruff format --check` on the plan files: clean.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- pyproject.toml uv.lock` exits 0; the `git log --grep="^[a-z]*(21-15):"` scan of `src/adapters src/approval src/execution src/db params` prints nothing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 21-12 public-API pin test**
- **Found during:** final verification run
- **Issue:** `tests/test_risk_reservations_pg.py::test_the_store_has_no_delete_path` pins the exact public method set of `PgRiskReservationStore`; the new `release_requested_in` (mandated by this plan) made it fail.
- **Fix:** added `"release_requested_in"` to the expected set (it is not a delete path).
- **Files modified:** tests/test_risk_reservations_pg.py
- **Commit:** ba24e767

## Notes

- `docs/data/DATA_MODEL.md` section 2.21 (plan 21-12) lists the writers; it was not in this plan's `files_modified`, so `release_requested_in` is not added there. Plan 21-14 (status and docs) can pick it up.
- The two commits are not split exactly along Task 1 / Task 2 (the tracer and the full store change are interdependent); one `feat` commit holds both source files, one `test` commit holds the tests.

## Known Stubs

None.

## Threat Flags

None. The new surface is the approval transaction itself (T-21-25, T-21-26 mitigated and tested).

## Self-Check: PASSED

Files exist (`src/persistence/approvals.py`, `src/persistence/risk_reservations.py`, `tests/test_risk_reservation_approval_pg.py`); commits 853c3c0d and ba24e767 are ancestors of HEAD.
