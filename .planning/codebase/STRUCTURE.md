---
last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
last_mapped_at: 2026-10-19
---
# Codebase Structure

**Analysis Date:** 2026-10-19

## Directory Layout

```text
Trading-Alert/
├── src/                       # the application (src-layout; `src` is a real package)
│   ├── core/                  # PURE deterministic features / strategy / planner
│   ├── domain/                # entities, enums, canonical serialization, parameter registry
│   ├── risk/                  # sizing, cost guards, quantization, portfolio gates
│   ├── backtest/              # project-owned closed-candle simulator
│   ├── paper/                 # paper runtime, freeze, shadow mode, liveness
│   ├── analytics/             # research metrics, kill-gate, report (+ cli.py edge)
│   ├── research/              # experiment manifest, register, multiplicity, authorization
│   ├── data/                  # collectors, backfill, immutable Parquet store
│   ├── execution/             # human-approved order placement (the only order caller)
│   ├── approval/              # one-time tokens, binding gate, replay resolution
│   ├── reconcile/             # exchange reconciliation, orphan sweeper, SAFE_MODE
│   ├── adapters/              # Binance + Telegram behind project-owned interfaces
│   ├── persistence/           # synchronous SQLAlchemy stores + UoW
│   ├── db/                    # ORM models, mappers, Alembic migrations
│   ├── ops/                   # backup, cutover, drills, health, redaction
│   └── sql/                   # analytical SQL (DuckDB coverage view)
├── params/                    # versioned, hash-locked parameter sets (3 families)
├── config/                    # ratified runtime configuration (binance, execution, paper)
├── tests/                     # flat test suite + shared support + golden fixtures
├── scripts/                   # dev helpers, decision-alignment gate, fixture generators
├── deploy/                    # host bootstrap/update/migrate/backup/restore + systemd
├── docs/                      # canonical specs (decisions, glossary, data model, research)
├── data/                      # runtime datasets (git-ignored): raw/, backup/, reports/
├── logs/                      # runtime logs, pinned epoch, held markers (git-ignored)
├── .planning/                 # GSD planning state (PROJECT, ROADMAP, phases, codebase/)
├── .github/workflows/         # ci.yml, registry-gate.yml, research-gate.yml, paper_freeze_check.yml
├── pyproject.toml             # deps + pytest/ruff/mypy config
├── uv.lock                    # the reproducibility mechanism
├── docker-compose.yml         # postgres + collector + paper + paper-pin + backup + ops
├── Dockerfile                 # `runtime` and `ops` targets
├── alembic.ini                # Alembic config (reads DATABASE_URL)
└── AGENTS.md                  # agent operating notes (GSD-managed blocks)
```

## Directory Purposes

**`src/core/`:**
- Purpose: the deterministic decision core — features, strategy family dispatch, trade planning.
- Contains: `types.py`, `features.py`, `strategy.py`, `planner.py`, `pivots.py`, `_decimal.py`.
- Key files: `src/core/strategy.py` (family dispatch, `evaluate()`), `src/core/planner.py` (`plan()`), `src/core/_decimal.py` (pinned-precision Decimal helpers `_add`/`_sub`/`_mul`/`_div`/`_q`).
- Rule: stdlib + `Decimal` only. No Polars/pandas/NumPy/Pydantic/SDK/network import.

**`src/domain/`:**
- Purpose: the shared vocabulary — entities, enums, canonical hashing, the parameter registry.
- Contains: `enums.py`, `signal.py`, `trade_plan.py`, `order.py`, `position.py`, `fill.py`, `approval.py`, `journal.py`, `registry.py`, `canonical.py`, `ids.py`, `rationale.py`, `lot_filters.py`, `transitions.py`, `algo_status.py`, `exchange_errors.py`, `stream_records.py`.
- Key files: `src/domain/registry.py` (`load_parameter_set` at `:568`, `verify_parameter_set` at `:608`, `STRATEGY_KEYS` whitelist), `src/domain/canonical.py` (`sha256_hex`, canonical JSON), `src/domain/ids.py` (`make_signal_id`, `derive_child_id`).
- Rule: Decimal-only (no `float(...)`), no wall clock, no I/O.

