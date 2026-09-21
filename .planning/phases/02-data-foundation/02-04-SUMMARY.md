---
phase: 02-data-foundation
plan: 04
type: tdd
subsystem: data-foundation
tags: [metadata-versioning, exchangeInfo, oi-collector, funding-sweep, gap-journal, tdd, flag-never-fabricate]

# Dependency graph
requires:
  - phase: 02-data-foundation
    plan: 02
    provides: "adapter + paginator + Parquet store + quality gate"
  - phase: 02-data-foundation
    plan: 01
    provides: "SQLAlchemy ORM (SymbolMetadata / CollectorWatermark / CollectorGap) + alembic baseline + golden exchangeInfo fixture"
provides:
  - "Versioned symbol metadata refresh — PK (symbol, metadata_observed_at_utc) means every refresh INSERTs a new row, never UPDATE (D-05 / RESEARCH §Pattern 4)"
  - "Day-one 5-minute OI collector loop with flag-never-fabricate gap journal (D-07 + D-09)"
  - "Funding-rate backfill + sweep on its own data_class='funding' namespace (D-08)"
  - "Opportunistic openInterestHist harvest tagged source='research' (D-08) — never the canonical forward source"
  - "5 metadata + 5 collector TDD behaviors; 30/30 full suite green"
affects:
  - "Phase 6 (backtest) consumes canonical OI snapshots + versioned metadata"
  - "Phase 7 (paper) consumes the live collector path"
  - "Phase 8 (approval/reconciliation) consumes the gap journal for fail-closed posture"

# Actuals (#2632)
actuals:
  tokens: 13213              # chars/4 over 1329 inserted lines (5 files)
  tasks: 2
  commits: 4                 # MEASURED: 4 atomic commits — 2 RED + 2 GREEN

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CapturingSession test wrapper — snapshots SymbolMetadata / CollectorGap / CollectorWatermark attributes BEFORE session.commit() to bypass SQLite's lossy REAL/tzinfo roundtrip (production uses PostgreSQL NUMERIC(38,18) + TIMESTAMPTZ)"
    - "Async wrapper / sync body split — adapter calls are async (SDK runs in to_thread), DB writes are sync inline on the event loop, Parquet writes are sync (Polars)"
    - "Per-tick Parquet file layout (data_class={oi|funding|oi_research}/symbol={SYM}/date={YYYY-MM-DD}/tick-{ISO}.parquet) keeps D-04 immutability trivial — no second-write collision possible"
    - "Tick-wide gap row (symbol=NULL) on adapter exception vs per-symbol gap row — preserves the operational distinction between 'whole tick failed' and 'one symbol failed' (deferred to a future plan)"

key-files:
  created:
    - src/data/metadata.py
    - src/data/collector.py
    - tests/test_metadata.py
    - tests/test_collector.py
  modified:
    - src/adapters/binance_usdm.py — additive: OiSnapshot.source field + BinanceUsdmAdapter.open_interest_statistics method

key-decisions:
  - "Refresh symbol metadata is INSERT-only per (symbol, observed_at) — even identical filter values produce a new version row (RESEARCH §Pattern 4 / versioned metadata)."
  - "OI tick on adapter exception writes ONE tick-wide gap row (symbol=NULL), not per-symbol — fail-closed posture aborts the whole tick rather than recover half-way (per-symbol recovery deferred to a future plan)."
  - "Funding sweep uses a distinct watermark namespace (data_class='funding') and a distinct Parquet partition (data_class=funding) — never co-mingled with the OI loop."
  - "Opportunistic openInterestHist harvest writes to data_class=oi_research AND tags rows source='research' so downstream consumers (Phase 6/7) can refuse to use historical data as the canonical forward source."
  - "Test-side CapturingSession snapshots instance attributes BEFORE session.commit() — SQLAlchemy's post-flush refresh from SQLite REAL drops Decimal precision and tzinfo, which would mask the exact-precision guarantees the metadata module enforces."

