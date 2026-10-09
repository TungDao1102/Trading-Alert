---
phase: 16-paper-runtime-composition
plan: 08
subsystem: paper-runtime / supervisor
tags: [supervisor, asyncio, resync, backfill, gap-records, source-tags, binance-sdk, determinism]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-01 (async PaperWsAdapter: connect, subscribe, unsubscribe, close, on_connection, rebuild, last_rebuild; SDK-shaped fakes) and plan 16-03 (src/adapters/binance_public.py with Kline and klines)"
provides:
  - "src/paper/vocabulary.py: SourceTag, HealthState, GapReason, DropReason (FUTURE_CLOSE), RuntimeEventType (including PAPER_TICK_STATS), TaggedBar, GapRecord, INTERVAL_MS"
  - "async PaperSupervisor with explicit symbols and intervals and the sinks on_closed_bar, on_backfill, on_gap, on_connection_event; start/stop/wait_idle; record_close seeding"
  - "resync that returns TaggedBar (REST_BACKFILL) and GapRecord values, anchors expected slots on the exchange grid (no phantom gaps), plus expected_close_times"
  - "tests rewritten on PaperWsAdapter over the SDK-shaped fake client and on live-shaped Binance rows"
affects: [16-17 smoke recorder, 16-21 live proof, 16-22 runtime composition, 16-24 bar pipeline, 16-26 live loop, 16-29 restart and warm-up, 16-38 SHADOW closure guard]

actuals:
  tokens: 18600
  tasks: 3
  commits: 6
plan_head_before: a1d26c878abbe15e325c406e8e1ed69a3045c153
plan_head_after: 0eb1544267348dde7bfecf972a2047c51f2b0a67
commits: 6

tech-stack:
  added: []
  patterns:
    - "SDK connection events are counted and scheduled from the callback (loop thread), recovery runs in a task under a lock; wait_idle() lets the root and tests await it"
    - "Live bars are held while a recovery is pending and delivered after the backfilled bars, so the monotonic cursor can never skip a recoverable bar"
    - "Every sink call is guarded; a refused bar becomes an UNKNOWN GapRecord instead of a silent loss"
    - "Gap records are de-duplicated per (symbol, interval, expected close)"

key-files:
  created:
    - src/paper/vocabulary.py
    - tests/test_paper_vocabulary.py
  modified:
    - src/paper/supervisor.py
    - src/paper/resync.py
    - tests/test_paper_supervisor_backfill.py
    - tests/test_paper_resync.py
    - tests/test_paper_reviewfix_pins.py
    - tests/test_domain_no_float.py
    - tests/fixtures/phase7/reconnect_resync/input.json
    - tests/fixtures/phase7/reconnect_resync/expected.json
    - tests/fixtures/phase7/unrecoverable_gap/input.json
    - tests/fixtures/phase7/unrecoverable_gap/expected.json

key-decisions:
  - "One rotation owner (research P3, planner decision as recommended by research, no threshold or semantics changed): the SDK owns the 23 h rotation; the scheduled rotation path, on_disconnect, _reconnect_with_retry and _resubscribe_and_backfill are gone"
  - "Gap reason is the reason of the window being verified: WS_RECONNECT_WINDOW after open/reconnect or a successful rebuild, WS_DISCONNECTED when the rebuild is exhausted; a hole the exchange reported (EXCHANGE_NO_CANDLE) is re-labelled by the supervisor with that window reason, an UNKNOWN hole is kept"
  - "WS_RECONNECT is recorded for a reconnect event, for a successful rebuild, and for an open event only when a drop preceded it (the initial open is not a reconnect)"
  - "Expected slots are anchored on the epoch grid (first open at or after last_close + 1 ms), which equals the plan's last_open + interval for real closes and cannot produce phantom gaps for a misaligned cursor"
  - "SUPERVISOR_* and RESYNC_* constants unchanged (implementation values, O-07)"

