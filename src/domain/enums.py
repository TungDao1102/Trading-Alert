"""GLOSSARY-canonical domain enums (Phase 3, plan 03-01).

Per D-10: enum values copy GLOSSARY sections 2, 3, 5, 8 verbatim. No
stringly-typed statuses; no invented names — an unknown status is a
load-time error.

The `str, Enum` mixin keeps ORM/JSON `.value` storage trivial while
preserving Enum identity for mypy checks.
"""

from __future__ import annotations

from enum import Enum


class SignalStatus(str, Enum):
    """GLOSSARY §2 — Signal lifecycle states.

    Execution lifecycle states do NOT belong in SignalStatus.
    """

    DETECTED = "DETECTED"
    NOTIFIED = "NOTIFIED"
    VIEWED = "VIEWED"
    APPROVED = "APPROVED"
    SKIPPED_USER = "SKIPPED_USER"
    SKIPPED_BUSY = "SKIPPED_BUSY"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class TradePlanStatus(str, Enum):
    """GLOSSARY §3 — TradePlan lifecycle states."""

    READY = "READY"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalAction(str, Enum):
    """GLOSSARY §4 — Approval actions.

    `VIEWED` is an observation state, not an approval action.
    """

    SIMULATE = "SIMULATE"
    APPROVE = "APPROVE"
    SKIP_USER = "SKIP_USER"
    SKIP_BUSY = "SKIP_BUSY"
    CANCEL = "CANCEL"


