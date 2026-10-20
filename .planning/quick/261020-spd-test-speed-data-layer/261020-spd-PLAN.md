---
quick_id: 261020-spd
date: 2026-10-20
type: quick
autonomous: true
files_modified:
  - tests/test_case_input_builder.py
  - tests/test_research_runner.py
  - tests/test_research_manifest_build.py
  - tests/test_research_terminal_settlement_integration.py
  - tests/test_research_known_gap_reason.py
  - tests/test_research_warmup.py
  - tests/conftest.py
  - src/data/case_input.py
  - tests/test_case_input_relative_paths_equivalence.py
  - src/research/run.py
  - tests/test_research_case_data_reuse.py
  - .planning/STATE.md
---

# 261020-spd: faster research tests in the data layer (owner "option B")

## Authority
Owner choice "option B" (2026-10-20) after the read-only profile of the slowest research tests (85-95 % of their time is in `src/data`, not in the engine). Changes A1, A2, A3, B1, B2 in this order, one commit each, each with evidence that it is behaviour-preserving. Nothing else from the profile: no change to the DuckDB gap check in `src/data/coverage.py`, no fsync or `atomic_write_parquet` change, no sha256 cache, no change to `src/core` or `src/backtest`. `SIMULATOR_SEMANTICS_VERSION`, protocol, manifest, grids, authorization files, `params/` and every record and hash stay byte-identical. `docs/DECISIONS.md` is not edited. Machine rules: one heavy process at a time, no xdist, targeted test files only (the full gate is plan 16-65's one sequential run).

## Baseline (each module alone, `-p no:cacheprovider -p no:xdist`, measured 2026-10-20 before any change)
test_research_warmup.py 119.0 s, test_research_checkpoint.py 87.1 s, test_research_terminal_settlement_integration.py 82.0 s, test_case_input_builder.py 109.1 s, test_research_known_gap_reason.py 82.8 s.

## A1 - `build_store(..., oi=False)` (tests only)
- `tests/test_case_input_builder.py::build_store` gets `oi: bool = True` (default unchanged: OI written). `oi=False` skips the 5-minute OI snapshots (one parquet file each, most of the store write time).
- Used in the modules that only build `ENGINE_SERIES` (open interest is never in it): test_research_runner.py (also the store of test_research_checkpoint.py), test_research_manifest_build.py, test_research_terminal_settlement_integration.py, test_research_known_gap_reason.py (every `build_store` call), test_research_warmup.py (the terminal-world test).
- Kept with OI: test_case_input_builder.py (reads and asserts OI under `SERIES_ALL`), test_smoke_backtest_cli.py (copies the store and asserts that `data_class=oi` exists before removing it).
- Proof per module (scratch experiment, not committed): a pytest plugin wraps every data-layer read entry point (`read_partitions`, `_read_rows`, `_observed_times_ms`, `gap_ranges_for_files`, `_file_sha256`, `_relative_posix`, `pl.read_parquet`, `pl.scan_parquet`, DuckDB `execute`) and fails on any path naming `data_class=oi`; each module is run with `build_store` forced back to `oi=True`, so OI files exist and any read would be caught. Positive control: the guard fails `test_builder_reads_published_partitions` (SERIES_ALL). Then each module runs green with `oi=False` (files absent).

## A2 - one shared terminal world (tests only)
- The identical world (`build_store(STORE_START..VAL_END, LONG, oi=False)` + `_publish_terminal_symbol(TERM)` + constraints + declaration + dataset_id) and the identical LOWER_BASE `_run` are built once per session by two fixtures in `tests/conftest.py` (`terminal_world`, `terminal_lower_run`), from a plain `build_world(base_dir)` in test_research_terminal_settlement_integration.py.
- Users: the `world` and `paired` fixtures of test_research_terminal_settlement_integration.py (paired = shared lower run + its own upper run), the `store` fixture of test_research_known_gap_reason.py (the world's store is that module's store: same writers, same range, same symbols), and `test_a_terminal_instant_inside_the_warmup...` in test_research_warmup.py (its own copy of the world and of the lower run are replaced by the shared ones; assertions unchanged).
- Read-only: the session fixtures check at teardown that the store tree (sha256 per file) and the captured run (canonical JSON of records, cases, outputs) are unchanged, so a test that mutates them fails instead of leaking. No test writes into them today (every writer uses its own tmp_path).

## A3 - cached manifest dataset_id in test_research_warmup.py
- `_manifest()` computes the same `build_case_input_data(...).dataset_id` for two `val_end` values over and over; cache it in a module dict keyed by `(store path, val_end)`. Same values (the store is module-scoped and never written).

## B1 - resolve the raw root once (src/data/case_input.py)
- `_relative_posix` resolved the file and the root per call and was called twice per file (files tuple, then `dataset_identity`). New private `_relative_posix_each` resolves each file once and the root once (lazily, after the first file, inside the same `try`, so no root resolve for an empty list and the same `CaseInputError` text and cause); `_files_and_identity` relates every used file once and returns the files tuple and the dataset_id; `dataset_identity` (public) keeps its signature and its per-file order (relate, then hash, file by file), so its errors are unchanged too.
- Error order kept: the builder relates all used files before hashing any (as before: the files tuple was built first), so an outside file still wins over an unreadable one there; `dataset_identity` alone still interleaves.
- Equivalence test `tests/test_case_input_relative_paths_equivalence.py`, method of 261015-mvq: the old functions are kept as a reference copy; full builder output (`==` and `repr`) new vs old tail on a two-symbol store and copies without funding, mark and 4h, for seven series choices and with minute rows; helper outputs for absolute, relative, trailing-separator, backslash, slash and `..` root spellings, several file orders, duplicates and an empty list; a root through a symlink or junction (skip only if neither can be created); files outside the root, a root-prefixed sibling, a missing file before/after an outside file; a root that cannot be resolved (NUL), with and without files. Exceptions compared by type, message and cause type.

## B2 - build the case data once per window (src/research/run.py)
Questions answered before the change (code read at HEAD):
- Inputs: `_simulate_split` builds with `raw_root`, `manifest.symbols`, `warmup_start(manifest, window)`, `window.end_utc`, `manifest.validation_end_utc.date()`, the manifest intervals, `ENGINE_SERIES` and `manifest.known_gaps`. Nothing of the grid point enters the build (the point only enters `to_case_input` scenario keys and the parameter set). Within one `run_research` call manifest and raw_root are fixed, so the result is a function of the window.
- Mutability: `CaseInputData` is a frozen dataclass of tuples; its rows are `dict[str, str | int | None]` (immutable values), `allowed_gaps` are frozen `GapRange`. The runner touches it only through `data.dataset_id` and `data.to_case_input(...)`, which builds a new dict and copies every row (`dict(b)`), so the simulator never receives (and cannot mutate) a cached row. No copy or freeze needed; a test asserts the cached rows are unchanged after a multi-point run.
- Checkpoint and order: loops stay point-outer, window-inner; records, checkpoint files and print lines keep their order. The cache lives in one `run_research` call (a dict keyed by window) and is filled lazily inside `_simulate_split`, which is only reached for a window that still has to be simulated (a window whose checkpoint exists is loaded and never built). Errors raise at the same point as before: the first build of a window happens at the same (point, window) step as the first build today, and a failing build is never cached (the exception ends the run). A resumed run is a new call with an empty cache. `_simulate_split` keeps its signature for direct callers (tests); the cache is an optional keyword. `time_run` timing lines are not part of any record.
- Memory: measured below on the test fixtures and extrapolated to the real run; bounded (see "Memory bound").
- Proof: byte goldens captured before the change (record files, checkpoint files, experiment ids, run log without timing lines) for a 3-point runner run plain, with checkpoint, crash-at-call-8 then resume, a 2-point range-mr run, a 2-point long warm-up run (folds with 50 days of history) and a 2-point terminal-world run; the same script after the change must give byte-identical trees. New test `tests/test_research_case_data_reuse.py`: a spy counts `build_case_input_data` calls (one per window regardless of grid size, plus the store check), a 2-point run equals two 1-point runs record by record, the crash/resume path gives the reference records and builds only for the windows not checkpointed, cached rows unchanged.

## Verification per commit
Targeted: the five modules, test_case_input_builder.py, test_research_runner.py, test_research_manifest_build.py, test_smoke_backtest_cli.py, test_decision_alignment*.py, test_minute_source.py (B1) and the new tests; `ruff check`, `ruff format --check`, `mypy src`; `scripts/verify_decision_alignment.py all` = ALL_PASS at the end. No push; explicit paths staged only.