patterns-established:
  - "Pattern: supervisor tests drive the real PaperWsAdapter over tests/paper_ws_fakes.py and fire SDK connection callbacks on the fake client, then await supervisor.wait_idle()"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "PaperSupervisor.start() is async, awaits connect and subscribe for every (symbol, interval), requires explicit symbols and intervals, and only closed klines reach on_closed_bar as LIVE_WS TaggedBar values with Decimal prices; duplicates are dropped with the existing warning"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_start_connects_once_and_subscribes_every_symbol_interval_pair"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_closed_kline_reaches_the_sink_once_as_a_live_ws_tagged_bar"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_forming_kline_never_reaches_the_sink_nor_moves_the_cursor"
        status: pass
    human_judgment: false
  - id: D2
    description: "Backfilled bars reach on_backfill tagged REST_BACKFILL with the request interval, and gaps reach on_gap with a reason code and no duplicates; nothing is only logged"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_reconnect_event_backfills_from_the_last_close_into_the_sinks"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_a_gap_seen_by_two_verifications_is_reported_once"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_rebuild_exhaustion_still_backfills_and_reports_ws_disconnected_gaps"
        status: pass
    human_judgment: false
  - id: D3
    description: "Real-shaped Binance bars (close = open + interval - 1 ms) produce zero phantom gaps in backfill_missed_closes; a genuine hole is one GapRecord"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_resync.py#test_real_shaped_rows_produce_the_closes_and_zero_gaps"
        status: pass
      - kind: unit
        ref: "tests/test_paper_resync.py#test_a_missing_bar_between_two_returned_bars_is_one_exchange_no_candle_gap"
        status: pass
    human_judgment: false
  - id: D4
    description: "The SDK owns rotation: the supervisor reacts to open/reconnect/close/error events, adds no parallel rotation timer, rebuilds only for close/error, and ignores events after stop and the echo of its own rebuild"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_no_scheduled_rotation_path_remains"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_sdk_rotation_is_one_verification_backfill_and_no_resubscribe"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_unsolicited_close_rebuilds_then_backfills_and_records_both_events"
        status: pass
    human_judgment: false
  - id: D5
    description: "The supervisor and resync import nothing from src.adapters.binance_usdm or src.data.backfill (grep prints nothing); the vocabulary imports no adapter or data module"
    requirement: PAPER-01
    verification:
      - kind: other
        ref: "grep -n 'binance_usdm\\|src.data.backfill' src/paper/supervisor.py src/paper/resync.py (no match)"
        status: pass
      - kind: unit
        ref: "tests/test_paper_vocabulary.py#test_vocabulary_module_imports_nothing_from_adapters_or_the_data_layer"
        status: pass
    human_judgment: false
  - id: D6
    description: "The event reactions against a real Binance connection (SDK 23 h rotation event name and timing, whether a rotation also emits close, the forced-disconnect rebuild)"
    requirement: PAPER-01
    verification: []
    human_judgment: true
    rationale: "The reactions are tested against the SDK-shaped fake; whether the real SDK emits reconnect, open or close during rotation and recovery is derived from reading binance_common 4.4.0 and is proven only by plans 16-17 and 16-21 (SC9: fake-level green never closes PAPER-01)"

duration: 27min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 08: Supervisor on the real adapter shape Summary

**Async `PaperSupervisor` that delivers only closed LIVE_WS bars, lets the SDK own rotation while reacting to its connection events with a REST verification backfill, and sends every recovered bar, gap (with a reason code) and connection event to explicit sinks; resync now anchors expected slots on the exchange grid so real Binance closes no longer produce phantom gaps.**

## Performance

- **Duration:** about 27 min (upper bound: the start time was not recorded; the previous commit was at 04:41Z and the last task commit at 05:03Z)
- **Tasks:** 3 (Task 1 tracer, Tasks 2 and 3 auto, all TDD)
- **Files:** 12 (2 created, 10 modified)

## Accomplishments

