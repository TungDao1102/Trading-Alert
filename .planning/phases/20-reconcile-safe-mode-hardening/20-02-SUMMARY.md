---
phase: 20-reconcile-safe-mode-hardening
plan: 02
subsystem: execution-protection
tags: [protection, transition-guard, state-machine, replay, fail-closed, d077, tdd]

requires:
  - phase: 19-execution-plan-binding-price-check
    provides: ProtectionCoordinator and the ProtectionState names (plans 19-11, 19-14, 19-16), the PROTECTION_TRANSITION journal event
provides:
  - "TransitionKind.PROTECTION, the PROTECTION table (eleven ProtectionState values) and PROTECTION_INITIAL_STATE in src/domain/transitions.py"
  - "ProtectionCoordinator._transition(..., evidence=None) -> bool: the one checked place a protection state changes; equal state is a no-op, a refused move is journaled PROTECTION_TRANSITION_REJECTED and enters SAFE_MODE PROTECTION_STATE_INVALID"
  - "src/execution/protection_replay.py: clearing_violation (shared by the live guard and the replay), CLEARING_EVIDENCE, replay_transitions, ReplayedProtection, ProtectionReplayInvalid"
  - "evidence key in every PROTECTION_TRANSITION payload; REST_STOP_CONFIRMED and REST_FLAT_TWO_READS_ENTRY_TERMINAL recorded where a blocking state clears"
affects: [20-09, 20-17, 20-19, 20-24]

plan_head_before: e1feed221283118aeacb34d1813993e8252f27ac
plan_head_after: fbaae0ea30a0d84c0ad4bbed228673c47ecb0202

actuals:
  tokens: 16445   # chars/4 over `git diff e1feed22 HEAD -- src tests` (65780 chars)
  tasks: 3
  commits: 8      # MEASURED: git rev-list --count e1feed22..HEAD (4 test + 3 feat + 1 fix)

tech-stack:
  added: []
  patterns:
    - "one table in src.domain keyed by string values of an execution-side enum, pinned by a parity test (domain never imports execution)"
    - "guard and replay share one pure function (clearing_violation) so they cannot drift"
    - "a refused state move journals its own event and enters SAFE_MODE; the caller keeps its fail-closed branch"

key-files:
  created:
    - src/execution/protection_replay.py
    - tests/test_protection_transitions.py
  modified:
    - src/domain/transitions.py
    - src/execution/protection.py
    - tests/test_transitions.py
    - tests/test_persistence_transitions_pg.py

key-decisions:
  - "The PROTECTION kind is not persisted and has no GLOSSARY section 11 block (waits for O-01); the DOMN-04 parity tests exempt it through GLOSSARY_DEFERRED_KINDS and the DB parity tests use PERSISTED_KINDS."
  - "Audit finding F1 resolved by adding PROTECTED_ENTRY_OPEN -> FLAT (lost stop, two zero reads, entry terminal) to the ProtectionState docstring and the table; the module docstring of the coordinator already states that outcome for WR-04."
  - "The O-H exception (a return from CLOSE_REQUIRED to protected exposure) is NOT built: default NO."
  - "A FLAT sweep runs only after an accepted FLAT move, so a refused move can never cancel the stop."

requirements-completed: [RISK-03]  # copied from the plan frontmatter as in 20-01; REQUIREMENTS.md is NOT edited and RISK-03 is NOT marked complete (wording checkpoint O-A is open)

