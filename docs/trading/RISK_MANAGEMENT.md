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

Cost-aware sizing (Phase 12, D046). `risk_per_unit` is measured from the sizing entry, which is the adverse edge of the entry zone (`entry_max` for LONG, `entry_min` for SHORT), not the zone mid. `modeled_costs` is quote currency per unit of base:

```text
modeled_costs = sizing_entry x (entry_fee_rate + entry_slippage_rate)
              + stop_price x (exit_fee_rate + exit_slippage_rate)
```

The loss at the stop, costs included, is therefore at most `allowed_risk` for a fill anywhere in the zone; a fill at the zone mid loses less than the budget, so the recorded realized risk is the worst case. The zone mid remains the reference price for the minimum-notional check. The same function runs in backtest, paper and live.

## 3. Costs

Risk and performance calculations should consider:

- entry fee,
- exit fee,
- expected slippage,
- funding where applicable,
- partial fill effects.

The entry fee is modeled at the taker rate (D036): entries may fill immediately and V1 uses no post-only order. Canonical parameter sets use `partial_fill_fraction` 1.0; partial and missed fills are studied as a separate sensitivity run (D038).

Cost rates and guards (Phase 12, D046):

- All fee and slippage rates are decimal fractions (0.0005 is 5 basis points); the loader rejects any rate above 0.01 as a unit error.
- Exit slippage: stop-market exits fill worse than limits, so `exit_slippage_rate` (baseline 0.0003) is applied to SL and EOD exits; entry and TP1 use `expected_slippage`. Slippage is booked per leg as price x quantity x rate.
- `STOP_TOO_TIGHT`: the stop distance divided by the sizing entry is below `min_stop_distance_rate` (baseline 0.003).
- `COST_TO_RISK_EXCEEDED`: the round-trip modeled cost divided by `risk_per_unit` is above `max_cost_to_risk` (baseline 0.15). At the modeled round trip of about 14 basis points this ceiling implies a minimum stop of about 0.79 percent of price, above the 0.3 percent floor; the ceiling is the binding gate (D046 item 6, ratified by the operator on 2026-10-04).
- Both guards are evaluated before quantization and reject with the codes above.
- Funding (protocol v2.0.0, D052): in the simulator `funding_pnl = -sign(position) x open_quantity x markPrice(fundingTime) x fundingRate`, charged at every actual `fundingTime` with `entry_time <= fundingTime < exit_time` (sign +1 LONG, -1 SHORT, so a LONG pays when the rate is positive and receives when it is negative). The open quantity is the quantity open at that `fundingTime` (the post-TP1 remainder after a TP1). The mark price comes from the funding-history row, else from the mark kline of that minute. Funding is included in net PnL and in R (it also counts toward the daily loss, section 8) and is excluded from position sizing, so the quantity is never reduced to pre-pay it. A holding window without funding coverage fails closed unless an allowed gap is recorded. The 15-second grace around `fundingTime` that the exchange describes is not modeled.
- Live commission: the rate per side is the larger of the parameter and the account taker rate from `GET /fapi/v1/commissionRate` (fee_source `ACCOUNT_MAX`); the BNB discount is ignored. An unknown, stale or malformed account rate is NO_TRADE with `UNCERTAIN_ACCOUNT_STATE`, never zero and never a silent fallback to the parameter. Backtest and paper use the versioned fees.

## 4. Portfolio limits

Initial research placeholders:

- max open positions: `2`
- max aggregate open risk: `1.0%`
- max risk for one correlated cluster: `cluster_cap`, research placeholder `0.5%` (registry value 0.005, not yet validated)
- daily loss: warning 0.5% and stop 1.0% of equity at the UTC day start, registry keys `daily_loss_warning_threshold` and `daily_loss_stop_threshold`; defined in section 8 (D033)

These are to be validated by research and simulation.

## 5. Correlation

Do not treat simultaneous BTC/ETH/SOL/XRP directionally aligned trades as fully independent risk.

V1 may use a conservative cluster rule before a full correlation model exists.

## 6. Stop-loss integrity

Once a live position is protected, the system must not silently widen the protective stop.

