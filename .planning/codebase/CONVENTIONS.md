---
last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
last_mapped_at: 2026-10-19
---
- ---
- last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
- last_mapped_at: 2026-10-19
- ---
- <!-- refreshed: 2026-10-19 -->

# Coding Conventions

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