coverage:
  - id: D1
    description: "PROTECTION table and guard in _transition: a CLOSE_REQUIRED -> PROTECTED request is refused end to end (state, seq, rejected journal row, SAFE_MODE PROTECTION_STATE_INVALID)"
    requirement: "RISK-03"
    verification:
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_close_required_never_downgrades_to_protected"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_tables_match_the_plan_objective[PROTECTION]"
        status: pass
    human_judgment: false
  - id: D2
    description: "Different clearing rules for UNPROTECTED (first-fill versus stop-lost) and CLOSE_REQUIRED/CLOSE_FAILED, with the evidence journaled on each clearing move"
    requirement: "RISK-03"
    verification:
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_unprotected_first_fill_clears_only_with_rest_stop_evidence"
        status: pass
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_stop_lost_unprotected_cannot_clear_to_protected_even_with_stop_evidence"
        status: pass
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_flat_from_a_blocking_state_needs_the_flat_evidence"
        status: pass
    human_judgment: false
  - id: D3
    description: "Equal-state no-op, duplicate fill after UNPROTECTED, stale ACTIVE stop after CLOSE_REQUIRED, one assignment point for .state (AST), evidence at every FLAT and settle call site"
    requirement: "RISK-03"
    verification:
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_a_repeated_request_for_the_current_state_writes_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_stale_active_stop_after_close_required_never_downgrades"
        status: pass
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_no_code_path_assigns_state_outside_transition"
        status: pass
    human_judgment: false
  - id: D4
    description: "replay_transitions validates a journaled PROTECTION_TRANSITION history through the same table and clearing rules; each corruption kind raises ProtectionReplayInvalid"
    requirement: "RISK-03"
    verification:
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_a_real_run_replays_to_its_last_state"
        status: pass
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_a_malformed_row_fails_closed"
        status: pass
      - kind: unit
        ref: "tests/test_protection_transitions.py#test_protection_replay_is_a_pure_module"
        status: pass
    human_judgment: false
  - id: D5
    description: "Whether the table and the clearing rules match the owner's intent for the real exchange (Demo behavior of a stop that reads ACTIVE after CLOSE_REQUIRED, A3/A2 assumptions)"
    verification: []
    human_judgment: true
    rationale: "Every test runs against the project fakes. No Demo observation exists for this plan; the Phase 19 probes and the owner's D055 closure decide whether the modelled exchange behavior is right."

duration: 18min
completed: 2026-10-21
status: complete
---

# Phase 20 Plan 02: Protection Transition Guard Summary

**Every protection-state change now passes one table-checked function (PROTECTION kind in src/domain/transitions.py): CLOSE_REQUIRED cannot be downgraded, UNPROTECTED clears only with REST evidence and never after a lost stop, each clearing move journals its evidence, and a pure replay validator runs a journaled history through the same rules.**

Evidence label: executed unit tests with fakes (project fake exchange, real `MarketEmergencyCloser`, virtual time) plus `[DOC]` code reading. No `[DEMO]` observation exists for this plan. LIVE stays blocked (`LIVE_ORDERS_DISABLED`).

## Performance

- **Duration:** 18 min
- **Started:** 2026-10-21T08:11:37Z
- **Completed:** 2026-10-21T08:30:08Z (clock of the dev machine)
- **Tasks:** 3 (plus one fail-closed fix found while auditing, see Deviations)
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- **T-A guard (Task 1, tracer).** `TransitionKind.PROTECTION` with an eleven-key table transcribed from the `ProtectionState` docstring; `ProtectionCoordinator._transition` checks it. A refused move leaves `state`, `seq` and `last_reason` unchanged, journals one `PROTECTION_TRANSITION_REJECTED` row (id prefix `ptx`) and enters SAFE_MODE `PROTECTION_STATE_INVALID`. An equal-state request is a no-op decided before the guard.
- **Clearing rules (Task 2).** `UNPROTECTED -> PROTECTED_ENTRY_OPEN/PROTECTED` needs `REST_STOP_CONFIRMED` and `stop_lost_at` unset; a stop-lost UNPROTECTED is refused with code `STOP_LOST_CLEARED` even with evidence. `FLAT` from UNPROTECTED, PROTECTED_ENTRY_OPEN, CLOSE_REQUIRED or CLOSE_FAILED needs `REST_FLAT_TWO_READS_ENTRY_TERMINAL`. CLOSE_REQUIRED/CLOSE_FAILED have no edge to a protected state, so no evidence can open one. Every `PROTECTION_TRANSITION` payload now has an `evidence` key (null when the move clears nothing).
- **Replay (Task 3).** `replay_transitions(rows, plan_hash=)` sorts by `seq`, counts an identical duplicate once, and raises `ProtectionReplayInvalid` (fixed reason code, never row text) for: `EMPTY_HISTORY`, `MALFORMED_ROW`, `PLAN_MISMATCH`, `DUPLICATE_CONFLICT`, `SEQ_GAP`, `BAD_START`, `CHAIN_BROKEN`, `ILLEGAL_EDGE`, `EVIDENCE_MISSING`, `STOP_LOST_CLEARED`. A real coordinator run (NONE, AWAITING_FILL, UNPROTECTED, PROTECTED_ENTRY_OPEN, PROTECTED, FLAT) replays to FLAT. No production caller exists yet (plan 20-19 is the caller).

