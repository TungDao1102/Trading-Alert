---
phase: 20-reconcile-safe-mode-hardening
plan: 03
subsystem: execution-persistence
tags: [execution-intents, reconciliation, alembic, postgres, tdd]
requires:
  - phase: 17
    provides: ExecutionIntentStore Protocol, PgExecutionStateStore, execution_intents table
  - phase: 19
    provides: migration 0006_approval_quantity (down_revision of 0007)
provides:
  - "ExecutionIntentStore.finalize_reconciled_resolution (T-B option 2, D-11)"
  - "execution_intents.resolution_reason_code (migration 0007_intent_resolution_reason)"
  - "RESOLUTION_RECONCILED_ABSENT, RESOLUTION_NEVER_SENT, RESOLUTION_REASON_CODES, required_source_status"
affects: [20-10 UNKNOWN-entry protocol, reconcile]
tech-stack:
  added: []
  patterns: [dedicated reconciliation-finalization API, one shared store contract test class]
key-files:
  created:
    - src/db/alembic/versions/0007_intent_resolution_reason.py
    - tests/test_intent_result_contract.py
    - tests/test_intent_result_contract_pg.py
  modified:
    - src/db/models.py
    - src/execution/intent_store.py
    - src/persistence/execution_state.py
    - tests/support/intent_store_fakes.py
    - tests/test_persistence_migration_pg.py
    - docs/data/DATA_MODEL.md
key-decisions:
  - "Option 2 of T-B: a dedicated finalize_reconciled_resolution API and its own column; record_result is untouched."
  - "The closed reason set maps each code to its only legal source status in one place (required_source_status), used by both stores."
requirements: [EXEC-02]
status: complete
estimate:
  tokens: 85000
actuals:
  tokens: 13000
  tasks: 3
  commits: 5
plan_head_before: 9d8a9b0e6b4b532b525c64424dd37bebb0b679d7
plan_head_after: be5aa34e9966a1861d8c11448c8d4f1c57c863d9
completed: 2026-10-21
---

# Phase 20 Plan 03: Reconciliation result API Summary

A reconciled absence (UNKNOWN to REJECTED, `RECONCILED_ABSENT`) or a never-sent intent (INTENDED to REJECTED, `NEVER_SENT`) is now stored through its own method and its own nullable column, so it can never be confused with a Binance rejection; `record_result` keeps its exact signature and meaning.

`actuals.tokens` is chars/4 over the added lines of the diff (about 1,100 lines), the same scale as the estimate. The estimate (85,000) was a planning figure for a low-confidence plan; the work needed far less.

## What was built

- Migration `0007_intent_resolution_reason` (down_revision `0006_approval_quantity`, verified as the head in this checkout): `execution_intents.resolution_reason_code VARCHAR(32) NULL` plus the named CHECK `ck_execution_intents_resolution_reason` (NULL, or REJECTED with one of the two codes). Hand-written, imports no project module, real downgrade, no backfill. Mirrored on `ExecutionIntentRow` (CHECK under `ddl_if postgresql`).
- `src/execution/intent_store.py`: the two code constants, `RESOLUTION_REASON_CODES`, `required_source_status` (code to its only legal source status, `ValueError` for any other code), `IntentRecord.resolution_reason_code: str | None = None`, and the Protocol method.
- `PgExecutionStateStore.finalize_reconciled_resolution`: validates the code before any database access, reads the row `FOR UPDATE`, accepts an identical repeat as a no-op, refuses every other source status or a different code with `IntentStateConflict`, runs `assert_transition`, writes REJECTED, the code, `exchange_status = NULL`, `exchange_order_id = NULL`, `resolved_at_utc = now_utc`. `_to_record` maps the column.
- Test doubles: `InMemoryExecutionIntentStore` applies the same rules; `AlwaysWinsIntentStore` returns None; `CrashAfter` has a new `reconcile` step; `FailingIntentStore` can fail the method (optionally by role); `BarrierBeforeConsume` got explicit delegates for the whole Protocol (see deviations).
- `tests/test_intent_result_contract.py` holds `IntentResultContract` (not collected itself) and the in-memory run; `tests/test_intent_result_contract_pg.py` runs the same class against `PgExecutionStateStore` and adds database-only proofs (column in the catalog, CHECK refusals and acceptances, the 0004 terminal trigger still blocking a move of a closed row).
- `docs/data/DATA_MODEL.md` section 2.14 documents the column, the two codes, the single writer and revision 0007. `docs/DECISIONS.md` is untouched.

## record_result call sites (T-B compatibility check)

None of these lines or their arguments changed; no file listed below appears in the diff except where noted:

