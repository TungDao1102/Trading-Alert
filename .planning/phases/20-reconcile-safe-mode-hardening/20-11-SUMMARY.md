---
phase: 20-reconcile-safe-mode-hardening
plan: 11
subsystem: execution-cancel-verification
tags: [cancel-verification, manual-close, emergency-close, sweeper, F-502, D-17, D-09, RISK-03, EXEC-06, tdd]
requires: [20-08]
provides:
  - "src.execution.cancel_verification: CancelVerdict, CancelDetail, PROVEN_GONE, confirm_entry_cancel, confirm_algo_cancel"
  - "expire_pending_entry returns a CancelVerdict; cancel_untriggered_protectives returns {role: CancelVerdict}"
  - "emergency_manual_close: protective legs cancelled only after two flat reads and a terminal entry"
  - "journal rows: phase cancel_unverified (ENTRY_EXPIRY, PROTECTIVE_CANCEL, ORPHAN_SWEEP), PROTECTIVES_KEPT, MANUAL_CLOSE_ORPHAN_UNVERIFIED, SWEEP_SKIPPED"
affects: [20-17, 20-19, 20-22]
tech-stack:
  added: []
  patterns: ["a cancel is not done until a query shows it", "stop is cancelled only with proof of no position", "exception class names only in audit payloads"]
key-files:
  created:
    - src/execution/cancel_verification.py
    - tests/test_cancel_verification.py
    - tests/test_manual_controls.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-11-SUMMARY.md
  modified:
    - src/execution/manager.py
    - src/reconcile/sweeper.py
    - tests/test_execution_emergency.py
    - tests/test_journal_failure_paths.py
    - tests/test_risk_first_spill.py
    - tests/test_execution_manager.py
    - tests/test_phase8_audit_reviewfix.py
key-decisions:
  - "cancel_unverified is a payload PHASE of the existing cancel event types (like pre_cancel, post_cancel, cancel_failed), not a new event_type; the verdict, Binance's observed status and the query's exception class are payload keys added only when set, so older event ids do not change."
  - "confirm_* take an optional CancelDetail out-parameter so the audit row can carry the observed status and the error class while the public result stays a CancelVerdict."
  - "A clean not-found right after an ENTRY cancel is UNKNOWN (it can mean FILLED); a clean not-found for an ALGO leg is GONE_NOT_CANCELED (nothing rests under the id; an absent algo order cannot hide exposure). Neither is called canceled."
  - "emergency_manual_close re-queries each leg itself after cancel_untriggered_protectives (which also verifies), so the orphan verdict does not depend on the first pass and survives an ExceptionGroup from the cancel step."
  - "When expire_pending_entry loses its audit record (AuditRecordLost) the verdict is lost with the exception; the manual close asks the exchange again instead of keeping the legs only because the journal is down."
requirements-addressed: []
status: complete
duration: about 2h
completed: 2026-10-21
estimate:
  tokens: 100000
  tasks: 3
actuals:
  tokens: 24000
  tasks: 3
  commits: 5
plan_head_before: 22df05e4c02b2adfdfdda1811ed8928dddd6f128
plan_head_after: 7755160ebbb1d2aaba6f88972e75949997b7b990
---

# Phase 20 Plan 11: Verified cancels and a manual close that keeps the stop Summary

A cancel is no longer counted until a query shows it, and `emergency_manual_close` can no longer remove the stop of an open position. A -2011 answer (the adapter maps it to the same `None` as a real cancel) now ends in a verdict: an entry that filled is `FILLED_OR_PARTIAL`, never "canceled". The manual close cancels the protective legs only after two independent fresh position reads are both zero and the entry is verified terminal; otherwise it cancels nothing protective and journals `PROTECTIVES_KEPT` with a reason code.

Base commit `22df05e4` (develop), branch `p20-11`. `commits: 5` is the measured `git rev-list --count 22df05e4..HEAD` taken at SUMMARY write, before the SUMMARY commit itself. All three tasks were finished; no split point was used. No requirement is marked complete (`requirements-addressed` is empty on purpose, as in 20-08; the plan frontmatter lists RISK-03, EXEC-06, EXEC-02 as the areas it contributes to).

## What was built

