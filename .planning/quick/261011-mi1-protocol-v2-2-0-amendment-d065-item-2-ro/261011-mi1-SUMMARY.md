---
phase: quick-261011-mi1
plan: 01
subsystem: research-protocol / experiment-identity
tags: [protocol-v2.2.0, D065, D067, REV-16, route-B, experiment-identity, decision-alignment]
requires: [16-DEC-REV-16 (route B, locked)]
provides:
  - "ExperimentRecord.data_manifest_hash (seventh identity field) and assemble keyword"
  - "analytics-evidence/2 optional experiment key data_manifest_hash"
  - "research protocol v2.2.0 frozen (header, D067, DOC_STATUS, research-gate witnesses)"
  - "decision-alignment gate PR-11"
affects: [plan 16-37 (seam already wired), plan 16-46]
status: complete
commits: 6
plan_head_before: de81ee8f80565b519801bc5776e622a29b48ac35
plan_head_after: 3bfcd325cf959e9402a94f4d326f4f785f1b59ef
actuals:
  tokens: 19000
  tasks: 3
  commits: 6
key-files:
  modified:
    - src/backtest/experiment.py
    - src/adapters/analytics_files.py
    - src/research/run.py
    - src/research/feasibility.py
    - scripts/decision_alignment/protocol.py
    - scripts/verify_decision_alignment.py
    - docs/research/RESEARCH_PROTOCOL.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/research/holdout_consumed.json
    - docs/configuration/CONFIGURATION.md
    - docs/backtest/BACKTEST_SPEC.md
    - docs/data/DATA_MODEL.md
    - .github/workflows/research-gate.yml
decisions:
  - "Route B: seventh identity field data_manifest_hash = manifest_hash(manifest); data_snapshot_id semantics, dataset_id formula and both bindings unchanged (D067)"
  - "Evidence loader: data_manifest_hash is the one OPTIONAL key of the analytics-evidence/2 experiment object (absent -> None, present -> 64 lowercase hex, null/non-str/unknown refused); no schema bump, no fixture value moves"
  - "assemble requires the keyword (fail closed), which forces the one-line runner seam wiring here"
  - "Kill-gate report provenance does not render the field (would move render goldens and digests)"
---

# Phase quick-261011-mi1 Plan 01: Protocol v2.2.0 amendment (D065 item 2, REV-16 route B) Summary

Research protocol v2.2.0 is frozen: every experiment record now names, through a seventh identity field `data_manifest_hash` (protocol name `dataManifestHash`, equal to `manifest_hash(manifest)`, the value a run authorization binds as `manifest_sha256`), exactly the frozen manifest the user authorized; `data_snapshot_id` and its bindings are untouched.

## Record

- BASE (HEAD before Task 1): `de81ee8f80565b519801bc5776e622a29b48ac35`
- Final landing commit: `3bfcd325cf959e9402a94f4d326f4f785f1b59ef`
- v2.1.0 text commit cited in the migration paragraph and D067: `d52cd6a5316ca052a80bfee5190ddeeadbe128c5`

| Task | Phase | Commit | Message |
|------|-------|--------|---------|
| 1 | RED | f2cceba | test: failing tests for the seventh identity field data_manifest_hash |
| 1 | GREEN | 652e7eb | feat: data_manifest_hash joins the experiment identity (REV-16 route B) |
| 2 | RED | 03049db | test: witness tests expect research protocol v2.2.0 (D067) |
| 2 | GREEN | 03573db | docs: research protocol v2.2.0 frozen (D067) |
| 3 | RED | 91c1468 | test: failing tests for decision-alignment gate PR-11 |
| 3 | GREEN | 3bfcd32 | feat: decision-alignment gate PR-11 pins the seven identity names (D067) |

## What changed

