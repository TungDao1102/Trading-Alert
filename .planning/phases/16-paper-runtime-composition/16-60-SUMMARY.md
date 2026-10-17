---
phase: 16-paper-runtime-composition
plan: 60
subsystem: research-warmup
status: complete
tags: [research, warm-up, simulator-semantics, protocol-v2.5.0, regeneration-inventory, B3-CR-01]
requires: [16-62]
requirements: [BKTS-03]
requirements-completed: []
provides:
  - "RESEARCH_WARMUP_SPAN = 50 days (whole-day ceiling of max(1000 x 1h, 300 x 4h) = 1200 h, STRUCTURAL) in src/backtest/semantics.py, covered by SIMULATOR_SEMANTICS_VERSION 2.2.0"
  - "src/research/run.py: warmup_start(manifest, window) = max(window start - span, development_start_utc); _simulate_split builds every case from it, keeps data_window and the minute source at the window; one neutral 'warmup ... starts cold' line per cold window (the Development window)"
  - "CaseInputData.to_case_input(data_window_start_utc=...): moves only data_window.start_utc of the case (validated UTC, inside the built range); default unchanged"
  - "protocol v2.5.0 (user's adopted text, label D073), DECISIONS D073 and D074 (owner's supersession wording verbatim), DOC_STATUS lines, holdout marker protocol_version v2.5.0 (entries empty)"
  - "evidence/16-60-regen-inventory.md and evidence/16-60-gate.txt; five decision records (span, row, marker, rerun directory, authorization form)"
affects: [16-61, 16-43, 16-44]
tech-stack:
  added: []
  patterns:
    - "regeneration through an inventory first (VERSION_PIN / DERIVED_DIGEST / STORED_RECORD), leak check over every committed backtest case, nothing of the bump committed before the records and guards"
    - "adopted protocol text read from the decision record by the witness test (label D073 as its only change)"
key-files:
  created:
    - tests/test_research_warmup.py
    - tests/test_research_protocol_v250.py
    - .planning/phases/16-paper-runtime-composition/evidence/16-60-regen-inventory.md
    - .planning/phases/16-paper-runtime-composition/evidence/16-60-gate.txt
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V250-span.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V250-row.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V250-marker.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-RERUN-DIR.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-RERUN-AUTH-FORM.md
  modified:
    - src/backtest/semantics.py
    - src/research/run.py
    - src/data/case_input.py
    - docs/research/RESEARCH_PROTOCOL.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/backtest/BACKTEST_SPEC.md
    - docs/research/holdout_consumed.json
    - scripts/decision_alignment/protocol.py
    - .github/workflows/research-gate.yml
    - tests/test_semantics_version_regression.py
    - tests/test_backtest_engine.py
    - tests/test_backtest_experiment.py
    - tests/test_backtest_lifecycle.py
    - tests/test_backtest_run_summary.py
    - tests/test_backtest_terminal_settlement.py
    - tests/test_backtest_simulator.py
    - tests/test_analytics_files.py
    - tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md
    - tests/fixtures/phase10/loaders/evidence_sample.json
    - tests/test_decision_alignment_protocol.py
    - tests/test_decision_alignment_bookkeeping.py
    - tests/test_kill_gate_docs.py
key-decisions:
  - "The data-window start is a keyword of CaseInputData.to_case_input (data_window_start_utc), not a rewrite of the case dict: the built range keeps its meaning (the files read and the dataset id), only the window the engine simulates moves; no existing case-input fixture changed."
  - "The cold-start line is printed once per run before the first window, one line per window whose history is empty (in a real run exactly the Development window), starting with the word 'warmup' and carrying no verdict word."
  - "The version-regression witness (design test 10) is parametrized over the earlier versions 2.0.0 and 2.1.0 with their recorded hashes, instead of being replaced, so the D070 witness is kept."
  - "The adopted v2.5.0 text sits in a new section 3 subsection 'Research window warm-up (v2.5.0)' with one pointer sentence; all explanation of the span is in the migration paragraph, so the user's block is the only normative sentence block added to section 3."
duration: "about 3 hours wall; three full-suite runs of about 18 minutes each dominated"
completed: 2026-10-17
commits: 4
plan_head_before: f51a5e18aa170cf40ab58b085f3643643802736b
plan_head_after: 76b1da05738dfd4b418f8fc0b493cccf9ed05639
actuals:
  tokens: 23800
  tasks: 4
  commits: 4
