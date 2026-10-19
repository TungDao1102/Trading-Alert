---
phase: 19-execution-plan-binding-price-check
plan: 10
subsystem: testing
tags: [binance, fake-exchange, test-double, partial-fill, closePosition, race-tests, determinism]
requires: ["19-05", "19-08"]
provides:
  - "BinanceSemanticsFakeAdapter v2 (tests/support/fake_binance_exchange.py): positions, partial fills, closePosition rule, trigger_stop, place_market_close, mark price, lot filters, snapshots, error_facts, scripted completion gates"
  - "tests/test_fake_exchange_v2.py (33 tests)"
affects: [19-11, 19-12, 19-13, 19-14, 19-15]
tech-stack:
  added: []
  patterns: [real-signature bind on every call, decorator-wrapped adapter methods, asyncio.Event hold/release gates, provenance labels DOC/DEMO/ASSUMED]
key-files:
  created: [tests/test_fake_exchange_v2.py]
  modified: [tests/support/fake_binance_exchange.py]
decisions:
  - "The -4509 rule for a closePosition stop while flat is opt-in (enforce_flat_stop_rejection=True): the pre-Phase-19 manager places its closePosition stop right after the entry ack, so a default-on rule fails the legacy PG tests"
  - "The fake's -2022 for a reduce-only MARKET close on a flat position is a labelled TEST CONVENTION; -2024 for a close above the position; callers must treat both the same (requery the position)"
  - "Every adapter method goes through one _exchange_call decorator (real-signature bind, record, gates, completion log) instead of per-method bind and record lines"
status: complete
commits: 6
plan_head_before: da4e841f139a28cb4270225ba9d49dd7dfcff3c6
plan_head_after: 40dd9f6a77876e5346322dbd5fa393ccc6efefd9
actuals:
  tokens: 12000
  tasks: 3
  commits: 6
---

# Phase 19 Plan 10: Stateful fake exchange v2 Summary

The Phase 17/18 stateful Binance-semantics fake now models a signed position book, partial fills, the Demo-observed -4509 for a flat closePosition stop, stop triggering, the reduce-only MARKET close, mark price, lot filters, open-order and algo snapshots, and scripted completion gates, so every Phase 19 stop/cancel race and deadline test can run offline and deterministically. Extended, not replaced: every existing test file that imports the fake still passes (156 tests across the two verification runs, 33 of them new).

## What was built

1. **Tracer (Task 1).** `ExchangeOrderRecord` gained trailing fields with safe defaults (quantity, executed_quantity, average_price, side, position_side, order_type, time_in_force, price, trigger_price, close_position, reduce_only, working_type, algo_type). `fill(client_id, quantity=None, price=None)`: `None` keeps the old full fill; a partial fill keeps the entry open as `PARTIALLY_FILLED` (client id stays taken), the last fill moves it to the history as `FILLED`. Every fill moves the signed per-symbol position (volume-weighted entry price) and appends a `FillEvent` with a unique trade id to `fill_events`. `query_order_by_client` reports `executed_quantity` and `average_price`; `snapshot_positions(symbol=)` serves the real `PositionSnapshot`. A closePosition `STOP_MARKET` while flat raises `BadRequestError` -4509 (the call is still recorded); with a position it is accepted as `NEW`; an explicit-quantity stop while flat is accepted (Demo, probe check line 37). `cancel_normal_order` of a `PARTIALLY_FILLED` entry ends it `CANCELED` with the executed quantity kept; of a `FILLED` entry it is a no-op.
2. **Reads, trigger, close, filters (Task 2).** `set_mark_price` / `get_mark_price` (real `MarkPriceReading`; an unset symbol raises the configured `set_mark_price_error` exception or a `RuntimeError`), `snapshot_open_normal_orders` / `snapshot_open_algo_orders` (real snapshot dataclasses, scoped by symbol), `trigger_stop` (closePosition consumes the position, algo leaves the open book as `FINISHED`; a later fill of the still-open entry opens a new position, the B4 race), `place_market_close` (real `MarketCloseResult`; reduces the position; flat -> -2022, above the position -> -2024, an order that would add exposure -> -2022), `market_close_ack_only` (answers like an acknowledgment), `set_lot_filters` / `symbol_lot_filters` (unset raises `ValueError`), static `error_facts` (same helper as the real adapter).
3. **Completion gates (Task 3).** `hold(method)` / `release(method)` / `held()`, `fail_next(method, exc)`, `reject_next(method, code)`, `reject_next_algo(code)`, and a `completed` log of methods that returned. A held call is recorded in `calls` at once but its state change happens only after `release`. No gate sleeps (a test patches `asyncio.sleep` to prove it). Two ordering tests (stop first, cancel first) run 20 fresh-fake rounds each inside one test.

All kwargs of every method are bound against the real `BinanceUsdmAdapter` signature (`_bind_real`), now through one `_exchange_call` decorator. The module docstring lists every rule with its provenance label (DOC, DEMO, ASSUMED) and states that a green test against the fake proves agreement with the label, not with mainnet.

## Provenance of the modelled rules

