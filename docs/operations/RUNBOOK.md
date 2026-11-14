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

SAFE_MODE is left only by the operator exit with its readiness rows (section 21.1), never by a restart, a timer or a recovered feed.

## 3. Position without confirmed stop

```text
SAFE_MODE
→ alert immediately
→ query Binance authoritative position
→ query protective/algo orders
→ if the stop was never confirmed ACTIVE and REST proves it absent, the system places it again under the same client id at the original plan SL (never wider), at most once per coordinator step and only until `max_unprotected_ms`; if the stop was confirmed ACTIVE and is later lost, it is never re-placed: the position is closed with a reduce-only order (D077)
→ if the SL is rejected or not acknowledged, close the position with a reduce-only order, then send a HIGH alert
→ manual intervention is optional, not required
```

The automatic ladder is per D034 and D077: the operator works full-time and cannot be assumed to react within minutes. The operator's control for a confirmed-then-lost stop is the close (`operator_close_position`, `EXECUTION_SPEC.md` section 11); there is no operator re-placement of that stop.

**Implementation status:** the ladder above (D034, narrowed by D077) is built in Phase 20 and composed into the live process in Phase 24 (`python -m src.live.runtime`, section 22; the coordinator places the stop after a fill is seen, `/close SYMBOL` is the operator's close, section 21.1a). It is tested with fakes and was observed once on Binance Demo: the smoke rehearsal of 2026-11-06 (21 steps, section 22.6) saw an entry fill, a REST-confirmed stop and the TP legs. What no run has shown: the ladder's timeouts firing on a real exchange, an emergency close, and anything on a host (the owner VPS session of plan 24-33 has not happened) `[NOT_TESTED]`. Live placement stays disabled (`LIVE_ORDERS_DISABLED`). Until the owner has run the system on the host, treat the ladder as unproven there: on an entry without a protective stop, place the stop-loss or close the position manually on the exchange. Do not wait for an automatic action.

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
now - last_expected_closed_candle > freshness threshold (a NOT_CONFIGURED key, see below)
```

Action:

```text
NO NEW SIGNALS
NO NEW ENTRY ORDERS
→ reconnect/re-bootstrap
→ validate candle continuity
→ resume only after health check
```

The freshness thresholds of the live execution path are not defaults in code: `stale_feed.max_mark_price_age_ms` (60000 ms, D089), `stale_feed.max_user_data_silence_ms` (420000 ms, D091) and the reconcile cadence `reconcile.tick_interval_ms` (15000 ms, D089) are keys of `config/execution/execution-limits-v1.toml`. While any required key is `NOT_CONFIGURED` the live path refuses; do not invent a value. Since Phase 20 the reconcile tick enters SAFE_MODE `STALE_FEED` when the mark price of a tracked symbol or the user-data stream is stale; the live process runs that tick (section 22), tested with fakes and seen clean on the Demo smoke run of 2026-11-06 (`reconcile_clean`); a stale feed itself was not provoked on Demo `[NOT_TESTED]`. The scheduled tick skips itself while a placement is outstanding and for one tick after it (D097), so a healthy placement is not compared half-written. A feed time ahead of the clock by more than the ratified `[drift]` skew of `config/binance/binance-limits-v1.toml` counts as stale, not fresh. A persisted REST gate deadline later than its record time plus the largest policy wait is not trusted: the gate starts as `GATE_STATE_UNKNOWN` and the operator clears it (section 21.3).

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

**Real-S3 gate.** D064 accepts this design only after the same detection claims have been shown on a real S3 remote through a crypt layer, multipart objects included (the S3 double does not produce them at the sizes tried). The real-S3 result is still pending (see 13.1-OPEN-DECISIONS, CR-01): it exists only once the owner has run the procedure below against the real remote and it printed `RESULT: PASS`; until then the push is tested against the S3 double and against the directory fake of `tests/test_backup_gate.py` only. By the owner's decision of 2026-10-20 it runs on the soak host at deploy time, before the first real soak backup (plan 16-43 checklist, step 1a).

How to run it: `deploy/backup-real-s3-gate.sh [--dry-run]` prints the plan (the throwaway prefix and every claim) from `python -m src.ops.backup real-s3-gate` in the compose `ops` image and makes no remote call; `deploy/backup-real-s3-gate.sh --execute [--evidence-dir DIR]` runs it and copies the output into `DIR/d064-real-s3-gate-<UTC>.txt` (default `DIR` is `$HOME/trading-evidence`, outside the checkout), also when a claim fails; `--dry-run` with either form prints the docker command only. `COMPOSE_PROJECT_NAME` and `TRADING_ENV_FILE` select the project and env file, so `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup-real-s3-gate.sh --execute` gates the soak bucket. The remote is the one of the `BACKUP_*` names, built by the same mapping as the backup (`rclone_env`), so it gates whatever backend that mapping produces; with `BACKUP_REMOTE=none` it refuses (exit 2). Every object it writes lives under a new prefix `d064-gate-<UTC>-<12 hex>` directly below the configured bucket (a name rclone's default crypt name encoding never produces, so it cannot collide with the backup's own objects); the run refuses (exit 2, nothing written) unless that prefix lists empty, gives each scenario its own crypt root and sentinel below it, and purges the whole prefix in every exit path (Ctrl-C and SIGTERM included); a failed purge is itself a FAIL that names the prefix to remove by hand. With bucket versioning or object lock on (11.1 step 4) the purged objects stay as noncurrent versions until the provider's retention removes them; they are a few MiB of ciphertext. The evidence lists one `CLAIM <id>: PASS` or `FAIL` line per claim and ends with `RESULT: PASS` or `RESULT: FAIL`; it names the provider and region, never the bucket (shown as `<bucket>`) or a key. Claims: new paths upload and the snapshot completes; an unchanged file is skipped by the manifest SHA-256 comparison; a published path changed locally (same size, other size) is refused with nothing uploaded; a new path next to published ones uploads alone; the newest snapshot pulls back and verifies; an object left by an interrupted push is adopted when identical and refused when different; `cryptcheck` detects a remote object changed through the crypt layer, a ciphertext object overwritten at the provider, and a deleted object; a check failure right after the upload leaves the snapshot incomplete; a manifest that fails its own check is removed; a multipart object (12 MiB, `--multipart-mib`, uploaded with the S3 upload cutoff and chunk size forced to 5 MiB) uploads and verifies, passes unchanged, and is detected when changed; the prefix is purged. Exit 0 means every claim passed, 1 a claim failed or the run was interrupted, 2 a usage or configuration error. Re-run it after any change of provider, rclone version or image. Not shown by the script: that an object really was stored in parts (the script forces the part size, it does not read the provider's ETag), and the cost figures of the double above on the real provider.

**Key custody.** Losing the crypt passphrase makes every backup unrecoverable: with a wrong key the bucket looks empty or garbled, and the tool refuses to continue rather than treat it as an empty store. Keep the raw passphrase (and the salt, `BACKUP_CRYPT_PASSWORD2`) off the VPS, in a password manager plus a second offline copy. The values in `.env.backup` are `rclone obscure` output, which is reversible and is not encryption.

**Local-only mode (no off-host copy, 261020-bkp).** By default a missing `BACKUP_S3_*` variable stops every backup command (fail closed); that does not change. An operator who has no remote yet can opt in explicitly with `BACKUP_REMOTE=none` in the backup env file the backup container reads (`.env.backup`, or the file named by `TRADING_BACKUP_ENV_FILE`, which defaults to `TRADING_ENV_FILE` when only that is set; `BACKUP_REMOTE` empty or `s3` is the default remote, any other value refuses). Then `deploy/backup.sh` (and the timers of 11.3, unchanged) makes and verifies the local bundle in `data/backup/bundle`, and `deploy/backup-drill.sh` copies that verified bundle into its `drill-<UTC timestamp>` directory, verifies it again and restores it into the scratch database exactly as in 11.6; neither contacts any remote, and both exit 0 on success. Every such run prints a multi-line warning on stderr whose first line is `OFF-HOST COPY SKIPPED: this backup does not survive the loss of this host`, and the machine-readable line `OFFSITE_COPY=skipped` on stdout (the journal of the unit keeps both); a run against the remote prints `OFFSITE_COPY=verified` instead. `deploy/backup.sh --init-remote` refuses in this mode (exit 2, nothing to initialise), as do `push`, `pull` (so `deploy/restore.sh`) and `retain`. A local-only backup is not an encrypted copy outside the host, so it does not meet the minimum of this section, and it never satisfies the soak pin (20.5). A later backend that is not S3-compatible would be a new value of `BACKUP_REMOTE` and its own mapper; none exists yet.

### 11.1 Configure the remote

1. Create a bucket (new and empty) and an access key limited to it at your provider.
2. Choose a long passphrase and a second one (the salt). On your workstation, never on the VPS, turn each into its obscured form with `rclone obscure` (read it from stdin, `rclone obscure -`, so it stays out of shell history). rclone rejects a raw passphrase.
3. Put these into the backup env file `/opt/trading/.env.backup` (template `.env.backup.example`, mode 0600, owned by the `trading` user; compose hands it to the `backup` and `ops` services only, plan 24-36), not into `.env`: `BACKUP_S3_PROVIDER` (`AWS`, `Wasabi` or `Other`), `BACKUP_S3_ENDPOINT` (needed for `Other`, for example a Backblaze B2 S3 endpoint), `BACKUP_S3_REGION`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `BACKUP_CRYPT_PASSWORD` and `BACKUP_CRYPT_PASSWORD2` (the two obscured values). A missing variable stops the command and names the variable, never its value.
4. Enable provider-side protection as an operator control: bucket versioning or object lock with a retention period, so a stolen access key cannot erase history. The scripts never delete anything outside `snapshots/<id>` but cannot stop a compromised key from doing so.

### 11.2 Initialise the remote (once, on an empty bucket)

`deploy/backup.sh --init-remote [--dry-run]` stages a bundle in `data/backup/bundle` (the `backupdata` volume) and then runs `push --init-remote`, which writes the sentinel only if the decrypted listing is empty, the raw bucket listing is empty and the sentinel does not exist yet. On a non-empty bucket, or with a wrong key, it refuses.

### 11.3 Install the daily timer

`sudo deploy/backup.sh --install-timer [--dry-run]` writes `trading-backup.service` (oneshot, `User=trading`, requires docker, two-hour limit) and `trading-backup.timer` (`OnCalendar=*-*-* 03:15:00 UTC`, `Persistent=true` so a missed run happens after downtime, `RandomizedDelaySec=5m`) under `/etc/systemd/system`, substitutes this checkout's directory, runs `systemctl daemon-reload` only when a unit changed and enables the timer. It must run as root and refuses a checkout path that the units cannot carry: the path may hold only letters, digits and `. _ / + = , ~ -` (no whitespace, no `%`, which systemd reads as a specifier, and no `&`), the rule of `--soak-env-file` below. Check with `systemctl list-timers trading-backup.timer`, `systemctl status trading-backup` and `journalctl -u trading-backup`.

`sudo deploy/backup.sh --install-soak-timer --soak-env-file <path> [--dry-run]` (plan 16-55) installs the soak project's pair, `trading-soak-backup.service` and `trading-soak-backup.timer`, the same way: same schedule, `COMPOSE_PROJECT_NAME=trading-soak`, and `TRADING_ENV_FILE` and `TRADING_BACKUP_ENV_FILE` both set to the absolute soak env file path. It refuses a soak env file whose `BACKUP_S3_BUCKET` is empty or equals the bucket of the trading backup env file (`TRADING_BACKUP_ENV_FILE`, default this checkout's `.env.backup`). It compares the values and prints names only. Both files are read the way Compose reads them (plan 16-65): comment lines skipped, an optional `export ` prefix, the last assignment wins, surrounding quotes and an unquoted ` # comment` removed; a value it cannot determine without Compose (a `$` interpolation, a backslash, an unterminated quote, or a bare `BACKUP_S3_BUCKET` line without `=`, whose value Compose takes from the process environment) refuses the install, so write the bucket as a plain `BACKUP_S3_BUCKET=name` line. The `--soak-env-file` path may hold only letters, digits and `. _ / + = , ~ -` (no `%`, which systemd reads as a specifier, and no `&`), as for `deploy/heartbeat.sh`. Each project backs up into its own bucket, because the remote layout has no project component (20.5). The existing `trading-backup` pair is not touched.

### 11.4 Run a backup now

`deploy/backup.sh [--dry-run]` runs one scheduled backup: dump the database, back up the Parquet files, verify the bundle against its sha256 manifest, push (new Parquet files, then `cryptcheck` of the Parquet tree, then `pg.dump` and its `cryptcheck`, then a second verification of the bundle against its manifest, then `manifest.json` and its own `cryptcheck`, so a snapshot looks complete only once its files exist and have been verified), then apply retention. A failed step makes the command, and so the systemd unit, fail visibly. The backup unit itself sends no ping: a failed backup unit is visible only in systemd and the journal, and the collector heartbeat of 11.9 does not cover the backup. A monitor for the backup would be a separate check that the operator registers by hand (operator control, bootstrap checklist item 2).

### 11.5 Restore onto an empty host

Prerequisites: the host is bootstrapped (section 13), `.env.backup` holds the same `BACKUP_*` values (the obscured passwords are derived from the raw passphrase you kept off the VPS), and the checkout is at the version you want.

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

**Live runtime heartbeat (plan 24-24).** The live process has its own external check and its own URL file, never the collector's or the paper's. Store the URL with `sudo deploy/heartbeat.sh --target live --set-url` (URL on stdin) and install the timer with `sudo deploy/heartbeat.sh --target live --install-timer --interval-seconds 60`. Check with `systemctl list-timers trading-live-heartbeat.timer`, `systemctl status trading-live-heartbeat` and `journalctl -u trading-live-heartbeat`. A run pings only while `python -m src.live.runtime --liveness` passes.

**Fail ping.** `--fail-ping` (or `HEARTBEAT_FAIL_PING=1`, which `--install-timer --fail-ping` writes into the service) makes a failed probe send one fail ping. It is optional because a fail ping alerts at once and bypasses the grace period, which is the user's value; without it, the silence after a failed probe is already an alert once the period plus the grace have passed.

**Fail-open.** The sender never stops or restarts the collector, and a failed ping changes only the exit code: the only `docker` subcommand the script runs is `exec` of the read-only probe, and the two units carry no dependency on, restart of or failure link to any other unit. Open Interest minutes lost to a collector stop are permanent (15.4); this sender cannot cause one.

**Scope.** Without `--target` (or with `--target collector`) this sender probes the collector only, exactly as above. The separate paper heartbeat of the soak project is the same script with `--target paper`: its own check, its own URL file and credential, its own units, and an install that names the soak env file with `--soak-env-file`; it is described in 20.9 (plan 16-56). The live runtime has the same script with `--target live` (Phase 24, plan 24-24, DECISIONS D106; section 22.5): its own check, URL file and units. The external monitor's coverage of every long-running process is therefore one check per process, collector, paper and live; nothing here changes the paper service's container healthcheck. "Heartbeat" here means the external ping. It is unrelated to the paper runtime's per-bar heartbeat records (coverage evidence of the Phase 16 runtime).

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
2. Build the secrets file off-host (your workstation or password manager), starting from `.env.example`. Bootstrap requires `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` to be present and non-empty and refuses any value containing `change_me`. Make the PostgreSQL password URL-safe (for example hex): compose builds the connection URL without encoding. The file must have LF line endings; a CR is refused. Keep `BINANCE_DEMO_*` and `BINANCE_LIVE_*` in separate files for separate hosts (OPS-06): a paper host never receives a live credential. Binance live keys must have no withdrawal permission and be IP-restricted to this host (checklist, 13.5).
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
6. `BACKUP_*` variables set in `/opt/trading/.env.backup` and `deploy/backup.sh --init-remote` run as `trading` (section 11). Root SSH login is disabled; `trading` is in the `sudo` group and sudo asks for its password (no passwordless sudo rule). Set that password with `passwd trading` in the root session (the lock-out guard requires it) and run `sudo -v` in a SECOND SSH session as `trading` BEFORE closing the root session. Then install the timer with `sudo /opt/trading/deploy/backup.sh --install-timer` (it does not read `.env`) and use `sudo` for every later apt, ufw or systemctl change.
7. Docker group kept to this one account; only `127.0.0.1` ports published.
8. Delete the copied secrets file from the host once `.env` is verified.

### 13.6 First start

Bootstrap does not start the stack. As the `trading` user in `/opt/trading`: validate with `docker compose config -q` (never plain `docker compose config` with real secrets: it prints the resolved environment), build both images with `docker compose --profile ops build`, then `docker compose up -d`. The one-shot `db-upgrade` service runs `alembic upgrade head`; the `collector` starts after it completes successfully, and its container health check allows a six-minute start period. `docker compose ps` shows the state. To run a second stack from one checkout (tests, a rehearsal), `TRADING_ENV_FILE` selects which env file compose reads (default `.env`) and `COMPOSE_PROJECT_NAME` the project; the deploy scripts honour both. The `live` service does not read that shared file: it reads its own file, `.env.live` in the checkout (template `.env.live.example`, mode 0600, gitignored), or the file named by `TRADING_LIVE_ENV_FILE`; the file is optional for every other compose command. The Binance credential names, the live Telegram bot names and `LIVE_RUNTIME_MODE` go only in that file, never in `.env`, so the collector, `db-upgrade` and `paper` services never receive a `BINANCE_` name (plan 24-30; the closed per-service variable lists are in `tests/test_live_compose_env_split.py`). The SHADOW Telegram names (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_AUTHORIZED_CHAT_ID`, `TELEGRAM_AUTHORIZED_USER_IDS`) go only in `.env.paper` (template `.env.paper.example`), or the file named by `TRADING_PAPER_ENV_FILE`, which only the `paper` and `paper-pin` services read on top of `.env`; the `BACKUP_*` names and `OFF_HOST_BACKUP_TARGET` go only in `.env.backup` (template `.env.backup.example`), or the file named by `TRADING_BACKUP_ENV_FILE`, which only the `backup` and `ops` services (profile `ops`) and `deploy/backup.sh` read on top of `.env`. Both files are optional for every other compose command, mode 0600 and gitignored, so the always-on collector holds no Telegram token, no backup secret and no Binance key (plan 24-36, D-29, WR-06). When `TRADING_ENV_FILE` selects another project's env file (the soak, a rehearsal, the cutover and drill tests), the deploy scripts use that one file for all three unless these variables are set, and `deploy/compose-soak.sh` and `deploy/compose-rehearsal.sh` always do, so those projects never read the checkout's own `.env.paper` or `.env.backup`; the cost in the soak is that every soak service holds every name of the soak file. The `paper` service is the Phase 16 paper runtime; the `live` service (profile `live`) is the Phase 24 live runtime, described in 21.1c: it is started by hand and its restart policy is off.

## 14. Update and rollback

`deploy/update.sh` moves the running stack to a git ref and can move it back to the exact images that ran before. Run it as the `trading` user in the checkout.

### 14.1 Before an update

Commit or discard local changes (a dirty working tree is refused), make sure the target is a tag or commit you reviewed, and rehearse `deploy/update.sh --ref <tag> --dry-run` to read the plan. Both images (`trading-alert:dev` and `trading-alert-ops:dev`, or your `IMAGE_TAG`) must exist locally: they are what a rollback returns to.

### 14.2 Update

`deploy/update.sh --ref REF [--skip-backup] [--force-live] [--dry-run]` records the current commit and the IDs of both images in `.deploy/last-good.env` (mode 0600, gitignored, parsed and never sourced), runs `deploy/backup.sh` (a failing backup stops the update; `--skip-backup` skips it and is a risk you take on), tags both images `:rollback`, fetches tags, checks out REF detached, runs `docker compose --profile ops build` and `docker compose up -d`. A ref starting with a dash is refused. `COMPOSE_PROJECT_NAME`, `TRADING_ENV_FILE` and `IMAGE_TAG` are honoured from the environment. Both `--ref` and `--rollback` refuse to run while the `live` compose service is running, and when the probe cannot tell (fail closed), because a resting entry can fill unprotected while the process restarts: stop it first as section 22.5 describes. `--force-live` accepts that window and only warns; `--dry-run` prints the check (`docker compose --profile live ps --status running --services`) and skips it.

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

The environment file for the soak is made from `deploy/soak.env.example`: names only, no trade-capable name (`BINANCE_` anything makes the runtime refuse to start, D-13). It is the soak's only operator file: `deploy/compose-soak.sh` (and the `trading-soak-backup` unit) point `TRADING_PAPER_ENV_FILE` and `TRADING_BACKUP_ENV_FILE` at it too (plan 24-36), so the soak never reads the checkout's `.env.paper` or `.env.backup`.

**Restart policy.** The `paper` service restarts with `unless-stopped`, by the owner's decision `decisions/16-DEC-RESTART-POLICY.md` (16-55 Q1 = A). The earlier `on-failure` was dropped because it does not restart a container after a Docker daemon restart (Docker documentation, `docs/SOURCES.md`), and a host reboot or a daemon restart must not leave the runtime down: `unless-stopped` brings the container back after a host reboot, a daemon restart and a crash, and keeps it down only after a requested stop (`deploy/compose-soak.sh stop paper`, 20.2). It restarts every exit that no stop preceded, a runtime-initiated exit 0 included, so no path of the service command relies on exit 0 to stay down: the command always carries `--hold-on-refusal` and never `--pin-epoch`.

**Exit codes of `python -m src.paper.runtime`.** No restart policy has a per-code exclusion list. The table below and the hold are what keep a refusal from becoming a restart loop (T-16-110). It lists every member of `ExitCode` in `src/paper/runtime_config.py`.

| Name | Code | Meaning and what happens |
| --- | --- | --- |
| `OK` | 0 | a stop the operator requested (after the stop record), the end of a hold, the one-shot `--pin-epoch`, the `--healthcheck` probe, or SKIPPED (the paper-start allowlist admits nothing) without `--hold-on-refusal`; the service command never exits 0 by itself, so nothing relies on exit 0 to stay down |
| `USAGE` | 2 | a malformed command line (argparse's own status), or `--pin-epoch` together with `--hold-on-refusal` (the one-shot pin never holds); the command line does not change on a restart, so fix the command |
| `TRADE_KEY_REFUSED` | 3 | a trade-capable variable name is present in the environment; refusal |
| `CONFIG_NOT_RATIFIED` | 4 | the runtime configuration file is not ratified; refusal |
| `NO_PINNED_EPOCH` | 5 | no pinned epoch; refusal |
| `ADMISSION_OR_EPOCH_MISMATCH` | 6 | the allowlist admission or the epoch does not match; refusal |
| `FAIL_CLOSED_RUNTIME` | 7 | the runtime failed closed on a condition a restart can clear (lost data, lost connection, an exhausted WebSocket rebuild, a market stream silent past its bounded recovery, an unreachable state database at start, a lost instance lease); restarted, and the time shows as a CRASH gap |
| `INSTANCE_LEASE_HELD` | 8 | another paper runtime or pin holds the instance lease of the soak database: one runtime per epoch (plan 16-55, review B1-WR-07); refusal |

A refusal (codes 3 to 6 and 8) can never succeed on a retry, because only a human action changes the outcome. With `--hold-on-refusal` the process logs the refusal and stays up, held and non-operational: it writes no record, starts no loop, builds no WebSocket, market-data or Telegram client, and leaves the held marker of its container (`logs/paper/held-refusal-<container>.json`, `src/paper/held_marker.py`). The healthcheck reads that marker first, so the paper container is up and unhealthy instead of looping, even when the soak database holds a fresh bar of an earlier run. The operator reads the refusal reason in the container log (`deploy/compose-soak.sh logs paper`) and must stop the container before correcting the cause (remove the variable, ratify the file, pin the epoch, fix the allowlist, stop the other runtime), then starts it again; the marker goes when the hold ends, and a marker left by a killed hold is removed by the next successful start of the same container. SKIPPED holds the same way under `--hold-on-refusal` (the owner's decision amends the earlier rule "SKIPPED never holds"): under `unless-stopped` an exit 0 would be restarted in a loop. Without the flag (a hand-run command, never the service) it exits 0 at once. A held container is not restarted, because it does not exit; it ends only when it is stopped. A refusal that holds is `INSTANCE_LEASE_HELD` as well. A crash, or code 7, is restarted by the compose policy and appears as a CRASH gap in the coverage evidence: it is uncovered like every other gap (20.2).

**Configuration in force and the feed watchdog (plan 16-56).** The soak runs `config/paper/paper-runtime-v2.toml`: every value of the historical v1 file unchanged plus `feed_silence_timeout_seconds` under `[health]` (owner decision `decisions/16-DEC-WS-WATCHDOG.md`). When no kline frame of any stream arrives on the market connection for longer than that bound, the runtime records `WS_DISCONNECT`, stops evaluating live bars and enters the existing bounded rebuild and REST backfill; backfilled bars are history only, never a late signal. When no frame has arrived when the bound expires again, or when the bounded rebuild is exhausted (after its backfill), the process exits 7 and the restart policy restarts it. A `minute_close_lag_seconds` of zero is refused at load with code 4 (`decisions/16-DEC-CLOSE-LAG-ZERO.md`).

**Single instance and the pin.** The runtime takes the instance lease of the soak database (a PostgreSQL session advisory lock) after admission and before the pin or any record, and releases it on every way out; a held process releases it before it waits. The live loop re-checks it at every consumer batch and every step of its periodic tasks and fails closed with code 7 when it is lost, so a lost lease is noticed at the next batch or periodic step. `--pin-epoch` pins the epoch, writes the pinned state and exits 0 without the start record and without the loop (`decisions/16-DEC-PIN-COMMAND.md`). It runs only in the one-shot `paper-pin` service (its own profile, `restart: "no"`, so Docker never restarts the pin); the managed `paper` service never pins.

**Pin sequence.** Pin only after the restart drill of 20.8 passed on every path. Stop a held `paper` container first (`deploy/compose-soak.sh stop paper`), so the pin and the start below are the only steps. Run the one-shot pin and wait for its exit 0, then start the managed service at once as the next operational step, with nothing else in between: the time from the pin to the service start is uncovered and counts toward the `continuous_uncovered_ceiling_seconds` of 900 s (`decisions/16-DEC-O-07.md`).

```text
IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper-pin run --rm paper-pin
IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d --no-build paper
```

The first command prints `epoch pinned: <epoch id>` and exits 0. Any other exit means nothing was pinned or the pin was refused: read its output, do not start the service, and report it. A pin refused with `INSTANCE_LEASE_HELD` means a `paper` container still runs.

### 20.2 Deploys during the trial soak

Every stop or deploy during the trial is a PLANNED_RESTART (glossary) and is never covered: the coverage denominator is the whole fixed trial window, only HEALTHY time counts, and a gap that has a reason is still uncovered (REV-01). The trial is 14 calendar days, which is 336 h; 95 percent of 336 h leaves about 16.8 h for all uncovered time together (REV-17): planned restarts, crashes, DEGRADED time, disconnects and maintenance share that one budget. A deploy therefore spends budget that no crash may need, so batch changes, prefer a change before the trial starts, and keep the stop short.

- Stop the paper service cleanly (`deploy/compose-soak.sh stop paper`) rather than killing the container: a clean stop writes the stop record, and the gap then carries the reason PLANNED_RESTART; a killed process shows as a CRASH gap. Both are uncovered.
- What the restart policy does (`unless-stopped`, 20.1): after a host reboot and after a Docker daemon restart the paper container comes back by itself, together with the collector, and resumes its epoch (the downtime is a gap like every other); after a process crash Docker restarts it. A requested stop, `deploy/compose-soak.sh stop paper`, stays stopped, also across a later daemon restart or reboot, until the operator starts the service again (`deploy/compose-soak.sh --profile paper up -d --no-build paper`). A refused start does not exit: it holds, unhealthy, and is not restarted. The restart drill of 20.8 proves these paths on the soak host before the pin.
- Write down the UTC time and the cause of each stop and deploy next to the evidence; the audit reads the gap reason, but the cause is only in your note.
- A change of the image, the allowlist or the runtime configuration during the trial is a restart and spends the budget above; changing any ratified L-04 value before the trial starts needs a new user approval (L-04).
- The runtime configuration is bound to the pin (owner decision 16-DEC-CONFIG-PIN, plan 16-57): the pin and every start record the configuration identity, the SHA-256 of the canonical, validated effective values. A change of any effective configuration value during the trial is refused at the next start with exit 6 and the held, unhealthy state (20.1): it needs a new pin, which starts a new qualifying trial (REV-07, REV-18). A comment-only or whitespace-only edit of the file is not refused, because it does not change the identity. The raw file SHA-256 that the records also carry is provenance only; it is never compared.
- Reconnects and the REST backfill depth (plan 16-62, B1-WR-09): after an SDK reconnect, after a drop and rebuild, and once after start, the supervisor reads the missed closes back over REST. One backfill requests at most `timing.rest_backfill_depth_bars` closed bars per symbol and interval (the ratified 1500 in `config/paper/paper-runtime-v2.toml`, 16-DEC-O-07); when more closes are missing, it requests the newest ones and records every older missing close as a gap with the reason of the window being verified (never as an exchange hole). Backfilled bars are history only and are never evaluated (Q-D). The restart warm-up (1000 bars of 1h, 300 bars of 4h) is structural and not governed by this key. Operator consequence: an outage longer than the depth leaves recorded gaps that no later backfill fills, and a change of the value is a configuration change that the identity rule above refuses during a trial.
- Never run the volume-removing form of `down` to "start clean": it deletes the evidence of the trial (20.1).

### 20.3 Telegram bot

The soak uses a separate bot, by the user's decision recorded in `decisions/16-DEC-Q-L.md` (16-DEC-Q-L, option `separate-bot`). The user creates the bot with BotFather and the token is never pasted anywhere: not into a chat with an assistant, not into this repository, not into an evidence file and not onto a command line. It reaches the host only through the soak environment file of 20.1, which is not committed.

### 20.4 Rehearsal before the trial

The pre-soak rehearsal of the SHADOW APPROVE, CONFIRM, journal path (REV-03, glossary `test_only`) runs before the trial in its own project, `trading-rehearsal`, with its own volumes and its own environment file, and never in trading-soak. Its records carry the rehearsal marker and are excluded from every count: signals, trades, parity evidence, the exit criteria G1 to G5 and PAPER-03. It does not bypass the paper-start allowlist. When the rehearsal is finished, the trial soak starts from a clean state of its own project; the soak database is not used as a scratch pad for the rehearsal at any point.

Every rehearsal compose command goes through `deploy/compose-rehearsal.sh` (plan 16-53); no hand-typed raw `docker compose` command is used for it. The wrapper pins the project `trading-rehearsal` (volumes such as `trading-rehearsal_pgdata`, apart from `trading` and `trading-soak`), takes the env file only from `TRADING_ENV_FILE`, and refuses, before any docker call and with exit 1: an env file that is unset, unreadable or inside the checkout; any variable whose name starts with `BINANCE_`, in the environment or in the env file (only the name is printed); a `-p` or `--project-name` flag naming another project; an `--env-file` flag; and a running `trading-soak` project (one `getUpdates` consumer per bot token, and the database port). `--dry-run` as the first argument prints the command and runs no docker. The rehearsal env file is created by hand outside the checkout, mode 0600, with its own `POSTGRES_*` names, a `POSTGRES_PORT` different from the soak's, the rehearsal bot names and no `BINANCE_` name; it is never the soak env file.

```text
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh --dry-run up -d db-upgrade
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh up -d db-upgrade
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh ps
TRADING_ENV_FILE=/home/trading/rehearsal.env deploy/compose-rehearsal.sh stop
```

`up -d db-upgrade` starts the rehearsal PostgreSQL and applies the migrations; `stop` ends the project and keeps its volumes. Then run `scripts/shadow_rehearsal.py --live-telegram --i-am-the-operator --out <path>` against that database (plan 16-40, Task 3). The script itself also refuses a `BINANCE_*` variable in both modes (`--dry-run` and `--live-telegram`, exit 3, names only).

### 20.5 Backups and restore drill before the long soak

Before the long soak starts, the host has a verified backup chain: a backup run now (11.4) that completes, then the restore drill (11.6) that passes. A backup is not valid until a drill passes. The drill restores into a scratch target, the scratch database that the drill creates and drops, and never into the soak database: a restore into the soak database would replace the evidence it is supposed to protect. The first real backup waits for the D064 real-S3 gate (section 11, "Real-S3 gate"; 19.4 item 6; run on the soak host with `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup-real-s3-gate.sh --execute`, which must end with `RESULT: PASS`), and the first verified pull to the development machine (19.5) is part of the same readiness. Run the drill again after any change of provider, key or image (11.6).

**The soak database has its own backup unit and its own bucket (plan 16-55, review B2-WR-07).** `trading-backup` (11.4) sets no project, so it dumps project `trading`, not `trading-soak_pgdata` where the soak evidence lives. The soak project therefore gets its own unit pair, `trading-soak-backup.service` and `trading-soak-backup.timer`, with the schedule of `trading-backup.timer`; the existing pair stays as it is. The remote layout has no project component (`src/ops/backup_remote.py`: `snapshots/<id>/` and `parquet/`), so two projects in one bucket would form one snapshot series and retention would delete one project's daily dump. The soak env file therefore names its own bucket: its `BACKUP_S3_BUCKET` must differ from the bucket of `trading-backup` (the checkout's `.env.backup`), with its own crypt passwords and its own sentinel. The soak bucket is created by the owner before plan 16-43 (an owner action). `--install-soak-timer` refuses an empty `BACKUP_S3_BUCKET` or the trading bucket and prints names only. On the soak host, as the `trading` user for the first two commands and with `sudo` for the install:

```text
COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup.sh --init-remote --dry-run
COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup.sh --init-remote
sudo deploy/backup.sh --install-soak-timer --soak-env-file /path/to/soak.env --dry-run
sudo deploy/backup.sh --install-soak-timer --soak-env-file /path/to/soak.env
systemctl list-timers trading-soak-backup.timer
COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=/path/to/soak.env deploy/backup-drill.sh
```

**The pin needs a real off-host backup (owner decision of 2026-10-20).** Local-only mode (`BACKUP_REMOTE=none`, section 11) keeps the soak backup running without a bucket, but it never satisfies the pin of plan 16-43: before the pin, a soak backup must have run against the real remote and printed `OFFSITE_COPY=verified`, and the restore drill must have passed against that remote; a run whose marker reads `OFFSITE_COPY=skipped` does not count. In local-only mode `--install-soak-timer` accepts a soak env file without `BACKUP_S3_BUCKET` (it prints the warning), and still refuses a bucket that is set and equals the trading bucket; `--init-remote` refuses.

`--init-remote` runs once, on the empty soak bucket. The unit runs `deploy/backup.sh` with `COMPOSE_PROJECT_NAME=trading-soak` and `TRADING_ENV_FILE` set to the soak env file. The restore drill covers the soak project with the same two variables (last line): it restores into a scratch database, never into the soak database. A soak backup is not valid until that drill passes. Read the unit's result with `systemctl status trading-soak-backup` and `journalctl -u trading-soak-backup`.

### 20.6 Image

The soak never runs from a working-tree bind mount: the paper service runs from an image built from a named commit, not from the files of a checkout. How that image is produced is the user's decision of 2026-10-10, recorded in `decisions/16-DEC-Q-I.md`: option `host-build-recorded`, build on the host at a recorded commit. No CI step pushes an image (D050 deferred the registry), so the image is not CI-produced; the commit and the image id are what the evidence cites. The options `registry` and `ci-save-transfer` were considered and are not automatic fallbacks: adopting either later is a new user decision, and `registry` also needs a new DECISIONS entry because it reopens D050.

On the soak host, in the checkout, with the commit to run checked out and nothing else changed:

```text
deploy/soak-image.sh --dry-run
deploy/soak-image.sh
IMAGE_TAG=<commit> TRADING_ENV_FILE=/path/to/soak.env deploy/compose-soak.sh --profile paper up -d --no-build
```

`deploy/soak-image.sh` refuses a dirty working tree (any uncommitted change, tracked or untracked, because the working tree is the build context). It builds `trading-alert:<commit>` and `trading-alert-ops:<commit>` with the soak wrapper, where `<commit>` is the full 40 character output of `git rev-parse HEAD`, checks that the tree and HEAD did not change during the build, and records the commit and both image ids in `.deploy/soak-image.env` (mode 0600, gitignored; the previous record is kept as `soak-image.env.prev` and every build is appended to `.deploy/soak-image.history`). The soak starts only from an image built this way, with `IMAGE_TAG` set to the recorded `GIT_SHA`; `--no-build` keeps compose from building anything else. Before the start, `docker image inspect --format '{{.Id}}' trading-alert:<commit>` must print the recorded `APP_IMAGE_ID`. The trial evidence names `GIT_SHA` and `APP_IMAGE_ID` from that file, and the host needs the build toolchain that the image build uses (`docker compose --profile ops build`, section 13.6).

**What the image holds and the in-image check (plan 16-55, review B2-CR-05).** The runtime image carries the parameter registry (`params/`, read by the runtime as `/app/params`) and the ratified runtime configuration (`config/paper/`), next to the code, the collect list and the migration config; both belong to the frozen decision surface, so they are part of the image and its hash. After the build and the tree check, and before anything is recorded, `deploy/soak-image.sh` runs `scripts/check_image_paths.py` inside the built `trading-alert:<commit>` image with `--network none`: it loads every allowlisted parameter set from `/app/params` (and checks the set's hash against its allowlist entry) and loads the configuration file `/app/config/paper/paper-runtime-v2.toml` with the runtime's own loader. It prints names only. A failure exits non-zero and writes no record, so an image that cannot admit or configure its paper runtime is never recorded. The soak env file sets `PAPER_RUNTIME_CONFIG` to that same in-image path (`/app/config/paper/paper-runtime-v2.toml`, the configuration in force since plan 16-56; the historical v1 file no longer loads); the comment in `deploy/soak.env.example` names it.

The paper-start allowlist is a source constant (O-04, plan 16-42), so the image must be rebuilt after the allowlist commit: an image built before that commit carries the earlier allowlist. Build, record and start only after the allowlist commit exists.

**Relation to `deploy/update.sh`.** `deploy/update.sh` (14) updates the ordinary stack: it records `.deploy/last-good.env`, checks out a ref, builds and starts, and it does not go through `deploy/compose-soak.sh`, so the guard of 20.1 does not apply to it. It is not used for the soak project: every `--ref` run overwrites `last-good.env` (14.4), while `soak-image.env` and the history file are the record of which image the soak ran. A deploy during the trial is a new commit, `deploy/soak-image.sh`, `deploy/compose-soak.sh stop paper` and a start with the new `IMAGE_TAG`, and it is a PLANNED_RESTART (20.2). To return to an earlier image, start again with the `IMAGE_TAG` of an earlier line of the history file (the older image stays on the host, because tags are per commit); that is also a PLANNED_RESTART, and a database schema migration applied by the newer image is not undone (14.4).

### 20.7 Exporting trial evidence

This is the procedure for getting the evidence of one epoch off the soak host and into the place the user chose, and for reading the hourly freeze ticks back from GitHub (plan 16-47; D-22, L-01, REV-02, REV-08, REV-18). It applies seven decision records and invents no value: `decisions/16-DEC-O-01.md` (where evidence is kept), `decisions/16-DEC-Q-F.md` (how the hourly check gets its pin), `decisions/16-DEC-Q-Q.md` (the cron minute of the first trial, minute 34), `decisions/16-DEC-Q-Q-2.md` (the cron minute since 2026-11-13, minute 17), `decisions/16-DEC-EVIDENCE-KEYS.md` (the object keys of the hourly and final bundles, plan 16-59) `decisions/16-DEC-FREEZE-LOG-ASSEMBLY.md` (how the freeze log is assembled from the run artifacts, plan 16-59) and `decisions/16-DEC-HOST-TICK.md` (the second tick source, a host timer with an S3 witness, 20.10).

**What the records say.**

- **Where (O-01, option a).** An S3 evidence prefix outside the backup crypt remote, with its own remote and its own credential. Versioning is enabled; there is no Object Lock and no retention. Object Lock can be added later but never removed, so it is the user's later decision, not part of this procedure.
- **Reader.** The recorded reader is project owner only (the user). GitHub never reads this store: the pin reaches GitHub through a commit (below), so no credential for the evidence store is ever placed on GitHub.
- **Crypt layer.** The evidence is written outside the backup crypt remote, on a plain S3 remote with no crypt layer, so it is not ciphertext to a holder of the evidence remote's credential and no crypt passphrase is needed to read it. It is also not covered by the encryption of the backup chain (11); what protects it is the bucket policy the user sets in plan 16-49, not this procedure. The two records are compatible because the workflow reads the pin from a commit and never from the store.
- **Write timing and loss window.** `exporter-schedule`, hourly: the operator runs the export and publish steps below every hour, and nothing on the host writes evidence by itself. Since D109 (owner decision `16-DEC-HOST-TICK`) the only exception to "nothing on the host writes evidence by itself" is the one create-only witness object per host freeze tick of 20.10. The loss window is what was recorded on the host since the last successful publish: at most the last hour while the hourly runs succeed, longer for every skipped or failed run, and everything not yet published if the host disk is lost. The database backups of 11 are a separate copy with their own window; this store is not a backup of the database.
- **Object keys (`decisions/16-DEC-EVIDENCE-KEYS.md`, Q1 = A).** Every hourly bundle and the final bundle is published under its own key `<epoch-id>/<as-of>-<sha12>/<file>`: `<as-of>` is the manifest `as_of_utc` as `YYYYMMDDTHHMMSSZ` and `<sha12>` the first 12 hex characters of the SHA-256 of the manifest bytes, so the key comes from the manifest and from nothing typed. The key is create-only: publishing the very same bundle again finds identical bytes, uploads nothing and succeeds (identical bytes are a success), while different bytes at an existing key are an error (exit 4) and nothing is ever replaced. The bucket keeps versioning, with no retention and no Object Lock; O-01 is unchanged. The second hourly publish of an epoch therefore no longer collides with the first, and the final bundle can always be published.
- **Freeze log (`decisions/16-DEC-FREEZE-LOG-ASSEMBLY.md`, Q2 = B).** The diff log is not read from one run only. Step 1 downloads every available run artifact and the exporter merges the freeze lines of all of them into one derived `registry_diff.jsonl`, deduplicated by run identity `(run_id, run_attempt)`, ordered by time, with the manifest `freeze_log` listing each input artifact with its sha256 and the run ids it carried. The derived file is not a byte copy of one artifact: every original artifact is kept unchanged in the bundle as `freeze_artifact_<16 hex>.jsonl`. Identical lines of one run identity collapse; two different lines of one identity stop the export (exit 4). A line without run metadata is deduplicated by its exact bytes.
- **One run at a time, and what is still missing.** The workflow has a `concurrency` group `paper-freeze-check` with `cancel-in-progress: false` and `queue: max` (the owner's amendment of 2026-10-16), so two runs never restore the same cache state and the line of one is not lost by an overlap. GitHub documents (https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/control-the-concurrency-of-workflows-and-jobs, read 2026-10-16, not verified live, `docs/SOURCES.md`) that a group keeps at most one running run; with the default `queue: single` a newly queued run replaces the pending one; `queue: max` allows up to 100 pending runs and is invalid together with `cancel-in-progress: true`. With `queue: max` up to 100 runs may wait and an additional run is cancelled; with fewer pending a tick is not lost. The residual risk is a cancelled, dropped or delayed run, and the rule for it does not depend on the queue: a tick without a usable line is never inferred clean. The expected slots and the run list make it an EVIDENCE_GAP, `missing_ticks.jsonl` records it with its slot, its run id and the run's conclusion (for example `cancelled`), and any cancelled or skipped tick breaks the qualifying window (REV-02). The first live run on GitHub shows that the `queue` key is accepted; no test can.
- **Pin source (Q-F, `commit-pinned-state`).** After each pin the user commits `evidence/paper/pinned_epoch.json` to `master`. The workflow step "Use the committed pinned epoch" copies that file to the path the freeze CLI reads before every check, with no secret and with the read-only token it already had. With no committed file there is no pin and a cached copy is removed. A new pin needs a new commit; until then a rollover is seen again at every tick. The Actions cache keeps only the diff log between ticks and is never a source of truth (L-01): caches unused for 7 days are removed.
- **Cron (Q-Q).** The workflow runs `17 * * * *`, the owner's choice of 2026-11-13 (`decisions/16-DEC-Q-Q-2.md`); the reconciler's slot grid is HH:17. The first trial (epoch ce6c0bbf) ran at minute 34 (`decisions/16-DEC-Q-Q.md`). The evaluator and the exporter read the cron from the workflow file, so a bundle of an epoch that ran under minute 34 is evaluated or re-exported with `--workflow` set to a copy of the workflow at that epoch's commit (`git show <commit>:.github/workflows/paper_freeze_check.yml > <file>`); otherwise every slot of it is a SCHEDULE_MISMATCH gap. A scheduled workflow change takes effect only on `master` (G15), so the operator checks `origin/master` for minute 17 before the next pin. A minute off the top of the hour is a mitigation of unproven effect on delayed or dropped scheduled runs (G15, REV-18): a missing tick is still an EVIDENCE_GAP, never filled and never counted as clean.

**Evidence remote configuration (fixed names).** The destination and the credentials of the evidence store come only from these environment names, which mirror the `BACKUP_S3_*` pattern of `src/ops/backup_remote.py` with an `EVIDENCE_` prefix and are not the BACKUP_ names: `EVIDENCE_S3_PROVIDER` (AWS, Wasabi or Other), `EVIDENCE_S3_ENDPOINT` (needed only for Other), `EVIDENCE_S3_REGION`, `EVIDENCE_S3_BUCKET`, `EVIDENCE_S3_PREFIX` (required, never empty), `EVIDENCE_S3_ACCESS_KEY_ID` and `EVIDENCE_S3_SECRET_ACCESS_KEY`. A change of provider changes these values only. They map to the rclone remote `EVIDENCES3` (plain S3, no crypt layer, never `BACKUPS3` or `BACKUPS3CRYPT`) in the rclone child process only, so a credential is never in argv and never printed. Use a credential of its own, scoped to this bucket and prefix: the exporter refuses to run when it equals the backup credential. Make the file from `deploy/evidence.env.example` (names only), keep it outside the checkout at mode 0600, and load it only into the shell that runs the export (`set -a; . /path/to/evidence.env; set +a`). It is not added to the shared `soak.env` file, because the paper container shares that file and must not hold this credential; the paper runtime reads none of these names and still refuses any `BINANCE_` name. A missing or empty name, an empty or unsafe prefix, or a credential shared with the backup chain exits 2 before anything is exported or uploaded, and the message lists variable names only.

**1. Fetch the GitHub run list and every run artifact.** Run this where the operator is logged in to GitHub (`gh auth login` is the operator's own step; no token is written into the repository, an environment file or a command line). The run list and its records expire (90 days by default, `docs/SOURCES.md`), so fetch before then and copy the files to the host.

```text
gh api repos/<owner>/<repo>/actions/workflows/paper_freeze_check.yml/runs --paginate --method GET -F per_page=100 --jq '.workflow_runs[]' | jq -s '.' > <github-runs-file>
gh run download <run-id> --repo <owner>/<repo> --name registry-diff-<run-id> --dir <download-dir>/<run-id>
```

Run the second command for every run id of the list whose artifact is still available (an expired artifact, or a run that produced none, is simply not downloaded: its tick is judged from the run list and recorded in `missing_ticks.jsonl`, never skipped silently). Each artifact holds the log that one run saw; because the cache carries the log from tick to tick, an artifact is usually the whole log up to its tick, but a run that overlapped another can lack the other's line, so no single artifact is trusted alone. An artifact that cannot be read stops the export. The exporter refuses a run list that is not a list of runs. These commands were not run on the development machine (no network): the first run on the real repository is the operator's check of the shape.

**2. Export one epoch on the host.** The state comes from the soak database through the environment names the runtime already uses (`DATABASE_URL_SYNC` or `DATABASE_URL`); the URL is never typed on the command line. `<pinned-epoch-file>` is the committed `evidence/paper/pinned_epoch.json` (repeat `--pinned` with an archived pin when an earlier epoch is exported).

```text
python scripts/export_soak_evidence.py --source pg --epoch <epoch-id> --pinned <pinned-epoch-file> --diff-log <download-dir>/<run-id>/registry_diff.jsonl --diff-log <download-dir>/<other-run-id>/registry_diff.jsonl --github-runs <github-runs-file> --config <runtime-config> --window-start <window-start-utc> --window-end <window-end-utc> --as-of <as-of-utc> --out <new-bundle-dir>
```

`--diff-log` is given once per downloaded artifact (a shell loop that builds the arguments is fine); the order does not matter and an artifact given twice counts once. The bundle is one epoch, written to a new directory (an existing one is never overwritten) with `manifest.json` last. A secret-looking value anywhere in it stops the export (exit 3) and removes the partial bundle.

`--as-of` is the UTC instant the freeze ticks are judged as of (default: now, and never later than the window end plus the ratified `freeze_tick_grace_seconds`). Only a slot whose slot time plus that grace is at or before it is judged, so an hourly export records a gap only for a tick that has already happened (never for a slot in the future), and the manifest records `as_of_utc`. An `--as-of` before the epoch pin, after the window end plus the grace, or later than the current time (plan 16-65; nothing is written or published) is refused (exit 2). A bundle exported before the window end plus the grace is **partial**: it loads and it is published, but `scripts/evaluate_trial_soak.py` refuses to judge it (exit 2, one line); the final bundle is the first one whose as-of is at or after the window end plus the grace.

**Host witness (20.10).** Once the host timer of 20.10 is installed for an epoch, every export of that epoch adds `--host-witness` with `EVIDENCE_S3_WITNESS_PREFIX` loaded, so the witnessed host ticks join the GitHub ticks in the bundle (`soak-evidence-bundle/2`); an export without it judges the GitHub ticks only. The fenced commands above stay as they are; 20.10 shows the same command with the flag.

**3. Publish and verify.** With the evidence names loaded, either add the flag `--publish` (it takes no value) to the command above, or publish an exported bundle on its own:

```text
python scripts/export_soak_evidence.py publish --bundle <new-bundle-dir>
```

There is no free-form destination: no remote, bucket or prefix is typed on the command line. Objects go to `<epoch-id>/<as-of>-<sha12>/<file>` under `EVIDENCE_S3_BUCKET` and `EVIDENCE_S3_PREFIX` (the per-bundle key above), every file first and `manifest.json` last, each with `rclone rcat --immutable`. The key is create-only: a bundle that is already published with identical bytes uploads nothing and succeeds, an object at an existing key with different bytes stops the publish (exit 4) before anything is uploaded, and nothing is ever replaced. Then every object is read back and compared with the manifest sha256: exit 0 prints "published and verified"; exit 4 names the file that failed and keeps the local bundle for another attempt. Run it as the hourly step of the recorded schedule, each hour with its own `--as-of`; a failed run is simply repeated (the same bundle again is harmless), and it is never edited by hand. A bundle whose manifest has no `as_of_utc` (made before plan 16-59) is not published: export it again.

**4. Evaluate.** Copy the bundle to the development machine (19.5) and run `python scripts/evaluate_trial_soak.py --bundle <new-bundle-dir> --config <runtime-config> --q-d-decision <q-d-decision-file> --out <evaluation-file>`; the bundle is checked against its manifest first, a partial bundle (as-of before the window end plus the grace) is refused, and a gap reconstructed from the run list plus the expected slots is an EVIDENCE_GAP (REV-02).

**Not shown by any test.** Publishing to a real bucket, the output shape of `gh api` and `gh run download`, and the bucket policy are checked only by the operator on the real accounts; `tests/test_soak_evidence_export.py` publishes to an injected fake and `tests/test_paper_freeze_workflow_pin_source.py` holds the workflow to the recorded decisions. Neither the acceptance of the `queue` key nor the behaviour of GitHub when more than 100 runs wait is tested: the first live runs show them.

### 20.8 Restart drill before the pin

The owner's decision `decisions/16-DEC-RESTART-POLICY.md` (16-55 Q1 = A) requires five paths to be tested before the trial: refused start, requested stop, process crash, host reboot and Docker daemon restart. The development machine cannot show a host reboot or a Docker daemon restart, so plan 16-43 runs this drill on the soak host. Run it on the clean soak project, after the image of 20.6 is built and recorded and before any pin. With no pinned epoch the runtime refuses with `NO_PINNED_EPOCH` (code 5) and holds, so nothing is written to the soak database during the drill. Write the UTC time and the observed outcome of each step into the evidence of plan 16-43. Any path that does not behave as written stops the trial start and is reported as a blocker. **The pin must not happen until every path passed.**

Set `IMAGE_TAG=<commit>` and `TRADING_ENV_FILE=/path/to/soak.env` in the shell first (20.6), so the wrapper commands below use the recorded image and the soak env file.

**(a) Refused start.** Start the managed service:

```text
deploy/compose-soak.sh --profile paper up -d --no-build
deploy/compose-soak.sh ps paper
deploy/compose-soak.sh logs paper
deploy/compose-soak.sh exec -T paper ls logs/paper
```

Expected:
- The container stays up and does not restart.
- The log shows `paper runtime refused (exit 5)`.
- `logs/paper` holds the held marker `held-refusal-<container>.json`.
- Once the probe's start period has passed, `ps` reports the container unhealthy.
- No paper runtime record exists in the soak database: no `PaperRuntime` journal event.

**(b) Docker daemon restart.**

```text
sudo systemctl restart docker
deploy/compose-soak.sh ps paper
deploy/compose-soak.sh logs paper
```

Expected: the paper container comes back by itself, without a command from the operator, and holds again. The log shows a new refusal with a later time, and the container is unhealthy again after the start period.

**(c) Host reboot.**

```text
sudo reboot
deploy/compose-soak.sh ps paper
```

Expected: after the host is back and you are logged in again, the paper container is up by itself and holds again. The collector restarts too; its downtime is recorded as a data gap (19.4).

**(d) Process crash.** Kill the container's main process from the host:

```text
deploy/compose-soak.sh ps -q paper
docker inspect --format '{{.State.Pid}}' <container id>
sudo kill -KILL <pid>
docker inspect --format '{{.RestartCount}}' <container id>
deploy/compose-soak.sh ps paper
```

Expected: Docker restarts the container by itself. The restart count goes up by one, and the container holds again.

**(e) Requested stop.**

```text
deploy/compose-soak.sh stop paper
sudo systemctl restart docker
deploy/compose-soak.sh ps -a paper
```

Expected: the container stays stopped (exited) after the daemon restart, until the operator starts it again. After this step, follow the pin sequence of 20.1 with the service still stopped: pin, then start the managed service at once.

### 20.9 Paper heartbeat

The paper runtime has its own external heartbeat, separate from the collector's (11.9), by the owner's decision `decisions/16-DEC-HUNG-RUNTIME.md` (16-55 Q2 = B): one combined alert could not tell a failed host heartbeat from a failed paper process. It is `deploy/heartbeat.sh --target paper` with the two units `trading-soak-paper-heartbeat.service` and `trading-soak-paper-heartbeat.timer` (plan 16-56).

**The recorded numbers.** The timer pings every 60 s (`paper_heartbeat_interval_seconds`, passed as `--interval-seconds 60`). The check in the monitor's dashboard has a period of 60 s and a grace of 120 s (`paper_check_period_seconds`, `paper_check_grace_seconds`); both are set in the dashboard, not in the repository. All three come from 16-DEC-HUNG-RUNTIME. A missed ping therefore alerts within a few minutes, well inside the 900 s `continuous_uncovered_ceiling_seconds` (`decisions/16-DEC-O-07.md`).

**What the probe checks.** One run executes, through `deploy/compose-soak.sh`, the read-only probe `python -m src.paper.runtime --liveness` inside the `paper` service, and sends one success ping only when it exits 0. The probe is the 120 s feed-liveness and loop-alive signal (correction 2 of 16-DEC-FIXPLANS.md), not the 3900 s bar-age healthcheck (`--healthcheck`, `healthcheck_max_bar_age_seconds`). It passes only when the container holds no held marker, and when the liveness stamp that the silence watchdog writes from the event loop shows both an event-loop wake and a market message within `feed_silence_timeout_seconds` (120 s, `config/paper/paper-runtime-v2.toml`, `decisions/16-DEC-WS-WATCHDOG.md`). A held refusal, a hung event loop or a silent feed sends no success ping, so the check goes quiet and the monitor alerts after its period and grace. The probe opens no database or network client and prints names and ages only.

**A crash-restart loop is not live (plan 16-65).** The stamp belongs to one process (`decisions/16-DEC-LIVENESS-FIRST-FRAME.md`): only the process holding the instance lease owns it: that process removes its container's stamp right after taking the lease (a start refused before or by the lease, such as a second start refused with exit 8, touches no stamp) and again on every exit, fail-closed exit 7 included, and the stamp records no market message until the first message of that process arrived (schema `paper-liveness/2`; an older `paper-liveness/1` file is refused). A runtime that fails shortly after each start and is restarted by `restart: unless-stopped` therefore never passes the probe, and the monitor alerts. A process killed without cleanup (kill -9, OOM kill, power loss) leaves a stamp that is no longer refreshed: it fails the probe once it is older than 120 s, or is removed by the next start that takes the lease, so the alert is delayed by at most that bound.

**Not proof of recovery.** The heartbeat is an alert, not proof of recovery. A runtime that stays down long enough to exceed the coverage ceiling still fails the coverage criterion of the trial, whatever the heartbeat showed.

**The URL.** The paper check has its own secret ping URL, never the collector's. It lives in its own root-only file, `/etc/trading/heartbeat-paper.url` (mode 0600), and systemd hands the unit a private copy as the credential `heartbeat-paper-url`. `--target paper` refuses a `--url-file` that names the collector's file. The URL is never an argument, never in the repository, a log, `acceptance.json` or the shell history. The owner creates the check (period and grace as above) before plan 16-43 and stores its URL on the soak host:

```text
sudo deploy/heartbeat.sh --target paper --set-url
sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file /home/trading/soak.env
```

The first command reads the URL as one line from standard input without echo. The second writes the two units with the interval of the command (there is no default in code) and the soak env file the unit passes to `deploy/compose-soak.sh`, and enables the timer; add `--dry-run` to either to see what would happen. The step timeout of the script is the existing PLACEHOLDER transport bound of 11.9. Exit codes are those of 11.9. Check the installed units with:

```text
systemctl status trading-soak-paper-heartbeat
journalctl -u trading-soak-paper-heartbeat
systemctl list-timers trading-soak-paper-heartbeat.timer
```

**Fail-open.** The sender never stops, restarts or touches the paper runtime: the only `docker` subcommand it runs is `exec` of the read-only liveness probe, and the paper units carry no dependency, restart or failure link to any other unit. Live delivery to the monitor, the systemd credential and the timer firing are operator verification on the soak host before plan 16-43.

### 20.10 Host freeze tick and its S3 witness

The soak host runs a second, independent freeze tick beside the GitHub one, by the owner's decision `decisions/16-DEC-HOST-TICK.md` (option s3-witness, 2026-11-14), recorded as D109 in `docs/DECISIONS.md`, which amends O-01 with a least-privilege host credential. Seven of the nine gaps of the first trial came from GitHub lateness and drops, and minute 17 is unproven (G15), so a slot can now also be satisfied by a witnessed host tick. This is quick task 261114-12e: the evidence side (plan A) and the host side (plan B, `deploy/freeze-witness.sh` and the units `trading-soak-freeze-witness.service` and `trading-soak-freeze-witness.timer`).

**What it is.** At the minute of the freeze workflow cron the timer starts the unit. One run takes the image of the running `paper` container, copies the pinned epoch out of the container to a scratch directory, and runs the same freeze CLI, `python -m src.paper.freeze --check --from-allowlist`, in that image: `docker run --rm --network none --read-only`, only the scratch directory mounted and only `PAPER_TICK_SOURCE`, `PAPER_TICK_ID` and `PAPER_EVENT_SCHEDULE` in its environment. It then uploads the exact line the CLI appended, create-only (`If-None-Match: *`, the payload SHA-256 signed), as `<witness prefix>/<epoch_id>/<YYYYMMDDTHHMMZ>-<tick id>.jsonl`. The timer has `Persistent=false` and no randomised delay: there is no catch-up, no retry and no re-send, because a late object is a late tick. The lateness of a tick is decided only by the S3 server time of its object, never by a time the host writes; the grace of `freeze_tick_grace_seconds` (1800), the slot grid, the thresholds, the criteria and D065 item 4 are unchanged, and a line without a witness object is not evidence.

**Prerequisite.** An image built and recorded by 20.6 from a commit that contains plan A of quick task 261114-12e (the freeze CLI that reads `PAPER_TICK_SOURCE` and `PAPER_TICK_ID`). With an older image the unit exits 5 and uploads nothing. This change does not touch the running soak image. Install the timer before the next pin, so that both sources cover the trial from its pin.

**Credential (owner-run).** Create a dedicated user or key for this purpose only: it can create objects under one witness prefix and do nothing else. The witness prefix is a sibling of `EVIDENCE_S3_PREFIX` (not equal to it, inside it or containing it) in the same bucket. AWS example, placeholders only; check it with the provider's policy simulator, no agent has run it. The identity policy of `<witness-user>`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::<evidence-bucket>/<witness-prefix>/*"
    }
  ]
}
```

The bucket policy, with three Deny statements for that principal: everything except `s3:PutObject`; everything outside the witness prefix; and `s3:PutObject` without the create-only condition (`s3:if-none-match`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WitnessOnlyPutObject",
      "Effect": "Deny",
      "Principal": {"AWS": "arn:aws:iam::<account-id>:user/<witness-user>"},
      "NotAction": "s3:PutObject",
      "Resource": ["arn:aws:s3:::<evidence-bucket>", "arn:aws:s3:::<evidence-bucket>/*"]
    },
    {
      "Sid": "WitnessOnlyItsPrefix",
      "Effect": "Deny",
      "Principal": {"AWS": "arn:aws:iam::<account-id>:user/<witness-user>"},
      "Action": "s3:*",
      "NotResource": "arn:aws:s3:::<evidence-bucket>/<witness-prefix>/*"
    },
    {
      "Sid": "WitnessCreateOnly",
      "Effect": "Deny",
      "Principal": {"AWS": "arn:aws:iam::<account-id>:user/<witness-user>"},
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::<evidence-bucket>/<witness-prefix>/*",
      "Condition": {"Null": {"s3:if-none-match": "true"}}
    }
  ]
}
```

The export credential of 20.7 is a different one: it gets `s3:ListBucket` limited to the witness prefix and `s3:GetObject` on it (besides its rights on the bundle prefix), and it must never be the witness credential. For another provider use its equivalent. Where a provider cannot refuse an overwrite, bucket versioning (O-01) keeps the first version, and an overwrite can only make a tick later, never earlier.

**Store and install (owner-run, on the soak host).** The credential is five `key=value` lines, each key once and no other line, by name only here: `bucket_url` (an https bucket URL, virtual-hosted or path style with the bucket as its one path segment), `region`, `witness_prefix` (the same value as `EVIDENCE_S3_WITNESS_PREFIX` of the exporter), `access_key_id` and `secret_access_key`. The script reads them from standard input without echo and stores them in the root-only file `/etc/trading/freeze-witness.conf` (mode 0600); systemd hands the unit a private copy as the credential `freeze-witness` (`LoadCredential`). The credential is never an argument, never in the soak env file, a container, the repository or a log, and the script refuses to run under xtrace.

```text
sudo deploy/freeze-witness.sh --set-credential
sudo deploy/freeze-witness.sh --install-timer --soak-env-file /home/trading/soak.env --dry-run
sudo deploy/freeze-witness.sh --install-timer --soak-env-file /home/trading/soak.env
systemctl list-timers trading-soak-freeze-witness.timer
```

The install reads the minute of the one hourly cron of `.github/workflows/paper_freeze_check.yml` and writes it into the timer as `OnCalendar=*-*-* *:MM:00 UTC`; if the workflow minute changes, run the install again. `--dry-run` shows what would be written without changing anything. Exit codes of one tick: 0 uploaded (clean or SKIPPED), 1 the tick could not run (no paper container, no pin, no line), 2 usage, an invalid schedule or xtrace, 3 uploaded REGISTRY_DIFF, 4 the credential is missing or invalid, 5 the line does not carry the host identity (an older image), 6 the upload was refused or failed.

**Verify with one manual tick (owner-run; agents cannot, as there is no network and no credential).** Start the unit once and read its journal, then export once with the witness and an `--as-of` after the tick:

```text
sudo systemctl start trading-soak-freeze-witness.service
journalctl -u trading-soak-freeze-witness
```

```text
python scripts/export_soak_evidence.py --source pg --epoch <epoch-id> --pinned <pinned-epoch-file> --diff-log <download-dir>/<run-id>/registry_diff.jsonl --github-runs <github-runs-file> --config <runtime-config> --window-start <window-start-utc> --window-end <window-end-utc> --as-of <as-of-utc> --host-witness --out <new-bundle-dir>
```

Use every placeholder and the repeated `--diff-log` of 20.7. The exporter prints `host witness: N object(s) read`, and the bundle's `host_witness_listing.json` lists the object with its server ModTime. Last, with the witness credential and the provider's own tool, confirm that a list, a read, a delete and a second PUT to the same key are refused (403 or 412).

**How the exporter reads it.** With `--host-witness` and `EVIDENCE_S3_WITNESS_PREFIX` loaded (a name beside the other `EVIDENCE_` names of `deploy/evidence.env.example`, no value in the repository) the exporter runs `rclone lsjson --use-server-modtime` on `<witness prefix>/<epoch id>/` (the server time of the provider, never client metadata) and `rclone cat` per object, then lists again to detect a change; the bundle becomes `soak-evidence-bundle/2` with `host_witness_listing.json` and `host_ticks.jsonl`. The evaluator judges each witnessed tick by its server time against its slot and the grace of 1800.

**When the remote is down.** At tick time the unit exits 6: that host tick does not count and is never re-sent (a later upload would be a late tick), and the GitHub tick may still cover the slot. At export time the export exits 2 and writes nothing; repeat it later. Never drop `--host-witness` to get a bundle for an epoch that has a host timer.

**What it never does.** It never stops, restarts, execs into or writes the paper runtime, never writes the runtime's own pin (the CLI works on a copy), never passes the credential to a container, and has no dependency, restart or failure link to any other unit. A failed tick only fails its oneshot.

**Not shown by any test.** The real upload, the bucket policy and its Deny conditions, the delivery of the systemd credential, the firing of the timer and the permissions of the scratch directory inside the container are owner-run checks on the soak host and the real bucket. `tests/test_deploy_freeze_witness.py` runs the script against stubs of `docker`, `curl`, `systemctl` and `date` with a fake credential, and `tests/test_soak_runbook.py` holds this section to the exporter flags and to placeholders only. The first tick on the real host shows the shape of the container run and of the S3 answer.

## 21. Reconcile loop, SAFE_MODE exit and recovery (Phase 20)

Status: everything in this section is built and tested with fakes (a Binance-semantics fake exchange, in-memory and local PostgreSQL stores). The live composition exists since Phase 24 (sections 21.1a, 21.1b and 22). The Demo smoke rehearsal of 2026-11-06 observed 21 steps on Binance Demo (section 22.6); nothing was observed on a host, the longer Demo campaign and the soak runs are Phases 25 and 26, and the rehearsal on a real stack is not done. Reading this section is not a statement that live execution is safe or ready; the execution model is decided by D079 (2026-10-22) and live placement stays disabled.

### 21.1 Leaving SAFE_MODE (operator exit)

SAFE_MODE is never left by a restart, a timer, a recovered feed, a closed intent or a flag flip. The only way out is `SafeModeController.exit_safe_mode`, an explicit, fail-closed, operator-attributed call. Since Phase 24 the live process has one entry point for it, the Telegram commands `/safemode_exit` and `/confirm <token>` (section 21.1a); the restore drill calls it too. The `operator_id` the commands pass is `tg:<Telegram user id>` of the allow-listed user who confirmed, so it is audit metadata backed by the chat and user allow-list of the live bot (section 21.1a), not a password.

The exit succeeds only when every readiness row holds in one call; every refusal found is returned and journaled as `SAFE_MODE_EXIT_REFUSED` (codes only) and the state does not change:

1. the operator id is a non-blank text;
2. the local intent source (the durable intents and the replayed protection journal) was read; a source that raises or is incomplete blocks the exit, and a local intent with no usable list of active plans refuses `LOCAL_SOURCE_UNREADABLE`;
3. positions, open orders and algo orders were read from Binance during this call (a failed read refuses `BINANCE_READ_FAILED`);
4. the compare on those fresh reads agrees, and no SAFE_MODE entry landed while the reads were awaited (`COMPARE_NOT_CLEAN`); the compare is given the local active plans like the reconcile loop, so a standing symbol-ownership conflict (two active plans on one symbol) refuses `SYMBOL_OWNERSHIP_CONFLICT`;
5. all readiness counts are read and zero: no unresolved execution intent, no plan in UNPROTECTED, CLOSE_REQUIRED or CLOSE_FAILED, no PENDING protective action, and the coordinator's restore after a restart is complete (`RESTORE_NOT_COMPLETE`; a readiness value that is missing or not a boolean refuses `READINESS_UNREADABLE`);
6. the REST gate has no restriction (`GATE_NOT_OPEN`) and its recovery status is `RESTORED_DURABLE` (`RESTORED_BARRIER` is accepted too but reserved; option a1 does not produce it) (`GATE_NOT_RESTORED`; the in-memory, not-restored, unknown-state and persistence-failed statuses all refuse);
7. the user-data stream state is exactly `LIVE` (`STREAM_NOT_LIVE`).

An unfilled resting entry (GTD LIMIT still `NEW` on the exchange, no position on its symbol) does not block the exit and raises no divergence; a position or an entry that vanished from the exchange does (`COMPARE_NOT_CLEAN`).

On success the order is: journal `SAFE_MODE_EXIT` with the operator id first, persist the exit state second, flip memory last. If the journal row was written and the state save then failed, the journal says EXIT while the durable state still says SAFE_MODE and a retry journals a second EXIT row: read the system-state row as the truth. An open gate means only "no restriction currently known"; it never replaces the fresh Binance reads of row 3.

### 21.1a Operator commands on the live bot (`/safemode_exit`, `/confirm`)

The live process (`python -m src.live.runtime`, Phase 24) registers these commands on its OWN Telegram bot (one `getUpdates` consumer per token; the paper/SHADOW bot has none). Every command is checked by the same two gates as an approval press: the message must come from the authorized chat (`TELEGRAM_LIVE_AUTHORIZED_CHAT_ID` of the live service), then from a private chat with a user id in `TELEGRAM_AUTHORIZED_USER_IDS`. Anything else changes nothing, is journaled with the user id, the chat id and a fixed reason code (never the message text) and is answered with the single word `Rejected`.

| Command | Effect |
|---|---|
| `/status` | read only: mode, SAFE_MODE and its reason, entry enablement, REST gate, user-data stream, protections |
| `/disable_entries` | disables new entries at once (risk reducing, no confirmation); idempotent |
| `/safemode_exit` | step 1 of 2: replies with a one-time token; nothing changes yet |
| `/close SYMBOL` | step 1 of 2: replies with a one-time token; the position is closed only after the confirmation, through the coordinator's own close flow |
| `/confirm <token>` | step 2 of 2 for either command above |
| `/demo_signal [far\|fill]` | DEMO only, section 21.1b |

How a SAFE_MODE exit goes:

1. Look at the cause first (`/status`, the journal, the Binance UI). The exit is refused unless every readiness row of section 21.1 holds, so there is nothing to gain by trying early, but the refusal rows are also the checklist.
2. Send `/safemode_exit`. The bot answers with a token. The token is bound to the user who asked, is single use and valid for `CONFIRM_TTL_SECONDS_DEFAULT` seconds (60). Only its SHA-256 is kept, in memory: a restart of the process forgets it, which is the safe direction. Asking again replaces the earlier token.
3. Send `/confirm <token>` from the SAME user within the window. The exit runs in the process through `SafeModeController.exit_safe_mode`, so all seven rows decide. On success the bot says so and the journal holds `SAFE_MODE_EXIT` with `tg:<user id>`; on refusal it lists the controller's own codes (`COMPARE_NOT_CLEAN`, `GATE_NOT_OPEN`, `STREAM_NOT_LIVE`, ...) and SAFE_MODE stays.
4. An unknown, expired, already used or other-user token answers `Not confirmed` and changes nothing. `/confirm` does nothing by itself: it only completes a pending `/safemode_exit` or `/close`.

If the bot does not answer (stream down, process held, bot token conflict), the commands are unavailable: the process still holds new entries in SAFE_MODE, and the exit then needs a restart after the cause is fixed (a restart never leaves SAFE_MODE by itself, section 21.1). Clearing a REST gate restriction stays an ssh command (section 21.3); `/safemode_exit` refuses `GATE_NOT_OPEN` while one is in force.

The start order is, after the recovery below, STREAM, then one RECONCILE tick, then the bot, the scheduler, HEALTH and ENABLE (DECISIONS D094): the user-data stream is up before the first tick, so a clean start, including a restart with an open position, is enabled by the start sequence itself and needs no `/safemode_exit`. SAFE_MODE after a start means something real: read its reason in the journal. A placement records the verified plan constraint snapshot before the entry is sent, which is what lets a restart rebuild a live plan; a reservation is released by the `reservation_release_sweep` task when its plan expired unplaced, when its CONFIRM was refused for a final reason, when its entry was rejected, or when its position closed or its entry ended with no fill (DECISIONS D095); an entry that may still fill stays counted.

After a restart the coordinator is rebuilt from the intent rows, the persisted plans and the journal, and no new entry opens until that restore is complete. The rows it reads are the ENTRY intents in SENT, UNKNOWN and ACKED for plans that have not ended (a `PROTECTION_TRANSITION` into `FLAT` or `ENTRY_ENDED_NO_FILL` ends a plan; no age limit, DECISIONS D093). A row that cannot be rebuilt: section 21.6.

### 21.1b Injecting a Demo smoke signal (DEMO only)

`/demo_signal [far|fill]` is the owner-triggered way to put one Demo smoke request into the RUNNING live process (there is no other: no file to drop, no network port). It exists only when the process runs in DEMO; a LIVE or TESTNET process does not register it and `check_wiring` refuses a start that does. It reads the current Demo exchange filters, mark price, commission rate and account equity through the signed adapter, derives one request sized from that account equity (`far` rests below the mark and is not meant to fill, `fill` sits just above it; the default is `far`), and queues it. The signal-source task then sends the normal approval card, and the placement still needs your APPROVE and CONFIRM presses. One request may wait at a time (`ALREADY_QUEUED` otherwise). The reply and the journal row carry only a fixed code (`QUEUED`, `ALREADY_QUEUED`, `BAD_USAGE`, `FILTERS_UNAVAILABLE`, `EQUITY_UNAVAILABLE`, `DERIVATION_FAILED`). The command has not been run against Binance Demo: that run is owner-only (`--execute` rules apply to the smoke scripts, not to this command, but the Demo evidence is Phases 25 and 26).

### 21.1c The live service under Compose (plan 24-35)

The `live` service of `docker-compose.yml` runs `python -m src.live.runtime --hold-on-refusal` in the same image as the collector (`trading-alert:${IMAGE_TAG}`), which carries `config/execution` and `config/binance` and its build commit (OPS-04); nothing is mounted from the host. It is in profile `live`, so `docker compose up -d` never starts it. It reads only `.env.live` (see 11.1 step 2 and `.env.live.example`), waits for `db-upgrade` to complete, publishes no port, and keeps its state (the REST gate state file, the spill directory, the liveness stamp and the held marker, all under `logs/live`) in its own named volume `livestate`, mounted at `/app/logs`, so recreating the container keeps them.

Start and inspect it as the `trading` user in `/opt/trading`:

```
docker compose --profile live up -d live
docker compose --profile live ps live
docker compose --profile live logs --tail 50 live
docker compose --profile live exec -T live /app/.venv/bin/python -m src.live.runtime --healthcheck
```

`--healthcheck` prints one JSON object (mode, Python version, application revision, held, the refusal code, the age of the liveness stamp, the latest task results) and exits 0 only while the process is live; the compose healthcheck runs it every 60 s with the paper service's timing. A start the process refuses (no `LIVE_RUNTIME_MODE`, a credential of the other mode, a `NOT_CONFIGURED` limit, a closed gate) is held, not exited: the container stays up and unhealthy, writes the held marker, and the reason is in the log (names and codes only, never a value). Stop the container (`docker compose --profile live stop live`), correct the cause in `.env.live` or the limits, and start it again. The external check is `deploy/heartbeat.sh --target live` (it runs `--liveness` in this container).

**Restart policy.** The service has `restart: "no"` and stays so until the owner has seen the first clean Demo run (owner answer Q15 of plan 24-01). With `no`, a host reboot or a daemon restart leaves the live process down, which is the safe default while nothing has been observed. To enable the restart after that run, change the one line in `docker-compose.yml` to `restart: unless-stopped`, commit it and apply it with `docker compose --profile live up -d live`. It is safe to do then because no start path exits 0 or crash-loops on a refusal (the hold above), a requested `stop` keeps the container down, and a crash restarts it into the same start sequence as a first start. Do not enable it earlier, and do not publish a port or add a credential to the compose file.

### 21.2 Spill directory and replay

When the journal is down, records that must not be lost (operator audit rows, pending protective-action intents, the closer's pre-send attempt) are written to a local spill directory by `src/ops/spill.py`: one canonical JSON file per journal event id, written atomically. At start `run_startup_recovery` reads the spill once and replays it into the journal: an identical stored event is `already_present`; a conflicting or corrupt file is kept and enters SAFE_MODE `RESTORE_INCONSISTENT`; a failed journal write enters `DB_FAILURE` and keeps the file. Do not edit or delete spill files by hand. The spill is supplementary evidence of what this process did, never a substitute for Binance truth, and a missing or empty spill proves nothing. In the live process the spill directory is `spill/` under the state directory (`logs/live`, option `--state-dir`), which the compose service keeps in its own named volume `livestate`; the first install writes a sentinel file `.spill-initialized` there, and a later start that finds an initialized gate state but no sentinel treats the volume as re-created empty: the `SPILL_SENTINEL` step enters SAFE_MODE `RESTORE_INCONSISTENT` (entries blocked, monitoring continues; section 22.3). The coordinator does not spill its own `PROTECTION_TRANSITION` rows when the journal is down; that limit is recorded in `20-DEFERRED.md` of Phase 20.

### 21.3 REST gate restart recovery (owner decision O-C, option a1 with commands)

The REST gate keeps its 418 ban and 429 pause deadlines in a state file (`src/ops/rest_gate_state.py`) and restores them at start. The first-install bootstrap call `FileGateStateStore.initialize(...)` runs once, from the live process itself: `python -m src.live.runtime --initialize-gate-state --operator-id ID` (only when no state file exists; section 22.3). The state file lives in the state directory, `logs/live` by default. Accepted consequence of option a1: if the initialized state file is missing, corrupt or cannot be read at start, the gate is in an unknown state and blocks every REST call, including emergency reduce-only closes, protective actions and reconciliation reads, until it is cleared (the assumed ban wait is 3 days, 259200 s); every restart before that keeps the block, and there is no bypass for any order category. The alert hook `REST_GATE_RECOVERY_REQUIRED` (and `REST_GATE_BAN_ENTERED`) reaches the journal-first alert sink in the live process since Phase 24 (plan 24-13 hook, composed in 24-27).

Two operator commands exist (run on the host, over ssh):

```text
python -m src.ops.rest_gate_cli status --path STATE_FILE
python -m src.ops.rest_gate_cli clear  --path STATE_FILE --operator-id ID --reason TEXT [--force]
```

`status` is read-only: it prints whether the file exists, parses and is initialized, the recorded ban and pause deadlines and the recovery status a restart would report. A recorded deadline cannot tell a real Binance ban from the assumed wait: check once by hand before clearing. `clear` needs an operator id and a reason, keeps the old file aside, writes a fresh initialized record with no deadline and takes effect at the NEXT restart; a deadline still in the future is refused unless `--force` is given. Stop the trading process first, because a running process can write its in-memory deadlines back over the cleared file. The operator id is audit metadata, not authentication. Every `clear` that goes ahead first appends one fsynced JSON line (operator id, reason, forced flag, the overridden deadlines, the previous state, the time) to `STATE_FILE.clear-audit.jsonl` and a closing `cleared` or `failed` line after; if the first line cannot be written, nothing is changed (exit 4). A refused clear writes nothing.

### 21.4 Orders and closes made by hand

An order placed by hand in the Binance UI is an exchange order with no local intent: the reconcile tick reports it as a `FOREIGN_ORDER` divergence, enters SAFE_MODE (fail closed) and alerts. The system never cancels it and never guesses an owner. Look at it on the exchange, cancel it by hand if it is unwanted, and leave SAFE_MODE through section 21.1. A position closed by hand leaves protective legs behind or not (what Binance does with a `closePosition` leg when the position closes outside the system is `[NOT_TESTED]`, G4-035); the sweeper cancels an orphan only after two zero position reads (section 12), and a leg whose cancel cannot be proven keeps SAFE_MODE and is looked at again.

Known limit, observed on the Demo smoke run and deferred by the owner on 2026-11-07 (`24-NOTES.md` item 7): when the owner closes a position by hand (`/close SYMBOL`, plan state CLOSE_REQUIRED) while its TP1 order still rests on the exchange, reconcile sees an exchange order with a project client id and no open local intent, reports `UNTRACKED_SYSTEM_ORDER` and enters SAFE_MODE. The system fails closed and nothing is at risk; the cost is a false alert and a `/safemode_exit` (section 21.1a). A candidate rule (TP legs of the same plan may rest in CLOSE_REQUIRED and CLOSE_FAILED) changes Phase 20 semantics, needs its own DECISIONS row and is not adopted. The normal path (a stop or take-profit that fills by itself) is not affected.

### 21.5 Drills

The eight drills in `src/ops/drills.py` (sections 3, 4, 5, 7, 9, 10 and 12, and the restore path) are fake-exchange rehearsals: they run the Phase 20 components against fakes and never touch Binance or Telegram. A passing drill shows that the code path behaves as designed with the fakes, not that a real host or exchange behaves that way. The rehearsal on a real stack is Phases 25 and 26 and is not done.

### 21.6 Partial restore after a restart (D110)

Status: built and tested with fakes (the Binance-semantics fake exchange) by quick tasks 261114-kxu and 261114-mp1, DECISIONS D110. Not observed on Binance Demo or on a host: a real cancel answer and the real position read after a restart, for a plan that could not be restored, are owner-run checks that have not been made.

**What the restore does.** At the RECOVERY step the coordinator is rebuilt from the ENTRY rows of section 21.1a, each row on its own. A fault of one row skips that row: no persisted plan or constraint snapshot for it (`RestoreSourceMissing`), or a value the rebuild refuses (`ValueError`, `TypeError`, `LookupError` or `ArithmeticError`). The log line `live.restore.entry_unrestorable` carries only `trade_plan_id`, `approval_id` and the fault class, never the row text. The healthy plans are restored and stay supervised, and the step `COORDINATOR_RESTORED` fails with SAFE_MODE `RESTORE_INCONSISTENT`. A fault of the store itself (any other exception class) restores nothing, enters SAFE_MODE `DB_FAILURE` with the restore incomplete, and sends no cancel; there fix the database or its connection first, then restart.

**What the process does next.** RECOVERY is not a hold step, so its failure degrades the start instead of holding it: the process is admitted, in SAFE_MODE, with RECOVERY among its degraded steps. The stream, the reconcile tick, the bot and the scheduler start, so monitoring continues. HEALTH and ENABLE are skipped, so that start never enables entries (entries start disabled at every start, section 22.2). `--hold-on-refusal` does not apply, because a degraded start is admitted. After a partial restore the coordinator's restore counts as complete, so the reconcile loop runs its ticks; leaving SAFE_MODE stays the operator's, through section 21.1.

**The one cancel.** With SAFE_MODE already on, the start sends ONE cancel request for the resting entry of each unrestorable plan, one per distinct plan hash. It cancels by the deterministic client order id of that entry (the plan hash and the symbol come from the intent row, which exists even when the persisted plan does not), through `expire_pending_entry` with the existing trigger `protection_handoff_failed`, and queries that order once afterwards. The audit row is a journal `ENTRY_EXPIRY` row that carries that trigger. This code never places an order, never closes a position and never sends a second cancel. One request here is not always one request on the wire: the adapter's `cancel_normal_order` keeps its existing bounded retry on STATUS_UNKNOWN (`_cancel_retrying` in `src/adapters/binance_usdm.py`, at most `_RECONCILER_CANCEL_MAX_ATTEMPTS` = 3 attempts), and an order that is already absent counts as success, so the request can become a few identical requests, all idempotent by the client order id. A row whose plan hash equals the hash of a rebuilt plan is never cancelled, because the same client order id would hit the order of the supervised plan; it is refused and alerted instead.

| Alert (severity) | Reason | When |
|---|---|---|
| PROTECTION_HANDOFF_FAILED (CRITICAL) | `UNRESTORED_CANCEL_UNVERIFIED` | the query after the cancel says the entry is still open, or its state is unknown |
| PROTECTION_HANDOFF_FAILED (CRITICAL) | `UNRESTORED_CANCEL_FAILED` | the cancel request raised |
| PROTECTION_HANDOFF_FAILED (CRITICAL) | `UNRESTORED_CANCEL_REFUSED` | refused before any call (a symbol outside the live-5 universe, or a malformed plan hash), or the plan hash is shared with a rebuilt plan |
| DIVERGENCE (HIGH) | `UNRESTORED_PLAN_POSITION` | the one position read of the symbol shows a non-zero amount, or an amount that is not a Decimal |
| DIVERGENCE (HIGH) | `UNRESTORED_POSITION_UNKNOWN` | the position read failed, or the symbol is outside the live-5 universe and nothing was read |

A cancelled entry, an entry that left the book by itself and an entry that filled raise no cancel alert; a fill shows up through the position read. A failing alert sink, or a failure of the whole cancel step, is logged by class name and never stops the start.

**What stays the operator's.** The unrestorable plan has no stop placed by the coordinator, and its order ids are unknown to the stream router, so a fill of it is not protected by the system. The system never closes that position and does not decide whose it is. Operator steps:

1. Read the journal and the log: the `LIVE_STARTUP_STEP` row of RECOVERY (section 22.2), the `live.restore.entry_unrestorable` line (which row, which fault class), the `ENTRY_EXPIRY` rows with the trigger `protection_handoff_failed`, and the alerts of the table.
2. Check the named symbol by hand on Binance: its position and its open orders. A position there has no stop from the system: protect or close it by hand if it needs it (an order made by hand is a foreign order to the reconcile, section 21.4). An entry that still rests after an `UNRESTORED_CANCEL_*` alert: cancel it by hand.
3. Fix the database row the log names (by `trade_plan_id` and `approval_id`): `RestoreSourceMissing` means its persisted plan or constraint snapshot is missing; the other classes mean a value the rebuild refuses. The repository has no tool for this: it is a manual correction in the database. Until it is fixed, every start repeats the partial restore, because the cancel does not rewrite the intent row and the restore reads the same rows (section 21.1a), and every such start sends its own one cancel request.
4. Restart the process (commands in section 21.1c; read section 22.5 on what a stop leaves resting).
5. Leave SAFE_MODE only through section 21.1 (`/safemode_exit` and `/confirm`, section 21.1a); its readiness rows decide.

A single wire request for this cancel, bypassing the adapter retry, would be an adapter change with its own decision; it is not done.

## 22. Live process (Phase 24)

Status: built and tested with fakes and with local PostgreSQL. It was observed on Binance Demo once, by the owner-run smoke rehearsal of 2026-11-06 (21 of 21 steps passed, section 22.6). Not observed: any run on a host (the owner VPS session, plan 24-33), the heartbeat, the compose service on a host, and everything Phases 25 and 26 are for. Live placement is disabled (`LIVE_ORDERS_DISABLED`, `src/execution/enablement.py`). The decisions are DECISIONS D098 to D107; this section says how to run what they decided. Reading it is not a statement that live execution is safe or ready.

### 22.1 What the process is

One process, `python -m src.live.runtime`, one asyncio loop (D098): Telegram bot runner (its own bot, D103), user-data stream, protection stepper, reconcile task, sweeper, health task, clock-drift re-measure, risk-input refresh and the reservation release sweep. Every store call on the loop goes through `src/ops/store_executor.py` (D099). It never imports the paper runtime. The mode is explicit: `LIVE_RUNTIME_MODE` must be exactly `DEMO` or `LIVE`; a credential of the other mode, a `NOT_CONFIGURED` limit, or the SHADOW bot variable `TELEGRAM_BOT_TOKEN` in its environment refuses the start.

| Verb | Use |
|---|---|
| `python -m src.live.runtime` | run the process; `--hold-on-refusal` stays up, unhealthy, with a held marker instead of exiting (the compose command uses it) |
| `--healthcheck` | one JSON object (mode, Python version, application revision, held, liveness age, task results); exit 0 only while live; opens no network or database client |
| `--liveness` | heartbeat probe: `live` and exit 0 only with no held marker and a liveness stamp younger than `stale_feed.max_mark_price_age_ms` |
| `--initialize-gate-state --operator-id ID` | first install only, section 22.3 |
| `--state-dir PATH` | the state directory (default `logs/live`) |

### 22.2 Start sequence

Each step is journaled as `LIVE_STARTUP_STEP` (name, outcome, a code; never a value). The order, after D094 (owner, 2026-11-01), is: CONFIG, GATE, ALEMBIC, SAFE_MODE, ENABLEMENT, SNAPSHOTS, SPILL_SENTINEL, CLOCK_DRIFT, EXCHANGE_INFO, RECOVERY, STREAM, RECONCILE, CONFIRM_EXPIRY, ALERT_REQUEUE, BOT, SCHEDULER, HEALTH, ENABLE. A failure in CONFIG, GATE, ALEMBIC, SAFE_MODE or ENABLEMENT holds the process (nothing starts); a failure elsewhere continues in SAFE_MODE with entries blocked and monitoring running. ENABLE runs in DEMO only, after a passing health verdict (D102); entries start disabled at every start. SAFE_MODE is never left by a restart (section 21.1). A `live.health.not_ok failing=['telegram_delivery']` warning at start is expected: that item reads FAIL until the first real Telegram send. A RECOVERY step that restores only part of the plans: section 21.6.

CLOCK_DRIFT passes when the measurement WORKS, not when the host is inside its limits. `place_entry` then refuses (`ENTRY_REFUSED_BEFORE_SEND`, journaled with the guard's reason) while the drift guard says OUT_OF_LIMITS.

**Host clock.** The host clock must be synchronised by NTP (chrony on the Linux host, section 13; w32time on the Windows development machine). The drift guard (`[drift]` of `config/binance/binance-limits-v1.toml`) blocks new entries when the host is more than 500 ms ahead of Binance or more than 1000 ms behind, counting the measurement uncertainty; it re-measures every 60 s and a measurement older than 300 s is stale. A Windows machine whose w32time is unsynchronised ("Local CMOS Clock") ran about 550 ms ahead during the Demo runs and every placement was refused until `w32tm /config` pointed it at an NTP server and the clock was stepped. The rehearsal pre-flight (section 22.6) stops before any card when the guard blocks.

### 22.3 First install: gate state and spill sentinel

On the first install, and only then, start the process once with `--initialize-gate-state --operator-id ID`. It creates the REST gate state file in the state directory, only when none exists (a corrupt file counts as existing and is never re-initialized silently), and the same start writes the sentinel `spill/.spill-initialized`. A later start without the flag and without the state file is "unknown", not a fresh install: the gate blocks every REST call until the owner clears it (section 21.3). A later start that finds an initialized gate state but no sentinel treats the spill volume as re-created empty and enters SAFE_MODE `RESTORE_INCONSISTENT`. State (gate file, spill directory, liveness stamp, held marker) lives under `logs/live`, which the compose service keeps in its own named volume `livestate` (section 21.1c).

### 22.4 Environment and compose

The live service reads only its own env file, `.env.live` (template `.env.live.example`, mode 0600, gitignored) or the file named by `TRADING_LIVE_ENV_FILE`: `LIVE_RUNTIME_MODE`, the `BINANCE_DEMO_*` or `BINANCE_LIVE_*` credentials (never both), `TELEGRAM_LIVE_BOT_TOKEN`, `TELEGRAM_LIVE_AUTHORIZED_CHAT_ID`, `TELEGRAM_AUTHORIZED_USER_IDS` and the database values (D107 item 1; section 13.6). The SHADOW names stay in `.env.paper`. Limits come from `config/execution` and `config/binance`, which are baked into the image (D106), so a changed limit is a rebuilt and re-pinned image. The compose service, its start and inspect commands and its restart policy are in section 21.1c: `restart: "no"` until the owner has seen the first clean Demo run (owner answer Q15 of plan 24-01). That run now exists (section 22.6); the owner has not switched the policy.

### 22.5 Operator commands and the heartbeat

The commands on the live bot (`/status`, `/disable_entries`, `/safemode_exit`, `/close SYMBOL`, `/confirm <token>`, and in DEMO `/demo_signal`) and the SAFE_MODE exit are in sections 21.1 and 21.1a; their authentication is the authorized private chat plus the user-id allow-list, and the `/confirm` token lives 60 s (D104). The external heartbeat is `deploy/heartbeat.sh --target live` (own URL file, own units, probe `--liveness` inside the container; URLs go in by stdin only), one healthchecks.io check per process (D106). Neither the heartbeat nor its units have been run on a host.

**Stopping the live process (review WR-04, `24-DEFERRED.md` R-22).** Protection is fill-driven (D079): the stop is placed only after the process sees a fill, and `shutdown_in_order` stops the protection step and the stream before the process exits. The process does not cancel resting entries on stop, so a GTD LIMIT entry that is still resting can fill while the process is down or restarting and stay without a stop until the next start protects it. Until cancel-on-stop is built (Phase 25), stop it like this: (1) send `/disable_entries` on the live bot, which blocks new entries only and cancels nothing; (2) send `/status` and wait until the line `protections: 0 open of N tracked` shows, that is until every resting entry has filled and been protected or has expired (confirm on the first Demo run that a resting entry counts as open there); (3) only then run `docker compose --profile live stop live` or `deploy/update.sh`. `deploy/update.sh` refuses to run while the `live` service is running (override only with `--force-live`, which accepts the window). After the restart, read `/status` before sending new signals.

### 22.6 Demo rehearsal (owner-run)

The Demo rehearsal is `scripts/demo_rehearsal.py`, run by the owner only. Without `--execute` it runs the same sequence against a fake exchange and sends nothing. With `--execute` it uses the live process's own environment (`LIVE_RUNTIME_MODE=DEMO`, the Demo credentials and the live Telegram names; never the SHADOW names), needs an interactive terminal and the exactly typed phrase `DEMO SMOKE BTCUSDT`, and sends real requests to `demo-fapi.binance.com`. Procedure:

1. Close every position and order on the Binance Demo account, and check that the host clock is synchronised (section 22.2).
2. Run `scripts/demo_clear.py` (from the repo root; on Windows `$env:PYTHONPATH = "."; uv run python scripts/demo_clear.py`). It needs `LIVE_RUNTIME_MODE=DEMO` and `DATABASE_URL`, asks for the phrase `DEMO IS FLAT`, refuses while an execution intent is unresolved, closes every plan behind an open DEMO approval through the DOMN-04 transition APPROVED to EXPIRED (one journal row `DEMO_STALE_PLAN_CLEARED` each) and exits a persisted SAFE_MODE with the operator id `owner-demo-clear`. Without it a plan whose CONFIRM was refused or never pressed stays APPROVED until its expiry (about 26 minutes for a smoke plan) and blocks every new card of the symbol. The risk reservation of a closed plan is released by the live process's own sweep at its next start, not by the script.
3. Run `uv run python -m scripts.demo_rehearsal --execute` and type the phrase. Every owner instruction is printed as `OPERATOR: ...` and sent to the live Telegram bot as `REHEARSAL: ...`, so the terminal need not be watched. Within about six minutes: APPROVE then CONFIRM the first card; after the restart the script performs, tap APPROVE and CONFIRM on the first card again (replays that must place nothing); APPROVE and CONFIRM the drill card (SAFE_MODE is entered on purpose and the CONFIRM must be refused with nothing placed); send `/safemode_exit` and send back the `/confirm <token>` line within 60 s. Then leave it: the last step waits for the drill plan's natural expiry (about 26 minutes) to show that the sweep released the refused drill's reservation. Do not interrupt it.
4. The run ends with an `evidence:` line naming `09-DEMO-REHEARSAL-EVIDENCE-smoke-<UTC>.json` in the phase evidence directory; a failure prints `STOPPED at step <name>` and the file records outcome `FAILED`. Then check that the Binance Demo account is flat.

A refused CONFIRM (SAFE_MODE, clock drift, `RECONCILIATION_REQUIRED`) leaves the plan APPROVED until its expiry (DECISIONS D051 item i). Nothing is re-sent: a DEMO placement is never re-sent, one `place_entry` POST per approval; an ambiguous result is probed once by client order id, and not found or a probe error is UNKNOWN with SAFE_MODE (D079, D080).

Observed on Demo (smoke rehearsal of 2026-11-06, `09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json`, outcome COMPLETE, 21 of 21 steps PASSED, committed): start sequence admitted, entries enabled by the start sequence, the signal and the approval card, APPROVE and CONFIRM, a GTD LIMIT entry fill seen on the user-data stream, a REST-confirmed stop and the TP legs, a clean reconcile, a restart that rebuilt the plan, replayed presses that placed nothing, the operator close, the reservation released on close, a flat account, and the SAFE_MODE drill with its reservation released. Not observed there: the heartbeat, the compose service and the image revision stamp on a host; `/status`, `/disable_entries` and `/close` as typed commands; a stale-feed SAFE_MODE; an emergency close; the P3, P7 and A2 items that wait for Phases 25 and 26 (`19-OWNER-GAPS.md`). `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False (D086): the Demo fill is evidence only.

### 22.7 Open items (owner)

- No re-issued CONFIRM card after a restart (`24-28-SUMMARY.md` finding 1). After a restart the old confirm card is expired (`RUNTIME_RESTART`) and answers `NO_CONFIRM_CONTEXT`; a plan already APPROVED gets no new card, and a new request for the same plan is refused. The owner waits for the plan to expire and for a new signal. Safe (no duplicate order), inconvenient. Recommendation: accept for V1; build a re-issue path only if it hurts in use. Decision pending.
- A manual close while TP1 still rests ends in a false `UNTRACKED_SYSTEM_ORDER` SAFE_MODE (section 21.4). Deferred by the owner on 2026-11-07; decide after Phase 24.
- Which later phase owns strategy-driven DEMO signals (D101) is not named.
- The `restart: "no"` policy of the live service is the owner's switch (section 22.4).
- Review items of 2026-11-07 deferred to Phase 25, each with a row in `24-DEFERRED.md` and an entry in the ROADMAP Phase 25 inherited items: R-21 margin reservations never advance (`mark_placed` and `mark_open` have no caller; needs a DECISIONS row on when `mark_placed` is stamped), R-22 cancel-on-stop (the stop procedure in 22.5 is the interim), R-23 sync store calls on the event loop in the operator commands and start-time rehydration, R-24 pool-timeout error not wrapped as `StoreUnavailable`, R-25 health tick journal volume (about 63,000 rows a day).
- Stuck first install (R-26): if a host ever has the REST gate state file but no `spill/.spill-initialized` in the `livestate` volume, the start enters SAFE_MODE `RESTORE_INCONSISTENT` and `--initialize-gate-state` refuses (`GATE_STATE_EXISTS`); create the sentinel file by hand. New installs cannot reach this state since commit cc9a9df8.
- The value of `scheduler.protection_stall_after_ms` is the owner's: it ships `NOT_CONFIGURED`, so the stall watchdog is off and no `TASK_STALLED` alert can fire until it is set (section 22.8, D111).
- A literal single wire request for the restart cancel of an unrestorable plan needs an adapter change and its own decision (section 21.6).

### 22.8 TASK_STALLED and the protection stall bound (D111)

Status: built and tested with fakes by quick tasks 261114-kxu (the watchdog) and 261114-mp1 (the alert and the key), DECISIONS D111. The shipped limits leave it off. Nothing was observed on Demo or on a host.

**Meaning.** The scheduler runs the protection task `protection_step`. When that task has a stall bound, a watchdog starts beside each run; if the run is still going after the bound, it logs one error line naming the task and the bound in seconds and records one stall event for that run. `LiveWiring._record_task` journals it as a `LIVE_TASK_EVENT` row (correlation `live_scheduler`, entity `protection_step`, payload `task`, `kind` and `error_class`) and then raises the HIGH alert `TASK_STALLED`, whose header subject is the task name and whose reason is `STALL_BOUND_EXCEEDED`; the alert is raised also when the journal write failed. Only the protection task has a bound.

**Observe only.** The run is never cancelled, cut short, stopped or restarted by the watchdog or the alert. Nothing is cancelled and nothing is re-sent.

**The key.** `scheduler.protection_stall_after_ms` in section `[scheduler]` of `config/execution/execution-limits-v1.toml` ships `NOT_CONFIGURED` as its value and as its provenance. It is alert-only: unlike a required key (section 22.1), unset it never refuses the start. While it is unset the watchdog is off, no stall row is written and no `TASK_STALLED` is raised. It stays off until the owner sets a value with its own DECISIONS row and the provenance `DECISION`. An integer value needs a provenance of STRUCTURAL, COST_GUARD, DECISION or EXPERIMENT; PLACEHOLDER refuses to load. To fire before the unprotected deadline the value must stay below `protection.max_unprotected_ms`. Limits are baked into the image (section 22.4, D106), so a set value is a rebuilt and re-pinned image.

**How to react.** Check the process log and the exchange position and its stop now. Close or protect the position by hand if it needs it. Restart the process if the task does not finish (a restart never leaves SAFE_MODE, section 21.1; a stop leaves resting entries, section 22.5). Repeated stalls inside `alerts.dedupe_window_ms` are suppressed in Telegram and journaled as `ALERT_SUPPRESSED`, while every stall keeps its `LIVE_TASK_EVENT` row.

**Measuring a bound (owner; no value is chosen here).** The journal holds no per-run duration: `protection_step` rows exist only for `first_run`, `failure`, `recovery` and, with a bound set, `stall`. Read-only query 1, the stall rows (empty while the key is unset):

```sql
SELECT occurred_at_utc, payload_json
FROM journal_events
WHERE correlation_id = 'live_scheduler'
  AND entity_id = 'protection_step'
  AND event_type = 'LIVE_TASK_EVENT'
  AND payload_json LIKE '%"kind":"stall"%'
ORDER BY occurred_at_utc;
```

Read-only query 2, the protection transitions of every plan (correlation `protection_<plan hash>`, event type `PROTECTION_TRANSITION`):

```sql
SELECT correlation_id, occurred_at_utc, payload_json
FROM journal_events
WHERE correlation_id LIKE 'protection\_%'
  AND event_type = 'PROTECTION_TRANSITION'
ORDER BY correlation_id, occurred_at_utc;
```

Reading query 2: per plan, take the time from the transition to `UNPROTECTED` (fill seen) to the transition to `PROTECTED_ENTRY_OPEN` or `PROTECTED` (stop confirmed). That is a lower bound only, and only when both rows were journaled by the same run: the journal does not say which run wrote a row, so a gap across two runs includes the wait between runs, and a fill also wakes the protection task. The direct method, owner-run on Demo only and never by an agent:

1. No command-line flag selects the limits file, so the owner edits the Demo host's copy of `config/execution/execution-limits-v1.toml` for the measurement only (an image or checkout used only for that run) and never commits it.
2. Set a trial value of `protection_stall_after_ms` in `[scheduler]` and the provenance `EXPERIMENT` in `[provenance.scheduler]`.
3. Run Demo sessions that exercise the protection step (fills, stop placement, restarts, take-profit attach) and count the stall rows of query 1 per trial bound; lower the bound until the first stall rows appear.
4. Adopt the observed maximum plus a margin the owner chooses, below `protection.max_unprotected_ms`.
5. Record it with a DECISIONS row and the provenance `DECISION`.

A per-run duration record would make this direct but needs a new decision; it is not built.
