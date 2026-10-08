---
phase: quick-261007-onb
reviewed: 2026-10-07T00:00:00Z
depth: deep
files_reviewed: 6
files_reviewed_list:
  - src/ops/backup_remote.py
  - tests/test_backup_remote.py
  - tests/test_docker_backup_remote.py
  - docs/operations/RUNBOOK.md
  - docs/DOC_STATUS.md
  - .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md
findings:
  critical: 0
  warning: 7
  info: 4
  total: 11
status: issues_found
---

# Quick 261007-onb: Code Review Report (commit 6ce7aac)

**Reviewed:** 2026-10-07
**Depth:** deep
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the D064 push logic against D064, the SPEC and the proof transcript (rclone 1.75.1 argv, exit
codes, `ERROR : <path>:` line shape). Line numbers are working-copy lines of the commit.

What holds (verified, not assumed):

- Content identity is decided only by the manifest SHA-256: no `--size-only`, `--checksum`, mtime or size
  reaches a decision (`classify_parquet_paths`, lines 405-425). A known path with a different hash, or two
  disagreeing manifests, becomes a conflict and `_stage_parquet` raises before any `copy` or `copyto`
  (lines 476-480). Mutation check: dropping the conflict gate, forcing "skip", dropping the disagree branch,
  forcing "adopt always" and removing the line-break guard are all killed by the existing tests.
- `manifest.json` is only copied after `_check_parquet_tree` and the `pg.dump` cryptcheck (lines 557-563).
  Mutation check: deleting the tree check is killed (test case F).
- Every argv used matches a proven form in 261007-onb-proof-output.txt: `lsf -R --files-only crypt:parquet/`
  (L1, rc 3 for a missing directory, l2), whole tree `cryptcheck <local> crypt:parquet --one-way` (final),
  adopt form `--one-way --files-from-raw` (F1, s1/s2), `copy --files-from-raw --immutable` (u1/u2),
  `deletefile` rc 4 for an absent object (m4).
- `uv run ruff check`, `ruff format --check`, `mypy src/ops/backup_remote.py` and
  `tests/test_backup_remote.py` (non-docker) all pass. RUNBOOK message heads equal the code strings
  (lines 312-317, 569-575, 368, 548), the cost table equals the proof COST table and carries "double, not
  real S3".

No critical (CR) defect was proven. The findings below are WARNINGs on silent failure paths, an
exit-code tolerance wider than the spec allows, tests that do not pin tolerated branches, a design
coupling the user should decide on, and documentation gaps on operator recovery.

## Critical Issues

None.

## Warnings

### WR-01: A KeyboardInterrupt during manifest publication drops the "could not remove" signal

**File:** `src/ops/backup_remote.py:564-568`
**Evidence:**
```python
except (RemoteError, KeyboardInterrupt) as exc:
    removed = _remove_manifest(runner, manifest_remote)
    if isinstance(exc, KeyboardInterrupt):
        raise
```
`removed` is computed and then ignored for the interrupt case.
**Scenario:** operator (or a wrapper) sends SIGINT while the manifest is being checked (this is the
`test_case_i_an_interrupt_during_manifest_publication...` case). Both `deletefile` attempts fail (network
is the usual reason the operator interrupted). The process exits with a bare `KeyboardInterrupt`
traceback: the manifest object stays on the remote, the snapshot looks complete, its manifest was never
verified, and nothing names the object to remove by hand. This is exactly the W2 state, but without the W2
message RUNBOOK 11.8 tells the operator to look for. The only test of the interrupt path (line 1695 of the
tests) covers the case where the removal succeeds.
**Fix:**
```python
removed = _remove_manifest(runner, manifest_remote)
if isinstance(exc, KeyboardInterrupt):
    if not removed:
        print(
            f"manifest of snapshot {snap} could not be removed after an interrupt: remove "
            f"{SNAPSHOTS_DIR}/{snap}/{MANIFEST_NAME} through the crypt remote by hand and do not "
            "trust that snapshot until then",
            file=sys.stderr,
        )
    raise
```
Add a test: crash hook `KeyboardInterrupt` plus two forced `deletefile` failures, assert the stderr text.

### WR-02: lsf exit code 4 is still tolerated on the push-critical listings (spec allows only lsf 3 and deletefile 4)

