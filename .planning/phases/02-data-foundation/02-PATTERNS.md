# Phase 2: Data Foundation — Pattern Map

**Mapped:** 2026-09-19
**Files analyzed:** 22 (16 new + 6 modified/created-as-part-of-Wave-0)
**Analogs found:** 18 with format/structure analogs / 22 (research-derived patterns carry the rest; 2 greenfield infrastructure files have no in-repo analog)

## Phase Context (greenfield code, rich doc corpus)

This is a **code-creation** phase (CONTEXT D-01..D-12). `git ls-files` confirms zero `src/`, zero `tests/`, zero `pyproject.toml`, zero `Dockerfile`, zero `docker-compose.yml`, zero `.sql` files. The working material is:

- The `docs/` corpus (27 markdown files, Core Docs v0.3) — canonical contracts the code must conform to.
- `02-RESEARCH.md` §Architecture Patterns (lines 175-256) and §Code Examples (lines 297-351) — explicit Python patterns from the Phase-2 researcher, cited with line numbers below.
- `.github/workflows/research-gate.yml` (Phase 1) — the only existing CI workflow; Phase 2 may extend it but does not replace it.

Doc-derived patterns dominate this map because every code module Phase 2 ships has a corresponding doc owner (DATA_PIPELINE §6/§9/§10/§11/§13/§14, DATA_MODEL §2.1/§2.11, BINANCE §2/§8, CONFIGURATION §6, SECURITY §9, RUNBOOK §11). The doc IS the analog; the planner's job is to extract the exact code excerpt and a verified existing-doc line range, not to invent patterns.

Code / module vocabulary used in the table:

| Module role | Module data flow |
|-------------|------------------|
| `adapter` | SDK-bounded dataclass projection; the ONLY module that imports `binance-sdk-derivatives-trading-usds-futures` |
| `service` (data plane) | async orchestration of REST pagination, watermark/gap-journal, Parquet publish |
| `pure-function` (data plane) | Polars-typed quality gate; deterministic, testable without network/DB |
| `service` (CLI) | terminal entrypoint: coverage report, optional backfill trigger |
| `model` (ORM) | SQLAlchemy 2.0 async declarative; PG metadata/watermarks/gaps |
| `migration` | Alembic baseline; one reviewed migration per DATA_MODEL change |
| `sql-view` | checked-in DuckDB view; queryable contract over Parquet hive |
| `script` (ops) | single-command backup + scratch-restore drill |
| `toolchain` (config) | `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `alembic.ini`, `pytest.ini`/ini-options in pyproject |
| `test-fixture` | golden recorded samples (exchangeInfo/kline-page/OI/funding) committed under `tests/fixtures/` |

## File Classification

| # | New/Modified File | Module Role | Module Data Flow | Closest Format/Structure Analog | Match Quality |
|---|-------------------|-------------|------------------|---------------------------------|---------------|
| 1 | `pyproject.toml` *(new, Wave 0)* | toolchain (project init) | dependency/pytest/ruff/mypy config | `docs/TECHNOLOGY_STACK.md` — §Core Technologies + §Dev Tools tables; `pyproject.toml` shape referenced by `docs/01_ENGINEERING_PRINCIPLES.md:103` ("`pyproject.toml` as project configuration source") | exact (D021 + D019 + D021 lock the version pins) |
| 2 | `uv.lock` *(new, generated from pyproject)* | toolchain (lockfile) | deterministic-resolve artifact | not authored — produced by `uv lock`; existence verified | n/a (generated) |
| 3 | `Dockerfile` *(new, Wave 0)* | toolchain (packaging) | `python:3.13-slim-bookworm` + uv-based install | `docs/operations/SECURITY_AND_OPERATIONS.md:112-117` §10 Python runtime ops rules; `docs/TECHNOLOGY_STACK.md` Docker row | exact |
| 4 | `docker-compose.yml` *(new, Wave 0)* | toolchain (local stack) | app + `postgres:17-bookworm` + named volume | `docs/architecture/DATA_PIPELINE.md:158-160` §13 storage diagram; `docs/TECHNOLOGY_STACK.md` Docker row | exact |
| 5 | `alembic.ini` *(new, Wave 0)* | toolchain (migration runner) | `alembic` config + `script_location = src/db/alembic` | `docs/architecture/DATA_PIPELINE.md:158-160` (PG for operational state); `docs/configuration/CONFIGURATION.md:88-96` §6 storage model | exact |
| 6 | `src/db/alembic/env.py` *(new)* | migration runtime | async engine + `target_metadata = Base.metadata` | `02-RESEARCH.md:336-342` §Code Examples — SQLAlchemy 2.0 async engine pattern | exact |
| 7 | `src/db/alembic/versions/0001_baseline.py` *(new)* | migration (baseline) | CREATE TABLE for `symbol_metadata`, `collector_watermarks`, `collector_gaps`, coverage-window table | `docs/data/DATA_MODEL.md:287-308` §2.11 `symbol_metadata` fields; §2.1 `market_candles` field-shape; D-05 + D-08 + D-09 | exact (fields from DATA_MODEL) |
| 8 | `src/db/models.py` *(new)* | ORM model | SQLAlchemy 2.0 async declarative | `docs/data/DATA_MODEL.md:287-308` §2.11 `symbol_metadata` schema; `02-RESEARCH.md:336-342` async-engine pattern; D-04 (immutable raw, PG owns only metadata/watermarks) | exact |
| 9 | `src/adapters/binance_usdm.py` *(new)* | adapter | SDK import boundary → frozen dataclasses with `Decimal` | `02-RESEARCH.md:198-207` Pattern 1 "Adapter boundary"; `docs/integration/BINANCE.md:17-21` §2 Python SDK; `docs/architecture/DATA_PIPELINE.md:162-164` §14 Python implementation rule | exact |
| 10 | `src/data/quality.py` *(new)* | pure-function (Polars) | fail-closed structural checks + warn-flag continuity checks | `02-RESEARCH.md:300-318` §Code Examples — "Backfill quality gate (Polars — pure, testable)"; `docs/architecture/DATA_PIPELINE.md:69-77` §6 quality rules; D-10 | exact (verbatim code-shape, swap interval_ms per TF) |
| 11 | `src/data/store.py` *(new)* | service (Parquet publish) | immutable per-day Hive-partitioned Parquet via Polars `write_parquet` | `02-RESEARCH.md:209-223` Pattern 2 deterministic paginated backfill; D-04 partition layout; `docs/architecture/DATA_PIPELINE.md:144-160` §13 storage architecture; §11 partitioning | exact |
| 12 | `src/data/backfill.py` *(new)* | service (async paginator) | windowed cursor + page cursors + tenacity + drop-forming-candle | `02-RESEARCH.md:209-223` Pattern 2; D-02 depth bounds; D-10 quality gate; D-03 SDK via adapter; Pitfall 1 (forming candle) + Pitfall 5 (weight-aware pacing) | exact (the pseudocode block is the canonical pattern) |
| 13 | `src/data/collector.py` *(new)* | service (long-running async loop) | 5-min OI + daily funding sweep + watermark + gap journal | `02-RESEARCH.md:225-226` Pattern 3 OI/funding collector with watermark + gap journal; D-07 (5-min cadence); D-08 (funding backfill + ongoing); D-09 (gap-never-fabricate); `docs/architecture/DATA_PIPELINE.md:95-105` §9 OI collector | exact |
| 14 | `src/data/metadata.py` *(new)* | service (one-shot) | `exchangeInfo` → versioned `symbol_metadata` upsert + Decimal parse | `02-RESEARCH.md:228-230` Pattern 4 versioned symbol metadata; `docs/data/DATA_MODEL.md:287-308` §2.11 fields; D-03 SDK via adapter; Pitfall 4 (Decimal for filters) | exact |
| 15 | `src/data/coverage.py` *(new)* | service (CLI + DuckDB) | per-symbol effective range + violation/gap counts + DuckDB view load | `02-RESEARCH.md:321-333` §Code Examples — DuckDB hive-partitioned coverage view; D-11; `docs/architecture/DATA_PIPELINE.md:107-120` §10 historical coverage; `docs/architecture/DATA_PIPELINE.md:144-160` §13 storage architecture | exact |
| 16 | `src/sql/coverage_v1.sql` *(new, checked-in)* | sql-view | DuckDB `read_parquet(..., hive_partitioning=true)` + per-symbol aggregates | `02-RESEARCH.md:321-333` §Code Examples — DuckDB coverage view; D-04 partition layout; D-11 per-symbol range | exact |
| 17 | `src/ops/backup.py` *(new)* | service (CLI script) | `pg_dump -Fc` + Parquet rsync/copy + off-host + scratch-restore + row-count/hash verify | `02-RESEARCH.md:232-234` Pattern 5 single-command backup + scratch-restore drill; D-12; `docs/operations/SECURITY_AND_OPERATIONS.md:98-109` §9 backup; `docs/operations/RUNBOOK.md:128-141` §11 backup/restore | exact |
| 18 | `scripts/backup-drill.ps1` *(new, Wave 0 wrapper)* | script (ops) | PowerShell entrypoint that calls `uv run python -m src.ops.backup drill` | `docs/operations/RUNBOOK.md:128-141` §11 backup/restore (procedure); `02-VALIDATION.md:46` row `02-04-01` references `scripts/backup-drill.ps1` | exact (format analog) |
| 19 | `tests/conftest.py` *(new, Wave 0)* | test-fixture (shared) | golden exchangeInfo + kline page samples + frozen-clock helper | `docs/testing/TESTING_STRATEGY.md:13-22` §2 golden-fixture model; `02-RESEARCH.md:107` test design notes | exact (file layout) |
| 20 | `tests/fixtures/exchange_info_sample.json` *(new, recorded)* | test-fixture (golden) | frozen recorded `exchangeInfo` response | `docs/integration/BINANCE.md:9-13` (verified endpoint shapes); `02-RESEARCH.md:78` endpoint table | exact (canonical shape) |
| 21 | `tests/test_quality_gates.py` *(new, Wave 0)* | test | fail-closed + warn-flag assertions | `02-RESEARCH.md:299-318` quality-gate Polars pattern; D-10 | exact (test surface) |
| 22 | `tests/test_collector.py` *(new, Wave 0)* | test | gap-never-fabricate under fake clock | `02-RESEARCH.md:225-226` Pattern 3; D-09; `docs/testing/TESTING_STRATEGY.md:107-117` §8 state-machine tests | exact (test surface) |

## Pattern Assignments

### 1. `pyproject.toml` *(new, Wave 0)* — toolchain / project-init

**Analog:** `docs/TECHNOLOGY_STACK.md` (canonical stack tables: Core Technologies, Persistence, Research, Dev Tools). Hard rule from `docs/01_ENGINEERING_PRINCIPLES.md:103`: "`pyproject.toml` as the project configuration source and keep tool configuration versioned."

**Required sections** (cross-referenced to AGENTS.md / STACK.md):

```toml
# Source: AGENTS.md / TECHNOLOGY_STACK.md §Core + §Dev (verified versions 2026-09-19)
[project]
name = "trading-alert"
version = "0.1.0"
requires-python = "==3.13.*"  # D019; never 3.14
dependencies = [
  "binance-sdk-derivatives-trading-usds-futures>=17.3,<18",   # 17.4.0 verified today
  "pyarrow>=19",                                              # 25.0.1 verified
  "duckdb==1.5.5",                                            # pinned per STACK
  "polars>=1.44,<2.0",                                        # 1.44.2 verified; NOT 2.0.0rc1
  "sqlalchemy>=2.0,<2.1",                                     # 2.0.54 verified; NOT 2.1rc1
  "psycopg[binary,pool]>=3.3,<4",                             # 3.3.6 verified
  "alembic>=1.19",                                            # 1.20.0 verified
  "pydantic>=2.11,<3",                                        # 2.13.5 verified
  "pydantic-settings>=2",
  "tenacity>=9",                                              # 9.1.4 verified
  "structlog>=25",                                            # 26.1.0 verified
  "tzdata",                                                   # 2026.4 verified; Windows zoneinfo
]

