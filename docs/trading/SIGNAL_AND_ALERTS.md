# Signal and Alerts

## 1. Signal is not an order

A signal means:

> the strategy detected a valid setup.

A trade plan means:

> the setup has explicit entry/SL/TP/risk data.

An order means:

> the user approved the plan and the execution manager submitted it.

Keep these as separate domain objects.

Signal-level approval (`SignalStatus.APPROVED`) records user approval observed on the signal instance; plan-level approval (`TradePlanStatus.APPROVED`) authorizes execution handoff; order placement reads the plan status. The transition order is Signal APPROVED → TradePlan APPROVED → Order PLANNED. (D028)

## 2. Signal fields

Minimum:

```text
SignalId
StrategyId
StrategyVersion
Symbol
Direction
DetectedAtUtc
SourceTimeframe
SourceCandleCloseUtc
SetupType
Regime
EntryZone
StopLoss
TakeProfit(s)
Invalidation
ExpiresAtUtc
ExpectedRR
RiskRate
FeatureSnapshotId
Status
```

## 3. Deterministic SignalId

Recommended concept:

```text
hash(
    StrategyVersion,
    Symbol,
    SourceTimeframe,
    SourceCandleCloseUtc,
    SetupType
)
```

This protects against duplicate alerts after restart.

## 4. Signal states (canonical)

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

Execution lifecycle states do not belong in `SignalStatus`; the canonical signal-state list above is the sole authoritative per `GLOSSARY.md` §2.

The execution lifecycle for an order after a plan approval is documented under the OrderStatus section of `GLOSSARY.md` (canonical order-state values) and under the TradeStatus section of `GLOSSARY.md` (canonical trade-state values); cross-reference those sections for execution-side state names. The domain-separation rule is defined in `DATA_MODEL.md` §3.

## 5. User-facing alert

Example:

```text
🟢 BTCUSDT LONG SETUP

Strategy: Trend-Pullback-v1
4H regime: BULLISH
1H setup: Pullback + confirmation

Entry: 103800–104050
SL: 103250
TP1: 105200
TP2: 106000
Expected R:R: 1.8 / 3.9
Risk: 0.5%
Valid until: 16:00 UTC

Why:
✓ higher-timeframe regime valid
✓ structure zone confirmed
✓ trigger candle closed
✓ required R:R passed
✓ portfolio risk available

[SIMULATE] [APPROVE] [SKIP]
```

The exact wording can change; the underlying numbers and reasons come from deterministic engine output.

## 6. Alert quality rules

- No alert for an unfinished strategy candle unless explicitly designated as an informational preview.
- No stale plan may be approved.
- No repeated alert for the same signal ID.
- Signal must show enough context to understand why it exists.

## 7. Human execution metrics

Record:

- delivered_at,
- seen_at if available,
- approve_at,
- order_submission_at,
- delay from signal to order.

This is required to quantify the user's limited availability instead of guessing.