| Rule | Label |
|------|-------|
| closePosition stop while flat -> -4509 | DEMO only (probe check file line 38), not on the error-code page |
| explicit-quantity reduce-only stop accepted while flat | DEMO (line 37) |
| closePosition cannot carry quantity or reduceOnly | DOC (enforced by the real adapter, not the fake) |
| partial fills | ASSUMED (research A5; Demo may never produce one) |
| MARKET close on a flat position -> -2022 | TEST CONVENTION, UNPROVEN (research A4/A8; the 2026-10-19 doc pass found -2022 only as a conflict with open orders, so the real code for this case is not known) |
| MARKET close above the position -> -2024 | ASSUMED ("Position is not sufficient." in the taxonomy) |
| MARKET close fills at once and in full | ASSUMED; the real response is normally an acknowledgment, so production code confirms by a position query |
| trigger_stop consumes the position in full | ASSUMED |

## Verification (real runs from the worktree, branch p19-10)

- `uv run pytest -m "not docker" tests/test_fake_exchange_v2.py tests/test_execution_exactly_once_pg.py tests/test_execution_write_ahead_pg.py -x`: 71 passed (PG tests ran; TEST_DATABASE_URL set).
- Other files that import the fake: `tests/test_approval_replay_pg.py tests/test_callback_redelivery_pg.py tests/test_fake_binance_semantics.py tests/test_intent_recovery.py tests/test_intent_recovery_pg.py tests/test_phase18_gate.py`: 85 passed.
- `uv run ruff check`: all checks passed. `uv run ruff format --check`: 649 files already formatted. `uv run mypy src`: no issues in 209 source files.
- `tests/test_fake_exchange_v2.py` ran three more times in a row: 33 passed each time.
- The full suite was not run (the orchestrator runs it after the merge).

## Deviations from Plan

**1. [Rule 1 - Bug avoided] The -4509 rule is opt-in, not always on**
- **Found during:** Task 1 (read of the legacy tests and `src/execution/manager.py` line 850).
- **Issue:** The plan says a flat closePosition stop raises -4509 and that existing fake users keep passing. The current manager places its closePosition stop immediately after the entry ack, when no fill exists, so a default-on rule fails `tests/test_execution_write_ahead_pg.py` and `tests/test_execution_exactly_once_pg.py`, which are outside this plan's files.
- **Fix:** constructor flag `enforce_flat_stop_rejection=False`; Phase 19 flow tests construct `BinanceSemanticsFakeAdapter(enforce_flat_stop_rejection=True)`. A test pins the default.
- **Exact change for later (not made here):** once the manager no longer places the stop before the first fill (plans 19-12 to 19-15), flip the default to `True` and drop the flag from callers.
- **Files modified:** tests/support/fake_binance_exchange.py, tests/test_fake_exchange_v2.py. **Commit:** 4738d58.

**2. [Rule 3 - Blocking] Legacy callers pass `quantity` and `price` as strings**
- **Found during:** Task 1 verification (`TypeError: str - Decimal` in `fill`).
- **Fix:** the fake coerces quantity, price and trigger price with `Decimal(str(value))` when it stores a record (`_dec`); real calls pass Decimal and are unchanged. **Commit:** 4738d58.

**3. [Rule 2 - Additive] Small extras beyond the plan's list**
- `reject_next(method, code)` (general form behind `reject_next_algo`), `completed` log, `market_close_ack_only`, `positions` and `fill_events` as public attributes, `mark_price` on `PositionSnapshot` when a mark is set. **Commits:** 437d67a, 40dd9f6.

**4. [Refactor] One decorator for the bind/record/gate sequence**
- Replaces the repeated `_bind_real` + `_record_call` pair in each method with `_exchange_call(name)` so the gates apply uniformly. `get_position_mode` now also binds (empty kwargs). Behavior of the old methods is unchanged (the legacy suites pass). **Commit:** 40dd9f6.

**Total deviations:** 4 (1 behavior-preserving opt-in, 1 compatibility coercion, 1 additive, 1 refactor). **Impact:** none on production code; no file outside files_modified changed.

## Not modelled (stated so a test does not lean on it)

- Hedge Mode position books (payload binding is checked; positions are one signed Decimal per symbol, side BOTH).
- The trigger price is never compared with the mark price; the test decides when the exchange triggers (`trigger_stop`).
- Other open closePosition algos of a symbol are left as they are when one triggers.
- Fills produced by `trigger_stop` and `place_market_close` do not append to `fill_events` (it lists scripted entry fills only).
- GTD expiry of an entry is not simulated.

## Known Stubs

None.

## Threat Flags

None (test-support code only; no network, no package change).

## Self-Check: PASSED

- tests/support/fake_binance_exchange.py and tests/test_fake_exchange_v2.py exist; both commits chains verified below.
- `def place_market_close` present in the fake; `_bind_real` present; no file outside files_modified plus this SUMMARY changed (`git diff --stat` shows only the two test files before this SUMMARY).
- Task commits on p19-10: 08b7872 (test), 4738d58 (feat), 0a7c201 (test), 437d67a (feat), 0471d26 (test), 40dd9f6 (feat); `git rev-list --count da4e841..HEAD` was 6 before this SUMMARY commit.
