# 16-DEC-WS-WATCHDOG: in-process feed-silence watchdog (16-56 Q1), user decision

option: Q1-new-key
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
configuration: config/paper/paper-runtime-v2.toml
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

[health]
feed_silence_timeout_seconds: 120

reviewer text (adopted by the user):

### Q1 — In-process silence watchdog

**Decision: B — add a new health threshold in `paper-runtime-v2.toml`.**

Register the new key:

`health.feed_silence_timeout_seconds: 120`

The watchdog must detect when the expected inbound feed has stopped, including a half-open connection for which the SDK supplies no receive timeout. At 120 seconds without a qualifying inbound message, the runtime must fail closed, mark feed health as unhealthy/unknown, and enter the existing bounded recovery path. It must not generate late signals for missed candles.

This threshold is distinct from the ratified 3900-second coverage-silence and healthcheck-bar-age values. The configuration and plan 16-43 must explicitly name and pin `paper-runtime-v2.toml`.

Rejected options and failure scenarios:
- A: rejected because reusing 3900 seconds means silence is detected too late to protect the 900-second coverage ceiling.
- C: rejected because a half-open connection may never reach the existing retries-exhausted path, leaving the process apparently alive while feed input is stale.

Test normal feed activity, a clean disconnect, a half-open connection and recovery. A watchdog timeout must not be treated as permission to process missed candles.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim):

2. 16-55 Q2 / 16-56 Q1: the paper heartbeat must be driven by the 120 s feed-liveness or loop-alive signal, not the 3900 s bar-age probe. A qualifying message is any frame on the connection, not per symbol. The user must provide a second secret heartbeat URL.
5. 16-56 and B1-WR-09 land in one `paper-runtime-v2.toml`; the REST backfill wiring lands before the epoch is pinned.

## Qualifying message (planning fact, not the owner's words)

Re-checked by the executor of plan 16-56 on 2026-10-16 with `codegraph explore "PaperSupervisor.start PaperWsAdapter.subscribe PaperWsAdapter._open_stream"` and a search of `src/adapters/paper_ws.py`, after the Phase 18 merge (commit 6610bd6): the paper connection subscribes only kline streams. `PaperSupervisor.start` calls `PaperWsAdapter.subscribe` once per symbol and interval; `subscribe` calls `_open_stream`, which opens `kline_candlestick_streams` with the stream name `<symbol>@kline_<interval>` for the 1h and 4h intervals. The only SDK calls of the adapter are `create_connection`, `on_connection`, `kline_candlestick_streams` and `close_connection`: no mark-price, book-ticker, trade or user-data stream is on this connection, and the minute mark prices come from REST through `LiveMinutePoller`.

So only kline frames qualify, and any kline frame of any symbol or interval, forming updates included, is the qualifying message of correction 2: it resets one connection-wide silence clock (never per symbol). The stamp sits in the supervisor's kline handler before the `is_closed` filter. A frame that the adapter's `_on_message` drops (unknown envelope, extract or normalize failure) never reaches the supervisor handler and does not reset the clock, which errs toward failing closed.

Values that keep their own meaning (16-DEC-O-07): `max_ws_message_silence_seconds` 3900 (coverage evidence) and `healthcheck_max_bar_age_seconds` 3900 (container probe) are unchanged; this key is a separate in-process bound.