**File:** `src/ops/backup_remote.py:86, 594, 611`
**Evidence:** `_EXIT_NOT_FOUND = frozenset({3, 4})` is still the `ok` set of `list_snapshots` and
`list_complete_snapshots`. The new, precise constants (`_EXIT_LSF_NOT_FOUND = 3`, line 320) are used only
by `remote_parquet_paths`. Reproduced: a runner returning `RcloneResult(4, "", "x")` makes
`list_complete_snapshots` return `[]` without raising.
**Scenario:** any spurious rc 4 from `lsf snapshots/` (rclone documents 4 as "file not found", which lsf of
a directory never legitimately returns, per proof l2 only rc 3 occurs) silently yields "no complete
snapshots". In `push_snapshot` that empties the known set (a previously published path with different
content is then classified `adopt` and refused with the wrong head, HEAD_PARQUET_ORPHAN) and disables the
`snap in complete` collision guard (line 547). Fail-closed for retention and pull, but it is the silent
shrinking of the known set that `known_parquet_hashes` explicitly refuses elsewhere.
**Fix:** use `ok=frozenset({0, _EXIT_LSF_NOT_FOUND})` in both listings; keep `{3, 4}` only where a `cat`
absence is meant (`init_sentinel`). Update the pre-existing tests that feed rc 4 to the listings.

### WR-03: The tree and `pg.dump` checks compare the current local bytes, not the manifest hash; the bundle is not re-verified before publishing

**File:** `src/ops/backup_remote.py:533-558`
**Evidence:** `verify_bundle` runs once at line 533. Uploads, the whole-tree cryptcheck (hours at scale; RUNBOOK
"Cost" gives no bound) and `pg.dump` cryptcheck follow. `cryptcheck` proves remote == local file now. The
manifest published at line 562 names the hashes read from `manifest.json` at line 541.
**Scenario:** a local Parquet file or `pg.dump` in the staging bundle is replaced after line 533 (any
process writing into `--bundle-root`; `cli_push` takes an arbitrary directory). The upload copies the new
bytes, cryptcheck passes (remote equals the modified local file), and a manifest is published that names the
old SHA-256. The snapshot looks complete and verified but its content does not match its manifest; it is
found only at pull time. That defeats the "identity is the manifest SHA-256" claim of D064.
**Fix:** immediately before `copyto manifest` call `problems = verify_bundle(bundle_root)` again and raise
`RemoteError` if non-empty (local hashing only, no network).

### WR-04: Tolerated and error branches are not pinned by any test (mutation survivors)

**File:** `tests/test_backup_remote.py` (cases F-I, `_ManifestRunner` block); source lines 489-499, 453-461, 512-514
**Evidence (mutations applied to a copy of the tree, `tests/test_backup_remote.py -m "not docker"`):**
- `_remove_manifest` with `ok=frozenset({0})` (rc 4 no longer tolerated): all tests pass. No test makes
  `deletefile` hit an absent object (the fake returns rc 4 for that, line 683 of the test file, but every
  manifest-failure test performs the upload first).
- Adopt cryptcheck: dropping the `returncode != 0` raise (rc 7, 2 etc. accepted as success) survives.
- `_check_parquet_tree`: accepting rc 7 as success survives.
- `known_parquet_hashes`/adopt `--one-way`: removal of `--one-way` from the adopt argv survives
  (behaviourally equivalent under `--files-from-raw`, so harmless, but the proof "e1" argv is not pinned).
**Scenario:** a regression that treats a fatal rclone exit (rc 7, 1x) as a pass on the verification that guards
the manifest, or that turns the common "upload failed before writing" case into a false "could not be
removed" alarm, ships green.
**Fix:** add (a) a manifest `copyto` forced to fail without writing, expect exactly one `deletefile` returning 4
and the "left incomplete" message; (b) forced `RcloneResult(7, ...)` for the adopt and the tree cryptcheck,
expect a `RemoteError` and no manifest; (c) a `_differing_paths` test with a path containing `": "` and
spaces (currently returns `[]`, falls back to naming every adopt path, tree check names nothing).

### WR-05: A failing verification uploads a full `pg.dump` first and, because retention is skipped, leaves a new incomplete snapshot per day

