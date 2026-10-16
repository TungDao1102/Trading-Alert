---
phase: 16-paper-runtime-composition
reviewed: 2026-10-16T02:20:22Z
depth: deep
files_reviewed: 18
files_reviewed_list:
  - src/paper/runtime.py
  - src/paper/runtime_config.py
  - src/paper/runtime_state.py
  - src/paper/freeze.py
  - src/paper/supervisor.py
  - src/paper/restart.py
  - src/paper/resync.py
  - src/paper/loop.py
  - src/paper/pipeline.py
  - src/paper/live_minutes.py
  - src/paper/market_inputs.py
  - src/paper/bars.py
  - src/paper/surface.py
  - src/paper/vocabulary.py
  - src/paper/replay_inputs.py
  - src/paper/journal.py
  - src/persistence/paper_runtime_state.py
  - src/adapters/paper_ws.py
findings:
  critical: 2
  warning: 12
  info: 8
  total: 22
status: issues_found
---

# Phase 16: Code Review Report (batch 1: runtime, start, pin and restart path)

**Reviewed:** 2026-10-16T02:20:22Z
**Depth:** deep (cross-file: callers in `shadow_runtime.py`, `shadow.py`, `exit_criteria.py`, `coverage.py`, `persistence/engine.py`, `persistence/journal.py`, `adapters/binance_public.py`, the installed `binance_common` SDK and `docker-compose.yml` were read to judge findings)
**Files Reviewed:** 18
**Status:** issues_found

## Summary

The start gate, the admission rule (Q-A), the pin and restore rules, Decimal handling and UTC handling are mostly sound. Secrets are not logged on any path I traced. I found no float in a value that gates an order.

The defects are in long-run robustness and crash consistency. Both matter most for a 14-day unattended soak, because a bug found after the pin forces a new trial:

- **CR-01:** after a WebSocket outage longer than the supervisor's retry budget (about 2 minutes), the process stays up but receives nothing. Nothing in the process fails closed. The `on-failure` restart policy never fires, so coverage is lost until a human notices.
- **CR-02:** heartbeats are committed before the acceptance log (`PAPER_HISTORY_BARS`) that the parity criterion needs. A crash or exception in that window leaves heartbeats that the parity replay can never match, and the trial's parity criterion fails permanently.
- **Warnings:**
  - A startup seam where bars are lost with no gap record, followed by a history lockout of up to 200 bars.
  - A state-port database engine without timeouts.
  - A lost SHADOW signal on a crash between the heartbeat and the SHADOW write.
  - The shutdown order.
  - Gap-record id collisions that crash the loop.
  - A retry wiring that never matches the SDK's error types.
  - No single-instance guard.
  - The runtime configuration is not pinned to the epoch.
  - Two configuration keys whose contract the code contradicts.
  - The exit-0-on-SIGTERM interplay with `restart: on-failure`.
  - An exchangeInfo refresh that fails because of unrelated symbols.

Counts: 2 Critical, 12 Warning, 8 Info.

## Critical Issues

### CR-01: A WebSocket that cannot be rebuilt leaves the process up and deaf. Nothing fails closed.

**Files:**
- `src/paper/supervisor.py:374-414` (`_recover_from_drop`, `_rebuild_with_retry`)
- `src/paper/runtime.py:690-730` (`_LiveLoop.run`)
- `src/paper/runtime_config.py:104-109` (`max_ws_message_silence_seconds` is read only by `coverage.py`)
- `src/adapters/paper_ws.py:426-459`

**Issue:**
- On an SDK `close`/`error` event, `_rebuild_with_retry` runs `ws.rebuild()` under `stop_after_attempt(7) | stop_after_delay(120)`. When that is exhausted it logs `reconnect_exhausted`, runs one backfill and returns. Nothing ever retries again.
- `rebuild()` has already closed the old client. The SDK's own reconnect is gone, and the new client holds no connection. No further SDK event can arrive.
- The live loop has no silence watchdog. `max_ws_message_silence_seconds` (ratified at 3900) is only used post hoc in `coverage.py`. The supervisor has no sink to report exhaustion, and `_LiveLoop` never fails closed on it.
- The SDK's `ws_connect` uses `autoping=False`, no heartbeat and no receive timeout (`binance_common/websocket.py:247-255`). A half-open TCP connection is only detected after kernel retransmission timeouts.
- The test `test_rebuild_exhaustion_still_backfills_and_reports_ws_disconnected_gaps` (tests/test_paper_supervisor_backfill.py:490) asserts this end state as correct. No test covers the process after exhaustion.

