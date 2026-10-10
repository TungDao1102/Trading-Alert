"""Plan 16-26 Task 1 (tracer): an admitted runtime carries a closed kline from the SDK-shaped fake
handle to a heartbeat record and stops cleanly (D-01, D-02, D-05, D-06, research P10, P20, A10).

The chain under test: SDK message -> PaperWsAdapter -> PaperSupervisor sink -> bounded queue ->
one consumer task -> `BarPipeline.handle` in `asyncio.to_thread` -> RuntimeStatePort. No network is
touched: the SDK client, the public adapter and the risk-inputs port are fakes, and the state is
the in-memory reference port. Exercising the real feed is plans 16-40, 16-43 and 16-44.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from collections.abc import Awaitable, Callable, Collection, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_public import SymbolFilters
from src.paper import runtime
from src.paper.freeze import StreamEpoch
from src.paper.pipeline import HeldBar, PipelineResult
from src.paper.runtime_config import ExitCode
from src.paper.runtime_state import InMemoryRuntimeState, RuntimeRecord
from src.paper.vocabulary import RuntimeEventType, SourceTag, TaggedBar

from tests.paper_ws_fakes import FakeSdkWsClient, fresh_sdk_stream_map, make_kline_model
from tests.test_paper_runtime_admission import _Rig
from tests.test_rationale import write_rationalized_set

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_SOURCE = REPO_ROOT / "src" / "paper" / "runtime.py"

UTC_ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)
ONE_MS = timedelta(milliseconds=1)
HOUR = timedelta(hours=1)

# The fixed UTC time every loop test runs at (the injected clock).
NOW = datetime(2026, 10, 10, 14, 0, 0, tzinfo=UTC)


def ms(moment: datetime) -> int:
    return (moment - UTC_ORIGIN) // ONE_MS


class FixedClock:
    """The single injected UTC clock: always the same instant unless a test moves it."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def filters(symbol: str) -> SymbolFilters:
    return SymbolFilters(
        symbol=symbol,
        contract_type="PERPETUAL",
        status="TRADING",
        onboard_time_utc=None,
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        max_quantity=None,
        min_notional=Decimal("5"),
        base_asset=symbol[:-4],
        quote_asset="USDT",
        margin_asset="USDT",
        notional_constraints_json="{}",
        order_capabilities_json="[]",
        position_mode_snapshot_json="{}",
    )


class FakePublic:
    """Credential-free public adapter fake: klines, exchangeInfo and server time."""

    def __init__(self, server_time: datetime = NOW) -> None:
        self.server = server_time
        self.klines_calls: list[tuple[str, str]] = []
        self.exchange_info_calls = 0

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        self.klines_calls.append((symbol, interval))
        return []

    async def server_time(self) -> datetime:
        return self.server

    async def exchange_info(self) -> list[SymbolFilters]:
        self.exchange_info_calls += 1
        return [filters("BTCUSDT"), filters("ETHUSDT")]


class FakeRiskInputs:
    """Test-only stand-in for the required risk-inputs port (src has no default, plan 16-31)."""

    def open_positions(self, at_utc: datetime) -> Sequence[Any]:
        return ()

    def daily_loss_quote(self, at_utc: datetime) -> Decimal | None:
        return Decimal("0")


class BlockingState:
    """A state port whose PAPER_BAR_PROCESSED write blocks until the test releases it."""

    def __init__(self, inner: InMemoryRuntimeState) -> None:
        self.inner = inner
        self.release = threading.Event()
        self.entered = threading.Event()

    def record(self, record: RuntimeRecord) -> None:
        if record.event_type is RuntimeEventType.PAPER_BAR_PROCESSED and not self.release.is_set():
            self.entered.set()
            self.release.wait(10)
        self.inner.record(record)

    def last_close_by_pair(self, epoch_id: str) -> Mapping[tuple[str, str], datetime]:
        return self.inner.last_close_by_pair(epoch_id)

    def latest_runtime_marker(self, epoch_id: str) -> RuntimeRecord | None:
        return self.inner.latest_runtime_marker(epoch_id)

    def records(
        self, epoch_id: str, event_types: Collection[RuntimeEventType] | None = None
    ) -> Sequence[RuntimeRecord]:
        return self.inner.records(epoch_id, event_types)


