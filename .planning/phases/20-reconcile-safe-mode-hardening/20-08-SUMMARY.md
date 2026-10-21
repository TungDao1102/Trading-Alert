---
phase: 20-reconcile-safe-mode-hardening
plan: 08
subsystem: execution-risk-first
tags: [risk-first, spill, journal-outage, disable, cancel, emergency-close, F-702, D-16, tdd]
requires: [20-04, 20-05]
provides:
  - "src.ops.spill: LocalSpill, SpillToken, SpillRecord, SpillScan, SpillReplayReport, replay_spill, is_valid_event_id"
  - "src.ops.risk_first: act_then_record (async), record_after (sync), AuditRecordLost"
  - "optional spill keyword on LiveEnablementController (constructor, rehydrate), expire_pending_entry, cancel_untriggered_protectives, emergency_manual_close"
  - "tests/support/reconcile_doubles.py: RaisingJournal, RecordingJournal, FlakyJournal"
affects: [20-11, 20-17, 20-19]
tech-stack:
  added: []
  patterns: ["act first, record afterwards", "write-ahead spill, one atomic file per record", "exception class names only in audit text"]
key-files:
  created:
    - src/ops/spill.py
    - src/ops/risk_first.py
    - tests/support/reconcile_doubles.py
    - tests/test_risk_first_spill.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-08-SUMMARY.md
  modified:
    - src/execution/enablement.py
    - src/execution/manager.py
    - tests/test_journal_failure_paths.py
    - tests/test_controller_rehydrate.py
key-decisions:
  - "disable() builds its event while the prior state is known, flips the flag, then record_after; enable() stays journal-first (enabling is not risk-reducing)."
  - "_cancel_then_audit in manager.py is the one place that wraps a cancel: the pre-image is the write-ahead record (act_then_record), the post_cancel or cancel_failed twin goes through record_after. Event types, payload keys and deterministic ids come from the unchanged _build_cancel_event."
  - "On the healthy path the journal rows keep their order (pre_cancel then post_cancel or cancel_failed); only their position relative to the exchange call changed."
  - "A lost audit record in a failing-cancel path is attached to the cancel's own exception as a note (class names only); the cancel's exception is the one that is raised."
  - "A lost audit record per protective leg is collected into the existing ExceptionGroup; every leg is still attempted."
requirements-addressed: []
status: complete
duration: about 1h30
completed: 2026-10-21
estimate:
  tokens: 95000
  tasks: 3
actuals:
  tokens: 23000
  tasks: 3
  commits: 5
plan_head_before: 6ef390216a3fd3005614ff7e5fc8fb7efa15fc3f
plan_head_after: 571180f9ddc5848d877a2f77d5c1c898f97a07f6
---

# Phase 20 Plan 08: Risk-reducing controls act first Summary

A database or journal outage no longer keeps live orders enabled or withholds a cancel. `disable`, `expire_pending_entry`, `cancel_untriggered_protectives` and `emergency_manual_close` run their effect first; the audit record is written ahead to a local durable spill, recorded in the journal afterwards, and replayed later by `replay_spill`. A new entry during the same outage still ends NO_TRADE.

Base commit `6ef39021` (develop), branch `p20-08`. `commits: 5` is the measured `git rev-list --count 6ef39021..HEAD` taken at SUMMARY write, before the SUMMARY commit itself.

All three tasks were finished. No split point was used. No requirement is marked complete (`requirements-addressed` is empty on purpose; the plan frontmatter lists OPS-01, EXEC-06, RISK-03 as the areas it contributes to).

## What was built

- `src/ops/spill.py`
  - `LocalSpill(directory)`: creates the directory (mode 0o700 where honoured; Windows ACLs are not POSIX modes, see `.planning/WINDOWS.md`); `write(event)` serialises to canonical JSON (sorted keys, ISO UTC text), writes `.<id>.json.<pid>.tmp`, fsyncs, moves it into `<journal_event_id>.json` with `src.data.store.replace_with_retry` (imported, not re-implemented), best-effort directory fsync off Windows; `discard(token)`; `scan()` / `pending()` / `corrupt()`.
  - File names are the validated journal id only (`[A-Za-z0-9][A-Za-z0-9_-]{0,127}`): nothing with a dot, separator or whitespace can be written or is accepted as a record.
  - `write` refuses to overwrite a spill file whose content differs (`FileExistsError`); an identical rewrite is an idempotent replace.
  - `replay_spill(spill, journal)` returns `SpillReplayReport(replayed, already_present, conflicts, corrupt, failed)` with ids, reason codes and exception class names only. If the journal has `get` (the real `PgJournalStore` does) an identical stored event is `already_present` and a different one is a conflict without writing; otherwise `record` runs and a `JournalConflict` is a conflict. Conflicting, corrupt and failed files are kept.
