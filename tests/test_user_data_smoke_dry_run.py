"""The user-data smoke dry run (plan 18-16): the identical pipeline over the SDK-shaped fakes.

The real `UserDataAdapter`, `SdkListenKeyPort`, `SdkUserDataTransport`, `UserDataSupervisor` and
`BinancePublicMarketData` run over the fakes of `tests/userdata_fakes.py` and the script's fake
order port, on virtual time. Every test patches `asyncio.sleep`, `socket.socket` and
`requests.Session.request` to fail, so nothing sleeps in real time and nothing reaches a
network. The smoke limits written here are TEST_ONLY values, never an owner-approved size.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
from scripts import user_data_smoke as uds
from src.adapters import binance_client
from src.ops import redaction

from tests.userdata_fakes import TEST_ONLY_LISTEN_KEY

TEST_ONLY_SMOKE_LIMITS = """
[order]
symbol = "BTCUSDT"
quantity = "0.002"
far_price_fraction = "0.96"

[waits]
event_wait_seconds = 30
cleanup_timeout_seconds = 60
"""


class _Forbidden(AssertionError):
    """Raised by every patched network or sleep entry point."""


_LOOPBACK = {"127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def no_network_no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail on any real sleep, HTTP request, name lookup or non-loopback socket connect.

    `socket.socket` is replaced by a subclass that refuses every connect to a non-loopback
    address: the Windows event loop builds its self-pipe from a loopback socket pair, which
    must keep working; anything that would reach a network host fails.
    """
    reached: list[str] = []
    real_socket = socket.socket

    class _LoopbackOnlySocket(real_socket):  # type: ignore[misc, valid-type]
        def connect(self, address: Any) -> None:
            if not (isinstance(address, tuple) and address[0] in _LOOPBACK):
                reached.append("socket.connect")
                raise _Forbidden("socket connect to a network host in the dry run")
            super().connect(address)

        def connect_ex(self, address: Any) -> int:
            if not (isinstance(address, tuple) and address[0] in _LOOPBACK):
                reached.append("socket.connect_ex")
                raise _Forbidden("socket connect to a network host in the dry run")
            return int(super().connect_ex(address))

    async def _sleep(delay: float, result: Any = None) -> Any:
        reached.append("asyncio.sleep")
        raise _Forbidden("asyncio.sleep called: the dry run must use virtual time")

    def _getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        reached.append("socket.getaddrinfo")
        raise _Forbidden("name lookup in the dry run")

    def _create_connection(*args: Any, **kwargs: Any) -> Any:
        reached.append("socket.create_connection")
        raise _Forbidden("socket.create_connection in the dry run")

    async def _loop_create_connection(self: Any, *args: Any, **kwargs: Any) -> Any:
        reached.append("loop.create_connection")
        raise _Forbidden("loop.create_connection in the dry run")

    def _request(self: Any, *args: Any, **kwargs: Any) -> Any:
        reached.append("requests")
        raise _Forbidden("requests.Session.request called: the dry run must not send HTTP")

    def _client_factory(**kwargs: Any) -> Any:
        reached.append("build_sdk_client")
        raise _Forbidden("the dry run must not build an SDK client")

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    monkeypatch.setattr(socket, "socket", _LoopbackOnlySocket)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", _create_connection)
    monkeypatch.setattr(
        asyncio.base_events.BaseEventLoop, "create_connection", _loop_create_connection
    )
    monkeypatch.setattr(requests.Session, "request", _request)
    monkeypatch.setattr(binance_client, "build_sdk_client", _client_factory)
    return reached


@pytest.fixture(autouse=True)
def _isolated_runtime_secrets() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


@pytest.fixture
def smoke_limits(tmp_path: Path) -> Path:
    path = tmp_path / "smoke-limits.toml"
    path.write_text(TEST_ONLY_SMOKE_LIMITS, encoding="utf-8")
    return path


def _argv(smoke_limits: Path, evidence: Path, *extra: str) -> list[str]:
    return [
        "--environment",
        "DEMO",
        "--smoke-limits-file",
        str(smoke_limits),
        "--evidence-dir",
        str(evidence),
        *extra,
    ]


def _only_evidence(directory: Path) -> tuple[Path, dict[str, Any]]:
    files = sorted(directory.glob("user-data-smoke-*.json"))
    assert len(files) == 1, files
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


def _config(smoke_limits: Path, evidence: Path, *extra: str) -> uds.SmokeConfig:
    return uds.parse_config(_argv(smoke_limits, evidence, *extra))


def _steps(document: dict[str, Any]) -> dict[str, str]:
    return {step["name"]: step["status"] for step in document["steps"]}


