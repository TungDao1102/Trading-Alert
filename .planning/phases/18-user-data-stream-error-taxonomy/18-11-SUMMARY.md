---
base: 529fb48a659cf13247c17d4f878d2ba79e56a164
phase: 18-user-data-stream-error-taxonomy
plan: 11
subsystem: adapters/user-data-stream
status: complete
tags: [adapter, sdk, user-data-stream, listenKey, redaction, contract-tests, D-01, D-02, EXEC-05, OPS-02, T-18-28, T-18-29, T-18-30, T-18-31]
requires: [18-03, 18-04, 18-05, 18-07]
provides:
  - src/adapters/binance_userdata.py (ListenKeyPort, UserDataTransport, SdkListenKeyPort, ListenKeyError, ListenKeyInvalid, ListenKeyTransient, ListenKeyFailure, ConnectionEvent, TransportDiagnostics, SdkUserDataTransport, QueuedStreamItem, UserDataAdapter, capture_raw_user_events, SdkNoiseGuard, install_sdk_noise_guard, install_sdk_log_bridge, CONNECTION_EVENTS, PRIVATE_URL_PATH)
  - tests/userdata_fakes.py (FakeConnection, FakeUserStreamHandle, FakeUserDataWsClient, FakeRestUserDataApi, make_order_trade_update_message, make_raw_dict_message, TEST_ONLY_LISTEN_KEY, TEST_ONLY_SECOND_LISTEN_KEY)
  - tests/test_userdata_adapter.py, tests/test_userdata_contract.py
affects:
  - plan 18-14 (supervisor drives start, keepalive, rekey, rebuild, stop; adds the required rest_gate keyword to SdkListenKeyPort and check/record inside _rest_call)
  - plan 18-15 (router consumes QueuedStreamItem from the adapter queue)
  - plan 18-18 (live smoke settles whether SUBSCRIBE with a bare listenKey delivers; capture_raw_user_events is the raw tap)
  - plan 18-19 (a direct transport implements the UserDataTransport Protocol, including resubscribe and the name-only connection sink)
tech-stack:
  added: []
  patterns:
    - SDK-shaped fakes built from the installed SDK models, bound to the SDK by introspection-only contract tests with negative controls
    - listenKey registered with the redactor on receipt and as the first statement of every transport entry point taking a key
    - single private REST call site (_rest_call) per port, the SDK exception dropped before the translated one is raised
key-files:
  created:
    - src/adapters/binance_userdata.py
    - tests/userdata_fakes.py
    - tests/test_userdata_adapter.py
    - tests/test_userdata_contract.py
  modified: []
decisions:
  - "The transport's connection sink receives only the event name; the adapter builds ConnectionEvent(name, at_utc, epoch) because the clock and the epoch live in the adapter (the transport constructor has no clock)"
  - "UserDataTransport gains resubscribe(listen_key), needed by rekey to subscribe a new key on the existing private connection; it registers the key first and raises ConnectionError when no private connection is open"
  - "rekey forgets the old listenKey name without sending UNSUBSCRIBE: the old key is either dead (-1125 or expiry) or identical to the new one, and an UNSUBSCRIBE of a listenKey is not documented in anything read"
  - "The three listenKey exceptions share a base ListenKeyError(category, retry_after_seconds) whose message names the category only; the translated exception is raised outside the except block so neither __cause__ nor __context__ holds the SDK exception"
  - "A start response without a key raises ListenKeyFailure(UNKNOWN_EXCHANGE_ERROR, None)"
  - "TransportDiagnostics reports stale_listen_key_names_found as a count, because a stale name is a listenKey (a credential)"
  - "SdkNoiseGuard also suppresses the SDK INFO line 'Sending message to WebSocket' (its SUBSCRIBE params are the listenKey); an SDK INFO record whose message cannot be read is suppressed and counted (fail closed)"
  - "The user-data SDK log bridge scrubs the message itself before handing it to structlog, in addition to the structlog redact_processor"
  - "capture_raw_user_events reads and replaces binance_common.websocket.parse_user_event by name (getattr/setattr) because the SDK does not re-export it (mypy attr-defined)"
metrics:
  duration: 15min
  completed: 2026-10-16
estimate:
  tokens: 106000
  tasks: 3
actuals:
  tokens: 27100
  tasks: 3
  commits: 3
plan_head_before: 529fb48a659cf13247c17d4f878d2ba79e56a164
plan_head_after: 845ae59ae0b0c4ce59ad5455ca201d56df7fde03
---

# Phase 18 Plan 11: SDK User-Data Adapter, listenKey Port and SDK Contract Pins Summary

An SDK `OrderTradeUpdate` model, delivered by an SDK-shaped fake streams client through the real callback shape (`UserDataStreamEventsResponse`), now becomes an `OrderUpdateEvent` on a `StreamLimits`-bounded queue and, through `to_fill_event`, a `FillEvent`. No SDK type leaves `src/adapters/binance_userdata.py`. The module also has the listenKey REST port, which makes one SDK call per invocation with no retry and reports a 429 or 418. It registers the listenKey with the redactor before any path-form URL can be logged. It also provides the private-connection event fan-in with an epoch, a rebuild that forgets only its own stale name, rekey, stop, queue overflow accounting, a raw-frame tap and two SDK log guards. Offline contract tests pin every SDK internal the adapter relies on.

