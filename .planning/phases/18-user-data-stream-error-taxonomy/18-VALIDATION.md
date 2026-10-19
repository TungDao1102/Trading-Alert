---
phase: "18"
slug: user-data-stream-error-taxonomy
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-15"
---

# Phase 18 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: 18-RESEARCH.md "Validation Architecture". Execution runs on a connected machine (user rule, 2026-10-15); this machine only plans and verifies plans.
>
> The per-task map below was filled on 2026-10-15 from the 25 final PLAN files (74 tasks). `nyquist_compliant`, `wave_0_complete`, the sign-off boxes and the approval line are deliberately left as `false`, unchecked and `pending`: the user sets them at plan acceptance, not the planner.
>
> Updated 2026-10-16 after the plan revisions that follow the user's records `decisions/18-DEC-O-18-01.md` (27 canonical keys: the rate-limit wait split into a 418 key and a 429 key beside the cap; the four flagged ALGO_UPDATE classes UNKNOWN; and its section "Amendment 2026-10-16 (user): 429 semantics": no call retried because of a 418 or 429, a 418 bans and a 429 pauses every REST call of the process through one shared gate, a blocked protective order surfaces as an unprotected position) and `decisions/18-DEC-D01-event-types.md`. The commands of rows 18-10-02, 18-13-02 and 18-14-02 are copied from the current plans; every other row's command was compared with its plan and is unchanged. The named tests the revisions added are listed under "Named tests added by the 2026-10-16 plan revisions".

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
| 18-01-01 | 1 | EXEC-05,EXEC-01 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py -x` | Wave 0: created here (test_sources_phase18_section.py) | green |
| 18-01-02 | 1 | EXEC-05,EXEC-01 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py -x` | Wave 0: created by 18-01-01 | green |
| 18-01-03 | 1 | EXEC-05,EXEC-01 | doc structure | `uv run pytest -m "not docker" tests/test_decision_alignment_exchange.py tests/test_sources_phase18_section.py -x` | Wave 0: created by 18-01-01 | green |
| 18-02-01 | 1 | OPS-02,EXEC-05,EXEC-01 | record check | inline check, see PLAN 18-02 Task 1 verify | n/a | manual-only |
| 18-02-02 | 1 | OPS-02,EXEC-05,EXEC-01 | blocking-human (manual) | inline check, see PLAN 18-02 Task 2 verify | n/a (decision or evidence record) | manual-only |
| 18-02-03 | 1 | OPS-02,EXEC-05,EXEC-01 | record check | inline check, see PLAN 18-02 Task 3 verify | n/a | manual-only |
| 18-03-01 | 1 | EXEC-05,EXEC-02 | unit | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_execution_partials.py tests/test_execution_attach.py -x` | Wave 0: created here (test_userdata_events.py) | green |
| 18-03-02 | 1 | EXEC-05,EXEC-02 | blocking-human (manual) | inline check, see PLAN 18-03 Task 2 verify | n/a (decision or evidence record) | manual-only |
| 18-03-03 | 1 | EXEC-05,EXEC-02 | unit | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_userdata_parsers.py -x` | Wave 0: created here (test_userdata_parsers.py); others by 18-03-01 | green |
| 18-04-01 | 1 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_binance_client_config.py tests/test_demo_rehearsal_safety.py -x` | Wave 0: created here (test_binance_client_config.py) | green |
| 18-04-02 | 1 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_binance_client_config.py tests/test_demo_rehearsal_safety.py tests/test_demo_rehearsal_flow.py -x` | Wave 0: created by 18-04-01 | green |
| 18-04-03 | 1 | OPS-02 | unit | `uv run pytest -m "not docker" tests/test_binance_secret_redaction.py tests/test_redaction.py tests/test_binance_client_config.py -x` | Wave 0: created here (test_binance_secret_redaction.py); others by 18-04-01 | green |
| 18-05-01 | 2 | EXEC-02,EXEC-01 | contract | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_sdk_error_mapping_contract.py -x` | Wave 0: created here (test_exchange_errors.py, test_sdk_error_mapping_contract.py) | green |
| 18-05-02 | 2 | EXEC-02,EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_exchange_errors.py -x` | Wave 0: created by 18-05-01 | green |
| 18-05-03 | 2 | EXEC-02,EXEC-01 | contract | `uv run pytest -m "not docker" tests/test_sdk_error_mapping_contract.py tests/test_exchange_errors.py -x` | Wave 0: created by 18-05-01 | green |
| 18-06-01 | 2 | EXEC-01,EXEC-02 | unit | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_execution_attach.py tests/test_execution_manager.py -x` | Wave 0: created here (test_algo_status.py) | green |
| 18-06-02 | 2 | EXEC-01,EXEC-02 | doc structure | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_reconcile.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-06-01 | green |
| 18-07-01 | 2 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_binance_limits.py -x` | Wave 0: created here (test_binance_limits.py) | green |
| 18-07-02 | 2 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_clock_drift.py tests/test_binance_limits.py -x` | Wave 0: created here (test_clock_drift.py); others by 18-07-01 | green |
| 18-07-03 | 2 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_no_unratified_defaults.py tests/test_binance_limits.py -x` | Wave 0: created here (test_no_unratified_defaults.py); others by 18-07-01 | green |
| 18-08-01 | 2 | EXEC-02,EXEC-05 | PostgreSQL integration | `uv run pytest -m "not docker" tests/test_stream_records.py tests/test_persistence_exit_evidence_pg.py tests/test_persistence_transitions_pg.py -x -rs` | Wave 0: created here (test_stream_records.py, test_persistence_exit_evidence_pg.py) | green |
| 18-08-02 | 2 | EXEC-02,EXEC-05 | PostgreSQL integration | `uv run pytest -m "not docker" tests/test_stream_records.py tests/test_persistence_exit_evidence_pg.py tests/test_persistence_transitions_pg.py tests/test_persistence_journal_pg.py -x -rs` | Wave 0: created by 18-08-01 | green |
| 18-24-01 | 2 | EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_userdata_fixtures.py tests/test_userdata_events.py -x` | Wave 0: created here (test_userdata_fixtures.py); others by 18-03-01 | green |
| 18-24-02 | 2 | EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_userdata_fixtures.py tests/test_userdata_events.py tests/test_userdata_parsers.py -x` | Wave 0: created by 18-03-01, 18-03-03, 18-24-01 | green |
| 18-09-01 | 3 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_binance_limits_ratified_file.py tests/test_binance_limits.py -x` | Wave 0: created here (test_binance_limits_ratified_file.py); others by 18-07-01 | green |
| 18-09-02 | 3 | OPS-02,EXEC-05 | unit | `uv run pytest -m "not docker" tests/test_binance_client_config.py tests/test_binance_limits_ratified_file.py tests/test_binance_secret_redaction.py tests/test_demo_rehearsal_safety.py -x` | Wave 0: created by 18-04-01, 18-04-03, 18-09-01 | green |
| 18-09-03 | 3 | OPS-02,EXEC-05 | doc structure | `uv run pytest -m "not docker" tests/test_binance_limits_ratified_file.py tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-09-01 | green |
| 18-10-01 | 3 | EXEC-02,EXEC-01 | contract | `uv run pytest -m "not docker" tests/test_adapter_not_found_mapping.py tests/test_binance_public.py tests/test_backfill.py tests/test_universe_freeze.py tests/test_execution_adapter_contract.py -x` | exists | green |
| 18-10-02 | 3 | EXEC-02,EXEC-01 | contract + unit (shared rate-limit gate) | `uv run pytest -m "not docker" tests/test_binance_ratelimit_gate.py tests/test_binance_usdm_error_routing.py tests/test_binance_public.py tests/test_adapter_not_found_mapping.py tests/test_execution_adapter_contract.py tests/test_reconcile.py tests/test_execution_manager.py tests/test_backfill.py tests/test_universe_freeze.py -x` | Wave 0: created here (test_binance_ratelimit_gate.py, test_binance_usdm_error_routing.py); test_binance_public.py, test_backfill.py, test_universe_freeze.py exist and must pass unchanged | green |
| 18-10-03 | 3 | EXEC-02,EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_binance_usdm_source_guard.py tests/test_binance_usdm_error_routing.py tests/test_adapter_not_found_mapping.py -x` | Wave 0: created here (test_binance_usdm_source_guard.py); others by 18-10-02 | green |
| 18-11-01 | 3 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_adapter.py tests/test_userdata_events.py tests/test_paper_ws_connect.py -x` | Wave 0: created here (test_userdata_adapter.py); others by 18-03-01 | green |
| 18-11-02 | 3 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_adapter.py -x` | Wave 0: created by 18-11-01 | green |
| 18-11-03 | 3 | EXEC-05,OPS-02 | contract + fake-driven | `uv run pytest -m "not docker" tests/test_userdata_contract.py tests/test_userdata_adapter.py tests/test_paper_ws_contract.py -x` | Wave 0: created here (test_userdata_contract.py); others by 18-11-01 | green |
| 18-12-01 | 4 | EXEC-01,EXEC-02 | contract | `uv run pytest -m "not docker" tests/test_binance_probe.py tests/test_binance_probe_contract.py -x` | Wave 0: created here (test_binance_probe.py, test_binance_probe_contract.py) | green |
| 18-12-02 | 4 | EXEC-01,EXEC-02 | contract | `uv run pytest -m "not docker" tests/test_binance_probe.py tests/test_binance_probe_contract.py -x` | Wave 0: created by 18-12-01 | green |
| 18-12-03 | 4 | EXEC-01,EXEC-02 | contract | `uv run pytest -m "not docker" tests/test_binance_probe.py tests/test_binance_probe_contract.py tests/test_binance_public.py -x` | Wave 0: created by 18-12-01 | green |
| 18-13-01 | 4 | OPS-02,EXEC-01 | unit | `uv run pytest -m "not docker" tests/test_binance_usdm_signed_calls.py tests/test_binance_usdm_error_routing.py tests/test_binance_usdm_source_guard.py -x` | Wave 0: created here (test_binance_usdm_signed_calls.py); others by 18-10-02, 18-10-03 | green |
| 18-13-02 | 4 | OPS-02,EXEC-01 | unit + attach path | `uv run pytest -m "not docker" tests/test_binance_usdm_signed_calls.py tests/test_binance_usdm_error_routing.py tests/test_binance_usdm_source_guard.py tests/test_binance_ratelimit_gate.py tests/test_execution_attach.py tests/test_commission_rates.py -x` | Wave 0: created by 18-10-02, 18-10-03, 18-13-01; test_execution_attach.py exists | green |
| 18-13-03 | 4 | OPS-02,EXEC-01 | full suite (regression) | `uv run pytest -m "not docker" -x` | exists | manual-only |
| 18-14-01 | 4 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_supervisor.py tests/test_userdata_adapter.py -x` | Wave 0: created here (test_userdata_supervisor.py); others by 18-11-01 | green |
| 18-14-02 | 4 | EXEC-05 | fake-driven (incl. the shared gate on the listenKey port) | `uv run pytest -m "not docker" tests/test_userdata_supervisor.py tests/test_userdata_adapter.py tests/test_binance_ratelimit_gate.py -x` | Wave 0: created by 18-14-01, 18-11-01, 18-10-02 | green |
| 18-14-03 | 4 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_supervisor.py -x` | Wave 0: created by 18-14-01 | green |
| 18-15-01 | 5 | EXEC-05,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_rig.py tests/test_userdata_supervisor.py -x` | Wave 0: created here (test_userdata_rig.py); others by 18-14-01 | green |
| 18-15-02 | 5 | EXEC-05,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_router.py tests/test_userdata_rig.py -x` | Wave 0: created here (test_userdata_router.py); others by 18-15-01 | green |
| 18-15-03 | 5 | EXEC-05,EXEC-02 | replay | `uv run pytest -m "not docker" tests/test_userdata_replay.py tests/test_execution_partials.py tests/test_execution_attach.py -x` | Wave 0: created here (test_userdata_replay.py) | green |
| 18-16-01 | 5 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_operator_evidence.py tests/test_user_data_smoke_dry_run.py -x` | Wave 0: created here (test_operator_evidence.py, test_user_data_smoke_dry_run.py) | green |
| 18-16-02 | 5 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_dry_run.py tests/test_user_data_smoke_evidence.py tests/test_operator_evidence.py -x` | Wave 0: created here (test_user_data_smoke_evidence.py); others by 18-16-01 | green |
| 18-16-03 | 5 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_cli.py tests/test_user_data_smoke_dry_run.py tests/test_user_data_smoke_evidence.py tests/test_demo_rehearsal_safety.py -x` | Wave 0: created here (test_user_data_smoke_cli.py); others by 18-16-01, 18-16-02 | green |
| 18-17-01 | 6 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_operator_evidence.py -x` | Wave 0: created here (test_demo_probe_cases.py, test_demo_probe_evidence.py); others by 18-16-01 | green |
| 18-17-02 | 6 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cli.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cases.py -x` | Wave 0: created here (test_demo_probe_cli.py); others by 18-17-01 | green |
| 18-18-01 | 6 | EXEC-05,OPS-02 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_evidence.py tests/test_user_data_smoke_dry_run.py -x` | Wave 0: created by 18-16-01, 18-16-02 | green |
| 18-18-02 | 6 | EXEC-05,OPS-02 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-01-01 | green |
| 18-18-03 | 6 | EXEC-05,OPS-02 | blocking-human (manual) | inline check, see PLAN 18-18 Task 3 verify | n/a (decision or evidence record); a recorded postponement also passes | manual-only |
| 18-18-04 | 6 | EXEC-05,OPS-02 | record check | inline check, see PLAN 18-18 Task 4 verify | n/a; a recorded postponement also passes | manual-only |
| 18-23-01 | 7 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | green |
| 18-23-02 | 7 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | green |
| 18-23-03 | 7 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | green |
| 18-19-01 | 8 | EXEC-05 | record check | inline check, see PLAN 18-19 Task 1 verify | n/a; `transport: none` with the postponement reason also passes | manual-only |
| 18-19-02 | 8 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_userdata_direct_transport.py tests/test_userdata_adapter.py -x` | Wave 0: created here (test_userdata_direct_transport.py); others by 18-11-01 | n/a (skipped by design: transport sdk) |
| 18-19-03 | 8 | EXEC-05 | fake-driven | `uv run pytest -m "not docker" tests/test_user_data_smoke_cli.py tests/test_user_data_smoke_dry_run.py tests/test_user_data_smoke_evidence.py tests/test_demo_probe_cli.py tests/test_demo_probe_evidence.py -x` | Wave 0: created by 18-16-01, 18-16-02, 18-16-03, 18-17-01, 18-17-02 | green |
| 18-19-04 | 8 | EXEC-05 | blocking-human (manual) | inline check, see PLAN 18-19 Task 4 verify | n/a (decision or evidence record) | manual-only |
| 18-20-01 | 9 | EXEC-01,EXEC-02 | fake-driven | `uv run pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_demo_probe_cli.py -x` | Wave 0: created by 18-17-01, 18-17-02 | green |
| 18-20-02 | 9 | EXEC-01,EXEC-02 | blocking-human (manual) | inline check, see PLAN 18-20 Task 2 verify | n/a (decision or evidence record) | manual-only |
| 18-20-03 | 9 | EXEC-01,EXEC-02 | blocking-human (manual) | inline check, see PLAN 18-20 Task 3 verify | n/a (decision or evidence record); a recorded postponement also passes | manual-only |
| 18-20-04 | 9 | EXEC-01,EXEC-02 | record check | inline check, see PLAN 18-20 Task 4 verify | n/a; a recorded postponement also passes | manual-only |
| 18-21-01 | 10 | EXEC-01,EXEC-02,EXEC-05 | replay + fake-driven | `uv run pytest -m "not docker" tests/test_userdata_recorded_frames.py tests/test_userdata_parsers.py tests/test_userdata_events.py tests/test_userdata_replay.py tests/test_userdata_router.py tests/test_userdata_fixtures.py -x` | Wave 0: created here (test_userdata_recorded_frames.py); others by 18-03-03, 18-03-01, 18-15-03, 18-15-02, 18-24-01; skipped by design when no recorded frame exists | green |
| 18-21-02 | 10 | EXEC-01,EXEC-02,EXEC-05 | PostgreSQL integration | `uv run pytest -m "not docker" tests/test_fake_binance_semantics.py tests/test_exchange_errors.py tests/test_execution_manager.py tests/test_execution_exactly_once_pg.py tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_callback_redelivery_pg.py tests/test_intent_recovery.py tests/test_intent_recovery_pg.py -x -rs` | Wave 0: created here (test_fake_binance_semantics.py); others by 18-05-01 | green |
| 18-25-01 | 11 | EXEC-01,EXEC-02,EXEC-05 | doc structure | `uv run pytest -m "not docker" tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py -x` | Wave 0: created by 18-01-01 | green |
| 18-25-02 | 11 | EXEC-01,EXEC-02,EXEC-05 | doc structure | `uv run pytest -m "not docker" tests/test_decision_alignment_exchange.py tests/test_decision_alignment_bookkeeping.py tests/test_sources_phase18_section.py -x` | Wave 0: created by 18-01-01 | green |
| 18-25-03 | 11 | EXEC-01,EXEC-02,EXEC-05 | record check | inline check, see PLAN 18-25 Task 3 verify | n/a | manual-only |
| 18-26-01 | 11 | EXEC-02,EXEC-01 | record + characterization | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_exchange_error_rejections.py tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py tests/test_demo_probe_cases.py -x -rs` | Wave 0: created here (test_exchange_error_rejections.py) | green |
| 18-26-02 | 11 | EXEC-02,EXEC-01 | characterization + table | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_exchange_error_rejections.py tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py -x -rs` | exists | green |
| 18-26-03 | 11 | EXEC-02,EXEC-01 | phase gate + full suite (strict, PostgreSQL) | `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_exchange_error_rejections.py tests/test_exchange_errors.py -x -rs` | exists | green |
| 18-22-01 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | phase gate | `uv run pytest -m "not docker" tests/test_phase18_gate.py -x` | Wave 0: created here (test_phase18_gate.py) | green |
| 18-22-02 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | full suite (strict, PostgreSQL) | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" -q -rs` | exists | manual-only |
| 18-22-03 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | blocking-human (manual) | inline check, see PLAN 18-22 Task 3 verify | n/a (decision or evidence record) | manual-only |
| 18-22-04 | 12 | EXEC-01,EXEC-02,EXEC-05,OPS-02 | record check | inline check, see PLAN 18-22 Task 4 verify | n/a; a recorded deferral also passes | manual-only |

