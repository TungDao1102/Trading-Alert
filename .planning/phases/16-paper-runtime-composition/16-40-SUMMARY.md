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

status: "all three tasks done; live rehearsal passed on attempt 3 (2026-10-12)"
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

**Status: tracer, Task 2 and Task 3 done (2026-10-12). PAPER-02 is NOT closed by this work (it needs the soak evidence, SC9).** The dry-run evidence below is FAKE (virtual clock, scripted market data, fake bot): it proves the rehearsal tool works on this machine and proves nothing about the real host or real Telegram.

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
- Task 3 is DONE: `evidence/16-40-rehearsal-live.json` (attempt 3, 2026-10-12, user ran `scripts/shadow_rehearsal.py --live-telegram --i-am-the-operator`; proof_class REAL_REHEARSAL, label_seen true, measured_delay_seconds 5.619, confirmed_within_ttl true, position_opened true, 16 records all test_only; the plan's automated check printed True). Attempt 1 stopped on the poller defect (partial evidence kept by the user outside the repo as 16-40-rehearsal-live-attempt1-partial.json) and attempt 2 on the CONFIRM stamp defect (no evidence written); both are recorded in the section 'Gap found by the live rehearsal 2026-10-12' and fixed (b098c2f, a5fad73, d08ab96, 263fe70). In the passing run confirm_requested_at_utc equals approval_acted_at_utc. The user's statement is that the rehearsal ran against the separate rehearsal project and database; the orchestrator did not observe the Telegram messages.
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

## Gap found by the live rehearsal 2026-10-12

**Gap against plans 16-26 / 16-31 (live minute poller), not a deviation of this plan's own tasks.**

- **Defect:** after a CONFIRM the fill-eligibility start (`since_utc`) is the minute AFTER the confirm minute (Q-B), which is later than the poll horizon (`now_utc - close_lag`). `LiveMinutePoller._fetch` used that as the cursor and `_page` called the public feed with `start_ms > end_ms`. The rehearsal and the SHADOW runtime stopped right after the first CONFIRM. The same happened on a later poll whose next cursor (last stored minute + 1) was past the horizon.
- **Why the tests missed it:** the `FakeFeed` in `tests/test_paper_live_minutes.py` never rejects `start > end`.
- **Assumption, NOT verified live:** that Binance answers `start > end` with HTTP 400 (the SDK's BadRequestError), a non-transient error that propagates. The diagnosis came from the code and the stopped runs, not from a live reproduction.
- **Fix (TDD):** RED `b098c2f` (3 tests; a `StrictFeed` raises on `start_ms > end_ms`) then GREEN `a5fad73`: `_fetch` returns an empty list before any page call when `cursor > horizon`. A poll in that state stores nothing, reports 0/0 added and `settled_through_utc == horizon`. Retry/transient behaviour, paging, validation and the `close_time_utc <= horizon` filter are unchanged; no float and no clock read were added.
- **Other callers examined (no change needed):** `shadow_runtime._refresh_mark` and `rehearsal.observed_reference_price` send `start_ms=None`; `shadow_runtime._funding_range` (used by `_funding_history` and `_restore_positions`) starts at `since - 2 * (8 h + 60 s)`, so its start cannot pass `until` (the horizon) for an eligibility start about one minute ahead; `_restore_positions` calls the same poller, so it is covered by the fix.
- **Tests:** `tests/test_paper_live_minutes.py` 25 passed, `tests/test_paper_test_signal_rehearsal.py` 23, `tests/test_paper_shadow_runtime.py` 50, `tests/test_paper_shadow_runtime_pg.py` 2 (no failures); ruff check, ruff format --check and mypy on `src/paper/live_minutes.py` clean.

### Second item: the CONFIRM card was stamped before the approval it follows

**Gap against plan 16-11 (`approved_handler`), found by the same live rehearsal.**

- **Evidence:** in attempt 1 `approval_acted_at_utc` = 16:28:57.805006 and `confirm_requested_at_utc` = 16:28:57.804910 (96 microseconds earlier). Attempt 2 raised `ValueError("confirm_requested_at_utc is before the approval acted_at_utc")` at the end of the run (`rehearsal.run_rehearsal -> paper_records -> records_for -> _approved_records -> assemble_paper_record -> journal._confirm_timestamps`).
- **Root cause (read from the code):** `on_callback` reads the clock once (`callback_at_utc`, `telegram_callbacks.py` line 777). `approved_handler` issued the card at that time (`now = press.callback_at_utc`). But the approval is stamped later: `ShadowApprovalBook.dispatch` (`shadow.py`) reads `self._clock()` again, inside the worker thread started by `ShadowRuntime._dispatch`, and passes it as `now_utc` to `dispatch_callback` -> `resolve_callback`, which stores it as `acted_at_utc` (`replay.py` `effective_now`). With a real clock the second read is later than the first; the offline tests use one fixed clock, so both were equal and the strict `issued < acted` check never tripped.
- **Fix (TDD):** RED `d08ab96` (4 parametrized cases through the real `on_callback` + `approved_handler` + `assemble_paper_record`, plus a repeated-APPROVE case; the Harness gets a `dispatch_lag` that models the second clock read; it fails with the live `ValueError`), then GREEN `263fe70`: the card is issued at `max(press.callback_at_utc, approval.acted_at_utc)`. `journal._confirm_timestamps` is untouched and still strict; the CONFIRM TTL (60 s), approval and replay semantics are unchanged. The card text, `expires_at_utc` (issued + TTL) and the journaled `confirm_requested_at_utc` all derive from that one stamp. Unchanged cases (acted_at equal to or earlier than the press time) still issue at the press time.
- **Other places examined:** the repeated-APPROVE replay path returns the existing entry and keeps its stamp (covered by a test); SKIP issues no card, so it has no such pair; `confirmed_at_utc` comes from the later CNF press (`press.callback_at_utc`) and is checked against the card stamp (`confirmed < issued`), which a human-delay press cannot violate; the restart sweep and `_sweep_orphans` use `acted_at_utc` only as a TTL base.
- **Tests:** `tests/test_paper_shadow_confirm.py` 54 passed (5 new), with buttons 31, test_signal_rehearsal 23, shadow_runtime 50, shadow_runtime_pg 2, shadow_pg 4, approval_delay_measured 37, journal_failure_paths 7, journal_ids 30; ruff check, ruff format --check and mypy on `src/paper/shadow_confirm.py` clean.

## Authentication Gates

None hit in Task 1. Tasks 2 and 3 are `blocking-human` by design (L-07) and were not attempted.

## Known Stubs

None.

## Threat Flags

None. The evidence file holds no token, key or URL.

## Self-Check: PASSED

- `evidence/16-40-rehearsal-dryrun.json` exists with proof_class FAKE; commit cbceb94 exists. STATE.md and ROADMAP.md were not touched. Tasks 2 and 3 artifacts are intentionally absent.
