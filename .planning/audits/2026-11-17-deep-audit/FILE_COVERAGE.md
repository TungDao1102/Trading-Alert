# File coverage (from lane coverage tables)

Best level any lane recorded for each tracked file under src/, scripts/, deploy/, config/, docs/ (docs/research/experiments excluded). NOT_RECORDED = no lane listed the exact path (it may be covered by a directory-level row, listed below).

| Level | Files |
|---|---|
| DEEP_READ | 200 |
| NOT_RECORDED | 143 |
| NORMAL_READ | 72 |
| METADATA_ONLY | 16 |
| NOT_READ | 4 |

| File | Level | Lane |
|---|---|---|
| `config/binance/README.md` | NORMAL_READ | binance_adapters |
| `config/binance/binance-limits-v1.toml` | DEEP_READ | binance_adapters |
| `config/execution/README.md` | NOT_RECORDED | - |
| `config/execution/execution-limits-v1.toml` | DEEP_READ | decisions_trading_soundness |
| `config/paper/README.md` | DEEP_READ | paper_runtime |
| `config/paper/paper-runtime-v1.toml` | DEEP_READ | paper_runtime |
| `config/paper/paper-runtime-v2.toml` | DEEP_READ | paper_runtime |
| `deploy/backup-drill.sh` | NOT_RECORDED | - |
| `deploy/backup-real-s3-gate.sh` | NOT_RECORDED | - |
| `deploy/backup.sh` | DEEP_READ | ops_deploy_security |
| `deploy/bootstrap.sh` | NORMAL_READ | ops_deploy_security |
| `deploy/compose-rehearsal.sh` | NOT_RECORDED | - |
| `deploy/compose-soak.sh` | NORMAL_READ | ops_deploy_security |
| `deploy/evidence.env.example` | NOT_RECORDED | - |
| `deploy/freeze-witness.sh` | NORMAL_READ | ops_deploy_security |
| `deploy/heartbeat.sh` | DEEP_READ | ops_deploy_security |
| `deploy/lib.sh` | DEEP_READ | ops_deploy_security |
| `deploy/migrate.sh` | NORMAL_READ | ops_deploy_security |
| `deploy/refresh-pins.sh` | NORMAL_READ | ops_deploy_security |
| `deploy/restore.sh` | DEEP_READ | ops_deploy_security |
| `deploy/soak-image.sh` | NOT_RECORDED | - |
| `deploy/soak.env.example` | NOT_RECORDED | - |
| `deploy/systemd/trading-backup.service` | NOT_RECORDED | - |
| `deploy/systemd/trading-backup.timer` | NOT_RECORDED | - |
| `deploy/systemd/trading-heartbeat.service` | NOT_RECORDED | - |
| `deploy/systemd/trading-heartbeat.timer` | NOT_RECORDED | - |
| `deploy/systemd/trading-live-heartbeat.service` | NOT_RECORDED | - |
| `deploy/systemd/trading-live-heartbeat.timer` | NOT_RECORDED | - |
| `deploy/systemd/trading-soak-backup.service` | NOT_RECORDED | - |
| `deploy/systemd/trading-soak-backup.timer` | NOT_RECORDED | - |
| `deploy/systemd/trading-soak-freeze-witness.service` | NOT_RECORDED | - |
| `deploy/systemd/trading-soak-freeze-witness.timer` | NOT_RECORDED | - |
| `deploy/systemd/trading-soak-paper-heartbeat.service` | NOT_RECORDED | - |
| `deploy/systemd/trading-soak-paper-heartbeat.timer` | NOT_RECORDED | - |
| `deploy/update.sh` | DEEP_READ | ops_deploy_security |
| `docs/00_PRODUCT_SCOPE.md` | NORMAL_READ | decisions_trading_soundness |
| `docs/01_ENGINEERING_PRINCIPLES.md` | NOT_RECORDED | - |
| `docs/DECISIONS.md` | DEEP_READ | decisions_requirements_process |
| `docs/DOC_STATUS.md` | NOT_RECORDED | - |
| `docs/GLOSSARY.md` | NOT_RECORDED | - |
| `docs/README.md` | NOT_RECORDED | - |
| `docs/SOURCES.md` | NORMAL_READ | exchange_facts |
| `docs/TECHNOLOGY_STACK.md` | NOT_RECORDED | - |
| `docs/architecture/ARCHITECTURE.md` | NOT_RECORDED | - |
| `docs/architecture/DATA_PIPELINE.md` | NOT_RECORDED | - |
| `docs/backtest/BACKTEST_SPEC.md` | NOT_RECORDED | - |
| `docs/backtest/METRICS.md` | NOT_RECORDED | - |
| `docs/configuration/CONFIGURATION.md` | NOT_RECORDED | - |
| `docs/data/DATA_MODEL.md` | NOT_RECORDED | - |
| `docs/implementation/AGENT_INSTRUCTIONS.md` | NOT_RECORDED | - |
| `docs/implementation/IMPLEMENTATION_PLAN.md` | NOT_RECORDED | - |
| `docs/integration/BINANCE.md` | DEEP_READ | exchange_facts |
| `docs/integration/TELEGRAM.md` | NORMAL_READ | exchange_facts |
| `docs/integration/TRADINGVIEW.md` | NOT_READ | exchange_facts |
| `docs/operations/DEMO_VS_MAINNET.md` | DEEP_READ | exchange_facts |
| `docs/operations/DEPLOY_GUIDE.vi.md` | NORMAL_READ | operator_golive_gap |
| `docs/operations/RUNBOOK.md` | DEEP_READ | operator_golive_gap |
| `docs/operations/SECURITY_AND_OPERATIONS.md` | DEEP_READ | operator_golive_gap |
| `docs/research/GEOMETRY_AUDIT.md` | NOT_RECORDED | - |
| `docs/research/RESEARCH_PROTOCOL.md` | DEEP_READ | backtest_research_analytics |
| `docs/research/TRADING_STRATEGY_RESEARCH.md` | NORMAL_READ | strategy_viability |
| `docs/research/families/breakout-retest.md` | NOT_RECORDED | - |
| `docs/research/families/range-mr.md` | NOT_RECORDED | - |
| `docs/research/families/trend-pullback.md` | NORMAL_READ | strategy_viability |
| `docs/research/holdout_consumed.json` | NOT_RECORDED | - |
| `docs/research/kill_gate_decisions.json` | NOT_RECORDED | - |
| `docs/research/kill_gate_review_registry.json` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/A_klines_after_settlement.body.json` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/A_klines_after_settlement.headers.txt` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/A_klines_after_settlement.request.json` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/B_indexPriceKlines_before_settlement.body.json` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/B_indexPriceKlines_before_settlement.headers.txt` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/B_indexPriceKlines_before_settlement.request.json` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/F_indexklines_sample_day.body.json` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/F_indexklines_sample_day.headers.txt` | NOT_RECORDED | - |
| `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/F_indexklines_sample_day.request.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-authorization-breakout-retest.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-authorization-range-mr.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-authorization-trend-pullback.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-constraints-S1.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-constraints-baseline.json` | DEEP_READ | strategy_viability |
| `docs/research/preregistration/research-run-1-grid-breakout-retest.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-grid-range-mr.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-grid-trend-pullback.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-hypothesis-ADDENDUM-v2.3.0.md` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-hypothesis-DRAFT.md` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-hypothesis.md` | NORMAL_READ | strategy_viability |
| `docs/research/preregistration/research-run-1-manifest.json` | DEEP_READ | strategy_viability |
| `docs/research/preregistration/research-run-1-v2-2-0-authorization-breakout-retest.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-v2-2-0-authorization-range-mr.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-v2-2-0-authorization-trend-pullback.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-v2-3-0-authorization-breakout-retest.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-v2-3-0-authorization-range-mr.json` | NOT_RECORDED | - |
| `docs/research/preregistration/research-run-1-v2-3-0-authorization-trend-pullback.json` | NOT_RECORDED | - |
| `docs/research/universe/collect-list-v1.toml` | NOT_RECORDED | - |
| `docs/research/universe/collect-list-v2.toml` | NOT_RECORDED | - |
| `docs/research/universe/research-universe-v1.freeze-report.json` | NOT_RECORDED | - |
| `docs/research/universe/research-universe-v1.sufficiency-report.json` | NOT_RECORDED | - |
| `docs/research/universe/research-universe-v1.toml` | NOT_RECORDED | - |
| `docs/strategy/TRADING_STRATEGY_SPEC.md` | NOT_READ | decisions_trading_soundness |
| `docs/testing/TESTING_STRATEGY.md` | NORMAL_READ | prior_findings_closure_b |
| `docs/trading/EXECUTION_SPEC.md` | NORMAL_READ | decisions_requirements_process |
| `docs/trading/RISK_MANAGEMENT.md` | DEEP_READ | decisions_trading_soundness |
| `docs/trading/SIGNAL_AND_ALERTS.md` | NOT_READ | decisions_trading_soundness |
| `scripts/_compute_phase4_fixtures.py` | NORMAL_READ | scripts_tooling |
| `scripts/_extend_phase4_candles.py` | METADATA_ONLY | scripts_tooling |
| `scripts/_regen_phase4_expectations.py` | NORMAL_READ | scripts_tooling |
| `scripts/backup-drill.ps1` | NOT_READ | scripts_tooling |
| `scripts/check_image_paths.py` | METADATA_ONLY | scripts_tooling |
| `scripts/decision_alignment/authority.py` | NORMAL_READ | scripts_tooling |
| `scripts/decision_alignment/bookkeeping.py` | NORMAL_READ | scripts_tooling |
| `scripts/decision_alignment/exchange.py` | NORMAL_READ | scripts_tooling |
| `scripts/decision_alignment/ops_risk.py` | DEEP_READ | scripts_tooling |
| `scripts/decision_alignment/params.py` | NORMAL_READ | scripts_tooling |
| `scripts/decision_alignment/protocol.py` | NORMAL_READ | scripts_tooling |
| `scripts/decision_alignment/universe.py` | METADATA_ONLY | scripts_tooling |
| `scripts/demo_clear.py` | DEEP_READ | scripts_tooling |
| `scripts/demo_probe.py` | NORMAL_READ | scripts_tooling |
| `scripts/demo_rehearsal.py` | NORMAL_READ | evidence_reproducibility |
| `scripts/dev/README.md` | NOT_RECORDED | - |
| `scripts/dev/_common.ps1` | NOT_RECORDED | - |
| `scripts/dev/clean.ps1` | NOT_RECORDED | - |
| `scripts/dev/journal-report.ps1` | NOT_RECORDED | - |
| `scripts/dev/migrate.ps1` | NOT_RECORDED | - |
| `scripts/dev/pytest_timing.py` | NOT_RECORDED | - |
| `scripts/dev/test.ps1` | NOT_RECORDED | - |
| `scripts/evaluate_demo_soak.py` | DEEP_READ | scripts_tooling |
| `scripts/evaluate_trial_soak.py` | DEEP_READ | scripts_tooling |
| `scripts/export_soak_evidence.py` | NORMAL_READ | scripts_tooling |
| `scripts/gen_phase14_fixtures.py` | NORMAL_READ | scripts_tooling |
| `scripts/gen_phase21_fixtures.py` | METADATA_ONLY | scripts_tooling |
| `scripts/gen_phase22_fixtures.py` | METADATA_ONLY | scripts_tooling |
| `scripts/gen_phase23_fixtures.py` | NORMAL_READ | scripts_tooling |
| `scripts/gen_phase6_fixtures.py` | NORMAL_READ | scripts_tooling |
| `scripts/geometry_census.py` | METADATA_ONLY | scripts_tooling |
| `scripts/paper_ws_smoke.py` | METADATA_ONLY | scripts_tooling |
| `scripts/repair_parquet_scale.py` | DEEP_READ | scripts_tooling |
| `scripts/shadow_rehearsal.py` | METADATA_ONLY | scripts_tooling |
| `scripts/smoke_backtest_realdata.py` | METADATA_ONLY | scripts_tooling |
| `scripts/soak_host_acceptance.py` | DEEP_READ | scripts_tooling |
| `scripts/user_data_silence_probe.py` | DEEP_READ | scripts_tooling |
| `scripts/user_data_smoke.py` | NORMAL_READ | scripts_tooling |
| `scripts/verify_decision_alignment.py` | DEEP_READ | scripts_tooling |
| `src/__init__.py` | NOT_RECORDED | - |
| `src/adapters/analytics_files.py` | NORMAL_READ | data_persistence_db |
| `src/adapters/analytics_store.py` | DEEP_READ | data_persistence_db |
| `src/adapters/binance_client.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_clock.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_errors.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_limits.py` | NORMAL_READ | binance_adapters |
| `src/adapters/binance_probe.py` | NORMAL_READ | binance_adapters |
| `src/adapters/binance_public.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_ratelimit_gate.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_usdm.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_userdata.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_userdata_events.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_userdata_router.py` | DEEP_READ | binance_adapters |
| `src/adapters/binance_userdata_supervisor.py` | DEEP_READ | binance_adapters |
| `src/adapters/code_version.py` | NOT_RECORDED | - |
| `src/adapters/paper_ws.py` | DEEP_READ | paper_gapfill |
| `src/adapters/telegram_callbacks.py` | DEEP_READ | telegram_alerts |
| `src/adapters/telegram_notify.py` | DEEP_READ | telegram_alerts |
| `src/analytics/__init__.py` | NOT_RECORDED | - |
| `src/analytics/approval_delay.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/cli.py` | NORMAL_READ | backtest_gapfill |
| `src/analytics/clock.py` | NORMAL_READ | backtest_gapfill |
| `src/analytics/core_metrics.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/excursion.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/family.py` | NOT_RECORDED | - |
| `src/analytics/gates.py` | NOT_RECORDED | - |
| `src/analytics/inputs.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/killgate.py` | NORMAL_READ | backtest_research_analytics |
| `src/analytics/killgate_guard.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/latency.py` | NORMAL_READ | backtest_gapfill |
| `src/analytics/lifecycle.py` | NORMAL_READ | backtest_gapfill |
| `src/analytics/live_outcomes.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/no_trade.py` | NOT_RECORDED | - |
| `src/analytics/provenance.py` | NOT_RECORDED | - |
| `src/analytics/render.py` | NOT_RECORDED | - |
| `src/analytics/render_common.py` | NOT_RECORDED | - |
| `src/analytics/render_killgate.py` | NOT_RECORDED | - |
| `src/analytics/render_metrics.py` | NOT_RECORDED | - |
| `src/analytics/render_sidecar.py` | NOT_RECORDED | - |
| `src/analytics/report.py` | NORMAL_READ | backtest_gapfill |
| `src/analytics/slices.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/stats.py` | NOT_RECORDED | - |
| `src/analytics/types.py` | DEEP_READ | backtest_gapfill |
| `src/analytics/universe.py` | NOT_RECORDED | - |
| `src/approval/__init__.py` | NOT_RECORDED | - |
| `src/approval/binding.py` | DEEP_READ | exec_placement |
| `src/approval/confirm_core.py` | DEEP_READ | exec_placement |
| `src/approval/mapping.py` | NORMAL_READ | exec_placement |
| `src/approval/reason_codes.py` | NOT_RECORDED | - |
| `src/approval/replay.py` | DEEP_READ | exec_placement |
| `src/approval/tokens.py` | DEEP_READ | exec_placement |
| `src/backtest/__init__.py` | NOT_RECORDED | - |
| `src/backtest/binding.py` | NOT_RECORDED | - |
| `src/backtest/case.py` | DEEP_READ | backtest_gapfill |
| `src/backtest/constraints.py` | NOT_RECORDED | - |
| `src/backtest/costs.py` | NOT_RECORDED | - |
| `src/backtest/engine.py` | NORMAL_READ | backtest_gapfill |
| `src/backtest/entry.py` | NOT_RECORDED | - |
| `src/backtest/exits.py` | NORMAL_READ | mutation_probe |
| `src/backtest/experiment.py` | NORMAL_READ | evidence_reproducibility |
| `src/backtest/funding.py` | DEEP_READ | backtest_gapfill |
| `src/backtest/ledger.py` | DEEP_READ | backtest_gapfill |
| `src/backtest/lifecycle.py` | DEEP_READ | backtest_gapfill |
| `src/backtest/records.py` | NOT_RECORDED | - |
| `src/backtest/report.py` | DEEP_READ | backtest_research_analytics |
| `src/backtest/semantics.py` | NOT_RECORDED | - |
| `src/backtest/series.py` | NOT_RECORDED | - |
| `src/backtest/simulator.py` | NOT_RECORDED | - |
| `src/backtest/validator.py` | NOT_RECORDED | - |
| `src/core/__init__.py` | DEEP_READ | core_strategy_risk |
| `src/core/_decimal.py` | DEEP_READ | core_strategy_risk |
| `src/core/features.py` | DEEP_READ | core_strategy_risk |
| `src/core/pivots.py` | DEEP_READ | core_strategy_risk |
| `src/core/planner.py` | DEEP_READ | core_strategy_risk |
| `src/core/strategy.py` | DEEP_READ | core_strategy_risk |
| `src/core/types.py` | DEEP_READ | core_strategy_risk |
| `src/data/archive.py` | NORMAL_READ | data_persistence_db |
| `src/data/backfill.py` | DEEP_READ | data_persistence_db |
| `src/data/backfill_cli.py` | NORMAL_READ | data_persistence_db |
| `src/data/case_input.py` | NORMAL_READ | data_persistence_db |
| `src/data/collect_list.py` | NOT_RECORDED | - |
| `src/data/collector.py` | NORMAL_READ | data_persistence_db |
| `src/data/coverage.py` | NORMAL_READ | data_persistence_db |
| `src/data/metadata.py` | NOT_RECORDED | - |
| `src/data/minute_source.py` | NORMAL_READ | data_persistence_db |
| `src/data/quality.py` | DEEP_READ | data_persistence_db |
| `src/data/store.py` | DEEP_READ | data_persistence_db |
| `src/data/sufficiency.py` | NORMAL_READ | data_persistence_db |
| `src/data/universe_freeze.py` | NORMAL_READ | data_persistence_db |
| `src/db/__init__.py` | NOT_RECORDED | - |
| `src/db/alembic/__init__.py` | NOT_RECORDED | - |
| `src/db/alembic/env.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0001_baseline.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0002_domain_registry.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0003_callback_mapping.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0004_persistence_integrity.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0005_live_sized_risk.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0006_approval_quantity.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0007_intent_resolution_reason.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0008_pending_protective_actions.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0009_validated_lot_filters.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0010_daily_risk_state.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0011_risk_reservations.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0012_reservation_margin.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0013_approval_money.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0014_decided_excl_expired.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/0015_order_event_time.py` | NOT_RECORDED | - |
| `src/db/alembic/versions/__init__.py` | NOT_RECORDED | - |
| `src/db/mappers.py` | NORMAL_READ | data_persistence_db |
| `src/db/models.py` | DEEP_READ | data_persistence_db |
| `src/domain/__init__.py` | NOT_RECORDED | - |
| `src/domain/algo_status.py` | DEEP_READ | binance_adapters |
| `src/domain/approval.py` | NOT_RECORDED | - |
| `src/domain/canonical.py` | DEEP_READ | core_strategy_risk |
| `src/domain/enums.py` | DEEP_READ | core_strategy_risk |
| `src/domain/exchange_errors.py` | DEEP_READ | binance_adapters |
| `src/domain/fill.py` | NOT_RECORDED | - |
| `src/domain/ids.py` | NOT_RECORDED | - |
| `src/domain/journal.py` | NOT_RECORDED | - |
| `src/domain/lot_filters.py` | NOT_RECORDED | - |
| `src/domain/order.py` | NOT_RECORDED | - |
| `src/domain/position.py` | NOT_RECORDED | - |
| `src/domain/rationale.py` | DEEP_READ | core_strategy_risk |
| `src/domain/registry.py` | DEEP_READ | core_strategy_risk |
| `src/domain/signal.py` | NOT_RECORDED | - |
| `src/domain/stream_records.py` | NORMAL_READ | binance_adapters |
| `src/domain/trade_plan.py` | NOT_RECORDED | - |
| `src/domain/transitions.py` | DEEP_READ | core_strategy_risk |
| `src/execution/__init__.py` | NOT_RECORDED | - |
| `src/execution/account_equity.py` | DEEP_READ | live_risk_state |
| `src/execution/approval_desk.py` | DEEP_READ | telegram_alerts |
| `src/execution/binding.py` | DEEP_READ | exec_placement |
| `src/execution/bracket_cache.py` | DEEP_READ | live_risk_state |
| `src/execution/cancel_verification.py` | DEEP_READ | exec_protection |
| `src/execution/confirm_flow.py` | DEEP_READ | telegram_alerts |
| `src/execution/confirm_recheck.py` | DEEP_READ | exec_placement |
| `src/execution/constraint_snapshot.py` | DEEP_READ | exec_gapfill |
| `src/execution/daily_stop.py` | DEEP_READ | live_risk_state |
| `src/execution/day_risk_service.py` | DEEP_READ | live_risk_state |
| `src/execution/emergency_close.py` | DEEP_READ | exec_protection |
| `src/execution/enablement.py` | DEEP_READ | exec_placement |
| `src/execution/execution_limits.py` | DEEP_READ | exec_gapfill |
| `src/execution/fill_monitor.py` | DEEP_READ | exec_protection |
| `src/execution/gates.py` | DEEP_READ | exec_placement |
| `src/execution/intent_recovery.py` | DEEP_READ | exec_placement |
| `src/execution/intent_store.py` | DEEP_READ | exec_placement |
| `src/execution/liquidation_watch.py` | DEEP_READ | exec_protection |
| `src/execution/live_context.py` | DEEP_READ | exec_protection |
| `src/execution/live_risk_inputs.py` | DEEP_READ | live_risk_state |
| `src/execution/lot_filter_source.py` | DEEP_READ | exec_gapfill |
| `src/execution/lot_split.py` | DEEP_READ | exec_gapfill |
| `src/execution/manager.py` | DEEP_READ | exec_placement |
| `src/execution/margin_guard.py` | DEEP_READ | live_risk_state |
| `src/execution/order_ids.py` | DEEP_READ | exec_placement |
| `src/execution/pending_actions.py` | DEEP_READ | exec_protection |
| `src/execution/placement.py` | DEEP_READ | exec_placement |
| `src/execution/pre_placement.py` | DEEP_READ | exec_placement |
| `src/execution/prior_outcome.py` | DEEP_READ | exec_placement |
| `src/execution/protection.py` | DEEP_READ | exec_protection |
| `src/execution/protection_rebuild.py` | DEEP_READ | exec_protection |
| `src/execution/protection_replay.py` | DEEP_READ | exec_protection |
| `src/execution/symbol_config_guard.py` | DEEP_READ | live_risk_state |
| `src/execution/tp_sizing.py` | DEEP_READ | exec_gapfill |
| `src/live/__init__.py` | METADATA_ONLY | live_composition |
| `src/live/alerts.py` | DEEP_READ | telegram_alerts |
| `src/live/approval_sender.py` | DEEP_READ | telegram_alerts |
| `src/live/commission.py` | DEEP_READ | live_risk_state |
| `src/live/config.py` | DEEP_READ | live_composition |
| `src/live/enablement.py` | DEEP_READ | live_composition |
| `src/live/exchange.py` | DEEP_READ | live_composition |
| `src/live/execution_service.py` | DEEP_READ | live_composition |
| `src/live/feeds.py` | DEEP_READ | live_composition |
| `src/live/health.py` | DEEP_READ | live_composition |
| `src/live/operator.py` | DEEP_READ | live_composition |
| `src/live/order_index.py` | DEEP_READ | live_composition |
| `src/live/reconcile.py` | DEEP_READ | reconcile_safemode |
| `src/live/reservation_release.py` | DEEP_READ | live_risk_state |
| `src/live/risk_inputs.py` | DEEP_READ | live_risk_state |
| `src/live/runtime.py` | DEEP_READ | live_composition |
| `src/live/scheduled_cancel.py` | DEEP_READ | live_composition |
| `src/live/scheduler.py` | DEEP_READ | live_composition |
| `src/live/signal_source.py` | DEEP_READ | paper_gapfill |
| `src/live/smoke_injection.py` | DEEP_READ | evidence_reproducibility |
| `src/live/startup.py` | DEEP_READ | live_composition |
| `src/live/stream.py` | DEEP_READ | live_composition |
| `src/live/stream_persistence.py` | DEEP_READ | paper_gapfill |
| `src/live/telegram_runner.py` | DEEP_READ | telegram_alerts |
| `src/live/wiring.py` | DEEP_READ | live_composition |
| `src/live/wiring_parts.py` | DEEP_READ | live_composition |
| `src/ops/__init__.py` | METADATA_ONLY | ops_deploy_security |
| `src/ops/alert_wording.py` | DEEP_READ | telegram_alerts |
| `src/ops/alerts.py` | DEEP_READ | telegram_alerts |
| `src/ops/backup.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/backup_gate.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/backup_remote.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/cutover.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/drills.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/evidence_remote.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/health.py` | NOT_RECORDED | - |
| `src/ops/operator_evidence.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/redaction.py` | DEEP_READ | ops_deploy_security |
| `src/ops/rest_gate_cli.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/rest_gate_state.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/risk_first.py` | NOT_RECORDED | - |
| `src/ops/spill.py` | NORMAL_READ | ops_deploy_security |
| `src/ops/store_executor.py` | NOT_RECORDED | - |
| `src/paper/__init__.py` | METADATA_ONLY | paper_gapfill |
| `src/paper/attribution.py` | DEEP_READ | paper_gapfill |
| `src/paper/bars.py` | DEEP_READ | paper_runtime |
| `src/paper/coverage.py` | DEEP_READ | paper_gapfill |
| `src/paper/evidence_bundle.py` | DEEP_READ | paper_gapfill |
| `src/paper/evidence_export.py` | DEEP_READ | paper_gapfill |
| `src/paper/exit_criteria.py` | DEEP_READ | paper_runtime |
| `src/paper/freeze.py` | DEEP_READ | paper_runtime |
| `src/paper/held_marker.py` | METADATA_ONLY | paper_runtime |
| `src/paper/journal.py` | DEEP_READ | paper_gapfill |
| `src/paper/live_minutes.py` | DEEP_READ | paper_runtime |
| `src/paper/liveness.py` | NORMAL_READ | paper_runtime |
| `src/paper/loop.py` | NORMAL_READ | paper_runtime |
| `src/paper/market_inputs.py` | DEEP_READ | paper_runtime |
| `src/paper/notify.py` | DEEP_READ | paper_gapfill |
| `src/paper/pipeline.py` | DEEP_READ | paper_runtime |
| `src/paper/rehearsal.py` | METADATA_ONLY | paper_runtime |
| `src/paper/replay_inputs.py` | DEEP_READ | paper_gapfill |
| `src/paper/restart.py` | DEEP_READ | paper_runtime |
| `src/paper/resync.py` | DEEP_READ | paper_runtime |
| `src/paper/runtime.py` | DEEP_READ | paper_runtime |
| `src/paper/runtime_config.py` | NORMAL_READ | paper_runtime |
| `src/paper/runtime_state.py` | NORMAL_READ | paper_runtime |
| `src/paper/shadow.py` | DEEP_READ | paper_gapfill |
| `src/paper/shadow_confirm.py` | DEEP_READ | paper_gapfill |
| `src/paper/shadow_fill.py` | DEEP_READ | paper_runtime |
| `src/paper/shadow_ledger.py` | DEEP_READ | paper_gapfill |
| `src/paper/shadow_runtime.py` | DEEP_READ | paper_runtime |
| `src/paper/supervisor.py` | DEEP_READ | paper_runtime |
| `src/paper/surface.py` | DEEP_READ | paper_gapfill |
| `src/paper/vocabulary.py` | METADATA_ONLY | paper_runtime |
| `src/persistence/__init__.py` | NOT_RECORDED | - |
| `src/persistence/approvals.py` | DEEP_READ | data_persistence_db |
| `src/persistence/day_risk.py` | DEEP_READ | live_risk_state |
| `src/persistence/engine.py` | DEEP_READ | data_persistence_db |
| `src/persistence/entities.py` | DEEP_READ | data_persistence_db |
| `src/persistence/errors.py` | DEEP_READ | data_persistence_db |
| `src/persistence/execution_state.py` | DEEP_READ | data_persistence_db |
| `src/persistence/journal.py` | DEEP_READ | data_persistence_db |
| `src/persistence/lot_filters.py` | DEEP_READ | data_persistence_db |
| `src/persistence/paper_runtime_state.py` | NORMAL_READ | data_persistence_db |
| `src/persistence/pending_actions.py` | NORMAL_READ | exec_protection |
| `src/persistence/risk_reservations.py` | DEEP_READ | live_risk_state |
| `src/persistence/safe_mode_store.py` | DEEP_READ | reconcile_safemode |
| `src/persistence/shadow_stores.py` | METADATA_ONLY | data_persistence_db |
| `src/persistence/snapshots.py` | DEEP_READ | data_persistence_db |
| `src/persistence/system_state.py` | DEEP_READ | reconcile_safemode |
| `src/persistence/uow.py` | DEEP_READ | data_persistence_db |
| `src/reconcile/__init__.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/classify.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/compare.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/feed_freshness.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/local_intent.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/loop.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/safe_mode.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/startup.py` | DEEP_READ | reconcile_safemode |
| `src/reconcile/sweeper.py` | DEEP_READ | reconcile_safemode |
| `src/research/__init__.py` | NOT_RECORDED | - |
| `src/research/authorization.py` | NORMAL_READ | backtest_gapfill |
| `src/research/feasibility.py` | NOT_RECORDED | - |
| `src/research/manifest.py` | NORMAL_READ | backtest_gapfill |
| `src/research/manifest_build.py` | DEEP_READ | backtest_gapfill |
| `src/research/multiplicity.py` | NOT_RECORDED | - |
| `src/research/plateau.py` | NOT_RECORDED | - |
| `src/research/register.py` | DEEP_READ | backtest_gapfill |
| `src/research/report.py` | NOT_RECORDED | - |
| `src/research/run.py` | NORMAL_READ | backtest_research_analytics |
| `src/research/settlement_evidence.py` | DEEP_READ | backtest_gapfill |
| `src/risk/__init__.py` | NOT_RECORDED | - |
| `src/risk/cost_guards.py` | DEEP_READ | core_strategy_risk |
| `src/risk/cost_rates.py` | DEEP_READ | core_strategy_risk |
| `src/risk/daily_loss.py` | DEEP_READ | live_risk_state |
| `src/risk/gating.py` | DEEP_READ | core_strategy_risk |
| `src/risk/liquidation.py` | DEEP_READ | live_risk_state |
| `src/risk/live_commission.py` | DEEP_READ | live_risk_state |
| `src/risk/live_equity.py` | DEEP_READ | live_risk_state |
| `src/risk/margin_check.py` | DEEP_READ | live_risk_state |
| `src/risk/money_at_stake.py` | NORMAL_READ | live_risk_state |
| `src/risk/portfolio.py` | DEEP_READ | core_strategy_risk |
| `src/risk/quantization.py` | DEEP_READ | core_strategy_risk |
| `src/risk/realized_risk.py` | DEEP_READ | core_strategy_risk |
| `src/risk/reservations.py` | DEEP_READ | live_risk_state |
| `src/risk/sizing.py` | DEEP_READ | core_strategy_risk |
| `src/risk/types.py` | DEEP_READ | core_strategy_risk |
| `src/sql/coverage_v1.sql` | NOT_RECORDED | - |

