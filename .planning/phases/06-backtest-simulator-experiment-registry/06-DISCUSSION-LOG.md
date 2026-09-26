# Phase 6: Backtest Simulator + Experiment Registry - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-26
**Phase:** 6-Backtest Simulator + Experiment Registry
**Areas discussed:** Intrabar resolution + execution semantics, Cost model versioning + risk parity, Experiment identity + storage + reproducibility, Reporting + uncertainty-first + baselines, Engine location/purity + dataset splits + VectorBT boundary

---

## Intrabar resolution + execution semantics

| Option | Description | Selected |
|--------|-------------|----------|
| 1m intrabar with SL-first fallback | Both-touched SL/TP bars resolve with 1m data; missing 1m uses logged SL-first conservative fallback; limit fills/partials/expiry/invalidation modeled | ✓ |
| Setup-candle-only resolution | Resolve SL/TP ordering from setup-candle OHLC alone with a fixed rule | |

**User's choice:** 1m intrabar with SL-first fallback (recommended default, auto-selected via `--auto`)
**Notes:** [auto] Intrabar resolution — Q: "1m intrabar with SL-first conservative fallback vs setup-candle-only resolution?" → Selected: "1m intrabar with SL-first fallback". Follows BACKTEST_SPEC §§3–6 + Phase-2/4 flag-never-fabricate.

---

## Cost model versioning + risk parity

| Option | Description | Selected |
|--------|-------------|----------|
| Registry-versioned costs with risk parity | Fees/funding/slippage as registry cost keys with costModelHash; simulator calls identical src/risk functions from run #1 | ✓ |
| Simulator-local cost estimates | Costs estimated inside the simulator, decoupled from risk engine | |

**User's choice:** Registry-versioned costs with risk parity (recommended default, auto-selected via `--auto`)
**Notes:** [auto] Cost model — Q: "Registry-versioned costs with identical src/risk parity vs simulator-local cost estimates?" → Selected: "Registry-versioned costs with risk parity". No cost-free ranking pass.

---

## Experiment identity + storage + reproducibility

| Option | Description | Selected |
|--------|-------------|----------|
| Six-field identity, Parquet-canonical + optional PG mirror | experimentId/strategyVersion/parameterSetHash(+Id)/dataSnapshotId/codeVersion/costModelHash; Parquet-canonical datasets; PG mirror at planner discretion | ✓ |
| PG-only experiment store | All experiment state lives in PostgreSQL | |

**User's choice:** Six-field identity, Parquet-canonical + optional PG mirror (recommended default, auto-selected via `--auto`)
**Notes:** [auto] Experiment registry — Q: "Six-field identity with Parquet-canonical datasets (+ optional PG mirror) vs PG-only experiment store?" → Selected: "Six-field identity, Parquet-canonical + optional PG mirror". Unregistered sets fail closed.

---

## Reporting + uncertainty-first + baselines

| Option | Description | Selected |
|--------|-------------|----------|
| Uncertainty-first with baselines | Slices + R distribution + bootstrap/block-bootstrap + plateau + no-trade/simple-trend baselines + dual-universe (research + live-5); no winner without OOS | ✓ |
| Headline-expectancy ranking | Rank candidates by single expectancy number | |

**User's choice:** Uncertainty-first with baselines (recommended default, auto-selected via `--auto`)
**Notes:** [auto] Reporting standard — Q: "Uncertainty-first (slices + R distribution + bootstrap + plateau + baselines + dual-universe) vs headline-expectancy ranking?" → Selected: "Uncertainty-first with baselines". Explicitly rejected per BACKTEST_SPEC §10.

---

## Engine location/purity + dataset splits + VectorBT boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Strict pure src/backtest/, Polars at edges | stdlib+Decimal execution core; Polars/DuckDB at load/report edges; VectorBT exploratory-only; dev/val/holdout + walk-forward | ✓ |
| Vectorized engine with pandas/NumPy inside | Full-frame vectorized simulator with scientific libs in the core | |

**User's choice:** Strict pure src/backtest/, Polars at edges (recommended default, auto-selected via `--auto`)
**Notes:** [auto] Engine boundary — Q: "Strict pure src/backtest/ with Polars-at-edges vs vectorized engine with pandas/NumPy inside?" → Selected: "Strict pure src/backtest/, Polars at edges". Extends Phase-4 D-10 / Phase-5 D-05 purity.

---

## Agent's Discretion

- User runs `--auto --chain` (fully autonomous): all five areas auto-resolved to recommended defaults, no interactive prompts. Single-pass cap observed.
- File layout inside `src/backtest/`, fixture layout under `tests/fixtures/phase6/`, cost-key breakdown, PG mirror timing, bootstrap counts, plateau grids, baseline-trend spec, and plan slicing at planner/researcher discretion provided D-01–D-05 hold.

## Deferred Ideas

- WS/paper loop → Phase 7; Telegram approval + reconciliation/SAFE_MODE → Phase 8; live Algo exits → Phase 9; journal depth + kill-gate ops → Phase 10.
- REFN-02/REFN-03 (OI/funding features), REFN-01 (15M), REFN-04 (correlation model), REFN-05 (extra families) → v2.
