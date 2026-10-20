---
phase: 16-paper-runtime-composition
plan: 65
subsystem: paper-liveness, deploy-backup, soak-evidence, soak-image
status: complete
tags: [review-fix, liveness, heartbeat, backup, evidence-export, gate, image-commit, PAPER-01]
requires: [16-64]
requirements: [PAPER-01]
provides:
  - "the liveness stamp belongs to the instance-lease holder and records no frame before the first one (paper-liveness/2)"
  - "deploy/backup.sh reads BACKUP_S3_BUCKET as Compose does and substitutes unit tokens safely"
  - "scripts/export_soak_evidence.py refuses an explicit --as-of later than now (P16R-01)"
  - "evidence/16-65-gate.txt: final gate and IMAGE_COMMIT=9b27da55ff1675b66c8033792b68186da9b4a498"
  - "16-43-PLAN.md reads IMAGE_COMMIT from evidence/16-65-gate.txt and depends on 16-65"
affects: [16-43]
key-files:
  created:
    - .planning/phases/16-paper-runtime-composition/16-65-PLAN.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-LIVENESS-FIRST-FRAME.md
    - .planning/phases/16-paper-runtime-composition/evidence/16-65-gate.txt
  modified:
    - src/paper/liveness.py
    - src/paper/runtime.py
    - deploy/backup.sh
    - scripts/export_soak_evidence.py
    - tests/test_paper_runtime_liveness.py
    - tests/test_deploy_backup_scripts.py
    - tests/test_soak_evidence_export.py
    - config/paper/README.md
    - docs/operations/RUNBOOK.md
    - .planning/phases/16-paper-runtime-composition/deferred-items.md
    - .planning/phases/16-paper-runtime-composition/16-43-PLAN.md
    - .planning/ROADMAP.md
    - .planning/STATE.md
key-decisions:
  - "only the instance-lease holder owns the liveness stamp: it is removed right after the lease and at every exit; a start refused before or by the lease touches no stamp (orchestrator decision, owner informed)"
  - "IMAGE_COMMIT is 9b27da5, the last commit that changes code, tests, configuration or deployment files; everything after it is .planning only"
completed: 2026-10-20
---

# Phase 16 Plan 65: fixes of the review of c654524..6f73e5b and the new soak IMAGE_COMMIT Summary

The independent review of c654524..6f73e5b (Phase 16 part; Phase 18 was reviewed by the owner separately) found one MAJOR and several MINOR problems. Plan 16-65 fixed the MAJOR one, two MINOR deploy/backup.sh ones and, with the owner's agreement, P16R-01, then gated the tree and recorded IMAGE_COMMIT=9b27da55ff1675b66c8033792b68186da9b4a498 for plan 16-43.

## What the review found and what 16-65 fixed

| Finding | Fix | Commit |
|---|---|---|
| MAJOR: the watchdog stamped `last_frame_utc = now` at its start and no exit removed the stamp, so a runtime crashing and restarting within seconds under `restart: unless-stopped` kept `--liveness` passing and the paper heartbeat never alerted | schema paper-liveness/2 (no last-frame time before the first message), stamp removed at start and on every exit, restart-loop test | 5c866c4 |
| follow-up of the MAJOR fix: the start removal ran before the instance lease, so a second start in the same container refused with exit 8 deleted the holder's stamp (false not-live) | removal moved to right after the lease; a start refused before or by the lease touches no stamp | 9b27da5 |
| MINOR: backup.sh parsed BACKUP_S3_BUCKET differently from Compose | Compose-like parse (export prefix, last assignment, quotes, inline comment), fail closed when undeterminable | 86b4db7 |
| MINOR: `&` or `%` in the soak env path could be rewritten in the unit files | patsub_replacement off, heartbeat.sh path pattern enforced | 86b4db7 |
| P16R-01 (deferred MINOR, owner agreed to fix it here): an explicit `--as-of` later than now made a mid-soak bundle look final (wrong FAIL, never a false PASS) | `_as_of` refuses an explicit `--as-of` after the injected now: exit 2, nothing written, nothing published | 56844f9 |