## Rows recorded for paths or groups not in the list above

- `.dockerignore`: DEEP_READ (ops_deploy_security)
- `.github/workflows/ci.yml`: DEEP_READ (ops_deploy_security)
- `.github/workflows/registry-gate.yml`: NORMAL_READ (evidence_reproducibility)
- `.github/workflows/registry-gate.yml, research-gate.yml, paper_freeze_check.yml`: NORMAL_READ (ops_deploy_security)
- `.github/workflows/research-gate.yml`: DEEP_READ (prior_findings_closure_b)
- `.gitignore`: DEEP_READ (ops_deploy_security)
- `.planning/PROJECT.md`: METADATA_ONLY (decisions_requirements_process)
- `.planning/REQUIREMENTS.md`: DEEP_READ (decisions_requirements_process)
- `.planning/ROADMAP.md`: NORMAL_READ (decisions_requirements_process)
- `.planning/STATE.md`: NORMAL_READ (decisions_requirements_process)
- `.planning/audits/2026-09-29-deep-audit/findings.json`: DEEP_READ (prior_findings_closure_a)
- `.planning/phases/16-*/decisions/16-DEC-candidate.md`: NORMAL_READ (strategy_viability)
- `.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt`: DEEP_READ (strategy_viability)
- `.planning/phases/18-*/evidence/18-probe-check.txt`: NORMAL_READ (exchange_facts)
- `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md`: METADATA_ONLY (failure_scenarios)
- `.planning/phases/24-.../evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T{083259,104211}Z.json`: NORMAL_READ (decisions_requirements_process)
- `.planning/phases/24-live-runtime-composition-demo/24-OWNER-RUNBOOK.md`: DEEP_READ (operator_golive_gap)
- `.planning/phases/24-live-runtime-composition-demo/evidence/silence-probe-20261031T114816Z.json`: DEEP_READ (evidence_reproducibility)
- `.planning/phases/25-demo-integration-test-campaign/25-OWNER-RUNBOOK.md`: NORMAL_READ (operator_golive_gap)
- `18-.../decisions/18-DEC-O-18-01.md`: NORMAL_READ (decisions_requirements_process)
- `19-OWNER-GAPS.md`: NORMAL_READ (decisions_requirements_process)
- `25-OWNER-DECISIONS.md`: NORMAL_READ (decisions_requirements_process)
- `AGENTS.md`: NORMAL_READ (decisions_requirements_process)
- `Discussion logs 11, 12, 13, 13.1, 14, 15, 17, 18, 23, 25`: DEEP_READ (decisions_requirements_process)
- `Dockerfile`: DEEP_READ (ops_deploy_security)
- `Phases 11-15, 17, 18, 23, 25 CONTEXT / DISCUSSION-LOG`: NOT_READ (decisions_trading_soundness)
- `Telegram approval / confirm cards`: NOT_READ (operator_golive_gap)
- `config/binance/README.md, config/execution/README.md`: NORMAL_READ (exchange_facts)
- `config/paper/*`: NOT_READ (decisions_trading_soundness)
- `deploy/backup-drill.sh, deploy/backup-real-s3-gate.sh`: NORMAL_READ (ops_deploy_security)
- `deploy/compose-rehearsal.sh, deploy/soak-image.sh`: METADATA_ONLY (ops_deploy_security)
- `deploy/soak.env.example, deploy/evidence.env.example`: NORMAL_READ (ops_deploy_security)
- `docker-compose.yml`: DEEP_READ (ops_deploy_security)
- `docs/research/experiments/research-run-1/*.json`: METADATA_ONLY (backtest_research_analytics)
- `docs/research/preregistration/*`: NORMAL_READ (backtest_research_analytics)
- `params/range-mr/baseline-v6.toml`: DEEP_READ (core_strategy_risk)
- `params/trend-pullback/baseline-v6.toml`: DEEP_READ (decisions_trading_soundness)
- `params/trend-pullback/research-run-1-a01.toml`: DEEP_READ (strategy_viability)
- `pyproject.toml`: DEEP_READ (ops_deploy_security)
- `scripts/dev/*.ps1, scripts/dev/README.md, scripts/dev/pytest_timing.py`: NOT_READ (scripts_tooling)
- `src/approval/reason_codes.py, src/approval/__init__.py`: NOT_READ (exec_placement)
- `src/db/alembic/versions/0001..0015`: NORMAL_READ (data_persistence_db)
- `src/domain/approval.py, order.py, fill.py, position.py, journal.py, __init__.py`: NORMAL_READ (core_strategy_risk)
- `src/domain/exchange_errors.py, algo_status.py, stream_records.py`: NOT_READ (core_strategy_risk)
- `src/domain/ids.py, trade_plan.py, signal.py, lot_filters.py`: DEEP_READ (core_strategy_risk)
- `src/execution/manager.py 1780-3076`: DEEP_READ (exec_gapfill)
- `src/execution/order_ids.py, src/risk/liquidation.py`: METADATA_ONLY (exchange_facts)
- `src/execution/placement.py 213-440`: NORMAL_READ (exec_gapfill)
- `src/ops/alerts.py, alert_wording.py`: NOT_READ (ops_deploy_security)
- `src/ops/health.py, risk_first.py, store_executor.py`: NORMAL_READ (ops_deploy_security)
- `src/persistence/{pending_actions,risk_reservations,day_risk,safe_mode_store,system_state}.py`: NOT_READ (data_persistence_db)
- `tests/conftest.py`: METADATA_ONLY (strategy_viability)
- `tests/demo/__init__.py`: METADATA_ONLY (scripts_tooling)
- `tests/demo/conftest.py`: DEEP_READ (scripts_tooling)
- `tests/demo/test_demo_s00, s02-s12, s14-s19`: METADATA_ONLY (scripts_tooling)
- `tests/demo/test_demo_s01_happy.py, test_demo_s13_margin_liquidation.py`: NORMAL_READ (scripts_tooling)
- `tests/fixtures/phase4/parameters.json`: DEEP_READ (evidence_reproducibility)
- `tests/support/ast_guards.py`: DEEP_READ (test_effectiveness_ci)
- `tests/support/fake_binance_exchange.py`: DEEP_READ (test_effectiveness_ci)
- `tests/test_backtest_determinism.py`: NORMAL_READ (evidence_reproducibility)
- `tests/test_demo_twin_s08_stream_loss.py`: NORMAL_READ (test_effectiveness_ci)
- `tests/test_phase25_gate.py`: METADATA_ONLY (test_effectiveness_ci)
- `tool-output/pytest.txt`: DEEP_READ (test_effectiveness_ci)
- `uv.lock`: METADATA_ONLY (ops_deploy_security)
