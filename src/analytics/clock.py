"""Research-clock arithmetic for the kill gate (Phase 10, plan 10-05, D-03, D013/D030).

Pure calendar-month arithmetic over UTC-aware datetimes. The 6-month boundary is exact
and inclusive: a moment is eligible iff `evaluated_at >= add_months(start, 6)`, with the
day clamped to the last day of the target month (2026-01-31 + 1 month = 2026-02-28).

No wall-clock reads: every instant is an injected argument (D-01).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.analytics.family import KillGateInputError
from src.domain.canonical import sha256_hex

REQUIRED_MONTHS = 6

# The exact `grep -E` regex of the research-gate CI (.github/workflows/research-gate.yml,
# Witness 1) with the date wrapped in one capture group. A test extracts the CI text and
# asserts identity, so the clock start is what CI reads (T-10-23).
FROZEN_ON_PATTERN = re.compile(
    r"^>\s*\*\*Frozen on:\*\*\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.MULTILINE
)

# Freeze-commit provenance, verified from git at plan time (D-03: not assumed):
#   git show -s --format=%H%n%aI 281ccd0
PROTOCOL_FREEZE_COMMIT = "281ccd0894ea35717cc741788b6133cfb202af82"
PROTOCOL_FREEZE_COMMIT_AUTHOR_DATE = "2026-09-19T14:08:12+07:00"
PROTOCOL_CLOCK_SOURCE = "docs/research/RESEARCH_PROTOCOL.md header: Frozen on"

_ONE_DAY = timedelta(days=1)


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC-aware datetime")


def add_months(dt: datetime, months: int) -> datetime:
    """Add whole calendar months, clamping the day to the target month's last day.

    Time of day and tzinfo are preserved. `months` must be >= 0.
    """
    if months < 0:
        raise ValueError("months must be >= 0")
    total = dt.year * 12 + (dt.month - 1) + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start: datetime, end: datetime) -> int:
    """Largest m >= 0 with `add_months(start, m) <= end` (0 when `end` precedes `start`)."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    while months > 0 and add_months(start, months) > end:
        months -= 1
    while add_months(start, months + 1) <= end:
        months += 1
    return months


def extra_days_after(start: datetime, end: datetime, whole_months: int) -> int:
    """Whole days from `add_months(start, whole_months)` to `end` (never negative)."""
    delta = end - add_months(start, whole_months)
    return max(0, delta // _ONE_DAY)


def earliest_terminal_utc(start: datetime) -> datetime:
    """The first instant the months budget is met: `start` + REQUIRED_MONTHS calendar months."""
    return add_months(start, REQUIRED_MONTHS)


@dataclass(frozen=True)
class ClockStart:
    """Research-clock provenance (D030: the protocol's Frozen-on date is the clock start)."""

    start_utc: datetime
    source: str
    freeze_commit: str
    commit_author_date: str

    def __post_init__(self) -> None:
        _require_utc(self.start_utc, "start_utc")
        for name in ("source", "freeze_commit", "commit_author_date"):
            value = getattr(self, name)
            if not isinstance(value, str) or value.strip() == "":
                raise ValueError(f"{name} must be a non-empty string")

    def as_payload(self) -> dict[str, str]:
        """Allow-listed, JSON-safe provenance fields."""
        return {
            "start_utc": self.start_utc.isoformat(),
            "source": self.source,
            "freeze_commit": self.freeze_commit,
            "commit_author_date": self.commit_author_date,
        }

    def digest(self) -> str:
        return sha256_hex(self.as_payload())


def parse_frozen_on(protocol_text: str) -> datetime:
    """Parse the protocol header's Frozen-on date as 00:00Z of that day (pure, no I/O).

    Raises `KillGateInputError` when the line is absent or the date is impossible.
    """
    match = FROZEN_ON_PATTERN.search(protocol_text)
    if match is None:
        raise KillGateInputError("protocol text has no 'Frozen on' header line")
    try:
        return datetime.fromisoformat(match.group(1)).replace(tzinfo=UTC)
    except ValueError as exc:
        raise KillGateInputError(f"invalid Frozen-on date: {match.group(1)}") from exc


def clock_start_from_protocol(
    protocol_text: str,
    *,
    freeze_commit: str = PROTOCOL_FREEZE_COMMIT,
    commit_author_date: str = PROTOCOL_FREEZE_COMMIT_AUTHOR_DATE,
) -> ClockStart:
    """Research-clock start from the frozen protocol header, with freeze-commit provenance."""
    return ClockStart(
        start_utc=parse_frozen_on(protocol_text),
        source=PROTOCOL_CLOCK_SOURCE,
        freeze_commit=freeze_commit,
        commit_author_date=commit_author_date,
    )
