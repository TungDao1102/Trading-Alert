# Backtest and Journal Metrics

## 1. Required trade-level fields

```text
SignalId
TradePlanId
TradeId
ApprovalId
OrderId(s)
PositionId
Strategy version
Symbol
Direction
Signal time
Approval time
Order time
Fill time
Entry intended
Entry actual
Stop loss
TP1 / TP2...
Exit time
Exit price
Gross PnL
Commission
Funding
Slippage estimate / realized slippage
Net PnL
R multiple
MFE
MAE
Duration
SessionTag
Regime
Outcome
```

## 2. Core metrics

### Win rate

```text
wins / closed trades
```

### Average R

Average realized profit/loss divided by initial trade risk.

### Expectancy

At a simple level:

```text
expectancy = average outcome in R per trade
```

It must be calculated after the defined cost model for the primary report.

### Profit factor

```text
gross profits / gross losses
```

### Maximum drawdown

Largest peak-to-trough decline in equity/PnL series according to a documented calculation.

## 3. User-vs-system reports

### System report

All valid strategy signals.

### User execution report

Only signals approved by the user.

### Opportunity report

Signals skipped/expired while the hypothetical trade outcome is still tracked.

This identifies selection bias and whether time availability changes observed performance.

## 4. Execution-quality metrics

- signal → seen latency,
- signal → approve latency,
- approve → order latency,
- intended → actual entry deviation,
- fill percentage,
- average wait to fill,
- expiry-without-fill rate.

## 5. Robustness dimensions

Slice results by:

- symbol,
- month/quarter,
- session,
- long vs short,
- volatility regime,
- trend/range regime,
- strategy version.

Do not use slices only when they make results look better; the full report must remain visible.

## 6. MFE / MAE

MFE: maximum favorable excursion after entry.

MAE: maximum adverse excursion after entry.

Track both to understand whether:

- TP is too close,
- SL is too tight,
- entry is poor,
- holding time is excessive.

## 7. Daily PnL

Daily PnL is an output metric, not a strategy constraint.

Do not modify strategy rules simply to avoid days with zero trades.

## 8. Statistical uncertainty

Primary research reports should include:

- expectancy point estimate;
- bootstrap confidence interval;
- number of resampled trades;
- block size/method when dependent observations are suspected;
- drawdown distribution from Monte Carlo/block bootstrap;
- parameter-region stability.

Do not present a single expectancy number without its sample count and uncertainty context.


## Python analytics

Reports may be generated from PostgreSQL and Parquet datasets using DuckDB/Polars/pandas. The metric definition itself must remain independent of a specific dataframe library.
