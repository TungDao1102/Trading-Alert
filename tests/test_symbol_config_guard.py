"""The symbol configuration guard (Phase 22, plan 22-11; D-01, D-03, D-04, D-06, criterion 1).

The tracer drives the REAL ``BinanceUsdmAdapter`` over a stateful fake SDK holding the recorded
Demo configuration (CROSSED, leverage 20, demo-observed, not mainnet): one marginType POST, one
leverage POST, one verifying read. The failure matrix drives the guard over a scripted port.
Executed unit tests against fakes [DESIGN]: the real Demo answers to the changes are unobserved
here (owner-run case ``symbol_config_change_to_isolated``).
"""

from __future__ import annotations

import ast
import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive
from src.execution.symbol_config_guard import (
    AUTO_ADD_MARGIN_ENABLED,
    MARGIN_CONFIG_CHANGE_REFUSED,
    MARGIN_CONFIG_UNVERIFIED,
    TARGET_LEVERAGE,
    TARGET_MARGIN_TYPE,
    ConfigGuardResult,
    SymbolConfigGuard,
)
from structlog.testing import capture_logs

from tests.support import ast_guards
from tests.support.config_guard_fakes import (
    LEVERAGE_POST,
    MARGIN_POST,
    READ,
    SYMBOL,
    ScriptedConfigAdapter,
    StatefulConfigSdk,
    build_config_adapter,
    snapshot,
)

MODULE = Path(__file__).resolve().parent.parent / "src" / "execution" / "symbol_config_guard.py"


def _guard(sdk: StatefulConfigSdk) -> SymbolConfigGuard:
    return SymbolConfigGuard(adapter=build_config_adapter(sdk), target_leverage=TARGET_LEVERAGE)


def _scripted(adapter: ScriptedConfigAdapter, target: int = 5) -> SymbolConfigGuard:
    return SymbolConfigGuard(adapter=adapter, target_leverage=target)


def _at_most_one_post_of_each(calls: list[str]) -> None:
    assert calls.count(MARGIN_POST) <= 1
    assert calls.count(LEVERAGE_POST) <= 1


def _assert_unverified(result: ConfigGuardResult, *, posts: int) -> None:
    assert result.ok is False
    assert result.reason_code == MARGIN_CONFIG_UNVERIFIED
    assert result.alert_reason == MARGIN_CONFIG_UNVERIFIED
    assert result.posts_sent == posts


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


# --------------------------------------------------------------------------- non-flat symbol


async def test_a_non_flat_crossed_symbol_is_refused_with_zero_posts() -> None:
    sdk = StatefulConfigSdk.from_recorded()
    result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=False)
    assert result.ok is False
    assert result.reason_code == MARGIN_CONFIG_CHANGE_REFUSED
    assert result.alert_reason is None
    assert result.posts_sent == 0
    assert result.changed is False
    assert (result.margin_type, result.leverage) == ("CROSSED", 20)
    assert (result.previous_margin_type, result.previous_leverage) == ("CROSSED", 20)
    assert sdk.calls == [READ]
    assert (sdk.margin_type, sdk.leverage) == ("CROSSED", 20)


async def test_a_non_flat_isolated_symbol_with_the_wrong_leverage_is_refused() -> None:
    sdk = StatefulConfigSdk(margin_type="ISOLATED", leverage=20)
    result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=False)
    assert result.ok is False
    assert result.reason_code == MARGIN_CONFIG_CHANGE_REFUSED
    assert result.posts_sent == 0
    assert sdk.calls == [READ]


# --------------------------------------------------------------------------- partial mismatch


async def test_only_the_leverage_is_sent_when_the_symbol_is_already_isolated() -> None:
    sdk = StatefulConfigSdk(margin_type="ISOLATED", leverage=20)
    result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.ok is True
    assert result.changed is True
    assert result.posts_sent == 1
    assert sdk.calls == [READ, LEVERAGE_POST, READ]
    assert (result.previous_margin_type, result.previous_leverage) == ("ISOLATED", 20)


async def test_only_the_margin_type_is_sent_when_the_leverage_is_already_the_target() -> None:
    sdk = StatefulConfigSdk(margin_type="CROSSED", leverage=5)
    result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.ok is True
    assert result.changed is True
    assert result.posts_sent == 1
    assert sdk.calls == [READ, MARGIN_POST, READ]