- Tracer: `await supervisor.start()` connects once and subscribes each explicitly named (symbol, interval); a closed SDK `KlineCandlestickStreamsResponse` reaches `on_closed_bar` exactly once as `TaggedBar(source=LIVE_WS, interval="1h", ...)` with Decimal prices; forming updates and duplicates never reach the sink; a failed start unsubscribes the created handles, closes the connection and allows a retry.
- Vocabulary (`src/paper/vocabulary.py`): `SourceTag`, `HealthState`, `GapReason`, `DropReason.FUTURE_CLOSE`, `RuntimeEventType` (with `PAPER_TICK_STATS`), frozen `TaggedBar` and `GapRecord` (both reject naive timestamps), `INTERVAL_MS` (a test pins it equal to the data-layer helper without the module importing it).
- Resync fix (P1): expected slots follow the exchange grid; the two live rows of 2026-10-07 return both closes and zero gaps; a genuinely missing bar is exactly one `GapRecord(EXCHANGE_NO_CANDLE)`; returned bars are `TaggedBar(REST_BACKFILL)` with the interval of the request; the new `expected_close_times` names the closes due after a cursor.
- Event-driven recovery: `reconnect` and `open` run the REST verification and record `WS_RECONNECT`; `close` and `error` record `WS_DISCONNECT`, rebuild under the unchanged bounded retry, record `WS_RECONNECT`, then run the same backfill; on exhaustion the backfill still runs and every unrecovered close is a `WS_DISCONNECTED` gap. No timer, no `on_disconnect`.
- `record_close` before `start()` seeds the cursor, so a restart backfills from the restored close instead of logging `no_last_close`.

## RED Evidence

- **Task 1** (`d2b67d4`): `ModuleNotFoundError: No module named 'src.paper.vocabulary'` at collection of both new test files.
- **Task 2** (`35c5c9e`), Test 1 against the pre-change code (the two live rows, `last_close_utc` 07:59:59.999, `now` 10:00:05, run in a scratch script because the new test module imports the not-yet-existing `expected_close_times`): `PRE-FIX: closes 2 gaps 2 ['exchange_returned_no_candle_for_expected_close']`, that is one phantom gap per returned bar. The re-shaped pagination pin `test_long_outage_pages_past_single_page_cap` also failed on the old code with a phantom gap per bar over the 1502-bar outage. The suite file itself failed at collection with `ImportError: cannot import name 'expected_close_times'`.
- **Task 3** (`021c75f`): 17 of the 29 tests in `tests/test_paper_supervisor_backfill.py` failed against the tracer supervisor (no event handling, no `wait_idle`, no sink feed); the structural and negative guards (`test_no_scheduled_rotation_path_remains`, `test_supervisor_never_closes_or_resubscribes_on_its_own`) hold vacuously before the change and are kept as regression guards.

## Task Commits

1. **Task 1 (tracer): async start, closed bars as LIVE_WS** - `d2b67d4` (test, RED), `8428777` (feat, GREEN)
2. **Task 2: resync 1 ms fix, REST_BACKFILL tags, typed gaps** - `35c5c9e` (test, RED), `fdb3ccd` (fix, GREEN)
3. **Task 3: connection events, backfill and gap sinks, seeding** - `021c75f` (test, RED), `0eb1544` (feat, GREEN)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified

- `src/paper/vocabulary.py` - shared runtime vocabulary (pure, Decimal and UTC datetimes)
- `src/paper/supervisor.py` - async supervisor: lifecycle, closed-bar path, event reactions, backfill with per-pair isolation, guarded sinks
- `src/paper/resync.py` - grid-anchored expected slots, `TaggedBar` and `GapRecord` results, `expected_close_times`
- `tests/test_paper_vocabulary.py` (new), `tests/test_paper_supervisor_backfill.py` (rewritten, 29 tests), `tests/test_paper_resync.py` (rewritten to live-shaped rows, 9 tests)
- `tests/test_paper_reviewfix_pins.py`, `tests/test_domain_no_float.py`, the four `tests/fixtures/phase7` JSON files - see deviations

## Decisions Made

See `key-decisions`. Two points worth restating for the downstream plans: the gap reason names the window being verified (so plan 16-26 journals `PAPER_GAP` with `WS_RECONNECT_WINDOW` or `WS_DISCONNECTED`, and plan 16-29 adds `PROCESS_DOWN`, `PLANNED_RESTART` and `CRASH` for downtime); and live bars are held, not dropped, while a recovery is pending.

