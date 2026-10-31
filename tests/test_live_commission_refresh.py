"""Tests for the live commission cache (plan 24-15; D-22, G3-008).

A fake adapter and ``VirtualTime`` drive the cache; nothing reads a wall clock. Oracles are
literal Decimals and literal instants, none computed by the code under test.

Setup: TTL 3600 s, refresh margin 60 s (one reconcile tick), so a reading is due again once it is
3540 s old. Parameter rates: fee 0.0005 / 0.0005, slippage 0.0001 / 0.0003.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from src.live.commission import CommissionCache, CommissionRefreshEvent
from src.risk.cost_rates import FEE_SOURCE_ACCOUNT_MAX, FEE_SOURCE_PARAMETER, CostRates
from src.risk.live_commission import AccountCommission

from tests.support.virtual_time import VirtualTime

TTL = timedelta(seconds=3600)
MARGIN = timedelta(seconds=60)
UNCERTAIN = "UNCERTAIN_ACCOUNT_STATE"
SYMBOLS = ("BTCUSDT", "ETHUSDT")


def _rates(symbol: str, maker: str = "0.0002", taker: str = "0.0004") -> Any:
    return SimpleNamespace(symbol=symbol, maker_rate=Decimal(maker), taker_rate=Decimal(taker))


class FakeAdapter:
    """Answers ``user_commission_rate`` per symbol; a value that is an Exception is raised."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def user_commission_rate(self, symbol: str) -> Any:
        self.calls.append(symbol)
        answer = self.answers[symbol]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _parameter_rates() -> CostRates:
    return CostRates(
        fee_rate_entry=Decimal("0.0005"),
        entry_slippage_rate=Decimal("0.0001"),
        fee_rate_exit=Decimal("0.0005"),
        exit_slippage_rate=Decimal("0.0003"),
        fee_source=FEE_SOURCE_PARAMETER,
    )


def _build(
    answers: dict[str, Any] | None = None,
    *,
    symbols: tuple[str, ...] = SYMBOLS,
    events: list[CommissionRefreshEvent] | None = None,
) -> tuple[CommissionCache, FakeAdapter, VirtualTime]:
    adapter = FakeAdapter(
        answers
        if answers is not None
        else {"BTCUSDT": _rates("BTCUSDT"), "ETHUSDT": _rates("ETHUSDT", taker="0.0006")}
    )
    vt = VirtualTime()

    async def record(event: CommissionRefreshEvent) -> None:
        assert events is not None
        events.append(event)

    cache = CommissionCache(
        adapter=adapter,
        clock=vt,
        symbols=symbols,
        ttl=TTL,
        refresh_margin=MARGIN,
        record=record if events is not None else None,
    )
    return cache, adapter, vt


# --------------------------------------------------------------------------- #
# Tracer: a due refresh reads through the adapter and a plan's cost rates resolve from it.
# --------------------------------------------------------------------------- #


async def test_due_refresh_reads_each_symbol_once_then_waits_for_the_margin() -> None:
    cache, adapter, vt = _build()
    refreshed = await cache.refresh_due()
    assert refreshed == SYMBOLS
    assert adapter.calls == ["BTCUSDT", "ETHUSDT"]

    await vt.advance(3539)  # one second short of TTL minus margin
    assert await cache.refresh_due() == ()
    assert adapter.calls == ["BTCUSDT", "ETHUSDT"]

    await vt.advance(1)  # exactly TTL minus margin: due again
    assert await cache.refresh_due() == SYMBOLS
    assert adapter.calls == ["BTCUSDT", "ETHUSDT"] * 2


async def test_cached_reading_resolves_live_cost_rates_from_the_account_taker() -> None:
    cache, _, _ = _build()
    await cache.refresh_due()
    result = cache.cost_rates_for(parameter_rates=_parameter_rates(), symbol="ETHUSDT")
    assert result.rates is not None
    assert result.reason_code == "OK"
    assert result.rates.fee_source == FEE_SOURCE_ACCOUNT_MAX
    assert result.rates.fee_rate_entry == Decimal("0.0006")
    assert result.rates.fee_rate_exit == Decimal("0.0006")
    assert result.rates.account_symbol == "ETHUSDT"


