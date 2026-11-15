---
phase: 24-live-runtime-composition-demo
plan: 22
subsystem: live
status: complete
tags: [health, degraded, d056, d058, enablement, kill-gate, ops-04, phase-24]
requirements-addressed: [EXEC-01, OPS-02, OPS-04]
requires: [24-02, 24-10, 24-11, 24-12]
provides:
  - "src/ops/health.py: HealthRuntimeMode, run_health_checks(results, mode, demo_degraded_allowed), HealthVerdict.mode/demo_degraded_allowed/degraded_names, check_not_applicable, check_telegram_delivery_observed, health_check_event"
  - "src/live/health.py: LiveHealthProducer (ten results), LiveHealthThresholds, RestErrorCounter, DbWriteTracker, ReconcileObserver, TelegramDeliveryObserver, health_tick_once"
  - "src/live/enablement.py: DEMO_RUNTIME_OPERATOR_ID, enable_demo, start_disabled, persist_enablement_snapshot, on_kill_gate_verdict, kill_gate_tick_once"
affects: [24-26, 24-27, 24-29, 24-32]
key-files:
  created:
    - src/live/health.py
    - src/live/enablement.py
    - tests/test_live_health.py
    - tests/test_live_enablement_wiring.py
  modified:
    - src/ops/health.py
    - tests/test_execution_health.py
key-decisions:
  - "Mode omitted in run_health_checks is the LEGACY path (DEGRADED passes, verdict.mode is None): scripts/demo_rehearsal.py produces DEGRADED itself and its test needs it to pass until plan 24-29. The live process cannot use such a verdict: enable_demo refuses a verdict whose mode is not DEMO, and a test pins that the only src caller (src/live/health.py) passes mode=."
  - "HealthVerdict carries mode and demo_degraded_allowed; a hand-built OK verdict with a DEGRADED result is rejected in LIVE and in DEMO without the flag; the flag is only valid in DEMO."
  - "telegram_delivery reads the outcome of the latest real send (startup probe, alert drain); a tick never messages the owner. Nothing observed yet is FAIL."
  - "Kill-gate state for enable_demo is supplied by the caller from the analytics source; None is refused (no default; KillGateState.WITHIN_BUDGET appears nowhere in src/live)."
  - "Thresholds without a limits key (max REST error rate, max age of the latest db write) are required arguments of LiveHealthThresholds with no default (missing contract is TBD, never invented)."
plan_head_before: 17307cd08288d97d6bc482e258b1380955ec41f5
plan_head_after: 2a2a447a95b47d0d43d96ffb0486341e35a3b205
commits: 2
actuals:
  tokens: 60000
  tasks: 3
  commits: 2
completed: 2026-10-31
---

# Phase 24 Plan 22: Health producers, DEGRADED policy D056, DEMO enable Summary

**DEGRADED now means something: LIVE never passes it, DEMO passes it only under an explicit, journaled flag; the live process produces all ten health results with the Q5 meanings, and the only way to an enabled controller is a DEMO-only in-process `enable_demo` after a passing ten-check verdict. The kill gate can only switch off.**

## What was built

