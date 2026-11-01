# Phase 24: Live Runtime Composition + Demo Rehearsal - Context

**Gathered:** 2026-10-30
**Status:** Ready for planning (gathered with `--auto`, single pass; every decision is the recommended default and the owner may override it; items marked OWNER-OPEN must not be given a number by the planner)

<domain>
## Phase Boundary

Phase 24 composes the library-level pieces of Phases 16 to 23 into named, running processes and proves the result on Binance Demo Trading (demo-fapi.binance.com) before any real order. It builds the composition root(s), the Telegram bot runner (APPROVE → CONFIRM → `execute_approved_plan`, D041), the schedulers (reconcile, sweeper, health, protection step, clock-drift re-measure), the live risk-input producer (constraints, equity, daily loss, open algo count, commission rates), the user-data stream consumer feeding the protection coordinator, the startup recovery order, the Docker Compose `live` service with its heartbeat coverage, and the end-to-end Demo smoke (signal → approve → confirm → entry → fill → SL/TP → reconcile clean → SAFE_MODE drill → restart and rehydrate).

Out of scope (fixed by ROADMAP): the automated failure-scenario campaign and multi-week soak (Phase 25), the affirmative go-live gate, real backups, CI and mainnet canary (Phase 26), the configurable quote asset (Phase 27). Live placement stays disabled (`LIVE_ORDERS_DISABLED`); nothing here enables mainnet. Demo scripts with `--execute` are run by the owner only (AGENTS.md); the assistant builds them, tests them with fakes and records what the owner must run.

Requirements: APRV-01, EXEC-01, EXEC-02, EXEC-03, OPS-02, OPS-03, OPS-04. Evidence in this phase is tests with fakes plus owner-run Demo captures; no result is "demo-observed" until the owner runs it, and no claim of live readiness is made.

</domain>

<decisions>
## Implementation Decisions

All decisions below are the recommended option chosen in `--auto` mode. Every Binance and Telegram fact the plans rely on is re-read by the researcher from the current official pages, not taken from this file or memory. No limit value, interval or threshold is invented: keys that are `NOT_CONFIGURED` in `config/execution/execution-limits-v1.toml` stay so until the owner sets them (see Owner-open items).

### Process topology and entry point (criterion 4, D042)
- **D-01:** One live process, `python -m src.live.runtime` (new package `src/live/`), runs a single asyncio event loop with these tasks: Telegram bot runner, user-data stream supervisor + router, protection coordinator stepper, reconcile loop, sweeper, health scheduler, clock-drift re-measure, live risk-input refresh. It replaces the `live` placeholder service in `docker-compose.yml` (profile `live`, restart policy `unless-stopped` only after the owner confirms the Demo mode flag; `restart: "no"` stays until then). The paper/SHADOW runtime (`src/paper/runtime.py`) and the collector stay separate processes; the live process never imports `src.paper.runtime`. — **Reversibility:** costly — the process boundary fixes the compose service, the heartbeat probe and the env allow-list; splitting later means moving state across processes.
- **D-02:** The runtime has an explicit mode value `DEMO` or `LIVE` read from configuration, never inferred from the base URL alone. Phase 24 builds and runs only `DEMO`. `LIVE` is constructible only through `LiveEnablementController`; a `LIVE` mode with `LIVE_ORDERS_DISABLED` refuses to start. The mode is journaled at startup and shown in every operator message. The paper runtime's rule is mirrored: the live process refuses to start if the credential names for the other mode are present (`BINANCE_DEMO_*` vs `BINANCE_LIVE_*`). — **Reversibility:** reversible — a validated config field and a start-up check.
- **D-03:** CLI shape mirrors `src/paper/runtime.py` (`--healthcheck`, `--liveness`, `--hold-on-refusal`) so the compose probe, the heartbeat and the runbook drills use the same verbs. A refusal at start holds (does not crash-loop) and is visible to the heartbeat as unhealthy. — **Reversibility:** reversible.

