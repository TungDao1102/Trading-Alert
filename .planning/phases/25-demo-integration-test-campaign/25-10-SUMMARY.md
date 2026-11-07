---
phase: 25-demo-integration-test-campaign
plan: 10
subsystem: demo-scenarios
tags: [D-04, D-05, S06, S02, S05, replay, concurrent-confirm, partial-fill, cancel-race, tdd, EXEC-03, APRV-02, EXEC-01]
requires: [25-02, 25-08, 25-09]
provides:
  - "tests/support/demo_scenarios/s06_replay.py: S06 run(env, recorder) plus shared helpers place_approved_entry, close_and_clean, cancel_resting_entry, placement_outcomes, place_entry_calls, shutdown, start_evidence"
  - "tests/support/demo_scenarios/s02_partial_fill.py: S02 run(env, recorder, *, partial_fill=None)"
  - "tests/support/demo_scenarios/s05_cancel_race.py: S05 run(env, recorder), crossed(), record_race_step()"
  - "three CI twins (tests/test_demo_twin_s06_replay.py, _s02_partial_fill.py, _s05_cancel_race.py) and three owner-run demo tests (tests/demo/test_demo_s06_replay.py, _s02_..., _s05_...)"
affects: [25-17, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "an event that did not happen is labelled NOT_OBSERVED, never DEMO_OBSERVED (T-25-25)"
    - "deterministic fake races through FaultEdge hold/release; Demo takes the natural branch with nothing held"
    - "exchange POSTs counted at the FaultEdge (records every adapter call), env-agnostic"
key-files:
  created:
    - tests/support/demo_scenarios/s06_replay.py
    - tests/support/demo_scenarios/s02_partial_fill.py
    - tests/support/demo_scenarios/s05_cancel_race.py
    - tests/test_demo_twin_s06_replay.py
    - tests/test_demo_twin_s02_partial_fill.py
    - tests/test_demo_twin_s05_cancel_race.py
    - tests/demo/test_demo_s06_replay.py
    - tests/demo/test_demo_s02_partial_fill.py
    - tests/demo/test_demo_s05_cancel_race.py
  modified: []
key-decisions:
  - "The plan says a 'rest' request; the injector's scenarios are `far` (rests, never fills) and `fill` (marketable). S06 uses `far`, S02 and S05 use `fill`."
  - "S06 proves the two concurrent CONFIRM presses and the replays on ONE plan (approve, two concurrent CONFIRM, replay APPROVE, replay CONFIRM) instead of a second request: while the first plan's entry rests, a second request on the symbol is refused at the card (ACTIVE_PLAN / PENDING_OR_APPROVED_APPROVAL), so a second request would need a cancel-and-expire dance and a second Demo order for no extra proof. The one-time-token consume rule is the same."
  - "The exchange POST count is read at the FaultEdge (`env.faults.calls_to('place_entry')`), which the fake env and the Demo env both install, so S06 and S05 assert the same number on both."
  - "S06 cleans up with `expire_pending_entry(trigger_reason='operator_close')` (by client id, verified by a query) and the APPROVED -> EXPIRED plan transition (the smoke drill's and demo_clear's step); waiting for the 10 minute plan expiry on Demo is avoided."
  - "S02: on the fake the first stop placement is held at the exchange for one look so the window 'stop sent, not yet REST-confirmed' is observable (the composed protection pass otherwise runs placement, REST confirmation and the TP step in one pass). On Demo nothing is delayed (a hold would create real unprotected exposure); the step is NOT_OBSERVED there."
  - "S02 checks what the coordinator really does: the stop is a closePosition STOP_MARKET (no quantity), the unfilled remainder is cancelled at the first fill (D-12), TP1 carries an explicit quantity sized from the REST position and TP2 is a closePosition leg. The plan text 'filling the remainder keeps the position protected' does not describe V1: the remainder is cancelled, never filled."
  - "S05 sends the cancel with `expire_pending_entry(trigger_reason='expiry_time')`, the call `scheduled_cancel` makes, at a chosen instant. The scheduled task body itself racing a fill is covered by an extra twin test (plan expiry passed, cancel held, fill lands)."
  - "S05 on Demo holds nothing (a delayed send is not the natural race): the race step is DEMO_OBSERVED only when the entry was NEW before the cancel and the post-cancel verdict is FILLED_OR_PARTIAL; otherwise NOT_OBSERVED with the observed order of events. The plan text allowed hold/release on Demo; it would label an injected delay as an observation."
requirements-completed: [EXEC-03, APRV-02, EXEC-01]
status: complete
duration: 100min
completed: 2026-11-07
commits: 7
plan_head_before: 013af3ef4cb274893d404f5adc3a916ae7e5e576
plan_head_after: bc3aa4436bc069c8d7d6a76983a9b37d5f8ae2dc
actuals:
  tokens: 17200
  tasks: 3
  commits: 7
---

# Phase 25 Plan 10: S06 replay, S02 partial fill, S05 cancel race Summary

Three more scenarios of the Demo campaign, each as a shared `run(env, recorder)`, a CI twin on the fake composed process and an owner-run demo test. S06 proves one `place_entry` and one non-refused outcome under two concurrent CONFIRM presses plus replayed APPROVE and CONFIRM; S02 proves the stop follows the first (partial) fill and is REST-confirmed before any new entry can open; S05 proves a cancel racing a fill ends with the fill protected, the cancel answered "already filled", no orphan and no second entry. Nothing under `src`, `scripts`, `pyproject.toml`, `uv.lock`, `harness.py` or `catalog.py` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): S06 replayed and concurrent presses | 3e285f1d | 405a5946 |
| 2: S02 partial fill | d1afd4f2 | 1b215211 |
| (refactor: shared close, expire and clean tail) | | 5b866f73 |
| 3: S05 cancel racing a fill | 45acdeb1 | bc3aa443 |