- `src/ops/risk_first.py`: `record_after`, `act_then_record`, `AuditRecordLost` (message and notes carry the event id and exception class names only). A spill failure before the action is remembered, never raised.
- `src/execution/enablement.py`: `spill: LocalSpill | None = None` on the constructor and `rehydrate`; `disable` flips then `record_after`; the event builder was split from the recording so `enable` stays journal-first.
- `src/execution/manager.py`: `_cancel_then_audit` helper; `spill` keyword (default None) on the three functions; `emergency_manual_close` keeps its step order (plan 20-11 owns the reorder) and passes `spill` to both cancel steps.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 1 - Pinned test contradicted the plan] `test_constructor_signatures_are_unchanged` asserted the enablement constructor parameters are exactly `["self", "journal"]`**
- **Found during:** Task 1 verification (tests of a module I modified).
- **Fix:** only that assertion changed, to `["self", "journal", "spill"]` plus `default is None`; the test keeps its name (same treatment as plan 20-06 gave to the SafeModeController line in the same test).
- **File:** `tests/test_controller_rehydrate.py`. **Commit:** `73088379`.

**2. [Plan intent] Phase 17 pins that said "journal failure prevents the cancel" were rewritten and renamed**
- The four tests in `tests/test_journal_failure_paths.py` that pinned F-702 (`disable` stays enabled; no cancel when the journal is down for expire, protectives, emergency close) now assert the new rule. Their names described the old behaviour, so they were renamed (each docstring names F-702 and the old name): `test_disable_with_a_failing_journal_flips_the_flag_and_raises_audit_record_lost`, `test_expire_pending_entry_still_cancels_when_the_journal_is_down`, `test_cancel_untriggered_protectives_cancels_every_leg_in_an_outage`, `test_emergency_close_in_an_outage_runs_every_step_and_reaches_the_exchange`. The module docstring was rewritten to match. The pytest node ids of these four changed.
- **Commits:** `646166d3`, `56336fe8`.

**3. Additions beyond the plan's interface list (small, same module)**
- `SpillReplayReport.failed` and `is_clean`: a journal that is still down during replay is neither a conflict nor corrupt, so it needed its own bucket (kept file, id plus exception class name).
- `LocalSpill.scan()` and `SpillScan` so `pending()` and `corrupt()` share one directory pass.
- `rehydrate(..., spill=None)` on `LiveEnablementController`, otherwise a restored controller could not carry a spill.

**4. Files named in `files_modified` that were not changed**
- `tests/test_execution_enablement.py` and `tests/test_execution_emergency.py` needed no edit: no test there pinned a journal-first disable or a pre-cancel journal write, and both pass unchanged. `tests/test_controller_rehydrate.py` was changed instead (item 1).

### Not done / limits

- `emergency_manual_close` still lets `SafeModeController.enter_safe_mode` raise `StoreUnavailable` from its own journal write (flag set first, as today). Making SAFE_MODE journaling act-first is not part of this plan (20-06 owns SAFE_MODE durability); the test pins the current result (one `StoreUnavailable` in the group).
- Who constructs a `LocalSpill` in production, where it lives on the host, and what a restart does with its contents are plan 20-19. Nothing is wired into a runtime here; `spill` defaults to None everywhere.
- `[NOT_TESTED]` Windows file replace under a real indexer or antivirus lock: only the existing `replace_with_retry` helper is used, and no test provokes a `PermissionError`.
- `[NOT_TESTED]` Behaviour against a real PostgreSQL outage: the tests use fakes (`RaisingJournal`, `ToggleJournal`, `FailingIntentStore`). No Binance, no Telegram, nothing `[DEMO]`.
- The spill is supplementary evidence of what this process did; it is never a substitute for Binance truth, and a missing or empty spill proves nothing (D-30).

## TDD Gate Compliance

Tracer first, then two further pairs. Commits in order: `646166d3` test, `73088379` feat (Task 1); `56336fe8` test, `49d51a5b` feat (Task 2); `571180f9` test (Task 3). No REFACTOR commit.

RED evidence (pytest failures seen before each GREEN commit; `gsd_run check tdd-red-evidence` does not parse pytest output and was not run):
- Task 1 RED: 15 failures. Honest note: the tests import `src.ops.spill` / `src.ops.risk_first` inside the test body, so the failures are `ModuleNotFoundError` (a missing module), not assertion failures on the behaviour. The rewritten `test_disable_with_a_failing_journal_flips_the_flag_and_raises_audit_record_lost` failed the same way.
- Task 2 RED: 11 failures: eight in `tests/test_risk_first_spill.py` (mostly `TypeError: ... got an unexpected keyword argument 'spill'`; the lost-audit-record test failed on `StoreUnavailable` surfacing instead of `AuditRecordLost`) and the three rewritten pins in `tests/test_journal_failure_paths.py` (assertion failures: the old code raised `StoreUnavailable` and issued no cancel).
- Task 3: there was no separate RED. The robustness cases (missing directory, corrupt file, conflict, partial replay, bad names) were already satisfied by the `spill.py` written in Task 1, so the 29 new tests passed on first run (52 in the file). They are regression guards; no `feat` commit exists for Task 3. Not claimed as RED/GREEN.

