"""Tests for the GLOSSARY-canonical domain enums (Phase 3, plan 03-01).

Per D-10: enum values copy GLOSSARY sections 2, 3, 5, 8 verbatim. No
stringly-typed statuses; no invented names — an unknown status is a
load-time error.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/domain/enums.py` is implemented.
"""

from __future__ import annotations

import pytest
from src.domain.enums import (
    ApprovalAction,
    OrderStatus,
    PositionStatus,
    RejectionReason,
    SignalStatus,
    SystemMode,
    TradePlanStatus,
    TradeStatus,
)

# --------------------------------------------------------------------------- #
# Test 1 — SignalStatus values match GLOSSARY §2 verbatim.
# --------------------------------------------------------------------------- #


def test_signal_status_values_match_glossary_section_2() -> None:
    """Beh. 1: SignalStatus enum values are exactly the GLOSSARY §2 set.

    GLOSSARY §2 (verbatim):
        DETECTED, NOTIFIED, VIEWED, APPROVED, SKIPPED_USER,
        SKIPPED_BUSY, EXPIRED, INVALIDATED
    """
    expected = {
        "DETECTED",
        "NOTIFIED",
        "VIEWED",
        "APPROVED",
        "SKIPPED_USER",
        "SKIPPED_BUSY",
        "EXPIRED",
        "INVALIDATED",
    }
    actual = {member.value for member in SignalStatus}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 2 — TradePlanStatus values match GLOSSARY §3 verbatim.
# --------------------------------------------------------------------------- #


def test_trade_plan_status_values_match_glossary_section_3() -> None:
    """Beh. 2: TradePlanStatus enum values are exactly the GLOSSARY §3 set.

    GLOSSARY §3 (verbatim):
        READY, APPROVAL_PENDING, APPROVED, EXPIRED, INVALIDATED, SUPERSEDED
    """
    expected = {
        "READY",
        "APPROVAL_PENDING",
        "APPROVED",
        "EXPIRED",
        "INVALIDATED",
        "SUPERSEDED",
    }
    actual = {member.value for member in TradePlanStatus}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 3 — ApprovalAction values match GLOSSARY §4 verbatim.
# --------------------------------------------------------------------------- #


def test_approval_action_values_match_glossary_section_4() -> None:
    """Beh. 3: ApprovalAction enum values are exactly the GLOSSARY §4 set.

    GLOSSARY §4 (verbatim):
        SIMULATE, APPROVE, SKIP_USER, SKIP_BUSY, CANCEL
    """
    expected = {"SIMULATE", "APPROVE", "SKIP_USER", "SKIP_BUSY", "CANCEL"}
    actual = {member.value for member in ApprovalAction}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 4 — OrderStatus values match GLOSSARY §5 verbatim.
# --------------------------------------------------------------------------- #


def test_order_status_values_match_glossary_section_5() -> None:
    """Beh. 4: OrderStatus enum values are exactly the GLOSSARY §5 set.

    GLOSSARY §5 (verbatim):
        PLANNED, SUBMITTING, NEW, PARTIALLY_FILLED, FILLED, CANCELED,
        EXPIRED, REJECTED, UNKNOWN
    """
    expected = {
        "PLANNED",
        "SUBMITTING",
        "NEW",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELED",
        "EXPIRED",
        "REJECTED",
        "UNKNOWN",
    }
    actual = {member.value for member in OrderStatus}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 5 — TradeStatus values match GLOSSARY §6 verbatim.
# --------------------------------------------------------------------------- #


def test_trade_status_values_match_glossary_section_6() -> None:
    """Beh. 5: TradeStatus enum values are exactly the GLOSSARY §6 set.

    GLOSSARY §6 (verbatim):
        PENDING, OPEN, CLOSED, ABORTED, UNKNOWN
    """
    expected = {"PENDING", "OPEN", "CLOSED", "ABORTED", "UNKNOWN"}
    actual = {member.value for member in TradeStatus}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 6 — PositionStatus values match GLOSSARY §7 verbatim.
# --------------------------------------------------------------------------- #


def test_position_status_values_match_glossary_section_7() -> None:
    """Beh. 6: PositionStatus enum values are exactly the GLOSSARY §7 set.

    GLOSSARY §7 (verbatim):
        OPEN, CLOSING, CLOSED, LIQUIDATION_REPORTED, UNKNOWN
    """
    expected = {"OPEN", "CLOSING", "CLOSED", "LIQUIDATION_REPORTED", "UNKNOWN"}
    actual = {member.value for member in PositionStatus}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 7 — SystemMode values match GLOSSARY §8 verbatim.
