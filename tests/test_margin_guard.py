"""MarginGuard (Phase 22, plan 22-14; D-05, D-13, D-15, criteria 1 to 4, amendments A5, A7, A9).

The tracer runs the recorded Demo CROSSED x20 account (demo-observed, not mainnet) through the REAL
``BinanceUsdmAdapter`` over one composite fake SDK, the real ``LiveEquitySource``,
``SymbolConfigGuard`` and ``BracketCache``, to one passing verdict. The refusal matrix pins the
fixed order (account mode, configuration, liquidation, margin), the plain code of each refusal and
that nothing after the first refusal is touched. Every limit below is a TEST_ONLY value (buffer 137
bps, bracket age 4141 ms, headroom 233 bps, equity age 9137 ms), never the owner's choice.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from tests.support.margin_guard_fakes import (
    ACCOUNT_BALANCE_READ,
    ACCOUNT_CONFIG_READ,
    ACCOUNT_INFORMATION_READ,
    BRACKET_READ,
    CONFIG_READ,
    LEVERAGE_POST,
    MARGIN_POST,
    build_rig,
    request,
)

RECORDED_EQUITY = Decimal("4999.09343961")

TRACER_CALLS = [
    ACCOUNT_CONFIG_READ,
    ACCOUNT_INFORMATION_READ,
    ACCOUNT_BALANCE_READ,
    CONFIG_READ,
    MARGIN_POST,
    LEVERAGE_POST,
    CONFIG_READ,
    BRACKET_READ,
]


# --------------------------------------------------------------------------- Task 1: tracer


async def test_recorded_crossed_x20_account_flows_through_every_check_to_one_pass() -> None:
    rig = build_rig()
    verdict = await rig.guard.evaluate(request())
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"
    assert verdict.margin_type == "ISOLATED"
    assert verdict.leverage == 5
    assert verdict.equity_used == RECORDED_EQUITY
    assert verdict.config_changed is True
    assert verdict.previous_margin_type == "CROSSED"
    assert verdict.previous_leverage == 20
    assert verdict.alert_reason is None
    # The three account reads, the symbolConfig read, the two POSTs, the verification read, then
    # the bracket read: the fixed order of the guard.
    assert rig.rest.calls == TRACER_CALLS
    assert rig.rest.config_sdk.margin_type == "ISOLATED"
    assert rig.rest.config_sdk.leverage == 5
    assert rig.claims.calls == 1


async def test_a_second_call_on_the_left_over_state_sends_no_post_and_reuses_the_brackets() -> None:
    rig = build_rig()
    await rig.guard.evaluate(request())
    before = len(rig.rest.calls)
    verdict = await rig.guard.evaluate(request(trade_plan_id="P2"))
    assert verdict.is_no_trade is False
    assert verdict.config_changed is False
    assert verdict.margin_type == "ISOLATED"
    assert verdict.leverage == 5
    assert verdict.equity_used == RECORDED_EQUITY
    assert rig.rest.calls[before:] == [
        ACCOUNT_CONFIG_READ,
        ACCOUNT_INFORMATION_READ,
        ACCOUNT_BALANCE_READ,
        CONFIG_READ,
    ]
    assert rig.rest.count(MARGIN_POST) == 1
    assert rig.rest.count(LEVERAGE_POST) == 1
    assert rig.rest.count(BRACKET_READ) == 1


async def test_the_clock_is_read_after_the_refresh_and_again_after_the_last_await() -> None:
    rig = build_rig()
    await rig.guard.evaluate(request())
    # The equity source stamps once before its first request; the cache reads before and after
    # the bracket request and once to find nothing cached; the guard reads after the refresh,
    # after the bracket read and after the claims read.
    assert rig.clock.reads >= 6


async def test_a_reading_that_ages_during_the_bracket_and_configuration_reads_is_refused() -> None:
    # Every SDK call takes 2 s of virtual time: the 8 calls of the tracer take 16 s, more than
    # the 9137 ms equity bound, although each judgement taken earlier was still fresh (Pitfall 6).
    # The bracket read alone takes 2 s, inside the bracket bound (4141 ms).
    rig = build_rig(advance_per_call=timedelta(seconds=2))
    verdict = await rig.guard.evaluate(request())
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert verdict.equity_used is None
    assert rig.rest.calls == TRACER_CALLS
    # The mutation happened before the refusal: the evidence rides on the refusal.
    assert verdict.config_changed is True
    assert verdict.previous_margin_type == "CROSSED"
    assert verdict.previous_leverage == 20
