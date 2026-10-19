---
last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
last_mapped_at: 2026-10-19
---
# External Integrations

**Analysis Date:** 2026-10-19

> **Scope note (verified 2026-10-19):** every integration below was confirmed by reading the
> adapter source, not from a plan. Where an integration is *planned but not built*, it is
> marked explicitly as NOT BUILT.

## APIs & External Services

**Exchange — Binance USDⓈ-M Futures (REST):**
- Official connector `binance-sdk-derivatives-trading-usds-futures` 17.4.0 (with
  `binance-common` 4.4.0). Used behind project-owned interfaces; SDK models never leak into
  the domain.
  - Public market data — `src/adapters/binance_public.py` (`BinancePublicMarketData`):
    `klines` → `rest_api.kline_candlestick_data`; `mark_klines` →
    `rest_api.mark_price_kline_candlestick_data`; `mark_price` → `rest_api.mark_price`;
    `open_interest` → `rest_api.open_interest`; `open_interest_statistics` →
    `rest_api.open_interest_statistics`; `funding_rate` → `rest_api.get_funding_rate_history`;
    `server_time` → `rest_api.check_server_time`; `exchange_info` →
    `rest_api.exchange_information` (dynamic stepSize / tick / notional filters).
  - Signed / trading surface — `src/adapters/binance_usdm.py` (`BinanceUsdmAdapter`):
    `place_entry`, `place_market_close`, `place_algo_protective` (conditional algo orders),
    `cancel_normal_order`, `cancel_algo_order`, `query_order_by_client`,
    `query_algo_order_by_client`, `snapshot_open_normal_orders`,
    `snapshot_open_algo_orders`, `snapshot_positions` (`position_information_v3`),
    `get_position_mode` (`get_current_position_mode`), `user_commission_rate`.
  - Diagnostic probe — `src/adapters/binance_probe.py` (`BinanceProbeAdapter`) wraps the same
    signed calls and returns data, never raising on exchange errors.
  - Credential loading — `src/adapters/binance_client.py`. Demo and live credential
    *variable names* are separate by design (OPS-06): `BINANCE_DEMO_API_KEY` /
    `BINANCE_DEMO_API_SECRET` vs `BINANCE_LIVE_API_KEY` / `BINANCE_LIVE_API_SECRET`.
    Each value may come from `<NAME>` or from `<NAME>_FILE` (an absolute path outside the
    repo); setting both is ambiguous and raises.
  - **Rate limiting:** `src/adapters/binance_ratelimit_gate.py` — a process-wide
    `RestRateLimitGate` that refuses every public and signed call during an HTTP 418 IP ban
    or a 429 pause. The shared gate instance is a hard requirement of the adapter
    composition (`binance_usdm.py:634-646`).
  - **Clock drift:** `src/adapters/binance_clock.py` — a `ClockDriftGuard` that blocks new
    entries when local time drifts from Binance server time.

**Exchange — Binance WebSocket Streams (market data):**
- `src/adapters/paper_ws.py` — wraps
  `DerivativesTradingUsdsFuturesWebSocketStreams` against
  `DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL` (`paper_ws.py:36`).
  - Stream name: `{symbol.lower()}@kline_{interval}` (`paper_ws.py:222-223`).
  - Payload normalisation into project types: `_normalize_kline_payload` (`paper_ws.py:91`).
  - The adapter detects **stale stream names** the SDK no longer supports and reports them
    (`paper_ws.py:190, 407-450`) instead of silently connecting to a dead stream.
  - The paper runtime has an in-process watchdog: `feed_silence_timeout_seconds` in
    `config/paper/paper-runtime-v2.toml` bounds the no-message window, after which the loop
    enters bounded recovery and then fails closed.

