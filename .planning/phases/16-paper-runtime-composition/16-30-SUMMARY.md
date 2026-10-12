---
phase: 16-paper-runtime-composition
plan: 30
subsystem: soak evidence export / durable-location decisions (D061 item A, L-01, REV-02, REV-18)
tags: [evidence-bundle, exporter, redaction-scan, evidence-gap, epoch, decisions, paper-01]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-25 (soak-evidence-bundle/1 layout, load_evidence_bundle, evaluator); plan 16-16 (PgRuntimeState); plan 16-36 (export_shadow_evidence); plan 16-51 (PAPER_REPLAY_INPUTS, PAPER_HISTORY_BARS, parity from the bundle); plan 16-15 (freeze_evidence_report, EvidenceGap)"
provides:
  - "scripts/export_soak_evidence.py: main(argv, *, state=None, environ=None) writing one soak-evidence-bundle/1 directory per epoch; exit 0 written, 2 unusable input, 3 secret-looking content"
  - "tests/test_soak_evidence_export.py: 18 tests (tracer, sources, gap file, redaction scan, per-epoch bundles, parity from the bundle, PostgreSQL port)"
  - "Decision records (user, not edited here): 16-DEC-O-01 (option a), 16-DEC-Q-F (commit-pinned-state), 16-DEC-Q-Q (off-hour-minute, cron 34 * * * *)"
affects: [16-47 (publishes the bundle to the O-01 location, sets cron 34 * * * * on master, reads the pinned state per Q-F), 16-43 (re-checks master before the pin), 16-44 (evaluates the bundle)]

requirements-completed: [PAPER-01]

status: complete
actuals:
  tokens: 12600
  tasks: 4
  commits: 2
plan_head_before: 614e5ad2d0f2303c03be89fb6cfbf281c36396cb
plan_head_after: fc2888c2f823be4a4fc064cf710642ed3fa17537
commits: 2

tech-stack:
  added: []
  patterns:
    - "Staged write: every file goes to a sibling hidden directory, the manifest is written last, then os.replace moves the directory into place; a failure removes the staging directory"
    - "Redaction scan before staging: src.ops.redaction.Redactor over every file; a finding names the file, never the value"
    - "Proof class follows the source only: the manifest source is the --source choice; a records file cannot back pg and a state port cannot back fixture"

key-files:
  created:
    - scripts/export_soak_evidence.py
    - tests/test_soak_evidence_export.py
  modified: []

key-decisions:
  - "A bundle is one epoch: runtime records are those of --epoch (port asked with no event-type filter); the freeze log and run list are copied whole, byte for byte, whatever the epoch (REV-18 auxiliary evidence)"
  - "Repeated --pinned: the file whose epoch_id equals --epoch is copied verbatim, so an earlier epoch is exported with its own archived pin after a new pin exists; zero or two matches refuse"
  - "EVIDENCE_GAP records use freeze_evidence_report exactly as the evaluator calls it (cron from the workflow file, grace from the ratified config, detected_at = window end), so the export is deterministic"
  - "An existing --out is never overwritten and an epoch with no runtime record is refused (a wrong --epoch must not yield an empty bundle)"
  - "SHADOW analytics rows come from an optional --analytics-inputs file (rows, backtest part, research universe); building ShadowRow from the journal is not in this plan"

patterns-established:
  - "Test seam for the pg source: main(..., state=port, environ=mapping); production builds PgRuntimeState from DATABASE_URL_SYNC / DATABASE_URL (allowed names only) through make_sync_engine"

coverage:
  - deliverable: "one export command builds a bundle load_evidence_bundle accepts, sha256 per file, manifest last"
    verification:
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_tracer_a_fixture_session_exports_to_a_bundle_the_evaluator_accepts", status: pass}
    human_judgment: false
  - deliverable: "EVIDENCE_GAP records in their own file, registry_diff.jsonl and every input byte-identical"
    verification:
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_evidence_gap_records_go_to_their_own_file_and_no_input_is_touched", status: pass}
    human_judgment: false
  - deliverable: "proof class follows the source only (fixture always FAKE, pg is the soak source)"
    verification:
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_no_argument_flag_or_variable_turns_a_fixture_source_into_a_pg_manifest", status: pass}
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_the_pg_source_reads_every_record_through_the_port_and_writes_source_pg", status: pass}
    human_judgment: false
  - deliverable: "redaction scan aborts, removes the partial bundle, prints no value"
    verification:
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_a_secret_looking_value_aborts_removes_the_partial_bundle_and_prints_no_value", status: pass}
    human_judgment: false
  - deliverable: "per-epoch bundles, earlier epoch retained and reproducible byte for byte"
    verification:
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_two_epochs_give_two_complete_bundles_and_no_export_drops_or_edits_evidence", status: pass}
    human_judgment: false
  - deliverable: "parity PASS / FAIL (bar close named) from the exported bundle through scripts/evaluate_trial_soak.py"
    verification:
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_parity_is_rebuilt_from_the_exported_bundle_and_one_altered_input_fails_it", status: pass}
    human_judgment: false
  - deliverable: "records of every RuntimeEventType read from PostgreSQL through PgRuntimeState"
    verification:
      - {kind: pytest, ref: "tests/test_soak_evidence_export.py::test_the_pg_source_exports_every_record_stored_on_postgresql", status: pass}
    human_judgment: false
  - deliverable: "O-01, Q-F, Q-Q decision records present and recorded by the user"
    verification:
      - {kind: shell, ref: "grep ^option: on the three records; Q-Q cron check", status: pass}
    human_judgment: true
    rationale: "The decisions are the user's; this plan only ran each task's automated verify command against the existing records and did not edit them"