Plan revision: revised 2026-10-16 (twice) to register the listenKey before any path-form URL (`/private/ws/<listenKey>`) can be logged, with the captured-log tests; the shared `RestRateLimitGate` is wired into `SdkListenKeyPort._rest_call` by plan 18-14, not here.

## Performance

- Duration: about 15 minutes (2026-10-16T05:56Z to 06:11Z)
- Tasks: 3 of 3
- Files: 4 created, 0 modified

## Task Commits

1. Task 1 (tracer): an SDK OrderTradeUpdate from a fake streams client becomes a queued OrderUpdateEvent and a FillEvent: `47fcda7`
2. Task 2: listenKey REST port with redaction, connection fan-in with an epoch, rebuild with stale-name forgetting, overflow, raw tap and SDK log guards: `af1ffa2`
3. Task 3: offline contract tests pinning every SDK internal: `845ae59`

Plan 18-10 ran on the same branch at the same time, so the ledger range `529fb48..845ae59` holds 6 commits. Three of them belong to 18-11 (`git log --grep="(18-11)"`), and `commits: 3` counts only those. The base `529fb48` is the 18-10 tracer commit, which was HEAD when this plan started.

## What Was Built

- `SdkUserDataTransport(configuration, client_factory=None, ws_client=None)` does the following:
  - `connect(listen_key)` registers the key, installs the log bridge and the noise guard, then awaits `create_connection`.
  - When no `/private` connection exists it raises `ConnectionError` with no URL in the message. Otherwise it awaits `user_data(listen_key)` and calls `handle.on("message", ...)`.
  - It registers connection callbacks for open, reconnect, close, error, ping and pong on the private connection only. They are built once with `functools.partial`, so the SDK's duplicate check also holds after a reconnect.
  - `resubscribe`, `rebuild`, `close`, `private_connection_open` and `diagnostics` complete the transport.
- `SdkListenKeyPort(rest_api)`:
  - `start`, `keepalive` and `close` go through `_rest_call`, the only `asyncio.to_thread` site. It makes one SDK call and never loops or sleeps.
  - Errors are classified with `CallKind.LISTEN_KEY`. INVALID_LISTEN_KEY becomes `ListenKeyInvalid`. RATE_LIMITED and STATUS_UNKNOWN become `ListenKeyTransient`. IP_BANNED, auth and unknown errors become `ListenKeyFailure`. The category and `retry_after_seconds` are carried; the SDK text is not.
  - The key is registered before `start` returns. A keepalive response that carries a key is registered too.
- `UserDataAdapter(*, transport, listen_keys, limits, clock)`:
  - The raw callback calls `parse_stream_message` with the injected clock. A parser exception becomes a MALFORMED_PAYLOAD anomaly, and anything unrecognisable becomes an UNRECOGNIZED_ENVELOPE anomaly. It enqueues `QueuedStreamItem(outcome, received_at_utc, connection_epoch)`. When the queue is full it counts the loss and sets `overflowed`. It never raises.
  - `start`, `keepalive`, `rekey` (new key; resubscribe on an open connection, otherwise rebuild), `rebuild` and `stop(*, close_listen_key)` (no default, idempotent) increase `epoch` where the plan says.
  - It also exposes `set_connection_listener`, `private_connection_open`, `queue`, `overflowed`, `overflow_count` and `clear_overflow`.
- `capture_raw_user_events(sink)` wraps the module global `parse_user_event` of `binance_common.websocket`. The sink gets a deep copy, the original function still runs, and the wrapper is restored on exit.
- `SdkNoiseGuard` and `install_sdk_noise_guard()` add an idempotent root-logger filter that drops SDK INFO lines carrying account data or a key, and counts them.
- `install_sdk_log_bridge()` is idempotent. It forwards SDK WARNING+ records to the structlog event `userdata.sdk_log` with the message scrubbed.

## Verification

- Plan verification: `uv run pytest -m "not docker" tests/test_userdata_adapter.py tests/test_userdata_contract.py tests/test_userdata_events.py tests/test_userdata_parsers.py tests/test_paper_ws_contract.py tests/test_paper_ws_connect.py -x` gave 480 passed. Of these, `tests/test_userdata_adapter.py` has 67 tests and `tests/test_userdata_contract.py` has 24.
- Task 1 verify (adapter, events, Phase 16 paper_ws connect): 156 passed. The Phase 16 tests still pass, so the shared SDK stream map was not disturbed.
- `uv run mypy src`: no issues in 195 files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 580 files formatted. `uv lock --check`: resolved, unchanged. All commands ran with `UV_OFFLINE=1 ... --frozen --extra dev`, and the full suite was not run.
- Mutation check: with `register_runtime_secret` moved after `create_connection` in `connect`, `test_transport_registers_key_before_connect_logs` and the first-statement AST test both fail. The module was restored afterwards.
- Path-form tests:
  - `test_path_form_url_not_caught_by_shape_rule_alone` is the negative control: with nothing registered, the key survives `scrub`.
  - `test_listen_key_registered_on_start_before_return` covers stdlib output and the bridge's structlog output.
  - `test_transport_registers_key_before_connect_logs` covers a key that only `connect` ever sees, with the fake logging the URL the way the SDK logs a swallowed connect failure.
  - `test_transport_registers_key_before_rebuild_logs` and `test_rekey_registers_the_new_key_before_subscribe_logs` cover the same for rebuild and rekey.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Security] SdkNoiseGuard suppresses a third SDK INFO prefix**
