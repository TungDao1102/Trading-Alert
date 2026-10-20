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

Phase 15 planner meanings (D054, D-27): the planner reuses three existing codes for its geometry invariants, checked in this fixed order with the invariants before the RR gate. `STOP_TOO_TIGHT` also means the stop is not strictly outside the whole entry zone (a LONG stop at or above the lower edge of the zone, a SHORT stop at or below its upper edge), or the distance from the entry reference to the stop is closer than `min_stop_atr` x ATR when that key is present. `INVALIDATED` also means the signal bar has already traded through the planned stop (a LONG bar low at or below the stop, a SHORT bar high at or above it). `RR_TOO_LOW` also means TP1 is not on the profit side of the entry reference, which is checked before the `minimum_rr` threshold. No new member was added for these cases.

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
| `PLAN_SIGNAL_MISMATCH` | `src/execution/binding.py` | The persisted Signal is not the one the plan was built from, or its strategy version or parameter set differs from the approval's; nothing is placed | proposed canonical, promote in Phase 24 |
| `PLAN_SYMBOL_MISMATCH` | `src/execution/binding.py` | The plan constraint snapshot's plan id or symbol, or the caller's symbol, disagrees with the persisted Signal; the symbol is never taken from the caller | proposed canonical, promote in Phase 24 |
| `PLAN_SIDE_MISMATCH` | `src/execution/binding.py` | The direction of the Signal disagrees with the side implied by the hash-bound geometry (stop below the zone is LONG, above is SHORT) or with the caller | proposed canonical, promote in Phase 24 |
| `QUANTITY_ABOVE_APPROVED` | `src/execution/binding.py` | The placement quantity is above the approved quantity stored on the approval row (`approvals.approved_quantity`, D078), which the plan's `quantity_after_rounding` must equal; it is refused, never clipped or raised | proposed canonical, promote in Phase 24 |
| `PLAN_QUANTITY_MISMATCH` | `src/execution/binding.py` | The plan's `quantity_after_rounding` differs from the approved quantity stored on the approval row (D078); the quantity is not in the plan hash (D051), so it is compared here; nothing is placed and the approval is not consumed | proposed canonical, promote in Phase 24 |
| `APPROVED_QUANTITY_MISSING` | `src/execution/binding.py` | The approval row records no approved quantity (a row written before Alembic revision 0006, D078); nothing is placed and the approval is not consumed | proposed canonical, promote in Phase 24 |
| `GEOMETRY_INVALID_AFTER_SNAP` | `src/execution/binding.py` | After the entry limit and the stop trigger are snapped to the tick grid the stop is no longer strictly outside the entry zone | proposed canonical, promote in Phase 24 |
| `WORKING_TYPE_NOT_MARK_PRICE` | `src/execution/binding.py` | The plan constraint snapshot's working type is not `MARK_PRICE` (D037) | proposed canonical, promote in Phase 24 |
| `PLAN_STATUS_INVALID` | `src/execution/pre_placement.py` | `TradePlan.status` is EXPIRED, INVALIDATED or SUPERSEDED at placement time (an executed APPROVED plan is never refused by this check) | proposed canonical, promote in Phase 24 |
| `PLAN_INVALIDATED_BEFORE_PLACEMENT` | `src/execution/pre_placement.py` | The Signal carries an invalidation time or the latest closed strategy bar closed beyond the plan's invalidation level before the entry was placed; deliberately distinct from `RejectionReason.INVALIDATED` (planner geometry, D-08, G4-017) and not an alias of it | proposed canonical, promote in Phase 24 |
| `INVALIDATION_INPUT_UNAVAILABLE` | `src/execution/pre_placement.py` | The closed-bar close needed for the invalidation check was not provided, or the plan's invalidation rule cannot be read, so the plan is refused (fail closed) | proposed canonical, promote in Phase 24 |
| `VALIDITY_TOO_SHORT` | `src/execution/pre_placement.py` | The remaining validity, measured to the floored `goodTillDate` second, is below the owner minimum or the exchange GTD floor | proposed canonical, promote in Phase 24 |
| `LIMITS_NOT_CONFIGURED` | `src/execution/pre_placement.py` | At least one of the seven execution limits in `config/execution/execution-limits-v1.toml` is still `NOT_CONFIGURED`, so every live and Demo placement is refused | proposed canonical, promote in Phase 24 |
| `SYMBOL_HAS_POSITION` | `src/execution/pre_placement.py` | The exchange already reports a position on the plan's symbol | proposed canonical, promote in Phase 24 |
| `SYMBOL_HAS_OPEN_ORDER` | `src/execution/pre_placement.py` | The exchange already reports an open order on the plan's symbol | proposed canonical, promote in Phase 24 |
| `UNPROTECTED_POSITION_EXISTS` | `src/execution/pre_placement.py` | An account-wide flag says a position without a confirmed stop exists (a protection state that blocks new entries); checked before the same-symbol rules | proposed canonical, promote in Phase 20 |
| `SYMBOL_STATE_UNAVAILABLE` | `src/execution/pre_placement.py` | The exchange open-order state could not be read (fail closed) | proposed canonical, promote in Phase 24 |
| `MARK_PRICE_UNAVAILABLE` | `src/execution/pre_placement.py` | The mark price is missing, older than the owner maximum age or not valid for the check | proposed canonical, promote in Phase 24 |
| `MARK_PRICE_CROSSED_STOP` | `src/execution/pre_placement.py` | The mark price is already at or beyond the stop trigger on the losing side | proposed canonical, promote in Phase 24 |
| `MARK_PRICE_OUTSIDE_ZONE` | `src/execution/pre_placement.py` | The mark price has left the entry zone on the adverse side (LONG: strictly below the zone minimum; SHORT: strictly above the zone maximum), so the approved entry is no longer valid; a mark on the favorable side is allowed because the GTD LIMIT rests (owner decision, 19-REVIEW WR-06) | proposed canonical, promote in Phase 24 |
| `LAST_PRICE_UNAVAILABLE` | `src/execution/pre_placement.py` | The last traded price is missing, older than its own owner maximum age (`pre_placement.max_last_price_age_ms`), stamped too far in the future, zero, negative or not finite, so the last-price check cannot run (quick task 261020-l4p) | proposed canonical, promote in Phase 24 |
| `LAST_PRICE_CROSSED_STOP` | `src/execution/pre_placement.py` | The last traded price is already at or beyond the stop trigger on the losing side (quick task 261020-l4p) | proposed canonical, promote in Phase 24 |
| `LAST_PRICE_OUTSIDE_ZONE` | `src/execution/pre_placement.py` | The last traded price has left the entry zone on the adverse side (LONG: strictly below the zone minimum; SHORT: strictly above the zone maximum); the favorable side is allowed, the same rule as `MARK_PRICE_OUTSIDE_ZONE` (quick task 261020-l4p) | proposed canonical, promote in Phase 24 |
| `HEDGE_MODE_UNSUPPORTED` | `src/execution/pre_placement.py` | The account is in Hedge position mode; V1 places only One-way orders | proposed canonical, promote in Phase 24 |
| `ENTRY_REFUSED_BEFORE_SEND` | `src/execution/manager.py` | The entry was refused before anything reached the exchange (REST gate pause or ban, entries blocked by the clock-drift guard, missing signed-call policy); no probe, no SAFE_MODE | proposed canonical, promote in Phase 24 |
| `APPROVED_QUANTITY_NOT_CONFIRMED` | `src/execution/manager.py` | The approval row read inside the consume transaction does not confirm the quantity: its stored `approved_quantity` is NULL, differs from the quantity bound from the caller's approval, or is below the quantity about to be placed (D078 (6)); the transaction rolls back, the approval is not consumed and nothing is sent; the differing and below cases also enter SAFE_MODE `APPROVED_QUANTITY_INCONSISTENT`, a NULL (legacy row) does not | proposed canonical, promote in Phase 24 |

