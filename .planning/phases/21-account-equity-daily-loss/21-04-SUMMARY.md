---
phase: 21-account-equity-daily-loss
plan: 04
subsystem: risk
tags: [equity, fail-closed, account-state, constraint-snapshot, F-012]
requires:
  - phase: 12
    provides: "live_commission.py structure (fail-closed resolver template)"
  - phase: 17
    provides: "build_plan_constraint_snapshot / snapshot_is_valid_for_live"
provides:
  - "src/risk/live_equity.py: AccountEquityReading, EquityCheck, LiveEquityResult, equity_basis, check_equity_reading, resolve_live_equity"
  - "D-18 snapshot test: live equity plus stubbed Phase 22 inputs is valid for live"
affects: [21-07, 22]
tech-stack:
  added: []
  patterns: ["pure fail-closed resolver, injected clock, reason_code coupled to presence of value"]
key-files:
  created:
    - src/risk/live_equity.py
    - tests/test_live_equity.py
    - tests/test_snapshot_live_equity.py
  modified: []
key-decisions:
  - "Equity basis is totalMarginBalance, isolated in equity_basis() so the owner's O-5 parity choice is a one-line change."
  - "Identities (wallet + unrealized, quote row, balance-endpoint wallet) are exact Decimal equality, no tolerance."
status: complete
requirements-addressed: [RISK-01, EXEC-01]
duration: ~25 min
completed: 2026-10-23
commits: 2
plan_head_before: 56573a3cecf03c4a84d57045657100839ba1591b
plan_head_after: a6f5c2cedee8c464ed7b187e4917d1e966ff502a
actuals:
  tokens: 8000
  tasks: 2
  commits: 2
---

# Phase 21 Plan 04: Live equity resolver Summary

**Pure fail-closed resolver that turns a fresh, consistent, single-asset Binance account reading into `AccountState(equity=totalMarginBalance, risk_rate)`, and refuses everything else with UNCERTAIN_ACCOUNT_STATE; plus the D-18 snapshot test.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | a6ba7f5f | `src/risk/live_equity.py` and `tests/test_live_equity.py` |
| 2 | a6f5c2ce | `tests/test_snapshot_live_equity.py` (D-18 / D-19) |

`commits: 2` counts the commits whose subject starts with `(21-04)`. The shared working tree means `git rev-list plan_head_before..plan_head_after` also contains sibling plans' commits (21-02, 21-03, 21-05, 21-06); the SUMMARY commit follows.

## What was built

- `AccountEquityReading` (frozen): three account amounts, the quote-asset `marginBalance` row (or None), the balance-endpoint wallet (or None), `multi_assets_margin`, UTC `observed_at_utc`. Floats, ints, bools and strings in an amount raise TypeError; NaN/Infinity and naive datetimes raise ValueError.
- `check_equity_reading` order: None, age outside [0, max_age], multi-asset, margin == wallet + unrealized, quote row present and equal, balance row present and equal, equity > 0.
- `resolve_live_equity` wraps it and builds `AccountState`; `LiveEquityResult.equity_for_snapshot` is None on NO_TRADE.
- The module has no wall-clock call, no float, imports only stdlib, `src.core`, `src.domain`; it contains no quote-asset literal (tested).
- D-18 test: a complete snapshot built with the resolved equity plus TEST DATA margin type and leverage passes `snapshot_is_valid_for_live`; NO_TRADE equity, or margin type / leverage None, does not; an AST scan proves no module under `src` passes `margin_type` or `leverage` to `build_plan_constraint_snapshot`.

## Verification

| Command | Result |
|---------|--------|
| `uv run pytest -m "not docker" tests/test_live_equity.py tests/test_snapshot_live_equity.py tests/test_constraint_snapshot.py` | passed (119 tests) |
| `uv run mypy src/risk/live_equity.py` | no issues |
| `uv run ruff check` / `ruff format --check` on the three files | clean |
| `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py` | first run: 1 failure in sibling territory (below); re-run of phase18 gate after 21-02 committed: 25 passed; phase19 and phase20 gates passed in the first run |
| `TRADING_CI_STRICT=1 ... tests/test_persistence_exit_evidence_pg.py` | passed |
| `git diff --exit-code -- pyproject.toml uv.lock` | clean |
| `git log --grep="^[a-z]*(21-04):" -- src/execution scripts pyproject.toml uv.lock` | prints nothing |

Evidence label: executed unit tests [DESIGN]; Demo numbers are recorded payload values (demo-observed, not mainnet).

## Deviations from Plan

**1. [Rule 1 - test expectation] Unknown margin type test.** The plan's behavior implied a snapshot with an unknown margin type is INCOMPLETE. `PlanConstraintSnapshot` rejects the `"UNKNOWN"` sentinel at construction (unknown is `None`). The test now asserts the sentinel raises ValueError, and the None cases cover the INCOMPLETE path. No source change.

**2. Shared-tree gate failure (not mine).** On the first gate run, `tests/test_phase18_gate.py::test_invariant_5_no_unratified_default_in_src_or_scripts` failed (`len(GUARDED_NAMES)` 54 vs 52): sibling plan 21-02's uncommitted `account.max_equity_age_ms` work. After 21-02 committed (017feeeb) the file passed on the single re-run. No sibling file was touched.

Otherwise the plan was executed as written.

## Known Stubs

None in `src`. `STUB_MARGIN_TYPE = "ISOLATED"` and `STUB_LEVERAGE = 5` in `tests/test_snapshot_live_equity.py` are labelled TEST DATA for Phase 22 and never reach `src` (AST scan).

## Threat Flags

None. T-21-07 and T-21-08 are mitigated and tested; T-21-SC: no dependency change.

## Notes for the owner

- O-3 (multi-asset mode): default refuse is implemented. O-5 (equity parity basis): change `equity_basis` only.
- Plan 21-07 maps the 21-03 adapter snapshots into `AccountEquityReading` and chooses `max_age` (from `account.max_equity_age_ms`, still NOT_CONFIGURED).
- Requirements RISK-01 and EXEC-01 are not marked complete (per instructions; plan 21-14 records status).

## Self-Check: PASSED

Files `src/risk/live_equity.py`, `tests/test_live_equity.py`, `tests/test_snapshot_live_equity.py` exist; commits a6ba7f5f and a6f5c2ce found in `git log`.
