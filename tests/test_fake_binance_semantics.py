"""BinanceSemanticsFakeAdapter: SDK-shaped errors and the evidence status of its assumptions.

Phase 18, plan 18-21 Task 2 (D-17). The fake used to raise `RuntimeError` text; it now raises the
SDK's `BadRequestError` with an int `status_code`, so the production error path
(`error_facts_from_exception` then `classify`) sees what the real adapter sees.

The three assumptions of the fake each have one test and one evidence status, taken from
`.planning/phases/18-user-data-stream-error-taxonomy/evidence/18-probe-check.txt` (the second
Demo probe run, 2026-10-16T17:36:12Z, lines 66 to 69, and the first run, lines 33 to 36 and
50 to 53).
Everything below is Demo evidence, not mainnet:

1. a client id is unique among OPEN orders: confirmed on Demo for `clientAlgoId` (-4116); NOT
   validated against Demo for a normal order (not observed).
2. a CANCELED order frees its client id: confirmed on Demo, normal and algo order.
3. a FILLED order frees its client id: confirmed on Demo for a normal order (second run).

The 3-day retention rule of the fake is a documentation rule the probe does not test: NOT
validated against Demo.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError
from src.adapters.binance_errors import error_facts_from_exception
from src.domain.exchange_errors import (
    CallKind,
    ExchangeErrorCategory,
    HttpClass,
    classify,
    retry_eligible,
    safe_mode_eligible,
)

from tests.support.fake_binance_exchange import (
    DUPLICATE_CLIENT_ID_CODE,
    HISTORY_RETENTION,
    BinanceSemanticsFakeAdapter,
)

ROOT = Path(__file__).resolve().parent.parent
PROBE_CHECK = (
    ROOT
    / ".planning"
    / "phases"
    / "18-user-data-stream-error-taxonomy"
    / "evidence"
    / "18-probe-check.txt"
)

CLIENT_ID = "test-only-client-0001"
ALGO_ID = "test-only-algo-0001"


def _entry_kwargs(client_id: str = CLIENT_ID) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "time_in_force": "GTC",
        "quantity": Decimal("0.0008"),
        "price": Decimal("78000.0"),
        "new_client_order_id": client_id,
    }


def _algo_kwargs(client_algo_id: str = ALGO_ID) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "algo_type": "CONDITIONAL",
        "type": "STOP_MARKET",
        "position_side": "BOTH",
        "trigger_price": Decimal("77000.0"),
        "close_position": False,
        "quantity": Decimal("0.0008"),
        "working_type": "MARK_PRICE",
        "client_algo_id": client_algo_id,
        "reduce_only": True,
    }


# --------------------------------------------------------------------------- #
# The probe check file is what the statuses below cite.
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not PROBE_CHECK.is_file(),
    reason="the Phase 18 probe check file is not in this checkout (archived or filtered)",
)
def test_the_probe_check_file_backs_the_three_statuses() -> None:
    text = PROBE_CHECK.read_text(encoding="utf-8")
    assert "probe postponed by the user" not in text  # PROBE_RAN
    assert (
        "The three assumptions of BinanceSemanticsFakeAdapter, updated by the second run:" in text
    )
    assert (
        "1 a client id is unique among OPEN orders: agrees with the probe for clientAlgoId "
        "(-4116 while the first is open); not observed for a normal order"
    ) in text
    assert "2 a CANCELED order frees its client id: agrees with the probe (normal and algo)" in text
    assert (
        "3 a FILLED order frees its client id: agrees with the probe (normal order: the reused "
        "id was accepted after FILLED)"
    ) in text
    assert (
        "duplicate clientAlgoId while the first is open (status NEW): rejected (BAD_REQUEST, "
        '-4116, DUPLICATE_CLIENT_ID, "ClientOrderId is duplicated.")'
    ) in text


# --------------------------------------------------------------------------- #
# SDK-shaped errors.
# --------------------------------------------------------------------------- #


async def test_duplicate_open_client_order_id_raises_a_sdk_bad_request_with_int_code() -> None:
    adapter = BinanceSemanticsFakeAdapter()
    await adapter.place_entry(**_entry_kwargs())
    with pytest.raises(BadRequestError) as caught:
        await adapter.place_entry(**_entry_kwargs())
    assert caught.value.status_code == -4116
    assert type(caught.value.status_code) is int
    assert DUPLICATE_CLIENT_ID_CODE == -4116

    facts = error_facts_from_exception(caught.value)
    assert facts.http_class is HttpClass.BAD_REQUEST
    assert facts.code == -4116
    category = classify(facts, CallKind.PLACEMENT)
    assert category is ExchangeErrorCategory.DUPLICATE_CLIENT_ID
    assert retry_eligible(category, CallKind.PLACEMENT) is False
    assert safe_mode_eligible(category) is False


async def test_duplicate_open_client_algo_id_raises_the_observed_demo_error() -> None:
    """Corrected: the probe observed -4116 for the duplicate clientAlgoId (check file line 33)."""
    adapter = BinanceSemanticsFakeAdapter()
    await adapter.place_algo_protective(**_algo_kwargs())
    with pytest.raises(BadRequestError) as caught:
        await adapter.place_algo_protective(**_algo_kwargs())
    assert caught.value.status_code == -4116
    assert type(caught.value.status_code) is int
    assert caught.value.error_message == "ClientOrderId is duplicated."  # the Demo text

    facts = error_facts_from_exception(caught.value)
    assert (facts.http_class, facts.code) == (HttpClass.BAD_REQUEST, -4116)
    assert classify(facts, CallKind.PLACEMENT) is ExchangeErrorCategory.DUPLICATE_CLIENT_ID


# --------------------------------------------------------------------------- #
# One test per assumption, with its evidence status.
# --------------------------------------------------------------------------- #


async def test_assumption_1_a_duplicate_is_rejected_only_while_the_first_is_open() -> None:
    """Assumption 1 (check file lines 51 and 67).

    clientAlgoId: confirmed on Demo 2026-10-16, not mainnet (-4116 while the first is open).
    Normal order: NOT validated against Demo: not observed for a normal order; the fake keeps
    -4116 as the page documents it ('clientOrderId is duplicated').
    """
    adapter = BinanceSemanticsFakeAdapter()
    await adapter.place_algo_protective(**_algo_kwargs())
    with pytest.raises(BadRequestError):
        await adapter.place_algo_protective(**_algo_kwargs())
    adapter.cancel_algo(ALGO_ID)
    await adapter.place_algo_protective(**_algo_kwargs())  # only while open
    assert len(adapter.open_algos) == 1

    await adapter.place_entry(**_entry_kwargs())
    with pytest.raises(BadRequestError) as caught:
        await adapter.place_entry(**_entry_kwargs())
    assert caught.value.status_code == -4116  # NOT validated against Demo for a normal order


async def test_assumption_2_a_canceled_order_frees_its_client_id() -> None:
    """Assumption 2 (check file lines 34, 35, 52 and 68): confirmed on Demo 2026-10-16, not
    mainnet, for a normal order and for an algo order."""
    adapter = BinanceSemanticsFakeAdapter()
    await adapter.place_entry(**_entry_kwargs())
    adapter.cancel(CLIENT_ID)
    second = await adapter.place_entry(**_entry_kwargs())
    assert second.status == "NEW"

    await adapter.place_algo_protective(**_algo_kwargs())
    adapter.cancel_algo(ALGO_ID)
    again = await adapter.place_algo_protective(**_algo_kwargs())
    assert again.algo_status == "NEW"
    assert len(adapter.calls_to("place_entry")) == 2


async def test_assumption_3_a_filled_order_frees_its_client_id() -> None:
    """Assumption 3 (check file lines 64 and 69): confirmed on Demo 2026-10-16, not mainnet,
    for a normal order (second probe run, id_reuse_after_filled)."""
    adapter = BinanceSemanticsFakeAdapter()
    first = await adapter.place_entry(**_entry_kwargs())
    adapter.fill(CLIENT_ID)
    second = await adapter.place_entry(**_entry_kwargs())
    assert second.status == "NEW"
    assert second.exchange_order_id != first.exchange_order_id  # a new order id, as on Demo


async def test_retention_rule_is_not_validated_against_demo_and_keeps_its_behavior() -> None:
    """NOT validated against Demo: the 3-day retention rule is a documentation rule the probe
    does not test (check file line 54); the behavior is unchanged."""
    adapter = BinanceSemanticsFakeAdapter()
    await adapter.place_entry(**_entry_kwargs())
    adapter.cancel(CLIENT_ID)
    adapter.now_utc += HISTORY_RETENTION + timedelta(seconds=1)
    probe = await adapter.query_order_by_client(symbol="BTCUSDT", orig_client_order_id=CLIENT_ID)
    assert probe.found is False


async def test_the_fake_returns_the_result_types_of_the_real_adapter() -> None:
    """Review WR-09: the shapes match the production surface, not only the call kwargs."""
    from src.adapters.binance_usdm import AlgoPlacementResult, EntryPlacementResult

    adapter = BinanceSemanticsFakeAdapter()
    entry = await adapter.place_entry(**_entry_kwargs())
    algo = await adapter.place_algo_protective(**_algo_kwargs())
    assert isinstance(entry, EntryPlacementResult)
    assert isinstance(algo, AlgoPlacementResult)
    assert entry.exchange_order_id is not None
    assert algo.algo_id is not None


async def test_the_query_update_time_moves_with_a_fill_or_a_cancel() -> None:
    adapter = BinanceSemanticsFakeAdapter()
    await adapter.place_entry(**_entry_kwargs())
    created = adapter.now_utc
    adapter.now_utc = created + timedelta(minutes=5)
    adapter.fill(CLIENT_ID)
    probe = await adapter.query_order_by_client(symbol="BTCUSDT", orig_client_order_id=CLIENT_ID)
    assert probe.status == "FILLED"
    assert probe.update_time_utc == created + timedelta(minutes=5)

    await adapter.place_algo_protective(**_algo_kwargs())
    adapter.now_utc = created + timedelta(minutes=9)
    adapter.cancel_algo(ALGO_ID)
    algo_probe = await adapter.query_algo_order_by_client(client_algo_id=ALGO_ID)
    assert algo_probe.update_time_utc == created + timedelta(minutes=9)
