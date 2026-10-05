---
phase: 14-backtest-causality-rewrite
plan: 14
subsystem: backtest
tags: [backtest, smoke, real-data, measurement, determinism, tracemalloc, cli]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-10 build_case_input_data (case-input v2) and ParquetMinuteSource; 14-12 simulator.run(case, minute_source=...) as the public entry point"
provides:
  - "scripts/smoke_backtest_realdata.py: argparse CLI that runs simulator.run twice over one symbol and one explicit closed-UTC-day window and prints runtime, tracemalloc peak, rss peak, trade/NO_TRADE counts, dataset_id and digest; exit 0 only when the two digests match"
  - "tests/test_smoke_backtest_cli.py: 16 CI-safe tests on a synthetic raw root (determinism, constraint-source fail-closed, credential safety, argument validation, no-OI store, holes still fail closed)"
  - "Measured real-data cost of the v2 simulator on BTCUSDT x 90 days (table below) and the D052 input"
affects: [14-15, 14-16]

requirements-completed: [BKTS-02]

actuals:
  tokens: 5200
  tasks: 2
  commits: 4
plan_head_before: e2db9bb4825368539f4e9a243c15fddb0b5a7035
plan_head_after: 7893a0e29be9095e2a47136da8105c53432a85f1

tech-stack:
  added: []
  patterns:
    - "Measurement CLI never reads the clock for the data window (--end-day and --days are required); time.perf_counter measures durations only"
    - "A series the engine does not consume is not requested from the case builder, so a missing series cannot block a run, while every requested series still fails closed on a hole (D-19)"

key-files:
  created:
    - scripts/smoke_backtest_realdata.py
    - tests/test_smoke_backtest_cli.py
  modified: []

key-decisions:
  - "The smoke script requests series=(trade, intrabar_1m, mark_1m, funding) and not open_interest: the v2 engine has no OI input (case-input v2 has no OI key) and the Binance OI statistics endpoint serves about 30 days, so a 90-day OI history cannot be backfilled locally. No allow_gaps is used for OI."
  - "Constraint history for the real run came from a one-row BTCUSDT JSON export of a live exchangeInfo call (tick 0.10, step 0.001, min_qty 0.001, min_notional 50, observed 2026-10-05T08:18:37+00:00) because the dev database symbol_metadata table is empty; the database was not touched"

patterns-established:
  - "Smoke CLI exit codes: 0 ok, 1 digest mismatch, 2 usage or missing constraint source, 3 store/constraint source/run failure (exception type name only)"

duration: about 3 hours including two real-data runs of about 13 minutes each
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 14: Real-data Smoke of the v2 Simulator Summary

**A credential-safe smoke CLI runs the v2 simulator twice on 90 days of real BTCUSDT data with byte-identical output digests; one run costs about 6.3 minutes with tracemalloc on and the traced Python heap peaks at about 7.8 MB.**

## Accomplishments

- `scripts/smoke_backtest_realdata.py` (Task 1, tracer): `--symbol`, `--days`, `--end-day` (all required, no wall-clock default), `--raw-root`, `--strategy-id`, `--parameter-set-id`, `--equity`, `--risk-rate` and exactly one of `--constraints-json` or `--database-url-env`. It builds the v2 case once, creates a lazy `ParquetMinuteSource`, runs `simulator.run` twice under `tracemalloc` and prints one `key=value` block per run, then `digests_match=true|false`. The database URL is read once from the named variable and never printed; any database failure reduces to its exception type name (T-14-27).
- `tests/test_smoke_backtest_cli.py`: 16 tests, all passing: matching digests on a synthetic two-day root, exit 2 without a constraint source or with both, non-zero and no leak for an unset, unreachable or malformed database URL, six invalid-argument cases, no clock default for the window, a store with no OI partitions still runs, and a missing 1m trade day or a missing 1m mark day still fails closed (exit 3, `CaseInputGapError`, no digest).
- Task 2: real-data run on the local Phase 13 store, BTCUSDT, 90 closed UTC days (2026-07-04 to 2026-10-01 inclusive), exit 0.

