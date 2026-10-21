---
phase: 20-reconcile-safe-mode-hardening
plan: 22
subsystem: ops
tags: [alerts, safe-mode, OPS-05, execution]
requires: [20-10, 20-11, 20-12, 20-13, 20-15, 20-16, 20-17, 20-19, 20-20, 20-25]
provides:
  - "SafeModeController(on_enter=...) observer; load() and rehydrate() accept it"
  - "SafeModeAlertObserver, DEDICATED_PRODUCER_REASONS, event SAFE_MODE_ENTERED, OPS05_MATRIX / Ops05Row in src/ops/alerts.py"
  - "ALERT_PROTECTIVE_REJECTED in protection.py (B5 branch)"
  - "LivePlacementContext.alert_sink and ALERT_DUPLICATE_EXECUTION_ATTEMPT in manager.py"
  - "emergency_manual_close(alert_sink=) alerting MANUAL_CLOSE_ORPHAN_UNVERIFIED"
affects: [20-24]
key-files:
  created: [tests/test_alert_producers.py, tests/test_alerts_ops05_matrix.py]
  modified:
    - src/reconcile/safe_mode.py
    - src/ops/alerts.py
    - src/execution/protection.py
    - src/execution/manager.py
    - src/execution/live_context.py
    - tests/test_alerts.py
    - tests/test_controller_rehydrate.py
    - tests/test_demo_rehearsal_flow.py
    - tests/test_exchange_error_rejections.py
    - tests/test_execution_manager.py
    - tests/test_manual_controls.py
    - tests/test_protection_branches.py
key-decisions:
  - "Owner decision O-F, D-24 line: accept (read from 20-10-SUMMARY.md; the D-11, D-15 and D-01a lines were not relied on)"
  - "safe_mode.py stays free of src.ops: the observer is a plain callable, the alert mapping lives in src/ops/alerts.py"
  - "DEDICATED_PRODUCER_REASONS is a literal set in alerts.py (alerts.py may not import src.reconcile); a parity test pins it against classify.POLICY_BY_KIND"
status: complete
commits: 4
plan_head_before: 54318f0109e134c6512d76d624875d8a77836592
plan_head_after: 056df00b32cbf72d52cab6501c753673152d9bce
actuals:
  tokens: 60000
  tasks: 3
  commits: 4
---

# Phase 20 Plan 22: Alert producers and the OPS-05 matrix Summary

The entry-path SAFE_MODE reasons, a rejected stop, a duplicate execution attempt and an unverifiable manual close now reach the plan 20-13 sink, and `OPS05_MATRIX` states for every OPS-05 alert who produces it and what Phase 20 does and does not deliver. OPS-05 is NOT complete end-to-end: DAILY_STOP and DAILY_LOSS_WARNING have a contract and a test trigger only (producer: Phase 21).

## What was built

- **Task 1 (tracer).** `SafeModeController` takes `on_enter(reason, now_utc)`, called once per entry and once per re-entry with a new reason, after the flag flip, the journal row and the save attempt (also when the save raised, so the operator hears about a SAFE_MODE whose store is down; a raising observer is swallowed). `SafeModeAlertObserver` maps ENTRY_STATE_UNKNOWN, PROTECTION_HANDOFF_FAILED and DB_FAILURE to their own events, stays silent for reasons with a dedicated producer, and sends `SAFE_MODE_ENTERED` (HIGH) for every other reason. Subject is `SYSTEM`; the reason is the code or `INVALID_REASON`. `SafeModeController.load()` and `rehydrate()` accept `on_enter`, and an unreadable store at start alerts `SAFE_MODE_ENTERED` / `SAFE_MODE_STATE_UNREADABLE` once (that entry does not pass through `enter_safe_mode`).
- **Task 2.** B5 alerts `PROTECTIVE_REJECTED` right after `CLOSE_REQUIRED` (both best-effort, close flow unchanged, once per plan). `LivePlacementContext.alert_sink` (optional, default None, must offer `alert(...)`); the two replay returns of `execute_approved_plan` alert `DUPLICATE_EXECUTION_ATTEMPT` (reasons `STORED_OUTCOME_REPLAY`, `CONSUME_RACE_LOST`, subject the plan hash). Nothing else in the order flow changed; a failing or absent sink changes no outcome. `emergency_manual_close(alert_sink=)` alerts `MANUAL_CLOSE_ORPHAN_UNVERIFIED` (reason `LEGS_NOT_PROVEN_GONE`) where it journals the same event.
- **Task 3.** `OPS05_MATRIX` (14 rows: the nine OPS-05 alerts expanded to their events plus the three D-24 rows). Tests: per-row event contract, journal-before-queue and dedupe through the real sink, AST proof that each named producer module owns the event name (or imports its `ALERT_<EVENT>` constant), DAILY rows list Phase 21 and "test trigger only", AUTH_FAILURE named only in the reconcile tick (`protection.py`, `emergency_close.py`, `manager.py` never mention it), and `test_journal_first_sink_matches_the_loop_and_coordinator_protocols` (signature parity of `alert` and `critical` with `ReconcileAlertSink` and `CriticalAlertSink`).