**Exchange — Binance user-data WebSocket (private):**
- `src/adapters/binance_userdata.py` (`UserDataAdapter`) — typed events on a bounded
  `asyncio.Queue`. The raw SDK callback **never raises**: an unrecognised message becomes a
  `StreamAnomaly`, a parser exception becomes a `MALFORMED_PAYLOAD` anomaly, and a full
  queue sets `overflowed` and counts the loss.
- Listen-key lifecycle: `rest_api.start_user_data_stream` / `keepalive_user_data_stream` /
  `close_user_data_stream` (`binance_userdata.py:136-141`).
- `src/adapters/binance_userdata_events.py` — event parsing, including the `ALGO_UPDATE`
  conditional-order rejection path (the legacy `CONDITIONAL_ORDER_TRIGGER_REJECT` event is
  gone; rejection reasons now arrive inside `ALGO_UPDATE.o.rm`).
- `src/adapters/binance_userdata_router.py` — routes parsed events to consumers.
- `src/adapters/binance_userdata_supervisor.py` — drives `start` / `keepalive` / `rekey` /
  `rebuild` / `stop`; rebuild proves the stored key with a keepalive first, and replaces an
  `INVALID_LISTEN_KEY` with a new key (fail closed on any other listen-key error).
- The listen key is an account-level credential: it is registered with the process redactor
  and never logged (`src/ops/redaction.py:73-76`).

**Telegram Bot API (notifications + APPROVE/SKIP loop):**
- `python-telegram-bot` 22.8 — **installed and imported from `src/`**.
  - Send side: `src/adapters/telegram_notify.py` — PTB-free by design. It defines a
    structural `TelegramBot` Protocol (`send_message`) and the renderers
    `format_simulate`, `format_approve`, `build_simulate_keyboard`,
    `build_approve_keyboard`, `build_skip_keyboard`. The paper core never imports PTB
    (`src/paper/notify.py`).
  - Callback side: `src/adapters/telegram_callbacks.py` — the **only** importer of
    `python-telegram-bot` for inbound callbacks. `on_callback` and `build_application` are the
    PTB-bound surfaces; `parse_callback_data`, `authorized_chat_gate` and
    `dispatch_callback` are pure stdlib+domain functions.
  - Wire format: callback prefixes `APR:`, `SKP:`, `SIM:`, `SKIP:`, `CNF:`, `CXL:` plus a
    32-hex short id, within Telegram's **64-byte** `callback_data` ceiling
    (`TELEGRAM_CALLBACK_DATA_MAX_BYTES`, `telegram_notify.py:139`).
  - Security ordering: the authorized-chat check runs **before** any state lookup; the
    journal receipt (`CALLBACK_RECEIVED`) is written **before** `resolve_callback` runs.
  - Runtime wiring: `src/paper/shadow_runtime.py:1239` calls
    `application.updater.start_polling(...)` — Telegram `getUpdates` long-polling. No
    Telegram webhook is configured (getUpdates and a webhook are mutually exclusive).
- Health probe: `src/ops/health.py:501-526` — `telegram_delivery` is one of ten canonical
  checks.

**TradingView (optional research cross-check):**
- **NOT BUILT.** There is no TradingView adapter, no HTTP endpoint and no FastAPI app
  anywhere in `src/`. `docs/integration/TRADINGVIEW.md:39` states: *"V1 has no webhook
  endpoint (INTG-02 is a v2 requirement)."*
- The documented compensating controls for a future adapter (no request signing is possible):
  an unguessable secret path segment in the URL, a source-IP allow-list of TradingView's
  published webhook addresses, acknowledging each request within 3 seconds, idempotent
  de-duplication, and payload normalisation before it reaches any strategy component.
- `FastAPI` and `uvicorn` are **not in `uv.lock`** (verified 2026-10-19) — the edge does not
  exist.

**External heartbeat monitor (uptime):**
- `deploy/heartbeat.sh` probes the collector (or the paper runtime with `--target paper`) and
  then sends exactly one success ping to an operator-supplied external monitor URL.