**File:** `src/ops/backup_remote.py:556-558, 868`
**Evidence:** `copyto pg.dump` (556) runs before `_check_parquet_tree` (558). `cli_scheduled` aborts on the raised
error, so `apply_retention` (868), the only code that purges stale incomplete directories, does not run.
**Scenario:** one known Parquet object is damaged on the remote (case G/H). Every nightly run uploads a
complete `pg.dump` into a new `snapshots/<id>/`, then fails at the tree check. Until an operator acts, the
bucket gains one full database dump per day that retention never removes (cost, and a growing list that every
`list_snapshots` and `lsf -R` walks).
**Fix:** run the whole-tree check before the `pg.dump` upload (still before the manifest, so D064 order holds),
and verify `pg.dump` right after its own copy. Update RUNBOOK 11.8 bullet "parquet verification failed" (it
states `pg.dump` of the new snapshot is on the remote).

### WR-06: RUNBOOK 11.8 gives no recovery for two states the design makes permanent, and the DB backup is coupled to Parquet health (user decision)

**Disposition (2026-10-08): item 3 decided, items 1 and 2 partly open.** Item 3 (the coupling): kept strict, recorded as D066, no code change. RUNBOOK 11.8 now states what exists on the remote, that a restore fails at pull before the database is touched, and that an older snapshot must be proven by `pull --snapshot ID` because the shared parquet tree can break several snapshots. Items 1 and 2 (how to resume pushing after an unreadable manifest of a complete snapshot, or a known Parquet object lost on the remote): RUNBOOK still says a manual action on the remote needs its own decision; no route is chosen. This stays user-owned (D066).

**File:** `docs/operations/RUNBOOK.md` section 11.8 and "Parquet push" paragraph; code `src/ops/backup_remote.py:384-386, 419-425, 558`
**Evidence:**
1. `unreadable manifest of complete snapshot <id>` is a hard failure for every later push (code 366-383). 11.8 says
   only "refuses rather than ignore it". Retention cannot fix it (the snapshot lists as complete and may be inside
   the 7/4/6 window) and the scheduled chain never reaches retention. Nothing tells the operator to remove or
   replace that manifest.
2. A path a complete snapshot names with the same hash whose remote object is missing or altered is classified
   `skip` and is never re-uploaded; the tree check then fails on every run (RUNBOOK says "the operator decides").
   There is no stated route to re-create the object (the push has no overwrite or repair option by design).
3. Because the tree check gates `manifest.json`, damage to one research Parquet object stops publication of
   every PostgreSQL snapshot (operational state: orders, fills, journal) until a manual remote action. With no
   external heartbeat (RUNBOOK 11.4 says none exists) the first symptom is the failed unit.
**Scenario:** one S3 object of the research tree is lost. For weeks no new complete snapshot is published; the
operator has no documented step to resume; the last good DB snapshot ages out of the 7/4/6 window only if retention
could run, which it cannot.
**Fix:** (a) document in 11.8 the minimal factual routes for 1 and 2 (for 1: remove or replace
`snapshots/<id>/manifest.json` through the crypt remote after confirming it against the pulled snapshot; for 2:
re-upload the object with `rclone copyto` through the crypt remote from a copy whose SHA-256 equals the manifest
value); (b) record the DB-vs-Parquet coupling and its recovery-point consequence as an explicit decision for the
user (publish a DB-only snapshot on tree-check failure, or keep fail-closed). No code change proposed here: this is
a money/safety choice that is the user's.

### WR-07: Verification trusts the cryptcheck exit code alone; the checked count is never compared

**File:** `src/ops/backup_remote.py:453-461, 489-499, 559, 563`
**Evidence:** all four cryptchecks accept `returncode == 0` and ignore the summary line the proof shows rclone
prints on success (`NOTICE: ... N matching files`, proof lines 483, 633). None checks that the number of
matched files equals the expected count (`len(local)`, `len(plan.adopt)`, 1).
**Scenario (unverified on real S3, which is the pending D064 gate):** an object that rclone cannot hash (a
multipart upload without stored MD5 on some providers; the RUNBOOK gate itself names multipart) is reported by
rclone as not hash-checkable while the exit code stays 0. The push then treats an unchecked object as verified and
publishes the manifest. The doubles produce no multipart objects, so no test could show it.
**Fix:** on rc 0 parse `(\d+) matching files` from stderr and fail with `HEAD_PARQUET_VERIFY` when it is missing or
differs from the expected count; also fail on any stderr line matching `could not be checked|no common hash|falling
back`. Pin it with the real-rclone test and fold the real-S3 run into the gate.

