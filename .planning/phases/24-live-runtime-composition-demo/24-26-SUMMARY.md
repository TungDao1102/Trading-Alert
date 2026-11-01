---
phase: 24-live-runtime-composition-demo
plan: 26
subsystem: live-startup
status: complete
tags: [start-sequence, restart, rehydrate, gate-bootstrap, spill-sentinel, ops-03, exec-03, phase-24]
requirements-addressed: [OPS-03, EXEC-03]
requires: [24-11, 24-12, 24-13, 24-17, 24-18, 24-20, 24-22]
provides:
  - "src/live/startup.py: START_STEPS, START_STEP_GROUP, StartupPorts, RecoveryPorts, run_start_sequence, StartupOutcome, StepRecord"
  - "src/live/startup.py: restored_plans_builder, resting_entry_from_intent, rebuild_client_id_index, close_attempts_reader, RestoreIntentReader, protection_correlation, close_correlation"
  - "src/live/startup.py: write_spill_sentinel, check_spill_sentinel, alembic_head_matches, AlembicRevisions"
affects: [24-27, 24-28, 24-29, 24-32]
key-files:
  created:
    - src/live/startup.py
    - tests/test_live_start_sequence.py
    - tests/test_live_restart_rehydrate.py
  modified: []
key-decisions:
  - "The start sequence is data: 18 named steps in the nine D-08 groups, one journaled LIVE_STARTUP_STEP row each (step, group, outcome, a fixed reason code; never a message or a value)."
  - "Holds (nothing started): CONFIG, GATE, ALEMBIC, SAFE_MODE and ENABLEMENT (no controller to run on). Every later failure continues in SAFE_MODE with monitoring running and enable_demo never called."
  - "A failing step enters SAFE_MODE only when the controller is not already in it, so a more informative persisted reason is never overwritten by a generic STARTUP_<STEP>_FAILED."
  - "Rows of steps 1 to 3 are buffered until the Alembic check passes (the journal table may not exist before it); on a hold they go to the log only."
  - "The gate is initialized only with --initialize-gate-state and an operator id, only when no state file exists (a corrupt file counts as existing), and gate.restore() must report RESTORED_DURABLE or the start holds."
  - "Kill-gate state is a port with no default: an unreadable or unevaluated state makes enable_demo refuse and journal LIVE_ENABLE_REFUSED; the process keeps running DISABLED (owner question below)."
plan_head_before: e60011eeb21a47429b0f611d0334eb2cbe2b7275
plan_head_after: 7d0d77ee8f6e5bd49458d984bbaa21ff20bf1b8b
commits: 2
actuals:
  tokens: 27000
  tasks: 3
  commits: 2
completed: 2026-11-01
---

# Phase 24 Plan 26: Start sequence and restart rehydrate Summary

**The live process now has one safe start order (config, REST gate, Alembic head, SAFE_MODE, enablement, snapshots, spill sentinel, drift, exchange info, recovery, one reconcile tick, confirm expiry, alert requeue, stream, bot, scheduler, health, DEMO enable), every step journaled and fail closed, plus the glue that rebuilds the coordinator registry and the client-id index from durable sources after a restart.**

## What was built

