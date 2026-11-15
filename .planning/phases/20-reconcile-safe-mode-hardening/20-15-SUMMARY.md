---
phase: 20-reconcile-safe-mode-hardening
plan: 15
subsystem: reconcile
tags: [safe-mode, operator-exit, fail-closed, f-711, d-15]

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "20-06 durable SAFE_MODE store and three-key state; 20-04 compare v2; 20-12 LocalIntent; 20-10 O-F record (D-15 line: accept)"
provides:
  - "SafeModeController.exit_safe_mode(*, operator_id, local_intent_fn, readiness, now_utc) -> ExitDecision"
  - "ExitReadiness, ExitRefusal, ExitDecision, LocalIntentLike, build_exit_readiness in src/reconcile/safe_mode.py"
  - "five-key persisted SAFE_MODE state (last_exit_operator_id, last_exit_at_utc); three-key rows still load"
  - "journal events SAFE_MODE_EXIT (with operator_id) and SAFE_MODE_EXIT_REFUSED (codes only)"
affects: [20-19 startup, 20-24 docs/GLOSSARY and 20-DEFERRED, 20-25 exit rows 6-7 (O-B)]

requirements-addressed: [OPS-01]

actuals:
  tokens: 20600
  tasks: 3
  commits: 5
plan_head_before: 87c82ce04e3e2abc25d49846b820920d2386d868
plan_head_after: a81ffbe38d778e4915982e63442c68f8182a5b88

key-files:
  created:
    - tests/test_safe_mode_exit_operator.py
  modified:
    - src/reconcile/safe_mode.py
    - src/reconcile/__init__.py
    - src/ops/drills.py
    - tests/test_controller_rehydrate.py
    - tests/test_journal_failure_paths.py
    - tests/test_phase8_audit_reviewfix.py
    - tests/test_reconcile.py
    - tests/test_safe_mode_persistence.py
    - tests/test_safe_mode_persistence_pg.py

key-decisions:
  - "Precondition checked: 20-10-SUMMARY.md O-F records `D-15: accept` on its own line, so no checkpoint was needed."
  - "Refusals are collected in one pass (rows 1-5) and journaled once as SAFE_MODE_EXIT_REFUSED with codes only; the refusal journal write is best-effort."
  - "last_exit_* is kept across a later entry, so the persisted state always says who last left SAFE_MODE; both keys are set together or both None."
  - "An exit already out of SAFE_MODE is a no-op returning ExitDecision(exited=True), without reads or writes."
  - "An enter_safe_mode call that lands while the exit awaits its Binance reads refuses the exit (COMPARE_NOT_CLEAN): added beyond the plan, see Deviations."

status: complete
---

# Phase 20 Plan 15: Operator-Attributed SAFE_MODE Exit Summary

**`exit_safe_mode` is now an explicit, fail-closed operator act: a non-blank operator id, a successfully read local intent, fresh Binance reads in the same call, a clean compare v2 and clean readiness counts (rows 1-5), journaled with the operator id first, persisted second, memory flipped last.** The `local_open_orders or []` vacuous exit (F-711) is gone and `SAFE_MODE_TICK_SECONDS` is removed.

Evidence label: fakes and a local PostgreSQL only. Nothing here is [DEMO]. Rows 6 (REST gate) and 7 (`StreamState.LIVE`) are NOT built (owner O-B, plan 20-25). The operator id is audit metadata, not authentication; the allow-list is Phase 23/24 (T-20-38).

## Accomplishments

- `src/reconcile/safe_mode.py`: new `ExitRefusal` (StrEnum, 8 codes), `ExitReadiness` (None = could not be read), `ExitDecision` (`__bool__` = `exited`), `LocalIntentLike`, `build_exit_readiness`; `exit_safe_mode` has only keyword-only required parameters, so a caller cannot leave a list empty. Row 5 counts every unresolved intent (any status), plans in UNPROTECTED / CLOSE_REQUIRED / CLOSE_FAILED (by string value, no `src.execution` import) and open pending actions; a failing provider makes its field None, which refuses as READINESS_UNREADABLE.
- State format: `_parse_state` accepts the five-key set and the three-key row of plan 20-06 (read as `last_exit_*` None); any other key set, a partial `last_exit_*` pair, a blank operator or a non-UTC time raises `ValueError` (so `load` fails closed into SAFE_MODE). `state_snapshot()` always has five keys.
- Callers: `make_restore_drill` passes `DRILL_OPERATOR_ID = "drill-operator"`, a default empty-but-successfully-read local intent and clean readiness (all overridable); the rehydrate, journal-failure and WR-16 tests use the operator exit.
- `SAFE_MODE_TICK_SECONDS` removed from `safe_mode.py` and `src/reconcile/__init__.py` (D-25); `tests/test_reconcile.py` now asserts its absence and that `ExecutionLimits` has `reconcile_tick_interval_ms`.
- AST guards: no `or <empty>` default inside `exit_safe_mode`; `src/reconcile/loop.py`, `src/execution/intent_recovery.py` and `src/ops/alerts.py` never call `exit_safe_mode`; across `src` the only caller is `src/ops/drills.py`; `safe_mode.py` imports nothing from `src.persistence` / `src.execution`.

