---
phase: 02-data-foundation
plan: 02
type: execute
subsystem: data-foundation
tags: [ingestion, adapter, paginator, quality-gate, parquet, duckdb, cli, tdd]
dependency_graph:
  requires: [02-01]
  provides: [DATA-01-end-to-end-slice, candle-store-v1, coverage-cli-v1]
  affects: [02-03, 02-04, 02-05]
tech-stack:
  added: []
  patterns: [adapter-as-only-sdk-importer, fail-closed-quality-gate, hive-partitioned-parquet, duckdb-hive-partitioning-read, injectable-clock-for-tests]
key-files:
  created:
    - src/adapters/binance_usdm.py
    - src/data/backfill.py
    - src/data/quality.py
    - src/data/store.py
    - src/data/coverage.py
    - src/sql/coverage_v1.sql
    - tests/test_tracer_slice.py
    - tests/fixtures/kline_page_sample.json
  modified: []
decisions:
  - "Adapter owns the SDK import and exposes frozen `Kline`/`OiSnapshot`/`FundingTick`/`SymbolFilters` dataclasses with `Decimal` prices and UTC datetimes — SDK response models never leak into the domain/strategy layer (D-03)."
  - "Paginator runs SDK calls via `asyncio.to_thread` because the SDK is synchronous; the async paginator can interleave multiple symbols/intervals without blocking."
  - "Forming candle (close_time > now) is dropped BEFORE the quality gate runs — protects D-10 from inspecting an unclosed bar."
  - "Cross-page dedup: paginator tracks `seen_open_times` across pages within one backfill run so a boundary overlap lands in Parquet exactly once (Pitfall 2)."
  - "`pages` counter increments BEFORE `fetch_page_with_retry` so an exhausted-retry iteration is observable in `BackfillResult.pages`."
  - "DuckDB SQL view casts tz-aware Polars Datetime columns to naive TIMESTAMP (UTC) at the boundary — avoids the `pytz` runtime requirement while preserving correct values."
  - "Coverage CLI re-attaches UTC and converts to `Asia/Ho_Chi_Minh` ONLY at the print edge (D-06)."
  - "`.gitignore` keeps `src/data/` as a tracked source package while still excluding the runtime `data/` raw store (D-04)."
metrics:
  duration: ~1.5h
  completed_date: 2026-09-19
  tasks_completed: 2
  files_created: 8
  files_modified: 0
  commits: 2
  commits_actual: 2
  plan_head_before: 1311164e3ca571d92871825118ac4e9ad6c4d92c
status: complete
actuals:
  tokens: 32000
  tasks: 2
  commits: 2
---

# Phase 2 Plan 2: Tracer Slice — Adapter → Paginator → Quality → Store → CLI

## One-liner

End-to-end candle ingestion for BTCUSDT 1h with quality-gated Parquet publish, DuckDB-backed coverage CLI, and TDD coverage of the three acceptance behaviors.

## What was built

A production-quality tracer slice proving the ingestion architecture end-to-end on a single (symbol, interval) before horizontal expansion:

1. **Adapter** (`src/adapters/binance_usdm.py`) — the ONLY module importing `binance-sdk-derivatives-trading-usds-futures`. Exposes frozen dataclasses (`Kline`, `OiSnapshot`, `FundingTick`, `SymbolFilters`) with `Decimal` prices and UTC `datetime`s. SDK calls run via `asyncio.to_thread` so the async paginator can interleave fetches.

2. **Quality gate** (`src/data/quality.py`) — pure-function `check_batch` enforcing D-10 fail-closed posture: duplicates, OHLC violations, and timestamp regressions reject the batch; continuity gaps publish with flags.

3. **Store** (`src/data/store.py`) — immutable per-day Hive-partitioned Parquet publish under `interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet`. Republishing an existing file raises `FileExistsError` (D-04).

4. **Paginator** (`src/data/backfill.py`) — windowed paginator with forming-candle exclusion, cross-page dedup via `seen_open_times` set, injectable `clock` for deterministic tests, and `tenacity`-bounded retry on rate-limit errors.

5. **DuckDB view** (`src/sql/coverage_v1.sql`) — `candles_v1` and `coverage_v1` views over the Parquet hive layout; casts tz-aware datetimes to naive TIMESTAMP (UTC) at the boundary.

