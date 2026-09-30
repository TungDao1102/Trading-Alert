---
phase: 12-fee-cost-model-correctness
plan: 05
subsystem: risk-live-commission
tags: [commission-rate, fail-closed, adapter, exchange-authority, decimal]
status: complete

requires:
  - phase: 12-02
    provides: commission_rate_ttl_seconds registry key
  - phase: 12-03
    provides: CostRates, FEE_SOURCE_ACCOUNT_MAX, MAX_RATE
provides:
  - src/risk/live_commission.py (AccountCommission, LiveCostRatesResult, resolve_live_cost_rates)
  - BinanceUsdmAdapter.user_commission_rate and the CommissionRates dataclass
  - SOURCES.md "Facts verified for Phase 12" and BINANCE.md section 12
affects: [12-08 (execution manager checks the resolver result), 24 (runtime refresh loop and Demo verification)]

actuals:
  tokens: 34000
  tasks: 3
  commits: 5

commits: 5
plan_head_before: 11ad2b61a1388e9bcea6c6f1ea52c3a70f0bd601
plan_head_after: 061e26fd76d574869fbe8710ea708d07c4af4ce6

tech-stack:
  added: []
  patterns:
    - "Pure resolver with injected clock and TTL; freshness rule copied from check_portfolio (age greater than ttl or negative fails closed, equality passes)"
    - "Adapter strict parse: unknown raises ValueError, never a zero; frozen project dataclass, SDK model never leaks"

key-files:
  created:
    - src/risk/live_commission.py
    - tests/test_commission_rates.py
  modified:
    - src/adapters/binance_usdm.py
    - tests/test_adapter_strictness.py
    - docs/SOURCES.md
    - docs/integration/BINANCE.md

key-decisions:
  - "The adapter defines its own 0.01 rate ceiling (_MAX_COMMISSION_RATE) instead of importing src.risk.cost_rates.MAX_RATE, because the adapter module imports nothing from src; AccountCommission re-validates with MAX_RATE."
  - "The SOURCES.md commissionRate row stays MEDIUM: the official page was not read directly in either the research session or this execution (no page-fetch tool for the executor; curl got a redirect and no body)."

requirements-completed: [RISK-01]

coverage:
  - deliverable: "resolve_live_cost_rates returns per-side max(parameter, account taker) with ACCOUNT_MAX, slippage passed through, zero account rate floored"
    verification:
      - kind: test
        ref: "tests/test_commission_rates.py#test_account_taker_below_parameter_keeps_parameter"
        status: pass
      - kind: test
        ref: "tests/test_commission_rates.py#test_account_taker_above_parameter_wins_on_both_sides"
        status: pass
      - kind: test
        ref: "tests/test_commission_rates.py#test_account_taker_zero_is_a_real_rate_floored_by_parameter"
        status: pass
    human_judgment: false
  - deliverable: "Missing, wrong-symbol, stale, future-dated account commission fails closed to UNCERTAIN_ACCOUNT_STATE with no rates; exact TTL passes"
    verification:
      - kind: test
        ref: "tests/test_commission_rates.py#test_stale_by_one_second_fails_closed"
        status: pass
      - kind: test
        ref: "tests/test_commission_rates.py#test_future_dated_by_one_second_fails_closed"
        status: pass
      - kind: test
        ref: "tests/test_commission_rates.py#test_age_exactly_equal_to_ttl_passes"
        status: pass
    human_judgment: false
  - deliverable: "Adapter user_commission_rate parses strictly through the SDK and raises on every malformed field"
    verification:
      - kind: test
        ref: "tests/test_adapter_strictness.py#test_user_commission_rate_projects_frozen_dataclass"
        status: pass
      - kind: test
        ref: "tests/test_adapter_strictness.py#test_user_commission_rate_raises_on_malformed_response"
        status: pass
      - kind: test
        ref: "tests/test_adapter_strictness.py#test_user_commission_rate_propagates_sdk_exception"
        status: pass
    human_judgment: false
  - deliverable: "Endpoint facts, provenance and sizing/fail-closed rules recorded in SOURCES.md and BINANCE.md"
    verification:
      - kind: command
        ref: "python scripts/verify_decision_alignment.py docs"
        status: pass
    human_judgment: true
    rationale: "The commissionRate row is MEDIUM confidence (official page not read directly); a human should re-confirm weight and field semantics on the official page before Phase 24."
---

# Phase 12 Plan 05: Live commission-rate resolver and adapter read Summary

