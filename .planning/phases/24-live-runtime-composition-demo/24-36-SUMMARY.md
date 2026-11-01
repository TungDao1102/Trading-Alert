---
phase: 24-live-runtime-composition-demo
plan: 36
subsystem: deploy
tags: [compose, env-file, secrets, WR-06, OPS-02, D-29, backup, soak]
requires: [24-30]
provides:
  - "paper and paper-pin read their own env file (TRADING_PAPER_ENV_FILE, default .env.paper): the SHADOW Telegram names"
  - "backup and ops read their own env file (TRADING_BACKUP_ENV_FILE, default .env.backup): BACKUP_ names and OFF_HOST_BACKUP_TARGET"
  - ".env.paper.example and .env.backup.example (names only); .env.example reduced to database, cadence and image tag"
  - "closed per-service allow-lists now cover collector, db-upgrade, paper, paper-pin, backup, ops and live"
affects: [24-35]
tech-stack:
  added: []
  patterns: ["compose env_file list (shared file + optional per-service file, required: false) through YAML anchors", "one-file projects: compose_init defaults the split files to TRADING_ENV_FILE"]
key-files:
  created:
    - .env.paper.example
    - .env.backup.example
  modified:
    - docker-compose.yml
    - .env.example
    - deploy/lib.sh
    - deploy/compose-soak.sh
    - deploy/compose-rehearsal.sh
    - deploy/backup.sh
    - deploy/backup-drill.sh
    - deploy/backup-real-s3-gate.sh
    - deploy/soak.env.example
    - deploy/systemd/trading-soak-backup.service
    - docs/operations/RUNBOOK.md
    - docs/operations/DEPLOY_GUIDE.vi.md
    - tests/test_live_compose_env_split.py
    - tests/test_soak_compose.py
    - tests/test_deploy_backup_scripts.py
    - tests/test_env_example.py
    - tests/test_deploy_docs.py
    - tests/test_deploy_guide_vi.py
    - tests/docker_helpers.py
    - tests/test_docker_cutover.py
    - tests/test_docker_backup_drill.py
key-decisions:
  - "paper and backup/ops read the shared file AND their own file (list, later file wins), not their own file alone: they still need the POSTGRES_* values; the live service keeps replacing the shared file (24-30)."
  - "A project that selects its own env file with TRADING_ENV_FILE (soak, rehearsal, cutover and drill tests) stays a one-file project: deploy/lib.sh compose_init defaults TRADING_PAPER_ENV_FILE and TRADING_BACKUP_ENV_FILE to it and exports them. deploy/compose-soak.sh and deploy/compose-rehearsal.sh force them, so those projects never read the checkout's real .env.paper or .env.backup. The live file is deliberately not defaulted."
  - "deploy/backup.sh --install-soak-timer still compares the soak bucket with the trading bucket, now read from TRADING_BACKUP_ENV_FILE (default .env.backup); the trading-soak-backup unit sets TRADING_BACKUP_ENV_FILE to the soak env file."
metrics:
  tasks: 3
  completed: 2026-11-01
status: complete
actuals:
  tokens: 60000
  tasks: 3
  commits: 3
plan_head_before: 5d80a2e1e257a85ba4af6b252da97f86b6f43586
plan_head_after: c1480679a0cc5dfa2d58b5f234e6c09a6d9bc64d
commits: 3
---

# Phase 24 Plan 36: Per-service env split, second half Summary

The SHADOW Telegram names now live only in the paper services' own env file and the BACKUP_ names only in the backup and ops services' own file, so the always-on collector holds no Telegram token, no backup secret and no Binance key; the soak, rehearsal, cutover and drill projects keep working with their single env file, and the docker-marked cutover and backup-drill tests pass on the new layout.

## What changed

