---
phase: "18"
slug: user-data-stream-error-taxonomy
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-15"
---

# Phase 18 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: 18-RESEARCH.md "Validation Architecture". Execution runs on a connected machine (user rule, 2026-10-15); this machine only plans and verifies plans.
>
> The per-task map below was filled on 2026-10-15 from the 25 final PLAN files (74 tasks). `nyquist_compliant`, `wave_0_complete`, the sign-off boxes and the approval line are deliberately left as `false`, unchecked and `pending`: the user sets them at plan acceptance, not the planner.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x with pytest-asyncio 1.4 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest -m "not docker" tests/<touched_file>.py -x` |
| **Full suite command** | `uv run pytest -m "not docker"` |
| **Other gates** | `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check` |
| **Live-PostgreSQL tests** | need `TEST_DATABASE_URL`; skip without it (G4-043 and G4-034 store tests) |
| **Estimated runtime** | quick: under 30 s per file; full suite: see Phase 17 baseline |

---

## Sampling Rate

- **After every task commit:** the touched test file(s) with `-x`, then `uv run ruff check` and `uv run mypy src` on the touched modules.
- **After every plan wave:** `uv run pytest -m "not docker"`, `uv run ruff format --check`, `uv lock --check`.
- **Before `/gsd-verify-work`:** full suite green and the blocking-human evidence files attached (or the user's recorded postponement of the live smoke or probe).
- **Max feedback latency:** one test file per task.

---

## Per-Task Verification Map

Task id is `18-<plan>-<task>`. Requirement is the requirement list of the plan that owns the task. "Automated Command" is the task's primary `<automated>` command (the first pytest command; every task also runs `uv run ruff check`, and code tasks `uv run mypy src`, as its own `<verify>` block states); a long inline Python record check is referenced by plan and task instead of being copied. "File Exists" says whether the test files of the command exist today or which task creates them (Wave 0 files are created by the tasks, TDD red first). Status is `pending` for every task until it runs.

| Task ID | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|-------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 1 | EXEC-05,EXEC-01 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py -x` | Wave 0: created here (test_sources_phase18_section.py) | pending |
| 18-01-02 | 1 | EXEC-05,EXEC-01 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py -x` | Wave 0: created by 18-01-01 | pending |
| 18-01-03 | 1 | EXEC-05,EXEC-01 | doc structure | `uv run pytest -m "not docker" tests/test_decision_alignment_exchange.py tests/test_sources_phase18_section.py -x` | Wave 0: created by 18-01-01 | pending |
| 18-02-01 | 1 | OPS-02,EXEC-05,EXEC-01 | record check | inline check, see PLAN 18-02 Task 1 verify | n/a | pending |
| 18-02-02 | 1 | OPS-02,EXEC-05,EXEC-01 | blocking-human (manual) | inline check, see PLAN 18-02 Task 2 verify | n/a (decision or evidence record) | pending |
| 18-02-03 | 1 | OPS-02,EXEC-05,EXEC-01 | record check | inline check, see PLAN 18-02 Task 3 verify | n/a | pending |
| 18-03-01 | 1 | EXEC-05,EXEC-02 | unit | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_execution_partials.py tests/test_execution_attach.py -x` | Wave 0: created here (test_userdata_events.py) | pending |
| 18-03-02 | 1 | EXEC-05,EXEC-02 | blocking-human (manual) | inline check, see PLAN 18-03 Task 2 verify | n/a (decision or evidence record) | pending |
| 18-03-03 | 1 | EXEC-05,EXEC-02 | unit | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_userdata_parsers.py -x` | Wave 0: created here (test_userdata_parsers.py); others by 18-03-01 | pending |
| 18-04-01 | 1 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_binance_client_config.py tests/test_demo_rehearsal_safety.py -x` | Wave 0: created here (test_binance_client_config.py) | pending |
| 18-04-02 | 1 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_binance_client_config.py tests/test_demo_rehearsal_safety.py tests/test_demo_rehearsal_flow.py -x` | Wave 0: created by 18-04-01 | pending |
| 18-04-03 | 1 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_binance_secret_redaction.py tests/test_redaction.py tests/test_binance_client_config.py -x` | Wave 0: created here (test_binance_secret_redaction.py); others by 18-04-01 | pending |
| 18-05-01 | 2 | EXEC-02,EXEC-01 | contract | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_sdk_error_mapping_contract.py -x` | Wave 0: created here (test_exchange_errors.py, test_sdk_error_mapping_contract.py) | pending |
| 18-05-02 | 2 | EXEC-02,EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_exchange_errors.py -x` | Wave 0: created by 18-05-01 | pending |
| 18-05-03 | 2 | EXEC-02,EXEC-01 | contract | `uv run pytest -m "not docker" tests/test_sdk_error_mapping_contract.py tests/test_exchange_errors.py -x` | Wave 0: created by 18-05-01 | pending |
| 18-06-01 | 2 | EXEC-01,EXEC-02 | unit | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_execution_attach.py tests/test_execution_manager.py -x` | Wave 0: created here (test_algo_status.py) | pending |
| 18-06-02 | 2 | EXEC-01,EXEC-02 | doc structure | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_reconcile.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-06-01 | pending |
| 18-07-01 | 2 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_binance_limits.py -x` | Wave 0: created here (test_binance_limits.py) | pending |
| 18-07-02 | 2 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_clock_drift.py tests/test_binance_limits.py -x` | Wave 0: created here (test_clock_drift.py); others by 18-07-01 | pending |
| 18-07-03 | 2 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_no_unratified_defaults.py tests/test_binance_limits.py -x` | Wave 0: created here (test_no_unratified_defaults.py); others by 18-07-01 | pending |
| 18-08-01 | 2 | EXEC-02,EXEC-05 | PostgreSQL integration | `uv run pytest -m "not docker" tests/test_stream_records.py tests/test_persistence_exit_evidence_pg.py tests/test_persistence_transitions_pg.py -x -rs` | Wave 0: created here (test_stream_records.py, test_persistence_exit_evidence_pg.py) | pending |
| 18-08-02 | 2 | EXEC-02,EXEC-05 | PostgreSQL integration | `uv run pytest -m "not docker" tests/test_stream_records.py tests/test_persistence_exit_evidence_pg.py tests/test_persistence_transitions_pg.py tests/test_persistence_journal_pg.py -x -rs` | Wave 0: created by 18-08-01 | pending |
| 18-24-01 | 2 | EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_userdata_fixtures.py tests/test_userdata_events.py -x` | Wave 0: created here (test_userdata_fixtures.py); others by 18-03-01 | pending |
| 18-24-02 | 2 | EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_userdata_fixtures.py tests/test_userdata_events.py tests/test_userdata_parsers.py -x` | Wave 0: created by 18-03-01, 18-03-03, 18-24-01 | pending |
| 18-09-01 | 3 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_binance_limits_ratified_file.py tests/test_binance_limits.py -x` | Wave 0: created here (test_binance_limits_ratified_file.py); others by 18-07-01 | pending |
| 18-09-02 | 3 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_binance_client_config.py tests/test_binance_limits_ratified_file.py tests/test_binance_secret_redaction.py tests/test_demo_rehearsal_safety.py -x` | Wave 0: created by 18-04-01, 18-04-03, 18-09-01 | pending |
| 18-09-03 | 3 | OPS-02,EXEC-05 | doc structure | `uv run pytest -m "not docker" tests/test_binance_limits_ratified_file.py tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-09-01 | pending |
| 18-10-01 | 3 | EXEC-02,EXEC-01 | contract | `uv run pytest -m "not docker" tests/test_adapter_not_found_mapping.py tests/test_binance_public.py tests/test_backfill.py tests/test_universe_freeze.py tests/test_execution_adapter_contract.py -x` | exists | pending |
| 18-10-02 | 3 | EXEC-02,EXEC-01 | contract | `uv run pytest -m "not docker" tests/test_binance_usdm_error_routing.py tests/test_adapter_not_found_mapping.py tests/test_execution_adapter_contract.py tests/test_reconcile.py tests/test_execution_manager.py -x` | Wave 0: created here (test_binance_usdm_error_routing.py) | pending |
| 18-10-03 | 3 | EXEC-02,EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_binance_usdm_source_guard.py tests/test_binance_usdm_error_routing.py tests/test_adapter_not_found_mapping.py -x` | Wave 0: created here (test_binance_usdm_source_guard.py); others by 18-10-02 | pending |
| 18-11-01 | 3 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_adapter.py tests/test_userdata_events.py tests/test_paper_ws_connect.py -x` | Wave 0: created here (test_userdata_adapter.py); others by 18-03-01 | pending |
| 18-11-02 | 3 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_adapter.py -x` | Wave 0: created by 18-11-01 | pending |
| 18-11-03 | 3 | EXEC-05,OPS-02 | contract + fake-driven | `uv run pytest -m "not docker" tests/test_userdata_contract.py tests/test_userdata_adapter.py tests/test_paper_ws_contract.py -x` | Wave 0: created here (test_userdata_contract.py); others by 18-11-01 | pending |
| 18-12-01 | 4 | EXEC-01,EXEC-02 | contract | `uv run pytest -m "not docker" tests/test_binance_probe.py tests/test_binance_probe_contract.py -x` | Wave 0: created here (test_binance_probe.py, test_binance_probe_contract.py) | pending |
| 18-12-02 | 4 | EXEC-01,EXEC-02 | contract | `uv run pytest -m "not docker" tests/test_binance_probe.py tests/test_binance_probe_contract.py -x` | Wave 0: created by 18-12-01 | pending |
| 18-12-03 | 4 | EXEC-01,EXEC-02 | contract | `uv run pytest -m "not docker" tests/test_binance_probe.py tests/test_binance_probe_contract.py tests/test_binance_public.py -x` | Wave 0: created by 18-12-01 | pending |
| 18-13-01 | 4 | OPS-02,EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_binance_usdm_signed_calls.py tests/test_binance_usdm_error_routing.py tests/test_binance_usdm_source_guard.py -x` | Wave 0: created here (test_binance_usdm_signed_calls.py); others by 18-10-02, 18-10-03 | pending |
| 18-13-02 | 4 | OPS-02,EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_binance_usdm_signed_calls.py tests/test_binance_usdm_error_routing.py tests/test_binance_usdm_source_guard.py tests/test_commission_rates.py -x` | Wave 0: created by 18-10-02, 18-10-03, 18-13-01 | pending |
| 18-13-03 | 4 | OPS-02,EXEC-01 | full suite (regression) | `uv run pytest -m "not docker" -x` | exists | pending |
| 18-14-01 | 4 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_supervisor.py tests/test_userdata_adapter.py -x` | Wave 0: created here (test_userdata_supervisor.py); others by 18-11-01 | pending |
| 18-14-02 | 4 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_supervisor.py -x` | Wave 0: created by 18-14-01 | pending |
| 18-14-03 | 4 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_supervisor.py -x` | Wave 0: created by 18-14-01 | pending |
| 18-15-01 | 5 | EXEC-05,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_rig.py tests/test_userdata_supervisor.py -x` | Wave 0: created here (test_userdata_rig.py); others by 18-14-01 | pending |
| 18-15-02 | 5 | EXEC-05,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_router.py tests/test_userdata_rig.py -x` | Wave 0: created here (test_userdata_router.py); others by 18-15-01 | pending |
| 18-15-03 | 5 | EXEC-05,EXEC-02 | replay | `uv run pytest -m "not docker" tests/test_userdata_replay.py tests/test_execution_partials.py tests/test_execution_attach.py -x` | Wave 0: created here (test_userdata_replay.py) | pending |
| 18-16-01 | 5 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_operator_evidence.py tests/test_user_data_smoke_dry_run.py -x` | Wave 0: created here (test_operator_evidence.py, test_user_data_smoke_dry_run.py) | pending |
| 18-16-02 | 5 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_dry_run.py tests/test_user_data_smoke_evidence.py tests/test_operator_evidence.py -x` | Wave 0: created here (test_user_data_smoke_evidence.py); others by 18-16-01 | pending |
| 18-16-03 | 5 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_cli.py tests/test_user_data_smoke_dry_run.py tests/test_user_data_smoke_evidence.py tests/test_demo_rehearsal_safety.py -x` | Wave 0: created here (test_user_data_smoke_cli.py); others by 18-16-01, 18-16-02 | pending |
| 18-17-01 | 6 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_operator_evidence.py -x` | Wave 0: created here (test_demo_probe_cases.py, test_demo_probe_evidence.py); others by 18-16-01 | pending |
| 18-17-02 | 6 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cli.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cases.py -x` | Wave 0: created here (test_demo_probe_cli.py); others by 18-17-01 | pending |
| 18-18-01 | 6 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_evidence.py tests/test_user_data_smoke_dry_run.py -x` | Wave 0: created by 18-16-01, 18-16-02 | pending |
| 18-18-02 | 6 | EXEC-05,OPS-02 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-01-01 | pending |
| 18-18-03 | 6 | EXEC-05,OPS-02 | blocking-human (manual) | inline check, see PLAN 18-18 Task 3 verify | n/a (decision or evidence record); a recorded postponement also passes | pending |
| 18-18-04 | 6 | EXEC-05,OPS-02 | record check | inline check, see PLAN 18-18 Task 4 verify | n/a; a recorded postponement also passes | pending |
| 18-23-01 | 7 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | pending |
| 18-23-02 | 7 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | pending |
| 18-23-03 | 7 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | pending |
| 18-19-01 | 8 | EXEC-05 | record check | inline check, see PLAN 18-19 Task 1 verify | n/a; `transport: none` with the postponement reason also passes | pending |
| 18-19-02 | 8 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_direct_transport.py tests/test_userdata_adapter.py -x` | Wave 0: created here (test_userdata_direct_transport.py); others by 18-11-01 | pending |
| 18-19-03 | 8 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_cli.py tests/test_user_data_smoke_dry_run.py tests/test_user_data_smoke_evidence.py tests/test_demo_probe_cli.py tests/test_demo_probe_evidence.py -x` | Wave 0: created by 18-16-01, 18-16-02, 18-16-03, 18-17-01, 18-17-02 | pending |
| 18-19-04 | 8 | EXEC-05 | blocking-human (manual) | inline check, see PLAN 18-19 Task 4 verify | n/a (decision or evidence record) | pending |
| 18-20-01 | 9 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | pending |
| 18-20-02 | 9 | EXEC-01,EXEC-02 | blocking-human (manual) | inline check, see PLAN 18-20 Task 2 verify | n/a (decision or evidence record) | pending |
| 18-20-03 | 9 | EXEC-01,EXEC-02 | blocking-human (manual) | inline check, see PLAN 18-20 Task 3 verify | n/a (decision or evidence record); a recorded postponement also passes | pending |
| 18-20-04 | 9 | EXEC-01,EXEC-02 | record check | inline check, see PLAN 18-20 Task 4 verify | n/a; a recorded postponement also passes | pending |
| 18-21-01 | 10 | EXEC-01,EXEC-02,EXEC-05 | replay + fake-driven | `uv run pytest -m "not docker" tests/test_userdata_recorded_frames.py tests/test_userdata_parsers.py tests/test_userdata_events.py tests/test_userdata_replay.py tests/test_userdata_router.py tests/test_userdata_fixtures.py -x` | Wave 0: created here (test_userdata_recorded_frames.py); others by 18-03-03, 18-03-01, 18-15-03, 18-15-02, 18-24-01; skipped by design when no recorded frame exists | pending |
| 18-21-02 | 10 | EXEC-01,EXEC-02,EXEC-05 | PostgreSQL integration | `uv run pytest -m "not docker" tests/test_fake_binance_semantics.py tests/test_exchange_errors.py tests/test_execution_manager.py tests/test_execution_exactly_once_pg.py tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_callback_redelivery_pg.py tests/test_intent_recovery.py tests/test_intent_recovery_pg.py -x -rs` | Wave 0: created here (test_fake_binance_semantics.py); others by 18-05-01 | pending |
| 18-25-01 | 11 | EXEC-01,EXEC-02,EXEC-05 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-01-01 | pending |
| 18-25-02 | 11 | EXEC-01,EXEC-02,EXEC-05 | doc structure | `uv run pytest -m "not docker" tests/test_decision_alignment_exchange.py tests/test_decision_alignment_bookkeeping.py tests/test_sources_phase18_section.py -x` | Wave 0: created by 18-01-01 | pending |
| 18-25-03 | 11 | EXEC-01,EXEC-02,EXEC-05 | record check | inline check, see PLAN 18-25 Task 3 verify | n/a | pending |
| 18-22-01 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | phase gate | `uv run pytest -m "not docker" tests/test_phase18_gate.py -x` | Wave 0: created here (test_phase18_gate.py) | pending |
| 18-22-02 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | full suite (strict, PostgreSQL) | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" -q -rs` | exists | pending |
| 18-22-03 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | blocking-human (manual) | inline check, see PLAN 18-22 Task 3 verify | n/a (decision or evidence record) | pending |
| 18-22-04 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | record check | inline check, see PLAN 18-22 Task 4 verify | n/a; a recorded deferral also passes | pending |