# --------------------------------------------------------------------------- POST failure matrix


def _bad_request(code: int) -> BadRequestError:
    return BadRequestError("rejected", code)


POST_FAILURES: list[Any] = [
    pytest.param(lambda: _bad_request(-4046), id="minus-4046"),
    pytest.param(lambda: _bad_request(-4047), id="minus-4047"),
    pytest.param(lambda: _bad_request(-4048), id="minus-4048"),
    pytest.param(lambda: _bad_request(-4028), id="minus-4028"),
    pytest.param(lambda: TimeoutError(), id="timeout"),
    pytest.param(lambda: RateLimitPauseActive(30), id="gate-pause"),
    pytest.param(lambda: ValueError("malformed"), id="value-error"),
]


@pytest.mark.parametrize("make_error", POST_FAILURES)
async def test_a_failed_margin_post_ends_the_mutations_and_the_read_decides(
    make_error: Any,
) -> None:
    adapter = ScriptedConfigAdapter(
        reads=[snapshot(), snapshot()],  # still CROSSED x20 at the verification read
        margin_outcomes=[make_error()],
    )
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    _assert_unverified(result, posts=1)
    assert adapter.calls == [READ, MARGIN_POST, READ]
    assert adapter.leverage_args == []
    assert result.error_types == (type(make_error()).__name__,)
    _at_most_one_post_of_each(adapter.calls)


@pytest.mark.parametrize("make_error", POST_FAILURES)
async def test_a_margin_post_error_that_raced_a_manual_change_is_ok_when_the_read_shows_it(
    make_error: Any,
) -> None:
    adapter = ScriptedConfigAdapter(
        reads=[snapshot(), snapshot(margin_type="ISOLATED", leverage=5)],
        margin_outcomes=[make_error()],
    )
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.ok is True
    assert result.reason_code == "OK"
    assert result.changed is True
    assert result.posts_sent == 1
    assert adapter.leverage_args == []
    _at_most_one_post_of_each(adapter.calls)


@pytest.mark.parametrize("make_error", POST_FAILURES)
async def test_a_failed_leverage_post_is_decided_by_the_verification_read(
    make_error: Any,
) -> None:
    adapter = ScriptedConfigAdapter(
        reads=[snapshot(), snapshot(margin_type="ISOLATED", leverage=20)],
        leverage_outcomes=[make_error()],
    )
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    _assert_unverified(result, posts=2)
    assert adapter.calls == [READ, MARGIN_POST, LEVERAGE_POST, READ]
    assert (result.margin_type, result.leverage) == ("ISOLATED", 20)
    _at_most_one_post_of_each(adapter.calls)


@pytest.mark.parametrize("make_error", POST_FAILURES)
async def test_a_leverage_post_error_that_did_apply_is_ok_when_the_read_shows_it(
    make_error: Any,
) -> None:
    adapter = ScriptedConfigAdapter(
        reads=[
            snapshot(margin_type="ISOLATED", leverage=20),
            snapshot(margin_type="ISOLATED", leverage=5),
        ],
        leverage_outcomes=[make_error()],
    )
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.ok is True
    assert result.posts_sent == 1
    assert adapter.calls == [READ, LEVERAGE_POST, READ]
    _at_most_one_post_of_each(adapter.calls)


async def test_a_refused_change_through_the_real_adapter_is_decided_by_the_read() -> None:
    sdk = StatefulConfigSdk.from_recorded()
    sdk.errors[MARGIN_POST] = [_bad_request(-4047)]
    result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=True)
    _assert_unverified(result, posts=1)
    assert sdk.calls == [READ, MARGIN_POST, READ]
    assert (sdk.margin_type, sdk.leverage) == ("CROSSED", 20)
    assert result.error_types == ("BadRequestError",)
    assert (result.margin_type, result.leverage) == ("CROSSED", 20)


@pytest.mark.parametrize(
    "silent",
    [{MARGIN_POST}, {LEVERAGE_POST}, {MARGIN_POST, LEVERAGE_POST}],
    ids=["margin", "leverage", "both"],
)
async def test_a_post_that_answers_200_without_changing_the_state_is_unverified(
    silent: set[str],
) -> None:
    sdk = StatefulConfigSdk.from_recorded()
    sdk.no_change = set(silent)
    result = await _guard(sdk).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.ok is False
    assert result.reason_code == MARGIN_CONFIG_UNVERIFIED
    assert result.alert_reason == MARGIN_CONFIG_UNVERIFIED
    _at_most_one_post_of_each(sdk.calls)
    assert sdk.calls[-1] == READ


