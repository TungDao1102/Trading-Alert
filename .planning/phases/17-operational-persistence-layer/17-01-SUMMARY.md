---
phase: 17-operational-persistence-layer
plan: 01
subsystem: database
tags: [postgresql, sqlalchemy, alembic, psycopg, write-ahead-intent, exactly-once, pytest]

requires:
  - phase: 09-live-execution
    provides: execute_approved_plan, deterministic client ids (order_ids.py), ExecutionAdapter surface
  - phase: 08-approval-binding
    provides: check_binding_full, approvals table, short-id mapping
provides:
  - "Durable approval consumption: ENTRY execution intent written ahead of place_entry, one transaction with the approvals stamp"
  - "src/persistence package (engine UTC-pinned fail-closed, OperationalDatabase.transaction, typed errors, PgExecutionStateStore)"
  - "ExecutionIntentStore Protocol (stdlib-only) with required intent_store argument on execute_approved_plan"
  - "Migration 0004_persistence_integrity first slice (approvals.consumption_status/consumed_at_utc, execution_intents)"
  - "Disposable-database test fixtures (t17_<hex>_test clones of an alembic-built template) with strict-skip canary"
  - "BinanceSemanticsFakeAdapter (clientOrderId unique only among open orders) reused unchanged by plans 12 and 14"
affects: [17-02, 17-03, 17-11, 17-12, 17-14, phase-18, phase-20, phase-24]

actuals:
  tokens: 23600
  tasks: 3
  commits: 3
plan_head_before: 14b0eb8f8927358e73e8d7c4865b0d95ff578abb
plan_head_after: 0c58ee4c1014a724be92d0db1db4e3e772c36a25

tech-stack:
  added: []
  patterns:
    - "Write-ahead intent: commit INTENDED (with approval consume) -> SENT -> place -> ACKED/REJECTED/UNKNOWN -> finalize outcome"
    - "INSERT ... ON CONFLICT (approval_id, role) DO NOTHING RETURNING with a named arbiter, never untargeted"
    - "Conditional UPDATE guarded by allowed predecessor statuses; rowcount 0 raises IntentStateConflict"
    - "PostgreSQL-only constraints declared on ORM tables with ddl_if(dialect=postgresql) so SQLite create_all suites keep pre-0004 DDL"
    - "Template-database clone per test (journal append-only in plan 02 makes row cleanup impossible)"

key-files:
  created:
    - src/db/alembic/versions/0004_persistence_integrity.py
    - src/persistence/__init__.py
    - src/persistence/engine.py
    - src/persistence/uow.py
    - src/persistence/errors.py
    - src/persistence/execution_state.py
    - src/execution/intent_store.py
    - tests/pg_support.py
    - tests/support/__init__.py
    - tests/support/fake_binance_exchange.py
    - tests/support/intent_store_fakes.py
    - tests/test_execution_exactly_once_pg.py
    - tests/test_pg_fixture_guard.py
  modified:
    - src/db/models.py
    - src/domain/enums.py
    - src/execution/manager.py
    - tests/conftest.py
    - tests/test_execution_manager.py
    - tests/test_domain_mappers_pg.py

key-decisions:
  - "Task 1 checkpoint:decision auto-resolved (auto mode) to option 'locked': sync repositories (D-01) and execution_intents PK (approval_id, role) (D-13) with research corrections C2 (OrderRole role values), C8 (explicit consumption_status), Open Q5 (UNIQUE(trade_plan_id, role)); listed for D051 (plan 15)"
  - "Pre-placement NO_TRADE never consumes the approval; consumption happens only immediately before placement (Open Q1)"
  - "Manager stays SQLAlchemy-free: depends on the ExecutionIntentStore Protocol, store called synchronously on the event loop (documented tradeoff, Phase 24 may wrap in asyncio.to_thread)"
  - "Stored-outcome lookup sits right after Gate 1b in this plan; plan 11 moves it ahead of the expiry gate (Open Q2)"

patterns-established:
  - "Test doubles for production Protocols live under tests/support, never in src (no in-memory fallback, T-17-04)"
  - "Never assert inside a fake adapter hook: the manager swallows Exception from place_entry; record observations and assert afterwards"

