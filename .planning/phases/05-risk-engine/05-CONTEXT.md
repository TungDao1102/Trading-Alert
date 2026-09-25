# Phase 5: Risk Engine - Context

**Gathered:** 2026-09-25
**Status:** Ready for planning

## Phase Boundary

Phase 5 delivers identical-everywhere risk math: a pure position-sizing function (equity × risk-rate ÷ SL-distance including modeled costs) with stepSize-floor quantization and reject-preferred-over-round-up gates, plus portfolio limits (max open positions, aggregate risk, correlated-cluster cap, DAILY_STOP states) that fail closed on uncertain state. No feature/strategy/planner changes (Phase 4 frozen), no backtest simulator (Phase 6 consumes this), no WS/paper loop (Phase 7), no Telegram/execution/Algo orders (Phases 8–9). Success means backtest, paper, and live produce byte-identical sizing outputs for identical inputs (parity fixture green), and no sizing surprise appears for the first time with money attached.

## Implementation Decisions

### Sizing formula + cost model

- **D-01:** Sizing follows `docs/trading/RISK_MANAGEMENT.md` §§1–3 verbatim: `allowed_risk = equity × risk_rate`, `risk_per_unit = SL_distance_per_unit + modeled_costs_per_unit`, `quantity = allowed_risk / risk_per_unit`. `risk_rate` default 0.5% of equity (research baseline, registry-owned per CONFIGURATION.md §3); SL distance derived from the Phase-4 plan (`entry_ref − stop_loss_price`, entry_ref = zone mid for LIMIT_ZONE). Modeled costs per unit include entry+exit fee + expected slippage (+ funding where applicable, Phase-6 cost-model compatible); exact cost keys are registry parameters, never hard-coded. All arithmetic in `Decimal`, tick/qty-step aware. — **Reversibility:** costly — sizing outputs enter fixtures, plan risk fields, and backtest parity.
- [auto] Sizing formula — Q: "Canonical RISK_MANAGEMENT §§1–3 formula with modeled costs vs simplified equity-percentage sizing?" → Selected: "Canonical formula with modeled costs" (recommended default)

### Quantization ownership + parity

- **D-02:** Risk owns ALL exchange rounding: `rounded = floor(raw / step_size) × step_size` → realized-risk check (`realized_risk / allowed_risk >= minimum_risk_utilization_after_rounding`, baseline 60% per RISK_MANAGEMENT §11) → min-qty/notional reject → `QUANTIZATION_REJECT`/`NO_TRADE` preferred over round-up, never silent increase. Phase-4 planner `DEFERRED_TO_RISK` estimate fields are consumed as inputs, not re-derived; risk populates final `suggested_quantity`, `quantity_before/after_rounding`, `quantization_decision`, `realized_risk`. Identical function called in backtest/paper/live; parity golden fixture (same inputs → byte-identical outputs incl. reason codes) is CI-blocking. Raw/rounded/realized values logged per §11 rule 5. — **Reversibility:** one-way — quantization decisions are stored on plans and bound into backtest evidence.
- [auto] Quantization ownership — Q: "Risk owns floor+reject with parity fixture vs planner pre-rounds?" → Selected: "Risk owns floor+reject, planner defers" (recommended default)

### Portfolio caps + DAILY_STOP

- **D-03:** Portfolio gates from RISK_MANAGEMENT §§4–5/8 as registry parameters with research-placeholder defaults: `max_open_positions = 2`, `max_aggregate_open_risk = 1.0%`, correlated-cluster cap = conservative V1 cluster rule (directionally-aligned BTC/ETH/SOL/XRP counted as one cluster, cap = single-trade risk_rate until REFN-04 model exists), `daily_loss_stop` threshold TBD-by-researcher with states `NORMAL / WARNING / DAILY_STOP`. DAILY_STOP blocks new entries, leaves existing protectives active, raises alert. Enforcement order: per-trade sizing → cluster cap → aggregate cap → position count → daily state; first failing gate determines the reason code. Caps evaluated against live/reconciled position set, never against plan-local assumptions. — **Reversibility:** costly — cap semantics enter portfolio fixtures and Phase-8 SAFE_MODE interplay.
- [auto] Portfolio caps — Q: "Registry-parameterized caps with conservative V1 cluster rule vs hard-coded limits?" → Selected: "Registry-parameterized, conservative cluster" (recommended default)

### Fail-closed + stale metadata

