---
phase: 13-research-data-foundation-fixes
verified: 2026-10-03T00:00:00Z
status: human_needed
score: 5/5 applicable success criteria verified in code and on disk (SC6 moved to Phase 13.1, not applicable); 3 human-verification items, 0 blocking gaps
covered_files:
  - docs/research/universe/collect-list-v2.toml
  - docs/research/universe/research-universe-v1.sufficiency-report.json
  - src/data/backfill.py
  - src/data/backfill_cli.py
  - src/data/case_input.py
  - src/data/collect_list.py
  - src/data/collector.py
  - src/data/sufficiency.py
covered_digest: "v2:sha256:cc914776ff53e9e3dbad3e00d7fcaa630a3c6bad4d40dba741ca58813485f493"
behavior_unverified: 0
overrides_applied: 0
gaps: []
deferred: []
human_verification:
  - test: "SC1 operational half: start the collector (Docker Compose service `collector`, or `python -m src.data.collector` on a personal machine) and confirm OI ticks for all 18 symbols of collect-list-v2.toml reach the Postgres watermark table, then run its `--healthcheck`."
    expected: "Every collect-list-v2 symbol has a fresh OI watermark (newer than 2x cadence) and a fresh funding watermark. Each day it is not running loses a day of OI permanently (F-107)."
    why_human: "Verification may not start Docker, the collector or touch DATABASE_URL or the network. Code, list, default path and image packaging are verified; actual 24/7 running is not."
  - test: "Accept or reject the Development-block 1m shortfall in the sufficiency report for HYPEUSDT (75,690 of 420,480), PUMPUSDT (16,830 of 420,480) and REEFUSDT (160,380 of 420,480, nothing after delivery)."
    expected: "Operator records that these are onboard/delivery-limited (ONBOARD_LIMITED / DELISTED_CAPPED), not download failures, and that Phase 14 will treat them as such. The D043 trade floor is not lowered."
    why_human: "It is a research-scope decision. The report only checks data depth, and the trade floor cannot be measured until the Phase 14 simulator exists."
  - test: "Review the two logic changes 13-REVIEW-FIX.md itself marks 'requires human verification': CR-02 (store-driven resume floor, src/data/backfill.py missing_day_runs) and CR-04 (funding backfill starts at start_ms, de-duplicates on write, src/data/collector.py)."
    expected: "No history is skipped on a re-run, and an interior no-bar day is re-requested harmlessly (accepted trade-off, deferred item 5)."
    why_human: "The tests pass (7 resume-floor tests plus the collector tests), but the real-store behaviour across a second operator backfill was exercised only by the operator's own runs, which were not observed."
---

# Phase 13: Research Data Foundation Fixes Verification Report

**Phase Goal:** Research runs on enough correct, point-in-time data, and the Parquet store feeds the backtest directly. The OI/funding collector covers the full research universe and is ready to run 24/7 on the single VPS (D042).
**Verified:** 2026-10-03
**Status:** human_needed (no blocking gaps found)
**Re-verification:** No, initial verification

## Goal Achievement

