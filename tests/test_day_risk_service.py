"""LiveDayRiskService (Phase 21, plan 21-13; D-03, D-06 to D-09, D-14, RISK-02).

Fakes only: ``InMemoryDayRiskStore`` (PgDayRiskStore semantics), ``ScriptedDayRiskReader`` and the
real ``LiveEquitySource`` over ``ScriptedAccountReader`` serving the recorded-Demo snapshots
(demo-observed, not mainnet). Trade rows are SYNTHETIC and labelled so. Nothing here is wired in a
running process (Phase 24).
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_ratelimit_gate import RateLimitBanActive, RateLimitPauseActive
from src.adapters.binance_usdm import IncomeRow, UserTradeRow
from src.domain.enums import DailyState, RejectionReason
from src.execution.account_equity import LiveEquitySource
from src.execution.day_risk_service import (
    FUNDING_INCOME_TYPE,
    LiveDayRiskService,
    components_from_income,
    components_from_user_trade,
)
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.persistence.errors import RowConflict, StoreUnavailable
from src.risk.daily_loss import (
    BLOCKED_DAILY_LOSS_UNKNOWN,
    BLOCKED_DAY_BASE_UNAVAILABLE,
    BLOCKED_DAY_STATE_MISSING,
    BLOCKED_DAY_STATE_UNREADABLE,
    ComponentKind,
    ComponentSource,
    DayRiskState,
    DayStateVerdict,
    FundingPolicy,
)

from tests.support.account_fakes import (
    BALANCES,
    CONFIG,
    INFORMATION,
    RECORDED_DEMO,
    ScriptedAccountReader,
    demo_account_snapshots,
)
from tests.support.ast_guards import wall_clock_calls
from tests.support.day_risk_fakes import InMemoryDayRiskStore, ScriptedDayRiskReader
from tests.support.execution_limits import test_only_execution_limits as only_limits
from tests.support.virtual_time import VirtualTime

MODULE = Path(__file__).resolve().parent.parent / "src" / "execution" / "day_risk_service.py"
DAY = date(2026, 10, 23)
NEXT_DAY = date(2026, 10, 24)
T0 = datetime(2026, 10, 23, 0, 5, 0, tzinfo=UTC)
DEMO_EQUITY = Decimal("4999.09343961")
UNVERIFIED = FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING
REQUIRE = FundingPolicy.REQUIRE_VERIFIED_FUNDING_SOURCE
UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
PARAMS: dict[str, Any] = {
    "daily_loss_warning_threshold": Decimal("0.005"),
    "daily_loss_stop_threshold": Decimal("0.01"),
    "cluster_cap": Decimal("0.006"),
    "max_aggregate_open_risk": Decimal("0.01"),
    "max_open_positions": 2,
}


# ------------------------------------------------------------------------------ helpers


def trade(
    pnl: str,
    commission: str,
    *,
    order_id: int = 1,
    trade_id: int = 1,
    at: datetime | None = None,
    asset: str = "USDT",
) -> UserTradeRow:
    """SYNTHETIC fill row (labelled test data, not a recorded Demo row)."""
    return UserTradeRow(
        symbol="BTCUSDT",
        order_id=order_id,
        trade_id=trade_id,
        realized_pnl=Decimal(pnl),
        commission=Decimal(commission),
        commission_asset=asset,
        margin_asset="USDT",
        time_utc=at or T0,
    )


def funding_row(amount: str, *, tran_id: int = 900, asset: str = "USDT") -> IncomeRow:
    """SYNTHETIC FUNDING_FEE row (no funding row was ever observed on Demo)."""
    return IncomeRow(
        symbol="BTCUSDT",
        income_type=FUNDING_INCOME_TYPE,
        income=Decimal(amount),
        asset=asset,
        tran_id=tran_id,
        trade_id=None,
        time_utc=T0,
    )


async def snapshots(equity: Decimal | None = None) -> tuple[Any, Any, Any]:
    """The recorded-Demo snapshots; with ``equity`` the USDT figures are rescaled to it."""
    information, balances, config = await demo_account_snapshots()
    if equity is None:
        return information, balances, config
    information = dataclasses.replace(
        information,
        total_margin_balance=equity,
        total_wallet_balance=equity,
        assets=tuple(
            dataclasses.replace(row, wallet_balance=equity, margin_balance=equity)
            if row.asset == "USDT"
            else row
            for row in information.assets
        ),
    )
    balances = tuple(
        dataclasses.replace(row, balance=equity) if row.asset == "USDT" else row for row in balances
    )
    return information, balances, config


async def account_reader(
    virtual_time: VirtualTime,
    *,
    refreshes: int = 1,
    advance: int = 0,
    equity: Decimal | None = None,
) -> ScriptedAccountReader:
    information, balances, config = await snapshots(equity)
    return ScriptedAccountReader(
        {
            CONFIG: [config] * refreshes,
            INFORMATION: [information] * refreshes,
            BALANCES: [balances] * refreshes,
        },
        virtual_time=virtual_time,
        advance_seconds_per_call=advance,
    )


@dataclass
class Rig:
    service: LiveDayRiskService
    store: InMemoryDayRiskStore
    reader: ScriptedDayRiskReader
    account: ScriptedAccountReader
    clock: VirtualTime


async def build(
    *,
    start: datetime = T0,
    store: InMemoryDayRiskStore | None = None,
    reader: ScriptedDayRiskReader | None = None,
    account: ScriptedAccountReader | None = None,
    refreshes: int = 1,
    advance: int = 0,
    equity: Decimal | None = None,
    policy: FundingPolicy = UNVERIFIED,
    clock: VirtualTime | None = None,
    limits: ExecutionLimits | None = None,
) -> Rig:
    clock = clock if clock is not None else VirtualTime(start)
    if account is None:
        account = await account_reader(clock, refreshes=refreshes, advance=advance, equity=equity)
    source = LiveEquitySource(
        adapter=account, clock=clock, limits=only_limits(), quote_asset="USDT"
    )
    day_store = store if store is not None else InMemoryDayRiskStore()
    day_reader = reader if reader is not None else ScriptedDayRiskReader()
    service = LiveDayRiskService(
        reader=day_reader,
        store=day_store,
        equity=source,
        clock=clock,
        symbols={"BTCUSDT"},
        quote_asset="USDT",
        funding_policy=policy,
        parameter_set=PARAMS,
        limits=limits if limits is not None else only_limits(),
    )
    return Rig(service, day_store, day_reader, account, clock)


def assert_blocked(verdict: DayStateVerdict, reason: str) -> None:
    assert verdict.state is None
    assert verdict.reason_code == UNCERTAIN
    assert verdict.blocked_reason == reason
    assert verdict.loss_quote is None
    assert not verdict.latch_now
    assert verdict.alerts_due == ()


def stored_day(store: InMemoryDayRiskStore, day: date = DAY) -> DayRiskState:
    state = store.get_day(day)
    assert state is not None
    return state


def preopen(rig: Rig, day: date = DAY) -> None:
    """Store today's day row directly: for tests about what happens AFTER the day is open.

    A day is only opened by the service once a backfill of the day is current (WR-06), so a test
    that needs an opened day with an unknown loss cannot get there through ``evaluate``.
    """
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    rig.store.open_day(
        DayRiskState(
            utc_day=day,
            equity_at_day_start=DEMO_EQUITY,
            base_observed_at_utc=start + timedelta(minutes=5),
        )
    )


# ------------------------------------------------------------------------ Task 1: tracer


async def test_tracer_opens_the_day_from_a_fresh_base_and_evaluates_normal() -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert verdict.loss_quote == Decimal("0")
    assert verdict.alerts_due == ()
    day = stored_day(rig.store)
    assert day.equity_at_day_start == DEMO_EQUITY
    assert (
        datetime(2026, 10, 23, tzinfo=UTC)
        <= day.base_observed_at_utc
        < datetime(2026, 10, 24, tzinfo=UTC)
    )
    assert day.stop_latched_at_utc is None
    assert rig.service.last_error_type is None


async def test_the_reader_port_gets_the_whole_day_window_for_every_symbol_and_funding() -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    day_start = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    assert rig.reader.calls == [
        ("user_trades_in_window", {"symbol": "BTCUSDT", "start_utc": day_start, "end_utc": T0}),
        (
            "income_in_window",
            {"income_type": "FUNDING_FEE", "start_utc": day_start, "end_utc": T0},
        ),
        # WR-09: the cross-check reads, whole account, for what the folded fills cannot see.
        (
            "income_in_window",
            {"income_type": "REALIZED_PNL", "start_utc": day_start, "end_utc": T0},
        ),
        (
            "income_in_window",
            {"income_type": "COMMISSION", "start_utc": day_start, "end_utc": T0},
        ),
        (
            "income_in_window",
            {"income_type": "INSURANCE_CLEAR", "start_utc": day_start, "end_utc": T0},
        ),
    ]


async def test_a_clock_that_moves_3s_during_refresh_still_opens_the_day() -> None:
    # The reader moves the virtual clock 1 s per call, 3 s during refresh(); the TEST_ONLY bound
    # is 9137 ms. The earlier caller now_utc would give a negative age (stale).
    rig = await build(advance=1)
    before = rig.clock()
    await rig.service.backfill(now_utc=before)
    verdict = await rig.service.evaluate(now_utc=before, exposure=False)
    assert verdict.state is DailyState.NORMAL
    day = stored_day(rig.store)
    assert day.base_observed_at_utc == before  # the stamp of the START of refresh()
    assert rig.clock() - before == timedelta(seconds=3)


async def test_a_caller_now_older_than_the_reading_stamp_is_not_a_negative_age() -> None:
    # The caller's now_utc precedes the clock at the start of refresh(): judged with it the
    # reading would have a negative age (stale). The clock re-read after refresh() is used.
    rig = await build(start=T0 + timedelta(seconds=2))
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert stored_day(rig.store).base_observed_at_utc == T0 + timedelta(seconds=2)


async def test_a_clock_that_moves_12s_during_refresh_is_a_stale_base_and_writes_no_day() -> None:
    rig = await build(advance=4)  # 12 s during refresh, above the 9137 ms bound
    before = rig.clock()
    await rig.service.backfill(now_utc=before)
    verdict = await rig.service.evaluate(now_utc=before, exposure=False)
    assert_blocked(verdict, BLOCKED_DAY_BASE_UNAVAILABLE)
    assert rig.store.get_day(DAY) is None
    assert rig.store.count("open_day") == 0


async def test_a_derived_stop_is_latched_in_the_store_before_the_verdict_returns() -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL
    # SYNTHETIC fill: realized -49.99 and commission 0.02 give the loss 50.01 >= stop 49.9909...
    rig.reader.trades["BTCUSDT"] = (trade("-49.99", "0.02"),)
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.DAILY_STOP
    assert verdict.loss_quote == Decimal("50.01")
    assert verdict.reason_code == RejectionReason.DAILY_STOP_BLOCK.value
    assert verdict.latch_now
    assert verdict.alerts_due == (DailyState.DAILY_STOP,)
    assert stored_day(rig.store).stop_latched_at_utc == T0


def test_components_from_a_user_trade_row() -> None:
    pnl, commission = components_from_user_trade(trade("-1.5", "0.25", order_id=7, trade_id=9))
    assert (pnl.kind, pnl.amount, pnl.asset) == (ComponentKind.FILL_PNL, Decimal("-1.5"), "USDT")
    assert (commission.kind, commission.amount) == (ComponentKind.FILL_COMMISSION, Decimal("-0.25"))
    assert pnl.source is commission.source is ComponentSource.REST_USER_TRADES
    assert pnl.source_key == commission.source_key == "BTCUSDT:7:9"
    assert pnl.event_time_utc == T0 and pnl.utc_day == DAY
    rebate = components_from_user_trade(trade("0", "-0.1"))[1]
    assert rebate.amount == Decimal("0.1")


def test_components_from_an_income_row() -> None:
    component = components_from_income(funding_row("-1.5", tran_id=42))
    assert component.kind is ComponentKind.FUNDING
    assert component.source is ComponentSource.REST_INCOME
    assert component.source_key == "BTCUSDT:42"
    assert component.amount == Decimal("-1.5")
    account_level = dataclasses.replace(funding_row("1"), symbol=None, tran_id=5)
    assert components_from_income(account_level).source_key == "ACCOUNT:5"
    with pytest.raises(ValueError):
        components_from_income(dataclasses.replace(funding_row("1"), income_type="COMMISSION"))


def income_row(income_type: str, symbol: str | None, *, tran_id: int = 700) -> IncomeRow:
    """SYNTHETIC income row of any type (no such row was observed on Demo)."""
    return IncomeRow(
        symbol=symbol,
        income_type=income_type,
        income=Decimal("-3"),
        asset="USDT",
        tran_id=tran_id,
        trade_id="1",
        time_utc=T0,
    )


@pytest.mark.parametrize(
    ("income_type", "symbol"),
    [
        ("REALIZED_PNL", "DOGEUSDT"),  # a symbol outside the configured universe
        ("COMMISSION", "DOGEUSDT"),
        ("REALIZED_PNL", None),  # an account-level row has no symbol to match
        ("INSURANCE_CLEAR", "BTCUSDT"),  # a liquidation clearance fee is never folded
    ],
)
async def test_a_loss_row_the_fold_cannot_see_makes_the_loss_unknown(
    income_type: str, symbol: str | None
) -> None:
    # WR-09: userTrades covers the configured symbols and income only FUNDING_FEE, so a trade
    # on another symbol or a liquidation fee would be understated, not unknown.
    reader = ScriptedDayRiskReader(income_by_type={income_type: (income_row(income_type, symbol),)})
    rig = await build(reader=reader)
    preopen(rig)
    await rig.service.backfill(now_utc=T0)
    assert rig.service.last_error_type == "IncomeOutsideConfiguredSymbols"
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )
    assert rig.service.current_daily_loss_quote(DAY) is None
    # A clean backfill later (the rows are gone from the answer) makes it known again.
    reader.income_by_type.clear()
    await rig.service.backfill(now_utc=T0)
    assert rig.service.last_error_type is None
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL


async def test_loss_rows_of_the_configured_symbols_do_not_disturb_the_known_loss() -> None:
    reader = ScriptedDayRiskReader(
        trades={"BTCUSDT": (trade("-4", "1"),)},
        income_by_type={
            "REALIZED_PNL": (income_row("REALIZED_PNL", "BTCUSDT", tran_id=1),),
            "COMMISSION": (income_row("COMMISSION", "BTCUSDT", tran_id=2),),
        },
    )
    rig = await build(reader=reader)
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL  # 4 + 1 = 5, warning is 24.99 of the base
    assert verdict.loss_quote == Decimal("5")
    assert rig.service.last_error_type is None


async def test_a_funding_row_counts_in_the_loss() -> None:
    rig = await build(reader=ScriptedDayRiskReader(income=(funding_row("-1.5"),)))
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert verdict.loss_quote == Decimal("1.5")


# ------------------------------------------------------------------- Task 2: other branches


async def _latched_rig() -> Rig:
    rig = await build()
    rig.reader.trades["BTCUSDT"] = (trade("-49.99", "0.02"),)
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.DAILY_STOP
    return rig


async def test_a_restart_inside_the_day_keeps_the_stored_base_and_the_latch() -> None:
    first = await _latched_rig()
    later = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
    second = await build(start=later, store=first.store, equity=Decimal("4000"))
    verdict = await second.service.evaluate(now_utc=later, exposure=True)
    assert verdict.state is DailyState.DAILY_STOP  # the latch, with no backfill yet (D-14)
    assert not verdict.latch_now
    assert second.account.calls == []  # no new equity read
    assert stored_day(first.store).equity_at_day_start == DEMO_EQUITY
    assert stored_day(first.store).stop_latched_at_utc == T0


async def test_an_unlatched_restart_is_unknown_until_its_first_backfill() -> None:
    first = await build()
    await first.service.backfill(now_utc=T0)
    assert (await first.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL
    later = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
    # SYNTHETIC fill: loss 45 is a WARNING against the stored base 4999.09 (stop 49.99) but
    # would be a DAILY_STOP against a base of 4000 (stop 40): proves the stored base is used.
    reader = ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-44.99", "0.01"),)})
    second = await build(start=later, store=first.store, reader=reader, equity=Decimal("4000"))
    unknown = await second.service.evaluate(now_utc=later, exposure=True)
    assert_blocked(unknown, BLOCKED_DAILY_LOSS_UNKNOWN)
    await second.service.backfill(now_utc=later)
    verdict = await second.service.evaluate(now_utc=later, exposure=True)
    assert verdict.state is DailyState.WARNING
    assert verdict.loss_quote == Decimal("45.00")
    assert second.account.calls == []


async def test_the_warning_alert_is_stamped_once_per_day() -> None:
    rig = await build(reader=ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-30", "0"),)}))
    await rig.service.backfill(now_utc=T0)
    first = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert first.state is DailyState.WARNING
    assert first.alerts_due == (DailyState.WARNING,)
    assert stored_day(rig.store).warning_alerted_at_utc == T0
    second = await rig.service.evaluate(now_utc=T0 + timedelta(minutes=1), exposure=False)
    assert second.state is DailyState.WARNING
    assert second.alerts_due == ()


async def test_a_failing_warning_stamp_drops_the_alert_and_keeps_the_verdict() -> None:
    rig = await build(reader=ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-30", "0"),)}))
    await rig.service.backfill(now_utc=T0)
    rig.store.raise_next("mark_warning_alerted", StoreUnavailable("down"))
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.WARNING
    assert verdict.alerts_due == ()
    assert rig.service.last_error_type == "StoreUnavailable"


async def test_a_later_gain_on_a_latched_day_keeps_daily_stop() -> None:
    rig = await _latched_rig()
    rig.reader.trades["BTCUSDT"] = (
        trade("-49.99", "0.02"),
        trade("1000", "0", order_id=2, trade_id=2),
    )
    await rig.service.backfill(now_utc=T0 + timedelta(hours=1))
    verdict = await rig.service.evaluate(now_utc=T0 + timedelta(hours=1), exposure=True)
    assert verdict.state is DailyState.DAILY_STOP
    assert verdict.loss_quote == Decimal("0")
    assert not verdict.latch_now


async def _rollover_store() -> InMemoryDayRiskStore:
    store = InMemoryDayRiskStore()
    yesterday = DayRiskState(
        utc_day=DAY,
        equity_at_day_start=DEMO_EQUITY,
        base_observed_at_utc=T0,
        stop_latched_at_utc=T0,
    )
    store.open_day(yesterday)
    return store


async def test_rollover_opens_the_new_day_from_a_fresh_in_day_read_without_a_carried_latch() -> (
    None
):
    midnight = datetime(2026, 10, 24, 0, 0, 0, tzinfo=UTC)
    rig = await build(start=midnight, store=await _rollover_store(), equity=Decimal("4800"))
    # WR-06: the base needs the day's net result, so no backfill yet means no new day.
    unknown = await rig.service.evaluate(now_utc=midnight, exposure=True)
    assert_blocked(unknown, BLOCKED_DAY_BASE_UNAVAILABLE)
    assert rig.store.get_day(NEXT_DAY) is None
    assert rig.account.calls == []
    await rig.service.backfill(now_utc=midnight)
    verdict = await rig.service.evaluate(now_utc=midnight, exposure=True)
    assert verdict.state is DailyState.NORMAL
    new_day = stored_day(rig.store, NEXT_DAY)
    assert new_day.equity_at_day_start == Decimal("4800")
    assert new_day.base_observed_at_utc == midnight
    assert new_day.stop_latched_at_utc is None
    assert stored_day(rig.store, DAY).stop_latched_at_utc == T0  # yesterday is untouched


async def test_a_base_stamped_before_midnight_is_not_accepted_for_the_new_day() -> None:
    before_midnight = datetime(2026, 10, 23, 23, 59, 59, tzinfo=UTC)
    rig = await build(start=before_midnight, store=await _rollover_store())
    verdict = await rig.service.evaluate(
        now_utc=datetime(2026, 10, 24, 0, 0, 0, tzinfo=UTC), exposure=True
    )
    assert_blocked(verdict, BLOCKED_DAY_BASE_UNAVAILABLE)
    assert rig.store.get_day(NEXT_DAY) is None


async def test_a_failing_base_read_blocks_every_evaluate_until_a_read_succeeds() -> None:
    midnight = datetime(2026, 10, 24, 0, 0, 0, tzinfo=UTC)
    clock = VirtualTime(midnight)
    information, balances, config = await snapshots()
    account = ScriptedAccountReader(
        {
            CONFIG: [RateLimitPauseActive(7), RuntimeError("boom"), config],
            INFORMATION: [information],
            BALANCES: [balances],
        },
        virtual_time=clock,
    )
    rig = await build(start=midnight, store=await _rollover_store(), account=account, clock=clock)
    service = rig.service
    source_calls = account
    await service.backfill(now_utc=midnight)  # WR-06: a day opens only after its backfill
    for _ in range(2):
        assert_blocked(
            await service.evaluate(now_utc=midnight, exposure=True), BLOCKED_DAY_BASE_UNAVAILABLE
        )
        assert rig.store.get_day(NEXT_DAY) is None
    assert source_calls.count(CONFIG) == 2
    assert (await service.evaluate(now_utc=midnight, exposure=True)).state is DailyState.NORMAL
    assert stored_day(rig.store, NEXT_DAY).equity_at_day_start == DEMO_EQUITY


@pytest.mark.parametrize("exposure", [True, None])
async def test_a_missing_state_with_exposure_blocks_and_reads_no_equity(
    exposure: bool | None,
) -> None:
    rig = await build()
    verdict = await rig.service.evaluate(now_utc=T0, exposure=exposure)
    assert_blocked(verdict, BLOCKED_DAY_STATE_MISSING)
    assert rig.account.calls == []
    assert rig.store.get_day(DAY) is None


async def test_a_two_day_gap_with_exposure_opens_from_a_fresh_read() -> None:
    # WR-08 (reproduced by the reviewer): after an outage of two UTC days neither today nor
    # yesterday has a row. An earlier persisted day proves the store is intact (D-08), so the
    # day opens from a fresh in-day read instead of staying blocked for as long as the position.
    store = InMemoryDayRiskStore()
    store.open_day(
        DayRiskState(
            utc_day=DAY - timedelta(days=2),
            equity_at_day_start=DEMO_EQUITY,
            base_observed_at_utc=T0 - timedelta(days=2),
        )
    )
    rig = await build(store=store)
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=True)
    assert verdict.state is DailyState.NORMAL
    assert stored_day(rig.store).equity_at_day_start == DEMO_EQUITY
    assert rig.account.count(INFORMATION) == 1


@pytest.mark.parametrize("exposure", [True, None])
async def test_a_later_day_row_is_not_an_earlier_day(exposure: bool | None) -> None:
    # Only a row BEFORE today proves an intact store; a row of a later day does not.
    store = InMemoryDayRiskStore()
    store.open_day(
        DayRiskState(
            utc_day=DAY + timedelta(days=1),
            equity_at_day_start=DEMO_EQUITY,
            base_observed_at_utc=T0 + timedelta(days=1),
        )
    )
    rig = await build(store=store)
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=exposure), BLOCKED_DAY_STATE_MISSING
    )
    assert rig.account.calls == []


LATE = datetime(2026, 10, 23, 10, 0, 0, tzinfo=UTC)


async def test_a_late_open_after_a_morning_gain_derives_the_day_start_base() -> None:
    # WR-06: the first read of the day comes at 10:00 after a +100 morning (realized). The
    # wallet at that moment already holds the gain, so the D033 base (equity at 00:00) is
    # 4999.09343961 - 100; a base of the moment would raise every threshold by the gain.
    reader = ScriptedDayRiskReader(trades={"BTCUSDT": (trade("100", "0"),)})
    rig = await build(start=LATE, reader=reader)
    await rig.service.backfill(now_utc=LATE)
    verdict = await rig.service.evaluate(now_utc=LATE, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert stored_day(rig.store).equity_at_day_start == DEMO_EQUITY - Decimal("100")


async def test_a_late_open_after_a_morning_loss_keeps_the_conservative_base_of_the_moment() -> None:
    # The smaller base is the conservative one: a loss day is not corrected upwards.
    reader = ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-30", "0.5"),)})
    rig = await build(start=LATE, reader=reader)
    await rig.service.backfill(now_utc=LATE)
    verdict = await rig.service.evaluate(now_utc=LATE, exposure=False)
    assert verdict.state is DailyState.WARNING
    assert stored_day(rig.store).equity_at_day_start == DEMO_EQUITY


async def test_a_morning_gain_uses_the_most_favorable_amount_when_sources_diverge() -> None:
    reader = ScriptedDayRiskReader(trades={"BTCUSDT": (trade("40", "0"),)})
    rig = await build(start=LATE, reader=reader)
    await rig.service.backfill(now_utc=LATE)
    # A stream fill of the same trade that reported 60: the loss would use 40, the base 60.
    stream = dataclasses.replace(
        components_from_user_trade(trade("60", "0"))[0],
        source=ComponentSource.USER_DATA_EVENT,
    )
    rig.store.add_components((stream,))
    await rig.service.evaluate(now_utc=LATE, exposure=False)
    assert stored_day(rig.store).equity_at_day_start == DEMO_EQUITY - Decimal("60")


async def test_opening_a_day_without_a_current_backfill_is_blocked_and_reads_no_equity() -> None:
    # WR-06: the base needs the day's net result; an unknown one means no base (fail closed).
    rig = await build(start=LATE)
    verdict = await rig.service.evaluate(now_utc=LATE, exposure=False)
    assert_blocked(verdict, BLOCKED_DAY_BASE_UNAVAILABLE)
    assert rig.account.calls == []
    assert rig.store.get_day(DAY) is None
    await rig.service.backfill(now_utc=LATE)
    assert (await rig.service.evaluate(now_utc=LATE, exposure=False)).state is DailyState.NORMAL


async def test_a_stream_gap_before_the_open_makes_the_base_unavailable_until_a_backfill() -> None:
    rig = await build(start=LATE, refreshes=2)
    await rig.service.backfill(now_utc=LATE)
    rig.service.invalidate(reason="STREAM_GAP")
    assert_blocked(
        await rig.service.evaluate(now_utc=LATE, exposure=False), BLOCKED_DAY_BASE_UNAVAILABLE
    )
    assert rig.store.get_day(DAY) is None


async def test_a_gain_larger_than_the_equity_cannot_make_a_base() -> None:
    reader = ScriptedDayRiskReader(trades={"BTCUSDT": (trade("5000", "0"),)})
    rig = await build(start=LATE, reader=reader)
    await rig.service.backfill(now_utc=LATE)
    assert_blocked(
        await rig.service.evaluate(now_utc=LATE, exposure=False), BLOCKED_DAY_BASE_UNAVAILABLE
    )
    assert rig.store.get_day(DAY) is None


async def test_a_missing_state_without_exposure_opens_from_a_fresh_read() -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert rig.account.count(INFORMATION) == 1


async def test_an_unreadable_day_row_blocks() -> None:
    rig = await build()
    rig.store.raise_next("get_day", StoreUnavailable("down"))
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAY_STATE_UNREADABLE
    )
    assert rig.service.last_error_type == "StoreUnavailable"
    assert rig.account.calls == []


async def test_a_failing_previous_day_check_blocks() -> None:
    rig = await build()
    rig.store.raise_next("has_earlier_day", StoreUnavailable("down"))
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAY_STATE_UNREADABLE
    )


async def test_a_failing_open_day_write_blocks_and_opens_nothing() -> None:
    rig = await build(refreshes=2)
    await rig.service.backfill(now_utc=T0)
    rig.store.raise_next("open_day", StoreUnavailable("down"))
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAY_STATE_UNREADABLE
    )
    assert rig.store.get_day(DAY) is None


async def test_unreadable_components_block() -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL
    rig.store.raise_next("list_components", StoreUnavailable("down"))
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAY_STATE_UNREADABLE
    )


async def test_a_failing_latch_write_still_answers_daily_stop_and_the_next_call_latches() -> None:
    # WR-01: the verdict is risk-reducing (the caller cancels resting entries), so a latch that
    # cannot be written does not turn it into a state-less NO_TRADE; the next call persists it.
    rig = await build(reader=ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-60", "0"),)}))
    await rig.service.backfill(now_utc=T0)
    rig.store.raise_next("latch_stop", StoreUnavailable("down"))
    first = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert first.state is DailyState.DAILY_STOP
    assert first.reason_code == RejectionReason.DAILY_STOP_BLOCK.value
    assert rig.service.last_error_type == "StoreUnavailable"
    assert stored_day(rig.store).stop_latched_at_utc is None
    again = await rig.service.evaluate(now_utc=T0 + timedelta(minutes=1), exposure=False)
    assert again.state is DailyState.DAILY_STOP
    assert stored_day(rig.store).stop_latched_at_utc == T0  # the first failure time, now stored


async def test_an_unpersisted_stop_holds_in_process_when_the_loss_falls() -> None:
    # WR-01: a stop whose latch write failed must not lapse in the same process when a later
    # gain lowers the loss below the stop (D-14: sticky for the rest of the UTC day).
    rig = await build(reader=ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-60", "0"),)}))
    await rig.service.backfill(now_utc=T0)
    rig.store.raise_next("latch_stop", StoreUnavailable("down"))
    rig.store.raise_next("latch_stop", StoreUnavailable("down"))
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.DAILY_STOP
    rig.reader.trades["BTCUSDT"] = (trade("-60", "0"), trade("1000", "0", order_id=2, trade_id=2))
    later = T0 + timedelta(hours=1)
    await rig.service.backfill(now_utc=later)
    held = await rig.service.evaluate(now_utc=later, exposure=True)  # latch write fails again
    assert held.state is DailyState.DAILY_STOP
    assert held.loss_quote == Decimal("0")
    assert stored_day(rig.store).stop_latched_at_utc is None
    final = await rig.service.evaluate(now_utc=later, exposure=True)  # the store is back
    assert final.state is DailyState.DAILY_STOP
    assert stored_day(rig.store).stop_latched_at_utc == T0


async def test_a_latched_day_with_unreadable_components_still_answers_daily_stop() -> None:
    # WR-01 (reproduced by the reviewer): the latch held at 10:00; at 10:05 the components read
    # fails. The answer must stay DAILY_STOP so the caller retries the entry cancels.
    rig = await _latched_rig()
    rig.store.raise_next("list_components", StoreUnavailable("down"))
    verdict = await rig.service.evaluate(now_utc=T0 + timedelta(minutes=5), exposure=True)
    assert verdict.state is DailyState.DAILY_STOP
    assert verdict.reason_code == RejectionReason.DAILY_STOP_BLOCK.value
    assert verdict.loss_quote is None  # the loss is unknown, the latch answers
    assert not verdict.latch_now
    assert rig.service.last_error_type == "StoreUnavailable"


async def test_an_unlatched_day_with_unreadable_components_still_blocks() -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL
    rig.store.raise_next("list_components", StoreUnavailable("down"))
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAY_STATE_UNREADABLE
    )


async def test_two_services_opening_the_same_day_keep_the_first_stored_base() -> None:
    store = InMemoryDayRiskStore()
    first = await build(store=store, advance=1, equity=DEMO_EQUITY)
    second = await build(store=store, advance=1, equity=Decimal("4000"))
    await first.service.backfill(now_utc=T0)
    await second.service.backfill(now_utc=T0)
    one, two = await asyncio.gather(
        first.service.ensure_day(now_utc=T0, exposure=False),
        second.service.ensure_day(now_utc=T0, exposure=False),
    )
    assert isinstance(one, DayRiskState) and isinstance(two, DayRiskState)
    assert one.equity_at_day_start == two.equity_at_day_start
    assert store.get_day(DAY) == one == two
    assert store.count("open_day") == 2


@pytest.mark.parametrize(
    "error", [RateLimitPauseActive(3), RateLimitBanActive(60), RuntimeError("boom 4999.09")]
)
@pytest.mark.parametrize("method", ["user_trades_in_window", "income_in_window"])
async def test_a_failed_backfill_read_leaves_the_loss_unknown_without_a_retry(
    error: BaseException, method: str
) -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL
    rig.reader.calls.clear()
    rig.reader.fail(method, error)
    await rig.service.backfill(now_utc=T0 + timedelta(minutes=1))
    assert rig.service.last_error_type == type(error).__name__
    assert rig.reader.count("user_trades_in_window") <= 1
    assert rig.reader.count("income_in_window") <= 1
    assert_blocked(
        await rig.service.evaluate(now_utc=T0 + timedelta(minutes=1), exposure=False),
        BLOCKED_DAILY_LOSS_UNKNOWN,
    )
    rig.reader.fail(method, None)
    await rig.service.backfill(now_utc=T0 + timedelta(minutes=2))
    assert rig.service.last_error_type is None
    verdict = await rig.service.evaluate(now_utc=T0 + timedelta(minutes=2), exposure=False)
    assert verdict.state is DailyState.NORMAL


async def test_a_failed_backfill_on_a_latched_day_still_answers_daily_stop() -> None:
    rig = await _latched_rig()
    rig.reader.fail("user_trades_in_window", RuntimeError("boom"))
    await rig.service.backfill(now_utc=T0 + timedelta(minutes=1))
    verdict = await rig.service.evaluate(now_utc=T0 + timedelta(minutes=1), exposure=True)
    assert verdict.state is DailyState.DAILY_STOP
    assert verdict.loss_quote is None


async def test_a_generation_bump_during_the_reads_keeps_the_loss_unknown() -> None:
    holder: list[Rig] = []

    def bump(method: str) -> None:
        if method == "income_in_window":
            holder[0].service._backfill_generation += 1  # what plan 21-16 does on ACCOUNT_UPDATE

    rig = await build(reader=ScriptedDayRiskReader(on_call=bump))
    holder.append(rig)
    preopen(rig)
    await rig.service.backfill(now_utc=T0)
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )
    rig.reader._on_call = None
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL
    rig.service._backfill_generation += 1  # a later stream gap makes the loss unknown again
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )


async def test_a_backfill_of_another_day_does_not_make_the_new_day_known() -> None:
    rig = await build()
    await rig.service.backfill(now_utc=T0)
    midnight = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)
    store = rig.store
    assert store.get_day(DAY) is None
    store.open_day(
        DayRiskState(
            utc_day=NEXT_DAY, equity_at_day_start=DEMO_EQUITY, base_observed_at_utc=midnight
        )
    )
    assert_blocked(
        await rig.service.evaluate(now_utc=midnight, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )


async def test_a_non_quote_component_makes_the_loss_unknown() -> None:
    reader = ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-1", "0.01", asset="BNB"),)})
    rig = await build(reader=reader)
    preopen(rig)
    await rig.service.backfill(now_utc=T0)
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )


async def test_the_strict_funding_policy_is_unknown_even_after_a_complete_backfill() -> None:
    rig = await build(policy=REQUIRE)
    preopen(rig)
    await rig.service.backfill(now_utc=T0)
    assert rig.service.last_error_type is None
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )


async def test_the_recorded_empty_income_answer_keeps_the_loss_known_under_the_lenient_policy() -> (
    None
):
    # Demo returned 0 income rows in four tries (demo-observed, not mainnet).
    payload = json.loads((RECORDED_DEMO / "income_funding_empty.json").read_text(encoding="utf-8"))
    assert payload == []
    rig = await build(reader=ScriptedDayRiskReader(income=tuple(payload)), policy=UNVERIFIED)
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert verdict.loss_quote == Decimal("0")


async def test_the_store_double_keeps_the_rows_idempotent_and_refuses_a_changed_amount() -> None:
    rig = await build(reader=ScriptedDayRiskReader(trades={"BTCUSDT": (trade("-1", "0.01"),)}))
    preopen(rig)
    await rig.service.backfill(now_utc=T0)
    await rig.service.backfill(now_utc=T0)  # the same keys again: stored once
    assert len(rig.store.list_components(DAY)) == 2
    rig.reader.trades["BTCUSDT"] = (trade("-2", "0.01"),)  # same key, another amount
    await rig.service.backfill(now_utc=T0)
    assert rig.service.last_error_type == RowConflict.__name__
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )


def test_the_funding_policy_has_no_default_and_must_be_a_policy() -> None:
    def make(**overrides: Any) -> LiveDayRiskService:
        arguments: dict[str, Any] = {
            "reader": ScriptedDayRiskReader(),
            "store": InMemoryDayRiskStore(),
            "equity": object(),
            "clock": lambda: T0,
            "symbols": {"BTCUSDT"},
            "quote_asset": "USDT",
            "funding_policy": UNVERIFIED,
            "parameter_set": PARAMS,
            "limits": only_limits(),
        }
        arguments.update(overrides)
        return LiveDayRiskService(**arguments)

    assert make() is not None
    omitted = {
        "reader": ScriptedDayRiskReader(),
        "store": InMemoryDayRiskStore(),
        "equity": object(),
        "clock": lambda: T0,
        "symbols": {"BTCUSDT"},
        "quote_asset": "USDT",
        "parameter_set": PARAMS,
        "limits": only_limits(),
    }
    with pytest.raises(TypeError):
        LiveDayRiskService(**omitted)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        make(funding_policy="TRADES_WITH_UNVERIFIED_FUNDING")
    with pytest.raises(ValueError):
        make(symbols=set())
    with pytest.raises(ValueError):
        make(quote_asset=" ")


# ------------------------------------------------------------------------- loss age (WR-05, D087)

# The owner's number (DECISIONS D087, 2026-10-25): 300 seconds, as milliseconds.
LOSS_AGE_MS = 300000


async def loss_age_rig() -> Rig:
    """A rig with the owner's 300000 ms loss age, after one backfill and one evaluate."""
    rig = await build(limits=only_limits(account_max_daily_loss_age_ms=LOSS_AGE_MS))
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    return rig