## Info

### IN-01: Compensating `deletefile` is unconditional and the id-collision guard is a point-in-time check

**File:** `src/ops/backup_remote.py:546-548, 564-566`
**Issue:** `snap in complete` is evaluated once, before an upload phase that can last hours. If a second writer
publishes the same-second id with an identical bundle (same `pg.dump` bytes and mtime pass `--immutable`; W4
declares this unsupported), and this process's own manifest check then fails transiently, `_remove_manifest`
deletes that other writer's valid, verified manifest. Different-content collisions cannot reach this code because
`copyto pg.dump --immutable` fails first (line 556, outside the `try`). Very low likelihood.
**Fix:** re-list immediately before `copyto manifest` (`snap not in list_complete_snapshots(runner)`) and only
delete when this process observed its own copy succeed or when the manifest was absent before it.

### IN-02: `splitlines()` on remote listings splits on characters rclone does not treat as separators

**File:** `src/ops/backup_remote.py:402`, `tests/test_backup_remote.py:573` (fake), `436-448`
**Issue:** `str.splitlines()` also splits on `\x0b \x0c \x1c-\x1e \x85 \u2028 \u2029`. A remote Parquet path with such a
character is cut into fragments, so it is never recognised as present (class `upload` instead of `adopt`;
`copy --immutable` then fails with rc 6 and the push stays blocked, fail-closed). `local_parquet_hashes` refuses only
`\n` and `\r`. Hive names make this academic. Also `_differing_paths` cuts the path at the first `": "`, so a path
containing a colon followed by a space is never named (verified: returns `[]`); the adopt branch then names every
adopt path, the tree check names none. Cosmetic.
**Fix:** `stdout.split("\n")` (strip a trailing `\r`), and either refuse these characters in `local_parquet_hashes`
or document them.

### IN-03: Only SIGINT triggers the compensation; SIGTERM and non-RemoteError exceptions bypass it

**File:** `src/ops/backup_remote.py:564`, `deploy/systemd/trading-backup.service:17`
**Issue:** `except (RemoteError, KeyboardInterrupt)` does not cover `SystemExit` or any other exception raised
between `copyto manifest` and the end of the check (`OSError` from a failing temp file, `MemoryError`), and Python
turns no signal other than SIGINT into an exception. The systemd unit's `TimeoutStartSec=2h` (and `docker stop`)
deliver SIGTERM, which kills the process with no cleanup: W1. The RUNBOOK documents W1 for "killed", so this is
awareness, not a mismatch. The whole-tree check grows with the dataset, so the 2 h timeout becomes a live kill point
before the manifest, not only inside W1.
**Fix:** `except BaseException` with a re-raise of non-`RemoteError`, and install a SIGTERM handler in the CLI entry
that raises `KeyboardInterrupt`; revisit `TimeoutStartSec` once real-S3 timings exist.

### IN-04: Documentation overstatements in RUNBOOK 11.8 and the 11.8 verification row

**File:** `docs/operations/RUNBOOK.md` (11.8 intro, matrix row 11.8)
**Issue:** "A rerun repeats the same refusal, because the push never overwrites a remote object" is true for the
refusal heads but false for `parquet verification failed` caused by a transient network error, `manifest
verification failed` and `snapshot id ... already exists` (a rerun a second later succeeds). The row says "every
message head is pinned by fake-runner tests": the heads `rclone cryptcheck failed (exit N)` (pg.dump check, adopt
with rc other than 1), `rclone lsf failed`, `rclone cat failed` appear in no 11.8 bullet, and the adopt rc-other-than-1
and tree rc-other-than-1 branches are not pinned (WR-04).
**Fix:** limit the "same refusal" sentence to the two `refused` heads, add the missing heads (or a line "any other
`rclone <verb> failed (exit N)` is a transport or verification error; rerun, then escalate"), and reword the row.

---

_Reviewed: 2026-10-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
