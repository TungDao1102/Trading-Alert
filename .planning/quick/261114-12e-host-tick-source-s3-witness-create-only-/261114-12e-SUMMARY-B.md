---
phase: quick-261114-12e
plan: 02
subsystem: paper-freeze-evidence-host
tags: [freeze-ticks, host-timer, s3-witness, least-privilege, systemd, runbook, d109, 16-dec-host-tick]
requires: [261114-12e-01, 16-DEC-HOST-TICK, 16-DEC-O-01]
provides: [deploy/freeze-witness.sh, trading-soak-freeze-witness service and timer, RUNBOOK 20.10, DECISIONS D109, Vietnamese guide cards]
affects: [deploy/freeze-witness.sh, deploy/systemd, docs/DECISIONS.md, docs/DOC_STATUS.md, docs/operations/RUNBOOK.md, docs/operations/DEPLOY_GUIDE.vi.md]
key-files:
  created:
    - deploy/freeze-witness.sh
    - deploy/systemd/trading-soak-freeze-witness.service
    - deploy/systemd/trading-soak-freeze-witness.timer
    - tests/test_deploy_freeze_witness.py
  modified:
    - docs/operations/RUNBOOK.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/operations/DEPLOY_GUIDE.vi.md
    - tests/test_soak_runbook.py
    - tests/test_deploy_docs.py
decisions:
  - "D109 (Accepted 2026-11-14) amends 16-DEC-O-01 with the owner's least-privilege wording: one dedicated create-only host credential (s3:PutObject with s3:if-none-match) under a sibling witness prefix, held as the systemd credential freeze-witness. Grace 1800, the slot grid, the minute list, the thresholds, the criteria set and D065 item 4 are unchanged."
status: complete
commits: 5
plan_head_before: de580e39c4430c2974d319b450a72531bbf33576
plan_head_after: 8bb4dbb1e597a7d712c55611f600ecac9567d063
actuals:
  tokens: 30000
  tasks: 3
  commits: 5
completed: 2026-11-14
---

# Phase quick-261114-12e Plan B: host freeze tick script, units, RUNBOOK 20.10, D109 Summary

The soak host now has an installable hourly freeze tick (`deploy/freeze-witness.sh` with `trading-soak-freeze-witness.service` and `.timer`) that runs the freeze CLI in the paper container's image on a scratch copy of the pin and uploads the exact line bytes create-only to the S3 witness prefix with a credential that is never in argv, stdout, stderr, a container or the repository; D109 amends O-01 for that one credential, RUNBOOK 20.10 gives the owner-run procedure, and the Vietnamese guide has cards for the three new files.

BASE (plan B) = `de580e39c4430c2974d319b450a72531bbf33576` (HEAD before the first commit). The orchestrator's SUMMARY commit (this file) is the sixth commit of the plan; `commits: 5` above is measured at write time, before it.

## Commits (branch develop)

| # | Task | Commit | Message |
|---|---|---|---|
| 1 | 1 RED | 7f938ec6 | test(quick-261114-12e): host freeze tick witness script and units, offline (RED) |
| 2 | 1 GREEN | 629978e3 | feat(quick-261114-12e): host freeze tick timer that uploads the exact line create-only to the S3 witness prefix |
| 3 | 2 RED | e9728e1c | test(quick-261114-12e): RUNBOOK 20.10 and the O-01 amendment row (RED) |
| 4 | 2 GREEN | 66cee20c | docs(quick-261114-12e): D109 amends O-01 for the host freeze tick witness; RUNBOOK 20.10 and the 20.7 exception |
| 5 | 3 | 8bb4dbb1 | docs(quick-261114-12e): Vietnamese guide cards for the host freeze tick witness |
| 6 | summary | (this file) | docs(quick-261114-12e): summary of plan B |

RED evidence: Task 1 RED failed (script absent, exit 127 in the stubbed run; the unit-file tests failed on a missing file). Task 2 RED failed 6 tests: the 5 new RUNBOOK tests and the `freeze-witness.sh` case of the parametrised script-section test.

D number taken: **D109** (highest row was D108, rows contiguous, DC-01 and DC-02 pass).

## What was built

- `deploy/freeze-witness.sh` (mode 100755 in the index): one tick (default), `--set-credential`, `--install-timer --soak-env-file PATH`, `--dry-run`, `-h`. Exit codes 0 to 6 as in the plan. The credential is read only from `$CREDENTIALS_DIRECTORY/freeze-witness` (no file fallback), validated as exactly five `key=value` lines against allow-lists, kept in non-exported variables and handed to curl only through `--config -` from the `printf` builtin. The script refuses xtrace. Docker verbs are exactly `compose ... ps` (through `compose-soak.sh`), `inspect`, `cp` and one `run --rm --network none --read-only --cap-drop ALL`. Upload is once, never retried, always with `If-None-Match: *` and a signed `x-amz-content-sha256`.
- Units: oneshot `User=trading`, `LoadCredential=freeze-witness:@CREDENTIAL_FILE@`, no link to any other unit; timer `OnCalendar=*-*-* *:@CRON_MINUTE@:00 UTC`, `Persistent=false`, `AccuracySec=1s`, no random delay. `--install-timer` reads the minute from the single hourly cron of `paper_freeze_check.yml`.
- `tests/test_deploy_freeze_witness.py`: 89 offline tests (stubs for docker, curl, systemctl, date; FAKE credential sentinels; the 14 behaviours of the plan plus parametrised cases: 20 invalid credential shapes, slot edge cases, malformed ids, bad modes).
- RUNBOOK: new 20.10 (prerequisite, AWS policy example as valid JSON with `<evidence-bucket>`, `<witness-prefix>`, `<account-id>`, `<witness-user>`, store and install, owner-run verification, exporter, remote down, what it never does, not shown by any test); 20.7 now cites seven decision records, names the one write exception in the write-timing bullet and has the host-witness paragraph after step 2 (its fenced commands are unchanged).
- DECISIONS D109 and a DOC_STATUS line dated 2026-11-14; Vietnamese guide: three cards (script, service, timer) with the nine fields, section 14 rows for every flag and the two units, and the two source lines.

