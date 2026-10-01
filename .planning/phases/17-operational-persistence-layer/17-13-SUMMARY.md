---
phase: 17-operational-persistence-layer
plan: 13
subsystem: persistence
tags: [constraint-snapshot, system-state, safe-mode, rehydrate, restart, postgresql, fail-closed, journal, append-only]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 02 plan_constraint_snapshots and system_state_events tables with append-only triggers; plan 04 SystemStateKey and KillGateState; plan 06 constraint_snapshot module (canonical JSON, sha256, live validity); plan 08 PgJournalStore.append(tx, event); plan 10 entity store parents and pg_rows builders"
provides:
  - "src/persistence/snapshots.py: PgPlanConstraintSnapshotStore (record, get, is_valid_for_live), write-once and hash-verified on every read"
  - "src/persistence/system_state.py: PgSystemStateStore (append, latest, latest_kill_gate_state) and frozen SystemStateRecord; journal event and state row in one transaction"
  - "SafeModeController.state_snapshot/rehydrate and LiveEnablementController.state_snapshot/rehydrate (plain mapping in, no persistence import)"
  - "Restart proof on PostgreSQL: SAFE_MODE, enablement and kill-gate state written through one engine are restored through a fresh engine and stores"
affects: [17-14, 17-15, phase-19, phase-20, phase-21, phase-22, phase-24]

actuals:
  tokens: 19700
  tasks: 3
  commits: 6
plan_head_before: 819957063926d9d4501f33ebb28d249cac253f06
plan_head_after: d7d22f346cdccfaf9bbbd65a2a5c2b1616d695d9

tech-stack:
  added: []
  patterns:
    - "Verify on read: parse the stored JSON, recompute its sha256 and compare every denormalized column; any disagreement is RowConflict (fail closed), is_valid_for_live turns it into False"
    - "Append-only versioned state: next version = max(version) + 1 read inside the transaction with no row lock; the unique (state_key, state_version) index is the arbiter and the loser raises RowConflict and rolls its journal row back"
    - "Controllers rehydrate from a plain Mapping validated field by field (ValueError on anything off); None means never persisted and gives the default"

key-files:
  created:
    - src/persistence/snapshots.py
    - src/persistence/system_state.py
    - tests/test_constraint_snapshot_pg.py
    - tests/test_system_state_pg.py
    - tests/test_controller_rehydrate.py
  modified:
    - src/reconcile/safe_mode.py
    - src/execution/enablement.py

key-decisions:
  - "Snapshot reads verify more than the digest: the denormalized columns (symbol, working type, margin type, leverage, equity, live-inputs status, both timestamps) must equal what the JSON implies, otherwise RowConflict. A digest-only check would let a tampered column that the live gate or an operator query reads stay unnoticed."
  - "is_valid_for_live answers False (not an exception) for a row that fails verification or does not parse; StoreUnavailable still propagates so the caller can translate it. get() itself still raises."
  - "System state values are str, bool or None only; ints, floats and nested values are refused before any write so a state document has one canonical form (canonical_bytes of the dict)."
  - "state_snapshot() reports the entry time and reason as None whenever the controller is not in SAFE_MODE (and the enable time and operator as None whenever disabled); rehydrate rejects the inconsistent combinations, so exit_safe_mode leaving stale _entered_* fields after a journal failure cannot be persisted as a half state."
  - "Rehydrate accepts exactly the three documented keys (unknown or missing key is ValueError); SAFE_MODE on requires both an entry time and a reason text, enabled requires a non-empty operator id and a UTC time."

requirements-completed: [EXEC-04, DOMN-01]

