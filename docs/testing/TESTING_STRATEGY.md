# Testing Strategy

## 1. Purpose

Provide deterministic tests for signal logic, timing, no-lookahead behavior, execution simulation, and state transitions.

## 2. Golden fixture model

Strategy tests must use small, human-readable fixtures.

Recommended layout:

```text
tests/fixtures/strategy/
  trend-pullback-v1/
    case-001/
      candles.csv
      parameters.json
      expected-signals.json
      expected-trade-plans.json
```

### `candles.csv`

Minimum columns:

```text
symbol,timeframe,open_time_utc,open,high,low,close,volume
```

### `expected-signals.json`

Contains only signals expected at closed-candle boundaries.

### `expected-trade-plans.json`

Contains exact Entry/SL/TP/invalidation/expiry for the fixture.

## 3. No-lookahead tests

For a prefix of candles ending at time `T`:

```text
run(prefix through T)
```

Then append arbitrary candles after `T` and run again.

The output for all events at or before `T` must be identical.

This is a mandatory invariant.

## 4. Candle-close timing tests

A strategy may inspect an unfinished candle only when explicitly classified as preview data.

For live trading decisions:

```text
kline closed = required
```

Test both:

- signal absent before close;
- signal appears exactly once after close when conditions are met.

## 5. Boundary tests

Every rule must have tests around:

- exact equality;
- just below threshold;
- just above threshold;
- exact support/resistance boundary;
- expiry timestamp;
- invalidation timestamp;
- insufficient warm-up history.

## 6. Determinism tests

Same:

```text
market data
strategyVersion
parameterSet
account state
```

must produce byte-equivalent canonical decision output.

## 7. Execution simulation tests

Cover:

- limit touched but not filled under the declared fill model;
- full fill;
- partial fill;
- entry expiry;
- invalidation before fill;
- stop before TP;
- TP before stop using finer data;
- both touched in one strategy candle;
- fee/funding/slippage application.

## 8. State-machine tests

At minimum validate invalid transitions such as:

```text
SignalStatus:    EXPIRED → APPROVED
TradePlanStatus: EXPIRED  → APPROVED
TradeStatus:     CLOSED   → NEW PROTECTIVE ORDER
```

unless an explicit reconciliation workflow authorizes the transition.

The order state machine has no approval state — order transitions start at `PLANNED` per `GLOSSARY.md` §5 and `EXECUTION_SPEC.md` §3. Approval is a signal/plan transition, not an order transition.

`TradePlanStatus` has no `CANCELED` member (the terminal states are `EXPIRED`, `INVALIDATED` and `SUPERSEDED`), so an example must name a real source state; earlier drafts of this list used one that does not exist in the enum (Phase 17, D051).

Implemented checks (Phase 17): `tests/test_transitions.py` proves that every enum member has an entry in the legal-transition tables of `src/domain/transitions.py`, that every listed pair passes and every unlisted pair raises `IllegalTransition` (exhaustive cross-product), that the terminal states are exactly the states without successors, and that `GLOSSARY.md` section 11 (the documented tables) equals the Python tables. `tests/test_persistence_transitions_pg.py` runs the repositories against PostgreSQL: an illegal transition writes nothing, two concurrent writers cannot both win, and `test_database_refuses_every_terminal_state_exit_and_accepts_every_legal_move` proves the terminal-status triggers of migration 0004 agree with `TERMINAL_STATES` for every kind and every state. The tables themselves are an auto-mode default awaiting user confirmation (D051).

## 9. Quantization fixtures

Include symbols with different price/quantity steps.

Expected outputs must include:

```text
raw_quantity
rounded_quantity
risk_before_rounding
risk_after_rounding
quantization_decision
```

A rounded-up quantity is a test failure.

## 10. Callback idempotency tests

Send the same Telegram approval callback multiple times.

Expected behavior:

```text
first callback  → APPROVED + at most one execution intent
replay callback → return current approval/order state
```

No duplicate order is permitted.

Implemented checks (Phase 17, all on PostgreSQL, see section 12.1):

