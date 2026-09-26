# Phase 6: Backtest Simulator + Experiment Registry - Context

**Gathered:** 2026-09-26
**Status:** Ready for planning

## Phase Boundary

Phase 6 delivers the canonical validation authority: a deterministic 1m-intrabar backtest simulator plus a versioned experiment registry. Both-touched SL/TP bars resolve with 1m intrabar data (SL-first conservative fallback when 1m is missing); limit fills/partials/expiry/invalidation are modeled; fees/funding/slippage apply from run #1 before any selection decision. Every experiment reproduces from dataset + strategy + parameter set + cost + execution versions and is compared against no-trade and simple-trend baselines. Reports are uncertainty-first (trade counts and slices, R distribution, bootstrap intervals, parameter-plateau analysis — never a single headline number), and no winner is declared without out-of-sample confirmation. No WS/paper loop (Phase 7), no Telegram/execution/Algo orders (Phases 8–9), no journal-depth/kill-gate ops (Phase 10). Success means selection decisions rest on costs-included, uncertainty-first evidence that paper (Phase 7) and live (Phase 9) can trust.

## Implementation Decisions

### Intrabar resolution + execution semantics

- **D-01:** Execution semantics follow `docs/backtest/BACKTEST_SPEC.md` §§3–6 verbatim: strategy decisions use closed-candle information only (no future-candle leakage, Phase-4 D-02/D-07 inherited); both-touched SL/TP bars resolve with 1m intrabar data where available, with SL-first conservative fallback when 1m is missing (fallback is logged on the trade record, never silent). Limit simulation models touch-vs-fill, partial-fill assumption, time-in-force/expiry, canceled-entry-after-invalidation, and no retroactive fill after expiry. Gap policy inherits Phase-2 D-09 / Phase-4 D-04 flag-never-fabricate: missing 1m coverage produces the conservative fallback + explicit report note, never synthesized intrabar prices. — **Reversibility:** one-way — execution semantics are baked into every experiment record; changing them invalidates prior evidence.
- [auto] Intrabar resolution — Q: "1m intrabar with SL-first conservative fallback vs setup-candle-only resolution?" → Selected: "1m intrabar with SL-first fallback" (recommended default)

### Cost model versioning + risk parity

- **D-02:** Costs apply from run #1 before any selection decision: entry fee + exit fee + funding treatment + slippage (+ spread/fill assumptions) are registry-parameterized cost keys producing a `costModelHash` (six-field experiment identity). The simulator calls the identical Phase-5 `src/risk/` sizing + quantization functions (same inputs → byte-identical outputs incl. reason codes); no simplified or cost-free ranking pass exists. All exchange-sensitive arithmetic stays `Decimal`, tick/qty-step aware. Realized-risk/quantization rejects (`QUANTIZATION_REJECT`, `MIN_QTY_REJECT`, `NOTIONAL_REJECT`, `UTILIZATION_REJECT`) are first-class trade outcomes in the simulator, not post-filters. — **Reversibility:** costly — cost keys enter registry versions, experiment hashes, and parity fixtures.
- [auto] Cost model — Q: "Registry-versioned costs with identical src/risk parity vs simulator-local cost estimates?" → Selected: "Registry-versioned costs with risk parity" (recommended default)

### Experiment identity + storage + reproducibility

- **D-03:** Every experiment record carries the canonical six-field identity tuple per BACKTEST_SPEC §11 / RESEARCH_PROTOCOL §5 / CONFIGURATION §7 (`experimentId`, `strategyVersion`, `parameterSetHash` + runtime `parameterSetId` alongside, `dataSnapshotId`, `codeVersion`, `costModelHash`) plus dataset range, symbol universe, timeframe, full parameters, cost assumptions, results, and notes; a record missing any field fails the acceptance gate. Datasets are Parquet-canonical (immutable raw Hive layout from Phase-2 D-04 + versioned derived sets; `dataSnapshotId` = dataset version/hash); a PostgreSQL experiment mirror for join queryability may land now or later at the planner's discretion (files/Parquet remain canonical either way, same pattern as Phase-3 D-05). Any run without a registered `parameterSetId` + matching hash fails closed (Phase-1 D-07, Phase-3 D-05); reproduction = re-running the recorded six-field tuple yields byte-identical trade lists. — **Reversibility:** one-way — published experiment IDs/hashes are permanent references.
- [auto] Experiment registry — Q: "Six-field identity with Parquet-canonical datasets (+ optional PG mirror) vs PG-only experiment store?" → Selected: "Six-field identity, Parquet-canonical + optional PG mirror" (recommended default)