- `docker-compose.yml`: two anchors, `x-paper-env-files` (shared file, then `${TRADING_PAPER_ENV_FILE:-.env.paper}`) for `paper` and `paper-pin`, and `x-backup-env-files` (shared file, then `${TRADING_BACKUP_ENV_FILE:-.env.backup}`) for `backup` and `ops`. The second file of each is `required: false`, so every other compose command works without them; a missing backup file fails closed inside Python (missing BACKUP_S3_ name), a missing paper file starts the runtime without notifications. Header and paper comments updated.
- `.env.paper.example` (TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_CHAT_ID, TELEGRAM_AUTHORIZED_USER_IDS; PAPER_* selection names commented) and `.env.backup.example` (OFF_HOST_BACKUP_TARGET, every BACKUP_ name): names only, LF, tracked (`!.env.*.example` already in `.gitignore` from 24-30). `.env.example` keeps POSTGRES_*, DATABASE_URL, OI_POLL_INTERVAL_SECONDS and IMAGE_TAG, plus a pointer block naming the three per-service files and their selector variables.
- `deploy/compose-soak.sh`: when `TRADING_ENV_FILE` is set it exports `TRADING_PAPER_ENV_FILE` and `TRADING_BACKUP_ENV_FILE` equal to it (overriding inherited values), so the soak needs no new operator file. `deploy/compose-rehearsal.sh` does the same with its rehearsal file.
- `deploy/lib.sh` `compose_init`: when `TRADING_ENV_FILE` is set and the paper or backup variable is not, it defaults to `TRADING_ENV_FILE` and is exported. Production (`TRADING_ENV_FILE` unset) is unchanged: `.env` plus `.env.paper` / `.env.backup`.
- `deploy/backup.sh`: `check_init_remote_mode` reads `BACKUP_REMOTE` from `TRADING_BACKUP_ENV_FILE` (else `TRADING_ENV_FILE`, else `.env.backup`); `check_soak_bucket` compares against `TRADING_BACKUP_ENV_FILE` (default `.env.backup`). Refusal rules and name-only messages unchanged. `backup-drill.sh` and `backup-real-s3-gate.sh` headers (their `--help`) describe the backup env file. `deploy/systemd/trading-soak-backup.service` also sets `TRADING_BACKUP_ENV_FILE=@SOAK_ENV_FILE@`; `trading-backup.service` is byte-unchanged.
- `deploy/soak.env.example` header updated (single soak file serves paper, backup and collector).
- Tests: `tests/test_live_compose_env_split.py` (44 tests; `SHARED_FILE_NAMES` reduced, `PAPER_FILE_NAMES`, `BACKUP_FILE_NAMES`, `ALLOWED_BY_SERVICE` now has paper, paper-pin, backup, ops; new checks that the collector holds no `BACKUP_`/`BINANCE_`/`TELEGRAM_` name, each moved name is active in exactly one example, selector variables move the file, files optional); `tests/test_soak_compose.py` (wrapper exports, paper services share the list, template names); `tests/test_deploy_backup_scripts.py` (backup file decides, shared file ignored, value never printed, headers/help, `compose_init` defaults, soak unit); `tests/test_env_example.py`, `tests/test_deploy_docs.py` (four selector variables exempt from the shared template, required in the RUNBOOK), `tests/test_deploy_guide_vi.py` (known variable names include every `.env.*.example`).
- Docs: RUNBOOK (stack paragraph, 11.1 step 3, 11.3, key custody, local-only mode, restore prerequisites, soak sections) and `DEPLOY_GUIDE.vi.md` (steps 2.5, 6.1, 4 step 6, restore prerequisites, telegram variables, soak, troubleshooting, checklist, WR-06 sentence now says the split is done; the Demo key sentence points to `.env.live`).

## Deviations from Plan

**1. [Rule 3 - Blocking] `deploy/lib.sh` one-file default (file not listed in the plan)**
- **Found during:** Task 2/3, reading the RUNBOOK soak commands and the cutover/drill test helpers.
- **Issue:** The soak and drill procedures run `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup.sh ...` and the docker tests build projects with one env file holding every name. After the split the backup container would have read the checkout's own `.env.backup` (the production bucket!) instead, so a soak `--init-remote` could have used the trading bucket.
- **Fix:** `compose_init` defaults the two split variables to `TRADING_ENV_FILE` (tests added). Production is unaffected.
- **Files modified:** deploy/lib.sh, tests/test_deploy_backup_scripts.py
- **Commit:** c1480679

**2. [Rule 3 - Blocking] Test helpers and gates outside `files_modified`**
- `tests/docker_helpers.py` (`ComposeProject.compose` env), `tests/test_docker_backup_drill.py` (`_wrapper` env), `tests/test_docker_cutover.py` (`_compose_prefix`) pass the project file as the paper and backup file so the cutover and drill run "the way the cutover runs them". `tests/test_deploy_docs.py` and `tests/test_deploy_guide_vi.py` gates broke on the split (undocumented selector variables, BACKUP_ names no longer in `.env.example`); fixed in scope with RUNBOOK and guide edits. Commit c1480679.