- Found during: Task 2
- Issue: the SDK's `send_message` logs `Sending message to WebSocket <id>: {...'params': [<listenKey>]...}` at INFO. Its `redact_sensitive_info` masks only `apiKey` and `signature`, so the listenKey appears in plain text.
- Fix: added "Sending message to WebSocket" to the suppressed prefixes, alongside the two the plan names. An unreadable SDK INFO record is now suppressed (fail closed).
- Files: src/adapters/binance_userdata.py, tests/test_userdata_adapter.py
- Commit: af1ffa2

**2. [Rule 3 - Blocking] `UserDataTransport.resubscribe` added to the Protocol**
- Found during: Task 2
- Issue: `rekey()` has to subscribe a new key on the existing private connection, and the Task 1 Protocol had no operation for that.
- Fix: added `async resubscribe(listen_key)`. Like `connect` and `rebuild`, it registers the key as its first statement; the AST test checks all three.
- Commit: af1ffa2

**3. [Rule 3 - Blocking] The transport's connection sink takes an event name, not a ConnectionEvent**
- Found during: Task 2
- Issue: the transport has no clock and no epoch, because its constructor is fixed by the plan.
- Fix: the transport forwards the name and the adapter builds `ConnectionEvent(name, at_utc, epoch)`.
- Commit: af1ffa2

**4. [Rule 3 - Blocking] mypy rejects `binance_common.websocket.parse_user_event`**
- Found during: Task 2
- Issue: mypy reports `parse_user_event` as not explicitly exported by `binance_common.websocket`.
- Fix: the tap reads and replaces it by name. The contract test pins that it is the `binance_common.utils` function, called by name from the receive loop.
- Commit: af1ffa2

**5. Test-fixture sequencing**
- `tests/userdata_fakes.py` was written in full in the Task 1 commit, including the Task 2 REST fake, the connection-event helpers and `simulate_unsolicited_close`. Task 2 added only the `on_user_data` hook.

## Additional contract pins (beyond the plan's list)

- `WebSocketConnection.__init__` sets `self.is_open = True`, which `private_connection_open` reads.
- `_discard_connection` does not forget stream names, but the user-initiated `_close_one` does. This asymmetry is what rebuild relies on.
- The streams client opens `market`, `public` and `private` connections.
- `_invoke_connection_callback` trims arguments to the callback signature, so no ping, pong or error payload reaches the adapter.
- `_wrap_raw_payload` holds the raw-dict fallback.
- `global_user_stream_connections` exists.

## SDK delta

None. Every SDK fact the plan and research relied on matched the installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0 and `binance-common` 4.4.0. These are files read offline; how the SDK behaves live against Binance is settled by plan 18-18.

## Known Stubs

None. The `rebuild` placeholder of the Task 1 commit was replaced by the implementation in Task 2.

## Threat Flags

None. No network endpoint, auth path, schema or file access was added. T-18-28, T-18-30 and T-18-31 are mitigated as the threat register says. For T-18-29 the adapter makes no liveness claim.

## Open Issues and Notes for Later Plans

- Plan 18-14 adds the required `rest_gate` keyword to `SdkListenKeyPort` and the `check()` / `record()` calls in `_rest_call`. The port constructions in `tests/test_userdata_adapter.py` (12 occurrences of `SdkListenKeyPort(`) gain that keyword.
- Plan 18-19:
  - `DirectUserDataTransport` must implement `resubscribe(listen_key)`. Rebuilding with the new URL is enough.
  - It reports connection events as names (`str`) to the connection sink, not as `ConnectionEvent` objects. This differs from the 18-19 plan text.
- Epoch timing: a connection event emitted while a connect, rebuild or rekey is still running carries the epoch from before that operation. The real SDK fires an "open" callback immediately when it is registered on an open connection, and that happens inside `connect`. The supervisor (plan 18-14) should rely on `start()` / `rebuild()` returning, not on that first "open".
- Binance facts here (the path form `/private/ws/<listenKey>`, -1125 for an invalid key) are WebFetch summaries and were not verified live. The adapter tests use SDK-shaped fakes built from the installed SDK models.

## Self-Check: PASSED

- FOUND: src/adapters/binance_userdata.py, tests/userdata_fakes.py, tests/test_userdata_adapter.py, tests/test_userdata_contract.py
- FOUND commits: 47fcda7, af1ffa2, 845ae59