- `src/execution/cancel_verification.py` (new, pure: stdlib + `src.domain.algo_status`, no clock, no float, no SDK, no placement call)
  - `CancelVerdict`: `CANCELED`, `FILLED_OR_PARTIAL`, `STILL_OPEN`, `GONE_NOT_CANCELED`, `UNKNOWN`. `PROVEN_GONE` = `{CANCELED, GONE_NOT_CANCELED}`.
  - `confirm_entry_cancel(adapter, *, symbol, client_order_id)`: `found` must be exactly `True`; CANCELED -> CANCELED, FILLED / PARTIALLY_FILLED -> FILLED_OR_PARTIAL, EXPIRED / EXPIRED_IN_MATCH -> GONE_NOT_CANCELED, NEW -> STILL_OPEN, everything else (found not True, any other or non-string status, an exception) -> UNKNOWN.
  - `confirm_algo_cancel(adapter, *, client_algo_id)`: CANCELED -> CANCELED, NEW (class ACTIVE) -> STILL_OPEN, TRIGGERING / TRIGGERED / FINISHED and the TERMINAL_FAILED statuses REJECTED / EXPIRED -> GONE_NOT_CANCELED, found `False` -> GONE_NOT_CANCELED, unseen status, `found` not a bool, or an exception -> UNKNOWN. No new status string.
  - Never raises for the query (`Exception` -> UNKNOWN, only the class name is kept in `CancelDetail.error_type`); `CancelledError` passes through.
- `src/execution/manager.py`
  - `_cancel_then_audit(..., verify=...)`: the verification runs right after the cancel, inside the act-first action (before the pre-image is journaled), and decides the twin: `post_cancel` only for `CANCELED`, otherwise phase `cancel_unverified` with `verdict`, `observed_status` and `error_type` (class name). Without `verify` nothing changes. A failing cancel is still `cancel_failed` and is not verified.
  - `expire_pending_entry` returns the verdict. `cancel_untriggered_protectives` verifies each leg and returns `{STOP_LOSS|TAKE_PROFIT_1|TAKE_PROFIT_2: CancelVerdict}` (the group is raised instead when a leg raises).
  - `emergency_manual_close` order: disable, SAFE_MODE `MANUAL_CLOSE`, `expire_pending_entry` (verdict kept), up to two `snapshot_positions(symbol=...)` reads, then either the cancel of the three legs + an independent re-query of each (a leg not in `PROVEN_GONE` journals `MANUAL_CLOSE_ORPHAN_UNVERIFIED`, SAFE_MODE stays) or `PROTECTIVES_KEPT` with reason `FIRST_READ_NONZERO`, `SECOND_READ_NONZERO`, `READ_FAILED` or `ENTRY_NOT_TERMINAL`. Per-step isolation and the `ExceptionGroup` are kept. A read counts only when every row for the symbol has a `Decimal` `position_amt`; anything else is unreadable (fail closed). The function has no plan store and writes no TradePlan status (G4-036). `execute_approved_plan` is untouched (`git diff` has no hunk in it).
- `src/reconcile/sweeper.py`
  - Every skipped cancel (transient position gap, probe failure, cancel failure, unverified cancel) leaves a best-effort `SWEEP_SKIPPED` row: symbol, client algo id, reason code. The gap row carries the code `transient_position_gap` only (no read values), the others an exception class name; a journal failure on that row is swallowed. `SweepSkip.reason` strings are unchanged.
  - After the cancel the orphan is verified with `confirm_algo_cancel`; swept (and `post_cancel`, now with a `verdict` key) only for `CANCELED` / `GONE_NOT_CANCELED`; otherwise an `ORPHAN_SWEEP` row with phase `cancel_unverified` and the orphan is reported in `skipped` (`cancel_unverified: <VERDICT>`) so the next tick looks again. The sweeper keeps its journal-first pre-image. No placement token entered `src/reconcile`.

## Deviations from Plan

### Auto-fixed / plan-intent changes

