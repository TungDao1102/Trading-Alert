---
phase: 25-demo-integration-test-campaign
plan: 12
subsystem: demo-scenarios
tags: [D-04, D-05, S07, restart-cuts, crash, abandon, D079, D080, D-13, fault-edge, tdd, EXEC-01, EXEC-03]
requires: [25-02, 25-08, 25-09, 25-10, 25-11]
provides:
  - "tests/support/demo_scenarios/s07_restart_cuts.py: S07 run(env, recorder, *, cut, probe_error=False, late_restart=False) for cuts a, b, c, plus start_tolerant, mutating_counts, lost_answer and the step recorders"
  - "CI twin tests/test_demo_twin_s07_restart_cuts.py and owner-run demo tests (one per cut) tests/demo/test_demo_s07_restart_cuts.py"
affects: [25-17, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "a crash is abandon() then restart(): a second process over the same stores and exchange; a crashed process is never shut down in order"
    - "an injected trigger is DEMO_FAULT_INJECTED, the second process's reaction carries the env label"
    - "exchange POSTs counted at the FaultEdge ledger (both processes, fake and Demo alike)"
key-files:
  created:
    - tests/support/demo_scenarios/s07_restart_cuts.py
    - tests/test_demo_twin_s07_restart_cuts.py
    - tests/demo/test_demo_s07_restart_cuts.py
  modified: []
key-decisions:
  - "Cut (a) injects TWO triggers, not one: the entry answer is dropped (drop_response_after_send, -1007 'send status unknown') AND the first process's own immediate probe by client id is failed (raise_before_send on query_order_by_client). Without the second, the manager's in-process probe (D080) finds the order and the entry is ACKED in the first process, so there is no crash-dependent recovery to observe. With it the first process ends UNKNOWN + SAFE_MODE ENTRY_STATE_UNKNOWN and crashes; the second process's start recovery then probes once. Holding the probe and killing the process would leak a blocked placement task on the fake."
  - "The found branch runs on the fake and on Demo; the probe-error branch (recovery probe also fails) is twin-only (probe_error=True raises ValueError on a non-synthetic env)."
  - "The crash of cut (b) on the fake is cancelling the tick task that is blocked on the held stop placement; on Demo it is abandon() cancelling the scheduler. The held call is recorded in the edge ledger (mode hold) but never reaches the exchange; the twin checks the fake saw the stop once, from the second process."
  - "A second process that inherits SAFE_MODE is admitted but not enabled, which dr._bring_up rejects. start_tolerant runs the same start sequence, writes the same start_sequences record and still stops on a refused admission, a failed recovery step or a broken wiring."
  - "SAFE_MODE is durable on Demo, so cuts (a) and (b) end by cancelling the entry or closing the position and leaving SAFE_MODE through /safemode_exit and /confirm (RUNBOOK 21.1a), then account_clean."
  - "Cut (b) late restart (twin only, 60 s of virtual time against the twin's test max_unprotected_ms 7777) shows the D-13 close; it ends COMPLETE_WITH_GAPS because the operator exit is refused (finding F1)."
requirements-completed: [EXEC-01, EXEC-03]
status: complete
duration: 3h (interrupted once by a rate limit, resumed from the working tree)
completed: 2026-11-07
commits: 6
plan_head_before: 6620993e63c67c6011f9341742071489f9d896fe
plan_head_after: c6107178c92476132287bfccaf69219e5f9dbf4c
actuals:
  tokens: 16100
  tasks: 3
  commits: 6
---

# Phase 25 Plan 12: S07 restart mid-flow at three cuts Summary

One scenario module with a `cut` argument, a CI twin per cut and an owner-run Demo test per cut. A crash is `abandon()` plus `restart()` (a second process over the same stores and exchange). Cut (c): after the fill and confirmed stop the second process rehydrates the plan in the state it had, sends nothing and the first reconcile is clean. Cut (a): the entry POST reaches the exchange, its answer is lost and the process's own probe fails; the second process's start recovery probes once by client id and finds the entry (ACKED, tracked), one `place_entry` across both processes. Cut (b): the first stop placement is held and the process crashes with an open, unprotected position; the second process rebuilds the plan UNPROTECTED (entries blocked) and places the stop under the same deterministic algo id, REST-confirmed. Nothing under `src`, `scripts`, `pyproject.toml`, `uv.lock`, `harness.py`, `catalog.py` or `fault_edge.py` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): cut (c) restart after fill and stop | 8ba76501 | b6fb6639 |
| 2: cut (a) lost entry answer, probe once, never re-sent | d9fb9399 | 01163950 |
| 3: cut (b) crash between fill and stop | eb4f6918 | c6107178 |

