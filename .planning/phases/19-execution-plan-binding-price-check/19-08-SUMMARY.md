---
phase: 19-execution-plan-binding-price-check
plan: 08
subsystem: adapters
tags: [binance, adapter, market-close, reduce-only, error-taxonomy, lot-filters]
requires: ["19-04", "19-05"]
provides:
  - "PreSendRefusal (src/domain/exchange_errors.py)"
  - "MarketCloseResult, BinanceUsdmAdapter.place_market_close"
  - "BinanceUsdmAdapter.error_facts (staticmethod)"
  - "BinanceUsdmAdapter.symbol_lot_filters"
affects: [19-10, 19-12, 19-13, 19-14, 19-15]
tech-stack:
  added: []
  patterns: [single-attempt placement, flag-never-fabricate, pure marker exception]
key-files:
  created: [tests/test_binance_market_close_adapter.py]
  modified:
    - src/domain/exchange_errors.py
    - src/adapters/binance_ratelimit_gate.py
    - src/adapters/binance_usdm.py
    - tests/test_binance_usdm_source_guard.py
    - tests/test_paper_shadow_isolation.py
decisions:
  - "place_market_close is not gated by the clock-drift guard (it blocks new entries only) but still passes the policy check and the shared REST gate"
  - "Hedge side/positionSide consistency (SELL on LONG, BUY on SHORT) is checked before sending; a close that would add exposure raises ValueError"
  - "executed_qty / avg_price are read with getattr (the SDK 17.4.0 NewOrderResponse model declares no avg_price); absent is None, a reported zero stays a Decimal zero"
  - "symbol_lot_filters passes [symbol] to exchange_info so exchangeInfo drift of an unrelated symbol cannot stop an emergency-close filter read"
status: complete
commits: 3
plan_head_before: e48a5b5d503b020b2538ad2ec6fd1898faa91a73
plan_head_after: dfa91f0d3c2b484af8083056568a3367017eafbc
actuals:
  tokens: 14000
  tasks: 3
  commits: 3
---

# Phase 19 Plan 08: MARKET close, pre-send marker, error facts and live lot filters Summary

The adapter can now send one auditable reduce-only MARKET close by a deterministic client id, tell "nothing was sent" from an ambiguous send by type, expose the Phase 18 error facts without the SDK normalizer, and read the lot filters of a symbol live from exchangeInfo. No network call in any test.

## What was built

1. **Tracer: `place_market_close` (D-15, D034).** Keyword-only `(symbol, side, position_side, quantity, new_client_order_id)`, returns `MarketCloseResult(symbol, client_order_id, exchange_order_id, side, position_side, status, executed_quantity, average_price, update_time_utc)`. One `new_order` call through `_sdk_call(CallKind.PLACEMENT)`: type MARKET, quantity as the wire string, no price, no time in force. One-way (BOTH) sends `reduce_only=NewOrderReduceOnlyEnum.TRUE`; Hedge (LONG/SHORT) sends the explicit `positionSide` and no `reduce_only`. Validation before any SDK call: side, position side, Hedge consistency (SELL on LONG / BUY on SHORT, otherwise "would add exposure"), `Decimal` finite > 0 quantity, client id 1..36 characters. Not blocked by the drift guard (test: a never-measured guard refuses `place_entry` with `EntriesBlocked`, `place_market_close` reaches the fake SDK once); a gate pause refuses it with nothing sent; an ambiguous failure is re-raised after exactly one call. A response without symbol, client id, order id or update time raises. `place_market_close` is in the source guard's `PLACEMENT_FUNCTIONS` (the "missing placement function" expectation now lists it) and in the SHADOW `ORDER_SURFACE`.
2. **`PreSendRefusal` (D-21, src/WR-02).** Pure `Exception` subclass in `src/domain/exchange_errors.py` (stdlib-only module, exported in `__all__`). `RestGateRefusal` (and so `RateLimitBanActive` / `RateLimitPauseActive`), `EntriesBlocked` and `SignedCallPolicyMissing` inherit it; attributes and messages are unchanged. `BinanceUsdmAdapter.error_facts(exc)` is a staticmethod delegating to `error_facts_from_exception`; the taxonomy and `classify` are untouched (-2021 on a placement stays REJECTED_DEFINITIVE, a plain `RuntimeError` UNKNOWN_EXCHANGE_ERROR).
3. **`symbol_lot_filters(*, symbol)` (D-16, D-19).** Builds `LotFilters` from live exchangeInfo (LOT_SIZE min/max/step, MARKET_LOT_SIZE min/max/step, tick, min notional). A symbol not listed, a missing LOT_SIZE max or any missing MARKET_LOT_SIZE field raises `ValueError` naming symbol and field; a gate refusal propagates unchanged.

