---
quick_task: 261020-l4p
title: Last-price pre-placement check (Phase 19 WR-06 work item, UAT item 10)
status: complete
date: 2026-10-20
base: eb471c0
branch: worktree-agent-ae6d43ac7e23cbe7b
commits:
  - 5171b1c test(19) RED
  - 4ad4102 feat(19) GREEN
  - 49cf760 docs(19)
model: Claude Opus 5.5
---

# 261020-l4p: last-price pre-placement check

ROADMAP Phase 19 criterion 2 says placement is refused when the "mark or last price has crossed
the SL or left the zone". 19-REVIEW WR-06 (review-fix batch 1) built only the mark price. This
task builds the last price.

## What changed

- **Adapter read.** `BinancePublicMarketData.last_price` (`src/adapters/binance_public.py`)
  reads `GET /fapi/v1/ticker/price` through the SDK method `symbol_price_ticker`, always with
  the symbol (weight 1), through the shared REST gate (`CallKind.QUERY`). It returns a new
  frozen `LastPriceReading(symbol, last_price, exchange_time_utc)`. The checks match
  `mark_price`: the answer must be one symbol, not a list; the symbol must match; the price must
  be a non-blank string that parses to a finite positive Decimal; the time must be an int that
  is not a bool. It never retries, never falls back to a default and never uses the mark price
  instead. Error messages name the field and the symbol only.
- **binance_usdm.py.** `BinanceUsdmAdapter.get_last_price(*, symbol)` is a delegate placed
  right after `get_mark_price`. It adds one re-export import line for `LastPriceReading`.
  Nothing near `_sdk_call` was touched.
- **Pure check.** `src/execution/pre_placement.py` gains:
  - `check_last_price` and the codes `LAST_PRICE_UNAVAILABLE`, `LAST_PRICE_CROSSED_STOP` and
    `LAST_PRICE_OUTSIDE_ZONE`.
  - The zone rule from WR-06: only the adverse side refuses (strict, so the exact edge passes).
  - The crossed-stop rule from `is_sl_touched`.
  - Its own age bound and its own check instant.
  - Fail-closed refusals: a missing input, a stale reading, one stamped beyond the skew, and a
    zero, negative or non-finite price all give `LAST_PRICE_UNAVAILABLE`. A naive datetime
    raises.

  `check_mark_price` behaves exactly as before; both checks now share one private rule.
  `PrePlacementInputs` gains `last_price`, `last_time_utc`, `last_checked_at_utc` and
  `max_last_price_age_ms`. `evaluate_pre_placement` runs the last-price check right after the
  mark-price check. The module stays stdlib plus Decimal plus `src.domain`, with no clock.
- **Manager gate 5e.** `ExecutionAdapter.get_last_price` is added. Gate 5e reads the last price
  right after the mark price (the reads are now mark, last, normal orders, algo orders,
  positions). One injected-clock reading taken after all the reads measures both ages (CR-01).
  A reading for another symbol, a non-Decimal price or a non-positive price is unusable. A
  refusal returns NO_TRADE before the position-mode read and before anything is consumed.
- **Owner limit.** A new key, `pre_placement.max_last_price_age_ms`, is added as
  `NOT_CONFIGURED`. It is in the config file, the README, `EXECUTION_LIMIT_KEYS` and
  `ExecutionLimits`. No number was chosen. While it is unset, gate 2b refuses every live and
  Demo placement, as it already does for the other unset keys.
- **Demo rehearsal.** `GuardedAdapter.get_last_price` is a read, so it is allowed in DRY_RUN.
  `derive_plan` is unchanged; its zone contains the mark, and the flow fake reports the last
  price equal to the mark.
- **Fakes.** `BinanceSemanticsFakeAdapter.set_last_price` / `get_last_price` keep their own
  state; an unset price raises and is never derived from the mark. The manager-test
  `FakeExecutionAdapter` and the rehearsal `FakeDemoAdapter` also gain the method.
  `_prime_mark_price` now primes the last price for the PG suites as well.