[project.optional-dependencies]
dev = [
  "pytest>=9",                                                # 9.1.1 verified
  "pytest-asyncio>=1.4",                                      # 1.4.0 verified
  "respx>=0.23",                                              # 0.23.1 verified
  "ruff",
  "mypy",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"                                         # RESEARCH.md §Validation Architecture
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.mypy]
python_version = "3.13"
strict = true                                                 # RESEARCH.md §Dev Tools: "mypy strict for src/"
files = ["src"]
```

**Forbidden versions** (RESEARCH.md `## Deprecated/outdated`):
- Python `3.14` baseline (D019)
- `polars==2.0.0rc1`, `sqlalchemy==2.1rc1`, `httpx==1.0*`
- `binance-connector`, `binance-futures-connector` (archived 2026-04-30)
- `ccxt` for any order/data path in this phase

**Project layout** (RESEARCH.md `## Recommended Project Structure`, lines 173-192):
- `src/{adapters,data,db,ops,sql}` + `tests/{unit,fixtures}` + `scripts/` + `data/` (raw parquet gitignored or off-host; fixtures only inside tests/)

---

### 2-3. `Dockerfile` + `docker-compose.yml` *(new, Wave 0)* — toolchain / packaging

**Analog:** `docs/architecture/DATA_PIPELINE.md:144-160` §13 storage architecture (Postgres + Parquet-DuckDB diagram) + `docs/TECHNOLOGY_STACK.md` Docker row.

**`Dockerfile` shape** (RESEARCH.md `## Installation` block + `docs/operations/SECURITY_AND_OPERATIONS.md:112-117` §10):
```dockerfile
FROM python:3.13-slim-bookworm
# Install uv via the official installer; never pip install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev     # CI/dev layer
COPY src ./src
COPY scripts ./scripts
# Healthcheck; backup/collector entrypoints deferred to compose.
```

