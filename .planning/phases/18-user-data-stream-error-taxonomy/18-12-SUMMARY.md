---
base: cc8d030b9af2fc3902b9e0adb820f12e5e3f704f
phase: 18-user-data-stream-error-taxonomy
plan: 12
subsystem: adapters/binance-probe
status: complete
tags: [binance, probe, demo, error-taxonomy, rate-limit, 418, 429, sdk-contract, EXEC-01, EXEC-02, D-15, D-16, D055, G2-029, T-18-32, T-18-33, T-18-34, T-18-35]
requires: [18-04, 18-05, 18-07, 18-10]
provides:
  - src/adapters/binance_probe.py (ErrorObservation, ProbeObservation, ProbeBanned, BinanceProbeAdapter, SDK_REST_METHODS, CONDITIONAL_ORDER_TYPES, MARK_PRICE_INTERVAL, ERROR_MESSAGE_MAX_CHARS)
  - tests/probe_fakes.py (FakeProbeRest, FakeProbeSdk, FakeResponse, VirtualClock, make_gate, make_public)
  - tests/test_binance_probe.py, tests/test_binance_probe_contract.py
affects:
  - plan 18-17 (probe composition builds BinanceProbeAdapter(sdk_client, policy=, rest_gate=, public=) with one gate shared by the adapter and its BinancePublicMarketData)
  - plan 18-20 (the user runs the probe on Demo; first connected run of this code)
  - plan 18-23 (G2-029 cases use the conditional-order variants)
tech-stack:
  added: []
  patterns:
    - exchange answers as frozen data (ProbeObservation / ErrorObservation) instead of exceptions
    - one SDK send site (`_call`, a single `asyncio.to_thread`) plus one gated public-read site; no loop, no sleep, no tenacity (AST-guarded)
    - SDK-shaped recording fake whose every call is bound offline against the installed SDK method signature and enum annotations, with negative controls
key-files:
  created:
    - src/adapters/binance_probe.py
    - tests/probe_fakes.py
    - tests/test_binance_probe.py
    - tests/test_binance_probe_contract.py
  modified: []
decisions:
  - "The constructor also requires the public reader to hold the SAME RestRateLimitGate instance (read through getattr of its private `_rest_gate`), so mark_price and symbol_filters can never be sent ungated during a ban or pause"
  - "reduce_only of new_limit_order and new_market_order is a required keyword typed bool | None: None omits the parameter (hedge mode rejects any reduceOnly), True/False send the SDK enum member"
  - "new_conditional_order accepts STOP_MARKET, TAKE_PROFIT_MARKET, STOP and TAKE_PROFIT only; TRAILING_STOP_MARKET is refused (it needs a callback rate this adapter does not send)"
  - "After a 418 or 429 the adapter's own flag refuses every later operation even after the shared gate opens again (ProbeBanned with retry_after_seconds None); a ban after a pause keeps IP_BAN_418"
  - "Public reads are not recorded in the gate a second time: the reader holding the same gate records the 418 or 429 itself; the probe only sets its own flag"
  - "Free-text response field `msg` (cancel answers) is scrubbed and capped like an error message"
metrics:
  duration: ~15min
  completed: 2026-10-16
  tasks: 3
  files: 4
estimate:
  tokens: 94000
  tasks: 3
actuals:
  tokens: 27300
  tasks: 3
  commits: 6
plan_head_before: cc8d030b9af2fc3902b9e0adb820f12e5e3f704f
plan_head_after: 7414b83a67fb6b667184f284e2e837b9d6e61fc4
---

# Phase 18 Plan 12: Demo-Probe Adapter Summary

`BinanceProbeAdapter` exposes the 16 exchange operations the D-16, D055 and G2-029 probe cases need. Each one returns a frozen `ProbeObservation`. An exchange error is recorded as data: the SDK class, the int Binance code, the Retry-After seconds, the taxonomy category, and the exchange message after `scrub`, capped at 200 characters. The probe holds the process-wide `RestRateLimitGate` and never retries. After any 418 or 429 it refuses every further call.

Plan revision: revised 2026-10-16 to hold the process-wide `RestRateLimitGate` of plan 18-10, per `decisions/18-DEC-O-18-01.md` and its amendment of the same day. A 418 or 429 is recorded in the shared gate. A restriction set by any holder stops the probe with `ProbeBanned`. Nothing is retried.

## Performance

