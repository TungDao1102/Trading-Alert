---
last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
last_mapped_at: 2026-10-19
---
- ---
- last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
- last_mapped_at: 2026-10-19
- ---
- <!-- refreshed: 2026-10-19 -->

# Architecture

- **Analysis Date:** 2026-10-19

## System Overview

- **External systems:** Binance USDⓈ-M Futures (REST /fapi/*, WS Streams, user-data WS), Telegram Bot API, PostgreSQL 17.
- **Adapter boundary (src/adapters/):** inance_public, inance_usdm, paper_ws, inance_userdata*, 	elegram_notify, 	elegram_callbacks, nalytics_files/nalytics_store. SDK response models NEVER leave this layer.
- **Pure deterministic core:** src/core/ (features, strategy, planner), src/domain/ (entities + registry), src/risk/ (sizing + quantization), src/backtest/ (closed-candle simulator) — stdlib + Decimal only.
- **Runtime / orchestration:** src/paper/runtime.py (one asyncio loop, 1 queue + 1 consumer task), src/execution/manager.py, src/approval/ (tokens/replay), src/reconcile/ (compare/sweep), src/ops/ (backup/health).
- **Persistence:** src/persistence/ (sync SQLAlchemy) + src/db/ (ORM + Alembic); src/data/store.py (immutable Hive Parquet).
- **Offline analysis & governance:** src/analytics/ (metrics + kill-gate report, src/analytics/cli.py edge), src/research/ (manifest, register, multiplicity, authorization, settlement).

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `src/core/features.py` | Deterministic feature computation (ATR, EMA20/50/200, swing hi/lo, zone bounds, validity reasons) | `src/core/features.py` |
| `src/core/strategy.py` | Family dispatch (trend-pullback / breakout-retest / range-mr) → `NO_TRADE` or `SETUP(Signal)`; regime + setup gates | `src/core/strategy.py` |
| `src/core/planner.py` | Signal + candles → `TradePlan` (entry zone, SL, TP1/TP2, expiry, invalidation, plan_hash) | `src/core/planner.py` |
| `src/core/pivots.py` | Confirmed fractal pivots (left/right width) shared by regime and setup detectors | `src/core/pivots.py` |
| `src/core/_decimal.py` | Pinned-precision Decimal arithmetic helpers (`_add`, `_sub`, `_mul`, `_div`, `_q`) | `src/core/_decimal.py` |
| `src/domain/enums.py` | GLOSSARY-canonical enums (SignalStatus, TradePlanStatus, OrderStatus, RejectionReason, SystemMode…) | `src/domain/enums.py` |
| `src/domain/registry.py` | Versioned TOML parameter registry: load, hash, verify; fail-closed on unknown keys | `src/domain/registry.py` |
| `src/domain/canonical.py` | Canonical JSON + SHA-256 (`sha256_hex`) — the hashing primitive of every identity | `src/domain/canonical.py` |
| `src/domain/ids.py` | Content-hash IDs: `make_signal_id`, `derive_child_id` (plan/order IDs) | `src/domain/ids.py` |
| `src/domain/signal.py`, `trade_plan.py`, `order.py`, `position.py`, `fill.py`, `approval.py`, `journal.py` | Separate lifecycle entities (D007: signal ≠ plan ≠ order ≠ position) | `src/domain/` |
| `src/risk/gating.py` | `size_and_quantize` + `evaluate_risk` — the single shared risk pipeline for backtest/paper/live | `src/risk/gating.py` |
| `src/risk/quantization.py` | Floor-to-stepSize, then min-qty → min-notional → 60% utilization gate, in that fixed order | `src/risk/quantization.py` |
| `src/risk/portfolio.py` | Portfolio caps, cluster cap, daily-loss state machine (`DAILY_STOP`) | `src/risk/portfolio.py` |
| `src/risk/cost_guards.py`, `cost_rates.py` | Cost model, cost-to-risk ceiling, min stop distance, commission TTL | `src/risk/cost_guards.py` |
| `src/backtest/engine.py` | Project-owned closed-candle simulator (fees, funding, mark-price triggers, intrabar tie-breaks) | `src/backtest/engine.py` |
| `src/backtest/simulator.py` | Thin public entry: `run(case_input)` → `engine.simulate(case_input, risk_fn=evaluate_risk)` | `src/backtest/simulator.py` |
| `src/paper/runtime.py` | Paper process entrypoint: start gate → admission → config → instance lease → epoch pin → loop | `src/paper/runtime.py` |
| `src/paper/pipeline.py` | `BarPipeline.handle` — closed-candle gate, warm-up, history continuity, evaluation order | `src/paper/pipeline.py` |
| `src/paper/loop.py` | Pure paper dispatch; the realtime mirror of the backtest simulator (identical call chain) | `src/paper/loop.py` |
| `src/paper/freeze.py` | Allowlist / epoch pin / parameter-set validation gate | `src/paper/freeze.py` |
| `src/execution/manager.py` | approve → binding → risk → intent → place; the only component allowed to place orders | `src/execution/manager.py` |
| `src/execution/gates.py` | Placement-time revalidation: live constraints, portfolio caps, DAILY_STOP, headroom, enablement | `src/execution/gates.py` |
| `src/execution/intent_store.py` | `ExecutionIntentStore` Protocol — the exactly-once guard for entry and protective legs | `src/execution/intent_store.py` |
| `src/approval/tokens.py` | One-time token issue/hash/constant-time verify (stdlib only) | `src/approval/tokens.py` |
| `src/approval/binding.py` | Fixed-order callback gate: chat → expiry → plan-hash → version → token-hash | `src/approval/binding.py` |
| `src/approval/replay.py` | At-least-once replay resolution: 1 press = 1 transition, 5 replays = 1 transition | `src/approval/replay.py` |
| `src/reconcile/compare.py` | Exchange-vs-local state diff (orphan protectives, position divergence) | `src/reconcile/compare.py` |
| `src/reconcile/sweeper.py` | Cancels orphan protectives; two consecutive zero position reads required | `src/reconcile/sweeper.py` |
| `src/reconcile/safe_mode.py` | SAFE_MODE transitions (entries blocked, monitoring continues) | `src/reconcile/safe_mode.py` |
| `src/persistence/` | Synchronous SQLAlchemy stores: journal, approvals, execution state, runtime state, shadow stores, system state, UoW | `src/persistence/` |
| `src/db/models.py`, `mappers.py` | ORM tables and the domain↔row mappers (`src/db/mappers.py` is Decimal-only) | `src/db/models.py` |
| `src/adapters/binance_public.py` | Credential-free public market data (klines, mark klines, OI, funding, server time, exchangeInfo) | `src/adapters/binance_public.py` |
| `src/adapters/binance_usdm.py` | The ONLY module importing the Binance SDK for order/account surfaces | `src/adapters/binance_usdm.py` |
| `src/adapters/paper_ws.py` | WebSocket market-data adapter behind a project-owned interface | `src/adapters/paper_ws.py` |
| `src/adapters/binance_userdata*.py` | User-data stream: event parsing, router, supervisor, listen-key handling | `src/adapters/binance_userdata_events.py` |
| `src/adapters/telegram_notify.py` / `telegram_callbacks.py` | The only modules importing `python-telegram-bot` | `src/adapters/telegram_notify.py` |
| `src/data/collector.py` | 5-minute OI poll + funding sweep + opportunistic harvest; gap journal, never fabricated | `src/data/collector.py` |
| `src/data/store.py` | Immutable Hive-partitioned Parquet publish with atomic `os.replace` | `src/data/store.py` |
| `src/analytics/` | Pure metrics, kill-gate, slices, report and render; `src/analytics/cli.py` is the single edge | `src/analytics/report.py` |
| `src/research/` | Experiment manifest, preregistration grid, candidate register, multiplicity, authorization | `src/research/manifest.py` |
| `src/ops/backup.py` | `pg_dump` + Parquet copy + sha256 manifest + scratch restore drill | `src/ops/backup.py` |
| `src/ops/redaction.py` | `configure_logging` / `scrub` — secrets never reach a log line | `src/ops/redaction.py` |

## Pattern Overview

- **Overall:** Layered hexagonal (ports-and-adapters) architecture with a **pure deterministic core** and **fail-closed** semantics at every boundary.

- **Key Characteristics:**
- **Pure core / impure shell.** `src/core`, `src/domain`, `src/risk`, `src/backtest` and the pure parts of `src/analytics` / `src/paper` / `src/research` import only stdlib + `Decimal` (+ project-owned pure modules). All I/O lives in `src/adapters`, `src/persistence`, `src/db`, `src/data`, `src/ops` and the process entrypoints.
- **One decision path, three runtimes.** The identical call chain `src/core/strategy.evaluate` → `src/core/planner.plan` → `src/risk/gating.evaluate_risk` → `src/risk/quantization.quantize` is executed by the backtest engine (`src/backtest/simulator.py:56`), the paper loop (`src/paper/loop.py:35-53`) and the live execution manager (`src/execution/manager.py:63`). There is no second implementation of sizing, quantization or cost math.
- **Adapters as the only SDK boundary.** `src/adapters/binance_usdm.py` and `src/adapters/binance_public.py` are the only modules importing `binance_sdk_derivatives_trading_usds_futures`; `src/adapters/telegram_notify.py` and `src/adapters/telegram_callbacks.py` are the only modules importing `python-telegram-bot`. SDK response models never reach `src/domain` or `src/core`.
- **Fail closed.** Uncertain data, connection, account or risk yields `NO_TRADE` and no order. Every pure function returns a typed rejection (`RejectionReason`) instead of raising.
- **Content-addressed identity.** Every entity ID is a SHA-256 over canonical JSON (`src/domain/canonical.py`, `src/domain/ids.py`). Parameter sets are hash-locked in `params/<family>/<set>.toml` and never edited in place.
- **Injected time.** Pure modules never read a clock; clocks and `now_utc` are arguments.
- **Journal-first ordering.** A lifecycle fact is committed to the journal *before* the side effect that depends on it (Telegram send, order placement).
- **In-process queues, not a broker.** One bounded `asyncio.Queue` per process; durable state is a PostgreSQL row.

## Layers

- **`src/domain/` — Entities, enums, canonical serialization, parameter registry**
- Purpose: the shared vocabulary every other layer speaks. No I/O, no clock, no float.
- Location: `src/domain/`
- Contains: `enums.py`, `signal.py`, `trade_plan.py`, `order.py`, `position.py`, `fill.py`, `approval.py`, `journal.py`, `registry.py`, `canonical.py`, `ids.py`, `rationale.py`, `lot_filters.py`, `transitions.py`, `algo_status.py`, `exchange_errors.py`, `stream_records.py`.
- Depends on: stdlib only.
- Used by: every other layer.
- **Constraint:** `src/domain/registry.py` is the only way a parameter set enters the system. `load_parameter_set` / `verify_parameter_set` raise on an unregistered, mutated or unknown-key file; there is no silent fallback.

- **`src/core/` — Pure deterministic features / strategy / planner**
- Purpose: turn a market snapshot into a `Signal`, and a `Signal` into a `TradePlan`. Zero I/O, zero clock reads, zero randomness.
- Location: `src/core/`
- Contains: `types.py` (Candle, MarketSnapshot, AccountState, FeatureFrame, SetupResult), `features.py`, `strategy.py`, `planner.py`, `pivots.py`, `_decimal.py`.
- Depends on: `src/domain` + stdlib.
- Used by: `src/backtest`, `src/paper`, `src/execution`, `src/analytics`.
- **Constraint:** no Polars/pandas/NumPy/Pydantic/SDK/network import. Enforced by `tests/test_domain_no_float.py` and `tests/support/ast_guards.py`.

- **`src/risk/` — Sizing, cost guards, quantization, portfolio gates**
- Purpose: turn a `TradePlan` into a `SizedResult` or a typed rejection.
- Location: `src/risk/`
- Contains: `types.py`, `sizing.py`, `quantization.py`, `gating.py`, `portfolio.py`, `cost_guards.py`, `cost_rates.py`, `realized_risk.py`, `live_commission.py`.
- Depends on: `src/core`, `src/domain`.
- Used by: `src/backtest`, `src/paper`, `src/execution`.
- **Constraint:** the quantization gate order is fixed — floor to stepSize → min-quantity reject → min-notional reject → `minimum_risk_utilization_after_rounding` reject. Floors never round up; NO_TRADE is preferred over a risk-budget breach.

- **`src/backtest/` — Project-owned closed-candle simulator**
- Purpose: the canonical execution semantics shared with paper and live.
- Location: `src/backtest/`
- Contains: `engine.py` (v2 event-loop simulator), `simulator.py` (public `run`), `costs.py`, `funding.py`, `entry.py`, `exits.py`, `lifecycle.py`, `records.py`, `ledger.py`, `series.py`, `semantics.py`, `validator.py`, `report.py`, `experiment.py`, `binding.py`, `case.py`, `constraints.py`.
- Depends on: `src/core`, `src/domain`, `src/risk`.
- Used by: `src/research`, `src/analytics`, `scripts/`.

- **`src/adapters/` — The external boundary**
- Purpose: translate SDK/HTTP/file shapes into project-owned frozen dataclasses.
- Location: `src/adapters/`
- Contains: `binance_public.py`, `binance_usdm.py`, `binance_client.py`, `binance_clock.py`, `binance_errors.py`, `binance_limits.py`, `binance_probe.py`, `binance_ratelimit_gate.py`, `binance_userdata.py`, `binance_userdata_events.py`, `binance_userdata_router.py`, `binance_userdata_supervisor.py`, `paper_ws.py`, `telegram_notify.py`, `telegram_callbacks.py`, `analytics_files.py`, `analytics_store.py`, `code_version.py`.
- Depends on: the SDKs, plus `src/domain` for the project types it returns.
- Used by: `src/paper`, `src/data`, `src/execution`, `src/ops`, `src/analytics`.
- **Constraint:** SDK response models never leave this layer. The shadow runtime imports `binance_public.py` (not `binance_usdm.py`) so a process that must never place an order never loads the order adapter (`src/adapters/binance_public.py:1-9`).

- **`src/paper/` — Paper runtime, freeze, shadow mode, liveness**
- Purpose: the realtime mirror of the backtest, running against a public (credential-free) feed.
- Location: `src/paper/`
- Contains: `runtime.py` (entrypoint), `pipeline.py`, `loop.py`, `bars.py`, `freeze.py`, `runtime_config.py`, `runtime_state.py`, `supervisor.py`, `restart.py`, `resync.py`, `market_inputs.py`, `journal.py`, `notify.py`, `coverage.py`, `liveness.py`, `held_marker.py`, `attribution.py`, `exit_criteria.py`, `evidence_bundle.py`, `evidence_export.py`, `rehearsal.py`, `replay_inputs.py`, `shadow*.py` (8 modules), `surface.py`, `vocabulary.py`.
- Depends on: `src/core`, `src/risk`, `src/backtest`, `src/persistence`, `src/adapters`.
- Used by: the `paper` compose service and `deploy/compose-soak.sh`.

- **`src/approval/` — Approval tokens, binding, replay**
- Purpose: prove a human pressed the button, exactly once, against a plan that has not changed.
- Location: `src/approval/`
- Contains: `tokens.py`, `binding.py`, `replay.py`, `mapping.py`.
- Depends on: `src/domain` only (stdlib + `src/domain/enums.py`).
- Used by: `src/execution/manager.py`, `src/adapters/telegram_callbacks.py`, `src/persistence/approvals.py`.

- **`src/execution/` — Human-approved order placement**
- Purpose: the only layer that may place an order.
- Location: `src/execution/`
- Contains: `manager.py` (orchestration), `placement.py` (price/tick derivation, protective sizing), `gates.py` (placement-time gates), `pre_placement.py`, `enablement.py` (`LIVE_ORDERS_DISABLED` default), `execution_limits.py`, `constraint_snapshot.py`, `fill_monitor.py`, `intent_store.py`, `intent_recovery.py`, `lot_split.py`, `order_ids.py`, `tp_sizing.py`, `binding.py`.
- Depends on: `src/approval`, `src/risk`, `src/domain`, `src/persistence/errors.py`.
- Used by: the live runner (Phase 24) and `scripts/demo_rehearsal.py`.

- **`src/reconcile/` — Exchange reconciliation**
- Purpose: compare exchange truth with local truth and sweep orphans; drive SAFE_MODE.
- Location: `src/reconcile/`
- Contains: `compare.py`, `sweeper.py`, `safe_mode.py`.
- Depends on: `src/domain`, `src/persistence`.
- Used by: `src/ops/drills.py`, the live runner.

- **`src/persistence/` + `src/db/` — Operational state**
- Purpose: durable lifecycle state in PostgreSQL.
- Location: `src/persistence/` (stores), `src/db/` (ORM + Alembic)
- Contains: `persistence/engine.py` (sync engine factory, UTC-pinned, bounded timeouts), `uow.py` (`OperationalDatabase`), `journal.py`, `approvals.py`, `entities.py`, `execution_state.py`, `paper_runtime_state.py`, `shadow_stores.py`, `snapshots.py`, `system_state.py`, `errors.py`; `db/models.py` (16 tables), `db/mappers.py`, `db/alembic/versions/0001..0005`.
- Depends on: SQLAlchemy + psycopg.
- Used by: `src/paper`, `src/execution`, `src/analytics`, `src/data`.
- **Constraint:** `src/db/mappers.py` is Decimal-only (scanned by `tests/test_domain_no_float.py`).

- **`src/data/` — Collectors, Parquet datasets, coverage**
- Purpose: historical and live market-data acquisition into an immutable dataset.
- Location: `src/data/`
- Contains: `collector.py`, `backfill.py`, `backfill_cli.py`, `store.py`, `archive.py`, `case_input.py`, `collect_list.py`, `coverage.py`, `metadata.py`, `minute_source.py`, `quality.py`, `sufficiency.py`, `universe_freeze.py`.
- Depends on: `src/adapters`, `src/db`, `polars`, `duckdb`.
- Used by: `src/backtest` (case inputs), `src/analytics`.

- **`src/analytics/` — Metrics, kill-gate, report**
- Purpose: compute the evidence that decides whether a family passes or fails the kill-gate.
- Location: `src/analytics/`
- Contains: `core_metrics.py`, `report.py`, `killgate.py`, `killgate_guard.py`, `gates.py`, `slices.py`, `stats.py`, `excursion.py`, `latency.py`, `approval_delay.py`, `no_trade.py`, `lifecycle.py`, `live_outcomes.py`, `provenance.py`, `family.py`, `universe.py`, `clock.py`, `inputs.py`, `types.py`, `render*.py` (4 modules), `cli.py` (the single edge).
- Depends on: `src/domain` + stdlib; the CLI edge adds `src/adapters/analytics_files` and `src/adapters/analytics_store`.
- Used by: the operator, `docs/research/kill_gate_decisions.json`.

- **`src/research/` — Experiment registry, manifest, multiplicity**
- Purpose: make the research run auditable and pre-registered.
- Location: `src/research/`
- Contains: `manifest.py`, `manifest_build.py`, `register.py`, `run.py`, `multiplicity.py`, `authorization.py`, `feasibility.py`, `plateau.py`, `report.py`, `settlement_evidence.py`.
- Depends on: `src/domain`, `src/backtest`, `src/analytics`.
- Used by: `docs/research/preregistration/`, `docs/research/experiments/`.

- **`src/ops/` — Backup, cutover, drills, health, redaction**
- Purpose: keep the host operable and the secrets out of the logs.
- Location: `src/ops/`
- Contains: `backup.py`, `backup_remote.py`, `cutover.py`, `drills.py`, `evidence_remote.py`, `health.py`, `operator_evidence.py`, `redaction.py`.
- Depends on: `src/persistence`, `src/data`, stdlib + `structlog`.
- Used by: `deploy/*.sh`, the `ops` compose profile.

- **`src/sql/` — Analytical SQL**
- Purpose: the DuckDB coverage view over the Parquet tree.
- Location: `src/sql/coverage_v1.sql`.

## Data Flow

### Primary Request Path

- Paper runtime tick (the path that decides and records a trade):

- **SDK frame → tagged bar.** The Binance WS adapter raises a kline event; `src/adapters/paper_ws.py` normalizes it; the supervisor sink in `src/paper/runtime.py:821` (`_enqueue`) applies the restart fence and does `queue.put_nowait(bar)` — a full queue raises `RuntimeFailClosed` rather than dropping a bar.
- **Consumer → pipeline.** The single consumer task calls `BarPipeline.handle` inside `asyncio.to_thread` (`src/paper/runtime.py:48-54`); the pipeline applies the closed-candle gate, the warm-up gate and the history-continuity gate, then hands the 1H bar to the pure loop (`src/paper/pipeline.py:498-517`).
- **Strategy → Signal.** `src/core/strategy.py:680` `evaluate(snapshot, account_state, strategy_version, parameter_set)` computes features on both streams, resolves the 4H regime, runs the family detector, and returns `NO_TRADE` with a `RejectionReason` or a `SETUP(Signal)` whose `signal_id` is `make_signal_id(...)` over the identity tuple (`src/core/strategy.py:900`).
- **Signal → TradePlan.** `src/core/planner.py:419` `plan(signal, setup_candles, parameter_set, account_state, created_at_utc)` derives direction, entry zone, SL, TP1/TP2, expiry and `plan_hash`. Any mismatch, empty stream, expired signal or non-positive risk returns `NO_TRADE` — it never raises.
- **Plan → SizedResult.** `src/risk/gating.py` `evaluate_risk` runs `size_position` → `STOP_TOO_TIGHT` → `COST_TO_RISK_EXCEEDED` → `quantize` → `check_portfolio`. `src/risk/quantization.py:91` floors to `quantity_step_size` with exact Decimal floor-division, then applies min-qty → min-notional → 60% utilization rejects in that fixed order.
- **Journal, then notify.** `src/paper/journal.py` commits the decision row **first**; only then does `src/paper/notify.py` `notify_simulate` format the 12 APRV-01 fields and send through `src/adapters/telegram_notify.py`. Send failures are caught, journaled via `on_outcome` and never raise into the loop.
- **Journal → state port.** The tick writes its `PAPER_TICK_STATS` record and the decision records through the synchronous `RuntimeStatePort` (`src/paper/runtime_state.py:341`), which the runtime wraps in `asyncio.to_thread`.

### Secondary Flow — Live approval and placement

- **Telegram callback → binding gate.** `src/adapters/telegram_callbacks.py` receives the inline-keyboard callback and hands it to `src/approval/binding.py` `check_binding_full`, whose order is fixed: chat-id → expiry → plan-hash → strategy version / parameter-set id / parameter-set hash → token hash (`src/approval/binding.py:5-16`).
- **Replay resolution.** `src/approval/replay.py` looks the approval up by token hash (the idempotency key), then either returns the stored approval untouched (a replay) or performs exactly one `PENDING → APPROVED/SKIPPED` transition. Five replays of one APPROVE produce one transition.
- **Intent, then place.** `src/execution/manager.py` writes the ENTRY execution intent through the `ExecutionIntentStore` protocol **before** `place_entry` runs, and the STOP_LOSS leg gets its own intent **before** `place_algo_protective` (`src/execution/manager.py:15-24`). The persisted intent is the duplicate-entry guard — Binance's `newClientOrderId` uniqueness covers only OPEN orders.
- **Placement gates.** `src/execution/gates.py` revalidates live constraints from exchangeInfo, the portfolio caps, `DAILY_STOP` and the account-wide 200 open conditional-order headroom before any order call.

### Secondary Flow — Historical data and backtest

- **Collector → Parquet.** `src/data/collector.py` polls open interest every 5 minutes and sweeps funding every 8 hours; each tick is published through `src/data/store.py` `atomic_write_parquet` (temp file → fsync → `os.replace`) into the immutable Hive layout `data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet`. A failed poll writes one `collector_gaps` row and never advances the watermark.
- **Case input → engine.** `src/data/case_input.py` builds a case-input v2 dict; `src/backtest/simulator.py:56` `run(case_input)` calls `engine.simulate(case_input, risk_fn=evaluate_risk)` — the risk function is looked up in the module globals at call time, so a monkeypatch of `src.backtest.simulator.evaluate_risk` intercepts every risk call.
- **Experiment → manifest.** `src/research/manifest_build.py` and `src/research/run.py` execute the preregistered grid (`docs/research/preregistration/research-run-1-grid-*.json`) and write per-candidate experiment records to `docs/research/experiments/research-run-1/`.
- **Evidence → kill gate.** `src/analytics/cli.py` loads the evidence, decision and universe files through `src/adapters/analytics_files`, composes the frozen `ReportInputs`, runs the pure core and writes exactly two files (Markdown report + sidecar) under the confined reports root.

### Secondary Flow — Reconciliation and SAFE_MODE

- `src/reconcile/compare.py` diffs the exchange snapshot (open normal orders, open algo orders, positions) against the local `orders` / `execution_intents` / `positions` rows.
- `src/reconcile/sweeper.py:141` `sweep(diff, position_verifier=...)` cancels orphan protectives. Two consecutive zero position reads are required; a single non-zero read yields a `SweepSkip` with reason `transient_position_gap` and no cancel. A single cancel failure is journaled and the sweep continues.
- `src/reconcile/safe_mode.py` moves the system to `SystemMode.SAFE_MODE`: entries are blocked while monitoring and reconciliation continue.

- **State Management:**
- **Durable:** PostgreSQL. 16 tables in `src/db/models.py` — `symbol_metadata`, `collector_watermarks`, `collector_gaps`, `coverage_windows`, `signals`, `trade_plans`, `approvals`, `orders`, `execution_intents`, `fills`, `positions`, `journal_events`, `short_id_mapping`, `plan_constraint_snapshots`, `system_state_events`. Migrations in `src/db/alembic/versions/0001_baseline.py` … `0005_live_sized_risk.py`; `alembic upgrade head` only — `create_all` is never used.
- **Analytical:** immutable Hive-partitioned Parquet under `data/raw/`, read by DuckDB (`src/sql/coverage_v1.sql`).
- **In-process:** one bounded `asyncio.Queue` (`QUEUE_MAXSIZE = 4096` in `src/paper/runtime.py:174`) between the WS receive callbacks and the single consumer task. The queue is never a buffer of loss: a full queue fails the process closed.
- **Ephemeral:** the pinned epoch in `logs/paper/pinned_epoch.json` and the held marker in `src/paper/held_marker.py`.

## Key Abstractions

- **`MarketSnapshot` / `Candle` / `AccountState`**
- Purpose: the complete, clock-free input of the decision path.
- Examples: `src/core/types.py`, `src/core/features.py`
- Pattern: frozen dataclass, `Decimal` money, UTC-aware `datetime`.

- **`Signal`**
- Purpose: a detected setup. Not a trade, not an order.
- Examples: `src/domain/signal.py`, `src/core/strategy.py:910`
- Pattern: content-hash ID (`src/domain/ids.py:19`); status enum `SignalStatus` (`src/domain/enums.py:16`).

- **`TradePlan`**
- Purpose: the priced, expiring intent — entry zone, SL, TP1/TP2, expiry, invalidation, `plan_hash`.
- Examples: `src/domain/trade_plan.py`, `src/core/planner.py:419`
- Pattern: frozen dataclass; the plan hash is the thing an approval binds to (`src/approval/binding.py`).

- **`ParameterSet`**
- Purpose: the versioned, hash-locked parameter identity bound into every signal, plan and experiment.
- Examples: `src/domain/registry.py`, `params/trend-pullback/baseline-v6.toml`
- Pattern: loaded from `params/<family>/<id>.toml`; `parameter_set_hash` = SHA-256 over the canonical JSON of the normalized document. A behavior change ships as a NEW set plus a NEW `strategy_version` — never an in-place edit.

- **`ConstraintSnapshot`**
- Purpose: the exchange filters (stepSize, tickSize, minQty, minNotional) plus their freshness TTL.
- Examples: `src/risk/types.py`, `src/execution/constraint_snapshot.py`
- Pattern: re-read at placement time; a stale snapshot is a fail-closed reject, not a cached value.

- **`SizedResult` / `PortfolioVerdict`**
- Purpose: the typed outcome of the risk pipeline — accept with a quantity, or reject with a `RejectionReason`.
- Examples: `src/risk/types.py`, `src/risk/gating.py`
- Pattern: `is_no_trade` boolean + `reason_code`; the reason is preserved byte-identically across backtest/paper/live.

- **`RuntimeRecord` / `RuntimeStatePort`**
- Purpose: the paper runtime's durable event stream and the single storage port for restart-surviving state.
- Examples: `src/paper/runtime_state.py:133`, `src/paper/runtime_state.py:341`
- Pattern: a synchronous Protocol wrapped by the runtime in `asyncio.to_thread`. Idempotent write; the same record twice is a no-op, different content under the same id is a `RuntimeRecordConflict`.

- **`ExecutionIntentStore` / `IntentRecord`**
- Purpose: the exactly-once guard for order placement.
- Examples: `src/execution/intent_store.py`, `src/persistence/execution_state.py`
- Pattern: a Protocol injected into the manager; the intent is written *before* the adapter call, so a crash between intent and order is recoverable by `src/execution/intent_recovery.py`.

- **`JournalEvent`**
- Purpose: the audit trail of every lifecycle fact, including skipped signals.
- Examples: `src/domain/journal.py`, `src/persistence/journal.py`
- Pattern: content-hash event id (`content_hash_event_id`); appended, never updated.

## Entry Points

- **`python -m src.data.collector`**
- Location: `src/data/collector.py:1145` (`main`)
- Triggers: the `collector` compose service; the 5-minute OI poll loop.
- Responsibilities: universe load → per-tick OI poll + funding sweep → Parquet publish → atomic watermark advance → gap journal on failure. Flags: `--once` (single tick), `--healthcheck` (container probe; fails when no OI tick completed within 2× cadence or no funding sweep within one 8h interval + margin).

- **`python -m src.paper.runtime`**
- Location: `src/paper/runtime.py:1427` (`main`), parser at `src/paper/runtime.py:210`
- Triggers: the `paper` compose service (`--hold-on-refusal`), the one-shot `paper-pin` service (`--pin-epoch`), the container probe (`--healthcheck`), the heartbeat probe (`--liveness`).
- Responsibilities, in order — each step may end the process before the next: configure redacted logging → refuse any `BINANCE_*` env var (exit 3) → allowlist start gate → admission (exact-hash entry for every parameter set; exit 6) → ratified runtime config (exit 4) → single-instance lease (exit 8) → epoch pin/load (exit 5 / 6) → `RUNTIME_START` → the live loop → `RUNTIME_STOP`.
- The live loop composes the credential-free public adapter, `PaperWsAdapter`, `PaperSupervisor`, ONE bounded queue, ONE consumer task and `BarPipeline`. A full queue, a failed write or a pipeline error stops the loop and ends the process with `ExitCode.FAIL_CLOSED_RUNTIME` and **without** a `RUNTIME_STOP` record, so a restart reads the open `RUNTIME_START` as a crash.

- **`python -m src.ops.backup <subcommand>`**
- Location: `src/ops/backup.py:950` (`main`), parser at `src/ops/backup.py:989`
- Triggers: the `backup` compose service (`scheduled`), `deploy/backup.sh`, `deploy/restore.sh`, the systemd timers in `deploy/systemd/`.
- Responsibilities: `pg_dump --format=custom` + a Parquet tree copy + a `manifest.json` of per-file sha256, then the scratch-restore drill that re-hashes and compares. Subcommands: `backup`, `drill`, `prune`, `verify`, `restore`, `dump`, `restore-db`, `push`, `pull`, `retain`, `scheduled`, `drill-remote`. No SQL or copy logic lives in the shell scripts.

- **`python -m src.analytics.cli` (`src/analytics/cli.py:795`)**
- Location: `src/analytics/cli.py`
- Triggers: the operator; the research report step.
- Responsibilities: load evidence/decision/universe through `src/adapters/analytics_files`, compose `ReportInputs`, run the pure core, verify the Markdown and the sidecar agree, and write exactly two files under the confined reports root. stdout on success is exactly four lines: `Report:`, `Sidecar:`, `Digest: sha256:<64 hex>`, `Kill gate: <STATE>`.

- **Other module CLIs (all `python -m …`)**
- `python -m src.data.backfill_cli` (`src/data/backfill_cli.py:1138`)
- `python -m src.data.universe_freeze` (`src/data/universe_freeze.py:899`)
- `python -m src.data.collect_list` (`src/data/collect_list.py:495`)
- `python -m src.data.coverage` (`src/data/coverage.py:629`)
- `python -m src.data.sufficiency` (`src/data/sufficiency.py:747`)
- `python -m src.research.run` (`src/research/run.py:878`)
- `python -m src.research.register` (`src/research/register.py:268`)
- `python -m src.research.manifest_build` (`src/research/manifest_build.py:441`)
- `python -m src.ops.cutover` (`src/ops/cutover.py:529`)

- **`scripts/`** — developer and CI helpers
- `scripts/verify_decision_alignment.py` — the docs↔code gate (AU-01..AU-05 in `scripts/decision_alignment/authority.py`).
- `scripts/gen_phase6_fixtures.py`, `scripts/gen_phase14_fixtures.py`, `scripts/_compute_phase4_fixtures.py` — golden-fixture generators. Never hand-type a fixture.
- `scripts/dev/` — Windows helpers: `test.ps1`, `clean.ps1`, `migrate.ps1`, `journal-report.ps1` (see `scripts/dev/README.md`).
- `scripts/paper_ws_smoke.py`, `scripts/user_data_smoke.py`, `scripts/demo_probe.py`, `scripts/demo_rehearsal.py`, `scripts/shadow_rehearsal.py`, `scripts/smoke_backtest_realdata.py`, `scripts/soak_host_acceptance.py`, `scripts/export_soak_evidence.py`, `scripts/geometry_census.py`.

- **`deploy/*.sh`** — host operations
- `deploy/bootstrap.sh`, `deploy/update.sh`, `deploy/migrate.sh`, `deploy/backup.sh`, `deploy/restore.sh`, `deploy/backup-drill.sh`, `deploy/heartbeat.sh`, `deploy/compose-soak.sh`, `deploy/compose-rehearsal.sh`, `deploy/soak-image.sh`, `deploy/refresh-pins.sh`, `deploy/lib.sh` (shared shell library). systemd units in `deploy/systemd/`.

## Architectural Constraints

- **Threading:** single asyncio event loop per process. The paper runtime's receive callbacks only enqueue; every database write and the whole tick run off the loop through the one synchronous state port, wrapped locally with `asyncio.to_thread` (`src/paper/runtime.py:56-59`). The choice between threads and an async pool is a documented open item (Phase 24, G4-040). The collector is likewise single-threaded: async adapter calls, sync SQLAlchemy writes inline on the loop (`src/data/collector.py:14-25`).
- **Global state:** no mutable module-level singletons in the decision path. `src/domain/registry.py` holds the immutable `REGISTRY_ROOT` and `STRATEGY_KEYS` frozenset; `src/core/strategy.py` holds the immutable `_INTERVAL_DURATIONS` map. The genuinely stateful module-level objects are the runtime singletons in `src/paper/runtime.py` and `src/paper/shadow_runtime.py` (loop-scoped, not import-scoped) and the `structlog` loggers.
- **Circular imports:** none in the decision path. The dependency direction is `adapters → domain/core` and `runtime → core/risk/persistence`; `src/backtest/simulator.py` deliberately re-exports `evaluate_risk` so `src/backtest/engine.py` never imports `src.risk` directly, which keeps the risk function injectable at call time.
- **`src/core` purity:** stdlib + `Decimal` only. No Polars, pandas, NumPy, Pydantic, SQLAlchemy, Binance SDK or network import. Enforced by `tests/test_domain_no_float.py` and `tests/support/ast_guards.py`.
- **Decimal-only:** `src/domain/*`, `src/db/mappers.py`, `src/core/*`, `src/risk/*`, `src/backtest/*`, `src/analytics/*` (pure core) and the `src/adapters/paper_ws.py` adapter carry no `float(...)` constructor, no float literal and no `Decimal(<float literal>)` shape. `tests/test_domain_no_float.py` `SCANNED_FILES` + `SCANNED_GLOBS` define the exact scope; a glob-covered package (`src/backtest/*.py`, `src/paper/*.py`, `src/research/*.py`) can only be excluded through `FLOAT_SCAN_EXCLUDED`, which requires a one-line reason (today: `src/paper/shadow.py` only).
- **No wall clock in pure modules:** the forbidden spellings are enumerated in `tests/support/ast_guards.py` `WALL_CLOCK_CALLS` — `datetime.now`, `datetime.utcnow`, `date.today`, `time.time`, `time.time_ns`, `time.monotonic`, `time.monotonic_ns`, `time.perf_counter`, `time.perf_counter_ns` — plus the event loop's own clock (`loop.time()`, `asyncio.get_running_loop().time()`). Import aliases are resolved. Clocks are injected.
- **SDK isolation:** SDK response models never leave `src/adapters/`. `src/adapters/binance_usdm.py` and `src/adapters/binance_public.py` are the only Binance-SDK importers; `src/adapters/telegram_notify.py` and `src/adapters/telegram_callbacks.py` are the only `python-telegram-bot` importers.
- **Entity separation (D007):** signal ≠ trade plan ≠ order ≠ position. They have separate entities in `src/domain/`, separate tables in `src/db/models.py` and separate status enums in `src/domain/enums.py`.
- **Parameter immutability:** a parameter set is loaded only from the versioned registry `params/<family>/<set>.toml` via `src/domain/registry.py` (`load_parameter_set`, `verify_parameter_set`). A file is hash-locked by `tests/fixtures/phase4/parameters.json` and `registry-gate.yml`; an unpinned file fails closed.
- **No AI/LLM in the decision path:** direction, entry, SL, TP, size, risk, parameters and signal validity are decided by `src/core` + `src/risk` only.
- **Fail closed:** uncertain data, connection, account or risk ⇒ `NO_TRADE` and no new order. `SAFE_MODE` blocks entries while monitoring and reconciliation continue.

## Anti-Patterns

### Re-implementing sizing or quantization in a runtime

- **What happens:** a runtime computes its own quantity or applies its own rounding instead of calling `src/risk/gating.evaluate_risk`.
- **Why it's wrong here:** it breaks the D-02 parity guarantee — backtest, paper and live would no longer produce identical decisions for the same snapshot, and the golden fixtures would stop predicting paper behavior.
- **Do this instead:** call `evaluate_risk` / `size_and_quantize` (`src/risk/gating.py:61`). The backtest already does it via `src/backtest/simulator.py:56`; the paper loop does it in `src/paper/loop.py`; the live manager does it in `src/execution/manager.py:63`.

### Letting an SDK response model reach the domain

- **What happens:** a function in `src/domain` or `src/core` takes or returns a `binance_sdk_derivatives_trading_usds_futures` model.
- **Why it's wrong here:** the domain would then change whenever the SDK is upgraded, breaking the version-lock and the determinism guarantee, and the SDK would leak into the pure core (which the AST guards forbid).
- **Do this instead:** normalize in `src/adapters/binance_public.py` / `src/adapters/binance_usdm.py` to a frozen dataclass with `Decimal` money and UTC-aware `datetime`, and pass that.

### Reading the wall clock inside a pure function

- **What happens:** a module in `src/core`, `src/domain`, `src/risk` or `src/backtest` calls `datetime.now(UTC)` to stamp a decision.
- **Why it's wrong here:** the decision would no longer be a function of its inputs, so the same snapshot could produce a different plan on a re-run — the exact thing the determinism requirement forbids.
- **Do this instead:** take `now_utc` / `created_at_utc` as an argument (`src/core/planner.py:419`, `src/execution/manager.py`) or inject a clock callable (`src/paper/runtime_state.py` `RuntimeContext.clock`).

### Rounding up to reach a minimum

- **What happens:** a quantity is rounded up so it clears `min_quantity` or `min_notional`.
- **Why it's wrong here:** it silently raises the realized risk above the budget. The project rule is floor-then-reject, and NO_TRADE is preferred over a risk-budget breach.
- **Do this instead:** floor with exact Decimal floor-division, then let the ordered gates reject (`src/risk/quantization.py:91-135`).

### Editing a parameter set in place

- **What happens:** `params/trend-pullback/baseline-v6.toml` is edited to change a threshold.
- **Why it's wrong here:** the `parameter_set_hash` changes, so every signal, plan, experiment and approval bound to the old hash becomes invalid, and the registry gate turns red.
- **Do this instead:** add a NEW set file plus a NEW `strategy_version`; keep the old file byte-identical.

### Placing an order before the intent is durable

- **What happens:** the adapter call is made and the intent row is written afterwards.
- **Why it's wrong here:** a crash between the two loses the record of an order that exists on the exchange, and Binance's `newClientOrderId` uniqueness covers only OPEN orders — a replay would be accepted again.
- **Do this instead:** write the intent first, then place (`src/execution/manager.py:15-24`), and recover with `src/execution/intent_recovery.py`.

### Swallowing a send failure inside the loop

- **What happens:** a Telegram send exception propagates out of the notify call into the runtime loop.
- **Why it's wrong here:** it would kill the process on a transient network error, and it would break the journal-first ordering guarantee.
- **Do this instead:** catch it, journal the outcome through `on_outcome`, return normally (`src/paper/notify.py:9-16`).

## Error Handling

- **Strategy:** fail closed with a typed reason. Every pure decision function returns a result object carrying a `RejectionReason` (`src/domain/enums.py`) instead of raising; exceptions are reserved for programmer errors and for genuinely impossible states.

- **Patterns:**
- **Typed rejections.** `SetupResult(is_no_trade=True, reason_code=...)`, `PlanResult(is_no_trade=True, reason_code=...)`, `SizedResult(is_no_trade=True, reason_code=...)`. First failure wins, and the reason code is byte-identical across backtest/paper/live.
- **Fail-closed validation.** `src/domain/registry.py` raises `UnregisteredParameterSet` / `RegistrySchemaMismatch` / `StrategyKeyOutsideRegistry` / `ParameterSetMutated` rather than defaulting. `src/paper/runtime_config.py` raises `ConfigNotRatified` naming every missing or unknown key; no default is injected for any key.
- **Named exit codes.** `ExitCode` in `src/paper/runtime_config.py`: `OK`, `TRADE_KEY_REFUSED` (3), `CONFIG_NOT_RATIFIED` (4), `NO_PINNED_EPOCH` (5), `ADMISSION_OR_EPOCH_MISMATCH` (6), `FAIL_CLOSED_RUNTIME` (7), `INSTANCE_LEASE_HELD` (8), `USAGE`. Refusals are non-restartable; the compose service therefore passes `--hold-on-refusal` so a `restart: unless-stopped` policy cannot loop on them.
- **Persistence error taxonomy.** `src/persistence/errors.py`: `PersistenceError` (base) → `StoreUnavailable`, `StoreFailure`, `SessionTimeZoneNotUtc`, `JournalConflict`, `RowConflict`, `ParentRowMissing`, `PrecisionError`, `EvidenceRequired`, `ShortIdRebindingRefused`, `IntentStateConflict`. An unreachable database raises `StoreUnavailable` — there is no in-memory fallback.
- **Adapter error normalization.** `src/adapters/binance_errors.py` `error_facts_from_exception` and `src/domain/exchange_errors.py` `classify` map SDK exceptions to project categories. With `project_transport_errors=True` the paper path converts them into `TransientMarketDataError` / `MarketDataRateLimited` / `MarketDataRateLimitBan`; the SDK class name only, never a body or a URL.
- **Bounded retries.** `tenacity` with a capped attempt count; after the cap the caller fails closed. `src/adapters/binance_ratelimit_gate.py` `RestRateLimitGate` refuses a request before sending on a 418/429 and re-raises the original exception.
- **Error output hygiene.** Names and exception types only — never file contents, never credentials, never a response body.

## Cross-Cutting Concerns

- **Logging:** `structlog` JSON, configured through `src/ops/redaction.py` `configure_logging` (called first thing in `src/paper/runtime.py` `main` and `src/data/collector.py`). `src/ops/redaction.py` `scrub` removes secret values from log payloads. Decision lineage is carried as structured events: the quantization trail (`src/risk/quantization.py` emits raw quantity, rounded quantity, realized risk and the realized-to-allowed ratio), the journal rows and the runtime records. The pure modules that must stay dependency-free import `structlog` locally at the logging call site (see the comment in `src/risk/quantization.py:13-17`).

- **Validation:** three layers.
- *Static AST guards* — `tests/support/ast_guards.py` (`module_imports`, `forbidden_imports`, `float_constructor_calls`, `wall_clock_calls`) applied by `tests/test_domain_no_float.py`, `tests/test_ast_guards.py`, `tests/test_analytics_purity.py`, `tests/test_backtest_purity.py`, `tests/test_domain_boundary.py`.
- *Runtime fail-closed validation* — every boundary re-validates its input type, UTC-awareness and non-emptiness and raises a specific error rather than coercing (`_require_decimal`, `_require_utc_aware`, `_require_non_empty` in `src/paper/loop.py:60-96`; the same in `src/approval/binding.py:34-39`).
- *Golden fixtures* — `tests/fixtures/phaseN/` with hand-derived arithmetic in `DERIVATIONS.md` / `REGRESSION_SNAPSHOTS.md`, regenerated by `scripts/gen_phase6_fixtures.py`, `scripts/gen_phase14_fixtures.py`, `scripts/_compute_phase4_fixtures.py`.

- **Authentication:** there is no user-authentication layer — the system is single-operator. Authorization is the Telegram **chat-id gate** (the first step of `src/approval/binding.py`), plus the one-time approval token (`src/approval/tokens.py`, SHA-256 hashed, constant-time compare) and the exact-hash parameter allowlist (`src/paper/freeze.py` + the runtime process gate). Exchange credentials are the `BINANCE_DEMO_*` / `BINANCE_LIVE_*` variable families, read only by `src/adapters/binance_usdm.py`; the paper runtime refuses to start if any `BINANCE_*` name is present in its environment (`src/paper/runtime.py:6-7`). Secrets live only in `.env` (mode 0600, gitignored) and `secrets.env`; `src/ops/redaction.py` keeps them out of the logs.

- ---

- *Architecture analysis: 2026-10-19*
