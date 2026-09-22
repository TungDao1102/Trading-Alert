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
    """GLOSSARY §9 — Canonical rejection reasons.

    Do not create synonyms such as `Skipped-User`, `USER_SKIPPED`, and
    `SKIPPED_USER` in different modules. Use the canonical enum names
    above.
    """

    NO_TRADE_REGIME = "NO_TRADE_REGIME"
    RR_TOO_LOW = "RR_TOO_LOW"
    STALE_SETUP = "STALE_SETUP"
    INVALIDATED = "INVALIDATED"
    RISK_LIMIT = "RISK_LIMIT"
    CORRELATED_RISK_LIMIT = "CORRELATED_RISK_LIMIT"
    DAILY_STOP = "DAILY_STOP"
    QUANTIZATION_REJECT = "QUANTIZATION_REJECT"
    MIN_NOTIONAL_REJECT = "MIN_NOTIONAL_REJECT"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    EXCHANGE_CONSTRAINT = "EXCHANGE_CONSTRAINT"
    DATA_STALE = "DATA_STALE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
