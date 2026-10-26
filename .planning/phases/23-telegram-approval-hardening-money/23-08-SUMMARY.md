---
phase: 23-telegram-approval-hardening-money
plan: 08
subsystem: persistence
status: awaiting-owner-decision
tags: [alembic, approvals, expiry, g4-042, owner-open-o-2]
requirements-addressed: [PAPER-02]
requires: [23-04, 23-07]
provides:
  - "src/db/alembic/versions/0014_decided_excl_expired.py: uq_approvals_one_decided_per_plan recreated with predicate status NOT IN ('PENDING','EXPIRED'), guarded downgrade"
  - "src/persistence/approvals.py: _decided_row_of_plan; EXPIRED on a plan with an APPROVED or SKIPPED row is refused with ApprovalAlreadyDecided(existing); race query selects APPROVED/SKIPPED only"
  - "tests/shadow_fakes.py: InMemoryShadowStores.save_atomic mirrors the same rule"
affects: [23-13]
key-files:
  created:
    - src/db/alembic/versions/0014_decided_excl_expired.py
  modified:
    - src/db/models.py
    - src/persistence/approvals.py
    - tests/shadow_fakes.py
    - tests/test_persistence_constraints_pg.py
    - tests/test_persistence_approvals_pg.py
    - tests/test_persistence_migration_pg.py
    - tests/test_risk_reservation_approval_pg.py
    - tests/test_phase21_gate.py
    - tests/test_phase22_gate.py
    - tests/test_paper_shadow_buttons.py
    - tests/test_paper_shadow_runtime.py
key-decisions:
  - "D-16 default of O-2 built and tested, NOT yet accepted by the owner (see Owner decision O-2)."
metrics:
  completed: 2026-10-26
commits: 3
plan_head_before: 19888f062ba56b4f55b029d98cf4bfe45f0d9dcc
plan_head_after: 3f4cc5e1dd470a7d474ac2f255713be155d39093
actuals:
  tokens: 60000
  tasks: 2
  commits: 3
---

# Phase 23 Plan 08: EXPIRED rows leave the one-decided-per-plan index (G4-042) Summary

Both PENDING siblings (APPROVE and SKIP_USER) of an undecided plan can now be expired at restart, while a decided plan's sibling is still refused by the store; the owner's O-2 answer is still required before anything merges.

## What was built

- Migration `0014_decided_excl_expired` (revises `0013_approval_money`, 25 characters, imports no project module): drops and recreates the unique partial index on `trade_plan_id` with `status NOT IN ('PENDING','EXPIRED')`. The downgrade counts plans with more than one non-PENDING row and raises `RuntimeError("cannot restore uq_approvals_one_decided_per_plan: N plans have more than one non-PENDING approval")` when N > 0, otherwise restores `status <> 'PENDING'`.
- ORM mirror: both `postgresql_where` and `sqlite_where` in `src/db/models.py`.
- Store rule (`PgApprovalStore._decide`): an EXPIRED decision first reads the plan's APPROVED or SKIPPED row inside the nested transaction and raises `ApprovalAlreadyDecided(existing)`; the IntegrityError race query uses the same helper (APPROVED/SKIPPED only), so it cannot raise `MultipleResultsFound` once several EXPIRED rows exist (T-23-25). The refusal happens before the Phase 21 `after_decide` hook, so a decided plan's reservation is never released as APPROVAL_EXPIRED by a sibling (T-23-24).
- Fake mirror: `InMemoryShadowStores.save_atomic` is blocked only by an APPROVED/SKIPPED sibling.

## Evidence (executed against local PostgreSQL, TRADING_CI_STRICT=1, no skips) [DESIGN]

