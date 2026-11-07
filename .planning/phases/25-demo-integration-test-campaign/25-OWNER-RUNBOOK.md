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

## 8. Campaign steps S02 to S19 (the safe order)

Run these after session 1 passed, in this order, on session dates you choose (decision Q-G; no plan sets a
date). You may stop after any step and continue in a later session from the next row. Only the last row,
S12, has a hard rule: it is the last step of its UTC day.

### 8.1 Clean-up (used by every step that says "clean-up")

Run it after any step that leaves state (catalog `leaves_state` = yes: S12, S15, S16, S18) and after any
failed or interrupted step, once the Demo UI shows no open position, order or algo order:

```powershell
$env:PYTHONPATH = "."; uv run python scripts/demo_clear.py
```

It needs `LIVE_RUNTIME_MODE=DEMO` and a database URL, asks for the phrase `DEMO IS FLAT`, refuses while an
execution intent is unresolved, closes the plan behind every open Demo approval (APPROVED to EXPIRED, one
journal row each, about 26 minutes saved) and leaves a persisted SAFE_MODE with the operator id
`owner-demo-clear`. The reservation of a closed plan is released by the live process's own sweep at its next
start, not by the script. If SAFE_MODE is still on afterwards, leave it with `/safemode_exit` and `/confirm`
on the live bot (RUNBOOK 21.1a) before the next step.

### 8.2 Step index

| Step | Id | Test file | Leaves state | Real orders on Demo |
|---|---|---|---|---|
| 1 | S06 | `tests/demo/test_demo_s06_replay.py` | no | one far resting entry, cancelled |
| 2 | S04 | `tests/demo/test_demo_s04_stop_rejected.py` | no | entry fill, one reduce-only close |
| 3 | S03 | `tests/demo/test_demo_s03_crossed_stop.py` | no | variant (ii): entry fill, one reduce-only close |
| 4 | S07 a, b, c | `tests/demo/test_demo_s07_restart_cuts.py` | no | entry, fill, stop, close; cut b leaves a real position without a stop for the restart time |
| 5 | S05 | `tests/demo/test_demo_s05_cancel_race.py` | no | one entry and its cancel |
| 6 | S02 | `tests/demo/test_demo_s02_partial_fill.py` | no | entry fill, stop, legs, close |
| 7 | S09 | `tests/demo/test_demo_s09_clock_skew.py` | no | none (nothing may be placed) |
| 8 | S17 | `tests/demo/test_demo_s17_stale_feed.py` | no | one resting entry |
| 9 | S08 | `tests/demo/test_demo_s08_stream_loss.py` | no | per the scenario; real stream reconnection |
| 10 | S10 | `tests/demo/test_demo_s10_rate_limit.py` | no | none or one far entry (see the step) |
| 11 | S19 | `tests/demo/test_demo_s19_rest_gate_cli.py` | no | one entry placed and cancelled |
| 12 | S11 | `tests/demo/test_demo_s11_db_outage.py` | no | entry fill, one reduce-only close |
| 13 | S13 | `tests/demo/test_demo_s13_margin_liquidation.py` | no | one far entry placed and cancelled |
| 14 | S14 | `tests/demo/test_demo_s14_safe_mode.py` | no | one far GTD LIMIT entry whose answer is dropped |
| 15 | S15 | `tests/demo/test_demo_s15_foreign_order.py` | yes | actor orders `t25a-`, a system entry |
| 16 | S16 | `tests/demo/test_demo_s16_manual_close.py` | yes | system entry, an actor reduce-only close |
| 17 | S18 | `tests/demo/test_demo_s18_unprotected.py` | yes | entry fill, reduce-only close after faults |
| 18 | S12 | `tests/demo/test_demo_s12_daily_stop.py` | yes | a resting entry, then DAILY_STOP |

The rows marked as blocked by an open strict-xfail twin in precondition P6 (S07 cut b, S11, S12) stay in their
place; run them after the gap is closed, or record your waiver.