**Live sizing now gets a pure per-side max(parameter, account taker) fee resolver that returns NO_TRADE / UNCERTAIN_ACCOUNT_STATE on any missing, wrong-symbol, stale or future-dated account rate, plus a strict `user_commission_rate` adapter method over the official SDK and a documented provenance trail.**

## Performance

- Tasks: 3 (1 tracer, 1 auto TDD, 1 auto docs); Tasks 1 and 2 each have a separate RED commit
- Commits: 5 (measured from the ledger)
- Files: 2 created, 4 modified

## Accomplishments

- `src/risk/live_commission.py`: `AccountCommission` (frozen; non-empty symbol, Decimal-only rates in [0, 0.01], UTC-aware timestamp), `LiveCostRatesResult` (rates None needs a non-OK RejectionReason code, rates present needs OK; derived `is_no_trade`), and `resolve_live_cost_rates`. Successful results build `CostRates` with `fee_source=ACCOUNT_MAX`; entry and exit fees are both `max(parameter, account taker)`; slippage rates pass through. The maker rate is validated and carried but unused (D036); the BNB discount is ignored (F-031). A naive or non-UTC `now_utc`, or a non-positive `ttl`, raises `ValueError`.
- `src/adapters/binance_usdm.py`: `CommissionRates(symbol, maker_rate, taker_rate)` and `user_commission_rate(symbol)`, calling `rest_api.user_commission_rate(symbol)` via `asyncio.to_thread` with `recv_window` left to the SDK. `ValueError` on None response, missing or mismatched symbol, and on a missing, empty, non-decimal, non-finite, negative or above-0.01 maker/taker field. A `"0"` rate is returned as `Decimal("0")`. SDK exceptions propagate; no clock, no retry, no Protocol change. Messages carry symbol and field name only.
- `docs/SOURCES.md`: "Facts verified for Phase 12 (2026-09-30)" with the commissionRate row (MEDIUM, honest retrieval note), the change-log RPI row, and a row stating Demo/testnet behavior is undocumented and verified in Phase 24. `docs/integration/BINANCE.md` section 12 states the endpoint with the verify marker, the max rule, the ignored BNB discount, the fail-closed rule, the backtest/paper parameter-fee rule (D-12) and the Phase 24 runtime deferral (D-13).

## Task Commits

1. Task 1 RED: `f5249c7` test(12-05) - resolver max rule, TTL boundary, fail-closed cases
2. Task 1 GREEN: `0a591b3` feat(12-05) - live commission resolver
3. Task 2 RED: `b92ec6d` test(12-05) - adapter strict parsing and fake-REST cases
4. Task 2 GREEN: `e90f559` feat(12-05) - adapter `user_commission_rate`
5. Task 3: `061e26f` docs(12-05) - SOURCES.md and BINANCE.md

## Verification

- `pytest tests/test_commission_rates.py tests/test_adapter_strictness.py tests/test_execution_adapter_contract.py tests/test_execution_secret_posture.py`: pass
- `mypy` on both source files: no issues; `ruff check` on all touched code and tests: clean
- `python scripts/verify_decision_alignment.py docs`: `ALL_PASS docs`; `tests/test_decision_alignment_exchange.py`: pass
- Full `pytest tests`: exit 0
- Adapter diff acceptance: `git diff` on `src/adapters/binance_usdm.py` adds the dataclass, the method, two private helpers (`_MAX_COMMISSION_RATE`, `_require_commission_rate`), one docstring table row and `InvalidOperation` in an existing import line (1 line changed).
- Tracer gate: resolver tests, mypy and ruff re-run green before expansion.

## Deviations from Plan

**1. [Rule 3 - Blocking] Official commissionRate page could not be retrieved by the executor**
- **Found during:** Task 3
- **Issue:** The executor has no page-fetch tool; a curl attempt returned a 302 and no page text, so the plan's "try WebFetch then web search" re-verification could not raise the row to HIGH.
- **Fix:** Kept the research session's honest MEDIUM wording and recorded the failed attempt in the Method column; nothing was written that was not read (endpoint facts come from search text, the installed SDK 17.4.0 method/model, and the change-log).
- **Files modified:** docs/SOURCES.md
- **Commit:** `061e26f`

**Total deviations:** 1 (documentation confidence only). **Impact:** none on code; Phase 24 must re-confirm weight and field semantics on the official page and verify the Demo behavior.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema; the adapter method reuses the existing signed SDK client.

## Self-Check: PASSED

- Files exist: src/risk/live_commission.py, tests/test_commission_rates.py, this SUMMARY.
- Commits f5249c7, 0a591b3, b92ec6d, e90f559, 061e26f present on master.
