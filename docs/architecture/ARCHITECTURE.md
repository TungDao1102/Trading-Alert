# Architecture

## 1. High-level system

```text
                         ┌────────────────────┐
                         │ Binance Market Data│
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Market Data Layer  │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Feature Engine     │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Strategy Engine    │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Trade Planner      │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Risk Engine        │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Alert/Approval     │
                         └─────────┬──────────┘
                                   │ APPROVE
                         ┌─────────▼──────────┐
                         │ Execution Manager  │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Binance Futures    │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ User Data Stream   │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼──────────┐
                         │ Journal/Analytics  │
                         └────────────────────┘
```

## 2. Component boundaries

### Market Data Layer

Responsible for:

- REST historical bootstrap.
- WebSocket realtime ingestion.
- reconnect/resync.
- deduplication.
- UTC normalization.
- symbol/timeframe normalization.

### Feature Engine

Responsible only for deterministic transformations:

- ATR,
- EMA,
- volume metrics,
- market structure,
- zones,
- futures context.

It must not generate orders.

### Strategy Engine

Consumes features + closed candles and produces:

```text
NO_TRADE
or
SETUP
```

It must not call Binance trading endpoints.

### Trade Planner

Transforms a valid setup into:

- direction,
- entry zone,
- SL,
- TP,
- expiry,
- invalidation,
- strategy metadata.

### Risk Engine

Calculates whether the proposed trade fits account and portfolio constraints and derives quantity.

### Approval/Alert

Presents the trade plan and records user intent.

### Execution Manager

Only component allowed to call live trading endpoints.

### Journal

Consumes all lifecycle events, including skipped signals.

## 3. Required separation

The following dependencies are forbidden:

```text
Strategy → Telegram directly
Strategy → Binance order API
LLM → Strategy decision
UI → direct Binance order API
```

Use application services/interfaces between components.

## 4. Technology baseline

The project is implemented primarily in Python. See `TECHNOLOGY_STACK.md` for the canonical technology decision.

Baseline components:

- Python 3.13.
- `asyncio` for realtime I/O/orchestration.
- Binance official Python connector where applicable.
- FastAPI for optional webhook/health/operational HTTP endpoints.
- PostgreSQL for operational state.
- Parquet + DuckDB for historical/research datasets.
- Polars/pandas/NumPy/SciPy for research and analysis.
- pytest + Ruff + static type checking for verification.
- Docker for packaging/runtime isolation.

Do not introduce Kafka/RabbitMQ, Kubernetes, or a large microservice topology until a documented scalability/reliability requirement exists.

## 4.1 Python project structure

A recommended initial repository shape is:

```text
src/
  domain/
  strategy/
  risk/
  planning/
  execution/
  data/
  backtest/
  notifications/
  infrastructure/
  api/
research/
  notebooks/
  experiments/
data/
  raw/
  processed/
tests/
  unit/
  golden/
  integration/
docs/
pyproject.toml
Dockerfile
```

The exact module split may evolve, but the boundary rule is fixed: research tooling and external SDKs must not become the strategy domain model.

## 5. State machines

Every signal, order, and position should have an explicit lifecycle. Avoid deriving state only from nullable columns.

## 6. Realtime principle

Use WebSocket for realtime market/user events and REST for bootstrap, reconciliation, and operations. Binance is believed to document a 24-hour lifetime for a single market-data WebSocket connection and to recommend user-data WebSocket updates for order/position state during volatile conditions; this was not confirmed on a fetched page on 2026-09-30, so verify against current Binance docs before implementation. [Binance WebSocket market streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Connect)