patterns-established:
  - "TDD discipline for adapter-boundary code: write tests against the project dataclass shape (SymbolFilters, OiSnapshot), not the SDK pydantic model — keeps the test surface small and the adapter the single owner of SDK shape translation."
  - "Epoch-ms datetime comparison across the SQLite roundtrip — naive datetimes read back are assumed UTC (the convention we wrote them in); production uses PostgreSQL TIMESTAMPTZ which preserves tzinfo exactly."
  - "Atomic per-tick transaction: snapshot file write (sync, Polars) → session.merge(watermark) → session.commit() — if commit fails the next tick re-writes the same data (no double-write, no silent corruption)."

requirements-completed: [DATA-02, DATA-03]

coverage:
  - id: D1
    description: "Golden exchangeInfo fixture → 1 new SymbolMetadata row per live-5 symbol with Decimal tick/step (Beh. 1)"
    requirement: DATA-03
    verification:
      - kind: unit
        ref: tests/test_metadata.py#test_refresh_inserts_one_version_row_per_live5_symbol
        status: pass
    human_judgment: false
  - id: D2
    description: "Second refresh with identical filters still INSERTs a new observed-at version, never UPDATEs (Beh. 2 / D-05)"
    requirement: DATA-03
    verification:
      - kind: unit
        ref: tests/test_metadata.py#test_second_refresh_inserts_new_observed_at_version
        status: pass
    human_judgment: false
  - id: D3
    description: "Filter numeric strings parse to Decimal exactly — 0.10+0.10+0.10==0.30, no float roundoff (Beh. 3)"
    requirement: DATA-03
    verification:
      - kind: unit
        ref: tests/test_metadata.py#test_filter_strings_parse_to_decimal_exactly
        status: pass
      - kind: unit
        ref: tests/test_metadata.py#test_no_float_call_in_metadata_or_adapter
        status: pass
    human_judgment: false
  - id: D4
    description: "Optional universe=LIVE_5 parameter trims out non-target symbols without failing the refresh (Beh. 4)"
    requirement: DATA-03
    verification:
      - kind: unit
        ref: tests/test_metadata.py#test_unknown_symbols_outside_live5_are_ignored
        status: pass
    human_judgment: false
  - id: D5
    description: "Healthy OI tick writes 1 snapshot per live-5 + advances 5 watermarks atomically (Beh. 1)"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: tests/test_collector.py#test_oi_tick_writes_one_snapshot_per_live5_and_advances_watermarks_atomically
        status: pass
    human_judgment: false
  - id: D6
    description: "Adapter exception writes 1 gap row + no snapshot + no watermark advance (Beh. 2 / D-09 flag-never-fabricate)"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: tests/test_collector.py#test_oi_tick_adapter_exception_writes_gap_row_no_snapshot_no_watermark
        status: pass
    human_judgment: false
  - id: D7
    description: "Skipped scheduled tick records expected vs observed timestamps, no interpolation, no snapshot files (Beh. 3)"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: tests/test_collector.py#test_oi_skipped_tick_records_expected_vs_observed_no_interpolation
        status: pass
    human_judgment: false
  - id: D8
    description: "Funding sweep uses distinct data_class='funding' namespace + watermark, distinct Parquet partition (Beh. 4 / D-08)"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: tests/test_collector.py#test_funding_sweep_uses_separate_partition_and_watermark_namespace
        status: pass
    human_judgment: false
  - id: D9
    description: "Opportunistic openInterestHist harvest rows carry source='research' tag and live in data_class=oi_research partition — canonical oi partition untouched (Beh. 5 / D-08)"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: tests/test_collector.py#test_open_interest_history_harvest_tagged_as_research_grade
        status: pass
    human_judgment: false
  - id: D10
    description: "Long-running OI loop + funding sweep + opportunistic harvest against live Binance"
    requirement: DATA-02
    verification: []
    human_judgment: true
    rationale: "Live-network exercise requires the dev machine to host the collector process against fapi.binance.com — deferred until Docker Compose postgres + observability (Phase 8) lands."

