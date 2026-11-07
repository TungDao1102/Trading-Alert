---
phase: "25"
slug: "demo-integration-test-campaign"
status: draft
nyquist_compliant: true
wave_0_complete: false
created: "2026-11-07"
---

# Phase 25 — Validation Strategy

> Seeded by plan-phase from `25-RESEARCH.md` "Validation Architecture". The planner copies task-level rows into
> the Per-Task Verification Map. Agents run only fake-exchange twins and unit tests; Demo runs are owner-only.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1, `asyncio_mode = "auto"`, pytest-xdist (dev extra; never for `demo` tests) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (the `demo` marker is added in Wave 0) |
| **Quick run command** | `uv run pytest tests/test_demo_twin_s04_sl_rejected.py -x` (one twin) |
| **Phase suite command** | `uv run pytest tests/test_demo_twin_*.py tests/test_phase25_gate.py tests/test_demo_marker_guard.py -x -q` |
| **Full suite command** | `uv run pytest -m "not docker" -n 4`; recorded gate: sequential, clean tree, `TEST_DATABASE_URL`, `TRADING_CI_STRICT=1` |
| **Owner Demo command** | `uv run pytest -m demo -p no:xdist -s` with the env guard set (owner only, never an agent) |
| **Estimated runtime** | twin under 30 s each; phase suite a few minutes; full ~10 min |

## Sampling Rate

- **After every task commit:** the single twin or unit file the task touched, plus `uv run ruff check <paths>`
- **After every plan wave:** the phase suite command
- **Before `/gsd-verify-work`:** full suite green; recorded sequential gate; `uv run mypy src`; `uv lock --check`; `uv run python scripts/verify_decision_alignment.py all`
- **Max feedback latency:** 120 s

## Per-Task Verification Map

