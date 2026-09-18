# Glossary and Canonical Enums

This is the single source of truth for domain terminology and status values.

## 1. Trading concepts

### Signal
A deterministic detection that a strategy's setup conditions are satisfied at a specific closed-candle observation.

### TradePlan
A signal translated into explicit entry, SL, TP, invalidation, expiry, and risk information.

### Order
An instruction submitted or intended for submission to Binance.

### Fill
An executed quantity/price event for an order.

### Position
The exchange/account exposure resulting from fills.

### Setup
A strategy pattern definition before it becomes a signal instance.

### Regime
The current high-timeframe market state used by the strategy, such as `BULLISH`, `BEARISH`, `NEUTRAL`, or `NO_TRADE`.

### Entry Zone
A price interval within which the strategy permits entry. It is a rule output, not a discretionary range invented at execution time.

### Invalidation
A deterministic condition that makes the setup no longer valid.

### Expiry
A time boundary after which an unfilled entry plan must not be executed.

## 2. Canonical SignalStatus

```text
DETECTED
NOTIFIED
VIEWED
APPROVED
SKIPPED_USER
SKIPPED_BUSY
EXPIRED
INVALIDATED
```

Execution lifecycle states do not belong in `SignalStatus`.

## 3. Canonical TradePlanStatus

```text
READY
APPROVAL_PENDING
APPROVED
EXPIRED
INVALIDATED
SUPERSEDED
```

## 4. Canonical ApprovalAction

```text
SIMULATE
APPROVE
SKIP_USER
SKIP_BUSY
CANCEL
```

`VIEWED` is an observation state, not an approval action.

## 5. Canonical OrderStatus

```text
PLANNED
SUBMITTING
NEW
PARTIALLY_FILLED
FILLED
CANCELED
EXPIRED
REJECTED
UNKNOWN
```

## 6. Canonical TradeStatus

```text
PENDING
OPEN
CLOSED
ABORTED
UNKNOWN
```

## 7. Canonical PositionStatus

```text
OPEN
CLOSING
CLOSED
LIQUIDATION_REPORTED
UNKNOWN
```

## 8. Canonical SystemMode

```text
RESEARCH
BACKTEST
PAPER
LIVE_APPROVAL
SAFE_MODE
LIVE_AUTONOMOUS_DISABLED
```

`LIVE_AUTONOMOUS` is a future architecture mode and is disabled by default.

## 9. Canonical rejection reasons

```text
NO_TRADE_REGIME
RR_TOO_LOW
STALE_SETUP
INVALIDATED
RISK_LIMIT
CORRELATED_RISK_LIMIT
DAILY_STOP
QUANTIZATION_REJECT
MIN_NOTIONAL_REJECT
INSUFFICIENT_MARGIN
EXCHANGE_CONSTRAINT
DATA_STALE
RECONCILIATION_REQUIRED
APPROVAL_EXPIRED
```

Do not create synonyms such as `Skipped-User`, `USER_SKIPPED`, and `SKIPPED_USER` in different modules. Use the canonical enum names above.