class FakeMonotonic:
    """The injected monotonic function: pops one prepared reading per call."""

    def __init__(self, readings: Sequence[int]) -> None:
        self._readings = list(readings)

    def __call__(self) -> int:
        return self._readings.pop(0)


def never_called_factory(_candle: object) -> Any:
    raise AssertionError("the context factory must not be reached without a full history")


class Live:
    """One admitted, pinned runtime and the fakes around it."""

    def __init__(self, rig: _Rig) -> None:
        self.rig = rig
        self.state = rig.state
        self.client = FakeSdkWsClient()
        self.clients: list[FakeSdkWsClient] = [self.client]
        self.public = FakePublic()
        self.script: Callable[[Live], Awaitable[None]] | None = None
        self.exit_code: int | None = None

    # ---- fakes handed to the runtime ------------------------------------------------------ #

    def client_factory(self, _configuration: object) -> FakeSdkWsClient:
        fresh = FakeSdkWsClient()
        self.clients.append(fresh)
        return fresh

    async def stop_waiter(self) -> None:
        assert self.script is not None
        await self.script(self)

    def wiring(self, **overrides: Any) -> Any:
        settings: dict[str, Any] = {
            "ws_client": self.client,
            "ws_client_factory": self.client_factory,
            "public": self.public,
            "risk_inputs": FakeRiskInputs(),
            "context_factory": never_called_factory,
            "stop_waiter": self.stop_waiter,
        }
        settings.update(overrides)
        return runtime.LoopWiring(**settings)

    # ---- driving -------------------------------------------------------------------------- #

    def start(
        self,
        script: Callable[[Live], Awaitable[None]],
        *,
        clock: Callable[[], datetime] | None = None,
        state: Any = None,
        **wiring_overrides: Any,
    ) -> int:
        self.script = script
        self.exit_code = runtime.main(
            ["--pinned-state", str(self.rig.pinned_path)],
            environ=self.rig.environ(),
            wait_for_stop=lambda: None,
            state=state if state is not None else self.state,
            registry_root=self.rig.root,
            clock=clock if clock is not None else FixedClock(),
            wiring=self.wiring(**wiring_overrides),
        )
        return self.exit_code

    @property
    def epoch(self) -> StreamEpoch:
        return self.rig.pinned()

    def records(self, *types: RuntimeEventType) -> list[RuntimeRecord]:
        return list(self.state.records(self.epoch.epoch_id, types or None))

    def handle(self, symbol: str, interval: str) -> Any:
        stream = f"{symbol.lower()}@kline_{interval}"
        for candidate in self.client.handles:
            if candidate._stream == stream:
                return candidate
        raise AssertionError(f"no subscription for {stream}")

    def emit(
        self,
        symbol: str,
        interval: str,
        *,
        open_time: datetime,
        step: timedelta = HOUR,
        closed: bool = True,
    ) -> None:
        """Deliver one SDK kline message through the fake stream handle."""
        close = open_time + step - ONE_MS
        self.handle(symbol, interval)._emit(
            make_kline_model(
                symbol=symbol,
                interval=interval,
                open_time_ms=ms(open_time),
                close_time_ms=ms(close),
                is_closed=closed,
            )
        )


async def wait_until(predicate: Callable[[], bool], *, timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


@pytest.fixture(autouse=True)
def _isolated_sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_sdk_stream_map(monkeypatch)


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    """A pinned, admitted runtime state: the epoch exists and only the live loop is missing."""
    import src.domain.registry as domain_registry

    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    yield Live(rig)


# The bar that closed one hour before NOW, and the one that closes after NOW (a clock running
# behind the exchange).
PAST_OPEN = NOW - timedelta(hours=2)
FUTURE_OPEN = NOW


# ---------------------------------------------------------------------------------------------- #
# Test 1: callback -> queue -> consumer -> pipeline -> heartbeat, then a clean stop.
# ---------------------------------------------------------------------------------------------- #


def test_a_closed_kline_reaches_a_heartbeat_record_and_the_stop_is_clean(live: Live) -> None:
    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 1)

    code = live.start(script)

    assert code == 0
    heartbeats = live.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert len(heartbeats) == 1
    assert heartbeats[0].symbol == "BTCUSDT"
    assert heartbeats[0].interval == "1h"
    assert heartbeats[0].occurred_at_utc == PAST_OPEN + HOUR - ONE_MS
    assert heartbeats[0].payload["source"] == SourceTag.LIVE_WS.value
    types = [r.event_type for r in live.records()]
    assert types[0] is RuntimeEventType.EPOCH_PINNED
    assert types.count(RuntimeEventType.RUNTIME_START) == 2
    assert types.count(RuntimeEventType.RUNTIME_STOP) == 2
    assert live.client.close_calls >= 1, "the stop closes the SDK connection"
    assert all(h._unsubscribed == 1 for h in live.client.handles), "every stream is unsubscribed"


