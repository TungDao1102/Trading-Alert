---
phase: 20-reconcile-safe-mode-hardening
plan: 06
subsystem: reconcile
tags: [safe-mode, persistence, postgres, fail-closed, restart, system-state]

requires:
  - phase: 17-operational-persistence
    provides: "PgSystemStateStore (append-only SAFE_MODE key) and SafeModeController.state_snapshot / rehydrate"
provides:
  - "SafeModeStateStore Protocol, SafeModeController(state_store=...), SafeModeController.load, is_durable, SAFE_MODE_STATE_UNREADABLE"
  - "PgSafeModeStateStore over the system_state_events log (no DDL change)"
affects: [20-12 reconcile loop, 20-15 operator-id exit, 20-19 startup, 20-24 GLOSSARY 9.4]

actuals:
  tokens: 9600
  tasks: 3
  commits: 6
plan_head_before: e64940d55a67316fed2cebdc253f9e5f6398b95f
plan_head_after: 867d79a06ea6471042f903c74bb22e5050204906

tech-stack:
  added: []
  patterns:
    - "Protocol seam: pure reconcile module takes a store Protocol, the persistence layer adapts it (no src.persistence import in src/reconcile)"
    - "Fail-closed load: any store or parse error starts the controller IN SAFE_MODE with a dedicated reason"
    - "Pending-persist flag: memory flips first, a failed save stays pending and is retried by the next enter call"

key-files:
  created:
    - src/persistence/safe_mode_store.py
    - tests/test_safe_mode_persistence.py
    - tests/test_safe_mode_persistence_pg.py
  modified:
    - src/reconcile/safe_mode.py
    - tests/test_controller_rehydrate.py

key-decisions:
  - "The in-memory flag flips first, then journal, then save; a save (or journal) failure propagates with the controller still in SAFE_MODE (D-14, F-127)."
  - "A failed save leaves _persist_pending set, so the next enter_safe_mode call with the SAME reason retries the save without a new journal transition."
  - "load journals SAFE_MODE_STATE_UNREADABLE best-effort with error_type only; a journal failure there is swallowed because the fail-closed state is already set."
  - "A load that failed is not re-saved: a restart reads whatever the store really holds; operator exit semantics stay with plan 20-15."

patterns-established:
  - "Store errors are never rendered into journal payloads: only type(exc).__name__ (poisoned-message test)."

requirements-addressed: [OPS-01]

duration: 35min
completed: 2026-10-21
status: complete
---

# Phase 20 Plan 06: Durable SAFE_MODE Summary

**SAFE_MODE is saved to the PostgreSQL system-state log on every enter and restored by `SafeModeController.load`, which starts IN SAFE_MODE (`SAFE_MODE_STATE_UNREADABLE`) on any read or parse error, so a restart can never read SAFE_MODE as off.**

## Performance

- **Duration:** about 35 min
- **Tasks:** 3 of 3 (Task 1 tracer, Tasks 2-3 auto, all TDD with a RED commit first)
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments

- `src/reconcile/safe_mode.py`: `SafeModeStateStore` Protocol (`save(state, *, now_utc)`, `load()`), optional `state_store` constructor keyword (default None, the 24 existing callers keep working), `is_durable`, classmethod `load(*, adapter, journal, state_store, now_utc, compare_fn=None)` and `SAFE_MODE_STATE_UNREADABLE`. The module still imports nothing from `src.persistence`.
- `enter_safe_mode` refuses an empty or non-string reason (IN-13), flips memory, journals as before, then saves `state_snapshot()`; both a first entry and a re-entry with a new reason are saved.
- `src/persistence/safe_mode_store.py`: `PgSafeModeStateStore(system_state)` maps `save`/`load` onto `PgSystemStateStore(SystemStateKey.SAFE_MODE)`. No retry, no DDL, no migration; typed persistence errors propagate unchanged.
- Tests: 27 unit tests on fakes (`tests/test_safe_mode_persistence.py`) and 6 PostgreSQL tests (`tests/test_safe_mode_persistence_pg.py`) covering every behavior bullet, including the poisoned-message case (`RuntimeError("password=hunter2")` never appears in any journal payload).

## Task Commits

| Task | RED | GREEN |
|---|---|---|
| 1 Tracer: enter persists, load restores | 55c1ee2b | 0572f239 |
| 2 Fail closed | f5371446 | bc60ea9b |
| 3 PgSafeModeStateStore | 41d2257f | 867d79a0 |