**`src/risk/`:**
- Purpose: the single risk pipeline shared by backtest, paper and live.
- Contains: `types.py`, `sizing.py`, `quantization.py`, `gating.py`, `portfolio.py`, `cost_guards.py`, `cost_rates.py`, `realized_risk.py`, `live_commission.py`.
- Key files: `src/risk/gating.py` (`evaluate_risk`, `size_and_quantize`), `src/risk/quantization.py` (floor + the three ordered rejects), `src/risk/portfolio.py` (caps, `DAILY_STOP`).

**`src/backtest/`:**
- Purpose: the canonical execution semantics (closed-candle simulator).
- Contains: `engine.py` (v2 simulator), `simulator.py` (public `run`), `costs.py`, `funding.py`, `entry.py`, `exits.py`, `lifecycle.py`, `records.py`, `ledger.py`, `series.py`, `semantics.py`, `validator.py`, `report.py`, `experiment.py`, `binding.py`, `case.py`, `constraints.py`.
- Key files: `src/backtest/simulator.py` (the one public entry), `src/backtest/engine.py` (`simulate`).

**`src/paper/`:**
- Purpose: the realtime mirror of the backtest against a credential-free feed, plus the shadow runtime.
- Contains: `runtime.py`, `pipeline.py`, `loop.py`, `bars.py`, `freeze.py`, `runtime_config.py`, `runtime_state.py`, `supervisor.py`, `restart.py`, `resync.py`, `market_inputs.py`, `journal.py`, `notify.py`, `coverage.py`, `liveness.py`, `held_marker.py`, `attribution.py`, `exit_criteria.py`, `evidence_bundle.py`, `evidence_export.py`, `rehearsal.py`, `replay_inputs.py`, `live_minutes.py`, `restart.py`, `surface.py`, `vocabulary.py`, and 8 `shadow*.py` modules.
- Key files: `src/paper/runtime.py` (entrypoint + start gate), `src/paper/pipeline.py` (`BarPipeline.handle`), `src/paper/loop.py` (pure dispatch), `src/paper/freeze.py` (allowlist / epoch pin).

**`src/analytics/`:**
- Purpose: metrics, slices, kill-gate and the report — the evidence layer.
- Contains: `core_metrics.py`, `report.py`, `killgate.py`, `killgate_guard.py`, `gates.py`, `slices.py`, `stats.py`, `excursion.py`, `latency.py`, `approval_delay.py`, `no_trade.py`, `lifecycle.py`, `live_outcomes.py`, `provenance.py`, `family.py`, `universe.py`, `clock.py`, `inputs.py`, `types.py`, `render.py`, `render_common.py`, `render_killgate.py`, `render_metrics.py`, `render_sidecar.py`.
- Key files: `src/analytics/cli.py` (the only edge module), `src/analytics/report.py` (`ReportInputs`).

**`src/research/`:**
- Purpose: pre-registered, auditable experiment governance.
- Contains: `manifest.py`, `manifest_build.py`, `register.py`, `run.py`, `multiplicity.py`, `authorization.py`, `feasibility.py`, `plateau.py`, `report.py`, `settlement_evidence.py`.
- Key files: `src/research/manifest.py` (`ManifestError`, `ParameterGrid`, `GridPoint`), `src/research/register.py` (the candidate validator).

**`src/data/`:**
- Purpose: market-data acquisition and the immutable dataset.
- Contains: `collector.py`, `backfill.py`, `backfill_cli.py`, `store.py`, `archive.py`, `case_input.py`, `collect_list.py`, `coverage.py`, `metadata.py`, `minute_source.py`, `quality.py`, `sufficiency.py`, `universe_freeze.py`.
- Key files: `src/data/collector.py` (`python -m src.data.collector`), `src/data/store.py` (`atomic_write_parquet`, the Hive layout), `src/data/case_input.py` (the backtest input builder).

