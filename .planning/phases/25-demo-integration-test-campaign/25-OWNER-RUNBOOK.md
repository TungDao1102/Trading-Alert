# Phase 25 owner runbook (plan 25-18; CONTEXT D-01, D-05 to D-07)

Written by the assistant (Claude Sonnet 5.5) on 2026-11-08. Everything here that sends a request to Binance
Demo is owner-only: it needs your Demo account, your live Telegram bot and your database. The assistant never
runs `pytest -m demo`, never runs any `--execute` script, never reads `.env` and never touches mainnet.
Live placement stays disabled (`LIVE_ORDERS_DISABLED`). Nothing below is recorded as observed until you run
it and bring the evidence back (plan 25-20 records it). Labels for results: demo-observed or
fault-injected on Demo, never mainnet.

This file holds the campaign checklist (criterion 1 and criterion 2 of the phase). The decisions you owe are
in `25-OWNER-DECISIONS.md`. The soak (criterion 3) gets its own "Soak (owner)" section from plan 25-24, after
the campaign; do not start a soak from this file.

## 1. Who runs what

| Who | What |
|---|---|
| You (owner) | every `pytest -m demo` run, every `scripts/demo_probe.py --execute`, `scripts/demo_clear.py`, every host or database command, every Telegram tap you choose to make, the session dates (decision Q-G) |
| The assistant | wrote the scenarios and their CI twins on fakes, reads the evidence files you return, copies your results into the Results section below, lists defects, and proposes fixes as plans |

The twin of each scenario (a fake-exchange test, `tests/test_demo_twin_*.py`) runs in CI and proves the logic.
The Demo run only adds what a fake cannot: real Demo order ids, real stream behaviour, real database stores.
A twin step is labelled SYNTHETIC and is never a Demo result.

## 2. Rules for every step

- Never paste a key, secret, token, password, heartbeat URL, host name or IP address into chat, a commit, a
  log or an evidence note. Send only the evidence the "Evidence to bring back" lines name. Variable names are
  fine; values never.
- Status values: `NOT_OBSERVED` (not run), `demo-observed` (run by you, evidence returned), `FAILED` (run;
  say what you saw), `WAIVED` (you chose to skip; say why), `NOT_TESTED` (an optional variant not run). The
  status says whether the run happened. The label inside the evidence file says what it shows:
  `DEMO_OBSERVED` (the exchange produced it), `DEMO_FAULT_INJECTED` (the trigger was injected at a test
  seam, the reaction is real), `NOT_OBSERVED` (the exchange never produced it), `SYNTHETIC` (a fake).
  An injected trigger is never exchange behaviour.
- A real HTTP 418 or 429 is never provoked, by anything in this file (owner decision 2026-10-22). Both are
  injected at a test seam (S10, S19). If a real 418 or 429 happens by accident, stop, save the answer text as
  evidence before anything else, and wait out the Retry-After the evidence records.
- One Demo account has one user-data listenKey. Never run two things on the account at once: not two pytest
  runs, not the paper soak next to a session, not the rehearsal script next to a session.
- Never run `pytest -m demo` with `-n` or with xdist: the guard refuses it.
- If any step fails or you stop it half way, do not start the next one. Close any open BTCUSDT position and
  order in the Binance Demo UI first, then clean up as the step says (usually `scripts/demo_clear.py`).

## 3. Sequencing (research order; keep it)

1. Twins green and no strict-xfail twin before any session (section 4, P6). Fix first, observe second.
2. No soak on the same Demo account during a session: the listenKey is a singleton and a defect found in a
   session restarts the soak clock. Sessions, then fixes, then the soak registration (plan 25-24), then the
   soak.
3. The step order of section 8 is the safe order: no-position scenarios first, scenarios that open a real
   position next, scenarios that leave state last. S12 is last: DAILY_STOP holds until 00:00 UTC, so no
   other scenario can run again on that account that UTC day.
4. Stopping a live process on purpose follows `docs/operations/RUNBOOK.md` 22.5 (R-22 stays an owner
   decision): send `/disable_entries`, send `/status` until it shows `protections: 0 open of N tracked`,
   only then stop it. The pytest harness stops its own process in order; this rule is for a live service you
   run yourself, and for any restart you add on top of a step.
5. Where to run: on the machine that ran the 2026-11-06 smoke (the dev machine) or on a Demo-only machine.
   The single EC2 host also runs the Phase 16 paper soak. Nothing in this campaign may deploy to, restart or
   run anything on that host until you have confirmed that the Phase 16 soak has finished. Never put a
   `BINANCE_` name into the soak's env files: the paper runtime refuses to start with one.

## 4. Preconditions

Do these once before session 1 and re-check the clock and the account before every session.

