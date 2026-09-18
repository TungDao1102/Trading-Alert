# Architecture Research

**Domain:** Deterministic Binance Futures research + semi-automated execution (4H/1H swing, human-approved)
**Researched:** 2026-09-19
**Confidence:** HIGH (synthesized from canonical Core Docs v0.3: ARCHITECTURE, DATA_PIPELINE, DATA_MODEL, GLOSSARY, CONFIGURATION, TESTING_STRATEGY, RISK_MANAGEMENT, EXECUTION_SPEC, IMPLEMENTATION_PLAN)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     INGESTION / ADAPTER LAYER                    │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ CandleColl.  │  │ OICollector  │  │ Funding/MetadataColl. │  │
│  │ REST+WS      │  │ REST poll    │  │ REST (exchangeInfo)   │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘  │
│         │                 │                      │               │
├─────────┴─────────────────┴──────────────────────┴───────────────┤
│              NORMALIZATION (SDK must not leak past here)         │
│  project-defined domain types: Candle, FundingTick, OI snapshot, │
│  SymbolMetadata — UTC, symbol/timeframe normalized, deduped      │
├──────────────────────────────────────────────────────────────────┤
│              PURE DETERMINISTIC CORE (no I/O, no network)        │
│  ┌──────────────┐ ┌──────────────┐ ┌────────┐ ┌───────────────┐  │
│  │Feature Engine│→│Strategy Eng. │→│Planner │→│ Risk Engine   │  │
│  │ ATR/EMA/zone │ │SETUP/NO_TRADE│ │plan    │ │ qty/quantize  │  │
│  └──────────────┘ └──────────────┘ └────────┘ └───────────────┘  │
├──────────────────────────────────────────────────────────────────┤
│              OPERATIONAL / EFFECT LAYER (adapters)               │
│  ┌─────────────────────────────────────────────────────┐        │
│  │ Approval/Alert (Telegram) → ExecutionMgr → Binance  │        │
│  │ Reconciler (REST authority) → Journal/Analytics     │        │
│  └─────────────────────────────────────────────────────┘        │
├──────────────────────────────────────────────────────────────────┤
│                         STORAGE                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Parquet raw  │  │ DuckDB/Polars│  │ PostgreSQL operational│  │
│  │ (immutable)  │  │ (analysis)   │  │ (state machine rows)  │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

Canonical pipeline direction (one way, no shortcuts):

