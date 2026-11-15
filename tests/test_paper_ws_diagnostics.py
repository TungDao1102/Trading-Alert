"""Paper WS observability: frame counters, SUBSCRIBE answers, SDK stream names (quick 261109-01d).

Implements "Next steps" 2 of `16-43-ws-investigation-2026-11-08.md`: the next market-stream
silence must be told apart (nothing sent, subscription refused, or one connection dead). The
adapter counts the messages the SDK delivers per SDK connection, records the answer to every
SUBSCRIBE request, and the SDK log bridge names the stream when an SDK message names one.

Every fake comes from `tests/paper_ws_fakes.py`; no network is touched. Counters and events are
in memory and structlog only.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import FrozenInstanceError, asdict
from typing import TYPE_CHECKING, Any

import pytest
from src.adapters.paper_ws import PaperWsAdapter, install_sdk_log_bridge
from structlog.testing import capture_logs

from tests.paper_ws_fakes import FakeSdkWsClient, fresh_sdk_stream_map, make_kline_model
from tests.test_paper_supervisor_backfill import _make_rig

if TYPE_CHECKING:
    from src.adapters.paper_ws import ConnectionDiagnostics

_BTC = "btcusdt@kline_1h"
_ETH = "ethusdt@kline_4h"
_SDK_PATH = "C:/x/site-packages/binance_common/websocket.py"


@pytest.fixture(autouse=True)
def sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the SDK module-global stream map per test (research D7)."""
    return fresh_sdk_stream_map(monkeypatch)


