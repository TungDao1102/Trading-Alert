# Deferred Items — Phase 09 Live Execution Rollout

Out-of-scope discoveries logged during execution (not fixed — pre-existing
in files this plan did not touch).

## Plan 09-04

- **`src/ops/drills.py` ruff F401 (unused imports)** — found while running
  `ruff check src/execution src/ops` for the plan's overall verification
  step. Three unused-import findings: `datetime.UTC` at module scope
  (line 49) and two local `import asyncio` statements (lines 537, 874)
  inside `make_orphan_drill`/`make_restore_drill` that shadow the
  module's own `_run_coro` helper's import. `src/ops/drills.py` is a
  Phase-8 (plan 08-05) file this plan did not modify — out of scope per
  the executor's scope-boundary rule. `src/ops/health.py` and
  `src/execution/manager.py` (this plan's actual files) are ruff-clean.
