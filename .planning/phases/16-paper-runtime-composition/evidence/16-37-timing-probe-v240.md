# 16-37 timing probe (3 parallel processes and cProfile), 30-day Development window, simulator 2.1.0: timing and memory only

date: 2026-10-15. Authority: the user wrote "ok theo khuyến nghị, chạy hai phép đo" in this session, which authorises exactly two timing measurements (parallel speed-up; one cProfile run) and nothing else.

Hard limits respected: no `run.py main`, no `assemble`, no ExperimentRecord, no manifest file or freeze, no O-03, no authorization file, `docs/research/holdout_consumed.json` untouched, no change under `src/`, `tests/`, `params/` or `docs/research/`. `as_of_day_utc` was 2024-11-02; only files dated before 2024-11-02 were hashed or read (2,750 files re-hashed equal to the inventory); no Validation or Holdout day and no file dated on/after 2025-07-22 was opened. No PnL, expectancy, R, win rate, equity, ranking or per-parameter-set comparison was computed. Only timings, memory, a plain total record count and profiler function times are reported. Nothing was pushed.

## What was run
- Code: repository HEAD `06b0f94da47e104d2d9d9a7ec2407b1ecfd22ec5`, no `src/` change in the working tree (only the unrelated `.planning/config.json`, `.gsd/`, `.planning/milestone.lock`). Simulator semantics 2.1.0.
- Script: adapted COPY of `evidence/16-37-12symbol-probe-a01-v240-script.txt` (sha256 `c66ca8e75527bd22f64fb204844ca5c43d69d60d17d09de3f528e87cb8d97f22`, committed one not edited). The adapted copy is `evidence/16-37-timing-probe-v240-script.txt` (scratchpad name `timing_probe.py`), sha256 `7e725d2ac4c5a67b6ec6084dec2a602bb16c2f8b1e6dfe2b9f5b29ce8ab490be`. Parameters: inventory, grid point id, mode (`plain` or `cprofile`), prof path. Changes: AVAIL_FLOOR 1.5 GiB (was 1 GiB); window `[2024-10-03T00:00Z, 2024-11-02T00:00Z)`; no REEF `TerminalDeclaration` and no `terminal_settlements` key (the builder rejects an empty list, so the key is omitted); constraints are the 12 S0 rows read after the same sha256 check (S0 sha256 `4307eec7...1e11d3f`, inventory listing sha256 `b9b8426a...982b34`, dataset id `34a1efa2...d18d7d2` derived from the inventory, as before); a cProfile switch around the `simulate_detailed` call only; a one-line TIMING output. Run with the repo `.venv` Python 3.13.15, `python -I`.
- Memory guard in every process: sample every 0.5 s, `os._exit(3)` if working set > 3 GiB or available physical memory < 1.5 GiB. It never fired.
- Points (only as three differently parameterised workloads): `research-run-1-a01` (trend-pullback), `research-run-1-b01` (breakout-retest), `research-run-1-c01` (range-mr). 12 symbols, equity 600, risk_rate 0.005.
- A first attempt of stage 1a failed in 15 s with a script bug (`terminal_settlements must not be empty (omit the key instead)`), before any simulation; the script was corrected and the stage re-run once. Not a guard abort and no measurement was lost. A later identical re-run of 1a was not made.
- Machine: Intel Core i7-10700, 16 logical processors, 15.83 GiB RAM total. Available RAM at start: stage 1a 6.42 GiB, stage 1b 6.30 GiB, profile stage 6.67 GiB (all above the 3 GiB start threshold). Stages ran one after the other, never overlapping; nothing else heavy was run.

## Measurement 1: parallel speed-up
| stage | process | exit | wall of process (s) | case build (s) | simulation (s) | peak working set (GiB) | min system available (GiB) | n_records |
|---|---|---|---|---|---|---|---|---|
| 1a baseline | a01 alone | 0 | 130.3 (outer shell wall 130) | 14.5 | 113.2 | 0.188 | 6.09 | 0 |
| 1b group | a01 | 0 | 139.7 | 17.0 | 119.8 | 0.187 | 5.83 (group) | 0 |
| 1b group | b01 | 0 | 138.9 | 16.8 | 119.4 | 0.179 | 5.83 (group) | 0 |
| 1b group | c01 | 0 | 141.2 | 17.0 | 121.4 | 0.179 | 5.82 (group) | 0 |

"wall of process" is `process_s` from the script (start of interpreter work to the end, preconditions with the 2,750-file re-hash included, about 1.7 s). Group wall time (first process start to last process end, measured by the shell): 141.6 s.