async def test_a_loss_known_299_seconds_ago_is_known() -> None:
    rig = await loss_age_rig()
    await rig.clock.advance(299)
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("0")
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL


async def test_a_loss_known_301_seconds_ago_is_unknown() -> None:
    rig = await loss_age_rig()
    await rig.clock.advance(301)
    assert rig.service.current_daily_loss_quote(DAY) is None
    assert_blocked(
        await rig.service.evaluate(now_utc=T0, exposure=False), BLOCKED_DAILY_LOSS_UNKNOWN
    )


async def test_the_age_edge_passes_when_equal_and_fails_one_millisecond_over() -> None:
    rig = await loss_age_rig()
    await rig.clock.advance(300)  # exactly the limit: equal passes (the D084 convention)
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("0")
    await rig.clock.advance(0.001)  # one millisecond over fails
    assert rig.service.current_daily_loss_quote(DAY) is None


async def test_a_stamp_in_the_future_is_unknown() -> None:
    rig = await loss_age_rig()
    rig.clock._now = T0 - timedelta(seconds=1)  # the clock went back: a negative age
    assert rig.service.current_daily_loss_quote(DAY) is None


async def test_a_new_backfill_renews_an_expired_loss() -> None:
    rig = await loss_age_rig()
    await rig.clock.advance(301)
    assert rig.service.current_daily_loss_quote(DAY) is None
    await rig.service.backfill(now_utc=T0 + timedelta(seconds=301))
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("0")
    await rig.clock.advance(299)  # counted from the new backfill, not from the first one
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("0")


