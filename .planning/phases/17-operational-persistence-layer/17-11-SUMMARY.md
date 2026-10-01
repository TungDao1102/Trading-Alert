---
phase: 17-operational-persistence-layer
plan: 11
subsystem: execution
tags: [write-ahead, execution-intent, postgresql, crash-injection, fail-closed, safe-mode, replay, transitions]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01 ExecutionIntentStore Protocol, PgExecutionStateStore, BinanceSemanticsFakeAdapter, pg_db fixtures; plan 02 execution_intents table, unique indexes and terminal-status trigger; plan 03 EXECUTION_INTENT transition table (assert_transition)"
provides:
  - "check_binding_identity (chat, plan hash, version/parameter set, token; no expiry) in src/approval/binding.py"
  - "execute_approved_plan: identity check, then stored-outcome replay, then expiry; STOP_LOSS leg written ahead (INTENDED, SENT) before place_algo_protective and closed ACKED or UNKNOWN"
  - "Fail-closed store handling on both sides of placement (NO_TRADE before, SAFE_MODE DB_FAILURE with the SL still placed after)"
  - "ExecutionIntentStore.record_protective_intent (Protocol, PgExecutionStateStore, in-memory double); intent status changes go through src.domain.transitions"
  - "tests/support: SimulatedCrash, CrashAfter, FailingIntentStore; tests/test_execution_write_ahead_pg.py"
affects: [17-12, 17-14, 17-15, phase-19, phase-20, phase-24]

actuals:
  tokens: 19000
  tasks: 2
  commits: 3
plan_head_before: 138106c6969ac04406d80b608df03afa444e7bec
plan_head_after: 668d3d169a384fba77ab242f68c9855a8a2620f4

tech-stack:
  added: []
  patterns:
    - "Post-consume store writes go through one local _store_write(): only PersistenceError is caught, SAFE_MODE(DB_FAILURE) is entered once, later writes are skipped, a BaseException (crash) propagates untouched"
    - "Idempotent status writes: an unchanged status is a no-op before assert_transition is called (it raises on old == new)"
    - "Crash injection by store decoration (CrashAfter(step=...)) with a BaseException subclass; restart is a fresh engine, store and manager call on the same database"

key-files:
  created:
    - tests/test_execution_write_ahead_pg.py
  modified:
    - src/approval/binding.py
    - src/execution/manager.py
    - src/execution/intent_store.py
    - src/execution/order_ids.py
    - src/persistence/execution_state.py
    - tests/support/intent_store_fakes.py
    - tests/test_execution_manager.py

key-decisions:
  - "SL write-ahead failure policy (for D051): if the STOP_LOSS intent (or any later store write) fails after the entry may exist, enter SAFE_MODE with reason DB_FAILURE exactly once, skip every later store write, STILL place the SL by its deterministic algo id, and return (True, RECONCILIATION_REQUIRED); protection outranks the audit row (EXECUTION_SPEC section 6, D034). The unconfirmed-SL path (SAFE_MODE ENTRY_WITHOUT_PROTECTIVE plus entry cancel) still runs when the SL is not confirmed."
  - "Pre-placement store failures never enter SAFE_MODE: PersistenceError returns (True, RECONCILIATION_REQUIRED) and IntentStateConflict at consume (a second approval of the same plan) returns (True, INVALIDATED); nothing is placed. A failure of the ENTRY mark_sent leaves the consumed INTENDED row, so every replay returns RECONCILIATION_REQUIRED until reconciliation resolves it."
  - "SL result mapping: confirmed -> ACKED, not confirmed -> UNKNOWN. exchange_order_id and exchange_status stay NULL on the STOP_LOSS row because _place_protective_leg returns only (confirmed, detail); reconciliation fills them."
  - "An unchanged intent status is an idempotent no-op in both the PG store and the in-memory double (plan 03 note); a missing row or an illegal move is IntentStateConflict. The terminal-state trigger in PostgreSQL stays the second line of defence."
  - "Gate order changed deliberately (Open Q2, D-16): identity, then stored outcome, then expiry. A mismatching plan hash on an already-expired callback now reports STALE_SETUP (identity) instead of APPROVAL_EXPIRED."
  - "The manager imports src.persistence.errors (pure exception classes, no SQLAlchemy) so it can catch PersistenceError, IntentStateConflict; the 'no SQLAlchemy in manager.py / intent_store.py' prohibition holds (grep proven)."

