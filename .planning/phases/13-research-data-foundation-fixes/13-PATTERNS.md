# Phase 13: Research Data Foundation Fixes - Pattern Map

**Mapped:** 2026-09-30
**Files analyzed:** 22 (new and modified)
**Analogs found:** 22 / 22 (all in-repo tracked files; no `.gsd` mirror paths used)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/data/collect_list.py` (new) | config loader | file-I/O | `scripts/decision_alignment/universe.py` (tomllib + `SYMBOL_RE` validation) | role-match |
| `docs/research/universe/collect-list-v1.toml` (new) | config | file-I/O | `docs/research/universe/research-universe-v1.toml` | exact |
| `src/data/collector.py` (mod) | service/CLI | event-driven loop | itself (`main`, `_parse_collector_args`, `_check_health`) | exact |
| `Dockerfile` (mod) | config | build | itself (lines 18-20 COPY block) | exact |
| `src/data/store.py` (mod: atomic + dataset root) | utility | file-I/O | itself (`publish_batch`); `CursorStore.write` in `backfill.py` for `os.replace` | exact |
| `src/data/quality.py` (mod: zero-trade, MarkKline validator) | utility | transform | itself (`check_batch`, line ~174-184) | exact |
| `src/data/backfill.py` (mod: closed-day clamp, bounds, selector) | service | batch/paginated | itself (`backfill_symbol_interval`, `backfill_universe`) | exact |
| `src/data/backfill_cli.py` (new) | CLI | batch | `src/data/collector.py` `_parse_collector_args` + `main` | role-match |
| `src/adapters/binance_usdm.py` (mod: `mark_klines`, `ticker/server_time`, `deliveryDate`, empty `markPrice`) | adapter | request-response | itself: `klines` (548-576), `_row_to_kline` (495) | exact |
| `src/data/archive.py` (new) | service | file-I/O + request-response | `klines` adapter method + `_row_to_kline` (feeds `Kline`); httpx mocked via respx | partial |
| `src/data/metadata.py` (mod) | service | CRUD (versioned insert) | itself (`refresh_symbol_metadata`) | exact |
| `src/data/universe_freeze.py` (new) | CLI/service | batch + file-I/O | `scripts/decision_alignment/universe.py` (`validate_manifest`, `compute_content_sha256`) | role-match |
| `scripts/decision_alignment/universe.py` (mod: `FROZEN_CONTENT_SHA256`) | config | - | itself, line 53 | exact |
| `src/data/coverage.py` (mod: gap-range fn) | utility | DuckDB transform | itself (`_gap_count_for_range`, 256-277) | exact |
| `src/data/case_input.py` (new) | adapter/builder | file-I/O transform | `src/paper/freeze.py` (Parquet reader), `src/backtest/experiment.py` (`data_snapshot_id`) | role-match |
| `src/paper/supervisor.py` (mod) | service | event-driven | itself (`_resubscribe_and_backfill`, 230-275) | exact |
| `src/paper/resync.py` (mod?) | service | request-response | itself (`backfill_missed_closes`) | exact |
| tests: `test_store_atomic.py`, `test_backfill_closed_day.py`, `test_mark_klines.py`, `test_collect_list.py`, `test_backfill_cli.py`, `test_archive_ingest.py`, `test_universe_freeze.py`, `test_case_input_builder.py` (new) | test | - | `tests/test_backfill.py`, `tests/test_collector.py`, `tests/test_metadata.py`, `tests/test_paper_supervisor_backfill.py` | exact |
| tests rewritten: `test_backfill.py::test_forming_candle_at_frozen_now_is_excluded`, `test_tracer_slice.py::test_paginator_drops_forming_candle_at_frozen_clock`, `test_decision_alignment_universe.py::test_real_manifest_is_draft_with_empty_freeze_fields` | test | - | themselves | exact |
| docs: `docs/SOURCES.md`, `DATA_MODEL.md`, `CONFIGURATION.md`, integration doc | doc | - | existing sections | n/a |

## Pattern Assignments

### `src/data/collector.py` (Plan 1, collect-list wiring, loop drift, F-706 probe)

**Analog:** itself.

**Current LIVE_5 coupling to remove** (line 62, 824-829, 865):
```python
from src.data.backfill import LIVE_5