### 9.4 SAFE_MODE entry reasons

Reason strings passed to `SafeModeController.enter_safe_mode(reason=...)` or recorded as the freeze halt reason. They describe why SAFE_MODE was entered, not why a plan was rejected.

| Reason | Emitted in |
|--------|------------|
| `ENTRY_WITHOUT_PROTECTIVE` | `src/execution/manager.py`, `src/execution/protection.py`, `src/ops/drills.py` |
| `ENTRY_STATE_UNKNOWN` | `src/execution/manager.py` |
| `UNRESOLVED_EXECUTION_INTENT` | `src/execution/intent_recovery.py` (restart recovery: an execution intent could not be resolved by exchange query, so new entries stay blocked until Phase 20 reconciliation) |
| `ORPHAN_PROTECTIVE` | `src/ops/drills.py`, `src/reconcile/compare.py` (divergence kind) |
| `API_DEGRADATION` | `src/ops/drills.py` |
| `STALE_FEED` | `src/ops/drills.py` |
| `DB_FAILURE` | `src/execution/manager.py`, `src/execution/protection.py`, `src/execution/emergency_close.py`, `src/execution/intent_recovery.py`, `src/ops/drills.py` |
| `MANUAL_CLOSE` | `src/execution/manager.py`, `src/ops/drills.py` |
| `REGISTRY_DIFF` | `src/paper/freeze.py` (halt reason on a parameter registry diff) |
| `CLOSE_REQUIRED` | `src/execution/protection.py` (a protection branch decided that a filled entry must be closed with a reduce-only order: the stop is unconfirmed at the deadline, was definitively rejected, or the entry cancel stayed slow; SAFE_MODE is entered before the emergency closer is asked) |
| `EMERGENCY_CLOSE_FAILED` | `src/execution/emergency_close.py` (the automatic reduce-only MARKET close did not end flat) |
| `PROTECTION_HANDOFF_FAILED` | `src/execution/manager.py` (the entry was placed but could not be handed to the protection coordinator, so no stop will be placed automatically) |
| `APPROVED_QUANTITY_INCONSISTENT` | `src/execution/manager.py` (the approval row read inside the consume transaction stores a quantity that differs from the bound one or is below the quantity to place, D078 (6); nothing was consumed or sent; a NULL legacy row does not enter SAFE_MODE) |

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

