---
phase: 23-telegram-approval-hardening-money
plan: 02
subsystem: risk
status: complete
tags: [money-at-stake, risk-pipeline, decimal, canonical-json, fail-closed, f-015]
requirements-addressed: [APRV-01]
requires: []
provides:
  - "src/risk/money_at_stake.py: MoneyAtStake, TakeProfitAtStake, MoneyAtStakeUnavailable, build_money_at_stake, money_canonical_json, parse_money_json, MONEY_AT_STAKE_MISSING, MONEY_SCHEMA_TAG, QUOTE_ASSET_USDT and the four source labels (+ EQUITY_SOURCES / LEVERAGE_SOURCES sets)"
affects: [23-04, 23-09, 23-11, 23-13]
tech-stack:
  added: []
  patterns:
    - "computed once in the risk layer, stored, only formatted by the message layer"
    - "strict canonical JSON with a schema tag, float/constant/duplicate/unknown-key rejection"
key-files:
  created:
    - src/risk/money_at_stake.py
    - tests/test_money_at_stake.py
  modified:
    - tests/test_domain_no_float.py
key-decisions:
  - "Net loss at SL is SizedResult.realized_risk itself; gross loss is quantity x |entry - SL|; margin goes through required_initial_margin; a TP cost goes through per_unit_round_trip_cost with the TP price as the exit price."
  - "Margin is truncated toward zero at 18 fractional digits (ROUND_DOWN, prec 38), never rounded up."
  - "The parser also rejects non-canonical Decimal text (exponent form) and non-canonical time text, and duplicate JSON keys, so the stored text round-trips byte for byte and only one text maps to one value."
  - "A stop on the wrong side of the entry is refused as MONEY_AT_STAKE_MISSING with field stop_loss_price (a case the plan did not list)."
metrics:
  completed: 2026-10-25
commits: 3
plan_head_before: a393406aa5b10ddcc91495502ee624fa42ee352b
plan_head_after: 43b2cf233228f757131462105f6ea7b7e55548df
actuals:
  tokens: 8700
  tasks: 2
  commits: 3
---

# Phase 23 Plan 02: Money at stake built once from the risk pipeline output Summary

One pure builder turns a `SizedResult` plus the plan's stop and take-profits, the cost rates, the verified leverage and the equity reading into a single frozen `MoneyAtStake` (notional, margin, SL loss gross and net, per-leg TP profit gross and net, equity with source label and time), with a strict canonical JSON stored form; any missing input refuses with `MONEY_AT_STAKE_MISSING` and the field name.

## What was built

- **Task 1 (tracer, RED `2e461aa5`, GREEN `760d89cb`).** `src/risk/money_at_stake.py`: constants, the two frozen dataclasses with `__post_init__` validation (finite positive Decimals, int leverage that is not a bool and at least 1, label sets, UTC-aware time, fractions summing to one, stop and take-profits on the right sides of the entry), `MoneyAtStakeUnavailable(ValueError)` with `reason_code` and `field`, `build_money_at_stake`, `money_canonical_json`, `parse_money_json`. The module is listed in `tests/test_domain_no_float.py`. The LONG fixture test recomputes notional 4008.00, margin 801.60, gross loss 48.00, net loss 53.5776 (== `realized_risk`), TP1/TP2 legs 0.040 with gross 36.00 / 76.00 and the nets, with literal Decimal arithmetic.
- **Task 2 (`43b2cf23`).** SHORT fixture (entry 50000, SL 50600, leverage 4: notional 4000.00, margin 1000, gross loss 48.00, TP gross 40.00 / 80.00), one test per refusal field, margin truncation against an exact `Fraction`, TP and stop side checks, parser strictness (float literal at top level, in a leg and as leverage; NaN / Infinity / -Infinity; unknown / missing keys at both levels; schema `money-at-stake/2`; naive time; bool leverage; exponent-form Decimal text; duplicate key; invalid JSON), and an AST test (no wall clock, no float constructor, no `src.execution` / `src.paper` / `src.adapters` / `telegram` import).