# --------------------------------------------------------------------------- #


def test_system_mode_values_match_glossary_section_8() -> None:
    """Beh. 7: SystemMode enum values are exactly the GLOSSARY §8 set.

    GLOSSARY §8 (verbatim):
        RESEARCH, BACKTEST, PAPER, LIVE_APPROVAL, SAFE_MODE,
        LIVE_AUTONOMOUS_DISABLED
    """
    expected = {
        "RESEARCH",
        "BACKTEST",
        "PAPER",
        "LIVE_APPROVAL",
        "SAFE_MODE",
        "LIVE_AUTONOMOUS_DISABLED",
    }
    actual = {member.value for member in SystemMode}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 8 — RejectionReason values match GLOSSARY §9 verbatim.
# --------------------------------------------------------------------------- #


def test_rejection_reason_values_match_glossary_section_9() -> None:
    """Beh. 8: RejectionReason enum values are exactly the GLOSSARY §9 set.

    GLOSSARY §9 (verbatim):
        NO_TRADE_REGIME, RR_TOO_LOW, STALE_SETUP, INVALIDATED, RISK_LIMIT,
        CORRELATED_RISK_LIMIT, DAILY_STOP, QUANTIZATION_REJECT,
        MIN_NOTIONAL_REJECT, INSUFFICIENT_MARGIN, EXCHANGE_CONSTRAINT,
        DATA_STALE, RECONCILIATION_REQUIRED, APPROVAL_EXPIRED
    """
    expected = {
        "NO_TRADE_REGIME",
        "RR_TOO_LOW",
        "STALE_SETUP",
        "INVALIDATED",
        "RISK_LIMIT",
        "CORRELATED_RISK_LIMIT",
        "DAILY_STOP",
        "QUANTIZATION_REJECT",
        "MIN_NOTIONAL_REJECT",
        "INSUFFICIENT_MARGIN",
        "EXCHANGE_CONSTRAINT",
        "DATA_STALE",
        "RECONCILIATION_REQUIRED",
        "APPROVAL_EXPIRED",
    }
    actual = {member.value for member in RejectionReason}
    assert actual == expected


# --------------------------------------------------------------------------- #
# Test 9 — Unknown status raises ValueError (D-10 boundary contract).
# --------------------------------------------------------------------------- #


def test_unknown_signal_status_raises_value_error() -> None:
    """Beh. 9: SignalStatus("UNKNOWN_VALUE") raises ValueError.

    D-10: unknown status at any boundary raises ValueError via Enum(value)
    coercion. No stringly-typed statuses anywhere.
    """
    with pytest.raises(ValueError):
        SignalStatus("UNKNOWN_VALUE")


def test_unknown_order_status_raises_value_error() -> None:
    """Beh. 9b: OrderStatus("UNKNOWN_VALUE") raises ValueError."""
    with pytest.raises(ValueError):
        OrderStatus("UNKNOWN_VALUE")


# --------------------------------------------------------------------------- #
# Test 10 — .value storage contract (ORM boundary).
# --------------------------------------------------------------------------- #


def test_signal_status_value_storage_contract() -> None:
    """Beh. 10: SignalStatus.DETECTED.value == "DETECTED" (ORM storage).

    The mapper stores `status.value` (the string) in the row; the
    `from_row` path reconstructs the Enum via `SignalStatus(value)`.
    """
    assert SignalStatus.DETECTED.value == "DETECTED"
    assert SignalStatus.APPROVED.value == "APPROVED"
    assert SignalStatus.INVALIDATED.value == "INVALIDATED"


# --------------------------------------------------------------------------- #
# Test 11 — str Enum mixin: enum members compare equal to their string value.
# --------------------------------------------------------------------------- #


def test_signal_status_str_mixin_compares_to_string() -> None:
    """Beh. 11: SignalStatus.DETECTED == "DETECTED" (str mixin).

    The `str, Enum` mixin keeps ORM/JSON `.value` storage trivial while
    preserving Enum identity for mypy checks.
    """
    assert SignalStatus.DETECTED == "DETECTED"
    assert SignalStatus.APPROVED == "APPROVED"
