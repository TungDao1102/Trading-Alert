---
phase: 03-domain-registry-fixtures
plan: "02"
subsystem: domain
tags: [domain, entities, tdd, frozen-dataclass, decimal, utc, enum, approval-result]
requires:
  - phase: 03-01
    provides: src/domain package skeleton, enums, canonical hash, ids, Signal entity
provides:
  - TradePlan, Approval, Order, Fill, Position, JournalEvent frozen dataclasses
  - ApprovalResult enum (PENDING, APPROVED, SKIPPED, EXPIRED)
  - Extended barrel exports in src/domain/__init__.py
  - Entity-discipline test suite (22 tests)
affects:
  - Phase 4 (Pure Core) consumes all seven domain entities
  - Phase 5 (Risk) consumes TradePlan + Position
  - Phase 6 (Backtest) consumes TradePlan + Fill + Position
  - Phase 8 (Approval) consumes Approval + Order
  - Phase 10 (Journal) consumes JournalEvent
tech-stack:
  added: []
  patterns:
    - frozen dataclass + Decimal + UTC + Enum (D-01/D-12)
    - __post_init__ validation for Decimal typing and UTC awareness
    - validated non-empty strings for event_type/entity_type (T-03-04)
    - explicit status columns; nullable timestamps only for "transition never happened" (D-11)
key-files:
  created:
    - src/domain/trade_plan.py
    - src/domain/approval.py
    - src/domain/order.py
    - src/domain/fill.py
    - src/domain/position.py
    - src/domain/journal.py
    - tests/test_domain_entities.py
  modified:
    - src/domain/enums.py
    - src/domain/__init__.py
key-decisions:
  - "D-10: ApprovalResult enum with PENDING, APPROVED, SKIPPED, EXPIRED (planner assumption flagged for user confirmation)"
  - "D-11: Approval carries both result and explicit status (both ApprovalResult); status alone answers state"
  - "D-12: __post_init__ validates Decimal typing on all money/qty/price fields and UTC awareness on all timestamps"
  - "T-03-04: JournalEvent event_type and entity_type are validated non-empty strings; empty values rejected at construction"
  - "DATA_MODEL §2.8: Fill has no status attribute (fills are events, not state)"
  - "DATA_MODEL §2.7: Order carries three independent identifier fields (client_order_id, exchange_order_id, algo_client_id)"
  - "Phase 4 deferral: setup_type, regime, order_role, side, position_side, order_type, time_in_force, event_type, entity_type stay as validated non-empty strings; Enum promotion deferred to Phase 4"
requirements-completed:
  - DOMN-01
duration: "~10 minutes"
completed: "2026-09-22"
status: complete
plan_head_before: 3a86baecc854d7faf0b4048c3eaac1e1f4487438
commits: 2
actuals:
  tokens: 18500
  tasks: 3
  commits: 2
---

# Phase 3 Plan 2: Six Remaining Domain Entities Summary

Six frozen dataclass modules (TradePlan, Approval, Order, Fill, Position, JournalEvent) plus the ApprovalResult enum, completing the seven-entity domain vocabulary per D-01/D-10/D-11/D-12.

## One-liner

Six frozen domain entities with Decimal money fields, UTC-aware timestamps, Enum statuses, and explicit-status discipline — all 22 entity-discipline tests green.

## Accomplishments

### RED Phase (commit `05010a9`)

Wrote 22 failing tests in `tests/test_domain_entities.py` covering:
- **Frozen mutation rejection** (D-01) — TradePlan, Approval, Order, Fill, Position, JournalEvent all raise `FrozenInstanceError` on mutation.
- **Decimal typing** (D-12) — money/qty/price fields reject non-Decimal construction.
- **UTC awareness** (D-12) — all datetime fields reject naive datetimes.
- **Enum identity** (D-10) — status fields are Enum instances, not strings.
- **Explicit status** (D-11) — Approval status reads correctly with `acted_at_utc` left as None.
- **Fill has no status** (DATA_MODEL §2.8) — fills are events, not state.
- **JournalEvent validation** (T-03-04) — empty `event_type`/`entity_type` rejected at construction.
- **Order three identifiers** (DATA_MODEL §2.7) — `client_order_id`, `exchange_order_id`, `algo_client_id` independently stored.
- **Seven-entity barrel** (D-01) — all seven entities importable from `src.domain` in one statement.
- **ApprovalResult enum** — PENDING, APPROVED, SKIPPED, EXPIRED.

All 22 tests failed with `ModuleNotFoundError` — the expected RED state.

### GREEN Phase (commit `d1deb4a`)

