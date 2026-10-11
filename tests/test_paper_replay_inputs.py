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
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_public import SymbolFilters
from src.core.types import Candle
from src.domain.canonical import canonical_bytes
from src.domain.registry import ParameterSet
from src.paper.bars import BarBuffers
from src.paper.evidence_bundle import EvidenceBundle, load_evidence_bundle
from src.paper.exit_criteria import ParityReplay, build_parity_replay, parity_criterion
from src.paper.loop import BarContext
from src.paper.market_inputs import ConstraintProvider, make_context_factory
from src.paper.pipeline import BarPipeline, PipelineResult
from src.paper.replay_inputs import context_digest, context_from_inputs, rebuild_context
from src.paper.runtime_config import AccountConfig
from src.paper.runtime_state import InMemoryRuntimeState, RuntimeRecord, runtime_event_id
from src.paper.surface import decision_surface, surface_digest
from src.paper.vocabulary import RuntimeEventType
from src.risk.types import OpenPosition

from tests.test_paper_decision_surface import (
    PASSING_BAR,
    _all_bars,
    _case_input,
    _per_bar_context,
)
from tests.test_paper_exit_evaluator import TrialFixture
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
        self, positions: Sequence[OpenPosition] = (), daily_loss: Decimal | None = Decimal("0")
    ) -> None:
        self.positions = tuple(positions)
        self.daily_loss = daily_loss

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

    async def exchange_info(self) -> list[SymbolFilters]:
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


class World:
    """Real pipeline, real context factory, in-memory state, bundle writer and replay."""

    def __init__(
        self, *, risk: RiskDouble | None = None, state: InMemoryRuntimeState | None = None
    ) -> None:
        self.fx = Fixture()  # the data only: its own pipeline is not used
        self.case = self.fx.case
        self.parameter_set: ParameterSet = self.fx.parameter_set
        self.risk = risk or RiskDouble()
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
        self.pipeline = self.new_pipeline()

    def new_pipeline(self, buffers: BarBuffers | None = None) -> BarPipeline:
        return BarPipeline(
            epoch=_epoch(self.case, self.parameter_set, self.fx.setup[-1]),
            parameter_set=self.parameter_set,
            context_factory=self.factory,
            buffers=buffers or BarBuffers(),
            state=self.state,
            sibling_4h_wait_seconds=30,
            fetch_4h_bar=lambda symbol, close: None,
        )

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

    def bundle(self, directory: Path, rows: list[dict[str, Any]] | None = None) -> EvidenceBundle:
        trial = TrialFixture(
            epoch_id=EPOCH_ID,
            pin=self.started_at,
            window_end=self.started_at + timedelta(days=14),
            parameter_hash=self.parameter_set.parameter_set_hash,
            records=self.rows() if rows is None else rows,
        )
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
    assert inputs.payload_json == canonical_bytes(dict(inputs.payload)).decode("ascii")
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
