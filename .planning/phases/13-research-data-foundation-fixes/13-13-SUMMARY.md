---
phase: 13-research-data-foundation-fixes
plan: 13
subsystem: research-data-backfill
tags: [collect-list, backfill, sufficiency, operator-action, D-21]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-12 frozen research universe v1 (12 symbols, content_sha256 d6223620...1682)"
provides:
  - "docs/research/universe/collect-list-v2.toml (18 still-TRADING symbols) and reissue_collect_list generator"
  - "docs/research/universe/research-universe-v1.sufficiency-report.json (schema data-sufficiency-report/1)"
affects: [phase-14 causal simulator, D043 trade floor check]

key-files:
  created:
    - docs/research/universe/collect-list-v2.toml
    - docs/research/universe/research-universe-v1.sufficiency-report.json
  modified:
    - src/data/collect_list.py
    - tests/test_collect_list.py

key-decisions:
  - "Depth defaults unchanged: 1m for 12 months, 1h/4h for 24 months (dataset 2024-10-03..2026-10-03)."
  - "RESEARCH_PROTOCOL.md, the D043 trade floor and every threshold are untouched."

requirements-completed: [DATA-01, DATA-02]

completed: 2026-10-03
---

# Phase 13 Plan 13: Collect list v2 and real backfill

Collect list v2 is live in the collector and the operator ran the real backfill. The committed sufficiency report validates and the backfill exits 0 (every missing row has a recorded cause). The 1m depth question (D-21) is open and belongs to the user.

## Commits

| Task | Commit | What |
|------|--------|------|
| 1 | `cc249c9`, `a5b4433` | RED tests, then `reissue_collect_list` and collect-list-v2.toml |
| 3 | `cb096f9` | Sufficiency report, committed unchanged |

## Verification

- `python -m src.data.sufficiency validate <report>`: valid data-sufficiency-report/1.
- `scripts/verify_decision_alignment.py protocol`: `ALL_PASS protocol`.
- Collector running in Docker with list v2: universe=18, oi=18 per 5-minute tick, gaps=0.

## Shortfall for the user

Report totals: 114 rows = 100 OK + 8 ONBOARD_LIMITED + 6 DELISTED_CAPPED. No GAP, NOT_BACKFILLED, UNAVAILABLE or NO_WINDOW row remains. `missing_data` is false.

### Rows short by cause

| Symbol | Cause | trade/mark 1h bars | trade/mark 4h bars | 1m |
|---|---|---|---|---|
| REEFUSDT | DELISTED_CAPPED (delivery 2025-01-22) | 2673 of 17520 | 669 of 4380 | 0 |
| HYPEUSDT | ONBOARD_LIMITED | 11773 of 17520 | 2943 of 4380 | full 12 months |
| PUMPUSDT | ONBOARD_LIMITED | 10792 of 17520 | 2698 of 4380 | full 12 months |

The other 16 symbols are complete: 525600 1m bars, 17520 1h bars and 4380 4h bars each, trade and mark. REEF is in the universe on purpose (selected 2024-10-03, kept against survivorship bias). It covers only the early Development block and nothing in Validation or holdout.

### 1m coverage per protocol split block (per symbol)

| Block | Window | Expected | Have | Coverage |
|---|---|---|---|---|
| development | 2024-10-03..2025-07-22 | 420480 | 0 | 0% |
| validation_fold_1 | 2025-07-22..2025-10-03 | 105120 | 0 | 0% |
| validation_fold_2 | 2025-10-03..2025-12-15 | 105120 | 105120 | 100% |
| validation_fold_3 | 2025-12-15..2026-02-26 | 105120 | 105120 | 100% |
| validation_fold_4 | 2026-02-26..2026-05-10 | 105120 | 105120 | 100% |
| holdout | 2026-05-10..2026-10-03 | 210240 | 210240 | 100% |

This holds for all 18 symbols except REEF (0 everywhere at 1m). Overall 1m coverage is 525600 of 1051200 bars per symbol, 50%.

### Open decision D-21 (user)

Keep 1m at 12 months, or extend to 24 months through the Binance archive. Arithmetic from the report: extending adds 525600 1m bars per symbol per dataset (trade and mark), and fills the Development block (40% of the timeline) and Validation fold 1 (10%). Keeping 12 months leaves only 3 of 4 Validation folds and the holdout measurable at 1m. The default stays 12 months until the user decides. Nothing in this plan changes it.

### Trade floor note (verbatim from the report)

The D043 trade floor (at least 100 closed trades pooled across the four Validation folds and at least 30 per fold) cannot be measured until the Phase 14 causal simulator exists; this report checks data depth only and never changes the floor.

## Deviations and risks

- **Resume can silently skip history.** The backfill floors its start at the day after the latest published partition (`src/data/backfill.py`, resume_from_store). BTCUSDT 1h trade had 15 stray recent partitions (2026-09-18..2026-10-02), so the first run saw an empty window (`backfill.universe.empty_window`) and skipped 2 years. The sufficiency report caught it (BTC 1h: 337 of 17520, GAP). Fix applied by the operator side: the 15 partitions were moved aside and the symbol was re-run, giving 17520 of 17520. The code is unchanged. Recommendation: have resume compare against the dataset start (or warn when the earliest partition is later than the window start) and keep the sufficiency report as the gate.
- **Cursor write was fragile on OneDrive.** The first long run died with PermissionError in `CursorStore.write` (file briefly locked after the previous write). A retry fix with 2 tests exists in the working tree (`src/data/backfill.py`, `tests/test_backfill.py`) and is not committed yet.
- **Service name.** The compose service is `collector`, not `app` as the plan text says.
- **Stale file names.** Dockerfile line 38, docs/CONFIGURATION.md line 74 and docs/DATA_MODEL.md line 393 still mention `collect-list-v1.toml`.
- The operator ran the backfill in their own terminal; the executor never read `.env`.

## Next

Phase 13 close-out: code review of the phase, verification, mark complete. User decision on D-21 before Phase 14.
