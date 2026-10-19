# Trading-Alert — agent operating notes

Deterministic Binance USDⓈ-M Futures research + semi-automated execution system.

Everything above the `<!-- GSD:*-start ... -->` markers is hand-written. GSD regenerates only
the blocks *between* markers, so this section survives every `generate-claude-md` run. To
refresh the generated blocks: `gsd-tools generate-claude-md --output AGENTS.md` — **without**
`--auto` (`--auto` skips every block it detects as hand-edited, so it is a no-op here).

## Commands

```bash
uv sync --frozen --extra dev                              # env setup
uv run pytest -m "not docker"                              # the suite CI runs
uv run pytest -m docker                                    # Docker-dependent suite
uv run pytest tests/test_risk_quantization.py::test_x      # single test
uv run ruff check && uv run ruff format --check
uv run mypy src
uv lock --check
uv run python scripts/verify_decision_alignment.py all    # docs<->code gate
```

Windows helpers: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/test.ps1`
(`clean.ps1`, `migrate.ps1`, `journal-report.ps1` — see `scripts/dev/README.md`).

## Environment gotchas

- **pytest reads `TEST_DATABASE_URL` from the PROCESS ENVIRONMENT only** — `tests/pg_support.py`
  does not load `.env`. Unset ⇒ the 26 `tests/*_pg.py` files silently skip. It must name a
  throwaway database whose name ends in `_test`; the role needs CREATEDB.
- **`TRADING_CI_STRICT=1`** turns every "missing infrastructure" skip into a FAILURE
  (`tests/infra_helpers.py::infra_skip`). Set it locally to see exactly what CI sees.
- Alembic reads `DATABASE_URL` (`src/db/alembic/env.py`). `alembic upgrade head` only —
  `create_all` is never used. Revisions live in `src/db/alembic/versions/`.
- Secrets live only in `.env` (mode 0600, gitignored); `src/ops/redaction.py` redacts them
  from logs. Demo (`BINANCE_DEMO_*`) and live (`BINANCE_LIVE_*`) credential names are separate
  on purpose. Never read `.env` / `secrets.env` into a transcript.

## Where the code lives

| Path | Role |
|---|---|
| `src/core/` | pure deterministic features / strategy / planner — stdlib + `Decimal` only |
| `src/domain/` | entities, enums, canonical serialization, parameter registry |
| `src/risk/` | sizing, cost guards, quantization, portfolio gates |
| `src/backtest/` | project-owned closed-candle simulator — the canonical execution semantics |
| `src/paper/` | paper runtime, freeze, shadow mode, liveness |
| `src/execution/`, `src/approval/`, `src/reconcile/` | human-approved placement, approval tokens + replay, exchange reconciliation |
| `src/adapters/` | Binance + Telegram behind project-owned interfaces |
| `src/persistence/`, `src/db/` | SQLAlchemy stores, Alembic migrations |
| `src/analytics/`, `src/research/` | metrics + kill-gate; experiment registry, manifest, multiplicity |
| `src/ops/` | backup, cutover, drills, health, redaction |
| `params/<family>/` | versioned, hash-locked parameter sets (trend-pullback, breakout-retest, range-mr) |

Entry points: `python -m src.data.collector`, `python -m src.paper.runtime`
(`--healthcheck` / `--pin-epoch` / `--hold-on-refusal`), `python -m src.ops.backup scheduled`,
`src/analytics/cli.py`. Host operations: `deploy/*.sh`.

## Invariants that are machine-enforced

These fail CI, they are not style preferences:

- **Decimal-only** on the domain/registry/risk/backtest/core/analytics path — no `float(...)`
  constructor. Scanned file list + globs: `tests/test_domain_no_float.py`.
- **No wall clock in pure modules.** The forbidden spellings are enumerated in
  `tests/support/ast_guards.py` (`WALL_CLOCK_CALLS`); inject clocks instead.
- **`src/core` stays pure** — no Polars/pandas/NumPy/Pydantic/SDK/network imports.
- **Parameter sets are hash-locked.** Never edit `params/**/*.toml` in place: a behavior change
  ships as a NEW set plus a NEW `strategy_version`. `registry-gate.yml` re-hashes every file
  against the pins in `tests/fixtures/phase4/parameters.json`; an unpinned file fails closed.
- **This file is gated too.** `scripts/decision_alignment/authority.py` (AU-01..AU-05) compares
  `AGENTS.md` against `docs/` and `.planning/`. The `- **Quantization**` bullet and the
  `| FastAPI |` row must stay byte-identical to their sources (`.planning/PROJECT.md` and
  `.planning/research/STACK.md`) or `registry-gate.yml` goes red. Re-run
  `uv run python scripts/verify_decision_alignment.py all` after editing this file.

## Test layout

- Flat `tests/test_*.py` (334 files). The `*_pg.py` suffix means it needs PostgreSQL (26 files).
- `tests/support/` — shared fakes and the AST guards (`ast_guards.py`,
  `fake_binance_exchange.py`, `net_guard.py`, `virtual_time.py`, `userdata_frames.py`, ...).
- `tests/fixtures/phaseN/` — golden fixtures; each carries `DERIVATIONS.md` or
  `REGRESSION_SNAPSHOTS.md` with the hand-derived arithmetic.
- Regenerate fixtures with `scripts/gen_phase6_fixtures.py`, `scripts/gen_phase14_fixtures.py`,
  `scripts/_compute_phase4_fixtures.py` — never hand-type them.
- `tests/conftest.py` provides `frozen_clock` (2026-09-19T00:00:00Z), `live5_symbols`
  (BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT), `golden_exchange_info`, and the phase3/4/5 loaders.
- Two CI marker axes: `-m "not docker"` (the default suite) and `-m docker` (needs a reachable
  daemon). `tests/test_deploy_workflows.py` and friends assert the CI text itself.

## Rules that are not negotiable

- **No AI/LLM in the trading decision path** — direction, entry, SL, TP, size, risk, parameters,
  signal validity. LLMs may assist code, docs, tests and explanations only.
- **Fail closed.** Uncertain data, connection, account or risk ⇒ NO_TRADE and no new order.
  SAFE_MODE blocks entries while monitoring and reconciliation continue.
- **Quantization floors, never rounds up**: floor to stepSize → reject below min quantity →
  reject below min notional → reject below `minimum_risk_utilization_after_rounding` → NO_TRADE
  is preferred over a risk-budget breach. Identical logic in backtest, paper and live.
- **Research before optimisation.** No parameter is chosen or tuned from backtest results, and
  every value carries a provenance label. `docs/research/RESEARCH_PROTOCOL.md` is FROZEN
  (v2.6.0): changing it needs a new `docs/DECISIONS.md` row AND a matching `docs/DOC_STATUS.md`
  index line AND the protocol header version — three witnesses checked by `research-gate.yml`.
- **Missing contract ⇒ TBD, never invent.** If a trading rule is absent from the docs, mark it
  TBD and open a research task; do not invent production behaviour.
- **Doc precedence (D031):** `docs/DECISIONS.md` > canonical `docs/` > `AGENTS.md` > `.planning/`.
  When `.planning/` decides something new, the canonical doc changes in the same change.

## Where to read

- `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/implementation/AGENT_INSTRUCTIONS.md` — the rules.
- `docs/GLOSSARY.md` — canonical enums and terminology. `docs/data/DATA_MODEL.md` — persistence.
- `docs/configuration/CONFIGURATION.md` — parameter registry.
  `docs/testing/TESTING_STRATEGY.md` — golden-fixture test protocol.
- `docs/DECISIONS.md` — decision log. `docs/DOC_STATUS.md` — which document is canonical.
- `docs/operations/RUNBOOK.md` — incident and deployment procedures.
- `.planning/state.json` — current phase. `.planning/WINDOWS.md` — the open defect ledger
  (verification that could not be run on the dev machine).

<!-- GSD:project-start source:PROJECT.md -->

## Project

**Deterministic Binance Futures Research & Semi-Automated Execution System**

A deterministic, reproducible Binance Futures trading research and semi-automated execution system for a full-time worker with $500–1,000 research capital. It detects a small number of well-defined setups on 4H/1H, generates complete trade plans (Entry/SL/TP/risk/quantity) deterministically, notifies via Telegram, and only places orders after explicit human APPROVE — never auto-trading in V1.

**Core Value:** Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.

### Constraints

- **Determinism**: same market snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs
- **No-AI core**: LLM may assist code/docs/tests/explanations only; must never decide direction/entry/SL/TP/size/risk/parameters/signal-validity
- **Exchange authority**: Binance is canonical for orders/fills/positions/PnL/fees/conditional orders; user-data WS preferred realtime; dynamic exchangeInfo (stepSize/tick/notional), Algo-Order endpoints, position-mode detection, 200-conditional-order headroom — all re-verified against current official docs before implementation, never hard-coded from memory
- **Quantization**: floor to stepSize → reject below min quantity → reject below min notional → reject below minimum_risk_utilization_after_rounding (60% baseline) → NO_TRADE preferred over round-up; identical logic backtest/paper/live; canonical statement in docs/trading/RISK_MANAGEMENT.md section 11 (D031)
- **Approval safety**: explicit, auditable, idempotent, expiring; at-least-once Telegram callbacks replay to existing state; no auto-approve on notification failure; stale/invalid plans unapprovable
- **Fail closed**: uncertain data/connection/account/risk → NO_TRADE, no new orders; SAFE_MODE blocks entries while monitoring/reconciliation continues
- **Tech stack**: Python 3.13, asyncio, official Binance Python connector (3.10+) behind adapters, FastAPI only for webhook/health edge, PostgreSQL (operational) + Parquet/DuckDB (research), Polars/pandas/NumPy/SciPy, VectorBT exploratory-only, pytest+Ruff+mypy, Docker, Decimal/tick arithmetic for exchange-sensitive values
- **Timeline**: one part-time developer (evenings/weekends); Phase 0A 4–8 wks, 0B 1–2 wks bootstrap + continuous, Phase 1 backtest 6–10 wks, Phase 2 paper 3–6 mo forward observation, Phase 3 live rollout 4–8 wks; overall ~15–24 mo to first cautious live order

<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

- ---
- last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
- last_mapped_at: 2026-10-19
- ---

# Technology Stack

- **Analysis Date:** 2026-10-19
- > **Scope note (verified 2026-10-19):** this document reports the **actual installed state**,
- > not the plan. `pyproject.toml` and `uv.lock` were read directly. Several packages named in
- > older planning documents (`.planning/research/STACK.md`) are **NOT** installed — see
- > "Not Installed (verified absent)" below. `uv.lock` wins for exact versions.

## Languages

- **Primary:**
- Python 3.13.15 — the only implementation language. 209 modules under `src/`, 334+ test files
- under `tests/`. Pinned by `.python-version` (`3.13.15`) and by `requires-python = "==3.13.*"`
- in `pyproject.toml:5`. Target version for Ruff is `py313` (`pyproject.toml:60`), mypy runs
- with `python_version = "3.13"` (`pyproject.toml:88`).
- Bash — host operations only: `deploy/*.sh` (12 scripts) and `deploy/systemd/*.service` /
- `*.timer` (8 unit files). Shellchecked in CI with `shellcheck -x -P SCRIPTDIR deploy/*.sh`
- (`.github/workflows/ci.yml`, `docker` job).
- **Secondary:**
- PowerShell — Windows developer helpers only: `scripts/dev/test.ps1`, `scripts/dev/clean.ps1`,
- `scripts/dev/migrate.ps1`, `scripts/dev/journal-report.ps1`, `scripts/backup-drill.ps1`.
- These are the Linux-script counterparts for the dev machine; they are not deployed.
- TOML — configuration and parameter data: `params/<family>/*.toml` (75 files),
- `config/paper/paper-runtime-v*.toml`, `config/binance/binance-limits-v1.toml`,
- `config/execution/execution-limits-v1.toml`, `alembic.ini` is INI.
- SQL — generated by Alembic into PostgreSQL only; no `.sql` source files are hand-maintained.
- **Not a language surface:** `package.json` is an empty object `{}` with a `package-lock.json`
- present. There is **no JavaScript/Node toolchain** in this project — the npm files are inert
- placeholders. Do not add npm dependencies without a decision record.

## Runtime

- **Environment:**
- CPython 3.13.15, Debian bookworm slim in the container (`python:3.13.15-slim-bookworm`
- digest-pinned at `Dockerfile:17`).
- asyncio single-event-loop model. `pytest-asyncio` runs in `asyncio_mode = "auto"`
- (`pyproject.toml:48`), so async tests carry no decorator.
- **Package Manager:**
- uv 0.12.21 — the canonical tool for env, dependency resolution and task running.
- - Lockfile: `uv.lock` present (version `1`), the reproducibility mechanism.
- - Pinned exactly in CI: `astral-sh/setup-uv` with `version: "0.12.21"`
- (`.github/workflows/ci.yml`); the same version is baked into the image via
- `ghcr.io/astral-sh/uv:0.12.21@sha256:...` (`Dockerfile:12`).
- - `[tool.uv] managed = true` (`pyproject.toml:44-45`) — uv manages the interpreter.
- - `uv sync --frozen --no-dev` is the image install (`Dockerfile:31`).
- - `uv lock --check` is a CI gate (`ci.yml`, `lint` job).
- **Use `uv run` for any command**, never a bare `python` — the image runs the venv
- interpreter explicitly (`/app/.venv/bin/python`) because bare `python` on PATH is the base
- interpreter without the venv packages (`Dockerfile:57-67`).

## Frameworks

- **Core:**
- asyncio (stdlib) — all I/O orchestration: WS market data, user-data stream, Telegram
- polling, DB access. One loop, no threads except `asyncio.to_thread` for the synchronous
- Binance SDK REST calls (`src/adapters/binance_probe.py:624`).
- SQLAlchemy 2.0.54 — the only ORM/Core surface for PostgreSQL. Two engines exist:
- - **async**: `create_async_engine` + `async_sessionmaker` in `src/db/models.py:946,962`
- (used by the Alembic `env.py` and the async session path).
- - **sync**: `create_engine` in `src/persistence/engine.py` (Phase 17 operational stores),
- pinned to `postgresql+psycopg` and UTC session timezone, with bounded waits.
- Pydantic 2.13.5 + pydantic-settings 2.15.0 — boundary validation (exchange payloads,
- webhook/callback bodies, configuration loading).
- **Testing:**
- pytest 9.1.1 with pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`).
- respx 0.23.1 — HTTP-level mocking at the httpx layer.
- Two CI marker axes: `-m "not docker"` (default suite) and `-m docker` (needs a reachable
- Docker daemon). Marker declared in `pyproject.toml:54-56`.
- **Build/Dev:**
- Ruff 0.16.8 — lint **and** format (replaces flake8/black/isort). `line-length = 100`,
- `select = ["E","W","F","I","B","UP"]` (`pyproject.toml:65-73`).
- mypy 2.3.1 — `strict = true` on `src` (`pyproject.toml:87-94`), including
- `warn_unused_ignores`, `warn_return_any`, `disallow_untyped_defs`,
- `ignore_missing_imports = false`.
- Docker + Docker Compose — packaging and the local Phase-0 stack.
- Alembic 1.20.0 — schema migrations. `script_location = src/db/alembic`
- (`alembic.ini:11`); revisions in `src/db/alembic/versions/` (0001–0005).

## Key Dependencies

- **Critical:**
- `binance-sdk-derivatives-trading-usds-futures` 17.4.0 — the official Binance USDⓈ-M
- Futures connector. Covers REST (`/fapi/*`), WS Streams and the WS user-data API.
- `binance-common` 4.4.0 is its transitive base. Imported **only** inside `src/adapters/`
- (`binance_client.py`, `binance_public.py`, `binance_usdm.py`, `binance_userdata.py`,
- `binance_probe.py`, `paper_ws.py`) — the domain core never sees an SDK type.
- `sqlalchemy` 2.0.54 + `psycopg` 3.3.6 (+ `psycopg-binary` 3.3.6, `psycopg-pool` 3.3.2) —
- the only supported PostgreSQL driver. `src/persistence/engine.py:50-58` **refuses** any
- URL that is not `postgresql+psycopg://`.
- `duckdb` 1.5.5 (exact pin, `pyproject.toml:14`) — in-memory analytical SQL over Parquet
- for coverage/QA queries (`src/data/coverage.py`).
- `polars` 1.44.2 — the frame engine for feature/backtest data pipelines
- (`src/data/store.py`, `src/data/quality.py`, `src/data/sufficiency.py`,
- `src/data/minute_source.py`, `src/adapters/analytics_store.py`).
- `pyarrow` 25.0.1 — the Parquet engine under Polars and DuckDB.
- `python-telegram-bot` 22.8 — **installed and imported from `src/`**. The only importer is
- `src/adapters/telegram_callbacks.py` (the callback side); the send side is PTB-free in
- `src/adapters/telegram_notify.py` (it defines a structural `TelegramBot` Protocol).
- `httpx` 0.28.1 — **installed and imported from `src/`** at `src/data/universe_freeze.py:41`,
- `src/data/backfill_cli.py:54`, `src/data/archive.py:29` (dataset ingest/archive fetch).
- `httpcore` 1.0.9 and `certifi` 2026.7.22 are its transitive deps.
- **Infrastructure:**
- `tenacity` 9.1.4 — bounded retries with jitter. Used at `src/paper/shadow.py:54`
- (`AsyncRetrying`, `wait_random_exponential`) and `src/paper/notify.py:49`. The supervisor
- uses `tenacity.stop.stop_base` (`src/adapters/binance_userdata_supervisor.py:55`).
- `structlog` 26.1.0 — structured JSON logging across 20+ modules
- (`src/adapters/*`, `src/paper/*`, `src/ops/redaction.py:48`, `src/ops/backup.py:60`,
- `src/data/collector.py:58`). The redaction processor is a structlog processor
- (`src/ops/redaction.py`).
- `tzdata` 2026.4 — Windows has no OS zoneinfo; the package supplies the IANA database.
- Runtime timezone is `Asia/Ho_Chi_Minh` for presentation, UTC internally.
- `alembic` 1.20.0, `pydantic` 2.13.5, `pydantic-settings` 2.15.0, `typing-extensions` 4.16.0.
- **Transitive runtime stack (from `uv.lock`):** `aiohttp` 3.14.3, `websockets` 15.0.1,
- `websocket-client` 1.9.2, `requests` 2.34.2, `urllib3` 2.8.0, `pycryptodome` 3.23.0,
- `ast-serialize` 0.11.2, `binance-common` 4.4.0, `greenlet` 3.5.6, `idna` 3.20,
- `certifi` 2026.7.22, `mako` 1.4.1, `markupsafe` 3.0.3, `anyio` 4.15.1.
- **Dev-only (the `dev` extra, `pyproject.toml:35-41`):** `pytest` 9.1.1, `pytest-asyncio` 1.4.0,
- `respx` 0.23.1, `ruff` 0.16.8, `mypy` 2.3.1, plus `iniconfig` 2.3.0, `pluggy` 1.6.0,
- `packaging` 26.3, `mypy-extensions` 1.1.0, `pathspec` 1.1.1, `tomli`-free (stdlib `tomllib`
- on 3.13).

### Not Installed (verified absent)

- These are named in the *recommended* stack in `.planning/research/STACK.md` but are **not**
- in `pyproject.toml` and **not** in `uv.lock` (verified by direct lockfile scan on 2026-10-19):

| Package | Status | Consequence |
|---|---|---|
| `fastapi` | NOT IN LOCK | No HTTP edge exists. `src/` contains no FastAPI import. |
| `uvicorn` | NOT IN LOCK | No ASGI server. |
| `pandas` | NOT IN LOCK | Never a dataframe citizen. |
| `numpy` | NOT IN LOCK | No numeric stack; `Decimal` and stdlib `statistics` only. |
| `scipy` | NOT IN LOCK | Significance tests are hand-rolled in `src/analytics/stats.py`. |
| `vectorbt` | NOT IN LOCK | Exploratory sweeps unavailable; the project-owned engine in `src/backtest/` is canonical. |
| `binance-sdk-algo` | NOT IN LOCK | No TWAP/VP execution algos. |

### Canonical edge row

- The AGENTS.md stack block is generated from this file, and the decision-alignment gate
- AU-03 compares the | FastAPI | row below byte-for-byte against
- .planning/research/STACK.md. Both files must carry the same row.

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| FastAPI | >= 0.141, < 0.150 (0.141.1 released 2026-07-29) | TradingView webhooks (secret URL path + source-IP allow-list; TradingView cannot sign requests), Telegram callback receiver (optional), `/healthz` | Edge-only: the strategy engine must not import FastAPI. Pydantic-v2-native request validation gives signature/body checks almost free. Keep the surface minimal: webhook in, health out |
| `pytest-httpx` | NOT IN LOCK | respx is the HTTP mock layer. |
- **Do this instead:** if any of these becomes necessary, add it with `uv add` and commit the
- updated `uv.lock` in the same change. The lockfile is the installed truth.

## Configuration

- **Environment:**
- Secrets live in `.env` (mode 0600, gitignored) on the VPS. A `.env` file and a
- `secrets.env` file **exist in the working tree** — both are gitignored and their contents
- are never read into a transcript.
- `.env.example` is the tracked template (no real values) — the canonical list of variable
- names.
- `deploy/soak.env.example` — the soak-host environment template (names only).
- `deploy/evidence.env.example` — the evidence-export S3 template (names only).
- Compose selects the file with `TRADING_ENV_FILE` (default `.env`) —
- `docker-compose.yml:18`.
- **The paper runtime reads only `ALLOWED_ENV_NAMES`** (`src/paper/runtime_config.py:70-85`)
- and refuses to start if any variable beginning with `BINANCE_` is present
- (`refuse_trade_capable_env`, `src/paper/runtime_config.py:112-118`, exit code 3).
- **Build:**
- `pyproject.toml` — the single manifest of record: `[project.dependencies]`,
- `[project.optional-dependencies.dev]`, `[tool.pytest.ini_options]`, `[tool.ruff]`,
- `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`, `[tool.mypy]`, `[tool.uv]`.
- `uv.lock` — pinned versions; `uv lock --check` in CI.
- `alembic.ini` — script location, UTC timezone, slug template. `sqlalchemy.url` is
- **overridden at runtime** from `$DATABASE_URL` in `src/db/alembic/env.py:29`.
- `Dockerfile` — two targets: `runtime` (collector / paper / live) and `ops` (runtime +
- `postgresql-client-17`, rclone, rsync, openssh-client). Every base image is pinned by
- **exact tag plus index digest**; no `# syntax=` directive is used.
- `docker-compose.yml` — project name fixed to `trading`; services `postgres`, `db-upgrade`,
- `collector`, `paper`, `paper-pin`, `live`, `backup`, `ops`; profiles `paper`, `paper-pin`,
- `live`, `ops`; named volumes `pgdata`, `rawdata`, `backupdata`, `logs`; **no
- `container_name` anywhere**; postgres published on `127.0.0.1` only.
- **Runtime configuration files (image-hashed, frozen decision surface):**
- `config/paper/paper-runtime-v1.toml` / `-v2.toml` — the ratified paper runtime config,
- selected by `PAPER_RUNTIME_CONFIG`. `deploy/soak-image.sh` checks the file loads **inside
- the built image** before recording the build.
- `config/binance/binance-limits-v1.toml` — Binance rate-limit policy.
- `config/execution/execution-limits-v1.toml` — execution limits.
- `params/<family>/*.toml` — 75 hash-locked parameter sets across `trend-pullback`,
- `breakout-retest`, `range-mr`. **Never edit a set in place**; a behaviour change ships as
- a new set plus a new `strategy_version`. `registry-gate.yml` re-hashes every file against
- `tests/fixtures/phase4/parameters.json`; an unpinned file fails closed.

## Platform Requirements

- **Development:**
- Python 3.13.15 + uv 0.12.21.
- Windows is a supported dev platform: `tzdata` supplies the zoneinfo database and
- `scripts/dev/*.ps1` wrap the Linux commands.
- Optional: Docker (for `docker compose` and the `-m docker` suite), `shellcheck`, `bash`
- (Git for Windows — the WSL launcher in `System32\WindowsApps` is ignored),
- a local PostgreSQL 17 for the `*_pg.py` tests.
- `TEST_DATABASE_URL` must be set in the **process environment** (not `.env`) and must name
- a throwaway database ending in `_test`; the role needs CREATEDB. Without it ~26
- `tests/*_pg.py` files silently skip.
- `TRADING_CI_STRICT=1` turns every "missing infrastructure" skip into a failure.
- **Production:**
- A single Ubuntu 22.04/24.04 or Debian 12 VPS, hardened by `deploy/bootstrap.sh`
- (plain apt, ufw, sshd, chrony, Docker Engine — no cloud CLI of any kind).
- Docker Engine + Docker Compose v2; the stack runs under Compose project name `trading`.
- 4 vCPU / 8 GB RAM / 100 GB SSD is the documented baseline for the swing-trading workload.
- systemd for the timers: `trading-backup.timer` (daily 03:15 UTC, `Persistent=true`,
- `RandomizedDelaySec=5m`), `trading-heartbeat.timer` (operator interval, no default),
- plus soak variants `trading-soak-backup.timer` and `trading-soak-paper-heartbeat.timer`.
- PostgreSQL 17.11-bookworm, digest-pinned (`docker-compose.yml:41`).

## Command Reference (the same ones CI runs)

- `uv sync --frozen --extra dev            # env setup`
- `uv run pytest -m "not docker"            # the default suite`
- `uv run pytest -m docker                  # Docker-dependent suite`
- `uv run ruff check                        # lint`
- `uv run ruff format --check               # format check`
- `uv run mypy src                          # types (strict)`
- `uv lock --check                          # lockfile currency`
- `uv run alembic upgrade head              # migrations (never create_all)`
- `uv run python scripts/verify_decision_alignment.py all   # docs<->code gate`
- **Entry points (`python -m ...`):**
- `src.data.collector` — OI/funding/klines collector (`--healthcheck` probe).
- `src.paper.runtime` — paper runtime (`--healthcheck`, `--pin-epoch`, `--hold-on-refusal`).
- `src.ops.backup` — backup/restore/drill CLI (`scheduled`, `push`, `pull`, `--help`).
- `src.paper.freeze` — registry freeze check (`--check --from-allowlist --diff-log ...`).
- `src.data.backfill_cli`, `src.analytics.cli` — research/analytics CLIs.

## CI/CD & Tooling Gates

- Four GitHub Actions workflows in `.github/workflows/`, all on `master`:

| Workflow | File | Purpose |
|---|---|---|
| `ci` | `ci.yml` | 4 jobs: `test` (with a digest-pinned PostgreSQL 17.11 service), `lint` (lock check + ruff lint + ruff format), `types` (mypy src), `docker` (compose config for all profiles, shellcheck, image build, `pytest -m docker`) |
| `registry-gate` | `registry-gate.yml` | Re-hashes every `params/**/*.toml` against the pinned hashes, runs the decision-alignment gate, runs the registry negative tests |
| `research-gate` | `research-gate.yml` | Protocol freeze check (3 witnesses: header, `docs/DOC_STATUS.md` index, `docs/DECISIONS.md` row), experiment identity-tuple check, registry-path tripwire |
| `Paper Freeze Check` | `paper_freeze_check.yml` | Hourly (cron `34 * * * *`) registry immutability tick; uploads `logs/paper/registry_diff.jsonl` as an artifact |
- **Pinning discipline:** every action is pinned to a **commit SHA** with the version in a
- trailing comment (e.g. `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`).
- The runner is `ubuntu-24.04` (exact) and uv is `0.12.21` (exact). `permissions: contents: read`
- on every workflow. `TRADING_CI_STRICT: "1"` is set in CI so a missing prerequisite fails
- rather than skips. `tests/test_deploy_workflows.py` asserts the CI text itself.
- **Deployment:** `deploy/*.sh` — `bootstrap.sh`, `update.sh` (+`--rollback`), `migrate.sh`
- (provider-to-provider cutover), `backup.sh`, `restore.sh`, `backup-drill.sh`, `heartbeat.sh`,
- `compose-soak.sh` (project `trading-soak`), `compose-rehearsal.sh` (project
- `trading-rehearsal`), `soak-image.sh`, `refresh-pins.sh`, `lib.sh`. All are
- `set -Eeuo pipefail` and idempotent with a `--dry-run` mode.

## Architectural Constraints the Stack Enforces

- **Decimal-only** on the domain/registry/risk/backtest/core/analytics path — no `float(...)`
- constructor. Scanned by `tests/test_domain_no_float.py`.
- **No wall clock in pure modules** — the forbidden spellings are enumerated in
- `tests/support/ast_guards.py` (`WALL_CLOCK_CALLS`); inject clocks instead.
- **`src/core` stays pure** — no Polars/pandas/NumPy/Pydantic/SDK/network imports.
- **No AI/LLM in the trading decision path** — direction, entry, SL, TP, size, risk,
- parameters, signal validity. LLMs may assist code, docs, tests and explanations only.
- **Fail closed** — uncertain data, connection, account or risk ⇒ NO_TRADE and no new order.
- SAFE_MODE blocks entries while monitoring and reconciliation continue.
- **No `float` for exchange-sensitive values** — a 1-ulp difference can flip NO_TRADE into an
- order.
- ---
- *Stack analysis: 2026-10-19*

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

- ---
- last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
- last_mapped_at: 2026-10-19
- ---
- <!-- refreshed: 2026-10-19 -->
- **Analysis Date:** 2026-10-19

## Where the rules live

- `pyproject.toml` is the single authoritative source for tool configuration. `docs/DECISIONS.md`
- is the single authoritative source for *why* the rules exist. Nothing in this document may
- contradict either.

| Concern | Authority |
|---|---|
| Ruff / mypy / pytest configuration | `pyproject.toml` |
| Engineering rules | `docs/01_ENGINEERING_PRINCIPLES.md` |
| Agent rules | `docs/implementation/AGENT_INSTRUCTIONS.md` |
| Canonical enums / terminology | `docs/GLOSSARY.md` |
| Persistence contract | `docs/data/DATA_MODEL.md` |
| Parameter registry | `docs/configuration/CONFIGURATION.md` |
| Test protocol | `docs/testing/TESTING_STRATEGY.md` |
| Decision log (D001…D060) | `docs/DECISIONS.md` |
| Which document is canonical | `docs/DOC_STATUS.md` |
| Operating notes + commands | `AGENTS.md` |
- **Source-of-authority precedence (D031):** `docs/DECISIONS.md` > canonical `docs/` >
- `AGENTS.md` > `.planning/`. When `.planning/` decides something new, the canonical doc changes
- in the **same change**.

## Naming Patterns

- **Files:**
- `snake_case.py`, one module per concern, inside a `src/<package>/` directory:
- `src/core/features.py`, `src/risk/quantization.py`, `src/persistence/engine.py`.
- A leading underscore marks a package-private helper module: `src/core/_decimal.py`.
- Alembic revisions are zero-padded and descriptive: `src/db/alembic/versions/0001_baseline.py`,
- `0004_persistence_integrity.py`, `0005_live_sized_risk.py`.
- Parameter sets are `params/<family>/<set-id>.toml` (see below).
- Test modules are `tests/test_*.py`; PostgreSQL-dependent ones end in `_pg.py`.
- **Functions:**
- `snake_case` for public functions; `_leading_underscore` for module-private helpers.
- Public API takes keyword-only arguments: `def quantize(*, sized, constraint_snapshot,
- allowed_risk, ...)` (`src/risk/quantization.py:32`),
- `def make_sync_engine(database_url, *, lock_timeout_ms=..., ...)`
- (`src/persistence/engine.py:97`).
- Test functions are `test_<observable behaviour>`: `test_empty_input_returns_explicit_invalid_reason`,
- `test_verify_on_mutated_copy_raises_parameter_set_mutated`.
- Test helper builders are `_make_*` / `_build_*` / `_seed_*`:
- `_make_candle(...)` (`tests/test_domain_boundary.py:36`),
- `_build_1h_candles(n)` (`tests/test_domain_boundary.py:64`),
- `_seed_candles(...)` (`tests/test_coverage.py:83`).
- **Variables:**
- `snake_case` for locals and parameters.
- Module-level constants are `UPPER_SNAKE_CASE`: `REGISTRY_ROOT`, `SCHEMA_VERSION`
- (`src/domain/registry.py:41-42`), `DEFAULT_LOCK_TIMEOUT_MS` (`src/persistence/engine.py:33`),
- `STATUS_PASS` / `CHECK_MARKET_FEED_FRESHNESS` (`src/ops/health.py:35-57`).
- Private module constants are `_UPPER_SNAKE_CASE`: `_PREC` (`src/core/_decimal.py:19`),
- `_SEGMENT_RE` (`src/domain/registry.py:47`).
- Test-only values are prefixed `TEST_ONLY_` so a scan can prove they never reach production:
- `TEST_ONLY_RECV_WINDOW_MS` (`tests/support/limits.py:38`).
- Test-only value *builders* are named `test_only_*` and carry `__test__ = False` so pytest
- does not collect them (`tests/support/limits.py:119-191`).
- **Types:**
- `PascalCase` for classes, dataclasses, protocols and enums.
- Domain enums are `str, Enum` (not `StrEnum`) — the mixin is the canonical pattern, which is
- why Ruff's `UP042` is globally ignored in `pyproject.toml:74-76`:
- `class SignalStatus(str, Enum)` (`src/domain/enums.py:16`).
- Enum *members* are `UPPER_SNAKE_CASE` and copy `docs/GLOSSARY.md` verbatim — no invented
- names: `DETECTED`, `NOTIFIED`, `VIEWED`, `APPROVED` (`src/domain/enums.py:22-30`).
- Value objects are `@dataclass(frozen=True)`: `Candle` (`src/core/types.py:63`),
- `FeatureOutput` (`src/core/types.py:120`).
- Discriminated results are modelled as a flag + optional payload, never as a bare union:
- `SetupResult(is_no_trade, signal, reason_code, regime)` (`src/core/types.py:230`),
- `PlanResult(is_no_trade, trade_plan, reason_code)` (`src/core/types.py:329`).
- **Constants and vocabularies:**
- Canonical status vocabularies live in one place per domain, as frozen sets:
- `_STATUSES` (`src/ops/health.py:39`), `STRATEGY_KEYS` (`src/domain/registry.py:59`),
- `_SETUP_REASONS` (`src/core/types.py:214`).
- Rejection reasons come from `RejectionReason` in `src/domain/enums.py`; feature-layer
- reason codes are additive `REASON_*` string constants (`src/core/types.py:114-117`).

## Code Style

- **Formatting:**
- Tool: Ruff formatter (`uv run ruff format` / `uv run ruff format --check`).
- `line-length = 100`, `target-version = "py313"`, `src = ["src", "tests"]`
- (`pyproject.toml:58-63`).
- `extend-exclude = [".planning", ".gsd"]` — planning artifacts are prose and their embedded
- Python snippets must not be reformatted (`pyproject.toml:62-63`).
- Formatter-only changes are their own commit (see `docs/DECISIONS.md` D050 item (a)).
- **Linting:**
- Tool: Ruff lint (`uv run ruff check`).
- `select = ["E", "W", "F", "I", "B", "UP"]` — pycodestyle, pyflakes, isort, bugbear, pyupgrade
- (`pyproject.toml:65-73`).
- `ignore = ["UP042"]` — `str, Enum` mixin is canonical per `docs/research/TRADING_STRATEGY_RESEARCH.md`
- §Code Examples (`pyproject.toml:74-76`).
- isort is on: import order is enforced mechanically, not by convention.
- **Per-file Ruff ignores — each one exists for a stated reason:**

| Entry | Why it exists |
|---|---|
| `"tests/*" = ["B011"]` (`pyproject.toml:79`) | B011 flags `assert False`; in tests the `assert` statement *is* the assertion mechanism. |
| `"src/adapters/binance_usdm.py" = ["E501"]` (`pyproject.toml:80`) | The module docstring carries a long SDK signature table (one row per SDK method with its 17.4.0 signature and semantics, `src/adapters/binance_usdm.py:56-62`). The table is deliberately verbatim and cannot be wrapped without losing the pinned signature. |
| `"src/risk/portfolio.py" = ["F841"]` (`pyproject.toml:81-85`) | `warning_threshold_quote` and `stop_threshold_quote` are assigned in `check_portfolio` and never read — the thresholds are consumed earlier by `_derive_daily_state`. This is a **documented latent daily-loss gating gap (D-18)**. Remove the ignore the next time the risk code is touched. |
- **Type checking:**
- Tool: mypy, `uv run mypy src` — **`src/` only**. `tests/` and `scripts/` are not type-checked,
- which is why `# type: ignore[arg-type]` appears freely in test code (e.g.
- `tests/test_binance_public.py:95`).
- `strict = true`, plus `ignore_missing_imports = false`, `warn_unused_ignores = true`,
- `warn_return_any = true`, `disallow_untyped_defs = true` (`pyproject.toml:87-94`).
- `warn_unused_ignores = true` means a **stale** `# type: ignore` is itself an error — an ignore
- that no longer suppresses anything must be deleted.
- **Type-error suppression is forbidden in `src/`.** There is no `as any` / `cast(Any, ...)`
- escape hatch for a real type error. `Any` is permitted only at genuine untyped boundaries:
- `canonical_scalars(value: Any)` (`src/domain/canonical.py:45`), SDK payload dicts.
- Narrow, code-specific ignores are allowed **only** where the third-party SDK is untyped:
- `# type: ignore[no-untyped-call]  # SDK is untyped` (`src/adapters/binance_userdata.py:570`,
- `src/adapters/paper_ws.py:290`), and `# type: ignore[arg-type]` where a project string is
- narrowed to the SDK's literal union (`src/adapters/binance_public.py:431,458,546`).
- **Narrow suppressions in `src/`:**
- `# noqa: BLE001` (blind `except Exception`) — allowed only where the failure is *classified
- into data*, never swallowed, and always with a reason:
- `src/adapters/binance_usdm.py:625` ("every exchange error is recorded as data"),
- `src/adapters/telegram_callbacks.py:536` ("fail closed: nothing was approved"),
- `src/adapters/telegram_notify.py:374` ("classified, never swallowed").
- `# noqa: E402` — only where a late import is structurally required:
- `src/core/types.py:321-322` (local re-export of `Signal` / `TradePlan` to avoid a circular
- import on the module's public surface).
- `# noqa: N818` — exception class names that do not end in `Error` because the public name is
- fixed by a plan/decision: `src/adapters/binance_client.py:69-93`,
- `src/adapters/binance_usdm.py:181,195`.

## Import Organization

- Order is enforced by Ruff's `I` rules. The project order is:
- `from __future__ import annotations` — **first line of every module** (`src/core/types.py:18`,
- `src/domain/registry.py:30`, `tests/conftest.py:23`).
- Stdlib (`import ast`, `import tomllib`, `from decimal import Decimal`).
- Third-party (`import pytest`, `import structlog`, `import sqlalchemy`).
- First-party `src.*` — **absolute** imports: `from src.core._decimal import _div, _mul`
- (`src/risk/quantization.py:24`), `from src.domain.enums import RejectionReason`
- (`src/core/types.py:24`).
- Same-package relative imports are used *inside* a package: `from .types import
- ConstraintSnapshot, SizedResult` (`src/risk/quantization.py:27`),
- `from .canonical import sha256_hex` (`src/domain/registry.py:39`).
- `tests.*` last, in its own isort section: `from tests import infra_helpers`,
- `from tests.pg_support import pg_db, ...` (`tests/conftest.py:36-45`),
- `from tests.support.ast_guards import wall_clock_calls` (`tests/test_ast_guards.py:14`).
- **Layer import rules (machine-enforced, not conventions):**
- `src/core` imports stdlib + `Decimal` only — no Polars, pandas, NumPy, Pydantic, SQLAlchemy or
- Binance SDK (`src/core/__init__.py:1-9`; enforced by `tests/test_domain_no_float.py` and the
- purity suites).
- Pure `src/analytics` modules import no `polars`/`pandas`/`numpy`/`sqlalchemy`/`pydantic`/
- `fastapi`/`httpx`/`duckdb`/`pyarrow` and no `src.adapters` / `src.db` / `src.data`
- (`tests/test_analytics_purity.py:21-37`).
- SDK response models never cross the adapter boundary.

## Error Handling

- **Strategy: fail closed.** Uncertain data, connection, account or risk ⇒ `NO_TRADE` and no new
- order (`docs/01_ENGINEERING_PRINCIPLES.md` §9). SAFE_MODE blocks entries while monitoring and
- reconciliation continue.
- **Rules:**
- **Typed exceptions, one per failure mode.** Never a bare `RuntimeError` for a domain
- condition. Examples:
- - `src/domain/registry.py` → `UnregisteredParameterSet`, `ParameterSetMutated`,
- `RegistrySchemaMismatch`, `StrategyKeyOutsideRegistry`.
- - `src/persistence/errors.py` → `StoreUnavailable`, `ParentRowMissing`, `JournalConflict`,
- `SessionTimeZoneNotUtc`.
- - `src/approval/replay.py` → `ApprovalAlreadyDecided`;
- `src/approval/binding.py` → `ApprovalRejected`;
- `src/backtest/binding.py` → `CostModelBindingMismatch`;
- `src/domain/transitions.py` → `IllegalTransition`.
- **No silent fallback.** The registry loader raises on an unknown key inside the registry, on
- a strategy-semantic key outside it, and on a mutated file — it never defaults
- (`src/domain/registry.py:1-28`).
- **Exception naming.** `XxxError` for a genuine error; a noun-phrase *refusal* when the
- condition is a deliberate gate rather than a defect: `PreSendRefusal` subclasses
- `SignedCallPolicyMissing` and `EntriesBlocked` (`src/adapters/binance_usdm.py:181,195`),
- `RestGateRefusal` (`src/adapters/binance_ratelimit_gate.py:59`).
- **Messages name the failure and the values, never a secret.** The persistence engine renders
- the URL with `hide_password=True` and names only the exception type
- (`src/persistence/engine.py:120-134`); the registry redaction module strips the password from
- subprocess stderr (`tests/pg_support.py:82-86`).
- **A broad `except Exception` is a classification, not a swallow.** It must attach the failure
- to a result, a journal event, a SAFE_MODE transition, or a NO_TRADE — and must carry
- `# noqa: BLE001` with a reason. `except Exception: pass` is forbidden.
- **Errors are never re-raised with a lost cause.** `raise ... from exc` (or `from None` when
- the cause is intentionally hidden) is used consistently
- (`src/domain/canonical.py:145-148`, `src/persistence/engine.py:130-134`).

## Logging

- **Framework:** `structlog`. Every module that logs creates a module-level logger:
- `import structlog`
- `log = structlog.get_logger()`
- (`src/adapters/binance_public.py:62`, `src/data/collector.py:76`, `src/ops/backup.py:60`.)
- **Patterns:**
- **Event names are dotted, lowercase, snake_case**, and read as a lineage path:
- `log.warning("adapter.exchange_info.unrequested_drift", symbols=ignored_drift)`
- (`src/adapters/binance_public.py:654`),
- `log.error("userdata.message_sink_failed", error_type=type(exc).__name__)`
- (`src/adapters/binance_userdata.py:519`),
- `log.info("userdata.supervisor.state", state=state.value, reason=reason)`
- (`src/adapters/binance_userdata_supervisor.py:867`).
- **Never log an exception message.** Log `error_type=type(exc).__name__` only — the message may
- carry a payload or a secret.
- **Structured key/value arguments**, not interpolated strings.
- **Decision lineage must be explainable post-hoc**: snapshot → signal → plan → approval →
- order. `src/risk/quantization.py` emits the lineage event with `raw_quantity`,
- `rounded_quantity`, `realized_risk` and the realized-to-allowed ratio
- (`src/risk/quantization.py:13-17`).
- **Purity wins over convenience.** A pure module keeps the `structlog` import *local to the
- logging call site* so the module-level import contract stays clean
- (`src/risk/quantization.py:13-17`).
- **Redaction is global.** `src/ops/redaction.py` scrubs structlog events, stdlib logging
- handlers, `sys.excepthook` / `threading.excepthook`, explicit stderr prints, and raises
- httpx/httpcore INFO to WARNING (Telegram URLs embed the bot token).
- `configure_logging()` lives in `src/ops/redaction.py:438`.
- Secrets are never logged, never printed, never returned in an error message.

## Comments

- **Module docstrings are mandatory and state the contract.** Every module opens with a docstring
- that says (a) what the module owns, (b) the decision IDs and phase/plan it came from, and
- (c) the fail-closed policy it enforces. Examples:
- `src/domain/canonical.py:1-33` — the canonicalisation policy, including what is *rejected*
- (`set`/`frozenset`, `float`) and why.
- `src/domain/registry.py:1-28` — the loader contract, including that the loader is
- fail-closed and never falls back silently.
- `src/ops/health.py:1-18` — the probe list, the injected clock, and the dependency-free rule.
- `src/risk/quantization.py:1-18` — the gate order and the "never round up" rule.
- **Docstrings on public functions** state the contract, the failure modes and the raises.
- `src/persistence/engine.py:105-111` uses the `Raises:` block form.
- **Inline comments explain WHY, never WHAT.** Examples:
- `src/core/types.py:138-145` — "WR-09: a stale value must never ride along on invalid — the
- AND-gate's chokepoint type enforces 'no value without validity' so `.value`-without-`.valid`
- misuse fails here, not downstream."
- `src/domain/registry.py:44-47` — "Registry path segments are restricted to this charset so
- `REGISTRY_ROOT / strategy_id / ...` cannot escape `params/` (WR-05: fail closed on
- `../../etc`-style inputs)."
- `src/ops/redaction.py:78-80` — "Values shorter than this are never collected from the
- environment (flags such as '1' or 'true' must not turn into redaction rules)."
- **Decision references are inline and greppable:** `(D-12)`, `(D047)`, `Per D-04/D-05/D-06:`,
- `(WR-16)`, `(CR-01)`, `(F-608)`. Use the same vocabulary as `docs/DECISIONS.md`.
- **Section banners** separate long modules:
- `# --------------------------------------------------------------------------- #`
- `# Decimal helpers (Phase 17, D-12) — spelling-invariant text and storage scale.`
- `# --------------------------------------------------------------------------- #`
- (`src/domain/canonical.py:94-96`, `src/core/types.py:26-30`, `src/ops/health.py:31-34`.)
- **`__all__` is declared** in barrels and in leaf modules with a curated public surface:
- `src/domain/__init__.py:46-81`, `src/core/__init__.py:25-41`, `src/core/types.py:355-367`,
- `src/core/_decimal.py:59-61`, `tests/support/ast_guards.py:192-198`.

## Function Design

- **Size:** one responsibility per function; a module that grows past ~500 lines is split by
- concern (e.g. `src/analytics/render.py` → `render_common.py`, `render_killgate.py`,
- `render_metrics.py`, `render_sidecar.py`).
- **Parameters:**
- Public API is keyword-only beyond the first positional argument.
- Decimal/price/quantity parameters are typed `Decimal` and validated at the boundary.
- **Return values:**
- Return a typed result object, not a tuple and not a bare `float`/`None`.
- A "no decision" outcome is a *typed* value with a reason code, never a silent `None`:
- `SetupResult.is_no_trade` + `reason_code`, `SizedResult.is_no_trade` +
- `quantization_decision`.
- **Validation happens at construction:**
- `@dataclass(frozen=True)` + `__post_init__` guards: `_require_non_empty`,
- `_require_utc_aware`, `_require_decimal`, `_require_positive` (`src/core/types.py:32-55`).
- Guards are **layer-local** by design (each phase layer keeps its own copy so the pure core
- stays dependency-free) — `src/core/types.py:26-30`, `src/core/_decimal.py:10-12`.
- Datetimes are UTC-aware or rejected: `value.utcoffset() != timedelta(0)` raises.
- **Decimal discipline (machine-enforced):**
- Money, price, quantity, risk and notional are `Decimal` — never `float(...)`.
- Floats are permitted only in statistical/feature code that never gates an order.
- Build a `Decimal` from a **string**, never from a float literal: `Decimal("0.5")`.
- All pure-core arithmetic runs in a pinned precision context:
- `src/core/_decimal.py` sets `_PREC = 28` and exposes `_q`, `_add`, `_sub`, `_mul`, `_div`.
- Use these; do not call raw operators outside them.
- Storage scale: `quantize_for_storage` rounds to `NUMERIC(38,18)` with `ROUND_HALF_EVEN`
- (`src/domain/canonical.py:130-148`).
- Canonical hashing text: `canonical_decimal_text` renders a plain (non-exponent) spelling so
- `1`, `1.0` and `Decimal("1.00")` hash identically (`src/domain/canonical.py:108-127`).
- **No wall clock in pure modules.**
- Inject the clock. `frozen_clock` (`tests/conftest.py:121-128`), `VirtualTime`
- (`tests/support/virtual_time.py`), or an explicit `now_utc` parameter
- (`src/ops/health.py:6-8`).
- The forbidden spellings are enumerated in `tests/support/ast_guards.py:21-31`
- (`WALL_CLOCK_CALLS`): `datetime.now`, `datetime.utcnow`, `date.today`, `time.time`,
- `time.time_ns`, `time.monotonic`, `time.monotonic_ns`, `time.perf_counter`,
- `time.perf_counter_ns`, plus the event loop's own clock (`loop.time()`).
- **Determinism:**
- Same snapshot + account state + strategy version + config ⇒ byte-equivalent output.
- Canonical JSON: sorted keys, compact separators, `ensure_ascii=True`, `allow_nan=False`
- (`src/domain/canonical.py:73-86`).
- Randomness only through an explicitly seeded instance (`random.Random(7)`), never the module
- (`tests/test_analytics_purity.py:156-160`).
- `hash()` (builtin) is banned in pure modules — it is salted per process
- (`tests/test_analytics_purity.py:152-154`).

## Module Design

- **Exports:**
- `src/<package>/__init__.py` is a **barrel**: a docstring, re-exports, and `__all__`. No logic
- lives there (`src/domain/__init__.py:1-9`, `src/core/__init__.py:1-9`).
- Barrels re-export the *public* surface only; registry exceptions are exported from
- `src/domain/__init__.py:35-42` because callers must catch them.
- **Package boundaries (enforced by AST guards, not by review):**

| Package | May import | Guard |
|---|---|---|
| `src/core` | stdlib + `Decimal` only | `tests/test_domain_no_float.py`, `tests/test_backtest_purity.py` |
| `src/domain` | stdlib + `Decimal` | `tests/test_domain_no_float.py` |
| `src/risk` | stdlib + `Decimal` + `src/core/_decimal.py` | `tests/test_domain_no_float.py` |
| `src/backtest` | stdlib + `Decimal` + `src/domain` + `src/risk` | `tests/test_domain_no_float.py`, `tests/test_backtest_purity.py` |
| `src/analytics` (pure) | stdlib + `Decimal`; **no** polars/pandas/numpy/sqlalchemy/pydantic/fastapi/httpx/duckdb/pyarrow, no `src.adapters`/`src.db`/`src.data` | `tests/test_analytics_purity.py` |
| `src/adapters` | Binance SDK, `python-telegram-bot`, httpx | boundary — SDK models never leave |
- **Database and migrations:**
- Every schema change is a **hand-written** Alembic revision in
- `src/db/alembic/versions/`. `create_all` is never used in a production path
- (`src/db/alembic/env.py:9-10`).
- Revisions `0001`–`0003` are **byte-identical historical revisions**; never edit them.
- `alembic upgrade head` only. `src/db/alembic/env.py` reads `DATABASE_URL` from the
- environment and refuses to run without it (`src/db/alembic/env.py:29-34`).
- DB URLs use `postgresql+psycopg://`; `src/persistence/engine.py:50-59` refuses any other
- driver.
- Every connection pins `TimeZone` to UTC: `options="-c timezone=UTC -c lock_timeout=... "`
- (`src/persistence/engine.py:82-88`), and the session zone is verified once
- (`assert_session_utc`, `src/persistence/engine.py:62-66`).
- Bounded waits are mandatory: `connect_timeout`, `lock_timeout`, `statement_timeout`,
- `pool_timeout`, TCP keepalives (`src/persistence/engine.py:33-46`).
- No in-memory fallback for a store: an unreachable database raises `StoreUnavailable`
- (`src/persistence/engine.py:20-22`).
- **Secrets:**
- Secrets live only in `.env` (mode 0600, gitignored). `secrets.env` also exists in the
- working tree and is never read into a transcript.
- Demo (`BINANCE_DEMO_*`) and live (`BINANCE_LIVE_*`) credential names are deliberately
- separate.
- `src/ops/redaction.py` redacts secrets from logs, tracebacks and stderr.
- CI synthesizes `.env` from `.env.example` with `chmod 600` (`.github/workflows/ci.yml:159-162`);
- the CI postgres password is a throwaway literal for an ephemeral service container.
- **Configuration:**
- Runtime configuration is versioned TOML under `params/`; operational config that is not a
- trading parameter lives under `config/` (e.g. `config/binance/binance-limits-v1.toml`).
- No ad-hoc virtualenv or tooling conventions per task
- (`docs/implementation/AGENT_INSTRUCTIONS.md` §11).

## Parameter Sets

- **Location:** `params/<family>/<parameter-set-id>.toml`, families `trend-pullback`,
- `breakout-retest`, `range-mr`.
- **Rules:**
- **Never edit a set in place.** A behaviour change ships as a NEW set plus a NEW
- `strategy_version`. `params/trend-pullback/baseline-v6.toml:8-10` states this explicitly:
- "baseline-v5 stays byte-identical for reproducing past hashes (F-810); do not mutate. New
- behaviour means a new set and a strategy-version bump (D-15)."
- **Hash-locked.** `parameter_set_hash` is SHA-256 over the canonical JSON of the normalized
- parameter document (`src/domain/registry.py:25-27`,
- `src/domain/canonical.py:89-91`). `registry-gate.yml` re-hashes every `params/**/*.toml`
- against the pins in `tests/fixtures/phase4/parameters.json`; an unpinned file fails closed.
- **Every value carries a provenance label** in a `[rationale.<key>]` table with a `basis`
- of `STRUCTURAL`, `COST_GUARD`, `DECISION`, `EXPERIMENT` or `PLACEHOLDER`, a `value`, a
- `text` and an optional `ref` naming the decision
- (`params/trend-pullback/baseline-v6.toml:69-224`).
- **Values are never chosen or tuned from backtest results** — "Research before optimisation"
- (`docs/01_ENGINEERING_PRINCIPLES.md` §4).
- **The loader is fail-closed**: an unknown key inside the registry raises; a
- strategy-semantic key found outside the registry raises
- (`src/domain/registry.py:57-58`, `STRATEGY_KEYS` at `:59-143`).
- Rate-like keys are unit-checked at load: a fee above 0.01 is a unit error and is refused
- (`src/domain/registry.py:146-150`).
- Registry path segments are charset-restricted so a set id can never escape `params/`
- (`src/domain/registry.py:44-47`).

## Domain Rules That Override Style

- **No AI/LLM in the trading decision path** — direction, entry, SL, TP, size, risk,
- parameters, signal validity. LLMs may assist code, docs, tests and explanations only
- (`docs/01_ENGINEERING_PRINCIPLES.md` §2, `docs/DECISIONS.md` D001).
- **Quantization floors, never rounds up**: floor to `stepSize` → reject below min quantity →
- reject below min notional → reject below `minimum_risk_utilization_after_rounding` (60%
- baseline) → `NO_TRADE` is preferred over a risk-budget breach. Identical logic in backtest,
- paper and live (`src/risk/quantization.py:41-57`).
- **Missing contract ⇒ TBD, never invent.** If a trading rule is absent from the docs, mark it
- TBD and open a research task; do not invent production behaviour
- (`docs/implementation/AGENT_INSTRUCTIONS.md` §10).
- **Research → Strategy Spec → Code.** Do not patch strategy logic in production code as an
- experiment (`docs/implementation/AGENT_INSTRUCTIONS.md` §3).
- **Exchange is the execution authority** for order status, fills, positions, realized PnL,
- commissions and conditional orders (`docs/01_ENGINEERING_PRINCIPLES.md` §3).
- **UTC internally**; convert to `Asia/Ho_Chi_Minh` only at the presentation edge
- (`docs/01_ENGINEERING_PRINCIPLES.md` §8, `tests/test_coverage.py:547-577`).
- ---
- *Convention analysis: 2026-10-19*

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

- ---
- last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
- last_mapped_at: 2026-10-19
- ---
- <!-- refreshed: 2026-10-19 -->
- **Analysis Date:** 2026-10-19

## System Overview

- **External systems:** Binance USDⓈ-M Futures (REST /fapi/*, WS Streams, user-data WS), Telegram Bot API, PostgreSQL 17.
- **Adapter boundary (src/adapters/):** inance_public, inance_usdm, paper_ws, inance_userdata*, 	elegram_notify, 	elegram_callbacks, nalytics_files/nalytics_store. SDK response models NEVER leave this layer.
- **Pure deterministic core:** src/core/ (features, strategy, planner), src/domain/ (entities + registry), src/risk/ (sizing + quantization), src/backtest/ (closed-candle simulator) — stdlib + Decimal only.
- **Runtime / orchestration:** src/paper/runtime.py (one asyncio loop, 1 queue + 1 consumer task), src/execution/manager.py, src/approval/ (tokens/replay), src/reconcile/ (compare/sweep), src/ops/ (backup/health).
- **Persistence:** src/persistence/ (sync SQLAlchemy) + src/db/ (ORM + Alembic); src/data/store.py (immutable Hive Parquet).
- **Offline analysis & governance:** src/analytics/ (metrics + kill-gate report, src/analytics/cli.py edge), src/research/ (manifest, register, multiplicity, authorization, settlement).

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `src/core/features.py` | Deterministic feature computation (ATR, EMA20/50/200, swing hi/lo, zone bounds, validity reasons) | `src/core/features.py` |
| `src/core/strategy.py` | Family dispatch (trend-pullback / breakout-retest / range-mr) → `NO_TRADE` or `SETUP(Signal)`; regime + setup gates | `src/core/strategy.py` |
| `src/core/planner.py` | Signal + candles → `TradePlan` (entry zone, SL, TP1/TP2, expiry, invalidation, plan_hash) | `src/core/planner.py` |
| `src/core/pivots.py` | Confirmed fractal pivots (left/right width) shared by regime and setup detectors | `src/core/pivots.py` |
| `src/core/_decimal.py` | Pinned-precision Decimal arithmetic helpers (`_add`, `_sub`, `_mul`, `_div`, `_q`) | `src/core/_decimal.py` |
| `src/domain/enums.py` | GLOSSARY-canonical enums (SignalStatus, TradePlanStatus, OrderStatus, RejectionReason, SystemMode…) | `src/domain/enums.py` |
| `src/domain/registry.py` | Versioned TOML parameter registry: load, hash, verify; fail-closed on unknown keys | `src/domain/registry.py` |
| `src/domain/canonical.py` | Canonical JSON + SHA-256 (`sha256_hex`) — the hashing primitive of every identity | `src/domain/canonical.py` |
| `src/domain/ids.py` | Content-hash IDs: `make_signal_id`, `derive_child_id` (plan/order IDs) | `src/domain/ids.py` |
| `src/domain/signal.py`, `trade_plan.py`, `order.py`, `position.py`, `fill.py`, `approval.py`, `journal.py` | Separate lifecycle entities (D007: signal ≠ plan ≠ order ≠ position) | `src/domain/` |
| `src/risk/gating.py` | `size_and_quantize` + `evaluate_risk` — the single shared risk pipeline for backtest/paper/live | `src/risk/gating.py` |
| `src/risk/quantization.py` | Floor-to-stepSize, then min-qty → min-notional → 60% utilization gate, in that fixed order | `src/risk/quantization.py` |
| `src/risk/portfolio.py` | Portfolio caps, cluster cap, daily-loss state machine (`DAILY_STOP`) | `src/risk/portfolio.py` |
| `src/risk/cost_guards.py`, `cost_rates.py` | Cost model, cost-to-risk ceiling, min stop distance, commission TTL | `src/risk/cost_guards.py` |
| `src/backtest/engine.py` | Project-owned closed-candle simulator (fees, funding, mark-price triggers, intrabar tie-breaks) | `src/backtest/engine.py` |
| `src/backtest/simulator.py` | Thin public entry: `run(case_input)` → `engine.simulate(case_input, risk_fn=evaluate_risk)` | `src/backtest/simulator.py` |
| `src/paper/runtime.py` | Paper process entrypoint: start gate → admission → config → instance lease → epoch pin → loop | `src/paper/runtime.py` |
| `src/paper/pipeline.py` | `BarPipeline.handle` — closed-candle gate, warm-up, history continuity, evaluation order | `src/paper/pipeline.py` |
| `src/paper/loop.py` | Pure paper dispatch; the realtime mirror of the backtest simulator (identical call chain) | `src/paper/loop.py` |
| `src/paper/freeze.py` | Allowlist / epoch pin / parameter-set validation gate | `src/paper/freeze.py` |
| `src/execution/manager.py` | approve → binding → risk → intent → place; the only component allowed to place orders | `src/execution/manager.py` |
| `src/execution/gates.py` | Placement-time revalidation: live constraints, portfolio caps, DAILY_STOP, headroom, enablement | `src/execution/gates.py` |
| `src/execution/intent_store.py` | `ExecutionIntentStore` Protocol — the exactly-once guard for entry and protective legs | `src/execution/intent_store.py` |
| `src/approval/tokens.py` | One-time token issue/hash/constant-time verify (stdlib only) | `src/approval/tokens.py` |
| `src/approval/binding.py` | Fixed-order callback gate: chat → expiry → plan-hash → version → token-hash | `src/approval/binding.py` |
| `src/approval/replay.py` | At-least-once replay resolution: 1 press = 1 transition, 5 replays = 1 transition | `src/approval/replay.py` |
| `src/reconcile/compare.py` | Exchange-vs-local state diff (orphan protectives, position divergence) | `src/reconcile/compare.py` |
| `src/reconcile/sweeper.py` | Cancels orphan protectives; two consecutive zero position reads required | `src/reconcile/sweeper.py` |
| `src/reconcile/safe_mode.py` | SAFE_MODE transitions (entries blocked, monitoring continues) | `src/reconcile/safe_mode.py` |
| `src/persistence/` | Synchronous SQLAlchemy stores: journal, approvals, execution state, runtime state, shadow stores, system state, UoW | `src/persistence/` |
| `src/db/models.py`, `mappers.py` | ORM tables and the domain↔row mappers (`src/db/mappers.py` is Decimal-only) | `src/db/models.py` |
| `src/adapters/binance_public.py` | Credential-free public market data (klines, mark klines, OI, funding, server time, exchangeInfo) | `src/adapters/binance_public.py` |
| `src/adapters/binance_usdm.py` | The ONLY module importing the Binance SDK for order/account surfaces | `src/adapters/binance_usdm.py` |
| `src/adapters/paper_ws.py` | WebSocket market-data adapter behind a project-owned interface | `src/adapters/paper_ws.py` |
| `src/adapters/binance_userdata*.py` | User-data stream: event parsing, router, supervisor, listen-key handling | `src/adapters/binance_userdata_events.py` |
| `src/adapters/telegram_notify.py` / `telegram_callbacks.py` | The only modules importing `python-telegram-bot` | `src/adapters/telegram_notify.py` |
| `src/data/collector.py` | 5-minute OI poll + funding sweep + opportunistic harvest; gap journal, never fabricated | `src/data/collector.py` |
| `src/data/store.py` | Immutable Hive-partitioned Parquet publish with atomic `os.replace` | `src/data/store.py` |
| `src/analytics/` | Pure metrics, kill-gate, slices, report and render; `src/analytics/cli.py` is the single edge | `src/analytics/report.py` |
| `src/research/` | Experiment manifest, preregistration grid, candidate register, multiplicity, authorization | `src/research/manifest.py` |
| `src/ops/backup.py` | `pg_dump` + Parquet copy + sha256 manifest + scratch restore drill | `src/ops/backup.py` |
| `src/ops/redaction.py` | `configure_logging` / `scrub` — secrets never reach a log line | `src/ops/redaction.py` |

## Pattern Overview

- **Overall:** Layered hexagonal (ports-and-adapters) architecture with a **pure deterministic core** and **fail-closed** semantics at every boundary.
- **Key Characteristics:**
- **Pure core / impure shell.** `src/core`, `src/domain`, `src/risk`, `src/backtest` and the pure parts of `src/analytics` / `src/paper` / `src/research` import only stdlib + `Decimal` (+ project-owned pure modules). All I/O lives in `src/adapters`, `src/persistence`, `src/db`, `src/data`, `src/ops` and the process entrypoints.
- **One decision path, three runtimes.** The identical call chain `src/core/strategy.evaluate` → `src/core/planner.plan` → `src/risk/gating.evaluate_risk` → `src/risk/quantization.quantize` is executed by the backtest engine (`src/backtest/simulator.py:56`), the paper loop (`src/paper/loop.py:35-53`) and the live execution manager (`src/execution/manager.py:63`). There is no second implementation of sizing, quantization or cost math.
- **Adapters as the only SDK boundary.** `src/adapters/binance_usdm.py` and `src/adapters/binance_public.py` are the only modules importing `binance_sdk_derivatives_trading_usds_futures`; `src/adapters/telegram_notify.py` and `src/adapters/telegram_callbacks.py` are the only modules importing `python-telegram-bot`. SDK response models never reach `src/domain` or `src/core`.
- **Fail closed.** Uncertain data, connection, account or risk yields `NO_TRADE` and no order. Every pure function returns a typed rejection (`RejectionReason`) instead of raising.
- **Content-addressed identity.** Every entity ID is a SHA-256 over canonical JSON (`src/domain/canonical.py`, `src/domain/ids.py`). Parameter sets are hash-locked in `params/<family>/<set>.toml` and never edited in place.
- **Injected time.** Pure modules never read a clock; clocks and `now_utc` are arguments.
- **Journal-first ordering.** A lifecycle fact is committed to the journal *before* the side effect that depends on it (Telegram send, order placement).
- **In-process queues, not a broker.** One bounded `asyncio.Queue` per process; durable state is a PostgreSQL row.

## Layers

- **`src/domain/` — Entities, enums, canonical serialization, parameter registry**
- Purpose: the shared vocabulary every other layer speaks. No I/O, no clock, no float.
- Location: `src/domain/`
- Contains: `enums.py`, `signal.py`, `trade_plan.py`, `order.py`, `position.py`, `fill.py`, `approval.py`, `journal.py`, `registry.py`, `canonical.py`, `ids.py`, `rationale.py`, `lot_filters.py`, `transitions.py`, `algo_status.py`, `exchange_errors.py`, `stream_records.py`.
- Depends on: stdlib only.
- Used by: every other layer.
- **Constraint:** `src/domain/registry.py` is the only way a parameter set enters the system. `load_parameter_set` / `verify_parameter_set` raise on an unregistered, mutated or unknown-key file; there is no silent fallback.
- **`src/core/` — Pure deterministic features / strategy / planner**
- Purpose: turn a market snapshot into a `Signal`, and a `Signal` into a `TradePlan`. Zero I/O, zero clock reads, zero randomness.
- Location: `src/core/`
- Contains: `types.py` (Candle, MarketSnapshot, AccountState, FeatureFrame, SetupResult), `features.py`, `strategy.py`, `planner.py`, `pivots.py`, `_decimal.py`.
- Depends on: `src/domain` + stdlib.
- Used by: `src/backtest`, `src/paper`, `src/execution`, `src/analytics`.
- **Constraint:** no Polars/pandas/NumPy/Pydantic/SDK/network import. Enforced by `tests/test_domain_no_float.py` and `tests/support/ast_guards.py`.
- **`src/risk/` — Sizing, cost guards, quantization, portfolio gates**
- Purpose: turn a `TradePlan` into a `SizedResult` or a typed rejection.
- Location: `src/risk/`
- Contains: `types.py`, `sizing.py`, `quantization.py`, `gating.py`, `portfolio.py`, `cost_guards.py`, `cost_rates.py`, `realized_risk.py`, `live_commission.py`.
- Depends on: `src/core`, `src/domain`.
- Used by: `src/backtest`, `src/paper`, `src/execution`.
- **Constraint:** the quantization gate order is fixed — floor to stepSize → min-quantity reject → min-notional reject → `minimum_risk_utilization_after_rounding` reject. Floors never round up; NO_TRADE is preferred over a risk-budget breach.
- **`src/backtest/` — Project-owned closed-candle simulator**
- Purpose: the canonical execution semantics shared with paper and live.
- Location: `src/backtest/`
- Contains: `engine.py` (v2 event-loop simulator), `simulator.py` (public `run`), `costs.py`, `funding.py`, `entry.py`, `exits.py`, `lifecycle.py`, `records.py`, `ledger.py`, `series.py`, `semantics.py`, `validator.py`, `report.py`, `experiment.py`, `binding.py`, `case.py`, `constraints.py`.
- Depends on: `src/core`, `src/domain`, `src/risk`.
- Used by: `src/research`, `src/analytics`, `scripts/`.
- **`src/adapters/` — The external boundary**
- Purpose: translate SDK/HTTP/file shapes into project-owned frozen dataclasses.
- Location: `src/adapters/`
- Contains: `binance_public.py`, `binance_usdm.py`, `binance_client.py`, `binance_clock.py`, `binance_errors.py`, `binance_limits.py`, `binance_probe.py`, `binance_ratelimit_gate.py`, `binance_userdata.py`, `binance_userdata_events.py`, `binance_userdata_router.py`, `binance_userdata_supervisor.py`, `paper_ws.py`, `telegram_notify.py`, `telegram_callbacks.py`, `analytics_files.py`, `analytics_store.py`, `code_version.py`.
- Depends on: the SDKs, plus `src/domain` for the project types it returns.
- Used by: `src/paper`, `src/data`, `src/execution`, `src/ops`, `src/analytics`.
- **Constraint:** SDK response models never leave this layer. The shadow runtime imports `binance_public.py` (not `binance_usdm.py`) so a process that must never place an order never loads the order adapter (`src/adapters/binance_public.py:1-9`).
- **`src/paper/` — Paper runtime, freeze, shadow mode, liveness**
- Purpose: the realtime mirror of the backtest, running against a public (credential-free) feed.
- Location: `src/paper/`
- Contains: `runtime.py` (entrypoint), `pipeline.py`, `loop.py`, `bars.py`, `freeze.py`, `runtime_config.py`, `runtime_state.py`, `supervisor.py`, `restart.py`, `resync.py`, `market_inputs.py`, `journal.py`, `notify.py`, `coverage.py`, `liveness.py`, `held_marker.py`, `attribution.py`, `exit_criteria.py`, `evidence_bundle.py`, `evidence_export.py`, `rehearsal.py`, `replay_inputs.py`, `shadow*.py` (8 modules), `surface.py`, `vocabulary.py`.
- Depends on: `src/core`, `src/risk`, `src/backtest`, `src/persistence`, `src/adapters`.
- Used by: the `paper` compose service and `deploy/compose-soak.sh`.
- **`src/approval/` — Approval tokens, binding, replay**
- Purpose: prove a human pressed the button, exactly once, against a plan that has not changed.
- Location: `src/approval/`
- Contains: `tokens.py`, `binding.py`, `replay.py`, `mapping.py`.
- Depends on: `src/domain` only (stdlib + `src/domain/enums.py`).
- Used by: `src/execution/manager.py`, `src/adapters/telegram_callbacks.py`, `src/persistence/approvals.py`.
- **`src/execution/` — Human-approved order placement**
- Purpose: the only layer that may place an order.
- Location: `src/execution/`
- Contains: `manager.py` (orchestration), `placement.py` (price/tick derivation, protective sizing), `gates.py` (placement-time gates), `pre_placement.py`, `enablement.py` (`LIVE_ORDERS_DISABLED` default), `execution_limits.py`, `constraint_snapshot.py`, `fill_monitor.py`, `intent_store.py`, `intent_recovery.py`, `lot_split.py`, `order_ids.py`, `tp_sizing.py`, `binding.py`.
- Depends on: `src/approval`, `src/risk`, `src/domain`, `src/persistence/errors.py`.
- Used by: the live runner (Phase 24) and `scripts/demo_rehearsal.py`.
- **`src/reconcile/` — Exchange reconciliation**
- Purpose: compare exchange truth with local truth and sweep orphans; drive SAFE_MODE.
- Location: `src/reconcile/`
- Contains: `compare.py`, `sweeper.py`, `safe_mode.py`.
- Depends on: `src/domain`, `src/persistence`.
- Used by: `src/ops/drills.py`, the live runner.
- **`src/persistence/` + `src/db/` — Operational state**
- Purpose: durable lifecycle state in PostgreSQL.
- Location: `src/persistence/` (stores), `src/db/` (ORM + Alembic)
- Contains: `persistence/engine.py` (sync engine factory, UTC-pinned, bounded timeouts), `uow.py` (`OperationalDatabase`), `journal.py`, `approvals.py`, `entities.py`, `execution_state.py`, `paper_runtime_state.py`, `shadow_stores.py`, `snapshots.py`, `system_state.py`, `errors.py`; `db/models.py` (16 tables), `db/mappers.py`, `db/alembic/versions/0001..0005`.
- Depends on: SQLAlchemy + psycopg.
- Used by: `src/paper`, `src/execution`, `src/analytics`, `src/data`.
- **Constraint:** `src/db/mappers.py` is Decimal-only (scanned by `tests/test_domain_no_float.py`).
- **`src/data/` — Collectors, Parquet datasets, coverage**
- Purpose: historical and live market-data acquisition into an immutable dataset.
- Location: `src/data/`
- Contains: `collector.py`, `backfill.py`, `backfill_cli.py`, `store.py`, `archive.py`, `case_input.py`, `collect_list.py`, `coverage.py`, `metadata.py`, `minute_source.py`, `quality.py`, `sufficiency.py`, `universe_freeze.py`.
- Depends on: `src/adapters`, `src/db`, `polars`, `duckdb`.
- Used by: `src/backtest` (case inputs), `src/analytics`.
- **`src/analytics/` — Metrics, kill-gate, report**
- Purpose: compute the evidence that decides whether a family passes or fails the kill-gate.
- Location: `src/analytics/`
- Contains: `core_metrics.py`, `report.py`, `killgate.py`, `killgate_guard.py`, `gates.py`, `slices.py`, `stats.py`, `excursion.py`, `latency.py`, `approval_delay.py`, `no_trade.py`, `lifecycle.py`, `live_outcomes.py`, `provenance.py`, `family.py`, `universe.py`, `clock.py`, `inputs.py`, `types.py`, `render*.py` (4 modules), `cli.py` (the single edge).
- Depends on: `src/domain` + stdlib; the CLI edge adds `src/adapters/analytics_files` and `src/adapters/analytics_store`.
- Used by: the operator, `docs/research/kill_gate_decisions.json`.
- **`src/research/` — Experiment registry, manifest, multiplicity**
- Purpose: make the research run auditable and pre-registered.
- Location: `src/research/`
- Contains: `manifest.py`, `manifest_build.py`, `register.py`, `run.py`, `multiplicity.py`, `authorization.py`, `feasibility.py`, `plateau.py`, `report.py`, `settlement_evidence.py`.
- Depends on: `src/domain`, `src/backtest`, `src/analytics`.
- Used by: `docs/research/preregistration/`, `docs/research/experiments/`.
- **`src/ops/` — Backup, cutover, drills, health, redaction**
- Purpose: keep the host operable and the secrets out of the logs.
- Location: `src/ops/`
- Contains: `backup.py`, `backup_remote.py`, `cutover.py`, `drills.py`, `evidence_remote.py`, `health.py`, `operator_evidence.py`, `redaction.py`.
- Depends on: `src/persistence`, `src/data`, stdlib + `structlog`.
- Used by: `deploy/*.sh`, the `ops` compose profile.
- **`src/sql/` — Analytical SQL**
- Purpose: the DuckDB coverage view over the Parquet tree.
- Location: `src/sql/coverage_v1.sql`.

## Data Flow

### Primary Request Path

- Paper runtime tick (the path that decides and records a trade):
- **SDK frame → tagged bar.** The Binance WS adapter raises a kline event; `src/adapters/paper_ws.py` normalizes it; the supervisor sink in `src/paper/runtime.py:821` (`_enqueue`) applies the restart fence and does `queue.put_nowait(bar)` — a full queue raises `RuntimeFailClosed` rather than dropping a bar.
- **Consumer → pipeline.** The single consumer task calls `BarPipeline.handle` inside `asyncio.to_thread` (`src/paper/runtime.py:48-54`); the pipeline applies the closed-candle gate, the warm-up gate and the history-continuity gate, then hands the 1H bar to the pure loop (`src/paper/pipeline.py:498-517`).
- **Strategy → Signal.** `src/core/strategy.py:680` `evaluate(snapshot, account_state, strategy_version, parameter_set)` computes features on both streams, resolves the 4H regime, runs the family detector, and returns `NO_TRADE` with a `RejectionReason` or a `SETUP(Signal)` whose `signal_id` is `make_signal_id(...)` over the identity tuple (`src/core/strategy.py:900`).
- **Signal → TradePlan.** `src/core/planner.py:419` `plan(signal, setup_candles, parameter_set, account_state, created_at_utc)` derives direction, entry zone, SL, TP1/TP2, expiry and `plan_hash`. Any mismatch, empty stream, expired signal or non-positive risk returns `NO_TRADE` — it never raises.
- **Plan → SizedResult.** `src/risk/gating.py` `evaluate_risk` runs `size_position` → `STOP_TOO_TIGHT` → `COST_TO_RISK_EXCEEDED` → `quantize` → `check_portfolio`. `src/risk/quantization.py:91` floors to `quantity_step_size` with exact Decimal floor-division, then applies min-qty → min-notional → 60% utilization rejects in that fixed order.
- **Journal, then notify.** `src/paper/journal.py` commits the decision row **first**; only then does `src/paper/notify.py` `notify_simulate` format the 12 APRV-01 fields and send through `src/adapters/telegram_notify.py`. Send failures are caught, journaled via `on_outcome` and never raise into the loop.
- **Journal → state port.** The tick writes its `PAPER_TICK_STATS` record and the decision records through the synchronous `RuntimeStatePort` (`src/paper/runtime_state.py:341`), which the runtime wraps in `asyncio.to_thread`.

### Secondary Flow — Live approval and placement

- **Telegram callback → binding gate.** `src/adapters/telegram_callbacks.py` receives the inline-keyboard callback and hands it to `src/approval/binding.py` `check_binding_full`, whose order is fixed: chat-id → expiry → plan-hash → strategy version / parameter-set id / parameter-set hash → token hash (`src/approval/binding.py:5-16`).
- **Replay resolution.** `src/approval/replay.py` looks the approval up by token hash (the idempotency key), then either returns the stored approval untouched (a replay) or performs exactly one `PENDING → APPROVED/SKIPPED` transition. Five replays of one APPROVE produce one transition.
- **Intent, then place.** `src/execution/manager.py` writes the ENTRY execution intent through the `ExecutionIntentStore` protocol **before** `place_entry` runs, and the STOP_LOSS leg gets its own intent **before** `place_algo_protective` (`src/execution/manager.py:15-24`). The persisted intent is the duplicate-entry guard — Binance's `newClientOrderId` uniqueness covers only OPEN orders.
- **Placement gates.** `src/execution/gates.py` revalidates live constraints from exchangeInfo, the portfolio caps, `DAILY_STOP` and the account-wide 200 open conditional-order headroom before any order call.

### Secondary Flow — Historical data and backtest

- **Collector → Parquet.** `src/data/collector.py` polls open interest every 5 minutes and sweeps funding every 8 hours; each tick is published through `src/data/store.py` `atomic_write_parquet` (temp file → fsync → `os.replace`) into the immutable Hive layout `data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet`. A failed poll writes one `collector_gaps` row and never advances the watermark.
- **Case input → engine.** `src/data/case_input.py` builds a case-input v2 dict; `src/backtest/simulator.py:56` `run(case_input)` calls `engine.simulate(case_input, risk_fn=evaluate_risk)` — the risk function is looked up in the module globals at call time, so a monkeypatch of `src.backtest.simulator.evaluate_risk` intercepts every risk call.
- **Experiment → manifest.** `src/research/manifest_build.py` and `src/research/run.py` execute the preregistered grid (`docs/research/preregistration/research-run-1-grid-*.json`) and write per-candidate experiment records to `docs/research/experiments/research-run-1/`.
- **Evidence → kill gate.** `src/analytics/cli.py` loads the evidence, decision and universe files through `src/adapters/analytics_files`, composes the frozen `ReportInputs`, runs the pure core and writes exactly two files (Markdown report + sidecar) under the confined reports root.

### Secondary Flow — Reconciliation and SAFE_MODE

- `src/reconcile/compare.py` diffs the exchange snapshot (open normal orders, open algo orders, positions) against the local `orders` / `execution_intents` / `positions` rows.
- `src/reconcile/sweeper.py:141` `sweep(diff, position_verifier=...)` cancels orphan protectives. Two consecutive zero position reads are required; a single non-zero read yields a `SweepSkip` with reason `transient_position_gap` and no cancel. A single cancel failure is journaled and the sweep continues.
- `src/reconcile/safe_mode.py` moves the system to `SystemMode.SAFE_MODE`: entries are blocked while monitoring and reconciliation continue.
- **State Management:**
- **Durable:** PostgreSQL. 16 tables in `src/db/models.py` — `symbol_metadata`, `collector_watermarks`, `collector_gaps`, `coverage_windows`, `signals`, `trade_plans`, `approvals`, `orders`, `execution_intents`, `fills`, `positions`, `journal_events`, `short_id_mapping`, `plan_constraint_snapshots`, `system_state_events`. Migrations in `src/db/alembic/versions/0001_baseline.py` … `0005_live_sized_risk.py`; `alembic upgrade head` only — `create_all` is never used.
- **Analytical:** immutable Hive-partitioned Parquet under `data/raw/`, read by DuckDB (`src/sql/coverage_v1.sql`).
- **In-process:** one bounded `asyncio.Queue` (`QUEUE_MAXSIZE = 4096` in `src/paper/runtime.py:174`) between the WS receive callbacks and the single consumer task. The queue is never a buffer of loss: a full queue fails the process closed.
- **Ephemeral:** the pinned epoch in `logs/paper/pinned_epoch.json` and the held marker in `src/paper/held_marker.py`.

## Key Abstractions

- **`MarketSnapshot` / `Candle` / `AccountState`**
- Purpose: the complete, clock-free input of the decision path.
- Examples: `src/core/types.py`, `src/core/features.py`
- Pattern: frozen dataclass, `Decimal` money, UTC-aware `datetime`.
- **`Signal`**
- Purpose: a detected setup. Not a trade, not an order.
- Examples: `src/domain/signal.py`, `src/core/strategy.py:910`
- Pattern: content-hash ID (`src/domain/ids.py:19`); status enum `SignalStatus` (`src/domain/enums.py:16`).
- **`TradePlan`**
- Purpose: the priced, expiring intent — entry zone, SL, TP1/TP2, expiry, invalidation, `plan_hash`.
- Examples: `src/domain/trade_plan.py`, `src/core/planner.py:419`
- Pattern: frozen dataclass; the plan hash is the thing an approval binds to (`src/approval/binding.py`).
- **`ParameterSet`**
- Purpose: the versioned, hash-locked parameter identity bound into every signal, plan and experiment.
- Examples: `src/domain/registry.py`, `params/trend-pullback/baseline-v6.toml`
- Pattern: loaded from `params/<family>/<id>.toml`; `parameter_set_hash` = SHA-256 over the canonical JSON of the normalized document. A behavior change ships as a NEW set plus a NEW `strategy_version` — never an in-place edit.
- **`ConstraintSnapshot`**
- Purpose: the exchange filters (stepSize, tickSize, minQty, minNotional) plus their freshness TTL.
- Examples: `src/risk/types.py`, `src/execution/constraint_snapshot.py`
- Pattern: re-read at placement time; a stale snapshot is a fail-closed reject, not a cached value.
- **`SizedResult` / `PortfolioVerdict`**
- Purpose: the typed outcome of the risk pipeline — accept with a quantity, or reject with a `RejectionReason`.
- Examples: `src/risk/types.py`, `src/risk/gating.py`
- Pattern: `is_no_trade` boolean + `reason_code`; the reason is preserved byte-identically across backtest/paper/live.
- **`RuntimeRecord` / `RuntimeStatePort`**
- Purpose: the paper runtime's durable event stream and the single storage port for restart-surviving state.
- Examples: `src/paper/runtime_state.py:133`, `src/paper/runtime_state.py:341`
- Pattern: a synchronous Protocol wrapped by the runtime in `asyncio.to_thread`. Idempotent write; the same record twice is a no-op, different content under the same id is a `RuntimeRecordConflict`.
- **`ExecutionIntentStore` / `IntentRecord`**
- Purpose: the exactly-once guard for order placement.
- Examples: `src/execution/intent_store.py`, `src/persistence/execution_state.py`
- Pattern: a Protocol injected into the manager; the intent is written *before* the adapter call, so a crash between intent and order is recoverable by `src/execution/intent_recovery.py`.
- **`JournalEvent`**
- Purpose: the audit trail of every lifecycle fact, including skipped signals.
- Examples: `src/domain/journal.py`, `src/persistence/journal.py`
- Pattern: content-hash event id (`content_hash_event_id`); appended, never updated.

## Entry Points

- **`python -m src.data.collector`**
- Location: `src/data/collector.py:1145` (`main`)
- Triggers: the `collector` compose service; the 5-minute OI poll loop.
- Responsibilities: universe load → per-tick OI poll + funding sweep → Parquet publish → atomic watermark advance → gap journal on failure. Flags: `--once` (single tick), `--healthcheck` (container probe; fails when no OI tick completed within 2× cadence or no funding sweep within one 8h interval + margin).
- **`python -m src.paper.runtime`**
- Location: `src/paper/runtime.py:1427` (`main`), parser at `src/paper/runtime.py:210`
- Triggers: the `paper` compose service (`--hold-on-refusal`), the one-shot `paper-pin` service (`--pin-epoch`), the container probe (`--healthcheck`), the heartbeat probe (`--liveness`).
- Responsibilities, in order — each step may end the process before the next: configure redacted logging → refuse any `BINANCE_*` env var (exit 3) → allowlist start gate → admission (exact-hash entry for every parameter set; exit 6) → ratified runtime config (exit 4) → single-instance lease (exit 8) → epoch pin/load (exit 5 / 6) → `RUNTIME_START` → the live loop → `RUNTIME_STOP`.
- The live loop composes the credential-free public adapter, `PaperWsAdapter`, `PaperSupervisor`, ONE bounded queue, ONE consumer task and `BarPipeline`. A full queue, a failed write or a pipeline error stops the loop and ends the process with `ExitCode.FAIL_CLOSED_RUNTIME` and **without** a `RUNTIME_STOP` record, so a restart reads the open `RUNTIME_START` as a crash.
- **`python -m src.ops.backup <subcommand>`**
- Location: `src/ops/backup.py:950` (`main`), parser at `src/ops/backup.py:989`
- Triggers: the `backup` compose service (`scheduled`), `deploy/backup.sh`, `deploy/restore.sh`, the systemd timers in `deploy/systemd/`.
- Responsibilities: `pg_dump --format=custom` + a Parquet tree copy + a `manifest.json` of per-file sha256, then the scratch-restore drill that re-hashes and compares. Subcommands: `backup`, `drill`, `prune`, `verify`, `restore`, `dump`, `restore-db`, `push`, `pull`, `retain`, `scheduled`, `drill-remote`. No SQL or copy logic lives in the shell scripts.
- **`python -m src.analytics.cli` (`src/analytics/cli.py:795`)**
- Location: `src/analytics/cli.py`
- Triggers: the operator; the research report step.
- Responsibilities: load evidence/decision/universe through `src/adapters/analytics_files`, compose `ReportInputs`, run the pure core, verify the Markdown and the sidecar agree, and write exactly two files under the confined reports root. stdout on success is exactly four lines: `Report:`, `Sidecar:`, `Digest: sha256:<64 hex>`, `Kill gate: <STATE>`.
- **Other module CLIs (all `python -m …`)**
- `python -m src.data.backfill_cli` (`src/data/backfill_cli.py:1138`)
- `python -m src.data.universe_freeze` (`src/data/universe_freeze.py:899`)
- `python -m src.data.collect_list` (`src/data/collect_list.py:495`)
- `python -m src.data.coverage` (`src/data/coverage.py:629`)
- `python -m src.data.sufficiency` (`src/data/sufficiency.py:747`)
- `python -m src.research.run` (`src/research/run.py:878`)
- `python -m src.research.register` (`src/research/register.py:268`)
- `python -m src.research.manifest_build` (`src/research/manifest_build.py:441`)
- `python -m src.ops.cutover` (`src/ops/cutover.py:529`)
- **`scripts/`** — developer and CI helpers
- `scripts/verify_decision_alignment.py` — the docs↔code gate (AU-01..AU-05 in `scripts/decision_alignment/authority.py`).
- `scripts/gen_phase6_fixtures.py`, `scripts/gen_phase14_fixtures.py`, `scripts/_compute_phase4_fixtures.py` — golden-fixture generators. Never hand-type a fixture.
- `scripts/dev/` — Windows helpers: `test.ps1`, `clean.ps1`, `migrate.ps1`, `journal-report.ps1` (see `scripts/dev/README.md`).
- `scripts/paper_ws_smoke.py`, `scripts/user_data_smoke.py`, `scripts/demo_probe.py`, `scripts/demo_rehearsal.py`, `scripts/shadow_rehearsal.py`, `scripts/smoke_backtest_realdata.py`, `scripts/soak_host_acceptance.py`, `scripts/export_soak_evidence.py`, `scripts/geometry_census.py`.
- **`deploy/*.sh`** — host operations
- `deploy/bootstrap.sh`, `deploy/update.sh`, `deploy/migrate.sh`, `deploy/backup.sh`, `deploy/restore.sh`, `deploy/backup-drill.sh`, `deploy/heartbeat.sh`, `deploy/compose-soak.sh`, `deploy/compose-rehearsal.sh`, `deploy/soak-image.sh`, `deploy/refresh-pins.sh`, `deploy/lib.sh` (shared shell library). systemd units in `deploy/systemd/`.

## Architectural Constraints

- **Threading:** single asyncio event loop per process. The paper runtime's receive callbacks only enqueue; every database write and the whole tick run off the loop through the one synchronous state port, wrapped locally with `asyncio.to_thread` (`src/paper/runtime.py:56-59`). The choice between threads and an async pool is a documented open item (Phase 24, G4-040). The collector is likewise single-threaded: async adapter calls, sync SQLAlchemy writes inline on the loop (`src/data/collector.py:14-25`).
- **Global state:** no mutable module-level singletons in the decision path. `src/domain/registry.py` holds the immutable `REGISTRY_ROOT` and `STRATEGY_KEYS` frozenset; `src/core/strategy.py` holds the immutable `_INTERVAL_DURATIONS` map. The genuinely stateful module-level objects are the runtime singletons in `src/paper/runtime.py` and `src/paper/shadow_runtime.py` (loop-scoped, not import-scoped) and the `structlog` loggers.
- **Circular imports:** none in the decision path. The dependency direction is `adapters → domain/core` and `runtime → core/risk/persistence`; `src/backtest/simulator.py` deliberately re-exports `evaluate_risk` so `src/backtest/engine.py` never imports `src.risk` directly, which keeps the risk function injectable at call time.
- **`src/core` purity:** stdlib + `Decimal` only. No Polars, pandas, NumPy, Pydantic, SQLAlchemy, Binance SDK or network import. Enforced by `tests/test_domain_no_float.py` and `tests/support/ast_guards.py`.
- **Decimal-only:** `src/domain/*`, `src/db/mappers.py`, `src/core/*`, `src/risk/*`, `src/backtest/*`, `src/analytics/*` (pure core) and the `src/adapters/paper_ws.py` adapter carry no `float(...)` constructor, no float literal and no `Decimal(<float literal>)` shape. `tests/test_domain_no_float.py` `SCANNED_FILES` + `SCANNED_GLOBS` define the exact scope; a glob-covered package (`src/backtest/*.py`, `src/paper/*.py`, `src/research/*.py`) can only be excluded through `FLOAT_SCAN_EXCLUDED`, which requires a one-line reason (today: `src/paper/shadow.py` only).
- **No wall clock in pure modules:** the forbidden spellings are enumerated in `tests/support/ast_guards.py` `WALL_CLOCK_CALLS` — `datetime.now`, `datetime.utcnow`, `date.today`, `time.time`, `time.time_ns`, `time.monotonic`, `time.monotonic_ns`, `time.perf_counter`, `time.perf_counter_ns` — plus the event loop's own clock (`loop.time()`, `asyncio.get_running_loop().time()`). Import aliases are resolved. Clocks are injected.
- **SDK isolation:** SDK response models never leave `src/adapters/`. `src/adapters/binance_usdm.py` and `src/adapters/binance_public.py` are the only Binance-SDK importers; `src/adapters/telegram_notify.py` and `src/adapters/telegram_callbacks.py` are the only `python-telegram-bot` importers.
- **Entity separation (D007):** signal ≠ trade plan ≠ order ≠ position. They have separate entities in `src/domain/`, separate tables in `src/db/models.py` and separate status enums in `src/domain/enums.py`.
- **Parameter immutability:** a parameter set is loaded only from the versioned registry `params/<family>/<set>.toml` via `src/domain/registry.py` (`load_parameter_set`, `verify_parameter_set`). A file is hash-locked by `tests/fixtures/phase4/parameters.json` and `registry-gate.yml`; an unpinned file fails closed.
- **No AI/LLM in the decision path:** direction, entry, SL, TP, size, risk, parameters and signal validity are decided by `src/core` + `src/risk` only.
- **Fail closed:** uncertain data, connection, account or risk ⇒ `NO_TRADE` and no new order. `SAFE_MODE` blocks entries while monitoring and reconciliation continue.

## Anti-Patterns

### Re-implementing sizing or quantization in a runtime

- **What happens:** a runtime computes its own quantity or applies its own rounding instead of calling `src/risk/gating.evaluate_risk`.
- **Why it's wrong here:** it breaks the D-02 parity guarantee — backtest, paper and live would no longer produce identical decisions for the same snapshot, and the golden fixtures would stop predicting paper behavior.
- **Do this instead:** call `evaluate_risk` / `size_and_quantize` (`src/risk/gating.py:61`). The backtest already does it via `src/backtest/simulator.py:56`; the paper loop does it in `src/paper/loop.py`; the live manager does it in `src/execution/manager.py:63`.

### Letting an SDK response model reach the domain

- **What happens:** a function in `src/domain` or `src/core` takes or returns a `binance_sdk_derivatives_trading_usds_futures` model.
- **Why it's wrong here:** the domain would then change whenever the SDK is upgraded, breaking the version-lock and the determinism guarantee, and the SDK would leak into the pure core (which the AST guards forbid).
- **Do this instead:** normalize in `src/adapters/binance_public.py` / `src/adapters/binance_usdm.py` to a frozen dataclass with `Decimal` money and UTC-aware `datetime`, and pass that.

### Reading the wall clock inside a pure function

- **What happens:** a module in `src/core`, `src/domain`, `src/risk` or `src/backtest` calls `datetime.now(UTC)` to stamp a decision.
- **Why it's wrong here:** the decision would no longer be a function of its inputs, so the same snapshot could produce a different plan on a re-run — the exact thing the determinism requirement forbids.
- **Do this instead:** take `now_utc` / `created_at_utc` as an argument (`src/core/planner.py:419`, `src/execution/manager.py`) or inject a clock callable (`src/paper/runtime_state.py` `RuntimeContext.clock`).

### Rounding up to reach a minimum

- **What happens:** a quantity is rounded up so it clears `min_quantity` or `min_notional`.
- **Why it's wrong here:** it silently raises the realized risk above the budget. The project rule is floor-then-reject, and NO_TRADE is preferred over a risk-budget breach.
- **Do this instead:** floor with exact Decimal floor-division, then let the ordered gates reject (`src/risk/quantization.py:91-135`).

### Editing a parameter set in place

- **What happens:** `params/trend-pullback/baseline-v6.toml` is edited to change a threshold.
- **Why it's wrong here:** the `parameter_set_hash` changes, so every signal, plan, experiment and approval bound to the old hash becomes invalid, and the registry gate turns red.
- **Do this instead:** add a NEW set file plus a NEW `strategy_version`; keep the old file byte-identical.

### Placing an order before the intent is durable

- **What happens:** the adapter call is made and the intent row is written afterwards.
- **Why it's wrong here:** a crash between the two loses the record of an order that exists on the exchange, and Binance's `newClientOrderId` uniqueness covers only OPEN orders — a replay would be accepted again.
- **Do this instead:** write the intent first, then place (`src/execution/manager.py:15-24`), and recover with `src/execution/intent_recovery.py`.

### Swallowing a send failure inside the loop

- **What happens:** a Telegram send exception propagates out of the notify call into the runtime loop.
- **Why it's wrong here:** it would kill the process on a transient network error, and it would break the journal-first ordering guarantee.
- **Do this instead:** catch it, journal the outcome through `on_outcome`, return normally (`src/paper/notify.py:9-16`).

## Error Handling

- **Strategy:** fail closed with a typed reason. Every pure decision function returns a result object carrying a `RejectionReason` (`src/domain/enums.py`) instead of raising; exceptions are reserved for programmer errors and for genuinely impossible states.
- **Patterns:**
- **Typed rejections.** `SetupResult(is_no_trade=True, reason_code=...)`, `PlanResult(is_no_trade=True, reason_code=...)`, `SizedResult(is_no_trade=True, reason_code=...)`. First failure wins, and the reason code is byte-identical across backtest/paper/live.
- **Fail-closed validation.** `src/domain/registry.py` raises `UnregisteredParameterSet` / `RegistrySchemaMismatch` / `StrategyKeyOutsideRegistry` / `ParameterSetMutated` rather than defaulting. `src/paper/runtime_config.py` raises `ConfigNotRatified` naming every missing or unknown key; no default is injected for any key.
- **Named exit codes.** `ExitCode` in `src/paper/runtime_config.py`: `OK`, `TRADE_KEY_REFUSED` (3), `CONFIG_NOT_RATIFIED` (4), `NO_PINNED_EPOCH` (5), `ADMISSION_OR_EPOCH_MISMATCH` (6), `FAIL_CLOSED_RUNTIME` (7), `INSTANCE_LEASE_HELD` (8), `USAGE`. Refusals are non-restartable; the compose service therefore passes `--hold-on-refusal` so a `restart: unless-stopped` policy cannot loop on them.
- **Persistence error taxonomy.** `src/persistence/errors.py`: `PersistenceError` (base) → `StoreUnavailable`, `StoreFailure`, `SessionTimeZoneNotUtc`, `JournalConflict`, `RowConflict`, `ParentRowMissing`, `PrecisionError`, `EvidenceRequired`, `ShortIdRebindingRefused`, `IntentStateConflict`. An unreachable database raises `StoreUnavailable` — there is no in-memory fallback.
- **Adapter error normalization.** `src/adapters/binance_errors.py` `error_facts_from_exception` and `src/domain/exchange_errors.py` `classify` map SDK exceptions to project categories. With `project_transport_errors=True` the paper path converts them into `TransientMarketDataError` / `MarketDataRateLimited` / `MarketDataRateLimitBan`; the SDK class name only, never a body or a URL.
- **Bounded retries.** `tenacity` with a capped attempt count; after the cap the caller fails closed. `src/adapters/binance_ratelimit_gate.py` `RestRateLimitGate` refuses a request before sending on a 418/429 and re-raises the original exception.
- **Error output hygiene.** Names and exception types only — never file contents, never credentials, never a response body.

## Cross-Cutting Concerns

- **Logging:** `structlog` JSON, configured through `src/ops/redaction.py` `configure_logging` (called first thing in `src/paper/runtime.py` `main` and `src/data/collector.py`). `src/ops/redaction.py` `scrub` removes secret values from log payloads. Decision lineage is carried as structured events: the quantization trail (`src/risk/quantization.py` emits raw quantity, rounded quantity, realized risk and the realized-to-allowed ratio), the journal rows and the runtime records. The pure modules that must stay dependency-free import `structlog` locally at the logging call site (see the comment in `src/risk/quantization.py:13-17`).
- **Validation:** three layers.
- *Static AST guards* — `tests/support/ast_guards.py` (`module_imports`, `forbidden_imports`, `float_constructor_calls`, `wall_clock_calls`) applied by `tests/test_domain_no_float.py`, `tests/test_ast_guards.py`, `tests/test_analytics_purity.py`, `tests/test_backtest_purity.py`, `tests/test_domain_boundary.py`.
- *Runtime fail-closed validation* — every boundary re-validates its input type, UTC-awareness and non-emptiness and raises a specific error rather than coercing (`_require_decimal`, `_require_utc_aware`, `_require_non_empty` in `src/paper/loop.py:60-96`; the same in `src/approval/binding.py:34-39`).
- *Golden fixtures* — `tests/fixtures/phaseN/` with hand-derived arithmetic in `DERIVATIONS.md` / `REGRESSION_SNAPSHOTS.md`, regenerated by `scripts/gen_phase6_fixtures.py`, `scripts/gen_phase14_fixtures.py`, `scripts/_compute_phase4_fixtures.py`.
- **Authentication:** there is no user-authentication layer — the system is single-operator. Authorization is the Telegram **chat-id gate** (the first step of `src/approval/binding.py`), plus the one-time approval token (`src/approval/tokens.py`, SHA-256 hashed, constant-time compare) and the exact-hash parameter allowlist (`src/paper/freeze.py` + the runtime process gate). Exchange credentials are the `BINANCE_DEMO_*` / `BINANCE_LIVE_*` variable families, read only by `src/adapters/binance_usdm.py`; the paper runtime refuses to start if any `BINANCE_*` name is present in its environment (`src/paper/runtime.py:6-7`). Secrets live only in `.env` (mode 0600, gitignored) and `secrets.env`; `src/ops/redaction.py` keeps them out of the logs.
- ---
- *Architecture analysis: 2026-10-19*

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
