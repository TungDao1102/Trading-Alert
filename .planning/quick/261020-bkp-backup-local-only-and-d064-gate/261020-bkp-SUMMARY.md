# 261020-bkp SUMMARY

Owner decisions of 2026-10-20 applied (see PLAN). Branch develop, nothing pushed. Commits:

| Item | Commit | What |
|---|---|---|
| A | 82d7d1c | `deploy/backup.sh`: `UNIT_PATH_RE` (letters, digits, `. _ / + = , ~ -`) now also guards the checkout path written into the units (A1); `env_value` reads a bare `NAME` line of the requested key as "cannot be determined" (A2). RUNBOOK 11.3. |
| B | f94e78e | Explicit local-only mode `BACKUP_REMOTE=none` (python decides; wrapper refuses `--init-remote`, soak timer guard needs no bucket but still refuses the trading bucket). Warning + `OFFSITE_COPY=skipped`; remote runs print `OFFSITE_COPY=verified`. RUNBOOK 11/20.5, both env examples, checklist pin rule. |
| C | 1b39a70 | D064 real-S3 gate: `src/ops/backup_gate.py`, `python -m src.ops.backup real-s3-gate`, `deploy/backup-real-s3-gate.sh` (mode 100755). RUNBOOK 11 "Real-S3 gate", DEPLOY_GUIDE.vi card and quick-reference row. |
| D | a724593 | 16-43 PLAN and CHECKLIST: open points 1-7, section 0 additions, IMAGE_COMMIT supersession. |

## Tests (written first for A and B; all against fakes, no network)
- A: `test_a_checkout_path_the_units_cannot_carry_is_refused` (percent, ampersand, semicolon red before the fix; space already refused), `test_a_plain_copied_checkout_still_installs`, `test_a_bare_key_soak_bucket_cannot_be_determined` (6 forms, red before), `test_a_bare_key_trading_bucket_cannot_be_determined`, `test_a_bare_line_of_another_name_does_not_matter`.
- B python (`tests/test_backup_remote.py`): local-only scheduled with and without an injected runner (no rclone call, marker, warning), default mode still fails closed before pg_dump, `s3`/empty mode prints `verified`, unknown values refused without echo, push/init-remote/pull/retain refused, local drill success and unequal-count failure, remote drill marker. B shell (`tests/test_deploy_backup_scripts.py`): init-remote refusal (exit 2, no docker call), undeterminable/unknown modes, explicit s3, soak timer local-only without bucket / with own bucket / with trading bucket, default empty bucket still refused, help and docs. The two existing `--init-remote` tests now use a test env file instead of the checkout's `.env`.
- C (`tests/test_backup_gate.py`, 32): subpath mapping and refusal, multipart options, dry run touches nothing, all claims PASS with cleanup and no secret or bucket in output, blind cryptcheck fails every detection claim, interruption and failed purge, non-empty / malformed prefix, `BACKUP_REMOTE=none`, missing variables, existing evidence file, CLI dispatch, wrapper default / `--dry-run` / `--execute` evidence file and exit code / usage errors / no rclone in the wrapper.
- Per-file runs after C (last run): test_deploy_backup_scripts 104, test_deploy_compose 27, test_deploy_docs 43, test_deploy_guide_vi 25, test_deploy_heartbeat 99 (4 skipped), test_deploy_images 30, test_deploy_migrate 26, test_deploy_scripts 73 (13 skipped), test_deploy_workflows 43, test_backup 20, test_backup_gate 32, test_backup_lock 7, test_backup_remote 145, test_backup_restore 34, test_backup_retention 22, test_soak_runbook 64, test_soak_compose 33, test_decision_alignment_ops_risk 45, test_env_example 18, test_evidence_remote 18, test_rehearsal_compose 26; all passed. `ruff check`, `ruff format --check`, `mypy src` (203 files), `uv lock --check`, `scripts/verify_decision_alignment.py all` = ALL_PASS. No full suite (owner runs it after the Phase 19 merge).

## Not verifiable here (no real remote, no host)
- Every real-S3 behaviour of the gate: rclone on a real provider, that the forced 5 MiB cutoff yields real multipart objects (the script does not read ETags), `purge` of a prefix with versioning/object lock, the raw `lsf --format ps` output shape. The D064 real-S3 result stays pending until the owner runs step 1a.
- The psql commands (local socket trust in the soak postgres container), `compose cp`, and the gh/jq commands of the checklist were derived from the code, not run.

## Open questions for the owner
1. Plan 16-43 Task 1, second automated check: it reads `^IMAGE_COMMIT=<40 hex>$` but `evidence/16-65-gate.txt` has no such line; the post-Phase-19 gate record should carry one (checklist open point A).
2. `deploy/heartbeat.sh` (line 363) still rejects only whitespace in the checkout path it writes into units; the A1 rule was applied to `backup.sh` only (scope).
3. A2 refusals exit 1 (the script's existing `die` for "cannot be determined"); the env reader itself returns 2. `--init-remote` in local-only mode exits 2.
4. `DEPLOY_GUIDE.vi.md` needed a Vietnamese card for the new script (its tests require a card per deploy script); written in Vietnamese like the rest of that file.
