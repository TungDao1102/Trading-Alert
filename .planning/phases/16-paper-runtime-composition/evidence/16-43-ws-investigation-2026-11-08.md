# 16-43 — investigation of the 2026-10-27 market-stream silence (code reading)

Follows `16-43-ws-silence-2026-10-27.md`. This record is a reading of the code and of the
evaluator output of `16-43-trial-evaluation-2026-11-08.md`; nothing was run against the soak host.
All times UTC. SDK means `binance_common` and `binance_sdk_derivatives_trading_usds_futures` as
installed in the project environment.

## What the code does when a stream goes silent

- `PaperRuntime._watch_feed` (`src/paper/runtime.py`) wakes every `bound / 2` (60 s for
  `feed_silence_timeout_seconds = 120`) and measures silence from the supervisor's
  `last_frame_monotonic`, or from its own start before the first frame. A frame is any kline update,
  forming or closed (`_make_kline_handler` stamps it before the closed-bar filter).
- A silence longer than the bound starts one recovery per episode: `recover_from_silence` runs the
  same path as an SDK `close` (`_recover_from_drop`): `PaperWsAdapter.rebuild()` under tenacity
  (at most 7 attempts or 120 s), then a REST backfill. If the rebuild is exhausted the supervisor
  reports fatal; if the rebuild succeeds but no frame arrives within one more bound, the watchdog
  calls `_fail_feed` and the process exits 7 (B1-CR-01, 16-DEC-WS-WATCHDOG).
- `PaperWsAdapter.rebuild()` (`src/adapters/paper_ws.py`) closes the old client, removes its own
  stream names from the SDK global stream map, builds a new client, `connect()`s (which raises when
  no connection exists) and re-opens every recorded subscription.

So a silence of 2 to 3 minutes, one rebuild and 2 more minutes without a frame give an exit about
4 minutes after the silence began. That matches the seven cycles of about 4 minutes 20 seconds of
the incident.

## Finding 1: seven fresh processes received no frame

Each of the seven restarts of 2026-10-27 00:11 to 00:37 was a new process with a new client, a new
connection and new subscriptions, and each one went silent and then failed closed. Only the eighth
start (00:37:29) received frames. A defect that exists only in a long-running connection, such as a
stale connection object, does not fit: the fresh connections did not deliver either. Both the long
running connection (before 00:04) and fresh connections (00:11 to 00:33) were silent, and the
fresh one at 00:37 was not.

What this does not show: whether Binance sent no kline messages, whether the SUBSCRIBE requests were
accepted, or whether frames were lost on the network path. The adapter checks that connections
exist after `create_connection`, but nothing in the code reads the answer to a SUBSCRIBE request,
and the SDK log bridge forwards WARNING and above only. The kernel log and the EC2 status check of
the earlier record show no host fault.

## Finding 2: the SDK message is a teardown artifact (explained)

`No WebSocket connections available for unsubscription` is logged by the SDK
(`binance_common/websocket.py`, `unsubscribe`) when the client's connection list is empty.
`PaperSupervisor._handles` is filled once in `start()` and is never refreshed (`supervisor.py`
`start`, `_rollback`), while `PaperWsAdapter.rebuild()` creates new handles on a new client. At
teardown (`stop` -> `_rollback`) the supervisor unsubscribes the old handles, which belong to the
closed client, so the SDK warns and returns. The warning therefore appears after a rebuild when the
watchdog ends the process, and it does not show a disagreement between the SDK and the runtime
during the silence, as the first record suspected. It is harmless today (the SDK returns without
raising, the connection is closed afterwards), but the supervisor holds stale handles after a
rebuild.

## Finding 3: any restart can break the 900 s ceiling (consequence for the next trial)

The evaluator counts the runtime as covered again only at the first LIVE_WS closed bar after a
start (`_enqueue` records HEALTHY at that bar; the report shows `WS_RECONNECT_WINDOW` until
13:00:00.25 on the pin day). The runtime subscribes to 1h and 4h klines, so the first closed bar is
the next full hour.

The first block of the trial alone is 12:37:43.83 to 13:00:00.25 UTC (PROCESS_DOWN, then
WS_RECONNECT_WINDOW) = 1336.4 s, above the ceiling of 900 s
(`continuous_uncovered_ceiling_seconds`), before the 2026-10-27 incident. So the trial could not
pass the continuous-uncovered criterion even with no incident, because it was pinned at 12:37.
Any restart more than 15 minutes before a full hour has the same effect. The criterion is a
ratified number (O-07); this record does not change it.

For a new trial, with no change to any threshold: start the pinned runtime in the last 15 minutes
before a full hour (a start at HH:46 or later leaves a block of at most about 14 minutes), and keep
any planned restart in the same part of the hour. A change of the health semantics or of the ceiling
is an owner decision and would need its own record.

## Not established

- Why fresh connections received no frames from 00:11 to 00:37 (Binance side, network path, or an
  unaccepted subscription).
- Whether the 15 other `market stream silent` lines of 2026-10-26 to 2026-10-27 (22 lines, 7 of
  them in the failed-closed cycles) each recovered with one rebuild, and how long each silence was.
- Whether the collector received kline frames in the same window (it logs no message-level event).

## Next steps (not done here)

1. Read-only collection on the soak host: the silence, rebuild and fail-closed lines of the paper
   container log since 2026-10-25, and the WS_DISCONNECT, WS_RECONNECT and HEALTH_STATE_CHANGED rows
   of `journal_events`, to see the length and the frequency of every silence.
2. Observability (a code change, needs an owner decision): count frames per SDK connection, log the
   answer to every SUBSCRIBE request, and log WARNING and above of the SDK with the stream name, so
   that the next silence can be told apart (nothing sent, subscription refused, or one connection
   dead).
3. Refresh `PaperSupervisor._handles` from the adapter after a rebuild (low severity, Finding 2).

No code or configuration was changed for this record.
