---
phase: 03-domain-registry-fixtures
plan: "04"
subsystem: database
tags: [orm, alembic, migration, mappers, tdd, parity-gate, domain-mirror]

# Dependency graph
requires:
  - phase: 03-01
    provides: src/domain package skeleton, Signal entity, SignalRow ORM mirror, signal mappers
  - phase: 03-02
    provides: TradePlan, Approval, Order, Fill, Position, JournalEvent frozen dataclasses
provides:
  - Six new ORM tables (TradePlanRow, ApprovalRow, OrderRow, FillRow, PositionRow, JournalEventRow)
  - Total to_row/from_row mapper pairs for all seven entities
  - Migration 0002_domain_registry with seven create_table blocks
  - Mapper round-trip test suite (25 tests)
  - Offline parity gate green across all seven tables
affects:
  - Phase 4 (Pure Core) consumes all seven domain entities via mappers
  - Phase 5 (Risk) consumes TradePlan + Position via mappers
  - Phase 6 (Backtest) consumes TradePlan + Fill + Position via mappers
  - Phase 8 (Approval) consumes Approval + Order via mappers
  - Phase 10 (Journal) consumes JournalEvent via mappers

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
# Same estimateTokens scale (chars/4 over the realized diff), never a harness token count.
actuals:
  tokens: 44000
  tasks: 3
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - single-Base + TIMESTAMPTZ + NUMERIC(38,18) + JSON-as-TEXT convention
    - content-hash PKs with no auto-increment (D-03)
    - explicit status columns; nullable timestamps only for "transition never happened" (D-11)
    - total mappers with Enum(value) coercion at boundary (D-10)
    - CapturingSession snapshot pattern for SQLite NUMERIC lossiness
    - offline parity gate (scripts/check_migration_parity.py)

key-files:
  created:
    - src/db/alembic/versions/0002_domain_registry.py
    - tests/test_domain_mappers.py
  modified:
    - src/db/models.py
    - src/db/mappers.py

key-decisions:
  - "D-02: Seven ORM tables on the existing single Base; no separate Base per entity"
  - "D-03: All PKs are content-hash IDs (String(128)); no auto-increment anywhere"
  - "D-11: Nullable columns ONLY for 'transition never happened' timestamps (invalidated_at_utc, acted_at_utc, telegram_message_id, canceled_at_utc, closed_at_utc, journal linkage ids)"
  - "D-10: Enum translation via .value for storage and Enum(value) for restore; unknown values raise ValueError"
  - "DATA_MODEL §2.7: Order carries three independent identifier fields (client_order_id, exchange_order_id, algo_client_id) — all independently nullable"
  - "DATA_MODEL §2.8: Fill has no status field (fills are events, not state)"
  - "FillRow has unique constraint on (order_id, exchange_trade_id) to protect against duplicate fill ingestion"
  - "Approval carries action + result + explicit status (all three columns); status alone answers state"
  - "Migration 0002 down_revision = 0001_baseline; reverse-order downgrade"
  - "PG-vs-SQLite boundary: SQLite is fine for mapper tests because we only exercise the SQLAlchemy ORM mapping; CapturingSession snapshots ORM instances BEFORE SQLite roundtrip so NUMERIC lossiness cannot hide mapper errors"

patterns-established:
  - "CapturingSession pattern: snapshot ORM instance at add() time before SQLite roundtrip"
  - "Total mapper pattern: every field mapped; from_row(to_row(x)) == x round-trip tested"
  - "Offline parity gate: scripts/check_migration_parity.py renders head DDL and diffs full Base.metadata"

requirements-completed:
  - DOMN-01

