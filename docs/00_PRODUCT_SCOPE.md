# 00 — Product Scope

## 1. Product goal

Build a deterministic trading research and semi-automation tool for Binance Futures that helps a full-time worker detect and act on a small number of well-defined trade setups without continuous chart watching.

The product is intended to reduce **observation time and execution friction**, not to guarantee daily income.

## 2. User constraints

- Full-time worker; cannot monitor charts continuously.
- Initial capital target: approximately USD 500–1,000.
- Wants limited, controlled risk rather than maximum leverage.
- Can review mobile notifications but cannot guarantee response within minutes.
- Human should remain in control of whether a live trade is approved during early phases.

## 3. Target workflow

```text
Realtime market data
  → detect deterministic setup
  → generate complete trade plan
  → notify
  → user reviews
  → approve or skip
  → system optionally places entry + protective exits
  → exchange manages active orders
  → system records all events
```

## 4. Scope

### In scope

- Binance Futures market-data ingestion.
- Historical data storage for backtesting.
- Deterministic strategy engine.
- Trade-plan generation:
  - direction
  - entry zone / entry price
  - stop loss
  - take profit(s)
  - invalidation
  - expiry
  - expected R multiple
  - risk and position quantity
- Telegram notifications and human approval.
- Optional live order placement after approval.
- User-data stream monitoring for orders and positions.
- Full signal/order/position journal.
- Backtest, paper-trade, and forward-test modes.
- TradingView research/cross-check and optional webhook adapter.

### Out of scope for initial release

- Fully autonomous live trading.
- LLM/AI price prediction.
- LLM-generated entry/SL/TP.
- News-driven discretionary prediction.
- Order-book ML.
- Reinforcement learning.
- High-frequency/scalping system.
- Large universe of illiquid altcoins.
- Forced daily profit target.

## 5. Initial market universe

Candidate V1 universe:

- BTCUSDT
- ETHUSDT
- BNBUSDT
- SOLUSDT
- XRPUSDT

This is a research universe, not a claim about future performance.

## 6. Initial timeframes

Primary strategy timeframes:

- 4H: regime/context.
- 1H: setup generation.

Optional later:

- 15M: entry refinement only.
- 5M: discretionary timing aid, not a required V1 dependency.

Backtest execution simulation may use 1M data to resolve intrabar order sequencing; this does not make 1M the strategy timeframe.

## 7. Operating modes

Canonical list per `GLOSSARY.md` §8:

1. `RESEARCH`
2. `BACKTEST`
3. `PAPER`
4. `LIVE_APPROVAL`
5. `SAFE_MODE`
6. `LIVE_AUTONOMOUS_DISABLED` — future only, disabled by default and requiring explicit evidence/gates.

The canonical name `LIVE_AUTONOMOUS_DISABLED` records the current disabled-by-default state of the future autonomous mode described in `GLOSSARY.md` §8.

## 8. Daily-profit principle

The system must **not** force trades to reach a daily PnL target. A day with zero trades is valid.

The product should optimize for:

- positive net expectancy after costs,
- controlled drawdown,
- operational reliability,
- repeatability.

It should not optimize for a fixed `$X/day` target.

## 9. Success criteria

A strategy is not accepted because it makes money on one backtest. It must satisfy the validation gates in `backtest/BACKTEST_SPEC.md` and remain understandable enough to explain every signal.

## 10. Expected return envelope — planning reality

This section is an **illustrative planning model, not a performance forecast**. Trade frequency and expectancy remain unknown until a strategy is researched and validated.

The basic relationship is:

```text
expected_monthly_net_pnl
≈ equity × risk_per_trade × trades_per_month × expectancy_R
```

For example, using an intentionally simple scenario:

```text
equity            = $800
risk_per_trade    = 0.5%
trades_per_month  = 15
expectancy        = +0.175R

≈ $800 × 0.005 × 15 × 0.175
≈ $10.50/month
```

Scenario examples (illustrative only):

| Equity | Risk/trade | 10 trades/mo | 15 trades/mo | 20 trades/mo |
|---:|---:|---:|---:|---:|
| $500 | 0.5% | $4.38 | $6.56 | $8.75 |
| $800 | 0.5% | $7.00 | $10.50 | $14.00 |
| $1,000 | 0.5% | $8.75 | $13.13 | $17.50 |
| $800 | 1.0% | $14.00 | $21.00 | $28.00 |
| $1,000 | 1.0% | $17.50 | $26.25 | $35.00 |

These are arithmetic scenarios only. They assume the stated expectancy is already net of the modeled costs and remains stable, which is unproven until research is completed.

For a target of $200/month, the same illustrative middle scenario (`15 trades × 0.175R`) would imply approximately:

```text
equity at 0.5% risk ≈ $15,238

equity at 1.0% risk ≈ $7,619
```

At $800 equity, achieving $200/month under those assumptions would require roughly 9.5% risk per trade, which is incompatible with the project's capital-preservation objective. This is why V1 must optimize for evidence, execution discipline, and capital survival rather than a fixed income target.

The project therefore treats the initial $500–1,000 as **research capital**, not as capital that should reliably produce a living-expense stream.


## 11. Technology baseline

The project uses Python as the primary implementation language for research, backtesting, paper trading, and human-approved live orchestration. This choice is based on the project's research-heavy workload and is documented in `TECHNOLOGY_STACK.md`.
