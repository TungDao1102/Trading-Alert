---
phase: 20-reconcile-safe-mode-hardening
plan: 19
subsystem: execution-restart-rebuild
tags: [restart, rebuild, d-08, d-30, d077, g4-029, fail-closed, startup, spill, tdd]
requires: [20-02, 20-06, 20-08, 20-10, 20-12, 20-14, 20-16, 20-17, 20-18]
provides:
  - "src/execution/protection_rebuild.py: RestoredPlan, rebuild_plan, REASON_STOP_HISTORY_UNKNOWN"
  - "ProtectionCoordinator(restore_required=...), restore(plans, now_utc=) -> RestoreReport, restore_complete / blocks_new_entries honour a pending restore (F6); SAFE_MODE_RESTORE_INCONSISTENT, EVENT_PROTECTION_RESTORED, REASON_REGISTERED_AFTER_RESTORE"
  - "MarketEmergencyCloser.restore_pending(plan_hash, attempts), RestoredAttempt, pending_attempts_from_events, plan_hash_of_close_event; the pre_send row is written ahead to the spill"
  - "src/reconcile/startup.py: run_startup_recovery -> StartupReport, the STEP_* names"
affects: [20-22, 20-23, 20-24]
tech-stack:
  added: []
  patterns:
    - "an unprovable stop history is restored UNPROTECTED with stop_lost_at at the earliest durable time, so the existing D077 path decides and no new placement or branch code exists"
    - "rebuild_plan is pure and takes every durable source as an argument; startup injects the reads (no src.persistence import)"
    - "write-ahead to the spill for the one row a crash must not lose (pre_send), removed after the journal took it"
key-files:
  created:
    - src/execution/protection_rebuild.py
    - src/reconcile/startup.py
    - tests/test_protection_rebuild.py
    - tests/test_startup_recovery.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-19-SUMMARY.md
  modified:
    - src/execution/protection.py
    - src/execution/emergency_close.py
key-decisions:
  - "A stop history is KNOWN only when the replay is valid (which already means contiguous from seq 1), the spill was readable and holds no protection-correlation record the journal lacks, and the STOP_LOSS intent row agrees with the rows. Otherwise the plan is restored UNPROTECTED, stop_history_known False, reason STOP_HISTORY_UNKNOWN, stop_lost_at = first_fill_at = earliest durable time. Plans already in CLOSE_REQUIRED, CLOSE_FAILED, FLAT or ENTRY_ENDED_NO_FILL keep their state (a blocking state is never downgraded) with stop_history_known False."
  - "Three journal-versus-intent contradictions count as an unknown history (added beyond the plan text, judgement call): a STOP_LOSS intent with no first-fill row, an ACKED intent with no REST_STOP_CONFIRMED row, a REJECTED intent while the journal does not end in a close state. They close the T-20-69 hole where a lost confirmation row would let a lost stop be re-placed."
  - "restore() writes no REGISTERED row; the one exception is a plan the journal never recorded (seq 0, AWAITING_FILL): it gets the missing seq-1 row with reason REGISTERED_AFTER_RESTORE so a later replay does not fail BAD_START."
  - "Only the highest-numbered open close attempt is adopted by restore_pending: a later attempt is sent only after the earlier one was proven terminal."
  - "run_startup_recovery reads the spill with one scan() (records plus corrupt entries), not pending(), because the corrupt list is needed; a spill with any corrupt entry or a scan() that raises passes spill_rows=None to every plan."
requirements-addressed: []
status: complete
duration: about 2h
completed: 2026-10-21
estimate:
  tokens: 125000
  tasks: 3
actuals:
  tokens: 29600   # chars/4 over `git diff 9632d69e HEAD -- src tests` (118658 chars)
  tasks: 3
  commits: 4      # MEASURED: git rev-list --count 9632d69e..HEAD at SUMMARY write, before the SUMMARY commit
plan_head_before: 9632d69ed6f009a119110ba8aa03ffbcd38e5add
plan_head_after: 7c54ae1c8998b36241d918ce130ef91d401b1b91
---

# Phase 20 Plan 19: Restart rebuild of the protection state and the startup order Summary

**After a restart the coordinator and the emergency closer are rebuilt from durable sources without restarting any clock, re-placing a lost stop or reusing a close attempt number; a stop history the journal cannot prove is treated as lost under D077, and every unprovable source ends in SAFE_MODE.**

