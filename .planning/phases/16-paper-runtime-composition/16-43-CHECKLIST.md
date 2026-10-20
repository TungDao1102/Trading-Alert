# 16-43 operator checklist (soak start and epoch pin)

Authority: `16-43-PLAN.md`. Where a command here differs from the plan, the RUNBOOK form is shown and the difference is listed under "Open points". Never write a DB URL, password, bucket key or ping URL into a command, a file of the repository, an evidence file or chat. Record UTC times, ids and exit codes only. IMAGE_COMMIT = `9b27da55ff1675b66c8033792b68186da9b4a498` [evidence/16-65-gate.txt]. In the commands below, `<commit>` is that value and `/path/to/soak.env` is your soak env file.

## 0. Before leaving this machine
- [ ] develop is pushed (OWNER action) and master carries IMAGE_COMMIT plus the freeze workflow. The local snapshot of origin/master (a67506f, last fetched) has neither the `concurrency` block nor 9b27da5, so a merge to master is still needed [plan Task 1; local `git show`, 2026-10-20].
- [ ] Read-only checks. Every one must pass [plan Task 1 action and verify]:
  `git fetch origin`
  `git show origin/master:.github/workflows/paper_freeze_check.yml` contains `--from-allowlist`, `concurrency:` with `group: paper-freeze-check`, `cancel-in-progress: false`, `queue: max`, and exactly one `- cron: "34 * * * *"`
  `git show origin/master:src/paper/freeze.py` holds the one `PAPER_START_ALLOWLIST` entry
  `git merge-base --is-ancestor 9b27da55ff1675b66c8033792b68186da9b4a498 origin/master` (exit 0)
  `git cat-file -e 9b27da55ff1675b66c8033792b68186da9b4a498:config/paper/paper-runtime-v2.toml` (exit 0)
  `gh workflow list --all` shows paper_freeze_check.yml as active (if `gh` is unavailable, check the Actions tab by hand and record that)
  Then run the five automated checks of plan Task 1 and `.venv/Scripts/python -m pytest tests/test_paper_runtime_config_file.py -q -p no:cacheprovider`, and write `evidence/16-43-preflight.txt`.
- [ ] The targeted re-review of `c654524..9b27da5` has passed and its result is recorded [plan, context bullet IMAGE_COMMIT].
- [ ] Evidence 16-40 rehearsal passed, 16-47/16-49 destination configured, 16-50 operator verification records `HEARTBEAT_MONITOR_ALERT_RECEIVED`, and 16-51/16-52 commits are on origin/master [plan Task 1].

## 1. Inputs to have in hand (never typed into chat)
| Input | Where it goes | Source |
|---|---|---|
| Soak backup bucket (not the trading bucket), its own access key, its own two crypt passwords in `rclone obscure` form (raw values kept off the host) | soak env file, `BACKUP_*` names, plain `BACKUP_S3_BUCKET=name` line | RUNBOOK 11.1, 11.3, 20.5 |
| Second healthchecks.io check: period 60 s, grace 120 s; its secret ping URL | stdin of `heartbeat.sh --target paper --set-url` only | 16-DEC-HUNG-RUNTIME, RUNBOOK 20.9 |
| Soak env file path (outside the checkout, mode 0600) with `PAPER_RUNTIME_CONFIG=/app/config/paper/paper-runtime-v2.toml` | `TRADING_ENV_FILE=` | RUNBOOK 20.1, 20.6 |
| Separate soak Telegram bot token (BotFather) | soak env file only | RUNBOOK 20.3, 16-DEC-Q-L |
| Binance: NO credential. Any `BINANCE_` name makes the runtime refuse (exit 3) | none | RUNBOOK 20.1 |
| `gh auth login` on the machine that fetches the run list | operator's own login | RUNBOOK 20.7 step 1 |

