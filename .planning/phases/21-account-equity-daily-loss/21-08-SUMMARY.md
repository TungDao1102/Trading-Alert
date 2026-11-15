---
phase: 21-account-equity-daily-loss
plan: 08
subsystem: adapters
tags: [binance, userTrades, income, paging, fixtures, daily-loss]
requires:
  - phase: 21-03
    provides: "_require_exchange_decimal, generator unflatten_summary/WIRE_TYPES, fixtures README, signed registry at fourteen"
provides:
  - "BinanceUsdmAdapter.user_trades_in_window and income_in_window (paged, strict, gated)"
  - "UserTradeRow and IncomeRow frozen dataclasses"
  - "Generated recorded-Demo trade rows, empty income answer and 20 verbatim stream frames"
affects: [21-13, 21-16, daily-loss service]
tech-stack:
  added: []
  patterns: ["from_id paging with strictly increasing id check", "page-number paging with unique tranId check", "byte-copy fixtures by generator"]
key-files:
  created:
    - tests/test_account_trades_adapter.py
    - tests/fixtures/phase21/recorded_demo/user_trades_commission_case.json
    - tests/fixtures/phase21/recorded_demo/user_trades_triggered_bracket.json
    - tests/fixtures/phase21/recorded_demo/income_funding_empty.json
    - tests/fixtures/phase21/recorded_demo/frames/ (20 files)
  modified:
    - src/adapters/binance_usdm.py
    - scripts/gen_phase21_fixtures.py
    - tests/fixtures/phase21/README.md
    - tests/test_phase21_fixtures.py
    - tests/test_binance_usdm_signed_calls.py
key-decisions:
  - "Trade ids must strictly increase within a page and across pages; the SDK docstring does not document the paging order, so this check (which fails closed either way and bounds the loop) was kept as the plan allows."
  - "income paging is bounded by a unique-tranId check (tranId is unique within one income type), so a server that ignored `page` cannot loop forever."
  - "A page that is not a list (including None) raises instead of reading as empty: a truncated read must not hide a loss (T-21-16)."
  - "Row times are built with exact integer millisecond arithmetic (no float); the window end is compared in epoch ms."
requirements-completed: []
duration: ~1h
completed: 2026-10-23
status: complete
commits: 1
plan_head_before: 629ff61a26c85fdf3aec82db139461e9103d5f17
plan_head_after: 8e6453935fab668e1219f4f9ecbfc8d889b530af
actuals:
  tokens: 17000
  tasks: 2
  commits: 1
---

# Phase 21 Plan 08: Paged userTrades and income reads Summary

**Adapter reads the REST trade list and FUNDING_FEE-style income of a UTC window page by page, strictly and through the shared gate, over generated recorded-Demo rows and verbatim stream frames.**

## Accomplishments

- `user_trades_in_window(*, symbol, start_utc, end_utc)`: GET /fapi/v1/userTrades via `_sdk_call(CallKind.QUERY, account_trade_list)`. Page 1 sends `start_time`/`end_time`; later pages send `from_id = last id + 1` only; stops on an empty page or a page holding only trades after `end_utc`; rows after the end are dropped; trade ids must strictly increase (ValueError); row symbol must equal the requested one; amounts are strict Decimals; no `limit`, no retry, no sleep, no clock.
- `income_in_window(*, income_type, start_utc, end_utc)`: GET /fapi/v1/income via `get_income_history`, `page=1,2,...` until an empty page; income type must be a member of the SDK enum (checked before any call); `info` is never read (the dataclass has no field for it); repeated `tranId` raises; rows ordered by `(time_utc, tran_id)`. The funding source stays labelled unverified on Demo.
- Window rule: both bounds timezone-aware UTC, start <= end, span at most seven days (SDK docstring), integer-ms arithmetic.
- Generator: `trade_rows`/`merged_trade_rows` (probe `row_<n>_<field>` text mapped to SDK aliases and JSON types by fixed tables, `symbol` BTCUSDT added as a documented reconstruction), `income_funding_empty.json` (`[]`, after checking both recorded reads had count `0`), and byte copies of the 20 ORDER_TRADE_UPDATE/ACCOUNT_UPDATE frame files of `triggered_close_position_bracket` and `commission_vs_realized_pnl` (including the `-2` variants). README documents every file with RECORDED_DEMO, demo-observed, not mainnet.
- Signed registry: SIGNED/SIGNATURE_SNAPSHOTS/_payloads/count test now sixteen; adapter docstring table and count updated.

## Verification

- `uv run pytest -m "not docker" tests/test_account_trades_adapter.py tests/test_phase21_fixtures.py tests/test_binance_usdm_signed_calls.py tests/test_account_reads_adapter.py tests/test_binance_usdm_source_guard.py`: all passed.
- Gate files `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py`: passed. `TRADING_CI_STRICT=1 tests/test_persistence_exit_evidence_pg.py`: passed.
- `uv run mypy src/adapters/binance_usdm.py`: no issues. Scoped `ruff check` and `ruff format --check` on the five files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock`: unchanged. `git log --grep="^[a-z]*(21-08):" -- src/execution src/risk config params pyproject.toml uv.lock`: prints nothing.
- Evidence label: recorded owner-run Demo payloads (demo-observed, not mainnet) and fakes [DESIGN]; income rows in tests are synthetic (labelled in the test), the income source is unverified on Demo (0 rows).

## Deviations from Plan

- Both tasks were committed together in one commit (`8e645393`) because Task 1 and Task 2 touch the same generator, adapter and test files and were built in one pass; the tracer's end-to-end check (recorded capture -> generator -> fixture -> fake SDK, two pages -> strict rows) is `test_the_recorded_triggered_close_is_read_over_two_pages`. Tests and implementation were written together, so no separate red commit exists.
- [Rule 3] The existing `tests/test_phase21_fixtures.py` assertions pinned exactly three fixture files; they were updated to the six JSON files plus the frames (the plan lists this file as owned).
- Existing three account fixtures were regenerated by the generator run, found byte-different only in line endings (CRLF working tree), and restored with `git checkout -- <file>`; their parsed content equals a fresh run.
- Commission-case fixture keeps the recorded order (ids 549732633, 549732634, 549732632, not ascending, as the plan specifies); tests sort it before serving it as one page and assert the recorded order fails closed.
- `commits:` counts only this plan's commit; in the shared tree the sibling 21-10 summary commit landed between my commit and the ledger read, so `rev-list` over the range may show one extra foreign commit.

## Known Stubs

None.

## Issues / Notes for the caller

- `docs/DOC_STATUS.md` and `docs/GLOSSARY.md` still say "fourteen" signed methods; out of this plan's files, left for plan 21-14 (docs).
- The SDK docstring does not state the page order of userTrades or income; the strictly-increasing trade-id check and the unique-tranId check fail closed regardless.
- No requirement marked complete (per plan; 21-14 records status).

## Threat Flags

None (no new endpoint beyond the two planned signed GETs; info field never read; no response logged).

## Self-Check: PASSED

- Files exist: src/adapters/binance_usdm.py, tests/test_account_trades_adapter.py, the three new JSON fixtures, `recorded_demo/frames/triggered_close_position_bracket-010-ORDER_TRADE_UPDATE.json`.
- Commit `8e645393` is an ancestor of HEAD.
