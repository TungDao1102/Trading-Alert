---
phase: 16-paper-runtime-composition
plan: 07
subsystem: infra
tags: [runbook, ec2, soak-host, acceptance-validator, backup-chain, s3-object-lock, rev-08]

requires:
  - phase: 13.1-deployment-ci
    provides: deploy/bootstrap.sh, deploy/migrate.sh, deploy/restore.sh, RUNBOOK sections 11 to 17, WR-05 (7148528), D064 push (e9a030c)
provides:
  - RUNBOOK section 19 (19.1 to 19.7) with the EC2 soak-host provisioning, collector migration and research data path
  - scripts/soak_host_acceptance.py, a validator for the filled D042 acceptance file (16 condition ids)
  - tests/test_soak_runbook.py, the doc test that keeps section 19, the validator and the backup CLI in step
  - REV-08 study of S3 versioning and Object Lock against the current backup chain, no option selected
affects: [16-14, 16-20, 16-30]

actuals:
  tokens: 12000
  tasks: 3
  commits: 6
plan_head_before: aff1fda4a5a2ab97def12f02376acd36b4d4e95c
plan_head_after: 929ff43e805345d21f8d3b088c7b230d59e06a0f

tech-stack:
  added: []
  patterns:
    - "Runbook section parsed by a doc test (heading, table of condition ids, phrases, existing paths and flags)"
    - "Evidence validator prints condition id and field name, never a value, and scans leaves with src.ops.redaction"

key-files:
  created:
    - scripts/soak_host_acceptance.py
    - tests/test_soak_runbook.py
  modified:
    - docs/operations/RUNBOOK.md

key-decisions:
  - "The Parquet copy to the development raw root uses the existing `restore --skip-db --parquet-target /app/data/raw --force` (verifies, skips identical, aborts on different content) instead of a new copy command"
  - "The validator rejects unknown fields as an input error so a secret cannot hide in an extra field"
  - "No number the user owns is written in section 19; the test greps for instance types, storage sizes and currency amounts and allows only the cited IPv4 price line"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "scripts/soak_host_acceptance.py validates a filled acceptance file: exit 0 / 1 (first missing or non-PASS condition) / 2 (input error or secret-looking value, never echoed)"
    requirement: "PAPER-01"
    verification:
      - kind: unit
        ref: "tests/test_soak_runbook.py#test_a_complete_all_pass_file_exits_0"
        status: pass
      - kind: unit
        ref: "tests/test_soak_runbook.py#test_a_secret_looking_value_exits_2_without_echoing_it"
        status: pass
    human_judgment: false
  - id: D2
    description: "RUNBOOK 19.2 to 19.4: region ping first, one measurable acceptance row per D042 condition id, bootstrap and collector migration text with the OI gap recorded as a coverage gap"
    requirement: "PAPER-01"
    verification:
      - kind: unit
        ref: "tests/test_soak_runbook.py#test_19_3_names_a_command_and_a_pass_condition_for_every_required_condition"
        status: pass
    human_judgment: true
    rationale: "The commands were written from the research file and AWS CLI naming, never run against AWS or a host; only the user on the real instance can show they work (RUNBOOK 17 real-host-only)"
  - id: D3
    description: "RUNBOOK 19.5 exact pull, verify and no-overwrite copy commands to the development machine"
    requirement: "PAPER-01"
    verification:
      - kind: unit
        ref: "tests/test_soak_runbook.py#test_the_backup_cli_has_every_subcommand_and_flag_19_5_uses"
        status: pass
    human_judgment: true
    rationale: "Command syntax and flags are checked against src/ops/backup.py; running them against a real bucket is the D064 real-S3 gate and needs the user's remote"
  - id: D4
    description: "RUNBOOK 19.6 REV-08 study of S3 versioning and Object Lock against push_snapshot and apply_retention, with URLs, read date and no option selected"
    verification:
      - kind: unit
        ref: "tests/test_soak_runbook.py#test_19_6_lists_the_rev_08_facts_each_with_url_and_read_date"
        status: pass
    human_judgment: true
    rationale: "Whether the stated facts and the two labelled inferences are right can only be judged against the live AWS and rclone pages, which were not re-read"

duration: 15min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 07: Soak host runbook and acceptance validator Summary