## Task Commits

| Task | Commit |
|---|---|
| 1 Tracer RED | 2ae17073 |
| 1 Tracer GREEN (exit, state format, persistence pins) | 456014be |
| 2 Row tests, write order, callers, tick constant | ed545723 |
| 3 build_exit_readiness and no-exit AST guards | e0f19e1a |
| Race fix (entry during exit reads) | a81ffbe3 |

Tracer gate: the Task 1 verify command (`tests/test_safe_mode_exit_operator.py` + `tests/test_safe_mode_persistence.py`) was green before Task 2 started.

## RED evidence (honest)

- Task 1: RED commit failed at collection (`ImportError: cannot import name 'ExitDecision'`). GREEN implemented the whole `exit_safe_mode` of the action text at once.
- Task 2: the row 1-5 and write-order tests were written AFTER that implementation and therefore passed on first run; they were not red. To show they bite, each of six mutants was applied to `safe_mode.py` one at a time and the file restored: row 1 check disabled, `local ... or ((), (), ())` (the F-711 default), row 3 disabled, row 4 disabled, row 5 disabled, memory flipped before the store save. Each mutant failed at least one named test (for example `test_missing_local_source_blocks_exit`, `test_row4_an_exchange_position_with_an_empty_successful_local_read_refuses`, `test_a_failing_state_save_keeps_safe_mode_and_a_retry_can_exit`). The caller rewrite and tick-constant part was genuinely red: 6 failures (`TypeError ... missing 4 required keyword-only arguments` in the restore drill, and `hasattr` in `test_divergence_forces_safe_mode_without_cancel`) before the drill and removal edits.
- Task 3: genuinely red at collection (`cannot import name 'build_exit_readiness'`).
- Race fix: `test_an_entry_during_the_exit_reads_refuses_the_exit` failed (exit succeeded) before the `_enter_calls` guard.

## Verification actually run

All with `TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` from the process environment (value never printed); PostgreSQL files ran (no skips under strict).

