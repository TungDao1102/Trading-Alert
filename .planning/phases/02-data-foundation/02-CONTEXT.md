# Phase 2: Data Foundation - Context

**Gathered:** 2026-09-19
**Status:** Ready for planning

## Phase Boundary

Phase 2 delivers irrecoverable-data safety: per-symbol bootstrap of 1m/1H/4H candles with quality checks and queryable coverage, a day-one OI snapshot collector plus funding history, versioned symbol metadata from live exchangeInfo, and an automated backup + restore drill covering PostgreSQL state and the self-collected OI dataset. No strategy logic, no backtest engine, no paper loop — this phase produces data plumbing and evidence that data is safe. Success means the user can bootstrap candles per symbol, query effective per-symbol coverage with duplicates/OHLC violations/gaps flagged, OI accumulates continuously so the 30-day API window can never destroy research data, metadata loads versioned from exchangeInfo instead of hard-coded values, and the backup + restore drill passes.

## Implementation Decisions

### Bootstrap scope

- **D-01:** First bootstrap covers the V1 live-5 only (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT) with all three intervals (1m + 1H + 4H) together. The 10–15-symbol research slice is explicitly deferred to a later expansion run, not part of the first green bootstrap.
- **D-02:** History depth is bounded for the first run, not "everything Binance has": 1H/4H ~2 years back, 1m ~6–12 months back, extendable on demand. Rationale: 1m full-history for 5 symbols is heavy for a part-time dev machine; bounded depth unblocks quality/coverage/OI work fast while the expansion path stays open. — **Reversibility:** reversible — re-running backfill with a deeper window appends data, no contract break.
- **D-03:** Backfill source is Binance USDⓈ-M klines via the official SDK (`binance-sdk-derivatives-trading-usds-futures`) behind a project-owned adapter, re-verified against current docs at implementation time. No TradingView or third-party vendor as bootstrap source (TradingView stays optional cross-check only).

### Storage layout

- **D-04:** Parquet is the immutable raw store, partitioned by interval → symbol → date (e.g. `data/raw/interval=1m/symbol=BTCUSDT/date=2026-09-19/part.parquet`), raw files never mutated after publish; derived/resampled datasets are versioned separately. — **Reversibility:** costly — partition layout is read by every downstream consumer (backtest, paper, DuckDB views); changing it later touches all readers.
- **D-05:** Role split: Parquet + DuckDB own analytical/research data (candles, funding, OI snapshots, coverage queries); PostgreSQL 17 owns operational state + metadata (symbol metadata versions, onboard time, coverage windows, collector watermarks). No candle OHLCV rows as primary store in PostgreSQL. — **Reversibility:** one-way — moving the analytical/transactional boundary later needs a data migration plus consumer rewiring.
- **D-06:** All storage timestamps UTC internally; presentation in Asia/Ho_Chi_Minh only at the display edge (per DATA_PIPELINE §7, resolving the Bangkok-vs-HCMC naming toward HCMC).

### OI + funding capture

- **D-07:** OI collector starts day one of this phase for the live-5, polling current OI (`/fapi/v1/openInterest`) every 5 minutes via the official SDK behind an adapter, persisting timestamp + symbol + OI + collector version. 5-minute cadence balances research need against rate limits for a part-time operator; NOT arbitrary sub-minute polling. — **Reversibility:** reversible — cadence is a config value, tightening/loosening it later does not break stored snapshots.
- **D-08:** Funding-rate history is backfilled once plus collected ongoing alongside OI (same scheduler family, separate tables/files per data class). Historical OI statistics endpoint (`/futures/data/openInterestHist`, ~30-day window) is harvested opportunistically at bootstrap but never relied upon — the self-collected snapshots are the canonical forward source.
- **D-09:** Gap policy is flag-never-fabricate: missed polls produce explicit gaps in the snapshot series (watermark + gap journal), never interpolated/synthesized OI values. Downstream (Phase 6/7) must treat gaps as missing, not zero.

### Quality + backup drill

- **D-10:** Quality gates fail closed on structural corruption (duplicate candle timestamps, impossible OHLC relationships, timestamp regressions, symbol-metadata mismatch → batch rejected, no silent overwrite) and warn + flag on continuity issues (missing sequence/gaps, stale feed → flagged in coverage, pipeline continues). Follows DATA_PIPELINE §6 exactly.
- **D-11:** "Queryable coverage" means both: (a) a CLI command (e.g. `uv run ... coverage --symbol BTCUSDT`) printing effective per-symbol range plus violation/gap counts, and (b) a DuckDB SQL view over Parquet + metadata reporting `historical_data_start_utc / historical_data_end_utc / onboard_time_utc / status_history` per symbol (per DATA_PIPELINE §10). Backtest reports later state effective range per symbol — no direct BTC-vs-short-alt comparison without showing the difference.
- **D-12:** Backup + restore drill covers PostgreSQL state (pg_dump of metadata/coverage/watermarks) AND the self-collected OI dataset (Parquet snapshot copy), restores into a scratch target and verifies row-count/hash equality. Drill is automated (single command) and rehearsed in this phase; off-host copy is required (backup must not live only on the primary host). Schedule default: weekly automated backup + drill on demand in Phase 2, hardened later.

