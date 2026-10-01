# Phase 2: Data Foundation - Research

**Researched:** 2026-09-19
**Domain:** Binance USDⓈ-M market-data ingestion → Parquet (immutable raw) + PostgreSQL 17 (metadata/watermarks) + DuckDB (analytics), quality gates, OI/funding collectors, backup drill
**Confidence:** HIGH (endpoints + versions verified against live registry/docs today; MEDIUM on SDK method names — re-verify at implementation per project policy)

## Summary

Phase 2 builds the irrecoverable-data safety net: per-symbol bootstrap of 1m/1H/4H candles with fail-closed quality gates and queryable coverage, a day-one OI snapshot collector (5-min poll of `GET /fapi/v1/openInterest`) plus funding-rate backfill + ongoing collection, versioned symbol metadata from live `exchangeInfo`, and an automated backup + restore drill covering PostgreSQL state and the self-collected OI Parquet dataset. Greenfield — no `src/`, no `pyproject.toml`, no DB exists yet.

All five Binance endpoints needed were re-verified against current official docs this session: `GET /fapi/v1/klines` (weight 1/2/5/10 by limit, max 1500/req), `GET /fapi/v1/exchangeInfo` (weight 1), `GET /fapi/v1/openInterest` (weight 1), `GET /futures/data/openInterestHist` (weight 0, 1000 req/5min IP cap, **latest-1-month only**), `GET /fapi/v1/fundingRate` (shares 500/5min/IP with fundingInfo, max 1000 records/req). The 30-day OI window confirms D-08's premise: the self-collected snapshots are the only forward source, and the opportunistic `openInterestHist` harvest at bootstrap must happen before the window slides.

The official SDK `binance-sdk-derivatives-trading-usds-futures` is at **17.4.0** on PyPI today (STACK.md pinned 17.3.1 from 2026-09-10 — a newer minor exists; pin `>=17.3,<18` and let `uv lock` resolve). DuckDB 1.5.5 confirmed current, Polars at 1.44.2 (patch bump over STACK's 1.44.1), SQLAlchemy 2.0.54, psycopg 3.3.6, Alembic 1.20.0 (over STACK's 1.19.1), pyarrow 25.0.1, pytest 9.1.1, pydantic 2.13.5, tenacity 9.1.4, structlog 26.1.0, tzdata 2026.4, respx 0.23.1, pytest-asyncio 1.4.0 — all verified via `pip index versions` this session.

**Primary recommendation:** Bootstrap behind a project-owned adapter over the official SDK (never import SDK models into domain code); store candles/funding/OI as Hive-partitioned Parquet (`interval= → symbol= → date=`), queryable via DuckDB `read_parquet(..., hive_partitioning=true)` + a checked-in SQL view file; own operational state in PostgreSQL 17 via SQLAlchemy 2.0 async + Alembic baseline migration; run the OI/funding collector as an `asyncio` task inside a Compose-managed long-running process with tenacity-bounded retries and watermark + gap-journal persistence; fail closed on structural corruption, warn-and-flag on continuity gaps; ship backup as one command (`pg_dump` + Parquet copy + off-host copy + scratch-restore verify).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** First bootstrap covers the V1 live-5 only (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT) with all three intervals (1m + 1H + 4H) together. The 10–15-symbol research slice is explicitly deferred to a later expansion run, not part of the first green bootstrap.
- **D-02:** History depth is bounded for the first run, not "everything Binance has": 1H/4H ~2 years back, 1m ~6–12 months back, extendable on demand. Rationale: 1m full-history for 5 symbols is heavy for a part-time dev machine; bounded depth unblocks quality/coverage/OI work fast while the expansion path stays open. — **Reversibility:** reversible — re-running backfill with a deeper window appends data, no contract break.
- **D-03:** Backfill source is Binance USDⓈ-M klines via the official SDK (`binance-sdk-derivatives-trading-usds-futures`) behind a project-owned adapter, re-verified against current docs at implementation time. No TradingView or third-party vendor as bootstrap source (TradingView stays optional cross-check only).
- **D-04:** Parquet is the immutable raw store, partitioned by interval → symbol → date (e.g. `data/raw/interval=1m/symbol=BTCUSDT/date=2026-09-19/part.parquet`), raw files never mutated after publish; derived/resampled datasets are versioned separately. — **Reversibility:** costly — partition layout is read by every downstream consumer (backtest, paper, DuckDB views); changing it later touches all readers.
- **D-05:** Role split: Parquet + DuckDB own analytical/research data (candles, funding, OI snapshots, coverage queries); PostgreSQL 17 owns operational state + metadata (symbol metadata versions, onboard time, coverage windows, collector watermarks). No candle OHLCV rows as primary store in PostgreSQL. — **Reversibility:** one-way — moving the analytical/transactional boundary later needs a data migration plus consumer rewiring.
- **D-06:** All storage timestamps UTC internally; presentation in Asia/Ho_Chi_Minh only at the display edge (per DATA_PIPELINE §7, resolving the Bangkok-vs-HCMC naming toward HCMC).
- **D-07:** OI collector starts day one of this phase for the live-5, polling current OI (`/fapi/v1/openInterest`) every 5 minutes via the official SDK behind an adapter, persisting timestamp + symbol + OI + collector version. 5-minute cadence balances research need against rate limits for a part-time operator; NOT arbitrary sub-minute polling. — **Reversibility:** reversible — cadence is a config value, tightening/loosening it later does not break stored snapshots.
- **D-08:** Funding-rate history is backfilled once plus collected ongoing alongside OI (same scheduler family, separate tables/files per data class). Historical OI statistics endpoint (`/futures/data/openInterestHist`, ~30-day window) is harvested opportunistically at bootstrap but never relied upon — the self-collected snapshots are the canonical forward source.
- **D-09:** Gap policy is flag-never-fabricate: missed polls produce explicit gaps in the snapshot series (watermark + gap journal), never interpolated/synthesized OI values. Downstream (Phase 6/7) must treat gaps as missing, not zero.
- **D-10:** Quality gates fail closed on structural corruption (duplicate candle timestamps, impossible OHLC relationships, timestamp regressions, symbol-metadata mismatch → batch rejected, no silent overwrite) and warn + flag on continuity issues (missing sequence/gaps, stale feed → flagged in coverage, pipeline continues). Follows DATA_PIPELINE §6 exactly.
- **D-11:** "Queryable coverage" means both: (a) a CLI command (e.g. `uv run ... coverage --symbol BTCUSDT`) printing effective per-symbol range plus violation/gap counts, and (b) a DuckDB SQL view over Parquet + metadata reporting `historical_data_start_utc / historical_data_end_utc / onboard_time_utc / status_history` per symbol (per DATA_PIPELINE §10). Backtest reports later state effective range per symbol — no direct BTC-vs-short-alt comparison without showing the difference.
- **D-12:** Backup + restore drill covers PostgreSQL state (pg_dump of metadata/coverage/watermarks) AND the self-collected OI dataset (Parquet snapshot copy), restores into a scratch target and verifies row-count/hash equality. Drill is automated (single command) and rehearsed in this phase; off-host copy is required (backup must not live only on the primary host). Schedule default: weekly automated backup + drill on demand in Phase 2, hardened later.