`EXPIRED` is not produced by any `ApprovalAction`; lifecycle analytics derive it from the `EXPIRED` outcome label (`src/analytics/lifecycle.py`). The value set PENDING, APPROVED, SKIPPED, EXPIRED was a Phase 3 planner assumption (D-10); it is recorded here as the enum source of truth and was ratified by the operator on 2026-10-04.

## 11. State transitions

The legal-transition tables below are enforced by `src/domain/transitions.py` (`assert_transition`) inside the write transaction of the repositories, and the terminal rule (a terminal state has no successors) is also enforced by the database triggers of migration 0004. `tests/test_transitions.py` parses the text blocks in this section and compares them with the Python tables, so the two cannot drift apart. An unchanged state is not a transition: repositories treat an equal state as an idempotent no-op before calling `assert_transition`.

Status: Accepted (decision D051); drafted as the Phase 17 auto-mode default and confirmed by the user on 2026-10-02. The GLOSSARY carried value sets only before this section; the tables are anchored on EXECUTION_SPEC section 3 (entry order lifecycle). `APPROVED -> SUPERSEDED` for a TradePlan is deliberately illegal (see 11.2).

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

`SUPERSEDED` means a plan replaced before the human decided (from `READY` or `APPROVAL_PENDING`). An approved plan never becomes `SUPERSEDED`: it ends as `EXPIRED` or `INVALIDATED`, with its unfilled entry cancelled first, and a replacement plan needs its own approval. Allowing `APPROVED -> SUPERSEDED` later is a one-line additive change here and in `src/domain/transitions.py` and needs no migration, because `APPROVED` is not terminal.

After execution a plan stays `APPROVED`. The trade lifecycle truth lives in Order and Position, which are learned from Binance (the user-data stream in Phase 18 and the reconcile in Phase 20), not from the plan. A plan's `expiry_utc` governs only an unfilled entry and must never move an already-executed plan to `EXPIRED`.

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

