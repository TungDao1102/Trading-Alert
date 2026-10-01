---
phase: 17-operational-persistence-layer
plan: 10
subsystem: database
tags: [postgresql, state-machine, transitions, precision, plan-hash, round-trip, sqlalchemy, pytest]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01 OperationalDatabase/make_sync_engine/pg_db fixtures and typed errors; plan 02 terminal-status triggers, FKs and unique indexes; plan 03 transition tables; plan 05 quantize_for_storage and the canonical-text plan hash; plan 08 PgJournalStore.append(tx, event)"
provides:
  - "src/persistence/entities.py PgTradingEntityStore: insert/get for Signal, TradePlan, Order, Position; transition_signal / transition_trade_plan / transition_order / transition_position; record_fill / list_fills_for_order; every method takes an optional tx"
  - "In-transaction DOMN-04 enforcement: row lock, idempotent no-op on unchanged status, assert_transition, conditional UPDATE with timestamp side effects from the injected now_utc"
  - "Store-boundary PrecisionError guard for every NUMERIC column (names table.field, never the value)"
  - "tests/test_persistence_transitions_pg.py (65 tests), tests/test_persistence_roundtrip_pg.py (7), tests/test_plan_hash_roundtrip_pg.py (22)"
affects: [17-11, 17-12, 17-14, phase-18, phase-19, phase-20]

actuals:
  tokens: 18800
  tasks: 2
  commits: 3
plan_head_before: 504244e0f7c4375f2dd27bbf23d6d931c5f7276a
plan_head_after: 823c699963061a9438a65ece3f1f40081ef9fbd4

tech-stack:
  added: []
  patterns:
    - "A small frozen _Spec[E, R] (PEP 695 generic) binds each entity to its row class, mappers and the columns that evolve after insertion; the four transition methods stay explicit so each one calls assert_transition itself"
    - "Idempotent insert = INSERT ... ON CONFLICT (pk) DO NOTHING RETURNING, then a re-read compared on the non-evolving columns; FK violation -> ParentRowMissing, other unique violation -> RowConflict"
    - "Precision guard is generic: after the mapper builds the row, every Decimal in a Numeric column must equal quantize_for_storage(value)"

key-files:
  created:
    - src/persistence/entities.py
    - tests/test_persistence_transitions_pg.py
    - tests/test_persistence_roundtrip_pg.py
    - tests/test_plan_hash_roundtrip_pg.py
  modified: []

key-decisions:
  - "Idempotent insert compares only the columns that do not evolve after insertion (Signal: all but status and invalidated_at_utc; TradePlan: all but status; Order: all but local_status, exchange_status, exchange_order_id, updated_at_utc, canceled_at_utc; Position: all but quantity, prices, PnL, updated_at_utc, closed_at_utc, status), the same rule 17-09 used for approvals, so replaying the original insert after the entity advanced is a no-op and a different entity under the same id is a RowConflict; fills are compared in full"
  - "A transition of a row that does not exist raises RowConflict (the 17-09 precedent), not a new error class, because errors.py is outside this plan's files"
  - "transition_trade_plan accepts now_utc for a uniform signature but ignores it: TradePlan has no transition timestamp"
  - "Non-finite Decimals (NaN, Infinity) are a PrecisionError too, since quantize_for_storage cannot store them"
  - "Check-constraint violations propagate as the raw IntegrityError; only foreign key and unique violations are translated"

patterns-established:
  - "Any later writer of these five tables (Phase 18 stream, Phase 19 execution, Phase 20 reconciler) goes through this store; the DB triggers are the second line of defence, proven equal to transitions.TERMINAL_STATES"

requirements-completed: [DOMN-01, DOMN-04]

