---
phase: 24-live-runtime-composition-demo
plan: 27
subsystem: live-composition
status: partial
tags: [composition, wiring-gate, run-admitted, d-04, d-05, d091, d092, phase-24]
requirements-addressed: [APRV-01, EXEC-01, EXEC-02, OPS-03]
requires: [24-14, 24-15, 24-16, 24-17, 24-19, 24-21, 24-23, 24-26, 24-34]
provides:
  - "src/live/wiring.py: LiveAssembly, build_wiring, CompleteLiveWiring, LiveStoreSet, build_pg_stores, check_wiring, LINK_* names, TASK_NAMES, WiringBroken, WiringIncomplete"
  - "src/live/wiring_parts.py: SignalContextBook, AdapterPositionsReader, ExecutorReservations, ExecutorPlanStore, make_reservation_registrar, LateBound, LiveBotProxy, make_kill_gate_sources (D092), alembic_revisions_reader, task_event_journal"
  - "src/live/runtime.py: production_run_live (the default runner of main), run_admitted, default_assemble, shutdown_in_order"
  - "PgExecutionStateStore.get_intent / restorable_entries / intent_for_client_id; PgTradingEntityStore.get_trade_plan_by_hash"
  - "LiveTelegramRunner(command_handlers=...), .handler, .service; ALLOWED_UPDATES = [callback_query, message]"
  - "build_reconcile(on_entry_resolved=...); SignalRequest.bar_close_price"
affects: [24-28, 24-29, 24-32, 25]
key-files:
  created:
    - src/live/wiring_parts.py
    - tests/support/live_wiring_rig.py
    - tests/test_live_wiring.py
    - tests/test_live_wiring_parts.py
    - tests/test_live_run_admitted.py
  modified:
    - src/live/wiring.py
    - src/live/runtime.py
    - src/live/telegram_runner.py
    - src/live/reconcile.py
    - src/live/signal_source.py
    - src/persistence/execution_state.py
    - src/persistence/entities.py
    - tests/test_phase22_gate.py
    - tests/test_live_config_refusal.py
key-decisions:
  - "Two-phase assembly: build_wiring builds everything that needs no SAFE_MODE controller; complete(safe_mode, enablement), reached at start step 4 (ENABLEMENT), builds the closer, coordinator, producer, service, stream, reconcile, runner, sender, health and scheduler. The startup ports reach those objects lazily (LateBound) because StartupPorts is built before step 4."
  - "check_wiring runs inside the ENABLEMENT step (a broken link raises WiringBroken, so the start holds with the links named) and again in run_admitted before the wait."
  - "D092 implemented exactly: the DEMO start port journals DEMO_KILL_GATE_RULE_APPLIED on every enable and returns WITHIN_BUDGET; the periodic kill-gate task source in DEMO returns WITHIN_BUDGET without a row (it can only move toward disabled); LIVE and TESTNET read only the persisted evaluated state, None keeps the enable refused."
  - "D091: REST_MAX_ERROR_RATE = Decimal('0.3') (3 of 10; the check fails when the window rate is STRICTLY above it), DB_WRITE_MAX_AGE = 60 s, passed to LiveHealthThresholds.from_limits."
  - "The legacy 6-field LiveWiring and build_execution_path stay (the shared rig and about 30 test modules use them); the complete value is CompleteLiveWiring."
plan_head_before: 5d80a2e1e257a85ba4af6b252da97f86b6f43586
plan_head_after: 72bf89b62263aaafc0b3db27c22d1401f5d2e504
commits: 2
actuals:
  tokens: 105000
  tasks: 3
  commits: 2
completed: 2026-11-01
---

# Phase 24 Plan 27: Live composition, wiring gate and run_admitted Summary

**PLAN PARTIAL.** The composition root, the D-05 wiring gate with a negative control per link, and the `run_admitted` runner with ordered shutdown exist and are tested on fakes at the edges. The end-to-end tracer through `build_wiring` (a CONFIRM placing one entry and a stream fill getting a REST-confirmed stop on the composed graph), the shared-rig migration and the StoreExecutor wrapping of the remaining inline synchronous store calls are NOT done; they are listed precisely below.

## What was built

### Task 1 (composition) - `src/live/wiring.py`, `src/live/wiring_parts.py`