RED means the twin and demo test were committed while the scenario symbol they use was absent (collection error confirmed before each commit).

## What each cut asserts

**Cut c**: clean start, start, `fill` request, stop REST-confirmed, take-profit legs awaited (best effort); the protection state before the crash is recorded; `abandon` and `restart`; `_bring_up` of the second process (admitted, enabled, plans restored 1); the restored plan has the same state and a confirmed stop; the exchange-edge counts of `place_entry`, `place_algo_protective`, `place_market_close` and both cancels are unchanged; `reconcile_tick_once` is clean; the position is closed through the production operator close, plan expired, `account_clean` PASSED. Negative control: a growing count fails the step. All steps carry the env label.

**Cut a** (found): `drop_response_after_send(place_entry, -1007)` and `raise_before_send(query_order_by_client)` armed; confirm; the intent is UNKNOWN, the edge shows one injected POST and one injected probe by the entry's client id, SAFE_MODE is ENTRY_STATE_UNKNOWN; crash; second process: admitted, in SAFE_MODE, entries not enabled, exactly one probe in the start sequence (by the entry id, not injected), recovery report resolves `[ENTRY, ACKED]` with nothing unresolved, the intent reads ACKED, the plan is tracked; after five settle ticks `place_entry` is 1 at the edge AND at the fake and the second process sent nothing; the entry is cancelled by its client id, SAFE_MODE is left through `/safemode_exit`, `account_clean` PASSED. Probe-error branch (twin): the recovery probe is injected to fail too, the report shows `[ENTRY, UNKNOWN]` unresolved and `safe_mode_entered`, SAFE_MODE stays, entries blocked, still one `place_entry`, resolved the same documented way. Labels: lost answer DEMO_FAULT_INJECTED, reaction steps env label.

**Cut b**: `hold(place_algo_protective)`, entry filled; the held stop is the only stop call at the edge (mode hold) and the state is UNPROTECTED with no confirmed stop; crash (held call cut, not surviving); second process: state UNPROTECTED, `blocks_new_entries()` True, in SAFE_MODE and not enabled; the coordinator places the stop (edge shows two calls under the same stop id: the held one and a real one), REST-confirmed, then the TP legs; one `place_entry` across both processes; operator close, `account_clean`, SAFE_MODE left through `/safemode_exit`. On the fake the exchange saw the stop exactly once (from the second process, 0 before the restart). Late variant (twin): after 60 virtual seconds the second process reaches CLOSE_REQUIRED, one reduce-only close, FLAT.

## REUSES

| Twin | REUSES |
|---|---|
| `tests/test_demo_twin_s07_restart_cuts.py` | `tests/test_live_restart_rehydrate.py::test_a_protected_plan_comes_back_protected_and_its_stop_is_not_placed_again`, `::test_an_entry_sent_with_an_unknown_result_stays_unknown_with_safe_mode`, `::test_a_fill_for_the_rebuilt_entry_reaches_the_coordinator_as_a_known_order`, `tests/test_intent_recovery_unknown_entry.py::test_a_found_order_becomes_acked_with_journaled_evidence`, `tests/test_live_stream_to_protection.py::test_a_fill_frame_at_the_transport_edge_ends_in_a_rest_confirmed_stop` |

A twin test checks every referenced test name exists in its file.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s07_restart_cuts.py tests/test_live_restart_rehydrate.py tests/test_demo_marker_guard.py -x -q`: passed. With `tests/test_demo_same_code_path.py`, `test_demo_harness.py`, `test_no_unratified_defaults.py`, `test_fault_edge.py` and `tests/demo`: all passed, one strict xfail (F1), 11 demo tests skipped (3 are S07, none passed); `TRADING_CI_STRICT=1` collection of `tests/demo` exits 0.
- Scoped `ruff check` and `ruff format --check` on the three files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock tests/support/demo_scenarios/harness.py tests/support/demo_scenarios/catalog.py tests/support/fault_edge.py` exits 0.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read.

## Deviations from Plan

**1. [Mechanism, inside latitude] Cut (a) also injects a failed in-process probe.** See key-decisions. The plan's key link names `drop_response_after_send("place_entry")`; that is used, plus `raise_before_send("query_order_by_client")`. Both are DEMO_FAULT_INJECTED on Demo.