- `assemble` takes a required keyword `data_manifest_hash` (64 lowercase hex, else `IncompleteExperimentRecord` naming the field, never echoing the value); it joins the `experiment_id` payload right after `data_snapshot_id`. `ExperimentRecord.data_manifest_hash: str | None` (None only for a record read from evidence written before v2.2.0); `to_dict` emits the key only when set, so a pre-v2.2.0 record round-trips to the same bytes.
- Lines of `assemble` that bind `dataset_id == data_snapshot_id` and `_check_run_binds_record` were not touched; `src/data/case_input.py` untouched.
- Loader choice: `_EXPERIMENT_OPTIONAL_KEYS = ("data_manifest_hash",)` in `src/adapters/analytics_files.py`; the schema name stays `analytics-evidence/2`; `tests/fixtures/phase10/loaders/evidence_sample.json` is unchanged and loads with `None`.
- Runner seam consequence for plan 16-37: `experiment_identity_inputs` in `src/research/run.py` is already wired to `manifest_hash(manifest)` (required because `assemble` now demands the field). Plan 16-37's seam edit therefore reduces to a check that this wiring is in place; its manifest `--build`, authorization-mapping test and consistency re-check remain its own work. Plan 16-37's file was not edited.
- Provenance-rendering choice: `src/analytics/provenance.py` and `render_metrics.py` keep their current identity projection and do not render `data_manifest_hash` (it would move render goldens and report digests). The value is carried by every record and evidence file. Rendering it is a separate change if wanted. The provenance test constant was renamed `REPORTED_IDENTITY_FIELDS` with a comment saying so.
- Docs: protocol header v2.2.0 (Frozen on 2026-09-19 unchanged, Amended on 2026-10-11, Supersedes v2.1.0), migration paragraph, section 5 with seven fields and "all seven", amendment log entry, DECISIONS D067 (one added line, directly after D066), DOC_STATUS index and change-log lines, `holdout_consumed.json` `protocol_version` v2.2.0 (schema `holdout-consumed/2`, entries empty), CONFIGURATION section 7, BACKTEST_SPEC, DATA_MODEL 2.12, research-gate REQUIRED list, feasibility citations ("unchanged since v2.1.0", constants untouched).
- PR-11 (`check_identity_linkage`, `IDENTITY_LINKAGE_FIELDS`) pins section 5, CONFIGURATION section 7 and the `ExperimentRecord` field names (order, "all seven"); `EXPECTED_MIN["protocol"]` is 11.
- "Preregistration and license" text named by D065 item 2 does not exist in the repository yet (plans 16-37/16-46 create it under v2.2.0); nothing to update.

## Verification

- G1/G5 byte-diff: changed `**G1 (` / `**G5 (` lines between BASE and HEAD = 0; the G1 and G5 sentences hash identically at BASE and HEAD.
- `git diff BASE HEAD` over `params`, `tests/fixtures`, `src/data/case_input.py`, `.planning/phases`, `.planning/STATE.md`, `.planning/ROADMAP.md`, `uv.lock`: empty. (The working tree carries pre-existing uncommitted STATE/ROADMAP/config/state changes from the orchestrator; none were staged.)
- DECISIONS.md numstat vs BASE: 1 added, 0 deleted.
- Task 1 verify list (experiment, analytics_files, research_runner, binding, provenance, report, render, backtest_report, cost_per_unit): all passed; mypy, ruff check, ruff format clean.
- Task 2 verify list (kill_gate_docs, bookkeeping, protocol, decision_alignment, research_gate_negative, research_feasibility, kill_gate_clock, deploy_workflows): all passed; `verify_decision_alignment.py all` ALL_PASS, PR-01..PR-11, DC-01..DC-06.
- Task 3: protocol/decision_alignment/provenance tests passed.
- `uv run pytest tests -k "research or analytics"`: 616 passed, 2 skipped.
- Full `uv run pytest -m "not docker"` (no TEST_DATABASE_URL): 5906 passed, 453 skipped, 1 failed: `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments`, the known pre-existing failure (neither the test nor the code it covers was touched by this task).
- `uv run ruff check`, `uv run ruff format --check` (510 files), `uv run mypy src` (178 files), `uv lock --check`: clean.
- All six commits end with the `Co-Authored-By: Claude Sonnet 5.5` trailer (the caller's instruction replaced the plan's "Opus 5.5" wording).

## Deviations from Plan

None in behavior. Notes:
- Process: `sed -i` on a CRLF test file silently turned it to LF; the CRLF was restored with a script before commit. All CRLF files kept CRLF in the working copy (git normalizes via autocrlf).
- The first `git add` of Task 2 returned a nonzero status on an advisory about an ignored-path hint (`docs/data` is tracked, files were staged); the commit was repeated after confirming the staged set, so no commit contained anything unplanned.
- The commit trailer follows the orchestrator's instruction (Sonnet 5.5) rather than the plan text (Opus 5.5).

## Known Stubs

None.

## Threat Flags

None. The optional evidence key is the only new input surface and is validated (T-mi1-01).

## Self-Check: PASSED

- 22 files changed between BASE and HEAD, exactly the plan's `files_modified` list.
- All six commit hashes exist in `git log de81ee8..HEAD`.
