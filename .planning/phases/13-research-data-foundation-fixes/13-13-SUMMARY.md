---
phase: 13-research-data-foundation-fixes
plan: 13
subsystem: research-data-backfill
tags: [collect-list, backfill, sufficiency, operator-action, D-21, funding]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-12 frozen research universe v1 (12 symbols, content_sha256 d6223620...1682)"
provides:
  - "docs/research/universe/collect-list-v2.toml (18 still-TRADING symbols) and reissue_collect_list generator"
  - "docs/research/universe/research-universe-v1.sufficiency-report.json (schema data-sufficiency-report/1, 1m at 24 months, funding rows)"
  - "Real backfilled research store under data/raw (trade and mark klines 1m/1h/4h, funding ticks), outside git"
affects: [phase-14 causal simulator, D043 trade floor check]

key-files:
  created:
    - docs/research/universe/collect-list-v2.toml
    - docs/research/universe/research-universe-v1.sufficiency-report.json
    - 13-REVIEW.md, 13-REVIEW-FIX.md
  modified:
    - src/data/collect_list.py
    - src/data/backfill.py, src/data/backfill_cli.py, src/data/sufficiency.py, src/data/collector.py, src/data/quality.py, src/data/store.py

key-decisions:
  - "D-21 (user, 2026-10-03): extend 1m from 12 to 24 months. With 12 months the Development block and Validation fold 1 (50% of the timeline) had no 1m and used the stop-first fallback while the other blocks resolved on 1m, so the blocks would not be comparable."
  - "RESEARCH_PROTOCOL.md, the D043 trade floor, thresholds and the CLI depth defaults are untouched."

requirements-completed: [DATA-01, DATA-02]

completed: 2026-10-03
---

# Phase 13 Plan 13: Collect list v2 and real backfill

Collect list v2 is live in the collector, the operator ran the real backfill at 24 months of 1m, and the committed sufficiency report shows 1m, 1h, 4h and funding coverage with no unexplained gap. The backfill exits 0 and `missing_data` is false.

## Commits

| What | Commit |
|------|--------|
| RED tests, then `reissue_collect_list` and collect-list-v2.toml | `cc249c9`, `a5b4433` |
| Cursor write retry on transient PermissionError | `413e0e6` |
| First sufficiency report (1m at 12 months) | `cb096f9` |
| Code review report, then 12 fix commits (CR-01..CR-04, WR-01..WR-07) | `2bef0b5`, `8acad28`..`16fb36e`, `0d397aa` |
| Sufficiency report refreshed with 1m at 24 months | `d98f71b` |
| D-21 outcome, collect-list-v2 doc names, deferred items | `797770f` |
| IN-01..IN-04 | `7dc1cf7` |
| Funding coverage rows in the sufficiency report (D-23) | `07d5903` |
| Stale `test_ci_docker_job` assertion | `1c317c4` |
| Funding rows documented | `e83a957` |
| Final sufficiency report | `2e59c3f` |

## Verification

- `python -m src.data.sufficiency validate <report>`: valid data-sufficiency-report/1.
- `scripts/verify_decision_alignment.py protocol` and `all`: `ALL_PASS`.
- `mypy src`: clean on 132 files. `ruff`: one pre-existing E501 on the frozen witness line in `scripts/decision_alignment/universe.py:53`, left untouched on purpose.
- Targeted test groups (backfill, sufficiency, collector, coverage, metadata, case input, parquet schema, universe freeze, collect list, deploy workflows) pass.
- Integrity scan of the whole store (76,400 Parquet files, 37.4 million rows, 114 groups, trade and mark): no OHLC violation, no duplicate open time, ordered, no scale above 8. This checks internal consistency, not equality with Binance, and covers klines only.
- Collector running in Docker with list v2: universe=18, oi=18 per 5-minute tick, gaps=0.

## Shortfall for the user

Report totals: 133 rows = 112 OK + 14 ONBOARD_LIMITED + 7 DELISTED_CAPPED. No GAP, NOT_BACKFILLED, UNAVAILABLE or NO_WINDOW row. `missing_data` is false. The remaining shortfall is only what the exchange cannot supply:

