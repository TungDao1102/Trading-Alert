---
phase: 22-leverage-margin-liquidation-guard
plan: 08
subsystem: persistence
tags: [migration-0012, risk-reservations, margin-claims, D-14, amendment-A2, F-966, criterion-3]
requires:
  - phase: 21
    provides: "risk_reservations table (migration 0011), PgRiskReservationStore, ReservationRequest"
  - phase: 22-04
    provides: "MarginClaim in src/risk/margin_check.py"
provides:
  - "migration 0012_reservation_margin: nullable required_margin, margin_entry_price, margin_leverage on risk_reservations; CHECKs ck_risk_reservations_margin_coherent and ck_risk_reservations_margin_positive; real downgrade"
  - "ReservationRequest optional margin trio (all None or all set, validated)"
  - "PgRiskReservationStore.register_request stores and compares the trio; PgRiskReservationStore.list_margin_claims -> tuple[MarginClaim, ...]"
affects: [22-14, 22-16]
tech-stack:
  added: []
  patterns: ["optional trailing dataclass fields keep every Phase 21 constructor working", "NULL = unknown margin, never zero (fail closed)"]
key-files:
  created:
    - src/db/alembic/versions/0012_reservation_margin.py
    - tests/test_risk_reservation_margin_pg.py
  modified:
    - src/db/models.py
    - src/risk/reservations.py
    - src/persistence/risk_reservations.py
    - tests/test_risk_reservations.py
    - tests/test_risk_reservations_pg.py
    - tests/test_persistence_migration_pg.py
    - tests/test_phase21_gate.py
    - docs/data/DATA_MODEL.md
key-decisions:
  - "Amendment A2 followed: the plan's required margin is stored on the Phase 21 reservation row and read back as claims; the authoritative sum is taken at placement (plan 22-14). reserve_in and the approval transaction are not changed."
  - "No backfill: a legacy row reads as an UNKNOWN margin (MarginClaim.required_margin None), which makes the placement-time sum unknown and the check NO_TRADE."
  - "The margin trio is part of the register_request identity comparison in both directions (a stored NULL differs from a set value and the reverse)."
status: complete
requirements-addressed: [RISK-02]
duration: ~35 min
completed: 2026-10-24
commits: 2
plan_head_before: a2525f9a744700f4e45fafadf60bfc953e22a1b4
plan_head_after: 064c523a0ff3ed52577302c1f54d64a9111edbd6
actuals:
  tokens: 26000
  tasks: 2
  commits: 2
---

# Phase 22 Plan 08: Reservation margin columns and claims reader Summary

**Migration 0012 gives every Phase 21 risk reservation an optional margin (`required_margin`, `margin_entry_price`, `margin_leverage`), `register_request` stores and compares it, and `list_margin_claims` returns one `MarginClaim` per RESERVED or PLACED row so the placement-time check can count the other plans' margin; legacy rows read as an unknown margin and fail closed.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 333d90fe | migration 0012, ORM mirror, request trio, `register_request` and `list_margin_claims`, unit and PostgreSQL tests |
| 2 | 064c523a | head pins moved to 0012, 0012 migration tests, DATA_MODEL 2.21 |

`commits: 2` is measured with `git rev-list plan_head_before..plan_head_after` filtered to this plan's subjects: the shared working tree also holds sibling commits (22-06, 22-07, 22-09) between the two hashes, so the raw range count is larger. The SUMMARY commit follows.

## What was built

