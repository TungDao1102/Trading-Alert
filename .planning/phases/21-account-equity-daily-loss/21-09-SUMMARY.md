---
phase: 21-account-equity-daily-loss
plan: 09
subsystem: persistence
tags: [postgres, alembic, daily-loss, day-risk, risk-02]
requires:
  - phase: 21-05
    provides: "DayRiskState, LossComponent, ComponentKind, ComponentSource (src/risk/daily_loss.py)"
provides:
  - "migration 0010_daily_risk_state: tables daily_risk_days and daily_loss_components"
  - "PgDayRiskStore: get_day, has_day, open_day, latch_stop, mark_warning_alerted, add_components, list_components, lock_day"
  - "ORM rows DailyRiskDayRow and DailyLossComponentRow"
affects: [21-12, 21-13, 21-15]
tech-stack:
  added: []
  patterns: ["insert-if-absent then return the stored row (open_day)", "set-once stamp via UPDATE ... WHERE col IS NULL", "idempotent insert per key with conflict compare (RowConflict names the key, never the amount)"]
key-files:
  created:
    - src/db/alembic/versions/0010_daily_risk_state.py
    - src/persistence/day_risk.py
    - tests/test_day_risk_pg.py
  modified:
    - src/db/models.py
    - src/persistence/__init__.py
    - tests/test_persistence_migration_pg.py
    - docs/data/DATA_MODEL.md
key-decisions:
  - "No symbol column on daily_loss_components: the 21-05 LossComponent has no symbol field and the symbol is already the prefix of source_key; a derived column would be a second source of truth"
  - "created_at_utc and recorded_at_utc use the database clock (server_default now()); the store reads no clock"
status: complete
actuals:
  tokens: 60000
  tasks: 2
  commits: 1
plan_head_before: 32292943e764b393d675e618541e6176ea2ca10d
plan_head_after: 51d4b162
requirements-completed: []
completed: 2026-10-23
---

# Phase 21 Plan 09: Daily risk state persistence Summary

**Migration 0010 and `PgDayRiskStore` keep the UTC day's equity base, the one-time DAILY_STOP latch and WARNING mark, and the idempotent signed loss components durable across a restart, with a `FOR UPDATE` day-row lock for the approval transaction.**

## What was built

- Migration `0010_daily_risk_state` (revises `0009_validated_lot_filters`): `daily_risk_days` (PK `utc_day`, equity > 0 CHECK) and `daily_loss_components` (PK `utc_day, kind, source, source_key`, CHECKs on kind, source, amount not NaN, non-empty key and asset, index on `utc_day`). Hand-written, imports no project module, real downgrade.
- ORM rows `DailyRiskDayRow` and `DailyLossComponentRow` (PostgreSQL-only CHECKs via `ddl_if`).
- `PgDayRiskStore` (`src/persistence/day_risk.py`):
  - `open_day` inserts if absent and returns the STORED row, so a second open or a restart never moves the base (T-21-18).
  - `latch_stop` / `mark_warning_alerted` update `WHERE col IS NULL`; a second call keeps the first time; an absent day raises `RowConflict`; a time outside the UTC day or naive raises `ValueError` before any write.
  - `add_components` is one transaction, idempotent per key; another amount or asset for a stored key raises `RowConflict` (message names the key, not the amount) and stores nothing of that call (T-21-19). More than 18 fractional digits raises `PrecisionError` before any write.
  - `lock_day(session, utc_day)` selects the day row `FOR UPDATE`; verified with two threads that the second connection blocks until the first commits.
  - No delete or purge method (owner-open O-1); an unreachable database raises `StoreUnavailable`; no retry loop.
- Migration-test pins moved to head `0010_daily_risk_state`; new 0010 import-guard, revises-0009 and upgrade/downgrade/upgrade cases; the 0007 and 0008 downgrade assertions now account for the 0010 tables. ORM parity (`compare_metadata`) passes.
- DATA_MODEL sections 2.19 `daily_risk_days` and 2.20 `daily_loss_components`.

## Verification

Executed against local PostgreSQL (`TEST_DATABASE_URL` set in the process environment), `TRADING_CI_STRICT=1`, label [DESIGN]:

- `tests/test_day_risk_pg.py`, `tests/test_persistence_migration_pg.py`, `tests/test_lot_filters_pg.py`, `tests/test_persistence_exit_evidence_pg.py`: all pass, no skips.
- `tests/test_phase18_gate.py`, `test_phase19_gate.py`, `test_phase20_gate.py`, `tests/test_agents_md.py`: pass.
- `uv run mypy` on models, day_risk and the migration; `ruff check` and `ruff format --check` on all plan files: clean.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- src/persistence/approvals.py src/persistence/system_state.py params pyproject.toml uv.lock`: clean (no dependency added).
- Real-stack outage behaviour stays [NOT_TESTED] (Phases 25/26).

## Deviations from Plan

**1. [Rule 1 - Plan/interface mismatch] No `symbol` column on `daily_loss_components`**
- **Found during:** Task 1
- **Issue:** The plan lists `symbol VARCHAR(32)`, but the shipped 21-05 `LossComponent` has no `symbol` field (the symbol is the first segment of `source_key`).
- **Fix:** Column omitted rather than derived from the key, to avoid a second source of truth. No reader needs it; adding it later is a new migration.
- **Files modified:** `0010_daily_risk_state.py`, `src/db/models.py`, DATA_MODEL 2.20.

**2. [Rule 3 - Blocking] `src/persistence/__init__.py` module map**
- **Found during:** gate run (`test_persistence_module_map_lists_every_module` failed on the new `day_risk` module)
- **Fix:** Added the `day_risk` line to the package docstring map. File is outside the plan's `files_modified`.
- **Commit:** 51d4b162

**3. [Rule 3 - Blocking] 0007/0008 downgrade tests**
- The two existing downgrade tests compare the table set after downgrading through 0010; their expected sets now include the two new tables (inside the plan's `tests/test_persistence_migration_pg.py`).

## Notes

- `created_at_utc` / `recorded_at_utc` use `server_default now()` (the plan did not name a source; the store reads no clock).
- Commit attribution: the DATA_MODEL 2.19/2.20 edit was swept into the parallel plan 21-10's commit `140c828e` (it staged `docs/data/DATA_MODEL.md` while my edit was uncommitted in the shared tree). The content is committed and correct; no separate 21-09 docs commit exists. `commits: 1` counts only this plan's own commit `51d4b162` (a `rev-list` range over the shared tree would include sibling commits).
- No stubs. No new threat surface beyond the plan's threat model.

## Self-Check: PASSED

- Files exist: migration 0010, `day_risk.py`, `test_day_risk_pg.py`.
- Commit `51d4b162` is an ancestor of HEAD; DATA_MODEL sections present in `140c828e`.