def test_forming_updates_never_reach_the_queue_or_the_journal(live: Live) -> None:
    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN, closed=False)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN - HOUR)
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 1)

    assert live.start(script) == 0
    (only,) = live.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert only.occurred_at_utc == PAST_OPEN - ONE_MS


# ---------------------------------------------------------------------------------------------- #
# Test 2: the callback only enqueues (research P10).
# ---------------------------------------------------------------------------------------------- #


def test_a_blocking_store_never_delays_the_receive_loop_and_the_queue_drains(live: Live) -> None:
    blocking = BlockingState(live.state)
    elapsed: dict[str, float] = {}

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(blocking.entered.is_set)  # the consumer is now stuck inside the store
        loop = asyncio.get_running_loop()
        started = loop.time()
        h.emit("ETHUSDT", "1h", open_time=PAST_OPEN)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN + HOUR)
        elapsed["emit"] = loop.time() - started
        assert not blocking.release.is_set()
        blocking.release.set()
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 3)

    assert live.start(script, state=blocking) == 0
    assert elapsed["emit"] < 1.0, "delivering messages must not wait for the store"


# ---------------------------------------------------------------------------------------------- #
# Test 3: supervisor sinks become records; held bars are re-submitted at their deadline.
# ---------------------------------------------------------------------------------------------- #


def test_supervisor_gap_and_connection_sinks_become_journal_records(live: Live) -> None:
    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 1)
        h.client.simulate_unsolicited_close()
        await wait_until(
            lambda: (
                bool(
                    h.records(
                        RuntimeEventType.WS_DISCONNECT,
                        RuntimeEventType.WS_RECONNECT,
                        RuntimeEventType.PAPER_GAP,
                    )
                )
                and {r.event_type for r in h.records()}
                >= {
                    RuntimeEventType.WS_DISCONNECT,
                    RuntimeEventType.WS_RECONNECT,
                    RuntimeEventType.PAPER_GAP,
                }
            )
        )

    assert live.start(script) == 0
    assert len(live.clients) == 2, "the unsolicited close rebuilt the SDK client once"
    gaps = live.records(RuntimeEventType.PAPER_GAP)
    assert gaps
    assert all(g.symbol == "BTCUSDT" and g.interval == "1h" for g in gaps)
    assert all(g.payload["reason"] for g in gaps)


class HoldingPipeline:
    """A pipeline double: the first call returns the bar as held, later calls record the time."""

    def __init__(self, deadline: datetime) -> None:
        self.deadline = deadline
        self.calls: list[tuple[list[TaggedBar], datetime]] = []

    def handle(self, bars: Any, *, now_utc: datetime) -> PipelineResult:
        batch = list(bars)
        self.calls.append((batch, now_utc))
        if len(self.calls) == 1:
            return PipelineResult(
                held=tuple(HeldBar(bar=b, deadline_utc=self.deadline) for b in batch)
            )
        return PipelineResult()