Every move out of `UNKNOWN` must be backed by evidence from Binance (the canonical source): a reconcile query over REST or a user-data stream event. It must never come from local inference such as a timeout or an operator guess. Recording the evidence source in the journal is deferred to Phase 18 and 20, when the first callers exist.

### 11.4 Position transitions

```text
OPEN -> CLOSING, CLOSED, LIQUIDATION_REPORTED, UNKNOWN
CLOSING -> CLOSED, OPEN, UNKNOWN
LIQUIDATION_REPORTED -> CLOSED, UNKNOWN
UNKNOWN -> OPEN, CLOSING, CLOSED, LIQUIDATION_REPORTED
CLOSED -> (terminal)
```

The moves out of `UNKNOWN` need Binance evidence, as for orders. A closed position never reopens: a new exposure is a new position.

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

## 12. Persistence status values (Phase 17)

Value sets of the four enums the Phase 17 persistence layer adds. Each text block lists one value per line and `tests/test_transitions.py` compares it with the enum in `src/domain/enums.py`, so a value cannot be added in one place only (D016, D031). These are explicit status columns (D-21): a state is never inferred from a nullable timestamp.

### 12.1 ExecutionIntentStatus

```text
INTENDED
SENT
ACKED
REJECTED
UNKNOWN
```

- `INTENDED`: written ahead of the exchange call.
- `SENT`: committed just before the exchange call.
- `ACKED`: the exchange acknowledged the order, or it was found by its client id.
- `REJECTED`: definitively absent or refused by the exchange.
- `UNKNOWN`: unresolved; never re-sent, only resolved by querying the exchange.

Legal moves are in section 11.6.

### 12.2 ApprovalConsumptionStatus

```text
UNCONSUMED
CONSUMED
```

Set only by the consume transaction that inserts the `ENTRY` execution intent. `CONSUMED` requires the approval status to be `APPROVED`.

### 12.3 LiveInputsStatus

```text
COMPLETE
INCOMPLETE
```

Recorded on plan constraint snapshots. `INCOMPLETE` while margin type, leverage, equity or a required exchange filter carries the `UNKNOWN` sentinel (D-19); such a snapshot can never support a live order.

### 12.4 SystemStateKey

```text
SAFE_MODE
LIVE_ENABLEMENT
KILL_GATE
```

Keys of the durable system-state event log (D-22).

## 13. Paper runtime vocabulary (Phase 16)

Terms of the paper runtime, the SHADOW approval mode and the freeze-check evidence rules. The code that emits each one is named in its entry; where a rule is the user's to set, the entry points to the record and states no value of its own. Decision rows are in `docs/DECISIONS.md`.

### CONTEXT_BAR

Reason code of a 4h feed event that only extends the context window and is never evaluated as a signal bar. `run_paper_tick` in `src/paper/loop.py` appends it to `no_trade_records` (stage `feed_gate`) for every closed 4h event and moves on, so a 4h close never reaches the 1h setup series (CR-08). Phase 16 plan 16-09 confirmed it against `src/paper/loop.py`. Authority: D-05 of the Phase 16 context.

### DUPLICATE_BAR

Reason code of a closed 1h feed event whose open time was already seen, in the warmed-up history or earlier in the same call. `run_paper_tick` records it in `no_trade_records` (stage `feed_gate`) and does not evaluate the bar again (WR-04); this is how a reconnect or a REST backfill that re-delivers a bar stays harmless.

### SHADOW

The first stage of the safe release path SHADOW, DEMO, CANARY, LIVE (D040). Signals and APPROVE or SKIP decisions are journaled with simulated fills on real market data. Every SHADOW message and record is labelled "SHADOW — no real order". No trade-capable API key is loaded and no order adapter is constructed, so a SHADOW approval cannot reach an exchange.

### Paper-start allowlist: runtime process gate and per-call rule

