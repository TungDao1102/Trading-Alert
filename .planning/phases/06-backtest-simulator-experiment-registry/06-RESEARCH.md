# Phase 6: Backtest Simulator + Experiment Registry - Research

**Researched:** 2026-09-26
**Domain:** Deterministic event-driven backtest simulation + versioned experiment registry + uncertainty-first reporting
**Confidence:** HIGH

## Summary

Phase 6 builds the canonical validation authority: a pure-Python, event-driven backtest simulator (`src/backtest/`) that replays closed 1H/4H strategy candles with 1m intrabar execution resolution, plus a versioned experiment registry (six-field identity, Parquet-canonical) and uncertainty-first reporting (slices, R distribution, block bootstrap, plateau analysis, baselines). All execution semantics are locked by CONTEXT.md D-01–D-05 and owned by canonical docs (`BACKTEST_SPEC.md` §§1–13, `RESEARCH_PROTOCOL.md` FROZEN v1.0.0, `CONFIGURATION.md` §7, `RISK_MANAGEMENT.md`, `METRICS.md`).

The dominant research finding is that **no new external packages are needed**: the simulator core is stdlib + `Decimal` only (extending the Phase-4/5 purity contract), data loading/reporting edges reuse the already-installed Polars 1.44.2 / DuckDB 1.5.5, and bootstrap statistics use stdlib `random` + `statistics` with an explicit seed (NumPy/SciPy are NOT installed in the project venv and must not be added without a legitimacy gate). The conservative SL-first fallback for both-touched bars is both locked (D-01) and externally corroborated: one paired study found 82.54% of TP-first-profitable configurations turned non-positive under SL-first [CITED: https://rulyfi.com/blog/adverse-same-bar-fill], and an independent engine documents "the stop is assumed hit before the target when a bar's range brackets both" [CITED: docs.rs wickra-backtest-core engine]. Block bootstrap (Politis & Romano 1994 stationary bootstrap with geometric block lengths) is the correct uncertainty method for plausibly clustered trade outcomes [CITED: https://doi.org/10.1080/01621459.1994.10476870].

**Primary recommendation:** Build `src/backtest/` as four dependency-free modules (`simulator.py`, `costs.py`, `experiment.py`, `report.py`) that call `src/risk/` sizing+quantization identically, resolve both-touched bars with 1m data then SL-first fallback, hash cost models with `sha256_hex`, key experiments by the six-field tuple, and report with seeded stdlib block-bootstrap — landing the intrabar+costs parity slice first (tracer-first precedent).

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Execution semantics follow `docs/backtest/BACKTEST_SPEC.md` §§3–6 verbatim: strategy decisions use closed-candle information only (no future-candle leakage, Phase-4 D-02/D-07 inherited); both-touched SL/TP bars resolve with 1m intrabar data where available, with SL-first conservative fallback when 1m is missing (fallback is logged on the trade record, never silent). Limit simulation models touch-vs-fill, partial-fill assumption, time-in-force/expiry, canceled-entry-after-invalidation, and no retroactive fill after expiry. Gap policy inherits Phase-2 D-09 / Phase-4 D-04 flag-never-fabricate: missing 1m coverage produces the conservative fallback + explicit report note, never synthesized intrabar prices. — **Reversibility:** one-way — execution semantics are baked into every experiment record; changing them invalidates prior evidence.
- **D-02:** Costs apply from run #1 before any selection decision: entry fee + exit fee + funding treatment + slippage (+ spread/fill assumptions) are registry-parameterized cost keys producing a `costModelHash` (six-field experiment identity). The simulator calls the identical Phase-5 `src/risk/` sizing + quantization functions (same inputs → byte-identical outputs incl. reason codes); no simplified or cost-free ranking pass exists. All exchange-sensitive arithmetic stays `Decimal`, tick/qty-step aware. Realized-risk/quantization rejects (`QUANTIZATION_REJECT`, `MIN_QTY_REJECT`, `NOTIONAL_REJECT`, `UTILIZATION_REJECT`) are first-class trade outcomes in the simulator, not post-filters. — **Reversibility:** costly — cost keys enter registry versions, experiment hashes, and parity fixtures.
- **D-03:** Every experiment record carries the canonical six-field identity tuple per BACKTEST_SPEC §11 / RESEARCH_PROTOCOL §5 / CONFIGURATION §7 (`experimentId`, `strategyVersion`, `parameterSetHash` + runtime `parameterSetId` alongside, `dataSnapshotId`, `codeVersion`, `costModelHash`) plus dataset range, symbol universe, timeframe, full parameters, cost assumptions, results, and notes; a record missing any field fails the acceptance gate. Datasets are Parquet-canonical (immutable raw Hive layout from Phase-2 D-04 + versioned derived sets; `dataSnapshotId` = dataset version/hash); a PostgreSQL experiment mirror for join queryability may land now or later at the planner's discretion (files/Parquet remain canonical either way, same pattern as Phase-3 D-05). Any run without a registered `parameterSetId` + matching hash fails closed (Phase-1 D-07, Phase-3 D-05); reproduction = re-running the recorded six-field tuple yields byte-identical trade lists. — **Reversibility:** one-way — published experiment IDs/hashes are permanent references.
- **D-04:** Reports are uncertainty-first per BACKTEST_SPEC §10 + METRICS §§1–2: trade counts overall and by symbol/quarter/regime/version, mean/median/std of R, bootstrap interval for expectancy (block bootstrap where outcomes are plausibly dependent/clustered), drawdown distribution under resampling, stability across time and symbols — never a single headline number. Parameter-plateau analysis is mandatory (no conclusion resting on an isolated parameter point). Every candidate is compared against declared baselines (no-trade + simple-trend at minimum, BACKTEST_SPEC §9). Research may use the 10–15-symbol research universe but the report MUST show the live-5 slice separately; a strategy is never accepted because the broader universe rescues a weak live universe (§10.1). No winner declared without out-of-sample confirmation (Phase-1 D-08); holdout is never used for parameter choice. — **Reversibility:** reversible — report sections grow additively.
- **D-05:** New pure package `src/backtest/` (e.g. `simulator.py`, `costs.py`, `experiment.py`, `report.py` or planner-discretion split) under the Phase-4 D-10 / Phase-5 D-05 purity contract: stdlib + `Decimal` only inside execution semantics (fill resolution, cost application, quantization calls) — no Polars/pandas/NumPy/SciPy, no Binance SDK types, no SQLAlchemy/Pydantic, no `float` (extend AST no-`float(` guards + mypy strict), UTC datetimes in, deterministic ordering. Polars/DuckDB are allowed at data-loading/reporting edges via adapter (Parquet → frozen candle structs in, trade lists → report frames out), never inside core fill logic. VectorBT stays exploratory-only per BACKTEST_SPEC §13: library sweeps are hypotheses, final validation runs the canonical engine. Dataset splits dev/val/holdout + walk-forward (train → validate → roll) per BACKTEST_SPEC §§7–8; warm-up gates inherited (required-feature-invalid → NO_TRADE inside the simulator too). — **Reversibility:** costly — module paths and purity guards persist in fixtures, experiment records, and Phase-7 paper reuse.

### The Agent's Discretion

- User runs `--auto --chain` (fully autonomous per `modes/auto.md`): all five gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact file layout inside `src/backtest/`, fixture layout under `tests/fixtures/phase6/`, per-key cost-model breakdown, PG experiment-mirror timing, bootstrap resample counts / block scheme, plateau-grid details, baseline-trend specification, and plan slicing (tracer-first vs single slice) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Whether the simulator + registry land as one plan or tracer+registry/report slices is at the planner's discretion; intrabar + costs-from-run-#1 parity slice must stay first.

### Deferred Ideas (OUT OF SCOPE)

- WS/paper realtime loop with three-way attribution → Phase 7; Telegram approval + reconciliation/orphan-sweeper/SAFE_MODE rehearsal → Phase 8; live Algo exits + placement-time revalidation → Phase 9.
- Journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10 (D-04 reports are the input, not the full journal).
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 6.
- None — discussion stayed within phase scope.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BKTS-01 | Backtest simulator resolves intrabar SL/TP ordering with 1m data, models limit fills/partials/expiry/invalidation, and applies fees/funding/slippage before any selection decision | Intrabar resolution pattern + limit-simulation checklist + cost-model pattern below; `src/risk/` parity reuse; TESTING_STRATEGY §7 execution-simulation test list |
| BKTS-02 | Every experiment is reproducible from dataset + strategy + parameter set + cost + execution versions and is compared against no-trade and simple-trend baselines | Six-field identity + `sha256_hex` canonical hashing + Hive Parquet `dataSnapshotId` + baseline pattern below |
| BKTS-03 | Reports show trade counts and slices (symbol/period/regime/version), R distribution, bootstrap intervals, and parameter-plateau analysis — never a single headline number | Uncertainty-first reporting pattern + stationary block bootstrap + plateau-analysis pattern below |

## Project Constraints (from AGENTS.md)

- **Determinism**: same market snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs. Simulator must additionally be seed-pinned (bootstrap RNG) and iteration-order deterministic (sort positions/trades by `(symbol, ...)` — Phase-5 D-04 precedent).
- **No-AI core**: LLM never decides direction/entry/SL/TP/size/risk/parameters/signal-validity. Phase 6 honors this structurally: the simulator executes the frozen strategy, never invents rules; missing rules stay TBD per `AGENT_INSTRUCTIONS.md`.
- **Quantization**: floor to stepSize → 60% realized-risk check → min-qty/notional reject → NO_TRADE over round-up; identical logic backtest/paper/live — enforced by calling `src/risk/` directly, never re-implementing.
- **Fail closed**: uncertain data/connection/account/risk → NO_TRADE; missing 1m coverage → conservative fallback + report note, never fabricated prices.
- **Tech stack**: Python 3.13, official Binance SDK behind adapters (simulator never imports it), PostgreSQL + Parquet/DuckDB, Polars/pandas/NumPy/SciPy at edges only, VectorBT exploratory-only, pytest+Ruff+mypy, `Decimal`/tick arithmetic for exchange-sensitive values.
- **`float` ban**: binary floating point forbidden for quantities/prices/notional/risk; `tests/test_domain_no_float.py` AST guards extend to `src/backtest/`. Statistics (R multiples, bootstrap) are report-edge values that never gate an order — still use `Decimal` where they touch sizing, `float`-free stdlib `statistics`/`random` at the reporting edge.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fill resolution + cost application + quantization calls | `src/backtest/` pure core (stdlib+Decimal) | — | Execution semantics are the determinism-critical path; D-05 purity contract forbids all third-party imports here |
| Candle/1m data loading (Parquet → frozen structs) | Data-loading adapter edge | `src/data/` Hive store | Polars/DuckDB live at the edge; core receives `list[Candle]` + 1m sequences, never frames |
| Experiment identity + hashing + record assembly | `src/backtest/experiment.py` | `src/domain/` (`canonical.py`, `registry.py`, `ids.py`) | Reuse canonical hash + registry loader; cost-model hash mirrors `parameterSetHash` construction |
| Report computation (slices, R distribution, bootstrap, plateau) | `src/backtest/report.py` edge | Polars/DuckDB frames out | Bootstrap RNG seeded stdlib `random`; deterministic ordering; never inside fill logic |
| Experiment persistence (Parquet-canonical + optional PG mirror) | Files first, PG mirror optional | `src/db/` Single-Base ORM pattern | Phase-3 D-05 precedent: files canonical, DB is a join-queryable mirror |
| Baselines (no-trade, simple-trend) | `src/backtest/` (same engine, degenerate configs) | — | Baselines must run through the identical simulator so cost/execution assumptions match |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| stdlib (`dataclasses`, `decimal`, `datetime`, `hashlib`, `json`, `random`, `statistics`) | Python 3.13 stdlib [VERIFIED: .venv `Python 3.13.15`] | Frozen simulator/report types, Decimal math, canonical hashing, seeded bootstrap RNG, R-distribution stats | D-05 purity contract: the only imports allowed inside execution semantics; `random.Random(seed)` gives reproducible bootstrap without NumPy |
| `src/risk/` (`sizing.size_position`, `quantization.quantize`, `portfolio.check_portfolio`, `gating`) | In-repo (Phase 5) [VERIFIED: src/risk/sizing.py:30-87, src/risk/quantization.py:32-155] | Canonical sizing + floor+reject quantization + portfolio caps, called identically | D-02 parity: same inputs → byte-identical outputs incl. reason codes; re-implementing is the top rewrite-causing error |
| `src/core/` (`features`, `strategy.evaluate`, `planner.plan`, `types.Candle/MarketSnapshot/PlanResult`) | In-repo (Phase 4) [VERIFIED: src/core/types.py:67-112 `Candle`, src/core/planner.py:1-22] | Closed-candle features, pure setup detection, full-zone plan contract the simulator executes per bar | D-01: simulator executes these, never re-derives setup logic |
| `src/domain/` (`canonical.sha256_hex`, `registry.load_parameter_set`, `ids.make_signal_id/derive_child_id`, `enums.*`) | In-repo (Phase 3) [VERIFIED: src/domain/canonical.py:39-89, src/domain/registry.py:345-382, src/domain/ids.py:19-60] | Canonical hashing, fail-closed registry loading, deterministic IDs, reason-code vocabulary | Six-field identity + costModelHash reuse this exact machinery |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Polars | 1.44.2 [VERIFIED: .venv import] | Parquet → `Candle` loading; trade-list → report-frame slicing at edges | Data-loading/reporting adapters only, never inside `simulator.py` fill logic |
| DuckDB | 1.5.5 [VERIFIED: .venv import] | Coverage/availability queries over Hive layout; dataset-version QA | Sourcing 1m coverage + gap accounting for D-01 fallback notes |
| structlog | present [VERIFIED: .venv import] | Lineage events (fill decisions, fallback logging, experiment record emission) | Same pattern as `quantize()` §11-rule-5 lineage call-site import (src/risk/quantization.py:192-220) |
| pytest + pytest-asyncio (auto) | 9.1.1 [VERIFIED: .venv import; pyproject.toml:46-52 `asyncio_mode = "auto"`, `testpaths = ["tests"]`] | Golden fixtures, determinism suites, execution-simulation tests | Extend `tests/fixtures/phase6/` per TESTING_STRATEGY §§2/7/9 |
| Ruff + mypy strict | repo-pinned [VERIFIED: pyproject.toml:54-82] | Lint + `strict = true` on `src/` | Extend `test_domain_no_float.py` AST guards to `src/backtest/` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `random`+`statistics` bootstrap | NumPy/SciPy bootstrap | NumPy/SciPy are NOT installed [VERIFIED: .venv import fails] and are banned inside pure core by D-05; adding them needs a legitimacy gate + purity-boundary discipline for zero determinism gain at 4H/1H trade counts |
| Project-owned engine | VectorBT / Backtrader / NautilusTrader as foundation | BACKTEST_SPEC §13 forbids: "A library-specific vectorized result is not sufficient evidence when execution semantics such as partial fill, expiry, quantization, or intrabar resolution differ" [VERIFIED: BACKTEST_SPEC.md:156-158]; VectorBT stays exploratory-only |
| Parquet-canonical + optional PG mirror | PG-only experiment store | Files remain the reproducibility artifact (immutable, hash-addressable); PG mirror is join-queryability only — planner's discretion per D-03 |

**Installation:**
```bash
# No new packages. Phase 6 uses stdlib + in-repo code + already-locked deps.
# If the planner later wants NumPy/SciPy for report statistics, add via:
# uv add "numpy>=1.26" "scipy>=1.14"   # REQUIRES package-legitimacy gate first
```

## Package Legitimacy Audit

No external packages are installed by this phase — the Standard Stack above is stdlib + in-repo + already-locked dependencies (Polars, DuckDB, structlog, pytest). Audit result: **nothing to verify, nothing removed, nothing flagged.**

| Package | Registry | Verdict | Disposition |
|---------|----------|---------|-------------|
| *(none proposed)* | — | — | No installs; audit N/A |

**Packages removed due to SLOP verdict:** none.
**Packages flagged as suspicious SUS:** none.
**Standing warning for planner:** NumPy/SciPy appear in AGENTS.md tech-stack prose but are NOT in `pyproject.toml` dependencies and NOT installed in `.venv` [VERIFIED: `import numpy`/`import scipy` → `ModuleNotFoundError`]. If any plan proposes them, the planner must run the Package Legitimacy Gate (`gsd_run query package-legitimacy check --ecosystem pypi numpy scipy` + `pip index versions`) and gate the install behind `checkpoint:human-verify`. Default recommendation: do not add them — stdlib covers Phase-6 statistics.

## Architecture Patterns

### System Architecture Diagram

```text
Hive Parquet (1H/4H strategy + 1m intrabar + funding)   Registry TOML sets
        │                                                        │
        ▼                                                        ▼
┌─ Loading edge (Polars/DuckDB) ─┐              ┌─ registry.load_parameter_set ─┐
│ Parquet → list[Candle] (frozen) │              │ fail-closed; cost keys parsed │
│ 1m map: {(symbol, bar) → [Candle]}│             └───────────────┬───────────────┘
│ coverage gaps → gap ledger      │                              │
└───────────────┬─────────────────┘              ┌─ costs.build_cost_model ──────┐
                │                                │ fee/slippage/funding/partial  │
                ▼                                │      → costModelHash          │
┌─ simulator.run ───────────────────────────────┴───────────────┐│
│ for each closed strategy bar (time order, deterministic):      ││
│   1. features+strategy.evaluate (closed candles only)          ││
│   2. planner.plan → PlanResult (RR gate, expiry, invalidation) ││
│   3. risk.size_position + quantize (IDENTICAL fns; rejects are ││
│      first-class outcomes, not post-filters)                   ││
│   4. entry-state machine: LIMIT touch-vs-fill / partial /      ││
│      expiry / cancel-after-invalidation                        ││
│   5. exit resolution per bar: 1m intrabar where available →    ││
│      SL-first conservative fallback + logged fallback flag     ││
│   6. costs.apply (entry/exit fee + funding + slippage, Decimal)││
│   7. emit trade record (SignalId/TradePlanId/costs/R/MFE/MAE…) ││
└───────────────────────────────┬────────────────────────────────┘│
                                ▼                                 │
              ┌─ experiment.assemble ─────────────┐               │
              │ six-field identity + ranges +     │◄──────────────┘
              │ universe + params + results+notes │
              └───────────────┬───────────────────┘
                              ▼
              ┌─ report.build ────────────────────┐
              │ slices + R distribution + seeded  │
              │ block bootstrap + plateau +       │
              │ baselines (no-trade, simple-trend)│
              │ + dual-universe (research + live-5)│
              └───────────────────────────────────┘
```

File-to-implementation mapping belongs in PLAN.md, not in the diagram. Entry points: Parquet datasets + registry sets. Exit: experiment record + uncertainty-first report. Decision points: warm-up gate (NO_TRADE), risk rejects (first-class), entry fill vs expiry/invalidation, SL/TP intrabar resolution, cost application.

### Recommended Project Structure

```text
src/
├── backtest/            # NEW — pure package (stdlib + Decimal + src/core/_decimal.py only)
│   ├── __init__.py
│   ├── simulator.py     # event loop: bar iteration, entry/exit state machines, 1m resolution
│   ├── costs.py         # CostModel frozen type + build_cost_model + apply (Decimal)
│   ├── experiment.py    # six-field identity assembly, record type, reproduce-bytes check
│   └── report.py        # slices, R distribution, seeded block bootstrap, plateau, baselines
├── core/                # consumed, never modified for Phase 6 (features/strategy/planner)
├── risk/                # called identically (sizing/quantization/portfolio/gating)
├── domain/              # reused (canonical/registry/ids/enums)
└── data/                # loading edge consumes Hive store + coverage views
tests/
├── fixtures/phase6/     # NEW — golden files (strategy candles + 1m intrabar + params + costs → trades/reports)
└── test_backtest_*.py   # simulator parity, intrabar, limit-model, determinism, registry, report suites
```

### Pattern 1: Event-driven bar loop with closed-candle gating

**What:** The simulator iterates strategy bars in time order; at each bar it feeds only candles with `close_time_utc <= current_bar.close_time_utc` into `strategy.evaluate`, then advances working orders against the bar (entry fills) and resolves open-position exits (SL/TP) — exactly the per-bar order documented by independent engines: fill pending orders → update indicators → resolve intrabar exits along a declared path → evaluate new entries [CITED: https://github.com/wickra-lib/wickra-backtest/blob/main/ARCHITECTURE.md].
**When to use:** Always — this is the simulator's main loop.
**Example:**
```python
# Source: project pattern (TESTING_STRATEGY §§3-4) + wickra ordering (cited above)
for bar in strategy_bars:  # time-ordered, deterministic
    snapshot = MarketSnapshot(symbol=s, setup_candles=closed_through(bar),
                              context_candles=closed_through_4h(bar), ...)
    setup = strategy.evaluate(snapshot, parameter_set, account_state)
    plan = planner.plan(setup, ...)          # RR gate, expiry, invalidation
    sized = size_position(...); final = quantize(...)  # identical src/risk/ fns
    entries.update(bar, plan, final)         # touch-vs-fill / expiry / invalidation
    exits.resolve(bar, intrabar_1m(bar))     # 1m path else SL-first fallback (logged)
```

### Pattern 2: Cost model as a hashed frozen value object

**What:** `CostModel` is a frozen dataclass (Decimal fields) built from registry cost keys; `costModelHash = sha256_hex(canonical cost snapshot)` using the identical canonicalizer as `parameterSetHash` [VERIFIED: src/domain/canonical.py:39-89]. Costs apply from run #1 (R4) inside both sizing (`modeled_costs_per_unit` input to `size_position` [VERIFIED: src/risk/sizing.py:30-36]) and realized-PnL computation — never retrofitted.
**When to use:** Every experiment; the hash joins the six-field identity.
**Example:**
```python
# Source: src/domain/canonical.py + src/domain/registry.py hash pattern
cost_model_hash = sha256_hex({
    "fee_rate_entry": fee_entry, "fee_rate_exit": fee_exit,
    "funding_treatment": funding_mode, "slippage_model": slippage_id,
    "spread_fill_assumptions": spread_id, "partial_fill_fraction": partial,
})
```

### Pattern 3: Experiment record = six-field identity + full context

**What:** Every record carries verbatim [VERIFIED: docs/research/RESEARCH_PROTOCOL.md:286-297]:
```text
experimentId
strategyVersion
parameterSetHash
dataSnapshotId
codeVersion
costModelHash
```
plus `parameterSetId` alongside, dataset range, symbol universe, timeframe, full parameters, cost assumptions, results, notes. "A backtest report is not considered reproducible without all six" [VERIFIED: docs/configuration/CONFIGURATION.md:100-113]. `dataSnapshotId` = version/hash of the immutable Hive dataset; `codeVersion` = engine commit.
**When to use:** Every run; missing field fails the acceptance gate (D-03).

### Pattern 4: Uncertainty-first report with seeded block bootstrap

**What:** Report shows trade counts (overall + by symbol/quarter/regime/version), mean/median/std of R, bootstrap interval for expectancy, drawdown distribution under resampling, stability across time/symbols — never a headline number [VERIFIED: BACKTEST_SPEC.md:89-99]. Under plausible dependence/clustering use block resampling, not IID [VERIFIED: BACKTEST_SPEC.md:99; RESEARCH_PROTOCOL.md:217-224]. The stationary bootstrap (Politis & Romano 1994) resamples blocks of geometrically-distributed random length so the pseudo-series stays stationary, and is less sensitive to block-size misspecification than fixed-block schemes [CITED: https://doi.org/10.1080/01621459.1994.10476870; https://public.econ.duke.edu/~ap172/Politis_White_2004.pdf]. Implement with `random.Random(experiment_seed)` (seed recorded in the experiment) + `statistics.mean/stdev/quantiles` — deterministic, stdlib-only, no NumPy.
**When to use:** Every candidate report; print `SE ≈ σ / sqrt(n)` diagnostic alongside the block-bootstrap SE so the dependence adjustment is visible (protocol requirement).

### Pattern 5: Parameter-plateau + dual-universe + baseline comparison

**What:** Group sweep results by parameter region, never single best point; a narrow isolated optimum is a robustness warning (R2) [VERIFIED: RESEARCH_PROTOCOL.md:66-73]. Every candidate runs against no-trade + simple-trend baselines through the SAME engine [VERIFIED: BACKTEST_SPEC.md:77-84]. Research may use 10–15 symbols but the report shows the live-5 slice separately; broader-universe rescue of a weak live universe is rejection [VERIFIED: BACKTEST_SPEC.md:111-119].

### Anti-Patterns to Avoid

- **TP-first / inferred-path intrabar resolution:** awarding TP when both levels touch inflates winners — 82.54% of TP-first-profitable configs failed under SL-first [CITED: https://rulyfi.com/blog/adverse-same-bar-fill]. D-01 mandates 1m-then-SL-first; do the opposite of the optimistic default.
- **Cost-free ranking pass:** any sweep or leaderboard computed before costs is selection bias (violates R4 + D-02). Costs from run #1, no exceptions.
- **VectorBT-as-verdict:** library sweeps are hypotheses; BACKTEST_SPEC §13 requires final validation on the canonical engine [VERIFIED: BACKTEST_SPEC.md:156-158].
- **Holdout peeking:** holdout chooses nothing; walk-forward windows fixed before evaluation [VERIFIED: RESEARCH_PROTOCOL.md:48-56].
- **Post-hoc search spaces:** sweeps only inside research-declared ranges; never invent the grid after seeing results [VERIFIED: RESEARCH_PROTOCOL.md:299-304].
- **Rounded-up quantities:** `quantize()` never rounds up (TESTING_STRATEGY §9: "A rounded-up quantity is a test failure") [VERIFIED: docs/testing/TESTING_STRATEGY.md:121-136].

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Canonical hashing (params, costs, IDs) | Custom JSON-dump hash | `src/domain/canonical.sha256_hex` | Trailing-precision (`"1.50" ≠ "1.5"`), UTC normalization, float/set rejection already handled [VERIFIED: src/domain/canonical.py:39-89] |
| Sizing / quantization / portfolio gates | Simulator-local math | `src/risk/sizing.py`, `quantization.py`, `portfolio.py`, `gating.py` | Byte-parity with paper/live is the whole point; the distinguishing cases (Pitfall 2 nonzero-cost utilization) are pinned by parity fixtures |
| Registry loading + hash verification | Custom TOML reader | `src/domain/registry.load_parameter_set` / `verify_parameter_set` | Fail-closed gates, ASCII-key rule, sidecar exclusion already enforced [VERIFIED: src/domain/registry.py:296-343] |
| Signal/plan IDs | UUIDs / counters | `src/domain/ids.make_signal_id` + `derive_child_id` | Content-hash IDs make reproduction byte-checkable; input list is locked (strategyVersion + parameterSetId + symbol + source_timeframe + source_candle_close_utc + setup_fingerprint) [VERIFIED: src/domain/ids.py:19-46] |
| Bootstrap statistics | Custom RNG/stats or new SciPy dep | stdlib `random.Random(seed)` + `statistics` | Deterministic, dependency-free; SciPy adds nothing at these sample sizes and breaks the purity boundary |
| Structured logging | Custom logger | structlog (already installed) | Lineage schema standard; local-import-at-callsite pattern preserves purity [VERIFIED: src/risk/quantization.py:192-220] |
| Parquet I/O + slicing frames | Custom CSV/pickle datasets | Polars 1.44.2 + DuckDB 1.5.5 (installed, locked) | Hive-partitioned immutable store already exists [VERIFIED: src/data/store.py:1-26] |

**Key insight:** Phase 6 is an assembly phase, not an invention phase. Every hard sub-problem (hashing, sizing, registry, storage, logging) already has a canonical in-repo solution with fixtures pinning its edge cases; the only genuinely new logic is the bar-loop state machines (entry/exit resolution) and the report statistics — and both follow documented external patterns cited above.

## Common Pitfalls

### Pitfall 1: Both-touched bars resolved optimistically

**What goes wrong:** Simulator awards TP when a bar touches both SL and TP; expectancy inflates; a strategy looks viable until paper/live.
**Why it happens:** OHLC bars contain no intrabar sequence; the coder picks whatever branch is convenient (often TP-checked-first).
**How to avoid:** D-01: resolve with 1m data; when missing, SL-first fallback + `fallback_applied=true` on the trade record + report note. Corroborated externally: SL-first is the documented conservative choice [CITED: docs.rs wickra-backtest-core engine], and paired TP-first/SL-first testing is the recommended screen [CITED: https://rulyfi.com/blog/adverse-same-bar-fill].
**Warning signs:** Win rate jumps on symbols/timeframes with wide-range bars; ambiguous-bar rate unreported.

### Pitfall 2: Look-ahead through the 1m stream

**What goes wrong:** 1m candles at or after the strategy-bar close leak into the entry decision for that bar.
**Why it happens:** The 1m map is keyed loosely; the simulator passes "the bar's 1m data" including the 1m candle that closes exactly at/after the decision boundary.
**How to avoid:** Strict invariant: strategy decisions consume only candles with `close_time_utc <= strategy_bar.close_time_utc`; 1m resolution consumes only 1m candles strictly inside `(entry_bar.open, exit_bar.close]`. Pin with prefix-invariance + no-lookahead suites extended to the 1m path (TESTING_STRATEGY §3 pattern).
**Warning signs:** Determinism suite passes on strategy candles but fails when 1m data is appended after T.

### Pitfall 3: Re-implemented risk math drifting from live

**What goes wrong:** Simulator copies the sizing formula with a "simplification" (e.g. utilization as `rounded/raw` instead of `realized_risk/allowed_risk`); backtest and live disagree on rejects.
**Why it happens:** Copy-paste with small edits; the distinguishing case only triggers with nonzero costs.
**How to avoid:** Import `size_position` + `quantize` directly (D-02). The parity fixture with nonzero costs pins the distinguishing case [VERIFIED: src/risk/quantization.py:115-136 gate 3]. Add a `test_risk_parity`-style Phase-6 test calling both paths.
**Warning signs:** Any `Decimal` arithmetic for sizing inside `src/backtest/` that is not a delegation call.

### Pitfall 4: `float` leaking through statistics into decisions

**What goes wrong:** A `float` R-multiple or bootstrap value flows back into a sizing/expiry gate; 1-ulp differences flip NO_TRADE to an order.
**Why it happens:** `statistics.mean` returns `float`; convenient to reuse.
**How to avoid:** One-way boundary: core decision types stay `Decimal`; report-edge floats never flow upstream. Extend `test_domain_no_float.py` AST guards to `src/backtest/` and keep bootstrap/R math in `report.py` only.
**Warning signs:** `float(` or `/` true-division on money values inside `simulator.py`/`costs.py`.

### Pitfall 5: Non-deterministic iteration order

**What goes wrong:** Dict/set iteration over symbols/positions makes trade lists order-dependent; byte-equivalence fails intermittently.
**Why it happens:** Python set ordering; multi-symbol loops without explicit sort.
**How to avoid:** Sort all iteration: bars by `(close_time_utc, symbol)`, positions by `(symbol, position_side)` (Phase-5 D-04 precedent), bootstrap resample indices from a seeded RNG. Determinism suite: run twice, compare canonical bytes.
**Warning signs:** Flaky byte-equivalence tests; dicts keyed by symbol iterated directly.

### Pitfall 6: Missing-1m gaps silently treated as clean

**What goes wrong:** Bars without 1m coverage resolve without any marker; the report overstates evidence quality.
**Why it happens:** Fallback path returns a fill without recording that it was a fallback.
**How to avoid:** D-01 + Phase-2 D-09 flag-never-fabricate: every fallback sets an explicit flag on the trade record and aggregates into a report-level "intrabar coverage" note (coverage % + fallback count). Gap ledger from the loading edge feeds this.
**Warning signs:** Report has no intrabar-coverage section; fallback flag absent from trade schema.

### Pitfall 7: Cost keys drifting outside the registry

**What goes wrong:** A new cost assumption (e.g. `partial_fill_fraction`, `funding_treatment`) lives in code constants; two experiments with different constants share a `costModelHash`.
**Why it happens:** Registry whitelist (`STRATEGY_KEYS`) predates the full cost model — only `"fee_rate_entry"`, `"fee_rate_exit"`, `"expected_slippage"` exist [VERIFIED: src/domain/registry.py:95-97]; funding/partial-fill/spread keys are missing.
**How to avoid:** Extend `STRATEGY_KEYS` + `DECIMAL_KEYS`/`INT_KEYS` with the missing cost keys (new `baseline-vN.toml` sets, never ambient edits); `costModelHash` covers the full snapshot. Fail closed on unknown cost keys exactly like strategy keys.
**Warning signs:** A cost constant defined in `src/backtest/` rather than read from the loaded `ParameterSet`.

## Code Examples

Verified patterns from in-repo sources (out-of-repo citations noted):

### Closed-candle Candle construction (loading-edge target type)

```python
# Source: src/core/types.py:67-112 (verbatim field contract)
Candle(symbol="BTCUSDT", interval="1h",
       open_time_utc=..., close_time_utc=...,   # aware UTC, open < close
       open=..., high=..., low=..., close=..., volume=...)  # all Decimal
# Guards: high >= low; open/close within [low, high]; volume >= 0
```

### Risk parity call (simulator delegates, never re-implements)

```python
# Source: src/risk/sizing.py:30-36 + src/risk/quantization.py:32-40
sized = size_position(trade_plan=plan, account_state=acct,
                      entry_ref=entry_mid, modeled_costs_per_unit=costs_per_unit)
final = quantize(sized=sized, constraint_snapshot=snap, allowed_risk=allowed,
                 risk_per_unit=rpu,
                 minimum_risk_utilization_after_rounding=Decimal("0.6"),
                 reference_price=entry_mid)
# Gate order first-failure-wins: MIN_QTY_REJECT → NOTIONAL_REJECT → UTILIZATION_REJECT
# Rejects are first-class outcomes: SizedResult(is_no_trade=True, quantity=None, ...)
```

### Cost-model hash (mirrors parameterSetHash construction)

```python
# Source: src/domain/canonical.py:87-89 sha256_hex + registry.py:365-374 payload shape
cost_model_hash = sha256_hex({
    "fee_rate_entry": ..., "fee_rate_exit": ..., "expected_slippage": ...,
    "funding_treatment": ..., "slippage_model": ..., "partial_fill_fraction": ...,
})
```

### Seeded stationary block bootstrap (report edge, stdlib-only)

```python
# Source: Politis & Romano 1994 stationary bootstrap (geometric block lengths)
# https://doi.org/10.1080/01621459.1994.10476870
import random, statistics
rng = random.Random(experiment_seed)  # seed recorded in experiment record
def stationary_bootstrap_mean(rs, probable=0.1, resamples=10000):
    n = len(rs); means = []
    for _ in range(resamples):
        sample, i = [], rng.randrange(n)
        while len(sample) < n:  # geometric block length, mean 1/probable
            sample.append(rs[i]); i = (i + 1) % n
            if rng.random() < probable: i = rng.randrange(n)
        means.append(statistics.fmean(sample))
    lo, hi = statistics.quantiles(means, n=40)[0], statistics.quantiles(means, n=40)[-1]
    return statistics.fmean(rs), lo, hi  # point + interval; floats stay in report.py
```

### Experiment record identity block

```python
# Source: RESEARCH_PROTOCOL §5 + CONFIGURATION §7 (verbatim field names)
record = {"experimentId": ..., "strategyVersion": ..., "parameterSetId": ...,
          "parameterSetHash": ..., "dataSnapshotId": ..., "codeVersion": ...,
          "costModelHash": ..., "time_range_start_utc": ..., "time_range_end_utc": ...,
          "universe_hash": ..., "run_type": ..., "result_summary_json": ...}
# DATA_MODEL §2.12 experiment_runs columns (verbatim, lines 315-328 of DATA_MODEL.md)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Vectorized pandas backtest as verdict | Canonical event-driven engine as verdict; vectorized only for exploration | BACKTEST_SPEC §13 (project baseline) | Sweeps are hypotheses; acceptance evidence uses identical execution semantics |
| Single expectancy number | Uncertainty-first: slices + R distribution + block bootstrap + plateau | BACKTEST_SPEC §10 + METRICS §8 (project baseline) | Prevents small-sample overconfidence; SE ≈ σ/√n diagnostic makes it visible |
| TP-first / inferred intrabar path | 1m resolution, SL-first conservative fallback (logged) | D-01 (this phase) | Removes the dominant optimistic bias; 82.54% TP-first-only profitability gap is the external warning [CITED: rulyfi stress test] |
| Fixed-block bootstrap default | Stationary (geometric-block) bootstrap preferred under dependence | Politis & Romano 1994; less sensitive to block-size misspecification [CITED: Politis & White 2004] | More robust intervals when trade clustering scale is unknown |
| Cost-free ranking then retrofit | Costs from run #1, hashed into identity | R4 + D-02 (this phase) | Selection decisions rest on net-of-cost evidence; hash binds costs to the record |

**Deprecated/outdated:**
- Legacy `binance-connector` / `binance-futures-connector` (archived 2026-04-30) — simulator never touches the network/SDK anyway; noted so no plan proposes them for funding-rate pulls (use `src/data/collector.py` outputs instead).
- IID-only bootstrap for trade expectancy — invalid under clustering; use block/stationary scheme per protocol.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 1m intrabar coverage sourced from existing Hive store + `collector.py` without schema changes; gap ledger suffices for D-01 fallback accounting | Architecture | Medium — if 1m history is sparse for the research window, fallback rate is high and evidence quality drops; planner should add a coverage-probe task first |
| A2 | Missing cost keys (`funding_treatment`, `partial_fill_fraction`, spread/slippage-model IDs) can extend `STRATEGY_KEYS` + new `baseline-vN.toml` sets without breaking existing hashes | Pitfall 7 | Low — additive keys + new set IDs preserve old hashes; but planner must confirm the exact key list |
| A3 | PG experiment mirror (if built now) follows the Phase-3 Single-Base ORM + content-hash-PK + mapper pattern onto DATA_MODEL §2.12 `experiment_runs` | Architecture | Low — precedent exists (`src/db/`); deferral to later is explicitly allowed by D-03 |
| A4 | `run_type` values + baseline-trend specification + plateau-grid density + bootstrap resample counts are planner-discretion choices with no canonical doc values | Report patterns | Low — protocol reserves numerics as TBD; any reasonable declared choice satisfies the gate |
| A5 | Stdlib `statistics`/`random` performance suffices for 10k-resample bootstraps at 4H/1H trade counts (hundreds–thousands of trades) | Standard Stack | Low — trivially fast at this scale; revisit only if resample counts grow 100x |

## Open Questions

1. **Exact cost-key list for `costModelHash`**
   - What we know: `fee_rate_entry`, `fee_rate_exit`, `expected_slippage` already whitelisted [VERIFIED: src/domain/registry.py:95-97]; funding treatment, partial-fill fraction, slippage-model ID, spread assumptions needed per BACKTEST_SPEC §5 + RESEARCH_PROTOCOL §2.
   - What's unclear: Whether funding uses a mode-enum key vs rate key; whether partial-fill fraction is Decimal vs fixed assumption string.
   - Recommendation: Planner defines the key list in the costs-slice plan; researcher discretion per CONTEXT.md.

2. **PG experiment-mirror timing**
   - What we know: D-03 allows now-or-later; files remain canonical either way.
   - What's unclear: Whether Phase-6 plans include the mirror or defer it.
   - Recommendation: Defer unless a plan needs join-queryability now; Parquet records + DuckDB reads cover V1 reporting.

3. **Bootstrap resample counts and mean block length**
   - What we know: Protocol requires block bootstrap under dependence + SE diagnostic; stationary bootstrap less sensitive to block choice [CITED].
   - What's unclear: No canonical numbers (correctly TBD per protocol).
   - Recommendation: Planner declares defaults (e.g. 10k resamples, mean block ≈ observed cluster scale) recorded per experiment; not a gate.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 (project venv) | Everything | ✓ | 3.13.15 [VERIFIED: `.venv` `python --version`] | — |
| Polars | Loading/reporting edges | ✓ | 1.44.2 [VERIFIED: `.venv` import] | — |
| DuckDB | Coverage QA, dataset reads | ✓ | 1.5.5 [VERIFIED: `.venv` import] | — |
| pytest (+asyncio auto) | Golden/determinism suites | ✓ | 9.1.1 [VERIFIED: `.venv` import; `asyncio_mode="auto"` in pyproject] | — |
| structlog | Lineage events | ✓ | installed [VERIFIED: `.venv` import] | stdlib logging + JSON formatter |
| NumPy / SciPy | Nothing (not recommended) | ✗ | — | stdlib `random`+`statistics` (primary recommendation, not a fallback) |
| PostgreSQL 17 | Optional PG mirror only | Unprobed | — | Defer mirror; files canonical |

**Missing dependencies with no fallback:** none (all Phase-6 needs are present).
**Missing dependencies with fallback:** NumPy/SciPy absent — by design; stdlib is the primary path.

## Validation Architecture

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio (auto mode) |
| Config file | `pyproject.toml` (`testpaths=["tests"]`, `asyncio_mode="auto"`) |
| Quick run command | `.venv/Scripts/python -m pytest tests/test_backtest_* -x -q` |
| Full suite command | `.venv/Scripts/python -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BKTS-01 | Both-touched bar → 1m resolution; missing 1m → SL-first + fallback flag | unit (golden) | `pytest tests/test_backtest_intrabar.py -x` | ❌ Wave 0 |
| BKTS-01 | Limit touch-no-fill / partial / expiry / invalidation-cancel / no-retroactive-fill | unit (golden ×5 cases) | `pytest tests/test_backtest_limits.py -x` | ❌ Wave 0 |
| BKTS-01 | Fees/funding/slippage applied from run #1; risk-parity byte-identical | unit (parity) | `pytest tests/test_backtest_parity.py -x` | ❌ Wave 0 |
| BKTS-02 | Six-field identity complete; missing field fails gate; reproduce → byte-identical trades | unit | `pytest tests/test_backtest_registry.py -x` | ❌ Wave 0 |
| BKTS-02 | Baselines (no-trade + simple-trend) run through same engine | unit (golden) | `pytest tests/test_backtest_baselines.py -x` | ❌ Wave 0 |
| BKTS-03 | Slices + R stats + bootstrap interval + plateau + dual-universe sections present | unit (golden report) | `pytest tests/test_backtest_report.py -x` | ❌ Wave 0 |
| BKTS-01/02/03 | No-lookahead + prefix-invariance incl. 1m path; determinism (run-twice bytes) | invariant | extend `test_no_lookahead.py` / `test_prefix_invariance.py` pattern | ❌ Wave 0 |
| All | No-`float(` AST guard over `src/backtest/`; mypy strict clean; ruff clean | static | `pytest tests/test_backtest_no_float.py` + `mypy` + `ruff check` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** quick run command for the touched suite
- **Per wave merge:** full suite command
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/fixtures/phase6/` — strategy candles + 1m intrabar (incl. both-touched bars, gap bars) + params + costs → expected trade lists/reports, byte-exact
- [ ] `tests/test_backtest_intrabar.py`, `test_backtest_limits.py`, `test_backtest_parity.py`, `test_backtest_registry.py`, `test_backtest_baselines.py`, `test_backtest_report.py`, `test_backtest_no_float.py`
- [ ] Framework install: none — pytest 9.1.1 present in `.venv`

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No credentials in this phase (no exchange/Telegram calls) |
| V3 Session Management | No | Stateless pure functions; no sessions |
| V4 Access Control | No | No multi-user surface |
| V5 Input Validation | Yes | Frozen dataclass guards (Decimal-only, UTC-aware, non-empty) + fail-closed registry loader + unknown-cost-key rejection; extend to `src/backtest/` types |
| V6 Cryptography | No | SHA256 via `hashlib` for identity hashing only (not secrecy); never hand-roll — stdlib used |
| V7 Errors/Logging | Partial | Fail-closed raises + structlog lineage; ensure no secret-adjacent values in logs (no secrets exist in this phase) |
| V8 Data Protection | Partial | Immutable Parquet (no overwrite — `FileExistsError` on republish [VERIFIED: src/data/store.py:82-87]); experiment IDs permanent references |
| V10 Malicious Code | Partial | No new dependencies = no new supply-chain surface (strongest control available) |

### Known Threat Patterns for pure-Python backtest stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Fabricated intrabar prices filling gaps | Tampering | Flag-never-fabricate (D-01/D-09): fallback + report note, never synthesis |
| Result cherry-picking (headline expectancy) | Tampering | Uncertainty-first report gate: missing sections fail acceptance |
| Unregistered parameter/cost sets in runs | Tampering | Fail-closed loader gates (Phase-1 D-07, Phase-3 D-05) |
| Supply-chain via new stats deps | Tampering | No new deps; stdlib-only statistics |

## Sources

### Primary (HIGH confidence)

- `docs/backtest/BACKTEST_SPEC.md` §§1–13 — full backtest contract (read this session)
- `docs/research/RESEARCH_PROTOCOL.md` FROZEN v1.0.0 §§1–6 — splits, costs, execution, acceptance, identity (read this session)
- `docs/configuration/CONFIGURATION.md` §7 — six-field experiment linkage (read this session)
- `docs/data/DATA_MODEL.md` §2.12 — `experiment_runs` columns (read this session, lines 311-328)
- `docs/trading/RISK_MANAGEMENT.md` §§1–12 — sizing, costs, quantization, caps (read this session)
- `docs/testing/TESTING_STRATEGY.md` §§2/7/9 — golden fixtures, execution-simulation tests, quantization fixtures (read this session)
- In-repo code read this session: `src/risk/sizing.py`, `src/risk/quantization.py`, `src/risk/types.py`, `src/domain/canonical.py`, `src/domain/registry.py`, `src/domain/ids.py`, `src/domain/enums.py`, `src/domain/trade_plan.py`, `src/core/types.py`, `src/core/planner.py` (partial), `src/data/store.py` (partial)
- `.venv` probes this session: Python 3.13.15, Polars 1.44.2, pytest 9.1.1, DuckDB 1.5.5, structlog present; NumPy/SciPy absent

### Secondary (MEDIUM confidence)

- [CITED: https://doi.org/10.1080/01621459.1994.10476870] — Politis & Romano stationary bootstrap (geometric blocks, stationarity of pseudo-series)
- [CITED: https://public.econ.duke.edu/~ap172/Politis_White_2004.pdf] — Politis & White block-length selection; stationary bootstrap less sensitive to misspecification
- [CITED: https://github.com/wickra-lib/wickra-backtest/blob/main/ARCHITECTURE.md] — event-driven per-bar order (fill → indicators → intrabar exits → entries); same-engine-live parity
- [CITED: https://docs.rs/wickra-backtest-core/latest/wickra_backtest_core/engine/index.html] — SL-before-TP conservative fill when bar brackets both
- [CITED: https://rulyfi.com/blog/adverse-same-bar-fill] — 82.54% TP-first-profitable configs non-positive under SL-first; paired TP-first/SL-first screen + three-bucket decision

### Tertiary (LOW confidence)

- None — all load-bearing claims are primary; external citations corroborate (not originate) locked decisions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — in-repo code read + `.venv` probes + locked STACK.md; only gap is cost-key list (flagged A2, planner-discretion by CONTEXT.md).
- Architecture: HIGH — event-driven bar loop is both canonical-doc-shaped and externally corroborated by two independent engines.
- Pitfalls: HIGH — six of seven pitfalls pinned to in-repo fixtures/guards; optimism-bias pitfall quantified by external paired study.

**Research date:** 2026-09-26
**Valid until:** 30 days (stable domain: frozen protocol + locked decisions; external bootstrap literature is decades-stable)