- Duration: about 15 minutes (2026-10-16T06:15Z to 06:30Z)
- Tasks: 3 of 3
- Files: 4 created, 0 modified

## Task Commits

1. Task 1 (tracer): raw order and algo-order queries record the exact exchange code as data: `b036914`
2. Task 2: placements, the conditional-order variants, cancels and cancel-all, with the ban flag and the shared gate: `633a7c2`
3. Task 3: state-capture reads, the gated public mark price and filters, and the purity guards: `7414b83`

The ledger range `cc8d030..7414b83` holds 6 commits. Plans 18-13 (`e93041a`, `7babb50`) and 18-14 (`0922648`) committed on the same branch in that window. Three of the 6 commits are this plan's (`git log --grep="(18-12)"`).

## What Was Built

- **Value types.**
  - `ErrorObservation(http_class, code, retry_after_seconds, category, message)` is frozen and validated. `http_class` must be an `HttpClass` value and `category` an `ExchangeErrorCategory` value; both are stored as plain text. `code` is a strict int or None. `message` is text of at most 200 characters.
  - `ProbeObservation(operation, ok, summary, error)` is frozen. It keeps a read-only copy of the summary, and both keys and values must be text. `ok` is True exactly when `error` is None.
  - `ProbeBanned(reason, retry_after_seconds)` is the refusal.
- **`BinanceProbeAdapter(sdk_client, *, policy, rest_gate, public)`.**
  - All four arguments are required, and the last three are keyword-only.
  - The gate's policy must equal `policy.rate_limit`, and `public` must hold the same gate. Otherwise the constructor raises ValueError.
  - The adapter never builds a client and never selects an environment.
- **`_call`.**
  1. Refuses with `ProbeBanned` while the adapter's own flag is set or `rest_gate.restriction()` is not None. No SDK call is made.
  2. Adds `recv_window=policy.recv_window_ms` to the request.
  3. Makes one `asyncio.to_thread` call.
  4. Turns any `Exception` into an observation through `error_facts_from_exception`, `classify` (with a call kind per operation) and `scrub`. A `BaseException` propagates. A non-SDK exception records its type name only.
  5. On an IP_BANNED or RATE_LIMITED answer, sets the adapter's flag and calls `gate.record(category, retry_after)`.
- **Operations.**
  - Queries: `query_order`, `query_algo_order`.
  - Placements: `new_limit_order`, `new_market_order`, and `new_conditional_order` (algoType CONDITIONAL). The conditional order sends only the optional parameters that are not None. A combination Binance documents as invalid is passed through unchanged.
  - Cancels: `cancel_order`, `cancel_algo_order`, `cancel_all_open_orders`, `cancel_all_algo_open_orders`.
  - State capture: `open_orders`, `open_algo_orders`, `positions` (zero-amount rows dropped), `user_trades` (`trade_id` is the SDK `id`) and `account_balance` (non-zero assets only). Results are `count` plus `row_<i>_<field>` text.
  - `mark_price` (the latest 1m mark kline close) and `symbol_filters` (tick, step, minimum quantity, minimum notional, PERCENT_PRICE). Both go through the gated `BinancePublicMarketData`.
- **Money and enums.** Money must be a `Decimal`: a float, int, bool or text raises TypeError. Zero, negative and non-finite values raise ValueError. Values cross the SDK boundary as exact fixed-point text through the shared `_decimal_to_wire`. SDK enum members come from the installed `rest_api.models.enums` classes, and unknown text raises ValueError before any SDK call.
- **Reuse.** `_decimal_to_wire`, `_row_to_open_order_snapshot`, `_row_to_open_algo_order_snapshot` and `_row_to_position_snapshot` are imported from `src/adapters/binance_usdm.py` under their post-18-10 names; plan 18-10 renamed none of them.

## Verification

- Final plan verification: `pytest -m "not docker" tests/test_binance_probe.py tests/test_binance_probe_contract.py tests/test_binance_public.py -x` gave **138 passed**:

  | File | Passed |
  |------|--------|
  | `test_binance_probe.py` | 116 |
  | `test_binance_probe_contract.py` | 11 |
  | `test_binance_public.py` | 11 (unchanged) |

