# Stack Research: Deterministic Binance Futures Research & Execution System

**Domain:** Deterministic crypto-futures research + semi-automated execution (Binance USDⓈ-M, 4H/1H swing, human approval)
**Researched:** 2026-09-19
**Confidence:** HIGH (exchange SDK + core data/DB/web versions verified against PyPI/official docs Sep 2026; floors marked MEDIUM where only training knowledge applies)

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.13.x (latest patch at init) | Single implementation language for research, backtest, paper, live | Canonical doc decision (D018); Binance official SDKs require 3.10+, so 3.13 is inside the supported range. Deterministic quant-research + low-frequency execution workload — no HFT latency case for another language. Do NOT move to 3.14 yet: dependency stack is verified on 3.13; evaluate 3.14 only after `uv lock` resolves cleanly |
| uv | >= 0.7 (latest at init) | Env, dependency, lockfile, task runner (`uv run`, `uv sync`) | Canonical tool choice; lockfile (`uv.lock`) is the reproducibility mechanism — deterministic builds are a first-class requirement here, and uv's resolver + lockfile is faster and stricter than pip-tools. Verified in the wild May 2026 (uv/0.11.14 publishing to PyPI) |
| asyncio (stdlib) | 3.13 stdlib | Realtime I/O orchestration: WS market data, user-data streams, Telegram, reconnection | Native to the workload (concurrent streams + timers, no CPU parallelism needed). python-telegram-bot is asyncio-native since v20, SQLAlchemy/psycopg both expose async engines — the whole stack converges on one loop. No trio/curio split-brain |
| PostgreSQL | 17 (bookworm Docker image) | Operational state: signals, plans, approvals, orders, fills, positions, journal | Transactional lifecycle entities need ACID + constraints + Alembic migrations. PG17 is the mature stable line (PG18 exists but tooling/images lag). Backup MUST be external to the primary host per SECURITY_AND_OPERATIONS |
| Parquet + DuckDB | Parquet (via pyarrow >= 19), DuckDB 1.5.5 | Immutable research datasets (raw + derived candles, funding, OI snapshots) and local analytical SQL over them | Separation of analytical vs transactional storage (D019–D021). DuckDB 1.5.5 verified on PyPI (released 2026-07-22); reads Parquet in-place, larger-than-memory, zero server. Store raw immutable → derived versioned; never mutate a published dataset file |

### Exchange Connectivity (Binance USDⓈ-M)

| Library | Version | Purpose | Why Recommended |
|---------|---------|---------|-----------------|
| `binance-sdk-derivatives-trading-usds-futures` | >= 17.3, < 18 (17.3.1 released 2026-09-10) | Official REST (`/fapi/*`), WS API, WS Streams for USDⓈ-M Futures | This is THE connector: covers market data, `exchangeInfo` (dynamic stepSize/tick/notional), trading, account, **and the post-migration conditional-order endpoint `POST /fapi/v1/algoOrder`** (STOP_MARKET / TAKE_PROFIT_MARKET / STOP / TAKE_PROFIT / TRAILING_STOP_MARKET) plus `ALGO_UPDATE` user-data events. Verified: PyPI 17.2.1 + GitHub release v17.3.1 (Sep 10 2026, algoUpdate/user-data fields). Requires Python 3.10+ — satisfied. Legacy `binance-connector` 3.13.0 and `binance-futures-connector` 4.2.0 were **archived/deprecated 2026-04-30** — never use them |
| `binance-sdk-algo` | 3.4.0 (evaluate in Phase 3+, NOT V1) | Official TWAP/VP execution algos (`/sapi/v1/algo/futures/*`) | Separate package from the futures SDK. TWAP/VP are *execution* algos (min notional ~1,000 USDT, max 10–30 open), NOT protective SL/TP — V1 protective exits use CONDITIONAL algo orders in the futures SDK. Defer until live execution actually needs scheduled execution; verify endpoint weights (TWAP new-order weight 3000 UID) before any use |
| Adapter layer (own code) | — | Isolate ALL SDK response models behind project-owned interfaces | Canonical boundary: SDK classes must never leak into the domain/strategy model. Direct HTTP/WS implementation is allowed where the SDK lacks a required operation, but default to the official SDK where it covers the endpoint |

