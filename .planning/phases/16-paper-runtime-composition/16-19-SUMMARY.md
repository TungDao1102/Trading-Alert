---
phase: 16-paper-runtime-composition
plan: 19
subsystem: paper-runtime / simulated fills
tags: [shadow-fill, lifecycle-reuse, live-minutes, rest-polling, eligibility-start, q-b, funding]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-10 BarOutcome and evaluate_closed_bar (the risk-passed outcome the driver opens); 16-03 BinancePublicMarketData (klines and mark_klines)"
  - phase: 14-backtest-engine
    provides: "new_plan_state, advance, booking_for_event, funding_events, build_trade_record, MinuteSource, validate_minute_series (all used unchanged)"
provides:
  - "src/paper/shadow_fill.py: ShadowFillDriver (open, open_confirmed, advance_to, trade_record, bookings, events), FundingHistory, FillEligibility, eligibility_start_for (Q-B confirm-plus-one)"
  - "src/paper/live_minutes.py: LiveMinuteSource (append-only validated MinuteSource), LiveMinutePoller (REST polling of trade and mark 1m, required cadence and close lag), PollResult"
  - "decisions/16-DEC-Q-B.md committed: option confirm-plus-one, decided by user, 2026-10-09"
affects: [16-31 SHADOW wiring (calls open_confirmed from on_confirmed and journals the audit fields), 16-23 paper ledger, 16-34 runtime configuration (poll cadence and close lag values), 16-22 runtime composition]

actuals:
  tokens: 19300
  tasks: 3
  commits: 5
plan_head_before: 8ce5af84b09aa355475ea1d679d5de955df976de
plan_head_after: 15ff5d57672b02a373c546a73bcc2151a799de4c
commits: 5

tech-stack:
  added: []
  patterns:
    - "Drive the public lifecycle functions over an injected MinuteSource; the byte-equality test against simulate is the drift guard"
    - "Windows partition time (previous end, now]; a call at or before the previous end is a no-op, so replay and restart cannot double-process a minute"
    - "Commit-after-compute: a window that fails (for example missing funding history) changes no state"
    - "Eligibility as a frozen value with a to_audit_dict, so the journal can record the whole chain"

key-files:
  created:
    - src/paper/shadow_fill.py
    - src/paper/live_minutes.py
    - tests/test_paper_shadow_fill.py
    - tests/test_paper_live_minutes.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-B.md
  modified: []

key-decisions:
  - "Q-B (user, 2026-10-09, 'confirm-plus-one'): the fill start is the successful CONFIRM instant recorded on SHADOW_CONFIRMED, floored to the minute, plus exactly one minute, passed to advance as start_exclusive. Because advance selects minutes by CLOSE time, the first eligible minute is the one opening at floor + 1 minute; the minute containing the confirm (and the minute opening exactly at a boundary confirm) is never read"
  - "eligibility_start_for reads no clock and takes the recorded confirm instant; an unsuccessful confirm, a confirm before the signal close, a confirm at or after plan expiry, or a start not before expiry yields status != ELIGIBLE and start None, and open_confirmed refuses it (no fill simulation starts)"
  - "REST polling for both trade and mark 1m (planner choice recorded in the plan objective: no SDK mark-price kline stream, REST weights 1-2); cadence and close lag are required keyword inputs with no default; trade and mark are fetched together and only minutes closed at or before now - close_lag are stored, giving a settled watermark both series share"
  - "Funding is booked in the driver with the engine's own funding_events and open-segment cut, so a funding payment inside the open stretch matches the simulate trade; a position with no funding history fails closed"

patterns-established:
  - "Parity by reuse: re-express only the engine's sizing sequence, never a rule"

requirements-completed: []
requirements-advanced: [PAPER-02]

