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

The fields `constraint_snapshot_json` through `equity_used` are the persisted per-plan record of the exchange constraint snapshot and execution assumptions (`RISK_MANAGEMENT.md` section 12, D035, D037). Phase 17 (D051) persists that record in its own write-once table, `plan_constraint_snapshots` (section 2.15), keyed by `trade_plan_id`, instead of as columns of `trade_plans`, so the plan row and its `plan_hash` do not move; `trade_plans` carries no `constraint_snapshot_*`, `working_type`, `margin_type`, `leverage` or `equity_used` column. State-transition validation (DOMN-04) is implemented in `src/domain/transitions.py` and enforced in the same transaction as each write (section 5).

The stored plan Decimals (`entry_min_price`, `entry_max_price`, `stop_loss_price`, the take-profit prices inside `take_profit_json`, `risk_rate`, `risk_budget`, `suggested_quantity`, `quantity_before_rounding`, `quantity_after_rounding`) are quantized by the planner to 18 fractional digits with `ROUND_HALF_EVEN` before the plan JSON is built and before `plan_hash` is computed, so a plan read back from `NUMERIC(38,18)` recomputes the same `plan_hash` (D-12, D051). The repository refuses any Decimal that carries more than 18 fractional digits (`PrecisionError`) instead of letting PostgreSQL round it.

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
status
consumption_status     UNCONSUMED / CONSUMED
consumed_at_utc        NULL
approved_quantity      NULL
```

Repeated callback delivery must resolve to the existing approval/result rather than create a new approval or order.

Phase 17 (D051) added the two consumption columns. `consumption_status` is an explicit NOT NULL value (default `UNCONSUMED`), never inferred from the nullable `consumed_at_utc`; a CHECK (`ck_approvals_consumption_coherent`) ties them together (`CONSUMED` requires `consumed_at_utc` and `status = APPROVED`, `UNCONSUMED` requires no timestamp). An approval is consumed only immediately before the entry order is placed, in the same transaction that inserts the ENTRY row of `execution_intents` (section 2.14); a NO_TRADE decided before placement leaves the approval unconsumed and retryable until the plan expires. Uniqueness is enforced by the database: `approval_token_hash` is unique (`uq_approvals_token_hash`), and at most one decided approval can exist per trade plan (partial unique index `uq_approvals_one_decided_per_plan` where `status <> 'PENDING'`), so several PENDING rows may coexist but a second decision cannot land. A decision is a conditional `UPDATE ... WHERE status = 'PENDING'`; a lost race returns the stored approval.

Phase 19 review-fix batch 4 (D078, 19-REVIEW WR-01) added `approved_quantity` (NUMERIC(38,18), Alembic revision `0006_approval_quantity`) with the CHECK `ck_approvals_approved_quantity` (NULL or above zero). It is the quantity of the plan the approval request was issued for (`trade_plans.quantity_after_rounding`, the figure the APPROVE message and the SHADOW confirmation card show, D078 item (6)), written once with the PENDING row and never changed by a decision. The plan hash does not cover it (D051); live binding requires the plan's quantity to equal it and refuses a NULL, which marks a row written before revision 0006 (`APPROVED_QUANTITY_MISSING`). The consume transaction re-reads it under `FOR UPDATE` (D078 (6)): a NULL, a value unequal to the bound quantity or one below the quantity to place rolls the consume back (`APPROVED_QUANTITY_NOT_CONFIRMED`).

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

Phase 17 (D051): `client_order_id` and `algo_client_id` are each unique where not NULL (partial unique indexes `uq_orders_client_order_id` and `uq_orders_algo_client_id`). `quantity` is `>= 0` (a `closePosition` stop-loss leg has no quantity and is stored as 0), `price` and `stop_price` are NULL or `> 0`, and `local_status` is limited to the `OrderStatus` values by a named CHECK. `order_role` is a free string and has no CHECK.

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

`positions.quantity` is a signed amount (negative for a short in one-way mode, as `positionAmt` is on Binance), so it has NO sign CHECK; a `>= 0` CHECK would reject a legal short (Phase 17, D051).

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

Phase 17 (D051): the table is append-only in PostgreSQL (row-level triggers refuse UPDATE and DELETE, a statement-level trigger refuses TRUNCATE). `journal_event_id` is deterministic and collision-free: it is a pure function of the event content (`content_hash_event_id`) or, for correlated flows such as a Telegram callback, of the correlation id, event type, entity id and a fixed step label (`correlated_event_id`), with no clock suffix and no randomness. Replaying an event therefore writes the same id, and the store treats an identical replay as a no-op and a different event under an existing id as a conflict. The five reference columns (`signal_id`, `trade_plan_id`, `approval_id`, `order_id`, `position_id`) are foreign keys with `ON DELETE RESTRICT`, so a writer must insert the parent row first, inside the same unit of work.

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

**V1 status: not built (D045).** Experiment identity is the seven-field tuple in file-based experiment records (protocol section 5); the field list below is a design record.

Backtest/research reproducibility.

```text
experiment_id          PK
strategy_version
parameter_set_id
parameter_set_hash
data_snapshot_id
data_manifest_hash
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

