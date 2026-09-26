# Phase 7: Paper Forward Observation - Context

**Gathered:** 2026-09-26
**Status:** Ready for planning

## Phase Boundary

Phase 7 runs the schedule long pole: a realtime paper forward-observation loop over wall-clock time (3–6-month envelope) that ingests WS market data, evaluates closed candles only through the identical Phase-4 core + Phase-5 risk functions, journals signals/plans with system-vs-user-executed-vs-opportunity attribution, and accumulates forward evidence with zero tuning on the paper stream. No live orders, no Algo-Order placement, no approval-idempotency hardening (Phase 8), no journal-depth/kill-gate ops (Phase 10). Success means forward evidence accumulates without contaminating itself: no unexplained gaps, no material backtest↔paper divergence, registry diff proving the running stream was never retuned, and the signal-frequency-based minimum-evidence gate satisfied.

## Implementation Decisions

### Realtime ingestion + reconnect/resync + warm-up + gap journaling

- **D-01:** Single-asyncio-loop WS ingestion via the official `binance-sdk-derivatives-trading-usds-futures` WS Streams surface behind `src/adapters/` (never imported by domain/core/risk/backtest/paper-core), with REST kline resync on reconnect and warm-up gates reusing the Phase-4 validity flags (long-warm-up features report invalid until history suffices; invalid → NO_TRADE). Gaps are journaled with explicit gap records and flagged per the Phase-2 D-09 / Phase-4 D-04 flag-never-fabricate rule — never synthesized candles, never fabricated signals. Uncertain/stale feed state fails closed to NO_TRADE with reason code (Phase-5 D-04 posture extended to the feed). — **Reversibility:** costly — the feed/j gap schema enters paper journal rows and the no-unexplained-gaps exit gate.
- [auto] Realtime ingestion — Q: "SDK WS Streams behind adapters with REST resync + journaled gaps vs direct WS with in-loop synthesis?" → Selected: "SDK WS behind adapters, REST resync, journaled gaps, fail-closed" (recommended default)

### Engine reuse + backtest parity (no divergence)

