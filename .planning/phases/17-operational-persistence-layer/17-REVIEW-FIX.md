---
phase: 17-operational-persistence-layer
fixed_at: 2026-10-02T00:00:00Z
review_path: .planning/phases/17-operational-persistence-layer/17-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 17: Code Review Fix Report

**Fixed at:** 2026-10-02
**Source review:** .planning/phases/17-operational-persistence-layer/17-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (CR-01, WR-01, WR-02, WR-03, WR-04)
- Fixed: 5
- Skipped: 0
- Out of scope, left untouched: IN-01, IN-02, IN-03, IN-04 (Info findings; IN-01 lives in `src/execution/__init__.py`, which no fix touched, so the one-line docstring exception did not apply)

Each finding has one atomic commit with a regression test written first. Verification ran in the main checkout (`workflow.use_worktrees` is false), against PostgreSQL 17.11 in Docker (`trading-postgres-1`), with `TEST_DATABASE_URL` pointing at the `trading_test` database.

## Fixed Issues

### CR-01: A database outage after the entry is acknowledged skips the stop loss (and the entry cancel)

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** 06a3d42
**Test added:** four tests in `tests/test_execution_manager.py` (`test_cr01_*`) using the REAL `SafeModeController` wired to a journal whose `record` raises `StoreUnavailable`. All four failed before the fix (`StoreUnavailable` escaped from `execute_approved_plan` at manager.py:707, :758 and :874) and pass after. They assert: (a) the SL is placed by its deterministic algo id after the entry (ack-write failure and SL-intent failure variants), (b) the outcome is `RECONCILIATION_REQUIRED`, (c) `controller.in_safe_mode` is True and the lost audit row was attempted, (d) at the `ENTRY_STATE_UNKNOWN` site the UNKNOWN intent row is still recorded and the outcome finalized, and at the `ENTRY_WITHOUT_PROTECTIVE` site the entry cancel still runs.
**Applied fix:** added a local `_enter_safe_mode(reason)` helper in `execute_approved_plan` that wraps `safe_mode_controller.enter_safe_mode` in `try/except Exception` (never `BaseException`) and used it in `_store_write`, the `ENTRY_STATE_UNKNOWN` branch and the `ENTRY_WITHOUT_PROTECTIVE` branch. The controller sets its flag before journaling, so only the audit row is lost.
**Docs:** `docs/DECISIONS.md` D051 got one sentence recording that the CR-01 fix made the "stop loss is STILL placed" claim true; `docs/trading/EXECUTION_SPEC.md` section 7.3 states the swallowed-journal behavior.
**Note:** this is a fail-closed logic change; status "fixed: requires human verification" applies to the choice to swallow the audit-row error.

### WR-01: Non-connection DB errors escape the typed `PersistenceError` hierarchy

**Files modified:** `src/persistence/errors.py`, `src/persistence/uow.py`, `tests/test_persistence_uow_pg.py` (new), `tests/test_persistence_transitions_pg.py`, `tests/test_plan_hash_roundtrip_pg.py`
**Commit:** 2a62ab6
**Test added:** `tests/test_persistence_uow_pg.py` (PG, disposable DB fixtures): read-only transaction (`ReadOnlySqlTransaction`), trigger `RAISE EXCEPTION` from an append-only journal UPDATE (`ProgrammingError`), out-of-range numeric (`DataError`) with a secret parameter that must not appear, `IntegrityError` still propagating raw, and the engine staying usable afterwards. Four of the five failed before the fix (the raw driver exception escaped); the integrity test is the control and passes both ways.
**Applied fix:** new `StoreFailure(PersistenceError)`; `OperationalDatabase.transaction()` re-raises `IntegrityError` unchanged, keeps `OperationalError`/`InterfaceError` as `StoreUnavailable`, and maps any other `DBAPIError` to `StoreFailure("PostgreSQL error during transaction (<SQLAlchemy type>/<driver type>)")` with `from None` (no SQL, parameters or URL).
**Pinned tests updated:** `test_integer_part_overflow_still_raises_a_database_error` in `tests/test_persistence_transitions_pg.py` and `tests/test_plan_hash_roundtrip_pg.py` encoded the raw `DataError` coming out of the store; they now expect `StoreFailure` (still "a database error", now typed).

### WR-02: The sync store runs on the event loop with no connect or statement timeout