Implemented the six entities per D-01, D-10, D-11, D-12:
- **`src/domain/trade_plan.py`** — frozen TradePlan with Decimal money fields, TradePlanStatus, JSON-as-TEXT payloads.
- **`src/domain/approval.py`** — frozen Approval with ApprovalAction + ApprovalResult (both result and status), nullable `acted_at_utc` and `telegram_message_id`.
- **`src/domain/order.py`** — frozen Order with three independent identifier fields, OrderStatus for `local_status`, raw string for `exchange_status`.
- **`src/domain/fill.py`** — frozen Fill with no status field (events not state), Decimal economics.
- **`src/domain/position.py`** — frozen Position with PositionStatus, nullable `closed_at_utc`.
- **`src/domain/journal.py`** — frozen JournalEvent with validated non-empty `event_type`/`entity_type`, all linkage ids nullable except `correlation_id`.
- **`src/domain/enums.py`** — added `ApprovalResult` enum (PENDING, APPROVED, SKIPPED, EXPIRED).
- **`src/domain/__init__.py`** — extended barrel exports.

All entities use `__post_init__` to validate Decimal typing and UTC awareness at construction. All 22 tests pass. Full suite: 140 tests pass. Ruff clean. Mypy strict clean.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Added __post_init__ validation to all six entities**
- **Found during:** Task 2 GREEN phase
- **Issue:** The plan specified "Decimal typing on all money fields" and "UTC awareness on all timestamps" as discipline tests, but the dataclass fields alone don't enforce these — a float or naive datetime would pass type checking and only fail at runtime in unexpected ways.
- **Fix:** Added `__post_init__` validation to each entity that rejects non-Decimal values for money/qty/price fields and naive datetimes. This makes the discipline tests pass and prevents silent type drift.
- **Files modified:** src/domain/trade_plan.py, src/domain/approval.py, src/domain/order.py, src/domain/fill.py, src/domain/position.py, src/domain/journal.py
- **Commit:** d1deb4a

**2. [Rule 2 - Missing critical] Updated test helpers to pass Enum instances instead of strings**
- **Found during:** Task 2 GREEN phase
- **Issue:** The test helpers passed enum values as strings (e.g., `"READY"`, `"APPROVE"`), but the dataclass fields are typed as Enum classes. The `str, Enum` mixin means `TradePlanStatus.READY == "READY"` is True, but `isinstance("READY", TradePlanStatus)` is False.
- **Fix:** Updated test helpers to import and pass Enum instances directly. This matches the canonical pattern from `src/domain/signal.py` and the existing `test_domain_enums.py` tests.
- **Files modified:** tests/test_domain_entities.py
- **Commit:** d1deb4a

**Total deviations:** 2 auto-fixed (2 missing critical). **Impact:** Both fixes are correctness/quality improvements that align with the plan's intent.

## Files Created/Modified

### Created (7 files)
- `src/domain/trade_plan.py` — TradePlan frozen dataclass
- `src/domain/approval.py` — Approval frozen dataclass
- `src/domain/order.py` — Order frozen dataclass
- `src/domain/fill.py` — Fill frozen dataclass
- `src/domain/position.py` — Position frozen dataclass
- `src/domain/journal.py` — JournalEvent frozen dataclass
- `tests/test_domain_entities.py` — 22 entity-discipline tests

### Modified (2 files)
- `src/domain/enums.py` — added ApprovalResult enum
- `src/domain/__init__.py` — extended barrel exports

## Verification

- `uv run pytest tests/test_domain_entities.py` → 22 passed
- `uv run pytest` → 140 passed (22 new + 118 existing)
- `uv run ruff check src/ tests/` → All checks passed
- `uv run mypy src/` → Success: no issues found in 28 source files

## Acceptance Criteria

- [x] Dataclass mutation attempts raise FrozenInstanceError on all six entities.
- [x] Every money field rejects non-Decimal construction in the discipline tests.
- [x] Approval status reads correctly with acted_at_utc left as None.
- [x] Seven entity classes import from src.domain in one statement without side effects.
- [x] Fill has no status attribute by construction test.
- [x] JournalEvent with an empty event_type raises at construction.
- [x] All listed test modules report all tests passed with zero failures.

## Must-Haves Verification

- [x] All seven entities exist as frozen dataclasses with GLOSSARY-canonical lifecycle enums
- [x] Approval carries action plus explicit result lifecycle plus explicit status, never inferred from timestamps
- [x] No entity imports anything beyond stdlib and the domain package

## Next Steps

Phase 3 plan 03 (Registry hardening): add fail-closed negative gates, CI gate workflow, and registry DB mirror timing decision.
