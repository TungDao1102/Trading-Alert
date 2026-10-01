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

### 2.1 Signal/Plan APPROVED ownership (D028)

`SignalStatus.APPROVED` records that the user approved the signal instance. `TradePlanStatus.APPROVED` is a separate value that records the plan has been authorized for execution handoff. Order placement reads the `TradePlan` status, never the `Signal` status directly. The transition order is: Signal APPROVED → TradePlan APPROVED → Order PLANNED. Authority: D007 (signal/plan/order separation) and D016 (canonical terminology). (D028)

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

### 8.1 Canonical DailyState (Phase 5, D-03)

```text
NORMAL
WARNING
DAILY_STOP
```

`NORMAL` — daily loss below the warning threshold; new entries permitted.
`WARNING` — warning threshold reached but stop threshold not yet; new entries still permitted (alert fires).
`DAILY_STOP` — stop threshold reached; no new entries, existing protective exits remain active.

### 8.2 Canonical KillGateState (Phase 10, D-03)

```text
WITHIN_BUDGET
PASSING_CANDIDATE
INSUFFICIENT_EDGE
```

`WITHIN_BUDGET` — fewer than three independently specified families tested, or fewer than six calendar months elapsed since the protocol freeze; keep researching.
`PASSING_CANDIDATE` — a family holds a recorded passing decision; evidence exists; does not authorize live trading.
`INSUFFICIENT_EDGE` — terminal: at least three families tested, at least six months elapsed, and none passing (D013, D030). A valid outcome; keeps live disabled, blocks new strategy-family registration and never clears itself.

## 9. Canonical rejection reasons

This section is the source of truth for rejection reason codes (D016, D031, audit F-110). One canonical code per concept: the 17 codes that production code referenced before Phase 12 (`RejectionReason.X` in `src/`, derived by scan, gate GL-02), the reserved `INSUFFICIENT_MARGIN`, and the two Phase 12 cost-guard codes `STOP_TOO_TIGHT` and `COST_TO_RISK_EXCEEDED` (D046). The block in 9.1 equals the `RejectionReason` enum (20 members, gate GL-03). The five synonyms that used to exist as members are retired and recorded in 9.2.

### 9.1 Canonical codes

```text
NO_TRADE_REGIME
RR_TOO_LOW
STALE_SETUP
INVALIDATED
EXCHANGE_CONSTRAINT
DATA_STALE
RECONCILIATION_REQUIRED
APPROVAL_EXPIRED
MIN_QTY_REJECT
NOTIONAL_REJECT
UTILIZATION_REJECT
CLUSTER_CAP_REJECT
AGGREGATE_CAP_REJECT
MAX_POSITIONS_REJECT
DAILY_STOP_BLOCK
STALE_CONSTRAINTS
UNCERTAIN_ACCOUNT_STATE
INSUFFICIENT_MARGIN
STOP_TOO_TIGHT
COST_TO_RISK_EXCEEDED
```

`INSUFFICIENT_MARGIN` is reserved: no code emits it yet; it is first emitted by the Phase 22 margin guard.

`STOP_TOO_TIGHT` means the stop distance divided by the sizing entry price is below the registry `min_stop_distance_rate`; `COST_TO_RISK_EXCEEDED` means the round-trip modeled cost divided by `risk_per_unit` is above the registry `max_cost_to_risk`. Both are emitted before quantization (D-07).

### 9.2 Retired aliases (removed in Phase 12)

These five names were removed from `RejectionReason` and from `tests/test_domain_enums.py` in Phase 12 (D-09, D044 follow-up 1). New code must use the replacement. The table records the removal only: it declares no enum member, and gates GL-01 and GL-03 fail if a retired name re-enters the enum or the 9.1 block. The 9.1 block equals the `RejectionReason` enum (20 members, gate GL-03).

| Removed name | Use instead | Removed in |
|--------------|-------------|------------|
| `QUANTIZATION_REJECT` | `MIN_QTY_REJECT` or `UTILIZATION_REJECT` | Phase 12 (D046) |
| `MIN_NOTIONAL_REJECT` | `NOTIONAL_REJECT` | Phase 12 (D046) |
| `RISK_LIMIT` | `AGGREGATE_CAP_REJECT` or `MAX_POSITIONS_REJECT` | Phase 12 (D046) |
| `CORRELATED_RISK_LIMIT` | `CLUSTER_CAP_REJECT` | Phase 12 (D046) |
| `DAILY_STOP` | `DAILY_STOP_BLOCK` when used as a rejection reason | Phase 12 (D046) |

