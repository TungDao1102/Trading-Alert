---
phase: 20-reconcile-safe-mode-hardening
plan: 21
subsystem: reconcile-loop
tags: [reconcile, tick-order, lot-filters, d-20, d-21, q4, o-e, fail-closed, tdd]
requires: [20-07, 20-12, 20-14, 20-16, 20-18]
provides:
  - "ReconcileLoop keywords lot_filters (LotFilterRefresher), pending_actions (OpenPendingSource), risk_reducer (RiskReducer = Callable[[], Awaitable[None]]); all default None, so an unwired loop behaves as before"
  - "TickReport.order: tuple of PHASE_* names in execution order (gate, restore, risk_reducing, feeds, stream, unknown_entries, reads, local, compare, act, sweep, background)"
  - "journal event types RECONCILE_RISK_REDUCING_FIRST and RECONCILE_BACKGROUND_SKIPPED; RISK_REDUCING_KIND_ORDER (Q4 order)"
  - "background lot-filter refresh, last in a compared tick (D-21)"
  - "risk-reducing-first phase right after the gate and restore checks (D-20, owner decision O-E accept-queue-order)"
affects: [20-24, 20-25, 24]
tech-stack:
  added: []
  patterns:
    - "a per-tick phase recorder (self._order, reset under the tick lock) instead of threading a list through every step"
    - "kinds matched by string value (RISK_REDUCING_KIND_ORDER) with a parity test against PendingKind, so src.reconcile imports no store"
key-files:
  created:
    - tests/test_reconcile_queue_order.py
  modified:
    - src/reconcile/loop.py
key-decisions:
  - "O-E accepted by the owner as queue order only: the risk_reducer is awaited first once the gate allows sending; no 429/418 bypass, no reserved weight, no number."
  - "The background phase re-asks the gate before the phase and before each symbol, because it makes REST reads and a pause can begin during a tick."
  - "A read-failed or skipped tick runs no background phase; only a COMPARED tick does."
requirements-addressed: [RISK-03, EXEC-02]
status: complete
duration: about 1h
completed: 2026-10-21
estimate:
  tokens: 60000
  tasks: 3
actuals:
  tokens: 11157   # chars/4 over `git diff 9632d69e HEAD -- src tests` (44628 chars)
  tasks: 3
  commits: 2      # MEASURED: git rev-list --count 9632d69e..HEAD at SUMMARY write, before the SUMMARY commit
plan_head_before: 9632d69ed6f009a119110ba8aa03ffbcd38e5add
plan_head_after: f4fbbb18ef5084536cd386c3de60dcd5128f4a6b
---

# Phase 20 Plan 21: Order of work inside a reconcile tick Summary

**A compared tick now refreshes the last validated lot filters of every tracked symbol as its final, skippable background step, and once the REST gate allows sending, open pending risk-reducing rows hand the tick to the injected `risk_reducer` before feeds, reads, sweep and background work; a pause is never bypassed.**

`commits: 2` is measured before the SUMMARY commit: Task 1 and Task 3 are commits; Task 2 is the owner checkpoint (no code). `requirements-addressed` only: no requirement is marked complete here, and STATE.md / ROADMAP.md are left to the orchestrator.

## Owner decision O-E

Asked at Task 2 (checkpoint:decision, `gate="blocking-human"`): what "reserved priority for risk-reducing calls" means (D-20).

Owner answer, recorded verbatim (2026-10-21, relayed by the orchestrator in the executor prompt):

> O-E: accept-queue-order

Meaning, as read by the review and accepted by the owner: reserved priority means queue ORDER only, once the REST gate allows sending. It is not a bypass of a 429/418 cooldown, it reserves no request weight, and it needs no number (D-20, D-18). Task 3's precondition ("20-21-SUMMARY.md records Owner decision O-E as accept-queue-order") is met by this section; Task 3 ran after it.

## What was built

- **Task 1 (tracer, commit `cb344f2c`)**: the `lot_filters` keyword and `_background`. After the compare, the act step and the sweep, a COMPARED tick calls `refresh_if_due(symbol, now_utc=now_utc)` once per tracked symbol (plans not FLAT / ENTRY_ENDED_NO_FILL, sorted). The gate is asked again before the phase and before each symbol (a pause that starts during the tick is never bypassed; skip row `RECONCILE_BACKGROUND_SKIPPED` reason `GATE_RESTRICTED`). A refresher that returns False or raises never fails the tick, adds no SAFE_MODE reason and is not put in `action_failures`; a raise is journaled as `RECONCILE_ACTION_FAILED` with action `lot_filter_refresh`, the symbol and the exception class name only. A tick under a gate restriction, a restore-pending tick and a read-failed tick run no background phase. `TickReport.order` records the phases that ran.
- **Task 3 (commit `f4fbbb18`)**: `_risk_reducing_first`, called right after the gate and restore checks.
  - With a `pending_actions` store wired: `list_open()` non-empty -> journal `RECONCILE_RISK_REDUCING_FIRST` (distinct kinds in Q4 order CLOSE_NOT_SENT, PROTECTION_ENTRY_CANCEL_NOT_SENT, STOP_NOT_SENT, plus `open_count` and `reducer_bound`), then `await risk_reducer()`. Empty -> nothing.
  - `list_open()` raising -> `RECONCILE_READ_FAILED` (source `pending_actions`, exception class name), SAFE_MODE `DB_FAILURE`, the reducer is still awaited (fail toward reducing risk), background skipped (`PENDING_UNREADABLE`).
  - A raising reducer is journaled by exception class name (`RECONCILE_ACTION_FAILED`, action `risk_reducer`), added to `action_failures`, and the tick goes on.
  - The background phase is skipped with `OPEN_PENDING_ACTIONS` while any row is still open after the tick, and with `PENDING_UNREADABLE` when the second read fails.
  - Without a bound reducer, open rows are journaled with `reducer_bound: false`, nothing is sent and the background phase is skipped.
