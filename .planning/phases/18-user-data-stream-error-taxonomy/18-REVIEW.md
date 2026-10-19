---
phase: 18-user-data-stream-error-taxonomy
reviewed: 2026-10-19T00:00:00Z
depth: deep
files_reviewed: 83
files_reviewed_list:
  - .gitattributes
  - config/binance/README.md
  - config/binance/binance-limits-v1.toml
  - scripts/demo_probe.py
  - scripts/demo_rehearsal.py
  - scripts/user_data_smoke.py
  - src/adapters/binance_client.py
  - src/adapters/binance_clock.py
  - src/adapters/binance_errors.py
  - src/adapters/binance_limits.py
  - src/adapters/binance_probe.py
  - src/adapters/binance_public.py
  - src/adapters/binance_ratelimit_gate.py
  - src/adapters/binance_usdm.py
  - src/adapters/binance_userdata.py
  - src/adapters/binance_userdata_events.py
  - src/adapters/binance_userdata_router.py
  - src/adapters/binance_userdata_supervisor.py
  - src/domain/algo_status.py
  - src/domain/exchange_errors.py
  - src/domain/stream_records.py
  - src/execution/fill_monitor.py
  - src/execution/manager.py
  - src/ops/operator_evidence.py
  - src/ops/redaction.py
  - src/persistence/__init__.py
  - src/persistence/entities.py
  - src/persistence/errors.py
  - src/reconcile/sweeper.py
  - tests/probe_fakes.py
  - tests/support/ast_guards.py
  - tests/support/fake_binance_exchange.py
  - tests/support/limits.py
  - tests/support/stream_sinks.py
  - tests/support/userdata_frames.py
  - tests/support/virtual_time.py
  - tests/test_adapter_not_found_mapping.py
  - tests/test_adapter_strictness.py
  - tests/test_algo_status.py
  - tests/test_binance_client_config.py
  - tests/test_binance_limits.py
  - tests/test_binance_limits_ratified_file.py
  - tests/test_binance_probe.py
  - tests/test_binance_probe_contract.py
  - tests/test_binance_ratelimit_gate.py
  - tests/test_binance_secret_redaction.py
  - tests/test_binance_usdm_error_routing.py
  - tests/test_binance_usdm_signed_calls.py
  - tests/test_binance_usdm_source_guard.py
  - tests/test_clock_drift.py
  - tests/test_demo_probe_cases.py
  - tests/test_demo_probe_cli.py
  - tests/test_demo_probe_evidence.py
  - tests/test_demo_rehearsal_safety.py
  - tests/test_exchange_errors.py
  - tests/test_execution_adapter_contract.py
  - tests/test_execution_attach.py
  - tests/test_execution_exactly_once_pg.py
  - tests/test_execution_manager.py
  - tests/test_fake_binance_semantics.py
  - tests/test_no_unratified_defaults.py
  - tests/test_operator_evidence.py
  - tests/test_persistence_exit_evidence_pg.py
  - tests/test_phase18_gate.py
  - tests/test_phase8_audit_reviewfix.py
  - tests/test_reconcile.py
  - tests/test_redaction.py
  - tests/test_sdk_error_mapping_contract.py
  - tests/test_sources_phase18_section.py
  - tests/test_stream_records.py
  - tests/test_user_data_smoke_cli.py
  - tests/test_user_data_smoke_dry_run.py
  - tests/test_user_data_smoke_evidence.py
  - tests/test_userdata_adapter.py
  - tests/test_userdata_contract.py
  - tests/test_userdata_events.py
  - tests/test_userdata_parsers.py
  - tests/test_userdata_recorded_frames.py
  - tests/test_userdata_replay.py
  - tests/test_userdata_rig.py
  - tests/test_userdata_router.py
  - tests/test_userdata_supervisor.py
  - tests/userdata_fakes.py
findings:
  critical: 2
  warning: 31
  info: 29
  total: 62
status: issues_found
---

# Phase 18: Code Review Report (deep, three parts)


# Part: src, scripts and config

Finding ids are scoped to this part (source file `18-REVIEW-src.md`).

# Phase 18: Code Review Report (src, scripts, config)

**Reviewed:** 2026-10-19
**Depth:** deep (adapters -> router -> supervisor -> execution/reconcile -> persistence, plus the installed `binance_common` 4.4.0 SDK source where behavior had to be confirmed)
**Files Reviewed:** 29
**Status:** issues_found

## Summary

The taxonomy, limits loader, gate, clock guard, event parser and persistence layer are carefully built and consistent with the recorded decisions: `ruff check`, `ruff format --check` and `mypy` (on the stream/sweeper files) are clean, no float reaches an order path, the SDK is confined to `src/adapters`, the listenKey is registered with the redactor before use, and unknown codes and statuses fail closed.

The defects that remain sit at the seams between modules, not inside any one of them:

- The stream can be declared LIVE while no subscription exists. The SDK's SUBSCRIBE is fire-and-forget, a server rejection is only logged, the supervisor ignores `error` events on an open socket, a rebuild reuses a possibly expired key, and the liveness verdict is ratified as "none" and is not called anywhere. (CR-02)
- A safety read used by the orphan sweeper fabricates a zero position. (CR-01)
- The supervisor and the execution manager retry calls that the recorded 418/429 decision says are never retried, and the manager does not use the taxonomy at all. (WR-01, WR-02)
- The out-of-order and duplicate-event requirement is only half met: the data a consumer needs to order events is dropped by the router. (WR-03)

Coverage note: `src/**` was read in full. `scripts/user_data_smoke.py` was read in full; `scripts/demo_probe.py` (about 40 percent: state/cleanup, run loop, live rig, main) and `scripts/demo_rehearsal.py` (credentials, client, evidence writer, main) were read selectively, because they are operator tools whose case bodies are test-like scenario code. No finding below depends on the unread scenario bodies.

## Critical Issues

### CR-01: A position row with a missing `positionAmt` is read as flat, which can defeat the sweeper's position-zero check

**File:** `src/adapters/binance_usdm.py:1363-1397` (and `:830-842`)
**Issue:** `_row_to_position_snapshot` turns `item.position_amt is None` into `Decimal("0")` (also `entry_price`, `break_even_price`, `un_realized_profit`). `snapshot_positions` then drops every row whose amount is zero. Every sibling converter in this file raises on a missing field ("Flag-never-fabricate (D-09)"), and the module docstring says so, but the one converter that feeds the "no position" decision does not. The project's own research (P4) records that the SDK models silently drop unknown or renamed fields, so a wire rename or a partial row produces `None`, then a fabricated flat position, and the row disappears from the snapshot. `OrphanSweeper` requires two consecutive zero reads from a caller-supplied verifier before it cancels a protective stop (T-8-30); a verifier built on `snapshot_positions` is satisfied by this fabricated zero, so the sweeper would cancel the stop-loss of a live position. The smoke and probe "account flat" checks and `_positions_summary` use the same converter, so their end-state verdict is also unreliable in that case. This violates "fail closed (uncertain -> NO_TRADE)".
**Fix:**
```python
if item.position_amt is None:
    raise ValueError("position row missing positionAmt: refusing to fabricate a flat position")
position_amt = Decimal(str(item.position_amt))
if not position_amt.is_finite():
    raise ValueError("position row positionAmt is not finite")
```
Do the same for `entry_price`, `break_even_price` and `un_realized_profit` (raise, or make them `Decimal | None`, but never `0`). Add a test where `position_amt=None` must raise.

### CR-02: The stream can be LIVE with no working subscription, and nothing detects it