**1. [Rule 1 - Pinned tests contradicted the plan] Tests that pinned the old behavior were updated; names kept, only the assertion or the double changed**
- `tests/test_execution_emergency.py::test_emergency_close_blocks_first_and_runs_every_step_despite_failures`: asserted all three protective cancels right after a failed entry cancel (the F1 defect). Now asserts one cancel (the entry's), two position reads and a `PROTECTIVES_KEPT` row; the docstring cites D-09 and EXECUTION_SPEC section 11. The happy-path test keeps its four cancels because its double now models a healthy flat exchange.
- The cancel doubles of `tests/test_execution_emergency.py` (`ContractCancelAdapter`), `tests/test_journal_failure_paths.py` (`RecordingCancelAdapter`) and `tests/test_risk_first_spill.py` (`CancelAdapter`) gained query and (flat) `snapshot_positions` methods so they answer like a healthy exchange; the queries are kept out of the lists that record the cancel calls, so the old call-order assertions hold unchanged.
- **Files outside the plan's `files_modified`:** `tests/test_execution_manager.py` (three hand-off tests: the default fake answers the verifying query with `None`; one now queues a `CANCELED` probe so `phases == ["pre_cancel", "post_cancel"]` still holds, two assert the last two calls are the cancel and its verifying query; `_probe` got a `status` parameter), `tests/test_risk_first_spill.py` (double only) and `tests/test_phase8_audit_reviewfix.py` (`_FakeSweepAdapter` answers the first query per algo id as before and every later one `CANCELED`, i.e. the verification query; three sweeper tests that assert a swept orphan depend on it). `tests/test_reconcile.py` is untouched (`git diff --exit-code` exits 0).

**2. [Plan intent] `cancel_unverified` is a payload phase, not a new `event_type`**
- The plan lists it under "new journal event types". It follows `pre_cancel` / `post_cancel` / `cancel_failed`, which are phases of `ENTRY_EXPIRY` / `PROTECTIVE_CANCEL` / `ORPHAN_SWEEP`. `PROTECTIVES_KEPT`, `MANUAL_CLOSE_ORPHAN_UNVERIFIED` and `SWEEP_SKIPPED` are real `event_type`s (`entity_type` TradePlan, TradePlan, OpenAlgoOrder).

**3. [Ordering] The verdict map of `cancel_untriggered_protectives` (listed under Task 3) was built in Task 2**
- Step 5 of the manual close needs verified legs, so the manager change landed with Task 2; its tests (`test_cancel_untriggered_protectives_returns_a_verdict_per_leg`, the stop-lost signal, the failing-leg group) were written in Task 3 and pass.

**4. [Test shape] "the fake plan store records zero status writes"**
- None of the three controls has a plan store parameter, so there is nothing to spy on. `test_no_manual_control_moves_a_trade_plan_to_expired` is a static guard: no `TradePlanStatus` / `EXPIRED` / status-writer name and no plan-store or status parameter in the three functions.

**5. `tests/support/fake_binance_exchange.py` was not changed.** It already models a cancel of a filled order (no-op, `None`), `cancel_algo`, the retention rule and `fail_next`; the new scripted behaviors (scripted position reads, an unreadable or sticky leg) live in small subclasses inside the new test files.

### Not done / limits

- `src/execution/protection.py::_sweep` (not in this plan's files) ignores the verdict map: it still sets `sweep_done = True` when `cancel_untriggered_protectives` does not raise, even if a leg verified `UNKNOWN` or `STILL_OPEN`. "The coordinator sweep logs a lost stop" is therefore a signal the caller can read, not yet wired. Owner of that follow-up: the plan that touches `protection.py` next (20-12 onward); not forced here.
- `emergency_manual_close` still returns `None` after a `MANUAL_CLOSE_ORPHAN_UNVERIFIED`; the journal row is the signal. Alerts for it are plan 20-22.
- `[NOT_TESTED]` What Binance does with closePosition legs when the position is closed outside the system (G4-035, A1/A3): both outcomes are modelled with the fake only. Owned by Phase 25. The -2011 semantics are `[DOC]` (official error-code page); the adapter's `None` mapping was read in code, not run.
- `[NOT_TESTED]` Real PostgreSQL, real adapter responses: the tests use the Binance-semantics fake and scripted adapters. No Binance, no Telegram, nothing `[DEMO]`.

## TDD Gate Compliance

Commits in order: `361c7e17` test + `dcd2e8ed` feat (Task 1, tracer); `3552f72b` test + `60a85208` fix (Task 2); `7755160e` feat with its tests (Task 3). No REFACTOR commit.

RED evidence (pytest failures seen before the GREEN commit; `gsd_run check tdd-red-evidence` does not parse pytest output and was not run):
- Task 1 RED: 35 failures, honestly mostly `ModuleNotFoundError` (the tests import `src.execution.cancel_verification` inside the test body); the behavior tests through `expire_pending_entry` (`test_absent_cancel_of_a_filled_entry_is_not_canceled` and the others) failed the same way. One test, the failing-cancel regression guard, passed already.
- Task 2 RED: 12 failures of `tests/test_manual_controls.py` on behavior (the stop was cancelled, `PROTECTIVES_KEPT` absent, a missing second `snapshot_positions`); 4 of the 16 tests passed already (for example the journal-outage control and the plan-status guard).
- Task 3: the sweeper change was written BEFORE its tests (an ordering slip). To get real RED evidence I saved the new `sweeper.py`, restored the committed one with `git checkout -- src/reconcile/sweeper.py`, ran the new tests (7 failed: the transient-gap skip row, the failing skip row, the traced probe and cancel failures, the verified swept orphan, the cancel that does not take effect, the unreadable verification, and the six-queries `test_manual_close_outside_system_orphan_swept`), and restored the new file. The other Task 3 tests (verdict map, stop-lost signal, both auto-cancel tests) passed against the Task 2 manager code by construction.

Tracer feedback gate: the Task 1 verify (`tests/test_cancel_verification.py`) passed end to end after the GREEN commit, together with the touched-module tests; the task has no `gate="blocking-human"`. Tracer verified end-to-end, expansion followed.

## Verification (only this plan's tests and tests of touched modules were run)

- `uv run pytest -m "not docker" tests/test_cancel_verification.py tests/test_manual_controls.py tests/test_execution_emergency.py tests/test_journal_failure_paths.py tests/test_risk_first_spill.py tests/test_reconcile.py` : all passed (sequential, at `7755160e`); `tests/test_cancel_verification.py` alone 48 passed, `tests/test_manual_controls.py` alone 16 passed.
- The same plus `tests/test_phase8_audit_reviewfix.py tests/test_execution_manager.py tests/test_drills.py` with `-n 4`: 378 passed.
- Modules that exercise the touched code: `tests/test_protection_*.py tests/test_execution_*.py tests/test_phase19_gate.py tests/test_demo_rehearsal_flow.py tests/test_safe_mode_persistence.py tests/test_journal_ids.py tests/test_domain_no_float.py` with `-n 4`: 796 passed.
- `uv run mypy src`: no issues in 220 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 687 files already formatted.
- `git diff --exit-code -- pyproject.toml uv.lock`: exit 0 (T-20-SC, no package added). `tests/test_reconcile.py::test_no_place_order_path_in_src_reconcile` passes and `git diff --exit-code 22df05e4 -- tests/test_reconcile.py` exits 0.
- AST guard: `test_cancel_verification_reads_no_wall_clock_and_builds_no_float` passes (`wall_clock_calls` and `float_constructor_calls` empty for `src/execution/cancel_verification.py`).
- Line endings: `manager.py`, `sweeper.py` and the five edited existing test files were converted to LF for editing and restored to pure CRLF (checked with `file` and `git ls-files --eol`); the new files are LF (git warns it will convert on checkout, as for the other new files of this phase). Git shows some of them as modified in `git status` only because the stat cache is dirty (`git diff` is empty).
- The full suite was not run (orchestrator). `scripts/verify_decision_alignment.py` was not run: AGENTS.md, docs and `.planning` rule files were not edited. STATE.md, ROADMAP.md, REQUIREMENTS.md and docs/DECISIONS.md were not touched.

## Acceptance map

| Criterion | Evidence |
|---|---|
| `test_absent_cancel_of_a_filled_entry_is_not_canceled` passes | yes (verdict FILLED_OR_PARTIAL, journal `pre_cancel` then `cancel_unverified`, no `post_cancel`) |
| wall-clock / float guard for `cancel_verification.py` | `test_cancel_verification_reads_no_wall_clock_and_builds_no_float` |
| a named test per Task 2 behavior bullet, incl. `test_manual_close_never_cancels_an_open_positions_stop` | yes in `tests/test_manual_controls.py` (open position, two flat reads, flat-then-nonzero, flat-then-failing, FILLED_OR_PARTIAL entry, orphan unverified x2, no plan status) |
| `git diff` shows no edit to `execute_approved_plan` | yes (no hunk touches it) |
| `test_manual_close_outside_system_auto_cancel` and `..._orphan_swept` | yes (plus a variant for legs still queryable inside the 3-day window) |
| `tests/test_reconcile.py` unedited and the no-placement guard passes | yes |
| ruff check, ruff format --check, mypy src | exit 0 |

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-20-25 (cancel interpretation) mitigated by `confirm_*` and the `post_cancel`-only-for-CANCELED rule; T-20-26 (manual close cancelling a live stop) mitigated by two zero reads, a terminal entry and `PROTECTIVES_KEPT`; T-20-27 (skipped sweeper cancels) mitigated by `SWEEP_SKIPPED`; T-20-SC mitigated. New journal rows carry codes, verdict values, Binance status strings and exception class names only; no new network surface, no new endpoint.

## Notes for dependents

- 20-17 (`operator_close_position`, re-place protection): the manual close now keeps the legs and says why; an operator close can rely on `PROTECTIVES_KEPT` / `MANUAL_CLOSE_ORPHAN_UNVERIFIED` rows and on `expire_pending_entry` / `cancel_untriggered_protectives` returning verdicts.
- 20-22 (alerts): wire `MANUAL_CLOSE_ORPHAN_UNVERIFIED` and the `cancel_unverified` rows; the payload keys are `verdict`, `observed_status`, `error_type`, `legs`.
- Whoever next edits `protection.py`: read the verdict map in `_sweep` before setting `sweep_done` (see "Not done").
- Any caller that treated the `None` return of `expire_pending_entry` / `cancel_untriggered_protectives` as "done" still works, but a cancel that did not verify is now visible only in the verdict and the journal.

## Self-Check: PASSED

- FOUND: src/execution/cancel_verification.py, src/execution/manager.py, src/reconcile/sweeper.py, tests/test_cancel_verification.py, tests/test_manual_controls.py
- FOUND commits: 361c7e17, dcd2e8ed, 3552f72b, 60a85208, 7755160e
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, params/, pyproject.toml, uv.lock, `.gsd/`, `.planning/config.json`, `.planning/state.json`, `.planning/milestone.lock`
