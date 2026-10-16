---
phase: 16-paper-runtime-composition
plan: 59
subsystem: paper-evidence-export-and-freeze-workflow
status: complete
tags: [soak-evidence, export, publish, freeze-workflow, concurrency, gate, B2-CR-04, B2-WR-05, B2-WR-06]
requires: [16-55, 16-58]
requirements: [PAPER-01]
requirements-completed: []
provides:
  - "scripts/export_soak_evidence.py --as-of (default: the injected now, at most window end plus the ratified grace): only a slot with slot + freeze_tick_grace_seconds <= as_of is judged, gaps carry detected_at = as_of, the manifest records as_of_utc"
  - "bundle_is_partial and EvidenceBundle.as_of_utc; scripts/evaluate_trial_soak.py exits 2 with one line for a partial bundle"
  - "per-bundle create-only key <epoch>/<as_of YYYYMMDDTHHMMSSZ>-<sha12 of the manifest bytes>/<file>; identical bytes are a success that uploads nothing; different bytes at an existing key exit 4 before anything is uploaded"
  - "merge_freeze_logs: --diff-log repeats per run artifact, derived registry_diff.jsonl deduplicated by (run_id, run_attempt), originals kept as freeze_artifact_<16 hex>.jsonl, manifest freeze_log provenance, conflicts exit 4"
  - "missing_ticks.jsonl (MissingTick in the loader): every judged tick without a usable line with slot, run id, status and conclusion"
  - "freeze workflow concurrency group paper-freeze-check with cancel-in-progress false and queue max"
  - "RUNBOOK 20.7 rewritten, docs/SOURCES.md row for the GitHub concurrency facts, decisions/16-DEC-EVIDENCE-KEYS.md and 16-DEC-FREEZE-LOG-ASSEMBLY.md"
  - "deferred-items.md dispositions and evidence/16-59-gate.txt with GATE_COMMIT"
affects: [16-62, 16-43, 16-44]
tech-stack:
  added: []
  patterns:
    - "a bundle is judged AS OF an instant; an hourly export is partial and cannot be evaluated"
    - "the storage key is derived from the manifest bytes only, so a re-publish of the same bytes is the same key"
    - "union of the artifacts deduplicated by run identity, ordered by time, originals kept next to the derived file"
    - "a missing artifact is a recorded missing tick, never a clean tick"
key-files:
  created:
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-EVIDENCE-KEYS.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-FREEZE-LOG-ASSEMBLY.md
    - .planning/phases/16-paper-runtime-composition/evidence/16-59-gate.txt
  modified:
    - scripts/export_soak_evidence.py
    - scripts/evaluate_trial_soak.py
    - src/paper/evidence_bundle.py
    - .github/workflows/paper_freeze_check.yml
    - docs/operations/RUNBOOK.md
    - docs/SOURCES.md
    - tests/test_soak_evidence_export.py
    - tests/test_paper_exit_evaluator.py
    - tests/test_paper_freeze_workflow_pin_source.py
    - tests/test_deploy_workflows.py
    - tests/test_soak_runbook.py
    - .planning/phases/16-paper-runtime-composition/deferred-items.md
key-decisions:
  - "The default --as-of is the clock reading, clamped to window end plus grace so a late final export is final; an explicit --as-of outside the pin to window end plus grace range is refused (exit 2)."
  - "Missing ticks are a hash-listed optional file (missing_ticks.jsonl), not a manifest field, so the loader verifies it like every other file. Original artifacts are flat files freeze_artifact_<first 16 hex of the sha256>.jsonl, so the one-level rclone listing still sees them."
  - "A conflict at an existing storage key is detected for every present object before the first upload, so a refused publish changes nothing in the bucket."
  - "No new number appears in code: the due bound is the ratified freeze_tick_grace_seconds, the slot step is the existing SLOT_INTERVAL_SECONDS."
duration: "not measured; the full-suite run of the gate alone took 15 min 32 s"
completed: 2026-10-16
commits: 4
plan_head_before: a1c29390ab4feae1b09755d43c22c7f6644c95f8
plan_head_after: f8230fd0e1b1f39de20aa201874b78d60e304054
actuals:
  tokens: 20000
  tasks: 4
  commits: 4