**File:** `src/adapters/binance_userdata.py:539-558` (`_subscribe`, `connect`), `:726-732` (`UserDataAdapter.rebuild`); `src/adapters/binance_userdata_supervisor.py:585-590` (`error` branch), `:131-156` (`stream_is_stale`); `config/binance/binance-limits-v1.toml` (`max_liveness_age_seconds = "none"`)
**Issue:** Four facts combine into a silent failure that is reachable in normal operation:
1. The SDK `subscribe` sends SUBSCRIBE and discards the future (`binance_common/websocket.py` `subscribe` -> `send_message`); a rejection only reaches `logging.error("Error received from server for request ...")` and an unawaited-future warning. The transport never checks for an acknowledgement and `_subscribe` just stores `self._listen_key`. `subscribe` also returns silently (with a warning) when no connection is usable, after which `handle.on("message")` only logs "Stream not connected".
2. `UserDataAdapter.rebuild()` re-subscribes the STORED key without proving it is still valid. After any outage or suspend longer than the 60 minute key lifetime the SUBSCRIBE is useless, but `connect` succeeds.
3. The supervisor ignores an `error` connection event while `private_connection_open()` is true (`error_on_open_connection_ignored`), which is exactly how a server-side error surfaces on a healthy socket.
4. `stream_is_stale` is never called by the supervisor, and the ratified `max_liveness_age_seconds` is `none`, so even a caller who wanted a verdict gets False. A quiet account sends no events, so event silence cannot expose it either.
The REST snapshot then succeeds and `_enter_live` publishes LIVE. The next signal is a keepalive failure up to `keepalive_interval_seconds` (30 minutes) later. During that window a REJECTED/EXPIRED protective algo update or a fill is never delivered while every consumer is told the stream is trusted. The live smoke (plan 18-18) only proves the happy path under controlled conditions.
**Fix:**
```python
# transport, after subscribe:
async def _subscribe(self, listen_key: str) -> None:
    handle = await self._ws.user_data(listen_key)
    handle.on("message", self._dispatch_message)
    if listen_key not in _sdk_stream_map():
        raise ConnectionError("SUBSCRIBE did not register the user-data stream")
    # confirm server-side: LIST_SUBSCRIPTIONS exists (WebSocketStreamBase.list_subscribe)
    await self._confirm_subscription(listen_key)   # raise ConnectionError on timeout / absence
    self._listen_key = listen_key
```
In `UserDataAdapter.rebuild()` call `await self._listen_keys.keepalive()` (or `start()`) before `transport.rebuild(key)` and treat `ListenKeyInvalid` as a REKEY. In the supervisor, run `stream_is_stale` from the keepalive tick and halt when it is true, and require a limits decision for `max_liveness_age_seconds` instead of `none` before Phase 24 relies on LIVE. Treat an `error` event that arrives within a few seconds after a subscribe/resubscribe as a failed subscription.

## Warnings

### WR-01: The supervisor retries listenKey and snapshot calls after a 429, contrary to the recorded decision and to `retry_eligible`

**File:** `src/adapters/binance_userdata_supervisor.py:285-287` (`_retryable`), `:644-667` (`_await_rest_allowed`, `_gated`), `:794-833` (`_bounded`)
**Issue:** `exchange_errors.retry_eligible(RATE_LIMITED, LISTEN_KEY)` is False and the user record says no call is retried because of a 429. `SdkListenKeyPort` raises `ListenKeyTransient(RATE_LIMITED)` after recording the pause, `_retryable` treats every `Exception` except Cancelled/Halted/`ListenKeyFailure` as retryable, and tenacity then waits out the pause (`_gated`) and sends the same listenKey `POST`/`PUT` again. The same happens to the snapshot calls (a REST 429 inside `snapshot_provider` is retried up to `snapshot_max_attempts`). The module docstring ("a pause waited inside an attempt is not an attempt") rewrites the rule rather than following it. The class docstring of `ListenKeyTransient` also says it is "not a retry permission".
**Fix:** In `_retryable`, ask the taxonomy: `return not isinstance(exc, ListenKeyError) or retry_eligible(exc.category, CallKind.LISTEN_KEY)`. A `ListenKeyTransient` with category `RATE_LIMITED` should halt with the category name and wait for `request_resync()`. Snapshot attempts need the same predicate (classify the exception; a 429/418 halts).

### WR-02: The execution manager ignores the error taxonomy, retries a placement, and treats refusals made before sending as "unknown"

**File:** `src/execution/manager.py:181`, `:201-254` (`_place_entry_no_blind_retry`), `:773-806`
**Issue:** `exchange_errors.py` and the user record say a placement is never retried and that definitive rejections, rate limits, auth and clock-skew answers are not ambiguous. The manager catches every `Exception` from `place_entry` as "ambiguous", probes, and calls `place_entry` a second time (`_ENTRY_MAX_ATTEMPTS = 2`) when the probe says absent. Consequences: (a) a definitive rejection (-2019, -4164, -4016 ...) is sent twice; (b) an `EntriesBlocked` (drift guard), `SignedCallPolicyMissing`, a gate refusal, or even a local `ValueError`/`TypeError` raised before anything left the process is treated as an exchange answer; when the probe is also refused by the gate the result is `ENTRY_STATE_UNKNOWN`, SAFE_MODE and an intent row UNKNOWN that needs Binance evidence to leave, although nothing was sent; when the probe works the outcome is `EXCHANGE_CONSTRAINT` and the approval is consumed with a wrong reason code; (c) a placement is re-sent after a 429/418 as soon as the probe succeeds.
**Fix:** Classify the failure with `error_facts_from_exception` + `classify(..., CallKind.PLACEMENT)` (the manager may call the adapter-level helper). Refusals raised before sending (`RestGateRefusal`, `EntriesBlocked`, `SignedCallPolicyMissing`, `ValueError`/`TypeError`) are a definitive "not placed" -> NO_TRADE without SAFE_MODE; `REJECTED_DEFINITIVE`/`AUTH_OR_SIGNATURE`/`CLOCK_SKEW`/`RATE_LIMITED`/`IP_BANNED` -> NO_TRADE, no second attempt; only `STATUS_UNKNOWN` and `UNKNOWN_EXCHANGE_ERROR` go to the probe. Remove the second `place_entry` or get an explicit decision that supersedes "a placement is never retried".

### WR-03: Out-of-order events cannot be ordered downstream, and a late event overwrites a newer exchange status

**File:** `src/adapters/binance_userdata_router.py:210-217` (`ExchangeStateUpdate`), `:550-557`, `:409-420`; `src/persistence/entities.py:465-516`
**Issue:** The requirement is to handle out-of-order and duplicate events. The router de-duplicates only ALGO_UPDATEs, and keys them without any time, so `NEW` after `TRIGGERED` is a different key and is routed as ACTIVE. For orders there is no ordering information at all: `ExchangeStateUpdate` carries `now_utc=self._clock()` (processing time), not the event's `transaction_time_utc`/trade time, and `OrderStatusHint`'s evidence carries `received_at_utc`. `update_order_exchange_state` writes whatever status it is given, unconditionally, with no monotonicity or event-time guard. A held event released after a snapshot (`after_gap=True`) or a plain reordered frame (`NEW` after `FILLED`) regresses `exchange_status`. `AlgoRoute` does carry the event, but nothing says the consumer must compare `transaction_time_utc`.
**Fix:** Carry `event_time_utc`/`transaction_time_utc` (and the execution type) on `ExchangeStateUpdate`; make `update_order_exchange_state` accept `event_time_utc` and ignore an update older than the stored one (store the event time in a column or in the journal), and never move a terminal exchange status back to a non-terminal one. Add a per-algo-id high-water mark of `transaction_time_utc` in the router and surface an older ALGO_UPDATE as a counted anomaly instead of routing it.

### WR-04: A failing sink silently loses a fill, a status hint or an algo update

**File:** `src/adapters/binance_userdata_router.py:848-885`
**Issue:** `_call_sink` swallows a sink exception and `_record_sink_failure` writes one `ROUTER_SINK_FAILURE` journal row (type name only). No divergence is emitted and the event is not retained, so the `RoutedFill`/`AlgoRoute` (including a TERMINAL_FAILED protective stop) never reaches the fold or the reconciler, and the router has already marked the lifecycle key as seen (`_seen_algo_keys.add`), so a redelivered frame is counted as a duplicate. The row's id is deduplicated by `(sink, exception type, outcome fingerprint)`, so a repeated failure for the same event leaves no further trace. Fail closed would surface the loss.
**Fix:** After journaling a sink failure, emit a `StreamDivergence` (new kind `SINK_FAILURE`, carrying the sink name and the order/algo identity) and do not add the algo key to `_seen_algo_keys` when its `algo_sink` failed, so a redelivery is routed again.

### WR-05: A crashed supervisor task is only logged; the stream stays LIVE

**File:** `src/adapters/binance_userdata_supervisor.py:446-452` (`_task_done`), `:481-487`, `:498-512`
**Issue:** `_control_loop` guards each command, but `_pump`, `_keepalive_timer` and `_rotation_timer` have no guard, and `_control_loop` itself can die on a non-`Exception` or on a failure inside its own `except` path (for example `_halt` -> `_set_state` raising out of a sink is caught, but `self._commands.get()` or `log.error` raising is not). `_task_done` logs and returns. If the pump or control loop dies, no event is delivered and no recovery runs, yet `state` stays LIVE and `stream_is_stale` cannot see it. If the keepalive timer dies, keepalives stop and the key expires after 60 minutes with no recovery path other than the expiry event.
**Fix:** In `_task_done`, for any task that is not cancelled and not during `stop()`, call a synchronous `_fail_closed("TASK_DIED")` that sets `_halted`, sets state UNKNOWN and calls `on_failure`. Wrap the bodies of `_pump` and `_keepalive_timer` in try/except Exception that does the same.