Interface for later plans: `PaperSupervisor(ws_adapter, rest_adapter, symbols, intervals, on_closed_bar, on_backfill, on_gap, on_connection_event, clock=None)`; `await start()`, `await stop()`, `await wait_idle()`, `record_close(symbol, interval, close_time_utc)`; sinks are synchronous and must only enqueue (`on_closed_bar` and `on_backfill` take one `TaggedBar`, `on_gap` one `GapRecord`, `on_connection_event` takes `(RuntimeEventType, datetime)`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] tenacity retried task cancellation**
- **Found during:** Task 3 (a test that cancels a recovery through `stop()` hung)
- **Issue:** `tenacity` records any `BaseException` as a failed attempt, so `asyncio.CancelledError` raised inside the resync fetch loop and inside the supervisor's rebuild loop was treated as a transient fault and retried (up to 7 attempts, each re-blocking), so `stop()` could not cancel a recovery.
- **Fix:** `CancelledError` is excluded from the retry predicate in both loops (`_is_transient` in `src/paper/resync.py`, the `retry_if_exception` lambda in `src/paper/supervisor.py`); the retry bounds are unchanged.
- **Files modified:** src/paper/resync.py, src/paper/supervisor.py, tests/test_paper_supervisor_backfill.py (`test_stop_cancels_a_recovery_that_is_still_running`, `test_stop_cancels_a_rebuild_that_is_still_running`)
- **Committed in:** 0eb1544

**2. [Rule 2 - Missing critical functionality] Live bars could move the cursor past an unrecovered bar**
- **Found during:** Task 3 design (the plan keeps the monotonic cursor and says the live and backfill paths race on it)
- **Issue:** with the SDK owning reconnection, the WS can resume and deliver bar N+1 before the REST backfill of bar N runs; the monotonic guard would then drop the recovered bar N, a silent hole.
- **Fix:** the SDK event callback counts the pending recovery synchronously; closed live bars arriving meanwhile are held and delivered, in close order and through the same monotonic guard, after the backfilled bars; a gap for a slot covered by a held bar is not reported. Covered by `test_a_live_bar_during_recovery_is_delivered_after_the_backfilled_bars`.
- **Files modified:** src/paper/supervisor.py, tests/test_paper_supervisor_backfill.py
- **Committed in:** 0eb1544

**3. [Rule 2 - Missing critical functionality] Gap de-duplication and guarded sinks**
- **Found during:** Task 3
- **Issue:** a trailing hole is seen again by the next verification (the cursor does not pass it), which would journal it twice once gaps are records; and a sink that raises inside an SDK callback would propagate into the SDK dispatch and lose the bar silently.
- **Fix:** `on_gap` receives each (symbol, interval, expected close) once; every sink call is guarded, logs `paper.supervisor.sink_failed`, and a refused bar becomes a `GapReason.UNKNOWN` record.
- **Committed in:** 0eb1544

**4. [Rule 3 - Blocking] Existing tests and fixtures encoded the pre-fix shape**
- **Found during:** Tasks 1 and 2
- **Issue:** the Phase 7 fixtures and `tests/test_paper_reviewfix_pins.py::test_long_outage_pages_past_single_page_cap` used close = open + interval (and imported `Kline` from the order adapter), which the corrected arithmetic reports as gaps; `tests/test_paper_resync.py` still held supervisor tests built on the fictional synchronous fake named in the 16-01 SUMMARY.
- **Fix:** the two golden fixtures were re-shaped to close = open + interval - 1 ms (the expected gap is now a `GapRecord` shape with `EXCHANGE_NO_CANDLE`); the pagination pin builds live-shaped rows; the three fictional-fake supervisor tests in `test_paper_resync.py` were removed (their behaviour, rotation without reconnect, unsolicited drop with rebuild and backfill, and per-symbol isolation, is covered by `test_sdk_rotation_is_one_verification_backfill_and_no_resubscribe`, `test_unsolicited_close_rebuilds_then_backfills_and_records_both_events` and `test_one_failing_pair_reports_its_gaps_while_the_healthy_pair_still_dispatches`). The old recovery methods of the supervisor were removed in the Task 1 commit and rebuilt event-driven in Task 3, so the commit between them has no recovery path (nothing in `src/` constructs the supervisor yet).
- **Committed in:** 8428777, 35c5c9e

**5. [Rule 2 - Missing critical functionality] Registration trap for the float guard**
- **Found during:** Task 1 (research P23)
- **Issue:** `tests/test_domain_no_float.py` scans an explicit module list; the new vocabulary carries Decimal prices and was not covered.
- **Fix:** added `src/paper/vocabulary.py` to the list.
- **Committed in:** 8428777