patterns-established:
  - "Every adapter order call is preceded by a committed row: ENTRY SENT before place_entry, STOP_LOSS SENT before place_algo_protective; plans 12 and 14 (and Phase 19 attach/TP legs) follow the same INTENDED -> SENT -> result sequence"

requirements-completed: [EXEC-03, APRV-02]

coverage:
  - id: D1
    description: "Full D-14 write-ahead order on PostgreSQL: a second connection reads ENTRY=SENT (no STOP_LOSS row) at place_entry and ENTRY=ACKED with STOP_LOSS=SENT at place_algo_protective; after the run both rows are ACKED, the ENTRY outcome is OK and the STOP_LOSS row carries the deterministic xa- id, NULL client_order_id and NULL quantity"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_execution_write_ahead_pg.py#test_rows_are_committed_before_each_order_call"
        status: pass
    human_judgment: false
  - id: D2
    description: "A SimulatedCrash after each of consume, entry_sent, entry_result, sl_intent, sl_sent and sl_result leaves the expected readable row(s); a restart on a fresh engine returns RECONCILIATION_REQUIRED with zero adapter calls and never a second place_entry (at most 1 in total, 0 before SENT); a crash after finalize restarts to the stored (False, OK)"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_execution_write_ahead_pg.py#test_crash_after_each_step_leaves_a_row_and_restart_never_resends"
        status: pass
      - kind: integration
        ref: "tests/test_execution_write_ahead_pg.py#test_crash_after_finalize_restarts_to_the_stored_outcome"
        status: pass
      - kind: unit
        ref: "tests/test_execution_manager.py#test_restart_after_a_crash_never_resends_the_entry"
        status: pass
    human_judgment: false
  - id: D3
    description: "The stored outcome is looked up after the identity checks and before the expiry gate: a replay after expiry returns the stored outcome with zero adapter calls, while a wrong token or wrong chat gets INVALIDATED and never sees the stored state; with nothing stored, expiry still returns APPROVAL_EXPIRED"
    requirement: APRV-02
    verification:
      - kind: unit
        ref: "tests/test_execution_manager.py#test_replay_after_expiry_returns_the_stored_outcome_with_zero_adapter_calls"
        status: pass
      - kind: unit
        ref: "tests/test_execution_manager.py#test_stored_outcome_is_not_revealed_to_a_wrong_token_or_wrong_chat"
        status: pass
      - kind: unit
        ref: "tests/test_execution_manager.py#test_check_binding_identity_hash_version_and_token_mismatches"
        status: pass
    human_judgment: false
  - id: D4
    description: "Store failures fail closed: StoreUnavailable on lookup or consume, or on the ENTRY mark_sent, returns RECONCILIATION_REQUIRED without placement; IntentStateConflict at consume returns INVALIDATED; a store failure after the entry is acknowledged enters SAFE_MODE(DB_FAILURE) once and still places the SL by its deterministic id"
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_execution_manager.py#test_store_down_after_entry_ack_enters_safe_mode_and_still_places_the_sl"
        status: pass
      - kind: unit
        ref: "tests/test_execution_manager.py#test_second_approval_of_the_same_plan_is_invalidated_without_placement"
        status: pass
      - kind: unit
        ref: "tests/test_execution_manager.py#test_store_down_and_sl_unconfirmed_still_cancels_the_entry"
        status: pass
    human_judgment: false
  - id: D5
    description: "Intent status changes in the PG store go through assert_transition(TransitionKind.EXECUTION_INTENT, ...) after a FOR UPDATE read (ALLOWED_PREDECESSORS removed from src); illegal move and missing row are IntentStateConflict, unchanged status is a no-op; protective insert is idempotent"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_execution_write_ahead_pg.py#test_protective_intent_insert_is_idempotent_and_transitions_are_enforced"
        status: pass
      - kind: unit
        ref: "tests/test_execution_manager.py#test_intent_status_changes_go_through_the_transition_tables"
        status: pass
    human_judgment: false
  - id: D6
    description: "order_ids.py and the manager docstring no longer claim exchange-side clientOrderId dedup: Binance rejects a duplicate only while the earlier order is open and the persisted intent is the guard (D-13, F-951, C18)"
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_execution_manager.py#test_order_ids_do_not_claim_exchange_side_deduplication"
        status: pass
    human_judgment: false

