# Phase 13: Research Data Foundation Fixes - Research

**Researched:** 2026-09-30
**Domain:** Binance USDⓈ-M historical data ingestion (klines, mark-price klines, funding, OI, delisted symbols), immutable Parquet store hardening, point-in-time universe freeze, Parquet to backtest case-input builder
**Confidence:** HIGH for exchange facts (probed live against `fapi.binance.com` and `data.binance.vision` on 2026-09-30) and for in-repo seams (files read this session); MEDIUM for the runtime estimates (measured from this machine, not the VPS)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Collector universe and time-sensitive start (F-107)
- **D-01:** The collector reads its symbol list from a config-driven **collect list** instead of importing `LIVE_5` (`src/data/collector.py` imports it today). The collect list is `LIVE_5` ∪ the top-N USDT perpetuals by current volume, N = 15 (a superset of the D039 top 10–15 range). The point-in-time freeze (D-06) later selects a subset; collecting a superset costs almost nothing and OI cannot be recovered afterward. Live trading keeps its own live-5 list unchanged.
- **D-02:** The collect list is a versioned file (`docs/research/universe/collect-list-v1.toml`, or the planner's equivalent under the same directory, never under `params/`) with the symbols and the date they were chosen. It is not the frozen manifest and carries no FROZEN semantics; it is an operational input. The collector loads it at start and refuses an empty list.
- **D-03:** Ship the collector widening as the **first plan of the phase**, independent of the rest, so it can start running on a personal machine before the VPS exists (roadmap SC1, F-107). Per-symbol failure isolation and the existing watermark/gap tables stay as they are.

### History depth and backfill CLI (F-906)
- **D-04:** The backfill CLI covers **1m for 12 months** (top of the decided 6–12 month range, because the D043 trade floor of ≥100 pooled trades and ≥30 per fold is unmeasured until Phase 14) and **1H/4H for 2 years**. It replaces `DEFAULT_BACKFILL_WINDOWS_MS` (7d/30d) as the CLI default; the depth is explicit, recorded in the run output, and overridable by flags. The CLI wraps `backfill_universe` and `refresh_symbol_metadata` (F-122) and runs metadata first, so onboard time bounds each symbol's start. Symbols are processed sequentially under the existing pacing so the weight budget stays bounded; 12 months × 15 symbols of 1m is the largest job and must resume from `CursorStore` after interruption.
- **D-05:** After backfill the CLI computes the **D043 trade-floor check as a data-sufficiency report only**: bars available per symbol/interval against the depth decided in D-04, and the shortfall in plain numbers. It never lowers the floor and never edits the protocol. A shortfall is reported to the user and exits non-zero only for missing-data causes, not for the unmeasurable trade count (no trade-frequency estimate exists until Phase 14).

### Point-in-time universe freeze (F-024, F-907, D039)
- **D-06:** Ranking follows the manifest's own procedure (`docs/research/universe/research-universe-v1.toml` header, steps 1–6): trailing 30-day mean daily **quote volume** ending the day before the dataset start date, top `top_n = 12`, delisted-later symbols included, contracts without a full 30-day window ineligible. The manifest's `top_n` stays 12.
- **D-07:** The dataset start date is the earliest 1H/4H start allowed by D-04 (2 years before the run date), fixed once and written into the manifest as `selection_date`. Volume comes from 1d klines fetched per candidate; candidate discovery uses exchangeInfo plus the delisted-symbol source found in D-08.
- **D-08:** Delisted symbols: the researcher must verify, against current official Binance docs, whether the REST kline endpoints still serve delisted USDT perpetuals; if not, the fallback is Binance's public historical data archive (data.binance.vision), ingested through the same validation and Parquet layout. Record the source URL and fetch date in `docs/SOURCES.md`. If no source can supply a delisted symbol, the freeze report lists it as **unavailable** (never silently dropped) and the user decides whether to freeze with the gap noted.
- **D-09:** The freeze is a CLI step that writes symbols, `selection_date`, `status = "FROZEN"` and `content_sha256` using the existing `python -m scripts.decision_alignment.universe` hash routine, and sets `FROZEN_CONTENT_SHA256` in `scripts/decision_alignment/universe.py` in the **same commit** (UN-02 independent witnesses). Freezing is a deliberate operator action: the CLI prints the proposed manifest and requires an explicit `--freeze` flag; it is never triggered as a side effect of backfill. Committed before any evaluation.
- **D-10:** `refresh_symbol_metadata` (DATA-03) also writes rows for delisted and currently non-TRADING symbols in the manifest, so point-in-time tick/step/notional are available for every research symbol. Each refresh keeps inserting new versioned rows (existing PK behaviour), never updating.

### Mark-price klines (D037)
- **D-11:** Ingest Binance `markPriceKlines` for the same symbols and intervals as the trade klines (1m required for SL/TP trigger evaluation; 1H/4H for parity), into a **separate Parquet dataset** (own partition root, e.g. `mark_klines`) with the same partitioning, structural validation and atomic publish as trade klines. Mark-price rows have no volume: the schema and validator must not require it. Endpoint path, limits and weights are re-verified against current official docs before implementation (AGENTS.md exchange-authority rule) and recorded in `docs/SOURCES.md`.
- **D-12:** Ingestion only. Phase 13 does not change the simulator; the causal trigger logic that reads mark-price klines is Phase 14. The Parquet → backtest builder (D-17) exposes the mark-price series alongside trade candles so Phase 14 can consume it.

### Backfill robustness (F-402, F-408, F-409, F-413)
- **D-13:** Never publish a partial UTC day as immutable data: a day file is published only when the day is closed (all expected bars up to the day's end exist). The current UTC day is never published by backfill; live data for it comes from the collector/WS path. (F-402)
- **D-14:** Publishing is atomic: write to a temporary file in the target directory, then `os.replace` into place. The existing no-overwrite guard stays (published files are immutable). (F-408)
- **D-15:** Zero-trade bars (volume 0, trades 0) are valid; the validator accepts them and they are not counted as structural rejections. OHLC validity checks stay. Gaps are still gaps: a missing bar is not a zero-trade bar. (F-409)
- **D-16:** The paper supervisor's reconnect and rotation path runs the REST backfill of missed closes **before** resubscribing, so a bar cannot be delivered twice or skipped across the seam (F-413, `src/paper/supervisor.py` `_resubscribe_and_backfill` and `src/paper/resync.py`). A regression test drives an unsolicited drop and asserts the order of calls. This is the only paper-runtime edit in the phase; keep it localized because Phase 16 composes the paper runtime.

### Parquet → backtest case-input builder (M4, BKTS-02)
- **D-17:** A builder in `src/backtest/` reads the immutable Parquet store (trade klines, mark-price klines, funding, OI) for a symbol/interval/date range and emits the case-input structure the simulator and `ExperimentRecord` already consume, so an experiment is reproducible from dataset + strategy + parameters + cost + execution versions (BKTS-02). It reads only closed, published partitions, never the current UTC day.
- **D-18:** The builder records a **dataset identity** (sorted file list with per-file content hash, rolled into one dataset hash) on its output, and the experiment record carries it. Same partitions in, same hash out; a changed partition changes the hash. Reading is deterministic: fixed column order, sorted by open time, no wall-clock input. Strategy code stays free of Polars (domain boundary); the builder is an adapter-side module.
- **D-19:** The builder refuses (raises a project exception, never silently pads) when a requested range has a gap that `coverage.py` reports as unresolved, unless the caller passes an explicit allow-gaps list that is recorded on the output.

### Verification
- **D-20:** Tests use recorded/fake adapter fixtures and never hit Binance. Required: atomic-publish crash test (interrupted write leaves no partial file), partial-day refusal test, zero-trade-bar acceptance test, backfill-before-resubscribe ordering test, mark-kline schema/validation tests, deterministic dataset-hash test, freeze-manifest hash test that both witnesses match, and a collect-list loader test (empty list rejected).

### Claude's Discretion
- Module and CLI names, provided the CLI lives beside the existing collector/backfill entry points and follows their argparse style.
- Exact flag names, log event names, and the layout of the mark-kline partition root.
- Whether the collect-list file is TOML or reuses the manifest reader, subject to D-02.
- Pacing and retry constants for the 12-month backfill within the existing `BackfillConfig` knobs.

### Deferred Ideas (OUT OF SCOPE)
- Simulator use of mark-price klines for SL/TP triggers — Phase 14.
- Executable trade-floor / gate code and holdout-consumed writer (F-960) — Phase 26.
- Trade-count estimate for the D043 floor — impossible until the Phase 14 causal simulator exists.
- HEALTHCHECK, DB localhost binding, encrypted off-VPS backups, VPS baseline and heartbeat monitor — Phase 13.1.
- Reconsidering the D043 trade floor if depth falls short — needs a new DECISIONS row, not this phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Bootstrap 1m/1H/4H candles per symbol with continuity/quality checks and query effective per-symbol coverage | Backfill CLI over `backfill_universe` (depth + per-symbol onboard/delivery bounds), partial-day clamp, zero-trade acceptance, atomic publish, coverage generalised beyond `LIVE_5`; weight/time budget below |
| DATA-02 | Collect OI snapshots continuously + funding history so the 30-day API window never destroys research data | Collect-list loader (D-01..D-03), Dockerfile does not copy `docs/`, collector loop period drift, funding-history backfill needs pagination (1000 rows = ~333 days) and an empty-`markPrice` adapter fix |
| DATA-03 | Versioned symbol metadata from live exchangeInfo | `refresh_symbol_metadata` with a mandatory `universe` filter (`contract_type` is `String(16)`, live value `TRADIFI_PERPETUAL` is 17 chars), SETTLING/delisted rows, `deliveryDate` needed by the CLI |
| DATA-04 | Automated backup + restore drill covering PostgreSQL and the OI dataset | Already implemented (`src/ops/backup.py`, `tests/test_backup.py`); Phase 13 obligation is to keep every new dataset under `data/raw` so the default backup root and the Compose `rawdata` volume cover it; encrypted off-VPS is Phase 13.1 |
| BKTS-02 | Every experiment reproducible from dataset + strategy + parameter set + cost + execution versions | Case-input builder + dataset identity feeding the existing `ExperimentRecord.data_snapshot_id` (64-hex) |
</phase_requirements>

## Summary

Every Binance fact the phase depends on was probed live on 2026-09-30. `GET /fapi/v1/markPriceKlines` exists with the same 12-column row shape as trade klines but volume and quote volume are `"0"` and the trades field is a price-tick count (so it must not be reused as `trade_count`); weight follows the kline table (limit 1000 = 5, limit 1500 = 10, measured 1 to 11 on one 1500-row call); the installed SDK 17.4.0 already exposes `rest_api.mark_price_kline_candlestick_data(symbol, interval, start_time, end_time, limit)` and `.data()` returns `list[list]` exactly like trade klines, so the existing `_row_to_kline` pattern extends with one new adapter method. REST kline endpoints serve **some** delisted symbols and not others: symbols still in exchangeInfo with status `SETTLING` (130 USDT perpetuals today) answered with data in every probe (FTTUSDT, SCUSDT, RAYUSDT, OMGUSDT, MKRUSDT, DENTUSDT), some removed symbols also serve (LUNAUSDT, EOSUSDT, MATICUSDT), but others answer `-1121 Invalid symbol` for trade klines (SXPUSDT, AERGOUSDT, BTCSTUSDT, BDXNUSDT), even though `fundingRate` and `markPriceKlines` may still answer for them. data.binance.vision serves all of them (31 USDT symbols exist in the archive but not in exchangeInfo, five of them with data after the likely dataset start of 2024-09-30), so the archive fallback in D-08 is not optional and delisted-symbol candidate discovery needs the archive bucket listing, not only exchangeInfo.

Two live findings change how the locked decisions must be implemented. (1) After a contract is delivered, REST klines keep returning an endless stream of flat zero-volume zero-trade bars up to "now" (FTTUSDT delivered 2022-11-14 still returns flat 1.5900 bars in 2026). Once D-15 accepts zero-trade bars, a naive backfill of a delisted symbol up to now would publish years of synthetic data as immutable; the CLI must cap each symbol's end at `deliveryDate` (exchangeInfo) or the archive's last real bar. (2) The 1m depth of 12 months against a 2-year 1H/4H dataset with a 40/40/20 time split means the whole Development split and Validation fold 1 have no 1m intrabar data (simulator falls back to SL-first there); the data-sufficiency report (D-05) must show per-split 1m coverage, and extending 1m to 24 months is cheap via the archive (see Open Questions).

The code seams are small and well isolated. Partial-day publish (F-402) lives at one choke point (`backfill_symbol_interval` end-of-loop flush plus a missing `open_time < end_ms` filter), atomic write (F-408) at one line in `store.py`, zero-trade rejection (F-409) at one predicate (`trade_count <= 0`, `quality.py:183`), and the supervisor order (F-413) at `supervisor.py:242-243`. Existing tests that assert partial-day publish (`test_forming_candle_at_frozen_now_is_excluded` and its tracer-slice twin) must be rewritten deliberately. The builder must not live in the pure `src/backtest` package as written in D-17 without lifting that package's no-Polars rule (its docstring forbids it); the recommendation is an adapter-side module under `src/data/` (D-18 already says adapter-side).

**Primary recommendation:** Ship Plan 1 (collect-list collector) immediately and independently; then harden store/quality/backfill (partial-day, atomic, zero-trade) before any long backfill runs, because published Parquet is immutable and a wrong file cannot be repaired; cap delisted symbols at `deliveryDate`/last real bar; place the mark-kline dataset under `data/raw/` (not a sibling of `data/raw`) so the backup root and Compose volume cover it.

## Project Constraints (from CLAUDE.md / AGENTS.md)

- Decimal only for exchange-sensitive values; no `float` (AST guard `tests/test_domain_no_float.py` scans the pure packages). Determinism: same inputs give byte-equivalent outputs, no wall clock in readers. [CITED: AGENTS.md Constraints]
- Exchange authority: endpoints, weights and filters re-verified against current official docs, never from memory; record source URL + fetch date in `docs/SOURCES.md`. [CITED: AGENTS.md]
- Python 3.13, uv, asyncio, official Binance SDK behind adapters (SDK types never leak), Polars/DuckDB/Parquet for research storage, pytest + Ruff + mypy strict. [CITED: AGENTS.md Technology Stack]
- Polars must not enter strategy/domain code (`src/core`, `src/domain`, `src/backtest` pure package). [CITED: AGENTS.md; `src/backtest/__init__.py` docstring]
- No Redis/Kafka; single-process asyncio + PostgreSQL + Parquet. LLM never in the decision path. [CITED: AGENTS.md What NOT to Use]
- Fail closed: uncertain data means NO_TRADE / refuse, never pad or interpolate. [CITED: AGENTS.md Constraints]
- GSD workflow enforcement: edits go through a GSD command; `tdd_mode: true`, `security_enforcement: true` (ASVS 1), `nyquist_validation: true` in `.planning/config.json`. [VERIFIED: .planning/config.json]
- CodeGraph: `.codegraph/` exists; run `codegraph explore` before Grep/Read when locating code. [CITED: user CLAUDE.md]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Kline / mark-kline / funding / exchangeInfo fetch | Adapter (`src/adapters/binance_usdm.py`) | — | Only module allowed to import the SDK; new `mark_klines`, `ticker_24hr`, `server_time` methods go here |
| Archive (data.binance.vision) download + checksum + CSV parse | Data ingestion (`src/data/`, httpx) | Adapter-style boundary (returns `Kline`) | Not an SDK call; must feed the same `Kline` -> `check_batch` -> `publish_batch` path |
| Quality gate (zero-trade, OHLC, gaps) | Data (`src/data/quality.py`) | — | Pure function over frames |
| Immutable publish (atomic, no overwrite, closed days only) | Data (`src/data/store.py`, `backfill.py`) | — | Single writer choke point |
| Collect list load, collector loop | Data (`src/data/collector.py`) | Docker/Compose (file must be in image or mounted) | Operational input, not a param or manifest |
| Universe candidate discovery + ranking + freeze | Data CLI (new `src/data/universe_freeze.py`) | `scripts/decision_alignment/universe.py` (hash) | Network + Polars belong outside the stdlib-only gate module; the gate keeps only hashing/validation |
| Symbol metadata versioning | Data (`metadata.py`) -> PostgreSQL | Adapter (`exchange_info`) | Versioned insert, never update |
| Parquet -> case-input builder + dataset identity | Data (adapter-side, `src/data/`) | Backtest package (consumes dicts only) | Polars/DuckDB allowed here; `src/backtest` stays pure |
| Supervisor backfill-before-resubscribe | Paper runtime (`src/paper/supervisor.py`) | — | Only paper edit in the phase |
| Backup/restore of new datasets | Ops (`src/ops/backup.py`) | Compose volume | Default parquet root is `data/raw`; keep datasets under it |

## Standard Stack

### Core (already in `pyproject.toml`; no new dependency needed) [VERIFIED: pyproject.toml, .venv]
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 installed (`>=17.3,<18`) | `mark_price_kline_candlestick_data`, `kline_candlestick_data`, `exchange_information`, `ticker24hr_price_change_statistics`, `get_funding_rate_history` | Official connector, already behind the adapter |
| Polars | 1.44.2 installed (`>=1.44,<2.0`) | Parquet write/read, frame ops | Existing store code; verified byte-identical output for identical frames within one version |
| DuckDB | 1.5.5 | Coverage views, gap detection SQL | Existing `coverage.py` |
| pyarrow | >=19 | Parquet engine | Existing |
| SQLAlchemy 2.0 + psycopg 3 | pinned | `symbol_metadata`, watermarks, gaps | Existing |
| tenacity | >=9 | Bounded retry with jitter | Existing paginator |
| structlog | >=25 | Lineage events | Existing |
| httpx | `>=0.28,<1` | Archive download (project-declared client for SDK gaps) | Already a dependency; `respx` (dev) mocks it |
| stdlib `tomllib`, `zipfile`, `csv`, `hashlib`, `argparse`, `os.replace` | 3.13 | Collect list, archive parse, checksum, atomic publish | No dependency, no hand-rolled parsers |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `src.domain.canonical.sha256_hex` | in repo | Canonical JSON hash for dataset identity and freeze report | Every 64-hex identity in this project already uses it |
| `scripts.decision_alignment.universe.compute_content_sha256` | in repo | Manifest hash | Freeze step (D-09); reuse verbatim, never re-implement |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| REST as bulk 1m source | data.binance.vision monthly zips | ~10x faster and no weight cost; needed anyway for delisted fallback. Locked D-04 wraps `backfill_universe` (REST), so archive is the fallback and an optional accelerator, not the default |
| Per-file byte hash for dataset identity | Logical row hash | Byte hash is stable for immutable files on disk; logical hash survives a Polars version change. Recommend byte hash (D-18 says per-file content hash) and treat a re-written dataset as a new dataset |
| `tomli_w` to write the manifest | Line-level replace of `status`, `selection_date`, `symbols`, `content_sha256` | The manifest header carries the freeze procedure comments; a TOML writer would drop them. No new dependency |

**Installation:** none. **Version verification:** installed versions read from `.venv` this session (`importlib.metadata` gave `17.4.0` for the SDK; `pl.__version__` gave `1.44.2`).

## Package Legitimacy Audit

No new external packages are recommended for this phase. Every library above is already declared in `pyproject.toml` and locked in `uv.lock`; the archive download uses the already-declared `httpx`, tests use the already-declared `respx`.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none added) | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                   +-----------------------------+
                   | docs/research/universe/     |
                   | collect-list-v1.toml (D-02) |
                   +--------------+--------------+
                                  | load, refuse empty
                                  v
   Binance REST ----> collector loop (OI 5min, funding sweep, per-symbol isolation)
   (fapi)                         |  watermark + gap rows (PostgreSQL)
                                  v
                       data/raw/data_class=oi|funding/...   (immutable ticks)

   Binance REST  --+                      +--> dataset selector: trade | mark
   (klines,        |   backfill CLI       |
    markPrice-     +-> (metadata first) --+--> per-symbol [start=max(depth,onboard),
    Klines,        |   -> backfill_universe        end=min(day_floor(now), deliveryDate)]
    fundingRate)   |          |
                   |          v
   data.binance.   |   Kline / MarkKline -> check_batch (zero-trade OK, OHLC strict)
   vision (zip +   +--------> closed-day buffer -> publish_batch
   .CHECKSUM)  fallback        (tmp -> fsync -> os.replace, no-overwrite guard)
                                  |
                                  v
        data/raw/interval=<TF>/symbol=<S>/date=<D>/part.parquet          (trade)
        data/raw/dataset=mark_klines/interval=<TF>/symbol=<S>/date=<D>/part.parquet (mark)
                                  |
              +-------------------+--------------------+
              v                                        v
   coverage (DuckDB views, gap ranges)        case-input builder (adapter-side)
              |                               sorted file list + per-file sha256
              v                                -> dataset_id (64-hex) -> data_snapshot_id
   data-sufficiency report (D-05,                       |
   per symbol / interval / split)                       v
                                          simulator case_input dict + ExperimentRecord

   freeze CLI (--freeze only): exchangeInfo + archive listing (candidates) -> 1d quote volume
   -> rank -> print proposed manifest -> write manifest + FROZEN_CONTENT_SHA256 (same commit)

   paper supervisor drop/rotation:  backfill_missed_closes -> record_close -> resubscribe (D-16)
```

### Recommended Project Structure
```
src/data/
├── collect_list.py      # load + validate collect-list-v1.toml (refuse empty, SYMBOL_RE, dedupe, sorted)
├── backfill.py          # + dataset selector, per-symbol start/end bounds, closed-day clamp, windows param
├── backfill_cli.py      # python -m src.data.backfill_cli  (metadata first, depth flags, sufficiency report)
├── archive.py           # data.binance.vision list/download/verify/parse -> Kline/MarkKline
├── mark.py or quality.py# MarkKline dataclass frame + validator (no volume requirement)
├── store.py             # atomic publish, dataset root parameter
├── universe_freeze.py   # candidate discovery, ranking, proposed manifest, --freeze writer
└── case_input.py        # Parquet -> case-input builder + dataset identity (adapter-side)
docs/research/universe/collect-list-v1.toml     # D-02 (operational input, not FROZEN)
docs/research/universe/research-universe-v1.freeze-report.json  # ranking evidence, unavailable symbols
tests/  test_store_atomic.py, test_backfill_closed_day.py, test_mark_klines.py, test_collect_list.py,
        test_backfill_cli.py, test_archive_ingest.py, test_universe_freeze.py, test_case_input_builder.py
```

### Suggested plan slicing (planner may adjust)
1. **Plan 1 (Wave 1, independent, D-03):** collect list + collector wiring (`--universe` default from the list, `--healthcheck` uses the same list) + Dockerfile `COPY docs/research/universe` + loop-period fix + tests. Ships alone.
2. **Plan 2 (Wave 1):** store/quality/backfill hardening (D-13, D-14, D-15) and rewrite of the tests that assert partial-day publish. Must land before any long backfill.
3. **Plan 3 (Wave 1):** supervisor ordering (D-16), independent of the data plans.
4. **Plan 4 (Wave 2):** mark-price kline adapter method, `MarkKline` schema/validator, dataset selector in the paginator.
5. **Plan 5 (Wave 2):** archive ingestion (checksum-verified) used as the delisted fallback.
6. **Plan 6 (Wave 3):** backfill CLI (metadata first, depth flags, per-symbol bounds, funding history, sufficiency report) and `refresh_symbol_metadata` for delisted symbols.
7. **Plan 7 (Wave 3):** universe freeze CLI + freeze report + the operator checkpoint that runs it (human-action: network, hours of backfill, then a commit).
8. **Plan 8 (Wave 3):** case-input builder + dataset identity + coverage gap ranges.
9. **Plan 9:** docs (SOURCES "Facts verified for Phase 13", DATA_MODEL mark-kline dataset + dataset identity, CONFIGURATION collector universe/depth, BINANCE.md endpoint, DECISIONS row).

### Pattern 1: Closed-day publish (D-13, F-402)
**What:** Clamp every backfill's `end_ms` to the start of the current UTC day and drop rows with `open_time >= end_ms` from each page before buffering. Everything the loop flushes is then a closed day by construction; intra-day exchange holes stay warn-only gaps (D-15: a missing bar is a gap).
**When:** always, in `backfill_symbol_interval` (the single choke point, covers direct callers and `backfill_universe`).
**Why the filter matters:** a 1000-row page of 1m bars is 16.7 h, so the last page routinely crosses `end_ms`; the current loop only filters `close_time <= now_ms` (`backfill.py:340-342`), so with a clamped `end_ms` alone, bars of the current day would still be buffered and published.
```python
# Sketch (src/data/backfill.py) - Source: derived from backfill.py:301-342 + audit F-402 recommendation
day_end_ms = align_to_day_start_ms(now_ms)          # start of the current UTC day, integer math
end_ms = min(end_ms, day_end_ms)
...
closed = [k for k in raw_page
          if int(k.close_time_utc.timestamp() * 1000) <= now_ms
          and int(k.open_time_utc.timestamp() * 1000) < end_ms]
```
Note the first and last day of a symbol's life are legitimately partial (listing mid-day, delivery mid-day). "All expected bars exist" in D-13 must be read as "the day has ended and the fetch covered through its end"; a hard 1440-bar completeness rule would leave a listing day unpublishable and stall the cursor.

### Pattern 2: Atomic immutable publish (D-14, F-408)
```python
# Sketch (src/data/store.py) - keeps the existing FileExistsError guard at store.py:83-87
tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")   # same directory => same volume => atomic
try:
    group_to_write.write_parquet(tmp)
    with open(tmp, "rb+") as fh:
        os.fsync(fh.fileno())
    if path.exists():                                     # no-overwrite guard stays
        raise FileExistsError(...)
    os.replace(tmp, path)
finally:
    tmp.unlink(missing_ok=True)
```
`os.replace` overwrites an existing target silently on Windows and POSIX (verified: replace over an existing file succeeded here), so the `exists()` guard before it is what preserves immutability; a single writer process is assumed. Tmp name starts with `.` and does not match the `date=*/part.parquet` glob used by `coverage_v1.sql`, so a leftover tmp never reaches DuckDB. Readers must glob `part.parquet` explicitly, never scan the directory. The same helper should be reused by the collector's three tick writers (audit F-408 lists `collector.py:170-181, 209, 239, 269, 514-525`), otherwise the F-408 fix is half done.

### Pattern 3: Mark-kline dataset
Schema: `open_time_utc`, `close_time_utc`, `open`, `high`, `low`, `close` (`Decimal(scale=8)`), `interval`, `symbol`. No `volume`, `quote_volume`, `trade_count` (rows carry `"0"`, `"0"` and a price-update count that is not a trade count). Validator: duplicates, OHLC validity, regressions, negative prices, bad durations, mixed keys, gaps warn-only (same as `check_batch` minus the volume/trade checks). Partition root: `data/raw/dataset=mark_klines/interval=<TF>/symbol=<S>/date=<D>/part.parquet` so that (a) `candles_v1` (`data/raw/interval=*/...`) does not match it, (b) the default backup root `DEFAULT_PARQUET_ROOT = Path("data") / "raw"` (`backup.py:58`) and the Compose `rawdata:/app/data/raw` volume both cover it. A sibling root such as `data/mark_klines` would silently escape both. `partition_file(raw_root, ...)` already takes the root as a parameter, so `raw_root=DEFAULT_RAW_ROOT / "dataset=mark_klines"` reuses it unchanged.

Adapter method (mirrors `klines`, `binance_usdm.py:548-576`):
```python
# Source: SDK 17.4.0 market_data_api.mark_price_kline_candlestick_data (GET /fapi/v1/markPriceKlines)
response = await asyncio.to_thread(
    self._sdk.rest_api.mark_price_kline_candlestick_data,
    symbol=symbol, interval=interval,  # type: ignore[arg-type]
    start_time=start_ms, end_time=end_ms, limit=limit)
raw = response.data()   # list[list], verified against a recorded live response
return [_row_to_mark_kline(symbol, interval, row) for row in raw]  # OHLC + times only
```
Mark-kline bounds: bound each symbol's mark backfill start/end to the trade-kline range. Live probe: FTTUSDT mark klines begin 2022-04-14T00:00Z although `onboardDate` is 2022-04-14T07:00Z, and mark klines continue after delivery (FTT bars at 1668400020000 > delivery 1668398400000). Unbounded, the mark dataset would contain pre-listing and post-delisting rows the trade dataset lacks.

### Pattern 4: Backfill CLI shape (D-04, D-05)
Order: (1) `adapter.exchange_info()` -> `refresh_symbol_metadata(session, filters, universe=collect_list ∪ manifest symbols)`; (2) derive per-symbol `[start, end)`: `start = align_to_day_start(max(run_now - depth, onboard))`, `end = min(day_floor(now), deliveryDate_day_end)` for non-TRADING symbols; (3) for each dataset (trade, mark) and interval call the paginator with a dataset-specific `CursorStore` root (the cursor file name is `{symbol}_{interval}.cursor` and would collide between trade and mark); (4) funding history (see Pitfall 9); (5) sufficiency report. `backfill_universe` needs new keyword parameters (`windows_ms` override, per-symbol start floor, per-symbol end cap, dataset/fetch selector) because today it hard-codes `DEFAULT_BACKFILL_WINDOWS_MS` and one `end_ms` for all symbols (`backfill.py:557-561, 598-660`). Keep the existing signature working (defaults unchanged) so `test_backfill.py` keeps passing.

Sufficiency report (D-05): per `(symbol, interval)`: `expected_bars` (from `max(depth_start, onboard)` to effective end, integer math), `have_bars` (DuckDB count), `missing_bars`, `cause` in {`ONBOARD_LIMITED` (info, exit 0), `NOT_BACKFILLED` / `GAP` (missing data, exit non-zero), `DELISTED_CAPPED` (info)}. Also report, on the 2-year 1H/4H timeline, which of the 40/40/20 split blocks have 1m coverage (see Pitfall 7). It never mentions or lowers the trade floor beyond stating it cannot be measured yet.

### Pattern 5: Freeze CLI (D-06..D-09)
1. `dataset_start = run_date - 2 years` (UTC date), computed once and printed; ranking window = `[start-30d, start-1d]` (30 daily bars, all required).
2. Candidates = exchangeInfo symbols with `contractType == "PERPETUAL"`, `quoteAsset == "USDT"`, any status, plus archive-only symbols (see Pitfall 5), each validated against `SYMBOL_RE` before use in a path or URL.
3. Daily quote volume: REST 1d klines (`limit=30`, weight 1) first; on `-1121` or an empty window fall back to the archive 1d zip (monthly then daily). Record the source per symbol.
4. Rank by mean daily `quote_volume` (Decimal sum / 30, no rounding), ties by symbol ascending (deterministic), take `top_n = 12`. A symbol without all 30 bars is ineligible; a symbol delisted before `start` has no window and is ineligible.
5. Print the proposed manifest, per-candidate ranking evidence and every symbol whose data is **unavailable** (list, never drop). Data unavailability must not change the ranking; if a top-12 symbol is unavailable the manifest still lists it (the validator requires `len(symbols) == top_n` and 10..15 symbols, `universe.py:122-125`) and the report carries the gap for the user's decision.
6. `--freeze` only: write `status`, `selection_date`, `symbols`, `content_sha256` into the manifest by line-level replace (keeps the header), then set `FROZEN_CONTENT_SHA256` in `scripts/decision_alignment/universe.py` by regex replace of `FROZEN_CONTENT_SHA256: str | None = None`, both via tmp + `os.replace`, and update `tests/test_decision_alignment_universe.py::test_real_manifest_is_draft_with_empty_freeze_fields` (it asserts DRAFT and will fail after a real freeze) in the same commit. Write the ranking evidence to a sidecar `research-universe-v1.freeze-report.json` under `docs/research/universe/` (it must not be inside the hashed payload: `compute_content_sha256` hashes only the fields listed at `universe.py:83-95`).

### Pattern 6: Case-input builder and dataset identity (D-17..D-19)
- Read an explicit sorted list of `part.parquet` paths (never a directory scan), `pl.read_parquet(files)`, sort by `open_time_utc`, project columns in a fixed order, emit dicts with Decimal-as-str values and `datetime.isoformat()` timestamps (the simulator builds its intrabar key from `bar.close_time_utc.isoformat()` at `simulator.py:901`, so the builder must produce keys with the same `isoformat()` of the same datetime).
- Dataset identity = `sha256_hex({"files": [{"path": <posix rel path>, "sha256": <sha256 of file bytes>}, ...sorted by path]})`; it is a 64-hex string, so it drops straight into `ExperimentRecord.data_snapshot_id` (validated 64-hex, `experiment.py:76-82, 125-135`). Same files in, same hash out; any changed partition changes it.
- Gap policy (D-19): `coverage.py` only computes a gap **count** per (symbol, tf) over the whole span (`_gap_count_for_range`, `coverage.py:256-277`), not ranges. Add one gap-range function (DuckDB `lag()` over `open_time_utc` restricted to the requested range) in `coverage.py` so the definition of "unresolved gap" lives in one place; the builder calls it and raises a project exception unless the gap is in the caller's `allow_gaps` list, which is copied onto the output.
- Placement: `src/backtest/__init__.py` states the package imports nothing from Polars/pandas/NumPy and that lifting the rule needs an explicit decision. Put the builder in `src/data/case_input.py` and let it only produce plain dicts/dataclasses; `src/backtest` never imports it. If the user insists on `src/backtest/` (D-17 wording), the plan must state it lifts that package rule for one non-barrel module and keep it out of the `SCANNED_FILES` list of `test_domain_no_float.py` only if it needs float-free exemptions (it should not; keep it float-free).
- Return a typed frozen dataclass (`CaseInputData`: `strategy_bars`, `context_bars`, `intrabar_1m`, `mark_bars_1m`, `dataset_id`, `allowed_gaps`) with a `to_case_input(**scenario_fields)` that merges with the scenario dict (`account_state`, `constraint_snapshot`, `cost_model`, ...). The current simulator reads only its known keys, so an extra `mark_price_bars` key is inert until Phase 14.
- Scale: the simulator parses `intrabar_1m_map` eagerly (`_parse_intrabar_map`, `simulator.py:335-343`); a full year for one symbol is ~8,760 keys x 60 candles = 525,600 candle dicts. Build per (symbol, walk-forward window), not per universe-year.

### Pattern 7: Supervisor ordering (D-16, F-413)
Target order inside `_resubscribe_and_backfill`: close old handles -> `backfill_missed_closes` per pair -> `record_close(...)` for each backfilled close -> `self.start()` (resubscribe) -> optional short verification pass. Today it does `self._close_all_handles()` then `self.start()` at `supervisor.py:242-243` and only then backfills (`supervisor.py:263`). Reordering alone does not fully remove the seam: a bar that closes between the backfill's `now` and the WS attach can be missed, and WS klines can still duplicate a backfilled bar. Add a monotonic guard in `_on_kline` (drop a closed kline whose `close_time_utc <= _last_close[(symbol, interval)]`) so duplicates are dropped by construction, and record backfilled closes so `_last_close` advances (audit F-413 notes they currently do not). Test: fake WS and REST sharing one `calls` list; drive `on_disconnect(scheduled=False)`; assert `["klines", "subscribe"...]` order and that a duplicate WS kline for an already-backfilled bar is not dispatched. The existing fixtures (`_FakeWsAdapter`, `_FakeRestAdapter` in `tests/test_paper_supervisor_backfill.py`) already record calls per object and just need a shared log.

### Anti-Patterns to Avoid
- **Publishing a delisted symbol up to "now":** REST returns synthetic flat zero-trade bars forever after delivery; with D-15 they validate. Cap at `deliveryDate` / last bar with `trade_count > 0`.
- **Repairing a bad immutable file:** there is no in-place fix; a wrong partition needs a versioned supersede. Get the hardening (Plan 2) in before the first long backfill.
- **Reading the mark dataset through `candles_v1`:** different schema (no volume); keep the roots disjoint.
- **Sharing one `CursorStore` root between trade and mark datasets** (file name collision).
- **`float` anywhere in hash or price paths;** `timestamp() * 1000` float round-trips are used in `backfill.py`; new code should use the integer helper style of `resync._datetime_to_ms`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pagination, retry, rate-limit backoff | New paging loop | `backfill_symbol_interval` + `fetch_page_with_retry` (add a fetch selector) | Cursor resume, dedup, structural-rejection budget already tested |
| Canonical hashes | New JSON hashing | `src.domain.canonical.sha256_hex` and `compute_content_sha256` | Byte-stable rules already fixed and pinned |
| Zip/CSV/checksum | Custom archive parser | `zipfile` + `csv` + `hashlib.sha256` against the `.CHECKSUM` file | Format verified live: `<sha256>  <filename>` |
| TOML reading | Custom parser | `tomllib` | Stdlib |
| Atomic file swap | Custom rename dance | `os.replace` (same directory) | Atomic on POSIX and Windows |
| Gap/continuity SQL | Python loops over rows | DuckDB `lag()` over the Parquet view | Existing `coverage.py` views |
| Kline row parsing | New parser | `_row_to_kline` shape (12-field list) | Same wire format for trade and mark |
| Manifest validation | New validator | `scripts.decision_alignment.universe.validate_manifest` on the proposed doc before writing | Guarantees the freeze output passes UN-01..UN-05 |
| Backup of new data | New backup path | Keep datasets under `data/raw` | `src/ops/backup.py` default root + Compose volume |

**Key insight:** Nearly every piece exists; the phase is about choke points (one publish function, one predicate, one paginator) and about the exchange facts (delisted behavior, delivery cap) that make naive reuse produce silently wrong immutable data.

## Common Pitfalls

### Pitfall 1: Synthetic bars after delivery pass validation once zero-trade is allowed
**What goes wrong:** Backfilling a `SETTLING`/removed symbol to now publishes years of flat `open=high=low=close`, volume 0, trades 0 bars. **Why:** verified live: FTTUSDT (delivered 2022-11-14, `deliveryDate` 1668398400000) returns `[1672531200000,"1.5900","1.5900","1.5900","1.5900","0.0",...,0,...]` in 2023, 2025 and 2026; DENTUSDT 1d bars after its 2026-04-21 delivery are flat zeros. **Avoid:** end cap = `min(day_floor(now), deliveryDate)` from exchangeInfo for non-TRADING symbols; for symbols absent from exchangeInfo, end at the archive's last file and drop trailing all-zero bars. Add a test with a fake adapter that keeps returning flat bars past `deliveryDate`. **Warning sign:** any symbol whose last N days are all-flat zero-trade.

### Pitfall 2: REST does not serve every delisted symbol
**What goes wrong:** freeze cannot rank or backfill symbols that answer `{"code":-1121,"msg":"Invalid symbol."}`. **Why:** verified live 2026-09-30: `klines` returns data for FTTUSDT, SCUSDT, RAYUSDT, OMGUSDT, MKRUSDT, DENTUSDT (all `SETTLING` in exchangeInfo) and for LUNAUSDT, EOSUSDT, MATICUSDT (not in exchangeInfo), but `-1121` for SXPUSDT, AERGOUSDT, BTCSTUSDT, BDXNUSDT. `markPriceKlines` and `fundingRate` still answered for SXP, AERGO, BTCST, BDXN (for AERGO and BDXN the mark series starts late, so its coverage is not a substitute for trade klines). **Avoid:** REST first, archive fallback per symbol, source recorded per symbol; classify a symbol **unavailable** only when both fail.

### Pitfall 3: exchangeInfo does not list every delisted symbol
**What goes wrong:** candidate discovery from exchangeInfo alone misses symbols that were tradable at the dataset start and later removed. **Why:** verified: 864 USDT symbols in the archive, 31 not in exchangeInfo; five have data after 2024-09-30: EOSUSDT (last daily file 2025-05-21), AERGOUSDT (2026-07-23), BTCSTUSDT (2026-07-29), SXPUSDT (2026-06-01), BDXNUSDT (2026-04-27); MATICUSDT and FRONTUSDT (both last file 2024-09-11) ended just before that date. **Avoid:** candidates = exchangeInfo PERPETUAL/USDT (all statuses) ∪ archive bucket prefixes under `data/futures/um/monthly/klines/` (S3 listing, `delimiter=/`, marker paging; 1,018 prefixes over two pages). Validate every prefix against `SYMBOL_RE` before use.

### Pitfall 4: The collect-list file is not in the Docker image
**What goes wrong:** the collector container cannot find `docs/research/universe/collect-list-v1.toml`, so it refuses to start (D-02) or, worse, falls back to `LIVE_5` silently. **Why:** the Dockerfile copies only `src`, `scripts`, `alembic.ini` (`Dockerfile:18-20`); there is no `.dockerignore` and no `docs` copy. **Avoid:** add `COPY docs/research/universe ./docs/research/universe` (or a read-only bind mount) and a `--collect-list` flag / env override; never fall back to `LIVE_5` on a missing file. The `--healthcheck` path builds its universe from `--universe` (default `list(LIVE_5)`, `collector.py:827, 865`); it must read the same list or the container reports healthy while checking 5 of 16 symbols (the HEALTHCHECK command itself is Phase 13.1).

### Pitfall 5: Collector loop period stretches with the universe
**What goes wrong:** `time.sleep(cadence)` after each tick (`collector.py:936`) means period = cadence + tick duration. With ~16-20 symbols polled sequentially (OI and funding per symbol, ~0.55 s per call measured from this machine), the period drifts ~10-25 s per cycle, which shows up as apparent gaps against the fixed 5-minute expectation (`build_oi_coverage` uses `DEFAULT_OI_INTERVAL_MS`). **Avoid:** sleep until the next cadence boundary (`cadence - elapsed`, floor to grid with the existing `_floor_to_cadence`). Small change, in Plan 1.

### Pitfall 6: `symbol_metadata` column widths
`contract_type` is `String(16)` and `status` `String(16)` (`models.py:70-71`); live exchangeInfo has `TRADIFI_PERPETUAL` (17 chars, 212 USDT symbols); the docs enum also lists `PERPETUAL_DELIVERING` (20) and `TRADING_CANCEL_ONLY` (19). SQLite ignores the length (masking it in tests), PostgreSQL raises. **Avoid:** the CLI always passes `universe=` (never insert the whole exchange), and add a test that a 17-char `contract_type` is filtered out rather than inserted. Widening the column would need an Alembic migration and is out of scope.

### Pitfall 7: 12-month 1m depth vs 2-year dataset and the 40/40/20 split
With `dataset_start = 2024-09-30` and end = run date, Development (first 40%) spans ~2024-09-30..2025-07-18, Validation fold 1 starts 2025-07-18, and 1m data starts ~2025-09-30. So all of Development and about the first 74 days of Validation have no 1m intrabar data, which the current simulator resolves by SL-first fallback and Phase 14 will treat as missing. **Avoid:** make the sufficiency report print 1m coverage per split block; surface the choice to the user (Open Question 1). Numbers here are arithmetic on the decided depths, not a measurement of the future dataset.

### Pitfall 8: Polars silently rounds Decimals beyond the frame scale
Verified: `pl.DataFrame({"a":[Decimal("1.123456789")]}, schema={"a": pl.Decimal(scale=8)})` yields `Decimal('1.12345679')`. The store uses `Decimal(scale=8)` for prices/volumes and `scale=10` for funding rates. Binance values observed are at most 8 decimals, but a quality-gate check `Decimal.as_tuple().exponent >= -8` (reject, do not round) makes silent precision loss impossible, which matters for hashed data.

### Pitfall 9: Funding history is not collected and the adapter cannot parse old rows
Two verified facts. (a) `async_funding_sweep` issues one call per symbol with `limit=1000` and no pagination, and fresh symbols bootstrap only 8 hours (`FUNDING_BOOTSTRAP_LOOKBACK_MS`, `collector.py:74`); 1000 rows is ~333 days at 3/day (probe: `startTime=2024-09-30` returned 1000 rows ending 2025-08-29). A 2-year funding history therefore needs a paginated backfill step (about 3 calls per symbol; the fundingRate limit is 500 per 5 min per IP shared with fundingInfo, so ~50 calls are trivial). (b) `adapter.funding_rate` raises `InvalidOperation` on historical rows whose `markPrice` is `""` (probe: FTTUSDT 2022 and BTCUSDT 2019-2020 rows; from 2024-09-30 none observed empty for BTC/EOS/MKR/DENT); treat `""` as `None` in the adapter. The builder (D-17) reads funding, and DATA-02 says "plus funding history", so the CLI should include the funding backfill even though D-04 names only klines (Open Question 3).

### Pitfall 10: OI is unrecoverable and endpoints reject non-TRADING symbols
`openInterestHist` keeps ~1 month only (probe: `limit=500` returned 31 rows; docs: "Only the data of the latest 1 month is available"). `openInterest` for a settling symbol returns `{"code":-4108,"msg":"Symbol is on delivering or delivered or settling or closed or pre-trading."}` (probe FTTUSDT), so a collect list containing a non-TRADING symbol would journal a gap row every tick forever. The collect list must only contain `TRADING` PERPETUAL USDT symbols (validate against exchangeInfo when generating). After the freeze, consider re-issuing the collect list as a superset that includes the frozen manifest symbols that are still TRADING: the collect list is current-volume based, the frozen universe is point-in-time (2024-09), so OI will exist only for their intersection unless the list is widened.

### Pitfall 11: Existing tests encode the old behavior
`tests/test_backfill.py::test_forming_candle_at_frozen_now_is_excluded` (frozen clock 01:01 UTC of the base day, expects one published bar) and `tests/test_tracer_slice.py::test_paginator_drops_forming_candle_at_frozen_clock` publish a partial current day; both must be rewritten (assert the current day is not published and the cursor is untouched). `tests/test_quality_gates.py` and the `Kline` factories use `trade_count=10`; add zero-trade cases. `tests/test_decision_alignment_universe.py:48` asserts the real manifest is DRAFT.

### Pitfall 12: Windows `os.replace` can hit a transient `PermissionError`
An antivirus or indexer scanning the fresh tmp file can hold a handle for a moment. Retry `os.replace` a few times with a short sleep on `PermissionError` (bounded), then fail closed. (`CursorStore.write` already uses `os.replace` with no retry, `backfill.py:169-176`.)

### Pitfall 13: `--freeze` and CI
The freeze needs the network and hours of data; it cannot run in CI. Plan it as a `checkpoint:human-action` with the CLI itself unit-tested on a temp copy of the manifest (both witnesses match, `validate_manifest` returns `[]`, second `--freeze` on a FROZEN manifest refuses).

## Code Examples

### Zero-trade acceptance (D-15, F-409)
```python
# Source: src/data/quality.py:174-184 currently reads (verbatim):
#   or k.volume < 0
#   or k.quote_volume < 0
#   or k.trade_count <= 0
# Change the last predicate to `k.trade_count < 0` and count zero-trade bars separately:
zero_trade_bars = sum(1 for k in klines if k.trade_count == 0)   # telemetry only, never a rejection
# QualityVerdict gains `zero_trade_bars: int = 0` (default keeps existing constructors valid)
```

### Archive fetch + verify (D-08)
```python
# Source: layout verified live 2026-09-30 (monthly/klines/FTTUSDT/1m/FTTUSDT-1m-2022-10.zip + .CHECKSUM)
BASE = "https://data.binance.vision/data/futures/um"
url = f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{yyyy_mm}.zip"
expected = (await client.get(url + ".CHECKSUM")).text.split()[0]      # "<sha256>  <filename>"
blob = (await client.get(url)).content
if hashlib.sha256(blob).hexdigest() != expected:
    raise ArchiveChecksumMismatch(url)                                 # fail closed
with zipfile.ZipFile(io.BytesIO(blob)) as z:
    name = z.namelist()[0]                                              # single CSV
    rows = list(csv.reader(io.TextIOWrapper(z.open(name), encoding="utf-8")))
# rows[0] is the header: open_time,open,high,low,close,volume,close_time,quote_volume,count,...
# timestamps are epoch ms (verified 2022 and 2026 futures files); map rows[1:] through _row_to_kline
```
The `.CHECKSUM` file comes from the same origin as the zip, so it proves transport integrity, not authenticity.

### Freeze writes (D-09)
```python
# Source: scripts/decision_alignment/universe.py:53 currently reads (verbatim):
#   FROZEN_CONTENT_SHA256: str | None = None
doc = tomllib.loads(new_manifest_text)
assert validate_manifest(doc) == []                       # UN-01 before anything is written
digest = compute_content_sha256(doc)                      # same routine as `python -m ...universe <path>`
witness_text = re.sub(r'^FROZEN_CONTENT_SHA256: str \| None = None$',
                      f'FROZEN_CONTENT_SHA256: str | None = "{digest}"', src, count=1, flags=re.M)
# write manifest and universe.py each via tmp + os.replace; operator commits both together
```

### Dataset identity (D-18)
```python
files = sorted(paths)                                      # explicit list, posix-relative to data/raw
entries = [{"path": p.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
dataset_id = sha256_hex({"files": entries})               # 64-hex -> ExperimentRecord.data_snapshot_id
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bootstrap 7d (1m) / 30d (1H,4H), no CLI | Explicit depth 12 months / 2 years with CLI, per-symbol bounds | This phase | 30 days of 4H is 180 bars, below EMA200 (audit F-906) |
| Last-price candles for SL/TP in backtest | Mark-price klines ingested (consumed in Phase 14) | D037 | Same trigger series as live `workingType=MARK_PRICE` |
| `LIVE_5` as collector universe | Config-driven collect list | This phase | OI history for the research universe starts accumulating |
| Docs enum lists 6 contract types | Live API also returns `TRADIFI_PERPETUAL` (212 USDT symbols) | observed 2026-09-30 | Must filter `contractType == "PERPETUAL"`; the Common Definitions page fetched today does not list `TRADIFI_PERPETUAL` |

**Deprecated/outdated:** `binance-connector` / `binance-futures-connector` (archived, per AGENTS.md); nothing from them may be used.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The delisted symbols in today's exchangeInfo `SETTLING` list and in the archive listing are the only sources needed; no top-12 symbol at 2024-09-30 will be unavailable in both REST and archive | Pattern 5, Pitfalls 2-3 | Freeze report lists an "unavailable" symbol and the user must decide; already handled by D-08, only the frequency is unknown |
| A2 | Per-call latency of ~0.55 s measured through this sandbox proxy is representative; the VPS will be faster | Runtime budget | Wall-clock estimates (below) are upper-ish bounds; weight budget is unaffected |
| A3 | Archive daily files appear about one day after the trading day (BTCUSDT 2026-09-29 daily existed on 2026-09-30; the 09-27 file's Last-Modified was 2026-09-28 08:18 GMT) | Archive ingestion | If lag grows, recent days must come from REST |
| A4 | Byte-identical Parquet output holds only within one Polars version (verified identical for two writes of the same frame in 1.44.2); another version may change bytes | Dataset identity | A re-generated dataset would hash differently, so it must be treated as a new dataset; immutable published files are unaffected |
| A5 | REST behavior for delisted symbols (which return data, which return -1121, endless flat bars) is stable enough to design around; Binance does not document it | Pitfalls 1-2 | The CLI must classify per symbol at run time, not from a hard-coded list |
| A6 | `data.binance.vision` `.CHECKSUM` files are published for every zip | Archive ingestion | Missing checksum should fail closed for that file (not assumed present in code) |
| A7 | The user prefers the builder outside the pure `src/backtest` package (D-18 says adapter-side) | Pattern 6 | If D-17 is read literally, the plan must explicitly lift the package rule |
| A8 | Depth extension to 24 months of 1m via the archive costs ~10x less wall-clock than REST | Open Question 1 | Estimate from file sizes (1.4 MB per 1m month) and call counts, not measured end to end |

## Open Questions

1. **1m depth vs the dataset split (needs a user decision, not blocking planning).**
   - Known: D-04 locks 1m at 12 months and 1H/4H at 2 years; the protocol splits the whole dataset 40/40/20 by time; the simulator falls back to SL-first without 1m.
   - Unclear: whether the user accepts that Development and early Validation have no intrabar data.
   - Recommendation: keep the locked 12 months as the CLI default, make `--depth-1m` overridable, have the sufficiency report print per-split 1m coverage, and note that extending to 24 months through the archive is about 24 monthly zips per symbol (1.4 MB each, no weight cost). Decide after seeing the report.
2. **Where the D-17 builder lives.** Literal `src/backtest/` conflicts with that package's no-Polars rule; recommended `src/data/case_input.py`. Confirm at plan review.
3. **Funding-history backfill scope.** Not named in D-04 but required by D-17 (builder reads funding) and DATA-02. Recommended: include it in the backfill CLI (paginated, `_write_funding_tick`, existing watermark), plus the empty-`markPrice` adapter fix.
4. **Collect list after freeze.** Current-volume list vs point-in-time frozen universe will differ; recommend re-issuing the list (v2) as a superset with the still-TRADING frozen symbols after the freeze commit.
5. **F-706 (clock validation) has no locked decision in CONTEXT.** Roadmap Phase 18 owns "clock checks". Recommendation: Phase 13 adds at most a warn-only server-time offset log at collector start (adapter `server_time`), and leaves order/approval gating to Phase 18; VPS chrony is Phase 13.1.
6. **`SymbolFilters.delivery_time_utc`.** The CLI needs `deliveryDate` (present in the live response: e.g. SCUSDT `SETTLING`, MKRUSDT `1757322000000`); the adapter dataclass lacks it. Recommendation: add an optional trailing field (default `None`, no test breakage), keep it out of PostgreSQL (no migration) and record it in the freeze report.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python (venv) | everything | yes | 3.13.15 | — |
| uv | env/lock | yes | 0.12.20 | — |
| Binance public REST (`fapi.binance.com`) | backfill, freeze, probes | yes (curl works through the sandbox proxy) | — | — |
| data.binance.vision (S3 listing + zips) | delisted fallback | yes | — | — |
| Python TLS to Binance from this sandbox | SDK live calls in dev | no (proxy CA fails verification in Python/requests; curl works) | — | Probe with curl or replay recorded responses; tests never hit the network anyway (D-20) |
| Docker CLI / Compose | Compose collector | CLI yes (29.5.3, Compose 5.1.4); daemon not running | — | Start Docker Desktop before running the collector; unit tests use SQLite, no Docker |
| PostgreSQL | real collector run, `refresh_symbol_metadata` | no local instance seen (`pg_isready` absent) | — | Compose `postgres:17-bookworm`; tests use SQLite in-memory |
| Disk | dataset | 70 GB free | — | — |

**Missing dependencies with no fallback:** none for planning. Executing the real backfill/freeze needs the Docker daemon (or another PostgreSQL) started by the operator.
**Missing dependencies with fallback:** Python-side live SDK calls from this sandbox (use recorded responses).

### Runtime budget (D-04) [measured/derived 2026-09-30]
| Job | Calls | Weight | Time at ~0.55 s/call (measured 0.53-0.65 s) |
|-----|-------|--------|------|
| 1m, 12 months, 1 symbol, limit 1000 | 526 | 2,630 | ~4.8 min |
| 1m, 12 months, 16 symbols (LIVE_5 ∪ top-15 today = 16) | 8,416 | 42,080 (17.5 min of full 2,400/min budget) | ~77 min; ~500 weight/min = 21% of the cap |
| Same for mark klines | 8,416 | 42,080 | ~77 min |
| 1H 2y (17,520 bars) + 4H 2y (4,380 bars), 16 symbols, both datasets | ~23 pages x 16 x 2 | ~3,700 | ~7 min |
| Freeze ranking: 1d, `limit=30` (weight 1), ~660-700 candidates | ~700 | ~700 | ~6-7 min |
| Funding history 2y, 16 symbols | ~50 | (own 500/5min limit) | <1 min |
| Storage | ~40 KB per 1m day file (measured: BTCUSDT 2026-09-27, 40,390 bytes) | | ~234 MB per 1m year for 16 symbols per dataset; ~58k files across both datasets |
Weight table [CITED: developers.binance.com Kline/Mark-Price-Kline pages via WebFetch 2026-09-30]: [1,100) = 1, [100,500) = 2, [500,1000] = 5, >1000 = 10; limit 1000 is the cost-optimal page size and is the existing `BackfillConfig.page_size` default. The 2,400/min IP limit is read from live `exchangeInfo.rateLimits` (`REQUEST_WEIGHT`, `MINUTE`, 1, 2400).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio (`asyncio_mode = "auto"`), respx for httpx mocking |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `addopts = "-q"`) |
| Quick run command | `.venv/Scripts/python -m pytest tests/test_backfill.py tests/test_quality_gates.py tests/test_tracer_slice.py tests/test_collector.py tests/test_metadata.py tests/test_coverage.py tests/test_paper_resync.py tests/test_paper_supervisor_backfill.py tests/test_decision_alignment_universe.py tests/test_backtest_experiment.py -q -p no:cacheprovider` (an 8-file subset of this ran in 23.7 s, all green, before any change) |
| Full suite command | `.venv/Scripts/python -m pytest -q -p no:cacheprovider` (not timed this session) |
| Static gates | `.venv/Scripts/python -m ruff check src tests` and `.venv/Scripts/python -m mypy src` (mypy strict; not run this session) |

### Phase Requirements -> Test Map
| Req / Decision | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01/D-02 DATA-02 | Collect list loads sorted/deduped; empty list, missing file, bad symbol rejected; collector default universe and healthcheck use it; never falls back to LIVE_5 | unit | `pytest tests/test_collect_list.py tests/test_collector.py -q -p no:cacheprovider` | Wave 0 (new) + extend |
| D-13 DATA-01 | Current UTC day never published; rows with `open_time >= end_ms` dropped; resume after interrupted run publishes only new closed days; first/last partial day of a symbol life is published | unit (async, fake adapter) | `pytest tests/test_backfill_closed_day.py tests/test_backfill.py -q -p no:cacheprovider` | Wave 0 (new) + rewrite 2 tests |
| D-14 DATA-01 | Interrupted write (monkeypatch `write_parquet` to raise after partial bytes, and `os.replace` to raise) leaves no `part.parquet` and no tmp; re-run succeeds; existing file still raises `FileExistsError` | unit | `pytest tests/test_store_atomic.py -q -p no:cacheprovider` | Wave 0 (new) |
| D-15 DATA-01 | Zero-trade bar accepted (`structural_ok`), counted as telemetry; negative volume, OHLC violation, duplicate still rejected; missing bar is a gap not a zero bar | unit | `pytest tests/test_quality_gates.py -q -p no:cacheprovider` | extend |
| D-11 | Mark-kline row parse (recorded live sample), schema has no volume, validator, dataset root disjoint from `candles_v1`, backup round-trip includes `dataset=mark_klines` | unit | `pytest tests/test_mark_klines.py tests/test_backup.py -q -p no:cacheprovider` | Wave 0 (new) + extend |
| D-04/D-05 DATA-01 | CLI runs metadata first, per-symbol start/end bounds, delisted cap at `deliveryDate` (fake adapter keeps returning flat bars), resume from cursor, sufficiency report causes and exit codes | unit (async) | `pytest tests/test_backfill_cli.py -q -p no:cacheprovider` | Wave 0 (new) |
| D-08 archive | Zip + CHECKSUM verify, mismatch fails closed, CSV header skipped, ms timestamps, feeds `check_batch`/`publish_batch`; symbols validated against `SYMBOL_RE` | unit (respx) | `pytest tests/test_archive_ingest.py -q -p no:cacheprovider` | Wave 0 (new) |
| D-10 DATA-03 | Metadata rows for SETTLING and PENDING_TRADING symbols in the universe; TRADIFI_PERPETUAL (17 chars) filtered by `universe`; versioned insert, no update; adapter parses a recorded 6-symbol exchangeInfo fixture including `deliveryDate` | unit (SQLite) | `pytest tests/test_metadata.py -q -p no:cacheprovider` | extend + new fixture |
| D-06..D-09 | Ranking: 30 full bars required, tie-break by symbol, top 12, delisted-later included, unavailable listed not dropped; proposed manifest passes `validate_manifest`; `--freeze` writes manifest + witness that match; refuses to re-freeze; `test_real_manifest_is_draft...` updated | unit | `pytest tests/test_universe_freeze.py tests/test_decision_alignment_universe.py -q -p no:cacheprovider` | Wave 0 (new) + update |
| D-17..D-19 BKTS-02 | Builder output deterministic (byte-equal across two builds, sorted, fixed columns); gap raises unless allowed and allow-list recorded; current day excluded; intrabar keys match simulator key format; dataset hash stable and changes with any file change; `assemble()` accepts it as `data_snapshot_id` | unit | `pytest tests/test_case_input_builder.py tests/test_backtest_experiment.py -q -p no:cacheprovider` | Wave 0 (new) |
| D-16 | Unsolicited drop: order of calls is backfill then subscribe; duplicate WS kline for a backfilled bar not dispatched; `_last_close` advances from backfilled closes | unit | `pytest tests/test_paper_supervisor_backfill.py tests/test_paper_resync.py -q -p no:cacheprovider` | extend |
| Funding | Empty `markPrice` row parses as `None`; paginated funding backfill advances watermark, no duplicate ticks | unit | `pytest tests/test_collector.py -q -p no:cacheprovider` | extend |
| DATA-04 | Existing backup/drill still green; bundle includes the mark-kline subtree | unit | `pytest tests/test_backup.py -q -p no:cacheprovider` | extend |

### Sampling Rate
- **Per task commit:** the single test file the task touched plus `tests/test_domain_no_float.py` when a scanned package is touched.
- **Per wave merge:** the quick-run subset above.
- **Phase gate:** full suite, `ruff check`, `mypy src`, and `python scripts/verify_decision_alignment.py` (gate suite includes UN-01..UN-05) green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_collect_list.py`, `tests/test_store_atomic.py`, `tests/test_backfill_closed_day.py`, `tests/test_mark_klines.py`, `tests/test_backfill_cli.py`, `tests/test_archive_ingest.py`, `tests/test_universe_freeze.py`, `tests/test_case_input_builder.py`
- [ ] Fixtures: trimmed exchangeInfo (about 6 symbols: TRADING BTCUSDT, SETTLING with `deliveryDate`, PENDING_TRADING, TRADIFI_PERPETUAL, a quarterly, a USDC) derived from the recorded live response; recorded `markPriceKlines` sample (2 rows, verbatim above: `[1790770020000,"83751.55144203",...,"0",1790770079999,"0",60,"0","0","0"]`); recorded funding sample with `"markPrice":""`; a zip + `.CHECKSUM` built in-test with `zipfile`
- [ ] Shared fake adapter that supports `klines`, `mark_klines`, `exchange_info`, `funding_rate` (current fakes are per-file)
- [ ] Rewrite `test_forming_candle_at_frozen_now_is_excluded` and `test_paginator_drops_forming_candle_at_frozen_clock`; update `tests/test_decision_alignment_universe.py::test_real_manifest_is_draft_with_empty_freeze_fields` in the freeze commit
- No framework install needed.

## Security Domain

`security_enforcement` is enabled (ASVS level 1, block on high) [VERIFIED: .planning/config.json].

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (public market-data endpoints only, no keys) | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Regex allow-list `^[A-Z0-9]+USDT$` for every symbol taken from an external listing or file before it enters a path, URL or SQL parameter; `tomllib` for config; strict schema on CSV/JSON rows (fail closed, never coerce) |
| V6 Cryptography | yes (integrity only) | `hashlib.sha256` for archive checksum and dataset identity; never hand-rolled |
| V8 Data Protection | partial | No secrets in this phase; DB URL comes from env as today; keep credentials out of logs and error text |
| V12 Files / Resources | yes | Zip handling: read only `namelist()[0]` into memory, size-cap the download and the uncompressed size, never `extractall` to disk; tmp files in the target directory only |
| V13 API / Web | yes (client side) | HTTPS only; fixed hosts (`fapi.binance.com`, `data.binance.vision`, `s3-ap-northeast-1.amazonaws.com/data.binance.vision`); TLS verification stays on (do not disable to work around the sandbox proxy) |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal / injection via symbol names from the S3 XML listing or a config file | Tampering | Validate against `SYMBOL_RE` before use; build paths only from validated components |
| Corrupted or tampered archive zip | Tampering | Verify the `.CHECKSUM` sha256 (transport integrity only; it shares the origin with the zip) and then run the full `check_batch` gate; a mismatch or rejection publishes nothing |
| Zip bomb / oversized download | Denial of service | Byte cap on download and on decompressed CSV size; per-file timeout; bounded retries |
| Silent overwrite of published data | Tampering | Existing no-overwrite guard + atomic tmp/replace; dataset hash changes on any file change |
| Non-atomic freeze leaving manifest FROZEN with no witness (or the reverse) | Tampering / repudiation | Write both files via tmp + `os.replace`; validate the proposed manifest first; UN-02 fails loudly on a half state |
| Retry storm causing a 418 IP ban | Denial of service | Keep sequential pacing and bounded tenacity retries (existing); one process only |

## Sources

### Primary (HIGH confidence)
- Live probes against `https://fapi.binance.com` on 2026-09-30 (curl): `exchangeInfo` (919 symbols, `rateLimits`, statuses, `deliveryDate`), `markPriceKlines`, `klines`, `fundingRate`, `openInterest`, `openInterestHist`, `ticker/24hr`; recorded responses replayed through the installed SDK 17.4.0 and the project adapter (`exchange_info()` parsed all 919 symbols; `mark_price_kline_candlestick_data().data()` is `list[list]`; `funding_rate` raised `InvalidOperation` on `markPrice:""`)
- Live probes against `https://data.binance.vision` (S3 listing, monthly and daily zips, `.CHECKSUM` verified equal to the sha256 of the downloaded zip) on 2026-09-30
- Installed SDK source: `binance_sdk_derivatives_trading_usds_futures.rest_api.api.market_data_api` docstrings (`GET /fapi/v1/markPriceKlines`, weight tiers; `GET /fapi/v1/ticker/24hr`, weight 1 single / 40 all)
- In-repo files read this session: `src/data/{store,quality,metadata,backfill,collector,coverage}.py`, `src/sql/coverage_v1.sql`, `src/adapters/binance_usdm.py`, `src/paper/{supervisor,resync}.py`, `src/backtest/{__init__,binding,experiment}.py`, `src/backtest/simulator.py` (parse and intrabar sections), `src/domain/canonical.py`, `scripts/decision_alignment/universe.py`, `src/db/models.py`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `docs/research/universe/research-universe-v1.toml`, `tests/test_backfill.py`, `tests/test_paper_supervisor_backfill.py`, `tests/test_decision_alignment_universe.py`, `.planning/audits/2026-09-29-deep-audit/findings.json` (F-107, F-906, F-907, F-024, F-122, F-402, F-408, F-409, F-413, F-706)

### Secondary (MEDIUM confidence)
- [developers.binance.com Mark-Price-Kline-Candlestick-Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data) - path, weight tiers, params, limit max 1500 default 500, 12-field response (WebFetch summarised by a small model, fetched 2026-09-30)
- [developers.binance.com Kline-Candlestick-Data / Exchange-Information / Get-Funding-Rate-History / Open-Interest pages](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information) - weights, funding limit 1000 default 100 shared 500/5min/IP, `openInterestHist` 1-month window (WebFetch summaries; the Kline page fetch returned only a landing page, weights were read from the Mark-Price page, the Open-Interest page fetch and the SDK docstring)
- [developers.binance.com common-definition](https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition) - contract status enum incl. `SETTLING`, `PENDING_TRADING`, `TRADING_CANCEL_ONLY`; contract type enum (does not list `TRADIFI_PERPETUAL`, which the live API returns)
- [binance/binance-public-data README](https://github.com/binance/binance-public-data/blob/master/README.md) - `.CHECKSUM` per zip, SHA256 verification, kline column order; it does not document futures paths (paths verified by live probe)

### Tertiary (LOW confidence)
- None used for recommendations.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in `pyproject.toml`/installed; versions read from the venv
- Architecture: HIGH - every seam read in source; live behavior probed
- Pitfalls: HIGH for the verified exchange behaviors and code defects; MEDIUM for wall-clock estimates (sandbox proxy latency)
- Freeze outcome (which symbols rank top 12): not researched on purpose; that is a run-time result (Assumption A1)

**Research date:** 2026-09-30
**Valid until:** 2026-10-07 for delisted-symbol availability and archive listing facts (they change as Binance delists); 30 days for code seams