| # | Precondition | Check (no secret in it) | Status |
|---|---|---|---|
| P1 | The Phase 24 owner steps (plan 24-33) are done, or you waived the ones this campaign location does not need. The campaign needs: your Demo key without withdrawal permission, the live Telegram bot, a Demo database. Record which steps you waived in the Results section. | `24-OWNER-RUNBOOK.md` sections B to E | NOT_OBSERVED |
| P2 | The process environment holds these names (values never leave your machine): `LIVE_RUNTIME_MODE=DEMO`, `BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_API_SECRET`, `TELEGRAM_LIVE_BOT_TOKEN`, `TELEGRAM_LIVE_AUTHORIZED_CHAT_ID`, `TELEGRAM_AUTHORIZED_USER_IDS`, and `DATABASE_URL` (or `DATABASE_URL_SYNC`). No `BINANCE_LIVE_*` name, no `TELEGRAM_BOT_TOKEN` (the shadow bot). The tests do not read `.env`: set the names in the shell. | the names-only command printed under this table | NOT_OBSERVED |
| P3 | The Demo database is migrated and is your own Demo database, never the soak host's database and never the `_test` database of the pytest suite. | `$env:DATABASE_URL` set to the Demo database, then `uv run alembic upgrade head` (it ends at the current head) | NOT_OBSERVED |
| P4 | The machine clock is synchronised. The drift guard blocks entries beyond +500 ms ahead of or -1000 ms behind Binance; S09 injects a skew on top of the real offset, so a bad clock spoils it. | Windows: `w32tm /query /status`; a Linux Demo machine: `chronyc tracking` | NOT_OBSERVED |
| P5 | Nothing else runs on the Demo account or with the live bot token: the `live` compose service is stopped, no rehearsal, no probe, no paper soak on the same key. | `docker compose --profile live ps` on a machine you own (not the soak host) shows no running `live` service | NOT_OBSERVED |
| P6 | The CI twins are green and no strict-xfail twin is open. | (a) `uv run pytest -m "not docker" tests/test_demo_twin_*.py tests/test_phase25_gate.py -p no:cacheprovider` is green; (b) `uv run python -c "import pathlib; hits=[p.name for p in sorted(pathlib.Path('tests').glob('test_demo_twin_*.py')) if 'xfail' in p.read_text(encoding='utf-8')]; print(hits)"` prints `[]`. When this runbook was written three strict-xfail twins were open (S07 cut b, S11, S12: findings 25-12-F1, 25-14-F1, 25-15-F1 in `25-DEFERRED.md`, questions in `25-OWNER-DECISIONS.md`). Either close them first, or waive that scenario step in the Results section with your reason. | NOT_OBSERVED |
| P7 | Plans 25-03 (pool timeout wrapped as `StoreUnavailable`) and 25-04 (health tick journal volume) are landed. | `uv run pytest tests/test_persistence_pool_timeout.py tests/test_live_health_journal_volume.py -p no:cacheprovider` is green (the pool test needs `TEST_DATABASE_URL`; without it the file skips: set it to see a real result) | NOT_OBSERVED |
| P8 | First install only: the kill-gate state of this machine does not exist yet. Set `TRADING_DEMO_INITIALIZE_GATE_STATE=1` for the first session on a fresh state directory and never otherwise: the start sequence refuses it when the state exists. Only the first process of the session uses it; a restart never does. | the S01 run tells you if the state is missing | NOT_OBSERVED |
| P9 | The Demo account is flat at the start of every session: no open order, no algo order, no position, no open approval. | Binance Demo UI, then `scripts/demo_clear.py` (section 8, "Clean-up") | NOT_OBSERVED |

Names-only check for P2 (PowerShell; it prints variable names, never values):

```powershell
Get-ChildItem Env: | Where-Object Name -match '^(BINANCE_|LIVE_RUNTIME|TELEGRAM_|DATABASE_URL)' | Select-Object -ExpandProperty Name
```

For the S20 probe cases (section 9) you also need your probe limits file (DEMO-EVIDENCE-PLAN, Step 0), with the
keys of the cases you run set to `true`.

## 5. Command form

Windows PowerShell, from the repository root. One file per step; the run prints the path of the evidence file
it wrote and, at the end of the session, the path of the session index.

```powershell
$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s <test file>
```

`-p no:xdist` and `-s` are required (the guard refuses xdist; `-s` shows the progress lines). To select one
test of a file add `-k <word>`. Two optional switches, off by default:

| Variable | Effect | Used by |
|---|---|---|
| `TRADING_DEMO_OWNER=console` | you tap APPROVE and CONFIRM on the real live bot (the Phase 24 console owner); the default presses through the bot's own callback handler, the same handler Telegram polling calls | any step; it proves the Telegram transport |
| `TRADING_DEMO_SLOW=1` | S08 also runs the real listenKey expiry (keepalive failures injected for more than the 60 minute key life; wall-clock slow) | S08 only |