duration: 35 min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 11: Write-Ahead Execution Flow Summary

**The SL leg now has its own committed INTENDED/SENT intent before `place_algo_protective`, the stored-outcome replay runs after identity and before expiry, store failures fail closed on both sides of placement (SAFE_MODE DB_FAILURE with the SL still placed after the entry), and crash injection on PostgreSQL proves a restart never sends a second order.**

## Performance

- **Duration:** about 35 min (about 12.5 of them the full-suite run)
- **Completed:** 2026-10-01
- **Tasks:** 2 (both TDD)
- **Files:** 1 created, 7 modified

## Accomplishments

- `check_binding_identity` (`src/approval/binding.py`): chat, plan hash, version/parameter set, token; never looks at expiry. `check_binding_full` is unchanged and is still run afterwards to add the expiry gate.
- `execute_approved_plan` order is now: argument validation, identity, stored-outcome lookup, `check_binding_full`, approval-authorizes-plan, enablement, SAFE_MODE, cost-rate gate, risk, placement gates, position mode, consume (ENTRY INTENDED), ENTRY SENT, `place_entry`, ENTRY ACKED/REJECTED/UNKNOWN, STOP_LOSS INTENDED then SENT, `place_algo_protective`, STOP_LOSS ACKED/UNKNOWN, ENTRY outcome finalized.
- Store failures: before the entry is sent a `PersistenceError` returns `(True, RECONCILIATION_REQUIRED)` (an `IntentStateConflict` at consume returns `(True, INVALIDATED)`); after the entry may exist the first failure enters SAFE_MODE `DB_FAILURE` once, all later store writes are skipped, the SL is still placed by its deterministic id and the outcome is `RECONCILIATION_REQUIRED`. Only `PersistenceError` is caught; there is no `except BaseException`, so `SimulatedCrash` propagates.
- `ExecutionIntentStore.record_protective_intent` added to the Protocol, `PgExecutionStateStore` (targeted `ON CONFLICT (approval_id, role) DO NOTHING RETURNING`, other unique arbiters become `IntentStateConflict`) and the in-memory double. The local predecessor map `ALLOWED_PREDECESSORS` is gone; `_advance` reads the status `FOR UPDATE` and calls `assert_transition(TransitionKind.EXECUTION_INTENT, ...)`.
- `order_ids.py` module and function docstrings and the manager docstring rewritten per research C18: ids are deterministic so a probe finds an order, Binance treats client ids as unique only among OPEN orders, the persisted intent is the duplicate-entry guard.
- Test doubles: `SimulatedCrash(BaseException)`, `CrashAfter(inner, step=...)` for seven steps (consume, entry_sent, entry_result, sl_intent, sl_sent, sl_result, finalize) and `FailingIntentStore(method, exc, role=...)`.

## Task Commits

1. Task 1 RED: `2ec2c45` test(17-11): RED for identity-before-replay, SL write-ahead and fail-closed store handling (17 of the 57 tests in `tests/test_execution_manager.py` failed)
2. Task 1 GREEN: `b55b014` feat(17-11): identity-before-replay, SL write-ahead intent and fail-closed store handling
3. Task 2: `668d3d1` test(17-11): PostgreSQL write-ahead proof with row state per adapter call and crash injection

Task 2 has no separate RED commit (the plan says production code is unchanged unless a test exposes a defect; none did). The tests were proved non-vacuous by mutation instead (see Verification).

## Verification (real runs)

PostgreSQL runs used the dev server (`TEST_DATABASE_URL` set inline; credential not written to any file).