### WR-06: `UserDataAdapter.start()/stop()` leak a listenKey and leave a dirty client after a partial failure

**File:** `src/adapters/binance_userdata.py:700-706`, `:734-747`; `:544-558`
**Issue:** `start()` obtains a key, then `transport.connect(key)`; if `connect` raises, `_listen_key` is never set, so a later `stop(close_listen_key=True)` skips the `DELETE` for a key that exists. The supervisor's tenacity retry then calls `start()` again, which calls `create_connection()` on the SAME SDK client that may already hold connections from the failed attempt (`connect` raises after `create_connection` when no private connection is present, and after `_subscribe` fails), so connections can accumulate and callbacks are registered on several. In `stop()`, `_stopped = True` is set before the awaits; if `transport.close()` raises, `_listen_key` is kept, `_stopped` stays True and the method can never be re-run, so the transport and the key stay open. `epoch` also increments only after `connect`, so frames delivered during the connect carry the old epoch (a `listenKeyExpired` received then is ignored as stale by the supervisor).
**Fix:** Set `self._listen_key = key` before `connect` and reset it on failure; in `SdkUserDataTransport.connect` build a fresh client when a previous attempt left connections (reuse the `rebuild` path); in `stop()` set `_stopped` only after the transport closed, and attempt the key `DELETE` in a `finally`. Increment the epoch before the first frame can arrive.

### WR-07: The sweeper journals SDK exception text and misreports a successful cancel

**File:** `src/reconcile/sweeper.py:218-232`, `:247-286`
**Issue:** (a) `reason=f"probe_failed: {type(exc).__name__}: {exc}"` and `"cancel_failed: ...: {exc}"` are written into the append-only journal. `binance_common` builds `NetworkError("Network error: " + str(requests_exception))`, and a `requests` connection error message embeds the full request URL, including `signature=<hmac>` and the timestamp. `binance_errors.py` exists precisely because this text must never travel (T-18-14); the journal payload is not passed through `scrub`. The `SweepSkip.reason` correctly keeps the type only. (b) The post-image `journal.record` is inside the same `try` as the cancel. When the cancel succeeded and the post-image write fails, the handler records `cancel_failed`, reports the orphan as `skipped`, and does not count it as cancelled, although the algo order is gone. (c) If the failure-event `journal.record` itself raises, the exception leaves the loop and aborts the remaining orphans, contrary to the docstring ("NEVER raises on a single cancel failure").
**Fix:** Use `reason=f"probe_failed: {type(exc).__name__}"` (or `scrub(...)[:200]`), split the `try` so a post-image failure is recorded as `post_image_failed` and the orphan is still counted as cancelled, and wrap the failure-event writes so one journal error cannot end the sweep.

### WR-08: HTTP `ClientError` (any 4xx other than 400/401/403/404/418/429) is classified STATUS_UNKNOWN and therefore retryable

**File:** `src/domain/exchange_errors.py:570-581`, `:609-625`; `src/adapters/binance_errors.py:37-44`; consumers `src/adapters/binance_usdm.py:222-232`, `src/adapters/binance_userdata.py:182-199`
**Issue:** The SDK raises `ClientError(error_message=...)` with no code for every other 4xx (405, 408, 409, 413, 414, 415, 451 ...). Only 408 is an execution-status-unknown timeout; the others are deterministic refusals (a 451 geo-block never succeeds on retry). Mapping the whole class to `STATUS_UNKNOWN` makes cancel and listenKey calls retry them and makes a placement an ambiguous probe case. This conflicts with "the error taxonomy must not map an unknown code to a retryable outcome". The class carries no HTTP status, so 408 cannot be told apart from the rest.
**Fix:** Map `HttpClass.CLIENT_OTHER` to `UNKNOWN_EXCHANGE_ERROR` (not retried, SAFE_MODE eligible), unless the adapter can read the HTTP status (extend `ErrorFacts` with an optional status read from the exception only when the SDK exposes it) and only 408 is mapped to `STATUS_UNKNOWN`.

### WR-09: `get_position_mode` turns a missing `dualSidePosition` into one-way mode

**File:** `src/adapters/binance_usdm.py:1243-1247`
**Issue:** `PositionModeResult(dual_side_position=bool(raw.dual_side_position))`: `None` (field dropped or renamed, see CR-01) becomes `False`, i.e. ONE_WAY, so entries and protective legs are sent with `positionSide=BOTH`. The manager's `resolve_position_mode` is strict about the literal bool, but it never sees the `None`. The project rule is that the position mode is detected, never assumed.
**Fix:** `if not isinstance(raw.dual_side_position, bool): raise ValueError("dualSidePosition missing or not a bool")`.

### WR-10: Rate-limit response headers are never read

**File:** `src/adapters/binance_usdm.py:649-677` (`_sdk_call`), `src/adapters/binance_public.py:281-298`, `src/adapters/binance_probe.py:604-629`, `src/adapters/binance_userdata.py:234-254`
**Issue:** The project requires the stream/REST layer to handle rate-limit headers. The SDK parses `X-MBX-USED-WEIGHT-*` and `X-MBX-ORDER-COUNT-*` into `ApiResponse.rate_limits` (`binance_common/utils.py::parse_rate_limit_headers`), but no code in `src` reads them (grep for `rate_limits`, `used-weight`: no hits). The gate is purely reactive: it opens only after the first 429/418, so burst paths (snapshot retries, reconcile ticks, probe cases) can reach the IP limit and an escalating ban before any restriction exists.
**Fix:** Have `_sdk_call`/`_gated_rest_call`/`SdkListenKeyPort._rest_call` pass `response.rate_limits` to a `gate.observe(...)` that pauses REST when the used weight or order count crosses a ratified fraction of the limit (needs a limits key), or record the decision that reactive handling is accepted.

### WR-11: `SdkNoiseGuard` lets a listenKey-bearing SDK ERROR line through to unfiltered handlers

**File:** `src/adapters/binance_userdata.py:345-368`
**Issue:** The guard drops only sub-WARNING records. The SDK logs `logging.error(f"Error in callback for key {key}: {e}")` (`binance_common/websocket.py:384`), where `key` is the stream name, i.e. the listenKey, and `logging.error("Error received from server ...: {data['error']}")`. Those are ERROR lines and are "untouched" by design. They are redacted only if every root handler carries `RedactingFilter` (true for handlers present when `configure_logging` ran, not for handlers added later, or when a composition never calls it). The bridge scrubs its own copy, but the original record still propagates to the other handlers.
**Fix:** In `SdkNoiseGuard.filter`, for SDK records at any level, replace `record.msg`/`record.args` with `scrub(record.getMessage())` (and clear `args`), instead of relying on each handler's filter.

### WR-12: A 429 pause blocks protective placement and entry cancel with no compensating control

**File:** `src/adapters/binance_ratelimit_gate.py:1-30`, `:128-150`; `src/execution/manager.py:858-905`
**Issue:** By recorded decision the gate refuses every REST call of every kind during a 429 pause or 418 ban, protective stops and cancels included, and "the unresolved account state stays with reconciliation". In `execute_approved_plan` that means: entry acknowledged -> pause starts (429 on the SL placement or a parallel call) -> SL refused -> `sl_confirmed=False` -> SAFE_MODE -> `expire_pending_entry` is also refused -> the exception is swallowed (`except Exception: pass`) and the resting GTC LIMIT entry stays live and can fill with no stop. SAFE_MODE blocks new entries only. The reconciler that would clean this up is Phase 20 and is not wired.
**Fix:** Keep the decision, but add a compensating control before live use: a durable "pending cancel/protect" record written when the cancel or SL is refused, retried by the first call after the gate opens, and an alert; or ask the owner to carve out a reduce-risk exemption (cancel and `closePosition` stop) from the pause. Record the choice in DECISIONS.

## Info

### IN-01: Float division in `_ms_to_utc`
**File:** `src/adapters/binance_public.py:195-197`
`datetime.fromtimestamp(ms / 1000, tz=UTC)` uses a float for every kline, server-time and update-time conversion, while `binance_userdata_events._ms_to_utc` and `binance_clock._utc_ms` use exact `timedelta` arithmetic. Results are correct at current epoch magnitudes (about 2e-7 s error), but the two helpers should be one exact function: `_EPOCH + timedelta(milliseconds=ms)`.