## Verification

- `uv run pytest -m "not docker"` on `tests/test_alert_producers.py`, `tests/test_alerts_ops05_matrix.py`, `tests/test_alerts.py`, `tests/test_execution_manager.py`, `tests/test_manual_controls.py`, `tests/test_protection_*.py`, `tests/test_emergency_market_close.py`, `tests/test_safe_mode_*.py`, `tests/test_controller_rehydrate.py`, `tests/test_demo_rehearsal_flow.py`, `tests/test_exchange_error_rejections.py`, `tests/test_reconcile_loop.py`, `tests/test_startup_recovery.py` and the other neighbours: all pass (full suite not run, per the orchestrator).
- `uv run mypy src`: no issues (235 files). `uv run ruff check` and `ruff format --check`: clean. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `git diff --exit-code -- pyproject.toml uv.lock`: clean (no dependency added).
- Evidence label: executed tests with a fake sink and fake adapters; nothing against Binance or Telegram. DAILY_STOP and the daily-loss WARNING have a test trigger only.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Neighbouring tests pinned the old behavior**
- **Found during:** Task 2 and the final neighbour run
- **Issue:** B5 now sends two alerts, `LivePlacementContext` has a ninth (optional) field and imports `typing`, and the controller constructor has a new keyword. Existing tests asserted the old shape.
- **Fix:** updated the expectations in `tests/test_protection_branches.py`, `tests/test_exchange_error_rejections.py`, `tests/test_demo_rehearsal_flow.py`, `tests/test_execution_manager.py` (`test_live_context_validates_every_field`, `test_live_context_module_is_pure`), `tests/test_controller_rehydrate.py` (`test_constructor_signatures_are_unchanged`) and the event-set pin in `tests/test_alerts.py` (adds SAFE_MODE_ENTERED); `tests/test_manual_controls.py::_close` forwards an optional `alert_sink`.
- **Commits:** 7e761c32, 3493674a, 056df00b

**2. [Rule 2 - Missing critical] on_enter on load/rehydrate and a fire-on-failed-save**
- **Found during:** Task 1
- **Issue:** the plan names SAFE_MODE_STATE_UNREADABLE as an alerted reason, but that entry is built inside `SafeModeController.load` without `enter_safe_mode`; and an observer called only after a successful save would stay silent exactly when the store is down.
- **Fix:** `load()`/`rehydrate()` take `on_enter` (the unreadable-start path notifies once); the observer runs in a `finally` after the journal and save attempt, still best-effort. The plan's "after flip, journal and save" holds for every successful path.
- **Commit:** 7e761c32

### Notes (no change made)

- **Severity of PROTECTIVE_REJECTED.** The plan text says "high severity"; plan 20-13 ratified it as CRITICAL in `ALERT_EVENTS` and `tests/test_alerts.py` pins that. Left as CRITICAL.
- **Matrix rows.** The plan's combined rows (UNPROTECTED_POSITION and CLOSE_REQUIRED; UNKNOWN_ORDER and FOREIGN_ORDER) are one row per event, so each event has its own producer and test case.
- **Producer coverage gaps, as designed.** The ENTRY_WITHOUT_PROTECTIVE entry from `require_protective_confirmation` and the TP_UNAVAILABLE path stay with their existing producers (listed in `DEDICATED_PRODUCER_REASONS`). Authentication failure is produced only by the reconcile tick; the coordinator, closer and manager journal the error class and do not alert it.
- **Composition is Phase 24.** Nothing in this plan builds the controller with `on_enter=SafeModeAlertObserver(sink)` or sets `LivePlacementContext.alert_sink` in production; no composition root exists yet. Until Phase 24 wires them, the alerts exist as tested mechanisms, not running producers in a deployed process.
- **CRLF.** Existing source files are CRLF in the working tree; they were edited byte-aware and stay CRLF. The two new test files were written with LF (git normalizes them under `core.autocrlf=true`).

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema; alert text carries only fixed codes, symbol and plan hash (T-20-57).

## Self-Check: PASSED

- Files present: `tests/test_alert_producers.py`, `tests/test_alerts_ops05_matrix.py`, this summary.
- Commits reachable from HEAD: 7e761c32, 3493674a, 74131da2, 056df00b.