### Plan-shape choices (not defects)

- A due slot whose only row is not closed yet (an inconsistent row) keeps the CR-09 behaviour as `GapReason.UNKNOWN`; with live-shaped rows a still-forming last bar is simply not due, so Test 4 produces no gap.
- `wait_idle()` is a public method so the composition root and tests can await a scheduled recovery; `stop()` is async and also closes the adapter (the supervisor opened the connection in `start()`).

---

**Total deviations:** 5 auto-fixed (1 Rule 1, 3 Rule 2, 1 Rule 3). **Impact:** all required for correctness against the real SDK shape; no thresholds or retry constants changed, no package installed, `uv.lock` unchanged.

## Issues Encountered

- A structlog keyword collision (`event=` clashes with structlog's positional event argument) surfaced as a swallowed `TypeError` in the first run of the new handler; renamed the field to `sdk_event` before the Task 3 commit.
- One shell heredoc with the test appendix failed on quoting before any file was written; the appendix was written from a scratch file instead.

## Known Stubs

None.

## Known Limitations (for plans 16-21, 16-26, 16-27)

- After a rebuild is exhausted no further reconnect loop runs: the stream stays dead until the SDK emits another event. The runtime health check (feed staleness, research P5) must detect a silent feed and the user-owned retry numbers stay in the O-07 table.
- Whether the real SDK also emits `close` while it rotates connections (which this supervisor would answer with a rebuild) is derived from source reading only; plan 16-21's live run decides. Coverage item D6 records this as needing a human.
- The gap reason `WS_RECONNECT_WINDOW` also labels a hole the exchange reported inside a reconnect window (the more specific `EXCHANGE_NO_CANDLE` is replaced); change it in `_backfill_pairs` if the journal should keep both.

## Threat Flags

None. No new endpoint, auth path or schema; the supervisor still touches only the paper WS adapter and the public REST adapter. T-16-19 mitigated (gaps are `GapRecord` values with reason codes sent to a sink, de-duplicated, phantom-gap fix proven with live-shaped rows); T-16-20 mitigated (one rotation owner, bounded rebuild retry unchanged, exhaustion still backfills and reports `WS_DISCONNECTED`); T-16-SC accepted, no install.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 16-22/16-24/16-26 can construct the supervisor with `on_closed_bar=queue.put_nowait`, `on_backfill=queue.put_nowait`, `on_gap=record`, `on_connection_event=record` and consume `TaggedBar`/`GapRecord`; plan 16-29 seeds the cursor with `record_close` before `start()`.
- Plan 16-38 can ban `BinanceUsdmAdapter` and `src.execution.manager` in the SHADOW closure: neither `src/paper/supervisor.py` nor `src/paper/resync.py` imports the order adapter or the data-layer backfill module.
- Plans 16-17 and 16-21 must show the event reactions against the real SDK (rotation event name, forced-disconnect rebuild); fake-level green never closes PAPER-01 (SC9).

## Verification

- `tests/test_paper_supervisor_backfill.py tests/test_paper_resync.py tests/test_paper_vocabulary.py tests/test_paper_ws_connect.py tests/test_paper_ws_contract.py`: 80 passed.
- Also green: `tests/test_paper_*.py` (315 passed excluding parity and start-gate), `test_paper_parity`, `test_paper_start_gate`, `test_paper_reviewfix_pins`, `test_domain_no_float`, `test_binance_public`, `test_execution_partials`, `test_reconcile`.
- `ruff check` and `ruff format --check` (450 files) and `mypy src` (157 files) are clean. The whole `pytest -m "not docker"` suite was not run in one process (tool limit); the targeted suites above replace it.
- No file was deleted by any commit; both grep acceptance checks (`binance_usdm` and `src.data.backfill` in supervisor and resync) print nothing.

## Self-Check: PASSED

- FOUND: src/paper/vocabulary.py, src/paper/supervisor.py, src/paper/resync.py, tests/test_paper_vocabulary.py, tests/test_paper_supervisor_backfill.py, tests/test_paper_resync.py
- FOUND commits: d2b67d4, 8428777, 35c5c9e, fdb3ccd, 021c75f, 0eb1544
