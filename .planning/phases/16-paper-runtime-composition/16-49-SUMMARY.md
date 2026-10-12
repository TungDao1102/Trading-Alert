---
phase: 16-paper-runtime-composition
plan: 49
subsystem: durable evidence destination (O-01 option a, S3, versioning, no Object Lock)
tags: [evidence, s3, preflight, publish, paper-01]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-47 (exporter --publish, EVIDENCE_S3_* names, src/ops/evidence_remote.py, deploy/evidence.env.example); plan 16-30 (O-01, Q-F records)"
provides:
  - "evidence/16-49-preflight.txt: the recorded configuration, the statement that no irreversible setting is recorded, and the publish test result"
affects: [16-43 (trial soak cannot start without a configured durable location)]

requirements-completed: []

status: tracer done, Tasks 2 and 3 pending user
actuals:
  tokens: 1400
  tasks: 1
  commits: 1
plan_head_before: 01bc1a622e9afc0a17c92351a0fb5585e640b97f
plan_head_after: f2fcf74a8ffc5c7e3b706dbc6f1a3bee5770f4ea
commits: 1

key-files:
  created:
    - .planning/phases/16-paper-runtime-composition/evidence/16-49-preflight.txt
  modified: []

key-decisions:
  - "None. The executor chose no value: every configuration line is copied from decisions/16-DEC-O-01.md."

duration: ~15 min
completed: 2026-10-12
---

# Phase 16 Plan 49: Evidence destination preflight (Task 1 only) Summary

**Task 1 (tracer) is done: the read-only preflight records O-01 option a (S3 prefix outside the backup crypt remote, versioning enabled, Object Lock none, retention none, reader project owner only, hourly exporter schedule), states that no irreversible Object Lock setting is recorded, and the publish tests pass against the injected uploader. Task 2 (user decision on the destination setting) and Task 3 (user configures the real bucket and proves the publish path) are NOT done and wait for the user.**

## What Task 1 produced

- `evidence/16-49-preflight.txt` (commit f2fcf74): recorded option and values verbatim, the Q-F link (commit-pinned-state, so no GitHub secret is needed for the evidence store), the irreversible-setting statement, the exact configuration to apply, the test result, and an offline fail-closed check.
- Irreversible setting recorded: **no**. `object_lock_mode: none` and `retention: none` are explicit lines, so the only allowed configuration is versioning enabled, Object Lock not enabled, no retention.
- Offline check: `scripts/export_soak_evidence.py publish --bundle <fake fixture bundle>` with no `EVIDENCE_S3_*` set exits 2 and names the seven missing variables (names only). No network was reached.

## Verification

- `uv run --frozen --extra dev pytest tests/test_soak_evidence_export.py tests/test_evidence_remote.py -q -p no:cacheprovider`: `test_soak_evidence_export.py` 45 passed, 1 skipped (the PostgreSQL export test, `TEST_DATABASE_URL` not set); `test_evidence_remote.py` passed. The plan names `.venv/Scripts/python -m pytest`; the venv was empty in this worktree, so `uv sync --frozen --extra dev` was run first (packages from the lockfile) and pytest was run through `uv run`.
- `uv run mypy src`: no issues in 183 files. `ruff check`: all checks passed. `ruff format --check`: 526 files already formatted.
- The whole test suite was not run (memory instruction).

## Deviations from Plan

None - Task 1 executed as written (the interpreter path differs only because `uv run` was used in a fresh worktree).

## Where the plan changes because of the records

- Q-F is `commit-pinned-state`, so Task 3 step 3 "GitHub runner path with its read-only secret" does not apply. The recorded reader is the project owner only: the reader read test is the owner reading the manifest back with their own identity (command below).
- Task 2 (blocking-human, never auto-selected) still has to be answered by the user before Task 3, even though no Object Lock is recorded; the preflight shows that `apply-as-recorded` and `apply-without-object-lock` describe the same configuration for this record, so the real choices are `apply-as-recorded` and `postpone`.

## What the user must decide (Task 2)

Reply with one of: `apply-as-recorded`, `apply-without-object-lock` (identical result here) or `postpone` (the trial soak cannot start, plan 16-43). Then the orchestrator writes `decisions/16-DEC-O-01-apply.md` with the reply verbatim.

## What the user must configure (Task 3 checklist)

Do these on the connected machine, in this order, and stop at any surprise.

