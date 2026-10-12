# 16-37 Task 1 evidence: preflight, post-amendment consistency check, dataset coverage facts

Plan: 16-37 Task 1 (tracer). Read-only: nothing outside this file was edited. No run, no network, `.env` not read.
Checked: 2026-10-13 (UTC), working tree `master` at e92ca7d (plan 16-28 recorded the amendment on `develop` at 9d2949c; the amendment commits are present in this tree's history and the files below carry them).

This file reports facts only. It proposes no date, symbol choice or value (REV-14, O-03b are the user's).

## 1. Protocol version read

`docs/research/RESEARCH_PROTOCOL.md` lines 3-7:

```
> **Protocol version:** v2.2.0
> **Status:** FROZEN
> **Frozen on:** 2026-09-19
> **Amended on:** 2026-10-11
> **Supersedes:** v2.1.0
```

Protocol version read: **v2.2.0**. `docs/research/holdout_consumed.json`: schema `holdout-consumed/2`, `protocol_version` `v2.2.0`, `entries: []`. `docs/DECISIONS.md` line 71 carries D067. `16-28-amendment-check.txt` (landing commit 3bfcd325, alignment and feasibility tests passed) is the recorded proof of the amendment; it was not re-run here (Task 1 runs only the plan's automated check and the grid listing).

## 2. Grid check (three files, not one)

The plan names `docs/research/preregistration/research-run-1-grid.json`. That file does not exist. Plan 16-45 registered three grid files (deviation recorded in the 16-45 SUMMARY). `python -m src.research.register --list-grid --grid <file>` on each (exit 0, file reads only):

| Grid file | Points | Status of every point |
|-----------|--------|-----------------------|
| `research-run-1-grid-trend-pullback.json` | a01..a16 (16) | STRUCTURALLY_VALID |
| `research-run-1-grid-breakout-retest.json` | b01..b16 (16) | STRUCTURALLY_VALID |
| `research-run-1-grid-range-mr.json` | c01..c16 (16) | STRUCTURALLY_VALID |

No point has any other status. Fact about the runner shape: `run_research` takes one `grid` and one `authorization` (`src/research/run.py:213-234`, `require_authorized(authorization, manifest=manifest, grid=grid)`), and the authorization file binds one `grid_sha256` and one `manifest_sha256` (`src/research/authorization.py:39`, `56-88`). With three grid files, a run is one (grid, authorization) pair per file.

## 3. The six consistency items of plan 16-28, re-checked against the landed v2.2.0 text

| # | Item | Source A | Source B | Conflict | Needed edit | Owner |
|---|------|----------|----------|----------|-------------|-------|
| 1 | v2.2.0 vs SC8 | `.planning/ROADMAP.md:710` (SC8: trial soak, 14 calendar days, >= 95 percent coverage, epoch pin, freeze ticks, EVIDENCE_GAP rule) | `RESEARCH_PROTOCOL.md:39` (v2.2.0 migration: seventh identity field only) and section 5 (`:285-343`) | no | none | n/a |
| 2 | v2.2.0 vs SC9 | `.planning/ROADMAP.md:711` (PAPER-01 completes on criteria 1, 2, 7; PAPER-02 on 3, 5; no G1-G5 result is a closure input) | `RESEARCH_PROTOCOL.md:39` ("no experiment has been recorded", nothing applied backwards); `16-28-amendment-check.txt` (amendment landed before any authorization) | no | none | n/a |
| 3 | v2.2.0 vs PAPER-01/02/03 | `.planning/REQUIREMENTS.md:52-54` and `:143-145` (PAPER-03 Pending, Phase 26; test events, planned restarts and gaps never count; "no tuning") | `RESEARCH_PROTOCOL.md:39` (identity change only; no strategy_version or parameter set moves) | no | none | n/a |
| 4 | v2.2.0 vs the WR registry and the kill-gate path | `docs/research/kill_gate_review_registry.json` (schema `kill-gate-review-registry/1`, 5 items WR-01, WR-06, WR-10, WR-12, WR-13, all UNRESOLVED; none mentions `data_snapshot_id`, `data_manifest` or a protocol version) | `RESEARCH_PROTOCOL.md:338-343` ("Every experiment record carries ... seven"; "not reproducible without all seven") vs `src/analytics/provenance.py:56-98` (`ExperimentIdentity` carries `data_snapshot_id`, no `data_manifest_hash`) | **yes, one gap** (route B left the fixtures untouched as 16-28 predicted; but the analytics provenance object does not carry the seventh field) | none made here. Facts: `src/adapters/analytics_files.py:137-141` and `:610-629` accept `data_manifest_hash` as the one OPTIONAL key (tests `tests/test_analytics_files.py:390`, `:625-657`); `experiment_id` is part of `ExperimentIdentity.digest()` and the id joins the manifest hash under v2.2.0, so the digest still differs, but the field itself is not shown in the provenance. Whether a later plan or follow-up surfaces it is a scope decision | USER (decides scope); ROADMAP-BATCH if it becomes a plan; the landed amendment (quick task 261011-mi1) is the amendment owner and is closed |
| 5 | Mapping required by REV-16 (authorization manifest hash == identity's manifest value) | `RESEARCH_PROTOCOL.md:39` ("the same value the run authorization binds as `manifest_sha256`"); `src/research/authorization.py:56-88` (`manifest_hash=payload["manifest_sha256"]`) | `src/research/run.py:68-81` (`experiment_identity_inputs` returns `{"data_snapshot_id": dataset_id, "data_manifest_hash": manifest_hash(manifest)}`); `run.py:234` (`require_authorized(... manifest=manifest ...)`) | no | none. Note for Task 3: the route B body of `experiment_identity_inputs` already landed in commit 652e7eb (the amendment); Task 3's remaining identity work is its tests 2 and 3 and the `--build` command, not a new function body | n/a (note for the Task 3 executor) |
| 6 | G1 and G5 floor sentences and `feasibility.py` constants | `RESEARCH_PROTOCOL.md:244` (G1: 100 pooled, 30 per Validation fold) and `:248` (G5: 30 in the holdout), present and worded as in v2.1.0; `16-28-amendment-check.txt` check 6 (0 changed lines) | `src/research/feasibility.py:31-37` (constants `G1_POOLED_FLOOR=100`, `G1_PER_FOLD_FLOOR=30`, `G5_HOLDOUT_FLOOR=30`, comments "unchanged since v2.1.0") | no | none | n/a |

Observation, not a conflict with v2.2.0 (owner: ROADMAP-BATCH to judge): this plan's frontmatter lists `requirements: [PAPER-01]`, and `ROADMAP.md:711` closes PAPER-01 on criteria 1, 2 and 7. Plan 16-37 produces a research manifest and a decision record; whether any of those three criteria needs it was not assessed here. This run closes no requirement.

## 4. Dataset coverage (read-only facts for the O-03b decision)

Method: partition directory names under `data/raw` only (a `date=` directory counts when it holds at least one `.parquet` file); no dataset was loaded. Spot checks of two files: `data/raw/interval=1m/symbol=BTCUSDT/date=2024-10-03/part.parquet` and `.../date=2026-10-02/part.parquet` each hold 1440 rows spanning 00:00..23:59 UTC; one funding file holds 1 row. `data/raw` is gitignored. 126986 files in total.

Layout on disk (`src/data/store.py:39`, `:149-151`):
- trade klines: `data/raw/interval=<1m|1h|4h>/symbol=<S>/date=<D>/part.parquet`
- mark-price klines: `data/raw/dataset=mark_klines/interval=<1m|1h|4h>/symbol=<S>/date=<D>/part.parquet`
- funding: `data/raw/data_class=funding/symbol=<S>/date=<D>/sweep-<time>.parquet` (3 files per day for 8 h cadence symbols, 6 for 4 h cadence ones)
- `data/raw/_cursors/` (collector cursor files). There is NO `data_class=oi` directory (open interest) locally.

Each row below is identical for trade 1m/1h/4h, mark 1m/1h/4h and funding unless a note says otherwise. "Missing" = a date between first and last with no partition.

| Symbol | In universe v1 | First date | Last date | Partitions | Missing between first and last |
|--------|:--------------:|-----------|-----------|-----------:|--------------------------------|
| 1000PEPEUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| BNBUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| BTCUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| DOGEUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| DOGSUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| ETHUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| REEFUSDT | yes | 2024-10-03 | 2025-01-22 | 112 | none |
| SOLUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none (see note A) |
| SUIUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| WIFUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| WLDUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| XRPUSDT | yes | 2024-10-03 | 2026-10-02 | 730 | none |
| ENAUSDT | no | 2024-10-03 | 2026-10-02 | 730 | none |
| HYPEUSDT | no | 2025-05-30 | 2026-10-02 | 491 | none |
| MOVRUSDT | no | 2024-10-03 | 2026-10-02 | 730 | none |
| NEARUSDT | no | 2024-10-03 | 2026-10-02 | 730 | none |
| PUMPUSDT | no | 2025-07-10 (funding: 2025-04-12) | 2026-10-02 | 450 (funding: 519) | klines none; funding 2025-06-20..2025-07-09 (20 days), see note B |
| QNTUSDT | no | 2024-10-03 | 2026-10-02 | 730 | none |
| ZECUSDT | no | 2024-10-03 | 2026-10-02 | 730 | none |

Note A (SOLUSDT, trade klines 1h only): two extra partitions `date=2023-11-14` and `date=2023-11-15` exist (732 partitions), so between the stray first date 2023-11-14 and the main run the dates 2023-11-16..2024-10-02 (322 days) are absent. The 1m and 4h trade series, the mark series and funding of SOLUSDT start at 2024-10-03 with 730 partitions. The runner lists the days of the requested range explicitly (`src/data/case_input.py:336-343`, `:572`), so files outside the range are not read.

Note B (PUMPUSDT funding): partitions exist for 2025-04-12..2025-06-19 and 2025-07-10..2026-10-02, with none for 2025-06-20..2025-07-09; the klines (all intervals, trade and mark) start at 2025-07-10. The universe sufficiency report (`docs/research/universe/research-universe-v1.sufficiency-report.json`, `run_date` 2026-10-03) lists PUMPUSDT funding as starting 2025-07-10 (2697 expected and present).

Summary of the 12 symbols of `docs/research/universe/research-universe-v1.toml` (top_n 12, FROZEN 2024-10-03): all 12 have local data (11 symbols over the full 2024-10-03..2026-10-02 range; REEFUSDT only through 2025-01-22, which the sufficiency report labels DELISTED_CAPPED). Data symbols NOT in the universe: ENAUSDT, HYPEUSDT, MOVRUSDT, NEARUSDT, PUMPUSDT, QNTUSDT, ZECUSDT (7 of 19). The sufficiency report (same file, `missing_data: false`, `depth_months` 24 for 1m/1h/4h, `dataset_start` 2024-10-03, `dataset_end` 2026-10-03) shows zero missing bars for the checked rows; HYPEUSDT and PUMPUSDT are labelled ONBOARD_LIMITED. Minute-level gaps were not re-computed here (the partition names cannot show them); the sufficiency report is the existing source.

### Dataset kinds: what exists locally and what the runner needs

| Kind | Exists locally | Needed by the runner for the first run |
|------|----------------|----------------------------------------|
| Trade klines 1m | yes, 19 symbols | yes: `intrabar_1m` series and the 1m minute source (`src/data/case_input.py:74`, `:533`; `src/data/minute_source.py:49`, `:193-194`) |
| Trade klines 1h and 4h | yes | yes for the strategy and context intervals (defaults 1h and 4h, `case_input.py:548-549`, files at `:531-532`); the manifest fields `strategy_interval` and `context_interval` (`src/research/manifest.py:91-92`) must be keys of `INTERVAL_MS` (`src/data/quality.py:30-38`: 1m, 3m, 5m, 15m, 1h, 4h, 1d; `case_input.py:306-311`). Locally only 1m, 1h, 4h exist, so a 3m, 5m, 15m or 1d interval has no files |
| Mark-price klines 1m | yes | yes: `mark_1m` series (`case_input.py:74`, `:534`; `minute_source.py:193`) |
| Mark-price klines 1h and 4h | yes | not read: `case_input.py:534` and `minute_source.py:193-194` read only the mark 1m partitions |
| Funding | yes | yes: `funding` series (`case_input.py:74`, `:535`) |
| Open interest (`data_class=oi`, `tick-*.parquet`) | **no** (no such directory locally) | **no**: the runner passes `series=ENGINE_SERIES` (`src/research/run.py:136` and `:166`); `ENGINE_SERIES = ("trade", "intrabar_1m", "mark_1m", "funding")` and the comment at `case_input.py:73` says open interest stays inert. The code that would read it exists (`case_input.py:536`, `:387-390`) but is not requested by the runner |
| Constraint source file (JSON with a row per symbol) | not found: no file with `constraint` in its name exists outside `.venv`, `node_modules`, `data` and `*.py` | yes: the manifest names a `constraint_source` and `constraint_sha256`; the runner refuses an unreadable file, a hash mismatch, or a symbol without a row (`src/research/run.py:90-103`) |

Mechanical constraints of the code, stated as facts (not as advice):
- every manifest boundary must sit on a UTC day boundary, the three blocks must be contiguous and non-empty (`manifest.py:109-137`);
- the Validation block must have a whole number of days divisible by 4, otherwise `validation_folds()` raises (`manifest.py:148-160`);
- the runner reads only Development and the four Validation folds, never the holdout (`manifest.py:245-256`); the manifest `dataset_id` covers the files from development start through validation end (`manifest.py:76-79`, `run.py:128-143`);
- `end_utc` must not be after the start of the `as_of_day` (`case_input.py:329-334`); the runner passes `as_of_day_utc = validation_end_utc.date()`;
- a non-empty `excluded_periods` is refused by the runner (`run.py:122-127`: "excluded_periods are not supported by the runner");
- any gap found in a requested series over a symbol's range must equal an entry of `known_gaps` or the build raises `CaseInputGapError` (`case_input.py:411-426`, `run.py:137`); so a symbol whose files start after the window start or end before the window end (HYPEUSDT, PUMPUSDT, REEFUSDT locally) is reported as a gap over the missing range;
- the partition last date locally is `date=2026-10-02`, so the latest `end_utc` for which every symbol-day file of the long-history symbols exists is 2026-10-03T00:00:00Z.

## 5. Open facts not verifiable here

(a) Is this local copy current against the EC2 host? **Not checked.** Facts only: the last local partition is `date=2026-10-02` for every long-history symbol; `16-20-migration.md` records a pull of snapshot `20261010T031756Z` on 2026-10-10 (destination `pull-20261010T085546Z`, verify-OK, 7810 files already present, 1608 copied) and a collector running on EC2 since the 2026-10-09 cutover. Why the pulled snapshot's newest partition is 2026-10-02 (rather than later) was not investigated. The local `data/raw/_cursors/BTCUSDT_1m.cursor` and `ETHUSDT_1m.cursor` hold `1759449540000`, which is 2025-10-02T23:59:00Z, a year before the last local partition; the meaning of these local cursor files was not investigated. `data/backup` and `data/reports` are empty. Whether EC2 holds partitions after 2026-10-02 is unknown here.

(b) How the manifest represents the four Validation folds: it does not store them. `DatasetManifest` stores only `validation_start_utc` and `validation_end_utc` (`src/research/manifest.py:87-88`), and the four folds are derived: `validation_folds()` (`manifest.py:148-160`) divides the whole days of the Validation block into `VALIDATION_FOLD_COUNT = 4` (`manifest.py:28`) equal consecutive intervals; the fold boundaries are therefore determined by the two stored boundaries and are not independent fields of `canonical()` (`manifest.py:162-192`). `research_splits()` (`manifest.py:245-256`) returns one DEVELOPMENT window followed by the four VALIDATION folds and never the holdout. Protocol text: `RESEARCH_PROTOCOL.md:62` (four consecutive equal-length walk-forward test folds) and `:94` (40/40/20 by time; "the dataset start and end, and the resulting fold boundaries, are recorded in the experiment record (section 5)").

OI gap window from `16-20-migration.md`: `2026-10-09T19:34:49Z .. 2026-10-09T19:55:00Z` (open-interest snapshots, 18 symbols in the pasted cutover report; about one 5-minute slot per symbol; DOGSUSDT has one additional hole 19:34:49Z..19:39:52Z). Falls inside the local data range? **No.** The local range ends at `date=2026-10-02` (the window is on 2026-10-09), and the local copy holds no open-interest data of any date. It is also not a series the runner reads (section 4). It remains a recorded coverage gap for any statement about the completeness of the collected dataset (open-interest snapshots cannot be fetched later; the dataset must not be called full history).

Other facts for the decision, not verified or not decided here: the research account inputs (`equity`, `risk_rate`, manifest fields at `manifest.py:97-98`) are positive Decimals chosen by the user; the data source and version strings (`manifest.py:93-94`) are free text chosen by the user; the constraint source file does not exist in the repository.
