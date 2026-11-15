---
phase: 25-demo-integration-test-campaign
plan: 15
subsystem: demo-scenarios
tags: [D-05, S14, S12, S13, safe-mode, daily-stop, margin-guard, liquidation-guard, tdd, OPS-01, EXEC-01]
requires: [25-02, 25-08, 25-09, 25-10, 25-11, 25-12, 25-13, 25-14]
provides:
  - "tests/support/demo_scenarios/s14_safe_mode.py: S14 run(env, recorder), journal_rows, intent_status, probe_calls, probe_interval_seconds"
  - "tests/support/demo_scenarios/s12_daily_stop.py: S12 run(env, recorder), persisted_day, daily_stop_alerts"
  - "tests/support/demo_scenarios/s13_margin_liquidation.py: S13 run(env, recorder), plan_values, needed_initial_margin, inside_the_stop_ratio"
  - "three CI twins (tests/test_demo_twin_s14_safe_mode.py, _s12_daily_stop.py, _s13_margin_liquidation.py) and three owner-run demo tests (tests/demo/test_demo_s14_..., _s12_..., _s13_...)"
affects: [25-17, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "an injected reading is armed at the adapter edge (FaultEdge.override / drop_response_after_send / raise_before_send); the guard's reaction is the real process's"
    - "an injected value is computed from the built plan, the loaded parameters and the account's real table, never typed in"
    - "a result that is not the expected one is recorded NOT_REHEARSED (env label) and pinned twice: observed, and a strict xfail for the desired behaviour"
key-files:
  created:
    - tests/support/demo_scenarios/s14_safe_mode.py
    - tests/support/demo_scenarios/s12_daily_stop.py
    - tests/support/demo_scenarios/s13_margin_liquidation.py
    - tests/test_demo_twin_s14_safe_mode.py
    - tests/test_demo_twin_s12_daily_stop.py
    - tests/test_demo_twin_s13_margin_liquidation.py
    - tests/demo/test_demo_s14_safe_mode.py
    - tests/demo/test_demo_s12_daily_stop.py
    - tests/demo/test_demo_s13_margin_liquidation.py
  modified: []
key-decisions:
  - "S14 cannot show 'a CONFIRM for a new request places nothing' while the entry is still UNKNOWN: the approval sender refuses any second card on a symbol with an unresolved entry intent (CONFLICT_WITH_OPEN_POSITION, sources ACTIVE_PLAN, UNRESOLVED_ENTRY_INTENT, RESTING_ENTRY_ORDER, PENDING_OR_APPROVED_APPROVAL). That refusal is recorded as the first fail-closed layer. The SAFE_MODE guard itself is shown after the reconcile resolver recorded the intent ACKED and the operator cancelled the resting entry: SAFE_MODE still stands, a new request gets a card and its CONFIRM is refused RECONCILIATION_REQUIRED with nothing sent."
  - "S14 resolves the unknown entry the way the running process does it: the reconcile resolver (UnknownEntryResolver) probes by client id at its own spacing (reconcile.entry_unknown_probe_interval_ms); with the probe fault cleared it finds the order and records ACKED. Closing an intent never exits SAFE_MODE (D-15), asserted. The probe fault is armed times=None because the resolver and the coordinator probe through the same edge."
  - "S14 health ticks: a HEALTH_VERDICT row id hashes its time, so two health ticks at one virtual instant collapse to one row. The scenario moves the clock (env.tick) between health ticks."
  - "S12 asks the day service to evaluate (LiveDayRiskService.evaluate, the call the placement makes at every CONFIRM) itself, because no scheduled task evaluates a day whose loss is already known; that step is labelled DEMO_FAULT_INJECTED (the trigger is scenario-made), the verdict and the persisted latch are the real service and store. The refusal at CONFIRM is the process's own path."
  - "S12 injects the loss through user_trades_in_window only (one BTCUSDT fill, 10 percent beyond the stop threshold, realized_pnl negative, Decimal). income_in_window is not overridden: the fold counts the fill, and overriding the income reader would mask the account's real funding rows on Demo."
  - "S12 refuses to start when the persisted day row is already latched (STEP precondition_day_not_latched, instruction in the detail): the stop holds until 00:00 UTC, so a second run the same day cannot reach its first request."
  - "S13 injects the available balance by replacing BOTH the account-level availableBalance and the USDT asset row of the real snapshot (read through env.faults.inner): the guard cross-checks the two and refuses UNCERTAIN_ACCOUNT_STATE on a mismatch, which would be a different refusal."
  - "S13 injects brackets only (not symbol_config_snapshot): one bracket whose maintenance ratio is solved from the closed form of src/risk/liquidation.py so that LP sits half way between the entry and the stop; floor, cap and initial leverage come from the real table."
  - "S13 order is margin refusal, normal placement, liquidation refusal: BracketCache keeps a reading for margin.max_bracket_age_ms (60 s), so the bad-bracket case goes last and waits that bound once; running it earlier would poison the next request for a minute."
requirements-completed: [OPS-01, EXEC-01]
status: complete
duration: about 3h (estimate; start time was not recorded)
completed: 2026-11-08
commits: 6
plan_head_before: a012efe9a565649fa5439c453e9953215afa0a0b
plan_head_after: 103e0753d1a0ae833d6829094429fc29a722915b
actuals:
  tokens: 17200
  tasks: 3
  commits: 6
---

# Phase 25 Plan 15: S14 SAFE_MODE, S12 DAILY_STOP, S13 margin and liquidation guards Summary

The three guard scenarios of the Demo campaign, each as a shared `run(env, recorder)`, a CI twin on the fake composed process and an owner-run demo test. S14 shows an unresolved entry putting the process in SAFE_MODE ENTRY_STATE_UNKNOWN, monitoring continuing, the operator exit refused while the cause stands and accepted after the reconcile resolved it. S12 shows loss rows beyond the daily stop (sized from the loaded rate and the persisted day base) latching DAILY_STOP and refusing the next CONFIRM. S13 shows a low available balance and a derived narrow liquidation distance refused by the margin and liquidation guards before anything is sent. The S12 twin exposed a real gap in `src` (finding F1, below), recorded and pinned with a strict xfail. Nothing under `src`, `scripts`, `params`, `pyproject.toml`, `uv.lock`, `harness.py`, `catalog.py` or `fault_edge.py` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): S14 SAFE_MODE entry and operator exit | 188fba2d | 21eb777a |
| 2: S12 DAILY_STOP | 2e632713 | bec5f5c5 |
| 3: S13 margin and liquidation guards | 8e057f84 | 103e0753 |