# --------------------------------------------------------------------------- reads


async def test_an_unreadable_first_read_sends_nothing() -> None:
    adapter = ScriptedConfigAdapter(reads=[TimeoutError()])
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    _assert_unverified(result, posts=0)
    assert adapter.calls == [READ]
    assert (result.margin_type, result.leverage, result.max_notional_value) == (None, None, None)
    assert result.error_types == ("TimeoutError",)


async def test_an_unreadable_verification_read_is_unverified_with_the_posts_counted() -> None:
    adapter = ScriptedConfigAdapter(reads=[snapshot(), ValueError("malformed")])
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    _assert_unverified(result, posts=2)
    assert adapter.calls == [READ, MARGIN_POST, LEVERAGE_POST, READ]
    assert (result.margin_type, result.leverage, result.max_notional_value) == (None, None, None)
    assert (result.previous_margin_type, result.previous_leverage) == ("CROSSED", 20)
    assert result.changed is False


@pytest.mark.parametrize(
    ("verified", "target"),
    [
        pytest.param(snapshot(margin_type="isolated", leverage=5), 5, id="lower-case"),
        pytest.param(snapshot(margin_type="Isolated", leverage=5), 5, id="mixed-case"),
        pytest.param(snapshot(margin_type="ISOLATED", leverage=4), 5, id="leverage-4"),
        pytest.param(snapshot(margin_type="ISOLATED", leverage=True), 1, id="leverage-bool"),
        pytest.param(snapshot(margin_type="ISOLATED", leverage=5.0), 5, id="leverage-float"),
        pytest.param(snapshot(margin_type="CROSSED", leverage=5), 5, id="still-crossed"),
    ],
)
async def test_a_verification_answer_that_is_not_exactly_the_target_is_not_ok(
    verified: Any, target: int
) -> None:
    adapter = ScriptedConfigAdapter(reads=[snapshot(leverage=20), verified])
    result = await _scripted(adapter, target).ensure(symbol=SYMBOL, symbol_is_flat=True)
    _assert_unverified(result, posts=2)
    _at_most_one_post_of_each(adapter.calls)


async def test_auto_add_margin_at_the_verification_read_is_refused() -> None:
    adapter = ScriptedConfigAdapter(
        reads=[snapshot(), snapshot(margin_type="ISOLATED", leverage=5, auto_add=True)]
    )
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.ok is False
    assert result.reason_code == AUTO_ADD_MARGIN_ENABLED
    assert result.posts_sent == 2


async def test_auto_add_margin_on_the_first_read_is_refused_before_any_post() -> None:
    for flat in (True, False):
        adapter = ScriptedConfigAdapter(reads=[snapshot(auto_add=True)])
        result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=flat)
        assert result.ok is False
        assert result.reason_code == AUTO_ADD_MARGIN_ENABLED
        assert result.alert_reason is None
        assert result.posts_sent == 0
        assert adapter.calls == [READ]


async def test_auto_add_margin_on_an_otherwise_matching_symbol_is_refused() -> None:
    adapter = ScriptedConfigAdapter(
        reads=[snapshot(margin_type="ISOLATED", leverage=5, auto_add=True)]
    )
    result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.reason_code == AUTO_ADD_MARGIN_ENABLED
    assert adapter.calls == [READ]


async def test_a_first_read_with_a_field_of_the_wrong_type_sends_nothing() -> None:
    for bad in (snapshot(margin_type=None), snapshot(leverage=None), snapshot(auto_add=None)):
        adapter = ScriptedConfigAdapter(reads=[bad])
        result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
        _assert_unverified(result, posts=0)
        assert adapter.calls == [READ]


# --------------------------------------------------------------------------- never two POSTs


SCENARIOS: list[Any] = [
    pytest.param([snapshot(), snapshot()], [_bad_request(-4047)], [], id="margin-refused"),
    pytest.param(
        [snapshot(), snapshot(margin_type="ISOLATED", leverage=20)],
        [None],
        [TimeoutError()],
        id="leverage-timeout",
    ),
    pytest.param(
        [snapshot(), snapshot(margin_type="ISOLATED", leverage=5)], [None], [None], id="happy"
    ),
    pytest.param([snapshot(), TimeoutError()], [None], [None], id="verify-unreadable"),
    pytest.param([snapshot(auto_add=True)], [], [], id="auto-add"),
]


