---
phase: 25-demo-integration-test-campaign
plan: 09
subsystem: demo-scenario-harness
tags: [D-04, D-08, demo-env, programmatic-owner, crash-cut, evidence-index, tdd, OPS-02, APRV-01, EXEC-01]
requires: [25-01, 25-02, 25-08]
provides:
  - "tests/support/demo_scenarios/demo_env.py: build_demo_scenario_env, DemoScenarioEnv, ProgrammaticOwner, RecordingBot, abandon, SessionEvidence, GateInitializer"
  - "tests/demo/conftest.py: scenario_recorder and make_demo_env fixtures (plan 25-08 contract), session index finalizer, the plan 25-01 guard"
  - "tests/demo/test_demo_s01_happy.py: the owner's first campaign step, S01 on Demo"
affects: [25-10, 25-11, 25-12, 25-13, 25-14, 25-15, 25-16]
tech-stack:
  added: []
  patterns:
    - "the Demo env mirrors default_assemble and adds only the three existing build_wiring seams"
    - "presses go through wiring.runner.handler with the admitted authorized chat id and smallest user id"
    - "a crash cut is abandon(): cancel the scheduler, stop the stream with the listenKey kept, no drain"
    - "refusals name variables only and come before any build, engine or network call"
key-files:
  created:
    - tests/support/demo_scenarios/demo_env.py
    - tests/test_demo_env_factory.py
    - tests/demo/test_demo_s01_happy.py
  modified:
    - tests/demo/conftest.py
key-decisions:
  - "SdkFaults.wrap_factory assigns client.rest_api, but the real DerivativesTradingUsdsFutures.rest_api is a read-only property (checked in the installed SDK): a plain wrap would raise AttributeError on the first owner run. demo_env wraps the real client in a small forwarding shim with a settable rest_api (_FaultableClient) after demo_guarded_sdk_factory has re-checked the host. fault_edge.py and src are untouched."
  - "The programmatic press carries message_id=None: a real chat card has an id this process never saw, and message_id=1 would make the confirm card edit fail on real Telegram. With None the approval flow takes its existing fallback (the confirm card is sent as a new message) and the final-edit step is skipped as an inaccessible message."
  - "The operator reply token is read from a RecordingBot (forwarding wrapper handed to build_wiring as bot=), recorded before the forward so a failed send still yields the token; never from Telegram history, and the list is never written to evidence."
  - "abandon() also stops the Telegram polling task (runner.stop, best effort): a dead process holds no getUpdates, and the second process must be able to poll. It still runs no service.drain, no persistence drain and no shutdown_in_order."
  - "initialize_gate_state is handed out once per session (GateInitializer, env TRADING_DEMO_INITIALIZE_GATE_STATE=1): the start sequence refuses the flag when a gate state file exists, so a second make_demo_env or a restart must start plain."
  - "A session id that equals an earlier one of the same env (two processes in the same second after a crash cut) is bumped by one second, keeping the production strftime format."
  - "SessionEvidence.finish() writes a recorder the test never wrote (outcome FAILED) before the index, so a failing owner run keeps its evidence."
requirements-completed: [OPS-02, APRV-01, EXEC-01]
status: complete
duration: 45min
completed: 2026-11-07
commits: 4
plan_head_before: 986f7f5ed5048d2e735917a25dd120b1462e312f
plan_head_after: 0c9daf50a3fe1af2d2939569bc6b4102d0dbae73
actuals:
  tokens: 13400
  tasks: 2
  commits: 4
---

# Phase 25 Plan 09: Demo env factory, fixtures and S01 demo test Summary

The owner-run side of the scenario harness: the real live process on Binance Demo, composed through the production assembly path with only the test seams added, a programmatic owner that presses through the runner's handler, a crash-cut `abandon`, the plan 25-08 fixture contract and one evidence index per owner session. Nothing under `src`, `scripts`, `pyproject.toml` or `uv.lock` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): Demo env factory, refusals, programmatic owner, crash cut | a0b3f5c3 | 7ebd8c89 |
| 2: fixtures, session index, S01 demo test | bb13bf77 | 0c9daf50 |

## API for plans 25-10 to 25-16

`from tests.support.demo_scenarios.demo_env import ...`