- `src/live/startup.py`
  - `START_STEPS` / `START_STEP_GROUP` and `run_start_sequence(ports, *, now_utc) -> StartupOutcome` (admitted, held step/code/message, safe_mode_reasons, started_tasks, enabled, enable_reason, steps, degraded_steps, the recovery and reconcile reports). `StartupPorts` holds every step as a sync-or-async callable; plan 24-27 binds it to the composed objects. Step 7 calls the real `run_startup_recovery`.
  - Gate rule: no state file and no flag holds with a message naming `--initialize-gate-state --operator-id`; the flag with an existing (or corrupt) file is refused and the file is untouched; the flag needs an operator id; `gate.restore()` runs before any later step and anything but RESTORED_DURABLE holds.
  - Spill sentinel (20-DEFERRED row 43): written at the first install, checked on every later start; a missing or unparsable sentinel enters SAFE_MODE `RESTORE_INCONSISTENT`. The name starts with a dot so `LocalSpill.scan` ignores it (tested).
  - Enable: DEMO only, last, after a health verdict and a kill-gate read; LIVE keeps the human step (rows SKIPPED). A persisted SAFE_MODE, any degraded step or a journal write failure blocks it.
  - Rehydrate glue: `resting_entry_from_intent` rebuilds the `RestingEntry` exactly as `execute_approved_plan` built it (snapped SL trigger, raw TP levels, deterministic ids; SENT/UNKNOWN rows become `entry_state_unknown=True`); `restored_plans_builder` runs `rebuild_plan` per restorable entry and fills the `ClientIdIndex` (entry id and every protective algo id) before it returns, so the index is complete before the stream starts; a missing plan or snapshot raises `RestoreSourceMissing` (recovery enters DB_FAILURE, the coordinator stays unrestored, no entry opens). `close_attempts_reader` groups EMERGENCY_CLOSE rows by plan. The correlation prefixes are pinned against their producers.
- `tests/test_live_start_sequence.py` (49 tests): exact call order and the nine groups, rows carry codes only, buffered first rows, 9 hold cases, the gate bootstrap, the sentinel, 13 parametrized failing steps (recovery, four reconcile outcomes, expiry, requeue, stream, bot, scheduler, snapshots, drift, exchange info), SAFE_MODE store failure, persisted SAFE_MODE keeping its reason, journal failure, LIVE mode, unevaluated kill gate, failing health, and a live-rig tracer: a CONFIRM during step 8 reaches the real manager while DISABLED and ends `NO_TRADE DISABLED` with zero `place_entry` at every step row; after the sequence exactly one entry is placed.
- `tests/test_live_restart_rehydrate.py` (13 tests): over the live rig, a restart (new SafeModeController.load, coordinator with `restore_required=True`, closer, index, router, confirm flow over the same stores) loads SAFE_MODE with its reason, rebuilds the resting entry with fields equal to run 1's record, registers the index, routes a fill as a known order (no UNKNOWN_STREAM_ORDER) and places the stop once; a PROTECTED plan comes back PROTECTED with no re-placed stop and its algo id known; an entry sent with an ambiguous result stays UNKNOWN with SAFE_MODE (never REJECTED, D080) and is tracked with `entry_state_unknown`; an outstanding confirm expires with RUNTIME_RESTART, the approval row stays APPROVED and a press on the old card places nothing; through `run_start_sequence` the registry and index are complete before the stream, bot and scheduler start.

## Verification

- `uv run pytest -m "not docker"` over tests/test_live_start_sequence.py, test_live_restart_rehydrate.py, test_startup_recovery.py, test_intent_recovery.py, test_intent_recovery_unknown_entry.py, test_live_ast_guards.py, test_live_tracer.py, test_live_enablement_wiring.py, test_no_unratified_defaults.py, test_agents_md.py, test_domain_no_float.py, test_paper_shadow_isolation.py: all pass (no PostgreSQL; `TEST_DATABASE_URL` unset).
- `uv run mypy src/live` (23 files) clean; scoped ruff check and format clean; `git grep -n create_all -- src/live` prints nothing; `git diff --exit-code -- pyproject.toml uv.lock` clean.
- Not run: the full suite and the PostgreSQL tests (orchestrator).

## Deviations from Plan

**1. [Process] Tasks 1 and 2 are one commit.** They share both files and the failure rules and step rows are one design; the tests of both were written together, so there is one `feat` commit (`20fa07db`) for them and one for Task 3 (`7d0d77ee`). TDD note: the implementation was written before its tests in this run; the tests include negative controls (hold cases, 13 failing steps, a tracer that would see a placement).

**2. [Design] `restored_plans_builder` takes a `RestoreIntentReader`, not just `ExecutionIntentStore`.** The production intent store cannot supply what a rebuild needs: `list_unresolved_intents` omits ACKED rows (a resting or filled entry that was acknowledged), and `PgExecutionStateStore` has no `get_intent` (the in-memory fake has one as a test-side extra, and `rebuild_plan` needs the STOP_LOSS row). See hand-off 1.

