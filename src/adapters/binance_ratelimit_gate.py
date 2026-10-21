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

Restart recovery (plan 20-07, T-D, D-18). The two end times live in memory; a gate built with a
`state_store` (the `GateStateStore` Protocol) saves them after every change and restores them
once, through `restore()`, at the start of the process. Until `restore()` ran, the empty
in-memory state is NOT proof that REST may be dispatched: `check()` refuses with
`GateNotRestored` (a `RestGateRefusal`, so a refused safety action stays a durable PENDING row
and is never sent around the gate). There is no exemption for any request category.
An open gate means no currently known restriction; it is not proof that REST is healthy. Fresh
successful reads from Binance stay mandatory. A gate built without a store behaves as before and
reports `LEGACY_IN_MEMORY`, which no SAFE_MODE exit accepts.

Known gap (Phase 18): the data jobs (backfill, universe freeze, collector), the Phase 16 paper
runtime and the scripts `paper_ws_smoke.py` and `shadow_rehearsal.py` do not hold this gate and
keep their existing rate-limit handling; gating them is left to the phases that compose those
processes.

Pure: standard library, `src.domain.exchange_errors` and the `RateLimitPolicy` type only. No
SDK import, no I/O (persistence goes through the injected `GateStateStore`), no wall clock (the
clock is injected), no sleep, no float.
"""

from __future__ import annotations

import enum
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from src.adapters.binance_limits import RateLimitPolicy
from src.domain.exchange_errors import (
    ExchangeErrorCategory,
    PreSendRefusal,
    RateLimitDecision,
    rate_limit_decision,
)

IP_BAN_418 = "IP_BAN_418"
RATE_LIMIT_PAUSE_429 = "RATE_LIMIT_PAUSE_429"
GATE_NOT_RESTORED = "GATE_NOT_RESTORED"
GATE_STATE_UNKNOWN = "GATE_STATE_UNKNOWN"
GATE_STATE_SCHEMA_VERSION = 1

# Alert event name handed to the injected `on_alert` hook, once per gate, when the persisted
# state is lost, unreadable or corrupt (a human must act; see `FileGateStateStore.initialize`).
REST_GATE_RECOVERY_REQUIRED = "REST_GATE_RECOVERY_REQUIRED"

# A restriction with no known end (not restored, unknown state) reports this many seconds: the
# smallest whole-second re-check hint. It is never the 259200 s wait: a consumer that sleeps on
# the value (binance_userdata_supervisor._await_rest_allowed) must not be parked for days.
_NO_KNOWN_END_SECONDS = 1

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


class GateNotRestored(RestGateRefusal):  # noqa: N818 - a refusal, not an error of the caller
    """Refused because the gate has no trustworthy knowledge of the ban or pause state.

    `reason` is `GATE_NOT_RESTORED` (restore() has not produced a verdict yet) or
    `GATE_STATE_UNKNOWN` (the persisted state was lost or is unreadable). A `RestGateRefusal`
    on purpose: plan 20-14 keeps a refused safety action as a durable PENDING row and sends it
    only when the gate permits. `retry_after_seconds` is 1 (no end is known). The message names
    the reason only: never a URL, a key or a path.
    """

    def __init__(self, reason: str, retry_after_seconds: int = _NO_KNOWN_END_SECONDS) -> None:
        super().__init__(reason, retry_after_seconds)


class GateRecoveryStatus(enum.Enum):
    """What the gate knows about its own restart recovery (read by plan 20-25, row 6).

    Only `RESTORED_DURABLE` (with `restriction()` None) may count toward a SAFE_MODE exit, and
    never without the fresh Binance reads of row 3. `RESTORED_BARRIER` is reserved for the
    startup-barrier option and is never produced by the persisted-deadline mechanism.
    """

    LEGACY_IN_MEMORY = "LEGACY_IN_MEMORY"
    NOT_RESTORED = "NOT_RESTORED"
    RESTORED_DURABLE = "RESTORED_DURABLE"
    RESTORED_BARRIER = "RESTORED_BARRIER"
    RESTORED_UNKNOWN_STATE = "RESTORED_UNKNOWN_STATE"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


class GateStateCorrupt(Exception):  # noqa: N818 - a state, not an error of the caller
    """The persisted gate state exists but does not parse; the store has set the file aside."""


@dataclass(frozen=True, slots=True)
class GateStateRecord:
    """The persisted gate state (schema_version 1): two deadlines and who initialized it.

    `initialized_at_utc` / `initialized_by` prove that the explicit first-install bootstrap ran;
    a state file without them is corrupt. A deadline is None while none is recorded.
    """

    ban_until_utc: datetime | None
    pause_until_utc: datetime | None
    recorded_at_utc: datetime
    initialized_at_utc: datetime
    initialized_by: str
    schema_version: int = GATE_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("ban_until_utc", "pause_until_utc", "recorded_at_utc", "initialized_at_utc"):
            value = getattr(self, name)
            required = name in ("recorded_at_utc", "initialized_at_utc")
            if value is None and not required:
                continue
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError(f"{name} must be a timezone-aware datetime")
        if not isinstance(self.initialized_by, str) or not self.initialized_by.strip():
            raise ValueError("initialized_by must be a non-empty string")
        if self.schema_version != GATE_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported gate state schema_version")


class GateStateStore(Protocol):
    """Where the gate keeps its deadlines (the file store lives in `src.ops.rest_gate_state`).

    `load()` returns None when no state exists and raises `GateStateCorrupt` when the state
    does not parse; `save()` raises on a failure to persist.
    """

    def save(self, record: GateStateRecord) -> None: ...

    def load(self) -> GateStateRecord | None: ...


@dataclass(frozen=True, slots=True)
class GateRestriction:
    """The active restriction: the refusing reason (the ban wins) and when REST opens again.

    `until_utc` is the later of the active end times (the moment `check()` stops refusing);
    `remaining_seconds` is the whole seconds until then, rounded up. `until_utc` is None only
    while no end is known (`GATE_NOT_RESTORED`, `GATE_STATE_UNKNOWN`); `remaining_seconds` is
    then 1, never a long wait.
    """

    reason: str
    until_utc: datetime | None
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

    With a `state_store` the gate starts NOT_RESTORED (see the module docstring): `check()`
    refuses with `GateNotRestored` until `restore()` has adopted a valid persisted record, and
    every change of an end time is saved. `check()` has no argument: no request category is
    exempt.
    """

    def __init__(
        self,
        *,
        policy: RateLimitPolicy,
        clock: Callable[[], datetime],
        state_store: GateStateStore | None = None,
        on_alert: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(policy, RateLimitPolicy):
            raise TypeError("policy must be a RateLimitPolicy")
        if not callable(clock):
            raise TypeError("clock must be a callable returning a timezone-aware datetime")
        if on_alert is not None and not callable(on_alert):
            raise TypeError("on_alert must be a callable taking the alert event name")
        self._policy = policy
        self._clock = clock
        self._state_store = state_store
        self._on_alert = on_alert
        self._lock = threading.Lock()
        self._restore_lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._ban_until: datetime | None = None
        self._pause_until: datetime | None = None
        self._restore_done = False
        self._unknown_state = False
        self._save_failed = False
        self._loaded: GateStateRecord | None = None

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

    def _blocking_reason(self) -> str | None:
        """The reason the gate refuses without a known end, or None (caller holds the lock)."""
        if self._state_store is None:
            return None
        if not self._restore_done:
            return GATE_NOT_RESTORED
        if self._unknown_state:
            return GATE_STATE_UNKNOWN
        return None

    def check(self) -> None:
        """Refuse the REST call about to be sent while a ban or a pause is active."""
        with self._lock:
            blocking = self._blocking_reason()
            if blocking is not None:
                raise GateNotRestored(blocking)
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
        changed = False
        with self._lock:
            end = self._now() + timedelta(seconds=decision.wait_seconds)
            if category is ExchangeErrorCategory.IP_BANNED:
                if self._ban_until is None or end > self._ban_until:
                    self._ban_until = end
                    changed = True
            elif category is ExchangeErrorCategory.RATE_LIMITED:
                if self._pause_until is None or end > self._pause_until:
                    self._pause_until = end
                    changed = True
        if changed:
            self._persist()
        return decision

    def restriction(self) -> GateRestriction | None:
        """The active restriction, or None when no restriction is currently known.

        None is not proof that REST is healthy (module docstring).
        """
        with self._lock:
            blocking = self._blocking_reason()
            if blocking is not None:
                return GateRestriction(
                    reason=blocking, until_utc=None, remaining_seconds=_NO_KNOWN_END_SECONDS
                )
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
        """Whole seconds (rounded up) until REST calls are no longer refused; 0 when open.

        1 while no end is known (the smallest re-check hint, never a long wait).
        """
        restriction = self.restriction()
        return 0 if restriction is None else restriction.remaining_seconds

    # -- restart recovery (plan 20-07, T-D) ----------------------------------- #

    def recovery_status(self) -> GateRecoveryStatus:
        """What the gate knows about its own restart recovery (see `GateRecoveryStatus`)."""
        with self._lock:
            if self._state_store is None:
                return GateRecoveryStatus.LEGACY_IN_MEMORY
            if not self._restore_done:
                return GateRecoveryStatus.NOT_RESTORED
            if self._unknown_state:
                return GateRecoveryStatus.RESTORED_UNKNOWN_STATE
            if self._save_failed:
                return GateRecoveryStatus.PERSISTENCE_FAILED
            return GateRecoveryStatus.RESTORED_DURABLE

    def restore(self) -> GateRecoveryStatus:
        """Adopt the persisted deadlines; call once at process start, before any REST call.

        One verdict per gate instance; a second call changes nothing (a running gate is never
        cleared in process, only by a restart whose `restore()` reads a valid record).

        * a valid record is adopted (end times only move later): `RESTORED_DURABLE`;
        * no record (loss of initialized state: a first install must have run the explicit
          bootstrap), a record that does not parse, or a store that cannot be read: the gate
          is restricted with no known end (`GATE_STATE_UNKNOWN`, status
          `RESTORED_UNKNOWN_STATE`) until a restart reads a valid record, and `on_alert` is
          called once with `REST_GATE_RECOVERY_REQUIRED`.

        Without a store nothing is restored and the status is `LEGACY_IN_MEMORY`.
        """
        store = self._state_store
        if store is None:
            return GateRecoveryStatus.LEGACY_IN_MEMORY
        with self._restore_lock:
            if self._restore_done:
                return self.recovery_status()
            record: GateStateRecord | None
            try:
                record = store.load()
            except Exception:
                # A missing record, a corrupt one and an unreadable store are the same verdict:
                # the persisted state cannot be trusted (D-10: decided by type, never by text).
                record = None
            if record is None:
                with self._lock:
                    self._unknown_state = True
                    self._restore_done = True
                self._alert(REST_GATE_RECOVERY_REQUIRED)
                return self.recovery_status()
            with self._lock:
                if record.ban_until_utc is not None and (
                    self._ban_until is None or record.ban_until_utc > self._ban_until
                ):
                    self._ban_until = record.ban_until_utc
                if record.pause_until_utc is not None and (
                    self._pause_until is None or record.pause_until_utc > self._pause_until
                ):
                    self._pause_until = record.pause_until_utc
                self._loaded = record
                self._restore_done = True
                merged = (
                    self._ban_until != record.ban_until_utc
                    or self._pause_until != record.pause_until_utc
                )
            if merged:
                self._persist()  # a deadline recorded before restore() is saved now
        return self.recovery_status()

    def _alert(self, event: str) -> None:
        """Tell the injected hook; a failing hook never changes the restriction."""
        hook = self._on_alert
        if hook is None:
            return
        try:
            hook(event)
        except Exception:
            pass

    def _persist(self) -> None:
        """Save the current end times; a no-op unless a valid record was restored.

        A failing save never raises into the REST caller: the in-memory restriction stays
        enforced and the status becomes `PERSISTENCE_FAILED` until a later save succeeds. An
        unknown state is never saved (a valid-looking file would reopen a closed gate).
        """
        store = self._state_store
        if store is None:
            return
        with self._save_lock:
            with self._lock:
                loaded = self._loaded
                if loaded is None:
                    return
                record = GateStateRecord(
                    ban_until_utc=self._ban_until,
                    pause_until_utc=self._pause_until,
                    recorded_at_utc=self._now(),
                    initialized_at_utc=loaded.initialized_at_utc,
                    initialized_by=loaded.initialized_by,
                )
            try:
                store.save(record)
            except Exception:
                failed = True
            else:
                failed = False
            with self._lock:
                self._save_failed = failed


__all__ = [
    "GATE_NOT_RESTORED",
    "GATE_STATE_SCHEMA_VERSION",
    "GATE_STATE_UNKNOWN",
    "IP_BAN_418",
    "RATE_LIMIT_PAUSE_429",
    "REST_GATE_RECOVERY_REQUIRED",
    "GateNotRestored",
    "GateRecoveryStatus",
    "GateRestriction",
    "GateStateCorrupt",
    "GateStateRecord",
    "GateStateStore",
    "RateLimitBanActive",
    "RateLimitPauseActive",
    "RestGateRefusal",
    "RestRateLimitGate",
]
