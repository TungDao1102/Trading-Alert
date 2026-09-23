# Phase 4: Pure Core (Feature + Strategy + Planner) - Context

**Gathered:** 2026-09-23
**Status:** Ready for planning

## Phase Boundary

Phase 4 delivers the pure deterministic core: closed candles in, deterministic setups out. A feature engine computes indicators/structure/zones from closed candles only with warm-up validity gates; a pure strategy function maps (market snapshot + account state + strategy version + config) to NO_TRADE or SETUP with a deterministic SignalId; a trade planner translates each valid setup into entry zone, SL, TP(s), invalidation, expiry, expected RR, and plan hash. No sizing/quantization math (Phase 5), no backtest engine (Phase 6), no WS/paper loop (Phase 7), no Telegram/execution (Phases 8–9). No family is declared a winner — all three remain hypotheses pending backtest plus out-of-sample evidence. Success means the simulators Phase 6 will consume are fixture-green: prefix-invariant, no-lookahead, candle-close-timing, and boundary suites pass over real family expectations.

## Implementation Decisions

### Feature engine scope

- **D-01:** V1 feature set is minimal and registry-driven: EMA(20/50/200), ATR(14), swing high/low over `swing_lookback`, support/resistance zones from `zone_tolerance_atr`. No OI/funding features in V1 (REFN-02/REFN-03 stay deferred); no 15M refinement (REFN-01 deferred). Feature code lives in a new pure package `src/core/` (e.g. `features.py`), importing NOTHING from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + `Decimal` only, matching the Phase-3 D-01 domain purity precedent. — **Reversibility:** costly — feature names/semantics enter fixtures, registry-adjacent docs, and backtest parity.
- **D-02:** Input is closed-candle sequences only (list of frozen candle dataclasses / validated dicts sourced from Parquet rows via an adapter edge); the engine NEVER resamples, forward-fills, or reads an unclosed/in-progress candle. Multi-timeframe inputs (1H setup + 4H context, 1m reserved for Phase 6 intrabar) arrive as separate closed sequences; 4H context computed independently, never interpolated into 1H bars. — **Reversibility:** one-way — lookahead violations baked into fixtures would poison backtest evidence.
- [auto] Feature scope — Q: "Minimal V1 set (EMA/ATR/swing/zones, pure stdlib+Decimal) vs full indicator library?" → Selected: "Minimal V1 set" (recommended default)

### Warm-up and validity policy

- **D-03:** Per-feature validity flags: every feature output carries `valid: bool` + `reason_code` (e.g. `WARMUP_INSUFFICIENT`, `GAP_IN_SOURCE`). Long-warm-up features (EMA200-4H ≈ 800h ≈ 33+ days of 4H history) report invalid until history suffices; the strategy treats any required-feature-invalid as NO_TRADE with reason code, never NaN/partial propagation. A whole-bar `features_valid` summary gates setup detection. — **Reversibility:** reversible — reason-code vocabulary grows additively.
- **D-04:** Gap policy inherits Phase-2 D-09 flag-never-fabricate: missing candles produce explicit gaps; features spanning a gap report invalid (or degrade per documented rule, never synthesize). Quality rejects (duplicate timestamps, OHLC violations, regressions) fail closed before features compute. — **Reversibility:** reversible — gap-handling refinements are additive rules.
- [auto] Warm-up policy — Q: "Per-feature valid flags + NO_TRADE on invalid vs whole-bar silent NaN?" → Selected: "Per-feature valid flags + NO_TRADE" (recommended default)

### Strategy family rollout + enum promotion

