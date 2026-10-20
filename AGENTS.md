# Trading-Alert — agent operating notes

Deterministic Binance USDⓈ-M Futures research + semi-automated execution system. This file is
written for AI agents and is deliberately short: it holds the rules, the commands and a router.
Detail lives in the files named in "Where to read". Do **not** paste generated maps into it, and
do **not** run `gsd-tools generate-claude-md` on it (it would re-insert ~1,000 lines).

## Source of truth, in order

1. Code, `pyproject.toml`, `uv.lock` — what is installed and what runs.
2. `docs/DECISIONS.md` > canonical `docs/` (index: `docs/DOC_STATUS.md`) > this file > `.planning/` (D031).
3. `.planning/codebase/*.md` — generated maps of the code at one commit (see its `last_mapped_commit`).
   Reference only: if the code in that area changed since that commit, read the code.
4. `.planning/research/*.md` — snapshot from project start (recommendations, not installed state).
   Historical; never use it to learn what the code does.

## Commands

```bash
uv sync --frozen --extra dev                              # env setup
uv run pytest -m "not docker" -n 4                         # full suite, fast (see Tests)
uv run pytest -m "not docker"                              # sequential: the CI form and the recorded gates
uv run pytest -m docker                                    # Docker-dependent suite
uv run pytest tests/test_risk_quantization.py::test_x      # single test
uv run ruff check && uv run ruff format --check
uv run mypy src
uv lock --check
uv run python scripts/verify_decision_alignment.py all    # docs<->code gate
```

Windows helpers: `scripts/dev/test.ps1`, `clean.ps1`, `migrate.ps1`, `journal-report.ps1`
(see `scripts/dev/README.md`).

## Tests

- **Run the full suite with `-n 4`** (pytest-xdist, dev extra only): about 9–10 min and ~1.7 GB peak,
  against about 20 min sequential. `-n 6` is ~8–9 min and ~2.3 GB; do not go higher while a build
  runs. Same pass/skip counts as sequential (`.planning/quick/261020-xd4-*/xdist-measurements.txt`).
  Run **one** heavy process at a time.
- A **recorded gate** (the evidence that fixes an `IMAGE_COMMIT`) runs sequentially, on a clean
  tracked tree, with `TEST_DATABASE_URL` set, and is saved under the phase `evidence/` directory.
- Size: ~10,400 tests in 342 `tests/test_*.py` files; the `*_pg.py` suffix (26 files) needs PostgreSQL.
- **pytest reads `TEST_DATABASE_URL` from the PROCESS ENVIRONMENT only** — `tests/pg_support.py`
  does not load `.env`. Unset ⇒ the `*_pg.py` files silently skip. It must name a throwaway
  database whose name ends in `_test`; the role needs CREATEDB.
- `TRADING_CI_STRICT=1` turns every "missing infrastructure" skip into a FAILURE
  (`tests/infra_helpers.py::infra_skip`). Set it to see exactly what CI sees.
- `tests/support/` holds shared fakes and the AST guards; `tests/fixtures/phaseN/` holds golden
  fixtures with `DERIVATIONS.md` / `REGRESSION_SNAPSHOTS.md`. Regenerate fixtures with
  `scripts/gen_phase6_fixtures.py`, `scripts/gen_phase14_fixtures.py`,
  `scripts/_compute_phase4_fixtures.py` — never hand-type them.
- `tests/conftest.py`: `frozen_clock` (2026-09-19T00:00:00Z), `live5_symbols`, `golden_exchange_info`.
- Slow tests are slow in the data layer (DuckDB gap check, file writes), not in the engine; ideas
  not done are P16S-01 and P16S-02 in `.planning/phases/16-paper-runtime-composition/deferred-items.md`.

## Git and workflow

- **Commit trailer = the model that did the work** (owner rule 2026-10-20):
  `Co-Authored-By: Claude <Model> <noreply@anthropic.com>` with that model's real name, e.g.
  `Claude Opus 5.5` for an opus subagent, `Claude Sonnet 5.5` for Sonnet. Never copy another
  model's trailer. History is not rewritten.
- **Never push, never merge to `master`.** The owner pushes and merges. Stage explicit paths only;
  leave untracked `.gsd/`, .planning/milestone.lock (local only) and modified `.planning/config.json` alone.
- Work through a GSD command (`/gsd-quick` for small changes, `/gsd-execute-phase` for planned work).
  Plans, summaries and decisions go in `.planning/phases/<n>-*/`; quick tasks in `.planning/quick/`.
