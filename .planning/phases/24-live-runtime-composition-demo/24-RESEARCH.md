# Phase 24: Live Runtime Composition + Demo Rehearsal - Research

**Researched:** 2026-10-30
**Domain:** asyncio process composition of existing library-level seams (execution, protection, reconcile, Telegram approval, Binance Demo adapters, Docker Compose, heartbeat)
**Confidence:** MEDIUM-HIGH. In-repo seam facts are HIGH (opened and read this session). Binance and Telegram facts are MEDIUM (official pages read through a fetch tool that renders only some pages; see "Official-doc facts"). Nothing here was run against Binance or Telegram (Demo runs are owner-only).

<user_constraints>
## User Constraints (from CONTEXT.md)

Source: `.planning/phases/24-live-runtime-composition-demo/24-CONTEXT.md` (gathered 2026-10-30 with `--auto`; every decision is the recommended default and the owner may override it; items marked OWNER-OPEN must not be given a number by the planner).

### Locked Decisions

All decisions below are the recommended option chosen in `--auto` mode. Every Binance and Telegram fact the plans rely on is re-read by the researcher from the current official pages, not taken from this file or memory. No limit value, interval or threshold is invented: keys that are `NOT_CONFIGURED` in `config/execution/execution-limits-v1.toml` stay so until the owner sets them (see Owner-open items).

#### Process topology and entry point (criterion 4, D042)
- **D-01:** One live process, `python -m src.live.runtime` (new package `src/live/`), runs a single asyncio event loop with these tasks: Telegram bot runner, user-data stream supervisor + router, protection coordinator stepper, reconcile loop, sweeper, health scheduler, clock-drift re-measure, live risk-input refresh. It replaces the `live` placeholder service in `docker-compose.yml` (profile `live`, restart policy `unless-stopped` only after the owner confirms the Demo mode flag; `restart: "no"` stays until then). The paper/SHADOW runtime (`src/paper/runtime.py`) and the collector stay separate processes; the live process never imports `src.paper.runtime`. — **Reversibility:** costly — the process boundary fixes the compose service, the heartbeat probe and the env allow-list; splitting later means moving state across processes.
- **D-02:** The runtime has an explicit mode value `DEMO` or `LIVE` read from configuration, never inferred from the base URL alone. Phase 24 builds and runs only `DEMO`. `LIVE` is constructible only through `LiveEnablementController`; a `LIVE` mode with `LIVE_ORDERS_DISABLED` refuses to start. The mode is journaled at startup and shown in every operator message. The paper runtime's rule is mirrored: the live process refuses to start if the credential names for the other mode are present (`BINANCE_DEMO_*` vs `BINANCE_LIVE_*`). — **Reversibility:** reversible — a validated config field and a start-up check.
- **D-03:** CLI shape mirrors `src/paper/runtime.py` (`--healthcheck`, `--liveness`, `--hold-on-refusal`) so the compose probe, the heartbeat and the runbook drills use the same verbs. A refusal at start holds (does not crash-loop) and is visible to the heartbeat as unhealthy. — **Reversibility:** reversible.

#### Composition root structure and wiring tests (criterion 1, F-201, F-956)
- **D-04:** A single composition module builds every object from explicit constructor arguments (clock, stores, adapter, gate, sinks, limits) and returns one `LiveWiring` value; `main()` only reads env, calls it, and runs `run_admitted`. No module outside `src/live/` constructs a live adapter, a coordinator, a sink or a scheduler. The pure layers (`src/core`, `src/risk`, `src/domain`) import nothing from `src/live/`. — **Reversibility:** costly — every later composition test and the runbook refer to this seam.
- **D-05:** A wiring test (the Phase 24 gate) fails the build when any link named in ROADMAP criterion 1 has no production caller: approval request sender, bot runner, execution service, reconcile, sweeper, health scheduler, risk-input producer, kill-gate event → `enable()`. The test inspects the built `LiveWiring` (types and presence), not source text, and a second AST guard keeps the Q5 rule: no retry wrapper around `place_entry`, `place_algo_protective` or `place_market_close` anywhere under `src/live/` (existing guards in `tests/test_execution_manager.py` and `tests/test_binance_usdm_source_guard.py` stay green and are extended to the new package). — **Reversibility:** reversible — tests.
- **D-06:** Clock-drift guard (24-NOTES item 1): the composition builds `ClockDriftGuard` from the ratified `drift.*` limits, passes it with the clock to `BinanceUsdmAdapter`, and schedules `drift.periodic_remeasure_interval_seconds`. Acceptance tests: the built adapter has a non-None guard; a never-measured guard blocks `place_entry` before any SDK call; a composition passing `None` fails a test. — **Reversibility:** reversible.
- **D-07:** Alert path (24-NOTES item 5): the real `JournalFirstAlertSink` (Phase 20) with the Phase 23 formatters and `TelegramAlertSender.drain()` is passed to `SafeModeController(on_enter=SafeModeAlertObserver(sink))`, `LivePlacementContext.alert_sink`, the protection coordinator, the REST gate `on_alert`, and the daily-state alert producers (`emit_daily_state_alert`). The rehearsal sink is rejected by the wiring test. The real `EmergencyCloser` is passed to the coordinator. — **Reversibility:** reversible.

#### Startup order, recovery and rehydrate (criterion 2 restart, G4-029)
- **D-08:** Start sequence, each step fail-closed (a failure holds the process in SAFE_MODE with entries blocked and monitoring running; nothing places an order until the sequence completes): (1) validate env and mode, refuse mixed credentials; (2) REST gate: run `FileGateStateStore.initialize` on the first install only (explicit flag, never silently), then load the persisted gate state; (3) Alembic head check (read-only, never `create_all`); (4) load SAFE_MODE and system state from the store (durable, D-14 of Phase 20) and the constraint snapshots; (5) clock-drift measure; (6) exchange info and lot-filter refresh; (7) `run_startup_recovery` (plan 20-19) which rebuilds the coordinator and closer and calls `resolve_unresolved_intents` (an acknowledged ENTRY with a rejected or absent STOP_LOSS intent is resolved by the 20-10 UNKNOWN-entry protocol; a probe "not found" never closes an entry as REJECTED, D080); (8) one full reconcile pass; (9) only then start the user-data stream, the bot runner and the schedulers. — **Reversibility:** costly — the order is the safety argument and drills pin it.
- **D-09:** Restart mid-flow (criterion 3): outstanding confirms expire with reason `RUNTIME_RESTART` (Phase 23 D-09); an APPROVED-but-not-confirmed plan stays approved until its expiry and needs a fresh CONFIRM; an entry already sent with an unknown result is UNKNOWN + SAFE_MODE; a resting entry and its `RestingEntry` registry record are rebuilt from the store. A replayed APPROVE, CONFIRM or CANCEL callback after restart answers from the stored decision and changes nothing. — **Reversibility:** reversible.
- **D-10:** Positions table, fills ledger and `Order` rows with `update_position_snapshot` and the exchange event-time column (G4-043, 20-DEFERRED D-13, D-29) are built here as the persistence the stream feeds: monotonic updates keyed by exchange event time, one Alembic migration, evidence rows kept as today. The D-01a reconcile bound check stays a bound check; the exact signed-quantity compare becomes possible and is added only if the owner asks (OWNER-OPEN O-5). — **Reversibility:** costly — a migration and a new table family other phases will read.

#### Schedulers and cadence (criterion 1; T-06)
- **D-11:** One small scheduler primitive (named task, injected clock and sleep, bounded jitter-free cadence read from limits, per-task last-run and last-error recorded to the journal, a task exception never kills the loop but raises the matching health result) drives: protection coordinator step, reconcile loop tick, sweeper, health checks, drift re-measure, bracket/commission/lot-filter refresh, scheduled cancel of unfilled entries at plan expiry. The primitive contains no wall clock call (AST guard). — **Reversibility:** reversible.
- **D-12:** Cadence values (reconcile interval, stale-feed threshold, WS-silence threshold, equity age, bracket age, protection step interval) are read from `execution-limits` / registry keys that are `NOT_CONFIGURED` today. A required key left `NOT_CONFIGURED` makes `main()` refuse to start in `DEMO` unless the owner supplies a value (OWNER-OPEN O-1). The plan lists every such key and the owner supplies the numbers in one checkpoint; nothing is defaulted from memory. — **Reversibility:** reversible — config values.
- **D-13:** Scheduled cancel of an unfilled entry at plan expiry (20-DEFERRED) is a scheduler task that cancels only with zero fills on the exchange (REST read first) and routes anything else to the coordinator; it follows the WR-07/G2-026 rule that protective legs are never cancelled while a fill may exist. The second-plan-per-symbol refusal and the D028 approval chain are enforced at the approval request sender, not in the scheduler. — **Reversibility:** reversible.

#### User-data stream to protection, fills and risk (criterion 2 fill via stream, 24-NOTES item 4)
- **D-14:** The Phase 18 router is the only consumer of the user-data stream. Its handlers are registered by the composition root: order/fill events → `ProtectionRegistry` and coordinator input (a fill leads to a REST-confirmed stop without any manual call, tested with the Binance-semantics fake exchange); fills and `ACCOUNT_UPDATE` → `LiveEquitySource` invalidation and the daily-loss service (Phase 21 stream path); listen-key keepalive and reconnect stay in the supervisor. The stream is evidence and a trigger, REST is the truth (Phase 21 D-01 pattern); a gap or silence beyond the (OWNER-OPEN) threshold raises the stale-stream health result and SAFE_MODE per Phase 20. — **Reversibility:** costly — handler registration order and event shapes are pinned by Phase 18 and Phase 20 tests.
- **D-15:** Every REST holder inside the live process takes the one shared `RestRateLimitGate` (24-NOTES item 3): the signed adapter, public market data, listen-key port, probe adapter, supervisor, the live risk-input producer, bracket and commission readers. A test constructs the process and asserts one gate instance; a 418 from any holder blocks the rest. The data jobs, the paper runtime and the two scripts stay outside by design (different processes) and are recorded in `tests/test_phase18_gate.py` as such. The supervisor's `_await_rest_allowed` wiring to `GateRestriction.remaining_seconds` and the D083 -1003 ban-end parsing are built here; the clock-margin key stays `NOT_CONFIGURED` (D083 condition, OWNER-OPEN O-1). — **Reversibility:** reversible.
- **D-16:** The direct `/private` URL form (24-NOTES item 2) is not changed here: the SDK stays the transport. The Demo smoke records the connection URL form once for Phase 25. — **Reversibility:** reversible.

#### Telegram runner and the approval path (criterion 1 and 3, APRV-01, D041, P23-R1)
- **D-17:** The runner composes the Telegram path only through `on_callback` (the user-id gate lives there); `dispatch_callback` is never called with `authorized_user_ids` omitted, and a wiring test fails if the runner's handler is anything else. `on_confirmed` of the shared confirm core (Phase 23 D-09) is the single seam connected to `execute_approved_plan` via the `ExecutionManager`; no `src.execution` import enters the confirm core. Pre-placement checks at CONFIRM use the Phase 23 `confirm_recheck` callable fed fresh REST/mark inputs. — **Reversibility:** reversible — the seam was designed for this.
- **D-18:** The approval request sender is the one place that creates the approval card for DEMO: it runs the second-plan-per-symbol refusal, the D028 chain, risk reservation (Phase 21, atomic in the approval transaction) and stores the money block with the approval (Phase 23 D-13). `notify` failures never auto-approve (APRV-02). — **Reversibility:** reversible.
- **D-19:** P23-R1 / SHADOW money block: this phase stores a money block with SHADOW approvals and renders it in the SHADOW alert, deliberately changing the SHADOW text pins. Coordinate first: read `.planning/phases/16-paper-runtime-composition/` soak evidence; if a Phase 16 soak is in progress or its evidence pins the SHADOW text, the change ships behind a new text version with the old pins kept, and the planner raises it as an owner checkpoint (OWNER-OPEN O-6) before editing. — **Reversibility:** costly — SHADOW text pins and soak evidence.
- **D-20:** Replay and restart safety (criterion 3) is tested at two levels: fakes (replayed APPROVE/CONFIRM/CANCEL, a restart between APPROVE and CONFIRM, a restart between CONFIRM and the `place_entry` result, two concurrent CONFIRMs on two connections) with an assertion of exactly zero or one `place_entry` call; and on Demo (owner-run) with recorded client order ids. The unknown-chat/other-user rejection check (G2-014) is an owner live check that needs a second Telegram account. — **Reversibility:** reversible.

#### Live risk-input producer (criterion 1, G3-008, G2-042)
- **D-21:** One producer assembles, per plan, from REST truth: the symbol constraint snapshot (Phase 22 `SymbolConfigGuard` margin type, leverage, `isAutoAddMargin`, brackets via `BracketCache`), equity (`LiveEquitySource`), daily-loss state (`LiveDayRiskService`), open positions including resting and approved plans (Phase 21 reservation), open algo order count against the 200 headroom, and per-symbol commission rates. It calls the pure `build_live_risk_inputs` and returns either a complete input or a refusal reason; any missing or stale input is NO_TRADE (fail closed). Backtest/paper parity tests from Phases 21 and 22 stay green. — **Reversibility:** costly — the producer's output type is read by the gates, the approval card and the liquidation watch.
- **D-22:** Commission wiring (G3-008, G3-014): per-symbol maker and taker rates come from the official commission-rate endpoint through a refresh task and cache, fed to `resolve_live_cost_rates`; a missing, stale or negative maker rate fails closed (Phase 12 IN-01), and the `assert`-based invariants (IN-05) become explicit raises. The researcher re-reads the official page (MEDIUM confidence) and the Demo behaviour is recorded by the owner run. — **Reversibility:** reversible.
- **D-23:** G2-042: the `realizedPnl` vs commission semantics are verified against the current Binance docs and one Demo fill, the citation is recorded, and `LIVE_NET_PNL_SEMANTICS_VERIFIED` is set only by a code change that names the evidence file; if the Demo sample is ambiguous the flag stays False and live R stays INCOMPLETE (no guess). Setting the flag needs the owner's DECISIONS row (OWNER-OPEN O-4). The Phase 22 flag `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` is handled the same way. — **Reversibility:** reversible.
- **D-24:** Post-fill liquidation watch (Phase 22) is activated by the user-data fill handler. The behaviour after a failed post-fill check (close or alert) is OWNER-OPEN O-3; until decided the default is alert + SAFE_MODE, no automatic close. — **Reversibility:** reversible.

#### Database access on the event loop (G4-040, P16R-03)
- **D-25:** Decision recorded in the plan and in `docs/DECISIONS.md` (new row, assistant proposes, owner ratifies): the sync PostgreSQL stores stay sync; the live process wraps every store call that runs on the event loop in `asyncio.to_thread` through one `StoreExecutor` seam, with a bounded single worker for write calls that need ordering (the ledger-lock rule). `ShadowConfirm.expire_due` on the loop (P16R-03) is moved behind the same seam in the paper runtime in the same plan, with the Phase 16 behaviour pinned by its existing tests. An async pool is rejected for now (new dependency, no measured need). — **Reversibility:** costly — the seam is used by every live store call.

#### Health, DEGRADED, mark-price gate and enablement (D056, D058, kill-gate)
- **D-26:** Health producers are built: each long-running task reports a `HealthCheckResult` (feed freshness, user-data stream state, REST error rate, reconcile drift, db writes, telegram delivery, unprotected positions, orphaned orders). D056: a producer for DEGRADED and an explicit mode are designed here with Phase 26: in `LIVE` a DEGRADED state cannot enable any order-capable capability and blocks new entries once enabled; in `DEMO` the process may continue DEGRADED only with an explicit `DEMO` mode flag that journals the health state and can never switch to `LIVE`. The `health.py` "unchanged policy" comment is replaced and `tests` pin both rows. — **Reversibility:** costly — changes a documented policy other tests pin.
- **D-27:** D058: the mark-price source (stream with REST fallback) has a freshness bound (OWNER-OPEN O-1); a missing or stale price refuses entry and refuses `enable()`, and a stale price while enabled is an invalid state that moves to SAFE_MODE. — **Reversibility:** reversible.
- **D-28:** Kill-gate event → `enable()`: the analytics kill-gate verdict (`src/analytics`) is the only automated trigger that may call `LiveEnablementController` toward disable; enabling is never automatic — it needs an operator action with an `operator_id` on the allow-list. Operator authentication (20-DEFERRED D-15) is resolved by reusing the Phase 23 authorized user ids for Telegram commands; ssh remains the access control for CLI controls. Demo mode needs no enable() for placement beyond the DEMO mode flag; the controller is still composed and exercised in the smoke. — **Reversibility:** reversible.

