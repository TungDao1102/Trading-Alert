---
phase: 25-demo-integration-test-campaign
plan: 03
subsystem: persistence
tags: [R-24, D-13, pool-timeout, StoreUnavailable, tdd, OPS-01]
requires: []
provides:
  - "OperationalDatabase.transaction(): a SQLAlchemy pool-exhaustion TimeoutError becomes StoreUnavailable (type name only, from None)"
affects: [25-04, 25-12]
tech-stack:
  added: []
  patterns:
    - "one typed clause at the one transaction seam; src/ops/store_executor.py untouched"
key-files:
  created:
    - tests/test_persistence_pool_timeout.py
  modified:
    - src/persistence/uow.py
    - tests/test_persistence_uow_pg.py
key-decisions:
  - "The new clause sits after IntegrityError and before DBAPIError: TimeoutError is not a DBAPIError, so the ordering is for readability, not precedence."
  - "Message is 'PostgreSQL pool exhausted during transaction (TimeoutError)', distinct from the OperationalError message, so a log reader can tell pool exhaustion from a connection loss."
requirements-completed: [OPS-01]
status: complete
actuals:
  tokens: 4500
  tasks: 2
  commits: 3
plan_head_before: f604df0f8bfaf68e5ba9b54368e56b07f33746a2
plan_head_after: 803ed72d2c2f57982203dd377e311fc76a025329
---

# Phase 25 Plan 03: Pool-timeout typed as StoreUnavailable Summary

R-24 closed test-first: a pool exhaustion inside `OperationalDatabase.transaction()` now surfaces as `StoreUnavailable("PostgreSQL pool exhausted during transaction (TimeoutError)")` with the cause suppressed, instead of escaping the execution manager as a raw `sqlalchemy.exc.TimeoutError` after the approval was consumed.

## Commits

| Task | Phase | Commit | Files |
|------|-------|--------|-------|
| 1 | RED | 44aac4b9 | tests/test_persistence_pool_timeout.py |
| 1 | GREEN | 87cb3db9 | src/persistence/uow.py |
| 2 | test | 803ed72d | tests/test_persistence_uow_pg.py |

## RED evidence

At HEAD before the fix, `uv run pytest -m "not docker" tests/test_persistence_pool_timeout.py` failed all three cases for the planned reason:

```
E   sqlalchemy.exc.TimeoutError: QueuePool limit of size 1 overflow 0 reached, connection timed out, timeout 0.20
FAILED test_an_exhausted_pool_is_store_unavailable_with_the_type_name_only
FAILED test_the_raw_pool_timeout_is_not_what_the_caller_sees
FAILED test_the_same_transaction_succeeds_once_the_held_connection_closes
```

After the one-clause fix all three pass. The PostgreSQL variant was written after the fix (Task 2 is the same rule on the real database); it was not run RED separately, the SQLite RED proves the missing clause because the pool is SQLAlchemy's own `QueuePool` in both cases.

## Verification (agent-run)

- `uv run pytest -m "not docker" tests/test_persistence_uow_pg.py tests/test_persistence_pool_timeout.py -q`: 9 passed, 0 skipped (TEST_DATABASE_URL was set in the process environment, so the PostgreSQL cases ran against a disposable `_test` database).
- `uv run ruff check` and `ruff format --check` on the three files: clean.
- `uv run mypy src`: no issues in 291 files.
- `uv lock --check`: ok. `git diff --exit-code -- pyproject.toml uv.lock src/ops/store_executor.py`: exit 0.
- Existing translations (IntegrityError raw, OperationalError/InterfaceError to StoreUnavailable, other DBAPIError to StoreFailure) are unchanged; the existing PostgreSQL cases in `tests/test_persistence_uow_pg.py` still pass.

## Deviations from Plan

None. The plan executed as written. Line endings: `src/persistence/uow.py` and `tests/test_persistence_uow_pg.py` are CRLF in the working tree and were edited byte-aware (CRLF kept). The new test file was written with LF and git will normalise it (autocrlf).

## Not covered by an agent-run test

- Behaviour end to end through the execution manager (a pool timeout after the approval was consumed): covered only at the `transaction()` seam here; scenario S11 in the campaign exercises the manager path.
- A real pool exhaustion under the production engine settings (`make_sync_engine` default pool, 5 s `pool_timeout_s`): the tests use a size-1 pool with short timeouts built with `create_engine` directly.

## Known Stubs

None.

## Threat Flags

None. T-25-07 and T-25-08 mitigated (typed error, type name only, `from None`, message assertions); T-25-SC: no dependency change.

## Self-Check: PASSED

Files found: src/persistence/uow.py, tests/test_persistence_pool_timeout.py, tests/test_persistence_uow_pg.py. Commits 44aac4b9, 87cb3db9, 803ed72d are ancestors of HEAD.
