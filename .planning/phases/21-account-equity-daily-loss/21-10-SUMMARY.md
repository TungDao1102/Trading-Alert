---
phase: 21-account-equity-daily-loss
plan: 10
subsystem: execution
tags: [daily-stop, d033, ops-05, alerts, cancel-entries, fail-closed]
requires:
  - phase: 21
    provides: "plan 21-05 DayStateVerdict (src/risk/daily_loss.py); plan 21-02 execution limits"
provides:
  - "src/execution/daily_stop.py: enforce_daily_state, PlacedPlanRef, DailyStopOutcome, day_alert_subject, DAILY_STOP_TRIGGER, ALERT_* constants"
  - "manager._EXPIRY_TRIGGERS accepts 'daily_stop'"
  - "OPS05_MATRIX producer src/execution/daily_stop.py for DAILY_STOP and DAILY_LOSS_WARNING"
affects: [21-13, 21-14, 24]
tech-stack:
  added: []
  patterns: ["cancel first through the audited helper, alert after (WR-C8)", "per-item failures reported in an outcome, never raised"]
key-files:
  created: [src/execution/daily_stop.py, tests/test_daily_stop.py]
  modified: [src/execution/manager.py, src/ops/alerts.py, tests/test_alerts.py, tests/test_alerts_ops05_matrix.py, docs/operations/SECURITY_AND_OPERATIONS.md, docs/trading/EXECUTION_SPEC.md]
key-decisions:
  - "Entries are found on REST open normal orders per symbol of the placed plans and matched by the deterministic ENTRY client id; a system ENTRY id with no placed plan is only listed in unmatched_entry_orders"
  - "Only symbols of the placed plans are read, so an unknown system entry on another symbol is left to the reconcile tick (UNKNOWN_ORDER)"
  - "Alert failures and per-plan cancel failures are caught (type name only); asyncio.CancelledError passes through"
requirements-addressed: [RISK-02]
status: complete
duration: 35min
completed: 2026-10-23
commits: 2
plan_head_before: 848fafee566c05c53d2a82216a8f779bbf759d58
plan_head_after: 629ff61a26c85fdf3aec82db139461e9103d5f17
actuals:
  tokens: 28000
  tasks: 3
  commits: 2
---

# Phase 21 Plan 10: DAILY_STOP actions and alert producers Summary

At a latched DAILY_STOP, `enforce_daily_state` cancels the resting entry of every placed plan through `expire_pending_entry(trigger "daily_stop")`, never touches a stop or take-profit, and only then journals the DAILY_STOP / DAILY_LOSS_WARNING / DB_FAILURE alert; the OPS-05 matrix and both canonical docs now name this module as the producer.

## What was built

- Tasks 1 and 2 (commit e571b2ec): `src/execution/daily_stop.py` with the tracer path and the hardening in one pass. REST open orders per symbol, match by `derive_client_order_id(ENTRY)`, `expire_pending_entry` per match, verdict sorted into `cancelled` / `unverified` (FILLED_OR_PARTIAL, STILL_OPEN, GONE_NOT_CANCELED, UNKNOWN) / `not_cancelled` (gate refusal or any exception, type name only) / `unmatched_entry_orders`. Alerts after the cancels: DAILY_STOP and DAILY_LOSS_WARNING from `verdict.alerts_due` (subject `utc-day-YYYY-MM-DD`, reason = state value), DB_FAILURE for DAY_STATE_MISSING / DAY_STATE_UNREADABLE (no adapter call), nothing for the other blocked reasons. `manager.py` gets `"daily_stop"` in `_EXPIRY_TRIGGERS` and a docstring line (CRLF kept).
- Task 3 (commit 629ff61a): OPS05_MATRIX rows DAILY_STOP / DAILY_LOSS_WARNING with producer `src/execution/daily_stop.py` and "not wired in a running process until Phase 24"; DB_FAILURE row text names the day-state reasons; module and `emit_daily_state_alert` docstrings; matrix test renamed to `test_daily_state_rows_name_the_phase_21_producer` plus a DB_FAILURE row test; SECURITY_AND_OPERATIONS 5.1 rows and paragraph; EXECUTION_SPEC section 4 item 3 note. CRLF kept in every edited file.
- Tests: `tests/test_daily_stop.py`, 21 tests, one or more per behavior bullet (tracer with a filled ETHUSDT position whose closePosition stop stays open and zero `cancel_algo_order`; 429 pause refusal on the first cancel with the second still cancelled; fill racing the cancel; unmatched system entry and foreign order; idempotent second call; WARNING; NORMAL; DB_FAILURE reasons; other blocked reasons silent; failing sink with AuditRecordLost and RuntimeError; AST guard: no wall clock, no float, no protective or placement call in the module).

## Verification

- `tests/test_daily_stop.py tests/test_cancel_verification.py`: passed.
- `tests/test_alerts.py tests/test_alerts_ops05_matrix.py tests/test_alert_producers.py tests/test_daily_stop.py`: passed.
- `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py`: passed.
- `TRADING_CI_STRICT=1 tests/test_persistence_exit_evidence_pg.py`: passed on the final run.
- `uv run mypy` on daily_stop.py, manager.py, alerts.py: clean. `ruff check` and `ruff format --check` on the six plan files: clean.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `git diff --exit-code -- pyproject.toml uv.lock`: clean.
- Evidence label: executed tests with the Binance-semantics fake [DESIGN]; no [DEMO] claim; not wired in a running process (Phase 24).

## Deviations from Plan

None - plan executed as written. Tasks 1 and 2 share one commit because the module was written in one pass with its tests; the tests per task are still separate bullets.

Notes (not deviations):
- The first run of `test_persistence_exit_evidence_pg.py::test_persistence_module_map_lists_every_module` failed while sibling 21-09 had an untracked `src/persistence/day_risk.py`; the re-run passed once that sibling committed (same-wave unfinished work, not this plan's file).
- A sibling had `docs/data/DATA_MODEL.md` staged when the Task 3 commit ran; that file was swept into the first attempt of the commit. The commit was redone (soft reset of my own just-made commit, file unstaged, commit with explicit paths) so `629ff61a` holds this plan's five files only. `DATA_MODEL.md` is back as an unstaged modification for its owner.
- `git rev-list --count plan_head_before..HEAD` shows 7 because siblings 21-07, 21-09, 21-11 committed on the shared branch meanwhile; this plan's commits are the 2 above (`git log --grep "(21-10)"`).
- The set of symbols read is the symbols of the placed plans: a stray system ENTRY order on a symbol with no placed plan is not seen here (the reconcile tick reports it as UNKNOWN_ORDER).

## Known Stubs

None.

## Threat Flags

None. T-21-20 (no protective cancel) is asserted by the tests and an AST guard; T-21-21 (gate refusal, alert failure) by the refusal and sink-failure tests; T-21-22 by the fixed subject and enum reasons; T-21-SC by the clean `pyproject.toml` / `uv.lock` diff.

## Self-Check: PASSED

- src/execution/daily_stop.py and tests/test_daily_stop.py exist; commits e571b2ec and 629ff61a exist and are ancestors of HEAD.
