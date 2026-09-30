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

### 2.13 Research Parquet datasets

**V1 status: built in Phase 13 as immutable Parquet files under the raw root (`data/raw`), not as PostgreSQL tables (D049).** All timestamps are UTC (`Datetime` in milliseconds, time zone UTC); prices, quantities and rates are `Decimal`, never binary floating point; a published file is never rewritten. Exchange facts behind the layouts are in `SOURCES.md` ("Facts verified for Phase 13") and `integration/BINANCE.md` section 13.

Trade candles, one file per symbol, interval and closed UTC day:

```text
data/raw/interval=<TF>/symbol=<SYMBOL>/date=<YYYY-MM-DD>/part.parquet
columns: open_time_utc, close_time_utc, open, high, low, close (Decimal scale 8),
         volume, quote_volume (Decimal scale 8), trade_count (Int64), interval, symbol
```

Mark-price klines are a separate dataset with the same partition shape under their own root, so the trade view (`candles_v1`, glob `interval=*/symbol=*/date=*/part.parquet`) never sees them and the existing backup root covers them (D-11, D-27):

```text
data/raw/dataset=mark_klines/interval=<TF>/symbol=<SYMBOL>/date=<YYYY-MM-DD>/part.parquet
columns: open_time_utc, close_time_utc, open, high, low, close (Decimal scale 8),
         price_tick_count (Int64), interval, symbol
```

The mark dataset has no volume, quote-volume or trade-count column (D-29): Binance returns `"0"` for the volume fields of a mark-price kline and the count field is a price-update count, stored as `price_tick_count`. It is a trigger series for the Phase 14 simulator (D037, D-12); Phase 13 does not consume it in any strategy or decision.

Funding and open-interest ticks, one file per observation, written by the collector and the funding-history backfill:

```text
data/raw/data_class=funding/symbol=<SYMBOL>/date=<YYYY-MM-DD>/sweep-<iso>.parquet
columns: symbol, funding_time_utc, funding_rate (Decimal scale 10), mark_price (Decimal scale 8, null for old rows)
data/raw/data_class=oi/symbol=<SYMBOL>/date=<YYYY-MM-DD>/tick-<iso>.parquet
columns: symbol, observed_at_utc, open_interest (Decimal scale 8), source
data/raw/data_class=oi_research/...  (same shape as oi)
```

Publication rules: a candle day file is published only for a whole closed UTC day (or the terminal day of a delivered contract), through a temporary file and an atomic replace, and an existing file is never overwritten (`DATA_PIPELINE.md` section 15). A dataset that is written again from a different source or a different library version has different bytes and is therefore a new dataset, never an edit of the old one.

Dataset identity (D-18): `dataset_id` is the canonical-JSON sha256 of `{"files": [{"path": <posix path relative to the raw root>, "sha256": <sha256 of the file bytes>}, ...]}` sorted by path, computed over exactly the day files a run reads (never a store-wide glob). It is a 64-hex string, independent of file order and of the operating system, and is carried as `ExperimentRecord.data_snapshot_id` so a research result names the exact bytes it was computed from (`src/data/case_input.py`, `dataset_identity`).

Collect list versus research universe (D-01, D-02, D-06 to D-09). The collect list `docs/research/universe/collect-list-v1.toml` (schema `collect-list/1`) is an operational input naming the symbols the OI and funding collector polls: the live-5 union the top 15 TRADING USDT perpetuals by 24h quote volume on the day it was chosen (2026-09-30). It has no FROZEN state and no content hash, and a later version supersedes it without touching stored data. The research universe is the separate manifest `docs/research/universe/research-universe-v1.toml`, a point-in-time selection by trailing 30-day quote volume at the dataset start that becomes FROZEN with a content hash and a second witness in the decision-alignment gate. The reviewable evidence for that selection is the freeze report `docs/research/universe/research-universe-v1.freeze-report.json` (schema `research-universe-freeze-report/1`): dates, per-candidate status, contract type, onboard time, `deliveryDate`, source, days, volume sum, eligibility and reason, the ranking, unrankable symbols, trade and mark availability for each proposed symbol, and `proposal_sha256` computed over every other report field. The report sits outside the hashed manifest payload; `freeze` accepts it only when the operator passes that hash as `--approve`.

Sufficiency report (D-04, D-05, D-21): `python -m src.data.backfill_cli --report-out <path>` writes canonical JSON (sorted keys, LF, UTF-8, atomic; byte-identical on an identical re-run) with schema `data-sufficiency-report/1` and the keys `run_date`, `depth_months`, `dataset_start`, `dataset_end`, `rows`, `split_coverage`, `trade_floor_note`, `depth_extension_note` and `missing_data`. Each row is one (dataset, symbol, interval) with `source` (REST or ARCHIVE), the expected window, `expected_bars`, `have_bars`, `missing_bars`, a `cause` (`OK`, `ONBOARD_LIMITED`, `DELISTED_CAPPED`, `NO_WINDOW`, `NOT_BACKFILLED`, `GAP`, `UNAVAILABLE`), `gaps` and `flat_tail`; `missing_data` is true only for `NOT_BACKFILLED`, `GAP` or `UNAVAILABLE`. `split_coverage` gives the 1m coverage of each protocol split block (40 percent Development, four 10 percent Validation folds, 20 percent holdout of the 1h/4h timeline). The report checks data depth only: the D043 trade floor (at least 100 closed trades pooled over the four Validation folds and at least 30 per fold) cannot be measured before the Phase 14 causal simulator exists, so the report states that and estimates no trade count. It never lowers the floor and it does not edit `RESEARCH_PROTOCOL.md`; extending 1m history from 12 to 24 months is a user decision taken after reading the report (D-21).

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