Collect list versus research universe (D-01, D-02, D-06 to D-09). The collect list (`docs/research/universe/collect-list-v1.toml` issued 2026-09-30, re-issued after the freeze as `docs/research/universe/collect-list-v2.toml` with the still-TRADING frozen symbols added, D-24; schema `collect-list/1`) is an operational input naming the symbols the OI and funding collector polls: the live-5 union the top 15 TRADING USDT perpetuals by 24h quote volume on the day it was chosen (2026-09-30). It has no FROZEN state and no content hash, and a later version supersedes it without touching stored data. The research universe is the separate manifest `docs/research/universe/research-universe-v1.toml`, a point-in-time selection by trailing 30-day quote volume at the dataset start that becomes FROZEN with a content hash and a second witness in the decision-alignment gate. The reviewable evidence for that selection is the freeze report `docs/research/universe/research-universe-v1.freeze-report.json` (schema `research-universe-freeze-report/1`): dates, per-candidate status, contract type, onboard time, `deliveryDate`, source, days, volume sum, eligibility and reason, the ranking, unrankable symbols, trade and mark availability for each proposed symbol, and `proposal_sha256` computed over every other report field. The report sits outside the hashed manifest payload; `freeze` accepts it only when the operator passes that hash as `--approve`.

Sufficiency report (D-04, D-05, D-21): `python -m src.data.backfill_cli --report-out <path>` writes canonical JSON (sorted keys, LF, UTF-8, atomic; byte-identical on an identical re-run) with schema `data-sufficiency-report/1` and the keys `run_date`, `depth_months`, `dataset_start`, `dataset_end`, `rows`, `split_coverage`, `trade_floor_note`, `depth_extension_note` and `missing_data`. Each row is one (dataset, symbol, interval) with `source` (REST or ARCHIVE), the expected window, `expected_bars`, `have_bars`, `missing_bars`, a `cause` (`OK`, `ONBOARD_LIMITED`, `DELISTED_CAPPED`, `NO_WINDOW`, `NOT_BACKFILLED`, `GAP`, `UNAVAILABLE`), `gaps` and `flat_tail`; `missing_data` is true only for `NOT_BACKFILLED`, `GAP` or `UNAVAILABLE`. Funding history has its own rows (dataset `funding`, interval `funding`, D-23) built from the stored sweep files: no constant funding interval is assumed (a symbol may move from 8h to 4h), a series is `GAP` when the first tick is later than 8h plus 60 s after the window start, the last tick is earlier than 8h plus 60 s before the window end (the delivery for a delivered contract), or two consecutive unique ticks are further apart than 8h plus 60 s, and an empty series is `NOT_BACKFILLED`; `have_bars` counts unique ticks and `expected_bars` adds the ticks implied by each hole. `--no-funding` produces no funding rows. `split_coverage` gives the 1m coverage of each protocol split block (40 percent Development, four 10 percent Validation folds, 20 percent holdout of the 1h/4h timeline). The report checks data depth only: the D043 trade floor (at least 100 closed trades pooled over the four Validation folds and at least 30 per fold) cannot be measured before the Phase 14 causal simulator exists, so the report states that and estimates no trade count. It never lowers the floor and it does not edit `RESEARCH_PROTOCOL.md`; extending 1m history from 12 to 24 months was a user decision taken after reading the report (D-21); the user chose 24 months on 2026-10-03.

