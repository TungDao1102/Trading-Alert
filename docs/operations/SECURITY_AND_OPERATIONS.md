# Security and Operations

## 1. Security baseline

- API key must not have withdrawal permission.
- Secrets must be outside source control.
- Prefer IP allowlisting where practical.
- Secrets live only in a permission-restricted `.env` (file mode 0600, owned by the service user), never in source control, with provider disk encryption on the VPS (D042). Application-level encryption of secrets at rest is not required in V1 (exclusion recorded in DECISIONS, D045).
- Avoid logging API keys/signatures.
- Webhook endpoints must be authenticated. TradingView cannot sign requests, so an HMAC signature is not available; V1 has no webhook endpoint, and if one is built the scheme is a secret URL path segment plus a source-IP allow-list (F-052). See `integration/TRADINGVIEW.md` section 5.
- Separate paper/test credentials from live credentials.
- Phase 13.1 (D050): `.env` is created by `deploy/bootstrap.sh` from an off-host secrets file with umask 077, mode 0600 and the service user as owner, and no value is ever printed (OPS-06). Paper/test and live credentials use separate variable names (`BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_API_SECRET`; `BINANCE_LIVE_API_KEY` and `BINANCE_LIVE_API_SECRET`, commented out until Phase 24), so a paper process can never pick up a live credential by accident.
- Phase 13.1 (D050): host access is key-only (`PasswordAuthentication no`, `PermitRootLogin no`, enforced by a `00-` sshd drop-in that is verified with `sshd -T`), ufw denies incoming traffic except SSH, and PostgreSQL is published only on `127.0.0.1`. ufw does not govern ports published by Docker, so no other port may be published. The Binance key is restricted to the host's IP and has no withdrawal permission (operator checklist printed by bootstrap).

## 2. Live safety

Default state after deployment:

```text
LIVE_ORDERS_DISABLED
```

The operator must explicitly enable live execution.

## 3. Reconnect

All external connections must have:

- heartbeat,
- reconnect,
- backoff,
- state reconciliation.

Binance market WebSocket connections are believed to have a 24-hour lifetime; a planned reconnect must therefore be part of normal operation (F-057). [Binance USDⓈ-M WebSocket market streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice) Verify the 24-hour figure against current Binance docs before implementation.

## 4. Health checks

Monitor:

- market feed freshness,
- last closed candle time,
- WS connection state,
- user-data stream state,
- REST error rate,
- reconciliation drift,
- database writes,
- Telegram delivery,
- unprotected positions,
- orphaned orders.

- Phase 13.1 (D050): every compose service states its own container health check decision (F-705). The collector probes with the venv interpreter (`/app/.venv/bin/python -m src.data.collector --healthcheck`, six-minute start period), PostgreSQL uses `pg_isready`, and one-shot and placeholder services disable the inherited probe explicitly; the paper and live probes arrive with Phases 16 and 24. A failed or silent unit (including the backup timer) is invisible on the host unless the operator registers an off-VPS heartbeat monitor.

## 5. Alerts

High priority:

- position exists without expected protective stop;
- local state disagrees with Binance;
- unknown order event;
- duplicate execution attempt;
- stale market data;
- exchange rejects risk-protective action;
- API authentication failure;
- daily loss WARNING and DAILY_STOP reached (D033).

## 6. Logging

Structured logs should contain:

- correlation ID,
- SignalId,
- OrderId/clientOrderId when present,
- symbol,
- strategy version,
- timestamp UTC,
- event type,
- result.

Never log secret credentials.

- Phase 13.1 (D050): `src/ops/redaction.py` redacts secrets from every output path of the collector and backfill processes (structlog events, standard logging, uncaught exceptions in all threads and explicit stderr prints) and is installed by `configure_logging()` as the first call of each entry point (OPS-02, F-708). It masks the values of environment variables whose name contains PASSWORD, SECRET, TOKEN, API_KEY, ACCESS_KEY, CRYPT or PRIVATE, and known shapes (URL passwords, Telegram bot tokens, `signature=` values, API-key headers, AWS key ids, PEM private keys). Redaction is value-based: a new secret variable must keep a name matching that rule. The `db-upgrade` one-shot (alembic) does not route its logging through the redactor, because alembic resets logging configuration; this is recorded in D050.

## 7. SAFE_MODE

SAFE_MODE blocks new entry orders only, meaning orders that can open or increase a position (D034). When SAFE_MODE is active:

- Protective and reduce-only orders are always allowed, after an authoritative position query;
- existing exchange-side protective orders remain active;
- monitoring, reconciliation and journaling continue;
- a missing or canceled stop-loss is automatically re-placed at the original plan stop-loss, never wider (D034);
- a stop-loss that is rejected or not acknowledged leads to a reduce-only market close, then a HIGH-priority alert (D034);
- a database failure must not block risk-reducing actions (D034);
- nothing depends on the operator reacting within minutes, because the operator works full-time (D034).

Implementation status: the automatic stop re-placement, the reduce-only close and the DB-outage guarantee above are the target behaviour (D034), built in Phase 20 (EXEC-06, OPS-05). Until then the system enters SAFE_MODE and alerts on an unprotected position but does not re-place the stop-loss or close the position itself, so the operator must place the stop-loss or close the position manually.

This supersedes the earlier "no new live order placement" wording and the cancel-only reconciler decision (Phase 08 D-03 / Phase 09 D-02), per D034.

## 8. Restart behavior

On restart:

```text
load config
→ validate time
→ restore strategy cache
→ reconcile Binance orders/positions
→ reconnect streams
→ verify no duplicate signal/order action
→ resume only when consistent
```

## 9. Backup and restore

The PostgreSQL database must have:

- automated backup;
- encrypted copy outside the primary runtime host;
- documented retention;
- periodic restore verification.

The self-collected OI dataset and journal are research assets. Backup loss is treated as a data-loss incident, not merely an infrastructure inconvenience.

See `operations/RUNBOOK.md` for the restore/emergency procedure.

- Phase 13.1 (D050): backups are encrypted client-side with rclone `crypt` and pushed to any S3-compatible store, so the provider sees only ciphertext. A systemd timer runs the backup daily at 03:15 UTC. Retention keeps 7 daily, 4 weekly and 6 monthly snapshots, counted over periods that actually have a snapshot, and runs only after the push is verified with `cryptcheck`; the Parquet copy is append-only. `deploy/backup-drill.sh` restores into a scratch database and compares it with the live one. The crypt passphrase is kept off the VPS (password manager plus an offline copy); losing it makes every backup unrecoverable. Provider object lock or versioning and an off-VPS heartbeat are operator controls. See `operations/RUNBOOK.md` section 11.


## 10. Python runtime operations

- Build from a locked Python dependency set.
- Do not install packages interactively on the production host.
- Record Python runtime version and application git revision in health/diagnostic output.
- Separate research/development dependencies from the minimal live runtime where practical.
- Test dependency upgrades in paper/testnet before live enablement.
- Phase 13.1 (D050): base images are pinned by tag plus index digest, GitHub Actions by commit SHA, and uv and Python by exact version (RUNBOOK section 16); bumps are deliberate reviewed commits, never automatic. The one conscious exception is `postgresql-client-17` in the ops image, which floats within major 17. Dependencies install only from `uv.lock` (`uv sync --frozen`). `.github/workflows/ci.yml` (test, lint, types and docker jobs, `TRADING_CI_STRICT=1`) gates every push and pull request to master.
