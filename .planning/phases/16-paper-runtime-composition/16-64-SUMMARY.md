---
phase: 16-paper-runtime-composition
plan: 64
subsystem: soak-image
status: complete
tags: [soak, image-commit, gate, r7, tp2-guard, PAPER-01]
requires: [16-63]
requirements: [PAPER-01]
provides:
  - "evidence/16-64-gate.txt: the 16-62 final gate repeated on the current tree (five exit=0 lines, PostgreSQL tests run), the efae1f3..HEAD code listing, docker results and IMAGE_COMMIT=6f73e5bb87167f386b22a64a00effa56ca4ef0bf"
  - "16-43-PLAN.md reads IMAGE_COMMIT from evidence/16-64-gate.txt and also checks that it contains 6f599dd"
  - "16-DEC-V260.md section 'R7 executed' (appended)"
affects: [16-43]
plan_head_before: dc2dd606e00d03cb49ede13023e6c80ac6645750
key-files:
  created:
    - .planning/phases/16-paper-runtime-composition/16-64-PLAN.md
    - .planning/phases/16-paper-runtime-composition/evidence/16-64-gate.txt
  modified:
    - .planning/phases/16-paper-runtime-composition/16-43-PLAN.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V260.md
    - .planning/ROADMAP.md
    - .planning/STATE.md
key-decisions:
  - "16-64: IMAGE_COMMIT is the last commit that changes code, tests, configuration or deployment files (6f73e5b); the tested tree (HEAD 7238d06) has the same code and image build context"
completed: 2026-10-20
---

# Phase 16 Plan 64: repeated final gate and the new soak IMAGE_COMMIT (R7) Summary

The soak image commit now contains the TP2 positivity guard: IMAGE_COMMIT=6f73e5bb87167f386b22a64a00effa56ca4ef0bf (6f599dd is an ancestor), gated on the current tree, and plan 16-43 reads it from evidence/16-64-gate.txt.

## Commits

| Task | What | Commit |
|---|---|---|
| plan | 16-64-PLAN.md, ROADMAP and STATE entries | 7238d06 |
| 1-3 | range check, gate, evidence, 16-43 pointers, "R7 executed" | 835e097 |
| close | this SUMMARY, ROADMAP and STATE | (closing docs commit) |

## Gate (tree at 7238d06, code identical to 6f73e5b)

- `pytest -m "not docker"`: 10412 ran, 10393 passed, 19 skipped (platform 7, shellcheck 12), 0 failed; PostgreSQL tests ran.
- ruff check, ruff format --check (631 files), mypy src (202 files), uv lock --check: exit 0.
- params/, manifest, grids, original authorization files and the v1 configuration unchanged since c654524; v2 configuration still has its single 16-56 commit.

## Code between efae1f3 and 6f73e5b

Plans 16-60, 16-61, 16-63 (guard, simulator 2.3.0) and Phase 18 (merge dde100b and its fixes). config/, deploy/, params/, Dockerfile and docker-compose.yml unchanged. The texts of 16-60 and 16-61 that say IMAGE_COMMIT never contains their code are history and no longer true for the new commit.

## Docker (local, separate from the gate)

- `pytest -m docker`: 17 passed, 11 skipped (no trading-alert-ops:dev image); the 3 passed image tests used the 2026-10-02 trading-alert:dev image, not this commit.
- `deploy/soak-image.sh` needs the soak env file (POSTGRES_USER interpolation), so the RUNBOOK recipe was not run here. A plain `docker build --target runtime` at 6f73e5b succeeded (sha256:3e787ea0..., local only, CRLF files from the Windows checkout, so not comparable with the soak-host image) and its in-image check passed; the ops target failed on network (DNS, then a self-signed certificate in the chain on the one retry).

## Deviations

- The RUNBOOK 20.6 recipe was not run past its compose interpolation (needs secrets); a plain docker build replaced it as a local check.
- docs/DECISIONS.md D075 still says R7 is "NOT DECIDED, open"; it was not edited (decision rows are the owner's), see Next.

## Next

Plan 16-43 on the soak host, building from IMAGE_COMMIT 6f73e5b after it is on origin/master and the targeted re-review of c654524..6f73e5b has passed. Open for the owner: whether D075's R7 sentence in docs/DECISIONS.md is updated.

## Self-Check: PASSED

- evidence/16-64-gate.txt exists with IMAGE_COMMIT and five exit=0 lines; 835e097 and 7238d06 are on develop.
