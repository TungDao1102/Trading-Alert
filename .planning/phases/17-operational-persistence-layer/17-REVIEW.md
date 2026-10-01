---
phase: 17-operational-persistence-layer
reviewed: 2026-10-02T00:00:00Z
depth: deep
files_reviewed: 36
files_reviewed_list:
  - pyproject.toml
  - src/adapters/binance_usdm.py
  - src/adapters/telegram_callbacks.py
  - src/approval/binding.py
  - src/approval/replay.py
  - src/backtest/costs.py
  - src/core/planner.py
  - src/data/metadata.py
  - src/db/alembic/versions/0004_persistence_integrity.py
  - src/db/mappers.py
  - src/db/models.py
  - src/domain/approval.py
  - src/domain/canonical.py
  - src/domain/enums.py
  - src/domain/journal.py
  - src/domain/transitions.py
  - src/execution/constraint_snapshot.py
  - src/execution/enablement.py
  - src/execution/intent_recovery.py
  - src/execution/intent_store.py
  - src/execution/manager.py
  - src/execution/order_ids.py
  - src/ops/drills.py
  - src/persistence/__init__.py
  - src/persistence/approvals.py
  - src/persistence/engine.py
  - src/persistence/entities.py
  - src/persistence/errors.py
  - src/persistence/execution_state.py
  - src/persistence/journal.py
  - src/persistence/snapshots.py
  - src/persistence/system_state.py
  - src/persistence/uow.py
  - src/reconcile/safe_mode.py
  - src/reconcile/sweeper.py
findings:
  critical: 1
  warning: 4
  info: 4
  total: 9
status: issues_found
---

# Phase 17: Code Review Report

**Reviewed:** 2026-10-02
**Depth:** deep (manager -> intent store -> PG stores -> migration 0004 call chains followed)
**Files Reviewed:** 36 (scripts/check_migration_parity.py is deleted and was skipped)
**Status:** issues_found

## Summary

The exactly-once core holds up. The entry intent is consumed by `INSERT ... ON CONFLICT (approval_id, role) DO NOTHING RETURNING` plus a conditional `UPDATE approvals` in one transaction (`execution_state.py:171-199`). The secondary arbiters (`uq_execution_intents_plan_role`, `uq_execution_intents_client_order_id`) and the lost-race re-check are correct, and `IntentStateConflict` is raised inside the transaction, so the intent insert rolls back. Every store method owns its own transaction, so no caller-owned transaction is left aborted by the consume path. The migration, the DB terminal-state triggers and `src/domain/transitions.py` agree exactly (signals, trade_plans, orders, positions, approvals, execution_intents). `ruff check src` and `mypy` over persistence, execution, reconcile, approval and domain are clean. I found no way to reach two `place_entry` calls for one approval.

The defects are all on the fail-closed side of the write-ahead flow, after the entry may already exist on the exchange. The documented guarantee "after the entry may exist the first store failure enters SAFE_MODE(DB_FAILURE) once and the stop loss is STILL placed" (manager docstring, D051 item (d)) is false for the realistic failure it is meant to cover: a database outage. The unit tests use a fake SAFE_MODE controller that never raises, so the gap is invisible to them.

## Critical Issues

### CR-01: A database outage after the entry is acknowledged skips the stop loss (and the entry cancel)

**File:** `src/execution/manager.py:698-709` (also `:758` and `:874`)
**Issue:** `_store_write` catches `PersistenceError`, sets `store_failed`, then calls `safe_mode_controller.enter_safe_mode(reason=DB_FAILURE, ...)` OUTSIDE any `try`. With the production controller, `enter_safe_mode` journals through `PgJournalStore.record`, which uses the same PostgreSQL database that just failed (`safe_mode.py:391`). The journal write then raises `StoreUnavailable` (a `PersistenceError`). It propagates out of `_store_write`, out of `execute_approved_plan`, and the `place_algo_protective` call at line 839 is never reached.

Concrete failing scenario:
1. `place_entry` is acknowledged by Binance.
2. The database goes away (restart, failover, connection reset).
3. `record_result(ACKED)` fails and `_store_write` calls `enter_safe_mode`.
4. The controller's in-memory flag flips, then the journal insert raises `StoreUnavailable`.
5. The exception reaches the caller and the entry is live with no stop.

The same pattern exists at the other two `enter_safe_mode` call sites:
- `:758`, the `ENTRY_STATE_UNKNOWN` branch, where the exception escapes before `record_result(UNKNOWN)`.
- `:874`, the `ENTRY_WITHOUT_PROTECTIVE` branch, where the exception escapes before `expire_pending_entry`, so the unprotected entry is not even cancelled.

