# Phase 17 Deferred Items

Out-of-scope discoveries logged during execution (not fixed by the plan that found them).

## From plan 17-01

- **`ruff format --check` (repo root) exits non-zero on a planning document.** This ruff version
  also formats fenced Markdown code blocks; `.planning/phases/17-operational-persistence-layer/17-RESEARCH.md`
  (committed in 99d3a94, before plan 17-01) has an unformatted Python sketch (`make_sync_engine`, line ~249).
  `ruff format --check src tests` is clean. CI's lint job runs the repo-root form, so either reformat the
  code block in the research doc or exclude `.planning/` in `[tool.ruff]` before the phase is shipped.
- **`tests/test_analytics_store.py::test_pg_append_and_reread_one_kill_gate_event` needs a `_test` database
  name in `TEST_DATABASE_URL`** (it runs `create_all`/`drop_all` on the URL's own database). The Phase 17
  fixtures treat `TEST_DATABASE_URL` as a maintenance connection only, so a URL ending in `/postgres`
  makes that older test fail by its own guard. CI already uses `.../trading_test`, which satisfies both.
  Plan 17-15 (docs/CI) should state the URL convention in `docs/testing/TESTING_STRATEGY.md`.
