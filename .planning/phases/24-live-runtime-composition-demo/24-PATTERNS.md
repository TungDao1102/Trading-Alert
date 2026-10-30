# Phase 24: Live Runtime Composition + Demo Rehearsal - Pattern Map

**Mapped:** 2026-10-30
**Files analyzed:** 27 new/modified (names of new `src/live/` modules follow the RESEARCH "Recommended project structure"; layout is Claude's discretion)
**Analogs found:** 25 / 27 (all analog paths verified git-tracked; no `.gsd/` mirror paths used)

Line numbers refer to the tree at HEAD `bac55faa`. Excerpts are short on purpose: read the analog for the full body.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/live/runtime.py` (CLI, `main`, `run_admitted`, hold/refuse) | entry point | request-response + event-driven | `src/paper/runtime.py` (`build_parser` 211, `_hold`/`_refuse` 279-332, `main` 1458, `run_admitted` 1200) | exact |
| `src/live/config.py` (mode, env parse, first-install flag) | config | transform | `src/paper/runtime.py` `main` env handling 1474-1547 + `refuse_trade_capable_env` | role-match |
| `src/live/wiring.py` (`LiveWiring`, `build_wiring`) | composition root | batch (construct) | `src/paper/runtime.py` `LoopWiring` 589-622 + RESEARCH "Gate + adapter + drift guard + stream assembly" (from `scripts/user_data_smoke.py:805-847`) | role-match |
| `src/live/startup.py` (D-08 ordered steps) | service | request-response | `src/reconcile/startup.py` `run_startup_recovery` 200+ (`_Run`, STEP_* constants) | role-match |
| `src/live/scheduler.py` | utility | event-driven (timers) | `tests/support/virtual_time.py` + `src/paper/runtime.py` `_LiveLoop` watchdog; RESEARCH Pattern 2 | partial |
| `src/live/execution_service.py` (`on_confirmed` bridge) | service | event-driven to async | `scripts/demo_rehearsal.py` `build_live_context` 2014 + `run_order_scenario` 2772 (sole existing caller of `execute_approved_plan`) | role-match |
| `src/live/approval_sender.py` | service | CRUD + request-response | `scripts/demo_rehearsal.py` `issue_approval` 2155 / `issue_and_send` 2225; `src/execution/approval_desk.py` `ApprovalDesk` 268 | role-match |
| `src/live/risk_inputs.py`, `commission.py` | service | request-response (REST reads) | `src/execution/live_risk_inputs.py` (`build_live_risk_inputs`), `account_equity.py`, `day_risk_service.py`, `bracket_cache.py` | role-match |
| `src/live/stream.py` (supervisor, fill fan-out, glue Protocols) | service | streaming | `tests/test_protection_router_rig.py` 60-97 (router + `fill_sink`), `src/adapters/binance_userdata_router.py`, `binance_userdata_supervisor.py` | role-match |
| `src/live/health.py`, `liveness.py` | service | request-response | `src/ops/health.py` (`ALL_CHECK_NAMES` 48-70, verdict 185-192, DEGRADED 606), `src/paper/runtime.py` `_healthcheck` 1341 / `_liveness` 1429, `src/paper/liveness.py` | role-match |
| `src/live/operator.py` (Telegram SAFE_MODE exit) | controller | request-response | `src/adapters/telegram_callbacks.py` `on_callback` 1022 / `build_application` 1341; `src/reconcile/safe_mode.py` `exit_safe_mode` 569-608 | role-match |
| `src/live/signal_source.py` | service | event-driven | `scripts/demo_rehearsal.py` `derive_plan` 1705 | role-match |
| `src/ops/store_executor.py` (+ paper `expire_due` move) | utility | request-response (thread offload) | RESEARCH Pattern 3; call site `src/paper/shadow_runtime.py:838,1320` | no code analog |
| `src/db/alembic/versions/0015_*.py` | migration | CRUD | `src/db/alembic/versions/0014_decided_excl_expired.py`, `0013_approval_money.py` | exact |
| `src/persistence/entities.py` (`update_position_snapshot`, event-time guard) | model/store | CRUD | same file, `PgTradingEntityStore` `update_order_exchange_state`, `transition_position` (433-660) | exact |
| `tests/support/live_rig.py` | test support | request-response | `tests/support/protection_doubles.py` `make_rig` 241-320, `ProtectionRig` 194 | exact |
| `tests/test_live_*.py` (wiring, replay/restart, stream-to-stop, drift guard) | test | event-driven | `tests/test_protection_router_rig.py`; `tests/test_phase23_gate.py` | exact |
| `tests/test_phase24_gate.py` | test (gate) | static | `tests/test_phase23_gate.py` (module inventory, `REQUIREMENT_TESTS`, head check 373) | exact |
| AST guard for `src/live/` (Q5, no wall clock) | test | static | `tests/test_binance_usdm_source_guard.py` 296-335; `tests/support/ast_guards.py` `wall_clock_calls` 154 | exact |
| `tests/test_phase18_gate.py` invariant 2 amendment | test | static | same file 445-455 | exact |
| `tests/test_deploy_compose.py` placeholder test amendment | test | static | same file 250-260 | exact |
| `docker-compose.yml` `live` service, env split | config | n/a | same file `live` placeholder 161-173 and `x-app` anchor | exact |
| `Dockerfile` (copy `config/execution`, `config/binance`, revision stamp) | config | n/a | same file COPY lines; `tests/test_deploy_images.py` `RUNTIME_READ_PATHS` 266-273 | exact |
| `deploy/heartbeat.sh` `--target live` (+ systemd units) | script | request-response | same file `--target paper`; `tests/test_deploy_heartbeat.py` stubs | exact |
| `scripts/demo_rehearsal.py` (drive composed process) | script | request-response | itself (`EvidenceRecorder` 500, `RunJournal` 1137, `run_order_scenario` 2772, `_fill_flow` 2651) | exact |
| `tests/test_phase23_gate.py` invariant 6 head `0014` -> `0015` | test | static | same file 373-380 | exact |
| `docs/DECISIONS.md` rows D089+, GLOSSARY 9.3 (G3-005) | docs | n/a | existing rows D086-D088 | exact |
| `src/ops/health.py` DEGRADED policy rewrite (D056) | service | request-response | itself, 606 comment "unchanged policy" | exact |

## Pattern Assignments

### `src/live/runtime.py` (entry point)

**Analog:** `src/paper/runtime.py`

**Parser verbs to mirror** (211-260): `--hold-on-refusal`, `--healthcheck`, `--liveness`, `--pinned-state`. Drop `--pin-epoch`.
```python
parser = argparse.ArgumentParser(prog="python -m src.paper.runtime", description="...")
parser.add_argument("--hold-on-refusal", action="store_true", help=...)
parser.add_argument("--healthcheck", action="store_true", help=...)
parser.add_argument("--liveness", action="store_true", help=...)
```
**Hold/refuse** (279-332): `_hold` writes `held_marker.write_marker(marker_dir, code=int(code), refusal=refusal)`, falls back to exiting non-zero if the marker cannot be written, `wait_for_stop()`, removes the marker in `finally`. `_refuse` prints to stderr, logs via `structlog`, returns `int(code)` unless `hold`. Reuse `src/paper/held_marker.py` directly (do not import `src.paper.runtime`; D-01 forbids it). Copy `wait_for_stop_signal` (263-272) shape.
**Main shape** (1458-1527): all seams are keyword-only params (`environ`, `wait_for_stop`, `clock`, `run_loop`, `wiring`) so tests inject; `liveness`/`healthcheck` short-circuit first; env refusal before anything else:
```python
trade_names = refuse_trade_capable_env(env)
if trade_names:
    return refuse(ExitCode.TRADE_KEY_REFUSED, "trade-capable variable present: " + ", ".join(trade_names))
```
For live, invert: refuse when the OTHER mode's credential names are present, via `binance_client.load_api_credentials(environ, spec=spec, repo_root=REPO_ROOT, refuse_if_present=(other_spec,))` (RESEARCH code example).
**Run function:** `RuntimeContext` frozen dataclass (189-208) carries `clock`, `env`, `started_at_utc`, `liveness_dir`; `run_admitted(context, wiring: LoopWiring | None = None)` (1200). Mirror as `run_admitted(context, wiring: LiveWiring)`.

### `src/live/wiring.py` (composition root)

**Analog:** `LoopWiring` (`src/paper/runtime.py` 589-622): frozen dataclass, every field optional test seam. For live, per D-04/D-05 the fields are REQUIRED (no `None` defaults) so the D-05 gate can assert presence; fakes enter only at the edges (SDK client, PTB bot, clock).
**Assembly order** (RESEARCH 582-603, from `scripts/user_data_smoke.py:805-847,1760-1777`):
```python
gate = RestRateLimitGate(policy=limits.signed.rate_limit, clock=clock, state_store=gate_store, on_alert=alert_hook)
drift_guard = ClockDriftGuard(limits=limits.drift)
adapter = BinanceUsdmAdapter(bundle.client, rest_gate=gate, signed_call_policy=limits.signed,
                             drift_guard=drift_guard, clock=clock, on_clock_skew=drift_guard.note_clock_skew_error)
supervisor = UserDataSupervisor(adapter=stream_adapter, limits=limits.stream, clock=clock, sleep=sleep,
                                rest_gate=gate, snapshot_provider=snapshot, on_event=router_feed, ...)
```
**Protection/closer assembly** (analog `tests/support/protection_doubles.py` 269-296, same kwargs as production): `MarketEmergencyCloser(adapter, journal, safe_mode_controller, alert_sink, clock, limits, pending_actions, spill)` then `ProtectionCoordinator(adapter, intent_store, journal, safe_mode_controller, alert_sink, emergency_closer, limits, clock, pending_actions, spill, liquidation_watch)`. Production: real `JournalFirstAlertSink` (`src/ops/alerts.py:341`), real closer, `liquidation_watch=LiquidationWatch(brackets, fee_rates, limits, policy)` with `CLOSE_POSITION` (D085 O-4, conflicts with CONTEXT D-24; planner must flag).
**Reconcile:** `ReconcileLoop(adapter, gate, safe_mode (must be durable; ctor raises otherwise), intent_store, protection, sweeper, alerts, journal, limits, unknown_entries, feeds, stream, lot_filters, pending_actions, risk_reducer, entry_good_till, feed_clock_skew)` (`src/reconcile/loop.py:418`). Tick interval must be below `max_unprotected_ms`.

### `src/live/startup.py` (D-08 sequence)

**Analog:** `src/reconcile/startup.py::run_startup_recovery` (200+): fixed order, a `_Run` recorder with `run.ok(STEP_...)` per step, a controller loaded first (`controller = safe_mode_load()`), `now_utc` must be tz-aware (raises `ValueError`), all ports injected as keyword-only parameters. Model `startup.py` as an ordered tuple of named step coroutines, each journaled; step 7 CALLS `run_startup_recovery(...)` with `restored_plans_builder`, `close_attempts_reader` (glue to write). `SafeModeController.load` starts IN SAFE_MODE on any store failure (`safe_mode.py:292-344`), so failures stay fail-closed.

### `src/live/scheduler.py`

**Analog:** RESEARCH Pattern 2 sketch (`TaskSpec`, `Scheduler._loop`: catch `Exception` except `CancelledError`, record class name only). Test style: `tests/test_protection_router_rig.py` 48-57 forbids `asyncio.sleep`; use `tests/support/virtual_time.py::VirtualTime`. Guard: `wall_clock_calls(path) == []` (`tests/support/ast_guards.py:154`; also catches `loop.time()`).

### `src/live/execution_service.py` (`on_confirmed` bridge)

**Analog:** `scripts/demo_rehearsal.py` `build_live_context` (2014-2127) and `run_order_scenario` (2772-2884) for the exact keyword set of `execute_approved_plan` (manager.py:540-558; `risk_kwargs["now_utc"]` must equal `now_utc`, manager.py:712-716; `gate_kwargs` is exactly `open_algo_count`, `planned_leg_count`, `positions_reconciled`). Copy the `LivePlacementContext` construction and the margin-guard refusal (`MARGIN_GUARD_NOT_COMPOSED`) logic, replacing the rehearsal sink with the real one.
**Bridge:** hook type `OnConfirmedFn = Callable[[Approval, TradePlan, datetime], None]` (`src/approval/confirm_core.py:199`), invoked at 965-983 inside try/except that sets `hand_off_failed`. Follow RESEARCH Pattern 4: hook only schedules (`create_task` + strong-ref set + done-callback journaling; `call_soon_threadsafe` if run on a worker thread). Needs new `ApprovalDesk` accessor for the raw approve token (`approval_desk.py` ~211-228, 574).
**Q5:** exactly one `execute_approved_plan` call, outside any loop or retry; never call `place_entry`/`place_algo_protective`/`place_market_close` under `src/live/`.

### `src/live/approval_sender.py`

**Analog:** `scripts/demo_rehearsal.py::issue_approval` 2155 and `issue_and_send` 2225 (desk issue then send); ids derive from `(trade_plan_id, action)` (`approval_desk.py:235-236,376-380`) so DEMO needs its own Signal/TradePlan ids (RESEARCH P-8). Hosting rules: second-plan-per-symbol refusal, D028 chain, Phase 21 reservation in the approval transaction, money block (Phase 23 D-13). Telegram path only through `on_callback` with `authorized_user_ids` (required keyword-only, `telegram_callbacks.py:1022-1035`).

### `src/live/stream.py` (supervisor + router + glue)

**Analog:** `tests/test_protection_router_rig.py` 60-97: real `UserDataRouter` via `make_router(lookup=..., journal=..., sinks=..., clock=..., overrides={"fill_sink": rig.coordinator.fill_sink})`, events wrapped as `TrustedEvent(outcome=parse_stream_message(frame, observed_at_utc=received), received_at_utc=..., connection_epoch=1, after_gap=...)`. Production composes ONE `fill_sink` fan-out (RESEARCH Pattern 5: coordinator sink, protection `wake`, equity invalidate, day-risk ingest, liquidation check task; a member failure must not skip others). The router is synchronous end to end (P-4): `fills_fallback` must return `()` immediately and schedule the async REST read. `OrderLookup.known_order/known_algo` should read `execution_intents` rows (carry `client_order_id`/`algo_client_id`), not Order rows.
**Amend:** `tests/test_phase18_gate.py::test_invariant_2_no_src_module_imports_the_supervisor` (445-455): allow `src/live/stream.py` explicitly.

### `src/live/risk_inputs.py` / `commission.py`

**Analog:** `src/execution/live_risk_inputs.py::build_live_risk_inputs` (pure, called by the producer), `account_equity.py` (`LiveEquitySource`), `day_risk_service.py`, `bracket_cache.py`, `symbol_config_guard.py`, `margin_guard.py`. Producer returns complete inputs or a refusal reason; every stale or missing input is NO_TRADE. Fakes: `tests/support/account_fakes.py`, `bracket_fakes.py`, `day_risk_fakes.py`, `margin_guard_fakes.py`, `config_guard_fakes.py`, `phase22_fixtures.py`. All REST holders take the one shared `RestRateLimitGate`.

### `src/live/health.py` / `liveness.py`

**Analog:** `src/ops/health.py` (10 named checks `ALL_CHECK_NAMES` 48-70; PASS verdict needs exactly one non-FAIL result per name 185-192; `enable()` needs `reason_code == "OK"`, enablement.py:254-272) and `src/paper/runtime.py::_healthcheck` 1341-1428 / `_liveness` 1429-1457 (reads stamp and held marker, opens no network or DB client). `--healthcheck` must print `sys.version` plus a build-time revision stamp, NOT `read_code_version` (C-9).

### `src/ops/store_executor.py`

**No code analog.** Use RESEARCH Pattern 3 verbatim (single-thread `ThreadPoolExecutor` for writes, `asyncio.to_thread` for reads). Location must be outside `src/execution` and `src/live` (isolation closure test `tests/test_paper_shadow_isolation.py:30-55`). Paper change: `src/paper/shadow_runtime.py:838` and `:1320-1322` (`self._confirm.expire_due(now)`) move behind it; Phase 16 tests pin behavior.

### Migration `src/db/alembic/versions/0015_*.py`

**Analog:** `0014_decided_excl_expired.py`: hand-written, imports no project module, docstring cites finding and decision, then
```python
import sqlalchemy as sa
from alembic import op
revision: str = "0015_<slug>"
down_revision = "0014_decided_excl_expired"
branch_labels = None
depends_on = None
```
with `upgrade()` and a guarded `downgrade()` that raises `RuntimeError` naming a count when data would be lost. Must update `tests/test_phase23_gate.py::test_invariant_6` (373-380, `alembic_head_revision()`), and any other head pin (grep `0014_decided_excl_expired` in tests).

### `tests/support/live_rig.py`

**Analog:** `tests/support/protection_doubles.py::make_rig` (241-320): async factory returning a frozen `ProtectionRig` dataclass, `VirtualTime` clock, `BinanceSemanticsFakeAdapter(now_utc=clock.now(), enforce_flat_stop_rejection=True)`, `InMemoryExecutionIntentStore`, `RecordingJournal`, `RecordingAlerts`, optional real closer; file docstring states "TEST_ONLY numbers, no production code imports this module". Extend rather than fork; `BinanceSemanticsFakeAdapter` needs the Wave-0 gaps (lagging `NEW` after cancel, D-34).

### `tests/test_live_*.py`

**Analog:** `tests/test_protection_router_rig.py` (autouse fixture making `asyncio.sleep` fail 48-57; route a synthetic frame from `tests/support/userdata_frames.py::order_trade_update_frame`, then `await rig.coordinator.step()`). Replay/restart tests assert zero or one `place_entry` call on the fake.

### `tests/test_phase24_gate.py` and `src/live` AST guards

**Analog:** `tests/test_phase23_gate.py`: module inventory test (97), parametrized purity invariant using `float_constructor_calls`, `forbidden_imports`, `wall_clock_calls` (103), `REQUIREMENT_TESTS` resolved with `ast` (never imported) and `_test_function_names` (522-544), docs checks. Q5 rule: extend `placement_retry_constructs` style (`tests/test_binance_usdm_source_guard.py` 296-335) with a call-name scan over `src/live/**` and negative-control snippets (the file already tests the guard against a seeded `for ... tenacity` snippet).

### Deploy: `docker-compose.yml`, `Dockerfile`, `deploy/heartbeat.sh`

**Compose analog:** `live` placeholder (161-173): `<<: *app`, `profiles: ["live"]`, `restart: "no"`, `healthcheck: disable: true`. Replace command with `python -m src.live.runtime --hold-on-refusal`, add `healthcheck` calling `--healthcheck`, keep `restart: "no"` (O-2). Copy the paper service's `depends_on: db-upgrade: condition: service_completed_successfully` and `volumes` style from the neighbouring services. Per-service `env_file` allow-list (D-29). Amend `tests/test_deploy_compose.py::test_placeholders_fail_fast_naming_the_owning_phase` (250-260), `test_deploy_images.py` `RUNTIME_READ_PATHS`, `test_paper_runtime_compose.py`, cutover tests.
**Heartbeat analog:** `deploy/heartbeat.sh` `--target paper` branch (probe via compose exec of `--liveness`, ping separate URL by stdin `--set-url`); tests copy `tests/test_deploy_heartbeat.py` stubs (`docker`, `curl`, `systemctl` first on PATH, FAKE sentinel URL asserted absent from output). Probe line shape: `docker compose exec -T collector /app/.venv/bin/python -m src.data.collector --healthcheck`.

### `scripts/demo_rehearsal.py`

**Analog:** itself. Keep `EvidenceRecorder` (500), `RunJournal` (1137), `GuardedAdapter` (654, Demo-host guard), `--execute` confirm (`_confirm_execute` 1116). Replace hand-stepping (`_drive_protection` 2595, `build_live_context` 2014, `enablement` at ~2827) with calls through the composed `LiveWiring`; delete the `RehearsalAlertSink` use (1972; the wiring test rejects it).

## Shared Patterns

### Injected clock, no wall clock in pure modules
**Source:** `tests/support/ast_guards.py::wall_clock_calls` 154; `tests/support/virtual_time.py::VirtualTime`. **Apply to:** `src/live/scheduler.py`, `startup.py`, `risk_inputs.py`, `execution_service.py`; edge modules (`runtime.py`) may read the clock like `_utc_now` (`src/paper/runtime.py:275`).

### Fail closed, refuse by named reason code
**Source:** `ExecutionLimitsNotConfigured` / `limits.unset_keys()` in `scripts/demo_rehearsal.py:1950-1964` (message names keys, never values). **Apply to:** `main()` refusal when a required `NOT_CONFIGURED` key remains (D-12).

### Secret-free logging
**Source:** `structlog.get_logger().error("paper runtime refused", exit_code=..., reason=...)` (`runtime.py:329`); exception class names only in scheduler records. **Apply to:** every `src/live/` module; never log env values, tokens, URLs.

### Single REST gate instance
**Source:** `RestRateLimitGate` construction (above). **Apply to:** adapter, public data, listen-key port, supervisor, probe adapter, risk-input producer, bracket and commission readers; test asserts one `id()`.

### Module header and style
`from __future__ import annotations`, absolute `src.*` imports, mypy strict, ruff 100, Decimal only on risk path, `uv run` for every command.

### Test gates to amend (not to fight)
`test_phase18_gate.py` inv. 2 (445) and inv. 5 (`len(GUARDED_NAMES) == 62`, line 484, changes if a limit key is added); `test_paper_shadow_isolation.py` (StoreExecutor placement); `test_deploy_compose.py` 250; `test_deploy_images.py` 266; `test_phase23_gate.py` 373.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `src/ops/store_executor.py` | utility | thread offload | No `to_thread`/executor seam exists; use RESEARCH Pattern 3 |
| `src/live/scheduler.py` | utility | timers | Only the paper watchdog and test virtual time resemble it; use RESEARCH Pattern 2 |
| Glue Protocol impls (`OrderLookup`, `StreamDivergenceSource`, `FeedSource`, `EntryGoodTillSource`, `RiskReducer`, `position_verifier`, `PrefetchFn`, `restored_plans_builder`, `close_attempts_reader`) | adapters | mixed | Protocols exist with only test doubles (`tests/support/stream_sinks.py`, `reconcile_doubles.py`, `reconcile_rig.py`); copy the Protocol signatures from the declaring module and the doubles' semantics |

## Metadata

**Analog search scope:** `src/paper`, `src/execution`, `src/reconcile`, `src/ops`, `src/adapters`, `src/db/alembic`, `tests/support`, `tests/test_phase18/23_gate.py`, deploy files, `scripts/demo_rehearsal.py`.
**Files read this pass:** runtime.py (selected ranges), protection_doubles.py, test_protection_router_rig.py, test_phase23_gate.py (parts), 0014 migration, startup.py, loop.py (docstring), compose, heartbeat test and script heads, plus RESEARCH.md 1-200, 441-540, 578-630.
**Pattern extraction date:** 2026-10-30
