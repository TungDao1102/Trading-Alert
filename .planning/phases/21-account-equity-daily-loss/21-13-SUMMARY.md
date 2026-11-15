---
phase: 21-account-equity-daily-loss
plan: 13
subsystem: execution
tags: [daily-loss, day-risk, equity, risk-02]
requires:
  - phase: 21-05
    provides: "fold_daily_loss, evaluate_day_state, day_open_action, blocked_verdict (src/risk/daily_loss.py)"
  - phase: 21-07
    provides: "LiveEquitySource, ScriptedAccountReader"
  - phase: 21-08
    provides: "user_trades_in_window, income_in_window, UserTradeRow, IncomeRow"
  - phase: 21-09
    provides: "PgDayRiskStore semantics"
provides:
  - "src/execution/day_risk_service.py: LiveDayRiskService, DayRiskReadPort, DayRiskStorePort, EquityCheckPort, components_from_user_trade, components_from_income"
  - "tests/support/day_risk_fakes.py: InMemoryDayRiskStore, ScriptedDayRiskReader"
affects: [21-10, 21-11, 21-15, 21-16]
tech-stack:
  added: []
  patterns: ["ports with Any returns (no adapter/persistence import)", "clock re-read after equity.refresh()", "backfill generation counter"]
key-files:
  created:
    - src/execution/day_risk_service.py
    - tests/support/day_risk_fakes.py
    - tests/test_day_risk_service.py
  modified: []
key-decisions:
  - "ensure_day returns DayRiskState | DayStateVerdict (a blocked verdict) instead of a wrapper type"
  - "has_day(yesterday) is read only when today's row is absent (it matters only then)"
  - "A fold error (conflicting duplicate, foreign-day component) is an unknown loss, still honouring a held latch"
status: complete
actuals:
  tokens: 13600
  tasks: 2
  commits: 1
plan_head_before: 923ae6e1935dc41c873f492b47a64c2947ed967f
plan_head_after: b3a2ba9b8eb9a1a72180de09c86fe889110065f8
requirements-completed: []
completed: 2026-10-23
---

# Phase 21 Plan 13: Live daily-loss service core Summary

**`LiveDayRiskService` opens and rolls the UTC day from a fresh Binance equity read judged on the clock re-read after `refresh()`, keeps the day loss from the REST arbiter per backfill generation, persists the DAILY_STOP latch before returning the verdict, and fails closed on every missing, stale or unreadable input.**

## What was built

- `LiveDayRiskService(*, reader, store, equity, clock, symbols, quote_asset, funding_policy, parameter_set)` with `backfill(now_utc)`, `ensure_day(now_utc, exposure)`, `evaluate(now_utc, exposure)`, `last_error_type`, and the private `_backfill_generation` that plan 21-16 bumps.
- `ensure_day`: `day_open_action` decides (stored row, open from fresh base, missing state, unreadable). Opening calls `equity.refresh()`, re-reads the injected clock, checks the reading with that value, requires the base inside the UTC day, then `open_day` and uses the RETURNED row (first stored base wins).
- `backfill`: userTrades of every symbol (sorted) then FUNDING_FEE income since 00:00 UTC, stored through `add_components`; completeness marks are set for (day, generation) only when the generation did not move during the reads; any exception clears the marks and keeps the type name only. No retry.
- `evaluate`: folds the stored components with the required funding policy, runs `evaluate_day_state`, persists a newly derived latch before returning (a failing write is blocked `DAY_STATE_UNREADABLE`), stamps the WARNING alert once (a failing stamp drops the alert, keeps the verdict).
- `components_from_user_trade` (PnL and MINUS commission, key `symbol:order:trade`) and `components_from_income` (FUNDING only, key `symbol|ACCOUNT:tranId`).
- Fakes: `InMemoryDayRiskStore` (PgDayRiskStore semantics, `raise_next`), `ScriptedDayRiskReader`.

## Verification (executed, label [DESIGN]; fakes plus the recorded empty income answer, demo-observed, not mainnet)

- `uv run pytest -m "not docker" tests/test_day_risk_service.py tests/test_daily_loss.py tests/test_account_equity_source.py`: all pass (35 test functions, 41 cases with parametrization in the new file).
- `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py`: pass.
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_exit_evidence_pg.py` with `TEST_DATABASE_URL` set in the process environment: pass (no skip). `tests/test_agents_md.py`, `tests/test_no_unratified_defaults.py`: pass.
- `uv run ruff check` and `ruff format --check` on the three files, `uv run mypy src/execution/day_risk_service.py`: clean.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- pyproject.toml uv.lock` clean (T-21-SC); `git log --grep="^[a-z]*(21-13):" -- src/adapters src/persistence src/db src/risk params pyproject.toml uv.lock` prints nothing.
- Clock proof: a reader moving the virtual clock 3 s during `refresh()` opens the day (`base_observed_at_utc` = clock at refresh start); 4 s per call (12 s, above the 9137 ms TEST_ONLY bound) is blocked `DAY_BASE_UNAVAILABLE` with no day row; a caller `now_utc` older than the stamp does not give a negative age.

## Deviations from Plan

None in behavior. Process note: the TDD red step was not committed separately and the two tasks landed in one commit (`b3a2ba9b`), because the module, fakes and tests were written together; every Task 1 and Task 2 behavior bullet has a test.

## Known limits (no stubs)

- A backfill at exactly 00:00:00.000 UTC has an empty window and may be refused by the adapter's window check; that is a failed read, so the loss stays unknown (fail closed) until the next backfill.
- A gap of more than one UTC day without a stored row blocks `DAY_STATE_MISSING` when exposure exists (the operator acknowledgement path is the owner item, research Open Question 5). Retention of day rows is owner-open O-1; the service never deletes or rewrites a day row.
- The store port is synchronous like `PgDayRiskStore`; Phase 24 decides whether to wrap it in a worker thread. Nothing is wired in a running process.

## Threat Flags

None. No new endpoint, auth path or schema; the service imports no adapter or persistence module.

## Self-Check: PASSED

- FOUND: src/execution/day_risk_service.py, tests/support/day_risk_fakes.py, tests/test_day_risk_service.py
- FOUND commit b3a2ba9b
