"""Tests for the portfolio-cap reservation inputs (Phase 21, plan 21-06; D-15, D-16, D-17).

`reservation_verdict` judges a reservation request through the shared `check_portfolio` against
the counted reservation rows, never counting the candidate's own row twice. The thresholds are
ABSOLUTE quote amounts. Every expected value is a literal derived by hand in the comments.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import DailyState, RejectionReason
from src.risk import reservations as reservations_module
from src.risk.reservations import (
    COUNTED_STATUSES,
    RELEASE_SOURCE_STATUSES,
    CountedReservation,
    ExchangeExposure,
    ReleaseReason,
    ReservationRequest,
    ReservationStatus,
    open_positions_from_reservations,
    reservation_verdict,
)

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64

# Absolute thresholds: cluster cap 6, aggregate cap 10, at most 2 positions, warning 5, stop 10.
THRESHOLDS: dict[str, Any] = {
    "max_open_positions": 2,
    "max_aggregate_open_risk": Decimal("10"),
    "cluster_cap": Decimal("6"),
    "daily_loss_warning_threshold": Decimal("5"),
    "daily_loss_stop_threshold": Decimal("10"),
}


def _counted(
    plan_id: str,
    symbol: str,
    side: str,
    status: ReservationStatus,
    risk: str,
    plan_hash: str = HASH_A,
) -> CountedReservation:
    return CountedReservation(
        trade_plan_id=plan_id,
        plan_hash=plan_hash,
        symbol=symbol,
        position_side=side,
        status=status,
        open_risk=Decimal(risk),
    )


def _request(
    symbol: str,
    side: str,
    risk: str,
    plan_id: str = "plan-req",
    plan_hash: str = HASH_D,
    quantity: str = "1",
) -> ReservationRequest:
    return ReservationRequest(
        trade_plan_id=plan_id,
        plan_hash=plan_hash,
        symbol=symbol,
        position_side=side,
        quantity=Decimal(quantity),
        realized_risk=Decimal(risk),
    )


def _verdict(
    request: ReservationRequest,
    counted: tuple[CountedReservation, ...],
    *,
    daily_loss: Decimal | None = Decimal("0"),
    latched: bool = False,
) -> Any:
    return reservation_verdict(
        request=request,
        counted=counted,
        daily_loss_quote=daily_loss,
        stop_latched=latched,
        thresholds=THRESHOLDS,
        now_utc=NOW,
    )


A_RESERVED = _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "5")


# --------------------------------------------------------------------------- #
# Task 1 - reservation_verdict over check_portfolio
# --------------------------------------------------------------------------- #


def test_cluster_cap_rejects_when_sum_exceeds_cap() -> None:
    # BTC LONG 5 + ETH LONG 2 = 7 > cluster cap 6.
    verdict = _verdict(_request("ETHUSDT", "LONG", "2"), (A_RESERVED,))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.CLUSTER_CAP_REJECT.value
    assert verdict.sized is None


def test_aggregate_cap_passes_exactly_at_the_cap() -> None:
    # BNB is outside the cluster; aggregate 5 + 5 = 10 == cap 10 passes (strictly greater rejects).
    verdict = _verdict(_request("BNBUSDT", "LONG", "5"), (A_RESERVED,))
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"
    assert verdict.sized is not None
    # The reserved amount is the sized realized risk (Pitfall 9).
    assert verdict.sized.realized_risk == Decimal("5")
    assert verdict.sized.quantity == Decimal("1")


def test_aggregate_cap_rejects_one_cent_over() -> None:
    # 5 + 5.01 = 10.01 > 10.
    verdict = _verdict(_request("BNBUSDT", "LONG", "5.01"), (A_RESERVED,))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.AGGREGATE_CAP_REJECT.value


def test_third_position_hits_the_position_count() -> None:
    counted = (
        _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "1"),
        _counted("plan-b", "BNBUSDT", "SHORT", ReservationStatus.PLACED, "1", HASH_B),
    )
    # Both caps fit (SOL LONG 1: cluster 1+1=2 <= 6; aggregate 3 <= 10); two rows >= max 2.
    verdict = _verdict(_request("SOLUSDT", "LONG", "1"), counted)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.MAX_POSITIONS_REJECT.value


def test_own_reservation_is_excluded_so_an_exact_fit_still_passes() -> None:
    # At placement the request's own row is already counted. Judged against {A 5, own 5} it
    # would be 5 + 5 + 5 = 15 > 10; with the own row excluded it is 5 + 5 = 10 and passes.
    own = _counted("plan-req", "BNBUSDT", "LONG", ReservationStatus.RESERVED, "5", HASH_D)
    verdict = _verdict(_request("BNBUSDT", "LONG", "5"), (A_RESERVED, own))
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"


def test_own_reservation_excluded_from_the_position_count() -> None:
    # Two other rows would hit the count; own + one other must not (1 other < max 2).
    own = _counted("plan-req", "BNBUSDT", "LONG", ReservationStatus.RESERVED, "1", HASH_D)
    other = _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "1")
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (other, own))
    assert verdict.is_no_trade is False


def test_latched_day_refuses_with_daily_stop_even_when_everything_fits() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), latched=True)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.DAILY_STOP_BLOCK.value
    assert verdict.daily_state is DailyState.DAILY_STOP
    assert verdict.sized is None


def test_unknown_daily_loss_refuses_with_uncertain_account_state() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), daily_loss=None)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.UNCERTAIN_ACCOUNT_STATE.value


def test_daily_loss_at_the_stop_threshold_refuses_through_check_portfolio() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), daily_loss=Decimal("10"))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.DAILY_STOP_BLOCK.value


def test_empty_counted_with_loss_below_warning_passes_normal() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), daily_loss=Decimal("4.99"))
    assert verdict.is_no_trade is False
    assert verdict.daily_state is DailyState.NORMAL


def test_counted_order_does_not_change_the_verdict() -> None:
    b = _counted("plan-b", "ETHUSDT", "LONG", ReservationStatus.PLACED, "1", HASH_B)
    request = _request("SOLUSDT", "LONG", "1")
    assert _verdict(request, (A_RESERVED, b)) == _verdict(request, (b, A_RESERVED))


@pytest.mark.parametrize(
    "overrides",
    [
        {"realized_risk": Decimal("0")},
        {"realized_risk": Decimal("-1")},
        {"quantity": Decimal("0")},
        {"quantity": Decimal("-1")},
        {"position_side": "BOTH"},
        {"position_side": "long"},
        {"plan_hash": "a" * 63},
        {"plan_hash": "A" * 64},
        {"plan_hash": "g" * 64},
        {"symbol": ""},
        {"trade_plan_id": ""},
    ],
)
def test_reservation_request_refuses_invalid_fields(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "trade_plan_id": "plan-req",
        "plan_hash": HASH_D,
        "symbol": "BNBUSDT",
        "position_side": "LONG",
        "quantity": Decimal("1"),
        "realized_risk": Decimal("1"),
    }
    fields.update(overrides)
    with pytest.raises(ValueError):
        ReservationRequest(**fields)


@pytest.mark.parametrize("field", ["realized_risk", "quantity"])
def test_reservation_request_refuses_a_non_decimal_amount(field: str) -> None:
    fields: dict[str, Any] = {
        "trade_plan_id": "plan-req",
        "plan_hash": HASH_D,
        "symbol": "BNBUSDT",
        "position_side": "LONG",
        "quantity": Decimal("1"),
        "realized_risk": Decimal("1"),
    }
    fields[field] = 1
    with pytest.raises(TypeError):
        ReservationRequest(**fields)


def test_reservation_request_refuses_a_non_finite_amount() -> None:
    with pytest.raises(ValueError):
        _request("BNBUSDT", "LONG", "NaN")
    with pytest.raises(ValueError):
        _request("BNBUSDT", "LONG", "Infinity")


def test_module_is_pure_stdlib_domain_core_risk_only() -> None:
    path = Path(reservations_module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_roots = {"src.domain", "src.core", "src.risk"}
    stdlib = set(__import__("sys").stdlib_module_names)
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names = ["src.risk"]
            elif node.module:
                names = [node.module]
        for name in names:
            root = name.split(".")[0]
            assert (
                root in stdlib
                or root == "__future__"
                or any(name == a or name.startswith(a + ".") for a in allowed_roots)
            ), f"disallowed import {name}"


def test_module_reads_no_clock_and_builds_no_float() -> None:
    path = Path(reservations_module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id != "float", "float constructor"
            if isinstance(func, ast.Attribute):
                assert func.attr not in {"now", "utcnow", "today", "time", "monotonic"}, func.attr


# --------------------------------------------------------------------------- #
# Task 2 - the open-position view
# --------------------------------------------------------------------------- #


def _three_rows() -> tuple[CountedReservation, ...]:
    return (
        _counted("plan-c", "SOLUSDT", "SHORT", ReservationStatus.OPEN, "4", HASH_C),
        _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "3"),
        _counted("plan-b", "ETHUSDT", "LONG", ReservationStatus.PLACED, "2", HASH_B),
    )


def test_view_counts_reserved_placed_and_open_sorted() -> None:
    positions = open_positions_from_reservations(
        counted=_three_rows(),
        exclude_trade_plan_id="plan-d",
        exchange_exposures=(ExchangeExposure("SOLUSDT", Decimal("-0.1")),),
    )
    assert positions is not None
    assert [(p.symbol, p.position_side, p.open_risk) for p in positions] == [
        ("BTCUSDT", "LONG", Decimal("3")),
        ("ETHUSDT", "LONG", Decimal("2")),
        ("SOLUSDT", "SHORT", Decimal("4")),
    ]
    assert all(p.daily_pnl_contribution == Decimal("0") for p in positions)


def test_view_excludes_the_named_plan() -> None:
    positions = open_positions_from_reservations(
        counted=_three_rows(), exclude_trade_plan_id="plan-b", exchange_exposures=()
    )
    assert positions is not None
    assert [p.symbol for p in positions] == ["BTCUSDT", "SOLUSDT"]


def test_view_sorts_ties_by_trade_plan_id() -> None:
    rows = (
        _counted("plan-z", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "2"),
        _counted("plan-y", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "1", HASH_B),
    )
    positions = open_positions_from_reservations(
        counted=rows, exclude_trade_plan_id="none", exchange_exposures=()
    )
    assert positions is not None
    assert [p.open_risk for p in positions] == [Decimal("1"), Decimal("2")]


def test_unexplained_exchange_position_makes_the_view_unknown() -> None:
    assert (
        open_positions_from_reservations(
            counted=_three_rows(),
            exclude_trade_plan_id="plan-d",
            exchange_exposures=(ExchangeExposure("BNBUSDT", Decimal("0.5")),),
        )
        is None
    )


def test_exposure_on_the_wrong_side_is_unexplained() -> None:
    assert (
        open_positions_from_reservations(
            counted=_three_rows(),
            exclude_trade_plan_id="plan-d",
            exchange_exposures=(ExchangeExposure("SOLUSDT", Decimal("0.1")),),
        )
        is None
    )


def test_reserved_row_alone_does_not_explain_an_exchange_position() -> None:
    assert (
        open_positions_from_reservations(
            counted=_three_rows(),
            exclude_trade_plan_id="plan-d",
            exchange_exposures=(ExchangeExposure("BTCUSDT", Decimal("0.1")),),
        )
        is None
    )


def test_the_excluded_row_still_explains_an_exposure() -> None:
    # At placement the candidate's own row is PLACED/OPEN and explains its own exposure.
    positions = open_positions_from_reservations(
        counted=_three_rows(),
        exclude_trade_plan_id="plan-b",
        exchange_exposures=(ExchangeExposure("ETHUSDT", Decimal("1")),),
    )
    assert positions is not None
    assert [p.symbol for p in positions] == ["BTCUSDT", "SOLUSDT"]


def test_zero_exposure_is_ignored() -> None:
    positions = open_positions_from_reservations(
        counted=(),
        exclude_trade_plan_id="plan-d",
        exchange_exposures=(ExchangeExposure("BNBUSDT", Decimal("0")),),
    )
    assert positions == ()


@pytest.mark.parametrize("status", [ReservationStatus.REQUESTED, ReservationStatus.RELEASED])
def test_counted_reservation_refuses_an_uncounted_status(status: ReservationStatus) -> None:
    with pytest.raises(ValueError):
        _counted("plan-a", "BTCUSDT", "LONG", status, "1")


def test_counted_reservation_refuses_negative_risk_and_bad_side() -> None:
    with pytest.raises(ValueError):
        _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "-1")
    with pytest.raises(ValueError):
        _counted("plan-a", "BTCUSDT", "BOTH", ReservationStatus.RESERVED, "1")


def test_exchange_exposure_validates_its_fields() -> None:
    with pytest.raises(ValueError):
        ExchangeExposure("", Decimal("1"))
    with pytest.raises(TypeError):
        ExchangeExposure("BTCUSDT", 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ExchangeExposure("BTCUSDT", Decimal("NaN"))


def test_enum_members_are_pinned() -> None:
    assert {s.value for s in ReservationStatus} == {
        "REQUESTED",
        "RESERVED",
        "PLACED",
        "OPEN",
        "RELEASED",
    }
    assert {r.value for r in ReleaseReason} == {
        "APPROVAL_EXPIRED",
        "APPROVAL_SKIPPED",
        "PLAN_EXPIRED",
        "PLAN_INVALIDATED",
        "PLAN_SUPERSEDED",
        "PLACEMENT_REFUSED",
        "ENTRY_REJECTED",
        "ENTRY_ENDED_NO_FILL",
        "POSITION_CLOSED",
    }
    assert COUNTED_STATUSES == frozenset(
        {ReservationStatus.RESERVED, ReservationStatus.PLACED, ReservationStatus.OPEN}
    )


def test_release_source_statuses_literal_oracle() -> None:
    s = ReservationStatus
    r = ReleaseReason
    expected = {
        r.APPROVAL_SKIPPED: frozenset({s.REQUESTED}),
        r.APPROVAL_EXPIRED: frozenset({s.REQUESTED}),
        r.PLAN_EXPIRED: frozenset({s.REQUESTED, s.RESERVED}),
        r.PLAN_INVALIDATED: frozenset({s.REQUESTED, s.RESERVED}),
        r.PLAN_SUPERSEDED: frozenset({s.REQUESTED, s.RESERVED}),
        r.PLACEMENT_REFUSED: frozenset({s.RESERVED}),
        r.ENTRY_REJECTED: frozenset({s.RESERVED, s.PLACED}),
        r.ENTRY_ENDED_NO_FILL: frozenset({s.PLACED}),
        r.POSITION_CLOSED: frozenset({s.PLACED, s.OPEN}),  # WR-10: a missed first fill
    }
    assert dict(RELEASE_SOURCE_STATUSES) == expected


def test_every_status_but_released_has_an_exit_and_released_is_never_a_source() -> None:
    union: set[ReservationStatus] = set()
    for sources in RELEASE_SOURCE_STATUSES.values():
        assert ReservationStatus.RELEASED not in sources
        union |= sources
    assert union == set(ReservationStatus) - {ReservationStatus.RELEASED}
    assert set(RELEASE_SOURCE_STATUSES) == set(ReleaseReason)


def test_release_source_statuses_is_read_only() -> None:
    with pytest.raises(TypeError):
        RELEASE_SOURCE_STATUSES[ReleaseReason.PLAN_EXPIRED] = frozenset()  # type: ignore[index]


# --------------------------------------------------------------------------------------
# Plan 22-08: the optional margin trio of a request (D-14, amendment A2)
# --------------------------------------------------------------------------------------
def _margin_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "trade_plan_id": "plan-req",
        "plan_hash": HASH_D,
        "symbol": "BTCUSDT",
        "position_side": "LONG",
        "quantity": Decimal("0.01"),
        "realized_risk": Decimal("4"),
    }
    fields.update(overrides)
    return fields


def test_a_request_without_the_margin_trio_is_the_phase_21_form() -> None:
    request = ReservationRequest(**_margin_fields())

    assert request.required_margin is None
    assert request.margin_entry_price is None
    assert request.margin_leverage is None


def test_a_request_with_the_whole_margin_trio_keeps_it() -> None:
    # 0.01 x 80000 / 5 = 160.
    request = ReservationRequest(
        **_margin_fields(
            required_margin=Decimal("160"),
            margin_entry_price=Decimal("80000"),
            margin_leverage=5,
        )
    )

    assert request.required_margin == Decimal("160")
    assert request.margin_entry_price == Decimal("80000")
    assert request.margin_leverage == 5


def test_margin_for_reservation_is_quantity_times_price_over_leverage() -> None:
    from src.risk.reservations import margin_for_reservation

    def margin(quantity: str, price: str, leverage: int) -> Decimal:
        return margin_for_reservation(
            quantity=Decimal(quantity), price=Decimal(price), leverage=leverage
        )

    assert margin("0.01", "80000", 5) == Decimal("160")
    assert margin("0.1", "3000", 10) == Decimal("30")
    assert margin("2.415", "102", 5) == Decimal("49.266")
    assert margin("1", "1", 1) == Decimal("1")
    # A quotient that is not a finite decimal is rounded UP at the 18th digit: never understated.
    third = margin("1", "1", 3)
    assert third == Decimal("0.333333333333333334")
    assert third > Decimal(1) / Decimal(3)
    assert margin("0.01", "80000", 3) == Decimal("266.666666666666666667")


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": 0.01},
        {"price": 80000},
        {"quantity": Decimal("0")},
        {"price": Decimal("-1")},
        {"quantity": Decimal("NaN")},
        {"price": Decimal("Infinity")},
        {"leverage": 0},
        {"leverage": True},
        {"leverage": 5.0},
    ],
)
def test_margin_for_reservation_refuses_malformed_inputs(bad: dict[str, Any]) -> None:
    from src.risk.reservations import margin_for_reservation

    fields: dict[str, Any] = {"quantity": Decimal("0.01"), "price": Decimal("80000"), "leverage": 5}
    fields.update(bad)
    with pytest.raises((TypeError, ValueError)):
        margin_for_reservation(**fields)


@pytest.mark.parametrize(
    "required",
    [
        Decimal("0.000001"),  # a stored understatement would over-admit (22-REVIEW WR-07)
        Decimal("159.999999999999999999"),
        Decimal("160.000000000000000001"),
        Decimal("800"),  # the notional, not the margin
    ],
)
def test_a_request_whose_required_margin_is_not_quantity_x_price_over_leverage_is_refused(
    required: Decimal,
) -> None:
    with pytest.raises(ValueError, match="required_margin must equal"):
        ReservationRequest(
            **_margin_fields(
                required_margin=required,
                margin_entry_price=Decimal("80000"),
                margin_leverage=5,
            )
        )


def test_a_request_with_a_leverage_that_does_not_divide_evenly_carries_the_rounded_up_margin() -> (
    None
):
    request = ReservationRequest(
        **_margin_fields(
            required_margin=Decimal("266.666666666666666667"),
            margin_entry_price=Decimal("80000"),
            margin_leverage=3,
        )
    )
    assert request.required_margin == Decimal("266.666666666666666667")
    with pytest.raises(ValueError, match="required_margin must equal"):
        ReservationRequest(
            **_margin_fields(
                required_margin=Decimal("266.666666666666666666"),  # rounded down: understated
                margin_entry_price=Decimal("80000"),
                margin_leverage=3,
            )
        )


@pytest.mark.parametrize(
    "partial",
    [
        {"required_margin": Decimal("160")},
        {"margin_entry_price": Decimal("80000")},
        {"margin_leverage": 5},
        {"required_margin": Decimal("160"), "margin_entry_price": Decimal("80000")},
        {"required_margin": Decimal("160"), "margin_leverage": 5},
        {"margin_entry_price": Decimal("80000"), "margin_leverage": 5},
    ],
)
def test_a_request_with_a_partial_margin_trio_is_refused(partial: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ReservationRequest(**_margin_fields(**partial))


@pytest.mark.parametrize(
    "bad",
    [
        {"required_margin": Decimal("0")},
        {"required_margin": Decimal("-1")},
        {"required_margin": Decimal("NaN")},
        {"required_margin": Decimal("Infinity")},
        {"margin_entry_price": Decimal("0")},
        {"margin_entry_price": Decimal("-80000")},
        {"margin_leverage": 0},
        {"margin_leverage": -3},
    ],
)
def test_a_request_with_a_non_positive_or_non_finite_margin_is_refused(
    bad: dict[str, Any],
) -> None:
    trio: dict[str, Any] = {
        "required_margin": Decimal("160"),
        "margin_entry_price": Decimal("80000"),
        "margin_leverage": 5,
    }
    trio.update(bad)
    with pytest.raises(ValueError):
        ReservationRequest(**_margin_fields(**trio))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_margin", 160),
        ("required_margin", 160.0),
        ("margin_entry_price", "80000"),
        ("margin_leverage", True),
        ("margin_leverage", Decimal("5")),
        ("margin_leverage", 5.0),
        ("margin_leverage", "5"),
    ],
)
def test_a_request_with_a_wrongly_typed_margin_value_is_refused(field: str, value: Any) -> None:
    trio: dict[str, Any] = {
        "required_margin": Decimal("160"),
        "margin_entry_price": Decimal("80000"),
        "margin_leverage": 5,
    }
    trio[field] = value
    with pytest.raises(TypeError):
        ReservationRequest(**_margin_fields(**trio))
