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

TradingView webhook delivery has no request-signing facility, so HMAC signature verification is not available for TradingView alerts: TradingView cannot sign requests and offers no custom-header mechanism to carry a credential. V1 has no webhook endpoint (INTG-02 is a v2 requirement). If an adapter is ever built, the authentication control is a set of compensating measures, not a signature check:

1. An unguessable secret path segment in the endpoint URL, treated as the credential. The secret is never placed in the alert message body; TradingView warns against putting sensitive credentials in webhook bodies. [TradingView webhook security guidance](https://www.tradingview.com/support/solutions/43000529348-about-webhooks/)
2. A source-IP allow-list of the addresses TradingView publishes for webhook POST requests. Recorded from the page on 2026-09-30: 52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7. Re-verify the list at build time; it is not a stable contract. TradingView accepts only ports 80 and 443 and does not support IPv6 for webhooks.
3. Acknowledge each request within 3 seconds (TradingView cancels a request after three seconds) and process the alert asynchronously.
4. Idempotent de-duplication of repeated alerts, because TradingView may occasionally deliver a webhook more than once or fail to deliver it.
5. Normalisation of the payload into a project-defined message before it reaches any strategy or execution component (see section 7).
6. 2FA enabled on the TradingView account: TradingView allows webhook alerts only when 2-factor authentication is enabled.

This scheme is an audit design recommendation (F-052), not an implemented control, so verify against current TradingView docs before implementation.

## 6. Alert-copy caveat

TradingView notes that when a strategy alert is created, a copy of the strategy runs on its servers; changes to the chart strategy do not automatically change an existing alert. Therefore strategy/version alignment must be explicit if TradingView alerts are ever used operationally. [TradingView strategy alerts](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/)


## 7. Python webhook adapter

If TradingView webhooks are enabled, the default endpoint implementation is FastAPI or another documented async Python HTTP layer. The webhook adapter must normalize the payload into a project-defined message before it reaches any strategy or execution component. Webhook authentication is described in section 5; TradingView cannot sign requests, so no signature check exists.