**`docker-compose.yml` shape** (RESEARCH.md `## Stack Patterns by Variant`):
```yaml
services:
  postgres:
    image: postgres:17-bookworm          # STACK: PostgreSQL 17-bookworm
    environment:
      POSTGRES_USER: ${POSTGRES_USER}    # .env, never committed (SECURITY §1)
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: trading
    volumes:
      - pgdata:/var/lib/postgresql/data  # named volume (D-12 off-host copy mandatory, but volume itself is host-local)
    ports: ["5432:5432"]
  app:
    build: .
    depends_on: [postgres]
    env_file: .env
    # Backup/collector services deferred; one app image, multiple entrypoints
volumes:
  pgdata:
```

**Toolchain-gate resolution order** (RESEARCH.md §Open Questions 1):
1. Plan 1 must install `uv` first (no fallback; BLOCKING)
2. `uv python install 3.13` (BLOCKING — system Python is 3.14.3 per RESEARCH.md §Environment Availability)
3. Stand up Postgres via Compose; if Docker Desktop install needs user action, `checkpoint:human-verify`

---

### 4. `alembic.ini` *(new, Wave 0)* — toolchain / migration-runner

**Analog:** `docs/configuration/CONFIGURATION.md:88-96` §6 storage model + `docs/data/DATA_MODEL.md:358-362` §5 integrity rules.

**Required keys** (single-file shape, no project-specific extension):
```ini
[alembic]
script_location = src/db/alembic
sqlalchemy.url = postgresql+psycopg://USER:PASS@HOST:5432/trading
# Override at runtime from env via env.py (RESEARCH.md §Code Examples async pattern)
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s
```

**`env.py` shape** (RESEARCH.md §Code Examples SQLAlchemy async):
```python
# Source: 02-RESEARCH.md:336-342 (Context7 /websites/sqlalchemy_en_20 VERIFIED)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.db.models import Base  # one Base for all models (file #8)

target_metadata = Base.metadata
# env.py must swap the synchronous URL for "postgresql+psycopg://" async URL
# and run migrations with `connection.run_sync(...)`. Plumb DATABASE_URL via env.
```

**Why `env.py` is in the migration runtime, not the models**: RESEARCH.md §Architecture Patterns line 246-247 — "`create_all` for schema: forbidden; Alembic baseline migration only."

---

### 5. `src/db/alembic/versions/0001_baseline.py` *(new)* — migration / baseline

**Analog:** `docs/data/DATA_MODEL.md` §2.11 `symbol_metadata` (lines 287-308) + D-04/05/08/09 table set (collector watermarks + collector gaps; coverage windows).

**Four tables, one migration** (D-08 watermarks + D-09 gap journal + DATA_MODEL §2.11 + DATA_PIPELINE §10 coverage-window):
- `symbol_metadata` — exact fields from DATA_MODEL.md:289-308. `metadata_observed_at_utc TIMESTAMPTZ NOT NULL` is the version key (Pattern 4: never UPDATE, always INSERT). Numeric filter columns use `NUMERIC` not `FLOAT` (Pitfall 4).
- `collector_watermarks(symbol, data_class, last_tick_utc, updated_at_utc)` — D-08.
- `collector_gaps(symbol, data_class, expected_utc, observed_utc, reason, recorded_at_utc)` — D-09.
- `coverage_windows(symbol, interval, historical_data_start_utc, historical_data_end_utc, onboard_time_utc)` — DATA_PIPELINE §10 list (line 113-118). PG-side authoritative; the DuckDB view joins over Parquet for the read path.

**Mandatory schema discipline** (DATA_MODEL §5 lines 355-362):
- All timestamps `TIMESTAMPTZ`; UTC enforced at the ORM boundary.
- Money/qty `NUMERIC`; `Numeric(38, 18)` for tick/step precision.
- Unique constraint on `(symbol, interval, open_time_utc)` would be the candle key — but candles live in Parquet (D-05), so PG does NOT carry OHLCV rows; only metadata/coverage windows.

---

### 6. `src/db/models.py` *(new)* — ORM / metadata

**Analog:** `docs/data/DATA_MODEL.md:287-308` §2.11 (canonical field list) + `02-RESEARCH.md:336-342` SQLAlchemy 2.0 async pattern.

**Engine bootstrap** (RESEARCH.md §Code Examples verbatim):
```python
# Source: 02-RESEARCH.md:336-342 — Context7 /websites/sqlalchemy_en_20 [VERIFIED]
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

def make_engine(database_url: str):
    return create_async_engine(database_url.replace("postgresql://", "postgresql+psycopg://"))

Session = async_sessionmaker(make_engine(...), expire_on_commit=False)
```

**`SymbolMetadata` mapping** (mirrors DATA_MODEL §2.11):
```python
# Source pattern: docs/data/DATA_MODEL.md:289-308
from sqlalchemy import String, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from decimal import Decimal

class SymbolMetadata(Base):
    __tablename__ = "symbol_metadata"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    metadata_observed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)  # version key
    status: Mapped[str] = mapped_column(String(16))
    contract_type: Mapped[str] = mapped_column(String(16))
    onboard_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    price_tick_size: Mapped[Decimal] = mapped_column(Numeric(38, 18))    # DATA_MODEL §5: no float
    quantity_step_size: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    min_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    max_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    notional_constraints_json: Mapped[str] = mapped_column(String)        # JSON-as-text for portability
    order_capabilities_json: Mapped[str] = mapped_column(String)
    # ... + position-mode snapshot, base/quote/margin assets
```