- `tests/test_execution_exactly_once_pg.py` (SC4): exactly one `place_entry` and one ENTRY intent row when the first entry is still open, FILLED or CANCELED, each in the same process and across a restart on a fresh engine, with the stored outcome replayed and zero adapter calls on the second call. The fake exchange (`tests/support/fake_binance_exchange.py`) models Binance's rule that a client id is unique only among open orders, so a filled or canceled entry frees its id. Two-thread races (a `threading.Barrier` releases both callers at the same instant, with separate engines) prove one winner, and a 60-round hammer proves the loser never raises. Negative controls prove the harness would catch a regression: a store that never remembers places two entries after a fill and after a cancel, the fake rejects a duplicate with `-4116` only while the first entry is open, and two overlapped callers without a durable row both reach the exchange.
- `tests/test_execution_write_ahead_pg.py`: a second connection reads the row state at each adapter call (ENTRY SENT at `place_entry`, ENTRY ACKED and STOP_LOSS SENT at `place_algo_protective`), and crash injection after each of consume, entry sent, entry result, stop-loss intent, stop-loss sent and stop-loss result leaves a readable row and a restart never places a second order.
- `tests/test_approval_replay_pg.py` and `tests/test_callback_redelivery_pg.py`: the real callback dispatch wired to the PostgreSQL approval and journal stores feeds the real execution path; a replayed APPROVE after a restart, after expiry and raced by two threads places one entry; a wrong token for the same short id is rejected and never sees the stored outcome; the same `callback_query.id` delivered three times leaves one receipt row and one resolution row; negative controls (a forgetful store, a forgetful decision store) show the assertions are not vacuous.
- `tests/test_persistence_approvals_pg.py`: one decision per plan is database-enforced, including against raw SQL that bypasses the repository.

## 11. Reconciliation tests

Simulate:

- missed user-data event;
- unknown order on exchange;
- local order missing on exchange;
- position without protective stop;
- protective orders remaining after position closes.

System must enter the documented reconciliation/safe state.

Implemented checks for the persisted-intent part (Phase 17): `tests/test_intent_recovery.py` and `tests/test_intent_recovery_pg.py` prove that restart recovery resolves in-flight intents by deterministic-id query only (found: ACKED; young and absent: REJECTED; probe error, indeterminate answer or absent at or past the 3-day window: UNKNOWN), that anything unresolved enters SAFE_MODE `UNRESOLVED_EXECUTION_INTENT` exactly once, and that `place_entry` and `place_algo_protective` are never called by recovery. `tests/test_controller_rehydrate.py` and `tests/test_system_state_pg.py` prove that SAFE_MODE, live enablement and kill-gate state written through one engine are restored through a fresh engine, and that malformed persisted state fails closed. The reconciliation job itself (user-data stream, divergence rules, SAFE_MODE exit) is tested in later phases.


## 12. Python test/tooling conventions

The default test runner is `pytest`. Strategy and domain tests should remain runnable without a Binance account, network access, or a database.

Use:

- Ruff for formatting/linting;
- static type checking as configured in the repository;
- deterministic fixture files under `tests/fixtures`;
- explicit integration-test markers for Binance/Testnet/network tests.

A live Binance credential must never be required to run the normal test suite.

### 12.1 PostgreSQL tests (Phase 17, D051)

Tests that need PostgreSQL follow one policy:

