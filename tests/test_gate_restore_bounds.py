"""A persisted deadline the policy could never have produced is untrusted (plan 20-30, WR-C3).

`restore()` used to adopt any persisted `ban_until_utc` or `pause_until_utc`. A record written
under host clock skew, or with a corrupted year, then gave a multi-day or multi-year restriction
(and a supervisor that slept for it). The longest wait the policy can produce is the largest of
`retry_after_cap_seconds`, `no_retry_after_wait_418_seconds` and `no_retry_after_wait_429_seconds`;
a deadline beyond `recorded_at_utc` plus that, with zero extra allowance, is untrusted: the gate
takes the unknown-state restriction (fail closed, the operator clears it) and raises the
`REST_GATE_RECOVERY_REQUIRED` signal once. Clocks and the store are fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import (
    GATE_STATE_UNKNOWN,
    REST_GATE_RECOVERY_REQUIRED,
    GateNotRestored,
    GateRecoveryStatus,
    GateRestriction,
    GateStateRecord,
    RateLimitBanActive,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.domain.exchange_errors import ExchangeErrorCategory

from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_418,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_429,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS as CAP,
)

_C = ExchangeErrorCategory
T0 = datetime(2026, 10, 21, 9, 0, 0, tzinfo=UTC)
MAX_WAIT = timedelta(seconds=max(CAP, WAIT_418, WAIT_429))
EPS = timedelta(microseconds=1)


class _Store:
    """A store holding one record; counts saves."""

    def __init__(self, record: GateStateRecord | None) -> None:
        self.record = record
        self.saves: list[GateStateRecord] = []

    def load(self) -> GateStateRecord | None:
        return self.record

    def save(self, record: GateStateRecord) -> None:
        self.saves.append(record)
        self.record = record


def _record(
    *, ban: datetime | None = None, pause: datetime | None = None, recorded: datetime = T0
) -> GateStateRecord:
    return GateStateRecord(
        ban_until_utc=ban,
        pause_until_utc=pause,
        recorded_at_utc=recorded,
        initialized_at_utc=T0 - timedelta(days=1),
        initialized_by="op-1",
    )


def _gate(store: _Store, alerts: list[str], now: datetime = T0) -> RestRateLimitGate:
    return RestRateLimitGate(
        policy=RateLimitPolicy(
            no_retry_after_wait_418_seconds=WAIT_418,
            no_retry_after_wait_429_seconds=WAIT_429,
            retry_after_cap_seconds=CAP,
        ),
        clock=lambda: now,
        state_store=store,
        on_alert=alerts.append,
    )


def test_the_test_values_make_the_largest_wait_the_cap() -> None:
    # The bound is the largest of the three; the TEST_ONLY cap is the largest here, so a wrong
    # pick of the 418 or 429 value would be caught by the boundary tests below.
    assert MAX_WAIT == timedelta(seconds=CAP)
    assert WAIT_418 < CAP and WAIT_429 < CAP


@pytest.mark.parametrize("field", ["ban", "pause"])
def test_a_deadline_exactly_at_recorded_plus_the_largest_wait_is_trusted(field: str) -> None:
    alerts: list[str] = []
    store = _Store(_record(**{field: T0 + MAX_WAIT}))
    gate = _gate(store, alerts)

    assert gate.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert alerts == []
    with pytest.raises(RateLimitBanActive if field == "ban" else RateLimitPauseActive):
        gate.check()


@pytest.mark.parametrize("field", ["ban", "pause"])
def test_a_deadline_beyond_recorded_plus_the_largest_wait_is_untrusted(field: str) -> None:
    alerts: list[str] = []
    store = _Store(_record(**{field: T0 + MAX_WAIT + EPS}))
    gate = _gate(store, alerts)

    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert gate.recovery_status() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert alerts == [REST_GATE_RECOVERY_REQUIRED]
    assert gate.restriction() == GateRestriction(
        reason=GATE_STATE_UNKNOWN, until_utc=None, remaining_seconds=1
    )
    with pytest.raises(GateNotRestored) as info:
        gate.check()
    assert info.value.reason == GATE_STATE_UNKNOWN
    # An unknown state is never saved (a valid-looking file would reopen a closed gate).
    assert store.saves == []


@pytest.mark.parametrize("field", ["ban", "pause"])
def test_a_corrupted_far_year_is_untrusted(field: str) -> None:
    alerts: list[str] = []
    store = _Store(_record(**{field: datetime(9999, 12, 31, tzinfo=UTC)}))
    gate = _gate(store, alerts)

    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert alerts == [REST_GATE_RECOVERY_REQUIRED]


def test_one_untrusted_deadline_poisons_the_record_even_if_the_other_is_fine() -> None:
    alerts: list[str] = []
    store = _Store(_record(ban=T0 + timedelta(seconds=5), pause=T0 + MAX_WAIT + EPS))
    gate = _gate(store, alerts)

    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert alerts == [REST_GATE_RECOVERY_REQUIRED]


def test_the_bound_is_measured_from_the_record_time_not_from_now() -> None:
    # Written a day ago with a ban that ends in the future of that day: fine. The same deadline
    # measured from a recorded_at far in the past would be untrusted.
    now = T0 + timedelta(days=1)
    alerts: list[str] = []
    ok = _Store(_record(ban=now + timedelta(seconds=5), recorded=now))
    assert _gate(ok, alerts, now).restore() is GateRecoveryStatus.RESTORED_DURABLE
    old = _Store(_record(ban=now + timedelta(seconds=5), recorded=T0))
    assert _gate(old, alerts, now).restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert alerts == [REST_GATE_RECOVERY_REQUIRED]


def test_a_second_restore_changes_nothing_and_alerts_once() -> None:
    alerts: list[str] = []
    gate = _gate(_Store(_record(ban=T0 + MAX_WAIT + EPS)), alerts)
    gate.restore()
    assert gate.restore() is GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    assert alerts == [REST_GATE_RECOVERY_REQUIRED]


@pytest.mark.parametrize(
    ("category", "field"),
    [(_C.IP_BANNED, "ban"), (_C.RATE_LIMITED, "pause")],
)
def test_a_deadline_the_gate_itself_wrote_is_always_trusted_after_a_restart(
    category: ExchangeErrorCategory, field: str
) -> None:
    """The longest legal Retry-After (above the cap) is capped, so it round-trips."""
    store = _Store(_record())
    writer = _gate(store, [])
    assert writer.restore() is GateRecoveryStatus.RESTORED_DURABLE
    writer.record(category, CAP * 5)
    assert store.saves, "the gate saved its deadline"

    alerts: list[str] = []
    reader = _gate(store, alerts)
    assert reader.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert alerts == []
    restriction = reader.restriction()
    assert restriction is not None
    assert restriction.until_utc == T0 + timedelta(seconds=CAP)
