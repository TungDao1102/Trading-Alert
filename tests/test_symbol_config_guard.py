"""The symbol configuration guard (Phase 22, plan 22-11; D-01, D-03, D-04, D-06, criterion 1).

The tracer drives the REAL ``BinanceUsdmAdapter`` over a stateful fake SDK holding the recorded
Demo configuration (CROSSED, leverage 20, demo-observed, not mainnet): one marginType POST, one
leverage POST, one verifying read. The failure matrix drives the guard over a scripted port.
Executed unit tests against fakes [DESIGN]: the real Demo answers to the changes are unobserved
here (owner-run case ``symbol_config_change_to_isolated``).
"""

from __future__ import annotations

from decimal import Decimal

from src.execution.symbol_config_guard import (
    TARGET_LEVERAGE,
    TARGET_MARGIN_TYPE,
    SymbolConfigGuard,
)

from tests.support.config_guard_fakes import (
    LEVERAGE_POST,
    MARGIN_POST,
    READ,
    SYMBOL,
    StatefulConfigSdk,
    build_config_adapter,
)


def _guard(sdk: StatefulConfigSdk) -> SymbolConfigGuard:
    return SymbolConfigGuard(adapter=build_config_adapter(sdk), target_leverage=TARGET_LEVERAGE)


# --------------------------------------------------------------------------- tracer


async def test_constants_are_the_d035_cap_and_isolated() -> None:
    assert TARGET_LEVERAGE == 5
    assert isinstance(TARGET_LEVERAGE, int) and not isinstance(TARGET_LEVERAGE, bool)
    assert TARGET_MARGIN_TYPE == "ISOLATED"


async def test_tracer_the_recorded_crossed_x20_flat_symbol_becomes_isolated_x5() -> None:
    sdk = StatefulConfigSdk.from_recorded()
    assert (sdk.margin_type, sdk.leverage, sdk.auto_add) == ("CROSSED", 20, False)

    result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=True)

    assert result.ok is True
    assert result.reason_code == "OK"
    assert result.alert_reason is None
    assert result.margin_type == "ISOLATED"
    assert result.leverage == 5
    # The figure comes from the LAST read (the exchange moves it with the leverage).
    assert result.max_notional_value == Decimal("100000000")
    assert result.changed is True
    assert result.previous_margin_type == "CROSSED"
    assert result.previous_leverage == 20
    assert result.posts_sent == 2
    assert sdk.calls == [READ, MARGIN_POST, LEVERAGE_POST, READ]
    assert sdk.margin_type_args == ["ISOLATED"]
    assert sdk.leverage_args == [5]


async def test_a_configuration_that_already_matches_costs_one_read() -> None:
    for flat in (True, False):
        sdk = StatefulConfigSdk(margin_type="ISOLATED", leverage=5, max_notional="100000000")
        result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=flat)
        assert result.ok is True
        assert result.reason_code == "OK"
        assert result.changed is False
        assert result.posts_sent == 0
        assert result.margin_type == "ISOLATED"
        assert result.leverage == 5
        assert result.max_notional_value == Decimal("100000000")
        assert sdk.calls == [READ]


async def test_ensure_is_idempotent_across_runs() -> None:
    sdk = StatefulConfigSdk.from_recorded()
    guard = _guard(sdk)
    first = await guard.ensure(symbol=SYMBOL, symbol_is_flat=True)
    sdk.calls.clear()
    second = await guard.ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert first.ok is True and first.posts_sent == 2
    assert second.ok is True
    assert second.changed is False
    assert second.posts_sent == 0
    assert sdk.calls == [READ]