`DAILY_STOP` remains a valid `DailyState` value (section 8.1); only its use as a rejection reason is retired.

### 9.3 Plain-string codes emitted outside RejectionReason

Production code also emits the following plain strings as `reason_code` values or outcome labels. They are not `RejectionReason` members. Status for the rejection-style codes: proposed canonical, promote to the enum in the owning phase (Phases 20, 24 and 26). Derived from `src/` by reading the emitting code; the list is not exhaustive for divergence kinds.

| Code | Emitted in | Meaning | Status |
|------|------------|---------|--------|
| `DISABLED` | `src/execution/enablement.py` (`_DISABLED`), `src/execution/manager.py` (fallback `reason_code`) | Live order enablement is off, no order placed | proposed canonical, promote in Phase 26 |
| `ENTRY_WITHOUT_PROTECTIVE` | `src/execution/manager.py`, `src/execution/fill_monitor.py`, `src/reconcile/compare.py`, `src/ops/health.py` | An entry fill exists without a protective order; also a reconciler divergence kind and a SAFE_MODE entry reason (9.4) | proposed canonical, promote in Phase 20 |
| `NO_FILL` | `src/execution/manager.py` (no-trade result reason) | Entry order produced no fill | proposed canonical, promote in Phase 24 |
| `HEALTH_CHECK_FAILED` | `src/ops/health.py` (result `reason_code`, paired with `OK` on pass) | A health check reported failure, so trading is blocked | proposed canonical, promote in Phase 24 |
| `EXPIRED` | `src/paper/journal.py` (paper journal outcome `reason_code`), `src/analytics/lifecycle.py` (`_EXPIRED_REASON`) | Signal or entry expired without a fill; this is a lifecycle outcome label, not a rejection reason (the rejection form is `APPROVAL_EXPIRED` or `STALE_SETUP`) | outcome label, not a rejection reason |
| `OK` | `src/core/types.py` (`REASON_OK`), `src/ops/health.py` | Feature output valid or health check passed | not a rejection reason |
| `WARMUP_INSUFFICIENT` | `src/core/types.py` (`REASON_WARMUP_INSUFFICIENT`) | Feature validity reason: not enough closed candles | feature validity string, not a rejection reason |
| `GAP_IN_SOURCE` | `src/core/types.py` (`REASON_GAP_IN_SOURCE`) | Feature validity reason: gap in the candle source | feature validity string, not a rejection reason |
| `INVALID_INPUT` | `src/core/types.py` (`REASON_INVALID_INPUT`) | Feature validity reason: invalid input | feature validity string, not a rejection reason |

### 9.4 SAFE_MODE entry reasons

Reason strings passed to `SafeModeController.enter_safe_mode(reason=...)` or recorded as the freeze halt reason. They describe why SAFE_MODE was entered, not why a plan was rejected.

| Reason | Emitted in |
|--------|------------|
| `ENTRY_WITHOUT_PROTECTIVE` | `src/execution/manager.py`, `src/ops/drills.py` |
| `ENTRY_STATE_UNKNOWN` | `src/execution/manager.py` |
| `ORPHAN_PROTECTIVE` | `src/ops/drills.py`, `src/reconcile/compare.py` (divergence kind) |
| `API_DEGRADATION` | `src/ops/drills.py` |
| `STALE_FEED` | `src/ops/drills.py` |
| `DB_FAILURE` | `src/ops/drills.py` |
| `MANUAL_CLOSE` | `src/execution/manager.py`, `src/ops/drills.py` |
| `REGISTRY_DIFF` | `src/paper/freeze.py` (halt reason on a parameter registry diff) |

Do not create synonyms such as `Skipped-User`, `USER_SKIPPED`, and `SKIPPED_USER` in different modules. Use the canonical enum names above.

## 10. Canonical ApprovalResult

```text
PENDING
APPROVED
SKIPPED
EXPIRED
```

`ApprovalAction` maps to `ApprovalResult` as implemented by `action_to_result` in `src/approval/binding.py`:

- `APPROVE` gives `APPROVED`.
- `SKIP_USER`, `SKIP_BUSY` and `CANCEL` give `SKIPPED`.
- `SIMULATE` gives `PENDING` (notify-only; it does not advance the approval state).

`EXPIRED` is not produced by any `ApprovalAction`; lifecycle analytics derive it from the `EXPIRED` outcome label (`src/analytics/lifecycle.py`). The value set PENDING, APPROVED, SKIPPED, EXPIRED was a Phase 3 planner assumption (D-10); it is recorded here as the enum source of truth pending user ratification.

## 11. State transitions

The legal-transition tables below are enforced by `src/domain/transitions.py` (`assert_transition`) inside the write transaction of the repositories, and the terminal rule (a terminal state has no successors) is also enforced by the database triggers of migration 0004. `tests/test_transitions.py` parses the text blocks in this section and compares them with the Python tables, so the two cannot drift apart. An unchanged state is not a transition: repositories treat an equal state as an idempotent no-op before calling `assert_transition`.

Status: Accepted as the Phase 17 auto-mode default; the user is to confirm these tables (decision D051). The GLOSSARY carried value sets only before this section; the tables are anchored on EXECUTION_SPEC section 3 (entry order lifecycle). Open point for the user: `APPROVED -> SUPERSEDED` for a TradePlan is illegal in this draft.

### 11.1 Signal transitions

```text
DETECTED -> NOTIFIED, SKIPPED_BUSY, EXPIRED, INVALIDATED
NOTIFIED -> VIEWED, APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED
VIEWED -> APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED
APPROVED -> (terminal)
SKIPPED_USER -> (terminal)
SKIPPED_BUSY -> (terminal)
EXPIRED -> (terminal)
INVALIDATED -> (terminal)
```

An expired or invalidated signal can never become `APPROVED`.

### 11.2 TradePlan transitions

```text
READY -> APPROVAL_PENDING, EXPIRED, INVALIDATED, SUPERSEDED
APPROVAL_PENDING -> APPROVED, EXPIRED, INVALIDATED, SUPERSEDED
APPROVED -> EXPIRED, INVALIDATED
EXPIRED -> (terminal)
INVALIDATED -> (terminal)
SUPERSEDED -> (terminal)
```

`APPROVED` is not terminal: an approved plan can still expire or be invalidated before execution handoff completes.

### 11.3 Order transitions

```text
PLANNED -> SUBMITTING, CANCELED
SUBMITTING -> NEW, REJECTED, UNKNOWN, CANCELED
NEW -> PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, UNKNOWN
PARTIALLY_FILLED -> FILLED, CANCELED, EXPIRED, UNKNOWN
UNKNOWN -> NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED
FILLED -> (terminal)
CANCELED -> (terminal)
EXPIRED -> (terminal)
REJECTED -> (terminal)
```

The moves out of `UNKNOWN` are reconciliation-only: they resolve the unknown state against the exchange (Binance is canonical) and no other code path may produce them.

### 11.4 Position transitions

```text
OPEN -> CLOSING, CLOSED, LIQUIDATION_REPORTED, UNKNOWN
CLOSING -> CLOSED, OPEN, UNKNOWN
LIQUIDATION_REPORTED -> CLOSED, UNKNOWN
UNKNOWN -> OPEN, CLOSING, CLOSED, LIQUIDATION_REPORTED
CLOSED -> (terminal)
```

The moves out of `UNKNOWN` are reconciliation-only, as for orders. A closed position never reopens: a new exposure is a new position.

### 11.5 Approval transitions

```text
PENDING -> APPROVED, SKIPPED, EXPIRED
APPROVED -> (terminal)
SKIPPED -> (terminal)
EXPIRED -> (terminal)
```

Approval states are the `ApprovalResult` values of section 10.

### 11.6 ExecutionIntent transitions

```text
INTENDED -> SENT, UNKNOWN, REJECTED
SENT -> ACKED, REJECTED, UNKNOWN
UNKNOWN -> ACKED, REJECTED
ACKED -> (terminal)
REJECTED -> (terminal)
```

Execution intent states are the values of section 12.1. An intent left `INTENDED`, `SENT` or `UNKNOWN` is unresolved and is resolved only by querying the exchange by its deterministic client id; it is never re-sent blindly.
