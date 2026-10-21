---
phase: 20-reconcile-safe-mode-hardening
plan: 17
subsystem: execution-operator-controls
tags: [exec-06, operator-close, operator-protect, d-26, d077, sweep-verdicts, risk-03, tdd]
requires: [20-09, 20-11, 20-14]
provides:
  - "ProtectionCoordinator.operator_close(plan_hash, operator_id) -> OperatorControlResult: plan -> CLOSE_REQUIRED (branch OPERATOR_CLOSE), the existing close flow runs"
  - "ProtectionCoordinator.operator_protect(plan_hash, operator_id) -> OperatorControlResult: no placement of its own (owner direction 1 on D-26 / D077)"
  - "OperatorControlResult (frozen: accepted, code), BRANCH_OPERATOR_CLOSE, EVENT_OPERATOR_CLOSE_REQUESTED / _PROTECT_STEPPED / _STOP_ADOPTED / _PROTECT_REFUSED, the CODE_* result codes"
  - "_Tracked.stop_history_known (True for every live-tracked plan; plan 20-19 sets it False when a restored history cannot be proven)"
  - "PROTECTION table edges AWAITING_FILL -> CLOSE_REQUIRED and ENTRY_UNRESOLVED -> CLOSE_REQUIRED (reason OPERATOR_CLOSE)"
  - "manager.operator_close_position, manager.operator_protect_position (thin wrappers), manager.EXEC06_CONTROLS"
  - "ProtectionCoordinator._sweep wired to the CancelVerdict map (mandatory extra); journal event PROTECTION_SWEEP_UNVERIFIED"
affects: [20-19, 20-22, 20-24, 20-26]
tech-stack:
  added: []
  patterns:
    - "a human control is an out-of-cadence trigger of the coordinator's own rule, never a second placement path"
    - "act first, journal after, spill fallback; both failing enters SAFE_MODE DB_FAILURE once"
    - "refusal decided from the tracked record before any adapter call"
key-files:
  created:
    - tests/test_protection_sweep_verdicts.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-17-SUMMARY.md
  modified:
    - src/execution/protection.py
    - src/execution/manager.py
    - src/domain/transitions.py
    - tests/test_manual_controls.py
    - tests/test_protection_transitions.py
    - tests/test_transitions.py
key-decisions:
  - "operator_protect has no placement code and no _transition call of its own; the only placement it can cause is the coordinator's never-confirmed same-id re-place at entry.sl_trigger_price, run by the coordinator's own per-plan step under the step lock."
  - "The sweep is done only when every leg verified CANCELED or GONE_NOT_CANCELED (PROVEN_GONE); a STILL_OPEN or UNKNOWN leg journals PROTECTION_SWEEP_UNVERIFIED and the next step sweeps again."
requirements-addressed: []
status: complete
duration: about 1.5h
completed: 2026-10-21
estimate:
  tokens: 90000
  tasks: 3
actuals:
  tokens: 19400   # chars/4 over `git diff 87c82ce0 HEAD -- src tests` (77691 chars)
  tasks: 3        # the three planned tasks; the mandatory _sweep item was done first as two extra commits
  commits: 8      # MEASURED: git rev-list --count 87c82ce0..HEAD at SUMMARY write, before the SUMMARY commit
plan_head_before: 87c82ce04e3e2abc25d49846b820920d2386d868
plan_head_after: f2e06c095d47b0cc687952dc2a946168b688cadd
---

# Phase 20 Plan 17: EXEC-06 operator controls and a sweep that waits for proof Summary

**An operator can now flatten a strategy position through the coordinator's own reduce-only close flow, and can trigger the system's own protection rule without any placement path of its own; the coordinator sweep no longer calls itself done while a protective leg may still be resting.**

Base commit `87c82ce0` (develop), branch `p20-17`. `commits: 8` is the measured `git rev-list --count 87c82ce0..HEAD` taken at SUMMARY write, before the SUMMARY commit itself. All three planned tasks were finished, plus the mandatory extra item (the `_sweep` wiring) done first. EXEC-06 is NOT marked complete (`requirements-addressed` is empty on purpose; Demo evidence is missing).

