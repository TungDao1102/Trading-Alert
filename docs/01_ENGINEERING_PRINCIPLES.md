# 01 — Engineering Principles

## 1. Deterministic core

For the same:

- market data snapshot,
- account state,
- strategy version,
- configuration,

the strategy engine must produce the same result.

```text
same inputs + same version = same decision
```

## 2. No AI in trading decisions

AI/LLM must not decide or modify:

- Long vs Short.
- Entry.
- Stop loss.
- Take profit.
- Position size.
- Risk limits.
- Strategy parameters.
- Signal validity.

AI may be used for code assistance, documentation, test generation, or explanatory text only.

## 3. Exchange is the execution authority

The tool calculates a plan, but Binance is the source of truth for:

- order status,
- fills,
- position state,
- realized PnL,
- commissions,
- exchange-side conditional orders.

User-data WebSocket events should be preferred for realtime order/position updates; Binance explicitly recommends WebSocket user data when REST may lag during volatile conditions. [Binance User Data Streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/user-data-streams)

## 4. Research before optimization

Do not tune parameters to historical results before fixing the research protocol.

## 5. No hidden assumptions

Every strategy rule must be explicit:

- lookback,
- candle-closed requirement,
- tolerance,
- confirmation,
- entry,
- invalidation,
- expiry,
- SL,
- TP,
- cost model.

## 6. No repainting

A strategy must not use future information or an unfinished candle to declare a historical signal.

## 7. Immutable signal identity

Every signal must have a deterministic ID based on immutable context such as:

```text
strategyVersion + symbol + timeframe + sourceCandleCloseTime + setupType
```

so restarts cannot duplicate alerts.

## 8. UTC internally

Persist timestamps in UTC. Convert to Asia/Ho_Chi_Minh only in presentation.

## 9. Fail closed

When data integrity, connection state, account state, or risk state is uncertain:

```text
NO TRADE / DO NOT PLACE NEW ORDER
```

## 10. Human approval stays authoritative in LIVE_APPROVAL

An approval action must be explicit, auditable, idempotent, and expire.


## Python engineering principles

- Keep domain/strategy logic framework-light and deterministic.
- Do not put strategy semantics inside pandas/Polars expressions that cannot be reproduced by the live engine.
- Use `Decimal` or explicitly documented integer/tick arithmetic for exchange-sensitive values; do not rely on binary floating-point equality for order quantities/prices.
- Prefer immutable/frozen value objects for strategy decisions where practical.
- Keep async/network concerns outside the pure strategy layer.
- Use `pyproject.toml` as the project configuration source and keep tool configuration versioned.
- The live process must not depend on a Jupyter notebook or notebook state.
- Every research notebook must call reusable library code rather than contain an independent copy of the strategy.
