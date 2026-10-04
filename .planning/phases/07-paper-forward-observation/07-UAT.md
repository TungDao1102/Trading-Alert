---
status: partial
phase: 07-paper-forward-observation
source: [07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md, 07-04-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing paused — 3 items outstanding]

## Tests

### 1. Closed-candle gate and pre-engine feed gates (07-01)
expected: Paper loop only evaluates closed candles (x=True and close_time <= now), rejects with WARMUP_INSUFFICIENT when < 200 bars and DATA_STALE when gap > 60s, then runs evaluate -> plan -> evaluate_risk.
result: pass
verified: uv run pytest tests/test_paper_closed_candle.py tests/test_paper_feed_gates.py with TEST_DATABASE_URL set -> 10 passed (5+5). Full tests/test_paper_*.py run: 83 passed, 0 failed. Checked by Claude on 2026-10-04.

### 2. WS supervisor rotation, bounded reconnect, REST resync with gap journaling (07-02, library level with fakes)
expected: Supervisor rotates the 24h stream, reconnects with bounded retries, isolates per-symbol failures; resync backfills missed closes and records explicit gaps without fabricating candles.
result: pass
verified: tests/test_paper_supervisor_backfill.py 16 passed, tests/test_paper_resync.py 6 passed, tests/test_paper_ws_connect.py 9 passed, tests/test_paper_reviewfix_pins.py 9 passed. Scope is module level with injected fakes only (see tests 9 and 10 for live behaviour). Checked by Claude on 2026-10-04.

### 3. Paper vs backtest parity digest (07-02)
expected: Paper evaluation on overlapping history is byte-equivalent to backtest simulator.run.
result: pass
verified: tests/test_paper_parity.py 5 passed. Checked by Claude on 2026-10-04.

### 4. Three-way attribution journaling (07-03)
expected: Filled gives system + user-executed-sim rows; skipped/expired give system + opportunity rows with reason codes; naive datetimes and empty identity rejected; ORM round-trip onto existing entities.
result: pass
verified: tests/test_paper_attribution.py 16 passed (AttributionKind has exactly system / user-executed-sim / opportunity; golden digests pinned). Caveat noted in 07-VERIFICATION.md: fill timestamps are caller supplied and approval lag is a fixed 30 s constant (Phase 16 SC3). Checked by Claude on 2026-10-04.

### 5. Pinned-epoch freeze monitor (07-04 D1, automated coverage PAPER-03)
expected: Pin refuses CostModelBindingMismatch; check_registry_unchanged re-hashes and opens a new epoch with REGISTRY_DIFF on diff; clean ticks append CLEAN log lines.
result: pass
source: automated
coverage_id: D1
verified: tests/test_paper_freeze.py 6 passed (pin clean, pin mismatch, absent cost key, check clean, check diff opens new epoch, CLI tick appends jsonl).

### 6. SIMULATE notify edge (07-04 D2, automated coverage PAPER-03)
expected: Message carries all 12 APRV-01 fields with Decimal str precision; journal-first ordering holds under send failure; callbacks stay inert (no poller, no approval mutation, telegram adapter is the only importer).
result: pass
source: automated
coverage_id: D2
verified: tests/test_paper_notify.py 6 passed.

### 7. Operator setup documentation (07-04 D4, automated coverage PAPER-03)
expected: 07-USER-SETUP.md covers the three secrets, PowerShell loader, BotFather and chat-id steps, alembic upgrade head, and smoke commands with the two known gotchas.
result: pass
source: automated
coverage_id: D4
verified: .planning/phases/07-paper-forward-observation/07-USER-SETUP.md present (coverage classifier status pass).

### 8. Pre-soak smoke run, 4 legs incl. WS (07-04 D3, human checkpoint)
expected: REST klines, journal round-trip, SIMULATE Telegram send and live WS subscribe all PASS before the soak starts.
result: blocked
blocked_by: prior-phase
reason: logs/paper/soak_smoke.log (2026-09-27) shows 3 of 4 legs PASS (REST klines 5 rows, journal round-trip byte-equivalent, SIMULATE send message_id=26) but ws_subscribe=BLOCKED with 0 kline events in 30s. Not re-run here (needs live network/Telegram). WS leg owned by Phase 16 (criteria 7-9).

### 9. Real paper run on the live WebSocket
expected: PaperWsAdapter.subscribe against a live connection delivers closed-candle events to the supervisor, and a runnable paper process exists.
result: blocked
blocked_by: prior-phase
reason: Code gap confirmed by inspection. src/adapters/paper_ws.py:160 calls self._ws.kline_candlestick_streams(...) without await (async SDK method), ws_subscribe=BLOCKED in smoke log, and no process composes PaperSupervisor. Owned by Phase 16 (WS adapter await, runnable paper process).

### 10. Zero-tuning forward observation over the 3-6 month soak
expected: One epoch_id for the whole window, all registry_diff.jsonl lines CLEAN, pinned hash unchanged.
result: skipped
reason: Wall-clock property needing a running soak; no stream was ever pinned (logs/paper has only soak_smoke.log). Depends on Phase 16 starting the soak.

## Summary

total: 10
passed: 7
issues: 0
pending: 0
skipped: 1
blocked: 2

## Gaps

<!-- No behavioural issues found in implemented code. Blocked and skipped items are known deferred work owned by Phase 16 and are recorded in 07-VERIFICATION.md. -->
