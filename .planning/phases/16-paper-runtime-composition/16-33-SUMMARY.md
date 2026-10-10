---
phase: 16-paper-runtime-composition
plan: 33
subsystem: infra
tags: [runbook, soak, docker-compose, image-provenance, shell]
status: complete

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-32 soak wrapper deploy/compose-soak.sh, project trading-soak, paper service with --hold-on-refusal"
provides:
  - "RUNBOOK section 20 Soak project operations (20.1 to 20.6)"
  - "16-DEC-Q-I.md: user decision host-build-recorded"
  - "deploy/soak-image.sh: clean-tree, commit-tagged soak image build with a recorded commit and image id"
affects: [16-40, 16-42, 16-43, 16-44]

actuals:
  tokens: 9150
  tasks: 3
  commits: 4
plan_head_before: 712eeddfb066231d0f7de7023e519aff49a6befd
plan_head_after: c9df5ed9013a5138536daa8f88605e16a10e14c2

tech-stack:
  added: []
  patterns:
    - "Soak image provenance: per-commit tags plus a 0600 record .deploy/soak-image.env and an append-only .deploy/soak-image.history"

key-files:
  created:
    - deploy/soak-image.sh
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-I.md
  modified:
    - docs/operations/RUNBOOK.md
    - docs/operations/DEPLOY_GUIDE.vi.md
    - tests/test_soak_runbook.py

key-decisions:
  - "Q-I (user, 2026-10-10): host-build-recorded. The registry and ci-save-transfer options were considered and are not automatic fallbacks."
  - "The soak image record is a separate file (.deploy/soak-image.env), not .deploy/last-good.env, because deploy/update.sh overwrites last-good.env on every --ref run."

requirements-completed: [PAPER-01]
---

# Phase 16 Plan 33: Soak operations runbook and pinned-image recipe Summary

RUNBOOK section 20 now states how the soak project is operated, and the soak image is built by `deploy/soak-image.sh` on the host from a clean commit, tagged with the full commit id, with the commit and image ids recorded (user decision Q-I: host-build-recorded).

## What was built

- **Task 1 (tracer, RED c36d283, GREEN 9df382c).** RUNBOOK section 20, subsections 20.1 to 20.6:
  - 20.1: the wrapper `deploy/compose-soak.sh` for every soak command, and no `down -v` on `trading-soak`. It also holds the exit-code table of `ExitCode`: every member, the `--hold-on-refusal` rule for codes 3 to 6, SKIPPED exits 0 and is not restarted, and a crash or code 7 restarts and shows as a CRASH gap.
  - 20.2: every stop or deploy during the trial is a PLANNED_RESTART and never covered. 95 percent of 336 h leaves about 16.8 h for all uncovered time together (REV-01, REV-17).
  - 20.3: the Telegram rule of 16-DEC-Q-L (separate bot, token never pasted).
  - 20.4: the rehearsal runs before the trial in `trading-rehearsal`, never in `trading-soak` (REV-03).
  - 20.5: a backup (11.4) and a restore drill (11.6) into a scratch target before the long soak, never into the soak database.
  - 20.6: the stub pointing at the Q-I record.
- **Task 2 (decision checkpoint).** The orchestrator relayed the user's verbatim reply "host-build-recorded đi". It is recorded in `decisions/16-DEC-Q-I.md` (option, decided by user, date 2026-10-10, words verbatim, and a note that the reviewer's `registry` proposal was considered and not chosen). Committed in 2f22e34 together with the RED tests of Task 3.
- **Task 3 (RED 2f22e34, GREEN c9df5ed).**
  - `deploy/soak-image.sh [--dry-run]` refuses any uncommitted change, tracked or untracked. It builds `trading-alert:<commit>` and `trading-alert-ops:<commit>` through `deploy/compose-soak.sh --profile ops build` with `IMAGE_TAG=<commit>`. It re-checks that the tree and HEAD did not change, then writes `GIT_SHA`, `IMAGE_TAG`, `APP_IMAGE_ID` and `OPS_IMAGE_ID` to `.deploy/soak-image.env` (0600, gitignored, `.prev` kept, history appended).
  - RUNBOOK 20.6 gives the commands, the "never from a working-tree bind mount" rule, the rebuild after the allowlist commit (the allowlist is a source constant, O-04, plan 16-42), and how `deploy/update.sh` relates to the wrapper.
  - The Vietnamese deploy guide has an operation card and a quick-reference row for the script.