Base: the worktree was created on an older commit than the wave-4 results, so it was fast-forwarded to `develop` (`9632d69e`) before any work (no commit of mine was lost: HEAD was an ancestor). `commits: 4` is the measured `git rev-list --count 9632d69e..HEAD` at SUMMARY write, before the SUMMARY commit. All three tasks were finished by one agent; the named split point (after Task 2) was not used. `requirements-addressed` is empty on purpose (the orchestrator owns REQUIREMENTS.md; RISK-03, OPS-01, EXEC-02 are the plan's areas). Evidence label: executed tests with fakes (the project fake exchange, in-memory stores, a real `LocalSpill`, virtual time). The caller wiring into a running process is Phase 24 (G4-029) and is NOT claimed; no `[DEMO]` claim.

## What was built

### Task 1 (tracer): crash after the STOP_LOSS intent was SENT (commits `c4eefb24` test, `cf412cc6` feat)

- `protection_rebuild.rebuild_plan(entry, transition_events, entry_intent, stop_intent, spill_rows) -> RestoredPlan`: validates the `PROTECTION_TRANSITION` rows with `replay_transitions`, takes `first_fill_at` from the first `FIRST_FILL_*` row (else the STOP_LOSS intent's `intended_at_utc`), `stop_confirmed_at` from the first `REST_STOP_CONFIRMED` evidence, `stop_lost_at` from the first `STOP_LOST*` row, `entry_terminal_at` from the first entry-terminal row, `close_branch` from the first move into CLOSE_REQUIRED. No clock is read (AST test: no wall clock, no float constructor).
- Coordinator: `restore_required` (default False keeps every caller unchanged); until `restore()` runs, `blocks_new_entries()` is True and `restore_complete` False (F6). `restore()` installs the tracked plans without an adapter call, without a stop placement, without a REGISTERED row, and journals one `PROTECTION_RESTORED` note per plan. The new `_Tracked.__init__(restored_state=...)` is how the state is set, because the existing AST test only allows `.state` to be assigned in `_Tracked.__init__` and `_transition`.
- Tracer test: `test_crash_after_stop_intent_sent_restart_places_stop_once` (run 1 dies with the intent SENT and nothing at the exchange; run 2 blocks entries, rebuilds UNPROTECTED with the journaled first-fill time, places the stop exactly once under the deterministic id at `entry.sl_trigger_price`, the intent ends ACKED, the plan PROTECTED). A second test runs `resolve_unresolved_intents` between the two (F5): the SENT intent becomes UNKNOWN, is not terminated, and ends ACKED.

### Task 2: clocks survive, lost stops stay lost, corrupt replay fails closed (commit `48217481`)

Named tests (`tests/test_protection_rebuild.py` has 20 collected tests, `tests/test_startup_recovery.py` 17): `test_restart_never_resets_stop_lost_at` (escalation at L + 7777 ms, not restart + 7777; the lost stop is never queried or placed; the whole journal still replays), the CLOSE_REQUIRED and CLOSE_FAILED restarts (branch kept, blocking, a late ACTIVE stop does not downgrade), the first-fill deadline kept, a FLAT plan not stepped for protection, three corrupt replays (seq gap, illegal edge, missing evidence) restored UNPROTECTED with SAFE_MODE `PROTECTION_STATE_INVALID` and closed by position with no stop read or placed, `test_unknown_stop_history_never_permits_a_replacement` over three sources (missing rows, a spill-only protection row, an unreadable spill: zero placement calls, zero stop queries, `RESTORE_INCONSISTENT`, escalation at first fill + 7777 ms, no MARKET close with a guessed quantity), exposure closed by MARKET with the correct side and quantity, flat-with-entry-open stays UNPROTECTED, and the `restore()` guards. The implementation for all of it landed with the Task 1 commit (restore and the unknown-history rule belong to the tracer); this commit adds the tests. Mutation check: making an unreadable spill count as consistent made two of them fail.

### Task 3: the closer's pending attempt and `run_startup_recovery` (commit `7c54ae1c`)

- `MarketEmergencyCloser`: `pre_send` is written ahead to the spill (when attached) before the journal write and removed after the journal took it; `pending_attempts_from_events(events)` reads open attempts (pre_send, ambiguous or post_send with no filled, ended_unfilled, rejected or not_sent row; rows without an attempt number are skipped; a malformed attempt row raises `ValueError`); `restore_pending(plan_hash, attempts)` adopts the highest-numbered one with `mark_unknown(CODE_HISTORY_NOT_TERMINAL)`. After a restart nothing is sent while REST does not prove it terminal; once it reads FILLED the next part uses attempt 2.
- `run_startup_recovery`: SAFE_MODE loaded, pending table loaded, spill read once, coordinator restored, closer restored (journal reader plus spill), intents resolved after the rebuild, spill replayed. Unreadable pending store -> DB_FAILURE (coordinator still restored); unreadable or corrupt spill -> RESTORE_INCONSISTENT with `spill_rows=None`; a rebuild that cannot read the plans -> DB_FAILURE and `restore_complete` stays False; replay conflict or corrupt file -> RESTORE_INCONSISTENT with the file kept; failed replay write -> DB_FAILURE. It never calls `exit_safe_mode`, makes no placement call and imports no `src.persistence` module (AST tests). `src.ops.spill.replay_spill` is imported lazily and can be injected.

## Deviations from Plan

**1. [Rule 3 - blocking] Worktree base was stale;** fast-forwarded to `develop` `9632d69e` (no local commits existed). The plan file and the wave 1-4 code were not in the worktree before that.

**2. [Rule 1 - test guard] `_Tracked.__init__` gained a `restored_state` keyword.** `tests/test_protection_transitions.py::test_no_code_path_assigns_state_outside_transition` allows `.state` to be assigned only in `_Tracked.__init__` and `_transition`; editing that test is outside this plan's files, so the restored state goes through the constructor.

**3. [Plan intent] Extra "journal contradicts the intent row" checks** (see key-decisions) in `rebuild_plan`, beyond the plan's list of unknown-history causes. Cost: a plan whose STOP_LOSS intent was ACKED by an earlier recovery probe, with the journal lacking a `REST_STOP_CONFIRMED` row, is restored under D077 (closed by position) after a second restart even though the stop may exist. This is the fail-closed side; flagged for the owner at O-A together with the never-confirmed same-id re-place (plan 20-17 already ties that to O-A).

**4. [Plan intent] `restore()` writes a `REGISTERED_AFTER_RESTORE` seq-1 row for a plan the journal never recorded** (the plan says only "no REGISTERED transition"). Without it the next restart's replay would fail `BAD_START` for that plan.

**5. [Plan wording] The startup reads `spill.scan()` once instead of `spill.pending()`,** because the corrupt-entry list is needed to decide `RESTORE_INCONSISTENT` (`pending()` is `scan().records`).

**6. [Test shape] Task 2 tests were written after the Task 1 implementation, and the Task 3 tests after its implementation,** so there is no separate RED commit for them (the Task 1 RED commit is `c4eefb24`: collection error on the missing module). Task 2 evidence is the mutation check above; Task 3 tests were run green and the AST and ordering tests assert behaviour that did not exist before the commit.

## Known limits and findings (not fixed here)

- **The coordinator does not spill its own `PROTECTION_TRANSITION` rows when the journal is down** (only operator audit rows and pending-action intents reach the spill). A transition row lost to a journal outage is therefore caught only through the STOP_LOSS intent row and the spill records `rebuild_plan` checks, not through the spill alone. Closing that fully is a change to `_record_journal` (a candidate for plan 20-23/24).
- **A plan restored UNPROTECTED from a journal that ends in another state** (for example PROTECTED with an unreadable spill) is held in memory as UNPROTECTED; its next journaled move is `UNPROTECTED -> ...` after a `PROTECTED` last row, which fails `CHAIN_BROKEN` at the next restart and is restored the same conservative way again. It never becomes less safe; the journal chain is just not repaired.
- **`LocalSpill.scan()` swallows an `OSError` from listing the directory,** so a directory that exists but cannot be listed looks empty ("nothing pending"). Startup treats a `scan()` that raises, or any corrupt entry, as unreadable; the silent-empty case is a 20-08 design choice that this plan cannot distinguish from a missing directory.
- A forced-UNPROTECTED plan raises no critical alert on its own (none exists for UNPROTECTED today); the alert comes with CLOSE_REQUIRED.
- SAFE_MODE `RESTORE_INCONSISTENT` is documented by plan 20-24, as the plan says.

## TDD Gate Compliance

Commits in order: `c4eefb24` test (RED, import error), `cf412cc6` feat (GREEN, Task 1), `48217481` test (Task 2, passes on arrival because the Task 1 implementation covers it; mutation-checked), `7c54ae1c` feat (Task 3, tests and implementation together). No REFACTOR commit. `gsd_run check tdd-red-evidence` was not run (it does not parse pytest output). Tracer feedback gate (Task 1 has no `gate="blocking-human"`): after the GREEN commit the verify command and the neighbouring protection suites passed end to end before Tasks 2 and 3 started.

## Verification actually run (own tests and touched-file neighbours; never the full suite)

- `uv run pytest -m "not docker" -n 4` over `tests/test_startup_recovery.py tests/test_protection_rebuild.py tests/test_emergency_market_close.py tests/test_risk_first_spill.py tests/test_protection_*.py tests/test_manual_controls.py tests/test_emergency_close_filters.py tests/test_execution_emergency.py tests/test_pending_actions.py tests/test_journal_failure_paths.py tests/test_ast_guards.py tests/test_domain_no_float.py tests/test_no_unratified_defaults.py tests/test_agents_md.py tests/test_system_throttle_protection.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_reconcile.py` at `7c54ae1c`: all passed, 0 failed (no `TEST_DATABASE_URL` set, so no `*_pg.py` file was run).
- `uv run mypy src`: no issues in 235 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 721 files already formatted. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `pyproject.toml` and `uv.lock` are untouched (T-20-SC); `.planning/STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`, `.gsd/`, `milestone.lock` and `config.json` are untouched.

## Known Stubs

None.

## Self-Check: PASSED

Files verified present: `src/execution/protection_rebuild.py`, `src/reconcile/startup.py`, `tests/test_protection_rebuild.py`, `tests/test_startup_recovery.py`; commits `c4eefb24`, `cf412cc6`, `48217481`, `7c54ae1c` are ancestors of HEAD.