coverage:
  - id: D1
    description: "The exact sizing snapshot is stored per trade plan as canonical JSON plus sha256 (no float literal), write-once: replay is a no-op, a different snapshot is RowConflict with the row unchanged, a missing plan is ParentRowMissing, and record joins a caller's unit of work"
    requirement: EXEC-04
    verification:
      - kind: integration
        ref: "tests/test_constraint_snapshot_pg.py#test_record_then_get_round_trips_with_sha_and_no_float"
        status: pass
      - kind: integration
        ref: "tests/test_constraint_snapshot_pg.py#test_a_different_snapshot_for_the_same_plan_is_a_row_conflict"
        status: pass
      - kind: integration
        ref: "tests/test_constraint_snapshot_pg.py#test_a_snapshot_for_a_missing_plan_is_parent_row_missing"
        status: pass
    human_judgment: false
  - id: D2
    description: "A stored sha that does not match its JSON, a column that disagrees with the JSON, or JSON that is not a valid snapshot fails closed on read; the append-only trigger refuses a bypassing UPDATE"
    requirement: EXEC-04
    verification:
      - kind: integration
        ref: "tests/test_constraint_snapshot_pg.py#test_a_stored_sha_that_does_not_match_the_json_fails_closed"
        status: pass
      - kind: integration
        ref: "tests/test_constraint_snapshot_pg.py#test_the_append_only_trigger_refuses_an_update_that_bypasses_the_store"
        status: pass
    human_judgment: false
  - id: D3
    description: "is_valid_for_live is False for a missing plan, for today's INCOMPLETE snapshots, for stale and future-dated captures, and True only for a COMPLETE fresh one (exactly the TTL is still valid)"
    requirement: EXEC-04
    verification:
      - kind: integration
        ref: "tests/test_constraint_snapshot_pg.py#test_is_valid_for_live_is_true_only_for_a_complete_fresh_snapshot"
        status: pass
      - kind: integration
        ref: "tests/test_constraint_snapshot_pg.py#test_is_valid_for_live_is_false_for_todays_incomplete_snapshot"
        status: pass
    human_judgment: false
  - id: D4
    description: "SAFE_MODE, enablement and kill-gate state append with contiguous per-key versions and exactly one SYSTEM_STATE_CHANGED journal event written in the same transaction; a journal failure (before or after its insert) leaves neither row; latest returns the highest version"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_system_state_pg.py#test_a_failure_after_the_journal_insert_rolls_back_both_rows"
        status: pass
      - kind: integration
        ref: "tests/test_system_state_pg.py#test_append_creates_contiguous_versions_and_latest_returns_the_highest"
        status: pass
    human_judgment: false
  - id: D5
    description: "Two threads with separate engines released at a barrier after the next version was computed: exactly one append wins, the other raises RowConflict (its journal row rolled back), versions stay contiguous and a retry gets the next version; the table refuses UPDATE and DELETE"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_system_state_pg.py#test_two_concurrent_appends_for_one_key_yield_one_winner_and_a_row_conflict"
        status: pass
      - kind: integration
        ref: "tests/test_system_state_pg.py#test_the_append_only_trigger_refuses_a_bypassing_writer"
        status: pass
    human_judgment: false
  - id: D6
    description: "Restart rehydration on a fresh engine: a persisted SAFE_MODE blocks new entries with RECONCILIATION_REQUIRED, persisted enabled state restores operator and time and passes placement, a never-written key rehydrates to the defaults, and every KillGateState value reads back"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_controller_rehydrate.py#test_safe_mode_survives_a_restart_on_a_fresh_engine"
        status: pass
      - kind: integration
        ref: "tests/test_controller_rehydrate.py#test_enablement_survives_a_restart_on_a_fresh_engine"
        status: pass
      - kind: integration
        ref: "tests/test_controller_rehydrate.py#test_kill_gate_state_survives_a_restart_on_a_fresh_engine"
        status: pass
    human_judgment: false
  - id: D7
    description: "Malformed persisted state (missing or unknown key, wrong type, naive or non-UTC datetime, entered without time or reason, enabled without operator or time, inconsistent off state, non-mapping) raises ValueError in both controllers; rehydrating writes no journal event; constructor signatures and the persistence-import prohibition hold"
    requirement: DOMN-01
    verification:
      - kind: unit
        ref: "tests/test_controller_rehydrate.py#test_safe_mode_rehydrate_fails_closed_on_malformed_state"
        status: pass
      - kind: unit
        ref: "tests/test_controller_rehydrate.py#test_enablement_rehydrate_fails_closed_on_malformed_state"
        status: pass
      - kind: unit
        ref: "tests/test_controller_rehydrate.py#test_controllers_do_not_import_the_persistence_layer"
        status: pass
    human_judgment: false

