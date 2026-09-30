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

The entry fee is modeled at the taker rate (D036): entries may fill immediately and V1 uses no post-only order. Canonical parameter sets use `partial_fill_fraction` 1.0; partial and missed fills are studied as a separate sensitivity run (D038).

## 4. Portfolio limits

Initial research placeholders:

- max open positions: `2`
- max aggregate open risk: `1.0%`
- max risk for one correlated cluster: `TBD`
- daily loss: warning 0.5% and stop 1.0% of equity at the UTC day start, registry keys `daily_loss_warning_threshold` and `daily_loss_stop_threshold`; defined in section 8 (D033)

These are to be validated by research and simulation.

## 5. Correlation

Do not treat simultaneous BTC/ETH/SOL/XRP directionally aligned trades as fully independent risk.

V1 may use a conservative cluster rule before a full correlation model exists.

## 6. Stop-loss integrity

Once a live position is protected, the system must not silently widen the protective stop.

Any stop modification must be explicit, logged, and permitted by the strategy/execution contract.

Automatic re-placement of a missing or canceled stop-loss restores the original plan SL, never a wider one (D034).

## 7. No revenge/compensation logic

The system must never increase risk because of previous losses or because a daily target has not been reached.

Compensation includes adding to a losing position: there is no averaging down (F-116).

## 8. Daily risk state

Suggested states:

```text
NORMAL
WARNING
DAILY_STOP
```

Definition (D033):

- the day is the UTC day (00:00 UTC = 07:00 Asia/Ho_Chi_Minh);
- daily loss = realized PnL + commissions + funding, counted as a loss;
- the base is account equity at the UTC day start;
- `WARNING` at 0.5% and `DAILY_STOP` at 1.0% of that base.

When `DAILY_STOP` is reached (D033):

- cancel pending entry orders, so no working entry opens a new position;
- keep the protective stop-loss orders on open positions active;
- alert the user.

## 9. Margin and leverage

Leverage must be treated as an exchange/account constraint, not as the reason for choosing position size.

Margin rules (D035):

- margin mode is ISOLATED and the leverage cap is 5x;
- the system sets marginType and leverage explicitly before entry and never inherits account defaults;
- the plan is rejected unless the liquidation price lies beyond the SL with a buffer; the buffer is a registry parameter whose value is chosen in Phase 22 (D035 fixes no number);
- the available-margin check includes other resting entry orders.

The tool must read current account/symbol constraints before live placement.

## 10. Failure behavior

If account equity, open positions, or existing orders cannot be reconciled:

```text
FAIL CLOSED
→ do not place new order
```

## 11. Quantity quantization policy

Exchange quantity steps and minimums are symbol-specific and must be loaded from current exchange metadata. Binance's current USDⓈ-M `exchangeInfo` exposes symbol filters including price/quantity constraints; the application must read those values rather than hard-code them. [Binance Exchange Information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)

Canonical order (D031): floor to stepSize, then reject below min quantity (MIN_QTY_REJECT), then reject below min notional (NOTIONAL_REJECT), then reject when realized risk divided by allowed risk is below minimum_risk_utilization_after_rounding, baseline 60% (UTILIZATION_REJECT), then NO_TRADE; never round quantity up; identical in backtest, paper and live.

This is the one order implemented in `src/risk/quantization.py`; AGENTS.md, PROJECT.md and the research protocol restate it by pointer (D031).

Algorithm:

```text
raw_quantity = calculated risk-based size
rounded_quantity = floor(raw_quantity / step_size) × step_size
```

Rules:

1. Never round quantity upward if that would exceed the risk budget.
2. If rounded quantity is below minimum quantity, reject with `MIN_QTY_REJECT`.
3. If rounded quantity is below minimum notional, reject with `NOTIONAL_REJECT`.
4. If realized risk after rounding is below the configured minimum utilization threshold, reject with `UTILIZATION_REJECT` rather than silently increasing quantity.
5. Apply exactly the same quantization logic in backtest, paper, and live modes, and log raw quantity, rounded quantity, and realized risk.

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
min_notional
market_lot_size (min, max, step)
percent_price (multiplierUp, multiplierDown)
leverage/margin constraints
working_type
margin_type
leverage
equity_used
metadata_observed_at_utc
```

The snapshot is persisted per plan (DATA_MODEL `trade_plans`) and a plan calculated with stale constraints must be revalidated before approval/execution (F-056, D035, D037).

Marker: verify the `market_lot_size` and `percent_price` filter definitions against current Binance docs before implementation.