requirements-completed: [EXEC-03, APRV-02, DOMN-01]

coverage:
  - id: D1
    description: "Second execute_approved_plan call for the same approval (after the entry FILLED, after CANCEL, and across a fresh engine/store restart) places exactly one entry and leaves exactly one ENTRY intent row; replay makes zero adapter calls"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_double_call_after_fill_places_exactly_one_entry"
        status: pass
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_replay_after_cancel_places_exactly_one_entry"
        status: pass
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_restart_returns_stored_outcome_with_zero_adapter_calls"
        status: pass
    human_judgment: false
  - id: D2
    description: "Write-ahead row is committed (visible to a second connection as SENT) before place_entry runs; approval stamped CONSUMED with consumed_at_utc in the same transaction"
    requirement: APRV-02
    verification:
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_double_call_after_fill_places_exactly_one_entry"
        status: pass
    human_judgment: false
  - id: D3
    description: "Negative control: a never-remembering intent store yields two place_entry calls, proving the fake models Binance open-orders-only clientOrderId uniqueness (F-126)"
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_execution_exactly_once_pg.py#test_negative_control_never_remembering_store_places_two_entries"
        status: pass
    human_judgment: false
  - id: D4
    description: "Disposable generated databases only (t17_<hex>_test), schema from alembic upgrade head, strict-mode canary: missing TEST_DATABASE_URL fails under TRADING_CI_STRICT=1 and skips locally"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_pg_fixture_guard.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Migration 0004 first slice (approvals consumption columns + execution_intents with named CHECK/FK/unique objects) applied by alembic on PostgreSQL 17.11"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_pg_db_is_a_generated_migrated_database"
        status: pass
    human_judgment: false

duration: 22min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 01: Durable approval consumption and write-ahead ENTRY intent Summary

**A replayed or redelivered APPROVE can no longer place a second entry: `execute_approved_plan` commits an ENTRY execution intent (and stamps the approval CONSUMED) in one PostgreSQL transaction before `place_entry`, so replays and restarts return the stored outcome with zero adapter calls, proven against a fake that reuses a client id once the first entry is FILLED or CANCELED.**

## Performance

- **Duration:** 22 min (includes an 11m46s full-suite run)
- **Started:** 2026-10-01T12:07:22Z
- **Completed:** 2026-10-01
- **Tasks:** 3 (Task 1 decision gate auto-resolved, Task 2 tracer RED+GREEN, Task 3 guard + mapper rebuild)
- **Files modified:** 19 (13 created, 6 modified; 2335 insertions, 90 deletions under src/ and tests/)

## Accomplishments

- Write-ahead exactly-once entry (EXEC-03, F-126): ENTRY intent INTENDED + approval CONSUMED commit together via `INSERT ... ON CONFLICT (approval_id, role) DO NOTHING RETURNING` (targeted arbiter); `mark_sent` is committed before `place_entry`; result and exact `ExecutionOutcome` fields are persisted so replay returns them with zero adapter calls, also from a brand-new engine/store.
- `src/persistence` foundation: `make_sync_engine` pins `timezone=UTC` and `lock_timeout` per connection, `pool_pre_ping`, refuses any driver but psycopg 3 and raises `StoreUnavailable` (type name plus password-hidden URL only) instead of degrading; `OperationalDatabase.transaction()` is the unit of work; 8 typed errors pre-declared for plans 08-13.
- Migration `0004_persistence_integrity` (first slice, hand-written, no project imports, 0001-0003 byte-identical): `approvals.consumption_status/consumed_at_utc` with two named CHECKs, `execution_intents` with PK, plan-level unique, partial unique client ids, RESTRICT FKs and six named CHECKs.
- Test infrastructure: template-database clone fixtures with generated, regex-validated names, strict-skip canary, `BinanceSemanticsFakeAdapter` (-4116 only among open orders, fill/cancel free the id, order-by-client history with retention), in-memory and never-remembering intent stores, destructive mapper PG test rebuilt on `pg_db` with an FK-safe parent chain.

## Task Commits