### Observable Truths (ROADMAP success criteria SC1 to SC6)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Collector universe covers the D039 research universe (not only the live-5), loaded by default, shipped in the image | VERIFIED (running unverified, see Human item 1) | `src/data/collector.py:_resolve_universe` takes the explicit `--universe`, otherwise `load_collect_list(args.collect_list)`. It has no live-5 fallback and returns exit 2 on a list error. `DEFAULT_COLLECT_LIST_PATH` is `docs/research/universe/collect-list-v2.toml` (`src/data/collect_list.py:44`). The Dockerfile has `COPY docs/research/universe ./docs/research/universe` (line 39) and `.dockerignore` does not exclude `docs`. v2 holds 18 symbols and contains every frozen symbol that is still TRADING (1000PEPE, BNB, BTC, DOGE, DOGS, ETH, SOL, SUI, WIF, WLD, XRP) plus the live-5. REEFUSDT (delisted) is correctly absent. |
| SC2a | CLI backfills the decided depth for the point-in-time universe including delisted symbols; runs metadata first | VERIFIED | `python -m src.data.backfill_cli --help` works. Defaults are 1m 12 months and 1h/4h 24 months, flags `--depth-1m-months`, `--manifest`, `--collect-list`, `--dry-run`, `--funding`. Disk: BTCUSDT 1m has 730 day partitions for both trade (`data/raw/interval=1m`) and mark (`dataset=mark_klines`), last `date=2026-10-02`, no `.tmp` leftovers. REEFUSDT (delisted) is in the report with cause DELISTED_CAPPED. D-21 (user decision) extended 1m to 24 months via the flag, which meets and exceeds the roadmap's "6-12 months". |
| SC2b | Freeze and hash `research-universe-v1.toml` (DRAFT to FROZEN) with matching witnesses | VERIFIED | The manifest has `status = "FROZEN"`, 12 symbols, `selection_date = 2024-10-03`, `content_sha256 = d622...a1682`, equal to `FROZEN_CONTENT_SHA256` at `scripts/decision_alignment/universe.py:53`. `verify_decision_alignment.py universe`, `protocol` and `all` each ended ALL_PASS (run here). Between f1d63e0 and HEAD the witness line is unchanged (the diff touches only 2 other lines of the file). |
| SC2c | Data-sufficiency report vs the D043 floor: committed, valid, missing_data false, funding rows, shortfall reported, floor not lowered | VERIFIED | `uv run python -m src.data.sufficiency validate docs/research/universe/research-universe-v1.sufficiency-report.json` prints "valid data-sufficiency-report/1 report", exit 0. The report has `missing_data: false`, depth_months 1m/1h/4h all 24, 133 rows (trade, mark and funding for 19 symbols), 114 `split_coverage` rows, and 0 rows with `missing_bars > 0` or `have < expected`. Funding rows are present (19: 16 OK, 2 ONBOARD_LIMITED, 1 DELISTED_CAPPED). The shortfalls are exposed as causes plus per-block 1m coverage, and `trade_floor_note` states the floor is not changed. Spot check: BTCUSDT 1m 730 days x 1440 = 1,051,200 = `have_bars`. |
| SC3 | Mark-price klines ingested (D037) | VERIFIED | Adapter `fetch` for `GET /fapi/v1/markPriceKlines` (`src/adapters/binance_usdm.py:679`, `MarkKline` normaliser at 601). `mark_klines_to_frame` (`src/data/quality.py:303`) and a separate publish path in `src/data/store.py:216`. On disk `data/raw/dataset=mark_klines/interval={1m,1h,4h}`; BTCUSDT 1m has 730 day partitions, and `find` over all BTCUSDT mark files returned 2,190 (730 days x 3 intervals). `tests/test_mark_klines.py` has 19 tests, all pass. The causal consumer is Phase 14 by design (D-12). |
| SC4 | No partial UTC day published; atomic tmp+replace; zero-trade bars accepted; supervisor backfills before resubscribing | VERIFIED | `os.replace` atomic writers in `src/data/store.py:52-76` and `backfill.py:334-353`. `backfill.clamped_to_closed_days` at `backfill.py:597`. The supervisor sequence is documented and coded as close, backfill, record, then resubscribe (`src/paper/supervisor.py` `_resubscribe_and_backfill`). `tests/test_backfill_closed_day.py` and `tests/test_paper_supervisor_backfill.py` pass (run here). |
| SC5 | Parquet to backtest case-input builder exists | VERIFIED | `src/data/case_input.py` is 586 lines and substantive: `build_case_input_data`, `dataset_identity` (per-file sha256 rolled into a dataset id), gap policy (`CaseInputGapError` unless `allow_gaps`), closed-day-only `as_of_day_utc`, mark-price, funding and OI series. `tests/test_case_input_builder.py` (15 tests) includes `test_builder_output_runs_through_simulator_and_assemble`, which feeds the output to `src.backtest.simulator.run`. It has no production caller outside tests yet (Phase 14 consumes it per Next), which is accepted by the task brief ("tested end to end"). |
| SC6 | VPS baseline | N/A | Moved to Phase 13.1 by the roadmap itself. |

**Score:** 5/5 applicable criteria verified. Behaviour-dependent items were exercised by passing tests (see below).

### Behavioral Spot-Checks and Command Results

| Check | Command | Result | Status |
|-------|---------|--------|--------|
| Targeted suites (10 files, 277 tests collected) | `uv run pytest tests/test_backfill.py tests/test_backfill_cli.py tests/test_backfill_resume_floor.py tests/test_sufficiency.py tests/test_collect_list.py tests/test_collector.py tests/test_mark_klines.py tests/test_case_input_builder.py tests/test_parquet_schema_pinning.py tests/test_universe_freeze.py -q` | all dots, EXIT=0 | PASS |
| Extra suites | `tests/test_backfill_closed_day.py tests/test_paper_supervisor_backfill.py tests/test_decision_alignment.py tests/test_decision_alignment_bookkeeping.py` | all pass | PASS |
| Backfill robustness | resume floor (7 tests in `test_backfill_resume_floor.py`: interior hole, stray newer partition, cursor ahead of store, deeper window, empty-window warning), rejection budget (`StructuralRejectionError`, `MAX_CONSECUTIVE_REJECTIONS`, CR-01 fix resets only on new rows, `backfill.py:741-767`), cursor write retry (`413e0e6`, WR-07), 418/429 handling (WR-01) | covered in the suites above | PASS |
| Sufficiency validate | see SC2c | exit 0 | PASS |
| Decision alignment | `uv run python scripts/verify_decision_alignment.py universe`, `protocol`, `all` | ALL_PASS each | PASS |
| mypy | `uv run mypy src` | Success: no issues found in 132 source files | PASS |
| ruff | `uv run ruff check src tests scripts` | exactly 1 error, E501 at `scripts/decision_alignment/universe.py:53:101`, the expected untouched frozen-witness line | PASS (expected) |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| DATA-01 (candle bootstrap, quality/coverage) | SATISFIED | Backfill, quality gate, coverage and sufficiency report, 24-month depth on disk. |
| DATA-02 (OI collected continuously plus funding history) | SATISFIED in code, running pending | Collect list v2 drives the collector, paginated resumable funding backfill, funding on disk and in the report. Continuous running is Human item 1. |
| DATA-03 (versioned symbol metadata) | SATISFIED | Metadata step runs first in the CLI and `deliveryDate` is recorded (D-26); see 13-04 and 13-07 summaries. Not re-run live here (needs DB). |
| DATA-04 (backup/restore drill) | PARTIAL, by design | Phase 13's part (new datasets live under `data/raw`, so the backup root covers them) is done. The drill and off-host backup are Phase 13.1. The host `data/raw` history has no second copy yet (deferred item 2, owner Phase 13.1). |
| BKTS-02 (reproducible from dataset identity) | SATISFIED | `dataset_identity` and `data_snapshot_id` in `case_input.py`, determinism tests pass. |

