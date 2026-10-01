---
phase: 17-operational-persistence-layer
plan: 02
subsystem: database
tags: [postgresql, alembic, sqlalchemy, check-constraints, foreign-keys, triggers, append-only, pytest]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01: pg_db template-clone fixtures, migration 0004 first slice (approval consumption, execution_intents), make_sync_engine"
provides:
  - "Complete migration 0004: VARCHAR(32) widths, 11 named enum CHECKs, 8 price/quantity CHECKs, unique and partial unique indexes, 12 ON DELETE RESTRICT foreign keys"
  - "Append-only triggers (row and TRUNCATE) on journal_events, system_state_events, plan_constraint_snapshots"
  - "Terminal-status triggers on signals, trade_plans, orders, positions, approvals, execution_intents"
  - "plan_constraint_snapshots and system_state_events tables with ORM rows PlanConstraintSnapshotRow and SystemStateEventRow"
  - "ORM parity: 18 pre-existing migration indexes declared under exact names plus every 0004 object (new ones PostgreSQL-only via ddl_if)"
  - "src/data/metadata.py width guard derived from the model (METADATA_TEXT_MAX_LEN = 32)"
affects: [17-03, 17-07, 17-08, 17-10, 17-13, phase-18, phase-20, phase-24]

actuals:
  tokens: 21300
  tasks: 2
  commits: 4
plan_head_before: dc2a74aca5e8f448fdc1c67cd58f867ed713e039
plan_head_after: ab3b110dd54f26f87146dd3a09f5f5943e4ea627

tech-stack:
  added: []
  patterns:
    - "Database-enforced decisions: duplicate decision, duplicate client id, orphan, illegal status change all refused by PostgreSQL with named constraints"
    - "One PL/pgSQL function per concern (reject_append_only_mutation, reject_terminal_status_change(column, terminal...)) bound by named triggers"
    - "ORM mirrors migration 0004 with ddl_if(dialect=postgresql) so SQLite create_all suites keep pre-0004 DDL"
    - "Insert-every-enum-member tests iterate the Python enum, so a new member without a CHECK update fails"

key-files:
  created:
    - tests/support/pg_rows.py
    - tests/test_persistence_constraints_pg.py
    - tests/test_persistence_enum_columns_pg.py
    - tests/test_persistence_triggers_pg.py
  modified:
    - src/db/alembic/versions/0004_persistence_integrity.py
    - src/db/models.py
    - src/data/metadata.py
    - tests/test_metadata.py

key-decisions:
  - "positions.quantity gets NO sign CHECK (C4 refinement for D051): position_amt is signed (negative for SHORT in one-way mode, src/adapters/binance_usdm.py ~329), so >= 0 would reject a legal short"
  - "No CHECK on orders.order_role or trade_plans.quantization_decision (research A3: free-string domain fields, tests use the non-enum ACCEPTED/ACCEPT)"
  - "Terminal sets for triggers taken from the research draft transition tables (auto-mode default C3): signals {APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED}, trade_plans {EXPIRED, INVALIDATED, SUPERSEDED}, orders.local_status {FILLED, CANCELED, EXPIRED, REJECTED}, positions {CLOSED}, approvals.status {APPROVED, SKIPPED, EXPIRED}, execution_intents.intent_status {ACKED, REJECTED}; plan 10 cross-checks against src/domain/transitions.py"
  - "Terminal triggers are plain BEFORE UPDATE (not UPDATE OF status): the function compares old/new through to_jsonb, so a no-op status assignment on a terminal row is allowed and an UPDATE touching only other columns is allowed"
  - "plan_constraint_snapshots.working_type CHECK mirrors WORKING_TYPE_VALUES = {MARK_PRICE} (D037); widen the registry set and the CHECK together"
  - "snapshot_json and state_json use TEXT (sa.Text / Text) on migration and ORM alike; alembic autogenerate compare against the migrated database reports zero differences"

patterns-established:
  - "Raw-bypass tests: constraints are proven with ORM/SQL writes that skip the Python repositories, reading diag.constraint_name from psycopg"
  - "Every PG test clones a fresh migrated database (append-only triggers forbid cleanup)"

requirements-completed: [DOMN-01, APRV-02, EXEC-03, DOMN-04]