### Reporting + uncertainty-first + baselines

- **D-04:** Reports are uncertainty-first per BACKTEST_SPEC §10 + METRICS §§1–2: trade counts overall and by symbol/quarter/regime/version, mean/median/std of R, bootstrap interval for expectancy (block bootstrap where outcomes are plausibly dependent/clustered), drawdown distribution under resampling, stability across time and symbols — never a single headline number. Parameter-plateau analysis is mandatory (no conclusion resting on an isolated parameter point). Every candidate is compared against declared baselines (no-trade + simple-trend at minimum, BACKTEST_SPEC §9). Research may use the 10–15-symbol research universe but the report MUST show the live-5 slice separately; a strategy is never accepted because the broader universe rescues a weak live universe (§10.1). No winner declared without out-of-sample confirmation (Phase-1 D-08); holdout is never used for parameter choice. — **Reversibility:** reversible — report sections grow additively.
- [auto] Reporting standard — Q: "Uncertainty-first (slices + R distribution + bootstrap + plateau + baselines + dual-universe) vs headline-expectancy ranking?" → Selected: "Uncertainty-first with baselines" (recommended default)

### Engine location/purity + dataset splits + VectorBT boundary

- **D-05:** New pure package `src/backtest/` (e.g. `simulator.py`, `costs.py`, `experiment.py`, `report.py` or planner-discretion split) under the Phase-4 D-10 / Phase-5 D-05 purity contract: stdlib + `Decimal` only inside execution semantics (fill resolution, cost application, quantization calls) — no Polars/pandas/NumPy/SciPy, no Binance SDK types, no SQLAlchemy/Pydantic, no `float` (extend AST no-`float(` guards + mypy strict), UTC datetimes in, deterministic ordering. Polars/DuckDB are allowed at data-loading/reporting edges via adapter (Parquet → frozen candle structs in, trade lists → report frames out), never inside core fill logic. VectorBT stays exploratory-only per BACKTEST_SPEC §13: library sweeps are hypotheses, final validation runs the canonical engine. Dataset splits dev/val/holdout + walk-forward (train → validate → roll) per BACKTEST_SPEC §§7–8; warm-up gates inherited (required-feature-invalid → NO_TRADE inside the simulator too). — **Reversibility:** costly — module paths and purity guards persist in fixtures, experiment records, and Phase-7 paper reuse.
- [auto] Engine boundary — Q: "Strict pure src/backtest/ with Polars-at-edges vs vectorized engine with pandas/NumPy inside?" → Selected: "Strict pure src/backtest/, Polars at edges" (recommended default)

### Agent's Discretion

- User runs `--auto --chain` (fully autonomous per `modes/auto.md`): all five gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact file layout inside `src/backtest/`, fixture layout under `tests/fixtures/phase6/`, per-key cost-model breakdown, PG experiment-mirror timing, bootstrap resample counts / block scheme, plateau-grid details, baseline-trend specification, and plan slicing (tracer-first vs single slice) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Whether the simulator + registry land as one plan or tracer+registry/report slices is at the planner's discretion; intrabar + costs-from-run-#1 parity slice must stay first.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Backtest contract (what to build)

- `docs/backtest/BACKTEST_SPEC.md` — §§1–13: candle-close rule, intrabar ambiguity + SL-first fallback, fees/funding/slippage minimum, limit simulation, dataset splits, walk-forward, baselines, uncertainty reporting (§10 + research-vs-live §10.1), six-field experiment identity (§11), acceptance gates (§12), VectorBT boundary (§13). Phase 6 implements it.
- `docs/backtest/METRICS.md` — §§1–2: required trade-level fields (SignalId/TradePlanId/costs/R/MFE/MAE…), win rate / average R / expectancy-after-costs / profit factor / max drawdown; system-vs-user report split (system report is the backtest scope).
- `docs/research/RESEARCH_PROTOCOL.md` — FROZEN v1.0.0; dataset/cost/execution assumptions, acceptance methodology, six-field identity (§5), no-winner rule; the gate Phase-6 evidence must satisfy.
- `docs/configuration/CONFIGURATION.md` — §7 experiment identity + cost-model hashing; §§2/4/5 registry identity + immutability; strategy-vs-runtime split (cost keys are registry parameters).