| Symbol | Cause | trade/mark 1m | 1h | 4h | funding ticks |
|---|---|---|---|---|---|
| REEFUSDT | DELISTED_CAPPED (delivery 2025-01-22) | 160,380 of 1,051,200 | 2,673 of 17,520 | 669 of 4,380 | 629 |
| HYPEUSDT | ONBOARD_LIMITED | 706,410 | 11,773 | 2,943 | 2,942 |
| PUMPUSDT | ONBOARD_LIMITED | 647,550 | 10,792 | 2,698 | 2,697 |

The other 16 symbols are complete: 1,051,200 1m bars, 17,520 1h bars and 4,380 4h bars each, trade and mark, and funding with no hole (2,190 ticks for the 8-hour symbols, 4,379 for DOGSUSDT, ENAUSDT, MOVRUSDT and WIFUSDT, which are on a shorter funding interval; this reading of the counts is not checked against Binance documents). REEF is in the universe on purpose (selected 2024-10-03, kept against survivorship bias).

### 1m coverage per protocol split block (all 19 symbols pooled)

| Block | Window | Coverage |
|---|---|---|
| development | 2024-10-03..2025-07-22 | 87.38% |
| validation_fold_1..4 | 2025-07-22..2026-05-10 | 94.74% each |
| holdout | 2026-05-10..2026-10-03 | 94.74% |

Per symbol every block is 100% except: REEFUSDT (160,380 of 420,480 in Development, nothing after its delivery), HYPEUSDT (75,690 of 420,480 in Development) and PUMPUSDT (16,830 of 420,480 in Development). Validation and holdout are 100% for all symbols except REEF.

### D-21 (decided by the user)

1m extended to 24 months. Cost: about 460 MB more on disk and about 3 hours of REST download; the CLI default stays 12 months.

### Trade floor note (verbatim from the report)

The D043 trade floor (at least 100 closed trades pooled across the four Validation folds and at least 30 per fold) cannot be measured until the Phase 14 causal simulator exists; this report checks data depth only and never changes the floor.

## Deviations and findings

- **Resume skipped history (fixed).** The first backfill run found BTCUSDT 1h trade with 15 stray recent partitions, so the resume floor treated it as complete and skipped 2 years. The sufficiency report caught it (BTC 1h: 337 of 17,520, GAP). The partitions were moved aside and re-fetched by hand; the code was fixed afterwards (CR-02, contiguity-aware floor with `interior_hole` and `cursor_ahead_of_store` warnings). The 24-month run is the first real use of that path and behaved as designed.
- **Deep code review (13-REVIEW.md) and fixes (13-REVIEW-FIX.md).** Four critical findings, all fixed: CR-01 infinite loop on a corrupt page after a good page, CR-02 resume floor, CR-03 Decimal scale not pinned (the real store already had mixed scales; the writer now pins `Decimal(38, 8)` and `read_partitions` widens legacy files losslessly), CR-04 funding start taken from the live collector watermark (funding history was never fetched, `ticks=0`). Seven warnings fixed (WR-01..WR-07) and four info items (IN-01..IN-04). CR-04 is now also guarded by funding rows in the report, so an empty funding series ends the run with exit 3.
- **Mixed scale remains in old files.** The older 12 months of 1m trade and some other symbols keep their original smaller scale. Values are exact; only the schema differs. Readers handle it. A dry-run repair script exists (`scripts/repair_parquet_scale.py`); repairing is optional.
- **Cursor write was fragile.** The first long run died with PermissionError in `CursorStore.write` (a file briefly locked right after the previous write; cause not proven, OneDrive sync is now off). Retry added (`413e0e6`) and hardened (WR-07).
- **Funding before the kline window.** PUMPUSDT has funding ticks earlier than its exchangeInfo onboard date; only ticks inside the window are counted (2,697).
- **Service name** is `collector`, not `app` as the original plan text said (plan text and docs corrected).
- **Stale names** `collect-list-v1.toml` in the Dockerfile, CONFIGURATION.md and DATA_MODEL.md now point at v2.
- The operator ran every real backfill in their own terminal; the executor never read `.env`.
- **Not protected yet.** `data/raw` is outside git (D-04) and outside the project backup flow, and OneDrive sync is off, so the backfilled history has no second copy (see deferred items).

## Deferred

See `deferred-items.md` (Phase 13 close-out table): funding stored as one file per tick, backup of the host store, optional repair of legacy scales, the HYPE `.006` ms funding tick for Phase 14, the accepted re-request of no-bar days, and two deployment tests owned by Phase 13.1.

## Next

Phase 13 verification and close-out. Phase 14 can read the store through `src/data/case_input.py`.
