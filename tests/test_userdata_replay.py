"""Replay proof of the stream fill path (Phase 18, plan 18-15 Task 3, D-06, D-21, research P13).

Three SYNTHETIC TRADE frames of one order (`tests/support/userdata_frames.py`, label
`SYNTHETIC_FROM_SDK_MODEL`; never captured Binance data) go through the real parser, the real
router and the unchanged `fold_fills`. Every delivery order of the multiset {A, A, B, B, C}
(30 distinct orderings), a replay of the whole sequence and a dropped frame healed by the REST
fills fallback all give the same `FoldedPositionView`. The one way to break it is pinned as a
negative control: folding stream fills together with a REST-synthetic fill keyed
`position-view:<order_id>` (scripts/demo_rehearsal.py) double counts.

No network, no clock (the router's clock is a constant) and no randomness beyond the
deterministic `itertools` permutations.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.adapters.binance_userdata_events import (
    OrderUpdateEvent,
    StreamAnomalyKind,
    parse_stream_message,
    to_fill_event,
)
from src.adapters.binance_userdata_router import (
    FillSource,
    KnownOrder,
    StreamDivergenceKind,
)
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.domain.enums import OrderRole, OrderStatus
from src.domain.stream_records import STREAM_ANOMALY
from src.execution.fill_monitor import (
    CurrentPositionView,
    FillEvent,
    FoldedPositionView,
    fold_fills,
)

from tests.support.ast_guards import forbidden_imports, wall_clock_calls
from tests.support.stream_sinks import (
    FakeOrderLookup,
    RecordingJournal,
    RecordingSinks,
    make_router,
)
from tests.support.userdata_frames import FRAME_LABEL, order_trade_update_frame
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START

T0 = TEST_ONLY_VIRTUAL_START
ORDER_ID = 8_000_000_001  # the frame builder's default exchange order id
ENTRY = KnownOrder(
    local_order_id="test-only-local-order-0001",
    client_id="synthetic-entry-0001",  # the frame builder's default client order id
    symbol="BTCUSDT",
    role=OrderRole.ENTRY,
    local_status=OrderStatus.NEW,
)
FLAT = CurrentPositionView(symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0"))

# One 0.010 order filled by three trades (synthetic): 0.004 + 0.003 + 0.003.
FRAMES: dict[str, dict[str, Any]] = {
    "A": order_trade_update_frame(t=901, l="0.004", z="0.004", X="PARTIALLY_FILLED"),
    "B": order_trade_update_frame(t=902, l="0.003", z="0.007", X="PARTIALLY_FILLED"),
    "C": order_trade_update_frame(t=903, l="0.003", z="0.010", X="FILLED"),
}
ORDER_QUANTITY = Decimal("0.010")


def _parsed(name: str) -> OrderUpdateEvent:
    outcome = parse_stream_message(FRAMES[name], observed_at_utc=T0)
    assert isinstance(outcome, OrderUpdateEvent)
    return outcome


def _fill(name: str) -> FillEvent:
    fill = to_fill_event(_parsed(name))
    assert fill is not None
    return fill


# The REST trades list of the order (account_trade_list shape: real trade ids, same values).
REST_TRADES: list[FillEvent] = [_fill(name) for name in "ABC"]


@dataclass
class Run:
    view: FoldedPositionView
    sinks: RecordingSinks
    journal: RecordingJournal


def run(sequence: Iterable[str]) -> Run:
    """Parse and route every named frame in order through one router, then fold the fills."""
    sinks = RecordingSinks()
    sinks.fallback_fills[str(ORDER_ID)] = list(REST_TRADES)
    journal = RecordingJournal()
    router = make_router(
        lookup=FakeOrderLookup.of(orders=[ENTRY]),
        journal=journal,
        sinks=sinks,
        clock=lambda: T0,
    )
    for index, name in enumerate(sequence):
        received = T0 + timedelta(milliseconds=index)
        outcome = parse_stream_message(FRAMES[name], observed_at_utc=received)
        router.route(
            TrustedEvent(
                outcome=outcome, received_at_utc=received, connection_epoch=1, after_gap=False
            )
        )
    view = fold_fills(fill_events=sinks.fill_events(), current_position_view=FLAT)
    return Run(view=view, sinks=sinks, journal=journal)


def assert_same_view(actual: FoldedPositionView, expected: FoldedPositionView) -> None:
    keys = [(f["order_id"], f["exchange_trade_id"]) for f in actual.fills]
    assert keys == [(f["order_id"], f["exchange_trade_id"]) for f in expected.fills]
    assert actual.fills == expected.fills
    assert actual.filled_quantity == expected.filled_quantity
    assert actual.fill_count == expected.fill_count
    assert actual.position_amt == expected.position_amt
    assert actual == expected


BASELINE = run("ABC")


def test_frames_are_labelled_synthetic() -> None:
    assert FRAME_LABEL == "SYNTHETIC_FROM_SDK_MODEL"


def test_baseline_is_the_whole_order() -> None:
    assert BASELINE.view.filled_quantity == ORDER_QUANTITY
    assert BASELINE.view.position_amt == ORDER_QUANTITY
    assert BASELINE.view.fill_count == 3
    assert [f["exchange_trade_id"] for f in BASELINE.view.fills] == ["901", "902", "903"]
    assert BASELINE.sinks.fallback_calls == []
    assert BASELINE.journal.events == {}


def test_every_ordering_of_duplicates_and_reorders_gives_one_view() -> None:
    orderings = sorted(set(itertools.permutations("AABBC")))
    assert len(orderings) == 30

    healed_by_fallback = 0
    for ordering in orderings:
        result = run(ordering)
        assert_same_view(result.view, BASELINE.view)
        if result.sinks.fallback_calls:
            healed_by_fallback += 1
            # Newest first: the mismatch is reported and healed once per accumulated value.
            assert result.sinks.fallback_calls == [str(ORDER_ID)]
    # Both paths are exercised: C before every A and B is answered by REST, the rest is not.
    assert 0 < healed_by_fallback < len(orderings)


def test_replaying_the_whole_sequence_gives_the_same_view_as_once() -> None:
    for sequence in ("ABC", "CBA", "AABBC", "BCA"):
        once = run(sequence)
        twice = run(sequence + sequence)
        assert_same_view(twice.view, once.view)
        assert_same_view(twice.view, BASELINE.view)
        # The replay adds no anomaly record and no second fallback call.
        assert twice.sinks.fallback_calls == once.sinks.fallback_calls
        assert set(twice.journal.events) == set(once.journal.events)


def test_a_dropped_frame_is_detected_on_the_latest_value_and_healed_by_rest() -> None:
    result = run("AC")  # B never arrives

    anomalies = result.journal.by_type(STREAM_ANOMALY)
    assert len(anomalies) == 1
    assert StreamAnomalyKind.FILL_TOTAL_MISMATCH.value in anomalies[0].payload_json
    assert [d.kind for d in result.sinks.divergences] == [
        StreamDivergenceKind.STREAM_FILL_TOTAL_MISMATCH
    ]
    assert result.sinks.fallback_calls == [str(ORDER_ID)]
    rest_fills = [r.fill for r in result.sinks.fills if r.source is FillSource.REST_FALLBACK]
    assert "902" in {fill.exchange_trade_id for fill in rest_fills}
    assert_same_view(result.view, BASELINE.view)


def test_a_dropped_latest_frame_cannot_be_seen_by_the_total_check() -> None:
    # Pinned limit: without the latest accumulated value the stream is self-consistent;
    # only the REST snapshot (the supervisor's baseline) can reveal the missing C.
    result = run("AB")
    assert result.sinks.fallback_calls == []
    assert result.journal.events == {}
    assert result.view.filled_quantity == Decimal("0.007")


def test_negative_control_rest_synthetic_key_space_double_counts() -> None:
    stream_fills = BASELINE.sinks.fill_events()
    synthetic = FillEvent(
        order_id=str(ORDER_ID),
        exchange_trade_id=f"position-view:{ORDER_ID}",
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        fill_price=Decimal("60000.00"),
        fill_quantity=ORDER_QUANTITY,
        fill_time_utc=T0,
    )
    mixed = fold_fills(fill_events=[*stream_fills, synthetic], current_position_view=FLAT)
    assert mixed.filled_quantity == 2 * ORDER_QUANTITY, (
        "expected double counting: the REST-synthetic key position-view:<order_id> and the "
        "stream trade ids are two key spaces, so fold_fills cannot de-duplicate them (P13)"
    )
    assert mixed.position_amt == 2 * ORDER_QUANTITY


def test_control_rest_trades_with_real_ids_dedup_to_the_stream_view() -> None:
    stream_fills = BASELINE.sinks.fill_events()
    combined = fold_fills(fill_events=[*stream_fills, *REST_TRADES], current_position_view=FLAT)
    assert_same_view(combined, BASELINE.view)
    rest_first = fold_fills(fill_events=[*REST_TRADES, *stream_fills], current_position_view=FLAT)
    assert_same_view(rest_first, BASELINE.view)


def test_replay_file_uses_no_clock_no_network_and_no_randomness() -> None:
    path = Path(__file__)
    assert wall_clock_calls(path) == []
    assert forbidden_imports(path, ["random", "socket", "httpx", "requests", "time"]) == []