- Task 1 verify: `pytest tests/test_execution_manager.py tests/test_execution_attach.py tests/test_execution_emergency.py tests/test_order_ids.py tests/test_approval_replay.py -x -q` exit 0 (all dots). `mypy src`: no issues in 129 source files. `ruff check` (repo root): all checks passed. `ruff format --check src tests`: 294 files already formatted.
- Task 2 verify: `TRADING_CI_STRICT=1 pytest tests/test_execution_write_ahead_pg.py tests/test_execution_exactly_once_pg.py -x -q -rs` exit 0, 20 passed, no SKIPPED line. `tests/test_persistence_approvals_pg.py` (also uses the store) passes under strict.
- Mutation check: replacing the STOP_LOSS `mark_sent` call in the manager with a no-op made `test_rows_are_committed_before_each_order_call`, the `sl_sent` and `sl_result` crash cases, `test_crash_after_finalize_restarts_to_the_stored_outcome` and `test_restart_after_a_complete_run_returns_the_stored_outcome` fail; manager restored via `git checkout -- src/execution/manager.py` (`git status` clean for `src`).
- Acceptance greps: `check_binding_identity` defined once (binding.py:140) and called once in the manager; no `except BaseException` in the manager; no "dedupe retries" or "impossible by construction" in order_ids.py; `record_protective_intent` present in manager.py, intent_store.py and execution_state.py; no `sqlalchemy` string in manager.py or intent_store.py.
- Plan-level full suite: `pytest -m "not docker" -q` with `TEST_DATABASE_URL` set, exit 0 (3429 passes, 10 skips = the pre-existing Windows/NTFS/shellcheck set noted in 17-05, no `F` or `E`). Not run under `TRADING_CI_STRICT=1` (those pre-existing skips would fail it); both new/changed PG modules were run separately under strict with zero skips.
- Repo-root `ruff format --check` reports one file: `.planning/phases/17-operational-persistence-layer/17-RESEARCH.md` (the pre-existing item logged in `deferred-items.md` from 17-01), not touched here.

## Deviations from Plan

None - plan executed as written, with these judgment calls inside its latitude (all in key-decisions):

- "Zero adapter calls" for a store failure at consume: the read-only `get_position_mode` probe still runs before consume (it must, so that a position-mode NO_TRADE never consumes the approval, Open Q1), so those tests assert zero ORDER-PLACING calls (`place_entry`, `place_algo_protective`); the lookup-failure and replay tests assert literally `adapter.calls == []`.
- In the crash matrix the `entry_sent` crash has 0 `place_entry` calls (the crash is after the SENT commit but before the call), which is within the plan's "at most 1".
- `_place_protective_leg` was not changed, so the STOP_LOSS row keeps NULL `exchange_order_id` and `exchange_status`.

**Total deviations:** 0 auto-fixed. **Impact:** none.

## Known Stubs

None.

## Threat Flags

None. T-17-28 mitigated (committed INTENDED/SENT rows before each call; restart returns RECONCILIATION_REQUIRED; crash injection at every step on PostgreSQL). T-17-29 mitigated (identity before lookup; test proves INVALIDATED for wrong token and wrong chat). T-17-30 mitigated (SAFE_MODE DB_FAILURE plus SL still placed). T-17-SC: no packages installed.

## Issues Encountered

None blocking. For later plans and phases:

- A crash after `sl_intent` (entry acknowledged, SL not yet placed) leaves an entry without a stop, and a restart returns `RECONCILIATION_REQUIRED` without placing it. Closing that gap is reconciliation's job (Phase 20); the intent rows (ENTRY ACKED, STOP_LOSS INTENDED or SENT) are what it will read.
- Plan 17-08 finding unchanged and not touched here: with a failing journal, the controller `disable`, `expire_pending_entry`, `cancel_untriggered_protectives` and `emergency_manual_close` behave unsafely (Phase 20 owns it). `execute_approved_plan` still swallows an `expire_pending_entry` exception exactly as before.
- Decisions to record in D051 (plan 15): the SL write-ahead failure policy above, the identity-then-replay-then-expiry gate order, the pre-placement versus post-placement failure split.

## Next Phase Readiness

Plans 17-12 and 17-14 can reuse `CrashAfter`/`FailingIntentStore` and the INTENDED -> SENT -> result sequence. The Phase 19 attach path (TP1/TP2) should write its legs ahead with `record_protective_intent` the same way.

## Self-Check: PASSED

- `tests/test_execution_write_ahead_pg.py` and this SUMMARY exist; commits `2ec2c45`, `b55b014`, `668d3d1` exist; measured commit count 3 from the recorded plan head `138106c`.
