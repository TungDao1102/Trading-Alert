---
phase: 16-paper-runtime-composition
plan: 61
subsystem: research-runner
status: partial
blocked_before: "Task 2 step (4): writing the three six-key authorization files and decisions/16-DEC-RERUN-AUTH.md. Authorizations are reserved to the owner for this run, and the permission system denied the write command. Tasks 3 and 4 depend on it and did not start."
tags: [research, runner-hardening, authorization, simulator-semantics-2.2.0, B3-WR-02, B3-WR-03, B3-WR-04, B3-WR-05]
requires: [16-60]
requirements: [BKTS-03]
requirements-completed: []
provides:
  - "result_summary_json of every research record carries the trades_digest of its window's trades (B3-WR-02); public trades_digest_of_output in src/backtest/experiment.py"
  - "constraint_source is validated as a clean repo-relative posix path by DatasetManifest and read as repo_root / constraint_source, confined to the root (B3-WR-03)"
  - "main refuses a --repo-root that is not the tree the code was imported from, before any read, simulation or write (B3-WR-04)"
  - "ParameterGrid refuses a duplicate parameter_set_id, a duplicate varied tuple (numerically, so 2 and 2.0 are one point) and points that vary different key sequences (B3-WR-05)"
  - "the required sixth authorization key simulator_semantics_version: the five-key form is malformed, a version other than SIMULATOR_SEMANTICS_VERSION is refused as simulator_semantics_version_mismatch (16-60 Q4 = B)"
  - "evidence/16-61-hashes.txt: every owner precondition passes and the manifest hash and the three grid hashes recomputed by the 2.2.0 code match all recorded sources"
  - "evidence/16-61-gate-before-rerun.txt: the full gate on the merged tree"
affects: [16-61, 16-44]
key-files:
  created:
    - tests/test_research_runner_hardening.py
    - .planning/phases/16-paper-runtime-composition/evidence/16-61-hashes.txt
    - .planning/phases/16-paper-runtime-composition/evidence/16-61-gate-before-rerun.txt
  modified:
    - src/research/run.py
    - src/research/manifest.py
    - src/research/authorization.py
    - src/backtest/experiment.py
    - tests/test_research_runner.py
    - tests/test_research_checkpoint.py
    - tests/test_research_manifest_build.py
    - tests/test_research_warmup.py
    - tests/test_research_feasibility.py
    - tests/test_research_report.py
    - tests/test_research_terminal_settlement_integration.py
    - tests/test_research_terminal_settlement_manifest.py
    - tests/test_research_register.py
key-decisions:
  - "A rule that every grid point varies the same key sequence was added: the three committed grids satisfy it (each has one key sequence, 16 points, 16 distinct tuples, checked before the rule), and their grid hashes are unchanged."
  - "The digest in a record is built from the engine output through a public wrapper (trades_digest_of_output) that rebuilds typed TradeRecords the way reproduce does, so the stored digest equals the one verify_experiment recomputes; no new digest format."
  - "Tests that used an absolute tmp constraint path now put constraints.json at the root of the repo_root they pass; main tests monkeypatch the module's _REPO_ROOT to that directory."
duration: "about 5 hours wall; the full suite (31 minutes with PostgreSQL timeouts, 15 minutes without) dominated"
completed: 2026-10-17
commits: 3
plan_head_before: dde100b994349750e8f018ede609492ec30868db
plan_head_after: 1b28ec9ab5c29390c7630d2e6fecd7eb715cc8db
actuals:
  tokens: 10500
  tasks: 1
  commits: 3
---

# Phase 16 Plan 61: Runner hardening and the 2.2.0 rerun Summary (PARTIAL)

Task 1 (the tracer) is done and committed: the runner that will produce the 2.2.0 records attests its trades, reads its inputs from the root it was imported from, refuses duplicate grids, and accepts only an authorization bound to its own simulator version. Task 2 is done through step (3) (preconditions, hash verification, refusals on the real inputs). It stopped at step (4), the writing of the three authorization files, which is reserved to the owner for this run. Tasks 3 (the rerun) and 4 (the supersede record and the final gate) did not start. No research run was made on the real manifest or the real data store.

## What was built (Task 1, commit d5067a3)

RED first, in `tests/test_research_runner_hardening.py` (32 tests). Re-check outcomes, each on the parent behavior (the sixth-key tests failed first with the five-key form accepted; the finding tests were then run with only the sixth key in place):

