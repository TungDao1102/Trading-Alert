# Phase 13: Research Data Foundation Fixes - Context

**Gathered:** 2026-09-30
**Status:** Ready for planning
**Mode:** `--auto` (Claude chose the recommended option for every gray area; each choice is logged in 13-DISCUSSION-LOG.md and can be overridden before planning)

<domain>
## Phase Boundary

Research runs on enough correct, point-in-time data, and the Parquet store feeds the backtest directly. The OI/funding collector covers the whole research universe and is ready to run 24/7 under Docker Compose (D042).

Delivers: a collector universe wider than the live-5, a history-depth backfill CLI, a frozen and hashed point-in-time research universe, mark-price kline ingestion, hardened backfill (no partial-day publish, atomic writes, zero-trade bars, backfill-before-resubscribe), and a Parquet → backtest case-input builder.

Out of scope (owned elsewhere): Docker HEALTHCHECK fix (F-705), PostgreSQL localhost binding (F-709), encrypted off-VPS backups (F-108, F-910), VPS baseline and provisioning (all Phase 13.1); the causal simulator that consumes mark-price klines for SL/TP triggers (Phase 14); executable gate code and holdout writer (F-960, Phase 26).

Requirements: DATA-01, DATA-02, DATA-03, DATA-04, BKTS-02. Audit refs: F-107, F-906, F-907, F-024, F-122, F-402, F-408, F-409, F-413, F-706.
</domain>

<decisions>
## Implementation Decisions

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
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authority and decisions
- `docs/DECISIONS.md` — D037 (mark-price triggers), D039 (point-in-time universe), D042 (single-VPS topology), D043 (protocol v1.1.0 trade floor), D044 follow-up 4 (universe freeze and history depth owned by Phase 13), D045
- `AGENTS.md` — determinism, exchange-authority (re-verify endpoints against current docs), fail-closed, Decimal rules
- `.planning/ROADMAP.md` §"Phase 13" and §"Phase 13.1" — goal, six success criteria, what moved to 13.1
- `.planning/REQUIREMENTS.md` — DATA-01, DATA-02, DATA-03, DATA-04, BKTS-02
- `.planning/phases/11-decision-alignment/11-CONTEXT.md` — manifest DRAFT → FROZEN decision, param-set versioning
- `.planning/phases/12-fee-cost-model-correctness/12-CONTEXT.md` — hash canonicalization and deliberate-regeneration conventions

### Audit
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` and `findings.json` — F-107, F-906, F-907, F-024, F-122, F-402, F-408, F-409, F-413, F-706

### Research universe and protocol
- `docs/research/universe/research-universe-v1.toml` — DRAFT manifest with the freeze procedure (steps 1–6) in its header
- `scripts/decision_alignment/universe.py` — hash routine and `FROZEN_CONTENT_SHA256` witness (UN-02)
- `docs/research/RESEARCH_PROTOCOL.md` (v1.1.0 FROZEN) — read-only; D043 trade floor and dataset splits

### Docs to amend
- `docs/SOURCES.md` — record source URL and fetch date for markPriceKlines, delisted-symbol data source, exchangeInfo fields
- `docs/configuration/CONFIGURATION.md` — collector universe / depth settings if they become registry or env parameters
- `docs/DATA_MODEL.md` — mark-kline dataset and dataset-identity hash
- Binance integration doc under `docs/integration/` — mark-price kline endpoint (planner locates path)

### Code
- `src/data/collector.py` — `LIVE_5` import, `async_oi_tick`, `async_funding_sweep`, `main`, watermark and gap recording
- `src/data/backfill.py` — `backfill_universe`, `backfill_symbol_interval`, `DEFAULT_BACKFILL_WINDOWS_MS`, `CursorStore`, `align_to_day_start_ms`
- `src/data/store.py` — `publish_batch`, partition layout
- `src/data/quality.py`, `src/data/coverage.py`, `src/data/metadata.py` — validators, coverage, `refresh_symbol_metadata`
- `src/adapters/binance_usdm.py` — adapter surface; mark-price kline method goes here (SDK types never leak)
- `src/paper/supervisor.py`, `src/paper/resync.py` — `_resubscribe_and_backfill`, `backfill_missed_closes`
- `src/backtest/experiment.py`, `src/backtest/binding.py`, `src/paper/freeze.py` — case-input consumers and existing Parquet reader precedent
- `tests/test_backfill.py`, `tests/test_collector.py`, `tests/test_metadata.py` — tests to extend
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backfill_universe` / `backfill_symbol_interval` with `CursorStore` resume and per-interval `BackfillConfig`: the CLI wraps these rather than re-implementing paging.
- `publish_batch` and the no-overwrite guard: extend for atomic tmp + replace instead of a new writer.
- `refresh_symbol_metadata`: already versioned-insert with an optional `universe` filter.
- `scripts/decision_alignment/universe.py` hash routine: reuse for the freeze so the two witnesses stay independent.
- `CollectorWatermark` / `CollectorGap` tables: gap and staleness tracking already exist per symbol.

### Established Patterns
- Published Parquet is immutable; derived data is versioned, never edited in place.
- Adapters isolate SDK models; tests use fakes/fixtures, never live endpoints.
- Frozen artifacts (protocol, params) are versioned, never edited in place; hashes are deliberate, single-commit changes.
- Decimal for exchange-sensitive values; determinism (no wall clock in readers).

### Integration Points
- `collector.py` symbol source → collect list (D-01/D-02).
- `binance_usdm.py` adapter → new mark-price kline method; `backfill.py` gains a dataset selector (trade vs mark).
- `paper/supervisor.py` reconnect path → order fix (D-16), minimal.
- `src/backtest/` → new builder feeding `ExperimentRecord` with dataset identity; Phase 14 will consume its mark-price output.
</code_context>

<specifics>
## Specific Ideas

- Time-sensitive: each day the widened collector is not running loses a day of OI permanently, so plan the collector widening as an independently shippable first plan (D-03).
- The freeze CLI should print the proposed manifest and delisted-symbol availability before `--freeze`, so the operator sees exactly what will be hashed.
</specifics>

<deferred>
## Deferred Ideas

- Simulator use of mark-price klines for SL/TP triggers — Phase 14.
- Executable trade-floor / gate code and holdout-consumed writer (F-960) — Phase 26.
- Trade-count estimate for the D043 floor — impossible until the Phase 14 causal simulator exists.
- HEALTHCHECK, DB localhost binding, encrypted off-VPS backups, VPS baseline and heartbeat monitor — Phase 13.1.
- Reconsidering the D043 trade floor if depth falls short — needs a new DECISIONS row, not this phase.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.
</deferred>

---

*Phase: 13-research-data-foundation-fixes*
*Context gathered: 2026-09-30*