### Composition root structure and wiring tests (criterion 1, F-201, F-956)
- **D-04:** A single composition module builds every object from explicit constructor arguments (clock, stores, adapter, gate, sinks, limits) and returns one `LiveWiring` value; `main()` only reads env, calls it, and runs `run_admitted`. No module outside `src/live/` constructs a live adapter, a coordinator, a sink or a scheduler. The pure layers (`src/core`, `src/risk`, `src/domain`) import nothing from `src/live/`. — **Reversibility:** costly — every later composition test and the runbook refer to this seam.
- **D-05:** A wiring test (the Phase 24 gate) fails the build when any link named in ROADMAP criterion 1 has no production caller: approval request sender, bot runner, execution service, reconcile, sweeper, health scheduler, risk-input producer, kill-gate event → `enable()`. The test inspects the built `LiveWiring` (types and presence), not source text, and a second AST guard keeps the Q5 rule: no retry wrapper around `place_entry`, `place_algo_protective` or `place_market_close` anywhere under `src/live/` (existing guards in `tests/test_execution_manager.py` and `tests/test_binance_usdm_source_guard.py` stay green and are extended to the new package). — **Reversibility:** reversible — tests.
- **D-06:** Clock-drift guard (24-NOTES item 1): the composition builds `ClockDriftGuard` from the ratified `drift.*` limits, passes it with the clock to `BinanceUsdmAdapter`, and schedules `drift.periodic_remeasure_interval_seconds`. Acceptance tests: the built adapter has a non-None guard; a never-measured guard blocks `place_entry` before any SDK call; a composition passing `None` fails a test. — **Reversibility:** reversible.
- **D-07:** Alert path (24-NOTES item 5): the real `JournalFirstAlertSink` (Phase 20) with the Phase 23 formatters and `TelegramAlertSender.drain()` is passed to `SafeModeController(on_enter=SafeModeAlertObserver(sink))`, `LivePlacementContext.alert_sink`, the protection coordinator, the REST gate `on_alert`, and the daily-state alert producers (`emit_daily_state_alert`). The rehearsal sink is rejected by the wiring test. The real `EmergencyCloser` is passed to the coordinator. — **Reversibility:** reversible.

### Startup order, recovery and rehydrate (criterion 2 restart, G4-029)
- **D-08:** Start sequence, each step fail-closed (a failure holds the process in SAFE_MODE with entries blocked and monitoring running; nothing places an order until the sequence completes): (1) validate env and mode, refuse mixed credentials; (2) REST gate: run `FileGateStateStore.initialize` on the first install only (explicit flag, never silently), then load the persisted gate state; (3) Alembic head check (read-only, never `create_all`); (4) load SAFE_MODE and system state from the store (durable, D-14 of Phase 20) and the constraint snapshots; (5) clock-drift measure; (6) exchange info and lot-filter refresh; (7) `run_startup_recovery` (plan 20-19) which rebuilds the coordinator and closer and calls `resolve_unresolved_intents` (an acknowledged ENTRY with a rejected or absent STOP_LOSS intent is resolved by the 20-10 UNKNOWN-entry protocol; a probe "not found" never closes an entry as REJECTED, D080); (8) one full reconcile pass; (9) only then start the user-data stream, the bot runner and the schedulers. — **Reversibility:** costly — the order is the safety argument and drills pin it. **Amended 2026-11-01 by D094 (plan 24-37):** the user-data stream starts before the reconcile tick (steps 8 and 9 swap for the stream); every other step and the fail-closed rule are unchanged.
- **D-09:** Restart mid-flow (criterion 3): outstanding confirms expire with reason `RUNTIME_RESTART` (Phase 23 D-09); an APPROVED-but-not-confirmed plan stays approved until its expiry and needs a fresh CONFIRM; an entry already sent with an unknown result is UNKNOWN + SAFE_MODE; a resting entry and its `RestingEntry` registry record are rebuilt from the store. A replayed APPROVE, CONFIRM or CANCEL callback after restart answers from the stored decision and changes nothing. — **Reversibility:** reversible.
- **D-10:** Positions table, fills ledger and `Order` rows with `update_position_snapshot` and the exchange event-time column (G4-043, 20-DEFERRED D-13, D-29) are built here as the persistence the stream feeds: monotonic updates keyed by exchange event time, one Alembic migration, evidence rows kept as today. The D-01a reconcile bound check stays a bound check; the exact signed-quantity compare becomes possible and is added only if the owner asks (OWNER-OPEN O-5). — **Reversibility:** costly — a migration and a new table family other phases will read.

