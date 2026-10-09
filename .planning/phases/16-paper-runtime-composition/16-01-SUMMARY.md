---
phase: 16-paper-runtime-composition
plan: 01
subsystem: paper-runtime / binance-ws-adapter
tags: [binance-sdk, websocket, asyncio, contract-test, fakes, determinism]

requires:
  - phase: 07-paper-loop
    provides: PaperWsAdapter, Kline dataclass, hardened per-message dispatch (CR-04)
provides:
  - "async PaperWsAdapter on the installed SDK shape: connect, subscribe, unsubscribe, close, on_connection, rebuild, last_rebuild, diagnostics"
  - "tests/paper_ws_fakes.py: SDK-shaped fake client and handle, make_kline_model built from SDK model classes, fresh_sdk_stream_map isolation helper"
  - "tests/test_paper_ws_contract.py: network-free contract test with negative controls"
affects: [16-08 supervisor rewrite, 16-17 live smoke, 16-21 live proof, 16-26]

actuals:
  tokens: 13500
  tasks: 3
  commits: 5
plan_head_before: 17fd942fb263e856c26b8e83b969adf1c39f0e5c
plan_head_after: 8bcb863f52d08c9c86de374b048cb86baaf781b8
commits: 5

tech-stack:
  added: []
  patterns:
    - "SDK-shaped fakes bound to the installed package by an introspection contract test with a negative control"
    - "Adapter reports SDK state through frozen value types (RebuildReport, WsDiagnostics); no SDK type leaves the module"
    - "SDK module-global state (stream map) isolated per test via monkeypatch, read at call time by adapter and fakes"

key-files:
  created:
    - tests/paper_ws_fakes.py
    - tests/test_paper_ws_contract.py
  modified:
    - src/adapters/paper_ws.py
    - tests/test_paper_ws_connect.py

key-decisions:
  - "SDK owns reconnection and rotation; the adapter adds no rotation timer and no handle-level reconnect/close (research D1, D2, P3)"
  - "rebuild() is the only recovery path for an unsolicited close; it removes only the adapter's own stream names from the SDK global map"
  - "connect() fails loudly (ConnectionError + paper_ws.connect_failed) when the SDK produced no connection (D4)"
  - "Connection callbacks are recorded by the adapter and re-applied after connect/rebuild because the SDK drops a callback registered with no connection"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "Adapter awaits create_connection and kline_candlestick_streams, passes plain-string interval and PROD stream_url, delivers a closed kline model as a frozen Kline with Decimal prices and UTC times"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_connect.py#test_closed_kline_model_reaches_caller_as_frozen_kline"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_connect.py#test_subscribe_passes_lowercase_symbol_and_plain_string_interval"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_connect.py#test_connect_awaits_create_connection_once_with_prod_stream_url"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every WS fake mirrors the installed SDK async surface; a synchronous fake or a fictional-API handle makes the contract test fail"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_contract.py#test_negative_control_synchronous_fake_is_rejected"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_contract.py#test_every_fake_mirrors_the_installed_sdk_async_surface"
        status: pass
    human_judgment: false
  - id: D3
    description: "Connect failure detection, connection events, unsubscribe/close, rebuild after an unsolicited close, distinguishable close paths via last_rebuild, read-only diagnostics"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_connect.py#test_rebuild_after_unsolicited_close_resubscribes_own_streams_only"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_connect.py#test_unsolicited_and_user_initiated_close_paths_are_distinguishable"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_connect.py#test_connect_without_any_sdk_connection_raises_and_logs"
        status: pass
    human_judgment: false
  - id: D4
    description: "The rebuild recovery against a real Binance connection (forced disconnect) behaves as derived from the SDK source"
    requirement: PAPER-01
    verification: []
    human_judgment: true
    rationale: "rebuild() and _forget_own_streams() are derived from reading binance_common 4.4.0 (research D3); only the live smoke of plans 16-17/16-21 can prove them against the exchange (SC9: fake-level green never closes PAPER-01)"

duration: 14min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 01: Paper WS adapter on the real SDK shape Summary

