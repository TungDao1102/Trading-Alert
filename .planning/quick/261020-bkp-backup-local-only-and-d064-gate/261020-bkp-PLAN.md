---
quick_id: 261020-bkp
date: 2026-10-20
type: quick
autonomous: true
files_modified:
  - deploy/backup.sh
  - deploy/backup-real-s3-gate.sh
  - src/ops/backup.py
  - src/ops/backup_remote.py
  - src/ops/backup_gate.py
  - tests/test_deploy_backup_scripts.py
  - tests/test_backup_remote.py
  - tests/test_backup_gate.py
  - tests/test_deploy_docs.py
  - docs/operations/RUNBOOK.md
  - deploy/soak.env.example
  - .env.example
  - .planning/phases/16-paper-runtime-composition/16-43-PLAN.md
  - .planning/phases/16-paper-runtime-composition/16-43-CHECKLIST.md
  - .planning/STATE.md
---

# 261020-bkp: backup local-only mode, D064 real-S3 gate procedure, 16-43 checklist fixes

## Authority
Owner decisions typed in chat on 2026-10-20: (1) the D064 real-S3 gate runs on the soak host at deploy time with the owner's real S3 and must not block work here; (2) with no S3 configured the backup must not FAIL when the owner explicitly asks for local-only, but a silently skipped off-host copy is not acceptable (a later Azure backend is a future task, not built here); (3) the soak pin requires a real-remote backup plus a passing restore drill, local-only is never enough; (4) Q-F confirmed: the owner commits `evidence/paper/pinned_epoch.json` to master after the pin, the O-01 alternative is dropped; (5) IMAGE_COMMIT 9b27da5 of `evidence/16-65-gate.txt` is superseded by the owner's fresh full gate after the Phase 19 merge.

## Constraints
- Default behaviour unchanged: a missing `BACKUP_S3_*` still fails closed. No network, no real remote: S3 double and fake runners only. One heavy process at a time, never the full suite, no xdist. No secret value anywhere. `docs/DECISIONS.md` is not edited. Line endings of every file are kept. Nothing is pushed.

## A - two review findings in deploy/backup.sh (tests first)
- A1: `require_root_and_plain_checkout` rejects a checkout path that the unit substitution cannot carry: the character set of `--soak-env-file` (letters, digits, `. _ / + = , ~ -` after the root or drive prefix; no `%`, no `&`, no whitespace).
- A2: `env_value` treats a bare-key line of the requested name (no `=`) as "cannot be determined" (rc 2): Compose takes such a value from the process environment.

## B - explicit local-only mode
- Opt-in: `BACKUP_REMOTE=none` in the env file the backup container reads (the systemd units then need no change). Empty or `s3` is the default S3 path; any other value fails closed.
- `scheduled` and `drill-remote` run locally (bundle, verification, scratch restore drill) without any rclone call, print a multi-line `OFF-HOST COPY SKIPPED` warning on stderr and the marker line `OFFSITE_COPY=skipped` on stdout; the remote path prints `OFFSITE_COPY=verified`. `push` (also `--init-remote`), `pull` and `retain` refuse in local-only mode.
- `deploy/backup.sh --init-remote` refuses (exit 2) before any docker call when the env file says `none`; `--install-soak-timer` accepts an empty soak bucket in local-only mode, still refuses a bucket equal to the trading bucket when one is set, and prints the warning.
- Docs: `--help`, RUNBOOK 11 and 20.5, `deploy/soak.env.example`, `.env.example`; 20.5 and the checklist state that the pin needs a real-remote backup and drill (marker not `skipped`).

## C - D064 real-S3 gate as a re-runnable procedure
- `python -m src.ops.backup real-s3-gate` (logic, `src/ops/backup_gate.py`) and the wrapper `deploy/backup-real-s3-gate.sh`: dry run by default, `--execute` required, a throwaway unique prefix under the configured bucket (refused unless it has the gate shape and is empty), the remote built by the same `rclone_env` code path, cleanup in every exit path, an evidence text file with one PASS/FAIL line per claim, exit 1 on any FAIL, exit 2 on a usage or configuration error.
- Claims from D064/D066 and RUNBOOK 11: manifest SHA-256 skip of unchanged files, refusal of a changed file (same and different size), upload of a new path only, orphan adoption and refusal, cryptcheck detection of a remote object modified (through crypt and at the provider) or deleted after upload, an upload followed by a failed check leaves the snapshot incomplete, a manifest that fails its check is removed, pull round trip, multipart objects through the crypt layer (12 MiB with a 5 MiB cutoff and chunk), cleanup.
- Tests with fakes only; RUNBOOK 11 "Real-S3 gate" says how to run it and that the real-S3 result stays pending until the owner runs it; the checklist runs it before the first real soak backup.

## D - 16-43 plan and checklist fixes (open points 1-7 and section 0)
- Exact commands: start command (RUNBOOK 20.1 form), soak backup-now command checked against `backup.sh --help` and the code, clean-state queries from `src/db/models.py` and the migrations through a read-only psql in the compose `postgres` service, heartbeat `--soak-env-file`, copying `pinned_epoch.json` out of the logs volume and reading the configuration identity, the CLEAN line of a schedule run, RUNBOOK 20.8 and 20.9 numbers. Section 0 gains the host-commit rule, the IMAGE_COMMIT supersession and the pin rule.

## Checks
Targeted tests, every `tests/test_deploy_*.py`, `tests/test_backup*.py` and the tests that read the RUNBOOK or 16-43, one file at a time; `ruff check`, `ruff format --check`, `mypy src`, `scripts/verify_decision_alignment.py all`.
