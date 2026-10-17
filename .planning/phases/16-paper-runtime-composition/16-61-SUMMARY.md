---
phase: 16-paper-runtime-composition
plan: 61
subsystem: research-runner
status: partial
blocked_at: "Task 3, family trend-pullback: the 2.2.0 rerun exited 1 (ValueError take_profit_json tp2 must be a positive finite price) after two windows of point a01; 0 experiment records written. Per the owner rule the rerun stopped; breakout-retest and range-mr were not started; Task 4 (supersede record, note, final gate) was not started because it states that the regenerated records exist."
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
  - "evidence/16-61-gate-before-rerun.txt: the full gate on the merged tree without PostgreSQL; evidence/16-61-gate-with-postgres.txt: the same gate with PostgreSQL, all green"
  - "the three owner-written six-key authorization files and decisions/16-DEC-RERUN-AUTH.md, verified without simulation and committed (dce3195)"
  - "evidence/16-61-run-output.txt: the technical state of the stopped rerun"
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
commits: 5
plan_head_before: dde100b994349750e8f018ede609492ec30868db
plan_head_after: dce3195f71fbc0c07564dc8f6693e5084fb0cf71
actuals:
  tokens: 14000
  tasks: 2
  commits: 5
---

# Phase 16 Plan 61: Runner hardening and the 2.2.0 rerun Summary (PARTIAL)

Task 1 (the tracer) and Task 2 are done and committed: the runner that will produce the 2.2.0 records attests its trades, reads its inputs from the root it was imported from, refuses duplicate grids and accepts only an authorization bound to its own simulator version; the preconditions, the hash verification and the owner-written authorization files check out. Task 3 (the rerun) STARTED and STOPPED at the first family: trend-pullback exited 1 with 0 experiment records written (see "Task 3: the rerun stopped" below). The rerun is not complete and is not labelled complete. Task 4 (supersede record, note on the 2026-10-16 table, final gate) was not started, because the supersede record states that the regenerated records exist. The plan stays `partial`; BKTS-03 stays open.

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

## Task 2 completion (commit dce3195)

The owner ran a script themself and wrote the three files `docs/research/preregistration/research-run-1-v2-2-0-authorization-{trend-pullback,breakout-retest,range-mr}.json` and `decisions/16-DEC-RERUN-AUTH.md` (session words: "Ký ba file authorization làm như thế nào, tôi uỷ quyền cho bạn làm luôn", then "xong rồi, và tôi cũng đã restart docker"). The agent did not create or edit them; it verified them without simulation and committed them with the evidence (section (5) of evidence/16-61-hashes.txt):

