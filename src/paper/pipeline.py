"""Per-closed-bar pipeline of the paper runtime (Phase 16, plan 16-24; D-02, D-05..D-07, D-20).

The stateful glue between the supervisor's tagged bars (`src.paper.vocabulary.TaggedBar`) and the
typed per-bar seam (`src.paper.loop.evaluate_closed_bar`). It owns the incremental state D-02 gives
the runtime: the engine-window buffers, the open times already seen, and the epoch and parameter
set pinned once at start. For every closed bar it applies the source-tag rule, writes the heartbeat
record coverage needs (`PAPER_BAR_PROCESSED`, keyed on epoch, symbol, interval and bar close), and
carries the live decision-surface record of the bar so the trial can be replayed.

Source-tag rule (L-11 and the user's Q-D decision "history-only", D-06; ratified, not tunable):

- `LIVE_WS` closed 1h bars are the only candidates for evaluation. They pass the feed-freshness
  gate, the warm-up gate (both called from `src.paper.loop`, not copied), a history-continuity
  gate and then `evaluate_closed_bar`.
- `LIVE_WS` closed 4h bars extend the context window and are recorded as context bars.
- `REST_WARMUP` bars (closed while the process was down) only extend history. They are never
  evaluated and never recorded as processed.
- `REST_BACKFILL` bars (recovered by REST while the process stayed up) also only extend history,
  in time order. They are never evaluated: no signal, no plan, no approval, no reservation. Every
  such close is recorded as exactly one `PAPER_GAP` with reason `WS_RECONNECT_WINDOW`; the gap
  stays uncovered evidence and no record says the feed was healthy because the backfill worked.
  There is no age or freshness exception, and the rule must not change during a soak without a
  separate user decision.

Mixed batches are decided bar by bar. When one batch carries several copies of the same bar the
copy with the strongest source wins (LIVE_WS over REST_BACKFILL over REST_WARMUP), so the outcome
never depends on arrival order; the other copies are reported as duplicates. A bar that was
already accepted (any source) is a duplicate: it creates no record and no state change.

Fail closed (never guess): live evaluation needs a continuous history. The last
`WARMUP_MIN_BARS` 1h bars before the live bar and the last `WARMUP_MIN_BARS` 4h bars must follow
each other without a hole, and the latest 4h bar must not be a whole 4h cycle behind. A hole left
by a backfill that could not recover a close makes the live bar a recorded feed-gate reject
(`HISTORY_DISCONTINUITY`), not an evaluation, until the history is filled again (for example by a
REST warm-up of the missing closes).

4h sibling (research Pitfall P6): at a close shared with a 4h bar, a live 1h bar whose 4h sibling
has not arrived is returned in `PipelineResult.held` with a deadline of its close plus
`sibling_4h_wait_seconds`; the caller re-submits it, and the pipeline never sleeps. At or after the
deadline the injected `fetch_4h_bar(symbol, close)` is tried once; a fetched sibling is a context
bar and is handled like a backfilled bar (history, one `PAPER_GAP`). If it is still missing the 1h
bar is not evaluated: one `PAPER_GAP` with reason `EXCHANGE_NO_CANDLE` is recorded for the 4h
close and the 1h bar is recorded as a feed-gate reject (`SIBLING_4H_MISSING`).

A closed bar whose close time is later than the injected tick time (a host clock running behind) is
not evaluated, exactly as `run_paper_tick` treats it. The pipeline only makes the drop visible: the
bar is listed in `PipelineResult.dropped` with reason `FUTURE_CLOSE` and the exact delta in
milliseconds, is not added to history and is not recorded as processed (research P20).

Parity replay records (plan 16-51, user decision 16-DEC-PARITY option 1): every bar `_accept`
stores, from any source and live bars included, is logged with its acceptance sequence `accept_seq`
in a `PAPER_HISTORY_BARS` record, written before the `PAPER_REPLAY_INPUTS` record of any evaluation
that can read it, before every heartbeat and every `PAPER_GAP` (plan 16-57, B1-CR-02: a crash
inside a batch never leaves a record naming a bar the log does not hold) and at the end of `handle`
when entries are pending. REST_WARMUP and REST_BACKFILL
bars are still never evaluated and never recorded as processed (L-11, D-06): the log only lets the
trial evaluator rebuild the windows in the order the buffers received the bars. Each evaluated
live 1h bar also writes one `PAPER_REPLAY_INPUTS` record (what the risk stage read and
`window_accept_seq`, the last accepted bar the windows were cut after) just before its heartbeat.
The heartbeat and gap payloads are unchanged; the new records ride in
`PipelineResult.replay_records`, not in `recorded`.

Pure module: the tick time is injected (no clock read), no sleeping, no float, and no import from
`src.backtest.engine`, `src.execution` or `src.adapters`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.types import Candle
from src.domain.registry import ParameterSet
from src.paper.bars import CONTEXT_INTERVAL, SETUP_INTERVAL, BarBuffers, group_by_close
from src.paper.freeze import StreamEpoch
from src.paper.loop import (
    WARMUP_MIN_BARS,
    BarContext,
    BarOutcome,
    check_feature_validity,
    check_feed_freshness,
    evaluate_closed_bar,
)
from src.paper.replay_inputs import HistoryEntry, history_log_payload, replay_inputs_payload
from src.paper.runtime_state import RuntimeRecord, RuntimeStatePort
from src.paper.surface import (
    DecisionSurfaceRecord,
    context_record,
    feature_digest,
    gate_record,
    outcome_record,
)
from src.paper.vocabulary import (
    INTERVAL_MS,
    DropReason,
    GapReason,
    GapRecord,
    RuntimeEventType,
    SourceTag,
    TaggedBar,
)

# Feed-gate reason codes this module adds to the ones `src.paper.loop` and `src.paper.surface` use.
REASON_HISTORY_DISCONTINUITY = "HISTORY_DISCONTINUITY"
REASON_SIBLING_4H_MISSING = "SIBLING_4H_MISSING"

# Where a PAPER_GAP written here came from (part of the payload, so it must be deterministic).
GAP_DETAIL_BACKFILL = "REST_BACKFILL"
GAP_DETAIL_SIBLING_FETCHED = "FETCHED_4H_SIBLING"
GAP_DETAIL_SIBLING_MISSING = "NO_4H_SIBLING"

_ONE_MS = timedelta(milliseconds=1)
_UNIX_ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_HOUR = timedelta(milliseconds=INTERVAL_MS[SETUP_INTERVAL])
_FOUR_HOURS = timedelta(milliseconds=INTERVAL_MS[CONTEXT_INTERVAL])

# Which copy of one bar wins when a batch carries several (higher wins).
_SOURCE_STRENGTH: dict[SourceTag, int] = {
    SourceTag.LIVE_WS: 2,
    SourceTag.REST_BACKFILL: 1,
    SourceTag.REST_WARMUP: 0,
}


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
    """What one `handle` call did, in processing order (close ascending, 4h before 1h).

    `recorded` holds every heartbeat and gap written; `gaps` the gaps among them. `replay_records`
    holds the parity-replay records written (`PAPER_HISTORY_BARS` and `PAPER_REPLAY_INPUTS`, plan
    16-51) in write order.
    """

    evaluated: tuple[BarOutcome, ...] = ()
    recorded: tuple[RuntimeRecord, ...] = ()
    duplicates: tuple[TaggedBar, ...] = ()
    held: tuple[HeldBar, ...] = ()
    gaps: tuple[GapRecord, ...] = ()
    dropped: tuple[DroppedBar, ...] = ()
    replay_records: tuple[RuntimeRecord, ...] = ()


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


def _contiguous(bars: Sequence[Candle], step: timedelta) -> bool:
    """True when every bar opens exactly one `step` after the previous one."""
    return all(
        later.open_time_utc - earlier.open_time_utc == step
        for earlier, later in zip(bars, bars[1:], strict=False)
    )


def _conflict(bar: TaggedBar) -> ValueError:
    return ValueError(
        f"conflicting duplicate bar for {bar.symbol} {bar.interval} "
        f"open {bar.open_time_utc.isoformat()}"
    )


class _Batch:
    """Mutable collector for one `handle` call, frozen into a `PipelineResult` at the end."""

    def __init__(self) -> None:
        self.evaluated: list[BarOutcome] = []
        self.recorded: list[RuntimeRecord] = []
        self.duplicates: list[TaggedBar] = []
        self.held: list[HeldBar] = []
        self.gaps: list[GapRecord] = []
        self.dropped: list[DroppedBar] = []
        self.replay_records: list[RuntimeRecord] = []

    def freeze(self) -> PipelineResult:
        dropped = sorted(self.dropped, key=lambda d: (d.close_time_utc, d.symbol, d.interval))
        return PipelineResult(
            evaluated=tuple(self.evaluated),
            recorded=tuple(self.recorded),
            duplicates=tuple(self.duplicates),
            held=tuple(self.held),
            gaps=tuple(self.gaps),
            dropped=tuple(dropped),
            replay_records=tuple(self.replay_records),
        )


class BarPipeline:
    """Handles tagged closed bars one batch at a time (see the module docstring).

    Every argument is required and keyword-only; none has a default. `parameter_set` is the object
    loaded once at start, whose hash `epoch` pinned: it is never re-read per bar (D-03, one registry
    root), and `context_factory` must return contexts that carry that same hash (registry
    immutability stays the hourly check's job, L-01). `context_factory(candle)` builds the
    `BarContext` of a 1h bar (the constraint snapshot, open positions and daily loss at its close).
    `sibling_4h_wait_seconds` is how long a 1h bar may wait for its 4h sibling at a shared close and
    `fetch_4h_bar(symbol, close_time_utc)` fetches that sibling once at the deadline (None when the
    exchange has no such candle); an exception it raises propagates to the caller.
    `claim_gap(symbol, interval, expected_close_utc)` is the shared written-gap set of the runtime
    (`GapLedger.claim`, plan 16-57, B1-WR-05): True when this pipeline is the first writer of that
    close, False when the supervisor or a restart already wrote it. A refused claim skips only the
    PAPER_GAP record; the bar still enters history.
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
        fetch_4h_bar: Callable[[str, datetime], TaggedBar | None],
        claim_gap: Callable[[str, str, datetime], bool],
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
        self._fetch_4h_bar = fetch_4h_bar
        self._claim_gap = claim_gap
        # Every bar accepted into history, by (symbol, interval, open time): one entry per closed
        # bar, a few bytes each, so it is kept for the life of the process.
        self._seen: dict[tuple[str, str, datetime], Candle] = {}
        # Open times of bars a previous run already processed (restored after a restart): a
        # redelivery of one is a duplicate, whatever the warm-up window still holds.
        self._processed_before_start: set[tuple[str, str, datetime]] = set()
        # The acceptance log of plan 16-51: a counter over every bar `_accept` stores, the entries
        # not yet written, and the counter of the PAPER_HISTORY_BARS records.
        self._accept_seq = 0
        self._pending: list[HistoryEntry] = []
        self._history_seq = 0

    def seed_processed(self, last_closes: Mapping[tuple[str, str], datetime]) -> None:
        """Mark each pair's restored last processed close as already handled (plan 16-29).

        Called once after the REST warm-up and before the first live bar. The bar is only marked,
        not added to history: the warm-up already did that when the exchange still returns it.
        """
        for (symbol, interval), close in last_closes.items():
            step = timedelta(milliseconds=INTERVAL_MS[interval])
            self._processed_before_start.add((symbol, interval, close + _ONE_MS - step))

    def handle(self, bars: Iterable[TaggedBar], *, now_utc: datetime) -> PipelineResult:
        """Process a batch of tagged bars at the injected tick time `now_utc`."""
        _require_utc("now_utc", now_utc)
        batch = _Batch()
        candidates: list[TaggedBar] = []
        for bar in bars:
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

        for _, group in group_by_close(self._one_copy_per_bar(candidates, batch)):
            for bar in group:
                self._handle_closed_bar(bar, now_utc, batch)
        self._flush_history(now_utc, batch)
        return batch.freeze()

    # ------------------------------------------------------------------ #
    # Batch preparation.
    # ------------------------------------------------------------------ #

    @staticmethod
    def _one_copy_per_bar(bars: Sequence[TaggedBar], batch: _Batch) -> list[TaggedBar]:
        """Keep the strongest-source copy of each bar; the others are duplicates."""
        chosen: dict[tuple[str, str, datetime], TaggedBar] = {}
        for bar in bars:
            key = (bar.symbol, bar.interval, bar.open_time_utc)
            kept = chosen.get(key)
            if kept is None:
                chosen[key] = bar
                continue
            if _to_candle(kept) != _to_candle(bar):
                raise _conflict(bar)
            if _SOURCE_STRENGTH[bar.source] > _SOURCE_STRENGTH[kept.source]:
                chosen[key] = bar
                batch.duplicates.append(kept)
            else:
                batch.duplicates.append(bar)
        return list(chosen.values())

    # ------------------------------------------------------------------ #
    # One closed bar.
    # ------------------------------------------------------------------ #

    def _handle_closed_bar(self, bar: TaggedBar, now_utc: datetime, batch: _Batch) -> None:
        candle = _to_candle(bar)
        stored = self._seen.get((bar.symbol, bar.interval, bar.open_time_utc))
        if stored is not None:
            if stored != candle:
                raise _conflict(bar)
            batch.duplicates.append(bar)
            return
        if (bar.symbol, bar.interval, bar.open_time_utc) in self._processed_before_start:
            batch.duplicates.append(bar)
            return

        live_1h = bar.source is SourceTag.LIVE_WS and bar.interval == SETUP_INTERVAL
        fetched: TaggedBar | None = None
        sibling_missing = False
        if live_1h:
            due = self._sibling_due(candle)
            if due:
                deadline = candle.close_time_utc + self._sibling_4h_wait
                if now_utc < deadline:
                    batch.held.append(HeldBar(bar=bar, deadline_utc=deadline))
                    return  # a held bar changes no state; the caller re-submits it
                fetched = self._fetch_sibling(candle, now_utc)
                sibling_missing = fetched is None

        if not self._accept(bar, candle, batch):
            return
        if fetched is not None:
            self._ingest_fetched_sibling(fetched, now_utc, batch)

        if bar.source is SourceTag.REST_WARMUP:
            return  # history only: never evaluated, never recorded (L-11)
        if bar.source is SourceTag.REST_BACKFILL:
            self._skip_backfilled(bar, GAP_DETAIL_BACKFILL, now_utc, batch)
            return
        if bar.interval == CONTEXT_INTERVAL:
            self._write_heartbeat(bar, candle, now_utc, context_record(candle), batch)
            return
        if bar.interval != SETUP_INTERVAL:
            raise ValueError(f"unsupported interval {bar.interval!r}")
        if sibling_missing:
            self._write_gap(
                GapRecord(
                    symbol=bar.symbol,
                    interval=CONTEXT_INTERVAL,
                    expected_close_utc=bar.close_time_utc,
                    reason=GapReason.EXCHANGE_NO_CANDLE,
                    detected_at_utc=now_utc,
                ),
                GAP_DETAIL_SIBLING_MISSING,
                now_utc,
                batch,
            )
            gate = gate_record(candle, REASON_SIBLING_4H_MISSING)
            self._write_heartbeat(bar, candle, now_utc, gate, batch)
            return
        self._evaluate_live_bar(bar, candle, now_utc, batch)

    def _accept(
        self,
        bar: TaggedBar,
        candle: Candle,
        batch: _Batch,
        *,
        fetched_for_close_utc: datetime | None = None,
    ) -> bool:
        """Add a new closed bar to the history; False when the buffers refuse it.

        An accepted bar gets the next acceptance sequence and waits in the pending log.
        """
        if not self._buffers.add(candle):
            # Older than everything a full buffer still retains: it cannot re-enter history.
            batch.duplicates.append(bar)
            return False
        self._seen[(bar.symbol, bar.interval, bar.open_time_utc)] = candle
        self._pending.append(
            HistoryEntry(
                accept_seq=self._accept_seq,
                source=bar.source.value,
                candle=candle,
                fetched_for_close_utc=fetched_for_close_utc,
            )
        )
        self._accept_seq += 1
        return True

    def _flush_history(self, now_utc: datetime, batch: _Batch) -> None:
        """Write the pending acceptance-log entries as ONE PAPER_HISTORY_BARS record.

        Nothing is written when nothing is pending. The sequence advances and the entries are
        released only after the state port accepted the record.
        """
        if not self._pending:
            return
        record = RuntimeRecord(
            event_type=RuntimeEventType.PAPER_HISTORY_BARS,
            epoch_id=self._epoch.epoch_id,
            occurred_at_utc=now_utc,
            payload=history_log_payload(self._pending, history_seq=self._history_seq),
        )
        self._state.record(record)
        self._history_seq += 1
        self._pending = []
        batch.replay_records.append(record)

    # ------------------------------------------------------------------ #
    # 4h sibling.
    # ------------------------------------------------------------------ #

    def _sibling_due(self, candle: Candle) -> bool:
        """True when the next 4h close after the latest known 4h bar is this 1h bar's close.

        The 4h cadence is read from the history itself, so the rule needs no calendar: a 1h bar at
        a close shared with a 4h bar whose 4h bar has not arrived is "due". With no 4h history the
        warm-up gate decides, so nothing is due.
        """
        context = self._buffers.context_window(candle.symbol, candle.close_time_utc)
        if not context:
            return False
        return context[-1].close_time_utc + _FOUR_HOURS == candle.close_time_utc

    def _fetch_sibling(self, candle: Candle, now_utc: datetime) -> TaggedBar | None:
        fetched = self._fetch_4h_bar(candle.symbol, candle.close_time_utc)
        if fetched is None:
            return None
        if (
            fetched.symbol != candle.symbol
            or fetched.interval != CONTEXT_INTERVAL
            or fetched.close_time_utc != candle.close_time_utc
            or fetched.close_time_utc > now_utc
        ):
            raise ValueError(
                f"fetch_4h_bar returned {fetched.symbol} {fetched.interval} closing "
                f"{fetched.close_time_utc.isoformat()}, expected {candle.symbol} "
                f"{CONTEXT_INTERVAL} closing {candle.close_time_utc.isoformat()}"
            )
        return fetched

    def _ingest_fetched_sibling(self, fetched: TaggedBar, now_utc: datetime, batch: _Batch) -> None:
        """A fetched 4h sibling is context only: history plus one gap, like a backfilled bar."""
        sibling = _to_candle(fetched)
        if self._accept(fetched, sibling, batch, fetched_for_close_utc=fetched.close_time_utc):
            self._skip_backfilled(fetched, GAP_DETAIL_SIBLING_FETCHED, now_utc, batch)

    # ------------------------------------------------------------------ #
    # Live evaluation.
    # ------------------------------------------------------------------ #

    def _evaluate_live_bar(
        self, bar: TaggedBar, candle: Candle, now_utc: datetime, batch: _Batch
    ) -> None:
        # The liveness signal wins over under-warmed history (run_paper_tick, WR-03).
        stale = check_feed_freshness(_close_event(candle), now_utc)
        if stale is not None:
            self._write_heartbeat(bar, candle, now_utc, gate_record(candle, stale), batch)
            return

        close = candle.close_time_utc
        setup_window = self._buffers.setup_window(candle.symbol, close)
        context_window = self._buffers.context_window(candle.symbol, close)
        warmup = check_feature_validity(setup_window[:-1], context_window)
        if warmup is not None:
            self._write_heartbeat(bar, candle, now_utc, gate_record(candle, warmup), batch)
            return
        if not self._history_is_continuous(candle, setup_window, context_window):
            gate = gate_record(candle, REASON_HISTORY_DISCONTINUITY)
            self._write_heartbeat(bar, candle, now_utc, gate, batch)
            return

        context = self._context_factory(candle)
        if context.symbol != candle.symbol:
            raise ValueError(f"context symbol {context.symbol!r} != bar symbol {candle.symbol!r}")
        if context.parameter_set.parameter_set_hash != self._parameter_set.parameter_set_hash:
            raise ValueError(
                "context parameter_set_hash differs from the pinned epoch's parameter_set_hash"
            )
        digest = feature_digest(context, candle.symbol, setup_window)
        inputs = RuntimeRecord(
            event_type=RuntimeEventType.PAPER_REPLAY_INPUTS,
            epoch_id=self._epoch.epoch_id,
            occurred_at_utc=close,
            symbol=candle.symbol,
            interval=candle.interval,
            payload=replay_inputs_payload(
                context,
                setup_window=setup_window,
                context_window=context_window,
                window_accept_seq=self._accept_seq - 1,
            ),
        )
        # Every bar these windows can read is stored before the inputs that name them.
        self._flush_history(now_utc, batch)
        self._state.record(inputs)
        batch.replay_records.append(inputs)
        outcome = evaluate_closed_bar(context, candle, setup_window, context_window)
        batch.evaluated.append(outcome)
        record = outcome_record(candle, outcome, digest=digest)
        self._write_heartbeat(bar, candle, now_utc, record, batch)

    @staticmethod
    def _history_is_continuous(
        candle: Candle, setup_window: Sequence[Candle], context_window: Sequence[Candle]
    ) -> bool:
        """The history the features will read has no hole (fail closed, never guess).

        The warm-up gate counts `WARMUP_MIN_BARS` bars of each interval; those bars (and the live
        bar) must follow each other exactly, and the latest 4h bar must not be a whole 4h cycle
        behind the live bar (a 4h bar at the live close itself is the shared-close case).
        """
        setup_tail = setup_window[-(WARMUP_MIN_BARS + 1) :]
        context_tail = context_window[-WARMUP_MIN_BARS:]
        if not _contiguous(setup_tail, _ONE_HOUR) or not _contiguous(context_tail, _FOUR_HOURS):
            return False
        return context_tail[-1].close_time_utc + _FOUR_HOURS > candle.close_time_utc

    # ------------------------------------------------------------------ #
    # Records.
    # ------------------------------------------------------------------ #

    def _skip_backfilled(
        self, bar: TaggedBar, detail: str, now_utc: datetime, batch: _Batch
    ) -> None:
        """Q-D history-only: the close is not evaluated; it is one PAPER_GAP WS_RECONNECT_WINDOW."""
        gap = GapRecord(
            symbol=bar.symbol,
            interval=bar.interval,
            expected_close_utc=bar.close_time_utc,
            reason=GapReason.WS_RECONNECT_WINDOW,
            detected_at_utc=now_utc,
        )
        self._write_gap(gap, detail, now_utc, batch)

    def _write_gap(self, gap: GapRecord, detail: str, now_utc: datetime, batch: _Batch) -> None:
        # B1-CR-02: the acceptance log is durable before any record that names an accepted bar.
        self._flush_history(now_utc, batch)
        if not self._claim_gap(gap.symbol, gap.interval, gap.expected_close_utc):
            # B1-WR-05: another writer recorded this close first; its record stands.
            return
        # The payload carries no tick time, so a replayed gap is the same record (same content).
        record = RuntimeRecord(
            event_type=RuntimeEventType.PAPER_GAP,
            epoch_id=self._epoch.epoch_id,
            occurred_at_utc=now_utc,
            symbol=gap.symbol,
            interval=gap.interval,
            payload={
                "expected_close_utc": gap.expected_close_utc,
                "reason": gap.reason.value,
                "source": detail,
            },
        )
        self._state.record(record)
        batch.recorded.append(record)
        batch.gaps.append(gap)

    def _write_heartbeat(
        self,
        bar: TaggedBar,
        candle: Candle,
        now_utc: datetime,
        surface: DecisionSurfaceRecord,
        batch: _Batch,
    ) -> None:
        # B1-CR-02: a crash after this heartbeat must not leave a bar the parity replay cannot
        # find, so every pending acceptance-log entry is written first.
        self._flush_history(now_utc, batch)
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
    "GAP_DETAIL_BACKFILL",
    "GAP_DETAIL_SIBLING_FETCHED",
    "GAP_DETAIL_SIBLING_MISSING",
    "REASON_HISTORY_DISCONTINUITY",
    "REASON_SIBLING_4H_MISSING",
    "BarPipeline",
    "DroppedBar",
    "HeldBar",
    "PipelineResult",
]