class ApprovalResult(str, Enum):
    """Approval result lifecycle (D-10, planner assumption).

    Maps to the approval result lifecycle. The value set
    PENDING, APPROVED, SKIPPED, EXPIRED is the explicit planner
    assumption flagged in plan 03-01 until user confirmation.

    `status` alone answers state (D-11); NULL `acted_at_utc` means
    "transition never happened".
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    """GLOSSARY §5 — Order lifecycle states."""

    PLANNED = "PLANNED"
    SUBMITTING = "SUBMITTING"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class TradeStatus(str, Enum):
    """GLOSSARY §6 — Trade lifecycle states."""

    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"
    UNKNOWN = "UNKNOWN"


class PositionStatus(str, Enum):
    """GLOSSARY §7 — Position lifecycle states."""

    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    LIQUIDATION_REPORTED = "LIQUIDATION_REPORTED"
    UNKNOWN = "UNKNOWN"


class SystemMode(str, Enum):
    """GLOSSARY §8 — System operating modes.

    `LIVE_AUTONOMOUS` is a future architecture mode and is disabled by
    default.
    """

    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE_APPROVAL = "LIVE_APPROVAL"
    SAFE_MODE = "SAFE_MODE"
    LIVE_AUTONOMOUS_DISABLED = "LIVE_AUTONOMOUS_DISABLED"


class RejectionReason(str, Enum):
    """GLOSSARY §9 — Canonical rejection reasons (20 members).

    Do not create synonyms such as `Skipped-User`, `USER_SKIPPED`, and
    `SKIPPED_USER` in different modules. Use the canonical enum names
    above. The five aliases retired in Phase 12 (GLOSSARY 9.2) must not
    return.
    """

    NO_TRADE_REGIME = "NO_TRADE_REGIME"
    RR_TOO_LOW = "RR_TOO_LOW"
    STALE_SETUP = "STALE_SETUP"
    INVALIDATED = "INVALIDATED"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    EXCHANGE_CONSTRAINT = "EXCHANGE_CONSTRAINT"
    DATA_STALE = "DATA_STALE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    # Phase 5 D-05 fine-grained reason codes (one-way, parity-fixture binding).
    # Promote-or-carry decision locked in plan 05-01: enum promotion + GLOSSARY
    # update so every downstream consumer (alerts, journal rows, Telegram payloads)
    # reads from one vocabulary.
    MIN_QTY_REJECT = "MIN_QTY_REJECT"
    NOTIONAL_REJECT = "NOTIONAL_REJECT"
    UTILIZATION_REJECT = "UTILIZATION_REJECT"
    CLUSTER_CAP_REJECT = "CLUSTER_CAP_REJECT"
    AGGREGATE_CAP_REJECT = "AGGREGATE_CAP_REJECT"
    MAX_POSITIONS_REJECT = "MAX_POSITIONS_REJECT"
    DAILY_STOP_BLOCK = "DAILY_STOP_BLOCK"
    STALE_CONSTRAINTS = "STALE_CONSTRAINTS"
    UNCERTAIN_ACCOUNT_STATE = "UNCERTAIN_ACCOUNT_STATE"
    # Phase 12 D-08 cost-guard codes (GLOSSARY 9.1, D046): emitted before quantization.
    STOP_TOO_TIGHT = "STOP_TOO_TIGHT"
    COST_TO_RISK_EXCEEDED = "COST_TO_RISK_EXCEEDED"


class DailyState(str, Enum):
    """GLOSSARY §8 — Daily PnL state machine (D-03).

    Three-state machine: NORMAL → WARNING → DAILY_STOP. The `DAILY_STOP`
    threshold blocks new entries; existing protective exits stay active
    (enforced downstream — risk only emits the block + reason).
    """

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    DAILY_STOP = "DAILY_STOP"


class KillGateState(str, Enum):
    """GLOSSARY section 8.2 - Research kill-gate state (Phase 10 D-03, D030).

    Defined here (not in analytics) so execution enablement can import it
    without importing the analytics package (D016: GLOSSARY is the only
    source of truth for statuses).

    - WITHIN_BUDGET: fewer than 3 independently specified families tested OR
      fewer than 6 calendar months elapsed - keep researching.
    - PASSING_CANDIDATE: a family holds a recorded passing decision; evidence
      exists; does NOT authorize live.
    - INSUFFICIENT_EDGE: terminal; at least 3 families tested AND at least 6
      months elapsed AND none passing. A valid outcome; keeps live disabled
      and never auto-clears.
    """

    WITHIN_BUDGET = "WITHIN_BUDGET"
    PASSING_CANDIDATE = "PASSING_CANDIDATE"
    INSUFFICIENT_EDGE = "INSUFFICIENT_EDGE"


# --------------------------------------------------------------------------- #
# Phase 4 plan 04-01 (D-06) — promoted enums.
# --------------------------------------------------------------------------- #


class Direction(str, Enum):
    """GLOSSARY — Signal direction (D-06 promotion)."""

    LONG = "LONG"
    SHORT = "SHORT"


class SetupType(str, Enum):
    """GLOSSARY — Setup type per family (D-06 promotion).

    Values cover all three Phase-4 families (trend-pullback,
    breakout-retest, range-mr) with LONG/SHORT variants. The exact
    tokens are the canonical setup names; unknown values raise at load.
    """

    TREND_PULLBACK_LONG = "TREND_PULLBACK_LONG"
    TREND_PULLBACK_SHORT = "TREND_PULLBACK_SHORT"
    BREAKOUT_RETEST_LONG = "BREAKOUT_RETEST_LONG"
    BREAKOUT_RETEST_SHORT = "BREAKOUT_RETEST_SHORT"
    RANGE_MR_LONG = "RANGE_MR_LONG"
    RANGE_MR_SHORT = "RANGE_MR_SHORT"


class SourceTimeframe(str, Enum):
    """GLOSSARY — Source candle timeframe (D-06 promotion).

    Values copy the exact timeframe spellings used in
    `tests/fixtures/phase3/candles.csv` (lowercase "1h", "4h", "1m").
    """

    M1 = "1m"
    H1 = "1h"
    H4 = "4h"


class EntryModel(str, Enum):
    """GLOSSARY — Trade plan entry model (D-06 promotion)."""

    LIMIT_ZONE = "LIMIT_ZONE"
    MARKET = "MARKET"


class OrderRole(str, Enum):
    """GLOSSARY — Order role in plan (D-06 promotion)."""

    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT_1 = "TAKE_PROFIT_1"
    TAKE_PROFIT_2 = "TAKE_PROFIT_2"


class QuantizationDecision(str, Enum):
    """GLOSSARY — Quantization decision (D-06 promotion, D-09 deferral).

    `DEFERRED_TO_RISK` is the V1 default — Phase 5 owns stepSize math.
    """

    DEFERRED_TO_RISK = "DEFERRED_TO_RISK"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ExecutionIntentStatus(str, Enum):
    """Write-ahead execution intent lifecycle (Phase 17, D-13/D-14).

    INTENDED -> SENT -> ACKED | REJECTED | UNKNOWN. An intent left INTENDED, SENT
    or UNKNOWN after a restart is unresolved: it is never re-sent blindly, only
    resolved by querying the exchange by its deterministic client id.
    GLOSSARY entries land in plan 03.
    """

    INTENDED = "INTENDED"
    SENT = "SENT"
    ACKED = "ACKED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class ApprovalConsumptionStatus(str, Enum):
    """Explicit approval consumption state (Phase 17, D-16/D-21, research C8).

    Never inferred from the nullable `consumed_at_utc`. GLOSSARY entries land in plan 03.
    """

    UNCONSUMED = "UNCONSUMED"
    CONSUMED = "CONSUMED"


class LiveInputsStatus(str, Enum):
    """Whether a persisted constraint snapshot carries every live input (Phase 17, D-19).

    INCOMPLETE while margin type, leverage or equity still hold the UNKNOWN sentinel.
    GLOSSARY entries land in plan 03.
    """

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class SystemStateKey(str, Enum):
    """Keys of the durable system-state event log (Phase 17, D-22).

    GLOSSARY entries land in plan 03.
    """

    SAFE_MODE = "SAFE_MODE"
    LIVE_ENABLEMENT = "LIVE_ENABLEMENT"
    KILL_GATE = "KILL_GATE"