- **D-05:** Tracer-first rollout: implement `trend-pullback/baseline-v1.toml` (the only registered set) end-to-end first (features → strategy → planner → golden fixtures green), then add `breakout-retest` and `range-mr` as parallel slices reusing the same harness. All three families land in Phase 4 as hypotheses; planner/researcher must NOT declare a winner (Phase-1 D-08, roadmap D012). New parameter keys per family extend the Phase-3 `STRATEGY_KEYS` whitelist via reviewed registry change, never ambient config. — **Reversibility:** one-way — published strategy versions + parameter hashes are permanent references.
- **D-06:** Promote deferred string fields to Enums now (closes Phase-3 deferred item): `direction` (LONG/SHORT), `setup_type` (per-family setup names), `source_timeframe`, plus planner `entry_model`/`order_role` and quantization `quantization_decision` vocabulary, in `src/domain/enums.py` with GLOSSARY-consistent names. `event_type`/`entity_type` (JournalEvent) and execution-side enums (`side`, `position_side`, `order_type`, `time_in_force`) promote only where Phase 4 constructs them; execution-lifecycle values stay Phase 8/9. Unknown values remain load-time errors. — **Reversibility:** costly — enum names persist in stored rows, fixtures, and Telegram payloads.
- **D-07:** Strategy is a pure function `evaluate(snapshot, account_state, strategy_version, parameter_set) -> NO_TRADE | SETUP(Signal fields)` with zero I/O, zero clock reads (timestamps passed in), zero randomness; `SignalId` via existing `ids.make_signal_id` and `detected_at_utc = source_candle_close_utc` (candle-close timing). Prefix-invariance and no-lookahead suites extend Phase-3 scaffolding with real family expectations. — **Reversibility:** one-way — SignalId inputs are stored in journal/experiment records forever.
- [auto] Family rollout — Q: "Tracer trend-pullback first then other two vs all three at once?" → Selected: "Tracer-first, then parallel slices" (recommended default)
- [auto] Enum promotion — Q: "Promote deferred strings to Enums in Phase 4 vs keep strings?" → Selected: "Promote now" (recommended default)

### Planner output contract

- **D-08:** Every SETUP produces exactly one TradePlan filling the existing `src/domain/trade_plan.py` shape: entry zone `[entry_min_price, entry_max_price]` from `entry_buffer_atr`, `stop_loss_price` from `sl_buffer_atr`, `take_profit_json` with TP1 at `minimum_rr` and TP2 extension, `expected_rr_json` with per-TP RR, `invalidation_rule_json` (structure-break + candle-close basis), `expiry_utc = source_close + signal_expiry_hours`, `plan_hash` = SHA256 over canonical JSON of (signal_id + entry + SL + TPs + invalidation + expiry), mirroring the D-04 canonical-hash discipline. RR below `minimum_rr` → NO_TRADE with reason code, never a downgraded plan. — **Reversibility:** one-way — plan hashes are approval-bound in Phase 8.
- **D-09:** Quantization fields (`suggested_quantity`, `quantity_before/after_rounding`, `quantization_decision`, `risk_rate`, `risk_budget`) are populated with Decimal planner-side estimates for shape completeness, but exchange rounding/minimums enforcement stays Phase 5. Planner NEVER floor/round-up against stepSize — it records pre-risk quantities and marks `quantization_decision = "DEFERRED_TO_RISK"` (or Enum equivalent) so Phase 5 owns identical-everywhere math. — **Reversibility:** reversible — Phase 5 refines values without breaking the plan shape.
- [auto] Planner contract — Q: "Full zone+TP1/TP2+RR-gate+hash contract vs minimal single-price plan?" → Selected: "Full contract per TradePlan shape" (recommended default)

### Determinism and purity boundary

- **D-10:** `src/core/` (features, strategy, planner) is dependency-free: no Polars/pandas/NumPy/SciPy imports, no Binance SDK types, no SQLAlchemy/Pydantic, no `float` anywhere (extend Phase-3 AST no-`float(` guards + mypy strict), `Decimal` for all price/qty/RR arithmetic, UTC `datetime` internally. Adapters at the edges convert Parquet/registry decimals in and fixtures out. Deterministic ordering everywhere (sorted keys, fixed iteration order); no dict-order/wall-clock dependence. — **Reversibility:** costly — purity violations leak into every consumer's test story.
- [auto] Purity boundary — Q: "Strict dependency-free core vs pragmatic NumPy/Polars inside core?" → Selected: "Strict dependency-free core" (recommended default)

### the agent's Discretion