```text
Market Data → Feature Engine → Strategy Engine → Trade Planner
  → Risk Engine → Approval/Alert → (APPROVE) → Execution Manager
  → Binance Futures → User-Data Stream → Journal/Analytics → Research
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Market Data Layer (collectors) | REST bootstrap + WS realtime, reconnect/resync, dedup, UTC + symbol/timeframe normalization, gap detection, warm-up seeding | `src/data/` asyncio collectors; one module per source (candles, OI, funding, metadata); quality checks per DATA_PIPELINE §6 |
| OI Collector | Poll `GET /fapi/v1/openInterest` every N min, persist timestamp+symbol+OI from day one (30-day API window is irrecoverable) | Standalone Phase-0 workstream, continuous process |
| Feature Engine | Pure deterministic transforms only: ATR, EMA, volume metrics, market structure, zones, futures context (mark/funding/OI/taker volume) | `src/strategy/` or `src/features/` pure functions: `(candles, params) → features`; must not generate orders |
| Strategy Engine | Consumes features + **closed candles only** → `NO_TRADE` or `SETUP` (+regime); prefix-invariant, no repaint | Pure function per strategy family; golden-fixture tested; no network calls |
| Trade Planner | SETUP → direction, entry zone (min/max), SL, TP JSON, expiry, invalidation rule, expected RR, strategy metadata | `src/planning/`; identical logic in backtest/paper/live |
| Risk Engine | allowed_risk = equity × risk_rate; qty = allowed_risk / (SL distance + costs); floor-to-step quantization, 60% utilization gate, portfolio limits (2 pos / 1.0% agg baseline), correlation cluster rule, DAILY_STOP | `src/risk/`; reads live exchangeInfo constraints + account state; FAIL CLOSED on uncertainty |
| Approval/Alert | Present plan via Telegram with SIMULATE/APPROVE/SKIP; expiring idempotent token; at-least-once callback replay resolves to existing state | `src/notifications/` + approvals table; no auto-approve on notification failure |
| Execution Manager | **Only component allowed to call live trading endpoints.** LIMIT-zone entry + Algo-Order protective exits (STOP/TP migrated off `/fapi/v1/order` since late 2025), partial-fill handling, pending-order expiry, deterministic client IDs, no blind retry | `src/execution/` behind exchange adapter interface; mode-aware (One-way vs Hedge) |
| Reconciler + Orphan Sweeper | Startup/reconnect/periodic: local vs open normal orders vs open algo orders vs positions; divergence → RECONCILIATION_REQUIRED; cancel orphan protective orders after authoritative verification | Background job; never trusts WS stream alone |
| Journal/Analytics | Append-only `journal_events` + three reporting joins: system (Signal→Plan→simulated), user (Signal→Approval→Order→Fill→Position), opportunity (skipped/expired→hypothetical); MFE/MAE, uncertainty | `src/infrastructure/` + analytics queries; never derive current state from event table |
| Backtest Simulator | Reuses live Feature/Strategy/Planner/Risk code; 1m intrabar resolution, limit-fill model, fees/funding/slippage, quantization; experiment registry + baselines + bootstrap/MC uncertainty | `src/backtest/`; VectorBT exploratory-only, project code is canonical |
| Parameter Registry | Versioned immutable parameter sets (`parameter_set_hash` over canonical JSON); source YAML/JSON → validated loader → DB; live orders require registered set | `src/infrastructure/config`; research notebooks load through same library code |

## Recommended Project Structure

```
src/
├── domain/           # project-defined types: Candle, Signal, TradePlan, enums (GLOSSARY)
│   └── enums.py      # SignalStatus ≠ OrderStatus ≠ PositionStatus ≠ ApprovalAction
├── data/             # collectors, normalization, quality checks, warm-up/resync
│   ├── candles.py    # REST bootstrap + WS ingestion
│   ├── oi.py         # OpenInterestCollector (Phase-0 workstream)
│   ├── funding.py    # funding history collection
│   └── metadata.py   # exchangeInfo snapshot → symbol_metadata
├── features/         # pure deterministic feature transforms (ATR/EMA/zones/context)
├── strategy/         # one module per family (trend-pullback, breakout-retest, range-mr)
├── planning/         # Trade Planner: SETUP → entry zone/SL/TP/expiry/invalidation
├── risk/             # sizing, quantization, portfolio limits, daily-stop state
├── backtest/         # historical reader, simulator, cost/fill models, experiment registry
├── execution/        # order manager, Algo-Order adapter, reconciler, orphan sweeper
├── notifications/    # Telegram adapter: alerts, approval callbacks, idempotency
├── infrastructure/   # Postgres repos, Parquet/DuckDB access, param registry, journal
├── api/              # FastAPI edge only: webhook/health/ops (no trading logic)
research/
├── notebooks/        # consumers of src package, never a second implementation
├── experiments/      # parameter sweeps inside declared ranges only
data/
├── raw/              # immutable Parquet research/raw
├── processed/        # derived, versioned
tests/
├── unit/             # domain + strategy pure tests
├── golden/           # fixtures: candles.csv + parameters.json + expected-*.json
└── integration/      # marked: testnet/network/DB (live creds never required for suite)
```

### Structure Rationale

- **domain/ is the anti-corruption layer:** Binance SDK classes and raw JSON stop at `data/` normalization; strategy/planning/risk only ever see project types. This is the single most important structural rule (ARCHITECTURE §4.1, DATA_PIPELINE §9).
- **One codebase, four modes:** research notebooks, backtest, paper, and live orchestration share the same `features/strategy/planning/risk` package — backtest/paper divergence is an exit-gate failure, not an acceptable drift.
- **planning/ and risk/ are separate modules** because sizing/quantization must be byte-identical across backtest/paper/live and independently fixture-tested (rounded-up quantity = test failure).
- **api/ is an edge, not a core:** FastAPI exists for webhook/health/ops; trading decisions never originate there (forbidden: UI → order API).
- **research/ never reimplements:** notebooks import the library; parameter sweeps stay inside research-declared ranges with region-grouped (not best-point) reporting.

## Architectural Patterns

### Pattern 1: Pure Core + Adapters at the Edge

**What:** Market-data I/O, Telegram, Binance, and DB live in adapters; the decision chain (features → setup → plan → sized plan) is pure functions of `(market snapshot, account state, strategy version, config)`.
**When to use:** Everywhere in the decision path — this is the determinism guarantee (same inputs → byte-equivalent outputs).
**Trade-offs:** Slightly more interface boilerplate (application services/interfaces between components) in exchange for golden-fixture testability without network/DB/Binance accounts.

**Example:**
```python
# Pure core: no imports from binance SDK, telegram, or db drivers allowed here.
def evaluate(state: MarketSnapshot, params: ParameterSet) -> Signal | NoTrade:
    features = compute_features(state.closed_candles, params)
    return detect_setup(features, params)  # NO_TRADE or SETUP, prefix-invariant

