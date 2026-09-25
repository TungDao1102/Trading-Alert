# Phase 5: Risk Engine - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-25
**Phase:** 5-risk-engine
**Areas discussed:** Sizing formula + cost model, Quantization ownership + parity, Portfolio caps + DAILY_STOP, Fail-closed + stale metadata, Purity/location/registry + reason codes

---

## Sizing formula + cost model

| Option | Description | Selected |
|--------|-------------|----------|
| Canonical formula with modeled costs | equity × risk_rate ÷ (SL-distance + modeled costs), Decimal-only | ✓ |
| Simplified equity-percentage sizing | Fixed fraction of equity, no SL-distance link | |

**User's choice:** Canonical formula with modeled costs (recommended default)
**Notes:** [auto] No interactive prompt; aligned with RISK_MANAGEMENT §§1–3 and CONFIGURATION §3 registry ownership.

---

## Quantization ownership + parity

| Option | Description | Selected |
|--------|-------------|----------|
| Risk owns floor+reject, planner defers | floor to stepSize → 60% utilization check → min/notional reject, parity fixture | ✓ |
| Planner pre-rounds | Planner rounds against stepSize before risk sees the plan | |

**User's choice:** Risk owns floor+reject, planner defers (recommended default)
**Notes:** [auto] Completes Phase-4 D-09 DEFERRED_TO_RISK contract; identical-everywhere math per RISK-01.

---

## Portfolio caps + DAILY_STOP

| Option | Description | Selected |
|--------|-------------|----------|
| Registry-parameterized, conservative cluster | max 2 open, 1.0% aggregate, aligned-cluster cap, NORMAL/WARNING/DAILY_STOP | ✓ |
| Hard-coded limits | Fixed constants in code | |

**User's choice:** Registry-parameterized, conservative cluster (recommended default)
**Notes:** [auto] V1 cluster rule stays conservative until REFN-04 model; DAILY_STOP blocks entries per §8.

---

## Fail-closed + stale metadata

| Option | Description | Selected |
|--------|-------------|----------|
| Strict fail-closed | Any uncertain/stale account, position, or constraint state → NO_TRADE, revalidate | ✓ |
| Best-effort with warnings | Size anyway and log a warning | |

**User's choice:** Strict fail-closed (recommended default)
**Notes:** [auto] Per RISK_MANAGEMENT §10 + §12 snapshot/TTL; no silent stop-widening (§6), no revenge logic (§7).

---

## Purity/location/registry + reason codes

| Option | Description | Selected |
|--------|-------------|----------|
| Strict dependency-free src/risk/ | stdlib+Decimal only, registry keys, explicit reason-code vocabulary | ✓ |
| Pragmatic shared math | NumPy/helpers inside risk, informal codes | |

**User's choice:** Strict dependency-free src/risk/ (recommended default)
**Notes:** [auto] Extends Phase-4 D-10 purity + Phase-3 AST no-float guards and mypy strict.

---

## Agent's Discretion

User runs `--auto --chain`: all five areas auto-resolved to recommended defaults, no interactive prompts. Single-pass cap observed. File layout inside `src/risk/`, fixture layout under `tests/fixtures/phase5/`, cost-key breakdown, cluster-membership details, daily-state thresholds, and plan slicing at planner/researcher discretion within D-01–D-05.

## Deferred Ideas

None — discussion stayed within phase scope. Phase 6 (backtest engine), Phase 7 (paper loop), Phase 8 (approval/reconciliation/SAFE_MODE), Phase 9 (live Algo exits) noted as downstream consumers only.
