---
phase: 17-operational-persistence-layer
plan: 08
subsystem: database
tags: [postgresql, journal, append-only, idempotency, sqlalchemy, safe-mode, pytest]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01 OperationalDatabase/make_sync_engine/pg_db fixtures and typed persistence errors; plan 02 append-only trigger and journal foreign keys; plan 04 deterministic journal ids"
provides:
  - "src/persistence/journal.py PgJournalStore: record(event), append(tx, event), get, list_by_correlation; no update or delete method"
  - "mypy-only conformance of PgJournalStore to the enablement, safe_mode, sweeper, health and kill-gate JournalLike Protocols and to the callback JournalReceipt alias"
  - "tests/test_persistence_journal_pg.py: 21 PostgreSQL tests (round trip, idempotent replay, conflict, unit of work, FK, ordering, append-only trigger, outage, controller wiring)"
  - "tests/test_journal_failure_paths.py: 6 tests pinning controller and emergency-close behavior during a journal outage"
affects: [17-09, 17-10, 17-11, 17-13, phase-18, phase-20, phase-24]

actuals:
  tokens: 8400
  tasks: 2
  commits: 3
plan_head_before: 4a8ae455903b38c762d9b738c6f140bf46700ff2
plan_head_after: 88bfe35272d3807022b54bd3fa4633959a8bc2df

tech-stack:
  added: []
  patterns:
    - "Journal write is INSERT ... ON CONFLICT (journal_event_id) DO NOTHING RETURNING; no row returned means re-read and compare identity fields plus payload"
    - "append(tx, event) joins a caller-owned unit of work; record(event) is append in its own transaction"
    - "TYPE_CHECKING-only conformance function returns the store as each consumer's own Protocol, so mypy catches surface drift without a new Protocol"

key-files:
  created:
    - src/persistence/journal.py
    - tests/test_persistence_journal_pg.py
    - tests/test_journal_failure_paths.py
  modified: []

key-decisions:
  - "Conflict rule compares event_type, entity_type, entity_id, correlation_id, the five linkage ids and payload_json; occurred_at_utc and created_at_utc are excluded so a redelivered callback with a new delivery time is a no-op that keeps the first row"
  - "JournalConflict messages carry the event id and differing field NAMES only, never payload contents"
  - "A failed append inside a caller's unit of work is not wrapped in a savepoint: the exception propagates and the whole unit of work rolls back"
  - "Failure paths are pinned, not fixed: F-702 and the emergency-close outage gap are Phase 20"

patterns-established:
  - "Plain TRUNCATE on journal_events is refused by the foreign-key guard before the trigger runs; trigger tests must use TRUNCATE ... CASCADE"

requirements-completed: [DOMN-01]

coverage:
  - id: D1
    description: "PgJournalStore round-trips events through journal_to_row/journal_from_row; record is idempotent by id; a replay with a later occurred_at_utc is a no-op that keeps the first timestamp; two callback receipts for one cbq correlation produce one row"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_record_then_get_round_trips"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_replay_with_a_later_delivery_time_is_a_noop_and_keeps_the_first"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_callback_receipts_with_different_delivery_times_produce_one_row"
        status: pass
    human_judgment: false
  - id: D2
    description: "The same id with a different payload or entity raises JournalConflict naming only field names, and the stored row is unchanged"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_same_id_with_a_different_payload_raises_and_leaves_the_row_unchanged"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_same_id_with_a_different_entity_names_the_differing_fields"
        status: pass
    human_judgment: false
  - id: D3
    description: "append(tx, event) commits or rolls back with the caller's work; a missing parent raises ParentRowMissing; parents inserted first succeed; an unreachable database raises StoreUnavailable without the password"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_append_rolls_back_together_with_the_caller_work"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_missing_parent_raises_parent_row_missing"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_an_unreachable_database_raises_store_unavailable"
        status: pass
    human_judgment: false
  - id: D4
    description: "The store has no update or delete method and the trigger refuses UPDATE, DELETE and TRUNCATE from a bypassing writer; LiveEnablementController, SafeModeController and OrphanSweeper write rows through the store with no signature change"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_a_bypassing_writer_is_refused_by_the_trigger"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_enablement_controller_writes_rows_through_the_store"
        status: pass
      - kind: integration
        ref: "tests/test_persistence_journal_pg.py#test_orphan_sweeper_pre_cancel_event_is_a_row_in_the_store"
        status: pass
    human_judgment: false
  - id: D5
    description: "Controller behavior during a journal outage is explicit and pinned (SAFE_MODE survives, disable stays enabled, cancels are not issued)"
    requirement: DOMN-01
    verification:
      - kind: unit
        ref: "tests/test_journal_failure_paths.py"
        status: pass
    human_judgment: true
    rationale: "The pinned behaviors are tested, but whether they are acceptable (two are unsafe in an outage) is a Phase 20 design decision"