coverage:
  - id: D1
    description: "A confirmed SHADOW plan is filled through the public Phase 14 lifecycle, record and funding functions and, with the start at the signal close, its trade record is byte-equal to the simulate trade"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_shadow_trade_record_equals_the_simulate_trade_when_start_is_the_signal_close"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_advancing_in_several_windows_gives_the_same_record_as_one_window"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_the_driver_calls_the_public_lifecycle_functions"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_the_driver_neither_uses_the_private_engine_nor_defines_a_lifecycle_step"
        status: pass
    human_judgment: false
  - id: D2
    description: "Fill eligibility follows the user's Q-B decision: no fill at any instant before the threshold, prices inside the confirm minute never create a fill, the first eligible minute is processed once, a boundary confirm excludes the minute opening then"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_no_fill_before_the_threshold_and_the_confirm_minute_is_never_used"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_when_the_first_eligible_minute_trades_through_it_fills_exactly_there"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_a_confirm_on_the_boundary_does_not_fill_on_the_minute_opening_then"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_the_first_eligible_minute_is_processed_once_across_windows_and_replays"
        status: pass
    human_judgment: false
  - id: D3
    description: "The threshold depends only on the recorded confirm instant, so a restart or replay reproduces it and creates no duplicate fill; an invalid or expired confirm starts nothing"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_restart_and_replay_give_the_same_threshold_and_no_duplicate_fill"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_the_module_reads_no_clock"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_an_ineligible_confirm_cannot_open_a_fill_simulation"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_an_expired_plan_starts_nothing"
        status: pass
    human_judgment: false
  - id: D4
    description: "Signal close, APPROVE, CONFIRM and the computed eligibility start are all available to the journal as fields"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_fill.py#test_the_audit_record_carries_signal_close_approve_confirm_and_start"
        status: pass
    human_judgment: false
  - id: D5
    description: "Live 1m trade and mark minutes come from the public REST adapter into an in-memory MinuteSource validated on every batch, forming minutes refused, holes kept, cadence and close lag required"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_live_minutes.py#test_every_batch_is_validated_with_the_minute_series_rules"
        status: pass
      - kind: unit
        ref: "tests/test_paper_live_minutes.py#test_a_forming_minute_is_rejected"
        status: pass
      - kind: unit
        ref: "tests/test_paper_live_minutes.py#test_the_cadence_and_the_close_lag_are_required_with_no_default"
        status: pass
      - kind: unit
        ref: "tests/test_paper_live_minutes.py#test_a_mark_hole_inside_a_position_is_annotated_by_the_lifecycle"
        status: pass
    human_judgment: false
  - id: D6
    description: "The Phase 14 simulator is unchanged (L-02)"
    requirement: PAPER-02
    verification:
      - kind: other
        ref: "git diff 8ce5af8 -- src/backtest is empty; tests/test_backtest_simulator.py passes"
        status: pass
    human_judgment: false
  - id: D7
    description: "That a real Binance markPriceKlines response served over REST returns the just-closed minute within the user-chosen close lag, so the mark minute of a fill is present when the driver advances"
    requirement: PAPER-02
    verification: []
    human_judgment: true
    rationale: "Tests use a fake adapter and no network. The close lag value is the user's (O-07, set by plan 16-34); whether it is long enough for the exchange to publish the closed mark minute is only observable in the live soak. A too-short lag shows up as mark holes annotated in coverage_note, never as a silent wrong fill."

duration: 55min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 19: SHADOW fill driver and live minutes Summary

**`ShadowFillDriver` fills a confirmed SHADOW plan by driving the unchanged Phase 14 `advance`, `booking_for_event`, `funding_events` and `build_trade_record` over live minutes, starting at the user's Q-B choice (`confirm-plus-one`: the recorded CONFIRM instant floored to the minute plus one minute), with a REST-polled `LiveMinuteSource` for trade and mark 1m bars; with the start at the signal close its record is byte-equal to the `simulate` trade.**

## Performance

- **Duration:** about 55 min (2026-10-09)
- **Tasks:** 3 (Task 1 tracer, Task 2 the Q-B decision resolved by the user before this run, Task 3 auto; Tasks 1 and 3 TDD)
- **Files:** 4 created in `src`/`tests`, plus the decision record committed

## Accomplishments

