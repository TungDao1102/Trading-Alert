"""Plan 16-57 Task 2: one PAPER_GAP per close across writers, and the start-up seam backfill.

B1-WR-05: the supervisor (`runtime._gap_record`, source SUPERVISOR) and the pipeline
(`BarPipeline._write_gap`, sources REST_BACKFILL, FETCHED_4H_SIBLING, NO_4H_SIBLING) key their
PAPER_GAP records on the same (epoch, symbol, interval, expected close) but carry different
payloads. A close reported by both was a `RuntimeRecordConflict` that ended the loop. The writers
now share one in-process set of written gap keys (seeded from the restored gaps and the restart
gaps); the first writer wins and the second write is skipped, while the bar still enters history.

B1-WR-01: the SDK fires `open` synchronously when a callback is registered on an already open
connection, which happens inside `PaperWsAdapter.connect`, before `PaperSupervisor._started` is
set, so the echo is ignored. A bar that closed between the warm-up snapshot and the first
subscription then never reached history and had no gap. One verification backfill now runs right
after `supervisor.start()`, under the recovery lock with live bars held.

No network is touched: the SDK client and the public adapter are fakes, the state is in memory.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import src.domain.registry as domain_registry
from src.core.types import Candle
from src.paper import pipeline as pipeline_module
from src.paper import restart as restart_module
from src.paper import runtime
from src.paper.bars import BarBuffers
from src.paper.freeze import StreamEpoch
from src.paper.pipeline import BarPipeline
from src.paper.runtime_state import GapLedger
from src.paper.vocabulary import RuntimeEventType, SourceTag, TaggedBar

from tests.paper_ws_fakes import FakeSdkWsClient
from tests.test_paper_decision_surface import _bar_context, _case_input
from tests.test_paper_runtime_admission import _Rig
from tests.test_paper_runtime_loop import (  # noqa: F401 - fixtures are used by name
    FixedClock,
    Live,
    _isolated_sdk_stream_map,
    never_called_factory,
    wait_until,
)
from tests.test_paper_runtime_pipeline import _parameter_set
from tests.test_paper_runtime_restart import REAL_REGISTRY_ROOT, WarmPublic
from tests.test_rationale import write_rationalized_set

ONE_MS = timedelta(milliseconds=1)
HOUR = timedelta(hours=1)
# The start: the warm-up snapshot. The newest closed 1h bar opened at 18:00, the 4h one at 12:00.
T0 = datetime(2026, 10, 10, 19, 5, tzinfo=UTC)
CLOSE_19 = datetime(2026, 10, 10, 19, 59, 59, 999000, tzinfo=UTC)  # a 1h and a 4h close
CLOSE_20 = datetime(2026, 10, 10, 20, 59, 59, 999000, tzinfo=UTC)
SIBLING_WAIT_SECONDS = 15  # the admission rig's sibling_4h_wait_seconds


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    """A pinned, admitted runtime state (the rig of the loop and restart tests)."""
    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    yield Live(rig)


class SeamPublic(WarmPublic):
    """The synthetic exchange of `WarmPublic` with a movable `now` and failing pairs."""

    def __init__(self, now: datetime) -> None:
        super().__init__(now)
        self.fail_pairs: set[tuple[str, str]] = set()

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        if (symbol, interval) in self.fail_pairs:
            # A non-transient error: the backfill does not retry it (no real wait in the test).
            raise ValueError(f"simulated klines failure for {symbol} {interval}")
        if start_ms is not None:
            # A backfill asks from the last close; the exchange answers from the next grid open.
            step_ms = (HOUR if interval == "1h" else 4 * HOUR) // ONE_MS
            start_ms = -(-start_ms // step_ms) * step_ms
        return await super().klines(symbol, interval, start_ms, end_ms, limit)


class EchoingClient(FakeSdkWsClient):
    """The fake SDK client, plus what binance_common does: `open` fires at registration.

    `on_connect` runs inside `create_connection`, i.e. after the REST warm-up snapshot and before
    the first subscription: the test moves the clock there to make a bar close in that seam.
    """

    def __init__(self, on_connect: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.on_connect = on_connect
        self.open_echoes = 0

    async def create_connection(self) -> None:
        await super().create_connection()
        if self.on_connect is not None:
            self.on_connect()

    def on_connection(
        self, event: str, callback: Callable[..., None], connection: Any = None
    ) -> None:
        already = callback in self.connection_callbacks[event]
        super().on_connection(event, callback, connection)
        if event == "open" and self.connections and not already:
            self.open_echoes += 1
            callback()


def case_pipeline(
    rig: Live,
    monkeypatch: pytest.MonkeyPatch,
    *,
    factory: Callable[[Candle], Any] | None = None,
    ledger: GapLedger | None = None,
) -> BarPipeline:
    """The real pipeline over the parity case's parameter set, on the rig's epoch id."""
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", REAL_REGISTRY_ROOT)
    case = _case_input()
    parameter_set = _parameter_set(case)
    epoch = rig.epoch
    return BarPipeline(
        epoch=StreamEpoch(
            epoch_id=epoch.epoch_id,
            strategy_id=case["strategy_id"],
            parameter_set_id=case["parameter_set_id"],
            parameter_set_hash=parameter_set.parameter_set_hash,
            opened_at_utc=epoch.opened_at_utc,
        ),
        parameter_set=parameter_set,
        context_factory=factory or (lambda candle: _bar_context(case, candle.close_time_utc)),
        buffers=BarBuffers(),
        state=rig.state,
        sibling_4h_wait_seconds=SIBLING_WAIT_SECONDS,
        fetch_4h_bar=lambda _symbol, _close: None,
        claim_gap=(ledger or GapLedger()).claim,
    )


def gaps_of(rig: Live, symbol: str, interval: str) -> list[dict[str, Any]]:
    return [
        json.loads(r.payload_json)
        for r in rig.records(RuntimeEventType.PAPER_GAP)
        if r.symbol == symbol and r.interval == interval
    ]


def logged(rig: Live) -> list[dict[str, Any]]:
    records = rig.records(RuntimeEventType.PAPER_HISTORY_BARS)
    payloads = sorted((json.loads(r.payload_json) for r in records), key=lambda p: p["history_seq"])
    return [entry for payload in payloads for entry in payload["entries"]]


def logged_source(rig: Live, symbol: str, interval: str, close: datetime) -> str | None:
    for entry in logged(rig):
        if (
            entry["symbol"] == symbol
            and entry["interval"] == interval
            and entry["close_time_utc"] == close.isoformat()
        ):
            return str(entry["source"])
    return None


def fire(rig: Live, event: str) -> None:
    for callback in list(rig.client.connection_callbacks[event]):
        callback()


@pytest.fixture
def evaluations(monkeypatch: pytest.MonkeyPatch) -> list[Candle]:
    seen: list[Candle] = []
    real = pipeline_module.evaluate_closed_bar

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "evaluate_closed_bar", spy)
    return seen


# ---------------------------------------------------------------------------------------------- #
# B1-WR-05 (a): a raising supervisor backfill, then a successful one for the same closes.
# ---------------------------------------------------------------------------------------------- #


def test_a_failed_then_successful_backfill_writes_one_gap_per_close_and_heals_history(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = GapLedger()
    clock = FixedClock(T0)
    public = SeamPublic(T0)
    pipeline = case_pipeline(live, monkeypatch, factory=never_called_factory, ledger=ledger)

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        clock.now = public.now = T0 + 2 * HOUR  # 19:59:59.999 and 20:59:59.999 are due
        public.fail_pairs.add(("BTCUSDT", "1h"))
        fire(h, "open")
        await wait_until(lambda: len(gaps_of(h, "BTCUSDT", "1h")) == 2)
        public.fail_pairs.clear()
        fire(h, "reconnect")
        await wait_until(lambda: logged_source(h, "BTCUSDT", "1h", CLOSE_20) is not None)

    code = live.start(script, clock=clock, public=public, pipeline=pipeline, gap_ledger=ledger)

    assert code == 0, "a second gap writer must not end the loop with RuntimeRecordConflict"
    gaps = gaps_of(live, "BTCUSDT", "1h")
    assert sorted(g["expected_close_utc"] for g in gaps) == [
        CLOSE_19.isoformat(),
        CLOSE_20.isoformat(),
    ]
    assert {g["source"] for g in gaps} == {"SUPERVISOR"}, "the first writer's record stays"
    # The supervisor cursor was not moved past the closes it reported: history healed.
    for close in (CLOSE_19, CLOSE_20):
        assert logged_source(live, "BTCUSDT", "1h", close) == "REST_BACKFILL"


# ---------------------------------------------------------------------------------------------- #
# B1-WR-05 (b): the pipeline reports a missing 4h sibling, a later reconnect backfills it.
# ---------------------------------------------------------------------------------------------- #


def test_a_missing_sibling_then_a_backfilled_4h_bar_keeps_the_pipelines_gap(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = GapLedger()
    clock = FixedClock(T0)
    public = SeamPublic(T0)
    pipeline = case_pipeline(live, monkeypatch, factory=never_called_factory, ledger=ledger)

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        clock.now = public.now = CLOSE_19 + ONE_MS + timedelta(seconds=30)  # past the deadline
        h.emit("BTCUSDT", "1h", open_time=CLOSE_19 + ONE_MS - HOUR)
        await wait_until(lambda: len(gaps_of(h, "BTCUSDT", "4h")) == 1)
        fire(h, "reconnect")
        await wait_until(lambda: logged_source(h, "BTCUSDT", "4h", CLOSE_19) is not None)

    code = live.start(script, clock=clock, public=public, pipeline=pipeline, gap_ledger=ledger)

    assert code == 0
    [gap] = gaps_of(live, "BTCUSDT", "4h")
    assert (gap["expected_close_utc"], gap["reason"], gap["source"]) == (
        CLOSE_19.isoformat(),
        "EXCHANGE_NO_CANDLE",
        "NO_4H_SIBLING",
    )
    assert logged_source(live, "BTCUSDT", "4h", CLOSE_19) == "REST_BACKFILL"


# ---------------------------------------------------------------------------------------------- #
# B1-WR-01: the start-up seam.
# ---------------------------------------------------------------------------------------------- #


def test_a_bar_closing_between_the_snapshot_and_the_subscription_reaches_history_with_a_gap(
    live: Live, monkeypatch: pytest.MonkeyPatch, evaluations: list[Candle]
) -> None:
    clock = FixedClock(T0)
    public = SeamPublic(T0)
    seam_now = CLOSE_19 + ONE_MS + timedelta(seconds=30)

    def slow_connect() -> None:
        clock.now = public.now = seam_now  # the 19:00 bar closes while the process connects

    live.client = EchoingClient(on_connect=slow_connect)
    live.clients = [live.client]
    ledger = GapLedger()
    pipeline = case_pipeline(live, monkeypatch, ledger=ledger)
    next_open = CLOSE_19 + ONE_MS

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        clock.now = CLOSE_20 + ONE_MS + timedelta(seconds=1)
        h.emit("BTCUSDT", "1h", open_time=next_open)
        await wait_until(
            lambda: any(
                r.symbol == "BTCUSDT" and r.interval == "1h" and r.occurred_at_utc == CLOSE_20
                for r in h.records(RuntimeEventType.PAPER_BAR_PROCESSED)
            )
        )

    code = live.start(script, clock=clock, public=public, pipeline=pipeline, gap_ledger=ledger)

    assert code == 0
    assert isinstance(live.client, EchoingClient) and live.client.open_echoes >= 1
    # The seam bars (the 1h and the 4h bar closing at 19:59:59.999) are history plus one gap.
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for interval in ("1h", "4h"):
            assert logged_source(live, symbol, interval, CLOSE_19) == "REST_BACKFILL"
            [gap] = gaps_of(live, symbol, interval)
            assert (gap["expected_close_utc"], gap["reason"]) == (
                CLOSE_19.isoformat(),
                "WS_RECONNECT_WINDOW",
            )
    # Never evaluated (Q-D), and the next live 1h bar is evaluated on a continuous history.
    assert [c.close_time_utc for c in evaluations] == [CLOSE_20]
    [heartbeat] = [
        r
        for r in live.records(RuntimeEventType.PAPER_BAR_PROCESSED)
        if r.symbol == "BTCUSDT" and r.interval == "1h"
    ]
    assert heartbeat.payload["reason_code"] != "HISTORY_DISCONTINUITY"
    # Nothing at or before the snapshot was reported as a gap (the fence keeps it history).
    assert all(
        datetime.fromisoformat(str(r.payload["expected_close_utc"])) > T0
        for r in live.records(RuntimeEventType.PAPER_GAP)
    )


def test_the_restart_docstring_names_the_post_start_verification_backfill() -> None:
    """Test 3: the docstring no longer claims the initial connection event closes the seam."""
    doc = restart_module.__doc__ or ""
    assert "that the initial connection event triggers" not in doc
    assert "post-start verification backfill" in " ".join(doc.split())


# ---------------------------------------------------------------------------------------------- #
# Unit level: the shared ledger and the pipeline's first-writer-wins.
# ---------------------------------------------------------------------------------------------- #


def test_the_gap_ledger_lets_the_first_writer_win_and_is_seeded_from_recorded_gaps() -> None:
    ledger = GapLedger()
    ledger.seed({("BTCUSDT", "1h", CLOSE_19)})
    assert not ledger.claim("BTCUSDT", "1h", CLOSE_19)
    assert ledger.claim("BTCUSDT", "1h", CLOSE_20)
    assert not ledger.claim("BTCUSDT", "1h", CLOSE_20)
    assert ledger.claim("BTCUSDT", "4h", CLOSE_20)
    assert ledger.claim("ETHUSDT", "1h", CLOSE_20)


def test_the_pipeline_skips_a_claimed_gap_but_still_takes_the_bar_into_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_paper_runtime_pipeline import EPOCH_ID, Fixture, _tagged

    fx = Fixture()
    ledger = GapLedger()
    pipeline = BarPipeline(
        epoch=StreamEpoch(
            epoch_id=EPOCH_ID,
            strategy_id=fx.case["strategy_id"],
            parameter_set_id=fx.case["parameter_set_id"],
            parameter_set_hash=fx.parameter_set.parameter_set_hash,
            opened_at_utc=fx.setup[-1].close_time_utc,
        ),
        parameter_set=fx.parameter_set,
        context_factory=never_called_factory,
        buffers=BarBuffers(),
        state=fx.state,
        sibling_4h_wait_seconds=30,
        fetch_4h_bar=lambda _s, _c: None,
        claim_gap=ledger.claim,
    )
    first, second = fx.setup[10], fx.setup[11]
    ledger.seed({(first.symbol, first.interval, first.close_time_utc)})
    bars: list[TaggedBar] = [
        _tagged(first, SourceTag.REST_BACKFILL),
        _tagged(second, SourceTag.REST_BACKFILL),
    ]
    result = pipeline.handle(bars, now_utc=fx.now)

    gaps = list(fx.state.records(EPOCH_ID, {RuntimeEventType.PAPER_GAP}))
    assert [str(g.payload["expected_close_utc"]) for g in gaps] == [
        second.close_time_utc.isoformat()
    ]
    assert [g.expected_close_utc for g in result.gaps] == [second.close_time_utc]
    history = [
        e
        for r in fx.state.records(EPOCH_ID, {RuntimeEventType.PAPER_HISTORY_BARS})
        for e in json.loads(r.payload_json)["entries"]
    ]
    assert [e["close_time_utc"] for e in history] == [
        first.close_time_utc.isoformat(),
        second.close_time_utc.isoformat(),
    ]
    # Replaying the same batch is a no-op: duplicates, no record.
    before = len(list(fx.state.records(EPOCH_ID)))
    again = pipeline.handle(bars, now_utc=fx.now)
    assert again.recorded == () and len(list(fx.state.records(EPOCH_ID))) == before


def test_the_loop_awaits_the_verification_backfill_right_after_the_supervisor_start() -> None:
    """The order in `_LiveLoop.run`: start, then the seam verification, then the consumer."""
    import inspect

    source = inspect.getsource(runtime._LiveLoop.run)
    start = source.index("await self._supervisor.start()")
    verify = source.index("await self._supervisor.verify_start_seam()")
    consumer = source.index("asyncio.create_task(self._consume())")
    assert start < verify < consumer
