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

`deploy/backup.sh [--dry-run]` runs one scheduled backup: dump the database, back up the Parquet files, verify the bundle against its sha256 manifest, push (new Parquet files, then `cryptcheck` of the Parquet tree, then `pg.dump` and its `cryptcheck`, then a second verification of the bundle against its manifest, then `manifest.json` and its own `cryptcheck`, so a snapshot looks complete only once its files exist and have been verified), then apply retention. A failed step makes the command, and so the systemd unit, fail visibly. Nothing in this repository pings an external monitor: unless you register an off-VPS heartbeat or dead-man's-switch service that expects a daily signal, a dead host or a failed unit stays silent (operator control, bootstrap checklist item 2).

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
2. Off-VPS heartbeat monitor registered, so a silent host is noticed.
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
- A systemd timer firing and catching up after downtime; provider disk encryption; the Binance IP whitelist; the heartbeat monitor.
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