- **Parity by reuse.** `open` re-expresses only the engine's per-plan sizing sequence (fill quantity = planned x `partial_fill_fraction` floored to the step, `protective_levels_for_fill`, `new_plan_state`); `advance_to` calls `advance`, books each event with `booking_for_event`, and books funding with `funding_events`; `trade_record` calls `build_trade_record`. The tracer test shows the SHADOW record equals `simulate`'s trade dict exactly (also when advanced in several windows, and with a non-zero funding payment inside the open stretch).
- **Q-B `confirm-plus-one`.** `eligibility_start_for(signal_close_utc, plan_expiry_utc, confirm_outcome, confirmed_at_utc, approved_at_utc=None)` returns a `FillEligibility` whose `eligibility_start_utc` is `floor_minute(confirmed_at_utc) + 1 minute`, applied once, from the recorded instant only. It reads no clock (an AST test). The driver passes it as `start_exclusive`; `advance` selects minutes by close time, so the first minute read opens at floor + 1 minute and a boundary confirm excludes the minute opening at that instant. Tests prove no fill before the threshold, the confirm minute's prices never create a fill, the first eligible minute is processed exactly once across windows and replays, and a restart that rebuilds from the journaled ISO text gets the same threshold, the same events and bookings, and no duplicate fill.
- **Fail closed.** An unsuccessful confirm, a confirm before the signal close, at or after plan expiry (inclusive boundary, as the confirm gate), or with no minute left before expiry gives `is_eligible == False` and a None start; `open_confirmed` raises for it, so no fill simulation starts. An open position without funding history raises `FundingCoverageError` and the window changes nothing.
- **Live minutes.** `LiveMinuteSource` is append-only, validates every batch with `validate_minute_series` (and the join to the stored tail), refuses a forming minute, never overwrites a stored minute (identical replay is a no-op), leaves holes as holes and raises for a symbol with no series. `LiveMinutePoller` requires `poll_interval_seconds` and `close_lag_seconds` (keyword-only, no default, must be positive), fetches trade and mark together up to `now - close_lag`, retries a transient error at most once, pages with a fail-closed budget, and returns a `settled_through_utc` watermark both series share. `run` polls at the cadence with an injected clock until a stop event.

## Task Commits

1. **Task 1 (tracer): driver byte-equal to simulate** - `56d2440` (test, RED: ImportError at collection), `e4db817` (feat, GREEN)
2. **Task 2 (decision Q-B, resolved by the user): `confirm-plus-one`** - `5e325d7` (docs)
3. **Task 3: eligibility start, live REST minutes, funding** - `b59c403` (test, RED: ImportError at collection), `15ff5d5` (feat, GREEN)

Tracer gate (auto mode): the tracer `<verify>` (`tests/test_paper_shadow_fill.py` and `tests/test_backtest_simulator.py`) was re-run end to end after Task 1 and passed; `git diff` of `src/backtest` against the plan base is empty; expansion continued.

**Plan metadata:** committed separately (docs: complete plan).

## RED Evidence

- **Task 1** (`56d2440`): `ImportError: cannot import name 'shadow_fill' from 'src.paper'` at collection.
- **Task 3** (`b59c403`): `ImportError: cannot import name 'STATUS_CONFIRM_BEFORE_SIGNAL_CLOSE' from 'src.paper.shadow_fill'` and `ModuleNotFoundError: No module named 'src.paper.live_minutes'` at collection.

## Decisions Made

See `key-decisions`. For downstream plans:

- **16-31 wiring.** The `on_confirmed(approval, plan, now_utc)` callback of the confirm book passes the confirm instant; plan 16-31 should build `eligibility_start_for(signal_close_utc=<bar close>, plan_expiry_utc=plan.expiry_utc, confirm_outcome="CONFIRMED", confirmed_at_utc=<the recorded SHADOW_CONFIRMED confirmed_at_utc, not a fresh clock read>, approved_at_utc=<APPROVE instant>)`, call `driver.open_confirmed(outcome, eligibility)`, and journal `eligibility.to_audit_dict()`. After a restart, rebuild the driver from the journaled SHADOW_CONFIRMED event and its `confirmed_at_utc`.
- **Advance only to the settled watermark.** Call `driver.advance_to(result.settled_through_utc, source, bar=..., funding=...)` with the `PollResult` of the poller, never with the raw clock, so a late mark minute is not skipped.
- **Funding history.** The caller supplies `FundingHistory(rows, loaded_start_utc, loaded_end_utc)` built from the public `funding_rate` rows (`parse_funding_row`); the loaded range must cover the holding window or the coverage rule fails closed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] No public quantization floor function exists**
- **Found during:** Task 1
- **Issue:** the plan says to floor the fill quantity with "the public quantization floor function of `src/risk/quantization.py`", but that module only has the full `quantize` pipeline (min-quantity, notional and utilization gates); the engine floors with its own `_floor_to_step`. Changing `src/backtest` or `src/risk` was out of bounds.
- **Fix:** import the engine's `_floor_to_step` (and `_open_segments`, `_EVENT_RANK`, `_RANK_FUNDING`, the funding cut and booking order helpers) by name from `src.backtest.engine`, rather than copying them, so the two cannot drift. The private `_Engine` class is not used (AST test).
- **Files modified:** `src/paper/shadow_fill.py`
- **Commit:** `e4db817`

