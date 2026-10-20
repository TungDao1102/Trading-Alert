# 16-43 operator checklist (soak start and epoch pin)

Authority: `16-43-PLAN.md`. Where a command here differs from the plan, the RUNBOOK form is shown and the plan was corrected on 2026-10-20 (quick 261020-bkp); what is still open is listed under "Open points". Never write a DB URL, password, bucket key or ping URL into a command, a file of the repository, an evidence file or chat. Record UTC times, ids and exit codes only. IMAGE_COMMIT = the commit of the owner's fresh full gate after the Phase 19 merge into develop (owner decision of 2026-10-20). The value `9b27da55ff1675b66c8033792b68186da9b4a498` of `evidence/16-65-gate.txt` is superseded by that later gate and is not used. In the commands below, `<commit>` is that new IMAGE_COMMIT (40 hex) and `/path/to/soak.env` is your soak env file.

## 0. Before leaving this machine
- [ ] IMAGE_COMMIT is taken from the owner's post-Phase-19-merge fresh full gate record, not from `evidence/16-65-gate.txt`. Write it down as 40 hex before anything else.
- [ ] The soak host checkout is on a commit that contains quick 261020-bkp (local-only mode, the D064 gate script and the backup.sh fixes): steps 1a to 1e run `deploy/backup.sh`, `deploy/backup-drill.sh` and `deploy/backup-real-s3-gate.sh` from the host's checkout, not from the image. Check on the host: `git merge-base --is-ancestor 1b39a70595919588ffb3c83c6440a8e15be2079c HEAD` (exit 0; 1b39a70595919588ffb3c83c6440a8e15be2079c is the 261020-bkp commit that adds the gate script) and `test -f deploy/backup-real-s3-gate.sh` (exit 0).
- [ ] Pin rule (owner decision of 2026-10-20): the pin needs a soak backup against the REAL remote (its output ends with `OFFSITE_COPY=verified`) and a restore drill that passed against that remote. Local-only mode (`BACKUP_REMOTE=none`, output `OFFSITE_COPY=skipped`) keeps backups running but never counts for the pin.
- [ ] develop is pushed (OWNER action) and master carries IMAGE_COMMIT plus the freeze workflow. The local snapshot of origin/master (a67506f, last fetched) has neither the `concurrency` block nor the new IMAGE_COMMIT, so a merge to master is still needed [plan Task 1; local `git show`, 2026-10-20].
- [ ] Read-only checks. Every one must pass [plan Task 1 action and verify]:
  `git fetch origin`
  `git show origin/master:.github/workflows/paper_freeze_check.yml` contains `--from-allowlist`, `concurrency:` with `group: paper-freeze-check`, `cancel-in-progress: false`, `queue: max`, and exactly one `- cron: "34 * * * *"`
  `git show origin/master:src/paper/freeze.py` holds the one `PAPER_START_ALLOWLIST` entry
  `git merge-base --is-ancestor <commit> origin/master` (exit 0)
  `git cat-file -e <commit>:config/paper/paper-runtime-v2.toml` (exit 0)
  `gh workflow list --all` shows paper_freeze_check.yml as active (if `gh` is unavailable, check the Actions tab by hand and record that)
  Then run the five automated checks of plan Task 1 and `.venv/Scripts/python -m pytest tests/test_paper_runtime_config_file.py -q -p no:cacheprovider`, and write `evidence/16-43-preflight.txt`. The second automated check reads `^IMAGE_COMMIT=<40 hex>$` from a gate file: see open point A.
- [ ] The targeted re-review of `c654524..<commit>` has passed and its result is recorded [plan, context bullet IMAGE_COMMIT].
- [ ] Evidence 16-40 rehearsal passed, 16-47/16-49 destination configured, 16-50 operator verification records `HEARTBEAT_MONITOR_ALERT_RECEIVED`, and 16-51/16-52 commits are on origin/master [plan Task 1].

