"""Phase 21 composition: equity source + day-risk service -> build_live_risk_inputs -> portfolio.

Nyquist validation (EXEC-01 / SC1). Fakes only: the in-memory day store, the scripted account
reader and the recorded-Demo snapshots (demo-observed, not mainnet). The manager's gate 5f3 is an
inline comparison inside ``execute_approved_plan`` and is covered in ``tests/test_phase21_gate.py``;
here the chain BEFORE the manager is run end to end with the real classes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.adapters.binance_usdm import UserTradeRow
from src.domain.enums import DailyState, RejectionReason
from src.execution.account_equity import LiveEquitySource
from src.execution.live_risk_inputs import build_live_risk_inputs
from src.risk.live_equity import LiveEquityResult
from src.risk.portfolio import check_portfolio
from src.risk.types import SizedResult

from tests.support.account_fakes import (
    BALANCES,
    CONFIG,
    INFORMATION,
    ScriptedAccountReader,
    demo_account_snapshots,
)
from tests.support.day_risk_fakes import (
    TEST_ONLY_PARAMETER_SET,
    DayRiskRig,
    ScriptedDayRiskReader,
    build_day_risk_rig,
)
from tests.support.execution_limits import test_only_execution_limits as only_limits
from tests.support.virtual_time import VirtualTime

T0 = datetime(2026, 10, 23, 0, 5, 0, tzinfo=UTC)
RISK_RATE = Decimal("0.005")
MAX_AGE = timedelta(milliseconds=9137)  # account.max_equity_age_ms of the TEST_ONLY limits
UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
DAILY_STOP_BLOCK = RejectionReason.DAILY_STOP_BLOCK.value


async def _source(clock: VirtualTime) -> LiveEquitySource:
    information, balances, config = await demo_account_snapshots()
    reader = ScriptedAccountReader(
        {CONFIG: [config], INFORMATION: [information], BALANCES: [balances]},
        virtual_time=clock,
        advance_seconds_per_call=0,
    )
    return LiveEquitySource(adapter=reader, clock=clock, limits=only_limits(), quote_asset="USDT")


def _loss_row(pnl: str, commission: str) -> UserTradeRow:
    """SYNTHETIC REST row (labelled test data)."""
    return UserTradeRow(
        symbol="BTCUSDT",
        order_id=11,
        trade_id=21,
        realized_pnl=Decimal(pnl),
        commission=Decimal(commission),
        commission_asset="USDT",
        margin_asset="USDT",
        time_utc=T0,
    )


async def _build(rig: DayRiskRig, equity: LiveEquityResult, *, now: datetime):  # type: ignore[no-untyped-def]
    verdict = await rig.service.evaluate(now_utc=now, exposure=False)
    day = rig.store.get_day(now.date())
    return verdict, build_live_risk_inputs(
        equity=equity,
        day=day,
        verdict=verdict,
        counted=[],
        exchange_exposures=[],
        candidate_trade_plan_id="cand",
        parameter_set=TEST_ONLY_PARAMETER_SET,
        now_utc=now,
        max_equity_age=MAX_AGE,
    )


def _portfolio_reason(inputs, now: datetime) -> str:  # type: ignore[no-untyped-def]
    sized = SizedResult(
        is_no_trade=False,
        quantity=Decimal("1"),
        quantity_before_rounding=Decimal("1"),
        quantity_after_rounding=Decimal("1"),
        quantization_decision="ACCEPTED",
        realized_risk=Decimal("1"),
    )
    return check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=inputs.open_positions,
        daily_loss_quote=inputs.daily_loss_quote,
        parameter_set=inputs.parameter_set,
        now_utc=now,
        ttl=timedelta(0),
        positions_reconciled=True,
        constraint_observed_at_utc=now,
    ).reason_code


async def test_fresh_equity_and_a_normal_day_reach_the_portfolio_gate_and_pass() -> None:
    rig = await build_day_risk_rig(start=T0)
    source = await _source(rig.clock)
    await source.refresh()
    await rig.service.backfill(now_utc=T0)
    equity = source.resolve(risk_rate=RISK_RATE, now_utc=rig.clock())
    verdict, result = await _build(rig, equity, now=rig.clock())
    assert verdict.state is DailyState.NORMAL
    assert result.reason_code == "OK" and result.inputs is not None
    assert _portfolio_reason(result.inputs, rig.clock()) == "OK"


async def test_stale_equity_is_no_trade_before_the_portfolio_gate() -> None:
    rig = await build_day_risk_rig(start=T0)
    source = await _source(rig.clock)
    await source.refresh()
    await rig.service.backfill(now_utc=T0)
    await rig.clock.advance(60)  # far past the 9.137 s age bound
    now = rig.clock()
    equity = source.resolve(risk_rate=RISK_RATE, now_utc=now)
    assert equity.is_no_trade
    _, result = await _build(rig, equity, now=now)
    assert result.is_no_trade and result.inputs is None
    assert result.reason_code == UNCERTAIN


async def test_a_latched_day_is_a_daily_stop_block_even_with_fresh_equity() -> None:
    reader = ScriptedDayRiskReader(trades={"BTCUSDT": (_loss_row("-49.99", "0.02"),)})
    rig = await build_day_risk_rig(start=T0, reader=reader)
    source = await _source(rig.clock)
    await source.refresh()
    await rig.service.backfill(now_utc=T0)
    equity = source.resolve(risk_rate=RISK_RATE, now_utc=rig.clock())
    assert not equity.is_no_trade
    verdict, result = await _build(rig, equity, now=rig.clock())
    assert verdict.state is DailyState.DAILY_STOP
    assert result.is_no_trade and result.inputs is None
    assert result.reason_code == DAILY_STOP_BLOCK