**3. [Design] A persisted constraint snapshot lacks the A8 verified values.** The `RestingEntry` of run 1 carried `margin_type`, `leverage` and `equity_used` filled in memory at placement; a rebuild uses the persisted write-once snapshot, where they are None. The test compares every economic field and not the snapshot. See hand-off 3.

## Hand-offs and open questions

1. **For plan 24-27 or 24-28 (PostgreSQL stores):** `PgExecutionStateStore` needs two reads: `restorable_entries()` (ENTRY rows in SENT, UNKNOWN and ACKED, bounded to plans that have not ended or the list grows forever) and `get_intent(approval_id, role)`. Without them the real `RestoreIntentReader` cannot be bound and a restart would not re-track an acknowledged resting entry. The builder also needs `plan_for` (the stored plan), `snapshot_for` (`PgPlanConstraintSnapshotStore.get`), and `transition_events_for` (`PgJournalStore.list_by_correlation(protection_correlation(plan_hash))`); `close_attempts_reader` takes `list_by_correlation` the same way. Use `protection_correlation` / `close_correlation` from this module.
2. **OWNER QUESTION (kill-gate state source for `enable_demo`):** nothing writes a `KILL_GATE` system-state row (confirmed from the 24-22 report; `latest_kill_gate_state()` returns None on a fresh database). `StartupPorts.kill_gate_state` has no default, so on a real start `enable_demo` refuses with `KILL_GATE_UNEVALUATED`, journals `LIVE_ENABLE_REFUSED`, and the process runs DISABLED (monitoring, bot and scheduler up). The owner must decide the source (an evaluated state written by the analytics job, or an explicit DEMO rule) before a Demo start can enable itself. The tests supply `WITHIN_BUDGET` as a TEST_ONLY value only.
3. **For 24-27:** `build_execution_path` builds the coordinator without `restore_required=True`; the production wiring must set it (the tests build their own) and must pass the same coordinator and closer to `RecoveryPorts`. Restored entries use the persisted snapshot (deviation 3); if the A8 values matter after a restart the snapshot store would have to persist them.
4. **For 24-27 (wiring still to bind, per the hand-off list):** the REST-error counter, DB-write tracker, ReconcileObserver feed and TelegramDeliveryObserver are not touched here. The `health_verdict` port must run `health_tick_once` after the stream is up; the first tick before any tracked write, send or reconcile is correctly not OK. `requeue_alerts` must read the `operational_alerts` rows and call `requeue_at_start`; `expire_confirms` is `ConfirmFlow.expire_on_restart` of a fresh flow. `alembic_revisions` needs the DB's `alembic_version` and the script head (`tests/pg_support.alembic_head_revision` is the analog); `--hold-on-refusal` should consume `StartupOutcome.held_step/held_code/held_message`.
5. **Journal volume:** one `LIVE_STARTUP_STEP` row per step (about 18 per start) plus the ten health rows and one verdict.
6. **Known limit:** a step port that hangs (for example a REST call with no timeout) blocks the sequence; the sequence adds no timeouts because a timeout value is an owner number.

## Known Stubs

None.

## Threat Flags

None new. T-24-79 (bot and stream start only after the rebuild; zero `place_entry` before the last step: tested over the real manager), T-24-80 (explicit flag, refused when a file exists, never silently), T-24-81 (spill sentinel, SAFE_MODE RESTORE_INCONSISTENT), T-24-82 (UNKNOWN stays UNKNOWN; tested), T-24-SC (`git diff --exit-code -- pyproject.toml uv.lock` exits 0) are mitigated and tested.

## Self-Check: PASSED

- FOUND: src/live/startup.py, tests/test_live_start_sequence.py, tests/test_live_restart_rehydrate.py
- FOUND commits 20fa07db, 7d0d77ee (ancestors of HEAD)