**`src/execution/`:**
- Purpose: the only layer that may place an order.
- Contains: `manager.py`, `placement.py`, `gates.py`, `pre_placement.py`, `enablement.py`, `execution_limits.py`, `constraint_snapshot.py`, `fill_monitor.py`, `intent_store.py`, `intent_recovery.py`, `lot_split.py`, `order_ids.py`, `tp_sizing.py`, `binding.py`.
- Key files: `src/execution/manager.py` (approve → risk → intent → place), `src/execution/intent_store.py` (the exactly-once guard).

**`src/approval/`:**
- Purpose: prove a human pressed the button, exactly once, against an unchanged plan.
- Contains: `tokens.py`, `binding.py`, `replay.py`, `mapping.py`.
- Key files: `src/approval/binding.py` (the fixed-order gate), `src/approval/replay.py` (at-least-once resolution).

**`src/reconcile/`:**
- Purpose: compare exchange truth with local truth, sweep orphans, drive SAFE_MODE.
- Contains: `compare.py`, `sweeper.py`, `safe_mode.py`.

**`src/adapters/`:**
- Purpose: the external boundary — SDK and file shapes become project-owned frozen dataclasses.
- Contains: `binance_public.py`, `binance_usdm.py`, `binance_client.py`, `binance_clock.py`, `binance_errors.py`, `binance_limits.py`, `binance_probe.py`, `binance_ratelimit_gate.py`, `binance_userdata.py`, `binance_userdata_events.py`, `binance_userdata_router.py`, `binance_userdata_supervisor.py`, `paper_ws.py`, `telegram_notify.py`, `telegram_callbacks.py`, `analytics_files.py`, `analytics_store.py`, `code_version.py`.
- Key files: `src/adapters/binance_public.py` (credential-free public data), `src/adapters/binance_usdm.py` (the only order-side SDK importer).

**`src/persistence/`:**
- Purpose: the synchronous SQLAlchemy stores and the unit of work.
- Contains: `engine.py`, `uow.py`, `journal.py`, `approvals.py`, `entities.py`, `execution_state.py`, `paper_runtime_state.py`, `shadow_stores.py`, `snapshots.py`, `system_state.py`, `errors.py`.
- Key files: `src/persistence/engine.py` (`make_sync_engine` — UTC-pinned, bounded timeouts, fail closed), `src/persistence/uow.py` (`OperationalDatabase`).

**`src/db/`:**
- Purpose: ORM tables, the domain↔row mappers, and the migrations.
- Contains: `models.py` (16 tables), `mappers.py`, `alembic/env.py`, `alembic/versions/0001_baseline.py` … `0005_live_sized_risk.py`.
- Key files: `src/db/models.py`, `src/db/mappers.py` (Decimal-only), `src/db/alembic/versions/`.

**`src/ops/`:**
- Purpose: host operations and secret hygiene.
- Contains: `backup.py`, `backup_remote.py`, `cutover.py`, `drills.py`, `evidence_remote.py`, `health.py`, `operator_evidence.py`, `redaction.py`.
- Key files: `src/ops/backup.py` (`python -m src.ops.backup`), `src/ops/redaction.py` (`configure_logging`, `scrub`).

**`params/`:**
- Purpose: the versioned, hash-locked parameter registry — the only source of strategy parameters.
- Contains: three families — `params/trend-pullback/` (baseline-v1..v6, `baseline-no-trade-v1..v4`, `baseline-simple-trend-v1..v4`, `research-run-1-a01..a16`), `params/breakout-retest/` (baseline-v1..v6, `research-run-1-b01..b16`), `params/range-mr/` (baseline-v1,v2,v4..v6, `research-run-1-c01..c16`).
- Key files: `params/trend-pullback/baseline-v6.toml` (current baseline), `params/*/research-run-1-*.toml` (the preregistered grid).
- Rule: never edit a file in place. A behavior change ships as a NEW set plus a NEW `strategy_version`.