### S06 Duplicate or replayed APPROVE and CONFIRM

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s06_replay.py`
- Expected result: `1 passed`. One approved far request, two concurrent CONFIRM presses through the runner's
  handler, then a replayed APPROVE and CONFIRM. Exactly one `place_entry` POST leaves the process (counted at
  the fault edge) and the journal holds one non-refused placement outcome. The resting entry is cancelled by
  its client id at the end.
- Labels: DEMO_OBSERVED (nothing is injected). Evidence: `25-DEMO-SCENARIO-EVIDENCE-S06-*.json`.
- Clean-up: none expected; after a failure see 8.1.
- Status: NOT_OBSERVED

### S04 Stop rejected after a fill, reduce-only close

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s04_stop_rejected.py`
- Expected result: `1 passed`. The stop rejection (code -2021) is injected at the adapter edge before
  anything is sent. The coordinator reacts for real: one reduce-only MARKET close under an `xc-` client id (a
  real Demo order), the plan ends FLAT, the critical alerts are journaled, SAFE_MODE is left through
  `/safemode_exit` and `/confirm`, and the account ends clean.
- Labels: DEMO_FAULT_INJECTED for the stop rejection, DEMO_OBSERVED for the close and the final state.
  Evidence: `25-DEMO-SCENARIO-EVIDENCE-S04-*.json`.
- Clean-up: after a failure close any BTCUSDT position in the Demo UI, then 8.1.
- Status: NOT_OBSERVED

### S03 Price crossed the stop before placement (-2021)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s03_crossed_stop.py`
- Expected result: `1 passed`. Variant (i): the mark the pre-placement check reads is moved past the stop at
  CONFIRM; the real check refuses and nothing is sent. Variant (ii): after a fill the stop payload is mutated to
  the wrong side of the mark and sent to Demo. The exchange's own answer (research assumption A2: -2021) is
  recorded by code and class name; it is DEMO_OBSERVED only if Binance really answered -2021, otherwise
  NOT_OBSERVED with the code recorded (outcome COMPLETE_WITH_GAPS). The coordinator then reacts as in S04
  (one reduce-only close).
- Labels: DEMO_FAULT_INJECTED for the injections, DEMO_OBSERVED for the exchange answer when it comes, else
  NOT_OBSERVED. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S03-*.json`.
- Clean-up: after a failure close any BTCUSDT position in the Demo UI, then 8.1.
- Status: NOT_OBSERVED

### S07 Restart mid-flow, the three cuts (a, then b, then c)

Each cut builds the real process, crashes it at one point (no drain, the listenKey kept) and starts a second
process over the same database and the same exchange. Three commands, one per cut:

- Cut a, before the entry answer is known:
  `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s07_restart_cuts.py -k cut_a`
  Expected: the lost answer and the failed in-process probe are injected; the second process probes once by
  client id, finds the entry and tracks it; one `place_entry` across both processes (never re-sent, D080).
  A restart that inherits SAFE_MODE ends admitted but with entries disabled (finding 25-12-F2): the scenario
  leaves SAFE_MODE with `/safemode_exit`. Labels: DEMO_FAULT_INJECTED.
- Cut b, between the fill and the stop:
  `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s07_restart_cuts.py -k cut_b`
  Expected: the stop placement is held and the process crashes; the second process protects or closes the
  position. This leaves a REAL Demo position without a stop for the restart time: do not leave the machine
  until it ends. Labels: DEMO_FAULT_INJECTED. A late restart (after `max_unprotected_ms`) is finding 25-12-F1
  (strict-xfail twin; decision question in `25-OWNER-DECISIONS.md`).
- Cut c, after the fill and the confirmed stop:
  `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s07_restart_cuts.py -k cut_c`
  Expected: the second process rehydrates the plan protected, sends nothing, and its first reconcile is clean.
  Labels: DEMO_OBSERVED.
- Every cut ends flat with a clean account. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S07-*.json` (one file per cut).
- Clean-up: after a failure close the position in the Demo UI, then 8.1.
- Status: cut a NOT_OBSERVED, cut b NOT_OBSERVED, cut c NOT_OBSERVED

