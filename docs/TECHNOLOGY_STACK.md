# Technology Stack

> Core docs v0.3 — 2026-09-19

## 1. Decision

The project uses **Python as the primary implementation language** for research, backtesting, paper trading, and live orchestration.

This is a project-level choice, not a general statement that Python is superior to other languages. The dominant workload is deterministic quantitative research plus low-frequency 1H/4H strategy execution with human approval, not HFT.

## 2. Runtime baseline

- Python baseline: **3.13**.
- Python 3.14 compatibility may be evaluated after the dependency stack is verified. Python 3.14 is currently the latest stable feature series, while Python 3.15 is still pre-release as of 2026-09-19.
- `pyproject.toml` is the canonical project metadata/dependency configuration.
- `uv` is the preferred environment/dependency/task tool unless the implementation later documents a justified alternative.

Binance's current Python connector documentation supports Python 3.10+ for USDⓈ-M Futures, so the project baseline is within the supported range.

## 3. Application/runtime stack

### Core application

- Python 3.13
- `asyncio` for realtime I/O and orchestration
- typed domain models and explicit state machines
- `Decimal` for exchange-sensitive monetary/quantity arithmetic where binary floating point could change a trading decision

### HTTP / webhook surface

- FastAPI is the default choice for optional HTTP endpoints such as TradingView webhooks, health checks, and operational APIs.
- The strategy engine must not depend on FastAPI.

### Persistence

- PostgreSQL for operational state and lifecycle entities.
- SQLAlchemy 2.x + psycopg 3 are the default persistence stack unless a measured requirement justifies a lower-level implementation.
- No ORM model may become the strategy-domain model; domain objects remain explicit and framework-light.

### Research / historical data

- Parquet for immutable raw/derived datasets.
- DuckDB for local analytical queries over Parquet.
- Polars and/or pandas for exploratory analysis.
- NumPy/SciPy for numerical/statistical work.
- VectorBT may be used for exploratory parameter sweeps and research comparison, but it is not the canonical execution/backtest semantics.

### Testing / quality

- pytest for tests.
- Ruff for linting/formatting.
- mypy (or another documented static type checker) for type validation.
- Golden fixtures remain the canonical strategy correctness mechanism.

### Deployment

- Docker for packaging/runtime isolation.
- PostgreSQL backup must be external to the primary runtime host.
- Redis remains optional and must not be introduced unless a documented concurrency/caching requirement exists.

## 4. Official Binance Python SDK

The current Binance connector family includes a dedicated USDⓈ-M Futures Python SDK supporting REST, WebSocket API, and WebSocket Streams. The official SDK documentation currently requires Python 3.10+.

The project should prefer the current official connector where it covers the required endpoint. Direct HTTP/WebSocket implementation is allowed when the SDK does not expose a required operation clearly or when an adapter is needed to preserve the project's domain boundary.

Never let SDK response models leak into the domain model.

## 5. Domain boundary

The project is intentionally structured so the strategy does not depend on pandas, Polars, DuckDB, Binance SDK classes, FastAPI, or PostgreSQL models.

```text
External adapters
    ↓
Normalized application data
    ↓
Pure deterministic domain/strategy logic
    ↓
Trade plan / risk decision
    ↓
External adapters
```

This keeps historical research and live execution on the same deterministic strategy implementation.

## 6. Performance policy

Do not rewrite the system in Rust/C++ or introduce distributed compute before a measured bottleneck exists.

Escalation order:

```text
Correct Python
    ↓
Profile
    ↓
NumPy / Polars / Numba / algorithmic improvement
    ↓
Only then consider a native extension or specialized engine
```

## 7. Explicitly rejected for V1

- .NET as the primary implementation language
- TypeScript as the research/runtime language
- Rust as a full rewrite
- Kafka/RabbitMQ or a large microservice topology
- NautilusTrader as the mandatory foundation
- AI/LLM as a trading-decision component

NautilusTrader and other specialized trading frameworks may be evaluated later, but the first version should keep the strategy and execution contracts under project control.

## 8. Source note

Current runtime/package compatibility must be re-checked before implementation or dependency upgrades. See `SOURCES.md`.


### Current verification sources

- Python release/version information: https://www.python.org/doc/versions/
- Binance Python connectors: https://github.com/binance/binance-connector-python
- Binance USDⓈ-M Futures Python SDK: https://github.com/binance/binance-connector-python/tree/master/clients/derivatives_trading_usds_futures