**`config/`:**
- Purpose: the ratified runtime configuration (values, not code).
- Contains: `config/binance/binance-limits-v1.toml`, `config/execution/execution-limits-v1.toml`, `config/paper/paper-runtime-v1.toml` and `paper-runtime-v2.toml` (v2 is in force), each with a `README.md` listing the required keys.
- Key files: `config/paper/paper-runtime-v2.toml` (named by `PAPER_RUNTIME_CONFIG`), `config/paper/README.md` (the two gate layers, exit codes, epoch pin).
- Rule: money and rates are written as TOML **strings** (a TOML float would lose digits). No default exists in the code for any key.

**`tests/`:**
- Purpose: the whole verification strategy — unit, adapter, golden-fixture, PostgreSQL and Docker suites.
- Contains: 334 flat `tests/test_*.py` files (26 of them `*_pg.py`, which need a live PostgreSQL), `tests/conftest.py`, `tests/support/` (shared fakes + AST guards), `tests/fixtures/phaseN/` (golden fixtures), `tests/pg_support.py`, `tests/infra_helpers.py`, `tests/docker_helpers.py`, plus the module-level helper packages (`geometry_builders.py`, `paper_ws_fakes.py`, `probe_fakes.py`, `shadow_fakes.py`, `userdata_fakes.py`, `backtest_case_helpers.py`, `backtest_plan_helpers.py`, `phase10_helpers.py`).
- Key files: `tests/support/ast_guards.py` (`WALL_CLOCK_CALLS`, `forbidden_imports`, `float_constructor_calls`), `tests/test_domain_no_float.py` (`SCANNED_FILES`, `SCANNED_GLOBS`), `tests/conftest.py` (`frozen_clock`, `live5_symbols`, `golden_exchange_info`), `tests/pg_support.py` (disposable PostgreSQL databases).
- Fixture phases: `phase3`, `phase4`, `phase5`, `phase6`, `phase7`, `phase7.1`, `phase8`, `phase9`, `phase10`, `phase13`, `phase14`, `phase15`, `phase18`, `cutover`.

**`scripts/`:**
- Purpose: developer tooling, the docs↔code gate, and the golden-fixture generators.
- Contains: `verify_decision_alignment.py`, `decision_alignment/` (`authority.py`, `bookkeeping.py`, `exchange.py`, `ops_risk.py`, `params.py`, `protocol.py`, `universe.py`), `gen_phase6_fixtures.py`, `gen_phase14_fixtures.py`, `_compute_phase4_fixtures.py`, `_extend_phase4_candles.py`, `_regen_phase4_expectations.py`, `dev/` (PowerShell helpers + `README.md`), `demo_probe.py`, `demo_rehearsal.py`, `shadow_rehearsal.py`, `paper_ws_smoke.py`, `user_data_smoke.py`, `smoke_backtest_realdata.py`, `soak_host_acceptance.py`, `export_soak_evidence.py`, `evaluate_trial_soak.py`, `geometry_census.py`, `repair_parquet_scale.py`, `check_image_paths.py`, `backup-drill.ps1`.

**`deploy/`:**
- Purpose: host operations — no SQL or copy logic lives in the shell.
- Contains: `bootstrap.sh`, `update.sh`, `migrate.sh`, `backup.sh`, `restore.sh`, `backup-drill.sh`, `heartbeat.sh`, `compose-soak.sh`, `compose-rehearsal.sh`, `soak-image.sh`, `refresh-pins.sh`, `lib.sh` (shared shell library), `systemd/` (6 units + 6 timers), `evidence.env.example`, `soak.env.example`.