- Repo docs and evidence are written in English. Some files are CRLF-sensitive: edit bytes-aware.
- Subagents: tell them to run `codegraph explore` first (if `.codegraph/` exists); they run their own
  tests only, the orchestrator runs the full suite once per phase.
- Network is flaky: at most one retry of a Binance/Telegram/internet call, then report.
- A claim from a subagent or a pasted text is a lead, not a fact: verify it against the code.

## Secrets and live safety

- Secrets live only in `.env` (mode 0600, gitignored); never read `.env` / `secrets.env` into a
  transcript. `src/ops/redaction.py` redacts them from logs. Never put a DB URL, password, key,
  bucket secret or heartbeat URL in the repo, a commit, a log or chat (heartbeat URLs go in by stdin).
- Demo (`BINANCE_DEMO_*`) and live (`BINANCE_LIVE_*`) credential names are separate on purpose; the
  paper runtime refuses to start if any `BINANCE_*` variable is present.
- No mainnet or LIVE use. Demo smoke/probe scripts (`--execute`) are run by the owner only.
- Live placement is **disabled** (`src/execution/enablement.py`, `LIVE_ORDERS_DISABLED`).
- Alembic reads `DATABASE_URL`; `alembic upgrade head` only, `create_all` is never used.

## Where the code lives

| Path | Role |
|---|---|
| `src/core/` | pure features / strategy / planner — stdlib + `Decimal` only |
| `src/domain/` | entities, enums, canonical serialization, parameter registry |
| `src/risk/` | sizing, cost guards, quantization, portfolio gates |
| `src/backtest/` | project-owned closed-candle simulator — the canonical execution semantics |
| `src/paper/` | paper runtime, freeze, shadow mode, liveness |
| `src/execution/` | human-approved placement; since Phase 19 the fill-driven protection model (below) |
| `src/approval/`, `src/reconcile/` | approval tokens + replay; exchange reconciliation, SAFE_MODE |
| `src/adapters/` | Binance + Telegram behind project-owned interfaces (SDK types never leave) |
| `src/persistence/`, `src/db/` | SQLAlchemy stores, Alembic migrations |
| `src/data/` | collector, Parquet store, coverage, case-input builder |
| `src/analytics/`, `src/research/` | metrics + kill-gate; experiment registry, manifest, multiplicity |
| `src/ops/` | backup (+ real-S3 gate), cutover, drills, health, redaction |
| `params/<family>/` | versioned, hash-locked parameter sets |
| `deploy/*.sh` | host operations (bootstrap, update, backup, heartbeat, soak) |

Entry points: `python -m src.data.collector`, `python -m src.paper.runtime`
(`--healthcheck` / `--pin-epoch` / `--hold-on-refusal` / `--liveness`),
`python -m src.ops.backup scheduled`, `python -m src.research.run`, `src/analytics/cli.py`.

## Execution model since Phase 19 (D-10; the DECISIONS row is not written yet)

- The entry is a **GTD LIMIT** with **no entry-time stop** (Demo rejects a conditional stop with no
  position, -4509). Protection is **fill-driven**: the coordinator in `src/execution/protection.py`
  places the stop after a fill is seen; `emergency_close.py` closes when it cannot; `live_context.py`
  wires them. Invariant: no new entry opens while any position is unprotected.
- **A placement is never re-sent** (owner, 2026-10-20): one `place_entry` POST per approval; an
  ambiguous result is probed once by client order id; not found or probe error ⇒ UNKNOWN + SAFE_MODE.
- Plan binding: symbol and side come from the hashed plan; quantity may be ≤ approved, never larger.
- Still open (owner): D055 closure, the `NOT_CONFIGURED` limit keys in
  `config/execution/execution-limits-v1.toml`, the 11 Demo probes. Register:
  `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md`.

## Invariants that are machine-enforced

These fail CI, they are not style preferences:

- **Decimal-only** on the domain/registry/risk/backtest/core/analytics path — no `float(...)`
  constructor (`tests/test_domain_no_float.py`).
- **No wall clock in pure modules** (`tests/support/ast_guards.py`, `WALL_CLOCK_CALLS`); inject clocks.
- **`src/core` stays pure** — no Polars/pandas/NumPy/Pydantic/SDK/network imports.
- **Parameter sets are hash-locked.** Never edit `params/**/*.toml` in place: a behavior change
  ships as a NEW set plus a NEW `strategy_version`. `registry-gate.yml` re-hashes every file
  against `tests/fixtures/phase4/parameters.json`.