The rows are ordered by wave. Blocking-human tasks (7: 18-02-02, 18-03-02, 18-18-03, 18-19-04, 18-20-02, 18-20-03, 18-22-03) carry an automated record check of the user's decision or evidence file, not a test of the live behavior; record checks (7) read a file the previous task wrote.

### Named tests added by the 2026-10-16 plan revisions

Copied from the plans (the command of each task is in the map above). 18-02-01 and 18-02-03 check the 27-key list (Task 3 amends the table to 27 key rows and checks the record's 27 `limit` lines); 18-09-01 checks that the ratified file has exactly those 27 keys.

| Task ID | Named tests (as written in the plan) | Rule they prove |
|---------|--------------------------------------|-----------------|
| 18-05-02 | `test_ip_banned_without_retry_after_uses_418_fallback`, `test_rate_limited_without_retry_after_uses_429_fallback`, `test_valid_retry_after_is_honoured_for_both_statuses`, `test_cap_bounds_retry_after_and_both_fallbacks`, `test_rate_limit_decision_never_retries`, `test_rate_limit_decision_requires_each_keyword`, `test_rate_limit_decision_rejects_bool_zero_and_negative`, `test_rate_limit_decision_has_only_retry_and_wait_fields` | 418 and 429 fallbacks and cap; `retry` always False; `retry_eligible` True only for STATUS_UNKNOWN |
| 18-06-01 | `test_algo_status_table_as_recorded_2026_10_16`, `test_attach_behavior_unchanged_from_new_only_allow_list` | NEW ACTIVE; TRIGGERING, TRIGGERED, FINISHED, CANCELED UNKNOWN; REJECTED, EXPIRED TERMINAL_FAILED |
| 18-07-01 | `test_rate_limit_keys_map_to_distinct_fields` | 27 canonical keys; the 418, 429 and cap keys map to three distinct `RateLimitPolicy` fields |
| 18-10-02 | `test_gate_requires_policy_and_clock`, `test_418_without_retry_after_bans_for_418_fallback`, `test_429_without_retry_after_pauses_for_429_fallback`, `test_valid_retry_after_is_capped_for_ban_and_pause`, `test_ban_and_pause_refuse_with_distinct_classes_and_reasons`, `test_ban_takes_precedence_over_pause`, `test_end_times_only_extend`, `test_other_categories_change_nothing`, `test_only_time_lifts_a_restriction`, `test_refusal_message_has_no_url_or_key`, `test_cancel_429_fails_at_once_and_pauses_the_gate`, `test_pause_refuses_every_method_without_sending`, `test_ban_refuses_every_method_without_sending`, `test_two_adapters_share_one_gate`, `test_public_server_time_refused_while_gate_banned_or_paused`, `test_public_rate_limit_answer_restricts_shared_gate`, `test_restriction_expiry_sends_and_replays_nothing` | one process-wide gate: a 418 bans and a 429 pauses every REST call of every holder (public reader included); no 429 cancel retry; expiry proves nothing |
| 18-11-02 | `test_path_form_url_not_caught_by_shape_rule_alone`, `test_listen_key_registered_on_start_before_return`, `test_transport_registers_key_before_connect_logs`, `test_listen_key_port_single_call_site_and_no_retry` | listenKey registered before a `/private/ws/<listenKey>` URL can be logged; the port never retries |
| 18-12-02 | `test_probe_records_rate_limit_in_shared_gate`, `test_probe_refuses_when_another_holder_restricted_the_gate` | the probe adapter holds the shared gate |
| 18-13-02 | `test_signed_methods_never_retry_429_or_418`, `test_restriction_expiry_does_not_touch_drift_guard_or_entries`, `test_drift_time_source_shares_gate`, `test_protective_blocked_by_pause_or_ban_surfaces_unprotected_position` | no retry on 418 or 429 for any signed method; the drift time source is gated; a blocked protective order becomes ENTRY_WITHOUT_PROTECTIVE with SAFE_MODE |
| 18-14-02 | `test_listen_key_port_records_and_respects_shared_gate`, `test_keepalive_429_never_triggers_immediate_rekey_or_snapshot`, `test_keepalive_429_with_retry_after_waits_capped_value`, `test_pause_set_by_another_holder_delays_every_supervisor_rest_step`, `test_ban_on_listen_key_call_blocks_every_holder`, `test_request_resync_during_ban_sends_nothing`, `test_wait_end_does_not_restore_live` | the supervisor waits out a pause and stops on a ban before every REST step; the stream stays UNKNOWN until a snapshot |
| 18-15-02 | `test_trailing_stop_algo_update_pair_is_one_lifecycle_update`, `test_trailing_stop_terminal_failed_pair_emits_one_divergence`, `test_unknown_algo_pair_journals_one_anomaly`, `test_algo_status_change_is_not_deduplicated`, `test_exact_duplicate_algo_frame_is_idempotent` | the ALGO_UPDATE trailing-stop pair (`ia` false then true) is one lifecycle update |
| 18-16-02 | `test_preflight_refused_by_paused_gate` (plus the one-gate source test of the rig builders) | the smoke's preflight `server_time` is gated; one gate per run |
| 18-19-02 | `test_direct_transport_registers_key_before_url_is_built` | the direct transport uses the path form and registers the key first |

### Requirement-level mapping

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| EXEC-05 | stream events become fills and state hints with REST fallback; replay, reorder and duplicate stay idempotent; recorded and synthetic frames parse | unit + fake rig + replay + fixtures | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_userdata_parsers.py tests/test_userdata_fixtures.py tests/test_userdata_adapter.py tests/test_userdata_contract.py tests/test_userdata_supervisor.py tests/test_userdata_router.py tests/test_userdata_replay.py tests/test_userdata_rig.py -x` | Wave 0 (created by the tasks above) |
| EXEC-01 | algo status table drives attach and adoption (as recorded: only NEW is ACTIVE); placement is never retried; a protective order blocked by a 429 pause or a 418 ban surfaces as ENTRY_WITHOUT_PROTECTIVE with SAFE_MODE; the probe records the D055 facts | unit + fake rig | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_execution_attach.py tests/test_binance_usdm_error_routing.py tests/test_binance_usdm_signed_calls.py tests/test_binance_probe.py tests/test_demo_probe_cases.py -x` | partial (attach test exists) |
| EXEC-02 | not-found and rate-limit handling in probes and the sweeper; evidence source recorded; no call retried because of a 418 or 429; one shared gate turns a 418 into a REST ban and a 429 into a pause of every REST call of the process | unit + contract | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_sdk_error_mapping_contract.py tests/test_adapter_not_found_mapping.py tests/test_binance_ratelimit_gate.py tests/test_binance_usdm_error_routing.py tests/test_persistence_exit_evidence_pg.py tests/test_reconcile.py -x` | partial |
| OPS-02 | no secret, signature or listenKey in any output (including a `/private/ws/<listenKey>` URL); explicit environment; ratified limits only (the 27 canonical keys of `config/binance/binance-limits-v1.toml`) | unit | `uv run pytest -m "not docker" tests/test_binance_secret_redaction.py tests/test_binance_client_config.py tests/test_binance_limits.py tests/test_binance_limits_ratified_file.py tests/test_clock_drift.py tests/test_no_unratified_defaults.py tests/test_userdata_adapter.py -x` | Wave 0 (created by the tasks above) |

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
| O-18-01 ratification of safety numbers | OPS-02, EXEC-05 | owner-only (D061 H and I) | user fills the value column of the ratification table and records the decision file (done 2026-10-16: `decisions/18-DEC-O-18-01.md` with 27 `limit` lines, the four flagged classes UNKNOWN and the section "Amendment 2026-10-16 (user): 429 semantics"; plan 18-02 Task 3 amends the table to 27 rows and checks the record's shape) |
| Documentation re-read of the four event pages | EXEC-05 | this machine cannot fetch them | executor repeats the reads, updates the Phase 18 SOURCES section, records failures verbatim |
| Live Demo smoke (acceptance a to h in 18-RESEARCH.md) | EXEC-05, OPS-02 | needs Binance Demo keys and network | run the smoke script on the connected machine with Demo keys in the shell session; the user may instead record a postponement (a recorded skip) |
| Probe `--execute` (D-16 cases) | EXEC-01, EXEC-02 | needs Binance Demo and the user typing the confirmation phrase | run the probe script; cleanup leaves zero open orders, zero open algo orders, flat position; the user may instead record a postponement (a recorded skip) |
| Integration of `phase-18` with `develop` | EXEC-01, EXEC-02, EXEC-05, OPS-02 | a rebase rewrites history, so only the user performs it | plan 18-22 Task 3: the user integrates and records `decisions/18-DEC-INTEGRATION.md`, or defers |

---

## Validation Sign-Off

Left for the user at plan acceptance (the planner does not tick these):

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency within one test file per task
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

## Validation Audit 2026-10-19

Run after the Phase 18 code-review fixes (26 commits, `ef90072` to `6f73e5b`; report `18-REVIEW-FIX.md`). Full suite `pytest -m "not docker"` with the local PostgreSQL 17.11 reachable through `TEST_DATABASE_URL`: exit 0, no failure, no error. The only skips are environmental (symlinks, POSIX file modes, `shellcheck` not on PATH). The 14 PostgreSQL test files ran (about 295 tests, none skipped).

| Metric | Count |
|--------|-------|
| Per-task rows | 88 |
| Set to green (a test file exists and the suite is green) | 60 |
| Manual-only (decision, evidence or blocking-human record) | 16 |
| N/A, skipped by design (18-19-02: gate result `transport: sdk`; `tests/test_userdata_direct_transport.py` is never built; 18-19-03 and 18-19-04 have no pytest command and count as manual-only) | 1 |
| Rows whose Status already held a text outcome (kept) | 11 |
| Gaps found | 0 |
| Resolved / Escalated | 0 / 0 |

Not asserted by this audit: the manual-only items stay the owner's (`18-VERIFICATION.md` lists them), and the Approval line in the Sign-Off section is left for the owner to write. The seven review items skipped as owner decisions are recorded in the Phase 19 and Phase 20 notes.