---

# Phase 16 Plan 59: Evidence export and workflow Summary

Plan 16-59 makes the hourly evidence export publishable and honest, and ends the blocking set 16-55 to 16-59 on one green, recorded commit.

- An hourly bundle records a gap only for a tick that has already happened, and the evaluator will not judge a bundle exported before the window end plus the grace.
- Every hourly bundle and the final bundle has its own create-only key, so the second hourly publish and the final one no longer exit 4. Publishing the same bundle again is a success.
- The freeze lines of every available run artifact survive in one derived log with provenance, the original artifacts are kept byte for byte, and every tick without a usable line is a recorded missing tick.
- The freeze workflow runs one tick at a time with `queue: max`.

GATE_COMMIT is `a54f9da47ca8b7b7c6c2488b0d8cb67b506f4ba0`. The soak image is NOT built from it: plan 16-62 changes the runtime next and records the image commit.

## Tasks

| Task | Name | Commit |
| --- | --- | --- |
| 1 | Tracer: an export before the window end records no future gap, and the evaluator refuses a partial bundle (B2-WR-06) | 8858fef |
| 2 | Owner decisions recorded, per-bundle keys, merged diff log with missing ticks, workflow concurrency group, RUNBOOK 20.7 (B2-CR-04, B2-WR-05) | 94e3e15 |
| 3 | Dispositions of the findings the gap-fix plans do not fix, in deferred-items.md | a54f9da |
| 4 | Final gate of the blocking set (GATE_COMMIT) | f8230fd |

Commit count, measured: `git rev-list --count a1c2939..HEAD` is 4 before this metadata commit. Each of tasks 1 and 2 is one commit holding its tests and its fix; the failing runs on the parent are recorded below (the tests were written first and run against the parent code).

## Re-check outcomes

All three findings held. No finding was closed with a note.

- **B2-WR-06 (future gaps).** A fixed 14-day window, an empty run list and an export made three hours into the epoch (the same inputs a real hourly run has): the parent wrote 336 NO_RUN_FOUND lines, 333 of them for slots after hour three, with `detected_at_utc` 2026-11-15 (the window end). After the change the same export with `--as-of` at hour three writes 3 gaps (00:17, 01:17, 02:17), detected at the as-of instant.
- **B2-CR-04 (second publish).** The parent test `test_an_epoch_prefix_that_already_holds_a_manifest_is_never_published_over` documented the refusal: any manifest under `<epoch>/` made the next publish exit 4. The new test publishes the hour-1, hour-2 and final bundle of one epoch to one fake uploader; before the change this failed, after it all three succeed under three different keys.
- **B2-WR-05 (overlap).** A model of the documented cache semantics (restore the newest cache with the prefix `paper-freeze-`, save under `paper-freeze-<run_id>`), recorded in `decisions/16-DEC-FREEZE-LOG-ASSEMBLY.md`: runs a and b restore the same state S and save S+a and S+b; the third run restores S+b, so its artifact lacks the line of run a, which survives only in run a's artifact. A test in `tests/test_soak_evidence_export.py` builds exactly this and shows the merge recovers the line. This is a model; it was not observed on live GitHub (no network).

RED evidence (failing on the parent, then green):

- Task 1: all export tests failed on the parent because `--as-of` was an unrecognised argument (`unrecognized arguments: --as-of ...`), plus the `as_of_utc` attribute and manifest tests of `tests/test_paper_exit_evaluator.py` (`AttributeError: 'EvidenceBundle' object has no attribute 'as_of_utc'`; `DID NOT RAISE BundleError`). The refusal test also asserts the text `cannot export` so an argparse refusal cannot pass for it.
- Task 2: after adding only the loader names (constants and `MissingTick`, so the test module imports), 23 tests failed on the parent exporter, workflow, RUNBOOK and SOURCES: the tracer, hourly/final/re-publish/forged-key/missing-`as_of_utc` publish tests, the merge, order, model, conflict, loose-line, single-artifact tests, both missing-tick tests, the empty missing-tick file test, `test_the_workflow_serialises_its_runs_and_queues_up_to_the_maximum`, `test_paper_freeze_check_runs_one_tick_at_a_time_and_queues_instead_of_cancelling`, the two RUNBOOK 20.7 tests and the SOURCES row test.