### S05 Cancel racing a fill

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s05_cancel_race.py`
- Expected result: `1 passed`. The "fill" request is marketable; right after the entry is acknowledged the
  scenario sends the entry cancel of the expiry path once. The race step is DEMO_OBSERVED only if the entry
  rested (NEW) before the cancel and the exchange then showed it filled; otherwise NOT_OBSERVED with the
  observed order of events and the outcome COMPLETE_WITH_GAPS (the twin is the deterministic proof). Either
  way the fill is protected or the entry is cancelled, no second entry is placed and the account ends clean.
- Labels: DEMO_OBSERVED or NOT_OBSERVED. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S05-*.json`.
- Clean-up: after a failure close any position in the Demo UI, then 8.1.
- Status: NOT_OBSERVED

### S02 Partial fill

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s02_partial_fill.py`
- Expected result: `1 passed`, outcome COMPLETE_WITH_GAPS. Nothing is scripted: the entry fills when Binance
  fills it. Demo cannot force a partial fill, so the `partial_fill` step is expected NOT_OBSERVED with its
  reason; the protection assertions (stop after the first fill, REST-confirmed, remainder cancelled, legs sized
  from the position, flat at the end) are checked on the real fill either way. The twin is the proof of the
  partial branch (DVM-03).
- Labels: NOT_OBSERVED for the partial fill (DEMO_OBSERVED only if it really was partial), DEMO_OBSERVED for
  the protection steps. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S02-*.json`. The best-effort exchange probe is in
  section 9.
- Clean-up: after a failure close any position in the Demo UI, then 8.1.
- Status: NOT_OBSERVED

### S09 Clock skew

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s09_clock_skew.py`
- Precondition: P4 (a synchronised clock; the skew is added on top of the real offset).
- Expected result: `1 passed`. The skew (twice the larger ratified drift limit) is injected into the process
  clock only. The real drift guard measures it against Binance's server time and blocks new entries
  (`OUT_OF_LIMITS`), so a request that is approved and confirmed places nothing. Research assumption A3: the
  SDK stamps requests from the system clock, so the signed calls themselves should succeed; if Binance answers
  -1021 the scenario records that and still asserts nothing was placed. The exchange-side -1021 is the probe
  case in section 9.
- Labels: DEMO_FAULT_INJECTED for the skew, DEMO_OBSERVED for the guard's reaction. Evidence:
  `25-DEMO-SCENARIO-EVIDENCE-S09-*.json`.
- Clean-up: after a failure see 8.1 (an approved plan may stay APPROVED).
- Status: NOT_OBSERVED

### S17 Stale feed drill (G2-016)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s17_stale_feed.py`
- Expected result: `1 passed`. A mark reading older than twice the configured mark-price age is injected (nothing
  is sent for it). The process fails the market-feed health check, refuses the CONFIRM at the pre-placement
  mark gate and, with a resting entry, enters SAFE_MODE `STALE_FEED` with a STALE_DATA alert. The fault is
  cleared, the operator leaves SAFE_MODE through `/safemode_exit`, the account ends clean.
- Labels: DEMO_FAULT_INJECTED. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S17-*.json`.
- Clean-up: after a failure cancel the BTCUSDT order in the Demo UI, leave SAFE_MODE (RUNBOOK 21.1a), then 8.1.
- Status: NOT_OBSERVED

### S08 WS disconnect and listenKey expiry

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s08_stream_loss.py`
  Optional real listenKey expiry (wall-clock slow, more than the 60 minute key life; keep the machine awake):
  `$env:TRADING_DEMO_RUN="1"; $env:TRADING_DEMO_SLOW="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s08_stream_loss.py`
  (`TRADING_DEMO_SLOW` is the S08-only switch of section 5.)
