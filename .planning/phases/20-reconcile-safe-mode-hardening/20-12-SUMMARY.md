---
phase: 20-reconcile-safe-mode-hardening
plan: 12
subsystem: reconcile
tags: [reconcile-loop, compare-v2, divergence-policy, local-intent, fail-closed, safe-mode, tdd]

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "20-01 limits + check_reconcile_cadence, 20-04 compare v2, 20-06 durable SafeModeController, 20-07 REST gate recovery, 20-08 spill doubles, 20-09 coordinator hooks, 20-10 UnknownEntryResolver"
provides:
  - "src.reconcile.loop: ReconcileLoop.tick(now_utc), TickReport, ReconcileAdapter / GateRestrictionSource / ProtectionView / ReconcileAlertSink (+ SafeModeGate, UnresolvedIntentSource, OrphanSweeperLike, JournalSink, UnknownEntryStepper) Protocols, journal event types"
  - "src.reconcile.classify: DivergenceAction, DivergencePolicy, POLICY_BY_KIND, classify, ALERT_* names"
  - "src.reconcile.local_intent: LocalIntent.compare_kwargs(), derive_local_intent, STATE_RULES"
  - "tests/support/reconcile_doubles.py: RecordingAlertSink, FakeGate, FakeProtectionView, FakeReconcileAdapter, FakeIntentStore, InMemorySafeModeStore, make_* row builders"
affects: [20-15, 20-16, 20-19, 20-20, 20-21, 20-22, 20-23, 20-24, 20-25]

tech-stack:
  added: []
  patterns:
    - "step-driven library: no sleep, no wall clock, injected now_utc"
    - "one owner per divergence kind: sweeper, coordinator or alert, always plus SAFE_MODE"
    - "fail closed: a failed read never reaches compare"
    - "Protocol seams: pure reconcile modules import no adapter, store or persistence module"

key-files:
  created:
    - src/reconcile/loop.py
    - src/reconcile/classify.py
    - src/reconcile/local_intent.py
    - tests/test_reconcile_loop.py
    - tests/test_reconcile_classify.py
  modified:
    - tests/support/reconcile_doubles.py

key-decisions:
  - "The local data source is the coordinator's protections() views plus ExecutionIntentStore.list_unresolved_intents() (SENT and UNKNOWN rows only); no positions table and no Order row (D-13)."
  - "Several SAFE_MODE reasons in one tick are entered least urgent first (ALERT_ONLY, SWEEP_ORPHAN, DELEGATE) because the controller keeps the last one: the persisted reason is the most urgent."
  - "A divergence is delegated only when exactly one tracked plan matches (by the 29-character plan-hash prefix of the order id, else by symbol among plans that are not FLAT / ENTRY_ENDED_NO_FILL); otherwise it is alerted, never guessed (D-01a)."
  - "Any exception from a truth read or from the local read is a failed read decided by type, never by message text: API_DEGRADATION for the exchange reads, compare and gate, DB_FAILURE for the local source (D-10)."

requirements-addressed: [EXEC-02, OPS-01]

duration: about 55min
completed: 2026-10-21
status: complete
actuals:
  tokens: 29458   # chars/4 over `git diff 7cce83c5 HEAD -- src tests` (117832 chars)
  tasks: 3
  commits: 7      # MEASURED: git rev-list --count 7cce83c5..HEAD, taken before this SUMMARY commit
plan_head_before: 7cce83c532fe8e3b23938ec1dfb60215afb195ae
plan_head_after: 2526b5c5e26594e393c1da88c0f715113c8abb70
---

# Phase 20 Plan 12: Reconcile loop Summary

**One `ReconcileLoop.tick` now reads the three Binance snapshots, derives the local intent from the coordinator and the unresolved intents, runs compare v2 and routes every divergence to SAFE_MODE plus exactly one owner (sweeper for orphans only, coordinator for stop-related exposure, an alert for the rest), skips every REST read under a gate restriction, and treats any failed read as SAFE_MODE rather than agreement.**

