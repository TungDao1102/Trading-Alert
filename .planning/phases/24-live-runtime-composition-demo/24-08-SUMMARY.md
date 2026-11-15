---
phase: 24-live-runtime-composition-demo
plan: 08
subsystem: persistence
status: complete
tags: [mode-scope, approvals, confirm-sweep, shared-database, oq-6, c-7]
requirements-addressed: [APRV-01, EXEC-03]
requires: [24-01]
provides:
  - "PgShadowStores(db, confirm_mode=None|SHADOW|DEMO|LIVE): mode-scoped list_approved_approvals and an issue-time mode marker"
  - "journal event APPROVAL_MODE_RECORDED under correlation approval-mode:<approval_id>"
  - "PgApprovalStore.insert_pending(..., after_insert=hook): the hook runs in the insert transaction"
  - "InMemoryShadowStores(confirm_mode=...) and .scoped(mode): the fake mirror"
affects: [24-30]
tech-stack:
  added: []
  patterns:
    - "marker as a journal row in the same unit of work as the row it describes (as save_atomic after_decide)"
key-files:
  created:
    - tests/test_approval_mode_scope_pg.py
  modified:
    - src/persistence/shadow_stores.py
    - src/persistence/approvals.py
    - src/paper/runtime.py
    - scripts/shadow_rehearsal.py
    - src/approval/confirm_core.py
    - tests/shadow_fakes.py
    - tests/test_confirm_core.py
    - tests/test_paper_runtime_env.py
key-decisions:
  - "Marker event name APPROVAL_MODE_RECORDED, entity_type ApprovalMode, correlation approval-mode:<approval_id>, journal id prefix appr-mode (deterministic, step 'recorded'), payload the canonical JSON {\"mode\":\"<MODE>\"}; occurred_at_utc = the approval's requested_at_utc."
  - "The reader compares the marker payload as a whole against the three canonical payloads (no parsing of text); a marker payload this code did not write is listed by no scoped store (fail closed)."
  - "The marker is written only when the PENDING row is newly inserted, never on a replay no-op, so a replay can not re-mark an existing (possibly legacy SHADOW) row."
  - "confirm_mode=None stays the unscoped store (no marker, lists every APPROVED approval) for the existing tests."
metrics:
  tasks: 2
  commits: 2
actuals:
  tokens: 30000
  tasks: 2
  commits: 2
plan_head_before: 7bd629638a5d5013148b57e65165e76e46da87df
---

# Phase 24 Plan 08: Mode-scoped approval reader Summary

SHADOW and DEMO can share the compose PostgreSQL database: a store built for a mode writes a durable mode marker in the same transaction as every PENDING approval it inserts and lists only the APPROVED approvals of its own mode, so a DEMO orphan sweep never sees a SHADOW approval and the reverse (T-24-20, T-24-21; research C-7, OQ-6; owner answer 24-01 Q8, option A).

## Precondition

24-01-SUMMARY "Owner answers" records Q8 as the recommended mode-scoped reader on a shared database: holds. No override.

## What was built

- `src/persistence/shadow_stores.py`: `confirm_mode` keyword (validated against SHADOW, DEMO, LIVE, else `ValueError`); `insert_pending` passes an `after_insert` hook that appends the marker through `PgJournalStore.append` in the insert transaction; `list_approved_approvals` is one LEFT OUTER JOIN of `approvals` to the marker rows and applies `mode_includes`: SHADOW lists unmarked and SHADOW-marked rows, DEMO and LIVE list only their own marker, `None` lists everything. Pure helpers (`mode_marker_payload`, `mode_from_marker_payload`, `approval_mode_event`, `mode_includes`, `validate_confirm_mode`, `CONFIRM_MODES`) are shared with the fake.
- `src/persistence/approvals.py`: `insert_pending(approval, *, after_insert=None)`, mirroring `save_atomic(after_decide=...)`; the hook runs only on a new insert.
- `tests/shadow_fakes.py`: `InMemoryShadowStores(confirm_mode=...)`, the same rule, and `scoped(mode)` returning a second view over the same data (two processes, one database).
- `src/paper/runtime.py` and `scripts/shadow_rehearsal.py`: `confirm_mode="SHADOW"`. `src/approval/confirm_core.py`: the WR-06 comment now states the scoping rule. SHADOW texts, journal event names and Phase 16 behaviour are unchanged; the only addition for SHADOW is one `APPROVAL_MODE_RECORDED` row per newly inserted approval.
- No schema change: `git diff --exit-code -- src/db pyproject.toml uv.lock` exits 0.

## Verification

Run here (no PostgreSQL):

- `uv run pytest -m "not docker" tests/test_confirm_core.py tests/test_confirm_flow.py tests/test_approval_desk.py tests/test_paper_runtime_env.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_isolation.py tests/test_paper_test_signal_rehearsal.py`: all pass (5 new fake tests in test_confirm_core.py, 1 new in test_paper_runtime_env.py).
- `uv run mypy src`: no issues (263 files). `uv run ruff check` and `ruff format --check` clean on the touched files.
- The marker-aware SELECT was compiled against the PostgreSQL dialect (LEFT OUTER JOIN journal_events ON approval_id and event_type); `tests/test_approval_mode_scope_pg.py` collects (6 tests).

## Gap for the orchestrator (not run here)

Per the parallel-run rule, no PostgreSQL test was run (24-07 uses the shared test database). To run after the merge, with `TEST_DATABASE_URL` in the process environment and `TRADING_CI_STRICT=1`:

`uv run pytest -m "not docker" tests/test_approval_mode_scope_pg.py tests/test_approval_replay_pg.py tests/test_persistence_approvals_pg.py tests/test_paper_shadow_runtime_pg.py tests/test_paper_shadow_pg.py -x`

`tests/test_approval_mode_scope_pg.py` is therefore written but unproven on a real database; if it fails, the likely causes are in that test's setup (Approval fields, FK order), not the stores' contract.

## Deviations from Plan

**1. [Rule 3 - Blocking] Worktree base**
- The worktree was created at d9907ffc (master), which lacks Phase 23 (`confirm_core.py`) and 24-01..24-03. Its branch had no commits; it was reset to the develop tip 7bd62963, the base of the sibling wave-2 worktrees, before any work.

**2. [Rule 3 - Blocking] `src/persistence/approvals.py` modified**
- Not in the plan's `files_modified`: the marker must commit with the PENDING row, and `PgApprovalStore.insert_pending` had no way to join its transaction. Added the optional `after_insert` hook (default None, no behaviour change for other callers). Sibling wave-2 plans should not touch `insert_pending`; a merge conflict there would be small.

**3. Order of work**
- The new fake tests were written together with the implementation instead of strictly red-first; the tests exercise the rule (a pre-change store would not satisfy the cross-mode assertions).

## Known Stubs

None.

## Threat Flags

None. The marker is a journal row on the existing table; no new endpoint, auth path or schema.

## Self-Check: PASSED

Files and commits checked below.