- `tests/test_persistence_constraints_pg.py tests/test_persistence_approvals_pg.py tests/test_persistence_migration_pg.py tests/test_risk_reservation_approval_pg.py tests/test_paper_shadow_pg.py tests/test_paper_shadow_runtime_pg.py tests/test_approval_replay_pg.py tests/test_pg_fixture_guard.py tests/test_execution_exactly_once_pg.py`: 270 passed.
- `tests/test_phase21_gate.py tests/test_phase22_gate.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_buttons.py`: 153 passed; the wider SHADOW set (confirm, reservations, messages, confirm_core, telegram_failures): 288 passed.
- ruff check and format check on the 12 touched Python files: clean. mypy on models, approvals and the migration: no issues. `verify_decision_alignment.py all`: ALL_PASS. `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md docs/data/DATA_MODEL.md src/paper` exits 0.
- RED commit `3baf911f` failed exactly the six tests that need the new rule; the three "decided plan stays protected" tests passed already (old behaviour), as intended.

## Behaviour recorded by the tests

- Reservation hook, never-decided plan: the first EXPIRED decision releases the REQUESTED reservation (APPROVAL_EXPIRED, timestamp of the first decision); the second EXPIRED decision matches no REQUESTED row, so the release is a no-op and the first timestamp stays.
- The index alone does not refuse an EXPIRED row next to an APPROVED one (a test documents it); that refusal is the store's rule.
- Assumption A4: an APPROVE or SKIP decision on a plan whose sibling is already EXPIRED is no longer blocked by the index (a PENDING row of such a plan is only reachable if the sweep did not cover it; both tokens die at restart).

## Deviations from Plan

1. **[Rule 1 - superseded assertions] Two SHADOW tests asserted the old one-decided-per-plan expiry**: `tests/test_paper_shadow_buttons.py::test_restart_expires_pending_approvals_and_later_callbacks_are_rejected` (expected 2 expired and one EXPIRED row per plan) and `tests/test_paper_shadow_runtime.py::test_a_restart_expires_pending_approvals_and_confirms_before_polling_begins` (expected one EXPIRED row of the undecided plan). Updated to the new rule (4 expired, none left pending; both rows of the undecided plan EXPIRED). Not in the plan's files list but required by the plan's own verification commands. Two fake tests were added to the buttons file (both siblings expire; a decided plan's sibling stays LEFT_PENDING_SIBLING_DECIDED).
2. **[Rule 1] `test_partial_unique_index_states_its_exact_predicate`** in `tests/test_persistence_migration_pg.py` pinned the old predicate; PostgreSQL stores the new one as `<> ALL (ARRAY['PENDING','EXPIRED'])`, so the expected normalized text changed.
3. **Push not performed.** The coordinator asked for `git push origin develop` after every commit. AGENTS.md says never push and the owner pushes; the request came as an agent message, which cannot lift that rule, so no push was made. The three commits are local on develop.
4. Not edited, as the plan prohibits: `src/paper/shadow.py` (its `RestartReport` docstring still says one decided approval per plan and `left_pending` is now only the decided-plan case) and `src/paper/shadow_runtime.py` ~1121 (comment assumes one decided row per plan). Plan 23-13 or a later cleanup should adjust those wordings.

## Owner decision O-2

**PENDING.** The plan stops at a blocking-human checkpoint. Options: (a) keep this rule (plan 23-13 then writes the DECISIONS row and the DATA_MODEL line), (b) revert plan-level (`git revert` of the three commits `3baf911f`, `57ec8f5f`, `3f4cc5e1`, G4-042 stays open), (c) leave unmerged and OPEN (do not merge develop to master). Answer, verbatim, and date: _to be recorded on resume_.

## Known Stubs

None.

## Threat Flags

None. T-23-24, T-23-25, T-23-26 mitigated and tested; T-23-SC: no dependency change.

## Self-Check: PASSED

Files found: 0014 migration, all modified test files. Commits `3baf911f`, `57ec8f5f`, `3f4cc5e1` exist on develop. STATE.md and ROADMAP.md were deliberately not advanced because the plan is not complete until the owner answers O-2.
