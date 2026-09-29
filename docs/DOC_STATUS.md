# Core Docs Status

## Stable / canonical

- `00_PRODUCT_SCOPE.md`
- `01_ENGINEERING_PRINCIPLES.md`
- `GLOSSARY.md`
- `data/DATA_MODEL.md`
- `configuration/CONFIGURATION.md`
- `testing/TESTING_STRATEGY.md`
- `DECISIONS.md`
- `TECHNOLOGY_STACK.md`
- `research/RESEARCH_PROTOCOL.md` — Frozen on 2026-09-19 (v1.0.1; D029, D030); executable gate at `.github/workflows/research-gate.yml`

## Living research

- `research/TRADING_STRATEGY_RESEARCH.md`

## Blocked until strategy freeze

- `strategy/TRADING_STRATEGY_SPEC.md`

## Baseline architecture/specification

- `architecture/ARCHITECTURE.md`
- `architecture/DATA_PIPELINE.md`
- `backtest/BACKTEST_SPEC.md`
- `backtest/METRICS.md`
- `trading/RISK_MANAGEMENT.md`
- `trading/EXECUTION_SPEC.md`
- `trading/SIGNAL_AND_ALERTS.md`

## Integrations

- `integration/BINANCE.md`
- `integration/TRADINGVIEW.md`
- `integration/TELEGRAM.md`

## Operations

- `operations/SECURITY_AND_OPERATIONS.md`
- `operations/RUNBOOK.md`

## Implementation

- `implementation/IMPLEMENTATION_PLAN.md`
- `implementation/AGENT_INSTRUCTIONS.md`

## Change log

- 2026-09-19 — Phase 1 C1–C7 contradiction resolutions landed as D022–D028; docs touched in this batch: `00_PRODUCT_SCOPE.md` (C1), `trading/SIGNAL_AND_ALERTS.md` (C2, C7), `trading/EXECUTION_SPEC.md` (C3), `testing/TESTING_STRATEGY.md` (C3), `research/TRADING_STRATEGY_RESEARCH.md` (C4, C5, C6 trailing renumber), `GLOSSARY.md` (C7), `data/DATA_MODEL.md` (C7), `backtest/BACKTEST_SPEC.md` (C6 duplicate gates header), `architecture/DATA_PIPELINE.md` (C6 trailing duplicates), `integration/TRADINGVIEW.md` (C6 webhook-adapter), `operations/SECURITY_AND_OPERATIONS.md` (C6 runtime-operations), `DECISIONS.md` (D022–D028 appended).
- 2026-09-19 — `research/RESEARCH_PROTOCOL.md` flipped to FROZEN per D029 (header `Status: FROZEN` + `Frozen on: 2026-09-19`); executable gate `.github/workflows/research-gate.yml` lands with three fail-closed checks (freeze / identity-tuple / registry-path tripwire). Phase 3 (parameter-registry loader) and Phase 8 (approval/reconciliation) reference this gate file as their acceptance criterion.
- 2026-09-29 — `research/RESEARCH_PROTOCOL.md` v1.0.1 clarification per D030: the kill-gate firing rule is conformed to D013 (both budgets exhausted, no passing family); header `Status` and `Frozen on` unchanged, no gate or threshold change; amendment recorded in the protocol Amendment log.