### 2.14 `execution_intents`

Write-ahead record of every order the system intends to send, one row per approval and role (Phase 17, D-13, D-14, D051). It is what makes a replayed approval or a restart unable to place a second entry: the exchange cannot be relied on to deduplicate (`EXECUTION_SPEC.md` section 7).

```text
approval_id            FK approvals, part of PK
role                   part of PK: ENTRY / STOP_LOSS / TAKE_PROFIT_1 / TAKE_PROFIT_2
trade_plan_id          FK trade_plans
plan_hash
client_order_id        NULL (ENTRY rows only, deterministic)
algo_client_id         NULL (non-ENTRY rows only, deterministic)
symbol
side
intended_quantity      NULL (a closePosition leg has none)
intended_price         NULL
intent_status          INTENDED / SENT / ACKED / REJECTED / UNKNOWN
exchange_order_id      NULL
exchange_status        NULL
outcome_recorded       BOOLEAN NOT NULL DEFAULT false
outcome_is_no_trade    NULL
outcome_reason_code    NULL
resolution_reason_code NULL: RECONCILED_ABSENT / NEVER_SENT (Phase 20, revision 0007)
intended_at_utc
sent_at_utc            NULL
resolved_at_utc        NULL
updated_at_utc
```

- Keys and constraints: primary key `pk_execution_intents (approval_id, role)`; `uq_execution_intents_plan_role (trade_plan_id, role)` so a second approval of the same plan cannot take another entry; partial unique indexes on `client_order_id` and `algo_client_id` where not NULL; foreign keys `ON DELETE RESTRICT` to `approvals` and `trade_plans`; named CHECKs for the role set, the status set (`ExecutionIntentStatus`, GLOSSARY section 12.1), the client id by role (an ENTRY row has `client_order_id` and no algo id, every other role the reverse), quantity and price (`NULL` or `> 0`) and the outcome columns (`outcome_recorded` is true exactly when the reason code and flag are set, and only for ENTRY).
- Status: `ACKED` and `REJECTED` are terminal (trigger `trg_execution_intents_terminal_status`); every other status change goes through `src/domain/transitions.py` (kind `EXECUTION_INTENT`) after a `FOR UPDATE` read. The ENTRY row also stores the persisted `ExecutionOutcome` (`outcome_is_no_trade`, `outcome_reason_code`), so a replay returns the stored result with zero adapter calls; an ENTRY row without a recorded outcome replays as `RECONCILIATION_REQUIRED`.
- Reconciliation reason (Phase 20, plan 20-03, Alembic revision `0007_intent_resolution_reason`): `resolution_reason_code` is nullable `VARCHAR(32)` with the named CHECK `ck_execution_intents_resolution_reason` (`NULL`, or `intent_status = 'REJECTED'` and the code is `RECONCILED_ABSENT` or `NEVER_SENT`). `RECONCILED_ABSENT` is `UNKNOWN` to `REJECTED` after the Phase 20 reconciliation protocol (plan 20-10) concluded that the exchange shows no such order; `NEVER_SENT` is `INTENDED` to `REJECTED`, nothing was sent because `mark_sent` commits before `place_entry`. It is written only by `finalize_reconciled_resolution` (which also writes `exchange_status` and `exchange_order_id` as NULL and sets `resolved_at_utc`), never by `record_result`; `exchange_status` keeps Binance's status only. A row closed by `record_result(REJECTED)` therefore has a NULL reason, so a definitive Binance rejection and a reconciled absence cannot be confused. The `outcome_*` columns cannot carry this reason: the manager already finalizes them on the ambiguous-entry path and they are written once. There is no backfill.
- Writers: `PgExecutionStateStore` (`consume_and_record_entry_intent`, `mark_sent`, `record_result`, `record_protective_intent`, `finalize_reconciled_resolution`, `finalize_entry_outcome`). Readers: `execute_approved_plan` (replay), restart recovery (`list_unresolved_intents`, `resolve_unresolved_intents`, Phase 17 code, wired in Phase 20 and 24), reconciliation (Phase 20) and the Telegram message (Phase 23 and 24, through `PgExecutionStateStore.get_entry`).

