# Security and Operations

## 1. Security baseline

- API key must not have withdrawal permission.
- Secrets must be outside source control.
- Prefer IP allowlisting where practical.
- Secrets live only in permission-restricted env files (the shared `.env` and the per-service `.env.live`, `.env.paper` and `.env.backup`, each file mode 0600, owned by the service user), never in source control, with provider disk encryption on the VPS (D042). Application-level encryption of secrets at rest is not required in V1 (exclusion recorded in DECISIONS, D045).
- Avoid logging API keys/signatures.
- Webhook endpoints must be authenticated. TradingView cannot sign requests, so an HMAC signature is not available; V1 has no webhook endpoint, and if one is built the scheme is a secret URL path segment plus a source-IP allow-list (F-052). See `integration/TRADINGVIEW.md` section 5.
- Separate paper/test credentials from live credentials.
- Phase 13.1 (D050): `.env` is created by `deploy/bootstrap.sh` from an off-host secrets file with umask 077, mode 0600 and the service user as owner, and no value is ever printed (OPS-06). Demo and live credentials use separate variable names (`BINANCE_DEMO_API_KEY` and `BINANCE_DEMO_API_SECRET`; `BINANCE_LIVE_API_KEY` and `BINANCE_LIVE_API_SECRET`), so a paper process can never pick up a live credential by accident. Since Phase 24 (plan 24-30, D107 item 1, WR-06 closed) the `BINANCE_*` names, the live Telegram bot names and `LIVE_RUNTIME_MODE` live only in the live service's own env file (`.env.live`, mode 0600, gitignored), so the always-on collector, `db-upgrade` and the paper services never receive a `BINANCE_` name; the live process refuses to start when the SHADOW bot token variable is present or when credentials of both modes are set (`docs/operations/RUNBOOK.md` sections 13.6 and 22.4).
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

### 5.1 OPS-05 matrix (Phase 20)

Phase 20 built the alert contract (`ALERT_EVENTS`: a closed set of events with a severity and a fixed template), a journal-first sink (the alert is journaled before it is queued; a repeat inside `alerts.dedupe_window_ms` is suppressed) and a Telegram sender with a bounded retry of the MESSAGE only (an order is never retried, Q5). The matrix below is `OPS05_MATRIX` in `src/ops/alerts.py`, one row per event, labelled `[DESIGN]`: each producer is a tested mechanism, not a running producer in a deployed process, because no composition root builds the sink, the SAFE_MODE observer or `LivePlacementContext.alert_sink` yet (Phase 24). The alert text is a fixed template; no exception text, URL or secret is copied into a message.

| Alert | Source | Severity | Producer module | What Phase 20 delivers |
|---|---|---|---|---|
| `UNPROTECTED_POSITION` | OPS-05 | CRITICAL | `src/reconcile/classify.py` | Reconcile tick alerts a position without a stop, a TP-only position, an entry without a protective leg |
| `CLOSE_REQUIRED` | OPS-05 | CRITICAL | `src/execution/protection.py` | The coordinator alerts once per plan when the position must be closed |
| `PROTECTIVE_REJECTED` | OPS-05 | CRITICAL | `src/execution/protection.py` | A definitive stop rejection after a fill (B5) alerts with CLOSE_REQUIRED |
| `DIVERGENCE` | OPS-05 | HIGH | `src/reconcile/classify.py` | Reconcile tick alerts a local versus exchange divergence |
| `UNKNOWN_ORDER` | OPS-05 | HIGH | `src/reconcile/classify.py` | Reconcile tick alerts an untracked system order |
| `FOREIGN_ORDER` | OPS-05 | HIGH | `src/reconcile/classify.py` | Reconcile tick alerts a foreign order, for example one placed by hand in the Binance UI |
| `STALE_DATA` | OPS-05 | HIGH | `src/reconcile/loop.py` | Reconcile tick alerts a stale mark price, a silent user-data stream or a halted stream |
| `AUTH_FAILURE` | OPS-05 | HIGH | `src/reconcile/loop.py` | Produced only by the reconcile tick REST reads; the coordinator, the closer and the manager journal the error class and do not alert it |
| `DUPLICATE_EXECUTION_ATTEMPT` | OPS-05 | HIGH | `src/execution/manager.py` | An already consumed approval (stored outcome or lost consume race) alerts through the optional `LivePlacementContext.alert_sink`; nothing is re-sent |
| `DAILY_STOP` | OPS-05 | CRITICAL | `src/execution/daily_stop.py` | Phase 21 producer; cancels resting entries via `expire_pending_entry('daily_stop')` before alerting; not wired until Phase 24 (`emit_daily_state_alert` stays a test trigger) |
| `DAILY_LOSS_WARNING` | OPS-05 | WARNING | `src/execution/daily_stop.py` | Phase 21 producer; alerts without any exchange call; not wired until Phase 24 |
| `ENTRY_STATE_UNKNOWN` | D-24 (entry path) | CRITICAL | `src/execution/manager.py` | SAFE_MODE entry of the entry path alerts through the `on_enter` observer |
| `PROTECTION_HANDOFF_FAILED` | D-24 (entry path) | CRITICAL | `src/execution/manager.py` | SAFE_MODE entry of the entry path alerts through the `on_enter` observer |
| `DB_FAILURE` | D-24 (entry path) | HIGH | `src/execution/manager.py` | SAFE_MODE entry after a store failure alerts through the `on_enter` observer; since Phase 21 `src/execution/daily_stop.py` also alerts it with the reasons `DAY_STATE_MISSING` and `DAY_STATE_UNREADABLE` (a missing or unreadable persisted day state; nothing is cancelled) |