## 1. Inputs to have in hand (never typed into chat)
| Input | Where it goes | Source |
|---|---|---|
| Soak backup bucket (not the trading bucket), its own access key, its own two crypt passwords in `rclone obscure` form (raw values kept off the host) | soak env file, `BACKUP_*` names, plain `BACKUP_S3_BUCKET=name` line, `BACKUP_REMOTE=` empty (or `s3`), never `none` for the pin | RUNBOOK 11.1, 11.3, 20.5 |
| Second healthchecks.io check: period 60 s, grace 120 s; its secret ping URL | stdin of `heartbeat.sh --target paper --set-url` only | 16-DEC-HUNG-RUNTIME, RUNBOOK 20.9 |
| Soak env file path (outside the checkout, mode 0600) with `PAPER_RUNTIME_CONFIG=/app/config/paper/paper-runtime-v2.toml` | `TRADING_ENV_FILE=` | RUNBOOK 20.1, 20.6 |
| Separate soak Telegram bot token (BotFather) | soak env file only | RUNBOOK 20.3, 16-DEC-Q-L |
| Binance: NO credential. Any `BINANCE_` name makes the runtime refuse (exit 3) | none | RUNBOOK 20.1 |
| `gh auth login` on the machine that fetches the run list | operator's own login | RUNBOOK 20.7 step 1 |

## 2. Ordered steps on the soak host
Run every command from the checkout directory as the `trading` user unless it starts with `sudo`. Set `export TRADING_ENV_FILE=/path/to/soak.env` once per shell (the compose wrappers and psql below need it for interpolation; it is a path, not a secret).

| # | Command (copy exactly) | Pass when | Record |
|---|---|---|---|
| 1a | `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup-real-s3-gate.sh` (plan only), then `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup-real-s3-gate.sh --execute --evidence-dir /home/trading/gate-evidence` | exit 0 and the evidence file ends with `RESULT: PASS` (every `CLAIM ...: PASS`, cleanup included) | UTC time, exit code, evidence file name; copy the file into `evidence/16-43-real-s3-gate.txt` [D064, RUNBOOK 11 "Real-S3 gate"] |
| 1b | `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup.sh --init-remote --dry-run` then without `--dry-run` (once, empty soak bucket) | exit 0, `init-OK sentinel=written` | UTC time, exit code [RUNBOOK 20.5] |
| 1c | `sudo deploy/backup.sh --install-soak-timer --soak-env-file /path/to/soak.env --dry-run` then without `--dry-run`; `systemctl list-timers trading-soak-backup.timer` | exit 0, timer listed, NO `OFF-HOST COPY SKIPPED` warning | UTC time [RUNBOOK 20.5] |
| 1d | Backup now: `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup.sh` | exit 0; output has `scheduled-OK snapshot=<id>` and the line `OFFSITE_COPY=verified` | UTC time, snapshot id [RUNBOOK 11.4, 20.5; `backup.sh --help`] |
| 1e | `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup-drill.sh` | exit 0; `drill-remote-OK snapshot=<id>` and `OFFSITE_COPY=verified`; scratch DB only, never the soak DB | UTC time, result [RUNBOOK 11.6, 20.5] |
| 2 | Clean state, the two commands below the table | `test_only_rows|0`, `pending_approvals|0`, `epoch_pinned|0`, and `pinned_epoch.json absent` | the four printed lines [plan Task 2 step 2] |
| 3 | `git checkout <commit>`; `deploy/soak-image.sh --dry-run`; `deploy/soak-image.sh`; `docker image inspect --format '{{.Id}}' trading-alert:<commit>` | build exit 0, in-image check passes; printed id equals `APP_IMAGE_ID` in `.deploy/soak-image.env` | GIT_SHA, APP_IMAGE_ID, OPS_IMAGE_ID [RUNBOOK 20.6] |
| 4 | `sudo deploy/heartbeat.sh --target paper --set-url` (URL as one line on stdin, no echo); `sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file /path/to/soak.env`; `systemctl list-timers trading-soak-paper-heartbeat.timer` | exit 0, timer listed | UTC times, never the URL [RUNBOOK 20.9; heartbeat.sh --help] |
| 5 | Restart drill, section 3 below, with `IMAGE_TAG=<commit>` and `TRADING_ENV_FILE=/path/to/soak.env` set in the shell; then repeat step 2 | every path as expected; paper check alerted while held | per path UTC time and outcome; `PAPER_HEARTBEAT_ALERT_RECEIVED <UTC>`; collector downtime of the reboot as a data gap [RUNBOOK 20.8; plan step 5] |

Step 1d is the soak form of RUNBOOK 11.4: `deploy/backup.sh` without options runs `python -m src.ops.backup scheduled` in the `backup` service, and `COMPOSE_PROJECT_NAME` and `TRADING_ENV_FILE` select the soak project and its env file (checked against `deploy/backup.sh --help` and `main()` of the script on 2026-10-20). Without `COMPOSE_PROJECT_NAME=trading-soak` it would back up project `trading`, not the soak database.

