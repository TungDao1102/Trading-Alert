---
phase: quick-261009-jqi
plan: 01
subsystem: operations documentation
status: complete
tags: [docs, vietnamese, deploy, runbook, traceability-test]

requires:
  - phase: 13.1-deployment-ci
    provides: deploy/*.sh, deploy/systemd, docker-compose.yml, RUNBOOK sections 11 and 13-19
  - phase: 16-paper-runtime-composition
    provides: plans 16-01..16-14 (SUMMARY files), decisions 16-DEC-O-12 (postpone) and 16-DEC-Q-L (separate-bot)
provides:
  - docs/operations/DEPLOY_GUIDE.vi.md, a Vietnamese operator guide (sections 0 to 15, eleven operation cards)
  - tests/test_deploy_guide_vi.py, a checker that keeps every command in the guide traceable
affects: [operators of the EC2 soak host, future edits of RUNBOOK.md or deploy/*]

requirements-completed: [QUICK-261009-jqi]

key-files:
  created:
    - docs/operations/DEPLOY_GUIDE.vi.md
    - tests/test_deploy_guide_vi.py
  modified: []

key-decisions:
  - "The guide never gives a runnable command for anything unbuilt: python -m src.paper.runtime appears only in a block labelled CHUA XAY, and DEMO, CANARY, LIVE have no commands."
  - "The checker enforces traceability by rule (deploy flags from the case arms, compose services and profiles from docker-compose.yml, python modules and quoted options from src, verbatim corpus, or a label) rather than by an allowlist of whole commands."
  - "Over-claim guard is per line: a line that carries the built label and also names Phase 18 to 26 fails, so table cells that need both were reworded."

actuals:
  tokens: 52500
  tasks: 3
  commits: 3
plan_head_before: 97a92a650778b13065f2097adb39617c7fb21f0e
plan_head_after: ed30321501edd000b77ea5cdc9a32b533acaa47e

duration: one session
completed: 2026-10-09
---

# Phase quick-261009-jqi Plan 01: Vietnamese operator deployment guide Summary

**A 1,900-line Vietnamese guide (sections 0 to 15, eleven nine-field operation cards, 49-row Phase 16 table, 30-row troubleshooting table, 43-item checklist) plus a 19-test checker that traces every deploy flag, compose call, python module and shell command back to the repository or to an explicit label.**

## Accomplishments

- Task 1 (commit 9e47a68): `tests/test_deploy_guide_vi.py` with groups common, part1, part2, part3 and final, and guide sections 0 to 5 (reading rules, overview, preparation, EC2 and the 16 acceptance conditions, bootstrap, collector and migration) with cards for `deploy/bootstrap.sh`, `deploy/migrate.sh` and `scripts/soak_host_acceptance.py`.
- Task 2 (commit 516da03): sections 6 to 9 (backups, restore and drill; Phase 16 table of all 49 plans with 01-14 built and 15-49 not built; separate Telegram bot, Binance keys and whitelist, heartbeat; SHADOW to DEMO to CANARY to LIVE with Phases 16 to 26) with cards for `deploy/backup.sh`, both systemd units, `deploy/restore.sh`, `deploy/backup-drill.sh` and `scripts/backup-drill.ps1`.
- Task 3 (commit ed30321): sections 10 to 15 (daily operations, update and rollback with the `deploy/update.sh` card and the `deploy/refresh-pins.sh` card, emergencies, troubleshooting, quick reference, final checklist).

## Verification (final run)

- `PYTHONPATH=. uv run --offline --frozen pytest tests/test_deploy_guide_vi.py -q`: 19 passed (all groups including final).
- `tests/test_deploy_docs.py` 35 passed; `tests/test_soak_runbook.py` 18 passed (each run as its own invocation).
- `ruff check` and `ruff format --check` on the checker: clean. `verify_decision_alignment.py docs`: ALL_PASS.
- `git diff --quiet 97a92a6 -- docs/operations/RUNBOOK.md deploy docker-compose.yml Dockerfile .env.example`: unchanged.
- No `gsd:write-continue` sentinel; no CR in the guide; the checker's negative cases (bad flag, missing script, wrong profile, unknown service, bare `config`, `down` with a volumes flag, volume prune, unlabelled missing module, unknown subcommand, unknown option) were exercised by hand and are rejected.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Line-ending assertion of the checker was wrong for Windows checkouts**
- **Found during:** Task 2
- **Issue:** `assert b"\r" not in raw` would fail when git (core.autocrlf=true here) turns the guide into CRLF on a checkout, although the repository content is LF.
- **Fix:** the test now rejects only mixed endings or a stray CR; the guide is still LF in the repository.
- **Files modified:** tests/test_deploy_guide_vi.py
- **Commit:** 516da03 (reason stated in the commit body)

**2. [Rule 1 - Bug] Four table cells in section 12 tripped the over-claim guard**
- **Found during:** Task 3
- **Issue:** cells such as "Phase 17 built; Phase 24 not built" put the built label and a Phase 18 to 26 name on one line.
- **Fix:** the Phase 17 part now reads "da hoan thanh" (completed) in words, and only the unbuilt later phase carries a label; no claim was weakened or strengthened.
- **Files modified:** docs/operations/DEPLOY_GUIDE.vi.md
- **Commit:** ed30321

### Other notes (not plan violations)

- Step numbering follows the contract of section 4 only loosely: the discussion of how to obtain a root session lives in step 4.1 (prepare), not 4.4; step 3.1 points at it.
- Section 10.5 gives no separate command to re-run `db-upgrade`: RUNBOOK documents none, so the guide says `docker compose up -d` re-applies migrations and labels the rest.
- The Task 3 commit message says "41" checklist items and "30 rows"; the file has 43 checklist items and 30 troubleshooting rows (the message is slightly off, the file is right).

## Open points found while writing (for the user, not decided by the guide)

- RUNBOOK 15.1 requires a fresh drilled backup before a migration, while RUNBOOK 19.4 item 6 says the first real backup waits for the D064 real-S3 gate. The two are not reconciled; the guide flags this in step 5.3 item 4 as a question for the user.
- RUNBOOK 13.1 assumes a root SSH login; AWS images normally do not offer one. The guide labels how to get a root session CHUA XAC MINH.
- No plan of Phase 16 builds an off-host heartbeat sender; the guide states this and labels it CHUA XAY.

## Known Stubs

None. The words "khung giu cho" in the guide describe the repository's own `paper` and `live` compose placeholders, which are labelled CHUA XAY.

## Threat Flags

None. Only two documentation/test files were added; no network endpoint, auth path or schema changed.

## Self-Check: PASSED

- FOUND: docs/operations/DEPLOY_GUIDE.vi.md
- FOUND: tests/test_deploy_guide_vi.py
- FOUND commits: 9e47a68, 516da03, ed30321