### 2.15 `plan_constraint_snapshots`

The exact exchange constraints used to size one trade plan (EXEC-04, D-18, D-19, D051). One row per `trade_plan_id`, written once.

```text
trade_plan_id               PK, FK trade_plans
symbol
working_type                MARK_PRICE only
margin_type                 text, 'UNKNOWN' until Phase 22
leverage                    text, 'UNKNOWN' until Phase 22
equity_used                 text, 'UNKNOWN' until Phase 21
live_inputs_status          COMPLETE / INCOMPLETE
constraints_observed_at_utc exchangeInfo capture time
captured_at_utc             time the snapshot was recorded
snapshot_json               TEXT, canonical JSON (sorted keys, Decimal as text, no float)
snapshot_sha256             64 lowercase hex
```

- `snapshot_json` holds the symbol filters (tick, step, minimum quantity, maximum quantity, minimum notional, `MARKET_LOT_SIZE`, `PERCENT_PRICE`) as Decimal text, the working type, margin type, leverage and equity; a filter the adapter did not supply is the explicit string `UNKNOWN`, never zero or an invented default. The digest is plan evidence and is NOT part of `plan_hash`, so the approval binding contract does not move.
- Constraints: foreign key `ON DELETE RESTRICT`, sha256 format CHECK, `live_inputs_status` set CHECK, `working_type IN ('MARK_PRICE')` (mirrors `WORKING_TYPE_VALUES`, D037; widen both together), and `COMPLETE` forbids any `UNKNOWN` live input. The table is append-only (trigger).
- Every snapshot written today is `INCOMPLETE` (margin type, leverage and equity arrive in Phases 21 and 22), and an `INCOMPLETE`, stale (age above `constraint_snapshot_ttl_seconds`) or future-dated snapshot is invalid for live placement. `PgPlanConstraintSnapshotStore` verifies the digest and every denormalized column on each read and fails closed on a mismatch.
- Readers: Phase 19 pre-placement checks (`is_valid_for_live`), Phases 21 and 22 (supply the live inputs).

### 2.16 `system_state_events`

Append-only log of durable system state, so SAFE_MODE, live enablement and the kill-gate state survive a restart (D-22, D051).

```text
state_event_id        PK, content hash
state_key             SAFE_MODE / LIVE_ENABLEMENT / KILL_GATE
state_version         integer >= 1, UNIQUE with state_key
state_json            TEXT, canonical JSON (str, bool or null values only)
journal_event_id      FK journal_events
recorded_at_utc
```

- Each row is written in the same transaction as its `SYSTEM_STATE_CHANGED` journal event (`journal_event_id`), so the audit trail and the current state cannot diverge. "Latest per key" is a query (`PgSystemStateStore.latest`), not a view. Constraints: unique `(state_key, state_version)`, key set CHECK, `state_version >= 1`, foreign key `ON DELETE RESTRICT`; append-only trigger.
- The controllers rebuild themselves from the latest document (`SafeModeController.rehydrate`, `LiveEnablementController.rehydrate`); malformed state raises instead of defaulting. Nothing writes these rows or reads them at startup yet: the SAFE_MODE wiring is Phase 20 and the enablement and kill-gate wiring is Phase 24.