# Coverage metadata (#1602) — one entry per shipped deliverable.
coverage:
  - id: D1
    description: "Six new ORM tables (TradePlanRow, ApprovalRow, OrderRow, FillRow, PositionRow, JournalEventRow) on the existing single Base with content-hash PKs and no auto-increment"
    requirement: DOMN-01
    verification:
      - kind: automated
        ref: "uv run python scripts/check_migration_parity.py"
        status: pass
      - kind: automated
        ref: "uv run pytest tests/test_domain_mappers.py -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "Total to_row/from_row mapper pairs for all seven entities with Enum translation at boundary"
    requirement: DOMN-01
    verification:
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_signal_round_trip"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_trade_plan_round_trip"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_approval_round_trip"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_order_round_trip"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_fill_round_trip"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_position_round_trip"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_journal_event_round_trip"
        status: pass
    human_judgment: false
  - id: D3
    description: "Migration 0002_domain_registry with seven create_table blocks matching ORM columns 1:1 plus indexes; reverse-order downgrade"
    requirement: DOMN-01
    verification:
      - kind: automated
        ref: "uv run python scripts/check_migration_parity.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "CapturingSession snapshot pattern for SQLite NUMERIC lossiness — captured ORM instances verified before SQLite roundtrip"
    requirement: DOMN-01
    verification:
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_signal_captured_snapshot_precision"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_trade_plan_captured_snapshot_precision"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_approval_captured_snapshot_precision"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_order_captured_snapshot_precision"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_fill_captured_snapshot_precision"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_position_captured_snapshot_precision"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_journal_event_captured_snapshot_precision"
        status: pass
    human_judgment: false
  - id: D5
    description: "Unknown status rejection — Enum(value) raises ValueError on unknown for every Enum-bearing entity"
    requirement: DOMN-01
    verification:
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_signal_unknown_status_raises"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_trade_plan_unknown_status_raises"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_approval_unknown_action_raises"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_approval_unknown_result_raises"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_order_unknown_local_status_raises"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_position_unknown_status_raises"
        status: pass
    human_judgment: false
  - id: D6
    description: "Nullable never-happened timestamps round-trip as None (invalidated_at_utc, acted_at_utc, canceled_at_utc, closed_at_utc, journal linkage ids)"
    requirement: DOMN-01
    verification:
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_signal_invalidated_at_utc_none_round_trips"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_approval_acted_at_utc_none_round_trips"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_order_canceled_at_utc_none_round_trips"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_position_closed_at_utc_none_round_trips"
        status: pass
      - kind: automated
        ref: "tests/test_domain_mappers.py::test_journal_event_message_id_none_round_trips"
        status: pass
    human_judgment: false

# Metrics
duration: "~15 minutes"
completed: "2026-09-22"
status: complete
plan_head_before: 1300150c043d2076fed811954eed21642ceb4c63
commits: 2
---

# Phase 3 Plan 4: Seven-Table ORM Mirror + Mappers + Migration 0002 Summary

Seven ORM tables (signals + six new) on the existing single Base, total to_row/from_row mapper pairs for all seven entities, migration 0002_domain_registry with offline parity gate green, and a 25-test mapper round-trip suite with CapturingSession precision snapshots.

## One-liner

Seven domain entities persist separately with content-hash PKs, explicit status columns, and total mappers — parity gate green, 25 mapper tests green, 176 total tests green.

## Accomplishments

### Task 1: Confirm one-way table shape (checkpoint:decision, auto-resolved)

Auto-selected the recommended seven-table shape per auto-mode protocol:
- Seven tables: signals, trade_plans, approvals, orders, fills, positions, journal_events
- PKs on deterministic content-hash IDs; no auto-increment anywhere
- trades and experiment_runs deferred to Phases 5 and 6
- Registry DB mirror deferred to Phase 6 with files canonical
- Approvals carry action + result + explicit status
- TIMESTAMPTZ + NUMERIC(38,18) with nullable only for never-happened transitions

### Task 2: Seven ORM tables + total mappers + migration 0002 (commit `fff161b`)