This is related to, but not the same as, the documented F-702 gap (those are `disable` / `expire_pending_entry` / `cancel_untriggered_protectives` / `emergency_manual_close`). Here the manager itself aborts its own protection step. Tests `test_execution_manager.py:1624-1663` use a recording fake controller, so they cannot see this. D051 (d) and the `execute_approved_plan` docstring state the opposite behavior.

**Fix:** Make every `enter_safe_mode` call on this path non-fatal, because the controller sets its flag before journaling (`safe_mode.py:248-251`). The flag is already set when the journal write fails, so swallowing the journal error loses only the audit row:
```python
def _enter_safe_mode(reason: str) -> None:
    try:
        safe_mode_controller.enter_safe_mode(reason=reason, now_utc=now_utc)
    except Exception:  # noqa: BLE001 - flag is set before journaling; protection outranks the audit row (D034)
        pass
```
Use it in `_store_write`, at line 758 and at line 874. Add a manager test with the real `SafeModeController` and a journal whose `record` raises `StoreUnavailable`, asserting that `place_algo_protective` is still called.

## Warnings

### WR-01: Non-connection DB errors escape the typed `PersistenceError` hierarchy, with the same stop-loss skip

**File:** `src/persistence/uow.py:34-40`, consumed at `src/execution/manager.py:705`
**Issue:** `transaction()` converts only `OperationalError` and `InterfaceError` to `StoreUnavailable`. Other `DBAPIError` subclasses propagate as raw SQLAlchemy exceptions. Verified against the installed psycopg:
- `ReadOnlySqlTransaction` (a write against a read-only replica after a failover) is an `InternalError`.
- `RaiseException` (the P0001 raised by the append-only and terminal triggers) is a `ProgrammingError`.
- `NumericValueOutOfRange` and `StringDataRightTruncation` are `DataError`.

The manager's post-entry handler catches only `PersistenceError`, so any of these during `record_result(ACKED)` (or any write after the entry may exist) propagates before the stop loss is placed. That contradicts the docstring ("only typed persistence errors are caught, so a crash propagates") because these are not crashes. Before the entry is sent, the same exceptions bubble out of `consume_and_record_entry_intent` as raw exceptions instead of the documented NO_TRADE.
**Fix:** In `OperationalDatabase.transaction()` map every `DBAPIError` that is not an `IntegrityError` (the stores translate those) to a `PersistenceError` subclass, with the exception type name only, `from None`:
```python
except IntegrityError:
    raise
except (OperationalError, InterfaceError) as exc:
    raise StoreUnavailable(...) from None
except DBAPIError as exc:
    raise StoreFailure(f"database error ({type(exc).__name__})") from None
```
Define `StoreFailure(PersistenceError)` in `errors.py`. Combine with CR-01 so protection never depends on the store.

### WR-02: The sync store runs on the event loop with no connect or statement timeout; the docstring claims a bound that does not exist

**File:** `src/persistence/engine.py:58-62`; claim at `src/execution/manager.py:430-431`
**Issue:** The manager docstring says store calls are "short indexed queries bounded by the engine `lock_timeout`". `lock_timeout` bounds only lock waits. `create_engine` sets no `connect_timeout`, no `statement_timeout`, no TCP keepalive or `tcp_user_timeout`, and no `pool_timeout`. A blackholed or half-open connection (`pool_pre_ping` itself blocks on it) therefore stalls the single asyncio thread for the OS TCP timeout, which can be minutes. This hits the worst moment: `record_result` runs between `place_entry` and `place_algo_protective`, so a hung call delays the stop loss and also freezes the user-data stream, reconciler and heartbeat, which share the loop.
**Fix:** Add `connect_args` `connect_timeout` (for example 3 s) and `-c statement_timeout=<ms>` to the `options` string, plus keepalive parameters (`keepalives=1`, `keepalives_idle`, `keepalives_interval`, `keepalives_count`) and `pool_timeout`. Correct the docstring to name the real bounds, or wrap the calls in `asyncio.to_thread` with `asyncio.wait_for` on the order path.

### WR-03: `exit_safe_mode` clears the SAFE_MODE flag before the journal write, contradicting its own contract and fail-open on a journal outage

**File:** `src/reconcile/safe_mode.py:346-354`
**Issue:** The docstring says exit requires "a clean compare AND a journaled restore event" and that "the controller never mutates state without journaling first". The code sets `self._in_safe_mode = False` at line 347, then calls `_journal_safe_mode_event`, then clears the entry fields. Before this phase the journal could not fail. With `PgJournalStore` it can: if the journal raises `StoreUnavailable`, the exception propagates but the controller is already out of SAFE_MODE. The next tick sees `exit_safe_mode` return True ("already out"), and `guard_new_entries` passes with no SAFE_MODE_EXIT event ever recorded. The entry side (`enter_safe_mode`) deliberately flips first (fail closed); the exit side must do the opposite and journal first. No test pins this (`tests/test_journal_failure_paths.py` has no EXIT case). Once Phase 20 persists this state, a silent un-journaled exit also corrupts the persisted audit trail.
**Fix:** Journal first, flip after:
```python
self._journal_safe_mode_event(event_type="SAFE_MODE_EXIT", reason="clean_three_source_compare", now_utc=effective_now)
self._in_safe_mode = False
self._entered_at_utc = None
self._entered_reason = None
```
A journal failure then leaves the controller in SAFE_MODE and propagates. Add a test with a failing journal.