| Finding | Re-check on the parent | Result |
|---|---|---|
| B3-WR-02 | every record's `result_summary_json` was `{}` and `stored_trades_digest` None | confirmed; fixed |
| B3-WR-03 | a run started from an unrelated cwd exit 2 "constraint source unreadable"; the manifest accepted absolute, drive-qualified and `..` paths (11 cases DID NOT RAISE) | confirmed; fixed |
| B3-WR-04 | `main` with a `--repo-root` of another checkout exit 0 | confirmed; fixed |
| B3-WR-05 | a duplicate `parameter_set_id` and a duplicate varied tuple did not raise | confirmed; fixed |
| 16-60 Q4 = B | the three existing five-key files loaded; a wrong version was never checked | fixed |

- `src/research/authorization.py`: `RunAuthorization.simulator_semantics_version`, the key in `_AUTHORIZATION_KEYS`, `load_authorization` requires exactly six keys with a non-empty string, `require_authorized` raises `simulator_semantics_version_mismatch` (names the key only, never the statement). The three existing five-key files are read from disk by a test and are refused as malformed; they are byte-unchanged.
- `src/research/run.py`: `_result_summary_json(output)` = canonical JSON of `{"trades_digest": ...}`, passed by `_assemble_split`; because the existing record-file byte comparison covers it, a reused checkpoint window whose trades differ from the record on disk ends with `ExperimentAlreadyRecorded` (tested). `_confined_path` is shared by `_evidence_bytes` and `_load_constraints(manifest, repo_root)`. `main` calls `_is_import_root` first (exit 2, one line, `repo_root_mismatch`).
- `src/research/manifest.py`: one `_require_repo_relative_path` used by `EvidenceFile` (message unchanged) and by `DatasetManifest.constraint_source`; the grid checks above.
- `src/backtest/experiment.py`: `trades_digest_of_output`.
- The committed manifest still loads and `manifest_hash` equals `ec161733...ac569`; the three committed grids load and keep their hashes (tests read evidence/16-46-hashes.txt).

Task 1 verification: the plan's six-file test command, 191 passed (3m14s); `mypy src` clean.

## Task 2 results (commit d5bdef2)

evidence/16-61-hashes.txt (HEAD d5067a3): every precondition line reads `pass`: SUMMARY files and completion commits of 16-55, 16-56, 16-57, 16-58, 16-59, 16-62, 16-60 in that git order; 16-60 gate file has 6 `exit=0` lines, no non-zero; `SIMULATOR_SEMANTICS_VERSION` 2.2.0 and protocol header v2.5.0; DECISIONS holds exactly one row each of D072, D073, D074 and D074 holds the owner's paragraph; the Holdout marker is `holdout-consumed/2`, `v2.5.0`, empty entries; Task 1 committed with its tests green; the output directory does not exist; no glob over `docs/research/experiments/` in src/, scripts/ or tests/.

Hashes (13 comparison lines, all `match`): the manifest hash `ec161733076f99e626da6900b7cc354ed68aa3104f5ac60de486b3b39f7ac569` recomputed by the 2.2.0 `load_manifest` + `manifest_hash` equals evidence/16-46-hashes.txt and `manifest_sha256` of all three existing authorization files; the grid hashes trend-pullback `13207b30...4411`, breakout-retest `2ed8577e...4069`, range-mr `3388fceb...97c6` equal evidence/16-46-hashes.txt, the existing authorization files and 16-45-SUMMARY.md. Task 2's first verify command passes (13 comparison lines, 13 match, no label missing).

Refusals on the real inputs (six, all as expected, exit 2, output directory never created, nothing on stdout): each family without an authorization prints `run refused: missing`; each family with its old five-key file prints `run refused: malformed`.

## Pending, owner-only