1. Bucket: create a bucket dedicated to evidence (preferred), or a prefix in a bucket that is NOT the backup bucket (RUNBOOK 19.6 items 4 and 5).
2. Versioning: enable it. Object Lock: **leave unchecked** at creation (it can never be removed once on). Default retention: none. Lifecycle rules that delete versions: none.
3. Access policy: project owner only. Create a credential of its own for the exporter, scoped to this bucket and prefix (put, get, list). It must not equal the `BACKUP_S3_*` credential (the exporter refuses to run if equal). Block public access on.
4. Host environment file, outside the checkout, mode 0600, made from `deploy/evidence.env.example`: `EVIDENCE_S3_PROVIDER` (AWS, Wasabi or Other), `EVIDENCE_S3_ENDPOINT` (only for Other), `EVIDENCE_S3_REGION`, `EVIDENCE_S3_BUCKET`, `EVIDENCE_S3_PREFIX` (required, not empty), `EVIDENCE_S3_ACCESS_KEY_ID`, `EVIDENCE_S3_SECRET_ACCESS_KEY`. Do not put them in the shared soak env file. Load it only into the shell that runs the exporter.
5. For the first proof use a throwaway prefix (for example `EVIDENCE_S3_PREFIX=selftest`), because the bucket is versioned: a fake epoch cannot be removed permanently, only hidden by a delete marker. Switch to the real prefix afterwards.

## Commands to prove the publish path (all run by the user; none were run by the executor)

Build a FAKE fixture bundle (epoch `aaaa...aaaa`, source "fixture", never soak evidence). Run from the repository root, where the dev dependencies are installed (`uv sync --frozen --extra dev`). This script was run by the executor in a scratch directory and produced a loadable bundle (exit 0):

```text
# fake_bundle.py (not committed; keep it outside the repository)
import sys
from datetime import timedelta
from pathlib import Path
from scripts import export_soak_evidence as export
from tests.test_soak_evidence_export import E1, P1, one_epoch_inputs

root = Path(sys.argv[1])
inputs = one_epoch_inputs(root / "in")
argv = inputs.argv(source="fixture", epoch=E1, start=P1, end=P1 + timedelta(hours=6), out=root / "bundle")
sys.exit(export.main(argv))
```

```bash
PYTHONPATH=. uv run --frozen --extra dev python /path/outside/repo/fake_bundle.py /tmp/fake-evidence
# expected: "bundle written: bundle (source fixture, 11 runtime record(s), 0 evidence gap(s))"

set -a; . /path/outside/checkout/evidence.env; set +a
python scripts/export_soak_evidence.py publish --bundle /tmp/fake-evidence/bundle
# expected: "published and verified", exit 0. Exit 2 = configuration (names only are printed),
# exit 4 = a read-back mismatch (names the file; the local bundle is kept).
```

Reader read test (owner identity, plaintext, no passphrase), using the owner's own AWS identity:

```bash
aws s3 cp s3://<bucket>/<prefix>/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json -
# expected: readable JSON with "schema": "soak-evidence-bundle/1" and the file hashes
aws s3api get-bucket-versioning --bucket <bucket>
# expected: "Status": "Enabled"
aws s3api get-object-lock-configuration --bucket <bucket>
# expected: an error ObjectLockConfigurationNotFoundError (Object Lock not enabled)
```

Then tell the orchestrator "destination configured" with, for the record: destination (bucket and prefix, no key), versioning result, Object Lock result, retention (none), the names of the `EVIDENCE_S3_*` variables (never values), the test publish output, and the reader read result. The executor of the continuation writes `evidence/16-49-destination.md` with the seven headings from that report.

## Known Stubs

None.

## Threat Flags

None. No AWS call, no credential read, written or printed (T-16-107, T-16-108).

## NOT RUN / still pending

- Task 2 (the user's decision) and Task 3 (the user's configuration and proof): `decisions/16-DEC-O-01-apply.md` and `evidence/16-49-destination.md` do not exist.
- Anything against a real bucket or the real rclone; the reader read test; the PostgreSQL export test (`TEST_DATABASE_URL`).
- STATE.md and ROADMAP.md were not edited (orchestrator's step); requirement PAPER-01 is not marked complete by this plan yet.

## Self-Check: PASSED

- File exists: `.planning/phases/16-paper-runtime-composition/evidence/16-49-preflight.txt`.
- Commit exists: f2fcf74.