- The ping URL is a **secret**: it is read only from a root-only file (mode 0600) and never
  echoed. The URL is provider-agnostic (any healthchecks.io-style endpoint).
- With `--fail-ping` (or `HEARTBEAT_FAIL_PING=1`) a failed probe sends one fail ping.
  A failed probe sends **no success ping**, so the monitor goes quiet and alerts on its own
  period and grace.
- Timer: `deploy/systemd/trading-heartbeat.timer`. It has **no catch-up and no randomised
  delay on purpose** — a ping sent after downtime would hide the very outage the monitor
  exists to report.

**GitHub Actions (CI/CD):**
- Four workflows in `.github/workflows/` (see the CI table in `STACK.md`). All actions are
  commit-SHA pinned; the runner is `ubuntu-24.04`; uv is pinned to `0.12.21`.
- The `test` job runs a digest-pinned `postgres:17.11-bookworm` service container with a
  CI-only throwaway password literal.

## Data Storage

**Databases:**
- PostgreSQL 17.11-bookworm (digest-pinned, `docker-compose.yml:41`) — operational state:
  signals, plans, approvals, orders, fills, positions, journal, watermarks, gaps.
  - Connection: `DATABASE_URL` (async, `postgresql+psycopg://`); `DATABASE_URL_SYNC` is the
    optional sync override for `pg_dump`/`pg_restore` and the collector
    (`src/ops/backup.py:938`, `src/data/collector.py:824`).
  - Client: SQLAlchemy 2.0.54 + psycopg 3.3.6. `src/persistence/engine.py:50-58` refuses any
    non-`postgresql+psycopg` URL.
  - Session discipline: `TimeZone=UTC` is pinned at the libpq level and asserted
    (`assert_session_utc`, `src/persistence/engine.py:62`); every wait is bounded
    (`connect_timeout` 3 s, `lock_timeout` 5000 ms, `statement_timeout` 10 s,
    `pool_timeout` 5 s, TCP keepalives, `tcp_user_timeout` 15 s).
  - Fail closed: an unreachable database raises `StoreUnavailable` — there is **no in-memory
    fallback**.
  - Published on `127.0.0.1:${POSTGRES_PORT}` only; Docker bypasses ufw, so the bind address
    is the control. Remote access is via an SSH tunnel only.
  - Migrations: Alembic, `src/db/alembic/versions/0001_baseline.py` … `0005_live_sized_risk.py`.
    **`alembic upgrade head` only — `create_all` is never used in any code path.**

**File Storage (research data):**
- Parquet on the local filesystem, written atomically by `src/data/store.py`
  (`atomic_write_parquet` → temp file → `replace_with_retry` → `part.parquet`).
  - Layout: `data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet`
    (`src/data/store.py:5, 144-151`); mark-price klines live under
    `data/raw/dataset=mark_klines/...` so the trade-view glob does not match them.
  - The raw store is immutable once published; a published dataset file is never mutated.
- Local filesystem only for datasets — no object store is used for market data.

**Caching:**
- None. No Redis, no memcached. In-process state (bounded `asyncio.Queue` in the user-data
  adapter, the shared `RestRateLimitGate`) plus PostgreSQL columns with TTL semantics
  (listen keys, approval expiry). The `RestRateLimitGate` is the only cross-cutting
  process-wide singleton.