RED means the twin and demo test were committed while the scenario module was absent (a collection error, confirmed for S14; S12 and S13 hit the same import error). The S14 GREEN commit also carries two small twin edits made while writing the module (a renamed fact key and rewrapped docstring lines). The tracer gate (re-run `<verify>` end to end after the tracer commit) passed: S14 twin plus the marker guard green.

## What each scenario asserts

**S14** (`s14_safe_mode.run`): clean start, start. The entry POST reaches the exchange and its answer is dropped (`drop_response_after_send`, once); the probe by client id fails (`raise_before_send`, until cleared). The intent stays UNKNOWN, SAFE_MODE `ENTRY_STATE_UNKNOWN` is entered (journaled SAFE_MODE_ENTER reason), one `place_entry` at the edge. Monitoring: two further `RECONCILE_TICK` and two `HEALTH_VERDICT` rows are journaled while SAFE_MODE stands and the resolver's probes keep failing (4 more injected probe failures on the twin). A second request is refused by the sender before it gets a card. `/safemode_exit` plus `/confirm` is refused with `UNKNOWN_INTENT_PRESENT` (a new `SAFE_MODE_EXIT_REFUSED` row) and SAFE_MODE stays. The probe fault is cleared and the clock moves past the resolver's spacing: the resolver finds the order and records the intent ACKED; SAFE_MODE stays (standing reason then `UNRESOLVED_EXECUTION_INTENT`, observed). The operator cancels the resting entry by client id; a new request is approved and its CONFIRM is refused `RECONCILIATION_REQUIRED` with `place_entry` unchanged. `/safemode_exit` plus `/confirm <token>` leaves SAFE_MODE (exactly one `SAFE_MODE_EXIT` row, with the operator id); a new request is placed, acknowledged and cancelled; `account_clean`. Outcome COMPLETE. Negative control: without the lost answer the entry is ACKED and the run halts at the unknown step.