# Adapter (execution/): the ONLY place trading endpoints are called.
class ExecutionManager:
    async def submit_entry(self, approved: ApprovedPlan) -> None: ...
```

### Pattern 2: Explicit State Machines per Entity, Never Shared Enums

**What:** Each entity owns its lifecycle; states are never inferred from nullable columns and never shared across entities (`SignalStatus ≠ OrderStatus ≠ PositionStatus ≠ ApprovalAction`).
**When to use:** All persisted entities from DATA_MODEL §2–§3.
**Trade-offs:** More tables/enums upfront; prevents the classic collapse bug where "signal APPROVED" is misread as "order accepted by exchange".

Per-entity lifecycles (GLOSSARY + EXECUTION_SPEC + TESTING_STRATEGY):

```text
Signal:     DETECTED → NOTIFIED → VIEWED → {APPROVED | SKIPPED_USER | SKIPPED_BUSY} ; → EXPIRED | INVALIDATED
TradePlan:  READY → APPROVAL_PENDING → {APPROVED | EXPIRED | INVALIDATED | SUPERSEDED}
Approval:   requested → {APPROVE→executed-intent | SIMULATE | SKIP_USER | SKIP_BUSY | CANCEL}; replays resolve to existing result
Order:      PLANNED → APPROVED → SUBMITTING → NEW → {PARTIALLY_FILLED | FILLED | CANCELED | EXPIRED | REJECTED}; UNKNOWN only via reconciler
Trade:      PENDING → OPEN → CLOSED | ABORTED; UNKNOWN only via reconciler
Position:   OPEN → CLOSING → CLOSED; LIQUIDATION_REPORTED | UNKNOWN reconciled from exchange
SystemMode: RESEARCH | BACKTEST | PAPER | LIVE_APPROVAL | SAFE_MODE | LIVE_AUTONOMOUS_DISABLED
DailyRisk:  NORMAL → WARNING → DAILY_STOP (blocks entries, exits stay armed)
```

Mandatory invalid-transition tests: `EXPIRED → APPROVED`, `CANCELED → FILLED`, `CLOSED → NEW PROTECTIVE ORDER` (blocked unless an explicit reconciliation workflow authorizes it).

### Pattern 3: Analytical vs Operational Storage Split

**What:** Immutable Parquet (raw market observations) → DuckDB/Polars/pandas (analysis) for research; PostgreSQL for operational state (signals/plans/approvals/orders/fills/positions/journal/registry).
**When to use:** From Phase 0B onward; never make PostgreSQL the sole store for the multi-million-row candle dataset.
**Trade-offs:** Two storage systems to operate (plus backup/restore smoke tests) in exchange for cheap reproducible research scans without loading transactional tables.

```text
Binance raw data → Parquet (immutable research/raw, partitioned symbol/date)
                → DuckDB / Polars / pandas (analysis, experiment_runs reference data_snapshot_id)