Two layers read the same allowlist (`PAPER_START_ALLOWLIST`, accessed only through `allowlist_entries()` and `find_allowlist_entry()` in `src/paper/freeze.py`) and are not the same rule. The **runtime process gate** (`python -m src.paper.runtime`, plan 16-22) requires an exact-hash entry (strategy id, parameter set id and the 64-hex hash of the registry file) for every parameter set, a fully rationalized one included; an empty allowlist ends the process as SKIPPED, and a missing entry or different hash is a refusal. The **per-call rule** inside `pin_stream_epoch` (Phase 15, unchanged) consults the allowlist only for a set without rationale tables and also checks rationale completeness and PLACEHOLDER keys. A hash match at the runtime gate only lets that validation continue; rationale tables never replace runtime authorization. A comment in `src/paper/freeze.py` that says the allowlist is "consulted only for sets without rationale tables" describes the per-call rule only. Authority: user decision Q-A `runtime-exact-hash-all` (`.planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-A.md`), L-05, D061 item E; changing the per-call rule needs the separate D054 item (i) checkpoint.

### SKIPPED (freeze-check line)

Outcome of a line the hourly freeze check appends to `registry_diff.jsonl` while the paper-start allowlist is empty: reason `allowlist empty`, written by `python -m src.paper.freeze --check --from-allowlist` (`FreezeSkippedEntry`, plan 16-09). It is neither a clean tick nor a failure, it proves nothing about any parameter set, and it is not counted against the L-04 freeze-continuity criterion before the epoch pin. Authority: D061 item A, D-21. Not the `SKIPPED` value of `ApprovalResult` in section 10.

### EVIDENCE_GAP

A scheduled freeze tick that is missing, so late that no valid evidence exists, invalid, or whose workflow produced no result. It is never CLEAN, never interpolated and never filled from neighbouring ticks, and no tolerance applies because GitHub Actions may delay or drop a scheduled run. It breaks the qualifying trial freeze window, so the qualifying 14-day trial restarts with a new epoch pin; runtime evidence collected before stays as auxiliary evidence and cannot complete the freeze criterion of the new trial. A run that did not happen writes no line, so the gap is found outside the workflow (reconciler, plan 16-15). Authority: D063 item 2 and D065 item 4 (REV-02, REV-18). The grace after which a late tick counts as a gap is the user's ratified value, not a default of the code.

### PLANNED_RESTART

Gap reason code of a restart the operator chose, kept distinct from a crash or maintenance for audit. It is always uncovered: it is never removed from the coverage denominator and a gap that has a reason is still uncovered. Authority: D063 item 1 (REV-01).

### HEALTHY

Feed health state in which the runtime observes the feed as the user's healthy-feed definition requires. Only HEALTHY time is covered by the runtime-coverage measure; the denominator is the whole fixed trial window. The numeric definition (silence, stale-bar age, reconnect bounds) is the user's O-07 table and is not restated here. Authority: D063 item 1.

### DEGRADED

Feed health state between HEALTHY and DISCONNECTED. DEGRADED time is not covered, and a maximum for a continuous DEGRADED state exists whose number is the user's (O-07 table). Authority: D063 item 1.

### LIVE_WS, REST_WARMUP, REST_BACKFILL

The three source tags of a bar (`SourceTag` in `src/paper/vocabulary.py`). A closed `LIVE_WS` bar is the only kind that can be evaluated for a signal. A `REST_WARMUP` bar closed while the process was down: it extends history and gap accounting and is never evaluated, so no late or fabricated signal exists (L-11, D061). Whether a `REST_BACKFILL` bar, recovered by REST while the process stayed up, may be evaluated is the user's decision Q-D, recorded by plan 16-24 in `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-D.md`; this entry states no rule of its own.

### test_only

Marker carried by every record of the pre-soak rehearsal of the SHADOW APPROVE, CONFIRM, journal path. The rehearsal runs before the trial soak in its own window on an explicit test-only path with its own test identifier, does not bypass the paper-start allowlist, and is excluded from every count: signals, trades, parity evidence, G1 to G5 and PAPER-03. The trial soak starts from a clean state afterwards. Authority: D063 item 3 (REV-03).
