"""Plan 16-56: the feed fails closed (review B1-CR-01, 16-DEC-WS-WATCHDOG).

Task 1 (tracer): an exhausted WebSocket rebuild still runs its REST backfill, then the process
fails closed with exit 7 and no RUNTIME_STOP, so the restart policy restarts it and the time is a
CRASH gap.

Task 3: the in-process silence watchdog. When no kline frame of any stream arrives for
`health.feed_silence_timeout_seconds`, the loop enters the supervisor's bounded drop recovery
once; when no frame has arrived when the bound expires again, it fails closed with exit 7. The
watchdog wakes through its own injected sleep (`LoopWiring.watchdog_sleep`) and reads the
injected monotonic feed clock (`LoopWiring.feed_clock`), so these tests move time by hand.

Everything runs through `main` with the real `_LiveLoop` over the SDK-shaped fake client of
`tests/paper_ws_fakes.py`; no network is touched and no tenacity wait is slept for real.
"""

from __future__ import annotations

import ast
import asyncio
import tomllib
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import tenacity
from src.adapters.binance_public import Kline
from src.adapters.paper_ws import PaperWsAdapter
from src.paper import runtime
from src.paper.pipeline import PipelineResult
from src.paper.runtime_config import ExitCode
from src.paper.vocabulary import GapReason, RuntimeEventType, SourceTag, TaggedBar

from tests.paper_ws_fakes import fresh_sdk_stream_map, make_kline_model
from tests.test_paper_runtime_admission import CONFIG_TEXT
from tests.test_paper_runtime_loop import (
    HOUR,
    NOW,
    ONE_MS,
    PAST_OPEN,
    FakePublic,
    FixedClock,
    Live,
    live,
    ms,
    wait_until,
)

__all__ = ["live"]  # the imported fixture


@pytest.fixture(autouse=True)
def _isolated_sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ratified bounds stay in src; only the random wait between attempts is skipped."""
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )


async def until_the_failure_ends_the_run(timeout: float = 10.0) -> None:
    """Park the script until the loop's own failure cancels it.

    Bounded: if no failure comes, the script returns, the stop is clean and the exit is 0, so the
    test fails on its exit-code assertion instead of hanging.
    """
    await asyncio.sleep(timeout)


def _dead_factory(_configuration: object) -> Any:
    raise ConnectionError("ws dead")


# ---------------------------------------------------------------------------------------------- #
# Task 1: the exhaustion half of B1-CR-01.
# ---------------------------------------------------------------------------------------------- #


def test_an_exhausted_rebuild_backfills_then_fails_closed_with_exit_7(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 1)
        h.client.simulate_unsolicited_close()
        await until_the_failure_ends_the_run()

    code = live.start(script, ws_client_factory=_dead_factory)

    assert code == ExitCode.FAIL_CLOSED_RUNTIME == 7
    assert "rebuild" in capsys.readouterr().err
    assert live.records(RuntimeEventType.RUNTIME_STOP) == [], "a crash leaves START open"
    assert len(live.records(RuntimeEventType.WS_DISCONNECT)) == 1
    assert live.records(RuntimeEventType.WS_RECONNECT) == []
    disconnected = [
        g
        for g in live.records(RuntimeEventType.PAPER_GAP)
        if g.payload["reason"] == GapReason.WS_DISCONNECTED.value
    ]
    assert [(g.symbol, g.interval) for g in disconnected] == [("BTCUSDT", "1h")], (
        "the backfill ran and recorded the close it could not recover"
    )
    assert live.client.close_calls >= 1, "the failure still closes the SDK connection"
    assert all(h._unsubscribed == 1 for h in live.client.handles), "every stream is unsubscribed"


# ---------------------------------------------------------------------------------------------- #
# Task 3: the silence watchdog (B1-CR-01 watchdog half, 16-DEC-WS-WATCHDOG).
# ---------------------------------------------------------------------------------------------- #

# The bound of the admission rig's configuration (never a literal of the watchdog itself).
BOUND = float(tomllib.loads(CONFIG_TEXT)["health"]["feed_silence_timeout_seconds"])
HALF = BOUND / 2
SUPERVISOR_SOURCE = Path(__file__).resolve().parent.parent / "src" / "paper" / "supervisor.py"


class Watch:
    """The watchdog's injected monotonic clock and sleep, moved only by `tick`."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.parked: asyncio.Future[None] | None = None
        self.requested: list[timedelta] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, delay: timedelta) -> None:
        self.requested.append(delay)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.parked = future
        await future

    async def tick(self, seconds: float = HALF, *, settle: bool = True) -> None:
        """Move the clock, wake the parked watchdog and (by default) wait until it parks again."""
        await wait_until(lambda: self.parked is not None and not self.parked.done())
        future = self.parked
        assert future is not None
        self.now += seconds
        future.set_result(None)
        if settle:
            await wait_until(lambda: self.parked is not future)

    def release(self, seconds: float) -> None:
        """Move the clock and wake a parked watchdog without waiting (from a spy)."""
        self.now += seconds
        if self.parked is not None and not self.parked.done():
            self.parked.set_result(None)