## What was built

### Mandatory extra: `_sweep` wired to the cancel verdicts (commits `5f80e00b` test, `99f2323c` fix)

20-11 and 20-14 both recorded that `ProtectionCoordinator._sweep` set `sweep_done = True` whenever `cancel_untriggered_protectives` did not raise, ignoring the `{role: CancelVerdict}` map. Now `_sweep` reads the map: `sweep_done` becomes True only when STOP_LOSS, TAKE_PROFIT_1 and TAKE_PROFIT_2 are all in `PROVEN_GONE`. A leg that verified `STILL_OPEN` or `UNKNOWN`, or a result that is not a verdict map (a missing role counts as UNKNOWN), keeps the sweep open, journals one `PROTECTION_SWEEP_UNVERIFIED` row (nested `legs` map of verdict names, symbol, trade plan id; no price, quantity or text from the exchange) and the next step sweeps again. The cancel is by deterministic id, so the retry is idempotent. `pending_actions` and `spill` of 20-14 are untouched.

### Task 1 (tracer): `operator_close_position`

- `ProtectionCoordinator.operator_close`: validates the operator id (non-empty string, the `enablement._validate_operator_id` rule), refuses an unknown plan, a finished plan (FLAT, ENTRY_ENDED_NO_FILL: `NOTHING_TO_CLOSE`) and a plan already in CLOSE_REQUIRED / CLOSE_FAILED (`CLOSE_ALREADY_REQUIRED`, see Deviations), then under the step lock calls the existing `_enter_close_required(tracked, BRANCH_OPERATOR_CLOSE)`. Everything after is the unchanged close flow: SAFE_MODE `CLOSE_REQUIRED`, critical alert (reason `OPERATOR_CLOSE`), the emergency closer reads the quantity itself, the entry remainder is cancelled each step, FLAT only after two zero reads with the entry terminal, the legs swept only after FLAT.
- The audit row `OPERATOR_CLOSE_REQUESTED` (operator id, `state_before`, plan hash, symbol, trade plan id) is written after the action, journal first, the local spill when the journal fails, SAFE_MODE `DB_FAILURE` once if both fail.
- PROTECTION table: `AWAITING_FILL` and `ENTRY_UNRESOLVED` gained the edge to `CLOSE_REQUIRED` (the other five states with a position had it). `ProtectionState` docstring, `src/domain/transitions.py` and `tests/test_transitions.py::EXPECTED` updated together.
- `manager.operator_close_position`: a thin async wrapper (AST test: no adapter name, only `.operator_close`).

### Task 2: `operator_protect_position`

`ProtectionCoordinator.operator_protect` decides in this order, with no placement, close, cancel or `_transition` call in its body or its helpers (AST test over the five functions):

1. operator id / unknown plan.
2. Stop history, from the record alone: `stop_history_known` False, or `stop_lost_at` set while `stop_confirmed_at` is unset, or UNPROTECTED with a confirmation and no loss, or a confirmed state with no confirmation -> `STOP_HISTORY_UNKNOWN`.
3. State, still no adapter call: AWAITING_FILL / ENTRY_UNRESOLVED / FLAT / ENTRY_ENDED_NO_FILL -> `NOTHING_TO_PROTECT`; UNPROTECTED with `stop_lost_at` -> `REPLACEMENT_FORBIDDEN_STOP_LOST`; CLOSE_REQUIRED / CLOSE_FAILED -> `REPLACEMENT_FORBIDDEN_STOP_LOST` for `B4_FILL_AFTER_STOP`, `B4_STOP_LOST_UNRESOLVED` or `stop_lost_at` set, else `REPLACEMENT_FORBIDDEN_CLOSE_REQUIRED` (B1, B2, B3, B5, OPERATOR_CLOSE, NO_POSITION_ON_STOP_BUT_EXPOSED).
4. One fresh position read through the existing reader: unreadable `POSITION_UNREADABLE`, zero `NO_EXPOSURE`, wrong sign `WRONG_SIDE`.
5. Never-confirmed UNPROTECTED: `_step_plan(tracked, None)` once under the step lock (the B2/B3 rule: query by the deterministic id, same-id re-place at `entry.sl_trigger_price` only after a definitive absence, escalation at the deadline) -> accepted `COORDINATOR_STEPPED`, row `OPERATOR_PROTECT_STEPPED` with `state_before` / `state_after`. Confirmed states: a read-only stop query through the existing `_apply_stop_answer`: ACTIVE -> accepted `STOP_ADOPTED` (row `OPERATOR_STOP_ADOPTED`, nothing placed, state unchanged), ABSENT / NOT_ACTIVE -> `REPLACEMENT_FORBIDDEN_STOP_LOST`, unreadable -> `STOP_UNREADABLE`.

