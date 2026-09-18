# Risk Management

> Parameters below are **research baselines**, not promises or recommended personal settings.

## 1. Core rule

Risk is determined from account equity and invalidation/SL distance. Leverage is not the starting point.

Baseline research parameter:

```text
risk_per_trade = 0.5% of equity
```

For example, at $800 equity, 0.5% equals $4 of nominal risk before execution costs/uncertainty.

## 2. Position sizing concept

```text
allowed_risk = equity × risk_rate
risk_per_unit = worst_case_distance_to_SL + modeled_costs
quantity = allowed_risk / risk_per_unit
```

Then validate exchange constraints:

- minimum quantity,
- quantity step,
- price tick size,
- notional limits,
- leverage/margin requirements,
- current portfolio exposure.

## 3. Costs

Risk and performance calculations should consider:

- entry fee,
- exit fee,
- expected slippage,
- funding where applicable,
- partial fill effects.

## 4. Portfolio limits

Initial research placeholders:

- max open positions: `2`
- max aggregate open risk: `1.0%`
- max risk for one correlated cluster: `TBD`
- daily loss stop: `TBD`

These are to be validated by research and simulation.

## 5. Correlation

Do not treat simultaneous BTC/ETH/SOL/XRP directionally aligned trades as fully independent risk.

V1 may use a conservative cluster rule before a full correlation model exists.

## 6. Stop-loss integrity

Once a live position is protected, the system must not silently widen the protective stop.

Any stop modification must be explicit, logged, and permitted by the strategy/execution contract.

## 7. No revenge/compensation logic

The system must never increase risk because of previous losses or because a daily target has not been reached.

## 8. Daily risk state

Suggested states:

```text
NORMAL
WARNING
DAILY_STOP
```

When `DAILY_STOP` is reached:

- no new live positions;
- existing protective exits remain active;
- alert the user.

## 9. Margin and leverage

Leverage must be treated as an exchange/account constraint, not as the reason for choosing position size.

The tool must read current account/symbol constraints before live placement.

## 10. Failure behavior

If account equity, open positions, or existing orders cannot be reconciled:

```text
FAIL CLOSED
→ do not place new order
```

## 11. Quantity quantization policy

Exchange quantity steps and minimums are symbol-specific and must be loaded from current exchange metadata. Binance's current USDⓈ-M `exchangeInfo` exposes symbol filters including price/quantity constraints; the application must read those values rather than hard-code them. [Binance Exchange Information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)

Algorithm:

```text
raw_quantity = calculated risk-based size
rounded_quantity = floor(raw_quantity / step_size) × step_size
```

Rules:

1. Never round quantity upward if that would exceed the risk budget.
2. If rounded quantity is below minimum quantity or notional, reject.
3. If realized risk after rounding is below the configured minimum utilization threshold, reject with `QUANTIZATION_REJECT` rather than silently increasing quantity.
4. Apply exactly the same quantization logic in backtest, paper, and live modes.
5. Log raw quantity, rounded quantity, and realized risk.

Initial research baseline:

```text
minimum_risk_utilization_after_rounding = 60%
```

This is a research parameter, not a permanent trading rule.

## 12. Exchange constraint snapshot

Before live placement, store the exact symbol/risk constraints used for sizing:

```text
symbol
price_tick_size
quantity_step_size
min_quantity
notional constraints
leverage/margin constraints
metadata_observed_at_utc
```

A plan calculated with stale constraints must be revalidated before approval/execution.
