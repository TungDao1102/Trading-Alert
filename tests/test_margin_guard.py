"""MarginGuard (Phase 22, plan 22-14; D-05, D-13, D-15, criteria 1 to 4, amendments A5, A7, A9).

The tracer runs the recorded Demo CROSSED x20 account (demo-observed, not mainnet) through the REAL
``BinanceUsdmAdapter`` over one composite fake SDK, the real ``LiveEquitySource``,
``SymbolConfigGuard`` and ``BracketCache``, to one passing verdict. The refusal matrix pins the
fixed order (account mode, configuration, liquidation, margin), the plain code of each refusal and
that nothing after the first refusal is touched. Every limit below is a TEST_ONLY value (buffer 137
bps, bracket age 4141 ms, headroom 233 bps, equity age 9137 ms), never the owner's choice.

Worked numbers (formulas of plans 22-04 and 22-07, entry fee 0.0004): LONG 0.01 at 80000 with stop
66000 at leverage 5 liquidates at about 64289.16, the 137 bps buffer is 1096, so the stop must be
above 65385.16; the initial margin is 160, the fees 0.64 and the need 160.64, which with the 233 bps
headroom is 164.382912.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import RejectionReason
from src.execution import margin_guard as margin_guard_module
from src.execution.bracket_cache import BracketReading
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.margin_guard import (
    MARGIN_MODE_UNSUPPORTED,
    MarginGuard,
    MarginGuardVerdict,
)
from src.execution.pre_placement import HEDGE_MODE_UNSUPPORTED
from src.execution.symbol_config_guard import (
    AUTO_ADD_MARGIN_ENABLED,
    MARGIN_CONFIG_CHANGE_REFUSED,
    MARGIN_CONFIG_UNVERIFIED,
)
from src.risk import margin_check
from src.risk.liquidation import (
    LEVERAGE_ABOVE_BRACKET,
    LIQUIDATION_INPUT_UNAVAILABLE,
    LIQUIDATION_TOO_CLOSE,
    NOTIONAL_ABOVE_MAX,
)
from src.risk.margin_check import (
    BLOCKED_HEDGE_MODE,
    BLOCKED_MULTI_ASSETS_MODE,
    BLOCKED_READING_UNUSABLE,
    MarginClaim,
    other_claims_margin,
)
from src.risk.reservations import ReservationStatus
from structlog.testing import capture_logs

from tests.support.ast_guards import forbidden_imports, wall_clock_calls
from tests.support.config_guard_fakes import StatefulConfigSdk
from tests.support.execution_limits import test_only_execution_limits as only_limits
from tests.support.margin_guard_fakes import (
    ACCOUNT_BALANCE_READ,
    ACCOUNT_CONFIG_READ,
    ACCOUNT_INFORMATION_READ,
    BRACKET_READ,
    CONFIG_READ,
    LEVERAGE_POST,
    MARGIN_POST,
    START,
    SYMBOL,
    GuardRig,
    MovingClock,
    ScriptedAccount,
    ScriptedBrackets,
    ScriptedClaims,
    ScriptedConfigGuard,
    account_payloads,
    build_rig,
    config_result,
    refused_check,
    request,
    set_available_balance,
)
from tests.support.margin_guard_fakes import (
    margin_check as usable_check,
)
from tests.support.phase22_fixtures import demo_brackets

MODULE = Path(__file__).resolve().parent.parent / "src" / "execution" / "margin_guard.py"
RECORDED_EQUITY = Decimal("4999.09343961")
SECRET = "secret-token 123.45"

TRACER_CALLS = [
    ACCOUNT_CONFIG_READ,
    ACCOUNT_INFORMATION_READ,
    ACCOUNT_BALANCE_READ,
    BRACKET_READ,
    CONFIG_READ,
    MARGIN_POST,
    LEVERAGE_POST,
    CONFIG_READ,
]
ACCOUNT_READS = [ACCOUNT_CONFIG_READ, ACCOUNT_INFORMATION_READ, ACCOUNT_BALANCE_READ]
CONFIG_CALLS = (CONFIG_READ, MARGIN_POST, LEVERAGE_POST)
NO_POSTS = (MARGIN_POST, LEVERAGE_POST)

UNCERTAIN = "UNCERTAIN_ACCOUNT_STATE"
INSUFFICIENT = "INSUFFICIENT_MARGIN"


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
    # The three account reads, the bracket read (both pure checks are judged on those), then the
    # symbolConfig read, the two POSTs and the verification read: the fixed order of the guard.
    # The configuration step is LAST so a refused plan sends nothing (WR-01).
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
    assert rig.rest.calls[before:] == [*ACCOUNT_READS, CONFIG_READ]
    assert rig.rest.count(MARGIN_POST) == 1
    assert rig.rest.count(LEVERAGE_POST) == 1
    assert rig.rest.count(BRACKET_READ) == 1


async def test_the_account_is_judged_after_the_refresh_and_again_after_the_last_await() -> None:
    # The clock moves by twice the equity bound inside the bracket read. Both judgements get a
    # clock value taken at their own moment: the second is later than the first by exactly that.
    events: list[str] = []
    clock = MovingClock()
    age = only_limits().account_max_equity_age_ms
    assert age is not None
    jump = timedelta(milliseconds=2 * age)
    account = ScriptedAccount(usable_check(at=START), events=events)
    limits = only_limits()

    class _JumpingBrackets(ScriptedBrackets):
        async def get(self, *, symbol: str) -> Any:
            clock.advance(jump)
            return BracketReading(
                symbol=SYMBOL, brackets=tuple(demo_brackets()), observed_at_utc=clock.value
            )

    guard = MarginGuard(
        config_guard=ScriptedConfigGuard(config_result(), events=events),
        brackets=_JumpingBrackets(None, events=events),
        account=account,
        claims=ScriptedClaims(events=events),
        clock=clock,
        limits=limits,
    )
    verdict = await guard.evaluate(request())
    assert verdict.is_no_trade is False
    # first judgement (account mode), second (before the margin verdict), third (after the
    # configuration step: its reads and POSTs take time too).
    assert len(account.check_times) == 3
    assert account.check_times[0] == START
    assert account.check_times[1] == START + jump
    assert account.check_times[2] == START + jump


async def test_a_reading_that_ages_during_the_bracket_and_configuration_reads_is_refused() -> None:
    # Every SDK call takes 2 s of virtual time: the 8 calls of the tracer take 16 s, more than
    # the 9137 ms equity bound, although each judgement taken earlier (at 6 s and 8 s, before the
    # configuration step) was still fresh (Pitfall 6). The third judgement, taken after the
    # configuration step, is the one that refuses. The bracket read alone takes 2 s, inside the
    # bracket bound (4141 ms).
    rig = build_rig(advance_per_call=timedelta(seconds=2))
    verdict = await rig.guard.evaluate(request())
    assert verdict.is_no_trade is True
    assert verdict.reason_code == UNCERTAIN
    assert verdict.equity_used is None
    assert rig.rest.calls == TRACER_CALLS
    # The mutation happened before this late refusal: the evidence rides on the refusal.
    assert verdict.config_changed is True
    assert verdict.previous_margin_type == "CROSSED"
    assert verdict.previous_leverage == 20


# --------------------------------------------------------------------------- Task 2: the matrix


def isolated_sdk(max_notional: str = "100000000", **kwargs: Any) -> StatefulConfigSdk:
    """A symbol already ISOLATED x5 (the closing state of the tracer), so nothing is POSTed."""
    return StatefulConfigSdk(
        margin_type="ISOLATED", leverage=5, max_notional=max_notional, **kwargs
    )


def claim(
    plan_id: str,
    margin: str | None,
    status: ReservationStatus = ReservationStatus.RESERVED,
    *,
    placed_after_reading: bool = False,
) -> MarginClaim:
    """A stored claim; a PLACED one is placed a minute BEFORE the reading unless told otherwise."""
    placed = None
    if status is ReservationStatus.PLACED:
        placed = (
            START + timedelta(minutes=1) if placed_after_reading else START - timedelta(minutes=1)
        )
    return MarginClaim(
        trade_plan_id=plan_id,
        status=status,
        required_margin=None if margin is None else Decimal(margin),
        placed_at_utc=placed,
    )


def _failing(name: str) -> Callable[[GuardRig], None]:
    def apply(rig: GuardRig) -> None:
        rig.rest.fail[name] = RuntimeError(SECRET)

    return apply


def _drop_quote_row(information: dict[str, Any]) -> None:
    information["assets"] = [r for r in information["assets"] if r["asset"] != "USDT"]


def _break_identity(information: dict[str, Any]) -> None:
    information["totalWalletBalance"] = "4999.0"


def _mismatch_available(information: dict[str, Any]) -> None:
    information["availableBalance"] = "4999.0"


def _dual_side(config: dict[str, Any]) -> None:
    config["dualSidePosition"] = True


def _multi_assets(config: dict[str, Any]) -> None:
    config["multiAssetsMargin"] = True


@dataclass
class Scenario:
    """One refusal: the rig, the request edits, the expected code and what stays untouched."""

    name: str
    code: str
    make: Callable[[], GuardRig]
    edits: dict[str, Any] = field(default_factory=dict)
    alert: str | None = None
    untouched: tuple[str, ...] = ()
    claims_called: int = 0
    after: Callable[[GuardRig], None] | None = None


def _scenarios() -> list[Scenario]:
    account_untouched = (*CONFIG_CALLS, BRACKET_READ)
    return [
        Scenario(
            "account read fails",
            UNCERTAIN,
            lambda: _with(build_rig(), _failing(ACCOUNT_INFORMATION_READ)),
            untouched=account_untouched,
        ),
        Scenario(
            "stale reading",
            UNCERTAIN,
            lambda: build_rig(advance_per_call=timedelta(seconds=4)),
            untouched=account_untouched,
        ),
        Scenario(
            "negative age",
            UNCERTAIN,
            lambda: build_rig(advance_per_call=timedelta(seconds=-1)),
            untouched=account_untouched,
        ),
        Scenario(
            "failed identity",
            UNCERTAIN,
            lambda: build_rig(account=account_payloads(information_edit=_break_identity)),
            untouched=account_untouched,
        ),
        Scenario(
            "missing quote row",
            UNCERTAIN,
            lambda: build_rig(account=account_payloads(information_edit=_drop_quote_row)),
            untouched=account_untouched,
        ),
        Scenario(
            "availableBalance mismatch",
            UNCERTAIN,
            lambda: build_rig(account=account_payloads(information_edit=_mismatch_available)),
            untouched=account_untouched,
        ),
        Scenario(
            "hedge account",
            "HEDGE_MODE_UNSUPPORTED",
            lambda: build_rig(account=account_payloads(config_edit=_dual_side)),
            untouched=account_untouched,
        ),
        Scenario(
            "multi-asset account",
            "MARGIN_MODE_UNSUPPORTED",
            lambda: build_rig(account=account_payloads(config_edit=_multi_assets)),
            untouched=account_untouched,
        ),
        # The pure checks (liquidation, margin) run BEFORE the configuration step (WR-01): a
        # refusal there never reads or POSTs the symbol configuration (``config_untouched``).
        Scenario(
            "non-flat symbol with a mismatch",
            "MARGIN_CONFIG_CHANGE_REFUSED",
            build_rig,
            edits={"symbol_is_flat": False},
            untouched=NO_POSTS,
            claims_called=1,
        ),
        Scenario(
            "configuration cannot be verified",
            "MARGIN_CONFIG_UNVERIFIED",
            lambda: build_rig(config_sdk=_unchangeable()),
            alert="MARGIN_CONFIG_UNVERIFIED",
            claims_called=1,
        ),
        Scenario(
            "configuration read fails",
            "MARGIN_CONFIG_UNVERIFIED",
            lambda: _with(build_rig(), _failing(CONFIG_READ)),
            alert="MARGIN_CONFIG_UNVERIFIED",
            untouched=NO_POSTS,
            claims_called=1,
        ),
        Scenario(
            "auto add margin on",
            "AUTO_ADD_MARGIN_ENABLED",
            lambda: build_rig(config_sdk=isolated_sdk(auto_add=True)),
            untouched=NO_POSTS,
            claims_called=1,
        ),
        Scenario(
            "no bracket reading",
            "LIQUIDATION_INPUT_UNAVAILABLE",
            lambda: _with(build_rig(), _failing(BRACKET_READ)),
            untouched=CONFIG_CALLS,
        ),
        Scenario(
            "notional above the symbol maximum",
            "NOTIONAL_ABOVE_MAX",
            lambda: build_rig(config_sdk=isolated_sdk("20000000"), account=_rich_account()),
            edits={"quantity": Decimal("250.0000125"), "stop_price": Decimal("70000")},
            claims_called=1,
        ),
        Scenario(
            "leverage above the bracket",
            "LEVERAGE_ABOVE_BRACKET",
            build_rig,
            edits={"quantity": Decimal("1500")},
            untouched=CONFIG_CALLS,
        ),
        Scenario(
            "liquidation too close (long)",
            "LIQUIDATION_TOO_CLOSE",
            build_rig,
            edits={"stop_price": Decimal("65000")},
            untouched=CONFIG_CALLS,
        ),
        Scenario(
            "liquidation too close (short)",
            "LIQUIDATION_TOO_CLOSE",
            build_rig,
            edits={"side": "SHORT", "stop_price": Decimal("95000")},
            untouched=CONFIG_CALLS,
        ),
        Scenario(
            "inverted stop geometry",
            "LIQUIDATION_INPUT_UNAVAILABLE",
            build_rig,
            edits={"stop_price": Decimal("81000")},
            untouched=CONFIG_CALLS,
        ),
        Scenario(
            "insufficient margin",
            "INSUFFICIENT_MARGIN",
            build_rig,
            edits={"quantity": Decimal("10")},
            untouched=CONFIG_CALLS,
            claims_called=1,
        ),
        Scenario(
            "claim with an unknown margin",
            UNCERTAIN,
            lambda: build_rig(claims=[claim("OTHER", None)]),
            untouched=CONFIG_CALLS,
            claims_called=1,
        ),
        Scenario(
            "reserved claim exhausts the free margin",
            "INSUFFICIENT_MARGIN",
            lambda: build_rig(claims=[claim("OTHER", "5000")]),
            untouched=CONFIG_CALLS,
            claims_called=1,
        ),
        Scenario(
            "placed claim placed after the reading still counts (netting verified, D085)",
            "INSUFFICIENT_MARGIN",
            lambda: build_rig(
                claims=[
                    claim("OTHER", "4900", ReservationStatus.PLACED, placed_after_reading=True)
                ],
            ),
            untouched=CONFIG_CALLS,
            claims_called=1,
        ),
        Scenario(
            "claims port raises",
            UNCERTAIN,
            lambda: build_rig(claims_exception=RuntimeError(SECRET)),
            untouched=CONFIG_CALLS,
            claims_called=1,
        ),
    ]


def _rich_account() -> dict[str, Any]:
    """The recorded account with an availableBalance far above any margin of these tests."""
    return account_payloads(information_edit=set_available_balance("50000000"))


def _with(rig: GuardRig, apply: Callable[[GuardRig], None]) -> GuardRig:
    apply(rig)
    return rig


def _unchangeable() -> StatefulConfigSdk:
    sdk = StatefulConfigSdk.from_recorded()
    sdk.no_change = {MARGIN_POST, LEVERAGE_POST}
    return sdk


SCENARIOS = _scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
async def test_every_refusal_has_its_exact_plain_code_and_touches_nothing_later(
    scenario: Scenario,
) -> None:
    rig = scenario.make()
    verdict = await rig.guard.evaluate(request(**scenario.edits))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == scenario.code
    assert verdict.alert_reason == scenario.alert
    assert verdict.margin_type is None
    assert verdict.leverage is None
    assert verdict.equity_used is None
    for name in scenario.untouched:
        assert rig.rest.count(name) == 0, name
    assert rig.claims.calls == scenario.claims_called
    assert SECRET not in repr(verdict)


async def test_the_unverified_configuration_refusal_carries_the_mutation_as_evidence() -> None:
    rig = build_rig(config_sdk=_unchangeable())
    verdict = await rig.guard.evaluate(request())
    assert verdict.reason_code == MARGIN_CONFIG_UNVERIFIED
    assert verdict.alert_reason == MARGIN_CONFIG_UNVERIFIED
    assert verdict.config_changed is True  # both POSTs were sent
    assert verdict.previous_margin_type == "CROSSED"
    assert verdict.previous_leverage == 20


async def test_a_refusal_without_a_post_carries_no_configuration_evidence() -> None:
    non_flat = await build_rig().guard.evaluate(request(symbol_is_flat=False))
    assert non_flat.reason_code == MARGIN_CONFIG_CHANGE_REFUSED
    assert non_flat.config_changed is False
    assert non_flat.previous_margin_type is None
    assert non_flat.previous_leverage is None
    insufficient = await build_rig(config_sdk=isolated_sdk()).guard.evaluate(
        request(quantity=Decimal("10"))
    )
    assert insufficient.reason_code == INSUFFICIENT
    assert insufficient.config_changed is False
    assert insufficient.previous_margin_type is None


async def test_a_refusal_after_a_post_carries_the_evidence_to_the_end_of_the_chain() -> None:
    # The symbol's maxNotionalValue AT x5 (500) is below the 800 notional of the plan: only the
    # verified configuration can show it, so the POSTs were sent before this refusal.
    sdk = StatefulConfigSdk(max_notional_by_leverage={5: "500"})
    rig = build_rig(config_sdk=sdk)
    verdict = await rig.guard.evaluate(request())
    assert verdict.reason_code == NOTIONAL_ABOVE_MAX
    assert rig.rest.count(MARGIN_POST) == 1
    assert rig.rest.count(LEVERAGE_POST) == 1
    assert verdict.config_changed is True
    assert verdict.previous_margin_type == "CROSSED"
    assert verdict.previous_leverage == 20


async def test_ordinary_refusals_carry_no_alert_reason() -> None:
    for edits in ({"symbol_is_flat": False}, {"quantity": Decimal("10")}):
        verdict = await build_rig().guard.evaluate(request(**edits))
        assert verdict.is_no_trade is True
        assert verdict.alert_reason is None


# ---- account mode comes first: no configuration call on an unsupported or unreadable account


async def test_a_hedge_or_multi_asset_account_is_refused_before_anything_is_mutated() -> None:
    hedge = build_rig(account=account_payloads(config_edit=_dual_side))
    assert (await hedge.guard.evaluate(request())).reason_code == HEDGE_MODE_UNSUPPORTED
    multi = build_rig(account=account_payloads(config_edit=_multi_assets))
    assert (await multi.guard.evaluate(request())).reason_code == MARGIN_MODE_UNSUPPORTED
    for rig in (hedge, multi):
        assert rig.rest.calls == ACCOUNT_READS
        assert rig.rest.config_sdk.margin_type == "CROSSED"
        assert rig.rest.config_sdk.leverage == 20


@pytest.mark.parametrize(
    ("blocked", "code"),
    [
        (BLOCKED_HEDGE_MODE, "HEDGE_MODE_UNSUPPORTED"),
        (BLOCKED_MULTI_ASSETS_MODE, "MARGIN_MODE_UNSUPPORTED"),
        (BLOCKED_READING_UNUSABLE, "UNCERTAIN_ACCOUNT_STATE"),
    ],
)
async def test_each_blocked_value_of_the_account_judgement_maps_to_its_code(
    blocked: str, code: str
) -> None:
    events: list[str] = []
    guard, _ = _scripted_guard(
        events, account=ScriptedAccount(refused_check(blocked), events=events)
    )
    verdict = await guard.evaluate(request())
    assert verdict.reason_code == code
    assert events == ["refresh", "check_margin"]


# ---- the fixed order: only the first of several simultaneous problems is reported


def _scripted_guard(
    events: list[str],
    *,
    account: ScriptedAccount | None = None,
    config: ScriptedConfigGuard | None = None,
    brackets: ScriptedBrackets | None = None,
    claims: ScriptedClaims | None = None,
    clock: MovingClock | None = None,
    limits: Any = None,
) -> tuple[MarginGuard, dict[str, Any]]:
    the_clock = clock if clock is not None else MovingClock()
    ports: dict[str, Any] = {
        "account": account or ScriptedAccount(usable_check(), events=events),
        "config": config or ScriptedConfigGuard(config_result(), events=events),
        "brackets": brackets
        or ScriptedBrackets(
            BracketReading(
                symbol=SYMBOL, brackets=tuple(demo_brackets()), observed_at_utc=the_clock.value
            ),
            events=events,
        ),
        "claims": claims or ScriptedClaims(events=events),
    }
    guard = MarginGuard(
        config_guard=ports["config"],
        brackets=ports["brackets"],
        account=ports["account"],
        claims=ports["claims"],
        clock=the_clock,
        limits=limits if limits is not None else only_limits(),
    )
    return guard, ports


@pytest.mark.parametrize(
    ("layer", "code", "expected_events"),
    [
        (0, "HEDGE_MODE_UNSUPPORTED", ["refresh", "check_margin"]),
        (1, "LIQUIDATION_TOO_CLOSE", ["refresh", "check_margin", "brackets"]),
        (
            2,
            "INSUFFICIENT_MARGIN",
            ["refresh", "check_margin", "brackets", "claims", "check_margin"],
        ),
        (
            3,
            "MARGIN_CONFIG_CHANGE_REFUSED",
            ["refresh", "check_margin", "brackets", "claims", "check_margin", "config"],
        ),
    ],
)
async def test_the_first_refusal_in_the_fixed_order_wins(
    layer: int, code: str, expected_events: list[str]
) -> None:
    """Hedge account, close stop, no margin and a refused configuration: one problem is reported.

    The configuration step is LAST (WR-01): the two pure checks come first and a refusal there
    never reaches the configuration port.
    """
    events: list[str] = []
    account = ScriptedAccount(
        refused_check(BLOCKED_HEDGE_MODE)
        if layer == 0
        else usable_check(available="10" if layer < 3 else "4999.09343961"),
        events=events,
    )
    config = ScriptedConfigGuard(
        dataclasses.replace(
            config_result(),
            ok=False,
            reason_code="MARGIN_CONFIG_CHANGE_REFUSED",
            margin_type=None,
            leverage=None,
            max_notional_value=None,
        ),
        events=events,
    )
    guard, ports = _scripted_guard(events, account=account, config=config)
    # layer 1 has the close stop (65000) and no margin; layer 2 has no margin only
    stop = Decimal("65000") if layer == 1 else Decimal("66000")
    verdict = await guard.evaluate(request(stop_price=stop))
    assert verdict.reason_code == code
    assert events == expected_events
    if layer < 2:
        assert ports["claims"].calls == 0
    if layer < 1:
        assert ports["brackets"].calls == []
    if layer < 3:
        assert config.calls == []


# ---- liquidation specifics


async def test_the_entry_fee_of_the_request_decides_the_liquidation_price() -> None:
    """Stop 65366 passes with no fee (LP 64257.03 < 64270) and fails with 0.0004 (LP 64289.16)."""
    with_fee = await build_rig(config_sdk=isolated_sdk()).guard.evaluate(
        request(stop_price=Decimal("65366"))
    )
    no_fee = await build_rig(config_sdk=isolated_sdk()).guard.evaluate(
        request(stop_price=Decimal("65366"), fee_rate_entry=Decimal("0"))
    )
    assert with_fee.reason_code == LIQUIDATION_TOO_CLOSE
    assert no_fee.is_no_trade is False


@pytest.mark.parametrize("rate", ["0", "0.0004", "0.0007"])
async def test_the_guard_passes_request_fee_rate_entry_to_the_liquidation_function(
    monkeypatch: pytest.MonkeyPatch, rate: str
) -> None:
    seen: list[dict[str, Any]] = []
    real = margin_guard_module.liquidation_verdict  # type: ignore[attr-defined]

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(margin_guard_module, "liquidation_verdict", spy)
    rig = build_rig(config_sdk=isolated_sdk())
    verdict = await rig.guard.evaluate(request(fee_rate_entry=Decimal(rate)))
    assert verdict.is_no_trade is False
    (call,) = seen
    assert call["entry_fee_rate"] == Decimal(rate)
    assert call["leverage"] == 5
    assert call["buffer_bps"] == only_limits().margin_liquidation_buffer_bps
    assert call["entry_price"] == Decimal("80000")
    assert call["stop_price"] == Decimal("66000")


async def test_the_short_mirror_passes_and_fails_on_the_other_side_of_the_stop() -> None:
    passing = await build_rig(config_sdk=isolated_sdk()).guard.evaluate(
        request(side="SHORT", stop_price=Decimal("94000"))
    )
    assert passing.is_no_trade is False
    too_close = await build_rig(config_sdk=isolated_sdk()).guard.evaluate(
        request(side="SHORT", stop_price=Decimal("95000"))
    )
    assert too_close.reason_code == LIQUIDATION_TOO_CLOSE


async def test_a_notional_equal_to_the_symbol_maximum_is_not_above_it() -> None:
    # 250 x 80000 = 20000000 = the recorded maxNotionalValue: equal passes. With the stop at 70000
    # the liquidation (65483.9) is beyond the buffer, and the owner-sized account covers the margin.
    rig = build_rig(config_sdk=isolated_sdk("20000000"), account=_rich_account())
    verdict = await rig.guard.evaluate(
        request(quantity=Decimal("250"), stop_price=Decimal("70000"))
    )
    assert verdict.is_no_trade is False
    # One unit of quantity-notional above the maximum is refused.
    above = await build_rig(
        config_sdk=isolated_sdk("20000000"), account=_rich_account()
    ).guard.evaluate(request(quantity=Decimal("250.0000125"), stop_price=Decimal("70000")))
    assert above.reason_code == NOTIONAL_ABOVE_MAX
    # The 250 x 80000 plan with the 66000 stop is refused by the liquidation check (pure, first).
    close = await build_rig(config_sdk=isolated_sdk("20000000")).guard.evaluate(
        request(quantity=Decimal("250"))
    )
    assert close.reason_code == LIQUIDATION_TOO_CLOSE


async def test_the_leverage_used_for_the_checks_is_the_target_the_port_reports() -> None:
    # The port's target leverage is 2 (and it verifies 2): the initial margin uses 2, not 5.
    # Available 100 covers 160/5 + costs, but not 160 x 5 / 2 = 400 + costs.
    events: list[str] = []
    guard, _ = _scripted_guard(
        events,
        account=ScriptedAccount(usable_check(available="100"), events=events),
        config=ScriptedConfigGuard(config_result(leverage=2), events=events, target_leverage=2),
    )
    verdict = await guard.evaluate(request())
    assert verdict.reason_code == INSUFFICIENT
    events2: list[str] = []
    guard5, _ = _scripted_guard(
        events2, account=ScriptedAccount(usable_check(available="200"), events=events2)
    )
    assert (await guard5.evaluate(request())).is_no_trade is False


# ---- WR-01: the pure checks run before any configuration POST


def _pure_refusals() -> list[tuple[str, str, dict[str, Any], Callable[[GuardRig], None] | None]]:
    return [
        ("liquidation too close", LIQUIDATION_TOO_CLOSE, {"stop_price": Decimal("65000")}, None),
        ("leverage above the bracket", LEVERAGE_ABOVE_BRACKET, {"quantity": Decimal("1500")}, None),
        ("inverted stop", LIQUIDATION_INPUT_UNAVAILABLE, {"stop_price": Decimal("81000")}, None),
        ("insufficient margin", INSUFFICIENT, {"quantity": Decimal("10")}, None),
        ("no bracket reading", LIQUIDATION_INPUT_UNAVAILABLE, {}, _failing(BRACKET_READ)),
    ]


@pytest.mark.parametrize(
    ("edits", "code", "break_rig"),
    [pytest.param(e, c, b, id=name) for name, c, e, b in _pure_refusals()],
)
async def test_a_plan_refused_by_a_pure_check_leaves_the_recorded_account_untouched(
    edits: dict[str, Any], code: str, break_rig: Callable[[GuardRig], None] | None
) -> None:
    """WR-01: the recorded CROSSED x20 symbol stays CROSSED x20; no configuration call is made."""
    rig = build_rig()
    if break_rig is not None:
        break_rig(rig)
    verdict = await rig.guard.evaluate(request(**edits))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == code
    for name in CONFIG_CALLS:
        assert rig.rest.count(name) == 0, name
    assert (rig.rest.config_sdk.margin_type, rig.rest.config_sdk.leverage) == ("CROSSED", 20)
    assert verdict.config_changed is False
    assert verdict.previous_margin_type is None
    assert verdict.previous_leverage is None


async def test_a_repeated_refused_attempt_never_posts_while_the_plan_stays_unplaceable() -> None:
    # An approve tap repeated on a plan the guard cannot pass used to repeat the account mutation.
    rig = build_rig()
    for _ in range(3):
        verdict = await rig.guard.evaluate(request(stop_price=Decimal("65000")))
        assert verdict.reason_code == LIQUIDATION_TOO_CLOSE
    assert rig.rest.count(CONFIG_READ) == 0
    assert rig.rest.count(MARGIN_POST) == 0
    assert rig.rest.count(LEVERAGE_POST) == 0


async def test_a_passing_plan_sends_each_post_once_and_the_verification_read_decides() -> None:
    rig = build_rig()
    verdict = await rig.guard.evaluate(request())
    assert verdict.is_no_trade is False
    assert rig.rest.count(MARGIN_POST) == 1
    assert rig.rest.count(LEVERAGE_POST) == 1
    assert rig.rest.count(CONFIG_READ) == 2  # the first read and the verification read
    # The POSTs come after the bracket read: the pure checks were judged first.
    assert rig.rest.calls.index(BRACKET_READ) < rig.rest.calls.index(MARGIN_POST)


async def test_the_guard_judges_the_pure_checks_at_the_target_of_its_configuration_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    seen: list[dict[str, Any]] = []
    real = margin_guard_module.liquidation_verdict  # type: ignore[attr-defined]

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return real(**kwargs)

    guard, _ = _scripted_guard(
        events,
        config=ScriptedConfigGuard(config_result(leverage=3), events=events, target_leverage=3),
    )
    monkeypatch.setattr(margin_guard_module, "liquidation_verdict", spy)
    verdict = await guard.evaluate(request())
    assert verdict.is_no_trade is False
    assert verdict.leverage == 3
    (call,) = seen
    assert call["leverage"] == 3
    # the order: liquidation and margin judged BEFORE the configuration port is reached
    assert events.index("brackets") < events.index("claims") < events.index("config")


# ---- WR-09: the D035 cap holds in the guard whatever port reports the leverage


@pytest.mark.parametrize("bad", [6, 50])
def test_construction_refuses_a_target_leverage_above_the_d035_cap(bad: int) -> None:
    with pytest.raises(ValueError):
        _scripted_guard(
            [], config=ScriptedConfigGuard(config_result(leverage=bad), target_leverage=bad)
        )


@pytest.mark.parametrize("bad", [0, -1])
def test_construction_refuses_a_target_leverage_below_one(bad: int) -> None:
    with pytest.raises(ValueError):
        _scripted_guard([], config=ScriptedConfigGuard(config_result(), target_leverage=bad))


@pytest.mark.parametrize("bad", [None, True, 5.0, "5"])
def test_construction_refuses_a_target_leverage_that_is_not_a_plain_int(bad: Any) -> None:
    with pytest.raises(TypeError):
        _scripted_guard([], config=ScriptedConfigGuard(config_result(), target_leverage=bad))


async def test_a_port_that_verifies_fifty_x_is_refused_even_if_it_reports_a_5x_target() -> None:
    events: list[str] = []
    guard, _ = _scripted_guard(
        events, config=ScriptedConfigGuard(config_result(leverage=50), events=events)
    )
    verdict = await guard.evaluate(request())
    assert verdict.is_no_trade is True
    assert verdict.reason_code == UNCERTAIN


# ---- margin specifics


@pytest.mark.parametrize(
    ("available", "ok"),
    [("164.382912", True), ("164.382911", False)],
    ids=["equal passes", "one unit below fails"],
)
async def test_the_headroom_boundary_equal_passes_and_one_unit_below_fails(
    available: str, ok: bool
) -> None:
    account = account_payloads(information_edit=set_available_balance(available))
    verdict = await build_rig(config_sdk=isolated_sdk(), account=account).guard.evaluate(request())
    assert verdict.is_no_trade is (not ok)
    if not ok:
        assert verdict.reason_code == INSUFFICIENT


async def test_the_candidates_own_claim_is_excluded() -> None:
    rig = build_rig(config_sdk=isolated_sdk(), claims=[claim("P1", "99999")])
    assert (await rig.guard.evaluate(request())).is_no_trade is False


async def test_a_claims_port_that_returns_an_awaitable_is_accepted() -> None:
    events: list[str] = []
    guard, _ = _scripted_guard(events, claims=ScriptedClaims(awaitable=True, events=events))
    assert (await guard.evaluate(request())).is_no_trade is False


async def test_the_netting_constant_is_the_switch_and_the_guard_passes_the_module_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # True since DECISIONS D085 (2026-10-24, owner Demo run: availableBalance nets a resting order).
    assert margin_check.AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED is True
    assert margin_guard_module.AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED is True  # type: ignore[attr-defined]
    placed = claim("OTHER", "4900", ReservationStatus.PLACED)
    late = claim("OTHER", "4900", ReservationStatus.PLACED, placed_after_reading=True)
    # Pure function: the same PLACED claim, placed before the reading, counts with False only.
    assert other_claims_margin(
        claims=[placed],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=START,
        resting_orders_netted=False,
    ) == Decimal("4900")
    assert other_claims_margin(
        claims=[placed],
        exclude_trade_plan_id="P1",
        reading_observed_at_utc=START,
        resting_orders_netted=True,
    ) == Decimal(0)
    # Guard with the real constant (True): the claim placed at or before the reading is not counted
    # twice, so the plan is admitted; a claim placed AFTER the reading still counts and is refused.
    admitted = await build_rig(config_sdk=isolated_sdk(), claims=[placed]).guard.evaluate(request())
    assert admitted.is_no_trade is False
    still_counted = await build_rig(config_sdk=isolated_sdk(), claims=[late]).guard.evaluate(
        request()
    )
    assert still_counted.reason_code == INSUFFICIENT
    # The switch is the module constant the guard passes: patched to False (test-only), the same
    # early PLACED claim counts again and the plan is refused.
    monkeypatch.setattr(
        margin_guard_module, "AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED", False
    )
    blocked = await build_rig(config_sdk=isolated_sdk(), claims=[placed]).guard.evaluate(request())
    assert blocked.reason_code == INSUFFICIENT


# ---- every port failure is NO_TRADE with a class name only


class _Boom(Exception):
    pass


@pytest.mark.parametrize("failing", ["refresh", "check", "config", "brackets", "claims", "recheck"])
async def test_any_port_exception_is_uncertain_account_state_without_its_text(
    failing: str,
) -> None:
    events: list[str] = []
    boom = _Boom(SECRET)
    account = ScriptedAccount(
        usable_check(),
        events=events,
        refresh_exception=boom if failing == "refresh" else None,
        check_exception=boom if failing == "check" else None,
    )
    if failing == "recheck":
        calls = {"n": 0}

        def second_raises() -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise boom

        account = ScriptedAccount(usable_check(), events=events, on_check=second_raises)
    guard, _ = _scripted_guard(
        events,
        account=account,
        config=ScriptedConfigGuard(
            config_result(), events=events, exception=boom if failing == "config" else None
        ),
        brackets=ScriptedBrackets(
            BracketReading(symbol=SYMBOL, brackets=tuple(demo_brackets()), observed_at_utc=START),
            events=events,
            exception=boom if failing == "brackets" else None,
        ),
        claims=ScriptedClaims(events=events, exception=boom if failing == "claims" else None),
    )
    verdict = await guard.evaluate(request())
    assert verdict.is_no_trade is True
    assert verdict.reason_code == UNCERTAIN
    assert SECRET not in repr(verdict)
    assert "_Boom" not in repr(verdict)


async def test_a_configuration_exception_carries_no_evidence_and_a_later_one_keeps_it() -> None:
    # A failure BEFORE the configuration step (the claims read) sent nothing: no evidence.
    events: list[str] = []
    sent = config_result(posts_sent=2, previous_margin_type="CROSSED", previous_leverage=20)
    guard, ports = _scripted_guard(
        events,
        config=ScriptedConfigGuard(sent, events=events),
        claims=ScriptedClaims(events=events, exception=_Boom(SECRET)),
    )
    early = await guard.evaluate(request())
    assert early.reason_code == UNCERTAIN
    assert early.config_changed is False
    assert early.previous_margin_type is None
    assert ports["config"].calls == []
    # A failure AFTER it (the third reading judgement) keeps the evidence of the POSTs.
    events2: list[str] = []
    calls = {"n": 0}

    def third_raises() -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise _Boom(SECRET)

    guard2, _ = _scripted_guard(
        events2,
        account=ScriptedAccount(usable_check(), events=events2, on_check=third_raises),
        config=ScriptedConfigGuard(sent, events=events2),
    )
    late = await guard2.evaluate(request())
    assert late.reason_code == UNCERTAIN
    assert late.config_changed is True
    assert late.previous_margin_type == "CROSSED"
    assert late.previous_leverage == 20
    assert SECRET not in repr(late)


@pytest.mark.parametrize(
    "bad_config",
    [
        object(),
        config_result(margin_type="CROSSED"),
        config_result(leverage=None),
        config_result(leverage=True),
        config_result(leverage=0),
        config_result(max_notional_value=None),
        config_result(max_notional_value=Decimal("0")),
        config_result(leverage=6),  # above the D035 cap (WR-09)
        config_result(leverage=2),  # not the target the checks were judged at (WR-01)
    ],
    ids=[
        "not a result",
        "crossed",
        "no leverage",
        "bool leverage",
        "zero leverage",
        "no max",
        "max 0",
        "above the cap",
        "not the target",
    ],
)
async def test_a_malformed_or_unusable_configuration_answer_is_uncertain(bad_config: Any) -> None:
    events: list[str] = []
    guard, ports = _scripted_guard(events, config=ScriptedConfigGuard(bad_config, events=events))
    verdict = await guard.evaluate(request())
    assert verdict.reason_code == UNCERTAIN
    assert verdict.is_no_trade is True
    assert ports["config"].calls == [(SYMBOL, True)]  # the pure checks passed first


@pytest.mark.parametrize("bad_code", ["", "OK", None, 5])
async def test_a_refused_configuration_without_a_usable_code_is_uncertain(bad_code: Any) -> None:
    events: list[str] = []
    refused = dataclasses.replace(
        config_result(), ok=False, reason_code=bad_code, margin_type=None, leverage=None
    )
    guard, _ = _scripted_guard(events, config=ScriptedConfigGuard(refused, events=events))
    assert (await guard.evaluate(request())).reason_code == UNCERTAIN


async def test_a_bad_account_answer_is_uncertain() -> None:
    events: list[str] = []
    guard, ports = _scripted_guard(events, account=ScriptedAccount(object(), events=events))
    assert (await guard.evaluate(request())).reason_code == UNCERTAIN
    assert ports["config"].calls == []


@pytest.mark.parametrize(
    "reading_factory",
    [
        lambda: BracketReading(
            symbol="ETHUSDT", brackets=tuple(demo_brackets()), observed_at_utc=START
        ),
        lambda: BracketReading(symbol=SYMBOL, brackets=(), observed_at_utc=START),
        lambda: BracketReading(
            symbol=SYMBOL,
            brackets=tuple(demo_brackets()),
            observed_at_utc=START - timedelta(hours=1),
        ),
        lambda: BracketReading(
            symbol=SYMBOL,
            brackets=tuple(demo_brackets()),
            observed_at_utc=START + timedelta(hours=1),
        ),
        lambda: object(),
    ],
    ids=["other symbol", "empty", "stale", "future", "not a reading"],
)
async def test_an_unusable_bracket_reading_is_liquidation_input_unavailable(
    reading_factory: Callable[[], Any],
) -> None:
    events: list[str] = []
    guard, ports = _scripted_guard(
        events, brackets=ScriptedBrackets(reading_factory(), events=events)
    )
    verdict = await guard.evaluate(request())
    assert verdict.reason_code == LIQUIDATION_INPUT_UNAVAILABLE
    assert ports["claims"].calls == 0


async def test_a_stale_or_unusable_second_judgement_refuses_the_margin_check() -> None:
    events: list[str] = []
    seen: list[int] = []

    class _TwoFaced(ScriptedAccount):
        def check_margin(self, *, now_utc: Any) -> Any:
            seen.append(1)
            if len(seen) == 1:
                return usable_check()
            return refused_check(BLOCKED_READING_UNUSABLE)

    guard, ports = _scripted_guard(events, account=_TwoFaced(None, events=events))
    verdict = await guard.evaluate(request())
    assert verdict.reason_code == UNCERTAIN
    assert ports["claims"].calls == 1  # the claims were read; the reading no longer qualified


async def test_a_cancellation_is_not_swallowed() -> None:
    import asyncio

    events: list[str] = []
    guard, _ = _scripted_guard(
        events,
        brackets=ScriptedBrackets(None, events=events, exception=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await guard.evaluate(request())


# ---- request and verdict values


def test_the_request_validates_its_fields() -> None:
    good = request()
    assert good.side == "LONG"
    for bad in (
        {"trade_plan_id": ""},
        {"symbol": " "},
        {"side": "BUY"},
        {"quantity": Decimal("0")},
        {"limit_price": Decimal("-1")},
        {"stop_price": Decimal("NaN")},
        {"mark_price": Decimal("Infinity")},
        {"fee_rate_entry": Decimal("-0.1")},
        {"fee_rate_exit": Decimal("-0.1")},
    ):
        with pytest.raises(ValueError):
            request(**bad)
    for bad_type in (
        {"quantity": 0.01},
        {"limit_price": 80000},
        {"fee_rate_entry": 0.0004},
        {"symbol_is_flat": 1},
    ):
        with pytest.raises(TypeError):
            request(**bad_type)
    assert request(fee_rate_entry=Decimal("0")).fee_rate_entry == Decimal("0")
    with pytest.raises(dataclasses.FrozenInstanceError):
        good.symbol = "X"  # type: ignore[misc]


async def test_the_guard_refuses_something_that_is_not_a_request() -> None:
    guard, _ = _scripted_guard([])
    with pytest.raises(TypeError):
        await guard.evaluate("not a request")  # type: ignore[arg-type]


def _verdict(**overrides: Any) -> MarginGuardVerdict:
    fields: dict[str, Any] = {
        "is_no_trade": False,
        "reason_code": "OK",
        "alert_reason": None,
        "margin_type": "ISOLATED",
        "leverage": 5,
        "equity_used": Decimal("1"),
        "config_changed": False,
        "previous_margin_type": None,
        "previous_leverage": None,
    }
    fields.update(overrides)
    return MarginGuardVerdict(**fields)


def test_the_verdict_validates_pass_and_refusal_shapes() -> None:
    assert _verdict().leverage == 5
    refusal = _verdict(
        is_no_trade=True,
        reason_code=INSUFFICIENT,
        margin_type=None,
        leverage=None,
        equity_used=None,
        config_changed=True,
        previous_margin_type="CROSSED",
        previous_leverage=20,
    )
    assert refusal.config_changed is True
    for bad in (
        {"reason_code": INSUFFICIENT},  # a pass needs OK
        {"margin_type": None},
        {"leverage": None},
        {"leverage": 0},
        {"leverage": True},
        {"equity_used": None},
        {"equity_used": Decimal("NaN")},
        {"alert_reason": "X"},
        {"previous_leverage": 5.0},
        {"config_changed": 1},
    ):
        with pytest.raises((ValueError, TypeError)):
            _verdict(**bad)
    base_refusal = {
        "is_no_trade": True,
        "reason_code": INSUFFICIENT,
        "margin_type": None,
        "leverage": None,
        "equity_used": None,
    }
    for bad in (
        {"reason_code": "OK"},
        {"margin_type": "ISOLATED"},
        {"leverage": 5},
        {"equity_used": Decimal("1")},
        {"reason_code": ""},
    ):
        with pytest.raises(ValueError):
            _verdict(**{**base_refusal, **bad})


# ---- construction


def test_construction_refuses_while_a_margin_limit_is_not_configured() -> None:
    keys = {
        "margin_liquidation_buffer_bps": "margin.liquidation_buffer_bps",
        "margin_max_bracket_age_ms": "margin.max_bracket_age_ms",
        "margin_headroom_bps": "margin.headroom_bps",
    }
    for field_name, dotted in keys.items():
        with pytest.raises(ExecutionLimitsNotConfigured) as caught:
            _scripted_guard([], limits=only_limits(**{field_name: None}))
        assert caught.value.keys == (dotted,)
    with pytest.raises(ExecutionLimitsNotConfigured) as all_unset:
        _scripted_guard(
            [],
            limits=only_limits(
                margin_liquidation_buffer_bps=None,
                margin_max_bracket_age_ms=None,
                margin_headroom_bps=None,
            ),
        )
    assert all_unset.value.keys == tuple(keys.values())


@pytest.mark.parametrize("field_name", ["margin_liquidation_buffer_bps", "margin_headroom_bps"])
def test_construction_refuses_a_non_positive_limit(field_name: str) -> None:
    with pytest.raises(ValueError):
        _scripted_guard([], limits=only_limits(**{field_name: 0}))


def test_construction_refuses_a_bad_clock_port_or_limits() -> None:
    events: list[str] = []
    good: dict[str, Any] = {
        "config_guard": ScriptedConfigGuard(config_result(), events=events),
        "brackets": ScriptedBrackets(None, events=events),
        "account": ScriptedAccount(usable_check(), events=events),
        "claims": ScriptedClaims(events=events),
        "clock": MovingClock(),
        "limits": only_limits(),
    }
    MarginGuard(**good)
    for name, bad in (
        ("clock", "not callable"),
        ("limits", object()),
        ("config_guard", object()),
        ("brackets", None),
        ("account", object()),
        ("claims", object()),
    ):
        with pytest.raises(TypeError):
            MarginGuard(**{**good, name: bad})


# ---- logging and purity


async def test_no_log_event_on_success_or_refusal() -> None:
    with capture_logs() as ok_logs:
        await build_rig(config_sdk=isolated_sdk()).guard.evaluate(request())
    with capture_logs() as refused_logs:
        await build_rig(claims_exception=RuntimeError(SECRET)).guard.evaluate(request())
    assert ok_logs == []
    assert refused_logs == []


def test_the_refusal_codes_are_the_plain_strings_of_the_contract() -> None:
    assert MARGIN_MODE_UNSUPPORTED == "MARGIN_MODE_UNSUPPORTED"
    assert HEDGE_MODE_UNSUPPORTED == "HEDGE_MODE_UNSUPPORTED"
    assert MARGIN_CONFIG_UNVERIFIED == "MARGIN_CONFIG_UNVERIFIED"
    assert MARGIN_CONFIG_CHANGE_REFUSED == "MARGIN_CONFIG_CHANGE_REFUSED"
    assert AUTO_ADD_MARGIN_ENABLED == "AUTO_ADD_MARGIN_ENABLED"
    assert LIQUIDATION_INPUT_UNAVAILABLE == "LIQUIDATION_INPUT_UNAVAILABLE"
    assert NOTIONAL_ABOVE_MAX == "NOTIONAL_ABOVE_MAX"
    assert LEVERAGE_ABOVE_BRACKET == "LEVERAGE_ABOVE_BRACKET"
    assert LIQUIDATION_TOO_CLOSE == "LIQUIDATION_TOO_CLOSE"
    assert RejectionReason.UNCERTAIN_ACCOUNT_STATE.value == UNCERTAIN
    assert RejectionReason.INSUFFICIENT_MARGIN.value == INSUFFICIENT


def test_the_rejection_reason_enum_is_unchanged() -> None:
    assert len(RejectionReason) == 23, (
        "G3-005 (D-35): Phase 24 promoted NO_FILL and HEALTH_CHECK_FAILED, 23 members"
    )
    assert not {m.value for m in RejectionReason} & {
        MARGIN_MODE_UNSUPPORTED,
        MARGIN_CONFIG_UNVERIFIED,
        LIQUIDATION_TOO_CLOSE,
    }


def test_the_module_is_pure_and_holds_no_number_of_its_own() -> None:
    assert wall_clock_calls(MODULE) == []
    assert (
        forbidden_imports(MODULE, ["src.adapters", "src.persistence", "binance*", "sqlalchemy"])
        == []
    )
    source = MODULE.read_text(encoding="utf-8")
    assert "USDT" not in source
    assert "float(" not in source


def test_the_module_defines_no_limit_default_and_no_rate_or_leverage_constant() -> None:
    import ast

    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    numbers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ]
    # Only the structural 0 and 1 of comparisons: no limit, rate, bracket or leverage value.
    assert set(numbers) <= {0, 1}