RED means the twin and demo test were committed while the scenario module was absent (collection error confirmed before each commit).

## What each scenario asserts

**S06** (`s06_replay.run`): clean start, start, `far` request, card, APPROVE, two CONFIRM presses through `env.owner.act` under `asyncio.gather` (distinct query ids), entry ACKED, exactly one `place_entry` at the fault edge; replay APPROVE and CONFIRM and five settle ticks: still one `place_entry` and one resting order; exactly one `LIVE_PLACEMENT_OUTCOME` for the plan's approvals, `is_no_trade` false; the entry is cancelled by client id (verdict CANCELED), the plan expires, `account_clean` PASSED. Negative control: a second counted POST fails the step with `SmokeHalt`.

**S02** (`s02_partial_fill.run(env, recorder, *, partial_fill=None)`): twin hook scripts the first fill (`fake.fill(quantity=)` plus the matching ORDER_TRADE_UPDATE through `rig.route`); the stop placement is held, `blocks_new_entries()` is True and the stop is unconfirmed while it is in flight; then one stop placed (closePosition STOP_MARKET), REST-confirmed; entry ends CANCELED with executed quantity equal to the scripted partial; TP1 explicit quantity below the position, TP2 closePosition; no algo quantity above the approved one; operator close, plan expired, `account_clean` PASSED. A first fill too small for TP1 (0.003 of 0.006, NOTIONAL_REJECT) keeps the stop and reports the TP step as a gap (TP_UNAVAILABLE). Without a hook (Demo, or the fake with a full fill) the partial step is NOT_REHEARSED (NOT_OBSERVED on Demo) and the outcome is COMPLETE_WITH_GAPS.

**S05** (`s05_cancel_race.run`): `fill` request acknowledged; entry read NEW; the cancel is held at the exchange (fake only), the entry fills while it is held, the cancel is released and the post-cancel verdict is FILLED_OR_PARTIAL; the journal holds the `cancel_unverified` audit with that verdict and no false `post_cancel`; the stop is REST-confirmed, state is not CLOSE_REQUIRED, position within the approved quantity, no resting order, no algo order outside the plan's own ids, one `place_entry`; operator close and `account_clean`. The cancel-wins branch (nothing fills) ends the plan cancelled and expired with COMPLETE_WITH_GAPS. `crossed(pre_status, verdict)` and `record_race_step` are unit-tested for the Demo labels.

## REUSES per twin

| Twin | REUSES |
|---|---|
| `tests/test_demo_twin_s06_replay.py` | `tests/test_live_replay_restart.py::test_two_concurrent_confirm_presses_lead_to_exactly_one_place_entry`, `::test_a_replayed_confirm_places_exactly_one_entry_with_the_derived_client_id`, `::test_a_replayed_approve_keeps_one_decision_and_places_nothing` |
| `tests/test_demo_twin_s02_partial_fill.py` | `tests/test_protection_branches.py::test_branch_b1_slow_entry_cancel_keeps_the_stop_then_closes_at_its_own_deadline`, `tests/test_protection_take_profits.py::test_tp_a_partially_closed_position_keeps_the_complete_state`, `tests/test_live_scheduled_cancel.py::test_a_partly_filled_entry_is_not_cancelled_and_is_journaled` |
| `tests/test_demo_twin_s05_cancel_race.py` | `tests/test_live_scheduled_cancel.py::test_an_unfilled_entry_past_its_plan_expiry_is_cancelled_by_its_client_id`, `::test_a_fully_filled_entry_is_left_to_the_coordinator`, `tests/test_protection_cancel_lag.py::test_a_lagging_by_id_query_after_the_cancel_is_a_success` |