- Expected result: `1 passed`. A "close" event of the current connection is posted into the supervisor's own
  listener, so the supervisor runs its own rebuild (a real keepalive, a new websocket connection, a REST
  snapshot). The states it passes through (UNKNOWN, SYNCING, LIVE) are recorded for the SAFE_MODE exit row 7.
  Without `TRADING_DEMO_SLOW=1` the real-expiry step is NOT_OBSERVED with its reason and the outcome is
  COMPLETE_WITH_GAPS. Expect the observation of finding 25-13-F1: after a recovery that halts (reconnect
  exhausted, a ban, a hard listenKey failure) nothing in `src` requests a resync, so only a process restart
  (RUNBOOK 22.5) recovers the stream.
- Labels: DEMO_FAULT_INJECTED for the forced drop and for the keepalive failures, NOT_OBSERVED for a real
  expiry unless the slow switch ran. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S08-*.json`.
- Clean-up: after a failure see 8.1.
- Status: NOT_OBSERVED (the slow variant: NOT_TESTED until run)

### S10 Rate limit (an injected 429 only)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s10_rate_limit.py`
- A real 429 or 418 is never provoked: the answer is raised under the real adapter before the SDK sends
  anything, with a short Retry-After derived from the loaded limits.
- Expected result: `1 passed`. The real gate records and persists the pause, the CONFIRM is refused with no
  order sent, and entries work again after the pause. The 418 variant is twin-only here; S19 runs the Demo 418
  variant and clears it at once.
- Labels: DEMO_FAULT_INJECTED (never an observed 429 or 418). Evidence: `25-DEMO-SCENARIO-EVIDENCE-S10-*.json`.
- Clean-up: after a failure see 8.1.
- Status: NOT_OBSERVED

### S19 REST gate operator commands after a false 418 (P20-DEMO)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s19_rest_gate_cli.py`
- Expected result: `1 passed`. A false 418 is injected under the real adapter (never provoked) and persisted
  by the real gate; the process is stopped in order (RUNBOOK 22.5 shape); `rest_gate_cli status` shows the
  ban; `clear` refuses the future deadline; `clear --force` writes a fresh record and its audit lines (a
  `.clear-audit.jsonl` file beside the state file); the restarted process restores a clear gate; a request is
  placed and cancelled. The commands run in process and the state file is never edited by hand.
- IF THE RUN STOPS AFTER THE INJECTION AND BEFORE THE CLEAR, the gate state file still holds a ban that lasts
  days (the real 259200 s fallback wait). Before any other scenario: stop the process, then run
  `uv run python -m src.ops.rest_gate_cli status --path <state dir>/<gate state file>` and
  `uv run python -m src.ops.rest_gate_cli clear --path <state dir>/<gate state file> --force --operator-id <id> --reason "Phase 25 S19 false restriction"`
  (RUNBOOK 21.3). Do not edit the file by hand.
- Labels: DEMO_FAULT_INJECTED. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S19-*.json` and the clear-audit file name.
  Note finding 25-14-F2: `rest_gate_cli` has no running-process check; stop the trading process first.
- Clean-up: after a failure the gate clear above, then 8.1.
- Status: NOT_OBSERVED

### S11 DB outage during a risk-reducing close

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s11_db_outage.py`
- Expected result: `1 passed`. The first stop placement after the fill is rejected at the adapter edge (-2021)
  and, at the same instant, the journal store raises `StoreUnavailable` (a test proxy over the real PostgreSQL
  store; the database itself stays up). The real process still sends ONE reduce-only MARKET close (a real Demo
  order), ends flat, writes the audit rows the journal refused to the local spill and enters SAFE_MODE
  `DB_FAILURE`. The fault is cleared, the operator leaves SAFE_MODE through `/safemode_exit`, entries work
  again and the next start replays the spill into the journal. Expect finding 25-14-F1 until it is decided:
  the coordinator's protection-transition rows are not spilled, so the closed plan's reservation stays counted
  and the next request can be refused `CLUSTER_CAP_REJECT`.
