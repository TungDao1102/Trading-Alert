---
phase: 20-reconcile-safe-mode-hardening
plan: 18
subsystem: execution-lot-filters
tags: [lot-filters, emergency-close, q3, d-21, migration-0009, fail-closed, tdd]
requires: [20-14, 20-01]
provides:
  - "migration 0009_validated_lot_filters: table validated_lot_filters (symbol PK, 8 NUMERIC(38,18) filter columns with named positive CHECKs, lot and market-lot range CHECKs, fetched_at_utc, updated_at_utc >= fetched_at_utc) and ORM row ValidatedLotFiltersRow"
  - "src.execution.lot_filter_source: LotFilterSource(adapter, store, limits, clock, snapshot_for=None) with for_entry, for_emergency_close, refresh_if_due; StoredLotFilters, LotFilterStore Protocol, LotFiltersUnavailable, SnapshotFor"
  - "src.persistence.lot_filters.PgLotFilterStore (upsert keeps the newest fetch, get returns the row flagged stale)"
  - "MarketEmergencyCloser(lot_filters=) keyword (default None: behavior unchanged); EMERGENCY_CLOSE journal rows carry filters_stale and filters_fetched_at_utc when a source is attached"
affects: [20-19, 20-21, 20-24]
tech-stack:
  added: []
  patterns:
    - "one object (LotFilterSource) owns the difference between the entry path (live only) and the emergency-close path (live, then stored, then plan snapshot); an AST test pins the single caller"
    - "a store failure never turns a good live read into a failed close; a store read failure is 'nothing stored' and falls to the next tier"
key-files:
  created:
    - src/db/alembic/versions/0009_validated_lot_filters.py
    - src/execution/lot_filter_source.py
    - src/persistence/lot_filters.py
    - tests/support/lot_filter_fakes.py
    - tests/test_emergency_close_filters.py
    - tests/test_lot_filters_pg.py
  modified:
    - src/db/models.py
    - src/execution/emergency_close.py
    - src/persistence/__init__.py
    - tests/test_persistence_migration_pg.py
    - docs/data/DATA_MODEL.md
key-decisions:
  - "Q3/D-21 implemented as written: the emergency close alone may use stored filters, flagged stale; for_entry never returns a stored row."
  - "PlanConstraintSnapshot IS persisted (PgPlanConstraintSnapshotStore); it is a tier-2 fallback only when max_quantity and all three market-lot values are present, never 'the last validated filters'."
requirements-addressed: [RISK-03]
status: complete
duration: about 3h (includes a session-limit pause)
completed: 2026-10-21
estimate:
  tokens: 95000
  tasks: 3
actuals:
  tokens: 17600   # chars/4 over `git diff 87c82ce0 HEAD -- src tests` (70350 chars)
  tasks: 3
  commits: 3      # MEASURED: git rev-list --count 87c82ce0..HEAD at SUMMARY write, before the SUMMARY commit
plan_head_before: 87c82ce04e3e2abc25d49846b820920d2386d868
plan_head_after: c31b3d6e8423dc7d5292d680011e94fe233cde4f
---

# Phase 20 Plan 18: Last validated lot filters for the emergency close Summary

**An emergency close survives a failed exchangeInfo read by sizing from the symbol's last validated MARKET_LOT_SIZE filters, journaled as stale with their fetch time; a new entry can never use them, and with no valid filters nothing is guessed (LOT_FILTERS_UNAVAILABLE, SAFE_MODE and the critical alert stay).**

Base `87c82ce0` (develop), branch `p20-18`. `commits: 3` is measured before the SUMMARY commit. No requirement is marked complete (`requirements-addressed` only).

## What was built