### 2.17 `pending_protective_actions`

The durable INTENT of a protective action that the REST gate refused (Phase 20, plan 20-14, D-19, owner decision Q4 of 2026-10-20). When an HTTP 418 ban, an HTTP 429 pause or a gate that is not restored refuses a protective stop, an entry-remainder cancel or an emergency close, nothing reaches Binance. Before this table the refusal was only a journal row and the coordinator's in-memory retry, so a restart forgot it. A row here is the explicit record that the action was NOT sent. It is **intent only, never a payload**: there is no column for a trigger price, a quantity or a side, so an old request can never be replayed from it. When sending is allowed again the coordinator's ordinary step reads the current exchange state first and then decides from the plan. The table does not protect the position while the exchange forbids sending, and nothing in it claims that a position always has a stop under every rate-limit condition (the plan stays in its blocking state).

```text
pending_id             PK, content hash of plan_hash + kind + opening time (one id per episode)
plan_hash              VARCHAR(64)
trade_plan_id          VARCHAR(128)
approval_id            VARCHAR(128)
symbol                 VARCHAR(32)
pending_kind           STOP_NOT_SENT / PROTECTION_ENTRY_CANCEL_NOT_SENT / CLOSE_NOT_SENT
state                  PENDING / RESOLVED / SUPERSEDED
gate_reason            VARCHAR(64), fixed project text (IP_BAN_418, RATE_LIMIT_PAUSE_429, GATE_NOT_RESTORED, ...)
first_blocked_at_utc   TIMESTAMPTZ
last_blocked_at_utc    TIMESTAMPTZ, >= first_blocked_at_utc
block_count            INTEGER >= 1 (how many steps the gate refused the same action)
retry_after_until_utc  NULL, TIMESTAMPTZ (the gate's own end, when it knew one)
resolved_at_utc        NULL while PENDING, set when RESOLVED or SUPERSEDED
resolution_note        NULL while PENDING, fixed project text when closed
```

- Alembic revision `0008_pending_protective_actions` (down revision `0007_intent_resolution_reason`). Named constraints: `pk_pending_protective_actions`, `ck_pending_protective_actions_kind`, `ck_pending_protective_actions_state`, `ck_pending_protective_actions_block_count`, `ck_pending_protective_actions_time_order`, `ck_pending_protective_actions_resolution` (open means no resolution time and no note, closed means both). The partial unique index `uq_pending_protective_actions_open` on `(plan_hash, pending_kind) WHERE state = 'PENDING'` allows at most one open row per plan and kind; a refusal of the same action bumps that row, and a block after a resolution opens a new row. There are no foreign keys: the table is an intent log keyed by the plan hash.
- States: `PENDING` is open. `RESOLVED` means the action got through or became moot because the exchange state settled (the stop was read ACTIVE by its deterministic id, the entry cancel was accepted or the entry is terminal, the close was sent after the gate opened or the position is flat). `SUPERSEDED` means policy now requires a close (`CLOSE_REQUIRED`, `CLOSE_FAILED` or `FLAT`), so a queued stop is never sent (note `CLOSE_REQUIRED_BY_POLICY`). `max_unprotected_ms` running out during the wait moves the plan to `CLOSE_REQUIRED` through the existing deadline.
- Writers: the protection coordinator (`src/execution/protection.py`: stop and entry-cancel refusals, resolution and supersede) and the emergency closer (`src/execution/emergency_close.py`: `CLOSE_NOT_SENT`), both through `PgPendingActionStore` (`src/persistence/pending_actions.py`). The intent is first written to the local spill (D-16) and then recorded; a store failure enters SAFE_MODE `DB_FAILURE` once and never blocks the protective step. Readers: the coordinator's `blocks_new_entries()` (true while any row is `PENDING`, and true when the store cannot be read), the startup load of open rows (plan 20-19) and the queue order once the gate opens (plan 20-21, D-20). A 418 or 429 pause is never bypassed: the refusal is recorded, not worked around (D-18).