## What changed

**As-of export (B2-WR-06).**
- `_as_of` reads `--as-of` or the injected clock (`main(..., now=...)`), floors to whole seconds, clamps the default to window end plus grace and refuses an explicit value before the epoch pin or after window end plus grace (exit 2).
- `freeze_evidence_report` is called with `window_end_utc = min(end, as_of - grace)` and `detected_at_utc = as_of`. The function itself is unchanged, so `tests/test_paper_freeze_evidence.py` and `tests/test_paper_coverage.py` pass untouched.
- The manifest records `as_of_utc`; `EvidenceBundle.as_of_utc` and `bundle_is_partial(bundle, grace_seconds)` read it. A manifest without `as_of_utc` is final, as before. The bundle schema string stays `soak-evidence-bundle/1`: the loader accepts both forms, because the new manifest fields and files are optional.

**Per-bundle keys (B2-CR-04).** `bundle_prefix` derives `<epoch>/<as_of>-<sha12>` from the manifest bytes only. `publish_bundle` lists the prefix, checks every present object (and the manifest if the bundle is complete) before it uploads anything, uploads the missing files, the manifest last, and reads everything back against the manifest sha256. A complete identical bundle uploads nothing. The `publish` subcommand refuses a manifest without `as_of_utc` (exit 2). No flag can type a key.

