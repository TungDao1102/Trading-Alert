"""RED skeleton for plan 14-03 (replaced by the GREEN implementation in the next commit)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.backtest.series import MinuteSource


@dataclass(frozen=True)
class FundingRow:
    symbol: str
    funding_time_utc: datetime
    funding_rate: Decimal
    mark_price: Decimal | None


def parse_funding_row(row: Mapping[str, Any]) -> FundingRow:
    return FundingRow(
        symbol=str(row["symbol"]),
        funding_time_utc=row["funding_time_utc"],
        funding_rate=Decimal(str(row["funding_rate"])),
        mark_price=Decimal(str(row["mark_price"])) if row["mark_price"] else None,
    )


@dataclass(frozen=True)
class OpenSegment:
    start_utc: datetime
    end_utc: datetime
    quantity: Decimal


@dataclass(frozen=True)
class FundingEvent:
    symbol: str
    funding_time_utc: datetime
    funding_rate: Decimal
    mark_price: Decimal
    quantity: Decimal
    amount: Decimal
    mark_from_kline: bool


@dataclass(frozen=True)
class FundingResult:
    events: tuple[FundingEvent, ...]
    total: Decimal
    used_allowed_gaps: tuple[object, ...]


def funding_pnl(
    *, direction: str, quantity: Decimal, mark_price: Decimal, funding_rate: Decimal
) -> Decimal:
    return Decimal("0")


def funding_events(
    *,
    symbol: str,
    direction: str,
    segments: Sequence[OpenSegment],
    rows: Sequence[FundingRow],
    mark_source: MinuteSource,
    allowed_gaps: Sequence[object],
    loaded_start_utc: datetime,
    loaded_end_utc: datetime,
) -> FundingResult:
    return FundingResult(events=(), total=Decimal("0"), used_allowed_gaps=())
