---
phase: quick-261007-mv4
plan: 01
status: incomplete
outcome: STOPPED at Task 1 (proof failed on a PRODUCT label)
reason: "rclone 1.75.1 on the crypt remote ignores --checksum and falls back to --size-only; a same-size changed file is skipped silently with exit 0"
commits: 0
plan_head_before: 348b350
plan_head_after: 348b350
---

# Quick 261007-mv4: CR-01 Parquet push `--checksum` - STOPPED, proof failed

No code commit, no change to `src/`, tests or docs. The tree is byte-identical to HEAD apart from the two
pre-existing modified planning files (`.planning/config.json`, `.planning/state.json`) and the untracked
`.gsd/` and `.planning/quick/...`. Nothing was pushed. No alternative was chosen.

## Failing PRODUCT labels (arm `checksum`, flags `--immutable --checksum`)

| Label | Expected | Actual | Transcript |
|-------|----------|--------|------------|
| PRODUCT [checksum] step X (same size, different bytes, original mtime) | return code != 0, `immutable` in an ERROR line | return code 0, no ERROR line, "Unchanged skipping" | proof-output lines 331-355 |
| PRODUCT [checksum] step X-PLAIN (same push, no `-vv`, as the adapter sends it) | return code != 0 | return code 0 | lines 356-361 |
| PRODUCT [checksum] step Y (same size, different bytes, new mtime) | return code != 0, `immutable` in an ERROR line | return code 0, "Unchanged skipping" | lines 362-386 |

The remote bytes stayed the original ones in every step, because the changed file was never uploaded, not because
it was rejected. The flag did not do what D062 item 2 expects on this remote.

What the flag did on this crypt remote, from rclone's own NOTICE line (printed on every checksum-arm push at
default log level, so it also appears in the plain-mode record):

```
NOTICE: Encrypted drive 'BACKUPS3CRYPT{z1Wlo}:parquet': --checksum is in use but the source and destination have no hashes in common; falling back to --size-only
```

So `--checksum` on a crypt remote with a local source is `--size-only`: the exact defect D062 wants removed. The
pinned binary's own help says the same: `-c, --checksum  Check for changes with size & checksum (if available, or fallback to size only)`.

PRODUCT labels that held (checksum arm): N (new files upload, "Copied"), U (mtime-only change: rc 0, no "Copied",
server objects identical), Z (new file uploads, exactly one new object, earlier objects unchanged).

## Harness calibration (no HARNESS violation; the experiment can see the defect)

| Arm | N new files | U mtime only | Z new file | X same size, orig mtime | Y same size, new mtime |
|-----|-------------|--------------|------------|-------------------------|------------------------|
| immutable-only | rc 0, Copied | rc 6 (immutable file modified, both files) | rc 0, Copied | rc 0, no Copied | rc 6 (immutable file modified) |
| size-only | rc 0, Copied | rc 0, no Copied | rc 0, Copied | rc 0, no Copied (silent skip) | rc 0, no Copied (silent skip) |
| checksum | rc 0, Copied | rc 0, no Copied, objects unchanged | rc 0, Copied, +1 object | rc 0, no Copied | rc 0, no Copied |
| checksum, plain (no -vv) | - | - | - | X-PLAIN: rc 0 | - |

The control arms behaved as the plan expected: immutable-only fails a restored file (the original CR-01 defect),
size-only skips a same-size changed file silently. The checksum arm is indistinguishable from size-only. Note
also: even plain `--immutable` (no size flag) skipped a same-size changed file with the SAME mtime (step X,
immutable-only, rc 0) - the default comparison is size plus mtime.

Each step also checked that the remote file `raw/a.parquet` still held its original bytes: it did in all arms.

## rclone output of proof (1), arm `checksum` (verbatim)

Step X, `-vv` (last 1500 characters as recorded, rc 0):