**Models for the other three tables** (collectors + coverage) follow the same `Mapped[...]` declarative style; column types mirror the migration (file #5).

**No-candle-in-PG rule** (D-05 one-way): `market_candles` is NOT modeled here — it lives in Parquet and is queried via DuckDB (`src/data/coverage.py`, file #15).

---

### 7. `src/adapters/binance_usdm.py` *(new)* — adapter / SDK-boundary

**Analog:** `02-RESEARCH.md:198-207` Pattern 1 (adapter boundary) + `docs/integration/BINANCE.md:17-21` §2 ("Wrap SDK clients behind project adapters. Do not let SDK-generated/Pydantic response models become domain entities") + `docs/architecture/DATA_PIPELINE.md:162-164` §14 ("SDK classes and raw JSON must not leak into the strategy layer").

**The adapter is the ONLY module that imports `binance_sdk_derivatives_trading_usds_futures`** (RESEARCH.md §Anti-Patterns line 243). Every other module imports `from src.adapters.binance_usdm import Kline, FundingTick, OiSnapshot, SymbolFilters`.

**Frozen dataclass shape** (RESEARCH.md Pattern 1, lines 198-207 verbatim):
```python
# Source: 02-RESEARCH.md:198-207 — Adapter boundary pattern (DATA_PIPELINE §14 + BINANCE §2)
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

@dataclass(frozen=True)
class Kline:
    symbol: str
    interval: str
    open_time_utc: datetime            # tz-aware UTC
    close_time_utc: datetime
    open: Decimal; high: Decimal; low: Decimal; close: Decimal
    volume: Decimal; quote_volume: Decimal
    trade_count: int

@dataclass(frozen=True)
class OiSnapshot:
    symbol: str
    observed_at_utc: datetime
    open_interest: Decimal

@dataclass(frozen=True)
class FundingTick:
    symbol: str
    funding_time_utc: datetime
    funding_rate: Decimal
    mark_price: Decimal | None = None

@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None
    min_notional: Decimal
    observed_at_utc: datetime
```

**SDK client injection** (D-03: re-verified at implementation):
```python
# Source: 02-RESEARCH.md A1 caveat — SDK method names re-verified against installed 17.x
# The exact names (`klines`, `open_interest`, `exchange_info`, `funding_rate`) MUST be
# confirmed against the installed SDK + docs at implementation start. The adapter
# is the layer that owns that confirmation; downstream modules never see SDK types.
class BinanceUsdmAdapter:
    def __init__(self, sdk_client):    # injected for respx mocking in adapter tests
        self._sdk = sdk_client

    async def klines(self, symbol, interval, start_ms, end_ms, limit=1500) -> list[Kline]: ...
    async def open_interest(self, symbol) -> OiSnapshot: ...
    async def funding_rate(self, symbol, start_ms=None, end_ms=None, limit=1000) -> list[FundingTick]: ...
    async def exchange_info(self) -> list[SymbolFilters]: ...
```

**Retry/backoff policy** (RESEARCH.md Pattern 3 + Don't Hand-Roll table):
- Use `tenacity` (RESEARCH.md §Don't-Hand-Roll line 252) with `stop_after_attempt(N)` + `wait_exponential_jitter()`; bound N then fail closed (D-09: gap journal, never infinite retry).

---

### 8. `src/data/quality.py` *(new)* — pure-function / Polars fail-closed gates

**Analog:** `02-RESEARCH.md:300-318` §Code Examples (Polars quality gate — verbatim) + `docs/architecture/DATA_PIPELINE.md:69-77` §6 quality rules + D-10 (fail-closed structural / warn-flag continuity).

**Verbatim pattern from RESEARCH.md §Code Examples** (lines 300-318, swap `interval_ms` per timeframe):
```python
# Source: 02-RESEARCH.md:300-318 — Backfill quality gate (Polars — pure, testable)
import polars as pl
from dataclasses import dataclass

INTERVAL_MS = {"1m": 60_000, "1h": 3_600_000, "4h": 14_400_000}

@dataclass(frozen=True)
class QualityVerdict:
    structural_ok: bool           # False ⇒ reject the batch (D-10)
    duplicates: int
    ohlc_violations: int
    timestamp_regressions: int
    gap_count: int                # warn-only; flagged in coverage

def check_batch(df: pl.DataFrame, interval: str) -> QualityVerdict:
    dupes = df.filter(pl.col("open_time_utc").is_duplicated()).height
    ohlc_bad = df.filter(
        (pl.col("high") < pl.col("open")) | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open")) | (pl.col("low") > pl.col("close"))
        | (pl.col("high") < pl.col("low"))
    ).height
    regress = (df["open_time_utc"].diff() <= 0).fill_null(False).sum()
    interval_ms = INTERVAL_MS[interval]
    expected = (df["open_time_utc"].max() - df["open_time_utc"].min()).total_seconds() * 1000 // interval_ms + 1
    gap_count = int(max(0, expected - df.height))
    structural_ok = (dupes == 0 and ohlc_bad == 0 and regress == 0)
    return QualityVerdict(structural_ok, dupes, ohlc_bad, int(regress), gap_count)
```

**D-10 mapping** (explicit, for the planner to wire into PLAN actions):
- Structural fail-closed: `duplicates > 0` OR `ohlc_violations > 0` OR `timestamp_regressions > 0` → reject batch, NO overwrite (DATA_PIPELINE §6 lines 70-77).
- Continuity warn-flag: `gap_count > 0` → publish batch but record in `coverage_windows` table + DuckDB view (DATA_PIPELINE §10 + D-09).

**Test surface** (file #21): pure-function inputs, no fixtures needed beyond a hand-built Polars frame.

---

### 9. `src/data/store.py` *(new)* — service / Parquet-publish

**Analog:** `02-RESEARCH.md:209-223` Pattern 2 + D-04 partition layout + `docs/architecture/DATA_PIPELINE.md:144-160` §13 storage architecture.

**Publish shape** (D-04 verbatim layout `data/raw/interval=1m/symbol=BTCUSDT/date=2026-09-19/part.parquet`):
```python
# Source: 02-RESEARCH.md:209-223 — Deterministic paginated backfill (publish half)
from pathlib import Path
import polars as pl
from datetime import date

RAW_ROOT = Path("data/raw")

def partition_path(interval: str, symbol: str, day: date) -> Path:
    return RAW_ROOT / f"interval={interval}" / f"symbol={symbol}" / f"date={day.isoformat()}"

def publish_batch(df: pl.DataFrame, interval: str, symbol: str) -> list[Path]:
    """Publish one or more per-day Parquet files; raw is immutable after publish.
    Returns the list of file paths written (caller appends to manifest)."""
    paths = []
    for day, group in df.group_by(pl.col("open_time_utc").dt.date()):
        path = partition_path(interval, symbol, day[0]) / "part.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Polars writes Hive-compatible Parquet; DuckDB reads it via hive_partitioning=true
        group.write_parquet(path)
        paths.append(path)
    return paths
```

**Immutability rule** (D-04 + RESEARCH.md §Anti-Patterns line 239): if a file already exists at the target path, raise — never overwrite. Repair flow publishes a new file and supersedes the manifest entry.

**Polars-vs-pyarrow choice** (RESEARCH.md §Don't-Hand-Roll line 249): "Polars `write_parquet` + Hive dirs" — keep Polars as the writer; no hand-rolled parquet.

---

### 10. `src/data/backfill.py` *(new)* — service / async-paginator

**Analog:** `02-RESEARCH.md:209-223` Pattern 2 (verbatim pseudocode) + Pitfall 1 (forming candle) + Pitfall 5 (weight-aware pacing).

**The pseudocode block from RESEARCH.md §Architecture Patterns (lines 213-223) is the canonical pattern — copy its shape verbatim, swap SDK method names once re-verified at implementation:**
```python
# Source: 02-RESEARCH.md:213-223 — Pseudocode, exact SDK call names re-verified at implementation [ASSUMED shape]
async def backfill_symbol_interval(adapter, symbol, interval, window_start, window_end, store, quality):
    cursor = window_start
    while cursor < window_end:
        page = await adapter.klines(symbol, interval, start_ms=cursor, limit=1500)   # weight 10
        await weight_aware_delay(adapter.last_weight_1m_header)                        # Pitfall 5
        batch = [k for k in page if k.close_time_utc <= utcnow()]                     # Pitfall 1: drop forming candle
        verdict = quality.check_batch(pl.from_dataclass(batch), interval=interval)
        if verdict.structural_ok:                                                      # D-10 fail-closed
            store.publish_batch(batch, interval=interval, symbol=symbol)
            manifest_record(cursor, len(batch))                                        # idempotent re-run (D-02 reversibility)
        cursor = max(k.open_time_utc for k in batch) + interval_ms(interval)
```

**Pacing helper** (Pitfall 5 mitigation):
```python
# Source: RESEARCH.md Pitfall 5 (lines 285-290) — read X-MBX-USED-WEIGHT-1M, sleep 150-250 ms, tenacity-retry 429
@tenacity.retry(stop=tenacity.stop_after_attempt(5),
                wait=tenacity.wait_exponential_jitter(initial=1, max=30),
                retry=tenacity.retry_if_exception_type(BinanceRateLimited))
async def klines_with_pacing(adapter, ...): ...
```

**Forming-candle guard** (Pitfall 1, lines 261-266): the `if k.close_time_utc <= utcnow()` filter is the ONLY lookahead-protection mechanism. Without it, every paginator is a repaint bug.

**Cursor resume** (D-02 reversibility): persist `last_cursor_utc` per `(symbol, interval)` in a small side-table so a re-run appends rather than restarts.

---

### 11. `src/data/collector.py` *(new)* — service / long-running async loop

**Analog:** `02-RESEARCH.md:225-226` Pattern 3 (verbatim) + `docs/architecture/DATA_PIPELINE.md:95-105` §9 OI collector + D-07/08/09.

**Pattern 3 verbatim** (RESEARCH.md lines 225-226):
> Single asyncio loop; every tick fetch OI for live-5 concurrently (bounded semaphore), insert snapshots + advance `collector_watermarks(symbol, last_tick_utc)` in the SAME PG transaction; on exception/missed tick insert a `collector_gaps(symbol, expected_utc, observed_utc, reason)` row and continue — never interpolate (D-09). Funding polled on its own slower cadence into separate files/table.

**Skeleton**:
```python
# Source: 02-RESEARCH.md:225-226 + docs/architecture/DATA_PIPELINE.md:95-105
import asyncio
from datetime import datetime, timezone, timedelta

OI_PERIOD = timedelta(minutes=5)                      # D-07
LIVE_5 = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")   # D-01
FUNDING_PERIOD = timedelta(days=1)                    # RESEARCH.md §Open Questions 3

async def oi_loop(adapter, session_factory, watermarks_repo, gaps_repo, stop_event):
    while not stop_event.is_set():
        tick_start = datetime.now(timezone.utc)
        try:
            snapshots = await asyncio.gather(*[adapter.open_interest(s) for s in LIVE_5])
        except Exception as exc:
            # D-09: gap journal, NEVER fabricated value
            async with session_factory() as s:
                await gaps_repo.insert(s, symbol=None, data_class="oi",
                                       expected_utc=tick_start, observed_utc=tick_start, reason=str(exc))
                await s.commit()
            await asyncio.sleep(OI_PERIOD.total_seconds())
            continue
        async with session_factory() as s:
            async with s.begin():
                for snap in snapshots:
                    await s.add(OiSnapshotRow(symbol=snap.symbol, observed_at_utc=snap.observed_at_utc,
                                              open_interest=snap.open_interest))
                    await watermarks_repo.advance(s, symbol=snap.symbol, data_class="oi",
                                                   last_tick_utc=snap.observed_at_utc)
        # Pace: drift next tick to the 5-minute boundary
        elapsed = (datetime.now(timezone.utc) - tick_start).total_seconds()
        await asyncio.sleep(max(0, OI_PERIOD.total_seconds() - elapsed))
```

**Funding-loop sibling** (D-08): separate cadence (daily sweep of `fundingRate` is the planner's per-delegation choice, RESEARCH.md §Open Questions 3); same watermark + gap journal pattern; persists to a Parquet partition `data/raw/interval=funding/symbol=…/date=…/part.parquet`.

**Watermark atomicity** (Pattern 3): snapshot insert + watermark advance MUST be in the same PG transaction; never two transactions with a crash window in between.

---

### 12. `src/data/metadata.py` *(new)* — service / versioned exchangeInfo upsert

**Analog:** `02-RESEARCH.md:228-230` Pattern 4 (verbatim) + `docs/data/DATA_MODEL.md:287-308` §2.11 + D-03 + Pitfall 4 (Decimal for filters).

**Pattern 4 verbatim** (RESEARCH.md lines 228-230):
> Each `exchangeInfo` fetch inserts a new `symbol_metadata` row (`metadata_observed_at_utc`, tick/step/min/max/notional JSON, position-mode snapshot) rather than UPDATE; readers pin `observed_at` ≤ dataset date. Fields per DATA_MODEL §2.11. Price/qty/notional parsed to `Decimal`, never float (ENGINEERING_PRINCIPLES Python rule).

**Skeleton**:
```python
# Source: 02-RESEARCH.md:228-230 + docs/data/DATA_MODEL.md:289-308
from decimal import Decimal, InvalidOperation

async def refresh_symbol_metadata(adapter, session_factory):
    info = await adapter.exchange_info()             # list[SymbolFilters] from adapter
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        async with s.begin():
            for f in info:
                row = SymbolMetadata(
                    symbol=f.symbol,
                    metadata_observed_at_utc=now,
                    price_tick_size=Decimal(str(f.price_tick_size)),       # Pitfall 4: NEVER float
                    quantity_step_size=Decimal(str(f.quantity_step_size)),
                    min_quantity=Decimal(str(f.min_quantity)),
                    max_quantity=Decimal(str(f.max_quantity)) if f.max_quantity else None,
                    min_notional=Decimal(str(f.min_notional)),
                    notional_constraints_json=json.dumps({...}),
                    order_capabilities_json=json.dumps({...}),
                    # ... + position-mode snapshot
                )
                await s.merge(row)                  # PK = (symbol, metadata_observed_at_utc)
```

**Refresh cadence** (DATA_PIPELINE §6 line 77 + RESEARCH.md Pattern 4): bootstrap + weekly; filter changes are rare but silent.

---

### 13. `src/data/coverage.py` *(new)* — service / CLI + DuckDB view loader

**Analog:** `02-RESEARCH.md:321-333` §Code Examples DuckDB coverage view + D-11 + `docs/architecture/DATA_PIPELINE.md:107-120` §10.

**CLI entry point** (D-11: `uv run ... coverage --symbol BTCUSDT`):
```python
# Source: 02-RESEARCH.md:321-333 — DuckDB hive-partitioned coverage view
import duckdb
from pathlib import Path
import click   # or typer; planner picks, AGENTS.md delegation area

CON = duckdb.connect()

def load_coverage_views(sql_path: Path = Path("src/sql/coverage_v1.sql")):
    CON.execute(sql_path.read_text())                # checked-in view definitions

def report_symbol(symbol: str, intervals=("1m", "1h", "4h")) -> dict:
    """Returns per-symbol {start_utc, end_utc, rows, violations, gaps} per interval."""
    rows = {}
    for tf in intervals:
        rows[tf] = CON.execute("""
            SELECT MIN(open_time_utc) AS start_utc,
                   MAX(close_time_utc) AS end_utc,
                   COUNT(*)           AS rows
            FROM candles_v1
            WHERE symbol = ? AND tf = ?
        """, [symbol, tf]).fetchone()
    return rows

@click.command()
@click.option("--symbol", required=True)
def main(symbol: str):
    load_coverage_views()
    print(report_symbol(symbol))
```

**Why a checked-in SQL file** (D-11 + Don't-Hand-Roll line 250): the DuckDB view name + definition is a stable contract shared by the CLI, QA checks, and Phase-6 backtest reports; one source of truth.

---

### 14. `src/sql/coverage_v1.sql` *(new, checked-in)* — sql-view / DuckDB

**Analog:** `02-RESEARCH.md:321-333` §Code Examples (verbatim DuckDB coverage view) + D-04 partition layout.

**Verbatim pattern** (RESEARCH.md lines 321-333 — copy the `candles_v1` definition verbatim, add `oi_v1` and `coverage_v1`):
```sql
-- Source: 02-RESEARCH.md:321-333 — DuckDB Hive-partitioned coverage view
CREATE OR REPLACE VIEW candles_v1 AS
SELECT *, interval AS tf
FROM read_parquet('data/raw/interval=*/symbol=*/date=*/part.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW oi_v1 AS
SELECT symbol, observed_at_utc AS open_time_utc, open_interest
FROM read_parquet('data/raw/interval=oi/symbol=*/date=*/part.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW coverage_v1 AS
SELECT  c.symbol,
        c.tf,
        MIN(c.open_time_utc) AS historical_data_start_utc,
        MAX(c.close_time_utc) AS historical_data_end_utc,
        COUNT(*)             AS rows
FROM candles_v1 c
GROUP BY c.symbol, c.tf;
```

**D-11 mapping** (explicit):
- CLI print: `coverage_v1` per symbol + joined with `coverage_windows` PG table for `onboard_time_utc` + `status_history`.
- Phase 6 backtest reports: same view, no duplicated coverage logic.

---

### 15. `src/ops/backup.py` *(new)* — service / CLI single-command drill

**Analog:** `02-RESEARCH.md:232-234` Pattern 5 (verbatim) + `docs/operations/SECURITY_AND_OPERATIONS.md:98-109` §9 + `docs/operations/RUNBOOK.md:128-141` §11.

**Pattern 5 verbatim** (RESEARCH.md lines 232-234):
> `backup.py` runs `pg_dump -Fc`, copies `data/raw/` OI+fencing snapshots (and candle Parquet manifest), pushes both off-host (second disk/remote — D-12 hard requirement), then restores into scratch PG database + temp dir and asserts row-count + hash equality; exits non-zero on any mismatch. Weekly schedule deferred to later hardening; Phase 2 needs the drill green on demand.

**Skeleton**:
```python
# Source: 02-RESEARCH.md:232-234 + RUNBOOK.md:128-141
import subprocess, shutil, hashlib, tempfile
from pathlib import Path

DATA_RAW = Path("data/raw")
PG_DUMP_FMT = "-Fc"                                          # RESEARCH.md §Alternatives Considered (custom format recommended)

@click.command()
@click.option("--mode", type=click.Choice(["backup", "drill"]), default="backup")
@click.option("--off-host-target", type=Path, required=False, default=Path("backup"))
def main(mode: str, off_host_target: Path):
    """`backup`: pg_dump + Parquet copy + off-host copy.
       `drill`: backup + scratch-restore + row-count/hash verify; exit non-zero on mismatch."""
    pg_dump_path = off_host_target / "pg.dump"
    subprocess.run(["pg_dump", PG_DUMP_FMT, "-f", str(pg_dump_path), DATABASE_URL], check=True)
    parquet_copy = off_host_target / "parquet"
    shutil.copytree(DATA_RAW, parquet_copy, dirs_exist_ok=True)
    if mode == "drill":
        with tempfile.TemporaryDirectory() as scratch:
            # Restore into scratch PG + temp dir, assert row counts + sha256 of every Parquet file match
            assert_restore_matches(pg_dump_path, parquet_copy, scratch)
    print(f"backup OK → {off_host_target}")
```

**Hash-equality verification** (DATA_MODEL §5 line 361 "Unique constraints must protect deterministic IDs and exchange event replay"): compute `sha256(file)` for every Parquet file pre- and post-restore; equality is the drill's success criterion.

**Off-host requirement** (D-12): OneDrive-synced backup dir is the documented Phase-2 fallback (RESEARCH.md §Open Questions 2); user confirmation belongs in plan 1's `checkpoint:human-verify` step.

---

### 16. `scripts/backup-drill.ps1` *(new, Wave 0 wrapper)* — script / ops

**Analog:** `docs/operations/RUNBOOK.md:128-141` §11 procedure + `02-VALIDATION.md:46` row `02-04-01` (already names this file).

**Shape** (PowerShell wrapper that defers all logic to `src/ops/backup.py`):
```powershell
# Source: 02-VALIDATION.md row 02-04-01 + RUNBOOK.md:128-141
$ErrorActionPreference = "Stop"
uv run python -m src.ops.backup drill --off-host-target "$PSScriptRoot\..\backup"
```

---

### 17. `tests/conftest.py` *(new, Wave 0)* — test-fixture / shared

**Analog:** `docs/testing/TESTING_STRATEGY.md:13-22` §2 golden-fixture model + `02-RESEARCH.md:107` ("Adapter tests use recorded exchangeInfo/kline fixtures").

**Required fixtures**:
- `golden_exchange_info` — load `tests/fixtures/exchange_info_sample.json` once per session; never hit Binance in unit tests (TESTING_STRATEGY.md:165-166 "live Binance credential must never be required").
- `golden_kline_page` — small recorded page (≤200 rows) used by paginator + forming-candle tests (Pitfall 1).
- `frozen_clock` — returns `datetime(2026, 9, 19, tzinfo=timezone.utc)`; injected into the collector so gap-never-fabricate tests don't depend on wall-clock.
- `in_memory_pg_session` — SQLAlchemy async engine on SQLite (only for tests, never for production) OR a tmpdir Postgres spun up via testcontainers/pytest-postgresql; planner's discretion per delegation.

---

### 18. `tests/fixtures/exchange_info_sample.json` *(new, recorded)* — test-fixture / golden

**Analog:** `docs/integration/BINANCE.md:9-13` (verified endpoint shapes) + `02-RESEARCH.md:78` (endpoint table).

**Recorded fixture shape** (one symbol's slice, hand-trimmed from a real response for the live-5):
```json
{
  "symbols": [{
    "symbol": "BTCUSDT",
    "status": "TRADING",
    "contractType": "PERPETUAL",
    "onboardDate": 1577836800000,
    "filters": [
      {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
      {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
      {"filterType": "MIN_NOTIONAL", "notional": "5"}
    ]
  }]
}
```

**Why recorded, not synthesized** (TESTING_STRATEGY §12 line 165): "Strategy and domain tests should remain runnable without a Binance account, network access, or a database." Recorded fixtures preserve real schema drift; synthesized ones hide it.

---

### 19. `tests/test_quality_gates.py` *(new, Wave 0)* — test / fail-closed + warn-flag

**Analog:** `02-RESEARCH.md:300-318` quality-gate Polars pattern + D-10 + `docs/testing/TESTING_STRATEGY.md:38-117` (no-lookahead + state-machine tests).

**Test cases** (every D-10 branch):
1. **Dupes** — frame with two identical `open_time_utc` rows → `structural_ok == False`, `duplicates == 2`.
2. **OHLC violation** — `high < open` → `structural_ok == False`, `ohlc_violations == 1`.
3. **Timestamp regression** — row order shuffled → `structural_ok == False`, `timestamp_regressions >= 1`.
4. **Gap (continuity only)** — missing middle row → `structural_ok == True` (warn-only), `gap_count == 1`.
5. **Clean batch** — fully dense, ordered → all zeros, `structural_ok == True`.

**Why these five** (D-10 + DATA_PIPELINE §6): one test per failure-mode the doc calls out by name.

---

### 20. `tests/test_collector.py` *(new, Wave 0)* — test / gap-never-fabricate

**Analog:** `02-RESEARCH.md:225-226` Pattern 3 + D-09 + `docs/testing/TESTING_STRATEGY.md:107-117` §8 state-machine tests.

**Test cases**:
1. **Happy tick** — adapter returns 5 snapshots → 5 rows in `oi_snapshot` table + 5 watermark advances in a single transaction.
2. **Adapter exception** — adapter raises → gap row in `collector_gaps`, NO `oi_snapshot` row written, NO watermark advance.
3. **Missed scheduled tick** — `frozen_clock` + simulated skip → gap row with `expected_utc` set to the skipped boundary, `observed_utc` to actual run time.
4. **Watermark atomicity** — kill the process mid-transaction (mock a SQLAlchemy commit failure) → on restart, next tick re-fetches from the last committed watermark (idempotent re-run).
5. **Funding cadence** — funding-loop sibling test: assert separate watermarks/gaps repo and separate Parquet partition path.

---

## Shared Patterns

### Authority chain (cross-cutting, applies to every Phase-2 file)

Per D006 (`docs/01_ENGINEERING_PRINCIPLES.md` + `docs/GLOSSARY.md` + `docs/data/DATA_MODEL.md` are canonical, RESEARCH.md re-verifies):

```text
docs/DECISIONS.md                                  (decision log)
    > docs/GLOSSARY.md                             (canonical enums)
    > docs/data/DATA_MODEL.md                      (canonical entities)
    > docs/architecture/DATA_PIPELINE.md           (canonical ingestion contract)
    > docs/integration/BINANCE.md                  (canonical Binance contract)
    > docs/configuration/CONFIGURATION.md          (parameter registry)
    > docs/operations/SECURITY_AND_OPERATIONS.md   (backup + safety)
    > docs/operations/RUNBOOK.md                   (incident response)
    > docs/research/RESEARCH_PROTOCOL.md           (frozen research contract)
    > docs/TECHNOLOGY_STACK.md                     (canonical stack pins)
```

**Apply to:** every file. Code cannot invent fields, enums, or partition layouts; it conforms to the doc that owns the slice. The doc-as-analog model means the planner cites the doc by section title, not by invented structure.

### Adapter boundary (cross-cutting, applies to all Binance-touching code)

```text
src/adapters/binance_usdm.py   ── ONLY ──> binance-sdk-derivatives-trading-usds-futures
        │                                       │
        └── frozen dataclasses (Kline, OiSnapshot, FundingTick, SymbolFilters)
                    │
                    ▼
        every other src/ module
```

**Source:** `02-RESEARCH.md:198-207` Pattern 1 + `docs/integration/BINANCE.md:17-21` §2 + `docs/architecture/DATA_PIPELINE.md:162-164` §14.

**Apply to:** file #9 (the adapter itself) + every file that would otherwise import the SDK. Pytest's `respx` mocks the SDK-underlying httpx at the adapter boundary (RESEARCH.md §Code Examples §Validation Architecture).

### Fail-closed posture (cross-cutting, applies to quality gate + collector + backup)

Per `docs/01_ENGINEERING_PRINCIPLES.md:85-89` §9 + `docs/architecture/DATA_PIPELINE.md:69-77` §6 + D-09/D-10:

```text
uncertain data        → reject batch, NO overwrite (file #8 quality.py)
uncertain connection  → gap journal, NEVER fabricated value (file #11 collector.py)
uncertain backup      → drill exits non-zero, halts automation (file #15 backup.py)
```

**Apply to:** all three files; verifier test (file #19, #20) covers the fail-closed path explicitly.

### UTC-internally / HCMC-display-edge (cross-cutting, applies to every timestamp)

Per `docs/01_ENGINEERING_PRINCIPLES.md:81` §8 + `docs/architecture/DATA_PIPELINE.md:79-83` §7 + D-06:

```python
# Source: 02-RESEARCH.md:344-350 §Code Examples — UTC store, HCMC display edge
from datetime import datetime, timezone
from zoneinfo import ZoneInfo       # needs `tzdata` wheel on Windows
now_utc = datetime.now(timezone.utc)
display = now_utc.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))    # only at the CLI/UI edge
```

**Apply to:** every model field of type `datetime` (use `TIMESTAMPTZ` not `TIMESTAMP`), every CLI output, every log line.

### Decimal-only for exchange-sensitive values (cross-cutting)

Per `docs/01_ENGINEERING_PRINCIPLES.md:100` (Python engineering principles) + `02-RESEARCH.md:281-283` Pitfall 4:

```text
✓ Decimal / integer tick-step arithmetic for prices, quantities, notional, filters
✗ float()  for any persisted financial value
```

**Apply to:** file #9 adapter (all filter fields); file #6 ORM (`NUMERIC(38, 18)` not `FLOAT8`); file #14 SQL view (no implicit float casts); every CLI print formatter (use `Decimal` formatting helpers, not `f"{x}"` on a float).

### Tenacity-bounded retry (cross-cutting, applies to all REST/WS paths)

Per `02-RESEARCH.md` §Don't Hand-Roll line 252 ("tenacity (bounded, jittered)") + `docs/operations/SECURITY_AND_OPERATIONS.md:23-32` §3 Reconnect:

```python
import tenacity

# Bound attempts; on exhaustion, gap journal or batch reject — never infinite retry
@tenacity.retry(
    stop=tenacity.stop_after_attempt(5),
    wait=tenacity.wait_exponential_jitter(initial=1, max=30),
    retry=tenacity.retry_if_exception_type(BinanceRateLimited | httpx.TransportError),
    reraise=True,
)
async def fetch(...): ...
```

**Apply to:** file #10 backfill (429 pacing), file #11 collector (OI/funding ticks), file #12 metadata refresh.

### Structured logging (cross-cutting, applies to every long-running module)

Per `docs/operations/SECURITY_AND_OPERATIONS.md:61-74` §6 Logging + `02-RESEARCH.md` §Standard Stack §Supporting (structlog >= 25):

```python
import structlog
log = structlog.get_logger()
log.info("oi.tick", symbol=s, observed_at_utc=o.isoformat(),
         correlation_id=cid, strategy_version=None)   # Phase 2 has no strategy yet
```

**Never log:** API keys, signatures, raw request bodies with `X-MBX-APIKEY`. `SECURITY_AND_OPERATIONS.md:74` hard rule.

### Verification grep suite (cross-cutting, applies to the entire phase gate)

Per `02-RESEARCH.md` §Validation Architecture + `02-VALIDATION.md` sampling rate:

```bash
# DATA-01: quality gates wired into publish path
grep -rn "quality.check_batch\|QualityVerdict" src/

# DATA-02: OI collector loop + watermark/gap journal present
grep -rn "watermark\|gap_journal\|collector_watermarks\|collector_gaps" src/

# DATA-03: metadata parsed as Decimal
grep -rn "Decimal(str(" src/adapters/

# DATA-04: backup + drill + hash verification present
grep -rn "pg_dump\|sha256\|assert_restore_matches" src/ops/

# Cross-cutting: SDK isolation (the ONLY importer)
grep -rln "from binance_sdk_derivatives_trading_usds_futures" src/   # MUST be exactly one line

# Cross-cutting: float ban on exchange-sensitive values
grep -rn "float(" src/adapters/ src/db/ src/data/store.py

# Cross-cutting: UTC discipline
grep -rn "tzdata\|ZoneInfo\|timezone.utc" src/
```

**Apply to:** every plan in the phase. Run at phase gate (`/gsd-verify-work`); failures block merge per RESEARCH.md §Validation Architecture.

---

## No Analog Found

| File | Module Role | Module Data Flow | Reason |
|------|-------------|------------------|--------|
| `Dockerfile` | toolchain (packaging) | image build | Greenfield — no existing image in repo. Format reference: `docs/TECHNOLOGY_STACK.md` Docker row + `docs/operations/SECURITY_AND_OPERATIONS.md:112-117` §10. Build-from-locked-deps rule is the analog, not a project Dockerfile to copy. |
| `docker-compose.yml` | toolchain (local stack) | service orchestration | Greenfield — no existing compose file in repo. Format reference: `docs/architecture/DATA_PIPELINE.md:158-160` §13 storage diagram + `docs/TECHNOLOGY_STACK.md` Docker row. The D-12 off-host-backup rule + OneDrive fallback (RESEARCH.md §Open Questions 2) is the analog, not a project compose file. |

All other 20 files have a clear doc-or-research pattern analog — either a docs section that owns the entity/schema/rule, or a RESEARCH.md §Architecture Patterns / §Code Examples block that ships the verbatim Python shape.

---

## Metadata

**Analog search scope:** `docs/**/*.md` (27 files in Core Docs v0.3) + `.planning/**/*.md` (planning context) + `.github/workflows/research-gate.yml` (Phase-1 CI precedent) + the Phase-2 RESEARCH.md §Architecture Patterns (lines 175-256) and §Code Examples (lines 297-351).

**Files scanned:** 27 docs + 2 planning inputs (CONTEXT.md, RESEARCH.md) + 1 Phase-1 CI YAML.

**Tracked-source verification:** All cited doc analogs (`docs/architecture/DATA_PIPELINE.md`, `docs/data/DATA_MODEL.md`, `docs/integration/BINANCE.md`, `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/configuration/CONFIGURATION.md`, `docs/operations/SECURITY_AND_OPERATIONS.md`, `docs/operations/RUNBOOK.md`, `docs/testing/TESTING_STRATEGY.md`, `docs/TECHNOLOGY_STACK.md`, `docs/research/RESEARCH_PROTOCOL.md`, `docs/DECISIONS.md`, `docs/GLOSSARY.md`, `docs/architecture/ARCHITECTURE.md`, `docs/implementation/IMPLEMENTATION_PLAN.md`) are git-tracked under `git ls-files -- docs/` (31 entries). The `.github/workflows/research-gate.yml` analog is git-tracked. The 20 new files Phase 2 will create do not exist yet — they will be created by Phase-2 plans.

**Pattern extraction date:** 2026-09-19

## PATTERN MAPPING COMPLETE

**Phase:** 02 — Data Foundation
**Files classified:** 22 (16 new code/toolchain + 4 test fixtures + 2 CI/build configs)
**Analogs found:** 20 with format/structure analogs / 22 (2 greenfield infrastructure files — Dockerfile, docker-compose.yml — reference doc policy, not project prior art)

### Coverage
- Files with exact format/structure analog: 20
- Files with no in-repo analog (greenfield infra): 2

### Key Patterns Identified
- **Doc-as-analog** is the operative pattern: every code module Phase 2 ships has a doc owner (`DATA_PIPELINE §6/§9/§10/§13/§14`, `DATA_MODEL §2.1/§2.11`, `BINANCE §2/§8`, `CONFIGURATION §6`, `SECURITY §9`, `RUNBOOK §11`). The doc IS the analog; the planner extracts the exact code excerpt + line range, never invents structure.
- **Adapter boundary** is non-negotiable: file #9 is the ONLY module that imports `binance-sdk-derivatives-trading-usds-futures`; every other module imports frozen dataclasses from the adapter.
- **Polars quality gate** ships verbatim from RESEARCH.md §Code Examples (lines 300-318); fail-closed on structural (D-10), warn-flag on continuity; gap_count ≠ fabrication (D-09).
- **OI/funding collector** runs as a single asyncio loop with watermark + gap journal in the SAME PG transaction (RESEARCH.md Pattern 3); never infinite retry on failure.
- **DuckDB view files are checked in** (`src/sql/coverage_v1.sql`) — one source of truth shared by CLI, QA, Phase-6 backtest reports.
- **Backup drill is one command** (`pg_dump -Fc` + Parquet copy + off-host + scratch-restore + sha256 verify; exits non-zero on mismatch); D-12 off-host requirement is non-negotiable.
- **Decimal-only** for all exchange-sensitive values; `NUMERIC(38, 18)` in PG, `Decimal` in Python, no `float()` in adapters/models/store.
- **UTC-internally / HCMC-display-edge** via `zoneinfo("Asia/Ho_Chi_Minh")` only at CLI/UI outputs; `TIMESTAMPTZ` in PG; Windows needs the `tzdata` wheel.

### File Created
`C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/02-data-foundation/02-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference doc-derived analogs and verbatim RESEARCH.md code excerpts in PLAN.md files. The 22 files should be split across 4-6 fine-grained plans (toolchain/Wave-0 → adapter + ORM + Alembic baseline → quality + store + backfill → collector + metadata → coverage CLI + DuckDB views + backup drill), with the SDK-method-name re-verification checkpoint explicit in plan 1 (RESEARCH.md §A1 caveat) and the off-host backup target confirmed via `checkpoint:human-verify` per D-12 + RESEARCH.md §Open Questions 2. Phase-2 gate fires only after the verification grep suite passes against the new src/ tree.