1. **Task 1: Confirm the one-way persistence contract** - no commit (checkpoint:decision, auto-mode resolution `locked`, recorded above and in key-decisions for D051)
2. **Task 2: Tracer (TDD)**
   - RED: `8d72536` (test) - fixtures, fake, tracer test; failed at collection (`ModuleNotFoundError: src.persistence`)
   - GREEN: `d4833f9` (feat) - migration, models, persistence package, Protocol, manager wiring
3. **Task 3: Fixture guard and mapper rebuild** - `0c58ee4` (test)

**Plan metadata:** docs commit follows this SUMMARY (STATE.md, ROADMAP.md, REQUIREMENTS.md).

_No REFACTOR commit: nothing to restructure after GREEN._

## Files Created/Modified

- `src/execution/intent_store.py` - `ExecutionIntentStore` Protocol, `IntentRecord`, `RecordedOutcome`, shared `ALLOWED_PREDECESSORS` (stdlib + domain only)
- `src/persistence/execution_state.py` - `PgExecutionStateStore`: consume, `mark_sent`, `record_result`, `finalize_entry_outcome`, `get_entry`
- `src/persistence/{engine,uow,errors,__init__}.py` - UTC-pinned fail-closed engine, unit of work, typed errors, module map
- `src/db/alembic/versions/0004_persistence_integrity.py` - first slice of migration 0004
- `src/db/models.py` - `ApprovalRow` consumption columns, `ExecutionIntentRow`; PostgreSQL-only constraints via `ddl_if`
- `src/domain/enums.py` - `ExecutionIntentStatus`, `ApprovalConsumptionStatus`, `LiveInputsStatus`, `SystemStateKey`
- `src/execution/manager.py` - required `intent_store`, replay lookup after Gate 1b, consume before placement, `mark_sent`, `record_result`, `_finish` finalizer, `_stored_entry_outcome`
- `tests/pg_support.py`, `tests/conftest.py` - disposable DB fixtures (explicit fixture import)
- `tests/support/*` - Binance-semantics fake and intent-store doubles
- `tests/test_execution_exactly_once_pg.py`, `tests/test_pg_fixture_guard.py`, `tests/test_domain_mappers_pg.py` - tracer + negative control, guard/canary, rebuilt mapper PG tests
- `tests/test_execution_manager.py` - `_live_wiring()` supplies a fresh `InMemoryExecutionIntentStore`

## Decisions Made