- **Migration 0009** (`down_revision` = `0008_pending_protective_actions`, hand-written, imports no project module) and `ValidatedLotFiltersRow`. Migrations 0001-0008 are byte-unchanged; `pyproject.toml` and `uv.lock` are unchanged.
- **`LotFilterSource`**: `for_entry` reads live only (raises `LotFiltersUnavailable`, never touches the stored path, and requires a `LotFilters` for the right symbol). `for_emergency_close(symbol, trade_plan_id=)` reads live and stores the read (`filters_stale=False`); on a failed read it returns the stored row, else the plan snapshot (tier 2), flagged stale, else raises. `refresh_if_due(symbol, now_utc=)` reads and upserts only when there is no row or `now_utc - fetched_at_utc >= reconcile.lot_filter_refresh_interval_ms`; it never raises. The constructor refuses limits without that key.
- **`PgLotFilterStore`**: `INSERT ... ON CONFLICT (symbol) DO UPDATE ... WHERE existing.fetched_at_utc <= excluded.fetched_at_utc` (an older fetch never replaces a newer row); Decimals exact; `get` returns `StoredLotFilters(filters_stale=True)`.
- **`MarketEmergencyCloser`**: with `lot_filters=` set, `close_position` uses `for_emergency_close`; `_record` adds `filters_stale` and `filters_fetched_at_utc` to every EMERGENCY_CLOSE row of that close. A close rejected with a lot-filter code (-1111, -4003, -4004, -4005, from the repo taxonomy's "Filter rejection" entries) records `(quantity, next attempt number)` per plan: the next call takes a new attempt number, and a part with the same quantity is not sent (`FILTER_REJECTED_SAME_PAYLOAD`, fail closed). The WR-03 one-part-at-a-time rule is untouched (a test pins the call order on stale filters).
- **Tests**: `tests/test_emergency_close_filters.py` (25), `tests/test_lot_filters_pg.py` (14, PostgreSQL), 0009 additions and the head pin (now 0009) in `tests/test_persistence_migration_pg.py`, `tests/support/lot_filter_fakes.py`.
- **Docs**: `docs/data/DATA_MODEL.md` section 2.18.

## Verification actually run

- `uv run pytest -m "not docker"` (TRADING_CI_STRICT=1, TEST_DATABASE_URL from the process environment, `-p no:randomly`) over: test_emergency_close_filters, test_emergency_market_close, test_market_lot_split, test_lot_filters_pg, test_persistence_migration_pg, test_phase18_gate, test_phase19_gate, test_persistence_exit_evidence_pg, test_pending_actions, test_pending_actions_pg, test_protection_router_rig, test_metadata, test_cutover, test_domain_mappers, test_collector, test_backfill_cli, test_analytics_store, test_approval_message, test_decision_alignment_bookkeeping, test_agents_md, test_pg_fixture_guard, test_execution_exactly_once_pg: 716 passed, 1 error. The error was `StoreUnavailable` (PostgreSQL unreachable at connect time) in one parametrized case of test_lot_filters_pg; the file was re-run once and gave 14 passed. Treated as a transient local-database blip, not a code failure.
- `uv run mypy src`: no issues in 232 files. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `uv run ruff format --check`: 711 files already formatted.
- `uv run ruff check` (whole repo) reports ONE error, `src/execution/protection.py:72` E501. That file is untouched by this plan (`git diff 87c82ce0 HEAD` is empty for it), so the error is present on the base. `ruff check` on every file this plan touched passes.
- Not run (by rule): the full suite. Evidence label: fakes and local PostgreSQL only; Binance acceptance of a close sized on stale filters is `[NOT_TESTED]`.

## RED evidence (honest)

- Task 1: `tests/test_emergency_close_filters.py` failed at collection (`ModuleNotFoundError: src.execution.lot_filter_source`) before any implementation. The PG tests and migration tests were written together with the migration and store and were NOT seen failing separately.
- Task 2: after a constructor stub that only accepted `snapshot_for`, two behavior tests failed for the right reason (`test_a_filter_rejected_close_is_not_resent_with_the_same_payload`: one extra send; `test_the_plan_snapshot_is_tier_two_...`: snapshot never asked). The remaining Task 2 tests (no filters, below-minimum, entries never stale, split close, incomplete snapshot, gated pause, AST) passed on first run because Task 1 already gave those paths their fail-closed behavior; they pin it.
- Task 3: four `refresh_if_due` tests failed with `AttributeError` before the method existed; the constructor-refusal test passed already (implemented in Task 1).

## Deviations from Plan

**1. [Interface] `LotFilterSource` takes `clock` and `snapshot_for` keywords.** The plan lists `LotFilterSource(*, adapter, store, limits)`. The source needs an injected clock to stamp a live read (no wall clock in this module) and the plan's own Task 2 text requires the injected snapshot callable. Both are keyword-only; `snapshot_for` defaults to None. `for_emergency_close` also takes an optional `trade_plan_id` keyword for tier 2.

**2. [Interpretation] Under a 429/418 pause the stored filters are still used to size the part.** The plan says stored filters "help only when the read fails for another reason ... and the close itself is still gated". The source does not distinguish a gate-refused read from a timeout; the sized part then meets the same adapter gate and ends as `NOT_SENT` with the 20-14 pending row (a test pins `NOT_SENT` and an untouched position). If the owner reads the sentence as "never use stored filters under a pause", this is a one-line change in `for_emergency_close`.

**3. [Scope] `updated_at_utc` equals the write's `fetched_at_utc`.** The store Protocol (`upsert(filters, *, fetched_at_utc)`) carries no second clock, so the column is the fetch time of the last write, with a CHECK `updated_at_utc >= fetched_at_utc`.

**4. [Test pin] `test_downgrade_0008_...` updated.** Downgrading from head to 0007 now also drops `validated_lot_filters`; the expected table set accounts for it (same pattern as the 0007 precedent). The head pin moved to 0009.

## Findings for later plans

- `-1013` (Binance invalid-quantity filter failure) is not in `src/domain/exchange_errors.py`, so a close rejected with it is classified ambiguous and goes through the existing probe path, not the filter-rejection path. Adding it needs a taxonomy row (owner/evidence decision; not done here).
- A filter-rejected part whose fresh live filters yield the same quantity is refused forever (fail closed, alert each step). That is the plan's rule; the operator path (`emergency_manual_close`) is the way out.
- Plan 20-21 must call `LotFilterSource.refresh_if_due` per symbol on the reconcile tick, and the composition root must construct `LotFilterSource(adapter, PgLotFilterStore, limits, clock, snapshot_for=PgPlanConstraintSnapshotStore.get)` and pass it to `MarketEmergencyCloser(lot_filters=)`. Nothing wires it yet.
- The stored fallback has no maximum age (the plan defines none and no number is invented); the journal records the fetch time so an age limit can be added by an owner decision.
- `ruff check` fails on the base at `src/execution/protection.py:72` (E501); unrelated to this plan.
- `PgLotFilterStore` calls are synchronous inside the async closer, like the 20-14 pending store.

## Known Stubs

None.

## Threat Flags

None. T-20-45 and T-20-46 are mitigated as planned (AST test for the single `for_emergency_close` caller; floor-only sizing; `LOT_FILTERS_UNAVAILABLE` fail closed). T-20-SC: `git diff --exit-code 87c82ce0 HEAD -- pyproject.toml uv.lock` exits 0.

## Self-Check: PASSED

All created files exist, the three commits (f9c0425e, db130cfb, c31b3d6e) are on branch p20-18, and no file was deleted.