#### Deployment, heartbeat, credentials (criterion 4; WR-06, T-02, 16-50, G3-033)
- **D-29:** WR-06: the shared `env_file` is split per service with an allow-list (`live` gets `BINANCE_DEMO_*` / `BINANCE_LIVE_*`, Telegram and DB values only; collector and paper get none of the Binance names), with the cutover test and drills re-run, before any real `BINANCE_LIVE_API_*` key enters `.env`; WR-05 stays as implemented (D062); the D064 CR-01 replacement is implemented before the first bootstrap and real backup. — **Reversibility:** costly — compose, deploy scripts and the cutover test all pin the layout.
- **D-30:** The healthchecks.io heartbeat (16-50, Phase 16 decision O-12) is extended so one sender covers every long-running process: collector, paper (when running), live. Each process exposes `--healthcheck`; the heartbeat posts only when all required probes pass, and the live probe checks the process liveness stamp plus the latest scheduler results. The interval and grace remain OWNER-OPEN (O-1/O-12). Heartbeat URLs go in by stdin only. — **Reversibility:** reversible.
- **D-31:** OPS-04: `--healthcheck` output and the health payload include the runtime Python version and the application git revision (`src/adapters/code_version.py`). — **Reversibility:** reversible.
- **D-32:** VPS and Demo key: building the VPS with `deploy/bootstrap.sh`, executing RUNBOOK sections 13 and 17 "real host" rows, the systemd backup timer firing, one real `migrate.sh`, and IP-whitelisting the Demo key to the VPS address are owner-run steps. The plan provides the checklist and evidence template; the assistant never runs host commands or reads `.env`. — **Reversibility:** reversible.

#### Demo rehearsal (criterion 2, 5)
- **D-33:** The end-to-end smoke extends `scripts/demo_rehearsal.py` so it drives the composed process instead of stepping the coordinator by hand: signal → approve → confirm → GTD LIMIT entry (no entry-time stop, D079) → fill seen on the user-data stream → REST-confirmed stop → TP1/TP2 (D-21 makes `snapshot_is_valid_for_live` hold with real data) → reconcile clean → SAFE_MODE drill (enter, verify entries blocked, operator exit) → restart and rehydrate → replayed callbacks. Output records Demo order ids and client order ids; it is run by the owner with `--execute`. The blocked 09-04 rehearsal is closed by this run. — **Reversibility:** reversible.
- **D-34:** Criterion 5 findings are carried as test and review items: a `closePosition=true` stop before a fill is -4509 (already the D079 model); `query_algo_order_by_client` still reports `NEW` for about a second after cancel, so reconciler and sweeper must treat "cancel sent, open list empty" as success (a test with a fake that lags); the `entry_price` float noise (`84816.40000000001`) is checked at the SDK boundary and converted through the string/Decimal path with a test; the adapter's market-order/close helper question is already answered by `place_market_close` (Phase 19). — **Reversibility:** reversible.