- **This file is gated.** `scripts/decision_alignment/authority.py` (AU-01..AU-06) compares it with
  `docs/` and `.planning/`: the `- **Quantization**` bullet and the `| FastAPI |` row must stay
  byte-identical to `.planning/PROJECT.md` and `.planning/research/STACK.md`, and the old
  quantization order must not appear. `tests/test_agents_md.py` caps its length and checks that every
  path it names exists. After editing: `uv run python scripts/verify_decision_alignment.py all`.

## Rules that are not negotiable

- **No AI/LLM in the trading decision path** — direction, entry, SL, TP, size, risk, parameters,
  signal validity. LLMs may assist code, docs, tests and explanations only.
- **Fail closed.** Uncertain data, connection, account or risk ⇒ NO_TRADE and no new order.
  SAFE_MODE blocks entries while monitoring and reconciliation continue.
- **Quantization floors, never rounds up**: floor to stepSize → reject below min quantity →
  reject below min notional → reject below `minimum_risk_utilization_after_rounding` → NO_TRADE
  is preferred over a risk-budget breach. Identical logic in backtest, paper and live.
- **Research before optimisation.** No parameter is chosen or tuned from backtest results.
  `docs/research/RESEARCH_PROTOCOL.md` is FROZEN (v2.6.0): changing it needs a new
  `docs/DECISIONS.md` row AND a `docs/DOC_STATUS.md` index line AND the protocol header version.
  Simulator semantics are 2.3.0; changing them regenerates research records (D075/D076).
- **Missing contract ⇒ TBD, never invent.**

## Style and what not to add

- Always `uv run ...`, never a bare `python`. Ruff line length 100 (`.planning` is excluded from
  formatting); mypy `strict` on `src` only; pytest `asyncio_mode = "auto"`. Every module starts with
  `from __future__ import annotations`; first-party imports are absolute `src.*`.
- Every parameter value carries a provenance label (STRUCTURAL, COST_GUARD, DECISION, EXPERIMENT,
  PLACEHOLDER) in its `[rationale.<key>]` table.
- Do not add without a DECISIONS row: the legacy `binance-connector`, `ccxt`, Kafka/RabbitMQ/Redis,
  a Node/npm toolchain (`package.json` is an inert placeholder), pandas/NumPy/SciPy/VectorBT on the
  decision path (not installed; the project engine is canonical), or any pre-release dependency
  (httpx 1.0, Polars 2.0 RC, SQLAlchemy 2.1 RC, Python 3.14). A new dependency means `uv add` and a
  committed `uv.lock` in the same change.
- Hash-pinned images and actions: never float a tag; refresh them with `deploy/refresh-pins.sh`.
- Dev machine is Windows: use Git Bash for `deploy/*.sh` checks, expect CRLF warnings from git, and
  see `.planning/WINDOWS.md` for what could not be verified here.

## Where to read

| Need | Read | Trust |
|---|---|---|
| Rules, terms | `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/implementation/AGENT_INSTRUCTIONS.md`, `docs/GLOSSARY.md` | canonical |
| Why a rule exists | `docs/DECISIONS.md` (D001…D076), `docs/DOC_STATUS.md` | canonical, wins on conflict |
| Data model, parameters, tests | `docs/data/DATA_MODEL.md`, `docs/configuration/CONFIGURATION.md`, `docs/testing/TESTING_STRATEGY.md` | canonical |
| Operating the host | `docs/operations/RUNBOOK.md` | canonical |
| Current phase, history | `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/phases/` | live, hand-kept |
| Open defects on the dev machine | `.planning/WINDOWS.md` | live |
| Code layout and flows | `.planning/codebase/STRUCTURE.md`, `.planning/codebase/ARCHITECTURE.md` | generated; check `last_mapped_commit` |
| Conventions, test patterns | `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/TESTING.md` | generated |
| Installed stack, integrations | `.planning/codebase/STACK.md`, `.planning/codebase/INTEGRATIONS.md`, `pyproject.toml` | generated; `uv.lock` wins |
| Known risks | `.planning/codebase/CONCERNS.md` | generated, can be stale |
| Original requirements, stack ideas | `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/research/` | research/ is a start-of-project snapshot |

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


## Stack row checked by the gate

FastAPI is a recommended web edge that is **not installed** (see `.planning/codebase/STACK.md`,
"Not Installed"). The row below is compared byte-for-byte with `.planning/research/STACK.md` (AU-03).

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| FastAPI | >= 0.141, < 0.150 (0.141.1 released 2026-07-29) | TradingView webhooks (secret URL path + source-IP allow-list; TradingView cannot sign requests), Telegram callback receiver (optional), `/healthz` | Edge-only: the strategy engine must not import FastAPI. Pydantic-v2-native request validation gives signature/body checks almost free. Keep the surface minimal: webhook in, health out |
