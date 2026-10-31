---
phase: 24-live-runtime-composition-demo
plan: 12
subsystem: live
status: complete
tags: [rest-gate, clock-drift-guard, composition, d-06, d-15, d083]
requirements-addressed: [EXEC-01, OPS-03]
requires: [24-03, 24-04]
provides:
  - "src/live/exchange.py: ExchangeBundle, build_exchange, remeasure_drift, GateAlert, gate_alert_adapter"
affects: [24-13, 24-26, 24-27]
tech-stack:
  added: []
  patterns:
    - "one construction site of the process-wide gate; behavioural propagation tests instead of identity-only checks"
    - "structured gate alert (event + deadline) instead of a message string"
key-files:
  created:
    - src/live/exchange.py
    - tests/test_live_exchange_wiring.py
  modified: []
key-decisions:
  - "The gate's string hook is wrapped by gate_alert_adapter into GateAlert(event, until_utc); plan 24-13 routes GateAlert to the sink/formatter, no text travels."
  - "live_enablement is an extra keyword of build_exchange (default None) so LIVE keeps the existing build_sdk_client refusal; TESTNET is refused."
  - "remeasure_drift does not take a cadence: the ratified periodic interval is applied by ClockDriftGuard.needs_remeasure; the scheduler (24-27) only chooses how often to poll the task."
plan_head_before: 18b04991c750901f9ff1fcde643df585653bc267
plan_head_after: dc11e21b922e9364230211dc1055a67beeb2709e
commits: 1
actuals:
  tokens: 16000
  tasks: 2
  commits: 1
completed: 2026-10-31
---

# Phase 24 Plan 12: Exchange composition (shared REST gate, drift guard) Summary

`build_exchange` composes the exchange edge of the live process: one durable `RestRateLimitGate` shared by the signed adapter, public reader, listen-key port and probe adapter, and a `ClockDriftGuard` that the adapter is always built with, so a 418 through any holder stops all of them and an unmeasured clock blocks `place_entry` before the SDK.

## What was built

- `build_exchange(*, mode, credentials, binance_limits, execution_limits, clock, sleep, gate_state_path, on_gate_alert, sdk_factory=None, live_enablement=None)`:
  - SDK client from `build_sdk_client` (or the injected factory) for REST + WS_STREAMS of one environment; TESTNET refused; the returned client's environment must equal `mode`.
  - `FileGateStateStore(gate_state_path)` and `RestRateLimitGate(policy, clock, state_store, on_alert, ban_end_clock_margin=execution_limits.rest_gate_ban_end_clock_margin)`. This is the single `RestRateLimitGate(` site under `src/live` (a test pins it).
  - `ClockDriftGuard(limits=binance_limits.drift)` and `BinanceUsdmAdapter(client, rest_gate, sleep, signed_call_policy, drift_guard, clock, on_clock_skew=guard.note_clock_skew_error)`: there is no parameter that builds the adapter without a guard.
  - `BinancePublicMarketData`, `SdkListenKeyPort`, `BinanceProbeAdapter` (all given the same gate) and the `ConfigurationWebSocketStreams` with the ratified SDK reconnect values.
  - `gate_state_path` must be an absolute `Path`, name a file and have an existing parent (`GateStatePathInvalid`); the build neither reads/writes the file nor restores the gate (start-sequence step 2, plan 24-26) and opens no socket.
- `remeasure_drift(bundle, *, clock_ms, now_utc)`: refreshes only when `needs_remeasure(now)`; a failed measure (including a gate refusal during a ban) is a failed verdict that keeps entries blocked; any other failure is logged by class name, requests a re-measure and returns None; cancellation propagates.
- `GateAlert` / `gate_alert_adapter`: parses the gate's `REST_GATE_BAN_ENTERED until_utc=<ISO>` and `REST_GATE_RECOVERY_REQUIRED` strings into a structured value (event, aware deadline or None).

## Verification

- `uv run pytest -m "not docker"` on tests/test_live_exchange_wiring.py (40 tests), tests/test_live_ast_guards.py, tests/test_gate_restore_bounds.py, tests/test_binance_usdm_signed_calls.py, tests/test_no_unratified_defaults.py, tests/test_binance_usdm_source_guard.py: all pass.
- Behaviour covered: a 418 from the adapter, public reader or listen-key port refuses the other two before the fake SDK; the probe adapter holds the same gate; fresh bundle `place_entry` raises `EntriesBlocked(NEVER_MEASURED)` with zero SDK calls and the same check detects an unguarded adapter (negative control); server time in limits allows entries, 2 s ahead keeps them blocked; -1021 returns the guard to STALE; D083 margin pads the body ban end and is off when unset; gate reports `NOT_RESTORED` (never `LEGACY_IN_MEMORY`) until restore and `RESTORED_DURABLE` after; one alert per 418 with the deadline; a lost state file alerts `REST_GATE_RECOVERY_REQUIRED`; a restart keeps the ban; DEMO builds through the real `build_sdk_client` without a connection; LIVE without an enabled controller raises `LiveNotEnabled`.
- `uv run mypy src/live` clean; scoped ruff check/format clean; `git diff --exit-code -- pyproject.toml uv.lock` exits 0; `git grep --cached -c "RestRateLimitGate(" -- src/live` is 1.
- Not run: PostgreSQL tests (none apply), the full suite (orchestrator).

## Deviations from Plan

None - plan executed as written. Both tasks share one file pair, so they were committed together in one commit rather than one per task.

## Notes for later plans

- Plan 24-13 (alerts): route `GateAlert` to `JournalFirstAlertSink.alert`. `ALERT_EVENTS` (src/ops/alerts.py) is a closed map with no REST-gate event, so a `REST_GATE_BAN_ENTERED` (and `REST_GATE_RECOVERY_REQUIRED`) entry plus Phase 23 wording is needed there; this plan did not touch `src/ops/alerts.py` (not in its files).
- Plan 24-26/27: call `bundle.gate_store.initialize` (first install only) then `bundle.gate.restore()` before any REST call; schedule `remeasure_drift` and pass the wall-clock `clock_ms`/`now_utc` from the process edge. No `LiveCadences` object exists yet, so the task takes no cadence argument.
- `ExchangeBundle.sdk` is the `SdkClientBundle`; the start sequence can use `binance_client.assert_environment(bundle.sdk)` as its guard.

## Known Stubs

None.

## Threat Flags

None. T-24-31 to T-24-33 are covered by the propagation, guard and durable-gate tests; T-24-SC: pyproject.toml and uv.lock unchanged.

## Self-Check: PASSED

- FOUND: src/live/exchange.py, tests/test_live_exchange_wiring.py
- FOUND: commit dc11e21b