- **Docs.** GLOSSARY 9.3 has rows for the three codes, and "six" became "seven" execution
  limits. `19-OWNER-GAPS.md` was updated in the WR-06 row, the O-04 key list, the header and
  the status sentence. `19-REVIEW-FIX.md` gained a batch-1 follow-up bullet. ROADMAP.md and
  19-UAT.md were NOT edited. No DECISIONS id was added.

## Test changes worth noting

- New file `tests/test_live_last_price_adapter.py` mirrors the mark-price adapter test: 17
  malformed-payload cases, no payload in error messages, an SDK exception passed through
  without a retry, and the gate pause and ban refusals.
- `tests/test_pre_placement.py`: a grid for both sides (edge, favorable, adverse, crossed),
  plus the age bound kept separate from the mark bound, missing inputs, non-positive and
  non-finite prices, skew, naive datetimes, the evaluation order after the mark check, and
  input validation.
- `tests/test_execution_manager.py`:
  - last-price refusals with the reads only and the approval left unconsumed;
  - favorable-side and edge cases that place;
  - the age measured with its own bound;
  - the clock read once after both reads;
  - gate-order pairs (symbol check before the last price, mark price before the last price);
  - `PRE_PLACEMENT_READS` and the unset-limit parameter list each gained one entry.
- One existing test was adjusted: `test_mark_age_a_fresh_mark_stamped_after_now_utc_places`
  also stamps its last price 3 s after `now_utc`. Its clock sits 3.75 s after the default
  last-price stamp, which the 2468 ms TEST_ONLY last bound would refuse.
- Pins moved:
  - the golden phase-9 `method_sequence` gained `get_last_price` (the same in-place update
    WR-02 made);
  - `ALLOWED_REST_CALLS` in `tests/test_binance_public.py` gained `symbol_price_ticker`;
  - the guarded-name count went from 36 to 37 (`test_no_unratified_defaults.py`,
    `test_phase18_gate.py`);
  - the limits-file `NOT_CONFIGURED` count went from 12 to 14;
  - the shadow-isolation market-data set gained `get_last_price`.
- The Phase 19 gate inventory gained the artifact, the symbols, the adapter method, a Protocol
  test, the RISK-04 test pairs and `NEW_PLAIN_CODES`.

## Verification (this worktree, nothing else)

- RED: before the implementation, the targeted files failed with import errors and with
  TypeErrors from the missing `ExecutionLimits` field.
- GREEN, with `TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` set in the process env, `-n 4`:
  37 targeted and regression files, the PG suites among them (approval replay, callback
  redelivery, exactly-once, write-ahead, intent recovery, consume quantity, realized risk):
  **1521 passed, 0 failed, 0 skipped**. After the final format pass, a re-run of the three
  reformatted files gave 345 passed; the gate files after the doc edits gave 81 passed.
- `uv run ruff check src tests scripts`: passed. `uv run ruff format --check src tests scripts`:
  623 files formatted. `uv run mypy src`: no issues in 214 files. `uv lock --check`: OK.
  `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- The full suite was NOT run (the orchestrator runs it).

## Not verified

- The endpoint was not called. The response shape (`symbol`, `price` as a string, `time` as
  int ms) and the path (`/fapi/v1/ticker/price`, weight 1 with a symbol) come from the
  installed SDK model `SymbolPriceTickerResponse1` and the SDK source on GitHub
  (`market_data_api.py`). The official docs page rendered as a JavaScript shell and its text
  could not be read, so it was not quoted. There is also a V2 endpoint (`/fapi/v2/ticker/price`,
  same shape); v1 was used because the owner named that page. Neither source shows a
  retirement notice for v1. Demo observation stays an owner probe.
- Whether `time` on Demo is the last-trade time or the response time is not observed. The age
  bound applies either way, and its number is the owner's (O-04).