Filled by the planner. Requirement-to-test map (from research): EXEC-01/02/03, APRV-01/02, OPS-01/02, D-03, D-08, D-11, R-24, soak evaluator, criterion-4 document gate. Status key: ⬜ pending, ✅ green, ❌ red, ⚠️ flaky.

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 25-01-01 | 01 | 1 | OPS-02, D-03 | unit + strict collection run | `uv run pytest -m "not docker" tests/test_demo_marker_guard.py tests/demo -x -q -rs` | ❌ W0 | ⬜ pending |
| 25-01-02 | 01 | 1 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_demo_env_guard.py tests/test_demo_marker_guard.py tests/demo -x -q` | ❌ W0 | ⬜ pending |
| 25-01-03 | 01 | 1 | OPS-02 | gate | `uv run pytest -m "not docker" tests/test_agents_md.py -x -q && uv run python scripts/verify_decision_alignment.py all` | ✅ | ⬜ pending |
| 25-02-01 | 02 | 1 | EXEC-01, D-08 | composed fake (tracer) | `uv run pytest -m "not docker" tests/test_fault_edge.py tests/test_live_stream_to_protection.py tests/test_live_demo_smoke.py -x -q` | ❌ W0 | ⬜ pending |
| 25-02-02 | 02 | 1 | EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_fault_edge.py -x -q` | ❌ W0 | ⬜ pending |
| 25-02-03 | 02 | 1 | OPS-01 | unit + composed fake | `uv run pytest -m "not docker" tests/test_fault_edge.py tests/test_live_demo_smoke.py tests/test_binance_ratelimit_gate.py -x -q` | ❌ W0 | ⬜ pending |
| 25-03-01 | 03 | 1 | OPS-01, R-24 | unit TDD (SQLite pool) | `uv run pytest -m "not docker" tests/test_persistence_pool_timeout.py -x -q` | ❌ W0 | ⬜ pending |
| 25-03-02 | 03 | 1 | OPS-01, R-24 | PostgreSQL | `uv run pytest -m "not docker" tests/test_persistence_uow_pg.py tests/test_persistence_pool_timeout.py -x -q` | ✅ | ⬜ pending |
| 25-04-01 | 04 | 1 | OPS-01, D-11 | unit TDD | `uv run pytest -m "not docker" tests/test_live_health_journal_volume.py tests/test_live_health.py -x -q` | ❌ W0 | ⬜ pending |
| 25-04-02 | 04 | 1 | OPS-01, D-11 | unit | `uv run pytest -m "not docker" tests/test_live_health_journal_volume.py tests/test_live_health.py tests/test_execution_health.py -x -q` | ❌ W0 | ⬜ pending |
| 25-05-01 | 05 | 1 | EXEC-01, D-08 | AST | `uv run pytest -m "not docker" tests/test_demo_same_code_path.py -x -q` | ❌ W0 | ⬜ pending |
| 25-05-02 | 05 | 1 | EXEC-02, D-08 | AST | `uv run pytest -m "not docker" tests/test_demo_same_code_path.py tests/test_live_ast_guards.py -x -q` | ❌ W0 | ⬜ pending |
| 25-06-01 | 06 | 1 | criterion 4, D-12 | doc gate | DVM row check in 25-06 Task 1 + `uv run python scripts/verify_decision_alignment.py all` | ❌ W0 | ⬜ pending |
| 25-06-02 | 06 | 1 | G2-030 | doc check | cross-check line check in 25-06 Task 2 (fails at HEAD: 6 lines) | ✅ | ⬜ pending |
| 25-07-01 | 07 | 1 | EXEC-03, criterion 3 | unit TDD | `uv run pytest -m "not docker" tests/test_evaluate_demo_soak.py -x -q` | ❌ W0 | ⬜ pending |
| 25-07-02 | 07 | 1 | EXEC-02, criterion 3 | unit TDD | `uv run pytest -m "not docker" tests/test_evaluate_demo_soak.py -x -q` | ❌ W0 | ⬜ pending |
| 25-07-03 | 07 | 1 | OPS-01 | unit + PostgreSQL | `uv run pytest -m "not docker" tests/test_evaluate_demo_soak.py tests/test_evaluate_demo_soak_pg.py -x -q` | ❌ W0 | ⬜ pending |
| 25-08-01 | 08 | 2 | APRV-01, EXEC-01 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s01_happy.py tests/test_live_demo_smoke.py -x -q` | ❌ W0 | ⬜ pending |
| 25-08-02 | 08 | 2 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_demo_evidence_index.py -x -q` | ❌ W0 | ⬜ pending |
| 25-08-03 | 08 | 2 | EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_demo_harness.py tests/test_demo_twin_s01_happy.py -x -q` | ❌ W0 | ⬜ pending |
| 25-09-01 | 09 | 3 | OPS-02, D-08 | unit (build_wiring stubbed) | `uv run pytest -m "not docker" tests/test_demo_env_factory.py tests/test_demo_same_code_path.py -x -q` | ❌ W0 | ⬜ pending |
| 25-09-02 | 09 | 3 | APRV-01 | unit + collection | `uv run pytest -m "not docker" tests/test_demo_env_factory.py tests/test_demo_marker_guard.py tests/demo -x -q -rs` | ❌ W0 | ⬜ pending |
| 25-10-01 | 10 | 4 | EXEC-03, APRV-02 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s06_replay.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-10-02 | 10 | 4 | EXEC-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s02_partial_fill.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-10-03 | 10 | 4 | EXEC-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s05_cancel_race.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-11-01 | 11 | 4 | EXEC-01 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s04_stop_rejected.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-11-02 | 11 | 4 | EXEC-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s03_crossed_stop.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-11-03 | 11 | 4 | OPS-01, D-06 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s18_unprotected.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-12-01 | 12 | 4 | EXEC-03 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s07_restart_cuts.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-12-02 | 12 | 4 | EXEC-03, D080 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s07_restart_cuts.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-12-03 | 12 | 4 | EXEC-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s07_restart_cuts.py tests/test_live_restart_rehydrate.py -x -q` | ❌ W0 | ⬜ pending |
| 25-13-01 | 13 | 4 | EXEC-02, D-07 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s08_stream_loss.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-13-02 | 13 | 4 | OPS-01, D-06 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s17_stale_feed.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-13-03 | 13 | 4 | OPS-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s09_clock_skew.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-14-01 | 14 | 4 | OPS-01, D-07 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s10_rate_limit.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-14-02 | 14 | 4 | OPS-01, D-06 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s19_rest_gate_cli.py tests/test_rest_gate_cli.py -x -q` | ❌ W0 | ⬜ pending |
| 25-14-03 | 14 | 4 | OPS-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s11_db_outage.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-15-01 | 15 | 4 | OPS-01 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s14_safe_mode.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-15-02 | 15 | 4 | OPS-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s12_daily_stop.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-15-03 | 15 | 4 | EXEC-01 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s13_margin_liquidation.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-16-01 | 16 | 4 | EXEC-02 | twin (tracer) | `uv run pytest -m "not docker" tests/test_demo_twin_s15_foreign_order.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-16-02 | 16 | 4 | EXEC-02, D-06 | twin | `uv run pytest -m "not docker" tests/test_demo_twin_s16_manual_close.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-17-01 | 17 | 5 | all seven | structural gate | `uv run pytest -m "not docker" tests/test_phase25_gate.py tests/test_phase24_gate.py -x -q` | ❌ W0 | ⬜ pending |
| 25-17-02 | 17 | 5 | all seven, D-01..D-14 | structural gate | `uv run pytest -m "not docker" tests/test_phase25_gate.py -x -q` | ❌ W0 | ⬜ pending |
| 25-17-03 | 17 | 5 | inherited items | structural gate | `uv run pytest -m "not docker" tests/test_phase25_gate.py tests/test_demo_marker_guard.py -x -q` | ❌ W0 | ⬜ pending |
| 25-18-01 | 18 | 5 | OPS-02, D-01 | doc check | runbook term check in 25-18 Task 1 | ❌ W0 | ⬜ pending |
| 25-18-02 | 18 | 5 | OPS-01, D-06, D-07 | doc check | runbook id check in 25-18 Task 2 | ❌ W0 | ⬜ pending |
| 25-18-03 | 18 | 5 | criterion 3 | doc check | packet heading check in 25-18 Task 3 | ❌ W0 | ⬜ pending |
| 25-19-01/02 | 19 | 6 | criterion 3 (decisions a, b, c) | owner checkpoint | manual (owner decision) | n/a | ⬜ pending |
| 25-19-03 | 19 | 6 | criterion 3 | doc check | answer check in 25-19 Task 3 | n/a | ⬜ pending |
| 25-20-01 | 20 | 6 | all seven | owner Demo run | manual (owner, `pytest -m demo`) | n/a | ⬜ pending |
| 25-20-02/03 | 20 | 6 | all seven | doc check + gate | evidence-path check; DVM check + `uv run pytest -m "not docker" tests/test_phase25_gate.py -x -q` | n/a | ⬜ pending |
| 25-21-01 | 21 | 6 | EXEC-01 (R-21, decision f) | owner checkpoint | manual (owner decision) | n/a | ⬜ pending |
| 25-21-02 | 21 | 6 | EXEC-01 | gate | `uv run python scripts/verify_decision_alignment.py all && uv run pytest -m "not docker" tests/test_phase25_gate.py -x -q` | n/a | ⬜ pending |
| 25-22-01/02 | 22 | 7 | OPS-01 (decisions d, e) | owner checkpoint | manual (owner decision) | n/a | ⬜ pending |
| 25-22-03 | 22 | 7 | OPS-01 | doc check | answer check in 25-22 Task 3 | n/a | ⬜ pending |
| 25-23-01..03 | 23 | 7 | EXEC-01 (R-21) | unit TDD | `uv run pytest -m "not docker" tests/test_live_reservation_stamping.py tests/test_live_reservation_release.py tests/test_live_wiring.py -x -q` | ❌ W0 | ⬜ pending |
| 25-24-01/03 | 24 | 8 | criterion 3, D-09 | script check | `uv run python scripts/evaluate_demo_soak.py verify-registration --registration .planning/phases/25-demo-integration-test-campaign/25-SOAK-REGISTRATION.md --hash-file .planning/phases/25-demo-integration-test-campaign/25-SOAK-REGISTRATION.sha256` | n/a | ⬜ pending |
| 25-24-02 | 24 | 8 | criterion 3 | owner checkpoint | manual (owner approves the registration) | n/a | ⬜ pending |
| 25-25-01 | 25 | 9 | criterion 3 | owner soak | manual (owner, at least 21 days) | n/a | ⬜ pending |
| 25-25-02 | 25 | 9 | criterion 3 | doc check | results hash and verdict check in 25-25 Task 2 | n/a | ⬜ pending |

## Wave 0 Requirements

- [ ] `pyproject.toml` marker `demo`; `tests/conftest.py` collection hook; `tests/demo/conftest.py` env guard; `tests/test_demo_marker_guard.py` (plan 25-01)
- [ ] `tests/support/fault_edge.py` (FaultEdge, SdkFaults, StoreFaults) with its own unit tests (plan 25-02)
- [ ] `tests/support/demo_scenarios/` skeleton, `catalog.py`, `harness.py`, `evidence_index.py` (plan 25-08)
- [ ] Demo-side environment factory calling `build_wiring(exchange_edge=...)` (plan 25-09)
- [ ] Coverage inventory mapping S01-S20 to existing tests: REUSES tuples per twin (plans 25-08, 25-10 to 25-16), consolidated in `25-SCENARIO-INVENTORY.md` (plan 25-17)
- [ ] D-08 allow-list test (plan 25-05) and `tests/test_phase25_gate.py` (plan 25-17)
- [ ] Failing tests first for R-24 (plan 25-03) and R-25 (plan 25-04) (`tdd_mode` on)
- [ ] `scripts/evaluate_demo_soak.py` with fixture-journal tests (plan 25-07)

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All scenarios S01-S20 on Binance Demo with recorded order ids | EXEC-01..03, APRV-01/02, OPS-01/02 | Owner-only (AGENTS.md); agents cannot reach or may not call Demo | Owner session, `-m demo`; evidence files are the proof |
| Demo soak of at least 3 weeks | criterion 3 | Owner-started, host actions, needs owner decisions on trade generation | Pre-registered soak file; evaluator over the live journal |
| Real HTTP 418 | D-07 | Owner decided 2026-10-22 not to provoke it | Stays NOT_OBSERVED; 418/429 injected at the edge |

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (owner checkpoints are manual by rule: AGENTS.md reserves Demo runs and decisions to the owner)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (longest run: two owner checkpoints in plans 25-19 and 25-22)
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120 s (twins on virtual time; the marker guard's nested collection run is the slowest unit)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