### IN-02: `is_rate_limit_error` falls back to a class-name substring
**File:** `src/adapters/binance_usdm.py:487-508`
`"RateLimit" in type(exc).__name__` is True for the project's own `RateLimitBanActive`/`RateLimitPauseActive`, and `"RateLimitBan" in ...` for `RateLimitBanActive`. `universe_freeze` uses `retry_if_exception(is_rate_limit_error)`, so a gate refusal is retried as if it were an SDK 429, and `rate_limit_retry_after_seconds` returns None for it. This contradicts the module's own "isinstance only" claim and the taxonomy rule that decisions never rest on names. Drop the name fallback and test for `RestGateRefusal` explicitly.

### IN-03: Journal helpers promise idempotent replay but include the observation time in the payload
**File:** `src/domain/stream_records.py:225-241`, `:173-181`
`stream_anomaly_event` says "a replay is a no-op", but `payload_json` contains `observed_at_utc`, and `PgJournalStore` compares `payload_json`, so a replay with a new time under the same id raises `JournalConflict`. The router avoids it only through its in-memory `_journaled` set, which is lost on restart. Also `entity_id = f"{kind}:{sha256}"` can be 129 characters for a 64-character kind (column is VARCHAR(128)); real kinds are far shorter. Move the observation time out of the payload (keep `occurred_at_utc`) and cap `kind` at 63 characters.

### IN-04: Evidence writers: `os.replace` can overwrite, and the rehearsal has a weaker private copy
**File:** `src/ops/operator_evidence.py:123-141`; `scripts/demo_rehearsal.py:549-569`
`write_evidence_atomic` checks `target.exists()` and then `os.replace`s, which overwrites on both POSIX and Windows if another writer created the name in between; use `os.link`/`open(..., "x")` or retry on `FileExistsError`. `EvidenceRecorder.write` in the rehearsal duplicates this logic with a fixed temp name `.{target}.tmp`, no temp cleanup on error, and only `Redactor.from_environ` (no runtime secrets); it should call `write_evidence_atomic`.

### IN-05: The decimal reader accepts exponent notation
**File:** `src/adapters/binance_userdata_events.py:89`, `:770-789`
`_DECIMAL_TEXT` allows `1e999999999`; `Decimal()` accepts it and `is_finite()` is True, but `format(value, "f")` (used by `jsonable`, `_decimal_to_wire`, `_text`) would build a billion-character string. Binance never sends exponents; drop `(?:[eE][+-]?\d+)?` and bound the length.

### IN-06: `exchange_info` does not require positive, finite filter values
**File:** `src/adapters/binance_public.py:630-661`
`tick_size`, `step_size`, `min_qty` and `notional` are only checked for `None`; `"0"` or `"NaN"` would reach quantization (zero tick floors everything, the very case the comment warns about). Reuse `_filter_decimal` and require `> 0`.

### IN-07: `fold_fills` fails open by default, and `FillEvent` does not validate positivity
**File:** `src/execution/fill_monitor.py:170`, `:90-108`
`has_protective=True` is the default, so a caller that forgets the argument gets no `ENTRY_WITHOUT_PROTECTIVE` divergence; make it a required keyword. `FillEvent` accepts zero, negative and NaN quantities and prices (the stream path guards this, the REST fallback path does not); require `fill_quantity > 0`, `fill_price > 0` and finite.

### IN-08: Router hygiene
**File:** `src/adapters/binance_userdata_router.py:466-471`, `:626-641`, `:529-557`
`_seen_algo_keys`, `_journaled` and `FillTotalsTracker` grow for the life of a session. `fills_fallback` is a synchronous call inside `route()`, which the supervisor documents as a "record or enqueue only" sink context, and it is not required to pass through the REST gate. `_route_order` never compares `event.symbol` with `known.symbol`. Fallback fills for other order ids are routed to the fill sink without being checked against the requested order.

### IN-09: Recorded Demo frames and evidence are not pinned to LF
**File:** `.gitattributes:17-20`
Only `tests/fixtures/phase18/synthetic/*.json` is pinned `text eol=lf`; `tests/fixtures/phase18/recorded_demo/**` and `.planning/phases/18-*/evidence/*.json` are written with LF by `write_evidence_atomic` but are subject to autocrlf on Windows. If any test hashes them, add `eol=lf` or `-text` for those paths.

### IN-10: A `Retry-After: 0` records an end time equal to now and pauses nothing
**File:** `src/domain/exchange_errors.py:677-688`; `src/adapters/binance_ratelimit_gate.py:128-150`
`wait_seconds=0` is accepted and `end = now`, so the gate refuses nothing after a 429/418. Treat 0 as "absent" and use the ratified fallback.

### IN-11: Limits file has no cross-check between keepalive period and the 60 minute key lifetime
**File:** `src/adapters/binance_limits.py:274-278`
`BinanceLimits.__post_init__` validates `behind_limit_ms <= recv_window_ms` but not `keepalive_interval_seconds * (keepalive_failure_tolerance + 1) < 3600`. The ratified 1800/1 satisfies it today; the guard prevents a future edit from silently allowing key expiry.

### IN-12: Stale or misleading text and an isolation gap
**File:** `scripts/demo_rehearsal.py:2466-2470`; `src/execution/manager.py:1472-1552`
The rehearsal attestation item 3 still says the stream "arrives with Phase 18". `cancel_untriggered_protectives` documents that every leg is attempted, but `journal.record(pre_cancel)` is outside the `try`, so a journal failure on the SL leg aborts the loop and TP1/TP2 are never attempted.

---

_Reviewed: 2026-10-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_


# Part: tests part A

Finding ids are scoped to this part (source file `18-REVIEW-tests-a.md`).

# Phase 18: Code Review Report (tests, shard A)

**Reviewed:** 2026-10-19
**Depth:** deep (each test cross-read against the src module, script or SDK signature it claims to cover)
**Files Reviewed:** 27
**Status:** issues_found

## Summary

The suite is carefully built: TEST_ONLY values are pairwise distinct so swapped fields fail, most
guards come with negative controls, nothing sleeps in real time, nothing reaches Binance, and the
signed-call tests bind recorded kwargs to the installed SDK signatures. No test was found that
hides a production defect outright, so there are no BLOCKER findings.

The defects are about tests that cannot fail, tests that bind less than their docstring claims,
fakes that are looser than the surface they stand for, and state that leaks between tests. The
most concrete: one assertion with an always-true `or` branch (WR-01); the probe fakes are not
checked against the `ProbePort` protocol (WR-02); the "every SDK call is bound" contract test
leaves out the two public reads of the probe (WR-03); three import-time or cwd-dependent reads
that turn a record edit into a whole-module collection failure (WR-04, WR-05); a logging
reconfiguration with no teardown (WR-06); and AST guards with documented-looking but bypassable
rules (WR-07).

Project-rule check: no `float` used for money (floats appear only as rejected inputs), line
length 100 holds (the seven long lines end in `# type: ignore`, which ruff E501 exempts), all
times are injected or fixed. Randomness appears only in WR-level-free form (IN-02).

## Warnings

### WR-01: Always-true assertion in the unregistered-handler test

**File:** `tests/test_demo_probe_cases.py:306-308`
**Issue:** The assertion is
`port.names()[-3:] == [...] or ("cancel_all_open_orders" in port.names())`. Every execute run
performs a cleanup, which calls `cancel_all_open_orders` (the sibling test at line 586 asserts it
runs once per case plus once at the end), so the right-hand branch is always true and the
assertion can never fail. The intent (the run still ends with the account re-read) is not
checked.
**Fix:**
```python
names = port.names()
assert names[-3:] == ["open_orders", "open_algo_orders", "positions"]
```
If the tail is not stable, assert the specific final cleanup read through `document["cleanup"]`
instead of an `or`.

### WR-02: Probe port fakes are not bound to the `ProbePort` protocol and are more permissive than it

**File:** `tests/probe_fakes.py:499, 523-536, 538, 554-592, 728-735` (protocol at `scripts/demo_probe.py:501-591`)
**Issue:** `ProbePort` declares keyword-only parameters, and `new_limit_order` requires
`time_in_force` and `reduce_only`. `FakeProbePort` and `RecordingProbePort` declare
`new_limit_order`, `new_market_order` and `new_conditional_order` as `**kwargs: Any`, and
`FakeProbePort` reads `kwargs["price"]`, `kwargs["position_side"]` and similar by key. No test
binds either fake to `ProbePort`, to `BinanceProbeAdapter`, or to `GuardedProbePort`. A case that
drops a required argument, adds a misspelled one, or the protocol gaining a required parameter,
passes on the fakes and fails only at the first live Demo run (the very situation the probe
contract test was written for). The state model is also loose: `FakeProbePort.new_market_order`
removes every position of the side regardless of order side or quantity, and no operation checks
`symbol`, so a wrong-side or wrong-size close, or an order for the wrong symbol, still ends
`CLEANUP_FLAT`.
**Fix:** Add a conformance test that compares `inspect.signature` of every `ProbePort` method
with the same method on `FakeProbePort`, `RecordingProbePort` and `BinanceProbeAdapter`
(parameter names, kinds, required/optional). Give the three order methods the explicit
signatures of the protocol. In `new_market_order` reduce the held amount by `quantity` and
require the opposite `side`; reject a `symbol` other than `self.symbol`.

