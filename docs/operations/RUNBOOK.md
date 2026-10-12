# Operations Runbook

## 1. Purpose

This is the operational response guide for incidents involving live approval mode, positions, orders, market data, or infrastructure.

The default objective is **preserve capital and state integrity**, not resume trading quickly.

## 2. Immediate emergency: SAFE_MODE

Trigger when:

- state cannot be reconciled;
- market data is stale;
- protective orders are missing or uncertain;
- duplicate execution is suspected;
- exchange/API behavior is unexpected;
- database state is corrupt or unavailable.

Actions:

```text
1. Set SAFE_MODE.
2. Block new ENTRY orders (protective and reduce-only orders remain allowed, D034).
3. Verify Binance positions directly.
4. Verify open normal orders.
5. Verify open algo/conditional orders.
6. Verify each live position has the expected protection; a missing protection goes to section 3.
7. Reconcile local state.
8. Only then consider resuming.
```

## 3. Position without confirmed stop

```text
SAFE_MODE
→ alert immediately
→ query Binance authoritative position
→ query protective/algo orders
→ if stop is absent or canceled, automatically re-place it at the original plan SL after risk validation (never wider)
→ if the SL is rejected or not acknowledged, close the position with a reduce-only order, then send a HIGH alert
→ manual intervention is optional, not required
```

The automatic ladder is per D034: the operator works full-time and cannot be assumed to react within minutes.

**Implementation status:** the ladder above is the target behaviour (D034) and is built in Phase 20 (EXEC-06, OPS-05). Until then the system does not re-place a stop-loss or close the position by itself: on an entry without a protective stop it enters SAFE_MODE and alerts, and the operator must place the stop-loss or close the position manually on the exchange. Do not wait for an automatic action.

Never assume a locally stored order ID means the exchange order exists.

## 4. Orphan protective orders

Definition:

> A protective order remains active when its associated position is already zero or the plan is otherwise closed/invalid.

Action:

```text
identify orphan
→ verify position = zero
→ cancel associated protective/algo orders
→ journal cancellation
→ re-scan for remaining orphan orders
```

This must run both on event-driven reconciliation and periodic sweeps.

A protective stop paired with a still-working ENTRY order is not an orphan: the position is zero only because the entry has not filled yet, so the sweeper must leave that stop in place (F-401, D034).

## 5. Suspected duplicate approval/order

```text
SAFE_MODE
→ do not retry blindly
→ look up approval token/hash
→ inspect clientOrderId/algoClientId/exchange order state
→ reconcile
→ continue only when unique execution intent is established
```