**2. [Rule 2 - Missing critical] Funding was needed in the Task 1 tracer, not only Task 3**
- **Found during:** Task 1
- **Issue:** byte-equality with `simulate` requires the engine's funding step (the engine always runs `funding_events` for an open stretch), so the funding wiring landed with the tracer; Task 3's funding test is therefore a parity characterization with a non-zero rate that passed on its first run rather than a failing RED test. Task 3's other new tests were RED.
- **Fix:** funding is a required input for an open stretch (`FundingHistory`); without it the call raises `FundingCoverageError` and changes nothing.
- **Commit:** `e4db817`

### Plan-shape choices (not defects)

- `eligibility_start_for` returns a `FillEligibility` (start plus status plus the audit fields) rather than a bare datetime, so "no fill simulation starts" and the four journal-able instants are one value. `confirm_outcome` is typed `str` and compared with the `ConfirmOutcome.CONFIRMED` value, so `shadow_fill` does not import the Telegram-facing shadow module.
- The driver has no `finalize_at_data_end`: live has no data end, so a plan still resting or open is simply in progress. Operator cancel and the DAILY_STOP cancel belong to the ledger plan (16-23).
- `ShadowFillDriver.open` also exists with a raw `eligibility_start_utc` (used by the tracer with the signal close and by the funding parity test); the confirmed path is `open_confirmed`.

## Issues Encountered

- None blocking. A heredoc quirk in the shell tool broke two scripted edits; they were redone with the editor tool.
- Pre-existing failure `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` (logged in `deferred-items.md`) still fails and was not touched; every other test in the `paper`/`backtest`/purity/no-float selection passed.

## What remains for later plans

- **Journal wiring of the audit fields** (signal close, APPROVE, CONFIRM, computed start; `FillEligibility.to_audit_dict`) and the call to `open_confirmed` from the confirm callback belong to plan 16-31 (and the measured-delay fields to 16-35). This plan provides the fields and return values only.
- **Poll cadence and close lag values** are the user's O-07 numbers, supplied by plan 16-34.
- **Ledger integration** (registering the simulated exposure, DAILY_STOP cancel of a resting plan, feeding open positions to the risk verdict) is plan 16-23.
- **Transient error classes.** The poller defaults to `TimeoutError` and `ConnectionError`; the composition root (16-22/16-34) should pass the adapter's network error types through `transient_errors` so the SDK exceptions stay out of the paper core.

- **PAPER-02 is advanced, not closed.** `requirements.mark-complete PAPER-02` was run and then reverted in REQUIREMENTS.md: the requirement text says Phase 16 closes it when Phase 16 criteria 3 and 5 hold, which needs the wiring plans (16-31 and later). The frontmatter therefore lists it as `requirements-advanced`.

## Known Stubs

None.

## Threat Flags

None. T-16-44 (malformed or forming minute bars) mitigated: `validate_minute_series` on every batch, forming minute refused, holes left as holes and annotated by the lifecycle (tests above). T-16-45 (silent semantics drift) mitigated: byte-equality test against `simulate`, AST test forbids `_Engine`, `simulate` and local lifecycle step definitions, `src/backtest` unchanged. T-16-SC accepted: no package installed, `uv.lock` unchanged.

## Self-Check: PASSED

- Files exist: `src/paper/shadow_fill.py`, `src/paper/live_minutes.py`, `tests/test_paper_shadow_fill.py`, `tests/test_paper_live_minutes.py`, `decisions/16-DEC-Q-B.md`.
- Commits exist: `56d2440`, `e4db817`, `5e325d7`, `b59c403`, `15ff5d5`.
- `ruff check`, `ruff format --check`, `mypy src` clean; `tests/test_paper_shadow_fill.py` (30) and `tests/test_paper_live_minutes.py` (22) pass.