## Task Commits

TDD, each task RED then GREEN:

1. **Task 1: Tracer, PROTECTION table plus guard** - RED `e7336791` (test), GREEN `da14fd9e` (feat)
2. **Task 2: Call-site audit, clearing rules, evidence** - RED `43b530a0` (test), GREEN `a71a9a87` (feat)
3. **Task 3: replay_transitions** - RED `92a2f77e` (test), GREEN `3bef51c8` (feat)
4. **Fail-closed sweep ordering (deviation 4)** - RED `a087f48d` (test), fix `fbaae0ea` (fix)

**Plan metadata:** the `docs(20-02)` commit that adds this file.

## Transition audit

All 18 `self._transition(` call sites of `src/execution/protection.py` (line numbers at HEAD `fbaae0ea`, CRLF file). "Verdict" is against the PROTECTION table after Task 2. Reasons are the journaled `reason` text; evidence is passed where the code already holds it.

| Line | Method | From-states reachable | To | Reason | Evidence | Verdict |
|---|---|---|---|---|---|---|
| 638 | `register_resting_entry` | NONE | AWAITING_FILL | REGISTERED / REGISTERED_ENTRY_STATE_UNKNOWN | - | legal (initial state) |
| 772 | `_on_first_fill` | AWAITING_FILL, ENTRY_UNRESOLVED | UNPROTECTED | FIRST_FILL_STREAM / FIRST_FILL_REST | - | legal |
| 827 | `_on_no_position_on_stop` | UNPROTECTED | FLAT | NO_POSITION_ON_STOP | REST_FLAT_TWO_READS_ENTRY_TERMINAL | legal; evidence required and passed |
| 887 | `_poll_entry` | AWAITING_FILL, ENTRY_UNRESOLVED | ENTRY_ENDED_NO_FILL | ENTRY_ENDED_NO_FILL | - | legal |
| 914 | `_mark_unknown_entry_unresolved` | AWAITING_FILL | ENTRY_UNRESOLVED | ENTRY_NOT_FOUND_AFTER_GTD_GRACE | - | legal; **F2** the entry edge is implied by the docstring, written into the table |
| 939 | `_poll_unresolved_entry` | ENTRY_UNRESOLVED | AWAITING_FILL | ENTRY_FOUND | - | legal |
| 1252 | `_on_stop_lost` | UNPROTECTED, PROTECTED_ENTRY_OPEN | FLAT | STOP_CONSUMED_FLAT | REST_FLAT_TWO_READS_ENTRY_TERMINAL | UNPROTECTED -> FLAT legal; **F1** PROTECTED_ENTRY_OPEN -> FLAT was not in the docstring, resolved by adding the edge |
| 1262 | `_on_stop_lost` | PROTECTED_ENTRY_OPEN | UNPROTECTED | STOP_LOST | - | legal (docstring WR-04) |
| 1356 | `_settle_state` | UNPROTECTED, PROTECTED_ENTRY_OPEN | PROTECTED | STOP_CONFIRMED_ENTRY_TERMINAL / ENTRY_TERMINAL | REST_STOP_CONFIRMED | legal; from UNPROTECTED the evidence and `stop_lost_at is None` are enforced |
| 1364 | `_settle_state` | UNPROTECTED | PROTECTED_ENTRY_OPEN | STOP_CONFIRMED_ENTRY_OPEN | REST_STOP_CONFIRMED | legal; evidence enforced |
| 1449 | `_attach_take_profits` | PROTECTED | FLAT | POSITION_CLOSED | REST_FLAT_TWO_READS_ENTRY_TERMINAL | legal (docstring: PROTECTED, when REST is flat) |
| 1496 | `_attach_take_profits` | PROTECTED | COMPLETE | TP_LEGS_CONFIRMED | - | legal |
| 1518 | `_enter_tp_unavailable` | PROTECTED | TP_UNAVAILABLE | TP_UNAVAILABLE | - | legal |
| 1556 | `_watch_exit` | COMPLETE, TP_UNAVAILABLE | FLAT | POSITION_CLOSED | REST_FLAT_TWO_READS_ENTRY_TERMINAL | legal |
| 1579 | `_enter_close_required` | UNPROTECTED, PROTECTED_ENTRY_OPEN | CLOSE_REQUIRED | branch code (B1..B5, NO_POSITION_ON_STOP_BUT_EXPOSED, B4_STOP_LOST_UNRESOLVED) | - | legal |
| 1617 | `_attempt_close` | CLOSE_REQUIRED | CLOSE_FAILED | CLOSE_FAILED / CLOSE_NOT_SENT | - | legal |
| 1654 | `_close_flow` | CLOSE_REQUIRED, CLOSE_FAILED | FLAT | CLOSED_ENTRY_TERMINAL | REST_FLAT_TWO_READS_ENTRY_TERMINAL | legal; evidence required and passed |
| 1664 | `_close_flow` | CLOSE_FAILED | CLOSE_REQUIRED | CLOSED_ENTRY_OPEN | - | legal |