- `src/ops/health.py` (D056, D-26): `HealthRuntimeMode` (DEMO, LIVE; any other value, TESTNET included, raises). `run_health_checks(results, mode=None, demo_degraded_allowed=False)`: a DEGRADED result is not OK in LIVE, not OK in DEMO without the flag, OK in DEMO with it; the flag raises `ValueError` outside DEMO. `HealthVerdict` stores `mode` and `demo_degraded_allowed` (so the flag use is journaled with the state) and its validator rejects a hand-built OK verdict that breaks the rows. The "unchanged policy" sentence is replaced by the rows table in the docstring. New pure helpers: `check_not_applicable` (DEGRADED), `check_telegram_delivery_observed` (no message sent), `health_check_event` (the same event the probe journals, optionally with extra payload keys).
- `src/live/health.py` (C-3, D058, OPS-04): `LiveHealthProducer.produce` returns the ten results in `ALL_CHECK_NAMES` order. market_feed_freshness is the age of the OLDEST tracked REST mark (missing, empty symbol set, stale, or ahead beyond the ratified skew all FAIL); ws_connection_state and user_data_stream_state come from the stream state (the second also from the divergence queue halt reason); last_closed_candle_time is DEGRADED "not applicable"; rest_error_rate from `RestErrorCounter` (per-window, `wrap` decorator); reconciliation_drift, unprotected_positions and orphaned_orders from `ReconcileObserver` (the composition feeds it each `TickReport`; divergences come from the last tick that compared); db_writes from `DbWriteTracker` (a failed latest write clears the stamp); telegram_delivery from `TelegramDeliveryObserver` (`note_send_report(SendReport)`, one-time `probe` for the startup). `health_tick_once` judges with the producer's mode and flag, stores the verdict on the producer before writing, then journals ten `HEALTH_CHECK` events and one `HEALTH_VERDICT` (is_no_trade, mode, flag, degraded and failing names), every payload carrying `python_version` and `app_revision` from `diagnostic_payload()` (24-11).
- `src/live/enablement.py` (D-27, D-28, Q5): `enable_demo` raises `LiveEnableForbidden` for LIVE and TESTNET before touching the controller; otherwise it refuses (journaled `LIVE_ENABLE_REFUSED` with the failing check names, controller stays disabled) a verdict not judged for DEMO (a legacy no-mode verdict too), a not-OK verdict (a stale or missing mark price is the market_feed_freshness FAIL, D058), an unevaluated kill-gate state, or INSUFFICIENT_EDGE; else it calls `controller.enable(DEMO_RUNTIME_OPERATOR_ID, ...)` and persists the snapshot under `SystemStateKey.LIVE_ENABLEMENT` through the StoreExecutor writer (a failed snapshot write is logged and reported, never undoes the enable). `start_disabled` always returns a fresh DISABLED controller; a stored enabled or malformed snapshot is journaled `LIVE_ENABLEMENT_RESET_AT_START` (no value echoed) and overwritten. `on_kill_gate_verdict` / `kill_gate_tick_once`: INSUFFICIENT_EDGE while enabled disables once with operator `KILL_GATE`; any other state does nothing; never an enable.

## Verification

- `uv run pytest -m "not docker"` over: tests/test_execution_health.py, test_live_health.py, test_live_enablement_wiring.py, test_execution_enablement.py, test_execution_manager.py, test_kill_gate_event.py, test_kill_gate_state.py, test_live_ast_guards.py, test_live_tracer.py, test_no_unratified_defaults.py, test_paper_shadow_isolation.py, test_domain_no_float.py, test_agents_md.py, test_phase18_gate.py, test_phase23_gate.py, test_controller_rehydrate.py, test_live_scheduler.py, test_live_runtime_cli.py: all pass.
- Rig tests (real desk, confirm flow, service, manager over the Binance-semantics fake): before `enable_demo` the CONFIRM ends `NO_TRADE DISABLED` with zero `place_entry`; after it, exactly one; a kill-gate switch-off makes the same flow end `DISABLED` again.
- AST test: `.enable(` is called in `src/live` only inside `enable_demo` (with a negative control). `git grep "unchanged policy" -- src/ops/health.py` prints nothing. `uv run mypy src` (286 files), scoped ruff check and format, `uv run python scripts/verify_decision_alignment.py all` (ALL_PASS), `uv lock --check`, `git diff --exit-code -- pyproject.toml uv.lock` all clean.
- Not run: PostgreSQL tests (none apply), the full suite (orchestrator).

## Deviations from Plan

**1. [Rule 3 - Blocking / plan correction] `mode` is optional in `run_health_checks`, not required.** The plan says "existing callers in tests updated to pass the mode explicitly". Eight test files and `tests/support/live_rig.py` (not in this plan's file list; siblings may touch them) call `run_health_checks(results=...)`, and `scripts/demo_rehearsal.py` builds DEGRADED results itself and `tests/test_demo_rehearsal_flow.py` expects that verdict OK (the plan's "nothing produced DEGRADED before" does not hold for the rehearsal script). So omitting the mode is the documented LEGACY path that keeps the old result and yields a verdict with `mode=None`. The live process cannot enable from such a verdict, and a test pins that every `src` caller passes `mode=`. Plan 24-29 (rehearsal) should pass `HealthRuntimeMode.DEMO` with the flag; after that the legacy path can be removed.

