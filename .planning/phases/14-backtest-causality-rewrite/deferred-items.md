# Phase 14 deferred items

## From plan 14-11

- **tests/test_analytics_cli.py (31 tests) fail until plan 14-15 Task 3.** The CLI loads backtest
  trades through `src/adapters/analytics_files.py` and `src/backtest/experiment._trade_from_dict`, which
  still build v1-shaped `TradeRecord`s from `tests/fixtures/phase10/loaders/evidence_sample.json`
  (exit_kind `TP1`, entry_kind `TOUCH_NO_FILL`, no `signal_close_utc`). Since 14-11 `normalize_backtest`
  runs `validate_trade_record`, so the CLI reports `trade 'T-1' violates a record invariant`.
  Plan 14-15 owns the evidence loader field fan-out, the `analytics-evidence/2` schema bump and the
  regeneration of `evidence_sample.json`; its Task 3 verify runs `tests/test_analytics_cli.py`.
  Not pulled forward into 14-11 to avoid duplicating that work.
- `tests/test_analytics_files.py` still passes (the loader tests do not call the normalizer).
