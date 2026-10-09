---
phase: 16-paper-runtime-composition
plan: 14
subsystem: infra
tags: [ec2, soak-host, preflight, user-decision, telegram, aws]

requires:
  - phase: 16-paper-runtime-composition
    provides: plan 16-07 (RUNBOOK section 19, soak_host_acceptance validator, tests/test_soak_runbook.py)
provides:
  - evidence/16-14-preflight.txt, proof that WR-05, the D064 push, D066 text and RUNBOOK 19 are present
  - decisions/16-DEC-O-12.md, option postpone (no EC2 number recorded)
  - decisions/16-DEC-Q-L.md, option separate-bot (soak host gets its own Telegram bot token)
affects: [16-20, 16-30]

actuals:
  tokens: 6000
  tasks: 3
  commits: 2
plan_head_before: 1d5e7b9
plan_head_after: 3c3efed58adf35a723278cd45e0cde38f497bc66

key-files:
  created:
    - .planning/phases/16-paper-runtime-composition/evidence/16-14-preflight.txt
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-12.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-L.md
  modified: []

key-decisions:
  - "O-12 postponed by the user: this machine has no connectivity to run the collector or reach AWS; the collector will be run from another machine. No instance type, EBS size, budget, S3 lifecycle or heartbeat value was chosen or recorded."
  - "Q-L: the soak host uses a separate Telegram bot token; the user creates the BotFather bot and never pastes the token anywhere."

requirements-completed: []

duration: not captured (two sessions with a user checkpoint between)
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 14: EC2 provisioning decisions Summary

**The host prerequisites are proven present and the two user decisions are recorded: O-12 is POSTPONED (no EC2 number exists) and Q-L is a separate Telegram bot for the soak host.**

## O-12 is postponed: what remains open

The plan's O-12 checkpoint accepts `postpone` as a valid recorded option, so this plan is complete. The consequence is stated in the plan itself: the collector stays on a user machine, every later open-interest gap is recorded as a coverage gap (D059 item 4), and the trial soak cannot start.

- Plan 16-20 (EC2 creation) cannot proceed until the user records O-12 `option: values` later, with each number in the user's own words: instance type, EBS volume size, budget-alert amount and notification address, S3 lifecycle and retention for the backup bucket, external heartbeat service and interval. No agent proposes any of them.
- Context the user gave (recorded as context only in `decisions/16-DEC-O-12.md`, not as values): the AWS account was created on 2026-07-25 under the new Free plan model (credits; auto-closes about 2027-01-25 or when credits run out, so a switch to the Paid plan is needed before then if the host is kept). The user asked whether the AWS free tier can be used; nothing was chosen.
- To resume: the user edits or replaces `decisions/16-DEC-O-12.md` with `option: values` plus one `key: value` line per number. The decision file belongs to the user; the existing postpone record documents the state on 2026-10-09.
- The D064 real-S3 gate stays OPEN (RUNBOOK 11, 19.1 item 2); it blocks the first real backup, not provisioning (preflight file).

## Accomplishments

- Task 1 (commit 46503bb): read-only preflight, five checks all PASS (WR-05 7148528 and D064 push e9a030c are ancestors of HEAD, no NOPASSWD line in `deploy/bootstrap.sh`, RUNBOOK `## 19.` and `11.8` present, `tests/test_soak_runbook.py` 18 passed).
- Task 2 (commit 3c3efed): `16-DEC-O-12.md` with `option: postpone`; grep verify `^option: (values|postpone)$` passes.
- Task 3 (commit 3c3efed): `16-DEC-Q-L.md` with `option: separate-bot`; grep verify `^option: (separate-bot|single-bot-rule)$` passes. No token value written anywhere.

## Task Commits

1. Task 1: preflight evidence - `46503bb`
2. Tasks 2 and 3: both decision records - `3c3efed`

**Plan metadata:** the docs commit carrying this SUMMARY, STATE.md and ROADMAP.md (not counted in `commits:` above, which was measured before it).

## Deviations from Plan

None - plan executed as written. The Q-L reply carried no extra text; the O-12 record adds a translation line and the earlier AWS context as labelled context lines, with `values: none recorded (postponed)` so the file cannot be mistaken for a values record.

## Requirement PAPER-01

Not marked complete by this plan: the plan's purpose (host created with the user's numbers) is deferred. Completion follows `requirements.ready-ids`.

## Known Stubs

None.

## Threat Flags

None. No token, key or password is in any record (T-16-33); Q-L decided before the soak (T-16-34); no capacity number was chosen by an agent (T-16-35).

## Verification

- Both plan grep verifies pass (see above). No code touched, so ruff/mypy gates not applicable.

## Self-Check: PASSED

- FOUND: evidence/16-14-preflight.txt, decisions/16-DEC-O-12.md, decisions/16-DEC-Q-L.md
- FOUND commits: 46503bb, 3c3efed (`git rev-list --count 1d5e7b9..HEAD` = 2 at the time of writing)