duration: 25 min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 13: Constraint Snapshot and System State Persistence Summary

**Each trade plan's sizing constraints are now stored once and verified (sha256 plus every denormalized column) on every read, SAFE_MODE / enablement / kill-gate state is an append-only, journaled, versioned log that survives a restart on a fresh PostgreSQL engine, and both controllers can be rebuilt from it with malformed state failing closed instead of defaulting.**

## Performance

- **Duration:** about 25 min (about 17 of them the full-suite run)
- **Completed:** 2026-10-01
- **Tasks:** 3 (all TDD, RED committed before GREEN)
- **Files:** 5 created, 2 modified

## Accomplishments

- `PgPlanConstraintSnapshotStore`: `record` is `INSERT ... ON CONFLICT (trade_plan_id) DO NOTHING` followed by a sha256 and JSON comparison with the stored row (replay no-op, different snapshot `RowConflict`, missing plan `ParentRowMissing`, optional `tx`). `get` parses the stored JSON with `parse_snapshot_json`, recomputes `snapshot_sha256`, and checks the eleven stored columns against the values derived from the JSON. `is_valid_for_live` returns False for a missing, unverifiable, INCOMPLETE, stale or future-dated snapshot. Every snapshot written today is INCOMPLETE (margin type, leverage and equity are UNKNOWN until Phases 21-22), so none is valid for live placement.
- `PgSystemStateStore(db, journal)`: `append(key, state, *, now_utc, tx=None)` validates the key and the scalar-only state, computes the next version inside the transaction, appends the `SYSTEM_STATE_CHANGED` journal event (entity `SystemState`, id the key, correlation `system_state:<key>`) and then inserts the state row that references it. `latest(key)` and `latest_kill_gate_state()` (ValueError outside `KillGateState`). No update or delete method.
- `SafeModeController` and `LiveEnablementController` gained `state_snapshot()` and a `rehydrate` classmethod; constructors, enter/exit/enable/disable and journaling are untouched, and neither module imports `src.persistence`.
- Restart tests build state through one engine, dispose it, and read it through a brand new engine and stores, then assert the rehydrated controllers behave as before the restart.

## Task Commits

1. Task 1 RED: `c7438bc` test(17-13): RED for write-once plan constraint snapshot store (collection failed: module absent)
2. Task 1 GREEN: `78d5b81` feat(17-13): write-once plan constraint snapshot store with hash verification
3. Task 2 RED: `ae0a763` test(17-13): RED for append-only system state store written through the journal (collection failed: module absent)
4. Task 2 GREEN: `4299355` feat(17-13): append-only system state store written through the journal
5. Task 3 RED: `7ada0a2` test(17-13): RED for controller state snapshots and rehydrate across a restart (`AttributeError: ... no attribute 'rehydrate'`)
6. Task 3 GREEN: `d7d22f3` feat(17-13): controller state snapshots and rehydrate constructors

## Verification (real runs)

PostgreSQL runs used the dev server (`TEST_DATABASE_URL` set inline; the credential is not in any file). The precondition probe exited 0.