- The loop sends nothing itself: no placement or cancel call exists in `loop.py` (the existing AST guard in `tests/test_reconcile_loop.py` still passes) and a test pins `forbidden_calls == []` and no cancels with the reducer, refresher and rows all wired.
- Docstrings (module and class) state that the new phase is ordering only, never a bypass of a pause, reserves no weight, and promises no immediate send. No claim is made that a position always has a stop under every rate-limit condition (Q4).

## Verification

- `uv run pytest -m "not docker" tests/test_reconcile_queue_order.py tests/test_reconcile_loop.py tests/test_reconcile_stream_divergences.py tests/test_reconcile_classify.py tests/test_agents_md.py tests/test_domain_no_float.py`: all passed (186 tests in the final run; the plan's two-file command alone: 82 passed).
- `uv run mypy src`: no issues in 233 source files. `uv run ruff check` and `uv run ruff format --check` on the touched files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock`: exit 0 (T-20-SC).
- The full suite was not run (orchestrator's job once per phase).
- Evidence label: executed unit tests with fakes and a shared call-order recorder. Binance behavior after a pause is [DOC]; no guarantee of immediate sending is claimed.

Named tests per behavior bullet in `tests/test_reconcile_queue_order.py`: `test_lot_filter_refresh_is_background_work_last`, `test_restricted_gate_makes_no_call_and_no_refresh`, `test_a_failing_refresher_never_fails_the_tick` (False and raising), `test_pause_is_never_bypassed_by_the_queue`, `test_open_rows_run_the_risk_reducer_before_reads_sweep_and_background`, `test_kinds_are_journaled_in_q4_order`, `test_background_is_skipped_while_rows_remain_open_after_the_reducer`, `test_background_runs_when_the_reducer_resolved_every_row`, `test_unreadable_pending_store_enters_db_failure_and_still_reduces_risk`, `test_the_loop_itself_places_and_cancels_nothing`, plus the parity test `test_q4_kind_order_matches_the_pending_kinds`.

## Deviations from Plan

### Auto-fixed / environment issues

**1. [Rule 3 - Blocking] Worktree base was stale**
- **Found during:** startup, before Task 1
- **Issue:** the agent worktree started at `9d8a9b0e` (Phase 19 tip), 151 commits behind `develop` `9632d69e`; the Phase 20 plans, `src/reconcile/loop.py` v2 and the 20-07..20-18 code did not exist there.
- **Fix:** `git merge --ff-only 9632d69e` on the agent branch (clean tree, nothing committed yet; fast-forward only, no history rewritten).
- **Commit:** none (fast-forward).

**2. [Rule 2 - Missing critical functionality] Gate re-check inside the background phase**
- **Found during:** Task 1 design, against the prohibition "no code path in the tick performs a REST call while gate.restriction() is not None".
- **Issue:** the tick asks the gate once at the start; a 429 can begin during the tick, and the refresh is a REST read.
- **Fix:** `_background` asks the gate before the phase and before each symbol and skips with `GATE_RESTRICTED`. Not in the plan text; covered by `test_gate_restricted_during_the_tick_stops_the_background_phase`.
- **Commit:** `cb344f2c`.

### Choices where the plan left room

- Background runs only after a COMPARED tick (not after READ_FAILED / skipped ticks); the refresh is a REST read and the exchange is already in doubt there.
- A refresh failure is journaled but not added to `TickReport.action_failures` (the RECONCILE_TICK row is written before the background step, so adding it there would make the report and the journal disagree).
- The plan's Task 1 commit already carries the Task 3 constants, Protocols and the pending-store checks inside `_background` (inert while `pending_actions` is None); Task 3 adds the risk-reducing phase and its tests.

## Known Stubs

None. `risk_reducer`, `pending_actions` and `lot_filters` are optional injection points by design; Phase 24 binds the real coordinator and closer steps, the `PendingActionStore` and the `LotFilterSource`. Until then a loop built without them behaves as before.

## Threat Flags

None. No new endpoint, auth path, file access or schema change. T-20-52 (bypassing a pause) is mitigated: the gate check stays first and a restricted tick makes no call (`test_pause_is_never_bypassed_by_the_queue`). T-20-53 (stale stop before a required close) is mitigated by the Q4 kind order handed to the reducer; superseded stops are never sent (plan 20-14). T-20-SC: no dependency change.

## Self-Check: PASSED

- FOUND: `src/reconcile/loop.py`, `tests/test_reconcile_queue_order.py`
- FOUND: commits `cb344f2c`, `f4fbbb18` (ancestors of HEAD)