- `uv run pytest -m "not docker"` on: `test_safe_mode_exit_operator.py` (104 tests), `test_safe_mode_persistence.py`, `test_safe_mode_persistence_pg.py`, `test_controller_rehydrate.py`, `test_journal_failure_paths.py`, `test_phase8_audit_reviewfix.py`, `test_reconcile.py`, `test_drills.py`, `test_reconcile_loop.py`, `test_phase18_gate.py`, `test_phase19_gate.py`, `test_persistence_exit_evidence_pg.py`, `test_system_state_pg.py`, `test_agents_md.py`: all passed. Also passed earlier: `test_journal_ids.py`, `test_demo_rehearsal_flow.py`, `test_intent_recovery.py`, `test_intent_recovery_unknown_entry.py`, `test_pending_actions.py`, `test_manual_controls.py`, `test_execution_gates.py`.
- `uv run mypy src`: no issues in 229 files.
- `uv run ruff format --check`: 706 files already formatted.
- `uv run ruff check`: 1 error, `E501` at `src/execution/protection.py:72`, introduced by commit cbbcb0a5 (plan 20-09 area), not by this plan. Out of scope, not fixed (see findings). All files touched by this plan are clean.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- pyproject.toml uv.lock`: unchanged.
- Not run: the full suite (orchestrator's job), `-m docker` (Docker unavailable).

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] Entry during the exit's awaits**
- **Found during:** Task 3 review of the exit path.
- **Issue:** the exit awaits three Binance reads on the event loop shared with the reconcile loop. A loop tick calling `enter_safe_mode` meanwhile would be erased by the flip, because the exit's older reads could look clean (a divergence lost, fail-open).
- **Fix:** private `_enter_calls` counter; an entry between the start of row 2 and the compare refuses with `COMPARE_NOT_CLEAN` (no new code added to the closed list). Docstring row 4 updated.
- **Files:** `src/reconcile/safe_mode.py`, `tests/test_safe_mode_exit_operator.py`. **Commit:** a81ffbe3.

**2. [Pins updated] Snapshot format pins.** `state_snapshot()` is five keys now, so the pins in `tests/test_safe_mode_persistence.py` (new `SNAP_OFF`, saved-state literal), `tests/test_controller_rehydrate.py` (`NO_EXIT` merged into the snapshot comparisons; the post-exit snapshot now names the operator) and `tests/test_safe_mode_persistence_pg.py` (default-controller snapshot) were updated. The three-key `SAFE_ON` / `SAFE_OFF` inputs stay, now documenting the accepted old format.

**3. [F-604-style rewrites]** `test_wr16_exit_prefers_fresh_intent_fn_over_stale_lists` and `test_wr16_divergent_intent_fn_blocks_exit` (the list arguments no longer exist; the stale-list half is now structural and asserted by the signature test; the divergent case asserts `COMPARE_NOT_CLEAN`); the exit calls in `test_controller_rehydrate.py` (2) and `test_journal_failure_paths.py` (2) keep their meaning behind an `_operator_exit` helper.

**4. [Process]** The branch name `p20-15` (set by the orchestrator) does not match the `agent-*` allow-list regex of the pre-commit assertion; the protected-branch part of that assertion was satisfied and the orchestrator's branch was used. The fresh worktree had no virtualenv; `uv sync --frozen --extra dev` was run (does not change `pyproject.toml` / `uv.lock`).

## Known Stubs

None. The drill's default `local_intent_fn` / `readiness` are intentional drill-context defaults (the drill's local state is empty), not production wiring.

## Threat Flags

None new. T-20-37 mitigated (mandatory `local_intent_fn`, raising source blocks, compare on fresh reads); T-20-39 mitigated (operator id in the exit journal row and the persisted state); T-20-38 transferred (no allow-list); T-20-SC mitigated (no dependency change).

## Findings for later plans

1. **`exit_safe_mode` still has no production caller.** Only `src/ops/drills.py` calls it. A real operator entry point must build `local_intent_fn` from `derive_local_intent(coordinator.protections(), intent_store.list_unresolved_intents())` and `readiness` from `build_exit_readiness(list_unresolved_intents, protections, PendingActionStore.list_open)`. Plan 20-19 (startup/composition) or a later plan must add it and the RUNBOOK step; the RUNBOOK and GLOSSARY 9.4 were not edited here.
2. **Journal/store split on a failed save.** If the `SAFE_MODE_EXIT` journal row is written and the state save then fails, the journal says EXIT while the durable state (and the controller) still say SAFE_MODE; a retry journals a second EXIT row (new `now_utc`, new content-hash id). Readers of the journal must treat the system-state row as the truth. This is the ordering the plan mandates; flagging it for the RUNBOOK/GLOSSARY text.
3. **Pre-existing `ruff check` failure:** `E501` at `src/execution/protection.py:72` (141 columns, from cbbcb0a5). The phase gate `ruff check` will fail until it is wrapped; not fixed here.
4. `ExitReadiness` accepts any value at construction; invalid values (negative, bool) are refused at consumption as READINESS_UNREADABLE. A shared contract test with the real `PendingActionStore.list_open` / `ProtectionCoordinator.protections` / `list_unresolved_intents` shapes belongs with the composition plan (the helper was tested on duck-typed rows only).
5. Rows 6 and 7 must be added to `ExitReadiness` / `exit_safe_mode` by plan 20-25 after O-B; the closed code list then grows.
6. The operator-id allow-list must be written to `20-DEFERRED.md` by plan 20-24 (T-20-38); the id format is only "non-blank text".

## Self-Check: PASSED

Created file `tests/test_safe_mode_exit_operator.py` exists; commits 2ae17073, 456014be, ed545723, e0f19e1a, a81ffbe3 are on branch `p20-15`; `SAFE_MODE_TICK_SECONDS` absent from `src`; `git diff --exit-code -- pyproject.toml uv.lock` clean.