### the agent's Discretion

- User explicitly delegated all four areas ("bạn hãy lựa chọn cái tốt nhất cho tôi") and confirmed the recommended-defaults bundle in one gate. Exact CLI names, Parquet filename conventions, DuckDB view names, scheduler implementation (asyncio task vs cron vs Compose job), and drill script layout are at the planner/researcher discretion, provided D-01–D-12 semantics hold.
- Plan slicing within the phase (fine granularity) is at the planner's discretion.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Research contract (frozen)

- `docs/research/RESEARCH_PROTOCOL.md` — FROZEN v1.0.0; universe discipline (live-5 vs 10–15 research slice, both reported), three-way splits, anti-overfitting R1–R6; dataset requirements Phase 2 must satisfy.
- `docs/research/TRADING_STRATEGY_RESEARCH.md` — living draft v0.1; source material only, never the frozen contract.

### Data pipeline + methodology

- `docs/architecture/DATA_PIPELINE.md` — canonical ingestion contract: §2 data classes (1m/1H/4H, 15m later), §3 OI endpoints + 30-day limit, §6 quality rules, §7 UTC storage, §8 raw-vs-derived, §9 OI collector, §10 per-symbol availability.
- `docs/backtest/BACKTEST_SPEC.md` — dataset-split discipline and cost/execution assumptions the stored data must support (warm-up history, 1m intrabar availability).
- `docs/data/DATA_MODEL.md` — canonical entities; Phase 2 persists metadata/coverage/watermarks compatibly, anticipating Phase 3 seven-entity work.
- `docs/configuration/CONFIGURATION.md` — parameter-registry identity; Phase 2 dataset versions must be referenceable by later experiment records.

### Platform + decisions

- `docs/TECHNOLOGY_STACK.md` — canonical stack: Python 3.13 + uv, Parquet + DuckDB / PostgreSQL 17, official Binance SDK behind adapters, Decimal/tick arithmetic for exchange-sensitive values.
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; C1–C7 resolutions (timezone → Asia/Ho_Chi_Minh, canonical enums) bind Phase 2.
- `docs/GLOSSARY.md` — canonical enums and terminology; no invented status names.
- `docs/integration/BINANCE.md` — Binance integration contract; endpoints/fields re-verified against current official docs at implementation, never hard-coded from memory.

### Project context

- `.planning/PROJECT.md` — project context, constraints, key decisions.
- `.planning/REQUIREMENTS.md` — DATA-01, DATA-02, DATA-03, DATA-04.
- `.planning/ROADMAP.md` — Phase 2 goal and success criteria.
- `.planning/phases/01-research-formalization/01-CONTEXT.md` — Phase 1 locks (frozen protocol location, 7-slot family template, gate enforcement via registry + CI) that Phase 2 consumes.

## Existing Code Insights

### Reusable Assets

- None — greenfield code. No `src/`, `pyproject.toml`, or DB exists yet. The `docs/` corpus (Core Docs v0.3 + Phase-1 outputs) is the working material, not code to reuse.

### Established Patterns

- Research → Strategy Spec → Code separation (`docs/implementation/AGENT_INSTRUCTIONS.md`): missing rules stay TBD and become research tasks; agents must not invent production behavior.
- Determinism and fail-closed posture from `docs/01_ENGINEERING_PRINCIPLES.md`: uncertain data/connection/account/risk → NO_TRADE, no new orders; same discipline applies to data ingestion (reject corrupt batches, flag gaps).

### Integration Points

- Phase 3 (Domain + Registry + Fixtures) implements the parameter registry; Phase 2 dataset versions must be linkable from future experiment records.
- Phase 6 (Backtest) consumes Parquet candles + funding + OI snapshots with 1m intrabar resolution; Phase 7 (Paper) consumes the live collector path. Storage layout decisions here constrain both.

## Specific Ideas

- User delegated implementation choices to the agent (Vietnamese: "tôi không có kiến thức về phần này. bạn hãy lựa chọn cái tốt nhất cho tôi") and confirmed the four-group recommended bundle (live-5-first bootstrap, Parquet-partitioned + PG/DuckDB split, 5-min day-one OI, fail-closed quality + automated backup drill) in a single confirmation gate.
- No "I want it like X" references — open to standard approaches within the locked decisions above.

## Deferred Ideas

None — discussion stayed within phase scope. Research-universe expansion (10–15 symbols), 15m interval support, and OI/funding as strategy features (REFN-02/REFN-03) remain scheduled in their own phases/requirements.

---

*Phase: 2-Data Foundation*
*Context gathered: 2026-09-19*