### 2.18 `validated_lot_filters`

The last validated exchangeInfo lot filters of each symbol (Phase 20, plan 20-18, D-21, owner decision Q3 of 2026-10-20, option b). The emergency close sizes its reduce-only MARKET parts from the symbol's lot filters. When exchangeInfo cannot be read at that moment (a timeout or a 5xx), the closer MAY use the stored filters, flagged stale with their fetch time. A new entry NEVER may. One row per symbol, replaced by a newer successful read; every value is a filter the exchange returned and `LotFilters` validated, so the table holds no default and no invented number.

```text
symbol                   PK, VARCHAR(32)
price_tick_size          NUMERIC(38,18), > 0
lot_min_quantity         NUMERIC(38,18), > 0, <= lot_max_quantity
lot_max_quantity         NUMERIC(38,18), > 0
lot_step_size            NUMERIC(38,18), > 0
market_lot_min_quantity  NUMERIC(38,18), > 0, <= market_lot_max_quantity
market_lot_max_quantity  NUMERIC(38,18), > 0
market_lot_step_size     NUMERIC(38,18), > 0
min_notional             NUMERIC(38,18), > 0
fetched_at_utc           TIMESTAMPTZ, when the exchange last answered with these values
updated_at_utc           TIMESTAMPTZ, when the row was written, >= fetched_at_utc
```

- Alembic revision `0009_validated_lot_filters` (down revision `0008_pending_protective_actions`). Named constraints: `pk_validated_lot_filters`, `ck_validated_lot_filters_symbol`, one `ck_validated_lot_filters_<column>_positive` per value column, `ck_validated_lot_filters_lot_range`, `ck_validated_lot_filters_market_lot_range`, `ck_validated_lot_filters_time_order`. No foreign keys; no backfill.
- Single writer: `LotFilterSource` (`src/execution/lot_filter_source.py`) through `PgLotFilterStore` (`src/persistence/lot_filters.py`), on a successful live read and on the periodic refresh (`reconcile.lot_filter_refresh_interval_ms`; the reconcile tick that calls `refresh_if_due` is plan 20-21). `upsert` keeps the newest fetch: an older `fetched_at_utc` never replaces a newer row.
- Use: only the emergency close reads a stored row, through `LotFilterSource.for_emergency_close` (called from `src/execution/emergency_close.py` and nowhere else; an AST test pins it). The row is returned with `filters_stale = true` and its fetch time, and the closer journals both on its `EMERGENCY_CLOSE` rows. `for_entry` reads the exchange live and never returns a stored row. With no live read, no stored row and no complete plan snapshot nothing is guessed: the close fails closed as `LOT_FILTERS_UNAVAILABLE`.
- Tier 2: when no row exists, the persisted `plan_constraint_snapshots` row of the plan (section 2.15) is used, flagged stale, only when its maximum quantity and all three MARKET_LOT_SIZE values are present. It is never "the last validated filters".
- The close quantity is floored onto the filters (never rounded up to reach the minimum quantity). A close rejected with a lot-filter code is not resent with the same quantity; the next attempt takes a new attempt number and reads live filters again when it can. Binance accepting a close sized on stale filters is `[NOT_TESTED]` (best effort, Q3).

## 3. Canonical state machines