async def test_a_failed_backfill_does_not_leave_an_old_stamp_to_renew_the_loss() -> None:
    rig = await loss_age_rig()
    rig.store.raise_next("add_components", RuntimeError("down"))
    await rig.service.backfill(now_utc=T0)
    assert rig.service.current_daily_loss_quote(DAY) is None


def test_the_loss_age_limit_is_required_and_has_no_default() -> None:
    arguments: dict[str, Any] = {
        "reader": ScriptedDayRiskReader(),
        "store": InMemoryDayRiskStore(),
        "equity": object(),
        "clock": lambda: T0,
        "symbols": {"BTCUSDT"},
        "quote_asset": "USDT",
        "funding_policy": UNVERIFIED,
        "parameter_set": PARAMS,
    }
    with pytest.raises(TypeError):
        LiveDayRiskService(**arguments)
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        LiveDayRiskService(**arguments, limits=only_limits(account_max_daily_loss_age_ms=None))
    assert caught.value.keys == ("account.max_daily_loss_age_ms",)


# ------------------------------------------------------------------------- module guards


def test_the_module_reads_no_wall_clock_no_sdk_or_adapter_and_no_order_endpoint() -> None:
    assert wall_clock_calls(MODULE) == []
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    for name in imported:
        assert not name.startswith(("src.adapters", "src.persistence", "src.db"))
        assert "binance" not in name and "sqlalchemy" not in name
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not any("order" in name or "cancel" in name for name in called)
    assert "USDT" not in MODULE.read_text(encoding="utf-8")