- Task 1 resolved to `locked` in auto mode (see key-decisions); one-way door recorded for D051.
- Consumption only immediately before placement; a pre-placement NO_TRADE leaves the approval retryable until expiry (research Open Q1, to be recorded in D051).
- `ExecutionOutcome` persisted as two columns plus explicit `outcome_recorded`; an ENTRY row without a recorded outcome replays as `RECONCILIATION_REQUIRED` (fail closed, never re-sent).
- `ALLOWED_PREDECESSORS` lives next to the Protocol so the PG store and the in-memory double enforce identical transitions; plan 11 swaps it for `src/domain/transitions.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Exchange identity captured for the ACKED record**
- **Found during:** Task 2
- **Issue:** `_place_entry_no_blind_retry` returned only a state string, so `record_result(ACKED)` could not persist the exchange order id/status that reconciliation (Phase 20) keys on.
- **Fix:** Private return type changed to a frozen `_EntryPlacement(state, exchange_order_id, exchange_status)`; the function is private and only used inside `manager.py`.
- **Files modified:** src/execution/manager.py
- **Verification:** `tests/test_execution_manager.py` (38 tests) and the tracer pass; row shows ACKED.
- **Committed in:** d4833f9

**2. [Rule 1 - Spec precision] Fake order-by-client retention narrowed to the documented rule**
- **Found during:** Task 2
- **Issue:** Plan text says history older than 3 days reports `found=False`. The Binance Query Order rule is narrower: a CANCELED/EXPIRED order with NO fill older than 3 days is not found; filled orders stay findable (research Pitfall 11).
- **Fix:** `_visible_history` hides only canceled-without-fill records older than `HISTORY_RETENTION` (3 days) relative to the injectable fake clock. EXPIRED is not modeled (the fake only has FILLED/CANCELED).
- **Files modified:** tests/support/fake_binance_exchange.py
- **Committed in:** 8d72536

### Environment / verification deviations (not code)

- **Protected-branch guard:** HEAD is `master`, which the executor's protected-branch assertion normally refuses. The dispatch explicitly directed commits on `master` (sequential mode, `branching_strategy: none`, prior planning commits already on master), so commits were made there; `.planning/config.json` was not changed. Flagged for the orchestrator.
- **TEST_DATABASE_URL:** the operator URL names the `postgres` maintenance database as designed. The pre-existing `tests/test_analytics_store.py::test_pg_append_and_reread_one_kill_gate_event` refuses any URL whose database does not end in `_test` (it runs `create_all`/`drop_all`). The plan-level full-suite run therefore used `.../trading_test` (as CI does); the three PG modules of this plan were verified under both URLs.
- **`ruff format --check` at repo root exits non-zero for a pre-existing reason:** this ruff version also formats Markdown code blocks and flags `.planning/phases/17-operational-persistence-layer/17-RESEARCH.md` (committed in 99d3a94, not touched by this plan). `ruff format --check src tests` is clean (272 files). Logged in `deferred-items.md`; CI's lint job will fail on that file until the research doc or the ruff config is adjusted.

---

**Total deviations:** 2 auto-fixed (1 Rule 2, 1 Rule 1) plus 3 environment notes.
**Impact on plan:** No scope creep; both code deviations are internal to this plan's files.

## Issues Encountered

- A first full-suite run exceeded the 10-minute foreground limit and was moved to the background; it completed green (11m46s) on the code of commit `d4833f9`. Task 3 test files were verified afterwards by the three-module strict run (40 passed, zero skips).
- TDD note for Task 3: its guard helpers already existed from Task 2, so the new tests passed on first run. To prove they bite, the name-guard regex was temporarily loosened and the guard tests failed (5 failures: `trading_test`, `x_t17_ab12_test`, `t17_AB12_test`, `t17_xyz_test`, `t17__test`), then restored.

## Verification Evidence

- `TRADING_CI_STRICT=1 pytest tests/test_execution_exactly_once_pg.py tests/test_pg_fixture_guard.py tests/test_domain_mappers_pg.py -q -rs` -> 40 passed, 0 skipped (PostgreSQL 17.11 Docker, `/postgres` maintenance URL).
- `pytest tests/test_execution_manager.py tests/test_domain_mappers.py tests/test_analytics_store.py` -> all passed (with `/trading_test`).
- `pytest -m "not docker" -rs` (full suite, `/trading_test`) -> exit 0; only skips were environment-only (symlinks, NTFS POSIX modes, 8x shellcheck missing).
- `mypy src` -> Success, 124 files. `ruff check` -> All checks passed. `ruff format --check src tests` -> 272 files already formatted.
- Without `TEST_DATABASE_URL`: guard tests skip loudly locally; with `TRADING_CI_STRICT=1` they fail (canary + fixtures).
- Leftover databases after runs: none (`pg_database` lists only postgres, template0/1, trading, trading_test).
- Acceptance greps: all pass (down_revision line, no project imports in 0004, `on_conflict_do_nothing(index_elements` present, no sqlalchemy import in manager/intent_store, signature line present and no `= None` default, 0 `create_all|drop_all` in `tests/pg_support.py` and `test_domain_mappers_pg.py`, negative-control test present, 0001-0003 byte-identical vs 99d3a94).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-17-01..04 mitigated: targeted ON CONFLICT + committed write-ahead row, generated-name regex guard, hide_password messages, `StoreUnavailable` with no in-memory fallback).

## Next Phase Readiness

Plan 02 can extend the same `0004_persistence_integrity` revision (the first slice is in place; ORM/migration parity test lands in plan 07) and reuse `pg_db`, `pg_empty_db`, `OperationalDatabase` and the pre-declared error classes. Plans 11, 12 and 14 can reuse `BinanceSemanticsFakeAdapter` unchanged.

## Self-Check: PASSED

- All 13 created files exist on disk; commits `8d72536`, `d4833f9`, `0c58ee4` exist (3 commits match `--grep=17-01`).
- Task acceptance criteria and plan-level verification re-run after the last code commit (results in Verification Evidence).
