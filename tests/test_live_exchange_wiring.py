"""The exchange edge of the live process (plan 24-12; D-15, D-06; 24-NOTES items 1 and 3).

* ONE `RestRateLimitGate` per process, handed to the signed adapter, the public reader, the
  listen-key port and the probe adapter: a 418 recorded through any holder refuses the next call
  of every other holder before it reaches the (fake) SDK;
* the adapter is built WITH a `ClockDriftGuard`: an unmeasured clock makes `place_entry` raise
  `EntriesBlocked` before any SDK call, and the same behavioural check detects an adapter built
  without a guard (negative control);
* the re-measure task refreshes the guard only when it asks for it and never raises;
* the gate is durable (file store) and not restored by the build; the alert hook is structured.

A fake SDK stands in for Binance; nothing opens a socket. Numbers are the TEST_ONLY objects of
`tests/support/limits.py` and `tests/support/execution_limits.py`.
"""

from __future__ import annotations

import asyncio
import re
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.errors import BadRequestError, RateLimitBanError
from src.adapters.binance_client import (
    ApiCredentials,
    Environment,
    LiveNotEnabled,
    Surface,
)
from src.adapters.binance_clock import DriftBlockReason
from src.adapters.binance_ratelimit_gate import (
    GATE_NOT_RESTORED,
    REST_GATE_BAN_ENTERED,
    REST_GATE_RECOVERY_REQUIRED,
    GateNotRestored,
    GateRecoveryStatus,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter, EntriesBlocked
from src.domain.exchange_errors import ExchangeErrorCategory
from src.live.exchange import (
    LIVE_SURFACES,
    ExchangeBundle,
    ExchangeCompositionError,
    GateAlert,
    GateStatePathInvalid,
    build_exchange,
    gate_alert_adapter,
    remeasure_drift,
)
from src.ops.rest_gate_state import FileGateStateStore

from tests.support.execution_limits import (
    test_only_execution_limits as execution_limits_for_tests,
)
from tests.support.limits import (
    TEST_ONLY_PERIODIC_REMEASURE_INTERVAL_SECONDS,
    TEST_ONLY_SDK_RECONNECT_ATTEMPTS,
    TEST_ONLY_SDK_RECONNECT_DELAY_MS,
    test_only_binance_limits,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_418,
)
from tests.support.virtual_time import VirtualTime

ROOT = Path(__file__).resolve().parents[1]
UPDATE_MS = 1_791_360_000_000
ENTRY_ID = "e" * 36
LISTEN_KEY = "listen-key-test-value"


# --------------------------------------------------------------------------- #
# A fake SDK: records every call, answers from a table, raises what is scripted.
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class FakeRest:
    """The `rest_api` of the fake SDK client; `server_ms` answers `check_server_time`."""

    def __init__(self, clock: VirtualTime) -> None:
        self._clock = clock
        self.calls: list[str] = []
        self.script: dict[str, list[BaseException]] = {}
        self.server_offset_ms = 0

    def fail(self, name: str, *excs: BaseException) -> None:
        self.script.setdefault(name, []).extend(excs)

    def _payload(self, name: str, kwargs: dict[str, Any]) -> Any:
        if name == "check_server_time":
            host_ms = int(self._clock.now().timestamp() * 1000)
            return SimpleNamespace(server_time=host_ms + self.server_offset_ms)
        if name == "query_order":
            return SimpleNamespace(order_id=1, status="NEW", update_time=UPDATE_MS)
        if name == "new_order":
            return SimpleNamespace(
                symbol=kwargs.get("symbol"),
                client_order_id=kwargs.get("new_client_order_id"),
                order_id=11,
                side="BUY",
                position_side="BOTH",
                type="LIMIT",
                time_in_force="GTC",
                status="NEW",
                orig_qty="0.010",
                price="100.0",
                update_time=UPDATE_MS,
            )
        if name in {"start_user_data_stream", "keepalive_user_data_stream"}:
            return SimpleNamespace(listen_key=LISTEN_KEY)
        return SimpleNamespace()

    def __getattr__(self, name: str) -> Callable[..., _Response]:
        if name.startswith("_") or name in {"calls", "script", "server_offset_ms"}:
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> _Response:
            self.calls.append(name)
            queue = self.script.get(name)
            if queue:
                raise queue.pop(0)
            return _Response(self._payload(name, kwargs))

        return _call

    def count(self, name: str) -> int:
        return self.calls.count(name)


class Rig:
    """A built bundle over the fake SDK, a virtual clock and a recording alert sink."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        mode: Environment = Environment.DEMO,
        restore: bool = True,
        execution_limits: Any = None,
    ) -> None:
        self.time = VirtualTime(datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC))
        self.rest = FakeRest(self.time)
        self.alerts: list[GateAlert] = []
        self.factory_calls: list[dict[str, Any]] = []
        self.state_path = tmp_path / "gate-state.json"

        def factory(**kwargs: Any) -> Any:
            self.factory_calls.append(kwargs)
            return SimpleNamespace(
                environment=kwargs["environment"],
                surfaces=kwargs["surfaces"],
                client=SimpleNamespace(rest_api=self.rest),
            )

        self.bundle: ExchangeBundle = build_exchange(
            mode=mode,
            credentials=ApiCredentials(api_key="k", api_secret="s"),
            binance_limits=test_only_binance_limits(),
            execution_limits=execution_limits or execution_limits_for_tests(),
            clock=self.time,
            sleep=self.time.sleep,
            gate_state_path=self.state_path,
            on_gate_alert=self.alerts.append,
            sdk_factory=factory,
        )
        if restore:
            self.restore_gate()

    def restore_gate(self) -> GateRecoveryStatus:
        self.bundle.gate_store.initialize(now_utc=self.time(), operator_id="test")
        return self.bundle.gate.restore()

    def clock_ms(self) -> int:
        return int(self.time.now().timestamp() * 1000)


def _place_entry(adapter: BinanceUsdmAdapter) -> Any:
    return adapter.place_entry(
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=Decimal("0.010"),
        price=Decimal("100.0"),
        new_client_order_id=ENTRY_ID,
    )


def _query_order(adapter: BinanceUsdmAdapter) -> Any:
    return adapter.query_order_by_client(symbol="BTCUSDT", orig_client_order_id=ENTRY_ID)


def _ban() -> RateLimitBanError:
    return RateLimitBanError("banned", -1003, None)


async def _measure(rig: Rig) -> Any:
    return await remeasure_drift(rig.bundle, clock_ms=rig.clock_ms, now_utc=rig.time)


def entries_blocked_before_sdk(adapter: BinanceUsdmAdapter, rest: FakeRest) -> bool:
    """The behavioural guard check: a fresh adapter refuses `place_entry` with NEVER_MEASURED.

    True only when `EntriesBlocked(NEVER_MEASURED)` is raised and the SDK saw no call. An adapter
    built without a drift guard places the entry and returns False.
    """
    before = len(rest.calls)
    try:
        asyncio.run(_place_entry(adapter))
    except EntriesBlocked as exc:
        return exc.reason is DriftBlockReason.NEVER_MEASURED and len(rest.calls) == before
    return False


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """No socket to a non-loopback host and no real sleep in this module."""
    reached: list[str] = []
    real_socket = socket.socket

    class _LoopbackOnly(real_socket):  # type: ignore[misc, valid-type]
        def connect(self, address: Any) -> None:
            if not (isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}):
                reached.append("connect")
                raise AssertionError("a network connect in a wiring test")
            super().connect(address)

    async def _forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("a real asyncio.sleep was called")

    monkeypatch.setattr(socket, "socket", _LoopbackOnly)
    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    return reached


# --------------------------------------------------------------------------- #
# Task 1 (tracer): one gate, a guarded adapter.
# --------------------------------------------------------------------------- #


def _call_adapter(rig: Rig) -> Any:
    return _query_order(rig.bundle.adapter)


def _call_public(rig: Rig) -> Any:
    return rig.bundle.public.server_time()


def _call_listen_keys(rig: Rig) -> Any:
    return rig.bundle.listen_keys.start()


def _call_probe(rig: Rig) -> Any:
    return rig.bundle.probe.mark_price("BTCUSDT")


def _meet_the_418(call: Callable[[Rig], Any], rig: Rig) -> None:
    """Run one call that meets the scripted 418: it fails, and not by a gate refusal."""
    try:
        asyncio.run(call(rig))
    except RestGateRefusal as exc:
        raise AssertionError("the origin was refused instead of meeting the 418") from exc
    except Exception:  # noqa: BLE001 - the origin's own translated error; its type is not the point
        return
    raise AssertionError("the origin call did not fail")


HOLDERS: dict[str, tuple[Callable[[Rig], Any], str, str]] = {
    "adapter": (_call_adapter, "query_order", "query_order"),
    "public": (_call_public, "check_server_time", "check_server_time"),
    "listen_keys": (_call_listen_keys, "start_user_data_stream", "start_user_data_stream"),
}


@pytest.mark.parametrize("origin", sorted(HOLDERS))
def test_a_418_through_any_holder_refuses_every_other_holder_before_the_sdk(
    tmp_path: Path, origin: str
) -> None:
    rig = Rig(tmp_path)
    call, sdk_name, _ = HOLDERS[origin]
    rig.rest.fail(sdk_name, _ban())
    _meet_the_418(call, rig)
    restriction = rig.bundle.gate.restriction()
    assert restriction is not None
    assert restriction.remaining_seconds == WAIT_418
    for other, (other_call, other_sdk_name, _) in HOLDERS.items():
        before = rig.rest.count(other_sdk_name)
        with pytest.raises(RestGateRefusal):
            asyncio.run(other_call(rig))
        assert rig.rest.count(other_sdk_name) == before, f"{other} reached the SDK during a ban"


def test_the_probe_adapter_shares_the_gate_too(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.rest.fail("query_order", _ban())
    _meet_the_418(_call_adapter, rig)
    calls = len(rig.rest.calls)
    with pytest.raises(RestGateRefusal):
        asyncio.run(rig.bundle.public.server_time())
    # The probe adapter hands its reads to the public reader of the bundle, which holds the gate.
    assert rig.bundle.probe._rest_gate is rig.bundle.gate  # noqa: SLF001
    assert len(rig.rest.calls) == calls


def test_every_holder_holds_the_one_gate_instance(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    gate = rig.bundle.gate
    assert rig.bundle.public._rest_gate is gate  # noqa: SLF001
    assert rig.bundle.adapter._rest_gate is gate  # noqa: SLF001
    assert rig.bundle.adapter._public._rest_gate is gate  # noqa: SLF001
    assert rig.bundle.listen_keys._rest_gate is gate  # noqa: SLF001
    assert rig.bundle.probe._rest_gate is gate  # noqa: SLF001


def test_there_is_one_gate_construction_site_under_src_live() -> None:
    sites = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "src" / "live").rglob("*.py"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.search(r"\bRestRateLimitGate\(", line) and not line.lstrip().startswith("#")
    ]
    assert sites == ["src/live/exchange.py"]


def test_a_fresh_bundle_refuses_place_entry_before_any_sdk_call(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert entries_blocked_before_sdk(rig.bundle.adapter, rig.rest)
    assert rig.rest.calls == []


def test_the_behavioural_guard_check_detects_an_adapter_without_a_guard(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    limits = test_only_binance_limits()
    unguarded = BinanceUsdmAdapter(
        SimpleNamespace(rest_api=rig.rest),  # type: ignore[arg-type]
        rest_gate=rig.bundle.gate,
        sleep=rig.time.sleep,
        signed_call_policy=limits.signed,
    )
    assert entries_blocked_before_sdk(unguarded, rig.rest) is False


def test_the_clock_skew_hook_is_the_guard_and_blocks_entries_again(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    asyncio.run(_measure(rig))
    assert rig.bundle.drift_guard.entries_allowed(rig.time())
    rig.rest.fail("query_order", BadRequestError("skew", -1021))
    with pytest.raises(BadRequestError):
        asyncio.run(_call_adapter(rig))
    assert rig.bundle.drift_guard.remeasure_requested is True
    before = rig.rest.count("new_order")
    with pytest.raises(EntriesBlocked) as info:
        asyncio.run(_place_entry(rig.bundle.adapter))
    assert info.value.reason is DriftBlockReason.STALE
    assert rig.rest.count("new_order") == before


def test_remeasure_inside_the_limits_allows_entries_and_two_seconds_ahead_does_not(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    guard = rig.bundle.drift_guard
    rig.rest.server_offset_ms = 2000
    verdict = asyncio.run(_measure(rig))
    assert verdict is not None and not verdict.within_limits
    assert guard.blocked_reason(rig.time()) is DriftBlockReason.OUT_OF_LIMITS
    with pytest.raises(EntriesBlocked):
        asyncio.run(_place_entry(rig.bundle.adapter))
    assert rig.rest.count("new_order") == 0

    guard.request_remeasure()
    rig.rest.server_offset_ms = 0
    verdict = asyncio.run(_measure(rig))
    assert verdict is not None and verdict.within_limits
    assert guard.entries_allowed(rig.time())
    placed = asyncio.run(_place_entry(rig.bundle.adapter))
    assert placed is not None
    assert rig.rest.count("new_order") == 1


def test_remeasure_refreshes_only_when_the_guard_asks(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert asyncio.run(_measure(rig)) is not None  # never measured: due
    assert rig.rest.count("check_server_time") == 1
    assert asyncio.run(_measure(rig)) is None  # fresh and no request: not due
    assert rig.rest.count("check_server_time") == 1
    asyncio.run(rig.time.advance(TEST_ONLY_PERIODIC_REMEASURE_INTERVAL_SECONDS - 1))
    assert asyncio.run(_measure(rig)) is None
    asyncio.run(rig.time.advance(1))
    assert asyncio.run(_measure(rig)) is not None  # the ratified cadence elapsed
    assert rig.rest.count("check_server_time") == 2
    rig.bundle.drift_guard.note_clock_skew_error()
    assert asyncio.run(_measure(rig)) is not None  # a -1021 asks at once
    assert rig.rest.count("check_server_time") == 3


def test_a_failed_measure_blocks_entries_and_does_not_raise(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.rest.fail("check_server_time", RuntimeError("down"))
    verdict = asyncio.run(_measure(rig))
    assert verdict is not None and verdict.measurement_failed
    assert rig.bundle.drift_guard.blocked_reason(rig.time()) is DriftBlockReason.MEASUREMENT_FAILED
    with pytest.raises(EntriesBlocked):
        asyncio.run(_place_entry(rig.bundle.adapter))
    assert rig.rest.count("new_order") == 0


def test_a_measure_during_a_ban_is_refused_by_the_gate_and_blocks_entries(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    rig.bundle.gate.record(ExchangeErrorCategory.IP_BANNED, None)
    verdict = asyncio.run(_measure(rig))
    assert verdict is not None and verdict.measurement_failed
    assert rig.rest.count("check_server_time") == 0
    assert not rig.bundle.drift_guard.entries_allowed(rig.time())


def test_a_wiring_error_in_the_task_is_swallowed_and_keeps_the_guard_asking(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    asyncio.run(_measure(rig))
    assert rig.bundle.drift_guard.entries_allowed(rig.time())

    def naive() -> datetime:
        return datetime(2026, 10, 31, 12, 0, 0)  # noqa: DTZ001 - the seeded wiring error

    result = asyncio.run(remeasure_drift(rig.bundle, clock_ms=rig.clock_ms, now_utc=naive))
    assert result is None


def test_building_touches_neither_the_state_file_nor_the_network(
    tmp_path: Path, _offline: list[str]
) -> None:
    rig = Rig(tmp_path, restore=False)
    assert not rig.state_path.exists()
    assert list(tmp_path.iterdir()) == []
    assert rig.rest.calls == []
    assert _offline == []


def test_demo_builds_the_demo_client_for_rest_and_the_stream(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    (call,) = rig.factory_calls
    assert call["environment"] is Environment.DEMO
    assert call["surfaces"] == LIVE_SURFACES == frozenset({Surface.REST, Surface.WS_STREAMS})
    assert call["limits"] == test_only_binance_limits().client
    assert rig.bundle.mode is Environment.DEMO


def test_the_default_factory_builds_a_real_demo_client_without_a_connection(
    tmp_path: Path, _offline: list[str]
) -> None:
    time = VirtualTime()
    bundle = build_exchange(
        mode=Environment.DEMO,
        credentials=ApiCredentials(api_key="k", api_secret="s"),
        binance_limits=test_only_binance_limits(),
        execution_limits=execution_limits_for_tests(),
        clock=time,
        sleep=time.sleep,
        gate_state_path=tmp_path / "gate-state.json",
        on_gate_alert=lambda alert: None,
    )
    assert bundle.sdk.environment is Environment.DEMO
    assert bundle.drift_guard.blocked_reason(time()) is DriftBlockReason.NEVER_MEASURED
    assert _offline == []


def test_live_without_an_enabled_controller_refuses_at_build(tmp_path: Path) -> None:
    time = VirtualTime()
    with pytest.raises(LiveNotEnabled):
        build_exchange(
            mode=Environment.LIVE,
            credentials=ApiCredentials(api_key="k", api_secret="s"),
            binance_limits=test_only_binance_limits(),
            execution_limits=execution_limits_for_tests(),
            clock=time,
            sleep=time.sleep,
            gate_state_path=tmp_path / "gate-state.json",
            on_gate_alert=lambda alert: None,
        )


def test_testnet_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ExchangeCompositionError):
        Rig(tmp_path, mode=Environment.TESTNET)


def test_a_client_built_for_another_environment_is_refused(tmp_path: Path) -> None:
    time = VirtualTime()

    def wrong(**kwargs: Any) -> Any:
        return SimpleNamespace(environment=Environment.LIVE, client=SimpleNamespace())

    with pytest.raises(ExchangeCompositionError):
        build_exchange(
            mode=Environment.DEMO,
            credentials=ApiCredentials(api_key="k", api_secret="s"),
            binance_limits=test_only_binance_limits(),
            execution_limits=execution_limits_for_tests(),
            clock=time,
            sleep=time.sleep,
            gate_state_path=tmp_path / "gate-state.json",
            on_gate_alert=lambda alert: None,
            sdk_factory=wrong,
        )


def test_the_stream_configuration_carries_the_ratified_reconnect_values(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    configuration = rig.bundle.stream_configuration
    assert configuration.stream_url == "wss://demo-fstream.binance.com"
    assert configuration.reconnect_delay == TEST_ONLY_SDK_RECONNECT_DELAY_MS
    assert configuration.reconnect_attempts == TEST_ONLY_SDK_RECONNECT_ATTEMPTS


# --------------------------------------------------------------------------- #
# D083 margin reaches the gate.
# --------------------------------------------------------------------------- #


def _ban_end_ms(rig: Rig, seconds: int) -> int:
    return rig.clock_ms() + seconds * 1000


def test_the_owner_clock_margin_pads_the_body_ban_end(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    margin = timedelta(milliseconds=4545)
    rig.bundle.gate.record(
        ExchangeErrorCategory.IP_BANNED, None, ban_until_epoch_ms=_ban_end_ms(rig, 100)
    )
    restriction = rig.bundle.gate.restriction()
    assert restriction is not None
    assert restriction.until_utc == rig.time() + timedelta(seconds=100) + margin


def test_without_the_margin_the_body_time_is_not_used(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path,
        execution_limits=execution_limits_for_tests(rest_gate_ban_end_clock_margin_ms=None),
    )
    rig.bundle.gate.record(
        ExchangeErrorCategory.IP_BANNED, None, ban_until_epoch_ms=_ban_end_ms(rig, 100)
    )
    restriction = rig.bundle.gate.restriction()
    assert restriction is not None
    assert restriction.until_utc == rig.time() + timedelta(seconds=WAIT_418)


# --------------------------------------------------------------------------- #
# Task 2: durable, alerting, never silently in memory.
# --------------------------------------------------------------------------- #


def test_the_built_gate_is_not_restored_until_restore_and_never_in_memory(tmp_path: Path) -> None:
    rig = Rig(tmp_path, restore=False)
    gate = rig.bundle.gate
    assert gate.recovery_status() is GateRecoveryStatus.NOT_RESTORED
    assert gate.recovery_status() is not GateRecoveryStatus.LEGACY_IN_MEMORY
    restriction = gate.restriction()
    assert restriction is not None and restriction.reason == GATE_NOT_RESTORED
    with pytest.raises(GateNotRestored):
        gate.check()
    with pytest.raises(GateNotRestored):
        asyncio.run(_call_public(rig))
    assert rig.rest.calls == []
    assert rig.restore_gate() is GateRecoveryStatus.RESTORED_DURABLE
    gate.check()


def test_entering_a_418_alerts_once_with_the_deadline_and_no_text(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.rest.fail("query_order", _ban())
    _meet_the_418(_call_adapter, rig)
    deadline = rig.time() + timedelta(seconds=WAIT_418)
    assert rig.alerts == [GateAlert(event=REST_GATE_BAN_ENTERED, until_utc=deadline)]
    assert not hasattr(rig.alerts[0], "message")
    # A refused call records nothing and alerts nothing.
    with pytest.raises(RestGateRefusal):
        asyncio.run(_call_public(rig))
    assert len(rig.alerts) == 1


def test_a_lost_state_file_alerts_recovery_required_and_restricts_the_gate(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, restore=False)
    status = rig.bundle.gate.restore()  # no initialize(): the state is lost
    assert status is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert rig.alerts == [GateAlert(event=REST_GATE_RECOVERY_REQUIRED, until_utc=None)]
    with pytest.raises(GateNotRestored):
        rig.bundle.gate.check()


def test_a_failing_sink_never_changes_the_restriction(tmp_path: Path) -> None:
    def broken(alert: GateAlert) -> None:
        raise RuntimeError("sink down")

    hook = gate_alert_adapter(broken)
    time = VirtualTime()
    gate = RestRateLimitGate(
        policy=test_only_binance_limits().signed.rate_limit, clock=time, on_alert=hook
    )
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    assert gate.remaining_seconds() == WAIT_418


def test_the_restriction_survives_a_restart_through_the_state_file(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.bundle.gate.record(ExchangeErrorCategory.IP_BANNED, None)
    store = FileGateStateStore(rig.state_path, clock=rig.time)
    gate = RestRateLimitGate(
        policy=test_only_binance_limits().signed.rate_limit, clock=rig.time, state_store=store
    )
    assert gate.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert gate.remaining_seconds() == WAIT_418


@pytest.mark.parametrize(
    "bad",
    [
        "relative/gate-state.json",
        Path("relative") / "gate-state.json",
        "SOMETHING_ABSOLUTE_AS_TEXT",
    ],
    ids=["text", "relative-path", "text-absolute"],
)
def test_a_gate_state_path_must_be_an_absolute_path_object(tmp_path: Path, bad: Any) -> None:
    time = VirtualTime()
    if bad == "SOMETHING_ABSOLUTE_AS_TEXT":
        bad = str(tmp_path / "gate-state.json")
    with pytest.raises(GateStatePathInvalid):
        build_exchange(
            mode=Environment.DEMO,
            credentials=ApiCredentials(api_key="k", api_secret="s"),
            binance_limits=test_only_binance_limits(),
            execution_limits=execution_limits_for_tests(),
            clock=time,
            sleep=time.sleep,
            gate_state_path=bad,
            on_gate_alert=lambda alert: None,
        )


def test_a_gate_state_path_needs_an_existing_parent_and_a_file_name(tmp_path: Path) -> None:
    time = VirtualTime()
    for bad in (tmp_path / "missing-dir" / "gate-state.json", tmp_path):
        with pytest.raises(GateStatePathInvalid):
            build_exchange(
                mode=Environment.DEMO,
                credentials=ApiCredentials(api_key="k", api_secret="s"),
                binance_limits=test_only_binance_limits(),
                execution_limits=execution_limits_for_tests(),
                clock=time,
                sleep=time.sleep,
                gate_state_path=bad,
                on_gate_alert=lambda alert: None,
            )


@pytest.mark.parametrize(
    ("text", "event", "has_until"),
    [
        ("REST_GATE_BAN_ENTERED until_utc=2026-10-31T12:00:00+00:00", REST_GATE_BAN_ENTERED, True),
        ("REST_GATE_BAN_ENTERED until_utc=2026-10-31T12:00:00", REST_GATE_BAN_ENTERED, False),
        ("REST_GATE_BAN_ENTERED until_utc=not-a-time", REST_GATE_BAN_ENTERED, False),
        ("REST_GATE_BAN_ENTERED", REST_GATE_BAN_ENTERED, False),
        ("REST_GATE_RECOVERY_REQUIRED", REST_GATE_RECOVERY_REQUIRED, False),
        (
            "REST_GATE_RECOVERY_REQUIRED until_utc=2026-10-31T12:00:00+00:00",
            "REST_GATE_RECOVERY_REQUIRED",
            False,
        ),
    ],
)
def test_the_alert_adapter_reads_only_the_event_and_a_ban_deadline(
    text: str, event: str, has_until: bool
) -> None:
    seen: list[GateAlert] = []
    gate_alert_adapter(seen.append)(text)
    assert len(seen) == 1
    assert seen[0].event == event
    assert (seen[0].until_utc is not None) is has_until


def test_the_alert_adapter_refuses_a_non_callable_sink() -> None:
    with pytest.raises(TypeError):
        gate_alert_adapter(None)  # type: ignore[arg-type]