**2. [Plan wording] The second process's SAFE_MODE reason in the probe-error branch is not ENTRY_STATE_UNKNOWN.** The first process enters ENTRY_STATE_UNKNOWN (asserted). After a failed recovery probe the second process's recovery report is `safe_mode_entered=True` and the standing reason becomes UNRESOLVED_EXECUTION_INTENT; the twin accepts either and records the observed one. In the same start sequence the reconcile loop's unknown-entry resolver then probes again, finds the order and the intent reads ACKED, but SAFE_MODE stays until the owner leaves it (D-15).

**3. [Scope choice] The found branch also asserts the entry is "tracked"**: the restored plan is in the coordinator (state AWAITING_FILL, reason REGISTERED_ENTRY_STATE_UNKNOWN even though recovery acked the intent; the coordinator keeps reading it by client id, never sending).

**4. [Added, twin only] `late_restart` variant of cut (b)**, to cover the plan's "or closes at its deadline" branch.

**5. [Shared helpers] S07 imports helpers from `s04_stop_rejected.py` and `s06_replay.py`** (catalog names only the three files).

## Findings

**F1 (behaviour gap, not fixed; no src change allowed here): after a restart later than `max_unprotected_ms` and the deadline close, the plan's STOP_LOSS intent stays UNKNOWN and `/safemode_exit` refuses (`UNKNOWN_INTENT_PRESENT`, `COMPARE_NOT_CLEAN`).** Sequence on the twin: the stop intent was SENT before the crash, recovery marks it UNKNOWN (F5: protective legs of a live plan are left for the coordinator rebuild), the second process places the stop and escalates to CLOSE_REQUIRED (B2_STOP_UNCONFIRMED) at once, the plan ends FLAT, but nothing resolves the intent. SAFE_MODE `CLOSE_REQUIRED` then cannot be left through the operator path (RUNBOOK 21.1a) without manual handling of the intent row. In the on-time restart the coordinator's stop placement resolves the intent to ACKED and the exit works. The twin records it (`stop_intent_after_close`, `safe_mode_exit_refusals`), ends COMPLETE_WITH_GAPS and holds a strict xfail `test_cut_b_a_late_restart_close_lets_the_operator_leave_safe_mode`. Whether `src` should resolve (or the exit tolerate) a stop intent of a FLAT plan is an owner decision with its own DECISIONS row.

**F2 (observation):** after a restart that inherits SAFE_MODE the process is admitted but entries stay disabled (HEALTH and ENABLE skipped, BLOCKED_SAFE_MODE); `dr._bring_up`, built for clean restarts, would reject it. Nothing to fix; the owner's Demo session for cuts (a) and (b) must expect SAFE_MODE after the restart and leave it through `/safemode_exit`.

No other twin exposed a defect in `src`.

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`, `TRADING_DEMO_RUN=1`); agents never connect to Demo:

- The three demo tests only collect and skip. That `abandon()` on the real process (scheduler task cancelled, stream stopped with the listenKey kept, polling stopped) leaves a second process able to start over the same PostgreSQL stores and Demo account is unobserved, as is the listenKey singleton behaviour (25-09's limit).
- Cut (a) on Demo: whether the real adapter's `error_facts` treats the injected `BadRequestError(-1007)` as ambiguous (the twin uses the same classifier on the same facts), whether the recovery probe on the real exchange finds the resting `far` entry (Demo visibility of a new order by client id is a documented unknown), and that the injected probe failure is consumed by the manager's own probe and not by another caller. The scenario checks the consumed probe call carries the entry's client id and fails otherwise.
- Cut (b) on Demo: the hold leaves a REAL open Demo position without a stop for the time between the crash and the second process's first protection pass; if the run stops early the owner closes the position in the Binance UI and runs `scripts/demo_clear.py`. The edge ledger of the real run is the only evidence that the held call never left the process; the fake-side "exchange saw one stop" check is twin-only.
- The probe-error branch and the late-restart variant are twin-only by design (the late restart uses the twin's test `max_unprotected_ms` of 7777 ms, the Demo limit is 180000 ms).
- SAFE_MODE durability across the restart on the real PostgreSQL safe-mode store and the real `/safemode_exit` token round trip.

## Known Stubs

None.

## Threat Flags

None. T-25-28 (cut a asserts one `place_entry` across both processes at the edge and the exchange, with a negative control, plus the D080 probe and UNKNOWN + SAFE_MODE path), T-25-29 (cut b asserts UNPROTECTED restore, entries blocked, the stop placed under the same id or the deadline close) and T-25-SC (no package added; `pyproject.toml` and `uv.lock` unchanged) hold.

## Self-Check: PASSED

The three created files exist; commits 8ba76501, b6fb6639, d9fb9399, 01163950, eb4f6918 and c6107178 are ancestors of HEAD; `git rev-list --count 6620993e..c6107178` is 6.