Phase 17 (D051): the authority for "was this approval executed" is PostgreSQL, not the exchange and not Telegram. The exchange cannot tell you whether an entry was replayed, because Binance treats a client order id as unique only among open orders (`EXECUTION_SPEC.md` section 7). Two things record it, and both are read with read-only `SELECT` statements (use `psql` against the stack's PostgreSQL with the user and database from `.env`; never `UPDATE` or `DELETE` these tables by hand):

```sql
-- the approval and its consumption state
SELECT approval_id, trade_plan_id, status, consumption_status, consumed_at_utc
  FROM approvals WHERE trade_plan_id = '<trade plan id>';

-- the write-ahead intent rows of the plan, one per role
SELECT role, intent_status, client_order_id, algo_client_id, exchange_order_id,
       outcome_recorded, outcome_is_no_trade, outcome_reason_code, intended_at_utc, sent_at_utc
  FROM execution_intents WHERE trade_plan_id = '<trade plan id>' ORDER BY role;

-- every intent that is not resolved
SELECT approval_id, role, intent_status, intended_at_utc
  FROM execution_intents WHERE intent_status IN ('INTENDED', 'SENT', 'UNKNOWN')
 ORDER BY intended_at_utc;
```

How to read them: `approvals.consumption_status = CONSUMED` means the approval reached order placement, and exactly one ENTRY row exists for it (the database allows only one per plan). `ACKED` means the exchange accepted the leg, `REJECTED` that it definitively did not, and `INTENDED`, `SENT` or `UNKNOWN` that the entry may or may not exist on the exchange: query Binance by the `client_order_id` (ENTRY) or `algo_client_id` (protective legs) shown in the row, and do not approve again. A plan whose approval is `UNCONSUMED` has not placed anything; a NO_TRADE decided before placement leaves it retryable until the plan expires. After a restart the system itself resolves in-flight intents by the same deterministic-id query and enters SAFE_MODE with reason `UNRESOLVED_EXECUTION_INTENT` when it cannot (section 9); that startup wiring is built in Phase 20 and 24.

## 6. Telegram callback replay

A repeated callback for the same approval token must return the current state.

It must never create another execution intent.

Phase 17 (D051): a replayed or redelivered APPROVE returns the stored approval and, for an executed plan, the stored execution outcome with zero Binance calls, also after a restart, because both are read from `approvals` and `execution_intents`. A redelivery of the same Telegram `callback_query.id` writes no second journal row. After the plan's expiry the callback layer still answers a redelivered APPROVE with "approval expired" even when the plan was executed (the callback layer keeps its expiry gate and does not read the intent rows); check `execution_intents` (section 5) before concluding that nothing was placed.

## 7. Market feed stale

Trigger when:

```text
now - last_expected_closed_candle > configured freshness threshold
```

Action:

```text
NO NEW SIGNALS
NO NEW ENTRY ORDERS
→ reconnect/re-bootstrap
→ validate candle continuity
→ resume only after health check
```

## 8. WebSocket disconnect

For every reconnect:

```text
reconnect
→ refresh server time if needed
→ bootstrap authoritative account/market state
→ compare local state
→ restore subscriptions
→ verify latest closed candle
→ resume
```

## 9. Database failure

```text
SAFE_MODE
→ block new entry orders only
→ a database failure must not prevent risk-reducing actions (D034)
→ preserve existing exchange-side protection
→ restore DB or switch to read-only monitoring
→ reconcile after recovery
```

Phase 17 (D051): the PostgreSQL stores fail closed. A store that cannot reach the database raises a typed error instead of falling back to memory. Before an entry order is sent that is NO_TRADE: nothing is placed and the approval stays retryable. After the entry may exist, the first failed write enters SAFE_MODE with reason `DB_FAILURE` once, the protective stop-loss is still placed by its deterministic id, and the outcome is "reconciliation required". A database failure never blocks risk-reducing actions (D034).

`UNRESOLVED_EXECUTION_INTENT` is the SAFE_MODE reason that restart recovery enters when an intent that was INTENDED, SENT or UNKNOWN at restart could not be resolved by querying the exchange (probe error, indeterminate answer, or the order is absent but older than the 3-day Query Order window). It means: an entry order may exist that the system cannot see. New entries stay blocked. Look up the intent (section 5), query Binance for its client id, and cancel or adopt the order by hand; do not edit the intent row. The system does not leave this SAFE_MODE by itself (the exit rules are Phase 20). Journal rows (`journal_events`), system-state rows (`system_state_events`) and plan constraint snapshots (`plan_constraint_snapshots`) are append-only: the database refuses a manual `UPDATE`, `DELETE` or `TRUNCATE` with an "append-only" error, so do not try to correct them. The table owner can disable the trigger; separating the owner role from the application role is Phase 26.

## 10. Binance API degradation

Do not infer absence of an order from a timeout.

Use query/reconciliation before retrying signed order requests.

## 11. Backup and restore

At minimum:

- automated PostgreSQL logical backup or equivalent;
- encrypted backup copy outside the primary VPS/host;
- retention policy;
- periodic restore drill.

The collected OI/time-series dataset is considered irreplaceable research data.

A backup is not considered valid until a restore test succeeds.

### Phase 13.1 implementation (D050)

Backups are encrypted on the host and pushed to any S3-compatible store (AWS S3, Backblaze B2 through its S3 endpoint, Wasabi, other) through `rclone` with a `crypt` layer, so the provider only ever sees ciphertext and encrypted file names. All logic lives in `python -m src.ops.backup` (run in the compose `ops` image); the shell scripts below are thin wrappers that pass its exit code through. Remote layout: an append-only `parquet/` copy (copied with `--immutable`, never synced, moved or deleted), one `snapshots/<YYYYMMDDTHHMMSSZ>/` folder per backup holding `pg.dump` and `manifest.json`, and a `_sentinel/sentinel.txt` that proves the key is right before every operation. The Parquet files are uploaded only after their SHA-256 has been compared with the manifests of the complete snapshots (see the next paragraphs).

Retention is 7/4/6: the newest snapshot of each of the last 7 UTC days, 4 ISO weeks and 6 months that actually have a snapshot (periods without a snapshot are skipped, so an outage never deletes the only good copy), and the newest snapshot overall is always kept. Retention runs only after a push has been verified with `cryptcheck`, removes only `snapshots/<id>` folders, and treats an empty listing as an error. The Parquet copy under `parquet/` is research data and is never pruned remotely, so the bucket grows with the dataset.

**Parquet push.** The push decides what to upload from content, never from file size or modification time. Each Parquet path of the bundle manifest is compared by SHA-256 with the manifests of all complete remote snapshots (a snapshot is complete when its `manifest.json` exists) and with a listing of `parquet/`. A path a complete snapshot names with the same hash is skipped. A path a complete snapshot names with a different hash (or that two complete snapshots name with different hashes) is refused: nothing is uploaded and nothing is overwritten. A path no complete snapshot names that is not on the remote is uploaded. A path no complete snapshot names that is already on the remote (an earlier push died before its `manifest.json`) is verified with `rclone cryptcheck` against the local file, adopted without a new upload when identical and refused when different. After the upload `cryptcheck` verifies the whole local Parquet tree against the remote (every push, every file, one way, so files pruned locally earlier do not count) before `pg.dump` is uploaded, so a damaged Parquet object leaves no snapshot folder behind. `pg.dump` is then uploaded and verified the same way, and the bundle is verified against its manifest once more, because `cryptcheck` compares against the local bytes of the moment and a local file changed during a long upload would otherwise get a manifest naming the old hash. All of this happens before `manifest.json` exists. Only then is the manifest published and checked, and it is removed again (`rclone deletefile`, two attempts) if its upload or its check fails, so a snapshot never looks complete unverified. rclone's size, modification-time and checksum comparisons decide nothing on a crypt remote (D064); `--immutable` stays on every upload as defence in depth only. The manifest format is unchanged (path to SHA-256). Retention and restore ignore a snapshot without `manifest.json`. A known path whose remote object is missing or altered is not uploaded again: the tree check fails and the operator decides (11.8).

**Cost of the check.** The whole-tree check runs on every push; no sampling, skip or time limit exists. Measured with rclone 1.75.1 against an S3 double on Docker Desktop (16 CPUs, one `docker run` per rclone call, about 0.76 s per call before any work), seconds for the whole-tree check, the listing of `parquet/` and the first upload: 250 files of 64 KiB 1.56, 1.10, 1.85; 1000 files of 64 KiB 2.64, 1.08, 4.37; 4000 files of 64 KiB 7.58, 1.43, 13.80; 8 files of 32 MiB 1.71, 0.77, 2.42. These figures are measured against an S3 double on Docker Desktop, not against a real S3 provider (no network latency, no request cost). No time limit has been set for the check; `trading-backup.service` has `TimeoutStartSec=2h`, and the adapter's limit for one rclone call is six hours.

**Failure windows.**

- W1: if the process is killed or the host is lost after the manifest object exists on the remote and before its check, or its removal, has finished, the snapshot looks complete with an unverified manifest. The window lasts about one single-object check per push. A restore verifies every pulled file against the pulled manifest and fails closed if it is wrong, and the next push reads that manifest and turns a wrong hash into a refusal, never into a silent skip.
- W2: if the removal of a manifest that failed its check fails twice, the snapshot looks complete with a manifest that failed its check. The push exits non-zero and its message names the snapshot and the object to remove by hand (11.8).
- W3: a crash between the Parquet upload and the manifest leaves Parquet objects that no complete snapshot names and, when it happened after `pg.dump` went up, an incomplete snapshot folder. The next push verifies and adopts those objects. Restore and retention ignore the incomplete folder, and retention purges it once a newer complete snapshot exists.
- W4: two writers at the same time (a second host) are not supported; the local backup lock only serialises one bundle root.
- W5: `cryptcheck` shows that the remote matches the local file at the time of the check. An object changed afterwards is found by the next push.

**Real-S3 gate.** D064 accepts this design only after the same detection claims have been shown on a real S3 remote through a crypt layer, multipart objects included (the S3 double does not produce them at the sizes tried). That proof has not been done yet (see 13.1-OPEN-DECISIONS, CR-01); until it passes, the push is tested against the S3 double only.

**Key custody.** Losing the crypt passphrase makes every backup unrecoverable: with a wrong key the bucket looks empty or garbled, and the tool refuses to continue rather than treat it as an empty store. Keep the raw passphrase (and the salt, `BACKUP_CRYPT_PASSWORD2`) off the VPS, in a password manager plus a second offline copy. The values in `.env` are `rclone obscure` output, which is reversible and is not encryption.

### 11.1 Configure the remote

1. Create a bucket (new and empty) and an access key limited to it at your provider.
2. Choose a long passphrase and a second one (the salt). On your workstation, never on the VPS, turn each into its obscured form with `rclone obscure` (read it from stdin, `rclone obscure -`, so it stays out of shell history). rclone rejects a raw passphrase.
3. Put these into the off-host secrets file that bootstrap installs as `.env` (or edit `/opt/trading/.env`, mode 0600, as the `trading` user): `BACKUP_S3_PROVIDER` (`AWS`, `Wasabi` or `Other`), `BACKUP_S3_ENDPOINT` (needed for `Other`, for example a Backblaze B2 S3 endpoint), `BACKUP_S3_REGION`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `BACKUP_CRYPT_PASSWORD` and `BACKUP_CRYPT_PASSWORD2` (the two obscured values). A missing variable stops the command and names the variable, never its value.
4. Enable provider-side protection as an operator control: bucket versioning or object lock with a retention period, so a stolen access key cannot erase history. The scripts never delete anything outside `snapshots/<id>` but cannot stop a compromised key from doing so.

### 11.2 Initialise the remote (once, on an empty bucket)

`deploy/backup.sh --init-remote [--dry-run]` stages a bundle in `data/backup/bundle` (the `backupdata` volume) and then runs `push --init-remote`, which writes the sentinel only if the decrypted listing is empty, the raw bucket listing is empty and the sentinel does not exist yet. On a non-empty bucket, or with a wrong key, it refuses.

### 11.3 Install the daily timer

`sudo deploy/backup.sh --install-timer [--dry-run]` writes `trading-backup.service` (oneshot, `User=trading`, requires docker, two-hour limit) and `trading-backup.timer` (`OnCalendar=*-*-* 03:15:00 UTC`, `Persistent=true` so a missed run happens after downtime, `RandomizedDelaySec=5m`) under `/etc/systemd/system`, substitutes this checkout's directory, runs `systemctl daemon-reload` only when a unit changed and enables the timer. It must run as root and refuses a checkout path with whitespace. Check with `systemctl list-timers trading-backup.timer`, `systemctl status trading-backup` and `journalctl -u trading-backup`.

### 11.4 Run a backup now

`deploy/backup.sh [--dry-run]` runs one scheduled backup: dump the database, back up the Parquet files, verify the bundle against its sha256 manifest, push (new Parquet files, then `cryptcheck` of the Parquet tree, then `pg.dump` and its `cryptcheck`, then a second verification of the bundle against its manifest, then `manifest.json` and its own `cryptcheck`, so a snapshot looks complete only once its files exist and have been verified), then apply retention. A failed step makes the command, and so the systemd unit, fail visibly. The backup unit itself sends no ping: a failed backup unit is visible only in systemd and the journal, and the collector heartbeat of 11.9 does not cover the backup. A monitor for the backup would be a separate check that the operator registers by hand (operator control, bootstrap checklist item 2).

### 11.5 Restore onto an empty host

Prerequisites: the host is bootstrapped (section 13), `.env` holds the same `BACKUP_*` values (the obscured passwords are derived from the raw passphrase you kept off the VPS), and the checkout is at the version you want.

`deploy/restore.sh [--snapshot ID] [--force] [--no-start] [--dry-run]`: starts only PostgreSQL; pulls the newest verified snapshot (or `--snapshot 20260930T031500Z`) into a fresh `data/backup/restore-<UTC timestamp>`; runs the refusing restore (bundle sha256 and set verification, then the empty-target checks, `pg_restore`, a never-overwriting Parquet copy into `data/raw`, `alembic upgrade head`, which upgrades a dump taken before Phase 17 through migration 0004); then starts the whole stack unless `--no-start`. It refuses a tampered bundle, a non-empty database or Parquet target unless `--force`, and aborts on any file that already exists with different content even under `--force` (raw files are immutable). Use `--no-start` to inspect the restored data before the collector runs. A failing step stops the script with that step's exit code.

### 11.6 Restore drill

`deploy/backup-drill.sh [--dry-run]` proves the whole chain without touching live data: backup, push, pull the snapshot into `data/backup/drill-<UTC timestamp>`, verify it, restore it into a scratch database named `<db>_drill_<YYYYMMDDHHMMSS>`, compare its `collector_watermarks` row count with the live one and drop the scratch database. The stack's PostgreSQL must be running. Windows keeps `scripts/backup-drill.ps1`. A backup is not valid until a drill passes: run it after setup, after any change of provider, key or image, and periodically thereafter. A collector adding a brand-new symbol row during the drill can fail the comparison; run it again.

### 11.7 Housekeeping

- `restore.sh` and the drill leave their `data/backup/restore-<timestamp>` and `data/backup/drill-<timestamp>` directories in the `backupdata` volume on purpose (no script deletes an operator path). Remove old ones by hand, for example `docker compose --profile ops run --rm -T --no-deps ops rm -r /app/data/backup/drill-<timestamp>`.
- Never run `docker compose config` without `-q` while real secrets are in `.env`: it prints the resolved environment. Use `docker compose config -q` to validate.
- The 7/4/6 numbers are the defaults of `select_retained` in `src/ops/backup_remote.py`, not an environment setting; changing them is a reviewed commit.

### 11.8 When the Parquet push fails

The push exits non-zero. Read the whole message with `journalctl -u trading-backup` (or the terminal output of `deploy/backup.sh`); its first words say which case it is. No override or force option exists, and the push never overwrites a remote object. A refusal caused by differing content (the two `parquet push refused` heads, and a `parquet verification failed` that names paths after `cryptcheck` exit 1) repeats on every rerun until the content is dealt with. A transient failure (network, an rclone exit other than 1, `snapshot id ... already exists`) can succeed on a rerun: read the message head to tell the two apart. The paths a message names are at most five, then "and N more".

- `parquet push refused: path(s) already published with different content`: a complete remote snapshot names a listed path with another SHA-256 than the local file, or two complete snapshots disagree about it ("manifests disagree"). Nothing was uploaded and no snapshot folder was created.
- `parquet push refused: remote object(s) differ from the local file(s) and no complete snapshot names them`: a listed path is already on the remote (typically left by an earlier push that died before its manifest) with content that differs from the local file. Nothing was uploaded and no snapshot folder was created.
- `parquet verification failed`: the Parquet uploads finished but `cryptcheck` found the remote Parquet tree different from the local one (a changed, missing or unreadable remote object, named in the message), or the check itself failed with an exit other than 1 (`rclone cryptcheck failed (exit N)` inside the message; read N, a network or tool failure may pass on a rerun). The check runs before `pg.dump` is uploaded: no snapshot folder, no `pg.dump` and no `manifest.json` of the new snapshot are on the remote (Parquet objects this push uploaded may be; the next push verifies and adopts them).
- `manifest verification failed: snapshot <id> left incomplete`: the manifest upload or its check failed and the manifest was removed again. The snapshot holds `pg.dump` only. The message carries the original rclone error.
- `manifest verification failed AND the manifest of snapshot <id> could not be removed`: both removal attempts failed, so that snapshot looks complete although its manifest failed its check. Remove the object `snapshots/<id>/manifest.json` through the crypt remote (its provider-side name is encrypted, so the provider console cannot find it by that name), and do not trust that snapshot until then. If the push was interrupted (Ctrl-C) during manifest publication and the removal failed too, the process still ends as a `KeyboardInterrupt` and the same text is attached to it as a note under the traceback.
- `refusing to publish manifest: bundle changed during push: <path>: sha256 mismatch`: a file of the staging bundle changed after the push had verified it and before the manifest was published. Nothing is wrong on the remote; no `manifest.json` was written, so the new snapshot holds `pg.dump` only and stays incomplete (retention purges it once a newer complete snapshot exists). The next scheduled run stages a fresh bundle; find out what writes into the bundle directory if it repeats.
- `rclone cryptcheck failed (exit N)` (the `pg.dump` check, or the check of Parquet objects left by an earlier push when N is not 1), `rclone lsf failed (exit N)`, `rclone cat failed (exit N)` (shown inside `unreadable manifest of complete snapshot <id>`), `rclone copy failed (exit N)` and `rclone copyto failed (exit N)`: the tool or the network failed, which is not a finding about content. A rerun may pass. A listing reads exit 3 as a directory that does not exist yet; any other exit, 4 included, is a failure and the push stops before it writes anything, because an empty-looking listing would otherwise hide existing snapshots. If it repeats, read the excerpt after the exit code and escalate.
- `unreadable manifest of complete snapshot <id>`: the push could not read or parse a remote manifest and refuses rather than ignore it. Nothing was uploaded.
- `snapshot id <id> already exists on the remote`: a snapshot with this UTC-second id is already complete. Nothing was written.

What to look at: the paths and the snapshot id in the message; the SHA-256 of the local file against the value in the local `manifest.json`; the remote copy, obtained with `python -m src.ops.backup pull --dest <dir> --snapshot <id>` in the compose `ops` image (the subcommand `deploy/restore.sh` runs), which verifies every pulled file against the manifest of that snapshot; the provider's object history if bucket versioning or object lock is on (11.1). Which choice is right (keep the local file, keep the remote file, treat it as possible tampering) is the operator's decision and is not made here. No override or force option exists; the factual routes are to restore the local file to the content its manifest names, or a manual action on the remote, which needs its own decision first.

**When the Parquet tree is damaged: what exists and how to recover (D066).** A snapshot is complete only when its `manifest.json` is on the remote, and the manifest is published only after the whole Parquet tree and `pg.dump` have passed `cryptcheck`. The PostgreSQL dump is therefore coupled to Parquet integrity on purpose: there is no standalone PostgreSQL backup on the remote, `pg.dump` reaches the remote only as part of a snapshot, and when the Parquet check fails the dump of that run is not uploaded at all (it stays only in the local bundle `data/backup/bundle` until the next backup run stages that bundle again, and it is not a remote backup). No setting or command publishes a snapshot whose Parquet files are not verified. Retention runs only after a successful push, so a failing night deletes no good snapshot.

A restore fails before it touches the database. `deploy/restore.sh` first runs `pull`, which copies the snapshot folder, fetches exactly the Parquet files that snapshot's manifest names and verifies the whole bundle against the manifest; a missing or altered Parquet object stops it there with `pulled bundle failed verification` and a `missing from bundle` or `sha256 mismatch` line. Only a bundle that passed is handed to `restore`, which verifies it again before any destructive step. There is no state in which the database is restored while the Parquet files fail verification.

Do not assume an older snapshot restores. The `parquet/` tree is shared by every snapshot and is never pruned, so one lost or damaged object makes every complete snapshot whose manifest names that path fail to pull. To find the newest snapshot that can be restored, try them from the newest down, each into its own empty directory: `python -m src.ops.backup pull --dest <empty dir> --snapshot <id>` through the compose `ops` image as in 11.5. The first one that pulls without error is the newest verified one; restore it with `deploy/restore.sh --snapshot <id>`. If none pulls, no verified restore point exists and the choice of how to proceed is the operator's; it is not made here. This describes the backup chain only: it does not make a backup the durable evidence record of Phase 16.

### 11.9 External heartbeat for the collector (healthchecks.io)

`deploy/heartbeat.sh` is the sender for the external, off-host monitor that D042 condition 1 asks for. The service is healthchecks.io: the user chose it on 2026-10-09 ("thêm healthchecks.io vào plan"), and the choice is recorded in decision record 16-DEC-O-12. The ping interval, the check's period and its grace are the user's values and are still open in that record. This runbook writes no number for any of them, and neither the script nor the timer supplies one (the single code default is a transport bound, described below). The facts about the monitor's HTTP interface and about systemd credentials are in `docs/SOURCES.md` ("Facts read for plan 16-50"), read on 2026-10-09 and not verified live. This sender runs once the collector is on the host (section 19); the first complete check of it is the operator verification of plan 16-50.

**What one run does.** It runs the collector probe, `python -m src.data.collector --healthcheck` inside the compose `collector` service, which is read-only (it only reads the freshness of the Open Interest and funding watermarks). Then it sends one success ping to the monitor, only while that probe passes. A failed probe sends no success ping, so a stopped or wedged collector silences the signal and the monitor alerts once the check's period plus its grace have passed. The signal therefore means only that the probe passed and that the host and the timer are running; it does not show that positions are protected (the stop-loss stays on the exchange, D042 condition 1). The probe and the ping each have a transport bound, `HEARTBEAT_STEP_TIMEOUT_SECONDS`, whose code default is copied from the collector's own probe timeout in `docker-compose.yml`. It carries the provenance label PLACEHOLDER: it only stops a hung `docker` or `curl` from freezing the timer, it is not a monitor value and it is never tuned.

**Exit codes.** The script exits with 0 (probe passed and ping delivered, or `--dry-run`), 1 (probe failed), 2 (usage error), 3 (probe passed but the ping was not delivered) or 4 (the ping URL source is missing or invalid). A failed probe wins over a failed fail ping, so exit code 1 always means the collector probe failed.

**The URL.** The ping URL the monitor gives you is a secret: whoever holds it can send a success ping and hide an outage (this is an inference; the monitor's page does not say so). It lives only in a root-only file, `/etc/trading/heartbeat.url` (mode 0600), and reaches the service through systemd `LoadCredential`, so the unprivileged `trading` account that runs docker reads a private copy. `deploy/heartbeat.sh --set-url` stores it from one line of standard input without echo, so it never enters the shell history or a process argument; `--url-file PATH` (or the variable `HEARTBEAT_URL_FILE`) selects another absolute path. The script hands the URL to `curl` on standard input, prints and logs it nowhere, refuses to run under xtrace, and accepts only one https URL made of plain characters. Never put the URL into `.env` (every container receives that file), into `acceptance.json` (the validator exits 2 on a value that looks like a ping URL), into chat, or into your shell history.

**Install.** Store the URL, then install the timer with your own interval:

```text
sudo deploy/heartbeat.sh --set-url
sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>
```

`<N>` is the ping interval the user records in 16-DEC-O-12, in seconds, and it must suit the check's period; the monitor's documentation also asks that one check is not pinged too often (`docs/SOURCES.md`). `--install-timer` refuses to run without `--interval-seconds`, so no default exists. The check's period and its grace are set in the monitor's dashboard only, never in the repository. Add `--dry-run` to either command to see what would be written. `--install-timer` writes `trading-heartbeat.service` (oneshot, `User=trading`, `LoadCredential`) and `trading-heartbeat.timer` (`OnBootSec` and `OnUnitActiveSec` both set to the interval) under `/etc/systemd/system`, runs `systemctl daemon-reload` only when a unit changed, enables the timer, and restarts it when a unit changed so a new interval takes effect. It must run as root, refuses a checkout path with whitespace, and refuses to install while the URL file does not exist (run `--set-url` first). Check with `systemctl list-timers trading-heartbeat.timer`, `systemctl status trading-heartbeat` and `journalctl -u trading-heartbeat`. There is no catch-up: the timer is not persistent and has no random delay, so no ping is sent after downtime for the time the host was down, because a catch-up ping would hide the very outage the monitor exists to report.

**Fail ping.** `--fail-ping` (or `HEARTBEAT_FAIL_PING=1`, which `--install-timer --fail-ping` writes into the service) makes a failed probe send one fail ping. It is optional because a fail ping alerts at once and bypasses the grace period, which is the user's value; without it, the silence after a failed probe is already an alert once the period plus the grace have passed.

**Fail-open.** The sender never stops or restarts the collector, and a failed ping changes only the exit code: the only `docker` subcommand the script runs is `exec` of the read-only probe, and the two units carry no dependency on, restart of or failure link to any other unit. Open Interest minutes lost to a collector stop are permanent (15.4); this sender cannot cause one.

**Scope.** This sender probes the collector only. Probes for the paper and live processes, and the external monitor's coverage of every long-running process, belong to Phase 24; nothing here changes the paper service probe. "Heartbeat" here means the external ping. It is unrelated to the paper runtime's per-bar heartbeat records (coverage evidence of the Phase 16 runtime).

## 12. Manual close

A manual position close must be explicit and recorded as:

```text
ManualExit
actor
reason
requested_at_utc
exchange_confirmation
```

After manual close, the reconciliation process must cancel orphan protective orders.

## 13. Host bootstrap

`deploy/bootstrap.sh` turns a fresh Ubuntu 22.04, Ubuntu 24.04 or Debian 12 host into a hardened Docker host with the repository checked out at a ref and `.env` installed. It uses plain apt, ufw, sshd, chrony and Docker Engine only, no provider CLI, so any provider that offers one of those images works. Any other OS is refused before anything changes. The script is idempotent (a second run announces no mutation) and `--dry-run` prints the ordered plan.

### 13.1 Prepare

1. Create the host at the provider with provider disk encryption enabled (or confirm it is on), and make sure you can log in as root over SSH with a key.
2. Build the secrets file off-host (your workstation or password manager), starting from `.env.example`. Bootstrap requires `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` to be present and non-empty and refuses any value containing `change_me`. Make the PostgreSQL password URL-safe (for example hex): compose builds the connection URL without encoding. The file must have LF line endings; a CR is refused. Keep `BINANCE_TESTNET_*` and `BINANCE_LIVE_*` in separate files for separate hosts (OPS-06): a paper host never receives a live credential. Binance live keys must have no withdrawal permission and be IP-restricted to this host (checklist, 13.5).
3. Prepare an authorized key file: at least one line that `ssh-keygen -l -f` accepts. This is the lock-out guard: bootstrap refuses to disable password login unless the `trading` user ends up with a valid authorized key (from `--authorized-keys`, or already present in its `authorized_keys`). Bootstrap also refuses to write the SSH drop-in unless the `trading` user is in the `sudo` group and `passwd -S trading` reports status `P` (a usable password), see 13.4.

### 13.2 Copy the scripts and files to the host

Copy the `deploy/` directory, the secrets file and the authorized key file to the host, for example with `scp -r deploy secrets.env authorized_keys root@host:/root/`. Shell scripts with CRLF line endings fail on Linux with `bad interpreter`. The repository forces LF for `deploy/` (`.gitattributes`) and a test scans for CRs, but a Windows working copy created before that rule can still hold CRLF files: copy from a clean checkout or `git archive`, not from an old Windows tree. Keep the secrets file out of shell history and out of the repository.

### 13.3 Dry run

As root, run the same command with `--dry-run` first, for example `sudo deploy/bootstrap.sh --dry-run --secrets-file /root/secrets.env --repo git@example.com:me/trading.git --ref v0.1.0 --authorized-keys /root/authorized_keys`. It prints the ordered `+ command` plan and changes nothing. Run it as root: without root the read-only probes (ufw, sshd, dpkg) can under-report. Read the plan, in particular the ufw and sshd lines.

### 13.4 Run it

`sudo deploy/bootstrap.sh --secrets-file PATH --repo URL --ref REF --authorized-keys PATH [--dir /opt/trading] [--user trading] [--deploy-key PATH] [--max-drift-ms 100] [--dry-run]`

`--ref` is required and should be a tag or a commit (a local branch name resolves from the local clone and can be stale). `--repo` is required unless `--dir` already holds a checkout. `--deploy-key` installs a read-only deploy key for a private repository. `--dir` defaults to `/opt/trading` and `--user` to `trading`. Order: preflight (OS, tools, root, secrets file, deploy key, authorized key), base packages (`ca-certificates`, `curl`, `git`, `ufw`, `sudo`), Docker's apt repository (deb822 `docker.sources`, `Signed-By` keyring) and Docker Engine with the compose plugin, the `trading` user in the `docker` and `sudo` groups with its authorized keys, ufw (default deny incoming, allow outgoing, an allow rule for every SSH port that `sshd -T` reports, then enable), SSH hardening (behind the sudo lock-out guard), chrony, the checkout at `--ref`, and `.env`.

- SSH hardening is a drop-in `/etc/ssh/sshd_config.d/00-trading-hardening.conf` (`PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`, `PubkeyAuthentication yes`). It is named `00-` because sshd keeps the first value it reads and cloud images ship `50-cloud-init.conf` with `PasswordAuthentication yes`. It is accepted only if `sshd -t` passes and `sshd -T` reports all four effective values; otherwise the file is removed and bootstrap stops before any reload. It also refuses when `sshd_config` has no `Include /etc/ssh/sshd_config.d/*.conf` line.
- **Sudo with a password (D062).** After hardening, root cannot log in over SSH, so `trading` is the administrator. Bootstrap installs the `sudo` package when dpkg reports it missing and runs `usermod -aG sudo trading`. There is no passwordless sudo rule anywhere: a rule that skips the password for a script `trading` can edit would be unrestricted root. `useradd` creates the account without a password, so bootstrap refuses to write the SSH drop-in (lock-out guard, checked on every real run) until `trading` is in the sudo group and `passwd -S trading` reports `P`. On a fresh host the first run therefore stops at the SSH step, after the user and ufw steps, with a message naming the fix: set the password yourself in the root session with `passwd trading` (bootstrap never sets, reads or prints it), then run the same command again; it is idempotent. The SSH key of `trading` is now effectively a root key: keep it key-only, protected and rotated like one (D042 condition 3).
- chrony replaces `systemd-timesyncd`; bootstrap runs `chronyc waitsync` and fails when the offset exceeds `--max-drift-ms` (default 100 ms). Hosts should run in UTC; the application stores UTC regardless.
- `.env` is installed with umask 077, mode 0600, owned by the `trading` user, and the mode is re-checked. No value is ever printed.
- **Keep your current root session open.** Before closing it, open a second SSH session as `trading` with your key, confirm it works and run `sudo -v` there (it asks for the `trading` password and must succeed). Only then close the first.

Optional operator choices that bootstrap does not make: install `unattended-upgrades` for security updates, and set the host time zone to UTC. ufw does not govern ports published by Docker: Docker writes its own firewall rules, so a published container port is reachable whatever `ufw status` says. The stack therefore publishes only `127.0.0.1` ports (PostgreSQL on `127.0.0.1:${POSTGRES_PORT:-5432}`); never add another published port without a deliberate decision. Membership of the `docker` group is root-equivalent: keep it to the one operator account.

### 13.5 Operator checklist (printed at the end; nothing here is automated)

1. Binance API key restricted to this host's public IP (IP whitelist), withdrawal permission off.
2. Off-VPS heartbeat monitor registered, so a silent host is noticed. The collector's sender is `deploy/heartbeat.sh` (11.9).
3. Backup crypt passphrase stored off the VPS; losing it makes every backup unrecoverable (section 11).
4. Second SSH session tested before closing the first, including `sudo -v` there.
5. Provider disk encryption enabled or confirmed.
6. `BACKUP_*` variables set in `/opt/trading/.env` and `deploy/backup.sh --init-remote` run as `trading` (section 11). Root SSH login is disabled; `trading` is in the `sudo` group and sudo asks for its password (no passwordless sudo rule). Set that password with `passwd trading` in the root session (the lock-out guard requires it) and run `sudo -v` in a SECOND SSH session as `trading` BEFORE closing the root session. Then install the timer with `sudo /opt/trading/deploy/backup.sh --install-timer` (it does not read `.env`) and use `sudo` for every later apt, ufw or systemctl change.
7. Docker group kept to this one account; only `127.0.0.1` ports published.
8. Delete the copied secrets file from the host once `.env` is verified.

### 13.6 First start

Bootstrap does not start the stack. As the `trading` user in `/opt/trading`: validate with `docker compose config -q` (never plain `docker compose config` with real secrets: it prints the resolved environment), build both images with `docker compose --profile ops build`, then `docker compose up -d`. The one-shot `db-upgrade` service runs `alembic upgrade head`; the `collector` starts after it completes successfully, and its container health check allows a six-minute start period. `docker compose ps` shows the state. To run a second stack from one checkout (tests, a rehearsal), `TRADING_ENV_FILE` selects which env file compose reads (default `.env`) and `COMPOSE_PROJECT_NAME` the project; the deploy scripts honour both. The `paper` and `live` services are placeholders (Phases 16 and 24): enabling their profiles starts nothing useful yet.

## 14. Update and rollback

`deploy/update.sh` moves the running stack to a git ref and can move it back to the exact images that ran before. Run it as the `trading` user in the checkout.

### 14.1 Before an update

Commit or discard local changes (a dirty working tree is refused), make sure the target is a tag or commit you reviewed, and rehearse `deploy/update.sh --ref <tag> --dry-run` to read the plan. Both images (`trading-alert:dev` and `trading-alert-ops:dev`, or your `IMAGE_TAG`) must exist locally: they are what a rollback returns to.

### 14.2 Update

`deploy/update.sh --ref REF [--skip-backup] [--dry-run]` records the current commit and the IDs of both images in `.deploy/last-good.env` (mode 0600, gitignored, parsed and never sourced), runs `deploy/backup.sh` (a failing backup stops the update; `--skip-backup` skips it and is a risk you take on), tags both images `:rollback`, fetches tags, checks out REF detached, runs `docker compose --profile ops build` and `docker compose up -d`. A ref starting with a dash is refused. `COMPOSE_PROJECT_NAME`, `TRADING_ENV_FILE` and `IMAGE_TAG` are honoured from the environment.

### 14.3 Roll back

`deploy/update.sh --rollback [--dry-run]` checks the state file, verifies that the `:rollback` tags still point at the recorded image IDs (a mismatch aborts before anything changes), checks out the recorded commit, re-tags `:rollback` to the active tag, compares the active tags with the recorded IDs again, and starts with `docker compose up -d --no-build`. `--ref` and `--rollback` cannot be combined.

### 14.4 Limits to know

- A rollback restores code and images only. A database **schema migration** that the newer version applied (`db-upgrade` runs `alembic upgrade head`) is **not undone**: if the older code cannot read the migrated schema, restore the pre-update backup with `deploy/restore.sh` instead (section 11.5). This is why `--skip-backup` is dangerous across a migration.
- Phase 17 (D051): the migration `0004_persistence_integrity` (unique constraints, foreign keys, CHECKs, append-only and terminal-status triggers, `execution_intents`, `plan_constraint_snapshots`, `system_state_events`) is applied by the compose `db-upgrade` service (`alembic upgrade head`, which gates the collector), not by `deploy/migrate.sh` (that script is the provider cutover). The migration chain is proven reversible and data-safe in the tests, but a rollback of code does not run `alembic downgrade`, so the 0004 constraints and triggers stay in place; if the older code cannot work with them, restore the pre-update backup as described above.
- Every `--ref` run overwrites `.deploy/last-good.env`. After a half-failed update, running `--ref` again records the half-updated state as the "last good" one. Always **roll back first** (or fix the cause), then update again.
- The first state file is written only by `--ref`; `--rollback` on a host that never updated stops with "no rollback state".

## 15. Provider migration (cutover)

`deploy/migrate.sh` moves the running collector, its Parquet store and its database from an OLD host to a NEW host with a bounded, reported data gap, and never shuts anything down.

### 15.1 Preconditions

- Both hosts are bootstrapped (section 13) and run the Phase 13.1 ops image; the old host must already have it (`docker compose --profile ops build` at a Phase 13.1 ref), because the old side runs `src.ops.backup dump` and `src.ops.cutover` in it.
- Take and drill a fresh backup first (section 11).
- Your account on the machine where you run the script can `ssh` to the old host non-interactively (`BatchMode`, strict host key checking, so the old host must already be in `known_hosts`), and the ssh user on the old host can run `docker compose` and `docker run` (docker group).
- A migration key directory (`--key-source`, default `~/.ssh/trading-migrate`, or a named docker volume) holds `id_ed25519` and `known_hosts` for the old host. Generate the key for this purpose only, add its public half to the old host's authorized keys, and fetch the host key from a channel you trust. It is mounted read-only into the receiving container and never copied into an image. Remove it after the cutover.

### 15.2 Dry run

`deploy/migrate.sh --dry-run <old-ssh-target> local` prints the ordered plan and executes nothing. Run it on the NEW host with `local` as the second argument; a remote new-host target is refused, because the rsync arguments would lose their quoting through a second ssh hop.

### 15.3 Run

`deploy/migrate.sh [--dry-run] [--max-gap-minutes N] [--wait-seconds S] [--key-source PATH_OR_VOLUME] [--report-only] <old-ssh-target> local`, for example `deploy/migrate.sh --key-source ~/.ssh/trading-migrate trading@old.example local`. Fixed order: (1) preflight, including the refusal to continue if either side already holds `data/backup/cutover/pg.dump` from an earlier attempt (inspect and remove it by hand; it would otherwise be skipped and silently reused); (2) Parquet pre-sync while the old collector keeps running; (3) stop the old collector, the only thing ever stopped on the old host; (4) final Parquet sync; (5) on the old host `pg_dump`, a Parquet fingerprint and a watermark snapshot; (6) pull those artifacts; (7) restore on the new host (dump hash verified, then `alembic upgrade head`); (8) start the new collector, which resumes from its restored watermark; (9) wait for its first new tick (`--wait-seconds`, default 900; a timeout is not fatal, the report then shows the trailing gap); (10) the cutover report.

Transfers are rsync over ssh run in the new host's `ops` container as root, with `--ignore-existing`, no delete option of any kind, atomic temp files excluded and strict host key checking against the mounted `known_hosts`. By default the remote side runs `docker run` of the ops image on the old host with the old named volumes mounted read-only (`--rsync-path`, D-20). The documented fallback is `sudo rsync` on the volume mount points under `/var/lib/docker/volumes/<project>_rawdata/_data` (and `_backupdata`), which needs sudoers and the script's fixed source paths `/data/raw/` and `/data/backup/cutover/` to exist on the old host, for example as symlinks, and set through `MIGRATE_RSYNC_PATH`. That fallback is not scripted or tested; if you need it, do the sync steps by hand. Other overrides for non-default topologies are the `MIGRATE_*` variables described at the top of the script (`MIGRATE_OLD_DIR` default `/opt/trading`, `MIGRATE_OLD_PROJECT` default `trading`).

### 15.4 Read the report

The report compares the old and new Parquet fingerprints (set equality of path and sha256, so one lost or changed file is loss), the watermark rows, and measures the Open Interest gap the switch caused in minutes. The exit code of `migrate.sh` is the report's:

| Exit | Meaning |
| --- | --- |
| 0 | clean: nothing lost, OI gap within the threshold |
| 1 | data loss: a Parquet file or watermark row is missing, changed or went backwards |
| 2 | input error: unreadable artifact or bad argument |
| 3 | the OI gap is above `--max-gap-minutes` (default 60 minutes) |

Open Interest history is only available from Binance for roughly the last month and not backfillable at this resolution, so OI gap minutes are **permanent loss**: the report says so. Funding-rate gaps are **recoverable** by the backfill tools. Exit 3 is data, not a failure to retry: decide whether the hole matters for the research. `--report-only` recomputes the new side's fingerprint and watermarks and re-prints the report against the stored old-side artifacts (for example with a tighter `--max-gap-minutes`).

### 15.5 If it stops halfway

If a step fails after the old collector was stopped, the script prints the exact `... start collector` command that resumes collecting on the old host. Nothing on the old host was removed, so resuming loses nothing but time.

### 15.6 After a clean report

Only a human shuts the old host down, and only after exit 0 (and, if you want extra safety, a fresh drill on the new host). The script never runs `down`, never powers off and never deletes. Update the Binance IP whitelist for the new host's public IP, move the heartbeat monitor and re-run the section 13.5 checklist on the new host. Remove the migration key directory.

## 16. Image and action pins

Every base image is pinned by exact tag plus the multi-architecture index digest, every GitHub Action by full commit SHA, and uv and Python by exact version (D050; 13.1 D-05). The values below were read from the registries and from `git ls-remote` on 2026-10-01 (research session, re-read when plans 02 and 03 were executed; method in `SOURCES.md`, "Facts verified for Phase 13.1"). `tests/test_deploy_docs.py` parses these tables and fails when they differ from what `Dockerfile`, `docker-compose.yml`, `.github/workflows/*.yml`, `tests/docker_helpers.py`, `tests/fixtures/cutover/Dockerfile.sshd` and `.python-version` actually use, so the table and the files can only move together.

| Image | Tag | Digest | Used in |
| --- | --- | --- | --- |
| python | 3.13.15-slim-bookworm | sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 | Dockerfile, tests/fixtures/cutover/Dockerfile.sshd |
| postgres | 17.11-bookworm | sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652 | docker-compose.yml, .github/workflows/ci.yml, tests/docker_helpers.py |
| uv | 0.12.21 | sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 | Dockerfile |
| rclone | 1.75.1 | sha256:45401ad7410db1d67ffdb58e19059ad20b0d8e0285a60e38bbec55cc1019c7a5 | Dockerfile, tests/docker_helpers.py |

| Tool | Version | Used in |
| --- | --- | --- |
| uv | 0.12.21 | `version:` of every `astral-sh/setup-uv` step in the four workflows; equals the uv image tag |
| python | 3.13.15 | `.python-version` (read by CI) and the python image tag |

| Action | Tag | Commit SHA |
| --- | --- | --- |
| actions/checkout | v7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| actions/setup-python | v7.0.0 | 5fda3b95a4ea91299a34e894583c3862153e4b97 |
| astral-sh/setup-uv | v10.2.0 | c18668ad3cf93ea998bef934396af7bb5c839dc7 |
| actions/cache | v6.1.0 | 55cc8345863c7cc4c66a329aec7e433d2d1c52a9 |
| actions/upload-artifact | v7.0.1 | 043fb46d1a93c77aae656e7c1c64a875d1fc6a0a |

`actions/cache` covers both the `restore` and the `save` sub-actions. The pinned `docker compose` and `docker` versions on a host are whatever Docker's apt repository serves at bootstrap time; they are not pinned (bootstrap installs the current packages).

### 16.1 Reading the pins

`deploy/refresh-pins.sh --list` runs offline and prints every pin parsed from the repository files, one line per image as `<name>:<tag>@sha256:<digest>`, then `uv-version`, `python-version` and one `<owner/repo>@<sha> <tag>` line per action. A test proves that output equals the tables above.

### 16.2 Deliberate refresh procedure

Bumps are never automatic (automatic image and action bumps are a deferred idea, D050). To refresh:

1. Run `deploy/refresh-pins.sh --lookup`. It asks each registry (anonymous token, then a HEAD request for `docker-content-digest`) and `git ls-remote` for the current value and prints `unchanged` or `MOVED` next to every pin. It needs `curl` and `git`, reads only, and never edits a file.
2. Read the release notes of every moved item before accepting it (uv, Python, PostgreSQL 17 minor, rclone, each action).
3. Change every occurrence and this section's tables in one commit: `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `registry-gate.yml`, `research-gate.yml`, `paper_freeze_check.yml`, `tests/docker_helpers.py`, `tests/fixtures/cutover/Dockerfile.sshd`, `.python-version`. Use the index digest of the tag (it is stable across amd64 and arm64), not a per-architecture digest.
4. Run `uv run pytest tests/test_deploy_docs.py tests/test_deploy_images.py tests/test_deploy_workflows.py`, then let CI build and run the docker job before deploying. After a Python or PostgreSQL major or minor change, rehearse `deploy/update.sh --ref <tag>` on a non-production host first.

The single conscious exception to D-05 is `postgresql-client-17` in the `ops` image target. It comes from the PostgreSQL project's apt repository (key fingerprint checked at build time) and floats within major 17 by design, because that repository drops old minor versions and a pinned minor would break the image build. The server image stays pinned. A `pg_dump`/`pg_restore` 17 client must be at least as new as the 17 server.

## 17. Tested locally or in CI versus needs a real host

Every step of sections 11, 13, 14 and 15 is listed once, with where it was proven. The labels in the "Tested by" column mean:

- **local test**: a pytest test that ran on the development machine (Windows with Git Bash) and runs again in CI. For the deploy scripts this means real bash against stub binaries (`docker`, `ssh`, `ufw`, `sshd`, `systemctl`, `chronyc`, `git` that record their arguments), so ordering, flags, exit codes and idempotency are proven but no real command ran.
- **CI docker job**: a `docker`-marked test (or the compose and image steps) that `.github/workflows/ci.yml` runs with `uv run pytest -m docker`. It is written and statically checked; at the time of writing it has run nowhere, because the development machine's Docker daemon cannot build the images (no egress to apt or PyPI from containers). Its first execution is the first green remote run, confirmed by pushing to the private repository and reading the Actions result (plan 13.1-12). Until that run is green, treat these rows as unproven.
- **real host (operator)**: only a real Linux host, a real provider or a real exchange account can show it; nothing in this repository exercised it. The operator checks it by following the procedure and the checklist.

| Step | What | Tested by | Notes |
| --- | --- | --- | --- |
| 11.1 | Configure the remote (BACKUP variables, obscured passwords) | local test; real host (operator) | env mapping, missing-variable errors and the `.env.example` names are unit-tested; a real provider account, bucket protection (versioning or object lock) and key custody are operator steps |
| 11.2 | Initialise the remote | local test; CI docker job | stubbed wrapper order and the sentinel and empty-bucket logic are tested locally, and the real rclone 1.75.1 against `rclone serve s3` test (2 tests) ran locally; a real provider bucket is not covered |
| 11.3 | Install the daily timer | local test; real host (operator) | the units are written under a path prefix with a `systemctl` stub and are idempotent; systemd timer firing, `Persistent=true` catch-up and the `trading` user are real-host only |
| 11.4 | Run a backup now | local test; CI docker job; real host (operator) | wrapper and exit-code propagation are stubbed; the backup chain with a real PostgreSQL 17 `pg_dump` runs in the CI docker drill; the Parquet push decision, the tree check and the manifest removal are pinned by fake-runner tests and by real-rclone tests against an S3 double; a real S3 provider and the real bucket at scale are real-host only |
| 11.5 | Restore onto an empty host | local test; CI docker job; real host (operator) | restore refusals, hash verification and the never-overwrite rule are unit-tested with fakes; `pg_restore` into a real PostgreSQL 17 and the restore into a second empty project are CI docker job only (not run locally); a real bucket and a real fresh host are real-host only |
| 11.6 | Restore drill | local test; CI docker job | same split as 11.5; the scratch-database create and drop helpers have not run against a real server locally |
| 11.7 | Housekeeping (old restore and drill directories, object lock, heartbeat, key custody) | local test; real host (operator) | the retention function is proven against a 400-day oracle; everything else is a manual or provider-side control |
| 11.8 | When the Parquet push fails | local test; real host (operator) | the message heads listed in 11.8 are pinned by fake-runner tests and the main cases by real-rclone tests against an S3 double; what the operator decides, and the behaviour on a real S3 provider (D064 real-S3 gate, pending), are real-host only |
| 11.9 | External heartbeat for the collector (healthchecks.io) | local test; real host (operator) | the script is run through real bash against stub `docker`, `curl` and `systemctl` binaries (probe, success and fail ping, exit codes 0 to 4, the URL absent from every output, the fail-open check, `--set-url`, `--install-timer` with no default interval, the unit templates), and the real `curl` option set against a closed loopback port; real delivery to the monitor, systemd credential delivery to the `trading` user, the timer firing and the monitor's alert can be shown only on a real host |
| 13.1 | Prepare (disk encryption, secrets file, authorized key) | local test; real host (operator) | secrets-file validation and the lock-out guard are tested with stubs; provider disk encryption and the real keys are operator steps; the sudo group, the password guard and the checklist text are tested with stub binaries |
| 13.2 | Copy the scripts and files to the host | local test; real host (operator) | LF-only, CR scan and executable-bit tests run locally; the copy itself is manual |
| 13.3 | Dry run | local test | `--dry-run` plan and "changes nothing" are tested through real bash with stubs |
| 13.4 | Run bootstrap | local test; real host (operator) | step order, idempotency and refusals are tested with stub binaries; Docker apt repository install on each OS release, real ufw, sshd and chrony effects, the ssh reload on Ubuntu 24.04 and the Docker plus ufw interplay are real-host only; shellcheck on the scripts runs only in CI; the sudo group, the password guard and the checklist text are tested with stub binaries |
| 13.5 | Operator checklist | real host (operator) | Binance IP whitelist, heartbeat monitor, provider disk encryption and passphrase custody cannot be tested from the repository; the sudo password prompt and `sudo -v` in a second session are real-host checks |
| 13.6 | First start | CI docker job; real host (operator) | compose config is tested locally against a real `docker compose config`; the image build, `db-upgrade` against a real PostgreSQL and the collector health probe are CI docker job only; a real host start is manual |
| 14.1 | Before an update | local test | dirty-tree refusal and the image-presence check are tested with stubs |
| 14.2 | Update to a ref | local test; real host (operator) | order (backup, tags, checkout, build, up) is tested with a tag-modelling docker stub; a real build on the host is manual |
| 14.3 | Roll back | local test; real host (operator) | the update-then-rollback round trip and the image-ID identity checks are tested with stubs; a real rollback on a real host is manual |
| 14.4 | Limits (migration not undone, last-good overwrite) | local test | the migration warning is asserted; the `last-good.env` overwrite behaviour is documented, not prevented |
| 15.1 | Preconditions | real host (operator) | two hosts, the migration key, host keys and the ops image on the old host cannot be tested here |
| 15.2 | Dry run | local test | the ordered plan with no execution is tested with stubs |
| 15.3 | Run the cutover | local test; CI docker job; real host (operator) | order, no delete option, collector-only stop and strict host key checking are tested with stubs; the full run between two Compose projects over an sshd and rsync sidecar is CI docker job only (not run locally, the sidecar image build was not verified either); real ssh between two providers, the `docker run` rsync path and the `sudo rsync` fallback are real-host only |
| 15.4 | Read the report | local test; CI docker job | fingerprint comparison, watermark comparison, gap minutes and exit codes 0, 1, 2 and 3 are unit-tested; the two-project run asserts the report JSON in CI |
| 15.5 | If it stops halfway | local test | the resume hint after a failure past the old-collector stop is tested with stubs |
| 15.6 | After a clean report | real host (operator) | a human shuts the old host down, updates the IP whitelist and the heartbeat; the script never does |

### Only a real host can show

- Docker's apt repository and package install on each of Ubuntu 22.04, Ubuntu 24.04 and Debian 12.
- The real effect of ufw, sshd (the drop-in winning over `50-cloud-init.conf`) and chrony, and the ssh reload semantics under Ubuntu 24.04 socket activation (`systemctl try-reload-or-restart ssh`).
- The Docker plus ufw interplay: ports published by Docker bypass ufw, and whether enabling ufw after Docker leaves container egress working (research assumption A2).
- The `docker run` rsync path over real ssh without a tty (assumption A7) and the unscripted `sudo rsync` fallback.
- A systemd timer firing and catching up after downtime; provider disk encryption; the Binance IP whitelist; the heartbeat monitor (a real ping, systemd credential delivery and the alert, 11.9).
- Restore of a real bucket at scale and a real provider-to-provider cutover.

### Not run locally during Phase 13.1

On the development machine these did not run, and they are verified only in CI or on a host: the Docker image builds (`runtime` and `ops`), the four image smoke tests, the cutover test (sidecar build, sshd key login, two-project run), the backup drill test, `pg_restore` and `alembic upgrade head` against a real PostgreSQL 17, shellcheck, and anything that touches real ufw, sshd, chrony or systemd. What did run locally: the stub-driven bash tests for every deploy script, the compose configuration tests against a real `docker compose config`, `docker build --check` (which also proves all four digests resolve), the redaction tests, the bundle, restore, retention and cutover unit tests, and the two real-rclone tests.

Facts assumed and not executed (ASSUMED or MEDIUM) are listed in `SOURCES.md`, "Facts verified for Phase 13.1".

## 18. CI pipeline

`.github/workflows/ci.yml` runs on every push and pull request to `master` with `contents: read` permission, one run per ref (a newer push cancels the older run), `UV_PYTHON_DOWNLOADS=never` and **`TRADING_CI_STRICT=1`**. Strict mode turns every infrastructure skip (no bash, no Docker daemon, no compose, no shellcheck) into a failure, so a run can never pass by skipping. It needs no Binance, Telegram or registry secret and pushes and deploys nothing. Actions are pinned by commit SHA (section 16). The jobs run in parallel on `ubuntu-24.04`:

| Job | What it runs | If it is red, run locally |
| --- | --- | --- |
| test | `uv run pytest -m "not docker"` with a digest-pinned PostgreSQL 17 service (`TEST_DATABASE_URL`), full git history | `uv run pytest -m "not docker" -rs` |
| lint | `uv lock --check`, `uv run ruff check`, `uv run ruff format --check` (the format check also covers fenced Python blocks in `.planning/**/*.md`) | the same three commands |
| types | `uv run mypy src` | `uv run mypy src` |
| docker | copy `.env.example` to `.env`, `docker compose config -q` for the default and all profiles, shellcheck of `deploy/*.sh` (fails if there are none), `docker compose --profile ops build`, `uv run pytest -m docker -rs` | the same commands; the image build needs Docker and egress |

How to read a red run: open the failed job, then the failed step. A skipped-test failure that mentions `TRADING_CI_STRICT=1` means infrastructure is missing on the runner, not that the code is wrong. A lint or types failure reproduces locally with the commands above. In the docker job the compose steps fail on a syntax or interpolation error (they are quiet on purpose: a resolved config would print the interpolated environment into the log), the shellcheck step fails with the SC code and line, and a failing docker-marked test prints the scrubbed script output in its assertion message.

Three older workflows keep their logic and now share the same pins: `registry-gate` and `research-gate` run on pull requests and pushes to master, and `paper_freeze_check` is a scheduled and manually dispatchable workflow. They are referenced, not merged.

**D-23 serial-run note.** `tests/test_backfill_cli.py` showed rare intermittent failures on the Windows development machine under heavy load (about 1 run in 15 to 30 while Docker pulls and a second pytest ran concurrently; the test returns exit code 1 from its generic exception branch). It was never changed and no retry, marker or suppression was added. CI runs the suite serially on a fresh Linux runner; if that test fails there, treat it as a real finding. It is logged in `.planning/phases/13.1-deployment-ci/deferred-items.md`.

## 19. Soak host (EC2) provisioning, migration and data path

This section is text for the person who creates the host (D061 hosts, D042, D-34). The repository never creates, changes or deletes an AWS resource, and no step here runs from a test. Every AWS, rclone and distribution fact below carries its URL and the read date 2026-10-08; those facts come from `16-RESEARCH-GAPS-RESULT.md`, were read through a fetch tool that summarises the page, and are **not verified live**: before a decision depends on a fact, read the page again. A number the user owns (instance type, EBS size, budget amount, S3 lifecycle and retention) is never written here: wherever one is needed the text says "value from decision record 16-DEC-O-12".

### 19.1 Prerequisites

1. The host runs Ubuntu 22.04, Ubuntu 24.04 or Debian 12, because `deploy/bootstrap.sh` refuses any other OS (section 13). The region is ap-southeast-1 (Singapore), D061 hosts.
2. WR-05 (D062) is implemented: commit 7148528 makes `trading` a sudo user with a password and no passwordless rule (13.4, 13.5). The D064 Parquet push is implemented (commit e9a030c and D066, section 11) and tested against an S3 double only; its real-S3 gate is still open (the "Real-S3 gate" paragraph in section 11).
3. The development machine can run the checks in 19.5 (`docker compose --profile ops`) and holds the off-host copy of the secrets file and the backup passphrases (section 11, "Key custody").
4. A text file named `acceptance.json` is kept on the development machine, not on the host and not in git. It holds one entry per condition id of 19.3 with `status`, `command`, `evidence` (a short excerpt) and `checked_at` (UTC). Never paste a key, token, password or the content of `.env` into it. `uv run python scripts/soak_host_acceptance.py acceptance.json` exits 0 only when every condition is `PASS` with a command, an evidence excerpt and a UTC time; it exits 1 and names the first missing or non-PASS condition; it exits 2, without printing the value, when a field holds something that looks like a secret.
5. Only the OI collector moves on the provisioning weekend (19.4). The Phase 16 paper runtime does not exist yet at that point.

### 19.2 First action on the instance: public ping to fapi.binance.com

Before anything is installed or configured, log in to the new instance and run, on the instance:

```text
curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping
```

Pass condition: the printed status is `200` (HTTP 200). This is condition `REGION_PING_FAPI` of 19.3. Run it again after the Elastic IP is associated if the instance first used another public address, because Binance sees the address the instance actually uses.

If it fails (any other status, a timeout or a TLS error), stop: do not install anything, the region or IP is not accepted. Record the output as evidence and report it. Choosing another region or address is a new decision for the user; this section does not make it.

### 19.3 Acceptance per D042 condition

One row per condition id. Run the command (on the host, or on the development machine where the AWS CLI is configured; `<...>` marks a value you look up), copy the result into `acceptance.json` as `evidence` (an excerpt, never a secret), and set `status` to `PASS` only when the pass condition holds. The source column says where the fact came from: a decision or runbook section of this repository, or an external page with its URL and read date, labelled "not verified live". Rows whose source says "AWS CLI help" use a command that was not read from a documentation page in the research pass: run `aws <service> <command> help` first and correct the command in your evidence if the installed CLI differs. The region of every AWS command is `--region ap-southeast-1`.

| Condition id | Command | Pass condition | Source |
| --- | --- | --- | --- |
| `REGION_PING_FAPI` | `curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping` on the instance (19.2) | prints `200` | D042 condition 4; D061 hosts (repository decisions) |
| `ELASTIC_IP` | `aws ec2 describe-addresses --region ap-southeast-1` and `aws ec2 describe-instances --region ap-southeast-1 --instance-ids <instance id>` | the address you use for ssh and for the Binance IP whitelist is an allocated Elastic IP with an association to this instance, and `PublicIpAddress` of the instance equals it | D042 condition 4; AWS CLI help |
| `EBS_ENCRYPTED_BY_DEFAULT` | `aws ec2 get-ebs-encryption-by-default --region ap-southeast-1` | the output reports `"EbsEncryptionByDefault": true` | https://docs.aws.amazon.com/ebs/latest/userguide/encryption-by-default.html (read 2026-10-08, not verified live) |
| `EBS_ROOT_VOLUME_ENCRYPTED` | `aws ec2 describe-volumes --region ap-southeast-1 --filters Name=attachment.instance-id,Values=<instance id>` | every volume attached to the instance reports `"Encrypted": true` | D042; operator checklist item 5 (13.5); AWS CLI help |
| `S3_BUCKET_PRIVATE` | `aws s3api get-public-access-block --bucket <backup bucket>` | all four block settings report `true`; no bucket policy or ACL grants public access | D042 condition 2; AWS CLI help |
| `S3_DEFAULT_ENCRYPTION` | `aws s3api get-bucket-encryption --bucket <backup bucket>` | a default encryption rule is reported (SSE-S3 is the default of every bucket); SSE-KMS is not required, and the objects are ciphertext anyway because the backup chain encrypts on the host (section 11) | https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-encryption-faq.html (read 2026-10-08, not verified live) |
| `S3_VERSIONING` | `aws s3api get-bucket-versioning --bucket <backup bucket>` | the output reports `"Status": "Enabled"` | https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html (read 2026-10-08, not verified live); 11.1 item 4 |
| `HEARTBEAT_MONITOR_ALERT_RECEIVED` | on the host in `/opt/trading`, with the 11.9 sender installed: `docker compose stop collector`, wait longer than the check's period plus its grace (the values of decision record 16-DEC-O-12), then `docker compose start collector` | an alert from the external monitor reached the operator while the collector was stopped, and a recovery notice followed the start; record both times in UTC | D042 condition 1; 11.9; 13.5 item 2 |
| `CHRONY_SYNCED` | on the host: `chronyc tracking` and `chronyc sources` | `chronyc sources` lists `169.254.169.123` with a selected-source marker, and the `System time` offset of `chronyc tracking` is below the bootstrap limit (`--max-drift-ms`, default 100 ms, 13.4); the `chronyc` field names come from chrony, not from the AWS page, so read `man chronyc` if they differ | https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configure-ec2-ntp.html (read 2026-10-08, not verified live); D042 condition 5 |
| `BUDGET_ALERT` | `aws budgets describe-budgets --account-id <account id>` and `aws budgets describe-notifications-for-budget --account-id <account id> --budget-name <budget name>` | at least one budget exists and has a notification with a subscriber; the amount is the user's (value from decision record 16-DEC-O-12) | https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/ (read 2026-10-08, not verified live) |
| `PAID_PLAN` | open the Billing and Cost Management console in a browser and read the account plan (a console check, no command) | the plan is a paid plan, not the free plan; record the plan name and the date | D061 hosts (the Free Tier page read on 2026-10-07 says a free-plan account closes on its own after 6 months or when credits run out; not verified live) |
| `SSH_KEY_ONLY` | on the host `sudo sshd -T`; from the development machine `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no trading@<elastic ip>` | `sshd -T` shows `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitrootlogin no` and `pubkeyauthentication yes`, and the ssh attempt is refused with `Permission denied (publickey)` | D042 condition 3; 13.4 |
| `POSTGRES_NOT_PUBLIC` | on the host `docker compose ps postgres` and `sudo ss -ltn`; `aws ec2 describe-security-groups --region ap-southeast-1 --group-ids <security group id>` | PostgreSQL is published on `127.0.0.1` only, no listener for its port is bound to `0.0.0.0` or `::`, and the security group has no inbound rule for the PostgreSQL port | D042 condition 3; 13.4 |
| `ENV_FILE_MODE_0600` | on the host `stat -c "%a %U" /opt/trading/.env` | prints `600 trading` | D042 condition 3; 13.4 |
| `SUDO_WITH_PASSWORD` | in a second ssh session as `trading`: `sudo -k` then `sudo -v`; also `passwd -S trading` | `sudo -v` asks for the password and succeeds, and `passwd -S trading` reports status `P` | D062 (WR-05); 13.4, 13.5 item 6 |
| `BACKUP_REAL_S3_GATE` | the commands recorded by the D064 real-S3 proof; no script of this repository runs that proof yet, so the entry quotes the id of the task whose record holds the commands and their output | the record shows, on a real S3 remote through the crypt layer with multipart objects included, that `rclone cryptcheck` detects a same-size different-content change, an object modified after upload and an object deleted after upload (D064 verification gate); until then the status is not `PASS` and no real backup runs | D064; 11 ("Real-S3 gate") |

**EBS encryption by default (G12).** It is a Region-specific setting, it does not change existing volumes, and the page read on 2026-10-08 does not say what its initial state is for a new account or Region: that initial state is not documented, so do not assume it. Run `aws ec2 get-ebs-encryption-by-default --region ap-southeast-1` before the instance volume is created. If it reports `false`, turning it on is `aws ec2 enable-ebs-encryption-by-default --region ap-southeast-1`; that changes an account setting, so it is your decision, and the alternative is to create the root volume with encryption requested explicitly and then record `EBS_ROOT_VOLUME_ENCRYPTED` (https://docs.aws.amazon.com/ebs/latest/userguide/encryption-by-default.html, read 2026-10-08, not verified live).

**Chrony (G14, D-35).** Amazon Linux 2023 is configured by default to use the Amazon Time Sync Service at `169.254.169.123` with chrony, but Amazon Linux is not a `deploy/bootstrap.sh` OS. On Ubuntu the AWS page gives manual steps: install `chrony` (bootstrap does) and add the line `server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4` to `/etc/chrony/chrony.conf`, then restart chrony (`sudo systemctl restart chrony`). The page does not say a stock Ubuntu image already has it ("your AMI might already have configured" it), and it does not cover Debian 12: read `chronyc sources` on the host and do not assume (https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configure-ec2-ntp.html, read 2026-10-08, not verified live). The runtime reads UTC only (D-35); nothing in this repository monitors drift after start (D042 condition 5 asks for drift monitoring, a later plan).

**Heartbeat monitor.** The service is healthchecks.io, by the user's decision of 2026-10-09; its check period, its grace and the ping interval are the user's values and belong in 16-DEC-O-12, not here. The sender is `deploy/heartbeat.sh` (11.9): it pings only while the collector probe passes, so stopping the collector silences the signal and the monitor alerts once the period plus the grace have passed. The URL a monitor gives you is a secret: it lives in the root-only file that `--set-url` writes and never in `acceptance.json`, and `scripts/soak_host_acceptance.py` exits 2, without printing the value, on a field that looks like a ping URL. Stopping the collector interrupts collection, and Open Interest minutes lost that way are permanent (15.4): run this check where that cost is accepted and record the resulting gap as a coverage gap (19.4).

**Costs.** An in-use public IPv4 address, an Elastic IP included, is billed at $0.005 per hour (https://aws.amazon.com/vpc/pricing/, read 2026-10-08, not verified live). AWS Budgets monitoring and notifications are free of charge (https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/, read 2026-10-08, not verified live). Instance type, EBS size, budget amount and S3 lifecycle are not written here: value from decision record 16-DEC-O-12; the compute, storage and request prices were not readable in the research pass and stay unverified.

### 19.4 Bootstrap and collector migration

On the provisioning weekend only the collector moves: the host holds PostgreSQL and the OI/funding collector, nothing else. The paper runtime comes later (the long soak follows Phase 16, D061 hosts). Until the host runs the collector, the collector keeps running where it is and its gaps stay recorded.

1. **Bootstrap.** Follow section 13 on the new instance after the 19.2 ping passed: prepare (13.1), copy (13.2), dry run (13.3), run (13.4), operator checklist (13.5). Set the `trading` password and test `sudo -v` in a second ssh session before closing the root session (WR-05). Do not use the first-start step of 13.6 beyond `docker compose config -q` and `docker compose --profile ops build`: `docker compose up -d` would start a collector that writes into the new database before the cutover, and the cutover restores into an empty one.
2. **Real-host checks of UAT 8, UAT 9 and UAT 10** (13.1-OPEN-DECISIONS, listed in section 17 as "real host (operator)"): UAT 8 is the bootstrap run on the real host; UAT 9 is the cutover between two real hosts with the systemd backup timer firing; UAT 10 is the restore of a real bucket, provider disk encryption, the Binance IP whitelist and the off-VPS heartbeat monitor. Record each in the evidence file of the plan that owns the weekend.
3. **Migration.** Run `deploy/migrate.sh` on the NEW host as described in section 15 (dry run first, 15.2; run, 15.3). Precondition to check before the weekend (15.1): the old machine must accept non-interactive ssh with strict host key checking and its user must be able to run `docker compose` and `docker run`. If the old machine is a Windows Docker Desktop host this is not given; if the precondition cannot be met, stop and report. The alternative path (a backup pushed from the old machine and `deploy/restore.sh` on the new host) has a longer gap, needs the D064 real-S3 gate first and is a separate decision for the user.
4. **Report.** Read the report (15.4). Exit 0 means nothing was lost and the OI gap is within the threshold; exit 3 is data, not a failure to retry. The OI gap printed by `deploy/migrate.sh` is recorded as a coverage gap (D059 item 4, L-14): every gap after 2026-10-08 is written down with its start, end and cause, and the dataset is never called full history while a known gap exists. The Open Interest history Binance serves is limited to roughly the latest month (`docs/SOURCES.md`), so the minutes cannot be backfilled.
5. **After a clean report** only a human shuts the old collector's machine down, updates the Binance IP whitelist to the Elastic IP and moves the heartbeat monitor (15.6): the check's ping URL is stored on the new host with `--set-url` and the timer installed (11.9) before the old host's timer is disabled. Then run the acceptance checks of 19.3 in order and validate the file: `uv run python scripts/soak_host_acceptance.py acceptance.json`.
6. **Backups.** The first real backup waits for the D064 real-S3 gate (section 11, "Real-S3 gate"; condition `BACKUP_REAL_S3_GATE`). A restore drill (11.6) runs on the host before the long soak, and so does the first verified pull to the development machine (19.5). A backup is not valid until a drill passes (11.6).

### 19.5 Pulling research data to the development machine

The research data (Parquet, plus the PostgreSQL dump in the same bundle) reaches the development machine over the existing backup chain: the host pushes a snapshot to the encrypted off-host store (section 11) and the development machine pulls it. No ssh from the development machine to the host is involved.

Prerequisites. The development machine holds the same `BACKUP_*` configuration as the host (11.1), including both obscured crypt passwords, so the passphrases and a bucket access key then exist on a second machine and the key custody rules of section 11 apply to it as well. The images are built there (`docker compose --profile ops build`). At least one complete snapshot exists on the remote: the first real backup waits for the D064 real-S3 gate (19.4).

1. Pull and verify. Replace `<UTC timestamp>` with the current UTC time as `YYYYMMDDTHHMMSSZ`; the destination must not exist or be empty:

```text
docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup pull --dest /app/data/backup/pull-<UTC timestamp>
```

   The newest complete snapshot is used. To pull a named one add `--snapshot <snapshot id>` (an id of the form `YYYYMMDDTHHMMSSZ`, listed by the push output `push-OK snapshot=<id>`). On success it prints `pull-OK snapshot=<id> dest=...`. The pull copies the snapshot folder, fetches exactly the Parquet files the manifest names and checks every file against the manifest SHA-256; a missing or altered object stops it with `pulled bundle failed verification` (11.8). The interpreter is the venv one (`/app/.venv/bin/python`) because bare `python` in the image is the base interpreter without the project packages (the comment above the health check in the `Dockerfile`).

2. Verify the pulled bundle once more, independently of the pull:

```text
docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup verify --bundle-root /app/data/backup/pull-<UTC timestamp>
```

   Exit 0 means every file hashes to its manifest entry and the file set equals the manifest. Anything else: stop, do not copy.

3. Copy the verified Parquet tree into the development raw root without overwriting anything:

```text
docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python -m src.ops.backup restore --bundle-root /app/data/backup/pull-<UTC timestamp> --parquet-target /app/data/raw --skip-db --force
```

   `--skip-db` restores the Parquet files only and leaves the development database alone. `--force` is needed only because the development raw root already holds data; it does not allow overwriting. The command verifies the bundle again, checks every target path before it copies anything, skips a file that already exists with identical content and copies the rest through a temporary name. The copy must never overwrite an existing file, because raw files are immutable: if a path already exists in the target with different content the command aborts with `already exists in the target with different content` and copies nothing. That is a finding to investigate (T-16-18), not a reason to delete the target file or to rerun with another option; no option exists that overwrites.

Rules. Pulled files enter the research raw root only through step 3, after steps 1 and 2 succeeded; never copy files out of the pulled bundle by hand. The `pull-<UTC timestamp>` directory stays in the `backupdata` volume until you remove it by hand (11.7). Loading the PostgreSQL dump of the bundle into a development database is a different step (`restore-db`) and is not part of this data path.

### 19.6 Durable evidence storage study (REV-08)

Question under study: where the Phase 16 evidence (`pinned_epoch.json`, `registry_diff.jsonl`, coverage artifacts, exit-criteria output) is kept durably, with S3 as the canonical copy and a Git manifest of hashes as the index. This section collects facts and their interaction with the backup chain as it is now (`src/ops/backup_remote.py`, re-read for D064 and D066). It selects nothing.

**Facts.** Each carries its page and the read date; all are not verified live (summarised by a fetch tool, `16-RESEARCH-GAPS-RESULT.md`).

- Object Lock works only in buckets that have S3 Versioning enabled (https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html, read 2026-10-08, not verified live).
- Object Lock can be enabled on an existing bucket, once S3 Versioning is on; once enabled it cannot be disabled and versioning cannot be suspended (https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-configure.html, read 2026-10-08, not verified live).
- GOVERNANCE versus COMPLIANCE. In COMPLIANCE mode no user, root included, can overwrite or delete a protected object version, and the mode and period cannot be shortened. In GOVERNANCE mode a version is protected unless the user has the `s3:BypassGovernanceRetention` permission and sends the bypass header (https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html, read 2026-10-08, not verified live).
- A bucket default retention (days or years) is a bucket property applied to every object version placed in the bucket; the retain-until date is computed from each version's creation time; an explicit per-object retention setting overrides the bucket default. The pages describe no per-prefix default. An object that is already in the bucket is not described as changed by a later default (https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-configure.html, read 2026-10-08, not verified live).
- A permanent delete of a locked version (a delete request with a version id) returns 403 Access Denied; a simple delete (no version id) returns 200 OK and inserts a delete marker (https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html, read 2026-10-08, not verified live).
- Versioning cost: normal S3 rates apply for every version of an object (https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html, read 2026-10-08, not verified live). Whether Object Lock itself has a separate charge is UNVERIFIED: neither the Object Lock pages nor the pricing page read stated one.
- rclone crypt: "Hashes are not stored for crypt"; `rclone cryptcheck` is the check to use instead of `rclone check`, and it needs a checksum on the underlying remote (https://rclone.org/crypt/ and https://rclone.org/commands/rclone_cryptcheck/, read 2026-10-08, not verified live).
- rclone with S3 Object Lock: it computes and sends Content-MD5 when Object Lock parameters are set, accepts a retention mode and date, shows versions with `--s3-versions`, and `rclone backend cleanup-hidden` deletes old hidden versions (https://rclone.org/s3/, read 2026-10-08, not verified live). What `rclone purge` does for a path inside a versioned bucket, and what it does when it meets a locked version, is UNVERIFIED: the purge page says only "Remove the path and all of its contents" (https://rclone.org/commands/rclone_purge/, read 2026-10-08, not verified live).
- GitHub Actions cache entries not accessed for over 7 days are removed, and the default repository limit evicts the oldest first (https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching, read 2026-10-08, not verified live). Git hashes do not make S3 immutable, and an Actions cache is never a source of truth.

**Interaction with the backup chain.**

1. Readability. The chain writes through an rclone `crypt` layer, so object names and contents in the bucket are ciphertext. Evidence written through that remote is unreadable off-host, by the GitHub runner or by an auditor, without `BACKUP_CRYPT_PASSWORD` and `BACKUP_CRYPT_PASSWORD2` (research S2 interaction 1); handing those to GitHub widens the exposure of the key. Evidence stored outside the crypt layer is a different remote with its own configuration mapping.
2. Integrity. Crypt stores no plaintext hash, so ETags and rclone checksums say nothing about plaintext. The chain relies on `rclone cryptcheck` after each upload and on the SHA-256 manifest inside each snapshot (`push_snapshot`). A Git manifest of SHA-256 values would be an independent plaintext check for evidence files; it is an index, not protection of the S3 objects.
3. Writes. `push_snapshot` uploads Parquet and `pg.dump` with `--immutable`, never deletes `parquet/`, and removes only a just-published `manifest.json` that failed its check (`rclone deletefile`, two attempts). Uploads without overwrite are compatible with versioning and with Object Lock. This is an inference, not tested: under a bucket default retention that compensating `deletefile` would at most add a delete marker (a simple delete, 200 OK), and whether rclone issues a permanent delete of the locked version instead is UNVERIFIED.
4. Retention. `apply_retention` deletes `snapshots/<id>` folders with `rclone purge` and raises `RemoteError` on a non-zero exit, which turns the scheduled backup red; it runs only after a push has been verified. This is an inference: under a COMPLIANCE default on the backup bucket a permanent delete of a locked version returns 403 (above), so the purge would be refused until the lock expires, but the behaviour of `rclone purge` on a locked or versioned path is UNVERIFIED, so it may also fail differently or leave hidden versions. With versioning only, a purge leaves hidden old versions and storage is not freed until `rclone backend cleanup-hidden` or a lifecycle rule for noncurrent versions runs; no such control exists in the repository and it is an operator action (value from decision record 16-DEC-O-12). A backup bucket and an evidence bucket should therefore not silently share one default retention; per-object retention on evidence writes is the alternative, since the default is bucket-wide.
5. Sentinel. `check_sentinel` and `init_sentinel` assume a dedicated bucket that is completely empty at `--init-remote`; evidence objects must not be placed in the bucket before it, and a second remote needs its own configuration mapping.
6. Provider-side protection. RUNBOOK 11.1 item 4 already asks for bucket versioning or object lock as an operator control; no code checks it and no test can prove it is on (section 17, row 11.7).
7. Host loss. Journal rows reach the development machine through `pg.dump` in the daily snapshot (11.3, 11.4), so on loss of the host up to a 24 hour loss window of evidence is exposed unless evidence is published more often or at event time.

Not covered by any source read: whether Object Lock changes the S3 request or storage price (UNVERIFIED), the exact IAM actions rclone needs for retention calls, and the real-S3 behaviour of the D064 gate itself (19.3, `BACKUP_REAL_S3_GATE`).

No option is selected here; the decision is O-01 (plan 16-30).

### 19.7 Things only the host can show

The list at the end of section 17, "Only a real host can show", holds the apt install on each OS, ufw/sshd/chrony effects, the Docker and ufw interplay, the `docker run` rsync path, a systemd timer firing, provider disk encryption, the Binance IP whitelist, the heartbeat monitor, a real bucket at scale and a real provider-to-provider cutover. Every check of 19.3 and every UAT item of 19.4 belongs to that list: no test in this repository shows any of them. `tests/test_soak_runbook.py` proves only that this section names commands that exist and that the validator behaves as described.

## 20. Soak project operations

This section says how the soak project is operated once it exists on the soak host (19) and the paper runtime is built. It applies D-32 and the reviewer decisions REV-01, REV-03 and REV-17 (D063, D065). It writes no number the user owns: the trial window, the 95 percent coverage and the 14 days are L-04 values (D061), and the O-07 and O-12 values stay in their decision records.

### 20.1 Project and wrapper

The soak is its own compose project, `trading-soak`, with its own volumes (`trading-soak_pgdata` and the others), apart from the development stack and from the rehearsal (20.4). Every soak command goes through `deploy/compose-soak.sh`; no hand-typed raw `docker compose` command is used for the soak. The wrapper pins the project, refuses a `-p` or `--project-name` that names another project and refuses `down` together with `-v` or `--volumes`. The volume-removing form (`down -v`, or `down --volumes`) is never run on `trading-soak`: its database volume holds the soak evidence, and the runbook shows no such command. If a volume ever has to go, it is a by-hand action on the host after a restore drill (20.5), never through the wrapper.

```text
TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d
deploy/compose-soak.sh ps
deploy/compose-soak.sh logs paper
deploy/compose-soak.sh stop paper
```

The environment file for the soak is made from `deploy/soak.env.example`: names only, no trade-capable name (`BINANCE_` anything makes the runtime refuse to start, D-13).

**Exit codes of `python -m src.paper.runtime`.** The compose command passes `--hold-on-refusal` and the restart policy is `on-failure`, which restarts on any non-zero status and has no per-code exclusion list. The table below is what keeps a refusal from becoming a restart loop (T-16-110). It lists every member of `ExitCode` in `src/paper/runtime_config.py`.

| Name | Code | Meaning and what happens |
| --- | --- | --- |
| `OK` | 0 | a clean stop, or SKIPPED because the paper-start allowlist admits nothing; exits 0 and is not restarted |
| `USAGE` | 2 | a malformed command line (argparse's own status); the command line does not change on a restart, so fix the compose command |
| `TRADE_KEY_REFUSED` | 3 | a trade-capable variable name is present in the environment; refusal |
| `CONFIG_NOT_RATIFIED` | 4 | the runtime configuration file is not ratified; refusal |
| `NO_PINNED_EPOCH` | 5 | no pinned epoch; refusal |
| `ADMISSION_OR_EPOCH_MISMATCH` | 6 | the allowlist admission or the epoch does not match; refusal |
| `FAIL_CLOSED_RUNTIME` | 7 | the runtime failed closed on a condition a restart can clear (lost data, lost connection); restarted, and the time shows as a CRASH gap |

A refusal (codes 3 to 6) can never succeed on a retry, because only a human action changes the outcome. With `--hold-on-refusal` the process logs the refusal and stays up, so the paper container is up and unhealthy instead of looping. The operator reads the refusal reason in the container log (`deploy/compose-soak.sh logs paper`) and must stop the container before correcting the cause (remove the variable, ratify the file, pin the epoch, fix the allowlist), then starts it again. SKIPPED exits 0 and is not restarted. A crash, or code 7, is restarted by the compose policy and appears as a CRASH gap in the coverage evidence: it is uncovered like every other gap (20.2).

### 20.2 Deploys during the trial soak

Every stop or deploy during the trial is a PLANNED_RESTART (glossary) and is never covered: the coverage denominator is the whole fixed trial window, only HEALTHY time counts, and a gap that has a reason is still uncovered (REV-01). The trial is 14 calendar days, which is 336 h; 95 percent of 336 h leaves about 16.8 h for all uncovered time together (REV-17): planned restarts, crashes, DEGRADED time, disconnects and maintenance share that one budget. A deploy therefore spends budget that no crash may need, so batch changes, prefer a change before the trial starts, and keep the stop short.

- Stop the paper service cleanly (`deploy/compose-soak.sh stop paper`) rather than killing the container: a clean stop writes the stop record, and the gap then carries the reason PLANNED_RESTART; a killed process shows as a CRASH gap. Both are uncovered.
- Write down the UTC time and the cause of each stop and deploy next to the evidence; the audit reads the gap reason, but the cause is only in your note.
- A change of the image, the allowlist or the runtime configuration during the trial is a restart and spends the budget above; changing any ratified L-04 value before the trial starts needs a new user approval (L-04).
- Never run the volume-removing form of `down` to "start clean": it deletes the evidence of the trial (20.1).

### 20.3 Telegram bot

The soak uses a separate bot, by the user's decision recorded in `decisions/16-DEC-Q-L.md` (16-DEC-Q-L, option `separate-bot`). The user creates the bot with BotFather and the token is never pasted anywhere: not into a chat with an assistant, not into this repository, not into an evidence file and not onto a command line. It reaches the host only through the soak environment file of 20.1, which is not committed.

### 20.4 Rehearsal before the trial

The pre-soak rehearsal of the SHADOW APPROVE, CONFIRM, journal path (REV-03, glossary `test_only`) runs before the trial in its own project, `trading-rehearsal`, with its own volumes and its own environment file, and never in trading-soak. Its records carry the rehearsal marker and are excluded from every count: signals, trades, parity evidence, the exit criteria G1 to G5 and PAPER-03. It does not bypass the paper-start allowlist. When the rehearsal is finished, the trial soak starts from a clean state of its own project; the soak database is not used as a scratch pad for the rehearsal at any point.

### 20.5 Backups and restore drill before the long soak

Before the long soak starts, the host has a verified backup chain: a backup run now (11.4) that completes, then the restore drill (11.6) that passes. A backup is not valid until a drill passes. The drill restores into a scratch target, the scratch database that the drill creates and drops, and never into the soak database: a restore into the soak database would replace the evidence it is supposed to protect. The first real backup waits for the D064 real-S3 gate (section 11, "Real-S3 gate"; 19.4 item 6), and the first verified pull to the development machine (19.5) is part of the same readiness. Run the drill again after any change of provider, key or image (11.6).

### 20.6 Image

The soak never runs from a working-tree bind mount: the paper service runs from an image built from a named commit, not from the files of a checkout. How that image is produced is the user's decision of 2026-10-10, recorded in `decisions/16-DEC-Q-I.md`: option `host-build-recorded`, build on the host at a recorded commit. No CI step pushes an image (D050 deferred the registry), so the image is not CI-produced; the commit and the image id are what the evidence cites. The options `registry` and `ci-save-transfer` were considered and are not automatic fallbacks: adopting either later is a new user decision, and `registry` also needs a new DECISIONS entry because it reopens D050.

On the soak host, in the checkout, with the commit to run checked out and nothing else changed:

```text
deploy/soak-image.sh --dry-run
deploy/soak-image.sh
IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d --no-build
```

`deploy/soak-image.sh` refuses a dirty working tree (any uncommitted change, tracked or untracked, because the working tree is the build context). It builds `trading-alert:<commit>` and `trading-alert-ops:<commit>` with the soak wrapper, where `<commit>` is the full 40 character output of `git rev-parse HEAD`, checks that the tree and HEAD did not change during the build, and records the commit and both image ids in `.deploy/soak-image.env` (mode 0600, gitignored; the previous record is kept as `soak-image.env.prev` and every build is appended to `.deploy/soak-image.history`). The soak starts only from an image built this way, with `IMAGE_TAG` set to the recorded `GIT_SHA`; `--no-build` keeps compose from building anything else. Before the start, `docker image inspect --format '{{.Id}}' trading-alert:<commit>` must print the recorded `APP_IMAGE_ID`. The trial evidence names `GIT_SHA` and `APP_IMAGE_ID` from that file, and the host needs the build toolchain that the image build uses (`docker compose --profile ops build`, section 13.6).

The paper-start allowlist is a source constant (O-04, plan 16-42), so the image must be rebuilt after the allowlist commit: an image built before that commit carries the earlier allowlist. Build, record and start only after the allowlist commit exists.

**Relation to `deploy/update.sh`.** `deploy/update.sh` (14) updates the ordinary stack: it records `.deploy/last-good.env`, checks out a ref, builds and starts, and it does not go through `deploy/compose-soak.sh`, so the guard of 20.1 does not apply to it. It is not used for the soak project: every `--ref` run overwrites `last-good.env` (14.4), while `soak-image.env` and the history file are the record of which image the soak ran. A deploy during the trial is a new commit, `deploy/soak-image.sh`, `deploy/compose-soak.sh stop paper` and a start with the new `IMAGE_TAG`, and it is a PLANNED_RESTART (20.2). To return to an earlier image, start again with the `IMAGE_TAG` of an earlier line of the history file (the older image stays on the host, because tags are per commit); that is also a PLANNED_RESTART, and a database schema migration applied by the newer image is not undone (14.4).

### 20.7 Exporting trial evidence

This is the procedure for getting the evidence of one epoch off the soak host and into the place the user chose, and for reading the hourly freeze ticks back from GitHub (plan 16-47; D-22, L-01, REV-02, REV-08, REV-18). It applies three decision records and invents no value: `decisions/16-DEC-O-01.md` (where evidence is kept), `decisions/16-DEC-Q-F.md` (how the hourly check gets its pin) and `decisions/16-DEC-Q-Q.md` (the cron minute).

**What the records say.**

- **Where (O-01, option a).** An S3 evidence prefix outside the backup crypt remote, with its own remote and its own credential. Versioning is enabled; there is no Object Lock and no retention. Object Lock can be added later but never removed, so it is the user's later decision, not part of this procedure.
- **Reader.** The recorded reader is project owner only (the user). GitHub never reads this store: the pin reaches GitHub through a commit (below), so no credential for the evidence store is ever placed on GitHub.
- **Crypt layer.** The evidence is written outside the backup crypt remote, so it is not ciphertext to a holder of the evidence remote's credential and no crypt passphrase is needed to read it. It is also not covered by the encryption of the backup chain (11); what protects it is the bucket policy the user sets in plan 16-49, not this procedure. The two records are compatible because the workflow reads the pin from a commit and never from the store.
- **Write timing and loss window.** `exporter-schedule`, hourly: the operator runs the export and publish steps below every hour, and nothing on the host writes evidence by itself. The loss window is what was recorded on the host since the last successful publish: at most the last hour while the hourly runs succeed, longer for every skipped or failed run, and everything not yet published if the host disk is lost. The database backups of 11 are a separate copy with their own window; this store is not a backup of the database.
- **Pin source (Q-F, `commit-pinned-state`).** After each pin the user commits `evidence/paper/pinned_epoch.json` to `master`. The workflow step "Use the committed pinned epoch" copies that file to the path the freeze CLI reads before every check, with no secret and with the read-only token it already had. With no committed file there is no pin and a cached copy is removed. A new pin needs a new commit; until then a rollover is seen again at every tick. The Actions cache keeps only the diff log between ticks and is never a source of truth (L-01): caches unused for 7 days are removed.
- **Cron (Q-Q).** The workflow runs `34 * * * *`, the user's own choice; the reconciler's slot grid is HH:34. A scheduled workflow change takes effect only on `master` (G15), so plan 16-43 checks `origin/master` before the pin. A minute off the top of the hour is a mitigation of unproven effect on delayed or dropped scheduled runs (G15, REV-18): a missing tick is still an EVIDENCE_GAP, never filled and never counted as clean.

**1. Fetch the GitHub run list and the diff log.** Run this where the operator is logged in to GitHub (`gh auth login` is the operator's own step; no token is written into the repository, an environment file or a command line). The run list and its records expire (90 days by default, `docs/SOURCES.md`), so fetch before then and copy the files to the host.

```text
gh api repos/<owner>/<repo>/actions/workflows/paper_freeze_check.yml/runs --paginate --method GET -F per_page=100 --jq '.workflow_runs[]' | jq -s '.' > <github-runs-file>
gh run download <run-id> --repo <owner>/<repo> --name registry-diff-<run-id> --dir <download-dir>
```

`<run-id>` is the newest run of the list. The diff log of that run (`registry_diff.jsonl` in `<download-dir>`) is the whole log up to that tick, because the cache carries it from tick to tick; an earlier run's artifact is a shorter copy of the same log. The exporter refuses a run list that is not a list of runs. These two commands were not run on the development machine (no network): the first run on the real repository is the operator's check of the shape.

**2. Export one epoch on the host.** The state comes from the soak database through the environment names the runtime already uses (`DATABASE_URL_SYNC` or `DATABASE_URL`); the URL is never typed on the command line. `<pinned-epoch-file>` is the committed `evidence/paper/pinned_epoch.json` (repeat `--pinned` with an archived pin when an earlier epoch is exported).

```text
python scripts/export_soak_evidence.py --source pg --epoch <epoch-id> --pinned <pinned-epoch-file> --diff-log <download-dir>/registry_diff.jsonl --github-runs <github-runs-file> --config <runtime-config> --window-start <window-start-utc> --window-end <window-end-utc> --out <new-bundle-dir>
```

The bundle is one epoch, written to a new directory (an existing one is never overwritten) with `manifest.json` last. A secret-looking value anywhere in it stops the export (exit 3) and removes the partial bundle.

**3. Publish and verify.** Either add `--publish <remote:bucket/prefix>` to the command above, or publish an exported bundle on its own:

```text
python scripts/export_soak_evidence.py publish --bundle <new-bundle-dir> --destination <remote:bucket/prefix>
```

`<remote:bucket/prefix>` is an rclone remote the operator configures for the evidence bucket, using rclone's own configuration or environment for that remote; the repository holds no default and no name for it. The command refuses a destination that carries a credential, a local path, and the backup remotes `BACKUPS3` and `BACKUPS3CRYPT` (exit 2, before anything is exported). Objects go to `<epoch-id>/<file>` under the prefix, every file first and `manifest.json` last, each with `rclone rcat --immutable`; a prefix that already holds a manifest is never published over. Then every object is read back and compared with the manifest sha256: exit 0 prints "published and verified"; exit 4 names the file that failed and keeps the local bundle for another attempt. Run it as the hourly step of the recorded schedule; a failed run is simply repeated, and it is never edited by hand.

**4. Evaluate.** Copy the bundle to the development machine (19.5) and run `python scripts/evaluate_trial_soak.py --bundle <new-bundle-dir> --config <runtime-config> --q-d-decision <q-d-decision-file> --out <evaluation-file>`; the bundle is checked against its manifest first, and a gap reconstructed from the run list plus the expected slots is an EVIDENCE_GAP (REV-02).

**Not shown by any test.** Publishing to a real bucket, the output shape of `gh api` and `gh run download`, and the bucket policy are checked only by the operator on the real accounts; `tests/test_soak_evidence_export.py` publishes to an injected fake and `tests/test_paper_freeze_workflow_pin_source.py` holds the workflow to the three records.
