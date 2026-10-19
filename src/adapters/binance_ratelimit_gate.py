"""The one process-wide REST rate-limit gate (plan 18-10).

One instance per process, shared by every REST holder: `BinanceUsdmAdapter` (and the
`BinancePublicMarketData` it builds), `BinancePublicMarketData` used on its own, the listenKey
port (plan 18-14) and the probe adapter (plan 18-12). Every composition creates exactly one
(plans 18-13, 18-16, 18-17) and hands the same object to every holder.

Semantics are the user's record `.planning/phases/18-user-data-stream-error-taxonomy/
decisions/18-DEC-O-18-01.md` and its amendment of 2026-10-16:

* an HTTP 418 bans every REST call of the process for a valid Retry-After capped by
  `signed_calls.rate_limit_retry_after_cap_seconds`, otherwise for
  `signed_calls.rate_limit_418_no_retry_after_wait_seconds`;
* an HTTP 429 pauses every REST call of the process for a valid Retry-After capped the same
  way, otherwise for `signed_calls.rate_limit_429_no_retry_after_wait_seconds`;
* while either is active every REST call of every holder, of every call kind including
  placements, is refused before it is sent (`RateLimitBanActive`, `RateLimitPauseActive`);
  nothing is retried because of a 418 or a 429.

The lengths come from the `RateLimitPolicy` the gate holds, through `rate_limit_decision`
(`src/domain/exchange_errors.py`): no wait number exists in this module.

The end of a ban or of a pause proves nothing about an order, a cancel, a fill or a
protective stop. The gate opening sends no request, replays nothing and emits no recovery
signal; there is no method that clears a restriction, only the injected clock passing the end
time lifts it. The unresolved account state stays with reconciliation.

Known gap (Phase 18): the data jobs (backfill, universe freeze, collector), the Phase 16 paper
runtime and the scripts `paper_ws_smoke.py` and `shadow_rehearsal.py` do not hold this gate and
keep their existing rate-limit handling; gating them is left to the phases that compose those
processes.

Pure: standard library, `src.domain.exchange_errors` and the `RateLimitPolicy` type only. No
SDK import, no I/O, no wall clock (the clock is injected), no sleep, no float.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.adapters.binance_limits import RateLimitPolicy
from src.domain.exchange_errors import (
    ExchangeErrorCategory,
    PreSendRefusal,
    RateLimitDecision,
    rate_limit_decision,
)

IP_BAN_418 = "IP_BAN_418"
RATE_LIMIT_PAUSE_429 = "RATE_LIMIT_PAUSE_429"

_ONE_MICROSECOND = timedelta(microseconds=1)
_MICROSECONDS_PER_SECOND = 1_000_000


class RestGateRefusal(PreSendRefusal):  # noqa: N818 - a refusal, not an error of the caller
    """A REST call refused before it was sent because a ban or a pause is active.

    `reason` is `IP_BAN_418` or `RATE_LIMIT_PAUSE_429`; `retry_after_seconds` is the whole
    number of seconds (rounded up) until the gate stops refusing. The message carries these
    two only: never a URL, a key or SDK text.
    """

    def __init__(self, reason: str, retry_after_seconds: int) -> None:
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"REST call refused before sending: {reason}; retry_after_seconds={retry_after_seconds}"
        )


class RateLimitBanActive(RestGateRefusal):
    """Refused because an HTTP 418 ban of the process is active."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(IP_BAN_418, retry_after_seconds)


