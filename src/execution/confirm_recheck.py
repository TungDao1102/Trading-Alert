"""CONFIRM-time re-run of the Phase 19 pre-placement checks (Phase 23, plan 23-05; D-11).

The confirm core (`src/paper/shadow_confirm.py`) is synchronous, runs under its lock and imports
no exchange code (D-09, D-11). The fresh mark price, last price and position mode are async
reads (Phase 24). The split is therefore:

1. the composition awaits the fresh reads, builds a `ConfirmInputs` and `put`s it into a
   `PrefetchedConfirmInputs` holder under the trade plan id, then calls the core's
   `handle_confirm`;
2. the core calls the ONE synchronous callable built by `make_confirm_recheck` under its lock;
3. the callable `take`s the snapshot (single use: one snapshot serves one CONFIRM, never two) and
   runs the existing Phase 19 checks, `evaluate_pre_placement` and then `check_position_mode`,
   in their fixed order. Nothing is re-implemented here and `pre_placement.py` is unchanged.

Fail closed (D058): no snapshot is `CONFIRM_INPUTS_UNAVAILABLE`; a snapshot for another plan
hash, symbol or side is `CONFIRM_INPUTS_MISMATCH`; an unknown position-mode string raises
`ValueError` (the core turns any raise into RECHECK_ERROR).

Time. The snapshot was fetched before the press, so `prefetched_provider` rebinds the checks'
clock to the press instant `now_utc`: the remaining-validity check and the price-age checks are
evaluated at the CONFIRM instant, so a snapshot fetched earlier cannot pass a plan that has since
run out of validity or a price that has since gone stale. The checked-at instants of the two
prices are moved forward to `now_utc` and never backwards: a press instant earlier than the fetch
instant must not make a reading look fresher than it was. No clock is read here.

The module imports only stdlib, `src.domain` and `src.execution.pre_placement`; it logs nothing.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.pre_placement import (
    PrePlacementInputs,
    check_position_mode,
    evaluate_pre_placement,
)

# Plain-string codes (GLOSSARY section 9.3 rows are added by plan 23-13).
CONFIRM_INPUTS_UNAVAILABLE = "CONFIRM_INPUTS_UNAVAILABLE"
CONFIRM_INPUTS_MISMATCH = "CONFIRM_INPUTS_MISMATCH"


@dataclass(frozen=True)
class ConfirmInputs:
    """The pre-fetched readings for one CONFIRM: the Phase 19 inputs plus the position mode."""

    pre_placement: PrePlacementInputs
    position_mode: str


class PrefetchedConfirmInputs:
    """Thread-safe, single-use holder of one `ConfirmInputs` per trade plan id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, ConfirmInputs] = {}

    def put(self, trade_plan_id: str, inputs: ConfirmInputs) -> None:
        """Store the snapshot for the plan; a later `put` replaces an unused earlier one."""
        with self._lock:
            self._items[trade_plan_id] = inputs

    def take(self, trade_plan_id: str) -> ConfirmInputs | None:
        """Remove and return the snapshot, or None when there is none (single use)."""
        with self._lock:
            return self._items.pop(trade_plan_id, None)


ConfirmInputsProvider = Callable[[Signal, TradePlan, datetime], ConfirmInputs | None]
ConfirmRecheck = Callable[[Signal, TradePlan, datetime], str | None]


def _later(checked_at: datetime | None, now_utc: datetime) -> datetime | None:
    """Move a checked-at instant forward to the press instant, never backwards."""
    if checked_at is None:
        return None
    return max(checked_at, now_utc)


def prefetched_provider(holder: PrefetchedConfirmInputs) -> ConfirmInputsProvider:
    """A provider that takes the plan's snapshot and rebinds its clock to the press instant."""

    def provide(signal: Signal, plan: TradePlan, now_utc: datetime) -> ConfirmInputs | None:
        del signal
        snapshot = holder.take(plan.trade_plan_id)
        if snapshot is None:
            return None
        pre = snapshot.pre_placement
        rebound = dataclasses.replace(
            pre,
            now_utc=now_utc,
            mark_checked_at_utc=_later(pre.mark_checked_at_utc, now_utc),
            last_checked_at_utc=_later(pre.last_checked_at_utc, now_utc),
        )
        return ConfirmInputs(pre_placement=rebound, position_mode=snapshot.position_mode)

    return provide


def make_confirm_recheck(provider: ConfirmInputsProvider) -> ConfirmRecheck:
    """The synchronous recheck the confirm core injects: reason code, or None to pass."""

    def recheck(signal: Signal, plan: TradePlan, now_utc: datetime) -> str | None:
        snapshot = provider(signal, plan, now_utc)
        if snapshot is None:
            return CONFIRM_INPUTS_UNAVAILABLE
        pre = snapshot.pre_placement
        if (
            pre.trade_plan.plan_hash != plan.plan_hash
            or pre.symbol != signal.symbol
            or pre.side != signal.direction
        ):
            return CONFIRM_INPUTS_MISMATCH
        reason = evaluate_pre_placement(pre)
        if reason is not None:
            return reason
        return check_position_mode(snapshot.position_mode)

    return recheck