## Measurements (BTCUSDT, 90 days, end-day 2026-10-01, baseline-v5, equity 1000, risk-rate 0.005)

Command: `.venv/Scripts/python scripts/smoke_backtest_realdata.py --symbol BTCUSDT --days 90 --end-day 2026-10-01 --constraints-json <btcusdt_constraints.json>`

| Key | Run 1 | Run 2 |
|-----|-------|-------|
| runtime_seconds | 384.617 | 371.199 |
| tracemalloc_peak_bytes | 7552745 | 7767720 |
| rss_peak | unavailable | unavailable |
| trade_count | 162 | 162 |
| end_of_data_count | 0 | 0 |
| no_trade_counts | {"CONFLICT_WITH_OPEN_POSITION":2,"COST_TO_RISK_EXCEEDED":100,"NO_TRADE_REGIME":1200,"STOP_TOO_TIGHT":60,"WARMUP_INSUFFICIENT":796} | identical |
| dataset_id | 2063b8caa9bdb2a6855ed0e538c1a1c923f3bf0d597b2c2fd1db1cd8793cdeb8 | identical |
| digest | 806c885e4422dc4bec8a94b928bccd9d03eb2ff90580acadf64d7e6343f08bb4 | 806c885e4422dc4bec8a94b928bccd9d03eb2ff90580acadf64d7e6343f08bb4 |

`digests_match=true`, exit code 0. The digest and dataset_id also equal the values from the orchestrator's earlier in-process run of the same configuration (806c885e..., 2063b8ca...), a third independent confirmation of reproducibility. An earlier orchestrator run measured 383.240 s and a 7772011 byte peak.

Caveats that bound how far these numbers can be read:

- `rss_peak` is `unavailable`: the stdlib `resource` module does not exist on Windows. The only memory figure is the Python heap peak from `tracemalloc`.
- The case input and the `ParquetMinuteSource` are built before `tracemalloc.start()`, so the 7.8 MB peak covers allocations made during a run (the simulator working set, lazily loaded day caches and results) and not the case data itself or native Arrow/Polars buffers. It is evidence that the per-run working set is small and bounded, not a whole-process footprint.
- `tracemalloc` slows allocation-heavy Python code, so `runtime_seconds` is inflated by an unmeasured factor. The run without tracing was not timed (the plan asks for one measured configuration; adding a `--no-trace` option was out of scope).
- The runs are sequential in one process, so run 2 reads files already in the OS page cache; the two runtimes (371 to 385 s) differ by about 3.5 percent.

### Assumption: constraints are today's values applied to all 90 days

The dev database `symbol_metadata` table is empty, so the run used a JSON export of one BTCUSDT row from a live Binance `exchangeInfo` call made today (tick 0.10, step 0.001, min_qty 0.001, min_notional 50). That row is observed after the window start, so the engine back-extrapolates it under D-30 (flagged as extrapolated and counted in the report). The effect is that today's constraints apply to all 90 days. This is an assumption: it is valid for a runtime, memory and determinism smoke, and it is NOT valid for strategy evaluation. The trade and NO_TRADE counts above are plumbing evidence only and must not be read as strategy performance.

### Extrapolation to a full run (ESTIMATE, not measured)

Per-bar cost is constant once the strategy window is fixed, and 1m processing is linear in minutes, so cost scales roughly linearly with days and symbols.

- Per symbol-day: about 380 s / 90 = 4.2 s (tracemalloc on).
- 24 months (about 730 days): about 8.1 x 380 s = about 3,080 s, about 51 minutes per symbol.
- Universe: the local store holds 19 symbols with 1m data, so about 16 hours; with the 12-symbol universe assumed in 14-RESEARCH Pitfall 1 it is about 10 hours. Both are overnight-class runs, not minutes.
- Because `tracemalloc` inflates, the true figure is lower by an unknown factor; the RESEARCH estimate for a trailing-window evaluate was about 2.2 to 3.6 hours for 12 symbols before the minute loop, so the order of magnitude is consistent and the minute loop is not negligible.
- A holdout, walk-forward or parameter-sweep campaign multiplies this by the number of runs.

