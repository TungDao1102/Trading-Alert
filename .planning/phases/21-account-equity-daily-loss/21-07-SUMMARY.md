---
phase: 21-account-equity-daily-loss
plan: 07
subsystem: execution
tags: [equity, account-reads, fail-closed, rest-truth]
requires: [21-02, 21-03, 21-04]
provides: [LiveEquitySource, AccountReadPort, equity_reading_from_snapshots, ScriptedAccountReader]
affects: [21-11, 21-13, phase-24-wiring]
key-files:
  created:
    - src/execution/account_equity.py
    - tests/support/account_fakes.py
    - tests/test_account_equity_source.py
decisions:
  - "An invalidate() that arrives while refresh() is in flight discards that refresh's result (generation counter): the reads may predate the account change."
  - "A refresh drops the previous reading at its start, so a failed refresh never falls back to an older reading."
status: complete
commits: 1
plan_head_before: 05225a8af900dbd4b50e9d938780c467ffb30fa9
plan_head_after: e9bc31c8045905c5108315c777dea15ff8c3596c
actuals:
  tokens: 14000
  tasks: 2
  commits: 1
---

# Phase 21 Plan 07: LiveEquitySource Summary

`LiveEquitySource` turns the adapter's three account reads (accountConfig, account, balance) into a fresh `AccountEquityReading`, stamped with the injected clock before the first request, and resolves it through `src.risk.live_equity` with the age bound from `account.max_equity_age_ms`; any read failure, account event or stream gap leaves NO_TRADE `UNCERTAIN_ACCOUNT_STATE`.

## What was built

- `src/execution/account_equity.py`: `AccountReadPort` (Protocol, `Any` returns, no adapter import), `INVALIDATION_REASONS`, `equity_reading_from_snapshots` (quote-asset rows by name, missing row -> None, duplicate row -> ValueError, wrong type -> TypeError), `LiveEquitySource` with `refresh`, `invalidate`, `check`, `resolve`, `last_error_type`, `last_invalidation_reason`. Construction raises `ExecutionLimitsNotConfigured(("account.max_equity_age_ms",))` while the limit is unset. No wall clock, no SDK, no `src.adapters`, no logging.
- `tests/support/account_fakes.py`: `ScriptedAccountReader` (scripted values or exceptions per call, call order, optional virtual-clock advance per call), `build_demo_adapter` (real `BinanceUsdmAdapter` over a fake SDK serving the Phase 21 recorded-Demo fixtures), `demo_account_snapshots` (async).
- `tests/test_account_equity_source.py`: 26 test cases covering every behavior bullet of both tasks. The tracer resolves the recorded Demo payloads through the real adapter to `Decimal("4999.09343961")` (demo-observed, not mainnet).

## Deviations from Plan

**1. [Rule 1 - Plan test premise] Freshness-contract test**
- **Found during:** Task 1
- **Issue:** The plan says a `now_utc` read before `refresh()` gives a negative age. Because the stamp is taken at the start of `refresh()` (before the first request), a `now` captured immediately before it equals the stamp (age 0, accepted); the age is negative only when the clock moves between the capture and the stamp. The first draft of the test failed for that reason.
- **Fix:** The test moves the virtual clock 1 s between the capture and the refresh: the early `now` is NO_TRADE (negative age), the `now` after `refresh()` is OK with age 3 s. The docstrings now say "can precede the stamp" instead of "gives a negative age". The contract for callers is unchanged: read `now_utc` after `refresh()` returns.
- **Files:** `tests/test_account_equity_source.py`, `src/execution/account_equity.py`

**2. [Rule 2 - Missing safety] In-flight invalidate**
- `invalidate()` during an in-flight `refresh()` discards the refresh result (generation counter), with a test; the plan only specified invalidate between refreshes.

**3. Single commit.** Both tasks share the same three files and the source was written once with both tasks' behavior, so the tests and implementation are in one commit (`e9bc31c8`) instead of one per task.

## Verification

- `uv run pytest -m "not docker" tests/test_account_equity_source.py tests/test_live_equity.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py`: 169 passed.
- `uv run mypy src/execution/account_equity.py`, `uv run ruff check` and `ruff format --check` on the three files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock`: clean (no dependency added). `git log --grep="^[a-z]*(21-07):" -- src/adapters src/risk config params pyproject.toml uv.lock` prints nothing.

## Issues Encountered

- `TRADING_CI_STRICT=1 uv run pytest tests/test_persistence_exit_evidence_pg.py` fails in `test_persistence_module_map_lists_every_module`: `src/persistence/day_risk.py` (untracked, a same-wave sibling's file, plan 21-09 or 21-10) is not yet in the `src.persistence` module map. Outside this plan's files; not touched. Re-run after that sibling commits.

## Known Stubs

None.

## Threat Flags

None. T-21-13 (stale equity), T-21-14 (no retry on a gate refusal) and T-21-15 (type names only, no logging) are covered by tests; T-21-SC verified.

## Self-Check: PASSED

- FOUND: src/execution/account_equity.py, tests/support/account_fakes.py, tests/test_account_equity_source.py
- FOUND: commit e9bc31c8