duration: 30min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 08: PostgreSQL journal store Summary

**`PgJournalStore` is a durable, append-only, replay-idempotent journal that every existing journal-first controller and the Telegram callback receipt use unchanged; a different event under an existing id raises `JournalConflict` instead of being dropped, and the behavior of those controllers during a journal outage is now pinned by tests (two of the pinned behaviors are unsafe and are handed to Phase 20).**

## Performance

- **Duration:** about 30 min (includes one full-suite run of about 12 min)
- **Completed:** 2026-10-01
- **Tasks:** 2 (Task 1 TDD RED then GREEN; Task 2 is characterization of existing behavior with no production change)
- **Files:** 3 created, 0 modified

## Accomplishments

- `PgJournalStore.record(event)` commits one event in its own transaction; `append(tx, event)` writes inside a caller-owned unit of work. The insert is `ON CONFLICT (journal_event_id) DO NOTHING RETURNING`; when nothing is inserted the existing row is re-read and compared on the identity fields and payload. Same identity and payload (any delivery time) is a no-op that keeps the first row; anything else raises `JournalConflict` naming the id and field names only (T-17-20, T-17-21).
- Conversion goes through `journal_to_row` / `journal_from_row`, so the mappers now have a production caller (F-202).
- A foreign-key violation (SQLSTATE 23503) becomes `ParentRowMissing`; an unreachable database surfaces as `StoreUnavailable` from the unit of work with no password in the message.
- Public surface is exactly `record`, `append`, `get`, `list_by_correlation` (asserted by a test); the append-only trigger refuses a bypassing UPDATE, DELETE or TRUNCATE.
- A `TYPE_CHECKING`-only function returns the store as the enablement, safe_mode, sweeper, health and kill-gate `JournalLike` types and `store.record` as `JournalReceipt`; `mypy src` fails if any surface drifts. No new Protocol was invented.
- `LiveEnablementController`, `SafeModeController` and `OrphanSweeper` (pre and post cancel events) all write rows through the store in tests, and two redelivered `cbq:` callback receipts produce one row.

## Task Commits

1. **Task 1 RED:** `766d77c` test(17-08): RED for PgJournalStore (module import fails: `No module named 'src.persistence.journal'`)
2. **Task 1 GREEN:** `21606cb` feat(17-08): PgJournalStore with idempotent-by-id writes, conflict detection and FK/outage mapping
3. **Task 2:** `88bfe35` test(17-08): pin journal-first controller behavior when the journal raises StoreUnavailable

Task 2 changes no production code, so there is no RED commit: the tests characterize behavior that already exists and pass on first run (mutation of the controllers is out of scope).

## Task 2: pinned behaviors (journal raises `StoreUnavailable`)

| # | Behavior pinned today | Safe in an outage? | Owner |
|---|----------------------|--------------------|-------|
| 1 | `SafeModeController.enter_safe_mode` sets `in_safe_mode` BEFORE journaling, then the `StoreUnavailable` propagates; SAFE_MODE survives and `guard_new_entries` blocks | Yes | pinned |
| 2 | `LiveEnablementController.disable` journals first; with a failing journal it raises and the controller STAYS ENABLED (F-702) | No | Phase 20 (F-702) |
| 3 | `expire_pending_entry` and `cancel_untriggered_protectives` journal the pre-image BEFORE the exchange call; with a failing journal no cancel is issued, and `cancel_untriggered_protectives` raises the bare `StoreUnavailable` on leg 1 (its pre-image write is outside the per-leg isolation) so SL/TP1/TP2 are all skipped | No | Phase 20 |
| 4 | `emergency_manual_close` with a failing journal still runs all four steps (each failure collected in one `ExceptionGroup` of four `StoreUnavailable`), enters SAFE_MODE, but leaves live orders enabled and issues ZERO exchange cancels | No | Phase 20 |