Each twin has a test that checks every referenced test name exists in its file.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s06_replay.py tests/test_demo_twin_s02_partial_fill.py tests/test_demo_twin_s05_cancel_race.py tests/test_demo_marker_guard.py -x -q`: all passed. With `tests/test_demo_same_code_path.py`, `tests/test_demo_twin_s01_happy.py` and `tests/demo`: all passed, 5 demo tests reported skipped (none passed); `TRADING_CI_STRICT=1` collection of `tests/demo` exits 0 with all skipped. Also green: `tests/test_demo_harness.py`, `tests/test_demo_env_factory.py`, `tests/test_no_unratified_defaults.py`.
- Scoped `ruff check` and `ruff format --check` on the nine files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock tests/support/demo_scenarios/harness.py tests/support/demo_scenarios/catalog.py` exits 0. The REUSES AST one-liner exits 0 for all three twins.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read.

## Deviations from Plan

**1. [Plan wording, inside latitude] `rest` is `far`.** The injector has `far` and `fill`; there is no `rest`. No code consequence.

**2. [Scope choice] S06 uses one plan, not a second request.** See key-decisions. The truth in must_haves ("two concurrent CONFIRM presses for one plan") is met exactly; the plan's behavior bullet described a second request.

**3. [Rule 1 on the plan text, no code change] S02 "filling the remainder keeps the position protected" is not what V1 does.** The coordinator cancels the unfilled remainder at the first fill (D-12), so there is no remainder fill to observe; the scenario asserts the cancel and the position staying what filled. A late remainder fill is the S05 race, covered there.

**4. [Scope choice] S05 on Demo does not hold the cancel.** See key-decisions.

**5. [Shared helpers] `s02` and `s05` import helpers from `s06_replay.py`.** The catalog names only the nine files, so the common prologue and tail live in the first file of the plan. Only this plan's files depend on them.

## Findings

None. No twin exposed a defect in `src`; no xfail was needed. Observations that are behavior of the existing design, not defects: a first fill too small for TP1 (position 0.003 at the fake prices) ends TP_UNAVAILABLE with the stop kept and SAFE_MODE `ENTRY_WITHOUT_PROTECTIVE` (documented in `src/execution/protection.py`); the composed protection pass runs stop placement, REST confirmation and the TP step in one pass (the unit-level two-pass description applies to `ProtectionRig` only).

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`, `TRADING_DEMO_RUN=1`); agents never connect to Demo:

- All three demo tests only collect and skip. That two concurrent CONFIRM presses through the real PTB runner handler on Demo produce one POST, and that the replay answers come from the stored decision on the real PostgreSQL stores, is unobserved (S06).
- The S06 cleanup on Demo (`expire_pending_entry` with trigger `operator_close`, then the APPROVED to EXPIRED transition through the real executor) and the real `PgJournalStore.list_by_correlation` read of the placement outcome (an assumption: the in-memory store has the same method name and signature) first run on Demo.
- S02 on Demo: whether Binance ever produces a partial fill is unknown (A10); the expected result is `partial_fill` NOT_OBSERVED, `blocks_new_entries_while_unprotected` NOT_OBSERVED (the window is only stepped on the fake) and outcome COMPLETE_WITH_GAPS. The twin is the proof of the partial-fill branch. Partial detection on Demo reads the entry's executed quantity at the first moment the coordinator leaves AWAITING_FILL; a REST read that arrives after the full fill reports not partial.
- S05 on Demo: with a marketable `fill` entry the fill most likely lands before the cancel starts, giving `crossed` False, race step NOT_OBSERVED and a COMPLETE_WITH_GAPS outcome. A genuine crossing is luck. The deterministic proof is the twin; `scripts/demo_probe.py` `entry_cancel_fill_race` (P7) stays the probe-level attempt.
- The real `scheduled_cancel` task body is exercised on the fake only (extra twin test); on Demo S05 calls `expire_pending_entry` directly rather than waiting for the plan expiry.
- `env.deliver_fill` is the only fill hook S05 uses; the S02 partial hook lives in the twin (`make_partial_fill`) and needs the fake's `rig` and `day_reader`.

## Known Stubs

None.

## Threat Flags

None. T-25-24 (S06 asserts one `place_entry` under replay and concurrency at the fault edge and one non-refused outcome row, with a negative control), T-25-25 (S02 and S05 label an unhappened partial fill or missed race NOT_OBSERVED, unit-tested on a non-synthetic stub env) and T-25-SC (no package added; `pyproject.toml` and `uv.lock` unchanged) hold.

## Self-Check: PASSED

All nine created files exist; commits 3e285f1d, 405a5946, d1afd4f2, 1b215211, 5b866f73, 45acdeb1 and bc3aa443 are ancestors of HEAD; `git rev-list --count 013af3ef..bc3aa443` is 7.
