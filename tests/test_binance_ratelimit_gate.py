"""The process-wide REST rate-limit gate (plan 18-10; user record 18-DEC-O-18-01.md).

A 418 bans and a 429 pauses every REST call of every holder of the one gate of the process,
for a valid Retry-After capped by the cap, otherwise for the 418 or the 429 fallback. Only the
injected clock passing the end time lifts a restriction; the gate has no clearing method and
its opening proves nothing. The policies here are TEST_ONLY values (tests/support/limits.py),
pairwise different so that a swapped 418/429 fallback fails a named test.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import src.adapters.binance_ratelimit_gate as gate_mod
from binance_common.errors import RateLimitBanError, TooManyRequestsError
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_public import BinancePublicMarketData
from src.adapters.binance_ratelimit_gate import (
    GateRestriction,
    RateLimitBanActive,
    RateLimitPauseActive,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.domain.exchange_errors import ExchangeErrorCategory, RateLimitDecision

from tests.support.ast_guards import float_constructor_calls, module_imports, wall_clock_calls
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
START = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)


class VirtualClock:
    """A UTC clock that only moves when the test says so."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        no_retry_after_wait_418_seconds=WAIT_418,
        no_retry_after_wait_429_seconds=WAIT_429,
        retry_after_cap_seconds=CAP,
    )


def _gate() -> tuple[RestRateLimitGate, VirtualClock]:
    clock = VirtualClock()
    return RestRateLimitGate(policy=_policy(), clock=clock), clock


def test_the_test_values_are_pairwise_different() -> None:
    assert len({WAIT_418, WAIT_429, CAP}) == 3
    assert WAIT_429 < WAIT_418 < CAP


# --------------------------------------------------------------------------- #
# Construction.
# --------------------------------------------------------------------------- #


def test_gate_requires_policy_and_clock() -> None:
    clock = VirtualClock()
    with pytest.raises(TypeError):
        RestRateLimitGate()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RestRateLimitGate(policy=_policy())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RestRateLimitGate(clock=clock)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RestRateLimitGate(_policy(), clock)  # type: ignore[misc]
    with pytest.raises(TypeError):
        RestRateLimitGate(policy=SimpleNamespace(), clock=clock)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RestRateLimitGate(policy=_policy(), clock="not callable")  # type: ignore[arg-type]
    policy = _policy()
    gate = RestRateLimitGate(policy=policy, clock=clock)
    assert gate.policy is policy
    with pytest.raises(AttributeError):
        gate.policy = _policy()  # type: ignore[misc]


def test_a_naive_clock_is_refused() -> None:
    gate = RestRateLimitGate(policy=_policy(), clock=lambda: datetime(2026, 10, 16))
    with pytest.raises(ValueError, match="timezone"):
        gate.check()


# --------------------------------------------------------------------------- #
# Ban (418) and pause (429) lengths.
# --------------------------------------------------------------------------- #


def test_418_without_retry_after_bans_for_418_fallback() -> None:
    gate, clock = _gate()
    decision = gate.record(_C.IP_BANNED, None)
    assert decision == RateLimitDecision(retry=False, wait_seconds=WAIT_418)
    assert gate.remaining_seconds() == WAIT_418
    assert gate.remaining_seconds() != WAIT_429
    restriction = gate.restriction()
    assert restriction == GateRestriction(
        reason="IP_BAN_418",
        until_utc=START + timedelta(seconds=WAIT_418),
        remaining_seconds=WAIT_418,
    )
    clock.advance(WAIT_429)  # the 429 fallback must not be what lifts a ban
    with pytest.raises(RateLimitBanActive):
        gate.check()
    clock.advance(WAIT_418 - WAIT_429 - 1)
    with pytest.raises(RateLimitBanActive) as info:
        gate.check()
    assert info.value.retry_after_seconds == 1
    clock.advance(1)
    assert gate.check() is None


def test_429_without_retry_after_pauses_for_429_fallback() -> None:
    gate, clock = _gate()
    decision = gate.record(_C.RATE_LIMITED, None)
    assert decision == RateLimitDecision(retry=False, wait_seconds=WAIT_429)
    assert gate.remaining_seconds() == WAIT_429
    assert gate.remaining_seconds() != WAIT_418
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.reason == "RATE_LIMIT_PAUSE_429"
    assert restriction.until_utc == START + timedelta(seconds=WAIT_429)
    clock.advance(WAIT_429 - 1)
    with pytest.raises(RateLimitPauseActive):
        gate.check()
    clock.advance(1)
    assert gate.check() is None
    assert gate.restriction() is None
    assert gate.remaining_seconds() == 0


