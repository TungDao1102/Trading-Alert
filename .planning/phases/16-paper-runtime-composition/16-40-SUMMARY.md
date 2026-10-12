---
phase: 16-paper-runtime-composition
plan: 40
subsystem: SHADOW rehearsal (O-11 iv, REV-03) - Task 1 tracer only
tags: [shadow, rehearsal, test-only, dry-run, fake-evidence, blocking-human, paper-02]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plans 16-38 (isolation proof), 16-39 (rehearsal tool), 16-33 (soak rules and image recipe), 16-20 (soak host)"
provides:
  - "evidence/16-40-rehearsal-dryrun.json: schema-valid dry-run evidence, proof_class FAKE"
affects: [16-43 (soak start)]

requirements-completed: []

status: "tracer and Task 2 done, Task 3 pending user"
actuals:
  tokens: 1500
  tasks: 1
  commits: 1
plan_head_before: 01bc1a622e9afc0a17c92351a0fb5585e640b97f
plan_head_after: cbceb9421444665da8c16092f463802bf678054a
commits: 1

key-files:
  created:
    - .planning/phases/16-paper-runtime-composition/evidence/16-40-rehearsal-dryrun.json
  modified: []

key-decisions: []

duration: ~10 min
completed: 2026-10-12
---

# Phase 16 Plan 40: Rehearsal window, Task 1 (tracer) Summary

**Status: tracer and Task 2 done (2026-10-12), Task 3 pending user. The plan is NOT complete and PAPER-02 is NOT closed by this work.** The dry-run evidence below is FAKE (virtual clock, scripted market data, fake bot): it proves the rehearsal tool works on this machine and proves nothing about the real host or real Telegram.

## What was done (Task 1, tracer)

- Ran `scripts/shadow_rehearsal.py --dry-run --out .planning/phases/16-paper-runtime-composition/evidence/16-40-rehearsal-dryrun.json`. No network, no `.env`, no Telegram, no Binance.
- The evidence file has `proof_class: "FAKE"`, `label_seen: true`, `measured_delay_seconds: 20.0` (virtual seconds), `confirmed_within_ttl: true`, `position_opened: true`, `records_written: 16`, `records_test_only: 16` (every record is test_only), `test_id: TEST-REHEARSAL-SIGNAL-0001`. It holds no secret.
- Task 1 acceptance: file exists, proof_class FAKE, record counts equal.

| Task | Commit | What |
| --- | --- | --- |
| 1 (tracer) | cbceb94 | test(16-40): dry-run rehearsal evidence, proof_class FAKE, 16 of 16 records test_only |

## Verification

- `uv run --frozen --extra dev pytest tests/test_paper_test_signal_rehearsal.py tests/test_paper_shadow_isolation.py -q -p no:cacheprovider -rs`: all passed, 1 skipped (`tests/test_paper_test_signal_rehearsal.py:563`, needs `TEST_DATABASE_URL`, not set on this machine; the PostgreSQL rehearsal test did NOT run).
- `uv run mypy src`: no issues in 183 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 526 files already formatted.
- The full suite was NOT run (memory limit, as instructed).
- The worktree had no `.venv`; `uv sync --frozen --extra dev` created it from the lockfile (no lockfile change, no new package).

## NOT RUN (pending user)

- Task 2 is DONE (user resume signal "host skipped observed", 2026-10-12): `evidence/16-40-host-skipped.md` records commit 4a16da8, image id, the SKIPPED log line and exit 0.
- Task 3: the live rehearsal with real Telegram taps (needs the soak host, the Q-L bot token, a human). `evidence/16-40-rehearsal-live.json` does not exist. Their automated `<verify>` commands will fail until the user produces those files.
- The PostgreSQL variant of the rehearsal test (no `TEST_DATABASE_URL`).

## What the user must do for Tasks 2 and 3

Both run on the soak host, in a checkout at the commit to run (clean working tree), after the allowlist commit of plan 16-42 exists (RUNBOOK 20.6: the allowlist is a source constant, so an image built earlier carries the earlier allowlist). Never paste a token, key or password into a file, a chat or a command line; the token reaches the host only through the soak env file (names in `deploy/soak.env.example`, no `BINANCE_` name). On a Telegram, Binance or network error retry once, then stop and report.

### Task 2: start gate on the real host (RUNBOOK 20.1, 20.6)

```text
deploy/soak-image.sh --dry-run
deploy/soak-image.sh
docker image inspect --format '{{.Id}}' trading-alert:<GIT_SHA>     # must equal APP_IMAGE_ID in .deploy/soak-image.env
IMAGE_TAG=<GIT_SHA> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d --no-build
deploy/compose-soak.sh ps
deploy/compose-soak.sh logs paper
```

`<GIT_SHA>` is the 40 character `GIT_SHA` recorded in `.deploy/soak-image.env`. Confirm the log line `SKIPPED (allowlist empty)`, exit code 0, and that the container stays exited (restart on-failure). Write `.planning/phases/16-paper-runtime-composition/evidence/16-40-host-skipped.md` with the headings `Commit`, `Image id`, `Log excerpt` (redacted) and `Exit code`, and the log line. Check:

