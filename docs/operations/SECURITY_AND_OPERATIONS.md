# Security and Operations

## 1. Security baseline

- API key must not have withdrawal permission.
- Secrets must be outside source control.
- Prefer IP allowlisting where practical.
- Secrets live only in a permission-restricted `.env` (file mode 0600, owned by the service user), never in source control, with provider disk encryption on the VPS (D042). Application-level encryption of secrets at rest is not required in V1 (exclusion recorded in DECISIONS, D045).
- Avoid logging API keys/signatures.
- Webhook endpoints must be authenticated. TradingView cannot sign requests, so an HMAC signature is not available; V1 has no webhook endpoint, and if one is built the scheme is a secret URL path segment plus a source-IP allow-list (F-052). See `integration/TRADINGVIEW.md` section 5.
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

Binance market WebSocket connections are believed to have a 24-hour lifetime; a planned reconnect must therefore be part of normal operation (F-057). [Binance USDⓈ-M WebSocket market streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice) Verify the 24-hour figure against current Binance docs before implementation.

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
- API authentication failure;
- daily loss WARNING and DAILY_STOP reached (D033).

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

SAFE_MODE blocks new entry orders only, meaning orders that can open or increase a position (D034). When SAFE_MODE is active:

- Protective and reduce-only orders are always allowed, after an authoritative position query;
- existing exchange-side protective orders remain active;
- monitoring, reconciliation and journaling continue;
- a missing or canceled stop-loss is automatically re-placed at the original plan stop-loss, never wider (D034);
- a stop-loss that is rejected or not acknowledged leads to a reduce-only market close, then a HIGH-priority alert (D034);
- a database failure must not block risk-reducing actions (D034);
- nothing depends on the operator reacting within minutes, because the operator works full-time (D034).

Implementation status: the automatic stop re-placement, the reduce-only close and the DB-outage guarantee above are the target behaviour (D034), built in Phase 20 (EXEC-06, OPS-05). Until then the system enters SAFE_MODE and alerts on an unprotected position but does not re-place the stop-loss or close the position itself, so the operator must place the stop-loss or close the position manually.

This supersedes the earlier "no new live order placement" wording and the cancel-only reconciler decision (Phase 08 D-03 / Phase 09 D-02), per D034.

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
