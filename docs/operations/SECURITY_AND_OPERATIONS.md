# Security and Operations

## 1. Security baseline

- API key must not have withdrawal permission.
- Secrets must be outside source control.
- Prefer IP allowlisting where practical.
- Encrypt secrets at rest.
- Avoid logging API keys/signatures.
- Webhook endpoints must be authenticated.
- Separate paper/test credentials from live credentials.

## 2. Live safety

Default state after deployment:

```text
LIVE_ORDERS_DISABLED
```

The operator must explicitly enable live execution.

## 3. Reconnect

All external connections must have:

- heartbeat,
- reconnect,
- backoff,
- state reconciliation.

Binance market WebSocket connections currently have a 24-hour lifetime; a planned reconnect must therefore be part of normal operation. [Binance WebSocket market streams](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/websocket-market-streams/Connect)

## 4. Health checks

Monitor:

- market feed freshness,
- last closed candle time,
- WS connection state,
- user-data stream state,
- REST error rate,
- reconciliation drift,
- database writes,
- Telegram delivery,
- unprotected positions,
- orphaned orders.

## 5. Alerts

High priority:

- position exists without expected protective stop;
- local state disagrees with Binance;
- unknown order event;
- duplicate execution attempt;
- stale market data;
- exchange rejects risk-protective action;
- API authentication failure.

## 6. Logging

Structured logs should contain:

- correlation ID,
- SignalId,
- OrderId/clientOrderId when present,
- symbol,
- strategy version,
- timestamp UTC,
- event type,
- result.

Never log secret credentials.

## 7. SAFE_MODE

When SAFE_MODE is active:

- no new live order placement;
- existing exchange-side protective orders remain active;
- system continues monitoring and journaling.

## 8. Restart behavior

On restart:

```text
load config
→ validate time
→ restore strategy cache
→ reconcile Binance orders/positions
→ reconnect streams
→ verify no duplicate signal/order action
→ resume only when consistent
```

## 9. Backup and restore

The PostgreSQL database must have:

- automated backup;
- encrypted copy outside the primary runtime host;
- documented retention;
- periodic restore verification.

The self-collected OI dataset and journal are research assets. Backup loss is treated as a data-loss incident, not merely an infrastructure inconvenience.

See `operations/RUNBOOK.md` for the restore/emergency procedure.


## 10. Python runtime operations

- Build from a locked Python dependency set.
- Do not install packages interactively on the production host.
- Record Python runtime version and application git revision in health/diagnostic output.
- Separate research/development dependencies from the minimal live runtime where practical.
- Test dependency upgrades in paper/testnet before live enablement.
