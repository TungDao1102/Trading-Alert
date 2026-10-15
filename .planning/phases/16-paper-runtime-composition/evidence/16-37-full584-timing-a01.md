# 16-37 full 584-day timing probe, grid point research-run-1-a01 (Development + 4 Validation folds), code a64e6af: timing and memory only

date: 2026-10-15. Authority: the user wrote "đo a91 đủ 584 ngày đi" in this session ("a91" is a typo of grid point a01; no a91 exists). This authorises one timing measurement of one grid point over the full research window (Development plus the four Validation folds, 584 days) with the current code, and nothing else.

Hard limits respected: no `src/research/run.py` `main` and no `run_research` (no RunAuthorization), no `assemble`, no ExperimentRecord built or written (`_run_split` was read, not called; its case-building and simulation calls were replicated), no manifest file (in-memory `DatasetManifest` only), no O-03, no authorization file, `docs/research/holdout_consumed.json` untouched, no change under `src/`, `tests/`, `params/` or `docs/`. No Holdout day was opened or hashed: every `polars.read_parquet` call and every dataset-id file hash (`src.data.case_input._file_sha256`) was wrapped in the probe process by a guard that raises on any path without a `date=` part or with a date on/after 2026-05-10; it never fired, and the 12,116 inventory listing lines on/after that date were only skipped as text. For the Validation folds only wall seconds, memory and file counts are reported; no record counts, kinds, labels, per-symbol numbers, PnL, R, win rate, equity or ranking were printed or computed. Risk-module stdout was filtered by line prefix and discarded. Nothing was pushed.

## What was run
- Code: repository HEAD `47d69bbdd1246684e6707586add79a76218b8e9e` (docs-only on top of `a64e6af`, the last-bar `compute_features` optimisation; `git diff a64e6af 47d69bb -- src tests params docs` is empty), no `src/` change in the working tree when the process started at 10:01:06Z (only the unrelated `.planning/config.json`, `.gsd/`, `.planning/milestone.lock`). While the probe ran, other work outside this probe modified `src/research/manifest.py` (10:08:12Z) and added `src/research/manifest_build.py` and `tests/test_research_manifest_build.py` (10:13-10:14Z); all modules were imported at process start, so the probe ran the HEAD code; those files were not touched or committed here. Simulator semantics 2.1.0, protocol v2.4.0.
- Script: adapted COPY of `evidence/16-37-12symbol-probe-a01-v240-script.txt` (sha256 `c66ca8e75527bd22f64fb204844ca5c43d69d60d17d09de3f528e87cb8d97f22`, not edited). Scratchpad name `full584/full584_a01.py`, committed as `evidence/16-37-full584-timing-a01-script.txt`, sha256 `a43db2da7cd8735de1bd75db5c0cea07a0647f619d12d572ade516290fa30503`. Run with the repo `.venv` Python 3.13.15, `python -I`, one process, 2026-10-15 10:01:06Z to 10:17:10Z.
- Changes against the source script: the five windows of `research_splits(manifest)` run sequentially instead of the Development window only; per split, the calls of `_run_split` are replicated (`build_case_input_data` with `as_of_day_utc = validation_end_utc.date()` = 2026-05-10, `to_case_input` with the `terminal_settlements` key only when `terminal_settlement_case_rows` returns a row, `ParquetMinuteSource` over the split, then `simulate_detailed` with `evaluate_risk`, which is what `simulator.run` calls); the Holdout read guard; a per-split dataset-id consistency check; per-split memory peaks; output reduced to timing, memory and file counts (Development: total record count and `settlement_count` only); all REEF/ledger/per-symbol diagnostics removed.
- Inputs: 12 S0 symbols, S0 constraints, point `research-run-1-a01` (trend-pullback), equity 600, risk_rate 0.005, the REEFUSDT `TerminalDeclaration` (DELISTED_CAPPED, T = 2025-01-22T09:00Z) and the `TerminalSettlement` recomputed from the committed evidence bytes exactly as in the previous probe.
- Memory guard: sample every 0.5 s, `os._exit(3)` if the process working set > 3 GiB or system available physical memory < 1 GiB. It never fired. Exit code 0, stderr empty.
- Machine: Intel Core i7-10700, 15.83 GiB RAM. Available RAM at start 5.51 GiB; minimum seen 4.26 GiB (during the Development split). Nothing else heavy ran.

