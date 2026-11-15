---
phase: 24-live-runtime-composition-demo
plan: 07
subsystem: persistence
tags: [alembic, postgresql, event-time, monotonic-guard, orders, positions, d-10, g4-043]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: "24-01 Q3 answer (recommended single migration 0015, two nullable event-time columns)"
  - phase: 23-telegram-approval-hardening-money
    provides: "migration 0014_decided_excl_expired (the previous head)"
provides:
  - "migration 0015_order_event_time: orders.exchange_event_time_utc and positions.snapshot_event_time_utc (TIMESTAMPTZ NULL), guarded downgrade"
  - "PgTradingEntityStore.update_order_exchange_state(..., exchange_event_time_utc=) with a monotonic rule"
  - "PgTradingEntityStore.update_position_snapshot (G4-043)"
  - "StateUpdate[E](entity, stale) result type exported from src.persistence.entities"
affects: [24-19]

key-files:
  created:
    - src/db/alembic/versions/0015_order_event_time.py
    - tests/test_persistence_event_time_pg.py
  modified:
    - src/db/models.py
    - src/persistence/entities.py
    - tests/test_persistence_migration_pg.py
    - tests/test_phase21_gate.py
    - tests/test_phase22_gate.py
    - tests/test_phase23_gate.py

key-decisions:
  - "Return type: update_order_exchange_state is overloaded. Without an event time it returns Order exactly as before (existing callers and tests unchanged); with an event time it returns StateUpdate[Order] (entity, stale). update_position_snapshot always returns StateUpdate[Position]."
  - "Monotonic rule: stale only when event time < stored; equal time applies (Binance can send several updates with the same E), and identical state at an equal time is an idempotent no-op that does not rewrite updated_at_utc."
  - "The guard is enforced twice: Python check under the row lock (FOR UPDATE) and the same predicate in the conditional UPDATE's WHERE (_apply gained *extra_where)."
  - "A call without an event time never clears a stored event time."
  - "The three gate tests were renamed ..._is_0015_order_event_time (no other file referenced the old names)."

patterns-established:
  - "Event-time columns are outside the domain entities and the content-hash identity; they are listed in the store's `evolving` sets so the idempotent-insert comparison ignores them."

requirements-completed: []  # EXEC-02 stays Pending for the orchestrator: plan 24-19 is the production caller

actuals:
  tokens: 31000
  tasks: 2
  commits: 2
plan_head_before: 7bd629638a5d5013148b57e65165e76e46da87df
plan_head_after: b9bdaff4b8f862f17cecfa3b10c7c54b9d4475cd

duration: 1 session
completed: 2026-10-31
status: complete
---

# Phase 24 Plan 07: Order and position event time Summary

**Migration 0015 adds nullable exchange event-time columns to orders and positions, and the store applies an order update or a position snapshot only when its event time is not older than the stored one.**

## Accomplishments

- `0015_order_event_time` (revises `0014_decided_excl_expired`, 21 characters): hand-written, imports no project module, adds `orders.exchange_event_time_utc` and `positions.snapshot_event_time_utc`; no new table. The downgrade counts rows holding an event time in either table and raises `RuntimeError("cannot drop event-time columns: N rows hold an event time")` when N > 0, else drops both columns.
- ORM mirror in `src/db/models.py` (ORM parity test passes).
- `update_order_exchange_state` accepts `exchange_event_time_utc`: older event is a stale no-op returning the stored order; newer applies and stores the time; equal time with the same state is a no-op; no event time keeps today's behaviour. A different exchange order id is still a `RowConflict`.
- `update_position_snapshot` (new): quantity (signed), entry price, break-even price, unrealized and realized PnL, event time; never touches `status` or `closed_at_utc`; float -> `TypeError`, more than 18 fractional digits or non-finite -> `PrecisionError` (never rounded); naive or non-UTC times -> `ValueError`.
- Head pins moved to 0015 in `test_persistence_migration_pg.py` and the phase 21, 22, 23 gates, with messages naming D-10. The 0014 downgrade-refusal test now steps down through 0015 first so it stays deterministic.
- O-5 (exact signed-quantity compare) not added; the D-01a reconcile bound check is unchanged.

## Verification

- `TRADING_CI_STRICT=1 uv run pytest -m "not docker"` on `tests/test_persistence_event_time_pg.py tests/test_persistence_transitions_pg.py tests/test_persistence_roundtrip_pg.py tests/test_persistence_constraints_pg.py tests/test_persistence_exit_evidence_pg.py tests/test_domain_entities.py`: pass (no skips, strict mode).
- `TRADING_CI_STRICT=1 ... tests/test_persistence_migration_pg.py tests/test_pg_fixture_guard.py`: pass.
- `tests/test_phase21_gate.py tests/test_phase22_gate.py tests/test_phase23_gate.py tests/test_domain_entities.py`: pass.
- Also green: `tests/test_domain_mappers.py tests/test_domain_mappers_pg.py tests/test_execution_exactly_once_pg.py tests/test_persistence_approvals_pg.py`; `scripts/verify_decision_alignment.py all` ALL_PASS.
- `uv run mypy src` clean (264 files); ruff check and format clean on touched files; `uv lock --check` ok; `git diff --exit-code -- pyproject.toml uv.lock` exits 0 (T-24-SC).
- `git grep -n "def update_position_snapshot" -- src`: one line. Index line endings unchanged (`i/lf`).

## Task Commits

1. **Task 1 (tracer): migration 0015, ORM columns, monotonic store methods, PostgreSQL tests** - `4567a903`
2. **Task 2: migration 0015 tests and head pins** - `b9bdaff4`

## Deviations from Plan

**1. [Rule 3 - Blocking] Worktree was created on the wrong base.** The agent worktree started at `d9907ffc` (master), which has no Phase 24 files and stops at migration 0006 in the worktree's history view; the work lives on `develop` (`7bd62963`). Before any edit I fast-forwarded the clean, commit-free agent branch to `develop` with `git reset --hard develop` (the sanctioned startup action). No plan content changed. The orchestrator should merge this branch onto `develop`.

**2. [Tracer gate] Tests were written before the implementation but were not run red first.** The test file and the implementation were produced in one pass, then run; the stale-event tests assert the stored state is unchanged, so they do fail without the guard, but the red run was not recorded.

**3. [Scope] Tests written beyond the plan's list:** equal-time-different-state applies, a different exchange id is still a conflict under an event time, UTC-awareness of both times, non-finite decimals, and a missing position.

The precondition (24-01 Q3) held; `TEST_DATABASE_URL` was set and names a `_test` database (value never printed).

## Known Stubs

None.

## Threat Flags

None. No endpoint, auth path or file access added; the schema change is the one the plan declared. T-24-17 (stale overwrite), T-24-18 (destructive downgrade), T-24-19 (float or rounded values) are mitigated and tested; T-24-SC holds.

## Self-Check: PASSED

- FOUND: src/db/alembic/versions/0015_order_event_time.py, tests/test_persistence_event_time_pg.py
- FOUND commits 4567a903, b9bdaff4 (ancestors of HEAD)
