---
phase: 16-paper-runtime-composition
plan: 06
subsystem: research runner / authorization guard
status: complete
tags: [research-runner, authorization, manifest-hash, grid-hash, experiment-record, rev-04, rev-05, d-24, d-25]

requires:
  - phase: 14-backtest-engine-experiment-records
    provides: "experiment.assemble, ExperimentRecord, simulator.run, read_code_version, build_case_input_data / to_case_input, ParquetMinuteSource"
provides:
  - "src/research/manifest.py: DatasetManifest, ParameterGrid, GridPoint, Period, SplitWindow, manifest_hash, grid_hash, research_splits, load_manifest, load_grid, ManifestError"
  - "src/research/authorization.py: RunAuthorization (grid_hash, manifest_hash, authorized_at_utc, statement, authorized_by), RunNotAuthorized(reason), require_authorized, load_authorization"
  - "src/research/run.py: run_research, experiment_identity_inputs, ExperimentAlreadyRecorded, main (python -m src.research.run)"
  - "decisions/16-DEC-O-03a.md: the user's recorded answer to checkpoint O-03a (option a)"
affects: [16-12 holdout G5 reporting, 16-28 REV-16 identity amendment (edit experiment_identity_inputs only), 16-37 O-03b manifest contents]

requirements-completed: [BKTS-03]

actuals:
  tokens: 15700
  tasks: 3
  commits: 5
plan_head_before: 71b20a34815abfd8a5c4345527c28dca6e283742
plan_head_after: afc04beb5d5fb0f395f9aa07b0351d8d9249781d
commits: 5

tech-stack:
  added: []
  patterns:
    - "Hashes are taken over the parsed manifest/grid objects (canonical JSON), from files re-read at run time; an edit that changes meaning changes the hash"
    - "Strict JSON loaders: exact key sets, UTC-offset timestamps, Decimal strings, floats refused"
    - "Every refusal returns exit 2 with the cause on stderr; nothing is printed to stdout except neutral record identifiers"

key-files:
  created:
    - src/research/__init__.py
    - src/research/manifest.py
    - src/research/authorization.py
    - src/research/run.py
    - tests/test_research_runner.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-03a.md
  modified: []

key-decisions:
  - "O-03a: option a, a user-committed JSON authorization file, chosen by the user (reply 'chọn a'); recorded in decisions/16-DEC-O-03a.md. Only --authorization <path> is accepted; typed-hash flags do not exist and argparse rejects them (allow_abbrev off)"
  - "The runner stays infrastructure: it authorizes nothing, ranks nothing, prints no verdict, writes nothing to params/, the allowlist or docs/research/holdout_consumed.json (a test scans src/research for both names)"

patterns-established:
  - "Approving a grid never authorizes a run (L-10): the run needs its own authorization file whose two hashes equal the grid and manifest read at that moment"

coverage:
  - id: D1
    description: "An authorized synthetic run goes case input, simulate, read_code_version, assemble and writes one experiment record per split; stdout carries no verdict wording; params/ and the holdout marker are unchanged"
    requirement: BKTS-03
    verification:
      - kind: unit
        ref: "tests/test_research_runner.py#test_authorized_run_writes_one_record_per_split_and_no_verdict"
        status: pass
      - kind: unit
        ref: "tests/test_research_runner.py#test_main_runs_an_exactly_authorized_manifest_and_grid"
        status: pass
    human_judgment: false
  - id: D2
    description: "Missing, malformed, grid-mismatched, manifest-mismatched and post-authorization-edited inputs are refused before any simulate or code-version call"
    requirement: BKTS-03
    verification:
      - kind: unit
        ref: "tests/test_research_runner.py#test_malformed_authorization_file_is_refused"
        status: pass
      - kind: unit
        ref: "tests/test_research_runner.py#test_main_refuses_a_hash_mismatch_before_simulate"
        status: pass
      - kind: unit
        ref: "tests/test_research_runner.py#test_main_refuses_a_manifest_edited_after_authorization"
        status: pass
      - kind: unit
        ref: "tests/test_research_runner.py#test_main_refuses_a_grid_edited_after_authorization"
        status: pass
    human_judgment: false
  - id: D3
    description: "A rerun of an already recorded experiment raises ExperimentAlreadyRecorded and overwrites nothing; only the user-chosen form is accepted on the command line"
    requirement: BKTS-03
    verification:
      - kind: unit
        ref: "tests/test_research_runner.py#test_rerun_of_a_recorded_experiment_is_refused_and_never_overwritten"
        status: pass
      - kind: unit
        ref: "tests/test_research_runner.py#test_only_the_authorization_file_form_is_accepted"
        status: pass
    human_judgment: false

duration: not measured (two executor sessions with a user checkpoint between them)
completed: 2026-10-09
---

# Phase 16 Plan 06: Research runner with the authorization-file guard Summary

**`python -m src.research.run` runs an experiment only when a user-committed JSON file binds the SHA-256 of the parameter grid and of the dataset manifest it re-reads from disk at that moment; every other input is refused with exit 2 before any simulation, and nothing is judged, ranked or written outside the output directory.**

## Accomplishments

