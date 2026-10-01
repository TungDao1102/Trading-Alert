---
phase: 17-operational-persistence-layer
plan: 07
subsystem: database
tags: [postgresql, alembic, compare-metadata, schema-parity, utc, sqlalchemy, pytest]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01 pg_db/pg_empty_db/run_alembic fixtures and make_sync_engine; plan 02 migration 0004 with ORM mirrors"
provides:
  - "tests/test_persistence_migration_pg.py: compare_metadata parity (with checkconstraint_byname), partial-index predicate, enum CHECK literal and trigger catalog assertions, upgrade/downgrade/upgrade cycle, data-bearing 0003 to 0004 upgrade, drift-sensitivity tests"
  - "tests/test_persistence_engine_pg.py: UTC pinning for sync and async engines against a database whose default zone is Asia/Ho_Chi_Minh, fail-closed unreachable server without password leak"
  - "src/db/models.make_engine pins session timezone to UTC (psycopg options, asyncpg server_settings)"
  - "alembic floor >=1.19.2 with regenerated uv.lock; scripts/check_migration_parity.py deleted"
affects: [17-08, 17-10, 17-13, 17-15, phase-18]

actuals:
  tokens: 8100
  tasks: 2
  commits: 4
plan_head_before: 13bd65f9b4dc2e9b4f06b18ef5912aa4cf59aa1f
plan_head_after: d43e1c8da5e76612ee161040d72b6c6da258b49b

tech-stack:
  added: []
  patterns:
    - "Parity by diff: alembic compare_metadata on a database built only by alembic upgrade, plus catalog queries for what the diff cannot see"
    - "Drift-sensitivity tests: each drift class (dropped named CHECK, widened column, dropped index, dropped FK) must make the diff non-empty, so a silently disabled plugin cannot pass"
    - "Data-bearing migration test reflects the 0003 tables from the database instead of using ORM tables that carry 0004-only columns"

key-files:
  created:
    - tests/test_persistence_migration_pg.py
    - tests/test_persistence_engine_pg.py
  modified:
    - src/db/models.py
    - pyproject.toml
    - uv.lock
  deleted:
    - scripts/check_migration_parity.py

key-decisions:
  - "No drift was found: the ORM and migration 0004 already matched, so models.py gained only the UTC pin and 0004 was not touched (0001-0003 untouched as well)"
  - "Partial-index predicates are compared after normalising PostgreSQL's rendering (cast and parenthesis stripping); enum CHECK literals are compared as exact sets against the Python enums, so a new enum member without a CHECK update fails"
  - "The alembic floor is asserted by a test that reads pyproject.toml, which gave the plan a genuine RED (the parity and catalog tests were characterization tests that passed immediately)"

patterns-established:
  - "Async engine UTC pin lives in one helper, _utc_connect_args, next to make_engine"

requirements-completed: [DOMN-01]

coverage:
  - id: D1
    description: "A database built by alembic upgrade head has an empty compare_metadata diff against Base.metadata (types, widths, indexes, FKs, uniques, named CHECK presence); four drift classes are each detected"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_migration_pg.py#test_migrated_database_matches_orm_metadata"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_migration_pg.py#test_parity_check_detects_drift"
        status: pass
    human_judgment: false
  - id: D2
    description: "Partial-index predicates, enum CHECK literals (17 CHECKs over 8 tables) and all 12 append-only/terminal-status triggers are asserted from the PostgreSQL catalog"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_migration_pg.py#test_partial_unique_index_states_its_exact_predicate"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_migration_pg.py#test_enum_check_lists_exactly_the_current_enum_values"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_migration_pg.py#test_append_only_and_terminal_status_triggers_are_all_present"
        status: pass
    human_judgment: false
  - id: D3
    description: "The chain is reversible (upgrade head, downgrade base leaves only alembic_version and no function, upgrade head) and a 0003 to 0004 upgrade keeps one row in each of 12 pre-existing tables with approvals UNCONSUMED"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_migration_pg.py#test_upgrade_downgrade_upgrade_cycle_is_clean"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_migration_pg.py#test_data_bearing_upgrade_keeps_every_row"
        status: pass
    human_judgment: false
  - id: D4
    description: "Sync and async engine sessions report TimeZone UTC and read TIMESTAMPTZ with offset 0 even when the database default is Asia/Ho_Chi_Minh; an unreachable server raises StoreUnavailable without the password"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_engine_pg.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Alembic floor >=1.19.2 with a consistent uv.lock; the column-name-only parity script is gone"
    requirement: DOMN-01
    verification:
      - kind: command
        ref: "uv lock --check"
        status: pass
      - kind: unit
        ref: "tests/test_persistence_migration_pg.py#test_alembic_floor_guarantees_the_opt_in_check_constraint_plugin"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 07: Schema parity, reversibility and UTC pin Summary

**The migrated PostgreSQL schema is now proven identical to the ORM (compare_metadata plus catalog checks for predicates, CHECK literals and triggers), the migration chain is proven reversible and data-safe, and both the sync and async engines pin sessions to UTC regardless of the database default.**

## Performance