### WR-04: The async `make_engine` echoes the full database URL, including the password, in a `ValueError`

**File:** `src/db/models.py:924-927`
**Issue:** `raise ValueError(f"refusing engine: {database_url!r} names no async driver ...")` puts the raw URL in the message. This phase changed `make_engine` (UTC pinning) and states the policy that URLs and passwords never reach messages (`persistence/engine.py` docstring, T-17-03, which hides the password and refuses non-psycopg schemes with a URL-free message). A mistyped scheme such as the common `postgres://user:pw@host/db` alias triggers it, and the secret then lands in logs and tracebacks. The sync engine factory does this correctly (`engine.py:30-33`).
**Fix:** Drop the URL from the message, or render it with `make_url(database_url).render_as_string(hide_password=True)` (guarded for an unparsable string).

## Info

### IN-01: Stale "exchange-deduped" wording survives in `src/execution/__init__.py`

**File:** `src/execution/__init__.py:3-5`
**Issue:** The package docstring still says a retry must reuse "the exchange-deduped identifier". This is exactly the retired 08 D-04 premise (EXECUTION_SPEC 7.1, F-126/F-951). Phase 17 corrected `order_ids.py`, `manager.py` and `intent_store.py` but not this file. `src/adapters/binance_usdm.py:120` ("Placement calls are the FIRST line of defense") is accurate about the adapter but reads as if the exchange were the defense.
**Fix:** Reword to "reuse the deterministic identifier so a probe by client id can find the order (the persisted execution intent, not the exchange, prevents a duplicate)".

### IN-02: SQLAlchemy errors keep SQL parameters, which are chained into the typed errors

**File:** `src/persistence/engine.py:58`, `src/persistence/journal.py:106-112`, and other `raise ... from exc` sites
**Issue:** The typed errors carefully avoid payload contents (T-17-21), but they chain the original `IntegrityError` with `from exc`. By default SQLAlchemy puts `[SQL: ...] [parameters: {...}]` in the message, so a traceback logged by any caller includes `payload_json`, `snapshot_json`, approval token hashes and prices. The `DETAIL: Key (...)=(...)` text of a unique violation likewise names the value. The docstring promise ("never payload contents") only holds for the top-level message.
**Fix:** Pass `hide_parameters=True` to `create_engine` in `make_sync_engine` (and to the async engine), or use `from None` where the cause adds nothing the constraint name does not already give.

### IN-03: Consumption does not bind the approval row to the plan and hash being consumed

**File:** `src/persistence/execution_state.py:181-193`
**Issue:** The conditional `UPDATE approvals` filters on `approval_id`, `consumption_status` and `status` only. `trade_plan_id` and `plan_hash` are taken from the caller and stored on the intent. The manager does verify `approval.trade_plan_id == trade_plan.trade_plan_id` and `plan_hash == approval.request_hash` before calling, so there is no present bug. The plan's own stated principle is a second line of defense in the database against a caller bug, and the exactly-once arbiters `uq_execution_intents_plan_role` and `uq_execution_intents_client_order_id` are keyed on caller-supplied values.
**Fix:** Add `ApprovalRow.trade_plan_id == trade_plan_id` and `ApprovalRow.request_hash == plan_hash` to the UPDATE's WHERE clause, so a mismatched pair fails with the existing `IntentStateConflict`.

### IN-04: Latent conflict between `uq_approvals_one_decided_per_plan` and expiring the sibling approval rows

**File:** `src/db/alembic/versions/0004_persistence_integrity.py:328-334`, `src/persistence/approvals.py:201-242`
**Issue:** Each button has its own approval row per plan (`resolve_callback` rejects `callback.action != approval.action`). The partial unique index counts every non-PENDING status, including EXPIRED and SKIPPED, as "decided". When a future expiry job writes EXPIRED to both sibling rows of an expired plan, the second write violates the index and `_decide` reports it as `ApprovalAlreadyDecided`, so the second row can never reach EXPIRED. No such writer exists yet (the only EXPIRED references are in `src/analytics/lifecycle.py`, which derives it rather than storing it), so this is not a present defect. Phases 23 and 24 should know the constraint when they add expiry.
**Fix:** Decide the rule now: either exclude EXPIRED from the predicate (`status NOT IN ('PENDING','EXPIRED')`) or define expiry as a single plan-level state. Record the choice in DATA_MODEL.

---

_Reviewed: 2026-10-02_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
