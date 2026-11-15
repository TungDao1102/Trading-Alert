---
phase: 23-telegram-approval-hardening-money
plan: 04
subsystem: persistence
tags: [approvals, alembic, postgresql, actor_id, money_json]
requires:
  - phase: 23-02
    provides: MoneyAtStake canonical JSON (schema money-at-stake/1) that money_json will hold
provides:
  - "approvals.money_json (nullable TEXT, ck_approvals_money_json) and Alembic head 0013_approval_money"
  - "PgApprovalStore._decide persists actor_id with result, status and acted_at_utc"
  - "Approval.money_json domain field, part of the insert identity"
affects: [23-08, 23-09, 23-11, phase-24]
tech-stack:
  added: []
  patterns: ["one nullable column + one named CHECK per migration, no backfill, real downgrade"]
key-files:
  created:
    - src/db/alembic/versions/0013_approval_money.py
  modified:
    - src/db/models.py
    - src/db/mappers.py
    - src/domain/approval.py
    - src/persistence/approvals.py
    - tests/test_persistence_approvals_pg.py
    - tests/test_persistence_migration_pg.py
    - tests/test_phase21_gate.py
    - tests/test_phase22_gate.py
    - tests/test_domain_entities.py
    - tests/test_domain_mappers.py
    - docs/data/DATA_MODEL.md
key-decisions:
  - "money_json is a plain str in the domain (no risk-layer import); the risk layer parses it strictly at render time"
  - "Gate test functions renamed to ..._is_0013_approval_money; no REQUIREMENT_TESTS entry referenced the old names"
requirements-completed: [PAPER-02, APRV-01]
duration: 40min
completed: 2026-10-25
status: complete
commits: 3
plan_head_before: 760d89cb7f30d59ab2a9c0ae6a39ae053add6455
plan_head_after: e5c4cfe3154e5d2eef14a52e36dfd8eb5a1c3997
actuals:
  tokens: 8000
  tasks: 2
  commits: 3
---

# Phase 23 Plan 04: Decided actor and money block on the approval row Summary

**A decided approval now keeps who decided it and the money block the messages show: `_decide` writes `actor_id`, and migration 0013 adds `approvals.money_json` with a CHECK, written once with the PENDING rows and part of the insert identity.**

## Accomplishments
- Tracer (task 1): a PENDING approval with `money_json` is decided by user "777001" and read back by a new store instance with actor and money intact; a second decision or a lost race to the sibling row keeps the first actor (T-23-11).
- `money_json` is part of `_IDENTITY_FIELDS`: the same request again is a no-op, a different text or None is `RowConflict` (T-23-12); a decision never rewrites it.
- Migration `0013_approval_money` (revises `0012_reservation_margin`, imports no project module, real downgrade that keeps every row). CHECK `ck_approvals_money_json` refuses "", "x", "[1]", "{" (T-23-13).
- Head pins moved on purpose in `tests/test_persistence_migration_pg.py`, `tests/test_phase21_gate.py` (invariant 6) and `tests/test_phase22_gate.py` (invariant 7); DATA_MODEL section 2.5 documents `money_json` and the `actor_id` rule.

## Task Commits
1. RED: `f1daf230` test(23-04) - decided actor and money_json persist across store instances
2. Task 1 GREEN: `e1e1546e` feat(23-04) - migration, ORM, mappers, domain field, store
3. Task 2: `e5c4cfe3` test(23-04) - head pins, migration/mapper tests, DATA_MODEL 2.5

## Verification
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker"` on tests/test_persistence_migration_pg.py, test_persistence_approvals_pg.py, test_paper_shadow_pg.py, test_paper_shadow_runtime_pg.py, test_pg_fixture_guard.py, test_execution_exactly_once_pg.py, test_persistence_constraints_pg.py, test_approval_replay_pg.py: all passed, no skip (TEST_DATABASE_URL was set in the process environment; per-test cloned databases).
- `uv run pytest -m "not docker"` on test_domain_entities.py, test_domain_mappers.py, test_phase21_gate.py, test_phase22_gate.py: passed.
- Scoped ruff check, ruff format --check, mypy on the plan's files: clean. `verify_decision_alignment.py all`: ALL_PASS. `git diff` of pyproject.toml, uv.lock, params, config, enums: empty. CRLF files kept (`i/lf w/crlf`, numstat shows only added lines).

## Deviations from Plan

### Auto-fixed Issues
**1. [Rule 1 - Bug] Older downgrade test expected a column set that no longer holds**
- **Found during:** Task 2
- **Issue:** `test_downgrade_0006_keeps_rows_and_removes_only_the_column_and_the_check` asserted that downgrading to 0005 removes only `approved_quantity`; it now also passes 0013, so `money_json` leaves too (the plan expected older downgrade tests to be unaffected).
- **Fix:** assertion is now `{"approved_quantity", "money_json"}` with a comment.
- **Files modified:** tests/test_persistence_migration_pg.py
- **Commit:** e5c4cfe3

### Other notes
- The domain validation test for `money_json` was committed with the task 1 RED commit (it belongs to the task 1 behavior list) instead of task 2.
- The restart-expiry actor is tested at the store level (`save_atomic` with `actor_id="RUNTIME_RESTART"` on PostgreSQL); no existing `_pg` test asserted `""` for an EXPIRED row, so none had to change.
- Base: the worktree was created from a stale commit (6c759ef6) that lacked the phase 23 plan files. It had no work of its own, so it was reset to the `develop` tip (760d89cb, which holds plans 23-01 and 23-02) before starting. The orchestrator should merge from that base.
- STATE.md, ROADMAP.md and REQUIREMENTS.md were not touched (parallel run).

## Known Stubs
None.

## Threat Flags
None. No new endpoint or trust boundary beyond the plan's threat model.

## Self-Check: PASSED
- src/db/alembic/versions/0013_approval_money.py exists; commits f1daf230, e1e1546e, e5c4cfe3 are ancestors of HEAD.
