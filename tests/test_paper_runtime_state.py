"""Runtime state port: deterministic ids, replay safety, restart restore (Phase 16, plan 16-16).

The behaviours are written once as `contract_*` functions that take a port factory, so the
in-memory implementation (this file) and the PostgreSQL implementation
(`tests/test_paper_runtime_state_pg.py`) are held to exactly the same rules.

Research Pattern 3 and Pitfall P11: record ids are a pure function of the epoch and the bar
close (or the tick time and its batch sequence), never of the wall clock.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from src.paper.runtime_state import (
    InMemoryRuntimeState,
    RuntimeRecord,
    RuntimeRecordConflict,
    RuntimeStatePort,
    runtime_event_id,
)
from src.paper.vocabulary import RuntimeEventType

EPOCH = "a" * 64
OTHER_EPOCH = "b" * 64
T0 = datetime(2026, 10, 9, 0, 0, 0, tzinfo=UTC)
ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)

PortFactory = Callable[[], RuntimeStatePort]


def bar_close(hour: int) -> datetime:
    """The exchange close of the 1h bar that opens at hour `hour`: open + 1h - 1 ms."""
    return T0 + timedelta(hours=hour) + ONE_HOUR - ONE_MS


def bar(
    hour: int,
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    epoch_id: str = EPOCH,
    source: str = "LIVE_WS",
) -> RuntimeRecord:
    return RuntimeRecord.bar_processed(
        epoch_id=epoch_id,
        symbol=symbol,
        interval=interval,
        close_time_utc=bar_close(hour),
        payload={
            "source": source,
            "tick_time_utc": bar_close(hour) + timedelta(seconds=2),
        },
    )


def marker(
    event_type: RuntimeEventType, at: datetime, *, epoch_id: str = EPOCH, **payload: object
) -> RuntimeRecord:
    return RuntimeRecord(
        event_type=event_type, epoch_id=epoch_id, occurred_at_utc=at, payload=dict(payload)
    )


def tick_stats(at: datetime, batch_seq: int, *, duration_ms: int = 12) -> RuntimeRecord:
    return RuntimeRecord(
        event_type=RuntimeEventType.PAPER_TICK_STATS,
        epoch_id=EPOCH,
        occurred_at_utc=at,
        payload={
            "batch_seq": batch_seq,
            "duration_ms": duration_ms,
            "queue_depth_before": 0,
            "dropped_total": 0,
            "dropped_by_reason": {},
        },
    )


def simulated_session() -> list[RuntimeRecord]:
    """One short session: start, pin, three processed bars of two pairs, a gap, a stop."""
    return [
        marker(RuntimeEventType.RUNTIME_START, T0),
        marker(RuntimeEventType.EPOCH_PINNED, T0 + timedelta(seconds=1), strategy="trend-pullback"),
        bar(0),
        bar(1),
        bar(2),
        bar(0, symbol="ETHUSDT"),
        bar(1, symbol="ETHUSDT"),
        RuntimeRecord(
            event_type=RuntimeEventType.PAPER_GAP,
            epoch_id=EPOCH,
            occurred_at_utc=bar_close(3) + timedelta(seconds=5),
            symbol="BTCUSDT",
            interval="1h",
            payload={"expected_close_utc": bar_close(3), "reason": "WS_DISCONNECTED"},
        ),
        marker(RuntimeEventType.WS_DISCONNECT, T0 + timedelta(hours=3, minutes=5)),
        marker(RuntimeEventType.WS_RECONNECT, T0 + timedelta(hours=3, minutes=6)),
        marker(
            RuntimeEventType.HEALTH_STATE_CHANGED,
            T0 + timedelta(hours=3, minutes=6),
            state="HEALTHY",
        ),
        tick_stats(T0 + timedelta(hours=3, minutes=7), 0),
        tick_stats(T0 + timedelta(hours=3, minutes=7), 1),
        marker(RuntimeEventType.RUNTIME_STOP, T0 + timedelta(hours=4)),
    ]


# --------------------------------------------------------------------------- #
# Behaviour contract shared with the PostgreSQL implementation.
# --------------------------------------------------------------------------- #


def contract_restores_last_close_and_marker(make: PortFactory) -> None:
    """Test 1 and Test 4: the later close per pair and the latest start or stop marker."""
    port = make()
    port.record(marker(RuntimeEventType.RUNTIME_START, T0))
    port.record(marker(RuntimeEventType.EPOCH_PINNED, T0 + timedelta(seconds=1)))
    port.record(bar(0))
    port.record(bar(1))
    port.record(bar(0, symbol="ETHUSDT", interval="4h"))
    closes = port.last_close_by_pair(EPOCH)
    assert closes == {("BTCUSDT", "1h"): bar_close(1), ("ETHUSDT", "4h"): bar_close(0)}
    start = port.latest_runtime_marker(EPOCH)
    assert start is not None
    assert start.event_type is RuntimeEventType.RUNTIME_START
    assert start.occurred_at_utc == T0
    port.record(marker(RuntimeEventType.RUNTIME_STOP, T0 + timedelta(hours=2)))
    stop = port.latest_runtime_marker(EPOCH)
    assert stop is not None
    assert stop.event_type is RuntimeEventType.RUNTIME_STOP
    assert stop.occurred_at_utc == T0 + timedelta(hours=2)
    assert port.last_close_by_pair(OTHER_EPOCH) == {}
    assert port.latest_runtime_marker(OTHER_EPOCH) is None


def contract_replay_is_a_no_op_and_different_content_conflicts(make: PortFactory) -> None:
    """Test 2: the same record twice stores one row; the same id with other content conflicts."""
    port = make()
    first = bar(0)
    port.record(first)
    port.record(first)
    port.record(bar(0))  # an equal record built a second time
    stored = port.records(EPOCH)
    assert len(stored) == 1
    assert stored[0] == first
    changed = bar(0, source="REST_BACKFILL")
    assert runtime_event_id(changed) == runtime_event_id(first)
    with pytest.raises(RuntimeRecordConflict):
        port.record(changed)
    assert port.records(EPOCH) == stored


def contract_bar_record_time_is_the_bar_close(make: PortFactory) -> None:
    """Test 3: occurred_at_utc is the close, not the moment of recording."""
    port = make()
    port.record(bar(5))
    (stored,) = port.records(EPOCH)
    assert stored.occurred_at_utc == bar_close(5)
    assert stored.occurred_at_utc.tzinfo is not None
    assert stored.occurred_at_utc.utcoffset() == timedelta(0)


def contract_tick_stats_ids_use_the_batch_sequence(make: PortFactory) -> None:
    """Test 5: same millisecond with different batch_seq is two rows; the same record is one."""
    port = make()
    at = T0 + timedelta(hours=1, microseconds=250)
    first = tick_stats(at, 0)
    second = tick_stats(at, 1)
    assert runtime_event_id(first) != runtime_event_id(second)
    port.record(first)
    port.record(second)
    port.record(first)
    port.record(second)
    stored = port.records(EPOCH, {RuntimeEventType.PAPER_TICK_STATS})
    assert len(stored) == 2
    assert {r.payload["batch_seq"] for r in stored} == {0, 1}
    with pytest.raises(RuntimeRecordConflict):
        port.record(tick_stats(at, 1, duration_ms=999))


def contract_a_full_session_replays_to_the_same_rows(make: PortFactory) -> None:
    """Replaying a whole session a second time adds nothing and raises nothing."""
    port = make()
    session = simulated_session()
    for record in session:
        port.record(record)
    before = port.records(EPOCH)
    assert len(before) == len(session)
    for record in session:
        port.record(record)
    assert port.records(EPOCH) == before
    assert port.last_close_by_pair(EPOCH) == {
        ("BTCUSDT", "1h"): bar_close(2),
        ("ETHUSDT", "1h"): bar_close(1),
    }


def contract_records_are_filtered_and_ordered(make: PortFactory) -> None:
    port = make()
    for record in reversed(simulated_session()):
        port.record(record)
    port.record(bar(0, epoch_id=OTHER_EPOCH))
    ours = port.records(EPOCH)
    assert all(r.epoch_id == EPOCH for r in ours)
    assert [r.occurred_at_utc for r in ours] == sorted(r.occurred_at_utc for r in ours)
    only_bars = port.records(EPOCH, {RuntimeEventType.PAPER_BAR_PROCESSED})
    assert {r.event_type for r in only_bars} == {RuntimeEventType.PAPER_BAR_PROCESSED}
    assert len(only_bars) == 5
    gap = port.records(EPOCH, {RuntimeEventType.PAPER_GAP})
    assert len(gap) == 1
    assert gap[0].symbol == "BTCUSDT"
    assert gap[0].interval == "1h"
    assert gap[0].payload["reason"] == "WS_DISCONNECTED"


def contract_payload_survives_the_round_trip(make: PortFactory) -> None:
    """Payload values come back equal, with Decimal and datetime in canonical text form."""
    port = make()
    original = RuntimeRecord(
        event_type=RuntimeEventType.HEALTH_STATE_CHANGED,
        epoch_id=EPOCH,
        occurred_at_utc=T0,
        payload={
            "state": "DEGRADED",
            "reason": "WS_RECONNECT_WINDOW",
            "ratio": Decimal("0.950"),
            "since": T0,
            "counts": [1, 2, 3],
            "nested": {"b": True, "a": None},
        },
    )
    port.record(original)
    (stored,) = port.records(EPOCH)
    assert stored == original
    assert stored.payload["ratio"] == "0.950"
    assert stored.payload["since"] == T0.isoformat()
    assert stored.payload["counts"] == (1, 2, 3)


# --------------------------------------------------------------------------- #
# In-memory runs of the contract.
# --------------------------------------------------------------------------- #

CONTRACTS = [
    contract_restores_last_close_and_marker,
    contract_replay_is_a_no_op_and_different_content_conflicts,
    contract_bar_record_time_is_the_bar_close,
    contract_tick_stats_ids_use_the_batch_sequence,
    contract_a_full_session_replays_to_the_same_rows,
    contract_records_are_filtered_and_ordered,
    contract_payload_survives_the_round_trip,
]


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.__name__)
def test_in_memory_state_meets_the_contract(contract: Callable[[PortFactory], None]) -> None:
    contract(InMemoryRuntimeState)


def test_tracer_records_round_trip_and_restore_the_later_close() -> None:
    state = InMemoryRuntimeState()
    state.record(marker(RuntimeEventType.RUNTIME_START, T0))
    state.record(marker(RuntimeEventType.EPOCH_PINNED, T0))
    state.record(bar(0))
    state.record(bar(1))
    assert state.last_close_by_pair(EPOCH) == {("BTCUSDT", "1h"): bar_close(1)}


# --------------------------------------------------------------------------- #
# Ids are pure functions of the epoch and the key, never of the wall clock.
# --------------------------------------------------------------------------- #


def test_bar_event_id_is_a_pure_function_of_epoch_pair_close_and_type() -> None:
    first = runtime_event_id(bar(3))
    assert runtime_event_id(bar(3)) == first
    # The payload and the recording are not part of the id.
    assert runtime_event_id(bar(3, source="REST_BACKFILL")) == first
    # Each key part changes the id.
    assert runtime_event_id(bar(4)) != first
    assert runtime_event_id(bar(3, symbol="ETHUSDT")) != first
    assert runtime_event_id(bar(3, interval="4h")) != first
    assert runtime_event_id(bar(3, epoch_id=OTHER_EPOCH)) != first
    gap = RuntimeRecord(
        event_type=RuntimeEventType.PAPER_GAP,
        epoch_id=EPOCH,
        occurred_at_utc=bar_close(3) + ONE_HOUR,
        symbol="BTCUSDT",
        interval="1h",
        payload={"expected_close_utc": bar_close(3), "reason": "UNKNOWN"},
    )
    assert runtime_event_id(gap) != first  # the event type is part of the id
    assert len(first) <= 128


def test_a_gap_is_keyed_on_its_expected_close_not_on_when_it_was_detected() -> None:
    def gap(detected: datetime) -> RuntimeRecord:
        return RuntimeRecord(
            event_type=RuntimeEventType.PAPER_GAP,
            epoch_id=EPOCH,
            occurred_at_utc=detected,
            symbol="BTCUSDT",
            interval="1h",
            payload={"expected_close_utc": bar_close(3).isoformat(), "reason": "UNKNOWN"},
        )

    assert runtime_event_id(gap(bar_close(3) + timedelta(seconds=1))) == runtime_event_id(
        gap(bar_close(3) + timedelta(hours=2))
    )


def test_a_gap_without_expected_close_is_refused() -> None:
    record = RuntimeRecord(
        event_type=RuntimeEventType.PAPER_GAP,
        epoch_id=EPOCH,
        occurred_at_utc=T0,
        symbol="BTCUSDT",
        interval="1h",
        payload={"reason": "UNKNOWN"},
    )
    with pytest.raises(ValueError, match="expected_close_utc"):
        runtime_event_id(record)


def test_marker_ids_use_the_millisecond_and_the_event_type() -> None:
    start = marker(RuntimeEventType.RUNTIME_START, T0)
    same_ms = marker(RuntimeEventType.RUNTIME_START, T0 + timedelta(microseconds=400))
    next_ms = marker(RuntimeEventType.RUNTIME_START, T0 + ONE_MS)
    stop = marker(RuntimeEventType.RUNTIME_STOP, T0)
    assert runtime_event_id(start) == runtime_event_id(same_ms)
    assert runtime_event_id(start) != runtime_event_id(next_ms)
    assert runtime_event_id(start) != runtime_event_id(stop)
    assert runtime_event_id(start) != runtime_event_id(
        marker(RuntimeEventType.RUNTIME_START, T0, epoch_id=OTHER_EPOCH)
    )


def test_ids_do_not_read_the_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """P11: no clock in the id. Freezing a different 'now' changes nothing."""
    import time

    before = [runtime_event_id(r) for r in simulated_session()]
    monkeypatch.setattr(time, "time", lambda: 1.0)
    monkeypatch.setattr(time, "time_ns", lambda: 1)
    after = [runtime_event_id(r) for r in simulated_session()]
    assert before == after
    assert len(set(before)) == len(before)


def test_tick_stats_without_a_batch_sequence_is_refused() -> None:
    record = RuntimeRecord(
        event_type=RuntimeEventType.PAPER_TICK_STATS,
        epoch_id=EPOCH,
        occurred_at_utc=T0,
        payload={"duration_ms": 3},
    )
    with pytest.raises(ValueError, match="batch_seq"):
        runtime_event_id(record)
    bad = RuntimeRecord(
        event_type=RuntimeEventType.PAPER_TICK_STATS,
        epoch_id=EPOCH,
        occurred_at_utc=T0,
        payload={"batch_seq": True},
    )
    with pytest.raises(ValueError, match="batch_seq"):
        runtime_event_id(bad)


# --------------------------------------------------------------------------- #
# Record validation.
# --------------------------------------------------------------------------- #


def test_a_naive_or_non_utc_time_is_refused() -> None:
    with pytest.raises(ValueError, match="UTC"):
        marker(RuntimeEventType.RUNTIME_START, datetime(2026, 10, 9))
    plus7 = datetime(2026, 10, 9, tzinfo=UTC).astimezone(timezone(timedelta(hours=7)))
    with pytest.raises(ValueError, match="UTC"):
        marker(RuntimeEventType.RUNTIME_START, plus7)


def test_a_bar_record_needs_symbol_and_interval() -> None:
    record = RuntimeRecord(
        event_type=RuntimeEventType.PAPER_BAR_PROCESSED, epoch_id=EPOCH, occurred_at_utc=T0
    )
    with pytest.raises(ValueError, match="symbol"):
        runtime_event_id(record)


def test_symbol_and_interval_come_together_and_hold_no_separator() -> None:
    with pytest.raises(ValueError, match="together"):
        RuntimeRecord(
            event_type=RuntimeEventType.WS_DISCONNECT,
            epoch_id=EPOCH,
            occurred_at_utc=T0,
            symbol="BTCUSDT",
        )
    with pytest.raises(ValueError, match=":"):
        RuntimeRecord(
            event_type=RuntimeEventType.WS_DISCONNECT,
            epoch_id=EPOCH,
            occurred_at_utc=T0,
            symbol="BTC:USDT",
            interval="1h",
        )
    with pytest.raises(ValueError, match="epoch_id"):
        marker(RuntimeEventType.RUNTIME_START, T0, epoch_id="x:y")
    with pytest.raises(ValueError, match="epoch_id"):
        marker(RuntimeEventType.RUNTIME_START, T0, epoch_id="")


def test_the_payload_cannot_hold_a_float_or_a_non_text_key() -> None:
    with pytest.raises(TypeError):
        marker(RuntimeEventType.RUNTIME_START, T0, ratio=0.5)
    with pytest.raises(ValueError, match="key"):
        RuntimeRecord(
            event_type=RuntimeEventType.RUNTIME_START,
            epoch_id=EPOCH,
            occurred_at_utc=T0,
            payload={1: "x"},  # type: ignore[dict-item]
        )


def test_the_payload_is_frozen_and_copied() -> None:
    source = {"state": "HEALTHY", "nested": {"a": 1}}
    record = marker(RuntimeEventType.HEALTH_STATE_CHANGED, T0, **source)
    source["state"] = "DEGRADED"
    assert record.payload["state"] == "HEALTHY"
    with pytest.raises(TypeError):
        record.payload["state"] = "DEGRADED"  # type: ignore[index]
    nested = record.payload["nested"]
    with pytest.raises(TypeError):
        nested["a"] = 2  # type: ignore[index]


def test_the_port_conforms_to_the_runtime_record_like_protocol_of_the_coverage_module() -> None:
    from src.paper.coverage import tick_timing_summary

    summary = tick_timing_summary(
        [tick_stats(T0 + timedelta(seconds=i), i, duration_ms=10 + i) for i in range(3)]
    )
    assert summary is not None


def test_runtime_state_module_imports_no_sqlalchemy_and_no_adapter() -> None:
    source = Path("src/paper/runtime_state.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    banned = ("sqlalchemy", "psycopg", "src.persistence", "src.db", "src.adapters", "binance")
    assert not [m for m in imported if m.startswith(banned)]


def test_the_module_never_hashes_the_wall_clock_into_an_id() -> None:
    """P11: content_hash_event_id with a time, and any clock read, are absent."""
    source = Path("src/paper/runtime_state.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert "content_hash_event_id" not in names
    assert not names & {"now", "utcnow", "today", "time_ns", "monotonic", "perf_counter"}
