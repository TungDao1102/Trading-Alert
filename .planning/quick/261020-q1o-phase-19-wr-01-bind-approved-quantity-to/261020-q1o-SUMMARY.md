---
phase: quick-261020-q1o
plan: 01
subsystem: execution-binding
tags: [phase-19, review-fix, WR-01, D078, approval, alembic, bind_plan]
requires:
  - "Phase 19 review finding WR-01 (19-REVIEW.md); owner option (a)"
provides:
  - "approvals.approved_quantity (migration 0006) bound at placement by bind_plan"
  - "DECISIONS D078; provisional D-10 / Q5 ids moved to D079 / D080"
affects:
  - src/execution/binding.py
  - src/execution/manager.py
  - src/persistence/approvals.py
  - src/paper/shadow.py
  - scripts/demo_rehearsal.py
key-files:
  created:
    - src/db/alembic/versions/0006_approval_quantity.py
  modified:
    - src/domain/approval.py
    - src/db/models.py
    - src/db/mappers.py
    - src/execution/binding.py
    - src/execution/manager.py
    - src/persistence/approvals.py
    - src/paper/shadow.py
    - scripts/demo_rehearsal.py
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/GLOSSARY.md
    - docs/data/DATA_MODEL.md
    - .planning/phases/19-execution-plan-binding-price-check/19-REVIEW-FIX.md
    - .planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md
key-decisions:
  - "D078: plain Decimal (not a hash) stored on the approval row; NULL for older rows is refused (APPROVED_QUANTITY_MISSING), no backfill"
  - "Equality at binding (PLAN_QUANTITY_MISMATCH); the at-most rule stays at gate 5b"
requirements: [RISK-04, APRV-01]
status: complete
commits: 5
plan_head_before: 18991a7caafe9e1dc156aa665b71198c4c1a716e
plan_head_after: 08d62cb
actuals:
  tasks: 3
  commits: 5
---

# Phase quick-261020-q1o Plan 01: WR-01 approved quantity bound to the approval row

**An inflated TradePlan quantity can no longer pass the hash checks and place a larger order: `bind_plan` now requires the plan's `quantity_after_rounding` to equal the `approved_quantity` stored on the approval row (migration 0006), and an older row without one is refused before any exchange call.**

## Commits

| Task | Commit | Message |
|---|---|---|
| 1 RED | `e0801ac` | test(19): WR-01 failing tests for the approved quantity bound |
| 1 GREEN | `1ea1c3b` | fix(19): WR-01 bind the approved quantity stored on the approval row |
| 2 RED | `8497f5c` | test(19): WR-01 failing tests for the approval quantity writers and store |
| 2 GREEN | `ca49a5c` | fix(19): WR-01 approval writers store the issued quantity; the store guards it |
| 3 | `08d62cb` | docs(19): D078 records the approved quantity on the approval row; provisional D-10/Q5 ids move to D079/D080 |

Nothing pushed. This SUMMARY.md and the `.planning/STATE.md` edit (see below) are NOT committed, as instructed.

## What was built

- `Approval.approved_quantity: Decimal | None = None` (last field; None or finite positive Decimal), `ApprovalRow.approved_quantity` NUMERIC(38,18) NULL, CHECK `ck_approvals_approved_quantity`, both mapper directions.
- Alembic revision `0006_approval_quantity` (hand-written, imports no project module, real downgrade).
- `bind_plan(..., approval_quantity=...)` required keyword; step 5 after the side check: None gives `APPROVED_QUANTITY_MISSING`, non-Decimal raises `TypeError`, unequal gives `PLAN_QUANTITY_MISMATCH`. `BoundPlan.approved_quantity` is the approval's value. Manager gate 1c passes `approval.approved_quantity`; gate 5b code is unchanged.
- `PgApprovalStore.insert_pending`: `approved_quantity` in the request identity; more than 18 fractional digits raises `PrecisionError` (never rounded); `_decide` untouched, so a decision never rewrites it.
- Writers: `ShadowApprovalBook.issue` and `scripts/demo_rehearsal.py::issue_approval` store the issued plan's `quantity_after_rounding`.
- Docs: DECISIONS D078, DOC_STATUS line, GLOSSARY 9.3 (two new codes, revised `QUANTITY_ABOVE_APPROVED`), DATA_MODEL 2.5, Phase 19 gate inventory, REVIEW-FIX batch 4, OWNER-GAPS WR-01 row, provisional ids D-10 to D079 and Q5 to D080 (both stay drafts).

## RED evidence

- Before any test edit, a scratch test at base `18991a7` (deleted, not committed): the golden case with the plan object's quantity set to 2.416 (unhashed field) reached `place_entry` and returned `OK`. That is the defect.
- `e0801ac`: `tests/test_execution_binding.py` fails at collection (`ImportError: APPROVED_QUANTITY_MISSING`); manager and rehearsal tests fail with `TypeError` (`Approval` has no `approved_quantity`). So the new manager tests fail at the base through the missing field, not through the placing behavior (that was shown by the scratch run).
- `8497f5c`: three tests failed at the base (SHADOW rows carry the quantity; replay with a different quantity is a `RowConflict`; 19 fractional digits give `PrecisionError`). The other new tests of that commit (domain validation, mapper round trip, Demo writer, migration 0006) already passed because those parts landed in the Task 1 GREEN commit.

## Existing tests that changed, and why