The rows are ordered by wave. Blocking-human tasks (7: 18-02-02, 18-03-02, 18-18-03, 18-19-04, 18-20-02, 18-20-03, 18-22-03) carry an automated record check of the user's decision or evidence file, not a test of the live behavior; record checks (7) read a file the previous task wrote.

### Requirement-level mapping

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| EXEC-05 | stream events become fills and state hints with REST fallback; replay, reorder and duplicate stay idempotent; recorded and synthetic frames parse | unit + fake rig + replay + fixtures | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_userdata_parsers.py tests/test_userdata_fixtures.py tests/test_userdata_adapter.py tests/test_userdata_contract.py tests/test_userdata_supervisor.py tests/test_userdata_router.py tests/test_userdata_replay.py tests/test_userdata_rig.py -x` | Wave 0 (created by the tasks above) |
| EXEC-01 | algo status table drives attach and adoption; placement is never retried; the probe records the D055 facts | unit + fake rig | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_execution_attach.py tests/test_binance_usdm_error_routing.py tests/test_binance_usdm_signed_calls.py tests/test_binance_probe.py tests/test_demo_probe_cases.py -x` | partial (attach test exists) |
| EXEC-02 | not-found and rate-limit handling in probes and the sweeper; evidence source recorded | unit + contract | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_sdk_error_mapping_contract.py tests/test_adapter_not_found_mapping.py tests/test_persistence_exit_evidence_pg.py tests/test_reconcile.py -x` | partial |
| OPS-02 | no secret, signature or listenKey in any output; explicit environment; ratified limits only | unit | `uv run pytest -m "not docker" tests/test_binance_secret_redaction.py tests/test_binance_client_config.py tests/test_binance_limits.py tests/test_clock_drift.py tests/test_no_unratified_defaults.py -x` | Wave 0 (created by the tasks above) |

---

## Wave 0 Requirements

- [ ] `tests/userdata_fakes.py` (created by 18-11-01) - SDK-shaped fake streams client and handle, mirrored by `tests/test_userdata_contract.py` (18-11-03; precedent: `paper_ws_fakes.py` and `test_paper_ws_contract.py`)
- [ ] `tests/support/userdata_frames.py` (18-03-01), `tests/support/ast_guards.py` (18-03-03), `tests/support/virtual_time.py` (18-14-01), `tests/support/limits.py` (18-07-01): test support created by the first task that needs it
- [ ] `tests/fixtures/phase18/synthetic/` and its README - frames labelled `SYNTHETIC_FROM_SDK_MODEL`, created by 18-24 from the frame builders; `RECORDED_DEMO` frames are added by the live smoke (18-18) and probe (18-20) and consumed by 18-21, and are absent when the user postponed those steps
- [ ] every file marked `Wave 0: created here` in the map above
- [ ] no framework install needed

---

## Manual-Only Verifications (blocking-human, connected machine)

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| O-18-01 ratification of safety numbers | OPS-02, EXEC-05 | owner-only (D061 H and I) | user fills the value column of the ratification table and records the decision file |
| Documentation re-read of the four event pages | EXEC-05 | this machine cannot fetch them | executor repeats the reads, updates the Phase 18 SOURCES section, records failures verbatim |
| Live Demo smoke (acceptance a to h in 18-RESEARCH.md) | EXEC-05, OPS-02 | needs Binance Demo keys and network | run the smoke script on the connected machine with Demo keys in the shell session; the user may instead record a postponement (a recorded skip) |
| Probe `--execute` (D-16 cases) | EXEC-01, EXEC-02 | needs Binance Demo and the user typing the confirmation phrase | run the probe script; cleanup leaves zero open orders, zero open algo orders, flat position; the user may instead record a postponement (a recorded skip) |
| Integration of `phase-18` with `develop` | EXEC-01, EXEC-02, EXEC-05, OPS-02 | a rebase rewrites history, so only the user performs it | plan 18-22 Task 3: the user integrates and records `decisions/18-DEC-INTEGRATION.md`, or defers |

---

## Validation Sign-Off

Left for the user at plan acceptance (the planner does not tick these):

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency within one test file per task
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