- User runs `--auto` (fully autonomous per `modes/auto.md`): all six gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact file layout inside `src/core/` (module split, helper design), fixture CSV/JSON layout under `tests/fixtures/phase4/`, per-family parameter key additions to `STRATEGY_KEYS`, TP2 extension rule details, invalidation JSON schema, reason-code vocabulary, and plan slicing are at the planner/researcher discretion, provided D-01–D-10 semantics hold.
- Whether the three families land as 3 plans or tracer+2 slices is at the planner's discretion; tracer must stay first.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Strategy contract (what to build)

- `docs/strategy/TRADING_STRATEGY_SPEC.md` — TEMPLATE/NOT FROZEN; slot structure (regime, structure, setup, entry, invalidation, SL, TP, expiry, risk compatibility, determinism §11, versioning §12) the core implements per family.
- `docs/research/families/trend-pullback.md` — Family A machine-detectable rules, alternatives, bias notes, parameters (source for tracer slice).
- `docs/research/families/breakout-retest.md` — Family B rules (second slice).
- `docs/research/families/range-mr.md` — Family C rules (third slice).
- `docs/research/RESEARCH_PROTOCOL.md` — FROZEN v1.0.0; acceptance gates, no-winner rule, dataset/cost assumptions the core must respect.
- `docs/research/TRADING_STRATEGY_RESEARCH.md` — living draft v0.1 background only, never the frozen contract.

### Domain + registry contract (what to conform to)

- `docs/data/DATA_MODEL.md` — canonical entities §§2.3–2.4 (Signal/TradePlan fields), §5 JSON-as-TEXT rule; core output must map 1:1.
- `docs/GLOSSARY.md` — canonical enums; authority for D-06 naming.
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; determinism (D001), quantization-deferral, approval-safety bind this phase.
- `docs/configuration/CONFIGURATION.md` — parameter-set identity + strategy-vs-runtime split; new family keys extend the whitelist.
- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism + fail-closed posture; Decimal-only and UTC-at-boundary rules extended by D-10.

### Data inputs (what to consume)

- `docs/architecture/DATA_PIPELINE.md` — §§2/6/7/8/10: closed-candle classes, quality rules, UTC storage, raw-vs-derived, per-symbol availability; D-02/D-04 implement it.
- `docs/backtest/BACKTEST_SPEC.md` — warm-up history, 1m intrabar availability, execution assumptions the core must not break.
- `docs/trading/SIGNAL_AND_ALERTS.md` — signal/plan schema and reason-code expectations downstream (alerts consume these).

### Methodology + platform

- `docs/TECHNOLOGY_STACK.md` — Python 3.13 + uv; Polars/pandas/NumPy reserved for research/backtest edges, NOT `src/core/`; pytest-asyncio auto mode; Ruff + mypy strict on `src/`.
- `docs/testing/TESTING_STRATEGY.md` — golden fixtures + deterministic test protocol; Phase-4 fixtures extend it.
- `docs/implementation/AGENT_INSTRUCTIONS.md` — Research → Spec → Code separation; missing rules stay TBD.

### Project context

- `.planning/PROJECT.md` — project context, constraints, key decisions.
- `.planning/REQUIREMENTS.md` — STRAT-01, STRAT-02, STRAT-03.
- `.planning/ROADMAP.md` — Phase 4 goal and success criteria.
- `.planning/phases/01-research-formalization/01-CONTEXT.md` — Phase 1 locks (frozen protocol, 7-slot template, gate enforcement, no-winner rule).
- `.planning/phases/02-data-foundation/02-CONTEXT.md` — Phase 2 locks (live-5 universe, Parquet Hive layout, PG/Parquet split, UTC/HCMC, 5-min OI, fail-closed quality) this phase consumes.
- `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` — Phase 3 locks (D-01–D-12: frozen dataclasses, content-hash IDs, TOML registry + SHA256, strict strategy/runtime split, fixture triple + 4 determinism suites, explicit statuses, Decimal-only) this phase fills with behavior.

## Existing Code Insights

### Reusable Assets

