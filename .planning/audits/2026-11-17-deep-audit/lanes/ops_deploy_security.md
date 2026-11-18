# Lane M12: ops_deploy_security

## Scope

`src/ops/*` except `alerts.py`, `alert_wording.py`; `deploy/**`, `Dockerfile`, `docker-compose.yml`,
`.github/workflows/*`, `pyproject.toml`, `uv.lock`, `.gitignore`, `.dockerignore`. Snapshot `55885b9`.
Finding IDs G-1200..1299. A second agent continued this partial run; every claim below was re-checked
by it. Probes (under `AUDIT\tmp\ops_deploy_security\`): `probe_redaction.py` (output
`probe_redaction.out`), `probe_f708.py` (output `probe_f708.out`).

## Progress notes of the first partial run (kept as written)

Read so far (DEEP): Dockerfile, .dockerignore, .gitignore, docker-compose.yml, deploy/lib.sh, update.sh,
backup.sh, restore.sh, backup-drill.sh, backup-real-s3-gate.sh, deploy/systemd/*, soak.env.example,
evidence.env.example, src/ops/redaction.py, src/ops/spill.py; NORMAL: src/ops/backup.py, backup_remote.py.
Probe: `tmp/ops_deploy_security/probe_redaction.py` (redaction shapes, fake secrets).
Candidate findings noted so far (to be written up): redaction has no shape rule for a bare Binance
key / libpq `password=` keyword / heartbeat URL (value layer covers env secrets); backup timer has no
failure notification; backup scope excludes the `logs` and `livestate` volumes; the host backup
credential can purge snapshots; update.sh leaves paper/live containers on the old image.

(Second run's disposition of these candidates: redaction shapes -> G-1205 LOW (value layer and runtime
registration cover the realistic paths); backup failure notification -> G-1201; backup scope -> G-1202;
purge credential -> Decision review (mitigated by required versioning, RUNBOOK 11 step 4), no finding;
update.sh and paper -> no finding (paper runs in the separate soak project, RUNBOOK 20; live is required to
be stopped and is restarted by the operator explicitly).)

## Coverage

| File | Level | Note |
|---|---|---|
| Dockerfile | DEEP_READ | digest-pinned bases, non-root UID 10001, PGDG key fingerprint check, healthcheck |
| .dockerignore | DEEP_READ | .env*, .git, .planning, data, logs, tests excluded |
| .gitignore | DEEP_READ | .env*, secrets*.env, *.pem, id_ed25519*, .deploy/ |
| docker-compose.yml | DEEP_READ | per-service env files, loopback-only postgres, live profile restart "no" |
| deploy/lib.sh | DEEP_READ | set -Eeuo pipefail, run/DRY_RUN, write_if_changed atomic |
| deploy/update.sh | DEEP_READ | live-running refusal, rollback record, retry detection |
| deploy/backup.sh | DEEP_READ | wrapper only, local-only mode, soak bucket check |
| deploy/restore.sh | DEEP_READ | pull + refusing restore + start default profile |
| deploy/heartbeat.sh | DEEP_READ (URL/ping/install), NORMAL_READ (arg parsing) | URL only via curl --config stdin, xtrace refusal |
| deploy/systemd/* (12 units) | DEEP_READ | no OnFailure= on any unit |
| deploy/migrate.sh | NORMAL_READ | header, order, refusal rules |
| deploy/bootstrap.sh | NORMAL_READ | .env mode 0600 check, password >= 16 chars, SSH lock-out guard |
| src/ops/redaction.py | DEEP_READ | probed (28 cases) |
| src/ops/spill.py | NORMAL_READ | header, naming rules |
| src/ops/backup.py | NORMAL_READ | libpq_target / child_env probed |
| src/ops/backup_remote.py | NORMAL_READ | layout, sentinel, retention, purge |
| .github/workflows/ci.yml | DEEP_READ | PG tests run in CI, docker job, shellcheck, mypy |
| .github/workflows/registry-gate.yml, research-gate.yml, paper_freeze_check.yml | NORMAL_READ | triggers, permissions, pins |
| pyproject.toml | DEEP_READ | ranges vs lock; no forbidden package |
| uv.lock | METADATA_ONLY | package/version list (`tmp/ops_deploy_security/lock_pkgs.txt`) |
| deploy/compose-soak.sh | NORMAL_READ | `down -v` / foreign project refusal; no `live` profile rule (G-1203) |
| deploy/freeze-witness.sh | NORMAL_READ | credential via curl `--config -`, xtrace refusal, create-only witness |
| deploy/refresh-pins.sh | NORMAL_READ | read-only lister/lookup |
| deploy/backup-drill.sh, deploy/backup-real-s3-gate.sh | NORMAL_READ | wrappers; real-S3 gate still owner-pending (KNOWN: STATE 261020-bkp) |
| deploy/compose-rehearsal.sh, deploy/soak-image.sh | METADATA_ONLY | header + `bash -n`; env-file redirection checked via lib.sh |
| deploy/soak.env.example, deploy/evidence.env.example | NORMAL_READ (first run) | templates, no values |
| all 14 `deploy/*.sh` | `bash -n` on copies | all pass; all `set -Eeuo pipefail` (lib.sh is sourced) |
| src/ops/rest_gate_state.py | NORMAL_READ | atomic write + fsync, exclusive initialize, corrupt file kept aside |
| src/ops/rest_gate_cli.py | NORMAL_READ | no env read, no secret; audit line before change |
| src/ops/operator_evidence.py | NORMAL_READ (header) | evidence scrubbed twice and re-scanned before keeping |
| src/ops/evidence_remote.py | NORMAL_READ (header) | separate credentials, env-to-rclone mapping, no argv secrets |
| src/ops/backup_gate.py | NORMAL_READ (header) | throwaway prefix, purge on every exit, bucket name masked |
| src/ops/cutover.py | NORMAL_READ (header) | prints only exception type names through scrub |
| src/ops/drills.py | NORMAL_READ (header) | fakes only (see Decision review) |
| src/ops/health.py, risk_first.py, store_executor.py | NORMAL_READ (headers) | owned by live lanes for behaviour; no secret or deploy issue seen |
| src/ops/__init__.py | METADATA_ONLY | 26 lines |
| src/ops/alerts.py, alert_wording.py | NOT_READ | out of scope (telegram_alerts lane) |
| tracked files (whole repo) | scanned | no API-key/Telegram-token/ping-URL shaped value committed; Demo account JSON fixtures carry balances only (Demo, no key, no listenKey) |

## Verified Safe Areas

- **Database password never in argv** -> `src/ops/backup.py` `libpq_target` returns a URL without the password
  plus `PGPASSWORD` in the child env; `child_env(prefixes=("PG",))` passes only `PATH` + `PG*` (probe_f708:
  Binance, Telegram and BACKUP_ names are not forwarded to pg_dump or rclone children).
- **Redaction value layer** -> with the secrets in the environment every tested form (bare key, secret in a repr,
  Telegram URL, DB URL, libpq `password=` kv, repr-escaped) is masked (probe_redaction.out lines 2-11).
  Runtime-loaded secrets are registered (`src/adapters/binance_client.py:380-381`, `src/live/config.py:255`,
  listenKeys `src/adapters/binance_userdata.py:565,598,627`). Every long-running entry point calls
  `configure_logging` (`src/live/runtime.py:353`, `src/paper/runtime.py:1484`, `src/data/collector.py:1147`,
  `src/ops/backup.py:1082`, `src/ops/cutover.py:530`, `src/data/backfill_cli.py:1145`).
- **Short DB password** -> the redactor ignores values < 8 chars (`src/ops/redaction.py:80`), but
  `deploy/bootstrap.sh:494-537` refuses a POSTGRES_PASSWORD shorter than 16 characters or not URL-safe.
- **Heartbeat URL secrecy** -> `deploy/heartbeat.sh`: read with `read -rs` from stdin (`set_url`), stored 0600,
  mode re-checked before use (`8#$mode & 8#077`), handed to curl only through `--config -` on stdin, curl stderr
  discarded, the script refuses to run under `set -x` (`main`). Systemd passes it with `LoadCredential=`.
- **Heartbeat does not hide outages** -> heartbeat timers have no `Persistent=` catch-up; the live check pings
  only while `src.live.runtime --liveness` passes (`deploy/systemd/trading-live-heartbeat.service:26`).
- **Container** -> non-root `USER 10001` (`Dockerfile:66-69`, the ops target drops back at `:104`); every base
  image pinned by tag+digest (`Dockerfile:12,15,17`, `docker-compose.yml:70`, CI `ci.yml:34`); PGDG key
  fingerprint checked before use (`Dockerfile:98`); postgres published on 127.0.0.1 only
  (`docker-compose.yml:80`); live publishes no port.
- **Secret separation per service** -> `docker-compose.yml:225-232` live reads only `.env.live`; the collector gets
  no Binance/Telegram/backup names; the backup service mounts rawdata read-only (`:270-273`).
- **Build context** -> `.dockerignore` excludes `.env`, `.env.*`, `.git`, `.planning`, data, logs, tests.
- **update.sh** -> refuses while `live` runs and when the probe fails (`deploy/update.sh:105-128`); refuses a dirty
  tree and a ref starting with `-` (`:91`); a retry keeps the last good record (`is_retry`, `:170-184`); rollback
  verifies image IDs before and after the retag (`:252-259`). `set -Eeuo pipefail` in every script (lib.sh:8).
- **Backups** -> encrypted with rclone crypt (names and contents); a sentinel guards against a wrong key looking
  like an empty bucket; Parquet uploads `--immutable`; retention deletes only `snapshots/<id>` after the new
  snapshot passed cryptcheck (`src/ops/backup_remote.py:1-34, 892-934`). Restore refuses a non-empty target
  unless `--force`; restore starts only the default profile, so live is not started (`deploy/restore.sh:96`).
- **CI** -> PostgreSQL tests run in CI (service container + `TEST_DATABASE_URL`, `.github/workflows/ci.yml:31-73`),
  mypy, ruff, `uv lock --check`, shellcheck on `deploy/*.sh`, docker-marked tests; `TRADING_CI_STRICT=1`;
  actions pinned by SHA; `permissions: contents: read`; `persist-credentials: false`.
  `verify_decision_alignment.py all` runs in `registry-gate.yml:101`. Local master contains develop
  (`git rev-list master..develop` = 0 in the original repo), so the merged code went through these triggers.
- **Dependencies** -> no package forbidden by AGENTS.md (no binance-connector, ccxt, pandas, NumPy, SciPy,
  Redis/Kafka); no pre-release (httpx 0.28.1, SQLAlchemy 2.0.54, polars 1.44.2); the lock is the install
  source (`uv sync --frozen` in Dockerfile:31 and CI). Static tools at the snapshot: mypy 0 issues in 291
  files, ruff clean (`tool-output/`).

## Decision review

| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D045(b) no application-level encryption; redaction only removes text | SOUND | practice | encryption at rest is delegated to rclone crypt and the provider; logs are scrubbed |
| Secrets only in env files, mode 0600, per-service split (D-29, plans 24-30/24-36) | SOUND | practice (least privilege) | the always-on collector holds no trade key, no bot token, no backup secret |
| Backup: daily, encrypted, off-host, 7/4/6 retention, versioning required of the operator | SOUND with caveat | practice (3-2-1, immutable copy) | the job's own credential can purge snapshots; protection rests on operator-enabled versioning/object lock (RUNBOOK 11 step 4, `S3_VERSIONING` check) |
| Live service `restart: "no"` until a first clean Demo run (O-2) | SOUND now / CANNOT_JUDGE mainnet | owner goals | fail-closed while unproven; on mainnet a crash is visible only through the external live heartbeat |
| D098 one live process | DOUBTFUL as implemented | practice (single-writer guard) | stated as a rule, nothing enforces it (G-1203) |
| Backup failure visibility = systemd unit status only | DOUBTFUL | owner goals (part-time, no daily console check) | G-1201 |
| Daily 03:15 UTC backup as the only DB copy for the live journal | DOUBTFUL for mainnet | practice (RPO sized to risk) | up to 24 h of journal lost on host loss; no number was derived (G-1202) |
| D-05 exact pins, with PGDG client floating in major 17 | SOUND | practice | conscious, documented exception; key fingerprint checked |
| D064/D066 backup integrity by manifest SHA-256 + cryptcheck | SOUND in design / UNPROVEN on a real provider | official rclone behaviour, D064 rationale | real-S3 gate still owner-pending (KNOWN: STATE 261020-bkp); until it runs, backups are proven only against an S3 double |
| D-05 "RUNBOOK drills with injected faults before live enablement" via `src/ops/drills.py` | DOUBTFUL as evidence | practice (game-day on the real stack) | the harness drives fakes only ("NEVER touches the network"); it proves the code path, not that the operator procedure works on the host (for lane operator_golive_gap) |
| `.env` mode 0600 + bootstrap password >= 16 chars | SOUND | practice | enforced in code for `.env` (not for the per-service files, G-1206) |

## Findings

### G-1201 Backup failure is visible only in `systemctl status`; no alert, no freshness check
- ID: G-1201 · Severity: LOW (now) / MEDIUM (mainnet) · Confidence: CONFIRMED · Classification: GAP
- Category: ops/backup · Component: deploy/systemd backup units, src/ops/health.py, deploy/heartbeat.sh
- File: `deploy/systemd/trading-backup.service` · Lines: 1-17 (also `trading-soak-backup.service:1-25`)
- Rule: D042 condition 2 (off-host backup), RUNBOOK 11; owner goal "part-time, fail closed"
- Known-prior: none found (no `OnFailure`, no backup-age probe in any doc or code)
- Evidence: the unit comment says "a failed backup makes this oneshot unit fail visibly (`systemctl status
  trading-backup`, `journalctl -u trading-backup`)" (`trading-backup.service:3-4`). The unit has no `OnFailure=`
  line. `grep -i backup src/ops/health.py deploy/heartbeat.sh src/live/*.py` finds nothing: no health probe or
  heartbeat checks the age of the last good snapshot. RUNBOOK line 231: "Check with
  `systemctl list-timers trading-backup.timer`, `systemctl status trading-backup` and `journalctl -u trading-backup`".
- Expected: a failed or missing nightly backup reaches the operator without a login (Telegram alert, a fail
  ping to the external monitor the project already uses, or a "last snapshot age" health probe).
- Actual: a broken backup (expired S3 key, full disk, rclone error, changed crypt password) fails silently
  every night until someone reads the unit status or needs a restore.
- Reproduction: read the unit files; `grep -rn OnFailure deploy` returns nothing.
- Impact: now LOW (Demo only, data reproducible). Mainnet: the operational DB (journal, approvals,
  reservations, order intents) can be days or weeks without a usable off-host copy, discovered only at restore.
- Why tests miss it: tests check unit text and exit codes, not that a human learns of a failure.
- Remediation: `OnFailure=` to a notify unit, or a dedicated external-monitor check pinged only on
  `scheduled-OK` (reuse the `heartbeat.sh` mechanics), or a health probe of the newest complete snapshot age.

### G-1202 Backup scope and RPO: `logs`/`livestate` volumes are never backed up; journal RPO is up to 24 h
- ID: G-1202 · Severity: LOW (now) / MEDIUM (mainnet) · Confidence: CONFIRMED · Classification: DESIGN
- Category: ops/backup · Component: docker-compose.yml backup service, src/ops/backup.py
- File: `docker-compose.yml` · Lines: 252-276, 213-217, 295-302
- Rule: D-12/D-13 (backup), RUNBOOK 11; T-24-102 (livestate keeps gate state and unsent spill)
- Known-prior: none
- Evidence: the backup service mounts only `rawdata` (read-only) and `backupdata` and dumps PostgreSQL
  (`docker-compose.yml:269-274`). The `livestate` volume holds "the gate state file, the spill directory, the
  liveness stamp and the held marker" (`:213-215`); `logs` holds `logs/paper/pinned_epoch.json` and
  `registry_diff.jsonl` (`:151`). Neither is mounted into `backup`/`ops`. The timer runs once a day
  (`deploy/systemd/trading-backup.timer:7`, `OnCalendar=*-*-* 03:15:00 UTC`).
- Expected: either these files are in the bundle, or the docs state that a restore loses them and what the
  operator does (re-initialize the REST gate state, accept that an unsent spill is lost, re-pin the epoch);
  and an RPO for the live journal chosen for the money at stake (owner decision).
- Actual: after host loss, restore brings the database as of the last 03:15 UTC run: up to ~24 h of live
  journal rows (approvals, order intents, fills, reservations) are gone; the REST gate state is missing (read
  as "loss of initialized state", fail-closed, `src/ops/rest_gate_state.py:8-10`); the spill (records written
  while the journal was down) is gone. Only the exchange remains the truth.
- Reproduction: compare the `volumes:` of `backup` (`:269-274`) with the volume list (`:295-302`).
- Impact: mainnet: after a restore the journal does not know positions/orders of the last day; the system
  relies on reconcile against Binance to notice (SAFE_MODE is the expected outcome, not verified here). The
  audit trail for that window is lost.
- Why tests miss it: the drill compares the restored DB with the live DB at the same moment; it never models
  a host lost 23 h after the last backup.
- Remediation: document the RPO and the post-restore procedure (initialize gate state, reconcile before
  `/enable_entries`); once live, a more frequent DB dump or WAL archiving; include the livestate spill.

### G-1203 "One live process" (D098) is not enforced: no instance lease; the soak wrapper can start a second live with the same keys
- ID: G-1203 · Severity: LOW (now) / MEDIUM (mainnet) · Confidence: PROBABLE · Classification: GAP
- Category: deploy/safety · Component: src/live/runtime.py, docker-compose.yml, deploy/compose-soak.sh, deploy/update.sh
- File: `docker-compose.yml` · Lines: 225-238 (also `deploy/compose-soak.sh:1-40`, `deploy/lib.sh:106-120`, `deploy/update.sh:105-128`)
- Rule: D098 ("the live execution path is ONE process"); AGENTS.md invariant "no new entry opens while any position is unprotected"
- Known-prior: none (the paper runtime has an instance lease, exit code 8 `INSTANCE_LEASE_HELD`,
  `src/paper/runtime.py:144-146,379`; nothing equivalent exists for live)
- Evidence: `grep -n -i "lease\|lock\|instance" src/live/runtime.py src/live/startup.py` finds no lease or
  advisory lock; `grep -rn advisory src` finds none. The live service reads `${TRADING_LIVE_ENV_FILE:-.env.live}`
  relative to the project directory (`docker-compose.yml:227-229`), and `deploy/lib.sh:112` says "The live
  service is deliberately not defaulted: it reads .env.live only". `deploy/compose-soak.sh` refuses only
  `down -v` and foreign project names; it has no rule about `--profile live` (`grep live deploy/compose-soak.sh`
  is empty). So `deploy/compose-soak.sh --profile live up -d live` starts a second live process in project
  `trading-soak` with the production `.env.live` keys, its own database (`trading-soak_pgdata`) and its own
  REST gate state volume. `deploy/update.sh` checks only the current project's `live` service. A restore or a
  cutover to a new host (`deploy/migrate.sh` stops only the old collector) can likewise leave two hosts able to
  run live. RUNBOOK has no rule against it.
- Expected: a second live start for the same account refuses (DB or exchange-side lease, or at least a wrapper
  refusal plus a runbook rule), as the paper runtime does.
- Actual: nothing refuses; two processes would each run protection, reconcile, Telegram polling and REST
  weight accounting for one account, each blind to the other's journal (separate DBs in the soak case).
- Reproduction: read the files above; not executed (no Docker run in this audit).
- Impact: now LOW (placement disabled, Demo). Mainnet: two protection coordinators/reconcilers on one account;
  each sees the other's orders as foreign. A likely outcome is SAFE_MODE in both (fail-closed), but a duplicate
  stop, a cancel of the other's stop, or doubled REST weight (ban risk; the gate state is per volume) are
  possible. The reconcile effect is for lane reconcile_safemode to judge.
- Why tests miss it: tests check closed per-service env lists and the soak `down -v` refusal, never a second
  live instance.
- Remediation: a PostgreSQL advisory lock or lease row at start (refuse/hold otherwise; a DB lease does not
  cover the separate-DB soak case, so also a `compose-soak.sh` refusal of the `live` profile) and a RUNBOOK rule
  for restore/cutover.

### G-1205 Redaction shape layer is narrow; masking depends on the value layer
- ID: G-1205 · Severity: LOW (now) / LOW (mainnet) · Confidence: CONFIRMED · Classification: IMPROVEMENT
- Category: security/secrets · Component: src/ops/redaction.py
- File: `src/ops/redaction.py` · Lines: 89-117, 78-80, 130-133
- Rule: D-09 / F-708 (secret redaction)
- Known-prior: F-708 (continuation; F-708 itself is closed by the value layer)
- Evidence (probe `tmp/ops_deploy_security/probe_redaction.out`): with no env value registered these pass
  unmasked: a bare 64-char API key (`Invalid API-key <key>`), `?apiKey=<key>`, a Telegram token whose secret
  part is not exactly 35 chars (`\d{8,10}:[A-Za-z0-9_-]{35}`, `:100`), libpq `password=` kv text (only the
  `?password=` query form is a shape, `:96`), a healthchecks-style ping URL, an S3 key id not starting with
  AKIA/ASIA, `secret_access_key = ...` kv text. Even with the value registered: the signature in a dict repr
  (`'signature': '<hex>'`) and a base64 (Ed25519) `signature=` are not masked (the shape is
  `signature=[0-9a-f]{64}` only, `:102`); upper-cased or truncated secrets and an HTTP Basic header are not
  masked; values shorter than 8 characters are never collected (`:80`).
- Expected: shapes cover the credential forms the project handles, independent of env naming.
- Actual: protection rests on the value layer (env names containing PASSWORD/SECRET/TOKEN/API_KEY/ACCESS_KEY/
  CRYPT/PRIVATE, plus `register_runtime_secret`). That layer is present on every main path checked (Verified Safe
  Areas), so no live leak was found; a key loaded under a neutral name without registration, or a process that
  never calls `configure_logging`, would leak.
- Reproduction: run `probe_redaction.py` (fake values only).
- Impact: defence-in-depth gap; a request signature is single-use (timestamped), so the dict-repr case is low value.
- Why tests miss it: tests assert the shapes that exist, not the forms above.
- Remediation: shapes for `password=` kv, `apiKey=`, an alnum run after `API-key`, base64 `signature=`,
  `"signature": "..."`; keep the value layer primary.

### G-1206 Mode 0600 is checked for `.env` only, not for `.env.live` / `.env.backup` / `.env.paper`
- ID: G-1206 · Severity: LOW (now) / LOW (mainnet) · Confidence: CONFIRMED · Classification: GAP
- Category: security/secrets · Component: deploy/bootstrap.sh, docker-compose.yml
- File: `deploy/bootstrap.sh` · Lines: 547-563
- Rule: AGENTS.md "Secrets live only in `.env` (mode 0600, gitignored)"; RUNBOOK 22 (`.env.live` "mode 0600")
- Known-prior: none
- Evidence: bootstrap installs `.env` with `install -m 0600` and dies if its mode is not 600 (`:559-563`). No
  script creates or checks `.env.live`, `.env.backup` or `.env.paper` (`grep -rn "env.live" deploy/*.sh`:
  comments only); compose reads them with `required: false` and no mode check; `src/live/config.py` reads env
  variables, not the file.
- Expected: the file holding the trade-capable Binance key and the live bot token gets the same check as `.env`
  (the heartbeat script already checks its URL file: `8#$mode & 8#077`).
- Actual: the operator creates `.env.live` by hand from `.env.live.example`; a world-readable copy is accepted.
- Reproduction: read the scripts named above.
- Impact: any local account can read the live API key if the operator forgets `chmod 600`. Docker-group members
  are root-equivalent anyway, so the marginal risk is other local users.
- Why tests miss it: no test covers per-service env file modes.
- Remediation: a mode check at live start (refuse when the env file is group/other readable) or in a wrapper.

### G-1207 Every application container connects as the PostgreSQL superuser
- ID: G-1207 · Severity: INFO (now) / LOW (mainnet) · Confidence: CONFIRMED · Classification: IMPROVEMENT
- Category: security/least-privilege · Component: docker-compose.yml
- File: `docker-compose.yml` · Lines: 59-66, 72-75
- Rule: practice (least privilege); same intent as the D-29 per-service secret split
- Known-prior: none
- Evidence: `DATABASE_URL: postgresql+psycopg://${POSTGRES_USER...}:${POSTGRES_PASSWORD...}@postgres:5432/...`
  (`:66`) goes to collector, paper, live, backup and ops. `POSTGRES_USER` is the role the official postgres
  image creates at init, a superuser.
- Expected: per-service roles (live: DML on its tables; collector: its tables; backup: a read-only dump role).
- Actual: a compromise of any container (e.g. a dependency of the Telegram or Binance client in `live`) gives
  superuser on the database, including `COPY ... TO PROGRAM` and rewriting the journal.
- Reproduction: read the compose file.
- Impact: hygiene; widens the blast radius of any other bug; not exploitable alone.
- Why tests miss it: no test of DB roles.
- Remediation: Alembic-created roles per service; the superuser only for `db-upgrade`.

(G-1204 not used.)

Also added to Verified Safe Areas in this pass: evidence files are scrubbed with the process redactor and
re-scanned before they are kept (`src/ops/operator_evidence.py` header); restore refuses manifest keys that
escape the bundle (`src/ops/backup.py:653-657`, `:409`) and never overwrites an existing Parquet file
(`_copy_into_target`); the freeze-witness credential reaches curl only through `--config -` and the script
refuses xtrace (`deploy/freeze-witness.sh:50-51,313-317,504`); spill directory created 0700
(`src/ops/spill.py:196`); no API key, Telegram token or ping URL value is committed anywhere in the tracked tree
(regex scan), and the committed Demo account fixtures hold balances only.

## Owner decisions

1. **RPO of the live journal (G-1202).** Today: one dump a day at 03:15 UTC. Example: a host dies at 02:00 UTC
   after a day with 3 approvals, 3 entries and their stops; the restored DB knows none of them, and the system
   must rediscover 3 positions from Binance (expected SAFE_MODE until the operator reconciles by hand). Options:
   keep daily (simplest, relies on reconcile), hourly dumps (24x storage/requests, minutes of work), or WAL
   archiving (near-zero loss, more ops). Not picked here.
2. **How a failed backup reaches you (G-1201).** Options: Telegram alert from the backup job, a fourth external
   heartbeat check pinged only on success (the monitor alerts when it goes silent for, e.g., 26 h), or both.
3. **Backup credential power.** The nightly job's S3 key can delete snapshots (retention needs it). Protection
   against a stolen key is the bucket versioning/object-lock you enable (RUNBOOK 11 step 4). Decide the
   object-lock retention period (e.g. 35 days covers the 4-week tier) and the noncurrent-version lifecycle (with
   versioning on, purged snapshots still cost storage until a lifecycle rule removes them).
4. **Run the real-S3 gate and a real restore drill before Phase 26** (KNOWN, owner-pending): until then no
   backup has been proven against a real provider.

## Open Questions

- Lane reconcile_safemode / live_composition: what do two live processes on one account do to each other
  (G-1203)? In particular, does either's reconcile or sweep cancel or close orders/positions it did not create?
- Lane core_strategy_risk: `pyproject.toml:83-87` keeps a ruff F841 ignore for `src/risk/portfolio.py` with the
  comment "warning_threshold_quote and stop_threshold_quote are assigned in check_portfolio and never read
  afterwards ... Surfaced to the user as a possible latent daily-loss gating gap (D-18)". Not checked here;
  no other lane file mentions it.
- Lane operator_golive_gap: after `deploy/update.sh` the live service stays stopped (required) and must be
  restarted by hand; after `deploy/restore.sh` the live service is not started either. Does the runbook say
  to reconcile and read `/status` before `/enable_entries` in both cases?
- Not verifiable offline: whether GitHub branch protection makes the `ci`, `registry-gate` and `research-gate`
  checks required on `master`, and whether the last runs on master were green.
- `update.sh --ref <branch>` checks out the LOCAL branch after `git fetch` (not `origin/<branch>`); RUNBOOK says
  to use a tag or commit, so this is noted, not a finding.

## DONE
