# Binance Futures Signal & Semi-Automation — Core Documentation

> Status: Core docs v0.3 — 2026-09-19
>
> Purpose: define the product, research process, architecture, risk model, execution model, data contracts, and implementation gates for a deterministic Binance Futures research/trading assistant.

## Core principle

The system is **not an AI trading predictor**. Trading decisions must be deterministic and reproducible from market/account data plus a versioned strategy specification.

The primary implementation language is Python. The intended operating model is:

```text
Binance market data
        ↓
Feature engine
        ↓
Deterministic strategy
        ↓
Trade plan (Entry / SL / TP / risk)
        ↓
Telegram alert
        ↓
Human APPROVE / SKIP
        ↓
Order manager
        ↓
Binance
        ↓
User-data events
        ↓
Journal / analytics
```

## Document map

| Document | Role | Status |
|---|---|---|
| `00_PRODUCT_SCOPE.md` | Product goals, constraints, non-goals | Stable baseline |
| `TECHNOLOGY_STACK.md` | Python runtime, research stack, persistence and tooling | **Canonical** |
| `01_ENGINEERING_PRINCIPLES.md` | Rules agents must not violate | Stable baseline |
| `research/TRADING_STRATEGY_RESEARCH.md` | Trading concepts, candidate strategies, research log | Living |
| `strategy/TRADING_STRATEGY_SPEC.md` | Frozen deterministic strategy contract | **TBD / blocked by research** |
| `architecture/ARCHITECTURE.md` | System architecture and boundaries | Stable baseline |
| `architecture/DATA_PIPELINE.md` | Market/account data ingestion and normalization | Baseline |
| `trading/RISK_MANAGEMENT.md` | Risk, position sizing, portfolio limits | Baseline + parameters TBD |
| `trading/EXECUTION_SPEC.md` | Human approval, order lifecycle, SL/TP, expiry | Baseline + Binance details verified before implementation |
| `trading/SIGNAL_AND_ALERTS.md` | Signal/trade-plan schema and notification UX | Baseline |
| `backtest/BACKTEST_SPEC.md` | Historical simulation and validation methodology | Baseline |
| `backtest/METRICS.md` | Metrics, journal schema, experiment reporting | Baseline |
| `integration/BINANCE.md` | Binance API/WebSocket integration contract | Current-data dependent |
| `integration/TRADINGVIEW.md` | TradingView research/cross-check/webhook adapter | Optional |
| `integration/TELEGRAM.md` | Approval/notification transport | Baseline |
| `operations/SECURITY_AND_OPERATIONS.md` | Secrets, uptime, reconnect, monitoring, incident handling | Baseline |
| `implementation/IMPLEMENTATION_PLAN.md` | Phased build plan and gates | Baseline |
| `DECISIONS.md` | Architecture/strategy decision log | Living |
| `GLOSSARY.md` | Canonical terminology and enums | **Canonical** |
| `data/DATA_MODEL.md` | Persistence/domain model | **Canonical** |
| `configuration/CONFIGURATION.md` | Parameter registry and reproducibility | **Canonical** |
| `testing/TESTING_STRATEGY.md` | Golden fixtures and deterministic test protocol | **Canonical** |
| `operations/RUNBOOK.md` | Incident/emergency procedures | **Operational** |

## Dependency order

```text
PRODUCT_SCOPE
    ↓
ENGINEERING_PRINCIPLES
    ↓
TRADING_STRATEGY_RESEARCH
    ↓
TRADING_STRATEGY_SPEC
    ↓
DATA_MODEL + CONFIGURATION + TESTING_STRATEGY
    ↓
BACKTEST_SPEC + RISK_MANAGEMENT
    ↓
ARCHITECTURE + DATA_PIPELINE + EXECUTION
    ↓
IMPLEMENTATION_PLAN
    ↓
Implementation
```

Do not let coding agents silently invent missing strategy rules. Missing strategy rules must remain `TBD` and become explicit research tasks.

## Source policy

Current Binance/TradingView API details must be verified against official documentation immediately before implementation because API behavior changes. Core design should reference official docs but avoid hard-coding unstable details into strategy logic.

## Python implementation note

Python is used because this project is research-heavy and operates primarily on 1H/4H strategy logic rather than ultra-low-latency execution. The same deterministic strategy implementation must run in historical backtests, paper mode, and live mode. See `TECHNOLOGY_STACK.md`.
