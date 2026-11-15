"""The project's own emergency-close order is not an unknown stream order.

First Demo run, 2026-11-01: the operator close of a restored plan sent `xc-<plan>0001`, the stream
reported it, the router called it unknown, and the reconcile entered SAFE_MODE
(UNTRACKED_SYSTEM_ORDER) four seconds after a clean close.
"""

from __future__ import annotations

from typing import Any

from src.adapters.binance_userdata_events import parse_stream_message
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.domain.stream_records import STREAM_ANOMALY
from src.execution.order_ids import derive_client_order_id, derive_close_order_id
from src.live.order_index import ClientIdIndex

from tests.support.stream_sinks import RecordingJournal, RecordingSinks, make_router
from tests.support.userdata_frames import order_trade_update_frame
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START

PLAN_HASH = "ab" * 32
OTHER_PLAN_HASH = "cd" * 32


def _index_with_plan() -> ClientIdIndex:
    index = ClientIdIndex()
    index.register_entry(
        plan_hash=PLAN_HASH,
        client_order_id=derive_client_order_id(plan_hash=PLAN_HASH, role="ENTRY"),
        symbol="BTCUSDT",
    )
    return index


def _route(index: ClientIdIndex, client_id: str) -> tuple[Any, RecordingSinks, RecordingJournal]:
    sinks, journal = RecordingSinks(), RecordingJournal()
    router = make_router(
        lookup=index, journal=journal, sinks=sinks, clock=lambda: TEST_ONLY_VIRTUAL_START
    )
    outcome = parse_stream_message(
        order_trade_update_frame(c=client_id), observed_at_utc=TEST_ONLY_VIRTUAL_START
    )
    result = router.route(
        TrustedEvent(
            outcome=outcome,
            received_at_utc=TEST_ONLY_VIRTUAL_START,
            connection_epoch=1,
            after_gap=False,
        )
    )
    return result, sinks, journal


def test_close_order_of_a_known_plan_is_ignored_without_anomaly_or_divergence() -> None:
    close_id = derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=1)

    result, sinks, journal = _route(_index_with_plan(), close_id)

    assert result.handled is True
    assert sinks.divergences == [] and sinks.fills == [] and sinks.status_hints == []
    assert journal.by_type(STREAM_ANOMALY) == []


def test_every_attempt_number_of_a_known_plan_is_recognised() -> None:
    index = _index_with_plan()

    assert all(
        index.is_close_order(derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=n))
        for n in (1, 2, 9999)
    )


def test_close_order_of_an_unknown_plan_is_still_an_unknown_order() -> None:
    close_id = derive_close_order_id(plan_hash=OTHER_PLAN_HASH, attempt_no=1)

    _, sinks, journal = _route(_index_with_plan(), close_id)

    assert len(sinks.divergences) == 1
    assert len(journal.by_type(STREAM_ANOMALY)) == 1


def test_entry_and_foreign_ids_are_not_close_orders() -> None:
    index = _index_with_plan()

    assert not index.is_close_order(derive_client_order_id(plan_hash=PLAN_HASH, role="ENTRY"))
    assert not index.is_close_order("web_3kF9aQ")
