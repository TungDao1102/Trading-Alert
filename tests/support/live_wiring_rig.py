"""The complete live composition over `build_wiring` with fakes ONLY at the edges (plan 24-27).

TEST_ONLY: the limits, the credentials, the chat ids, the SDK stand-in and the database URL are
made-up values. The SDK client factory, the PTB application factory and bot, the clock and the
sleep are the fakes; the SQL engine is created but never connected (a socket monkeypatch makes
any connection attempt fail the test), so every PostgreSQL store is the real class. No production
module imports this file (tests/test_no_unratified_defaults.py enforces it).

`make_assembly(tmp_path)` returns a `LiveAssembly`; `await complete_assembly(assembly)` loads a
durable in-memory SAFE_MODE store and a DISABLED enablement controller, the way start step 4 does,
and returns the `CompleteLiveWiring`.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
import sqlalchemy
from src.adapters.binance_client import ApiCredentials, Environment
from src.domain.registry import load_parameter_set
from src.execution.enablement import LiveEnablementController
from src.live.config import LiveConfig
from src.live.wiring import CompleteLiveWiring, LiveAssembly, build_wiring
from src.live.wiring_parts import LiveBotProxy
from src.reconcile.safe_mode import SafeModeController

from tests.shadow_fakes import AUTHORIZED_USER_IDS, CHAT_ID, T0, FakeBot
from tests.support.execution_limits import test_only_execution_limits
from tests.support.limits import test_only_binance_limits
from tests.support.reconcile_doubles import InMemorySafeModeStore
from tests.support.virtual_time import VirtualTime

TEST_ONLY_DATABASE_URL = "postgresql+psycopg://wiring_test:wiring_test@127.0.0.1:1/wiring_test"
TEST_ONLY_SYMBOLS = ("BTCUSDT",)


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class AnyRest:
    """The `rest_api` of the SDK stand-in: every method records its name and returns an object."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name == "calls":
            raise AttributeError(name)

        def call(*_args: Any, **_kwargs: Any) -> _Response:
            self.calls.append(name)
            return _Response(SimpleNamespace())

        return call


class FakeApplication:
    """A PTB application stand-in; the runner is never started by the wiring tests."""

    def __init__(self) -> None:
        self.bot = SimpleNamespace()


def forbid_connections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Any outbound connection or database connect fails the test; returns the attempts.

    The event loop itself needs a socket pair on Windows, so `socket.socket` is left alone; the
    outbound paths (`create_connection`, name resolution, the psycopg connect) are refused.
    """
    attempts: list[str] = []

    def refuse(*_args: object, **_kwargs: object) -> None:
        attempts.append("connect")
        raise AssertionError("the wiring tests must not open a connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(lambda cls, *a, **k: refuse()))
    monkeypatch.setattr(psycopg, "connect", refuse)
    return attempts


def make_config(tmp_path: Path, *, mode: Environment = Environment.DEMO) -> LiveConfig:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    return LiveConfig(
        mode=mode,
        credentials=ApiCredentials(api_key="test-key", api_secret="test-secret"),
        telegram_bot_token="123456:TEST_ONLY_TOKEN",
        authorized_chat_id=CHAT_ID,
        authorized_user_ids=AUTHORIZED_USER_IDS,
        limits=test_only_execution_limits(),
        state_dir=state,
        gate_state_path=state / "rest-gate.json",
        spill_dir=state / "spill",
        held_marker_dir=state,
        liveness_dir=state,
    )


@dataclass
class WiringHandles:
    """What a wiring test needs next to the assembly."""

    assembly: LiveAssembly
    clock: VirtualTime
    bot: FakeBot
    rest: AnyRest
    factory_calls: list[dict[str, Any]]
    safe_mode_store: InMemorySafeModeStore


def make_assembly(
    tmp_path: Path,
    *,
    mode: Environment = Environment.DEMO,
    use_proxy_bot: bool = False,
) -> WiringHandles:
    clock = VirtualTime(T0)
    rest = AnyRest()
    factory_calls: list[dict[str, Any]] = []

    def sdk_factory(**kwargs: Any) -> Any:
        factory_calls.append(kwargs)
        return SimpleNamespace(
            environment=kwargs["environment"],
            surfaces=kwargs["surfaces"],
            client=SimpleNamespace(rest_api=rest),
        )

    config = make_config(tmp_path, mode=mode)
    bot = FakeBot.for_mode(mode.value)
    engine = sqlalchemy.create_engine(TEST_ONLY_DATABASE_URL)
    assembly = build_wiring(
        config=config,
        execution_limits=config.limits,
        binance_limits=test_only_binance_limits(),
        parameter_set=load_parameter_set("trend-pullback", "baseline-v5"),
        clock=clock,
        sleep=clock.sleep,
        sdk_factory=sdk_factory,
        application_factory=FakeApplication,
        bot=LiveBotProxy(bot) if use_proxy_bot else bot,
        engine=engine,
        repo_root=Path(__file__).resolve().parents[2],
        symbols=TEST_ONLY_SYMBOLS,
        session_id="wiring-test",
    )
    return WiringHandles(
        assembly=assembly,
        clock=clock,
        bot=bot,
        rest=rest,
        factory_calls=factory_calls,
        safe_mode_store=InMemorySafeModeStore(),
    )


async def complete_assembly(handles: WiringHandles) -> CompleteLiveWiring:
    """Complete the assembly with a durable SAFE_MODE controller and a DISABLED enablement."""
    assembly = handles.assembly
    controller = SafeModeController(
        adapter=assembly.exchange.adapter,  # type: ignore[arg-type]
        journal=assembly.stores.journal,
        state_store=handles.safe_mode_store,
        on_enter=assembly.alerts.safe_mode_observer,
    )
    enablement = LiveEnablementController(journal=assembly.stores.journal)
    return assembly.complete(safe_mode=controller, enablement=enablement)


__all__ = [
    "TEST_ONLY_SYMBOLS",
    "AnyRest",
    "FakeApplication",
    "WiringHandles",
    "complete_assembly",
    "forbid_connections",
    "make_assembly",
    "make_config",
]
