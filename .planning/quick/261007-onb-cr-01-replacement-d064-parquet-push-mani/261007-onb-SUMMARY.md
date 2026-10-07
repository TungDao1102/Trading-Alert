---
phase: quick-261007-onb
plan: 01
status: complete-on-double
outcome: Tasks 1-3 done; Task 4 (real S3) NOT run, D064 acceptance gate still open
commits: 2 (6ce7aac implementation, e9a030c review fixes)
---

# Quick 261007-onb: CR-01 replacement (D064) - Parquet push by manifest SHA-256 plus cryptcheck

Implemented and tested against the pinned rclone 1.75.1 and an S3 double only. D064 accepts B+A only after
Task 4 (real S3 on a throwaway bucket); that has NOT been done. Nothing was pushed.

## Proof (Task 1, `261007-onb-proof-output.txt`, PROOF-OUTCOME: PASS)
`rclone cryptcheck --one-way` on a crypt remote detects: same-size changed file (original and new mtime),
remote object rewritten out of band, remote object deleted; passes identical content and mtime-only change.
Controls: `--size-only` is blind to the same change. One harness fix (server restart after out-of-band delete).
Cost on the double (not real S3): whole-tree cryptcheck 1.6 s / 2.6 s / 7.6 s for 250 / 1000 / 4000 files.

## Code
- 6ce7aac: manifest-hash decision (skip / refuse / upload / adopt-if-identical), tree + pg.dump cryptcheck before
  the manifest, compensating `deletefile`, RUNBOOK 11 and 11.8, OPEN-DECISIONS CR-01 row, DOC_STATUS line.
- e9a030c: review fixes WR-01 (interrupt note), WR-02 (lsf tolerates rc 3 only), WR-03 (re-verify bundle before
  publishing the manifest), WR-04 (mutant-killing tests), WR-05 (tree check before the pg.dump upload), IN-04.

## Review (`261007-onb-REVIEW.md`): 0 CR, 7 WR, 4 IN
Fixed: WR-01..05, IN-04. Left open on purpose:
- WR-06: a damaged remote Parquet object blocks publication of every PostgreSQL snapshot; no recovery steps for
  an unreadable manifest or a lost known object. USER DECISION (decouple or not).
- WR-07: cryptcheck trusted by exit code only (no matching-count check); belongs to the real-S3 proof.
- IN-01, IN-02, IN-03 (SIGTERM does not trigger the compensating delete; covered by window W1).

## Not verified
Real S3 (multipart objects, ETag/checksum metadata, latency, request cost); time at production scale versus
`TimeoutStartSec=2h` and the 6 h per-call rclone timeout (mismatch flagged, unchanged); two concurrent writers
(unsupported); `tests/test_docker_backup_drill.py` (image trading-alert-ops:dev absent locally).
