---
phase: 19-execution-plan-binding-price-check
plan: 09
subsystem: execution
tags: [intent-store, write-ahead, sized-realized-risk, live-outcomes, postgres]
requires: ["19-06"]
provides:
  - "IntentRecord.sized_realized_risk (trailing field, default None)"
  - "ExecutionIntentStore.consume_and_record_entry_intent(..., sized_realized_risk=None)"
  - "ExecutionIntentStore.record_protective_intent(..., intended_quantity=None)"
  - "src.analytics.live_outcomes.sized_risks_from_entry_intents"
affects: [19-11, 19-12, 19-13, 19-14, 19-15, 19-16, 19-17]
tech-stack:
  added: []
  patterns: [nullable evidence column written by the single consuming INSERT, optional keyword with None = unknown]
key-files:
  created: [tests/test_realized_risk_persistence_pg.py]
  modified:
    - src/execution/intent_store.py
    - src/persistence/execution_state.py
    - src/execution/manager.py
    - src/analytics/live_outcomes.py
    - tests/support/intent_store_fakes.py
decisions:
  - "Both new parameters default to None, so existing direct callers keep their behavior; the manager passes sized_realized_risk=sized.realized_risk and intended_quantity=None explicitly and a test pins both"
  - "sized_risks_from_entry_intents skips non-ENTRY rows and rows with a NULL figure or NULL quantity (the plan stays INCOMPLETE(NO_RISK_VALUE), never imputed) and raises AnalyticsInputError on two ENTRY rows of one plan with different figures"
  - "Live R stays INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS) (LIVE_NET_PNL_SEMANTICS_VERIFIED is still False); only NO_RISK_VALUE goes away for plans whose sized figure is stored (research F13/A9)"
status: complete
commits: 2
plan_head_before: da4e841f139a28cb4270225ba9d49dd7dfcff3c6
plan_head_after: a870351490cd7c5990714bf05289b4e97a639fbd
actuals:
  tokens: 40000
  tasks: 3
  commits: 2
---

# Phase 19 Plan 09: Sized risk and protective quantity on the intent store Summary

The ENTRY intent now stores the sizing-time realized risk in the same INSERT that consumes the approval (D-22, migration 0005 column), protective intents can be written ahead with an explicit quantity (D-20, used by plan 19-16 for TP1), and analytics reads the stored figure back through `sized_risks_from_entry_intents`. Live R is still INCOMPLETE with `UNVERIFIED_EXCHANGE_SEMANTICS`: only `NO_RISK_VALUE` goes away.

## What changed

- `src/execution/intent_store.py`: `IntentRecord.sized_realized_risk` (trailing field, default `None`); Protocol keyword `sized_realized_risk` on consume and `intended_quantity` on `record_protective_intent`.
- `src/persistence/execution_state.py`: `PgExecutionStateStore` writes the sized figure in the single consuming INSERT (no UPDATE path), `_to_record` maps it back, protective INSERT stores `intended_quantity` (NULL when omitted).
- `tests/support/intent_store_fakes.py`: all five doubles updated together (`InMemoryExecutionIntentStore` keeps both fields, `AlwaysWinsIntentStore`, `CrashAfter` and `FailingIntentStore` forward, `BarrierBeforeConsume` forwards consume and passes protective through `__getattr__`).
- `src/execution/manager.py`: the consume call passes `sized_realized_risk=sized.realized_risk`; `_record_sl_intent` passes `intended_quantity=None` (closePosition leg, D-10).
- `src/analytics/live_outcomes.py`: `sized_risks_from_entry_intents`, docstrings updated (the figure is persisted since Phase 19).
- `tests/test_realized_risk_persistence_pg.py`: PG round trip (get_entry and list_unresolved_intents), replay does not overwrite, NULL when omitted, TP1 quantity stored and SL NULL, positive-quantity CHECK, forwarding test per double, manager call-site test, PG vs in-memory field-by-field parity, DB CHECK rejecting a sized figure on a protective row, fail-closed duplicate figures, end-to-end store -> SizedRisk -> `normalize_live_outcomes`.

## Verification (real runs from the worktree)

- `pytest tests/test_realized_risk_persistence_pg.py tests/test_analytics_live_outcomes.py tests/test_analytics_purity.py`: passed, no skips.
- `pytest` on test_realized_risk_persistence_pg, test_execution_manager, test_intent_recovery, test_execution_write_ahead_pg, test_execution_exactly_once_pg, test_intent_recovery_pg, test_persistence_approvals_pg, test_persistence_migration_pg, test_persistence_transitions_pg, test_persistence_triggers_pg: all passed, no skips (the local PostgreSQL test container was reachable).
- `uv run mypy src`: Success, no issues in 209 source files. `uv run ruff check`: All checks passed. `uv run ruff format --check`: 649 files already formatted.

## Deviations from Plan

1. **[Commit granularity]** Tasks 2 and 3 share `tests/test_realized_risk_persistence_pg.py` and were committed together (a870351) rather than as two commits; Task 1 is its own commit (245485e). Tests were written in the same task commit as the code, not as separate RED commits.
2. **[Not modified]** `tests/test_analytics_live_outcomes.py` is in the plan's `files_modified` but needed no change: the new normalize/read-back tests live in `tests/test_realized_risk_persistence_pg.py` (reusing its `_Rows` fixture). Its module docstring still says the sized figure is "supplied explicitly" (Phase 14 wording), which remains true of `normalize_live_outcomes` itself.
3. Plan 19-06 resolved migration 0005 with the column and CHECK present (not defer-d22), so Tasks 1 and 3 were executed in full.

## Known Stubs

None.

## Threat Flags

None. No new network surface; the only schema contact is the existing migration 0005 column. T-19-22 (single INSERT, DB CHECK, no UPDATE path, analytics reads stored ENTRY rows only) and T-19-23 (five doubles changed together, forwarding tests, PG parity test) are mitigated by the tests above.

## Self-Check: PASSED

Files exist (`tests/test_realized_risk_persistence_pg.py` and the five modified files); commits 245485e and a870351 are ancestors of HEAD on branch p19-09.
