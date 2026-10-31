---
phase: 24-live-runtime-composition-demo
plan: 19
subsystem: live
status: complete
tags: [stream-persistence, feed-source, stale-feed, divergence-queue, d-10, d-14, g4-043, g4-034]
requirements-addressed: [EXEC-02]
requires: [24-05, 24-07, 24-12]
provides:
  - "src/live/stream_persistence.py: StreamPersistence, make_exchange_state_writer, make_account_position_writer, order_id_for, position_id_for, ExchangeStateLike, IntentSource"
  - "src/live/feeds.py: LiveFeedSource, MarkBook, refresh_marks, StreamDivergenceQueue"
affects: [24-20, 24-27]
key-files:
  created:
    - src/live/stream_persistence.py
    - src/live/feeds.py
    - tests/test_live_stream_persistence_pg.py
    - tests/test_live_feed_source.py
  modified: []
key-decisions:
  - "The order sink reads the event time E from `ExchangeStateLike.exchange_event_time_utc`; the router's ExchangeStateUpdate has no such field (see Hand-off 1)."
  - "A rejected triggered stop is relabelled by the queue from STREAM_ANOMALY/DEPRECATED_EVENT to SINK_FAILURE because the loop only acts on SINK_FAILURE (see Hand-off 3)."
  - "The mark time is the REST premiumIndex `time` (Binance clock), not the local receive time; a failed refresh keeps the old reading so it ages."
  - "User-data liveness = newest of last event, ping, pong and (while LIVE) the LIVE entry time: the same signals stream_is_stale uses. The LIVE entry is added so a freshly started quiet stream is not stale before its first ping."
plan_head_before: f76eacb86a2bd7f78bb7d0f6cd3790868db0fe8e
plan_head_after: c478ee95
commits: 2
actuals:
  tokens: 26000
  tasks: 3
  commits: 2
completed: 2026-10-31
---

# Phase 24 Plan 19: Stream persistence and feed sources Summary

**Router order and account events now persist as Order and Position rows with exchange event-time monotonicity (a late event is a recorded no-op, an exit from UNKNOWN journals USER_DATA_EVENT), and the reconcile loop has a real `FeedSource` (connection liveness plus REST mark times) and `StreamDivergenceSource` (a rejected triggered stop reaches SAFE_MODE).**

## What was built

- `src/live/stream_persistence.py`
  - `StreamPersistence` holds the two sync sinks. A sink builds an immutable job from the event (memory only) and does `loop.create_task(executor.write(job_fn, job))`; tasks start in creation order and the `store-writer` thread is single, so arrival order is kept. Store calls, the intent lookup and the failure journal all run on the writer thread. A tracker (`pending`, `drain()`) is exposed for shutdown and tests.
  - Orders: a client id without a system prefix (`x-`, `xa-`, `xc-`) is not persisted (`stats.foreign`). A missing row is inserted from the intent record (LIMIT, GTD, `local_status` NEW, or UNKNOWN when the intent is UNKNOWN), then `update_order_exchange_state(..., exchange_event_time_utc=E)`; `StateUpdate.stale` is counted. No intent or no intended quantity is journaled (`NO_INTENT`, `NO_QUANTITY`), nothing is invented.
  - G4-034: when the stored `local_status` is UNKNOWN and a not-stale event reports a status the table knows, `transition_order(..., evidence=ExitEvidence(USER_DATA_EVENT, observed_at=E))` runs in the same transaction, so the `UNKNOWN_EXIT_EVIDENCE` event carries the evidence source and the event time. Same for a Position in UNKNOWN (OPEN, or CLOSED for quantity zero).
  - Positions: one transaction per ACCOUNT_UPDATE position row, id = sha256 of (symbol, side). First sight inserts OPEN (a flat never-seen position is skipped; missing break-even or accumulated-realized on first sight is journaled `MISSING_FIELD`, not invented), then `update_position_snapshot` with `E`. An existing row keeps its stored value for a field the event omits. `status` is otherwise untouched.
  - Failures: `STREAM_PERSISTENCE_FAILURE` journal event with the exception class name (or a reason token) and the event time only; a failing journal is logged and swallowed.