**Async `PaperWsAdapter` that awaits the installed Binance SDK coroutines with a plain-string interval and the PROD stream URL, detects a silent failed connect, can rebuild after an unsolicited close (reporting which close path it saw), and is covered by SDK-bound fakes with a contract test and negative controls.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-10-09T02:50:14Z
- **Completed:** 2026-10-09T03:04:00Z
- **Tasks:** 3 (Task 1 tracer, Tasks 2 and 3 auto, all TDD)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- Tracer: awaited `connect` and `subscribe` deliver one closed `KlineCandlestickStreamsResponse` end to end as a frozen `Kline` (Decimal prices, UTC times exact to the millisecond), interval passed as the plain string `1h`, default configuration carries `DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL`. The SDK interval Enum import and `_INTERVAL_TO_ENUM` table are gone; `ALLOWED_INTERVALS = {1m, 1h, 4h}`.
- Contract test binds the fake client and handle to the installed SDK (coroutine-ness, parameter names, handle public members exactly `{on, unsubscribe}`) and proves the check bites through two negative controls (a synchronous fake, a fictional `on_message`/`reconnect` handle).
- Lifecycle on the real shape: `ConnectionError` plus `paper_ws.connect_failed` when `ws.connections` is empty after `create_connection` (D4), `on_connection` limited to open/reconnect/close/error, `unsubscribe(handle)`, `close()`, `rebuild()` with `last_rebuild: RebuildReport`, read-only `diagnostics() -> WsDiagnostics`, SDK stdlib log records bridged to structlog. `reconnect`, `schedule_reconnect` and handle-level `close` are removed.

## RED Evidence (Task 1)

Commit `dd20179` (tests only) against the pre-change adapter, `.venv/Scripts/python -m pytest tests/test_paper_ws_connect.py -q -p no:cacheprovider`: 9 failed, 0 passed. Representative failure: `RuntimeError: WS handle coroutine has no on_message; dispatch unwired (pre-soak wiring required)` plus `RuntimeWarning: coroutine 'FakeSdkWsClient.kline_candlestick_streams' was never awaited` (the old adapter never awaited the SDK call). The Task 3 RED commit `1adf2cc` also failed (18 failing tests) before the implementation commit `8bcb863`. After GREEN: 34 passed across `tests/test_paper_ws_connect.py` and `tests/test_paper_ws_contract.py`.

## Task Commits

1. **Task 1 (tracer): awaited connect and subscribe** - `dd20179` (test, RED), `d15e07d` (feat, GREEN)
2. **Task 2: contract test with negative control** - `084251d` (test)
3. **Task 3: adapter lifecycle, rebuild, diagnostics** - `1adf2cc` (test, RED), `8bcb863` (feat, GREEN)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified

- `src/adapters/paper_ws.py` - async adapter, `RebuildReport`, `WsDiagnostics`, `install_sdk_log_bridge`, `ALLOWED_INTERVALS`, `LIFECYCLE_EVENTS`
- `tests/paper_ws_fakes.py` - `FakeSdkWsClient` (mirrors SDK discard vs user-initiated close paths and the skip-already-mapped-stream subscribe), `FakeStreamHandle`, `FakeConnection`, `make_kline_model`, `fresh_sdk_stream_map`
- `tests/test_paper_ws_connect.py` - rewritten around the SDK-shaped fakes (tracer behaviours, retained CR-04 dispatch hardening, Task 3 lifecycle)
- `tests/test_paper_ws_contract.py` - new contract test

## Decisions Made

- The SDK owns rotation and reconnection; no parallel rotation timer (avoids two rotation owners, research P3).
- `rebuild()` order: record the report from the SDK map and connection count first, best-effort `close_connection()` of the dead client (releases surviving sockets and the aiohttp session), `_forget_own_streams()`, fresh client from the stored configuration, `connect()`, replay of recorded subscriptions with their original callbacks.
- Added a `client_factory` constructor argument (default: the SDK class) so `rebuild` can build a fresh client and tests can inject SDK-shaped fakes without patching.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug in plan assumption] `global_stream_connections` is not a dict**
- **Found during:** Task 2 / Task 3 (reading `binance_common/websocket.py` lines 43-47)
- **Issue:** The plan and research call it a "module-level dict". In the installed `binance_common` 4.4.0 it is a `StreamConnectionsMap` object whose `stream_connections_map` attribute is the dict.
- **Fix:** The contract test pins `global_stream_connections.stream_connections_map` as a dict; the adapter edits that inner dict through `_sdk_stream_map()`, looked up through the module at call time so tests can swap it.
- **Files modified:** tests/test_paper_ws_contract.py, src/adapters/paper_ws.py, tests/paper_ws_fakes.py
- **Verification:** `test_sdk_global_stream_map_exists`, rebuild tests pass
- **Committed in:** 084251d, 8bcb863