Step 2, clean state (read-only; derived from `src/db/models.py`: `journal_events.payload_json`, `journal_events.entity_type`/`event_type`, `approvals.status`; the runtime records live in `journal_events` with entity type `PaperRuntime`, `src/paper/runtime_state.py`; `test_only` exists only inside the journal payload, `src/paper/rehearsal.py`). psql runs inside the soak `postgres` container as its own user over the local socket, so no URL or password is typed; the transaction is read-only:

```text
deploy/compose-soak.sh exec -T postgres sh -c 'exec psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
BEGIN READ ONLY;
SELECT 'test_only_rows', count(*) FROM journal_events WHERE (payload_json::jsonb ->> 'test_only') = 'true';
SELECT 'pending_approvals', count(*) FROM approvals WHERE status = 'PENDING';
SELECT 'epoch_pinned', count(*) FROM journal_events WHERE entity_type = 'PaperRuntime' AND event_type = 'EPOCH_PINNED';
ROLLBACK;
SQL
deploy/compose-soak.sh --profile ops run --rm --no-deps -T ops sh -c 'if test -e /app/logs/paper/pinned_epoch.json; then echo "pinned_epoch.json PRESENT"; else echo "pinned_epoch.json absent"; fi'
```

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
2. [ ] `IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper-pin run --rm paper-pin` must print `epoch pinned: <epoch id>; start the managed paper service now` and exit 0. Any other exit: do NOT start, report (exit 8 = a paper container still runs).
3. [ ] At once: `IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d --no-build paper` (the RUNBOOK 20.1 form, with the env file and the service name).
4. [ ] Record: epoch_id, pin UTC, configuration identity (64 hex) and the raw file sha256 (labelled provenance) from the EPOCH_PINNED record, first RUNTIME_START UTC, first healthy probe UTC, UTC when the paper check reports up again. Later starts never pin. The EPOCH_PINNED record and the first RUNTIME_START, read-only (the epoch id is the second `:` field of `correlation_id`; `config_identity_sha256` is the identity, `config_file_provenance.file_sha256` the provenance, `src/paper/runtime_config.py`):

```text
deploy/compose-soak.sh exec -T postgres sh -c 'exec psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
BEGIN READ ONLY;
SELECT event_type, occurred_at_utc, split_part(correlation_id, ':', 2) AS epoch_id, payload_json::jsonb ->> 'config_identity_sha256' AS config_identity, payload_json::jsonb -> 'config_file_provenance' ->> 'file_sha256' AS file_sha256_provenance FROM journal_events WHERE entity_type = 'PaperRuntime' AND event_type IN ('EPOCH_PINNED', 'RUNTIME_START') ORDER BY occurred_at_utc LIMIT 2;
ROLLBACK;
SQL
```

5. [ ] Export the pin (Q-F `commit-pinned-state`, owner decision confirmed 2026-10-20: the owner commits the file to master after the pin; there is no other route). On the soak host, copy the file out of the soak `logs` volume (the `paper` container runs after step 3) and hash it:

```text
mkdir -p /home/trading/pin-export
deploy/compose-soak.sh cp paper:/app/logs/paper/pinned_epoch.json /home/trading/pin-export/pinned_epoch.json
sha256sum /home/trading/pin-export/pinned_epoch.json
deploy/compose-soak.sh exec -T paper sha256sum logs/paper/pinned_epoch.json
```

   Both hashes must be equal. Bring the file to the development machine (for example `scp`), place it at `evidence/paper/pinned_epoch.json` on a branch of master, check `sha256sum evidence/paper/pinned_epoch.json` against the host value, commit and push it to master as the owner [16-DEC-Q-F; RUNBOOK 20.7 "Pin source"]. Until it is on master the hourly check has no pin.
6. [ ] After the first HH:34 scheduled tick after the pin: a CLEAN line from a `schedule` event run whose schedule string is `34 * * * *` [16-DEC-Q-Q]. Where `gh` is logged in (`<owner>/<repo>` is the repository):

```text
gh run list --repo <owner>/<repo> --workflow paper_freeze_check.yml --event schedule --limit 5 --json databaseId,createdAt,event,conclusion
gh run download <run-id> --repo <owner>/<repo> --name registry-diff-<run-id> --dir <download-dir>/<run-id>
jq -c 'select(.outcome == "clean" and .epoch_id == "<epoch id>" and .pinned_hash == .current_hash and .run_metadata.event_name == "schedule" and .run_metadata.schedule == "34 * * * *" and .run_metadata.run_id == "<run-id>")' <download-dir>/<run-id>/registry_diff.jsonl
```

   Take `<run-id>` from the first run whose `createdAt` is after the pin UTC. Pass when the last command prints exactly one line; record that line (it holds `checked_at_utc`, `epoch_id`, `pinned_hash`, `current_hash`, `outcome` and `run_metadata` with `run_id`, `run_attempt`, `event_name`, `commit`, `schedule`; `src/paper/freeze.py` `DiffLogEntry`). The outcome value in the file is lower-case `clean`. No line, or a line with `REGISTRY_DIFF`, is a stop.