| Name | Behavior |
|---|---|
| `build_demo_scenario_env(recorder, options, *, environ, clock=None, sleep=None, initialize_gate_state=False, approval_timeout_seconds=300)` | sync; returns `DemoScenarioEnv` (a `SmokeEnv` plus `faults`, `sdk_faults`, `store_faults`, `abandon()`); `synthetic` False, `label` DEMO_OBSERVED; omitted fault objects are fresh; `options.clock_offset` is added to the process clock |
| refusals | `DemoRunRefused` (names only) from `assert_demo_run_environment` (LIVE name, xdist, `TRADING_DEMO_RUN`, non-DEMO mode), a missing `DATABASE_URL_SYNC`/`DATABASE_URL`, or an unknown `TRADING_DEMO_OWNER`; all before `make_sync_engine` or `build_wiring` |
| assembly | `build_wiring(config, execution_limits=config.limits, binance_limits from REPO_ROOT / BINANCE_LIMITS_RELATIVE, parameter_set of STRATEGY_ID/PARAMETER_SET_ID, symbols=DEMO_SYMBOLS, application_factory (PTB), bot=RecordingBot(LiveBotProxy()), engine=make_sync_engine(url), stores=store_faults.wrap(build_pg_stores(...)), sdk_factory, exchange_edge=faults.install)` |
| `ProgrammaticOwner.act` | `approve`, `replay_approve` (APR), `confirm`, `confirm_refused`, `replay_confirm` (CNF, then `service.drain()`), `safemode_exit` (operator command, token from the bot channel, then `/confirm`); unknown action `ValueError`; missing token `ProgrammaticOwnerError` |
| `TRADING_DEMO_OWNER=console` | `dr.ConsoleOwner(recorder, notify=)` instead |
| `env.restart()` | `make(False)`: a second process over the SAME engine, wrapped stores and fault objects (the edge is re-bound by `install`) |
| `env.abandon()` / `abandon(assembly)` | crash cut (see key-decisions); no-op on an assembly that never completed |
| `SessionEvidence(evidence_dir, *, environ, clock)` | `.recorder(scenario_id)` EXECUTE-mode recorder whose `write()` defaults to the evidence dir and is tracked; `.finish()` writes unwritten recorders then `write_session_index` |
| fixtures (`tests/demo/conftest.py`) | `scenario_recorder(scenario_id)`, `make_demo_env(recorder, options=None)` (async), session-scoped `demo_session_evidence` whose teardown writes the index |

Owner variables: `TRADING_DEMO_RUN=1`, `TRADING_DEMO_OWNER=console|programmatic`, `TRADING_DEMO_INITIALIZE_GATE_STATE=1` (first env of the session only), a database URL variable.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_env_factory.py tests/test_demo_marker_guard.py tests/test_demo_same_code_path.py tests/demo -x -q -rs`: 130 passed, 2 skipped (both tests under `tests/demo` reported skipped, none passed). `TRADING_CI_STRICT=1` collection of `tests/demo` also exits 0 with both skipped.
- Also green: `tests/test_demo_harness.py`, `test_demo_evidence_index.py`, `test_demo_twin_s01_happy.py`, `test_demo_env_guard.py`.
- Scoped `ruff check` and `ruff format --check` on the four files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock` exits 0. The constants acceptance one-liner exits 0.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read.

## Deviations from Plan

None in scope. The additions inside the plan's latitude are listed under key-decisions (the settable-`rest_api` shim, `message_id=None`, `runner.stop` in `abandon`, once-per-session gate initialization, session id bump, FAILED evidence for an unwritten recorder). The S01 demo test accepts `COMPLETE` and `COMPLETE_WITH_GAPS` (the smoke's own two success outcomes) instead of `COMPLETE` only, because a gap is an attestation the smoke could not make, recorded in the evidence, not a failure of the harness. The S01 demo test does not call `abandon()`: `run_composed_smoke` already stops the running process in order whatever happens.

The `SessionEvidence` class landed in the Task 1 GREEN commit with `demo_env.py`; its tests arrived in the Task 2 RED commit (so those tests were green on arrival; the three structural AST tests were the RED ones).

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`), because agents never connect to Demo, PostgreSQL or Telegram:

- `make_sync_engine`, `build_pg_stores(OperationalDatabase(engine))`, the PTB `application_factory` and the real SDK client are stubbed or never invoked in tests; `build_wiring` is stubbed. That the assembled process starts and reaches LIVE on Demo is shown only by the owner's S01 run.
- The `_FaultableClient` shim is tested against a stand-in with a read-only `rest_api` property, not against the real `DerivativesTradingUsdsFutures`. It assumes the SDK's `rest_api` property returns a stable object and that no src code type-checks the client (a grep of `src` found none).
- A programmatic CONFIRM runs immediately after APPROVE with `message_id=None`; whether the real confirm flow accepts it exactly as a human tap (timing, final-edit skipped) is unobserved. `TRADING_DEMO_OWNER=console` is the fallback.
- `abandon()` against a real stream supervisor and the real PTB runner (the crash cut cancelling the real scheduler task, stopping real polling) is tested with stubs only; the listenKey singleton behavior on the second process is from the Binance docs (25-RESEARCH Pattern 4), unobserved.
- The `demo_run_guard` / `make_demo_env` / `demo_session_evidence` fixtures themselves are checked by AST (names, calls, S01 test requesting both) and the session class by unit tests; the pytest fixture wiring first executes in the owner's run (same limit as plan 25-01's guard fixture).
- `clock_offset` shifts the process clock only; the drift guard's reaction on Demo is S09's to observe.

## Known Stubs

None.

## Threat Flags

None. T-25-21 (admission, Demo-guarded SDK factory with host re-check kept underneath the proxy, refusal tests before `build_wiring`), T-25-22 (presses through `runner.handler` with the admitted authorized ids, asserted), T-25-23 (refusals name variables only with sentinel assertions; evidence through `EvidenceRecorder` scrub; the `RecordingBot` list is never written) and T-25-SC (no package added) hold.

## Self-Check: PASSED

All four files exist; commits a0b3f5c3, 7ebd8c89, bb13bf77 and 0c9daf50 are ancestors of HEAD; `git rev-list --count 986f7f5e..0c9daf50` is 4.