Evidence label: executed unit tests with fakes. Nothing was run against Binance or Telegram, nothing is `[DEMO]`, the loop is NOT composed into a running process (Phase 24), and no live read-only reconcile has run. EXEC-02 and OPS-01 are not marked complete (`requirements-addressed` only). Live placement stays disabled.

Base commit `7cce83c5` (develop), branch `p20-12`, final commit before this SUMMARY `2526b5c5`. `commits: 7` is the measured `git rev-list --count 7cce83c5..HEAD` at SUMMARY write. All three tasks were finished; the Context-budget split point after Task 1 was NOT used.

## Owner decision O-C (read from the 20-07 SUMMARY)

The owner chose option a1 with the status and clear commands, so the two restore reasons exist: `GATE_NOT_RESTORED` and `GATE_STATE_UNKNOWN`. The gate-skip test is parametrized over all four reasons (`IP_BAN_418`, `RATE_LIMIT_PAUSE_429`, `GATE_NOT_RESTORED`, `GATE_STATE_UNKNOWN`) and one test drives the real `RestRateLimitGate` with a `FileGateStateStore`: not restored means zero REST reads, restored means a compare. The owner's decisions D-11, D-15, D-01a, D-24 and O-C were taken from the 20-10 and 20-07 SUMMARYs; nothing was recorded on the owner's behalf.

## What was built