**`docs/`:**
- Purpose: the canonical specifications. Precedence (D031): `docs/DECISIONS.md` > canonical `docs/` > `AGENTS.md` > `.planning/`.
- Contains: `README.md` (document map), `00_PRODUCT_SCOPE.md`, `01_ENGINEERING_PRINCIPLES.md`, `DECISIONS.md`, `DOC_STATUS.md`, `GLOSSARY.md`, `SOURCES.md`, `TECHNOLOGY_STACK.md`, `architecture/` (`ARCHITECTURE.md`, `DATA_PIPELINE.md`), `backtest/` (`BACKTEST_SPEC.md`, `METRICS.md`), `configuration/CONFIGURATION.md`, `data/DATA_MODEL.md`, `implementation/` (`AGENT_INSTRUCTIONS.md`, `IMPLEMENTATION_PLAN.md`), `integration/` (`BINANCE.md`, `TELEGRAM.md`, `TRADINGVIEW.md`), `operations/` (`RUNBOOK.md`, `SECURITY_AND_OPERATIONS.md`, `DEPLOY_GUIDE.vi.md`), `research/` (`RESEARCH_PROTOCOL.md`, `TRADING_STRATEGY_RESEARCH.md`, `families/`, `preregistration/`, `experiments/`, `universe/`, `GEOMETRY_AUDIT.md`, `kill_gate_decisions.json`), `strategy/TRADING_STRATEGY_SPEC.md`, `testing/TESTING_STRATEGY.md`, `trading/` (`EXECUTION_SPEC.md`, `RISK_MANAGEMENT.md`, `SIGNAL_AND_ALERTS.md`).

