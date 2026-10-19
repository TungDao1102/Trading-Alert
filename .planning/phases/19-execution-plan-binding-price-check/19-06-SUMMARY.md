---
phase: 19-execution-plan-binding-price-check
plan: 06
subsystem: persistence
tags: [alembic, postgresql, migration, execution_intents, live-r]
requires: []
provides:
  - "Alembic migration 0005_live_sized_risk: nullable execution_intents.sized_realized_risk NUMERIC(38,18) with CHECK ck_execution_intents_sized_realized_risk"
  - "ExecutionIntentRow.sized_realized_risk ORM mirror"
  - "tests/pg_support.alembic_head_revision() (head read from the Alembic script directory)"
affects: [19-09, phase-20]
tech-stack:
  added: []
  patterns: ["hand-written migration with no project import", "head-agnostic migration tests"]
key-files:
  created:
    - src/db/alembic/versions/0005_live_sized_risk.py
  modified:
    - src/db/models.py
    - tests/pg_support.py
    - tests/test_pg_fixture_guard.py
    - tests/test_execution_exactly_once_pg.py
    - tests/test_persistence_migration_pg.py
key-decisions:
  - "Owner approved in session: option column-on-entry-intent (one nullable column plus one named CHECK on execution_intents, nothing else). Recorded 2026-10-19."
  - "No emergency-close attempt table (deterministic per-attempt ids, plan 19-12); Phase 20 can add one additively."
requirements-completed: [EXEC-02]
status: complete
duration: ~35 min
completed: 2026-10-19
actuals:
  tokens: 30000
  tasks: 3
  commits: 2
plan_head_before: e48a5b5
plan_head_after: 966c528a180bb5ec7978c4f3f6a8f821810e45eb
---

# Phase 19 Plan 06: Migration 0005 sized_realized_risk Summary

Migration 0005 adds one nullable `sized_realized_risk NUMERIC(38,18)` column and the named CHECK `ck_execution_intents_sized_realized_risk` (`IS NULL OR (role = 'ENTRY' AND value > 0)`) to `execution_intents`, mirrored in the ORM, with every migration test made head-agnostic.

## Task 1: owner decision (checkpoint:decision, blocking-human)

Owner approved in session (answered by the orchestrating session, 2026-10-19): option `column-on-entry-intent`. The migration was written exactly as the plan states; the schema was not widened. The migration was not applied to any real or shared database: tests only create and drop generated `t17_*_test` databases on the local PostgreSQL 17.11 test container, and `TEST_DATABASE_URL` was already set in the environment (not set by this plan).

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Owner decision (no commit) | n/a |
| 2 | Tracer: migration 0005, ORM mirror, head-agnostic tests | 5c682b7 |
| 3 | Reversible chain and data-bearing 0004 -> 0005 | 966c528 |

## What was built

- `src/db/alembic/versions/0005_live_sized_risk.py`: hand-written, imports only sqlalchemy and alembic (AST-checked), `down_revision = "0004_persistence_integrity"`, real downgrade (drop CHECK, then column). 0001-0004 are byte-identical (`git diff --exit-code` exits 0).
- `src/db/models.py`: `ExecutionIntentRow.sized_realized_risk` and the same-named CHECK with `ddl_if(dialect="postgresql")`; no enum, role, status or existing CHECK changed, so the enum-parity tests are untouched and green.
- `tests/pg_support.py`: `alembic_head_revision()` (single head from `ScriptDirectory`, raises on several heads). The two literal `0004_persistence_integrity` assertions in `tests/test_pg_fixture_guard.py` and `tests/test_execution_exactly_once_pg.py` now call it.
- `tests/test_persistence_migration_pg.py`: head equals script-directory head and `0005_live_sized_risk`; no `src`/`tests` import in 0005; catalog check of column type and CHECK text; ENTRY accepts 12.5; NULL stored on ENTRY and STOP_LOSS; STOP_LOSS/TAKE_PROFIT_1 with a value and ENTRY with 0 or -3 raise `IntegrityError` (SQLSTATE 23514, constraint name asserted); data-bearing upgrade 0004 -> 0005 through reflected tables keeps every row with NULL figures; downgrade 0005 -> 0004 keeps rows and removes only the column and its CHECK. The existing upgrade/downgrade/upgrade cycle test covers the full chain.

## Verification (real runs)

- `pytest -m "not docker" tests/test_pg_fixture_guard.py tests/test_execution_exactly_once_pg.py tests/test_persistence_migration_pg.py -x -rs`: pass, no skipped test (also green together with `tests/test_persistence_triggers_pg.py` and `tests/test_persistence_transitions_pg.py`, which insert `ExecutionIntentRow`).
- `uv run pytest -m "not docker" tests/test_persistence_migration_pg.py -x -rs`: pass, no skips.
- `uv run mypy src`: Success, no issues in 208 source files.
- `uv run ruff check`: All checks passed. `uv run ruff format --check`: 645 files already formatted.

## Deviations from Plan

None - plan executed as written. Notes: tests and implementation for Task 2 landed in one commit (the new tests fail without the migration, but a separate failing-test commit was not made); `alembic_head_revision()` sets `path_separator=os` on its in-memory Config to avoid an Alembic deprecation warning.

Doc follow-up (not changed, outside files_modified): `docs/data/DATA_MODEL.md` line 506, `docs/operations/RUNBOOK.md` line 362 and `docs/operations/DEPLOY_GUIDE.vi.md` line 2026 call 0004 the Phase 17 revision, which remains true; D055 / the DATA_MODEL execution_intents column list should mention `sized_realized_risk` (plan 19-17 documentation).

## Known Stubs

None.

## Threat Flags

None. T-19-15 (CHECK plus violation tests) and T-19-16 (data-bearing upgrade, reversible chain, 0001-0004 byte-identical) are mitigated.

## Self-Check: PASSED

- 0005 migration file, models change, pg_support change: present.
- Commits 5c682b7 and 966c528 are ancestors of HEAD on branch p19-06.