def _frame(h: Live, symbol: str, interval: str) -> None:
    """One forming (x=False) kline frame on the newest client: a message, never a closed bar."""
    target = h.clients[-1]
    stream = f"{symbol.lower()}@kline_{interval}"
    handle = next(c for c in reversed(target.handles) if c._stream == stream)
    handle._emit(
        make_kline_model(
            symbol=symbol,
            interval=interval,
            open_time_ms=ms(NOW),
            close_time_ms=ms(NOW + HOUR - ONE_MS),
            is_closed=False,
        )
    )


class RecordingPipeline:
    """A pipeline double that records every bar it is handed, with its source tag."""

    def __init__(self) -> None:
        self.bars: list[TaggedBar] = []

    def handle(self, bars: Any, *, now_utc: Any) -> PipelineResult:
        self.bars.extend(bars)
        return PipelineResult()


class SilencePublic(FakePublic):
    """REST serves the BTCUSDT 1h bar that closed during the silence (NOW + 1 h - 1 ms), once armed.

    Not armed during the start's warm-up, so the bar is unknown until the recovery's backfill.
    """

    armed = False

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        self.klines_calls.append((symbol, interval))
        if not self.armed or (symbol, interval) != ("BTCUSDT", "1h") or start_ms is None:
            return []
        opened = NOW
        if ms(opened) < start_ms:
            return []
        return [
            Kline(
                symbol=symbol,
                interval=interval,
                open_time_utc=opened,
                close_time_utc=NOW + HOUR - ONE_MS,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("1"),
                quote_volume=Decimal("100"),
                trade_count=1,
            )
        ]


def _watched(watch: Watch, **overrides: Any) -> dict[str, Any]:
    return {"feed_clock": watch.clock, "watchdog_sleep": watch.sleep, **overrides}


def test_normal_feed_activity_on_any_stream_never_trips_the_watchdog(live: Live) -> None:
    watch = Watch()

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        for symbol, interval in [("BTCUSDT", "1h"), ("ETHUSDT", "4h"), ("BTCUSDT", "4h")] * 3:
            _frame(h, symbol, interval)  # forming updates only
            await watch.tick()

    assert live.start(script, **_watched(watch)) == 0
    assert live.records(RuntimeEventType.WS_DISCONNECT) == []
    assert len(live.clients) == 1, "no recovery"
    assert set(watch.requested) == {timedelta(seconds=HALF)}, "wakes at half the bound"


def test_one_quiet_symbol_never_trips_the_connection_wide_clock(live: Live) -> None:
    """Correction 2: a qualifying message is any frame on the connection, not per symbol."""
    watch = Watch()

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        for _ in range(8):  # BTCUSDT stays quiet for four bounds
            _frame(h, "ETHUSDT", "1h")
            await watch.tick()

    assert live.start(script, **_watched(watch)) == 0
    assert live.records(RuntimeEventType.WS_DISCONNECT) == []


