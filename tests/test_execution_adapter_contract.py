"""Manager <-> real adapter contract tests (Phase 9 code-review fixes).

The Phase 9 execution tests inject `**kwargs` fakes, which hid real
signature mismatches between `src/execution/manager.py` and
`BinanceUsdmAdapter` (09-REVIEW CR-01 / WR-12). These tests bind the
exact kwargs the execution core produces against the REAL adapter
method signatures, and drive the real adapter methods against a fake
SDK so the wire-level parameters are pinned.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.execution.placement import ProtectiveTemplate, size_protectives_to_filled_qty
from src.risk.types import ConstraintSnapshot

_NOW = datetime(2026, 9, 19, 10, 30, tzinfo=UTC)
_SL_ID = "xa-194547b9a1659419ecfa4a736a3deceSL"
_T1_ID = "xa-194547b9a1659419ecfa4a736a3deceT1"


def _snapshot() -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=Decimal("0.01"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("5.00"),
        metadata_observed_at_utc=_NOW,
    )


def _template() -> ProtectiveTemplate:
    return ProtectiveTemplate(
        stop_loss_trigger_price=Decimal("98.00"),
        tp1_trigger_price=Decimal("106.00"),
        tp2_trigger_price=Decimal("110.00"),
        tp1_quantity_fraction=Decimal("0.5"),
    )


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _RecordingRest:
    """Fake SDK REST surface recording `new_algo_order` kwargs."""

    def __init__(self) -> None:
        self.new_algo_order_calls: list[dict[str, Any]] = []

    def new_algo_order(self, **kwargs: Any) -> _FakeResponse:
        self.new_algo_order_calls.append(kwargs)
        return _FakeResponse(
            SimpleNamespace(
                symbol=kwargs["symbol"],
                client_algo_id=kwargs["client_algo_id"],
                algo_id=123,
                algo_type="CONDITIONAL",
                order_type=str(kwargs["type"].value),
                side=str(kwargs["side"].value),
                position_side=kwargs["position_side"],
                algo_status="NEW",
                trigger_price=kwargs["trigger_price"],
                close_position=kwargs["close_position"].value == "true",
                working_type="MARK_PRICE",
                update_time=1_758_277_800_000,
            )
        )


def _adapter() -> tuple[BinanceUsdmAdapter, _RecordingRest]:
    rest = _RecordingRest()
    sdk = SimpleNamespace(rest_api=rest)
    return BinanceUsdmAdapter(sdk_client=sdk), rest  # type: ignore[arg-type]


@pytest.mark.parametrize("position_mode", ["ONE_WAY", "HEDGE"])
def test_every_sized_leg_binds_to_real_place_algo_protective_signature(
    position_mode: str,
) -> None:
    """CR-01: every leg dict the manager splats into
    `place_algo_protective(**leg)` must bind against the REAL adapter
    signature (no unexpected keyword such as `reduce_only`)."""
    sizing = size_protectives_to_filled_qty(
        filled_quantity=Decimal("0.300"),
        protective_template=_template(),
        constraint_snapshot=_snapshot(),
        position_mode=position_mode,
        candidate_position_side="LONG",
    )
    assert sizing.is_no_trade is False
    signature = inspect.signature(BinanceUsdmAdapter.place_algo_protective)
    for leg in (sizing.sl_leg, sizing.tp1_leg, sizing.tp2_leg):
        assert leg is not None
        signature.bind(None, symbol="BTCUSDT", client_algo_id=_SL_ID, **leg)


@pytest.mark.asyncio
async def test_one_way_tp1_is_sent_reduce_only_and_sl_omits_it() -> None:
    """CR-01: the real adapter forwards reduceOnly=true for the one-way
    TP1 leg and omits it on the closePosition SL leg."""
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
        NewAlgoOrderReduceOnlyEnum,
    )

    sizing = size_protectives_to_filled_qty(
        filled_quantity=Decimal("0.300"),
        protective_template=_template(),
        constraint_snapshot=_snapshot(),
        position_mode="ONE_WAY",
        candidate_position_side="LONG",
    )
    assert sizing.sl_leg is not None and sizing.tp1_leg is not None
    adapter, rest = _adapter()

    await adapter.place_algo_protective(symbol="BTCUSDT", client_algo_id=_SL_ID, **sizing.sl_leg)
    await adapter.place_algo_protective(symbol="BTCUSDT", client_algo_id=_T1_ID, **sizing.tp1_leg)

    sl_wire, tp1_wire = rest.new_algo_order_calls
    assert sl_wire["reduce_only"] is None
    assert tp1_wire["reduce_only"] is NewAlgoOrderReduceOnlyEnum.TRUE


@pytest.mark.asyncio
async def test_hedge_legs_omit_reduce_only() -> None:
    """CR-01: hedge mode omits reduceOnly on every leg (EXECUTION_SPEC §5)."""
    sizing = size_protectives_to_filled_qty(
        filled_quantity=Decimal("0.300"),
        protective_template=_template(),
        constraint_snapshot=_snapshot(),
        position_mode="HEDGE",
        candidate_position_side="LONG",
    )
    assert sizing.tp1_leg is not None
    adapter, rest = _adapter()
    await adapter.place_algo_protective(symbol="BTCUSDT", client_algo_id=_T1_ID, **sizing.tp1_leg)
    assert rest.new_algo_order_calls[0]["reduce_only"] is None


@pytest.mark.asyncio
async def test_close_position_with_reduce_only_is_rejected_before_any_sdk_call() -> None:
    """CR-01: closePosition=true is exclusive with reduceOnly."""
    adapter, rest = _adapter()
    with pytest.raises(ValueError, match="mutually exclusive"):
        await adapter.place_algo_protective(
            symbol="BTCUSDT",
            side="SELL",
            algo_type="CONDITIONAL",
            type="STOP_MARKET",
            position_side="BOTH",
            trigger_price=Decimal("98.00"),
            close_position=True,
            quantity=None,
            working_type="MARK_PRICE",
            client_algo_id=_SL_ID,
            reduce_only=True,
        )
    assert rest.new_algo_order_calls == []


@pytest.mark.asyncio
async def test_non_close_leg_without_quantity_is_rejected() -> None:
    """CR-01: an explicit-quantity leg without a quantity fails closed."""
    adapter, rest = _adapter()
    with pytest.raises(ValueError, match="requires an explicit quantity"):
        await adapter.place_algo_protective(
            symbol="BTCUSDT",
            side="SELL",
            algo_type="CONDITIONAL",
            type="TAKE_PROFIT_MARKET",
            position_side="BOTH",
            trigger_price=Decimal("106.00"),
            close_position=False,
            quantity=None,
            working_type="MARK_PRICE",
            client_algo_id=_T1_ID,
            reduce_only=True,
        )
    assert rest.new_algo_order_calls == []