**Merged log and missing ticks (B2-WR-05, correction 3).**
- `--diff-log` repeats. `merge_freeze_logs` reads each artifact (an unreadable or non-UTF-8 one is an input error naming the file), collapses artifacts of equal bytes, deduplicates by `(run_id, run_attempt)`, refuses two different lines of one identity (`FreezeLogConflict`, exit 4), deduplicates lines without run metadata by their exact bytes, and orders by `checked_at_utc`, then identity, then bytes. The result does not depend on the argument order.
- For one artifact that is already in time order the derived log equals it byte for byte (the existing tests keep their equality assertions); the artifact is also stored as `freeze_artifact_<16 hex>.jsonl`.
- The manifest `freeze_log` section says `derived: true`, carries the merge description ("not a byte copy of one artifact") and lists each input artifact with its file name, sha256 and the run ids it carried, in sha256 order.
- `missing_ticks.jsonl` has one row per EVIDENCE_GAP of the report (with the assigned run's status and conclusion) plus one per scheduled run, after the pin and inside the judged grid, that left no freeze line (for example a cancelled run). The slot of such a run is a gap whatever the artifacts say, never CLEAN.

**Workflow and documents.** `concurrency: group: paper-freeze-check`, `cancel-in-progress: false`, `queue: max` after the permissions block; nothing else in the workflow changed. RUNBOOK 20.7 states the key layout and the create-only rule (correction 4), the as-of flag and partial bundles, the merge and the missing ticks, the concurrency group and the residual risk with the GitHub documentation URL and read date. `docs/SOURCES.md` has one row for the GitHub concurrency facts (WebFetch summary, not verified live, MEDIUM). The records `16-DEC-EVIDENCE-KEYS.md` (`option: Q1-per-bundle-key`) and `16-DEC-FREEZE-LOG-ASSEMBLY.md` (`option: Q2-merge-artifacts`) were copied by a script from `16-DEC-FIXPLANS.md` and the reviewer text and checked byte for byte (the user's line, the reviewer section, correction 4, correction 3 and the queue amendment).

**Dispositions (Task 3).** One dated section in `deferred-items.md`: B1-WR-04 with the owner's reopen rule, B1-WR-09 as fixed by plan 16-62, the three Info groups with owner and reason, the two Phase 26 items referenced and not registered again, and a line that no Warning of plans 16-55 to 16-58 was closed with a "does not hold" note. The existing content is an exact prefix of the new file.

## Gate (Task 4)

All five commands exit 0 on `a54f9da` (evidence/16-59-gate.txt):

- `pytest -m "not docker"`: 10099 tests ran, 10093 passed, 6 skipped, 0 failed (counted from the progress lines; the project configuration is quiet and prints no count line). Skips: symlinks (1), POSIX file modes on NTFS (1 + 4). TEST_DATABASE_URL was set on this machine, so the PostgreSQL tests ran.
- `ruff check` clean, `ruff format --check` 617 files already formatted, `mypy src` no issues in 202 source files, `uv lock --check` resolved.
- `git diff --name-only c654524 HEAD -- params/ ... research-run-1-manifest.json ... grid-*.json ... authorization-*.json ... config/paper/paper-runtime-v1.toml` printed nothing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The Task 3 verify command cannot pass as written**
- **Found during:** Task 3
- **Issue:** the command asserts `t.count('B3-CR-02')==1`, but the existing line (commit 010fcca) already holds that id twice (`B3-CR-02 (...)` and `[B3-CR-02]`). It also compares the working file with the blob of 010fcca, which fails on this machine because the working tree has CRLF line endings (`core.autocrlf`) while the blob has LF.
- **Fix:** the new section does not mention the id, so it appears exactly as often as in 010fcca (2, all in the old line); the working file was normalised to LF so it is byte-for-byte the blob plus the appended section. The adapted check compares the count with the count in the old blob and prints True.
- **Files modified:** `.planning/phases/16-paper-runtime-composition/deferred-items.md`
- **Commit:** a54f9da

**2. [Rule 1 - Bug] Existing export tests had to give `--as-of`**
- **Found during:** Task 1
- **Issue:** the default as-of is the clock, and the fixtures pin the epoch in the future of the development machine (2026-11-01 while the clock reads 2026-10-16), so the default is refused as before the pin.
- **Fix:** `Inputs.argv` in `tests/test_soak_evidence_export.py` passes an explicit `--as-of` (window end plus the 300 s grace, a final bundle) unless a test omits it; the gap expectation uses that as-of as `detected_at_utc`. Nothing in the exporter was changed for this.
- **Commit:** 8858fef

**3. [Rule 2 - Missing critical functionality] A refused publish must not half-upload**
- **Found during:** Task 2
- **Issue:** the first version checked present objects while uploading, so a conflict at the last object left the earlier ones uploaded.
- **Fix:** every present object is compared first, then the missing files are uploaded, the manifest last.
- **Commit:** 94e3e15

### Design choices inside the plan (not deviations)

- Missing ticks are a hash-listed optional file, not a manifest field, and the original artifacts are flat `freeze_artifact_<16 hex>.jsonl` files (the plan allowed both choices). `OPTIONAL_FILES` gains `missing_ticks.jsonl`; the loader accepts the artifact name pattern next to the known names, so a foreign name is still refused.
- `EXIT_CONFLICT = 4` is an alias of the publish exit code, as the plan says "exit 4" for both.

## Not shown by any test (stated in RUNBOOK 20.7)

- Whether GitHub accepts `queue: max` in this workflow, and what it does with more than 100 waiting runs. The documentation was read by the planner, not verified live. The workflow test checks only the text; the first live run is the proof. Recorded in `.planning/WINDOWS.md` as an unrun verify.
- The output shape of `gh api` and `gh run download`, the real bucket and its policy: operator checks on the real accounts.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, authentication path or file access outside the exporter's existing inputs and outputs. The threat register of the plan is covered: T-16-155 (as-of bound, partial bundle refused), T-16-156 and T-16-157 (per-bundle create-only keys, read-back kept, rclone `--immutable` kept), T-16-158 and T-16-175 (concurrency group, merged log, run-identity conflicts refused, originals kept with sha256), T-16-159 (one recorded GATE_COMMIT, user-owned inputs unchanged).

## Next

Plan 16-62 (B1-WR-09) runs next and records the soak image commit and the targeted re-review range `c654524..IMAGE_COMMIT`; then 16-60 and 16-43, then 16-61 and 16-44. PAPER-01 is not marked complete: `requirements.ready-ids` reports it blocked.

## Self-Check: PASSED

Every file named above exists and the four task commits (8858fef, 94e3e15, a54f9da, f8230fd) are in the history.