- `src/reconcile/classify.py` (pure): `POLICY_BY_KIND` (an immutable mapping) covers exactly the 16 kinds of `compare._DIVERGENCE_KINDS`. Every kind enters SAFE_MODE with its own name as the reason, except STREAM_TASK_DIED which is `USER_DATA_STREAM_HALTED`. ORPHAN_PROTECTIVE is the only `SWEEP_ORPHAN`; POSITION_WITHOUT_STOP, TP_ONLY_POSITION, ENTRY_WITHOUT_PROTECTIVE (alert UNPROTECTED_POSITION) and SIGN_FLIPPED_POSITION, DOUBLED_POSITION (alert DIVERGENCE) are `DELEGATE_TO_COORDINATOR`; FOREIGN_ORDER (alert FOREIGN_ORDER) and UNTRACKED_SYSTEM_ORDER (alert UNKNOWN_ORDER) and every other kind are `ALERT_ONLY`. No kind maps to a cancel of a foreign order.
- `src/reconcile/local_intent.py` (pure): `derive_local_intent(protections, unresolved)` and `LocalIntent.compare_kwargs()`. Source named in the module docstring (D-13, D-30). The per-state table (`STATE_RULES`, eleven names, no import of `src.execution.protection`) says which entry, stop and take-profit legs and which position intent each state contributes. The position intent carries `plan_hash`, `expected_side` (LONG or SHORT) and `max_abs_amount` (the plan's entry quantity), `position_side` BOTH; a missing side or quantity stays None, which compare reads as AMBIGUOUS_POSITION_OWNER. SENT and UNKNOWN rows add their legs (a stop that may exist is never FOREIGN); INTENDED rows add nothing (nothing was sent).
- `src/reconcile/loop.py`: `ReconcileLoop(*, adapter, gate, safe_mode, intent_store, protection, sweeper, alerts, journal, limits, unknown_entries=None)`. Constructor refuses a non-durable controller (ValueError), unset limits (`require_live_ready`, ExecutionLimitsNotConfigured) and a tick not strictly below `max_unprotected_ms` (`check_reconcile_cadence`, ExecutionLimitsInvalid). `tick(now_utc=...)` order: gate restriction (skip, journal `RECONCILE_SKIPPED_GATE`), `restore_complete` (skip, `RECONCILE_SKIPPED_RESTORE_PENDING`), optional `UnknownEntryResolver.step`, three guarded snapshot reads (stop at the first failure), the local read, compare, SAFE_MODE once per distinct reason, delegation, alerts (a raising sink is journaled `ALERT_SINK_FAILED` with the type name), the orphan sweep, one `RECONCILE_TICK` row with counts per kind. An overlapping call returns `SKIPPED_OVERLAP` at once. The loop supplies the sweeper's position verifier: one fresh `snapshot_positions(symbol=...)` per call, summing absolute amounts.
- Never in the loop (AST-tested): a call starting with `place_`, `new_`, `cancel`, `finalize`, `record_result`, `insert`, `update`, `mark_`, `close_` or named `exit_safe_mode`; an import of `src.adapters`, `binance_sdk`, `sqlalchemy`, `src.persistence`, or of the intent store, intent recovery, coordinator, closer or manager modules. An autouse fixture fails any loop test in which `exit_safe_mode` is called.

## Task commits

| Task | Commit | Type | Description |
|---|---|---|---|
| 1 RED | `5d64baf2` | test | tracer tests and the new doubles (collection fails: modules missing) |
| 1 GREEN | `5aa057c6` | feat | classify.py, local_intent.py, loop.py: the foreign-order tracer passes |
| 2 RED | `ac86482a` | test | 57 tests; one failing (urgency order), the rest pin the tracer implementation |
| 2 GREEN | `eb4b6b35` | feat | SAFE_MODE reasons entered least urgent first; explicit never-exits test |
| 3 | `5615ae78` | test | policy table and per-state local-intent tests (all pass on first run) |
| note RED | `6b7ecb6e` | test | failing tests for the gate recovery status in the tick rows |
| note GREEN | `2526b5c5` | feat | `gate_recovery_status` in the tick rows and the report |

Tracer feedback gate (Task 1 has no `gate="blocking-human"`): the Task 1 verify plus the two static guards of `tests/test_reconcile.py` were re-run after the tracer commit and passed (12 passed) before Task 2 began.

## TDD Gate Compliance

`gsd_run check tdd-red-evidence` does not parse pytest output and was not run. RED evidence is the pytest failure seen before each GREEN commit, stated honestly:
- Task 1 RED: collection `ModuleNotFoundError: No module named 'src.reconcile.classify'`, not an assertion failure on the behavior.
- Task 2 RED: 1 failed (`test_safe_mode_ends_on_the_most_urgent_reason_of_the_tick`, assertion on the entered order), 56 passed. The 56 are regression pins for behavior the Task 1 loop already had (the plan puts the full tick in Task 1). They are not new RED.
- Task 3: no RED. All 60 tests passed on the first run against the Task 1 modules. As a sensitivity check I temporarily flipped FOREIGN_ORDER to `SWEEP_ORPHAN` and COMPLETE's take profits to off; 4 tests failed; both files were restored with `git checkout -- <file>` and the committed text was re-verified green. No `feat` commit exists for Task 3.
- Gate-status note: RED was `AttributeError: 'TickReport' object has no attribute 'gate_recovery_status'` (3 tests), then GREEN.

## Deviations from Plan

**1. [Rule 2 - hardening] SAFE_MODE reasons entered least urgent first.** The controller keeps the last reason entered, and compare sorts divergences by symbol and ids, so a tick with UNSYNCED_ALGO and POSITION_WITHOUT_STOP persisted the less important one. The plan says "once per distinct reason"; the order within a tick was open. Commit `eb4b6b35`.

**2. [Binding note, 20-07] `gate_recovery_status` added.** The 20-07 SUMMARY says the gate state is reported by `recovery_status()`. The loop reads it by duck typing (a gate without the method, like `FakeGate`, simply omits the field) and copies it into the `RECONCILE_SKIPPED_GATE` and `RECONCILE_TICK` rows and `TickReport.gate_recovery_status`. A gate with no persistence shows `LEGACY_IN_MEMORY`, which plan 20-25 must not accept. Commits `6b7ecb6e`, `2526b5c5`.

**3. [Additions beyond the listed names]** Journal event `RECONCILE_ACTION_FAILED` (payload: action name, optional reason or kind, exception type name) for a failed SAFE_MODE save, delegation, sweep or UNKNOWN-entry step; outcome constants `TICK_COMPARED`, `TICK_SKIPPED_GATE`, `TICK_SKIPPED_RESTORE_PENDING`, `TICK_READ_FAILED`, `TICK_SKIPPED_OVERLAP`; extra doubles `FakeIntentStore`, `InMemorySafeModeStore`, `AlertCall` and four row builders. A failed SAFE_MODE save does not abort the tick: the controller flips its flag first, so entries stay blocked and the alerts still go out.

**4. [Plan text vs code] The sweeper call.** The plan says `OrphanSweeper.sweep(diff.orphan_protectives)`. The real signature is `sweep(diff, *, position_verifier, now_utc)` (read from `src/reconcile/sweeper.py`); the loop passes the whole `CompareDiff` and its own fresh-read verifier.

**5. [Fact check] A plan-derived stop can never be an ORPHAN_PROTECTIVE.** Compare's orphan rule needs no local position, but the coordinator's states that carry a confirmed stop all carry a position intent. The orphan test therefore uses the other local source the plan names: a SENT STOP_LOSS intent row with no plan, no position and a stop on the exchange. After a plan goes FLAT the coordinator cancels its own legs (`ProtectionCoordinator._sweep`); a leftover leg after that would appear as UNTRACKED_SYSTEM_ORDER (alert only), not as an orphan.

**6. [Process]** The executor's `agent-*` branch allow-list was not applied; the orchestrator pinned worktree `C:/Users/admin/Music/Trading/.claude/worktrees/p20-12` and branch `p20-12`, and the toplevel and branch were verified before every commit. The instruction to `codegraph explore` first was skipped: the worktree has no `.codegraph/` index.

No existing test assertion was changed; `tests/test_reconcile.py` is untouched and passes. `tests/support/reconcile_doubles.py` only gained code and kept its CRLF line endings; the five new files are LF in the working tree.

## Observed findings for the orchestrator (not fixed here: outside this plan's files)

1. **Compare Pass 2 reports every resting entry with no fill as ENTRY_WITHOUT_PROTECTIVE.** Demonstrated and pinned (labelled OBSERVED LIMITATION) by `tests/test_reconcile_classify.py::test_observed_limit_a_resting_entry_with_no_fill_is_entry_without_protective`: a plan in AWAITING_FILL whose entry rests on the exchange gives that divergence, so a composed loop would enter SAFE_MODE, notify the coordinator and send an UNPROTECTED_POSITION alert for every pending entry. Since Phase 19 D-10 the stop is placed only after a fill, but `src/reconcile/compare.py` (plan 20-04) still applies the pre-Phase-19 rule to every open local ENTRY. It fails closed, but it would make every entry block further entries. The fix belongs in compare.py (for example, require a stop only for an entry the local side knows is PARTIALLY_FILLED; exposure is already covered by the position rules) and needs a decision before Phase 24 composes the loop; plan 20-20 tests two AWAITING_FILL plans and may meet it. When fixed, that pin test must change consciously.
2. **Local intent is built from the strictly listed states.** TP legs rest only in COMPLETE (a TP_UNAVAILABLE plan whose TP1 does rest would be UNTRACKED_SYSTEM_ORDER, alert only), and an entry that is still open in CLOSE_REQUIRED / CLOSE_FAILED is not emitted (the same). Both fail closed. An emergency-close order (`xc-` id) that rests would be UNTRACKED_SYSTEM_ORDER; a MARKET close normally does not rest.
3. **Races.** The truth snapshots are read first and the local side last, with no await between the two local calls, so a coordinator step between the reads can only produce a divergence (SAFE_MODE, fail closed), never hide one. "Stale local data" is handled as: read in the tick, no cache, `restore_complete` required, None or an exception from either local call is a failed read (DB_FAILURE). The age of a Binance snapshot is not judged here (feed freshness is plan 20-16).
4. **Documentation still to do (plan 20-24):** GLOSSARY 9.4 rows for the SAFE_MODE reasons named after the new kinds (and `SAFE_MODE_STATE_UNREADABLE` from 20-06); the module docstring of `src/reconcile/__init__.py` still says the reconciler "NEVER places a new order", which the F-604 rewrite replaces with "places nothing itself, delegates".
5. **Not covered by a real run:** `UnknownEntryResolver` is exercised through a recording stand-in (the tick calls `step(now_utc=...)` once, before any read, never under a gate or restore skip, and survives a raising step). Its own behavior is plan 20-10's tests. The alert sink is a recording double; the conformance of `JournalFirstAlertSink.alert` with `ReconcileAlertSink.alert` is plan 20-22's check (the signatures match by reading `src/ops/alerts.py`).

## Verification (only this plan's tests, tests of touched files, and the three gate files)

- `uv run pytest -m "not docker" tests/test_reconcile_loop.py tests/test_reconcile_classify.py tests/test_reconcile.py -x`: 142 passed (final run at `2526b5c5`: 61 in the loop file, 60 in the classify file, 21 in the existing reconcile file).
- Tests of files that import the modified doubles (`test_alerts`, `test_cancel_verification`, `test_intent_recovery_pg`, `test_intent_recovery_unknown_entry`, `test_manual_controls`, `test_risk_first_spill`) plus the three above: 342 passed, 4 warnings (a python-telegram-bot deprecation).
- Gate files after the last code change: `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_persistence_exit_evidence_pg.py -rs`: 88 passed, nothing skipped (PostgreSQL through `TEST_DATABASE_URL`).
- `uv run mypy src`: no issues in 226 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 699 files already formatted.
- `uv lock --check` resolves; `git diff --exit-code -- pyproject.toml uv.lock` exits 0 (T-20-SC, no package added). `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- The full suite was not run (orchestrator).

## Acceptance criteria

| Criterion | Result |
|---|---|
| `test_foreign_order_tick_enters_safe_mode_alerts_and_cancels_nothing` passes | yes |
| AST: no forbidden imports, wall clock or `float(...)` in the three modules | `test_new_modules_are_pure[loop.py, classify.py, local_intent.py]` pass |
| `tests/test_reconcile.py::test_no_place_order_path_in_src_reconcile` passes (file not edited) | yes |
| One named test per Task 2 behavior bullet; `exit_safe_mode` never called across all loop tests | yes (autouse fixture plus `test_a_tick_never_calls_exit_safe_mode_even_when_everything_agrees`) |
| `test_only_orphans_are_sweepable`, `test_every_protection_state_is_covered` pass; ruff clean | yes |

## Known Stubs

None. `unknown_entries` is optional by design (the caller wiring is Phase 24, G4-029).

## Threat Flags

None. No network endpoint, auth path, file access or schema change was added. T-20-28 (no cancel of a foreign order, no placement) is mitigated by the pure policy table, the AST tests and the text guard in `tests/test_reconcile.py`; T-20-29 (reads under a restriction) by the gate check first and the zero-read tests; T-20-30 (partial data as agreement) by the fail-closed read tests; T-20-SC by the unchanged dependency files. Journal payloads hold ids, kinds, symbols, counts and exception class names; poisoned-message tests show an exception text never reaches a journal row.

## Next Phase Readiness

- 20-15 (operator exit), 20-16 (stream and feed divergences, auth), 20-20 (symbol ownership via another `compare_kwargs()` entry), 20-21 (queue order, lot-filter refresh) can build on `ReconcileLoop`; 20-22 wires the real alert sink and checks its conformance; 20-24 writes the GLOSSARY rows; 20-25 must reject a `gate_recovery_status` of `LEGACY_IN_MEMORY`.
- Decide finding 1 (compare Pass 2 versus a resting entry with no fill) before anything composes the loop.

## Self-Check: PASSED

- FOUND: src/reconcile/loop.py, src/reconcile/classify.py, src/reconcile/local_intent.py, tests/test_reconcile_loop.py, tests/test_reconcile_classify.py, tests/support/reconcile_doubles.py
- FOUND commits: 5d64baf2, 5aa057c6, ac86482a, eb4b6b35, 5615ae78, 6b7ecb6e, 2526b5c5
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, config/binance/, params/, pyproject.toml, uv.lock, `.gsd/`, `.planning/config.json`, `.planning/state.json`, `.planning/milestone.lock`