Operational events/orders/positions → PostgreSQL (indexed by DATA_MODEL lookup paths)
```

Partitioning guidance: 5 symbols × 3y 1m ≈ 7.9M candles — monthly partitions on `open_time_utc`, canonical key `(symbol, timeframe, open_time_utc)`; derived `feature_snapshots` carry `(calculation ts, source candle close, algorithm version, feature_set_hash)` so signals reconstruct without recomputation.

## Data Flow

### Request Flow (live decision path)

```
Closed 1H/4H candle (WS kline-closed event)
    ↓
Market Data Layer: validate (dedup/OHLC-sanity/sequence) → normalize → persist raw
    ↓
Feature Engine: (closed candles + params) → FeatureSnapshot (hashed, persisted)
    ↓
Strategy Engine: (features + closed candles) → NO_TRADE | SETUP→Signal(DETECTED, deterministic signal_id)
    ↓
Trade Planner: Signal → TradePlan(READY: zone/SL/TP/expiry/invalidation/RR, plan_hash)
    ↓
Risk Engine: + equity/account + exchangeInfo snapshot → sized plan (raw/rounded qty, realized risk, QUANTIZATION_REJECT path)
    ↓
Approval/Alert: Telegram SIMULATE/APPROVE/SKIP (APPROVAL_PENDING, expiring token)
    ↓ APPROVE only
Execution Manager: risk re-check → LIMIT entry → attach Algo STOP/TP → monitor user-data WS
    ↓
Reconciler: local vs open-normal vs open-algo vs positions → RECONCILIATION_REQUIRED on drift
    ↓
