"""Tests for the live commission-rate resolver (Phase 12, plan 12-05).

Wave 0 file. Live sizing uses max(parameter rate, account taker rate) per
side (entry and stop exit are both taker, D036) and fails closed to
NO_TRADE / UNCERTAIN_ACCOUNT_STATE on any unknown account state (D-11).

Oracles are literal Decimals; no expectation is computed by the code under
test. Parameter rates: fee 0.0005 / 0.0005, slippage 0.0001 / 0.0003.
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from src.risk.cost_rates import FEE_SOURCE_ACCOUNT_MAX, FEE_SOURCE_PARAMETER, CostRates
from src.risk.live_commission import (
    AccountCommission,
    LiveCostRatesResult,
    resolve_live_cost_rates,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
TTL = timedelta(seconds=3600)
UNCERTAIN = "UNCERTAIN_ACCOUNT_STATE"


def _param_rates() -> CostRates:
    return CostRates(
        fee_rate_entry=Decimal("0.0005"),
        entry_slippage_rate=Decimal("0.0001"),
        fee_rate_exit=Decimal("0.0005"),
        exit_slippage_rate=Decimal("0.0003"),
        fee_source=FEE_SOURCE_PARAMETER,
    )


def _account(**overrides: object) -> AccountCommission:
    kwargs: dict[str, object] = {
        "symbol": "BTCUSDT",
        "maker_rate": Decimal("0.0002"),
        "taker_rate": Decimal("0.0004"),
        "observed_at_utc": NOW - timedelta(seconds=10),
    }
    kwargs.update(overrides)
    return AccountCommission(**kwargs)  # type: ignore[arg-type]


def _resolve(
    account: AccountCommission | None,
    *,
    candidate_symbol: str = "BTCUSDT",
    now_utc: datetime = NOW,
    ttl: timedelta = TTL,
) -> LiveCostRatesResult:
    return resolve_live_cost_rates(
        parameter_rates=_param_rates(),
        account_commission=account,
        candidate_symbol=candidate_symbol,
        now_utc=now_utc,
        ttl=ttl,
    )


# --------------------------------------------------------------------------- #
# AccountCommission validation
# --------------------------------------------------------------------------- #


def test_account_commission_valid_and_frozen() -> None:
    a = _account()
    assert a.symbol == "BTCUSDT"
    assert a.maker_rate == Decimal("0.0002")
    assert a.taker_rate == Decimal("0.0004")
    with pytest.raises(AttributeError):
        a.taker_rate = Decimal("0.001")  # type: ignore[misc]


def test_account_commission_accepts_zero_and_ceiling() -> None:
    assert _account(taker_rate=Decimal("0")).taker_rate == Decimal("0")
    assert _account(taker_rate=Decimal("0.01")).taker_rate == Decimal("0.01")


def test_account_commission_rejects_empty_symbol() -> None:
    with pytest.raises(ValueError):
        _account(symbol="")


@pytest.mark.parametrize("bad", [0.0004, 1, "0.0004", True])
def test_account_commission_rejects_non_decimal_taker(bad: object) -> None:
    with pytest.raises(TypeError):
        _account(taker_rate=bad)


@pytest.mark.parametrize("bad", [0.0002, 0, "0.0002", False])
def test_account_commission_rejects_non_decimal_maker(bad: object) -> None:
    with pytest.raises(TypeError):
        _account(maker_rate=bad)


@pytest.mark.parametrize(
    "bad",
    [Decimal("-0.0001"), Decimal("0.0100001"), Decimal("0.5"), Decimal("NaN"), Decimal("Infinity")],
)
def test_account_commission_rejects_out_of_range_rates(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        _account(taker_rate=bad)
    with pytest.raises(ValueError):
        _account(maker_rate=bad)


def test_account_commission_rejects_naive_observed_at() -> None:
    with pytest.raises(ValueError):
        _account(observed_at_utc=datetime(2026, 9, 30, 11, 59, 0))


def test_account_commission_rejects_non_utc_observed_at() -> None:
    plus7 = timezone(timedelta(hours=7))
    with pytest.raises(ValueError):
        _account(observed_at_utc=datetime(2026, 9, 30, 11, 59, 0, tzinfo=plus7))


# --------------------------------------------------------------------------- #
# LiveCostRatesResult invariants
# --------------------------------------------------------------------------- #


def test_result_with_rates_requires_ok() -> None:
    res = LiveCostRatesResult(rates=_param_rates(), reason_code="OK")
    assert res.is_no_trade is False
    with pytest.raises(ValueError):
        LiveCostRatesResult(rates=_param_rates(), reason_code=UNCERTAIN)


def test_result_without_rates_requires_non_ok_known_reason() -> None:
    res = LiveCostRatesResult(rates=None, reason_code=UNCERTAIN)
    assert res.is_no_trade is True
    with pytest.raises(ValueError):
        LiveCostRatesResult(rates=None, reason_code="OK")
    with pytest.raises(ValueError):
        LiveCostRatesResult(rates=None, reason_code="NOT_A_REAL_REASON")


def test_result_is_frozen() -> None:
    res = LiveCostRatesResult(rates=None, reason_code=UNCERTAIN)
    with pytest.raises(AttributeError):
        res.reason_code = "OK"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Max rule (parameter 0.0005, slippage 0.0001 / 0.0003)
# --------------------------------------------------------------------------- #


def test_account_taker_below_parameter_keeps_parameter() -> None:
    res = _resolve(_account(taker_rate=Decimal("0.0004")))
    assert res.is_no_trade is False
    assert res.reason_code == "OK"
    assert res.rates is not None
    assert res.rates.fee_rate_entry == Decimal("0.0005")
    assert res.rates.fee_rate_exit == Decimal("0.0005")
    assert res.rates.fee_source == FEE_SOURCE_ACCOUNT_MAX
    assert res.rates.fee_source == "ACCOUNT_MAX"


def test_account_taker_above_parameter_wins_on_both_sides() -> None:
    res = _resolve(_account(taker_rate=Decimal("0.0007")))
    assert res.rates is not None
    assert res.rates.fee_rate_entry == Decimal("0.0007")
    assert res.rates.fee_rate_exit == Decimal("0.0007")
    assert res.rates.fee_source == "ACCOUNT_MAX"


def test_account_taker_zero_is_a_real_rate_floored_by_parameter() -> None:
    res = _resolve(_account(taker_rate=Decimal("0")))
    assert res.is_no_trade is False
    assert res.rates is not None
    assert res.rates.fee_rate_entry == Decimal("0.0005")
    assert res.rates.fee_rate_exit == Decimal("0.0005")


def test_maker_rate_is_not_used_for_sizing() -> None:
    res = _resolve(_account(maker_rate=Decimal("0.01"), taker_rate=Decimal("0.0004")))
    assert res.rates is not None
    assert res.rates.fee_rate_entry == Decimal("0.0005")
    assert res.rates.fee_rate_exit == Decimal("0.0005")


def test_slippage_rates_pass_through_unchanged() -> None:
    res = _resolve(_account(taker_rate=Decimal("0.0007")))
    assert res.rates is not None
    assert res.rates.entry_slippage_rate == Decimal("0.0001")
    assert res.rates.exit_slippage_rate == Decimal("0.0003")


# --------------------------------------------------------------------------- #
# Fail closed (D-11): every unknown account state is NO_TRADE, no rates
# --------------------------------------------------------------------------- #


def _assert_fail_closed(res: LiveCostRatesResult) -> None:
    assert res.is_no_trade is True
    assert res.rates is None
    assert res.reason_code == UNCERTAIN


def test_missing_account_commission_fails_closed() -> None:
    _assert_fail_closed(_resolve(None))


def test_wrong_symbol_fails_closed() -> None:
    _assert_fail_closed(_resolve(_account(symbol="ETHUSDT"), candidate_symbol="BTCUSDT"))


def test_stale_by_one_second_fails_closed() -> None:
    observed = NOW - TTL - timedelta(seconds=1)
    _assert_fail_closed(_resolve(_account(observed_at_utc=observed)))


def test_future_dated_by_one_second_fails_closed() -> None:
    observed = NOW + timedelta(seconds=1)
    _assert_fail_closed(_resolve(_account(observed_at_utc=observed)))


def test_age_exactly_equal_to_ttl_passes() -> None:
    observed = NOW - TTL
    res = _resolve(_account(observed_at_utc=observed))
    assert res.is_no_trade is False
    assert res.rates is not None


def test_age_zero_passes() -> None:
    res = _resolve(_account(observed_at_utc=NOW))
    assert res.is_no_trade is False


def test_failing_resolution_never_carries_rates_or_zero_fee() -> None:
    for res in (
        _resolve(None),
        _resolve(_account(symbol="ETHUSDT")),
        _resolve(_account(observed_at_utc=NOW - TTL - timedelta(seconds=1))),
        _resolve(_account(observed_at_utc=NOW + timedelta(seconds=1))),
    ):
        assert res.rates is None


# --------------------------------------------------------------------------- #
# Programming errors raise (not market states)
# --------------------------------------------------------------------------- #


def test_naive_now_utc_raises() -> None:
    with pytest.raises(ValueError):
        _resolve(_account(), now_utc=datetime(2026, 9, 30, 12, 0, 0))


def test_non_utc_now_utc_raises() -> None:
    plus7 = timezone(timedelta(hours=7))
    with pytest.raises(ValueError):
        _resolve(_account(), now_utc=datetime(2026, 9, 30, 19, 0, 0, tzinfo=plus7))


@pytest.mark.parametrize("bad_ttl", [timedelta(0), timedelta(seconds=-1)])
def test_non_positive_ttl_raises(bad_ttl: timedelta) -> None:
    with pytest.raises(ValueError):
        _resolve(_account(), ttl=bad_ttl)


# --------------------------------------------------------------------------- #
# Purity: no float arithmetic, no backtest/adapters import.
# --------------------------------------------------------------------------- #


def test_module_has_no_float_call() -> None:
    source = (REPO_ROOT / "src" / "risk" / "live_commission.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)


def test_module_does_not_import_backtest_or_adapters() -> None:
    code = (
        "import sys\n"
        "import src.risk.live_commission\n"
        "bad = sorted(\n"
        "    m for m in sys.modules\n"
        "    if m in ('src.backtest', 'src.adapters')\n"
        "    or m.startswith('src.backtest.')\n"
        "    or m.startswith('src.adapters.')\n"
        ")\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    assert out.stdout.strip() == ""


# --------------------------------------------------------------------------- #
# Adapter read (plan 24-15, Phase 12 review IN-01): the symbol is checked before the weight-20
# call, and a negative maker rate stays a fail-closed refusal (owner decision D-22).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", ["", "btcusdt", "BtcUsdT", " BTCUSDT", "BTCUSDT ", None, 7, b"BTC"])
def test_user_commission_rate_refuses_a_malformed_symbol_before_any_call(bad: object) -> None:
    from tests.test_adapter_strictness import _commission_adapter, _commission_response

    adapter, rest = _commission_adapter(_commission_response())
    with pytest.raises(ValueError, match="symbol"):
        asyncio.run(adapter.user_commission_rate(bad))  # type: ignore[arg-type]
    assert rest.commission_calls == []


def test_user_commission_rate_accepts_an_upper_case_symbol_with_digits() -> None:
    from tests.test_adapter_strictness import _commission_adapter, _commission_response

    adapter, rest = _commission_adapter(_commission_response(symbol="1000PEPEUSDT"))
    out = asyncio.run(adapter.user_commission_rate("1000PEPEUSDT"))
    assert out.symbol == "1000PEPEUSDT"
    assert len(rest.commission_calls) == 1


def test_user_commission_rate_negative_maker_stays_a_refusal() -> None:
    from tests.test_adapter_strictness import _commission_adapter, _commission_response

    adapter, rest = _commission_adapter(_commission_response(maker="-0.0001"))
    with pytest.raises(ValueError, match="makerCommissionRate"):
        asyncio.run(adapter.user_commission_rate("BTCUSDT"))
    assert len(rest.commission_calls) == 1
