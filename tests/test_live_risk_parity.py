"""Parity of the portfolio-gate inputs: backtest ledger versus the live builder (plan 21-11).

D-02 / RISK-01 / RISK-02: for equal inputs the live risk-input builder hands `check_portfolio`
the same open positions and the same absolute thresholds as the backtest ledger, so the
portfolio verdicts are identical. Both sides are built from the same literal inputs and only
the public ledger API is used (`Ledger.start`, `register_exposure`, `open_positions_for_risk`).

The one known difference is the equity basis (owner item O-5, decided 2026-10-24, DECISIONS
D086: the smaller of the wallet balance and the margin balance), asserted in
`test_unrealized_pnl_makes_live_equity_differ_from_the_ledger_equity`.

Evidence label: executed unit tests [DESIGN].
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.backtest.ledger import Ledger, open_positions_for_risk, register_exposure
from src.core.types import AccountState
from src.domain.enums import DailyState
from src.execution.live_risk_inputs import build_live_risk_inputs
from src.risk.daily_loss import DayRiskState, DayStateVerdict
from src.risk.live_equity import AccountEquityReading, LiveEquityResult, equity_basis
from src.risk.portfolio import RATE_THRESHOLD_KEYS, check_portfolio
from src.risk.reservations import CountedReservation, ExchangeExposure, ReservationStatus
from src.risk.types import OpenPosition, SizedResult

AT = datetime(2026, 10, 23, 0, 0, 5, tzinfo=UTC)
NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
DAY = date(2026, 10, 23)
RISK_RATE = Decimal("0.005")
HASH = "a" * 64

# Rates against the base 1000: warning 5, stop 10, cluster 6, aggregate 10 (up to 2 positions).
RATES: dict[str, Any] = {
    "daily_loss_warning_threshold": Decimal("0.005"),
    "daily_loss_stop_threshold": Decimal("0.01"),
    "cluster_cap": Decimal("0.006"),
    "max_aggregate_open_risk": Decimal("0.01"),
    "max_open_positions": 2,
}


def _ledger(
    rows: list[tuple[str, str, str, str]], *, equity: str = "1000", max_positions: int = 2
) -> Ledger:
    ledger = Ledger.start(
        equity=Decimal(equity),
        parameter_set_params=dict(RATES, max_open_positions=max_positions),
        at_utc=AT,
    )
    for plan_id, symbol, side, risk in rows:
        ledger = register_exposure(
            ledger,
            trade_plan_id=plan_id,
            symbol=symbol,
            position_side=side,
            open_risk=Decimal(risk),
        )
    return ledger


def _live(
    rows: list[tuple[str, str, str, str, ReservationStatus]],
    exposures: list[ExchangeExposure],
    *,
    equity: str = "1000",
    base: str = "1000",
    max_positions: int = 2,
) -> tuple[tuple[OpenPosition, ...], dict[str, Any]]:
    counted = [
        CountedReservation(
            trade_plan_id=plan_id,
            plan_hash=HASH,
            symbol=symbol,
            position_side=side,
            status=status,
            open_risk=Decimal(risk),
        )
        for plan_id, symbol, side, risk, status in rows
    ]
    result = build_live_risk_inputs(
        equity=LiveEquityResult(
            account_state=AccountState(equity=Decimal(equity), risk_rate=RISK_RATE),
            reason_code="OK",
            equity=Decimal(equity),
            observed_at_utc=NOW,
        ),
        day=DayRiskState(utc_day=DAY, equity_at_day_start=Decimal(base), base_observed_at_utc=AT),
        verdict=DayStateVerdict(
            utc_day=DAY,
            state=DailyState.NORMAL,
            reason_code="OK",
            blocked_reason=None,
            loss_quote=Decimal("0"),
            latch_now=False,
            alerts_due=(),
        ),
        counted=counted,
        exchange_exposures=exposures,
        candidate_trade_plan_id="CANDIDATE",
        parameter_set=dict(RATES, max_open_positions=max_positions),
    )
    assert result.inputs is not None
    return result.inputs.open_positions, result.inputs.parameter_set


def _reason(
    positions: list[OpenPosition] | tuple[OpenPosition, ...],
    thresholds: dict[str, Any],
    symbol: str,
    side: str,
    risk: str,
) -> str:
    sized = SizedResult(
        is_no_trade=False,
        quantity=Decimal("1"),
        quantity_before_rounding=Decimal("1"),
        quantity_after_rounding=Decimal("1"),
        quantization_decision="ACCEPTED",
        realized_risk=Decimal(risk),
    )
    return check_portfolio(
        sized=sized,
        candidate_symbol=symbol,
        candidate_position_side=side,
        open_positions=positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=thresholds,
        now_utc=NOW,
        ttl=timedelta(0),
        positions_reconciled=True,
        constraint_observed_at_utc=NOW,
    ).reason_code


def _key(position: OpenPosition) -> tuple[str, str, Decimal]:
    return (position.symbol, position.position_side, position.open_risk)


R = ReservationStatus
ABC_LEDGER = [
    ("A", "BTCUSDT", "LONG", "3"),
    ("B", "ETHUSDT", "LONG", "2"),
    ("C", "SOLUSDT", "SHORT", "4"),
]
ABC_LIVE = [
    ("A", "BTCUSDT", "LONG", "3", R.RESERVED),
    ("B", "ETHUSDT", "LONG", "2", R.PLACED),
    ("C", "SOLUSDT", "SHORT", "4", R.OPEN),
]
EXPOSURES = [
    ExchangeExposure(symbol="ETHUSDT", signed_quantity=Decimal("0.5")),
    ExchangeExposure(symbol="SOLUSDT", signed_quantity=Decimal("-0.1")),
]


def test_open_positions_and_thresholds_are_the_same() -> None:
    ledger = _ledger(ABC_LEDGER)
    live_positions, live_thresholds = _live(ABC_LIVE, EXPOSURES)

    ledger_positions = open_positions_for_risk(ledger)
    assert sorted(map(_key, ledger_positions)) == sorted(map(_key, live_positions))
    assert sorted(map(_key, live_positions)) == [
        ("BTCUSDT", "LONG", Decimal("3")),
        ("ETHUSDT", "LONG", Decimal("2")),
        ("SOLUSDT", "SHORT", Decimal("4")),
    ]
    for key in RATE_THRESHOLD_KEYS:
        assert live_thresholds[key] == ledger.thresholds[key]
    assert {k: live_thresholds[k] for k in RATE_THRESHOLD_KEYS} == {
        "daily_loss_warning_threshold": Decimal("5"),
        "daily_loss_stop_threshold": Decimal("10"),
        "cluster_cap": Decimal("6"),
        "max_aggregate_open_risk": Decimal("10"),
    }
    assert live_thresholds["max_open_positions"] == ledger.thresholds["max_open_positions"]


# Row sets chosen so each case is reachable (max_open_positions given per case):
#   fit:      ETH LONG 2 only, cap 2, candidate BTC LONG 3 -> LONG 5 <= 6, total 5 <= 10, 1 < 2
#   cluster:  ETH LONG 4 only, cap 2, candidate BTC LONG 3 -> LONG 7 > 6
#   maxpos:   ETH LONG 2 and SOL SHORT 1, cap 2, candidate BNB LONG 1 -> LONG 3 <= 6,
#             total 4 <= 10, but 2 rows already fill the cap of 2
CASES = [
    pytest.param(
        [("A", "ETHUSDT", "LONG", "2")],
        [("A", "ETHUSDT", "LONG", "2", R.PLACED)],
        [ExchangeExposure(symbol="ETHUSDT", signed_quantity=Decimal("1"))],
        ("BTCUSDT", "LONG", "3"),
        "OK",
        id="fitting-candidate-passes",
    ),
    pytest.param(
        [("A", "ETHUSDT", "LONG", "4")],
        [("A", "ETHUSDT", "LONG", "4", R.RESERVED)],
        [],
        ("BTCUSDT", "LONG", "3"),
        "CLUSTER_CAP_REJECT",
        id="same-side-cluster",
    ),
    pytest.param(
        [("A", "ETHUSDT", "LONG", "2"), ("B", "SOLUSDT", "SHORT", "1")],
        [("A", "ETHUSDT", "LONG", "2", R.PLACED), ("B", "SOLUSDT", "SHORT", "1", R.OPEN)],
        [
            ExchangeExposure(symbol="ETHUSDT", signed_quantity=Decimal("1")),
            ExchangeExposure(symbol="SOLUSDT", signed_quantity=Decimal("-1")),
        ],
        ("BNBUSDT", "LONG", "1"),
        "MAX_POSITIONS_REJECT",
        id="beyond-max-open-positions",
    ),
]


@pytest.mark.parametrize(("ledger_rows", "live_rows", "exposures", "candidate", "expected"), CASES)
def test_check_portfolio_gives_the_same_verdict(
    ledger_rows: list[tuple[str, str, str, str]],
    live_rows: list[tuple[str, str, str, str, ReservationStatus]],
    exposures: list[ExchangeExposure],
    candidate: tuple[str, str, str],
    expected: str,
) -> None:
    ledger = _ledger(ledger_rows)
    live_positions, live_thresholds = _live(live_rows, exposures)
    symbol, side, risk = candidate
    from_ledger = _reason(open_positions_for_risk(ledger), ledger.thresholds, symbol, side, risk)
    from_live = _reason(live_positions, live_thresholds, symbol, side, risk)
    assert from_ledger == from_live == expected


def _reading_with_unrealized(unrealized: str) -> AccountEquityReading:
    """A reading with a wallet balance of 1000 and the given unrealized PnL (margin = sum)."""
    wallet = Decimal("1000")
    margin = wallet + Decimal(unrealized)
    return AccountEquityReading(
        total_margin_balance=margin,
        total_wallet_balance=wallet,
        total_unrealized_profit=Decimal(unrealized),
        quote_asset_margin_balance=margin,
        balance_endpoint_wallet=wallet,
        multi_assets_margin=False,
        available_balance=margin,
        total_open_order_initial_margin=Decimal("0"),
        quote_asset_available_balance=margin,
        dual_side_position=False,
        observed_at_utc=NOW,
    )


def test_unrealized_profit_does_not_raise_the_live_equity_above_the_ledger_equity() -> None:
    """O-5 (D086): the basis is the smaller of wallet and margin balance; a profit adds nothing."""
    ledger = _ledger(ABC_LEDGER, equity="1000")
    assert equity_basis(_reading_with_unrealized("10")) == ledger.equity == Decimal("1000")


def test_unrealized_pnl_makes_live_equity_differ_from_the_ledger_equity() -> None:
    """O-5: the live equity is the smaller of wallet and margin balance, the ledger realized-only.

    With an unrealized LOSS of 10 the live account equity is 990 while the ledger (which books
    realized PnL only) stays at 1000. The gate inputs still agree because the thresholds resolve
    against the day-start base; only the sizing equity differs, and only downwards (an unrealized
    profit leaves the live equity at the wallet balance, see the test above).
    """
    ledger = _ledger(ABC_LEDGER, equity="1000")
    result_equity = equity_basis(_reading_with_unrealized("-10"))
    assert result_equity == Decimal("990")
    live_positions, live_thresholds = _live(
        ABC_LIVE, EXPOSURES, equity=str(result_equity), base="1000"
    )
    assert ledger.equity == Decimal("1000")
    assert result_equity != ledger.equity
    assert (
        live_thresholds["daily_loss_stop_threshold"]
        == ledger.thresholds["daily_loss_stop_threshold"]
    )
    assert sorted(map(_key, live_positions)) == sorted(map(_key, open_positions_for_risk(ledger)))