- `src/execution/intent_recovery.py:157` - unchanged (file not in the diff)
- `src/execution/manager.py:1119`, `:1155`, `:1169`, `:1184`, `:1812` - unchanged (file not in the diff)
- `src/execution/protection.py:778`, `:1270`, `:1283` - unchanged (file not in the diff)
- `src/persistence/execution_state.py` `record_result` definition - unchanged (the new method sits next to it)
- `scripts/`: no `record_result` call exists; `scripts/demo_rehearsal.py` is not edited
- `tests/support/intent_store_fakes.py`: the three delegating `record_result` calls in the wrappers are unchanged

## TDD record

Task 1: RED `b36ed11e` (collection ImportError for the PG contract, six migration tests failing, seen before the GREEN commit), GREEN `e8f64f7e`. Task 2: RED `5b58b57e` (in-memory contract and fake Protocol checks failing), GREEN `a22434c4`. Task 3 (docs) `be5aa34e`.

## Verification actually run

- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_intent_result_contract_pg.py tests/test_persistence_migration_pg.py` : all passed, none skipped, on the local PostgreSQL via the harness template database.
- `uv run pytest -m "not docker" tests/test_intent_result_contract.py tests/test_intent_recovery.py tests/test_execution_write_ahead_pg.py` : all passed.
- Consumers of the changed fakes, run beyond the plan's list because the fakes are shared: `tests/test_execution_manager.py`, `tests/test_execution_exactly_once_pg.py`, `tests/test_intent_recovery_pg.py`, `tests/test_protection_coordinator.py` (strict mode): all passed.
- `uv run ruff check`, `uv run ruff format --check` (673 files), `uv run mypy src` (215 files), `uv run python scripts/verify_decision_alignment.py all` (ALL_PASS): clean.
- The full suite was not run (orchestrator's job). `pyproject.toml` and `uv.lock` are untouched.

## Deviations from Plan

**1. [Rule 1 - Bug] Existing downgrade test pinned a single removed column**
- **Found during:** Task 1 (first GREEN run)
- **Issue:** `test_downgrade_0005_keeps_rows_and_removes_only_the_column` downgrades from head to 0004, which now also drops `resolution_reason_code`.
- **Fix:** the expected difference is now both columns, with a comment. The 0006 downgrade test targets `approvals` and needed no change.
- **Files modified:** tests/test_persistence_migration_pg.py. **Commit:** e8f64f7e

**2. [Rule 3 - Blocking] BarrierBeforeConsume never satisfied the runtime_checkable Protocol**
- **Found during:** Task 2 (the plan's acceptance criterion asks for an isinstance test on all five fakes)
- **Issue:** on Python 3.12+ `isinstance` against a `runtime_checkable` Protocol looks attributes up statically, so the wrapper's `__getattr__` delegation does not count. The plan's wording ("keep passing") assumed it did; it did not, for any Protocol method.
- **Fix:** explicit delegating methods for the whole Protocol on `BarrierBeforeConsume`; `__getattr__` stays for test-side extras such as `get_intent`.
- **Files modified:** tests/support/intent_store_fakes.py. **Commit:** a22434c4

**3. Worktree base predates the Phase 20 documents (process, not code)**
- The worktree was created at 9d8a9b0e, before the Phase 20 plan documents existed. The plan, `20-REVIEW-RESOLUTIONS.md` and `20-CONTEXT.md` were read from `develop` with `git show` (the plan version at develop's tip is byte-identical to the one first read at e1feed22; the resolutions and context files do not differ between those two refs). The base was not changed. Nothing built differs from those versions. Migration 0006 was verified as the head in this checkout.

## Known Stubs

None.

## Threat Flags

None. T-20-06 and T-20-07 are mitigated as the plan states (source status under the row lock, closed code set, CHECK tied to REJECTED, NULL reason for exchange rejections); T-20-SC: no dependency added.

## Notes for consumers (plan 20-10)

- Call `finalize_reconciled_resolution(approval_id=..., role=..., reason_code=..., now_utc=...)` only after the D-11 evidence conditions hold; the store enforces the status precondition, not the evidence.
- The method is not wired to any production caller yet; it does not touch `outcome_*`, the protection registry, SAFE_MODE or intent recovery. The old 3-day REJECTED rule in `resolve_unresolved_intents` is untouched here (plan 20-10).

## Self-Check: PASSED

Files exist (migration, both new test files, summary), the five task commits `b36ed11e`, `e8f64f7e`, `5b58b57e`, `a22434c4`, `be5aa34e` are in this branch, STATE.md and ROADMAP.md are not modified.