@pytest.mark.parametrize(
    ("category", "refusal"),
    [(_C.IP_BANNED, RateLimitBanActive), (_C.RATE_LIMITED, RateLimitPauseActive)],
)
@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [(5, 5), (WAIT_418 + 1, WAIT_418 + 1), (CAP, CAP), (CAP + 1, CAP), (10 * CAP, CAP)],
)
def test_valid_retry_after_is_capped_for_ban_and_pause(
    category: ExchangeErrorCategory,
    refusal: type[RestGateRefusal],
    retry_after: int,
    expected: int,
) -> None:
    gate, clock = _gate()
    decision = gate.record(category, retry_after)
    assert decision == RateLimitDecision(retry=False, wait_seconds=expected)
    assert gate.remaining_seconds() == expected
    clock.advance(expected - 1)
    with pytest.raises(refusal):
        gate.check()
    clock.advance(1)
    assert gate.check() is None


def test_ban_and_pause_refuse_with_distinct_classes_and_reasons() -> None:
    assert issubclass(RateLimitBanActive, RestGateRefusal)
    assert issubclass(RateLimitPauseActive, RestGateRefusal)
    assert not issubclass(RateLimitBanActive, RateLimitPauseActive)
    assert not issubclass(RateLimitPauseActive, RateLimitBanActive)
    assert issubclass(RestGateRefusal, Exception)

    ban_gate, _ = _gate()
    ban_gate.record(_C.IP_BANNED, None)
    with pytest.raises(RateLimitBanActive) as ban:
        ban_gate.check()
    assert ban.value.reason == "IP_BAN_418"
    assert ban.value.retry_after_seconds == WAIT_418

    pause_gate, _ = _gate()
    pause_gate.record(_C.RATE_LIMITED, None)
    with pytest.raises(RateLimitPauseActive) as pause:
        pause_gate.check()
    assert pause.value.reason == "RATE_LIMIT_PAUSE_429"
    assert pause.value.retry_after_seconds == WAIT_429


def test_ban_takes_precedence_over_pause() -> None:
    gate, clock = _gate()
    gate.record(_C.RATE_LIMITED, None)
    gate.record(_C.IP_BANNED, 10)
    with pytest.raises(RateLimitBanActive) as info:
        gate.check()
    # The refusal says when REST opens again: the later of the two end times.
    assert info.value.retry_after_seconds == WAIT_429
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.reason == "IP_BAN_418"
    clock.advance(10)
    with pytest.raises(RateLimitPauseActive):
        gate.check()
    clock.advance(WAIT_429 - 10)
    assert gate.check() is None


def test_end_times_only_extend() -> None:
    gate, clock = _gate()
    gate.record(_C.RATE_LIMITED, 100)
    gate.record(_C.RATE_LIMITED, 10)  # an earlier end never shortens the pause
    assert gate.remaining_seconds() == 100
    clock.advance(50)
    gate.record(_C.RATE_LIMITED, 200)  # a later end extends it
    assert gate.remaining_seconds() == 200
    gate.record(_C.IP_BANNED, 300)
    gate.record(_C.IP_BANNED, 1)
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.until_utc == START + timedelta(seconds=350)


@pytest.mark.parametrize(
    "category",
    [c for c in ExchangeErrorCategory if c not in (_C.IP_BANNED, _C.RATE_LIMITED)],
)
def test_other_categories_change_nothing(category: ExchangeErrorCategory) -> None:
    gate, _ = _gate()
    assert gate.record(category, None) == RateLimitDecision(retry=False, wait_seconds=None)
    assert gate.record(category, 60) == RateLimitDecision(retry=False, wait_seconds=None)
    assert gate.check() is None
    assert gate.restriction() is None
    assert gate.remaining_seconds() == 0