- `src/domain/signal.py` (frozen Signal + UTC validation) — strategy output type; construct with `ids.make_signal_id`, `detected_at_utc = source_candle_close_utc`.
- `src/domain/trade_plan.py` (frozen TradePlan + Decimal/UTC guards, JSON-as-TEXT fields) — planner output type; `trade_plan_id` via `ids.derive_child_id` discriminator `trade_plan:v1`.
- `src/domain/ids.py` (`make_signal_id`, `derive_child_id`) — deterministic ID derivation; reuse for SignalId + plan IDs + `plan_hash` discipline.
- `src/domain/canonical.py` (`sha256_hex`, canonical JSON) — reuse for `plan_hash` computation.
- `src/domain/registry.py` (`load_parameter_set`, `STRATEGY_KEYS`, `UnregisteredParameterSet`/`ParameterSetMutated`/`StrategyKeyOutsideRegistry`) — parameter loading + fail-closed gates; extend `STRATEGY_KEYS` for new family keys.
- `src/domain/enums.py` (SignalStatus, TradePlanStatus, ApprovalStatus, OrderStatus) — extend with D-06 promotions.
- `params/trend-pullback/baseline-v1.toml` (schema_version 1, 10 strategy keys) — tracer parameter set; second/third families add new TOML sets.
- `tests/test_no_lookahead.py`, `tests/test_prefix_invariance.py`, `tests/test_candle_close_timing.py`, `tests/test_domain_boundary.py`, `tests/test_fixture_harness.py`, `tests/conftest.py` (golden-fixture loaders, frozen clock) — extend scaffolding with real family expectations under `tests/fixtures/phase4/`.
- `tests/test_domain_no_float.py` (AST no-`float(` guards) — extend to `src/core/`.
- `src/data/` (`backfill.py`, `coverage.py`, `quality.py`, `store.py`) — candle sourcing + quality-reject precedent for D-02/D-04; core consumes closed sequences via adapter, never imports these directly.
- `src/adapters/binance_usdm.py` — adapter-boundary isolation precedent D-01/D-10 follow.

### Established Patterns

- TDD RED→GREEN per behavior with atomic commits; frozen dataclasses; INSERT-only versioning; fail-closed loader/quality posture; structured lineage logging.
- Decimal-only + UTC-at-boundary + Asia/Ho_Chi_Minh display-edge discipline (Phases 2–3).
- Single-Base ORM + offline parity-gate discipline for any DB touch (none expected in Phase 4 — pure core has no new tables).

### Integration Points

- New pure `src/core/` package (features + strategy + planner, dependency-free) consuming closed-candle sequences + registry sets, emitting Signal/TradePlan domain objects.
- New `tests/fixtures/phase4/` golden files (input candles + parameters → expected features/signals/plans, byte-exact).
- Phase 5 consumes planner outputs + registry identity for sizing/quantization parity; Phase 6 consumes core + fixtures for the 1m-intrabar backtest engine; Phase 8 binds `plan_hash` + SignalId in approvals.

## Specific Ideas

- No "I want it like X" references — `--auto` mode, open to standard approaches within the locked decisions above (same delegation pattern as Phases 1–3).
- Prior delegation precedent (Phases 1–3 CONTEXTs): user delegates implementation choices to recommended defaults; planner/researcher discretion governs layout and slicing.

## Deferred Ideas

- Sizing/quantization enforcement → Phase 5 (D-09 defers exchange rounding/minimums; NO_TRADE-preferred-over-round-up stays Phase 5).
- Backtest intrabar/SL-first/costs engine → Phase 6; WS/paper loop → Phase 7; Telegram approval + reconciliation/SAFE_MODE → Phase 8; live Algo exits → Phase 9.
- OI/funding as strategy features (REFN-02/REFN-03), 15M entry refinement (REFN-01), correlation model (REFN-04), extra families (REFN-05) → v2 requirements, not Phase 4.
- None — discussion stayed within phase scope.

---

*Phase: 4-Pure Core (Feature + Strategy + Planner)*
*Context gathered: 2026-09-23*
