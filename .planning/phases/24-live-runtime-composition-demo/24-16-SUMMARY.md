---
phase: 24-live-runtime-composition-demo
plan: 16
subsystem: live-runtime
tags: [risk-inputs, placement-inputs-source, margin-guard, liquidation-watch, day-risk-backfill]
requires: [24-04, 24-01]
provides:
  - "src/live/risk_inputs.py: LiveRiskInputProducer, build_liquidation_watch, backfill_day_risk, read_pre_placement_inputs, confirm_inputs_from_readings, make_cost_rates_for"
  - "tests/support/live_risk_rig.py: producer rig (build_parts, make_producer_rig, LateInputs, ScriptedExchange)"
affects: [24-17, 24-27, 24-32]
tech-stack:
  added: []
  patterns: ["producer over real Phase 21/22 libraries, fakes only at the edges", "refresh then clock then pure build (WR-04)"]
key-files:
  created:
    - src/live/risk_inputs.py
    - tests/support/live_risk_rig.py
    - tests/test_live_risk_input_producer.py
    - tests/test_live_liquidation_and_tp.py
  modified: []
key-decisions:
  - "Q9 recorded as CLOSE_POSITION (D085 O-4); no override, so build_liquidation_watch takes no policy argument"
  - "The producer composes the real MarginGuard itself when none is injected"
requirements-completed: [EXEC-01]
status: complete
commits: 2
plan_head_before: cc6e912c
plan_head_after: 7efeddd79ba3475afd8a5e075faf9ca5416b243d
actuals:
  tokens: 60000
  tasks: 3
  commits: 2
---

# Phase 24 Plan 16: Live risk-input producer Summary

`LiveRiskInputProducer` implements the `PlacementInputsSource` port of plan 24-04 and builds every placement input from account and exchange truth through the Phase 21 and 22 libraries; the liquidation watch is built with `CLOSE_POSITION` (24-01 Q9, D085 O-4), and the daily-loss backfill and the shared pre-placement read exist as plain functions for plan 24-27.

## What was built