Speed-up: three processes were completed in 141.6 s, against the a01 baseline of 130.3 s for one. Running three one after the other at the baseline cost would take about 391 s, so the group is about 2.76 times the single-process throughput (about 92 percent of ideal 3x); per-process simulation time grew by 5 to 7 percent (113.2 s to 119.4 to 121.4 s), build time by about 16 percent. Peak memory per process stayed under 0.19 GiB and system available memory never went below 5.8 GiB. Caveat: b01 and c01 are different parameter sets and different strategies from a01 (and baselines of b01 and c01 were not measured), so this compares group wall time with the a01 baseline only; their near-equal times (all within 3 percent) suggest similar cost on this window, but that is not a proof. The "equal work" check is weak here: all four runs have `n_records` 0 (see below).

## Measurement 2: cProfile (a01, same window, one process)
Run under cProfile around the `simulate_detailed` call only; setup untimed by the profiler. Plain process 130.3 s versus cProfile process 288.9 s (build 14.4 s, simulation 272.0 s versus 113.2 s plain): the profiler inflates simulation time by about 2.4x, so use the proportions only. Peak working set 0.177 GiB. `.prof` saved in the scratchpad (not in the repo): `C:\Users\admin\AppData\Local\Temp\claude\C--Users-admin-Music-Trading\02361c36-76cc-4c29-a6a4-39726053ab06\scratchpad\tp\a01.prof`.

Call structure: `simulate_detailed` 1 -> `_Engine.run` 1 -> `_evaluate_signal` / `_evaluate_strategy` 8,640 calls (12 symbols x 720 hourly bars) -> `src/core/strategy.py:680 evaluate` 8,640 calls -> `src/core/features.py:320 compute_features` 17,208 calls = 270.1 s of 272.0 s profiled simulation time (99.3 percent cumulative).

### Top 25 by cumulative time (profiler seconds; ncalls = total calls)
| ncalls | function (file:line) | cumulative s |
|---|---|---|
| 2 | engine.py:944 simulate_detailed | 271.98 |
| 1 | engine.py:353 run | 271.38 |
| 8,640 | engine.py:723 _evaluate_signal | 271.36 |
| 8,640 | engine.py:747 _evaluate_strategy | 271.32 |
| 8,640 | core/strategy.py:680 evaluate | 270.98 |
| 17,208 | core/features.py:320 compute_features | 270.10 |
| 51,624 | core/features.py:63 _ema_series | 110.65 |
| 8,283,660 | core/features.py:52 ema_update | 74.53 |
| 17,208 | core/features.py:122 _atr_series | 58.73 |
| 34,416 | core/features.py:166 _swing_series | 57.94 |
| 26,282,064 | core/types.py:148 _ok | 52.28 |
| 17,208 | core/features.py:201 _zone_series | 39.43 |
| 23,794,428 | core/_decimal.py:40 _mul | 33.11 |
| 23,475,216 | core/_decimal.py:54 _sub | 29.92 |
| 17,974,920 | core/_decimal.py:47 _add | 23.41 |
| 77,272,152 | built-in `_decimal.localcontext` | 22.04 |
| 3,883,860 | core/features.py:104 true_range | 20.16 |
| 31,120,704 | core/types.py:133 __post_init__ | 19.61 |
| 77,272,152 | `decimal.ContextManager.__exit__` | 19.16 |
| 3,573,307 | built-in `min` | 17.80 |
| 3,590,587 | built-in `max` | 17.31 |
| 15,718,452 | core/_decimal.py:22 _q | 14.90 |
| 31,202,640 | core/types.py:32 _require_non_empty | 10.60 |
| 4,838,640 | core/types.py:153 _invalid | 9.04 |
| 71,615,104 | built-in `isinstance` | 8.24 |