### Domain + registry contract (what to conform to)

- `docs/data/DATA_MODEL.md` — canonical entities §§2.3–2.4 (Signal/TradePlan fields the simulator consumes), §5 JSON-as-TEXT rule; experiment linkage maps onto these shapes.
- `docs/GLOSSARY.md` — canonical enums; authority for reason-code and status naming in simulator outputs.
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; determinism (D001), quantization-deferral, approval-safety bind this phase.

### Risk + core inputs (what to reuse identically)

- `docs/trading/RISK_MANAGEMENT.md` — §§1–12: sizing formula, costs, portfolio caps, cluster rule, DAILY_STOP, fail-closed, quantization + 60% baseline; the simulator calls this math identically (D-02).
- `docs/strategy/TRADING_STRATEGY_SPEC.md` — TEMPLATE/NOT FROZEN slot structure the core implements per family; backtest executes it, never redefines it.
- `docs/research/families/trend-pullback.md` — Family A rules (tracer expectations source).
- `docs/research/families/breakout-retest.md` — Family B rules.
- `docs/research/families/range-mr.md` — Family C rules.
- `docs/trading/SIGNAL_AND_ALERTS.md` — signal/plan schema and reason-code expectations the simulator emits.

### Data inputs (what to consume)

- `docs/architecture/DATA_PIPELINE.md` — Hive Parquet layout, quality rules, UTC storage, raw-vs-derived, per-symbol availability; D-01/D-03 consume it (1m intrabar source + fallback accounting).
- `docs/trading/EXECUTION_SPEC.md` — Algo-Order/position-mode context (Phase 9); the simulator models LIMIT-zone + protective semantics without pre-building execution paths.

### Methodology + platform

- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism + fail-closed posture; Decimal-only and UTC-at-boundary rules extended by D-05.
- `docs/TECHNOLOGY_STACK.md` — Python 3.13 + uv; Polars/DuckDB at research/backtest edges (NOT inside pure execution semantics); VectorBT exploratory-only; pytest-asyncio auto mode; Ruff + mypy strict on `src/`.
- `docs/testing/TESTING_STRATEGY.md` — golden fixtures + deterministic test protocol; Phase-6 fixtures extend it.
- `docs/implementation/AGENT_INSTRUCTIONS.md` — Research → Spec → Code separation; missing rules stay TBD.

### Project context

- `.planning/PROJECT.md` — project context, constraints (determinism, quantization, fail-closed, exchange authority), key decisions.
- `.planning/REQUIREMENTS.md` — BKTS-01, BKTS-02, BKTS-03.
- `.planning/ROADMAP.md` — Phase 6 goal and success criteria.
- `.planning/phases/01-research-formalization/01-CONTEXT.md` — Phase 1 locks (frozen protocol, 7-slot template, gate enforcement D-07, no-winner rule D-08).
- `.planning/phases/02-data-foundation/02-CONTEXT.md` — Phase 2 locks (live-5 universe D-01, bounded depth D-02, Hive Parquet D-04, PG/Parquet split D-05, UTC/HCMC D-06, 5-min OI D-07, flag-never-fabricate D-09, fail-closed quality D-10, coverage CLI/views D-11) the simulator consumes.
- `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` — Phase 3 locks (D-01–D-12: frozen dataclasses, content-hash IDs, TOML registry + SHA256, strategy/runtime split, fixture triple + 4 determinism suites, Decimal-only) the simulator builds on.
- `.planning/phases/04-pure-core-feature-strategy-planner/04-CONTEXT.md` — Phase 4 locks (D-01–D-10: pure `src/core/`, closed-candle-only, warm-up valid flags, tracer-first families, planner full-zone contract D-08 with `DEFERRED_TO_RISK` D-09) the simulator executes.
- `.planning/phases/05-risk-engine/05-CONTEXT.md` — Phase 5 locks (D-01–D-05: canonical sizing with modeled costs, risk-owned floor+reject quantization, registry-parameterized portfolio caps + DAILY_STOP, strict fail-closed, dependency-free `src/risk/`) the simulator calls identically.