`build_wiring(...)` returns a `LiveAssembly` holding, over one `StoreExecutor`: the PostgreSQL stores (`build_pg_stores`, `PgTradingEntityStore` with a journal, DEMO-scoped `PgShadowStores`), the alert bundle (`bundle.sink`, `safe_mode_observer`, `gate_alert`, `drain_once`, `requeue_at_start`), the exchange bundle (one `RestRateLimitGate`, the drift guard), `CommissionCache` (refreshed by a task), equity, bracket cache, day-risk service, the lot-filter source, the desk over `DemoDeskStores` and the reserving D028 save, the marks book and the observers. `complete(safe_mode, enablement)` builds `MarketEmergencyCloser(lot_filters=...)`, the liquidation watch (`CLOSE_POSITION`), `ProtectionCoordinator(restore_required=True, liquidation_watch=...)`, `LiveRiskInputProducer`, `ExecutionService` (inputs = the producer), `StreamPersistence`, `build_stream` (sinks: persistence writers, divergence queue; coordinator `fill_sink` through the fan-out), `build_reconcile` (resolver `on_resolved` = `coordinator.note_entry_resolved`), `OperatorCommands`, `LiveTelegramRunner` (the only confirm flow; commands registered; `message` polled), `ApprovalRequestSender` (`register_reservation` bound), the health producer and the scheduler. The twelve task specs are exactly: protection step (with the fill wake and `make_protection_step`), reconcile tick, drift re-measure, mark refresh, commission refresh, day-risk backfill, confirm-TTL sweep, alert drain, health tick (with the kill-gate check toward `disable()`), liveness stamp, scheduled cancel, signal-source pump; intervals come from `LiveCadences`.

`startup_ports(...)` binds `StartupPorts` to those objects: `alembic_revisions` (read-only, `alembic_revisions_reader`), `load_safe_mode`, `start_enablement`, `requeue_alerts` (reads `operational_alerts`, `requeue_at_start`), `expire_confirms` (`runner.expire_on_restart`), `health_verdict` (mark refresh, one Telegram probe, `health_tick_once`), `kill_gate_state` (D092), recovery ports (`restored_plans_builder`, `close_attempts_reader` over the new store reads).

### Task 2 (the D-05 gate) - `check_wiring`, `tests/test_live_wiring.py`

`check_wiring(wiring) -> list[str]` returns the broken links: approval sender (desk) and its pump task, bot runner with `handler.func is on_callback`, the service as the flow's `on_confirmed` target, producer feeding the service, reconcile loop with its sweeper, resolver bound to the coordinator, health task, kill-gate task, one REST gate across seven holders, drift guard, the one `JournalFirstAlertSink` on four holders, the market closer, `restore_required`, the liquidation watch, a durable SAFE_MODE controller, the exact task-name set and the registered operator commands. 35 tests; a negative control per link replaces exactly that link and asserts `check_wiring` names exactly it (sink replaced by a rehearsal-style class, coordinator without closer, adapter without guard, second gate, handler other than `on_callback`, missing scheduler task, and the rest). A volatile SAFE_MODE controller is refused earlier, by `build_reconcile` itself (asserted). An AST scan proves no module outside `src/live` constructs the service, coordinator, sink, gate, adapter or scheduler.

### Task 3 (runner) - `src/live/runtime.py`, `tests/test_live_run_admitted.py`

`main` now defaults to `production_run_live` -> `run_admitted(context)`: `default_assemble` (database URL from `DATABASE_URL_SYNC` or `DATABASE_URL`, `load_binance_limits`, the PTB `ApplicationBuilder`, a late-bound bot) -> `run_start_sequence` -> `check_wiring` -> wait for the stop (signal handlers installed in the main thread; an injected `wait_for_stop` in tests) -> `shutdown_in_order`: scheduler, bot, stream supervisor, stream fan-out writes, stream persistence, `ExecutionService.drain()`, `StoreExecutor.aclose()`; a failing step is logged by class name and the next still runs. A refused start prints its step, code and message (never a value) and `--hold-on-refusal` holds on it. Tests cover: start/stop, a refused start, the hold with the marker, a broken link refusing the start naming it, a raising sequence (class name only), the stop order, a placement in flight and a queued write completing before the close, and the liveness stamp (written each tick with the scheduler results, accepted by the `--liveness` rule).

### Hand-offs closed