coverage:
  - id: D1
    description: "PgTradingEntityStore persists Signal, TradePlan, Order, Fill and Position through the existing mappers; every status change takes a row lock, treats an unchanged status as a no-op, calls assert_transition and applies a conditional UPDATE; IllegalTransition writes nothing and two concurrent writers cannot both win"
    requirement: DOMN-04
    verification:
      - kind: integration
        ref: "tests/test_persistence_transitions_pg.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "For every kind and every state, the PostgreSQL terminal trigger refuses every exit from a state in transitions.TERMINAL_STATES and accepts every legal move out of a non-terminal state (parity)"
    requirement: DOMN-04
    verification:
      - kind: integration
        ref: "tests/test_persistence_transitions_pg.py#test_database_refuses_every_terminal_state_exit_and_accepts_every_legal_move"
        status: pass
    human_judgment: false
  - id: D3
    description: "A Decimal with 19 fractional digits (any NUMERIC field of the five entities) is refused with PrecisionError before PostgreSQL could round it; 18 digits round-trip exactly; integer overflow is still a DataError"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_transitions_pg.py#test_nineteen_fractional_digits_are_refused_before_postgres_can_round"
        status: pass
      - kind: integration
        ref: "tests/test_plan_hash_roundtrip_pg.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "plan -> row -> PostgreSQL -> row -> plan reproduces the stored plan_hash for 15 real planner outputs (five phase 4 windows x three account sizes), and the three plans pinned in expected_plans.json have their pinned hashes"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_plan_hash_roundtrip_pg.py#test_real_plan_round_trips_and_reproduces_its_plan_hash"
        status: pass
      - kind: integration
        ref: "tests/test_plan_hash_roundtrip_pg.py#test_planner_hashes_equal_the_pinned_phase4_fixture"
        status: pass
    human_judgment: false
  - id: D5
    description: "Seeded property (random.Random(17), 25 cases each) shows every Signal, TradePlan, Order, Fill and Position mapper pair round-trips through real PostgreSQL"
    requirement: DOMN-01
    verification:
      - kind: integration
        ref: "tests/test_persistence_roundtrip_pg.py"
        status: pass
    human_judgment: false
  - id: D6
    description: "An order transition and its journal event commit in one unit of work, or neither does"
    requirement: DOMN-04
    verification:
      - kind: integration
        ref: "tests/test_persistence_transitions_pg.py#test_order_transition_and_journal_event_roll_back_together"
        status: pass
    human_judgment: false

duration: 25 min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 10: Trading Entity Repositories Summary

**`PgTradingEntityStore` persists the five remaining entities with the DOMN-04 state machines enforced inside a locked write transaction, refuses any Decimal NUMERIC(38,18) would round, and a real-PostgreSQL battery proves plan_hash survives the round trip.**

## Performance

- **Duration:** about 25 min (about 12.5 of them the full-suite run)
- **Started:** 2026-10-01T15:31:16Z, **Completed:** 2026-10-01T15:55Z
- **Tasks:** 2 (both TDD)
- **Files:** 4 created, 0 modified

## Accomplishments

- `PgTradingEntityStore` (`src/persistence/entities.py`): `insert_*`, `get_*` and `transition_*` for Signal, TradePlan, Order and Position, plus `record_fill` and `list_fills_for_order`. Every method takes an optional keyword `tx`; without it the method opens its own transaction, with it the work joins the caller's unit of work (D-03).
- Transitions: `SELECT ... FOR UPDATE`, unchanged status returns the stored entity untouched, otherwise `assert_transition` then a conditional `UPDATE ... WHERE <status column> = old`, `rowcount` must be 1. Side effects from the injected `now_utc`: Signal INVALIDATED sets `invalidated_at_utc`; Order CANCELED sets `canceled_at_utc`; Position CLOSED sets `closed_at_utc`; Order and Position moves set `updated_at_utc`. A concurrent-writer test (two engines, a barrier, NOTIFIED -> APPROVED versus NOTIFIED -> SKIPPED_USER) shows exactly one wins and the other gets `IllegalTransition`.
- Precision guard: after the mapper builds the row, every Decimal in a `Numeric` column must equal `quantize_for_storage(value)`, otherwise `PrecisionError("<table>.<field>: more than 18 fractional digits")`. The guard is generic, so it covers all 8 plan columns, 3 order, 5 position and 5 fill NUMERIC fields; each is tested separately.
- Database cross-check (D-20): the six terminal-status triggers of migration 0004 were compared with `transitions.TERMINAL_STATES` on a real server, exhaustively (every terminal state to every other state of the enum must be refused; every legal move out of every non-terminal state must pass). The sets match exactly, so no migration change was needed; the Phase 17 plan-02 note that the trigger sets were research drafts is closed: they equal the Python tables.
- Real plan hashes: five phase 4 windows (trend-pullback from `candles.csv`, breakout-retest and range-mr in both directions) at three account sizes (15 plans, quantities with up to 18 fractional digits) go through insert and read-back; `_plan_hash` recomputed from the read-back fields equals the stored hash every time, and the three plans pinned in `expected_plans.json` still have their pinned hashes. Plan 05's quantization held; no defect to report.
- Seeded property: 25 cases per entity from `random.Random(17)` covering every enum member, 0 to 18 fractional digits, a zero order quantity, a signed position quantity and PnL, a full-width NUMERIC(38,18) boundary price, `None` and set values for every nullable, and microsecond UTC datetimes.