- **D-04:** Uncertain account/risk state fails closed to NO_TRADE with reason code, no new orders: unknown/stale equity, unreconciled positions/orders, missing stepSize/tick/min/notional metadata, or stale exchange-constraint snapshot (RISK_MANAGEMENT §12 fields + `metadata_observed_at_utc` with registry TTL) → reject and require revalidation before approval/execution. Never widen a protective stop silently (§6); any stop modification is explicit, logged, contract-permitted (else Phase 8/9 concern, out of scope here). No revenge/compensation logic (§7): risk never scales up after losses or missed targets. — **Reversibility:** reversible — reason-code vocabulary grows additively.
- [auto] Fail-closed policy — Q: "Strict fail-closed on any uncertain/stale state vs best-effort sizing with warnings?" → Selected: "Strict fail-closed" (recommended default)

### Purity, location, registry + reason codes

- **D-05:** New pure package `src/risk/` (e.g. `sizing.py`, `portfolio.py`, `quantization.py` or planner-discretion split) under the Phase-4 D-10 purity contract: stdlib + `Decimal` only — no Polars/pandas/NumPy/SciPy, no Binance SDK types, no SQLAlchemy/Pydantic, no `float` (extend AST no-`float(` guards + mypy strict), UTC datetimes in, deterministic ordering. Exchange metadata arrives as frozen input structs via adapter edge (Phase-2 `src/data/metadata.py` shape), never fetched inside. Risk keys (`risk_rate`, `minimum_risk_utilization_after_rounding`, `max_open_positions`, `max_aggregate_open_risk`, `cluster_cap`, `daily_loss_*`, cost rates, metadata TTL) extend the Phase-3 `STRATEGY_KEYS` whitelist via reviewed registry change; new TOML values ship as new versioned sets, never ambient edits. Reason-code vocabulary: `QUANTIZATION_REJECT`, `MIN_QTY_REJECT`, `NOTIONAL_REJECT`, `UTILIZATION_REJECT`, `CLUSTER_CAP_REJECT`, `AGGREGATE_CAP_REJECT`, `MAX_POSITIONS_REJECT`, `DAILY_STOP_BLOCK`, `STALE_CONSTRAINTS`, `UNCERTAIN_ACCOUNT_STATE`. — **Reversibility:** costly — module paths and reason codes persist in fixtures, journal rows, and Telegram payloads.
- [auto] Purity/location — Q: "Strict dependency-free src/risk/ with registry keys vs pragmatic shared math?" → Selected: "Strict dependency-free src/risk/" (recommended default)

### Agent's Discretion

- User runs `--auto --chain` (fully autonomous per `modes/auto.md`): all five gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact file layout inside `src/risk/`, fixture layout under `tests/fixtures/phase5/`, per-key registry additions, cost-model key breakdown, cluster-membership rule details, daily-state transition thresholds, and plan slicing (tracer-first vs single slice) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Whether portfolio enforcement lands as one plan or sizing+portfolio slices is at the planner's discretion; sizing+quantization parity fixture must stay first.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Risk contract (what to build)

- `docs/trading/RISK_MANAGEMENT.md` — §§1–12: sizing formula, costs, portfolio placeholders, cluster rule, DAILY_STOP states, fail-closed, quantization algorithm + 60% baseline, constraint snapshot; Phase 5 implements it.
- `docs/configuration/CONFIGURATION.md` — §3 strategy-vs-runtime split (`risk_rate`, `minimum_risk_utilization_after_rounding` are registry keys); §§2/4/5 identity + immutability; new risk keys extend the whitelist.
- `docs/data/DATA_MODEL.md` — canonical entities; risk outputs map onto TradePlan quantity/risk fields, no new tables expected (trades-table deferral stays Phase 5-or-later per STATE.md; planner decides if a migration is needed).
- `docs/GLOSSARY.md` — canonical enums; authority for reason-code and status naming.
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; determinism (D001), quantization-deferral, approval-safety bind this phase.

### Inputs consumed (what to conform to)

- `docs/architecture/DATA_PIPELINE.md` — versioned symbol metadata from live exchangeInfo (step/tick/min/notional/position modes) + gap/quality fail-closed posture; D-04 consumes it.
- `docs/backtest/BACKTEST_SPEC.md` — cost model + execution assumptions the sizing function must stay compatible with (Phase 6 consumes risk parity).
- `docs/trading/SIGNAL_AND_ALERTS.md` — signal/plan schema and reason-code expectations downstream (alerts carry risk fields).
- `docs/trading/EXECUTION_SPEC.md` — Algo-Order/position-mode context (Phase 9); risk must not pre-build execution paths.
- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism + fail-closed posture; Decimal-only and UTC-at-boundary rules extended by D-05.

### Methodology + platform

- `docs/TECHNOLOGY_STACK.md` — Python 3.13 + uv; Decimal/tick arithmetic for exchange-sensitive values; pytest-asyncio auto mode; Ruff + mypy strict on `src/`.
- `docs/testing/TESTING_STRATEGY.md` — golden fixtures + deterministic test protocol; Phase-5 parity fixtures extend it.
- `docs/implementation/AGENT_INSTRUCTIONS.md` — Research → Spec → Code separation; missing rules stay TBD.