**`.planning/`:**
- Purpose: the GSD planning state (roadmap, phases, audits, and this codebase map).
- Contains: `PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, `STATE.md`, `state.json`, `config.json`, `milestone.lock`, `WINDOWS.md` (the open defect ledger), `LIVE-TEST-2026-10-04.md`, `v0.3-MILESTONE-AUDIT.md`, `phases/`, `codebase/`, `research/`, `audits/`, `intel/`, `quick/`.
- Note: `.planning` is excluded from `ruff format` (`pyproject.toml` `extend-exclude`) because it holds prose with embedded Python snippets.

## Key File Locations

**Entry Points:**
- `src/data/collector.py:1145` — `main()` for `python -m src.data.collector` (5-minute OI poll, funding sweep, `--once`, `--healthcheck`).
- `src/paper/runtime.py:1427` — `main()` for `python -m src.paper.runtime`; the parser is `build_parser()` at `src/paper/runtime.py:210` (`--hold-on-refusal`, `--pin-epoch`, `--healthcheck`, `--liveness`, `--pinned-state`).
- `src/ops/backup.py:950` — `main()` for `python -m src.ops.backup` (`backup`, `drill`, `prune`, `verify`, `restore`, `dump`, `restore-db`, `push`, `pull`, `retain`, `scheduled`, `drill-remote`).
- `src/analytics/cli.py:795` — `main()` for the offline journal-depth / kill-gate report.
- `src/data/backfill_cli.py:1138`, `src/data/universe_freeze.py:899`, `src/data/collect_list.py:495`, `src/data/coverage.py:629`, `src/data/sufficiency.py:747`, `src/research/run.py:878`, `src/research/register.py:268`, `src/research/manifest_build.py:441`, `src/ops/cutover.py:529` — the remaining module CLIs.
- `deploy/*.sh` and `deploy/systemd/` — the host-side entry points.

**Configuration:**
- `pyproject.toml` — dependencies, `asyncio_mode = "auto"`, ruff (`line-length = 100`, `target-version = "py313"`), mypy (`strict = true`).
- `uv.lock` — the reproducibility mechanism; `uv lock --check` is a CI gate.
- `alembic.ini` + `src/db/alembic/env.py` — Alembic reads `DATABASE_URL`.
- `config/paper/paper-runtime-v2.toml` — the in-force paper runtime configuration (`PAPER_RUNTIME_CONFIG`).
- `config/binance/binance-limits-v1.toml`, `config/execution/execution-limits-v1.toml` — the ratified exchange and execution limits.
- `params/<family>/<set>.toml` — every strategy parameter.
- `.env` (mode 0600, gitignored) and `.env.example` — secrets and their documented names. Never read `.env` into a transcript.

**Core Logic:**
- `src/core/features.py` — `compute_features`.
- `src/core/strategy.py:680` — `evaluate()` (the family dispatch and the NO_TRADE vocabulary).
- `src/core/planner.py:419` — `plan()` (Signal → TradePlan, geometry, RR gate).
- `src/risk/gating.py` — `size_and_quantize` / `evaluate_risk` (the shared pipeline).
- `src/risk/quantization.py:32` — `quantize` (floor + the three ordered rejects).
- `src/risk/portfolio.py` — caps, cluster cap, daily-loss state machine.
- `src/backtest/engine.py` — the closed-candle simulator.
- `src/domain/registry.py` — `load_parameter_set` / `verify_parameter_set` / `STRATEGY_KEYS`.
- `src/domain/canonical.py` — `sha256_hex` and the canonical JSON form.
- `src/paper/pipeline.py` — `BarPipeline.handle` (closed-candle, warm-up, continuity gates).
- `src/execution/manager.py` — approve → risk → intent → place.
- `src/approval/binding.py` — the fixed-order callback gate.
- `src/adapters/binance_usdm.py` — the SDK method/signature table (re-verify after every SDK bump).

**Testing:**
- `tests/conftest.py` — `frozen_clock` (2026-09-19T00:00:00Z), `live5_symbols` (BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT), `golden_exchange_info`, the phase3/4/5 loaders.
- `tests/support/ast_guards.py` — the reusable AST guards.
- `tests/test_domain_no_float.py` — the Decimal-only scope.
- `tests/test_ast_guards.py`, `tests/test_domain_boundary.py`, `tests/test_analytics_purity.py`, `tests/test_backtest_purity.py` — the purity and boundary suites.
- `tests/pg_support.py` — disposable PostgreSQL databases (the role needs CREATEDB; the database name must end in `_test`).
- `tests/infra_helpers.py` — `infra_skip`; `TRADING_CI_STRICT=1` turns every "missing infrastructure" skip into a failure.
- `tests/fixtures/phaseN/` — golden fixtures; each phase directory carries `DERIVATIONS.md` or `REGRESSION_SNAPSHOTS.md` with the hand-derived arithmetic.
- `tests/test_deploy_workflows.py`, `tests/test_deploy_scripts.py`, `tests/test_deploy_compose.py` — the deployment contract as text.

**Data & Reports (git-ignored):**
- `data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet` — the immutable raw dataset (`src/data/store.py`).
- `data/raw/dataset=mark_klines/...` — the separate mark-price dataset.
- `data/backup/` — the backup bundle root (`pg.dump`, `parquet/`, `manifest.json`).
- `data/reports/` — the analytics Markdown report + JSON sidecar.
- `logs/paper/pinned_epoch.json` — the pinned epoch; `logs/paper/` also holds the held marker.

## Naming Conventions

**Files:**
- `snake_case.py` for every Python module — no abbreviations except the established `oi` (open interest), `ws` (websocket), `pg` (PostgreSQL) and `db` (database) stems.
- Layer-first naming inside a package: the subject comes first, the role second — `src/risk/quantization.py`, `src/risk/realized_risk.py`, `src/paper/runtime_config.py`, `src/execution/intent_store.py`.
- `_`-prefixed for a private module-local helper: `src/core/_decimal.py`, `scripts/_compute_phase4_fixtures.py`, `scripts/_extend_phase4_candles.py`, `scripts/_regen_phase4_expectations.py`.
- `test_*.py` for tests; `*_pg.py` marks a test that needs a live PostgreSQL; `test_<subject>.py` names the subject under test, not the layer (`tests/test_registry.py`, `tests/test_paper_freeze.py`, `tests/test_kill_gate_state.py`).
- `snake_case.toml` for configuration and parameter files, versioned with a `-vN` suffix (`paper-runtime-v2.toml`, `baseline-v6.toml`).
- `UPPER_SNAKE_CASE` for shell scripts (`deploy/backup.sh`) and `kebab-case` for GitHub workflows (`.github/workflows/ci.yml`).

**Directories:**
- One lowercase, single-word layer per directory under `src/`: `core`, `domain`, `risk`, `backtest`, `paper`, `analytics`, `research`, `data`, `execution`, `approval`, `reconcile`, `adapters`, `persistence`, `db`, `ops`, `sql`.
- `phaseN` (and `phase7.1`) for the golden-fixture directories under `tests/fixtures/` — the number is the phase that produced them.
- `family` names under `params/` are the strategy family ids: `trend-pullback`, `breakout-retest`, `range-mr` (kebab-case, matching `parameter_set.strategy_id`).
- `dataset=<name>`, `interval=<TF>`, `symbol=<SYM>`, `date=<YYYY-MM-DD>` for the Hive-partitioned Parquet layout.
- `src/adapters/binance_*` for the Binance surface, `src/adapters/telegram_*` for the Telegram surface, `src/adapters/analytics_*` for the analytics file/store surface.

**Functions and variables:**
- `snake_case` for functions and module-level constants; `PascalCase` for classes and dataclasses; `UPPER_SNAKE_CASE` for module-level constants (`REGISTRY_ROOT`, `QUEUE_MAXSIZE`, `HEADROOM_LIMIT`, `LIVE5_SYMBOLS`, `WALL_CLOCK_CALLS`).
- Private helpers carry a leading underscore (`_require_decimal`, `_check_registry_segment`, `_detect_setup`).
- Booleans read as predicates: `is_no_trade`, `features_valid`, `project_transport_errors`, `hold_on_refusal`.
- Decision identifiers are SCREAMING_SNAKE (`NO_TRADE`, `MIN_QTY_REJECT`, `NOTIONAL_REJECT`, `UTILIZATION_REJECT`, `DAILY_STOP`, `STOP_TOO_TIGHT`, `COST_TO_RISK_EXCEEDED`).
- Explicit `from __future__ import annotations` at the top of every module.

**Types:**
- Domain entities are frozen dataclasses with `Decimal` money and UTC-aware `datetime` timestamps.
- Enums are `str, Enum` mixins so the ORM and JSON `.value` storage is trivial (`src/domain/enums.py:8-13`).
- Ports are `typing.Protocol` classes: `RuntimeStatePort` (`src/paper/runtime_state.py:341`), `ExecutionIntentStore` (`src/execution/intent_store.py`), `PositionVerifier` (`src/reconcile/sweeper.py`).
- Protocol-typed adapters keep the manager free of the SDK (`src/execution/manager.py:86-89`).

## Where to Add New Code

**New Feature (a strategy or rule change):**
- Primary code: `src/core/strategy.py` (the detector) and `src/core/planner.py` (the geometry). A new family also needs a new directory under `params/` and a new `strategy_id` branch.
- Parameter values: a NEW file under `params/<family>/` plus a new `strategy_version`. Never edit an existing TOML.
- Tests: `tests/test_core_strategy_<family>.py` (pattern: `tests/test_core_strategy_breakout_retest.py`, `tests/test_core_strategy_range_mr.py`) and `tests/test_planner_geometry.py`.
- Fixtures: a new `tests/fixtures/phaseN/` directory with `DERIVATIONS.md`, regenerated by a `scripts/gen_phaseN_fixtures.py` script — never hand-typed.

**New Component/Module (an implementation detail of an existing layer):**
- Put it in the layer that owns the concern: a new detector helper goes in `src/core/`, a new store in `src/persistence/`, a new gate in `src/execution/` or `src/risk/`, a new SDK call wrapper in `src/adapters/`, a new operational task in `src/ops/`.
- If the module touches I/O, it does **not** belong in `src/core`, `src/domain` or `src/risk`.
- If it is pure, it goes in the pure layer and must satisfy the AST guards (`tests/support/ast_guards.py`): no wall clock, no float, no forbidden imports.
- Name it `snake_case.py` and export the public names in an `__all__` list (the convention in `src/core/strategy.py`, `src/approval/tokens.py`, `src/backtest/simulator.py`).
- If it introduces a new database table, add an Alembic revision under `src/db/alembic/versions/` — `alembic upgrade head` only, never `create_all`.

**New Entry Point (a CLI):**
- Put `main(argv: Sequence[str] | None = None) -> int` plus a module-level `if __name__ == "__main__":` guard in the owning layer module (`src/data/collector.py:1145`, `src/research/run.py:878`).
- The parser is a module-level `argparse.ArgumentParser`; exit codes are integers, and 0 means success only.

**New Adapter (an external call):**
- Add it to `src/adapters/` and expose frozen dataclasses, never SDK models.
- If it is a Binance surface, follow `src/adapters/binance_public.py` (credential-free) or `src/adapters/binance_usdm.py` (order/account); the shadow runtime must keep importing only the public module.
- If it is Telegram, extend `src/adapters/telegram_notify.py` (outbound) or `src/adapters/telegram_callbacks.py` (inbound).
- Never import the SDK outside `src/adapters/`.

**New Persistence Store:**
- Add a `Pg…Store` class in `src/persistence/` (the naming convention is `Pg` + the entity, e.g. `PgJournalStore`, `PgApprovalStore`, `PgExecutionStateStore`, `PgRuntimeState`).
- Take the store's dependencies as callables or a Protocol; the store must not import the adapters.
- Add the matching test as `tests/test_persistence_<name>_pg.py`.

**Utilities:**
- Shared pure helpers for the decision path: `src/core/_decimal.py` (Decimal arithmetic) and `src/domain/canonical.py` (hashing/canonical JSON).
- Shared test helpers: `tests/support/` (the AST guards, the fake Binance exchange, the virtual clock, the net guard) or a module-level helper in `tests/` (`tests/geometry_builders.py`).
- Operational helpers: `src/ops/`.
- Developer helpers: `scripts/` (Python) or `scripts/dev/` (PowerShell, dot-sourcing `scripts/dev/_common.ps1`).

**New Configuration:**
- A runtime value: a TOML file under `config/<area>/` plus a `README.md` listing the required keys, loaded by a `<area>/config.py` module that refuses unknown keys and injects no default.
- A strategy value: a new file under `params/<family>/`.
- A secret: an environment variable named in `.env.example`, read only by the owning adapter.

## Special Directories

**`params/`:**
- Purpose: the versioned, hash-locked strategy parameter registry.
- Generated: No — hand-authored, but hash-pinned by `tests/fixtures/phase4/parameters.json` and re-checked by `.github/workflows/registry-gate.yml`.
- Committed: Yes.

**`tests/fixtures/phaseN/`:**
- Purpose: golden fixtures with hand-derived arithmetic (`DERIVATIONS.md` / `REGRESSION_SNAPSHOTS.md`).
- Generated: Partly — `scripts/gen_phase6_fixtures.py`, `scripts/gen_phase14_fixtures.py`, `scripts/_compute_phase4_fixtures.py` regenerate them; the derivations are hand-written.
- Committed: Yes.

**`docs/research/experiments/research-run-1/` and `docs/research/experiments/research-run-1-v2-3-0/`:**
- Purpose: one JSON file per experiment candidate, named by its parameter-set hash.
- Generated: Yes — by the research runner (`src/research/run.py`).
- Committed: Yes — the run is part of the audit trail.

**`data/`:**
- Purpose: the runtime datasets (raw Parquet, backup bundles, analytics reports).
- Generated: Yes.
- Committed: No — git-ignored.

**`logs/`:**
- Purpose: runtime logs, `paper/pinned_epoch.json`, the held marker, `registry_diff.jsonl`.
- Generated: Yes.
- Committed: No — git-ignored.

**`src/db/alembic/versions/`:**
- Purpose: the schema migrations, numbered `0001_…` … `0005_…`.
- Generated: No — hand-written, reviewed, and applied with `alembic upgrade head` only.
- Committed: Yes.

**`deploy/systemd/`:**
- Purpose: the host timers for backup, heartbeat and soak runs.
- Generated: No.
- Committed: Yes.

**`.planning/`:**
- Purpose: the GSD planning state and this codebase map.
- Generated: Partly — GSD regenerates the marked blocks in `AGENTS.md`; the rest is hand-written.
- Committed: Yes.

**`.codegraph/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.venv/`, `.serena/`, `.omo/`, `.gsd/`:**
- Purpose: tooling caches and indexes.
- Generated: Yes.
- Committed: No.

---

*Structure analysis: 2026-10-19*