Canonical states are defined in `GLOSSARY.md`. The legal transitions between them are `GLOSSARY.md` section 11 (six tables: Signal, TradePlan, Order, Position, Approval, ExecutionIntent) and are implemented once in `src/domain/transitions.py`; the Phase 17 persistence status values (`ExecutionIntentStatus`, approval `consumption_status`, `live_inputs_status`, `SystemStateKey`) are `GLOSSARY.md` section 12. The section 11 tables are an auto-mode default awaiting user confirmation (D051).

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
- State transitions must be validated in application code. Phase 17 does this inside the write transaction: the repository reads the row `FOR UPDATE`, treats an unchanged status as an idempotent no-op, calls `assert_transition` (typed `IllegalTransition`, never swallowed into a silent save) and then applies a conditional `UPDATE ... WHERE status = <old>`. PostgreSQL adds a second line of defence for terminal states: `trg_<table>_terminal_status` on `signals`, `trade_plans`, `orders`, `positions`, `approvals` and `execution_intents` refuses any change of the status column once it holds a terminal value (the terminal sets equal `TERMINAL_STATES` in `src/domain/transitions.py`, proven by an exhaustive parity test).
- Foreign keys must prevent orphan domain rows except where an explicit `NULL` lifecycle is documented. All of them are `ON DELETE RESTRICT` (nothing is ever cascade-deleted from an audit table); `short_id_mapping` deliberately has no foreign key because it must survive a plan supersede.
- Unique constraints must protect deterministic IDs and exchange event replay: `approvals.approval_token_hash`, one decided approval per plan, `orders.client_order_id` and `orders.algo_client_id` (where not NULL), `(order_id, exchange_trade_id)` on fills, `(approval_id, role)` and `(trade_plan_id, role)` on `execution_intents`, `(state_key, state_version)` on `system_state_events`.
- Every status or enum-valued column carries a named CHECK whose literals are copied from `src/domain/enums.py`; a test inserts every enum member into its column and a parity test fails when an enum gains a member without a CHECK update. Price and quantity CHECKs: plan prices, `risk_rate`, `risk_budget` and fill price and quantity are `> 0`; `orders.quantity`, `fills.commission` and `trade_plans` quantities are `>= 0`; optional prices are NULL or `> 0`; `positions.quantity` is signed and has no sign CHECK.
- Status columns are `VARCHAR(32)` (`signals.status`, `trade_plans.status`, `orders.local_status`, `positions.status`, `symbol_metadata.contract_type`, `symbol_metadata.status`), so no real enum value (for example `TRADIFI_PERPETUAL`, `TRADING_CANCEL_ONLY`, `LIQUIDATION_REPORTED`) can be truncated.
- Every connection pins the session `TimeZone` to UTC (`options=-c timezone=UTC`, also for the async engine), so a database whose default zone is not UTC cannot leak local offsets into the domain objects, which reject non-UTC datetimes.
- Audit and journal events are append-only: `journal_events`, `system_state_events` and `plan_constraint_snapshots` refuse UPDATE, DELETE and TRUNCATE by trigger. The table owner can still disable a trigger; separating the owner role from the application role is deferred to Phase 26.
- Plan Decimals are stored at `NUMERIC(38,18)`: the planner quantizes with `ROUND_HALF_EVEN` to 18 fractional digits before hashing and the repository raises `PrecisionError` for a value that PostgreSQL would round, so a stored plan recomputes its `plan_hash`.
- Journal ids are deterministic (content hash or correlated id, no clock and no randomness), so replay writes the same id and the primary key makes the write idempotent.
- The schema is built only by Alembic migrations (`0004_persistence_integrity` is the Phase 17 revision); a test compares a database built by `alembic upgrade head` with the ORM metadata (`compare_metadata`, plus catalog checks for partial-index predicates, CHECK literals and triggers), and the chain is proven reversible (upgrade, downgrade, upgrade) and data-safe (a 0003 database with rows upgrades to 0004). The PostgreSQL-only objects are declared on the ORM tables with `ddl_if(dialect="postgresql")`, so SQLite `create_all` suites keep their pre-0004 DDL.

## 6. Reporting joins

System-performance reporting joins from `Signal → TradePlan → simulated outcome`.

User-performance reporting joins from `Signal → Approval → Order → Fill → Position`.

Opportunity reporting joins skipped/expired signals to a hypothetical outcome produced by the same strategy/execution assumptions.