Journal/Analytics: every transition (incl. skipped/expired) → system/user/opportunity reports
```

### State Management

```
PostgreSQL = current-state tables (signals, trade_plans, approvals, trades, orders, fills, positions)
journal_events = append-only audit (never the source of current state)
Parquet/DuckDB = immutable market history + feature provenance
Parameter registry = immutable sets; every run references (strategyVersion, parameterSetId, parameterSetHash)
Experiment registry = (experimentId, strategyVersion, parameterSetHash, dataSnapshotId, codeVersion, costModelHash)
```

### Key Data Flows

1. **Research flow:** Parquet → backtest simulator (same core code) → experiment_runs + metrics/uncertainty → frozen protocol/baseline. Direction: history → analysis, never live state → research assumptions.
2. **Paper flow:** WS realtime → warm-up-seeded core → signal journal + Telegram → system-vs-user opportunity reports. No orders; validates backtest assumptions forward.
3. **Live flow:** approved plan → idempotent execution intent (deterministic client IDs) → Binance (authority for orders/fills/positions/PnL/fees) → user-data WS + periodic REST reconciliation → journal.
4. **Provenance flow:** every signal/plan/approval/order links `(strategy_version, parameter_set_id/hash, feature_snapshot_id, data_snapshot_id)` so any decision replays byte-equivalently.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| V1 (5 symbols, 1m/1H/4H, 4H+1H decisions) | Monolith asyncio service + Postgres + Parquet files is enough; monthly partitions; no Kafka/K8s/microservices (explicitly out of scope without measured bottleneck) |
| Research expansion (10–15 symbols, OI/funding features, 15M refinement) | Grow Parquet/DuckDB side; portfolio correlation model lives in Risk Engine; still monolith |
| 200-conditional-order headroom pressure | Track open algo-order count in risk/execution; leave headroom; never depend on removed `MAX_NUM_ALGO_ORDERS` filter |

### Scaling Priorities

1. **First bottleneck:** 1m candle table growth (~7.9M rows per 5 symbols/3y) — solved by monthly partitioning + Parquet-first research scans, not by splitting services.
2. **Second bottleneck:** WS reconnect/gap storms during volatility — solved by REST re-bootstrap + user-data WS + periodic authoritative reconciliation, not by bigger pipes.

## Anti-Patterns

### Anti-Pattern 1: SDK Types Leaking into the Domain

**What people do:** Pass Binance connector classes / raw kline JSON straight into strategy functions.
**Why it's wrong:** Couples every strategy to one SDK version; breaks determinism tests; makes backtest/paper/live divergence inevitable.
**Do this instead:** Normalize at the `data/` boundary into project-defined frozen types; core imports only `domain/`.

### Anti-Pattern 2: Collapsing Signal/Plan/Order/Position into One Row or Enum

**What people do:** One `trades` table with a mega-status covering detection through fill.
**Why it's wrong:** "APPROVED signal" gets misread as exchange acceptance; analytics cannot separate system vs user vs opportunity performance.
**Do this instead:** Seven separate entities with own state machines (DATA_MODEL §2–§4); cross-entity analytics only via reporting joins (§6).

### Anti-Pattern 3: Mutable Parameters / Env-Driven Strategy Semantics

**What people do:** Tune thresholds via `.env` or live-edit a YAML that backtests already ran against.
**Why it's wrong:** Destroys reproducibility; live orders diverge from published backtests silently.
**Do this instead:** Immutable parameter sets with hash identity; new behavior → new set (+ strategy version bump when material); live requires a registered set; notebooks load via the same loader as the runner.

### Anti-Pattern 4: Trusting the WS Stream for Position Safety

**What people do:** Assume user-data events always arrive; skip REST reconciliation; leave protective orders unverified.
**Why it's wrong:** Missed events → unprotected positions or orphan stops that fire against zero exposure.
**Do this instead:** Periodic authoritative reconciliation (normal + algo + positions), protective-existence verification with HIGH PRIORITY alert on failure, orphan sweeper, SAFE_MODE that blocks entries while monitoring continues.

### Anti-Pattern 5: LLM Anywhere in the Decision Path

**What people do:** Let an LLM pick direction/entry/SL/TP/size or "validate" a signal.
**Why it's wrong:** Violates D001 determinism; unreproducible, un-backtestable, stale-context risk.
**Do this instead:** LLM assists code/docs/tests/explanations only; all trading parameters come from the versioned registry.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Binance USDⓈ-M Futures (market data) | REST bootstrap + WS `kline_closed` events; 24h WS lifetime assumed, heartbeat/reconnect + gap re-bootstrap | Exchange is canonical for market data; re-verify endpoints/schemas before implementation (docs drift) |
| Binance trading (orders/algo/positions) | Execution Manager only; Algo-Order endpoints for STOP/TP (post-2025 migration); dynamic exchangeInfo (tick/step/notional); position-mode detection; 200-conditional-order/symbol limit (verify current) | Idempotent client IDs; no blind retry — reconcile-by-ID first; `closePosition=true` has mode-specific constraints |
| Binance user-data stream | WS for order/position events during volatility; supplements, never replaces, REST reconciliation | Handle replay/out-of-order fills; fills keyed `(order_id, exchange_trade_id)` |
| Telegram | Approval/Alert adapter: notify + SIMULATE/APPROVE/SKIP callbacks; expiring idempotent tokens | At-least-once replay → existing state; no auto-approve on failure; stale/invalid plans unapprovable |
| TradingView (optional) | Visualization/research/webhook experiments only | Never the canonical execution data source (D003) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Strategy → Telegram / Strategy → order API | **FORBIDDEN** | Via Planner → Risk → Approval → Execution chain only |
| LLM → Strategy decision | **FORBIDDEN** | D001; LLM outside decision path entirely |
| UI / API → order API | **FORBIDDEN** | All orders originate from approved plans via Execution Manager |
| Feature/Strategy/Planner/Risk ↔ I/O | Pure functions; no network/DB/SDK imports | Application services wire adapters around the core |
| Backtest ↔ Live core | Shared package code, not duplicated logic | Divergence = gate failure (Phase 1/2 exit gates) |
| Journal ↔ State tables | Journal consumes events; never serves current state | Prevents "event-sourced current state" drift |

## Build-Order Implications for Roadmap (8–12 fine-grained phases)

Reflects IMPLEMENTATION_PLAN 0A → 0B → 1 → 2 → 3 → 4 → 5 (15–24 mo, part-time; forward evidence is the long pole):

1. **0A Research formalization** — freeze candidate families, exact entry/SL/TP rules, cost/execution assumptions, parameter registry schema, golden-fixture format, anti-overfitting constraints. *Gates all parameter work.*
2. **0B Data foundation bootstrap** (parallel, starts immediately) — project scaffold (pyproject/uv/pytest+Ruff+mypy/Docker), 1m/1H/4H backfill, OI collector live, funding/metadata collection, quality checks, backup/restore smoke test.
3. **Domain + parameter registry + fixtures** — `domain/` enums/state machines, immutable param sets with hash loader, golden fixture harness (no-lookahead, candle-close timing, boundary, determinism tests green on stubs).
4. **Feature + Strategy + Planner (pure core)** — deterministic transforms, three family detectors, planner outputs; boundary/determinism suites passing.
5. **Risk Engine** — sizing, floor-quantization + 60% gate, portfolio/daily-stop states, exchange-constraint snapshots, quantization fixtures.
6. **Backtest simulator + experiment registry** — 1m intrabar, limit-fill/cost models, baselines, bootstrap/MC uncertainty; reproducible reports with full identity tuple.
7. **Paper engine (realtime, no orders)** — WS ingestion, warm-up/reconnect/resync, signal journal, Telegram SIMULATE/APPROVE/SKIP, system-vs-user/opportunity reports; 3–6 mo forward evidence.
8. **Approval hardening + reconciliation core** — idempotent expiring approvals, callback replay safety, reconciler + orphan sweeper, SAFE_MODE, RUNBOOK rehearsal (much of this can land during paper phase).
9. **Live execution rollout** — order manager, LIMIT-zone entries, Algo protective exits (mode-aware), partial-fill handling, live constraint snapshots, smallest meaningful capital.
10. **Journal/analytics depth** — MFE/MAE, system-vs-user-vs-opportunity dashboards, uncertainty reporting; kill-gate tracking (3 families / 6 months → NO_TRADE is valid).
11. **Phase 4 expansion (each a gated increment)** — OI/funding features, 15M refinement, correlation model, new families — every addition vs frozen baseline.
12. **Phase 5 autonomous (future, uncommitted)** — requires separate decision record + stability/reliability/failure-mode evidence; roadmap must keep it disabled-by-default.

**Ordering rationale:** pure core before simulators (simulators consume core); registry/fixtures before families (reproducibility harness first); paper before any order code exists; reconciliation/approval hardening before live enablement; analytics depth after live semantics stabilize; autonomy never on the V1 critical path.

## Sources

- Canonical: `docs/architecture/ARCHITECTURE.md`, `docs/architecture/DATA_PIPELINE.md`, `docs/data/DATA_MODEL.md`, `docs/GLOSSARY.md`, `docs/configuration/CONFIGURATION.md`, `docs/testing/TESTING_STRATEGY.md`, `docs/trading/RISK_MANAGEMENT.md`, `docs/trading/EXECUTION_SPEC.md`, `docs/implementation/IMPLEMENTATION_PLAN.md`, `.planning/PROJECT.md`
- External (pinned by Core Docs, re-verify before implementation — never hard-code from memory): Binance WS market streams (24h lifetime), USDⓈ-M trade REST API + Algo-Order endpoints, exchangeInfo filters, futures changelog (Dec 2025: MAX_NUM_ALGO_ORDERS removal → 200 conditional-order limit)
- Known doc inconsistencies to resolve during roadmap (PROJECT.md Context §45, not silently): SystemMode LIVE_AUTONOMOUS vs LIVE_AUTONOMOUS_DISABLED + SAFE_MODE scoping; SIGNAL_AND_ALERTS alert-states vs SignalStatus; EXECUTION_SPEC §3 APPROVED vs GLOSSARY OrderStatus; timezone naming (Bangkok vs Ho_Chi_Minh); RESEARCH §12 non-canonical names; duplicate section numbers

---
*Architecture research for: Deterministic Binance Futures research + semi-automated execution*
*Researched: 2026-09-19*
