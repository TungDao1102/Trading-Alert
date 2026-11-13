"""SHADOW money block (Phase 24, plan 24-09; CONTEXT D-19, ROADMAP P23-R1, owner Q10, F-015).

Owner answer Q10 (24-01, 2026-10-31): a Phase 16 soak is running, so the money block ships as a NEW
SHADOW text version (`SHADOW_TEXT_V2`) and the old text and pins stay for `SHADOW_TEXT_V1`.

* V2: both approval rows carry the same `money_json` (canonical JSON of the block built from the
  pipeline output that sized the plan); the alert shows the money rows with the DEMO wording.
* V1: the alert carries no money rows and the rows carry no `money_json` (its Quantity line and
  the estimated-loss line follow D108).
* A plan whose money cannot be built is refused before anything is stored or sent.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.adapters.telegram_notify import format_presentation_time, render_money_block
from src.paper.shadow import (
    DEFAULT_SHADOW_TEXT_VERSION,
    SHADOW_TEXT_V1,
    SHADOW_TEXT_V2,
    Mode,
    ShadowApprovalBook,
    build_shadow_money,
    format_shadow_alert,
    send_shadow_alert,
)
from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.money_at_stake import (
    EQUITY_SOURCE_PAPER_CONFIG,
    LEVERAGE_SOURCE_PAPER_CONFIG,
    MONEY_AT_STAKE_MISSING,
    MoneyAtStakeUnavailable,
    money_canonical_json,
    parse_money_json,
)

from tests.shadow_fakes import (
    CHAT_ID,
    T0,
    FakeBot,
    InMemoryShadowStores,
    RecordingSleep,
    assert_shadow_text,
    make_shadow_money,
    make_shadow_plan,
    make_shadow_signal,
    make_shadow_sized,
)

REASONS = ["SETUP_DETECTED"]


def _alert(**extra: Any) -> dict[str, Any]:
    return {"exposure_quote": Decimal("0"), "reason_codes": REASONS, **extra}


async def _send(
    stores: InMemoryShadowStores, bot: FakeBot, book: ShadowApprovalBook, **extra: Any
) -> Any:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)
    return await send_shadow_alert(
        stores=stores,
        book=book,
        bot=bot,
        chat_id=CHAT_ID,
        mode=Mode.SHADOW,
        signal=signal,
        plan=plan,
        now_utc=T0,
        sleep=RecordingSleep(),
        sized=make_shadow_sized(plan),
        **_alert(**extra),
    )


# --------------------------------------------------------------------------- #
# The tracer: a sized plan -> money stored on both rows and shown in the alert (V2).
# --------------------------------------------------------------------------- #


async def test_d19_a_v2_alert_stores_the_money_on_both_rows_and_shows_the_money_rows() -> None:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)
    money = make_shadow_money(signal, plan)
    stores, bot = InMemoryShadowStores(), FakeBot()
    book = ShadowApprovalBook(stores, clock=lambda: T0, text_version=SHADOW_TEXT_V2)

    outcome = await _send(stores, bot, book, money=money)

    assert outcome.sent is True
    rows = list(stores.approvals.values())
    assert len(rows) == 2
    assert rows[0].money_json is not None and rows[0].money_json == rows[1].money_json
    # The stored text parses back to the block built from the sizing (T-24-22).
    assert parse_money_json(rows[0].money_json) == money
    assert rows[0].money_json == money_canonical_json(money)
    # The alert carries the DEMO money rows, right after the Quantity line.
    text = bot.sent[0].text
    assert_shadow_text(text)
    lines = text.split("\n")
    quantity_at = next(i for i, line in enumerate(lines) if line.startswith("Quantity: "))
    block = list(render_money_block(money))
    shown = lines[quantity_at + 1 : quantity_at + 1 + len(block)]
    # Same rows as the DEMO card; only the observation time uses the SHADOW UTC + Ho Chi Minh pair.
    assert shown[:-1] == block[:-1]
    assert shown[-1] == block[-1].replace(
        format_presentation_time(money.equity_observed_at_utc),
        "2026-10-09 02:55:00 UTC (2026-10-09 09:55:00 Asia/Ho_Chi_Minh)",
    )
    # 0.08 x 50100 = 4008; margin at 5x = 801.6; loss at SL gross = 0.08 x 600 = 48.
    assert "Notional: 4008.00 USDT" in text
    assert "Margin: 801.60 USDT at 5x leverage (PAPER_CONFIG:target_leverage)" in text
    assert "Loss at SL: 48.00 USDT gross, 48.5 USDT net of modeled costs" in text
    assert "Profit at TP1 (0.5 of quantity): 36.000 USDT gross, " in text
    assert "Profit at TP2 (0.5 of quantity): 76.000 USDT gross, " in text
    assert (
        "Equity used: 1000 USDT (PAPER_CONFIG:initial_equity, observed 2026-10-09 02:55:00" in text
    )


def test_d19_the_money_block_comes_from_the_sizing_not_from_a_recomputation() -> None:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)

    money = build_shadow_money(
        signal=signal,
        plan=plan,
        sized=make_shadow_sized(plan, realized_risk=Decimal("49.25")),
        cost_rates=CostRates(
            fee_rate_entry=Decimal("0.0005"),
            entry_slippage_rate=Decimal("0.0002"),
            fee_rate_exit=Decimal("0.0005"),
            exit_slippage_rate=Decimal("0.0002"),
            fee_source=FEE_SOURCE_PARAMETER,
        ),
        leverage=3,
        leverage_source=LEVERAGE_SOURCE_PAPER_CONFIG,
        equity=Decimal("500"),
        equity_source=EQUITY_SOURCE_PAPER_CONFIG,
        equity_observed_at_utc=T0 - timedelta(minutes=5),
    )

    assert money.loss_at_stop_net == Decimal("49.25")  # SizedResult.realized_risk, as is
    assert money.quantity == plan.quantity_after_rounding
    assert money.stop_loss_price == plan.stop_loss_price
    assert money.side == "LONG"
    assert [leg.price for leg in money.take_profits] == [Decimal("51000"), Decimal("52000")]
    assert money.leverage == 3 and money.equity == Decimal("500")


# --------------------------------------------------------------------------- #
# Fail closed: no money, no alert, no write, no send.
# --------------------------------------------------------------------------- #


async def test_d19_a_v2_alert_without_money_is_refused_before_any_write_or_send() -> None:
    trace: list[str] = []
    stores, bot = InMemoryShadowStores(trace), FakeBot(trace)
    book = ShadowApprovalBook(stores, clock=lambda: T0, text_version=SHADOW_TEXT_V2)

    with pytest.raises(MoneyAtStakeUnavailable) as raised:
        await _send(stores, bot, book)

    assert raised.value.reason_code == MONEY_AT_STAKE_MISSING
    assert trace == []
    assert bot.sent == [] and stores.approvals == {}


def test_d19_a_plan_whose_money_cannot_be_built_raises() -> None:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)

    with pytest.raises(MoneyAtStakeUnavailable) as raised:
        make_shadow_money(signal, plan, equity=None)
    assert raised.value.field == "equity"
    with pytest.raises(MoneyAtStakeUnavailable) as no_time:
        make_shadow_money(signal, plan, equity_observed_at_utc=None)
    assert no_time.value.field == "equity_observed_at_utc"
    with pytest.raises(MoneyAtStakeUnavailable):
        make_shadow_money(
            signal, plan, sized=make_shadow_sized(plan, is_no_trade=True, quantity=None)
        )
    with pytest.raises(MoneyAtStakeUnavailable, match="modeled_costs_per_unit"):
        make_shadow_money(signal, plan, sized=make_shadow_sized(plan, modeled_costs_per_unit=None))
    with pytest.raises(MoneyAtStakeUnavailable):
        make_shadow_money(signal, plan, leverage=None)


async def test_d19_a_money_block_that_disagrees_with_the_plan_is_refused() -> None:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)
    other_plan = make_shadow_plan(
        signal,
        quantity_after_rounding=Decimal("0.07"),
        quantity_before_rounding=Decimal("0.07"),
        suggested_quantity=Decimal("0.07"),
    )
    different = make_shadow_money(signal, other_plan)
    stores, bot = InMemoryShadowStores(), FakeBot()
    book = ShadowApprovalBook(stores, clock=lambda: T0, text_version=SHADOW_TEXT_V2)

    with pytest.raises(ValueError, match="differs from approved_quantity"):
        await _send(stores, bot, book, money=different)
    with pytest.raises(ValueError, match="differs from approved_quantity"):
        book.issue(signal=signal, plan=plan, now_utc=T0, money=different)

    assert bot.sent == [] and stores.approvals == {}


# --------------------------------------------------------------------------- #
# Text versions (owner Q10): V1 is the old text, byte for byte.
# --------------------------------------------------------------------------- #


def test_q10_the_default_text_version_is_the_old_one() -> None:
    assert DEFAULT_SHADOW_TEXT_VERSION == SHADOW_TEXT_V1
    assert ShadowApprovalBook(InMemoryShadowStores(), clock=lambda: T0).text_version == (
        SHADOW_TEXT_V1
    )


def test_q10_v2_differs_from_v1_only_by_the_money_rows() -> None:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)
    money = make_shadow_money(signal, plan)

    v1 = format_shadow_alert(
        signal=signal,
        plan=plan,
        mode=Mode.SHADOW,
        now_utc=T0,
        sized=make_shadow_sized(plan),
        **_alert(text_version=SHADOW_TEXT_V1),
    )
    v2 = format_shadow_alert(
        signal=signal,
        plan=plan,
        mode=Mode.SHADOW,
        now_utc=T0,
        sized=make_shadow_sized(plan),
        **_alert(text_version=SHADOW_TEXT_V2, money=money),
    )

    v1_lines, v2_lines = v1.split("\n"), v2.split("\n")
    extra = len(render_money_block(money))
    at = next(i for i, line in enumerate(v1_lines) if line.startswith("Quantity: ")) + 1
    assert v2_lines[:at] == v1_lines[:at]
    assert v2_lines[at + extra :] == v1_lines[at:]
    assert not any(line.startswith(("Notional: ", "Margin: ", "Loss at SL")) for line in v1_lines)


async def test_q10_a_v1_book_stores_no_money_and_refuses_a_block() -> None:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)
    money = make_shadow_money(signal, plan)
    stores, bot = InMemoryShadowStores(), FakeBot()
    book = ShadowApprovalBook(stores, clock=lambda: T0)

    await _send(stores, bot, book)

    assert all(row.money_json is None for row in stores.approvals.values())
    assert "Notional:" not in bot.sent[0].text
    with pytest.raises(ValueError, match="shadow-text/2"):
        book.issue(signal=signal, plan=plan, now_utc=T0, money=money)


def test_q10_an_unknown_text_version_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown SHADOW text version"):
        ShadowApprovalBook(InMemoryShadowStores(), clock=lambda: T0, text_version="shadow-text/9")