**RUNBOOK section 19 gives the EC2 soak-host provisioning, collector migration and research-data pull steps with a region ping first and one measurable acceptance row per D042 condition, backed by a secret-safe acceptance-file validator and a doc test; the S3 versioning and Object Lock study (REV-08) is written and selects nothing.**

## Performance

- **Duration:** about 15 min (start time was not captured; first commit 11:30 and last 11:39, UTC+07:00)
- **Completed:** 2026-10-09T04:40Z
- **Tasks:** 3 (one tracer, two auto, all TDD)
- **Files modified:** 3 (1 doc, 1 script, 1 test file)

## Accomplishments

- `scripts/soak_host_acceptance.py` with `REQUIRED_CONDITIONS` (16 ids: REGION_PING_FAPI first through BACKUP_REAL_S3_GATE last). Exit 0 only when every id is PASS with a command, an evidence excerpt and a UTC `checked_at`; exit 1 names the first missing or non-PASS id; exit 2 names the condition and field of a secret-looking value, an unexpected field or an unreadable file, and never prints the value.
- RUNBOOK 19.2: `curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping` is the first host action, pass HTTP 200, and "if it fails, stop: do not install anything, the region or IP is not accepted".
- RUNBOOK 19.3: a table with command, pass condition and source per condition id; EBS default encryption is checked with `aws ec2 get-ebs-encryption-by-default --region ap-southeast-1` because the initial state of a new account is not documented (G12); chrony line `server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4` for Ubuntu (G14); the IPv4 price line is the only currency amount.
- RUNBOOK 19.4: only the collector moves; bootstrap (section 13, without `docker compose up -d`), UAT 8 to 10, `deploy/migrate.sh` (section 15), the OI gap recorded as a coverage gap (D059 item 4), the first real backup waits for the D064 real-S3 gate and a restore drill (11.6) runs before the long soak.
- RUNBOOK 19.5: pull with `src.ops.backup pull --dest /app/data/backup/pull-<UTC timestamp>` (optional `--snapshot`), a separate `verify`, then `restore --skip-db --parquet-target /app/data/raw --force`, which never overwrites a raw file.
- RUNBOOK 19.6: seven interaction points against the current `push_snapshot` and `apply_retention` (D064/D066 code re-read), facts with URL and read date 2026-10-08, two labelled inferences about retention purge and manifest removal under an Object Lock default, ends with "No option is selected here; the decision is O-01 (plan 16-30)."

## Task Commits

1. **Task 1: Tracer - validator and runbook test on one condition** - RED `822ead2` (test), GREEN `ee6cbc3` (feat)
2. **Task 2: D042 acceptance per condition, bootstrap and migration text** - RED `a597506` (test), GREEN `e639968` (docs)
3. **Task 3: Data path and REV-08 study** - RED `3e1f87b` (test), GREEN `929ff43` (docs)

**Plan metadata:** the docs commit that carries this SUMMARY, STATE.md and ROADMAP.md.

## Files Created/Modified

- `scripts/soak_host_acceptance.py` - acceptance-file validator (new)
- `tests/test_soak_runbook.py` - 18 tests: validator exit codes and no-echo, section 19 structure, id set equals validator ids, no user-owned numbers, named repository paths and backup CLI flags exist (new)
- `docs/operations/RUNBOOK.md` - section 19 appended (19.1 to 19.7)

## Decisions Made

- The copy into the development raw root reuses `restore --skip-db --force`: it re-verifies the bundle, checks every target path before copying, skips identical files and aborts on different content, which is the T-16-18 mitigation without new code.
- Unknown fields in the acceptance file are an input error (exit 2), so a secret cannot be carried in an extra field.
- The currency test flags `$` followed by a digit rather than any `$`, so shell expansions stay legal; the single allowed amount is the cited IPv4 hourly price with its URL and read date.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan command used bare `python` inside the ops image**
- **Found during:** Task 3 (read of `Dockerfile` lines 53-54 and `deploy/restore.sh` line 26)
- **Issue:** the plan's pull command `... ops python -m src.ops.backup pull ...` would run the base interpreter, which has none of the venv packages (F-705, comment above the Dockerfile health check); `deploy/restore.sh` and `deploy/backup.sh` use `/app/.venv/bin/python`.
- **Fix:** 19.5 uses `/app/.venv/bin/python` and `--no-deps` (as RUNBOOK 11.7 does), so the pull does not start PostgreSQL; the test pins the exact string.
- **Files modified:** docs/operations/RUNBOOK.md, tests/test_soak_runbook.py
- **Verification:** `tests/test_soak_runbook.py` passes; flags checked against `src/ops/backup.py`.
- **Committed in:** `929ff43`