class RateLimitPauseActive(RestGateRefusal):
    """Refused because an HTTP 429 pause of every REST call of the process is active."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(RATE_LIMIT_PAUSE_429, retry_after_seconds)


@dataclass(frozen=True, slots=True)
class GateRestriction:
    """The active restriction: the refusing reason (the ban wins) and when REST opens again.

    `until_utc` is the later of the active end times (the moment `check()` stops refusing);
    `remaining_seconds` is the whole seconds until then, rounded up.
    """

    reason: str
    until_utc: datetime
    remaining_seconds: int


def _whole_seconds_until(now: datetime, end: datetime) -> int:
    """Seconds from `now` to `end`, rounded up, in integer arithmetic (no float)."""
    micros = (end - now) // _ONE_MICROSECOND
    if micros <= 0:
        return 0
    return -(-micros // _MICROSECONDS_PER_SECOND)


class RestRateLimitGate:
    """The single rate-limit state of the process: two end times, nothing else.

    `check()` raises `RateLimitBanActive` while a ban is active, else `RateLimitPauseActive`
    while a pause is active, else returns None. `record(category, retry_after_seconds)`
    extends the ban (IP_BANNED) or the pause (RATE_LIMITED) to now plus the wait of
    `rate_limit_decision`; every other category changes nothing. An end time only moves
    later. A `threading.Lock` guards the end times because every holder of the process shares
    the one instance (the SDK calls run in worker threads).
    """

    def __init__(self, *, policy: RateLimitPolicy, clock: Callable[[], datetime]) -> None:
        if not isinstance(policy, RateLimitPolicy):
            raise TypeError("policy must be a RateLimitPolicy")
        if not callable(clock):
            raise TypeError("clock must be a callable returning a timezone-aware datetime")
        self._policy = policy
        self._clock = clock
        self._lock = threading.Lock()
        self._ban_until: datetime | None = None
        self._pause_until: datetime | None = None

    @property
    def policy(self) -> RateLimitPolicy:
        return self._policy

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("the gate clock must return a timezone-aware datetime")
        return now

    def _active(self, now: datetime) -> tuple[bool, bool]:
        banned = self._ban_until is not None and now < self._ban_until
        paused = self._pause_until is not None and now < self._pause_until
        return banned, paused

    def _refuse_until(self, now: datetime) -> datetime | None:
        banned, paused = self._active(now)
        ends = [
            end
            for end, active in ((self._ban_until, banned), (self._pause_until, paused))
            if active and end is not None
        ]
        return max(ends) if ends else None

    def check(self) -> None:
        """Refuse the REST call about to be sent while a ban or a pause is active."""
        with self._lock:
            now = self._now()
            banned, paused = self._active(now)
            opens_at = self._refuse_until(now)
        if opens_at is None:
            return
        remaining = _whole_seconds_until(now, opens_at)
        if banned:
            raise RateLimitBanActive(remaining)
        if paused:
            raise RateLimitPauseActive(remaining)

    def record(
        self, category: ExchangeErrorCategory, retry_after_seconds: int | None
    ) -> RateLimitDecision:
        """Record a classified failure: a 418 extends the ban, a 429 extends the pause."""
        policy = self._policy
        decision = rate_limit_decision(
            category,
            retry_after_seconds,
            no_retry_after_wait_418_seconds=policy.no_retry_after_wait_418_seconds,
            no_retry_after_wait_429_seconds=policy.no_retry_after_wait_429_seconds,
            retry_after_cap_seconds=policy.retry_after_cap_seconds,
        )
        if decision.wait_seconds is None:
            return decision
        with self._lock:
            end = self._now() + timedelta(seconds=decision.wait_seconds)
            if category is ExchangeErrorCategory.IP_BANNED:
                if self._ban_until is None or end > self._ban_until:
                    self._ban_until = end
            elif category is ExchangeErrorCategory.RATE_LIMITED:
                if self._pause_until is None or end > self._pause_until:
                    self._pause_until = end
        return decision

    def restriction(self) -> GateRestriction | None:
        """The active restriction, or None when REST calls are not refused."""
        with self._lock:
            now = self._now()
            banned, _ = self._active(now)
            opens_at = self._refuse_until(now)
        if opens_at is None:
            return None
        return GateRestriction(
            reason=IP_BAN_418 if banned else RATE_LIMIT_PAUSE_429,
            until_utc=opens_at,
            remaining_seconds=_whole_seconds_until(now, opens_at),
        )

    def remaining_seconds(self) -> int:
        """Whole seconds (rounded up) until REST calls are no longer refused; 0 when open."""
        restriction = self.restriction()
        return 0 if restriction is None else restriction.remaining_seconds


__all__ = [
    "IP_BAN_418",
    "RATE_LIMIT_PAUSE_429",
    "GateRestriction",
    "RateLimitBanActive",
    "RateLimitPauseActive",
    "RestGateRefusal",
    "RestRateLimitGate",
]