async def test_account_commission_for_returns_the_stamped_reading() -> None:
    cache, _, vt = _build()
    await cache.refresh_due()
    reading = cache.account_commission_for("BTCUSDT")
    assert reading == AccountCommission(
        symbol="BTCUSDT",
        maker_rate=Decimal("0.0002"),
        taker_rate=Decimal("0.0004"),
        observed_at_utc=vt.now(),
    )


async def test_never_refreshed_symbol_is_no_trade() -> None:
    cache, _, _ = _build()
    assert cache.account_commission_for("BTCUSDT") is None
    result = cache.cost_rates_for(parameter_rates=_parameter_rates(), symbol="BTCUSDT")
    assert result.rates is None
    assert result.reason_code == UNCERTAIN


async def test_untracked_symbol_is_no_trade_and_never_read() -> None:
    cache, adapter, _ = _build()
    await cache.refresh_due()
    assert cache.account_commission_for("SOLUSDT") is None
    result = cache.cost_rates_for(parameter_rates=_parameter_rates(), symbol="SOLUSDT")
    assert result.reason_code == UNCERTAIN
    assert "SOLUSDT" not in adapter.calls


async def test_reading_older_than_the_ttl_is_no_trade() -> None:
    cache, adapter, vt = _build({"BTCUSDT": _rates("BTCUSDT")}, symbols=("BTCUSDT",))
    await cache.refresh_due()
    adapter.answers["BTCUSDT"] = RuntimeError("down")
    await vt.advance(3600)  # age equals the TTL: still valid
    assert cache.account_commission_for("BTCUSDT") is not None
    await vt.advance(1)  # one second past the TTL
    assert cache.account_commission_for("BTCUSDT") is None
    result = cache.cost_rates_for(parameter_rates=_parameter_rates(), symbol="BTCUSDT")
    assert result.rates is None
    assert result.reason_code == UNCERTAIN


# --------------------------------------------------------------------------- #
# Failure handling: previous reading until its own TTL, journaled by class, no retry.
# --------------------------------------------------------------------------- #


async def test_failed_refresh_keeps_the_previous_reading_until_its_ttl() -> None:
    events: list[CommissionRefreshEvent] = []
    cache, adapter, vt = _build(events=events)
    await cache.refresh_due()
    adapter.answers["BTCUSDT"] = RuntimeError("secret detail must not be kept")
    await vt.advance(3540)

    assert await cache.refresh_due() == ("ETHUSDT",)  # BTCUSDT failed, ETHUSDT unaffected
    assert adapter.calls.count("BTCUSDT") == 2  # one call in this due refresh, no retry
    assert cache.account_commission_for("BTCUSDT") is not None  # 3540 s old, TTL not yet over
    assert cache.account_commission_for("ETHUSDT") is not None
    assert cache.last_error_types == {"BTCUSDT": "RuntimeError"}
    assert events == [
        CommissionRefreshEvent(symbol="BTCUSDT", error_class="RuntimeError", at_utc=vt.now())
    ]
    assert "secret" not in repr(events)

    await vt.advance(61)  # BTCUSDT's own reading is now 3601 s old
    assert cache.account_commission_for("BTCUSDT") is None
    assert cache.account_commission_for("ETHUSDT") is not None


async def test_failure_is_retried_only_by_the_next_due_call_not_inside_one() -> None:
    cache, adapter, _ = _build({"BTCUSDT": TimeoutError("x")}, symbols=("BTCUSDT",))
    assert await cache.refresh_due() == ()
    assert adapter.calls == ["BTCUSDT"]  # exactly one call