## Existing Code Insights

### Reusable Assets

- `src/core/features.py` + `src/core/strategy.py` + `src/core/planner.py` (closed-candle features, pure `evaluate`, zone+TP1/TP2+RR-gate+`plan_hash` contract, `DEFERRED_TO_RISK` fields) — the simulator executes these per bar; never re-derives setup logic.
- `src/risk/sizing.py` + `src/risk/quantization.py` + `src/risk/portfolio.py` + `src/risk/gating.py` (canonical sizing, floor+reject quantization, portfolio caps, DAILY_STOP/fail-closed) — the simulator calls these identically for parity; reason codes are first-class outcomes.
- `src/domain/registry.py` (`load_parameter_set`, `STRATEGY_KEYS`, fail-closed gates) — cost keys extend the whitelist; versioned TOML sets under `params/<family>/baseline-v1.toml`.
- `src/domain/ids.py` + `src/domain/canonical.py` (`make_signal_id`, `derive_child_id`, `sha256_hex`) — deterministic ID/hash discipline for experiment + cost-model hashes.
- `src/domain/signal.py` + `src/domain/trade_plan.py` + `src/domain/enums.py` — frozen Signal/TradePlan shapes + reason vocabulary the simulator emits.
- `src/data/backfill.py` + `src/data/store.py` + `src/data/coverage.py` + `src/data/quality.py` (bounded bootstrap, Hive Parquet store, coverage CLI/views, fail-closed quality) — 1H/4H strategy + 1m intrabar sourcing with gap accounting for D-01.
- `src/data/metadata.py` + `src/data/collector.py` (versioned exchange metadata, OI/funding collection) — constraint snapshots + funding leg of the cost model.
- `src/adapters/binance_usdm.py` — adapter-boundary isolation precedent D-05 follows (simulator never imports the SDK).
- `tests/test_domain_no_float.py` (AST no-`float(` guards), `tests/test_prefix_invariance.py`, `tests/test_no_lookahead.py`, `tests/test_candle_close_timing.py`, `tests/test_fixture_harness.py`, `tests/conftest.py` — extend with `tests/fixtures/phase6/` golden files (input candles + 1m intrabar + parameters + costs → expected trade lists/reports, byte-exact).

### Established Patterns

- TDD RED→GREEN per behavior with atomic commits; frozen dataclasses; INSERT-only versioning; fail-closed loader/quality posture; structured lineage logging.
- Decimal-only + UTC-at-boundary + Asia/Ho_Chi_Minh display-edge discipline (Phases 2–5).
- Tracer-first rollout precedent (Phases 4–5): land intrabar+costs parity slice first, then registry/report slices.
- Single-Base ORM + offline parity-gate discipline for any DB touch (experiment PG mirror, if any).

### Integration Points

- New pure `src/backtest/` package (simulator + costs + experiment registry + uncertainty-first reporting, dependency-free core) consuming closed-candle sequences + 1m intrabar + registry sets + cost model + constraint snapshots, emitting deterministic trade lists + experiment records + reports.
- New `tests/fixtures/phase6/` golden files (strategy candles + 1m intrabar incl. both-touched bars + parameters + costs → expected fills/reports, byte-exact).
- Phase 7 consumes the simulator + experiment identity for the paper forward-observation loop (no tuning on the paper stream); Phase 8 binds experiment hashes in approvals; Phase 10 deepens MFE/MAE + kill-gate analytics on top of D-04 reports.

## Specific Ideas

- No "I want it like X" references — `--auto` mode, open to standard approaches within the locked decisions above (same delegation pattern as Phases 1–5).
- Prior delegation precedent (Phases 1–5 CONTEXTs): user delegates implementation choices to recommended defaults; planner/researcher discretion governs layout and slicing.

## Deferred Ideas

- WS/paper realtime loop with three-way attribution → Phase 7; Telegram approval + reconciliation/orphan-sweeper/SAFE_MODE rehearsal → Phase 8; live Algo exits + placement-time revalidation → Phase 9.
- Journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10 (D-04 reports are the input, not the full journal).
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 6.
- None — discussion stayed within phase scope.

---

*Phase: 6-Backtest Simulator + Experiment Registry*
*Context gathered: 2026-09-26*