---

# Phase 16 Plan 60: Research warm-up fix Summary

Every research window (the Development window and each of the four Validation folds) is now built with 50 days of candle history loaded before its start, for the indicators only; simulator semantics move 2.1.0 to 2.2.0 and the protocol to v2.5.0 with D073 and D074, in one landing commit, with the owner's five decisions on record before it.

## What was built

- **Constant and runner (Task 1, tracer).** `RESEARCH_WARMUP_SPAN` is the whole-day ceiling of max(1000 x 1h, 300 x 4h) = 1200 h = 50 days (the owner accepted exactly this, Q0). `_simulate_split` builds the case from `warmup_start` (clamped at `development_start_utc`), passes `data_window_start_utc=window.start_utc` to `to_case_input`, and builds the `ParquetMinuteSource` over the window only. The engine already skipped signal evaluation before `data_start`; it is unchanged. `as_of_day_utc`, `_check_manifest_against_store` and `manifest_hash` are unchanged.
- **Tests, RED first.** `tests/test_research_warmup.py` (15 tests, 14 at the RED run): at the RED run 10 of them failed (the constant did not exist, then the runner did not use it); all pass after. Coverage: the constant is a derivation (Test 2); a fold case holds history from `window start - 50 days`, `data_window` and the minute source stay at the window, the record is the window, the cold count is 0 with the span and positive with the span forced to zero (Test 1); the first evaluated bar sees full 1000/300-bar windows with exactly the span, and 299 context bars one hour less (Test 3); the strategy's own minimum (`_EMA_SLOW_PERIOD` 4h bars, read from `src/core`) is enough and one hour less is WARMUP_INSUFFICIENT (Test 4); the Development window is clamped at the dataset start, starts cold, keeps its start, and the run prints one neutral cold-start line (Test 5); no day at or after the Holdout start is read (spy on the files of each build, `as_of_day_utc` unchanged) (Test 6); no evaluated bar closes before the window, the case `dataset_id` equals the builder's for exactly the days read and differs from the window-only one (Test 7); a terminal declaration inside a fold's warm-up builds and simulates with no settlement row and no error (Test 8, through the existing synthetic REEF-shaped world); plus the `data_window_start_utc` keyword validation.
- **Version 2.2.0 and the inventory (Task 2).** 106 failing tests under the bump, all in the three expected classes (9 VERSION_PIN including the 3 witness tests, 9 DERIVED_DIGEST, 88 STORED_RECORD, 0 WARMUP_BEHAVIOUR, 0 other). Leak check over 28 cases (26 committed fixtures + 2 captured): 28 `simulator_semantics_version` differences, 32 `trade_id` differences, 0 others, so only version string and trade_id differ. Captured hashes: 2.1.0 scripted_tracer `8b9b0d59...e320`, strategy_trigger_no_declaration `6130a3dd...1e87`; 2.2.0 `e97d7161...c817` and `95a35ac1...f5be`. Regeneration from each item's own build path: 6 literal pins, 9 digests in 2 files (computed, never typed), 1 literal in `evidence_sample.json` (from the code constant), the witness test rewritten. Inventory committed alone (`6570234`).
- **Owner's five decisions (Task 3).** Guards (a) to (d) held (span exactly 50 days; leak check clean; HEAD's DECISIONS ends at the Phase 18 row D072 with no D073/D074; marker at v2.4.0 with empty entries, sha256 before `2f6adee3...5e4`), so no side branch was needed. Records `16-DEC-V250-span`, `-row`, `-marker`, `16-DEC-RERUN-DIR`, `16-DEC-RERUN-AUTH-FORM` were written by a script that copies the reviewer subsections and the renumbering section byte for byte; committed alone (`4337ead`).
- **Landing (Task 4).** One commit (`c96fa0d`) holds the code, the version, the regenerated items, the protocol v2.5.0 (adopted text with label D073), D073, D074 (with the owner's supersession paragraph verbatim and the mapping note), the DOC_STATUS index and log lines, the BACKTEST_SPEC pointers, the alignment-script docstring, the workflow comment and the marker's `protocol_version`. Gate evidence committed separately (`76b1da0`).

## Gate numbers (evidence/16-60-gate.txt, commit c96fa0d)

Full suite `-m "not docker"` with `TEST_DATABASE_URL` set: exit 0, 10145 tests ran, 10139 passed, 6 skipped (symlinks unavailable, NTFS POSIX modes, file modes on Windows), 0 failed. `ruff check` exit 0; `ruff format --check` exit 0 (620 files); `mypy src` exit 0 (202 files); `uv lock --check` exit 0. The diff of `params/`, `docs/research/experiments/research-run-1`, the frozen manifest, the three grids and the three authorization files since `5f8269b` is empty.

## For the integrator (DECISIONS numbering)

The phase-18 branch was merged into develop first (merge 6610bd6) with its DECISIONS row D072 ("Phase 18 client configuration, user-data stream and exchange error taxonomy"), which keeps its number; no Phase 18 row is renumbered. Phase 16's rows are D073 (protocol v2.5.0 warm-up amendment) and D074 (regeneration inventory and disposition of the original records). Read from `git show HEAD:docs/DECISIONS.md` before writing this summary (read only; the phase-18 branch and its worktree were not touched):

- D072 | Phase 18 client configuration, user-data stream and exchange error taxonomy: user-ratified thresholds, environments and status classes
- D073 | Research protocol v2.5.0 frozen: warm-up history for research windows (finding B3-CR-01) and simulator semantics 2.2.0
- D074 | Regeneration inventory of the research warm-up fix (simulator semantics 2.1.0 to 2.2.0) and the disposition of the original 240 research records

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test 3 'one hour shorter' cannot be published as a store**
- **Found during:** Task 1 (test design)
- **Issue:** the store publishes whole UTC days, so a history that is one hour shorter than 50 days cannot exist in a store, and the runner's warm-up is whole days by construction.
- **Fix:** the hour-granular cases (Tests 3 and 4) trim the bars of the case the runner built on their way into the simulator (`_trim_history_hours`), so the engine's window composition is tested at hour granularity; the runner itself is tested with the whole-day span.
- **Files modified:** `tests/test_research_warmup.py`
- **Commit:** c96fa0d

**2. [Rule 1 - Bug] E501 line lengths found by ruff**
- **Found during:** Task 4
- **Issue:** two docstring/test lines over 100 characters (the alignment script docstring, the new protocol witness test).
- **Fix:** wrapped; no behaviour change.
- **Commit:** c96fa0d

No existing research runner, checkpoint, terminal-settlement or feasibility test needed a WARMUP_BEHAVIOUR update: their synthetic stores clamp every fold's history at the dataset start (the stores are shorter than 50 days), so their expectations did not move. The plan's `files_modified` lists `tests/test_research_runner.py` and `tests/test_research_checkpoint.py` for that case; they are unchanged.

The plan's Test 3 text says the history one hour shorter 'holds 299 bars'; that is what the trimmed-case test asserts.

## Pending, owner-only or later plans (not done here)

- Plan 16-61 (not part of this plan): the runner's sixth authorization key, the three new authorization files and the rerun itself on the real store into `docs/research/experiments/research-run-1-v2-2-0/`. No research runner was run on the real manifest or the real data store here; no ExperimentRecord was written outside pytest tmp_path; no Holdout read; no push.
- The Development window starts cold (data begins 2024-10-03). It is recorded in the protocol, D073 and the migration paragraph; the evidence of the rerun (plan 16-61) must carry the limitation explicitly.
- BKTS-03 is not marked complete: `requirements.ready-ids` reports it as blocked, so `requirements.mark-complete` was not called (the rerun under 2.2.0 is still to come).

## Known Stubs

None.

## Threat Flags

None. The only new data path is the warm-up read of earlier day files of the same published store; T-16-160 (Holdout leakage) is mitigated by the spy test over every build's files and by the unchanged `as_of_day_utc`/window-end bound.

## Self-Check: PASSED

- Files exist: `tests/test_research_warmup.py`, `tests/test_research_protocol_v250.py`, `evidence/16-60-regen-inventory.md`, `evidence/16-60-gate.txt`, the five decision records, this summary.
- Commits exist: `6570234` (inventory), `4337ead` (five records), `c96fa0d` (landing), `76b1da0` (gate evidence).
- Task verify commands pass: semantics `2.2.0` and span 50 days; the protocol, alignment and kill-gate test files; the marker equals `{'schema': 'holdout-consumed/2', 'protocol_version': 'v2.5.0', 'entries': []}`; D073 once, D074 once with the supersession paragraph and mapping note, the Phase 18 row D072 once; the landing commit holds the semantics file, the runner, the protocol and DECISIONS; the gate file has six `exit=0` lines and none non-zero.