7. [ ] From the pin to the end of the trial do NOT edit the workflow `cron:` line (a different string makes every later slot SCHEDULE_MISMATCH and restarts the trial, REV-18).

## 5. STOP: do not pin (or stop the trial) when
- any section 0 check fails, IMAGE_COMMIT is not on origin/master, the re-review has not passed, or the workflow is disabled;
- the real-S3 gate (step 1a) prints any `FAIL` or does not end with `RESULT: PASS` (D064: the push design is then not claimed to protect integrity, the owner decides again);
- backup or restore drill fails, or a clean-state count is non-zero (before or after the drill);
- the soak backup or the drill ran in local-only mode: the pin needs a backup against the real remote whose output carries `OFFSITE_COPY=verified` and a drill that passed against that remote; a run printing `OFFSITE_COPY=skipped` (`BACKUP_REMOTE=none`) never counts (owner decision 2026-10-20, RUNBOOK 20.5);
- `soak-image.sh` fails, or the inspected image id differs from `APP_IMAGE_ID`;
- the paper heartbeat did not alert while paper was held, or any of the five drill paths differs from section 3 (reboot and daemon restart are never an accepted deviation);
- the pin exits non-zero; after the pin: any EvidenceGap, or a first tick that is not CLEAN, means stop and report; a new trial needs a new pin by the owner (REV-18).

## 6. Bring back to the repository [plan frontmatter and Tasks 1-3]
- `evidence/16-43-preflight.txt`: every section 0 check with command and result, origin/master commit id, and the IMAGE_COMMIT of the post-Phase-19 gate.
- `evidence/16-43-real-s3-gate.txt`: the evidence file of step 1a, unchanged.
- `evidence/16-43-soak-start.md` with the headings Backup, Restore drill, Clean state, Image id, Paper heartbeat, Restart drill, Epoch, Config sha256, Pinned state export, First tick, the line `PAPER_HEARTBEAT_ALERT_RECEIVED` and the 64-hex identity. Under Backup and Restore drill record the `OFFSITE_COPY=verified` line.
- `evidence/16-43-first-export-check.txt` after at least one full UTC day (RUNBOOK 20.7 export `--source pg`): `REAL_SOAK`, the single epoch_id, `evidence gaps: 0`, `sdk rotation observed: <count or not yet due>`, `tick timing: <summary>`.
- Then reply "soak started" with the epoch_id; `16-43-SUMMARY.md` follows.

## Open points for the owner
Points 1 to 7 of the first version were resolved on 2026-10-20 (quick 261020-bkp): (1) step 4.3 and plan step 6 use the RUNBOOK 20.1 start form; (2) the soak backup-now command is step 1d, checked against `backup.sh --help`, and the D064 gate is step 1a, run on the soak host with the owner's real S3 (owner decision: it does not block work elsewhere, it blocks the first real soak backup); (3) the clean-state check is the command below step 2; (4) the heartbeat timer carries `--soak-env-file`; (5) the pin export and the identity query are in step 4.4 and 4.5, the O-01 alternative is dropped; (6) the CLEAN-line check is step 4.6; (7) the restart drill is RUNBOOK 20.8 and the paper heartbeat 20.9. Still open:
- A. Plan Task 1's second automated check reads `^IMAGE_COMMIT=<40 hex>$` from `evidence/16-65-gate.txt`, but that file states the commit as "commit under test (IMAGE_COMMIT, ...): <sha>" and has no such line, so the check prints False as written. The post-Phase-19 gate record should carry a line `IMAGE_COMMIT=<40 hex>` and the check should read that record; which file it is, is the owner's choice.
- B. The psql commands of steps 2 and 4.4 and the `compose cp` of step 4.5 were derived from the code and the compose file; they were not run against a real soak database here (no host). The official postgres image trusts local socket connections inside the container; if the soak image was initialised otherwise, psql asks for a password and the command must not be "fixed" by typing one on the command line.
- C. No read-only command of the repository prints the configuration identity on its own; the query of step 4.4 reads it from the EPOCH_PINNED journal row. The pin command itself prints only the epoch id.