# Metrics
duration: ~25 min
completed: 2026-09-21
status: complete
---

# Phase 02 Plan 04: Versioned Metadata + OI/Funding Collector Summary

**Versioned symbol metadata refresh + day-one OI collector + funding sweep with flag-never-fabricate gap journal — all 9 plan behaviors TDD-green via 5+5 RED→GREEN commits.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 (Task 1 metadata, Task 2 collector)
- **Files modified:** 5 (2 src + 1 test × 2 + 1 adapter extension)
- **Commits:** 4 (RED + GREEN × 2 tasks)

## Accomplishments

- **Versioned metadata refresh** (`src/data/metadata.py::refresh_symbol_metadata`) — every refresh INSERTs a new `(symbol, metadata_observed_at_utc)` row, never UPDATEs. PK = version key, so historical snapshots stay queryable for backtest-time rule reconstruction (RESEARCH §Pattern 4).
- **Day-one 5-minute OI loop** (`src/data/collector.py::async_oi_tick`) — polls `adapter.open_interest()` for each live-5 symbol, writes one Parquet file per symbol per tick under `data_class=oi/symbol={SYM}/date={YYYY-MM-DD}/tick-{ISO}.parquet`, advances `CollectorWatermark` for each symbol atomically in one transaction.
- **Funding-rate sweep** (`async_funding_sweep`) — distinct `data_class='funding'` watermark namespace + distinct Parquet partition. Backfill is `since_ms`-driven (caller passes `last_watermark + 1` or `0` for first bootstrap).
- **Opportunistic openInterestHist harvest** (`harvest_open_interest_history`) — D-08 compliance: writes to `data_class=oi_research` partition AND tags every row `source='research'`. Canonical `data_class=oi` is never touched. Per-symbol `OiSnapshot.source` field (additive adapter change) carries the tag end-to-end.
- **Additive adapter extension** (`src/adapters/binance_usdm.py`) — `OiSnapshot.source: str = 'canonical'` field + `BinanceUsdmAdapter.open_interest_statistics(symbol, period, limit)` method that wraps the SDK's `/futures/data/openInterestHist` endpoint and emits `list[OiSnapshot]` with `source='research'` pre-tagged.

## Task Commits

Each TDD task produced two commits (RED → GREEN):

1. **Task 1 RED — metadata tests** — `61dea64` (test: add RED metadata tests for 4 behaviors)
2. **Task 1 GREEN — metadata module** — `bbddb47` (feat: versioned symbol metadata refresh)
3. **Task 2 RED — collector tests** — `31b73d8` (test: add RED collector tests for 5 behaviors)
4. **Task 2 GREEN — collector module + adapter extension** — `06e9c3f` (feat: day-one OI/funding collector with gap journal)

**Plan metadata:** this SUMMARY, pending commit.

## Files Created/Modified

- `src/data/metadata.py` (new, 90 lines) — `refresh_symbol_metadata(session, filters, observed_at=None, universe=None) -> int`. INSERT-only versioned writer for `symbol_metadata`. Optional `universe` parameter trims to the V1 live-5 (D-01).
- `src/data/collector.py` (new, 447 lines) — three async operations (`async_oi_tick`, `async_funding_sweep`, `harvest_open_interest_history`) plus three Parquet writers and two internal helpers (`_record_gap`, `_advance_watermark`). Atomic one-transaction pattern: file write → watermark merge → commit. On any exception the tick aborts and a single tick-wide gap row is written (D-09).
- `tests/test_metadata.py` (new, 324 lines) — 5 tests covering the 4 plan behaviors + a static guard against explicit `float(` calls in metadata.py or adapter. Includes `CapturingSession` wrapper that snapshots SymbolMetadata attributes before SQLite's lossy roundtrip can mask the exact-Decimal guarantee.
- `tests/test_collector.py` (new, 420 lines) — 5 tests covering the 5 plan behaviors. `_epoch_ms(dt)` helper compares datetimes via Unix-ms epoch to bypass SQLite's tzinfo stripping. `_FakeAdapter` duck-types the BinanceUsdmAdapter async surface (`open_interest`, `funding_rate`, `open_interest_statistics`).
- `src/adapters/binance_usdm.py` (modified, +49 / -1 lines) — additive `source` field on `OiSnapshot` (default `'canonical'`) + new `open_interest_statistics(symbol, period, limit) -> list[OiSnapshot]` method wrapping the SDK's `/futures/data/openInterestHist` endpoint.