...
parser.add_argument(
    "--universe", nargs="+", default=list(LIVE_5), help="Symbols to poll (default: live-5)."
)
...
universe: list[str] = list(args.universe) or list(LIVE_5)
```
Replace default with `None`, add `--collect-list` (Path, default `docs/research/universe/collect-list-v1.toml`); `universe = args.universe or load_collect_list(args.collect_list)`. Never fall back to `LIVE_5` (Pitfall 4). `--healthcheck` at 866-871 already takes `universe=universe`, so the same loader feeds it.

**Loop drift fix** (line 936 `time.sleep(cadence)`): compute `elapsed` from the `observed` timestamp at loop top and sleep to the next grid boundary; reuse `_floor_to_cadence(dt, cadence_seconds)` (line 652).

**Main loop error style to keep** (lines 918-935): per-tick `try/except Exception: log.exception("collector.tick.failed")` and `finally: session.close()`. F-706 server-time probe: warn-only via `log.warning(...)` before the loop; no raise.

**Atomic writes for tick files** (F-408): `_guard_no_overwrite(path)` (line 170) then a direct write in `_write_oi_snapshot` (183), `_write_oi_research_snapshot` (213), `_write_funding_tick` (243). Route these through the shared atomic helper from `store.py`.

### `src/data/collect_list.py` (new)

**Analog:** `scripts/decision_alignment/universe.py` lines 40-60 (constants):
```python
SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
```
Use `tomllib`, validate each symbol against `SYMBOL_RE`, dedupe, return sorted tuple, raise a project `CollectListError` on empty or missing file. Do not import from `scripts/` (stdlib-only gate); duplicate the regex or import from a shared spot the planner picks. Test analog: `tests/test_collector.py` fixture style; add empty-list-rejected test (D-20).

### `Dockerfile` (mod)

**Analog:** lines 18-20:
```dockerfile
COPY src ./src
COPY scripts ./scripts
COPY alembic.ini ./
```
Add `COPY docs/research/universe ./docs/research/universe` before the `RUN useradd` line (no `.dockerignore` exists). Keep inside Phase 13 (HEALTHCHECK is 13.1).

### `src/data/store.py` (Plan 2, atomic publish D-14; dataset root)

**Analog:** itself, lines 80-91 (`publish_batch` tail):
```python
path = partition_file(raw_root, interval, symbol, day)
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    raise FileExistsError(f"refusing to overwrite immutable Parquet at {path} ...")
group_to_write = group.drop("__day")
group_to_write.write_parquet(path)
paths.append(path)
```
Change `write_parquet(path)` to tmp-in-same-dir (`.{name}.{pid}.tmp`, dot-prefixed so `date=*/part.parquet` globs ignore it), fsync, keep the `exists()` guard, `os.replace`, `finally: tmp.unlink(missing_ok=True)`, bounded retry on `PermissionError` (Pitfall 12). Extract a reusable `atomic_write_bytes/parquet` helper used by the collector tick writers. `partition_file(raw_root, ...)` already takes a root, so mark klines pass `DEFAULT_RAW_ROOT / "dataset=mark_klines"` (D-11/D-27). Crash test: monkeypatch `write_parquet` to raise mid-write, assert no `part.parquet` and no `.tmp`.

### `src/data/quality.py` (Plan 2 F-409; Plan 4 mark validator)

**Analog:** itself, `check_batch` lines 174-184:
```python
negative_values = sum(
    1
    for k in klines
    if k.open < 0
    or k.high < 0
    or k.low < 0
    or k.close < 0
    or k.volume < 0
    or k.quote_volume < 0
    or k.trade_count <= 0
)
```
Change `trade_count <= 0` to `< 0`; add `zero_trade_bars = sum(1 for k in klines if k.trade_count == 0)` as telemetry field on `QualityVerdict` with default `0`. Keep gap/OHLC/duplicate/regression/mixed-key checks (lines 160-200). Mark validator: copy `check_batch` minus volume/quote_volume/trade_count predicates; also reject `Decimal.as_tuple().exponent < -8` (Pitfall 8). Mark frame writer: sibling of `klines_to_frame` with columns `open_time_utc, close_time_utc, open, high, low, close, interval, symbol` at `Decimal(scale=8)`; tick count stored (if at all) as `price_tick_count`, never `trade_count` (D-29).

### `src/data/backfill.py` (Plans 2, 4, 6)

**Analog:** itself. Anchors: `BackfillConfig` (78-90), `align_to_day_start_ms` (93-111, integer math; reuse), `CursorStore` file `{symbol}_{interval}.cursor` (129-180, `os.replace`), `fetch_page_with_retry` (194), `backfill_symbol_interval` (231, closed filter at ~340-342), `LIVE_5` (549), `DEFAULT_BACKFILL_WINDOWS_MS` (557), `backfill_universe` (564-660).

Edits:
- Closed-day clamp (D-13): `end_ms = min(end_ms, align_to_day_start_ms(now_ms))` and add `open_time < end_ms` to the page filter (current filter is only `close_time <= now_ms`).
- `backfill_universe` new keyword args, defaults unchanged so `tests/test_backfill.py` still passes: `windows_ms: dict[str,int] | None`, per-symbol `start_floor_ms`/`end_cap_ms` mappings (onboard and `deliveryDate`, D-26), dataset/fetch selector (`trade` or `mark`, callable resolving to `adapter.klines` or `adapter.mark_klines`), and a `cursor_store` per dataset (trade and mark must not share a root).
- Use integer ms helpers (`resync._datetime_to_ms`) not `timestamp()*1000` in new code.

### `src/adapters/binance_usdm.py` (Plan 4 and 6)

**Analog:** `klines` (548-576) + `_row_to_kline` (495-521):
```python
response = await asyncio.to_thread(
    self._sdk.rest_api.kline_candlestick_data,
    symbol=symbol,
    interval=interval,  # type: ignore[arg-type]
    start_time=start_ms,
    end_time=end_ms,
    limit=limit,
)
raw = response.data()
return [_row_to_kline(symbol, interval, row) for row in raw]
```
Add `mark_klines(...)` with `mark_price_kline_candlestick_data` and `_row_to_mark_kline` (OHLC + times only). Add `SymbolFilters.delivery_date_ms: int | None = None` as an optional trailing field (no migration, D-26), map from exchangeInfo `deliveryDate`. In `funding_rate`, treat `markPrice == ""` as `None` (Pitfall 9). Add `server_time` and a paginated funding-history helper (or loop in CLI). SDK types stay inside the adapter.

### `src/data/metadata.py` (Plan 6, D-10, D-29)

**Analog:** itself, lines 36-90: versioned insert only (`session.add(SymbolMetadata(...))`, then `session.commit()`), optional `universe` filter (`if universe_set is not None and f.symbol not in universe_set: continue`). The CLI always passes `universe=` (collect list plus manifest symbols) so `TRADIFI_PERPETUAL` (17 chars > `String(16)`) rows are never inserted. Include SETTLING and non-TRADING statuses for manifest symbols. Test analog: `tests/test_metadata.py`; add a 17-char `contract_type` filtered-out test.

### `src/data/backfill_cli.py` (new, Plan 6)

**Analog:** `collector.py` lines 815-862 (`_parse_collector_args` with `prog="python -m src.data.collector"`, `Path` args with defaults, `--database-url` default None with env fallback via `_resolve_database_url` 625 / `_make_sync_engine` 647), and `main(argv) -> int` returning exit codes (2 for config error, print to stderr). Order per RESEARCH Pattern 4: metadata refresh, then per-symbol bounds, trade then mark per interval, funding history, sufficiency report. Exit non-zero only for missing-data causes (`NOT_BACKFILLED`, `GAP`), never for `ONBOARD_LIMITED` or `DELISTED_CAPPED`. Print per-split 1m coverage (D-21).

### `src/data/archive.py` (new, Plan 5)

**Analog:** RESEARCH "Archive fetch + verify" snippet (lines 369-383; verified layout) plus `_row_to_kline`, whose 12-column layout the CSV shares. httpx async client, `hashlib.sha256` vs `.CHECKSUM` (fail closed with `ArchiveChecksumMismatch`), `zipfile`+`csv`, skip header row, validate symbols with `SYMBOL_RE` before URL use. Output `Kline` objects into `check_batch` then `publish_batch`. Tests use `respx` (no network).

### `src/data/universe_freeze.py` (new, Plan 7)

**Analog:** `scripts/decision_alignment/universe.py`: `validate_manifest(doc)` (must return `[]`, requires `len(symbols)==top_n`, 10..15 symbols), `compute_content_sha256(doc)` (hashes only the fields at lines 83-95), `FROZEN_CONTENT_SHA256: str | None = None` at line 53. Write manifest via line-level replace (keeps header comments; no `tomli_w`), regex-replace the witness, both via tmp + `os.replace`. `--freeze` required; print proposed manifest and unavailable-symbol list first. Ranking evidence goes in sidecar `docs/research/universe/research-universe-v1.freeze-report.json` (outside hash). Deterministic tie-break: symbol ascending; Decimal mean.

### `src/data/coverage.py` (Plan 8)

**Analog:** `_gap_count_for_range` (256-277). Add a sibling `gap_ranges_for_range(...)` using DuckDB `lag(open_time_utc)` over the view restricted to the requested range, so "unresolved gap" is defined in one place. Reads only `interval=*/symbol=*/date=*/part.parquet`, so mark data under `dataset=mark_klines` stays out of `candles_v1`.

### `src/data/case_input.py` (new, Plan 8; placement D-22)

**Analogs:** `src/backtest/experiment.py` lines 76-82, 125-135 (`data_snapshot_id` validated as 64-hex), `src/domain.canonical.sha256_hex`, `src/paper/freeze.py` (existing Parquet reader precedent), simulator key rule `bar.close_time_utc.isoformat()` (`simulator.py:901`) and `_parse_intrabar_map` (335-343).
```python
files = sorted(paths)  # explicit posix-relative list, never a dir scan
entries = [
    {"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    for p in files
]
dataset_id = sha256_hex({"files": entries})
```
Return a frozen dataclass `CaseInputData` (`strategy_bars`, `context_bars`, `intrabar_1m`, `mark_bars_1m`, `dataset_id`, `allowed_gaps`) with `to_case_input(**scenario)`. Values as Decimal-strings and isoformat timestamps. Raise project exception on unresolved gap unless in `allow_gaps`. Must not live in `src/backtest` (no-Polars rule).

### `src/paper/supervisor.py` (Plan 3, D-16/D-28)

**Analog:** itself, `_resubscribe_and_backfill` (230-275). Current order:
```python
self._close_all_handles()
self.start()
...
closes, gaps = await backfill_missed_closes(
    self._rest, symbol=symbol, interval=interval, last_close_utc=last, now_utc=now
)
```
Move `self.start()` after the backfill loop, call `record_close` (advance `_last_close`) for each backfilled close, and add a monotonic guard in `_on_kline` (drop closed kline with `close_time_utc <= _last_close[(symbol, interval)]`). Keep per-pair `try/except` isolation and the outage-gap dict shape. Test analog: `tests/test_paper_supervisor_backfill.py` (`_FakeWsAdapter`, `_FakeRestAdapter` at line 89 with `klines_calls`, `_make_supervisor` at 116); give both a shared `calls` list, drive `on_disconnect(scheduled=False)`, assert klines call precedes subscribe and a duplicate WS kline is not dispatched.

## Shared Patterns

### Immutable publish
**Source:** `src/data/store.py` 80-91 and `collector._guard_no_overwrite` (170-180). **Apply to:** trade store, mark store, collector tick writers, archive ingestion. Rule: never overwrite; tmp + `os.replace`; leftover tmp invisible to globs.

### Integer-ms time math, no wall clock in readers
**Source:** `align_to_day_start_ms` (`backfill.py:93`) and `resync._datetime_to_ms`. **Apply to:** all new backfill/builder code; readers take no clock.

### Per-symbol failure isolation and fail-closed
**Source:** `collector.main` loop (918-935) and `supervisor._resubscribe_and_backfill`. **Apply to:** backfill CLI, freeze CLI, archive fallback (classify UNAVAILABLE only when REST and archive both fail; never silently drop).

### Argparse CLI style
**Source:** `collector._parse_collector_args` / `main(argv) -> int`, `prog="python -m src.data.<module>"`.

### Canonical hashing
**Source:** `src.domain.canonical.sha256_hex`; `compute_content_sha256` reused verbatim for the manifest.

### Adapter boundary
SDK types only in `src/adapters/binance_usdm.py`; everything else consumes `Kline`/`MarkKline`/`SymbolFilters`. No `float` in price paths (AST guard `tests/test_domain_no_float.py`).

### Test conventions
Fake adapters recording calls (no live Binance), `respx` for httpx, tmp_path raw roots, tdd_mode is on. Rewrite (do not delete) the three old-behavior tests listed above.

## No Analog Found

| File | Role | Reason |
|---|---|---|
| `src/data/archive.py` HTTP/zip/checksum parsing | service | No existing httpx download or zip ingestion; use RESEARCH snippet and stdlib |
| Delivery-cap logic (`deliveryDate`) | service | New concept; no precedent, use RESEARCH Pitfall 1 and a fake adapter returning flat bars past delivery |
| Freeze writer (line-level manifest replace) | utility | No existing manifest writer; only the validator/hash exist |

## Metadata

**Analog search scope:** `src/data`, `src/adapters`, `src/paper`, `src/backtest`, `scripts/decision_alignment`, `tests`, `Dockerfile`
**Files read this session:** CONTEXT.md, RESEARCH.md (lines 1-406), store.py, targeted ranges of collector.py, backfill.py, quality.py, metadata.py, supervisor.py, universe.py, binance_usdm.py, test_paper_supervisor_backfill.py. Line numbers for `coverage.py`, `experiment.py`, `simulator.py`, `freeze.py` are taken from RESEARCH.md and were not re-read; the planner should confirm before editing.
**Tracked check:** `git ls-files` shows the only tracked file under `docs/research/universe` is `research-universe-v1.toml`; `src/data/case_input.py` does not yet exist. All analogs are under tracked `src/`, `scripts/`, `tests/`.
**Pattern extraction date:** 2026-09-30
