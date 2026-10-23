"""LiveDayRiskService stream path (Phase 21, plan 21-16; D-01, D-09, D-11, Pitfall 5).

Fakes only. The fills and rows below are SYNTHETIC test data (labelled), not Demo figures; the
recorded-frame proof is in ``tests/test_daily_loss_recorded.py``. Frames sent during a stream gap
are not replayed (demo-observed, not mainnet), which is why an invalidation makes the loss
unknown until a REST backfill completes AFTER it.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from src.adapters.binance_usdm import UserTradeRow
from src.domain.enums import DailyState
from src.execution.day_risk_service import (
    INVALIDATION_REASONS,
    LiveDayRiskService,
    components_from_fill,
)
from src.execution.fill_monitor import FillEvent
from src.persistence.errors import StoreUnavailable
from src.risk.daily_loss import (
    BLOCKED_DAILY_LOSS_UNKNOWN,
    ComponentKind,
    ComponentSource,
    DayStateVerdict,
)

from tests.support.ast_guards import wall_clock_calls
from tests.support.day_risk_fakes import (
    DayRiskRig,
    ScriptedDayRiskReader,
    build_day_risk_rig,
)

MODULE = Path(__file__).resolve().parent.parent / "src" / "execution" / "day_risk_service.py"
DAY = date(2026, 10, 23)
T0 = datetime(2026, 10, 23, 0, 5, 0, tzinfo=UTC)


def fill(
    pnl: str | None = "-1",
    commission: str | None = "0.5",
    *,
    asset: str | None = "USDT",
    order_id: str = "11",
    trade_id: str = "21",
    symbol: str = "BTCUSDT",
) -> FillEvent:
    """SYNTHETIC stream fill (labelled test data)."""
    return FillEvent(
        order_id=order_id,
        exchange_trade_id=trade_id,
        symbol=symbol,
        side="SELL",
        position_side="BOTH",
        fill_price=Decimal("100"),
        fill_quantity=Decimal("1"),
        fill_time_utc=T0,
        commission=None if commission is None else Decimal(commission),
        commission_asset=asset,
        realized_pnl=None if pnl is None else Decimal(pnl),
    )


def rest_row(pnl: str, commission: str, *, order_id: int = 11, trade_id: int = 21) -> UserTradeRow:
    """SYNTHETIC REST row; the default ids give the key of ``fill()``."""
    return UserTradeRow(
        symbol="BTCUSDT",
        order_id=order_id,
        trade_id=trade_id,
        realized_pnl=Decimal(pnl),
        commission=Decimal(commission),
        commission_asset="USDT",
        margin_asset="USDT",
        time_utc=T0,
    )


async def known_rig(reader: ScriptedDayRiskReader | None = None) -> DayRiskRig:
    """A rig after one complete backfill and one evaluate: the loss is known (0)."""
    rig = await build_day_risk_rig(start=T0, reader=reader)
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    return rig


def assert_unknown(verdict: DayStateVerdict) -> None:
    assert verdict.state is None
    assert verdict.blocked_reason == BLOCKED_DAILY_LOSS_UNKNOWN
    assert verdict.loss_quote is None


@pytest.mark.parametrize("reason", ["ACCOUNT_UPDATE", "STREAM_GAP"])
async def test_an_invalidation_makes_the_loss_unknown_until_the_next_backfill(reason: str) -> None:
    rig = await known_rig()
    rig.service.invalidate(reason=reason)
    assert_unknown(await rig.service.evaluate(now_utc=T0, exposure=False))
    assert rig.service.current_daily_loss_quote(DAY) is None
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert verdict.loss_quote == Decimal("0")


async def test_an_unknown_invalidation_reason_is_a_value_error_and_changes_nothing() -> None:
    assert INVALIDATION_REASONS == frozenset({"ACCOUNT_UPDATE", "STREAM_GAP"})
    rig = await known_rig()
    with pytest.raises(ValueError):
        rig.service.invalidate(reason="OTHER")
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL


async def test_an_invalidation_during_a_backfill_keeps_the_loss_unknown_after_it() -> None:
    armed = [True]
    holder: list[LiveDayRiskService] = []

    def invalidate_on_trades_read(method: str) -> None:
        if armed[0] and method == "user_trades_in_window":
            holder[0].invalidate(reason="STREAM_GAP")  # the gap arrives while the read awaits

    reader = ScriptedDayRiskReader(on_call=invalidate_on_trades_read)
    rig = await build_day_risk_rig(start=T0, reader=reader)
    holder.append(rig.service)
    await rig.service.backfill(now_utc=T0)
    assert rig.reader.count("user_trades_in_window") == 1
    assert_unknown(await rig.service.evaluate(now_utc=T0, exposure=False))
    assert rig.service.current_daily_loss_quote(DAY) is None
    armed[0] = False  # a second backfill with no invalidation restores the loss
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.state is DailyState.NORMAL
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("0")


@pytest.mark.parametrize(
    "unusable",
    [
        fill(commission=None),
        fill(asset=None),
        fill(pnl=None),
    ],
    ids=["no-commission", "no-commission-asset", "no-realized-pnl"],
)
async def test_an_unusable_fill_stores_nothing_and_leaves_the_loss_unknown(
    unusable: FillEvent,
) -> None:
    rig = await known_rig()
    assert components_from_fill(unusable, quote_asset="USDT") is None
    rig.service.ingest_fill(unusable)
    assert rig.store.list_components(DAY) == ()
    assert_unknown(await rig.service.evaluate(now_utc=T0, exposure=False))
    assert rig.service.current_daily_loss_quote(DAY) is None
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL


async def test_a_failed_fill_write_is_unknown_until_the_next_backfill_and_never_raises() -> None:
    rig = await known_rig()
    rig.store.raise_next("add_components", StoreUnavailable("down"))
    rig.service.ingest_fill(fill())  # must not raise to the stream router
    assert rig.service.last_error_type == "StoreUnavailable"
    assert_unknown(await rig.service.evaluate(now_utc=T0, exposure=False))
    await rig.service.backfill(now_utc=T0)
    assert (await rig.service.evaluate(now_utc=T0, exposure=False)).state is DailyState.NORMAL


async def test_a_stream_fill_between_backfills_adds_to_the_loss() -> None:
    rig = await known_rig()
    rig.service.ingest_fill(fill("-1", "0.5"))
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.loss_quote == Decimal("1.5")
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("1.5")
    # A second fill counts after the last evaluate too: the quote is folded on each call.
    rig.service.ingest_fill(fill("-2", "0", order_id="12", trade_id="22"))
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("3.5")


async def test_the_most_adverse_of_stream_and_rest_counts_once_for_the_same_trade() -> None:
    # Stream says pnl -1 / commission 0.5 (loss 1.5); REST says pnl -3 / commission 0.5 (loss 3.5).
    rig = await known_rig(ScriptedDayRiskReader(trades={"BTCUSDT": (rest_row("-3", "0.5"),)}))
    rig.service.ingest_fill(fill("-1", "0.5"))
    await rig.service.backfill(now_utc=T0)
    verdict = await rig.service.evaluate(now_utc=T0, exposure=False)
    assert verdict.loss_quote == Decimal("3.5")  # the larger loss, counted once
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("3.5")
    # The other way round: REST milder than the stream still counts the stream amount.
    rig2 = await known_rig(ScriptedDayRiskReader(trades={"BTCUSDT": (rest_row("-0.5", "0.5"),)}))
    rig2.service.ingest_fill(fill("-1", "0.5"))
    await rig2.service.backfill(now_utc=T0)
    assert rig2.service.current_daily_loss_quote(DAY) == Decimal("1.5")


async def test_stream_and_rest_rows_are_kept_as_two_sources_of_one_key() -> None:
    rig = await known_rig(ScriptedDayRiskReader(trades={"BTCUSDT": (rest_row("-3", "0.5"),)}))
    rig.service.ingest_fill(fill("-1", "0.5"))
    await rig.service.backfill(now_utc=T0)
    sources = {(c.kind, c.source) for c in rig.store.list_components(DAY)}
    assert sources == {
        (ComponentKind.FILL_PNL, ComponentSource.USER_DATA_EVENT),
        (ComponentKind.FILL_COMMISSION, ComponentSource.USER_DATA_EVENT),
        (ComponentKind.FILL_PNL, ComponentSource.REST_USER_TRADES),
        (ComponentKind.FILL_COMMISSION, ComponentSource.REST_USER_TRADES),
    }


async def test_current_daily_loss_quote_is_none_for_a_day_that_was_never_evaluated() -> None:
    rig = await build_day_risk_rig(start=T0)
    assert rig.service.current_daily_loss_quote(DAY) is None
    await rig.service.backfill(now_utc=T0)  # complete backfill, but the day was never opened
    assert rig.service.current_daily_loss_quote(DAY) is None
    await rig.service.evaluate(now_utc=T0, exposure=False)
    assert rig.service.current_daily_loss_quote(DAY) == Decimal("0")
    assert rig.service.current_daily_loss_quote(date(2026, 10, 22)) is None


async def test_a_fill_in_another_asset_or_a_foreign_symbol_leaves_the_loss_unknown() -> None:
    rig = await known_rig()
    rig.service.ingest_fill(fill(asset="BNB"))  # commission paid in BNB: not a quote amount
    assert_unknown(await rig.service.evaluate(now_utc=T0, exposure=False))
    rig2 = await known_rig()
    foreign = components_from_fill(fill(symbol="BTCEUR"), quote_asset="USDT")
    assert foreign is not None and foreign[0].asset == "BTCEUR"
    rig2.service.ingest_fill(fill(symbol="BTCEUR"))
    assert_unknown(await rig2.service.evaluate(now_utc=T0, exposure=False))


async def test_a_conflicting_redelivery_is_unknown_and_never_raises() -> None:
    rig = await known_rig()
    rig.service.ingest_fill(fill("-1", "0.5"))
    rig.service.ingest_fill(replace(fill("-1", "0.5"), realized_pnl=Decimal("-9")))
    assert rig.service.last_error_type == "RowConflict"
    assert rig.service.current_daily_loss_quote(DAY) is None


def test_the_module_reads_no_wall_clock_and_imports_no_adapter_persistence_or_sdk() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert wall_clock_calls(MODULE) == []
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    forbidden = ("src.adapters", "src.persistence", "binance")
    assert not [name for name in imported if name.startswith(forbidden)]