### D052 input: is an incremental feature series needed after Phase 15?

Recommendation: yes, record it in D052 as a deferred follow-up, not as a Phase 14 blocker. A single full run is feasible (hours), but every experiment, sweep and re-run after a spec change pays the full price, and the windowed recompute is the measured dominant cost of a per-bar loop. The incremental series touches `src/core/features.py`, which Phase 15 rewrites (confirmed pivots), so it belongs after Phase 15 as an exact-equivalence refactor (incremental output must equal windowed output). Before committing to it, re-time one run without tracemalloc (and with a POSIX RSS reading) so the decision rests on an uninflated figure.

## Task Commits

1. **Task 1 (tracer), RED**: `7a3c86c` failing CLI tests
2. **Task 1 (tracer), GREEN**: `b494533` smoke CLI for the v2 simulator
3. **Task 2, RED**: `4ae3acb` failing test, the smoke script must not request open_interest
4. **Task 2, GREEN**: `7893a0e` smoke script does not request open_interest

The real-data run itself produces no commit (output is in this SUMMARY).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The smoke script requested open_interest and failed on a real store**
- **Found during:** Task 2 (first real-data run)
- **Issue:** `build_case_input_data` defaults to `series=SERIES_ALL`, which includes `open_interest`. The local store has no 90-day OI history (the Binance OI statistics endpoint serves about 30 days), so the run raised `CaseInputGapError: open_interest/5m 2026-07-04..2026-10-02 missing=25920`. Nothing in `src/core`, `src/risk`, `src/backtest` or params uses OI and case-input v2 has no OI key.
- **Fix (user-approved):** pass `series=("trade", "intrabar_1m", "mark_1m", "funding")` with a comment. `allow_gaps` is not used for OI. RED first: `test_store_without_open_interest_still_runs` failed with exit 3 before the fix; two parametrized tests prove a missing 1m trade day or 1m mark day still fails closed.
- **Files modified:** scripts/smoke_backtest_realdata.py, tests/test_smoke_backtest_cli.py
- **Commits:** 4ae3acb (RED), 7893a0e (GREEN)

### Other departures

- **Constraint source:** the plan allowed a constraints JSON or a database URL; the database table was empty, so the JSON export described above was used. Recorded as an assumption, not a defect.
- **Static typing note (not fixed, Windows only):** `mypy` reports `Module has no attribute "getrusage"/"RUSAGE_SELF"` for the `resource` use in `_rss_peak` because mypy analyses for `win32`; the call is guarded by the `ImportError` branch at runtime. `ruff check` and `ruff format --check` are clean. This line came from Task 1 and was left alone.

## Verification

- `.venv/Scripts/python -m pytest tests/test_smoke_backtest_cli.py -q -p no:cacheprovider`: 16 passed.
- Real-data run: exit 0, `digests_match=true`.
- The full `pytest -m "not docker"` suite was not run (known Windows access violation, coordinator instruction); `tests/test_analytics_cli.py` was not touched (31 failures owned by plan 14-15 Task 3).

## Known Stubs

None.

## Threat Flags

None. The script adds no network endpoint; the only external read is the optional database named by an environment variable, covered by T-14-27 (type name only, tests assert no URL, user, host or password in output). T-14-28 is mitigated by the lazy `ParquetMinuteSource`; the measured peak is recorded above.

## Regeneration inventory

none

## Self-Check: PASSED

- FOUND: scripts/smoke_backtest_realdata.py, tests/test_smoke_backtest_cli.py
- FOUND commits: 7a3c86c, b494533, 4ae3acb, 7893a0e (`git rev-list --count e2db9bb..HEAD` = 4)
