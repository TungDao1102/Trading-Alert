---
last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
last_mapped_at: 2026-10-19
---
<!-- refreshed: 2026-10-19 -->

# Testing Patterns

**Analysis Date:** 2026-10-19

## Test Framework

**Runner:**
- pytest 9 (`pytest>=9`, `pytest-asyncio>=1.4` in `[project.optional-dependencies].dev` of
  `pyproject.toml:35-41`).
- Config: `pyproject.toml` `[tool.pytest.ini_options]` (`pyproject.toml:47-56`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-q"
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
  "docker: needs a reachable Docker daemon and the built trading-alert images (cutover, backup drill, image checks)",
]
```

- `asyncio_mode = "auto"` means an `async def test_...` needs **no** decorator. 58 test modules
  contain async tests; 25 still carry an explicit `@pytest.mark.asyncio`.
- `addopts = "-q"` keeps local runs terse.

**Assertion Library:**
- Plain `assert` — pytest's builtin assertion rewriting. No `pytest-assert`/`unittest` style.
  Ruff's B011 is disabled for `tests/*` so `assert` statements are first-class
  (`pyproject.toml:79`).

**Mocking Library:**
- `respx>=0.23` for httpx-level interception (`pyproject.toml:38`).
- `monkeypatch` (pytest builtin) for environment, module attributes and entry points.

**Run Commands:**

```bash
uv sync --frozen --extra dev                            # env setup
uv run pytest -m "not docker"                           # the default suite CI runs
uv run pytest -m "not docker" -rs -p no:cacheprovider    # the exact CI invocation
uv run pytest -m docker                                 # docker-dependent suite
uv run pytest tests/test_risk_quantization.py::test_x   # single test
uv run ruff check && uv run ruff format --check        # lint gate
uv run mypy src                                         # type gate
uv lock --check                                         # lockfile gate
uv run python scripts/verify_decision_alignment.py all # docs<->code gate
```

Windows helpers live in `scripts/dev/` (`scripts/dev/README.md`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/test.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/migrate.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/clean.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/journal-report.ps1
```

## Two Marker Axes

| Axis | Command | Needs |
|---|---|---|
| default | `uv run pytest -m "not docker"` | nothing beyond the venv (PG tests skip locally) |
| docker | `uv run pytest -m docker` | a reachable Docker daemon + built images |

**`TRADING_CI_STRICT=1` turns every "missing infrastructure" skip into a FAILURE**, so a CI run
can never pass vacuously by skipping the infrastructure-bound tests. The switch lives in
`tests/infra_helpers.py`:

- `infra_skip(reason)` — skips the test, or `pytest.fail`s under strict mode
  (`tests/infra_helpers.py:43-50`).
- `module_skip(reason)` — the module-level counterpart; fails collection under strict mode so a
  missing tool cannot make a whole gate module vanish (`tests/infra_helpers.py:53-61`).
- `tests/conftest.py::pytest_runtest_setup` gates every `docker`-marked test on a reachable
  daemon (`tests/conftest.py:63-73`).
- CI sets `TRADING_CI_STRICT: "1"` globally in `.github/workflows/ci.yml:21-24`.
- `tests/test_test_infra.py` is the self-test of this mechanism — it proves the skip and the
  strict failure both fire.
- On Windows, `find_bash()` rejects the WSL launcher in `System32` and the Store alias in
  `Microsoft\WindowsApps`, and prefers Git-for-Windows bash (`tests/infra_helpers.py:64-81`).

## Test File Organization

**Location:** flat under `tests/` — no nested test packages, no `src` mirroring.

**Counts:** 334 `tests/test_*.py` files, of which **26 carry the `_pg.py` suffix** and require
PostgreSQL.

**Naming:**
- `tests/test_<area>_<subject>.py` — e.g. `tests/test_risk_quantization.py`,
  `tests/test_binance_usdm_signed_calls.py`, `tests/test_paper_runtime_loop.py`.
- `_pg.py` suffix = needs a live PostgreSQL: `tests/test_persistence_journal_pg.py`,
  `tests/test_execution_exactly_once_pg.py`, `tests/test_approval_replay_pg.py`.
- `tests/test_decision_alignment*.py` — the negative tests for the docs↔code gate.

**Shared helpers — `tests/support/` (11 modules):**

| Module | Purpose |
|---|---|
| `tests/support/ast_guards.py` | Reusable AST guards: `module_imports`, `forbidden_imports`, `float_constructor_calls`, `wall_clock_calls`, and the `WALL_CLOCK_CALLS` tuple |
| `tests/support/fake_binance_exchange.py` | Stateful Binance-semantics fake adapter (client-id reuse, SDK-shaped errors, `fill()`, `cancel()`, `place_market_close()`) |
| `tests/support/intent_store_fakes.py` | Fakes for the `ExecutionIntentStore` protocol |
| `tests/support/limits.py` | `TEST_ONLY_*` limit objects + a TOML writer for the loader tests |
| `tests/support/net_guard.py` | `forbid_network_and_sleep(monkeypatch)` — blocks sockets, DNS, `asyncio.sleep`, `requests` and the SDK client factory |
| `tests/support/pg_rows.py` | ORM row builders with GLOSSARY-valid defaults, `hexid(n)` |
| `tests/support/stream_sinks.py` | Sinks for stream events |
| `tests/support/userdata_frames.py` | Recorded user-data WebSocket frames |
| `tests/support/virtual_time.py` | `VirtualTime` — injected clock + virtual sleep with `advance()` |
| `tests/support/execution_limits.py` | Execution-limit key sets |
| `tests/support/__init__.py` | Package marker |

**Top-level helper modules in `tests/`** (not collected as test modules): `conftest.py`,
`infra_helpers.py`, `pg_support.py`, `docker_helpers.py`, `backtest_case_helpers.py`,
`backtest_plan_helpers.py`, `geometry_builders.py`, `paper_ws_fakes.py`,
`phase10_helpers.py`, `probe_fakes.py`, `shadow_fakes.py`, `userdata_fakes.py`.

**Structure:**

```
tests/
├── conftest.py            # shared fixtures + the docker-marker hook
├── infra_helpers.py       # infra_skip / module_skip / docker & bash probes
├── pg_support.py          # disposable PostgreSQL databases
├── docker_helpers.py      # compose-project helper for the docker suite
├── support/               # shared fakes, AST guards, virtual time
├── fixtures/              # golden data (see below)
└── test_*.py              # 334 flat test modules
```

## Test Structure

**Suite organization** — a typical module:

```python
"""PostgreSQL journal store: durable, append-only, replay-idempotent (Phase 17-08, D-10, F-412).

`PgJournalStore` is the production implementation behind every journal-first controller
(...). The behaviors pinned here:

  - round trip through `journal_to_row` / `journal_from_row`;
  - a replayed event (same id, same identity fields and payload) is a no-op ...

"""

from __future__ import annotations

import pytest
from src.persistence.journal import PgJournalStore

from tests.support.pg_rows import T0, T1, hexid, make_approval, make_plan, make_signal

# --------------------------------------------------------------------------- #

# Helpers.

# --------------------------------------------------------------------------- #

@pytest.fixture
def engine(pg_db: str) -> Iterator[Engine]:
    eng = make_sync_engine(pg_db)
    try:
        yield eng
    finally:
        eng.dispose()

def test_...() -> None:
    ...
```

(`tests/test_persistence_journal_pg.py:1-79`.)

**Patterns:**
- **Module docstring states the contract** — the behaviours pinned, the phase/plan and the
  D-/F- ids.
- **Section banners** separate the helpers from the tests:
  `# --------------------------------------------------------------------------- #`
  `# Helpers.`
  `# --------------------------------------------------------------------------- #`.
- **Typed test signatures**: `def test_x(tmp_path: Path) -> None:` — every test returns `None`
  and every parameter is annotated.
- **Fixture builders live at the top of the module** and take keyword-only arguments with
  deterministic defaults: `_make_candle(*, open_time, close="50000.00", high=None, ...)`
  (`tests/test_domain_boundary.py:36-61`), `_kline(*, open_ms, close_ms, symbol="BTCUSDT", ...)`
  (`tests/test_coverage.py:60-81`).
- **Parametrization is the default** for a table of cases — 294 `@pytest.mark.parametrize`
  decorators across the suite. Pattern:
  ```python
  @pytest.mark.parametrize(("code", "text"), OWNER_CASES, ids=OWNER_IDS)
  ```
  or `@pytest.mark.parametrize("family", sorted(FAMILIES))`.
- **Behavioural numbering in docstrings**: `"""Beh. 1: empty candle list yields NO_TRADE with
  NO_TRADE_REGIME, no exception."""` (`tests/test_domain_boundary.py:116`) — the behavior
  numbering matches the plan's behavior list.
- **Negative controls accompany every guard.** A test that asserts a guard fires must also
  prove the assertion is not vacuous. Example:
  `tests/test_domain_boundary.py:312-342` — a deliberately broken `_raising_evaluate` proves the
  never-raises assertion is sensitive to the crash bug class.
  The same rule is stated in `docs/testing/TESTING_STRATEGY.md:156-158` for the exactly-once
  and callback-replay suites.
- **Boundary cases are mandatory** per `docs/testing/TESTING_STRATEGY.md` §5: exact equality,
  just below, just above, support/resistance boundary, expiry instant, invalidation instant,
  insufficient warm-up.
- **Test-local imports** are used for a one-off import inside a test body
  (`tests/test_domain_boundary.py:319`, `tests/test_coverage.py:304`) — Ruff's isort keeps
  module-level imports clean.

## Shared Fixtures (`tests/conftest.py`)

| Fixture | Scope | Value / purpose |
|---|---|---|
| `golden_exchange_info` | session | Trimmed live-5 `/fapi/v1/exchangeInfo` snapshot, recorded 2026-09-19 (`tests/fixtures/exchange_info_sample.json`) |
| `live5_symbols` | session | The D-01 universe: `("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")` |
| `frozen_clock` | function | `datetime(2026, 9, 19, tzinfo=UTC)` — inject into anything that would call `datetime.now(timezone.utc)` |
| `fixture_path` | function | The `tests/fixtures` directory |
| `phase3_candles` / `phase3_parameters` / `phase3_expected_signals` / `phase3_expected_plans` | session | Phase-3 golden set |
| `phase4_candles` / `phase4_parameters` / `phase4_expected_features` / `phase4_expected_signals` / `phase4_expected_plans` | session | Phase-4 tracer slice |
| `phase5_parity_cases` / `phase5_frozen_clock` | session / function | Phase-5 parity cases (`input.json` + `expected.json` per case dir) and the frozen clock |
| `pg_db`, `pg_empty_db`, `pg_server_url`, `pg_template_name` | session / function | PostgreSQL fixtures, imported (not used) in `conftest.py:40-45` so pytest discovers them by name |
| `_restore_logging_state` | function, **autouse** | Restores structlog / root-logger / httpx log state after every test, because `configure_logging()` has global side effects (`tests/conftest.py:76-106`) |

## Mocking

**Framework:** `respx` for HTTP, hand-written fakes for SDK/stream boundaries, `monkeypatch`
for entry points.

**Patterns:**

*respx (httpx level):*

```python
with respx.mock(assert_all_called=False) as router:
    route = router.get("https://fapi.binance.com/fapi/v1/exchangeInfo").mock(
        return_value=httpx.Response(200, json=payload)
    )
    ...
```

(`tests/test_archive_ingest.py:167` and following; `assert_all_called=False` is used where a
route may legitimately not fire.)

*Hand-written SDK fake:*

```python
class _FakeRest:
    """Records every call so a test can assert which SDK method was reached."""

    def __init__(self, rows: list[list[Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def kline_candlestick_data(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("kline_candlestick_data", kwargs))
        return _FakeResponse(self._rows)
```

(`tests/test_binance_public.py:73-82`.) The fake **records its calls** so the test asserts
*which* SDK method was reached, not just the returned value.

*Stateful exchange fake:* `tests/support/fake_binance_exchange.py` models the one exchange
rule the audit turns on — a Binance client id is unique only among **open** orders, so a
FILLED or CANCELED order frees it. It raises the SDK's `BadRequestError` with code `-4116` for
a duplicate id while the first order is still open. Its kwargs are bound against the real
`BinanceUsdmAdapter` method signatures so the fake can never drift from the production surface.

*Network/sleep blocker:*

```python
from tests.support.net_guard import forbid_network_and_sleep
reached = forbid_network_and_sleep(monkeypatch)
...
assert reached == []
```

(`tests/support/net_guard.py:30-81`.) `socket.socket` is replaced by a subclass that refuses
every non-loopback connect (the Windows event loop's self-pipe is loopback and must keep
working), and every patched entry point raises `Forbidden` so a regression fails at once
instead of waiting or connecting.

*Virtual time:*

```python
vt = VirtualTime()
vt.advance(3600)
assert vt.sleeps == [1.0]
```

(`tests/support/virtual_time.py:34-82`.) `VirtualTime.sleep()` records the requested duration
and suspends until `advance()` moves virtual time past the deadline; it never calls
`asyncio.sleep`. `TEST_ONLY_VIRTUAL_START = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)` is
explicitly "TEST_ONLY and not a value of the project".

*Environment patching:* `monkeypatch.setenv` / `monkeypatch.delenv` for env-dependent
behaviour, and `monkeypatch.setattr` for module attributes — e.g.
`tests/test_test_infra.py:37-38` patches `infra_helpers.sys.platform` and `shutil.which`.

**What to mock:**
- HTTP transport (`respx`), the SDK client, WebSocket frames, the system clock, sleeps, the
  filesystem root (`tmp_path`), and the process environment.
- The *boundary* only — the pure core is never mocked; it is exercised with real inputs.

**What NOT to mock:**
- Never hit Binance or Telegram in unit tests. A live Binance credential must never be
  required to run the normal suite (`docs/testing/TESTING_STRATEGY.md:187`).
- Never mock the thing under test to make a guard pass — the negative-control rule above.
- Never mock the pure core's determinism; golden fixtures are the mechanism.
- Never mock the database in `_pg.py` tests: those tests exist to prove PostgreSQL's real
  constraint, trigger and race behaviour (`docs/testing/TESTING_STRATEGY.md:195-197`).

## Fixtures and Factories

**Golden fixture layout:**

```
tests/fixtures/
├── exchange_info_sample.json        # trimmed live-5 exchangeInfo
├── kline_page_sample.json           # one REST klines page
├── cutover/                         # compose override, Dockerfile, fake collector
├── phase3/ phase4/ phase5/ phase6/ phase7/ phase7.1/ phase8/ phase9/
├── phase10/ phase13/ phase14/ phase15/ phase18/
```

Each phase directory holds one directory per case with `input.json` + `expected.json`, e.g.
`tests/fixtures/phase14/hold_to_sl/`, `tests/fixtures/phase10/kill_passing_candidate/`.

**Hand-derived arithmetic is documented next to the data.** Every phase directory carries a
`DERIVATIONS.md` or `REGRESSION_SNAPSHOTS.md`. `tests/fixtures/phase14/DERIVATIONS.md` is the
model: it lists the common inputs, the formulas, and states the rule that **nothing in the
repository writes an `expected.json`** — the numbers were produced by standalone `python -c`
one-liners with `from decimal import Decimal` and nothing from `src/`, `tests/` or `scripts/`.
"Any change to a number needs a new derivation in this file first; do not regenerate an
expectation by running the simulator and pasting the result."

**Fixture generators — regenerate, never hand-type:**
- `scripts/gen_phase6_fixtures.py`
- `scripts/gen_phase14_fixtures.py`
- `scripts/_compute_phase4_fixtures.py`
- `scripts/_extend_phase4_candles.py`, `scripts/_regen_phase4_expectations.py`

`tests/test_phase14_fixture_generator.py` fails if the generator ever writes anything other
than `input.json`.

**Comparison semantics:** golden comparisons use Decimal equality for amounts and parsed
datetimes for times, so the scale spelling of a Decimal (`98` vs `98.00`) can never cause a
false failure (`tests/fixtures/phase14/DERIVATIONS.md:13-16`).

**Test data factories:**
- `tests/support/pg_rows.py` — `make_signal`, `make_plan`, `make_approval`, `hexid(n)`;
  GLOSSARY-valid defaults plus keyword overrides. Rows are built *directly* (not through the
  domain mappers) because several tests need values the domain constructors would refuse.
- `tests/support/limits.py` — `TEST_ONLY_*` values deliberately odd-looking so they cannot be
  mistaken for a chosen threshold; the three rate-limit values are pairwise different so a
  consumer reading the wrong field fails its test.

## Purity and Invariant Tests (the guard suite)

Purity is itself tested — a guard that silently stopped matching would leave every module test
green, so each guard has negative controls.

| Test | What it pins |
|---|---|
| `tests/support/ast_guards.py` | The shared guard primitives and the `WALL_CLOCK_CALLS` forbidden-spelling tuple |
| `tests/test_ast_guards.py` | Negative controls: 12 seeded clock-read spellings must be found, 5 near-misses must not be |
| `tests/test_domain_no_float.py` | Decimal-only invariant (D-12): `SCANNED_FILES` (explicit list) + `SCANNED_GLOBS = ("src/backtest/*.py", "src/paper/*.py", "src/research/*.py")`; `FLOAT_SCAN_EXCLUDED` needs a one-line reason per entry and the file must exist |
| `tests/test_analytics_purity.py` | Pure analytics modules: no float shapes, no ambient clock, no module-level randomness, no builtin `hash()`, no `total_seconds()`, no forbidden imports |
| `tests/test_backtest_purity.py` | Backtest package purity |
| `tests/test_domain_boundary.py` | Boundary determinism: empty, single-bar, warm-up-insufficient and gap-injected inputs each return an explicit invalid reason and never raise |
| `tests/test_no_lookahead.py` | No future information or unfinished candle may declare a signal |
| `tests/test_prefix_invariance.py` | Output for events at or before `T` is identical when arbitrary candles are appended after `T` |
| `tests/test_backtest_determinism.py` | Same input ⇒ byte-equivalent canonical output |
| `tests/test_candle_close_timing.py` | Signal absent before close, present exactly once after close |
| `tests/test_transitions.py` | Every enum member has a legal-transition entry; every unlisted pair raises `IllegalTransition` |
| `tests/test_no_unratified_defaults.py` | Scans `src/` and `scripts/` for a numeric constant assigned to a canonical limits key; production code may not import the `TEST_ONLY` values |
| `tests/test_registry_gate.py` | The registry loader is fail-closed: `UnregisteredParameterSet`, `ParameterSetMutated`, `RegistrySchemaMismatch`, `StrategyKeyOutsideRegistry` — never a silent fallback |

**The Decimal-only mechanism.** `tests/test_domain_no_float.py` walks the AST of every scanned
file and fails on: a `float(...)` call, a float **literal** (`0.5`), a `Decimal(<float
literal>)` shape (a silent binary-noise constructor), and a numpy floating type
(`np.float64`). The scanned set is an explicit file list **plus** globs, so a module added by
a later plan is covered without anyone remembering to list it (the "registration trap", D-26).
`FLOAT_SCAN_EXCLUDED` currently holds exactly one entry, `src/paper/shadow.py`, whose reason is
tenacity retry-wait arithmetic in seconds — no price, quantity or risk value is computed with
it. An exclusion needs a reason; weakening the scan instead is not allowed.

## PostgreSQL Tests

**`tests/pg_support.py` — disposable databases only.**

1. `pg_template_name` (session) builds **one** template database `t17_tmpl_<hex>_test` by
   running `alembic upgrade head` **in a subprocess** — never an ORM-metadata schema build
   (`tests/pg_support.py:159-168`).
2. `pg_db` (function) clones it per test with `CREATE DATABASE ... TEMPLATE ...` into a
   generated `t17_<hex>_test` database (`tests/pg_support.py:171-179`).
3. `pg_empty_db` (function) creates an **empty** database for migration-cycle tests
   (`tests/pg_support.py:182-190`).
4. Every generated database is dropped `WITH (FORCE)` at teardown.

A clone per test is **mandatory** because the append-only journal triggers make row cleanup
impossible.

**Name safety.** Generated names are validated against `^t17_(tmpl_)?[0-9a-f]+_test$` by
`assert_disposable_database_name` **before** they reach SQL, and quoted
(`tests/pg_support.py:46,58-65,89-112`). This is the only dynamic SQL in the project.

**`TEST_DATABASE_URL` names the SERVER** (the maintenance connection) and is never itself
altered, dropped, or used for test data. The role needs `CREATEDB`. It must name a throwaway
database whose name ends in `_test`; the CI form is
`postgresql+psycopg://trading:…@localhost:5432/trading_test`.

> ### ⚠️ `tests/pg_support.py` does NOT load `.env`
>
> pytest reads `TEST_DATABASE_URL` from the **PROCESS ENVIRONMENT only**. Nothing in the test
> path loads `.env` or `secrets.env`. Unset ⇒ the 26 `tests/*_pg.py` files **silently skip**
> locally. Under `TRADING_CI_STRICT=1` the same condition is a **FAILURE**
> (`tests/infra_helpers.py::infra_skip`, called from `require_test_database_url` at
> `tests/pg_support.py:50-55`). Set it in the shell before running the PG suite, e.g.
> `$env:TEST_DATABASE_URL = "postgresql+psycopg://…/trading_test"`.
>
> `tests/test_pg_fixture_guard.py` is the canary: it proves the strict-mode failure, the name
> guard, and that the fixtures never hand out the server's own database.

**Real PostgreSQL behaviour, not mocks:**
- Raw SQL that bypasses the repositories proves each constraint and trigger by its
  `diag.constraint_name`.
- `tests/test_persistence_migration_pg.py` diffs a migrated database with the ORM metadata
  (`compare_metadata` with `compare_type` and `compare_server_default`), reads partial-index
  predicates, CHECK literals and the 12 triggers from the catalog, and runs upgrade →
  downgrade → upgrade.
- Race and crash tests use separate engines released by a `threading.Barrier`; crash injection
  is store decoration with a `BaseException` subclass, so the manager (which catches only the
  typed persistence errors) never swallows it. A restart is a fresh engine, store and manager
  call on the same database.
- `tests/test_plan_hash_roundtrip_pg.py` stores 15 real planner plans and recomputes `plan_hash`
  from the read-back row.

## Decision-Alignment Gate

`scripts/verify_decision_alignment.py` is the single **read-only** command that checks
`AGENTS.md` and `docs/` against `.planning/PROJECT.md` and `.planning/research/STACK.md`.

```bash
uv run python scripts/verify_decision_alignment.py all
```

**Output contract:** one `PASS <gate>` or `FAIL <gate> :: <detail>` line per gate, then
`ALL_PASS <mode>` (exit 0) or `FAILED <n> gate(s)` (exit 1). An unknown or missing mode prints
a usage line to stderr and exits 2. A module that returns fewer gates than its
`EXPECTED_MIN` adds a `FAIL <module>-gate-count` line, so a **silently emptied gate module
cannot pass**; a module that raises is reported as `FAIL <module>-error :: <type>` (type name
only, never the message).

**Modes:** `protocol`, `params`, `universe`, `docs`, `glossary`, `reqs`, `decisions`, `all`.

**Gate modules** live in `scripts/decision_alignment/`: `protocol.py`, `params.py`,
`universe.py`, `ops_risk.py`, `exchange.py`, `authority.py`, `bookkeeping.py`
(`scripts/verify_decision_alignment.py:36-46`).

**Negative tests:** `tests/test_decision_alignment.py`,
`tests/test_decision_alignment_authority.py`, `tests/test_decision_alignment_bookkeeping.py`,
`tests/test_decision_alignment_exchange.py`, `tests/test_decision_alignment_ops_risk.py`,
`tests/test_decision_alignment_params.py`, `tests/test_decision_alignment_protocol.py`,
`tests/test_decision_alignment_universe.py`.

## CI Jobs

`.github/workflows/ci.yml` — four parallel jobs on `ubuntu-24.04` for every push and pull
request to `master`. Every action is pinned to a commit SHA with its version in a trailing
comment; `uv` is pinned to `0.12.21`; Python comes from `.python-version`. `fetch-depth: 0` is
required because the decision-alignment tests read pre-change text via `git`.

| Job | Steps |
|---|---|
| `test` | `uv sync --frozen --extra dev`; `uv run pytest -m "not docker" -rs -p no:cacheprovider` with `TEST_DATABASE_URL` set and `TRADING_CI_STRICT=1`. Service: `postgres:17.11-bookworm` **digest-pinned** with a `pg_isready` health check. |
| `lint` | `uv sync --frozen --extra dev`; `uv lock --check`; `uv run ruff check`; `uv run ruff format --check` |
| `types` | `uv sync --frozen --extra dev`; `uv run mypy src` |
| `docker` | `cp .env.example .env` + `chmod 600 .env`; `docker compose config -q`; `docker compose --profile paper --profile live --profile ops config -q`; `shellcheck -x -P SCRIPTDIR deploy/*.sh`; `docker compose --profile ops build`; `uv run pytest -m docker -rs -p no:cacheprovider` |

There is **no** `continue-on-error` and no failure-suppression idiom anywhere in CI.

**Other workflows:**

- `.github/workflows/registry-gate.yml` — re-hashes every `params/**/*.toml` against the pins in
  `tests/fixtures/phase4/parameters.json` (an unpinned file fails closed: "no pinned hash —
  register it"); then runs the decision-alignment gates read-only; then runs the fail-closed
  negative tests with `TRADING_CI_STRICT=1`:
  `tests/test_registry_gate.py tests/test_registry.py tests/test_kill_gate_docs.py
  tests/test_kill_gate_clock.py tests/test_research_gate_negative.py tests/test_decision_alignment*.py`.
- `.github/workflows/research-gate.yml` — the three-witness freeze check on
  `docs/research/RESEARCH_PROTOCOL.md`: (1) the header reads `Status: FROZEN` and carries a
  `Frozen on` date; (2) `docs/DOC_STATUS.md` lists the protocol at exactly the header's
  version `V`; (3) `docs/DECISIONS.md` has a `protocol vV frozen` row. Plus the
  identity-tuple check (the seven fields `strategyVersion`, `parameterSetId`,
  `parameterSetHash`, `dataSnapshotId`, `dataManifestHash`, `codeVersion`, `costModelHash`) and
  the registry-path tripwire (parameter-set files must live under `docs/research/registry/`).
- `.github/workflows/paper_freeze_check.yml` — the hourly soak-host cron (minute 34) that
  re-reads the registry against the committed pinned epoch and opens a new epoch on a diff;
  exit code 3 (`REGISTRY_DIFF`) fails the workflow loudly.

`tests/test_deploy_workflows.py` and `tests/test_deploy_docs.py` assert the **text** of these
workflow files, so the pins, the marker split and the commands cannot drift silently.

## Coverage

**Requirements:** none enforced. There is no `pytest-cov`, `coverage` or `pytest-cov`-style
dependency in `pyproject.toml`, no `--cov` flag in any CI job, and no coverage threshold.

**Do not confuse** `tests/test_coverage.py` with code coverage — it tests the **data**
coverage CLI and the DuckDB coverage views (`candles_v1`, `coverage_v1`, `oi_coverage_v1` in
`src/data/coverage.py`'s checked-in SQL file) over Parquet + PostgreSQL metadata.

Coverage is instead asserted **behaviourally**: every behaviour in a plan has a test, every
guard has a negative control, and every gate has a fail-closed test. That is the project's
substitute for a coverage percentage.

## Test Types

**Unit tests:**
- Flat `tests/test_*.py` (308 files without the `_pg` suffix). No network, no database, no
  Binance account. Examples: `tests/test_core_features.py`, `tests/test_risk_quantization.py`,
  `tests/test_registry.py`, `tests/test_domain_no_float.py`.

**Integration tests:**
- PostgreSQL: the 26 `tests/*_pg.py` files.
- HTTP: `tests/test_archive_ingest.py` (respx, zips built in-test with `zipfile`).
- WebSocket / stream: `tests/test_userdata_*.py`, `tests/test_userdata_recorded_frames.py`,
  `tests/test_userdata_replay.py` (recorded frames from `tests/support/userdata_frames.py`).
- CLI: `tests/test_analytics_cli.py`, `tests/test_backfill_cli.py`, `tests/test_coverage.py`
  (subprocess `python -m src.data.coverage`).
- Docs↔code: `tests/test_decision_alignment*.py`.

**E2E / container tests:**
- `tests/test_docker_cutover.py`, `tests/test_docker_backup_drill.py`,
  `tests/test_docker_backup_remote.py`, `tests/test_docker_image.py` — all marked
  `@pytest.mark.docker` and driven by `tests/docker_helpers.py` (a throwaway compose project
  with a generated env file of random credentials, always torn down with `down -v`).

**Property-style tests:**
- `tests/test_geometry_property.py`, `tests/test_sl_loss_property.py`,
  `tests/test_geometry_census.py`.

## Common Patterns

**Async testing:**

```python

# asyncio_mode = "auto" — no decorator needed.

async def test_paper_loop_consumes_one_queue_item() -> None:
    ...
```

An explicit `@pytest.mark.asyncio` is acceptable where the module wants to be self-documenting
(25 occurrences), but do not add it by default.

**Error testing:**

```python
with pytest.raises(UnregisteredParameterSet):
    load_parameter_set("trend-pullback", "does-not-exist")
```

(`tests/test_registry_gate.py:46-47`.) Use the **typed** domain exception, and add
`match="..."` when the message carries a contract detail:
`with pytest.raises(ValueError, match="non-empty")` (`tests/test_domain_boundary.py:356`).

**Fail-closed assertion:**

```python
assert result.is_no_trade
assert result.reason_code == "WARMUP_INSUFFICIENT"
```

The reason code is the assertion — a NO_TRADE without a canonical reason is a failure.

**Clock injection:**

```python
def test_...(frozen_clock: datetime) -> None:
    ...  # frozen_clock == 2026-09-19T00:00:00Z
```

or `VirtualTime` for anything that also sleeps.

**Golden comparison:**

```python
assert result.quantity == Decimal("1.234")     # Decimal equality, not string equality
assert result.close_time_utc == datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
```

**Isolation:**
- Every test gets a fresh `pg_db` clone — no shared mutable database state.
- The autouse `_restore_logging_state` fixture keeps structlog / root-logger / httpx levels
  from leaking between tests.
- `tmp_path` (pytest builtin) is the filesystem root for Parquet/JSON scratch.

**Test names read as specifications:**
`test_empty_input_returns_explicit_invalid_reason`,
`test_verify_on_mutated_copy_raises_parameter_set_mutated`,
`test_float_scan_exclusions_are_justified_and_exist`,
`test_paper_shadow_messages`,
`test_funding_jitter_is_not_a_gap_but_a_missing_tick_is`.

---

*Testing analysis: 2026-10-19*