### Top 25 by tottime (profiler seconds; total profiled time 247.6 s)
| ncalls | function (file:line) | tottime s | cumulative s |
|---|---|---|---|
| 77,272,152 | built-in `_decimal.localcontext` | 22.04 | 22.04 |
| 23,794,428 | core/_decimal.py:40 _mul | 20.36 | 33.11 |
| 77,272,152 | `decimal.ContextManager.__exit__` | 19.16 | 19.16 |
| 23,475,216 | core/_decimal.py:54 _sub | 17.47 | 29.92 |
| 8,283,660 | core/features.py:52 ema_update | 17.39 | 74.53 |
| 26,282,064 | core/types.py:148 _ok | 14.78 | 52.28 |
| 17,974,920 | core/_decimal.py:47 _add | 13.96 | 23.41 |
| 3,573,307 | built-in `min` | 11.55 | 17.80 |
| 3,590,587 | built-in `max` | 11.14 | 17.31 |
| 15,718,452 | core/_decimal.py:22 _q | 10.25 | 14.90 |
| 31,120,704 | core/types.py:133 __post_init__ | 9.04 | 19.61 |
| 17,208 | core/features.py:122 _atr_series | 8.95 | 58.73 |
| 51,624 | core/features.py:63 _ema_series | 8.26 | 110.65 |
| 71,615,104 | built-in `isinstance` | 8.19 | 8.24 |
| 31,202,640 | core/types.py:32 _require_non_empty | 7.17 | 10.60 |
| 17,208 | core/features.py:201 _zone_series | 6.91 | 39.43 |
| 34,416 | core/features.py:166 _swing_series | 6.65 | 57.94 |
| 75,028,464 | core/features.py:191 genexpr | 6.24 | 6.24 |
| 75,028,464 | core/features.py:189 genexpr | 6.17 | 6.17 |
| 37,834,438 | built-in `list.append` | 5.77 | 5.77 |
| 3,883,860 | core/features.py:104 true_range | 4.71 | 20.16 |
| 3,743,928 | core/_decimal.py:33 _div | 3.34 | 5.34 |
| 4,838,640 | core/types.py:153 _invalid | 2.62 | 9.04 |
| 7,734,912 | built-in `abs` | 1.22 | 1.22 |
| 17,208 | core/features.py:290 _detect_gaps | 1.18 | 1.71 |

### Where the simulation time goes (shares of profiled time, tottime)
- `src/core` feature computation (`compute_features` and below: EMA, ATR, swings, zones, `_decimal` helpers, `types` validators): 167.6 s tottime of 247.6 s (67.7 percent) in the repo files, plus 79.4 s (32.1 percent) in built-ins called from them (decimal `localcontext`/`__exit__`, `min`, `max`, `isinstance`, `list.append`). Cumulatively `compute_features` is 99.3 percent of the profiled simulation time. The Decimal context handling alone (`localcontext` plus `__exit__`) is 41.2 s, about 16.6 percent, of tottime.
- `src/risk/*` (including structured logging and stdout writes): 0.0 percent. It is not called at all in this window.
- parquet / minute-source I/O (`src/data`, `ParquetMinuteSource`, polars, pyarrow): 0.0 percent. It does not appear in the profile.
- `src/backtest` engine code itself: 0.2 percent (0.51 s).

### Output volume
Plain-run stdout is 659 bytes (a handful of PHASE/TIMING lines), against 4.5 MB in the earlier full-window run. Reason: in this window no signal reached sizing/risk or a position, so none of the `risk.quantize`, `risk.cost_rates`, `risk.cost_guard` lines were written. The stdout comparison is therefore not a like-for-like test of logging cost.

## What this establishes / does not establish
Establishes (for this 30-day, 12-symbol window on code at HEAD `06b0f94`):
- Three independent processes on the 16-logical-processor machine run in parallel with a group wall time 8.7 percent above the single-process baseline (about 2.76x throughput, three different parameter sets), with under 0.19 GiB per process and no memory pressure.
- In this window the simulation time is almost entirely re-computation of features in `src/core` (`compute_features` called 17,208 times, once per symbol, timeframe and signal bar), dominated by Decimal arithmetic and its context handling.

Does NOT establish:
- Full-run cost. The real run reads Development plus 4 Validation folds, about 584 days; scaling from 30 days to 292 or 584 days is an inference, not measured. The earlier full-Development single point took 3,604 s of simulation, about 43 ms per hourly signal-bar evaluation (292 days x 24 x 12 = 84,096 evaluations), while here it is 113.2 s / 8,640 = 13 ms; per-bar cost is therefore not constant, and the difference (trades, risk, minute I/O, longer state) is not explained by this probe.
- Any behaviour of the risk module or the minute-source I/O: this window produced `n_records` 0 for every run (no trade or reject record), so those code paths were not exercised and their share of a real run is unknown from this probe. The profile shows only the cost of the pure feature path.
- That the group speed-up holds for more than three processes, for heavier windows (where the minute source reads Parquet and memory per process is about 0.58 GiB, as measured earlier), or when disk I/O is active; the b01 and c01 single-process baselines were not measured.
- Anything about results: no research result, PnL or ranking of any kind; the near-equal timings of a01, b01 and c01 say nothing about their quality.
- profiler overhead: the cProfile figures are inflated (2.4x total) and are only usable as proportions; fine-grained numbers for tiny functions are distorted most.