### WR-03: The probe SDK contract test leaves the two public reads unbound

**File:** `tests/test_binance_probe_contract.py:1-10, 48-62, 68-144`; `tests/probe_fakes.py:116-121`; `src/adapters/binance_probe.py:631-652, 913-935`
**Issue:** The module docstring says "Every SDK call the adapter makes is recorded ... and bound".
`SDK_REST_METHODS` and `_OPERATIONS` cover only the signed `_call` path. `mark_price` and
`symbol_filters` go through `_public_read` and `BinancePublicMarketData`, which call
`mark_price_kline_candlestick_data` (with `interval=interval,  # type: ignore[arg-type]` and an
enum-annotated SDK parameter) and `exchange_information`. Neither is in `_OPERATIONS`, neither has
a scripted payload, `FakeProbeRest` accepts any kwargs for them, and
`test_every_call_site_names_a_declared_sdk_method` only inspects `_call`. So the one place where
the adapter passes a plain string for an enum-annotated parameter is exactly what
`_check_argument_types` does not examine. The mark price and filters feed every write case's
sizing, and the test file states that a mistyped keyword "would otherwise surface only" at the
user checkpoint.
**Fix:** Add `mark_price` and `symbol_filters` to `_OPERATIONS` with scripted payloads
(`[[...kline row...]]`, an `ExchangeInformationResponse`), include
`mark_price_kline_candlestick_data` and `exchange_information` in the recorded-call binding, and
either assert the enum rule for `interval` or add an explicit, commented exception for it.

### WR-04: Record parsing at import time makes a record edit a whole-module collection error

**File:** `tests/test_binance_client_config.py:455-462` (also the `parametrize` at line 494)
**Issue:** `_GUARDED_URLS` calls `_record_demo_streams_url()` at module import. That helper
asserts the decision record configures a DEMO streams URL. If the owner sets
`env DEMO ws_streams_url: NOT_CONFIGURED` (a state the other tests in this same file are written
to handle, see `test_demo_websocket_surface_follows_the_record`), the assertion fires during
collection, and all ~50 tests of the module, including the unrelated parse, credential and
endpoint-guard tests, are reported as one collection error instead of one failing test.
**Fix:** Resolve the URL lazily: build `_GUARDED_URLS` inside a function or fixture, or
parametrize over labels and look the value up inside the test body; skip the `demo-streams`
label when the record answers NOT_CONFIGURED.

### WR-05: A test depends on the working directory

**File:** `tests/test_binance_limits_ratified_file.py:208`
**Issue:** `load_binance_limits(Path("config/binance/binance-limits-v1.toml").resolve())`
resolves against the current directory, while every other path in the module uses `REPO_ROOT`
(`LIMITS_FILE`, line 234 in the next test). Running pytest from any directory other than the
repository root makes this one test fail with `LimitsFileMissing`, and it is the only test that
exercises "the real loader accepts the ratified file with the record values".
**Fix:** `limits = load_binance_limits(LIMITS_FILE)`.

### WR-06: Global logging state is reconfigured with no teardown

**File:** `tests/test_binance_secret_redaction.py:34-40, 246-251, 318-321`; `src/ops/redaction.py:438-478`
**Issue:** Two tests call `configure_logging(environ={}, stream=buffer)`. That call replaces the
global structlog configuration (PrintLogger writing to `buffer`, `cache_logger_on_first_use=False`)
and attaches a marked handler to the root logger that writes to `buffer`. The autouse fixture
only clears runtime secrets and calls `uninstall_global_hooks()` (which restores the excepthooks
only). After these tests, later tests in the same session that log through structlog or the root
logger write into a stale `StringIO`, and any later test that asserts on structlog output
through `capsys` sees nothing. The result depends on test order.
**Fix:** In the fixture teardown call `structlog.reset_defaults()` and remove every root handler
carrying `redaction._ROOT_HANDLER_MARKER` (or add a public `redaction.reset_logging()` for tests),
and restore the root level.

### WR-07: The AST guards have bypasses that the negative controls do not cover