### the agent's Discretion
- User explicitly delegated all four areas ("bạn hãy lựa chọn cái tốt nhất cho tôi") and confirmed the recommended-defaults bundle in one gate. Exact CLI names, Parquet filename conventions, DuckDB view names, scheduler implementation (asyncio task vs cron vs Compose job), and drill script layout are at the planner/researcher discretion, provided D-01–D-12 semantics hold.
- Plan slicing within the phase (fine granularity) is at the planner's discretion.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. Research-universe expansion (10–15 symbols), 15m interval support, and OI/funding as strategy features (REFN-02/REFN-03) remain scheduled in their own phases/requirements.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Bootstrap 1m/1H/4H candles per symbol with continuity/quality checks (duplicates, OHLC validity, regressions, gaps) and query effective per-symbol coverage | Binance klines pagination + weights (§Binance Endpoints); Polars quality-check patterns (§Code Examples); Hive Parquet + DuckDB coverage view + CLI (§Architecture Patterns) |
| DATA-02 | Collect OI snapshots continuously from Phase 0 plus funding history, so the 30-day API window never destroys research data | OI/funding endpoint table (§Binance Endpoints); asyncio collector + watermark/gap-journal pattern (§Architecture Patterns); opportunistic openInterestHist harvest note (§Common Pitfalls P3) |
| DATA-03 | Record versioned symbol metadata (onboard time, tick/step, min/max qty, notional constraints, position modes) from live exchangeInfo instead of hard-coded values | exchangeInfo weight/filters (§Binance Endpoints); symbol_metadata table per DATA_MODEL §2.11 + Alembic baseline (§Architecture Patterns); Decimal rule (§Don't Hand-Roll) |
| DATA-04 | Pass an automated backup + restore drill covering PostgreSQL state and the self-collected OI dataset | pg_dump + Parquet-copy + scratch-restore pattern (§Architecture Patterns P5); off-host requirement from D-12; row-count/hash verification |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- **Determinism:** same snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs. Phase 2 implication: backfill pagination must be deterministic (fixed window cursors, dedupe by `(symbol, timeframe, open_time_utc)`), raw files content-addressed/immutable after publish.
- **No-AI core:** LLM never decides direction/entry/SL/TP/size/risk/parameters/signal-validity. No impact on Phase 2 (pure plumbing), but quality-gate thresholds must come from DATA_PIPELINE, not invented.
- **Exchange authority:** Binance canonical; dynamic exchangeInfo, re-verified against current official docs before implementation, never hard-coded from memory. Satisfied: endpoints re-verified this session (see table below); planner must add a re-verify checkpoint at implementation start since docs drift.
- **Quantization / Approval safety / Fail closed:** fail-closed posture applies directly to ingestion (D-10: reject corrupt batches, flag gaps, never fabricate).
- **Tech stack lock:** Python 3.13, asyncio, official Binance SDK behind adapters, FastAPI edge-only (not needed in Phase 2), PostgreSQL + Parquet/DuckDB, Polars primary, pytest+Ruff+mypy, Docker, Decimal/tick arithmetic for exchange-sensitive values.
- **GSD workflow enforcement:** implementation must run through GSD commands, not ad-hoc edits.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Kline backfill pagination (REST) | API / Backend (collector process) | — | Network I/O + retry + watermarking; no browser/SSR involved |
| Parquet raw store + DuckDB analytics | Database / Storage (files + in-process OLAP) | — | Larger-than-memory scans, zero-server; PG must NOT own OHLCV rows (D-05) |
| Symbol metadata / watermarks / coverage windows | Database / Storage (PostgreSQL 17) | — | Transactional, versioned operational state with Alembic migrations |
| OI/funding periodic collection | API / Backend (long-running asyncio process) | — | Timer-driven REST polling with fail-closed gap journaling |
| Coverage CLI + DuckDB views | API / Backend (CLI entrypoint) | — | Display-edge only for Asia/Ho_Chi_Minh formatting (D-06) |
| Backup + restore drill | Database / Storage + API / Backend (script) | — | pg_dump + file copy orchestrated by a single command |

## Binance Endpoints (re-verified 2026-09-19)

| Endpoint | Purpose (Phase 2) | Weight / Limit | Key parameters | Provenance |
|----------|-------------------|----------------|----------------|------------|
| `GET /fapi/v1/klines` | Candle backfill (1m/1H/4H) | Weight by limit: [1,100)→1, [100,500)→2, [500,1000]→5, >1000→10; max 1500/req; IP limit 2400/min | `symbol`, `interval`, `startTime`, `endTime`, `limit` (default 500); klines uniquely identified by open time | [VERIFIED: developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data — fetched via WebSearch excerpt 2026-09-19] |
| `GET /fapi/v1/exchangeInfo` | Versioned symbol metadata (DATA-03) | Weight 1 | No required params; response `symbols[]` carries PRICE_FILTER/LOT_SIZE/MIN_NOTIONAL filters, `rateLimits[]` carries current limits | [VERIFIED: developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information — fetched via WebSearch excerpt 2026-09-19] |
| `GET /fapi/v1/openInterest` | OI 5-min poll (DATA-02) | Weight 1 | `symbol` required; response `{openInterest, symbol, time}` | [VERIFIED: developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest (+ legacy page) — fetched via WebSearch excerpt 2026-09-19] |
| `GET /futures/data/openInterestHist` | Opportunistic bootstrap harvest ONLY (D-08) | Weight 0; separate cap **1000 req/5min IP** | `symbol`, `period` (5m…1d), `limit` default 30 max 500; **only latest 1 month available** | [VERIFIED: developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics — fetched via WebSearch excerpt 2026-09-19] |
| `GET /fapi/v1/fundingRate` | Funding backfill + ongoing (DATA-02) | **Shares 500/5min/IP with `fundingInfo`** | `symbol` optional, `startTime`/`endTime` inclusive, `limit` default 100 max 1000 (default-recents 200); ascending order | [VERIFIED: developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History — fetched via WebSearch excerpt 2026-09-19] |

**Backfill volume math (bounded depth, D-02):** per symbol — 1m × 12 mo ≈ 525,600 candles; 1m × 6 mo ≈ 262,800; 1H × 2y ≈ 17,520; 4H × 2y ≈ 4,380. Live-5 totals (12-mo 1m case): ≈ 2.63M 1m + 87.6k 1H + 21.9k 4H ≈ **2.74M candles**. At limit=1500 (weight 10): ≈ 350 req/symbol for 1m + ~12 for 1H + ~3 for 4H → **~1,825 requests total**, ≈ 18k weight. Against 2400 weight/min this is ~8–15 min of paced fetching per full bootstrap — trivially safe with a small sleep between pages [ASSUMED arithmetic on VERIFIED limits — planner: make paginator sleep ~100–200 ms and read `X-MBX-USED-WEIGHT-1M` headers]. Funding: 8h settlement → ~3 records/day/symbol → 2y ≈ 2,190 records/symbol, **3 requests/symbol** at limit=1000 [ASSUMED: 8h settlement cadence is long-standing Binance behavior, re-verify one sample response at implementation]. OI poll load: 5 symbols × 12 polls/h = 60 req/h at weight 1 — negligible [VERIFIED weights → ASSUMED conclusion].

**SDK method-name caveat:** exact Python method names on the v17 SDK client (e.g. `klines` / `open_interest` / `exchange_info`) were **not** opened in SDK source this session — the planner must add a "confirm SDK method names + response field names against installed 17.x package + current docs" task at implementation start. This is consistent with the project's standing re-verification policy (BINANCE.md §1, D-03). [ASSUMED]

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | `>=17.3,<18` (17.4.0 current on PyPI, verified today) | REST klines / exchangeInfo / openInterest / fundingRate behind project adapter | Official SDK; only non-archived Python path (legacy connectors archived 2026-04-30); covers all five Phase-2 endpoints | 
| `pyarrow` | `>=19` (25.0.1 current, verified today) | Parquet read/write engine under Polars + DuckDB | Required companion; `uv lock` arbitrates the Polars↔DuckDB floor |
| `duckdb` | `==1.5.5` (confirmed current today) | SQL over Hive-partitioned Parquet; checked-in coverage views | `read_parquet` with `hive_partitioning=true` auto-exposes `interval/symbol/date` as columns [VERIFIED: Context7 /duckdb/duckdb-python]; zero-server, larger-than-memory |
| `polars` | `>=1.44,<2.0` (1.44.2 current, verified today) | Backfill framing, quality checks (dupes/OHLC/gaps), Parquet writes | Primary frame engine per STACK; lazy + multithreaded for 2.7M-row scale |
| `sqlalchemy` | `>=2.0,<2.1` (2.0.54 current, verified today) | Async ORM for PG metadata/watermarks | `create_async_engine("postgresql+psycopg://…")` + `async_sessionmaker` is the documented current API [VERIFIED: Context7 /websites/sqlalchemy_en_20] |
| `psycopg[binary,pool]` | `>=3.3,<4` (3.3.6 current, verified today) | PG driver sync+async | Official SQLAlchemy-async path; `binary` avoids libpq build pain on Windows; `psycopg_pool.AsyncConnectionPool` + `NullPool` pattern [VERIFIED: Context7 /websites/sqlalchemy_en_20] |
| `alembic` | `>=1.19` (1.20.0 current, verified today) | Baseline migration for Phase-2 tables | Every DATA_MODEL change ships as reviewed migration; never `create_all` in prod paths |
| `pydantic` + `pydantic-settings` | `>=2.11,<3` (2.13.5 current, verified today) | Exchange-payload boundary validation; collector config (poll cadence, symbols, depth windows) | V2 Rust-core standard; separates versioned config from secrets |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tenacity` | `>=9` (9.1.4 current, verified today) | Bounded retries + jitter for REST pagination, OI polls, listen-key-free public reads | Always: cap attempts then fail-closed (gap journal / batch reject), never infinite retry |
| `structlog` | `>=25` (26.1.0 current, verified today) | Structured JSON logs for ingestion lineage (request → batch → quality verdict → publish) | Always; or stdlib logging + JSON formatter — pick ONE |
| `tzdata` | current (2026.4, verified today) | IANA zones on Windows (no OS zoneinfo) | Always on Windows dev; `zoneinfo("Asia/Ho_Chi_Minh")` for display edge only |
| `pytest` + `pytest-asyncio` | pytest 9.1.1 + pytest-asyncio 1.4.0 (both verified today) | Determinism + adapter + quality-gate tests | `asyncio_mode = "auto"`; never hit Binance in unit tests |
| `respx` | 0.23.1 (verified today) | Mock SDK-underlying httpx in adapter tests | Adapter tests use recorded exchangeInfo/kline fixtures |
| `ruff` + `mypy` | latest at init / strict=true for `src/` | Lint+format; typed Decimal boundaries | CI gates; domain/execution paths strict |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio` collector task | cron / Windows Task Scheduler / Compose `restart: unless-stopped` one-shot | Cron/Scheduler splits the single-loop architecture and complicates watermark atomicity; a long-running asyncio process in Compose keeps poll→persist→watermark in one transaction scope. Use OS scheduler only for the weekly *backup* trigger, not the 5-min OI loop |
| DuckDB views | Pandas/Polars-only coverage script | DuckDB gives a stable SQL contract (`SELECT * FROM coverage_v1`) shared by CLI, QA checks, and Phase-6 reports; keep Polars for checks, DuckDB for the queryable contract |
| `pg_dump` custom format | `pg_dump` plain SQL | Custom format (`-Fc`) + `pg_restore` is smaller and supports parallel restore; plain SQL is more greppable. Either passes D-12 — planner picks, custom format recommended |
| Parquet per-day files | Per-month files | Per-day matches D-04 example and keeps re-publish/repair blast radius small; per-month halves file count. 5 symbols × 3 intervals × 365 d ≈ 5.5k files/yr — fine for DuckDB glob. Stay with per-day |

**Installation:**
```bash
uv add "binance-sdk-derivatives-trading-usds-futures>=17.3,<18" "pyarrow>=19" "duckdb==1.5.5" "polars>=1.44,<2.0" "sqlalchemy>=2.0,<2.1" "psycopg[binary,pool]>=3.3,<4" "alembic>=1.19" "pydantic>=2.11,<3" "pydantic-settings>=2" "tenacity>=9" "structlog>=25" "tzdata"
uv add --dev "pytest>=9" "pytest-asyncio>=1.4" "respx>=0.23" "ruff" "mypy"
```

**Version verification:** all versions above confirmed via `pip index versions <pkg>` on 2026-09-19 (PyPI registry reads). SDK 17.4.0 > STACK.md's 17.3.1; Alembic 1.20.0 > STACK's 1.19.1; Polars 1.44.2 > STACK's 1.44.1; SQLAlchemy 2.0.54 > STACK's 2.0.52; psycopg 3.3.6 > STACK's 3.3.5. Floors hold; only the lockfile needs to float forward.

## Package Legitimacy Audit

> The `gsd-tools query package-legitimacy` seam is not available in this environment, so this audit is manual: PyPI registry existence (`pip index versions`) + project-authority cross-check (STACK.md / official docs / Context7). Planner must gate installs behind `uv lock` review; no package below is new, low-download, or repo-less to my knowledge, but download-count spot-checks were not run — treat Verdicts as MEDIUM confidence.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| binance-sdk-derivatives-trading-usds-futures | PyPI (17.4.0 listed) | ~2+ yrs lineage (v6→v17) | High (official Binance SDK) | github.com/binance/binance-sdk-* [ASSUMED exact org path — confirm at implementation] | OK (official vendor, STACK-canonical) | Approved |
| duckdb | PyPI (1.5.5) | 6+ yrs | Very high (~10M+/mo) | duckdb/duckdb | OK | Approved |
| polars | PyPI (1.44.2) | 5+ yrs | Very high | pola-rs/polars | OK | Approved |
| pyarrow | PyPI (25.0.1) | 8+ yrs (Apache) | Very high | apache/arrow | OK | Approved |
| sqlalchemy | PyPI (2.0.54) | 15+ yrs | Very high | sqlalchemy/sqlalchemy | OK | Approved |
| psycopg | PyPI (3.3.6) | 3+ yrs (v3 line) | Very high | psycopg/psycopg | OK | Approved |
| alembic | PyPI (1.20.0) | 10+ yrs | Very high | sqlalchemy/alembic | OK | Approved |
| pydantic / pydantic-settings | PyPI (2.13.5) | 6+ yrs | Very high | pydantic/pydantic | OK | Approved |
| tenacity | PyPI (9.1.4) | 10+ yrs | Very high | joshuaalbert/tenacity (maintained) | OK | Approved |
| structlog | PyPI (26.1.0) | 10+ yrs | High | hynek/structlog | OK | Approved |
| tzdata | PyPI (2026.4) | IANA data repack | Very high | python/tzdata | OK | Approved |
| pytest / pytest-asyncio / respx | PyPI | Mature | Very high | pytest-dev/* / lundberg/respx | OK | Approved |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
**Explicitly forbidden (do NOT install):** `binance-connector`, `binance-futures-connector` (archived 2026-04-30 per STACK.md); `ccxt` for any order/data path in this phase (V1 needs Binance-native semantics); `polars==2.0.0rc1`, `httpx==1.0*` pre-releases, Python 3.14 as baseline.

## Architecture Patterns

### System Architecture Diagram

```text
Binance USDⓈ-M REST (fapi)
 ├─ /fapi/v1/klines ─────────┐ (paginated, limit=1500, weight-aware sleep)
 ├─ /fapi/v1/exchangeInfo ───┤ (weight 1, versioned snapshot)
 ├─ /fapi/v1/openInterest ───┤ (5-min poll, weight 1)
 ├─ /futures/data/openInterestHist ┤ (one-shot opportunistic harvest, ≤30d)
 └─ /fapi/v1/fundingRate ────┘ (backfill ×3 req/symbol + 8h ongoing poll)
        ↓ (official SDK behind project-owned adapter: SDK models stop here)
 ┌─ Backfill CLI (one-shot, deterministic window cursors)
 │     ↓ validate batch (fail-closed / warn-flag per D-10)
 │     ↓ publish immutable Parquet (interval= → symbol= → date=)
 └─ Collector process (asyncio, 5-min OI + 8h funding ticks)
       ↓ persist snapshot + watermark + gap journal (same PG txn)
Parquet data/raw/  ──→ DuckDB views (coverage_v1, oi_latest_v1) ──→ coverage CLI
PostgreSQL 17 (symbol_metadata versions, coverage windows, watermarks, gap journal)
        ↓
Backup script (pg_dump -Fc + Parquet rsync/copy + off-host) → scratch restore verify
```

### Recommended Project Structure
```text
src/
├── adapters/
│   └── binance_usdm.py      # ONLY module importing the SDK; exposes dataclasses
├── data/
│   ├── backfill.py          # kline/funding pagination + deterministic cursors
│   ├── quality.py           # pure functions: dupes / OHLC / regression / gap checks
│   ├── store.py             # Parquet publish (immutable) + partition paths
│   ├── collector.py         # asyncio OI/funding loop + watermark/gap journal
│   ├── metadata.py          # exchangeInfo → symbol_metadata versioned upsert
│   └── coverage.py          # CLI + DuckDB view queries (effective range, counts)
├── db/
│   ├── models.py            # SQLAlchemy 2.0 async models (metadata, watermarks, gaps)
│   └── alembic/             # baseline migration (never create_all in prod paths)
├── ops/
│   └── backup.py            # single-command backup + scratch-restore drill
└── sql/
    └── coverage_v1.sql      # checked-in DuckDB view definitions
```

### Pattern 1: Adapter boundary (SDK never leaks)
**What:** one module owns all SDK imports and translates responses into frozen project dataclasses (`Kline`, `FundingTick`, `OiSnapshot`, `SymbolFilters`) with `Decimal` for prices/quantities.
**When to use:** every Binance touch in this phase.
**Example:**
```python
# Source: project rule BINANCE.md §2 + DATA_PIPELINE §14 (SDK behind adapters)
@dataclass(frozen=True)
class Kline:
    symbol: str
    interval: str
    open_time_utc: datetime  # tz-aware UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
```

### Pattern 2: Deterministic paginated backfill
**What:** cursor over fixed `[startTime, endTime)` windows with `limit=1500`; dedupe incoming pages by `(symbol, interval, open_time)`; drop the forming (unclosed) candle; write one Parquet file per symbol/interval/date; record per-file SHA/page cursors in PG for resume.
**When to use:** DATA-01 bootstrap and any later depth extension (D-02 reversible).
**Example:**
```python
# Pseudocode — exact SDK call names re-verified at implementation [ASSUMED shape]
cursor = window_start
while cursor < window_end:
    page = adapter.klines(symbol, interval, startTime=cursor, limit=1500)  # weight 10
    sleep(weight_aware_delay(headers["X-MBX-USED-WEIGHT-1M"]))
    batch = [to_kline(r) for r in page if r.close_time < now_utc]  # drop forming candle
    verdict = quality.check(batch)  # fail-closed vs warn-flag per D-10
    if verdict.structural_ok:
        store.publish(batch)
    cursor = max_open_time(batch) + interval_ms
```

### Pattern 3: OI/funding collector with watermark + gap journal
**What:** single asyncio loop; every tick fetch OI for live-5 concurrently (bounded semaphore), insert snapshots + advance `collector_watermarks(symbol, last_tick_utc)` in the SAME PG transaction; on exception/missed tick insert a `collector_gaps(symbol, expected_utc, observed_utc, reason)` row and continue — never interpolate (D-09). Funding polled on its own slower cadence into separate files/table.
**When to use:** DATA-02 from day one of implementation.

### Pattern 4: Versioned symbol metadata
**What:** each `exchangeInfo` fetch inserts a new `symbol_metadata` row (`metadata_observed_at_utc`, tick/step/min/max/notional JSON, position-mode snapshot) rather than UPDATE; readers pin `observed_at` ≤ dataset date. Fields per DATA_MODEL §2.11 [VERIFIED: docs/data/DATA_MODEL.md:287-308 read this session]. Price/qty/notional parsed to `Decimal`, never float (ENGINEERING_PRINCIPLES Python rule).
**When to use:** DATA-03; refresh on bootstrap + weekly (filter changes are rare but silent).

### Pattern 5: Single-command backup + scratch-restore drill
**What:** `backup.py` runs `pg_dump -Fc`, copies `data/raw/` OI+fencing snapshots (and candle Parquet manifest), pushes both off-host (second disk/remote — D-12 hard requirement), then restores into scratch PG database + temp dir and asserts row-count + hash equality; exits non-zero on any mismatch. Weekly schedule deferred to later hardening; Phase 2 needs the drill green on demand.
**When to use:** DATA-04.

### Anti-Patterns to Avoid
- **Storing OHLCV rows primarily in PostgreSQL:** violates D-05 (one-way); PG holds metadata/watermarks only. DATA_PIPELINE §13 explicitly warns against PG-only historical storage.
- **Mutating published Parquet ("fix in place"):** violates D-04 immutability; repairs publish a new file version and supersede the manifest entry.
- **Interpolating missed OI polls:** violates D-09; gaps are journaled and downstream treats them as missing, not zero.
- **Hard-coding tick/step/notional or weight limits:** violates exchange-authority; read from live `exchangeInfo` + response weight headers.
- **Using the forming candle in backfill:** classic lookahead/repaint leak; always exclude `close_time > now`.
- **`create_all` for schema:** forbidden; Alembic baseline migration only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parquet I/O + partitioning | Custom binary format / CSV store | pyarrow via Polars `write_parquet` + Hive dirs | Compression, schema evolution, predicate pushdown, DuckDB-native reads; CSV loses types and inflates 2.7M rows |
| SQL over Parquet | Hand-rolled file scanners for coverage | DuckDB `read_parquet` + checked-in views | Vectorized engine, `hive_partitioning=true` gives partition cols free [VERIFIED: Context7] |
| PG async access | Raw psycopg strings everywhere | SQLAlchemy 2.0 async (`create_async_engine`, `async_sessionmaker`) | Connection/pool lifecycle, migrations story, typed models [VERIFIED: Context7] |
| Retries/backoff | Hand-rolled sleep loops | tenacity (bounded, jittered) | Fail-closed needs attempt caps + jitter; infinite retry on poll paths masks outages |
| Structured logs | Custom logger | structlog (or stdlib JSON formatter) — one choice | Decision-lineage audit trail is a safety feature |
| Timezones | Manual offset math | `zoneinfo` + `tzdata`, UTC everywhere, HCMC at display edge | DST/offset bugs; Windows lacks system zoneinfo (tzdata wheel required) |
| Kline pagination | "Fetch all" single call | Windowed cursor, limit=1500 | API caps at 1500/req; unbounded windows silently truncate |

**Key insight:** every deceptively-complex problem in this phase (partition pruning at 2.7M rows, async pool lifecycle, retry-then-gap semantics, schema evolution) already has a boring standard solution. Custom code here creates the exact failure modes (silent truncation, fabricated continuity, leaked SDK types) that the fail-closed posture exists to prevent.

## Common Pitfalls

### Pitfall 1: Including the forming (unclosed) candle in backfill
**What goes wrong:** last row of each paginated window is still forming; its OHLC mutates, breaking immutability + future determinism checks.
**Why it happens:** `/fapi/v1/klines` returns the in-progress candle like any other; paginators naively take all rows.
**How to avoid:** filter `close_time_utc <= last_closed_boundary(now, interval)` before publish; covered by a unit test with a frozen clock.
**Warning signs:** duplicate open_times across consecutive runs; coverage end drifting with wall-clock.

### Pitfall 2: Silent truncation by unbounded time windows
**What goes wrong:** requesting 2y of 1m without pagination returns only the most recent 1500 candles; bootstrap looks green but holds 25h, not 12mo.
**Why it happens:** docs default `limit=500, max 1500` — no error when the window exceeds it [VERIFIED endpoint table].
**How to avoid:** assert `expected_candles ≈ (end-start)/interval_ms` per window; windowed cursor loop is the only accepted shape.
**Warning signs:** coverage range far shorter than requested depth; round `total_rows / symbols` ≈ 1500 multiples.

### Pitfall 3: Treating `openInterestHist` as a backfill source
**What goes wrong:** planner/executor tries to "backfill 2y of OI" via `/futures/data/openInterestHist`; only ~30 days exist, and `sumOpenInterest` (period aggregate) ≠ `openInterest` (point snapshot) — different semantics.
**Why it happens:** endpoint names look interchangeable; community threads confirm the confusion and 1–3 min publication lag on hist values [CITED: dev.binance.vision thread + docs "Only the data of the latest 1 month is available"].
**How to avoid:** one-shot harvest at bootstrap for the trailing 30d labeled `source=openInterestHist-v1` (research-grade, not canonical); canonical series is self-collected `source=collector-v1` from day one. Never mix the two without a source tag.
**Warning signs:** OI values with `timestamp` not aligning to poll grid; mixing period-aggregates into point series.

### Pitfall 4: Float quantization of tick/step sizes
**What goes wrong:** `0.1`-style binary-float tick values corrupt the realized-risk check boundary later (Phase 5 inherits this metadata).
**Why it happens:** `exchangeInfo` filters arrive as strings; `float()` is the lazy parse.
**How to avoid:** parse every filter string to `Decimal` at the adapter boundary; store PG `NUMERIC`, Parquet decimal/string; ban `float` for exchange-sensitive values (AGENTS.md hard rule).
**Warning signs:** `repr(tick) = 0.010000000000000000208`; mypy strict failures on Decimal|float unions.

### Pitfall 5: Backfill hammering the weight limit (429s mid-bootstrap)
**What goes wrong:** 1,825 requests × weight 10 with no pacing trips the 2400/min IP limit; Binance returns 429/418 and the run half-completes.
**Why it happens:** weight-10 pages look cheap individually; aggregate 18k weight is not.
**How to avoid:** read `X-MBX-USED-WEIGHT-1M` response headers, sleep ~150–250 ms between pages, tenacity-retry 429 with exponential backoff + jitter, resume from persisted page cursors (idempotent re-run).
**Warning signs:** 429 responses in logs; gaps exactly at rate-limit windows.

### Pitfall 6: No `uv` / Docker on the dev machine (toolchain gap)
**What goes wrong:** plans assuming `uv sync` + Compose PG17 fail on this Windows box (verified today: `uv` and `docker` not recognized; system Python is **3.14.3**, not the mandated 3.13).
**Why it happens:** greenfield + fresh machine; STACK assumes tooling present.
**How to avoid:** Phase 2 plan 1 must install `uv`, pin `python 3.13` (via `uv python install 3.13` or Docker `python:3.13-slim-bookworm`), and stand up PG17 via Compose — or document the approved fallback (local PG17 install / SQLite-spike explicitly labeled non-canonical). See Open Questions.
**Warning signs:** executor burning budget on "command not found".

## Code Examples

### Backfill quality gate (Polars — pure, testable)
```python
# Source pattern: DATA_PIPELINE §6 rules; Polars lazy API per STACK.md
import polars as pl


def check_batch(df: pl.DataFrame) -> dict:
    dupes = df.filter(pl.col("open_time_utc").is_duplicated()).height
    ohlc_bad = df.filter(
        (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
        | (pl.col("high") < pl.col("low"))
    ).height
    regress = (df["open_time_utc"].diff() <= 0).fill_null(False).sum()
    # structural → fail closed; gaps → warn+flag (D-10)
    structural_ok = dupes == 0 and ohlc_bad == 0 and regress == 0
    expected = (df["open_time_utc"].max() - df["open_time_utc"].min()) // interval_ms + 1
    gaps = (
        expected - df.height
    )  # [ASSUMED arithmetic shape — verify interval_ms per timeframe at implementation]
    return {
        "structural_ok": structural_ok,
        "duplicates": dupes,
        "ohlc_violations": ohlc_bad,
        "regressions": regress,
        "gaps": gaps,
    }
```

### DuckDB Hive-partitioned coverage view
```python
# Source: Context7 /duckdb/duckdb-python — read_parquet hive_partitioning + from_parquet relation API [VERIFIED]
import duckdb

con = duckdb.connect()  # in-process :memory:; pass database= path to persist views
con.execute("""
CREATE OR REPLACE VIEW candles_v1 AS
SELECT *, interval AS tf
FROM read_parquet('data/raw/interval=*/symbol=*/date=*/part.parquet', hive_partitioning=true)
""")
# Per-symbol effective range + row counts (feeds the coverage CLI, D-11):
# SELECT symbol, tf, MIN(open_time_utc) AS start_utc, MAX(open_time_utc) AS end_utc,
#        COUNT(*) AS rows FROM candles_v1 GROUP BY symbol, tf;
```

### SQLAlchemy 2.0 async engine (psycopg)
```python
# Source: Context7 /websites/sqlalchemy_en_20 — official dialect docs [VERIFIED]
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine("postgresql+psycopg://user:pass@localhost:5432/trading")
Session = async_sessionmaker(engine, expire_on_commit=False)
# Pool control variant: psycopg_pool.AsyncConnectionPool + poolclass=NullPool [VERIFIED same source]
```

### UTC storage / HCMC display edge
```python
# Source: ENGINEERING_PRINCIPLES §8 + DATA_PIPELINE §7 (UTC store, display converts)
from datetime import datetime, timezone
from zoneinfo import ZoneInfo  # needs tzdata wheel on Windows [VERIFIED: PyPI tzdata 2026.4 exists]

open_time_utc = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)  # persist this
display = open_time_utc.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))  # display edge only (D-06)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `binance-connector` / `binance-futures-connector` | `binance-sdk-derivatives-trading-usds-futures` v17.x | Archived 2026-04-30 | Old libs lack Algo endpoints + current user-data events; never use |
| Conditional SL/TP via normal order endpoint | Algo Order service (`/fapi/v1/algoOrder`, `ALGO_UPDATE`) | Dec 2025 migration | Phase-9 concern, but metadata/position-mode detection in Phase 2 must already follow new model |
| PG-only market-data storage (§11 monthly partitions) | Parquet immutable raw + DuckDB analytics, PG for operational state (§13) | DATA_PIPELINE §13 supersedes §11 | D-05 locks this; §11 partition sketch is NOT the plan |
| `asyncpg` as default async driver | `psycopg3` async via `postgresql+psycopg://` | STACK canonical (D018–D021) | One driver for sync+async; asyncpg only on measured bottleneck |

**Deprecated/outdated:**
- Legacy connector packages: archived, lack current endpoints — forbidden.
- Polars 2.0.0rc1 / SQLAlchemy 2.1rc1 / httpx 1.0-dev / Python 3.14 baseline: pre-release lines move under you; determinism starts with pinned stable deps.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SDK v17 method/field names (klines, open_interest, funding_rate, exchange_info shapes) | Binance Endpoints | MEDIUM — adapter tests fail fast against recorded fixtures; mitigated by mandatory re-verify task |
| A2 | Funding settles 3×/day (~8h) so 2y funding ≈ 2,190 records/symbol | Binance Endpoints | LOW — pagination handles any cadence; count estimate only affects progress bars |
| A3 | Weight-aware sleep 150–250 ms + header reads suffice for bootstrap pacing | Pitfall 5 | LOW — tenacity retry + resume cursors make overruns recoverable |
| A4 | Per-day Parquet ≈ 5.5k files/yr is fine for DuckDB glob on dev machine | Alternatives | LOW — can compact to monthly later (cheap, readers use globs) |
| A5 | `pg_dump -Fc` available wherever PG17 runs (Compose image) | Architecture P5 | LOW — fallback to plain SQL dump |
| A6 | Exact Binance SDK GitHub org path for source cross-check | Legitimacy Audit | LOW — PyPI presence verified; repo URL confirmed at implementation |

## Open Questions

1. **Dev-machine toolchain (uv + Docker + Python 3.13 vs installed 3.14.3)?**
   - What we know: this Windows box has Python 3.14.3, no `uv`, no `docker` (verified today). STACK mandates Python 3.13 + uv + Compose PG17.
   - What's unclear: whether the user will install Docker Desktop / allow `uv python install 3.13`, or prefers a local PG17 install.
   - Recommendation: planner makes Toolchain Setup plan 1 (install uv → `uv python install 3.13` → Compose PG17) with a `checkpoint:human-verify` if Docker Desktop install needs user action; never silently build on 3.14.

2. **Off-host backup target?**
   - What we know: D-12 requires off-host copy; machine has OneDrive (project lives under OneDrive/Documents).
   - What's unclear: whether OneDrive folder counts as "off-host" for the drill, or a second physical target is required.
   - Recommendation: accept OneDrive-synced backup dir as the Phase-2 drill target (documented), harden to true second-host later; flag in plan for user confirm.

3. **Funding ongoing cadence (8h poll vs daily sweep)?**
   - What we know: funding settles ~8h; missing one settlement leaves a permanent hole (no fabrication allowed).
   - What's unclear: optimal poll (every 8h aligned to 00/08/16 UTC vs daily catch-up sweep).
   - Recommendation: daily catch-up sweep of `fundingRate` (cheap: ≤1 req/symbol/day) + alert on gap; planner's discretion per delegation.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | All runtime code (STACK lock) | ✗ (3.14.3 installed) | — | `uv python install 3.13` or Docker `python:3.13-slim-bookworm`; NEVER build on 3.14 silently |
| uv | Env/lockfile (`uv sync`, `uv run`) | ✗ | — | Install via official script; BLOCKING until resolved (plan 1) |
| Docker / Compose | PG17 + reproducible stack | ✗ | — | Local PG17 install (documented, user confirms) or SQLite spike labeled non-canonical |
| PostgreSQL 17 | Metadata/watermarks/gaps | ✗ (no server found) | — | Compose `postgres:17-bookworm` once Docker exists |
| Network → fapi.binance.com | Backfill + OI/funding | [ASSUMED reachable] | — | No fallback: offline bootstrap impossible; verify with `GET /fapi/v1/time` (weight 1) in plan 1 |
| pip / PyPI | Version verification | ✓ | pip 26.1.2 | — (used for all `pip index versions` checks today) |

**Missing dependencies with no fallback:**
- `uv` + Python 3.13 + reachable PostgreSQL 17 — planner must resolve in the first plan before any ingestion code runs.

**Missing dependencies with fallback:**
- Docker → local PG17 install (user-confirmed, documented as equivalent for Phase 2 scope).

## Validation Architecture

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) [VERIFIED: PyPI today] |
| Config file | none — Wave 0 creates `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.ruff]`, `[tool.mypy]`) |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | Quality gate rejects dupes/OHLC-violation/regression batches; flags gaps | unit | `uv run pytest tests/test_quality.py -x -q` | ❌ Wave 0 |
| DATA-01 | Paginator resumes from cursor; drops forming candle; no silent truncation | unit (respx + fixtures) | `uv run pytest tests/test_backfill.py -x -q` | ❌ Wave 0 |
| DATA-01 | Coverage CLI prints per-symbol range + violation/gap counts | integration (DuckDB + sample Parquet) | `uv run pytest tests/test_coverage.py -x -q` | ❌ Wave 0 |
| DATA-02 | Missed OI tick writes gap row, never interpolated value | unit (fake clock/adapter) | `uv run pytest tests/test_collector.py -x -q` | ❌ Wave 0 |
| DATA-03 | exchangeInfo snapshot inserts new version; filters parsed as Decimal | unit (recorded fixture) | `uv run pytest tests/test_metadata.py -x -q` | ❌ Wave 0 |
| DATA-04 | Backup→scratch-restore verifies row-count/hash equality; failure exits non-zero | integration (scratch PG + tmpdir) | `uv run pytest tests/test_backup.py -x -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -x -q`
- **Per wave merge:** `uv run pytest tests/ -q` + `ruff check` + `mypy` (strict on `src/`)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` — project init, pytest/ruff/mypy config, Python `requires-python = "==3.13.*"` [ASSUMED exact pin syntax — standard uv practice]
- [ ] `tests/` + `tests/fixtures/` (recorded exchangeInfo sample, kline page sample, OI sample)
- [ ] `alembic.ini` + baseline migration for `symbol_metadata`, `collector_watermarks`, `collector_gaps`, coverage-window tables
- [ ] `docker-compose.yml` (app + `postgres:17-bookworm` + named volume) or documented local-PG fallback
- [ ] Framework install: `uv sync` (after toolchain plan resolves uv/Python 3.13)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (public market-data endpoints; no API key needed for klines/OI/funding/exchangeInfo) | No secrets in Phase 2 — assert this in review |
| V3 Session Management | No | No sessions |
| V4 Access Control | Partial | PG credentials via env, never in git; backup dir permissions |
| V5 Input Validation | **Yes** | pydantic v2 boundary models for every exchange payload; Decimal parsing at adapter edge |
| V6 Cryptography | No | No crypto hand-rolled; backup integrity via hashes (SHA-256 manifest), not encryption (document if off-host needs it — Open Q2) |
| V10 Malicious Code / Supply Chain | Yes | Pinned lockfile (`uv.lock` committed); no archived connectors; no pre-release deps |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Dependency confusion / slopsquatting (ML-generated package names) | Tampering | Install only audit-table packages; `uv lock` review; never `pip install` an LLM-suggested name unchecked |
| Secret leak (PG URL, future API keys in logs/dumps) | Information disclosure | structlog secret-free schema; `pg_dump` files excluded from git; env-only credentials |
| Silent data corruption (bad batch overwrites good Parquet) | Tampering | Immutable publish + fail-closed gates + hash manifest; restore drill proves recovery |
| DoS via unbounded bootstrap (429 → IP ban 418) | Denial of service | Weight-aware pacing + bounded retries; 418 backoff respected (trading API precedent) |

## Sources

### Primary (HIGH confidence)
- `/websites/sqlalchemy_en_20` (Context7) — async engine, psycopg_pool + NullPool, AsyncSession patterns
- `/duckdb/duckdb-python` (Context7) — `read_parquet` hive_partitioning/union_by_name, `connect()` semantics
- `pip index versions` (PyPI registry, 2026-09-19) — SDK 17.4.0, duckdb 1.5.5, polars 1.44.2, sqlalchemy 2.0.54, psycopg 3.3.6, alembic 1.20.0, pyarrow 25.0.1, pytest 9.1.1, pydantic 2.13.5, tenacity 9.1.4, structlog 26.1.0, tzdata 2026.4, respx 0.23.1, pytest-asyncio 1.4.0
- `docs/data/DATA_MODEL.md` §2.11, `docs/architecture/DATA_PIPELINE.md`, `docs/integration/BINANCE.md`, `docs/GLOSSARY.md`, `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/backtest/BACKTEST_SPEC.md`, `docs/configuration/CONFIGURATION.md` — read this session (project authority)

### Secondary (MEDIUM confidence)
- developers.binance.com USDⓈ-M endpoint pages via WebSearch excerpts (klines, exchangeInfo, openInterest, openInterestHist/openInterestHist-statistics, fundingRate) — official source, excerpt-mediated
- dev.binance.vision community thread on openInterest vs sumOpenInterest semantics + 1–3 min hist lag

### Tertiary (LOW confidence)
- SDK method names, funding 8h cadence arithmetic, OneDrive-as-off-host acceptability — marked [ASSUMED], gated by re-verify tasks

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package version read from live PyPI today; two Context7-doc verifications (SQLAlchemy async, DuckDB parquet)
- Architecture: HIGH — patterns derive from locked D-decisions + canonical docs read this session; scheduler choice is delegated discretion with rationale
- Pitfalls: MEDIUM-HIGH — endpoint-driven pitfalls verified; SDK-shape items honestly flagged ASSUMED
- Environment: HIGH — `uv`/docker absence + Python 3.14.3 verified by direct probe today

**Research date:** 2026-09-19
**Valid until:** ~30 days for stack/patterns; **endpoints re-verify at implementation start** (standing project policy — Binance docs drift)
