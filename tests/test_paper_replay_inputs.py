"""Replay inputs and the acceptance log of the paper runtime (Phase 16, plan 16-51).

User decision 16-DEC-PARITY (option 1): the runtime records, per evaluated live 1h bar, what the
risk stage read (constraint snapshot, account state, open positions, daily loss, ttl) as a
`PAPER_REPLAY_INPUTS` record, and every bar it accepts into its history as a `PAPER_HISTORY_BARS`
record with its acceptance sequence. The trial evaluator rebuilds the parity replay from a bundle
holding those records and nothing else (D061 item D, L-04: tolerance zero).

Task 1 (tracer): pipeline -> state -> bundle -> replay -> parity on the Phase 7 parity fixture, the
record shapes, the heartbeat that stays byte-identical, the altered-input failures and the
observer change in `src/paper/surface.py`.

No network is touched. The database URL (Task 2's PostgreSQL test) reaches the suite only through
`TEST_DATABASE_URL` in the process environment.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from src.adapters.binance_public import SymbolFilters
from src.core.types import Candle
from src.db.models import JournalEventRow
from src.domain.canonical import canonical_bytes
from src.domain.registry import ParameterSet
from src.paper.bars import BarBuffers
from src.paper.evidence_bundle import (
    BundleError,
    EvidenceBundle,
    load_evidence_bundle,
    runtime_record_line,
)
from src.paper.exit_criteria import (
    ParityReplay,
    ParityUnavailable,
    ReplayRun,
    build_parity_replay,
    parity_criterion,
)
from src.paper.loop import BarContext
from src.paper.market_inputs import ConstraintProvider, make_context_factory
from src.paper.pipeline import BarPipeline, PipelineResult
from src.paper.replay_inputs import (
    HistoryEntry,
    context_digest,
    context_from_inputs,
    rebuild_context,
    window_digest,
)
from src.paper.restart import (
    apply_restart_fence,
    downtime_gaps,
    restart_gap_record,
    restore_runtime,
)
from src.paper.runtime_config import AccountConfig
from src.paper.runtime_state import (
    GapLedger,
    InMemoryRuntimeState,
    RuntimeRecord,
    RuntimeRecordConflict,
    runtime_event_id,
)
from src.paper.surface import decision_surface, surface_digest
from src.paper.vocabulary import RuntimeEventType, SourceTag, TaggedBar
from src.persistence.engine import make_sync_engine
from src.persistence.paper_runtime_state import PgRuntimeState
from src.persistence.uow import OperationalDatabase
from src.risk.portfolio import resolve_absolute_thresholds
from src.risk.types import OpenPosition

from tests.test_paper_decision_surface import (
    PASSING_BAR,
    _all_bars,
    _case_input,
    _per_bar_context,
)
from tests.test_paper_exit_evaluator import (
    QD_DECISION,
    RATIFIED_CONFIG,
    TrialFixture,
    _load_script,
    _workflow,
)
from tests.test_paper_runtime_loop import filters
from tests.test_paper_runtime_pipeline import EPOCH_ID, Fixture, _epoch, _tagged

SYMBOL = "BTCUSDT"
# surface_digest of decision_surface over the Phase 7 parity fixture, measured before plan 16-51.
PHASE7_SURFACE_DIGEST = "74ad1cc1efb6355113011e1d0b0b732b7d078550bb758aa6708e979d352e792a"
ONE_DAY = 86_400


# --------------------------------------------------------------------------- #
# A production-shaped runtime around the parity fixture.
# --------------------------------------------------------------------------- #


class RiskDouble:
    """The in-test risk-inputs port: fixed positions and daily loss, never a default in src."""

    def __init__(
        self,
        positions: Sequence[OpenPosition] = (),
        daily_loss: Decimal | None = Decimal("0"),
        *,
        equity: Decimal | None = None,
        threshold_equity: Decimal | None = None,
    ) -> None:
        self.positions = tuple(positions)
        self.daily_loss = daily_loss
        self.equity = equity
        self.threshold_equity = threshold_equity
        # `World` attaches the parameter set and the fixture equity once it has loaded them.
        self.params: Mapping[str, Any] | None = None
        self.fixture_equity: Decimal | None = None

    def equity_and_thresholds(self, at_utc: datetime) -> tuple[Decimal, dict[str, Any]]:
        """The sizing equity and the absolute thresholds (the ledger's view at the close)."""
        assert self.params is not None and self.fixture_equity is not None
        equity = self.fixture_equity if self.equity is None else self.equity
        base = equity if self.threshold_equity is None else self.threshold_equity
        return equity, resolve_absolute_thresholds(parameter_set=self.params, equity=base)

    def open_positions(self, at_utc: datetime) -> Sequence[OpenPosition]:
        return self.positions

    def daily_loss_quote(self, at_utc: datetime) -> Decimal | None:
        return self.daily_loss


class ExchangeDouble:
    """A public adapter whose exchangeInfo holds the fixture's constraint row."""

    def __init__(self, case: Mapping[str, Any]) -> None:
        row = case["constraint_history"][0]
        self._rows = [
            dataclasses.replace(
                filters(SYMBOL),
                price_tick_size=Decimal(row["price_tick_size"]),
                quantity_step_size=Decimal(row["quantity_step_size"]),
                min_quantity=Decimal(row["min_quantity"]),
                min_notional=Decimal(row["min_notional"]),
            )
        ]

    async def exchange_info(self, symbols: Any = None) -> list[SymbolFilters]:
        return list(self._rows)

    async def klines(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def server_time(self) -> datetime:
        raise AssertionError("not used")


class RecordingState(InMemoryRuntimeState):
    """The in-memory port that remembers the order of the writes."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[RuntimeEventType] = []

    def record(self, record: RuntimeRecord) -> None:
        super().record(record)
        self.writes.append(record.event_type)


class SessionTrial(TrialFixture):
    """The exporter's bundle of a session: it pins the registry set the session ran with."""

    parameter_set_id: str = "baseline-v6"

    def pinned_row(self) -> dict[str, Any]:
        return {**super().pinned_row(), "parameter_set_id": self.parameter_set_id}


class World:
    """Real pipeline, real context factory, in-memory state, bundle writer and replay."""

    def __init__(
        self, *, risk: RiskDouble | None = None, state: InMemoryRuntimeState | None = None
    ) -> None:
        self.fx = Fixture()  # the data only: its own pipeline is not used
        self.case = self.fx.case
        self.parameter_set: ParameterSet = self.fx.parameter_set
        self.risk = risk or RiskDouble()
        self.risk.params = self.parameter_set.params
        self.risk.fixture_equity = Decimal(self.case["account_state"]["equity"])
        self.state = state or InMemoryRuntimeState()
        self.started_at = self.fx.now - timedelta(minutes=1)
        observed = self.fx.setup[0].open_time_utc
        provider = ConstraintProvider(
            public=ExchangeDouble(self.case), symbols=[SYMBOL], clock=lambda: observed
        )
        asyncio.run(provider.refresh())
        self.factory_calls: list[datetime] = []
        inner = make_context_factory(
            parameter_set=self.parameter_set,
            constraints=provider,
            risk_inputs=self.risk,
            account=AccountConfig(
                initial_equity=Decimal(self.case["account_state"]["equity"]),
                risk_rate=Decimal(self.case["account_state"]["risk_rate"]),
            ),
            ttl_seconds=30 * ONE_DAY,
        )

        def factory(candle: Candle) -> BarContext:
            self.factory_calls.append(candle.close_time_utc)
            return inner(candle)

        self.factory = factory
        # The sibling fetch of the pipeline; a test sets it before the bar that needs it.
        self.fetch_impl: Callable[[str, datetime], TaggedBar | None] | None = None
        self.pipeline = self.new_pipeline()

    def new_pipeline(self, buffers: BarBuffers | None = None) -> BarPipeline:
        return BarPipeline(
            epoch=_epoch(self.case, self.parameter_set, self.fx.setup[-1]),
            parameter_set=self.parameter_set,
            context_factory=self.factory,
            buffers=buffers or BarBuffers(),
            state=self.state,
            sibling_4h_wait_seconds=30,
            fetch_4h_bar=self._fetch,
            claim_gap=GapLedger().claim,
        )

    def _fetch(self, symbol: str, close: datetime) -> TaggedBar | None:
        return None if self.fetch_impl is None else self.fetch_impl(symbol, close)

    def start(self, at: datetime | None = None) -> None:
        self.state.record(
            RuntimeRecord(
                event_type=RuntimeEventType.RUNTIME_START,
                epoch_id=EPOCH_ID,
                occurred_at_utc=at or self.started_at,
            )
        )

    def run_tracer_session(self) -> PipelineResult:
        self.start()
        self.pipeline.handle(self.fx.warmup, now_utc=self.fx.now)
        return self.pipeline.handle([self.fx.live()], now_utc=self.fx.now)

    def records(self, *types: RuntimeEventType) -> list[RuntimeRecord]:
        return list(self.state.records(EPOCH_ID, types or None))

    def rows(self) -> list[dict[str, Any]]:
        return [runtime_row(r) for r in self.records()]

    def bundle(
        self,
        directory: Path,
        rows: list[dict[str, Any]] | None = None,
        *,
        parameter_hash: str | None = None,
    ) -> EvidenceBundle:
        trial = SessionTrial(
            epoch_id=EPOCH_ID,
            pin=self.started_at,
            window_end=self.started_at + timedelta(days=14),
            parameter_hash=parameter_hash or self.parameter_set.parameter_set_hash,
            records=self.rows() if rows is None else rows,
        )
        trial.parameter_set_id = self.case["parameter_set_id"]
        return load_evidence_bundle(trial.write(directory))

    def parity(self, bundle: EvidenceBundle) -> Any:
        replay = build_parity_replay(
            bundle.records,
            parameter_set=self.parameter_set,
            pinned_parameter_set_hash=bundle.pinned.parameter_set_hash,
        )
        assert isinstance(replay, ParityReplay)
        return parity_criterion(bundle.records, replay)


def runtime_row(record: RuntimeRecord) -> dict[str, Any]:
    """The 16-25 line shape of one runtime record."""
    return {
        "event_type": record.event_type.value,
        "epoch_id": record.epoch_id,
        "occurred_at_utc": record.occurred_at_utc.isoformat(),
        "symbol": record.symbol,
        "interval": record.interval,
        "payload": json.loads(record.payload_json),
    }


def rows_of(rows: Sequence[dict[str, Any]], event_type: RuntimeEventType) -> list[dict[str, Any]]:
    return [row for row in rows if row["event_type"] == event_type.value]


def _walk_for_floats(value: object) -> None:
    assert not isinstance(value, float), "a float reached a recorded payload"
    if isinstance(value, Mapping):
        for item in value.values():
            _walk_for_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk_for_floats(item)


def with_digest(payload: dict[str, Any], parameter_set: ParameterSet) -> dict[str, Any]:
    """Recompute the context digest of an edited payload so the record stays self-consistent."""
    context = rebuild_context(payload, symbol=SYMBOL, parameter_set=parameter_set)
    return {**payload, "context_digest": context_digest(context)}


# --------------------------------------------------------------------------- #
# Task 1 - tracer.
# --------------------------------------------------------------------------- #


def test_tracer_one_evaluated_bar_is_recorded_exported_replayed_and_passes_parity(
    tmp_path: Path,
) -> None:
    """Test 1: pipeline -> state -> bundle -> build_parity_replay -> parity PASSES."""
    world = World()
    result = world.run_tracer_session()
    assert [o.stage for o in result.evaluated] == ["risk_passed"]

    bundle = world.bundle(tmp_path / "bundle")
    replay = build_parity_replay(
        bundle.records,
        parameter_set=world.parameter_set,
        pinned_parameter_set_hash=bundle.pinned.parameter_set_hash,
    )
    assert isinstance(replay, ParityReplay)
    criterion = parity_criterion(bundle.records, replay)
    assert criterion.passed, criterion.evidence
    text = "\n".join(criterion.evidence)
    assert "1 recorded surface record(s) compared" in text
    assert "risk_passed=1" in text


def test_the_replay_inputs_record_carries_what_the_risk_stage_read() -> None:
    """Test 2: schema, keys, Decimal text, canonical bytes, no float, keyed like the heartbeat."""
    world = World(
        risk=RiskDouble(
            positions=(
                OpenPosition(
                    symbol=SYMBOL,
                    position_side="LONG",
                    open_risk=Decimal("1.50"),
                    daily_pnl_contribution=Decimal("0"),
                ),
            ),
            daily_loss=Decimal("12.5"),
        )
    )
    world.run_tracer_session()
    [inputs] = world.records(RuntimeEventType.PAPER_REPLAY_INPUTS)
    [heartbeat] = world.records(RuntimeEventType.PAPER_BAR_PROCESSED)

    assert (inputs.epoch_id, inputs.symbol, inputs.interval, inputs.occurred_at_utc) == (
        heartbeat.epoch_id,
        heartbeat.symbol,
        heartbeat.interval,
        heartbeat.occurred_at_utc,
    )
    assert runtime_event_id(inputs) != runtime_event_id(heartbeat)

    payload = json.loads(inputs.payload_json)
    assert payload["schema"] == "paper-replay-inputs/1"
    assert set(payload) >= {
        "schema",
        "strategy_version",
        "parameter_set_hash",
        "cost_model_hash",
        "constraint_snapshot",
        "account_state",
        "open_positions",
        "daily_loss_quote",
        "ttl_seconds",
        "window_accept_seq",
        "context_digest",
        "setup_window_digest",
        "context_window_digest",
    }
    assert payload["parameter_set_hash"] == world.parameter_set.parameter_set_hash
    assert payload["account_state"] == {"equity": "10000.00", "risk_rate": "0.005"}
    assert payload["constraint_snapshot"]["min_notional"] == "50"
    assert payload["constraint_snapshot"]["symbol"] == SYMBOL
    assert payload["open_positions"] == [
        {
            "symbol": SYMBOL,
            "position_side": "LONG",
            "open_risk": "1.50",
            "daily_pnl_contribution": "0",
        }
    ]
    assert payload["daily_loss_quote"] == "12.5"
    assert payload["ttl_seconds"] == 30 * ONE_DAY
    assert inputs.payload_json == canonical_bytes(payload).decode("ascii")
    _walk_for_floats(payload)
    for key in ("context_digest", "setup_window_digest", "context_window_digest"):
        assert len(payload[key]) == 64


def test_every_accepted_bar_is_logged_in_acceptance_order_before_its_inputs() -> None:
    """Test 3: the history log, the cut point and the write order history, inputs, heartbeat."""
    state = RecordingState()
    world = World(state=state)
    world.start()
    world.pipeline.handle(world.fx.warmup, now_utc=world.fx.now)
    state.writes.clear()
    world.pipeline.handle([world.fx.live()], now_utc=world.fx.now)

    assert state.writes == [
        RuntimeEventType.PAPER_HISTORY_BARS,
        RuntimeEventType.PAPER_REPLAY_INPUTS,
        RuntimeEventType.PAPER_BAR_PROCESSED,
    ]
    logged = [
        json.loads(r.payload_json) for r in world.records(RuntimeEventType.PAPER_HISTORY_BARS)
    ]
    assert [p["history_seq"] for p in logged] == [0, 1]
    entries = [e for p in logged for e in p["entries"]]
    assert [e["accept_seq"] for e in entries] == list(range(len(world.fx.warmup) + 1))
    assert {e["source"] for e in entries[:-1]} == {"REST_WARMUP"}
    assert entries[-1]["source"] == "LIVE_WS"
    assert entries[-1]["close_time_utc"] == world.fx.last_1h.close_time_utc.isoformat()
    [inputs] = world.records(RuntimeEventType.PAPER_REPLAY_INPUTS)
    assert json.loads(inputs.payload_json)["window_accept_seq"] == entries[-1]["accept_seq"]


def test_the_heartbeat_payload_is_unchanged_and_recorded_holds_only_heartbeats_and_gaps() -> None:
    """Test 4: PAPER_BAR_PROCESSED keeps its 16-24 shape; the new records ride in replay_records."""
    world = World()
    world.start()
    warm = world.pipeline.handle(world.fx.warmup, now_utc=world.fx.now)
    live = world.pipeline.handle([world.fx.live()], now_utc=world.fx.now)

    [heartbeat] = world.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert set(heartbeat.payload) == {
        "source",
        "tick_time_utc",
        "bar",
        "stage",
        "reason_code",
        "plan_hash",
        "surface",
    }
    assert live.recorded == (heartbeat,)
    assert [r.event_type for r in live.replay_records] == [
        RuntimeEventType.PAPER_HISTORY_BARS,
        RuntimeEventType.PAPER_REPLAY_INPUTS,
    ]
    assert warm.recorded == ()
    assert [r.event_type for r in warm.replay_records] == [RuntimeEventType.PAPER_HISTORY_BARS]


def test_an_altered_input_with_a_recomputed_digest_fails_parity_naming_the_bar_close(
    tmp_path: Path,
) -> None:
    """Test 5: a self-consistent record whose inputs change the verdict is a parity difference."""
    world = World()
    world.run_tracer_session()
    rows = world.rows()
    [row] = rows_of(rows, RuntimeEventType.PAPER_REPLAY_INPUTS)
    payload = json.loads(json.dumps(row["payload"]))
    payload["constraint_snapshot"]["min_notional"] = "1000000"
    row["payload"] = with_digest(payload, world.parameter_set)

    criterion = world.parity(world.bundle(tmp_path / "consistent", rows))
    assert not criterion.passed
    text = "\n".join(criterion.evidence)
    assert world.fx.last_1h.close_time_utc.isoformat() in text
    assert "differs in" in text


def test_an_altered_input_without_a_recomputed_digest_fails_parity_naming_context_digest(
    tmp_path: Path,
) -> None:
    """Test 6: the same change without the digest is refused as inconsistent."""
    world = World()
    world.run_tracer_session()
    rows = world.rows()
    [row] = rows_of(rows, RuntimeEventType.PAPER_REPLAY_INPUTS)
    row["payload"]["constraint_snapshot"]["min_notional"] = "1000000"

    criterion = world.parity(world.bundle(tmp_path / "inconsistent", rows))
    assert not criterion.passed
    text = "\n".join(criterion.evidence)
    assert world.fx.last_1h.close_time_utc.isoformat() in text
    assert "context_digest" in text


def test_context_from_inputs_rebuilds_the_live_context_exactly() -> None:
    """The rebuilt context has the digest the live context had (the recorded digest verifies)."""
    world = World()
    world.run_tracer_session()
    [inputs] = world.records(RuntimeEventType.PAPER_REPLAY_INPUTS)
    context = context_from_inputs(
        json.loads(inputs.payload_json), symbol=SYMBOL, parameter_set=world.parameter_set
    )
    assert context_digest(context) == json.loads(inputs.payload_json)["context_digest"]
    assert context.ttl == timedelta(seconds=30 * ONE_DAY)


def test_decision_surface_is_unchanged_and_the_context_is_resolved_after_the_gates() -> None:
    """Test 7: same records and digest as before plan 16-51; a gated bar never builds a context."""
    case = _case_input()
    assert (
        surface_digest(decision_surface(_all_bars(case), context=_per_bar_context(case)))
        == PHASE7_SURFACE_DIGEST
    )

    calls: list[datetime] = []
    per_bar: Callable[[Candle], BarContext] = _per_bar_context(case)

    def counting(candle: Candle) -> BarContext:
        calls.append(candle.close_time_utc)
        return per_bar(candle)

    records = decision_surface(_all_bars(case), context=counting)
    stages = [r.stage for r in records if r.interval == "1h"]
    # 200 bars stopped by the warm-up gate build no context; the 50 others build exactly one.
    assert stages.count("feed_gate") == 200
    assert len(calls) == 50
    assert len(set(calls)) == 50
    assert _all_bars(case)[PASSING_BAR].close_time_utc in calls
    assert surface_digest(records) == PHASE7_SURFACE_DIGEST


# =========================================================================== #
# Task 2 - expansion: acceptance order, runs, failure modes, crash, writer, command line, PG.
# =========================================================================== #


def live(candle: Candle) -> TaggedBar:
    return _tagged(candle, SourceTag.LIVE_WS)


def warm_bars(
    fx: Fixture,
    *,
    n_1h: int,
    skip: frozenset[int] | set[int] = frozenset(),
    n_4h: int | None = None,
) -> list[TaggedBar]:
    """REST warm-up of the first `n_1h` 1h bars (minus `skip`) and the first `n_4h` 4h bars."""
    count_4h = len(fx.context) if n_4h is None else n_4h
    return [
        *(
            _tagged(c, SourceTag.REST_WARMUP)
            for i, c in enumerate(fx.setup[:n_1h])
            if i not in skip
        ),
        *(_tagged(c, SourceTag.REST_WARMUP) for c in fx.context[:count_4h]),
    ]


def two_seconds_after(candle: Candle) -> datetime:
    return candle.close_time_utc + timedelta(seconds=2)


def history_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows_of(rows, RuntimeEventType.PAPER_HISTORY_BARS),
        key=lambda row: row["payload"]["history_seq"],
    )


def logged_entries(world: World) -> list[dict[str, Any]]:
    records = world.records(RuntimeEventType.PAPER_HISTORY_BARS)
    payloads = sorted((json.loads(r.payload_json) for r in records), key=lambda p: p["history_seq"])
    return [entry for payload in payloads for entry in payload["entries"]]


# ---- Test 1: acceptance order ---------------------------------------------------------------- #


def test_the_replay_follows_acceptance_order_and_a_close_order_replay_fails(
    tmp_path: Path,
) -> None:
    """Test 1: a bar backfilled after L is absent from L window and present in M window."""
    world = World()
    fx = world.fx
    backfilled, last, final = fx.setup[20], fx.setup[248], fx.setup[249]
    world.start(fx.now - timedelta(hours=2))
    world.pipeline.handle(warm_bars(fx, n_1h=248, skip={20}), now_utc=fx.now)
    first = world.pipeline.handle([live(last)], now_utc=two_seconds_after(last))
    world.pipeline.handle(
        [_tagged(backfilled, SourceTag.REST_BACKFILL)],
        now_utc=last.close_time_utc + timedelta(minutes=10),
    )
    second = world.pipeline.handle([live(final)], now_utc=fx.now)
    assert len(first.evaluated) == 1 and len(second.evaluated) == 1

    inputs = {
        r.occurred_at_utc: json.loads(r.payload_json)
        for r in world.records(RuntimeEventType.PAPER_REPLAY_INPUTS)
    }
    without = [c for i, c in enumerate(fx.setup[:249]) if i != 20]
    assert inputs[last.close_time_utc]["setup_window_digest"] == window_digest(without)
    assert inputs[final.close_time_utc]["setup_window_digest"] == window_digest(fx.setup[:250])

    bundle = world.bundle(tmp_path / "bundle")
    criterion = world.parity(bundle)
    assert criterion.passed, criterion.evidence

    # Negative control: the 16-25 single pass, every logged bar as history in close order.
    replay = build_parity_replay(
        bundle.records,
        parameter_set=world.parameter_set,
        pinned_parameter_set_hash=bundle.pinned.parameter_set_hash,
    )
    assert isinstance(replay, ParityReplay)
    close_order = ParityReplay(
        context=world.factory, history_bars=tuple(e.candle for e in replay.runs[0].log)
    )
    control = parity_criterion(bundle.records, close_order)
    assert not control.passed
    assert last.close_time_utc.isoformat() in "\n".join(control.evidence)


# ---- Test 2: fetched sibling and fenced bar -------------------------------------------------- #


def test_a_fetched_sibling_and_a_fenced_bar_are_logged_and_replayed_as_live(
    tmp_path: Path,
) -> None:
    """Test 2: both are in the log and inside the replayed windows exactly as live."""
    world = World()
    fx = world.fx
    final = fx.setup[249]
    sibling = fx.context[-1]
    world.fetch_impl = lambda symbol, close: _tagged(sibling, SourceTag.REST_BACKFILL)
    world.start(fx.now - timedelta(hours=2))
    fence = fx.now
    world.pipeline.handle(
        warm_bars(fx, n_1h=249, skip={100}, n_4h=len(fx.context) - 1), now_utc=fence
    )
    fenced = apply_restart_fence(_tagged(fx.setup[100], SourceTag.REST_BACKFILL), fence)
    assert fenced.source is SourceTag.REST_WARMUP
    world.pipeline.handle([fenced], now_utc=fence)
    result = world.pipeline.handle(
        [live(final)], now_utc=final.close_time_utc + timedelta(seconds=30)
    )
    assert len(result.evaluated) == 1

    entries = logged_entries(world)
    assert [e["source"] for e in entries[-2:]] == ["LIVE_WS", "REST_BACKFILL"]
    assert entries[-1]["fetched_for_close_utc"] == final.close_time_utc.isoformat()
    assert entries[-1]["interval"] == "4h"
    opened = fx.setup[100].open_time_utc.isoformat()
    [fenced_entry] = [e for e in entries if e["open_time_utc"] == opened]
    assert fenced_entry["source"] == "REST_WARMUP"
    [inputs] = world.records(RuntimeEventType.PAPER_REPLAY_INPUTS)
    assert json.loads(inputs.payload_json)["window_accept_seq"] == entries[-1]["accept_seq"]

    criterion = world.parity(world.bundle(tmp_path / "bundle"))
    assert criterion.passed, criterion.evidence


# ---- Tests 3 and 6: two runs and the crash between the two writes ----------------------------- #


class CrashingState(InMemoryRuntimeState):
    """A state port whose heartbeat write for one close fails after the inputs were stored."""

    def __init__(self) -> None:
        super().__init__()
        self.crash_close: datetime | None = None

    def record(self, record: RuntimeRecord) -> None:
        if (
            self.crash_close is not None
            and record.event_type is RuntimeEventType.PAPER_BAR_PROCESSED
            and record.occurred_at_utc == self.crash_close
        ):
            raise OSError("simulated crash between the replay-inputs record and its heartbeat")
        super().record(record)


@dataclasses.dataclass
class Restart:
    """What `drive_two_runs` produced besides the records."""

    k: Candle
    last: Candle
    final: Candle
    gaps: tuple[Any, ...]
    second_evaluated: tuple[Candle, ...]


def drive_two_runs(
    world: World, *, run1_skip: frozenset[int] = frozenset(), crash_on_last: bool = False
) -> Restart:
    """Run 1 evaluates K (and L, or crashes on its heartbeat); run 2 restarts and evaluates M."""
    fx = world.fx
    k, last, final = fx.setup[247], fx.setup[248], fx.setup[249]
    state = world.state
    world.start(k.close_time_utc - timedelta(hours=2))
    world.pipeline.handle(
        warm_bars(fx, n_1h=247, skip=run1_skip, n_4h=len(fx.context) - 1),
        now_utc=fx.setup[246].close_time_utc + timedelta(seconds=1),
    )
    world.pipeline.handle([live(k)], now_utc=two_seconds_after(k))
    if crash_on_last:
        assert isinstance(state, CrashingState)
        state.crash_close = last.close_time_utc
        with pytest.raises(OSError):
            world.pipeline.handle([live(last)], now_utc=two_seconds_after(last))
        state.crash_close = None
    else:
        world.pipeline.handle([live(last)], now_utc=two_seconds_after(last))

    started = last.close_time_utc + timedelta(minutes=10)
    snapshot = last.close_time_utc + timedelta(minutes=20)
    world.start(started)
    restored = restore_runtime(state, EPOCH_ID, current_start_utc=started)
    gaps = downtime_gaps(restored, now_utc=snapshot, symbols=[SYMBOL], intervals=["1h", "4h"])
    for gap in gaps:
        state.record(restart_gap_record(EPOCH_ID, gap))
    second = world.new_pipeline()
    warm = [
        apply_restart_fence(bar, snapshot)
        for bar in warm_bars(fx, n_1h=249, n_4h=len(fx.context) - 1)
    ]
    second.handle(warm, now_utc=snapshot)
    second.seed_processed(restored.last_closes)
    result = second.handle([live(fx.context[-1]), live(final)], now_utc=two_seconds_after(final))
    return Restart(k, last, final, gaps, tuple(o.closed_candle for o in result.evaluated))


def test_each_run_is_replayed_from_its_own_log_and_one_merged_log_fails(tmp_path: Path) -> None:
    """Test 3: run 1 lacks a bar run 2 holds; per-run replay passes, a merged log does not."""
    world = World()
    restart = drive_two_runs(world, run1_skip=frozenset({20}))
    assert restart.second_evaluated == (restart.final,)

    bundle = world.bundle(tmp_path / "bundle")
    criterion = world.parity(bundle)
    assert criterion.passed, criterion.evidence
    assert "2 run(s)" in "\n".join(criterion.evidence)

    replay = build_parity_replay(
        bundle.records,
        parameter_set=world.parameter_set,
        pinned_parameter_set_hash=bundle.pinned.parameter_set_hash,
    )
    assert isinstance(replay, ParityReplay)
    by_bar: dict[Candle, HistoryEntry] = {}
    for run in replay.runs:
        for entry in run.log:
            by_bar.setdefault(entry.candle, entry)
    ordered = sorted(
        by_bar.values(),
        key=lambda e: (e.candle.close_time_utc, 0 if e.candle.interval == "4h" else 1),
    )
    merged = tuple(dataclasses.replace(e, accept_seq=i) for i, e in enumerate(ordered))
    one_run = ParityReplay(
        runs=(ReplayRun(replay.runs[0].started_at_utc, None, merged),),
        parameter_set=world.parameter_set,
    )
    control = parity_criterion(bundle.records, one_run)
    assert not control.passed
    assert restart.k.close_time_utc.isoformat() in "\n".join(control.evidence)


def test_a_crash_between_the_inputs_and_the_heartbeat_leaves_a_reported_orphan(
    tmp_path: Path,
) -> None:
    """Test 6: a CRASH gap, no second evaluation, no conflict, and the orphan is reported."""
    world = World(state=CrashingState())
    restart = drive_two_runs(world, crash_on_last=True)
    close = restart.last.close_time_utc

    # The fixture closes carry whole seconds; the exchange grid close is 999 ms later.
    grid_close = close + timedelta(milliseconds=999)
    assert [(g.expected_close_utc, g.reason.value) for g in restart.gaps] == [(grid_close, "CRASH")]
    assert restart.second_evaluated == (restart.final,)
    orphans = [
        r for r in world.records(RuntimeEventType.PAPER_REPLAY_INPUTS) if r.occurred_at_utc == close
    ]
    assert len(orphans) == 1
    heartbeats = world.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert close not in {r.occurred_at_utc for r in heartbeats if r.interval == "1h"}

    criterion = world.parity(world.bundle(tmp_path / "bundle"))
    assert criterion.passed, criterion.evidence
    text = "\n".join(criterion.evidence)
    assert "orphan replay-inputs record" in text and close.isoformat() in text


# ---- Test 4: gated bars ---------------------------------------------------------------------- #


def test_a_stale_bar_is_reproduced_and_a_pipeline_only_gate_is_not_compared(
    tmp_path: Path,
) -> None:
    """Test 4: no replay-inputs record for DATA_STALE or HISTORY_DISCONTINUITY; parity passes."""
    world = World()
    fx = world.fx
    stale_bar, final = fx.setup[248], fx.setup[249]
    world.start(fx.now - timedelta(hours=3))
    world.pipeline.handle(warm_bars(fx, n_1h=240), now_utc=fx.now)
    late = world.pipeline.handle(
        [live(stale_bar)], now_utc=stale_bar.close_time_utc + timedelta(hours=1)
    )
    hole = world.pipeline.handle([live(final)], now_utc=fx.now)
    assert late.evaluated == () and hole.evaluated == ()
    heartbeats = world.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    reasons = [r.payload["reason_code"] for r in heartbeats]
    assert sorted(reasons) == ["DATA_STALE", "HISTORY_DISCONTINUITY"]
    assert world.records(RuntimeEventType.PAPER_REPLAY_INPUTS) == []

    criterion = world.parity(world.bundle(tmp_path / "bundle"))
    assert criterion.passed, criterion.evidence
    text = "\n".join(criterion.evidence)
    assert "1 recorded surface record(s) compared" in text
    assert "pipeline-only gate records not compared: 1" in text


# ---- Test 5: failure modes ------------------------------------------------------------------- #


def _drop_inputs(rows: list[dict[str, Any]]) -> None:
    [row] = rows_of(rows, RuntimeEventType.PAPER_REPLAY_INPUTS)
    rows.remove(row)


def _drop_a_logged_entry(rows: list[dict[str, Any]]) -> None:
    history_rows(rows)[0]["payload"]["entries"].pop(10)


def _move_the_cut(rows: list[dict[str, Any]]) -> None:
    [row] = rows_of(rows, RuntimeEventType.PAPER_REPLAY_INPUTS)
    row["payload"]["window_accept_seq"] -= 1


def _drop_the_live_entry(rows: list[dict[str, Any]]) -> None:
    history_rows(rows)[-1]["payload"]["entries"] = []


@pytest.mark.parametrize(
    ("alter", "needle"),
    [
        (_drop_inputs, "no recorded replay inputs"),
        (_drop_a_logged_entry, "not contiguous"),
        (_move_the_cut, "setup_window_digest"),
        (_drop_the_live_entry, "acceptance log"),
    ],
    ids=["missing-inputs", "log-gap", "moved-cut", "bar-not-in-log"],
)
def test_every_way_the_recording_can_be_altered_fails_parity_naming_the_bar_close(
    tmp_path: Path, alter: Callable[[list[dict[str, Any]]], None], needle: str
) -> None:
    """Test 5."""
    world = World()
    world.run_tracer_session()
    rows = world.rows()
    alter(rows)
    criterion = world.parity(world.bundle(tmp_path / "altered", rows))
    assert not criterion.passed
    text = "\n".join(criterion.evidence)
    assert world.fx.last_1h.close_time_utc.isoformat() in text
    assert needle in text


# ---- Test 7: positions, daily loss, float ---------------------------------------------------- #


def test_open_positions_and_the_daily_loss_are_recorded_in_provider_order_and_replayed(
    tmp_path: Path,
) -> None:
    """Test 7."""
    positions = (
        OpenPosition(
            symbol="ETHUSDT",
            position_side="SHORT",
            open_risk=Decimal("2.5"),
            daily_pnl_contribution=Decimal("-1.25"),
        ),
        OpenPosition(
            symbol=SYMBOL,
            position_side="LONG",
            open_risk=Decimal("1.5"),
            daily_pnl_contribution=Decimal("0"),
        ),
    )
    world = World(risk=RiskDouble(positions, daily_loss=Decimal("12.5")))
    world.run_tracer_session()
    [inputs] = world.records(RuntimeEventType.PAPER_REPLAY_INPUTS)
    payload = json.loads(inputs.payload_json)
    assert [p["symbol"] for p in payload["open_positions"]] == ["ETHUSDT", SYMBOL]
    assert payload["daily_loss_quote"] == "12.5"
    criterion = world.parity(world.bundle(tmp_path / "bundle"))
    assert criterion.passed, criterion.evidence


def test_a_float_in_a_recorded_payload_is_refused_by_the_bundle_loader(tmp_path: Path) -> None:
    world = World()
    world.run_tracer_session()
    rows = world.rows()
    [row] = rows_of(rows, RuntimeEventType.PAPER_REPLAY_INPUTS)
    row["payload"]["ttl_seconds"] = 1.5
    with pytest.raises(BundleError, match="runtime_records.jsonl"):
        world.bundle(tmp_path / "float", rows)


# ---- Test 8: the one line writer ------------------------------------------------------------- #


def _sample(event_type: RuntimeEventType) -> RuntimeRecord:
    at = datetime(2026, 10, 11, 9, 0, 0, 500000, tzinfo=UTC)
    keyed = event_type in (
        RuntimeEventType.PAPER_BAR_PROCESSED,
        RuntimeEventType.PAPER_REPLAY_INPUTS,
        RuntimeEventType.PAPER_GAP,
    )
    payloads: dict[RuntimeEventType, dict[str, Any]] = {
        RuntimeEventType.PAPER_GAP: {"expected_close_utc": at, "reason": "CRASH"},
        RuntimeEventType.PAPER_TICK_STATS: {"batch_seq": 3, "dropped_by_reason": {}},
        RuntimeEventType.PAPER_HISTORY_BARS: {"history_seq": 2, "entries": [{"accept_seq": 0}]},
        RuntimeEventType.PAPER_REPLAY_INPUTS: {
            "schema": "paper-replay-inputs/1",
            "ttl_seconds": 5,
            "amount": Decimal("1.50"),
        },
    }
    return RuntimeRecord(
        event_type=event_type,
        epoch_id=EPOCH_ID,
        occurred_at_utc=at,
        symbol=SYMBOL if keyed else None,
        interval="1h" if keyed else None,
        payload=payloads.get(event_type, {"note": "café"}),
    )


def test_runtime_record_line_round_trips_every_event_type_through_the_bundle(
    tmp_path: Path,
) -> None:
    """Test 8."""
    records = [_sample(event_type) for event_type in RuntimeEventType]
    assert {RuntimeEventType.PAPER_REPLAY_INPUTS, RuntimeEventType.PAPER_HISTORY_BARS} <= {
        r.event_type for r in records
    }
    lines = [runtime_record_line(r) for r in records]
    keys = {"event_type", "epoch_id", "occurred_at_utc", "symbol", "interval", "payload"}
    for record, line in zip(records, lines, strict=True):
        row = json.loads(line)
        assert set(row) == keys
        assert line == json.dumps(row, sort_keys=True, separators=(",", ":"))
        assert row["event_type"] == record.event_type.value

    trial = SessionTrial(
        epoch_id=EPOCH_ID,
        pin=records[0].occurred_at_utc,
        window_end=records[0].occurred_at_utc + timedelta(days=14),
        parameter_hash="b" * 64,
        records=[json.loads(line) for line in lines],
    )
    loaded = load_evidence_bundle(trial.write(tmp_path / "bundle"))
    assert [runtime_event_id(r) for r in loaded.records] == [runtime_event_id(r) for r in records]
    assert [r.payload_json for r in loaded.records] == [r.payload_json for r in records]


# ---- Test 9: build_parity_replay and the command line ---------------------------------------- #


def test_a_bundle_without_replay_inputs_or_with_another_hash_is_not_evaluated(
    tmp_path: Path,
) -> None:
    world = World()
    world.run_tracer_session()
    bundle = world.bundle(tmp_path / "bundle")

    no_inputs = build_parity_replay(
        [r for r in bundle.records if r.event_type is RuntimeEventType.RUNTIME_START],
        parameter_set=world.parameter_set,
        pinned_parameter_set_hash=world.parameter_set.parameter_set_hash,
    )
    assert isinstance(no_inputs, ParityUnavailable)
    assert "no recorded replay inputs" in no_inputs.reason
    other = build_parity_replay(
        bundle.records, parameter_set=world.parameter_set, pinned_parameter_set_hash="f" * 64
    )
    assert isinstance(other, ParityUnavailable)
    assert "hash" in other.reason
    for unavailable in (no_inputs, other):
        result = parity_criterion(bundle.records, unavailable)
        assert not result.passed
        assert result.evidence[0].startswith("NOT EVALUATED: ")


def _cli(bundle_dir: Path, tmp_path: Path) -> list[str]:
    config = tmp_path / "paper-runtime.toml"
    config.write_text(RATIFIED_CONFIG, encoding="utf-8")
    return [
        "--bundle",
        str(bundle_dir),
        "--config",
        str(config),
        "--workflow",
        str(_workflow(tmp_path)),
        "--q-d-decision",
        str(QD_DECISION),
        "--out",
        str(tmp_path / "evaluation.txt"),
    ]


def test_the_command_line_builds_the_parity_replay_from_the_bundle_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 9: PASS with the pinned registry set, NOT EVALUATED and FAIL with another hash."""
    world = World()
    world.run_tracer_session()
    script = _load_script()

    good = world.bundle(tmp_path / "good")
    script.main(_cli(good.path, tmp_path))
    printed = capsys.readouterr().out
    assert "PASS  parity (tolerance zero)" in printed

    bad_dir = tmp_path / "bad"
    world.bundle(bad_dir, parameter_hash="f" * 64)
    script.main(_cli(bad_dir, tmp_path))
    printed = capsys.readouterr().out
    assert "FAIL  parity (tolerance zero)" in printed
    assert "NOT EVALUATED" in printed and "hash" in printed


# =========================================================================== #
# Plan 16-57 Task 1 (B1-CR-02): the acceptance log is durable before any record naming its bars.
# =========================================================================== #


class LogFirstState(InMemoryRuntimeState):
    """A state port that notes every heartbeat or gap whose bar no earlier history record holds."""

    def __init__(self) -> None:
        super().__init__()
        self.logged: set[tuple[str, str, datetime]] = set()
        self.violations: list[str] = []

    def record(self, record: RuntimeRecord) -> None:
        super().record(record)
        if record.event_type is RuntimeEventType.PAPER_HISTORY_BARS:
            for entry in json.loads(record.payload_json)["entries"]:
                close = datetime.fromisoformat(entry["close_time_utc"])
                self.logged.add((entry["symbol"], entry["interval"], close))
        elif record.event_type is RuntimeEventType.PAPER_BAR_PROCESSED:
            key = (str(record.symbol), str(record.interval), record.occurred_at_utc)
            if key not in self.logged:
                self.violations.append(f"heartbeat {key} before its history entry")
        elif record.event_type is RuntimeEventType.PAPER_GAP:
            close = datetime.fromisoformat(json.loads(record.payload_json)["expected_close_utc"])
            if not any(s == record.symbol and c == close for s, _i, c in self.logged):
                self.violations.append(f"gap {record.symbol} {close} before its history entry")


def _raising_world(state: InMemoryRuntimeState, fail_close: datetime) -> World:
    """A World whose context factory raises for one close (a crash inside the 1h path)."""
    world = World(state=state)
    inner = world.factory

    def factory(candle: Candle) -> BarContext:
        if candle.close_time_utc == fail_close:
            raise OSError("simulated crash in the 1h path after the 4h heartbeat")
        return inner(candle)

    world.factory = factory
    world.pipeline = world.new_pipeline()
    return world


def test_a_crash_after_a_4h_heartbeat_inside_one_batch_still_passes_parity(
    tmp_path: Path,
) -> None:
    """16-57 Test 1 (B1-CR-02): the committed 4h heartbeat names a bar of the acceptance log."""
    probe = World()
    fx = probe.fx
    final, sibling = fx.setup[249], fx.context[-1]
    assert sibling.close_time_utc == final.close_time_utc
    world = _raising_world(LogFirstState(), final.close_time_utc)
    world.start(fx.now - timedelta(hours=2))
    world.pipeline.handle(
        warm_bars(fx, n_1h=249, n_4h=len(fx.context) - 1),
        now_utc=fx.setup[248].close_time_utc + timedelta(seconds=1),
    )
    with pytest.raises(OSError, match="simulated crash"):
        world.pipeline.handle([live(sibling), live(final)], now_utc=two_seconds_after(final))

    heartbeats = world.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert [(r.interval, r.occurred_at_utc) for r in heartbeats] == [("4h", sibling.close_time_utc)]
    criterion = world.parity(world.bundle(tmp_path / "bundle"))
    text = "\n".join(criterion.evidence)
    assert "not a LIVE_WS entry" not in text, text
    assert criterion.passed, criterion.evidence


def test_gated_heartbeats_and_pipeline_gaps_follow_the_history_record_of_their_bar() -> None:
    """16-57 Test 2 (B1-CR-02): DATA_STALE, WARMUP_INSUFFICIENT, backfill and sibling gaps."""
    # WARMUP_INSUFFICIENT: a live bar with no history at all.
    cold = World(state=LogFirstState())
    cold.start()
    cold.pipeline.handle([cold.fx.live()], now_utc=cold.fx.now)
    [warmup] = cold.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert warmup.payload["reason_code"] == "WARMUP_INSUFFICIENT"
    assert isinstance(cold.state, LogFirstState)
    assert cold.state.violations == []

    # DATA_STALE, then a REST_BACKFILL gap.
    world = World(state=LogFirstState())
    fx = world.fx
    stale_bar = fx.setup[248]
    world.start(fx.now - timedelta(hours=3))
    world.pipeline.handle(warm_bars(fx, n_1h=240), now_utc=fx.now)
    world.pipeline.handle([live(stale_bar)], now_utc=stale_bar.close_time_utc + timedelta(hours=1))
    world.pipeline.handle([_tagged(fx.setup[241], SourceTag.REST_BACKFILL)], now_utc=fx.now)
    [stale] = world.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert stale.payload["reason_code"] == "DATA_STALE"
    assert len(world.records(RuntimeEventType.PAPER_GAP)) == 1
    assert isinstance(world.state, LogFirstState)
    assert world.state.violations == []

    # A missing 4h sibling: the gap and the SIBLING_4H_MISSING heartbeat follow the 1h entry.
    sib = World(state=LogFirstState())
    final = sib.fx.setup[249]
    sib.start(sib.fx.now - timedelta(hours=2))
    sib.pipeline.handle(
        warm_bars(sib.fx, n_1h=249, n_4h=len(sib.fx.context) - 1), now_utc=sib.fx.now
    )
    sib.pipeline.handle([live(final)], now_utc=final.close_time_utc + timedelta(seconds=40))
    [gap] = sib.records(RuntimeEventType.PAPER_GAP)
    assert gap.payload["reason"] == "EXCHANGE_NO_CANDLE"
    assert isinstance(sib.state, LogFirstState)
    assert sib.state.violations == []


def test_several_flushes_at_one_tick_time_keep_ids_unique_and_a_replayed_batch_is_a_no_op(
    tmp_path: Path,
) -> None:
    """16-57 Test 3 (B1-CR-02): history_seq per flush, no conflict, accept_seq order."""
    world = World(state=LogFirstState())
    fx = world.fx
    final, sibling = fx.setup[249], fx.context[-1]
    world.start(fx.now - timedelta(hours=2))
    world.pipeline.handle(
        warm_bars(fx, n_1h=249, skip={100}, n_4h=len(fx.context) - 1),
        now_utc=fx.setup[248].close_time_utc + timedelta(seconds=1),
    )
    batch = [
        _tagged(fx.setup[100], SourceTag.REST_BACKFILL),
        live(sibling),
        live(final),
    ]
    tick = two_seconds_after(final)
    result = world.pipeline.handle(batch, now_utc=tick)
    assert len(result.evaluated) == 1

    at_tick = [
        r for r in world.records(RuntimeEventType.PAPER_HISTORY_BARS) if r.occurred_at_utc == tick
    ]
    assert len(at_tick) >= 3  # one flush before the gap, the 4h heartbeat and the 1h inputs
    ids = {runtime_event_id(r) for r in world.records()}
    assert len(ids) == len(world.records())
    assert isinstance(world.state, LogFirstState)
    assert world.state.violations == []

    before = len(world.records())
    again = world.pipeline.handle(batch, now_utc=tick)
    assert again.recorded == () and again.replay_records == ()
    assert len(world.records()) == before

    seqs = [e["accept_seq"] for e in logged_entries(world)]
    assert seqs == sorted(seqs) == list(range(len(seqs)))
    criterion = world.parity(world.bundle(tmp_path / "bundle"))
    assert criterion.passed, criterion.evidence


# ---- Test 10: PostgreSQL --------------------------------------------------------------------- #


@pytest.fixture
def pg_engine(pg_db: str) -> Iterator[Engine]:
    engine = make_sync_engine(pg_db)
    try:
        yield engine
    finally:
        engine.dispose()


def _journal_rows(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(JournalEventRow)).scalar_one())


def test_replay_inputs_and_history_records_round_trip_on_postgresql(pg_engine: Engine) -> None:
    """Test 10: stored once, replayed as no-ops, conflicting content refused, read back equal."""
    world = World()
    world.run_tracer_session()
    new_types = (RuntimeEventType.PAPER_REPLAY_INPUTS, RuntimeEventType.PAPER_HISTORY_BARS)
    records = world.records(*new_types)
    assert {r.event_type for r in records} == set(new_types)

    state = PgRuntimeState(OperationalDatabase(pg_engine))
    for record in records:
        state.record(record)
    stored = _journal_rows(pg_engine)
    assert stored == len(records)
    for record in records:
        state.record(record)  # replay: a no-op
    assert _journal_rows(pg_engine) == stored

    for record in records:
        changed = dict(json.loads(record.payload_json), changed="yes")
        conflicting = RuntimeRecord(
            event_type=record.event_type,
            epoch_id=record.epoch_id,
            occurred_at_utc=record.occurred_at_utc,
            symbol=record.symbol,
            interval=record.interval,
            payload=changed,
        )
        with pytest.raises(RuntimeRecordConflict):
            state.record(conflicting)

    read_back = state.records(EPOCH_ID, new_types)
    assert sorted(r.payload_json for r in read_back) == sorted(r.payload_json for r in records)
