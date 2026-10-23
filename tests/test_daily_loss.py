"""Tests for the pure live daily-loss rules (Phase 21, plan 21-05; D033, D-06 to D-14).

Evidence label: executed unit tests [DESIGN]. No [DEMO] claim: the realizedPnl
semantics (commission excluded) are demo-observed (A9), not mainnet (G2-042).
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import DailyState, RejectionReason
from src.risk import daily_loss as dl
from src.risk.daily_loss import (
    BLOCKED_DAILY_LOSS_UNKNOWN,
    BLOCKED_DAY_BASE_UNAVAILABLE,
    BLOCKED_DAY_STATE_MISSING,
    BLOCKED_DAY_STATE_UNREADABLE,
    BLOCKED_DAY_THRESHOLDS_INVALID,
    FUNDING_LABEL_UNVERIFIED,
    FUNDING_LABEL_VERIFIED,
    ComponentKind,
    ComponentSource,
    DailyLossResult,
    DayOpenAction,
    DayRiskState,
    DayStateVerdict,
    FundingPolicy,
    LossComponent,
    base_is_inside_day,
    blocked_verdict,
    day_open_action,
    day_thresholds,
    evaluate_day_state,
    utc_day_of,
    utc_day_start,
)
from src.risk.portfolio import derive_daily_state

from tests.support.ast_guards import float_constructor_calls, module_imports, wall_clock_calls

MODULE_PATH = Path(dl.__file__)
QUOTE = "USDT"
DAY = date(2026, 10, 23)
NEXT_DAY = date(2026, 10, 24)
NOON = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
BASE_AT = datetime(2026, 10, 23, 0, 0, 5, tzinfo=UTC)
UNVERIFIED = FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING
REQUIRE = FundingPolicy.REQUIRE_VERIFIED_FUNDING_SOURCE
UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value

PARAMS: dict[str, Any] = {
    "daily_loss_warning_threshold": Decimal("0.005"),
    "daily_loss_stop_threshold": Decimal("0.01"),
    "cluster_cap": Decimal("0.006"),
    "max_aggregate_open_risk": Decimal("0.01"),
    "max_open_positions": 2,
}


def comp(
    kind: ComponentKind,
    amount: str,
    *,
    key: str = "BTCUSDT:1:1",
    source: ComponentSource = ComponentSource.USER_DATA_EVENT,
    asset: str = QUOTE,
    at: datetime = NOON,
) -> LossComponent:
    return LossComponent(
        kind=kind,
        source=source,
        source_key=key,
        amount=Decimal(amount),
        asset=asset,
        event_time_utc=at,
        utc_day=utc_day_of(at),
    )


def pnl(amount: str, **kw: Any) -> LossComponent:
    return comp(ComponentKind.FILL_PNL, amount, **kw)


def fee(amount: str, **kw: Any) -> LossComponent:
    return comp(ComponentKind.FILL_COMMISSION, amount, **kw)


def funding(amount: str, key: str = "BTCUSDT:900", **kw: Any) -> LossComponent:
    return comp(
        ComponentKind.FUNDING,
        amount,
        key=key,
        source=ComponentSource.REST_INCOME,
        **kw,
    )


def fold(
    components: list[LossComponent],
    *,
    trades_complete: bool = True,
    funding_read_ok: bool = True,
    policy: FundingPolicy = UNVERIFIED,
    day: date = DAY,
) -> DailyLossResult:
    return dl.fold_daily_loss(
        components=tuple(components),
        utc_day=day,
        quote_asset=QUOTE,
        trades_complete=trades_complete,
        funding_read_ok=funding_read_ok,
        funding_policy=policy,
    )


def day_state(equity: str = "1000", **kw: Any) -> DayRiskState:
    return DayRiskState(
        utc_day=kw.pop("utc_day", DAY),
        equity_at_day_start=Decimal(equity),
        base_observed_at_utc=kw.pop("base_observed_at_utc", BASE_AT),
        **kw,
    )


def known(loss: str, policy_label: str = FUNDING_LABEL_UNVERIFIED) -> DailyLossResult:
    return DailyLossResult(
        loss_quote=Decimal(loss),
        reason_code="OK",
        blocked_reason=None,
        divergent_keys=(),
        funding_label=policy_label,
    )


def unknown() -> DailyLossResult:
    return DailyLossResult(
        loss_quote=None,
        reason_code=UNCERTAIN,
        blocked_reason=BLOCKED_DAILY_LOSS_UNKNOWN,
        divergent_keys=(),
        funding_label=FUNDING_LABEL_UNVERIFIED,
    )


# ---------------------------------------------------------------- Task 1: fold


def test_one_fill_pnl_and_commission_give_loss_5_and_warning_boundary() -> None:
    result = fold([pnl("-4"), fee("-1")])
    assert result.loss_quote == Decimal("5")
    assert result.reason_code == "OK"
    assert result.blocked_reason is None
    thresholds = day_thresholds(parameter_set=PARAMS, day=day_state())
    assert thresholds is not None
    assert (
        derive_daily_state(daily_loss_quote=result.loss_quote, parameter_set=thresholds)
        is DailyState.WARNING
    )


def test_second_fill_brings_loss_to_10_and_daily_stop_boundary() -> None:
    result = fold([pnl("-4"), fee("-1"), pnl("-5", key="BTCUSDT:2:2")])
    assert result.loss_quote == Decimal("10")
    thresholds = day_thresholds(parameter_set=PARAMS, day=day_state())
    assert thresholds is not None
    assert (
        derive_daily_state(daily_loss_quote=result.loss_quote, parameter_set=thresholds)
        is DailyState.DAILY_STOP
    )


def test_net_gain_day_has_loss_zero_and_is_normal() -> None:
    result = fold([pnl("12"), fee("-1")])
    assert result.loss_quote == Decimal("0")
    assert not result.loss_quote.is_signed()
    thresholds = day_thresholds(parameter_set=PARAMS, day=day_state())
    assert thresholds is not None
    assert (
        derive_daily_state(daily_loss_quote=result.loss_quote, parameter_set=thresholds)
        is DailyState.NORMAL
    )


def test_empty_day_with_complete_sources_is_loss_zero() -> None:
    result = fold([])
    assert result.loss_quote == Decimal("0")
    assert result.funding_label == FUNDING_LABEL_UNVERIFIED


def test_commission_rebate_is_a_positive_component() -> None:
    result = fold([pnl("-4"), fee("0.5")])
    assert result.loss_quote == Decimal("3.5")


def test_same_fill_from_two_sources_counts_once_at_the_most_adverse_amount() -> None:
    result = fold(
        [
            pnl("-4", source=ComponentSource.USER_DATA_EVENT),
            pnl("-4.5", source=ComponentSource.REST_USER_TRADES),
        ]
    )
    assert result.loss_quote == Decimal("4.5")
    assert result.divergent_keys == ("BTCUSDT:1:1",)


def test_most_adverse_is_independent_of_which_source_is_lower() -> None:
    result = fold(
        [
            pnl("-4.5", source=ComponentSource.USER_DATA_EVENT),
            pnl("-4", source=ComponentSource.REST_USER_TRADES),
        ]
    )
    assert result.loss_quote == Decimal("4.5")
    assert result.divergent_keys == ("BTCUSDT:1:1",)


def test_most_adverse_for_a_gain_counts_the_smaller_gain() -> None:
    result = fold(
        [
            pnl("9", source=ComponentSource.USER_DATA_EVENT),
            pnl("-1", source=ComponentSource.REST_USER_TRADES),
        ]
    )
    assert result.loss_quote == Decimal("1")


def test_equal_amounts_from_two_sources_count_once_without_divergence() -> None:
    result = fold(
        [
            pnl("-4", source=ComponentSource.USER_DATA_EVENT),
            pnl("-4", source=ComponentSource.REST_USER_TRADES),
        ]
    )
    assert result.loss_quote == Decimal("4")
    assert result.divergent_keys == ()


def test_equal_amounts_with_different_exponent_are_not_divergent() -> None:
    result = fold(
        [
            pnl("-4.0", source=ComponentSource.USER_DATA_EVENT),
            pnl("-4.00", source=ComponentSource.REST_USER_TRADES),
        ]
    )
    assert result.divergent_keys == ()


def test_divergent_keys_are_sorted_and_cover_each_kind() -> None:
    result = fold(
        [
            pnl("-1", key="B:1:1", source=ComponentSource.USER_DATA_EVENT),
            pnl("-2", key="B:1:1", source=ComponentSource.REST_USER_TRADES),
            fee("-1", key="A:1:1", source=ComponentSource.USER_DATA_EVENT),
            fee("-2", key="A:1:1", source=ComponentSource.REST_USER_TRADES),
        ]
    )
    assert result.divergent_keys == ("A:1:1", "B:1:1")
    assert result.loss_quote == Decimal("4")


def test_same_component_twice_with_same_amount_counts_once() -> None:
    result = fold([pnl("-4"), pnl("-4")])
    assert result.loss_quote == Decimal("4")


def test_same_component_twice_with_different_amounts_raises() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        fold([pnl("-4"), pnl("-5")])


@pytest.mark.parametrize("kind", list(ComponentKind))
def test_a_component_in_another_asset_makes_the_loss_unknown(kind: ComponentKind) -> None:
    if kind is ComponentKind.FUNDING:
        odd = funding("-1", asset="BNB")
    else:
        odd = comp(kind, "-1", asset="BNB")
    result = fold([pnl("-4", key="BTCUSDT:9:9"), odd])
    assert result.loss_quote is None
    assert result.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert result.blocked_reason == BLOCKED_DAILY_LOSS_UNKNOWN


def test_incomplete_trade_sources_make_the_loss_unknown() -> None:
    result = fold([pnl("-4")], trades_complete=False)
    assert result.loss_quote is None
    assert result.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert result.blocked_reason == BLOCKED_DAILY_LOSS_UNKNOWN


@pytest.mark.parametrize("policy", [UNVERIFIED, REQUIRE])
def test_a_failed_funding_read_makes_the_loss_unknown_under_both_policies(
    policy: FundingPolicy,
) -> None:
    result = fold([pnl("-4")], funding_read_ok=False, policy=policy)
    assert result.loss_quote is None
    assert result.blocked_reason == BLOCKED_DAILY_LOSS_UNKNOWN


def test_require_verified_funding_source_is_unknown_while_unverified() -> None:
    assert dl.FUNDING_SOURCE_VERIFIED is False
    result = fold([pnl("-4")], policy=REQUIRE)
    assert result.loss_quote is None
    assert result.reason_code == "UNCERTAIN_ACCOUNT_STATE"


def test_require_verified_funding_source_counts_once_the_source_is_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dl, "FUNDING_SOURCE_VERIFIED", True)
    result = fold([pnl("-4"), funding("-2")], policy=REQUIRE)
    assert result.loss_quote == Decimal("6")
    assert result.funding_label == FUNDING_LABEL_VERIFIED


def test_unverified_funding_policy_is_known_with_zero_funding_rows_and_labelled() -> None:
    result = fold([pnl("-4")], policy=UNVERIFIED)
    assert result.loss_quote == Decimal("4")
    assert result.funding_label == FUNDING_LABEL_UNVERIFIED


def test_a_funding_payment_adds_to_the_loss() -> None:
    result = fold([pnl("-4"), funding("-2")])
    assert result.loss_quote == Decimal("6")


def test_a_funding_receipt_reduces_the_loss() -> None:
    result = fold([pnl("-4"), funding("1.5")])
    assert result.loss_quote == Decimal("2.5")


def test_fold_rejects_a_component_of_another_utc_day() -> None:
    other = pnl("-4", at=datetime(2026, 10, 22, 23, 59, 59, tzinfo=UTC))
    with pytest.raises(ValueError, match="utc_day"):
        fold([other])


def test_fold_is_independent_of_component_order() -> None:
    items = [pnl("-0.1"), fee("-0.2", key="X:2:2"), pnl("-0.3", key="Y:3:3"), funding("-0.4")]
    assert fold(items).loss_quote == fold(list(reversed(items))).loss_quote == Decimal("1.0")


def test_utc_day_of_midnight_belongs_to_the_new_day() -> None:
    assert utc_day_of(datetime(2026, 10, 24, 0, 0, 0, 0, tzinfo=UTC)) == NEXT_DAY
    assert utc_day_of(datetime(2026, 10, 23, 23, 59, 59, 999999, tzinfo=UTC)) == DAY
    assert utc_day_start(NEXT_DAY) == datetime(2026, 10, 24, 0, 0, 0, 0, tzinfo=UTC)


def test_utc_helpers_reject_naive_and_non_utc_times() -> None:
    with pytest.raises(ValueError, match="UTC"):
        utc_day_of(datetime(2026, 10, 23, 12, 0))
    with pytest.raises(ValueError, match="UTC"):
        utc_day_of(datetime(2026, 10, 23, 12, 0, tzinfo=timezone(timedelta(hours=2))))
    with pytest.raises(TypeError):
        utc_day_start(NOON)  # type: ignore[arg-type]


def test_component_utc_day_must_match_its_event_time() -> None:
    with pytest.raises(ValueError, match="utc_day"):
        LossComponent(
            kind=ComponentKind.FILL_PNL,
            source=ComponentSource.USER_DATA_EVENT,
            source_key="BTCUSDT:1:1",
            amount=Decimal("-1"),
            asset=QUOTE,
            event_time_utc=NOON,
            utc_day=NEXT_DAY,
        )


def test_funding_must_come_from_rest_income_and_fills_never() -> None:
    with pytest.raises(ValueError, match="FUNDING"):
        comp(ComponentKind.FUNDING, "-1", source=ComponentSource.USER_DATA_EVENT)
    with pytest.raises(ValueError, match="FUNDING"):
        comp(ComponentKind.FUNDING, "-1", source=ComponentSource.REST_USER_TRADES)
    with pytest.raises(ValueError, match="REST_INCOME"):
        comp(ComponentKind.FILL_PNL, "-1", source=ComponentSource.REST_INCOME)
    with pytest.raises(ValueError, match="REST_INCOME"):
        comp(ComponentKind.FILL_COMMISSION, "-1", source=ComponentSource.REST_INCOME)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"amount": 1.5},
        {"amount": Decimal("NaN")},
        {"amount": Decimal("Infinity")},
        {"amount": 3},
        {"source_key": ""},
        {"source_key": "k" * 129},
        {"asset": ""},
        {"kind": "FILL_PNL"},
        {"source": "USER_DATA_EVENT"},
    ],
)
def test_component_construction_validates_its_fields(kwargs: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "kind": ComponentKind.FILL_PNL,
        "source": ComponentSource.USER_DATA_EVENT,
        "source_key": "BTCUSDT:1:1",
        "amount": Decimal("-1"),
        "asset": QUOTE,
        "event_time_utc": NOON,
        "utc_day": DAY,
    }
    base.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        LossComponent(**base)


def test_component_source_key_of_128_chars_is_accepted() -> None:
    assert pnl("-1", key="k" * 128).source_key == "k" * 128


def test_component_requires_a_utc_event_time() -> None:
    with pytest.raises(ValueError, match="UTC"):
        LossComponent(
            kind=ComponentKind.FILL_PNL,
            source=ComponentSource.USER_DATA_EVENT,
            source_key="BTCUSDT:1:1",
            amount=Decimal("-1"),
            asset=QUOTE,
            event_time_utc=datetime(2026, 10, 23, 12, 0),
            utc_day=DAY,
        )


def test_result_coupling_between_loss_and_reason() -> None:
    with pytest.raises(ValueError):
        DailyLossResult(
            loss_quote=None,
            reason_code="OK",
            blocked_reason=None,
            divergent_keys=(),
            funding_label=FUNDING_LABEL_UNVERIFIED,
        )
    with pytest.raises(ValueError):
        DailyLossResult(
            loss_quote=Decimal("1"),
            reason_code=UNCERTAIN,
            blocked_reason=BLOCKED_DAILY_LOSS_UNKNOWN,
            divergent_keys=(),
            funding_label=FUNDING_LABEL_UNVERIFIED,
        )
    with pytest.raises(ValueError):
        DailyLossResult(
            loss_quote=Decimal("-1"),
            reason_code="OK",
            blocked_reason=None,
            divergent_keys=(),
            funding_label=FUNDING_LABEL_UNVERIFIED,
        )


# ------------------------------------------------- Task 1: thresholds / day base


def test_thresholds_come_from_the_day_start_base_only() -> None:
    thresholds = day_thresholds(parameter_set=PARAMS, day=day_state("1000"))
    assert thresholds is not None
    assert thresholds["daily_loss_warning_threshold"] == Decimal("5")
    assert thresholds["daily_loss_stop_threshold"] == Decimal("10")
    # A second state row with the same base resolves identically; the function takes
    # no current equity, so an intraday equity change cannot move the thresholds.
    again = day_thresholds(parameter_set=PARAMS, day=day_state("1000", base_observed_at_utc=NOON))
    assert again == thresholds
    other_base = day_thresholds(parameter_set=PARAMS, day=day_state("2000"))
    assert other_base is not None
    assert other_base["daily_loss_stop_threshold"] == Decimal("20")


def test_thresholds_are_none_for_a_malformed_parameter_set() -> None:
    broken = {k: v for k, v in PARAMS.items() if k != "daily_loss_stop_threshold"}
    assert day_thresholds(parameter_set=broken, day=day_state()) is None
    text = dict(PARAMS, cluster_cap="0.006")
    assert day_thresholds(parameter_set=text, day=day_state()) is None


def test_day_risk_state_validates_base_and_times() -> None:
    with pytest.raises(ValueError):
        day_state("0")
    with pytest.raises(ValueError):
        day_state("-5")
    with pytest.raises(ValueError):
        day_state("NaN")
    with pytest.raises(TypeError):
        DayRiskState(
            utc_day=DAY,
            equity_at_day_start=1000,  # type: ignore[arg-type]
            base_observed_at_utc=BASE_AT,
        )
    with pytest.raises(ValueError):
        day_state(base_observed_at_utc=datetime(2026, 10, 22, 23, 59, 59, tzinfo=UTC))
    with pytest.raises(ValueError):
        day_state(base_observed_at_utc=datetime(2026, 10, 24, 0, 0, 0, tzinfo=UTC))
    with pytest.raises(ValueError):
        day_state(base_observed_at_utc=datetime(2026, 10, 23, 1, 0))


# ----------------------------------------------------------- Task 1: purity


def test_module_reads_no_clock_and_builds_no_float() -> None:
    assert wall_clock_calls(MODULE_PATH) == []
    assert float_constructor_calls(MODULE_PATH) == []


def test_module_imports_only_stdlib_and_core_domain_risk() -> None:
    stdlib = set(sys.stdlib_module_names)
    allowed = ("src.domain", "src.core", "src.risk")
    for name in module_imports(MODULE_PATH):
        top = name.split(".")[0]
        assert top in stdlib or name.startswith(allowed), name


def test_module_has_no_literal_quote_asset_and_default_funding_flag_is_false() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "USDT" not in source
    assert "FUNDING_SOURCE_VERIFIED: bool = False" in source


def test_fold_has_no_default_for_the_funding_policy() -> None:
    with pytest.raises(TypeError):
        dl.fold_daily_loss(  # type: ignore[call-arg]
            components=(),
            utc_day=DAY,
            quote_asset=QUOTE,
            trades_complete=True,
            funding_read_ok=True,
        )
    assert {m.name for m in FundingPolicy} == {
        "TRADES_WITH_UNVERIFIED_FUNDING",
        "REQUIRE_VERIFIED_FUNDING_SOURCE",
    }


def test_rejection_reason_vocabulary_is_unchanged_at_21() -> None:
    assert len(list(RejectionReason)) == 21


# ------------------------------------------- Task 2: latch, alerts, day-open rule

LATCH_AT = datetime(2026, 10, 23, 9, 30, tzinfo=UTC)
WARNED_AT = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def evaluate(day: DayRiskState, loss: DailyLossResult) -> DayStateVerdict:
    return evaluate_day_state(day=day, loss=loss, parameter_set=PARAMS)


@pytest.mark.parametrize(
    "loss",
    [known("0"), known("3"), known("5"), unknown()],
    ids=["zero", "three", "warning-level", "unknown"],
)
def test_a_held_latch_wins_over_any_loss(loss: DailyLossResult) -> None:
    verdict = evaluate(day_state(stop_latched_at_utc=LATCH_AT), loss)
    assert verdict.state is DailyState.DAILY_STOP
    assert verdict.reason_code == "DAILY_STOP_BLOCK"
    assert verdict.blocked_reason is None
    assert verdict.latch_now is False
    assert verdict.alerts_due == ()
    assert verdict.utc_day == DAY


def test_a_later_gain_cannot_lift_a_latched_stop() -> None:
    verdict = evaluate(day_state(stop_latched_at_utc=LATCH_AT), fold([pnl("50")]))
    assert verdict.state is DailyState.DAILY_STOP


def test_a_newly_derived_daily_stop_asks_for_the_latch_and_alerts_once() -> None:
    verdict = evaluate(day_state(), known("10"))
    assert verdict.state is DailyState.DAILY_STOP
    assert verdict.reason_code == "DAILY_STOP_BLOCK"
    assert verdict.latch_now is True
    assert verdict.alerts_due == (DailyState.DAILY_STOP,)
    assert verdict.loss_quote == Decimal("10")


def test_a_jump_straight_to_daily_stop_alerts_daily_stop_only() -> None:
    verdict = evaluate(day_state(), known("50"))
    assert verdict.alerts_due == (DailyState.DAILY_STOP,)


def test_warning_alerts_once() -> None:
    first = evaluate(day_state(), known("5"))
    assert first.state is DailyState.WARNING
    assert first.reason_code == "OK"
    assert first.latch_now is False
    assert first.alerts_due == (DailyState.WARNING,)
    again = evaluate(day_state(warning_alerted_at_utc=WARNED_AT), known("5"))
    assert again.state is DailyState.WARNING
    assert again.alerts_due == ()


def test_a_warning_already_alerted_still_asks_for_the_latch_at_the_stop() -> None:
    verdict = evaluate(day_state(warning_alerted_at_utc=WARNED_AT), known("10"))
    assert verdict.latch_now is True
    assert verdict.alerts_due == (DailyState.DAILY_STOP,)


def test_below_the_warning_threshold_is_normal_with_no_alert() -> None:
    verdict = evaluate(day_state(), known("2"))
    assert verdict.state is DailyState.NORMAL
    assert verdict.reason_code == "OK"
    assert verdict.alerts_due == ()
    assert verdict.latch_now is False


def test_just_below_each_boundary() -> None:
    assert evaluate(day_state(), known("4.999999")).state is DailyState.NORMAL
    assert evaluate(day_state(), known("9.999999")).state is DailyState.WARNING


def test_unknown_loss_on_an_unlatched_day_is_uncertain_account_state() -> None:
    verdict = evaluate(day_state(), unknown())
    assert verdict.state is None
    assert verdict.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert verdict.blocked_reason == BLOCKED_DAILY_LOSS_UNKNOWN
    assert verdict.alerts_due == ()
    assert verdict.latch_now is False


def test_thresholds_do_not_move_with_intraday_equity() -> None:
    # The verdict is a function of the persisted base and the loss only: with base 1000
    # a loss of 10 is the stop whatever the account equity became during the day.
    assert evaluate(day_state("1000"), known("10")).state is DailyState.DAILY_STOP
    assert evaluate(day_state("1000"), known("9")).state is DailyState.WARNING
    assert evaluate(day_state("2000"), known("10")).state is DailyState.WARNING


def test_inverted_thresholds_are_rejected_on_the_live_path() -> None:
    inverted = dict(
        PARAMS,
        daily_loss_warning_threshold=Decimal("0.02"),
        daily_loss_stop_threshold=Decimal("0.01"),
    )
    verdict = evaluate_day_state(day=day_state(), loss=known("0"), parameter_set=inverted)
    assert verdict.state is None
    assert verdict.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert verdict.blocked_reason == BLOCKED_DAY_THRESHOLDS_INVALID


def test_equal_warning_and_stop_thresholds_are_not_inverted() -> None:
    equal = dict(
        PARAMS,
        daily_loss_warning_threshold=Decimal("0.01"),
        daily_loss_stop_threshold=Decimal("0.01"),
    )
    verdict = evaluate_day_state(day=day_state(), loss=known("0"), parameter_set=equal)
    assert verdict.state is DailyState.NORMAL


@pytest.mark.parametrize(
    "drop",
    [
        "daily_loss_warning_threshold",
        "daily_loss_stop_threshold",
        "cluster_cap",
        "max_aggregate_open_risk",
        "max_open_positions",
    ],
)
def test_a_parameter_set_missing_a_key_is_blocked_not_normal(drop: str) -> None:
    broken = {k: v for k, v in PARAMS.items() if k != drop}
    verdict = evaluate_day_state(day=day_state(), loss=known("100"), parameter_set=broken)
    assert verdict.state is None
    assert verdict.blocked_reason == BLOCKED_DAY_THRESHOLDS_INVALID


def test_a_latch_still_wins_over_invalid_thresholds() -> None:
    broken = {k: v for k, v in PARAMS.items() if k != "cluster_cap"}
    verdict = evaluate_day_state(
        day=day_state(stop_latched_at_utc=LATCH_AT), loss=known("0"), parameter_set=broken
    )
    assert verdict.state is DailyState.DAILY_STOP


@pytest.mark.parametrize(
    "reason",
    [
        BLOCKED_DAY_STATE_MISSING,
        BLOCKED_DAY_STATE_UNREADABLE,
        BLOCKED_DAY_BASE_UNAVAILABLE,
        BLOCKED_DAILY_LOSS_UNKNOWN,
        BLOCKED_DAY_THRESHOLDS_INVALID,
    ],
)
def test_blocked_verdict_is_uncertain_account_state(reason: str) -> None:
    verdict = blocked_verdict(utc_day=DAY, blocked_reason=reason)
    assert verdict.state is None
    assert verdict.reason_code == "UNCERTAIN_ACCOUNT_STATE"
    assert verdict.blocked_reason == reason
    assert verdict.alerts_due == ()
    assert verdict.latch_now is False
    assert verdict.loss_quote is None


def test_blocked_verdict_rejects_an_unknown_reason() -> None:
    with pytest.raises(ValueError):
        blocked_verdict(utc_day=DAY, blocked_reason="SOMETHING_ELSE")


def test_verdict_coupling_rules() -> None:
    with pytest.raises(ValueError):  # state None without a blocked reason
        DayStateVerdict(
            utc_day=DAY,
            state=None,
            reason_code="UNCERTAIN_ACCOUNT_STATE",
            blocked_reason=None,
            loss_quote=None,
            latch_now=False,
            alerts_due=(),
        )
    with pytest.raises(ValueError):  # a state with an UNCERTAIN reason
        DayStateVerdict(
            utc_day=DAY,
            state=DailyState.NORMAL,
            reason_code="UNCERTAIN_ACCOUNT_STATE",
            blocked_reason=None,
            loss_quote=Decimal("0"),
            latch_now=False,
            alerts_due=(),
        )
    with pytest.raises(ValueError):  # latch_now only with DAILY_STOP
        DayStateVerdict(
            utc_day=DAY,
            state=DailyState.WARNING,
            reason_code="OK",
            blocked_reason=None,
            loss_quote=Decimal("5"),
            latch_now=True,
            alerts_due=(),
        )
    with pytest.raises(ValueError):  # DAILY_STOP carries DAILY_STOP_BLOCK
        DayStateVerdict(
            utc_day=DAY,
            state=DailyState.DAILY_STOP,
            reason_code="OK",
            blocked_reason=None,
            loss_quote=Decimal("10"),
            latch_now=False,
            alerts_due=(),
        )


@pytest.mark.parametrize(
    ("today", "previous", "exposure", "readable", "expected"),
    [
        (False, True, False, False, DayOpenAction.BLOCKED_STORE_UNREADABLE),
        (True, True, True, False, DayOpenAction.BLOCKED_STORE_UNREADABLE),
        (True, False, True, True, DayOpenAction.USE_STORED),
        (True, False, None, True, DayOpenAction.USE_STORED),
        (False, True, False, True, DayOpenAction.OPEN_FROM_FRESH_BASE),
        (False, True, True, True, DayOpenAction.OPEN_FROM_FRESH_BASE),
        (False, True, None, True, DayOpenAction.OPEN_FROM_FRESH_BASE),
        (False, False, False, True, DayOpenAction.OPEN_FROM_FRESH_BASE),
        (False, False, True, True, DayOpenAction.BLOCKED_MISSING_STATE),
        (False, False, None, True, DayOpenAction.BLOCKED_MISSING_STATE),
    ],
)
def test_day_open_action_table(
    today: bool,
    previous: bool,
    exposure: bool | None,
    readable: bool,
    expected: DayOpenAction,
) -> None:
    action = day_open_action(
        today=day_state() if today else None,
        previous_day_present=previous,
        exposure=exposure,
        store_readable=readable,
    )
    assert action is expected


def test_base_is_inside_day_is_a_half_open_window() -> None:
    start = datetime(2026, 10, 23, 0, 0, 0, tzinfo=UTC)
    assert base_is_inside_day(utc_day=DAY, observed_at_utc=start) is True
    last = datetime(2026, 10, 23, 23, 59, 59, 999999, tzinfo=UTC)
    assert base_is_inside_day(utc_day=DAY, observed_at_utc=last) is True
    before = start - timedelta(microseconds=1)
    assert base_is_inside_day(utc_day=DAY, observed_at_utc=before) is False
    assert base_is_inside_day(utc_day=DAY, observed_at_utc=start + timedelta(days=1)) is False
    with pytest.raises(ValueError, match="UTC"):
        base_is_inside_day(utc_day=DAY, observed_at_utc=datetime(2026, 10, 23, 1, 0))


def test_a_latch_never_crosses_the_day_boundary() -> None:
    with pytest.raises(ValueError, match="outside"):
        day_state(utc_day=NEXT_DAY, stop_latched_at_utc=LATCH_AT)
    with pytest.raises(ValueError, match="outside"):
        day_state(utc_day=NEXT_DAY, warning_alerted_at_utc=WARNED_AT)
    fresh = day_state(
        utc_day=NEXT_DAY, base_observed_at_utc=datetime(2026, 10, 24, 0, 1, tzinfo=UTC)
    )
    verdict = evaluate(fresh, known("0"))
    assert verdict.state is DailyState.NORMAL
    assert verdict.utc_day == NEXT_DAY


def test_rollover_resets_the_state_machine_for_the_new_day() -> None:
    latched_day = evaluate(day_state(stop_latched_at_utc=LATCH_AT), known("0"))
    assert latched_day.state is DailyState.DAILY_STOP
    new_day = day_state(
        "985",
        utc_day=NEXT_DAY,
        base_observed_at_utc=datetime(2026, 10, 24, 0, 0, 3, tzinfo=UTC),
    )
    assert evaluate(new_day, known("0")).state is DailyState.NORMAL