- Task 1 verify: 29 passed. Task 2 verify: 98 passed.
- `mypy src`: no issues, 197 files.
- `ruff check` and `ruff format --check`: clean on all four files of this plan. On the whole tree the only findings are in `tests/test_userdata_supervisor.py`, an in-progress file of the concurrent plan 18-14, which I did not touch.
- `uv lock --check`: exit 0; no dependency changed.
- Every command ran as `UV_OFFLINE=1 uv run --frozen --extra dev ...`. Nothing opened a connection, and every limit value is a TEST_ONLY constant.
- The contract test binds the recorded kwargs of every signed SDK call with `inspect.signature(...).bind` against the installed `DerivativesTradingUsdsFuturesRestAPI` method. It covers 13 methods across 15 operation variants. It also checks:
  - every enum-annotated parameter receives a member of that enum, and no value is a float;
  - every call carries `recv_window`;
  - the recorded method set equals `SDK_REST_METHODS`;
  - every `_call(...)` site names a declared method.

  Three negative controls prove the checks catch errors: a renamed `orig_client_order_id`, a renamed `trigger_price`, and a plain string or float in an enum or money parameter.

## TDD gate compliance

- Task 1: the tests failed first with ModuleNotFoundError, then passed.
- Task 2: 4 contract tests failed first (missing methods), then passed. The behavior tests were written before the operations.
- Task 3: collection failed first (ImportError on `MARK_PRICE_INTERVAL`), then passed. The purity-guard negative controls run on seeded temporary files.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 3 - Blocking] Shared fakes module `tests/probe_fakes.py`, which is not in the plan's file list**
- Found during: Task 1.
- Issue: the contract test has to drive the adapter with the same recording fake as the behavior tests. Importing helpers from a test module is fragile.
- Fix: a sibling fakes module, following the `tests/userdata_fakes.py` precedent.
- Commits: b036914, 633a7c2, 7414b83.

**2. [Rule 2 - Security] The public reader must hold the same gate instance**
- Found during: Task 3.
- Issue: the plan says the plan 18-17 composition builds `public` with the same `rest_gate`. Nothing enforced it, so an ungated reader would let `mark_price` or `symbol_filters` extend a ban (T-18-33).
- Fix: the constructor raises ValueError unless `getattr(public, "_rest_gate", None) is rest_gate`. It reads a private attribute of `BinancePublicMarketData` because that class has no public accessor, and the plan does not allow modifying `binance_public.py`.
- Commit: 7414b83.

### Interpretation notes (no behavior beyond the plan)

- Limit and market `reduce_only` is required and typed `bool | None`: None omits the parameter, because hedge mode rejects any reduceOnly.
- `new_conditional_order` refuses TRAILING_STOP_MARKET as well as LIMIT, MARKET and unknown text.
- `ProbeBanned.retry_after_seconds` is the gate's remaining seconds when the gate is the cause. It is None when only the adapter's own flag is the cause, for example after the gate has opened again. The flag never clears.
- A 418 or 429 met by a public read is recorded in the gate once, by the reader. The probe only sets its own flag.
- A response-shape error raised by a production row converter (a missing identity field) propagates from the signed reads, because it is not an exchange answer. A parse error inside the public reader becomes a NON_SDK observation, because the projection runs inside `exchange_info()` or `mark_klines()`.
- `ERROR_MESSAGE_MAX_CHARS = 200` is the cap the plan states. `MARK_PRICE_INTERVAL = "1m"` and `_LATEST_ROW_ONLY = 1` are structural: one row means the latest. None of them is an O-18-01 safety threshold.

## SDK delta

None. All 13 signed methods the research names (F6, cleanup toolbox) exist in the installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0 under those names, and all take `recv_window`. So do `mark_price_kline_candlestick_data` and `exchange_information`, which are reached through the public reader. These facts were read offline; the first connected run is the user's, at plan 18-20.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema beyond the plan's threat register (T-18-32 to T-18-35). The adapter never builds a client and never reads the environment.

## Open issues

- `uv run ruff check` and `ruff format --check` on the whole tree currently fail only on `tests/test_userdata_supervisor.py` (E501 and formatting). That file belongs to the concurrent plan 18-14; it was not touched.
- Whether the user-data stream `t` uses the same key space as `user_trades` `trade_id` is to be confirmed by the probe (research Open Question 8, P13).

## Self-Check: PASSED

- FOUND: src/adapters/binance_probe.py, tests/probe_fakes.py, tests/test_binance_probe.py, tests/test_binance_probe_contract.py
- FOUND commits: b036914, 633a7c2, 7414b83
