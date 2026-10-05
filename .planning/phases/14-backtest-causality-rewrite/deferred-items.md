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

## From plan 14-12

- **v2 filled and non-filled `TradeRecord`s carry `modeled_costs_per_unit = None`** (`records.build_trade_record` hard-codes it, `src/backtest/records.py` line 318; only some engine REJECT records set it). The v1 simulator put the sizing figure on every record. Nothing in `src` reads the field today; the simulator and cost-parity suites now read the figure from the `evaluate_risk` verdict the engine received. Decide in 14-15 or 14-16 whether to restore it on filled records (it is not covered by any Phase 14 plan).
- **`experiment._trade_from_dict` leaves the v2 trailing fields (`signal_close_utc`, `planned_quantity`, `tp1_*`, `resolved_at_utc`) as strings** on rebuilt records, so `reproduce` and the baselines return partly untyped records. Digests are unaffected (`to_dict` passes strings through). Plan 14-15 owns the typed rebuild and `validate_trade_record` call (its Task 3 text already lists it); the 14-12 experiment tests read causal order from the engine output instead.
- **The two phase 6 cases that need a strategy bar N+1 (`intrabar_missing_fallback`, `invalidation_cancels_entry`) carry a second record**: the strategy fires a fresh setup at the close of bar 250 once the first plan is closed, and that plan is `PENDING_AT_DATA_END`. Every bar shape tried (eight variants) produced it, so it is kept and asserted rather than avoided.