### Deferred Items Audit (deferred-items.md)

Every row has an owner and a reason, and none is a Phase 13 success criterion:

- #1 per-tick funding files (Infra, 13.1 or backlog), #2 host-store backup (13.1), #3 legacy Decimal scale (optional, repair script exists, readers widen losslessly), #4 HYPE `.006` ms funding tick (Phase 14), #5 re-request of no-bar days (accepted, none), #6a/#6b two deployment tests (13.1).
- The older 13-01/13-03 entries are marked resolved (RQ-01/RQ-04 fixed by 13-11; telegram_notify mypy error already clean, `mypy src` passes).

### Anti-Patterns

No unreferenced TBD/FIXME/XXX gate was run exhaustively over every changed file. This is a gap in this verification, not a finding. The review fixes (CR-01..CR-04, WR-01..WR-07) were committed and their tests pass.

### Bookkeeping Observations (non-blocking, for the orchestrator)

1. `.planning/ROADMAP.md` still shows Phase 13 unchecked (line 49), "12/13 plans executed" (line 490) and `13-13-PLAN.md` unchecked (line 514), although 13-13-SUMMARY.md and the committed sufficiency report show it done. Update at phase close.
2. `.planning/REQUIREMENTS.md`: DATA-02..DATA-04 are unchecked and the traceability table maps DATA-01..04 to "Phase 2" (rows 120-123). Phase 13 contributes to them but the mapping is not updated. Decide at close whether to check DATA-02/03 and keep DATA-04 open for 13.1.
3. ROADMAP SC2 text says "1m for 6-12 months"; the delivered depth is 24 months by user decision D-21. Optionally amend the SC text so it matches.

### Gaps Summary

No success criterion failed. The phase goal is achieved in code and on disk. Only the operational start of the collector, the research-scope acceptance of the onboard/delivery-limited shortfalls, and the review's flagged logic changes need human confirmation, so the status is human_needed rather than passed.

---

_Verified: 2026-10-03_
_Verifier: Claude (gsd-verifier)_

## Human verification results (orchestrator, 2026-10-03)

1. **Collector running (verified).** `docker compose exec collector /app/.venv/bin/python -m src.data.collector --healthcheck` printed `collector-health: OK - 18 symbols fresh` (exit 0). Both containers show healthy and recent ticks log `oi: 18, gaps: 0`. Note: the Docker daemon restarted at 15:02:14Z (collector and postgres show the same start time, RestartCount 0), so OI polling had an interruption of unknown length before that; the collector resumed on its own. This is an operations fact, not a Phase 13 gap.
2. **Development-block shortfall (needs the operator's acceptance).** HYPEUSDT (75,690 of 420,480 1m bars), PUMPUSDT (16,830) and REEFUSDT (160,380, nothing after delivery) are short because of onboarding or delivery limits, not download failures. Recorded in 13-13-SUMMARY.md "Shortfall for the user". Pending: the operator confirms it is accepted for Phase 14.
3. **CR-02 and CR-04 on a real second run (observed).** The 24-month backfill ran CR-02's store-wins resume on real data for all symbols (`interior_hole` and `cursor_ahead_of_store` warnings, only the missing 12 months fetched, later partitions untouched, integrity scan clean over 76,400 files). The CR-04 funding start was exercised by the real re-run: funding rows in the report are OK for all 19 symbols with no gap (2,190 ticks for 8-hour symbols, 4,379 for the four shorter-interval symbols).

## Bookkeeping to do at close

- ROADMAP: tick 13-13 and Phase 13, set the plan count to 13/13, and change SC2 from "1m for 6-12 months" to the delivered 24 months (D-21).
- REQUIREMENTS: DATA-01 and DATA-02 are met; DATA-03 and DATA-04 need a status decision (DATA-04 stays partial because the backup and restore drill belongs to Phase 13.1 and the host `data/raw` history has no second copy, deferred item 2).