def test_a_half_open_connection_enters_the_bounded_recovery_and_backfills_as_history(
    live: Live,
) -> None:
    watch = Watch()
    pipeline = RecordingPipeline()
    public = SilencePublic()
    live.public = public
    clock = FixedClock()

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)  # the cursor: the last live close
        await wait_until(lambda: len(pipeline.bars) == 1)
        clock.advance(2 * HOUR)  # the silence spans the next hourly close, after the start
        public.armed = True  # the bar that closed during the silence now exists on REST
        await watch.tick()
        await watch.tick()  # exactly the bound: not yet "more than" the bound
        assert h.records(RuntimeEventType.WS_DISCONNECT) == []
        await watch.tick()  # silent for more than the bound: the recovery starts
        await wait_until(lambda: bool(h.records(RuntimeEventType.WS_RECONNECT)))
        await wait_until(lambda: len(pipeline.bars) == 2)
        _frame(h, "ETHUSDT", "1h")  # messages resume on the rebuilt connection
        for _ in range(4):
            await watch.tick()
            _frame(h, "ETHUSDT", "1h")

    code = live.start(script, clock=clock, pipeline=pipeline, **_watched(watch))

    assert code == 0
    assert len(live.records(RuntimeEventType.WS_DISCONNECT)) == 1, "the feed was marked lost"
    assert len(live.clients) == 2, "one bounded rebuild"
    live_bar, backfilled = pipeline.bars
    assert live_bar.source is SourceTag.LIVE_WS
    assert backfilled.source is SourceTag.REST_BACKFILL, "history only, never a late signal"
    assert backfilled.close_time_utc == NOW + HOUR - ONE_MS