Tracer gate: the Task 1 verify command (`tests/test_safe_mode_persistence.py` + `tests/test_controller_rehydrate.py`) was re-run green before Task 2 began. RED evidence: Task 1 and Task 3 failed at collection (missing symbol/module), Task 2 showed 15 failing tests against the happy-path implementation (the staged Task 1 implementation had no pending-retry, no fail-closed load and no reason check).

## Verification (executed, this machine, PostgreSQL via TEST_DATABASE_URL; no [DEMO] claim)

- `uv run pytest -m "not docker" tests/test_safe_mode_persistence.py tests/test_controller_rehydrate.py tests/test_reconcile.py tests/test_drills.py -x`: all passed (119 tests, no failures).
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_safe_mode_persistence_pg.py -x -rs`: 6 passed, 0 skipped.
- `uv run mypy src`: no issues in 216 source files. `uv run ruff check` and `uv run ruff format --check`: clean.
- `git diff --exit-code -- pyproject.toml uv.lock` clean; `git status --porcelain -- src/db/alembic/versions` empty.
- Also ran `tests/test_phase18_gate.py tests/test_phase19_gate.py` (they scan src/tests trees): passed. The full suite was not run (orchestrator owns it).

## Deviations from Plan

**1. [Rule 3 - Blocking] Edited `tests/test_controller_rehydrate.py` (one assertion)**
- **Found during:** Task 1
- **Issue:** `test_constructor_signatures_are_unchanged` pins `SafeModeController.__init__` parameters to `[self, adapter, journal, compare_fn]`. The plan requires the new `state_store` constructor keyword, so that test cannot pass unedited; the plan's acceptance criterion "test_controller_rehydrate.py passes unedited (git diff --exit-code)" is therefore unsatisfiable together with its own artifact list.
- **Fix:** the assertion now lists `state_store` as the last parameter and checks its default is None (4-line diff, test name kept). Every other test in that file is untouched and passes.
- **Files modified:** tests/test_controller_rehydrate.py
- **Commit:** 0572f239
- **Note for the orchestrator:** the `git diff --exit-code -- tests/test_controller_rehydrate.py` acceptance check will report a diff by design. A later plan editing the same assertion line would conflict on merge.

**2. [Rule 1 - Bug in test design] Unreachable-database test uses a lazy engine**
- **Found during:** Task 3
- **Issue:** `make_sync_engine` probes the server at creation and raises `StoreUnavailable` itself, so "a store over an unreachable database" could not be built with it.
- **Fix:** the test builds `sqlalchemy.create_engine` on a closed local port (`127.0.0.1:1`, no credentials) wrapped in `OperationalDatabase`, which is what a database lost after startup looks like. The journal payload there is `{"error_type": "StoreUnavailable"}`.
- **Commit:** 867d79a0

**3. Additional behavior beyond the plan text:** the pending-persist flag is also set when the journal write fails (not only the save), so a journal failure on first entry is also followed by a save retry on the next call. This only makes the controller retry more, never less.

Otherwise the plan was executed as written. `SAFE_MODE_TICK_SECONDS` and `exit_safe_mode` are untouched (plan 20-15). No `datetime.now` fallback was added to new code (the pre-existing fallbacks in `enter_safe_mode`/`exit_safe_mode` are unchanged).

## Auth gates

None.

## Known Stubs

None.

## Threat Flags

None. T-20-12 (restart clears SAFE_MODE) and T-20-13 (information disclosure in the journal payload on load failure) are mitigated and tested; T-20-SC: no dependency change.

## Notes for downstream plans

- `is_durable` is False for any controller built without a store; plans 20-12 and 20-19 must refuse such a controller.
- The new reason `SAFE_MODE_STATE_UNREADABLE` needs its GLOSSARY 9.4 entry (plan 20-24).
- Line endings: `src/reconcile/safe_mode.py` and `tests/test_controller_rehydrate.py` kept CRLF; the three new files are LF in the working tree (git normalizes per autocrlf).

## Self-Check: PASSED

- FOUND: src/persistence/safe_mode_store.py, tests/test_safe_mode_persistence.py, tests/test_safe_mode_persistence_pg.py
- FOUND commits: 55c1ee2b, 0572f239, f5371446, bc60ea9b, 41d2257f, 867d79a0 (6 measured by `git rev-list --count`)