Tracer feedback gate: the Task 1 verify (`tests/test_risk_first_spill.py tests/test_execution_enablement.py tests/test_journal_failure_paths.py`) was re-run after the GREEN commit and passed; the task has no `gate="blocking-human"`.

## Verification (only this plan's tests and tests of touched files were run)

- `uv run pytest -m "not docker" tests/test_risk_first_spill.py tests/test_execution_enablement.py tests/test_journal_failure_paths.py tests/test_execution_emergency.py tests/test_protection_branches.py tests/test_controller_rehydrate.py`: 161 passed (final run at `571180f9`; `tests/test_risk_first_spill.py` alone: 52 passed).
- Also run because they exercise the touched modules (before the Task 3 test-only commit): `tests/test_execution_manager.py tests/test_execution_attach.py tests/test_drills.py tests/test_execution_secret_posture.py tests/test_paper_shadow_isolation.py tests/test_phase19_gate.py` and the `tests/test_protection_*.py` files with `-n 4`: all passed (counts not recorded; the output showed no failure); plus `tests/test_execution_gates.py tests/test_execution_health.py tests/test_demo_rehearsal_safety.py tests/test_demo_rehearsal_flow.py tests/test_kill_gate_event.py tests/test_domain_no_float.py` in the first Task 1 run (all passed except the constructor-signature test, fixed in deviation 1).
- `uv run mypy src`: no issues in 219 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 683 files already formatted.
- `git diff --exit-code -- pyproject.toml uv.lock`: exit 0 (T-20-SC, no package added).
- `tests/test_risk_first_spill.py::test_new_modules_read_no_wall_clock_and_build_no_float[spill.py|risk_first.py]` passes (`wall_clock_calls` and `float_constructor_calls` are empty).
- Line endings preserved: `enablement.py`, `manager.py`, `test_journal_failure_paths.py`, `test_controller_rehydrate.py` were converted to LF for editing and restored to pure CRLF (checked with `file`). New files are LF (git warns it will convert on checkout, as for the other new files in this repo).
- The full suite was not run (orchestrator). `scripts/verify_decision_alignment.py` was not run: AGENTS.md, docs and `.planning` rule files were not edited.

## Acceptance map

| Criterion | Evidence |
|---|---|
| `test_disable_flips_with_journal_always_raising` passes | yes, in the run above |
| AST guards for spill.py and risk_first.py | `test_new_modules_read_no_wall_clock_and_build_no_float` |
| One journal-always-raising test per control asserting the exchange call count | `test_disable_flips_with_journal_always_raising` (flag), `test_expire_pending_entry_cancels_with_journal_always_raising` (1 call), `test_cancel_untriggered_protectives_cancels_all_legs_with_journal_always_raising` (3 calls, SL -> TP1 -> TP2), `test_emergency_manual_close_runs_every_step_with_journal_always_raising` (4 calls) |
| New entry during an outage is NO_TRADE | `test_a_store_outage_blocks_a_new_entry_but_none_of_the_risk_reducing_controls` (FailingIntentStore on `consume_and_record_entry_intent`, `is_no_trade` True, zero placements) |
| A named test per Task 3 behaviour bullet | directory deleted, corrupt file, conflict, first-ok-second-conflict, invalid name: all present |

## Known Stubs

None. `spill` defaults to None; that is intended wiring left to plan 20-19, not a stub that blocks this plan's goal.

## Threat Flags

None beyond the plan's register. T-20-17 (DoS) mitigated by act-first plus per-control outage tests; T-20-18 (spill tampering) mitigated by id-validated names, identical-replay no-op, conflict kept; T-20-19 (disclosure) mitigated: class names only in spill-derived messages, the existing event payloads carry no credentials; T-20-SC mitigated. New local file surface: a directory the operator chooses (`LocalSpill(directory)`), no network, no new endpoint.

## Notes for dependents

- 20-11: reorder `emergency_manual_close` (cancel protectives only after two flat reads) on top of the act-first calls; the `spill` keyword is already threaded through.
- 20-19: owns constructing the spill, where it lives, and the startup behaviour (a missing/corrupt/conflicting spill and SAFE_MODE). `replay_spill` and `LocalSpill.scan()` already report all of those cases at the spill level.
- Any caller that catches `StoreUnavailable` around these controls must now also expect `AuditRecordLost` (single call) or an `ExceptionGroup` member (protective legs, emergency close) when no spill is configured.

## Self-Check: PASSED

- FOUND: src/ops/spill.py, src/ops/risk_first.py, tests/support/reconcile_doubles.py, tests/test_risk_first_spill.py, src/execution/enablement.py, src/execution/manager.py
- FOUND commits: 646166d3, 73088379, 56336fe8, 49d51a5b, 571180f9
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, params/, pyproject.toml, uv.lock, `.gsd/`, `.planning/config.json`, `.planning/state.json`, `.planning/milestone.lock`
