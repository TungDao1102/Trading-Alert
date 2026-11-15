---
phase: 24-live-runtime-composition-demo
plan: 10
subsystem: live
tags: [scheduler, cadence, virtual-time, execution-limits, phase-24]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: "24-04 src/live package and tests/test_live_ast_guards.py; 24-01 owner answers (cadence table accepted, no overrides)"
provides:
  - "src/live/scheduler.py: TaskSpec, TaskEvent, TaskResult, Scheduler, LiveCadences, DAILY_LOSS_AGE_DIVISOR"
  - "tests/test_live_scheduler.py: 22 virtual-time tests"
affects: [24-11, 24-12, 24-13, 24-14, 24-15, 24-16, 24-17]

tech-stack:
  added: []
  patterns: ["one asyncio task per spec; wait = earlier of injected sleep, wake event and stop event", "outcome-change journaling through an injected async writer", "errors recorded by exception class name only"]

key-files:
  created:
    - src/live/scheduler.py
    - tests/test_live_scheduler.py
  modified: []

key-decisions:
  - "Interval is measured from the end of a run (fixed delay); a wake restarts the period, so the next periodic run is one interval after the woken run"
  - "A wake set while the task is running is kept and triggers an immediate further run (a fill during a protection step is not lost)"
  - "Journal kinds: first_run (ok or failed, carries the class), failure (after ok, or a different class), recovery (first success after a failure); a repeated same-class failure is not journaled again"
  - "A None drift.periodic_remeasure_interval_seconds is reported through ExecutionLimitsNotConfigured by its dotted key, with the execution keys that are unset"
  - "daily_loss_age_divisor defaults to the module constant DAILY_LOSS_AGE_DIVISOR = 2 (D087 relationship) and values below 2 raise ValueError"

patterns-established:
  - "Later plans add periodic work as TaskSpec(name, run, interval=cadences.<field>[, wake=event])"

requirements-completed: [EXEC-02]  # not marked in STATE/REQUIREMENTS: the orchestrator owns those files in this wave

plan_head_before: 18b04991c750901f9ff1fcde643df585653bc267
plan_head_after: 857cff33c42ebc1ea42454c2b76d3847bc4c4198
actuals:
  tokens: 14000
  tasks: 2
  commits: 1
status: complete
completed: 2026-10-31
---

# Phase 24 Plan 10: Scheduler primitive Summary

**One scheduler primitive (injected clock and sleep, wake event, per-task failure isolation, class-name-only errors, outcome-change journaling) plus `LiveCadences.from_limits`, which derives every periodic live interval from loaded limits and refuses unset keys by name.**

## Accomplishments

- `Scheduler.run()` runs one loop per `TaskSpec`; a task exception is caught, recorded by class name, turns that task's `TaskResult.healthy` false until its next success and never affects the other tasks. `CancelledError` propagates (and cancelling `run()` cancels every loop); `stop()` ends all loops after their current run.
- `results()` exposes `last_started_utc`, `last_ok_utc`, `last_error_class` and `consecutive_failures` for the liveness stamp and the health probes.
- Journal events go through the injected async `record`; a `record` that raises is logged by class name and the loop continues.
- `LiveCadences.from_limits(execution_limits, binance_limits)`: protection step, reconcile tick, confirm-TTL sweep, alert drain, health, liveness stamp and scheduled-cancel check = `reconcile.tick_interval_ms`; drift re-measure = ratified `drift.periodic_remeasure_interval_seconds`; day-risk backfill = `account.max_daily_loss_age_ms` / 2 (D087); lot-filter refresh = `reconcile.lot_filter_refresh_interval_ms`. Unset keys raise `ExecutionLimitsNotConfigured` naming all of them.
- The module has no wall-clock call and no `asyncio.sleep` (the AST guard and `git grep` both clean).

## Verification

- `uv run pytest -m "not docker" tests/test_live_scheduler.py tests/test_live_ast_guards.py tests/test_no_unratified_defaults.py`: 112 passed (22 of them new).
- `uv run ruff check` and `ruff format --check` on both files: clean. `uv run mypy src/live`: no issues.
- `git diff --exit-code -- pyproject.toml uv.lock`: clean (no dependency added).
- No PostgreSQL test was run (none belongs to this plan).

## Deviations from Plan

**1. Task commits merged.** Tasks 1 (tracer) and 2 (cadences) were written together and committed as one commit (`857cff33`) instead of one commit per task. Tests were written before the implementation; both tasks' tests and code are in that commit. No behaviour is affected.

No Rule 1-3 fixes were needed. The tracer feedback gate (re-run of the verify command end to end) passed before the final commit.

## Known Stubs

None.

## Threat Flags

None. Mitigations in place: T-24-24 (per-task isolation, tests), T-24-25 (intervals only from loaded keys, no default, no-defaults guard passes), T-24-26 (class name only, asserted in a test), T-24-SC (no dependency change).

## Self-Check: PASSED

- src/live/scheduler.py and tests/test_live_scheduler.py exist; commit 857cff33 is on the branch.
