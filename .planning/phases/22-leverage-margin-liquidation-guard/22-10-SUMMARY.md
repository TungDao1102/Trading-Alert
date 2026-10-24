---
phase: 22-leverage-margin-liquidation-guard
plan: 10
subsystem: risk
tags: [margin, available-balance, account-reading, hedge-mode, fail-closed, F-965, F-966, F-020, criterion-3, criterion-4]
requires:
  - phase: 22
    provides: "free_margin_basis and the pure margin module (plan 22-04)"
  - phase: 21
    provides: "AccountEquityReading, check_equity_reading, LiveEquitySource, the adapter account reads"
provides:
  - "AccountInformationSnapshot.available_balance and .total_open_order_initial_margin, AccountAssetRow.available_balance (required Decimals)"
  - "AccountEquityReading.available_balance, .total_open_order_initial_margin, .quote_asset_available_balance (Decimal or None), .dual_side_position"
  - "src/risk/margin_check.py: check_available_margin, AvailableMarginCheck, BLOCKED_READING_UNUSABLE / BLOCKED_HEDGE_MODE / BLOCKED_MULTI_ASSETS_MODE"
  - "LiveEquitySource.check_margin(now_utc)"
affects: [22-14, 22-16]
tech-stack:
  added: []
  patterns: ["one account answer, one stamp: equity, free margin and the mode flags share the reading and its age bound"]
key-files:
  created: []
  modified:
    - src/adapters/binance_usdm.py
    - src/risk/live_equity.py
    - src/risk/margin_check.py
    - src/execution/account_equity.py
    - tests/test_account_reads_adapter.py
    - tests/test_account_equity_source.py
    - tests/test_live_equity.py
    - tests/test_snapshot_live_equity.py
    - tests/test_margin_check.py
    - tests/test_binance_usdm_signed_calls.py
key-decisions:
  - "The mode flags come from the accountConfig read refresh() already makes (amendment A5): no get_position_mode call, no extra request; refresh() still makes exactly one call per read."
  - "Refusal order is fixed: unusable (none, stale, future), hedge, multi-assets, then the Phase 21 identities and the availableBalance cross-check by value equality. A stale reading's mode is never trusted."
  - "A refused AvailableMarginCheck carries no figures and no observed_at_utc; blocked is one of three plain strings, not RejectionReason members."
status: complete
requirements-addressed: [RISK-02]
duration: ~45 min (interrupted once by a rate limit)
completed: 2026-10-24
commits: 2
plan_head_before: 569cb788
plan_head_after: dfcab301
actuals:
  tokens: 22000
  tasks: 2
  commits: 2
---

# Phase 22 Plan 10: Free-margin figures and mode flags in the one account reading Summary

**The reading that carries the Phase 21 equity now also carries `availableBalance`, the open-order margin total, the quote row's `availableBalance` and `dualSidePosition`, all under one stamp; `check_available_margin` judges it in one pure place and refuses an unusable, hedge or multi-asset account with distinct reasons before anything is mutated.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 457f24c3 | Adapter snapshot and row, `AccountEquityReading` and `equity_reading_from_snapshots` carry the new fields; constructors, fake SDK payload and docstrings updated |
| 2 | dfcab301 | `check_available_margin`, `AvailableMarginCheck`, `BLOCKED_*`, `LiveEquitySource.check_margin` |

`commits: 2` counts this plan's own commits; `plan_head_before` is the parent of the first one. The shared working tree means `git rev-list plan_head_before..plan_head_after` also contains sibling plans' commits (22-12, 22-13).

## What was built

- Adapter: `available_balance` and `total_open_order_initial_margin` (top level) and the asset row's `available_balance`, parsed with `_require_exchange_decimal` (missing, empty, `abc`, `NaN`, `Infinity` raise naming the field, never the offending text). Still one SDK call, no clock, no logging. The docstring that said `availableBalance` is deliberately not read now says it is read since Phase 22 for the margin check and never used as the equity.
- Reading: four new required fields validated in `__post_init__` like their siblings (Decimal and finite; `dual_side_position` a bool). `check_equity_reading`, `equity_basis` and `resolve_live_equity` are untouched; a test shows odd free-margin figures leave the equity unchanged.
- `equity_reading_from_snapshots` maps the fields, `None` for a missing quote row, and refuses a non-bool `dual_side_position` with `TypeError`.
- `check_available_margin(*, reading, now_utc, max_age)`: result `AvailableMarginCheck(available, equity, observed_at_utc, reason_code, blocked)`; the available figure is `free_margin_basis(...)`; the equity is the `check_equity_reading` equity. Recorded Demo reading gives available and equity `Decimal("4999.09343961")`, `OK`. Age equal to `max_age` passes; one microsecond past, a negative age, a missing/mismatching quote `availableBalance` and any failed identity are `READING_UNUSABLE`.
- `LiveEquitySource.check_margin(now_utc)` applies the function to its last reading and configured bound; unusable before any refresh and after `invalidate`.

## Verification

| Command | Result |
|---------|--------|
| `uv run pytest -m "not docker" tests/test_account_reads_adapter.py tests/test_account_equity_source.py tests/test_live_equity.py tests/test_snapshot_live_equity.py tests/test_margin_check.py tests/test_binance_usdm_signed_calls.py tests/test_phase21_gate.py` | passed |
| `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_domain_no_float.py` | passed |
| `uv run mypy` on the four source files | no issues |
| `uv run ruff check` / `ruff format --check` on the eleven plan files | clean |
| `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config` | clean |
| `git log --grep="(22-10):" -- config params src/persistence src/domain src/approval` | prints nothing |

Evidence label: recorded Demo payload through the real adapter and executed unit tests [DESIGN] (demo-observed, not mainnet). What `availableBalance` deducts is not proven by this plan: `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` stays False until the owner's DECISIONS row (the 2026-10-24 Demo run observed the fall by the resting order's initial margin; see 22-DEMO-RESULTS.md).

## Deviations from Plan

None - plan executed as written. Small choices inside the plan's latitude:

- `tests/support/account_fakes.py` needed no edit: it builds its snapshots by running the real adapter over the recorded fixtures, which already carry the new fields.
- A refused `AvailableMarginCheck` has `observed_at_utc` None for all three blocked values (including hedge and multi-assets), mirroring `EquityCheck`.
- The signed-call registry test payload gained the new attributes (`available_balance`, `total_open_order_initial_margin`, and the asset row's `available_balance`), as the plan required.
- The run was interrupted by a rate limit between the two tasks; Task 1 was already committed and Task 2's uncommitted edits were intact, so nothing was redone.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or file access; no logging added (tests assert no balance digits in logs).

## Self-Check: PASSED

- 457f24c3 and dfcab301 are on the branch; `src/risk/margin_check.py` defines `check_available_margin`, `src/execution/account_equity.py` defines `check_margin`; all named tests pass.