The plan expected behavior 4 to "still run its isolated exchange steps against a fake adapter (each step's call is recorded)". That expectation is false: the steps run, but their exchange calls are never reached because each one journals first. This is the unsafe-difference case the plan says to report instead of fixing, so controller code is unchanged and the test documents it in its module docstring. A control test shows all four cancels are issued once the journal is healthy.

## Verification (real outputs)

- `TRADING_CI_STRICT=1 pytest tests/test_persistence_journal_pg.py -x -q -rs -p no:cacheprovider` (with `TEST_DATABASE_URL`): 21 passed, no SKIPPED lines.
- `pytest tests/test_journal_failure_paths.py tests/test_execution_emergency.py tests/test_reconcile.py tests/test_execution_enablement.py -x -q`: all passed (31 tests).
- `mypy src`: Success, no issues in 127 source files. `ruff check`: All checks passed. `ruff format --check src tests`: 287 files already formatted.
- Full suite `pytest -m "not docker" -q -p no:cacheprovider -x` with `TEST_DATABASE_URL` exported: reached 100%, exit code 0.
- Acceptance criteria: `on_conflict_do_nothing(index_elements=["journal_event_id"])` present once (src/persistence/journal.py:103); `grep -nE "def (update|delete)"` prints nothing; `TYPE_CHECKING` present (lines 36 and 156); `StoreUnavailable` appears 12 times in tests/test_journal_failure_paths.py.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test used plain TRUNCATE, which the foreign-key guard refuses before the trigger fires**
- **Found during:** Task 1 GREEN
- **Issue:** `TRUNCATE journal_events` raised `FeatureNotSupported` (system_state_events references the table) so the "append-only" trigger message was never asserted for the TRUNCATE case.
- **Fix:** the test uses `TRUNCATE journal_events CASCADE`, the form the existing trigger tests use, so the append-only trigger is what refuses it.
- **Files modified:** tests/test_persistence_journal_pg.py
- **Commit:** 21606cb

**2. [Plan expectation corrected] emergency_manual_close does not reach the exchange during a journal outage** (see Task 2 table). Reported, not fixed, per the plan's instruction.

**Total deviations:** 1 auto-fixed (test bug), 1 plan expectation found false and reported. **Impact:** no production code outside `src/persistence/journal.py` changed.

## Issues Encountered

- `ruff format --check` with no path argument (the plan's verify form) still reports `17-RESEARCH.md` as unformatted. This is the pre-existing item already recorded in `deferred-items.md` under plan 17-01; `ruff format --check src tests` is clean.

## Known Stubs

None.

## Threat Flags

None. The store adds no network endpoint or auth path; it writes the existing `journal_events` table behind the existing trigger. Threat-register mitigations applied: T-17-20 (conflict re-read and `JournalConflict`), T-17-21 (field names only in messages, URLs never rendered), T-17-22 (distinct `StoreUnavailable`; SAFE_MODE-before-journaling pinned; F-702 pinned and left to Phase 20).

## Next Phase Readiness

Ready for the next Phase 17 plan. Plans that insert a journal event together with its subject row should call `PgJournalStore.append(tx, event)` inside `OperationalDatabase.transaction()` after inserting parents. Phase 20 owns the three unsafe outage behaviors in the table above (disable must flip before or independently of journaling; emergency close must reach the exchange even when the journal is down; `cancel_untriggered_protectives` must isolate the pre-image write per leg). The controllers are not wired to PostgreSQL in production until Phase 24.

## Self-Check: PASSED

- FOUND: src/persistence/journal.py, tests/test_persistence_journal_pg.py, tests/test_journal_failure_paths.py
- FOUND commits: 766d77c, 21606cb, 88bfe35