Where the evidence goes: `.planning/phases/25-demo-integration-test-campaign/evidence/`. One file per scenario
run named `25-DEMO-SCENARIO-EVIDENCE-<id>-<UTC stamp>.json` (a counter suffix on a repeat; never overwritten),
and one session index per pytest session, `25-DEMO-SESSION-INDEX-<UTC stamp>.json` with a `.md` table beside
it. The evidence is scrubbed before and after writing and holds exchange order ids, never a secret. A test that
fails still writes its file with outcome FAILED.

## 6. Session 1: preflight and happy path

Goal: prove that the pytest harness itself, the production assembly and your environment work on Demo before
any fault is injected. Run S00, then S01, in one pytest session if you like (two commands are fine).

### S00 Preflight (no order, no network call)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s00_preflight.py`
- Preconditions: P1 to P5.
- What it does: checks that the process environment is admitted as a DEMO run (no LIVE name, the Demo
  credentials present, no `NOT_CONFIGURED` limit) and that the host constant is the Demo Trading host. It sends
  nothing.
- Expected result: `1 passed`. A refusal names variables, never values; fix the named variable and rerun.
- Evidence file pattern: none (S00 writes no scenario file); bring the pytest summary line.
- Expected labels: none.
- Cleanup: none.
- Status: NOT_OBSERVED

### S01 Happy path

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s01_happy.py`
  (first install only: also `$env:TRADING_DEMO_INITIALIZE_GATE_STATE="1"`; optional `$env:TRADING_DEMO_OWNER="console"`
  if you want to tap on the real bot, as in the 2026-11-06 smoke)
- Preconditions: S00 passed; P6 and P9 (clean account: a dirty start stops with the `scripts/demo_clear.py`
  instruction before anything is placed).
- What it does: builds the real live process on Demo through the production assembly, runs the start sequence,
  one signal, the approval card, APPROVE, CONFIRM, a GTD LIMIT entry, the fill on the user-data stream, the
  REST-confirmed stop and the take-profit legs, a clean reconcile, restart rehydrate, replayed presses that place
  nothing, the close and the clean-up. The 2026-11-06 `demo_rehearsal --execute` smoke already showed this
  (21 of 21 steps); this run proves the pytest harness on Demo.
- Expected result: `1 passed`; outcome COMPLETE (or COMPLETE_WITH_GAPS with the named gap) in the evidence
  file; the account is flat afterwards; the session index is printed at the end.
- Evidence file pattern: `25-DEMO-SCENARIO-EVIDENCE-S01-*.json` and `25-DEMO-SESSION-INDEX-*`.
- Expected labels: DEMO_OBSERVED on the steps (the health verdict is recorded as a fact; the live process
  reports the candle check DEGRADED by construction, see decision Q-C; the harness does not judge it).
- Cleanup: none expected. If the run stopped early: close any BTCUSDT position and order in the Binance Demo
  UI, then `scripts/demo_clear.py` (section 8, "Clean-up").
- Status: NOT_OBSERVED

## 7. What to bring back after every session

Reply with (no secrets):

1. The path of the session index (`25-DEMO-SESSION-INDEX-<UTC stamp>.json`).
2. The path of every evidence file the session wrote (the index lists them).
3. For each step: its status (`demo-observed`, `FAILED`, `WAIVED`) and the outcome line of the evidence file.
4. Anything left on the account or in the database (an open position, an order, SAFE_MODE still on, a
   persisted DAILY_STOP) and whether `scripts/demo_clear.py` was needed.
5. Anything that surprised you, in one line each (for example a card that did not arrive, a long wait).
6. Which host you ran on and whether the Phase 16 soak host was left untouched.

The assistant copies your reply verbatim into "Results (owner run)" below and sets a status only from your reply
and the evidence files; a step with no evidence stays NOT_OBSERVED.

<!-- gsd:write-continue -->

## Evidence template

Copy one row per step you ran into the Results section.

| Step | Status | Date (UTC) | Run on | Evidence (path, journal row id, or the pasted output) | What you saw (one line) |
|---|---|---|---|---|---|
| e.g. S01 | demo-observed | 2026-11-DD | dev machine | evidence file path and the session index path | outcome COMPLETE, account flat |

## Results (owner run)

Empty until you reply with the step outcomes and evidence paths (or "partial: steps N..M" with what remains).
Plan 25-20 copies your reply here verbatim. Nothing in this file counts as observed before that.

## Defects

One row per defect found by a session. A defect is a step that failed, a behaviour that contradicts the plan or
a finding you decide to fix. `OPEN` rows block the soak registration (plan 25-24). The gap plan is the plan
that closes it.

| Defect id | Scenario | Symptom | Status (OPEN or FIXED) | Gap plan |
|---|---|---|---|---|
