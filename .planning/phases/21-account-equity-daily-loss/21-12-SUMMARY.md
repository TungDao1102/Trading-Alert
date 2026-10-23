---
phase: 21-account-equity-daily-loss
plan: 12
subsystem: persistence
tags: [postgres, alembic, reservations, portfolio-caps, risk-02]
requires:
  - phase: 21-05
    provides: "day_thresholds, utc_day_of (src/risk/daily_loss.py)"
  - phase: 21-06
    provides: "ReservationStatus, ReleaseReason, RELEASE_SOURCE_STATUSES, ReservationRequest, CountedReservation, reservation_verdict"
  - phase: 21-09
    provides: "PgDayRiskStore.lock_day, daily_risk_days"
provides:
  - "migration 0011_risk_reservations: table risk_reservations (one row per plan for its life)"
  - "RiskReservationRow ORM row"
  - "PgRiskReservationStore: register_request, reserve_in, mark_placed, mark_open, release, list_counted, get"
  - "ReservationRefused(ApprovalRejected), ReservationRecord"
  - "DATA_MODEL section 2.21 risk_reservations with the release table"
affects: [21-14, 21-15]
tech-stack:
  added: []
  patterns: ["reserve step runs inside the caller's session under a FOR UPDATE lock on today's day row", "transition table enforced from the shared RELEASE_SOURCE_STATUSES mapping", "first durable release reason wins"]
key-files:
  created:
    - src/db/alembic/versions/0011_risk_reservations.py
    - src/persistence/risk_reservations.py
    - tests/test_risk_reservations_pg.py
  modified:
    - src/db/models.py
    - src/persistence/__init__.py
    - tests/test_persistence_migration_pg.py
    - docs/data/DATA_MODEL.md
key-decisions:
  - "reserve_in uses now_utc for the day lock, the verdict and reserved_at_utc (the caller passes the callback time); a non-APPROVED approval is refused as UNCERTAIN_ACCOUNT_STATE"
  - "reserve_in and release return the stored ReservationRecord so the approval transaction can read the result without a second query"
  - "register_request, mark_placed, mark_open and release take now_utc (no clock is read in the store) and an optional tx session"
status: complete
actuals:
  tokens: 70000
  tasks: 2
  commits: 2
plan_head_before: 22b56c7ace9c008ac43b2476c2e4e33a596be8ff
plan_head_after: ef821b6614fccf6781f8b056ab0885073afe6194
requirements-completed: []
completed: 2026-10-23
---

# Phase 21 Plan 12: Durable risk reservations Summary

**Migration 0011 and `PgRiskReservationStore` keep one durable reservation row per trade plan; `reserve_in` counts a plan only through the shared cap gate under the day-row lock inside the caller's transaction, and `release` follows the 21-06 transition table cell by cell.**

## What was built

- Migration `0011_risk_reservations` (revises `0010_daily_risk_state`, imports no project module, real downgrade): table `risk_reservations` with the PK, two RESTRICT foreign keys (plan, approval), the status, side, quantity, risk, release-reason (nine values), released-coherent and approval-coherent CHECKs and `ix_risk_reservations_status`. `RiskReservationRow` mirrors it (PostgreSQL-only constraints through `ddl_if`).
- `PgRiskReservationStore`:
  - `register_request` inserts a REQUESTED (not counted) row; a repeat with the same identity is a no-op, another identity is `RowConflict`, an unknown plan is `ParentRowMissing`, 19 fractional digits are `PrecisionError` before any write.
  - `reserve_in(session, ...)` locks today's `daily_risk_days` row, locks the plan row, reads the counted rows, resolves thresholds from the STORED day base, judges with `reservation_verdict` and updates REQUESTED to RESERVED, or raises `ReservationRefused` carrying the `RejectionReason` and changes nothing. It never commits and swallows nothing. A RESERVED row of the same approval is a no-op.
  - `mark_placed` / `mark_open` are no-ops on repeat and `RowConflict` from any other status; `release` reads `RELEASE_SOURCE_STATUSES[reason]` (the module's own mapping object), keeps the first stored reason and time of an already RELEASED row, and raises `RowConflict` (plan, reason and status named, no amount) from any other status or for an absent plan.
  - `list_counted` rebuilds `CountedReservation` tuples from the table, sorted by (symbol, position_side, plan id).
- DATA_MODEL section 2.21 with the columns, constraints, lifecycle, the nine-reason release table, writers and readers.
- `src/persistence/__init__.py` module map lists `risk_reservations`.

## Tests

- `tests/test_risk_reservations_pg.py`: 90 PostgreSQL tests, including the new-store-instance rebuild, idempotent `reserve_in`, the CLUSTER_CAP_REJECT refusal (4 + 2.5 > 6) leaving the plan REQUESTED, caller-owned rollback, the day-row lock held until the caller ends the transaction (`FOR UPDATE NOWAIT` from a second connection fails with 55P03), eight fail-closed refusals, and 45 parametrized (reason x status) release cells plus 9 absent-plan cases against a hand-written copy of the table that is also asserted equal to `RELEASE_SOURCE_STATUSES`.
- `tests/test_persistence_migration_pg.py`: head pinned to `0011_risk_reservations`; 0011 import-guard, revises-0010, downgrade/upgrade cycle with a stored row, CHECK-violation cases; earlier downgrade tests extended with the new table. ORM parity (`compare_metadata`) passes.

## Verification (executed against local PostgreSQL, TRADING_CI_STRICT=1)

- `tests/test_risk_reservations_pg.py tests/test_day_risk_pg.py tests/test_persistence_migration_pg.py`: 185 passed, 0 skipped.
- `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_persistence_exit_evidence_pg.py`: passed (module-map test included).
- `tests/test_domain_no_float.py tests/test_agents_md.py tests/test_risk_reservations.py`: passed.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- mypy on the three source files, ruff check and ruff format --check on the six touched code files: clean. `git diff --exit-code -- pyproject.toml uv.lock`: clean.
- `git log --grep="^[a-z]*(21-12):" -- src/adapters src/approval src/execution src/persistence/approvals.py params pyproject.toml uv.lock`: empty.
- Evidence label: executed tests against local PostgreSQL [DESIGN]; no running process composes it (plan 21-15 composes the approval transaction and the two-connection race; Phase 24 wires the PLACED/OPEN/RELEASED callers).

## Deviations from Plan

None - plan executed exactly as written. The two tasks were committed as a code commit (migration, ORM, store, tests, pins) and a docs commit (DATA_MODEL), because the Task 2 transitions were written together with Task 1 in the same module and test file.

## Known Stubs

None.

## Threat Flags

None. `reserve_in` and the transitions add no network, auth or file surface; the new table is covered by T-21-27 and T-21-34.

## Self-Check: PASSED

- FOUND: src/db/alembic/versions/0011_risk_reservations.py, src/persistence/risk_reservations.py, tests/test_risk_reservations_pg.py
- FOUND commits: 03b2f96d (feat), ef821b66 (docs)
