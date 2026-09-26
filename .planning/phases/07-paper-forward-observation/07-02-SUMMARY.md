# Phase 7 Plan 2: Paper Reconnect/Resync + Parity Gate Summary

## One-liner
WS supervisor with rotation + bounded reconnect + per-symbol isolation, REST resync with flag-never-fabricate gap journaling, and a byte-exact parity gate proving paper evaluation matches backtest simulator.run on overlapping history.

## What Was Built

### Core modules
- `src/paper/resync.py` — REST kline backfill with flag-never-fabricate gap journaling:
  - `backfill_missed_closes(adapter, *, symbol, interval, last_close_utc, now_utc) -> (closes, gaps)`
  - Paginates via `adapter.klines` until reached `last_close_utc` (drops forming candles with `close_time_utc > now_utc`)
  - Diffs by `open_time_utc` so a forming candle at the expected slot still covers it
  - Returns `(closes, gaps)` — gaps are dicts matching the `CollectorGap` shape (`symbol`, `data_class="paper-<interval>"`, `expected_utc`, `observed_utc`, `reason`)
  - Tenacity bounded: `stop_after_attempt(7) | stop_after_delay(120)`, `wait_random_exponential(multiplier=1, max=60)`, `reraise=True`
  - Module-level named constants: `RESYNC_MAX_ATTEMPTS`, `RESYNC_MAX_DELAY_SECONDS`, `RESYNC_WAIT_MULTIPLIER_SECONDS`, `RESYNC_WAIT_MAX_SECONDS`
- `src/paper/supervisor.py` — WS lifecycle owner with rotation, reconnect, per-symbol isolation:
  - `PaperSupervisor(ws, rest, *, symbols, intervals, on_closed_candle)`
  - `start()` — subscribes all symbol-interval pairs, registers dispatch
  - `on_disconnect(scheduled=True)` — 24h rotation: resubscribe + resync from last-seen close, NO reconnect (WS still connected), NO outage gap
  - `on_disconnect(scheduled=False)` — unsolicited drop: tenacity-bounded reconnect + resubscribe + resync, per-symbol try-except isolation
  - `stop()` — closes all handles cleanly
  - Module-level named constants: `SUPERVISOR_MAX_ATTEMPTS`, `SUPERVISOR_MAX_DELAY_SECONDS`, `SUPERVISOR_WAIT_MULTIPLIER_SECONDS`, `SUPERVISOR_WAIT_MAX_SECONDS`

### Test fixtures (golden pairs)
- `tests/fixtures/phase7/reconnect_resync/{input,expected}.json` — 3-close hole fully returned by REST backfill (no gap records)
- `tests/fixtures/phase7/unrecoverable_gap/{input,expected}.json` — 12:00 bar missing from exchange response → 1 gap record (`reason="exchange_returned_no_bar_for_slot"`)
- `tests/fixtures/phase7/parity_overlapping_history/{input,expected}.json` — 250 1H strategy bars + 250 4H context bars + 1m intrabar map sourced from phase6 `intrabar_both_touched`. Pinned digest `4b0b427ff594e0ff3d854d576893bd36571a5d09538c386b5dff09fb0b2fb6f8`, trade_count 1

### Test suites
- `tests/test_paper_resync.py` — 6 tests (3 resync + 3 supervisor):
  - `test_clean_backfill_returns_all_missed_closes` — 3-close hole fully returned
  - `test_unrecoverable_gap_journals_one_explicit_record` — 12:00 missing → 1 gap
  - `test_forming_candle_dropped_before_diff` — x=False close beyond now_utc dropped
  - `test_rotation_treated_as_scheduled_resubscribes_and_backfills` — 24h rotation path
  - `test_unsolicited_disconnect_reconnects_and_resyncs` — bounded reconnect + backfill
  - `test_one_bad_symbol_does_not_block_healthy_symbols` — per-symbol isolation
- `tests/test_paper_parity.py` — 2 tests + minimal replay helper inside the test module:
  - `test_paper_replay_digest_equals_simulator_digest` — paper replay digest == pinned expected digest == simulator digest (D-02)
  - `test_paper_replay_is_prefix_invariant` — appending a post-horizon bar does not change earlier verdicts (D-02 determinism)

## Key Decisions

