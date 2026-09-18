# TradingView Integration

## 1. Role

TradingView is optional and serves three purposes:

1. chart visualization;
2. independent Pine implementation for strategy cross-check;
3. optional webhook alert adapter.

It is **not** the canonical execution data source.

## 2. Strategy Tester

TradingView supports Pine strategies, historical backtesting, and forward testing on refreshed realtime data. [TradingView strategies/backtesting/forward testing](https://www.tradingview.com/support/solutions/43000562362-what-are-strategies-backtesting-and-forward-testing/)

## 3. Alerts

TradingView strategy and `alert()` mechanisms can send custom realtime notifications. Webhooks deliver alert payloads to an external HTTP endpoint. [TradingView strategy alerts](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/) / [Webhook alerts](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)

## 4. Cross-check pattern

Optional research flow:

```text
Same strategy concept
      ↓
Pine Script implementation
      +
Python implementation
      ↓
compare signal timestamps / levels
```

Any discrepancy becomes a research/debugging item.

## 5. Webhook security

Webhook endpoint must be authenticated and must not accept secrets in the message body. TradingView warns against putting sensitive credentials in webhook bodies. [TradingView webhook security guidance](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)

## 6. Alert-copy caveat

TradingView notes that when a strategy alert is created, a copy of the strategy runs on its servers; changes to the chart strategy do not automatically change an existing alert. Therefore strategy/version alignment must be explicit if TradingView alerts are ever used operationally. [TradingView strategy alerts](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/)


## 8. Python webhook adapter

If TradingView webhooks are enabled, the default endpoint implementation is FastAPI or another documented async Python HTTP layer. The webhook adapter must normalize the payload into a project-defined message before it reaches any strategy or execution component.
