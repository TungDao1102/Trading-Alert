# Trading-Alert core

Deterministic Binance USDⓈ-M research + semi-automated execution (human APPROVE; no auto-trading V1). No AI/LLM in decision path. Authority: `AGENTS.md`, `docs/DECISIONS.md` (D001..D05x), `docs/GLOSSARY.md` (enum source, D016).

## Source map (`src/`)
- `core/` strategy, planner, features, `_decimal.py` (pinned prec-28 helpers; use for all money math)
- `risk/` sizing, gating (`evaluate_risk`), portfolio gates, cost_rates
- `backtest/` simulator, costs, experiment, report, binding (Polars-free by package rule)
- `data/` collector, backfill, Parquet store, case_input builder, universe freeze (Polars allowed)
- `analytics/` live outcomes, kill-gate, reports; `paper/` paper loop/supervisor; `execution/` placement/manager
- `adapters/` Binance/Telegram wrappers (SDK models never leak); `approval/`, `reconcile/`, `persistence/`, `db/` (SQLAlchemy+Alembic), `domain/` enums/registry
- `params/` versioned parameter sets (TOML, hash-locked, never edited in place); `scripts/decision_alignment/` doc/protocol pin witnesses
- `.planning/` GSD artifacts (ROADMAP, STATE, phases/NN-slug/*-CONTEXT|RESEARCH|PLAN); `docs/` specs

## Invariants
- Decimal only for prices/qty/risk; no float on order-gating paths; no wall-clock inside backtest; sorted iteration; byte-identical reruns; prefix-invariance; no lookahead.
- Fail closed: uncertain state → NO_TRADE/SAFE_MODE.
- Frozen artifacts (params, RESEARCH_PROTOCOL v1.1.0) are versioned, never edited in place; deliberate fixture/hash regeneration gets one DECISIONS entry listing every moved item.
- Exchange facts re-verified against official docs; record source+date in `docs/SOURCES.md`.

See `mem:tech_stack`, `mem:suggested_commands`, `mem:conventions`, `mem:task_completion`, `mem:ci_traps`.
