# Data Model

## 1. Purpose

This document is the canonical persistence contract for the trading tool.

The domain must keep these concepts separate:

```text
Signal
  ↓
TradePlan
  ↓
Approval
  ↓
Order(s)
  ↓
Fill(s)
  ↓
Position
  ↓
JournalEvent(s)
```

Do not collapse these entities into one row or one status enum.

## 2. Core entities

### 2.1 `market_candles`

Purpose: immutable normalized OHLCV observations.

Minimum fields:

```text
id
symbol
timeframe
open_time_utc
close_time_utc
open_price
high_price
low_price
close_price
volume
quote_volume
trade_count
source
ingested_at_utc
```

Canonical key:

```text
(symbol, timeframe, open_time_utc)
```

Recommended index:

```text
(symbol, open_time_utc)
```

1m data should be partitionable by month on `open_time_utc`.

### 2.2 `feature_snapshots`

**V1 status: not built (D045).** Feature snapshots are recomputed deterministically from closed candles; the field list below is a design record.

Immutable derived inputs used by a strategy evaluation.

```text
id
strategy_version
symbol
timeframe
source_candle_close_utc
feature_set_hash
features_json
created_at_utc
```

The snapshot is linked from a signal so a historical signal can be reconstructed without recomputing from mutable configuration.

### 2.3 `signals`

A deterministic statement that the strategy detected a setup.

```text
signal_id              PK
strategy_id
strategy_version
parameter_set_id
parameter_set_hash
symbol
direction
setup_type
regime
source_timeframe
source_candle_close_utc
detected_at_utc
feature_snapshot_id
trade_plan_id          NULL
status
expires_at_utc
invalidated_at_utc     NULL
created_at_utc
```

`signal_id` is deterministic and unique.

### 2.4 `trade_plans`

The executable interpretation of one signal.

```text
trade_plan_id          PK
signal_id              FK
trade_plan_version
entry_model
entry_min_price
entry_max_price
stop_loss_price
take_profit_json
invalidation_rule_json
expiry_utc
expected_rr_json
risk_rate
risk_budget
suggested_quantity
quantity_before_rounding
quantity_after_rounding
quantization_decision
constraint_snapshot_json
constraint_snapshot_hash
working_type
margin_type
leverage
equity_used
plan_hash
status
created_at_utc
```

The fields `constraint_snapshot_json` through `equity_used` are the persisted per-plan record of the exchange constraint snapshot and execution assumptions (`RISK_MANAGEMENT.md` section 12, D035, D037). They are a Phase 17 target; state-transition validation is a separate requirement recorded by the decision-alignment bookkeeping.

A signal may have zero or one active trade plan in V1. Future versions may allow plan revisions with immutable versioning.

### 2.5 `approvals`

Human interaction with a trade plan.

```text
approval_id           PK
trade_plan_id         FK
signal_id             FK
action
approval_token_hash
requested_at_utc
acted_at_utc           NULL
actor_id
telegram_message_id    NULL
request_hash
result
```

Repeated callback delivery must resolve to the existing approval/result rather than create a new approval or order.

### 2.6 `trades`

**V1 status: not built (D045).** User-executed attribution derives from approvals, orders, fills, positions and journal events; the field list below is a design record.

Logical user-executed trade instance. This is distinct from the plan that proposed it and the exchange position that represents current exposure.

```text
trade_id              PK
trade_plan_id         FK
approval_id            FK
direction
symbol
risk_budget
status
opened_at_utc NULL
closed_at_utc NULL
gross_pnl
commission
funding
slippage
net_pnl
realized_R
```

V1 normally maps one approved trade to one resulting position, but the separate entity keeps analytics independent from exchange position mechanics.

### 2.7 `orders`

One row per exchange order intent/submission known to the system.