def test_only_time_lifts_a_restriction() -> None:
    public = {name for name in dir(RestRateLimitGate) if not name.startswith("_")}
    assert public == {"check", "record", "restriction", "remaining_seconds", "policy"}
    for word in ("clear", "reset", "lift", "unban", "resume", "release", "open", "restore"):
        assert not any(word in name.lower() for name in dir(RestRateLimitGate)), word
    gate, clock = _gate()
    gate.record(_C.IP_BANNED, 30)
    gate.record(_C.RATE_LIMITED, 20)
    with pytest.raises(RateLimitBanActive):
        gate.check()
    clock.advance(29)
    with pytest.raises(RateLimitBanActive):
        gate.check()
    clock.advance(1)
    assert gate.check() is None


def test_remaining_seconds_round_up_without_float() -> None:
    gate, clock = _gate()
    gate.record(_C.RATE_LIMITED, 10)
    clock.now = clock.now + timedelta(seconds=8, microseconds=1)
    assert gate.remaining_seconds() == 2
    with pytest.raises(RateLimitPauseActive) as info:
        gate.check()
    assert info.value.retry_after_seconds == 2


def test_refusal_message_has_no_url_or_key() -> None:
    gate, _ = _gate()
    gate.record(_C.IP_BANNED, None)
    with pytest.raises(RestGateRefusal) as info:
        gate.check()
    text = str(info.value)
    assert "IP_BAN_418" in text
    assert str(WAIT_418) in text
    for forbidden in ("http", "://", "fapi", "binance", "key", "signature", "secret", "?"):
        assert forbidden not in text.lower(), forbidden
    assert info.value.args == (text,)


def test_gate_module_is_pure() -> None:
    path = Path(inspect.getfile(gate_mod))
    allowed = {
        "__future__",
        "threading",
        "dataclasses",
        "datetime",
        "collections.abc",
        "typing",
        "src.domain.exchange_errors",
        "src.adapters.binance_limits",
    }
    assert set(module_imports(path)) <= allowed
    assert float_constructor_calls(path) == []
    assert wall_clock_calls(path) == []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "sleep" not in names | attributes
    assert "float" not in names


def test_one_gate_is_safe_to_share_across_threads() -> None:
    gate, _ = _gate()
    assert isinstance(gate._lock, type(__import__("threading").Lock()))  # noqa: SLF001


# --------------------------------------------------------------------------- #
# The public-data reader holds the same gate (consistency with "block REST").
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


_PUBLIC_PAYLOADS: dict[str, Any] = {
    "kline_candlestick_data": [],
    "mark_price_kline_candlestick_data": [],
    "open_interest": SimpleNamespace(symbol="BTCUSDT", time=1_791_360_000_000, open_interest="1"),
    "open_interest_statistics": [],
    "get_funding_rate_history": [],
    "check_server_time": SimpleNamespace(server_time=1_791_360_000_000),
    "exchange_information": SimpleNamespace(symbols=[]),
    "cancel_order": SimpleNamespace(),
}