Any stop modification must be explicit, logged, and permitted by the strategy/execution contract.

Re-placement of a stop is limited to a stop that was never confirmed ACTIVE and that REST proved absent: it is placed again under the same client id at the original plan SL, never a wider one (D034 clause (1)). A stop that was confirmed and later lost is never re-placed, neither automatically nor by an operator action (D077); its exposure is closed by a reduce-only order.

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

- cancel pending entry orders, so no working entry opens a new position (the simulator cancels every resting entry as `DAILY_STOP_CANCEL` at that instant, and resting entries are cancelled on DAILY_STOP in backtest exactly as in live);
- keep the protective stop-loss orders on open positions active;
- alert the user.

Live implementation (Phase 21). This paragraph describes what the code does; no rule of this section changed.

- Equity: the live account equity is the field `totalMarginBalance` of `GET /fapi/v3/account` (wallet balance plus unrealized PnL), read for the quote asset only, in single-asset margin mode only (multi-asset mode is refused). Demo-observed, not mainnet. It must be fresh (the age limit `account.max_equity_age_ms` is an owner value, 15000 ms since DECISIONS D084) and it must agree with the quote-asset row and the balance endpoint, or the result is NO_TRADE. The backtest ledger is realized-only, so the two agree only when unrealized PnL is zero (owner item O-5).
- Day state: the day-start equity base and every loss component (fill PnL, commission, funding) are persisted per UTC day (`daily_risk_days`, `daily_loss_components`), so a restart keeps the stored base and the latch. A component seen by two sources (user-data stream and REST) counts once, at the more adverse amount. A missing, unreadable or unknown day state is NO_TRADE and never NORMAL.
- Latch: once `DAILY_STOP` is reached it is held for the rest of the UTC day, whatever the loss does afterwards; the backtest derives the state per booking (owner item O-6).
- Reservation: the sized risk of a plan is reserved in the approval transaction (`risk_reservations`, under a lock on the day row), so two approvals cannot both pass a cap that only one fits. A reservation is released by the terminal state of its plan.
- Daily stop: the resting entries are cancelled with the expiry trigger `daily_stop`; the protective stop-loss orders of open positions are kept.

Nothing in this paragraph is started by a running process before Phase 24.

## 9. Margin and leverage

Leverage must be treated as an exchange/account constraint, not as the reason for choosing position size.

Margin rules (D035):

- margin mode is ISOLATED and the leverage cap is 5x;
- the system sets marginType and leverage explicitly before entry and never inherits account defaults;
- the plan is rejected unless the liquidation price lies beyond the SL with a buffer; the buffer is a registry parameter whose value is chosen in Phase 22 (D035 fixes no number);
- the available-margin check includes other resting entry orders.

Note on the buffer (Phase 22, deviation recorded, owner item O-2). The bullet above keeps its wording: a registry parameter whose value is chosen in Phase 22. The default built in Phase 22 is the owner's execution-limits key `margin.liquidation_buffer_bps` in `config/execution/execution-limits-v1.toml`, in basis points of the entry price, required and `NOT_CONFIGURED`. The reason: a hash-locked registry parameter forces a new parameter set, a new `strategy_version` and regenerated research records (D075, D076) while the backtest has no liquidation model. The registry-parameter wording stays until the owner's DECISIONS row settles the home; no number is set by this note or by any case run on the Demo.

The tool must read current account/symbol constraints before live placement.

Live implementation (Phase 22). This paragraph describes what the code does; no rule of this section changed.