def test_held_bars_are_resubmitted_when_the_clock_reaches_their_deadline(live: Live) -> None:
    clock = FixedClock()
    deadline = NOW + timedelta(seconds=15)
    pipeline = HoldingPipeline(deadline)
    slept: list[timedelta] = []

    async def sleep(delta: timedelta) -> None:
        if delta >= timedelta(seconds=17):  # the exchangeInfo refresh period: never fires here
            await asyncio.Event().wait()
        slept.append(delta)
        clock.advance(delta)  # the held bar waits exactly until its deadline
        await asyncio.sleep(0)

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: len(pipeline.calls) == 2)

    assert live.start(script, clock=clock, pipeline=pipeline, sleep=sleep) == 0
    assert slept == [timedelta(seconds=15)]
    first_bars, _ = pipeline.calls[0]
    second_bars, second_time = pipeline.calls[1]
    assert [b.close_time_utc for b in second_bars] == [b.close_time_utc for b in first_bars]
    assert second_time >= deadline


# ---------------------------------------------------------------------------------------------- #
# Test 4: a full queue fails closed.
# ---------------------------------------------------------------------------------------------- #


def test_a_full_queue_stops_the_process_with_the_fail_closed_exit_code(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    blocking = BlockingState(live.state)

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(blocking.entered.is_set)
        h.emit("ETHUSDT", "1h", open_time=PAST_OPEN)  # fills the queue of one
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN + HOUR)  # no room: must fail closed
        blocking.release.set()
        await asyncio.Event().wait()  # the failure, not this script, ends the run

    code = live.start(script, state=blocking, queue_maxsize=1)

    assert code == ExitCode.FAIL_CLOSED_RUNTIME == 7
    err = capsys.readouterr().err
    assert "queue is full" in err
    last = live.state.latest_runtime_marker(live.epoch.epoch_id)
    assert last is not None
    assert last.event_type is RuntimeEventType.RUNTIME_START, "a failed run leaves START open"
    assert live.client.close_calls >= 1, "the failure still unsubscribes and closes"


# ---------------------------------------------------------------------------------------------- #
# Test 5: one PAPER_TICK_STATS per batch (research P20 and A10).
# ---------------------------------------------------------------------------------------------- #


def test_every_batch_writes_one_tick_stats_record_with_measured_duration(live: Live) -> None:
    monotonic = FakeMonotonic([100, 130, 200, 207])

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_TICK_STATS)) == 1)
        h.emit("BTCUSDT", "1h", open_time=FUTURE_OPEN)  # closes after the injected clock
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_TICK_STATS)) == 2)

    assert live.start(script, monotonic_ms=monotonic) == 0

    first, second = live.records(RuntimeEventType.PAPER_TICK_STATS)
    assert first.occurred_at_utc == NOW == second.occurred_at_utc
    assert dict(first.payload) == {
        "batch_seq": 0,
        "bars_in": 1,
        "evaluated": 0,
        "held": 0,
        "duplicates": 0,
        "dropped_total": 0,
        "dropped_by_reason": {},
        "duration_ms": 30,
        "queue_depth_before": 1,
    }
    assert second.payload["batch_seq"] == 1
    assert second.payload["dropped_total"] == 1
    assert dict(second.payload["dropped_by_reason"]) == {"FUTURE_CLOSE": 1}
    assert second.payload["duration_ms"] == 7
    # The late bar was dropped, not recorded as processed.
    assert len(live.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 1


# ---------------------------------------------------------------------------------------------- #
# AST checks over src/paper/runtime.py.
# ---------------------------------------------------------------------------------------------- #


def _runtime_tree() -> ast.Module:
    return ast.parse(RUNTIME_SOURCE.read_text(encoding="utf-8"))


def test_no_sdk_callback_touches_the_state_port_directly() -> None:
    sinks = {
        node.name: node
        for node in ast.walk(_runtime_tree())
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_sink_")
    }
    assert {"_sink_closed_bar", "_sink_backfill", "_sink_gap", "_sink_connection_event"} <= set(
        sinks
    )
    for name, node in sinks.items():
        touched = {
            n.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Attribute) and n.attr in {"record", "_state", "to_thread"}
        }
        assert touched == set(), f"{name} reaches the store: {touched}"


def test_callbacks_enqueue_with_put_nowait_only() -> None:
    source = RUNTIME_SOURCE.read_text(encoding="utf-8")
    assert "put_nowait" in source
    assert "await self._queue.put(" not in source and "queue.put(" not in source


