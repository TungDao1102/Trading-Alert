---
phase: 19-execution-plan-binding-price-check
plan: 05
subsystem: adapters
tags: [binance, adapter, mark-price, gtd, order-probe]
requires: []
provides:
  - "MarkPriceReading, BinancePublicMarketData.mark_price, BinanceUsdmAdapter.get_mark_price"
  - "place_entry(good_till_date) for time_in_force GTD"
  - "OrderProbe.executed_quantity, OrderProbe.average_price"
affects: [19-10, execution manager, fake exchange]
tech-stack:
  added: []
  patterns: [flag-never-fabricate, additive trailing dataclass fields]
key-files:
  created: [tests/test_live_mark_price_adapter.py, tests/test_binance_entry_gtd.py]
  modified: [src/adapters/binance_public.py, src/adapters/binance_usdm.py]
decisions:
  - "get_mark_price delegates to the public reader, so it passes the shared REST gate without needing a signed-call policy (premiumIndex is unsigned)"
  - "OrderProbe parsing uses getattr(raw, name, None) so query responses/fakes without the new attributes stay valid (None = unknown)"
status: complete
commits: 5
plan_head_before: 28e7f284da9b142f31b97d68a3400475dd8a2944
plan_head_after: c2f1ae6359b61a5a2dec109e92c3a1c15c5815d8
actuals:
  tokens: 14000
  tasks: 3
  commits: 5
---

# Phase 19 Plan 05: Adapter reads for mark price, GTD entry and executed quantity Summary

Three exchange-facing additions at the adapter boundary: a validated live mark price read, `good_till_date` on the GTD LIMIT entry, and `executed_quantity` / `average_price` on `OrderProbe`. No network call in any test.

## What was built

1. **Mark price (tracer, D-06).** `MarkPriceReading(symbol, mark_price: Decimal, exchange_time_utc)` and `BinancePublicMarketData.mark_price(symbol)` call the SDK `rest_api.mark_price` (`GET /fapi/v1/premiumIndex`) through `_gated_rest_call` (CallKind.QUERY, shared REST gate). The `actual_instance` wrapper is unwrapped; an empty response, a list, a wrong or missing symbol, a missing / empty / non-decimal / non-finite / non-positive `markPrice` or a missing `time` raises `ValueError` (message names field and symbol only). The millisecond time is converted with `divmod` and `timedelta` (no float division). `BinanceUsdmAdapter.get_mark_price(*, symbol)` delegates; `MarkPriceReading` is re-exported from the adapter module.
2. **GTD entry (D-05).** `place_entry(..., good_till_date: int | None = None)`. Validation runs before the policy check and any SDK call: non-int or bool raises `TypeError`; GTD without the date and the date with any other time in force raise `ValueError`. The key is forwarded only when set, so the GTC `new_order` kwargs are unchanged (full-dict regression test). `place_entry` stays loop-free and single-attempt (source guard green).
3. **Order probe (research F8, D-10).** `OrderProbe` gains trailing `executed_quantity` and `average_price` (default None). `_query_order_to_probe` parses `executed_qty` / `avg_price` string-mediated; None stays None, junk / non-finite / negative raises. Not-found probes keep both None; existing positional and keyword constructions still work.

Provenance: B6 (GTD, goodTillDate) and B10 (premiumIndex) are WebFetch summaries of 2026-10-19 (MEDIUM confidence), per the research; the research network gaps still apply (no live call was made here, nothing was verified against a live endpoint). The 600-second GTD floor is not checked in the adapter; the pure core (plan 19-03) and Binance validate it.

## Verification (real runs from the worktree)

- `uv run ruff check`: all checks passed; `uv run ruff format --check`: clean; `uv run mypy src`: no issues in 202 source files.
- `tests/test_live_mark_price_adapter.py`, `tests/test_binance_entry_gtd.py`, `tests/test_binance_usdm_source_guard.py`, `tests/test_execution_adapter_contract.py`, `tests/test_execution_manager.py`, `tests/test_execution_exactly_once_pg.py`: pass (PG tests skip without TEST_DATABASE_URL).
- `tests/test_binance_usdm_signed_calls.py`: all pass EXCEPT `test_public_signature_is_unchanged[place_entry]` (see deviation).

## Deviations from Plan

### Required change in a file outside files_modified (not applied)

**1. [Rule 3 - Blocking, left to the orchestrator] `tests/test_binance_usdm_signed_calls.py` SIGNATURE_SNAPSHOTS["place_entry"]**
- **Found during:** Task 2.
- **Issue:** that file pins the exact public signature of `place_entry` ("Public signatures before plan 18-13"). Adding the keyword `good_till_date` (required by this plan) makes `test_public_signature_is_unchanged[place_entry]` fail with "Left contains one more item: ('good_till_date', 'KEYWORD_ONLY')". The plan's verify command includes this test file but its files_modified does not list it.
- **Not changed** because of the instruction to touch only files_modified in parallel waves. **Fix to apply at merge:** append `("good_till_date", _K),` after `("new_client_order_id", _K),` in the `place_entry` snapshot (line ~589). No other behavior of that file is affected.

### Auto-fixed

**2. [Rule 1 - Bug] Probe parsing tolerant of responses without the new attributes**
- **Found during:** Task 3. The existing fake `query_order` payloads in `tests/test_binance_usdm_signed_calls.py` carry no `executed_qty` / `avg_price`; reading `raw.executed_qty` raised AttributeError in six existing tests.
- **Fix:** `getattr(raw, "executed_qty", None)` / `getattr(raw, "avg_price", None)` (absent = unknown = None, consistent with the plan). The real SDK model always has both attributes.
- **Commit:** c2f1ae6

## Notes

- Binance reports `avgPrice` as `0.00000` for an order with no fills; that is a real reported zero and is parsed as `Decimal("0.00000")`. Only an omitted field is None.
- Working-tree line endings in this checkout are CRLF (core.autocrlf=true); edits were made LF-normalized in the index, no whole-file diffs were committed.

## Known Stubs

None.

## Threat Flags

None (no new endpoints beyond the planned premiumIndex read, no auth path or schema change).

## Self-Check: PASSED

Files exist: the two new test files and the SUMMARY; commits ab33780, 2550660, 3008677, 0a461db, c2f1ae6 are ancestors of HEAD on p19-05.