**File:** `tests/test_binance_usdm_source_guard.py:131-159`; `tests/support/ast_guards.py:107-137`; `tests/test_binance_usdm_signed_calls.py:1131-1178`; `tests/test_demo_probe_cases.py:1827-1832`
**Issue:** These guards enforce safety properties ("message text never decides", "no wall clock in
the pure modules", "only `_sdk_call` sends a signed method", "every wait is the case timeout"),
but each has a simple route around it that passes:
- `message_text_reads` only flags `.error_message` and `str(<exc|e|err|error|exception>)`. It
  misses `repr(exc)`, `f"{exc}"`, `exc.args[0]`, `getattr(exc, "error_message")`, and
  `str(caught)` with any other variable name. The normalizer guard in
  `test_exchange_errors.py:131-148` already forbids all of these (`args`, `msg`, `repr`,
  `format`, f-strings), so the adapter and manager, where the decision risk sits, get the weaker
  rule.
- `wall_clock_calls` resolves only `from time import x [as y]`. `from datetime import datetime as
  DT; DT.now()`, `import time as t; t.time()`, and `asyncio.get_running_loop().time()` all pass.
  The same alias hole is in `time_contract_violations` (`test_demo_probe_cli.py:860-897`).
- `signed_send_violations` matches only the literal chain `self._sdk.rest_api.<name>`;
  `getattr(self._sdk.rest_api, name)` or `rest = self._sdk.rest_api; rest.new_order(...)`
  bypasses it.
- `_function_nodes` (`test_demo_probe_cases.py:1827`) keys functions by bare name, so a nested
  function reusing a name (for example a local `sleep`) silently replaces the analysed node.
**Fix:** Reuse the stricter normalizer rule set for the adapter and manager (forbid `repr`,
f-strings of exception names, `.args`, `getattr(..., "error_message")`). Resolve import aliases
for `time`, `datetime` and `asyncio`, and add `loop.time` to the call list. Extend the send guard
to `getattr(<rest_api>, ...)` and to local aliases of `rest_api`. Key `_function_nodes` by
qualified name. Add one negative control per new rule.

### WR-08: The cancel-retry ceilings are not actually asserted

**File:** `tests/test_binance_usdm_error_routing.py:57, 405-428`
**Issue:** The module docstring says cancel retries "within the four `_RECONCILER_CANCEL_*`
ceilings". The test imports `MAX_ATTEMPTS` from `src` and asserts call count against that
same value, so the attempt ceiling follows whatever `src` holds (it would pass for 1 or for 1000).
The other three ceilings (`_MAX_DELAY_SECONDS=30`, `_WAIT_MULTIPLIER_SECONDS=1`,
`_WAIT_MAX_SECONDS=10`, `src/adapters/binance_usdm.py:142-145`) are never referenced, and the
values recorded in `sleep.waits` are never inspected, only their count. A regression to a zero
wait, an uncapped exponential wait, or a changed attempt count passes every test.
**Fix:** Assert the literal expected schedule, for example
`assert sleep.waits == [1, 2]` for three attempts under the current constants, and a separate
case with more attempts proving the 10 s cap, or assert the four constants against the owner
record in one dedicated test.

### WR-09: The stateful exchange fake returns a different shape than the real adapter

**File:** `tests/support/fake_binance_exchange.py:170, 190, 207-213`; `src/execution/manager.py:232-233`; `src/adapters/binance_usdm.py:359-398`
**Issue:** The module docstring promises the fake "can never drift from the production surface",
but only the call kwargs are bound (`_bind_real`). The return values differ: the real
`place_entry` returns `EntryPlacementResult` (attribute `exchange_order_id`), the fake returns
`{"order_id": ..., "status": ...}`. The manager reads
`_get_attr_or_key(response, "exchange_order_id") or _get_attr_or_key(response, "order_id")`, so
the `order_id` fallback exists in production code only to serve this fake; the real, primary
path is not exercised by the eight modules that use the fake (write-ahead, exactly-once,
replay, recovery). `query_order_by_client` also reports `update_time_utc` as the creation time
even after a fill.
**Fix:** Return `EntryPlacementResult` and `AlgoPlacementResult` instances (all fields) from the
fake, then remove the `order_id` fallback from the manager. Update `update_time_utc` on `fill()`
and `cancel()`.

### WR-10: Two refusal tests pass for any failure of the right type

**File:** `tests/test_binance_limits.py:527-532`; `tests/test_binance_secret_redaction.py:129-134`
**Issue:**
- `test_a_section_that_is_not_a_table_is_refused` expects `LimitsNotRatified` with
  `match="stream"`. The constructed file also lacks the whole `[stream]` table (renamed to
  `[stream_x]`), so a missing-key message `stream.event_queue_max`, an unknown-section message
  for `stream_x`, or a provenance message all contain "stream". The test passes even if the
  loader has no "section is not a table" check at all.
- `test_file_loading_refused_inside_the_repository_through_a_relative_hop` asserts only that some
  `CredentialError` is raised and takes an unused `tmp_path`. It does not check the message, so
  it also passes if the `..` hop is refused as "relative path" or "unreadable" rather than "inside
  the repository", which is the property named in the test.
**Fix:** For the first, write a file where only `stream` is a scalar and every other table is
valid (do not rename the table), and match the exact key text the loader emits. For the second,
assert `"repository" in message` and that the path is not echoed, as the sibling test does.

### WR-11: Tests whose names claim more than they check

**File:** `tests/test_binance_ratelimit_gate.py:317-319`; `tests/test_demo_probe_evidence.py:273-281`; `tests/test_demo_rehearsal_safety.py:760-766`
**Issue:**
- `test_one_gate_is_safe_to_share_across_threads` only asserts that a private attribute is a
  `threading.Lock`. It exercises no concurrency, and an `RLock` or a lock that is never taken
  would fail or pass independently of thread safety.
- `test_every_listed_status_is_accepted` checks the `CASE_STATUSES` set and then accepts only an
  OBSERVED case. NOT_OBSERVED, ERROR and `SKIPPED_DRY_RUN` are never fed to
  `check_probe_evidence` as accepted statuses.
- `test_live_orders_stay_disabled_by_default` (a rehearsal safety item, SR-3) builds a
  `LiveEnablementController` and asserts `dr is not None`; it never touches the rehearsal runner,
  so it cannot detect the runner enabling live orders.
**Fix:** For the first, run N threads recording and checking concurrently against one gate and
assert a consistent restriction, or rename the test to what it checks. For the second, loop over
`dp.CASE_STATUSES` with a minimal valid case for each. For the third, run the tracer with the
real controller wired in and assert `is_disabled` afterwards, and drop `assert dr is not None`.

## Info

### IN-01: Helper classes copied across files

**File:** `tests/test_binance_ratelimit_gate.py:52`, `tests/test_binance_usdm_error_routing.py:72`, `tests/test_binance_usdm_signed_calls.py:90`, `tests/probe_fakes.py:130`, `tests/test_clock_drift.py:25`
**Issue:** `VirtualClock` is defined five times (and `tests/support/virtual_time.py` is a sixth
clock). `_Response`/`_FakeResponse`/`FakeResponse` exist in six files, and `_payloads` (about 45
lines) is duplicated line for line in the error-routing and signed-call modules. A change to an
SDK payload shape must be made in each copy.
**Fix:** Move one `VirtualClock`, one `FakeResponse`, one `sdk_payloads()` and `RecordingSleep`
into `tests/support/`.

### IN-02: Random secrets in redaction tests

**File:** `tests/test_binance_secret_redaction.py:43-44, 248, 285`
**Issue:** `secrets.token_hex(32)` and `secrets.token_urlsafe(48)` give each run different input.
Project rules require deterministic tests, and assertions such as `scrub(text) == text`
(line 233, "no rule matches these names") depend on the generated text not resembling any
shape rule. A fixed, obviously fake value of the right length and alphabet gives the same
coverage without run-to-run variation.
**Fix:** Use fixed 64-character fake constants (one hex, one alphanumeric) with a comment.

### IN-03: Offline socket guard misses some connect paths

**File:** `tests/test_demo_probe_cli.py:69-102`; `tests/test_demo_probe_evidence.py:38-73`
**Issue:** The guard overrides `socket.connect` only. `connect_ex` and UDP `sendto` are not
guarded, and on Windows (the development platform) asyncio's Proactor loop connects through
`ConnectEx`, which bypasses `socket.connect`. Today the `getaddrinfo` patch still stops
hostname-based attempts, but an IP-literal destination would not be caught.
**Fix:** Also override `connect_ex` and `sendto`, and add a test that an IP-literal
`loop.create_connection` is refused.

### IN-04: Cross-test-module coupling through private helpers

**File:** `tests/test_binance_usdm_signed_calls.py:975-995`
**Issue:** `_attach_inputs` imports six underscore-prefixed builders from
`tests.test_execution_attach`. Renaming or splitting that module breaks this one with an
`ImportError` at test time.
**Fix:** Move the builders to `tests/support/` and import them from there.

### IN-05: Duplicate tests

**File:** `tests/test_adapter_not_found_mapping.py:134-139`; `tests/test_adapter_strictness.py:407-413`; `tests/test_demo_rehearsal_safety.py:378-388`; `tests/test_binance_client_config.py:226-231`
**Issue:** `test_a_code_number_inside_other_text_is_not_not_found` repeats two cases of the
parametrized `test_every_other_error_reraises_the_same_object` with a weaker assertion (no
identity check). `test_invalid_symbol_predicate` repeats the invalid-symbol lines of
`test_public_rate_limit_and_symbol_helpers_still_behave`. The transport-level Demo-host test
exists twice (client config and rehearsal safety), and
`test_demo_and_live_credential_names_differ` also exists in the ratified-file module.
**Fix:** Delete the weaker copies.

### IN-06: Prose-pinning and re-typed owner values

**File:** `tests/test_exchange_errors.py:457-484, 752-815, 818-832, 719-723`
**Issue:** Many tests assert that long sentences appear inside `entry.note` and inside a
`docs/SOURCES.md` table cell. Any wording edit fails them while behaviour is unchanged, and they
carry the same expectation a third time in `_EXPECTED_BY_CODE`. `test_no_users_number_is_a_module_constant_of_src`
types the owner's values (`"259200"`, `"120"`) as literals, which the sibling modules avoid by
parsing the record.
**Fix:** Keep one assertion per fact (category, evidence label, dates) and reduce note checks to
a few anchor tokens. Parse the two numbers from the decision record.

### IN-07: Remaining SDK-shaped fakes accept any arguments

**File:** `tests/test_binance_usdm_error_routing.py:184-194`; `tests/test_binance_ratelimit_gate.py:354-365`; `tests/test_adapter_not_found_mapping.py:43-46`; `tests/test_execution_adapter_contract.py:60-83`; `tests/test_demo_rehearsal_safety.py:96-171`
**Issue:** These fakes take `*args, **kwargs` and do not bind to the installed SDK or adapter
signature. The signed-call and probe-contract modules do bind, so the risk is covered for the
signed methods, but the error-routing and gate tests rely on that being true elsewhere. The
file-level docstring of `test_execution_adapter_contract.py` says wire-level parameters are
pinned, yet `_RecordingRest.new_algo_order(**kwargs)` is not checked against the SDK signature.
`@pytest.mark.asyncio` markers in that file are redundant under `asyncio_mode = "auto"`.
**Fix:** Have the shared fake (see IN-01) bind every call with `inspect.signature(...).bind`
against `DerivativesTradingUsdsFuturesRestAPI`, and use it in these modules.

### IN-08: The limits-file writer silently creates entries an override should only change

**File:** `tests/support/limits.py:231-236, 270-273`
**Issue:** The docstring says `overrides` "changes an existing entry" and `extra` "adds one", but
`_apply` uses `setdefault` for both. A misspelled override key in a test therefore adds an unknown
key and the test then fails (or passes a refusal assertion) for the unknown-key reason instead of
the intended one. `float` values `nan`/`inf` would render as invalid TOML.
**Fix:** In `overrides` raise `KeyError` when the key is absent; in `extra` raise when it is
present.

### IN-09: Misleading case label and dead defensive code

**File:** `tests/test_binance_usdm_error_routing.py:396, 626`; `tests/test_binance_client_config.py:80-85`
**Issue:** The case `("client_408", ClientError("timeout", None))` passes a `None` status, so no
408 is exercised; the label suggests the retry-on-408 rule is covered. The autouse
`_clean_runtime_secrets` fixture does `getattr(redaction, "clear_runtime_secrets", None)`, but
the function exists, so a later removal would silently turn the cleanup into a no-op instead of
failing.
**Fix:** Rename the case to `client_error_no_status`, or pass a real 408 through the SDK
`send_request` stub as `test_exchange_errors.py` does. Call `redaction.clear_runtime_secrets()`
directly.

---

_Reviewed: 2026-10-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_


# Part: tests part B

Finding ids are scoped to this part (source file `18-REVIEW-tests-b.md`).

# Phase 18: Code Review Report (tests, batch B)

**Reviewed:** 2026-10-19
**Depth:** deep (each test cross-read against the src module, the fakes, the SDK-contract tests and the shared `tests/support/*` helpers)
**Files Reviewed:** 27
**Status:** issues_found

## Summary

The batch is strong. `ruff check` and `ruff format --check` are clean on every file. Assertions generally bind real behaviour: the SDK fakes are pinned to the installed SDK by `test_userdata_contract.py` (with negative controls), the replay and recorded-frame proofs fold through the unchanged `fold_fills`, the redaction tests use run-time secrets and report lengths only, and the supervisor tests run on virtual time with `asyncio.sleep` poisoned. I traced the jittered tenacity waits (`wait_random_exponential`) in the supervisor tests and found every timing assertion is bounded independently of the jitter, so I found no flaky test.

No BLOCKER was found. The findings below are tests that cannot fail for the regression they claim to guard (WR-01, WR-02, WR-03, WR-04), safeguards that would damage committed evidence or be silently unenforced when they regress (WR-07, WR-08), and tests whose pass/fail depends on the working directory or on `.planning/` artifacts that the GSD tooling itself archives or filters out (WR-05, WR-06).

## Warnings

### WR-01: `test_connection_listener_failure_never_reaches_the_sdk` cannot fail (the fake swallows the exception)

**File:** `tests/test_userdata_adapter.py:708-717` (fake at `tests/userdata_fakes.py:83-109`)
**Issue:** The test installs a listener that raises, emits a `close` event and asserts nothing. The fake's `_invoke_connection_callback` wraps `callback(*args)` in `try/except Exception` and logs (copying the SDK). The transport (`_emit_connection`, `src/adapters/binance_userdata.py:511-519`) and the adapter (`_on_connection_event`, line 751-758) each have their own `try/except` as well. Removing the adapter's guard, the transport's guard, or both leaves this test green, because the fake is the third layer. The same hole applies to every "never raise into the SDK" branch: a grep over `tests/` finds no assertion on any of `userdata.connection_listener_failed`, `userdata.connection_sink_failed`, `userdata.message_sink_failed` or `userdata.raw_callback_failed`. Message callbacks are called directly by `emit_user_event` (no fake-side guard), so those branches are testable, but no test makes a message sink or `_enqueue` raise.
**Fix:** Capture the structlog event and assert it, so the test needs the project guard:
```python
with capture_logs() as logs:
    ws.emit_connection_event("private", "close")
assert [e for e in logs if e["event"] == "userdata.connection_listener_failed"] == [
    {"event": "userdata.connection_listener_failed", "error_type": "RuntimeError", "log_level": "error"}
]
```
Also call `adapter._on_connection_event("close")` directly (no fake in the path) and add one test per message-sink branch (`transport.set_message_sink(raising)` then `emit_user_event`, expecting no exception and a `userdata.message_sink_failed` entry).

### WR-02: The Windows backslash branch of the SDK log guard and bridge is untested

**File:** `tests/test_userdata_adapter.py:101-102, 984-1033` (source `src/adapters/binance_userdata.py:340-342`)
**Issue:** `_is_sdk_record` normalises `record.pathname.replace("\\", "/")` before matching `/binance_common/` and `/binance_sdk_`. Project development is on Windows (`C:\...\site-packages\binance_common\websocket.py`), where this normalisation is the only reason the guard matches at all. Every test pathname is a forward-slash string (`TEST_ONLY_SDK_PATHNAME`, `TEST_ONLY_FOREIGN_PATHNAME`). Deleting the `.replace` leaves the whole file green while the noise guard and the log bridge stop working on the platform the owner uses, so the account-data and listenKey-bearing SDK INFO lines (T-18-28) would reach the log. `grep` confirms no backslash pathname anywhere in `tests/`.
**Fix:** Parametrize the guard and bridge tests over both separators:
```python
@pytest.mark.parametrize("pathname", [
    "C:/x/site-packages/binance_common/websocket.py",
    r"C:\x\site-packages\binance_common\websocket.py",
])
```
and add a foreign backslash path as the negative control.

### WR-03: `test_phase18_evidence_is_reported_not_required` is a tautology

**File:** `tests/test_phase18_gate.py:161-166`
**Issue:** `present` and `absent` are a partition of `PHASE18_EVIDENCE`, so `assert sorted(present + absent) == sorted(PHASE18_EVIDENCE)` is true for any filesystem state. The test can never fail; it only prints. It is also the only place the gate documents that evidence is optional, while `PHASE18_ARTIFACTS` (same file, lines 128-137) hard-requires other `.planning/` files.
**Fix:** Either drop the test and keep the print as a `capsys`-less report, or assert something real, e.g. that every optional path is a relative path under `.planning/` or `tests/fixtures/` and that no path appears in both tuples (`assert not set(PHASE18_EVIDENCE) & set(PHASE18_ARTIFACTS)`).

### WR-04: The "no unratified default" scan is bypassed by upper-case constants and positional constructor arguments

**File:** `tests/test_no_unratified_defaults.py:105-129` (`hit` compares `name in GUARDED_NAMES`)
**Issue:** `GUARDED_NAMES` holds the 30 lower-case keys. A module constant such as `KEEPALIVE_INTERVAL_SECONDS = 1800`, `RECV_WINDOW_MS = 5000`, or `StreamLimits(1800, 3, ...)` (positional) is not matched, so a ratified-looking number can enter `src/` or `scripts/` and the scan, `test_invariant_5` of the phase gate and the "ALLOW_LIST is empty" claim all stay green. The supervisor test itself uses exactly `KEEPALIVE_INTERVAL_SECONDS = 1800` as its negative control (`tests/test_userdata_supervisor.py:1226-1228`), which shows the form is recognised as a violation there but not here. No scanner self-test covers an upper-case form (`_FORBIDDEN_FORMS` is lower-case only). Today no such constant exists in `src`/`scripts` (checked by grep), so this is a latent guard hole, not a current violation.
**Fix:** Compare `name.lower()` against `GUARDED_NAMES` (and the upper-case spelling of each guarded name), add `"upper-case constant": "KEEPALIVE_INTERVAL_SECONDS = 1800\n"` and `"class attribute": "class C:\n    RECV_WINDOW_MS = 5\n"` to `_FORBIDDEN_FORMS`, and add a check on positional arguments of calls to the limit dataclasses (`BinanceLimits`, `StreamLimits`, `RateLimitPolicy`, `SignedCallPolicy`, `DriftLimits`, `ClientLimits`).

### WR-05: Tests hard-require `.planning/` artifacts that the GSD workflow archives or strips

**File:** `tests/test_phase18_gate.py:47, 128-137, 511-554`; `tests/test_sources_phase18_section.py:84-86, 274-291, 367-370`; `tests/test_fake_binance_semantics.py:48-55, 94-112`
**Issue:** Three modules assert on exact text and on the existence of files under `.planning/phases/18-user-data-stream-error-taxonomy/` (decision records, evidence check files, `18-TRACEABILITY.md`, two limits TOML files). `/gsd-cleanup` archives completed-milestone phase directories and `/gsd-pr-branch` produces branches without `.planning/` commits. After either, `test_phase18_artifacts_exist`, `test_phase18_traceability_*`, `test_run_flags_follow_the_decision_files`, `test_the_probe_check_file_backs_the_three_statuses` and the Demo-subsection tests fail with a missing-path error, not a skip, in CI. `PHASE18_ARTIFACTS` also contradicts the module docstring ("evidence ... reported, never required") for the `.planning/` entries. `test_invariant_8_d055_stays_open` additionally fails the day D055 is legitimately closed in a later phase.
**Fix:** Gate the planning-dependent tests behind one helper that skips with an explicit reason when `ROOT / ".planning" / "phases" / "18-..."` is absent (the repo already has `infra_helpers.infra_skip`), keep the code-and-fixture inventory (`src/`, `scripts/`, `tests/`, `config/`) as hard requirements, and copy any evidence text a test pins into `tests/fixtures/phase18/` so the pin survives archiving.

### WR-06: `ROUTER_PATH` is relative to the working directory

**File:** `tests/test_userdata_rig.py:67, 366-383`
**Issue:** `ROUTER_PATH = Path("src/adapters/binance_userdata_router.py")` is resolved against the process cwd by `forbidden_imports`, `module_imports` and `wall_clock_calls` (they call `Path(path).read_text`). Run from an IDE test runner, `pytest tests/...` from a sub-directory, or any tool that sets another cwd, the two structural guards fail with `FileNotFoundError`. Every other module in this batch anchors on `Path(__file__).resolve().parents[1]`.
**Fix:** `ROUTER_PATH = Path(__file__).resolve().parents[1] / "src" / "adapters" / "binance_userdata_router.py"`.

### WR-07: The recorded-fixtures refusal test targets the real committed evidence directory and covers only one path form

**File:** `tests/test_user_data_smoke_dry_run.py:418-424` (source `scripts/user_data_smoke.py:358-373`)
**Issue:** The negative control passes `uds.RECORDED_DEMO_FIXTURES_DIR` (the real `tests/fixtures/phase18/recorded_demo`) as `--fixtures-dir`. If the guard ever regresses, the dry run writes `dry-run-00x-*.json` and a `provenance.md` into the committed Demo evidence that `test_userdata_recorded_frames.py` pins as "never edited", so the failing test also corrupts the tree it protects. It also checks only the directory root: `recorded_demo/smoke`, `recorded_demo/../recorded_demo/probe` and a relative spelling are the realistic mistakes and are not exercised (`_is_within` resolves paths, so they probably pass today, but nothing pins that).
**Fix:** `monkeypatch.setattr(uds, "RECORDED_DEMO_FIXTURES_DIR", tmp_path / "recorded_demo")`, create the sub-directories there, and parametrize over root, `smoke`, a `..` spelling and (where the platform allows) a symlink; assert exit code `EXIT_REFUSED` and that the directory is still empty.

### WR-08: `test_user_data_smoke_evidence.py` drives the dry run without the no-network and no-sleep guard

**File:** `tests/test_user_data_smoke_evidence.py:50-82, 377-385` (guard exists only in `tests/test_user_data_smoke_dry_run.py:48-105` and `tests/test_user_data_smoke_cli.py:60-93`)
**Issue:** The module-scoped `valid_document` fixture and `test_a_listen_key_printed_during_the_run_fails_the_log_scan` run the complete dry-run pipeline (`uds.main` with `build_dry_run_rig`, waits of 30 s and 60 s in the limits file) with no patch of `asyncio.sleep`, `socket`, `requests` or `build_sdk_client`. If the dry-run rig regressed to the real clock or to a real client, this module would sleep for real or reach Binance instead of failing, against the project rule "tests never hit Binance". The other two smoke modules would catch it, but only if they run in the same job.
**Fix:** Move `no_network_no_sleep` into a shared fixture (for example `tests/support/net_guard.py`) and apply it here; the module-scoped fixture needs a `pytest.MonkeyPatch.context()` around the dry run.

## Info

### IN-01: A test name says the opposite of what it asserts

**File:** `tests/test_stream_records.py:173-181`
**Issue:** `test_distinct_steps_or_sources_give_distinct_records` asserts that a different *source* gives the **same** `journal_event_id` (only the step changes the id). The comment explains the intent (a different source is a journal conflict), so the code is right and the name is wrong.
**Fix:** Rename to `test_distinct_steps_give_distinct_ids_and_a_different_source_reuses_the_id`.

### IN-02: A hard-coded alembic head in an unrelated test

**File:** `tests/test_execution_exactly_once_pg.py:204-206`
**Issue:** `test_pg_db_is_a_generated_migrated_database` asserts `version_num == "0004_persistence_integrity"`. Every future migration breaks an exactly-once test.
**Fix:** Compare with the script directory head (`ScriptDirectory.from_config(...).get_current_head()`).

### IN-03: Hard-coded evidence counts

**File:** `tests/test_userdata_recorded_frames.py:144, 210, 508, 523, 527, 543-545`
**Issue:** `>= 58`, `== 8`, `== 26`, `== 16`, `== 42` pin the exact recorded set. Adding a third capture (the evidence folder is append-only by design) fails six tests for a reason unrelated to the parsers.
**Fix:** Derive the expectations from the loaded `FRAMES` (count by `frame["e"]` / `frame["o"]["x"]`) and keep one test that pins the minimum.

### IN-04: Duplicated test scaffolding

**File:** `tests/test_user_data_smoke_cli.py:35-44`, `test_user_data_smoke_dry_run.py:29-38`, `test_user_data_smoke_evidence.py:31-40`, `test_operator_evidence.py:29-38` (the same TEST_ONLY smoke-limits TOML); `test_userdata_adapter.py`, `test_userdata_supervisor.py`, `test_userdata_rig.py` (each defines `_Factory`, `sdk_stream_map`, `_isolated_redactor`, `real_sleep_calls`, `_inline_worker_thread`); `FakeExecutionAdapter` in `test_execution_attach.py:145` and `test_execution_manager.py:81` and `BinanceSemanticsFakeAdapter._bind_real` (three copies of the signature-binding guard).
**Issue:** Drift between copies is the usual failure mode (WR-08 is one instance: the network guard exists in two copies of three).
**Fix:** Hoist the shared fixtures to `tests/conftest.py` or `tests/support/`, and have the two execution fakes subclass or reuse `BinanceSemanticsFakeAdapter`.

### IN-05: Recorded-but-never-read state in the new SDK fakes

**File:** `tests/userdata_fakes.py:132-145, 188-190, 262-267`
**Issue:** `FakeUserStreamHandle._unsubscribed`, `handles`, `unsubscribed_streams`, `dropped_connection_callbacks` and `unsubscribe` were copied from `tests/paper_ws_fakes.py`; no user-data test (and no src code: the adapter never calls `unsubscribe`) reads them.
**Fix:** Remove them or add the test that needs them; `unsubscribe` must stay (the contract test pins the handle surface).

### IN-06: Plain `RuntimeError` and dict responses in the execution fakes after the SDK-shaped correction

**File:** `tests/test_execution_attach.py:195`; `tests/test_execution_manager.py:106-111, 753, 784, 1769, 100-107`
**Issue:** Plan 18-21 made `BinanceSemanticsFakeAdapter` raise `BadRequestError` with an int code, but these fakes still raise `RuntimeError("duplicate clientAlgoId")`, `RuntimeError("-2019")` and `RuntimeError("-2013 Order does not exist")` (message text standing in for a code, the pattern the phase removed) and return plain dicts where the real adapter returns `AlgoPlacementResult` / an order-ack object; only keyword arguments are bound to the real signature. The manager treats any exception as ambiguous, so results are identical today, and the tests would stay green if Phase 19 wired "-2019 is a definitive reject, do not retry" incorrectly. The comment at `test_execution_manager.py:100-102` ("tests that want the ambiguous path pass `entry_response=None`") is also wrong: `None` selects the non-None default, so a `place_entry` that returns `None` (which `_place_entry_no_blind_retry` treats as ambiguous) is never exercised.
**Fix:** Raise `BadRequestError(msg, -2019)` / `BadRequestError(msg, -2013)` in these tests, return the real dataclasses, and add one test where `place_entry` returns `None`. Fix the stale comment.

### IN-07: `real_sleep_calls` is collected but mostly never asserted

**File:** `tests/test_userdata_supervisor.py:138-148`, `tests/test_userdata_rig.py:121-130`
**Issue:** The autouse fixture makes `asyncio.sleep` raise `AssertionError` and records the call, but only three tests read `real_sleep_calls == []`. An `AssertionError` raised inside a supervisor task is handled by the supervisor's own error paths, so a stray `asyncio.sleep` in most tests would surface as an odd state sequence rather than a clear failure.
**Fix:** Assert `calls == []` in the fixture teardown (`yield calls; assert calls == [], ...`).

### IN-08: Minor coverage gaps

**File:** `tests/test_fake_binance_semantics.py:206-214`, `tests/test_persistence_exit_evidence_pg.py:147-155`, `tests/test_userdata_supervisor.py:364-393, 746, 1105, 1122-1130`
**Issue:** (a) The retention test only shows an *old* CANCELED order is not found; no test shows a *young* CANCELED order is found, so a fake that never returns canceled history passes. (b) The replay test uses identical evidence; `transition_order` returns early when `old_status is new_status` (`src/persistence/entities.py:540-541`) before any evidence check, so a replay with *different* or invalid evidence silently succeeds, and nothing pins that choice. (c) Supervisor tests read private attributes (`_commands`, `_tasks`, `_rotation_task`, `_on_connection_event`), so an internal rename breaks them without a behaviour change.
**Fix:** Add the young-CANCELED positive control; add a test that states the intended result of a replay with different evidence (no-op, or `ValueError`); expose a small public read-only surface (`pending_commands()`, `task_count()`) on the supervisor if the checks are wanted.

---

_Reviewed: 2026-10-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
