"""Tests for the live equity resolver (Phase 21, plan 21-04; F-012, D-02, D-03, D-04, D-05).

Live sizing uses Binance-canonical equity (`totalMarginBalance` of GET /fapi/v3/account) and
fails closed to NO_TRADE / UNCERTAIN_ACCOUNT_STATE on anything stale, inconsistent, multi-asset
or non-positive. Oracles are literal Decimals; no expectation is computed by the code under
test. The Demo numbers below are recorded payload values (demo-observed, not mainnet).
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core.types import AccountState
from src.risk.live_equity import (
    AccountEquityReading,
    EquityCheck,
    LiveEquityResult,
    check_equity_reading,
    equity_basis,
    resolve_live_equity,
)

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = REPO_ROOT / "src" / "risk" / "live_equity.py"

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
MAX_AGE = timedelta(seconds=60)
RISK_RATE = Decimal("0.005")
UNCERTAIN = "UNCERTAIN_ACCOUNT_STATE"
DEMO_EQUITY = Decimal("4999.09343961")


def _reading(**overrides: Any) -> AccountEquityReading:
    """A fresh recorded-Demo-shaped reading: no open position, so unrealized is zero."""
    kwargs: dict[str, Any] = {
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
    return AccountEquityReading(**kwargs)


def _resolve(
    reading: AccountEquityReading | None,
    *,
    now_utc: datetime = NOW,
    max_age: timedelta = MAX_AGE,
    risk_rate: Decimal = RISK_RATE,
) -> LiveEquityResult:
    return resolve_live_equity(
        reading=reading, risk_rate=risk_rate, now_utc=now_utc, max_age=max_age
    )


def _assert_no_trade(result: LiveEquityResult) -> None:
    assert result.reason_code == UNCERTAIN
    assert result.account_state is None
    assert result.equity is None
    assert result.equity_for_snapshot is None
    assert result.is_no_trade is True


# --------------------------------------------------------------------------- #
# Happy paths
# --------------------------------------------------------------------------- #


def test_fresh_demo_shaped_reading_resolves_to_account_state() -> None:
    result = _resolve(_reading())
    assert result.reason_code == "OK"
    assert result.is_no_trade is False
    assert result.account_state == AccountState(
        equity=Decimal("4999.09343961"), risk_rate=RISK_RATE
    )
    assert result.account_state is not None
    assert result.account_state.equity == Decimal("4999.09343961")
    assert result.account_state.risk_rate == Decimal("0.005")
    assert result.equity == Decimal("4999.09343961")
    assert result.equity_for_snapshot == Decimal("4999.09343961")
    assert result.observed_at_utc == NOW - timedelta(seconds=10)


def test_unrealized_loss_is_included_in_equity() -> None:
    reading = _reading(
        total_wallet_balance=Decimal("1000"),
        total_unrealized_profit=Decimal("-12.5"),
        total_margin_balance=Decimal("987.5"),
        quote_asset_margin_balance=Decimal("987.5"),
        balance_endpoint_wallet=Decimal("1000"),
    )
    result = _resolve(reading)
    assert result.reason_code == "OK"
    assert result.equity_for_snapshot == Decimal("987.5")
    assert result.account_state is not None
    assert result.account_state.equity == Decimal("987.5")


def test_age_exactly_max_age_passes() -> None:
    result = _resolve(_reading(observed_at_utc=NOW - MAX_AGE))
    assert result.reason_code == "OK"
    assert result.equity_for_snapshot == DEMO_EQUITY


def test_equity_basis_is_total_margin_balance() -> None:
    reading = _reading(
        total_wallet_balance=Decimal("1000"),
        total_unrealized_profit=Decimal("-12.5"),
        total_margin_balance=Decimal("987.5"),
        quote_asset_margin_balance=Decimal("987.5"),
    )
    assert equity_basis(reading) == Decimal("987.5")


# --------------------------------------------------------------------------- #
# Fail closed
# --------------------------------------------------------------------------- #


def test_missing_reading_is_no_trade() -> None:
    _assert_no_trade(_resolve(None))


def test_one_millisecond_past_max_age_is_no_trade() -> None:
    stale = _reading(observed_at_utc=NOW - MAX_AGE - timedelta(milliseconds=1))
    _assert_no_trade(_resolve(stale))


def test_future_dated_reading_is_no_trade() -> None:
    future = _reading(observed_at_utc=NOW + timedelta(milliseconds=1))
    _assert_no_trade(_resolve(future))


def test_multi_assets_margin_is_no_trade() -> None:
    _assert_no_trade(_resolve(_reading(multi_assets_margin=True)))


def test_margin_differing_from_wallet_plus_unrealized_is_no_trade() -> None:
    # wallet 1000 + unrealized -12.5 = 987.5, but the account reports 990.
    reading = _reading(
        total_wallet_balance=Decimal("1000"),
        total_unrealized_profit=Decimal("-12.5"),
        total_margin_balance=Decimal("990"),
        quote_asset_margin_balance=Decimal("990"),
        balance_endpoint_wallet=Decimal("1000"),
    )
    _assert_no_trade(_resolve(reading))


def test_missing_quote_asset_row_is_no_trade() -> None:
    _assert_no_trade(_resolve(_reading(quote_asset_margin_balance=None)))


def test_quote_asset_row_differing_from_total_margin_is_no_trade() -> None:
    _assert_no_trade(_resolve(_reading(quote_asset_margin_balance=Decimal("4999.09343960"))))


def test_missing_balance_endpoint_row_is_no_trade() -> None:
    _assert_no_trade(_resolve(_reading(balance_endpoint_wallet=None)))


def test_balance_endpoint_differing_from_wallet_is_no_trade() -> None:
    _assert_no_trade(_resolve(_reading(balance_endpoint_wallet=Decimal("4999.09343962"))))


def test_zero_equity_is_no_trade() -> None:
    zero = Decimal("0")
    reading = _reading(
        total_margin_balance=zero,
        total_wallet_balance=zero,
        total_unrealized_profit=zero,
        quote_asset_margin_balance=zero,
        balance_endpoint_wallet=zero,
    )
    _assert_no_trade(_resolve(reading))


def test_negative_equity_is_no_trade() -> None:
    reading = _reading(
        total_margin_balance=Decimal("-5"),
        total_wallet_balance=Decimal("10"),
        total_unrealized_profit=Decimal("-15"),
        quote_asset_margin_balance=Decimal("-5"),
        balance_endpoint_wallet=Decimal("10"),
    )
    _assert_no_trade(_resolve(reading))


def test_no_tolerance_one_unit_in_last_place_is_no_trade() -> None:
    reading = _reading(total_margin_balance=Decimal("4999.09343962"))
    _assert_no_trade(_resolve(reading))


# --------------------------------------------------------------------------- #
# check_equity_reading
# --------------------------------------------------------------------------- #


def test_check_returns_equity_check_without_risk_rate() -> None:
    check = check_equity_reading(reading=_reading(), now_utc=NOW, max_age=MAX_AGE)
    assert check == EquityCheck(
        equity=Decimal("4999.09343961"),
        observed_at_utc=NOW - timedelta(seconds=10),
        reason_code="OK",
    )
    assert not hasattr(check, "risk_rate")


@pytest.mark.parametrize(
    "reading",
    [
        None,
        _reading(observed_at_utc=NOW - MAX_AGE - timedelta(milliseconds=1)),
        _reading(observed_at_utc=NOW + timedelta(milliseconds=1)),
        _reading(multi_assets_margin=True),
        _reading(quote_asset_margin_balance=None),
        _reading(balance_endpoint_wallet=None),
        _reading(total_margin_balance=Decimal("1")),
    ],
)
def test_check_fails_closed_without_equity(reading: AccountEquityReading | None) -> None:
    check = check_equity_reading(reading=reading, now_utc=NOW, max_age=MAX_AGE)
    assert check.reason_code == UNCERTAIN
    assert check.equity is None
    assert check.observed_at_utc is None


def test_equity_check_couples_reason_to_presence() -> None:
    with pytest.raises(ValueError):
        EquityCheck(equity=None, observed_at_utc=None, reason_code="OK")
    with pytest.raises(ValueError):
        EquityCheck(equity=DEMO_EQUITY, observed_at_utc=NOW, reason_code=UNCERTAIN)
    with pytest.raises(ValueError):
        EquityCheck(equity=None, observed_at_utc=None, reason_code="NOT_A_REASON")


def test_result_couples_reason_to_presence() -> None:
    with pytest.raises(ValueError):
        LiveEquityResult(account_state=None, reason_code="OK", equity=None, observed_at_utc=None)
    with pytest.raises(ValueError):
        LiveEquityResult(
            account_state=AccountState(equity=DEMO_EQUITY, risk_rate=RISK_RATE),
            reason_code=UNCERTAIN,
            equity=DEMO_EQUITY,
            observed_at_utc=NOW,
        )


# --------------------------------------------------------------------------- #
# Programming errors raise
# --------------------------------------------------------------------------- #


def test_naive_now_utc_raises() -> None:
    with pytest.raises(ValueError):
        _resolve(_reading(), now_utc=datetime(2026, 10, 23, 12, 0, 0))


def test_non_utc_now_utc_raises() -> None:
    with pytest.raises(ValueError):
        _resolve(_reading(), now_utc=NOW.astimezone(timezone(timedelta(hours=7))))


@pytest.mark.parametrize("bad", [timedelta(0), timedelta(seconds=-1)])
def test_non_positive_max_age_raises(bad: timedelta) -> None:
    with pytest.raises(ValueError):
        _resolve(_reading(), max_age=bad)
    with pytest.raises(ValueError):
        check_equity_reading(reading=_reading(), now_utc=NOW, max_age=bad)


@pytest.mark.parametrize(
    "field",
    [
        "total_margin_balance",
        "total_wallet_balance",
        "total_unrealized_profit",
        "quote_asset_margin_balance",
        "balance_endpoint_wallet",
        "available_balance",
        "total_open_order_initial_margin",
        "quote_asset_available_balance",
    ],
)
@pytest.mark.parametrize("bad", [1000.5, 1000, True, "1000"])
def test_non_decimal_amount_raises_type_error(field: str, bad: object) -> None:
    with pytest.raises(TypeError):
        _reading(**{field: bad})


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_amount_raises_value_error(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        _reading(total_unrealized_profit=bad)


def test_naive_observed_at_raises() -> None:
    with pytest.raises(ValueError):
        _reading(observed_at_utc=datetime(2026, 10, 23, 11, 59, 50))


def test_non_bool_multi_assets_margin_raises_type_error() -> None:
    with pytest.raises(TypeError):
        _reading(multi_assets_margin="false")


@pytest.mark.parametrize("bad", [0, 1, "false", None])
def test_non_bool_dual_side_position_raises_type_error(bad: object) -> None:
    with pytest.raises(TypeError):
        _reading(dual_side_position=bad)


@pytest.mark.parametrize(
    "field",
    ["available_balance", "total_open_order_initial_margin", "quote_asset_available_balance"],
)
@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_free_margin_figure_raises_value_error(field: str, bad: Decimal) -> None:
    with pytest.raises(ValueError):
        _reading(**{field: bad})


def test_a_missing_quote_asset_available_balance_is_kept_as_none() -> None:
    assert _reading(quote_asset_available_balance=None).quote_asset_available_balance is None


def test_the_free_margin_figures_do_not_change_the_equity() -> None:
    """The equity does not depend on availableBalance (Phase 22 prohibition)."""
    odd = _reading(
        available_balance=Decimal("1"),
        total_open_order_initial_margin=Decimal("3"),
        quote_asset_available_balance=Decimal("2"),
        dual_side_position=True,
    )
    result = _resolve(odd)
    assert result.equity == DEMO_EQUITY


def test_reading_is_frozen() -> None:
    reading = _reading()
    with pytest.raises(AttributeError):
        reading.total_margin_balance = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.1"), Decimal("1.5")])
def test_invalid_risk_rate_raises_from_account_state(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        _resolve(_reading(), risk_rate=bad)


# --------------------------------------------------------------------------- #
# Purity (D-05)
# --------------------------------------------------------------------------- #


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