- `LiveRiskInputProducer.for_plan(approval, plan, confirmed_at_utc)`: reads exchangeInfo (a TRADING PERPETUAL), the shared pre-placement readings, the counted reservations and the brackets; evaluates the day (`LiveDayRiskService`); refreshes the equity (`LiveEquitySource.refresh()`), THEN reads the clock once (WR-04); resolves equity, the commission (`cost_rates_for`) and calls the pure `build_live_risk_inputs`. It returns `PlacementInputs` (`risk_kwargs["now_utc"] == now_utc`, exactly the 13 risk keys and the 3 gate keys, 3 planned legs, all open algo orders counted) or a `PlacementRefusal`.
- `LivePlacementContext`: the real `MarginGuard(config_guard, brackets, equity, reservations, clock, limits)` (target leverage 5 ISOLATED comes from the injected `SymbolConfigGuard`), the alert sink passed in, the protection registry, `latest_closed_bar_close` from the signal context, `gtd_clock_margin` = max(ahead, behind) of the drift limits, `TP1_QUANTITY_FRACTION`.
- Refusal reasons: `UNCERTAIN_ACCOUNT_STATE` and `DAILY_STOP_BLOCK` (from the builder and the cost-rate result), `SIGNAL_CONTEXT_UNAVAILABLE`, `EXCHANGE_STATE_UNAVAILABLE`, `RESERVATIONS_UNAVAILABLE`, `SYMBOL_NOT_TRADABLE`, `BRACKETS_UNAVAILABLE`, `CLOCK_UNAVAILABLE`, `PLACEMENT_INPUTS_ERROR` (only the exception class name is kept in `last_error_type`).
- `backfill_day_risk(day_risk, now_utc)`: one call, never raises, logs and returns the failure class name (D087).
- `read_pre_placement_inputs(adapter, symbol, clock)`: mark, last, open orders, open algo orders, positions, position mode, each read once, the clock read after the last read; `confirm_inputs_from_readings(...)` turns the same readings into the `ConfirmInputs` of the CONFIRM recheck using the manager's own reading helpers.
- `build_liquidation_watch(brackets, fee_rates, limits)`: `LiquidationWatch(..., policy=LiquidationFailurePolicy.CLOSE_POSITION)`.
- `make_cost_rates_for(commission_for, parameter_set)`: `resolve_live_cost_rates` over a commission lookup (for plan 24-15's `CommissionCache.account_commission_for`).

## Tests

- `tests/test_live_risk_input_producer.py` (32 tests): complete inputs from the recorded-Demo account (equity 4999.09343961, not a fixture), the live context, the WR-04 order (event log: the clock read follows the last refresh; control: a `now` taken before the refresh gives a negative age and is refused), 15 parametrized refusal cases (equity refresh failed or older than `account.max_equity_age_ms`, loss older than `account.max_daily_loss_age_ms`, DAILY_STOP, commission unknown or stale, brackets unreadable or older than the bound, unexplained exchange position, positions or algo orders unreadable, exchangeInfo failed, symbol not trading or not listed, reservations unreadable), no configuration POST by the producer, the D087 backfill (renew then pass; skipped then refuse), and end to end under the Phase 24 live rig: APPROVE then CONFIRM, the real margin guard moves the recorded CROSSED x20 to ISOLATED x5, exactly one `place_entry`, outcome `OK`. Three manager-level refusals place nothing: 199 open algo orders (EXCHANGE_CONSTRAINT), symbol configuration not verified (MARGIN_CONFIG_UNVERIFIED), margin claims too large (INSUFFICIENT_MARGIN).
- `tests/test_live_liquidation_and_tp.py` (15 tests): policy `CLOSE_POSITION`; a failed post-fill check closes through the coordinator (one reduce-only market close, flat, SAFE_MODE once, one `CLOSE_REQUIRED` alert with the B6 reason); a passing check closes nothing; the producer snapshot is INCOMPLETE until the guard verdict completes it, then `snapshot_is_valid_for_live` holds (control: a missing market-lot filter never becomes valid); after a fill and a terminal entry the coordinator places STOP, TP1 and TP2 and ends COMPLETE with no alert; the shared read reads each input once, a failed read is `None`, and the CONFIRM recheck accepts or refuses (hedge account, existing position, unprotected position, missing price) the inputs built from the readings.

## Verification run

- `uv run pytest -m "not docker" tests/test_live_risk_input_producer.py tests/test_live_liquidation_and_tp.py tests/test_live_tracer.py tests/test_snapshot_live_equity.py tests/test_cost_parity.py tests/test_live_ast_guards.py tests/test_no_unratified_defaults.py`: green.
- `tests/test_day_risk_service.py tests/test_account_equity_source.py tests/test_margin_guard.py`, `tests/test_protection_liquidation.py tests/test_liquidation_watch.py tests/test_confirm_recheck.py`: green.
- `uv run ruff check`, `uv run ruff format --check` on this plan's files, `uv run mypy src/live`: clean. `git grep "float("` on `src/live/risk_inputs.py`: nothing. `pyproject.toml` and `uv.lock` untouched.
- No PostgreSQL test was run (none was needed by this plan's tests). The full suite was not run.

## Deviations from Plan

All additive; no rule 4 (architecture) change.

1. **[Rule 3 - Blocking] `signal_context_for` constructor argument.** The port gives only `(approval, plan, confirmed_at_utc)`, but `LivePlacementContext` needs the persisted Signal and `latest_closed_bar_close` ("from the signal request", plan 24-14's `SignalRequest`, not merged yet). The producer takes `signal_context_for: Callable[[TradePlan], PlanSignalContext | None]` (an in-process lookup). Plan 24-27 must adapt the signal source to it.
2. **Optional `margin_guard`.** The plan lists `margin_guard` and also `config_guard`/`brackets`; when `margin_guard` is None the producer composes the real `MarginGuard` from the other parts (key link `MarginGuard(`), otherwise it uses the injected one.
3. **`parameter_set` is a `Mapping` of registry values** (pass `ParameterSet.params`), validated for the required keys at construction.
4. **`cost_rates_for(symbol, now_utc) -> LiveCostRatesResult`** (sync or async); added `make_cost_rates_for` as the adapter from the commission lookup.
5. **`read_pre_placement_inputs` signature.** It returns raw `PrePlacementReadings` (the readings need the Signal, plan, limits and registry to become `PrePlacementInputs`); `confirm_inputs_from_readings` completes the step and returns `ConfirmInputs` (pre-placement inputs plus position mode). Plan 24-27 binds the prefetch to the pair.
6. **Private helpers imported from `src.execution.manager`** (`_mark_price_of`, `_last_price_of`, `_position_symbols`, `_open_order_symbols`, ...) so gate 5e and the CONFIRM recheck read identically instead of duplicating the parsing. Making them public is a one-line change to `manager.py` that this plan did not make (not its file).
7. **Extra test-support file** `tests/support/live_risk_rig.py` (not in the plan's file list) holds the shared producer rig, so the two test files do not import each other.
8. **A day-open requirement.** The day row opens only after a completed backfill (WR-06/D087); the tests prime it. Production must run `backfill_day_risk` before the first CONFIRM.

## Notes for plan 24-27 and the orchestrator

- `LivePlacementContext.alert_sink` must provide `.alert(...)` (the `JournalFirstAlertSink` shape). The coordinator and closer take a different sink (`CriticalAlertSink.critical(...)`). Do not pass the same object unless it has both.
- The reservation store is synchronous (`PgRiskReservationStore`): `list_counted` and `list_margin_claims` may return awaitables, so plan 24-27 can wrap them with the store executor (24-05). The producer accepts either; the margin guard accepts either for claims.
- The producer reads mark and last price through the shared function although it only uses positions and orders (two extra weight-1 reads per CONFIRM); kept so that the shared function is literally shared.
- The day's `exposure` for the day-open rule (D-07) is: any non-zero exchange position, any open order or algo order, or a PLACED/OPEN reservation of another plan. A RESERVED reservation (approved, unplaced) is not exposure.
- `positions_reconciled` in `gate_kwargs` is True only because `build_live_risk_inputs` explained every exchange exposure by a PLACED or OPEN reservation; the reconcile loop and SAFE_MODE remain separate gates.
- No DECISIONS row is needed from this plan (D090 not requested).
- Gaps: no PostgreSQL test (none required); real Binance behavior of the producer is unproven until the Demo run of plan 24-35; the TEST_ONLY numbers in `tests/support/live_risk_rig.py` prove the composition only.

## Known Stubs

None.

## Threat Flags

None (no new endpoint, auth path or schema; the producer only reads, and the one configuration POST stays inside the Phase 22 margin guard behind the manager's gates).

## Self-Check: PASSED

- `src/live/risk_inputs.py`, `tests/support/live_risk_rig.py`, `tests/test_live_risk_input_producer.py`, `tests/test_live_liquidation_and_tp.py`: present.
- Commits `ed9036e3` and `7efeddd7`: ancestors of HEAD.