**S12** (`s12_daily_stop.run`): clean start, start; the persisted day row exists and is not latched (precondition). Baseline: the stop threshold is the loaded `daily_loss_stop_threshold` rate times the persisted day base (twin: 49.99 on 4999.09). A request is approved and confirmed (a GTD LIMIT rests). Injected: `user_trades_in_window` returns one loss fill of 1.1 times the threshold (54.99); the process's `day_risk_backfill` folds it (loss known equals the injected amount). The day service evaluates the day: `DAILY_STOP`, reason `DAILY_STOP_BLOCK`, latch persisted. The resting entry stays open (zero cancels, state AWAITING_FILL) and no `DAILY_STOP` alert is journaled (finding F1; step NOT_REHEARSED, outcome COMPLETE_WITH_GAPS). The operator cancels the entry; a new request gets a card and is APPROVED (the card and APPROVE are not blocked, observed) and its CONFIRM is refused `DAILY_STOP_BLOCK` with `place_entry` unchanged; `account_clean`. The docstrings of the module, the twin and the demo test say to run S12 LAST in an owner session because the stop holds for the UTC day (the catalog flag `leaves_state` is already True). Negative control: with no loss rows the run halts at the loss step. A day already latched halts at the precondition before anything is placed.

**S13** (`s13_margin_liquidation.run`): clean start, start. Margin: the plan's quantity and zone-mid entry over the target leverage give the initial margin needed (twin: 58.5 at 5x); the real account snapshot is read through the edge's inner adapter and its `available_balance` (account level and USDT row) is replaced by half of that (29.25); the CONFIRM is refused `INSUFFICIENT_MARGIN`, no `place_entry`, no `change_margin_type` or `change_initial_leverage`. With the override cleared a request is placed once, acknowledged and cancelled by its client id (here the configuration POSTs do go out, so the zero count in the refusals is not vacuous). After waiting `margin.max_bracket_age_ms`, the bracket table is replaced by one bracket whose maintenance ratio (twin: 0.18145685) is solved so the computed liquidation price (47645.625) lies half way between the entry (48750) and the stop (46541.25); the CONFIRM is refused `LIQUIDATION_TOO_CLOSE`, nothing sent. `account_clean`. Outcome COMPLETE. Negative control: with no override the request is placed and the margin-refusal step fails.

## REUSES per twin

| Twin | REUSES |
|---|---|
| `tests/test_demo_twin_s14_safe_mode.py` | `tests/test_live_safe_mode_drill.py::test_the_drill_enter_blocked_refused_exit_operator_exit_entry_allowed`, `::test_each_failing_exit_row_keeps_safe_mode_and_is_named`, `tests/test_safe_mode_exit_operator.py::test_operator_exit_checks_journals_persists_then_flips`, `tests/test_intent_recovery_unknown_entry.py::test_a_found_order_becomes_acked_with_journaled_evidence`, `tests/test_demo_twin_s07_restart_cuts.py::test_cut_a_the_first_process_ends_unknown_with_safe_mode` |
| `tests/test_demo_twin_s12_daily_stop.py` | `tests/test_daily_stop.py::test_latched_daily_stop_cancels_the_entry_keeps_the_stop_and_alerts_after`, `tests/test_day_risk_service.py::test_a_derived_stop_is_latched_in_the_store_before_the_verdict_returns`, `::test_a_restart_inside_the_day_keeps_the_stored_base_and_the_latch`, `tests/test_day_risk_stream.py::test_an_invalidation_makes_the_loss_unknown_until_the_next_backfill`, `tests/test_demo_twin_s11_db_outage.py::test_the_close_goes_out_once_reduce_only_while_the_journal_is_down` |
| `tests/test_demo_twin_s13_margin_liquidation.py` | `tests/test_margin_guard.py::test_recorded_crossed_x20_account_flows_through_every_check_to_one_pass`, `::test_every_refusal_has_its_exact_plain_code_and_touches_nothing_later`, `::test_a_plan_refused_by_a_pure_check_leaves_the_recorded_account_untouched`, `tests/test_margin_check.py::test_recorded_demo_shape_initial_margin`, `tests/test_live_liquidation_and_tp.py::test_a_failed_check_judges_close_for_a_liquidation_price_at_the_stop` |