### Schedulers and cadence (criterion 1; T-06)
- **D-11:** One small scheduler primitive (named task, injected clock and sleep, bounded jitter-free cadence read from limits, per-task last-run and last-error recorded to the journal, a task exception never kills the loop but raises the matching health result) drives: protection coordinator step, reconcile loop tick, sweeper, health checks, drift re-measure, bracket/commission/lot-filter refresh, scheduled cancel of unfilled entries at plan expiry. The primitive contains no wall clock call (AST guard). — **Reversibility:** reversible.
- **D-12:** Cadence values (reconcile interval, stale-feed threshold, WS-silence threshold, equity age, bracket age, protection step interval) are read from `execution-limits` / registry keys that are `NOT_CONFIGURED` today. A required key left `NOT_CONFIGURED` makes `main()` refuse to start in `DEMO` unless the owner supplies a value (OWNER-OPEN O-1). The plan lists every such key and the owner supplies the numbers in one checkpoint; nothing is defaulted from memory. — **Reversibility:** reversible — config values.
- **D-13:** Scheduled cancel of an unfilled entry at plan expiry (20-DEFERRED) is a scheduler task that cancels only with zero fills on the exchange (REST read first) and routes anything else to the coordinator; it follows the WR-07/G2-026 rule that protective legs are never cancelled while a fill may exist. The second-plan-per-symbol refusal and the D028 approval chain are enforced at the approval request sender, not in the scheduler. — **Reversibility:** reversible.

### User-data stream to protection, fills and risk (criterion 2 fill via stream, 24-NOTES item 4)
- **D-14:** The Phase 18 router is the only consumer of the user-data stream. Its handlers are registered by the composition root: order/fill events → `ProtectionRegistry` and coordinator input (a fill leads to a REST-confirmed stop without any manual call, tested with the Binance-semantics fake exchange); fills and `ACCOUNT_UPDATE` → `LiveEquitySource` invalidation and the daily-loss service (Phase 21 stream path); listen-key keepalive and reconnect stay in the supervisor. The stream is evidence and a trigger, REST is the truth (Phase 21 D-01 pattern); a gap or silence beyond the (OWNER-OPEN) threshold raises the stale-stream health result and SAFE_MODE per Phase 20. — **Reversibility:** costly — handler registration order and event shapes are pinned by Phase 18 and Phase 20 tests.
- **D-15:** Every REST holder inside the live process takes the one shared `RestRateLimitGate` (24-NOTES item 3): the signed adapter, public market data, listen-key port, probe adapter, supervisor, the live risk-input producer, bracket and commission readers. A test constructs the process and asserts one gate instance; a 418 from any holder blocks the rest. The data jobs, the paper runtime and the two scripts stay outside by design (different processes) and are recorded in `tests/test_phase18_gate.py` as such. The supervisor's `_await_rest_allowed` wiring to `GateRestriction.remaining_seconds` and the D083 -1003 ban-end parsing are built here; the clock-margin key stays `NOT_CONFIGURED` (D083 condition, OWNER-OPEN O-1). — **Reversibility:** reversible.
- **D-16:** The direct `/private` URL form (24-NOTES item 2) is not changed here: the SDK stays the transport. The Demo smoke records the connection URL form once for Phase 25. — **Reversibility:** reversible.

