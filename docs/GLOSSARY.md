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

This section is the source of truth for rejection reason codes (D016, D031, audit F-110). One canonical code per concept: the 17 codes that production code referenced before Phase 12 (`RejectionReason.X` in `src/`, derived by scan, gate GL-02), the reserved `INSUFFICIENT_MARGIN`, the two Phase 12 cost-guard codes `STOP_TOO_TIGHT` and `COST_TO_RISK_EXCEEDED` (D046), `ENTRY_WITHOUT_PROTECTIVE`, promoted from the plain-string list in Phase 20 (D-10, D044 item 1), and `NO_FILL` and `HEALTH_CHECK_FAILED`, promoted from the same list in Phase 24 (G3-005, D-35). The block in 9.1 equals the `RejectionReason` enum (23 members, gate GL-03). The five synonyms that used to exist as members are retired and recorded in 9.2.

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
ENTRY_WITHOUT_PROTECTIVE
NO_FILL
HEALTH_CHECK_FAILED
```

`ENTRY_WITHOUT_PROTECTIVE` means an entry fill exists without a confirmed protective stop. It was a plain-string code before Phase 20 (D-10, D044 item 1); the string value is unchanged. The same string is also a reconciler divergence kind and a SAFE_MODE entry reason (9.4); those copies stay plain strings because they are divergence kinds and SAFE_MODE reasons, not rejection reasons.

`NO_FILL` means the entry order produced no fill (`src/execution/manager.py`, the no-trade result reason). `HEALTH_CHECK_FAILED` means a health check reported failure, so trading is blocked (`src/ops/health.py`, the result `reason_code`, paired with `OK` on pass). Both were plain strings until Phase 24, promoted there (G3-005, D-35, D044 item 1); the string values are unchanged, so stored rows, golden texts and journal payloads keep their bytes, and both modules now emit them through `RejectionReason.<NAME>.value`.

`INSUFFICIENT_MARGIN` is emitted by the Phase 22 margin guard (`src/risk/margin_check.py` decides it, `src/execution/margin_guard.py` returns it) when the free margin does not cover the margin the plan needs; the code list above is unchanged. No running process composes the guard before Phase 24.

`STOP_TOO_TIGHT` means the stop distance divided by the sizing entry price is below the registry `min_stop_distance_rate`; `COST_TO_RISK_EXCEEDED` means the round-trip modeled cost divided by `risk_per_unit` is above the registry `max_cost_to_risk`. Both are emitted before quantization (D-07).

Phase 15 planner meanings (D054, D-27): the planner reuses three existing codes for its geometry invariants, checked in this fixed order with the invariants before the RR gate. `STOP_TOO_TIGHT` also means the stop is not strictly outside the whole entry zone (a LONG stop at or above the lower edge of the zone, a SHORT stop at or below its upper edge), or the distance from the entry reference to the stop is closer than `min_stop_atr` x ATR when that key is present. `INVALIDATED` also means the signal bar has already traded through the planned stop (a LONG bar low at or below the stop, a SHORT bar high at or above it). `RR_TOO_LOW` also means TP1 is not on the profit side of the entry reference, which is checked before the `minimum_rr` threshold. No new member was added for these cases.

### 9.2 Retired aliases (removed in Phase 12)

These five names were removed from `RejectionReason` and from `tests/test_domain_enums.py` in Phase 12 (D-09, D044 follow-up 1). New code must use the replacement. The table records the removal only: it declares no enum member, and gates GL-01 and GL-03 fail if a retired name re-enters the enum or the 9.1 block. The 9.1 block equals the `RejectionReason` enum (23 members, gate GL-03).

| Removed name | Use instead | Removed in |
|--------------|-------------|------------|
| `QUANTIZATION_REJECT` | `MIN_QTY_REJECT` or `UTILIZATION_REJECT` | Phase 12 (D046) |
| `MIN_NOTIONAL_REJECT` | `NOTIONAL_REJECT` | Phase 12 (D046) |
| `RISK_LIMIT` | `AGGREGATE_CAP_REJECT` or `MAX_POSITIONS_REJECT` | Phase 12 (D046) |
| `CORRELATED_RISK_LIMIT` | `CLUSTER_CAP_REJECT` | Phase 12 (D046) |
| `DAILY_STOP` | `DAILY_STOP_BLOCK` when used as a rejection reason | Phase 12 (D046) |

`DAILY_STOP` remains a valid `DailyState` value (section 8.1); only its use as a rejection reason is retired.

### 9.3 Plain-string codes emitted outside RejectionReason

Production code also emits the following plain strings as `reason_code` values or outcome labels. They are not `RejectionReason` members. Status for the rejection-style codes: proposed canonical, promote to the enum in the owning phase (Phases 24 and 26; `ENTRY_WITHOUT_PROTECTIVE` was promoted in Phase 20, and `NO_FILL` and `HEALTH_CHECK_FAILED` in Phase 24 (G3-005); all three now live in 9.1). Derived from `src/` by reading the emitting code; the list is not exhaustive for divergence kinds. Phase 23 adds its plain codes here instead of new `RejectionReason` members: the enum kept its 21 members through Phase 23 (it has 23 members since Phase 24 promoted `NO_FILL` and `HEALTH_CHECK_FAILED`, G3-005); this deliberately amends the wording of the Phase 23 decision D-15, which had proposed enum members (orchestrator resolution 7).

| Code | Emitted in | Meaning | Status |
|------|------------|---------|--------|
| `DISABLED` | `src/execution/enablement.py` (`_DISABLED`), `src/execution/manager.py` (fallback `reason_code`) | Live order enablement is off, no order placed | proposed canonical, promote in Phase 26 |
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
| `LIMITS_NOT_CONFIGURED` | `src/execution/pre_placement.py` | At least one of the nineteen required execution limits (`EXECUTION_LIMIT_KEYS` holds twenty keys: the seven Phase 19 keys, the seven Phase 20 keys, the alert-only key `reconcile.entry_stale_grace_ms`, which never blocks, the two Phase 21 keys `account.max_equity_age_ms` and `account.max_daily_loss_age_ms` and the three Phase 22 keys `margin.liquidation_buffer_bps`, `margin.max_bracket_age_ms` and `margin.headroom_bps`) in `config/execution/execution-limits-v1.toml` is still `NOT_CONFIGURED`, so every live and Demo placement is refused. The owner set `account.max_equity_age_ms` (D084), `account.max_daily_loss_age_ms` (D087, 2026-10-25) and the three `margin.*` keys (D085, 2026-10-24); fourteen required keys stay `NOT_CONFIGURED` | proposed canonical, promote in Phase 24 |
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
| `RECONCILED_ABSENT` | `src/execution/intent_recovery.py` (`UnknownEntryResolver`; the constant `RESOLUTION_RECONCILED_ABSENT` lives in `src/execution/intent_store.py`) | Resolution reason of an execution intent, stored in `resolution_reason_code` (Alembic revision 0007): an UNKNOWN ENTRY intent was closed as REJECTED after the D-11 evidence held in one pass (the configured number of clean not-found probes by client order id, `goodTillDate` plus grace passed, a fresh positions read and open-orders read for the symbol showing no position and no open order, all journaled with source `REST_RECONCILE`). It records that the entry is absent on Binance; it is not a Binance rejection and never exits SAFE_MODE | resolution reason, not a rejection reason |
| `NEVER_SENT` | `src/execution/intent_recovery.py` (`resolve_unresolved_intents`; the constant `RESOLUTION_NEVER_SENT` lives in `src/execution/intent_store.py`) | Resolution reason of an execution intent, stored in `resolution_reason_code`: an INTENDED ENTRY (`mark_sent` never committed, so the send never happened) was probed once by client order id, found absent, and recorded REJECTED (D-11). It is not a Binance rejection | resolution reason, not a rejection reason |
| `DAY_STATE_MISSING` | `src/risk/daily_loss.py` (`BLOCKED_DAY_STATE_MISSING`, carried as `blocked_reason` of a `DayStateVerdict` whose `reason_code` is `UNCERTAIN_ACCOUNT_STATE`); alerted as `DB_FAILURE` by `src/execution/daily_stop.py` | There is no persisted day state for today and the exposure rule forbids opening one (a missing day with open exposure); no entry is allowed and nothing is cancelled | blocked reason, not a rejection reason |
| `DAY_STATE_UNREADABLE` | `src/risk/daily_loss.py` (`BLOCKED_DAY_STATE_UNREADABLE`), alerted as `DB_FAILURE` by `src/execution/daily_stop.py` | The persisted day state or its components could not be read; the day is never treated as NORMAL | blocked reason, not a rejection reason |
| `DAY_BASE_UNAVAILABLE` | `src/risk/daily_loss.py` (`BLOCKED_DAY_BASE_UNAVAILABLE`) | The day-start equity base could not be read fresh enough to open the day | blocked reason, not a rejection reason |
| `DAILY_LOSS_UNKNOWN` | `src/risk/daily_loss.py` (`BLOCKED_DAILY_LOSS_UNKNOWN`) | A loss source failed, a component is in another asset or conflicts with a stored one, or the funding policy cannot count the day; the loss is unknown, so no entry is allowed (a held latch still answers `DAILY_STOP`) | blocked reason, not a rejection reason |
| `DAY_THRESHOLDS_INVALID` | `src/risk/daily_loss.py` (`BLOCKED_DAY_THRESHOLDS_INVALID`) | The parameter set lacks a typed daily threshold or its warning is above its stop, so the daily state cannot be derived (a malformed set must not read as NORMAL) | blocked reason, not a rejection reason |
| `FUNDING_SOURCE_UNVERIFIED` | `src/risk/daily_loss.py` (`FUNDING_LABEL_UNVERIFIED`) | Label on a daily loss counted under `FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING` (the owner's O-2 answer): zero income rows were counted as zero funding while the FUNDING_FEE source has not been observed | label, not a rejection reason |
| `LIQUIDATION_TOO_CLOSE` | `src/risk/liquidation.py` | The liquidation price of the plan is not strictly beyond the stop by the owner's buffer (`margin.liquidation_buffer_bps`); nothing is placed | proposed canonical, promote in Phase 24 |
| `LIQUIDATION_INPUT_UNAVAILABLE` | `src/risk/liquidation.py` | The leverage brackets are missing, malformed, stale or inconsistent, so no liquidation price can be computed; the plan is refused (fail closed) | proposed canonical, promote in Phase 24 |
| `LEVERAGE_ABOVE_BRACKET` | `src/risk/liquidation.py` | The leverage the plan would need is above the exchange maximum of the bracket that holds its entry notional | proposed canonical, promote in Phase 24 |
| `NOTIONAL_ABOVE_MAX` | `src/risk/liquidation.py` | The entry notional is above the top bracket of the exchange (or above the symbol's `maxNotionalValue`), so no tier fits | proposed canonical, promote in Phase 24 |
| `MARGIN_CONFIG_UNVERIFIED` | `src/execution/symbol_config_guard.py` | The symbol configuration could not be read, or the closing read does not show ISOLATED at the target leverage; no entry is placed and a DIVERGENCE alert carries this code as its reason | proposed canonical, promote in Phase 24 |
| `MARGIN_CONFIG_CHANGE_REFUSED` | `src/execution/symbol_config_guard.py` | The symbol holds a position, an open order or an open algo order and its configuration is not already the target; the guard changes nothing (zero requests) and never cancels or closes to make room | proposed canonical, promote in Phase 24 |
| `AUTO_ADD_MARGIN_ENABLED` | `src/execution/symbol_config_guard.py` | The symbol reports `isAutoAddMargin` true; an automatic top-up would defeat the liquidation guard, so the plan is refused before any change | proposed canonical, promote in Phase 24 |
| `MARGIN_MODE_UNSUPPORTED` | `src/execution/margin_guard.py` | The account is in multi-asset margin mode; V1 supports single-asset margin only (a Hedge account keeps `HEDGE_MODE_UNSUPPORTED`) | proposed canonical, promote in Phase 24 |
| `LIQUIDATION_UNKNOWN_AFTER_FILL` | `src/execution/liquidation_watch.py` | After the fill the exchange `liquidationPrice` is None, zero (the cross-margin sentinel), negative or not finite, or an input needed to judge it is unknown; judged as a failure by the owner's policy (built, not active before Phase 24) | proposed canonical, promote in Phase 24 |
| `LIQUIDATION_TOO_CLOSE_AFTER_FILL` | `src/execution/liquidation_watch.py` | After the fill the exchange `liquidationPrice` is not strictly beyond the stop by the buffer, measured from the actual fill price; judged as a failure by the owner's policy (built, not active before Phase 24) | proposed canonical, promote in Phase 24 |
| `LIQUIDATION_PRICE_DIFFERS` | `src/execution/liquidation_watch.py` | The exchange and the locally computed liquidation prices differ at the exchange's own decimal places while the exchange value passes; calibration only, never a refusal and never an alert (the protection journal row `PROTECTION_LIQUIDATION_PRICE_DIFFERS` is the record, without any amount in a message) | proposed canonical, promote in Phase 24 (calibration reason, never a refusal) |
| `READING_UNUSABLE` | `src/risk/margin_check.py` (`BLOCKED_READING_UNUSABLE`) | The account reading is missing, stale, future-dated or inconsistent between its two `availableBalance` figures; mapped to `UNCERTAIN_ACCOUNT_STATE` by the margin guard | blocked reason, not a rejection reason |
| `HEDGE_MODE` | `src/risk/margin_check.py` (`BLOCKED_HEDGE_MODE`) | The account reading says `dualSidePosition` is true; mapped to `HEDGE_MODE_UNSUPPORTED` by the margin guard before anything is changed | blocked reason, not a rejection reason |
| `MULTI_ASSETS_MODE` | `src/risk/margin_check.py` (`BLOCKED_MULTI_ASSETS_MODE`) | The account reading says multi-asset margin is on; mapped to `MARGIN_MODE_UNSUPPORTED` by the margin guard before anything is changed | blocked reason, not a rejection reason |
| `USER_ID_UNAVAILABLE` | `src/approval/reason_codes.py` (also the confirm core's `REASON_USER_ID_UNAVAILABLE`) | The press carries no usable Telegram user id (no `from_user`, or a non-integer id); refused before any lookup. A confirm that cannot read the id is journaled EXPIRED with this reason | proposed canonical, promote in Phase 24 |
| `CHAT_NOT_PRIVATE` | `src/approval/reason_codes.py` | The press came from a chat whose type is not exactly `private` (group, supergroup, channel or unknown), even if the chat id is the authorized one; refused before any lookup | proposed canonical, promote in Phase 24 |
| `USER_NOT_AUTHORIZED` | `src/approval/reason_codes.py` | The pressing Telegram user id is not in the required allow-list `TELEGRAM_AUTHORIZED_USER_IDS`; refused before any lookup and journaled with only the presser's id | proposed canonical, promote in Phase 24 |
| `APPROVAL_STORE_FAILURE` | `src/approval/reason_codes.py`, returned by `src/adapters/telegram_callbacks.py` | A store or connection failure inside the callback dispatch; the press changed nothing (before Phase 23 it was reported as `INVALIDATED`). The keyboard is kept so the operator can tap again | proposed canonical, promote in Phase 24 |
| `ALREADY_DECIDED` | `src/approval/reason_codes.py`, answered by `src/execution/approval_desk.py` | A tap on an approval that was already decided (a replay, or the other button of the same request); the reply says `Already decided` and nothing changes. Read from the stored row, never from memory | outcome label, not a rejection reason |
| `CALLBACK_HANDLER_ERROR` | `src/approval/reason_codes.py`, returned by `src/adapters/telegram_callbacks.py` (`on_callback`) | An unexpected exception inside the callback handler after both gates; it is logged by class name, journaled as `CALLBACK_HANDLER_FAILED` and answered with one neutral text. The keyboard is kept | proposed canonical, promote in Phase 24 |
| `CONFIRM_INPUTS_UNAVAILABLE` | `src/execution/confirm_recheck.py` | No pre-fetched exchange snapshot exists for the CONFIRM press (none was put, or it was already taken: each snapshot serves one press), so the re-check cannot run and the confirm is refused (fail closed) | proposed canonical, promote in Phase 24 |
| `CONFIRM_INPUTS_MISMATCH` | `src/execution/confirm_recheck.py` | The pre-fetched snapshot belongs to another plan hash, symbol or side than the plan being confirmed; the snapshot is consumed and the confirm is refused | proposed canonical, promote in Phase 24 |
| `MONEY_AT_STAKE_MISSING` | `src/risk/money_at_stake.py` (`MoneyAtStakeUnavailable`), checked again by `src/adapters/telegram_notify.py` and `src/execution/approval_desk.py` | A DEMO, LIVE or SIMULATE request has no money block, or an input of it (sizing result, costs, leverage, equity, stop, take-profits) is missing or disagrees with the plan; the field is named and nothing is written or sent | proposed canonical, promote in Phase 24 |
| `USER_MISMATCH` | `src/approval/confirm_core.py` (`REASON_USER_MISMATCH`) | A CONFIRM or CANCEL press came from a listed user other than the one who pressed APPROVE; the press is rejected, the confirm stays open and the approving user can still confirm | proposed canonical, promote in Phase 24 |
| `CHAT_MISMATCH` | `src/approval/confirm_core.py` (`REASON_CHAT_MISMATCH`) | A CONFIRM or CANCEL press came from another chat than the confirm card was issued in; the press is rejected | proposed canonical, promote in Phase 24 |
| `NO_CONFIRM_CONTEXT` | `src/approval/confirm_core.py` (`REASON_NO_CONFIRM_CONTEXT`) | A CONFIRM or CANCEL press for a card the process does not know (typically after a restart: card, message id and token live in memory only); the press is refused and the card loses its keyboard | proposed canonical, promote in Phase 24 |
| `RECHECK_ERROR` | `src/approval/confirm_core.py` (`REASON_RECHECK_ERROR`) | The injected CONFIRM-time re-check raised an exception; any raise is treated as a refusal (fail closed), nothing is handed to placement | proposed canonical, promote in Phase 24 |
| `CONFIRM_TTL_ELAPSED` | `src/approval/confirm_core.py` (`REASON_CONFIRM_TTL_ELAPSED`) | The 60-second confirm window elapsed before a valid CONFIRM; the confirm is journaled EXPIRED and its token is dead | confirm journal reason, not a rejection reason |
| `CARD_DELIVERY_FAILED` | `src/approval/confirm_core.py` (`REASON_CARD_DELIVERY_FAILED`) | No confirmation card could be delivered (the edit and the one fallback send both failed, or Telegram was throttling); the confirm is journaled EXPIRED and its token is dead | confirm journal reason, not a rejection reason |
| `RUNTIME_RESTART` | `src/approval/confirm_core.py` (`REASON_RUNTIME_RESTART`) | The process restarted while a confirm was outstanding; every outstanding confirm is journaled EXPIRED at startup because the in-memory tokens died with the process | confirm journal reason, not a rejection reason |
| `CONFIRM_ALREADY_EXPIRED` | `src/approval/confirm_core.py` (`REASON_CONFIRM_ALREADY_EXPIRED`) | A CONFIRM or CANCEL press arrived for a confirm that was already journaled EXPIRED; the press is rejected and changes nothing | confirm journal reason, not a rejection reason |
| `VALIDITY_RULE_ERROR` | `src/execution/confirm_flow.py` | Shown on the confirmation card only: the injected remaining-validity rule raised, so the card reads `refused (VALIDITY_RULE_ERROR)` (fail closed); it is not a stored reason code | confirmation card text, not a rejection reason |
| `LEFT_PENDING_SIBLING_DECIDED` | `src/paper/shadow.py` (restart sweep outcome) | Restart-sweep outcome label of a SHADOW approval row that stayed PENDING because its plan already had an APPROVED or SKIPPED row; since Alembic revision 0014 it is the only case left (the two PENDING siblings of an undecided plan are both EXPIRED, DECISIONS D088) | outcome label, not a rejection reason |

### 9.4 SAFE_MODE entry reasons

Reason strings passed to `SafeModeController.enter_safe_mode(reason=...)` or recorded as the freeze halt reason. They describe why SAFE_MODE was entered, not why a plan was rejected.

| Reason | Emitted in |
|--------|------------|
| `ENTRY_WITHOUT_PROTECTIVE` | `src/execution/manager.py`, `src/execution/protection.py`, `src/ops/drills.py` |
| `ENTRY_STATE_UNKNOWN` | `src/execution/manager.py` |
| `UNRESOLVED_EXECUTION_INTENT` | `src/execution/intent_recovery.py` (restart recovery: an execution intent could not be resolved by exchange query, so new entries stay blocked until Phase 20 reconciliation) |
| `ORPHAN_PROTECTIVE` | `src/ops/drills.py`, `src/reconcile/compare.py` (divergence kind), `src/reconcile/classify.py` (policy) |
| `API_DEGRADATION` | `src/ops/drills.py`, `src/reconcile/loop.py` (a Binance read, the compare or the REST gate check of the tick failed for a reason other than authentication; nothing is judged on partial data) |
| `STALE_FEED` | `src/ops/drills.py`, `src/reconcile/loop.py` (the mark price of a tracked symbol is older than `stale_feed.max_mark_price_age_ms`, or the user-data stream is silent for longer than `stale_feed.max_user_data_silence_ms`; D-25) |
| `DB_FAILURE` | `src/execution/manager.py`, `src/execution/protection.py`, `src/execution/emergency_close.py`, `src/execution/intent_recovery.py`, `src/reconcile/loop.py` (a local read of the tick failed: no compare is made), `src/reconcile/startup.py` (a store read or write of the restart recovery failed), `src/ops/drills.py` |
| `MANUAL_CLOSE` | `src/execution/manager.py`, `src/ops/drills.py` |
| `REGISTRY_DIFF` | `src/paper/freeze.py` (halt reason on a parameter registry diff) |
| `CLOSE_REQUIRED` | `src/execution/protection.py` (a protection branch decided that a filled entry must be closed with a reduce-only order: the stop is unconfirmed at the deadline, was definitively rejected, or the entry cancel stayed slow; SAFE_MODE is entered before the emergency closer is asked) |
| `EMERGENCY_CLOSE_FAILED` | `src/execution/emergency_close.py` (the automatic reduce-only MARKET close did not end flat) |
| `PROTECTION_HANDOFF_FAILED` | `src/execution/manager.py` (the entry was placed but could not be handed to the protection coordinator, so no stop will be placed automatically) |
| `APPROVED_QUANTITY_INCONSISTENT` | `src/execution/manager.py` (the approval row read inside the consume transaction stores a quantity that differs from the bound one or is below the quantity to place, D078 (6); nothing was consumed or sent; a NULL legacy row does not enter SAFE_MODE) |
| `SYMBOL_OWNERSHIP_CONFLICT` | `src/reconcile/classify.py`, `src/reconcile/loop.py` (reconcile time: more than one active plan for one symbol, or exposure whose owning plan cannot be determined, is the divergence kind `AMBIGUOUS_POSITION_OWNER` from `src/reconcile/compare.py`; SAFE_MODE blocks new entries and the operator is alerted, nothing is closed, cancelled or guessed; owner decision O-D, not a D-13 decision; `SafeModeController.exit_safe_mode` refuses with the same code while the conflict stands, plan 20-28) |
| `PROTECTION_STATE_INVALID` | `src/execution/protection.py`, `src/execution/protection_rebuild.py` (the journaled `PROTECTION_TRANSITION` rows of a plan cannot be replayed on restart: a sequence gap, an illegal edge or a missing evidence; the plan is restored UNPROTECTED and closed by the exchange position, never by a guessed history) |
| `RESTORE_INCONSISTENT` | `src/execution/protection.py`, `src/reconcile/startup.py` (restart recovery found local state that cannot be trusted: an unreadable or corrupt spill, a replay conflict, a stop history the journal cannot establish, a plan restored in a state its rows contradict; files are kept, no stop is placed on a guessed history) |
| `SAFE_MODE_STATE_UNREADABLE` | `src/reconcile/safe_mode.py` (the durable SAFE_MODE state could not be read at start; the controller starts in SAFE_MODE, it never starts "off" on an unreadable store) |
| `USER_DATA_STREAM_HALTED` | `src/reconcile/classify.py` (the user-data supervisor halted: the divergence kind `STREAM_TASK_DIED` maps to this reason, alert event `STALE_DATA`), `src/reconcile/loop.py` (the tick applies the policy) |
| `AUTH_FAILURE` | `src/reconcile/loop.py` (a truth read of the tick failed with an authentication or signature error; alert event `AUTH_FAILURE`, subject `SYSTEM`; the coordinator, the closer and the manager journal the error class and do not alert it) |
| `POSITION_WITHOUT_STOP` | `src/reconcile/compare.py` (divergence kind: an exchange position has no ACTIVE system STOP_LOSS), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `TP_ONLY_POSITION` | `src/reconcile/compare.py` (divergence kind: an exchange position has take-profit legs but no ACTIVE system stop), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `SIGN_FLIPPED_POSITION` | `src/reconcile/compare.py` (divergence kind: the signed bound check: the exchange position has the opposite side to the intended one), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `DOUBLED_POSITION` | `src/reconcile/compare.py` (divergence kind: the signed bound check (D-01a): the exchange position is larger than the intended quantity), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `FOREIGN_ORDER` | `src/reconcile/compare.py` (divergence kind: an exchange order with no local intent whose client id does not carry this system's prefix, for example an order placed by hand in the Binance UI; never cancelled), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `UNTRACKED_SYSTEM_ORDER` | `src/reconcile/compare.py` (divergence kind: an exchange order with no local intent whose client id does carry this system's prefix; never swept), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `UNSYNCED_NORMAL` | `src/reconcile/compare.py` (divergence kind: a local normal order has no matching exchange normal order), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `UNSYNCED_ALGO` | `src/reconcile/compare.py` (divergence kind: a local algo order has no matching exchange algo order), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `UNSYNCED_POSITION` | `src/reconcile/compare.py` (divergence kind: an exchange position has no matching local intent), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `DUPLICATE_EXCHANGE_ID` | `src/reconcile/compare.py` (divergence kind: the same client id appears twice in the exchange truth), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `UNSUPPORTED_POSITION_SIDE` | `src/reconcile/compare.py` (divergence kind: a Hedge-mode position row (V1 is One-way only)), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `STREAM_SINK_FAILURE` | `src/reconcile/compare.py` (divergence kind: a record of the user-data stream could not be stored), `src/reconcile/classify.py` (the kind is its own SAFE_MODE reason in `POLICY_BY_KIND`) |
| `STALE_ENTRY_ORDER` | `src/reconcile/loop.py` (an alert event of `OPS05_MATRIX`, NOT a SAFE_MODE reason: a resting entry order that is still `NEW` more than the owner grace `reconcile.entry_stale_grace_ms` after its `goodTillDate` raises this alert once while it stands, because Binance Demo did not cancel a GTD order 780 s and 1500 s after `goodTillDate`; alert only, nothing is cancelled, SAFE_MODE is not entered and no plan state changes; the key is `NOT_CONFIGURED`, and while it is unset the check is skipped and the journal row `RECONCILE_STALE_ENTRY_CHECK_SKIPPED` says so) |

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

### 11.7 Protection transitions

This is the `ProtectionState` machine of the protection coordinator (`src/execution/protection.py`), which implements the execution model of D079. Its table is `TransitionKind.PROTECTION` in `src/domain/transitions.py` (plan 20-02, D-29), keyed by the eleven `ProtectionState` string values and copied from the `ProtectionState` docstring; it is enforced by `ProtectionCoordinator._transition`. Unlike 11.1 to 11.6 it is not persisted as a table and has no database trigger. A plan is first registered in the state `PROTECTION_INITIAL_STATE`, which is `AWAITING_FILL`.

```text
AWAITING_FILL -> CLOSE_REQUIRED, ENTRY_ENDED_NO_FILL, ENTRY_UNRESOLVED, UNPROTECTED
ENTRY_UNRESOLVED -> AWAITING_FILL, CLOSE_REQUIRED, ENTRY_ENDED_NO_FILL, UNPROTECTED
UNPROTECTED -> CLOSE_REQUIRED, FLAT, PROTECTED, PROTECTED_ENTRY_OPEN
PROTECTED_ENTRY_OPEN -> CLOSE_REQUIRED, FLAT, PROTECTED, UNPROTECTED
PROTECTED -> CLOSE_REQUIRED, COMPLETE, FLAT, TP_UNAVAILABLE, UNPROTECTED
COMPLETE -> CLOSE_REQUIRED, FLAT, UNPROTECTED
TP_UNAVAILABLE -> CLOSE_REQUIRED, FLAT, UNPROTECTED
CLOSE_REQUIRED -> CLOSE_FAILED, FLAT
CLOSE_FAILED -> CLOSE_REQUIRED, FLAT
FLAT -> (terminal)
ENTRY_ENDED_NO_FILL -> (terminal)
```

State meanings (from the `ProtectionState` docstring and the comments beside it; a state without a stated meaning is described by its edges only):

- `AWAITING_FILL`: the state a plan is first registered in; it holds no known exposure; a fill leads to `UNPROTECTED`.
- `UNPROTECTED`: a position exposed without a confirmed stop; a confirmed stop that is lost leads here (reasons `STOP_LOST`, `STOP_LOST_AFTER_PROTECTED`), and from there the plan leaves only to `CLOSE_REQUIRED` or `FLAT`.
- `PROTECTED_ENTRY_OPEN`: reached from `UNPROTECTED`; a lost stop moves it back to `UNPROTECTED`.
- `PROTECTED`: reached from `UNPROTECTED`; leaves to `COMPLETE` or `TP_UNAVAILABLE`, or to `FLAT` when REST reads flat.
- `COMPLETE`: reached from `PROTECTED`; leaves to `FLAT`.
- `TP_UNAVAILABLE`: reached from `PROTECTED`; leaves to `FLAT`.
- `CLOSE_REQUIRED`: a close is required; it moves to `CLOSE_FAILED` and back, and ends `FLAT`; no edge leads from `CLOSE_REQUIRED` or `CLOSE_FAILED` to a protected state.
- `CLOSE_FAILED`: a close attempt failed; see `CLOSE_REQUIRED`.
- `FLAT`: terminal; the plan ended flat.
- `ENTRY_ENDED_NO_FILL`: terminal; reached from `AWAITING_FILL` or `ENTRY_UNRESOLVED` when the entry ended with no fill.
- `ENTRY_UNRESOLVED`: an `ENTRY_STATE_UNKNOWN` entry never found by its GTD time plus the grace (19-REVIEW WR-05); it leaves to `UNPROTECTED` on a fill, to `ENTRY_ENDED_NO_FILL` when found ended, or to `AWAITING_FILL` when found open.

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

## 14. Live account state vocabulary (Phase 21)

Words of the live equity, daily loss and reservation code. This section describes the code as built (`src/risk/daily_loss.py`, `src/risk/reservations.py`); it adds no rule and no `RejectionReason` member. Nothing here is started by a running process before Phase 24. Demo facts are demo-observed, not mainnet.

### 14.1 ReservationStatus

A reservation is one row per plan for the plan's life (`risk_reservations`). The caps count RESERVED, PLACED and OPEN.

| Value | Meaning | Counted by the caps |
|-------|---------|---------------------|
| `REQUESTED` | The plan asked to reserve its sized risk; not approved yet | no |
| `RESERVED` | The approval transaction accepted the risk against the caps | yes |
| `PLACED` | The entry order was sent | yes |
| `OPEN` | The entry filled and the position is live | yes |
| `RELEASED` | Terminal; the risk is free again. The first release reason and time are kept | no |

### 14.2 ReleaseReason

The nine reasons, each with the terminal plan state that causes it and the statuses it may release from (`RELEASE_SOURCE_STATUSES`). RELEASED is never a source.

| Value | Terminal plan state | Permitted source statuses |
|-------|---------------------|---------------------------|
| `APPROVAL_SKIPPED` | Approval decided SKIPPED (the SKIP and CANCEL actions) | REQUESTED |
| `APPROVAL_EXPIRED` | Approval decided EXPIRED | REQUESTED |
| `PLAN_EXPIRED` | Plan EXPIRED, or an APPROVED plan never consumed before its expiry | REQUESTED, RESERVED |
| `PLAN_INVALIDATED` | Plan INVALIDATED | REQUESTED, RESERVED |
| `PLAN_SUPERSEDED` | Plan SUPERSEDED | REQUESTED, RESERVED |
| `PLACEMENT_REFUSED` | A final pre-placement refusal before consumption (`PLAN_STATUS_INVALID`, `PLAN_INVALIDATED_BEFORE_PLACEMENT`, `VALIDITY_TOO_SHORT`) | RESERVED |
| `ENTRY_REJECTED` | Entry intent REJECTED | RESERVED, PLACED |
| `ENTRY_ENDED_NO_FILL` | Protection state `ENTRY_ENDED_NO_FILL` (a resting entry ended with no fill) | PLACED |
| `POSITION_CLOSED` | Protection state `FLAT` | OPEN |

### 14.3 ComponentKind and ComponentSource

A daily loss component is one signed amount of one kind from one source. The same component seen from two sources counts once, at the more adverse amount.

| Value | Meaning |
|-------|---------|
| `ComponentKind.FILL_PNL` | Realized PnL of a fill |
| `ComponentKind.FILL_COMMISSION` | Commission of a fill |
| `ComponentKind.FUNDING` | A funding payment or receipt; comes from REST income only |
| `ComponentSource.USER_DATA_EVENT` | The user-data stream event of a fill |
| `ComponentSource.REST_USER_TRADES` | A row of the REST user trades read |
| `ComponentSource.REST_INCOME` | A row of the REST income read |

### 14.4 FundingPolicy

| Value | Meaning |
|-------|---------|
| `TRADES_WITH_UNVERIFIED_FUNDING` | Owner choice O-2, "option A" (2026-10-23): PnL and commission come from the trade sources, FUNDING_FEE rows are added when the income read returns them, zero rows count as zero funding with the label `FUNDING_SOURCE_UNVERIFIED`, and a failed income read makes the loss unknown. Passed by the Phase 24 composition |
| `REQUIRE_VERIFIED_FUNDING_SOURCE` | The loss is unknown until `FUNDING_SOURCE_VERIFIED` is True; it stays False until a DECISIONS row changes it |

## 15. Margin guard vocabulary (Phase 22)

Words of the leverage, margin and liquidation guard. This section describes the code as built (`src/execution/symbol_config_guard.py`, `src/execution/margin_guard.py`, `src/execution/liquidation_watch.py`, `src/risk/liquidation.py`, `src/risk/margin_check.py`); it adds no rule and no `RejectionReason` member (the new codes are plain strings in 9.3, amendment A3). Nothing here is started by a running process before Phase 24. Demo facts are demo-observed, not mainnet, and are single samples.

### 15.1 LiquidationFailurePolicy

What a failed post-fill liquidation check means. Both members are built behind a required argument with no default. The owner chose `CLOSE_POSITION` on 2026-10-24 (DECISIONS D085, owner item O-4); the Phase 24 composition must pass it, and nothing composes the watch before then.

| Value | Meaning |
|-------|---------|
| `CLOSE_POSITION` | A failed check sends the plan to CLOSE_REQUIRED (reduce-only MARKET close). The owner's choice (D085): the Phase 24 composition must pass it |
| `ALERT_ONLY` | A failed check is journaled and alerted; the position is not closed |

### 15.2 LiquidationWatchAction

The four answers of one post-fill check (`LiquidationWatch.check`). The watch is built and tested but not active before Phase 24.

| Value | Meaning |
|-------|---------|
| `OK` | The exchange value passes the strict buffer predicate and agrees with the local price (or the local price is unavailable) |
| `OK_DIFFERS` | The exchange value passes but differs from the local price; both exact prices are journaled for calibration only, no amount in an alert |
| `CLOSE` | The check failed (`LIQUIDATION_TOO_CLOSE_AFTER_FILL` or `LIQUIDATION_UNKNOWN_AFTER_FILL`) under `CLOSE_POSITION` |
| `ALERT_ONLY_FAILED` | The check failed under `ALERT_ONLY` |

### 15.3 Branch code, journal event and alert reasons

| Name | Kind | Meaning |
|------|------|---------|
| `B6_LIQUIDATION_TOO_CLOSE` | protection branch code | The post-fill check failed; the plan enters the existing CLOSE_REQUIRED path with the confirmed stop kept. No new state, edge or order type |
| `MARGIN_CONFIG_CHANGED` | journal event (`src/execution/manager.py`) | The guard sent at least one configuration request; carries the previous and the verified margin type and leverage. Written best effort: a failing journal never changes the outcome. The previous configuration is never restored |
| `MARGIN_CONFIG_UNVERIFIED` | alert reason on a `DIVERGENCE` event | The symbol configuration could not be verified (see 9.3) |
| `LIQUIDATION_PRICE_DIFFERS` | journal reason (no alert) | The exchange and local liquidation prices differ (see 9.3); calibration only, journaled by `PROTECTION_LIQUIDATION_PRICE_DIFFERS`, no alert and no amount in a message |