- Labels: DEMO_FAULT_INJECTED for the rejection and the journal fault, DEMO_OBSERVED for the close. Evidence:
  `25-DEMO-SCENARIO-EVIDENCE-S11-*.json`.
- Clean-up: after a failure close any BTCUSDT position in the Demo UI, then 8.1.
- Status: NOT_OBSERVED

### S13 Liquidation-guard and available-margin rejections

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s13_margin_liquidation.py`
- Expected result: `1 passed`. Two readings are injected at the adapter edge: an available balance below the
  margin the plan needs, and a leverage-bracket table whose liquidation price lies between the entry and the
  stop. The real guards refuse the CONFIRM before any entry or symbol-configuration POST. A normal request is
  then placed and cancelled. The bad-bracket case runs last and waits the `margin.max_bracket_age_ms` bound
  once, in real time (see `config/execution/execution-limits-v1.toml`; 60000 ms when this was written), so the
  run has one silent minute. The exchange-side -2019 is not part of this test: it is the probe case
  `insufficient_margin_order` (Demo-observed 2026-10-24).
- Labels: DEMO_FAULT_INJECTED for the two readings, DEMO_OBSERVED for the normal request. Evidence:
  `25-DEMO-SCENARIO-EVIDENCE-S13-*.json`.
- Clean-up: after a failure cancel any BTCUSDT order in the Demo UI, then 8.1.
- Status: NOT_OBSERVED

### S14 SAFE_MODE entry and operator exit

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s14_safe_mode.py`
- Expected result: `1 passed`. The answer of the entry POST is dropped after it was sent (the order is really
  on Demo, a GTD LIMIT far from the market) and the probe by client id fails. The real process leaves the entry
  UNKNOWN, enters SAFE_MODE `ENTRY_STATE_UNKNOWN`, keeps its reconcile and health ticks running, refuses the
  operator exit, resolves the entry through its own reconcile probe once the fault is cleared, refuses a CONFIRM
  while SAFE_MODE stands and accepts `/safemode_exit` plus `/confirm <token>` (the token lives 60 s). SAFE_MODE
  is durable on Demo, so the exit is part of the run. Note finding 25-15-F4: after the reconcile resolves the
  entry the standing reason reads `UNRESOLVED_EXECUTION_INTENT`; the journal keeps the original row.
- Labels: DEMO_FAULT_INJECTED for the dropped answer, DEMO_OBSERVED for the reaction. Evidence:
  `25-DEMO-SCENARIO-EVIDENCE-S14-*.json`.
- Clean-up: after a failure leave SAFE_MODE by hand (RUNBOOK 21.1a), cancel any BTCUSDT order in the Demo UI,
  then 8.1.
- Status: NOT_OBSERVED

### S15 Foreign order and doubled position (leaves state)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s15_foreign_order.py`
- Expected result: `1 passed`. A test actor makes REAL Demo orders on BTCUSDT outside the system: one far
  resting BUY LIMIT, then, on top of a protected system position, one marketable BUY LIMIT of the smallest valid
  size and a reduce-only MARKET close of the same quantity. The actor's client ids start with `t25a-`. Reconcile
  reports the foreign order and the doubled position, alerts and enters SAFE_MODE (it acts on nothing: findings
  25-16-F2 and 25-16-F3); the run leaves SAFE_MODE through the operator exit.
- Labels: DEMO_OBSERVED (the actor steps carry the detail "test actor"). Evidence:
  `25-DEMO-SCENARIO-EVIDENCE-S15-*.json`.
- Clean-up: ALWAYS 8.1 after this step. If the run stopped early: the actor's resting order is cancelled by its
  own id, but an actor position is NOT closed automatically: close any BTCUSDT order and position in the Demo
  UI, leave SAFE_MODE with `/safemode_exit` and `/confirm`, then 8.1.
- Status: NOT_OBSERVED

