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
- `research/RESEARCH_PROTOCOL.md` — Frozen on 2026-09-19, amended 2026-09-30 (v1.1.0; D029, D030, D043); executable gate at `.github/workflows/research-gate.yml`

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
- 2026-09-30 — `research/RESEARCH_PROTOCOL.md` v1.1.0 semantic amendment per D043 (implements D032): numeric pre-registration of acceptance thresholds, variant budget with Holm-Bonferroni correction and a single-use holdout with the `docs/research/holdout_consumed.json` marker; the research-gate freeze step is now version-bound (header version = DECISIONS row = DOC_STATUS line). Header `Status` and `Frozen on` unchanged (the D013 clock is not restarted); an `Amended on` line and `Supersedes: v1.0.1` are added.
- 2026-09-30 — Phase 11 decision alignment recorded as D044, with exclusions and dispositions as D045 (protocol v1.1.0 is D043 above): documents amended by Phase 11 are `GLOSSARY.md` (canonical reason codes, ApprovalResult), `DECISIONS.md` (D043-D045), `SOURCES.md`, `architecture/ARCHITECTURE.md`, `backtest/BACKTEST_SPEC.md`, `configuration/CONFIGURATION.md`, `data/DATA_MODEL.md` (V1 status notes for `feature_snapshots`, `trades`, `experiment_runs`), `integration/BINANCE.md`, `integration/TRADINGVIEW.md`, `operations/RUNBOOK.md`, `operations/SECURITY_AND_OPERATIONS.md`, `research/TRADING_STRATEGY_RESEARCH.md`, `trading/EXECUTION_SPEC.md`, `trading/RISK_MANAGEMENT.md` and `trading/SIGNAL_AND_ALERTS.md`, plus `AGENTS.md` and `.planning/PROJECT.md` pointers; 13 requirement IDs registered in `.planning/REQUIREMENTS.md`.
- 2026-09-30 — Phase 13 research data foundation recorded as D049: documents amended by plan 13-11 are `SOURCES.md` (Facts verified for Phase 13), `integration/BINANCE.md` (section 13 Historical market data), `data/DATA_MODEL.md` (section 2.13 Research Parquet datasets), `architecture/DATA_PIPELINE.md` (section 15 Phase 13 research data rules), `configuration/CONFIGURATION.md` (runtime configuration of the Phase 13 data tools) and `DECISIONS.md` (D049). `research/RESEARCH_PROTOCOL.md` (v1.1.0 FROZEN) is untouched.
- 2026-10-01 — Phase 13.1 deployment and CI recorded as D050: documents amended by plan 13.1-11 are `operations/RUNBOOK.md` (section 11 extended with the backup, restore and drill procedures; new sections 13 Host bootstrap, 14 Update and rollback, 15 Provider migration, 16 Image and action pins, 17 Tested locally or in CI versus needs a real host, 18 CI pipeline), `operations/SECURITY_AND_OPERATIONS.md` (D050 lines in sections 1, 4, 6, 9 and 10), `SOURCES.md` (Facts verified for Phase 13.1) and `DECISIONS.md` (D050). `research/RESEARCH_PROTOCOL.md` (v1.1.0 FROZEN) is untouched.