**Endpoint-authority notes (re-verify from developers.binance.com immediately before implementation — HIGH confidence on structure, MEDIUM on field details):**
- Protective exits: `POST /fapi/v1/algoOrder` with `algoType=CONDITIONAL`; query via `GET /fapi/v1/algoOrder`; cancel via `DELETE /fapi/v1/algoOrder`. Weight 1 on order-count limits, 0 on IP weight — cheap to manage.
- Conditional-order lifecycle moved to the Algo Service (Dec 2025 changelog): `CONDITIONAL_ORDER_TRIGGER_REJECT` event is GONE; rejection reasons now arrive inside `ALGO_UPDATE.o.rm`. The reconciler/orphan-sweeper must parse `ALGO_UPDATE`, not the old event.
- User-data streams are the preferred realtime source for orders/fills/positions (Binance-canonical per D002); REST is fallback + reconciliation.
- 200-conditional-order headroom and position-mode (one-way vs hedge → `positionSide` mandatory in hedge) detection must be dynamic via `exchangeInfo`/account queries, never hard-coded.

### Operational Persistence

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| SQLAlchemy | 2.0.x stable (2.0.52 released 2026-08-11) | ORM + Core for all PostgreSQL access | 2.0-style async (`create_async_engine`, `AsyncSession`) is the documented current API; 2.1 is still RC (2.1.0rc1, Aug 2026) — pin `>=2.0,<2.1`. Verified pattern: `postgresql+psycopg://` async engine, with optional `psycopg_pool.AsyncConnectionPool` + `NullPool` for pool control. No ORM model may become the strategy-domain model |
| psycopg (+pool, binary) | >= 3.3, < 4 (`psycopg[binary,pool]`, 3.3.5 current) | PostgreSQL driver, sync + async | Psycopg 3 is the successor to psycopg2 for all new work (official guidance); native asyncio + `AsyncConnectionPool`. `binary` extra avoids libpq build pain on Windows dev machines; `pool` extra for the async pool. Requires Python >= 3.10 — satisfied |
| Alembic | 1.19.1 (released 2026-08-08) | Schema migrations | Every DATA_MODEL change ships as a reviewed migration; journal/analytics tables evolve across Phase 0→3. Never `create_all` in production code paths |
| Pydantic v2 + pydantic-settings | pydantic >= 2.11, < 3; pydantic-settings >= 2.x | Boundary validation (exchange payloads, webhook bodies, Telegram callbacks) and CONFIGURATION parameter-registry loading | Pydantic v2 (Rust-core) is the standard; settings management cleanly separates the versioned parameter registry from secrets (env/.env, never in git). MEDIUM confidence on exact minor — pin floors, let `uv lock` resolve |