**3. Plan wording: "keep their mode-0600 checks"**
- `deploy/backup.sh`, `backup-drill.sh` and `backup-real-s3-gate.sh` contain no file-mode check (only `bootstrap.sh` checks the mode of `.env`); there was nothing to keep and none was added. Mode 0600 is stated in both new example headers and the RUNBOOK; creating `.env.paper` / `.env.backup` with that mode on the host is an owner step (bootstrap installs only `.env`).

**4. `scripts/demo_rehearsal.py` not changed**
- It reads its five credentials from the process environment only ("no file is read"), names no env file, and is unaffected; the earlier "describes the keys as living in `.env`" worry from 24-30 applied to the Vietnamese guide only (fixed: step 2.5 and the WR-06 sentence).

## Known residual (not a regression)

- In the soak project the single soak env file is the shared, paper and backup file, so every soak service (collector included) still holds every name of that file. The plan chose this ("the soak needs no new operator file"); production does not have it.
- `deploy/migrate.sh` runs compose with `--project-directory` on each host: the NEW host needs `.env.backup` (with the BACKUP_ names) next to its checkout before a cutover, the old host's checkout is the pre-split compose file and is untouched.

## Verification

- `uv run pytest -m "not docker" tests/test_live_compose_env_split.py tests/test_soak_compose.py tests/test_deploy_backup_scripts.py tests/test_env_example.py tests/test_cutover.py tests/test_deploy_compose.py tests/test_deploy_docs.py tests/test_deploy_guide_vi.py tests/test_rehearsal_compose.py tests/test_agents_md.py`: all pass (no skips; `docker compose config` ran).
- Also pass: `tests/test_bootstrap.py`, `test_deploy_heartbeat.py`, `test_deploy_migrate.py`, `test_deploy_scripts.py`, `test_soak_runbook.py`, `test_paper_runtime_compose.py`, `test_demo_rehearsal_*`, `test_paper_test_signal_rehearsal.py` (a few existing infra skips).
- `uv run pytest -m docker tests/test_docker_cutover.py tests/test_docker_backup_drill.py -x`: 10 passed in 239.57 s against the local Docker Desktop daemon (real run, observed on this machine).
- `shellcheck -S warning deploy/*.sh`: exit 0 (info-level SC1091 only without `-x`). Edited scripts and examples are LF.
- `uv run ruff check` and `ruff format --check` on the touched test files: exit 0. `scripts/verify_decision_alignment.py all`: ALL_PASS. `git diff --exit-code -- pyproject.toml uv.lock`: exit 0.
- No `TEST_DATABASE_URL`, `.env` never read, no secret value written; fake values only in tests.

## Owner checklist (NOT_OBSERVED here; owner-run)

- Production host: before the next `deploy/update.sh` (it runs a backup) or timer run, move every `BACKUP_*` name and `OFF_HOST_BACKUP_TARGET` from `/opt/trading/.env` to `/opt/trading/.env.backup` (mode 0600, owner `trading`), the shadow Telegram names to `/opt/trading/.env.paper`, and delete them from `.env`. NOT_OBSERVED: no host command was run.
- Soak host: re-run `sudo deploy/backup.sh --install-soak-timer --soak-env-file <path>` so the installed `trading-soak-backup.service` gains the `TRADING_BACKUP_ENV_FILE` line. NOT_OBSERVED.
- Real-host cutover (`deploy/migrate.sh`) with the new layout, the restore drill and the D064 real-S3 gate stay owner-run: only the local docker-marked cutover and drill tests were run.
- Optional follow-up for a later plan: teach `deploy/bootstrap.sh` to install `.env.paper` / `.env.backup` with mode 0600 (it only installs `.env` today).

## Known Stubs

None.

## Threat Flags

None. Threat register T-24-97 (collector holds no backup key or Telegram token: per-service files and allow-list tests), T-24-98 (backups and soak still work: scripts updated, cutover and drill tests re-run), T-24-99 (modes: documented in the examples; no check existed to loosen), T-24-SC (`pyproject.toml` and `uv.lock` unchanged).

## Self-Check: PASSED

Files found: .env.paper.example, .env.backup.example, this summary. Commits 1b37342a, a84aa9b7, c1480679 are ancestors of HEAD.