def test_a_silence_that_outlasts_the_recovery_fails_closed_with_exit_7(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    watch = Watch()

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        for _ in range(3):
            await watch.tick()
        await wait_until(lambda: bool(h.records(RuntimeEventType.WS_RECONNECT)))
        await watch.tick()  # half the bound since the recovery began: still waiting
        await watch.tick(settle=False)  # the bound expired again with no message
        await until_the_failure_ends_the_run()

    code = live.start(script, **_watched(watch))

    assert code == ExitCode.FAIL_CLOSED_RUNTIME == 7
    assert "market stream silent" in capsys.readouterr().err
    assert live.records(RuntimeEventType.RUNTIME_STOP) == []
    assert len(live.records(RuntimeEventType.WS_DISCONNECT)) == 1, "one recovery per silence"


def test_a_clean_disconnect_goes_through_the_sdk_close_path_with_no_double_recovery(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SDK close starts the recovery; a silence during that rebuild never starts another."""
    watch = Watch()
    gate = asyncio.Event()
    original = PaperWsAdapter.rebuild

    async def slow_rebuild(self: PaperWsAdapter) -> None:
        await gate.wait()
        await original(self)

    monkeypatch.setattr(PaperWsAdapter, "rebuild", slow_rebuild)

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        _frame(h, "BTCUSDT", "1h")
        h.client.simulate_unsolicited_close()
        await wait_until(lambda: bool(h.records(RuntimeEventType.WS_DISCONNECT)))
        for _ in range(3):  # silent for more than the bound while the rebuild runs
            await watch.tick()
        gate.set()
        await wait_until(lambda: bool(h.records(RuntimeEventType.WS_RECONNECT)))
        _frame(h, "BTCUSDT", "1h")
        await watch.tick()
        _frame(h, "BTCUSDT", "1h")
        await watch.tick()

    assert live.start(script, **_watched(watch)) == 0
    assert len(live.records(RuntimeEventType.WS_DISCONNECT)) == 1
    assert len(live.records(RuntimeEventType.WS_RECONNECT)) == 1
    assert len(live.clients) == 2, "exactly one rebuild"


def _count_fail_calls(monkeypatch: pytest.MonkeyPatch, after: Any = None) -> list[BaseException]:
    calls: list[BaseException] = []
    original = runtime._LiveLoop._fail

    def spy(self: Any, exc: BaseException) -> None:
        calls.append(exc)
        original(self, exc)
        if after is not None:
            after()

    monkeypatch.setattr(runtime._LiveLoop, "_fail", spy)
    return calls


def test_one_fail_closed_cause_when_the_deadline_passes_while_the_rebuild_still_runs(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 1b: the watchdog fails the process; the released rebuild then exhausts: one _fail."""
    watch = Watch()
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def blocked_rebuild(self: PaperWsAdapter) -> None:
        entered.set()
        await gate.wait()
        raise ConnectionError("ws dead")

    monkeypatch.setattr(PaperWsAdapter, "rebuild", blocked_rebuild)
    calls = _count_fail_calls(monkeypatch, after=gate.set)  # release with a failure afterwards

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        for _ in range(3):
            await watch.tick()
        await wait_until(entered.is_set)
        await watch.tick()
        await watch.tick(settle=False)  # the second deadline, the rebuild still blocked
        await until_the_failure_ends_the_run()

    code = live.start(script, **_watched(watch))

    assert code == ExitCode.FAIL_CLOSED_RUNTIME == 7
    assert len(calls) == 1 and isinstance(calls[0], runtime.RuntimeFailClosed)
    assert "market stream silent" in str(calls[0])
    assert live.records(RuntimeEventType.RUNTIME_STOP) == []


def test_one_fail_closed_cause_when_the_rebuild_exhausts_before_the_deadline(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 1b, reverse order: on_fatal fails the process, then the watchdog's deadline passes."""
    watch = Watch()

    async def dead_rebuild(self: PaperWsAdapter) -> None:
        raise ConnectionError("ws dead")

    monkeypatch.setattr(PaperWsAdapter, "rebuild", dead_rebuild)
    calls = _count_fail_calls(monkeypatch, after=lambda: watch.release(4 * BOUND))

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        for _ in range(3):
            await watch.tick()
        await until_the_failure_ends_the_run()

    code = live.start(script, **_watched(watch))

    assert code == ExitCode.FAIL_CLOSED_RUNTIME == 7
    assert len(calls) == 1 and isinstance(calls[0], runtime.RuntimeFailClosed)
    assert "rebuild" in str(calls[0])
    assert live.records(RuntimeEventType.RUNTIME_STOP) == []


def test_the_frame_stamp_is_one_attribute_write_before_the_closed_filter() -> None:
    """Correction 2: every kline frame stamps one connection-wide clock on the SDK thread, with
    no I/O there; the stamp comes before the `is_closed` filter (forming updates count)."""
    tree = ast.parse(SUPERVISOR_SOURCE.read_text(encoding="utf-8"))
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_on_kline"
    )
    first, second = handler.body[0], handler.body[1]
    assert isinstance(first, ast.Assign) and len(first.targets) == 1
    target = first.targets[0]
    assert isinstance(target, ast.Attribute) and target.attr == "_last_frame_monotonic"
    assert isinstance(target.value, ast.Name) and target.value.id == "self", "one shared stamp"
    calls = [n for n in ast.walk(first) if isinstance(n, ast.Call)]
    assert len(calls) == 1 and isinstance(calls[0].func, ast.Attribute)
    assert calls[0].func.attr == "_feed_clock", "only the injected monotonic reading"
    assert isinstance(second, ast.If) and "is_closed" in ast.unparse(second.test)


def test_the_watchdog_reads_its_bound_only_from_the_configuration() -> None:
    tree = ast.parse((SUPERVISOR_SOURCE.parent / "runtime.py").read_text(encoding="utf-8"))
    watchdog = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_watch_feed"
    )
    assert "health.feed_silence_timeout_seconds" in ast.unparse(watchdog)
    numbers = [
        n.value
        for n in ast.walk(watchdog)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, int | float)
        and not isinstance(n.value, bool)
    ]
    assert set(numbers) <= {2}, f"only the half-bound divisor may be a literal: {numbers}"