async def test_a_failure_with_no_previous_reading_stays_no_trade() -> None:
    cache, _, _ = _build({"BTCUSDT": TimeoutError("x")}, symbols=("BTCUSDT",))
    await cache.refresh_due()
    assert cache.account_commission_for("BTCUSDT") is None
    assert cache.cost_rates_for(parameter_rates=_parameter_rates(), symbol="BTCUSDT").rates is None


async def test_journal_gets_a_change_of_outcome_only() -> None:
    events: list[CommissionRefreshEvent] = []
    cache, adapter, vt = _build({"BTCUSDT": TimeoutError("x")}, symbols=("BTCUSDT",), events=events)
    await cache.refresh_due()
    await cache.refresh_due()  # same class again: not journaled again
    adapter.answers["BTCUSDT"] = RuntimeError("y")
    await cache.refresh_due()  # another class
    adapter.answers["BTCUSDT"] = _rates("BTCUSDT")
    await cache.refresh_due()  # recovery
    await vt.advance(10)
    await cache.refresh_due()  # not due: nothing
    assert [(e.kind, e.error_class) for e in events] == [
        ("failure", "TimeoutError"),
        ("failure", "RuntimeError"),
        ("recovery", None),
    ]


def test_refresh_event_refuses_inconsistent_fields() -> None:
    vt = VirtualTime()
    with pytest.raises(ValueError):
        CommissionRefreshEvent(symbol="BTCUSDT", error_class=None, at_utc=vt.now())
    with pytest.raises(ValueError):
        CommissionRefreshEvent(symbol="BTCUSDT", error_class="X", at_utc=vt.now(), kind="recovery")


async def test_recovery_clears_the_error_class() -> None:
    cache, adapter, vt = _build({"BTCUSDT": TimeoutError("x")}, symbols=("BTCUSDT",))
    await cache.refresh_due()
    assert cache.last_error_types == {"BTCUSDT": "TimeoutError"}
    adapter.answers["BTCUSDT"] = _rates("BTCUSDT")
    await cache.refresh_due()  # no reading yet, so due at once
    assert cache.last_error_types == {}
    assert cache.account_commission_for("BTCUSDT") is not None
    assert vt.now() is not None


async def test_a_record_that_raises_does_not_stop_the_refresh() -> None:
    adapter = FakeAdapter({"BTCUSDT": TimeoutError("x"), "ETHUSDT": _rates("ETHUSDT")})

    async def broken(event: CommissionRefreshEvent) -> None:
        raise OSError("journal down")

    vt = VirtualTime()
    cache = CommissionCache(
        adapter=adapter, clock=vt, symbols=SYMBOLS, ttl=TTL, refresh_margin=MARGIN, record=broken
    )
    assert await cache.refresh_due() == ("ETHUSDT",)


async def test_base_exception_propagates() -> None:
    cache, _, _ = _build({"BTCUSDT": KeyboardInterrupt()}, symbols=("BTCUSDT",))
    with pytest.raises(KeyboardInterrupt):
        await cache.refresh_due()


# --------------------------------------------------------------------------- #
# Invalid responses give no reading (fail closed, T-24-41).
# --------------------------------------------------------------------------- #


async def test_negative_maker_response_gives_no_reading() -> None:
    cache, _, _ = _build({"BTCUSDT": _rates("BTCUSDT", maker="-0.0001")}, symbols=("BTCUSDT",))
    assert await cache.refresh_due() == ()
    assert cache.account_commission_for("BTCUSDT") is None
    assert cache.last_error_types == {"BTCUSDT": "ValueError"}


async def test_wrong_symbol_response_gives_no_reading() -> None:
    cache, _, _ = _build({"BTCUSDT": _rates("ETHUSDT")}, symbols=("BTCUSDT",))
    assert await cache.refresh_due() == ()
    assert cache.account_commission_for("BTCUSDT") is None
    assert cache.account_commission_for("ETHUSDT") is None