## Verification

- Final run, once: `uv run pytest tests/test_deploy_freeze_witness.py tests/test_deploy_scripts.py tests/test_deploy_heartbeat.py tests/test_deploy_docs.py tests/test_deploy_guide_vi.py tests/test_soak_runbook.py tests/test_soak_compose.py tests/test_agents_md.py`: 502 tests, 498 passed, 4 skipped (the 4 are `tests/test_deploy_heartbeat.py:403`, file modes on Windows). `tests/test_deploy_freeze_witness.py` alone: 89 passed. shellcheck is installed here and `test_script_passes_shellcheck[freeze-witness.sh]` passed.
- `uv run ruff check`: clean. `uv run ruff format --check`: 1029 files already formatted. `uv run mypy src`: no issues in 291 files. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `uv lock --check`: resolved, `uv.lock` unchanged.
- Scope gate `git diff --quiet BASE HEAD -- src scripts params config .github src/live src/execution src/approval .planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-01.md`: clean. `git diff --name-only BASE HEAD` lists only the ten plan paths.
- Not run, by instruction: the full suite, any network call, real S3, systemctl, rclone, docker.

## Deviations from Plan

### Auto-fixed Issues

None needed against the code under test. Three plan-level clarifications:

1. **[Rule 3 - working-copy line endings]** The plan says every edited file is LF in the working tree. The working copies of RUNBOOK, DECISIONS, DOC_STATUS, the guide, `tests/test_soak_runbook.py` and `tests/test_deploy_docs.py` are CRLF (the index is LF under autocrlf), so those edits were made bytes-aware and kept CRLF. New files (`deploy/*`, `tests/test_deploy_freeze_witness.py`) are LF.
2. **[Rule 1 - test text]** The first GREEN run showed that three static-text assertions I wrote in the RED test file did not match the real script text (curl line count, docker verb scan, credential holder scan). They were corrected in the GREEN commit (`629978e3` also contains `tests/test_deploy_freeze_witness.py`); no behaviour test was weakened.
3. **DOC_STATUS date.** The plan says to date the line with the UTC execution date, which was still 2026-11-13 (local 2026-11-14 02:xx +0700); the plan's own Test 3 requires a line dated 2026-11-14 or later and the owner decision is dated 2026-11-14, so the line is dated 2026-11-14.
4. **Guide location.** The plan describes the existing heartbeat cards as section 7; they are in section 8. The new cards were placed where the plan says (section 7, after the `compose-rehearsal.sh` card, before step 7.6); section 14 rows follow the paper-heartbeat rows.

## Open: owner-run steps of RUNBOOK 20.10 (not verified by any agent)

- Create the dedicated witness user or key and apply the identity and bucket policies (with the three Deny statements); check them in the provider's policy simulator.
- `sudo deploy/freeze-witness.sh --set-credential`, then `--install-timer --soak-env-file /home/trading/soak.env` (dry run first).
- Build an image from a commit that contains plan A (RUNBOOK 20.6) before the next pin; with an older image the unit exits 5.
- One manual tick (`sudo systemctl start trading-soak-freeze-witness.service`), then an export with `--host-witness` and `EVIDENCE_S3_WITNESS_PREFIX`; confirm `host witness: N object(s) read` and the server ModTime in `host_witness_listing.json`.
- With the witness credential, confirm that list, read, delete and a second PUT to the same key are refused (403 or 412).
- Unverified anywhere: systemd credential delivery, the timer firing, the container permissions (the scratch directory is owned by `trading` and the container runs as the same uid), and what a real curl SigV4 PUT with `If-None-Match: *` returns on the chosen provider.

## Known Stubs

None. No placeholder data flows to a consumer; the `<...>` markers in RUNBOOK 20.10 and the guide are documented placeholders by design.

## Threat Flags

None beyond the plan's register (T-26111412e-09 to -16 mitigated as listed: credential only in curl stdin config, tested for argv, stdout, stderr and the stub log; create-only header on every PUT, one call, no retry; scratch copy of the pin; no docker verb besides ps, inspect, cp and run --rm; no unit link; placeholders only in the documents).

## Self-Check: PASSED

- Files exist: `deploy/freeze-witness.sh`, the two units, `tests/test_deploy_freeze_witness.py`, RUNBOOK 20.10, D109 row, DOC_STATUS line, guide cards (found on disk; `git diff --name-only BASE HEAD` lists them).
- Commits 7f938ec6, 629978e3, e9728e1c, 66cee20c, 8bb4dbb1 are ancestors of HEAD (`git rev-list --count BASE..HEAD` = 5 before this file).