- preconditions re-checked at HEAD 9547ce6 (18 pass lines, no failure): SUMMARY files and git order 16-55, 56, 57, 58, 59, 62, 60; 16-60 gate 6 `exit=0`; simulator 2.2.0; protocol header v2.5.0; DECISIONS rows D072, D073, D074 once each and D074 holds the owner's paragraph; Holdout marker `holdout-consumed/2`, v2.5.0, empty entries; Task 1 committed; tracked tree clean; output directory absent; no glob over `docs/research/experiments/`. Task 1's six-file test command ran again (191 dots, no failure) and `mypy src` is clean.
- each file has the six keys in order; `load_authorization` accepts it; `require_authorized` passes against the real manifest and the family's real grid (no simulation); `grid_sha256` is the hash of the family in the file name (checked against the hash recomputed by the 2.2.0 `load_grid` + `grid_hash` and against evidence/16-46-hashes.txt), `manifest_sha256` is `ec161733...ac569`, `simulator_semantics_version` is `2.2.0`, `authorized_at_utc` is `2026-10-16T07:22:56+00:00`, and `statement` equals the plan's text plus the `words:` line of 16-DEC-FIXPLANS.md verbatim.
- `16-DEC-RERUN-AUTH.md` holds the owner's words, the three reviewer subsections byte-equal to the reviewer-text file, the mapping line `reviewer text says D072 and D073; recorded as D073 and D074` and the owner's note.
- the three old authorization files and the frozen manifest are byte-unchanged against 5f8269b (Task 2's third verify command passes); Task 2's first and second verify commands pass (13 comparison lines, 13 match; three files, one per family).
- observation, not edited: each statement says "File written by Claude on the user's explicit permission", the text the plan prescribes, while the files were in fact produced by the owner's script.

## Task 3: the rerun stopped at trend-pullback

Setup: `RUN_COMMIT` dce3195f71fbc0c07564dc8f6693e5084fb0cf71; separate worktree `C:\Users\daotu\trading-rerun-v220` (detached, clean); `r._REPO_ROOT` printed the worktree path; empty checkpoint directories `C:\Users\daotu\rerun-v220-ck\<family>`; main `.venv` python; `--raw-root` the main `data/raw`; `--output-dir` `docs/research/experiments/research-run-1-v2-2-0` in the main tree; `--time-run`. The run ran as one background process per family in the order trend-pullback, breakout-retest, range-mr, stopping at the first non-zero exit.

Result (evidence/16-61-run-output.txt): trend-pullback started 2026-10-17T08:50:31Z and ended 09:03:15Z (12 min 44 s) with exit code 1. Uncaught `ValueError: take_profit_json tp2 must be a positive finite price, got '-0.001548100000000000'` raised by `src/backtest/exits.py` `take_profit_levels` (called from `protective_levels_for_fill` in `_size_and_register`). 0 experiment records were written; the output directory was never created; the checkpoint directory holds 2 saved windows of point a01 (the Development window and the Validation window starting 2025-07-22) and the failing window is the next one of a01 (inferred from the files). The cold-start line for the first Development window was printed and is recorded. No performance section was inspected, nothing was retried, edited or worked around, breakout-retest and range-mr were not started, and the worktree and checkpoint directories were left in place. The Holdout marker and `docs/research/experiments/research-run-1/` are untouched.

Cause as printed, not decided: `src/core/planner.py` computes `tp2 = entry_ref -/+ 2 * tp1_leg`; a negative short `tp2` means the planned take-profit leg exceeds half of the entry price on a very low-priced symbol. The engine fails closed on it. Likely, not verified: the 2.1.0 run never produced this trade plan because indicators were cold for the first ~800 hours of each window; the 50-day warm-up lets signals through earlier. Whether the planner should refuse such a plan (a NO_TRADE reason) or the engine should skip the signal is a change of simulator or planner semantics: that is a decision for the owner and, under REV-05, a new simulator version and new authorizations, not a fix inside this authorization.

## Gate with PostgreSQL (evidence/16-61-gate-with-postgres.txt)

Docker Desktop was restarted by the owner; `trading-postgres-1` (postgres:17.11-bookworm) is healthy and the connection was checked. On HEAD dce3195 with `TEST_DATABASE_URL` set: `pytest -m "not docker" -rs` exit 0, 10229 passed, 6 skipped (platform skips as before), 0 failed, 0 errors, counted from the progress lines because `addopts = "-q"` plus `-q` suppresses the summary line (10229 = 9742 + the 487 PostgreSQL tests); `ruff check` exit 0; `ruff format --check` exit 0 (626 files); `mypy src` exit 0 (202 files); `uv lock --check` exit 0. This closes the earlier gap that the 487 PostgreSQL tests had not run on the merged tree. It is not the plan's post-rerun `16-61-gate.txt`, which does not exist.

## Pending

1. **Owner decision on the trend-pullback failure** (the cause above). No further rerun attempt is made until it is decided. Nothing was run for breakout-retest and range-mr.
2. **Task 3 (finish) and Task 4** remain open: after the decision, the rerun (probably under a new simulator version and fresh authorizations, REV-05), then `16-DEC-RUN1-SUPERSEDED.md`, the note appended to `16-46-run1-feasibility-table.md` (its committed blob is LF while the working copy is CRLF; the plan's prefix check needs the file rebuilt from the blob bytes plus the note) and `16-61-gate.txt`.
3. The worktree `C:\Users\daotu\trading-rerun-v220` and `C:\Users\daotu\rerun-v220-ck\` can be kept for diagnosis or removed. `BKTS-03` was not marked complete.

## Gate numbers without PostgreSQL (evidence/16-61-gate-before-rerun.txt, commit 1b28ec9)

`pytest -m "not docker" -rs`, TEST_DATABASE_URL unset: exit 0, 9742 passed, 493 skipped (487 PostgreSQL, 6 platform skips as in the 16-60 gate), 28 deselected, 0 failed, 15m26s. `ruff check` exit 0; `ruff format --check` exit 0 (626 files); `mypy src` exit 0 (202 files); `uv lock --check` exit 0.

The first full run, on commit d5bdef2 with `TEST_DATABASE_URL` set and no PostgreSQL server: 4 failed, 9742 passed, 6 skipped, 483 errors (30m50s). 483 errors and 3 failures are the PostgreSQL connection timeout; the fourth failure was a real one found by the new duplicate rule and fixed in 1b28ec9.

## Deviations from Plan

**1. [Rule 3 - Blocking] Existing tests had to follow the new rules.** Found during Task 1. The new `constraint_source` rule and the sixth key broke tests that built a manifest with an absolute tmp constraint path, `repo_root=REPO_ROOT`, or the five-key authorization. Fixed in tests/test_research_runner.py, test_research_checkpoint.py, test_research_manifest_build.py, test_research_warmup.py, test_research_feasibility.py, test_research_report.py, test_research_terminal_settlement_integration.py and test_research_terminal_settlement_manifest.py (the plan lists only the first three and the hardening file). In test_research_checkpoint.py the two-point grid now uses the first two points of the committed trend-pullback grid, because baseline-v5 and baseline-v6 share every varied key value. Commit d5067a3.

**2. [Rule 1 - Bug] tests/test_research_register.py helper wrote the same varied value for every point.** Found by the full gate; the new duplicate rule refused the grid. The helper now uses a distinct value per point. Test-only. Commit 1b28ec9.

**3. [Rule 2 - Missing] Public `trades_digest_of_output`.** The plan says to use the existing `trades_digest`; it takes typed `TradeRecord`s while the engine output holds dicts, so a one-line public wrapper over the existing `_trade_from_dict` and `trades_digest` was added (same format as `reproduce`). Commit d5067a3.

**4. [Rule 2 - Missing] The key-sequence rule.** The plan allows it only if all three committed grids satisfy it; they do (checked before adding it), so it was added. Commit d5067a3.

**5. Task 2 step (4) was done by the owner, not by the agent.** The agent's earlier write was denied by the permission system; the owner then ran their own script and told the agent to verify. The agent verified and committed the files without editing them.

**6. Two extra gate evidence files.** `evidence/16-61-gate-before-rerun.txt` (no PostgreSQL) and `evidence/16-61-gate-with-postgres.txt` are additions to the plan's file list; the plan's `16-61-gate.txt` is the post-rerun gate and does not exist.

**7. Task 3 stopped on a family failure; Task 4 not started.** Per the owner rule and the plan (a failed family stops the rerun and is reported, never retried blindly). Not a Rule 1-3 fix: the cause is a simulator/planner semantics question (Rule 4), not fixed here.

**8. STATE.md `completed_plans` checked, not changed.** 231 plans, 228 with a SUMMARY file (3 without: 16-43, 16-44, 18-25); 16-61 is partial, so 227 completed. The value 227 written by the earlier record-session is correct.

## Known Stubs

None.

## Threat Flags

None. The new code paths only read files under the repository root the code was imported from (T-16-167, T-16-168 mitigated); no new network, auth or schema surface.

## Self-Check: PASSED

- Files exist: `tests/test_research_runner_hardening.py`, `evidence/16-61-hashes.txt`, `evidence/16-61-gate-before-rerun.txt`, this summary.
- Commits exist: `d5067a3` (Task 1), `d5bdef2` (Task 2 evidence), `1b28ec9` (register test fix).
- Files exist and are committed: the three authorization files and `16-DEC-RERUN-AUTH.md` (dce3195, owner-written), `evidence/16-61-run-output.txt`, `evidence/16-61-gate-with-postgres.txt`.
- Not produced (rerun stopped): the 240 records, `16-61-feasibility-table.md`, `16-DEC-RUN1-SUPERSEDED.md`, the appended note, `16-61-gate.txt`. Self-check of the plan as a whole: NOT COMPLETE, by design.
