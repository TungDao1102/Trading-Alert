# Phase 4: Pure Core (Feature + Strategy + Planner) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-23
**Phase:** 4-Pure Core (Feature + Strategy + Planner)
**Areas discussed:** Feature engine scope, Warm-up and validity policy, Strategy family rollout + enum promotion, Planner output contract, Determinism and purity boundary

---

## Feature engine scope

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal V1 set (EMA/ATR/swing/zones, pure stdlib+Decimal) | EMA20/50/200, ATR14, swing high/low, zones; `src/core/` dependency-free | ✓ |
| Full indicator library (MACD/RSI/BB/fib, NumPy/Polars in core) | Broader coverage, heavier deps inside deterministic core | |
| Research-notebook features ported directly | Fastest path, breaks purity + determinism boundary | |

**User's choice:** Minimal V1 set (auto-selected recommended default, --auto mode, no interactive prompt)
**Notes:** OI/funding excluded (REFN-02/REFN-03); 15M excluded (REFN-01). Closed candles only.

---

## Warm-up and validity policy

| Option | Description | Selected |
|--------|-------------|----------|
| Per-feature valid flags + NO_TRADE on invalid | Each feature carries valid+reason_code; required-invalid → NO_TRADE | ✓ |
| Whole-bar silent NaN propagation | Simpler code, risks NaN leaking into signals | |
| Interpolate across gaps | Fabricates data, violates flag-never-fabricate | |

**User's choice:** Per-feature valid flags + NO_TRADE (auto-selected recommended default)
**Notes:** EMA200-4H invalid until ~33+ days history; gaps → invalid per Phase-2 D-09.

---

## Strategy family rollout

| Option | Description | Selected |
|--------|-------------|----------|
| Tracer trend-pullback first, then parallel slices | baseline-v1 end-to-end green, then breakout-retest + range-mr reuse harness | ✓ |
| All three families at once | Maximum parallelism, no proven harness first | |
| Single family only in Phase 4 | Leaves two hypotheses unbuilt, breaks roadmap parity | |

**User's choice:** Tracer-first, then parallel slices (auto-selected recommended default)
**Notes:** No winner declared (D012 / Phase-1 D-08). New family keys extend STRATEGY_KEYS via reviewed change.

---

## Enum promotion

| Option | Description | Selected |
|--------|-------------|----------|
| Promote deferred strings to Enums now | direction/setup_type/timeframes/entry_model/quantization vocabulary in enums.py | ✓ |
| Keep validated strings through Phase 4 | Defers Phase-3 deferred item again | |

**User's choice:** Promote now (auto-selected recommended default)
**Notes:** Closes Phase-3 deferred item; execution-lifecycle values stay Phase 8/9.

---

## Planner output contract

| Option | Description | Selected |
|--------|-------------|----------|
| Full zone+TP1/TP2+RR-gate+hash contract | Entry zone, SL, TP1@minimum_rr + TP2, invalidation/expiry JSON, plan_hash, RR gate | ✓ |
| Minimal single-price plan | Less downstream value, mismatches TradePlan shape | |

**User's choice:** Full contract per TradePlan shape (auto-selected recommended default)
**Notes:** Quantization fields estimated with DEFERRED_TO_RISK marker; enforcement stays Phase 5.

---

## Determinism and purity boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Strict dependency-free core (stdlib+Decimal only) | No Polars/pandas/NumPy/SDK/SQLAlchemy/Pydantic/float in src/core/ | ✓ |
| Pragmatic NumPy/Polars inside core | Faster vectorization, breaks identical-everywhere test story | |

**User's choice:** Strict dependency-free core (auto-selected recommended default)
**Notes:** Adapters at edges; AST no-float guards + mypy strict extend to src/core/.

---

## the agent's Discretion

- All six areas auto-resolved to recommended defaults under --auto (no prompts); single-pass cap observed.
- File layout in src/core/, fixture layout in tests/fixtures/phase4/, TP2 rule details, invalidation JSON schema, reason-code vocabulary, plan slicing → planner/researcher discretion.

## Deferred Ideas

- Sizing/quantization enforcement → Phase 5; backtest engine → Phase 6; paper loop → Phase 7; approval/reconciliation → Phase 8; live exits → Phase 9.
- REFN-01 (15M), REFN-02 (OI), REFN-03 (funding), REFN-04 (correlation), REFN-05 (extra families) → v2.
