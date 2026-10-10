"""Plan 16-29: restart, downtime and warm-up of the paper runtime (D-02, D-04, D-06, L-04, L-11,
REV-01, research Pitfall P8).

Task 1 (tracer): a planned restart restores the last closes from the state port, records the
downtime closes as gaps (PLANNED_RESTART after a RUNTIME_STOP, CRASH without one), seeds the
supervisor and warms the engine windows up from REST before subscribing, and evaluates only the
next closed LIVE_WS bar. A restart fence keeps every bar that closed at or before the warm-up
snapshot out of evaluation, whatever the user's Q-D answer is.

No network is touched: the SDK client and the public adapter are fakes and the state is the
in-memory reference port (the PostgreSQL variant is `tests/test_paper_runtime_restart_pg.py`).
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import src.domain.registry as domain_registry
from src.adapters.binance_public import Kline
from src.core.types import Candle
from src.paper import pipeline as pipeline_module
from src.paper import runtime
from src.paper.bars import BarBuffers
from src.paper.freeze import StreamEpoch
from src.paper.pipeline import BarPipeline, PipelineResult
from src.paper.runtime_state import InMemoryRuntimeState, RuntimeRecord
from src.paper.supervisor import PaperSupervisor
from src.paper.vocabulary import RuntimeEventType, SourceTag, TaggedBar

from tests.paper_ws_fakes import make_kline_model
from tests.test_paper_decision_surface import (
    PASSING_BAR,
    _bar_context,
    _case_input,
    _context_bars,
    _setup_bars,
)
from tests.test_paper_runtime_admission import _Rig
from tests.test_paper_runtime_loop import (  # noqa: F401 - fixtures are used by name
    FakePublic,
    FixedClock,
    Live,
    _isolated_sdk_stream_map,
    ms,
    wait_until,
)
from tests.test_paper_runtime_pipeline import _parameter_set
from tests.test_rationale import write_rationalized_set

# The registry root before any fixture re-points it to a temporary one (the parity case needs it).
REAL_REGISTRY_ROOT = domain_registry.REGISTRY_ROOT
ONE_MS = timedelta(milliseconds=1)
HOUR = timedelta(hours=1)
FOUR_HOURS = timedelta(hours=4)

# The last close both pairs processed before the stop: on the 1h and the 4h exchange grid.
C = datetime(2026, 10, 10, 15, 59, 59, 999000, tzinfo=UTC)
# The restart: three 1h closes (C + 1h, C + 2h, C + 3h) and no 4h close happened meanwhile.
RESTART = datetime(2026, 10, 10, 19, 5, tzinfo=UTC)
STOP_AT = C + timedelta(minutes=10)
START_AT = datetime(2026, 10, 10, 13, 0, tzinfo=UTC)
DOWNTIME_CLOSES = (C + HOUR, C + 2 * HOUR, C + 3 * HOUR)


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    """A pinned, admitted runtime state (the same rig the loop tests use)."""
    import src.domain.registry as domain_registry

    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    yield Live(rig)


def restart_module() -> ModuleType:
    """The module under test, imported lazily so a missing module fails each test on its own."""
    return importlib.import_module("src.paper.restart")


def exchange_kline(symbol: str, interval: str, open_time: datetime, step: timedelta) -> Kline:
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=open_time + step - ONE_MS,
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1"),
        quote_volume=Decimal("100"),
        trade_count=1,
    )


class RecordedCall:
    def __init__(self, symbol: str, interval: str, start_ms: int | None, limit: int) -> None:
        self.symbol = symbol
        self.interval = interval
        self.start_ms = start_ms
        self.limit = limit


class WarmPublic(FakePublic):
    """A public adapter that serves a synthetic, gap-free exchange history up to `now`.

    `omit_opens` removes bars the exchange does not return (a hole). Real exchanges return the
    forming bar too, so the newest row is the bar that has not closed yet.
    """

    def __init__(
        self,
        now: datetime,
        *,
        omit_opens: Sequence[tuple[str, str, datetime]] = (),
        rows: dict[tuple[str, str], list[Kline]] | None = None,
        late_opens: Sequence[tuple[str, str, datetime]] = (),
    ) -> None:
        super().__init__(server_time=now)
        self.now = now
        self.omit = set(omit_opens)
        self.rows = rows
        self.late = set(late_opens)
        self.calls: list[RecordedCall] = []
        self._seen_pairs: dict[tuple[str, str], int] = {}

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        self.klines_calls.append((symbol, interval))
        self.calls.append(RecordedCall(symbol, interval, start_ms, limit))
        index = self._seen_pairs.get((symbol, interval), 0)
        self._seen_pairs[(symbol, interval)] = index + 1
        if start_ms is None:
            raise AssertionError("a warm-up or backfill request needs a start")
        if self.rows is not None:
            rows = [
                k
                for k in self.rows.get((symbol, interval), [])
                if not (index == 0 and (symbol, interval, k.open_time_utc) in self.late)
            ]
            return [k for k in rows if ms(k.open_time_utc) >= start_ms][:limit]
        step = timedelta(hours=1) if interval == "1h" else FOUR_HOURS
        step_ms = step // ONE_MS
        forming_ms = ((ms(self.now)) // step_ms) * step_ms
        out: list[Kline] = []
        cursor = start_ms
        while cursor <= forming_ms and len(out) < limit:
            opened = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=cursor)
            if (symbol, interval, opened) not in self.omit:
                out.append(exchange_kline(symbol, interval, opened, step))
            cursor += step_ms
        return out


class RecordingPipeline:
    """A pipeline double: logs every batch, 'evaluates' closed LIVE_WS 1h bars, records them."""

    def __init__(self, state: InMemoryRuntimeState | None = None, epoch_id: str = "") -> None:
        self.batches: list[tuple[list[TaggedBar], datetime]] = []
        self.evaluated: list[TaggedBar] = []
        self._state = state
        self._epoch_id = epoch_id

    def handle(self, bars: Any, *, now_utc: datetime) -> PipelineResult:
        batch = list(bars)
        self.batches.append((batch, now_utc))
        live_1h = [b for b in batch if b.source is SourceTag.LIVE_WS and b.interval == "1h"]
        self.evaluated.extend(live_1h)
        if self._state is not None:
            for bar in batch:
                if bar.source is SourceTag.LIVE_WS:
                    self._state.record(
                        RuntimeRecord.bar_processed(
                            epoch_id=self._epoch_id,
                            symbol=bar.symbol,
                            interval=bar.interval,
                            close_time_utc=bar.close_time_utc,
                            payload={"source": "LIVE_WS", "tick_time_utc": now_utc},
                        )
                    )
        return PipelineResult(evaluated=tuple(object() for _ in live_1h))  # type: ignore[misc]


def seed_history(live_rig: Live, *, with_stop: bool) -> None:
    """The state a stopped process leaves behind: START, processed closes up to C, maybe STOP."""
    state = live_rig.state
    epoch = live_rig.epoch
    base = {
        "strategy_id": epoch.strategy_id,
        "parameter_set_id": epoch.parameter_set_id,
        "parameter_set_hash": epoch.parameter_set_hash,
    }
    state.record(
        RuntimeRecord(
            event_type=RuntimeEventType.RUNTIME_START,
            epoch_id=epoch.epoch_id,
            occurred_at_utc=START_AT,
            payload=base,
        )
    )
    for interval in ("1h", "4h"):
        state.record(
            RuntimeRecord.bar_processed(
                epoch_id=epoch.epoch_id,
                symbol="BTCUSDT",
                interval=interval,
                close_time_utc=C,
                payload={"source": "LIVE_WS", "tick_time_utc": C + timedelta(seconds=2)},
            )
        )
    if with_stop:
        state.record(
            RuntimeRecord(
                event_type=RuntimeEventType.RUNTIME_STOP,
                epoch_id=epoch.epoch_id,
                occurred_at_utc=STOP_AT,
                payload=base,
            )
        )


@dataclass
class SupervisorTrace:
    order: list[str]
    seeded: list[tuple[str, str, datetime]]


@pytest.fixture
def supervisor_trace(monkeypatch: pytest.MonkeyPatch) -> SupervisorTrace:
    """Record the order of `record_close` and `start` on every supervisor."""
    trace = SupervisorTrace(order=[], seeded=[])
    real_record_close = PaperSupervisor.record_close
    real_start = PaperSupervisor.start

    def record_close(self: PaperSupervisor, symbol: str, interval: str, close: datetime) -> None:
        trace.order.append("record_close")
        trace.seeded.append((symbol, interval, close))
        real_record_close(self, symbol, interval, close)

    async def start(self: PaperSupervisor) -> None:
        trace.order.append("start")
        await real_start(self)

    monkeypatch.setattr(PaperSupervisor, "record_close", record_close)
    monkeypatch.setattr(PaperSupervisor, "start", start)
    return trace


def gap_triples(records: Sequence[RuntimeRecord]) -> list[tuple[str, str, str, str]]:
    return sorted(
        (
            str(r.symbol),
            str(r.interval),
            str(r.payload["expected_close_utc"]),
            str(r.payload["reason"]),
        )
        for r in records
    )


def next_live_open() -> datetime:
    return datetime(2026, 10, 10, 19, 0, tzinfo=UTC)


def run_restart(
    live_rig: Live,
    *,
    with_stop: bool,
    clock: FixedClock | None = None,
    public: WarmPublic | None = None,
    emit_live: bool = True,
    extra_script: Callable[[Live, WarmPublic], Any] | None = None,
) -> tuple[RecordingPipeline, WarmPublic, FixedClock]:
    seed_history(live_rig, with_stop=with_stop)
    clock = clock or FixedClock(RESTART)
    public = public or WarmPublic(RESTART)
    pipeline = RecordingPipeline()

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        if extra_script is not None:
            await extra_script(h, public)
        if emit_live:
            clock.now = next_live_open() + HOUR + timedelta(seconds=1)
            h.emit("BTCUSDT", "1h", open_time=next_live_open())
            await wait_until(lambda: len(pipeline.evaluated) == 1)

    assert live_rig.start(script, clock=clock, public=public, pipeline=pipeline) == 0
    return pipeline, public, clock


# ---------------------------------------------------------------------------------------------- #
# Task 1, Test 1: a planned restart.
# ---------------------------------------------------------------------------------------------- #


def test_planned_restart_restores_warms_up_records_the_gaps_and_evaluates_the_next_live_bar(
    live: Live, supervisor_trace: SupervisorTrace
) -> None:
    pipeline, public, _ = run_restart(live, with_stop=True)

    # The warm-up is the first batch the pipeline sees: exactly the engine windows, REST_WARMUP.
    warm_bars, warm_time = pipeline.batches[0]
    assert warm_time == RESTART
    assert {b.source for b in warm_bars} == {SourceTag.REST_WARMUP}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        ones = [b for b in warm_bars if b.symbol == symbol and b.interval == "1h"]
        fours = [b for b in warm_bars if b.symbol == symbol and b.interval == "4h"]
        assert len(ones) == 1000 and len(fours) == 300
        assert max(b.close_time_utc for b in ones) == RESTART.replace(minute=0) - ONE_MS
        assert max(b.close_time_utc for b in fours) == C
        assert all(b.close_time_utc <= RESTART for b in ones + fours), "a forming bar never enters"
    assert len(public.calls) == 4, "one request per (symbol, interval): no live REST traffic else"

    # Downtime closes are explained gaps, never bars: PLANNED_RESTART, uncovered, one per close.
    gaps = live.records(RuntimeEventType.PAPER_GAP)
    assert gap_triples(gaps) == sorted(
        ("BTCUSDT", "1h", close.isoformat(), "PLANNED_RESTART") for close in DOWNTIME_CLOSES
    )
    assert {str(g.payload["source"]) for g in gaps} == {"RESTART"}

    # The supervisor cursor is the newest close of the warm-up snapshot, seeded before start.
    assert supervisor_trace.order[-1] == "start"
    assert supervisor_trace.order.count("start") == 1
    assert set(supervisor_trace.order[:-1]) == {"record_close"}
    newest_1h = RESTART.replace(minute=0) - ONE_MS
    assert ("BTCUSDT", "1h", newest_1h) in supervisor_trace.seeded
    assert ("BTCUSDT", "4h", C) in supervisor_trace.seeded
    assert not any(close == C for _, interval, close in supervisor_trace.seeded if interval == "1h")

    # Only the next closed LIVE_WS 1h bar is evaluated, exactly once.
    assert [b.close_time_utc for b in pipeline.evaluated] == [next_live_open() + HOUR - ONE_MS]
    assert all(b.source is SourceTag.LIVE_WS for b in pipeline.evaluated)


# ---------------------------------------------------------------------------------------------- #
# Task 1, Test 2: no STOP means CRASH.
# ---------------------------------------------------------------------------------------------- #


def test_the_same_history_without_a_stop_record_gives_the_crash_reason(live: Live) -> None:
    run_restart(live, with_stop=False)

    gaps = live.records(RuntimeEventType.PAPER_GAP)
    assert gap_triples(gaps) == sorted(
        ("BTCUSDT", "1h", close.isoformat(), "CRASH") for close in DOWNTIME_CLOSES
    )


# ---------------------------------------------------------------------------------------------- #
# Task 1, Test 3: health states around the warm-up.
# ---------------------------------------------------------------------------------------------- #


def test_health_is_disconnected_until_the_first_live_closed_event_then_healthy(
    live: Live,
) -> None:
    seen_before_live: list[tuple[str, ...]] = []

    async def extra(h: Live, _public: WarmPublic) -> None:
        seen_before_live.append(
            tuple(str(r.payload["state"]) for r in h.records(RuntimeEventType.HEALTH_STATE_CHANGED))
        )

    run_restart(live, with_stop=True, extra_script=extra)

    assert seen_before_live == [("DISCONNECTED",)], "no HEALTHY before a live closed event"
    health = live.records(RuntimeEventType.HEALTH_STATE_CHANGED)
    assert [str(r.payload["state"]) for r in health] == ["DISCONNECTED", "HEALTHY"]
    disconnected, healthy = health
    assert disconnected.occurred_at_utc == RESTART, "from the RUNTIME_START of this run"
    assert disconnected.payload["reason"] == "WS_RECONNECT_WINDOW"
    assert healthy.occurred_at_utc == next_live_open() + HOUR + timedelta(seconds=1)
    starts = [
        r for r in live.records(RuntimeEventType.RUNTIME_START) if r.occurred_at_utc == RESTART
    ]
    assert len(starts) == 1


# ---------------------------------------------------------------------------------------------- #
# Task 1, Test 4: no late signal for any Q-D answer (D-06, L-11).
# ---------------------------------------------------------------------------------------------- #

# The user's three possible Q-D answers. Only history-only exists in src (the ratified rule); the
# other two are modelled test-locally by a wrapper that admits REST_BACKFILL bars as live ones,
# which is exactly the hazard the restart fence has to remove before the pipeline.
RULES = ("history-only", "fresh-within-bound", "evaluate-all")


class RulePipeline:
    """The real `BarPipeline` behind a Q-D rule that decides whether a backfill bar is live."""

    def __init__(self, real: BarPipeline, rule: str) -> None:
        self.real = real
        self.rule = rule
        self.bound = timedelta(days=36500)
        self.closes_seen: list[tuple[str, str, datetime]] = []

    def handle(self, bars: Any, *, now_utc: datetime) -> PipelineResult:
        mapped: list[TaggedBar] = []
        for bar in bars:
            self.closes_seen.append((bar.symbol, bar.interval, bar.close_time_utc))
            if bar.source is SourceTag.REST_BACKFILL and (
                self.rule == "evaluate-all"
                or (
                    self.rule == "fresh-within-bound" and now_utc - bar.close_time_utc <= self.bound
                )
            ):
                bar = replace(bar, source=SourceTag.LIVE_WS)
            mapped.append(bar)
        return self.real.handle(mapped, now_utc=now_utc)


def exchange_candles(candles: Sequence[Candle], step: timedelta) -> list[Candle]:
    """The parity candles on the exchange convention: close = open + interval - 1 ms."""
    return [replace(c, close_time_utc=c.open_time_utc + step - ONE_MS) for c in candles]


def to_kline(candle: Candle) -> Kline:
    return Kline(
        symbol=candle.symbol,
        interval=candle.interval,
        open_time_utc=candle.open_time_utc,
        close_time_utc=candle.close_time_utc,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        quote_volume=candle.volume,
        trade_count=1,
    )


class DowntimeRig:
    """The parity history as the exchange serves it, a restart 31 seconds after bar 248 closed."""

    def __init__(self, live_rig: Live, rule: str, monkeypatch: pytest.MonkeyPatch) -> None:
        # Admission uses the explicit temporary root; the parity set lives in the real registry.
        monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", REAL_REGISTRY_ROOT)
        self.live = live_rig
        self.case = _case_input()
        self.setup = exchange_candles(_setup_bars(self.case), HOUR)
        self.context = exchange_candles(_context_bars(self.case), FOUR_HOURS)
        self.downtime = self.setup[PASSING_BAR - 1]  # closed 31 s before the restart, fresh
        self.snapshot = self.downtime.close_time_utc + ONE_MS + timedelta(seconds=30)
        self.last_processed = self.setup[PASSING_BAR - 4]
        self.live_bar = self.setup[PASSING_BAR]
        self.live_context = self.context[-1]
        epoch = live_rig.epoch
        parameter_set = _parameter_set(self.case)
        self.pipeline = BarPipeline(
            epoch=StreamEpoch(
                epoch_id=epoch.epoch_id,
                strategy_id=self.case["strategy_id"],
                parameter_set_id=self.case["parameter_set_id"],
                parameter_set_hash=parameter_set.parameter_set_hash,
                opened_at_utc=epoch.opened_at_utc,
            ),
            parameter_set=parameter_set,
            context_factory=lambda candle: _bar_context(self.case, candle.close_time_utc),
            buffers=BarBuffers(),
            state=live_rig.state,
            sibling_4h_wait_seconds=30,
            fetch_4h_bar=lambda _symbol, _close: None,
        )
        self.rule = RulePipeline(self.pipeline, rule)
        self.clock = FixedClock(self.snapshot)
        history_1h = self.setup[:PASSING_BAR]  # opens up to bar 248; the exchange is late for 248
        history_4h = [c for c in self.context if c.close_time_utc <= self.snapshot]
        self.public = WarmPublic(
            self.snapshot,
            rows={
                ("BTCUSDT", "1h"): [to_kline(c) for c in history_1h],
                ("BTCUSDT", "4h"): [to_kline(c) for c in history_4h],
            },
            late_opens=[("BTCUSDT", "1h", self.downtime.open_time_utc)],
        )

    def seed(self) -> None:
        state = self.live.state
        epoch = self.live.epoch
        start = self.last_processed.open_time_utc
        for kind, at in (
            (RuntimeEventType.RUNTIME_START, start - timedelta(hours=4)),
            (
                RuntimeEventType.RUNTIME_STOP,
                self.last_processed.close_time_utc + timedelta(minutes=5),
            ),
        ):
            state.record(
                RuntimeRecord(event_type=kind, epoch_id=epoch.epoch_id, occurred_at_utc=at)
            )
        state.record(
            RuntimeRecord.bar_processed(
                epoch_id=epoch.epoch_id,
                symbol="BTCUSDT",
                interval="1h",
                close_time_utc=self.last_processed.close_time_utc,
                payload={"source": "LIVE_WS", "tick_time_utc": self.last_processed.close_time_utc},
            )
        )

    def emit(self, h: Live, candle: Candle) -> None:
        h.handle(candle.symbol, candle.interval)._emit(
            make_kline_model(
                symbol=candle.symbol,
                interval=candle.interval,
                open_time_ms=ms(candle.open_time_utc),
                close_time_ms=ms(candle.close_time_utc),
                open_=str(candle.open),
                high=str(candle.high),
                low=str(candle.low),
                close=str(candle.close),
                volume=str(candle.volume),
            )
        )

    def run(self) -> None:
        self.seed()

        async def script(h: Live) -> None:
            await wait_until(lambda: len(h.client.handles) == 4)
            # The initial connection event: the supervisor verifies the seam against REST.
            for callback in list(h.client.connection_callbacks["open"]):
                callback()
            key = ("BTCUSDT", "1h", self.downtime.close_time_utc)
            await wait_until(lambda: key in self.rule.closes_seen)
            self.clock.now = self.live_bar.close_time_utc + timedelta(seconds=1)
            self.emit(h, self.live_context)
            self.emit(h, self.live_bar)
            await wait_until(
                lambda: any(
                    r.symbol == "BTCUSDT"
                    and r.interval == "1h"
                    and r.occurred_at_utc == self.live_bar.close_time_utc
                    for r in h.records(RuntimeEventType.PAPER_BAR_PROCESSED)
                )
            )

        assert (
            self.live.start(script, clock=self.clock, public=self.public, pipeline=self.rule) == 0
        )


@pytest.fixture
def evaluations(monkeypatch: pytest.MonkeyPatch) -> list[Candle]:
    seen: list[Candle] = []
    real = pipeline_module.evaluate_closed_bar

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "evaluate_closed_bar", spy)
    return seen


@pytest.mark.parametrize("rule", RULES)
def test_no_bar_that_closed_during_downtime_is_evaluated_whatever_the_qd_rule_is(
    live: Live, evaluations: list[Candle], rule: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = DowntimeRig(live, rule, monkeypatch)
    rig.run()

    assert [c.close_time_utc for c in evaluations] == [rig.live_bar.close_time_utc]
    gaps = [
        g
        for g in live.records(RuntimeEventType.PAPER_GAP)
        if g.symbol == "BTCUSDT" and g.interval == "1h"
    ]
    expected = [
        rig.setup[i].close_time_utc.isoformat()
        for i in (PASSING_BAR - 3, PASSING_BAR - 2, PASSING_BAR - 1)
    ]
    assert sorted(str(g.payload["expected_close_utc"]) for g in gaps) == expected, (
        "exactly one PAPER_GAP per downtime close"
    )
    assert not any(g.payload["reason"] == "WS_RECONNECT_WINDOW" for g in gaps)


def test_negative_control_without_the_fence_the_evaluate_all_rule_does_evaluate_a_downtime_bar(
    live: Live, evaluations: list[Candle], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "apply_restart_fence", lambda bar, _fence: bar)
    rig = DowntimeRig(live, "evaluate-all", monkeypatch)
    rig.run()

    assert rig.downtime.close_time_utc in [c.close_time_utc for c in evaluations], (
        "the spy would catch a late signal: the hazard is real without the fence"
    )


# ---------------------------------------------------------------------------------------------- #
# The pure fence helper.
# ---------------------------------------------------------------------------------------------- #


def tagged(source: SourceTag, close: datetime, interval: str = "1h") -> TaggedBar:
    step = HOUR if interval == "1h" else FOUR_HOURS
    return TaggedBar(
        symbol="BTCUSDT",
        interval=interval,
        open_time_utc=close + ONE_MS - step,
        close_time_utc=close,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("1"),
        source=source,
    )


def test_fence_demotes_non_live_bars_at_or_before_the_fence_to_history_only() -> None:
    fence = RESTART
    module = restart_module()
    before = tagged(SourceTag.REST_BACKFILL, RESTART - HOUR)
    at = tagged(SourceTag.REST_BACKFILL, RESTART)
    after = tagged(SourceTag.REST_BACKFILL, RESTART + HOUR)
    warm = tagged(SourceTag.REST_WARMUP, RESTART - HOUR)
    live_old = tagged(SourceTag.LIVE_WS, RESTART - HOUR)

    assert module.apply_restart_fence(before, fence).source is SourceTag.REST_WARMUP
    assert module.apply_restart_fence(at, fence).source is SourceTag.REST_WARMUP
    assert module.apply_restart_fence(after, fence) is after, "a later recovery keeps its tag"
    assert module.apply_restart_fence(warm, fence) is warm
    assert module.apply_restart_fence(live_old, fence) is live_old, "a live bar is never re-tagged"
    changed = module.apply_restart_fence(before, fence)
    assert replace(changed, source=SourceTag.REST_BACKFILL) == before, "only the tag changes"


def test_warm_up_asks_for_exactly_the_engine_windows_and_drops_the_forming_bar() -> None:
    import asyncio

    module = restart_module()
    public = WarmPublic(RESTART)
    result = asyncio.run(module.warm_up(public, ("BTCUSDT",), ("1h", "4h"), RESTART))

    ones = [b for b in result.bars if b.interval == "1h"]
    fours = [b for b in result.bars if b.interval == "4h"]
    assert (len(ones), len(fours)) == (1000, 300)
    assert ones[-1].close_time_utc == RESTART.replace(minute=0) - ONE_MS
    assert fours[-1].close_time_utc == C
    assert [call.interval for call in public.calls] == ["1h", "4h"]
    assert all(b.source is SourceTag.REST_WARMUP for b in result.bars)


def test_downtime_gaps_use_the_exchange_grid_and_the_previous_runs_end() -> None:
    module = restart_module()
    state = InMemoryRuntimeState()
    epoch_id = "e" * 64
    for kind, at in (
        (RuntimeEventType.RUNTIME_START, START_AT),
        (RuntimeEventType.RUNTIME_STOP, STOP_AT),
    ):
        state.record(RuntimeRecord(event_type=kind, epoch_id=epoch_id, occurred_at_utc=at))
    state.record(
        RuntimeRecord.bar_processed(
            epoch_id=epoch_id, symbol="BTCUSDT", interval="1h", close_time_utc=C
        )
    )
    restored = module.restore_runtime(state, epoch_id)
    assert dict(restored.last_closes) == {("BTCUSDT", "1h"): C}

    gaps = module.downtime_gaps(
        restored, now_utc=RESTART, symbols=("BTCUSDT", "ETHUSDT"), intervals=("1h", "4h")
    )

    assert [g.expected_close_utc for g in gaps] == list(DOWNTIME_CLOSES)
    assert {g.reason.value for g in gaps} == {"PLANNED_RESTART"}
    assert {g.detected_at_utc for g in gaps} == {RESTART}
    nothing = module.downtime_gaps(restored, now_utc=C, symbols=("BTCUSDT",), intervals=("1h",))
    assert nothing == (), "no close is due yet: nothing is downtime"


# ---------------------------------------------------------------------------------------------- #
# Task 2, Test 1: the pinned state file and the stored EPOCH_PINNED record must agree.
# ---------------------------------------------------------------------------------------------- #


def pin_record(epoch: StreamEpoch, *, parameter_set_hash: str | None = None) -> RuntimeRecord:
    return RuntimeRecord(
        event_type=RuntimeEventType.EPOCH_PINNED,
        epoch_id=epoch.epoch_id,
        occurred_at_utc=epoch.opened_at_utc,
        payload={
            "strategy_id": epoch.strategy_id,
            "parameter_set_id": epoch.parameter_set_id,
            "parameter_set_hash": parameter_set_hash or epoch.parameter_set_hash,
        },
    )


def test_check_epoch_consistency_accepts_a_match_and_refuses_everything_else(live: Live) -> None:
    module = restart_module()
    epoch = live.epoch

    module.check_epoch_consistency(epoch, live.state)  # the pin run recorded it: no exception

    empty = InMemoryRuntimeState()
    with pytest.raises(module.EpochMismatch, match="no EPOCH_PINNED"):
        module.check_epoch_consistency(epoch, empty)

    other_hash = InMemoryRuntimeState()
    other_hash.record(pin_record(epoch, parameter_set_hash="f" * 64))
    with pytest.raises(module.EpochMismatch, match="differs"):
        module.check_epoch_consistency(epoch, other_hash)

    other_time = InMemoryRuntimeState()
    other_time.record(
        RuntimeRecord(
            event_type=RuntimeEventType.EPOCH_PINNED,
            epoch_id=epoch.epoch_id,
            occurred_at_utc=epoch.opened_at_utc + timedelta(seconds=1),
            payload=dict(pin_record(epoch).payload),
        )
    )
    with pytest.raises(module.EpochMismatch, match="differs"):
        module.check_epoch_consistency(epoch, other_time)


def test_a_restart_with_a_missing_or_different_pin_record_exits_6_before_any_subscription(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    epoch = live.epoch
    missing = InMemoryRuntimeState()
    different = InMemoryRuntimeState()
    different.record(pin_record(epoch, parameter_set_hash="f" * 64))

    for state in (missing, different):

        async def script(_h: Live) -> None:
            raise AssertionError("the loop must not start")

        code = live.start(
            script, state=state, public=WarmPublic(RESTART), clock=FixedClock(RESTART)
        )

        assert code == 6, "ADMISSION_OR_EPOCH_MISMATCH: a refusal held by the compose command"
        assert live.client.handles == [], "nothing was subscribed"
        assert not state.records(epoch.epoch_id, {RuntimeEventType.RUNTIME_START})
    assert "EPOCH_PINNED" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------- #
# Task 2, Test 2: a bar recorded before the stop is never recorded or evaluated twice.
# ---------------------------------------------------------------------------------------------- #


def test_a_bar_recorded_before_the_stop_is_not_recorded_or_evaluated_again_after_a_restart(
    live: Live, evaluations: list[Candle], monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = DowntimeRig(live, "history-only", monkeypatch)
    rig.seed()  # the processed record of bar 245
    (original,) = live.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    seen_by_pipeline: list[datetime] = []

    class Spy:
        def handle(self, bars: Any, *, now_utc: datetime) -> PipelineResult:
            batch = list(bars)
            seen_by_pipeline.extend(b.close_time_utc for b in batch)
            return rig.pipeline.handle(batch, now_utc=now_utc)

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        rig.clock.now = rig.last_processed.close_time_utc + timedelta(seconds=1)
        rig.emit(h, rig.last_processed)  # re-delivered by the feed after the restart
        await asyncio.sleep(0.3)

    rig.public.rows = {}  # an exchange that returns nothing: only the restored state remains
    assert live.start(script, clock=rig.clock, public=rig.public, pipeline=Spy()) == 0

    assert live.records(RuntimeEventType.PAPER_BAR_PROCESSED) == [original], (
        "no second record and no conflict"
    )
    assert evaluations == []
    assert rig.last_processed.close_time_utc not in seen_by_pipeline, (
        "the supervisor cursor, seeded from the restored close, drops it before the pipeline"
    )


def test_the_pipeline_treats_the_restored_last_close_as_already_processed() -> None:
    case = _case_input()
    setup = exchange_candles(_setup_bars(case), HOUR)
    parameter_set = _parameter_set(case)
    state = InMemoryRuntimeState()
    pipeline = BarPipeline(
        epoch=StreamEpoch(
            epoch_id="a" * 64,
            strategy_id=case["strategy_id"],
            parameter_set_id=case["parameter_set_id"],
            parameter_set_hash=parameter_set.parameter_set_hash,
            opened_at_utc=setup[0].close_time_utc,
        ),
        parameter_set=parameter_set,
        context_factory=lambda candle: _bar_context(case, candle.close_time_utc),
        buffers=BarBuffers(),
        state=state,
        sibling_4h_wait_seconds=30,
        fetch_4h_bar=lambda _symbol, _close: None,
    )
    processed = setup[10]
    pipeline.seed_processed({("BTCUSDT", "1h"): processed.close_time_utc})

    bar = TaggedBar(
        symbol=processed.symbol,
        interval=processed.interval,
        open_time_utc=processed.open_time_utc,
        close_time_utc=processed.close_time_utc,
        open=processed.open,
        high=processed.high,
        low=processed.low,
        close=processed.close,
        volume=processed.volume,
        source=SourceTag.LIVE_WS,
    )
    result = pipeline.handle([bar], now_utc=processed.close_time_utc + timedelta(seconds=1))

    assert result.duplicates == (bar,)
    assert result.recorded == () and result.evaluated == ()
    assert list(state.records("a" * 64)) == []


def test_the_supervisor_cursor_falls_back_to_the_restored_close_when_the_warm_up_is_empty(
    live: Live, supervisor_trace: SupervisorTrace
) -> None:
    public = WarmPublic(RESTART, rows={})  # the exchange returns no row at all
    run_restart(live, with_stop=True, public=public, emit_live=False)

    assert ("BTCUSDT", "1h", C) in supervisor_trace.seeded
    assert ("BTCUSDT", "4h", C) in supervisor_trace.seeded


# ---------------------------------------------------------------------------------------------- #
# Task 2, Test 3: exchange holes and repeated restarts leave exactly one record per close.
# ---------------------------------------------------------------------------------------------- #


def test_a_close_the_exchange_does_not_return_is_an_exchange_hole_not_a_planned_restart(
    live: Live,
) -> None:
    hole_open = DOWNTIME_CLOSES[1] + ONE_MS - HOUR
    public = WarmPublic(RESTART, omit_opens=[("BTCUSDT", "1h", hole_open)])
    run_restart(live, with_stop=True, public=public, emit_live=False)

    gaps = live.records(RuntimeEventType.PAPER_GAP)
    assert gap_triples(gaps) == sorted(
        [
            ("BTCUSDT", "1h", DOWNTIME_CLOSES[0].isoformat(), "PLANNED_RESTART"),
            ("BTCUSDT", "1h", DOWNTIME_CLOSES[1].isoformat(), "EXCHANGE_NO_CANDLE"),
            ("BTCUSDT", "1h", DOWNTIME_CLOSES[2].isoformat(), "PLANNED_RESTART"),
        ]
    )


def test_a_close_older_than_the_requested_window_keeps_the_restart_reason() -> None:
    module = restart_module()
    state = InMemoryRuntimeState()
    epoch_id = "e" * 64
    old_close = RESTART.replace(minute=0) - timedelta(hours=1300) - ONE_MS
    state.record(
        RuntimeRecord.bar_processed(
            epoch_id=epoch_id, symbol="BTCUSDT", interval="1h", close_time_utc=old_close
        )
    )
    restored = module.restore_runtime(state, epoch_id)
    warm = asyncio.run(module.warm_up(WarmPublic(RESTART), ("BTCUSDT",), ("1h",), RESTART))

    gaps = module.downtime_gaps(
        restored, now_utc=RESTART, symbols=("BTCUSDT",), intervals=("1h",), warm=warm
    )

    assert len(gaps) == 1300  # every close after the processed one, up to 18:59:59.999
    assert {g.reason.value for g in gaps} == {"CRASH"}, "never stopped, and the exchange has all"
    first_requested = RESTART.replace(minute=0) - timedelta(hours=1000) - ONE_MS
    older = [g for g in gaps if g.expected_close_utc < first_requested]
    assert len(older) == 300, "closes outside the requested window are not exchange holes"


def test_a_repeated_restart_never_rewrites_a_recorded_gap_with_another_reason() -> None:
    module = restart_module()
    state = InMemoryRuntimeState()
    epoch_id = "e" * 64
    for kind, at in (
        (RuntimeEventType.RUNTIME_START, START_AT),
        (RuntimeEventType.RUNTIME_STOP, STOP_AT),
    ):
        state.record(RuntimeRecord(event_type=kind, epoch_id=epoch_id, occurred_at_utc=at))
    state.record(
        RuntimeRecord.bar_processed(
            epoch_id=epoch_id, symbol="BTCUSDT", interval="1h", close_time_utc=C
        )
    )
    first = module.downtime_gaps(
        module.restore_runtime(state, epoch_id),
        now_utc=RESTART,
        symbols=("BTCUSDT",),
        intervals=("1h",),
    )
    # The first restart recorded only C + 1h as PLANNED_RESTART, then crashed.
    state.record(module.restart_gap_record(epoch_id, first[0]))
    state.record(
        RuntimeRecord(
            event_type=RuntimeEventType.RUNTIME_START,
            epoch_id=epoch_id,
            occurred_at_utc=RESTART,
        )
    )

    restored = module.restore_runtime(state, epoch_id)  # the previous run is a START: a crash
    gaps = module.downtime_gaps(
        restored,
        now_utc=RESTART + timedelta(minutes=1),
        symbols=("BTCUSDT",),
        intervals=("1h",),
    )

    assert [g.expected_close_utc for g in gaps] == list(DOWNTIME_CLOSES[1:])
    assert {g.reason.value for g in gaps} == {"CRASH"}
