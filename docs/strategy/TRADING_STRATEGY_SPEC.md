# Trading Strategy Specification

> Status: TEMPLATE — **NOT FROZEN**
>
> This file becomes implementation-authoritative only after the research gates pass.

## 1. Strategy identity

- Strategy ID: `TBD`
- Strategy version: `TBD`
- Direction: `LONG`, `SHORT`, or both — `TBD`
- Primary timeframes: `TBD`
- Supported symbols: `TBD`

## 2. Market regime

### Long regime

`TBD`

### Short regime

`TBD`

### Neutral / no-trade regime

`TBD`

## 3. Market structure definitions

- Swing High: `TBD`
- Swing Low: `TBD`
- Support zone: `TBD`
- Resistance zone: `TBD`
- Breakout: `TBD`
- Retest: `TBD`
- Confirmation: `TBD`

## 4. Setup detection

```text
Prerequisites:
TBD

Trigger:
TBD

Confirmation:
TBD
```

## 5. Entry

- Entry type: `LIMIT_ZONE | LIMIT | MARKET | TBD`
- Entry calculation: `TBD`
- Allowed slippage/buffer: `TBD`
- Order validity: `TBD`

## 6. Invalidation

A setup becomes invalid when any of the following occurs:

- `TBD`

## 7. Stop loss

- Calculation: `TBD`
- Trigger price basis: `TBD`
- Maximum allowed stop distance: `TBD`

## 8. Take profit

- TP1: `TBD`
- TP2: `TBD`
- Minimum R:R: `TBD`
- Partial exit rules: `TBD`

## 9. Expiry

- Time expiry: `TBD`
- Candle-based expiry: `TBD`
- Structure invalidation: `TBD`

## 10. Risk compatibility

Strategy must expose enough data for the risk engine to calculate:

```text
entry reference
stop reference
expected quantity constraints
expected reward
```

## 11. Determinism requirement

No external LLM call or subjective classifier may alter the strategy result.

## 12. Strategy versioning

Any change to:

- detection rules,
- entry,
- SL,
- TP,
- invalidation,
- expiry,
- feature definition,

must create a new strategy version and a new backtest record.

## 13. Acceptance status

- Research complete: `NO`
- Out-of-sample validated: `NO`
- Forward tested: `NO`
- Approved for live human-approved trading: `NO`


## Implementation neutrality

The strategy contract is technology-independent. Python is the project implementation language, but strategy semantics must remain expressible as deterministic inputs/outputs and must not depend on pandas, Polars, notebooks, network calls, or Binance SDK objects.
