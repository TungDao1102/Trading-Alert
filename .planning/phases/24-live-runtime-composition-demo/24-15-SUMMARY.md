---
phase: 24-live-runtime-composition-demo
plan: 15
subsystem: live
tags: [commission, fee-rate, cost-guard, fail-closed, binance-usdm]
requires:
  - phase: 24-04
    provides: src/live package, AST guards, VirtualTime tests
provides:
  - "CommissionCache: TTL-bound per-symbol account commission readings"
  - "entry_fee_rate: the EntryFeeRateSource port of LiquidationWatch (plan 24-16)"
  - "user_commission_rate symbol validation before the weight-20 call"
affects: [24-16, 24-27]
tech-stack:
  added: []
  patterns: ["cache with injected clock, per-symbol reading, class-name-only journal event"]
key-files:
  created:
    - src/live/commission.py
    - tests/test_live_commission_refresh.py
  modified:
    - src/adapters/binance_usdm.py
    - src/domain/canonical.py
    - tests/test_commission_rates.py
    - tests/test_domain_canonical_decimal.py
key-decisions:
  - "An invalid response (ValueError/TypeError/AttributeError: negative or out-of-range rate, wrong symbol, missing field) drops the previous reading; a transport failure keeps it to its own TTL."
  - "entry_fee_rate returns the account TAKER rate (not max with the parameter fee): the liquidation estimate wants the real fee."
  - "Journal event only on a change of outcome per symbol (first failure, other class, recovery)."
status: complete
requirements: [EXEC-01]
actuals:
  tokens: 14000
  tasks: 3
  commits: 3
plan_head_before: cc6e912c979c531661c70b9981cc58ea457fcf9a
plan_head_after: 54b2c2b7f379cb55747b79efa9109d33aa00d4ad
completed: 2026-10-31
---

# Phase 24 Plan 15: Commission wiring (G3-008, G3-014) Summary

`CommissionCache` refreshes per-symbol maker/taker commission through the adapter, serves
`resolve_live_cost_rates` and the liquidation watch fee-rate port from the same readings, and
fails closed (NO_TRADE UNCERTAIN_ACCOUNT_STATE) on a missing, stale, wrong-symbol or negative rate.

## What was built

- `src/live/commission.py`: `CommissionCache(adapter, clock, symbols, ttl, refresh_margin, record)`.
  - `refresh_due()` reads a symbol when it has no reading or the reading is at least
    `ttl - refresh_margin` old (margin = one reconcile tick, handed in by the composition root;
    TTL = registry `commission_rate_ttl_seconds`). One call per symbol per due refresh, no retry,
    no sleep. Returns the symbols read OK; never raises for a failed read.
  - `account_commission_for(symbol)` returns a reading only for age in [0, ttl].
  - `cost_rates_for(parameter_rates, symbol)` calls `resolve_live_cost_rates` (sizing consumer).
  - `entry_fee_rate(symbol=)` is the `EntryFeeRateSource` port for `LiquidationWatch` (plan 24-16).
  - `last_error_types` and `CommissionRefreshEvent` carry the exception class name only.
- `src/adapters/binance_usdm.py`: `user_commission_rate` raises `ValueError` for an empty, non-str,
  padded or non-upper-case symbol before the SDK call (11 added lines, CRLF kept).
- `src/domain/canonical.py`: the surviving IN-05 `assert` became `RuntimeError`.

## G3-014 dispositions

- **IN-01, negative maker rate:** kept as a fail-closed refusal by owner decision D-22 (adapter
  `_require_commission_rate` and `AccountCommission` unchanged). Pinned by
  `test_user_commission_rate_negative_maker_stays_a_refusal` and, at the cache level, by
  `test_negative_maker_response_gives_no_reading`.
