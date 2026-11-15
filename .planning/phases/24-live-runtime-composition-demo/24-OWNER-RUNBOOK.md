# Phase 24 owner runbook (plan 24-33, D-32, D-33)

Everything here is owner-only: it needs your Binance Demo account, your Telegram accounts, the
healthchecks.io account and the VPS. The assistant never runs these steps, never runs
`scripts/demo_rehearsal.py --execute`, and never reads `.env`. Nothing below is recorded as
observed until you run it and bring the evidence back (plan 24-33 Task 2). Label for results:
demo-observed (not mainnet). Live placement stays disabled (`LIVE_ORDERS_DISABLED`).

Rules for every step:

- Never paste a key, token, password, heartbeat URL or IP address into chat, a commit or a log.
  Send only the evidence the "Evidence" column names.
- Status values: `NOT_OBSERVED` (not run), `demo-observed` (run by you, evidence returned),
  `FAILED` (run, with what you saw), `WAIVED` (you chose to skip, with the reason).
- REQUIRED steps close Phase 24; OPTIONAL steps are recommended but do not block it.
- Reference sections: `docs/operations/RUNBOOK.md` 13 (host bootstrap), 17 (real-host rows),
  11.9 (heartbeat), 21 (operator commands), 22 (live process).

## A. Already observed (no action)

| # | Step | Required | Status | Evidence |
|---|---|---|---|---|
| A1 | Demo smoke rehearsal `uv run python -m scripts.demo_rehearsal --execute` on the dev machine: start sequence, card, APPROVE, CONFIRM, GTD LIMIT entry fill, REST-confirmed stop and TP legs, clean reconcile, restart rehydrate, replays place nothing, operator close, reservation released, account clean, SAFE_MODE drill and owner exit | REQUIRED | demo-observed on the dev machine 2026-11-06 (not mainnet, not on the VPS): outcome COMPLETE, 21 of 21 steps PASSED | `.planning/phases/24-live-runtime-composition-demo/evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json` (committed `e97198f2`) |

Prerequisites you learned on the dev machine (apply again before any rehearsal re-run):

- The host clock must be NTP-synchronised. The drift guard blocks new entries beyond +500 ms
  ahead or -1000 ms behind Binance, and the rehearsal stops at the start when it blocks. On
  Windows check `w32tm /query /status`; on the VPS `chronyc tracking`.
- Run `scripts/demo_clear.py` first (Windows: `$env:PYTHONPATH = "."; uv run python scripts/demo_clear.py`,
  phrase `DEMO IS FLAT`) after closing every Demo position and order. It closes stale plans so a
  new card is not blocked for about 26 minutes.

## B. Host (VPS)

| # | Step | Required | Command (no secret in it) | Expected result | Evidence to bring | Status |
|---|---|---|---|---|---|---|
| B1 | Prepare the host and the files off-host (RUNBOOK 13.1, 13.2): provider disk encryption on, root SSH key login works, secrets file built from `.env.example` (no `change_me`), authorized key file | REQUIRED | `ssh-keygen -l -f authorized_keys` (on your workstation) | the key file is accepted | "done", and whether provider disk encryption is on | NOT_OBSERVED |
| B2 | Bootstrap dry run, then the real run (RUNBOOK 13.3, 13.4) | REQUIRED | `sudo deploy/bootstrap.sh --dry-run --secrets-file /root/secrets.env --repo <repo-url> --ref <tag-or-commit> --authorized-keys /root/authorized_keys`, then the same without `--dry-run` | the dry run prints an ordered plan; the real run ends with the operator checklist (13.5) and no error | the last 30 lines of the real run (no values are printed) | NOT_OBSERVED |
| B3 | Real-host rows of RUNBOOK 17 (G3-033): Docker apt install, ufw, sshd drop-in `00-trading-hardening.conf` winning, chrony replacing `systemd-timesyncd`, Docker plus ufw egress | REQUIRED | `docker --version`, `sudo ufw status verbose`, `sudo sshd -T`, `chronyc tracking`, `docker run --rm hello-world` | Docker runs; ufw active; `sshd -T` shows `passwordauthentication no` and `permitrootlogin no`; chrony offset under 100 ms; container egress works | the output of those commands | NOT_OBSERVED |
| B4 | Second SSH session as `trading` with your key, plus `sudo -v` there, before closing the first | REQUIRED | `ssh trading@<host>` then `sudo -v` | both succeed | "done" | NOT_OBSERVED |
| B5 | NTP drift monitoring: confirm the host clock stays within the drift guard limits | REQUIRED | `chronyc tracking` and, a day later, `chronyc sourcestats` | system time offset well under 500 ms | both outputs | NOT_OBSERVED |
| B6 | Backup timer fires and catches up (RUNBOOK 11.3) | REQUIRED | `sudo deploy/backup.sh --install-timer`, then `systemctl list-timers trading-backup.timer` and, after the next 03:15 UTC (or a reboot), `journalctl -u trading-backup` | the timer is listed; one run completed; `Persistent=true` catches up after downtime | the `list-timers` line and the journal tail | NOT_OBSERVED |
| B7 | One real `deploy/migrate.sh`, or an explicit waiver (RUNBOOK 15, 19) | OPTIONAL | `deploy/migrate.sh --dry-run` first | exit 0 (clean) or a recorded waiver | exit code and report, or "waived: <reason>" | NOT_OBSERVED |