**Off-host backup (encrypted, provider-neutral):**
- `src/ops/backup_remote.py` — rclone only. An `s3` remote (any S3-compatible store: AWS,
  Wasabi, Backblaze B2 via its S3 endpoint) with an rclone `crypt` remote layered on top, so
  the provider sees ciphertext only.
  - Remote names: `BACKUPS3` (S3) and `BACKUPS3CRYPT` (crypt).
  - Env mapping: `BACKUP_S3_*` / `BACKUP_CRYPT_*` → `RCLONE_CONFIG_*`. No credential ever
    appears in argv — the mapped values live only in the child process environment.
  - Layout: `_sentinel/sentinel.txt`, `snapshots/<YYYYMMDDTHHMMSSZ>/{pg.dump,manifest.json}`,
    `parquet/<root basename>/...` (append-only, `--immutable`).
  - Safety: a wrong crypt key looks like an empty bucket, so every push/pull/retention run
    first decrypts and compares the sentinel; exit code 3, an empty listing or a content
    mismatch is an **error**, never "no backups yet".
  - `BACKUP_CRYPT_PASSWORD` / `BACKUP_CRYPT_PASSWORD2` must be `rclone obscure` output, not
    the raw passphrase. The raw passphrase is kept off the VPS.
  - Provider: `BACKUP_S3_PROVIDER` ∈ {`aws`, `wasabi`, `other`}; only `other` requires
    `BACKUP_S3_ENDPOINT`.
  - The rclone binary is pinned in the `ops` Docker target: `rclone/rclone:1.75.1@sha256:...`
    (`Dockerfile:15`).
  - `pg_dump` / `pg_restore` come from `postgresql-client-17` (PGDG repo) in the `ops`
    target; the client floats within major 17 because PGDG removes superseded minors from
    its live repository (the one conscious exception to the exact-pin rule).

**Off-host evidence export (separate chain from backups):**
- `src/ops/evidence_remote.py` — plain S3 remote `EVIDENCES3`, **no crypt layer**, own bucket
  credential. The exporter refuses to start when the evidence credential equals the backup
  credential. Env names in `deploy/evidence.env.example`:
  `EVIDENCE_S3_PROVIDER`, `EVIDENCE_S3_ENDPOINT`, `EVIDENCE_S3_REGION`, `EVIDENCE_S3_BUCKET`,
  `EVIDENCE_S3_PREFIX`, `EVIDENCE_S3_ACCESS_KEY_ID`, `EVIDENCE_S3_SECRET_ACCESS_KEY`.

## Authentication & Identity

**Exchange auth:**
- HMAC-SHA256 signed REST requests, handled by the official SDK. The signed-call policy
  carries `recv_window` for every signed call; a `SignedCallPolicyMissing` is raised when a
  signed call is attempted without a policy and gate
  (`src/adapters/binance_usdm.py:671-677`).
- Two isolated credential pairs (OPS-06): `BINANCE_DEMO_API_KEY`/`BINANCE_DEMO_API_SECRET`
  and `BINANCE_LIVE_API_KEY`/`BINANCE_LIVE_API_SECRET`. The paper runtime refuses to start
  when **any** `BINANCE_`-prefixed variable is present in its environment, even with an
  empty value (exit code 3, `src/paper/runtime_config.py:112-118`).
- `ApiCredentials` masks both values in `repr`/`str` (`src/adapters/binance_client.py:250-260`).
  The live credential is a no-withdrawal key, IP-allow-listed to the VPS public IP (OPS-02).

**Telegram auth:**
- Bot token in `TELEGRAM_BOT_TOKEN`; the authorized chat id in `TELEGRAM_AUTHORIZED_CHAT_ID`
  (an integer; may be negative for groups). The chat-id allow-list is the only
  authentication for the approval loop — there is no user-id authorization yet (Phase 23).
- The raw token never crosses the adapter boundary into the journal payload; only short id +
  chat context is recorded.

**Approval identity:**
- `src/approval/tokens.py`, `src/approval/mapping.py`, `src/approval/replay.py` — expiring,
  idempotent approval tokens with a 32-hex short-id mapping. At-least-once Telegram callback
  delivery replays to the existing state rather than creating a second one.

**No auth provider:** there is no OAuth/OIDC/JWT issuer, no user table and no session
management. The system has exactly one human operator, identified by a Telegram chat id.

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Datadog/OTel). Errors are classified in-house:
  `src/domain/exchange_errors.py` + `src/adapters/binance_errors.py` produce `ErrorFacts`
  (HTTP class, Binance integer code, `Retry-After`) and a category
  (`src/adapters/binance_usdm.py:661-669`).