- Tracer (Task 1, earlier session): manifest and grid with canonical hashes, `require_authorized`, `run_research` (development window plus the four validation folds, never the holdout), `read_code_version` plus `experiment.assemble`, one `<experiment_id>.json` per window.
- Checkpoint O-03a answered by the user: option a. The decision file records `option: a`, `decided by: user`, `date: 2026-10-09` and the reply verbatim.
- Option a implemented: `--authorization <path>` with exactly `grid_sha256`, `manifest_sha256`, `authorized_at_utc`, `statement`, `authorized_by`. Loaders for the authorization, manifest and grid files; `ExperimentAlreadyRecorded`; `main()` no longer refuses unconditionally.
- Refusals, each named on stderr and each before any simulation: `missing`, `malformed`, `grid_hash_mismatch`, `manifest_hash_mismatch`, invalid manifest or grid file, registry hash mismatch, constraint file mismatch, dataset id mismatch, `experiment_already_recorded`.

## Task Commits

1. **Task 1: Tracer** - `6b75206` (test, RED), `b88a570` (feat, GREEN)
2. **Task 2: Checkpoint O-03a (user decision)** - `5666316` (docs)
3. **Task 3: Authorization file form and REV-05 refusals** - `e199de3` (test, RED), `afc04be` (feat, GREEN)

**Plan metadata:** the closing docs commit that holds this file, STATE.md and ROADMAP.md.

## Files Created/Modified

- `src/research/manifest.py` - frozen `DatasetManifest` / `ParameterGrid`, canonical hashes, split windows, strict JSON loaders
- `src/research/authorization.py` - `RunAuthorization`, `RunNotAuthorized`, `require_authorized`, `load_authorization`
- `src/research/run.py` - `run_research`, `experiment_identity_inputs` (the single place REV-16 will edit), `ExperimentAlreadyRecorded`, `main`
- `tests/test_research_runner.py` - 39 tests on a synthetic published store built in `tmp_path`
- `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-03a.md` - the user's decision

## Decisions Made

- Form of the authorization artifact: user's choice, option a. The plan's recommendation was never applied by the executor.
- No value that belongs to the user was chosen: the manifest contents (window, split dates, universe, equity, risk rate, constraint file), the grid points and the authorization statement are all inputs from files; O-03b (16-37) decides them.

## Deviations from Plan

None of Rules 1 to 4 fired. The following are interpretations the plan left open; the Task 1 ones were recorded by the earlier session and are carried forward unchanged. The user should know they exist.

1. **One record per grid point per window.** `run_research` writes one `<experiment_id>.json` for every (grid point, development or validation fold) pair, so a one-point grid yields five records.
2. **`dataset_id` scope.** The manifest `dataset_id` is the `dataset_identity` of the published files over the research window only (development start to validation end); the holdout files are never read. Per-window `data_snapshot_id` is the case `dataset_id` of that window, through `experiment_identity_inputs` (REV-16 open, one place to edit).
3. **`excluded_periods` are refused.** A non-empty list raises `ManifestError` because the runner has no way to simulate around an excluded period; it refuses rather than simulate a window the manifest excludes.
4. **`run_type` is `CANDIDATE`** for every record.
5. **Constraint source** is a JSON path (a list, or an object with a `constraint_history` list) plus its `sha256`; the bytes are checked against the manifest hash and must hold a row for every manifest symbol. Account inputs `equity` and `risk_rate` come from the manifest, never defaulted.
6. **No wall clock.** Nothing in the runner reads the current time; `authorized_at_utc` is carried as the user wrote it and is not compared with anything.
7. **Rerun refusal timing (Task 3).** The plan truth says a rerun is "refused before any simulation starts", but `experiment_id` only exists once `assemble` has run on a simulated window, and recomputing its identity payload outside `assemble` would duplicate it. So `ExperimentAlreadyRecorded` is checked immediately after each window is assembled (a full rerun stops after its first window) and again over all records before the first write; no file is created or overwritten on that path (tested, including a directory holding only the last record). All other refusals, including the hash checks, happen before any simulation. Closing the gap fully would need an `experiment_id` precompute helper in `src/backtest/experiment.py`; not done because it is outside this plan's files.
8. **`authorized_by` added to `RunAuthorization`** (required, non-empty) because the chosen file form carries it; the Task 1 dataclass had four fields. The Task 1 test helper was updated accordingly.
9. **Strict file parsing.** Authorization, manifest and grid files accept exactly the documented key sets, JSON fractions or exponents are refused (Decimal strings only), and timestamps need a UTC offset. Hashes are taken over the parsed objects, so whitespace or key-order edits do not change a hash but any meaning-changing edit does.
10. **Record print moved** from `_run_split` to after the write ("recorded experiment_id=...") so the line is true when printed.

## Issues Encountered

- Shell heredocs containing quotes failed in the tool wrapper; edits were applied with the editor tools instead. No effect on the code.

## Known Stubs

None.

## Threat Flags

None. The new CLI reads only files the caller names and writes only into `--output-dir`; this is the T-16-14, T-16-15 and T-16-16 surface already in the plan's threat model.

## Verification

- `tests/test_research_runner.py` plus `tests/test_paper_start_gate.py`: 115 passed (39 in the runner file).
- `ruff check`, `ruff format --check` (446 files), `mypy src` (156 files): clean.
- `grep PAPER_START_ALLOWLIST src/research`: empty. Only `--authorization` is accepted; `--authorize-*` flags exit 2 in argparse.
- The whole pytest suite was not run in one process (tool time limit); only the files above were run.

## Self-Check: PASSED

- Files: `src/research/{__init__,manifest,authorization,run}.py`, `tests/test_research_runner.py`, `decisions/16-DEC-O-03a.md` exist.
- Commits `6b75206`, `b88a570`, `5666316`, `e199de3`, `afc04be` exist on `develop`; `git rev-list --count 71b20a3..HEAD` was 5 at write time.