**Files modified:** `src/persistence/engine.py`, `src/execution/manager.py` (docstring), `tests/test_persistence_engine_timeouts.py` (new)
**Commit:** 1b65bcd
**Test added:** `tests/test_persistence_engine_timeouts.py`: connect args contain `connect_timeout`, `statement_timeout` in `options`, keepalives and `tcp_user_timeout`; arguments override defaults and reject non-positive values; an unreachable host (RFC 5737 192.0.2.1) fails with `StoreUnavailable` in about 2 s (bound asserted under 8 s) with no password in the message; on PG the session reports `statement_timeout`/`lock_timeout`/`TimeZone` as configured, `engine.pool.timeout()` is applied, and a `pg_sleep(5)` is cancelled in under 3 s as `StoreUnavailable`. All failed before the fix.
**Applied fix:** named module constants (`DEFAULT_STATEMENT_TIMEOUT_MS` 10 s, `DEFAULT_CONNECT_TIMEOUT_S` 3, `DEFAULT_POOL_TIMEOUT_S` 5, keepalive idle/interval/count 30/10/3, `DEFAULT_TCP_USER_TIMEOUT_MS` 15 s), a pure `build_connect_args(...)`, and `make_sync_engine(..., statement_timeout_ms=, connect_timeout_s=, pool_timeout_s=)`, all overridable. The `execute_approved_plan` docstring no longer claims `lock_timeout` bounds the store calls; it names the real bounds and says a call can still block the loop up to the longest of them.
**Note:** the numeric defaults are judgment calls (documented in the module); `tcp_user_timeout` is honoured by libpq on Linux only. The docstring option of wrapping the order path in `asyncio.to_thread` was not taken (Phase 24 owns it).

### WR-03: `exit_safe_mode` clears the SAFE_MODE flag before the journal write

**Files modified:** `src/reconcile/safe_mode.py`, `tests/test_journal_failure_paths.py`
**Commit:** 887c34a
**Test added:** `test_exit_safe_mode_with_a_failing_journal_stays_in_safe_mode_and_can_retry` (failed before: the controller was already out of SAFE_MODE). It asserts the error propagates, the controller stays in SAFE_MODE with its reason and entry time, new entries stay blocked, no exit event is recorded, and that a retry after the journal recovers exits and records exactly one `SAFE_MODE_EXIT`.
**Applied fix:** `_journal_safe_mode_event(SAFE_MODE_EXIT)` now runs before `_in_safe_mode = False`.
**Pinned 17-08 tests:** none encoded the unsafe exit order; no existing test was changed (the 17-08 module docstring got a fifth pinned behavior). `enter_safe_mode` is unchanged (flag first, deliberately).

### WR-04: The async `make_engine` echoes the full database URL in a `ValueError`

**Files modified:** `src/db/models.py`, `tests/test_db_make_engine_errors.py` (new)
**Commit:** 3d72580
**Test added:** `tests/test_db_make_engine_errors.py`: for `postgres://user:secret@host/db`, a `mysql+aiomysql://` URL and a scheme-less `user:secret@host/db`, the message contains no password, userinfo or host and still names the expected `postgresql+psycopg://` form; the first one reports `scheme 'postgres'`. All failed before the fix.
**Applied fix:** the message now names only the scheme (a new `_scheme_class` helper returns the validated scheme, or `<unrecognized>`), never the URL.

## Documentation

**Commit:** c7c44d9 (`docs/DECISIONS.md` D051 one sentence; `docs/trading/EXECUTION_SPEC.md` section 7.3 two clauses). RUNBOOK needed no change (its wording is now true as written). No document contained "bounded by lock_timeout".

## Skipped Issues

None in scope. Not attempted (Info, out of scope): IN-01 (stale "exchange-deduped" wording in `src/execution/__init__.py`), IN-02 (SQL parameters chained into typed errors; WR-01's new `StoreFailure` already uses `from None`, but the existing `from exc` sites in the stores are unchanged), IN-03 (bind approval row to plan and hash in the consume UPDATE), IN-04 (`uq_approvals_one_decided_per_plan` versus EXPIRED siblings).

## Verification

Run in the main checkout against PostgreSQL 17.11 (Docker), `TEST_DATABASE_URL` set:

- Touched test modules: pass (`test_execution_manager.py` 61 passed; the new and changed PG modules pass).
- `TRADING_CI_STRICT=1` over `tests/test_persistence_*.py`, `tests/test_execution_*_pg.py`, `tests/test_intent_recovery_pg.py`, `tests/test_system_state_pg.py`, `tests/test_approval_replay_pg.py`, `tests/test_callback_redelivery_pg.py`: all pass, exit code 0 (about 390 tests, no skips under strict).
- `mypy src`: Success, no issues in 132 source files.
- `ruff check src tests`: All checks passed. `ruff format --check src tests`: 308 files already formatted.
- Full suite `pytest -m "not docker"`: 3633 tests, 0 failures, 0 errors, 10 skipped (8 shellcheck not on PATH, 1 symlinks unavailable, 1 NTFS POSIX modes: all environmental). The known Windows PermissionError flakes in `tests/test_backfill_cli.py` and `tests/test_universe_freeze.py` did not occur.

---

_Fixed: 2026-10-02_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