```text
order_id              PK
trade_plan_id         FK NULL
position_id            FK NULL
parent_order_id        FK NULL
order_role             ENTRY / STOP / TP / CANCEL_REPLACE / OTHER
exchange
symbol
side
position_side
order_type
time_in_force
quantity
price
stop_price
close_position
reduce_only
client_order_id        NULL
exchange_order_id      NULL
algo_client_id         NULL
exchange_status
local_status
submitted_at_utc
updated_at_utc
canceled_at_utc        NULL
```

`client_order_id`, `exchange_order_id`, and conditional/algo identifiers must be independently stored because Binance may use different identifiers for normal and algo orders.

### 2.8 `fills`

One row per execution/fill event.

```text
fill_id                PK
order_id               FK
exchange_trade_id
symbol
side
position_side
fill_price
fill_quantity
quote_quantity
commission
commission_asset
realized_pnl
fill_time_utc
is_maker
```

Unique key where available:

```text
(order_id, exchange_trade_id)
```

### 2.9 `positions`

Internal representation reconciled from Binance.

```text
position_id             PK
symbol
position_side
mode
quantity
entry_price
break_even_price
unrealized_pnl
realized_pnl
opened_at_utc
updated_at_utc
closed_at_utc NULL
status
```

The exchange remains authoritative for the live position state.

### 2.10 `journal_events`

Append-only operational/audit events.

```text
journal_event_id        PK
occurred_at_utc
event_type
entity_type
entity_id
correlation_id
signal_id NULL
trade_plan_id NULL
approval_id NULL
order_id NULL
position_id NULL
payload_json
created_at_utc
```

Do not use the event table as a substitute for current-state tables.

### 2.11 `symbol_metadata`

Versioned exchange metadata.

```text
symbol
status
contract_type
onboard_time_utc
base_asset
quote_asset
margin_asset
price_tick_size
quantity_step_size
min_quantity
max_quantity
notional_constraints_json
order_capabilities_json
metadata_observed_at_utc
```

Do not hard-code current symbol filters into strategy code.

### 2.12 `experiment_runs`

**V1 status: not built (D045).** Experiment identity is the six-field tuple in file-based experiment records (protocol section 5); the field list below is a design record.

Backtest/research reproducibility.

```text
experiment_id          PK
strategy_version
parameter_set_id
parameter_set_hash
data_snapshot_id
code_version
cost_model_hash
time_range_start_utc
time_range_end_utc
universe_hash
run_type
created_at_utc
result_summary_json
```

## 3. Canonical state machines

Canonical states are defined in `GLOSSARY.md`.

Domain separation is mandatory:

```text
SignalStatus       ≠ OrderStatus ≠ PositionStatus ≠ ApprovalAction
```

A signal reaching `APPROVED` must never imply that an order was accepted by Binance. Signal-level approval and plan-level approval are separate: `SignalStatus.APPROVED` records user approval observed on the signal instance, `TradePlanStatus.APPROVED` authorizes execution handoff, and order placement reads the plan status. (D028)

## 4. Relationships

```text
FeatureSnapshot 1 ── N Signal
Signal          1 ── 0..1 TradePlan
TradePlan       1 ── N ApprovalAttempt
TradePlan       1 ── 0..1 Trade
Trade           1 ── N Order
Order           1 ── N Fill
Trade           0..1 ── 1 Position
All entities     1 ── N JournalEvent
```

## 5. Integrity rules

- All timestamps are UTC.
- Monetary/price/quantity values must use decimal-safe numeric types; do not use binary floating point for persisted financial calculations.
- State transitions must be validated in application code.
- Foreign keys must prevent orphan domain rows except where an explicit `NULL` lifecycle is documented.
- Unique constraints must protect deterministic IDs and exchange event replay.
- Audit/journal events are append-only.

## 6. Reporting joins

System-performance reporting joins from `Signal → TradePlan → simulated outcome`.

User-performance reporting joins from `Signal → Approval → Order → Fill → Position`.

Opportunity reporting joins skipped/expired signals to a hypothetical outcome produced by the same strategy/execution assumptions.
