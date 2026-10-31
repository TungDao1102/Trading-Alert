---
phase: 24-live-runtime-composition-demo
plan: 25
subsystem: deploy-image
tags: [dockerfile, compose, build-arg, revision-stamp, ops-04, phase-24]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: "24-01 owner answers Q12 (bake the limits files) and Q13 (build-time stamp); 24-11 read_build_revision and the live --healthcheck"
provides:
  - "Dockerfile: config/execution and config/binance copied into the runtime stage; ARG/ENV TRADING_APP_REVISION (no default)"
  - "docker-compose.yml: build.args TRADING_APP_REVISION on db-upgrade (runtime image) and backup (ops image)"
  - "deploy/update.sh and deploy/soak-image.sh export the 40-hex commit before compose build"
  - "tests/test_dockerfile_revision_stamp.py: static stamp checks and four docker-marked image checks"
affects: [24-31, 24-32]

key-files:
  created:
    - tests/test_dockerfile_revision_stamp.py
  modified:
    - Dockerfile
    - docker-compose.yml
    - deploy/update.sh
    - deploy/soak-image.sh
    - .env.example
    - tests/test_deploy_images.py
    - tests/test_deploy_compose.py
    - tests/test_deploy_scripts.py

key-decisions:
  - "ARG/ENV sit after the config COPY lines and the dependency install, so a new commit never invalidates the uv sync layer; the ops stage inherits the ENV through FROM runtime."
  - "An unstamped build sets the variable to the empty string; read_build_revision treats empty as malformed, so the healthcheck answers app_revision unknown plus app_revision_problem (names the variable, never a value) and still exits through the normal probe path."
  - "update.sh stamps from HEAD after the real checkout; in --dry-run it resolves REF itself and prints a placeholder when REF is unresolved. soak-image.sh stamps the same 40-hex commit that names the images."

patterns-established:
  - "Image facts for the runbook/gate: build arg name TRADING_APP_REVISION; set by deploy/update.sh (after git checkout --detach) and deploy/soak-image.sh (before compose-soak.sh build); passed by docker-compose.yml build.args; read in-image by src.adapters.code_version.read_build_revision."

requirements-completed: [OPS-04]

duration: ~1h
completed: 2026-10-31
status: complete
actuals:
  tokens: 6300
  tasks: 3
  commits: 2
commits: 2
plan_head_before: 17307cd08288d97d6bc482e258b1380955ec41f5
plan_head_after: 912b0197507823a91ec818884adc2161f8420097
---

# Phase 24 Plan 25: image limits and revision stamp Summary

The runtime image now carries `config/execution` and `config/binance` and reports the commit it was built from: `ARG`/`ENV TRADING_APP_REVISION` in the runtime stage, passed by compose `build.args` and exported by `deploy/update.sh` and `deploy/soak-image.sh` before the build.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 (tracer) | Image carries the limits and answers --healthcheck with the stamped revision | a2330ecc |
| 2 | Compose and the deploy scripts pass the commit as the build argument | 912b0197 |
| 3 | Image facts pinned (the `.dockerignore` test lives in the new test file, committed with Task 1) | a2330ecc |

## Image facts for plans 24-31 and 24-32

- Build argument: `TRADING_APP_REVISION` (40 lowercase hex), no default, no secret.
- Set by: `deploy/update.sh` (exported after `git checkout --detach "$REF"`, printed as `+ export TRADING_APP_REVISION=<sha>`), `deploy/soak-image.sh` (exported before `compose-soak.sh --profile ops build`, printed as `revision stamp TRADING_APP_REVISION=<sha>`). A hand-run `docker compose build` takes it from the environment or `.env` (documented, commented, in `.env.example`); unset gives `unknown`.
- Passed by: `docker-compose.yml` `build.args` on `db-upgrade` (runtime image) and `backup` (ops image).
- `--rollback` does not build; the older images keep their own stamp.
- In-image check: `/app/.venv/bin/python -m src.live.runtime --healthcheck` prints JSON with `app_revision` and `python_version`.
- Docker result: the four docker-marked tests in `tests/test_dockerfile_revision_stamp.py` were RUN and PASSED (Docker 29.8.0 daemon up, `TRADING_CI_STRICT=1`): stamped image reports the stamp and Python 3.13, carries both limits files, has no `.git`/`.env` in `/app`, and an unstamped image prints `unknown` and still answers.

## Verification run

- `uv run pytest -m "not docker" tests/test_deploy_*.py tests/test_soak_compose.py tests/test_soak_runbook.py tests/test_dockerfile_revision_stamp.py -n 4`: all passed (pre-existing infra skips only).
- `uv run pytest -m docker tests/test_dockerfile_revision_stamp.py`: 4 passed.
- `shellcheck -x update.sh soak-image.sh` (from `deploy/`): clean. LF kept on Dockerfile, compose and both scripts.
- `uv run ruff check` and `ruff format --check` on the four touched Python test files: clean.
- FROM lines unchanged (diff shows zero `FROM` changes); `pyproject.toml` and `uv.lock` untouched.

## Deviations from Plan

**1. [Rule 3 - Blocking] `.env.example` edited (not in the plan's file list)**
- **Found during:** directly affected gate run (`tests/test_deploy_docs.py::test_every_compose_variable_is_documented_in_env_example`).
- **Issue:** the new `${TRADING_APP_REVISION:-}` interpolation in `docker-compose.yml` must be documented in `.env.example` (the gate matches `^#?\s*VAR=`).
- **Fix:** added a commented `# TRADING_APP_REVISION=` block explaining that the scripts export it. Commented, so it never reaches interpolation.
- **Files modified:** `.env.example`
- **Commit:** 912b0197

**2. [Plan wording] update.sh tests live in `tests/test_deploy_scripts.py` with a small dedicated rig**
- The existing update.sh rig is in `tests/test_deploy_backup_scripts.py` (not listed); a separate stub-git/stub-docker rig was added to the listed `tests/test_deploy_scripts.py`. The existing update tests in the other file were re-run (`-k update`, 8 passed, then the whole `test_deploy_*` set).

**3. Compose test scope:** a test asserting the variable never reaches a container `environment` was dropped: the test rig's `.env` doubles as `env_file`, so it cannot express the property. The Dockerfile `ENV` is the only intended carrier and `compose` `build.args` is build-only.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or file-access surface; the stamp is a non-secret commit id. T-24-76 (stamp + healthcheck + docker test), T-24-77 (`.dockerignore` test, no secret build args, `ARG` list pinned to exactly one name), T-24-78 (FROM lines untouched) and T-24-SC (no dependency change) are mitigated as planned.

## Gaps reported

- No PostgreSQL tests were run or needed.
- No DECISIONS row proposed.
- `docs/operations/RUNBOOK.md` does not yet mention the stamp (outside this plan's file list; plans 24-31/24-32 own the runbook facts above).

## Self-Check: PASSED

- Files present: Dockerfile, docker-compose.yml, deploy/update.sh, deploy/soak-image.sh, .env.example, tests/test_dockerfile_revision_stamp.py, tests/test_deploy_images.py, tests/test_deploy_compose.py, tests/test_deploy_scripts.py.
- Commits a2330ecc and 912b0197 are ancestors of HEAD.