**2. [Rule 2 - Missing critical functionality] Connection callbacks recorded and re-applied**
- **Found during:** Task 3 (SDK `on_connection` source)
- **Issue:** The SDK `on_connection` registers only on existing connections and logs a warning otherwise; a callback registered before `connect()` or on a rebuilt client would be silently lost.
- **Fix:** The adapter records `(event, callback)` pairs and re-applies them after every successful `connect()` (including inside `rebuild()`); tests cover pre-connect registration and re-application on the rebuilt client.
- **Files modified:** src/adapters/paper_ws.py, tests/test_paper_ws_connect.py
- **Committed in:** 1adf2cc, 8bcb863

**3. [Rule 2 - Missing critical functionality] `unsubscribe` removes the replay record**
- **Found during:** Task 3
- **Issue:** Without it `rebuild()` would resurrect a stream the caller had deliberately unsubscribed.
- **Fix:** Subscriptions are recorded with their handle; `unsubscribe(handle)` drops the record after awaiting the SDK handle. Covered by `test_rebuild_does_not_resubscribe_an_unsubscribed_stream`.
- **Committed in:** 1adf2cc, 8bcb863

**4. [Rule 3 - Blocking] Untyped SDK call under mypy strict**
- **Found during:** Task 1
- **Issue:** `create_connection` is untyped in the SDK; mypy strict raised `no-untyped-call`.
- **Fix:** Single targeted `# type: ignore[no-untyped-call]` with a reason comment (`warn_unused_ignores` is on, so it is verified used).
- **Committed in:** d15e07d

### Plan-shape choices (not defects)

- `FakeSdkWsClient.create_connection` appends three connection stand-ins (market, public, private) instead of the plan's single sentinel, to mirror research D5; Test 1 still asserts exactly one awaited `create_connection`, and `diagnostics.connection_count` is asserted equal to the number the fake created.
- `simulate_unsolicited_close()` removes only the market connection (the SDK discards just the dead one), so `connections_before` after an unsolicited drop is 2 and `connections_after` is 3.
- `rebuild()` returns `None`; the report is read through `adapter.last_rebuild` as specified.

---

**Total deviations:** 4 auto-fixed (1 Rule 1, 2 Rule 2, 1 Rule 3). **Impact:** All necessary for correctness against the installed SDK; no scope creep, no package installed, `uv.lock` unchanged.

## Issues Encountered

None blocking. A first attempt to append the Task 3 tests via a shell heredoc failed on quoting before any file was written; the tests were then added from a scratch file and verified.

## WS Fakes Left For Plan 16-08

`grep -rn "on_message|kline_candlestick_streams|schedule_reconnect|def reconnect|def close" tests` found two remaining fakes that stand in for `PaperWsAdapter` itself at the supervisor boundary (synchronous `subscribe` / `reconnect(handle)` / `close(handle)`, matching the supervisor's `WsAdapterLike` protocol), not for the SDK:

- `tests/test_paper_supervisor_backfill.py` - class `_FakeWsAdapter` (lines 65-95)
- `tests/test_paper_resync.py` - class `_FakeWsAdapter` (lines 467-493)

Both are owned by plan 16-08 (supervisor rewrite). Until then `src/paper/supervisor.py` `WsAdapterLike` (sync, `reconnect`, `close(handle)`) no longer matches `PaperWsAdapter` structurally; nothing in `src/` constructs the supervisor with the real adapter, and the supervisor tests pass because they use their own fakes (`tests/test_paper_supervisor_backfill.py`, `tests/test_paper_resync.py`, `tests/test_domain_no_float.py` re-run green). `tests/test_demo_rehearsal_flow.py` `close` is an unrelated Telegram notifier fake.

## Known Stubs

None. `rebuild()` and `_forget_own_streams()` are real code, but UNVERIFIED against a real exchange until plan 16-21 (documented in the docstring and in coverage D4).

## Threat Flags

None. No new network endpoint, auth path or schema; the adapter touches no order or account endpoint. T-16-01 (silent dead stream) mitigated by the connect check and test; T-16-02 normalisation kept unchanged; T-16-03 mitigated by `_forget_own_streams()` plus the foreign-entry-preserved assertion and the contract pin; T-16-SC accepted, no install.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 16-08 can build the supervisor on `PaperWsAdapter.on_connection`, `rebuild` and `last_rebuild`, and reuse `tests/paper_ws_fakes.py`.
- Plans 16-17 and 16-21 must exercise a forced disconnect live and copy `last_rebuild` and `diagnostics()` into their evidence; fake-level green here never closes PAPER-01 (SC9).

---
*Phase: 16-paper-runtime-composition*
*Completed: 2026-10-09*

## Self-Check: PASSED

All four source/test files and this SUMMARY exist; commits dd20179, d15e07d, 084251d, 1adf2cc, 8bcb863 found in git log; 34 tests pass; ruff check and mypy src clean.
