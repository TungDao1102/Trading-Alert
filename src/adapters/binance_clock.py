"""Server-time drift: the pure decision and the entry-blocking guard (plan 18-07, D-14).

The drift is host minus Binance, measured as the midpoint of two injected host-clock readings
around one server-time request, so request latency does not masquerade as drift; half the
round trip (rounded up) is the measurement uncertainty. Positive: the host clock is ahead.

Fail closed: ``ClockDriftGuard`` allows new entries only on a fresh, successful, in-limit
verdict. Never measured, a failed measurement, an out-of-limit offset or a stale verdict each
block new entries. Nothing here reads a clock: every time is an argument.

No number lives here: every limit comes from ``DriftLimits`` (``src/adapters/binance_limits``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from src.adapters.binance_limits import DriftLimits


def _is_strict_int(value: object) -> bool:
    return type(value) is int


def _is_aware(moment: object) -> bool:
    return (
        isinstance(moment, datetime)
        and moment.tzinfo is not None
        and moment.utcoffset() is not None
    )


@dataclass(frozen=True, kw_only=True)
class DriftVerdict:
    """One drift measurement and its decision.

    A successful verdict carries ``offset_ms`` and ``uncertainty_ms``; a failed one carries
    neither, is never within limits, and records only the exception TYPE NAME (or a fixed
    reason word) in ``failure_type``. ``measured_at_utc`` is the injected time of the
    measurement; the guard refuses a verdict without one.
    """

    offset_ms: int | None
    uncertainty_ms: int | None
    within_limits: bool
    measurement_failed: bool
    measured_at_utc: datetime | None
    failure_type: str | None

    def __post_init__(self) -> None:
        if self.measured_at_utc is not None and not _is_aware(self.measured_at_utc):
            raise ValueError("DriftVerdict.measured_at_utc must be an aware datetime or None")
        if self.measurement_failed:
            if self.within_limits:
                raise ValueError("a failed DriftVerdict is never within limits")
            if self.offset_ms is not None or self.uncertainty_ms is not None:
                raise ValueError("a failed DriftVerdict carries no offset and no uncertainty")
            if not isinstance(self.failure_type, str) or not self.failure_type:
                raise ValueError("a failed DriftVerdict names its failure_type")
            return
        if not _is_strict_int(self.offset_ms) or not _is_strict_int(self.uncertainty_ms):
            raise ValueError("a successful DriftVerdict carries int offset_ms and uncertainty_ms")
        if self.failure_type is not None:
            raise ValueError("a successful DriftVerdict has no failure_type")
        if type(self.within_limits) is not bool:
            raise ValueError("DriftVerdict.within_limits must be a bool")

    @classmethod
    def failed(cls, *, failure_type: str, measured_at_utc: datetime | None) -> DriftVerdict:
        """A failed measurement: blocks new entries (fail closed)."""
        return cls(
            offset_ms=None,
            uncertainty_ms=None,
            within_limits=False,
            measurement_failed=True,
            measured_at_utc=measured_at_utc,
            failure_type=failure_type,
        )


def evaluate_clock_drift(
    *,
    before_ms: int,
    server_ms: int,
    after_ms: int,
    limits: DriftLimits,
    measured_at_utc: datetime | None = None,
) -> DriftVerdict:
    """The pure drift decision for one measurement (no clock read).

    ``offset_ms`` = midpoint of ``before_ms`` and ``after_ms`` (floored) minus ``server_ms``;
    ``uncertainty_ms`` = half the round trip rounded up. Within limits exactly when
    ``offset (+ uncertainty) <= ahead_limit_ms`` and ``-offset (+ uncertainty) <=
    behind_limit_ms``, the uncertainty added only when ``include_measurement_uncertainty``.

    Raises:
        ValueError: a reading is not an int (or is a bool), or ``after_ms < before_ms``, or
            ``measured_at_utc`` is naive.
        TypeError: ``limits`` is not a ``DriftLimits``.
    """
    for name, value in (("before_ms", before_ms), ("server_ms", server_ms), ("after_ms", after_ms)):
        if not _is_strict_int(value):
            raise ValueError(f"{name} must be an int (not a bool)")
    if not isinstance(limits, DriftLimits):
        raise TypeError("limits must be a DriftLimits")
    if after_ms < before_ms:
        raise ValueError("after_ms is earlier than before_ms (the host clock went backwards)")
    if measured_at_utc is not None and not _is_aware(measured_at_utc):
        raise ValueError("measured_at_utc must be an aware datetime")
    round_trip = after_ms - before_ms
    midpoint = before_ms + round_trip // 2
    uncertainty = (round_trip + 1) // 2
    offset = midpoint - server_ms
    margin = uncertainty if limits.include_measurement_uncertainty else 0
    within = offset + margin <= limits.ahead_limit_ms and -offset + margin <= limits.behind_limit_ms
    return DriftVerdict(
        offset_ms=offset,
        uncertainty_ms=uncertainty,
        within_limits=within,
        measurement_failed=False,
        measured_at_utc=measured_at_utc,
        failure_type=None,
    )


class DriftBlockReason(StrEnum):
    """Why ``ClockDriftGuard`` blocks new entries."""

    NEVER_MEASURED = "NEVER_MEASURED"
    MEASUREMENT_FAILED = "MEASUREMENT_FAILED"
    OUT_OF_LIMITS = "OUT_OF_LIMITS"
    STALE = "STALE"


class ClockDriftGuard:
    """Holds the last drift verdict and decides whether new entries are allowed (fail closed).

    Only new entries are gated; protective orders, cancels and reads never consult this guard
    (plan 18-13). The guard keeps no clock of its own: every query takes ``now_utc``.
    """

    def __init__(self, *, limits: DriftLimits) -> None:
        if not isinstance(limits, DriftLimits):
            raise TypeError("limits must be a DriftLimits")
        self._limits = limits
        self._last: DriftVerdict | None = None

    @property
    def limits(self) -> DriftLimits:
        return self._limits

    @property
    def last_verdict(self) -> DriftVerdict | None:
        return self._last

    def record(self, verdict: DriftVerdict) -> None:
        """Store a verdict; it replaces the previous one (a failed verdict included)."""
        if not isinstance(verdict, DriftVerdict):
            raise TypeError("verdict must be a DriftVerdict")
        if verdict.measured_at_utc is None:
            raise ValueError("the guard needs a verdict with measured_at_utc")
        self._last = verdict

    def blocked_reason(self, now_utc: datetime) -> DriftBlockReason | None:
        """The reason new entries are blocked at ``now_utc``, or None when they are allowed."""
        if not _is_aware(now_utc):
            raise ValueError("now_utc must be an aware datetime")
        last = self._last
        if last is None:
            return DriftBlockReason.NEVER_MEASURED
        if last.measurement_failed:
            return DriftBlockReason.MEASUREMENT_FAILED
        if not last.within_limits:
            return DriftBlockReason.OUT_OF_LIMITS
        if last.measured_at_utc is None:  # pragma: no cover - record() refuses it
            return DriftBlockReason.STALE
        age = now_utc - last.measured_at_utc
        if age < timedelta(0) or age > timedelta(seconds=self._limits.max_measurement_age_seconds):
            return DriftBlockReason.STALE
        return None

    def entries_allowed(self, now_utc: datetime) -> bool:
        """True only for a fresh, successful, in-limit verdict."""
        return self.blocked_reason(now_utc) is None


__all__ = [
    "ClockDriftGuard",
    "DriftBlockReason",
    "DriftVerdict",
    "evaluate_clock_drift",
]
