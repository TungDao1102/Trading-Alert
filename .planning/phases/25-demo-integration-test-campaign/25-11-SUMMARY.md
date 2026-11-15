---
phase: 25-demo-integration-test-campaign
plan: 11
subsystem: demo-scenarios
tags: [D-04, D-05, D-06, S04, S03, S18, stop-rejected, crossed-stop, unprotected-drill, fault-edge, tdd, EXEC-01, OPS-01]
requires: [25-02, 25-08, 25-09, 25-10]
provides:
  - "tests/support/demo_scenarios/s04_stop_rejected.py: S04 run(env, recorder) plus the helpers S03 and S18 share (injected_rejection, drive_fill, observe_close_window, wait_flat, assert_b5_reaction, expire_plan_and_leave_safe_mode, stop_placements, close_placements, protection_rows, alert_rows, step recorders)"
  - "tests/support/demo_scenarios/s03_crossed_stop.py: S03 run(env, recorder, *, stop_sender=None), crossed_mark, wrong_side_trigger, send_wrong_side, record_answer"
  - "tests/support/demo_scenarios/s18_unprotected.py: S18 run(env, recorder), confirm_token, bot_channel"
  - "three CI twins (tests/test_demo_twin_s04_stop_rejected.py, _s03_crossed_stop.py, _s18_unprotected.py) and three owner-run demo tests (tests/demo/test_demo_s04_..., _s03_..., _s18_...)"
