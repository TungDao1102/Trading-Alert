# Backtest Specification

## 1. Purpose

Estimate how a deterministic strategy would have behaved under explicit data, execution, and cost assumptions.

A backtest is evidence about the tested assumptions, not proof of future performance.

## 2. Data hierarchy

Preferred:

- 4H + 1H for strategy.
- 1M for execution simulation where available and appropriate.
- Historical funding where strategy/cost model needs it.
- Self-collected OI for periods outside Binance's historical API window.

## 3. Candle-close rule

Strategy decisions must use information available by the source candle close.

No future candle data, future swing confirmation, or future intrabar outcome may leak into historical decisions.

## 4. Intrabar ambiguity

If a strategy candle's high/low touches both stop and target, execution must be resolved using finer-resolution data when available.

If finer data is unavailable, use a conservative deterministic assumption and report it.

## 5. Fees and funding

All backtests must expose cost configuration.

Minimum:

- entry fee,
- exit fee,
- funding treatment,
- slippage,
- spread/fill assumptions.

## 6. Limit-order simulation

Backtest must model:

- price touched vs actual fill,
- partial fill assumption,
- time-in-force / expiry,
- canceled entry after invalidation,
- no retroactive fill after expiry.

## 7. Dataset splits

Minimum:

```text
Development
    ↓
Validation
    ↓
Final holdout / forward test
```

The final holdout must not be used to choose parameters.

## 8. Walk-forward

Where practical, use rolling windows:

```text
train → validate → roll forward
```

This is especially important when testing parameterized structure/ATR rules.

## 9. Baselines

Every candidate strategy should be compared with at least one simple baseline, e.g.:

- no-trade,
- buy/hold for spot-style reference when appropriate,
- simple trend filter without the proposed setup.

The purpose is not to prove a strategy “wins”; it is to understand whether the added complexity contributes measurable value.


## 10. Statistical power and uncertainty

Backtest sample size must be treated as a limitation, not hidden behind a single expectancy number.

Required reporting:

- trade count overall and by symbol/quarter/regime;
- mean, median, standard deviation of R;
- bootstrap interval for expectancy;
- drawdown distribution under resampling;
- stability across time and symbols.

If trade returns are plausibly dependent or clustered, use a block/bootstrap method rather than assuming independent observations.

As a diagnostic, for approximately independent trade outcomes with standard deviation `σ`, the standard error of the mean is approximately:

```text
SE ≈ σ / sqrt(n)
```

For example, if `σ ≈ 1.2R`, then `n = 500` gives `SE ≈ 0.054R`, so a 95% interval is still roughly ±0.11R before accounting for dependence. This illustrates why an observed expectancy such as +0.15R may remain statistically uncertain even after hundreds of trades.

This is a methodology warning, not a claim that a fixed sample size proves or disproves a strategy.

## 10.1 Research universe vs live universe

To increase research sample size without changing the intended live product:

- research may evaluate 10–15 sufficiently liquid symbols;
- live V1 may remain limited to the declared 5-symbol universe;
- the research report must show results both for the broader research universe and the intended live universe.

A strategy must not be accepted solely because the broader universe rescues a weak live universe.

## 11. Experiment record

Each run stores:

- experiment ID,
- strategy version,
- dataset range,
- symbol universe,
- timeframe,
- all parameters,
- cost assumptions,
- results,
- code/data version,
- notes.

## 11. Acceptance gates

A strategy may proceed only when:

1. rules are deterministic;
2. there is no material look-ahead;
3. costs are modeled;
4. results are not confined to one symbol/session;
5. out-of-sample behavior is not materially inconsistent without an understood reason;
6. drawdown and loss streak are operationally tolerable;
7. results are reproducible;
8. uncertainty is reported with distributional/interval analysis rather than a single point estimate;
9. no critical conclusion depends on a single symbol, quarter, or isolated parameter point;
10. candidate has been compared against declared baselines.

Exact numerical acceptance thresholds remain `TBD` until the research methodology is exercised on real data.


## 13. Research implementation

Exploratory backtests may use pandas/Polars/NumPy/VectorBT, but the final validation path must execute the canonical project strategy/backtest engine. A library-specific vectorized result is not sufficient evidence when execution semantics such as partial fill, expiry, quantization, or intrabar resolution differ.