### Telegram runner and the approval path (criterion 1 and 3, APRV-01, D041, P23-R1)
- **D-17:** The runner composes the Telegram path only through `on_callback` (the user-id gate lives there); `dispatch_callback` is never called with `authorized_user_ids` omitted, and a wiring test fails if the runner's handler is anything else. `on_confirmed` of the shared confirm core (Phase 23 D-09) is the single seam connected to `execute_approved_plan` via the `ExecutionManager`; no `src.execution` import enters the confirm core. Pre-placement checks at CONFIRM use the Phase 23 `confirm_recheck` callable fed fresh REST/mark inputs. — **Reversibility:** reversible — the seam was designed for this.
- **D-18:** The approval request sender is the one place that creates the approval card for DEMO: it runs the second-plan-per-symbol refusal, the D028 chain, risk reservation (Phase 21, atomic in the approval transaction) and stores the money block with the approval (Phase 23 D-13). `notify` failures never auto-approve (APRV-02). — **Reversibility:** reversible.
- **D-19:** P23-R1 / SHADOW money block: this phase stores a money block with SHADOW approvals and renders it in the SHADOW alert, deliberately changing the SHADOW text pins. Coordinate first: read `.planning/phases/16-paper-runtime-composition/` soak evidence; if a Phase 16 soak is in progress or its evidence pins the SHADOW text, the change ships behind a new text version with the old pins kept, and the planner raises it as an owner checkpoint (OWNER-OPEN O-6) before editing. — **Reversibility:** costly — SHADOW text pins and soak evidence.
- **D-20:** Replay and restart safety (criterion 3) is tested at two levels: fakes (replayed APPROVE/CONFIRM/CANCEL, a restart between APPROVE and CONFIRM, a restart between CONFIRM and the `place_entry` result, two concurrent CONFIRMs on two connections) with an assertion of exactly zero or one `place_entry` call; and on Demo (owner-run) with recorded client order ids. The unknown-chat/other-user rejection check (G2-014) is an owner live check that needs a second Telegram account. — **Reversibility:** reversible.

### Live risk-input producer (criterion 1, G3-008, G2-042)
- **D-21:** One producer assembles, per plan, from REST truth: the symbol constraint snapshot (Phase 22 `SymbolConfigGuard` margin type, leverage, `isAutoAddMargin`, brackets via `BracketCache`), equity (`LiveEquitySource`), daily-loss state (`LiveDayRiskService`), open positions including resting and approved plans (Phase 21 reservation), open algo order count against the 200 headroom, and per-symbol commission rates. It calls the pure `build_live_risk_inputs` and returns either a complete input or a refusal reason; any missing or stale input is NO_TRADE (fail closed). Backtest/paper parity tests from Phases 21 and 22 stay green. — **Reversibility:** costly — the producer's output type is read by the gates, the approval card and the liquidation watch.
- **D-22:** Commission wiring (G3-008, G3-014): per-symbol maker and taker rates come from the official commission-rate endpoint through a refresh task and cache, fed to `resolve_live_cost_rates`; a missing, stale or negative maker rate fails closed (Phase 12 IN-01), and the `assert`-based invariants (IN-05) become explicit raises. The researcher re-reads the official page (MEDIUM confidence) and the Demo behaviour is recorded by the owner run. — **Reversibility:** reversible.
- **D-23:** G2-042: the `realizedPnl` vs commission semantics are verified against the current Binance docs and one Demo fill, the citation is recorded, and `LIVE_NET_PNL_SEMANTICS_VERIFIED` is set only by a code change that names the evidence file; if the Demo sample is ambiguous the flag stays False and live R stays INCOMPLETE (no guess). Setting the flag needs the owner's DECISIONS row (OWNER-OPEN O-4). The Phase 22 flag `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` is handled the same way. — **Reversibility:** reversible.
- **D-24:** Post-fill liquidation watch (Phase 22) is activated by the user-data fill handler. The behaviour after a failed post-fill check (close or alert) is OWNER-OPEN O-3; until decided the default is alert + SAFE_MODE, no automatic close. — **Reversibility:** reversible.