**2. [Rule 2 - Missing critical] Explicit verification and a no-overwrite copy for the pulled data (T-16-18)**
- **Found during:** Task 3
- **Issue:** the plan asks for "the verification and the copy ... without overwriting" but names no command; a hand-written `cp` would not verify hashes or detect differing content.
- **Fix:** 19.5 adds `src.ops.backup verify --bundle-root ...` and the `restore --skip-db --parquet-target /app/data/raw --force` copy, both existing commands.
- **Files modified:** docs/operations/RUNBOOK.md, tests/test_soak_runbook.py
- **Committed in:** `929ff43`

**3. [Rule 3 - Blocking] Sudo condition cannot name the bypass rule keyword**
- **Found during:** Task 2
- **Issue:** `tests/test_deploy_docs.py` forbids the passwordless-sudo keyword anywhere in the RUNBOOK.
- **Fix:** the `SUDO_WITH_PASSWORD` row checks `sudo -k` then `sudo -v` prompting for a password and `passwd -S trading` status `P`, without naming the keyword.
- **Committed in:** `e639968`

---

**Total deviations:** 3 auto-fixed (1 bug in plan text, 1 missing safeguard, 1 blocking test constraint)
**Impact on plan:** none on scope; all three tighten the runbook text.

## Issues Encountered

None in execution. Points the text surfaces for the user and does not decide (also listed here for the orchestrator):

- Heartbeat check versus OI gap (19.3, 19.4): stopping the collector to prove the external monitor creates a permanent OI gap, and the collector must not run on the new host before `deploy/migrate.sh` (the restore needs an empty database). The text says to accept and record the gap; whether to test earlier with another mechanism is the user's choice (O-12).
- Old machine for `deploy/migrate.sh` (19.4 item 3): 15.1 needs non-interactive ssh and `docker compose` / `docker run` on the old host. If the old host is a Windows Docker Desktop machine this is not given; the alternative (backup, push, `deploy/restore.sh`) has a longer gap and needs the D064 real-S3 gate. The text stops and reports instead of choosing.
- `BACKUP_REAL_S3_GATE` has no command in the repository: no script runs the D064 real-S3 proof, so the acceptance entry quotes the id of the task that owns it.
- Commands marked "AWS CLI help" in 19.3 (EBS, Elastic IP, S3 public access block, budgets) were not read from a documentation page in the research pass; the text tells the operator to check `aws <service> <command> help` first.

## User Setup Required

None for this plan. The runbook it produced is the user's weekend procedure; the AWS account, region numbers (16-DEC-O-12), heartbeat service and old-host ssh access are user-owned.

## Next Phase Readiness

Plans 16-14 and 16-20 can reference RUNBOOK 19.4 and 19.5 and the validator; 16-14 reads `tests/test_soak_runbook.py` as a preflight. O-01 (plan 16-30) can decide from 19.6.

## Known Stubs

None.

## Threat Flags

None. The validator reads one local file, opens no network connection and prints no input value (T-16-17 mitigated by test); the pull copy refuses differing content (T-16-18 mitigated by 19.5 and by existing `restore` behaviour).

## Verification

- `.venv/Scripts/python -m pytest tests/test_soak_runbook.py tests/test_deploy_docs.py -q -p no:cacheprovider` : passed (53 tests).
- `.venv/Scripts/python -m ruff check scripts/soak_host_acceptance.py tests/test_soak_runbook.py` and `ruff format --check` : clean. `.venv/Scripts/python -m mypy src` : no issues (156 files).

## Self-Check: PASSED

- FOUND: scripts/soak_host_acceptance.py, tests/test_soak_runbook.py, docs/operations/RUNBOOK.md (section 19), this SUMMARY.
- FOUND commits: 822ead2, ee6cbc3, a597506, e639968, 3e1f87b, 929ff43 (`git rev-list --count aff1fda..HEAD` = 6 at the time of writing).