## Verification

- `pytest tests/test_soak_runbook.py tests/test_deploy_docs.py tests/test_soak_compose.py tests/test_deploy_guide_vi.py tests/test_deploy_scripts.py -m "not docker"` passes.
- `ruff check .` is clean. Ruff format is clean on the changed test file. Shellcheck reports only SC1091 (info, `lib.sh` not followed), which the existing scripts also produce.
- Only dry-run was exercised, in a throwaway git repository. No real build ran: no docker, no network, no host.

## TDD gate compliance

- Task 1: RED c36d283 (`test(16-33)`, assertions failed because section 20 did not exist), then GREEN 9df382c (`feat(16-33)`).
- Task 3: RED 2f22e34 (`test(16-33)`), then GREEN c9df5ed (`feat(16-33)`).
- The RED run of Task 3 failed on `assert source.is_file()` for the missing script and on the section 20.6 phrase assertions. The decision-record test passed in RED because the record was committed in the same commit.
- No REFACTOR commits. `gsd_run check tdd-red-evidence` was not run; the RED failures were read from the pytest output.

## Deviations from Plan

**1. [Rule 3 - Blocking] DEPLOY_GUIDE.vi.md operation card and quick-reference row.**
- **Found during:** Task 3 verification (not in the plan's `files_modified`).
- **Issue:** `tests/test_deploy_guide_vi.py` requires an operation card, a mention and a section 14 quick-reference row for every `deploy/*.sh` script, so the new script broke two tests there. The guide also said the section 20 runbook and the 16-33 image recipe did not exist yet.
- **Fix:** Added the card "Thẻ lệnh: deploy/soak-image.sh", one quick-reference row and the source line entry. Updated the two stale sentences in step 7.5.
- **Files modified:** docs/operations/DEPLOY_GUIDE.vi.md
- **Commit:** c9df5ed

**2. [Judgement] Separate record file instead of `.deploy/last-good.env`.**
- The option text in the plan mentions "deploy/update.sh and .deploy/last-good.env". Recording the soak image there would be overwritten by any `update.sh --ref` run, which is the failure mode RUNBOOK 14.4 describes. The script writes `.deploy/soak-image.env` with the same key layout plus `IMAGE_TAG`, and RUNBOOK 20.6 and the card say `update.sh` is not used for the soak project. If the user wants the same file, that is a one-line change plus a decision.

Otherwise the plan was executed as written. The Q-I checkpoint was handled by returning to the orchestrator and resuming with the user's relayed reply.

## Known Stubs

None.

## Threat Flags

None. T-16-77 (uncommitted or unrecorded code in the soak) is mitigated by the dirty-tree refusal, the post-build re-check and the record. T-16-78 (restarts not accounted for) is mitigated by RUNBOOK 20.2.

## Open items for the user and later plans

- Nothing has been run on a real host. The build, the record and the start sequence are `[CHƯA XÁC MINH]` until the soak host exists (19) and plan 16-43 or 16-44 runs them.
- The allowlist commit of plan 16-42 must come before the soak image is built (20.6).
- The registry option would need a new DECISIONS entry (D050) and a new user decision.

## Self-Check: PASSED

- FOUND: deploy/soak-image.sh, .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-I.md, docs/operations/RUNBOOK.md section 20.
- FOUND commits: c36d283, 9df382c, 2f22e34, c9df5ed.
- STATE.md, ROADMAP.md, scripts/paper_ws_smoke.py and evidence/16-21-* untouched.