## 2. Ordered steps on the soak host
| # | Command (copy exactly) | Pass when | Record |
|---|---|---|---|
| 1a | `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup.sh --init-remote --dry-run` then without `--dry-run` (once, empty soak bucket) | exit 0 | UTC time, exit code [RUNBOOK 20.5] |
| 1b | `sudo deploy/backup.sh --install-soak-timer --soak-env-file /path/to/soak.env --dry-run` then without `--dry-run`; `systemctl list-timers trading-soak-backup.timer` | exit 0, timer listed | UTC time [RUNBOOK 20.5] |
| 1c | Backup now: `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup.sh` (see open point 2) | exit 0 | UTC time, snapshot id [RUNBOOK 11.4, backup.sh --help] |
| 1d | `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup-drill.sh` | exit 0; scratch DB only, never the soak DB | UTC time, result [RUNBOOK 11.6, 20.5] |
| 2 | Clean state in trading-soak DB: zero `test_only` true rows, zero PENDING approvals, zero EPOCH_PINNED; no `logs/paper/pinned_epoch.json` (see open point 3) | all zero / absent | query results [plan Task 2 step 2] |
| 3 | `git checkout 9b27da55ff1675b66c8033792b68186da9b4a498`; `deploy/soak-image.sh --dry-run`; `deploy/soak-image.sh`; `docker image inspect --format '{{.Id}}' trading-alert:<commit>` | build exit 0, in-image check passes; printed id equals `APP_IMAGE_ID` in `.deploy/soak-image.env` | GIT_SHA, APP_IMAGE_ID, OPS_IMAGE_ID [RUNBOOK 20.6] |
| 4 | `sudo deploy/heartbeat.sh --target paper --set-url` (URL as one line on stdin, no echo); `sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file /path/to/soak.env`; `systemctl list-timers trading-soak-paper-heartbeat.timer` | exit 0, timer listed | UTC times, never the URL [RUNBOOK 20.9; heartbeat.sh --help] |
| 5 | Restart drill, section 3 below, with `IMAGE_TAG=<commit>` and `TRADING_ENV_FILE=/path/to/soak.env` set in the shell; then repeat step 2 | every path as expected; paper check alerted while held | per path UTC time and outcome; `PAPER_HEARTBEAT_ALERT_RECEIVED <UTC>`; collector downtime of the reboot as a data gap [RUNBOOK 20.8; plan step 5] |

## 3. Restart drill (all five must pass before the pin) [RUNBOOK 20.8; 16-DEC-RESTART-POLICY]
| Path | Command | Expected observable result |
|---|---|---|
| (a) Refused start | `deploy/compose-soak.sh --profile paper up -d --no-build`; `deploy/compose-soak.sh ps paper`; `deploy/compose-soak.sh logs paper`; `deploy/compose-soak.sh exec -T paper ls logs/paper` | stays up, no restart; log `paper runtime refused (exit 5)`; `held-refusal-<container>.json` present; unhealthy after the start period (6m); no `PaperRuntime` journal event |
| (b) Docker daemon restart | `sudo systemctl restart docker`; `deploy/compose-soak.sh ps paper`; `deploy/compose-soak.sh logs paper` | comes back by itself, holds again; new refusal with a later time; unhealthy again |
| (c) Host reboot | `sudo reboot`; after login `deploy/compose-soak.sh ps paper` | up by itself and held; collector restarted (downtime = data gap) |
| (d) Process crash | `deploy/compose-soak.sh ps -q paper`; `docker inspect --format '{{.State.Pid}}' <container id>`; `sudo kill -KILL <pid>`; `docker inspect --format '{{.RestartCount}}' <container id>`; `deploy/compose-soak.sh ps paper` | Docker restarts it; RestartCount +1; holds again |
| (e) Requested stop | `deploy/compose-soak.sh stop paper`; `sudo systemctl restart docker`; `deploy/compose-soak.sh ps -a paper` | stays stopped (exited) after the daemon restart; leave it stopped for the pin |

