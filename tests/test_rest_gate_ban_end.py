"""D083: the 418 / -1003 ban end time read from the response body (plan 24-03).

DECISIONS D083 is an exception to D-10 limited to one read: for an HTTP 418 with the int body code
-1003, exactly one 13-digit integer after the literal ``IP banned until `` in the ``msg`` field is
read as epoch milliseconds. The gate accepts it only when it is in the future against the injected
clock and not later than ``now`` plus the ratified retry-after cap, and only when the owner has set
the clock margin; the accepted end is padded by the margin and persisted like any deadline. Every
other case keeps today's fallback wait. A valid Retry-After still wins. The text and the number are
never logged. Clocks, the SDK exception and the state store are fakes or temp files.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from binance_common.errors import RateLimitBanError, TooManyRequestsError
from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import (
    REST_GATE_BAN_ENTERED,
    GateRecoveryStatus,
    RateLimitBanActive,
    RestRateLimitGate,
)
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    classify,
)
from src.ops.rest_gate_state import FileGateStateStore
from structlog.testing import capture_logs

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
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MARGIN = timedelta(seconds=45)  # TEST ONLY: the real value is the owner's (plan 24-06, O-1)


def _ms(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


def _text(ban_ms: int | str) -> str:
    return f"Way too many requests; IP banned until {ban_ms}. Please use WebSocket Streams."


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Alerts:
    def __init__(self) -> None:
        self.events: list[str] = []

    def __call__(self, event: str) -> None:
        self.events.append(event)


def _policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        no_retry_after_wait_418_seconds=WAIT_418,
        no_retry_after_wait_429_seconds=WAIT_429,
        retry_after_cap_seconds=CAP,
    )


def _gate(
    clock: Clock,
    *,
    margin: timedelta | None = MARGIN,
    alerts: Alerts | None = None,
    store: FileGateStateStore | None = None,
) -> RestRateLimitGate:
    return RestRateLimitGate(
        policy=_policy(),
        clock=clock,
        state_store=store,
        on_alert=alerts,
        ban_end_clock_margin=margin,
    )


def _answer(
    gate: RestRateLimitGate,
    exc: BaseException,
    call_kind: CallKind = CallKind.QUERY,
) -> None:
    """What every REST holder does on a failed call: facts, category, record."""
    facts = error_facts_from_exception(exc)
    category = classify(facts, call_kind)
    gate.record(category, facts.retry_after_seconds, ban_until_epoch_ms=facts.ban_until_epoch_ms)


def _ban(text: str, *, code: int | None = -1003, retry_after: int | None = None) -> BaseException:
    return RateLimitBanError(error_message=text, status_code=code, retry_after=retry_after)


def _until(gate: RestRateLimitGate) -> datetime | None:
    restriction = gate.restriction()
    return None if restriction is None else restriction.until_utc


# --------------------------------------------------------------------------- #
# Tracer: a real-looking 418 body with a configured margin sets the padded end.
# --------------------------------------------------------------------------- #


def test_a_418_body_with_a_margin_sets_the_padded_end_and_without_it_the_fallback() -> None:
    clock = Clock()
    ban_end = T0 + timedelta(seconds=600)

    padded = _gate(clock)
    _answer(padded, _ban(_text(_ms(ban_end))))
    assert _until(padded) == ban_end + MARGIN

    unset = _gate(clock, margin=None)
    _answer(unset, _ban(_text(_ms(ban_end))))
    assert _until(unset) == T0 + timedelta(seconds=WAIT_418)


def test_the_padded_end_survives_a_restart(tmp_path: Path) -> None:
    clock = Clock()
    store = FileGateStateStore(tmp_path / "gate.json", clock=clock)
    store.initialize(now_utc=T0, operator_id="op-1")
    first = _gate(clock, store=store)
    assert first.restore() is GateRecoveryStatus.RESTORED_DURABLE
    ban_end = T0 + timedelta(seconds=600)
    _answer(first, _ban(_text(_ms(ban_end))))

    clock.now = T0 + timedelta(minutes=10)
    second = _gate(clock, store=FileGateStateStore(tmp_path / "gate.json", clock=clock))
    assert second.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert _until(second) == ban_end + MARGIN
    with pytest.raises(RateLimitBanActive):
        second.check()


def test_a_padded_end_at_the_cap_plus_margin_is_trusted_by_restore(tmp_path: Path) -> None:
    clock = Clock()
    store = FileGateStateStore(tmp_path / "gate.json", clock=clock)
    store.initialize(now_utc=T0, operator_id="op-1")
    first = _gate(clock, store=store)
    first.restore()
    _answer(first, _ban(_text(_ms(T0 + timedelta(seconds=CAP)))))
    assert _until(first) == T0 + timedelta(seconds=CAP) + MARGIN

    second = _gate(clock, store=FileGateStateStore(tmp_path / "gate.json", clock=clock))
    assert second.restore() is GateRecoveryStatus.RESTORED_DURABLE
    assert _until(second) == T0 + timedelta(seconds=CAP) + MARGIN


# --------------------------------------------------------------------------- #
# The accept / ignore matrix.
# --------------------------------------------------------------------------- #

_NOW_MS = _ms(T0)
_IGNORED_TEXTS = {
    "no match": "Way too many requests; IP banned.",
    "no literal": f"Way too many requests; banned until {_NOW_MS + 600_000}.",
    "literal without IP": f"too many; Banned until {_NOW_MS + 600_000}.",
    "two matches": (f"IP banned until {_NOW_MS + 600_000}. IP banned until {_NOW_MS + 700_000}."),
    "two equal matches": (
        f"IP banned until {_NOW_MS + 600_000}. IP banned until {_NOW_MS + 600_000}."
    ),
    "12 digits": "IP banned until 179300000000.",
    "14 digits": "IP banned until 17930000000000.",
    "seconds not ms": f"IP banned until {_NOW_MS // 1000 + 600}.",
    "past": _text(_NOW_MS - 1_000),
    "exactly now": _text(_NOW_MS),
    "too far": _text(_NOW_MS + CAP * 1000 + 1),
}


@pytest.mark.parametrize("name", sorted(_IGNORED_TEXTS))
def test_an_unusable_body_uses_the_fallback_wait(name: str) -> None:
    gate = _gate(Clock())
    _answer(gate, _ban(_IGNORED_TEXTS[name]))
    assert _until(gate) == T0 + timedelta(seconds=WAIT_418)


def test_exactly_the_cap_is_accepted_and_one_millisecond_more_is_not() -> None:
    at_cap = _gate(Clock())
    _answer(at_cap, _ban(_text(_NOW_MS + CAP * 1000)))
    assert _until(at_cap) == T0 + timedelta(seconds=CAP) + MARGIN

    beyond = _gate(Clock())
    _answer(beyond, _ban(_text(_NOW_MS + CAP * 1000 + 1)))
    assert _until(beyond) == T0 + timedelta(seconds=WAIT_418)


def test_one_millisecond_in_the_future_is_accepted() -> None:
    gate = _gate(Clock())
    _answer(gate, _ban(_text(_NOW_MS + 1)))
    assert _until(gate) == T0 + timedelta(milliseconds=1) + MARGIN


def test_a_valid_retry_after_still_wins_over_the_body() -> None:
    gate = _gate(Clock())
    _answer(gate, _ban(_text(_NOW_MS + 600_000), retry_after=120))
    assert _until(gate) == T0 + timedelta(seconds=120)


def test_a_code_other_than_1003_is_never_read() -> None:
    gate = _gate(Clock())
    _answer(gate, _ban(_text(_NOW_MS + 600_000), code=-1000))
    assert _until(gate) == T0 + timedelta(seconds=WAIT_418)
    gate = _gate(Clock())
    _answer(gate, _ban(_text(_NOW_MS + 600_000), code=None))
    assert _until(gate) == T0 + timedelta(seconds=WAIT_418)


def test_a_429_with_the_same_text_is_never_read() -> None:
    exc = TooManyRequestsError(
        error_message=_text(_NOW_MS + 600_000), status_code=-1003, retry_after=None
    )
    assert error_facts_from_exception(exc).ban_until_epoch_ms is None
    gate = _gate(Clock())
    _answer(gate, exc)
    assert _until(gate) == T0 + timedelta(seconds=WAIT_429)


def test_a_later_ban_never_shortens_an_existing_one() -> None:
    gate = _gate(Clock())
    _answer(gate, _ban(_text(_NOW_MS + 900_000)))
    first = _until(gate)
    _answer(gate, _ban(_IGNORED_TEXTS["no match"]))  # fallback 777 s, shorter than 945 s
    assert _until(gate) == first


# --------------------------------------------------------------------------- #
# Alert on entering the ban carries the deadline; nothing is logged.
# --------------------------------------------------------------------------- #


def test_the_ban_entry_alert_carries_the_deadline() -> None:
    alerts = Alerts()
    gate = _gate(Clock(), alerts=alerts)
    ban_end = T0 + timedelta(seconds=600)
    _answer(gate, _ban(_text(_ms(ban_end))))
    assert alerts.events == [f"{REST_GATE_BAN_ENTERED} until_utc={(ban_end + MARGIN).isoformat()}"]


def test_the_ban_entry_alert_on_the_fallback_carries_its_deadline_too() -> None:
    alerts = Alerts()
    gate = _gate(Clock(), margin=None, alerts=alerts)
    _answer(gate, _ban(_IGNORED_TEXTS["no match"]))
    expected = (T0 + timedelta(seconds=WAIT_418)).isoformat()
    assert alerts.events == [f"{REST_GATE_BAN_ENTERED} until_utc={expected}"]


def test_the_parsed_number_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    ban_ms = _NOW_MS + 600_000
    alerts = Alerts()
    gate = _gate(Clock(), alerts=alerts)
    with capture_logs() as captured, caplog.at_level(logging.DEBUG):
        structlog.get_logger("d083").info("probe-logger-is-wired")
        _answer(gate, _ban(_text(ban_ms)))
        with pytest.raises(RateLimitBanActive) as refusal:
            gate.check()
    assert str(ban_ms) not in repr(captured)
    assert str(ban_ms) not in caplog.text
    assert str(ban_ms) not in str(refusal.value)
    assert all(str(ban_ms) not in event for event in alerts.events)


# --------------------------------------------------------------------------- #
# ErrorFacts carries only a validated number, for 418 / -1003 only.
# --------------------------------------------------------------------------- #


def test_error_facts_extracts_only_for_418_and_1003() -> None:
    ban_ms = _NOW_MS + 600_000
    facts = error_facts_from_exception(_ban(_text(ban_ms)))
    assert facts.http_class is HttpClass.BANNED_418
    assert facts.ban_until_epoch_ms == ban_ms
    assert error_facts_from_exception(_ban(_text(ban_ms), code=-1000)).ban_until_epoch_ms is None
    assert error_facts_from_exception(ValueError(_text(ban_ms))).ban_until_epoch_ms is None


def test_error_facts_default_is_none_and_the_number_is_validated() -> None:
    assert ErrorFacts(http_class=HttpClass.NETWORK, code=None, retry_after_seconds=None) == (
        ErrorFacts(
            http_class=HttpClass.NETWORK,
            code=None,
            retry_after_seconds=None,
            ban_until_epoch_ms=None,
        )
    )
    for bad in (True, 123, 12_345_678_901_234, -1_793_000_000_000, 1.793e12, "1793000000000"):
        with pytest.raises((TypeError, ValueError)):
            ErrorFacts(
                http_class=HttpClass.BANNED_418,
                code=-1003,
                retry_after_seconds=None,
                ban_until_epoch_ms=bad,  # type: ignore[arg-type]
            )
    for http_class, code in ((HttpClass.TOO_MANY_429, -1003), (HttpClass.BANNED_418, -1000)):
        with pytest.raises(ValueError):
            ErrorFacts(
                http_class=http_class,
                code=code,
                retry_after_seconds=None,
                ban_until_epoch_ms=1_793_000_000_000,
            )


def test_the_margin_must_be_a_positive_timedelta_or_none() -> None:
    for bad in (timedelta(0), timedelta(seconds=-1)):
        with pytest.raises(ValueError):
            _gate(Clock(), margin=bad)
    for wrong in (45, 45.0, True, "45"):
        with pytest.raises(TypeError):
            _gate(Clock(), margin=wrong)  # type: ignore[arg-type]


def test_a_ban_end_is_ignored_for_a_429_category_directly() -> None:
    gate = _gate(Clock())
    gate.record(_C.RATE_LIMITED, None, ban_until_epoch_ms=_NOW_MS + 600_000)
    assert _until(gate) == T0 + timedelta(seconds=WAIT_429)
