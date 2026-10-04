"""Simulated ledger skeleton (Phase 14, plan 14-05, RED stage).

Signatures only: every function is behavior-less so the RED tests fail on
assertions rather than on imports. The real implementation lands in the GREEN
commit of the same task.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.domain.enums import DailyState

from .records import Booking


@dataclass(frozen=True)
class Ledger:
    """Skeleton ledger value object."""

    initial_equity: Decimal
    equity: Decimal
    thresholds: dict[str, Any]

    @classmethod
    def start(
        cls, *, equity: Decimal, parameter_set_params: dict[str, Any], at_utc: datetime
    ) -> Ledger:
        return cls(initial_equity=equity, equity=equity, thresholds=dict(parameter_set_params))


def apply_booking(ledger: Ledger, booking: Booking) -> Ledger:
    return ledger


def daily_loss_quote(ledger: Ledger) -> Decimal:
    return Decimal("0")


def daily_state(ledger: Ledger) -> DailyState:
    return DailyState.NORMAL


def cancel_resting_required(ledger: Ledger) -> bool:
    return False