```
d230/gkp6ue11kvmip94ad74vdtmflg" for canonical name "BACKUPS3{3zSdM}:bkt-628dd230/gkp6ue11kvmip94ad74vdtmflg"
2026/10/07 10:09:25 DEBUG : fs cache: renaming cache item "BACKUPS3CRYPT:parquet" to be canonical "BACKUPS3CRYPT{z1Wlo}:parquet"
2026/10/07 10:09:25 DEBUG : raw/c.parquet: size = 1200 OK
2026/10/07 10:09:25 NOTICE: Encrypted drive 'BACKUPS3CRYPT{z1Wlo}:parquet': --checksum is in use but the source and destination have no hashes in common; falling back to --size-only
2026/10/07 10:09:25 DEBUG : raw/c.parquet: Size of src and dst objects identical
2026/10/07 10:09:25 DEBUG : raw/c.parquet: Unchanged skipping
2026/10/07 10:09:25 DEBUG : raw/a.parquet: size = 1200 OK
2026/10/07 10:09:25 DEBUG : raw/a.parquet: Size of src and dst objects identical
2026/10/07 10:09:25 DEBUG : raw/a.parquet: Unchanged skipping
2026/10/07 10:09:25 DEBUG : raw/b.parquet: size = 1200 OK
2026/10/07 10:09:25 DEBUG : raw/b.parquet: Size of src and dst objects identical
2026/10/07 10:09:25 DEBUG : raw/b.parquet: Unchanged skipping
2026/10/07 10:09:25 DEBUG : Encrypted drive 'BACKUPS3CRYPT{z1Wlo}:parquet': Waiting for checks to finish
2026/10/07 10:09:25 DEBUG : Encrypted drive 'BACKUPS3CRYPT{z1Wlo}:parquet': Waiting for transfers to finish
2026/10/07 10:09:25 INFO  : There was nothing to transfer
2026/10/07 10:09:25 INFO  : 
Transferred:   	          0 B / 0 B, -, 0 B/s, ETA -
Checks:                 3 / 3, 100%, Listed 8
Elapsed time:         0.0s

2026/10/07 10:09:25 DEBUG : 5 go routines active
```