def test_the_monotonic_reading_feeds_only_the_tick_stats_record() -> None:
    tree = _runtime_tree()
    consumer = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_process_batch"
    )
    readings: set[str] = set()
    for node in ast.walk(consumer):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "_monotonic_ms"
        ):
            readings |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert len(readings) == 2, "exactly two readings around the call"
    for node in ast.walk(consumer):
        if not isinstance(node, ast.Call):
            continue
        used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id in readings}
        if not used:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        assert name == "_tick_stats_record", f"a monotonic reading reaches {name}()"


# ---------------------------------------------------------------------------------------------- #
# Task 3: the healthcheck probe (research Pitfall P5: liveness is not health) and the Q-D key.
# ---------------------------------------------------------------------------------------------- #

MAX_BAR_AGE = timedelta(seconds=20)  # healthcheck_max_bar_age_seconds of the admission rig
Q_D_DECISION = (
    REPO_ROOT / ".planning" / "phases" / "16-paper-runtime-composition" / "decisions"
) / "16-DEC-Q-D.md"
README = REPO_ROOT / "config" / "paper" / "README.md"
# The key plan 16-24 / Q-D would have added had the user chosen "fresh-within-bound".
Q_D_KEY = "backfill_eval_max_age_seconds"


class Probe:
    """Drives `main(["--healthcheck"])` against the state of a pinned `Live` runtime."""

    def __init__(self, live: Live) -> None:
        self.live = live

    def _marker(self, event_type: RuntimeEventType, at: datetime) -> None:
        self.live.state.record(
            RuntimeRecord(
                event_type=event_type, epoch_id=self.live.epoch.epoch_id, occurred_at_utc=at
            )
        )

    def start(self, at: datetime) -> None:
        self._marker(RuntimeEventType.RUNTIME_START, at)

    def stop(self, at: datetime) -> None:
        self._marker(RuntimeEventType.RUNTIME_STOP, at)

    def bar(self, close: datetime) -> None:
        self.live.state.record(
            RuntimeRecord.bar_processed(
                epoch_id=self.live.epoch.epoch_id,
                symbol="BTCUSDT",
                interval="1h",
                close_time_utc=close,
                payload={"source": SourceTag.LIVE_WS.value},
            )
        )

    def run(self, now: datetime, *, environ: dict[str, str] | None = None) -> int:
        return runtime.main(
            ["--healthcheck", "--pinned-state", str(self.live.rig.pinned_path)],
            environ=self.live.rig.environ() if environ is None else environ,
            state=self.live.state,
            registry_root=self.live.rig.root,
            clock=FixedClock(now),
        )


@pytest.fixture
def probe(live: Live) -> Probe:
    return Probe(live)


def test_healthy_while_the_last_processed_bar_is_younger_than_the_maximum_age(
    probe: Probe, capsys: pytest.CaptureFixture[str]
) -> None:
    probe.start(NOW)
    probe.bar(NOW + timedelta(seconds=1))

    assert probe.run(NOW + timedelta(seconds=1) + MAX_BAR_AGE) == 0
    assert capsys.readouterr().out.startswith("healthy")
    assert probe.run(NOW + timedelta(seconds=1) + MAX_BAR_AGE + timedelta(seconds=1)) == 1
    assert "unhealthy" in capsys.readouterr().out


def test_a_running_process_that_processes_no_bar_turns_unhealthy_after_the_maximum_age(
    probe: Probe,
) -> None:
    probe.start(NOW)

    assert probe.run(NOW + MAX_BAR_AGE) == 0, "a fresh start gets one maximum age for its first bar"
    assert probe.run(NOW + MAX_BAR_AGE + timedelta(seconds=1)) == 1


def test_a_bar_from_before_the_latest_start_does_not_count_as_progress(probe: Probe) -> None:
    probe.bar(NOW - timedelta(seconds=5))
    probe.start(NOW)

    assert probe.run(NOW + MAX_BAR_AGE) == 0
    assert probe.run(NOW + MAX_BAR_AGE + timedelta(seconds=1)) == 1


def test_a_stopped_process_is_unhealthy(probe: Probe) -> None:
    probe.start(NOW)
    probe.bar(NOW + timedelta(seconds=1))
    probe.stop(NOW + timedelta(seconds=2))

    assert probe.run(NOW + timedelta(seconds=3)) == 1