### Research / Analytics

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Polars | >= 1.44 (< 2.0 until API settles; 1.44.1 released 2026-08-26; 2.0.0rc1 exists — do NOT take the RC) | Primary frame engine: feature engineering, 1m-intrabar execution simulation, metric computation | Rust engine, lazy evaluation, multithreaded — the correct default for candle/funding/OI-scale data. Requires Python >= 3.10. Strategy core must NOT import it (domain boundary); it lives in feature/backtest adapters |
| pandas | >= 2.2 (compat/fallback only) | Interop where an API only speaks pandas (some stats helpers, VectorBT) | Secondary citizen: use only at adapter edges, convert to/from Polars explicitly. Never the strategy-domain type |
| NumPy / SciPy | NumPy >= 1.26 (2.x OK if stack resolves); SciPy >= 1.14 | Numerical/statistical work: returns, drawdown, significance/uncertainty reporting (per METRICS) | Foundation under Polars/pandas; SciPy for hypothesis/selection-bias-aware statistics supporting the kill-gate decision. MEDIUM confidence on exact floors |
| pyarrow | >= 19 | Parquet read/write engine under Polars + DuckDB | Required companion; version must satisfy both Polars and DuckDB wheels — `uv lock` is the arbiter |
| VectorBT | >= 0.28 (exploratory ONLY) | Fast parameter sweeps + research comparison | Explicitly NOT the canonical backtest semantics: the project's own engine (closed-candle, no-lookahead, warm-up, 1m intrabar, fees/funding/slippage, quantization) is the authority. VectorBT results are hypotheses, never acceptance evidence. MEDIUM confidence on floor |
| DuckDB | 1.5.5 (see Core Technologies) | SQL analytics over Parquet (dataset QA, journal extracts, opportunity analysis) | Direct `read_parquet` queries; share SQL files between research notebooks and pipeline QA checks |

### HTTP / Webhook Edge

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| FastAPI | >= 0.141, < 0.150 (0.141.1 released 2026-07-29) | TradingView webhooks (secret URL path + source-IP allow-list; TradingView cannot sign requests), Telegram callback receiver (optional), `/healthz` | Edge-only: the strategy engine must not import FastAPI. Pydantic-v2-native request validation gives signature/body checks almost free. Keep the surface minimal: webhook in, health out |
| uvicorn | >= 0.52, < 0.60 (0.52.4 released 2026-08-19) | ASGI server for the FastAPI edge | `uvicorn[standard]` (uvloop + httptools) on Linux/Docker; plain uvicorn on Windows dev. Single-worker suffices for webhook/health volume |
| httpx | 0.28.x stable (0.28.1; 1.0 is dev pre-release — do NOT take) | Async HTTP client for any direct REST needs + test mocking via respx/pytest-httpx | If the official SDK covers the endpoint, the SDK owns the wire. httpx is for gaps, health probes, and Telegram-adjacent calls. MEDIUM confidence on patch |

### Telegram (alerts + approval loop)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `python-telegram-bot` | >= 22.8, < 23 (22.8 released 2026-06-12; Bot API 10.0; Python 3.10+) | SIMULATE/notify + APPROVE/SKIP inline-keyboard callback loop | asyncio-native since v20 — fits the single-loop architecture. Callback handler must implement at-least-once replay to existing approval state (idempotent, expiring approvals per constraints); no auto-approve on notification failure. Pin the major: v20→v22 had breaking changes before, treat upgrades as deliberate |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | >= 9.x | Bounded retries with jitter for REST/WS reconnect, listen-key refresh, Telegram sends | Retry policy is a safety feature (fail-closed): cap attempts, then NO_TRADE/SAFE_MODE — never infinite retry on order paths. MEDIUM confidence on floor |
| structlog | >= 25.x | Structured JSON logs (decision lineage: snapshot → signal → plan → approval → order) | Every deterministic decision must be explainable post-hoc; structured logs + journal rows are the audit trail. Plain `logging` with JSON formatter is an acceptable substitute — do not build a custom logger. MEDIUM confidence on floor |
| python-dateutil / tzdata | stdlib `zoneinfo` + `tzdata` package | UTC-internally, Asia/Ho_Chi_Minh presentation | Canonical zones per PROJECT.md context (resolve Bangkok-vs-HCMC naming in the docs audit; runtime uses `Asia/Ho_Chi_Minh`). Windows needs the `tzdata` wheel since OS zoneinfo is absent |
| PyYAML / tomli | — | Config/parameter-registry file loading (if YAML/TOML chosen) | Only if CONFIGURATION doc selects file-based registry; pydantic-settings validates whatever is loaded |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest + pytest-asyncio | Unit, adapter, golden-fixture, backtest-determinism tests | pytest 9 is current (pytest-httpx 0.36 requires pytest>=9, drops py3.9). pytest-asyncio with `asyncio_mode = "auto"` so async tests need no decorators; anyio is an acceptable alternative ONLY if a plugin forces it — do not mix both |
| respx (or pytest-httpx) | Mock httpx-level calls in adapter tests | Never hit Binance/Telegram in unit tests; golden fixtures + recorded exchangeInfo samples are the canonical correctness mechanism |
| Ruff | Lint + format (replaces flake8/black/isort) | `ruff check` + `ruff format` in pre-commit and CI; version pinned via pre-commit rev or dev dependency — take latest at init (MEDIUM confidence on number, HIGH on choice) |
| mypy (strict) | Static typing over domain, adapters, risk, execution | `strict = true` target for `src/` domain + execution paths; research notebooks/scripts may be excluded via `mypy_path`/overrides. Decimal-vs-float boundaries are exactly what strict typing protects |
| Docker + Docker Compose | Packaging (app + PostgreSQL 17) + local Phase-0 stack | App image pins `python:3.13-slim-bookworm`; Compose wires `postgres:17-bookworm` with a named volume. Backup job is a separate container/cron pushing off-host |
| pre-commit (optional) | Ruff + mypy + trailing-whitespace hooks locally | Nice-to-have; CI quality gates are the enforcement point, not the hook |