| Hand-off | Where |
|---|---|
| 24-13 bundle.sink / safe_mode_observer / gate_alert / drain_once / requeue_at_start | `LiveAssembly.__init__`, `_build_complete`, `_requeue_alerts`, `alert_drain` task |
| 24-15 CommissionCache refresh task, ttl from params, margin = tick | `commission_refresh`, `LiveAssembly.__init__` |
| 24-14 / Phase 22 inv. 13 `register_reservation` | `make_reservation_registrar` (margin trio via `margin_for_reservation`); pins 13 and 14 of `tests/test_phase22_gate.py` now name `wiring_parts.py` / `wiring.py` |
| 24-17 runner.flow single flow | one flow per process (`build_execution_path` is not used by the composition) |
| 24-18 protection TaskSpec with wake and `make_protection_step`; drain order | `_specs`, `shutdown_in_order` |
| 24-19 intent lookup by client id; entities store with a journal | `PgExecutionStateStore.intent_for_client_id`; `build_pg_stores` |
| 24-20 lot filters -> closer, `restore_required=True`, `spill`, `on_enter` | `_build_complete` |
| 24-21 plan-expiry-by-hash adapter | `PgTradingEntityStore.get_trade_plan_by_hash`, `ExecutorPlanStore` |
| 24-22 observers, `LiveHealthThresholds` D091 | `REST_MAX_ERROR_RATE`, `DB_WRITE_MAX_AGE`, `rest_errors.wrap`, `db_writes.track`, `note_send_report` |
| 24-23 CommandHandler registration, `allowed_updates` with `message` | `LiveTelegramRunner(command_handlers=...)`, `ALLOWED_UPDATES` |
| 24-26 `restorable_entries` / `get_intent`, `restore_required`, startup ports | `PgExecutionStateStore`, `startup_ports` |
| 24-34 `on_resolved` | `build_reconcile(on_entry_resolved=coordinator.note_entry_resolved)` |

## Verification

- `uv run pytest -m "not docker"` (no `TEST_DATABASE_URL`, no PostgreSQL): tests/test_live_wiring.py (35), test_live_wiring_parts.py (20), test_live_run_admitted.py (13), test_live_tracer, test_live_stream_to_protection, test_live_reconcile_wiring, test_live_approval_sender, test_live_telegram_runner, test_live_operator_commands, test_live_health, test_live_ast_guards, test_live_config_refusal, test_live_runtime_cli, test_live_start_sequence, test_live_restart_rehydrate, test_live_enablement_wiring, test_live_alerts_wiring, test_live_exchange_wiring, test_live_risk_input_producer, test_phase18/19/20/22 gates, test_no_unratified_defaults, test_agents_md, test_domain_no_float, test_paper_shadow_isolation: all pass.
- `uv run ruff check` and `ruff format --check` on every touched file, `uv run mypy src` (289 files), `uv lock --check`, `git diff --exit-code -- pyproject.toml uv.lock`: clean.
- The wiring tests run with a guard that fails on any outbound connection or psycopg connect; the SQL engine is created and never connected.
- Every scheduler task body and the startup ports were exercised once on the fakes: they raise only the expected connection guard (database) or `GateNotRestored`; no wiring error.
- Not run: the full suite, any PostgreSQL test (forbidden for this run), the new `PgExecutionStateStore` reads against a database (their SQL is built and compiled for the PostgreSQL dialect in a test; semantics are unproven), any Demo or network call.
- Acceptance grep for constructions outside `src/live` found three reviewed exceptions, all `BinanceUsdmAdapter` in the data collection tools (`src/data/backfill_cli.py`, `src/data/collector.py`, `src/data/universe_freeze.py`); they are not the live process and are allow-listed in the test.

## Deviations from Plan

**1. [Scope] `make_live_rig` was NOT migrated to `build_wiring` and the tracer is not run through the composed graph.** About 30 existing test modules build on the 6-field `LiveWiring` and in-memory stores; migrating them is a separate pass. The new rig (`tests/support/live_wiring_rig.py`) builds the real composition over PostgreSQL store classes on an unconnected engine, so a CONFIRM-to-protected-position run on it needs a store-set of in-memory fakes that does not exist for reservations, day-risk, system-state, lot filters and pending actions. The path itself is proven by the existing tracer and stream tests on the same real manager, coordinator and router objects. Task 1's behaviour bullets 2 and 3 are therefore unmet.

**2. [Naming] The complete value is `CompleteLiveWiring`, not `LiveWiring`;** the legacy `LiveWiring` and `build_execution_path` remain for the same reason.

**3. [Rule 2/3] `SignalRequest.bar_close_price` added** (additive, default None, set to the mark price by `derive_request`). `SignalRequest.latest_closed_bar_close` is a time, but the producer and the invalidation rule need a price; without it every placement would refuse. For the Demo smoke the stand-in is the mark price the plan was derived from (a rehearsal input, not a market fact).

**4. [Rule 3] `LiveTelegramRunner` gained `command_handlers`, `.handler` and `.service`** (touches the 24-17 file as the 24-23 hand-off said); `build_reconcile` gained `on_entry_resolved`; `PgExecutionStateStore` and `PgTradingEntityStore` gained the reads above.