## C. Keys, bots and env files

| # | Step | Required | Command (no secret in it) | Expected result | Evidence to bring | Status |
|---|---|---|---|---|---|---|
| C1 | Create the Binance Demo API key without withdrawal permission and restrict it to the VPS public IP (OPS-02) | REQUIRED | in the Binance Demo Trading UI: API Management, Edit restrictions | the key has no withdrawal permission and an IP restriction | your own written attestation: "no withdrawal permission, IP restricted to the VPS: yes/no" (no key, no IP) | NOT_OBSERVED |
| C2 | Create the second Telegram bot for the live process (a bot of its own, not the shadow bot of the paper runtime; one getUpdates consumer per token) | REQUIRED | `@BotFather` then `/newbot` | a new bot token exists | "done" (never the token) | NOT_OBSERVED |
| C3 | Create the live env file from the template, mode 0600, owned by `trading` (names: `LIVE_RUNTIME_MODE=DEMO`, `BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_API_SECRET`, `TELEGRAM_LIVE_BOT_TOKEN`, `TELEGRAM_LIVE_AUTHORIZED_CHAT_ID`, `TELEGRAM_AUTHORIZED_USER_IDS`) | REQUIRED | `cd /opt/trading && (umask 077; cp .env.live.example .env.live) && nano .env.live && stat -c '%a %U' .env.live` | the last command prints `600 trading` | that one line | NOT_OBSERVED |
| C4 | Paper and backup env files keep their own names (per-service split) | REQUIRED | `stat -c '%a %U' .env .env.backup` (and `.env.paper` if used) | each prints `600 trading`; no `BINANCE_` name in `.env` | the `stat` lines; "no BINANCE_ name in .env: yes/no" | NOT_OBSERVED |
| C5 | Validate compose without printing secrets | REQUIRED | `docker compose --profile live config -q` (never plain `config`) | exit 0, no output | exit code | NOT_OBSERVED |

## D. First start of the live process

| # | Step | Required | Command (no secret in it) | Expected result | Evidence to bring | Status |
|---|---|---|---|---|---|---|
| D1 | Start the database and apply migrations | REQUIRED | `docker compose up -d postgres` then `docker compose run --rm db-upgrade` | `alembic upgrade head` ends at `0015_order_event_time` | the last migration line | NOT_OBSERVED |
| D2 | First-install gate state and spill sentinel, once only (RUNBOOK 22.3) | REQUIRED | `docker compose --profile live run --rm live python -m src.live.runtime --initialize-gate-state --operator-id owner` | the REST gate state file and `spill/.spill-initialized` are created in the `livestate` volume; the process admits and runs as in 22.2 (stop it with Ctrl+C after it logs the start sequence) | the printed start-sequence lines (no values) | NOT_OBSERVED |
| D3 | Start the live service and probe it | REQUIRED | `docker compose --profile live up -d live`, then `docker compose --profile live exec live python -m src.live.runtime --healthcheck` | the JSON shows `mode` DEMO, `held` false, a small `liveness_age_ms`; exit 0 | the JSON line (it holds no secret) | NOT_OBSERVED |
| D4 | The live bot answers on its own chat | REQUIRED | send `/status` to the live bot | a status reply from the live bot | a copy of the reply text | NOT_OBSERVED |

## E. Heartbeat