## Decisions Made

- **CapturingSession wrapper for metadata tests** — SQLite stores `Numeric(38,18)` as REAL (loses Decimal precision) and `TIMESTAMPTZ` without tzinfo. Asserting on `SymbolMetadata` read-back from SQLite would mask the exact-Decimal guarantee the metadata module enforces. The wrapper snapshots `SymbolMetadata` attribute values BEFORE `session.commit()` so post-flush refresh from the DB can't corrupt the assertion. Production uses PostgreSQL NUMERIC(38,18) + TIMESTAMPTZ which preserve both exactly — the wrapper documents this boundary explicitly.
- **Tick-wide gap row (symbol=NULL), not per-symbol** — when the adapter raises mid-tick, the fail-closed posture aborts the whole tick and writes one gap row with the original `expected_utc`/`observed_utc`. Per-symbol recovery is deferred to a future plan; V1's contract is "all-or-nothing per tick".
- **Harvest completion recorded as a `data_class='oi_research_harvest'` gap row** — the audit trail lives in one place. Future plans can JOIN against this gap-table entry to find the most-recent successful research harvest per (symbol, period).
- **`harvest_open_interest_history` does NOT advance any watermark** — D-08 says the historical endpoint is research-grade only. Advancing a watermark would imply canonical forward semantics, which is exactly what D-08 forbids.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SQLite Decimal precision + tzinfo loss masked Decimal guarantee**
- **Found during:** Task 1 GREEN (initial `test_filter_strings_parse_to_decimal_exactly` failure — `Decimal('0.10')` read back as `Decimal('0.100000000000000006')`)
- **Issue:** SQLite has no native NUMERIC type; SQLAlchemy falls back to REAL storage, which converts via float on the roundtrip. Same issue strips tzinfo from TIMESTAMPTZ.
- **Fix:** Introduced `CapturingSession` wrapper that snapshots the `SymbolMetadata` instance attributes (Decimal / datetime values) BEFORE `session.commit()` — post-flush refresh from SQLite can't poison the assertion. Documented the boundary in the wrapper's docstring + module docstring so future maintainers understand why production assertions on PG will work without this wrapper.
- **Files modified:** `tests/test_metadata.py`
- **Verification:** 5/5 metadata tests pass + 25/25 full suite
- **Committed in:** `bbddb47` (Task 1 GREEN, included the wrapper alongside the metadata implementation)

