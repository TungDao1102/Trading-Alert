"""Tests for the pure available-margin predicate (Phase 22, plan 22-04; D-13, criterion 3, F-966).

The check answers one question: does the exchange's free margin cover the new order plus every
other claim on margin? Oracles are literal Decimals; no expectation is computed by the code under
test. The -2019 shape below is a recorded Demo payload (demo-observed, not mainnet, D-19): 10 BTC
at 78570.9 at leverage 20 against an availableBalance of 4998.39137539.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from src.domain.enums import Direction, RejectionReason
from src.risk import margin_check
from src.risk.live_equity import AccountEquityReading
from src.risk.margin_check import (
    AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED,
    BLOCKED_HEDGE_MODE,
    BLOCKED_MULTI_ASSETS_MODE,
    BLOCKED_READING_UNUSABLE,
    AvailableMarginCheck,
    MarginClaim,
    MarginVerdict,
    check_available_margin,
    estimated_fees,
    estimated_open_loss,
    free_margin_basis,
    margin_verdict,
    other_claims_margin,
    required_initial_margin,
)
from src.risk.reservations import ReservationStatus

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = REPO_ROOT / "src" / "risk" / "margin_check.py"

INSUFFICIENT = "INSUFFICIENT_MARGIN"
UNCERTAIN = "UNCERTAIN_ACCOUNT_STATE"
RATE = Decimal("0.0004")
T = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
BEFORE = T - timedelta(seconds=5)
AFTER = T + timedelta(seconds=5)
DEMO_AVAILABLE = Decimal("4998.39137539")


def _verdict(**overrides: object) -> MarginVerdict:
    """The small passing plan: 0.01 at 80000, leverage 5, rates 0.0004 each, headroom 500 bps."""
    kwargs: dict[str, object] = {
        "available_balance": Decimal("1000"),
        "quantity": Decimal("0.01"),
        "limit_price": Decimal("80000"),
        "mark_price": Decimal("80000"),
        "side": Direction.LONG,
        "leverage": 5,
        "fee_rate_entry": RATE,
        "fee_rate_exit": RATE,
        "others_margin": Decimal("0"),
        "headroom_bps": 500,
    }
    kwargs.update(overrides)
    return margin_verdict(**kwargs)  # type: ignore[arg-type]


# --- required_initial_margin ------------------------------------------------------------------


def test_recorded_demo_shape_initial_margin() -> None:
    margin = required_initial_margin(quantity=Decimal("10"), price=Decimal("78570.9"), leverage=20)
    assert margin == Decimal("39285.45")


def test_initial_margin_small_plan() -> None:
    margin = required_initial_margin(quantity=Decimal("0.01"), price=Decimal("80000"), leverage=5)
    assert margin == Decimal("160")


@pytest.mark.parametrize("leverage", [True, 0, -3, Decimal("5"), 5.0, "5", None])
def test_initial_margin_rejects_bad_leverage(leverage: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        required_initial_margin(
            quantity=Decimal("1"),
            price=Decimal("100"),
            leverage=leverage,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "quantity, price",
    [
        (Decimal("0"), Decimal("100")),
        (Decimal("-1"), Decimal("100")),
        (Decimal("1"), Decimal("0")),
        (Decimal("1"), Decimal("NaN")),
        (Decimal("Infinity"), Decimal("100")),
        (1, Decimal("100")),
        (Decimal("1"), 100.0),
    ],
)
def test_initial_margin_rejects_bad_quantity_or_price(quantity: object, price: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        required_initial_margin(
            quantity=quantity,  # type: ignore[arg-type]
            price=price,  # type: ignore[arg-type]
            leverage=5,
        )


# --- estimated_fees ---------------------------------------------------------------------------


def test_estimated_fees_literal() -> None:
    fees = estimated_fees(
        quantity=Decimal("0.01"),
        price=Decimal("80000"),
        fee_rate_entry=Decimal("0.0004"),
        fee_rate_exit=Decimal("0.0004"),
    )
    assert fees == Decimal("0.64")


def test_estimated_fees_zero_rates_are_zero() -> None:
    fees = estimated_fees(
        quantity=Decimal("1"),
        price=Decimal("100"),
        fee_rate_entry=Decimal("0"),
        fee_rate_exit=Decimal("0"),
    )
    assert fees == Decimal("0")


@pytest.mark.parametrize(
    "entry, exit_",
    [(Decimal("-0.0001"), RATE), (RATE, Decimal("-0.0001")), (RATE, Decimal("NaN")), (RATE, 0)],
)
def test_estimated_fees_rejects_bad_rates(entry: object, exit_: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        estimated_fees(
            quantity=Decimal("1"),
            price=Decimal("100"),
            fee_rate_entry=entry,  # type: ignore[arg-type]
            fee_rate_exit=exit_,  # type: ignore[arg-type]
        )


# --- estimated_open_loss ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "side, limit, mark, expected",
    [
        (Direction.LONG, "101", "100", "2"),  # buy above the mark: marketable, loses at once
        (Direction.LONG, "99", "100", "0"),  # resting buy below the mark: no open loss
        (Direction.LONG, "100", "100", "0"),
        (Direction.SHORT, "99", "100", "2"),  # sell below the mark
        (Direction.SHORT, "101", "100", "0"),
        (Direction.SHORT, "100", "100", "0"),
    ],
)
def test_estimated_open_loss(side: Direction, limit: str, mark: str, expected: str) -> None:
    loss = estimated_open_loss(
        quantity=Decimal("2"),
        limit_price=Decimal(limit),
        mark_price=Decimal(mark),
        side=side,
    )
    assert loss == Decimal(expected)


def test_estimated_open_loss_rejects_unknown_side() -> None:
    with pytest.raises(ValueError):
        estimated_open_loss(
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            mark_price=Decimal("100"),
            side="BUY",
        )


# --- margin_verdict: the tracer ---------------------------------------------------------------


def test_recorded_demo_2019_shape_is_refused_insufficient_margin() -> None:
    verdict = margin_verdict(
        available_balance=DEMO_AVAILABLE,
        quantity=Decimal("10"),
        limit_price=Decimal("78570.9"),
        mark_price=Decimal("78570.9"),
        side=Direction.LONG,
        leverage=20,
        fee_rate_entry=RATE,
        fee_rate_exit=RATE,
        others_margin=Decimal("0"),
        headroom_bps=1,
    )
    assert verdict.ok is False
    assert verdict.reason_code == INSUFFICIENT
    assert verdict.required > verdict.available  # type: ignore[operator]
    assert verdict.available == DEMO_AVAILABLE
    # 39285.45 margin + 628.5672 fees = 39914.0172; headroom 1 bps = 3.99140172
    assert verdict.required == Decimal("39918.00860172")


def test_passing_plan_needs_margin_fees_and_headroom_equality_passes() -> None:
    # need 160 + 0.64 = 160.64; headroom 500 bps = 8.032; total 168.672.
    verdict = _verdict(available_balance=Decimal("168.672"))
    assert verdict.ok is True
    assert verdict.reason_code == "OK"
    assert verdict.required == Decimal("168.672")
    assert verdict.available == Decimal("168.672")


def test_one_unit_short_of_equality_fails() -> None:
    verdict = _verdict(available_balance=Decimal("168.671999"))
    assert verdict.ok is False
    assert verdict.reason_code == INSUFFICIENT
    assert verdict.required == Decimal("168.672")


def test_negative_free_margin_is_insufficient_not_an_error() -> None:
    verdict = _verdict(available_balance=Decimal("-5"))
    assert verdict.ok is False
    assert verdict.reason_code == INSUFFICIENT


def test_open_loss_of_a_marketable_limit_is_part_of_the_need() -> None:
    # Buy limit 80100 over a mark of 80000: open loss (80100-80000) x 0.01 = 1.
    # margin 801/5... the limit price is the margin price: 0.01 x 80100 / 5 = 160.2;
    # fees 801 x 0.0008 = 0.6408; need 160.2 + 0.6408 + 1 = 161.8408; headroom 0 bps is refused,
    # so use 1 bps: 0.01618408; total 161.85698408.
    verdict = _verdict(
        available_balance=Decimal("161.85698408"),
        limit_price=Decimal("80100"),
        mark_price=Decimal("80000"),
        headroom_bps=1,
    )
    assert verdict.ok is True
    assert verdict.required == Decimal("161.85698408")


def test_reason_codes_are_the_existing_rejection_reasons() -> None:
    assert INSUFFICIENT == RejectionReason.INSUFFICIENT_MARGIN.value
    assert UNCERTAIN == RejectionReason.UNCERTAIN_ACCOUNT_STATE.value


# --- headroom ---------------------------------------------------------------------------------


@pytest.mark.parametrize("headroom", [True, 0, -1, Decimal("5"), 5.0, "5", None])
def test_headroom_must_be_a_positive_int(headroom: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _verdict(headroom_bps=headroom)


# --- MarginVerdict ----------------------------------------------------------------------------


def test_verdict_ok_requires_reason_ok() -> None:
    with pytest.raises(ValueError):
        MarginVerdict(
            ok=True, reason_code=INSUFFICIENT, required=Decimal("1"), available=Decimal("2")
        )


def test_verdict_refusal_requires_a_rejection_reason() -> None:
    with pytest.raises(ValueError):
        MarginVerdict(ok=False, reason_code="OK", required=Decimal("2"), available=Decimal("1"))
    with pytest.raises(ValueError):
        MarginVerdict(ok=False, reason_code="NOPE", required=Decimal("2"), available=Decimal("1"))


def test_verdict_rejects_float_amounts() -> None:
    with pytest.raises(TypeError):
        MarginVerdict(ok=True, reason_code="OK", required=1.0, available=Decimal("2"))  # type: ignore[arg-type]


# --- purity and no-default signature ----------------------------------------------------------


def test_leverage_fee_rates_and_headroom_are_required_keywords() -> None:
    required = {
        required_initial_margin: ("leverage",),
        estimated_fees: ("fee_rate_entry", "fee_rate_exit"),
        margin_verdict: ("leverage", "fee_rate_entry", "fee_rate_exit", "headroom_bps"),
    }
    for func, names in required.items():
        params = inspect.signature(func).parameters
        for name in names:
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert params[name].default is inspect.Parameter.empty


def test_module_reads_no_wall_clock() -> None:
    assert wall_clock_calls(MODULE) == []


def test_module_builds_no_float() -> None:
    assert float_constructor_calls(MODULE) == []
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)


def test_module_imports_only_stdlib_and_pure_layers() -> None:
    forbidden = (
        "src.adapters",
        "src.backtest",
        "src.execution",
        "src.persistence",
        "src.paper",
        "src.approval",
        "src.reconcile",
        "src.data",
        "src.db",
        "src.ops",
        "src.analytics",
        "src.research",
        "binance*",
        "polars",
        "pandas",
        "numpy",
        "pydantic",
        "sqlalchemy",
        "httpx",
        "requests",
        "aiohttp",
    )
    assert forbidden_imports(MODULE, forbidden) == []


def test_module_holds_no_quote_asset_literal() -> None:
    source = MODULE.read_text(encoding="utf-8")
    for name in ("USDT", "USDC", "BUSD", "FDUSD"):
        assert name not in source


def test_module_numeric_literals_are_only_zero_one_and_the_bps_denominator() -> None:
    allowed = {0, 1, 10000}
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if isinstance(node.value, bool):
                continue
            assert node.value in allowed, node.value
    assert margin_check.BASIS_POINT_DENOMINATOR == 10000


# --- MarginClaim ------------------------------------------------------------------------------


def _claim(
    plan: str = "P2",
    status: ReservationStatus = ReservationStatus.RESERVED,
    margin: Decimal | None = Decimal("50"),
    placed_at: datetime | None = None,
) -> MarginClaim:
    return MarginClaim(
        trade_plan_id=plan, status=status, required_margin=margin, placed_at_utc=placed_at
    )


@pytest.mark.parametrize(
    "status",
    [
        ReservationStatus.REQUESTED,
        ReservationStatus.OPEN,
        ReservationStatus.RELEASED,
    ],
)
def test_claim_accepts_only_reserved_or_placed(status: ReservationStatus) -> None:
    with pytest.raises(ValueError):
        _claim(status=status, placed_at=BEFORE)


def test_claim_margin_is_positive_decimal_or_none() -> None:
    assert _claim(margin=None).required_margin is None
    for bad in (Decimal("0"), Decimal("-1"), Decimal("NaN")):
        with pytest.raises(ValueError):
            _claim(margin=bad)
    for bad_type in (50, 50.0, "50"):
        with pytest.raises(TypeError):
            _claim(margin=bad_type)  # type: ignore[arg-type]


def test_placed_claim_requires_an_aware_utc_placement_time() -> None:
    with pytest.raises(ValueError):
        _claim(status=ReservationStatus.PLACED, placed_at=None)
    with pytest.raises(ValueError):
        _claim(status=ReservationStatus.PLACED, placed_at=datetime(2026, 10, 24, 12, 0, 0))
    with pytest.raises(ValueError):
        _claim(
            status=ReservationStatus.PLACED,
            placed_at=datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone(timedelta(hours=7))),
        )
    assert _claim(status=ReservationStatus.PLACED, placed_at=BEFORE).placed_at_utc == BEFORE


def test_reserved_claim_may_carry_no_placement_time_and_unknown_margin() -> None:
    claim = _claim(margin=None, placed_at=None)
    assert claim.status is ReservationStatus.RESERVED


def test_claim_needs_a_plan_id() -> None:
    with pytest.raises(ValueError):
        _claim(plan="")


# --- free_margin_basis ------------------------------------------------------------------------


def test_free_margin_basis_is_available_balance_today() -> None:
    basis = free_margin_basis(
        available_balance=Decimal("123.45"), total_open_order_initial_margin=Decimal("40")
    )
    assert basis == Decimal("123.45")


def test_free_margin_basis_returns_a_negative_value_as_is() -> None:
    basis = free_margin_basis(
        available_balance=Decimal("-7"), total_open_order_initial_margin=Decimal("0")
    )
    assert basis == Decimal("-7")


@pytest.mark.parametrize("bad", [1, 1.5, "1", None, Decimal("NaN"), Decimal("Infinity")])
def test_free_margin_basis_validates_both_arguments(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        free_margin_basis(
            available_balance=bad,  # type: ignore[arg-type]
            total_open_order_initial_margin=Decimal("0"),
        )
    with pytest.raises((TypeError, ValueError)):
        free_margin_basis(
            available_balance=Decimal("1"),
            total_open_order_initial_margin=bad,  # type: ignore[arg-type]
        )


# --- other_claims_margin ----------------------------------------------------------------------


def _two_claims(placed_at: datetime) -> list[MarginClaim]:
    return [
        _claim(plan="P2", status=ReservationStatus.RESERVED, margin=Decimal("50")),
        _claim(
            plan="P3",
            status=ReservationStatus.PLACED,
            margin=Decimal("30"),
            placed_at=placed_at,
        ),
    ]


@pytest.mark.parametrize(
    "netted, placed_at, expected",
    [
        (False, BEFORE, "80"),  # netting off (the state before D085): the PLACED claim counts
        (True, BEFORE, "50"),  # the exchange already shows it in availableBalance
        (True, AFTER, "80"),  # placed after the reading: the exchange has not shown it yet
        (False, AFTER, "80"),
        (True, T, "50"),  # equality is not strictly after the reading
    ],
)
def test_other_claims_margin_netting(netted: bool, placed_at: datetime, expected: str) -> None:
    total = other_claims_margin(
        claims=_two_claims(placed_at),
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=netted,
    )
    assert total == Decimal(expected)


@pytest.mark.parametrize("netted", [False, True])
def test_reserved_claims_are_always_counted(netted: bool) -> None:
    total = other_claims_margin(
        claims=[_claim(margin=Decimal("50"))],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=netted,
    )
    assert total == Decimal("50")


@pytest.mark.parametrize("netted", [False, True])
def test_the_candidates_own_row_is_never_counted(netted: bool) -> None:
    total = other_claims_margin(
        claims=[
            _claim(plan="P1", margin=Decimal("999")),
            _claim(
                plan="P1",
                status=ReservationStatus.PLACED,
                margin=Decimal("999"),
                placed_at=AFTER,
            ),
            _claim(plan="P2", margin=Decimal("7")),
        ],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=netted,
    )
    assert total == Decimal("7")


def test_no_claims_is_zero() -> None:
    total = other_claims_margin(
        claims=[],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=False,
    )
    assert total == Decimal("0")


@pytest.mark.parametrize("netted", [False, True])
def test_an_unknown_counted_margin_makes_the_sum_unknown(netted: bool) -> None:
    total = other_claims_margin(
        claims=[_claim(plan="P2", margin=Decimal("50")), _claim(plan="P3", margin=None)],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=netted,
    )
    assert total is None


def test_an_unknown_margin_of_a_netted_placed_claim_is_not_counted() -> None:
    total = other_claims_margin(
        claims=[
            _claim(plan="P2", margin=Decimal("50")),
            _claim(plan="P3", status=ReservationStatus.PLACED, margin=None, placed_at=BEFORE),
        ],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=True,
    )
    assert total == Decimal("50")


def test_an_unknown_margin_of_the_excluded_plan_is_ignored() -> None:
    total = other_claims_margin(
        claims=[_claim(plan="P1", margin=None), _claim(plan="P2", margin=Decimal("5"))],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=False,
    )
    assert total == Decimal("5")


def test_other_claims_margin_rejects_a_naive_reading_time() -> None:
    with pytest.raises(ValueError):
        other_claims_margin(
            claims=[],
            exclude_trade_plan_id="P1",
            reading_observed_at_utc=datetime(2026, 10, 24, 12, 0, 0),
            resting_orders_netted=False,
        )


# --- the verdict with other claims and with unknowns ------------------------------------------


def test_verdict_with_other_claims_adds_them_to_the_need() -> None:
    # need 160 + 0.64 + 50 = 210.64; headroom 500 bps = 10.532; total 221.172.
    passing = _verdict(available_balance=Decimal("221.172"), others_margin=Decimal("50"))
    assert passing.ok is True
    assert passing.required == Decimal("221.172")
    failing = _verdict(available_balance=Decimal("221.171999"), others_margin=Decimal("50"))
    assert failing.ok is False
    assert failing.reason_code == INSUFFICIENT


def test_unknown_other_claims_are_uncertain_account_state_not_insufficient() -> None:
    verdict = _verdict(available_balance=Decimal("1000000"), others_margin=None)
    assert verdict.ok is False
    assert verdict.reason_code == UNCERTAIN
    assert verdict.required is None
    assert verdict.available == Decimal("1000000")


def test_end_to_end_claims_to_verdict() -> None:
    others = other_claims_margin(
        claims=[_claim(margin=Decimal("50"))],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED,
    )
    free = free_margin_basis(
        available_balance=Decimal("221.172"), total_open_order_initial_margin=Decimal("0")
    )
    assert _verdict(available_balance=free, others_margin=others).ok is True


# --- the netting constant ---------------------------------------------------------------------


def test_netting_constant_is_true_since_the_owner_decision_d085() -> None:
    # The owner Demo run of 2026-10-24 (two samples, demo-observed, not mainnet) showed that
    # availableBalance nets a resting order; the owner flipped the constant (DECISIONS D085).
    assert AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED is True
    # With it, a PLACED claim placed at or before the reading is not counted a second time, and a
    # PLACED claim placed AFTER the reading still counts (the reading cannot show it yet).
    reserved = _claim(plan="P2", margin=Decimal("50"))
    early = _claim(plan="P3", status=ReservationStatus.PLACED, placed_at=T - timedelta(seconds=1))
    at_reading = _claim(plan="P4", status=ReservationStatus.PLACED, placed_at=T)
    late = _claim(plan="P5", status=ReservationStatus.PLACED, placed_at=T + timedelta(seconds=1))
    total = other_claims_margin(
        claims=[reserved, early, at_reading, late],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=T,
        resting_orders_netted=AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED,
    )
    assert total == Decimal("100")  # the RESERVED claim and the late PLACED claim only


def test_resting_orders_netted_is_a_required_keyword() -> None:
    params = inspect.signature(other_claims_margin).parameters
    assert params["resting_orders_netted"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["resting_orders_netted"].default is inspect.Parameter.empty


def test_netting_constant_is_a_final_true_literal_in_source() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED"
        and node.value is not None
    ]
    assert len(values) == 1
    assert isinstance(values[0], ast.Constant)
    assert values[0].value is True


# --- check_available_margin (plan 22-10; D-07, D-13, criterion 4, F-965, F-020) -----------------

NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
MAX_AGE = timedelta(seconds=60)
DEMO_EQUITY = Decimal("4999.09343961")


def _reading(**overrides: object) -> AccountEquityReading:
    """A fresh recorded-Demo-shaped reading (demo-observed, not mainnet): no open order."""
    kwargs: dict[str, object] = {
        "total_margin_balance": DEMO_EQUITY,
        "total_wallet_balance": DEMO_EQUITY,
        "total_unrealized_profit": Decimal("0.00000000"),
        "quote_asset_margin_balance": DEMO_EQUITY,
        "balance_endpoint_wallet": DEMO_EQUITY,
        "multi_assets_margin": False,
        "available_balance": DEMO_EQUITY,
        "total_open_order_initial_margin": Decimal("0.00000000"),
        "quote_asset_available_balance": DEMO_EQUITY,
        "dual_side_position": False,
        "observed_at_utc": NOW - timedelta(seconds=10),
    }
    kwargs.update(overrides)
    return AccountEquityReading(**kwargs)  # type: ignore[arg-type]


def _check(
    reading: AccountEquityReading | None, *, now_utc: datetime = NOW, max_age: timedelta = MAX_AGE
) -> AvailableMarginCheck:
    return check_available_margin(reading=reading, now_utc=now_utc, max_age=max_age)


def _assert_blocked(result: AvailableMarginCheck, blocked: str) -> None:
    assert result.reason_code == UNCERTAIN
    assert result.blocked == blocked
    assert result.available is None
    assert result.equity is None
    assert result.observed_at_utc is None


def test_a_fresh_recorded_reading_is_ok() -> None:
    reading = _reading()
    result = _check(reading)
    assert result.available == Decimal("4999.09343961")
    assert result.equity == Decimal("4999.09343961")
    assert result.observed_at_utc == reading.observed_at_utc
    assert result.reason_code == "OK"
    assert result.blocked is None


def test_no_reading_is_unusable() -> None:
    _assert_blocked(_check(None), BLOCKED_READING_UNUSABLE)


def test_the_age_bound_is_inclusive_and_one_microsecond_past_it_is_unusable() -> None:
    assert _check(_reading(observed_at_utc=NOW - MAX_AGE)).reason_code == "OK"
    late = _reading(observed_at_utc=NOW - MAX_AGE - timedelta(microseconds=1))
    _assert_blocked(_check(late), BLOCKED_READING_UNUSABLE)


def test_a_future_dated_reading_is_unusable() -> None:
    future = _reading(observed_at_utc=NOW + timedelta(microseconds=1))
    _assert_blocked(_check(future), BLOCKED_READING_UNUSABLE)


_ZERO = Decimal("0")
_ONE_OFF = Decimal("4999.09343962")


@pytest.mark.parametrize(
    "overrides",
    [
        {"quote_asset_margin_balance": None},
        {"quote_asset_margin_balance": Decimal("1")},
        {"balance_endpoint_wallet": None},
        {"balance_endpoint_wallet": Decimal("1")},
        {"total_wallet_balance": Decimal("1")},
        {
            "total_margin_balance": _ZERO,
            "total_wallet_balance": _ZERO,
            "quote_asset_margin_balance": _ZERO,
            "balance_endpoint_wallet": _ZERO,
        },
        {"quote_asset_available_balance": None},
        {"quote_asset_available_balance": Decimal("4999.09343960")},
        {"available_balance": _ONE_OFF},
    ],
)
def test_a_failed_identity_or_a_mismatching_available_balance_is_unusable(
    overrides: dict[str, object],
) -> None:
    _assert_blocked(_check(_reading(**overrides)), BLOCKED_READING_UNUSABLE)


def test_the_two_available_balance_figures_are_compared_by_value() -> None:
    same = _reading(available_balance=Decimal("4999.0934396100"))
    assert _check(same).reason_code == "OK"


def test_a_hedge_account_is_reported_as_hedge_mode() -> None:
    result = _check(_reading(dual_side_position=True))
    assert result.reason_code == UNCERTAIN
    assert result.blocked == BLOCKED_HEDGE_MODE == "HEDGE_MODE"
    assert result.available is None and result.equity is None


def test_a_multi_assets_account_is_reported_as_multi_assets_mode() -> None:
    result = _check(_reading(multi_assets_margin=True))
    assert result.reason_code == UNCERTAIN
    assert result.blocked == BLOCKED_MULTI_ASSETS_MODE == "MULTI_ASSETS_MODE"
    assert result.available is None and result.equity is None


_STALE = NOW - MAX_AGE - timedelta(seconds=1)
_FUTURE = NOW + timedelta(seconds=1)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"observed_at_utc": _STALE, "dual_side_position": True}, BLOCKED_READING_UNUSABLE),
        ({"observed_at_utc": _FUTURE, "multi_assets_margin": True}, BLOCKED_READING_UNUSABLE),
        ({"dual_side_position": True}, BLOCKED_HEDGE_MODE),
        ({"multi_assets_margin": True}, BLOCKED_MULTI_ASSETS_MODE),
        ({"dual_side_position": True, "multi_assets_margin": True}, BLOCKED_HEDGE_MODE),
        ({}, None),
    ],
)
def test_the_refusal_order_is_unusable_then_hedge_then_multi_assets(
    overrides: dict[str, object], expected: str | None
) -> None:
    assert _check(_reading(**overrides)).blocked == expected


def test_the_available_figure_is_the_value_of_the_single_basis_function() -> None:
    reading = _reading(
        available_balance=Decimal("4959.09343961"),
        total_open_order_initial_margin=Decimal("40.00000000"),
        quote_asset_available_balance=Decimal("4959.09343961"),
    )
    result = _check(reading)
    assert result.reason_code == "OK"
    assert result.available == free_margin_basis(
        available_balance=reading.available_balance,
        total_open_order_initial_margin=reading.total_open_order_initial_margin,
    )
    assert result.equity == DEMO_EQUITY  # the equity does not depend on availableBalance


def test_programming_errors_raise() -> None:
    naive = datetime(2026, 10, 24, 12, 0, 0)
    offset = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone(timedelta(hours=7)))
    with pytest.raises(ValueError):
        _check(_reading(), now_utc=naive)
    with pytest.raises(ValueError):
        _check(_reading(), now_utc=offset)
    with pytest.raises(ValueError):
        _check(_reading(), max_age=timedelta(0))
    with pytest.raises(ValueError):
        _check(None, max_age=timedelta(seconds=-1))


def test_the_check_result_couples_its_fields() -> None:
    ok = {"available": Decimal("1"), "equity": Decimal("1"), "observed_at_utc": NOW}
    assert AvailableMarginCheck(**ok, reason_code="OK", blocked=None).blocked is None  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AvailableMarginCheck(**ok, reason_code="OK", blocked=BLOCKED_HEDGE_MODE)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AvailableMarginCheck(**ok, reason_code=UNCERTAIN, blocked=BLOCKED_HEDGE_MODE)  # type: ignore[arg-type]
    none = {"available": None, "equity": None, "observed_at_utc": None}
    with pytest.raises(ValueError):
        AvailableMarginCheck(**none, reason_code=UNCERTAIN, blocked=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AvailableMarginCheck(**none, reason_code=UNCERTAIN, blocked="OTHER")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AvailableMarginCheck(**none, reason_code="OK", blocked=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AvailableMarginCheck(**none, reason_code="NOT_A_REASON", blocked=BLOCKED_HEDGE_MODE)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        AvailableMarginCheck(
            available=1.5,  # type: ignore[arg-type]
            equity=Decimal("1"),
            observed_at_utc=NOW,
            reason_code="OK",
            blocked=None,
        )


def test_the_blocked_values_are_plain_strings_not_rejection_reasons() -> None:
    values = {BLOCKED_READING_UNUSABLE, BLOCKED_HEDGE_MODE, BLOCKED_MULTI_ASSETS_MODE}
    assert values == {"READING_UNUSABLE", "HEDGE_MODE", "MULTI_ASSETS_MODE"}
    assert all(type(value) is str for value in values)
    assert not values & {r.value for r in RejectionReason}