### Project context

- `.planning/PROJECT.md` — project context, constraints (quantization, fail-closed, exchange authority), key decisions.
- `.planning/REQUIREMENTS.md` — RISK-01, RISK-02.
- `.planning/ROADMAP.md` — Phase 5 goal and success criteria.
- `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` — Phase 3 locks (D-01–D-12: frozen dataclasses, content-hash IDs, TOML registry + SHA256, strategy/runtime split, fixture triple + 4 determinism suites, Decimal-only) this phase builds on.
- `.planning/phases/04-pure-core-feature-strategy-planner/04-CONTEXT.md` — Phase 4 locks (D-01–D-10: pure `src/core/`, closed-candle-only, tracer-first families, planner `DEFERRED_TO_RISK` contract D-09) this phase completes with real sizing.
- `.planning/phases/04-pure-core-feature-strategy-planner/04-VERIFICATION.md` — Phase 4 exit state the risk engine assumes as input.

## Existing Code Insights

### Reusable Assets

- `src/core/planner.py` (entry zone, SL/TP, RR gate, `plan_hash`, `DEFERRED_TO_RISK` estimate fields) — risk consumes planner outputs as inputs; never re-derives setup logic.
- `src/domain/trade_plan.py` (frozen TradePlan + Decimal/UTC guards, JSON-as-TEXT fields) — risk populates final quantity/risk fields on this shape.
- `src/domain/registry.py` (`load_parameter_set`, `STRATEGY_KEYS`, fail-closed gates) — extend `STRATEGY_KEYS` for D-05 risk keys; versioned TOML sets under `params/<family>/baseline-v1.toml`.
- `src/domain/ids.py` + `src/domain/canonical.py` (`make_signal_id`, `derive_child_id`, `sha256_hex`) — deterministic ID/hash discipline for parity fixtures.
- `src/domain/enums.py` — extend with quantization/portfolio reason vocabulary following D-05.
- `src/data/metadata.py` + `src/data/quality.py` — versioned exchange metadata shape + fail-closed quality precedent for D-04 adapter edge.
- `src/core/_decimal.py` — Decimal helper precedent for D-05 purity.
- `tests/test_domain_no_float.py` (AST no-`float(` guards), `tests/test_prefix_invariance.py`, `tests/test_no_lookahead.py`, `tests/test_candle_close_timing.py`, `tests/test_fixture_harness.py`, `tests/conftest.py` — extend with `tests/fixtures/phase5/` parity fixtures (identical inputs → byte-identical sizing in backtest/paper/live).
- `src/adapters/binance_usdm.py` — adapter-boundary isolation precedent D-05 follows (risk never imports the SDK).

### Established Patterns

- TDD RED→GREEN per behavior with atomic commits; frozen dataclasses; INSERT-only versioning; fail-closed loader/quality posture; structured lineage logging.
- Decimal-only + UTC-at-boundary + Asia/Ho_Chi_Minh display-edge discipline (Phases 2–4).
- Tracer-first rollout precedent (Phase 4): land sizing+quantization parity slice first, then portfolio caps.

### Integration Points

- New pure `src/risk/` package (sizing + quantization + portfolio gates, dependency-free) consuming TradePlan + account/position snapshot + registry set + constraint snapshot, emitting sized plan or NO_TRADE with reason code.
- New `tests/fixtures/phase5/` golden files (plan + account + constraints + parameters → expected sized quantities/rejects, byte-exact).
- Phase 6 consumes risk + parity fixtures for the costs-included backtest engine; Phase 8 binds sized-plan hashes in approvals and reuses DAILY_STOP/SAFE_MODE interplay; Phase 9 revalidates constraints at placement time.

## Specific Ideas

- No "I want it like X" references — `--auto` mode, open to standard approaches within the locked decisions above (same delegation pattern as Phases 1–4).
- Prior delegation precedent (Phases 1–4 CONTEXTs): user delegates implementation choices to recommended defaults; planner/researcher discretion governs layout and slicing.

## Deferred Ideas

- Backtest intrabar/SL-first/costs engine → Phase 6; WS/paper loop → Phase 7; Telegram approval + reconciliation/orphan-sweeper/SAFE_MODE rehearsal → Phase 8; live Algo exits + placement-time revalidation → Phase 9.
- Correlation model upgrade (REFN-04), OI/funding as features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 5.
- None — discussion stayed within phase scope.

---

*Phase: 5-Risk Engine*
*Context gathered: 2026-09-25*
