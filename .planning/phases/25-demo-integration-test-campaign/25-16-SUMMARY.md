---
phase: 25-demo-integration-test-campaign
plan: 16
subsystem: demo-scenarios
tags: [D-05, S15, S16, reconcile, foreign-order, doubled-position, manual-close, G2-016, G4-035, tdd, EXEC-02, OPS-01]
requires: [25-02, 25-08, 25-09, 25-10, 25-11, 25-12, 25-13, 25-14, 25-15]
provides:
  - "tests/support/demo_scenarios/s15_foreign_order.py: S15 run(env, recorder), actor_client_id, ACTOR_ID_PREFIX, actor_sizing, ActorSizing, record_actor_step"
  - "tests/support/demo_scenarios/s16_manual_close.py: S16 run(env, recorder, *, legs), actor_client_id, record_actor_step, record_leg_status_step, end_close_position_legs"
  - "two CI twins (tests/test_demo_twin_s15_foreign_order.py, tests/test_demo_twin_s16_manual_close.py) and two owner-run demo tests (tests/demo/test_demo_s15_foreign_order.py, tests/demo/test_demo_s16_manual_close.py)"
affects: [25-17, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "a test actor makes real account actions outside the system process: client ids that no system id family can match (t25a-), sizes from the loaded filters, calls on env.faults.inner so the edge ledger keeps counting only what the system sends"
    - "nothing is injected: the actor steps and the reactions carry the env label, a twin-only mechanism is its own SYNTHETIC step"
    - "a scenario that leaves_state names scripts/demo_clear.py in the failed step and in details['leaves_state']"
key-files:
  created:
    - tests/support/demo_scenarios/s15_foreign_order.py
    - tests/support/demo_scenarios/s16_manual_close.py
    - tests/test_demo_twin_s15_foreign_order.py
    - tests/test_demo_twin_s16_manual_close.py
    - tests/demo/test_demo_s15_foreign_order.py
    - tests/demo/test_demo_s16_manual_close.py
  modified: []
key-decisions:
  - "The actor calls env.faults.inner (the adapter the FaultEdge wraps), not env.assembly.exchange.adapter. A call through the edge would land in the edge ledger and mix the actor's orders with the system's (place_entry counts, the close count of S16). The actor keeps its own list of actions in details['actor']; the twin tests assert no actor id ever appears in an edge call."
  - "Actor client ids are t25a-<role>-<epoch>-<n> (at most 36 characters, Binance charset). The system id families are x-, xa-, xc- (src/execution/order_ids.py), so is_system_client_id is False and the compare reports FOREIGN_ORDER, never UNTRACKED_SYSTEM_ORDER. Each id is written to the evidence (record_ids) so the owner can find it in the Demo UI."
  - "actor_sizing takes the exchange filters (price tick, step, min quantity, min notional, PERCENT_PRICE band) and the mark: prices half way into the band on either side of the mark (the injector's own FAR_BAND_FRACTION), quantity = smallest multiple of the step that reaches min notional at the LOWER price. Twin: 0.003 at 48750.00 and 51250.00 (mark 50000). A test proves other filters give other numbers."
  - "S15 runs the doubled-position flow first, then the foreign-order flow. The twin's shared deliver_fill (tests/support/live_smoke_env.py, not editable here) unpacks exactly one place_entry from the fake's own ledger; the actor's order goes to that ledger too, so it must come after the system's fill. The order does not matter on Demo."
  - "S15 foreign flow: a new request gets NO CARD (the sender refuses it, source RESTING_ENTRY_ORDER), so 'a CONFIRM places nothing' is shown one layer earlier than the plan wording: no CONFIRM can exist. The SAFE_MODE guard on CONFIRM itself is S14's step."
  - "S15 adds, beyond the plan text, three steps the code makes cheap and valuable: the operator exit is refused (COMPARE_NOT_CLEAN, journaled, SAFE_MODE stays) while the divergence stands; a clean tick after the actor's clean-up leaves SAFE_MODE on (the loop never exits it, D-15); entries are shown restored (card again after the foreign flow, a request placed and cancelled after the doubled flow)."
  - "S15 doubled flow detail: the actor adds the smallest valid quantity in the system position's own direction (read from the position, not assumed); the actor's reduce-only close is exactly its own quantity; the system position is then exited by the production operator close (close_and_clean), SAFE_MODE by the operator exit."
  - "S16 twin models A3 (labelled): the fake ends the closePosition legs (stop and TP2) EXPIRED right after the actor's close, with no tick in between, as the Demo record of 2026-10-22 says. That record covers closePosition legs only; the explicit-quantity TP1 is left open and the system's own sweep ends it (CANCELED, one cancel). legs='stay' ends nothing (the orphan branch of G4-035). A Demo env refuses the twin-only variant (ValueError); on Demo the final status of each leg is read from the exchange and recorded verbatim (ABSENT when the id is no longer listed)."
  - "S16 asserts the system sent no close of its own (edge ledger place_market_close empty, only the actor's close exists) and that no protective leg of the symbol is open after the close and the reconcile (T-25-40, a failed step names scripts/demo_clear.py). A tick with a divergence after the close would be recorded NOT_REHEARSED with the env label and the outcome COMPLETE_WITH_GAPS (SAFE_MODE then left by the operator exit), never hidden."
  - "S16 'a new request afterwards' records what the code does: the closed plan's APPROVED approval holds the symbol until its expiry, so the new request is refused (reason CONFLICT_WITH_OPEN_POSITION, source PENDING_OR_APPROVED_APPROVAL, finding F1). The operator step APPROVED -> EXPIRED (the one scripts/demo_clear.py makes) ends it, then a request is placed and cancelled."
requirements-completed: [EXEC-02, OPS-01]
status: complete
duration: about 2h (estimate; start time was not recorded)
completed: 2026-11-08
commits: 4
plan_head_before: 1b913726ca1e3082819ccadaa7e40195d0bf963c
plan_head_after: d2cbfc8882bc723969f54968826ad67a0f461dd2
actuals:
  tokens: 22400
  tasks: 2
  commits: 4
---

# Phase 25 Plan 16: S15 foreign order and doubled position, S16 manual close Summary

The two reconcile-truth scenarios of the Demo campaign, each as a shared `run(env, recorder)`, a CI twin on the fake composed process and an owner-run demo test. A test actor makes real account actions outside the system: S15 shows a resting order with an actor id reported as FOREIGN_ORDER and an extra position on top of a protected system position reported as DOUBLED_POSITION, each entering SAFE_MODE with an alert while the system touches nothing; S16 shows a reduce-only close made outside the system ending flat with no divergence, no SAFE_MODE, no close of the system's own and no orphan leg. Both twins passed on the first full run against the real reconcile loop and coordinator; no `src` defect was found (see Findings for four observations). Nothing under `src`, `scripts`, `params`, `pyproject.toml`, `uv.lock`, `harness.py`, `catalog.py` or `fault_edge.py` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): S15 foreign order and doubled position | f4343d2a | 578ba5e8 |
| 2: S16 manual close outside the system | c9dfea22 | d2cbfc88 |

RED means the twin and demo test were committed while the scenario module was absent (a collection error, confirmed for S15 and S16). The S15 GREEN commit also carries small twin edits made while writing the module (the flow order, two scoped assertions). The tracer gate (re-run `<verify>` end to end after the tracer commit) passed: S15 twin plus the marker guard, 36 passed.

## What each scenario asserts

**S15** (`s15_foreign_order.run`): clean start, start. *Flow 1, doubled position:* a `fill` request is placed, filled and protected (state COMPLETE) and the last reconcile tick has no divergence (twin position 0.006). The actor adds the smallest valid BUY (0.003, id `t25a-add-...`); the position is 0.009. The next tick journals `DOUBLED_POSITION`, enters SAFE_MODE `DOUBLED_POSITION` (journaled enter reason), sends the alert (event DIVERGENCE, reason DOUBLED_POSITION) and tells the coordinator once (delegated 1, D-07); the system sends no close, no second entry, keeps the stop open and the plan in COMPLETE. `/safemode_exit` plus `/confirm` is refused `COMPARE_NOT_CLEAN` (one `SAFE_MODE_EXIT_REFUSED` row), SAFE_MODE stays. The actor reduces its own 0.003 with a reduce-only MARKET close; the next tick is clean and SAFE_MODE still stands. The system position is exited by the production operator close, `account_clean`, `/safemode_exit` plus `/confirm` leaves SAFE_MODE (one `SAFE_MODE_EXIT` row with the operator), and a new request is placed and cancelled. *Flow 2, foreign order:* the actor places one far resting BUY LIMIT (0.003 at 48750.00, id `t25a-rest-...`). The next tick journals `FOREIGN_ORDER`, enters SAFE_MODE `FOREIGN_ORDER` and alerts (event FOREIGN_ORDER); after further ticks the order still rests and the system sent no cancel naming it (ALERT_ONLY, D-02). A new request gets no card: `DEMO_APPROVAL_REQUEST_REFUSED` with source `RESTING_ENTRY_ORDER`, no `place_entry`. The exit is refused `COMPARE_NOT_CLEAN`. The actor cancels its own order by its own id; a clean tick follows with SAFE_MODE still on; the operator exit leaves it; a new request gets its card and APPROVE and its plan is expired; `account_clean`. Outcome COMPLETE. The edge ledger holds exactly the two system entries (the fill and the restored request); the actor's calls are in `details['actor']['actions']` (add, reduce, rest, cancel).

**S16** (`s16_manual_close.run`): clean start, start, a `fill` request placed and protected (stop, TP1 and TP2 open, twin position 0.006). The actor closes the whole position (reduce-only MARKET SELL 0.006, id `t25a-close-...`). Twin only, labelled SYNTHETIC: the closePosition legs (stop, TP2) end EXPIRED. The coordinator moves the plan to FLAT (reason POSITION_CLOSED, evidence REST_FLAT_TWO_READS_ENTRY_TERMINAL) and the edge ledger holds no `place_market_close`. Two reconcile ticks follow, none with a divergence, SAFE_MODE not entered. No protective leg of the symbol is open; the legs' final status is recorded verbatim: STOP_LOSS=EXPIRED, TAKE_PROFIT_1=CANCELED, TAKE_PROFIT_2=EXPIRED, one system cancel call each (the system's own sweep sends the cancel for every leg; the twin's fake treats a cancel of an already expired leg as a no-op, as Binance reports ORDER_ABSENT). A new request is refused (finding F1) until the operator expires the first plan, then a request is placed and cancelled; `account_clean`. Outcome COMPLETE. Variant `legs='stay'` (twin only): nothing expires, the system cancels all three legs itself (CANCELED, one cancel each), still no orphan.

Negative controls: S15 with an actor that places nothing halts at `foreign_order_detected_safe_mode_entered` and names `scripts/demo_clear.py`; the actor's resting order is cancelled by its own id when the run stops early (never a position); S16 with an actor that closes nothing halts at `actor_closes_the_position_outside_the_system`; S16 with a leg that is still open halts at `no_orphan_leg_remains`. Evidence documents carry the schema, kind SYNTHETIC and the facts.

## REUSES per twin

| Twin | REUSES |
|---|---|
| `tests/test_demo_twin_s15_foreign_order.py` | `tests/test_live_reconcile_divergences.py::test_a_duplicate_exchange_client_id_is_journaled_enters_safe_mode_and_alerts`, `tests/test_reconcile_compare_v2.py::test_a_foreign_normal_order_is_a_foreign_order_divergence_and_never_sweepable`, `::test_a_foreign_order_next_to_an_orphan_protective_keeps_only_the_orphan_sweepable`, `tests/test_reconcile_classify.py::test_each_kind_has_the_planned_action_alert_and_safe_mode_reason`, `tests/test_reconcile_tp1_fill.py::test_a_position_larger_than_the_plan_is_not_an_explanation`, `tests/test_demo_twin_s14_safe_mode.py::test_the_catalog_pins_s14_to_this_plan` |
| `tests/test_demo_twin_s16_manual_close.py` | `tests/test_drills.py::test_manual_close_drill_removes_the_legs_that_stayed_after_a_filled_entry`, `::test_manual_close_drill_orphan_variant_sweeps_the_legs_that_stayed_after_a_failed_read`, `::test_manual_close_drill_auto_cancel_variant_has_nothing_to_sweep`, `::test_manual_close_drill_with_the_position_still_open_never_cancels_the_stop`, `tests/test_reconcile_tp1_fill.py::test_tp1_filled_and_position_reduced_is_no_divergence` |

Each twin has a test that checks every referenced test name exists in its file. The plan's read-first named `tests/test_reconcile_compare_v2.py` for a doubled-position test; no test of that file is named for it (`test_a_position_larger_than_the_plan_is_not_an_explanation` in `test_reconcile_tp1_fill.py` is the closest). S15's `test_the_catalog_pins_s14_to_this_plan` is a thin reuse (the catalog pin pattern), kept for the inventory.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s15_foreign_order.py tests/test_demo_twin_s16_manual_close.py tests/test_demo_marker_guard.py tests/demo tests/test_demo_harness.py tests/test_demo_same_code_path.py tests/test_demo_env_factory.py tests/test_no_unratified_defaults.py tests/test_agents_md.py`: 293 passed, 22 skipped (all 22 are tests under `tests/demo`, none passed). Twins: S15 20 tests, S16 17. `TRADING_CI_STRICT=1` run of `tests/demo`: 22 skipped, exit 0.
- Scoped `ruff check` and `ruff format --check` on the six files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code <plan base> -- src scripts params pyproject.toml uv.lock tests/support/demo_scenarios/harness.py tests/support/demo_scenarios/catalog.py tests/support/fault_edge.py` exits 0.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read, no soak. The six new files are LF.

## Deviations from Plan

**1. [Mechanism, inside latitude] The actor calls `env.faults.inner`, not `env.assembly.exchange.adapter`** (key-decisions). The same adapter methods, outside the edge ledger.

**2. [Plan wording] S15 "a CONFIRM places nothing" is shown as "the request gets no card".** The sender's symbol rule (`RESTING_ENTRY_ORDER`) refuses the request before any CONFIRM exists. The SAFE_MODE refusal of a CONFIRM is S14's step.

**3. [Order] S15 runs the doubled-position flow before the foreign-order flow** (twin helper constraint, key-decisions). The plan lists the foreign order first.

**4. [Additions] Steps beyond the plan text:** the refused operator exit in both flows, the clean-tick-with-SAFE_MODE-standing step, the card after the exit (S15 foreign), the restored entry (S15 doubled), and in S16 the verbatim leg status, the system-sent-no-close check and the new-request step.

**5. [Plan wording] S16 "any leg still open is swept" is the coordinator's own sweep, not the reconcile sweeper.** After `POSITION_CLOSED` the coordinator cancels each of its legs by id, and in a tick the protection pass runs before the reconcile pass, so the legs were already gone when the reconcile read the account. Whether the compare would flag a leg left behind (ORPHAN_PROTECTIVE) was therefore not observed here; the reconcile sweeper (ORPHAN_SWEEP) did not act, and its orphan path is covered by the REUSES drill tests, not by this twin.

**6. [Twin model] S16's A3 model covers closePosition legs only** (the Demo record covers no other kind); TP1 is left to the system. A second variant (`legs='stay'`) is twin-only.

**7. [Shared helpers] The scenarios import helpers from `s04_stop_rejected.py`, `s06_replay.py`, `s08_stream_loss.py` and `s14_safe_mode.py`** (catalog names only the six files of the plan). The actor's few lines are copied in S16, not imported from S15, as the plan says.

## Findings

No defect of `src` was found, so no strict xfail was needed. Four observations for the owner:

**F1 (observation, owner decision): after a plan's position is closed, whether by an outside close or by the system, a new request on the symbol is refused until the closed plan's approval expires.** The twin shows `DEMO_APPROVAL_REQUEST_REFUSED` with reason `CONFLICT_WITH_OPEN_POSITION` and source `PENDING_OR_APPROVED_APPROVAL` right after the manual close (position flat, plan FLAT): the sender counts an APPROVED approval whose `expiry_utc` is still in the future (`src/live/approval_sender.py`, `_conflict_sources`). The refusal clears at the plan's expiry (about 26 minutes for a smoke plan, `scripts/demo_clear.py` text) or when something moves the plan APPROVED -> EXPIRED; the scenarios use that transition, which `scripts/demo_clear.py` makes (the live operator commands are status, disable_entries, safemode_exit, close and confirm; none expires a plan). The reason code name says "open position" for a flat account. This is code-defined behaviour, not a bug of this plan, but an owner who closes a position by hand cannot re-enter the symbol for that time. Pinned as observed by `test_a_new_request_waits_for_the_first_plan_to_expire_then_places`.

**F2 (observation): DOUBLED_POSITION makes the system alert and enter SAFE_MODE but act on nothing.** Policy `DELEGATE_TO_COORDINATOR` only marks the plan for a re-check (`notify_divergence`); the coordinator stays COMPLETE, sends no close and no second entry, the stop (closePosition) keeps covering the whole doubled position and TP1 keeps its explicit quantity (sized to the plan). By design (D-02, EXEC-06: closing a position the system did not open is the human's action). Pinned by the twin.

**F3 (observation): `open_entry_order_count` counts every open normal order of the symbol** (`src/live/wiring_parts.py`), not only entries, so a foreign resting order (or any reduce-only order) is listed as source `RESTING_ENTRY_ORDER` and blocks the card. Fail closed, consistent with the plan; the source name is the only inexact part.

**F4 (twin fidelity): the twin does not deliver the actor's fills to the user-data stream and the fake has no leg expiry.** The reconcile reads the actor's position over REST (as it does on Demo), but on Demo the stream will also deliver the actor's ORDER_TRADE_UPDATE and ACCOUNT_UPDATE; that the stream persistence ignores a foreign id (`is_system_client_id` in `src/live/stream_persistence.py`) is by reading, not observed.

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`, `TRADING_DEMO_RUN=1`); agents never connect to Demo:

- The two demo tests only collect and skip. The actor's real orders (a far resting BUY LIMIT, a marketable BUY LIMIT of the smallest valid size, a reduce-only MARKET close) through the real adapter, their acceptance under the Demo filters (PERCENT_PRICE band, min notional), and that the marketable LIMIT fills at once, are unobserved. The actor sizes come from `public.exchange_info` (an unsigned GET the process also makes); the twin's values are the test filters (0.001 step, 100 min notional).
- S15 on Demo: the cadence of the real reconcile loop against the scenario's polling; that the real alert sender journals the FOREIGN_ORDER and DIVERGENCE alerts the same way; the durable SAFE_MODE on PostgreSQL across the two flows; the `/safemode_exit` token flow against real Telegram; the real sender's read of every open order (F3).
- S16 on Demo: the final status each leg really ends with. The 2026-10-22 record says the closePosition legs ended EXPIRED and the REST answer is ABSENT; the status of the explicit-quantity TP1 is unrecorded; whether the real coordinator reaches FLAT at once or the reconcile sees a transient divergence while the stream catches up (the scenario would then record NOT_REHEARSED with the kinds and finish COMPLETE_WITH_GAPS, SAFE_MODE left by the operator exit). The A3 model of the twin is not an observation.
- The failure branch: that an early stop names `scripts/demo_clear.py` is tested on the twin; that the owner's real clean-up (closing an actor position by hand, then `demo_clear.py`) works after a stop between the actor's add and reduce is not. The actor's resting order is cancelled automatically, an actor position never is.
- Not covered by any test: a SHORT system position (V1 plans are LONG; the actor derives its side from the position but only BUY was run), hedge mode, and an actor order that happens to fill while a system entry rests on the same symbol.

## Known Stubs

None.

## Threat Flags

None. T-25-39 (S15 asserts the FOREIGN_ORDER and DOUBLED_POSITION divergences, the SAFE_MODE entry, the alerts, that the system touched nothing, the refused exit and the restored entries), T-25-40 (S16 asserts no orphan leg after the close and the reconcile, names `scripts/demo_clear.py` on failure) and T-25-SC (no package added; `pyproject.toml` and `uv.lock` unchanged) hold.

## Self-Check: PASSED

The six created files exist; commits f4343d2a, 578ba5e8, c9dfea22 and d2cbfc88 are ancestors of HEAD; `git rev-list --count 1b913726..d2cbfc88` is 4.