**2. [Rule 1 - Bug] Static guard `assert "float(" not in src` caught docstring mention**
- **Found during:** Task 1 RED (initial `test_no_float_call_in_metadata_or_adapter` failure — assertion tripped on the metadata module's own docstring mentioning `float(...)`)
- **Issue:** Naive substring search matched the word "float(" anywhere in the source file, including docstrings that DESCRIBE the rule.
- **Fix:** Replaced the substring check with an AST walk that finds every `ast.Call` whose `func` is `Name(id='float')`. AST parsing skips strings and comments entirely.
- **Files modified:** `tests/test_metadata.py`
- **Verification:** Guard passes on the docstring-mentioning metadata.py and would fail on any actual `float(x)` call.
- **Committed in:** `bbddb47` (Task 1 GREEN, alongside metadata implementation)

**3. [Rule 1 - Bug] Test 4 symbol= glob didn't match Windows Path**
- **Found during:** Task 2 GREEN (initial `test_open_interest_history_harvest_tagged_as_research_grade` failure — `rglob("*symbol=BTCUSDT*")` returned empty)
- **Issue:** Pathlib's `rglob` returns directories matching the glob but the test expected parquet files matching the pattern; on Windows the pattern with `=` is interpreted as a glob-set only against file basenames, not directory names containing `=`.
- **Fix:** Replaced the rglob with a direct `Path.iterdir()` filter on `name == "symbol=BTCUSDT"`, then rglobs for `*.parquet` inside the matched directory. Cross-platform.
- **Files modified:** `tests/test_collector.py`
- **Verification:** Test passes on Windows; the iterdir approach is portable to Linux.
- **Committed in:** `06e9c3f` (Task 2 GREEN)

**4. [Rule 1 - Bug] Naive `datetime.timestamp()` interpreted as local time**
- **Found during:** Task 2 GREEN (initial `_epoch_ms(dt)` helper — naive datetime read back from SQLite was 7 hours off)
- **Issue:** `_epoch_ms(naive_dt)` called `naive_dt.timestamp()` which interprets naive datetimes as local time (not UTC).
- **Fix:** When the input is naive, re-attach UTC before calling `.timestamp()`. Documented in the helper docstring.
- **Files modified:** `tests/test_collector.py`
- **Verification:** All 5 collector tests pass; helper now produces identical ms regardless of tzinfo presence.
- **Committed in:** `06e9c3f` (Task 2 GREEN)

---

**Total deviations:** 4 auto-fixed (1 SQLite precision, 1 AST guard, 1 path glob, 1 tz-naive conversion). All 4 are correctness fixes that the plan's verification implicitly required (`Decimal arithmetic exact`, `no float conversion anywhere`, `gap row records expected vs observed`, `research-tagged rows`).
**Impact on plan:** All four fixes are necessary for the plan's behaviors to actually verify under SQLite. Production uses PostgreSQL where 3 of 4 (Decimal precision, TIMESTAMPTZ tzinfo) are non-issues; the 4th (the helper) is needed regardless.

## Issues Encountered

- **`git diff 5e96f0a..HEAD` shows 4855 inserted lines** — that's the entire phase 2 diff (5 plans total). For per-plan measurement I used `git diff 12df757..HEAD -- <plan files>` → 1329 lines / 13,213 chars/4 = ~13k tokens, matching the `actual: 13213` frontmatter.
- **Pathlib Windows glob with `=` separator** — Pathlib on Windows treats `=` as part of a glob pattern. Direct `iterdir()` + `name ==` comparison is portable.
- **LSP errors on the new files** — pre-existing project-wide issue (LSP not pointed at `.venv`). Real `uv run pytest` resolves all imports. Recorded as `out of scope` per 02-03's pattern.

## User Setup Required

None — no external services or credentials required for the test surface. The collector itself only runs against live Binance when the Docker Compose postgres stack is up and `DATABASE_URL` is set, which is a Phase 8 orchestration concern (not this plan's deliverable).

## Next Phase Readiness

- **02-05 (coverage CLI + DuckDB views)** can now query the Parquet `data_class=oi` + `data_class=funding` partitions produced by this plan's collector + the existing `data_class=oi_research` partition for research comparisons.
- **Phase 3 (live rollout)** can wire the `async_oi_tick` loop into a Compose-managed long-running process. The plan's `harvest_open_interest_history` is the bootstrap-time one-shot (run once at Phase 3 deployment to fill the 30-day research window before the 5-min loop takes over).
- **Phase 8 (approval/reconciliation)** reads `CollectorGap` rows as the authoritative "this is what we missed" ledger; the `expected_utc` vs `observed_utc` columns carry the lag the reconciliation needs to compute.

---

*Phase: 02-data-foundation*
*Completed: 2026-09-21*