## 4. Pin, start, export, first tick [16-DEC-PIN-COMMAND; RUNBOOK 20.1; plan steps 6-8]
1. [ ] Paper is stopped (end of drill (e)). Nothing else runs between the next two commands; pin-to-start time counts toward the 900 s ceiling.
2. [ ] `IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper-pin run --rm paper-pin` must print `epoch pinned: <epoch id>` and exit 0. Any other exit: do NOT start, report (exit 8 = a paper container still runs).
3. [ ] At once: `IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d --no-build paper`.
4. [ ] Record: epoch_id, pin UTC, configuration identity (64 hex) and the raw file sha256 (labelled provenance) from the EPOCH_PINNED record, first RUNTIME_START UTC, first healthy probe UTC, UTC when the paper check reports up again. Later starts never pin.
5. [ ] Export the pin (Q-F commit-pinned-state): commit `evidence/paper/pinned_epoch.json` to master, as the owner [16-DEC-Q-F; RUNBOOK 20.7 "Pin source"]. Until it is on master the hourly check has no pin.
6. [ ] After the first HH:34 scheduled tick after the pin: a CLEAN line from a `schedule` event run whose schedule string is `34 * * * *` [16-DEC-Q-Q]. Fetch with RUNBOOK 20.7 step 1 (`gh api .../paper_freeze_check.yml/runs ...` and `gh run download <run-id> ... --name registry-diff-<run-id> ...`).
7. [ ] From the pin to the end of the trial do NOT edit the workflow `cron:` line (a different string makes every later slot SCHEDULE_MISMATCH and restarts the trial, REV-18).

## 5. STOP: do not pin (or stop the trial) when
- any section 0 check fails, IMAGE_COMMIT is not on origin/master, the re-review has not passed, or the workflow is disabled;
- backup or restore drill fails, or a clean-state count is non-zero (before or after the drill);
- `soak-image.sh` fails, or the inspected image id differs from `APP_IMAGE_ID`;
- the paper heartbeat did not alert while paper was held, or any of the five drill paths differs from section 3 (reboot and daemon restart are never an accepted deviation);
- the pin exits non-zero; after the pin: any EvidenceGap, or a first tick that is not CLEAN, means stop and report; a new trial needs a new pin by the owner (REV-18).

## 6. Bring back to the repository [plan frontmatter and Tasks 1-3]
- `evidence/16-43-preflight.txt`: every section 0 check with command and result, origin/master commit id.
- `evidence/16-43-soak-start.md` with the headings Backup, Restore drill, Clean state, Image id, Paper heartbeat, Restart drill, Epoch, Config sha256, Pinned state export, First tick, the line `PAPER_HEARTBEAT_ALERT_RECEIVED` and the 64-hex identity.
- `evidence/16-43-first-export-check.txt` after at least one full UTC day (RUNBOOK 20.7 export `--source pg`): `REAL_SOAK`, the single epoch_id, `evidence gaps: 0`, `sdk rotation observed: <count or not yet due>`, `tick timing: <summary>`.
- Then reply "soak started" with the epoch_id; `16-43-SUMMARY.md` follows.

## Open points for the owner
1. Plan step 6 writes `IMAGE_TAG=<IMAGE_COMMIT> deploy/compose-soak.sh --profile paper up -d --no-build` (no `TRADING_ENV_FILE`, no service name); RUNBOOK 20.1 adds both. This checklist uses the RUNBOOK form.
2. Plan step 1 cites RUNBOOK 11.4 (`deploy/backup.sh`), which backs up project `trading`; RUNBOOK 20.5 gives soak forms for `--init-remote` and the drill but no literal soak "backup now" line. Step 1c is derived from 20.5 plus `backup.sh --help` (COMPOSE_PROJECT_NAME and TRADING_ENV_FILE are honoured). Confirm. Also RUNBOOK 20.5 says the first real backup waits for the D064 real-S3 gate, which STATE still lists as pending: decide whether it blocks the pin.
3. Plan step 2 names the clean-state conditions but no query or table names; no command is given for it.
4. Plan step 4 writes the paper `--install-timer` without `--soak-env-file`; `heartbeat.sh --help` and RUNBOOK 20.9 require it. The RUNBOOK example uses `/home/trading/soak.env`.
5. No documented command copies `logs/paper/pinned_epoch.json` out of the soak `logs` volume to `evidence/paper/pinned_epoch.json`, and no command reads the configuration identity from the EPOCH_PINNED record. Plan step 7 also allows "or publish to the O-01 location", but the workflow reads the pin only from the master commit (Q-F).
6. Plan step 8 gives no command or field names for the "CLEAN line from a schedule-event run". It is only shown here as the RUNBOOK 20.7 fetch.
7. The plan's context cites `RUNBOOK 20.x "Restart drill before the pin"` and "the paper heartbeat". The actual sections are 20.8 and 20.9.