### S16 Manual close outside the system (G2-016; leaves state)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s16_manual_close.py`
- Expected result: `1 passed`. A system plan is filled and protected; then the test actor closes the whole
  position with a REAL reduce-only MARKET order made outside the system (client id `t25a-close-...`), exactly
  what you closing in the Binance UI does. The scenario reads the final status of the stop and both
  take-profit legs from the exchange and records each verbatim (the 2026-10-22 record says the closePosition
  legs ended EXPIRED, none orphaned; the status of the explicit-quantity TP1 is unrecorded). The plan ends FLAT
  with no close of the system's own, reconcile reports no divergence, no leg stays open, and a new request is
  placed once the first plan is expired (the scenario applies the same APPROVED to EXPIRED step as
  `scripts/demo_clear.py`; finding 25-16-F1: without it the symbol is blocked about 26 minutes).
- Labels: DEMO_OBSERVED. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S16-*.json`.
- Clean-up: ALWAYS 8.1 after this step; after a failure close the position and the algo orders in the Demo UI
  first.
- Status: NOT_OBSERVED

### S18 Unprotected-position drill (G2-016; leaves state)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s18_unprotected.py`
- Expected result: `1 passed`. The stop rejection (-2021) and the rejection of every reduce-only close (-2022)
  are injected at the adapter edge (nothing is sent for them). With the position open and unprotected the real
  coordinator holds CLOSE_FAILED, blocks entries, retries the close at every step and journals the critical
  alerts. `/close` then `/confirm` are sent through the real handler and the code answers
  CLOSE_ALREADY_REQUIRED (finding 25-11-F1). Then the close fault is lifted and the coordinator's own retry
  sends a real reduce-only MARKET close; the plan ends FLAT, SAFE_MODE is left through `/safemode_exit`, the
  account ends clean.
- If it fails, a real Demo position without a stop may stay open with SAFE_MODE on: the recorded failure step
  names the recovery. Close the position and orders in the Binance Demo UI, then 8.1.
- Labels: DEMO_FAULT_INJECTED for the rejections, DEMO_OBSERVED for the final close. Evidence:
  `25-DEMO-SCENARIO-EVIDENCE-S18-*.json`.
- Clean-up: ALWAYS 8.1 after this step.
- Status: NOT_OBSERVED

### S12 DAILY_STOP (run it LAST; leaves state until 00:00 UTC)

- Command: `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s tests/demo/test_demo_s12_daily_stop.py`
- Run this step last in its session and last of the UTC day: DAILY_STOP holds for the UTC day. Once the day
  state is latched, every later CONFIRM on this Demo account is refused `DAILY_STOP_BLOCK` until 00:00 UTC, so
  no other scenario can run again that day. The scenario refuses to start when the day is already latched.
- Expected result: `1 passed`. The loss rows are injected at the adapter edge, sized from the loaded daily stop
  rate and the day base the process persisted; no real loss is made. A resting entry placed before the stop is
  expected to be cancelled with the stops kept and an alert, but the code does not do that in a live process
  today (finding 25-15-F1, strict-xfail twin; the run records what it sees). A new request still gets a card
  and its APPROVE succeeds; only the CONFIRM is refused (finding 25-15-F2).
- Labels: DEMO_FAULT_INJECTED. Evidence: `25-DEMO-SCENARIO-EVIDENCE-S12-*.json`.
- Clean-up: 8.1 after this step; if the run stopped early close any open BTCUSDT order in the Demo UI first.
  The day latch itself ends at 00:00 UTC; nothing clears it earlier.
- Status: NOT_OBSERVED

## 9. S20 observation-only items (probe cases, owner opt-in)

S20 has no test and no twin. These are exchange questions only Demo can answer. Each is an opt-in case of
`scripts/demo_probe.py`, enabled by its own key in your probe limits file (DEMO-EVIDENCE-PLAN, Step 0). They
send real Demo orders and are run by you only. Command, one case at a time (the typed phrase is
`DEMO PROBE BTCUSDT`, the symbol of your file; the run needs an interactive terminal):