**2. [Design] Test-only convenience: `tests/test_live_enablement_wiring.py` imports `Parts` from `tests/test_live_health.py`** to build a real stale-mark verdict without duplicating the fixtures.

No other Rule 1-3 fixes. Both task 2 and task 3 share one file pair and were committed together.

## Pre-existing failure observed (not caused by this plan)

`tests/test_demo_rehearsal_flow.py::test_committed_not_configured_limits_abort_before_any_mutation` fails: it expects `protection.max_unprotected_ms` among the NOT_CONFIGURED keys but the committed limits file now (after 24-06) holds only `stale_feed.max_user_data_silence_ms` as unset. It does not touch health code; `scripts/demo_rehearsal.py` is plan 24-29's file.

## Items for the orchestrator and later plans

- **Owner numbers missing (TBD):** no limits key exists for the maximum REST error rate (`LiveHealthThresholds.rest_max_error_rate`) or the maximum age of the latest database write (`db_write_max_age`). The producer takes them as required arguments with no default; plan 24-27 needs an owner-confirmed value (or new limits keys). `mark_price_max_age` comes from `stale_feed.max_mark_price_age_ms`, the skew from the ratified drift limits.
- **Kill-gate source for the DEMO enable:** `enable_demo` takes the `KillGateState` from the caller and refuses `None`. Nothing in `src` appends a `KILL_GATE` system-state row today (`PgSystemStateStore.latest_kill_gate_state()` returns None on a fresh database), so the start sequence (24-26) either needs a persisted evaluated state or an owner decision on a DEMO default; 24-01 Q5 recorded none and none was invented.
- **Wiring for 24-26/27:** feed `ReconcileObserver.note(report)` from the reconcile task, wrap REST-calling task bodies with `RestErrorCounter.wrap`, wrap the store journal writer with `DbWriteTracker.track`, call `TelegramDeliveryObserver.note_send_report(await drain_once(...))` and run `probe` once at start, construct `LiveHealthProducer(mode=..., demo_degraded_allowed=<True only in DEMO>)`, run `health_tick_once` and `kill_gate_tick_once` as scheduler bodies, call `start_disabled` then (after a first reconcile tick and a passing `health_tick_once`) `enable_demo`. The first tick before any tracked write, any send or any reconcile tick is correctly not OK (fail closed).
- **Journal volume:** the plan journals ten `HEALTH_CHECK` rows plus one `HEALTH_VERDICT` per health tick (the tick is the reconcile interval). If that is too much for the journal table, a change-only rule needs a decision.
- **LIVE row "blocks new entries once enabled":** no LIVE enable path exists (`enable_demo` raises in LIVE, LIVE_ORDERS_DISABLED stays) and the manager's gate was not changed, so nothing in this plan disables an enabled DEMO controller on a RED health tick. If that is wanted, it is a separate decision (health must then become a second automatic caller toward `disable()`).
- **DECISIONS:** D056's "Current state" text in `docs/DECISIONS.md` still describes the old behavior; a row/amendment (next free id D091) is for the orchestrator. Not written here.
- `controller.enable` and `controller.disable` journal synchronously on the loop thread through the controller's own journal (Phase 9 object); only the snapshot write goes through the StoreExecutor.

## Known Stubs

None.

## Threat Flags

None. T-24-65 (LIVE DEGRADED, flag in LIVE: verdict and constructor tests), T-24-66 (start disabled), T-24-67 (AST: enable only in `enable_demo`; kill gate only disables), T-24-68 (stale or missing mark refuses enable), T-24-SC (`git diff --exit-code -- pyproject.toml uv.lock` exits 0) are mitigated and tested.

## Self-Check: PASSED

- FOUND: src/live/health.py, src/live/enablement.py, tests/test_live_health.py, tests/test_live_enablement_wiring.py, src/ops/health.py, tests/test_execution_health.py
- FOUND commits e6eefc95, 2a2a447a (ancestors of HEAD)
