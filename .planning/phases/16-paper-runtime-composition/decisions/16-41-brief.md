# 16-41 brief: first-run facts for OQ-1 (O-06) and O-10

Source: `evidence/16-46-run-output.txt` (research run 1, scenario S0, 48 grid points, code a225420). Figures copied verbatim; nothing computed from them.

## OQ-1: trades held through mark-price holes

Printed line, the same text for every one of the 48 grid points (the count is 0 for all 48; `parameter_set_id` differs per line):

> trades held through mark-price holes: 0 (unclassified; methodology is a user decision before any candidate is evaluated with this metric, OQ-1, D063 item 8) parameter_set_id=research-run-1-a01

Lines with a count other than 0: none (48 lines, 48 with 0).

## O-10: modeled_costs_per_unit

Printed line:

> modeled_costs_per_unit is None on v2 filled TradeRecords (D052-open, O-10); no figure uses it

Consumer audit (plan 16-18 SUMMARY, "REV-09 consumer audit", pinned in `tests/test_modeled_costs_none_guard.py`):
- Readers on `TradeRecord` values: `src/backtest/experiment.py` `_DECIMAL_TRADE_FIELDS` (round-trip parse, None stays None); `src/adapters/analytics_files.py` `_TRADE_DECIMAL_FIELDS` (evidence-file validation, None skipped).
- Same name on values that are not trade records: `src/backtest/engine.py` `_Engine._size_and_register` (x2, SizedResult), `src/risk/types.py` `SizedResult.__post_init__`, `src/risk/sizing.py` `size_position`, `src/execution/manager.py` `execute_approved_plan`.
- Not reads: `__all__` exports, the `costs.modeled_costs_per_unit()` function, and the one writer of None on filled records, `src/backtest/records.py` `build_trade_record`.
- The report digest and the research point summary are proven invariant to the field's value (None, "0", "0.0008", "5").

## Options (from 16-CONTEXT O-06 and O-10)

O-06 (how a trade held through mark-price holes is treated in research evidence): annotate only; count against coverage; exclude from pooled R; void such trades; postpone (no candidate is evaluated with this metric until decided).

O-10 (modeled_costs_per_unit on v2 filled TradeRecords): leave None and keep documenting; restore from the cost model when the record is built; restore by a post-run recomputation; postpone.

## Consequences stated in CONTEXT and research

- REV-10 / D063 item 8: the OQ-1 methodology is decided before any candidate is evaluated with the metric, never retroactively from results. D058 (live fails closed on missing mark price) is not the answer.
- Each non-annotate OQ-1 option needs a typed counter, a `run_summary` key, an `ExperimentRecord` field and a deliberate digest regeneration (Phase 14 deferred-items).
- O-10: a restore changes trade payload bytes, `trades_digest`, reproduce equality and so the experiment identity; it needs its own plan before any candidate is registered. REV-09 keeps the field None for now.
