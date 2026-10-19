"""One shared "no network, no real sleep" guard for the user-data smoke tests (review WR-08).

`forbid_network_and_sleep(monkeypatch)` patches every entry point through which a dry run could
reach Binance or sleep in real time, and returns the list of entry points that were reached
(empty when the run stayed offline). Each patched entry point also raises `Forbidden`, so a
regression fails the test at once instead of waiting or connecting.

`socket.socket` is replaced by a subclass that refuses every connect to a non-loopback address:
the Windows event loop builds its self-pipe from a loopback socket pair, which must keep
working. Nothing here opens a connection or reads the environment.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import pytest
import requests
from src.adapters import binance_client

LOOPBACK = frozenset({"127.0.0.1", "::1"})


class Forbidden(AssertionError):
    """Raised by every patched network, client or sleep entry point."""


def forbid_network_and_sleep(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch the network, sleep and SDK-client entry points to fail; return what was reached."""
    reached: list[str] = []
    real_socket = socket.socket

    class _LoopbackOnlySocket(real_socket):  # type: ignore[misc, valid-type]
        def connect(self, address: Any) -> None:
            if not (isinstance(address, tuple) and address[0] in LOOPBACK):
                reached.append("socket.connect")
                raise Forbidden("socket connect to a network host in the dry run")
            super().connect(address)

        def connect_ex(self, address: Any) -> int:
            if not (isinstance(address, tuple) and address[0] in LOOPBACK):
                reached.append("socket.connect_ex")
                raise Forbidden("socket connect to a network host in the dry run")
            return int(super().connect_ex(address))

    async def _sleep(delay: float, result: Any = None) -> Any:
        reached.append("asyncio.sleep")
        raise Forbidden("asyncio.sleep called: the dry run must use virtual time")

    def _getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        reached.append("socket.getaddrinfo")
        raise Forbidden("name lookup in the dry run")

    def _create_connection(*args: Any, **kwargs: Any) -> Any:
        reached.append("socket.create_connection")
        raise Forbidden("socket.create_connection in the dry run")

    async def _loop_create_connection(self: Any, *args: Any, **kwargs: Any) -> Any:
        reached.append("loop.create_connection")
        raise Forbidden("loop.create_connection in the dry run")

    def _request(self: Any, *args: Any, **kwargs: Any) -> Any:
        reached.append("requests")
        raise Forbidden("requests.Session.request called: the dry run must not send HTTP")

    def _client_factory(**kwargs: Any) -> Any:
        reached.append("build_sdk_client")
        raise Forbidden("the dry run must not build an SDK client")

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