```text
.venv/Scripts/python -c "import pathlib,sys; t=pathlib.Path('.planning/phases/16-paper-runtime-composition/evidence/16-40-host-skipped.md').read_text(encoding='utf-8'); m=[h for h in ('Commit','Image id','Log excerpt','Exit code','SKIPPED (allowlist empty)') if h not in t]; print(m); sys.exit(1 if m else 0)"
```

Then type "host skipped observed".

### Task 3: rehearsal with real Telegram taps (RUNBOOK 20.4, 20.3)

1. The soak runtime must be exited in SKIPPED state (Task 2), so that no other poller uses the bot token (one `getUpdates` consumer per bot token, Q-L).
2. Start a separate compose project `trading-rehearsal` with its own database volume and its own env file; never `trading-soak`, and never the soak database (T-16-92). Plan 16-53 added the wrapper `deploy/compose-rehearsal.sh` (see "Gap" below); `deploy/compose-soak.sh` refuses any other project name. Create the rehearsal env file by hand outside the checkout (mode 0600, its own `POSTGRES_*` names, a `POSTGRES_PORT` different from the soak's, the rehearsal bot names, no `BINANCE_` name, never the soak env file), stop the soak first (`deploy/compose-soak.sh stop`, no volume removal; the wrapper refuses while any `trading-soak` container runs), then:

```text
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh --dry-run up -d db-upgrade
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh up -d db-upgrade
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh ps
```

   After the rehearsal: `TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh stop` (RUNBOOK 20.4).
3. In the rehearsal environment (names only: `DATABASE_URL_SYNC` or `DATABASE_URL` pointing at the rehearsal database, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_AUTHORIZED_CHAT_ID`, `PAPER_RUNTIME_CONFIG`, `PAPER_STRATEGY_ID`, `PAPER_PARAMETER_SET_ID`; NO `BINANCE_` name), run:

```text
python scripts/shadow_rehearsal.py --live-telegram --i-am-the-operator --out <path>/16-40-rehearsal-live.json
```

   Exit codes: 0 done, 1 failed, 2 refused or usage, 3 a `BINANCE_` variable present, 4 the rehearsal already ran in this database, 5 not configured (the runtime config is not ratified or a variable is missing; the names are printed).
4. In Telegram, confirm the message shows "SHADOW - no real order" and "TEST SIGNAL", tap APPROVE, read the confirmation card, tap CONFIRM within the TTL. Let the simulated position open on live minutes, then stop the rehearsal project. The trial soak starts later from the clean `trading-soak` database (checked in plan 16-43).
5. Copy the evidence to `.planning/phases/16-paper-runtime-composition/evidence/16-40-rehearsal-live.json` and check:

```text
.venv/Scripts/python -c "import json,sys; e=json.load(open('.planning/phases/16-paper-runtime-composition/evidence/16-40-rehearsal-live.json',encoding='utf-8')); ok=e['proof_class']=='REAL_REHEARSAL' and e['label_seen'] is True and e['measured_delay_seconds']>0 and e['confirmed_within_ttl'] is True and e['position_opened'] is True and e['records_written']==e['records_test_only']; print(ok); sys.exit(0 if ok else 1)"
```

   Then type "rehearsal done".

## Gap noticed (not decided)

RUNBOOK 20.4 and the plan name the `trading-rehearsal` project but give no command or compose wrapper for starting it (only `deploy/compose-soak.sh` exists and it refuses other project names). The rehearsal entrypoint itself needs only a reachable PostgreSQL and the env names above, so the user may also run it from any environment with those, but the "own project, own volume" shape of T-16-92 is then the user's to set up. A follow-up plan could add a `deploy/compose-rehearsal.sh`; not done here (out of scope).

Update (plan 16-53): `deploy/compose-rehearsal.sh` now exists (project `trading-rehearsal`, env file from `TRADING_ENV_FILE` outside the checkout, refuses `BINANCE_` names, other project names and a running soak; `--dry-run` prints only). The commands are in Task 3 step 2 above and in RUNBOOK 20.4.

## Open question for the user (not decided, behavior unchanged)

(Answered yes by the user; implemented in plan 16-53: both modes refuse `BINANCE_*`, exit 3, names only.) Should `scripts/shadow_rehearsal.py --dry-run` also refuse `BINANCE_*` variables? Today only `--live-telegram` runs `refuse_trade_capable_env` (plan 16-39 design: the dry run uses fakes only; plan 16-38 deviation 3 recorded the same). Moving the check ahead of the mode branch in `main()` plus one test would make both modes refuse. The source was left as is.

## Deviations from Plan

None - Task 1 executed as written, with one command-form difference: the plan's `.venv/Scripts/python` did not exist in this fresh worktree, so `uv run` (and `uv sync --frozen --extra dev`) from the lockfile was used instead. The user's host commands above keep the plan's `.venv/Scripts/python` form for the check commands.

## Authentication Gates

None hit in Task 1. Tasks 2 and 3 are `blocking-human` by design (L-07) and were not attempted.

## Known Stubs

None.

## Threat Flags

None. The evidence file holds no token, key or URL.

## Self-Check: PASSED

- `evidence/16-40-rehearsal-dryrun.json` exists with proof_class FAKE; commit cbceb94 exists. STATE.md and ROADMAP.md were not touched. Tasks 2 and 3 artifacts are intentionally absent.