Callers treat `-2022` REDUCE_ONLY_REJECT and `-2024` POSITION_NOT_SUFFICIENT the same way (requery the position); nothing here branches on the difference, and which code a flat-position reduce-only MARKET returns remains unproven (research "Gap pass results").

## Owner-open, recorded not decided

- **Q4 / Phase 18 src/WR-12:** a 418/429 gate pause also refuses the MARKET close, the stop and the cancel. No exemption for risk-reducing calls was added.
- **Q3:** whether a failed exchangeInfo read during an emergency close may fall back to the plan-time snapshot. `symbol_lot_filters` reads live and raises; it never falls back.

## Verification (real runs from the worktree)

- `uv run pytest -m "not docker"` on `tests/test_binance_market_close_adapter.py tests/test_binance_usdm_source_guard.py tests/test_paper_shadow_isolation.py tests/test_exchange_errors.py tests/test_binance_ratelimit_gate.py tests/test_binance_usdm_signed_calls.py tests/test_binance_usdm_error_routing.py tests/test_symbol_filters_extra.py` (plus `tests/test_binance_public.py` and `tests/test_execution_adapter_contract.py`): all pass.
- Also green: 490 tests over the adapter, GTD, mark price, phase18 gate, constraint snapshot, paper runtime, demo probe, execution manager and reconcile files (no PG).
- `uv run ruff check`: all checks passed; `uv run ruff format --check`: 645 files already formatted; `uv run mypy src`: no issues in 207 source files.

## Deviations from Plan

### Auto-fixed / additive

**1. [Rule 3 - Blocking] Stale pins inside files_modified**
- `tests/test_binance_usdm_source_guard.py`: the "missing placement function" expectation of `test_placement_guard_reports_loops_awaits_and_tenacity` now also lists `place_market_close: not defined`.
- `tests/test_paper_shadow_isolation.py`: besides `ORDER_SURFACE`, the negative-control `market_data` set gained `"symbol_lot_filters"` (a read, not an order method). The 19-05 stale-pin fix for `get_mark_price` was already on the base.
- **Commits:** 35f4331, dfa91f0

**2. [Rule 2 - Robustness] Optional `symbols` argument on `BinanceUsdmAdapter.exchange_info`**
- `exchange_info(symbols: Sequence[str] | None = None)` forwards to the existing public parameter; the no-argument call is unchanged. `symbol_lot_filters` passes `[symbol]` so exchangeInfo drift of an unrelated symbol (strictly validated otherwise) cannot fail an emergency-close read. Test: ETHUSDT without LOT_SIZE does not stop a BTCUSDT read.
- **Commit:** dfa91f0

### Merge note

Plans 19-06 and 19-07 run in parallel; if either also edits `ORDER_SURFACE` / the `market_data` set in `tests/test_paper_shadow_isolation.py`, the merge conflict is textual and the resolution is the union of the added names.

## Known Stubs

None.

## Threat Flags

None. T-19-19 (exposure-adding close) is mitigated by reduceOnly in One-way and the Hedge consistency check; T-19-20 by the single-attempt placement (source guard green); T-19-21 by the `PreSendRefusal` marker.

## Self-Check: PASSED

- tests/test_binance_market_close_adapter.py: FOUND
- Commits 35f4331, 1895887, dfa91f0 are ancestors of HEAD.