- **IN-01, symbol validation:** fixed (adapter guard, zero SDK calls on a bad symbol, tests).
- **IN-01, ASCII-digit regex before `Decimal(...)`:** stays deferred, as ROADMAP records (not part
  of this plan's scope).
- **IN-05:** the review's `src/backtest/simulator.py:873-875` and `src/backtest/costs.py:79`
  asserts no longer exist at the base (`git grep` finds none under `src/backtest`): Phase 14-12
  moved `run` onto the v2 engine and 17-05 moved `canonical_decimal_text` to
  `src/domain/canonical.py`. The one live remnant, `assert isinstance(exponent, int)` in
  `canonical_decimal_text` (the function IN-05 names), is now an explicit
  `raise RuntimeError("finite Decimal exponent is not an int")`. Behaviour is identical for every
  finite Decimal; `src/backtest/simulator.py` and `costs.py` were not edited. Tests:
  `tests/test_domain_canonical_decimal.py` (violation via a Decimal subclass, plus an AST check
  that the module has no `assert`).

## Official commission page re-read

`https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate`
answered `302 Moved Temporarily` (nginx) on one plain request and one header re-check; not followed
and no bot-check workaround used. So path, weight and fields could NOT be confirmed from the
official page this run. Confidence stays MEDIUM. The installed SDK (`binance_sdk_derivatives_trading_usds_futures`
`account_api.py`) docstring still says `GET /fapi/v1/commissionRate`, `Weight(IP): 20`, parameters
`symbol` (+ `recvWindow`), which matches the adapter and `tests/test_binance_usdm_signed_calls.py`.
Owner can confirm against the page in a browser; nothing here depends on a field beyond
`symbol`, `makerCommissionRate`, `takerCommissionRate`.

## Verification

- `tests/test_live_commission_refresh.py` (new, 31 cases incl. parametrized), `tests/test_commission_rates.py`,
  `tests/test_binance_usdm_signed_calls.py`, `tests/test_binance_usdm_source_guard.py`,
  `tests/test_adapter_strictness.py`, `tests/test_live_ast_guards.py`, `tests/test_cost_parity.py`,
  `tests/test_backtest_purity.py`, `tests/test_domain_no_float.py`, `tests/test_cost_per_unit.py`,
  `tests/test_backtest_experiment.py`, `tests/test_money_at_stake.py`, `tests/test_core_planner.py`,
  `-k "simulator or costs"`: all pass.
- `uv run mypy src` clean (274 files); ruff check and format clean on the plan's files;
  `scripts/verify_decision_alignment.py all` ALL_PASS; `pyproject.toml` and `uv.lock` unchanged.
- No PostgreSQL tests run (none are affected by this plan).

## Deviations from Plan

**1. [Rule 3 - Blocking] IN-05 targets moved**
- Found during: Task 3.
- Issue: the named asserts in simulator.py/costs.py no longer exist; the remaining instance lives
  in `src/domain/canonical.py`, outside the plan's `files_modified`.
- Fix: replaced that one assert (3-line diff); no backtest file touched, no semantics change.
- Commit: 54b2c2b7.

**2. [Design choice within D-22] invalid response drops the previous reading**
- The plan says a failed refresh keeps the previous reading to its own TTL and also that a
  negative or wrong-symbol response "yields no reading". Resolved as: transport/SDK failures keep
  the reading to its TTL; a response the project refuses as untrustworthy (ValueError, TypeError,
  AttributeError) drops it. Tested both ways.

Otherwise the plan was executed as written.

## Known Stubs

None. The cache is not yet constructed by the composition root; `LiveWiring` assembly is plan
24-27 and the `entry_fee_rate` consumer is plan 24-16 (as the plan states).

## Notes for the orchestrator

- No DECISIONS row needed for this plan.
- Wiring (24-27) must schedule `cache.refresh_due` as a `TaskSpec` at the reconcile tick, build the
  cache with `ttl=timedelta(seconds=params["commission_rate_ttl_seconds"])` and
  `refresh_margin=cadences.reconcile_tick`, and pass the cache to `LiquidationWatch(fee_rates=...)`
  and to the sizing path (`cache.cost_rates_for`).
- The two adapter docstring sentences "runtime wiring (refresh loop, TTL) is Phase 24" in
  `binance_usdm.py` were left as they are to keep the diff small.

## Self-Check: PASSED

- src/live/commission.py, tests/test_live_commission_refresh.py: present.
- Commits cd527825, 32855910, 54b2c2b7: ancestors of HEAD.