- `src/ops/health.py` — ten canonical health checks with a three-value vocabulary
  (`PASS` / `FAIL` / `DEGRADED`): `market_feed_freshness`, `last_closed_candle_time`,
  `ws_connection_state`, `user_data_stream_state`, `rest_error_rate`,
  `reconciliation_drift`, `db_writes`, `telegram_delivery`, `unprotected_positions`,
  `orphaned_orders`.
- `src/ops/drills.py` — the operational drill suite (backup/restore drill, cutover).

**Logs:**
- structlog 26.1.0 for structured JSON logs across the adapters, paper runtime, collector
  and ops layer.
- `src/ops/redaction.py` — the redaction processor. It masks values whose **environment
  variable name** contains `PASSWORD`, `SECRET`, `TOKEN`, `API_KEY`, `ACCESS_KEY`, `CRYPT`
  or `PRIVATE` (values shorter than 8 chars are ignored), and whose **log key** contains
  `password`, `secret`, `token`, `api_key`, `apikey`, `authorization`, `signature`,
  `listenkey`, `listen_key`. Shape rules additionally redact PEM private-key blocks, URL
  userinfo and query-string passwords, Telegram bot tokens, Binance `signature=` query
  parameters, `X-MBX-APIKEY` header values and AWS-style access key ids.
- Compose log driver: `json-file`, `max-size: 10m`, `max-file: 5`
  (`docker-compose.yml:24-28`). Application logs also land on the `logs` named volume
  (`logs/paper/pinned_epoch.json`, `logs/paper/registry_diff.jsonl`).

**Audit trail:**
- PostgreSQL journal rows (`src/domain/journal.py`, `src/persistence/journal.py`) — the
  decision lineage: snapshot → signal → plan → approval → order. The `CALLBACK_RECEIVED`
  receipt is written before any state transition.

## CI/CD & Deployment

**Hosting:**
- A single VPS under Docker Compose, project name fixed to `trading`. Compose services:
  `postgres` (always), `db-upgrade` (one-shot migration, owns the image build), `collector`
  (always), `paper` (profile `paper`), `paper-pin` (profile `paper-pin`), `live` (profile
  `live` — a placeholder that raises `SystemExit`, Phase 24), `backup` (profile `ops`),
  `ops` (profile `ops`).
- Named volumes only (`pgdata`, `rawdata`, `backupdata`, `logs`); **no host bind mounts**.
  The `backup` service mounts `rawdata` **read-only** so a backup can never modify the raw
  store.
- Container hardening: `tini` as PID 1 (`init: true`), `stop_grace_period: 30s`, a fixed
  numeric UID 10001 (`appuser`), never root at runtime, and the volume mount points are
  created and owned in the image before first use.
- Health probes: the image `HEALTHCHECK` runs the collector's `--healthcheck`; `paper` and
  `collector` define their own per-service probes; `db-upgrade`, `paper-pin`, `live`,
  `backup` and `ops` disable the image probe.
