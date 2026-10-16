"""Restart, downtime and warm-up of the paper runtime (Phase 16, plan 16-29).

What a restart has to guarantee (D-02, D-04, D-06, L-04, L-11, REV-01, research Pitfall P8):

- State comes back from the soak database, never from memory: the last processed close per
  (symbol, interval) and the last runtime marker (`restore_runtime`).
- A bar that closed while the process was down is a gap with a reason code and is never
  evaluated: `downtime_gaps` names every such close, PLANNED_RESTART when a RUNTIME_STOP closed
  the previous run and CRASH when none did. The gap stays uncovered evidence (REV-01).
- The engine windows are rebuilt from REST before the first evaluated bar (`warm_up`): exactly
  `STRATEGY_WINDOW_BARS` closed 1h bars and `CONTEXT_WINDOW_BARS` closed 4h bars per symbol. The
  depth is structural (the same windows the backtest cuts), not a user number.
- The supervisor cursor is seeded with the newest close of the warm-up snapshot, because the
  downtime closes are already recorded as gaps (an empty cursor map hides the downtime gap and
  breaks the post-reconnect backfill).
- The seam between the warm-up snapshot and the first subscription is closed by one
  post-start verification backfill (plan 16-57, B1-WR-01): the runtime awaits
  `PaperSupervisor.verify_start_seam()` right after `PaperSupervisor.start()`. The SDK's `open`
  echo fires while the connection is being opened, before the supervisor counts as started, so
  it is ignored and triggers nothing. The verification backfill runs from the seeded cursors under
  the supervisor's recovery lock with live bars held; a bar that closed after the snapshot reaches
  history as REST_BACKFILL with its one PAPER_GAP (Q-D: never evaluated).
- No late signal, whatever the user's Q-D answer is. The verification backfill (and any later
  reconnect backfill) can hand the pipeline a bar that closed at or before the warm-up snapshot
  (an exchange that was late for a bar the snapshot lacked). A restart fence
  (`apply_restart_fence`) re-tags every such non-live bar as history only before it reaches the
  pipeline, so no evaluation rule can turn a downtime bar into a signal. The user's choice only
  governs recoveries of drops while the process stays up.

Pure module: stdlib, the pure paper vocabulary, the interval arithmetic of the resync module and
the runtime state port. It never reads a clock (every time is injected) and uses no float.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from src.adapters.binance_public import Kline
from src.backtest.semantics import CONTEXT_WINDOW_BARS, STRATEGY_WINDOW_BARS
from src.paper.resync import expected_close_times
from src.paper.runtime_config import CONFIG_IDENTITY_FIELD
from src.paper.runtime_state import (
    RuntimeRecord,
    RuntimeStatePort,
    latest_marker,
    record_sort_key,
)
from src.paper.vocabulary import (
    INTERVAL_MS,
    GapReason,
    GapRecord,
    HealthState,
    RuntimeEventType,
    SourceTag,
    TaggedBar,
)

# Origin tag of a PAPER_GAP written by a restart (the supervisor and the pipeline use their own).
GAP_DETAIL_RESTART = "RESTART"

# How many closed bars of each interval the engine windows hold (structural, from the backtest).
WARMUP_BARS: Mapping[str, int] = {"1h": STRATEGY_WINDOW_BARS, "4h": CONTEXT_WINDOW_BARS}

_UNIX_ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)

Pair = tuple[str, str]


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC-aware")


def _ms(moment: datetime) -> int:
    return (moment - _UNIX_ORIGIN) // _ONE_MS


def _gap_time(record: RuntimeRecord) -> datetime | None:
    raw = record.payload.get("expected_close_utc")
    if not isinstance(raw, str):
        return None
    return datetime.fromisoformat(raw)


# --------------------------------------------------------------------------- #
# Restore.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RestoredState:
    """What the state port remembers about the epoch before this run started.

    `previous_marker` is the last RUNTIME_START or RUNTIME_STOP strictly before this run's own
    start. `recorded_gaps` are the (symbol, interval, expected close) keys that already have a
    PAPER_GAP, so a repeated restart never writes the same close twice with another reason.
    """

    epoch_id: str
    last_closes: Mapping[Pair, datetime]
    previous_marker: RuntimeRecord | None
    recorded_gaps: frozenset[tuple[str, str, datetime]]

    @property
    def downtime_reason(self) -> GapReason:
        """PLANNED_RESTART when a RUNTIME_STOP closed the previous run, otherwise CRASH."""
        marker = self.previous_marker
        if marker is not None and marker.event_type is RuntimeEventType.RUNTIME_STOP:
            return GapReason.PLANNED_RESTART
        return GapReason.CRASH


def restore_runtime(
    state: RuntimeStatePort, epoch_id: str, *, current_start_utc: datetime | None = None
) -> RestoredState:
    """Read the epoch's last closes, previous run marker and recorded gaps from the port.

    `current_start_utc` is the time of this run's own RUNTIME_START: markers at or after it belong
    to this run (or to a replay of it) and are not the previous run.
    """
    closes = dict(state.last_close_by_pair(epoch_id))
    markers = state.records(
        epoch_id, {RuntimeEventType.RUNTIME_START, RuntimeEventType.RUNTIME_STOP}
    )
    if current_start_utc is not None:
        markers = [m for m in markers if m.occurred_at_utc < current_start_utc]
    recorded: set[tuple[str, str, datetime]] = set()
    for gap in state.records(epoch_id, {RuntimeEventType.PAPER_GAP}):
        expected = _gap_time(gap)
        if gap.symbol is not None and gap.interval is not None and expected is not None:
            recorded.add((gap.symbol, gap.interval, expected))
    return RestoredState(
        epoch_id=epoch_id,
        last_closes=closes,
        previous_marker=latest_marker(markers),
        recorded_gaps=frozenset(recorded),
    )


# --------------------------------------------------------------------------- #
# Downtime gaps.
# --------------------------------------------------------------------------- #


def downtime_gaps(
    restored: RestoredState,
    *,
    now_utc: datetime,
    symbols: Sequence[str],
    intervals: Sequence[str],
    warm: WarmUp | None = None,
) -> tuple[GapRecord, ...]:
    """One gap per close that is due after each pair's last processed close, up to `now_utc`.

    The closes come from the exchange grid (close = open + interval - 1 ms). The reason is
    PLANNED_RESTART or CRASH (the previous run's end), except for a close the REST warm-up asked
    for and the exchange did not return: that is EXCHANGE_NO_CANDLE, so each expected close has
    exactly one record or one explained gap. A close older than the requested window cannot be
    judged and keeps the restart reason. A pair with no processed bar has no recorded baseline and
    yields no gap: nothing was expected from a feed that never delivered. A close that already
    has a gap record is skipped (first writer wins), so a repeated restart never rewrites one.
    """
    _require_utc("now_utc", now_utc)
    reason = restored.downtime_reason
    gaps: list[GapRecord] = []
    for symbol in symbols:
        for interval in intervals:
            last = restored.last_closes.get((symbol, interval))
            if last is None:
                continue
            step = timedelta(milliseconds=INTERVAL_MS[interval])
            for close in expected_close_times(last, now_utc, interval):
                if (symbol, interval, close) in restored.recorded_gaps:
                    continue
                gap_reason = reason
                if warm is not None and warm.is_exchange_hole(
                    symbol, interval, close + _ONE_MS - step
                ):
                    gap_reason = GapReason.EXCHANGE_NO_CANDLE
                gaps.append(
                    GapRecord(
                        symbol=symbol,
                        interval=interval,
                        expected_close_utc=close,
                        reason=gap_reason,
                        detected_at_utc=now_utc,
                    )
                )
    return tuple(sorted(gaps, key=lambda g: (g.expected_close_utc, g.symbol, g.interval)))


def restart_gap_record(epoch_id: str, gap: GapRecord) -> RuntimeRecord:
    """The PAPER_GAP record of a downtime gap, keyed on the expected close (replay-safe)."""
    return RuntimeRecord(
        event_type=RuntimeEventType.PAPER_GAP,
        epoch_id=epoch_id,
        occurred_at_utc=gap.detected_at_utc,
        symbol=gap.symbol,
        interval=gap.interval,
        payload={
            "expected_close_utc": gap.expected_close_utc,
            "reason": gap.reason.value,
            "source": GAP_DETAIL_RESTART,
        },
    )


def health_record(
    epoch_id: str, state: HealthState, at: datetime, reason: GapReason | None = None
) -> RuntimeRecord:
    """A HEALTH_STATE_CHANGED record, read by `derive_health_intervals` (plan 16-15)."""
    payload: dict[str, str] = {"state": state.value}
    if reason is not None:
        payload["reason"] = reason.value
    return RuntimeRecord(
        event_type=RuntimeEventType.HEALTH_STATE_CHANGED,
        epoch_id=epoch_id,
        occurred_at_utc=at,
        payload=payload,
    )


# --------------------------------------------------------------------------- #
# REST warm-up.
# --------------------------------------------------------------------------- #


class KlinesLike(Protocol):
    """The credential-free public adapter surface the warm-up needs."""

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]: ...


@dataclass(frozen=True)
class WarmUp:
    """The REST snapshot that rebuilds the engine windows.

    `bars` are tagged REST_WARMUP (history only, never evaluated, never recorded);
    `newest_close` is the newest closed bar of each pair, the seed of the supervisor cursor;
    `requested_first_open` is the first open time the request asked for and `returned_opens` the
    open times of the closed bars the exchange returned, per pair (they classify exchange holes).
    """

    snapshot_utc: datetime
    bars: tuple[TaggedBar, ...]
    newest_close: Mapping[Pair, datetime]
    requested_first_open: Mapping[Pair, datetime]
    returned_opens: Mapping[Pair, frozenset[datetime]]

    def is_exchange_hole(self, symbol: str, interval: str, open_time: datetime) -> bool:
        """True when the request covered this open time and the exchange did not return it."""
        first = self.requested_first_open.get((symbol, interval))
        if first is None or open_time < first:
            return False
        return open_time not in self.returned_opens.get((symbol, interval), frozenset())


async def warm_up(
    public: KlinesLike,
    symbols: Sequence[str],
    intervals: Sequence[str],
    now_utc: datetime,
) -> WarmUp:
    """Fetch exactly the engine windows of closed bars for every (symbol, interval)."""
    _require_utc("now_utc", now_utc)
    bars: list[TaggedBar] = []
    newest: dict[Pair, datetime] = {}
    first_open: dict[Pair, datetime] = {}
    returned: dict[Pair, frozenset[datetime]] = {}
    now_ms = _ms(now_utc)
    for symbol in symbols:
        for interval in intervals:
            size = WARMUP_BARS.get(interval)
            if size is None:
                raise ValueError(f"no engine window for interval {interval!r}")
            step_ms = INTERVAL_MS[interval]
            # The newest grid open whose close (open + interval - 1 ms) is not after `now_utc`.
            newest_open_ms = ((now_ms + 1 - step_ms) // step_ms) * step_ms
            start_ms = newest_open_ms - (size - 1) * step_ms
            rows = await public.klines(symbol, interval, start_ms=start_ms, limit=size + 1)
            closed = sorted(
                (k for k in rows if k.close_time_utc <= now_utc), key=lambda k: k.close_time_utc
            )[-size:]
            for kline in closed:
                bars.append(
                    TaggedBar(
                        symbol=symbol,
                        interval=interval,
                        open_time_utc=kline.open_time_utc,
                        close_time_utc=kline.close_time_utc,
                        open=kline.open,
                        high=kline.high,
                        low=kline.low,
                        close=kline.close,
                        volume=kline.volume,
                        source=SourceTag.REST_WARMUP,
                    )
                )
            first_open[(symbol, interval)] = _UNIX_ORIGIN + timedelta(milliseconds=start_ms)
            returned[(symbol, interval)] = frozenset(k.open_time_utc for k in closed)
            if closed:
                newest[(symbol, interval)] = closed[-1].close_time_utc
    return WarmUp(
        snapshot_utc=now_utc,
        bars=tuple(bars),
        newest_close=newest,
        requested_first_open=first_open,
        returned_opens=returned,
    )


def supervisor_cursors(
    restored: RestoredState,
    warm: WarmUp,
    *,
    symbols: Sequence[str],
    intervals: Sequence[str],
) -> dict[Pair, datetime]:
    """The close the supervisor resumes each pair from.

    The newest close of the warm-up snapshot (the downtime closes are already gaps); a pair the
    exchange returned nothing for falls back to its restored last processed close, so a bar
    processed before the stop is never delivered again and a reconnect still has a cursor. The
    cursor never moves behind a processed close.
    """
    out: dict[Pair, datetime] = {}
    for symbol in symbols:
        for interval in intervals:
            pair = (symbol, interval)
            known = [
                close
                for close in (warm.newest_close.get(pair), restored.last_closes.get(pair))
                if close is not None
            ]
            if known:
                out[pair] = max(known)
    return out


@dataclass(frozen=True)
class RestartPlan:
    """Everything a restart decided before the first subscription (see the module docstring).

    `started_at_utc` is this run's RUNTIME_START time and `snapshot_utc` the warm-up snapshot time;
    the restart fence is the snapshot time.
    """

    started_at_utc: datetime
    snapshot_utc: datetime
    restored: RestoredState
    warm: WarmUp
    gaps: tuple[GapRecord, ...]


# --------------------------------------------------------------------------- #
# Epoch consistency.
# --------------------------------------------------------------------------- #


class EpochMismatch(Exception):
    """The pinned state file and the stored EPOCH_PINNED record do not agree (fail closed)."""


class PinnedLike(Protocol):
    """The identity of the pinned epoch (`StreamEpoch`)."""

    @property
    def epoch_id(self) -> str: ...

    @property
    def strategy_id(self) -> str: ...

    @property
    def parameter_set_id(self) -> str: ...

    @property
    def parameter_set_hash(self) -> str: ...

    @property
    def opened_at_utc(self) -> datetime: ...


def check_epoch_consistency(
    pinned: PinnedLike, state: RuntimeStatePort, *, config_identity: str
) -> None:
    """A restart never mints an epoch: the pin file must be the latest pin across ALL epochs.

    Raises `EpochMismatch` when the latest EPOCH_PINNED record of the whole runtime state belongs
    to another epoch than the pin file, or when two epochs share the latest pin instant (REV-18:
    a new pin starts a new trial, so a superseded pin must not resume). The epoch-scoped
    comparison follows: the state port must hold an EPOCH_PINNED record for the pinned epoch, and
    the latest one must agree in strategy, parameter set, hash and opening time.

    `config_identity` is the identity of the effective configuration of this start
    (`src.paper.runtime_config.config_identity`, plan 16-57, owner decision 16-DEC-CONFIG-PIN).
    The pin record must carry the same value: a changed effective value, or a pin record with no
    identity, is an `EpochMismatch` (exit 6, held under `--hold-on-refusal`). A changed value needs
    a new pin, which starts a new qualifying trial (REV-07, REV-18). The raw file hash the records
    also carry is provenance only and is never compared.
    """
    latest_pins = state.latest_epoch_pins()
    foreign = sorted({p.epoch_id for p in latest_pins if p.epoch_id != pinned.epoch_id})
    if foreign:
        shared = len(latest_pins) > 1 and any(p.epoch_id == pinned.epoch_id for p in latest_pins)
        raise EpochMismatch(
            (
                "two epochs share the latest EPOCH_PINNED instant"
                if shared
                else "the latest EPOCH_PINNED record belongs to another epoch"
            )
            + f" ({', '.join(foreign)}); the pinned state is superseded"
            " (REV-18: a new pin starts a new trial)"
        )
    pins = state.records(pinned.epoch_id, {RuntimeEventType.EPOCH_PINNED})
    if not pins:
        raise EpochMismatch("no EPOCH_PINNED record for the pinned epoch in the runtime state")
    latest = max(pins, key=record_sort_key)
    differing = [
        name
        for name, expected in (
            ("strategy_id", pinned.strategy_id),
            ("parameter_set_id", pinned.parameter_set_id),
            ("parameter_set_hash", pinned.parameter_set_hash),
        )
        if latest.payload.get(name) != expected
    ]
    if latest.occurred_at_utc != pinned.opened_at_utc:
        differing.append("opened_at_utc")
    if differing:
        raise EpochMismatch(
            "the latest EPOCH_PINNED record differs from the pinned state in: "
            + ", ".join(differing)
        )
    recorded = latest.payload.get(CONFIG_IDENTITY_FIELD)
    if not isinstance(recorded, str) or recorded == "":
        raise EpochMismatch(
            "the EPOCH_PINNED record carries no configuration identity: the effective "
            "configuration of this start cannot be compared with the pin (16-DEC-CONFIG-PIN); "
            "a new pin starts a new trial"
        )
    if recorded != config_identity:
        raise EpochMismatch(
            "the effective runtime configuration differs from the configuration the epoch was "
            f"pinned with (configuration identity {config_identity[:12]} != pinned "
            f"{recorded[:12]}): a changed value needs a new pin and a new trial "
            "(16-DEC-CONFIG-PIN, REV-07)"
        )


# --------------------------------------------------------------------------- #
# The restart fence.
# --------------------------------------------------------------------------- #


def apply_restart_fence(bar: TaggedBar, fence_utc: datetime) -> TaggedBar:
    """History only for any non-live bar at or before the fence (L-11, D-06).

    A closed LIVE_WS bar is never touched. Any other bar (a REST backfill) whose close is at or
    before the warm-up snapshot closed while the process was down, or before it could listen; it
    only extends history, whatever evaluation rule the pipeline applies to backfilled bars.
    """
    if bar.source is SourceTag.LIVE_WS or bar.close_time_utc > fence_utc:
        return bar
    if bar.source is SourceTag.REST_WARMUP:
        return bar
    return replace(bar, source=SourceTag.REST_WARMUP)


__all__ = [
    "GAP_DETAIL_RESTART",
    "WARMUP_BARS",
    "EpochMismatch",
    "KlinesLike",
    "PinnedLike",
    "RestartPlan",
    "RestoredState",
    "WarmUp",
    "apply_restart_fence",
    "check_epoch_consistency",
    "downtime_gaps",
    "health_record",
    "restart_gap_record",
    "restore_runtime",
    "supervisor_cursors",
    "warm_up",
]