- `tests/test_execution_manager.py`: `_build_approval` now sets `approved_quantity` from the fixture field `quantity_after_rounding` (no fixture file changed). `test_risk04_quantity_above_the_approved_quantity_is_never_clipped` moves the approval to 2.414 with the plan (otherwise gate 1c would refuse first); `_assert_refused_then_placeable_with_risk` forwards extra overrides. `_order_pairs`: the two `small_plan_quantity()` cases pass an approval at 2.414 (reasons unchanged) and a new pair pins gate 1c before enablement.
- `tests/test_execution_binding.py`: `_bind` helper and the direct call in `test_signal_or_approval_identity_mismatch` pass `approval_quantity`.
- `tests/test_demo_rehearsal_flow.py::test_build_live_context_binds_to_the_derived_plan`: the `bind_plan` call passes `approval_quantity`.
- `tests/test_persistence_migration_pg.py`: head-revision test now pins `0006_approval_quantity` (was 0005).
- `tests/test_phase19_gate.py`: inventory only (two codes, two symbols, 0006 file, two RISK-04 tests).

## Verification (real results)

All sequential (pytest-xdist is not installed in this environment, so `-n 4` could not be used; I did not run `uv sync` to avoid changing the shared environment). PG files ran with `TRADING_CI_STRICT=1` and the process-env `TEST_DATABASE_URL` (value never printed).

| Check | Result |
|---|---|
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 667 files already formatted |
| `uv run mypy src` | Success, 214 source files |
| `uv lock --check` | Resolved 62 packages, no change |
| `verify_decision_alignment.py all` | ALL_PASS |
| Task 1 non-PG (binding, manager, demo flow, exchange_error_rejections) | 295 passed, 0 skipped |
| Task 1 PG (7 files) | 135 passed, 0 skipped |
| Task 2 non-PG (9 files) | 323 passed, 0 skipped |
| Task 2 PG (6 files) | 162 passed, 0 skipped |
| Task 3 docs/gate group (13 file groups) | 674 passed, 0 skipped |
| Other Approval-building / approvals-reading files (11) | 301 passed, 0 skipped |

Counts overlap between runs; they are not additive. NOT run: the full suite, `-m docker`, any Demo / `--execute` / network. A host database upgrade to 0006 was not exercised (only throwaway `t17_*_test` databases).

`git diff 18991a7 HEAD` shows no change to `params/`, `config/`, `AGENTS.md`, `src/core/planner.py`, `src/persistence/execution_state.py`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `pyproject.toml` or `uv.lock`, and no deleted file.

## Owner choices to confirm (same nine as REVIEW-FIX batch 4)

1. Plain Decimal, not a hash (the bound is an order comparison).
2. Nullable column; older rows refused as `APPROVED_QUANTITY_MISSING`; no backfill.
3. Equality at binding; the "at most" rule stays at gate 5b.
4. The quantity is stored on both the APPROVE and the SKIP rows.
5. The stored figure is the plan's `quantity_after_rounding` (what the SHADOW confirmation card shows); the APPROVE and Demo messages show no quantity (Phase 23).
6. Residual: the Approval object is caller-supplied; a consume-time DB check (not null and at least the intended quantity) is not built.
7. Two new reason codes rather than reusing `QUANTITY_ABOVE_APPROVED`.
8. The 18-digit precision guard (never round).
9. A host takes revision 0006 through the compose `migrate` service; existing approval rows read NULL; soak `IMAGE_COMMIT` `9b27da5` predates it.

## Deviations from Plan

**1. [Rule 3 - Blocking] Demo rehearsal writer moved from Task 2 to Task 1.** Task 1's verify includes `tests/test_demo_rehearsal_flow.py`, whose flow builds its approval through `scripts/demo_rehearsal.py::issue_approval`; with the required `approval_quantity` and a NULL approval quantity every rehearsal flow test failed with `APPROVED_QUANTITY_MISSING`. The one-line writer fix therefore landed in `1ea1c3b`, and the Task 2 RED commit has fewer failing tests than planned (documented above and in REVIEW-FIX batch 4). Files: `scripts/demo_rehearsal.py`. Commit `1ea1c3b`.

**2. Instruction conflict resolved in favour of the run constraints.** The plan's Task 3 commit lists `.planning/STATE.md`; the run constraints say not to commit STATE.md. I edited `.planning/STATE.md` line 43 (provisional ids D079/D080, D077 and D078 written) but did NOT commit it: it is a modified, uncommitted file for the orchestrator's state commit.

**3. `-n 4` not used.** `pytest-xdist` is not installed in the active environment (`uv run pytest -n` is rejected); sequential runs were used instead.

No auth gates. No stubs were introduced (no hardcoded empty values, TODO or placeholder text in the added code).

## Threat Flags

None. The change adds no network endpoint or auth path; it tightens an existing trust boundary (threat register T-q1o-01 to T-q1o-05 mitigated and tested; T-q1o-06 accepted and listed for the owner as choice 6; T-q1o-07 recorded in OWNER-GAPS and REVIEW-FIX choice 9).

## Self-Check: PASSED

- Created file present: `src/db/alembic/versions/0006_approval_quantity.py`.
- Commits `e0801ac`, `1ea1c3b`, `8497f5c`, `ca49a5c`, `08d62cb` are ancestors of HEAD; `commits:` was measured as `git rev-list --count 18991a7..HEAD` = 5.
