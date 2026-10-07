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
- `research/RESEARCH_PROTOCOL.md` — Frozen on 2026-09-19, amended 2026-10-07 (v2.1.0; D029, D030, D043, D052, D057, D060); executable gate at `.github/workflows/research-gate.yml`

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
- 2026-10-01 — Phase 17 operational persistence layer recorded as D051: documents amended in Phase 17 are `GLOSSARY.md` (section 11 legal state transitions, section 12 persistence status values, a section 9.4 row for `UNRESOLVED_EXECUTION_INTENT`; sections 8.2, 9.1-9.3 and 10 untouched), `data/DATA_MODEL.md` (new sections 2.14 `execution_intents`, 2.15 `plan_constraint_snapshots`, 2.16 `system_state_events`, approval consumption columns, integrity rules), `trading/EXECUTION_SPEC.md` (section 7 idempotency rewritten: write-ahead order, the exchange does not deduplicate; section 10 restart recovery), `integration/BINANCE.md` (section 6.1 client order id uniqueness), `SOURCES.md` (Facts verified for Phase 17), `testing/TESTING_STRATEGY.md` (section 8 transition checks, sections 10 and 11 test inventory, new section 12.1 PostgreSQL tests), `operations/RUNBOOK.md` (sections 5, 6, 9, 11.5 and 14.4), `operations/SECURITY_AND_OPERATIONS.md` (section 9) and `DECISIONS.md` (D051; the transition tables are recorded as an auto-mode default awaiting user confirmation). `research/RESEARCH_PROTOCOL.md` (v1.1.0 FROZEN) is untouched.
- 2026-10-04 — Operator ratified the ApprovalResult value set (PENDING, APPROVED, SKIPPED, EXPIRED) and the D043 numeric pre-registration as written; `GLOSSARY.md` section 10 now records the ApprovalResult ratification. No enum value, protocol number or decision row changed.
- 2026-10-04 — Operator ratified D046 item 6 (cost ceiling 0.15, minimum stop about 0.79 percent, values kept) and accepted the three Phase 10 kill-gate policy calls (D030 as a clarification, permanent INSUFFICIENT_EDGE terminal, budget restart after a reset); `DECISIONS.md` D046 status updated. No parameter set, threshold or code changed.
- 2026-10-05 — `research/RESEARCH_PROTOCOL.md` v2.0.0 semantic amendment per D052 (Phase 14, backtest causality): the execution simulation is rebuilt (plan active from bar N+1, trade-through fills, mark-price triggers, TP1/TP2 ladder, funding, point-in-time constraints, simulated ledger, one R denominator) and all earlier backtest evidence is void. Thresholds, splits and the D030 kill-gate rule are unchanged. Header `Status` and `Frozen on` unchanged (the D013 clock is not restarted); `Amended on` 2026-10-05 and `Supersedes: v1.1.0`. The version witnesses in the gate code and tests are now read from the header.
- 2026-10-07 — `DECISIONS.md` D055 to D059 recorded (user decisions): D055 protective stop loss -4509 safety invariant and Demo probe plan (execution model stays open), D056 DEGRADED health policy, D057 G5 minimum holdout sample of 30 closed trades (decision only; `research/RESEARCH_PROTOCOL.md` stayed at v2.0.0 until the amendment recorded in the next entry, D060, landed), D058 live mark-price fail-closed rule (OQ-1 stays open), D059 deferral and commitment register. No protocol, code or parameter file changed.
- 2026-10-07 — `research/RESEARCH_PROTOCOL.md` v2.1.0 semantic amendment per D057 and D060 (acceptance gate G5): G5 gains a floor of at least 30 closed trades in the holdout (counted as G1 counts them; fewer than 30 cannot pass and consumes the holdout for that lineage; 30 is an eligibility floor, never an edge claim); `research/holdout_consumed.json` moves to schema holdout-consumed/2 with a per-entry `protocol_version`; `Frozen on` unchanged; nothing applied backwards; `BACKTEST_SPEC.md` pointers and the decision-alignment gate and tests follow.
- 2026-10-07 — `DECISIONS.md` D061 recorded (user decisions with reviewer input): Phase 16 pre-decisions for the freeze check, parity, structure, paper exit criteria process, empty allowlist, kill-gate guard, machine roles, the chain that closes Phase 16 (PAPER-03 stays Pending for Phase 26) and the planned EC2 Singapore host for the long soak. Open items are listed in the row. No code, protocol or parameter file changed.