coverage:
  - id: D1
    description: "A second approval with the same token hash, or a second decided approval for one trade plan, is rejected by PostgreSQL; several PENDING approvals per plan coexist (F-404, research A4 confirmed on a real server for UPDATE)"
    requirement: APRV-02
    verification:
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_duplicate_approval_token_hash_is_rejected"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_second_decided_approval_for_one_plan_is_rejected"
        status: pass
    human_judgment: false
  - id: D2
    description: "Duplicate non-null client_order_id / algo_client_id on orders rejected; NULLs may repeat"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_duplicate_client_order_id_is_rejected"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_duplicate_algo_client_id_is_rejected"
        status: pass
    human_judgment: false
  - id: D3
    description: "Twelve foreign keys are ON DELETE RESTRICT; orphan children and deletes of referenced parents fail; short_id_mapping has no FK"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_all_listed_foreign_keys_exist_and_restrict_deletes"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_orphan_child_is_rejected"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_deleting_a_referenced_parent_is_restricted"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every enum-valued column accepts every Python enum member and rejects any other value with its named CHECK; price/risk/quantity CHECKs; widths of six columns are VARCHAR(32) so TRADIFI_PERPETUAL, TRADING_CANCEL_ONLY and LIQUIDATION_REPORTED insert untruncated"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_enum_columns_pg.py"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_constraints_pg.py#test_trade_plan_price_and_risk_checks"
        status: pass
      - kind: unit
        ref: "tests/test_metadata.py#test_metadata_width_limit_is_derived_from_the_model"
        status: pass
    human_judgment: false
  - id: D5
    description: "journal_events, system_state_events and plan_constraint_snapshots reject UPDATE, DELETE and TRUNCATE; terminal statuses cannot change on six tables while non-terminal transitions, no-op status assignments and non-status updates (approval consumption) are allowed"
    requirement: DOMN-04
    verification:
      - kind: integration
        ref: "tests/test_persistence_triggers_pg.py"
        status: pass
    human_judgment: false
  - id: D6
    description: "plan_constraint_snapshots (UNKNOWN sentinels, COMPLETE-has-live-inputs and MARK_PRICE CHECKs) and system_state_events (key set, version >= 1, unique key/version, journal FK) exist with ORM mirrors"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_triggers_pg.py#test_snapshot_checks"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_triggers_pg.py#test_state_event_key_version_is_unique"
        status: pass
    human_judgment: false

duration: 30min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 02: Schema integrity in migration 0004 Summary

**PostgreSQL itself now refuses a duplicate approval decision, a duplicate client id, an orphan row, an out-of-enum or non-positive value, a truncating status width, an audit-row rewrite and a status leaving a terminal state, all with named constraints and triggers proven by bypass tests on disposable migrated databases.**

## Performance

- **Duration:** about 30 min (includes a full-suite run)
- **Completed:** 2026-10-01
- **Tasks:** 2 (both TDD: RED then GREEN, no REFACTOR needed)
- **Files:** 8 (4 created, 4 modified), about 2250 insertions

## Accomplishments

- Migration 0004 extended (hand-written, no project imports; 0001-0003 byte-identical to 99d3a94): six columns widened to VARCHAR(32), 11 enum CHECKs with literals copied from `src/domain/enums.py`, 8 price/quantity CHECKs, `uq_approvals_token_hash`, `uq_approvals_one_decided_per_plan` (partial, `status <> 'PENDING'`), `uq_orders_client_order_id` and `uq_orders_algo_client_id` (partial), 12 named `fk_*` RESTRICT foreign keys; full reversible downgrade (upgrade, downgrade to 0003 and upgrade again verified on an empty database).
- Triggers: `reject_append_only_mutation()` bound by `trg_<table>_append_only` (row UPDATE/DELETE) and `trg_<table>_no_truncate` (statement) on three tables; `reject_terminal_status_change(column, terminal...)` bound by `trg_<table>_terminal_status` on six tables, comparing old/new through `to_jsonb`.
- New tables `plan_constraint_snapshots` (PK/FK to the plan, NOT NULL `margin_type`/`leverage`/`equity_used` with the UNKNOWN sentinel, sha256 hex CHECK, `COMPLETE` forbids sentinels, `working_type` limited to MARK_PRICE) and `system_state_events` (state key set, version >= 1, UNIQUE(key, version), FK to the journal event).
- ORM parity: `PlanConstraintSnapshotRow`, `SystemStateEventRow`, exact-name constraints on every operational table, the 18 pre-existing indexes declared plainly; new 0004 objects use `ddl_if(dialect="postgresql")` so the SQLite suites (analytics, mappers, collector, metadata) are unchanged. `alembic.autogenerate.compare_metadata` against a freshly migrated database returns 0 differences (checked ad hoc; the permanent parity test is plan 07).
- Metadata guard: `METADATA_TEXT_MAX_LEN` is derived from `SymbolMetadata` column lengths (32); TRADIFI_PERPETUAL and TRADING_CANCEL_ONLY are accepted, an overlong (33 characters) value still raises.

## Task Commits

1. **Task 1 RED** `c9d7ee0` (test) - enum/constraint/width tests, metadata tests; about 55 failures, the allowed-insert cases passed
2. **Task 1 GREEN** `3a9272b` (feat) - widths, CHECKs, indexes, FKs, ORM parity, metadata guard
3. **Task 2 RED** `25597cf` (test) - trigger/snapshot/state tests; collection error (`PlanConstraintSnapshotRow` missing)
4. **Task 2 GREEN** `ab3b110` (feat) - triggers, two tables, ORM rows