- **Migration `0012_reservation_margin`** (hand-written, imports no project module, revises `0011_risk_reservations`): `ADD COLUMN` x3 (NUMERIC(38,18) NULL, NUMERIC(38,18) NULL, INTEGER NULL), then the two named CHECKs. The downgrade drops the CHECKs then the columns; rows stay.
- **`RiskReservationRow`** mirrors the columns and the two PostgreSQL-only CHECKs, so the existing `compare_metadata` parity test (with the check-constraint-by-name plugin) holds.
- **`ReservationRequest`** gains the optional trio (default None). Partial trio: `ValueError`; Decimals must be finite and above zero (`TypeError` for a non-Decimal); leverage an int, not a bool, at least 1.
- **`PgRiskReservationStore.register_request`** inserts the trio, runs `_require_exact_storage` on both Decimals before any write, and compares the trio in the identity check.
- **`PgRiskReservationStore.list_margin_claims(tx=None)`**: RESERVED and PLACED rows only, ordered `(symbol, position_side, trade_plan_id)`, rebuilt on every call.
- **Pins moved on purpose**: the head test and the three post-upgrade head assertions in `tests/test_persistence_migration_pg.py`, and `test_invariant_6_*` in `tests/test_phase21_gate.py` (renamed `..._is_0012_reservation_margin`; no other file references the old name).
- **DATA_MODEL 2.21**: three columns, the revision bullet with both CHECK names and "no backfill", the claims reader and the amendment A2 sentence.

## Verification

All commands run on the shared tree with `TEST_DATABASE_URL` set in the process environment and `TRADING_CI_STRICT=1`, so a skip would have been a failure.

| Command | Result |
|---------|--------|
| `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_migration_pg.py tests/test_risk_reservation_margin_pg.py tests/test_risk_reservations.py tests/test_risk_reservations_pg.py tests/test_risk_reservation_approval_pg.py tests/test_pg_fixture_guard.py tests/test_execution_exactly_once_pg.py` (sequential) | all passed, no skips (PG tests ran against the local PostgreSQL) |
| `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py` | all passed |
| `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS |
| `uv run mypy` on the four `src` files of the plan | no issues |
| `uv run ruff check` / `ruff format --check` on the eight code files | clean |
| `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config/binance` | clean |
| `git log --grep="^[a-z]*(22-08):" -- src/adapters src/execution src/persistence/approvals.py params config` | prints nothing |

Evidence label: executed tests against local PostgreSQL [DESIGN]; no running process writes these columns until the Phase 24 issuer composes `register_request`.

## Deviations from Plan

**1. [Rule 3 - Blocking] `tests/test_risk_reservations_pg.py` edited (one line)**
- **Found during:** Task 1 verification.
- **Issue:** `test_the_store_has_no_delete_path` pins the exact public method set of `PgRiskReservationStore`; the new read `list_margin_claims` made it fail. The file is named under "Pins this plan updates" in the plan body but not in `files_modified`.
- **Fix:** added `"list_margin_claims"` to the expected set. The test still guards against a delete path.
- **Commit:** 333d90fe

**2. Intermediate commit state.** Between 333d90fe and 064c523a the two head-pin tests (`test_migrated_database_is_at_the_script_directory_head`, Phase 21 gate invariant 6) were red, because the plan puts the pin moves in Task 2. Sibling plan 22-06 saw this once (recorded in its SUMMARY) and left the file alone. Both are green at HEAD.

**3. Shared-tree note.** `docs/data/` is matched by a `.gitignore` rule although `DATA_MODEL.md` is tracked; `git add` refuses it, the path-limited `git commit -- <paths>` picks up the tracked modification (verified in the commit stat).

Otherwise the plan was executed as written. `reserve_in`, `release`, `mark_placed`, `mark_open`, `src/persistence/approvals.py`, `make_reserving_save_atomic` and `CountedReservation` are untouched, and `_request_from_row` (used by `reserve_in`) deliberately does not read the trio.

## Known Stubs

None. Nothing writes the trio yet: the Phase 24 issuer composes `register_request` (stated in the plan; no stub in code).

## Threat Flags

None beyond the plan's register (T-22-23..T-22-26 are addressed: nullable columns with no backfill, identity comparison of the trio, durable claims visible across connections once committed, tested real downgrade).

## Self-Check: PASSED

- `src/db/alembic/versions/0012_reservation_margin.py` and `tests/test_risk_reservation_margin_pg.py` exist.
- Commits 333d90fe and 064c523a are ancestors of HEAD.