Findings: **F1** (PROTECTED_ENTRY_OPEN -> FLAT) and **F2** (AWAITING_FILL -> ENTRY_UNRESOLVED) were the only edges the literal docstring did not list. Both are covered by the docstring's stated intent (module docstring bullet "Stop lost, exposure not proven" ends FLAT on two zero reads with a terminal entry; the ENTRY_UNRESOLVED paragraph says it is entered when an AWAITING_FILL entry is never found by GTD plus the grace). Both were added to the `ProtectionState` docstring or the table's source comment and to the `EXPECTED` table in `tests/test_transitions.py`. No call site had to be changed to fit the table, and no branch decision, deadline or placement changed.

D-29 deferred: exchange event-time column and monotonic Order updates are Phase 24 (before the event stream feeds persistent Order updates); Phase 20 detects only what ordering and dedup evidence it has

Limit [DESIGN]: Phase 20 has no exchange event-time column. The guard detects only what the `seq` ordering and the equal-state dedup give it. General stale-event detection is NOT claimed.

## Files Created/Modified

- `src/domain/transitions.py` - `TransitionKind.PROTECTION`, `_PROTECTION`, `PROTECTION_INITIAL_STATE`, module docstring
- `src/execution/protection.py` - checked `_transition` (returns bool, `evidence=`), `_edge_is_legal`, `_reject_transition`, evidence at every FLAT/settle call, sweep only after an accepted FLAT, docstring edge
- `src/execution/protection_replay.py` (new) - evidence constants, `clearing_violation`, `replay_transitions`, `ReplayedProtection`, `ProtectionReplayInvalid`
- `tests/test_protection_transitions.py` (new) - 29 tests: guard, clearing, stale/duplicate, AST guards, replay, pure module
- `tests/test_transitions.py` - seven kinds, PROTECTION entry in `EXPECTED`, `GLOSSARY_DEFERRED_KINDS`, `ENUM_KINDS`
- `tests/test_persistence_transitions_pg.py` - `PERSISTED_KINDS` (no table, no trigger for PROTECTION)

## Decisions Made