| # | Step | Required | Command (no secret in it) | Expected result | Evidence to bring | Status |
|---|---|---|---|---|---|---|
| E1 | Create the healthchecks.io check for the live process (period 60 s, grace 120 s, or your values) | REQUIRED | in the healthchecks.io dashboard | a check exists | "done" and the period and grace you chose (never the ping URL) | NOT_OBSERVED |
| E2 | Store the ping URL by standard input (never as an argument) | REQUIRED | `sudo deploy/heartbeat.sh --target live --set-url` and paste the URL when it waits | the URL file is written with a restricted mode | the script's confirmation line | NOT_OBSERVED |
| E3 | Install the timer and watch a real ping and an alert | REQUIRED | `sudo deploy/heartbeat.sh --target live --install-timer --interval-seconds 60`, then `systemctl list-timers trading-live-heartbeat.timer`, `systemctl status trading-live-heartbeat`, `journalctl -u trading-live-heartbeat` | the timer is listed; pings succeed while the process is live; stopping the live service (`docker compose --profile live stop live`) makes the check go red and the alert reach you; start it again afterwards | the three status outputs, and "alert received: yes/no" | NOT_OBSERVED |

## F. Telegram rejection check (G2-014)

| # | Step | Required | Command (no secret in it) | Expected result | Evidence to bring | Status |
|---|---|---|---|---|---|---|
| F1 | With a Demo card on the live bot (`/demo_signal`), a SECOND Telegram account and a group chat that contains the bot each tap APPROVE or send an operator command | REQUIRED | tap from the second account; add the live bot to a group and tap there | each tap is rejected, the approval state does not change, and a journal row records the rejection (`CALLBACK_RECEIVED` with `chat_gate_rejected` or `user_gate_rejected` true) | the journal row ids (query below) and "approval state unchanged: yes/no" | NOT_OBSERVED |

Find the row ids (read-only):

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select journal_event_id, event_type, occurred_at_utc from journal_events where event_type='CALLBACK_RECEIVED' and (payload_json like '%chat_gate_rejected%' or payload_json like '%user_gate_rejected%') order by occurred_at_utc desc limit 5;"
```

## G. Optional re-run and the restart policy

| # | Step | Required | Command (no secret in it) | Expected result | Evidence to bring | Status |
|---|---|---|---|---|---|---|
| G1 | Demo rehearsal re-run from the VPS (the VPS clock is chrony-synchronised, so the drift pre-flight should pass) | OPTIONAL | stop the live service, close every Demo position and order, `uv run python scripts/demo_clear.py`, then `uv run python -m scripts.demo_rehearsal --execute` (phrase `DEMO SMOKE BTCUSDT`); follow the `REHEARSAL:` Telegram messages | `evidence:` line, outcome COMPLETE, 21 of 21 steps PASSED, no `STOPPED` | the evidence file path; "Demo account flat afterwards: yes/no" | NOT_OBSERVED |
| G2 | Restart-policy switch after a clean run (O-2, Q15): the live service has `restart: "no"` | REQUIRED to decide | change `restart: "no"` to `restart: unless-stopped` on the `live` service in `docker-compose.yml` only after you have seen a clean run, then `docker compose --profile live up -d live` | the service survives a daemon restart; a refusal still holds (`--hold-on-refusal`) instead of looping | your decision: "switched" or "kept off", with the reason | NOT_OBSERVED |

## Evidence template

Copy one row per step you ran into the results section below.

| Step | Status | Date (UTC) | Run on | Evidence (path, journal row id, or the pasted output) | What you saw (one line) |
|---|---|---|---|---|---|
| e.g. D3 | demo-observed | 2026-11-DD | VPS | healthcheck JSON | mode DEMO, held false |

## Results (owner run)

Empty until you reply with the step outcomes and evidence paths (or "partial: steps N..M" with
what remains). The assistant copies your reply here verbatim and sets each status above only
from that reply and the evidence files; a step without evidence stays NOT_OBSERVED.

### Notes recorded 2026-11-07 (owner session; no status above was changed)

- E (heartbeat): the owner already ran the healthchecks.io monitor for the collector and paper on the
  EC2 host in `/opt/trading` (`deploy/heartbeat.sh --set-url`, `--install-timer --interval-seconds 300`).
  Record: `.planning/phases/16-paper-runtime-composition/evidence/16-50-operator-verification.md`
  (owner statement of 2026-10-12, not independently observed; the alert row was waived in
  `16-20-acceptance.json`). That check is not the live one: E1 to E3 need `--target live` with its own
  check (period 60 s, grace 120 s) and stay NOT_OBSERVED.
- B (host): a host exists and has run the collector and soak, but no file in the repo shows B1 to B7
  (`chronyc`, `ufw`, `sshd -T`, backup timer). They stay NOT_OBSERVED until the owner names the ones done
  and gives the output.
- F1 (G2-014): the owner has no second Telegram account and will test later. Stays NOT_OBSERVED. A group
  chat that holds only the owner and the live bot can show the chat gate; the user gate needs a second
  person. Not run.
