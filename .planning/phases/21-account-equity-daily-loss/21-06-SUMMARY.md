---
phase: 21-account-equity-daily-loss
plan: 06
subsystem: risk
tags: [portfolio-caps, reservations, check_portfolio, fail-closed, D-15, D-16, D-17]
requires: []
provides:
  - "src/risk/reservations.py: ReservationStatus, COUNTED_STATUSES, ReleaseReason, RELEASE_SOURCE_STATUSES, ReservationRequest, CountedReservation, ExchangeExposure, open_positions_from_reservations, reservation_verdict"
affects: [21-11, 21-12, 21-14, 21-15]
tech-stack:
  added: []
  patterns: ["pure verdict over the shared check_portfolio", "read-only MappingProxyType release table"]
key-files:
  created:
    - src/risk/reservations.py
    - tests/test_risk_reservations.py
  modified: []
key-decisions:
  - "reservation_verdict short-circuits the latched day itself (DAILY_STOP_BLOCK, DailyState.DAILY_STOP) and otherwise delegates every cap to check_portfolio with positions_reconciled=True, constraint_observed_at_utc=now_utc, ttl=0 (freshness and reconciliation are placement-time gates)."
  - "The candidate's own row is excluded by trade_plan_id from the rows it is judged against, but still explains its own exchange exposure in open_positions_from_reservations."
requirements-addressed: [RISK-02]
status: complete
duration: ~20 min
completed: 2026-10-23
commits: 2
plan_head_before: a6ba7f5feeec9093891d8e16053cbfe9420e7f1c
plan_head_after: 883798c030a4df4c890a73f3c6ddea6dd7910ad6
actuals:
  tokens: 7200
  tasks: 2
  commits: 2
---

# Phase 21 Plan 06: Reservation inputs for the portfolio caps Summary

Pure reservation vocabulary, an open-position view that counts approved-but-unplaced, resting and open plans (fail-closed on an exchange position no PLACED/OPEN row explains), and `reservation_verdict` over the shared `check_portfolio`, plus a release vocabulary covering every terminal plan state.

## Tasks

| Task | Name | Commit |
| ---- | ---- | ------ |
| 1 (tracer) | Reservation request judged through check_portfolio against counted rows | 7de64d6e |
| 2 | Open-position view, exchange-exposure fail-closed, ReleaseReason / RELEASE_SOURCE_STATUSES | 883798c0 |

## What was built

- `ReservationStatus` (5 members), `COUNTED_STATUSES = {RESERVED, PLACED, OPEN}`, `ReleaseReason` (9 members), `RELEASE_SOURCE_STATUSES` (read-only `MappingProxyType`, literal oracle in the test; coverage property: union of sources is every status except RELEASED, RELEASED is never a source).
- `ReservationRequest` / `CountedReservation` / `ExchangeExposure` frozen dataclasses with construction-time validation (Decimal-only, finite, side LONG/SHORT, 64 lower-case hex plan hash, counted statuses only).
- `open_positions_from_reservations`: counted rows minus the excluded plan, sorted by (symbol, position_side, trade_plan_id); any non-zero exchange exposure without a PLACED/OPEN row on the same symbol and side returns `None`.
- `reservation_verdict`: latch gives DAILY_STOP_BLOCK; otherwise `check_portfolio` with the sized realized risk (never the budget); own row excluded so an exact fit passes (cap equality passes, strictly greater rejects).
- Module is stdlib + `src.domain` + `src.risk` only (AST test), no clock call, no float constructor.

## Verification

- `uv run pytest -m "not docker" tests/test_risk_reservations.py tests/test_risk_portfolio.py`: pass (43 reservation tests plus the portfolio file).
- Gate files `tests/test_phase18_gate.py`, `test_phase19_gate.py`, `test_phase20_gate.py`: pass on the re-run (see Shared-tree note).
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_exit_evidence_pg.py`: 31 passed.
- `uv run mypy src/risk/reservations.py`, `ruff check`, `ruff format --check` on own files: clean.
- `git diff --exit-code -- src/risk/portfolio.py params pyproject.toml uv.lock`: clean.
- Evidence label: executed unit tests [DESIGN]. No full-suite run (orchestrator owns it).

## Shared-tree note

The first gate run failed once: `tests/test_phase18_gate.py::test_invariant_5_no_unratified_default_in_src_or_scripts` (`len(GUARDED_NAMES)` 54 vs 52). Cause: sibling plan 21-02's uncommitted `account.max_equity_age_ms` execution-limits key (`config/execution/*`, `src/execution/execution_limits.py`, `tests/support/execution_limits.py`), outside this plan's files. After 21-02 committed (017feeeb) the three gate files re-ran green. No sibling file was edited.

`commits: 2` is counted by `git log --grep='(21-06)'`, not `rev-list ${plan_head_before}..HEAD`: the tree is shared, so that range also contains sibling commits (21-04, 21-03, 21-02).

## Deviations from Plan

None. The plan was executed as written. TDD note: the tracer's test file was written whole first and split by task for the two commits; the red state was not committed separately.

## Known Stubs

None.

## Threat Flags

None. The module adds no endpoint, auth path or file access; T-21-11, T-21-12, T-21-33 are mitigated and tested; T-21-SC: `pyproject.toml` and `uv.lock` unchanged.

## Notes for the owner / downstream plans

- Plan 21-14 records the owner item that `CLUSTER_SYMBOLS` membership (BNB excluded) is unchanged; moving it to the registry needs a new parameter set and `strategy_version` (F-908, F-014).
- Plan 21-12 must copy the nine `ReleaseReason` values and five `ReservationStatus` values into the migration 0011 CHECKs and enforce `RELEASE_SOURCE_STATUSES` in the store.
- The protected-branch guard (`develop`) was not a blocker: commits were made on `develop` as the orchestrator directed.
- `.gitattributes`/CRLF: git warns LF will become CRLF on the two new files; content was committed as written.

## Self-Check: PASSED

- FOUND: src/risk/reservations.py, tests/test_risk_reservations.py
- FOUND commits: 7de64d6e, 883798c0
