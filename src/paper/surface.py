"""Non-semantic decision-surface observer (Phase 16, plan 16-10, D-20, L-02).

`decision_surface` replays a recorded sequence of closed bars through the shared decision chain
and returns one `DecisionSurfaceRecord` per closed 1h bar: the bar, a digest of the last-bar
feature frame, the signal id or the NO_TRADE reason, the plan hash and the risk verdict. It is
the parity evidence for the decision logic itself, including the strategy-stage NO_TRADE and
signal-less bars the trade-level parity test cannot see (G2-008). Two runs over the same recorded
bars give the same `surface_digest`, whatever the arrival order (tolerance zero, D061).

It is an observer, not a second engine. Every decision comes from the same functions the paper
tick and the backtest call: `src.paper.loop.evaluate_closed_bar` (which runs `src.core` evaluate,
plan and `src.risk` evaluate_risk) and `src.core.features.compute_features`. The windows and the
4h-before-1h ordering come from `src.paper.bars`, which takes the windows from the engine
constants. The module imports nothing from `src.backtest.engine`, `simulator` or `lifecycle` and
changes none of their hashes (L-02). Stdlib, Decimal and project core types only; no float.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core.features import compute_features
from src.core.types import Candle
from src.domain.canonical import sha256_hex
from src.paper.bars import CONTEXT_INTERVAL, SETUP_INTERVAL, BarBuffers, group_by_close
from src.paper.loop import (
    BAR_STAGES,
    BarContext,
    BarOutcome,
    check_feature_validity,
    evaluate_closed_bar,
)

SURFACE_SCHEMA = "decision-surface/1"

# Stages a record can carry: the per-bar chain stages plus the two the observer adds.
STAGE_FEED_GATE = "feed_gate"
STAGE_CONTEXT = "context"
SURFACE_STAGES: tuple[str, ...] = (*BAR_STAGES, STAGE_FEED_GATE, STAGE_CONTEXT)

REASON_CONTEXT_BAR = "CONTEXT_BAR"
REASON_DUPLICATE_BAR = "DUPLICATE_BAR"


@dataclass(frozen=True)
class DecisionSurfaceRecord:
    """One observed bar: what the shared chain decided and a digest of what it looked at.

    `feature_digest` is the SHA-256 of the canonical JSON of the last-bar `FeatureFrame`; it is
    None where no features were computed (context bars, feed-gate rejections). `signal_id`,
    `plan_hash`, `risk_reason` and `sized_quantity` are set as far as the chain got.
    """

    symbol: str
    interval: str
    bar_close_utc: datetime
    stage: str
    reason_code: str
    feature_digest: str | None = None
    signal_id: str | None = None
    plan_hash: str | None = None
    risk_reason: str | None = None
    sized_quantity: Decimal | None = None
    regime: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in SURFACE_STAGES:
            raise ValueError(f"unknown stage {self.stage!r}; expected one of {SURFACE_STAGES}")
        if self.bar_close_utc.tzinfo is None or self.bar_close_utc.utcoffset() != timedelta(0):
            raise ValueError("bar_close_utc must be UTC-aware")
        if not self.reason_code:
            raise ValueError("reason_code must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        """Canonical-JSON-safe form (Decimal as text, datetime as ISO text)."""
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "bar_close_utc": self.bar_close_utc.isoformat(),
            "stage": self.stage,
            "reason_code": self.reason_code,
            "feature_digest": self.feature_digest,
            "signal_id": self.signal_id,
            "plan_hash": self.plan_hash,
            "risk_reason": self.risk_reason,
            "sized_quantity": None if self.sized_quantity is None else str(self.sized_quantity),
            "regime": self.regime,
        }


def surface_digest(records: Iterable[DecisionSurfaceRecord]) -> str:
    """SHA-256 over the canonical JSON of the records, in order (tolerance zero)."""
    return sha256_hex(
        {"schema": SURFACE_SCHEMA, "records": [record.to_dict() for record in records]}
    )


def feature_digest(context: BarContext, symbol: str, setup_window: list[Candle]) -> str:
    """SHA-256 of the canonical JSON of the last-bar `FeatureFrame` of the setup window."""
    frame = compute_features(
        symbol=symbol,
        interval=SETUP_INTERVAL,
        candles=setup_window,
        parameter_set=context.parameter_set,
    )
    return sha256_hex({"frame": asdict(frame)})


def gate_record(candle: Candle, reason_code: str) -> DecisionSurfaceRecord:
    """The record of a bar a feed gate stopped before the chain (no features computed)."""
    return DecisionSurfaceRecord(
        symbol=candle.symbol,
        interval=candle.interval,
        bar_close_utc=candle.close_time_utc,
        stage=STAGE_FEED_GATE,
        reason_code=reason_code,
    )


def context_record(candle: Candle) -> DecisionSurfaceRecord:
    """The record of a 4h context bar: it extends the context window and decides nothing."""
    return DecisionSurfaceRecord(
        symbol=candle.symbol,
        interval=candle.interval,
        bar_close_utc=candle.close_time_utc,
        stage=STAGE_CONTEXT,
        reason_code=REASON_CONTEXT_BAR,
    )


def outcome_record(
    candle: Candle, outcome: BarOutcome, *, digest: str | None
) -> DecisionSurfaceRecord:
    """The record of a bar the chain evaluated: stage, reason and the ids it reached.

    This is the single mapping from a `BarOutcome` to a record; `decision_surface` (replay) and
    the runtime pipeline (live) both use it, so their digests are comparable with tolerance zero.
    """
    sized = None if outcome.verdict is None else outcome.verdict.sized
    return DecisionSurfaceRecord(
        symbol=candle.symbol,
        interval=candle.interval,
        bar_close_utc=candle.close_time_utc,
        stage=outcome.stage,
        reason_code=outcome.reason_code,
        feature_digest=digest,
        signal_id=None if outcome.signal is None else outcome.signal.signal_id,
        plan_hash=None if outcome.trade_plan is None else outcome.trade_plan.plan_hash,
        risk_reason=None if outcome.verdict is None else outcome.verdict.reason_code,
        sized_quantity=None if sized is None else sized.quantity,
        regime=outcome.regime,
    )


def observe_closed_bar(
    candle: Candle,
    setup_window: list[Candle],
    context_window: list[Candle],
    context: BarContext | Callable[[], BarContext],
) -> DecisionSurfaceRecord:
    """Observe ONE closed 1h bar over its two windows: the gate record or the outcome record.

    The order is the live one: the warm-up gate (`check_feature_validity`) runs first, and only a
    bar that passes it needs a context. `context` is a `BarContext`, or a zero-argument callable
    resolved only after the gate passed, so a gated bar never builds a context (plan 16-51: the
    live pipeline does not call its context factory for such a bar either). The context's symbol
    must match the bar's. Shared by `decision_surface` and the trial evaluator's parity replay;
    non-semantic (D-20): every decision comes from `evaluate_closed_bar`.
    """
    gate = check_feature_validity(setup_window[:-1], context_window)
    if gate is not None:
        return gate_record(candle, gate)
    bar_context = context() if callable(context) else context
    if bar_context.symbol != candle.symbol:
        raise ValueError(f"context symbol {bar_context.symbol!r} != bar symbol {candle.symbol!r}")
    digest = feature_digest(bar_context, candle.symbol, setup_window)
    outcome = evaluate_closed_bar(bar_context, candle, setup_window, context_window)
    return outcome_record(candle, outcome, digest=digest)


def decision_surface(
    bars: Iterable[Candle],
    *,
    context: BarContext | Callable[[Candle], BarContext],
    buffers_factory: Callable[[], BarBuffers] = BarBuffers,
) -> tuple[DecisionSurfaceRecord, ...]:
    """Replay recorded closed bars and observe the decision chain bar by bar.

    `bars` are closed 1h and 4h candles in any order; they are put in close order with 4h before
    1h at a shared close (`group_by_close`) and fed through the buffers the runtime uses. For
    each closed 1h bar the setup and context windows are cut by the buffers, the feed warm-up gate
    runs, and the rest of the chain runs through `evaluate_closed_bar`. A 4h bar yields a context
    record only. A bar whose open time was already seen yields a DUPLICATE_BAR record and is not
    evaluated; the same open time with different content raises `ValueError` (fail closed).

    `context` is a `BarContext`, or a callable returning the context for each 1h bar (the
    constraint snapshot, open positions and daily loss at that close). Its symbol must match the
    bar's. The callable is called only for a bar the warm-up gate lets through, as the live
    pipeline does (`observe_closed_bar`). `buffers_factory` builds the buffers; the default is the
    engine windows.
    """
    buffers = buffers_factory()
    seen: dict[tuple[str, str, datetime], Candle] = {}
    records: list[DecisionSurfaceRecord] = []

    for _, group in group_by_close(bars):
        for candle in group:
            key = (candle.symbol, candle.interval, candle.open_time_utc)
            stored = seen.get(key)
            if stored is not None:
                if stored != candle:
                    raise ValueError(
                        f"conflicting duplicate bar for {candle.symbol} {candle.interval} "
                        f"open {candle.open_time_utc.isoformat()}"
                    )
                records.append(gate_record(candle, REASON_DUPLICATE_BAR))
                continue
            seen[key] = candle
            buffers.add(candle)

            if candle.interval == CONTEXT_INTERVAL:
                records.append(context_record(candle))
                continue

            close = candle.close_time_utc
            setup_window = buffers.setup_window(candle.symbol, close)
            context_window = buffers.context_window(candle.symbol, close)
            resolved: BarContext | Callable[[], BarContext]
            if callable(context):
                # Bound now, called only if the warm-up gate lets the bar through.
                resolved = functools.partial(context, candle)
            else:
                resolved = context
            records.append(observe_closed_bar(candle, setup_window, context_window, resolved))
    return tuple(records)


__all__ = [
    "REASON_CONTEXT_BAR",
    "REASON_DUPLICATE_BAR",
    "STAGE_CONTEXT",
    "STAGE_FEED_GATE",
    "SURFACE_SCHEMA",
    "SURFACE_STAGES",
    "DecisionSurfaceRecord",
    "context_record",
    "decision_surface",
    "feature_digest",
    "gate_record",
    "observe_closed_bar",
    "outcome_record",
    "surface_digest",
]
