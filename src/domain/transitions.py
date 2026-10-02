"""Legal state-transition tables (Phase 17 plan 03, DOMN-04, D-20).

Pure module: standard library and ``src.domain.enums`` only. The tables are copied from
GLOSSARY section 11 (the text blocks there are parsed back by ``tests/test_transitions.py``,
so code and documentation cannot drift) and are enforced by ``assert_transition`` inside
the write transaction of the repositories. The terminal rule is also enforced in PostgreSQL
by the terminal-state triggers of migration 0004.

Status: Accepted (D051); drafted as the Phase 17 auto-mode default (research C3) and
confirmed by the user on 2026-10-02. EXECUTION_SPEC section 3 (entry order lifecycle) is the
anchor for the Order machine.

Rules:

- A terminal state is a state with no successors.
- An unchanged state is not a transition. ``assert_transition`` raises for ``old == new``,
  so a repository must treat equal states as an idempotent no-op before calling it.
- Every ``UNKNOWN`` exit for Order and Position must be backed by evidence from Binance (a
  reconcile query over REST or a user-data stream event), never by local inference such as
  a timeout or an operator guess. The tables only say which moves are legal; recording the
  evidence source is deferred to Phase 18 and 20, when the first callers exist.
- ``APPROVED -> SUPERSEDED`` for a TradePlan is deliberately illegal (D051 item (i)):
  ``SUPERSEDED`` means replaced before the human decided.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType

from src.domain.enums import (
    ApprovalResult,
    ExecutionIntentStatus,
    OrderStatus,
    PositionStatus,
    SignalStatus,
    TradePlanStatus,
)


class TransitionKind(str, Enum):
    """The state machines that have a transition table."""

    SIGNAL = "SIGNAL"
    TRADE_PLAN = "TRADE_PLAN"
    ORDER = "ORDER"
    POSITION = "POSITION"
    APPROVAL = "APPROVAL"
    EXECUTION_INTENT = "EXECUTION_INTENT"


class IllegalTransition(ValueError):
    """Raised for a move that is not in the transition table (DOMN-04)."""

    def __init__(self, kind: TransitionKind, old: str, new: str) -> None:
        self.kind = kind
        self.old = old
        self.new = new
        super().__init__(f"illegal {kind.value} transition: {old} -> {new}")


def _table(raw: Mapping[str, tuple[str, ...]]) -> Mapping[str, frozenset[str]]:
    return MappingProxyType({old: frozenset(new) for old, new in raw.items()})


_SIGNAL = _table(
    {
        SignalStatus.DETECTED.value: (
            SignalStatus.NOTIFIED.value,
            SignalStatus.SKIPPED_BUSY.value,
            SignalStatus.EXPIRED.value,
            SignalStatus.INVALIDATED.value,
        ),
        SignalStatus.NOTIFIED.value: (
            SignalStatus.VIEWED.value,
            SignalStatus.APPROVED.value,
            SignalStatus.SKIPPED_USER.value,
            SignalStatus.SKIPPED_BUSY.value,
            SignalStatus.EXPIRED.value,
            SignalStatus.INVALIDATED.value,
        ),
        SignalStatus.VIEWED.value: (
            SignalStatus.APPROVED.value,
            SignalStatus.SKIPPED_USER.value,
            SignalStatus.SKIPPED_BUSY.value,
            SignalStatus.EXPIRED.value,
            SignalStatus.INVALIDATED.value,
        ),
        SignalStatus.APPROVED.value: (),
        SignalStatus.SKIPPED_USER.value: (),
        SignalStatus.SKIPPED_BUSY.value: (),
        SignalStatus.EXPIRED.value: (),
        SignalStatus.INVALIDATED.value: (),
    }
)

_TRADE_PLAN = _table(
    {
        TradePlanStatus.READY.value: (
            TradePlanStatus.APPROVAL_PENDING.value,
            TradePlanStatus.EXPIRED.value,
            TradePlanStatus.INVALIDATED.value,
            TradePlanStatus.SUPERSEDED.value,
        ),
        TradePlanStatus.APPROVAL_PENDING.value: (
            TradePlanStatus.APPROVED.value,
            TradePlanStatus.EXPIRED.value,
            TradePlanStatus.INVALIDATED.value,
            TradePlanStatus.SUPERSEDED.value,
        ),
        TradePlanStatus.APPROVED.value: (
            TradePlanStatus.EXPIRED.value,
            TradePlanStatus.INVALIDATED.value,
        ),
        TradePlanStatus.EXPIRED.value: (),
        TradePlanStatus.INVALIDATED.value: (),
        TradePlanStatus.SUPERSEDED.value: (),
    }
)

_ORDER = _table(
    {
        OrderStatus.PLANNED.value: (
            OrderStatus.SUBMITTING.value,
            OrderStatus.CANCELED.value,
        ),
        OrderStatus.SUBMITTING.value: (
            OrderStatus.NEW.value,
            OrderStatus.REJECTED.value,
            OrderStatus.UNKNOWN.value,
            OrderStatus.CANCELED.value,
        ),
        OrderStatus.NEW.value: (
            OrderStatus.PARTIALLY_FILLED.value,
            OrderStatus.FILLED.value,
            OrderStatus.CANCELED.value,
            OrderStatus.EXPIRED.value,
            OrderStatus.REJECTED.value,
            OrderStatus.UNKNOWN.value,
        ),
        OrderStatus.PARTIALLY_FILLED.value: (
            OrderStatus.FILLED.value,
            OrderStatus.CANCELED.value,
            OrderStatus.EXPIRED.value,
            OrderStatus.UNKNOWN.value,
        ),
        # Reconciliation only: the unknown state is resolved against the exchange.
        OrderStatus.UNKNOWN.value: (
            OrderStatus.NEW.value,
            OrderStatus.PARTIALLY_FILLED.value,
            OrderStatus.FILLED.value,
            OrderStatus.CANCELED.value,
            OrderStatus.EXPIRED.value,
            OrderStatus.REJECTED.value,
        ),
        OrderStatus.FILLED.value: (),
        OrderStatus.CANCELED.value: (),
        OrderStatus.EXPIRED.value: (),
        OrderStatus.REJECTED.value: (),
    }
)

_POSITION = _table(
    {
        PositionStatus.OPEN.value: (
            PositionStatus.CLOSING.value,
            PositionStatus.CLOSED.value,
            PositionStatus.LIQUIDATION_REPORTED.value,
            PositionStatus.UNKNOWN.value,
        ),
        PositionStatus.CLOSING.value: (
            PositionStatus.CLOSED.value,
            PositionStatus.OPEN.value,
            PositionStatus.UNKNOWN.value,
        ),
        PositionStatus.LIQUIDATION_REPORTED.value: (
            PositionStatus.CLOSED.value,
            PositionStatus.UNKNOWN.value,
        ),
        # Reconciliation only: the unknown state is resolved against the exchange.
        PositionStatus.UNKNOWN.value: (
            PositionStatus.OPEN.value,
            PositionStatus.CLOSING.value,
            PositionStatus.CLOSED.value,
            PositionStatus.LIQUIDATION_REPORTED.value,
        ),
        PositionStatus.CLOSED.value: (),
    }
)

_APPROVAL = _table(
    {
        ApprovalResult.PENDING.value: (
            ApprovalResult.APPROVED.value,
            ApprovalResult.SKIPPED.value,
            ApprovalResult.EXPIRED.value,
        ),
        ApprovalResult.APPROVED.value: (),
        ApprovalResult.SKIPPED.value: (),
        ApprovalResult.EXPIRED.value: (),
    }
)

_EXECUTION_INTENT = _table(
    {
        ExecutionIntentStatus.INTENDED.value: (
            ExecutionIntentStatus.SENT.value,
            ExecutionIntentStatus.UNKNOWN.value,
            ExecutionIntentStatus.REJECTED.value,
        ),
        ExecutionIntentStatus.SENT.value: (
            ExecutionIntentStatus.ACKED.value,
            ExecutionIntentStatus.REJECTED.value,
            ExecutionIntentStatus.UNKNOWN.value,
        ),
        ExecutionIntentStatus.UNKNOWN.value: (
            ExecutionIntentStatus.ACKED.value,
            ExecutionIntentStatus.REJECTED.value,
        ),
        ExecutionIntentStatus.ACKED.value: (),
        ExecutionIntentStatus.REJECTED.value: (),
    }
)

LEGAL_TRANSITIONS: Mapping[TransitionKind, Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        TransitionKind.SIGNAL: _SIGNAL,
        TransitionKind.TRADE_PLAN: _TRADE_PLAN,
        TransitionKind.ORDER: _ORDER,
        TransitionKind.POSITION: _POSITION,
        TransitionKind.APPROVAL: _APPROVAL,
        TransitionKind.EXECUTION_INTENT: _EXECUTION_INTENT,
    }
)

# Terminal states are the states with no successors (D-20); derived, never restated.
TERMINAL_STATES: Mapping[TransitionKind, frozenset[str]] = MappingProxyType(
    {
        kind: frozenset(old for old, successors in table.items() if not successors)
        for kind, table in LEGAL_TRANSITIONS.items()
    }
)


def _normalize(state: object) -> str:
    """Accept an Enum member or its string value."""
    if isinstance(state, Enum):
        return str(state.value)
    return str(state)


def is_legal(kind: TransitionKind, old: object, new: object) -> bool:
    """True only for a move listed in the table; an unchanged or unknown state is False."""
    successors = LEGAL_TRANSITIONS[kind].get(_normalize(old))
    return successors is not None and _normalize(new) in successors


def assert_transition(kind: TransitionKind, old: object, new: object) -> None:
    """Raise IllegalTransition unless ``old -> new`` is in the table (DOMN-04).

    An unchanged state is not a transition and raises too; callers treat equal states as an
    idempotent no-op before calling this.
    """
    if not is_legal(kind, old, new):
        raise IllegalTransition(kind, _normalize(old), _normalize(new))