6. **CLI** (`src/data/coverage.py`) — prints per-symbol effective range from real Parquet files, converting to `Asia/Ho_Chi_Minh` at the display edge only.

7. **Tests** (`tests/test_tracer_slice.py` + `tests/fixtures/kline_page_sample.json`) — TDD coverage of forming-candle exclusion, cross-page dedup, and 429-retry-then-pace.

## Verification

All three plan-level verifies pass:

| Verify | Command | Result |
|--------|---------|--------|
| Coverage CLI | `uv run python -m src.data.coverage --symbol BTCUSDT` | prints `1h rows=25 start=... end=...` from real Parquet |
| Test suite | `uv run pytest tests/test_tracer_slice.py -q` | 4/4 passed in ~1.2s |
| SDK import isolation | `git grep -l "from binance_sdk_derivatives_trading_usds_futures" src/` | exactly one file (`src/adapters/binance_usdm.py`) |

Full suite: 7/7 passed (4 tracer + 3 wave0 sanity).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] DuckDB `pytz` requirement for tz-aware Parquet**
- **Found during:** Task 1 verification
- **Issue:** DuckDB requires `pytz` to read Polars-written tz-aware datetime columns as `TIMESTAMP WITH TIME ZONE`, even when no explicit timezone math is performed.
- **Fix:** Modified `src/sql/coverage_v1.sql` to `CAST(open_time_utc AS TIMESTAMP)` at the view boundary; the CLI re-attaches UTC and converts to `Asia/Ho_Chi_Minh` at the print edge.
- **Files modified:** `src/sql/coverage_v1.sql`, `src/data/coverage.py`

**2. [Rule 3 - Blocking] `.gitignore` `data/` matched `src/data/`**
- **Found during:** Task 1 commit staging
- **Issue:** The `data/` gitignore pattern matched both the runtime raw store AND the `src/data/` source package, preventing the tracer files from being committed.
- **Fix:** Added `!src/data/` exception after the `data/` rule.
- **Files modified:** `.gitignore`

**3. [Rule 2 - Missing critical] Cross-page dedup**
- **Found during:** Task 2 RED phase (TDD)
- **Issue:** The paginator processed each page independently; boundary overlaps would be published twice.
- **Fix:** Added `seen_open_times: set[int]` tracking across pages; rows already seen are skipped and counted in `duplicates_skipped`.
- **Files modified:** `src/data/backfill.py`

### Test Adjustments

**4. [Rule 1 - Bug] Test 1 frozen-clock placement**
- **Found during:** Task 2 RED phase
- **Issue:** The test placed the frozen clock 1 minute after `closed_open`, but the closed bar's close_time is `closed_open + 3_599_999` (1 hour later). This made the closed bar's close_time appear in the future relative to the clock, so both bars were dropped.
- **Fix:** Changed `frozen_at` to `forming_open + 60_000` so the clock sits inside the forming bar (1 minute after it starts).

**5. [Rule 1 - Bug] Test 3 `pages` assertion**
- **Found during:** Task 2 RED phase
- **Issue:** The test asserted `result.pages == 2` expecting the first failed fetch to be counted. But tenacity handles retries internally inside `fetch_page_with_retry`, so the paginator only sees one successful `fetch_page_with_retry` call.
- **Fix:** Changed assertion to `result.pages == 1` with a comment explaining that the retry is transparent at the paginator layer; the two adapter calls prove the retry happened.

## Auth Gates

None.

## Known Stubs

None — the tracer slice is complete and end-to-end functional.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `d05d10d` | feat | wire candle adapter + paginator + quality gate + Parquet store + coverage CLI |
| `2164979` | test | cover tracer slice with TDD tests + cross-page dedup |

## Next Steps

- 02-03 (funding + OI capture) can reuse the `BinanceUsdmAdapter.funding_rate()` and `open_interest()` methods that are already implemented but not yet exercised by the tracer.
- 02-04 (coverage tracking + gap-filling) can build on the `coverage_v1` view and the `duplicates_skipped` counter.
- 02-05 (exchange-info persistence) is the next plan in this wave.