- `restart: unless-stopped` for `collector` and `paper` (the owner's decision 16-DEC-RESTART-POLICY);
  `restart: "no"` for the one-shot services. The paper runtime's `--hold-on-refusal` makes
  refusals and SKIPPED states hold rather than exit, because `unless-stopped` restarts every
  exit that no stop preceded.
- Compose projects: `trading` (development), `trading-soak` (`deploy/compose-soak.sh`),
  `trading-rehearsal` (`deploy/compose-rehearsal.sh`). The soak project never runs the
  volume-removal form of `down`.

**CI Pipeline:**
- GitHub Actions, four workflows (table in `STACK.md`). No registry login, image push or
  deploy step in CI — the VPS builds its own image from a committed tree
  (`deploy/soak-image.sh` refuses a dirty working tree).

## Environment Configuration

**Required env vars (names only — values never appear in a transcript):**

| Variable | Read by | Purpose |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_HOST` / `POSTGRES_PORT` | `docker-compose.yml:44-47`, `alembic` | PostgreSQL 17 connection |
| `DATABASE_URL` | `src/db/alembic/env.py:29`, `src/analytics/cli.py:719` | Async engine URL (`postgresql+psycopg://`) |
| `DATABASE_URL_SYNC` | `src/ops/backup.py:938`, `src/data/collector.py:824` | Optional sync URL for `pg_dump`/`pg_restore` and the collector |
| `TEST_DATABASE_URL` | `tests/pg_support.py` | **Process environment only** — `tests/pg_support.py` does not load `.env`. Must name a throwaway DB ending in `_test`; the role needs CREATEDB. Unset ⇒ the ~26 `tests/*_pg.py` files silently skip. |
| `OI_POLL_INTERVAL_SECONDS` | collector | OI poll cadence (default 300 s, D-07) |
| `OFF_HOST_BACKUP_TARGET` | backup | Canonical default `data/backup` — matches `DEFAULT_BUNDLE_ROOT` in `src/ops/backup.py`, the compose `backupdata` mount, and `scripts/backup-drill.ps1` |
| `IMAGE_TAG` | `docker-compose.yml:17` | Tag of the image the stack runs |
| `TRADING_ENV_FILE` | `docker-compose.yml:18` | Selects the env file (default `.env`) |
| `TRADING_CI_STRICT` | `tests/infra_helpers.py::infra_skip` | `1` turns every "missing infrastructure" skip into a failure |
| `TELEGRAM_BOT_TOKEN` | `src/paper/runtime.py:501`, `src/adapters/telegram_callbacks.py:950` | BotFather-issued token |
| `TELEGRAM_AUTHORIZED_CHAT_ID` | `src/paper/runtime.py:502` | Integer allow-listed chat id |
| `PAPER_DATABASE_URL` | alembic + SQLAlchemy session | Soak/paper journal database URL |
| `PAPER_RUNTIME_CONFIG` / `PAPER_STRATEGY_ID` / `PAPER_PARAMETER_SET_ID` | `src/paper/runtime_config.py:81-83` | Ratified runtime config path and admission identity |
| `BINANCE_DEMO_API_KEY` / `BINANCE_DEMO_API_SECRET` | `src/adapters/binance_client.py:268-269` | Demo credential pair |
| `BINANCE_LIVE_API_KEY` / `BINANCE_LIVE_API_SECRET` | `src/adapters/binance_client.py:272-273` | Live credential pair (commented out in `.env.example` until Phase 24) |
| `BACKUP_S3_PROVIDER` / `BACKUP_S3_ENDPOINT` / `BACKUP_S3_REGION` / `BACKUP_S3_BUCKET` / `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY` | `src/ops/backup_remote.py:69-76` | Off-host S3 target |
| `BACKUP_CRYPT_PASSWORD` / `BACKUP_CRYPT_PASSWORD2` | `src/ops/backup_remote.py:77` | `rclone obscure` output, not the raw passphrase |
| `EVIDENCE_S3_*` (7 names) | `src/ops/evidence_remote.py:33-39` | Evidence-export bucket (separate credential from backup) |
| `PG_DUMP_BIN` / `PG_RESTORE_BIN` | `src/ops/backup.py:871,892` | Override the pg client binary path |
| `HEARTBEAT_FAIL_PING` | `deploy/heartbeat.sh` | Send a fail ping on probe failure |
| `HEARTBEAT_URL` (file, mode 0600) | `deploy/heartbeat.sh --set-url` | External monitor ping URL — read from a root-only file, never echoed |

**Secrets location:**
- `.env` (mode 0600, gitignored) and `secrets.env` **both exist in the working tree**. Their
  contents are never read into a transcript, a log or an image layer.
- `deploy/bootstrap.sh` creates the real `.env` on the VPS from an off-host secrets file.
- `.dockerignore` excludes `.env` and every `.env.*` variant **except** `.env.example`, so
  secrets can never reach an image layer.
- The soak and evidence env templates (`deploy/soak.env.example`,
  `deploy/evidence.env.example`) live **outside** the checkout on the host, mode 0600.
- `src/ops/redaction.py` scrubs secrets from logs; a resolved Compose config is never
  printed.

## Webhooks & Callbacks

**Incoming:**
- **Telegram inline-keyboard callbacks** — the primary inbound action channel. Prefix
  set `APR:` / `SKP:` / `SIM:` / `SKIP:` / `CNF:` / `CXL:` + 32-hex short id, ≤ 64 bytes.
  Handled by `src/adapters/telegram_callbacks.py`; the paper runtime drives it through
  `start_polling` (`src/paper/shadow_runtime.py:1239`).
- **TradingView webhook — NOT BUILT** (see above). No HTTP endpoint exists in the codebase.
- No other inbound endpoint. There is no `/healthz` HTTP route; health is exposed through
  the `docker compose` healthcheck (`python -m src.data.collector --healthcheck`,
  `python -m src.paper.runtime --healthcheck`), not over HTTP.

**Outgoing:**
- **Telegram Bot API `sendMessage`** — SIMULATE/plan notifications and the APPROVE/SKIP
  keyboards (`src/adapters/telegram_notify.py`).
- **Binance user-data events** are *inbound*; the outgoing Binance calls are REST order
  placement, cancellation and queries.
- **External heartbeat ping** — one HTTP GET to the operator-supplied monitor URL
  (`deploy/heartbeat.sh`).
- **rclone push/pull** to the off-host S3 remote (`src/ops/backup_remote.py`).
- **S3 evidence publish** (`src/ops/evidence_remote.py`, `scripts/export_soak_evidence.py`).
- **Registry-diff artifact upload** — `logs/paper/registry_diff.jsonl` is uploaded as a
  GitHub Actions artifact by `.github/workflows/paper_freeze_check.yml`.

## Integration Status Summary

| Integration | Status | Primary file(s) |
|---|---|---|
| Binance USDⓈ-M Futures REST (public) | **Built, in production use** | `src/adapters/binance_public.py`, `src/adapters/binance_usdm.py` |
| Binance WS Streams (klines) | **Built** | `src/adapters/paper_ws.py` |
| Binance user-data WS | **Built** | `src/adapters/binance_userdata.py`, `binance_userdata_events.py`, `binance_userdata_router.py`, `binance_userdata_supervisor.py` |
| Binance signed trading (order/algo placement) | **Built** (live runner is Phase 24) | `src/adapters/binance_usdm.py`, `src/execution/` |
| Telegram Bot API — send | **Built** | `src/adapters/telegram_notify.py` |
| Telegram Bot API — callback loop | **Built** | `src/adapters/telegram_callbacks.py` |
| PostgreSQL 17 | **Built** | `src/db/models.py`, `src/persistence/engine.py`, `src/db/alembic/` |
| Parquet + DuckDB + Polars research store | **Built** | `src/data/store.py`, `src/data/coverage.py` |
| rclone S3 + crypt off-host backup | **Built** | `src/ops/backup_remote.py`, `src/ops/backup.py` |
| Evidence export to S3 | **Built** | `src/ops/evidence_remote.py` |
| External heartbeat monitor | **Built** | `deploy/heartbeat.sh`, `deploy/systemd/trading-heartbeat.timer` |
| **TradingView webhook** | **NOT BUILT** (v2 requirement INTG-02) | `docs/integration/TRADINGVIEW.md` only |
| **HTTP edge (FastAPI/uvicorn)** | **NOT BUILT** — not in `uv.lock` | — |
| **Telegram webhook** (instead of getUpdates) | **NOT USED** — mutually exclusive with polling | `src/paper/shadow_runtime.py:1223-1224` |

---

*Integration audit: 2026-10-19*
