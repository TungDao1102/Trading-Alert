---
phase: "24"
slug: "live-runtime-composition-demo"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-30"
---

# Phase 24 — Validation Strategy

> Per-phase validation contract. The requirement-to-test map and Wave 0 gap list live in `24-RESEARCH.md` section "Validation Architecture"; the planner copies task-level rows here.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1, pytest-asyncio (`asyncio_mode = "auto"`), pytest-xdist (dev extra) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`, `tests/conftest.py` |
| **Quick run command** | `uv run pytest tests/test_live_*.py tests/test_phase24_gate.py -x -q` |
| **Full suite command** | `uv run pytest -m "not docker" -n 4` (orchestrator, once per phase) |
| **Estimated runtime** | quick ~60 s; full ~10 min |

## Sampling Rate

- **After every task commit:** the plan's own test files, `uv run ruff check <paths>`, `uv run mypy src/live`
- **After every plan wave:** quick command plus `tests/test_phase18_gate.py`, `tests/test_paper_shadow_isolation.py`, phase 19 to 23 gates
- **Before `/gsd-verify-work`:** full suite green; recorded sequential gate with `TEST_DATABASE_URL`
- **Max feedback latency:** 120 s

## Per-Task Verification Map

Filled by the planner per task. Requirement coverage: APRV-01, EXEC-01, EXEC-02, EXEC-03, OPS-02, OPS-03, OPS-04 (see research map).

Filled by the planner on 2026-10-31 from the 36 PLAN.md files (first `<automated>` command of each task; long commands are cut with "..."; the plan file holds the full command and its `<fails_when>`). "❌ W0" means the test file is created by the task itself or by an earlier Phase 24 plan; plan 24-32 sets the final statuses.

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 24-01-T1 | 24-01 | 1 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | doc/static | inline `uv run python -c` check that 24-OWNER-DECISIONS.md has Q1..Q16 and 16 recommendations | n/a | ⬜ pending |
| 24-01-T2 | 24-01 | 1 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | doc/static | inline `uv run python -c` check that 24-LIMITS-CHECKPOINT.md names every key and ASSISTANT RECOMMENDATION | n/a | ⬜ pending |
| 24-01-T3 | 24-01 | 1 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | checkpoint:decision (owner) | n/a (owner answer recorded in 24-01-SUMMARY.md) | n/a | ⬜ pending |
| 24-02-T1 | 24-02 | 1 | EXEC-01,OPS-02 | tracer | `uv run pytest -m "not docker" tests/test_domain_enums.py tests/test_phase23_gate.py tests/test_execution_health.py tests/test_execution_manager.py -x` | ✅ | ⬜ pending |
| 24-02-T2 | 24-02 | 1 | EXEC-01,OPS-02 | unit/integration | `uv run pytest -m "not docker" tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py tests/test_phase22_gate.py ...` | ✅ | ⬜ pending |
| 24-02-T3 | 24-02 | 1 | EXEC-01,OPS-02 | unit/integration | `uv run pytest -m "not docker" tests/test_execution_health.py tests/test_execution_manager.py tests/test_execution_enablement.py -x` | ✅ | ⬜ pending |
| 24-03-T1 | 24-03 | 1 | OPS-03,EXEC-02 | tracer | `uv run pytest -m "not docker" tests/test_rest_gate_ban_end.py tests/test_gate_restore_bounds.py tests/test_rest_gate_clear_audit.py ...` | ❌ W0 | ⬜ pending |
| 24-03-T2 | 24-03 | 1 | OPS-03,EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_execution_limits.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py -x` | ✅ | ⬜ pending |
| 24-03-T3 | 24-03 | 1 | OPS-03,EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_binance_usdm_source_guard.py -x` | ✅ | ⬜ pending |
| 24-04-T1 | 24-04 | 2 | APRV-01,EXEC-01,EXEC-03 | tracer | `uv run pytest -m "not docker" tests/test_live_tracer.py tests/test_approval_desk.py tests/test_confirm_flow.py -x` | ❌ W0 | ⬜ pending |
| 24-04-T2 | 24-04 | 2 | APRV-01,EXEC-01,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_tracer.py -x` | ❌ W0 | ⬜ pending |
| 24-04-T3 | 24-04 | 2 | APRV-01,EXEC-01,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_ast_guards.py tests/test_binance_usdm_source_guard.py tests/test_execution_manager.py -x` | ❌ W0 | ⬜ pending |
| 24-05-T1 | 24-05 | 2 | OPS-03 | tracer | `uv run pytest -m "not docker" tests/test_store_executor.py -x` | ❌ W0 | ⬜ pending |
| 24-05-T2 | 24-05 | 2 | OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_paper_shadow_runtime.py tests/test_paper_shadow_isolation.py tests/test_paper_shadow_confirm.py ...` | ✅ | ⬜ pending |
| 24-06-T1 | 24-06 | 3 | EXEC-01,EXEC-02,OPS-03 | tracer | `uv run pytest -m "not docker" tests/test_live_limits_relationships.py -x` | ❌ W0 | ⬜ pending |
| 24-06-T2 | 24-06 | 3 | EXEC-01,EXEC-02,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_execution_limits.py tests/test_execution_manager.py tests/test_phase19_gate.py ...` | ✅ | ⬜ pending |
| 24-06-T3 | 24-06 | 3 | EXEC-01,EXEC-02,OPS-03 | doc/static | `uv run python scripts/verify_decision_alignment.py all` | ✅ | ⬜ pending |
| 24-07-T1 | 24-07 | 2 | EXEC-02 | tracer | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_event_time_pg.py tests/test_persistence_transitions_pg.py ...` | ❌ W0 | ⬜ pending |
| 24-07-T2 | 24-07 | 2 | EXEC-02 | unit/integration | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_migration_pg.py tests/test_pg_fixture_guard.py -x` | ✅ | ⬜ pending |
| 24-08-T1 | 24-08 | 2 | APRV-01,EXEC-03 | tracer | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_approval_mode_scope_pg.py tests/test_approval_replay_pg.py ...` | ❌ W0 | ⬜ pending |
| 24-08-T2 | 24-08 | 2 | APRV-01,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_paper_runtime_env.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_isolation.py ...` | ✅ | ⬜ pending |
| 24-09-T1 | 24-09 | 3 | APRV-01 | tracer | `uv run pytest -m "not docker" tests/test_paper_shadow_money.py tests/test_paper_shadow_isolation.py tests/test_money_at_stake.py -x` | ❌ W0 | ⬜ pending |
| 24-09-T2 | 24-09 | 3 | APRV-01 | unit/integration | `uv run pytest -m "not docker" tests/test_paper_shadow_messages.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_buttons.py ...` | ✅ | ⬜ pending |
| 24-10-T1 | 24-10 | 3 | EXEC-02 | tracer | `uv run pytest -m "not docker" tests/test_live_scheduler.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-10-T2 | 24-10 | 3 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_live_scheduler.py tests/test_no_unratified_defaults.py -x` | ❌ W0 | ⬜ pending |
| 24-11-T1 | 24-11 | 3 | OPS-02,OPS-04 | tracer | `uv run pytest -m "not docker" tests/test_live_config_refusal.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-11-T2 | 24-11 | 3 | OPS-02,OPS-04 | unit/integration | `uv run pytest -m "not docker" tests/test_live_runtime_cli.py -x` | ❌ W0 | ⬜ pending |
| 24-11-T3 | 24-11 | 3 | OPS-02,OPS-04 | unit/integration | `uv run pytest -m "not docker" tests/test_live_runtime_cli.py tests/test_code_version.py -x` | ❌ W0 | ⬜ pending |
| 24-12-T1 | 24-12 | 3 | EXEC-01,OPS-03 | tracer | `uv run pytest -m "not docker" tests/test_live_exchange_wiring.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-12-T2 | 24-12 | 3 | EXEC-01,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_exchange_wiring.py tests/test_gate_restore_bounds.py -x` | ❌ W0 | ⬜ pending |
| 24-13-T1 | 24-13 | 3 | EXEC-02 | tracer | `uv run pytest -m "not docker" tests/test_live_alerts_wiring.py tests/test_alerts.py tests/test_alerts_ops05_matrix.py -x` | ❌ W0 | ⬜ pending |
| 24-13-T2 | 24-13 | 3 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_live_alerts_wiring.py tests/test_live_tracer.py -x` | ❌ W0 | ⬜ pending |
| 24-14-T1 | 24-14 | 3 | APRV-01 | tracer | `uv run pytest -m "not docker" tests/test_live_approval_sender.py tests/test_approval_desk.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-14-T2 | 24-14 | 3 | APRV-01 | unit/integration | `uv run pytest -m "not docker" tests/test_live_approval_sender.py -x` | ❌ W0 | ⬜ pending |
| 24-14-T3 | 24-14 | 3 | APRV-01 | unit/integration | `uv run pytest -m "not docker" tests/test_live_approval_sender.py tests/test_risk_reservation_approval_pg.py -x` | ❌ W0 | ⬜ pending |
| 24-15-T1 | 24-15 | 3 | EXEC-01 | tracer | `uv run pytest -m "not docker" tests/test_live_commission_refresh.py tests/test_commission_rates.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-15-T2 | 24-15 | 3 | EXEC-01 | unit/integration | `uv run pytest -m "not docker" tests/test_commission_rates.py tests/test_binance_usdm_signed_calls.py tests/test_binance_usdm_source_guard.py -x` | ✅ | ⬜ pending |
| 24-15-T3 | 24-15 | 3 | EXEC-01 | unit/integration | `uv run pytest -m "not docker" tests/test_backtest_purity.py tests/test_cost_parity.py tests/test_domain_no_float.py -x` | ✅ | ⬜ pending |
| 24-16-T1 | 24-16 | 3 | EXEC-01 | tracer | `uv run pytest -m "not docker" tests/test_live_risk_input_producer.py tests/test_live_tracer.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-16-T2 | 24-16 | 3 | EXEC-01 | unit/integration | `uv run pytest -m "not docker" tests/test_live_risk_input_producer.py tests/test_day_risk_service.py tests/test_account_equity_source.py ...` | ❌ W0 | ⬜ pending |
| 24-16-T3 | 24-16 | 3 | EXEC-01 | unit/integration | `uv run pytest -m "not docker" tests/test_live_liquidation_and_tp.py tests/test_protection_liquidation.py tests/test_liquidation_watch.py ...` | ❌ W0 | ⬜ pending |
| 24-17-T1 | 24-17 | 3 | APRV-01,EXEC-03 | tracer | `uv run pytest -m "not docker" tests/test_live_telegram_runner.py tests/test_live_tracer.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-17-T2 | 24-17 | 3 | APRV-01,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_confirm_flow_worker_thread.py tests/test_confirm_flow.py tests/test_confirm_core.py ...` | ❌ W0 | ⬜ pending |
| 24-17-T3 | 24-17 | 3 | APRV-01,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_telegram_dispatch_off_loop.py tests/test_telegram_authorization.py ...` | ❌ W0 | ⬜ pending |
| 24-18-T1 | 24-18 | 4 | EXEC-02,EXEC-01 | tracer | `uv run pytest -m "not docker" tests/test_live_stream_to_protection.py tests/test_protection_router_rig.py tests/test_userdata_router.py -x` | ❌ W0 | ⬜ pending |
| 24-18-T2 | 24-18 | 4 | EXEC-02,EXEC-01 | unit/integration | `uv run pytest -m "not docker" tests/test_live_stream_to_protection.py tests/test_day_risk_stream.py -x` | ❌ W0 | ⬜ pending |
| 24-18-T3 | 24-18 | 4 | EXEC-02,EXEC-01 | unit/integration | `uv run pytest -m "not docker" tests/test_phase18_gate.py -x` | ✅ | ⬜ pending |
| 24-19-T1 | 24-19 | 4 | EXEC-02 | tracer | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_live_stream_persistence_pg.py tests/test_persistence_event_time_pg.py -x` | ❌ W0 | ⬜ pending |
| 24-19-T2 | 24-19 | 4 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_live_feed_source.py tests/test_reconcile_loop.py -x` | ❌ W0 | ⬜ pending |
| 24-19-T3 | 24-19 | 4 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_live_feed_source.py tests/test_userdata_events.py -x` | ❌ W0 | ⬜ pending |
| 24-20-T1 | 24-20 | 4 | EXEC-02 | tracer | `uv run pytest -m "not docker" tests/test_live_reconcile_wiring.py tests/test_reconcile_loop.py tests/test_sweeper_verifier_failure.py ...` | ❌ W0 | ⬜ pending |
| 24-20-T2 | 24-20 | 4 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_live_reconcile_wiring.py tests/test_lot_filters_pg.py -x` | ❌ W0 | ⬜ pending |
| 24-20-T3 | 24-20 | 4 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_safe_mode_persistence.py tests/test_safe_mode_reentry.py tests/test_safe_mode_exit_operator.py ...` | ✅ | ⬜ pending |
| 24-21-T1 | 24-21 | 4 | EXEC-02 | tracer | `uv run pytest -m "not docker" tests/test_live_scheduled_cancel.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-21-T2 | 24-21 | 4 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_sweeper_cancel_lag.py tests/test_sweeper_verifier_failure.py tests/test_reconcile_loop.py ...` | ❌ W0 | ⬜ pending |
| 24-21-T3 | 24-21 | 4 | EXEC-02 | unit/integration | `uv run pytest -m "not docker" tests/test_adapter_entry_price_decimal.py tests/test_binance_usdm_signed_calls.py tests/test_adapter_strictness.py -x` | ❌ W0 | ⬜ pending |
| 24-22-T1 | 24-22 | 4 | EXEC-01,OPS-02,OPS-04 | tracer | `uv run pytest -m "not docker" tests/test_execution_health.py tests/test_live_health.py tests/test_execution_enablement.py ...` | ❌ W0 | ⬜ pending |
| 24-22-T2 | 24-22 | 4 | EXEC-01,OPS-02,OPS-04 | unit/integration | `uv run pytest -m "not docker" tests/test_live_enablement_wiring.py tests/test_execution_enablement.py tests/test_live_tracer.py -x` | ❌ W0 | ⬜ pending |
| 24-22-T3 | 24-22 | 4 | EXEC-01,OPS-02,OPS-04 | unit/integration | `uv run pytest -m "not docker" tests/test_live_enablement_wiring.py tests/test_kill_gate_event.py tests/test_kill_gate_state.py -x` | ❌ W0 | ⬜ pending |
| 24-23-T1 | 24-23 | 4 | EXEC-02,OPS-03 | tracer | `uv run pytest -m "not docker" tests/test_live_safe_mode_drill.py tests/test_safe_mode_exit_operator.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-23-T2 | 24-23 | 4 | EXEC-02,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_operator_commands.py tests/test_telegram_authorization.py -x` | ❌ W0 | ⬜ pending |
| 24-23-T3 | 24-23 | 4 | EXEC-02,OPS-03 | unit/integration | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_live_safe_mode_drill.py -x` | ❌ W0 | ⬜ pending |
| 24-24-T1 | 24-24 | 4 | OPS-02,OPS-03 | tracer | `uv run pytest -m "not docker" tests/test_deploy_heartbeat.py -x` | ✅ | ⬜ pending |
| 24-24-T2 | 24-24 | 4 | OPS-02,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_deploy_heartbeat.py tests/test_deploy_scripts.py -x` | ✅ | ⬜ pending |
| 24-25-T1 | 24-25 | 4 | OPS-04 | tracer | `uv run pytest -m "not docker" tests/test_dockerfile_revision_stamp.py tests/test_deploy_images.py -x` (+ docker-marked image run) | ❌ W0 | ⬜ pending |
| 24-25-T2 | 24-25 | 4 | OPS-04 | unit/integration | `uv run pytest -m "not docker" tests/test_deploy_compose.py tests/test_deploy_scripts.py -x` | ✅ | ⬜ pending |
| 24-25-T3 | 24-25 | 4 | OPS-04 | doc/static | `uv run pytest -m "not docker" tests/test_dockerfile_revision_stamp.py -x` | ❌ W0 | ⬜ pending |
| 24-26-T1 | 24-26 | 5 | OPS-03,EXEC-03 | tracer | `uv run pytest -m "not docker" tests/test_live_start_sequence.py tests/test_live_ast_guards.py -x` | ❌ W0 | ⬜ pending |
| 24-26-T2 | 24-26 | 5 | OPS-03,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_start_sequence.py tests/test_startup_recovery.py -x` | ❌ W0 | ⬜ pending |
| 24-26-T3 | 24-26 | 5 | OPS-03,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_restart_rehydrate.py tests/test_intent_recovery.py tests/test_intent_recovery_unknown_entry.py -x` | ❌ W0 | ⬜ pending |
| 24-27-T1 | 24-27 | 6 | APRV-01,EXEC-01,EXEC-02,OPS-03 | tracer | `uv run pytest -m "not docker" tests/test_live_wiring.py tests/test_live_tracer.py tests/test_live_stream_to_protection.py ...` | ❌ W0 | ⬜ pending |
| 24-27-T2 | 24-27 | 6 | APRV-01,EXEC-01,EXEC-02,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_wiring.py -x` | ❌ W0 | ⬜ pending |
| 24-27-T3 | 24-27 | 6 | APRV-01,EXEC-01,EXEC-02,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_run_admitted.py tests/test_live_runtime_cli.py tests/test_live_config_refusal.py -x` | ❌ W0 | ⬜ pending |
| 24-28-T1 | 24-28 | 7 | EXEC-03,OPS-03,APRV-01 | tracer | `uv run pytest -m "not docker" tests/test_live_replay_restart.py -x` | ❌ W0 | ⬜ pending |
| 24-28-T2 | 24-28 | 7 | EXEC-03,OPS-03,APRV-01 | unit/integration | `uv run pytest -m "not docker" tests/test_live_replay_restart.py tests/test_live_restart_rehydrate.py -x` | ❌ W0 | ⬜ pending |
| 24-28-T3 | 24-28 | 7 | EXEC-03,OPS-03,APRV-01 | unit/integration | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_live_replay_restart_pg.py -x` | ❌ W0 | ⬜ pending |
| 24-29-T1 | 24-29 | 7 | EXEC-01,EXEC-02,EXEC-03,OPS-03 | tracer | `uv run pytest -m "not docker" tests/test_live_demo_smoke.py -x` | ❌ W0 | ⬜ pending |
| 24-29-T2 | 24-29 | 7 | EXEC-01,EXEC-02,EXEC-03,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_demo_smoke.py tests/test_demo_rehearsal_safety.py -x` | ❌ W0 | ⬜ pending |
| 24-29-T3 | 24-29 | 7 | EXEC-01,EXEC-02,EXEC-03,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_demo_rehearsal_safety.py tests/test_demo_rehearsal_flow.py tests/test_live_demo_smoke.py ...` | ❌ W0 | ⬜ pending |
| 24-30-T1 | 24-30 | 5 | OPS-02 | tracer | `uv run pytest -m "not docker" tests/test_live_compose_env_split.py tests/test_deploy_compose.py -x` | ❌ W0 | ⬜ pending |
| 24-30-T2 | 24-30 | 5 | OPS-02 | unit/integration | `uv run pytest -m "not docker" tests/test_live_compose_env_split.py -x` | ❌ W0 | ⬜ pending |
| 24-30-T3 | 24-30 | 5 | OPS-02 | unit/integration | `uv run pytest -m "not docker" tests/test_env_example.py tests/test_paper_runtime_compose.py tests/test_live_compose_env_split.py ...` | ❌ W0 | ⬜ pending |
| 24-31-T1 | 24-31 | 8 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | doc/static | `uv run python scripts/verify_decision_alignment.py all` | ✅ | ⬜ pending |
| 24-31-T2 | 24-31 | 8 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | doc/static | `uv run pytest -m "not docker" tests/test_deploy_docs.py tests/test_kill_gate_docs.py -x` | ✅ | ⬜ pending |
| 24-31-T3 | 24-31 | 8 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | doc/static | `uv run pytest -m "not docker" tests/test_agents_md.py tests/test_decision_alignment_authority.py tests/test_decision_alignment.py -x` | ✅ | ⬜ pending |
| 24-32-T1 | 24-32 | 9 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | tracer | `uv run pytest -m "not docker" tests/test_phase24_gate.py -x` | ❌ W0 | ⬜ pending |
| 24-32-T2 | 24-32 | 9 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | unit/integration | `uv run pytest -m "not docker" tests/test_phase24_gate.py -x` | ❌ W0 | ⬜ pending |
| 24-32-T3 | 24-32 | 9 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03,OPS-04 | doc/static | `uv run pytest -m "not docker" tests/test_phase24_gate.py tests/test_phase18_gate.py tests/test_phase23_gate.py ...` | ❌ W0 | ⬜ pending |
| 24-33-T1 | 24-33 | 10 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03 | doc/static | inline `uv run python -c` check that 24-OWNER-RUNBOOK.md has every owner step | n/a | ⬜ pending |
| 24-33-T2 | 24-33 | 10 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03 | checkpoint:human-action (owner) | n/a (owner run; evidence paths recorded in 24-OWNER-RUNBOOK.md) | n/a | ⬜ pending |
| 24-33-T3 | 24-33 | 10 | APRV-01,EXEC-01,EXEC-02,EXEC-03,OPS-02,OPS-03 | doc/static | `uv run pytest -m "not docker" tests/test_phase24_gate.py -x` | ❌ W0 | ⬜ pending |
| 24-34-T1 | 24-34 | 5 | EXEC-02,EXEC-03 | tracer | `uv run pytest -m "not docker" tests/test_live_unknown_entry_notify.py tests/test_intent_recovery.py tests/test_intent_recovery_unknown_entry.py ...` | ❌ W0 | ⬜ pending |
| 24-34-T2 | 24-34 | 5 | EXEC-02,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_protection_cancel_lag.py tests/test_protection_sweep_spill.py tests/test_protection_router_rig.py -x` | ❌ W0 | ⬜ pending |
| 24-34-T3 | 24-34 | 5 | EXEC-02,EXEC-03 | unit/integration | `uv run pytest -m "not docker" tests/test_live_reconcile_divergences.py tests/test_reconcile_compare_v2.py -x` | ❌ W0 | ⬜ pending |
| 24-35-T1 | 24-35 | 7 | OPS-02,OPS-03 | tracer | `uv run pytest -m docker tests/test_live_compose_service.py -x` | ❌ W0 | ⬜ pending |
| 24-35-T2 | 24-35 | 7 | OPS-02,OPS-03 | unit/integration | `uv run pytest -m "not docker" tests/test_deploy_compose.py tests/test_live_compose_env_split.py -x` | ❌ W0 | ⬜ pending |
| 24-36-T1 | 24-36 | 6 | OPS-02 | tracer | `uv run pytest -m "not docker" tests/test_live_compose_env_split.py tests/test_soak_compose.py -x` | ❌ W0 | ⬜ pending |
| 24-36-T2 | 24-36 | 6 | OPS-02 | unit/integration | `uv run pytest -m "not docker" tests/test_deploy_backup_scripts.py tests/test_live_compose_env_split.py -x` | ❌ W0 | ⬜ pending |
| 24-36-T3 | 24-36 | 6 | OPS-02 | unit/integration | `uv run pytest -m "not docker" tests/test_env_example.py tests/test_cutover.py -x` (+ docker-marked cutover and backup drill) | ✅ | ⬜ pending |

## Wave 0 Requirements

See `24-RESEARCH.md` "Wave 0 Gaps": `tests/support/live_rig.py`, fake-exchange extensions, lagging-algo-cancel fake, user-data frame injector, PTB update fake, PG restart fixtures, amended Phase 18 gate and isolation tests.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Demo end-to-end smoke with recorded order ids | EXEC-01..03 | Owner-only (AGENTS.md); machine cannot reach Binance | `scripts/demo_rehearsal.py --execute` by the owner |
| Unknown-chat / other-user tap rejected live (G2-014) | APRV-01 | Needs a second Telegram account | Owner check list |
| VPS bootstrap, IP whitelist, heartbeat firing | OPS-02, OPS-03 | Host actions | RUNBOOK sections 13 and 17 |
| All of the above in one owner session | APRV-01, EXEC-01..03, OPS-02, OPS-03 | Owner-only by AGENTS.md | Plan 24-33, `24-OWNER-RUNBOOK.md` (checkpoint:human-action); results recorded verbatim, NOT_OBSERVED until run |

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