Step X-PLAIN (plain mode, the adapter's argv, rc 0):

```
2026/10/07 10:09:27 NOTICE: Config file "/config/rclone/rclone.conf" not found - using defaults
2026/10/07 10:09:27 NOTICE: Encrypted drive 'BACKUPS3CRYPT{z1Wlo}:parquet': --checksum is in use but the source and destination have no hashes in common; falling back to --size-only
```

Step Y, `-vv` (rc 0): same shape as step X, with `raw/a.parquet: Size of src and dst objects identical` /
`Unchanged skipping`, "There was nothing to transfer", `Checks: 3 / 3, 100%`. The full transcript of all three arms is in
`261007-mv4-proof-output.txt` in this directory (untracked).

Control for comparison, arm `immutable-only`, step U (rc 6): `ERROR : raw/a.parquet: Source and destination exist but do not match: immutable file modified`,
`NOTICE: Failed to copy with 2 errors: last error was: immutable file modified`.

## Help text from the pinned binary (rclone v1.75.1, alpine 3.24.1, go1.27.1; `docker run --rm $IMG help flags <name>`)

```
-c, --checksum          Check for changes with size & checksum (if available, or fallback to size only)
    --ignore-size       Ignore size when skipping use modtime or checksum
    --size-only         Skip based on size only, not modtime or checksum
    --immutable         Do not modify files, fail if existing files have been modified
```

`docker run --rm $IMG help backend crypt` lists only crypt options (remote, filename encryption, passwords); it
has no statement about hashes, so the crypt/hash statement rests on the rclone NOTICE line above (a real run) and on
https://rclone.org/crypt/ ("Hashes are not stored for crypt"; current release, not necessarily the pin).

## Alternatives for the user (none chosen, none proven; each needs its own real-rclone proof and plan)

- (A) Keep the current size comparison and add a read-only `rclone cryptcheck` of the Parquet tree after the push
  (probably one-way so remote-only files are not differences). Not yet verified that cryptcheck detects a same-size
  change of an existing object on this remote; `push_snapshot` already runs cryptcheck for the snapshot directory.
- (B) Before pushing, compare the sha256 of every local Parquet path in the bundle manifest with the `manifest.json`
  of the newest complete remote snapshot (`list_complete_snapshots`) and refuse on a mismatch: pure Python, independent
  of rclone hash support, but only covers paths present in that snapshot.
- (C) Accept the current behaviour (as at the original CR-01 acceptance), relying on the sha256 check at restore time.
- (D) Content-addressed remote object names: a layout change touching push, pull and retention.

Fact the user should weigh: with the current `--immutable --size-only` AND with `--immutable --checksum` a same-size
changed Parquet file is skipped silently; the only way to make the push fail on it is something other than a flag
swap on this copy command.

## Files changed

None committed. Temporary proof block was appended to `tests/test_docker_backup_remote.py` and then reverted with
`git checkout -- tests/test_docker_backup_remote.py` (working copy is `i/lf w/crlf` again, `git diff` empty for it).
Untracked artifacts left in this directory (not staged): `261007-mv4-proof-output.txt`,
`261007-mv4-proof-block.diff` (the removed proof block, 153 lines), this SUMMARY.

## Commands run and results

- `git status --short`, `git ls-files --eol` on the six files: all `i/lf w/crlf`; no uncommitted change to any of the six files (precondition met).
- `docker info`: server 29.5.3 reachable. The pinned image was already present locally (id equals the pinned digest); no pull was needed. `docker run --rm $IMG version`: `rclone v1.75.1`.
- `uv sync` was not run (per instruction: `uv run --frozen --offline`).
- `docker run --rm $IMG help flags checksum|immutable|size-only` and `help backend crypt`: output quoted above.
- Proof block appended by a Python script (CRLF preserved), `ruff check` and `ruff format --diff` clean on it.
- `PYTHONPATH=. TRADING_CI_STRICT=1 uv run --frozen --offline pytest tests/test_docker_backup_remote.py -m docker -k cr01_proof -s -rA -p no:cacheprovider`: 2 passed (`immutable-only`, `size-only`), 1 failed (`checksum`, 5 PRODUCT expectations, 0 HARNESS), 3 deselected, 0 skipped, 49.87 s.
- Revert, `git status --short` after: only `.planning/config.json`, `.planning/state.json` modified; `.gsd/` and the quick directory untracked.
- Tasks 2 and 3 were not started; no ruff, mypy or other test run beyond the above.

## Surprises

- The fallback is announced by rclone itself at NOTICE level, so it is visible even in the adapter's plain-mode output: the adapter would have reported success with that line in stderr.
- Plain `--immutable` also skips a same-size changed file when the mtime is unchanged (control arm step X).
- The planning-time docs reading ("`--checksum` compares hash and size") was true only when both sides have a common hash; the real run shows size-only fallback on crypt.

## What could not be verified

- Behaviour against a real S3 provider (only the `rclone serve s3` double was used). The fallback is decided by the crypt wrapper's lack of hashes, which does not depend on the provider, but this was not tested elsewhere.
- Whether `rclone cryptcheck` (alternative A) detects a same-size changed existing object: not run.
- Push time at production dataset size against the systemd `TimeoutStartSec=2h`: moot since no hashing happens.

## Left alone on purpose and now needing a user decision

`docs/DECISIONS.md` D062 item 2 (it assumes `--checksum` works on this remote), `.planning/ROADMAP.md` lines 533 and 740 (list CR-01 as open),
`13.1-OPEN-DECISIONS.md` (CR-01 stays open), RUNBOOK section 11 and DOC_STATUS (unchanged).