def test_the_healthcheck_never_prints_an_environment_value(
    probe: Probe, capsys: pytest.CaptureFixture[str]
) -> None:
    probe.start(NOW)
    probe.bar(NOW + timedelta(seconds=1))
    environ = {
        **probe.live.rig.environ(),
        "TELEGRAM_BOT_TOKEN": "tg-secret-token-value",
        "DATABASE_URL": "postgresql://user:db-secret-password@host/db",
        "UNRELATED_NAME": "unrelated-value",
    }
    assert probe.run(NOW + timedelta(seconds=2), environ=environ) == 0
    with_key = {**environ, "BINANCE_API_KEY": "binance-secret-key-value"}
    assert probe.run(NOW + timedelta(seconds=2), environ=with_key) == 1

    out = capsys.readouterr()
    text = out.out + out.err
    assert "BINANCE_API_KEY" in text, "the offending NAME may be reported"
    for value in (
        "tg-secret-token-value",
        "db-secret-password",
        "unrelated-value",
        "binance-secret-key-value",
    ):
        assert value not in text


def test_a_held_refusal_is_never_reported_healthy(probe: Probe, tmp_path: Path) -> None:
    probe.start(NOW)
    probe.bar(NOW + timedelta(seconds=1))
    at = NOW + timedelta(seconds=2)
    healthy_env = probe.live.rig.environ()
    assert probe.run(at, environ=healthy_env) == 0, "control: this environment is healthy"

    unratified = tmp_path / "unratified.toml"
    unratified.write_text("[health]\nmax_ws_message_silence_seconds = 11\n", encoding="utf-8")
    wrong_set = {**healthy_env, "PAPER_PARAMETER_SET_ID": "some-other-set"}
    no_config = {k: v for k, v in healthy_env.items() if k != "PAPER_RUNTIME_CONFIG"}

    assert probe.run(at, environ={**healthy_env, "BINANCE_API_KEY": ""}) == 1
    assert probe.run(at, environ={**healthy_env, "PAPER_RUNTIME_CONFIG": str(unratified)}) == 1
    assert probe.run(at, environ=no_config) == 1
    assert probe.run(at, environ=wrong_set) == 1


def test_an_empty_allowlist_is_not_healthy_either(
    probe: Probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.paper.freeze as freeze

    probe.start(NOW)
    probe.bar(NOW + timedelta(seconds=1))
    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", ())

    assert probe.run(NOW + timedelta(seconds=2)) == 1


# ---- Q-D: the configuration part of the recorded decision --------------------------------- #


def _valid_config_dict() -> dict[str, dict[str, Any]]:
    import tomllib

    from tests.test_paper_runtime_admission import CONFIG_TEXT

    return tomllib.loads(CONFIG_TEXT)


def test_q_d_option_history_only_means_no_age_key_anywhere() -> None:
    from src.paper.runtime_config import ConfigNotRatified, parse_runtime_config

    text = Q_D_DECISION.read_text(encoding="utf-8")
    option = next(
        line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("option:")
    )
    if option != "history-only":
        pytest.fail(
            "Q-D now records a different option: load_runtime_config must require the age key "
            "under [timing] and config/paper/README.md must list it with the owner Q-D"
        )
    assert Q_D_KEY not in README.read_text(encoding="utf-8")
    raw = _valid_config_dict()
    raw["timing"][Q_D_KEY] = 30
    with pytest.raises(ConfigNotRatified, match=f"timing.{Q_D_KEY}"):
        parse_runtime_config(raw)


def test_a_key_nothing_reads_is_refused_in_every_section() -> None:
    from src.paper.runtime_config import ConfigNotRatified, parse_runtime_config

    for section, key in (("health", "invented_seconds"), ("account", "leverage")):
        raw = _valid_config_dict()
        raw[section][key] = 1
        with pytest.raises(ConfigNotRatified, match=f"{section}.{key}"):
            parse_runtime_config(raw)
    parse_runtime_config(_valid_config_dict())  # control: the complete file is accepted


def test_the_readme_documents_the_probe_and_the_unknown_key_rule_without_a_value() -> None:
    text = README.read_text(encoding="utf-8")
    assert "--healthcheck" in text
    assert "unknown key" in text
