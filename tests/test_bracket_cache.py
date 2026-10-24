"""BracketCache (Phase 22, plan 22-12; D-11, criterion 2, assumption A8).

The tracer runs the recorded Demo bracket table (demo-observed, not mainnet) through the REAL
``BinanceUsdmAdapter`` over a fake SDK, the cache and the pure ``liquidation_verdict``. The rest of
the file pins the freshness boundaries and the fail-closed behavior with a scripted adapter.
Every age bound, buffer and fee below is a TEST_ONLY value, never the owner's choice.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive
from src.adapters.binance_usdm import LeverageBracketRow, SymbolLeverageBrackets
from src.execution.bracket_cache import BracketCache, BracketReading
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.risk.liquidation import LIQUIDATION_OK, liquidation_verdict
from structlog.testing import capture_logs

from tests.support.ast_guards import forbidden_imports, wall_clock_calls
from tests.support.bracket_fakes import (
    SDK_METHOD,
    ScriptedBracketAdapter,
    build_bracket_adapter,
    demo_table,
)
from tests.support.execution_limits import test_only_execution_limits as only_limits
from tests.support.phase22_fixtures import demo_brackets
from tests.support.virtual_time import VirtualTime

MODULE = Path(__file__).resolve().parent.parent / "src" / "execution" / "bracket_cache.py"
SYMBOL = "BTCUSDT"
OTHER_SYMBOL = "ETHUSDT"
G1 = Decimal("64257.028112449799")
AGE_MS = only_limits().margin_max_bracket_age_ms  # TEST_ONLY value of margin.max_bracket_age_ms
assert AGE_MS is not None
MAX_AGE = timedelta(milliseconds=AGE_MS)
BUFFER_BPS = 100  # TEST_ONLY
NO_FEE = Decimal("0")  # TEST_ONLY


class MovingClock:
    """A plain mutable clock for the fake SDK (its calls are synchronous worker-thread calls)."""

    def __init__(self) -> None:
        self.value = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _cache(adapter: object, clock: object, **limit_overrides: int | None) -> BracketCache:
    return BracketCache(
        adapter=adapter,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        limits=only_limits(**limit_overrides),
    )


# --------------------------------------------------------------------------- Task 1: tracer


async def test_recorded_demo_table_reaches_the_liquidation_verdict_through_the_real_adapter() -> (
    None
):
    clock = MovingClock()

    def advance(_: str) -> None:
        clock.value += timedelta(seconds=1)

    adapter, rest = build_bracket_adapter(on_sdk_call=advance)
    start = clock()
    cache = _cache(adapter, clock)
    reading = await cache.get(symbol=SYMBOL)
    assert reading is not None
    assert cache.last_error_type is None
    assert rest.called == [SDK_METHOD]
    assert rest.kwargs[0]["symbol"] == SYMBOL
    assert reading.symbol == SYMBOL
    assert len(reading.brackets) == 10
    assert list(reading.brackets) == demo_brackets()
    # Stamped BEFORE the request: the age is only over-estimated.
    assert reading.observed_at_utc == start
    assert clock() - start == timedelta(seconds=1)

    verdict = liquidation_verdict(
        side="LONG",
        entry_price=Decimal("80000"),
        quantity=Decimal("0.01"),
        leverage=5,
        brackets=reading.brackets,
        stop_price=Decimal("66000"),
        buffer_bps=BUFFER_BPS,
        entry_fee_rate=NO_FEE,
    )
    assert verdict.ok is True
    assert verdict.reason_code == LIQUIDATION_OK
    assert verdict.liquidation_price is not None
    assert verdict.liquidation_price.quantize(Decimal("1E-12")) == G1


async def test_a_second_get_inside_the_bound_makes_no_call_and_the_boundary_is_inclusive() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([demo_table(), demo_table()])
    cache = _cache(port, clock)
    first = await cache.get(symbol=SYMBOL)
    assert first is not None
    stamp = first.observed_at_utc
    assert port.calls == [SYMBOL]

    await clock.advance(MAX_AGE.total_seconds() / 2)
    again = await cache.get(symbol=SYMBOL)
    assert again is first
    assert port.calls == [SYMBOL]

    # Exactly the bound since observed_at_utc: still fresh (equal passes), no call.
    await clock.advance(MAX_AGE.total_seconds() / 2)
    assert clock() - stamp == MAX_AGE
    at_bound = await cache.get(symbol=SYMBOL)
    assert at_bound is first
    assert port.calls == [SYMBOL]

    # One microsecond later: stale, so exactly one more read.
    await clock.advance(0.000001)
    assert clock() - stamp == MAX_AGE + timedelta(microseconds=1)
    refreshed = await cache.get(symbol=SYMBOL)
    assert refreshed is not None and refreshed is not first
    assert port.calls == [SYMBOL, SYMBOL]
    assert refreshed.observed_at_utc == clock()


# --------------------------------------------------------------------------- Task 2: fail closed


async def test_a_backwards_clock_forces_a_refresh() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([demo_table(), demo_table()])
    cache = _cache(port, clock)
    assert await cache.get(symbol=SYMBOL) is not None
    await clock.advance(-1)  # an observation from the future: negative age
    assert await cache.get(symbol=SYMBOL) is not None
    assert port.calls == [SYMBOL, SYMBOL]


async def test_a_read_slower_than_the_bound_returns_none_and_keeps_nothing() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter(
        [demo_table(), demo_table()],
        virtual_time=clock,
        advance_per_call=MAX_AGE + timedelta(milliseconds=1),
    )
    cache = _cache(port, clock)
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == "StaleBracketReading"
    # Nothing was kept: the next get reads again (and is again too slow).
    assert await cache.get(symbol=SYMBOL) is None
    assert port.calls == [SYMBOL, SYMBOL]


async def test_a_read_that_takes_exactly_the_bound_is_still_fresh() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([demo_table()], virtual_time=clock, advance_per_call=MAX_AGE)
    cache = _cache(port, clock)
    reading = await cache.get(symbol=SYMBOL)
    assert reading is not None
    assert clock() - reading.observed_at_utc == MAX_AGE


@pytest.mark.parametrize(
    "error", [RateLimitPauseActive(0), RuntimeError("boom 64257.02"), ValueError("bad field")]
)
async def test_a_failed_read_is_none_recorded_by_type_and_never_retried(
    error: BaseException,
) -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([error, error])
    cache = _cache(port, clock)
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == type(error).__name__
    assert port.calls == [SYMBOL]  # once: no retry
    assert clock.sleeps == []  # and never slept on


async def test_a_failure_drops_the_cache_and_a_later_success_clears_the_error() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([demo_table(), RuntimeError("down"), demo_table()])
    cache = _cache(port, clock)
    assert await cache.get(symbol=SYMBOL) is not None
    await clock.advance(MAX_AGE.total_seconds() + 1)  # stale: a refresh is due
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == "RuntimeError"
    # No stale fallback: the earlier reading is gone, the next get reads again.
    recovered = await cache.get(symbol=SYMBOL)
    assert recovered is not None
    assert cache.last_error_type is None
    assert port.calls == [SYMBOL] * 3


@pytest.mark.parametrize("coef", [None, Decimal("1"), Decimal("1.0")])
async def test_a_notional_coefficient_of_one_or_none_is_accepted(coef: Decimal | None) -> None:
    port = ScriptedBracketAdapter([demo_table(notional_coef=coef)])
    reading = await _cache(port, VirtualTime()).get(symbol=SYMBOL)
    assert reading is not None
    assert len(reading.brackets) == 10


@pytest.mark.parametrize(
    "coef", [Decimal("1.1"), Decimal("0.9"), Decimal("0"), Decimal("NaN"), Decimal("-1")]
)
async def test_a_notional_coefficient_other_than_one_makes_the_set_unusable(coef: Decimal) -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([demo_table(notional_coef=coef)])
    cache = _cache(port, clock)
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == "ValueError"


async def test_a_coefficient_of_the_wrong_type_is_unusable() -> None:
    bad = dataclasses.replace(demo_table(), notional_coef=1.0)  # type: ignore[arg-type]
    port = ScriptedBracketAdapter([bad])
    cache = _cache(port, VirtualTime())
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == "TypeError"


def _row(**overrides: Any) -> LeverageBracketRow:
    fields: dict[str, Any] = dataclasses.asdict(demo_table().brackets[0])
    fields.update(overrides)
    return LeverageBracketRow(**fields)


@pytest.mark.parametrize(
    "overrides",
    [
        {"cum": Decimal("-1")},
        {"maint_margin_ratio": Decimal("1")},
        {"notional_floor": Decimal("50000")},  # floor equal to the cap
        {"notional_floor": Decimal("60000")},  # floor above the cap
    ],
)
async def test_a_malformed_row_is_none_and_never_raises(overrides: dict[str, Any]) -> None:
    table = SymbolLeverageBrackets(symbol=SYMBOL, notional_coef=None, brackets=(_row(**overrides),))
    port = ScriptedBracketAdapter([table])
    cache = _cache(port, VirtualTime())
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type in {"ValueError", "TypeError"}


async def test_an_empty_bracket_tuple_is_none() -> None:
    table = SymbolLeverageBrackets(symbol=SYMBOL, notional_coef=None, brackets=())
    cache = _cache(ScriptedBracketAdapter([table]), VirtualTime())
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == "ValueError"


async def test_a_table_for_another_symbol_is_refused() -> None:
    port = ScriptedBracketAdapter([demo_table(symbol=OTHER_SYMBOL)])
    cache = _cache(port, VirtualTime())
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == "ValueError"


async def test_two_symbols_are_cached_independently() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([demo_table(), demo_table(symbol=OTHER_SYMBOL)])
    cache = _cache(port, clock)
    btc = await cache.get(symbol=SYMBOL)
    eth = await cache.get(symbol=OTHER_SYMBOL)
    assert btc is not None and eth is not None
    assert (btc.symbol, eth.symbol) == (SYMBOL, OTHER_SYMBOL)
    assert port.calls == [SYMBOL, OTHER_SYMBOL]
    assert await cache.get(symbol=SYMBOL) is btc
    assert await cache.get(symbol=OTHER_SYMBOL) is eth
    assert port.calls == [SYMBOL, OTHER_SYMBOL]


async def test_invalidate_one_symbol_drops_only_that_symbol_and_none_drops_all() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter(
        [
            demo_table(),
            demo_table(symbol=OTHER_SYMBOL),
            demo_table(),
            demo_table(),
            demo_table(symbol=OTHER_SYMBOL),
        ]
    )
    cache = _cache(port, clock)
    await cache.get(symbol=SYMBOL)
    eth = await cache.get(symbol=OTHER_SYMBOL)
    cache.invalidate(symbol=SYMBOL)
    assert await cache.get(symbol=OTHER_SYMBOL) is eth  # untouched
    assert port.calls == [SYMBOL, OTHER_SYMBOL]
    assert await cache.get(symbol=SYMBOL) is not None  # read again
    assert port.calls == [SYMBOL, OTHER_SYMBOL, SYMBOL]
    cache.invalidate()
    assert await cache.get(symbol=SYMBOL) is not None
    assert await cache.get(symbol=OTHER_SYMBOL) is not None
    assert port.calls == [SYMBOL, OTHER_SYMBOL, SYMBOL, SYMBOL, OTHER_SYMBOL]


@pytest.mark.parametrize("scope", ["symbol", "all"])
async def test_an_invalidate_during_a_read_discards_its_result(scope: str) -> None:
    clock = VirtualTime()
    holder: dict[str, BracketCache] = {}

    def racing(_: str) -> None:
        if scope == "symbol":
            holder["cache"].invalidate(symbol=SYMBOL)
        else:
            holder["cache"].invalidate()

    port = ScriptedBracketAdapter([demo_table(), demo_table()], on_call=racing)
    cache = _cache(port, clock)
    holder["cache"] = cache
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type is None  # the read itself succeeded
    # Nothing was published: the next get reads again.
    assert await cache.get(symbol=SYMBOL) is None
    assert port.calls == [SYMBOL, SYMBOL]


async def test_an_invalidate_of_another_symbol_does_not_discard_a_read() -> None:
    holder: dict[str, BracketCache] = {}
    port = ScriptedBracketAdapter(
        [demo_table()], on_call=lambda _: holder["cache"].invalidate(symbol=OTHER_SYMBOL)
    )
    cache = _cache(port, VirtualTime())
    holder["cache"] = cache
    assert await cache.get(symbol=SYMBOL) is not None


async def test_the_age_bound_comes_from_the_limit_key() -> None:
    clock = VirtualTime()
    port = ScriptedBracketAdapter([demo_table(), demo_table()])
    cache = _cache(port, clock, margin_max_bracket_age_ms=500)
    first = await cache.get(symbol=SYMBOL)
    await clock.advance(0.5)
    assert await cache.get(symbol=SYMBOL) is first
    await clock.advance(0.001)
    assert await cache.get(symbol=SYMBOL) is not first
    assert port.calls == [SYMBOL, SYMBOL]


def test_construction_refuses_while_the_age_limit_is_not_configured() -> None:
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        _cache(ScriptedBracketAdapter([]), VirtualTime(), margin_max_bracket_age_ms=None)
    assert caught.value.keys == ("margin.max_bracket_age_ms",)


@pytest.mark.parametrize("bad_age", [0, -5])
def test_construction_refuses_a_non_positive_age(bad_age: int) -> None:
    with pytest.raises(ValueError):
        _cache(ScriptedBracketAdapter([]), VirtualTime(), margin_max_bracket_age_ms=bad_age)


def test_construction_refuses_a_bad_clock_or_adapter() -> None:
    with pytest.raises(TypeError):
        _cache(ScriptedBracketAdapter([]), "not callable")
    with pytest.raises(TypeError):
        _cache(None, VirtualTime())
    with pytest.raises(TypeError):
        _cache(object(), VirtualTime())
    with pytest.raises(TypeError):
        BracketCache(
            adapter=ScriptedBracketAdapter([]),
            clock=VirtualTime(),
            limits=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("bad", ["", " ", 5, None])
async def test_a_bad_symbol_is_refused(bad: object) -> None:
    cache = _cache(ScriptedBracketAdapter([]), VirtualTime())
    with pytest.raises(ValueError):
        await cache.get(symbol=bad)  # type: ignore[arg-type]
    if bad is not None:  # invalidate(symbol=None) means "all symbols"
        with pytest.raises(ValueError):
            cache.invalidate(symbol=bad)  # type: ignore[arg-type]


async def test_a_naive_clock_value_is_a_failed_read_not_an_exception() -> None:
    cache = _cache(ScriptedBracketAdapter([demo_table()]), lambda: datetime(2026, 10, 22))
    assert await cache.get(symbol=SYMBOL) is None
    assert cache.last_error_type == "ValueError"


async def test_a_base_exception_propagates() -> None:
    class _Stop(BaseException):
        pass

    cache = _cache(ScriptedBracketAdapter([_Stop()]), VirtualTime())
    with pytest.raises(_Stop):
        await cache.get(symbol=SYMBOL)


def test_the_reading_is_a_frozen_value() -> None:
    reading = BracketReading(
        symbol=SYMBOL,
        brackets=tuple(demo_brackets()),
        observed_at_utc=VirtualTime()(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        reading.symbol = OTHER_SYMBOL  # type: ignore[misc]


async def test_logs_carry_no_bracket_value_and_no_exception_text() -> None:
    clock = VirtualTime()
    with capture_logs() as ok_logs:
        await _cache(ScriptedBracketAdapter([demo_table()]), clock).get(symbol=SYMBOL)
    with capture_logs() as bad_logs:
        await _cache(ScriptedBracketAdapter([RuntimeError("secret-token 0.004")]), clock).get(
            symbol=SYMBOL
        )
    assert ok_logs == []
    assert bad_logs == []


def test_the_module_reads_no_wall_clock_and_imports_no_adapter_store_or_sdk() -> None:
    assert wall_clock_calls(MODULE) == []
    assert (
        forbidden_imports(MODULE, ["src.adapters", "src.persistence", "binance*", "sqlalchemy"])
        == []
    )
    source = MODULE.read_text(encoding="utf-8")
    assert "USDT" not in source
    assert "float(" not in source
