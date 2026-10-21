---
phase: 20-reconcile-safe-mode-hardening
plan: 25
subsystem: reconcile
tags: [safe-mode, operator-exit, rest-gate, user-data-stream, fail-closed, owner-decision-o-b]
status: complete

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "20-15 exit_safe_mode rows 1-5; 20-07 RestRateLimitGate.restriction() / recovery_status() (O-C = option-a1-with-commands)"
provides:
  - "exit_safe_mode(*, operator_id, local_intent_fn, readiness, gate_status, stream_state, now_utc); gate_status and stream_state are required keyword-only, no default"
  - "ExitRefusal.GATE_NOT_OPEN, GATE_NOT_RESTORED, STREAM_NOT_LIVE; ACCEPTED_GATE_RECOVERY_STATES; STREAM_LIVE_STATE"
  - "make_restore_drill(gate_status=, stream_state=) with healthy fake defaults"
affects: [20-24 docs and 20-DEFERRED (nothing deferred for O-B: both rows built), future composition that calls exit_safe_mode (must inject a real gate view and the supervisor state)]

requirements-addressed: [OPS-01]

actuals:
  tokens: 21000
  tasks: 2
  commits: 2
plan_head_before: 9632d69ed6f009a119110ba8aa03ffbcd38e5add
plan_head_after: e24f3ffc373a9a965630955b1f4526eb81e657f7

key-files:
  modified:
    - src/reconcile/safe_mode.py
    - src/ops/drills.py
    - tests/test_safe_mode_exit_operator.py
    - tests/test_controller_rehydrate.py
    - tests/test_journal_failure_paths.py
    - tests/test_phase8_audit_reviewfix.py

key-decisions:
  - "Owner decision O-B accept-both: rows 6 and 7 are SAFE_MODE exit conditions."
  - "Row 6 reads gate.restriction() (a pure read), never check() (which is the call that refuses a REST request); a test pins that restriction() is not None exactly when check() refuses."
  - "A gate_status provider that raises or returns a malformed value refuses GATE_NOT_RESTORED; a restriction plus an unrestored status reports both codes."
  - "Row 7 passes only for the exact string LIVE; None, bytes, lowercase and padded strings refuse."

metrics:
  duration: "about 25 minutes"
  completed: 2026-10-21
---

# Phase 20 Plan 25: SAFE_MODE exit rows 6 and 7 Summary

An operator exit from SAFE_MODE is now also refused while the REST gate is restricted or not durably restored (row 6) and while the user-data stream is not LIVE (row 7), as the owner decided in O-B.

## Owner decision O-B

Answer (verbatim, given by the owner in the orchestrator session on 2026-10-21): **"O-B: accept-both"**

Rows 6 and 7 become SAFE_MODE exit conditions. The answer was recorded here before the implementation commits (Task 2) were made; Task 1 (the blocking-human checkpoint) was already answered when this plan was dispatched, so the executor did not stop at it.

Dependency check: `20-07-SUMMARY.md` "Owner decision O-C" is `option-a1-with-commands`, not option-reject. The gate recovery exists, so row 6 could be built; nothing was skipped. No deferral entry is needed for plan 20-24 from this plan.

## What was built

- `src/reconcile/safe_mode.py`
  - `exit_safe_mode` gains required keyword-only `gate_status: Callable[[], tuple[str | None, str]]` and `stream_state: Callable[[], str]`. Neither has a default, so no composition can forget them (a test asserts no parameter has a default, and that a missing one raises `TypeError` at call).
  - Row 6 (`_gate_refusals`): restriction not None gives `GATE_NOT_OPEN`; recovery status outside `ACCEPTED_GATE_RECOVERY_STATES` (`RESTORED_DURABLE`, `RESTORED_BARRIER`) gives `GATE_NOT_RESTORED`. `LEGACY_IN_MEMORY`, `NOT_RESTORED`, `RESTORED_UNKNOWN_STATE`, `PERSISTENCE_FAILED`, an unknown string, a raising provider and any malformed return all give `GATE_NOT_RESTORED`.
  - Row 7 (`_stream_refusals`): only the exact string `LIVE` passes; everything else, including a raising provider, gives `STREAM_NOT_LIVE`.
  - Both rows run in the single refusal pass after row 5; all refusal codes are collected and journaled in `SAFE_MODE_EXIT_REFUSED`.
  - Row 6 never substitutes row 3: a failed Binance read with a healthy gate still refuses `BINANCE_READ_FAILED`.
  - The module imports nothing from `src.adapters`; states are compared by string value and a parity test pins the strings against `GateRecoveryStatus` and `StreamState`.
- `src/ops/drills.py`: `make_restore_drill` accepts optional `gate_status` / `stream_state`; the defaults are the healthy fakes `(None, "RESTORED_DURABLE")` and `"LIVE"`.
- Tests: one named failure test per row and per listed gate state in `tests/test_safe_mode_exit_operator.py`, wiring tests against the real `RestRateLimitGate`, and the three other caller test files pass healthy fakes (test meaning unchanged).

## Verification

- `uv run pytest -m "not docker" tests/test_safe_mode_exit_operator.py tests/test_gate_restart.py tests/test_controller_rehydrate.py tests/test_journal_failure_paths.py tests/test_phase8_audit_reviewfix.py tests/test_drills.py`: all passed (RED run before the implementation failed as expected).
- `uv run mypy src`: no issues in 233 files. `uv run ruff check` clean; `ruff format --check` clean on touched files.
- `grep -nE "^[[:space:]]*(from|import) src[.]adapters" src/reconcile/safe_mode.py`: no output.
- `git diff --exit-code -- pyproject.toml uv.lock`: exit 0 (no dependency added).
- Evidence label: executed tests with fakes and the real in-process gate; no [DEMO] claim.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree started 151 commits behind develop**
- **Found during:** startup (the plan files did not exist in the worktree)
- **Fix:** `git merge --ff-only develop` on the clean, commit-free agent branch (no history rewritten).
- **Commit:** none (fast-forward).

**2. [Rule 1 - Test signature pin] `test_exit_safe_mode_has_only_the_keyword_only_operator_signature`**
- The test listed the exact parameter names; updated to include `gate_status` and `stream_state` (its no-default and keyword-only assertions already cover them).
- **Commit:** e24f3ffc

**3. Plan said row 6 accepts `RESTORED_BARRIER` "after its window"**
- `GateRecoveryStatus` documents `RESTORED_BARRIER` as reserved and never produced by the persisted-deadline mechanism (plan 20-07). It is in `ACCEPTED_GATE_RECOVERY_STATES` as the plan specifies; because the gate reports it only once its window has passed, the predicate does not need a window check of its own. If a future gate produces it earlier, this constant must be revisited.

None otherwise - plan executed as written.

## Known Stubs

None.

## Threat Flags

None. Mitigations T-20-54 (row 6) and T-20-55 (row 7) are implemented; T-20-SC holds (no dependency change).

## Notes for the composition (not in this plan's scope)

`exit_safe_mode` has no production caller in `src` yet except the restore drill. Whoever composes the operator exit must inject `gate_status` as `(None if gate.restriction() is None else gate.restriction().reason, gate.recovery_status().value)` (one `restriction()` read, not two) and `stream_state` as the supervisor's `StreamState` value. Process-local views gate the return to entries; they do not replace row 3.

## Commits

- 83dd7c4c: test(20-25): RED - rows 6 and 7 failure tests
- e24f3ffc: feat(20-25): rows 6 and 7 implementation and caller updates

## Self-Check: PASSED

Files modified exist; commits 83dd7c4c and e24f3ffc are ancestors of HEAD.