duration: ~1 h
completed: 2026-10-12
---

# Phase 16 Plan 30: Soak evidence exporter Summary

**`scripts/export_soak_evidence.py` writes one `soak-evidence-bundle/1` directory per epoch (pinned state, freeze log and run list copied whole, that epoch's runtime records, EVIDENCE_GAP records in their own file, optional SHADOW analytics) with a sha256 per file, after a redaction scan, and `load_evidence_bundle` and the 16-25 evaluator accept it, including parity rebuilt from the exported replay inputs.**

## Performance

- **Tasks:** 4 of 4 (Task 1 tracer with `tdd="true"`: RED commit then GREEN commit; Tasks 2 to 4 are the checkpoint tasks the user had already answered, see below)
- **Files:** 2 created, 0 modified
- **Commits:** 2 measured (`plan_head_before..plan_head_after`); the SUMMARY commit is the third

## Accomplishments

- **Exporter (Task 1).** `main(["--source", "fixture"|"pg", "--epoch", ..., "--pinned", ..., "--diff-log", ..., "--github-runs", ..., "--config", ..., "--workflow", ..., "--window-start", ..., "--window-end", ..., "--out", ...])`. Runtime records go through `runtime_record_line` (all `RuntimeEventType`, `PAPER_REPLAY_INPUTS` and `PAPER_HISTORY_BARS` included, `state.records(epoch)` with no filter); gaps come from `freeze_evidence_report`; the analytics file comes from `export_shadow_evidence` when `--analytics-inputs` is given (`test_only` rows keep their flag; the normalizer counted 7 excluded rows in the test).
- **Source and proof class.** The manifest `source` equals the `--source` choice and nothing else sets it. `--source pg` with `--records`, and `--source fixture` with a state port, are refused (exit 2) with nothing written; ambient variables named like a source do not matter.
- **Epochs (REV-18).** A two-epoch fixture session gives two complete bundles; each holds only its own runtime records, the freeze log and run list byte-identical to the inputs, the archived pin of its own epoch; every input file is byte-identical after both exports, and re-exporting the earlier epoch after the new pin reproduces its bundle bytes.
- **Scan and write.** The scrubber of `src/ops/redaction` runs over every file before anything is staged; a URL password, an AWS key id or an environment secret value aborts with exit 3, names the file, prints no value and leaves no partial directory. Files are staged in a sibling directory, the manifest is written last, `os.replace` moves the directory into place, and an existing `--out` is never overwritten.
- **Parity from the bundle.** A session produced by the real `BarPipeline` (`World` of the 16-51 tests) exported with `--source pg` from an in-memory port prints `PASS  parity (tolerance zero)` through `scripts/evaluate_trial_soak.py`; with one recorded input altered (digest recomputed) it prints `FAIL  parity (tolerance zero)` with the bar close named.
- **Checkpoints (Tasks 2 to 4).** The user had already answered O-01, Q-F and Q-Q; the records were not rewritten or edited. Each task's automated verify command was run against the existing records: `^option: (a|b|c|d|e)$` matches `option: a` (O-01); `^option: (commit-pinned-state|read-from-durable-store)$` matches `option: commit-pinned-state` (Q-F); the Q-Q Python check prints `True` for `option: off-hour-minute` with `cron: 34 * * * *`.

## Task Commits

| Task | Commit | What |
| --- | --- | --- |
| 1 RED | 10bd62f | test(16-30): RED for the soak evidence exporter (bundle, source, gaps, scan, epochs, parity) |
| 1 GREEN | fc2888c | feat(16-30): export one epoch of the soak evidence as a verifiable bundle |
| 2 to 4 | (none) | Decision records were committed on `develop` before this plan ran (614e5ad, 594f96b); verify commands run only |

## Decisions recorded by the user (read, not edited)

- **O-01:** option a (private encrypted S3 backup bucket, separate evidence prefix, written from the EC2 host); `versioning: enabled`, `object_lock_mode: none`, `retention: none`, `reader_access: project owner only`, `through_crypt_remote: no`, `write_timing: exporter-schedule, hourly`. The record states that the six lines are the orchestrator's proposed values accepted by the user with "dong y". Plan 16-47 implements the publish step; the hourly cadence is an exporter-schedule value, not an event-time writer.
- **Q-F:** `commit-pinned-state` (the user commits `pinned_epoch.json` to master after each pin; no credential on GitHub). Compatible with O-01 (`through_crypt_remote: no`, GitHub does not read S3).
- **Q-Q:** `off-hour-minute`, `cron: 34 * * * *`. The slot grid is HH:34. The workflow itself is edited in plan 16-47; the effect on dropped runs remains unproven (G15).

## Verification (plan level, re-run at SUMMARY time)

- `.venv/Scripts/python -m pytest tests/test_soak_evidence_export.py tests/test_paper_exit_evaluator.py -q -p no:cacheprovider` with `TEST_DATABASE_URL` set: 71 passed, none skipped (18 in the new file, including the PostgreSQL test).
- `ruff check` and `ruff format --check` on the two new files: pass. `mypy src`: Success, no issues in 181 source files. `mypy scripts/export_soak_evidence.py`: no error in the new file; one pre-existing error in `scripts/evaluate_trial_soak.py:72` (no-any-return, not touched here, scripts are outside the CI `mypy src` gate).
- Decision record verify commands: all three exit 0 (see Accomplishments).
- `uv run pytest -m "not docker" -q -p no:cacheprovider` over the whole suite (with `TEST_DATABASE_URL` set): every progress line is passes only, exit code 0 (about 30 minutes on this machine; the summary line with the total count was cut by `tail`).

## Deviations from Plan

**1. [Rule 3 - Blocking] Inputs the plan's argument list did not name**
- **Found during:** Task 1 design
- **Issue:** the plan's Test 1 argument list has no cron, grace or SHADOW inputs, but `freeze_evidence_report` needs a cron string and the user's freeze-tick grace, and `export_shadow_evidence` needs rows, a backtest part and a research universe.
- **Fix:** added `--config` (ratified runtime configuration, grace from `health.freeze_tick_grace_seconds`), `--workflow` (default the freeze workflow, cron read with the evaluator's own `read_workflow_cron`) and optional `--analytics-inputs`. No default value was invented; `--pinned` is repeatable so an archived pin can back an earlier epoch.
- **Files:** `scripts/export_soak_evidence.py`. **Commit:** fc2888c.

**2. [Rule 2 - Missing critical] Refusals for unsafe exports**
- **Issue:** an export with an unknown epoch would silently give an empty or mislabelled bundle.
- **Fix:** exit 2 when no `--pinned` file belongs to `--epoch`, when no runtime record belongs to it, when the window is not increasing, when `--out` exists, and for source/records/port mismatches (T-16-69). Tests cover each.
- **Files:** `scripts/export_soak_evidence.py`, `tests/test_soak_evidence_export.py`. **Commits:** 10bd62f, fc2888c.

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical). **Impact:** none on scope; no architectural change.

## Authentication Gates

None. The checkpoint tasks were already answered by the user; no credential was read, written or printed (the PostgreSQL test URL was passed only through the process environment).

## Known Stubs

None in the code. One documented limitation: the script does not build `ShadowRow` objects from the journal. In both sources the SHADOW analytics rows come from the optional `--analytics-inputs` file; without it the bundle has no `analytics_evidence.json` (the file is optional in the layout). Building the rows from the journal (plan 16-31 was expected to, but did not add a builder to `src/`) is open work and is not hidden: the test builds the file from the Phase 7 fixtures.

## Threat Flags

None beyond the plan's threat model. T-16-68 (sha256 per file, manifest last, verified by the loader), T-16-69 (source follows `--source` only, tests for every crossing) and T-16-70 (scan before staging, abort and removal) are mitigated and tested.

## Not run

- Real PostgreSQL soak database, real GitHub run list download and the publishing step to the O-01 location: plan 16-47 and the operator; this machine has no network.
- The workflow cron line `34 * * * *` is not set on master here (plan 16-47).

## Self-Check: PASSED

- Created files exist: `scripts/export_soak_evidence.py`, `tests/test_soak_evidence_export.py` (checked with `[ -f ]`).
- Commits exist: 10bd62f, fc2888c.
- No edit under `.github/workflows`; the three decision records, STATE.md and ROADMAP.md were not touched.