class _CountingRest:
    """Every SDK REST method counts its calls and raises a scripted exception once."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.raises: dict[str, BaseException] = {}

    def __getattr__(self, name: str) -> Any:
        if name not in _PUBLIC_PAYLOADS:
            raise AttributeError(name)

        def _call(*_: Any, **__: Any) -> _Response:
            self.calls[name] += 1
            exc = self.raises.pop(name, None)
            if exc is not None:
                raise exc
            return _Response(_PUBLIC_PAYLOADS[name])

        return _call


def _sdk() -> tuple[Any, _CountingRest]:
    rest = _CountingRest()
    return SimpleNamespace(rest_api=rest), rest


_PUBLIC_CALLS: dict[str, Any] = {
    "klines": (lambda r: r.klines("BTCUSDT", "1h"), "kline_candlestick_data"),
    "mark_klines": (lambda r: r.mark_klines("BTCUSDT", "1h"), "mark_price_kline_candlestick_data"),
    "open_interest": (lambda r: r.open_interest("BTCUSDT"), "open_interest"),
    "open_interest_statistics": (
        lambda r: r.open_interest_statistics("BTCUSDT", "1h"),
        "open_interest_statistics",
    ),
    "funding_rate": (lambda r: r.funding_rate("BTCUSDT"), "get_funding_rate_history"),
    "server_time": (lambda r: r.server_time(), "check_server_time"),
    "exchange_info": (lambda r: r.exchange_info(), "exchange_information"),
}


@pytest.mark.parametrize(
    ("category", "refusal"),
    [(_C.IP_BANNED, RateLimitBanActive), (_C.RATE_LIMITED, RateLimitPauseActive)],
    ids=["ban", "pause"],
)
def test_public_server_time_refused_while_gate_banned_or_paused(
    category: ExchangeErrorCategory, refusal: type[RestGateRefusal]
) -> None:
    gate, _ = _gate()
    gate.record(category, None)
    sdk, rest = _sdk()
    public = BinancePublicMarketData(sdk_client=sdk, rest_gate=gate)
    with pytest.raises(refusal):
        asyncio.run(public.server_time())
    assert rest.calls["check_server_time"] == 0
    adapter = BinanceUsdmAdapter(sdk_client=sdk, rest_gate=gate)
    with pytest.raises(refusal):
        asyncio.run(adapter.server_time())
    assert rest.calls["check_server_time"] == 0


@pytest.mark.parametrize("method", sorted(_PUBLIC_CALLS))
@pytest.mark.parametrize(
    ("category", "refusal"),
    [(_C.IP_BANNED, RateLimitBanActive), (_C.RATE_LIMITED, RateLimitPauseActive)],
    ids=["ban", "pause"],
)
def test_every_public_call_checks_the_gate_before_sending(
    method: str, category: ExchangeErrorCategory, refusal: type[RestGateRefusal]
) -> None:
    call, sdk_name = _PUBLIC_CALLS[method]
    gate, clock = _gate()
    sdk, rest = _sdk()
    public = BinancePublicMarketData(sdk_client=sdk, rest_gate=gate)
    asyncio.run(call(public))
    assert rest.calls[sdk_name] == 1
    gate.record(category, 5)
    with pytest.raises(refusal):
        asyncio.run(call(public))
    assert rest.calls[sdk_name] == 1
    clock.advance(5)
    asyncio.run(call(public))
    assert rest.calls[sdk_name] == 2


@pytest.mark.parametrize("method", sorted(_PUBLIC_CALLS))
@pytest.mark.parametrize(
    ("exc", "reason", "remaining"),
    [
        (RateLimitBanError("418", -1003, None), "IP_BAN_418", WAIT_418),
        (TooManyRequestsError("429", -1003, 7), "RATE_LIMIT_PAUSE_429", 7),
    ],
    ids=["418", "429"],
)
def test_every_public_call_records_a_rate_limit_answer(
    method: str, exc: BaseException, reason: str, remaining: int
) -> None:
    call, sdk_name = _PUBLIC_CALLS[method]
    gate, _ = _gate()
    sdk, rest = _sdk()
    rest.raises[sdk_name] = exc
    public = BinancePublicMarketData(sdk_client=sdk, rest_gate=gate)
    with pytest.raises(type(exc)) as info:
        asyncio.run(call(public))
    assert info.value is exc
    assert rest.calls[sdk_name] == 1  # never retried
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.reason == reason
    assert restriction.remaining_seconds == remaining


def test_public_rate_limit_answer_restricts_shared_gate() -> None:
    gate, _ = _gate()
    public_sdk, public_rest = _sdk()
    limited = TooManyRequestsError("429", -1003, None)
    public_rest.raises["exchange_information"] = limited
    public = BinancePublicMarketData(sdk_client=public_sdk, rest_gate=gate)
    with pytest.raises(TooManyRequestsError) as info:
        asyncio.run(public.exchange_info())
    assert info.value is limited
    assert public_rest.calls["exchange_information"] == 1
    assert gate.remaining_seconds() == WAIT_429

    other_sdk, other_rest = _sdk()
    other = BinanceUsdmAdapter(sdk_client=other_sdk, rest_gate=gate)
    with pytest.raises(RateLimitPauseActive):
        asyncio.run(other.cancel_normal_order(symbol="BTCUSDT", orig_client_order_id="e" * 36))
    assert other_rest.calls["cancel_order"] == 0


def test_public_reader_without_gate_is_unchanged() -> None:
    sdk, rest = _sdk()
    limited = TooManyRequestsError("429", -1003, 7)
    rest.raises["check_server_time"] = limited
    public = BinancePublicMarketData(sdk_client=sdk)
    with pytest.raises(TooManyRequestsError) as info:
        asyncio.run(public.server_time())
    assert info.value is limited
    asyncio.run(public.server_time())
    assert rest.calls["check_server_time"] == 2