```powershell
uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file <owner probe limits file> --evidence-dir .planning/phases/25-demo-integration-test-campaign/evidence --only <case id> --execute
```

The probe cleans up after every case (cancel-all, one reduce-only close, verify flat) and ends `CLEANUP_FAILED`
if it cannot: then clean the account by hand and run `scripts/demo_clear.py`. An `--only` run reports
`acceptance.overall` FAIL by design; read the per-case verdicts. Run the cases in the order below, not during
a pytest session (one process per Demo account).

| Case id (key in your file) | Question | Expected | Status |
|---|---|---|---|
| `partial_fill_attempt` (`partial_fill_attempt`) | P3: can Demo produce a real partial fill (best effort) | NOT_OBSERVED is a valid result; it can stay so for ever on Demo (DVM-03) | NOT_OBSERVED |
| `entry_cancel_fill_race` (`cancel_fill_race`, needs `race_repeats`) | P7: a cancel racing a fill (best effort) | OBSERVED only if a race really happens | NOT_OBSERVED |
| `timestamp_outside_recv_window` (`recv_window_error`) | the exchange side of S09: one read-only signed GET with a stale timestamp answers -1021 | OBSERVED with the code | NOT_OBSERVED |
| `gtd_entry_expiry_status` (`gtd_expiry`, needs `gtd_lifetime_seconds` and `gtd_expiry_wait_seconds`) | A2: the terminal status of a GTD entry after its goodTillDate (DVM-22 saw NEW 840 s after expiry and no terminal status) | OBSERVED with the terminal status, or NOT_OBSERVED again; waits more than 10 minutes, so run it last of the probe cases | NOT_OBSERVED |

Items that are already recorded or permanent, with no step to run:

- A3 (closePosition legs after the position closes), B2/B3 (same-id stop re-place, -4116 and the -2013 timing)
  and the stream states of the SAFE_MODE exit row 7 are in `docs/operations/DEMO_VS_MAINNET.md` (rows DVM-19 to
  DVM-21 and DVM-25) with their evidence. S08 and S16 add system-level runs.
- A real HTTP 418 that outlasts 259200 s (DVM-28) and the 429/418 queue order against the real exchange
  (DVM-29) are permanent NOT_OBSERVED rows: the rule "a real 418 or 429 is never provoked" is the owner decision
  of 2026-10-22. They are never a step in this runbook. The injected runs of S10 and S19 are fault-injected, not
  exchange behaviour. The real -1003 text (DVM-30) can be recorded only if a ban ever happens by accident.

## 10. Optional variants (not part of any status until you run them)

All are NOT_TESTED until run. None blocks the campaign.

- Telegram transport on the VPS: re-run `uv run python -m scripts.demo_rehearsal --execute` (typed phrase
  `DEMO SMOKE BTCUSDT`) from the machine that will host the process, with the live service stopped and the
  account flat. Only on a machine that is not the Phase 16 soak host, or after you confirmed the soak finished.
- Real taps instead of the programmatic owner: add `$env:TRADING_DEMO_OWNER="console"` to any step above.
- A real PostgreSQL stop for S11 (`docker compose stop postgres` on your own machine while the close runs): the
  S11 test keeps the database up and injects the journal fault instead; this variant checks the same reaction
  against a real outage. Follow RUNBOOK 22.5 before and after, and do it only on a machine you own.

## 11. Restarts of a live process (R-22 interim)

R-22 (cancel-on-stop for the live process) is an owner decision and is open. Until it is decided, any stop or
restart of a live process during the campaign (a `live` compose service, not the pytest harness) follows
`docs/operations/RUNBOOK.md` 22.5: `/disable_entries`, then `/status` until `protections: 0 open of N tracked`,
then stop it. `deploy/update.sh` refuses while the live service runs. After the restart read `/status` before
sending any new signal. A restart you did not plan is a defect: record it in the Defects section.

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
