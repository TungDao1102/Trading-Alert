---
phase: 24-live-runtime-composition-demo
plan: 30
subsystem: deploy
tags: [compose, env-file, secrets, WR-06, OPS-02, D-29]
requires: [24-11, 24-25]
provides:
  - "live compose service reads its own env file (TRADING_LIVE_ENV_FILE, default .env.live)"
  - ".env.live.example (names only)"
  - "closed per-service variable allow-lists tested against docker compose config"
affects: [24-35, 24-36]
tech-stack:
  added: []
  patterns: ["compose env_file long syntax with required: false", "AST scan of env readers as a drift guard"]
key-files:
  created:
    - .env.live.example
    - tests/test_live_compose_env_split.py
  modified:
    - docker-compose.yml
    - .env.example
    - .gitignore
    - .gitattributes
    - docs/operations/RUNBOOK.md
    - tests/test_deploy_compose.py
    - tests/test_env_example.py
    - tests/test_paper_runtime_compose.py
    - tests/test_deploy_docs.py
key-decisions:
  - "The live service's env_file replaces the x-app one, so it does not read the shared .env at all: the live runtime refuses start when the shadow TELEGRAM_BOT_TOKEN is present, which the shared file would deliver."
  - "TELEGRAM_AUTHORIZED_USER_IDS is listed in both the shared and the live template (same owner ids); the live copy is the one the live process reads."
metrics:
  tasks: 3
  completed: 2026-11-01
status: complete
actuals:
  tokens: 30000
  tasks: 3
  commits: 3
plan_head_before: e60011eeb21a47429b0f611d0334eb2cbe2b7275
plan_head_after: 21ade208378123ba2969381289549e70248509ba
commits: 3
---

# Phase 24 Plan 30: Live env file split Summary

The `live` compose service now reads its own optional env file (`${TRADING_LIVE_ENV_FILE:-.env.live}`, `required: false`) instead of the shared `.env`, so Binance and live-bot names reach the live container only; the collector, db-upgrade, paper and paper-pin services never receive a `BINANCE_` name, and a closed allow-list per service is enforced against `docker compose config`.

## What changed

- `docker-compose.yml`: `live` overrides the anchor's `env_file` with the live file and adds `environment: *database-env` (DATABASE_URL, POSTGRES_HOST). Header and paper comments updated (WR-06 first half done here, second half in 24-36).
- `.env.live.example` (new): `LIVE_RUNTIME_MODE=DEMO`, the DEMO key pair active (empty), the LIVE key pair commented (the live process refuses the other mode's names even when empty), `TELEGRAM_LIVE_BOT_TOKEN`, `TELEGRAM_LIVE_AUTHORIZED_CHAT_ID`, `TELEGRAM_AUTHORIZED_USER_IDS`. Names only.
- `.env.example`: Binance and live-bot names removed; the overclaim "a paper process can never pick up a live credential" replaced by the per-service rule and a pointer to the test.
- `.gitignore`: `!.env.*.example` (every real `.env*` stays ignored); `.gitattributes`: `.env.*.example` is LF.
- `tests/test_live_compose_env_split.py` (new, 28 tests): `ALLOWED_BY_SERVICE` for collector, db-upgrade, paper and live. Sources: AST scan of `os.environ` reads in `src/data/collector.py` and `src/db/alembic/env.py`, `runtime_config.ALLOWED_ENV_NAMES` for paper, the `*_VARIABLE` constants of `src/live/*.py` plus `CREDENTIAL_SPECS` (with `_FILE` variants) for live. Compose is rendered over FAKE copies of both example files in a temp directory; messages carry names only. A mutation check (removing the live `env_file`) made 4 tests fail, so the tests bite.
- Amended: `test_deploy_compose.py` (scrub `TRADING_LIVE_ENV_FILE`, live environment is only the database values), `test_env_example.py` (Binance assertions moved to the live template, shared template has none, overclaim gone, both templates tracked), `test_paper_runtime_compose.py` (every `BINANCE_` name of the live template still refuses the paper runtime: second barrier).

## Deviations from Plan

**1. [Rule 3 - Blocking] tests/test_deploy_docs.py gate and RUNBOOK**
- **Found during:** verification of the neighbouring gate tests.
- **Issue:** `test_every_compose_variable_is_documented_in_env_example` requires every interpolated compose variable to be in `.env.example` (only `TRADING_ENV_FILE` was exempt, documented in the RUNBOOK instead). The new `TRADING_LIVE_ENV_FILE` failed it.
- **Fix:** exempted `TRADING_LIVE_ENV_FILE` the same way and required its mention in the RUNBOOK; added the live env file paragraph to `docs/operations/RUNBOOK.md` (stack start paragraph; also corrects "paper is a placeholder").
- **Files modified:** tests/test_deploy_docs.py, docs/operations/RUNBOOK.md
- **Commit:** 21ade208

**2. [Plan wording] "settings classes" scan** The repo has no `BaseSettings` classes; the drift guard scans `os.environ` reads (AST), the `*_VARIABLE` constants and `ALLOWED_ENV_NAMES` instead.

**3. Shared-file names tolerated until 24-36.** The shared `.env` still delivers the backup and `OFF_HOST_BACKUP_TARGET` names to the collector, db-upgrade and paper (plan 24-36 splits them). The test keeps that as an explicit closed list, `SHARED_FILE_NAMES`, so any new name in `.env.example` fails.

## Not done (out of scope, left to later plans)

- `docs/operations/DEPLOY_GUIDE.vi.md` lines 191 and 1637 and `scripts/demo_rehearsal.py` still describe the Demo key names as living in `.env`; plan 24-36 owns scripts, cutover, drills and guides. `tests/test_deploy_guide_vi.py` passes unchanged.
- The live placeholder command is unchanged (24-35).

## Verification

- `uv run pytest -m "not docker" tests/test_env_example.py tests/test_paper_runtime_compose.py tests/test_live_compose_env_split.py tests/test_deploy_compose.py tests/test_deploy_docs.py tests/test_deploy_guide_vi.py`: all pass.
- `tests/test_soak_compose.py`, `tests/test_rehearsal_compose.py`, `tests/test_agents_md.py`: pass.
- `uv run ruff check` and `ruff format --check` on the touched test files: exit 0. `scripts/verify_decision_alignment.py all`: ALL_PASS. `pyproject.toml` and `uv.lock` unchanged.
- `docker-compose.yml`, `.env.example`, `.env.live.example` are LF; `grep -c TRADING_LIVE_ENV_FILE docker-compose.yml` = 2.
- No `TEST_DATABASE_URL` used, `.env` never read, no docker-marked test run.

## Known Stubs

None.

## Threat Flags

None.

## Self-Check: PASSED

Files found: .env.live.example, tests/test_live_compose_env_split.py, this summary. Commits 3f9b1aa6, f78f0e07, 21ade208 are ancestors of HEAD.
