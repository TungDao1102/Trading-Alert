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

## From plan 14-15

- **Resolved: tests/test_analytics_cli.py (31 failures from 14-11).** The evidence loader now builds typed v2 trades and typed `ExperimentRecord`s, the schema is `analytics-evidence/2`, and `evidence_sample.json` was regenerated; all 57 tests of the file pass. The validator and the normalizer boundary were not touched.
- **Resolved: `experiment._trade_from_dict` left the v2 trailing fields as strings (from 14-12).** It now rebuilds `signal_close_utc`, `planned_quantity`, `tp1_*` and `resolved_at_utc` as typed values, checks counters and flags strictly, and calls `validate_trade_record`.
- **Still open: `modeled_costs_per_unit` is `None` on v2 filled records** (14-12 item). Plan 14-15 does not read the field and did not restore it; decide in 14-16 or later.
- **Not covered by any Phase 14 plan: experiments over a `SCRIPTED` run are refused by `assemble` and `reproduce`.** That is deliberate (a scripted fixture is never evidence); a later plan that wants scripted records for tests must build `ExperimentRecord` through the shared factory, not `assemble`.

## From plan 14-16

- **Still open, now recorded in D052: `modeled_costs_per_unit` is `None` on v2 filled records** (14-12 item, restated in 14-15). Plan 14-16 does not read or restore it (nothing in `src` reads it; sizing figures come from the `evaluate_risk` verdict). The Phase 15 research runner decides.
- **Still open, recorded in D052: no runner calls `read_code_version` plus `assemble` outside tests.** Owed to the Phase 15 research runner (and Phase 26 for the holdout-once enforcement).
- **ROADMAP Phase 26 goal still reads "a family has passed under protocol v1.1.0"** (`.planning/ROADMAP.md` line about 956). After D052 no family can pass under v1.1.0 (all earlier evidence is void). Not in 14-16's file list, so not edited here; fix when Phase 26 is planned (reword to the protocol version in force, v2.0.0 or later).
- **`06-VERIFICATION.md` frontmatter `covered_digest` is now stale** because plan 14-16 added the VOID notes to `06-01-SUMMARY.md` and `06-03-SUMMARY.md` (both listed in `covered_files`). Intended: the report is void; a re-verification of Phase 6 would replace the digest.
- **`tests/test_research_gate_negative.py` was missing from the plan's file list** but pinned the literal v1.1.0 in two real-file tests; it is header-driven now (Rule 3, see the SUMMARY).
