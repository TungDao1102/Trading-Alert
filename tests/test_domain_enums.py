"""Tests for the GLOSSARY-canonical domain enums (Phase 3, plan 03-01).

Per D-10: enum values copy GLOSSARY sections 2, 3, 5, 8 verbatim. No
stringly-typed statuses; no invented names — an unknown status is a
load-time error.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/domain/enums.py` is implemented.

Phase 4 plan 04-01 (D-06) extends the enum set with Direction,
SetupType, SourceTimeframe, EntryModel, OrderRole, QuantizationDecision.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from src.domain import (
    Direction,
    EntryModel,
    OrderRole,
    QuantizationDecision,
    SetupType,
    SourceTimeframe,
)
from src.domain.enums import (
    ApprovalAction,
    DailyState,
    OrderStatus,
    PositionStatus,
    RejectionReason,
    SignalStatus,
    SystemMode,
    TradePlanStatus,
    TradeStatus,
)
from src.risk.types import PortfolioVerdict, SizedResult

_REPO_ROOT = Path(__file__).resolve().parents[1]

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
    """Beh. 8: RejectionReason enum values are exactly the GLOSSARY section 9.1 set.

    GLOSSARY section 9.1 (20 canonical codes; the five deprecated aliases were
    removed in Phase 12, D-09, and are recorded in section 9.2):
        NO_TRADE_REGIME, RR_TOO_LOW, STALE_SETUP, INVALIDATED,
        INSUFFICIENT_MARGIN, EXCHANGE_CONSTRAINT, DATA_STALE,
        RECONCILIATION_REQUIRED, APPROVAL_EXPIRED, MIN_QTY_REJECT,
        NOTIONAL_REJECT, UTILIZATION_REJECT, CLUSTER_CAP_REJECT,
        AGGREGATE_CAP_REJECT, MAX_POSITIONS_REJECT, DAILY_STOP_BLOCK,
        STALE_CONSTRAINTS, UNCERTAIN_ACCOUNT_STATE, STOP_TOO_TIGHT,
        COST_TO_RISK_EXCEEDED
    """
    expected = {
        "NO_TRADE_REGIME",
        "RR_TOO_LOW",
        "STALE_SETUP",
        "INVALIDATED",
        "INSUFFICIENT_MARGIN",
        "EXCHANGE_CONSTRAINT",
        "DATA_STALE",
        "RECONCILIATION_REQUIRED",
        "APPROVAL_EXPIRED",
        # Phase 5 D-05 fine-grained codes (plan 05-01).
        "MIN_QTY_REJECT",
        "NOTIONAL_REJECT",
        "UTILIZATION_REJECT",
        "CLUSTER_CAP_REJECT",
        "AGGREGATE_CAP_REJECT",
        "MAX_POSITIONS_REJECT",
        "DAILY_STOP_BLOCK",
        "STALE_CONSTRAINTS",
        "UNCERTAIN_ACCOUNT_STATE",
        # Phase 12 D-08 cost-guard codes.
        "STOP_TOO_TIGHT",
        "COST_TO_RISK_EXCEEDED",
    }
    actual = {member.value for member in RejectionReason}
    assert actual == expected
    assert len(RejectionReason) == 20


@pytest.mark.parametrize(
    "retired",
    [
        "RISK_LIMIT",
        "CORRELATED_RISK_LIMIT",
        "DAILY_STOP",
        "QUANTIZATION_REJECT",
        "MIN_NOTIONAL_REJECT",
    ],
)
def test_retired_rejection_aliases_are_not_enum_values(retired: str) -> None:
    """Phase 12 D-09: the five deprecated aliases are gone from RejectionReason."""
    assert retired not in {member.value for member in RejectionReason}
    assert not hasattr(RejectionReason, retired)


def test_daily_state_daily_stop_survives_alias_removal() -> None:
    """DAILY_STOP stays a valid DailyState value (GLOSSARY section 8.1)."""
    assert DailyState.DAILY_STOP.value == "DAILY_STOP"


def _reject_sized(reason_code: str) -> SizedResult:
    return SizedResult(
        is_no_trade=True,
        quantity=None,
        quantity_before_rounding=Decimal("0"),
        quantity_after_rounding=Decimal("0"),
        quantization_decision="REJECTED",
        realized_risk=Decimal("0"),
        reason_code=reason_code,
    )


@pytest.mark.parametrize("code", ["STOP_TOO_TIGHT", "COST_TO_RISK_EXCEEDED"])
def test_sized_result_accepts_new_cost_guard_codes(code: str) -> None:
    """Phase 12 D-08: SizedResult validates against the enum-derived vocabulary."""
    result = _reject_sized(code)
    assert result.reason_code == code
    assert result.is_no_trade is True
    assert result.quantity is None


def test_sized_result_rejects_invented_reason_code() -> None:
    with pytest.raises(ValueError):
        _reject_sized("STOP_TOO_CLOSE")


@pytest.mark.parametrize("code", ["STOP_TOO_TIGHT", "COST_TO_RISK_EXCEEDED"])
def test_portfolio_verdict_accepts_new_cost_guard_codes(code: str) -> None:
    verdict = PortfolioVerdict(
        is_no_trade=True, sized=None, reason_code=code, daily_state=DailyState.NORMAL
    )
    assert verdict.reason_code == code
    with pytest.raises(ValueError):
        PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code="STOP_TOO_CLOSE",
            daily_state=DailyState.NORMAL,
        )


def test_glossary_section_9_1_block_equals_enum() -> None:
    """The GLOSSARY 9.1 text block parses to the same 20 tokens as the enum."""
    lines = (_REPO_ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8").splitlines()
    start = lines.index("### 9.1 Canonical codes")
    fence = "`" * 3
    open_idx = lines.index(fence + "text", start)
    close_idx = lines.index(fence, open_idx + 1)
    tokens = [line.strip() for line in lines[open_idx + 1 : close_idx] if line.strip()]
    assert len(tokens) == len(set(tokens)) == 20
    assert set(tokens) == {member.value for member in RejectionReason}


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


# --------------------------------------------------------------------------- #
# Phase 4 plan 04-01 (D-06) — promoted enums.
# --------------------------------------------------------------------------- #


def test_direction_values_match_glossary() -> None:
    """Beh. 12: Direction enum values are LONG and SHORT (verbatim)."""
    assert {m.value for m in Direction} == {"LONG", "SHORT"}
    assert Direction.LONG.value == "LONG"
    assert Direction.SHORT.value == "SHORT"


def test_direction_unknown_raises_value_error() -> None:
    """Beh. 13: Direction("BOGUS") raises ValueError (load-time error)."""
    with pytest.raises(ValueError):
        Direction("BOGUS")


def test_direction_str_mixin_compares_to_string() -> None:
    """Beh. 14: Direction.LONG == "LONG" (str mixin)."""
    assert Direction.LONG == "LONG"
    assert Direction.SHORT == "SHORT"


def test_setup_type_values_match_glossary() -> None:
    """Beh. 15: SetupType enum values cover all three families."""
    expected = {
        "TREND_PULLBACK_LONG",
        "TREND_PULLBACK_SHORT",
        "BREAKOUT_RETEST_LONG",
        "BREAKOUT_RETEST_SHORT",
        "RANGE_MR_LONG",
        "RANGE_MR_SHORT",
    }
    assert {m.value for m in SetupType} == expected


def test_setup_type_unknown_raises_value_error() -> None:
    """Beh. 16: SetupType("UNKNOWN") raises ValueError."""
    with pytest.raises(ValueError):
        SetupType("UNKNOWN")


def test_source_timeframe_values_match_phase3_fixture_spelling() -> None:
    """Beh. 17: SourceTimeframe values copy phase-3 candles.csv spellings.

    The phase-3 fixture uses "1h" (lowercase) for the 1H timeframe.
    """
    assert {m.value for m in SourceTimeframe} == {"1m", "1h", "4h"}
    assert SourceTimeframe.H1.value == "1h"
    assert SourceTimeframe.H4.value == "4h"
    assert SourceTimeframe.M1.value == "1m"


def test_source_timeframe_unknown_raises_value_error() -> None:
    """Beh. 18: SourceTimeframe("5m") raises ValueError."""
    with pytest.raises(ValueError):
        SourceTimeframe("5m")


def test_entry_model_values_match_glossary() -> None:
    """Beh. 19: EntryModel enum values are LIMIT_ZONE and MARKET."""
    assert {m.value for m in EntryModel} == {"LIMIT_ZONE", "MARKET"}


def test_entry_model_unknown_raises_value_error() -> None:
    """Beh. 20: EntryModel("STOP") raises ValueError."""
    with pytest.raises(ValueError):
        EntryModel("STOP")


def test_order_role_values_match_glossary() -> None:
    """Beh. 21: OrderRole enum values cover entry/SL/TP1/TP2."""
    expected = {"ENTRY", "STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"}
    assert {m.value for m in OrderRole} == expected


def test_order_role_unknown_raises_value_error() -> None:
    """Beh. 22: OrderRole("TAKE_PROFIT_3") raises ValueError."""
    with pytest.raises(ValueError):
        OrderRole("TAKE_PROFIT_3")


def test_quantization_decision_values_match_glossary() -> None:
    """Beh. 23: QuantizationDecision enum values are DEFERRED_TO_RISK, ACCEPTED, REJECTED."""
    expected = {"DEFERRED_TO_RISK", "ACCEPTED", "REJECTED"}
    assert {m.value for m in QuantizationDecision} == expected


def test_quantization_decision_unknown_raises_value_error() -> None:
    """Beh. 24: QuantizationDecision("UNKNOWN") raises ValueError."""
    with pytest.raises(ValueError):
        QuantizationDecision("UNKNOWN")


def test_signal_constructs_with_direction_enum() -> None:
    """Beh. 25: Signal accepts Direction enum (str-subclass compatibility).

    The str+Enum mixin means Direction.LONG is a str subclass, so
    Signal(direction=Direction.LONG, ...) constructs without explicit
    .value coercion.
    """
    from datetime import UTC, datetime

    from src.domain.enums import SignalStatus
    from src.domain.signal import Signal

    sig = Signal(
        signal_id="abc",
        strategy_id="trend-pullback",
        strategy_version="v1.0.0",
        parameter_set_id="baseline-v1",
        parameter_set_hash="0" * 64,
        symbol="BTCUSDT",
        direction=Direction.LONG,
        setup_type=SetupType.TREND_PULLBACK_LONG,
        source_timeframe=SourceTimeframe.H1,
        source_candle_close_utc=datetime(2026, 9, 19, 0, 59, 59, tzinfo=UTC),
        detected_at_utc=datetime(2026, 9, 19, 0, 59, 59, tzinfo=UTC),
        status=SignalStatus.DETECTED,
        expires_at_utc=datetime(2026, 9, 19, 4, 59, 59, tzinfo=UTC),
    )
    assert sig.direction == "LONG"
    assert sig.setup_type == "TREND_PULLBACK_LONG"
    assert sig.source_timeframe == "1h"


# --------------------------------------------------------------------------- #
# Phase 10 plan 10-02 (D-03, D030) — KillGateState, GLOSSARY §8.2.
# --------------------------------------------------------------------------- #


def test_kill_gate_state_values_match_glossary_8_2() -> None:
    """KillGateState is exactly the three GLOSSARY §8.2 tokens, value == name."""
    from src.domain.enums import KillGateState

    assert {m.value for m in KillGateState} == {
        "WITHIN_BUDGET",
        "PASSING_CANDIDATE",
        "INSUFFICIENT_EDGE",
    }
    assert all(m.value == m.name for m in KillGateState)
    assert KillGateState("WITHIN_BUDGET") is KillGateState.WITHIN_BUDGET
    assert KillGateState.INSUFFICIENT_EDGE == "INSUFFICIENT_EDGE"
    with pytest.raises(ValueError):
        KillGateState("NOT_A_STATE")