**Failure scenario:**
1. A Binance futures maintenance window, a DNS failure or an ISP or VPC outage lasts longer than about 2 minutes.
2. The supervisor gives up. The process keeps running: the consumer is idle, the Telegram poller runs and the constraints refresh runs.
3. The healthcheck turns unhealthy after 3900 s, but Docker does not restart unhealthy containers, and `restart: on-failure` only reacts to an exit.
4. Every hour after that is uncovered. The 95 % coverage criterion allows about 16.8 uncovered hours in 14 days, so one night of this fails the trial.

**Fix:** fail closed (exit 7, restartable, recorded as a CRASH gap) when the feed cannot be recovered or goes silent. For example:

```python
# supervisor.py: report exhaustion through a sink instead of only logging it
if await self._rebuild_with_retry():
    ...
else:
    reason = GapReason.WS_DISCONNECTED
    await self._backfill_and_emit(reason)
    self._call_sink("on_fatal", self._on_fatal, "WebSocket rebuild exhausted")

# runtime.py (_LiveLoop): map it to the existing fail-closed path
def _sink_fatal(self, reason: str) -> None:
    self._fail(RuntimeFailClosed(reason))
```

Also add a watchdog task in `_LiveLoop.run`. It records the monotonic time of the last WS message, forming updates included (the supervisor's kline handler can stamp it before the `is_closed` filter). It calls `_fail(RuntimeFailClosed("market stream silent"))` once the silence exceeds a user-owned bound, for example `max_ws_message_silence_seconds` or a new ratified key.

### CR-02: Heartbeats are committed before the acceptance log they depend on. A crash mid-batch fails the parity criterion permanently.

**Files:**
- `src/paper/pipeline.py:377-379` (4h live heartbeat written right after `_accept`)
- `src/paper/pipeline.py:382-397` (sibling-missing gap and heartbeat)
- `src/paper/pipeline.py:494-505` (DATA_STALE and WARMUP heartbeats)
- `src/paper/pipeline.py:312` and `:428-445` (`_flush_history` runs only at the end of `handle`, or just before an evaluated bar's inputs at `:533`)
- Consumer: `src/paper/exit_criteria.py:1113-1127`

**Issue:**
- `_accept` only appends the bar to the in-memory `_pending` list. The `PAPER_HISTORY_BARS` record that carries it is written at the end of `handle`, or when a later 1h bar of the same batch is evaluated.
- Each record is its own transaction (`PgRuntimeState.record` -> `PgJournalStore.record`). So a 4h context heartbeat, or a DATA_STALE or WARMUP_INSUFFICIENT heartbeat, is durably committed while its acceptance-log entry is still in memory.
- The parity check requires every non-pipeline-only heartbeat to be a `LIVE_WS` entry of its run's acceptance log (`exit_criteria.py:1124-1126`). Otherwise parity fails.
- The existing crash test (`tests/test_paper_replay_inputs.py:754`) only covers a crash between the inputs and the heartbeat of an evaluated bar. That path flushes first, so the case above is not tested.

**Failure scenario:**
1. At a 4h boundary one batch holds the 4h live closes and the 1h closes. `group_by_close` handles the 4h bars first, so their heartbeats are committed.
2. Before the first 1h evaluation flushes the log, any of these ends the batch:
   - an exception: the risk-inputs port, a `_conflict` `ValueError`, a `RuntimeRecordConflict` from a gap write (WR-05), or `fetch_4h_bar` raising after the SDK's retries;
   - a database error;
   - an OOM kill, a SIGKILL or a host crash.
3. The process exits 7 and restarts with a new run whose log starts at `accept_seq` 0.
4. The committed 4h heartbeats never get a log entry. The parity criterion reports "the bar is not a LIVE_WS entry of its run's acceptance log" for the rest of the epoch, and the trial must be re-pinned.

**Fix:** make the log durable before anything that references it. The simplest change is to flush at the start of every record write that names an accepted bar:

```python
def _write_heartbeat(self, bar, candle, now_utc, surface, batch) -> None:
    self._flush_history(now_utc, batch)   # the acceptance log first (crash-consistent)
    record = RuntimeRecord.bar_processed(...)
    ...

def _write_gap(self, gap, detail, now_utc, batch) -> None:
    self._flush_history(now_utc, batch)
    ...
```

The record ids stay unique (`history:<at_ms>:<history_seq>`, with `history_seq` incremented per flush), and the evaluator already concatenates and sorts the entries by `accept_seq`. The alternative is a `record_many` port method that writes the whole batch in one transaction. Add a test that raises inside `handle` after a 4h heartbeat and asserts that the bundle still passes parity.

## Warnings

### WR-01: Bars that close between the warm-up snapshot and the first subscription are lost with no gap, and the hole then blocks evaluation for up to 200 bars.

**Files:**
- `src/paper/runtime.py:857-863` (snapshot and `warm_up`) and `:691-706` (restore, Telegram start, then `supervisor.start()`)
- `src/paper/supervisor.py:216-239` and `:330-335`
- `src/adapters/paper_ws.py:298-301`
- `src/paper/restart.py:16-21` (the docstring claims the seam is verified)
- `src/paper/pipeline.py:541-555`

**Issue:**
- The REST warm-up is taken at `snapshot`. The supervisor subscribes only after the restore writes, the warm-up `handle` (about 6,500 bars plus one PAPER_HISTORY_BARS record of roughly 2 MB), the Telegram start and the WS connect. That is several seconds.
- The restart docstring says "the verification backfill that the initial connection event triggers" closes this seam. In production that event is never acted on:
  - `PaperWsAdapter.connect()` re-applies the callbacks after `create_connection`.
  - The SDK invokes an `open` callback synchronously at registration when the connection is already open (`binance_common/websocket.py:605-606`).
  - At that moment `PaperSupervisor._started` is still False (it is set at line 239), so `_on_sdk_event` ignores the event (line 332).
  - The restart test fires `open` by hand after the four handles exist (`tests/test_paper_runtime_restart.py:546-549`), which hides this.
- A closed kline whose final `x=true` message was pushed before the subscription is never delivered. The cursor sits at the warm-up's newest close, and the next live close simply advances it, because `_deliver_live` has no contiguity check.
- No PAPER_GAP is written. The restart's `downtime_gaps` only covers closes up to the snapshot, and later restarts key on the last processed close, which is past the hole.
- `_history_is_continuous` then rejects every live 1h bar of each affected symbol as `HISTORY_DISCONTINUITY` until the hole leaves the checked tail: 201 1h bars (about 8.4 days). A 4h hole stays inside the 200-bar 4h tail (33 days), which is the rest of the trial. Only another restart's REST warm-up heals it, and nothing triggers one.

**Fix:**
- After `await self._supervisor.start()`, run one verification backfill from the seeded cursors through the existing path, under the recovery lock, with `GapReason.WS_RECONNECT_WINDOW`. Alternatively, set `_started` before `connect()` and let the `open` echo schedule it.
- Correct the restart docstring.
- Consider also scheduling a REST re-warm of the missing closes when the pipeline records HISTORY_DISCONTINUITY. The bars stay history-only, so Q-D is unaffected.

### WR-02: The runtime state port bypasses `make_sync_engine`: no statement, connect or TCP timeouts, no `pool_pre_ping`, no UTC session pin.

**Files:**
- `src/paper/runtime.py:268-281`
- Compare `src/persistence/engine.py:97-137`, whose docstring explains why each of these settings exists.

**Issue:**
- `_state_from_env` builds `create_engine(url, future=True)`. Every heartbeat, gap, tick-stats, history and marker write, and every healthcheck read, goes through this engine.
- The SHADOW stores, in the same process, use `make_sync_engine`. Only the state port runs without the hardening.

**Failure scenario:**
- A blackholed or half-open database connection blocks `asyncio.to_thread(self._state.record, ...)` with no bound. The consumer wedges, and the process stays up without failing closed.
- On SIGTERM, `_shutdown` waits on `_idle` until Docker's 30 s SIGKILL, so no RUNTIME_STOP is written.
- After a PostgreSQL container restart, the first write uses a stale pooled connection and raises `StoreUnavailable`. That is an avoidable exit 7 and a CRASH gap; `pool_pre_ping` would reconnect transparently.

**Fix:**

```python
from src.persistence.engine import make_sync_engine
return PgRuntimeState(OperationalDatabase(make_sync_engine(url)))
```

`make_sync_engine` already normalises `postgresql://` URLs. Keep the import local.

### WR-03: A risk-passed bar is recorded as processed before the SHADOW chain persists its signal. A crash in between loses the signal for good.

**Files:**
- `src/paper/runtime.py:597-625` (the pipeline writes the heartbeat with `stage=risk_passed` and `plan_hash` -> tick-stats write -> `self._shadow.on_result(result)`)
- `src/paper/shadow_runtime.py:439-487`

**Issue:**
- The signal, the plan and the PENDING approvals are written only inside `send_shadow_alert`, after two other durable writes. A failed tick-stats write, a kill or an OOM in that window leaves a heartbeat that claims `risk_passed` with a `plan_hash` that has no signal or plan row.
- On restart the bar is in the warm-up history (`_seen`), so it is never re-evaluated, and nothing compares the heartbeats against the SHADOW stores.

**Failure scenario:** the only signal of a day is never alerted or attributed. The evidence shows a plan hash with no plan, which violates "no missing journal row" (L-04).

**Fix:**
- Either persist the SHADOW parents (signal, plan, approvals) before the heartbeat of a risk-passed bar,
- or add a restart step: in `ShadowCoordinator.restore()`, find PAPER_BAR_PROCESSED records with `stage == "risk_passed"` whose `plan_hash` has no plan row, and re-drive them (or journal them explicitly as lost).

### WR-04: The shutdown stops the Telegram application before the in-flight batch has finished, so the alert of a signal evaluated during a planned stop is never delivered.

**File:** `src/paper/runtime.py:732-748`

**Issue:** `_shutdown` awaits `self._supervisor.stop()`, then `self._shadow.stop()` (updater stop, application stop, shutdown), and only then `self._idle.wait()`. If a batch is running, its `on_result` runs against a stopped application:
- `_send_bounded` classifies the error and journals `SHADOW_ALERT_FAILED`. It never raises.
- The approvals stay PENDING, and the restart sweep later expires them.

**Fix:** drain first: `await self._supervisor.stop(); await self._idle.wait(); await self._shadow.stop()`. Stopping the feed first already guarantees no new batch starts. Keep the cancellation of the remaining tasks after that.

### WR-05: PAPER_GAP ids are keyed on (epoch, pair, close), but the payload carries writer-specific `source` and `reason`, so a second writer crashes the loop with `RuntimeRecordConflict`.

**Files:**
- `src/paper/runtime_state.py:231-238`
- `src/paper/runtime.py:419-432` (`source: SUPERVISOR`)
- `src/paper/pipeline.py:561-590` (`source: REST_BACKFILL`, `FETCHED_4H_SIBLING` or `NO_4H_SIBLING`)
- `src/paper/supervisor.py:459-484`

**Issue:** two paths are reachable.
- **(a)** A supervisor backfill for a pair raises, for example REST failing for the whole retry budget. The supervisor emits gaps (`source: SUPERVISOR`) for every expected close but leaves the cursor where it was. The next connection event before the next live close re-fetches the same closes. They reach the pipeline as REST_BACKFILL, and `_skip_backfilled` writes a PAPER_GAP with the same id but a different payload.
- **(b)** The pipeline records a missing 4h sibling (`EXCHANGE_NO_CANDLE`, `NO_4H_SIBLING`) at close C, while the supervisor's 4h cursor stays before C. A reconnect within the next 4 h either backfills C (pipeline gap with a different reason and source) or emits its own gap for C (supervisor gap).

Either way `RuntimeRecordConflict` reaches `_fail`, and the process exits 7.

**Fix:**
- Write at most one gap per close across writers. Keep the writer label out of the hashed payload (put it in a separate non-identity field, or use a separate event type for the provenance).
- Or have each writer check `recorded_gaps` and the pipeline's own gap set before writing, keeping the first one ("first writer wins", as `downtime_gaps` already does).
- Advance or mark the supervisor cursor for closes it has already reported as gaps.

### WR-06: The minute poller's "one retry on a transient error" never applies to real SDK errors, so one Binance 5xx while a position is open crashes the runtime.

**Files:**
- `src/paper/live_minutes.py:229`, `:343-346`
- Callers: `src/paper/shadow_runtime.py:367-372` (no `transient_errors` passed) and `src/paper/runtime.py:679-688`

**Issue:**
- The default `transient_errors=(TimeoutError, ConnectionError)` does not match what `BinancePublicMarketData` raises. `binance_common` raises `NetworkError` after its own retries and `ServerError` on any 5xx without retrying. Both subclass `binance_common.errors.Error(Exception)`.
- The documented single retry therefore never happens. A poll error ends `run_poller`, `_run_shadow_poller` calls `_fail`, and the process exits 7.
- While a SHADOW position is open the poller makes 2 REST calls per symbol every 2 s (about 86,000 calls per symbol per day). Any 5xx means a crash, a restart, a CRASH coverage gap and a rebuilt in-memory minute source.

**Fix:** pass the SDK's transient types from the composition root:

```python
from binance_common.errors import NetworkError, ServerError, TooManyRequestsError
LiveMinutePoller(..., transient_errors=(NetworkError, ServerError, TimeoutError, ConnectionError))
```

Better still, keep the SDK types inside the adapter and have it raise a project `TransientMarketDataError`. Do not retry `TooManyRequestsError` immediately: back off instead.

### WR-07: No single-instance guard per epoch. Two runtimes on one epoch conflict and fight over the Telegram bot.

**File:** `src/paper/runtime.py:1060-1145`

**Issue:**
- `--pin-epoch` does more than pin: it continues into the full live loop. The only way to pass the flag is a one-off `compose run`, while restarts use the `paper` service.
- If the service is started (`up -d`) while the pin container still runs, or if `compose run` is repeated without the flag, two processes run the same epoch:
  - Their PAPER_BAR_PROCESSED payloads differ in `tick_time_utc`, so the second writer gets `RuntimeRecordConflict` and exits 7. The restart policy brings it back, and the conflict repeats every hour.
  - Both poll `getUpdates` with one token (Telegram `Conflict`), and both may send alerts.
- Nothing in the code prevents this (no advisory lock or lease).

**Fix:**
- Take a session-level PostgreSQL advisory lock keyed on the epoch id (or a fixed paper-runtime key) right after admission, and refuse with a hold-able code when it is already held.
- Optionally make `--pin-epoch` pin and exit, so the managed service is the only live instance.

### WR-08: The ratified runtime configuration is not pinned to the epoch. A mid-trial edit is accepted silently.

**Files:**
- `src/paper/runtime.py:1030-1031`
- `src/paper/runtime.py:323-339` (the `EPOCH_PINNED` and `RUNTIME_START` payloads carry no config identity)
- `src/paper/restart.py:386-427`

**Issue:**
- The config file says "A changed value is a new configuration version and a new qualifying trial (REV-07)". Plan 16-43 records the config sha256 only by hand.
- The runtime reloads `PAPER_RUNTIME_CONFIG` on every start and never compares it with what the trial started with. A changed `risk_rate`, `symbols` or `initial_equity`, or a different file named by the environment variable, takes effect after any restart with no record and no refusal. Parameter sets are hash-locked; this config is not.

**Fix:**
- Store `sha256(file bytes)` (and the path) in the `EPOCH_PINNED` payload and in every `RUNTIME_START`.
- In `check_epoch_consistency`, refuse with `ADMISSION_OR_EPOCH_MISMATCH` when the current file's hash differs from the pinned one.

### WR-09: `rest_backfill_depth_bars` is a required, ratified key that no code reads.

**Files:**
- `src/paper/runtime_config.py:117`, `:152`
- `src/paper/resync.py:215-256` (hard-coded `limit=1500` and a 200-page cap)
- `config/paper/README.md:39`

**Issue:**
- The README defines it as "how many bars a REST backfill reads". `_refuse_unknown_keys` justifies itself with "A key no code reads is refused: an unused threshold is a value nobody ratified for a use". This key is exactly that: ratified (1500), required, and with no effect.
- The resync pages up to 200 × 1500 bars, so the real depth differs from the ratified one. A future change to the value would silently change nothing.

**Fix:**
- Either wire it: pass `config.timing.rest_backfill_depth_bars` through the supervisor to `backfill_missed_closes`, and record a gap for closes beyond the depth.
- Or remove the key through a new config version and decision record.

### WR-10: `minute_close_lag_seconds = 0` passes config validation but crashes the poller, which turns into a restart loop.

**Files:**
- `src/paper/runtime_config.py:129-131`, `:186`
- `src/paper/live_minutes.py:235-236`

**Issue:**
- The config contract (README: "may be zero, all others are strictly positive") allows 0. `LiveMinutePoller.__init__` raises `ValueError` for `close_lag_seconds <= 0`.
- `ShadowCoordinator.__init__` builds the poller inside `build_coordinator`. `run_admitted` only catches `ShadowRuntimeError` there, so the `ValueError` escapes `main` as exit 1, after `RUNTIME_START` has already been written (`runtime.py:1139`).
- `on-failure` then restarts it forever, which is the restart loop T-16-110 is meant to prevent.
- The ratified value today is 5, so the defect is latent, but the documented contract and the code disagree.

**Fix:**
- Make the two agree: either reject 0 in `_read_ints` (drop it from `_ZERO_ALLOWED`, and update the README through a decision), or allow `close_lag_seconds >= 0` in the poller.
- Map configuration-shaped errors from `build_coordinator` to `CONFIG_NOT_RATIFIED`, and check them before `RUNTIME_START` is written.

### WR-11: A clean SIGTERM stop exits 0, and with `restart: on-failure` the runtime is not brought back after a host reboot or a Docker daemon restart.

**Files:**
- `src/paper/runtime.py:1145`, `:1155`
- `src/paper/runtime_config.py:15-22`
- `docker-compose.yml:119`

**Issue:**
- When the daemon stops containers during a reboot or a daemon upgrade, the runtime handles SIGTERM, records RUNTIME_STOP and returns `ExitCode.OK`.
- Docker's `on-failure` policy restarts only after a non-zero exit, so after boot the paper container stays exited until someone starts it. The collector uses `unless-stopped` and does come back.
- Confidence: medium. This is Docker's documented on-failure semantics; confirm on the EC2 host with `sudo reboot`.

**Fix:**
- Return a distinct non-zero, non-refusal code for a signal-requested stop (for example `STOPPED_BY_SIGNAL = 8`). Docker does not restart a container stopped by hand with `docker stop`, but does restart a non-zero exit after a daemon restart.
- Or switch the service to `unless-stopped` and keep the SKIPPED case held, like a refusal.
- Either way, record the code in the RUNBOOK table.

### WR-12: One malformed symbol anywhere in exchangeInfo stops the constraint refresh for the five configured symbols.

**Files:**
- `src/paper/market_inputs.py:111-131`
- `src/adapters/binance_public.py:533-537` and `:469-471`
- `src/paper/runtime.py:795-800`

**Issue:**
- `BinancePublicMarketData.exchange_info()` raises when ANY listed contract lacks a filter or an identity field, including settling, delivery or new listings the runtime never uses. `ConstraintProvider.refresh` cannot get its five rows.
- **At start:** "the first exchangeInfo refresh failed" exits 7 after `RUNTIME_START` was written. The process restart-loops for as long as the exchange carries the odd symbol.
- **Mid-run:** `refresh_forever` only logs a warning. After `constraint_snapshot_ttl_seconds` (2400 s) every evaluation is `STALE_CONSTRAINTS` for the rest of the trial.

Failing closed on data the runtime does not use turns one exchange-side oddity into a lost trial.

**Fix:**
- Give the adapter a mode, or a separate method, that validates only the requested symbols and reports drift on the others as a warning.
- `ConstraintProvider.refresh` stays all-or-nothing for its own symbols.

## Info

### IN-01: A closed bar dropped as FUTURE_CLOSE is lost for good, with no PAPER_GAP and no re-queue.

**Files:**
- `src/paper/pipeline.py:296-305`
- `src/paper/runtime.py:1129-1136`
- `src/paper/market_inputs.py:207-218`

**Issue:**
- The supervisor has already advanced its cursor past the bar, so no backfill re-delivers it. It shows up only in PAPER_TICK_STATS counts.
- The resulting hole then triggers the HISTORY_DISCONTINUITY lockout described in WR-01.
- Clock skew is measured once at start and has no threshold (D-35). chrony on EC2 makes this unlikely.

**Fix:** re-submit a FUTURE_CLOSE bar at `close + delta` (like `HeldBar`) instead of dropping it, or record a PAPER_GAP for it.

### IN-02: `write_pinned_state` is not atomic.

**Files:**
- `src/paper/freeze.py:912-928`
- `src/paper/freeze.py:1025-1026`

**Issue:**
- `path.write_text` truncates the file and then writes it, with no temporary file, rename or fsync. A crash or power loss mid-write leaves invalid JSON, and every later start refuses with "the pinned state is unreadable" (exit 6).
- `run_check_cli` overwrites the same file with a new epoch on a rollover.

**Fix:** write to `path.with_suffix(".tmp")`, fsync it, then `os.replace` it.

### IN-03: The continuity gate checks only the last 201 1h bars and 200 4h bars, while the windows hold 1000 and 300 bars.

**File:** `src/paper/pipeline.py:541-555`

**Issue:** a hole older than 200 bars is accepted inside the setup window that `compute_features` reads (EMA recursion over the whole window). Paper and replay agree, because the replay uses the same buffers, but the backtest on the contiguous dataset sees different inputs.

**Fix:** check contiguity over the whole cut window, or document that this is deliberate.

### IN-04: The healthcheck reports healthy when any single pair is fresh.

**File:** `src/paper/runtime.py:957-962`

**Issue:** `max(closes.values())` hides a dead stream for one symbol or interval.

**Fix:** require every configured (symbol, 1h) pair to be within the maximum age.

### IN-05: SHADOW store writes run synchronously on the event-loop thread, contrary to the module docstring.

**Files:**
- `src/paper/runtime.py:39-41` (docstring)
- `src/paper/runtime.py:622-625`
- `src/paper/shadow.py:787-816`

**Issue:** `send_shadow_alert` calls `stores.insert_*` and `record_journal` directly on the loop thread. Each call can block the loop for up to the 10 s statement timeout, which delays WS callbacks and ping handling.

**Fix:** wrap the store calls in `asyncio.to_thread`, or correct the docstring.

### IN-06: SIGTERM before the loop's signal handler is installed kills the process without RUNTIME_STOP.

**Files:**
- `src/paper/runtime.py:400-416`, `:717`, `:1129`, `:1144`

**Issue:**
- The handler is installed only once `_LiveLoop.run` reaches its wait.
- A planned `compose stop` during the clock-skew check, the constraints refresh, the warm-up, the Telegram start or the WS connect uses Python's default SIGTERM action. That restart is then recorded as a CRASH instead of PLANNED_RESTART.

**Fix:** install the handlers at the top of `main` (set an event), and check it between the startup steps.

### IN-07: The minute poller requests `limit=1500` (weight 10) to fetch one or two new minutes, and its source is never trimmed.

**Files:**
- `src/paper/live_minutes.py:49`, `:301-341`
- `src/paper/live_minutes.py:69-126`

**Issue:**
- Each active symbol costs about 600 request weight per minute: 2 calls × 10 weight × 30 polls. That is half of the 2400 per-minute IP budget at `max_open_positions = 2`, before any backfill or warm-up.
- `LiveMinuteSource` is never trimmed. After a gap between positions on a symbol, the next poll re-fetches every minute since the last stored one, up to 20 pages.

**Fix:** use `limit` = (expected minutes + 1), clamped to 1500. Drop minutes older than the earliest active eligibility start.

### IN-08: `assemble_paper_record` drops `mode` and `test_only` on its skip and expired branches.

**File:** `src/paper/journal.py:534-607`

**Issue:** with `mode="SHADOW", test_only=True, skip_reason=...` and no `shadow_outcome`, both rows come back without `mode` or `test_only`. A test record would then read as a production Phase-7 record. This is latent: both current callers (`evidence_export.py:65`, `shadow_runtime.py:927`) pass `shadow_outcome`.

**Fix:** pass `mode=mode, test_only=test_only` on those rows, or reject `mode="SHADOW"` without `shadow_outcome`.

---

_Reviewed: 2026-10-16T02:20:22Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