class _Clock:
    """A hand-moved monotonic clock."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


async def _connected(
    clock: _Clock | None = None,
) -> tuple[PaperWsAdapter, FakeSdkWsClient, list[FakeSdkWsClient], list[Any], list[Any]]:
    """Adapter on a first fake client, rebuilding through a recording factory; two streams."""
    first = FakeSdkWsClient()
    clients: list[FakeSdkWsClient] = [first]

    def factory(_configuration: Any) -> Any:
        client = FakeSdkWsClient()
        clients.append(client)
        return client

    adapter = PaperWsAdapter(
        ws_client=first,  # type: ignore[arg-type]
        client_factory=factory,
        feed_clock=clock,
    )
    await adapter.connect()
    btc: list[Any] = []
    eth: list[Any] = []
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=btc.append)
    await adapter.subscribe(symbol="ethusdt", interval="4h", on_kline=eth.append)
    return adapter, first, clients, btc, eth


def _by_path(rows: tuple[ConnectionDiagnostics, ...]) -> dict[str | None, ConnectionDiagnostics]:
    return {row.url_path: row for row in rows}


# --------------------------------------------------------------------------- #
# Frame counters per SDK connection.
# --------------------------------------------------------------------------- #


async def test_frames_are_counted_per_sdk_connection_with_the_feed_clock(
    sdk_stream_map: Any,
) -> None:
    clock = _Clock(50.0)
    adapter, fake, _clients, btc, eth = await _connected(clock)
    # The SDK assigns each stream to a connection; point eth at the public one.
    public = fake.connections[1]
    sdk_stream_map.stream_connections_map[_ETH] = public

    clock.now = 100.0
    for _ in range(3):
        fake.handles[0]._emit(make_kline_model(is_closed=False))
    clock.now = 105.0
    fake.handles[1]._emit(make_kline_model(symbol="ETHUSDT", interval="4h", is_closed=True))
    clock.now = 110.0

    rows = _by_path(adapter.connection_diagnostics())
    assert rows["market"].frames_since_connect == 3
    assert rows["market"].seconds_since_last_frame == 10
    assert rows["market"].streams_assigned == (_BTC,)
    assert rows["public"].frames_since_connect == 1
    assert rows["public"].seconds_since_last_frame == 5
    assert rows["public"].streams_assigned == (_ETH,)
    assert rows["private"].frames_since_connect == 0
    assert rows["private"].seconds_since_last_frame is None
    assert rows["private"].streams_assigned == ()
    assert [row.connection_id for row in adapter.connection_diagnostics()] == ["1", "2", "3"]
    # Every forming and closed kline still reaches on_kline unchanged.
    assert [k.is_closed for k in btc] == [False, False, False]
    assert [k.is_closed for k in eth] == [True]
    assert adapter.unattributed_frames == 0


async def test_a_malformed_message_counts_as_a_frame_and_never_reaches_on_kline() -> None:
    adapter, fake, _clients, btc, _eth = await _connected(_Clock(1.0))

    fake.handles[0]._emit({"unexpected": 1})

    assert btc == []
    assert _by_path(adapter.connection_diagnostics())["market"].frames_since_connect == 1


async def test_a_frame_for_an_unmapped_stream_is_counted_as_unattributed(
    sdk_stream_map: Any,
) -> None:
    adapter, fake, _clients, _btc, _eth = await _connected(_Clock(1.0))
    sdk_stream_map.stream_connections_map.pop(_BTC)

    fake.handles[0]._emit(make_kline_model())

    assert adapter.unattributed_frames == 1
    assert all(row.frames_since_connect == 0 for row in adapter.connection_diagnostics())


async def test_counters_reset_when_rebuild_replaces_the_client() -> None:
    clock = _Clock(10.0)
    adapter, fake, clients, _btc, _eth = await _connected(clock)
    fake.handles[0]._emit(make_kline_model())
    assert _by_path(adapter.connection_diagnostics())["market"].frames_since_connect == 1

    fake.simulate_unsolicited_close()
    await adapter.rebuild()

    rows = adapter.connection_diagnostics()
    assert len(rows) == 3
    assert all(row.frames_since_connect == 0 for row in rows)
    assert all(row.seconds_since_last_frame is None for row in rows)
    assert _by_path(rows)["market"].streams_assigned == (_BTC, _ETH)
    assert adapter.unattributed_frames == 0
    # A frame on the new client is counted on the new connection.
    clock.now = 20.0
    clients[1].handles[0]._emit(make_kline_model())
    assert _by_path(adapter.connection_diagnostics())["market"].frames_since_connect == 1


async def test_the_snapshot_holds_only_plain_types() -> None:
    adapter, _fake, _clients, _btc, _eth = await _connected(_Clock(1.0))

    rows = adapter.connection_diagnostics()

    with pytest.raises(FrozenInstanceError):
        rows[0].frames_since_connect = 9  # type: ignore[misc]
    for row in rows:
        assert type(row.connection_id) is str
        assert row.url_path is None or type(row.url_path) is str
        assert type(row.frames_since_connect) is int
        assert row.seconds_since_last_frame is None or type(row.seconds_since_last_frame) in (
            int,
            float,
        )
        assert type(row.streams_assigned) is tuple
        assert all(type(name) is str for name in row.streams_assigned)
        assert type(row.subscribe_accepted) is int
        assert type(row.subscribe_refused) is int
        assert type(row.subscribe_unanswered) is int


# --------------------------------------------------------------------------- #
# SUBSCRIBE answers.
# --------------------------------------------------------------------------- #


def _answers(logs: list[Any]) -> list[Any]:
    return [entry for entry in logs if entry["event"] == "paper_ws.subscribe_answer"]


async def test_an_accepted_subscribe_is_logged_once_at_info() -> None:
    adapter, fake, _clients, _btc, _eth = await _connected()
    assert _by_path(adapter.connection_diagnostics())["market"].subscribe_unanswered == 2

    with capture_logs() as logs:
        assert fake.answer_subscribes() == 2
        await asyncio.sleep(0)

    answers = _answers(logs)
    assert [a["log_level"] for a in answers] == ["info", "info"]
    assert [a["outcome"] for a in answers] == ["accepted", "accepted"]
    assert [a["streams"] for a in answers] == [[_BTC], [_ETH]]
    assert {a["connection_id"] for a in answers} == {"1"}
    assert {a["url_path"] for a in answers} == {"market"}
    market = _by_path(adapter.connection_diagnostics())["market"]
    assert (market.subscribe_accepted, market.subscribe_refused, market.subscribe_unanswered) == (
        2,
        0,
        0,
    )
    # No kline payload and no answer body in any event.
    for entry in logs:
        assert "k" not in entry
        assert "data" not in entry
        assert "result" not in entry


async def test_a_refused_subscribe_is_logged_at_error_with_the_stream_names() -> None:
    adapter, fake, _clients, _btc, _eth = await _connected()

    with capture_logs() as logs:
        fake.answer_subscribes(error={"code": 2, "msg": "Invalid request"})
        await asyncio.sleep(0)

    answers = _answers(logs)
    assert [a["log_level"] for a in answers] == ["error", "error"]
    assert [a["outcome"] for a in answers] == ["refused", "refused"]
    assert [a["streams"] for a in answers] == [[_BTC], [_ETH]]
    assert all("Invalid request" in a["error"] for a in answers)
    assert all(len(a["error"]) <= 200 for a in answers)
    market = _by_path(adapter.connection_diagnostics())["market"]
    assert (market.subscribe_accepted, market.subscribe_refused, market.subscribe_unanswered) == (
        0,
        2,
        0,
    )


async def test_a_long_refusal_text_is_cut_to_200_characters() -> None:
    _adapter, fake, _clients, _btc, _eth = await _connected()

    with capture_logs() as logs:
        fake.answer_subscribes(error="x" * 500)
        await asyncio.sleep(0)

    assert all(len(a["error"]) == 200 for a in _answers(logs))


async def test_the_hook_is_on_the_client_instance_only() -> None:
    original = FakeSdkWsClient.send_message
    _adapter, fake, _clients, _btc, _eth = await _connected()

    assert "send_message" in vars(fake)
    assert FakeSdkWsClient.send_message is original


async def test_connect_twice_wraps_the_client_once() -> None:
    fake = FakeSdkWsClient()
    adapter = PaperWsAdapter(ws_client=fake)  # type: ignore[arg-type]
    await adapter.connect()
    await adapter.connect()
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=lambda _k: None)

    with capture_logs() as logs:
        fake.answer_subscribes()
        await asyncio.sleep(0)

    assert len(_answers(logs)) == 1


async def test_a_send_error_propagates_unchanged_through_the_wrapper() -> None:
    class _Broken(FakeSdkWsClient):
        async def send_message(self, payload: dict[str, Any], connection: Any) -> Any:
            raise OSError("socket closed")

    adapter = PaperWsAdapter(ws_client=_Broken())  # type: ignore[arg-type]
    await adapter.connect()

    with pytest.raises(OSError, match="socket closed"):
        await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=lambda _k: None)


async def test_the_wrapper_returns_the_sdk_future_and_observes_only_subscribe_requests() -> None:
    _adapter, fake, _clients, _btc, _eth = await _connected()
    connection = fake.connections[0]

    future = await fake.send_message(
        {"method": "SUBSCRIBE", "params": ["a@kline_1m"], "id": 99}, connection
    )
    assert future is fake.pending_requests[99]

    non_subscribe = await fake.send_message({"method": "PING", "id": 100}, connection)
    assert non_subscribe is fake.pending_requests[100]
    with capture_logs() as logs:
        non_subscribe.set_result({"id": 100})
        await asyncio.sleep(0)
    assert _answers(logs) == []  # only SUBSCRIBE requests are observed


async def test_after_a_rebuild_the_records_reset_and_the_new_client_is_observed() -> None:
    adapter, fake, clients, _btc, _eth = await _connected()
    assert _by_path(adapter.connection_diagnostics())["market"].subscribe_unanswered == 2

    fake.simulate_unsolicited_close()
    await adapter.rebuild()

    market = _by_path(adapter.connection_diagnostics())["market"]
    assert market.subscribe_unanswered == 2  # the new client's two requests, not four
    with capture_logs() as logs:
        clients[1].answer_subscribes()
        await asyncio.sleep(0)
    assert len(_answers(logs)) == 2
    market = _by_path(adapter.connection_diagnostics())["market"]
    assert (market.subscribe_accepted, market.subscribe_unanswered) == (2, 0)


# --------------------------------------------------------------------------- #
# The SDK log bridge names the stream when the SDK message names one.
# --------------------------------------------------------------------------- #


def _sdk_record(message: str, *, path: str = _SDK_PATH) -> logging.LogRecord:
    return logging.LogRecord(
        name="root",
        level=logging.WARNING,
        pathname=path,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def _bridge_events(message: str, *, path: str = _SDK_PATH) -> list[Any]:
    install_sdk_log_bridge()
    with capture_logs() as logs:
        logging.getLogger().handle(_sdk_record(message, path=path))
    return [entry for entry in logs if entry["event"] == "paper_ws.sdk_log"]


def test_the_bridge_adds_the_stream_name_a_single_stream_message_carries() -> None:
    events = _bridge_events("Stream btcusdt@kline_1h not connected.")

    assert len(events) == 1
    assert events[0]["message"] == "Stream btcusdt@kline_1h not connected."
    assert events[0]["streams"] == [_BTC]
    assert events[0]["sdk_level"] == "WARNING"


def test_the_bridge_adds_every_stream_name_sorted_and_unique() -> None:
    message = f"Stream ['{_ETH}', '{_BTC}', '{_ETH}'] is not subscribed."

    events = _bridge_events(message)

    assert events[0]["message"] == message
    assert events[0]["streams"] == [_BTC, _ETH]


def test_the_bridge_leaves_a_message_without_stream_names_unchanged() -> None:
    events = _bridge_events("No WebSocket connections available for unsubscription.")

    assert len(events) == 1
    assert "streams" not in events[0]
    assert events[0]["message"] == "No WebSocket connections available for unsubscription."


def test_the_bridge_never_extracts_anything_from_a_url_with_credentials() -> None:
    events = _bridge_events("failed to connect wss://user:secret@fstream.binancefuture.com/stream")

    assert len(events) == 1
    assert "streams" not in events[0]


def test_the_bridge_never_extracts_a_name_that_is_not_an_allowed_kline_interval() -> None:
    events = _bridge_events("Stream btcusdt@kline_15m and btcusdt@trade not connected.")

    assert "streams" not in events[0]


def test_the_bridge_still_ignores_a_record_from_a_foreign_path() -> None:
    assert _bridge_events("Stream btcusdt@kline_1h not connected.", path="C:/x/other/lib.py") == []


# --------------------------------------------------------------------------- #
# One `paper_ws.diagnostics` snapshot per trigger: watchdog entry and a successful rebuild.
# --------------------------------------------------------------------------- #


def _snapshots(logs: list[Any]) -> list[Any]:
    return [entry for entry in logs if entry["event"] == "paper_ws.diagnostics"]


def test_the_two_snapshot_reasons_are_module_constants() -> None:
    from src.adapters import paper_ws

    assert paper_ws.WS_DIAGNOSTICS_SILENCE == "silence_recovery_entered"
    assert paper_ws.WS_DIAGNOSTICS_REBUILT == "rebuilt"


async def test_log_diagnostics_logs_one_event_with_one_row_per_connection() -> None:
    adapter, fake, _clients, _btc, _eth = await _connected(_Clock(10.0))
    fake.handles[0]._emit(make_kline_model())

    with capture_logs() as logs:
        adapter.log_diagnostics("silence_recovery_entered")

    events = _snapshots(logs)
    assert len(events) == 1
    event = events[0]
    assert event["reason"] == "silence_recovery_entered"
    assert event["connection_count"] == 3
    assert event["subscribed_streams"] == 2
    assert type(event["subscribed_streams"]) is int
    assert event["unattributed_frames"] == 0
    expected = [
        {**asdict(row), "streams_assigned": list(row.streams_assigned)}
        for row in adapter.connection_diagnostics()
    ]
    assert event["connections"] == expected
    assert [row["url_path"] for row in event["connections"]] == ["market", "public", "private"]
    assert event["connections"][0]["frames_since_connect"] == 1
    assert event["connections"][0]["streams_assigned"] == [_BTC, _ETH]


async def test_log_diagnostics_rejects_an_unknown_reason() -> None:
    adapter, _fake, _clients, _btc, _eth = await _connected()

    with pytest.raises(ValueError, match="reason"):
        adapter.log_diagnostics("every_ten_seconds")


async def test_a_failure_while_building_the_snapshot_is_a_warning_never_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _fake, _clients, _btc, _eth = await _connected()

    def boom() -> Any:
        raise RuntimeError("snapshot broke")

    monkeypatch.setattr(adapter, "connection_diagnostics", boom)

    with capture_logs() as logs:
        adapter.log_diagnostics("silence_recovery_entered")

    assert _snapshots(logs) == []
    failed = [e for e in logs if e["event"] == "paper_ws.diagnostics_failed"]
    assert len(failed) == 1
    assert failed[0]["log_level"] == "warning"
    assert failed[0]["reason"] == "silence_recovery_entered"
    assert failed[0]["error"] == "RuntimeError"


async def test_a_successful_rebuild_logs_one_snapshot_after_the_rebuilt_line() -> None:
    adapter, fake, _clients, _btc, _eth = await _connected(_Clock(1.0))
    fake.simulate_unsolicited_close()

    with capture_logs() as logs:
        await adapter.rebuild()

    names = [entry["event"] for entry in logs]
    assert names.index("paper_ws.rebuilt") < names.index("paper_ws.diagnostics")
    events = _snapshots(logs)
    assert len(events) == 1
    assert events[0]["reason"] == "rebuilt"
    assert events[0]["connection_count"] == 3
    assert all(row["frames_since_connect"] == 0 for row in events[0]["connections"])


async def test_a_failed_rebuild_logs_no_snapshot() -> None:
    first = FakeSdkWsClient()

    def broken_factory(_configuration: Any) -> Any:
        raise ConnectionError("ws dead")

    adapter = PaperWsAdapter(ws_client=first, client_factory=broken_factory)  # type: ignore[arg-type]
    await adapter.connect()
    await adapter.subscribe(symbol="btcusdt", interval="1h", on_kline=lambda _k: None)
    first.simulate_unsolicited_close()

    with capture_logs() as logs, pytest.raises(ConnectionError):
        await adapter.rebuild()

    assert _snapshots(logs) == []


async def test_subscribing_frames_and_answers_log_no_snapshot() -> None:
    with capture_logs() as logs:
        _adapter, fake, _clients, _btc, _eth = await _connected(_Clock(1.0))
        for _ in range(10):
            fake.handles[0]._emit(make_kline_model(is_closed=False))
        fake.answer_subscribes()
        await asyncio.sleep(0)

    assert _snapshots(logs) == []


async def test_the_supervisor_forwards_a_snapshot_request_to_the_adapter() -> None:
    rig = _make_rig()
    await rig.supervisor.start()

    with capture_logs() as logs:
        rig.supervisor.log_ws_diagnostics("silence_recovery_entered")

    events = _snapshots(logs)
    assert len(events) == 1
    assert events[0]["reason"] == "silence_recovery_entered"
    assert events[0]["subscribed_streams"] == 1
    await rig.supervisor.stop()


async def test_the_supervisor_ignores_an_adapter_without_a_snapshot_method() -> None:
    class _PlainWs:
        pass

    rig = _make_rig()
    rig.supervisor._ws = _PlainWs()  # type: ignore[assignment]

    with capture_logs() as logs:
        rig.supervisor.log_ws_diagnostics("silence_recovery_entered")

    assert _snapshots(logs) == []
    assert [e for e in logs if e["event"] == "paper.supervisor.ws_diagnostics_unavailable"]


async def test_the_supervisor_never_raises_when_the_adapter_snapshot_fails() -> None:
    class _BrokenWs:
        def log_diagnostics(self, reason: str) -> None:
            raise RuntimeError("adapter broke")

    rig = _make_rig()
    rig.supervisor._ws = _BrokenWs()  # type: ignore[assignment]

    with capture_logs() as logs:
        rig.supervisor.log_ws_diagnostics("silence_recovery_entered")

    failed = [e for e in logs if e["event"] == "paper.supervisor.ws_diagnostics_failed"]
    assert len(failed) == 1
    assert failed[0]["log_level"] == "warning"
    assert failed[0]["reason"] == "silence_recovery_entered"
    assert failed[0]["error"] == "RuntimeError"