**5. [Pin] Phase 22 gate invariants 13 and 14 were updated on purpose** (they said a composition would appear): `register_request` and `required_margin` are allowed in `src/live/wiring_parts.py`, `liquidation_watch=` in `src/live/wiring.py`.

**6. [Test] `test_an_admitted_start_without_a_composed_runner_fails_closed` became `test_an_admitted_start_without_a_database_url_fails_closed`** (the runner is composed now; without a URL it refuses naming the variables).

## What remains (precisely)

1. **Tracer through `build_wiring`** (Task 1 behaviour 2 and 3): an in-memory `LiveStoreSet` (reservations, day risk, system state, snapshots, lot filters, pending actions, shadow stores) so a Demo request, APPROVE, CONFIRM and a synthetic fill frame can run on the composed graph; then migrate `make_live_rig` and the 30 modules (or keep both rigs and say so).
2. **StoreExecutor wrapping of the remaining inline synchronous store calls.** Done: reservation reads, plan expiry, stream writes, journal record, SAFE_MODE load, enablement start, alembic read, kill-gate read, runner confirm book via `run_sync`. Still inline on the loop: `ApprovalDesk.issue` and the sender's `register_reservation` and `entities.transition_*`, `ConfirmFlow.handle_cancel` and `finalize_expired`'s expire step (24-17 notes), the coordinator, closer, service and reconcile loop's `PgExecutionStateStore` / `PgJournalStore` / `PgPendingActionStore` calls, `LiveDayRiskService`'s `PgDayRiskStore` calls, `expire_on_restart`, the recovery builders (startup only).
3. **PostgreSQL proof** of `restorable_entries`, `get_intent`, `intent_for_client_id` and `get_trade_plan_by_hash` (needs `TEST_DATABASE_URL`; the orchestrator runs the `_pg` suite).
4. **No feeder for the running process's signal source.** `DemoSmokeSignalSource` is queue-based; `scripts/demo_rehearsal.py` builds its own objects, so nothing injects a request into `python -m src.live.runtime`. The pump and the sender are wired and gated, but a Demo run needs an owner-chosen injection path (plan 24-28/29 or Phase 25).
5. **`restorable_entries()` is unbounded** (ACKED rows never leave ACKED); bounding it needs an owner number (the rebuild marks ended plans FLAT from the journal).
6. **`fills_reader` is None** (no REST fills-by-order read exists on the adapter); the router's own FILL_TOTAL_MISMATCH divergence is the only trace. **`status_hint_sink` and `algo_sink` are counting no-ops** (no consumer exists; REST is the truth).
7. **LIVE mode** is not buildable by this plan: `build_exchange` is called without a `LiveEnablementState`, so a LIVE start fails closed at assembly (the human enable step is Phase 25/26). A LIVE start without an evaluated persisted kill-gate state is refused by D092 as required.
8. Docs not touched (not in this plan's files): RUNBOOK 21.3 still says the gate alert hook is not wired; `/safemode_exit` and `/confirm` should be named in the SAFE_MODE exit section.
9. **REST error bound wording:** D091 says "3 failed calls of the last 10"; the existing check fails when the window rate is strictly above the bound, so 3 of 10 passes and 4 of 10 fails. Confirm that is the intended edge (changing it is one constant plus the `>` in `check_rest_error_rate`, which is outside this plan).

## Known Stubs

- `_EvidenceSink` (status hint and algo route sinks) drops the items it counts: intentional, no consumer exists (see remaining 6).
- No other stub flows to a UI or an order path.

## Threat Flags

None new beyond the plan's register. T-24-83 (dropped link): `check_wiring` at start and in CI with a negative control per link. T-24-84 (two gates or an unguarded adapter): identity and behaviour assertions (a 418 on the one gate blocks the public mark-price call before the SDK). T-24-85 (placement or write cut off at shutdown): ordered shutdown, tested with a placement task and a queued write in flight. T-24-SC: `git diff --exit-code -- pyproject.toml uv.lock` clean. New surface: none (no endpoint or auth path; the database URL is read from the environment by name and never echoed).

## Self-Check: PASSED

- FOUND: src/live/wiring.py, src/live/wiring_parts.py, src/live/runtime.py, tests/test_live_wiring.py, tests/test_live_wiring_parts.py, tests/test_live_run_admitted.py, tests/support/live_wiring_rig.py
- FOUND commits ec1cb3cc, 72bf89b6 (ancestors of HEAD)