## Preconditions verified (in the probe process, before any simulation)
- Inventory listing `inventory-admin-machine.sha256` sha256 `b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34`.
- S0 constraint file sha256 `4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f`, 12 symbols (1000PEPEUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, DOGSUSDT, ETHUSDT, REEFUSDT, SOLUSDT, SUIUSDT, WIFUSDT, WLDUSDT, XRPUSDT); all 49,549 inventory files dated before 2026-05-10 belong to these 12 symbols.
- Dataset id derived from the inventory over those 49,549 files equals `34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2`.
- All 49,549 files dated before 2026-05-10 were re-hashed from disk and equal the inventory (44.1 s). No file dated on/after 2026-05-10 was opened.
- Runner checks through landed code: `research_run._load_constraints` (sha256 + 12 rows), `check_terminal_settlement_evidence` (recompute from committed bytes), `research_splits(manifest)` equal to the expected five windows, `terminal_settlement_case_rows` returning the REEF row (bounds 0.000845 / 0.000887) for the Development window only and no row for any Validation fold.
- Per split: the case `dataset_id` equals the id recomputed from the inventory hashes of exactly the files the builder hashed (all of them present in the inventory).

## Results
| split | days | case build (s) | simulation (s) | split wall (s) | peak working set in split (GiB) | min available in split (GiB) | files hashed by builder | parquet files read by builder | minute parquet files read by simulation |
|---|---|---|---|---|---|---|---|---|---|
| Development [2024-10-03, 2025-07-22) | 292 | 127.5 | 346.1 | 488.0 | 0.589 | 4.26 | 25,313 | 18,665 | 1,878 |
| Validation fold 1 [2025-07-22, 2025-10-03) | 73 | 40.3 | 70.0 | 114.6 | 0.397 | 5.27 | 6,059 | 4,453 | 309 |
| Validation fold 2 [2025-10-03, 2025-12-15) | 73 | 37.6 | 65.4 | 107.4 | 0.395 | 5.46 | 6,059 | 4,453 | 290 |
| Validation fold 3 [2025-12-15, 2026-02-26) | 73 | 37.8 | 63.0 | 104.3 | 0.395 | 5.71 | 6,059 | 4,453 | 257 |
| Validation fold 4 [2026-02-26, 2026-05-10) | 73 | 36.3 | 64.0 | 104.2 | 0.385 | 5.69 | 6,059 | 4,453 | 242 |
| all five splits | 584 | 279.5 | 608.5 | 919.1 | 0.595 (process peak) | 4.26 | | | |

- Process wall: 963.2 s (44.1 s preconditions incl. the 49,549-file re-hash, 919.1 s for the five splits).
- "split wall" also contains about 14.4 s (Development) and about 4 s (each fold) of probe-only work: the dataset-id consistency recomputation and the phase/memory logging. The runner does not do this per split.
- Development only: total record count 9,970 and `settlement_count` 1, identical to the earlier pre-optimisation Development probe (`16-37-12symbol-probe-a01-v240.md`), which is consistent with the optimisation being byte-identical (a count match, not a byte comparison of outputs).
- Minute parquet counts vary per fold because the minute source loads a day only when the simulation asks for it.

## Arithmetic from this one measurement
- Per point, as measured: 919.1 s (about 15.3 min) for the five splits.
- 16 points (one family) one after another: 16 x 919.1 = 14,706 s, about 4.1 h.
- 48 points one after another: 48 x 919.1 = 44,117 s, about 12.3 h.
- Three family processes in parallel (16 points each) at the 92 percent efficiency measured in `16-37-timing-probe-v240.md` (throughput 2.76x one process): 16 x 919.1 / 0.92 = 15,984 s, about 4.4 h. INFERENCE: it assumes every grid point costs what a01 costs, and that the 92 percent efficiency measured on 30-day windows (peak 0.19 GiB per process) holds for 584-day runs (peak here 0.6 GiB per process, so about 1.8 GiB for three, against 4.26 GiB minimum available seen today). b01/c01 and the other parameter sets were not measured at this length and may be faster or slower.
- Comparison with the previous Development-only probe (before the last-bar `compute_features` optimisation): 3,743 s wall / 3,604 s simulation. Development now: 488.0 s split wall / 346.1 s simulation, i.e. simulation about 10.4x faster and the Development split about 7.7x faster. The whole 584-day point (919.1 s) now takes about a quarter (24.6 percent) of what the Development split alone took before.

## What this establishes / does not establish
Establishes:
- With code a64e6af, the case building and simulation of grid point a01 over Development plus the four Validation folds (584 days, 12 symbols) take 919.1 s in one process, peak working set 0.595 GiB, minimum system available memory 4.26 GiB, without touching Holdout data.
- Case building is now a large share of the cost (279.5 s of 919.1 s, about 30 percent).

Does not establish:
- Not included: the runner's one-time whole-range store check (`_check_manifest_against_store`, one extra `build_case_input_data` over the 584 days per run, not per point; by the build times above roughly 280 s, not measured), analytics post-processing (feasibility, plateau summaries, mark-hole counts), ExperimentRecord construction and writing, report rendering, authorization and registry checks.
- One parameter set only (a01, trend-pullback); other points, in particular breakout-retest and range-mr, were not measured at this length.
- One run only; no repeat, so run-to-run variation is unknown (the 30-day probe saw 5 to 7 percent variation under load).
- No Holdout, and no outcome figures of any kind for the Validation folds.
- The parallel figure is an inference, not a measurement.