- **D-02:** The paper loop calls the identical functions the backtest executes: `src/core/` feature/strategy/planner evaluation on closed candles, `src/risk/` sizing + quantization + portfolio gates, and backtest fill/cost semantics for simulated fills (1m-intrabar SL-first resolution, registry-versioned costs from run #1 — Phase-6 D-01/D-02). No paper-local setup logic, no simplified sizing, no cost-free path. Paper-vs-backtest divergence on overlapping history is an acceptance gate (IMPLEMENTATION_PLAN Phase 2 exit gate: no material divergence), reported as an incident and fixed in the engine, never patched at the call site. All exchange-sensitive arithmetic stays `Decimal`, tick/qty-step aware; UTC internally, Asia/Ho_Chi_Minh at the display edge. — **Reversibility:** one-way — paper evidence is only trustworthy if it ran the canonical engine; changing the engine binding invalidates the soak.
- [auto] Engine reuse — Q: "Identical core+risk+backtest-semantics calls with divergence gate vs paper-local simplified engine?" → Selected: "Identical engine calls with divergence gate" (recommended default)

### Three-way attribution + paper journal storage

- **D-03:** Every paper record carries the canonical identity (strategyVersion + parameterSetId + parameterSetHash + experiment linkage per CONFIGURATION §7 / RESEARCH_PROTOCOL §5, SignalId/plan hash per Phase-3/Phase-4) plus the full timestamp lineage signal/approve(simulated)/order(fill-simulated)/fill. Attribution splits three ways: system-generated (what the engine emitted), user-executed/simulated-execution (what a SIMULATE fill would have done, incl. approval-delay modeling), and opportunity (skipped/expired plans retained with reason codes — never dropped). Operational rows land in PostgreSQL on the Phase-3 seven-entity shapes (+ JournalEvent gap/attribution rows; single-Base ORM + offline parity-gate discipline for any migration); Parquet extracts mirror the journal for DuckDB/Polars analysis (files remain the analytical canonical, same pattern as Phase-6 D-03). — **Reversibility:** costly — attribution schema enters journal rows, extracts, and Phase-10 analytics inputs.
- [auto] Attribution + storage — Q: "Three-way attribution in PG operational rows + Parquet mirror vs log-file-only paper journal?" → Selected: "Three-way attribution, PG rows + Parquet mirror" (recommended default)

### No-tuning freeze proof on the running stream

- **D-04:** The soak pins its registry version at start (parameterSetId + parameterSetHash, cost keys included via the 07.1 binding gate). Any registry diff against the pinned set halts the stream's evidence claim: the change is rejected-or-logged with a new stream epoch, and evidence windows are per-epoch — a mid-soak parameter change never retroactively contaminates earlier evidence. A soak monitor (registry diff check, CI or scheduled job at planner discretion) proves zero tuning on the paper stream; the PAPER-03 acceptance artifact is the diff log showing the pinned hash untouched for the whole window. Research may continue offline on other sets; only the pinned set's stream counts as forward evidence. — **Reversibility:** one-way — published forward-evidence windows reference the pinned hash permanently.
- [auto] No-tuning enforcement — Q: "Pinned-registry epoch with diff-proof monitor vs convention-based no-tuning discipline?" → Selected: "Pinned registry + diff-proof monitor, per-epoch evidence" (recommended default)

### Run scope + Telegram SIMULATE boundary + soak operations

- **D-05:** Live-5 universe (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT) with the research universe reported separately if ever used; 4H regime + 1H setup closed-candle evaluation (1m for simulated fill resolution only, per backtest semantics). Telegram sends SIMULATE-style read-only notifications carrying the Phase-8 APRV-01 field set (symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, reason codes) — APPROVE/SKIP idempotency hardening stays Phase 8; paper approvals are simulated timestamps for attribution, never order authorizations. Soak operations: 3–6-month wall-clock envelope with the minimum-evidence gate defined by actual signal frequency (IMPLEMENTATION_PLAN exit gate), no unexplained gaps/reconciliation drift, runbook exercised; Phase-8 construction may overlap the soak but its enablement gates on paper evidence. — **Reversibility:** reversible — universe/timeframe/notify scope grows additively; the evidence gate thresholds are set by the researcher.
- [auto] Run scope — Q: "Live-5 + 4H/1H + SIMULATE-notify with Phase-8 hardening deferred vs full approval loop now?" → Selected: "Live-5, 4H/1H, SIMULATE-notify only, hardening in Phase 8" (recommended default)

### Agent's Discretion

- User runs `--auto --chain` (fully autonomous per `modes/auto.md`): all five gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact module layout of the paper loop (e.g. new `src/paper/` package shape, loop/supervisor/resync/journal-monitor splits), WS client structure inside `src/adapters/`, journal table vs JSON-as-TEXT field choices, Parquet extract layout, soak-monitor mechanics (CI job vs scheduled process), SIMULATE message formatting, epoch-rollover mechanics, and plan slicing (tracer-first realtime slice vs vertical slices) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Pre-answered from prior phases (not re-asked): purity contracts (stdlib + `Decimal` only in core/risk/backtest/paper-core, no `float`, AST no-`float(` guards + mypy strict); TDD RED→GREEN with atomic commits; frozen dataclasses; content-hash IDs; TOML registry + SHA256 with 07.1 cost-binding gate; six-field experiment identity permanence; Hive Parquet raw-immutable + versioned derived; flag-never-fabricate gaps; fail-closed posture; single-Base ORM + parity-gate discipline.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Paper contract (what to build)

- `docs/implementation/IMPLEMENTATION_PLAN.md` — Phase 2 realtime paper signal engine: WS market data, warm-up/reconnect/resync, strategy + planner + risk reuse, signal journal, Telegram notifications, system-vs-user opportunity reports; exit gate (signal-frequency evidence, no unexplained gaps, no backtest↔paper divergence, runbook exercised). The Phase-7 build list.
- `docs/trading/SIGNAL_AND_ALERTS.md` — signal/plan schema, SIMULATE/APPROVE/SKIP payload fields (§106 field set), no-stale-approval rule, approve/expire timestamp lineage PAPER-02 consumes.
- `docs/configuration/CONFIGURATION.md` — §7 experiment identity + cost-model hashing; §§2/4/5 registry identity + immutability; every paper signal/plan traceable to strategyVersion + parameterSetId + parameterSetHash.
- `docs/research/RESEARCH_PROTOCOL.md` — FROZEN v1.0.0; paper run structure (§34 sequential blocks), cost exposure (§85+), slippage calibration from paper/live fills (§105), quantization identity (§128), identity tuple (§246); the gate paper evidence must satisfy.

### Exchange connectivity (how to ingest)

- `docs/integration/BINANCE.md` — Binance WS/REST surface, user-data streams, exchangeInfo dynamics; re-verify SDK minor + changelog before wiring (Dec-2025 Algo-migration precedent).
- `docs/TECHNOLOGY_STACK.md` — `binance-sdk-derivatives-trading-usds-futures>=17.3` (never legacy connectors), adapter-layer isolation, asyncio single loop, python-telegram-bot SIMULATE loop, tenacity bounded retries (fail-closed, never infinite on order-adjacent paths).

### Domain + risk + backtest inputs (what to reuse identically)

- `docs/data/DATA_MODEL.md` — canonical seven entities + JSON-as-TEXT; paper journal rows conform to these shapes.
- `docs/GLOSSARY.md` — canonical enums; authority for reason-code and status naming in paper outputs.
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; determinism (D001), quantization, approval-safety bind this phase.
- `docs/trading/RISK_MANAGEMENT.md` — §§1–12: sizing, costs, portfolio caps, DAILY_STOP, fail-closed, quantization + 60% baseline; paper calls this math identically.
- `docs/backtest/BACKTEST_SPEC.md` — §§1–13: closed-candle rule, intrabar SL-first, costs-from-run-#1, limits/partials/expiry, splits, baselines, uncertainty reporting, six-field identity, VectorBT boundary; the divergence baseline.
- `docs/backtest/METRICS.md` — §§1–2: trade-level fields, system-vs-user report split (paper attribution extends it).
- `docs/strategy/TRADING_STRATEGY_SPEC.md` — TEMPLATE/NOT FROZEN slot structure paper executes, never redefines.
- `docs/architecture/DATA_PIPELINE.md` — Hive Parquet layout, quality rules, UTC storage, coverage/gap accounting the feed layer consumes.
- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism + fail-closed posture; Decimal-only and UTC-at-boundary rules.
- `docs/testing/TESTING_STRATEGY.md` — golden fixtures + deterministic test protocol; Phase-7 fixtures (reconnect/resync, gap journaling, attribution, freeze-gate) extend it.
- `docs/operations/RUNBOOK.md` — failure drills the soak exercises (exit-gate requirement).
- `docs/integration/TELEGRAM.md` — SIMULATE notification mechanics (APPROVE/SKIP hardening stays Phase 8).

### Project context

- `.planning/PROJECT.md` — project context, constraints (determinism, quantization, fail-closed, exchange authority), key decisions.
- `.planning/REQUIREMENTS.md` — PAPER-01, PAPER-02, PAPER-03.
- `.planning/ROADMAP.md` — Phase 7 goal and success criteria (no per-phase Canonical-refs block; refs above assembled from REQUIREMENTS + IMPLEMENTATION_PLAN + scout).
- `.planning/phases/02-data-foundation/02-CONTEXT.md` — Phase 2 locks (live-5 universe, Hive Parquet, coverage/quality fail-closed, 5-min OI, flag-never-fabricate) the feed consumes.
- `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` — Phase 3 locks (frozen dataclasses, content-hash IDs, TOML registry + SHA256, fixture triple + determinism suites) paper records conform to.
- `.planning/phases/04-pure-core-feature-strategy-planner/04-CONTEXT.md` — Phase 4 locks (pure `src/core/`, closed-candle-only, warm-up flags, planner full-zone contract) paper evaluates.
- `.planning/phases/05-risk-engine/05-CONTEXT.md` — Phase 5 locks (canonical sizing with modeled costs, floor+reject quantization, portfolio caps + DAILY_STOP, fail-closed, dependency-free `src/risk/`) paper calls identically.
- `.planning/phases/06-backtest-simulator-experiment-registry/06-CONTEXT.md` — Phase 6 locks (intrabar SL-first, registry-versioned costs with risk parity, six-field identity, uncertainty-first reports, pure `src/backtest/`) paper reuses + divergence-gates against.
- `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-CONTEXT.md` — 07.1 locks (assemble()-time cost-binding gate, pinned-hash permanence) the D-04 freeze proof builds on.

## Existing Code Insights

### Reusable Assets

- `src/core/features.py` + `src/core/strategy.py` + `src/core/planner.py` (closed-candle features, pure `evaluate`, zone+TP1/TP2+RR-gate+`plan_hash` contract) — paper evaluates these per closed candle; never re-derives setup logic.
- `src/risk/sizing.py` + `src/risk/quantization.py` + `src/risk/portfolio.py` + `src/risk/gating.py` (canonical sizing, floor+reject quantization, portfolio caps, DAILY_STOP/fail-closed) — paper calls identically; reason codes are first-class paper outcomes.
- `src/backtest/simulator.py` + `src/backtest/costs.py` + `src/backtest/experiment.py` + `src/backtest/binding.py` (intrabar SL-first, CostModel hash verify-or-compute, assemble() binding gate, six-field identity) — simulated-fill semantics + pinned-hash discipline paper inherits.
- `src/domain/registry.py` (`load_parameter_set`, `STRATEGY_KEYS`, fail-closed gates) — stream-pinning + diff-proof authority (D-04).
- `src/domain/signal.py` + `src/domain/trade_plan.py` + `src/domain/approval.py` + `src/domain/journal.py` + `src/domain/enums.py` — frozen paper-record shapes + reason vocabulary.
- `src/domain/ids.py` + `src/domain/canonical.py` (`make_signal_id`, `derive_child_id`, `sha256_hex`) — deterministic ID/hash discipline for paper records.
- `src/data/backfill.py` + `src/data/store.py` + `src/data/coverage.py` + `src/data/quality.py` (bounded bootstrap, Hive Parquet store, coverage CLI/views, fail-closed quality) — warm-up history + gap accounting for the feed.
- `src/data/collector.py` (OI/funding collection) — reconnect/collect loop precedent for the WS supervisor.
- `src/data/metadata.py` (versioned exchange metadata) — constraint snapshots for paper sizing.
- `src/adapters/binance_usdm.py` — adapter-boundary isolation precedent the WS client follows (paper-core never imports the SDK).
- `src/db/models.py` + `src/db/mappers.py` (single-Base ORM, Enum translation, Fill dedup constraint) + `src/db/alembic/versions/0002_domain_registry.py` — journal persistence pattern + parity-gate discipline for any paper migration.
- `tests/test_domain_no_float.py` (AST guards), `tests/test_prefix_invariance.py`, `tests/test_no_lookahead.py`, `tests/test_candle_close_timing.py`, `tests/test_fixture_harness.py`, `tests/conftest.py` — extend with `tests/fixtures/phase7/` golden files (reconnect/resync sequences, gap journals, attribution records, freeze-gate epochs, byte-exact).

### Established Patterns

- TDD RED→GREEN per behavior with atomic commits; frozen dataclasses; INSERT-only versioning; fail-closed loader/quality posture; structured lineage logging.
- Decimal-only + UTC-at-boundary + Asia/Ho_Chi_Minh display-edge discipline (Phases 2–6).
- Tracer-first rollout precedent (Phases 4–6): land the realtime closed-candle slice first, then attribution/freeze-monitor slices.
- Single-asyncio-loop + tenacity bounded-retry precedent from the stack; adapter-edge isolation for all SDK types.

### Integration Points

- New realtime loop (e.g. `src/paper/` at planner discretion: loop + WS supervisor + resync + journal + freeze-monitor, core/risk/backtest-semantics dependency-free) consuming WS candles + registry-pinned sets + constraint snapshots, emitting attributed paper records + SIMULATE notifications.
- WS client extension inside `src/adapters/` (paper-core never imports the SDK directly).
- New `tests/fixtures/phase7/` golden files (feed sequences incl. reconnects/gaps → expected journal/attribution/epoch records, byte-exact).
- Phase 8 hardens the SIMULATE notify into idempotent APPROVE/SKIP + reconciliation/orphan-sweeper/SAFE_MODE on top of D-03 journal rows; Phase 10 deepens MFE/MAE + kill-gate analytics on top of D-03 attribution.

## Specific Ideas

- No "I want it like X" references — `--auto` mode, open to standard approaches within the locked decisions above (same delegation pattern as Phases 1–6 and 07.1).
- Prior delegation precedent (Phases 1–7.1 CONTEXTs): user delegates implementation choices to recommended defaults; planner/researcher discretion governs layout and slicing.

## Deferred Ideas

- Telegram APPROVE/SKIP idempotency hardening + reconciliation/orphan-sweeper/SAFE_MODE rehearsal → Phase 8 (paper rows are its input, SIMULATE payloads prefigure APRV-01 fields).
- Live Algo exits + placement-time revalidation → Phase 9; journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10.
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 7.
- None — discussion stayed within phase scope.

---

*Phase: 7-Paper Forward Observation*
*Context gathered: 2026-09-26*