affects: [25-17, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "an injected trigger is DEMO_FAULT_INJECTED, the reaction is the env label, anything that did not happen is NOT_OBSERVED"
    - "a rejection is injected at the adapter edge before anything is sent; the coordinator's reaction stays the real one"
    - "the exchange's answer is recorded as code and exception class name only, never the message text"
key-files:
  created:
    - tests/support/demo_scenarios/s04_stop_rejected.py
    - tests/support/demo_scenarios/s03_crossed_stop.py
    - tests/support/demo_scenarios/s18_unprotected.py
    - tests/test_demo_twin_s04_stop_rejected.py
    - tests/test_demo_twin_s03_crossed_stop.py
    - tests/test_demo_twin_s18_unprotected.py
    - tests/demo/test_demo_s04_stop_rejected.py
    - tests/demo/test_demo_s03_crossed_stop.py
    - tests/demo/test_demo_s18_unprotected.py
  modified: []
key-decisions:
  - "The pre-placement mark is read through `adapter.get_mark_price` (execution/manager gate 5e and live/risk_inputs), not through the public reader, so `FaultEdge.moved_mark` (a `FaultPublic` method) would not reach it. S03 variant (i) answers `get_mark_price` through `FaultEdge.override` with the real reading and its price moved 1% past the stop, armed after the request is derived (the injector reads the same mark) and cleared in a finally."
  - "The CONFIRM press is refused by the approval core's recheck (journaled as DEMO_CONFIRM_EXPIRED with rejected_at_confirm in the shadow journal), before the placement service writes any LIVE_PLACEMENT_* row. S03 reads both journals through `shadow.journal_for_correlation` and `journal.list_by_correlation`, which exist on the in-memory and the PostgreSQL stores, so the check holds on Demo."
  - "S03 variant (ii) uses `FaultEdge.override` instead of `mutate_payload`: `mutate_payload` cannot see the exchange's reply, and the plan requires the real answer to be recorded by code. On Demo the override sends the stop with its trigger mirrored around the mark (2*mark - stop on the stop's own decimal precision) and records what comes back; a stop that is already past the mark is sent unchanged. On the fake the trigger rule is not modelled, so the -2021 is injected (SYNTHETIC). The default sender can be replaced (`stop_sender`) so the twin tests the 'exchange accepted the stop' branch."
  - "If Demo answers a wrong-side stop with another code (research assumption A2) the step is NOT_REHEARSED/NOT_OBSERVED with the code recorded; if it accepts the stop the scenario finishes by the production operator close and ends COMPLETE_WITH_GAPS."
  - "B5 enters SAFE_MODE, which is durable on Demo (PostgreSQL), so the shared tail leaves it through `/safemode_exit` and `/confirm` (the owner's path, RUNBOOK 21.1a) after expiring the APPROVED plan; otherwise the next scenario would start in SAFE_MODE."
  - "The window 'CLOSE_REQUIRED, entries blocked' is stepped on the fake by holding the reduce-only close at the exchange for one look (FaultEdge hold/release), the same technique as S02. On Demo nothing is held (a delayed risk-reducing close would be real exposure): the poll between ticks may land after FLAT, which is recorded as NOT_OBSERVED and the outcome COMPLETE_WITH_GAPS."
  - "S18 injects -2021 for the stop and -2022 (a test convention, D055) for every reduce-only close (`times=None` until cleared; cleared in a finally as well) and treats every step inside the fault window as DEMO_FAULT_INJECTED, because nothing real was sent; only the final close, after the fault is lifted, is a real Demo order."
  - "S18's operator step asserts what the code does: `/close` issues a token for a CLOSE_FAILED plan and `/confirm` is answered CLOSE_ALREADY_REQUIRED with nothing sent. The plan's wording 'the operator /close flattens the position' does not describe V1; the flatten is the coordinator's own retry once the fault is lifted (see Findings)."
  - "The confirm token is read from the process's bot channel (`FakeBot.sent` objects on the twin, `RecordingBot.sent` pairs on Demo) and never recorded; a twin test asserts no token reaches the evidence."
requirements-completed: [EXEC-01, OPS-01]
status: complete
duration: 150min
completed: 2026-11-07
commits: 6
plan_head_before: b9d2088ec3ca3087ea634feb80aca2d05ea89b98
plan_head_after: 9159836b4f7a7e46afb1620ef4da5622851df965
actuals:
  tokens: 22800
  tasks: 3
  commits: 6
---

# Phase 25 Plan 11: S04 stop rejected, S03 crossed stop, S18 unprotected drill Summary

The stop-failure scenarios of the Demo campaign, each as a shared `run(env, recorder)`, a CI twin on the fake composed process and an owner-run demo test. S04 proves a stop the exchange refuses after a fill is never resent and ends in one reduce-only `xc-` close; S03 proves a mark already past the stop is refused at CONFIRM with nothing sent, and a wrong-side stop after a fill is handled exactly like S04; S18 rehearses the unprotected-position drill (stop rejected plus failing closes) end to end with the operator's real command path. Nothing under `src`, `scripts`, `pyproject.toml`, `uv.lock`, `harness.py`, `catalog.py` or `fault_edge.py` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): S04 stop rejected after a fill | 1078886a | 79e94a21 |
| 2: S03 price crossed the stop | 6757bc63 | 408f92ba |
| 3: S18 unprotected-position drill | b463bdbe | 9159836b |

RED means the twin and demo test were committed while the scenario module was absent (collection error confirmed before each commit).

## What each scenario asserts

**S04** (`s04_stop_rejected.run`): clean start, start, `place_algo_protective` armed with an injected `BadRequestError` -2021 (`raise_before_send`, once) before the fill, `fill` request approved, confirmed and filled. Through the process only: exactly one stop call at the fault edge for the plan's stop id and it was the injected one (nothing reached the exchange for it), its intent REJECTED, never resent after five settle ticks; the journal holds `UNPROTECTED -> CLOSE_REQUIRED` with reason `B5_STOP_REJECTED`; exactly one `place_market_close` under `derive_close_order_id(plan_hash, 1)` (`xc-`), one-way (`position_side` BOTH), the position flat; `OPERATIONAL_ALERT` rows `CLOSE_REQUIRED` and `PROTECTIVE_REJECTED` name the plan; one `place_entry` in total; while the plan is CLOSE_REQUIRED `blocks_new_entries()` is True; the plan expires, SAFE_MODE is left by `/safemode_exit` and `/confirm`, `account_clean` PASSED. Labels: injection DEMO_FAULT_INJECTED (`label_for(env, injected=True)`), close `label_for(env, injected=False)`; on the fake everything is SYNTHETIC (label rule pinned on a non-synthetic stub env).

**S03** (`s03_crossed_stop.run(env, recorder, *, stop_sender=None)`): variant (i): request derived, card, APPROVE, then `get_mark_price` overridden with a reading 1% past the stop, CONFIRM refused by the real recheck with `MARK_PRICE_CROSSED_STOP` (journaled), zero `place_entry`, no order, algo order or position, then the plan expires and the symbol is held by nothing. Variant (ii): a second `fill` request; the first stop request is answered `-2021` (injected on the fake, a mirrored-trigger payload to the real exchange on Demo); the answer is recorded as `{answer, code, exception_class, source}`; the reaction is S04's (`assert_b5_reaction`), then plan expiry, SAFE_MODE exit and `account_clean`. The variant (i) refusal step is DEMO_FAULT_INJECTED on Demo (driven by an injected mark); the answer step is DEMO_OBSERVED only for a real rejection with -2021.

**S18** (`s18_unprotected.run`): stop rejected (-2021, once) and every close rejected (-2022, until cleared). The plan reaches CLOSE_FAILED with `blocks_new_entries()` True, SAFE_MODE on and the position still open; five settle ticks later it is still CLOSE_FAILED and blocked, at least two close attempts reached the edge (all injected), the stop was never resent; alerts `CLOSE_REQUIRED`, `PROTECTIVE_REJECTED` and `EMERGENCY_CLOSE_FAILED` name the plan; the operator `/close` and `/confirm` go through `wiring.operator` with the authorized chat and the smallest allowed user id (token read from the bot channel): `CONFIRM_REQUIRED`, then `CLOSE_ALREADY_REQUIRED` with no close sent by the command (asserted on the twin; on Demo the background scheduler may send one in between, so only recorded). The close fault is cleared, the coordinator's retry sends one real reduce-only `xc-` close, the plan ends FLAT, entries unblock, SAFE_MODE is left, `account_clean` PASSED. On any halt a `state_left_on_demo` FAILED step is recorded that names `scripts/demo_clear.py` (`CLEAR_INSTRUCTION`).

## REUSES per twin

| Twin | REUSES |
|---|---|
| `tests/test_demo_twin_s04_stop_rejected.py` | `tests/test_protection_branches.py::test_branch_b5_definitive_stop_rejection_after_a_fill_closes_and_ends_flat`, `::test_branch_close_failed_keeps_blocking_and_retries_every_step_until_flat`, `tests/test_fault_edge.py::test_an_injected_stop_rejection_after_a_fill_ends_in_close_required_and_a_close`, `tests/test_emergency_market_close.py::test_tracer_one_part_closes_the_position_and_reports_flat` |
| `tests/test_demo_twin_s03_crossed_stop.py` | `tests/test_pre_placement.py::test_evaluate_refuses_a_crossed_mark_price`, `::test_check_mark_price_position`, `tests/test_protection_branches.py::test_branch_b5_definitive_stop_rejection_after_a_fill_closes_and_ends_flat`, `tests/test_exchange_errors.py::test_demo_observed_codes_are_exactly_the_probe_observed_codes_in_the_table` |
| `tests/test_demo_twin_s18_unprotected.py` | `tests/test_live_operator_commands.py::test_close_asks_for_a_confirm_and_closes_once_after_it`, `tests/test_protection_branches.py::test_branch_close_failed_keeps_blocking_and_retries_every_step_until_flat`, `tests/test_emergency_market_close.py::test_a_reduce_only_rejection_on_an_open_position_fails_without_a_resend`, `tests/test_drills.py::test_unprotected_drill_blocks_entries_through_the_loop` |

Each twin has a test that checks every referenced test name exists in its file; the plan's REUSES AST one-liner exits 0 for S03 (and the same shape holds for the other two).

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s04_stop_rejected.py tests/test_demo_twin_s03_crossed_stop.py tests/test_demo_twin_s18_unprotected.py tests/test_demo_marker_guard.py -x -q`: all passed.
- With `tests/demo`, `tests/test_demo_same_code_path.py`, `tests/test_demo_harness.py`, `tests/test_demo_env_factory.py`, `tests/test_no_unratified_defaults.py`, `tests/test_fault_edge.py` and every other `tests/test_demo_twin_s0*.py`: 360 passed, 8 skipped (all 8 skipped are the demo tests, none passed); `TRADING_CI_STRICT=1` collection of `tests/demo` exits 0 with all skipped.
- Scoped `ruff check` and `ruff format --check` on the nine files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock tests/support/demo_scenarios/harness.py tests/support/demo_scenarios/catalog.py tests/support/fault_edge.py` exits 0.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read.

## Deviations from Plan

**1. [Plan wording, no code change] The pre-placement mark is not `moved_mark`.** The plan says "moved_mark on the reader the check uses". The check reads `adapter.get_mark_price`, the signed adapter, so the right seam is `FaultEdge.override("get_mark_price", ...)`. `FaultPublic.moved_mark` would not have reached it.

**2. [Mechanism] S03 (ii) uses `override`, not `mutate_payload`.** `mutate_payload` cannot observe the exchange's answer and the plan requires it to be recorded verbatim by code. The override sends the mutated payload itself and records the answer (the ledger shows mode `override`).

**3. [Plan wording, see Findings] The operator `/close` does not flatten a CLOSE_FAILED plan.** The plan's truth and S18 wording say it does after the fault is cleared; the code answers CLOSE_ALREADY_REQUIRED and the coordinator's own retry flattens. S18 asserts and records what the code does.

**4. [Scope choice] "A new request during CLOSE_REQUIRED is refused" is shown by `blocks_new_entries()` and one `place_entry` in total, not by a second request.** A second injected request on the symbol is refused at the card for the symbol rule (open position, ACTIVE_PLAN), which would not prove the coordinator's block. The coordinator is the registry the entry gate reads; the unit tests of the gate remain the proof of the refusal itself.

**5. [Shared helpers] S03 and S18 import helpers from `s04_stop_rejected.py`.** The catalog names only the nine files, so the shared prologue, window observer, B5 reaction check and cleanup tail live in the first file of the plan, as in plan 25-10.

**6. [Twin rig limit, not a src defect] The S18 twin relaxes the rig bot's text check for `/close` replies only.** `live_composed_rig` demands `Mode: DEMO` and +07/UTC pairs in every text that names BTCUSDT; the operator's short replies ("Close the BTCUSDT position ...", "Close BTCUSDT: <code>") name the symbol but are command replies without either, and the operator drops a refused reply (`live.operator.reply_failed`), so the token never arrived. The twin wraps `FakeBot._text_check` (texts starting with "Close " or "Nothing to close" skip it, everything else keeps it). `live_composed_rig.py` was not edited (shared file).

## Findings

**F1 (design observation, not a defect fixed here): `/close SYMBOL` + `/confirm` on a plan in CLOSE_REQUIRED or CLOSE_FAILED is a token round trip that ends `CLOSE_ALREADY_REQUIRED`, and the reply is "Close BTCUSDT: CLOSE_ALREADY_REQUIRED" while the position is still open and the closes keep failing.** `ProtectionCoordinator.operator_close` refuses a plan whose close is already required (`src/execution/protection.py` around line 1206), and `OperatorCommands._closable_plan` offers the command for any plan not FLAT or ENTRY_ENDED_NO_FILL, so the owner is asked to confirm something that can never act. The close itself stays the coordinator's retry at every step. Consequence for the owner at the G2-016 drill: during CLOSE_FAILED the human action that works is a manual close on the exchange (RUNBOOK section 3 implementation status says the same). No src change was made; if the owner wants `/close` to be an out-of-cadence retry or to say "the close is already being retried", that is a Phase 20/24 behaviour change with its own DECISIONS row.

No xfail was needed. No other twin exposed a defect in `src`.

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`, `TRADING_DEMO_RUN=1`); agents never connect to Demo:

- All three demo tests only collect and skip. That an injected -2021 at the edge before the stop leads on Demo to one real reduce-only close, with the plan FLAT and the account clean (S04), and the real `/safemode_exit` path on the real PostgreSQL safe-mode store, is unobserved.
- S03 variant (ii) on Demo: whether the exchange answers a mirrored wrong-side stop with -2021 (assumption A2) is unobserved; the mirrored price stays on the stop's decimal precision and assumes a 0.1 tick for BTCUSDT; a different code or an accepted stop is recorded honestly (NOT_OBSERVED, COMPLETE_WITH_GAPS) but the accepted-stop branch was only exercised on the twin through a replaced `stop_sender`. `send_wrong_side` is unit-tested against a stub adapter, not the real one.
- S03 variant (i) on Demo: the override returns the real reading with a moved price; that the refusal appears as `DEMO_CONFIRM_EXPIRED` with `rejected_at_confirm` (not as a `LIVE_PLACEMENT_*` row) is the twin's observation, and the scenario accepts either row.
- The "CLOSE_REQUIRED, entries blocked" window and "no entry opened meanwhile" are stepped on the fake only (the close is held for one look); on Demo the window is best effort (NOT_OBSERVED if missed).
- S18 on Demo leaves a REAL open Demo position without a stop and SAFE_MODE on while the faults are armed; if the run stops early the owner follows the recorded step (`scripts/demo_clear.py` after closing in the Binance UI). The -2022 close rejection is a test convention (D055), never an exchange observation. The operator `/close` reply text and the real token delivery over Telegram are unobserved (the twin's bot is a fake with a relaxed text check for those replies).
- The `RecordingBot` path of `confirm_token` is tested on a stub shape, not against the real PTB bot.

## Known Stubs

None.

## Threat Flags

None. T-25-26 (S04, S03 ii and S18 assert one stop call and a close at the edge, twins in CI), T-25-27 (S18's close step, `leaves_state`, and the `scripts/demo_clear.py` failure step) and T-25-SC (no package added; `pyproject.toml` and `uv.lock` unchanged) hold.

## Self-Check: PASSED

All nine created files exist; commits 1078886a, 79e94a21, 6757bc63, 408f92ba, b463bdbe and 9159836b are ancestors of HEAD; `git rev-list --count b9d2088e..9159836b` is 6.
