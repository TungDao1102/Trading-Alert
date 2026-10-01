---
phase: "17"
slug: operational-persistence-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-01"
---

# Phase 17 — Validation Strategy

> Per-phase validation contract. Source of truth for the per-requirement map is the `## Validation Architecture` section of `17-RESEARCH.md`; this file is the execution-time contract.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio (auto mode); Ruff; mypy strict on `src` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_transitions.py tests/test_journal_ids.py tests/test_execution_manager.py -x -q` |
| **PG run command** | `TEST_DATABASE_URL=postgresql+psycopg://trading:dev_only_local@127.0.0.1:5432/postgres uv run pytest tests/test_persistence_*.py tests/test_execution_exactly_once_pg.py -x -q -rs` (dev Docker Postgres `trading-postgres-1`; fixture creates throwaway `t17_*_test` databases and never touches the URL's own database) |
| **Full suite command** | `uv run pytest -m "not docker" -rs -p no:cacheprovider` + `uv run ruff check` + `uv run ruff format --check` + `uv run mypy src` |
| **Estimated runtime** | ~120 seconds (PG modules included) |

## Sampling Rate

- **After every task commit:** quick run command plus the single PG module the task touches.
- **After every plan wave:** full suite command with `TEST_DATABASE_URL` set; zero skips allowed from `tests/test_persistence_*` and `tests/test_execution_*_pg.py`.
- **Before `/gsd-verify-work`:** full suite green; CI with `TRADING_CI_STRICT=1` green.
- **Max feedback latency:** 180 seconds.

## Per-Task Verification Map

See `17-RESEARCH.md` §Validation Architecture "Phase Requirements to Test Map" (SC1-SC5, EXEC-04, DOMN-04, F-606 restart). The planner copies each row's command into the owning task's `<automated>` block; task IDs are assigned by the plans.

## Wave 0 Requirements

- [ ] `tests/pg_support.py` / conftest fixtures: `pg_server_url`, `pg_template`, `pg_db`, strict-skip via `infra_skip`; `tests/test_pg_fixture_guard.py`
- [ ] `src/db/alembic/env.py` connection/logging seam (or documented subprocess runner) before parity tests
- [ ] RED tests: parity, enum-columns, constraints, write-ahead, exactly-once (stateful Binance-semantics fake and `SimulatedCrash` helper)
- [ ] Rebuild `tests/test_domain_mappers_pg.py` on the new fixtures
- [ ] Local PG available (dev Docker `trading-postgres-1`, `trading_test` DB exists)

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Confirm DOMN-04 transition tables | DOMN-04 | GLOSSARY has value sets only; tables are authored this phase (research C3) | Review the drafted tables in the DECISIONS D051 row and `docs/GLOSSARY.md`; override before first live use |

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 180s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