Extended `src/db/models.py` with six new tables on the existing `Base`:
- **TradePlanRow** on `trade_plans` — String(128) PK `trade_plan_id`, signal_id FK, entry bound and price Decimal columns, payload String columns, plan_hash String(64), status String(16), created TIMESTAMPTZ
- **ApprovalRow** on `approvals` — String(128) PK `approval_id`, plan and signal FKs, action/result/status String columns, token and request hash Strings, nullable acted and message TIMESTAMPTZ
- **OrderRow** on `orders` — String(128) PK `order_id`, nullable plan/position/parent FKs, role and side Strings, Decimal quantity/price/stop_price, three independent identifier columns (client_order_id, exchange_order_id, algo_client_id), exchange_status String, local_status String(16), submitted/updated/canceled TIMESTAMPTZ
- **FillRow** on `fills` — String(128) PK `fill_id`, order FK, exchange_trade_id String, Decimal economics, commission_asset String, maker Boolean, fill_time TIMESTAMPTZ, unique constraint on (order_id, exchange_trade_id)
- **PositionRow** on `positions` — String(128) PK `position_id`, symbol/side/mode Strings, Decimal economics, opened/updated/closed TIMESTAMPTZ, status String(16)
- **JournalEventRow** on `journal_events` — String(128) PK `journal_event_id`, occurred/created TIMESTAMPTZ, event/entity type Strings, correlation String, nullable linkage ids, payload String

Extended `src/db/mappers.py` with total to_row/from_row pairs for all seven entities:
- Enum translation via `.value` for storage and `Enum(value)` for restore (raises ValueError on unknown — D-10)
- Every field mapped; round-trip tested

Created `src/db/alembic/versions/0002_domain_registry.py`:
- `revision = "0002_domain_registry"`, `down_revision = "0001_baseline"`
- Seven `create_table` blocks matching ORM columns 1:1
- Indexes on signals (symbol, source_candle_close_utc) and (parameter_set_id, parameter_set_hash)
- Indexes on trade_plans (signal_id), approvals (trade_plan_id, signal_id), orders (trade_plan_id, position_id, symbol+submitted_at_utc), fills (order_id, symbol+fill_time_utc), positions (symbol+status), journal_events (correlation_id, occurred_at_utc)
- Reverse-order downgrade

Offline parity gate green: `scripts/check_migration_parity.py` reports no drift across all seven tables.

### Task 3: Mapper round-trip suite times seven (commit `e8fdb58`)

Wrote `tests/test_domain_mappers.py` with 25 tests:
- **7 round-trip tests** — `from_row(to_row(x)) == x` for each entity
- **7 captured-snapshot precision tests** — CapturingSession snapshots ORM instances BEFORE SQLite roundtrip so NUMERIC lossiness cannot hide mapper errors
- **6 unknown-status rejection tests** — Signal, TradePlan, Approval (action + result), Order, Position all raise ValueError on unknown status
- **5 nullable never-happened timestamp tests** — invalidated_at_utc, acted_at_utc, canceled_at_utc, closed_at_utc, journal linkage ids all round-trip as None

PG-vs-SQLite boundary documented in module docstring: SQLite is fine for these tests because we only exercise the SQLAlchemy ORM mapping (Numeric → Decimal, TIMESTAMPTZ → datetime); no PostgreSQL-specific features (JSONB, partial indexes) are used.

## Deviations from Plan

None — plan executed exactly as written.

## Files Created/Modified

### Created (2 files)
- `src/db/alembic/versions/0002_domain_registry.py` — migration with seven create_table blocks
- `tests/test_domain_mappers.py` — 25 mapper round-trip tests

### Modified (2 files)
- `src/db/models.py` — added six new ORM tables on existing Base
- `src/db/mappers.py` — added total to_row/from_row pairs for all seven entities

## Verification

- `uv run python scripts/check_migration_parity.py` → OK — model <-> migration parity green (all 11 tables)
- `uv run pytest tests/test_domain_mappers.py -q` → 25 passed
- `uv run pytest` → 176 passed (25 new + 151 existing)
- `uv run ruff check src/ tests/` → All checks passed
- `uv run mypy src/` → Success: no issues found in 29 source files

## Acceptance Criteria

- [x] The parity script exits zero with no drift reported across all seven tables.
- [x] No auto-increment or sequence column exists in the new migration.
- [x] src/domain contains no import of src.db by inspection.

## Must-Haves Verification

- [x] Seven entities persist in separate tables keyed by deterministic content-hash PKs with no auto-increment
- [x] Migration 0002 matches the ORM one-to-one and the offline parity gate is green
- [x] Every entity mapper round-trips exactly, with unknown statuses raising

## Next Steps

Phase 3 plan 05 (DOMN-02/DOMN-03): determinism suites (no-lookahead, prefix-invariance, candle-close-timing, boundary) plus CI registry gate plus no-float guard.