Each twin has a test that checks every referenced test name exists in its file; the plan's REUSES AST one-liner exits 0 (checked for S12). The plan's read-first names `tests/test_daily_loss.py`, `tests/test_liquidation_watch.py` and `tests/test_live_safe_mode_drill.py` (partly) were replaced by the closer tests above; `test_daily_loss.py` and `test_liquidation_watch.py` are pure-rule suites with no composed behaviour to build on.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s14_safe_mode.py tests/test_demo_twin_s12_daily_stop.py tests/test_demo_twin_s13_margin_liquidation.py tests/test_demo_marker_guard.py tests/demo tests/test_demo_harness.py tests/test_demo_same_code_path.py tests/test_demo_env_factory.py tests/test_no_unratified_defaults.py tests/test_agents_md.py`: 290 passed, 20 skipped (all 20 are tests under `tests/demo`, none passed), 1 xfailed (finding F1, strict). Twins: S14 13 tests, S12 13 (12 pass, 1 xfail), S13 9. `TRADING_CI_STRICT=1` collection of `tests/demo` exits 0 with every test skipped.
- Scoped `ruff check` and `ruff format --check` on the nine files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts params pyproject.toml uv.lock tests/support/demo_scenarios/harness.py tests/support/demo_scenarios/catalog.py tests/support/fault_edge.py` exits 0.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read, no soak. The nine new files are LF.

## Deviations from Plan