## Installation

```bash
# Prereqs: Python 3.13.x, uv (latest), Docker (for PostgreSQL)
uv init --python 3.13   # only if scaffolding fresh; else add to existing pyproject.toml

# Core runtime
uv add "binance-sdk-derivatives-trading-usds-futures>=17.3,<18"
# Algo execution SDK — Phase 3+ evaluation only, NOT V1:
# uv add "binance-sdk-algo>=3.4,<4"
uv add "sqlalchemy>=2.0,<2.1" "psycopg[binary,pool]>=3.3,<4" "alembic>=1.19,<2"
uv add "pydantic>=2.11,<3" "pydantic-settings>=2,<3"

# Research / analytics
uv add "polars>=1.44,<2" "pyarrow>=19" "duckdb>=1.5,<2"
uv add "numpy>=1.26" "scipy>=1.14" "pandas>=2.2"
# Exploratory sweeps only (never canonical semantics):
# uv add "vectorbt>=0.28"

# Edge + Telegram
uv add "fastapi>=0.141,<0.150" "uvicorn[standard]>=0.52,<0.60" "httpx>=0.28,<0.29"
uv add "python-telegram-bot>=22.8,<23"

# Supporting
uv add tenacity structlog tzdata pyyaml

# Dev dependencies
uv add --dev pytest "pytest-asyncio>=1" respx ruff mypy pre-commit
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| psycopg 3 (async) | asyncpg | Only if profiling proves the async DB path is the bottleneck AND asyncpg's prepared-statement behavior is validated against the migration story; psycopg 3 keeps sync/async on one driver and is the documented SQLAlchemy-async path |
| SQLAlchemy 2.0.x | SQLModel / raw psycopg | SQLModel if the FastAPI edge grows full CRUD (it doesn't in V1 — webhook/health only). Raw psycopg only inside a measured hot path, never as the default |
| Polars (primary) | pandas-only | Only at narrow interop edges (a helper that only accepts pandas); default stays Polars for lazy/multithreaded scans |
| Own backtest engine (canonical) | VectorBT / Backtrader / Freqtrade / NautilusTrader as foundation | VectorBT for throwaway sweeps; the canonical engine stays project-owned so backtest/paper/live share identical execution semantics (fees/funding/slippage/quantization). Revisit NautilusTrader only as a *comparison harness*, never as the mandatory core, until a measured need exists |
| `uvicorn[standard]` | gunicorn+uvicorn workers | Only if the edge ever needs multi-process serving (webhook/health volume says it won't in V1) |
| structlog | stdlib logging + JSON formatter | If the team prefers zero extra deps — either is fine, but pick ONE and standardize the decision-lineage schema |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `binance-connector` / `binance-futures-connector` (legacy) | Deprecated and archived 2026-04-30; lack Algo-Order/conditional endpoints and current user-data events | `binance-sdk-derivatives-trading-usds-futures>=17.3` (+ `binance-sdk-algo` later for TWAP/VP) |
| Kafka / RabbitMQ / large microservice topology / K8s | No measured throughput or team-size justification; a single-asyncio-process + PostgreSQL system has orders of magnitude of headroom for 4H/1H swing trading. Adds failure modes to a fail-closed safety design | In-process asyncio queues → PostgreSQL rows; Docker Compose for packaging |
| Rust/C++ rewrite or native extension first | Performance policy escalation order is Correct-Python → Profile → NumPy/Polars/Numba → only then native. A rewrite before a measured bottleneck burns the 15–24-month part-time budget for zero evidence | Polars/NumPy vectorization when profiling points at a loop |
| NautilusTrader as mandatory foundation | Takes strategy/execution contracts out of project control; V1's value is identical semantics across backtest/paper/live, which a foreign engine cannot guarantee without an adapter layer as thick as the engine itself | Project-owned deterministic engine; NT only as late-stage comparison harness |
| LLM/AI in the decision path (direction/entry/SL/TP/size/parameters/signal-validity) | Violates D001 determinism: same snapshot + spec + config must equal same decision, byte-equivalent. Stale-context subjective predictions are un-backtestable | LLM allowed for code/docs/tests/explanations only, behind human review |
| ccxt as the execution connector | ccxt normalizes across exchanges — V1 needs Binance-native semantics (Algo Orders, `ALGO_UPDATE.o.rm` rejections, position modes, 200-order headroom), which a generic shim obscures. Useful later for multi-venue research data, never for order paths | Official Binance SDKs behind project adapters |
| Redis (V1) | No documented concurrency/caching requirement; listen-keys, idempotency keys, and approval state all live correctly in PostgreSQL with TTL columns | PostgreSQL + in-process state; revisit only with a measured contention profile |
| .NET / TypeScript as primary language | Canonical decision is Python 3.13 for the quant-research ecosystem (Polars/SciPy/VectorBT) and the official Binance Python SDKs | Python 3.13 + uv |
| httpx 1.0 pre-releases / Polars 2.0 RC / SQLAlchemy 2.1 RC / Python 3.14 as baseline | Pre-release lines move under you; determinism starts with pinned stable dependencies | Stable lines listed above; re-evaluate RCs at defined upgrade windows, never mid-phase |
| `float` for quantities/prices/notional/risk arithmetic | Binary floating point changes trading decisions (quantization floor → min-qty/min-notional rejects → realized-risk utilization check). A 1-ulp difference can flip NO_TRADE to an order | `Decimal` (or integer tick/qty-step arithmetic) for all exchange-sensitive values; floats allowed only inside statistical/feature code that never gates an order |

## Stack Patterns by Variant

**If Phase 0 (data foundation only):**
- Install runtime + research + persistence subsets; defer FastAPI/Telegram/Algo SDK. DuckDB + Parquet + collectors + Alembic-baselined PostgreSQL are the whole world. Backup/restore smoke test runs against Compose PostgreSQL 17.

**If Phase 1 (backtest research):**
- Add the full research subset (Polars/SciPy/VectorBT-exploratory). No networked services required; Binance SDK used only for historical REST pulls and exchangeInfo snapshots (versioned into fixtures).

**If Phase 2 (paper) / Phase 3 (live):**
- Add FastAPI edge, python-telegram-bot approval loop, full SDK surface (WS streams + user-data + `algoOrder` conditionals). Re-verify SDK minor version and the Futures change-log before wiring order paths — Binance migrates endpoints (Dec 2025 Algo migration precedent) and the code must follow the docs, not memory.

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `binance-sdk-*-futures >= 17.3` | Python >= 3.10 (3.13 OK) | Auto-generated SDK; minor bumps track REST/WS changes — read CHANGELOG per bump, especially Trade/Algo sections |
| SQLAlchemy 2.0.x + psycopg 3.3+ | `postgresql+psycopg://` sync AND async; `psycopg_pool` for external pooling | Verified pattern from official SQLAlchemy 2.0 dialect docs (Context7). asyncpg NOT required |
| Polars 1.44 + pyarrow 19+ + DuckDB 1.5.5 | Python >= 3.10; mutual Parquet compatibility via Arrow | `uv lock` arbitrates; if DuckDB and Polars disagree on a pyarrow floor, take the higher floor |
| FastAPI 0.141 + pydantic 2.11+ + uvicorn 0.52 | Python >= 3.10 | Standard trio; no known conflicts at these floors |
| python-telegram-bot 22.8 | Python >= 3.10; Bot API 10.0; httpx-based internally | Pin major 22; check Bot API changelog when approval UX needs new message features |
| pytest 9 + pytest-asyncio (auto mode) | Python 3.13 | pytest 8 EOL in plugin ecosystem (pytest-httpx 0.36 requires 9). Do not mix pytest-asyncio with anyio in the same suite |
| PostgreSQL 17-bookworm image | SQLAlchemy/psycopg/Alembic above | pgvector-style extensions NOT needed in V1; keep the image stock |