- Order: for an approved plan the placement runs one guard (gate 5f2 of `execute_approved_plan`), after the position-mode check and before the hand-off record and the consume, in a fixed order: account mode (One-way, single-asset margin only), symbol configuration, liquidation, available margin. The first refusal wins and carries one plain code; a refusal consumes nothing, so the approval can be retried.
- Configuration: the margin type and leverage of the symbol are read from `GET /fapi/v1/symbolConfig`. If they already read ISOLATED and the target (5, the D035 cap) nothing is sent. Otherwise only a flat symbol with no open order, position or algo order is changed (margin type, then leverage, each at most one request, never retried), and only the closing read decides. `isAutoAddMargin` true is refused. The previous configuration is journaled and never restored.
- Liquidation: the liquidation price is computed from the exchange leverage brackets (the tier of the liquidation notional, never of the entry notional), the verified leverage and the entry fee rate; no bracket, rate or leverage value is hard-coded. It must lie strictly beyond the stop by the buffer. Brackets older than `margin.max_bracket_age_ms`, a set that is malformed, and a notional above the top bracket are refused.
- Margin: the fresh `availableBalance` must cover the initial margin of the new order (notional divided by the verified leverage), the round-trip taker fees, the open loss of an already marketable limit, the margin of the other approved or placed plans, and a headroom (`margin.headroom_bps`); a shortfall is `INSUFFICIENT_MARGIN`. Whether `availableBalance` already nets a resting order is an evidence-gated constant that stays False until the owner's DECISIONS row (two Demo samples saw the netting; demo-observed, not mainnet), so PLACED entries are counted again, which can only over-refuse.
- Other plans' margin: nothing in Phase 22 writes `required_margin`; the Phase 24 issuer calls `register_request` with it. Until then every RESERVED or PLACED row reads as an unknown margin, and a plan placed while another claim exists is refused `UNCERTAIN_ACCOUNT_STATE`. That part of the margin rule is proven on fakes and on the PostgreSQL claims reader only.
- After the first fill, once the stop is confirmed, a watch compares the exchange `liquidationPrice` of the position with the same buffer and with the local price; a danger or an unknown value (None or 0) goes to the existing CLOSE_REQUIRED path. The watch is built and tested but is not active: `ProtectionCoordinator` defaults it to None and Phase 24 composes it (whether a failed check closes or only alerts is owner item O-4).
- Fail closed and unchanged rules: any unreadable or stale input is NO_TRADE; sizing and quantization (section 11) are unchanged. The backtest has no margin or liquidation model, so these are live-only gates. Nothing in this paragraph is started by a running process before Phase 24, and the Demo cases of 2026-10-24 are single samples (demo-observed, not mainnet): the criteria are not Demo-proven beyond them.

## 10. Failure behavior

If account equity, open positions, or existing orders cannot be reconciled:

```text
FAIL CLOSED
→ do not place new order
```

## 11. Quantity quantization policy

Exchange quantity steps and minimums are symbol-specific and must be loaded from current exchange metadata. Binance's current USDⓈ-M `exchangeInfo` exposes symbol filters including price/quantity constraints; the application must read those values rather than hard-code them. [Binance Exchange Information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)

Canonical order (D031): floor to stepSize, then reject below min quantity (MIN_QTY_REJECT), then reject below min notional (NOTIONAL_REJECT), then reject when realized risk divided by allowed risk is below minimum_risk_utilization_after_rounding, baseline 60% (UTILIZATION_REJECT), then NO_TRADE; never round quantity up; identical in backtest, paper and live.

The two cost guards of section 3 (`STOP_TOO_TIGHT`, `COST_TO_RISK_EXCEEDED`) run before this quantization order and do not change it.

This is the one order implemented in `src/risk/quantization.py`; AGENTS.md, PROJECT.md and the research protocol restate it by pointer (D031).

Provenance: D031 is the source-of-authority rule that makes this section the single statement of the order when documents conflicted; it does not set any numeric value. The 60% baseline is a research parameter from this section, not a D031 value, and it is not evidence-backed.

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

The value `equity_used` comes from the live equity resolver (section 8, `totalMarginBalance`); the snapshot stays INCOMPLETE and not valid for live until Phase 22 supplies `margin_type` and `leverage`. Since Phase 22 the margin guard supplies `margin_type`, `leverage` and `equity_used` from the exchange-verified values to the in-memory snapshot handed to the protection coordinator; the persisted write-once row is not changed (Phase 24 builds it). The snapshot is persisted per plan (DATA_MODEL `trade_plans`) and a plan calculated with stale constraints must be revalidated before approval/execution (F-056, D035, D037).

Marker: verify the `market_lot_size` and `percent_price` filter definitions against current Binance docs before implementation.
