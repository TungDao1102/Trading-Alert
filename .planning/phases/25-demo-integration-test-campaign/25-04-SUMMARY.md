---
phase: 25-demo-integration-test-campaign
plan: 04
subsystem: live-health
tags: [R-25, D-11, D-13, health, journal-volume, tdd, OPS-01]
requires: []
provides:
  - "health_tick_once journals the ten HEALTH_CHECK rows on the first tick of a producer and afterwards only for a check whose status changed; one HEALTH_VERDICT row per tick is kept"
affects: [25-12]
tech-stack:
  added: []
  patterns:
    - "per-check last-journaled status on the producer, advanced only after that row's record call returned"
key-files:
  created:
    - tests/test_live_health_journal_volume.py
  modified:
    - src/live/health.py
key-decisions:
  - "The remembered status lives on LiveHealthProducer (_journaled_status), not on a module global: the start-sequence call and the scheduled call run on the same producer (wiring.health), so they share it."
  - "Only the status is compared, not the detail text (the detail carries a changing age), otherwise the rule would write every tick."
requirements-completed: [OPS-01]
status: complete
actuals:
  tokens: 2500
  tasks: 2
  commits: 3
plan_head_before: 8e7fb0f29508d873fc89bc9a6cd7cbd6b1f3c252
plan_head_after: bf1448c4abbd37b0139ef076fcafa3b93b025f48
---

# Phase 25 Plan 04: On-change HEALTH_CHECK journaling Summary

R-25 closed test-first: an idle live process now journals 1 HEALTH_VERDICT row per 15 s tick plus the ten HEALTH_CHECK rows once, instead of 11 rows per tick (about 5,760 health rows a day instead of about 63,000). The verdict row stays on every tick, so `DbWriteTracker` is refreshed on an otherwise quiet account and `db_writes` keeps passing (25-RESEARCH Pitfall 5).

## Commits

| Task | Phase | Commit | Files |
|------|-------|--------|-------|
| 1 | RED | c52752b5 | tests/test_live_health_journal_volume.py |
| 1 | GREEN | afd87e93 | src/live/health.py |
| 2 | test | bf1448c4 | tests/test_live_health_journal_volume.py |

## RED evidence

At HEAD before the change, `uv run pytest -m "not docker" tests/test_live_health_journal_volume.py` failed the tracer for the planned reason (ten idle ticks, ten verdict rows were already correct):

```
>       assert len(checks) == 10
E       assert 100 == 10
FAILED tests/test_live_health_journal_volume.py::test_ten_idle_ticks_journal_ten_verdicts_and_the_ten_check_rows_once
```

After the change it passes, including `db_writes == PASS` on tick 10.

## What changed

- `src/live/health.py`: `LiveHealthProducer._journaled_status: dict[str, str]` (empty at construction). In `health_tick_once`, a check row is skipped when the remembered status equals the result's status; otherwise it is written and the status is remembered only after `record` returned (a failed write leaves it unset, so the next tick writes it again). The producer's `_latest` is still stored before any write; the verdict row is still written every tick. Module and function docstrings name R-25.
- `tests/test_live_health_journal_volume.py`: a `Rig` over the existing `Parts` fakes with a virtual clock and a `DbWriteTracker.track`-wrapped recording journal (no wall clock, no network). Six tests:
  1. ten idle ticks: 10 verdicts, 10 check rows (all on tick 1), `db_writes` PASS;
  2. a status flip PASS->FAIL on tick 4 and back on tick 6 writes exactly one extra row each, for that check only;
  3. a failing first check-row write propagates, the verdict was kept, the row is written again on tick 2;
  4. a journal that fails for 75 virtual seconds makes `db_writes` FAIL (no-trade), the tracker stamp stays cleared;
  5. a stamp older than 60 s reads stale and recovers on the next write;
  6. the start-sequence call and the scheduled call share the producer (ten rows, then none).

## Verification (agent-run)

- `uv run pytest -m "not docker" tests/test_live_health_journal_volume.py tests/test_live_health.py tests/test_execution_health.py tests/test_live_ast_guards.py tests/test_phase24_gate.py -q`: all passed (6 new tests, existing health tests unchanged).
- `uv run pytest -m "not docker" tests/test_live_start_sequence.py tests/test_live_wiring.py tests/test_journal_failure_paths.py -q`: all passed (callers of `health_tick_once`).
- `uv run ruff check` and `uv run ruff format --check` on both files: clean. `uv run mypy src`: no issues in 291 files. `uv lock --check`: ok; `git diff --exit-code -- pyproject.toml uv.lock`: clean.

## Deviations from Plan

None - plan executed as written. Task 2 required no source change: all four planned behaviours (plus the stale-stamp case) passed against the Task 1 implementation.

Observation (not a defect): because `DbWriteTracker` clears its stamp on any failed write, a single failed check-row write makes `db_writes` read FAIL on the next tick (before any write of that tick) and PASS on the one after; that second tick therefore writes one extra `db_writes` row. Test 3 pins this. The ">60 s of failing" case in test 4 is thus FAIL earlier than 60 s, which is the tracker's existing, stricter behavior.

## Known Stubs

None.

## Not covered by an agent-run test

- Behavior on a real PostgreSQL journal and over the multi-week soak (the daily row volume figure is arithmetic: 15 s cadence, one verdict per tick = 5,760 rows a day). The owner-run soak will show it.
- A process restart rebuilds the producer, so the first tick after a restart journals the ten check rows again (intended: a fresh baseline per process).

## Threat Flags

None. No new endpoint, auth path or schema; no package added.

## Self-Check: PASSED

- tests/test_live_health_journal_volume.py: FOUND
- src/live/health.py: FOUND
- Commits c52752b5, afd87e93, bf1448c4: FOUND in HEAD history
