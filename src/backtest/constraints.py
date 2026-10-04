"""Point-in-time constraint selection skeleton (Phase 14, plan 14-05, RED stage).

Signatures only: behavior-less so the RED tests fail on assertions rather than on
imports. The real implementation lands in the GREEN commit of the same task.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.risk.types import ConstraintSnapshot


class ConstraintHistoryError(ValueError):
    """Skeleton error."""


@dataclass(frozen=True)
class ConstraintRow:
    """Skeleton row."""

    symbol: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    observed_at_utc: datetime


@dataclass(frozen=True)
class PitConstraint:
    """Skeleton selection result."""

    snapshot: ConstraintSnapshot
    observed_at_utc: datetime
    extrapolated: bool


@dataclass(frozen=True)
class ConstraintHistory:
    """Skeleton history."""

    rows: tuple[ConstraintRow, ...]

    @classmethod
    def from_rows(cls, rows: Iterable[ConstraintRow]) -> ConstraintHistory:
        return cls(rows=tuple(rows))


def parse_constraint_row(row: Mapping[str, Any]) -> ConstraintRow:
    return ConstraintRow(
        symbol=str(row["symbol"]),
        price_tick_size=Decimal(str(row["price_tick_size"])),
        quantity_step_size=Decimal(str(row["quantity_step_size"])),
        min_quantity=Decimal(str(row["min_quantity"])),
        min_notional=Decimal(str(row["min_notional"])),
        observed_at_utc=datetime.fromisoformat(str(row["metadata_observed_at_utc"])),
    )


def select_constraints(
    history: ConstraintHistory, *, symbol: str, bar_close_utc: datetime
) -> PitConstraint:
    first = history.rows[0]
    snapshot = ConstraintSnapshot(
        symbol=first.symbol,
        price_tick_size=first.price_tick_size,
        quantity_step_size=first.quantity_step_size,
        min_quantity=first.min_quantity,
        min_notional=first.min_notional,
        metadata_observed_at_utc=first.observed_at_utc,
    )
    return PitConstraint(
        snapshot=snapshot, observed_at_utc=first.observed_at_utc, extrapolated=False
    )