Decision note: decisions/16-DEC-LIVENESS-FIRST-FRAME.md (implementation fix of 16-DEC-HUNG-RUNTIME, with a follow-up section for 9b27da5). Owner-ratified values (120 s bound, heartbeat 60/60/120, restart policy, config/paper/paper-runtime-v2.toml) are unchanged.

## Deferred (not touched)

- P16R-02: `src/paper/shadow_confirm.py` `_deferred_confirmed` keeps only the last adoption of one `expire_due` sweep. Registered in ROADMAP.md under the inherited items of Phase 23.
- P16R-03: `expire_due` runs on the event-loop thread and may read the database. Registered in ROADMAP.md under Phase 24, folded into G4-040.
- Both are listed in deferred-items.md; P16R-01 there is marked FIXED by 56844f9.

## Commits

| Step | What | Commit |
|---|---|---|
| plan | 16-65-PLAN.md | dd9a44a |
| Task 1 | liveness stamp per process, no frame before the first | 5c866c4 |
| Task 2 | backup.sh bucket guard and unit substitution | 86b4db7 |
| Task 3 | docs and decision note | 4bc0101, f1cf29b |
| Task 2b | P16R-01 fix (tests red first) | 56844f9 |
| Task 2b docs | plan amendment, P16R-01 marked FIXED | a87489b |
| Task 1b | only the lease holder owns the stamp (tests red first) | 9b27da5 |
| Task 1b docs | plan, decision-note follow-up | ce79193 |
| Task 4 | gate evidence, 16-43 pointers | bb56b95 |
| close | this SUMMARY, ROADMAP and STATE | (closing docs commit) |

Between them, and part of the IMAGE_COMMIT range: quick task 261020-xd4 (7e54082, 83b46fe: pytest-xdist in the dev extra, opt-in only) and quick task 261020-spd (622e65f, c410247, 5000686, 8b01a61, a5e2b30: test speed; its only production change is 8b01a61 in src/data/case_input.py, which src/paper does not import).

## Gate (tree at ce79193, code identical to 9b27da5)

- `pytest -m "not docker"` sequential: 10460 ran, 10441 passed, 19 skipped (platform 7: symlinks 2, NTFS modes 1, Windows file modes 4; shellcheck not on PATH 12), 0 failed; 20 min 25 s; PostgreSQL tests ran (the two shadow pg files alone: 7 passed).
- ruff check, ruff format --check (632 files), mypy src (202 files), uv lock --check (62 packages), verify_decision_alignment all (ALL_PASS): exit 0.
- params/, manifest, grids, original authorization files and the v1 configuration unchanged since c654524; paper-runtime-v2.toml unchanged since its single commit 63ffa58.
- pytest-xdist does not enter the runtime image: the Dockerfile runs `uv sync --frozen --no-dev` with no extra; `uv export --frozen --no-dev` lists no pytest or xdist.

## IMAGE_COMMIT

IMAGE_COMMIT=9b27da55ff1675b66c8033792b68186da9b4a498 (supersedes 6f73e5b of 16-64; contains 6f599dd). `git diff --name-only 9b27da5 HEAD` lists .planning files only. Re-review range before push or merge: c654524..9b27da5; the part not yet reviewed is 6f73e5b..9b27da5.

## Deviations

- Task 2b (P16R-01) and Task 1b (lease-holder follow-up) were added during execution, the first with the owner's agreement and the second by orchestrator decision with the owner informed; both are in the plan.
- A first full run on a87489b finished but was cancelled by the owner's decision ("fix first, then run clean") and is not a gate result; the gate above is the one clean sequential run.
- The soak-export tests now pin the default clock (`_system_now`) to 2030-01-01, because their fixture windows start on 2026-11-01, after today, and an explicit `--as-of` later than the clock is now refused.
- Docker tests and a local image build were not repeated (Dockerfile, .dockerignore and docker-compose.yml unchanged since 6f73e5b; see evidence/16-64-gate.txt).

## Next

Targeted re-review of 6f73e5b..9b27da5, then push and merge, then plan 16-43 on the soak host building from IMAGE_COMMIT 9b27da5.

## Self-Check: PASSED

- evidence/16-65-gate.txt exists with IMAGE_COMMIT and six exit=0 lines; 16-43-PLAN.md has no 16-64-gate pointer left and depends on 16-65.