- Disposable databases only. `tests/pg_support.py` builds one session-scoped template database named `t17_tmpl_<hex>_test` by running `alembic upgrade head` in a subprocess (never `create_all` or an ORM-metadata schema build), clones it per test with `CREATE DATABASE ... TEMPLATE ...` into a generated `t17_<hex>_test` database, and drops every generated database `WITH (FORCE)` at teardown. A clone per test is mandatory because the append-only triggers make row cleanup impossible. The fixtures are `pg_db` (migrated clone) and `pg_empty_db` (empty database for migration tests); `run_alembic` runs the migrations.
- `TEST_DATABASE_URL` names the server and is used only as the maintenance connection; the fixtures never alter, drop or write test data into the database the URL points at. Generated names are validated against `^t17_(tmpl_)?[0-9a-f]+_test$` before they reach SQL, so a name that does not match is refused. The older `tests/test_analytics_store.py` PostgreSQL test additionally requires the URL's own database name to end in `_test`, so the convention is a URL ending in `/trading_test` (the form CI uses); the credential belongs in the environment only and never in a committed file.
- A missing `TEST_DATABASE_URL` skips loudly in a local run and FAILS under `TRADING_CI_STRICT=1` (`tests/infra_helpers.py` `infra_skip`), the flag CI already sets (`RUNBOOK.md` section 18). `tests/test_pg_fixture_guard.py` is the canary: it proves the strict-mode failure, the name guard and that the fixtures never hand out the server's own database. No new environment variable and no new CI service exist for this policy; the existing PostgreSQL 17.11 service container is reused.
- Schema checks use real PostgreSQL behaviour: raw SQL that bypasses the repositories proves each constraint and trigger by its constraint name (`diag.constraint_name`); `tests/test_persistence_migration_pg.py` diffs a migrated database with the ORM metadata (`compare_metadata` with `compare_type` and `compare_server_default`, four sensitivity tests proving the diff is not vacuous), reads partial-index predicates, CHECK literals and the 12 triggers from the catalog, runs upgrade, downgrade and upgrade, and upgrades a 0003 database with a row in every table.
- Race and crash tests use separate engines released by a `threading.Barrier`, crash injection by store decoration with a `BaseException` subclass (`SimulatedCrash`; the manager catches only the typed persistence errors, so a crash is never swallowed), and a restart is a fresh engine, store and manager call on the same database. Every such test has a negative control.
- Round-trip tests use real planner outputs, not hand-made samples: `tests/test_plan_hash_roundtrip_pg.py` stores 15 planner plans (five phase 4 windows at three account sizes) and recomputes `plan_hash` from the read-back row.

The CI test job runs the whole `pytest -m "not docker"` battery with `TEST_DATABASE_URL` and `TRADING_CI_STRICT=1`, so none of the Phase 17 PostgreSQL modules can skip silently there. On a development machine without PostgreSQL they skip, and the rest of the suite stays runnable without a database.

### 12.2 Owner-run Demo scenario suite (Phase 25, D-03)

The scenarios that need the Binance Demo account live in `tests/demo/` and carry the `demo` marker (registered in `pyproject.toml`). They are a separate selection that CI and agents cannot run by accident:

- `pytest_collection_modifyitems` in `tests/conftest.py` adds a plain skip to every `demo` item unless `-m` names `demo` (not `not demo`) AND `TRADING_DEMO_RUN=1`. `-m "not docker"`, the CI and AGENTS.md command, does not exclude `demo`, so without the hook those tests would run there and try signed calls. The hook uses a plain skip, never `infra_skip`, so the items stay SKIPPED under `TRADING_CI_STRICT=1`. `tests/test_demo_marker_guard.py` proves it with a hook unit test, a strict-mode child run of `tests/demo`, and an AST scan that every `test_*` function under `tests/demo` carries the mark (with a seeded negative control).
- Owner command (PowerShell): `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s`. One Demo account and one listenKey exist, so the suite never runs in parallel.
- Session guard: `tests/demo/conftest.py` calls `tests/support/demo_guard.py` `assert_demo_run_environment`, which refuses any `BINANCE_LIVE_*` name, an xdist worker, a `TRADING_DEMO_RUN` other than `1` and any environment `scripts/demo_rehearsal.py` `admit_smoke_environment` does not admit (non-DEMO mode). Refusals name variables, never values (`tests/test_demo_env_guard.py`).
- Evidence labels for every step of a Demo run: `SYNTHETIC` (fakes), `DEMO_OBSERVED` (seen on the Demo exchange), `DEMO_FAULT_INJECTED` (a fault injected on purpose, never reported as exchange behaviour) and `NOT_OBSERVED` (not seen; stays open).
- Agents run only the fake twins of the scenarios (the default suite). `pytest -m demo` is owner-only, like every `--execute` script.