**Plan metadata:** docs commit follows this SUMMARY (STATE.md, ROADMAP.md, REQUIREMENTS.md).

## Decisions Made

- positions.quantity has no sign CHECK (signed exchange amounts); recorded as the C4 refinement for D051 (plan 15).
- Terminal sets as listed in key-decisions; plan 10 cross-checks them with `src/domain/transitions.py`.
- No CHECK on `orders.order_role` or `trade_plans.quantization_decision` (research A3).

## Deviations from Plan

### Auto-fixed Issues

None for production code. Minor test-structure notes:

**1. [Rule 3 - Blocking structure] Shared row builders live in `tests/support/pg_rows.py`**
- **Issue:** the three PG test modules and `test_persistence_*` need the same ORM row builders and a DB-error assertion helper; the plan listed only the three test modules.
- **Fix:** added `tests/support/pg_rows.py` (builders, `insert_and_commit`, `seed_chain`, `expect_db_error` reading `diag.constraint_name`/`sqlstate`). Rows are built directly instead of through the domain mappers because several tests must send values the domain constructors refuse (zero stop-loss, out-of-enum status).
- **Commit:** c9d7ee0

**2. [Rule 1 - Spec precision] TRUNCATE tests use CASCADE**
- **Issue:** a plain `TRUNCATE journal_events` is refused by PostgreSQL for the referencing foreign key from `system_state_events`, which could hide a missing trigger.
- **Fix:** tests run `TRUNCATE TABLE <t> CASCADE` and assert the "append-only ... TRUNCATE" message; a separate `pg_trigger` test asserts both triggers exist and are enabled on each table.
- **Commit:** 25597cf

---

**Total deviations:** 2 test-structure notes, no production-code deviations.
**Impact on plan:** none on scope.

## Issues Encountered

- Environment: this shell rejected some long heredocs, so multi-line edits were applied with small scripts kept in the scratchpad (not committed).
- `TEST_DATABASE_URL` for PG modules used the `/postgres` maintenance database; the full-suite run used `/trading_test` because `tests/test_analytics_store.py` refuses URLs not ending in `_test` (same as plan 01).

## Verification Evidence

- `TRADING_CI_STRICT=1 pytest tests/test_persistence_triggers_pg.py tests/test_persistence_constraints_pg.py tests/test_persistence_enum_columns_pg.py tests/test_execution_exactly_once_pg.py tests/test_domain_mappers_pg.py tests/test_pg_fixture_guard.py -q -rs` -> exit 0, zero skips (the five plan modules: 145 passed in 35s on PostgreSQL 17.11).
- SQLite suites (`test_metadata`, `test_domain_mappers`, `test_analytics_store`, `test_analytics_lifecycle`, `test_analytics_cli`, `test_collector`, `test_approval_message`, `test_phase8_audit_reviewfix`) -> all passed after Task 1.
- `mypy src` -> Success, 124 files; `ruff check` -> All checks passed; `ruff format --check src tests` -> 276 files already formatted.
- Acceptance greps: `op.create_check_constraint` = 21 (>= 19); `uq_approvals_one_decided_per_plan` in both models.py and 0004; `ondelete="RESTRICT"` = 14 lines (>= 12); no `METADATA_TEXT_MAX_LEN = 16`; `EXECUTE FUNCTION reject_append_only_mutation` = 6 (>= 3), `reject_terminal_status_change` = 6 (>= 6); both Row classes present; no `EXECUTE PROCEDURE`; 0001-0003 `git diff --exit-code 99d3a94` exit 0.
- Migration cycle (upgrade head, downgrade 0003_callback_mapping, upgrade head) on an empty generated database: ok.
- `pytest -m "not docker" -q -rs` (full suite, `/trading_test` URL, after the last code commit ab3b110) -> exit 0; only skips were environment-only (1 symlinks, 1 NTFS POSIX modes, 8 shellcheck missing).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-17-05 token/decision uniques, T-17-06 append-only triggers, T-17-07 widths and enum CHECKs, T-17-08 terminal triggers, all mitigated and tested). The table owner can still DISABLE TRIGGER; owner-vs-app role separation stays deferred to Phase 26.

## Next Phase Readiness

Plan 03+ can rely on named constraints (`ck_*`, `uq_*`, `fk_*`, `trg_*`), the two new tables and their ORM rows. Plan 07 adds the permanent ORM/migration parity test and the `pg_trigger` assertions; plan 10 cross-checks the terminal sets with `src/domain/transitions.py`; plan 15 records the positions.quantity refinement in D051.

## Self-Check: PASSED

- Created files exist: tests/support/pg_rows.py, tests/test_persistence_constraints_pg.py, tests/test_persistence_enum_columns_pg.py, tests/test_persistence_triggers_pg.py; commits c9d7ee0, 3a9272b, 25597cf, ab3b110 exist (4 commits since dc2a74a).