### Database access on the event loop (G4-040, P16R-03)
- **D-25:** Decision recorded in the plan and in `docs/DECISIONS.md` (new row, assistant proposes, owner ratifies): the sync PostgreSQL stores stay sync; the live process wraps every store call that runs on the event loop in `asyncio.to_thread` through one `StoreExecutor` seam, with a bounded single worker for write calls that need ordering (the ledger-lock rule). `ShadowConfirm.expire_due` on the loop (P16R-03) is moved behind the same seam in the paper runtime in the same plan, with the Phase 16 behaviour pinned by its existing tests. An async pool is rejected for now (new dependency, no measured need). — **Reversibility:** costly — the seam is used by every live store call.

### Health, DEGRADED, mark-price gate and enablement (D056, D058, kill-gate)
- **D-26:** Health producers are built: each long-running task reports a `HealthCheckResult` (feed freshness, user-data stream state, REST error rate, reconcile drift, db writes, telegram delivery, unprotected positions, orphaned orders). D056: a producer for DEGRADED and an explicit mode are designed here with Phase 26: in `LIVE` a DEGRADED state cannot enable any order-capable capability and blocks new entries once enabled; in `DEMO` the process may continue DEGRADED only with an explicit `DEMO` mode flag that journals the health state and can never switch to `LIVE`. The `health.py` "unchanged policy" comment is replaced and `tests` pin both rows. — **Reversibility:** costly — changes a documented policy other tests pin.
- **D-27:** D058: the mark-price source (stream with REST fallback) has a freshness bound (OWNER-OPEN O-1); a missing or stale price refuses entry and refuses `enable()`, and a stale price while enabled is an invalid state that moves to SAFE_MODE. — **Reversibility:** reversible.
- **D-28:** Kill-gate event → `enable()`: the analytics kill-gate verdict (`src/analytics`) is the only automated trigger that may call `LiveEnablementController` toward disable; enabling is never automatic — it needs an operator action with an `operator_id` on the allow-list. Operator authentication (20-DEFERRED D-15) is resolved by reusing the Phase 23 authorized user ids for Telegram commands; ssh remains the access control for CLI controls. Demo mode needs no enable() for placement beyond the DEMO mode flag; the controller is still composed and exercised in the smoke. — **Reversibility:** reversible.

### Deployment, heartbeat, credentials (criterion 4; WR-06, T-02, 16-50, G3-033)
- **D-29:** WR-06: the shared `env_file` is split per service with an allow-list (`live` gets `BINANCE_DEMO_*` / `BINANCE_LIVE_*`, Telegram and DB values only; collector and paper get none of the Binance names), with the cutover test and drills re-run, before any real `BINANCE_LIVE_API_*` key enters `.env`. WR-05 stays as implemented (D062); the D064 CR-01 replacement is implemented before the first bootstrap and real backup. — **Reversibility:** costly — compose, deploy scripts and the cutover test all pin the layout.
- **D-30:** The healthchecks.io heartbeat (16-50, Phase 16 decision O-12) is extended so one sender covers every long-running process: collector, paper (when running), live. Each process exposes `--healthcheck`; the heartbeat posts only when all required probes pass, and the live probe checks the process liveness stamp plus the latest scheduler results. The interval and grace remain OWNER-OPEN (O-1/O-12). Heartbeat URLs go in by stdin only. — **Reversibility:** reversible.
- **D-31:** OPS-04: `--healthcheck` output and the health payload include the runtime Python version and the application git revision (`src/adapters/code_version.py`). — **Reversibility:** reversible.
- **D-32:** VPS and Demo key: building the VPS with `deploy/bootstrap.sh`, executing RUNBOOK sections 13 and 17 "real host" rows, the systemd backup timer firing, one real `migrate.sh`, and IP-whitelisting the Demo key to the VPS address are owner-run steps. The plan provides the checklist and evidence template; the assistant never runs host commands or reads `.env`. — **Reversibility:** reversible.

