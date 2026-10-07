---
phase: "17"
slug: operational-persistence-layer
status: validated
nyquist_compliant: true
wave_0_complete: true
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

Run 2026-10-07, file by file, `uv run pytest <file> -q -rs -p no:cacheprovider`. PG files ran with `TRADING_CI_STRICT=1` against a throwaway postgres:17.11-bookworm container (the documented dev URL for `trading-postgres-1` was rejected with a password authentication failure, so a disposable container was used; same image as CI). Every file below: green, zero skips.

| Req / SC | Audit refs | Test file(s) | Command (prefix `uv run pytest`, PG files need `TEST_DATABASE_URL`) | Status |
|----------|------------|--------------|------------------------------------------|--------|
| SC1 / DOMN-01 | F-202 | `test_persistence_roundtrip_pg.py` (7 round trips), `test_domain_mappers.py`, `test_domain_mappers_pg.py`, `test_persistence_approvals_pg.py`, `test_persistence_journal_pg.py`; Protocol conformance is structural via mypy blocks (no `test_persistence_protocols.py` exists) | `tests/test_persistence_roundtrip_pg.py`; `uv run mypy src` (149 files, clean) | COVERED |
| SC2 / DOMN-01, APRV-02 | F-404 | `test_persistence_constraints_pg.py` (45), `test_persistence_triggers_pg.py` (60) | `tests/test_persistence_constraints_pg.py` | COVERED |
| SC2 | F-403 | `test_persistence_enum_columns_pg.py` (25) | `tests/test_persistence_enum_columns_pg.py` | COVERED |
| SC2 | F-411, D-24 | `test_persistence_migration_pg.py` (32: parity, up/down/up, 0003->0004 data) | `tests/test_persistence_migration_pg.py` | COVERED |
| SC2 | F-406 | `test_persistence_engine_pg.py` (5), `test_persistence_engine_timeouts.py` (5), `test_persistence_uow_pg.py` (5) | `tests/test_persistence_engine_pg.py` | COVERED |
| SC2 | F-410 | `test_plan_hash_roundtrip_pg.py` (22), `test_core_planner.py` (17) | `tests/test_plan_hash_roundtrip_pg.py tests/test_core_planner.py` (run per file) | COVERED |
| SC2 | F-412 | `test_journal_ids.py` (30), `test_persistence_journal_pg.py` (21), `test_journal_failure_paths.py` (7) | `tests/test_journal_ids.py` | COVERED |
| SC3 / EXEC-03 | F-126, F-951, F-703 | `test_execution_write_ahead_pg.py` (10), `test_intent_recovery.py` (21), `test_intent_recovery_pg.py` (13), `test_execution_manager.py` (61, incl. CR-01 tests) | `tests/test_execution_write_ahead_pg.py` | COVERED |
| SC3 / APRV-02 | F-603 | `test_approval_replay_pg.py` (5), `test_callback_redelivery_pg.py` (12) | `tests/test_approval_replay_pg.py` | COVERED |
| SC4 / EXEC-03 | F-603 | `test_execution_exactly_once_pg.py` (28, incl. negative controls) | `tests/test_execution_exactly_once_pg.py` | COVERED |
| SC5 | F-606 | `test_pg_fixture_guard.py` (25) plus remote CI run 37180873501 green | `tests/test_pg_fixture_guard.py` | COVERED |
| EXEC-04 | | `test_constraint_snapshot.py` (50), `test_constraint_snapshot_pg.py` (16) | `tests/test_constraint_snapshot_pg.py` | COVERED |
| DOMN-04 | | `test_transitions.py` (52), `test_persistence_transitions_pg.py` (65) | `tests/test_transitions.py` | COVERED |
| F-606 restart | F-606 | `test_system_state_pg.py` (28) | `tests/test_system_state_pg.py` | COVERED |
| D-27 | | `test_decision_alignment*.py` (8 files), `test_deploy_docs.py` (32) | per file | COVERED |

## Wave 0 Requirements

- [x] `tests/pg_support.py` / conftest fixtures: `pg_server_url`, `pg_template`, `pg_db`, strict-skip via `infra_skip`; `tests/test_pg_fixture_guard.py`
- [x] `src/db/alembic/env.py` connection/logging seam (or documented subprocess runner) before parity tests
- [x] RED tests: parity, enum-columns, constraints, write-ahead, exactly-once (stateful Binance-semantics fake and `SimulatedCrash` helper)
- [x] Rebuild `tests/test_domain_mappers_pg.py` on the new fixtures
- [x] Local PG available (dev Docker `trading-postgres-1`, `trading_test` DB exists)

## Manual-Only Verifications

Resolved:

| Behavior | Requirement | Resolution |
|----------|-------------|------------|
| DOMN-04 transition tables | DOMN-04 | Confirmed by the user 2026-10-02 |
| Binance facts (clientOrderId unique among OPEN orders, 3-day Query Order retention) | EXEC-03 | Re-read live on developers.binance.com 2026-10-07 |
| First remote CI run of the PG battery | SC5 | CI run 37180873501 green |
| CR-01 safe-mode audit-write policy | EXEC-03 | Accepted by the owner |

Remaining (deferred, not a Phase 17 gap):

| Behavior | Requirement | Why Manual | Owner |
|----------|-------------|------------|-------|
| Demo probe: -4116 on duplicate OPEN client id, and client id reuse after close, against real Binance | EXEC-03 | Needs a live demo account; the fake encodes the documented behavior only | Phase 18 |

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 180s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-10-07

## Validation Audit 2026-10-07

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 (no new tests needed) |
| Escalated | 0 |

Notes: all 36 mapped files were executed individually and passed with no skips; `mypy src` clean. `test_persistence_protocols.py` named in research was never created; its behavior (SC1 structural conformance) is enforced by the mypy conformance blocks. The documented dev PG URL password failed against `trading-postgres-1`, so the run used a disposable postgres:17.11-bookworm container (since removed); update the PG run command credentials locally if needed.