- `src/live/feeds.py`
  - `LiveFeedSource.read_feed()` as above; the module docstring records which clock stamps the user-data time (the supervisor's injected clock, the process wall clock, compared by `assess_feeds` with the ratified drift skew).
  - `refresh_marks(reader, marks, symbols)`: one `mark_price` call per distinct symbol, never raises (cancellation excepted), failure class name kept in `MarkBook.last_failure`.
  - `StreamDivergenceQueue`: `sink` (router `divergence_sink`), `drain()` once in arrival order, `halted_reason()` from `note_failure` / `note_state` (bind to the supervisor's `on_failure` / `on_state_change`; the supervisor has no public halt accessor), bounded by `max_items` (bind the stream's `event_queue_max`); overflow calls `on_overflow` once and `halted_reason()` returns `DIVERGENCE_QUEUE_OVERFLOW` for good.
  - `feeds.py` does not import the supervisor module: `tests/test_phase18_gate.py::test_invariant_2` bans it outside the supervisor file. It uses structural `LivenessLike` and the string `LIVE`.

## Verification

- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_live_stream_persistence_pg.py tests/test_persistence_event_time_pg.py tests/test_live_feed_source.py tests/test_reconcile_loop.py tests/test_userdata_events.py tests/test_live_ast_guards.py`: all pass (no skips). Also `tests/test_phase18_gate.py`, `tests/test_no_unratified_defaults.py`, `tests/test_domain_no_float.py`: pass.
- Also pass: `tests/test_persistence_event_time_pg.py` (24-07), the real-router/real-loop tests (a SYNTHETIC `CONDITIONAL_ORDER_TRIGGER_REJECT` frame parsed, routed, queued, and a `ReconcileLoop` tick enters SAFE_MODE `STREAM_SINK_FAILURE`; a halted queue enters `USER_DATA_STREAM_HALTED`; a dead feed enters `STALE_FEED`).
- `uv run mypy src/live` clean; `uv run ruff check src/live <tests>` and `ruff format --check` clean; `git diff --exit-code -- pyproject.toml uv.lock` exits 0 (T-24-SC).
- Not run (by instruction): the full suite.

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] LIVE entry time counts as a user-data liveness signal.** The plan says newest of event, ping, pong. A stream that has just reached LIVE has none of them until the first ping, so the loop would enter SAFE_MODE at start on a quiet account. `stream_is_stale` counts the LIVE entry for the same reason (research P12); `LiveFeedSource` does too. Keepalive success is deliberately not counted (it proves REST, not the socket).

**2. [Rule 2] Relabelling of the rejected triggered stop.** The loop turns only a drained `SINK_FAILURE` item into a divergence; any other kind only triggers a REST query. A `STREAM_ANOMALY` with anomaly kind `DEPRECATED_EVENT` (what the router makes of CONDITIONAL_ORDER_TRIGGER_REJECT) would therefore never reach SAFE_MODE. The queue relabels that one anomaly kind as `SINK_FAILURE` with fixed project text (`ESCALATED_REASON`), other fields kept. Stop-gap, see Hand-off 3.

**3. [Rule 1/scope] The writer is bound to a Protocol, not to the router's real update type.** See Hand-off 1.

**4. Tests written first and run together with the code** (the feed tests passed on the first run, the PostgreSQL tests too); the red run was not recorded separately. The stale cases assert stored state unchanged and depend on the 24-07 store guard, which `tests/test_persistence_event_time_pg.py` pins.

## Hand-off for plan 24-27 (composition) and the orchestrator

1. **Blocker for binding the order sink (needs a file this plan does not own).** `src/adapters/binance_userdata_router.py::ExchangeStateUpdate` has no event time (`local_order_id, exchange_status, exchange_order_id, now_utc` only; `now_utc` is the router clock, not `E`) and the sink is not given the `OrderUpdateEvent`. `StreamPersistence.exchange_state_sink` needs `exchange_event_time_utc`. The smallest fix is additive: `exchange_event_time_utc: datetime | None = None` on `ExchangeStateUpdate`, set to `event.event_time_utc` in `_route_order` (about three lines; tests/test_phase18_gate.py pins only class names). Until then a real `ExchangeStateUpdate` fails mypy against `ExchangeStateLike`, and at runtime would raise `AttributeError` inside the sink, which the router journals as ROUTER_SINK_FAILURE and SINK_FAILURE (SAFE_MODE): fail closed, not silent. I did not widen scope into the router.
2. **`IntentSource.intent_for_client_id(client_order_id) -> IntentRecord | None`** has no production implementation: `ExecutionIntentStore` offers `get_entry(approval_id)` and `list_unresolved_intents()` only. 24-27 must bind one (a PostgreSQL lookup on `execution_intents.client_order_id`, or a map filled when the entry intent is recorded). The order sink assumes `ExchangeStateUpdate.local_order_id` is the client order id, as `ClientIdIndex` defaults it.
3. **The `PgTradingEntityStore` given to `StreamPersistence` must be built with a journal** (`journal=PgJournalStore(db)`), or an UNKNOWN exit fails with `EvidenceRequired` and the whole event rolls back (journaled as a failure).
4. **Wiring:** `router(exchange_state_sink=make_exchange_state_writer(p), account_sink=make_account_position_writer(p), divergence_sink=queue.sink)`; supervisor `on_failure=queue.note_failure`, `on_state_change=queue.note_state`; `ReconcileLoop(feeds=LiveFeedSource(...), stream=queue, feed_clock_skew=clock_skew_from_drift(...))`; schedule `refresh_marks` once per tick with the shared-gate `BinancePublicMarketData`; `await persistence.drain()` before `executor.aclose()` at shutdown.
5. **Phase 18 gate invariant 2** (no src module imports the supervisor) will also fail for plan 24-18's `src/live/stream.py`; that plan must add its file to the gate's allowance.

## Items for 24-DEFERRED

| Item | Why | Owner |
|---|---|---|
| Re-label CONDITIONAL_ORDER_TRIGGER_REJECT from `DEPRECATED_EVENT` to its own router kind and give the loop its own divergence and SAFE_MODE mapping; the queue's SINK_FAILURE relabel is a stop-gap and its SAFE_MODE reason (`STREAM_SINK_FAILURE`) is imprecise | the frame is a rejected triggered stop (research official-doc facts); today it reaches SAFE_MODE only through the relabel | Phase 25 |
| Position lifecycle for the snapshot writer: a position id per (symbol, side) means a CLOSED row (terminal) is reused if the position reopens, and a row stays OPEN after a flat snapshot (`status` is untouched by design) | no code owns OPEN to CLOSING to CLOSED from the stream yet | Phase 25 or a reconcile plan |
| Mark time source: 20-DEFERRED said "stream receive time"; this plan uses the REST `time` (Binance clock) as the plan text asked, so a mark is stale by Binance's own clock too | confirm against Demo that premiumIndex `time` advances roughly each second | Demo soak (Phase 25/26) |
| `positions_flat_skipped`: a flat position never seen is not stored | revisit if reconcile needs flat rows | Phase 25 |

## Known Stubs

None.

## Threat Flags

None. No endpoint, auth path or schema change. T-24-54 (late events): monotonic writes plus the PostgreSQL stale test. T-24-55: liveness from ping/pong/event and mark age per tick, tested both ways, through the real `assess_feeds` and a loop tick. T-24-56: evidence source and event time journaled for Order and Position exits. T-24-57: SYNTHETIC rejected-stop frame through a real router and loop to SAFE_MODE. T-24-SC: `pyproject.toml` and `uv.lock` unchanged.

## Task Commits

1. **Tasks 2 and 3 (feeds and divergence queue):** `f0b0bb4b`
2. **Task 1 (stream persistence tracer) and the supervisor-import fix of feeds.py:** `c478ee95`

## Deviation: worktree base

The worktree branch was reset to `develop` (`f76eacb8`, the D090-era tip) with `git checkout -B worktree-agent-adbc58f25e4884a4b develop` on a clean tree, as the batch rules require. The orchestrator should merge this branch onto `develop`.

## Self-Check: PASSED

- FOUND: src/live/stream_persistence.py, src/live/feeds.py, tests/test_live_stream_persistence_pg.py, tests/test_live_feed_source.py
- FOUND commits f0b0bb4b, c478ee95 (ancestors of HEAD)