@pytest.mark.parametrize(("reads", "margin_outcomes", "leverage_outcomes"), SCENARIOS)
async def test_no_branch_sends_two_posts_of_one_kind_or_sleeps(
    reads: list[Any],
    margin_outcomes: list[Any],
    leverage_outcomes: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(*args: object, **kwargs: object) -> None:
        raise AssertionError("the guard must never sleep")

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    adapter = ScriptedConfigAdapter(
        reads=list(reads),
        margin_outcomes=list(margin_outcomes),
        leverage_outcomes=list(leverage_outcomes),
    )
    await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    _at_most_one_post_of_each(adapter.calls)
    assert set(adapter.calls) <= {READ, MARGIN_POST, LEVERAGE_POST}


async def test_the_scripted_adapter_refuses_any_other_method() -> None:
    adapter = ScriptedConfigAdapter(reads=[])
    with pytest.raises(AttributeError):
        adapter.cancel_all_open_orders  # type: ignore[attr-defined]  # noqa: B018


# --------------------------------------------------------------------------- hygiene


async def test_no_exception_message_reaches_the_result_or_the_logs() -> None:
    secret = "balance 123456789.123456"
    adapter = ScriptedConfigAdapter(
        reads=[snapshot(), snapshot()], margin_outcomes=[ValueError(secret)]
    )
    with capture_logs() as logs:
        result = await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert logs == []
    assert "123456789" not in repr(result)
    assert result.error_types == ("ValueError",)


async def test_a_cancellation_from_a_post_propagates() -> None:
    adapter = ScriptedConfigAdapter(reads=[snapshot()], margin_outcomes=[asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await _scripted(adapter).ensure(symbol=SYMBOL, symbol_is_flat=True)


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        pytest.param(True, TypeError, id="bool"),
        pytest.param(5.0, TypeError, id="float"),
        pytest.param("5", TypeError, id="text"),
        pytest.param(0, ValueError, id="zero"),
        pytest.param(-1, ValueError, id="negative"),
    ],
)
def test_the_constructor_refuses_a_bad_target_leverage(bad: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        SymbolConfigGuard(adapter=ScriptedConfigAdapter(reads=[]), target_leverage=bad)


def test_the_target_leverage_has_no_default_and_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        SymbolConfigGuard(adapter=ScriptedConfigAdapter(reads=[]))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        SymbolConfigGuard(ScriptedConfigAdapter(reads=[]), 5)  # type: ignore[misc]


async def test_a_lower_target_is_a_composition_decision() -> None:
    sdk = StatefulConfigSdk.from_recorded()
    guard = SymbolConfigGuard(adapter=build_config_adapter(sdk), target_leverage=3)
    result = await guard.ensure(symbol=SYMBOL, symbol_is_flat=True)
    assert result.ok is True
    assert sdk.leverage_args == [3]
    assert result.leverage == 3


async def test_ensure_refuses_a_bad_symbol_or_flat_flag() -> None:
    guard = _scripted(ScriptedConfigAdapter(reads=[]))
    with pytest.raises(ValueError):
        await guard.ensure(symbol="", symbol_is_flat=True)
    with pytest.raises(TypeError):
        await guard.ensure(symbol=SYMBOL, symbol_is_flat=1)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- purity (AST)


def test_the_module_is_pure() -> None:
    assert ast_guards.wall_clock_calls(MODULE) == []
    assert (
        ast_guards.forbidden_imports(
            MODULE, ["src.adapters", "src.persistence", "binance*", "sqlalchemy"]
        )
        == []
    )
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    texts = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert [text for text in texts if "USDT" in text] == []


@pytest.mark.parametrize("target", [6, 20, 125])
def test_a_target_above_the_d035_cap_is_refused_at_construction(target: int) -> None:
    with pytest.raises(ValueError, match="D035 cap"):
        SymbolConfigGuard(adapter=object(), target_leverage=target)  # type: ignore[arg-type]


@pytest.mark.parametrize("target", [1, 2, 3, 4, 5])
def test_a_target_up_to_the_d035_cap_is_accepted(target: int) -> None:
    SymbolConfigGuard(adapter=object(), target_leverage=target)  # type: ignore[arg-type]
