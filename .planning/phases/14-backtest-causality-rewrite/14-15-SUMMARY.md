---
phase: 14-backtest-causality-rewrite
plan: 15
subsystem: backtest
tags: [backtest, experiment-record, identity, code-version, evidence-loader, schema-bump, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-09 typed engine run_summary; 14-10 funding_convention in the cost slice; 14-11 normalizer boundary validation; 14-12 v2 simulator.run and regenerated phase 6 cases"
provides:
  - "src/backtest/experiment.py: typed, validated ExperimentRecord (17 typed fields), CodeVersion, RecordedGap, assemble(run_summary=, code_version=CodeVersion, split_*), reproduce/verify_experiment bound to the v2 run, typed trade fan-out with validate_trade_record"
  - "src/adapters/code_version.py: read_code_version(repo_root) -> CodeVersion (list argv, no shell, timeout)"
  - "src/adapters/analytics_files.py: analytics-evidence/2 loader with a closed typed experiment key set and v2 trade fields; v1 files refused"
  - "tests/backtest_case_helpers.py: strategy_run_summary, assemble_kwargs, make_experiment_record (the one shared record factory)"
  - "tests/fixtures/phase10/loaders/evidence_sample.json regenerated in the v2 shape"
affects: [14-16]

requirements-completed: [BKTS-04, BKTS-02]

actuals:
  tokens: 34300
  tasks: 3
  commits: 6
plan_head_before: e1d74d31d42447f97bdf15a0751ee88b893a76b4
plan_head_after: ab8a6068b152b5c97a256b0761d723522c48e496

tech-stack:
  added: []
  patterns:
    - "Typed record fields are pair tuples (sorted, unique) and a frozen RecordedGap, so the record stays hashable and has exactly one representation; JSON uses objects and lists and the loader converts"
    - "cost_values are rebuilt through build_cost_model inside __post_init__ and must hash to cost_model_hash, so a forged cost value cannot ride a genuine hash"
    - "The git read lives in an adapter that returns the pure CodeVersion defined in src/backtest; AST test pins no-shell and a timeout"

key-files:
  created:
    - src/adapters/code_version.py
    - tests/test_code_version.py
  modified:
    - src/backtest/experiment.py
    - src/backtest/__init__.py
    - src/adapters/analytics_files.py
    - tests/backtest_case_helpers.py
    - tests/test_backtest_experiment.py
    - tests/test_backtest_binding.py
    - tests/test_backtest_report.py
    - tests/test_analytics_report.py
    - tests/test_analytics_files.py
    - tests/test_analytics_render.py
    - tests/test_analytics_sidecar.py
    - tests/test_cost_per_unit.py
    - tests/fixtures/phase10/loaders/evidence_sample.json
    - tests/fixtures/phase10/report_composite/input.json
    - tests/fixtures/phase10/report_composite/expected.json
    - tests/fixtures/phase10/render_golden/expected.md
    - tests/fixtures/phase10/render_golden/expected.json
    - tests/fixtures/phase10/render_golden/expected_sections_0_2.md

key-decisions:
  - "ExperimentRecord keeps its 13 old fields and appends 17 required typed fields with no defaults; result_summary_json survives only as the carrier of the optional stored trades_digest"
  - "cost_values must carry the seven cost keys plus funding_convention and must hash to cost_model_hash (rebuilt with build_cost_model); parameter_values are the full registry params as sorted (key, canonical text) pairs"
  - "allowed_gaps records the gaps the run used (run_summary allowed_gaps_used), as sorted RecordedGap values; the configured gap list stays in the case input"
  - "assemble goes beyond the plan text in two binding checks: run_summary data_window must equal the record time range, and a set run_summary dataset_id must equal data_snapshot_id; reproduce repeats both, and compares every typed field of the re-run summary with the record"
  - "dirty means any output of git status --porcelain, untracked files included, so a record never claims a clean commit it did not run on"
  - "A legacy 7-key set can no longer assemble (the cost model lacks funding_convention); the binding gate itself and the byte-locked legacy cost hashes are unchanged"
  - "Holdout-once enforcement is not implemented and holdout_consumed.json is neither read nor written (Phase 26, F-960)"

patterns-established:
  - "One shared test factory for typed records; no test spells the typed fields by hand"

duration: about 2.5 h (estimate; start time was not captured)
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 15: Typed Experiment Record, Verifiable Code Version and analytics-evidence/2 Summary

**`ExperimentRecord` now carries the protocol-mandated typed fields (NO_TRADE counts, tie-break, timeframes, full parameter and cost values, semantics version, git commit plus dirty flag, counts, windows, used gaps, split role and boundaries) and cannot be constructed invalid; `experiment_id` binds the semantics version and the split; reproduce and verify bind the record to its v2 re-run; and the evidence loader is `analytics-evidence/2` with old files refused.**

## Accomplishments

- **Typed record (Task 1, tracer).** 17 required fields after `notes`; `__post_init__` raises `IncompleteExperimentRecord` for a wrong semantics version or tie-break, a split role outside DEVELOPMENT/VALIDATION/HOLDOUT, split boundaries that do not contain the time range, a negative or bool count, unsorted or duplicate pairs, a non-40-hex commit, a `code_version` that is not the commit (plus `-dirty`), cost values that lack `funding_convention` or do not hash to `cost_model_hash`, and a naive datetime. `assemble` takes the engine `run_summary` and refuses SCRIPTED runs, foreign semantics or tie-break, a window or dataset id that is not the record's, and a cost model without the funding convention. `experiment_id` adds `simulator_semantics_version`, `split_role` and both boundaries (D-02, D-22). `to_dict()` gives the JSON shape (no key named `parameters` or `parameters_json`).
- **Code version and v2 binding (Task 2).** `read_code_version` runs `git rev-parse HEAD` and `git status --porcelain` with list argv, `shell=False`, a 30 s timeout; missing git, timeout, non-zero exit and a malformed commit are `CodeVersionError` and stderr is never echoed. `_trade_from_dict` rebuilds `signal_close_utc`, `planned_quantity`, `tp1_*`, `resolved_at_utc`, checks counters, flags and labels strictly, and validates every trade (D-23); a v1-shaped trade raises. `reproduce` checks the data window against the record range, then requires the re-run summary to agree with every typed field. Every other `assemble`/`ExperimentRecord` caller moved onto the shared factory.
- **Evidence schema v2 (Task 3).** `EVIDENCE_SCHEMA = "analytics-evidence/2"`; the experiment object is a closed key set (missing or unexpected key fails closed naming the key); mappings become the pair tuples; v2 trade fields are parsed before the shared parser; every failure is an `EvidenceFileError` that echoes no value. `evidence_sample.json` was regenerated.

## test_analytics_cli.py: the 31 known failures

All 57 tests in `tests/test_analytics_cli.py` pass, so all 31 deferred failures are green. They are green because the loader and the sample were upgraded to v2: the sample trades are v2 records (exit_kind TP2, entry_kind REJECT, `signal_close_utc`, `planned_quantity`, `resolved_at_utc`) built through `_trade_from_dict`, which now calls `validate_trade_record`, and `normalize_backtest` still runs the validator at its boundary. `validate_trade_record` and the normalizer were not touched or bypassed. None remain.

## Task Commits

1. **Task 1 (tracer)**: `784a5de` (test, RED: every experiment test fails at `CodeVersion` import), `65163b9` (feat, GREEN)
2. **Task 2**: `55c0c41` (test, RED: `test_code_version.py` fails to import the adapter), `d02ad86` (feat, GREEN)
3. **Task 3**: `6c9913a` (test, RED: 38 loader tests fail on the v1 sample and loader), `ab8a606` (feat, GREEN)

Plan metadata commit (SUMMARY, STATE, ROADMAP, REQUIREMENTS, deferred-items) follows this file.

## TDD Gate Compliance

- Task 1 and Task 3 each have a genuine RED commit that failed before the matching GREEN commit. `gsd_run check tdd-red-evidence` was not run.
- Task 2 is only partly RED. `test_code_version.py` failed (module missing) in `55c0c41`. The tests for the trade fan-out validation and the v2 run binding (added in the same commit) passed on first run, because that source (`_trade_from_dict` typing and validation, `_check_run_binds_record`, the `data_window` check) landed in the Task 1 GREEN commit `65163b9`. The Task 1 tests already include `test_cr03b` (typed v2 trade fields), and the Task 1 verify runs the whole experiment test file, so that source had to be present at that commit. I tried to strip those pieces out of the Task 1 commit to stage a cleaner RED for Task 2; the auto-mode classifier denied the edit as a removal of security checks, I did not retry or work around it, and the full file was committed in Task 1. The Task 2 tests are not vacuous: they feed v1-shaped trades, an entry before the signal close, a shifted or missing data window, a different engine semantics version (monkeypatched on the engine module) and a scripted case, all of which the pre-14-15 code accepted.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Phase 10 report_composite fixture identity and its pinned goldens**
- **Found during:** Task 2
- **Issue:** `tests/test_analytics_report.py::build_experiment` builds `ExperimentRecord(**raw)` from `tests/fixtures/phase10/report_composite/input.json`, whose experiment had `code_version "code-abc123"` and an arbitrary `cost_model_hash`. D-22 forbids both (a code version must be a commit; the cost values must hash to the recorded hash), and the plan lists neither this fixture nor its goldens.
- **Fix:** The fixture experiment now carries a 40-hex commit and the baseline-v5 cost hash; `build_experiment` builds the typed record through the factory. The digest pins moved (see the inventory). The diff of the regenerated `expected.md` is exactly two lines (the digest row and the experiment identity row).
- **Files modified:** the five phase10 fixture files, tests/test_analytics_report.py, tests/test_analytics_render.py (the renderer shows any 64- or 40-hex string as a 12-character prefix, so the expected `code_version` cell is `[:12]`), tests/test_analytics_sidecar.py (stem pin)
- **Commit:** d02ad86

**2. [Rule 3 - Blocking] Callers outside the plan's file list**
- `tests/test_cost_per_unit.py` calls `assemble` and was migrated (the legacy 7-key set now asserts the gate still binds and the legacy hash is unchanged, while `assemble` refuses it). `tests/test_case_input_builder.py` is in the plan's list but never constructs a record or calls `assemble`, so it needed no change.
- `tests/test_backtest_binding.py` rebinds the phase 7.1 cases onto baseline-v5 through `_v5_case` (the cost divergence of each case is respelled: fee 0.0009, funding PRO_RATA, fee spelling 0.00050), because a legacy 7-key set cannot assemble any more. The phase 7.1 fixture files are untouched and keep feeding the tests that never call `assemble`.
- **Commit:** d02ad86

**3. [Scope] Two binding checks beyond the plan text** (`data_window` equals the time range, `dataset_id` equals `data_snapshot_id`), plus the typed-field comparison in `reproduce`. They are what "reproduce binds the record to its inputs" needs to mean in practice. One existing test changed with it: the drifted-minute case in `test_verify_experiment_compares_the_v2_digest...` now trips on `end_of_data_count` (the position runs to the data end) before the digest comparison, which is a stronger detection, not a weaker one.

**4. [Ordering]** The Task 2 source landed in the Task 1 commit, as described under TDD Gate Compliance.

**Total deviations:** 4 (2 blocking, 1 scope, 1 ordering). **Impact:** one Phase 10 pin moved with a documented inventory; no params, hash of any registry set, cost hash, validator or normalizer changed.

## Issues Encountered

- Full `pytest -m "not docker"` was not run (the known Windows access violation; coordinator instruction). In its place: 132 test files that import `src.core`, `src.backtest`, `src.risk`, `src.domain`, `src.paper`, `src.analytics`, `src.data` or `src.adapters` (deploy, docker, backup, PG and universe-freeze files excluded) ran together and passed; 16 further files (decision alignment, domain no-float, research-gate negative, smoke CLI, fixture generator, execution partials and secret posture, wave 0, test infra, analytics typing) also passed. No stray pytest or python processes remain.
- A shell heredoc containing an apostrophe fails in this tool (seen before in 14-08 and 14-12); the large edits went through the Write tool and `.py` script files.
- The branch is `develop`; the five-name protected fallback would match it, but the repository default branch is `master`, prior plan commits are on `develop`, and the orchestrator ordered normal commits on this tree.

## Verification (real output)

- `pytest tests/test_backtest_experiment.py` (84 tests), `tests/test_code_version.py` (14), `tests/test_analytics_files.py tests/test_analytics_store.py tests/test_analytics_cli.py` (cli: 57 passed): all green.
- The Task 2 verify set plus provenance, render and sidecar suites (389 tests): all green.
- Acceptance: `simulator_semantics_version`, `split_role`, `parameter_values` in experiment.py; the field-name check (`parameters`/`parameters_json` absent, `no_trade_counts` present); the AST no-shell check on `code_version.py` (also a test); `"signal_close_utc"` in `_DATETIME_TRADE_FIELDS`; `tests/test_backtest_purity.py` passes; `"analytics-evidence/2"` in analytics_files.py; the tracked-file name trap (`experiment*`/`backtest*` json/yaml) prints OK with `git ls-files` captured first; no `"parameters"` or `parameters_json` key in the sample.
- `ruff check`: all checks passed. `ruff format --check`: 409 files already formatted. `mypy src`: no issues in 147 source files.
- Tracer gate (interactive, end-of-phase, automated verify only): the Task 1 verify command was re-run after GREEN and passed; expansion continued.

## Regeneration inventory

No file under `params/` changed. Registry `parameter_set_hash` values, `cost_model_hash` of every set, `strategy_version` and the validator are unchanged. No committed `experiment_id` pin existed outside the evidence sample (the experiment tests assert stability and inequality, not literals).

| Item | Old | New | Reason |
| --- | --- | --- | --- |
| `EVIDENCE_SCHEMA` | `analytics-evidence/1` | `analytics-evidence/2` | D-03, T-14-29: void pre-Phase-14 evidence is refused by schema |
| `experiment_id` hash inputs | six identity fields, run_type, strategy_id, range, universe hash | plus `simulator_semantics_version`, `split_role`, `split_start_utc`, `split_end_utc`; `code_version` is now commit or commit-dirty | D-02, D-22, F-904 identity part |
| `tests/fixtures/phase10/loaders/evidence_sample.json` | v1: experiment id 71d98aa164245e35..., `baseline-v1`, parameter_set_hash e1579900..., cost_model_hash 41c8dcc0..., code_version `fixture-code-1`, trade exit_kind TP1, reject entry_kind TOUCH_NO_FILL with reason RISK_REJECT_MIN_NOTIONAL | v2: experiment id e3bb209d29f00df4..., `baseline-v5`, parameter_set_hash 41ed39d4... (baseline-v5), cost_model_hash 6d6c4e23... (baseline-v5 slice), 40-hex commit, trade exit_kind TP2 with `signal_close_utc`, `planned_quantity`, `resolved_at_utc`, reject entry_kind REJECT reason NOTIONAL_REJECT; paper rows re-pointed at the new identity | v2 loader, validated trades; the old reason code was not a RejectionReason value |
| `report_composite/input.json` experiment | `code_version` code-abc123, `cost_model_hash` c1c1...c1 | `code_version` 0123456789abcdef0123456789abcdef01234567, `cost_model_hash` 6d6c4e237ed0b56996ed344f4449b09a59c253a8d148af60e3aba1c8436f1caa | the typed record binds both (D-22) |
| `report_composite/expected.json` `report_digest` | 2838cb3aa82744bee5ccf588c3e1ef5a0b9e20bb6e1814f4ca88dcfb4db33627 | ebd9e1014da67eeba942199a67699b3ac79f5fb8c64ef86b7218f003733a19c7 | provenance carries code_version and cost_model_hash |
| `render_golden/expected.md` | digest row 2838cb3a...; identity row `code_version=code-abc123; cost_model_hash=c1c1c1c1c1c1` | digest row ebd9e101...; `code_version=0123456789ab; cost_model_hash=6d6c4e237ed0` | same; exactly two lines differ |
| `render_golden/expected.json` | markdown_sha256 848f5a2c92bc...; report_digest 2838cb3a... | regenerated from the report and the markdown (one line) | same |
| `render_golden/expected_sections_0_2.md` | digest 2838cb3a... | digest ebd9e101... | same |
| `test_analytics_sidecar` stem pin | `journal-depth-20270401T000000Z-2838cb3aa827` | `journal-depth-20270401T000000Z-ebd9e1014da6` | same digest |
| `test_analytics_render` section 10 expectation | `code_version={experiment.code_version}` | `code_version={experiment.code_version[:12]}` | the renderer prefixes any hex string to 12 characters |
| Method for the sample | | a scratch script (not committed) built the experiment with the real `assemble` over baseline-v5 and the run summary of the real engine run of the phase 6 simple_trend case (data_window set to 2026-01-01..2026-03-01, and the sample's one reject added to no_trade_counts), built the two trades as validated `TradeRecord`s, and wrote the JSON with sorted keys, indent 2 | the run summary is real engine output with the window and one count adjusted to the sample, not a new simulation |
| Phase 7.1 fixture files, phase 6 cases | | untouched | the binding tests rebind in code (`_v5_case`) |

## Known Stubs

None.

## Threat Flags

None. T-14-29 (schema bump, typed record validation, validated trades, old schema refused) and T-14-31 (`parameter_values` naming, the tracked-file name check, a JSON key walk in the loader tests) are mitigated as planned. T-14-30 is mitigated by the list-argv, no-shell, timeout `subprocess.run` calls in `src/adapters/code_version.py` and an AST test. `src/adapters/code_version.py` is the only new process-spawning surface, and it is the planned one.

## Next Phase Readiness

Plan 14-16 can build on `assemble(run_summary=...)`, `make_experiment_record` and the v2 evidence shape. Open for it: `modeled_costs_per_unit` is still `None` on v2 filled records (see `deferred-items.md`). The typed record is not wired to any CLI that produces experiment records yet (no caller reads git and assembles outside the tests); a later plan that records a real run should call `read_code_version` and `assemble` with the engine `run_summary`.

## Self-Check: PASSED

Created and modified files exist (`src/adapters/code_version.py`, `tests/test_code_version.py`, the regenerated sample and the phase 10 goldens); commits 784a5de, 65163b9, 55c0c41, d02ad86, 6c9913a and ab8a606 are in `git log`; the acceptance commands re-ran green (name trap OK, no gate keys, `analytics-evidence/2`, ruff, mypy).