- **Duration:** about 45 min (includes two full-suite runs)
- **Completed:** 2026-10-01
- **Tasks:** 2 (both TDD: RED then GREEN; no REFACTOR needed)
- **Files:** 5 changed, 1 deleted

## Accomplishments

- `test_migrated_database_matches_orm_metadata` diffs a database built only by `alembic upgrade head` against `Base.metadata` with `compare_type`, `compare_server_default` and `alembic.ext.checkconstraint_byname`; the diff is empty. Four sensitivity tests (dropped named CHECK, widened column, dropped index, dropped FK) prove the diff is not vacuous.
- Catalog assertions cover what compare_metadata is blind to (Pitfall 4): the exact WHERE predicate of five partial unique indexes via `pg_indexes`, the literal set of 17 enum CHECKs via `pg_get_constraintdef` compared with the Python enums (and `WORKING_TYPE_VALUES`), and the full set of 12 non-internal triggers via `pg_trigger`.
- Reversibility: upgrade head, downgrade base (only `alembic_version`, no public function left), upgrade head reproduces the same table set. Data-bearing upgrade: tables reflected from a 0003 database receive one GLOSSARY-valid row each in 12 tables, upgrade to head, every value reads back unchanged and the approval is UNCONSUMED with no consumed timestamp.
- `make_engine` now passes `options=-c timezone=UTC` (psycopg) or `server_settings={"timezone": "UTC"}` (asyncpg). Verified on a database altered to `Asia/Ho_Chi_Minh`: unpinned control sessions report that zone and a +7 offset; sync and async engine sessions report UTC and offset 0; `assert_session_utc` raises on the unpinned connection.
- `make_sync_engine` against 127.0.0.1:1 raises `StoreUnavailable` naming `OperationalError`; the message and repr contain no password.
- Alembic floor raised to `>=1.19.2` (resolved version stays 1.20.0), `uv.lock` regenerated and committed with it, `uv lock --check` exits 0. `scripts/check_migration_parity.py` deleted (no references in tests, docs, .github or scripts).

## Task Commits

1. **Task 1 RED:** `55490aa` test(17-07): RED for alembic floor; parity, predicates, triggers, cycle and 0003 to 0004 data tests (31 pass, only the floor test fails)
2. **Task 1 GREEN:** `ed2d29d` feat(17-07): raise alembic floor to 1.19.2 and delete column-name-only parity script
3. **Task 2 RED:** `dbfe1b0` test(17-07): RED for UTC session pin on the async engine (async test fails with 'Asia/Ho_Chi_Minh' != 'UTC'; 4 pass)
4. **Task 2 GREEN:** `d43e1c8` feat(17-07): pin async engine sessions to timezone=UTC

## Verification (real outputs)

- `TRADING_CI_STRICT=1 pytest tests/test_persistence_migration_pg.py -x -q -rs`: 32 passed, 0 skipped.
- `TRADING_CI_STRICT=1 pytest tests/test_persistence_engine_pg.py -x -q -rs`: 5 passed, 0 skipped.
- `uv lock --check`: exit 0.
- `pytest tests/test_domain_mappers.py tests/test_analytics_store.py tests/test_approval_message.py`: all passed. `pytest tests/test_analytics_store.py tests/test_analytics_cli.py tests/test_collector.py`: all passed.
- `mypy src`: no issues in 126 files. `ruff check`: all checks passed. `ruff format --check src tests`: 285 files already formatted.
- Full suite `pytest -m "not docker" -q` with `TEST_DATABASE_URL` set: 100%, no failures section (see Issues Encountered for one transient first-run failure).
- Acceptance criteria: `scripts/check_migration_parity.py` absent; `checkconstraint_byname` present in the migration test; `alembic>=1.19.2` in pyproject.toml; `timezone=UTC` present in `src/db/models.py` and `src/persistence/engine.py`.

## Deviations from Plan

None - plan executed exactly as written. (No ORM/migration drift existed, so the plan's "fix any drift" branch had nothing to do; 0004 and 0001-0003 are unchanged.)

## Issues Encountered

- The first full-suite run (with `-x`) stopped at `tests/test_backfill_cli.py::test_funding_step_runs_per_symbol_within_bounds` with a Windows `PermissionError: [WinError 5]` on an atomic `os.replace` of a cursor file in a pytest temp dir (file locked by another process). The module passes on its own and the second full-suite run had no failures. Unrelated to this plan (no file in that path was touched); noted as a Windows flake.
- The second full-suite output was captured through `tail -15`, so the evidence is the absence of a failures section and the 100% progress line, not a printed pass count.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or trust-boundary schema change; the only runtime change is a connect option on the existing async engine.

## Next Phase Readiness

Ready for the next Phase 17 plan. Later plans that change the schema must keep the parity, predicate, CHECK-literal and trigger-inventory tests green (a new enum member, index or trigger without the matching migration or test update now fails here).

## Self-Check: PASSED

- FOUND: tests/test_persistence_migration_pg.py, tests/test_persistence_engine_pg.py
- Deleted as intended: scripts/check_migration_parity.py
- FOUND commits: 55490aa, ed2d29d, dbfe1b0, d43e1c8