OPS-05 is therefore not complete end to end: the `DAILY_STOP` and daily-loss WARNING producers exist since Phase 21 (D033, `src/execution/daily_stop.py`), and the wiring of every producer into a running process is Phase 24. Other events of the closed set (`TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED`, `EMERGENCY_CLOSE_NOT_SENT`, `MANUAL_CLOSE_ORPHAN_UNVERIFIED`, `SAFE_MODE_ENTERED`) keep their existing producers. Section 7 is not changed by this note.

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
- a stop-loss that was never confirmed ACTIVE and that REST proved absent is placed again under the same client id at the plan stop-loss, never wider, at most once per coordinator step and only until `max_unprotected_ms` (D034 clause (1)); a stop that was confirmed ACTIVE and is later lost is never re-placed, neither automatically nor by an operator action: the exposure is closed by a reduce-only order (D077);
- a stop-loss that is rejected or not acknowledged leads to a reduce-only market close, then a HIGH-priority alert (D034);
- a database failure must not block risk-reducing actions (D034);
- nothing depends on the operator reacting within minutes, because the operator works full-time (D034).

Implementation status (Phase 20): the never-confirmed stop rule, the reduce-only close and the D077 handling of a lost stop, the act-first risk-reducing controls with the local spill (a risk-reducing action does not wait for the journal) and the five EXEC-06 controls are built and tested with fakes and a local PostgreSQL `[DESIGN]`. They are not run by any deployed process yet: the composition is Phase 24, the controls have no command surface and no authentication (the operator id is audit metadata), and no behavior is observed on Binance `[NOT_TESTED]`: assumption A3 (does a closePosition stop leave with its position), probe P6 and the same-id placement of case (1) against the exchange are open. Until the composition exists the operator uses `RUNBOOK.md` section 3: place the stop-loss or close the position manually on the exchange.

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
- Phase 17 (D051): `journal_events`, `system_state_events` and `plan_constraint_snapshots` are append-only audit tables: PostgreSQL triggers refuse UPDATE, DELETE and TRUNCATE, and status columns cannot leave a terminal value. The triggers stop a code bug or a mistaken manual statement, not a hostile operator: the table owner can disable a trigger, and separating the migration/owner role from the application role (so that the running application cannot disable them) is deferred to the go-live readiness gate in Phase 26. The new operational tables (`execution_intents`, `plan_constraint_snapshots`, `system_state_events`) are ordinary tables of the same database, so the daily backup and the restore (`alembic upgrade head`, through migration 0004) carry them with no extra step; they are part of the audit trail that a backup loss would destroy.

## 10. Python runtime operations

- Build from a locked Python dependency set.
- Do not install packages interactively on the production host.
- Record Python runtime version and application git revision in health/diagnostic output.
- Separate research/development dependencies from the minimal live runtime where practical.
- Test dependency upgrades in paper/testnet before live enablement.
- Phase 13.1 (D050): base images are pinned by tag plus index digest, GitHub Actions by commit SHA, and uv and Python by exact version (RUNBOOK section 16); bumps are deliberate reviewed commits, never automatic. The one conscious exception is `postgresql-client-17` in the ops image, which floats within major 17. Dependencies install only from `uv.lock` (`uv sync --frozen`). `.github/workflows/ci.yml` (test, lint, types and docker jobs, `TRADING_CI_STRICT=1`) gates every push and pull request to master.