1. **The three authorization files and `decisions/16-DEC-RERUN-AUTH.md` (Task 2 step 4).** Not written. The values are verified and recorded at the end of evidence/16-61-hashes.txt: file `docs/research/preregistration/research-run-1-v2-2-0-authorization-<family>.json` with `grid_sha256` (the family's hash above), `manifest_sha256` `ec161733...ac569`, `authorized_at_utc` `2026-10-16T07:22:56+00:00` (author date of bdbdc11 in UTC), `statement` (the plan's text plus the `words:` line of 16-DEC-FIXPLANS.md in quotes), `authorized_by` `Tung Dao`, `simulator_semantics_version` `2.2.0`. The owner either confirms in the session that the agent may write them (the owner's decision in 16-DEC-FIXPLANS.md already permits it, but this run was told not to sign authorizations and the permission system denied the write), or writes the three files. Then the continuation re-checks the precondition lines at HEAD, writes the record `16-DEC-RERUN-AUTH.md` (layout of 16-DEC-RERUN-AUTH-FORM.md, three reviewer subsections copied by script, correction 7, renumbering mapping line `reviewer text says D072 and D073; recorded as D073 and D074`), verifies the two Task 2 commands that read the files, and commits.
2. **A running PostgreSQL for the PostgreSQL tests.** Docker Desktop cannot start on this machine (WSL engine bootstrap error), so with `TEST_DATABASE_URL` set 483 tests error with `psycopg ConnectionTimeout` and 3 more fail the same way. The 487 PostgreSQL tests have not run on the merged tree. The owner starts a PostgreSQL (Docker Desktop repair or another server) and the gate is rerun with the variable set.
3. **Task 3 (the rerun) and Task 4 (supersede record `16-DEC-RUN1-SUPERSEDED.md`, note on the 2026-10-16 feasibility table, final `16-61-gate.txt`)** follow once item 1 is done. Task 3 is a multi-hour sequential run (trend-pullback, breakout-retest, range-mr) in a separate worktree at a fixed commit; the evidence must state that the first Development window starts cold (the data begins 2024-10-03). Task 4's gate must run after the rerun, on a machine with PostgreSQL. `BKTS-03` stays open: `requirements.ready-ids` was not called to mark it, and it was not marked.

## Gate numbers (evidence/16-61-gate-before-rerun.txt, commit 1b28ec9)

`pytest -m "not docker" -rs`, TEST_DATABASE_URL unset: exit 0, 9742 passed, 493 skipped (487 PostgreSQL, 6 platform skips as in the 16-60 gate), 28 deselected, 0 failed, 15m26s. `ruff check` exit 0; `ruff format --check` exit 0 (626 files); `mypy src` exit 0 (202 files); `uv lock --check` exit 0.

The first full run, on commit d5bdef2 with `TEST_DATABASE_URL` set and no PostgreSQL server: 4 failed, 9742 passed, 6 skipped, 483 errors (30m50s). 483 errors and 3 failures are the PostgreSQL connection timeout; the fourth failure was a real one found by the new duplicate rule and fixed in 1b28ec9.

## Deviations from Plan

**1. [Rule 3 - Blocking] Existing tests had to follow the new rules.** Found during Task 1. The new `constraint_source` rule and the sixth key broke tests that built a manifest with an absolute tmp constraint path, `repo_root=REPO_ROOT`, or the five-key authorization. Fixed in tests/test_research_runner.py, test_research_checkpoint.py, test_research_manifest_build.py, test_research_warmup.py, test_research_feasibility.py, test_research_report.py, test_research_terminal_settlement_integration.py and test_research_terminal_settlement_manifest.py (the plan lists only the first three and the hardening file). In test_research_checkpoint.py the two-point grid now uses the first two points of the committed trend-pullback grid, because baseline-v5 and baseline-v6 share every varied key value. Commit d5067a3.

**2. [Rule 1 - Bug] tests/test_research_register.py helper wrote the same varied value for every point.** Found by the full gate; the new duplicate rule refused the grid. The helper now uses a distinct value per point. Test-only. Commit 1b28ec9.

**3. [Rule 2 - Missing] Public `trades_digest_of_output`.** The plan says to use the existing `trades_digest`; it takes typed `TradeRecord`s while the engine output holds dicts, so a one-line public wrapper over the existing `_trade_from_dict` and `trades_digest` was added (same format as `reproduce`). Commit d5067a3.

**4. [Rule 2 - Missing] The key-sequence rule.** The plan allows it only if all three committed grids satisfy it; they do (checked before adding it), so it was added. Commit d5067a3.

**5. Task 2 step (4) not done; Tasks 3 and 4 not started.** See the pending section. Authorizations are the owner's for this run and the write command was denied by the permission system; nothing was worked around.

**6. The gate was run twice, and the PostgreSQL tests did not run.** See the gate section. `evidence/16-61-gate-before-rerun.txt` is an addition to the plan's file list; the plan's `16-61-gate.txt` is the post-rerun gate and does not exist yet.

## Known Stubs

None.

## Threat Flags

None. The new code paths only read files under the repository root the code was imported from (T-16-167, T-16-168 mitigated); no new network, auth or schema surface.

## Self-Check: PASSED

- Files exist: `tests/test_research_runner_hardening.py`, `evidence/16-61-hashes.txt`, `evidence/16-61-gate-before-rerun.txt`, this summary.
- Commits exist: `d5067a3` (Task 1), `d5bdef2` (Task 2 evidence), `1b28ec9` (register test fix).
- Not self-checked because not produced: the three authorization files, `16-DEC-RERUN-AUTH.md`, the 240 records, `16-DEC-RUN1-SUPERSEDED.md`, `16-61-gate.txt`.