## Verification

- `uv run pytest -m "not docker" tests/test_money_at_stake.py tests/test_domain_no_float.py tests/test_margin_check.py tests/test_cost_parity.py`: 157 passed (30 in the new file).
- `uv run mypy src/risk/money_at_stake.py`: no issues. Scoped `ruff check` and `ruff format --check` on the three files: clean.
- `grep -nE "^(from|import) src\.(execution|paper|adapters)" src/risk/money_at_stake.py`: nothing.
- `git diff --exit-code -- pyproject.toml uv.lock params config src/risk/margin_check.py src/risk/cost_rates.py src/risk/types.py`: exit 0 (T-23-SC: no dependency change).
- Line endings: the two new files are LF (index and working tree); `tests/test_domain_no_float.py` kept its index-LF / working-copy-CRLF state, diff is 2 inserted lines.
- Evidence label: executed unit tests [DESIGN]. No producer calls the builder until plan 23-11 (DEMO/LIVE request issue) and Phase 24.

## Deviations from Plan

### Auto-fixed Issues

**1. [Process] Task 2 had no failing RED commit**
- **Found during:** Task 2
- **Issue:** the Task 1 GREEN implementation already carried every validation and refusal that Task 2 lists (the plan puts them in the module's design), so the Task 2 tests passed when first run; there was no failing state to commit.
- **Fix:** committed the tests as a `test(23-02)` commit; a mutation check (rounding the margin up) made the margin and parser tests fail, which shows the tests detect a wrong implementation. No `src` change in Task 2.
- **Commit:** 43b2cf23

**2. [Rule 1 - Bug, in my own RED test] Expected text of two JSON values**
- **Issue:** the RED test expected `"801.6"` and `"0.04"`; Decimal arithmetic keeps its exponent, so `4008.00 / 5` is `801.60` and `0.08 x 0.5` is `0.040`. Values are numerically equal; only the text differs.
- **Fix:** the assertions now expect `"801.60"` and `"0.040"`. **Commit:** 760d89cb

**3. [Plan example arithmetic] Non-terminating margin fixture**
- The plan's example (leverage 3, quantity 0.07, entry 50100) gives exactly 1169, a terminating quotient. The test uses entry 50101 (0.07 x 50101 / 3 = 1169.02333...) so the truncation is actually exercised.

**4. [Rule 2 - missing validation] Stop on the wrong side**
- A LONG stop at or above the entry (or a SHORT stop at or below it) is refused with field `stop_loss_price`; the plan listed only the take-profit side checks. `MoneyAtStake.__post_init__` enforces the same, and also rejects `loss_at_stop_net < loss_at_stop_gross`.

## Notes for later plans

- Stored decimals keep the exponent Python gives them (`801.60`, `0.040`); a renderer formats from the parsed Decimal, not from the text.
- `take_profits` input is a sequence of `(price, fraction)` tuples; the plan's TP fractions come from the same source the SHADOW alert uses (`TP1_QUANTITY_FRACTION` = 0.5 and its complement, `src/backtest/semantics.py`), passed by the caller; this module holds no such constant.
- Profit figures are estimates: the live TP1 leg is floored to the step size (Phase 19), so a real leg can be smaller.
- `modeled_costs_per_unit` is required (refusal field) but the net SL loss is read from `realized_risk`, not recomputed from it.
- Equity, leverage and the observation time are inputs; where they come from (account reading, constraint snapshot, paper config) is wired by plans 23-04 / 23-11.

## Known Stubs

None.

## Threat Flags

None. T-23-06 (computed once, truncated, independent recomputation in tests), T-23-07 (strict parser), T-23-08 (MONEY_AT_STAKE_MISSING with the field named) mitigated as planned; T-23-SC: no dependency change.

## Self-Check: PASSED

- FOUND: src/risk/money_at_stake.py, tests/test_money_at_stake.py
- FOUND commits: 2e461aa5, 760d89cb, 43b2cf23 (ancestors of HEAD)
