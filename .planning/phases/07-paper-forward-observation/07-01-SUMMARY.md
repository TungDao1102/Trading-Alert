# Phase 7 Plan 1: Paper Closed-Candle Tracer Slice Summary

## One-liner
Pure paper-loop dispatch through the identical Phase-4 core + Phase-5 risk chain, with closed-candle gate and pre-engine feed fail-closed gates (WARMUP_INSUFFICIENT, DATA_STALE).

## What Was Built

### Core modules
- `src/paper/__init__.py` — barrel re-exporting `run_paper_tick`, `STALENESS_THRESHOLD_SECONDS`, `WARMUP_MIN_BARS`
- `src/paper/loop.py` — pure paper-loop dispatch with:
  - Double closed-candle gate (`x=True AND close_time_utc <= now_utc`)
  - `check_feature_validity` pre-engine gate (rejects when either stream has < 200 bars)
  - `check_feed_freshness` pre-engine gate (rejects when gap > 60s)
  - Identical engine chain: `evaluate` → `plan` → `evaluate_risk`
  - `STALENESS_THRESHOLD_SECONDS = 60`, `WARMUP_MIN_BARS = 200` exported constants
- `src/adapters/paper_ws.py` — `PaperWsAdapter` wrapping the official Binance WS Streams surface, normalizing wire-format kline payloads into frozen `Kline` instances with Decimal prices and UTC datetimes

### Test fixtures (golden pairs)
- `tests/fixtures/phase7/clean_run/` — 250 closed 1H bars + 300 closed 4H bars + 2 feed events (forming x=False + closed x=True), canonical outcome digest `efe70227cdc0f9bdabb2869ab43c235ba60ccce24b42dc6885085f875881ca43`
- `tests/fixtures/phase7/warmup_invalid_no_trade/` — 5 closed 1H bars + 2 closed 4H bars (below EMA200 warmup)
- `tests/fixtures/phase7/feed_stale_no_trade/` — 250 closed 1H + 300 closed 4H bars, `now_utc` 1h past last close

### Test suites
- `tests/test_paper_closed_candle.py` — 4 tests pinning the closed-candle gate (forming updates emit nothing, future-close emits nothing, closed event flows end-to-end, byte-deterministic under frozen clock)
- `tests/test_paper_feed_gates.py` — 5 tests pinning the feed gates (warmup insufficient, feed stale, recovery after stale, threshold constant exported, within-threshold event passes)

## Key Decisions

### D-01/D-02: Paper loop is the realtime mirror of the backtest
- No paper-local setup logic, no simplified sizing, no cost-free path
- Same `evaluate` → `plan` → `evaluate_risk` chain the backtest executes
- Double closed-candle gate is structural, not a log warning

### Feature-validity vs feed-freshness gate semantics
- `check_feature_validity` short-circuits the whole loop when either stream lacks the EMA200 warmup window (one-shot per input, not per-event)
- `check_feed_freshness` is per-event (not latched) so a fresh event after a stale one resumes evaluation without restart
- Both emit `stage="feed_gate"` to distinguish from engine NO_TRADE records

### Adapter-boundary isolation
- SDK WS surface isolated to `src/adapters/paper_ws.py` (RESEARCH §Pattern 1)
- `src/paper/loop.py` imports nothing from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only
- SDK types never leak past the boundary (frozen `Kline` dataclass with project-typed fields)

## Deviations from Plan

None — plan executed exactly as written.

## Test Results
- 9 paper tests passing (4 closed-candle + 5 feed-gates)
- Full test suite passes (no regressions)
- `ruff check` clean across `src/paper`, `src/adapters/paper_ws.py`, `tests/test_paper_*.py`
- `mypy --strict` clean across `src/paper`, `src/adapters/paper_ws.py`
- D-12 Decimal-only guard extended to cover new files

## Commits
- `fffef34` — feat(07-01): paper closed-candle tracer slice
- `604e113` — feat(07-01): paper feed fail-closed gates
- `4e5c63a` — chore(07-01): static gates for paper tracer slice