### D-01: Flag-never-fabricate in resync
- Forming candles (`x=False` or `close_time_utc > now_utc`) are dropped before the open_time_utc diff — never synthesized
- Unrecoverable windows stay explicit gap records matching the `CollectorGap` shape; they flow into the journal layer unchanged
- REST backfill retry is tenacity-bounded with `reraise=True` — the caller decides what to do when the budget is exhausted (supervisor journals a gap)

### D-01: Rotation is not an outage
- Server-initiated 24h rotation triggers `on_disconnect(scheduled=True)` — NO reconnect attempt (WS is still connected), only resubscribe + resync from last-seen close
- Only unsolicited drops get the bounded reconnect path; this prevents reconnect storms during scheduled Binance maintenance

### D-02: Parity gate is a divergence tripwire
- The replay helper builds the paper loop's `warmed_up_1h` / `warmed_up_4h` / `feed_events` from the fixture's `strategy_bars` bar by bar — both entrypoints see the same snapshot
- Projection reduces both outputs to `(signal_id, reason_code)` tuples — the verdict chain is the common surface (paper loop does not simulate fills yet)
- Any divergence is an engine incident: the fix lives in the shared `evaluate` / `plan` / `evaluate_risk`, never at the paper call site
- Prefix-invariance test guards D-02 determinism: verdict for bar N must depend only on bars [0..N]

### D-05: Purity preserved
- `src/paper/resync.py` imports only stdlib + tenacity + structlog + sibling modules
- `src/paper/supervisor.py` imports only stdlib + tenacity + structlog + sibling modules + the `WsKline` / `RestKline` adapter types (renamed to disambiguate from paper_ws.Kline which has `is_closed`)
- No Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic leaks

### FLAGGED ASSUMPTION (PAPER-01 unclassified)
- Bounded-retry ceilings (`RESYNC_MAX_ATTEMPTS=7`, `RESYNC_MAX_DELAY_SECONDS=120`, `SUPERVISOR_MAX_ATTEMPTS=7`, `SUPERVISOR_MAX_DELAY_SECONDS=120`) are module-level named constants
- Operator tunes them only before a soak epoch starts, never mid-epoch
- Edge probe unresolved — PAPER-01 remains unclassified

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Symbol key lives in constraint_snapshot, not top-level**
- **Found during:** Task 3 GREEN
- **Issue:** `run_paper_tick` reads `case_input["symbol"]` at the top level, but the phase6 fixture stores it in `case_input["constraint_snapshot"]["symbol"]`. Replay helper had to extract and re-inject.
- **Fix:** `_replay_paper_through_bars` reads `symbol` from `constraint_snapshot` and adds it to the per-bar `paper_input` dict
- **Files modified:** `tests/test_paper_parity.py`
- **Commit:** `821f835`

**2. [Rule 3 - Blocking] Duplicate-bar guard rejects post-horizon append**
- **Found during:** Task 3 GREEN (prefix-invariance test)
- **Issue:** `compute_features` raises on duplicate `open_time_utc`. Appending the last bar verbatim triggers the guard.
- **Fix:** Extended replay advances the appended bar's `open_time_utc` / `close_time_utc` by 1H to avoid the duplicate
- **Files modified:** `tests/test_paper_parity.py`
- **Commit:** `821f835`

**3. [Rule 3 - Blocking] Trade lives on the last bar of the fixture**
- **Found during:** Task 3 GREEN (initial prefix-invariance test)
- **Issue:** Dropping the last bar changes the digest (the trade is on bar N, not bar N-1). The first test was comparing truncated digest vs full digest and asserting equality — which fails when the trade is on the last bar.
- **Fix:** Restructured the test to compare the first N bars' verdicts in both the full replay and the extended replay (where bar N+1 is appended). The appended bar's verdict is excluded from the comparison.
- **Files modified:** `tests/test_paper_parity.py`
- **Commit:** `821f835`

## Test Results
- 8 paper tests passing (6 resync + 2 parity)
- Full test suite passes (no regressions)
- `ruff check` clean across `src/paper/`, `tests/test_paper_resync.py`, `tests/test_paper_parity.py`
- `mypy` clean across `src/paper/`, `tests/test_paper_parity.py`
- D-12 Decimal-only guard extended to cover new files

## Commits
- `162fded` — test(07-02): paper resync red-phase fixtures and failing tests
- `2bca442` — feat(07-02): paper resync module with REST backfill and gap journaling
- `e382eb7` — feat(07-02): paper supervisor with rotation, reconnect, per-symbol isolation
- `821f835` — feat(07-02): backtest-paper parity gate on overlapping history