### Demo rehearsal (criterion 2, 5)
- **D-33:** The end-to-end smoke extends `scripts/demo_rehearsal.py` so it drives the composed process instead of stepping the coordinator by hand: signal → approve → confirm → GTD LIMIT entry (no entry-time stop, D079) → fill seen on the user-data stream → REST-confirmed stop → TP1/TP2 (D-21 makes `snapshot_is_valid_for_live` hold with real data) → reconcile clean → SAFE_MODE drill (enter, verify entries blocked, operator exit) → restart and rehydrate → replayed callbacks. Output records Demo order ids and client order ids; it is run by the owner with `--execute`. The blocked 09-04 rehearsal is closed by this run. — **Reversibility:** reversible.
- **D-34:** Criterion 5 findings are carried as test and review items: a `closePosition=true` stop before a fill is -4509 (already the D079 model); `query_algo_order_by_client` still reports `NEW` for about a second after cancel, so reconciler and sweeper must treat "cancel sent, open list empty" as success (a test with a fake that lags); the `entry_price` float noise (`84816.40000000001`) is checked at the SDK boundary and converted through the string/Decimal path with a test; the adapter's market-order/close helper question is already answered by `place_market_close` (Phase 19). — **Reversibility:** reversible.

### Inherited-item triage
- **D-35:** Folded into plans: G4-029, G4-034 (journal evidence source on exits from UNKNOWN), G4-043, G2-019 (duplicate client ids and skipped sweeper cancels surfaced), T-04, T-05 (alerts for duplicate execution attempt, rejected protective action, daily-loss WARNING), T-06 (values via D-12), G3-005 (promote `NO_FILL` and `HEALTH_CHECK_FAILED`, update GLOSSARY 9.3 and the Phase 21 gate invariant in the same change), G2-035 (triage each of IN-01/05/06/07 to fix or a won't-fix note), P20-GATE-WIRING, P20-DEFERRED, G4-040/P16R-03 (D-25), the coordinator notification of a `RECONCILED_ABSENT` entry (20-DEFERRED). G3-033 and G2-014 are owner checks. T-02 WR-06 half is D-29; the disk-encryption half stays with Phase 26. — **Reversibility:** reversible.

### Claude's Discretion
- Package layout inside `src/live/` and module names; the scheduler primitive's API; whether risk inputs are one class or several; the migration split for D-10; golden-text details of new formatters (following Phase 23 style); how the smoke script is parameterised.
- Test composition: which fakes to extend (the Binance-semantics fake exchange is the default), provided the Q5 and drift-guard acceptance tests exist.

</decisions>

<owner_open>
## Owner-open items (do not implement with a number until the owner decides)

- **O-1:** Values for every required `NOT_CONFIGURED` key: reconcile cadence, stale-feed and WS-silence thresholds, equity age (`account.max_equity_age_ms`), mark-price freshness, bracket age and margin headroom, clock margin for D083, heartbeat interval and grace, protection step cadence. Phase 22 O-1 (target leverage), O-2 (liquidation buffer) remain as recorded in `22-CONTEXT.md`.
- **O-2:** Enabling `restart: unless-stopped` for the live service (default `restart: "no"` until the first clean Demo run).
- **O-3:** Close or alert after a failed post-fill liquidation check (Phase 22 O-4); default alert + SAFE_MODE.
- **O-4:** DECISIONS rows to set `LIVE_NET_PNL_SEMANTICS_VERIFIED` and `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED`.
- **O-5:** Whether to add an exact signed-quantity position compare once Order and fill rows exist (D-01a is accepted as a bound check).
- **O-6:** SHADOW money-block text change if a Phase 16 soak is running or pins the text (D-19).
- **O-7:** Ratify the `docs/DECISIONS.md` row proposed for G4-040 (D-25) and the D056 DEGRADED mode (D-26).

</owner_open>

<research_reconciliation>
## Research reconciliation (2026-10-30, from 24-RESEARCH.md; verified against docs/DECISIONS.md)

Where this section and a decision above disagree, this section wins. These are recommended defaults, still overridable by the owner.

- **R-1 (supersedes D-12 values, D-23, D-24):** D084, D085, D086 and D087 already fix equity age (15000 ms), bracket age, headroom, daily-loss age, target leverage 5 ISOLATED, liquidation buffer 300 bps, `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` True, and `CLOSE_POSITION` for a failed post-fill liquidation check. `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False until the Phase 26 canary (D086). Composition passes these; it does not re-ask them. Only the keys still `NOT_CONFIGURED` (listed in 24-RESEARCH "Limit keys") stay owner-open (O-1).
- **R-2 (refines D-17):** `on_confirmed` is a synchronous hook and cannot await `execute_approved_plan`; it also gets no raw approval token. Build an `ExecutionService` that schedules the async placement from the hook (`run_coroutine_threadsafe` if the confirm core runs on a worker thread) and add the token accessor to `ApprovalDesk`. Still exactly one `place_entry` per approval.
- **R-3 (refines D-28):** DEMO enablement is an in-process `enable()` after the start sequence, as the rehearsal does; the health probes that describe a market feed the live process does not own are fed by a live-process feed source or scoped out by an explicit DEMO rule (owner-confirm, OQ-3).
- **R-4 (adds to D-33):** SAFE_MODE operator exit cannot be a separate CLI; it is an in-process Telegram command channel (owner-confirmed 2026-10-23). Minimal operator commands are in scope (OQ-5).
- **R-5 (adds):** Signal/TradePlan source for the live process (OQ-2), a second Telegram bot token for DEMO (one getUpdates consumer per token, OQ-4), and one database per confirm mode (OQ-6) are owner checkpoints; the planner proposes a recommended default for each and gates the dependent tasks behind a checkpoint.
- **R-6 (adds to D-29, D-31):** deployment fixes are in scope: copy `config/execution` and `config/binance` into the image, and a build-time revision stamp for OPS-04 (`.git` is dockerignored).
- **R-7 (refines D-10):** Order, Fill and Position repositories already exist (Phase 17); new work is the event-time column with a monotonic guard, `update_position_snapshot`, production writers; next migration is 0015, next DECISIONS id D089.
- **R-8 (refines D-30):** heartbeat stays one external check per target; add `--target live` rather than a single multiplexed sender.
- **R-9:** tests that will break and must be amended in the same plans: `test_phase18_gate` invariants 2 and 5, `test_paper_shadow_isolation` (forces `StoreExecutor` into `src/ops`), `test_deploy_compose`, `test_deploy_images`.

</research_reconciliation>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Rules and decisions
- `AGENTS.md` — operating rules: no push/merge, secrets, fail closed, execution model since Phase 19
- `docs/DECISIONS.md` — D040 (release path), D041 (two-step confirm), D042 (single VPS), D055/D079 (stop after fill), D056 (DEGRADED), D058 (mark-price gate), D062/D064 (WR-05, CR-01), D080 (placement never re-sent), D083 (-1003 ban end)
- `docs/DOC_STATUS.md` — index of canonical docs
- `docs/operations/RUNBOOK.md` — sections 13 and 17 (host rows), drills, SAFE_MODE exit
- `docs/integration/TELEGRAM.md` — token trust model, callback behaviour
- `docs/trading/RISK_MANAGEMENT.md` — quantization and risk sections
- `.planning/ROADMAP.md` — Phase 24 section and inherited items
- `.planning/REQUIREMENTS.md` — APRV-01, EXEC-01..03, OPS-02..04, OPS-06
- `.planning/WINDOWS.md` — what cannot be verified on the dev machine

### Phase inputs
- `.planning/phases/24-live-runtime-composition-demo/24-NOTES.md` — clock-drift guard, /private URL, REST gate coverage, protection driver, sinks, TP inputs
- `.planning/phases/20-reconcile-safe-mode-hardening/20-DEFERRED.md` — about 30 deferred items and composition gaps
- `.planning/phases/20-reconcile-safe-mode-hardening/20-CONTEXT.md` — reconcile, SAFE_MODE, alert sink decisions
- `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md` — execution gaps and Demo captures
- `.planning/phases/21-account-equity-daily-loss/21-OWNER-DECISIONS.md`, `21-DEFERRED.md`, `21-CONTEXT.md`
- `.planning/phases/22-leverage-margin-liquidation-guard/22-CONTEXT.md`, `22-DEMO-RESULTS.md`
- `.planning/phases/23-telegram-approval-hardening-money/23-CONTEXT.md`, `23-VERIFICATION.md` (R-1), `23-OWNER-CHECKS.md`
- `.planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md` — WR-06 env split
- `.planning/phases/09-live-execution-rollout/09-DEMO-REHEARSAL-FINDINGS.md` — blocked 09-04 rehearsal
- `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-12.md`, `deferred-items.md` — heartbeat and P16R items

### Configuration
- `config/execution/execution-limits-v1.toml` — the `NOT_CONFIGURED` keys
- `docker-compose.yml` — `live` placeholder, env_file, profiles

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/execution/live_context.py` (`LivePlacementContext`), `protection.py` (coordinator, `RestingEntry`), `protection_rebuild.py`, `emergency_close.py`, `enablement.py` (`LiveEnablementController`): the execution side to be composed.
- `src/execution/live_risk_inputs.py`, `day_risk_service.py`, `account_equity.py`, `margin_guard.py`, `symbol_config_guard.py`, `bracket_cache.py`, `liquidation_watch.py`, `constraint_snapshot.py`: Phase 21 and 22 library level, no process composes them.
- `src/approval/confirm_core.py`, `src/execution/confirm_flow.py`, `confirm_recheck.py`, `src/adapters/telegram_callbacks.py` (`on_callback`): Phase 23 confirm and user-id gate.
- `src/adapters/binance_usdm.py`, `binance_clock.py` (`ClockDriftGuard`), `binance_ratelimit_gate.py`, `binance_userdata_{supervisor,router,events}.py`: adapter, gate and stream.
- `src/reconcile/{loop,startup,sweeper,safe_mode}.py`, `src/ops/{alerts,health,rest_gate_state,spill}.py`: reconcile, alerts, health, gate state store.
- `src/paper/runtime.py`: the pattern for CLI flags, admission, hold-on-refusal, liveness stamp and `run_admitted`.
- `scripts/demo_rehearsal.py`, `scripts/demo_probe.py`, `deploy/heartbeat.sh`, `deploy/systemd/`: rehearsal, probe and heartbeat to extend.

### Established Patterns
- Pure cores take injected clocks and callables; adapters hide SDK types; mutating signed calls are single-shot (Q5).
- Every limit has a provenance label and a `NOT_CONFIGURED` fail-closed default; owner supplies values.
- AST guards in `tests/support/ast_guards.py` (no wall clock, no float, `src/core` purity) and the signed-call registry (`tests/test_binance_usdm_signed_calls.py`).
- Golden-text tests for operator messages; generated fixtures only via the `gen_phase*_fixtures.py` scripts.

### Integration Points
- New `src/live/` package consumed by compose `live` service and `deploy/heartbeat.sh`.
- Router handlers register into the Phase 18 router; protection registry, equity source and daily-loss service are the subscribers.
- `ExecutionManager.execute_approved_plan` is the only placement entry, reached only from the confirm core's `on_confirmed`.
- New Alembic migration(s) for positions/fills/orders (D-10) and any approval money-block carrier changes.

</code_context>

<specifics>
## Specific Ideas

- The owner has little domain knowledge and asked the assistant to choose (as in Phases 21 to 23): present each owner checkpoint with a recommended value and the reason, in plain words.
- Demo proof must show recorded Demo order ids; "tests pass with fakes" is not Demo evidence.
- Keep the process observable: every scheduler task and startup step writes a journal event so a failed rehearsal can be diagnosed from the journal alone.

</specifics>

<deferred>
## Deferred Ideas

- Direct (non-SDK) `/private` user-data transport — only after Phase 25 captures the URL form.
- Failure-scenario campaign, multi-week Demo soak — Phase 25.
- Enablement gate, real backups, CI, mainnet read-only check, canary, disk encryption — Phase 26.
- USDC / configurable quote asset — Phase 27.
- Async PostgreSQL pool — only if the `to_thread` seam measures as insufficient.
- Local-time display in Telegram (owner preference) — later.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 24-live-runtime-composition-demo*
*Context gathered: 2026-10-30*