- Task 1: `TRADING_CI_STRICT=1 pytest tests/test_constraint_snapshot_pg.py -x -q -rs -p no:cacheprovider` exit 0, 16 tests, no SKIPPED line.
- Task 2: `TRADING_CI_STRICT=1 pytest tests/test_system_state_pg.py -x -q -rs` exit 0, 28 tests, no SKIPPED line, run 3 times (the barrier race is deterministic by construction: both racers wait inside the journal append, after the next version was computed).
- Task 3: `TRADING_CI_STRICT=1 pytest tests/test_controller_rehydrate.py -x -q -rs` exit 0, 62 tests, no SKIPPED line. The three new modules together: 106 passed.
- Existing suites: `tests/test_reconcile.py tests/test_execution_enablement.py tests/test_drills.py tests/test_kill_gate_gates.py` plus `test_journal_failure_paths`, `test_persistence_journal_pg`, `test_phase8_audit_reviewfix`, `test_execution_gates`, `test_execution_health`: 151 passed.
- `mypy src`: no issues in 132 source files. `ruff check`: all checks passed. `ruff format --check src tests`: 303 files already formatted.
- Acceptance greps: `def is_valid_for_live` one line in `snapshots.py`; `snapshot_sha256` on several lines; `def (update|delete)` in `system_state.py` prints nothing; `self._journal.append` present; `def rehydrate` in both controllers; `^(from|import) src\.persistence` in the two controllers prints nothing.
- Plan-level full suite: `pytest -q -rs` (no marker filter) with `TEST_DATABASE_URL` set: 3592 passed, 21 skipped, exit 0. The 21 skips are the docker image-not-built set (`test_docker_backup_drill`, `test_docker_cutover`, `infra_helpers`) plus one each in `test_analytics_files` and `test_bootstrap` (pre-existing platform skips); none is a PostgreSQL skip. Not run as one strict (`TRADING_CI_STRICT=1`) full suite; strict runs were per module as listed.
- Repo-root `ruff format --check` (no path) still reports only `.planning/phases/17-operational-persistence-layer/17-RESEARCH.md` (pre-existing, logged in `deferred-items.md` since 17-01), which is why the plan's literal `ruff format --check` was run as `ruff format --check src tests`.

## Deviations from Plan

None - plan executed exactly as written.

Judgment calls inside the plan's latitude: (a) `get` also verifies the denormalized columns, not only the digest (stricter than the plan's "hash verification"); (b) `is_valid_for_live` maps a failed verification to False rather than raising, since the plan states it "returns False" for unusable snapshots; (c) state values are restricted to `str | bool | None` (the plan's type hint) and the store refuses ints and floats; (d) the barrier in the race test sits inside a wrapper journal's `append` so the conflict is deterministic, which also proves the loser's journal row rolls back.

## Known Stubs

None. (Snapshots with UNKNOWN margin type, leverage and equity are intended, not stubs: Phases 21-22 supply them, and an INCOMPLETE snapshot is invalid for live by design.)

## Threat Flags

None. T-17-34 mitigated (state rows plus rehydrate constructors; restart tests on a fresh engine for SAFE_MODE, enablement and kill gate). T-17-35 mitigated (write-once table with the append-only trigger, sha256 and columns verified on every read, mismatch fails closed). T-17-36 mitigated (journal event and state row in one transaction; rollback tests for a failure before and after the journal insert; the race loser's journal row rolls back). T-17-SC: no packages installed.

## Issues Encountered

None blocking. For later phases:

- Nothing writes these stores yet: no process calls `PgSystemStateStore.append` after a SAFE_MODE or enablement change, and nothing reads `latest` at startup. That wiring is Phase 20 (SAFE_MODE) and Phase 24 (enablement), as the plan prohibits; the controllers' journal-first semantics (including the 17-08 finding under a failing journal) are unchanged.
- The persisted state and the controller's own journal event are two separate transactions when written through `PgJournalStore.record` and then `append`; the guarantee of this plan is that each state row and its `SYSTEM_STATE_CHANGED` event are atomic, not that the controller's own event and the state row are. A caller that wants all three atomic would pass a shared `tx` (the stores accept one); that choice belongs to the Phase 20 wiring.
- For D051 (plan 15): snapshot read verification covers columns as well as the digest; system-state value restriction to `str | bool | None`; `state_snapshot` normalizes entry/enable fields to None when off/disabled; `rehydrate` formats are owned by the controllers.

## Next Phase Readiness

Plan 17-14 can rely on the stores as written. Phase 19 revalidates the snapshot with `is_valid_for_live` before placement; Phases 21-22 replace UNKNOWN margin type, leverage and equity so a snapshot can become COMPLETE; Phase 20 wires SAFE_MODE persistence and startup rehydrate.

## Self-Check: PASSED

- Files exist: `src/persistence/snapshots.py`, `src/persistence/system_state.py`, `tests/test_constraint_snapshot_pg.py`, `tests/test_system_state_pg.py`, `tests/test_controller_rehydrate.py`, this SUMMARY.
- Commits exist: `c7438bc`, `78d5b81`, `ae0a763`, `4299355`, `7ada0a2`, `d7d22f3`; measured commit count 6 from the recorded plan head `8199570`.