**1. [Plan wording] S14: "while in SAFE_MODE a CONFIRM for a new request places nothing" is shown after the entry is reconciled, not while it is UNKNOWN.** A second card cannot be issued on the symbol while its entry intent is unresolved (key-decisions). During UNKNOWN the scenario records the refusal of the second request (the sender's symbol rule). The CONFIRM refusal by SAFE_MODE is shown with the intent ACKED, the resting entry cancelled and SAFE_MODE still on.

**2. [Plan wording] S14: "once the entry is reconciled" means the reconcile resolver recorded the intent ACKED**, not that the process left SAFE_MODE; the operator exit is accepted only after the operator also cancelled the resting entry (compare row, plan state). The standing SAFE_MODE reason changes from `ENTRY_STATE_UNKNOWN` to `UNRESOLVED_EXECUTION_INTENT` after the first resolver tick; the scenario takes the entry reason from the journaled SAFE_MODE_ENTER rows, not from the controller's current reason.

**3. [Plan wording] S12 overrides `user_trades_in_window` only, not `income_in_window`** (key-decisions).

**4. [Plan wording] S12 "resting entries are handled as the code defines" resolved as: not handled at all** (finding F1). The step is NOT_REHEARSED with the observed facts; the desired behaviour is a strict xfail.

**5. [Mechanism, inside latitude] S12 calls the day service's `evaluate` itself** and labels that step DEMO_FAULT_INJECTED; nothing evaluates a known-loss day between CONFIRMs.

**6. [Plan wording] S13 injects brackets, not symbol-config values**, and runs the margin case first, then the normal request, then the liquidation case (key-decisions). The plan's order ("overrides cleared, request placed") is kept per request: the normal request runs with no override armed.

**7. [Shared helpers] The scenarios import helpers from `s04_stop_rejected.py`, `s06_replay.py`, `s07_restart_cuts.py` and `s08_stream_loss.py`.** The catalog names only the nine files of the plan.

## Findings

**F1 (behaviour gap in `src`, not fixed; no src change allowed here): `enforce_daily_state` is not called by any live composition.** `src/execution/daily_stop.py` implements D033 and D-12 (cancel every resting entry of a placed plan through `expire_pending_entry("daily_stop")`, keep the stops, alert DAILY_STOP) and is unit-tested (`tests/test_daily_stop.py`), but `git grep` over `src` finds no caller outside the module (the Phase 21 and Phase 24 notes say "not wired until Phase 24"; plan 24-13 wired the alert sink but the only call of `enforce_daily_state` is in a test, `tests/test_live_alerts_wiring.py`). On the real composed process, after the day is latched DAILY_STOP: the persisted latch and the `DAILY_STOP_BLOCK` refusal of new entries work; the resting entry stays on the exchange (zero `cancel_normal_order` at the edge, protection state AWAITING_FILL) and no `DAILY_STOP` alert is journaled. Entries are blocked either way; what is missing is the cancel of an entry that was already resting and the operator alert. Held by the observation test `test_finding_f1_a_resting_entry_is_not_cancelled_and_no_alert_is_journaled` and the strict xfail `test_a_resting_entry_is_cancelled_at_daily_stop_and_the_alert_is_journaled`. The fix belongs to the owner: a scheduler task (or the day-risk task) that calls `enforce_daily_state` with the verdict and the placed plans from the reservation rows, with its own DECISIONS row.

**F2 (observation): the card and the APPROVE are not blocked by DAILY_STOP.** With the day latched, a new request still gets a card and its APPROVE succeeds (the reservation at APPROVE accepts it); only the CONFIRM is refused `DAILY_STOP_BLOCK`. This is consistent with D033 (the gate is at placement) but means the owner is shown a card it cannot place.

**F3 (observation): while an entry intent is unresolved, the approval sender refuses any second request on the symbol** (`CONFLICT_WITH_OPEN_POSITION`, four sources). So the only SAFE_MODE-time CONFIRM refusal that can be shown is after the intent is resolved. Not a defect.

**F4 (observation): closing an UNKNOWN intent through the reconcile resolver changes the standing SAFE_MODE reason** to `UNRESOLVED_EXECUTION_INTENT` (the resolver re-enters SAFE_MODE with that reason on each tick that keeps an intent). The journal keeps the original `ENTRY_STATE_UNKNOWN` row. An alert or status text that reads only the controller's current reason would no longer say ENTRY_STATE_UNKNOWN after the first reconcile tick.

**F5 (twin fidelity): the twin day base and amounts are the recorded Demo account's (equity 4999.09343961), so figures such as the 49.99 stop threshold are twin values; on Demo the process persists the account's real day base.** Nothing here is a mainnet figure.

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`, `TRADING_DEMO_RUN=1`); agents never connect to Demo:

- The three demo tests only collect and skip. That `FaultEdge.override` / `drop_response_after_send` / `raise_before_send` behave the same through the real adapter on Demo, and that the real PostgreSQL stores (journal, day risk, execution state) serve the same reads as the in-memory twin stores, are unobserved.
- S14 on Demo: the dropped entry answer leaves a real GTD LIMIT on Demo; the reconcile resolver's probe interval and the scheduler cadence run concurrently with the scenario's waits (counts of reconcile and health rows are polled, not exact); the Programmatic or Console owner's `/safemode_exit` token flow against real Telegram; the durable SAFE_MODE exit on PostgreSQL; the real sender's symbol rule with the real Demo open-order reads.
- S12 on Demo: the backfill reading the injected fill through the real adapter's `user_trades_in_window`; the day base the real Demo account persists; the injected rows stay among the day's loss components in the Demo database; the latch holds until 00:00 UTC, so after S12 no other scenario can place that day (run it last). No real Demo loss is made.
- S13 on Demo: the real snapshot read through `faults.inner`, the real bracket table's floor, cap and initial leverage, the 60 s real wait for the bracket cache, and that no real `change_margin_type` or `change_initial_leverage` reaches Demo in the two refusals. The exchange-side -2019 is the owner probe case `insufficient_margin_order` (Demo-observed 2026-10-24), not this test. The symbol-configuration injection (`symbol_config_snapshot`) is not exercised.
- Not covered by any test: that a Demo account with a position open on another symbol would change the day exposure flag the S12 evaluate call passes (it passes `exposure=True` because the resting entry counts).

## Known Stubs

None.

## Threat Flags

None. T-25-37 (S14 asserts the second request is refused, the CONFIRM is refused in SAFE_MODE with `place_entry` unchanged, and the exit goes only through the operator two-step; S12 asserts the CONFIRM refusal under DAILY_STOP with nothing sent), T-25-38 (S12 documents `leaves_state` and the run-last rule, and refuses to start on an already latched day) and T-25-SC (no package added; `pyproject.toml` and `uv.lock` unchanged) hold.

## Self-Check: PASSED

The nine created files exist; commits 188fba2d, 21eb777a, 2e632713, bec5f5c5, 8e057f84 and 103e0753 are ancestors of HEAD; `git rev-list --count a012efe9..103e0753` is 6.