Every refusal writes `OPERATOR_PROTECT_REFUSED` (operator id, code, state). `manager.operator_protect_position` is a thin wrapper.

Decision recorded (objective of the plan, revision 2): `operator_protect_position` stays as the EXEC-06 "re-place protection" control but has no placement code of its own. There is one placement path (the coordinator's), one step lock and one absence-proof rule, so the operator call can only cause a placement that the next cadence step would make anyway, and it cannot extend `max_unprotected_ms` (the same step escalates at the deadline). The D077-compatible human action for a confirmed-then-lost stop is `operator_close_position`.

**Coupling to O-A (plan 20-26), as the plan requires:** the basis of the never-confirmed same-id re-place (D034 clause (1), plan 19-14 judgement call) is an owner confirm-or-reject item at O-A. If the owner rejects it, the automatic path and `operator_protect_position` change together in one gap plan, because they are one path. Nothing in this SUMMARY or the code calls it owner approved.

### Task 3: EXEC-06 checklist

`manager.EXEC06_CONTROLS` (an immutable mapping, exported in `__all__`): `cancel_pending_strategy_orders` -> `expire_pending_entry`, `disable_new_entries` -> `LiveEnablementController.disable`, `close_strategy_positions` -> `operator_close_position`, `replace_protection` -> `operator_protect_position`, `enter_safe_mode` -> `safe_mode_freeze`. `test_exec06_five_controls_exist` resolves each dotted path and checks it is callable. No edit inside `execute_approved_plan` (`git diff` shows no hunk in it; an AST test also checks it calls none of the new controls).

## Deviations from Plan

**1. [Plan intent] Extra result code `CLOSE_ALREADY_REQUIRED` (not in the plan's code list).** `operator_close` on a plan already in CLOSE_REQUIRED / CLOSE_FAILED neither starts anything nor says "nothing to close" truthfully, so it is refused with this code, no row, no second alert. Accepted code of a started close: `CLOSE_REQUESTED` (the plan lists no accepted code for the close).

**2. [Plan intent] No audit row for `OPERATOR_ID_MISSING`, `UNKNOWN_PLAN` and the refusals of `operator_close`.** The plan names `EVENT_OPERATOR_CLOSE_REQUESTED` for the accepted close and `EVENT_OPERATOR_PROTECT_REFUSED` for protect refusals. An empty operator id or an unknown plan has no one or nothing to audit; the close refusals have no event in the plan's vocabulary and nothing happened. Protect refusals for a known plan with a valid id are all journaled.

**3. [Test shape] Task 2 AST test covers `operator_protect` AND its four helper functions** (`_operator_protect_precheck`, `_operator_protect_position_refusal`, `_operator_protect_step`, `_operator_protect_stop_refusal`), because the delegation `_step_plan` sits in `_operator_protect_step`. The first draft of that one test (committed in the RED commit) checked the single function; it was changed in the same session before the GREEN commit.

**4. [Test shape] "places nothing" at the deadline is tested with a stop that reads NOT_ACTIVE, not ABSENT.** By code reading, `_confirm` re-places a stop it read ABSENT BEFORE it checks the unprotected deadline, so a never-confirmed stop that reads ABSENT on the deadline step is placed once and the plan then escalates in the same step (existing coordinator behaviour, untested by the 19-14 suite; the operator call runs the identical step, so it neither widens nor extends anything). The plan's sentence "escalates ... and places nothing" is exact for NOT_ACTIVE / unreadable readings (the B2 test scenario). Flagged below as a finding; no automatic behaviour was changed.

**5. [Rule 1 - lint] Fixed a pre-existing E501 in the `protection.py` module docstring** (a 141-character line from 20-14, reflowed). Content unchanged.

**6. [Environment] The worktree's `.venv` lacked the dev extra;** `uv sync --frozen --extra dev` was run once (no lock or pyproject change).

## TDD Gate Compliance

Commits in order: `5f80e00b` test + `99f2323c` fix (sweep); `2ac132c4` test + `36314f11` feat (Task 1, tracer); `d3f01140` test + `af5c56fb` feat (Task 2); `bde03dec` test + `f2e06c09` feat (Task 3). No REFACTOR commit.

RED evidence (pytest failures seen before the GREEN commit; `gsd_run check tdd-red-evidence` does not parse pytest output and was not run):
- Sweep: 3 of 4 new tests failed on behavior (no `PROTECTION_SWEEP_UNVERIFIED` row, `IndexError` on the row); 1 (every leg proven gone) passed already as a regression guard.
- Task 1: after a helper name clash in my own test file was fixed, 8 `test_manual_controls.py` tests failed (7 `AttributeError: no attribute 'operator_close'`, 1 `ImportError`) and 3 table tests failed on behavior (`AWAITING_FILL -> CLOSE_REQUIRED` not legal in `test_transitions.py` x2 and the new `test_protection_transitions.py` test). The `AttributeError` failures are honest but do not distinguish behaviors.
- Task 2: all 16 new tests failed on the missing method (14 `AttributeError`, 1 `ImportError`, 1 AST test `assert False`); every scenario builder ran to the call (no setup failure). The AttributeError RED is weak evidence, so after GREEN I ran a mutation check: removing the UNPROTECTED stop-lost refusal from `_operator_protect_precheck` made `test_operator_protect_never_places_after_a_confirmed_stop_was_lost` fail; the file was restored and the test passes.
- Task 3: only `test_exec06_five_controls_exist` failed RED (`AttributeError: EXEC06_CONTROLS`); the other 8 new tests pass against existing behavior and are regression guards of the journal-outage contract (D-16).

Tracer feedback gate (Task 1 has no `gate="blocking-human"`): after the GREEN commit the verify command (`tests/test_manual_controls.py tests/test_protection_transitions.py tests/test_transitions.py`) passed end to end together with the protection suites, then Tasks 2 and 3 followed.

## Verification actually run (own tests, tests of touched files, the three gate files; never the full suite)

- `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set (not printed), `-n 4`, at `f2e06c09`: `tests/test_protection_*.py tests/test_manual_controls.py tests/test_transitions.py tests/test_execution_*.py tests/test_emergency_market_close.py tests/test_pending_actions.py tests/test_pending_actions_pg.py tests/test_ast_guards.py tests/test_domain_no_float.py tests/test_no_unratified_defaults.py tests/test_agents_md.py tests/test_cancel_verification.py tests/test_risk_first_spill.py tests/test_journal_failure_paths.py tests/test_reconcile.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_persistence_exit_evidence_pg.py tests/test_system_throttle_protection.py`: 1168 passed, 0 failed, 0 skipped (strict).
- `uv run mypy src`: no issues in 229 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 706 files already formatted. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code 87c82ce0 -- pyproject.toml uv.lock docs/DECISIONS.md config/binance params .planning/STATE.md .planning/ROADMAP.md .planning/REQUIREMENTS.md` exits 0 (T-20-SC: no package added; nothing forbidden touched).
- Line endings: the six existing files were converted to LF for editing and restored to pure CRLF (checked with `file`); the new test file and this SUMMARY are LF (git warns it will convert on checkout, as for the other new files of this phase).
- Not run: the full suite (orchestrator), `-m docker`, any Demo or Binance call. Evidence label: executed tests with the Binance-semantics fake, the real `MarketEmergencyCloser`, the in-memory pending store and a real `LocalSpill` in a temporary directory. `[NOT_TESTED]` reduce-only MARKET behavior and stop semantics on Binance (A4, A8). Nothing is `[DEMO]`.

## Acceptance map

| Criterion | Evidence |
|---|---|
| `test_operator_close_flattens_through_the_coordinator` passes, SL cancelled only after FLAT | yes (no `cancel_algo_order` before the step that reaches FLAT, then SL, TP1, TP2 in order) |
| a named test per Task 2 behavior bullet incl. `..._never_widens_the_stop`, `..._never_places_after_a_confirmed_stop_was_lost` (UNPROTECTED STOP_LOST and both B4 CLOSE_REQUIRED branches, zero adapter calls), `..._refuses_unknown_stop_history`, `..._delegates_to_the_coordinator_step` | yes in `tests/test_manual_controls.py` |
| AST test: no placement and no `_transition` in `operator_protect` | yes (`test_operator_protect_has_no_placement_and_no_transition_of_its_own`, five functions) |
| `tests/test_protection_stop_lost.py` passes unedited | yes (in the 1168; `git diff` shows no change to it) |
| `test_exec06_five_controls_exist` passes | yes |
| `git diff -- src/execution/manager.py` has no edit inside `execute_approved_plan` | yes |
| `ruff check` / `ruff format --check` / `mypy src` exit 0 | yes |

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-20-42 mitigated (no placement call in the control, price-invariant `PlacementSpy` in the delegated-step tests, AST test); T-20-43 mitigated (the close goes through the closer, which reads the quantity; test with the position unreadable sends no market close); T-20-44 transferred (operator id is audit metadata only); T-20-64 mitigated (refusals before any adapter call, zero-call assertions, D077 deadline still escalates); T-20-65 mitigated (`STOP_HISTORY_UNKNOWN` on a flag or inconsistent fields); T-20-SC mitigated. New journal rows carry operator id, codes and state names only; no new network surface.

## Findings for later plans

- **20-19 (restore):** set `_Tracked.stop_history_known = False` for a restored plan whose confirmed / lost history the journal cannot establish; `operator_protect` already refuses on it. Until 20-19 the flag is True for every plan because nothing restores yet.
- **20-22 (alerts):** `PROTECTION_SWEEP_UNVERIFIED` (payload `legs`) and `OPERATOR_*` rows have no alert wiring. A FLAT plan whose stop will not leave the book is swept again every step (one cancel and one verifying query per leg per step, no backoff, no SAFE_MODE): decide whether that needs an alert and a backoff.
- **SAFE_MODE control has no spill:** `SafeModeController.enter_safe_mode` flips the flag first and lets a journal error propagate (the checklist test pins this: state entered, `StoreUnavailable` raised, no spill record). The "leaves its record in the spill" part of the D-16 checklist therefore holds for four of the five controls; closing it needs a spill on the controller (`src/reconcile/safe_mode.py`, not in this plan's files).
- **Existing coordinator behaviour (Deviation 4):** `_confirm` re-places an ABSENT never-confirmed stop before it checks `max_unprotected_ms`, so on the deadline step one more same-id stop is placed and the plan then escalates. Safe (same id, plan price, exchange refuses a duplicate) but worth a line when the owner reviews O-A.
- **20-24 (docs):** EXECUTION_SPEC section 11 should describe `operator_close_position`, `operator_protect_position` (no placement of its own, refusal codes) and `EXEC06_CONTROLS`; the wording that D-26 "re-places" a stop must say "triggers the coordinator's own never-confirmed rule".
- **Operator cadence:** neither control is wired to any command or Telegram surface; Phase 23/24 owns authentication and the entry point.

## Self-Check: PASSED

- FOUND: src/execution/protection.py, src/execution/manager.py, src/domain/transitions.py, tests/test_manual_controls.py, tests/test_protection_sweep_verdicts.py, tests/test_protection_transitions.py, tests/test_transitions.py
- FOUND commits: 5f80e00b, 99f2323c, 2ac132c4, 36314f11, d3f01140, af5c56fb, bde03dec, f2e06c09
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, config/binance/, params/, pyproject.toml, uv.lock, `.gsd/`, `.planning/config.json`, `.planning/state.json`, `.planning/milestone.lock`
