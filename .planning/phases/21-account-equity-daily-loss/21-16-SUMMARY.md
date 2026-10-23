---
phase: 21-account-equity-daily-loss
plan: 16
subsystem: execution
tags: [daily-loss, day-risk, user-data-stream, risk-02]
requires:
  - phase: 21-13
    provides: "LiveDayRiskService core with the private _backfill_generation counter"
  - phase: 21-08
    provides: "recorded Demo frames and userTrades fixtures"
provides:
  - "src/execution/day_risk_service.py: components_from_fill, INVALIDATION_REASONS, LiveDayRiskService.ingest_fill / invalidate / current_daily_loss_quote"
  - "tests/support/day_risk_fakes.py: build_day_risk_rig, DayRiskRig, TEST_ONLY_PARAMETER_SET"
affects: [21-15, 21-14, phase-24]
tech-stack:
  added: []
  patterns: ["generation check defeats an in-flight backfill", "loss folded from stored components on each quote call"]
key-files:
  created:
    - tests/test_daily_loss_recorded.py
    - tests/test_day_risk_stream.py
  modified:
    - src/execution/day_risk_service.py
    - tests/support/day_risk_fakes.py
key-decisions:
  - "current_daily_loss_quote folds the stored components on each call (not a cached figure), for a day evaluate has opened and while the backfill is current, so a stream fill added after the last evaluate counts"
  - "A non-quote symbol gets the symbol as the PnL asset so the asset check of fold_daily_loss makes the loss unknown"
  - "ingest_fill and invalidate are synchronous; ingest_fill never raises (type name only in last_error_type)"
status: complete
actuals:
  tokens: 15000
  tasks: 2
  commits: 2
plan_head_before: 1d2e633ffe8b9642e562f772b643eedc16fd594b
plan_head_after: 07294f61
requirements-completed: []
completed: 2026-10-23
---

# Phase 21 Plan 16: Stream path of the live daily loss Summary

Stream fills feed the day loss between REST backfills (most adverse amount per trade key counted once), any ACCOUNT_UPDATE or stream gap makes the loss unknown until a backfill completes after it, and the recorded Demo SL-triggered close is proven to reach the loss through the real parser.

## What was built

- `components_from_fill(fill, quote_asset=)`: FILL_PNL and FILL_COMMISSION (minus commission) components, source USER_DATA_EVENT, key `symbol:orderId:tradeId` (same as the REST row); None when commission, commission asset or realized PnL is missing.
- `LiveDayRiskService.invalidate(reason=)` accepts only `INVALIDATION_REASONS` (`ACCOUNT_UPDATE`, `STREAM_GAP`; anything else is a ValueError), bumps the backfill generation and clears the completeness marks. A backfill already in flight started under the older generation and so never marks the loss known.
- `ingest_fill(fill)`: stores the components; an unusable fill, a store failure or a conflicting redelivery bumps the generation (loss unknown until the next backfill) and never raises.
- `current_daily_loss_quote(utc_day)`: the loss folded from the stored components, only for a day `evaluate` has opened and only while the backfill is current; else None (fail closed). It is the callable plan 21-15 takes as `daily_loss_quote`.
- Tests: `tests/test_daily_loss_recorded.py` (5 tests) and `tests/test_day_risk_stream.py` (one or more per behavior bullet, 17 cases). The `on_call` hook of `ScriptedDayRiskReader` already existed from 21-13; this plan added a shared `build_day_risk_rig` helper to the fakes.

## Evidence (demo-observed, not mainnet, one sample)

- Frame `triggered_close_position_bracket-010` (rp -0.00327999, n 0.02616201 USDT) goes parse_stream_message -> to_fill_event -> ingest_fill -> evaluate: loss 0.02944200, state NORMAL; key `BTCUSDT:28645789207:549733079` equals its REST row's key and the amounts are identical (no divergence).
- Wallet identity: wb of frame 009 minus frame 003 = 4998.71854421 - 4998.74798621 = -0.029442 = rp - n (literal Decimals).
- Evidence label: executed tests with fakes [DESIGN] and recorded Demo frames; not wired in a running process (Phase 24).

## Verification run

- plan tests + `tests/test_day_risk_service.py` + `tests/test_daily_loss.py`: pass
- `tests/test_phase18_gate.py`, `test_phase19_gate.py`, `test_phase20_gate.py`: pass
- `TRADING_CI_STRICT=1 tests/test_persistence_exit_evidence_pg.py` (TEST_DATABASE_URL set in process env): pass
- ruff check / format --check and mypy on the plan's files: clean
- `verify_decision_alignment.py all`: ALL_PASS
- `git diff --exit-code -- pyproject.toml uv.lock`: clean; no commit of this plan touches src/adapters, src/persistence, src/db, src/risk or params (T-21-SC, acceptance check)

## Deviations from Plan

None - plan executed exactly as written. Notes: Task 1 commit already carried the whole src change (the methods share one module and the tracer test needed `current_daily_loss_quote`), so the Task 2 commit is tests only; the `build_day_risk_rig` helper was added to the fakes in the Task 1 commit because the tracer test needed it.

## Known Stubs

None.

## Threat Flags

None (T-21-28 mitigated: invalidation plus generation check, in-flight race tested; T-21-SC: no dependency change).

## Self-Check: PASSED

- FOUND: tests/test_daily_loss_recorded.py, tests/test_day_risk_stream.py, src/execution/day_risk_service.py (`def components_from_fill`)
- FOUND commits: 37f03122, 07294f61