See `key-decisions`. Not decided and not built here: the O-H exception, GLOSSARY section 11 for ProtectionState (waits for the owner's D055 closure acceptance), any caller of `replay_transitions` (plan 20-19).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] A refused FLAT move still swept the protective legs**
- **Found during:** Task 2 audit (all five `_sweep` calls followed a `_transition(FLAT)` whose result was ignored)
- **Issue:** `_transition` now can refuse a move; the sweep cancels every leg including an ACTIVE stop, so a refused FLAT must not sweep.
- **Fix:** `_sweep` runs only when `_transition` returned True at the five call sites. No change for an accepted move. Unreachable today (every FLAT site holds a legal edge and its evidence), so this guards the edges plans 20-09 and 20-17 add.
- **Files modified:** `src/execution/protection.py`, `tests/test_protection_transitions.py`
- **Verification:** `test_a_refused_flat_move_never_sweeps_the_protective_legs` (RED: three `cancel_algo_order` calls, `assert 3 == 0`; GREEN passes)
- **Committed in:** `a087f48d` (RED), `fbaae0ea` (fix)

### Plan-order and design deviations (no rule needed)

**2. `protection_replay.py` created in Task 2, not Task 3.** The evidence constants and `clearing_violation` are first needed by the Task 2 guard; creating the module then keeps the live guard and the replay on one definition from their first use. Task 3 added `replay_transitions` and the types. The plan's file lists for Tasks 2 and 3 are therefore swapped for this file.

**3. SAFE_MODE entry for a refused move uses its own best-effort call, not `_enter_safe_mode_once`.** That helper shares the `_db_failure_reported` flag with `DB_FAILURE`; reusing it would let an earlier DB failure suppress `PROTECTION_STATE_INVALID` (or the reverse). `_reject_transition` calls `enter_safe_mode` directly inside a try/except, the same pattern as `_enter_close_required`.

**4. Slightly wider than the plan text:**
- The flat-evidence rule also covers `PROTECTED_ENTRY_OPEN -> FLAT` (the audit edge F1), because its only call site holds the evidence.
- The rejected-move payload adds `evidence` and a fixed `rejection` code (`ILLEGAL_EDGE`, `EVIDENCE_MISSING`, `STOP_LOST_CLEARED`); the replay accepts an optional `plan_hash` row key (the journal event's entity id) next to the identity triple (`approval_id`, `trade_plan_id`, `symbol`) for the `PLAN_MISMATCH` check, and adds the codes `EMPTY_HISTORY`, `BAD_START`, `DUPLICATE_CONFLICT`.

---

**Total deviations:** 1 auto-fixed (Rule 2), 3 design or order notes. **Impact on plan:** no scope creep; no branch decision, deadline or placement changed; every plan acceptance criterion is met.

## TDD Gate Compliance

RED then GREEN commits exist for each task and for the sweep fix (`git log --grep` on `test(20-02)` precedes `feat(20-02)`/`fix(20-02)` each time). RED evidence is the pytest failure output seen before each GREEN commit (`gsd_run check tdd-red-evidence` does not parse pytest output, found in plan 20-01, so it was not used):

- Task 1 RED: `test_close_required_never_downgrades_to_protected` failed on `assert None is False` (the intended assertion); the two table tests failed with `ImportError`/`AttributeError` because `TransitionKind.PROTECTION` did not exist.
- Task 2 RED: seven new tests failed (`TypeError` for the missing `evidence` keyword, the audit edge refused so the state stayed `PROTECTED_ENTRY_OPEN`, `ImportError` of the evidence names, a missing `evidence` payload key) and two parametrized table tests failed on the added FLAT edge. Four Task 2 tests (stale ACTIVE stop after CLOSE_REQUIRED, duplicate fill after UNPROTECTED, equal-state no-op, the AST single-assignment test) passed at RED because the Task 1 guard and the existing coordinator already satisfy them; they are regression pins, not new behavior.
- Task 3 RED: 12 tests failed with `AttributeError` (`replay_transitions`, `ProtectionReplayInvalid` absent); the real-run history helper passed its own chain assertion first, so the failure is the missing API, not the fixture.
- Sweep fix RED: `assert 3 == 0`.

## Verification (what was run, with results)

All `[executed]`, on the dev machine, `TEST_DATABASE_URL` set (name ends `_test`; value never printed):

- `uv run pytest -m "not docker" tests/test_protection_transitions.py tests/test_transitions.py tests/test_protection_branches.py tests/test_protection_stop_lost.py tests/test_protection_coordinator.py tests/test_protection_take_profits.py tests/test_protection_unknown_entry.py` : 177 passed
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_transitions_pg.py` : 65 passed (PostgreSQL, strict, Task 1 gate; unchanged files afterwards)
- Callers of the coordinator (not in the plan list, run as an impact check): `tests/test_demo_rehearsal_flow.py test_emergency_market_close.py test_exchange_error_rejections.py test_execution_attach.py test_execution_manager.py test_protection_router_rig.py test_system_throttle_protection.py test_phase19_gate.py test_binance_usdm_signed_calls.py test_execution_write_ahead_pg.py` : 597 passed
- `uv run mypy src` : Success, no issues in 215 source files; `uv run ruff check` : all passed; `uv run ruff format --check` : 672 files formatted
- `uv run python scripts/verify_decision_alignment.py all` : ALL_PASS
- `git diff --exit-code -- pyproject.toml uv.lock docs/GLOSSARY.md docs/DECISIONS.md` : exit 0 (T-20-SC: no dependency added; GLOSSARY and DECISIONS untouched)
- `grep -nE "^[[:space:]]*(from|import) src[.]execution" src/domain/transitions.py` : no output
- The full suite was NOT run (orchestrator runs it once per phase).

## Issues Encountered

- The first Task 2 duplicate-fill test fed the fake a second fill on an already cancelled entry (`KeyError` in the fake). Fixed in the test by re-queuing the same routed fill, which is what a repeated stream event is.
- Windows line endings: `src/execution/protection.py` is CRLF in the working tree and was edited bytes-aware (a small multi-edit helper kept in the scratchpad, not in the repo); `file` confirms CRLF after the final edit.

## Limits and open items

- `[NOT_TESTED]` The "late REST answer reads the stop ACTIVE after CLOSE_REQUIRED" case is exercised by calling `_settle_state` directly with a forced `entry_terminal_at`. No production path reads the stop in CLOSE_REQUIRED/CLOSE_FAILED (`_close_flow` does not), so the guard is defense in depth; no end-to-end late-answer path exists to test.
- `[DOC]` The `REST_FLAT_TWO_READS_ENTRY_TERMINAL` evidence at the CLOSE_* to FLAT site rests on `MarketEmergencyCloser` answering True only on two consecutive zero reads (`src/execution/emergency_close.py`, tested in `tests/test_emergency_market_close.py`). The `ScriptedEmergencyCloser` double used in some tests does not do two reads.
- Callers other than the five sweep sites ignore the `bool`; after a refused move the caller continues its own branch, which fails closed (for example `_enter_close_required` still alerts and closes).
- Not a Demo observation; not a D055 closure; not LIVE approval. Phase 20 criterion 2 wording (O-A) is untouched.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 20-09 (supervision after PROTECTED) and 20-17 (operator close) extend the one `_PROTECTION` table and `clearing_violation`; any new edge needs an `EXPECTED` entry in `tests/test_transitions.py`.
- Plan 20-19 can call `replay_transitions(rows, plan_hash=...)` with the decoded `PROTECTION_TRANSITION` payloads; a pre-20-02 history that crossed a clearing edge fails closed (`EVIDENCE_MISSING`) by design.
- Plan 20-24 copies the "D-29 deferred" line into `20-DEFERRED.md`.

## Threat Flags

None. No network endpoint, auth path, file access or schema change was added; the new journal event type `PROTECTION_TRANSITION_REJECTED` carries fixed text and ids only.

---
*Phase: 20-reconcile-safe-mode-hardening*
*Completed: 2026-10-21*
## Self-Check: PASSED

Created files and the eight task commits were checked on disk and in git; the plan-level verification ran after the last code commit (see Verification).