## Sources

- PyPI `binance-sdk-derivatives-trading-usds-futures` (17.2.1 listing; GitHub releases to v17.3.1, Sep 10 2026) + USDⓈ-M Futures SDK README (REST/WS API/WS Streams, Python 3.10+) — HIGH
- PyPI archived markers: `binance-connector` 3.13.0, `binance-futures-connector` 4.2.0 (both archived Apr 30 2026) — HIGH
- PyPI `binance-sdk-algo` 3.4.0 (`/sapi/v1/algo/*` TWAP/VP) + SDK source `future_algo_api.py` — HIGH
- Binance docs: New/Query Algo Order (`/fapi/v1/algoOrder`, CONDITIONAL types), Algo Trading REST (Future Algo), derivatives change-log (Dec 2025 conditional→Algo migration, `ALGO_UPDATE.o.rm`) — HIGH structure / MEDIUM field detail
- PyPI: `polars` 1.44.1 (Aug 26 2026), `duckdb` 1.5.5 (Jul 22 2026), `fastapi` 0.141.1 (Jul 29 2026), `uvicorn` 0.52.4 (Aug 19 2026), `python-telegram-bot` 22.8 (Jun 12 2026, Bot API 10.0), `psycopg` 3.3.4→3.3.5 (May 2026), `httpx` 0.28.1 stable / 1.0 dev-pre, `alembic` 1.19.1 (Aug 8 2026), `pytest` 9 / pytest-httpx 0.36 changelog — HIGH
- Context7 `/websites/sqlalchemy_en_20` (async engine + psycopg_pool patterns), `/pola-rs/polars`, `/duckdb/duckdb-python`, `/websites/psycopg_psycopg3`, `/websites/fastapi_tiangolo`, `/pytest-dev/pytest`, `/pydantic/pydantic` (library IDs resolved, docs sampled for SQLAlchemy-async) — HIGH
- `docs/TECHNOLOGY_STACK.md` + `docs/SOURCES.md` (canonical decisions D001–D021, re-verification policy) — HIGH (project authority)
- NumPy/SciPy/pandas/tenacity/structlog/ruff/mypy floors: training knowledge + ecosystem convention, NOT re-verified this pass — MEDIUM; Phase-0 `uv lock` resolution is the acceptance check

---
*Stack research for: Deterministic Binance Futures Research & Semi-Automated Execution System*
*Researched: 2026-09-19*
