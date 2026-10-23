"""Tests for the live risk-input builder (Phase 21, plan 21-11; D-05, D-14 to D-16, F-012).

The builder turns the live equity result, the persisted day row, the day verdict, the counted
reservations and the exchange exposures into the four `evaluate_risk` inputs the manager takes
from `risk_kwargs`. Every expected value is a literal derived by hand in the comments.

Evidence label: executed unit tests [DESIGN]; not wired into execute_approved_plan (Phase 24).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core.types import AccountState
from src.domain.enums import (
    ApprovalResult,
    DailyState,
    ExecutionIntentStatus,
    RejectionReason,
    TradePlanStatus,
)
from src.execution import live_risk_inputs as module
from src.execution import pre_placement
from src.execution.live_risk_inputs import (
    FINAL_PLACEMENT_REFUSALS,
    LiveRiskInputs,
    LiveRiskInputsResult,
    build_live_risk_inputs,
    release_reason_for_approval_status,
    release_reason_for_entry_intent,
    release_reason_for_placement_refusal,
    release_reason_for_plan,
    release_reason_for_protection_state,
)
from src.execution.protection import ProtectionState
from src.risk.daily_loss import DayRiskState, DayStateVerdict
from src.risk.live_equity import LiveEquityResult
from src.risk.portfolio import check_portfolio
from src.risk.reservations import (
    RELEASE_SOURCE_STATUSES,
    CountedReservation,
    ExchangeExposure,
    ReleaseReason,
    ReservationStatus,
)
from src.risk.types import SizedResult

from tests.support.ast_guards import module_imports, wall_clock_calls

MODULE_PATH = Path(module.__file__)
DAY = date(2026, 10, 23)
NEXT_DAY = date(2026, 10, 24)
BASE_AT = datetime(2026, 10, 23, 0, 0, 5, tzinfo=UTC)
NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
RISK_RATE = Decimal("0.005")
UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
DAILY_STOP_BLOCK = RejectionReason.DAILY_STOP_BLOCK.value
HASH = "a" * 64

# Registry rates; against the day base 1000 they are: warning 5, stop 10, cluster 6, aggregate 10.
RATES: dict[str, Any] = {
    "daily_loss_warning_threshold": Decimal("0.005"),
    "daily_loss_stop_threshold": Decimal("0.01"),
    "cluster_cap": Decimal("0.006"),
    "max_aggregate_open_risk": Decimal("0.01"),
    "max_open_positions": 2,
}


def _equity(value: str = "1010") -> LiveEquityResult:
    return LiveEquityResult(
        account_state=AccountState(equity=Decimal(value), risk_rate=RISK_RATE),
        reason_code="OK",
        equity=Decimal(value),
        observed_at_utc=NOW,
    )


def _equity_no_trade() -> LiveEquityResult:
    return LiveEquityResult(
        account_state=None, reason_code=UNCERTAIN, equity=None, observed_at_utc=None
    )


def _day(base: str = "1000", utc_day: date = DAY) -> DayRiskState:
    return DayRiskState(
        utc_day=utc_day, equity_at_day_start=Decimal(base), base_observed_at_utc=BASE_AT
    )


def _verdict(
    state: DailyState | None = DailyState.NORMAL,
    loss: str | None = "2",
    utc_day: date = DAY,
) -> DayStateVerdict:
    if state is None:
        return DayStateVerdict(
            utc_day=utc_day,
            state=None,
            reason_code=UNCERTAIN,
            blocked_reason="DAILY_LOSS_UNKNOWN",
            loss_quote=None,
            latch_now=False,
            alerts_due=(),
        )
    return DayStateVerdict(
        utc_day=utc_day,
        state=state,
        reason_code=DAILY_STOP_BLOCK if state is DailyState.DAILY_STOP else "OK",
        blocked_reason=None,
        loss_quote=None if loss is None else Decimal(loss),
        latch_now=False,
        alerts_due=(),
    )


def _row(
    plan_id: str, symbol: str, side: str, status: ReservationStatus, risk: str
) -> CountedReservation:
    return CountedReservation(
        trade_plan_id=plan_id,
        plan_hash=HASH,
        symbol=symbol,
        position_side=side,
        status=status,
        open_risk=Decimal(risk),
    )


def _abc() -> list[CountedReservation]:
    return [
        _row("A", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "3"),
        _row("B", "ETHUSDT", "LONG", ReservationStatus.PLACED, "2"),
        _row("C", "SOLUSDT", "SHORT", ReservationStatus.OPEN, "4"),
    ]


def _build(**overrides: Any) -> LiveRiskInputsResult:
    kwargs: dict[str, Any] = {
        "equity": _equity(),
        "day": _day(),
        "verdict": _verdict(),
        "counted": _abc(),
        "exchange_exposures": [ExchangeExposure(symbol="SOLUSDT", signed_quantity=Decimal("-0.1"))],
        "candidate_trade_plan_id": "D",
        "parameter_set": RATES,
    }
    kwargs.update(overrides)
    return build_live_risk_inputs(**kwargs)


def _sized(risk: str) -> SizedResult:
    return SizedResult(
        is_no_trade=False,
        quantity=Decimal("1"),
        quantity_before_rounding=Decimal("1"),
        quantity_after_rounding=Decimal("1"),
        quantization_decision="ACCEPTED",
        realized_risk=Decimal(risk),
    )


def _portfolio(inputs: LiveRiskInputs, symbol: str, side: str, risk: str) -> str:
    verdict = check_portfolio(
        sized=_sized(risk),
        candidate_symbol=symbol,
        candidate_position_side=side,
        open_positions=inputs.open_positions,
        daily_loss_quote=inputs.daily_loss_quote,
        parameter_set=inputs.parameter_set,
        now_utc=NOW,
        ttl=timedelta(0),
        positions_reconciled=True,
        constraint_observed_at_utc=NOW,
    )
    return verdict.reason_code


# --------------------------------------------------------------------------- #
# Task 1: the tracer
# --------------------------------------------------------------------------- #


def test_sources_assemble_into_the_four_risk_inputs() -> None:
    result = _build()
    assert result.reason_code == "OK"
    assert result.is_no_trade is False
    inputs = result.inputs
    assert inputs is not None
    assert inputs.account_state.equity == Decimal("1010")
    assert [p.symbol for p in inputs.open_positions] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert [p.open_risk for p in inputs.open_positions] == [
        Decimal("3"),
        Decimal("2"),
        Decimal("4"),
    ]
    assert inputs.daily_loss_quote == Decimal("2")
    # Thresholds come from the day base 1000, not from the current equity 1010.
    assert inputs.parameter_set["daily_loss_stop_threshold"] == Decimal("10")
    assert inputs.parameter_set["daily_loss_warning_threshold"] == Decimal("5")
    assert inputs.parameter_set["cluster_cap"] == Decimal("6")
    assert inputs.parameter_set["max_aggregate_open_risk"] == Decimal("10")
    assert inputs.parameter_set["max_open_positions"] == 2


def test_resting_and_reserved_plans_count_toward_the_caps() -> None:
    inputs = _build().inputs
    assert inputs is not None
    # Three counted rows against a cap of two; BNB LONG with risk 1 hits the cluster cap
    # only if the sum exceeds 6 (3 + 2 + 1 = 6, not above), so the position count decides.
    assert _portfolio(inputs, "BNBUSDT", "LONG", "1") == "MAX_POSITIONS_REJECT"


def test_as_risk_kwargs_has_exactly_the_four_keys() -> None:
    inputs = _build().inputs
    assert inputs is not None
    kwargs = inputs.as_risk_kwargs()
    assert set(kwargs) == {"account_state", "open_positions", "daily_loss_quote", "parameter_set"}
    assert kwargs["account_state"] is inputs.account_state
    assert kwargs["parameter_set"] == inputs.parameter_set


def test_result_couples_reason_to_presence() -> None:
    inputs = _build().inputs
    assert inputs is not None
    with pytest.raises(ValueError):
        LiveRiskInputsResult(inputs=inputs, reason_code=UNCERTAIN)
    with pytest.raises(ValueError):
        LiveRiskInputsResult(inputs=None, reason_code="OK")
    with pytest.raises(ValueError):
        LiveRiskInputsResult(inputs=None, reason_code="MAX_POSITIONS_REJECT")


# --------------------------------------------------------------------------- #
# Task 2: fail closed
# --------------------------------------------------------------------------- #


def test_unknown_equity_is_uncertain() -> None:
    result = _build(equity=_equity_no_trade())
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


def test_missing_day_row_is_uncertain() -> None:
    result = _build(day=None)
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


def test_missing_verdict_is_uncertain() -> None:
    result = _build(verdict=None)
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


def test_verdict_for_another_day_is_uncertain() -> None:
    result = _build(verdict=_verdict(utc_day=NEXT_DAY))
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


def test_blocked_verdict_without_a_state_is_uncertain() -> None:
    result = _build(verdict=_verdict(state=None))
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


def test_verdict_with_a_state_but_no_loss_is_uncertain() -> None:
    result = _build(verdict=_verdict(state=DailyState.NORMAL, loss=None))
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


@pytest.mark.parametrize(
    "drop",
    [
        "daily_loss_warning_threshold",
        "daily_loss_stop_threshold",
        "cluster_cap",
        "max_aggregate_open_risk",
    ],
)
def test_parameter_set_missing_a_threshold_is_uncertain(drop: str) -> None:
    broken = {k: v for k, v in RATES.items() if k != drop}
    result = _build(parameter_set=broken)
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


def test_unexplained_exchange_position_is_uncertain() -> None:
    exposure = ExchangeExposure(symbol="BNBUSDT", signed_quantity=Decimal("1"))
    result = _build(exchange_exposures=[exposure])
    assert result.inputs is None
    assert result.reason_code == UNCERTAIN


@pytest.mark.parametrize("loss", ["0", "3", "50"])
def test_latched_day_blocks_whatever_the_loss(loss: str) -> None:
    result = _build(verdict=_verdict(state=DailyState.DAILY_STOP, loss=loss))
    assert result.inputs is None
    assert result.reason_code == DAILY_STOP_BLOCK


def test_latched_day_with_unknown_loss_still_blocks_as_daily_stop() -> None:
    result = _build(verdict=_verdict(state=DailyState.DAILY_STOP, loss=None))
    assert result.inputs is None
    assert result.reason_code == DAILY_STOP_BLOCK


def test_candidates_own_row_is_excluded_so_an_exact_fit_passes() -> None:
    # Others: ETH LONG 4 (RESERVED). Candidate D: BTC LONG 2, already PLACED. Sized risk 2.
    # Cluster LONG: 4 + 2 = 6 <= 6 passes; counted twice it would be 8 > 6 (Pitfall 2).
    rows = [
        _row("X", "ETHUSDT", "LONG", ReservationStatus.RESERVED, "4"),
        _row("D", "BTCUSDT", "LONG", ReservationStatus.PLACED, "2"),
    ]
    exposure = ExchangeExposure(symbol="BTCUSDT", signed_quantity=Decimal("0.01"))
    inputs = _build(counted=rows, exchange_exposures=[exposure]).inputs
    assert inputs is not None
    assert [p.open_risk for p in inputs.open_positions] == [Decimal("4")]
    assert _portfolio(inputs, "BTCUSDT", "LONG", "2") == "OK"


@pytest.mark.parametrize("current", ["900", "1100"])
def test_thresholds_do_not_move_with_current_equity(current: str) -> None:
    inputs = _build(equity=_equity(current)).inputs
    assert inputs is not None
    assert inputs.account_state.equity == Decimal(current)
    assert inputs.parameter_set["daily_loss_stop_threshold"] == Decimal("10")
    assert inputs.parameter_set["daily_loss_warning_threshold"] == Decimal("5")
    assert inputs.parameter_set["cluster_cap"] == Decimal("6")
    assert inputs.parameter_set["max_aggregate_open_risk"] == Decimal("10")


def test_registry_parameter_set_is_not_mutated() -> None:
    before = dict(RATES)
    _build()
    assert before == RATES


# --------------------------------------------------------------------------- #
# Task 2: release-reason mappings
# --------------------------------------------------------------------------- #

RELEASE = ReleaseReason


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ApprovalResult.EXPIRED, RELEASE.APPROVAL_EXPIRED),
        (ApprovalResult.SKIPPED, RELEASE.APPROVAL_SKIPPED),
        (ApprovalResult.PENDING, None),
        (ApprovalResult.APPROVED, None),
    ],
)
def test_release_reason_for_approval_status(
    status: ApprovalResult, expected: ReleaseReason | None
) -> None:
    assert release_reason_for_approval_status(status) is expected


def test_every_approval_status_is_classified() -> None:
    assert {s for s in ApprovalResult} == {
        ApprovalResult.EXPIRED,
        ApprovalResult.SKIPPED,
        ApprovalResult.PENDING,
        ApprovalResult.APPROVED,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ExecutionIntentStatus.REJECTED, RELEASE.ENTRY_REJECTED),
        (ExecutionIntentStatus.INTENDED, None),
        (ExecutionIntentStatus.SENT, None),
        (ExecutionIntentStatus.ACKED, None),
        (ExecutionIntentStatus.UNKNOWN, None),
    ],
)
def test_release_reason_for_entry_intent(
    status: ExecutionIntentStatus, expected: ReleaseReason | None
) -> None:
    assert release_reason_for_entry_intent(status) is expected


def test_every_entry_intent_status_is_classified() -> None:
    assert len(list(ExecutionIntentStatus)) == 5


@pytest.mark.parametrize("state", list(ProtectionState), ids=lambda s: s.value)
def test_release_reason_for_protection_state(state: ProtectionState) -> None:
    expected: dict[ProtectionState, ReleaseReason] = {
        ProtectionState.ENTRY_ENDED_NO_FILL: RELEASE.ENTRY_ENDED_NO_FILL,
        ProtectionState.FLAT: RELEASE.POSITION_CLOSED,
    }
    assert release_reason_for_protection_state(state) is expected.get(state)


EXPIRY = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
JUST_BEFORE = datetime(2026, 10, 23, 11, 59, 59, 999999, tzinfo=UTC)
LATER = datetime(2026, 10, 23, 12, 0, 1, tzinfo=UTC)


@pytest.mark.parametrize("status", list(TradePlanStatus), ids=lambda s: s.value)
def test_release_reason_for_plan_over_every_status(status: TradePlanStatus) -> None:
    fixed = {
        TradePlanStatus.EXPIRED: RELEASE.PLAN_EXPIRED,
        TradePlanStatus.INVALIDATED: RELEASE.PLAN_INVALIDATED,
        TradePlanStatus.SUPERSEDED: RELEASE.PLAN_SUPERSEDED,
    }
    for now in (JUST_BEFORE, EXPIRY, LATER):
        got = release_reason_for_plan(status=status, expiry_utc=EXPIRY, now_utc=now)
        if status in fixed:
            assert got is fixed[status]
        elif now < EXPIRY:
            assert got is None
        else:
            assert got is RELEASE.PLAN_EXPIRED


def test_approved_plan_never_consumed_is_released_at_exactly_its_expiry() -> None:
    kwargs: dict[str, Any] = {"status": TradePlanStatus.APPROVED, "expiry_utc": EXPIRY}
    assert release_reason_for_plan(now_utc=JUST_BEFORE, **kwargs) is None
    assert release_reason_for_plan(now_utc=EXPIRY, **kwargs) is RELEASE.PLAN_EXPIRED


@pytest.mark.parametrize("which", ["now_utc", "expiry_utc"])
def test_release_reason_for_plan_refuses_a_naive_instant(which: str) -> None:
    kwargs: dict[str, Any] = {
        "status": TradePlanStatus.APPROVED,
        "expiry_utc": EXPIRY,
        "now_utc": NOW,
    }
    kwargs[which] = datetime(2026, 10, 23, 12, 0, 0)
    with pytest.raises(ValueError):
        release_reason_for_plan(**kwargs)


# The classification of every public string constant of pre_placement and every
# RejectionReason value, written out so a new refusal code fails until it is classified.
FINAL = RELEASE.PLACEMENT_REFUSED
PRE_PLACEMENT_EXPECTED: dict[str, ReleaseReason | None] = {
    "PLAN_STATUS_INVALID": FINAL,
    "PLAN_INVALIDATED_BEFORE_PLACEMENT": FINAL,
    "VALIDITY_TOO_SHORT": FINAL,
    "INVALIDATION_INPUT_UNAVAILABLE": None,
    "LIMITS_NOT_CONFIGURED": None,
    "SYMBOL_HAS_POSITION": None,
    "SYMBOL_HAS_OPEN_ORDER": None,
    "UNPROTECTED_POSITION_EXISTS": None,
    "SYMBOL_STATE_UNAVAILABLE": None,
    "MARK_PRICE_UNAVAILABLE": None,
    "MARK_PRICE_CROSSED_STOP": None,
    "MARK_PRICE_OUTSIDE_ZONE": None,
    "LAST_PRICE_UNAVAILABLE": None,
    "LAST_PRICE_CROSSED_STOP": None,
    "LAST_PRICE_OUTSIDE_ZONE": None,
    "HEDGE_MODE_UNSUPPORTED": None,
}


def _public_pre_placement_codes() -> list[str]:
    return sorted(
        name
        for name, value in vars(pre_placement).items()
        if name.isupper() and not name.startswith("_") and isinstance(value, str)
    )


def test_every_public_pre_placement_constant_is_classified() -> None:
    assert _public_pre_placement_codes() == sorted(PRE_PLACEMENT_EXPECTED)


@pytest.mark.parametrize("name", sorted(PRE_PLACEMENT_EXPECTED))
def test_release_reason_for_each_pre_placement_refusal(name: str) -> None:
    code = getattr(pre_placement, name)
    assert release_reason_for_placement_refusal(code) is PRE_PLACEMENT_EXPECTED[name]


def test_final_refusals_are_the_pre_placement_constants() -> None:
    assert FINAL_PLACEMENT_REFUSALS == frozenset(
        {
            pre_placement.PLAN_STATUS_INVALID,
            pre_placement.PLAN_INVALIDATED_BEFORE_PLACEMENT,
            pre_placement.VALIDITY_TOO_SHORT,
        }
    )


# RejectionReason values the manager can return as a refusal: none is a final refusal.
@pytest.mark.parametrize("reason", list(RejectionReason), ids=lambda r: r.value)
def test_no_rejection_reason_is_a_final_refusal(reason: RejectionReason) -> None:
    assert release_reason_for_placement_refusal(reason.value) is None


def test_ok_is_not_a_refusal() -> None:
    assert release_reason_for_placement_refusal("OK") is None


@pytest.mark.parametrize("bad", [None, 1, b"PLAN_STATUS_INVALID"])
def test_placement_refusal_refuses_a_non_string(bad: Any) -> None:
    with pytest.raises(TypeError):
        release_reason_for_placement_refusal(bad)


def test_mappings_refuse_foreign_enum_values() -> None:
    with pytest.raises(TypeError):
        release_reason_for_approval_status("EXPIRED")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        release_reason_for_entry_intent("REJECTED")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        release_reason_for_protection_state("FLAT")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        release_reason_for_plan(status="EXPIRED", expiry_utc=EXPIRY, now_utc=NOW)  # type: ignore[arg-type]


def _all_returnable_reasons() -> set[ReleaseReason]:
    reasons: set[ReleaseReason | None] = set()
    reasons.update(release_reason_for_approval_status(s) for s in ApprovalResult)
    reasons.update(release_reason_for_entry_intent(s) for s in ExecutionIntentStatus)
    reasons.update(release_reason_for_protection_state(s) for s in ProtectionState)
    reasons.update(
        release_reason_for_plan(status=s, expiry_utc=EXPIRY, now_utc=now)
        for s in TradePlanStatus
        for now in (JUST_BEFORE, LATER)
    )
    reasons.update(release_reason_for_placement_refusal(c) for c in FINAL_PLACEMENT_REFUSALS)
    return {r for r in reasons if r is not None}


def test_every_returnable_reason_has_a_release_source() -> None:
    reasons = _all_returnable_reasons()
    assert reasons <= set(RELEASE_SOURCE_STATUSES)
    # All nine reasons are produced by some mapping.
    assert reasons == set(ReleaseReason)


@pytest.mark.parametrize(
    "reason",
    [
        RELEASE.PLAN_EXPIRED,
        RELEASE.PLAN_INVALIDATED,
        RELEASE.PLAN_SUPERSEDED,
        RELEASE.PLACEMENT_REFUSED,
    ],
)
def test_plan_and_placement_reasons_release_unplaced_reservations_only(
    reason: ReleaseReason,
) -> None:
    sources = RELEASE_SOURCE_STATUSES[reason]
    assert ReservationStatus.PLACED not in sources
    assert ReservationStatus.OPEN not in sources


# --------------------------------------------------------------------------- #
# Module hygiene
# --------------------------------------------------------------------------- #


def test_module_reads_no_wall_clock() -> None:
    assert wall_clock_calls(MODULE_PATH) == []


def test_module_imports_no_adapter_persistence_or_sdk() -> None:
    imports = module_imports(MODULE_PATH)
    forbidden = ("src.adapters", "src.persistence", "binance", "httpx", "sqlalchemy")
    assert [m for m in imports if m.startswith(forbidden)] == []