def _run_with(
    smoke_limits: Path, evidence: Path, scenario: uds.DryRunScenario | None = None
) -> tuple[int, uds.SmokeRig, dict[str, Any]]:
    """main() with a captured dry rig so the test can read the fakes afterwards."""
    built: list[uds.SmokeRig] = []

    def factory(config: uds.SmokeConfig) -> uds.SmokeRig:
        rig = uds.build_dry_run_rig(config, scenario)
        built.append(rig)
        return rig

    code = uds.main(_argv(smoke_limits, evidence), environ={}, rig_factory=factory)
    _, document = _only_evidence(evidence)
    return code, built[0], document


# --------------------------------------------------------------------------- #
# Tracer: start, one far order placed and cancelled, typed NEW and CANCELED, FAKE evidence.
# --------------------------------------------------------------------------- #


def test_tracer_dry_run_writes_a_scrubbed_fake_evidence_file_with_both_typed_events(
    tmp_path: Path, smoke_limits: Path, no_network_no_sleep: list[str]
) -> None:
    evidence = tmp_path / "evidence"
    code = uds.main(_argv(smoke_limits, evidence), environ={})

    path, document = _only_evidence(evidence)
    assert code == uds.EXIT_OK
    assert no_network_no_sleep == []
    assert path.name.startswith("user-data-smoke-DRYRUN-")
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert document["schema"] == uds.EVIDENCE_SCHEMA == "user-data-smoke-evidence/schema-1"
    assert document["mode"] == "dry-run"
    assert document["proof_class"] == "FAKE"
    assert document["sdk_route_delivery"] == "PASS"
    ours = [event for event in document["events"] if event.get("is_smoke_order")]
    assert [event["execution_type"] for event in ours] == ["NEW", "CANCELED"]
    assert all(event["event_type"] == "ORDER_TRADE_UPDATE" for event in ours)
    assert document["order"]["client_order_id"] == ours[0]["client_order_id"]
    assert TEST_ONLY_LISTEN_KEY not in raw.decode("ascii")
    assert uds.SINGLETON_NOTE in document["notes"]


def test_the_dry_run_state_sequence_reaches_live_and_ends_stopped(
    tmp_path: Path, smoke_limits: Path
) -> None:
    code, rig, document = _run_with(smoke_limits, tmp_path)
    states = [entry["state"] for entry in document["state_sequence"]]
    assert code == uds.EXIT_OK
    assert states[:3] == ["CONNECTING", "SYNCING", "LIVE"]
    assert states[-1] == "STOPPED"
    assert set(_steps(document).values()) == {"PASSED"}


def test_the_far_order_is_one_buy_limit_on_the_tick_grid_inside_the_band(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, rig, document = _run_with(smoke_limits, tmp_path)
    order = document["order"]
    mark = uds.Decimal(uds.DRY_RUN_FAKE_MARK)
    tick = uds.Decimal(uds.DRY_RUN_FAKE_FILTERS["tick_size"])
    price = uds.Decimal(order["price"])
    assert price == uds.far_order_price(mark, uds.Decimal("0.96"), tick)
    assert price % tick == 0
    assert (order["side"], order["type"], order["time_in_force"]) == ("BUY", "LIMIT", "GTC")
    calls = rig.fakes.orders.calls
    assert calls.count("place_entry") == 1
    assert calls.count("cancel_normal_order") == 1


def test_the_environment_guard_runs_before_the_stages_and_the_calls(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, rig, _ = _run_with(smoke_limits, tmp_path)
    # every port call, every transport connect and every stage passes the guard
    order_calls = len(rig.fakes.orders.calls)
    assert len(rig.fakes.guard_calls) > order_calls


def test_dry_run_restores_the_process_wide_patches(tmp_path: Path, smoke_limits: Path) -> None:
    from binance_common import websocket as sdk_websocket

    stream_map = sdk_websocket.global_stream_connections
    to_thread = asyncio.to_thread
    _run_with(smoke_limits, tmp_path)
    assert sdk_websocket.global_stream_connections is stream_map
    assert asyncio.to_thread is to_thread


def test_the_ratified_limits_file_is_the_default_and_recorded_by_hash(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, _, document = _run_with(smoke_limits, tmp_path)
    assert document["settings"]["limits_file"] == "binance-limits-v1.toml"
    assert document["settings"]["limits_file_sha256"] == uds.sha256_lf(uds.DEFAULT_LIMITS_FILE)
    assert document["settings"]["smoke_limits_file_sha256"] == uds.sha256_lf(smoke_limits)