## Task Commits

1. Task 1 RED: `dbb1d30` test(17-10): RED for PgTradingEntityStore transitions, precision guard, journal atomicity and DB terminal parity (collection failed with `ModuleNotFoundError: src.persistence.entities`)
2. Task 1 GREEN: `da71dba` feat(17-10): PgTradingEntityStore with in-transaction transitions, precision guard and idempotent inserts
3. Task 2: `823c699` test(17-10): seeded mapper round-trip property and real-planner plan_hash reproduction on PostgreSQL

Task 2 has no separate RED commit: as the plan states, its modules exercise the Task 1 store and plan 05's quantization, so they pass once those exist. They were proved non-vacuous by mutation instead (see Verification).

## Verification (real runs)

All PostgreSQL runs used the dev server with `TEST_DATABASE_URL` set inline (credential not written to any file).

- Task 1 verify: `TRADING_CI_STRICT=1 pytest tests/test_persistence_transitions_pg.py -x -q -rs` exit 0, 65 passed, no SKIPPED line. `mypy src`: no issues in 129 source files. `ruff check src tests`: all checks passed. `ruff format --check src tests`: 294 files already formatted.
- Task 2 verify: `TRADING_CI_STRICT=1 pytest tests/test_persistence_roundtrip_pg.py tests/test_plan_hash_roundtrip_pg.py -x -q -rs` exit 0, 29 passed (7 + 22), no SKIPPED line.
- Mutation checks (sources restored, `git status` clean afterwards): disabling the `quantized != value` comparison made the 19-digit tests fail in both modules (all fill, plan, order and position cases); changing `position_to_row` to write `entry_price` into `break_even_price` made `test_position_round_trips_through_postgresql` fail.
- Acceptance greps: `grep -c "assert_transition(" src/persistence/entities.py` prints 4; `with_for_update` / `FOR UPDATE` present; `PrecisionError` present; `random.Random(17)` present in `tests/test_persistence_roundtrip_pg.py`; `_plan_hash` present in `tests/test_plan_hash_roundtrip_pg.py`.
- Plan-level verification, full suite: `pytest -m "not docker"` with `TEST_DATABASE_URL` set (so PG tests did not skip) exit 0 in about 12.5 min, no `F`/`E` markers. The repository's `addopts = -q` plus `-q` suppresses the summary line, so a pass count was not captured; the only non-dot markers are the skips (about 10, the same pre-existing set recorded in 17-05: symlinks on Windows, NTFS POSIX modes, `shellcheck` absent). That run was not under `TRADING_CI_STRICT=1` (those pre-existing skips would fail it); the three modules of this plan were run separately under strict with zero skips.

## Deviations from Plan

None - plan executed as written. Two judgment calls inside the plan's latitude, both recorded under key-decisions: replay-after-advance of an insert is a no-op (evolving columns excluded from the comparison), and a transition of a missing row raises `RowConflict`.

## Known Stubs

None.

## Threat Flags

None. T-17-26 mitigated (row lock, `assert_transition`, conditional UPDATE in one transaction, DB terminal triggers, exhaustive parity test, race test). T-17-27 mitigated (`PrecisionError` before insert, real-planner hash round trip). T-17-SC: no packages installed.

## Issues Encountered

None blocking. For Phase 18+ authors (not bugs of this plan):

- A failed statement inside a caller-owned `tx` leaves that transaction aborted (PostgreSQL semantics); callers must let the exception propagate so the unit of work rolls back. Documented in the module docstring.
- Position evolution beyond status (quantity, prices, PnL updated by reconciliation) has no store method yet; `insert_position` deliberately ignores those columns on replay, so a Phase 20 `update_position_snapshot` can be added without changing insert semantics.
- Order `exchange_status` / `exchange_order_id` updates (Phase 18/19) likewise have no method here; only `local_status` transitions were in scope.

## Next Phase Readiness

Plan 17-11 and later plans can call `PgTradingEntityStore` with `tx` to compose order transitions with `PgJournalStore.append` and `PgExecutionStateStore`. The transition tables remain the Phase 17 auto-mode default awaiting user confirmation (D051); the database triggers and the repository now both follow `src/domain/transitions.py`.

## Self-Check: PASSED

- `src/persistence/entities.py`, the three test modules and this SUMMARY exist; commits `dbb1d30`, `da71dba`, `823c699` exist; measured commit count 3 from the recorded plan head `504244e`.
