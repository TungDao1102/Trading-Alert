"""Post-fill liquidation watch (Phase 22, plan 22-13, task 1; D-12, amendment A10, owner item O-4).

The exchange `liquidationPrice` of a filled position is judged with the strict D-09 predicate of
`src.risk.liquidation`, measured from the actual fill price, and compared with the local price.
Oracles: the recorded Demo bracket table (demo-observed, not mainnet) through
`tests/support/phase22_fixtures.py`; the buffer is the TEST_ONLY `margin.liquidation_buffer_bps`
(a FAKE number, never an owner value). The exchange text "0" is the cross-margin sentinel of every
recorded Demo row and must fail closed. Nothing here is Demo-proven for an isolated position.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.execution import liquidation_watch
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.liquidation_watch import (
    LIQUIDATION_PRICE_DIFFERS,
    LIQUIDATION_TOO_CLOSE_AFTER_FILL,
    LIQUIDATION_UNKNOWN_AFTER_FILL,
    LiquidationFailurePolicy,
    LiquidationWatch,
    LiquidationWatchAction,
    LiquidationWatchInput,
    LiquidationWatchVerdict,
)
from src.risk.liquidation import LIQUIDATION_OK, Bracket

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.phase22_fixtures import demo_brackets

MODULE = Path(liquidation_watch.__file__)
D = Decimal
CLOSE_POLICY = LiquidationFailurePolicy.CLOSE_POSITION
ALERT_POLICY = LiquidationFailurePolicy.ALERT_ONLY
NO_FEE = D("0")
# The recorded Demo isolated LONG (entry 80845.8, quantity 0.0014, leverage 5, fee 0.0004).
G6_EXCHANGE = D("64968.85373637")


@dataclass(frozen=True)
class _Reading:
    brackets: Sequence[Bracket]


class _Brackets:
    def __init__(self, *, reading: _Reading | None, error: Exception | None = None) -> None:
        self._reading = reading
        self._error = error
        self.calls: list[str] = []

    async def get(self, *, symbol: str) -> _Reading | None:
        self.calls.append(symbol)
        if self._error is not None:
            raise self._error
        return self._reading


class _Fees:
    def __init__(self, rate: Decimal | None, error: Exception | None = None) -> None:
        self._rate = rate
        self._error = error
        self.calls: list[str] = []

    async def entry_fee_rate(self, *, symbol: str) -> Decimal | None:
        self.calls.append(symbol)
        if self._error is not None:
            raise self._error
        return self._rate


def _watch(
    *,
    policy: LiquidationFailurePolicy = CLOSE_POLICY,
    brackets: _Brackets | None = None,
    fees: _Fees | None = None,
) -> LiquidationWatch:
    return LiquidationWatch(
        brackets=brackets if brackets is not None else _Brackets(reading=_Reading(demo_brackets())),
        fee_rates=fees if fees is not None else _Fees(NO_FEE),
        limits=limits_with(),
        policy=policy,
    )


def _inputs(**overrides: Any) -> LiquidationWatchInput:
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "stop_price": D("66000"),
        "leverage": 5,
        "quantity": D("0.01"),
        "entry_price": D("80000"),
        "exchange_liquidation_price": D("64257.03"),
    }
    fields.update(overrides)
    return LiquidationWatchInput(**fields)


# --- the tracer: a pass is OK or OK_DIFFERS, a danger closes --------------------------------------


async def test_equal_at_the_exchange_decimal_places_is_ok_with_both_prices() -> None:
    # Local G1 is 64257.028112449799...; at the exchange's two places it is 64257.03.
    verdict = await _watch().check(_inputs())
    assert verdict.action is LiquidationWatchAction.OK
    assert verdict.reason == LIQUIDATION_OK
    assert verdict.exchange_price == D("64257.03")
    assert verdict.local_price is not None
    assert verdict.local_price.quantize(D("1E-12")) == D("64257.028112449799")


async def test_a_different_exchange_value_that_passes_is_ok_differs_with_both_prices() -> None:
    verdict = await _watch().check(_inputs(exchange_liquidation_price=D("64257.04")))
    assert verdict.action is LiquidationWatchAction.OK_DIFFERS
    assert verdict.reason == LIQUIDATION_PRICE_DIFFERS
    assert verdict.exchange_price == D("64257.04")
    assert verdict.local_price is not None
    assert verdict.local_price.quantize(D("1E-12")) == D("64257.028112449799")


async def test_the_recorded_demo_isolated_long_differs_by_the_rounded_wallet_only() -> None:
    # G6: with the 0.0004 entry fee the local price is 64968.853735; the exchange says
    # 64968.85373637, so at eight places they differ and the verdict is calibration only.
    watch = _watch(fees=_Fees(D("0.0004")))
    inputs = _inputs(
        stop_price=D("70000"),
        quantity=D("0.0014"),
        entry_price=D("80845.8"),
        exchange_liquidation_price=G6_EXCHANGE,
    )
    verdict = await watch.check(inputs)
    assert verdict.action is LiquidationWatchAction.OK_DIFFERS
    assert verdict.local_price is not None
    assert abs(verdict.local_price - G6_EXCHANGE) < D("0.00001")
    # Seen at the two places of a coarser exchange string the same local price is equal.
    coarse = await watch.check(replace(inputs, exchange_liquidation_price=D("64968.85")))
    assert coarse.action is LiquidationWatchAction.OK


async def test_a_short_that_passes_is_judged_on_the_other_side() -> None:
    verdict = await _watch().check(
        _inputs(side="SHORT", stop_price=D("94000"), exchange_liquidation_price=D("95617.53"))
    )
    assert verdict.action is LiquidationWatchAction.OK
    assert verdict.local_price is not None
    assert verdict.local_price.quantize(D("1E-12")) == D("95617.529880478088")


@pytest.mark.parametrize(
    ("policy", "action"),
    [
        (CLOSE_POLICY, LiquidationWatchAction.CLOSE),
        (ALERT_POLICY, LiquidationWatchAction.ALERT_ONLY_FAILED),
    ],
)
async def test_an_exchange_value_inside_the_buffer_fails_by_policy(
    policy: LiquidationFailurePolicy, action: LiquidationWatchAction
) -> None:
    # Buffer = 80000 x TEST_ONLY 137 bps / 10000 = 1096; stop 66000 - 1096 = 64904, so 65000 fails.
    verdict = await _watch(policy=policy).check(_inputs(exchange_liquidation_price=D("65000")))
    assert verdict.action is action
    assert verdict.reason == LIQUIDATION_TOO_CLOSE_AFTER_FILL
    assert verdict.exchange_price == D("65000")


async def test_the_predicate_is_strict_at_the_boundary_and_measured_from_the_fill_price() -> None:
    limits = limits_with()
    buffer_bps = limits.margin_liquidation_buffer_bps
    assert buffer_bps is not None
    entry = D("80000")
    boundary = D("66000") - entry * buffer_bps / D("10000")
    assert (await _watch().check(_inputs(exchange_liquidation_price=boundary))).action is (
        LiquidationWatchAction.CLOSE
    )
    just_inside = boundary - D("0.01")
    assert (await _watch().check(_inputs(exchange_liquidation_price=just_inside))).action in (
        LiquidationWatchAction.OK,
        LiquidationWatchAction.OK_DIFFERS,
    )
    # A fill at a different price moves the buffer with it: the same 64257.03 now fails because
    # a much higher fill price makes the buffer larger than the distance to the stop.
    high_fill = await _watch().check(
        _inputs(
            entry_price=D("90000"), stop_price=D("66000"), exchange_liquidation_price=D("65500")
        )
    )
    assert high_fill.action is LiquidationWatchAction.CLOSE


async def test_a_short_inside_the_buffer_closes() -> None:
    verdict = await _watch().check(
        _inputs(side="SHORT", stop_price=D("94000"), exchange_liquidation_price=D("94500"))
    )
    assert verdict.action is LiquidationWatchAction.CLOSE
    assert verdict.reason == LIQUIDATION_TOO_CLOSE_AFTER_FILL


# --- unknown is never "far away" (Pitfall 7, T-22-43) ---------------------------------------------


@pytest.mark.parametrize(
    "value",
    [None, D("0"), D("0.00000000"), D("-0"), D("-1"), D("-64257.03"), D("NaN"), D("Infinity")],
)
@pytest.mark.parametrize(
    ("policy", "action"),
    [
        (CLOSE_POLICY, LiquidationWatchAction.CLOSE),
        (ALERT_POLICY, LiquidationWatchAction.ALERT_ONLY_FAILED),
    ],
)
async def test_an_unknown_exchange_value_fails_closed(
    value: Decimal | None, policy: LiquidationFailurePolicy, action: LiquidationWatchAction
) -> None:
    verdict = await _watch(policy=policy).check(_inputs(exchange_liquidation_price=value))
    assert verdict.action is action
    assert verdict.reason == LIQUIDATION_UNKNOWN_AFTER_FILL


@pytest.mark.parametrize(
    "overrides",
    [
        {"leverage": None},
        {"leverage": 0},
        {"side": "SHORT", "stop_price": D("79000")},
        {"side": "SHORT", "stop_price": D("80000")},
        {"side": "LONG", "stop_price": D("80000")},
        {"side": "LONG", "stop_price": D("81000")},
    ],
)
async def test_an_input_needed_to_judge_that_is_unknown_fails_closed(
    overrides: dict[str, Any],
) -> None:
    verdict = await _watch().check(_inputs(**overrides))
    assert verdict.action is LiquidationWatchAction.CLOSE
    assert verdict.reason == LIQUIDATION_UNKNOWN_AFTER_FILL


# --- the local comparison never decides -----------------------------------------------------------


async def test_a_bracket_source_that_returns_none_leaves_the_exchange_value_to_decide() -> None:
    fees = _Fees(NO_FEE)
    verdict = await _watch(brackets=_Brackets(reading=None), fees=fees).check(_inputs())
    assert verdict.action is LiquidationWatchAction.OK
    assert verdict.local_price is None
    assert verdict.exchange_price == D("64257.03")


async def test_a_bracket_source_that_raises_leaves_the_exchange_value_to_decide() -> None:
    brackets = _Brackets(reading=None, error=RuntimeError("boom"))
    verdict = await _watch(brackets=brackets).check(_inputs())
    assert verdict.action is LiquidationWatchAction.OK
    assert verdict.local_price is None
    assert brackets.calls == ["BTCUSDT"]


@pytest.mark.parametrize(
    "fees", [_Fees(None), _Fees(None, error=RuntimeError("boom")), _Fees(D("-1"))]
)
async def test_an_unavailable_or_invalid_fee_rate_skips_only_the_comparison(fees: _Fees) -> None:
    verdict = await _watch(fees=fees).check(_inputs())
    assert verdict.action is LiquidationWatchAction.OK
    assert verdict.local_price is None


async def test_an_unusable_bracket_table_skips_only_the_comparison() -> None:
    # Notional above the top cap: the local price is unknown, the exchange value still passes.
    huge = _inputs(quantity=D("100000000"))
    verdict = await _watch().check(huge)
    assert verdict.action is LiquidationWatchAction.OK
    assert verdict.local_price is None


async def test_a_failing_exchange_value_still_closes_when_the_local_price_is_unavailable() -> None:
    verdict = await _watch(brackets=_Brackets(reading=None)).check(
        _inputs(exchange_liquidation_price=D("65000"))
    )
    assert verdict.action is LiquidationWatchAction.CLOSE
    assert verdict.local_price is None


# --- construction -----------------------------------------------------------------------------


def test_construction_refuses_while_the_buffer_is_not_configured() -> None:
    with pytest.raises(ExecutionLimitsNotConfigured) as excinfo:
        LiquidationWatch(
            brackets=_Brackets(reading=None),
            fee_rates=_Fees(NO_FEE),
            limits=limits_with(margin_liquidation_buffer_bps=None),
            policy=CLOSE_POLICY,
        )
    assert "margin.liquidation_buffer_bps" in str(excinfo.value)


def test_the_policy_is_a_required_keyword_with_no_default() -> None:
    with pytest.raises(TypeError):
        LiquidationWatch(  # type: ignore[call-arg]
            brackets=_Brackets(reading=None),
            fee_rates=_Fees(NO_FEE),
            limits=limits_with(),
        )


@pytest.mark.parametrize("policy", [None, "CLOSE_POSITION", "ALERT_ONLY", 1, True])
def test_a_policy_that_is_not_a_member_raises_type_error(policy: Any) -> None:
    with pytest.raises(TypeError):
        LiquidationWatch(
            brackets=_Brackets(reading=None),
            fee_rates=_Fees(NO_FEE),
            limits=limits_with(),
            policy=policy,
        )


def test_both_policies_exist_and_none_is_a_default_of_the_module() -> None:
    assert {member.name for member in LiquidationFailurePolicy} == {"CLOSE_POSITION", "ALERT_ONLY"}
    assert {member.name for member in LiquidationWatchAction} == {
        "OK",
        "OK_DIFFERS",
        "CLOSE",
        "ALERT_ONLY_FAILED",
    }
    init = LiquidationWatch.__init__
    assert init.__kwdefaults__ is None or "policy" not in init.__kwdefaults__


@pytest.mark.parametrize(
    "overrides",
    [
        {"symbol": ""},
        {"side": "BUY"},
        {"stop_price": 66000},
        {"stop_price": D("0")},
        {"quantity": D("-1")},
        {"entry_price": 80000.0},
        {"entry_price": D("NaN")},
        {"leverage": True},
        {"leverage": 5.0},
        {"exchange_liquidation_price": 64257.03},
    ],
)
def test_the_input_refuses_malformed_fields(overrides: dict[str, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _inputs(**overrides)


def test_the_verdict_refuses_malformed_fields() -> None:
    with pytest.raises(TypeError):
        LiquidationWatchVerdict("CLOSE", "X", None, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        LiquidationWatchVerdict(LiquidationWatchAction.OK, "", None, None)
    with pytest.raises(TypeError):
        LiquidationWatchVerdict(LiquidationWatchAction.OK, "X", 1.5, None)  # type: ignore[arg-type]


# --- purity -----------------------------------------------------------------------------


def test_module_reads_no_wall_clock_and_builds_no_float() -> None:
    assert wall_clock_calls(MODULE) == []
    assert float_constructor_calls(MODULE) == []


def test_module_imports_no_adapter_store_or_sdk() -> None:
    forbidden = (
        "src.adapters",
        "src.persistence",
        "src.ops",
        "src.paper",
        "src.backtest",
        "src.approval",
        "src.reconcile",
        "src.data",
        "src.db",
        "src.execution.protection",
        "sqlalchemy",
        "binance*",
        "polars",
        "pandas",
        "numpy",
        "httpx",
        "asyncio",
        "time",
    )
    assert forbidden_imports(MODULE, forbidden) == []


def test_module_holds_no_quote_asset_literal_and_only_zero_and_one_as_numbers() -> None:
    source = MODULE.read_text(encoding="utf-8")
    for name in ("USDT", "USDC", "BUSD", "FDUSD"):
        assert name not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if isinstance(node.value, bool):
                continue
            assert node.value in {0, 1}, node.value
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
