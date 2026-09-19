# Testing Strategy

## 1. Purpose

Provide deterministic tests for signal logic, timing, no-lookahead behavior, execution simulation, and state transitions.

## 2. Golden fixture model

Strategy tests must use small, human-readable fixtures.

Recommended layout:

```text
tests/fixtures/strategy/
  trend-pullback-v1/
    case-001/
      candles.csv
      parameters.json
      expected-signals.json
      expected-trade-plans.json
```

### `candles.csv`

Minimum columns:

```text
symbol,timeframe,open_time_utc,open,high,low,close,volume
```

### `expected-signals.json`

Contains only signals expected at closed-candle boundaries.

### `expected-trade-plans.json`

Contains exact Entry/SL/TP/invalidation/expiry for the fixture.

## 3. No-lookahead tests

For a prefix of candles ending at time `T`:

```text
run(prefix through T)
```

Then append arbitrary candles after `T` and run again.

The output for all events at or before `T` must be identical.

This is a mandatory invariant.

## 4. Candle-close timing tests

A strategy may inspect an unfinished candle only when explicitly classified as preview data.

For live trading decisions:

```text
kline closed = required
```

Test both:

- signal absent before close;
- signal appears exactly once after close when conditions are met.

## 5. Boundary tests

Every rule must have tests around:

- exact equality;
- just below threshold;
- just above threshold;
- exact support/resistance boundary;
- expiry timestamp;
- invalidation timestamp;
- insufficient warm-up history.

## 6. Determinism tests

Same:

```text
market data
strategyVersion
parameterSet
account state
```

must produce byte-equivalent canonical decision output.

## 7. Execution simulation tests

Cover:

- limit touched but not filled under the declared fill model;
- full fill;
- partial fill;
- entry expiry;
- invalidation before fill;
- stop before TP;
- TP before stop using finer data;
- both touched in one strategy candle;
- fee/funding/slippage application.

## 8. State-machine tests

At minimum validate invalid transitions such as:

```text
SignalStatus:    EXPIRED → APPROVED
TradePlanStatus: CANCELED → APPROVED
TradeStatus:     CLOSED   → NEW PROTECTIVE ORDER
```

unless an explicit reconciliation workflow authorizes the transition.

The order state machine has no approval state — order transitions start at `PLANNED` per `GLOSSARY.md` §5 and `EXECUTION_SPEC.md` §3. Approval is a signal/plan transition, not an order transition.

## 9. Quantization fixtures

Include symbols with different price/quantity steps.

Expected outputs must include:

```text
raw_quantity
rounded_quantity
risk_before_rounding
risk_after_rounding
quantization_decision
```

A rounded-up quantity is a test failure.

## 10. Callback idempotency tests

Send the same Telegram approval callback multiple times.

Expected behavior:

```text
first callback  → APPROVED + at most one execution intent
replay callback → return current approval/order state
```

No duplicate order is permitted.

## 11. Reconciliation tests

Simulate:

- missed user-data event;
- unknown order on exchange;
- local order missing on exchange;
- position without protective stop;
- protective orders remaining after position closes.

System must enter the documented reconciliation/safe state.


## 12. Python test/tooling conventions

The default test runner is `pytest`. Strategy and domain tests should remain runnable without a Binance account, network access, or a database.

Use:

- Ruff for formatting/linting;
- static type checking as configured in the repository;
- deterministic fixture files under `tests/fixtures`;
- explicit integration-test markers for Binance/Testnet/network tests.

A live Binance credential must never be required to run the normal test suite.