async def test_an_invalid_response_drops_the_previous_reading() -> None:
    cache, adapter, vt = _build({"BTCUSDT": _rates("BTCUSDT")}, symbols=("BTCUSDT",))
    await cache.refresh_due()
    assert cache.account_commission_for("BTCUSDT") is not None
    adapter.answers["BTCUSDT"] = _rates("BTCUSDT", taker="-0.1")
    await vt.advance(3540)
    await cache.refresh_due()
    assert cache.account_commission_for("BTCUSDT") is None


async def test_rejected_response_never_carries_a_zero_fee() -> None:
    cache, _, _ = _build({"BTCUSDT": _rates("BTCUSDT", maker="-1")}, symbols=("BTCUSDT",))
    await cache.refresh_due()
    result = cache.cost_rates_for(parameter_rates=_parameter_rates(), symbol="BTCUSDT")
    assert result.rates is None
    assert result.reason_code == UNCERTAIN
    assert await cache.entry_fee_rate(symbol="BTCUSDT") is None


# --------------------------------------------------------------------------- #
# The liquidation watch's fee-rate port (plan 24-16) answers from the same readings.
# --------------------------------------------------------------------------- #


async def test_entry_fee_rate_is_the_account_taker_rate() -> None:
    cache, _, _ = _build()
    await cache.refresh_due()
    assert await cache.entry_fee_rate(symbol="BTCUSDT") == Decimal("0.0004")
    assert await cache.entry_fee_rate(symbol="ETHUSDT") == Decimal("0.0006")


async def test_entry_fee_rate_zero_is_a_real_rate() -> None:
    cache, _, _ = _build({"BTCUSDT": _rates("BTCUSDT", taker="0")}, symbols=("BTCUSDT",))
    await cache.refresh_due()
    assert await cache.entry_fee_rate(symbol="BTCUSDT") == Decimal("0")


async def test_entry_fee_rate_is_none_when_unknown_or_stale() -> None:
    cache, adapter, vt = _build({"BTCUSDT": _rates("BTCUSDT")}, symbols=("BTCUSDT",))
    assert await cache.entry_fee_rate(symbol="BTCUSDT") is None
    await cache.refresh_due()
    adapter.answers["BTCUSDT"] = RuntimeError("down")
    await vt.advance(3601)
    assert await cache.entry_fee_rate(symbol="BTCUSDT") is None


def test_cache_satisfies_the_liquidation_watch_port() -> None:
    from src.execution.liquidation_watch import EntryFeeRateSource

    cache, _, _ = _build()
    port: EntryFeeRateSource = cache  # a static check under mypy
    assert port is cache


# --------------------------------------------------------------------------- #
# Construction refusals.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs",
    [
        {"symbols": ()},
        {"symbols": ("btcusdt",)},
        {"symbols": ("BTCUSDT", "BTCUSDT")},
        {"symbols": ("",)},
        {"ttl": timedelta(0)},
        {"ttl": timedelta(seconds=-1)},
        {"refresh_margin": timedelta(seconds=-1)},
    ],
)
def test_construction_refuses_bad_arguments(kwargs: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "adapter": FakeAdapter({}),
        "clock": VirtualTime(),
        "symbols": SYMBOLS,
        "ttl": TTL,
        "refresh_margin": MARGIN,
    }
    base.update(kwargs)
    with pytest.raises((ValueError, TypeError)):
        CommissionCache(**base)


def test_construction_refuses_an_adapter_without_the_read() -> None:
    with pytest.raises(TypeError):
        CommissionCache(
            adapter=object(),  # type: ignore[arg-type]
            clock=VirtualTime(),
            symbols=SYMBOLS,
            ttl=TTL,
            refresh_margin=MARGIN,
        )


async def test_margin_at_or_above_the_ttl_refreshes_on_every_call() -> None:
    adapter = FakeAdapter({"BTCUSDT": _rates("BTCUSDT")})
    cache = CommissionCache(
        adapter=adapter,
        clock=VirtualTime(),
        symbols=("BTCUSDT",),
        ttl=TTL,
        refresh_margin=TTL,
    )
    await cache.refresh_due()
    await cache.refresh_due()
    assert adapter.calls == ["BTCUSDT", "BTCUSDT"]
