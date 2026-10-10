"""Per-closed-bar pipeline of the paper runtime (Phase 16, plan 16-24; D-02, D-05..D-07, D-20).

The stateful glue between the supervisor's tagged bars (`src.paper.vocabulary.TaggedBar`) and the
typed per-bar seam (`src.paper.loop.evaluate_closed_bar`). It owns the incremental state D-02 gives
the runtime: the engine-window buffers, the open times already seen, and the epoch and parameter
set pinned once at start. For every closed bar it applies the source-tag rule, writes the heartbeat
record coverage needs (`PAPER_BAR_PROCESSED`, keyed on epoch, symbol, interval and bar close), and
carries the live decision-surface record of the bar so the trial can be replayed.

Source-tag rule (L-11, structural, not a freshness constant):

- `LIVE_WS` closed 1h bars are the only candidates for evaluation: they pass the feed-freshness and
  warm-up gates (the same functions `run_paper_tick` calls) and then `evaluate_closed_bar`.
- `LIVE_WS` closed 4h bars extend the context window and are recorded as context bars.
- `REST_WARMUP` bars only extend history. They are never evaluated and never recorded.
- `REST_BACKFILL` bars (recovered by REST while the process stayed up) have no rule yet: it is the
  user's Q-D decision. Until it is recorded and implemented, `handle` refuses them with
  `UndecidedSourceRule` before touching any state, so no late signal can slip through.

A closed bar whose close time is later than the injected tick time (a host clock running behind) is
not evaluated, exactly as `run_paper_tick` treats it. The pipeline only makes the drop visible: the
bar is listed in `PipelineResult.dropped` with reason `FUTURE_CLOSE` and the exact delta in
milliseconds, is not added to history and is not recorded as processed (research P20). It is never
retried, held or re-timed here.

Pure module: the tick time is injected (no clock read), no sleeping, no float, and no import from
`src.backtest.engine`, `src.execution` or `src.adapters`. The 4h sibling wait is data the caller
re-submits against, never a sleep (research Pitfall P6).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.types import Candle
from src.domain.registry import ParameterSet
from src.paper.bars import CONTEXT_INTERVAL, SETUP_INTERVAL, BarBuffers, group_by_close
from src.paper.freeze import StreamEpoch
from src.paper.loop import (
    BarContext,
    BarOutcome,
    check_feature_validity,
    check_feed_freshness,
    evaluate_closed_bar,
)
from src.paper.runtime_state import RuntimeRecord, RuntimeStatePort
from src.paper.surface import (
    DecisionSurfaceRecord,
    context_record,
    feature_digest,
    gate_record,
    outcome_record,
)
from src.paper.vocabulary import DropReason, GapRecord, SourceTag, TaggedBar

_ONE_MS = timedelta(milliseconds=1)
_UNIX_ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)


class UndecidedSourceRule(ValueError):  # noqa: N818 - a refusal, named after what is undecided
    """A bar arrived with a source tag whose evaluation rule the user has not decided yet."""


@dataclass(frozen=True)
class DroppedBar:
    """A closed bar the tick did not evaluate because its close lies after the tick time."""

    symbol: str
    interval: str
    close_time_utc: datetime
    reason: DropReason
    delta_ms: int


@dataclass(frozen=True)
class HeldBar:
    """A 1h bar waiting for its 4h sibling; the caller re-submits it at `deadline_utc`."""

    bar: TaggedBar
    deadline_utc: datetime


@dataclass(frozen=True)
class PipelineResult:
    """What one `handle` call did, in processing order (close ascending, 4h before 1h)."""

    evaluated: tuple[BarOutcome, ...] = ()
    recorded: tuple[RuntimeRecord, ...] = ()
    duplicates: tuple[TaggedBar, ...] = ()
    held: tuple[HeldBar, ...] = ()
    gaps: tuple[GapRecord, ...] = ()
    dropped: tuple[DroppedBar, ...] = ()


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC-aware")


def _to_candle(bar: TaggedBar) -> Candle:
    return Candle(
        symbol=bar.symbol,
        interval=bar.interval,
        open_time_utc=bar.open_time_utc,
        close_time_utc=bar.close_time_utc,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


def _close_event(candle: Candle) -> dict[str, Any]:
    """The minimal kline-event shape `check_feed_freshness` reads: the close time in ms."""
    return {"T": (candle.close_time_utc - _UNIX_ORIGIN) // _ONE_MS}


class _Batch:
    """Mutable collector for one `handle` call, frozen into a `PipelineResult` at the end."""

    def __init__(self) -> None:
        self.evaluated: list[BarOutcome] = []
        self.recorded: list[RuntimeRecord] = []
        self.duplicates: list[TaggedBar] = []
        self.held: list[HeldBar] = []
        self.gaps: list[GapRecord] = []
        self.dropped: list[DroppedBar] = []

    def freeze(self) -> PipelineResult:
        dropped = sorted(self.dropped, key=lambda d: (d.close_time_utc, d.symbol, d.interval))
        return PipelineResult(
            evaluated=tuple(self.evaluated),
            recorded=tuple(self.recorded),
            duplicates=tuple(self.duplicates),
            held=tuple(self.held),
            gaps=tuple(self.gaps),
            dropped=tuple(dropped),
        )


class BarPipeline:
    """Handles tagged closed bars one batch at a time (see the module docstring).

    Every argument is required and keyword-only; none has a default. `parameter_set` is the object
    loaded once at start, whose hash `epoch` pinned: it is never re-read per bar (D-03, one registry
    root), and `context_factory` must return contexts that carry that same hash (registry
    immutability stays the hourly check's job, L-01). `context_factory(candle)` builds the
    `BarContext` of a 1h bar (the constraint snapshot, open positions and daily loss at its close).
    `sibling_4h_wait_seconds` is how long a 1h bar may wait for its 4h sibling at a shared close.
    """

    def __init__(
        self,
        *,
        epoch: StreamEpoch,
        parameter_set: ParameterSet,
        context_factory: Callable[[Candle], BarContext],
        buffers: BarBuffers,
        state: RuntimeStatePort,
        sibling_4h_wait_seconds: int,
    ) -> None:
        if epoch.parameter_set_hash != parameter_set.parameter_set_hash:
            raise ValueError(
                f"epoch parameter_set_hash={epoch.parameter_set_hash!r} != loaded "
                f"parameter_set_hash={parameter_set.parameter_set_hash!r}"
            )
        if isinstance(sibling_4h_wait_seconds, bool) or not isinstance(
            sibling_4h_wait_seconds, int
        ):
            raise TypeError("sibling_4h_wait_seconds must be an int")
        if sibling_4h_wait_seconds < 0:
            raise ValueError("sibling_4h_wait_seconds must not be negative")
        self._epoch = epoch
        self._parameter_set = parameter_set
        self._context_factory = context_factory
        self._buffers = buffers
        self._state = state
        self._sibling_4h_wait = timedelta(seconds=sibling_4h_wait_seconds)
        # Every bar accepted into history, by (symbol, interval, open time): one entry per closed
        # bar, a few bytes each, so it is kept for the life of the process.
        self._seen: dict[tuple[str, str, datetime], Candle] = {}

    def handle(self, bars: Iterable[TaggedBar], *, now_utc: datetime) -> PipelineResult:
        """Process a batch of tagged bars at the injected tick time `now_utc`."""
        _require_utc("now_utc", now_utc)
        incoming = list(bars)
        for bar in incoming:
            if bar.source is SourceTag.REST_BACKFILL:
                raise UndecidedSourceRule(
                    "REST_BACKFILL evaluation is the user's Q-D decision and is not implemented "
                    "yet; refusing the batch before any state changes"
                )

        batch = _Batch()
        candidates: list[TaggedBar] = []
        for bar in incoming:
            if bar.close_time_utc > now_utc:
                batch.dropped.append(
                    DroppedBar(
                        symbol=bar.symbol,
                        interval=bar.interval,
                        close_time_utc=bar.close_time_utc,
                        reason=DropReason.FUTURE_CLOSE,
                        delta_ms=(bar.close_time_utc - now_utc) // _ONE_MS,
                    )
                )
            else:
                candidates.append(bar)

        for _, group in group_by_close(candidates):
            for bar in group:
                self._handle_closed_bar(bar, now_utc, batch)
        return batch.freeze()

    # ------------------------------------------------------------------ #

    def _handle_closed_bar(self, bar: TaggedBar, now_utc: datetime, batch: _Batch) -> None:
        candle = _to_candle(bar)
        key = (bar.symbol, bar.interval, bar.open_time_utc)
        stored = self._seen.get(key)
        if stored is not None:
            if stored != candle:
                raise ValueError(
                    f"conflicting duplicate bar for {bar.symbol} {bar.interval} "
                    f"open {bar.open_time_utc.isoformat()}"
                )
            batch.duplicates.append(bar)
            return
        if not self._buffers.add(candle):
            # Older than everything a full buffer still retains: it cannot re-enter history.
            batch.duplicates.append(bar)
            return
        self._seen[key] = candle

        if bar.source is SourceTag.REST_WARMUP:
            return  # history only: never evaluated, never recorded (L-11)

        if bar.interval == CONTEXT_INTERVAL:
            self._write(bar, candle, now_utc, context_record(candle), batch)
            return
        if bar.interval != SETUP_INTERVAL:
            raise ValueError(f"unsupported interval {bar.interval!r}")
        self._evaluate_live_bar(bar, candle, now_utc, batch)

    def _evaluate_live_bar(
        self, bar: TaggedBar, candle: Candle, now_utc: datetime, batch: _Batch
    ) -> None:
        # The liveness signal wins over under-warmed history (run_paper_tick, WR-03).
        stale = check_feed_freshness(_close_event(candle), now_utc)
        if stale is not None:
            self._write(bar, candle, now_utc, gate_record(candle, stale), batch)
            return

        close = candle.close_time_utc
        setup_window = self._buffers.setup_window(candle.symbol, close)
        context_window = self._buffers.context_window(candle.symbol, close)
        warmup = check_feature_validity(setup_window[:-1], context_window)
        if warmup is not None:
            self._write(bar, candle, now_utc, gate_record(candle, warmup), batch)
            return

        context = self._context_factory(candle)
        if context.symbol != candle.symbol:
            raise ValueError(f"context symbol {context.symbol!r} != bar symbol {candle.symbol!r}")
        if context.parameter_set.parameter_set_hash != self._parameter_set.parameter_set_hash:
            raise ValueError(
                "context parameter_set_hash differs from the pinned epoch's parameter_set_hash"
            )
        digest = feature_digest(context, candle.symbol, setup_window)
        outcome = evaluate_closed_bar(context, candle, setup_window, context_window)
        batch.evaluated.append(outcome)
        self._write(bar, candle, now_utc, outcome_record(candle, outcome, digest=digest), batch)

    def _write(
        self,
        bar: TaggedBar,
        candle: Candle,
        now_utc: datetime,
        surface: DecisionSurfaceRecord,
        batch: _Batch,
    ) -> None:
        record = RuntimeRecord.bar_processed(
            epoch_id=self._epoch.epoch_id,
            symbol=bar.symbol,
            interval=bar.interval,
            close_time_utc=bar.close_time_utc,
            payload={
                "source": bar.source.value,
                "tick_time_utc": now_utc,
                "bar": {
                    "symbol": candle.symbol,
                    "interval": candle.interval,
                    "open_time_utc": candle.open_time_utc,
                    "close_time_utc": candle.close_time_utc,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                },
                "stage": surface.stage,
                "reason_code": surface.reason_code,
                "plan_hash": surface.plan_hash,
                "surface": surface.to_dict(),
            },
        )
        self._state.record(record)
        batch.recorded.append(record)


__all__ = [
    "BarPipeline",
    "DroppedBar",
    "HeldBar",
    "PipelineResult",
    "UndecidedSourceRule",
]