#### Inherited-item triage
- **D-35:** Folded into plans: G4-029, G4-034 (journal evidence source on exits from UNKNOWN), G4-043, G2-019 (duplicate client ids and skipped sweeper cancels surfaced), T-04, T-05 (alerts for duplicate execution attempt, rejected protective action, daily-loss WARNING), T-06 (values via D-12), G3-005 (promote `NO_FILL` and `HEALTH_CHECK_FAILED`, update GLOSSARY 9.3 and the Phase 21 gate invariant in the same change), G2-035 (triage each of IN-01/05/06/07 to fix or a won't-fix note), P20-GATE-WIRING, P20-DEFERRED, G4-040/P16R-03 (D-25), the coordinator notification of a `RECONCILED_ABSENT` entry (20-DEFERRED). G3-033 and G2-014 are owner checks. T-02 WR-06 half is D-29; the disk-encryption half stays with Phase 26. — **Reversibility:** reversible.

### Claude's Discretion
- Package layout inside `src/live/` and module names; the scheduler primitive's API; whether risk inputs are one class or several; the migration split for D-10; golden-text details of new formatters (following Phase 23 style); how the smoke script is parameterised.
- Test composition: which fakes to extend (the Binance-semantics fake exchange is the default), provided the Q5 and drift-guard acceptance tests exist.

### Owner-open items (do not implement with a number until the owner decides)
- **O-1:** Values for every required `NOT_CONFIGURED` key: reconcile cadence, stale-feed and WS-silence thresholds, equity age (`account.max_equity_age_ms`), mark-price freshness, bracket age and margin headroom, clock margin for D083, heartbeat interval and grace, protection step cadence. Phase 22 O-1 (target leverage), O-2 (liquidation buffer) remain as recorded in `22-CONTEXT.md`.
- **O-2:** Enabling `restart: unless-stopped` for the live service (default `restart: "no"` until the first clean Demo run).
- **O-3:** Close or alert after a failed post-fill liquidation check (Phase 22 O-4); default alert + SAFE_MODE.
- **O-4:** DECISIONS rows to set `LIVE_NET_PNL_SEMANTICS_VERIFIED` and `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED`.
- **O-5:** Whether to add an exact signed-quantity position compare once Order and fill rows exist (D-01a is accepted as a bound check).
- **O-6:** SHADOW money-block text change if a Phase 16 soak is running or pins the text (D-19).
- **O-7:** Ratify the `docs/DECISIONS.md` row proposed for G4-040 (D-25) and the D056 DEGRADED mode (D-26).

### Deferred Ideas (OUT OF SCOPE)
- Direct (non-SDK) `/private` user-data transport — only after Phase 25 captures the URL form.
- Failure-scenario campaign, multi-week Demo soak — Phase 25.
- Enablement gate, real backups, CI, mainnet read-only check, canary, disk encryption — Phase 26.
- USDC / configurable quote asset — Phase 27.
- Async PostgreSQL pool — only if the `to_thread` seam measures as insufficient.
- Local-time display in Telegram (owner preference) — later.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (REQUIREMENTS.md) | Research Support |
|----|-------------|------------------|
| APRV-01 | User receives Telegram alerts (SIMULATE/APPROVE/SKIP) carrying symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, and reason codes | Seam inventory B (ApprovalDesk.issue/send, ConfirmFlow, `on_callback`); finding C-1 (`on_confirmed` bridge), C-4 (signal source); money block stored by the desk |
| EXEC-01 | Execution manager places LIMIT-zone entries and Algo-Order protective exits, supports both position modes and partial-fill protective sizing (Pending: no Demo proof) | `execute_approved_plan` per-call inputs (seam inventory A), `LivePlacementContext`, live risk-input producer (D-21), enablement gate finding C-2, Demo smoke (D-33) |
| EXEC-02 | Reconciliation loop compares local state against open normal orders, open algo orders, positions, sweeps orphans, forces SAFE_MODE on divergence (Pending: not composed) | Seam inventory D (`ReconcileLoop`, `OrphanSweeper`, `run_startup_recovery`), glue classes (finding C-5), stream divergence source, feed source |
| EXEC-03 | Deterministic client/algo order identifiers prevent duplicate entry orders across retries, restarts, replayed events (marked complete; Phase 24 proves it through the composed process) | replay/restart test design (Validation Architecture), `_one_placement_per_symbol`, intent store `get_entry` replay, Q5 AST guard |
| OPS-02 | Live credentials use no-withdrawal keys, IP allowlisting, off-source secret storage, structured secret-free logging with health checks | per-service env allow-list (finding C-8), credential loader `load_api_credentials(... refuse_if_present=...)`, redaction, owner attestation items |
| OPS-03 | Restart sequence loads config, validates time, reconciles orders and positions, reconnects streams, verifies no duplicate action, resumes only when state is consistent | start sequence (D-08) mapped to existing functions; gate restore requirement for SAFE_MODE exit (finding C-6) |
| OPS-04 | Health and diagnostic output includes the runtime Python version and the application git revision | finding C-9 (no `.git`/git binary in the image: build-arg stamp needed), `--healthcheck` payload design |
</phase_requirements>

## Summary

Phase 24 is a composition phase: every safety-critical piece already exists as a tested library (`ProtectionCoordinator`, `ReconcileLoop`, `OrphanSweeper`, `UserDataSupervisor` + `UserDataRouter`, `ApprovalDesk` + `ConfirmFlow` + the confirm core, `LiveEquitySource`, `LiveDayRiskService`, `MarginGuard`, `JournalFirstAlertSink`, `RestRateLimitGate`, `ClockDriftGuard`) and, apart from `scripts/demo_rehearsal.py` (which hand-steps them) and tests, **nothing in `src` constructs any of them** [VERIFIED: `git grep` of each constructor over `src` and `scripts` this session; only `scripts/demo_rehearsal.py:2827` builds a `LiveEnablementController`, and no `src` module builds `ReconcileLoop`, `OrphanSweeper`, `ClockDriftGuard`, `JournalFirstAlertSink`, `TelegramAlertSender`, `SafeModeAlertObserver`, `LiveEquitySource`, `LiveDayRiskService`, `BracketCache`, `SymbolConfigGuard`, `MarginGuard`, `LiquidationWatch`]. The work is therefore (a) one new package `src/live/` with a composition root, a scheduler primitive and about a dozen small glue classes that implement the Protocols the libraries declare but nobody implements, (b) a handful of small changes to existing code where the seams do not fit (the sync `on_confirmed` hook, the enablement gate, health probes, Dockerfile/compose/heartbeat), and (c) tests plus owner-run Demo evidence.

The research found **eleven plan-shaping findings (section "Critical findings")** that the CONTEXT does not mention or states differently. The three that most change the plan: (1) `on_confirmed` is a synchronous `None`-returning hook, while placement needs an async `execute_approved_plan` call that also needs the raw approval token the hook does not carry; (2) the manager's enablement gate refuses every placement while `LIVE_ORDERS_DISABLED`, so CONTEXT D-28 ("Demo needs no enable()") cannot hold without a code change, and `enable()` needs a complete ten-probe passing health verdict that includes market-feed probes belonging to other processes; (3) the CONTEXT topology has **no producer of Signal/TradePlan** for the live process, so "signal → approve" has no source in production. Several CONTEXT premises are also stale against recorded owner decisions (D084, D085, D086: equity age, bracket age, headroom already set; `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` already True; post-fill liquidation policy already `CLOSE_POSITION`; `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False until the Phase 26 canary).

Fourteen required keys of `config/execution/execution-limits-v1.toml` plus one alert-only key are still `NOT_CONFIGURED`; with any of them unset `ProtectionCoordinator`, `ReconcileLoop`, `JournalFirstAlertSink` and the manager refuse, so the owner checkpoint of D-12 blocks the first Demo run, not only the cadence. The D083 clock-margin key and a protection-step cadence key do not exist yet; this research recommends reusing `reconcile.tick_interval_ms` for the stepper (no new owner number) and an optional, alert-only-style key for D083.

**Primary recommendation:** Build `src/live/` as thin glue over the existing libraries, in this order: seam/glue + `StoreExecutor` + scheduler primitive, then the start sequence and `LiveWiring` with the D-05 wiring gate, then the approval/execution path (`ApprovalRequestSender`, `ExecutionService`, `on_confirmed` bridge), then stream to protection, then risk-input producer and commission refresh, then health/DEGRADED, then compose/Dockerfile/heartbeat/env split, then the smoke script and owner checklists. Raise four owner checkpoints early (limits values; signal source; enablement semantics in DEMO; Telegram bot token and database per mode), because they decide the shape of everything after them.

## Critical findings (read first; each changes a plan)

**C-1. `on_confirmed` is a sync hook with no token; placement is async and needs the approval token.**
- `OnConfirmedFn = Callable[[Approval, TradePlan, datetime], None]` [VERIFIED: src/approval/confirm_core.py:199]. The core calls it as `hook(*item)` after releasing its lock, catches `Exception`, logs the class, sets `entry.hand_off_failed = True` [VERIFIED: src/approval/confirm_core.py:965-983]. `ConfirmFlow._confirm` calls the core synchronously on the event-loop thread: `result = self._book.handle_confirm(` [VERIFIED: src/execution/confirm_flow.py:400].
- `execute_approved_plan` is `async` and takes `callback`, `approval`, `authorized_chat_id`, `expiry_utc`, `approval_strategy_version`, `approval_parameter_set_id`, `approval_parameter_set_hash`, `now_utc`, `adapter`, `risk_kwargs`, `safe_mode_controller`, `journal`, `enablement`, `gate_kwargs`, `intent_store`, `live_context` (all keyword-only, no defaults) [VERIFIED: src/execution/manager.py:540-558]. Gate 0 verifies `callback.raw_token` against `approval.approval_token_hash` [VERIFIED: src/approval/binding.py:179-180 `if not verify_token_hash(callback.raw_token, approval.approval_token_hash)`]. The raw approve token lives only in the desk's memory (`_Request.approve_token`, "restart loses it") and is exposed only inside the `resolve(short_id)` context dict [VERIFIED: src/execution/approval_desk.py:211-228, 574].
- Consequences for the plan: a new `ExecutionService` (in `src/live/`) is the `on_confirmed` target. The hook must only schedule: `loop.create_task(self._place(...))`, keep a strong reference in a task set, and attach a done-callback that journals any exception (the core never sees a task failure, so `hand_off_failed` will not be set for it; the final card text for such a case must come from the stored entry intent, which `ConfirmFlow` already does). If D-25 moves `handle_confirm` into a worker thread, the hook runs on that thread and must use `loop.call_soon_threadsafe` (a bare `create_task` from a non-loop thread is unsafe). A small public accessor on `ApprovalDesk` (approval id to approve raw token) must be added; `ConfirmFlow._short_by_approval` is private.
- The per-call inputs (`risk_kwargs`: `trade_plan`, `candidate_position_side`, `account_state`, `constraint_snapshot`, `open_positions`, `daily_loss_quote`, `now_utc`, `ttl`, `cost_rates`, `min_stop_distance_rate`, `max_cost_to_risk`, `minimum_risk_utilization_after_rounding`, `parameter_set`; `gate_kwargs`: exactly `open_algo_count`, `planned_leg_count`, `positions_reconciled`; `LivePlacementContext`) are all assembled per plan by the service from the D-21 producer. `risk_kwargs["now_utc"]` must equal `now_utc` or the manager raises [VERIFIED: src/execution/manager.py:712-716].

**C-2. The manager refuses all placement while `LIVE_ORDERS_DISABLED`; D-28 as written cannot work.**
- Gate 2 of `execute_approved_plan`: `enablement_verdict = enablement.guard_placement(plan_hash=approval.trade_plan_id)` then NO_TRADE `DISABLED` [VERIFIED: src/execution/manager.py:809-817]. `LiveEnablementController.__init__` sets `self._disabled: bool = True` [VERIFIED: src/execution/enablement.py:112]. The only way to flip it is `enable(operator_id, now_utc, health_verdict, kill_gate_state)`, which requires `health_verdict.is_no_trade is False` and `reason_code == "OK"` (a complete set of ten non-FAIL probe results) and a `KillGateState` that is not `INSUFFICIENT_EDGE` [VERIFIED: src/execution/enablement.py:254-272]. `scripts/demo_rehearsal.py:2836-2841` does exactly this in-process with `KillGateState.WITHIN_BUDGET` and disables afterwards.
- Recommendation (needs owner/planner confirmation, Open Question OQ-3): keep the manager unchanged; in `DEMO` the start sequence ends with an in-process `enable(operator_id=<fixed DEMO operator id>, ...)` after a passing health verdict, journaled with the mode, never reachable in `LIVE` mode (LIVE keeps the human operator action of D-28). Persist `state_snapshot()` under `SystemStateKey.LIVE_ENABLEMENT = "LIVE_ENABLEMENT"` [VERIFIED: src/domain/enums.py:307-309] (the key exists, nothing writes it: src/persistence/system_state.py docstring "Nothing here wires SAFE_MODE or enablement to the store"), but on restart start DISABLED and re-enable only after the sequence passes (never trust a persisted "enabled").

**C-3. Health: `enable()` needs all ten probes; three of them describe a market feed the live process does not own.**
- `ALL_CHECK_NAMES` has ten names including `market_feed_freshness`, `last_closed_candle_time`, `ws_connection_state` ("FAIL when the market-data WS connection is not connected") [VERIFIED: src/ops/health.py:48-70, 354-369]. A PASS `HealthVerdict` requires exactly one non-FAIL result per name [VERIFIED: src/ops/health.py:185-192]. `STATUS_DEGRADED` is accepted ("`STATUS_DEGRADED` does not block (unchanged policy)", health.py:606) and nothing under `src` produces it.
- The live process has no market WS and no candle feed (the only mark price source in `src` is REST `GET /fapi/v1/premiumIndex`: `MarkPriceReading` with `exchange_time_utc` [VERIFIED: src/adapters/binance_public.py:139-148]). The plan must define what each of the three probes means for the live process (recommended: `market_feed_freshness` = age of the REST mark price of tracked symbols; `ws_connection_state` = the user-data private connection; `last_closed_candle_time` = DEGRADED/not-applicable, which is why the D056 DEGRADED mode must be designed before `enable()` can be wired) and who counts REST errors for `rest_error_rate` (no counter exists; the gate does not count).

**C-4. The CONTEXT topology has no signal/plan source.**
- D-01 lists the tasks of the live process; none produces a `Signal` + `TradePlan`. In the paper process signals come from `BarPipeline` over the pinned epoch and the SHADOW chain; D040 says SHADOW holds no order adapter, DEMO places. `scripts/demo_rehearsal.py` derives a synthetic plan (`derive_plan`, setup type `"DEMO_REHEARSAL"`). Nothing in ROADMAP Phases 24 to 26 assigns a strategy-driven producer for the live process.
- Also: `ApprovalDesk` approval ids are `"apv-" + sha256({"trade_plan_id", "action"})[:32]` and the short id is derived from `(signal_id, trade_plan_id)` [VERIFIED: src/execution/approval_desk.py:235-236, 376-380], so the same plan cannot be issued in both SHADOW and DEMO against one database (primary-key collision). A DEMO request needs its own Signal/TradePlan ids.
- Recommendation (OQ-2): define a `SignalSource` Protocol in `src/live/`; Phase 24 ships the Demo-smoke injector (the rehearsal's plan derivation moved behind the Protocol) and leaves strategy-driven production as an explicit owner decision with a named owner phase. Do not silently import `src.paper.*` pipeline pieces into the live process.

**C-5. About a dozen Protocols have no production implementation (the real glue list).**
`OrderLookup.known_order/known_algo` for the router (no code calls `PgTradingEntityStore.insert_order`; `git grep insert_order -- src` finds only its definition; the recommended source is NOT Order rows but the `execution_intents` rows, which carry `client_order_id` / `algo_client_id` and are written before each send: see P-4), `StreamDivergenceSource` (`drain`, `halted_reason`), `FeedSource.read_feed`, `EntryGoodTillSource` (plan hash to `goodTillDate`), `RiskReducer` (awaitable the loop calls when a pending action is open), the sweeper `position_verifier`, `ConfirmInputs` prefetch (`PrefetchFn`) and the shared pre-placement reads, `restored_plans_builder` and `close_attempts_reader` for `run_startup_recovery`, the `fills_fallback` callable, the scheduled-cancel driver, the alert-queue requeue read, health producers. Note `fills_fallback` is typed `Callable[[str], Sequence[FillEvent]]` (synchronous) and is called inside the synchronous `route` [VERIFIED: src/adapters/binance_userdata_router.py:458, 640], but REST fill reads are async: the glue must return an empty sequence immediately and schedule the async REST read separately (the router already raises a divergence on a fill-total mismatch), never block the loop and never run a nested loop.

**C-6. SAFE_MODE exit cannot run from a separate CLI; the REST gate must be built durable.**
- `exit_safe_mode` takes closures over live state (`local_intent_fn`, `readiness`, `gate_status`, `stream_state`) and refuses unless the gate's recovery status is accepted (`RESTORED_DURABLE`) and the stream state is exactly `"LIVE"` [VERIFIED: src/reconcile/safe_mode.py:569-608]. A gate without a `state_store` reports `LEGACY_IN_MEMORY`, which "no SAFE_MODE exit accepts" [VERIFIED: src/adapters/binance_ratelimit_gate.py:35-36, 374-385]. So the composition must build the gate with a `FileGateStateStore`, run `initialize` only on an explicit first-install flag, then `restore()` once before any REST call.
- The D-33 "operator exit" therefore needs an in-process command channel: the natural one is a Telegram command on the same authorized-user gate with the two-step confirm (owner confirmed this direction on 2026-10-23, 20-DEFERRED "Telegram operator commands"), but CONTEXT has no decision that builds those commands. Decide the minimal command set in the plan (OQ-5).

**C-7. One bot token = one getUpdates consumer; one database = one approval mode.**
- `BOT_TOKEN_RULE = "separate-bot: exactly one getUpdates consumer per bot token (16-DEC-Q-L, RUNBOOK 20.3)"` [VERIFIED: src/paper/shadow_runtime.py:152-154]. The live process polls too, so it needs its own bot token (per-service env, D-29). PTB raises `telegram.error.Conflict` "when a long poll or webhook conflicts with another one" [VERIFIED: installed python-telegram-bot 22.8, telegram/error.py:253-254].
- `ConfirmStores.list_approved_approvals` returns "Every APPROVED approval of the database, of any mode (review WR-06) ... so one database must serve ONE mode until a mode-scoped reader exists" [VERIFIED: src/approval/confirm_core.py:213-216]. The compose stack has one `postgres` service; SHADOW (paper) and DEMO (live) sharing it would let the DEMO orphan sweep act on SHADOW approvals. Decide: a mode-scoped reader, or a second database for the live process (OQ-6).

**C-8. Deployment blockers.**
- The paper runtime refuses to start when any `BINANCE_*` name is present (`refuse_trade_capable_env`, exit code 3) and all `x-app` services share one `env_file` [VERIFIED: docker-compose.yml:16-19, 119-122 comment "WR-06 ... stays Phase 24"; src/paper/runtime.py:1516-1521]. Putting `BINANCE_DEMO_*` into the shared `.env` for the live service therefore breaks the paper service: the WR-06 env split is a functional prerequisite, not only hardening.
- The Dockerfile copies `src`, `scripts`, `alembic.ini`, `docs/research/universe`, `params`, `config/paper` only [VERIFIED: Dockerfile COPY lines]. `config/execution/execution-limits-v1.toml` and `config/binance/binance-limits-v1.toml` are not in the image; the live process cannot load its limits. Decide bake-in (rebuild per owner value change) or a read-only mount.
- The compose `live` service is a placeholder (`restart: "no"`, command raises SystemExit, `healthcheck: disable: true`) [VERIFIED: docker-compose.yml:161-173].

**C-9. OPS-04 cannot use `read_code_version` inside the container.** It runs `git rev-parse HEAD` and `git status --porcelain` via `subprocess` with a 30 s timeout [VERIFIED: src/adapters/code_version.py:33-55], `.dockerignore` excludes `.git` [VERIFIED: .dockerignore], and the runtime base is `python:3.13.15-slim-bookworm` (no git). Stamp the revision at build time (a `--build-arg`/ENV or a generated file) and have `--healthcheck` print `sys.version` plus that stamp; use `read_code_version` only on a dev checkout.

**C-10. Stale CONTEXT premises (use the recorded owner decisions instead).**
- `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` is already `True` [VERIFIED: src/risk/margin_check.py:282 `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED: Final[bool] = True`; DECISIONS D085 O-3]. O-4 of CONTEXT is half moot.
- `LIVE_NET_PNL_SEMANTICS_VERIFIED: bool = False` [VERIFIED: src/analytics/live_outcomes.py:80] and DECISIONS D086 O-4 says it "stays False until a DECISIONS row says otherwise", with verification by one small mainnet trade at the Phase 26 canary. D-23 (set it from one Demo fill) conflicts with D086; record the Demo sample as evidence only.
- D085 O-4: "the `LiquidationFailurePolicy` is `CLOSE_POSITION`. ... the Phase 24 composition must pass `CLOSE_POSITION` to `ProtectionCoordinator`". CONTEXT D-24/O-3 default (alert + SAFE_MODE, no close) contradicts an owner-recorded decision; the planner must surface the conflict. Note `ProtectionCoordinator` takes `liquidation_watch: LiquidationWatchPort | None` built as `LiquidationWatch(brackets, fee_rates, limits, policy)` [VERIFIED: src/execution/liquidation_watch.py:209-216].
- Already set in the file (not open): `account.max_equity_age_ms = 15000`, `account.max_daily_loss_age_ms = 300000`, `margin.liquidation_buffer_bps = 300`, `margin.max_bracket_age_ms = 60000`, `margin.headroom_bps = 1000` [VERIFIED: config/execution/execution-limits-v1.toml:55-61]. Target leverage 5 and ISOLATED are decided (D085 O-1).
- D-10: the Order, Fill and Position tables and repositories already exist (Phase 17: `PgTradingEntityStore.insert_order`, `get_order_by_client_order_id`, `get_order_by_algo_client_id`, `update_order_exchange_state`, `record_fill`, `insert_position`, `transition_position`) [VERIFIED: src/persistence/entities.py:433-660]. What is missing: production callers that write Order rows (needed only for the persisted exchange-state evidence of `update_order_exchange_state`; the router's lookup itself can and should run from the intent rows, P-4), the exchange event-time column with a monotonic guard, and `update_position_snapshot` (no such name anywhere in `src`: `git grep update_position_snapshot -- src scripts` is empty). Alembic head is `0014_decided_excl_expired.py`, so the new migration is `0015`.
- The last `docs/DECISIONS.md` row is D088 [VERIFIED: docs/DECISIONS.md tail], so Phase 24 rows start at D089 (candidates: G4-040 sync-store seam, D056 DEGRADED/DEMO mode, DEMO enablement semantics, any new limit keys, OQ answers).

**C-11. Existing tests that the new package will trip (amend them in the same plan).**
- `tests/test_phase18_gate.py::test_invariant_2_no_src_module_imports_the_supervisor` fails for any `src/live` module that imports `src.adapters.binance_userdata_supervisor` [VERIFIED: tests/test_phase18_gate.py:445-455].
- `tests/test_no_unratified_defaults.py` and Phase 18 invariant 5 pin `len(GUARDED_NAMES) == 62` [VERIFIED: tests/test_phase18_gate.py:484]; adding any new `ExecutionLimits` key changes that count (two names per key), the key tables in `execution_limits.py` and `config/execution/README.md`.
- `tests/test_paper_shadow_isolation.py` bans `src.execution.*` (except four pure helpers) and `src.adapters.binance_usdm` from the import closure of `src.paper.runtime`, `src.paper.shadow_runtime`, `src.paper.rehearsal`, `scripts.shadow_rehearsal` [VERIFIED: tests/test_paper_shadow_isolation.py:30-55]. The `StoreExecutor` used by the paper runtime for P16R-03 must live outside `src.execution` and `src.live` (recommend `src/ops/` or `src/persistence/`). The SHADOW money block (D-19) must be built without `ApprovalDesk` (which lives in `src.execution`).
- `tests/test_phase19_gate.py::test_invariant_7` forbids `src.backtest` imports under `src/execution` only [VERIFIED: tests/test_phase19_gate.py:532-543]; `src/live` may import `src.backtest.semantics.TP1_QUANTITY_FRACTION` as the scripts do, with a parity test.
- Deploy tests pin the placeholder and the image contents: `tests/test_deploy_compose.py::test_placeholders_fail_fast_naming_the_owning_phase` asserts the `live` service has `restart == "no"`, `healthcheck == {"disable": True}` and a command containing `SystemExit` and `Phase 24` [VERIFIED: tests/test_deploy_compose.py:250-260]; `tests/test_deploy_images.py` `RUNTIME_READ_PATHS` lists the paths the runtime image must carry (`params`, `config/paper`, `docs/research/universe`, `alembic.ini`, `src`, `scripts`) [VERIFIED: tests/test_deploy_images.py:266-273]. Replacing the placeholder and adding `config/execution` and `config/binance` to the image means amending both, plus `tests/test_deploy_heartbeat.py` for a `--target live`, `tests/test_cutover.py`/`tests/test_docker_cutover.py` and `tests/test_paper_runtime_compose.py` for the env split.

## Project Constraints (from CLAUDE.md / AGENTS.md)

Treated with the authority of locked decisions [VERIFIED: AGENTS.md read in full this session]:
- Always `uv run ...`, never bare `python`. Ruff line length 100; mypy `strict` on `src` only; pytest `asyncio_mode = "auto"`; every module starts with `from __future__ import annotations`; first-party imports absolute `src.*`.
- No AI/LLM in the decision path; fail closed; SAFE_MODE blocks entries while monitoring continues; quantization floors, never rounds up.
- Live placement stays disabled in this phase (`LIVE_ORDERS_DISABLED`); no mainnet; Demo scripts with `--execute` are owner-run only; the paper runtime refuses any `BINANCE_*` variable.
- Never push, never merge to `master`; stage explicit paths; leave `.gsd/`, `.planning/milestone.lock`, modified `.planning/config.json` alone. Commit trailer is the model that did the work (`Co-Authored-By: Claude <Model> <noreply@anthropic.com>`).
- Secrets only in `.env`; never read `.env`/`secrets.env` into a transcript; never put a DB URL, key or heartbeat URL in repo, commit, log or chat (heartbeat URLs by stdin).
- Parameter sets are hash-locked (never edit `params/**/*.toml`); `src/core` stays pure; Decimal only on the risk path; no wall clock in pure modules (inject clocks).
- Do not add without a DECISIONS row: `binance-connector`, `ccxt`, Kafka/RabbitMQ/Redis, Node toolchain, pandas/NumPy/SciPy/VectorBT on the decision path, pre-release dependencies. A new dependency means `uv add` and a committed `uv.lock`. Hash-pinned images/actions: never float a tag; refresh with `deploy/refresh-pins.sh`.
- `AGENTS.md` is gated by `scripts/decision_alignment/authority.py` and `tests/test_agents_md.py`; do not run `generate-claude-md` on it; after editing run `uv run python scripts/verify_decision_alignment.py all`.
- Research before optimisation; `docs/research/RESEARCH_PROTOCOL.md` is FROZEN; missing contract means TBD, never invent. Windows dev machine: use Git Bash for `deploy/*.sh` checks, expect CRLF warnings, edit CRLF-sensitive files bytes-aware (`.planning/WINDOWS.md`).
- Network is flaky: at most one retry of a Binance/Telegram/internet call, then report. A subagent claim is a lead, not a fact.

## Architectural Responsibility Map

This is a single-host, single-process backend (no browser, no CDN). Tiers here are process-internal.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Pure decisions (sizing, gates, plan binding, quantization) | `src/core`, `src/risk`, `src/domain`, `src/execution` pure cores | none | Must stay stdlib/Decimal; `src/live` is the only importer of the wiring, never the reverse (D-04) |
| Composition, start sequence, scheduler, glue Protocol impls | `src/live/` (new) | none | D-04: nothing else constructs adapters, coordinators, sinks or schedulers |
| Exchange I/O (REST + user-data stream) | `src/adapters/` behind project interfaces | `RestRateLimitGate` shared by all holders | SDK types never leave the adapter; one gate per process (D-15) |
| Telegram I/O (bot runner, cards, alerts) | `src/adapters/telegram_*` + PTB `Application` | `src/execution/approval_desk.py`, `confirm_flow.py` | The user-id gate lives in `on_callback` only (D-17) |
| Durable state (journal, intents, SAFE_MODE, enablement, reservations, orders/fills/positions) | PostgreSQL via sync SQLAlchemy stores, called through one `StoreExecutor` | local `LocalSpill` and `FileGateStateStore` files on a named volume | D-25; file stores are synchronous fsync writes (event-loop cost, see P-3) |
| Placement authority | `execute_approved_plan` only, reached only from the confirm core `on_confirmed` through `ExecutionService` | `ProtectionCoordinator` (stop after fill), `MarketEmergencyCloser` | Q5/D080: one `place_entry` POST per approval, never re-sent |
| Process supervision and monitoring | Docker Compose (`restart` policy, per-service healthcheck) + external heartbeat (`deploy/heartbeat.sh`) | `--healthcheck` / `--liveness` verbs | D042 condition 1 |

## Standard Stack

No new runtime dependency is needed or recommended. Everything below is already locked in `uv.lock` [VERIFIED: uv.lock lines for each name; `uv pip list`].

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.13.15 (`requires-python = "==3.13.*"`) | runtime | project pin [VERIFIED: pyproject.toml:5, Dockerfile base image tag] |
| asyncio (stdlib) | 3.13 | single event loop, `to_thread`, `ThreadPoolExecutor` | D-01/D-25 |
| python-telegram-bot | 22.8 | `Application`, `CallbackQueryHandler`, polling | already used by `build_application` and SHADOW [VERIFIED: uv.lock:811-812] |
| binance-sdk-derivatives-trading-usds-futures | 17.4.0 (+ binance-common 4.4.0) | REST + WS streams transport behind `BinanceUsdmAdapter` | single SDK construction path in `binance_client.py` [VERIFIED: uv.lock:156-175] |
| SQLAlchemy + psycopg | 2.0.54 + 3.3.6 (sync) | operational stores | D-25 keeps sync stores [VERIFIED: uv.lock:602-603, 875-876] |
| structlog / tenacity | 26.1.0 / 9.1.4 | logging; bounded message retry (never order retry) | existing [VERIFIED: uv.lock:895-905] |
| pytest / pytest-asyncio / pytest-xdist | 9.1.1 / 1.4.0 / 3.8.0 | tests | `asyncio_mode = "auto"` [VERIFIED: `uv pip list`, pyproject.toml] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Alembic | repo pin | migration `0015` (event-time column, position snapshot) | D-10; head check read-only at start |
| ruff 0.16.8 / mypy 2.3.1 | dev | lint, strict types on `src` | every plan's verify step |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio.to_thread` for store calls | async PostgreSQL pool (asyncpg / psycopg async) | rejected by D-25 and Deferred Ideas: new dependency, no measured need |
| Default executor (`to_thread`) for ordered writes | one dedicated `ThreadPoolExecutor(max_workers=1)` + `loop.run_in_executor` | required for writes that need order: the default executor reorders completion [VERIFIED: local run, see P-2] |
| PTB `run_polling()` | manual `initialize/start/updater.start_polling/stop/shutdown` in the existing loop | use the manual form, as `ShadowRuntime.start` does; `run_polling` blocks and owns signals [CITED: docs.python-telegram-bot.org Application.run_polling tip] |

**Installation:** none. Do not run `uv add` or `uv lock --upgrade` in this phase (see Package Legitimacy Audit).

**Version verification:** versions above are the locked versions read from `uv.lock`, not registry-latest. The registry-latest `binance-sdk-derivatives-trading-usds-futures` and `binance-common` were published on 2026-10-29 (one day before this research) [VERIFIED: `gsd-tools query package-legitimacy check` publishedAt 2026-10-29T14:25:22Z and 13:59:37Z]; the lock stays at 17.4.0 / 4.4.0 (the version whose models and docstrings were read here).

## Package Legitimacy Audit

Phase 24 installs no new package. The seam was still run for the dependencies the phase leans on:

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| python-telegram-bot | PyPI | years (latest release 2026-06-12) | n/a (PyPI gives none) | python-telegram-bot.org | SUS (`unknown-downloads`) | Existing locked dependency, no install: no checkpoint |
| binance-sdk-derivatives-trading-usds-futures | PyPI | latest release 2026-10-29 | n/a | none listed | SUS (`too-new`, `unknown-downloads`, `no-repository`) | Existing locked 17.4.0: do NOT bump in this phase |
| binance-common | PyPI | latest release 2026-10-29 | n/a | none listed | SUS (same reasons) | Existing locked 4.4.0: do NOT bump |
| structlog, tenacity, sqlalchemy, psycopg | PyPI | latest releases 2026-06 to 2026-10 | n/a | listed (tenacity, sqlalchemy, psycopg) | SUS (`unknown-downloads`; some `too-new` because the registry-latest release is recent) | Existing locked versions: no checkpoint |

**Packages removed due to SLOP verdict:** none.
**Packages flagged SUS:** all of the above, solely because the checker has no PyPI download counts and judges the newest release, not the locked one. They are not installed by this phase, so no `checkpoint:human-verify` install task is needed. Any plan that proposes a new dependency or an upgrade must add that checkpoint and a DECISIONS row (AGENTS.md).

## Seam inventory (exact constructors, who calls them in production today)

"Production caller" means a module under `src/` (tests and `scripts/demo_rehearsal.py` excluded). Constructor signatures were read from the cited lines this session.

### A. Execution side

| Seam | Constructor / entry (all keyword-only unless noted) | Production caller today | Phase 24 work |
|------|------------------------------------------------------|-------------------------|----------------|
| `execute_approved_plan` | see C-1; decorated by `_one_placement_per_symbol`, a module-level in-flight map keyed `(id(adapter), symbol)` [VERIFIED: src/execution/manager.py:489-531] | none | `ExecutionService._place`: assemble inputs, call once, never wrap in retry |
| `LivePlacementContext` | `signal, plan_constraint_snapshot, execution_limits, protection_registry, latest_closed_bar_close, gtd_clock_margin, tp1_quantity_fraction, clock, margin_guard, alert_sink=None` [VERIFIED: src/execution/live_context.py:78-87] | none | built per plan; `signal` must be the persisted Signal; `gtd_clock_margin` from the ratified drift limits (`max(ahead_limit_ms, behind_limit_ms)` in the rehearsal, demo_rehearsal.py:2096); `alert_sink` is the real sink (D-07); `latest_closed_bar_close` has no producer (Q6, see OQ-2) |
| `ProtectionCoordinator` | `adapter, intent_store, journal, safe_mode_controller, alert_sink, emergency_closer, limits, clock, pending_actions=None, spill=None, restore_required=False, liquidation_watch=None`; calls `limits.require_live_ready()` first [VERIFIED: src/execution/protection.py:828-848] | none (rehearsal only) | build with `restore_required=True`, `pending_actions=PgPendingActionStore`, `spill=LocalSpill`, `liquidation_watch=LiquidationWatch(... policy=CLOSE_POSITION)` per D085; `step()` is the stepper task; `fill_sink(routed)` is the router handler; `register_resting_entry` is called by the manager |
| `MarketEmergencyCloser` | `adapter, journal, safe_mode_controller, alert_sink, clock, limits, pending_actions=None, spill=None, lot_filters=None` [VERIFIED: src/execution/emergency_close.py:420-432] | none | pass `lot_filters=LotFilterSource(adapter, PgLotFilterStore, limits, clock, snapshot_for=PgPlanConstraintSnapshotStore.get)` (20-DEFERRED lot-filter wiring) |
| `UnknownEntryResolver` | `store, adapter, journal, safe_mode_controller, limits, entry_good_till: Callable[[IntentRecord], datetime | None]` [VERIFIED: src/execution/intent_recovery.py:497-511] | none | step it once per reconcile tick via `ReconcileLoop(unknown_entries=...)`; `entry_good_till` from the stored plan expiry |
| `LiveEnablementController` | `journal, spill=None`; `rehydrate(journal, state, spill)`; `enable(operator_id, now_utc, health_verdict, kill_gate_state)`; `disable(operator_id, now_utc)` [VERIFIED: src/execution/enablement.py:109-117, 211-217, 287] | none | see C-2 |
| `LiveEquitySource` | `adapter, clock, limits, quote_asset` (needs `account.max_equity_age_ms`) [VERIFIED: src/execution/account_equity.py:137-143] | none | per-plan `refresh()` then `build_live_risk_inputs` (WR-04 ordering: read the clock AFTER the refresh) |
| `LiveDayRiskService` | `reader, store, equity, clock, symbols, quote_asset, funding_policy, parameter_set, limits` [VERIFIED: src/execution/day_risk_service.py:251-262] | none | `PgDayRiskStore`, backfill at start, `ingest_fill` and `invalidate` from the stream account/fill sinks; `current_daily_loss_quote(utc_day)` feeds `make_reserving_save_atomic` |
| `BracketCache`, `SymbolConfigGuard`, `MarginGuard` | `BracketCache(adapter, clock, limits)`; `SymbolConfigGuard(adapter, target_leverage)`; `MarginGuard(config_guard, brackets, account, claims, clock, limits)` (claims = `PgRiskReservationStore.list_margin_claims`) [VERIFIED: bracket_cache.py:107-112, symbol_config_guard.py:137, margin_guard.py:275-282] | none | `target_leverage=5` is the named constant `TARGET_LEVERAGE: Final[int] = 5` (symbol_config_guard.py:58, D085 O-1); the guard is the required `LivePlacementContext.margin_guard` |
| `LiquidationWatch` | `brackets, fee_rates, limits, policy: LiquidationFailurePolicy` [VERIFIED: src/execution/liquidation_watch.py:209-216] | none | `policy=CLOSE_POSITION` (D085 O-4, see C-10); `fee_rates` = the commission cache |
| `build_live_risk_inputs` | pure; `equity, day, verdict, counted, exchange_exposures, candidate_trade_plan_id, parameter_set, now_utc, max_equity_age` [VERIFIED: src/execution/live_risk_inputs.py:144-155] | none | the D-21 producer calls it; returns `LiveRiskInputsResult` (inputs or `UNCERTAIN_ACCOUNT_STATE` / `DAILY_STOP_BLOCK`) |
| `resolve_live_cost_rates` | pure; `parameter_rates, account_commission, candidate_symbol, now_utc, ttl` (ttl is the registry key `commission_rate_ttl_seconds`) [VERIFIED: src/risk/live_commission.py:123-130 and docstring] | none | commission refresh task + cache (D-22) |
| `expire_pending_entry` | `plan_hash, symbol, adapter, journal, now_utc, trigger_reason, spill=None` returns `CancelVerdict` [VERIFIED: src/execution/manager.py:2400-2408] | only hand-off failure and operator close | the D-13 scheduled cancel calls it; it already verifies the cancel afterwards and leaves a filled entry to the coordinator |

### B. Approval and Telegram

| Seam | Constructor / entry | Production caller today | Phase 24 work |
|------|---------------------|-------------------------|----------------|
| `ApprovalDesk` | `ApprovalDesk(stores, *, profile, clock, intent_reader)`; `issue(signal, plan, money, exposure_quote, reason_codes, now_utc)`; `send(bot, chat_id, issued, sleep)`; `resolve`, `dispatch`, `reply_fn`, `finalize_hook`, `finalize_expired_requests` [VERIFIED: src/execution/approval_desk.py:276-283, 350-359, 491-498] | none | the approval request sender wraps `issue` + `send`; `profile=DEMO_CONFIRM_PROFILE`; `stores` is `PgShadowStores`-shaped but its `save_atomic` must be `make_reserving_save_atomic(approvals=PgApprovalStore, reservations=PgRiskReservationStore, parameter_set, daily_loss_quote)` [VERIFIED: src/persistence/risk_reservations.py:585-640] |
| `make_confirm_flow` / `ConfirmFlow` | `desk, profile, stores, clock, bot, sleep=asyncio.sleep, mark_price, validity_rule, recheck, on_confirmed, prefetch=None, ttl_seconds=CONFIRM_TTL_SECONDS_DEFAULT` [VERIFIED: src/execution/confirm_flow.py:814-828]; `callback_kwargs(authorized_chat_id, authorized_user_ids, error_journal)` returns the full `on_callback` keyword set | none | `expire_on_restart(now_utc)` once at start; `finalize_expired(now_utc)` as a scheduler task; `validity_rule` = `functools.partial(check_remaining_validity, ...)` per the docstring (confirm_flow.py:126-134). Note: `make_confirm_flow` builds `CoreConfirmBook` without a `reservations=` port, so the exposure reservation of Phase 21 happens at APPROVE through `make_reserving_save_atomic`, not at CONFIRM |
| `build_application` / `on_callback` | `build_application(*, token, authorized_chat_id, authorized_user_ids, binding_context_resolver, dispatch, reply_text_fn, confirm_handler, approved_handler, finalize_message, error_journal, clock)`; it calls `on_callback`, which validates `authorized_user_ids` (required, never allow-all) [VERIFIED: src/adapters/telegram_callbacks.py:1022-1036, 1341-1391] | `src/paper/runtime.py` (SHADOW) | the live runner uses the manual PTB lifecycle exactly like `ShadowRuntime.start/stop` (src/paper/shadow_runtime.py:1259-1293): `initialize`, `start`, `updater.start_polling(allowed_updates=["callback_query"], error_callback=...)`, stop in reverse order; add the application error handler |
| `make_confirm_recheck`, `PrefetchedConfirmInputs` | `ConfirmInputs(pre_placement: PrePlacementInputs, position_mode: str)`; `holder.put(trade_plan_id, inputs)`; the recheck `take`s once [VERIFIED: src/execution/confirm_recheck.py:50-126] | none | the `prefetch(signal, plan)` coroutine awaits mark price, last price, open orders, open algo orders, positions, position mode and `put`s them; the same reads gate 5e of the manager performs, so share one builder |

### C. Binance adapters and the stream

| Seam | Constructor / entry | Production caller today | Phase 24 work |
|------|---------------------|-------------------------|----------------|
| `build_sdk_client` | `environment, credentials, limits: ClientLimits, surfaces, live_enablement=None`; LIVE requires an enabled controller [VERIFIED: src/adapters/binance_client.py:427-453] | scripts only | `Environment` has exactly `DEMO = "DEMO"`, `TESTNET = "TESTNET"`, `LIVE = "LIVE"` (binance_client.py:102-107): reuse it as the D-02 mode value instead of a second enum; DEMO REST is the SDK constant `DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL`, DEMO WS Streams is `"wss://demo-fstream.binance.com"`, WS API `None` (binance_client.py:153-160) |
| credentials | `credential_spec_for(env)`; `load_api_credentials(environ, spec, repo_root, refuse_if_present=(other_spec,))`; names `BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_API_SECRET`, `BINANCE_LIVE_API_KEY`, `BINANCE_LIVE_API_SECRET` (each also as `<NAME>_FILE`) [VERIFIED: src/adapters/binance_client.py:263-276, 348-382] | scripts only | D-02 mirror rule is `refuse_if_present` |
| `BinanceUsdmAdapter` | `(sdk_client, *, rest_gate, sleep, signed_call_policy, drift_guard, clock, on_clock_skew)`; a `drift_guard` requires a `clock`; a `signed_call_policy` requires `rest_gate` and `rest_gate.policy == signed_call_policy.rate_limit` [VERIFIED: src/adapters/binance_usdm.py:801-841] | none | pass `drift_guard=ClockDriftGuard(limits=<DriftLimits>)`, `on_clock_skew=guard.note_clock_skew_error` (D-14 hook); the signed methods cannot run without a gate |
| `ClockDriftGuard` | `(*, limits: DriftLimits)`; `refresh(server_time, clock_ms, now_utc)`; `needs_remeasure(now_utc)`; `entries_allowed(now_utc)` [VERIFIED: src/adapters/binance_clock.py:204-305] | none | scheduler task: `if guard.needs_remeasure(now): await guard.refresh(server_time=adapter.server_time, clock_ms=<ms clock>, now_utc=clock)`; the ms clock is a callable returning `int` (the paper runtime's `_monotonic_ms` is the precedent but is a wall-independent monotonic; use the composition's injected clock for `now_utc`) |
| `RestRateLimitGate` | `(*, policy, clock, state_store=None, on_alert=None)`; `restore()` once; `recovery_status()`; `restriction()` [VERIFIED: src/adapters/binance_ratelimit_gate.py:228-245, 342-387] | none | `state_store=FileGateStateStore(path, clock=...)` on the persistent volume; `on_alert` to the real sink (`REST_GATE_RECOVERY_REQUIRED`); one instance passed to the adapter, `BinancePublicMarketData`, `SdkListenKeyPort`, the probe adapter and `UserDataSupervisor` |
| user-data assembly | `SdkListenKeyPort(rest_api, *, rest_gate)`; `SdkUserDataTransport(configuration, client_factory=None, ws_client=None)`; `UserDataAdapter(*, transport, listen_keys, limits, clock)`; `UserDataSupervisor(*, adapter, limits, clock, sleep, rest_gate, snapshot_provider, on_state_change, on_event, on_snapshot, on_failure)` [VERIFIED: binance_userdata.py:230, 480-486, 667-674; binance_userdata_supervisor.py:307-320] | `scripts/user_data_smoke.py:829-847, 1760-1777` is the proven assembly recipe | `snapshot_provider` is an async REST snapshot (positions, open orders, open algo orders); sinks are synchronous and must only record or enqueue |
| `UserDataRouter` | `(*, order_lookup, journal, session_id, clock, fill_sink, status_hint_sink, exchange_state_sink, algo_sink, account_sink, divergence_sink, fills_fallback)`; `route(item) -> RouteResult` is synchronous; "one router instance serves one stream session" (`session_id` at most 128 chars) [VERIFIED: src/adapters/binance_userdata_router.py:445-486] | none | `supervisor.on_event` calls `router.route`; `fill_sink = coordinator.fill_sink` plus equity invalidation, day-risk `ingest_fill` and the liquidation-watch trigger fan-out (a router has ONE `fill_sink`, so fan out in a small composed callable that never raises) |

### D. Reconcile, sweeper, SAFE_MODE

| Seam | Constructor / entry | Production caller today | Phase 24 work |
|------|---------------------|-------------------------|----------------|
| `ReconcileLoop` | `adapter, gate, safe_mode, intent_store, protection, sweeper, alerts, journal, limits, unknown_entries=None, feeds=None, stream=None, lot_filters=None, pending_actions=None, risk_reducer=None, entry_good_till=None, feed_clock_skew=None`; refuses a non-durable SAFE_MODE controller, unset limits, and a tick not strictly below `max_unprotected_ms`; `tick(now_utc)`; an overlapping tick returns `TICK_SKIPPED_OVERLAP` [VERIFIED: src/reconcile/loop.py:462-482, 487-496, 534-542] | none | pass `feed_clock_skew=clock_skew_from_drift(binance_limits.drift)` (20-DEFERRED WR-B6); `risk_reducer` = an awaitable that steps coordinator then closer pending actions |
| `OrphanSweeper` | `(*, adapter, journal, now_utc=None)`; `sweep(diff, *, position_verifier, now_utc)`; falls back to `datetime.now(UTC)` when `now_utc` is None [VERIFIED: src/reconcile/sweeper.py:150-167] | none (the loop drives it) | the sweeper is NOT its own scheduler task: the loop calls it. Pass an explicit `now_utc` always (wall-clock fallback violates the injected-clock rule) |
| `run_startup_recovery` | `safe_mode_load, pending_store, coordinator, closer, restored_plans_builder, close_attempts_reader, intent_store, probe_adapter, journal, spill, now_utc, spill_replay=None` returns `StartupReport` [VERIFIED: src/reconcile/startup.py:200-214] | none | step 7 of D-08; the coordinator must have been built with `restore_required=True` |
| `SafeModeController` | `(*, adapter, journal, compare_fn=None, state_store=None, on_enter=None)`; `load(adapter, journal, state_store, now_utc, compare_fn, on_enter)` starts IN SAFE_MODE `SAFE_MODE_STATE_UNREADABLE` on any store failure; `exit_safe_mode(...)` see C-6 [VERIFIED: src/reconcile/safe_mode.py:235-346, 569-578] | none | `PgSafeModeStateStore(PgSystemStateStore(db, journal))`; `on_enter=SafeModeAlertObserver(sink)` (D-07) |

### E. Ops

| Seam | Constructor / entry | Production caller today | Phase 24 work |
|------|---------------------|-------------------------|----------------|
| `JournalFirstAlertSink` | `(*, journal, spill, limits, queue=None)`; needs `alerts.dedupe_window_ms` (raises `ExecutionLimitsNotConfigured` otherwise); `alert(...)`, `critical(...)`, `requeue_undelivered(journal_rows)` (the read of rows with correlation `operational_alerts` "belongs to the composition, Phase 24") [VERIFIED: src/ops/alerts.py:358-373, 433-441] | none | startup: read undelivered alert rows and requeue (step before the bot starts) |
| `TelegramAlertSender` | `(*, bot, chat_id, journal, spill, sleep, queue)`; `await drain()` never raises for a send failure; re-queues on cancellation [VERIFIED: src/ops/alerts.py:611-666] | none | a `drain` scheduler task sharing the sink's `queue`; the sink and the sender are different objects sharing one deque |
| `FileGateStateStore` | `(path, *, clock)`; `initialize(now_utc, operator_id)`, `load`, `save`, `inspect`, `reinitialize` [VERIFIED: src/ops/rest_gate_state.py:159-240] | `src/ops/rest_gate_cli.py` | first-install flag in the start sequence; file writes are synchronous fsync (see P-3) |
| `LocalSpill` | `(directory)`; creates the directory (mode `0o700` where honoured) [VERIFIED: src/ops/spill.py:189-196] | none | directory on a named volume; an unmounted volume re-created empty reads as empty (20-DEFERRED row 43): add a startup sentinel file check |
| health probes | ten `check_*` functions plus `run_health_checks(results=...)`; each journals one `HEALTH_CHECK` event [VERIFIED: src/ops/health.py:286-592] | `scripts/demo_rehearsal.py` only | health scheduler producing all ten; see C-3 |

### F. Persistence

| Seam | Constructor | Notes |
|------|-------------|-------|
| engine | `make_sync_engine(url)` (connect, lock, statement, pool timeouts, UTC pin) then `OperationalDatabase(engine)` [VERIFIED: src/paper/runtime.py:468-492] | `DATABASE_URL_SYNC` or `DATABASE_URL`; the compose network URL is built in `x-database-env` |
| stores | `PgJournalStore(db)`, `PgApprovalStore(db)`, `PgSystemStateStore(db, journal)`, `PgSafeModeStateStore(system_state)`, `PgPendingActionStore(db)`, `PgDayRiskStore(db)`, `PgLotFilterStore(db)`, `PgPlanConstraintSnapshotStore(db)`, `PgRiskReservationStore(db)`, `PgExecutionStateStore(db)` (the `ExecutionIntentStore`), `PgTradingEntityStore(db, journal=...)`, `PgShadowStores(db)` (satisfies `DeskStores` and `ConfirmStores`) | all synchronous; none is called from production code in a live process yet |

### G. Deploy

`docker-compose.yml` `live` placeholder (C-8), `deploy/heartbeat.sh` targets `collector` (default) and `paper` only (its own URL file `/etc/trading/heartbeat-paper.url`, own systemd credential and units) [VERIFIED: deploy/heartbeat.sh header], `deploy/systemd/` has no live units, the `paper` service is the pattern for `restart: unless-stopped` + `--hold-on-refusal` + per-service healthcheck [VERIFIED: docker-compose.yml:123-139].

## Limit keys Phase 24 needs (item 2): what is NOT_CONFIGURED, what is set, what does not exist

**Rule for the planner:** no number is proposed here. The owner supplies every value in one checkpoint (D-12); each needs a DECISIONS row and provenance `DECISION` [VERIFIED: config/execution/execution-limits-v1.toml header "A set value needs a DECISIONS row and the provenance label DECISION"].

### Still `NOT_CONFIGURED` (15 keys: 14 required, 1 alert-only) [VERIFIED: config/execution/execution-limits-v1.toml:29-52]

Verbatim lines: `max_unprotected_ms = "NOT_CONFIGURED"`, `entry_terminal_timeout_ms = "NOT_CONFIGURED"`, `entry_unknown_grace_ms = "NOT_CONFIGURED"`, `emergency_close_poll_timeout_ms = "NOT_CONFIGURED"` (section `[protection]`); `min_remaining_validity_seconds`, `max_mark_price_age_ms`, `max_last_price_age_ms` (`[pre_placement]`); `tick_interval_ms`, `entry_unknown_probe_count`, `entry_unknown_probe_interval_ms`, `lot_filter_refresh_interval_ms`, `entry_stale_grace_ms` (`[reconcile]`); `max_mark_price_age_ms`, `max_user_data_silence_ms` (`[stale_feed]`); `dedupe_window_ms` (`[alerts]`). Every one is read as `None`; `require_live_ready()` raises `ExecutionLimitsNotConfigured` naming the unset required keys [VERIFIED: src/execution/execution_limits.py:252-260]. `reconcile.entry_stale_grace_ms` is the one alert-only key (`ALERT_ONLY_LIMIT_KEYS`, execution_limits.py:110): unset only skips the stale-entry alert.

| Key | Consumed by (constructor refuses when unset) | Constraint / evidence the owner needs |
|-----|-----------------------------------------------|----------------------------------------|
| `protection.max_unprotected_ms` | `ProtectionCoordinator` (D-13 deadline) | `reconcile.tick_interval_ms` must be strictly below it (`check_reconcile_cadence`); 20-DEFERRED: "Must exceed several coordinator step cadences (Phase 24) and the 120 s HTTP 429 pause, or a correctly protected position is market-closed (CLOSE_FAILED)"; Demo showed a by-id stop query answering -2013 right after placement although the stop was NEW (lag not measured) |
| `protection.entry_terminal_timeout_ms` | `ProtectionCoordinator` | starts at the first fill, not at placement |
| `protection.entry_unknown_grace_ms` | `ProtectionCoordinator`, `UnknownEntryResolver` | Demo: a GTD entry was still `NEW` 840 s after `goodTillDate` (20-DEFERRED "Demo results of 2026-10-22"); a GTD expiry is not proof of a terminal order |
| `protection.emergency_close_poll_timeout_ms` | `MarketEmergencyCloser` | separate from `max_unprotected_ms` |
| `pre_placement.min_remaining_validity_seconds` | manager gate 5e, confirm card `validity_rule` | exchange floor: a `goodTillDate` must be greater than now + 600 s (error -5040 "The goodTillDate timestamp must be greater than the current time plus 600 seconds") [CITED: developers.binance.com/en/docs/products/derivatives-trading-usds-futures/error-code.md]; `LivePlacementContext.gtd_clock_margin` is added on top |
| `pre_placement.max_mark_price_age_ms`, `.max_last_price_age_ms` | manager gate 5e and the CONFIRM recheck | the CONFIRM recheck rebinds the checked-at instants to the press instant (confirm_recheck.py:19-24) |
| `reconcile.tick_interval_ms` | `ReconcileLoop` (cadence) | strictly below `protection.max_unprotected_ms` |
| `reconcile.entry_unknown_probe_count`, `.entry_unknown_probe_interval_ms` | `UnknownEntryResolver` | the "3 probes / 5000 ms" once suggested is non-binding and must not appear in code (20-DEFERRED) |
| `reconcile.lot_filter_refresh_interval_ms` | `LotFilterSource.refresh_if_due` | the loop calls `refresh_if_due` once per tracked symbol at the end of a compared tick; WR-B7: the refresh runs inside the tick lock with no timeout |
| `stale_feed.max_mark_price_age_ms` | feed freshness (`assess_feeds`) | a different key from `pre_placement.max_mark_price_age_ms` (never reuse) |
| `stale_feed.max_user_data_silence_ms` | feed freshness | Binance sends user-data events only on account activity, so the feed liveness time must be the newest of last event, ping, pong from `supervisor.liveness()` (20-DEFERRED "Feed liveness source for FeedSource"); the ratified `stream.max_liveness_age_seconds` is `"none"` [VERIFIED: config/binance/binance-limits-v1.toml:42] so this key is the only silence bound |
| `alerts.dedupe_window_ms` | `JournalFirstAlertSink` (no default; raises when unset) | blocks every alert path, including SAFE_MODE alerts |
| `reconcile.entry_stale_grace_ms` (alert-only) | stale-entry alert | optional: leave unset to skip that alert |

### Already set (not owner-open any more)

`account.max_equity_age_ms = 15000` (D084), `account.max_daily_loss_age_ms = 300000` (D087), `margin.liquidation_buffer_bps = 300`, `margin.max_bracket_age_ms = 60000`, `margin.headroom_bps = 1000` (D085) [VERIFIED: config/execution/execution-limits-v1.toml:55-61 and DECISIONS D084/D085/D087]. Ratified Binance limits (sha256-pinned, 27 keys, not editable): `drift.ahead_limit_ms = 500`, `behind_limit_ms = 1000`, `max_measurement_age_seconds = 300`, `periodic_remeasure_interval_seconds = 60`; `stream.keepalive_interval_seconds = 1800`, `event_queue_max = 4096`; `signed_calls.recv_window_ms = 5000`, `rate_limit_retry_after_cap_seconds = 259200` [VERIFIED: config/binance/binance-limits-v1.toml:10-43]. The D-06 re-measure cadence therefore already exists: `drift.periodic_remeasure_interval_seconds`.

### Cadences CONTEXT O-1 names that have no key today

- **Protection step cadence:** no key. `ProtectionCoordinator.step()` is a no-argument async method; recommended: drive it at `reconcile.tick_interval_ms` (no new owner number) and additionally wake it immediately when `fill_sink` queues a fill (an `asyncio.Event` set by the fan-out callable), because a protective stop after a fill is bounded by `max_unprotected_ms` and a periodic-only step adds its full period to the unprotected window. Alternative: a new `protection.step_interval_ms` key (touches `EXECUTION_LIMIT_KEYS`, `EXECUTION_LIMIT_FIELDS`, the TOML + provenance, `config/execution/README.md`, and the two `GUARDED_NAMES` counts).
- **D083 clock margin:** no key and no code. D083 point (4): a new owner-set margin key, `NOT_CONFIGURED` until set, and points (1) to (6) are the gate change (`ErrorFacts`/`rate_limit_decision`/`RestRateLimitGate.record` read an integer after the literal `IP banned until `). The ratified binance-limits file cannot take the key (27 keys, pinned); it belongs in `execution-limits-v1.toml`. It must behave as an optional refinement: with it unset the existing 259200 s fallback applies, so it must NOT be a required key (else `main()` could never start under D-12). Mirror the `ALERT_ONLY_LIMIT_KEYS` mechanism with a differently named set. Amend the message-text source guard (`tests/test_binance_usdm_source_guard.py`, rule 3) for the single permitted read.
- **Commission refresh / max age:** the TTL is the registry key `commission_rate_ttl_seconds` [VERIFIED: src/risk/live_commission.py docstring "the registry key `commission_rate_ttl_seconds`"], so the refresh cadence is derived from it (refresh at a fraction of the TTL is a planner choice that needs no new owner number only if expressed as "refresh whenever older than the TTL minus the reconcile tick"; otherwise an owner number).
- **Mark price freshness (D-27):** use the two existing `max_mark_price_age_ms` keys; no new key.
- **Heartbeat interval/grace:** operator-supplied at install (`deploy/heartbeat.sh --install-timer --interval-seconds N`, "has no default"); the paper check uses period 60 s, grace 120 s per the owner (STATE.md "second heartbeat check (period 60 s, grace 120 s)").
- **Scheduler tasks with no cadence source** (drain of the alert queue, ConfirmFlow `finalize_expired`, health scheduler, liveness stamp write): derive from existing keys or the HTTP-level bounds already ratified, or add keys; the primitive must not invent defaults (AST guard `tests/test_no_unratified_defaults.py` fails any numeric default for guarded names).

## Official-doc facts (item 3). Re-read status and confidence

Tooling note: the Binance developer site is a single-page app; WebFetch of most REST pages returns the landing page. What worked: `.md` URLs under `/en/docs/products/derivatives-trading-usds-futures/` for `user-data-streams`, `general-info`, `error-code`; the `legacy-docs` path for REST endpoint pages; the installed SDK's generated docstrings. The `gsd-tools classify-confidence` seam rates `webfetch`/`websearch` LOW and `context7` MEDIUM; findings below are tagged by what they rest on. **Plans must re-read the pages named "RE-READ" on a machine/tool that renders them (owner-run).**

| Fact | Source | Confidence |
|------|--------|-----------|
| **Commission rate:** `GET /fapi/v1/commissionRate` (USER_DATA), request weight (IP) 20, `symbol` mandatory, `recvWindow` optional, `timestamp` mandatory; response fields `symbol`, `makerCommissionRate` ("0.0002" = 0.02%), `takerCommissionRate` ("0.0004"), `rpiCommissionRate` ("0.00005") | [CITED: developers.binance.com/legacy-docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate (legacy page)] and [VERIFIED: installed SDK 17.4.0 `rest_api/api/account_api.py:1035-1066` docstring "Weight(IP): 20", path `/fapi/v1/commissionRate`, and `UserCommissionRateResponse` fields] | MEDIUM. RE-READ the current (non-legacy) page: the current catalog URL printed in the SDK docstring (`.../catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account#user-commission-rate`) was not renderable by the fetch tool |
| The adapter already implements the call with fail-closed parsing (missing, non-decimal, negative, above 0.01, wrong symbol raise `ValueError`; no retry; "runtime wiring (refresh loop, TTL) is Phase 24") | [VERIFIED: src/adapters/binance_usdm.py:1647-1686] | HIGH |
| **User-data stream URL:** base `wss://fstream.binance.com/private`, stream at `/ws/<listenKey>`, example `wss://fstream.binance.com/private/ws/<listenKey>`; the page does not mention an `events` parameter or an alternative query-string form | [CITED: developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams.md, read in full] | MEDIUM (a third-party library claims a newer `/private/ws?listenKey=...&events=...` form; the official page read here does not show it; D-16 keeps the SDK as transport and asks the smoke to record the URL form once) |
| listenKey valid 60 minutes; `PUT` extends 60 minutes, `-1125` "This listenKey does not exist" means recreate with `POST`; `POST` with an active key returns it and extends 60 minutes; `DELETE` closes the stream and invalidates the key; a single connection is valid for 24 hours | same page | MEDIUM. The ratified `stream.keepalive_interval_seconds = 1800` is inside the 60-minute validity |
| Event names: `MARGIN_CALL`, `ACCOUNT_UPDATE`, `ORDER_TRADE_UPDATE`, `ACCOUNT_CONFIG_UPDATE`, `TRADE_LITE`, `CONDITIONAL_ORDER_TRIGGER_REJECT`, `STRATEGY_UPDATE`, `GRID_UPDATE` (deprecated), `ALGO_UPDATE`, `listenKeyExpired` | same page | MEDIUM |
| `CONDITIONAL_ORDER_TRIGGER_REJECT`: "update when a triggered TP/SL order got rejected". The project classifies it as a `DEPRECATED_EVENT` anomaly [VERIFIED: src/adapters/binance_userdata_events.py:28-32] while the page marks only `GRID_UPDATE` deprecated | same page | MEDIUM: a rejected triggered stop is safety-relevant; re-label it (it still surfaces as an anomaly and a `StreamDivergence`, so it is not silent) |
| `ALGO_UPDATE` statuses `NEW`, `CANCELED`, `TRIGGERING`, `TRIGGERED`, `FINISHED`, `REJECTED`, `EXPIRED`; `EXPIRED` includes a system cancel after all positions on the symbol are closed | same page | MEDIUM. Consistent with Demo observation A3 (both legs end `EXPIRED`) |
| `ORDER_TRADE_UPDATE` order status values `NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `EXPIRED`, `EXPIRED_IN_MATCH`; execution types include `TRADE`, `AMENDMENT`, `CALCULATED`; expiry-reason code 8 = "The initial order has expired after the stop order is triggered" | same page | MEDIUM |
| Ordering: messages of the same event type on one connection are strictly ordered by both `T` and `E`; "Use the `E` field for ordering updates", especially across event types | same page | MEDIUM: supports D-10's monotonic update keyed by exchange event time |
| The page does not say what happens to events during a reconnect | same page (silence) | no observation; Demo showed frames sent during a gap were not redelivered (20-DEFERRED); REST is the truth |
| **New algo order:** `POST /fapi/v1/algoOrder`, `algoType` mandatory and only `CONDITIONAL`; `clientAlgoId` unique among open orders, regex `^[\.A-Z\:/a-z0-9_-]{1,36}$`; `closePosition=true` with `STOP_MARKET`/`TAKE_PROFIT_MARKET` closes all of the current position and cannot be sent with `quantity` or `reduceOnly`; weight 1 on each of the 10 s and 1 min order-rate limits, 0 on IP rate limit; `workingType` default `CONTRACT_PRICE`; `goodTillDate` must exceed now + 600 s | [CITED: developers.binance.com/legacy-docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order (legacy page)] | MEDIUM-LOW (legacy page). The page does NOT contain the 200 conditional-order limit nor the "no position yet" rule; those rest on project evidence: Demo -4509 (probe check file line 38) and the project's recorded 200 headroom |
| **Cancel algo order:** `DELETE /fapi/v1/algoOrder`, weight 1, "Either `algoId` or `clientAlgoId` must be sent" | [CITED: legacy-docs .../trade/rest-api/Cancel-Algo-Order] | MEDIUM-LOW. The ~1 s `NEW` lag after cancel (D-34) is Demo-observed, not documented |
| **Rate limits and bans:** limits are per IP; after a 429 you must back off; continuing to send after 429 leads to an automated IP ban, HTTP 418; ban durations scale "from 2 minutes to 3 days"; 403 is the WAF limit; order endpoints are not exempt from order rate limits; `-1008` overload (HTTP 503) exempts "reduce-only, close-position and cancel orders" only from -1008 | [CITED: .../derivatives-trading-usds-futures/general-info.md] | MEDIUM. Matches 20-DEFERRED: the exemption is from -1008 only, not from 429 or 418 |
| **-1003 text:** "Too many requests; current limit is %s requests per minute." and "Way too many requests; IP banned until %s." | [CITED: .../derivatives-trading-usds-futures/error-code.md] | MEDIUM. The general-info page does not document `Retry-After` or the "banned until" format (silence): D083's path (epoch milliseconds after the literal `IP banned until `) rests on a third-party report (ccxt issue 23970) and stays UNVERIFIED on Futures. RE-READ before building D083 |
| Other codes the project relies on: `-1021` "Timestamp for this request is outside of the recvWindow"; `-1125` INVALID_LISTEN_KEY; `-2011` CANCEL_REJECTED "Unknown order sent"; `-2013` "Order does not exist"; `-2022` REDUCE_ONLY_REJECT; `-2024` "Position is not sufficient"; `-2019` "Margin is insufficient"; `-4116` "clientOrderId is duplicated"; `-4164` min notional "no smaller than 5.0 (unless you choose reduce only)"; `-4137`/`-4138` closePosition conflicts; `-5040` goodTillDate; `-2021` would immediately trigger. `-4509` is NOT on the page (Demo-observed only) | [CITED: .../error-code.md] | MEDIUM |
| Server time window: SIGNED endpoints need `timestamp`; `recvWindow` default 5000 ms; accepted only if `timestamp < serverTime + 1000` and `serverTime - timestamp <= recvWindow` | [CITED: .../general-info.md] | MEDIUM. Ratified `drift.ahead_limit_ms = 500` is inside the +1000 ms rule |
| **Telegram getUpdates:** "This method will not work if an outgoing webhook is set up"; updates are stored on the server for at most 24 hours; an update is confirmed once `getUpdates` is called with a higher offset | [CITED: core.telegram.org/bots/api#getupdates] | MEDIUM. The page text read does not state the single-consumer 409 rule; the project rule is `BOT_TOKEN_RULE` (16-DEC-Q-L) and PTB's `Conflict` class |
| **python-telegram-bot 22.8 lifecycle:** `run_polling()` order is `initialize`, `post_init`, `Updater.start_polling`, `start`, run, `Updater.stop`, `stop`, `post_stop`, `shutdown`, `post_shutdown`; "When combining python-telegram-bot with other asyncio based frameworks ... manually call the methods ... Keeping the event loop running and listening for a stop signal is then up to you"; `Application.stop()` does not stop the updater and "does not call post_stop"; updates are processed one by one unless `concurrent_updates` is set; `add_error_handler` receives every error, signature `async def callback(update: object | None, context)`; polling errors reach the handlers with `update=None` | [CITED: docs.python-telegram-bot.org/en/stable/telegram.ext.application.html and applicationbuilder.html via Context7 /websites/python-telegram-bot_en_stable] | MEDIUM. Consequence: a handler that awaits placement would block every other update (CANCEL, replays); `on_confirmed` must only schedule |
| **asyncio:** `asyncio.to_thread` propagates `contextvars`; "can typically only be used to make IO-bound functions non-blocking" (GIL) | [CITED: docs.python.org/3/library/asyncio-task.html] | MEDIUM |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Placing, cancelling, protective stops, emergency close | any new order call path or retry wrapper | `execute_approved_plan`, `ProtectionCoordinator`, `MarketEmergencyCloser`, `expire_pending_entry` | Q5/D080: one POST per approval; the AST guard forbids retry constructs |
| Telegram user gate and callback parsing | a second handler or manual `dispatch_callback` | `on_callback` via `ConfirmFlow.callback_kwargs(...)` | `authorized_user_ids` is validated there; omission is a `ValueError` |
| Confirm state machine, token issue, TTL, replay | new tokens or expiry logic | `src/approval/confirm_core.ConfirmBook` + `ConfirmFlow` | replay semantics, B2 lock order, RUNTIME_RESTART already pinned |
| Alert dedupe, journal-first, requeue, bounded message retry | a new queue or sender | `JournalFirstAlertSink` + `TelegramAlertSender` + `SafeModeAlertObserver` | OPS05 matrix and Phase 23 wording are golden-tested |
| REST ban/pause handling and persistence | per-holder sleep/retry on 418/429 | one `RestRateLimitGate` with `FileGateStateStore` | restart recovery and SAFE_MODE exit row 6 depend on it |
| Reconcile compare, orphan sweep, SAFE_MODE exit rules | a second reconcile or sweep | `ReconcileLoop`, `OrphanSweeper`, `SafeModeController.exit_safe_mode` | seven fixed exit rows, two-read position proof |
| Clock drift | an NTP client or ad hoc skew check | `ClockDriftGuard` + `measure_clock_drift` with the ratified `drift.*` | opt-in at the adapter: composition must pass it (24-NOTES item 1) |
| Risk inputs | recomputing equity/loss/exposure | `LiveEquitySource`, `LiveDayRiskService`, `build_live_risk_inputs`, `make_reserving_save_atomic` | parity with backtest pinned by Phase 21/22 tests |
| Durable sync-to-async bridge | a custom thread-pool framework or an async DB pool | one `StoreExecutor` over `ThreadPoolExecutor(max_workers=1)` for ordered writes plus `asyncio.to_thread` for reads | D-25; ordering proven below |
| Healthcheck/liveness files and held marker | new marker formats | `src/paper/held_marker.py` and `liveness.py` patterns (schema-versioned JSON, atomic replace) | probes must never crash or print values |
| Heartbeat sender | a Python sender | `deploy/heartbeat.sh` (`--target` pattern) | URL-by-stdin, no-xtrace, fail-open rules already enforced and shellchecked |

**Key insight:** the dangerous part of this phase is not any single feature, it is the seams: sync hooks vs async placement, sync stores on the loop, shared env/bot/database between SHADOW and DEMO, and Protocols nobody implements. Most "build" items are 20 to 80 line glue classes; the cost is in the tests that pin their behaviour.

## Architecture Patterns

### System architecture diagram

```
 Telegram (owner chat) --getUpdates (1 consumer per bot token)--> PTB Application (manual lifecycle)
      | callback_query                                                  ^ edit / send
      v                                                                 |
 on_callback: chat gate + authorized_user_ids gate ---> ApprovalDesk.dispatch --> PgApprovalStore.save_atomic
      |                                                  (decision + Phase 21 reservation in ONE tx)   [StoreExecutor]
      | CONFIRM: ConfirmFlow.prefetch (async REST reads -> PrefetchedConfirmInputs)
      |          -> ConfirmBook.handle_confirm (sync: recheck, *_CONFIRMED journal) --> on_confirmed (sync hook)
      v                                                                        |  schedules a task, returns at once
 ExecutionService._place  <-----------------------------------------------------+
   LiveRiskInputProducer (equity, day loss, reservations, commission, brackets, algo count, constraints)
   LivePlacementContext(signal, snapshot, limits, registry, margin_guard, alert_sink, clock, ...)
      v
 execute_approved_plan: identity -> stored-outcome replay -> binding -> ENABLEMENT -> limits -> SAFE_MODE
      -> cost rates -> risk -> pre-placement -> position mode -> margin guard -> consume (ENTRY intent) -> place GTD LIMIT
      v                                                           (no entry-time stop; one POST per approval)
 BinanceUsdmAdapter --(shared RestRateLimitGate, ClockDriftGuard)--> Binance Demo REST
      |                                   RestingEntry --> ProtectionCoordinator registry

 Binance user-data stream --SDK--> UserDataAdapter --> UserDataSupervisor (keepalive, rekey, gap state, held events)
      | on_event (sync) --> UserDataRouter.route --> fill fan-out: coordinator.fill_sink | equity.invalidate | day_risk.ingest_fill
      |                                          \-> divergence queue (drain) | status hints | account sink | journal
      v
 Scheduler (injected clock + sleep; per-task last-run/last-error journal rows)
   protection step (also woken by a fill) | reconcile tick (-> sweeper, UnknownEntryResolver, feed check, lot-filter refresh,
   risk_reducer) | drift re-measure | commission / bracket refresh | confirm TTL sweep | alert drain | health | liveness stamp
   | scheduled cancel at plan expiry
      v
 SafeModeController (durable, PgSafeModeStateStore) <-- loop / coordinator / manager;  on_enter --> SafeModeAlertObserver
      --> JournalFirstAlertSink --queue--> TelegramAlertSender.drain --> Telegram
 PostgreSQL: journal, approvals, execution_intents, system_state, reservations, day risk, lot filters, snapshots (+ 0015)
 Named volume: FileGateStateStore file, LocalSpill directory, held marker, liveness stamp
```

### Recommended project structure (names are Claude's discretion; keep one composition module, D-04)

```
src/live/
├── runtime.py          # CLI: --healthcheck / --liveness / --hold-on-refusal, main(), run_admitted
├── config.py           # mode (reuse binance_client.Environment), env parsing, paths, first-install flag
├── startup.py          # the D-08 sequence as ordered named steps, each journaled
├── wiring.py           # build_wiring(...) -> LiveWiring (the ONLY place that constructs live objects)
├── scheduler.py        # task primitive (injected clock + sleep)
├── execution_service.py# on_confirmed bridge + per-plan assembly + the single execute_approved_plan call
├── approval_sender.py  # second-plan refusal, D028 chain, money block, desk.issue + send
├── risk_inputs.py      # D-21 producer; commission.py cache + refresh
├── stream.py           # supervisor assembly, fill fan-out, divergence queue, FeedSource, client-id index
├── health.py           # ten-probe producers + DEGRADED/DEMO mode; liveness.py stamp
├── operator.py         # authenticated Telegram commands (SAFE_MODE exit etc.)
└── signal_source.py    # SignalSource Protocol + Demo injector
src/ops/store_executor.py   # neutral home (paper imports it too; must not sit in src.execution or src.live)
```

### Pattern 1: start sequence as data, each step fail-closed and journaled
**What:** D-08 as an ordered list of named steps; a failure enters SAFE_MODE (entries blocked, monitoring continues) and, under `--hold-on-refusal`, holds with a marker the probe reads, exactly like `src/paper/runtime.py` `_hold/_refuse` (held marker, wait for SIGTERM, return the code only after stop) [VERIFIED: src/paper/runtime.py:279-335, 1458-1527].
**Order (maps to existing functions):** (1) env + mode + `load_api_credentials(..., refuse_if_present=(other_spec,))`; (2) `FileGateStateStore.initialize` ONLY with an explicit flag, then `gate.restore()` (a missing file without the flag is "unknown", never a fresh install); (3) Alembic head compare, read-only; (4) `SafeModeController.load(...)`, `LiveEnablementController` default (disabled), snapshots; (5) `ClockDriftGuard.refresh`; (6) `adapter.exchange_info` + `LotFilterSource.refresh_if_due` per symbol; (7) `run_startup_recovery(...)`; (8) one `ReconcileLoop.tick`; (9) only then start supervisor, bot, scheduler, and (DEMO) `enable()`; also `ConfirmFlow.expire_on_restart(now)` and `JournalFirstAlertSink.requeue_undelivered(rows)` before the bot starts.
**Note:** the SAFE_MODE `load` itself starts IN SAFE_MODE with reason `SAFE_MODE_STATE_UNREADABLE` on any store failure [VERIFIED: src/reconcile/safe_mode.py:292-344], so step 4 already fails closed.

### Pattern 2: scheduler primitive (sketch; the cadence comes from the loaded limits, never a default)
```python
# Sketch. Source of pattern: src/paper/runtime.py _LiveLoop watchdog + tests/support/virtual_time.py.
@dataclass(frozen=True)
class TaskSpec:
    name: str
    run: Callable[[], Awaitable[None]]
    interval: timedelta          # computed from ExecutionLimits / DriftLimits at build time; no default
    wake: asyncio.Event | None = None   # e.g. set by the fill fan-out so the protection step runs now

class Scheduler:
    def __init__(self, *, clock, sleep, journal, specs): ...
    async def _loop(self, spec: TaskSpec) -> None:
        while not self._stopping:
            started = self._clock()
            try:
                await spec.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:                       # a task never kills the loop
                self._note(spec.name, started, error=type(exc).__name__)   # class name only
            else:
                self._note(spec.name, started, error=None)
            await self._wait(spec)                         # injected sleep, or the wake event
```
Rules: no `time.*`/`datetime.now`/`loop.time()` in the module (AST guard `tests/support/ast_guards.wall_clock_calls`, which also matches `loop.time()`); the per-task result also feeds the matching health probe.

### Pattern 3: StoreExecutor (ordered writes, parallel reads)
```python
# src/ops/store_executor.py (neutral location: tests/test_paper_shadow_isolation.py bans src.execution from the SHADOW closure)
class StoreExecutor:
    def __init__(self) -> None:
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="store-writer")
    async def read(self, fn, /, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)
    async def write(self, fn, /, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(
            self._writer, functools.partial(fn, *args, **kwargs))
    def close(self) -> None:
        self._writer.shutdown(wait=True)
```
Two facts measured locally (P-2): the default executor completes concurrent calls out of order; a cancelled `await` does not stop the worker thread. Writes must therefore be idempotent and must not be cancelled mid-flight on shutdown (shield them or drain the writer).

### Pattern 4: the `on_confirmed` bridge (C-1)
```python
class ExecutionService:
    def on_confirmed(self, approval, plan, confirmed_at_utc) -> None:   # OnConfirmedFn: sync, returns None
        coro = self._place(approval, plan, confirmed_at_utc)
        if self._on_loop_thread():                    # handle_confirm ran on the loop thread
            task = self._loop.create_task(coro)
        else:                                          # D-25 moved handle_confirm to the writer thread
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            ...                                         # keep fut; attach a done-callback that journals
        self._tasks.add(task); task.add_done_callback(self._finished)   # strong ref + exception journal
    async def _place(self, approval, plan, at):
        callback = Callback(raw_token=self._desk.approve_token_for(approval.approval_id), ...)  # new accessor
        inputs = await self._producer.assemble(approval, plan, at)      # D-21; a refusal is a NO_TRADE outcome
        outcome = await execute_approved_plan(callback=callback, approval=approval, ..., live_context=ctx)
        # exactly one call, no loop, no tenacity (Q5/D080); the outcome is journaled and the card finalised
```

### Pattern 5: fill fan-out (the router has ONE `fill_sink`)
A small composed callable that never raises and never blocks: `coordinator.fill_sink(routed)`; set the protection `wake` event; `equity.invalidate(reason=...)`; `day_risk.ingest_fill(fill)`; trigger the post-fill liquidation watch check as a scheduled task. A failing member must not skip the others (the router already journals `ROUTER_SINK_FAILURE` per sink and raises a `SINK_FAILURE` divergence if the sink raises [VERIFIED: src/adapters/binance_userdata_router.py:37-41]).

### Pattern 6: the D-05 wiring gate
Build `LiveWiring` with fakes only at the edges (SDK client, PTB bot, clock) and real classes everywhere else, then assert types and identities: one `RestRateLimitGate` object shared by adapter, public data, listen-key port, supervisor, producers; the adapter has a non-None `ClockDriftGuard` and a never-measured guard raises `EntriesBlocked` before any SDK call [VERIFIED: src/adapters/binance_usdm.py:216-230 `EntriesBlocked(PreSendRefusal)`]; the Telegram handler is `on_callback`; the sink is a `JournalFirstAlertSink` (the rehearsal's `RehearsalAlertSink` is rejected); `ProtectionCoordinator.emergency_closer` is a `MarketEmergencyCloser`; `SafeModeController` is durable (`is_durable`). The adapter exposes no public accessor for its gate/guard, so assert through `LiveWiring` fields and add read-only properties where identity must be proven.

### Pattern 7: Q5 guard for `src/live/`
The existing guard scans the definitions of the three placement functions for loops and tenacity [VERIFIED: tests/test_binance_usdm_source_guard.py:302-335], not their callers. For the new package add an AST rule: no `Call` whose attribute name is `place_entry`, `place_algo_protective` or `place_market_close` anywhere under `src/live/`; `execute_approved_plan` is called in exactly one module (`execution_service.py`), once, outside any loop, `try/except` re-call or `tenacity` decorator; no `tenacity` import under `src/live/` except where a bounded MESSAGE retry is intended (alerts glue), allow-listed per file with a reason. Include negative controls (a seeded snippet must fail), as every guard in this repo has.

### Anti-Patterns to Avoid
- **Awaiting placement inside the Telegram handler or the hook:** PTB processes updates one by one by default; a long await blocks CANCEL and replays [CITED: PTB `concurrent_updates`].
- **A separate CLI process for SAFE_MODE exit or operator close:** the exit closes over in-process coordinator state (C-6).
- **Using `asyncio.to_thread` for ordered writes:** default executor reorders (P-2).
- **Putting `StoreExecutor` in `src/execution` or `src/live`:** breaks the SHADOW isolation closure test.
- **Defaulting any cadence "just to start":** `tests/test_no_unratified_defaults.py` fails numeric defaults for guarded names, and the owner rule forbids invention.
- **Reusing the SHADOW bot token or database for DEMO:** C-7.
- **Importing `src.paper.runtime` from `src/live`** (D-01) or `scripts/*` / `tests/*` from `src/` (the rehearsal imports `tests.support.intent_store_fakes.InMemoryExecutionIntentStore`; the live process must use `PgExecutionStateStore`).

## Common Pitfalls

### P-1: sync PostgreSQL and file I/O on the event loop (G4-040, P16R-03)
**What goes wrong:** `ConfirmBook.handle_confirm` (journal writes, recheck), `ApprovalDesk.dispatch` (`save_atomic` + reservation under a `FOR UPDATE` day lock), router-side `known_order` lookups, `FileGateStateStore.save` (tmp + fsync + replace) and `LocalSpill.write` all run synchronously on whichever thread calls them. On the loop thread each can block it up to the engine bounds (connect, lock, statement, pool timeouts) [VERIFIED: manager.py docstring lines 676-682; src/persistence/engine.py `make_sync_engine`].
**How to avoid:** wrap through `StoreExecutor` at the composition seam. Where library code calls a store synchronously inside a sync callback (router sinks, `known_order`), the callback must touch memory only and enqueue the I/O. `ConfirmFlow._confirm` calls `self._book.handle_confirm(...)` directly (confirm_flow.py:400); moving it to a worker needs a small injected `run_sync` seam in `ConfirmFlow` (and the `on_confirmed` thread rule of Pattern 4). `ConfirmBook` uses `threading.Lock` and `PrefetchedConfirmInputs` is documented thread-safe, so a worker thread is the intended use [VERIFIED: confirm_core.py:31-34; confirm_recheck.py:58-73].
**Warning signs:** reconcile `TICK_SKIPPED_OVERLAP` rows, supervisor queue growth toward `event_queue_max = 4096`, PTB "Query is too old" on CONFIRM.

### P-2: `asyncio.to_thread` ordering and cancellation (measured)
Local run this session (`uv run python`, 3.13.15): two concurrent `to_thread` calls (first sleeps 0.2 s, second 0.0 s) completed in the order `[2, 1]` on threads `asyncio_1`, `asyncio_0`; the same pair on `ThreadPoolExecutor(max_workers=1)` completed `[1, 2]` on one thread `store_0`; a `to_thread` task cancelled at 0.05 s still completed its side effect (`[(9, 'asyncio_1')]`) 0.5 s later. [VERIFIED: scratchpad `to_thread_probe.py` output]. Consequences: ordered writes need the single worker; a cancelled caller does not mean the write did not happen (restart-safe idempotent writes, `shield` on shutdown); contextvars propagate into the thread [CITED: docs.python.org], which matters for `current_press_correlation()` journal correlation.

### P-3: file stores with fsync under a `threading.Lock` called from async code
`RestRateLimitGate.record/check` hold `self._lock` and `_persist()` writes through `FileGateStateStore` (fsync). It only writes on a 418/429 change, so the cost is rare and small, but it is on the loop; on Windows `replace_with_retry` can sleep under an indexer lock (WINDOWS.md entry, `[NOT_TESTED]`). Keep it, document it, test that a slow `GateStateStore` does not deadlock the loop.

### P-4: the router is synchronous end to end
`UserDataRouter.route` and every sink are plain callables; `fills_fallback` is sync (C-5); `OrderLookup.known_order` is called once per order event. A blocking lookup stalls the loop for every event. **Source for the lookup:** the intent rows are written before the send (`consume_and_record_entry_intent(... client_order_id ...)` for the entry, `record_protective_intent` before each protective placement) and carry `client_order_id` / `algo_client_id` [VERIFIED: src/execution/intent_store.py:79-99, 122-136, 150]. Keep an in-memory index rebuilt at start from `list_unresolved_intents` plus registered plans and updated by the service/coordinator, with the deterministic-id helpers (`is_system_client_id`, `plan_hash_prefix_of`, `role_of_client_id`, prefixes `x-`, `xa-`, `xc-` [VERIFIED: src/execution/order_ids.py:61-66, 202-229]) to avoid a false `UNKNOWN_ORDER` anomaly. A fill that arrives before any index entry would raise an `UNKNOWN_STREAM_ORDER` divergence and (via the loop) SAFE_MODE: the entry id must be in the index BEFORE `place_entry` is awaited (a marketable limit can fill instantly).

### P-5: PTB behaviour that interacts with restart and replay
Updates are processed one by one; `drop_pending_updates` defaults to False (updates are kept up to 24 h by Telegram [CITED: core.telegram.org/bots/api#getupdates]), so after a restart the old APPROVE/CONFIRM taps are redelivered and must be answered from the stored decision (D-09, D-20); do NOT drop pending updates, the replay path is the safety property under test. Two processes polling one token produce `telegram.error.Conflict`. Stop in the order `updater.stop()`, `application.stop()`, `application.shutdown()` (as `ShadowRuntime.stop`); `Application.stop()` does not stop the updater [CITED: PTB docs].

### P-6: Windows dev machine and CRLF
`loop.add_signal_handler` is not available on Windows event loops; use the main-thread `signal.signal` pattern of `_wait_for_stop_signal` (runtime.py:634-651). `deploy/*.sh`, compose files and Dockerfile need LF; git warns about CRLF (AGENTS.md): edit bytes-aware and run shellcheck (installed here) on `deploy/heartbeat.sh` changes; the deploy test set has shellcheck tests that skip when shellcheck is absent (WINDOWS.md entry 7). File-replace under an indexer lock is `[NOT_TESTED]`. Docker Desktop daemon is up on this machine (build and `-m docker` tests are runnable), PostgreSQL tests run because `TEST_DATABASE_URL` is set in this shell (re-check in the executor's shell: unset means the `*_pg.py` files silently skip; use `TRADING_CI_STRICT=1` to turn skips into failures).

### P-7: clocks
`OrphanSweeper` falls back to `datetime.now(UTC)` when `now_utc` is None (sweeper.py:146-147, 161-167): always pass it. `execute_approved_plan` requires `risk_kwargs["now_utc"] == now_utc` and the manager reads `live_context.clock` AFTER the gate-5e reads for the mark-price age (CR-01); `build_live_risk_inputs` requires `now_utc` read AFTER `LiveEquitySource.refresh()` (a `now` captured before the refresh gives a negative age and is refused by design). The clock-drift guard blocks new entries on a never-measured or stale (`max_measurement_age_seconds = 300`) verdict, so the re-measure task (60 s) must be running before enable and must not share a failure domain with the reconcile tick.

### P-8: SHADOW and DEMO sharing identifiers
Approval ids hash `(trade_plan_id, action)`; short ids derive from `(signal_id, trade_plan_id)` (C-4, C-7). DEMO must use its own Signal/TradePlan rows. The confirm core's orphan sweep is mode-agnostic over `list_approved_approvals` (C-7).

### P-9: gate arithmetic that looks like a typo
`reconcile.tick_interval_ms` must be strictly below `protection.max_unprotected_ms` (loop constructor raises `ExecutionLimitsInvalid`), `max_unprotected_ms` must also exceed several step cadences and the 120 s 429 pause (20-DEFERRED), and `gtd_clock_margin` is added on top of the exchange's 600 s `goodTillDate` floor. Put a test over the owner's final numbers (a pure arithmetic test that fails with the key names) so a later edit of the TOML cannot silently invalidate the relationships.

### P-10: Telegram alert delivery is at-least-once and a failed CRITICAL alert is never re-queued in process (WR-C6, open)
`TelegramAlertSender.drain` journals `ALERT_SEND_FAILED` and drops; the dedupe window then suppresses repeats (20-DEFERRED WR-C6: needs an owner decision on redelivery bound and delay, which are new numbers). During the smoke, an unreachable Telegram means the operator hears nothing: rely on the heartbeat/health path for liveness and record WR-C6 in the owner register.

## Code Examples

Verified patterns from this repository (no new API is introduced):

### Gate + adapter + drift guard + stream assembly (from the proven smoke script)
```python
# Source: scripts/user_data_smoke.py:805-847 and 1760-1777 (Phase 18), adapted names only
spec = binance_client.credential_spec_for(environment)
credentials = binance_client.load_api_credentials(
    environ, spec=spec, repo_root=REPO_ROOT, refuse_if_present=(other_spec,))
bundle = binance_client.build_sdk_client(
    environment=environment, credentials=credentials, limits=limits.client, surfaces=SURFACES)
gate = RestRateLimitGate(policy=limits.signed.rate_limit, clock=clock,
                         state_store=gate_store, on_alert=alert_hook)      # + gate.restore() at start
drift_guard = ClockDriftGuard(limits=limits.drift)
adapter = BinanceUsdmAdapter(bundle.client, rest_gate=gate, signed_call_policy=limits.signed,
                             drift_guard=drift_guard, clock=clock,
                             on_clock_skew=drift_guard.note_clock_skew_error)
stream_adapter = UserDataAdapter(transport=SdkUserDataTransport(stream_config), listen_keys=
                                 SdkListenKeyPort(bundle.client.rest_api, rest_gate=gate),
                                 limits=limits.stream, clock=clock)
supervisor = UserDataSupervisor(adapter=stream_adapter, limits=limits.stream, clock=clock,
                                sleep=sleep, rest_gate=gate, snapshot_provider=snapshot,
                                on_state_change=..., on_event=router_feed, on_snapshot=..., on_failure=...)
```
`stream_config` is `ConfigurationWebSocketStreams(stream_url=row.ws_streams_url, reconnect_delay=limits.stream.sdk_reconnect_delay_ms, reconnect_attempts=limits.stream.sdk_reconnect_attempts)`.

### Rehearsal assembly that the smoke replaces (what hand-stepping looks like today)
`scripts/demo_rehearsal.py:2014-2119` builds `MarketEmergencyCloser`, `ProtectionCoordinator`, `LivePlacementContext` per run; `2827-2884` builds the controller, enables it with `KillGateState.WITHIN_BUDGET`, then calls `execute_approved_plan`. The rehearsal refuses without `margin_guard` ("Composing the live one is Phase 24, so the rehearsal never invents one").

## State of the Art

| Old approach | Current approach | When changed | Impact |
|--------------|------------------|--------------|--------|
| `closePosition` stop placed with the entry | GTD LIMIT entry, stop after the first fill (D079) | 2026-10-22 | Demo rejects the stop with -4509 while flat; the coordinator places it after a fill is seen |
| Message-text parsing for decisions | classify by int code only (D-10), single narrow exception D083 | 2026-10-22 | D083 is the only permitted text read |
| SDK reconnect trusted | supervisor makes every gap visible, REST snapshot before releasing held events | Phase 18 | stream = hint, REST = truth |
| `CONDITIONAL_ORDER_TRIGGER_REJECT` as deprecated | listed as a live event on the current user-data page | page read 2026-10-30 | re-label; it signals a rejected triggered stop |
| `health.py` DEGRADED "unchanged policy" | explicit DEMO/LIVE DEGRADED rows (D056) | this phase | changes a policy other tests pin |

**Deprecated/outdated:** the REST docs pages read for algo orders and commission are marked legacy by the site; treat the shapes as MEDIUM until re-read on the current catalog. `GRID_UPDATE` is deprecated per the current page (the project ignores it already).

## Suggested plan decomposition (planner discretion; `tdd_mode` is on, so each plan starts with its failing tests)

| Wave | Plan slice | Why this order |
|------|-----------|----------------|
| 0 | `StoreExecutor` in `src/ops` plus the paper `expire_due` move (P16R-03) and the isolation test; scheduler primitive plus AST guard; test rig `tests/support/live_rig.py` and fake-exchange extensions (see Wave 0 gaps); owner-checkpoint document (limit keys, OQ-1 to OQ-10) | everything later is built on these; the owner answers take calendar time |
| 1 | config + mode + env refusal + CLI verbs + held marker + liveness (D-02, D-03, OPS-02); gate/adapter/drift composition and D083 (D-06, D-15); alert path (D-07); migration `0015` + client-id index + event-time monotonic update (D-10) | no Telegram/placement yet; each is independently testable with fakes |
| 2 | approval request sender + desk/confirm flow + PTB runner (+ SHADOW money block behind O-6); `ExecutionService` + risk-input producer + commission refresh; stream assembly + protection stepper + liquidation watch; reconcile loop + sweeper + startup recovery + scheduled cancel | the criterion-1 links; the two largest are the service and the stream |
| 3 | health producers + DEGRADED/DEMO mode + `enable()` wiring + kill-gate event; operator commands; `LiveWiring` + D-05 wiring gate + Q5 guard + amended invariants + replay/restart tests (fakes and PG) | the gate plan is last so it can assert everything |
| 4 | Dockerfile (config files, revision stamp), compose `live`, env split, cutover test re-run, `heartbeat.sh --target live` (+ systemd units, shellcheck), RUNBOOK; smoke script + owner checklist/evidence templates; inherited-item closures (G3-005 enum promotion + GLOSSARY, G2-035 triage, G4-034) and DECISIONS rows from D089; phase gate test + traceability | host/owner items last; evidence template needs the final output shape |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Driving `ProtectionCoordinator.step()` at `reconcile.tick_interval_ms` plus an immediate wake on a queued fill is acceptable and needs no new owner number | Limit keys | owner may want a separate `protection.step_interval_ms`; adds a key and test-count changes |
| A2 | Two long pollers on one bot token produce Telegram 409 / `telegram.error.Conflict` (taken from the project's own rule BOT_TOKEN_RULE and the PTB class docstring; the Telegram page read does not state it) | C-7 | low: the project rule already requires separate bots |
| A3 | The current (non-legacy) Binance REST pages for commission rate and new/cancel algo order match the legacy pages read | Official-doc facts | endpoint shape or weight could differ; the SDK 17.4.0 docstring agrees on weight 20 and path for commission |
| A4 | A fixed DEMO operator id plus `KillGateState.WITHIN_BUDGET` for the in-process DEMO `enable()` is acceptable (the rehearsal does exactly this) | C-2 | owner may require the human `enable()` also in DEMO |
| A5 | `src/ops/store_executor.py` keeps the SHADOW import closure free of `src.execution` and `src.live` | C-11 | the isolation test fails; move the module |
| A6 | `ConfirmBook.handle_confirm` and `ApprovalDesk.dispatch` are safe to run on the single writer thread (they use `threading.Lock`; the docstrings call the holder thread-safe) | P-1 | a hidden loop-thread assumption (for example `asyncio.get_running_loop()` inside) would raise on the worker thread; must be proven by a test |
| A7 | The Demo account accepts `GET /fapi/v1/commissionRate` for the five live symbols and returns plausible rates | Seam A | commission refresh fails closed on Demo; the owner run records the fact (D-22) |
| A8 | One `UserDataRouter` instance per process (session id = process start) is acceptable, its ALGO_UPDATE de-dup key set growing for the process life | Seam C | memory growth over weeks; Phase 25 soak would show it |
| A9 | `Environment` (DEMO/TESTNET/LIVE) can be the D-02 mode value, with TESTNET rejected by the composition | Seam C | a second enum would duplicate the URL/credential rows |
| A10 | A mode-scoped `list_approved_approvals` (or a second database) is a small change | C-7 | if large, it needs its own plan and DECISIONS row |
| A11 | The owner can create a second Telegram bot for DEMO (as for SHADOW, Q-L) | C-7 | otherwise SHADOW and DEMO cannot run at the same time |

## Open Questions

1. **OQ-1 Limit values (blocks the first Demo run).**
   - Known: 15 keys unset (table above); relationships between them; Demo evidence on the stop-query lag and the GTD non-expiry.
   - Unclear: the numbers; whether the owner also wants a separate protection step key (A1).
   - Recommendation: one checkpoint document (plain words, one row per key: meaning, who reads it, constraint, evidence), the owner answers, the assistant writes the TOML + provenance + DECISIONS row (D089+) and adds the arithmetic-relationship test (P-9). The planner must not default any value.
2. **OQ-2 Where do Signal/TradePlan come from in the live process? (C-4)**
   - Known: no producer in the CONTEXT topology; the rehearsal derives a synthetic plan; DEMO needs ids distinct from SHADOW's; `latest_closed_bar_close` (Q6) has no producer either.
   - Unclear: whether strategy-driven DEMO signals are expected in Phase 24 or only the smoke injector.
   - Recommendation: `SignalSource` Protocol + the injector for the smoke; ask the owner which phase owns the strategy-driven source (and its bar feed for `latest_closed_bar_close`); do not import `src.paper.*` pipeline pieces without that decision.
3. **OQ-3 DEMO enablement semantics (C-2, C-3).** Known: the manager gate needs `enable()`; `enable()` needs a ten-probe passing verdict. Unclear: owner acceptance of an in-process DEMO enable (A4) and the live meaning of the three market-feed probes. Recommendation: keep the manager unchanged; define the probes and DEGRADED rows in one plan with the D056 text; pin both rows in tests.
4. **OQ-4 Telegram identity for the live process (C-7).** Known: one consumer per token; SHADOW bot exists. Unclear: second bot for DEMO and the same or another chat. Recommendation: second bot token in the `live` service env only.
5. **OQ-5 Operator commands (C-6).** Known: owner confirmed on 2026-10-23 that Phase 24 wires Telegram commands (SAFE_MODE exit, gate status/clear, EXEC-06 controls) on the Phase 23 base; CONTEXT has no decision. Unclear: the minimal set for this phase. Recommendation: SAFE_MODE exit (two-step confirm), gate `status`, disable entries (risk-reducing, no confirm), close position (two-step); everything else deferred; no command may place or raise risk.
6. **OQ-6 One database per mode (C-7).** Known: WR-06 in the confirm core. Unclear: mode-scoped reader versus a second database/volume. Recommendation: mode-scoped reader keyed on the profile's ISSUED journal event; second database only if that proves large.
7. **OQ-7 Post-fill liquidation policy (C-10).** D085 O-4 recorded `CLOSE_POSITION` and says the composition must pass it; CONTEXT D-24/O-3 defaults to alert + SAFE_MODE. Recommendation: follow D085 unless the owner overrides, and say so in the checkpoint.
8. **OQ-8 Heartbeat shape (D-30).** The shipped design is one external check per target (`--target collector|paper`, own URL file, own credential, own units), not one sender that ANDs probes. Recommendation: add `--target live` in the same pattern (distinguishable alerts); the "one sender covers every process" criterion is met by having one check per process. Ask the owner only if they want a combined check.
9. **OQ-9 Delivery of the limits files to the container (C-8).** Bake `config/execution` and `config/binance` into the image (owner value change = rebuild, hash visible in image) or mount read-only. Recommendation: bake in, like `config/paper`, so the image hash covers the decision surface.
10. **OQ-10 Revision stamp for OPS-04 (C-9).** Recommend an `ARG`/`ENV` stamp passed by the build script; confirm `deploy/update.sh` and `deploy/soak-image.sh` pass it, and that the Dockerfile pin tests tolerate an `ARG`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python / uv | tests, lint | yes | Python 3.13.15, uv 0.12.17 (Dockerfile pins uv 0.12.21) | none needed |
| Docker Desktop daemon | image build, `-m docker` tests, compose rehearsal | yes (Server 29.8.0, Docker Desktop) | 29.8.0 | skip docker-marked tests |
| PostgreSQL for `*_pg.py` tests | persistence and replay/restart PG tests | yes in this shell: `TEST_DATABASE_URL` is set (value not read); `psql`/`pg_isready` are not on PATH | native service per STATE.md | unset means silent skips: run with `TRADING_CI_STRICT=1` |
| shellcheck | `deploy/heartbeat.sh` changes | yes (winget package) | n/a | WINDOWS.md entry 7 said absent: now present |
| Git Bash | `deploy/*.sh` checks | yes | bash 5.2.37 | none |
| Binance Demo (public ping) | owner smoke | a public `GET /fapi/v1/ping` returned HTTP 200 from this shell during research | n/a | The brief says Binance/Telegram are unreachable from this machine and Demo runs are owner-only: treat reachability as unreliable and never send a signed request from here |
| Telegram API | owner smoke, G2-014 | not probed | n/a | owner-run |
| Real VPS, healthchecks.io, second Telegram account, no-withdrawal key attestation | D-30, D-32, G2-014, OPS-02 | no | n/a | owner checklist + evidence template; marked NOT_OBSERVED until the owner runs it |

**Missing dependencies with no fallback:** none for building and fake-based testing. **Owner-only:** every Demo/VPS/Telegram observation.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1, pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`), pytest-xdist 3.8.0 (dev extra) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`; marker `docker`; `tests/conftest.py` (`frozen_clock` 2026-09-19T00:00:00Z) |
| Quick run command | `uv run pytest tests/test_live_*.py tests/test_phase24_gate.py -x -q` (plus the amended `tests/test_phase18_gate.py`, `tests/test_paper_shadow_isolation.py`) |
| Full suite command | `uv run pytest -m "not docker" -n 4` (about 9 to 10 min, about 1.7 GB; one heavy process at a time) |
| Recorded gate | sequential `uv run pytest -m "not docker"` on a clean tracked tree with `TEST_DATABASE_URL` set, saved under the phase `evidence/` |
| Static checks | `uv run ruff check && uv run ruff format --check`, `uv run mypy src`, `uv lock --check`, `uv run python scripts/verify_decision_alignment.py all` |
| Docker suite | `uv run pytest -m docker` (image, compose, cutover) |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| APRV-01 | request card has the mandatory fields + stored money block; second-plan-per-symbol refusal; a send failure approves nothing; runner handler is `on_callback`; unauthorized user and non-private chat rejected | unit/integration (fakes) | `uv run pytest tests/test_live_approval_sender.py tests/test_live_telegram_runner.py -x` | Wave 0 (existing library tests: `tests/test_approval_desk.py`, `tests/test_confirm_flow.py`, `tests/test_telegram_authorization.py`, `tests/test_telegram_error_handler.py`) |
| EXEC-01 | CONFIRM leads to exactly one `execute_approved_plan` through `on_confirmed` (loop thread and worker thread); hook/task failure paths journaled; per-plan inputs fail closed (stale equity, unknown loss, missing commission, algo headroom); DEMO `enable()` rules; real Demo order ids | integration (fakes) + owner Demo | `uv run pytest tests/test_live_execution_service.py tests/test_live_risk_input_producer.py tests/test_live_commission_refresh.py tests/test_live_enablement_wiring.py -x` | Wave 0 |
| EXEC-02 | stream frame to router to fan-out to coordinator to REST-confirmed stop with no manual call; reconcile tick composed; sweeper treats "cancel sent, open list empty" as success with a lagging fake; scheduled cancel at expiry only with zero fills; SAFE_MODE drill (enter, entries blocked, operator exit in process) | integration (fakes) | `uv run pytest tests/test_live_stream_to_protection.py tests/test_live_reconcile_wiring.py tests/test_live_scheduled_cancel.py tests/test_live_safe_mode_drill.py -x` | Wave 0 (extends `tests/test_protection_router_rig.py`) |
| EXEC-03 | replayed APPROVE/CONFIRM/CANCEL; restart between APPROVE and CONFIRM; restart between CONFIRM and the `place_entry` result; two concurrent CONFIRMs: `place_entry` called zero or one time; ids from `derive_client_order_id` | integration (fakes) + `_pg` | `uv run pytest tests/test_live_replay_restart.py tests/test_live_replay_restart_pg.py -x` | Wave 0 |
| OPS-02 | mixed-mode credentials refuse; `_FILE` form; per-service env allow-list (collector/paper get no `BINANCE_*`, live has its own bot token); redaction of live values; refusal holds and probe reports unhealthy | unit + compose-config test | `uv run pytest tests/test_live_config_refusal.py tests/test_live_compose_env_split.py -x` | Wave 0; attestation of no-withdrawal key + IP allow-list is human |
| OPS-03 | start sequence order and fail-closed behaviour; gate restore and first-install flag; startup recovery called; nothing placed before step 9; restart rehydrates (SAFE_MODE, intents, registry, gate) | integration (fakes) + `_pg` | `uv run pytest tests/test_live_start_sequence.py tests/test_live_restart_rehydrate.py -x` | Wave 0 |
| OPS-04 | `--healthcheck` and the health payload print the Python version and the revision stamp without git; Dockerfile carries the stamp | unit + docker | `uv run pytest tests/test_live_healthcheck.py tests/test_dockerfile_revision_stamp.py -x` | Wave 0 |
| D-05 / D-06 / D-15 | wiring gate: every criterion-1 link present; non-None drift guard; never-measured guard blocks `place_entry` before the SDK; ONE `RestRateLimitGate` shared; no retry wrapper or direct placement call under `src/live` | wiring + AST | `uv run pytest tests/test_live_wiring.py tests/test_live_ast_guards.py -x` | Wave 0 |
| Gate | traceability, invariants, amended Phase 18 invariants 2 and 5 | gate | `uv run pytest tests/test_phase24_gate.py tests/test_phase18_gate.py -x` | Wave 0 / amend |

### Sampling Rate
- **Per task commit:** the plan's own test file(s), `uv run ruff check <changed paths>`, `uv run mypy src/live <changed src>`. Subagents run their own tests only (AGENTS.md).
- **Per wave merge:** the quick run command above plus `tests/test_paper_shadow_isolation.py`, `tests/test_phase18_gate.py`, `tests/test_phase19_gate.py` to `tests/test_phase23_gate.py`.
- **Phase gate:** the orchestrator runs the full suite once (`-n 4`), then the recorded sequential gate before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/support/live_rig.py`: composition harness over `VirtualTime` (a real `asyncio.sleep` call must fail the test, as in `tests/test_protection_router_rig.py`).
- [ ] Fake-exchange extensions: `BinanceSemanticsFakeAdapter` implements orders, algo, positions, mark/last price, lot filters but NOT `server_time`, `user_commission_rate`, `account_*_snapshot`, `symbol_config_snapshot`, `leverage_brackets_snapshot`, `change_margin_type`, `change_initial_leverage`, `user_trades_in_window`, `income_in_window` [VERIFIED: method list of tests/support/fake_binance_exchange.py:462-826]; either extend it or add a facade over `tests/support/account_fakes.py`, `bracket_fakes.py`, `config_guard_fakes.py`, `day_risk_fakes.py`, `margin_guard_fakes.py`. Its kwargs are bound against the real adapter signature (09-REVIEW WR-12), so additions must match `BinanceUsdmAdapter`.
- [ ] A fake that lags `query_algo_order_by_client` after cancel (D-34) and a SDK-boundary test that converts `84816.40000000001` through the string/Decimal path.
- [ ] A user-data frame injector into the supervisor path (`tests/support/userdata_frames.py` and `tests/test_userdata_rig.py` are the starting points); SYNTHETIC frames only, labelled as such.
- [ ] A PTB update/bot fake for `on_callback` (reuse the patterns in `tests/test_confirm_flow.py` and `tests/test_approval_desk.py`); PTB `build_application` is never called in a unit test (its docstring).
- [ ] PG fixtures for restart tests (`tests/pg_support.py`; `TEST_DATABASE_URL` is read from the process environment only).
- [ ] Amend `tests/test_phase18_gate.py` (invariant 2 allows `src/live`; invariant 5 count if a key is added) and add `src.live` to the pure-module and wall-clock scans; extend the `tests/test_execution_manager.py` and `tests/test_binance_usdm_source_guard.py` guards (Pattern 7).
- [ ] Framework install: none.
- Manual-only (owner, recorded as NOT_OBSERVED until run): the `--execute` Demo smoke with recorded Demo order ids; VPS bootstrap rows; IP whitelist of the Demo key; second-Telegram-account unknown-user tap (G2-014); real heartbeat delivery; real host restart drill.

## Security Domain

`security_enforcement` is enabled (absent or true; ASVS level 1 per `.planning/config.json`).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Telegram: `authorized_user_ids` allow-list + private chat + authorized chat id in `on_callback`; exchange: API key/secret loaded by name only, `refuse_if_present` for the other mode |
| V3 Session Management | partial | one-time approval and confirm tokens (memory only, single use, bound to user id and plan hash, TTL); no web session |
| V4 Access Control | yes | operator commands only for allow-listed user ids; two-step confirm for anything that raises risk; ssh as the CLI control (20-DEFERRED D-15) |
| V5 Input Validation | yes | strict `parse_callback_data`; env parsing with named errors; exchange payloads parsed with typed models, never message text for decisions (D-10, source guard) |
| V6 Cryptography | yes | `src/approval/tokens.py` (`issue_one_time_token`, `token_hash_of`, `verify_token_hash`); never hand-roll |
| V7 Logging | yes | `src/ops/redaction.py`, class-name-only error logging, `register_runtime_secret` on load |
| V10/V14 Configuration | yes | per-service env allow-list, non-root UID 10001, secrets only via `env_file`, `.dockerignore` excludes `.env*` |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Another Telegram user or chat presses APPROVE/CONFIRM | Spoofing/Elevation | gate order in `on_callback`: chat id, private chat, user id allow-list, then token and confirm-entry bound to the approving user id |
| Replayed or redelivered callback after restart | Tampering/Repudiation | stored-outcome replay (`get_entry`), single-use tokens, `RUNTIME_RESTART` expiry, `_one_placement_per_symbol` |
| Credential mix-up (DEMO key in LIVE mode or LIVE key present in DEMO/paper) | Spoofing | D-02 `refuse_if_present`; paper refuses any `BINANCE_*`; env split (D-29) before any LIVE key enters `.env` |
| Secret in logs, journal, evidence or compose | Information disclosure | redactor, names-only messages, heartbeat URL by stdin only, no `.env` read |
| Fail-open on uncertain state (stale mark, unknown loss, DB down) | Elevation | NO_TRADE and SAFE_MODE paths; start sequence fail-closed |
| Duplicate order from a retry wrapper | Tampering | Q5 AST guards (Pattern 7), single `execute_approved_plan` call site |
| Event-loop starvation by sync DB/file I/O | Denial of service | `StoreExecutor`; bounded engine timeouts; reconcile overlap detection |
| REST ban (418) from an unshared holder | Denial of service | one shared gate with durable state; `GATE_NOT_RESTORED` fail-closed |
| Operator command abuse (SAFE_MODE exit, gate clear) | Elevation | allow-listed user ids, two-step confirm, journal row with operator id (audit, not authentication, until the allow-list lands) |

## Sources

### Primary (HIGH confidence)
- In-repo files opened this session (cited inline with path and line): `src/execution/{live_context,protection,manager,enablement,execution_limits,confirm_flow,confirm_recheck,approval_desk,intent_store,live_risk_inputs,emergency_close,intent_recovery,order_ids}.py`, `src/approval/{confirm_core,binding}.py`, `src/adapters/{binance_usdm,binance_client,binance_clock,binance_ratelimit_gate,binance_userdata,binance_userdata_router,binance_userdata_supervisor,binance_userdata_events,binance_public,telegram_callbacks,code_version}.py`, `src/reconcile/{loop,startup,sweeper,safe_mode,feed_freshness}.py`, `src/ops/{alerts,health,rest_gate_state,spill}.py`, `src/paper/{runtime,shadow_runtime,liveness}.py`, `src/persistence/{entities,risk_reservations,safe_mode_store,system_state}.py`, `config/execution/execution-limits-v1.toml`, `config/binance/binance-limits-v1.toml`, `docker-compose.yml`, `Dockerfile`, `.dockerignore`, `deploy/heartbeat.sh`, `tests/test_phase18_gate.py`, `tests/test_phase19_gate.py`, `tests/test_paper_shadow_isolation.py`, `tests/test_no_unratified_defaults.py`, `tests/test_binance_usdm_source_guard.py`, `tests/test_protection_router_rig.py`, `tests/support/*`; `docs/DECISIONS.md` rows D040, D041, D042, D083, D084 to D088; `.planning/{ROADMAP,STATE,WINDOWS}.md`; phase 20 `20-DEFERRED.md`, phase 24 `24-NOTES.md`, phase 9 `09-DEMO-REHEARSAL-FINDINGS.md`.
- Installed SDK `binance-sdk-derivatives-trading-usds-futures` 17.4.0 (`rest_api/api/account_api.py`, `rest_api/models/user_commission_rate_response.py`) and python-telegram-bot 22.8 (`telegram/error.py`).
- Local runs this session: `to_thread` ordering/cancellation probe; `gsd-tools query package-legitimacy check`; `classify-confidence`.

### Secondary (MEDIUM confidence)
- Binance USDS-M Futures user data streams page, `.md` form, read in full: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams.md
- Binance USDS-M Futures general info: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info.md
- Binance USDS-M Futures error codes: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/error-code.md
- Binance legacy docs (marked legacy by the site): https://developers.binance.com/legacy-docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate , .../trade/rest-api/New-Algo-Order , .../trade/rest-api/Cancel-Algo-Order
- python-telegram-bot docs via Context7 `/websites/python-telegram-bot_en_stable` (Application lifecycle, `add_error_handler`, `concurrent_updates`, `run_polling`): https://docs.python-telegram-bot.org/en/stable/telegram.ext.application.html
- Telegram Bot API getUpdates: https://core.telegram.org/bots/api#getupdates
- Python asyncio tasks: https://docs.python.org/3/library/asyncio-task.html

### Tertiary (LOW confidence; marked for validation)
- Search-engine summaries of a newer `/private/ws?listenKey=...&events=...` user-data URL form (third-party library note) — not on the official page read; D-16 defers it.
- The ccxt issue report that carries the 418 "IP banned until <epoch ms>" body (cited in 20-DEFERRED, not re-fetched here) — D083 stays UNVERIFIED on Futures.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH. No new dependency; versions read from `uv.lock`.
- Architecture: HIGH for the seams (read this session), MEDIUM for the recommended glue shapes (not yet built).
- Pitfalls: HIGH for those evidenced by code or a local run (P-1, P-2, P-4, P-7, P-8); MEDIUM for P-5, P-10 (documentation plus prior phase records).
- Official-doc facts: MEDIUM. Current REST pages were not renderable; user-data, general-info and error-code pages were read in `.md` form; REST endpoint shapes rest on legacy pages and the SDK.

**Research date:** 2026-10-30
**Valid until:** repository facts until the next commit touching the cited files; Binance/Telegram doc facts 7 days (fast-moving: the Binance SDK published new releases on 2026-10-29).

