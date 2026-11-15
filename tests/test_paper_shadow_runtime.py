"""SHADOW chain in the running process (Phase 16, plan 16-31, D-12, D-14, D-16, D-17, L-12, L-13).

`ShadowCoordinator` wires the SHADOW pieces built in isolation (alert and approval book of 16-04,
the D041 confirm step of 16-11, the fill driver and live minutes of 16-19, the paper ledger and
reservations of 16-23, the measured-delay record fields of 16-35) into one object the paper loop
hands its risk-passed bar outcomes to. Everything here runs on fakes: an in-memory store, the fake
bot of `tests/shadow_fakes.py` (it asserts the SHADOW label, the mode and both time zones on every
call) and a fake public adapter that holds recorded 1m trade and mark minutes. No network, no real
Telegram, no wall clock: the coordinator's clock is a movable test value.

Fake-level green never closes PAPER-02 (SC9): real taps and a position on live data come from the
rehearsal (plan 16-40).
"""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from src.adapters.binance_public import FundingTick, Kline, MarkKline
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.backtest.costs import build_cost_model
from src.core.types import Candle
from src.domain.approval import Approval
from src.domain.enums import ApprovalResult, DailyState
from src.domain.registry import load_parameter_set
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.ops.store_executor import WRITER_THREAD_PREFIX
from src.paper.loop import BarOutcome
from src.paper.pipeline import PipelineResult
from src.paper.shadow import SHADOW_LABEL, Mode
from src.paper.shadow_confirm import (
    EVENT_SHADOW_CONFIRM_CANCELLED,
    EVENT_SHADOW_CONFIRM_EXPIRED,
    EVENT_SHADOW_CONFIRMED,
)
from src.paper.shadow_ledger import (
    EVENT_SHADOW_POSITION_OPENED,
    ShadowLedger,
)
from src.paper.shadow_runtime import FillContext, ShadowCoordinator
from src.risk.types import ConstraintSnapshot, PortfolioVerdict, SizedResult
from telegram import error as tg_error

from tests.backtest_case_helpers import DEFAULT_COST_MODEL
from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    STRANGER_USER_ID,
    T0,
    USER_ID,
    FakeBot,
    InMemoryShadowStores,
    RecordingSleep,
    assert_shadow_text,
    keyboard_buttons,
    make_callback_update,
    make_shadow_plan,
    make_shadow_signal,
)

SRC = Path(__file__).resolve().parent.parent / "src" / "paper"
SHADOW_RUNTIME_PATH = SRC / "shadow_runtime.py"

SYMBOL = "BTCUSDT"
PARAMS = load_parameter_set("trend-pullback", "baseline-v5").params
# A TEST equity chosen for hand arithmetic (REV-07); never a ratified value.
EQUITY = Decimal("10000")
SIGNAL_CLOSE = T0 - timedelta(milliseconds=1)
LEDGER_START = T0 - timedelta(hours=2)
T_ALERT = T0 + timedelta(seconds=5)
T_APPROVE = T0 + timedelta(seconds=30)
T_CONFIRM = T0 + timedelta(seconds=40)
FIRST_MINUTE = T0 + timedelta(minutes=1)  # Q-B confirm-plus-one: the minute after the confirm
POLL_SECONDS = 60
LAG_SECONDS = 5
MINUTE = timedelta(minutes=1)
CONSTRAINTS = ConstraintSnapshot(
    symbol=SYMBOL,
    price_tick_size=Decimal("0.1"),
    quantity_step_size=Decimal("0.001"),
    min_quantity=Decimal("0.001"),
    min_notional=Decimal("5"),
    metadata_observed_at_utc=T0 - timedelta(hours=1),
)
EPOCH_ID = "e" * 64


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #


class RuntimeStores(InMemoryShadowStores):
    """The in-memory stores plus the three readers the running process needs."""

    def get_signal(self, signal_id: str) -> Signal | None:
        return self.signals.get(signal_id)

    def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None:
        return self.plans.get(trade_plan_id)

    def get_approval(self, approval_id: str) -> Approval | None:
        return self.approvals.get(approval_id)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _close(opened: datetime) -> datetime:
    return opened + timedelta(seconds=59, milliseconds=999)


@dataclass(frozen=True)
class Bar:
    """One scripted minute: open, high, low, close (identical for trade and mark)."""

    open: str
    high: str
    low: str
    close: str


# From the first eligible minute (03:01): a touch without a fill, a trade-through fill at the
# zone midpoint, a flat minute, then a drop through the 49500 stop.
SCRIPT: tuple[Bar, ...] = (
    Bar("50120", "50130", "50050", "50060"),
    Bar("50060", "50070", "50040", "50050"),
    Bar("50050", "50060", "50040", "50050"),
    Bar("50050", "50060", "49400", "49450"),
    Bar("49450", "49460", "49440", "49450"),
)


def scripted_trade(symbol: str = SYMBOL, start: datetime = FIRST_MINUTE) -> list[Kline]:
    out: list[Kline] = []
    for index, bar in enumerate(SCRIPT):
        opened = start + MINUTE * index
        out.append(
            Kline(
                symbol=symbol,
                interval="1m",
                open_time_utc=opened,
                close_time_utc=_close(opened),
                open=Decimal(bar.open),
                high=Decimal(bar.high),
                low=Decimal(bar.low),
                close=Decimal(bar.close),
                volume=Decimal("1"),
                quote_volume=Decimal("1"),
                trade_count=1,
            )
        )
    return out


def scripted_mark(symbol: str = SYMBOL, start: datetime = FIRST_MINUTE) -> list[MarkKline]:
    out: list[MarkKline] = []
    for index, bar in enumerate(SCRIPT):
        opened = start + MINUTE * index
        out.append(
            MarkKline(
                symbol=symbol,
                interval="1m",
                open_time_utc=opened,
                close_time_utc=_close(opened),
                open=Decimal(bar.open),
                high=Decimal(bar.high),
                low=Decimal(bar.low),
                close=Decimal(bar.close),
                price_tick_count=1,
            )
        )
    return out


class FakePublic:
    """The public adapter surface the coordinator reads: klines, mark klines, funding history."""

    def __init__(
        self,
        trade: Sequence[Kline] | None = None,
        mark: Sequence[MarkKline] | None = None,
        funding: Sequence[FundingTick] | None = None,
    ) -> None:
        self.trade = list(scripted_trade() if trade is None else trade)
        self.mark = list(scripted_mark() if mark is None else mark)
        self.funding = list(
            [FundingTick(SYMBOL, T0 - timedelta(hours=2), Decimal("0.0001"), Decimal("50000"))]
            if funding is None
            else funding
        )
        self.calls: list[str] = []
        self.fail_next: BaseException | None = None

    def _raise(self) -> None:
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.calls.append("klines")
        self._raise()
        return [
            r
            for r in self.trade
            if r.symbol == symbol
            and (start_ms is None or _ms(r.open_time_utc) >= start_ms)
            and (end_ms is None or _ms(r.open_time_utc) <= end_ms)
        ][:limit]

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        self.calls.append("mark_klines")
        self._raise()
        return [
            r
            for r in self.mark
            if r.symbol == symbol
            and (start_ms is None or _ms(r.open_time_utc) >= start_ms)
            and (end_ms is None or _ms(r.open_time_utc) <= end_ms)
        ][:limit]

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]:
        self.calls.append("funding_rate")
        self._raise()
        return [
            r
            for r in self.funding
            if r.symbol == symbol
            and (start_ms is None or _ms(r.funding_time_utc) >= start_ms)
            and (end_ms is None or _ms(r.funding_time_utc) <= end_ms)
        ][:limit]


def make_outcome(
    n: int = 1,
    *,
    stage: str = "risk_passed",
    symbol: str = SYMBOL,
    realized_risk: str = "48",
    quantity: str = "0.08",
) -> BarOutcome:
    """A bar outcome: the SHADOW fixture signal and plan of `n`; the risk stage sized `quantity`
    (default 0.08, the planner quantity of the fixture plan) for a risk of `realized_risk`."""
    signal = make_shadow_signal(n, symbol=symbol, source_candle_close_utc=SIGNAL_CLOSE)
    plan = make_shadow_plan(signal, plan_hash=str(n) * 64)
    candle = Candle(
        symbol=symbol,
        interval="1h",
        open_time_utc=SIGNAL_CLOSE - timedelta(hours=1) + timedelta(milliseconds=1),
        close_time_utc=SIGNAL_CLOSE,
        open=Decimal("50000"),
        high=Decimal("50200"),
        low=Decimal("49900"),
        close=Decimal("50050"),
        volume=Decimal("10"),
    )
    if stage != "risk_passed":
        return BarOutcome(
            closed_candle=candle,
            stage=stage,
            reason_code="NO_SETUP" if stage == "strategy" else "NO_TRADE",
            regime=None,
        )
    sized = SizedResult(
        is_no_trade=False,
        quantity=Decimal(quantity),
        quantity_before_rounding=Decimal(quantity),
        quantity_after_rounding=Decimal(quantity),
        quantization_decision="ACCEPTED",
        realized_risk=Decimal(realized_risk),
    )
    return BarOutcome(
        closed_candle=candle,
        stage="risk_passed",
        reason_code="OK",
        signal=signal,
        trade_plan=plan,
        verdict=PortfolioVerdict(False, sized, "OK", DailyState.NORMAL),
        regime="TREND",
    )


class Rig:
    """One process: stores, bot, public adapter, ledger and a coordinator on a movable clock.

    `restart()` builds a fresh process (new ledger, new coordinator, new books) on the SAME stores
    and the SAME public data, which is all that survives a restart.
    """

    def __init__(
        self,
        *,
        stores: RuntimeStores | None = None,
        public: FakePublic | None = None,
        bot: FakeBot | None = None,
        now: datetime = T_ALERT,
        confirm_ttl_seconds: int = 60,
        application_factory: Callable[[dict[str, Any]], Any] | None = None,
        constraints_for: Callable[[str, datetime], ConstraintSnapshot] | None = None,
        authorized_user_ids: frozenset[int] = AUTHORIZED_USER_IDS,
    ) -> None:
        self.authorized_user_ids = authorized_user_ids
        self.now = now
        self.constraints_for = (
            constraints_for if constraints_for is not None else lambda symbol, at: CONSTRAINTS
        )
        self.stores = stores if stores is not None else RuntimeStores()
        self.public = public if public is not None else FakePublic()
        self.bot = bot if bot is not None else FakeBot()
        self.sleep = RecordingSleep()
        self.ledger = ShadowLedger(
            initial_equity=EQUITY, parameter_set_params=PARAMS, started_at_utc=LEDGER_START
        )
        self.confirm_ttl_seconds = confirm_ttl_seconds
        self.application_factory = application_factory
        self.coordinator = self._build()

    def _build(self) -> ShadowCoordinator:
        return ShadowCoordinator(
            mode=Mode.SHADOW,
            stores=self.stores,
            bot=self.bot,
            chat_id=CHAT_ID,
            authorized_user_ids=self.authorized_user_ids,
            clock=lambda: self.now,
            ledger=self.ledger,
            public=self.public,
            fill=FillContext(
                cost_model=build_cost_model(dict(DEFAULT_COST_MODEL)),
                strategy_version="v1.0.0",
                parameter_set_hash="b" * 64,
                constraints_for=self.constraints_for,
            ),
            minute_poll_interval_seconds=POLL_SECONDS,
            minute_close_lag_seconds=LAG_SECONDS,
            experiment_id="exp-test",
            epoch_id=EPOCH_ID,
            confirm_ttl_seconds=self.confirm_ttl_seconds,
            sleep=self.sleep,
            application_factory=self.application_factory,
        )

    def restart(self, *, now: datetime | None = None) -> Rig:
        other = Rig(
            stores=self.stores,
            public=self.public,
            bot=self.bot,
            now=self.now if now is None else now,
            confirm_ttl_seconds=self.confirm_ttl_seconds,
            constraints_for=self.constraints_for,
        )
        return other

    # ---- driving the chain ------------------------------------------------ #

    async def alert(self, outcome: BarOutcome | None = None) -> Any:
        return await self.coordinator.on_outcome(outcome if outcome is not None else make_outcome())

    def buttons(self, index: int = 0) -> list[tuple[str, str]]:
        return keyboard_buttons(self.bot.sent[index].reply_markup)

    async def tap(
        self,
        data: str,
        query: str,
        *,
        at: datetime | None = None,
        chat_id: int = CHAT_ID,
        user: int | None = USER_ID,
        message_id: int | None = 1,
    ) -> DispatchResult:
        if at is not None:
            self.now = at
        update = make_callback_update(
            data=data, chat_id=chat_id, query_id=query, from_user_id=user, message_id=message_id
        )
        return await on_callback(update, cast(Any, None), **self.coordinator.callback_kwargs())

    async def approve_and_confirm(
        self, *, outcome: BarOutcome | None = None, short: str | None = None
    ) -> str:
        """Alert (when `short` is not given), APPROVE, CONFIRM: returns the short id."""
        if short is None:
            await self.alert(outcome)
            short = self.buttons()[0][1].removeprefix("APR:")
        await self.tap(f"APR:{short}", f"q-apr-{short[:6]}", at=T_APPROVE)
        await self.tap(f"CNF:{short}", f"q-cnf-{short[:6]}", at=T_CONFIRM)
        return short

    def journal(self, event_type: str) -> list[Any]:
        return self.stores.journal_of_type(event_type)


def payload(event: Any) -> dict[str, Any]:
    loaded = json.loads(event.payload_json)
    assert isinstance(loaded, dict)
    return loaded


def exposures(rig: Rig) -> list[tuple[str, str, Decimal]]:
    found, _loss = rig.ledger.risk_inputs(rig.now)
    return [(p.symbol, p.position_side, p.open_risk) for p in found]


# --------------------------------------------------------------------------- #
# Task 1, test 1: alert, APPROVE, confirmation card, CONFIRM, simulated position.
# --------------------------------------------------------------------------- #


def _lines_with(text: str, prefix: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith(prefix)]


async def test_a_risk_passed_plan_goes_alert_approve_card_confirm_and_a_simulated_position() -> (
    None
):
    rig = Rig()
    sent = await rig.alert()

    assert sent is not None and sent.sent
    assert len(rig.bot.sent) == 1
    alert = rig.bot.sent[0].text
    assert SHADOW_LABEL in alert
    assert "Mode: SHADOW" in alert
    # D108: the default sizing equals the planner quantity, so the alert shows it and the loss.
    assert "Quantity: 0.08" in alert
    assert "Estimated loss at SL (incl. costs): 48 quote" in alert
    assert [label for label, _ in rig.buttons()] == ["APPROVE", "SKIP"]
    short = rig.buttons()[0][1].removeprefix("APR:")
    assert rig.buttons()[1][1] == f"SKP:{short}"

    # APPROVE turns the alert into the confirmation card and confirms nothing (D041).
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    assert len(rig.bot.edited) == 1
    card = rig.bot.edited[0]
    assert "Confirm this SHADOW plan? No real order will be placed." in card.text
    assert _lines_with(card.text, "Quantity: ") == _lines_with(alert, "Quantity: ")
    assert _lines_with(card.text, "Estimated loss at SL") == _lines_with(
        alert, "Estimated loss at SL"
    )
    assert [data for _, data in keyboard_buttons(card.reply_markup)] == [
        f"CNF:{short}",
        f"CXL:{short}",
    ]
    assert rig.journal(EVENT_SHADOW_CONFIRMED) == []
    assert rig.coordinator.open_positions() == ()
    assert exposures(rig) == [], "APPROVE reserves nothing (Q-C reserve-at-confirm)"

    # CONFIRM inside the TTL opens the simulated position.
    await rig.tap(f"CNF:{short}", "q-cnf", at=T_CONFIRM)
    (confirmed,) = rig.journal(EVENT_SHADOW_CONFIRMED)
    body = payload(confirmed)
    assert body["confirmed_at_utc"] == T_CONFIRM.isoformat()
    # Q-B confirm-plus-one: the minute after the CONFIRM minute (03:00:40 -> 03:01:00).
    assert body["reservation"]["eligibility_start_utc"] == FIRST_MINUTE.isoformat()
    # Q-C: the exposure is reserved at CONFIRM, with the sized risk of the signal bar.
    assert exposures(rig) == [(SYMBOL, "LONG", Decimal("48"))]
    (position,) = rig.coordinator.open_positions()
    assert position.symbol == SYMBOL
    assert position.eligibility_start_utc == FIRST_MINUTE
    assert position.filled is False
    # The reply to the CONFIRM press is the SHADOW-only result, not an order.
    assert "SHADOW only: no order was placed." in rig.bot.sent[-1].text
    assert rig.journal(EVENT_SHADOW_POSITION_OPENED) == []

    # Live minutes arrive: the plan fills and the reservation becomes the position.
    rig.now = FIRST_MINUTE + timedelta(minutes=2, seconds=LAG_SECONDS + 1)
    await rig.coordinator.poll_once()
    (opened,) = rig.journal(EVENT_SHADOW_POSITION_OPENED)
    assert payload(opened)["fill_quantity"] == "0.080"
    assert rig.coordinator.open_positions()[0].filled is True
    assert exposures(rig) == [(SYMBOL, "LONG", Decimal("48"))], "one exposure, never counted twice"


async def test_d108_the_alert_and_the_card_show_the_same_risk_stage_figures() -> None:
    """D108 (owner decision 2026-11-13, option A): one message, one quantity.

    The alert reads the same `verdict.sized` as the card, so both show 0.05 and the loss 31.25,
    and the alert's `Exposure:` is that same 0.05 x the adverse entry. The approval rows keep the
    planner quantity 0.08 (D078).
    """
    rig = Rig()
    await rig.alert(make_outcome(quantity="0.05", realized_risk="31.25"))
    alert = rig.bot.sent[0].text
    short = rig.buttons()[0][1].removeprefix("APR:")

    assert _lines_with(alert, "Quantity: ") == ["Quantity: 0.05"]
    assert _lines_with(alert, "Estimated loss at SL (incl. costs): ") == [
        "Estimated loss at SL (incl. costs): 31.25 quote"
    ]
    assert "Quantity: 0.08" not in alert
    (exposure_line,) = _lines_with(alert, "Exposure: ")
    exposure = Decimal(exposure_line.removeprefix("Exposure: ").removesuffix(" quote"))
    assert exposure == Decimal("0.05") * Decimal("50100")
    assert rig.stores.approvals
    for row in rig.stores.approvals.values():
        assert row.approved_quantity == Decimal("0.08")

    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    card = rig.bot.edited[0].text
    assert _lines_with(card, "Quantity: ") == _lines_with(alert, "Quantity: ")
    assert _lines_with(card, "Estimated loss at SL (incl. costs): ") == _lines_with(
        alert, "Estimated loss at SL (incl. costs): "
    )


async def test_the_confirm_card_shows_what_the_ledger_reserves() -> None:
    """16-DEC-EQUITY-BASE: the card shows the risk-stage figures, not the planner quantity."""
    rig = Rig()
    await rig.alert(make_outcome(quantity="0.05", realized_risk="31.25"))
    short = rig.buttons()[0][1].removeprefix("APR:")

    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    card = rig.bot.edited[0].text
    assert "Quantity: 0.05" in card
    assert "Notional: 2505 quote" in card  # 0.05 x 50100, the adverse edge of the entry zone
    assert "Estimated loss at SL (incl. costs): 31.25 quote" in card
    assert "Quantity: 0.08" not in card

    await rig.tap(f"CNF:{short}", "q-cnf", at=T_CONFIRM)
    (confirmed,) = rig.journal(EVENT_SHADOW_CONFIRMED)
    reservation = payload(confirmed)["reservation"]
    assert reservation["planned_quantity"] == "0.05"
    assert reservation["sized_realized_risk"] == "31.25"
    assert exposures(rig) == [(SYMBOL, "LONG", Decimal("31.25"))]
    # The approval rows keep the planner quantity (owner choice, 16-DEC-EQUITY-BASE).
    approved = [a for a in rig.stores.approvals.values() if a.status == ApprovalResult.APPROVED]
    assert [a.approved_quantity for a in approved] == [Decimal("0.08")]


# --------------------------------------------------------------------------- #
# Task 1, test 2: nothing else becomes an alert.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stage", ["strategy", "planner", "risk"])
async def test_a_plan_that_did_not_pass_risk_sends_nothing_and_creates_no_approval(
    stage: str,
) -> None:
    rig = Rig()

    sent = await rig.coordinator.on_outcome(make_outcome(stage=stage))

    assert sent is None
    assert rig.bot.sent == [] and rig.bot.edited == []
    assert rig.stores.approvals == {} and rig.stores.signals == {} and rig.stores.plans == {}
    assert rig.stores.journal == []


async def test_warm_up_and_stale_results_hand_nothing_to_the_coordinator() -> None:
    rig = Rig()

    # The pipeline never evaluates a warm-up bar and drops a stale one: its result carries no
    # outcome, so there is nothing to hand over.
    assert await rig.coordinator.on_result(PipelineResult()) == []
    assert rig.bot.sent == [] and rig.stores.approvals == {}

    handed = await rig.coordinator.on_result(
        PipelineResult(evaluated=(make_outcome(stage="strategy"), make_outcome(1)))
    )
    assert len(handed) == 1, "only the risk-passed outcome is alerted"
    assert len(rig.bot.sent) == 1


async def test_the_same_plan_is_alerted_once() -> None:
    rig = Rig()
    outcome = make_outcome()
    await rig.alert(outcome)
    assert await rig.coordinator.on_outcome(outcome) is None
    assert len(rig.bot.sent) == 1


# --------------------------------------------------------------------------- #
# Task 1, test 3: the coordinator holds no order adapter (L-12, D040).
# --------------------------------------------------------------------------- #

ORDER_SURFACE_NAMES = frozenset(
    {
        "BinanceUsdmAdapter",
        "execute_approved_plan",
        "place_entry",
        "place_algo_protective",
        "new_order",
        "cancel_order",
    }
)


def imported_modules(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append(node.module)
    return found


def test_the_coordinator_imports_nothing_from_execution_and_names_no_order_adapter() -> None:
    source = SHADOW_RUNTIME_PATH.read_text(encoding="utf-8")
    modules = imported_modules(source)
    assert modules, "the module should import something"
    bad = [m for m in modules if m.startswith(("src.execution", "src.adapters.binance_usdm"))]
    assert bad == [], f"forbidden imports in shadow_runtime.py: {bad}"
    names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)
    }
    assert names & ORDER_SURFACE_NAMES == set()


def test_the_coordinator_takes_no_order_adapter_argument() -> None:
    import inspect

    parameters = set(inspect.signature(ShadowCoordinator).parameters)
    assert not any("order" in name or "exchange" in name for name in parameters), parameters


# --------------------------------------------------------------------------- #
# Task 1, test 4: label, mode and both time zones on every text of a session (D-12, D-35).
# --------------------------------------------------------------------------- #


async def _session_skip(rig: Rig) -> None:
    await rig.alert()
    skip = rig.buttons()[1][1]
    await rig.tap(skip, "q-skp", at=T_APPROVE)


async def _session_cancel(rig: Rig) -> None:
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    await rig.tap(f"CXL:{short}", "q-cxl", at=T_CONFIRM)


async def _session_confirm_expiry(rig: Rig) -> None:
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    await rig.tap(f"CNF:{short}", "q-cnf-late", at=T_APPROVE + timedelta(seconds=61))
    await rig.coordinator.expire_due()


async def _session_approval_expired(rig: Rig) -> None:
    await rig.alert()
    apr = rig.buttons()[0][1]
    await rig.tap(apr, "q-apr-late", at=T0 + timedelta(hours=4, seconds=1))


async def _session_replay(rig: Rig) -> None:
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)  # redelivery of the same callback
    await rig.tap(f"APR:{short}", "q-apr-2", at=T_APPROVE + timedelta(seconds=1))
    await rig.tap(f"CNF:{short}", "q-cnf", at=T_CONFIRM)
    await rig.tap(f"CNF:{short}", "q-cnf-2", at=T_CONFIRM + timedelta(seconds=1))


async def _session_full(rig: Rig) -> None:
    await rig.approve_and_confirm()
    rig.now = FIRST_MINUTE + timedelta(minutes=5, seconds=LAG_SECONDS + 1)
    await rig.coordinator.poll_once()


async def _session_card_delivery_failure(rig: Rig) -> None:
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    rig.bot.queue_error(tg_error.BadRequest("Message to edit not found"))
    rig.bot.queue_error(tg_error.NetworkError("fallback send failed"))
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)


SESSIONS: dict[str, Callable[[Rig], Any]] = {
    "full": _session_full,
    "skip": _session_skip,
    "cancel": _session_cancel,
    "confirm_expiry": _session_confirm_expiry,
    "approval_expired": _session_approval_expired,
    "replay": _session_replay,
    "card_delivery_failure": _session_card_delivery_failure,
}


@pytest.mark.parametrize("name", sorted(SESSIONS))
async def test_every_text_of_a_session_carries_the_label_the_mode_and_both_time_zones(
    name: str,
) -> None:
    rig = Rig()

    await SESSIONS[name](rig)

    texts = [m.text for m in rig.bot.sent] + [m.text for m in rig.bot.edited]
    assert texts, "the session should have sent something"
    for text in texts:
        assert_shadow_text(text)  # the fake bot already asserted it on every call, raising or not
        assert SHADOW_LABEL in text and "Mode: SHADOW" in text
    outcomes = {
        "skip": [],
        "cancel": [EVENT_SHADOW_CONFIRM_CANCELLED],
        "confirm_expiry": [EVENT_SHADOW_CONFIRM_EXPIRED],
        "card_delivery_failure": [EVENT_SHADOW_CONFIRM_EXPIRED],
        "full": [EVENT_SHADOW_CONFIRMED],
        "replay": [EVENT_SHADOW_CONFIRMED],
        "approval_expired": [],
    }[name]
    for event_type in outcomes:
        assert rig.journal(event_type), f"{name}: {event_type} should be journaled"


TEXT_SENDERS = frozenset({"send_text", "edit_text", "edit_to_confirm_card"})
COMPOSERS = frozenset({"render_shadow_message", "format_shadow_alert", "render_confirm_card"})
# Attribute reads that carry composed text: `ConfirmEntry.card_text` is assigned only from
# `render_confirm_card` (checked below).
COMPOSED_ATTRIBUTES = frozenset({"card_text"})


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _text_argument(call: ast.Call) -> ast.expr | None:
    """The `text` argument of a send or edit call (positional index 2 or 4, or keyword)."""
    for keyword in call.keywords:
        if keyword.arg == "text":
            return keyword.value
    index = {"send_text": 2, "edit_text": 3, "edit_to_confirm_card": 3, "_try_edit": 3}[
        cast(str, _call_name(call))
    ]
    return call.args[index] if len(call.args) > index else None


def unlabelled_text_sources(source: str) -> list[str]:
    """Violations: a send or edit whose text does not come from the composer (pure scan).

    A text expression is composed when it is a call of a composer, an attribute read from the
    composed attributes, or a name that every assignment (or, for a parameter, every call site in
    the module) binds to a composed expression.
    """
    tree = ast.parse(source)
    functions = [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    by_name: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for function in functions:
        by_name.setdefault(function.name, []).append(function)
    violations: list[str] = []

    def composed(expr: ast.expr, scope: ast.FunctionDef | ast.AsyncFunctionDef, depth: int) -> bool:
        if depth > 6:
            return False
        if isinstance(expr, ast.Call):
            return _call_name(expr) in COMPOSERS
        if isinstance(expr, ast.Attribute):
            return expr.attr in COMPOSED_ATTRIBUTES
        if isinstance(expr, ast.Name):
            assigned = [
                node.value
                for node in ast.walk(scope)
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == expr.id for t in node.targets)
            ]
            if assigned:
                return all(composed(value, scope, depth + 1) for value in assigned)
            params = [
                a.arg for a in [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]
            ]
            if expr.id not in params:
                return False
            position = params.index(expr.id)
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and _call_name(node) == scope.name
            ]
            if not calls:
                return False
            for call in calls:
                argument: ast.expr | None = None
                for keyword in call.keywords:
                    if keyword.arg == expr.id:
                        argument = keyword.value
                if argument is None and len(call.args) > position:
                    argument = call.args[position]
                if argument is None:
                    return False
                caller = next(
                    (
                        f
                        for f in functions
                        if any(n is call for n in ast.walk(f)) and f is not scope
                    ),
                    None,
                )
                if caller is None or not composed(argument, caller, depth + 1):
                    return False
            return True
        return False

    for function in functions:
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and _call_name(node) in TEXT_SENDERS | {"_try_edit"}:
                if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "self":
                    continue
                argument = _text_argument(node)
                if argument is None:
                    violations.append(f"{function.name}:{node.lineno}: no text argument")
                elif not composed(argument, function, 0):
                    violations.append(f"{function.name}:{node.lineno}: {ast.unparse(argument)}")
    return sorted(violations)


def test_the_text_scan_finds_a_seeded_unlabelled_send() -> None:
    seeded = (
        "async def go(bot, chat):\n"
        "    text = 'hello'\n"
        "    await send_text(bot, chat, text)\n"
        "async def ok(bot, chat):\n"
        "    text = render_shadow_message(1)\n"
        "    await send_text(bot, chat, text)\n"
    )
    assert unlabelled_text_sources(seeded) == ["go:3: text"]


def text_call_count(source: str) -> int:
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and _call_name(node) in TEXT_SENDERS | {"_try_edit"}
    )


@pytest.mark.parametrize(
    ("module", "expected_calls"),
    [("shadow_runtime.py", 0), ("shadow.py", 2), ("shadow_confirm.py", 4)],
)
def test_every_send_and_edit_text_comes_from_the_composer(module: str, expected_calls: int) -> None:
    source = (SRC / module).read_text(encoding="utf-8")
    # The scan is not vacuous: it finds the real sends of the two modules that make them.
    assert text_call_count(source) == expected_calls
    assert unlabelled_text_sources(source) == []


def test_the_confirm_entry_card_text_is_assigned_only_from_the_card_composer() -> None:
    tree = ast.parse((SRC / "shadow_confirm.py").read_text(encoding="utf-8"))
    values = [
        kw.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "card_text"
    ]
    assert values
    assert all(isinstance(v, ast.Call) and _call_name(v) == "render_confirm_card" for v in values)


# --------------------------------------------------------------------------- #
# Task 1: wired into run_admitted - the consumer hands risk-passed outcomes over.
# --------------------------------------------------------------------------- #

from src.paper.shadow_runtime import ShadowWiring  # noqa: E402
from src.paper.vocabulary import RuntimeEventType  # noqa: E402

from tests import test_paper_runtime_loop as loop_tests  # noqa: E402
from tests.test_paper_runtime_loop import PAST_OPEN, Live, wait_until  # noqa: E402
from tests.test_paper_runtime_loop import FakePublic as LoopPublic  # noqa: E402

# The admitted-runtime fixtures of plan 16-26's loop tests, re-exposed to this module.
live = loop_tests.live
_isolated_sdk_stream_map = loop_tests._isolated_sdk_stream_map


class SpyPipeline:
    """A pipeline double: every batch evaluates to the scripted outcomes (HandlesBars)."""

    def __init__(self, outcomes: Sequence[BarOutcome]) -> None:
        self.outcomes = tuple(outcomes)
        self.batches: list[int] = []

    def handle(self, bars: Any, *, now_utc: datetime) -> PipelineResult:
        batch = list(bars)
        self.batches.append(len(batch))
        return PipelineResult(evaluated=self.outcomes if batch else ())


class RuntimePublic(LoopPublic):
    """The loop's public fake plus the minute and funding calls the chain reads."""

    def __init__(self) -> None:
        super().__init__()
        self.inner = FakePublic()

    async def mark_klines(self, *args: Any, **kwargs: Any) -> Any:
        return await self.inner.mark_klines(*args, **kwargs)

    async def funding_rate(self, *args: Any, **kwargs: Any) -> Any:
        return await self.inner.funding_rate(*args, **kwargs)


def test_the_running_loop_hands_a_risk_passed_outcome_to_the_shadow_chain(live: Live) -> None:
    stores = RuntimeStores()
    bot = FakeBot()
    live.public = RuntimePublic()
    pipeline = SpyPipeline([make_outcome(1), make_outcome(2, stage="strategy")])

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: len(bot.sent) == 1)

    code = live.start(
        script,
        pipeline=pipeline,
        risk_inputs=None,
        shadow=ShadowWiring(
            stores=stores,
            chat_id=CHAT_ID,
            authorized_user_ids=AUTHORIZED_USER_IDS,
            bot=bot,
            sleep=RecordingSleep(),
        ),
    )

    assert code == 0
    assert len(bot.sent) == 1, "only the risk-passed outcome becomes an alert"
    assert SHADOW_LABEL in bot.sent[0].text and "Mode: SHADOW" in bot.sent[0].text
    assert len(stores.approvals) == 2, "one APPROVE and one SKIP row"


def test_the_start_is_not_refused_when_the_shadow_chain_binds_the_risk_inputs(
    live: Live,
) -> None:
    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)

    live.public = RuntimePublic()
    code = live.start(
        script,
        pipeline=SpyPipeline([]),
        risk_inputs=None,
        context_factory=None,
        shadow=ShadowWiring(
            stores=RuntimeStores(),
            chat_id=CHAT_ID,
            authorized_user_ids=AUTHORIZED_USER_IDS,
            bot=FakeBot(),
        ),
    )
    assert code == 0
    assert live.records(RuntimeEventType.RUNTIME_START)


# --------------------------------------------------------------------------- #
# Task 2: positions on live minutes, ledger feedback into the risk verdict, Telegram lifecycle.
# --------------------------------------------------------------------------- #

import asyncio  # noqa: E402
import threading  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from src.backtest.ledger import daily_loss_quote  # noqa: E402
from src.backtest.semantics import EXIT_SL  # noqa: E402
from src.paper.market_inputs import make_context_factory  # noqa: E402
from src.paper.runtime_config import AccountConfig  # noqa: E402
from src.paper.shadow_ledger import (  # noqa: E402
    EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
)
from src.paper.shadow_runtime import EVENT_SHADOW_POSITION_CLOSED  # noqa: E402
from structlog.testing import capture_logs  # noqa: E402

HOUR = timedelta(hours=1)
ETH = "ETHUSDT"


def rig_with(public: FakePublic, **kwargs: Any) -> Rig:
    return Rig(public=public, **kwargs)


async def poll_at(rig: Rig, now: datetime) -> None:
    rig.now = now
    await rig.coordinator.poll_once()


def after_minutes(count: int) -> datetime:
    """A poll instant whose settled horizon is `count` whole minutes after the first minute."""
    return FIRST_MINUTE + MINUTE * count + timedelta(seconds=LAG_SECONDS + 1)


async def test_positions_advance_on_live_minutes_book_funding_and_record_the_close() -> None:
    funding = [
        FundingTick(SYMBOL, T0 - timedelta(hours=2), Decimal("0.0001"), Decimal("50000")),
        # A funding instant inside the holding window (fill 03:02:59.999, stop 03:04:59.999).
        FundingTick(
            SYMBOL, T0 + timedelta(minutes=3, seconds=30), Decimal("0.0001"), Decimal("50000")
        ),
    ]
    rig = rig_with(FakePublic(funding=funding))
    await rig.approve_and_confirm()

    await poll_at(rig, after_minutes(2))
    (opened,) = rig.journal(EVENT_SHADOW_POSITION_OPENED)
    assert (
        payload(opened)["opened_at_utc"]
        == (FIRST_MINUTE + MINUTE * 2 - timedelta(milliseconds=1)).isoformat()
    )
    assert rig.ledger.equity < EQUITY, "the entry fee is booked on the ledger at the fill"
    assert rig.journal(EVENT_SHADOW_POSITION_CLOSED) == []

    await poll_at(rig, after_minutes(5))
    (closed,) = rig.journal(EVENT_SHADOW_POSITION_CLOSED)
    body = payload(closed)
    assert body["exit_kind"] == EXIT_SL
    assert body["trade"]["exit_kind"] == EXIT_SL
    assert body["trade"]["funding_event_count"] == 1, "funding during the position is booked"
    assert body["eligibility"]["status"] == "ELIGIBLE"
    assert body["eligibility"]["eligibility_start_utc"] == FIRST_MINUTE.isoformat()
    realized = Decimal(body["trade"]["realized_pnl"])
    assert realized < 0
    assert rig.ledger.equity == EQUITY + realized
    assert exposures(rig) == [], "the closed position no longer carries risk"
    (view,) = rig.coordinator.open_positions()
    assert view.closed and view.filled

    # Polling again changes nothing and journals nothing twice.
    await poll_at(rig, after_minutes(5) + timedelta(minutes=1))
    assert len(rig.journal(EVENT_SHADOW_POSITION_CLOSED)) == 1
    assert len(rig.journal(EVENT_SHADOW_POSITION_OPENED)) == 1
    assert rig.ledger.equity == EQUITY + realized


async def test_a_poll_with_no_position_reads_no_minutes() -> None:
    rig = Rig()
    await rig.alert()
    rig.now = after_minutes(2)
    await rig.coordinator.poll_once()
    assert "klines" not in rig.public.calls
    assert rig.public.calls.count("mark_klines") == 1, "only the best-effort mark of the alert"


# --------------------------------------------------------------------------- #
# Plan 24-05 (D-25, P16R-03): the confirm sweep leaves the event loop.
# --------------------------------------------------------------------------- #

TEST_ONLY_WAIT_SECONDS = 5.0


def _spy_expire_due(rig: Rig, threads: list[str], gate: threading.Event | None = None) -> None:
    """Replace the confirm book's `expire_due` by a spy that records its thread, then delegates."""
    real = rig.coordinator.confirm_book.expire_due

    def spy(now_utc: datetime) -> list[str]:
        threads.append(threading.current_thread().name)
        if gate is not None:
            assert gate.wait(TEST_ONLY_WAIT_SECONDS), "the test never released the sweep"
        return real(now_utc)

    rig.coordinator.confirm_book.expire_due = spy  # type: ignore[method-assign]


async def test_the_confirm_sweep_of_a_poll_runs_on_the_store_writer_thread() -> None:
    rig = Rig()
    threads: list[str] = []
    _spy_expire_due(rig, threads)
    rig.now = after_minutes(1)
    await rig.coordinator.poll_once()
    await rig.coordinator.poll_once()
    assert len(threads) == 2
    assert all(name.startswith(WRITER_THREAD_PREFIX) for name in threads), threads
    assert threading.current_thread().name not in threads
    await rig.coordinator.stop()


async def test_the_public_expire_due_also_runs_on_the_store_writer_thread() -> None:
    rig = Rig()
    threads: list[str] = []
    _spy_expire_due(rig, threads)
    assert await rig.coordinator.expire_due() == []
    assert len(threads) == 1 and threads[0].startswith(WRITER_THREAD_PREFIX)
    await rig.coordinator.stop()


async def test_a_slow_confirm_sweep_does_not_block_the_event_loop() -> None:
    rig = Rig()
    started = threading.Event()
    release = threading.Event()
    threads: list[str] = []

    real = rig.coordinator.confirm_book.expire_due

    def blocking(now_utc: datetime) -> list[str]:
        threads.append(threading.current_thread().name)
        started.set()
        assert release.wait(TEST_ONLY_WAIT_SECONDS), "the test never released the sweep"
        return real(now_utc)

    rig.coordinator.confirm_book.expire_due = blocking  # type: ignore[method-assign]
    rig.now = after_minutes(1)
    poll = asyncio.create_task(rig.coordinator.poll_once())
    assert await asyncio.to_thread(started.wait, TEST_ONLY_WAIT_SECONDS)
    ticks = 0
    for _ in range(5):  # the loop keeps turning while the sweep is stuck in the worker
        await asyncio.sleep(0)
        ticks += 1
    assert ticks == 5 and not poll.done()
    release.set()
    await asyncio.wait_for(poll, timeout=TEST_ONLY_WAIT_SECONDS)
    assert threads[0].startswith(WRITER_THREAD_PREFIX)
    await rig.coordinator.stop()


async def test_a_confirm_that_times_out_is_still_expired_and_journaled_by_the_off_loop_sweep() -> (
    None
):
    rig = Rig()
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{short}", "q-apr-sweep", at=T_APPROVE)
    rig.now = T_APPROVE + timedelta(seconds=61)  # past the 60 s confirm TTL, never pressed
    await rig.coordinator.poll_once()
    assert len(rig.journal(EVENT_SHADOW_CONFIRM_EXPIRED)) == 1
    await rig.coordinator.poll_once()
    assert len(rig.journal(EVENT_SHADOW_CONFIRM_EXPIRED)) == 1, "a second sweep writes nothing"
    await rig.coordinator.stop()


async def test_stop_closes_the_store_executor_and_a_later_poll_skips_the_sweep() -> None:
    rig = Rig()
    threads: list[str] = []
    _spy_expire_due(rig, threads)
    await rig.coordinator.stop()
    await rig.coordinator.stop()  # idempotent, also without an application
    rig.now = after_minutes(1)
    await rig.coordinator.poll_once()  # the runtime may poll once more while it shuts down
    assert threads == []
    with pytest.raises(RuntimeError, match="closed"):
        await rig.coordinator.expire_due()


async def test_stop_waits_for_a_sweep_that_is_in_flight() -> None:
    rig = Rig()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    real = rig.coordinator.confirm_book.expire_due

    def blocking(now_utc: datetime) -> list[str]:
        started.set()
        assert release.wait(TEST_ONLY_WAIT_SECONDS)
        try:
            return real(now_utc)
        finally:
            finished.set()

    rig.coordinator.confirm_book.expire_due = blocking  # type: ignore[method-assign]
    rig.now = after_minutes(1)
    poll = asyncio.create_task(rig.coordinator.poll_once())
    assert await asyncio.to_thread(started.wait, TEST_ONLY_WAIT_SECONDS)
    stopper = asyncio.create_task(rig.coordinator.stop())
    await asyncio.sleep(0)
    assert not stopper.done(), "stop() must wait for the write that is in flight"
    release.set()
    await asyncio.wait_for(asyncio.gather(poll, stopper), timeout=TEST_ONLY_WAIT_SECONDS)
    assert finished.is_set()


async def test_the_next_bars_context_sees_the_open_position_and_the_booked_daily_loss() -> None:
    rig = Rig()
    provider = SimpleNamespace(snapshot_for=lambda symbol, at: CONSTRAINTS)
    factory = make_context_factory(
        parameter_set=load_parameter_set("trend-pullback", "baseline-v5"),
        constraints=cast(Any, provider),
        risk_inputs=rig.coordinator.risk_inputs,
        account=AccountConfig(initial_equity=EQUITY, risk_rate=Decimal("0.005")),
        ttl_seconds=3600,
    )
    candle = make_outcome().closed_candle
    later = Candle(
        symbol=candle.symbol,
        interval=candle.interval,
        open_time_utc=candle.open_time_utc + HOUR,
        close_time_utc=candle.close_time_utc + HOUR,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
    )

    empty = factory(candle)
    assert empty.open_positions == () and empty.daily_loss_quote == Decimal("0")

    await rig.approve_and_confirm()
    reserved = factory(candle)
    assert [(p.symbol, p.position_side, p.open_risk) for p in reserved.open_positions] == [
        (SYMBOL, "LONG", Decimal("48"))
    ]

    await poll_at(rig, after_minutes(5))
    after = factory(later)
    assert after.open_positions == ()
    assert after.daily_loss_quote > 0
    assert after.daily_loss_quote == daily_loss_quote(rig.ledger.ledger)


async def test_a_plan_that_expires_unfilled_releases_its_exposure_once() -> None:
    quiet = [
        Bar("50300", "50310", "50290", "50300"),
    ]
    count = 250
    trade: list[Kline] = []
    mark: list[MarkKline] = []
    for index in range(count):
        opened = FIRST_MINUTE + MINUTE * index
        bar = quiet[0]
        trade.append(
            Kline(
                SYMBOL,
                "1m",
                opened,
                _close(opened),
                Decimal(bar.open),
                Decimal(bar.high),
                Decimal(bar.low),
                Decimal(bar.close),
                Decimal("1"),
                Decimal("1"),
                1,
            )
        )
        mark.append(
            MarkKline(
                SYMBOL,
                "1m",
                opened,
                _close(opened),
                Decimal(bar.open),
                Decimal(bar.high),
                Decimal(bar.low),
                Decimal(bar.close),
                1,
            )
        )
    rig = rig_with(FakePublic(trade=trade, mark=mark))
    await rig.approve_and_confirm()
    assert exposures(rig) == [(SYMBOL, "LONG", Decimal("48"))]

    # Past the plan expiry (07:00): the lifecycle cancels the plan and the expiry sweep releases
    # the reservation; both drop the same exposure and neither may fail on the other.
    await poll_at(rig, T0 + timedelta(hours=4, minutes=10, seconds=30))

    assert exposures(rig) == []
    (expired,) = rig.journal(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)
    assert payload(expired)["reason"] == "PLAN_EXPIRED_UNFILLED"
    assert rig.journal(EVENT_SHADOW_POSITION_OPENED) == []
    assert rig.journal(EVENT_SHADOW_POSITION_CLOSED) == []
    await poll_at(rig, T0 + timedelta(hours=4, minutes=11))
    assert len(rig.journal(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)) == 1


async def test_two_positions_are_booked_in_time_order_across_symbols() -> None:
    """One sweep applies the bookings of both plans sorted by time (the ledger needs that)."""
    rig_trade = scripted_trade(SYMBOL, FIRST_MINUTE) + scripted_trade(ETH, FIRST_MINUTE + MINUTE)
    rig_mark = scripted_mark(SYMBOL, FIRST_MINUTE) + scripted_mark(ETH, FIRST_MINUTE + MINUTE)
    funding = [
        FundingTick(s, T0 - timedelta(hours=2), Decimal("0.0001"), Decimal("50000"))
        for s in (SYMBOL, ETH)
    ]
    rig = rig_with(FakePublic(trade=rig_trade, mark=rig_mark, funding=funding))
    first = make_outcome(1, realized_risk="10")
    second = make_outcome(2, symbol=ETH, realized_risk="10")
    await rig.alert(first)
    await rig.alert(second)
    short_a = rig.buttons(0)[0][1].removeprefix("APR:")
    short_b = rig.buttons(1)[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{short_a}", "q-a1", at=T_APPROVE)
    await rig.tap(f"CNF:{short_a}", "q-a2", at=T_CONFIRM)
    await rig.tap(f"APR:{short_b}", "q-b1", at=T_APPROVE + MINUTE)
    await rig.tap(f"CNF:{short_b}", "q-b2", at=T_CONFIRM + MINUTE)
    assert len(rig.coordinator.open_positions()) == 2

    # A single poll covers both plans: plan 1 exits at 03:04:59.999, plan 2 fills at 03:03:59.999.
    await poll_at(rig, after_minutes(6))

    closed = rig.journal(EVENT_SHADOW_POSITION_CLOSED)
    assert len(closed) == 2
    pnl = sum(Decimal(payload(e)["trade"]["realized_pnl"]) for e in closed)
    assert rig.ledger.equity == EQUITY + pnl
    assert exposures(rig) == []


# ---- the Telegram application lifecycle (Q-L, G6) --------------------------------------------- #


class FakeUpdater:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.kwargs: dict[str, Any] = {}

    async def start_polling(self, **kwargs: Any) -> None:
        self.trace.append("updater.start_polling")
        self.kwargs = kwargs

    async def stop(self) -> None:
        self.trace.append("updater.stop")


class FakeApplication:
    """The slice of the PTB application the lifecycle touches (never a real one, never network)."""

    def __init__(self, trace: list[str], bot: FakeBot) -> None:
        self.trace = trace
        self.bot = bot
        self.updater = FakeUpdater(trace)
        self.error_handlers: list[Callable[..., Any]] = []

    async def initialize(self) -> None:
        self.trace.append("initialize")

    async def start(self) -> None:
        self.trace.append("start")

    async def stop(self) -> None:
        self.trace.append("stop")

    async def shutdown(self) -> None:
        self.trace.append("shutdown")

    def add_error_handler(self, callback: Callable[..., Any]) -> None:
        self.error_handlers.append(callback)


def application_rig(
    stores: RuntimeStores | None = None,
) -> tuple[Rig, FakeApplication, list[dict[str, Any]]]:
    trace: list[str] = []
    built: list[dict[str, Any]] = []
    bot = FakeBot()
    application = FakeApplication(trace, bot)

    def factory(kwargs: dict[str, Any]) -> FakeApplication:
        built.append(kwargs)
        return application

    rig = Rig(stores=stores, bot=bot, application_factory=factory)
    return rig, application, built


async def test_the_application_starts_in_order_logs_the_token_rule_and_stops_in_reverse() -> None:
    rig, application, built = application_rig()

    with capture_logs() as logs:
        await rig.coordinator.start()

    assert application.trace == ["initialize", "start", "updater.start_polling"]
    assert application.updater.kwargs["allowed_updates"] == ["callback_query"]
    assert callable(application.updater.kwargs["error_callback"])
    assert len(built) == 1
    assert set(built[0]) >= {
        "authorized_chat_id",
        "binding_context_resolver",
        "dispatch",
        "reply_text_fn",
        "confirm_handler",
        "approved_handler",
        "clock",
    }
    rules = [e for e in logs if e["event"] == "paper.shadow.bot_token_rule"]
    assert len(rules) == 1 and "separate-bot" in rules[0]["rule"]
    assert len(application.error_handlers) == 1

    await rig.coordinator.stop()
    assert application.trace[3:] == ["updater.stop", "stop", "shutdown"]
    await rig.coordinator.stop()  # idempotent
    assert application.trace[3:] == ["updater.stop", "stop", "shutdown"]


async def test_the_chain_registers_no_webhook() -> None:
    source = SHADOW_RUNTIME_PATH.read_text(encoding="utf-8")
    names = {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)
    }
    assert names & {"run_webhook", "set_webhook", "start_webhook"} == set()


class ThreadSpyStores(RuntimeStores):
    """Records the thread each decided approval is saved on."""

    def __init__(self) -> None:
        super().__init__()
        self.save_threads: list[int] = []

    def save_atomic(self, approval: Approval, mapping: Any) -> None:
        self.save_threads.append(threading.get_ident())
        super().save_atomic(approval, mapping)


async def test_a_press_is_dispatched_off_the_event_loop() -> None:
    stores = ThreadSpyStores()
    rig = Rig(stores=stores)
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")

    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)

    assert stores.save_threads, "the APPROVE decision was saved"
    assert threading.get_ident() not in stores.save_threads
    assert asyncio.iscoroutinefunction(rig.coordinator.callback_kwargs()["dispatch"])


# ---- Telegram failures in the running process (research F3) ------------------------------------ #

SECRET = "bot123456:SECRET-TOKEN-VALUE"


def telegram_failures() -> list[BaseException]:
    return [
        tg_error.RetryAfter(3),
        tg_error.BadRequest(f"Bad Request: {SECRET}"),
        tg_error.NetworkError(f"connection reset {SECRET}"),
        tg_error.Conflict(f"terminated by other getUpdates request {SECRET}"),
    ]


async def test_an_error_that_escaped_a_handler_is_logged_by_class_and_changes_nothing() -> None:
    rig, application, _built = application_rig()
    await rig.coordinator.start()
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    before_journal = list(rig.stores.journal)
    before_approvals = dict(rig.stores.approvals)
    (handler,) = application.error_handlers

    with capture_logs() as logs:
        for failure in telegram_failures():
            await handler(
                SimpleNamespace(callback_query=SimpleNamespace(data=f"APR:{short}")),
                SimpleNamespace(error=failure),
            )

    assert rig.stores.journal == before_journal, "an error approves, confirms or cancels nothing"
    assert rig.stores.approvals == before_approvals
    classes = [e["error_class"] for e in logs if e["event"] == "paper.shadow.telegram_error"]
    assert classes == ["RetryAfter", "BadRequest", "NetworkError", "Conflict"]
    rendered = repr(logs)
    assert SECRET not in rendered and f"APR:{short}" not in rendered
    assert rig.coordinator.telegram_error_counts == {
        "RetryAfter": 1,
        "BadRequest": 1,
        "NetworkError": 1,
        "Conflict": 1,
    }
    # The runtime and the poller keep working.
    rig.now = after_minutes(1)
    await rig.coordinator.poll_once()
    await rig.coordinator.stop()


async def test_a_conflict_logs_the_one_consumer_rule_once_per_process() -> None:
    rig, application, _built = application_rig()
    await rig.coordinator.start()
    (handler,) = application.error_handlers
    polling_error = application.updater.kwargs["error_callback"]

    with capture_logs() as logs:
        await handler(None, SimpleNamespace(error=tg_error.Conflict("a")))
        await handler(None, SimpleNamespace(error=tg_error.Conflict("b")))
        polling_error(tg_error.Conflict("c"))  # the sync polling error callback
        polling_error(tg_error.NetworkError("d"))

    conflicts = [e for e in logs if e["event"] == "paper.shadow.bot_token_conflict"]
    assert len(conflicts) == 1 and "separate-bot" in conflicts[0]["rule"]
    assert rig.coordinator.telegram_error_counts["Conflict"] == 3
    assert rig.coordinator.telegram_error_counts["NetworkError"] == 1


async def test_an_error_without_an_exception_is_ignored_safely() -> None:
    rig, application, _built = application_rig()
    await rig.coordinator.start()
    (handler,) = application.error_handlers
    await handler(None, SimpleNamespace(error=None))
    assert rig.coordinator.telegram_error_counts == {}


# ---- the poller task ------------------------------------------------------------------------- #


async def test_the_poller_polls_until_the_stop_event_is_set() -> None:
    rig = Rig()
    await rig.approve_and_confirm()
    rig.now = after_minutes(2)
    stop = asyncio.Event()
    original = rig.public.klines

    async def klines_then_stop(*args: Any, **kwargs: Any) -> Any:
        stop.set()  # the first poll sets the stop event; the loop must end after that poll
        return await original(*args, **kwargs)

    rig.public.klines = klines_then_stop  # type: ignore[method-assign]
    await asyncio.wait_for(rig.coordinator.run_poller(stop), timeout=5)

    assert rig.journal(EVENT_SHADOW_POSITION_OPENED), "the poll ran before the stop was honoured"


async def test_a_failing_poll_ends_the_poller_so_the_runtime_fails_closed() -> None:
    rig = Rig()
    await rig.approve_and_confirm()
    rig.now = after_minutes(2)
    rig.public.fail_next = ValueError("feed broke")

    with pytest.raises(ValueError, match="feed broke"):
        await asyncio.wait_for(rig.coordinator.run_poller(asyncio.Event()), timeout=5)


def test_releasing_an_exposure_twice_is_not_an_error() -> None:
    ledger = ShadowLedger(
        initial_equity=EQUITY, parameter_set_params=PARAMS, started_at_utc=LEDGER_START
    )
    ledger.restore(
        trade_plan_id="plan-1",
        symbol=SYMBOL,
        direction="LONG",
        sized_realized_risk=Decimal("10"),
        planned_quantity=Decimal("1"),
    )
    ledger.release("plan-1")
    ledger.release("plan-1")  # the lifecycle and the expiry sweep may both release one plan
    ledger.release("never-registered")
    assert ledger.ledger.exposures == ()


# ---- the application and the poller run inside the loop ---------------------------------------- #


def lifecycle_wiring(trace: list[str]) -> tuple[ShadowWiring, FakeApplication]:
    bot = FakeBot()
    application = FakeApplication(trace, bot)
    wiring = ShadowWiring(
        stores=RuntimeStores(),
        chat_id=CHAT_ID,
        authorized_user_ids=AUTHORIZED_USER_IDS,
        bot=bot,
        sleep=RecordingSleep(),
        application_factory=lambda kwargs: application,
    )
    return wiring, application


def test_the_loop_starts_the_application_and_the_poller_and_stops_them_in_reverse(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace: list[str] = []
    wiring, _application = lifecycle_wiring(trace)
    polls: list[int] = []

    async def counting_poll(self: ShadowCoordinator) -> None:
        polls.append(1)
        trace.append("poll")

    monkeypatch.setattr(ShadowCoordinator, "poll_once", counting_poll)
    live.public = RuntimePublic()

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4 and len(polls) >= 1)

    code = live.start(script, pipeline=SpyPipeline([]), risk_inputs=None, shadow=wiring)

    assert code == 0
    assert trace[:3] == ["initialize", "start", "updater.start_polling"]
    assert "poll" in trace
    assert trace[-3:] == ["updater.stop", "stop", "shutdown"]
    assert all(h._unsubscribed == 1 for h in live.client.handles), "the feed is closed as well"


def test_a_failing_poller_fails_the_loop_closed_and_still_stops_the_application(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace: list[str] = []
    wiring, _application = lifecycle_wiring(trace)

    async def failing_poll(self: ShadowCoordinator) -> None:
        raise ValueError("feed broke")

    monkeypatch.setattr(ShadowCoordinator, "poll_once", failing_poll)
    live.public = RuntimePublic()

    async def script(h: Live) -> None:
        await asyncio.Event().wait()  # never stops by itself: the poller failure must

    code = live.start(script, pipeline=SpyPipeline([]), risk_inputs=None, shadow=wiring)

    assert code == 7, "restartable fail-closed exit"
    assert trace[-3:] == ["updater.stop", "stop", "shutdown"]
    # The pin exits without a run (16-DEC-PIN-COMMAND), so no STOP at all: a crash marker.
    assert live.records(RuntimeEventType.RUNTIME_STOP) == [], "no RUNTIME_STOP: a crash marker"


# --------------------------------------------------------------------------- #
# Task 3: restart behaviour of the SHADOW chain and per-signal attribution (D-15, P13).
# --------------------------------------------------------------------------- #

from src.domain.enums import ApprovalAction  # noqa: E402
from src.paper.attribution import AttributionKind  # noqa: E402
from src.paper.shadow import EVENT_PENDING_INVALIDATED, approval_id_for  # noqa: E402
from src.paper.shadow_confirm import EVENT_SHADOW_CONFIRM_REJECTED  # noqa: E402
from src.paper.shadow_runtime import EVENT_SHADOW_PLAN_CONTEXT, ShadowRuntimeError  # noqa: E402


def restart_rig(rig: Rig, *, now: datetime) -> tuple[Rig, FakeApplication, list[int]]:
    """A restarted process whose application records how many approvals were already swept."""
    trace: list[str] = []
    application = FakeApplication(trace, rig.bot)
    swept_before_polling: list[int] = []
    original = application.initialize

    async def initialize() -> None:
        swept_before_polling.append(len(rig.stores.journal_of_type(EVENT_PENDING_INVALIDATED)))
        await original()

    application.initialize = initialize  # type: ignore[method-assign]
    other = Rig(
        stores=rig.stores,
        public=rig.public,
        bot=rig.bot,
        now=now,
        application_factory=lambda kwargs: application,
    )
    return other, application, swept_before_polling


async def test_a_restart_expires_pending_approvals_and_confirms_before_polling_begins() -> None:
    rig = Rig()
    first = make_outcome(1)
    second = make_outcome(2)
    await rig.alert(first)
    await rig.alert(second)
    approved_short = rig.buttons(0)[0][1].removeprefix("APR:")
    pending_short = rig.buttons(1)[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{approved_short}", "q-apr-1", at=T_APPROVE)  # a card with a live confirm

    restarted, _application, swept_before_polling = restart_rig(
        rig, now=T_APPROVE + timedelta(seconds=20)
    )
    await restarted.coordinator.start()

    assert swept_before_polling == [3], "the sweep ran before the application started polling"
    invalidated = rig.journal(EVENT_PENDING_INVALIDATED)
    assert {payload(e)["reason_code"] for e in invalidated} == {"RUNTIME_RESTART"}
    assert second.trade_plan is not None
    pending_ids = {approval_id_for(second.trade_plan, a) for a in _both_actions()}
    expired_ids = {
        a.approval_id for a in rig.stores.approvals.values() if a.status.value == "EXPIRED"
    }
    # EXPIRED rows are outside the one-decided-per-plan index (G4-042, 0014): both rows of the
    # undecided plan are EXPIRED and neither keeps a token nobody holds.
    assert pending_ids == expired_ids
    (confirm_expired,) = rig.journal(EVENT_SHADOW_CONFIRM_EXPIRED)
    assert payload(confirm_expired)["reason"] == "RUNTIME_RESTART"
    assert rig.journal(EVENT_SHADOW_CONFIRMED) == []

    # A callback for a pre-restart approval or confirm is rejected, and the reply is labelled.
    before = len(rig.bot.sent)
    await restarted.tap(f"APR:{pending_short}", "q-late-apr", at=T_APPROVE + timedelta(seconds=25))
    await restarted.tap(f"CNF:{approved_short}", "q-late-cnf", at=T_APPROVE + timedelta(seconds=26))
    assert rig.journal(EVENT_SHADOW_CONFIRMED) == []
    assert rig.journal(EVENT_SHADOW_CONFIRM_REJECTED), "the late confirm press is journaled"
    assert restarted.coordinator.open_positions() == ()
    assert len(rig.bot.sent) > before
    for message in rig.bot.sent:
        assert_shadow_text(message.text)


def _both_actions() -> tuple[ApprovalAction, ApprovalAction]:
    return ApprovalAction.APPROVE, ApprovalAction.SKIP_USER


async def test_the_restart_sweep_is_idempotent() -> None:
    rig = Rig()
    await rig.alert()
    restarted, _application, _ = restart_rig(rig, now=T_APPROVE)
    await restarted.coordinator.start()
    count = len(rig.stores.journal)
    again, _application2, _ = restart_rig(rig, now=T_APPROVE + timedelta(seconds=5))
    await again.coordinator.start()
    assert len(rig.stores.journal) == count


async def _uninterrupted(polls: Sequence[datetime]) -> Rig:
    rig = Rig()
    await rig.approve_and_confirm()
    for instant in polls:
        await poll_at(rig, instant)
    return rig


@pytest.mark.parametrize(
    ("restart_after", "label"),
    [(0, "reserved, not filled yet"), (3, "filled and open"), (5, "already closed")],
)
async def test_open_positions_are_rebuilt_and_the_ledger_equals_an_uninterrupted_run(
    restart_after: int, label: str
) -> None:
    reference = await _uninterrupted([after_minutes(5), after_minutes(6)])

    rig = Rig()
    await rig.approve_and_confirm()
    if restart_after:
        await poll_at(rig, after_minutes(restart_after))
    restarted, _application, _ = restart_rig(rig, now=after_minutes(restart_after) + MINUTE)
    await restarted.coordinator.start()
    # The rebuilt process continues the position over the minutes it has not seen yet.
    await poll_at(restarted, after_minutes(5))
    await poll_at(restarted, after_minutes(6))

    assert restarted.ledger.ledger == reference.ledger.ledger, label
    assert len(rig.journal(EVENT_SHADOW_POSITION_OPENED)) == 1, label
    assert len(rig.journal(EVENT_SHADOW_POSITION_CLOSED)) == 1, label
    (view,) = restarted.coordinator.open_positions()
    assert view.closed and view.filled, label


async def test_a_confirmed_plan_whose_context_was_never_journaled_cannot_be_rebuilt() -> None:
    rig = Rig()
    await rig.approve_and_confirm()
    rig.stores.journal = [
        e for e in rig.stores.journal if e.event_type != EVENT_SHADOW_PLAN_CONTEXT
    ]
    restarted, _application, _ = restart_rig(rig, now=after_minutes(1))

    with pytest.raises(ShadowRuntimeError, match="context"):
        await restarted.coordinator.start()


async def test_the_plan_context_is_journaled_with_the_alert() -> None:
    rig = Rig()
    await rig.alert()
    (context,) = rig.journal(EVENT_SHADOW_PLAN_CONTEXT)
    body = payload(context)
    assert body["regime"] == "TREND"
    assert body["constraints"]["quantity_step_size"] == "0.001"
    assert body["closed_candle"]["close_time_utc"] == SIGNAL_CLOSE.isoformat()
    assert body["sized"] == {"quantity": "0.08", "realized_risk": "48"}


# ---- per-signal attribution (plan 16-35 from the journaled rows) ------------------------ #


def pair(outcome: BarOutcome) -> tuple[Signal, TradePlan]:
    assert outcome.signal is not None and outcome.trade_plan is not None
    return outcome.signal, outcome.trade_plan


def kinds(records: Sequence[Any]) -> list[tuple[str, str]]:
    return [(r.attribution.value, r.reason_code) for r in records]


async def test_every_signal_of_a_session_gets_its_attribution_from_the_journal() -> None:
    rig = Rig()
    outcomes = {n: make_outcome(n) for n in range(1, 8)}
    for outcome in outcomes.values():
        await rig.alert(outcome)
    shorts = {n: rig.buttons(n - 1)[0][1].removeprefix("APR:") for n in outcomes}
    skips = {n: rig.buttons(n - 1)[1][1] for n in outcomes}

    await rig.tap(skips[2], "q-skp-2", at=T0 + timedelta(seconds=20))
    for n in (1, 3, 4):
        await rig.tap(f"APR:{shorts[n]}", f"q-apr-{n}", at=T_APPROVE)
    await rig.tap(f"CNF:{shorts[1]}", "q-cnf-1", at=T_CONFIRM)
    await rig.tap(f"CXL:{shorts[3]}", "q-cxl-3", at=T_CONFIRM)
    await rig.tap(f"CNF:{shorts[4]}", "q-cnf-4", at=T_APPROVE + timedelta(seconds=61))
    await rig.coordinator.expire_due()

    early = rig.coordinator.records_for(*pair(outcomes[7]))
    assert kinds(early) == [("system", "")], (
        "an untouched plan that is still valid: engine row only"
    )

    await poll_at(rig, after_minutes(5))
    expiry = T0 + timedelta(hours=4, seconds=1)
    await rig.tap(f"APR:{shorts[6]}", "q-apr-6", at=expiry)  # approval after the plan expiry
    records = rig.coordinator.paper_records(expiry)

    ids = {n: pair(outcomes[n])[0].signal_id for n in outcomes}
    assert list(records) == [ids[n] for n in (1, 2, 3, 4, 5, 6, 7)]
    assert kinds(records[ids[1]]) == [("system", ""), ("user-executed-sim", "")]
    assert kinds(records[ids[2]]) == [("system", ""), ("opportunity", "SKIP_USER")]
    assert kinds(records[ids[3]]) == [
        ("system", ""),
        ("opportunity", "SHADOW_CONFIRM_CANCELLED"),
    ]
    assert kinds(records[ids[4]]) == [
        ("system", ""),
        ("opportunity", "SHADOW_CONFIRM_EXPIRED"),
    ]
    assert kinds(records[ids[5]]) == [("system", ""), ("opportunity", "EXPIRED")]
    assert kinds(records[ids[6]]) == [
        ("system", ""),
        ("opportunity", "APPROVAL_EXPIRED"),
    ]
    assert kinds(records[ids[7]]) == [("system", ""), ("opportunity", "EXPIRED")]

    sim = records[ids[1]][1]
    assert sim.attribution is AttributionKind.USER_EXECUTED_SIM and sim.mode == "SHADOW"
    assert sim.approval_requested_at_utc == T_ALERT
    assert sim.approval_acted_at_utc == T_APPROVE
    assert sim.approval_acted_at_utc - sim.approval_requested_at_utc == timedelta(seconds=25)
    assert sim.confirm_requested_at_utc == T_APPROVE
    assert sim.confirmed_at_utc == T_CONFIRM
    assert sim.order_submitted_at_utc == T_CONFIRM
    assert sim.fill_time_utc == FIRST_MINUTE + MINUTE * 2 - timedelta(milliseconds=1)
    assert all(
        r.epoch_id == EPOCH_ID and r.experiment_id == "exp-test"
        for rs in records.values()
        for r in rs
    )


async def test_a_confirmed_plan_that_has_not_filled_yet_has_no_record_until_it_ends() -> None:
    rig = Rig()
    outcome = make_outcome()
    await rig.approve_and_confirm(outcome=outcome)
    assert rig.coordinator.records_for(*pair(outcome)) == []


async def test_a_restart_expired_plan_is_an_opportunity_with_the_restart_reason() -> None:
    rig = Rig()
    outcome = make_outcome()
    await rig.alert(outcome)
    restarted, _application, _ = restart_rig(rig, now=T_APPROVE)
    await restarted.coordinator.start()

    records = restarted.coordinator.records_for(*pair(outcome))

    assert kinds(records) == [("system", ""), ("opportunity", "RUNTIME_RESTART")]


# ---- the production wiring from the environment ------------------------------------------------ #


def test_the_production_shadow_wiring_needs_the_telegram_chat_and_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.paper import runtime
    from src.paper.runtime_config import ConfigNotRatified

    token = "123456:test-token-value"
    assert runtime._shadow_from_env({}) is None
    assert runtime._shadow_from_env({"TELEGRAM_BOT_TOKEN": token}) is None
    with pytest.raises(ConfigNotRatified, match="integer"):
        runtime._shadow_from_env(
            {
                "TELEGRAM_BOT_TOKEN": token,
                "TELEGRAM_AUTHORIZED_CHAT_ID": "not-a-number",
                "DATABASE_URL_SYNC": "postgresql://u:p@h/db",
            }
        )
    with pytest.raises(ConfigNotRatified, match="DATABASE_URL"):
        runtime._shadow_from_env(
            {
                "TELEGRAM_BOT_TOKEN": token,
                "TELEGRAM_AUTHORIZED_CHAT_ID": "4242",
                "TELEGRAM_AUTHORIZED_USER_IDS": "777001",
            }
        )

    seen: list[str] = []
    stores = RuntimeStores()

    def fake_stores(url: str) -> RuntimeStores:
        seen.append(url)
        return stores

    monkeypatch.setattr(runtime, "_pg_shadow_stores", fake_stores)
    wiring = runtime._shadow_from_env(
        {
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_AUTHORIZED_CHAT_ID": "4242",
            "TELEGRAM_AUTHORIZED_USER_IDS": "777001, 777002",
            "DATABASE_URL_SYNC": "postgresql://u:p@h/db",
        }
    )
    assert wiring is not None
    assert wiring.chat_id == 4242 and wiring.stores is stores
    assert wiring.authorized_user_ids == frozenset({777001, 777002})
    assert seen == ["postgresql://u:p@h/db"]
    assert wiring.application_factory is not None

    captured: dict[str, Any] = {}

    def fake_build_application(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "application"

    monkeypatch.setattr("src.adapters.telegram_callbacks.build_application", fake_build_application)
    assert wiring.application_factory({"authorized_chat_id": 4242, "clock": None}) == "application"
    assert captured == {"token": token, "authorized_chat_id": 4242, "clock": None}


def test_a_configured_telegram_without_a_usable_user_allow_list_refuses_the_start() -> None:
    """Phase 23 (D-02): token and chat set, user ids missing or unparsable -> not ratified."""
    from src.paper import runtime
    from src.paper.runtime_config import ConfigNotRatified

    base = {
        "TELEGRAM_BOT_TOKEN": "123456:test-token-value",
        "TELEGRAM_AUTHORIZED_CHAT_ID": "4242",
        "DATABASE_URL_SYNC": "postgresql://u:p@h/db",
    }
    for missing in (
        {},
        {"TELEGRAM_AUTHORIZED_USER_IDS": ""},
        {"TELEGRAM_AUTHORIZED_USER_IDS": " "},
    ):
        with pytest.raises(ConfigNotRatified) as missing_info:
            runtime._shadow_from_env({**base, **missing})
        assert missing_info.value.problems == ["TELEGRAM_AUTHORIZED_USER_IDS (missing)"]
    for bad in ("abc", "777001,", "0", "-5", "777001,777001"):
        with pytest.raises(ConfigNotRatified) as bad_info:
            runtime._shadow_from_env({**base, "TELEGRAM_AUTHORIZED_USER_IDS": bad})
        assert bad_info.value.problems == [
            "TELEGRAM_AUTHORIZED_USER_IDS (must be comma-separated positive integers)"
        ]
        assert bad not in str(bad_info.value), "no input text in the message"
    # With Telegram unconfigured the start stays SKIPPED, whatever the allow-list says.
    assert runtime._shadow_from_env({"TELEGRAM_AUTHORIZED_USER_IDS": "abc"}) is None


def test_the_coordinator_requires_a_non_empty_integer_allow_list() -> None:
    parameter = inspect.signature(ShadowCoordinator).parameters["authorized_user_ids"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    for bad in (frozenset(), frozenset({True}), {USER_ID}):
        with pytest.raises(ValueError):
            Rig(authorized_user_ids=bad)  # type: ignore[arg-type]
    assert Rig().coordinator.callback_kwargs()["authorized_user_ids"] == AUTHORIZED_USER_IDS


async def test_a_press_by_a_user_outside_the_allow_list_changes_no_approval() -> None:
    rig = Rig()
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")

    result = await rig.tap(f"APR:{short}", "q-stranger", at=T_APPROVE, user=STRANGER_USER_ID)

    assert result.ok is False and result.reason_code == "USER_NOT_AUTHORIZED"
    assert all(a.status == ApprovalResult.PENDING for a in rig.stores.approvals.values())


def test_the_postgresql_stores_implement_every_member_of_the_chain_port() -> None:
    import typing

    from src.paper.shadow_runtime import ShadowRuntimeStores
    from src.persistence.shadow_stores import PgShadowStores

    members = typing.get_protocol_members(ShadowRuntimeStores)
    assert {"list_pending_approvals", "list_approved_approvals", "journal_for_correlation"} <= (
        members
    )
    assert {"get_signal", "get_trade_plan", "get_approval", "record_journal"} <= members
    missing = sorted(name for name in members if not callable(getattr(PgShadowStores, name, None)))
    assert missing == []


# --------------------------------------------------------------------------- #
# Plan 16-57 Task 3 (B1-WR-03, L-11): a risk-passed bar whose SHADOW rows never persisted.
# --------------------------------------------------------------------------- #

from src.paper.runtime_state import RuntimeRecord  # noqa: E402
from src.paper.shadow import EVENT_SHADOW_ALERT_PENDING  # noqa: E402

from tests.paper_ws_fakes import FakeSdkWsClient  # noqa: E402

SIGNAL_LOST = "SHADOW_SIGNAL_LOST"


class FailingAlertStores(RuntimeStores):
    """The SHADOW store loses its database right before the alert's first write."""

    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    def insert_signal(self, signal: Signal) -> None:
        if self.fail:
            raise ConnectionError("the SHADOW database went away before the alert persisted")
        super().insert_signal(signal)


class HeartbeatPipeline:
    """Records the risk-passed heartbeat like `BarPipeline`, then hands the outcome on."""

    def __init__(self, state: Any, epoch_id: str, outcome: BarOutcome) -> None:
        self.state = state
        self.epoch_id = epoch_id
        self.outcome = outcome
        self.done = False

    def handle(self, bars: Any, *, now_utc: datetime) -> PipelineResult:
        batch = list(bars)
        if not batch or self.done:
            return PipelineResult()
        self.done = True
        bar = batch[0]
        assert self.outcome.signal is not None and self.outcome.trade_plan is not None
        plan_hash = self.outcome.trade_plan.plan_hash
        record = RuntimeRecord.bar_processed(
            epoch_id=self.epoch_id,
            symbol=bar.symbol,
            interval=bar.interval,
            close_time_utc=bar.close_time_utc,
            payload={
                "source": "LIVE_WS",
                "tick_time_utc": now_utc,
                "stage": "risk_passed",
                "reason_code": "OK",
                "plan_hash": plan_hash,
                "surface": {
                    "stage": "risk_passed",
                    "signal_id": self.outcome.signal.signal_id,
                    "plan_hash": plan_hash,
                },
            },
        )
        self.state.record(record)  # the heartbeat is committed before the SHADOW write
        return PipelineResult(evaluated=(self.outcome,), recorded=(record,))


def _fresh_client(rig: Live) -> None:
    rig.client = FakeSdkWsClient()
    rig.clients = [rig.client]


def _crash_before_the_shadow_write(rig: Live, stores: FailingAlertStores, bot: FakeBot) -> None:
    """Run 1: the heartbeat is committed, then the alert's store write fails (exit 7)."""
    rig.public = RuntimePublic()
    pipeline = HeartbeatPipeline(rig.state, rig.epoch.epoch_id, make_outcome(1))

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: False, timeout=5.0)  # the loop fails closed first

    code = rig.start(
        script,
        pipeline=pipeline,
        risk_inputs=None,
        shadow=ShadowWiring(
            stores=stores,
            chat_id=CHAT_ID,
            authorized_user_ids=AUTHORIZED_USER_IDS,
            bot=bot,
            sleep=RecordingSleep(),
        ),
    )
    assert code == 7
    [heartbeat] = rig.records(RuntimeEventType.PAPER_BAR_PROCESSED)
    assert heartbeat.payload["stage"] == "risk_passed"
    assert stores.signals == {} and stores.plans == {}


def _restart(rig: Live, stores: FailingAlertStores, bot: FakeBot) -> int:
    _fresh_client(rig)
    stores.fail = False

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)

    return rig.start(
        script,
        pipeline=SpyPipeline([]),
        risk_inputs=None,
        shadow=ShadowWiring(
            stores=stores,
            chat_id=CHAT_ID,
            authorized_user_ids=AUTHORIZED_USER_IDS,
            bot=bot,
            sleep=RecordingSleep(),
        ),
    )


def test_a_signal_lost_before_its_shadow_write_is_journaled_once_at_the_next_start(
    live: Live,
) -> None:
    """The B1-WR-03 re-check and Test 3: detection at restart, explicit journal row, no alert."""
    stores = FailingAlertStores()
    bot = FakeBot()
    _crash_before_the_shadow_write(live, stores, bot)
    plan_hash = "1" * 64

    assert _restart(live, stores, bot) == 0

    [lost] = stores.journal_of_type(SIGNAL_LOST)
    body = payload(lost)
    assert body["plan_hash"] == plan_hash
    assert body["epoch_id"] == live.epoch.epoch_id
    assert body["signal_id"] == make_outcome(1).signal.signal_id  # type: ignore[union-attr]
    assert body["mode"] == "SHADOW"
    assert lost.signal_id is None and lost.trade_plan_id is None, "no parent row exists"
    assert "occurred" not in json.dumps(body) and "detected" not in json.dumps(body)
    # L-11: no late alert, no approval, no plan row.
    assert bot.sent == []
    assert stores.approvals == {} and stores.plans == {}
    assert stores.journal_of_type(EVENT_SHADOW_ALERT_PENDING) == []

    # A second start writes nothing new (replay no-op).
    before = len(stores.journal)
    assert _restart(live, stores, bot) == 0
    assert len(stores.journal) == before
    assert len(stores.journal_of_type(SIGNAL_LOST)) == 1


async def test_a_persisted_alert_is_not_lost_and_the_lost_view_counts_apart() -> None:
    from src.paper.shadow_runtime import EVENT_SHADOW_SIGNAL_LOST, RiskPassedBar

    rig = Rig()
    alerted, lost = make_outcome(1), make_outcome(2)
    await rig.alert(alerted)

    def bar(outcome: BarOutcome) -> RiskPassedBar:
        assert outcome.signal is not None and outcome.trade_plan is not None
        return RiskPassedBar(
            symbol=outcome.closed_candle.symbol,
            interval=outcome.closed_candle.interval,
            bar_close_utc=outcome.closed_candle.close_time_utc,
            signal_id=outcome.signal.signal_id,
            plan_hash=outcome.trade_plan.plan_hash,
        )

    restarted = rig.restart(now=T_APPROVE)
    await restarted.coordinator.start(risk_passed=(bar(alerted), bar(lost)))

    assert EVENT_SHADOW_SIGNAL_LOST == SIGNAL_LOST
    [event] = rig.journal(SIGNAL_LOST)
    assert payload(event)["plan_hash"] == "2" * 64
    assert restarted.coordinator.lost_signals() == ("2" * 64,)
    # Counted apart from strategy signals: the lost plan is never a paper record or an alert.
    assert len(rig.bot.sent) == 1
    assert all(
        signal_id != lost.signal.signal_id  # type: ignore[union-attr]
        for signal_id in restarted.coordinator.paper_records()
    )


# --------------------------------------------------------------------------- #
# Plan 16-58: an unsizable confirmed plan never stops the chain (B2-CR-03) and a reservation is
# released by the data horizon, not the wall clock (B2-CR-02).
# --------------------------------------------------------------------------- #

from dataclasses import replace  # noqa: E402

from src.paper.shadow_ledger import EVENT_SHADOW_RESERVATION_REFUSED  # noqa: E402

PLAN_EXPIRY = T0 + timedelta(hours=4)
# TP1 is half of the planned 0.08, so a 0.05 minimum quantity cannot size the TP1 leg.
UNSIZABLE = replace(CONSTRAINTS, min_quantity=Decimal("0.05"))
ETH_CONSTRAINTS = replace(CONSTRAINTS, symbol=ETH)


def _refusal_code() -> str:
    """The open check's reject code of the unsizable constraints (read from the driver itself)."""
    from src.paper.shadow_fill import ShadowFillDriver, eligibility_start_for

    outcome = make_outcome()
    driver = ShadowFillDriver(
        cost_model=build_cost_model(dict(DEFAULT_COST_MODEL)),
        constraint_snapshot=UNSIZABLE,
        strategy_version="v1.0.0",
        parameter_set_hash="b" * 64,
        constraints_extrapolated=False,
    )
    eligibility = eligibility_start_for(
        signal_close_utc=SIGNAL_CLOSE,
        plan_expiry_utc=PLAN_EXPIRY,
        confirm_outcome="CONFIRMED",
        confirmed_at_utc=T_CONFIRM,
    )
    opened = driver.open_confirmed(outcome, eligibility)
    assert not opened.opened
    return opened.reason_code


def _by_symbol(table: dict[str, ConstraintSnapshot]) -> Callable[..., ConstraintSnapshot]:
    return lambda symbol, at: table[symbol]


async def test_a_confirm_the_fill_driver_cannot_open_is_refused_before_any_reservation() -> None:
    code = _refusal_code()
    rig = Rig(constraints_for=lambda symbol, at: UNSIZABLE)
    await rig.alert()
    short = rig.buttons()[0][1].removeprefix("APR:")
    await rig.tap(f"APR:{short}", "q-apr-unsizable", at=T_APPROVE)
    await rig.tap(f"CNF:{short}", "q-cnf-unsizable", at=T_CONFIRM)

    assert rig.journal(EVENT_SHADOW_CONFIRMED) == [], "a refused CONFIRM is never journaled as one"
    (refused,) = rig.journal(EVENT_SHADOW_CONFIRM_EXPIRED)
    body = payload(refused)
    assert body["reason"] == code and body["rejected_at_confirm"] is True
    assert exposures(rig) == [] and rig.coordinator.open_positions() == ()
    assert code in rig.bot.sent[-1].text, "the operator's reply names the refusal"
    await rig.coordinator.poll_once()  # nothing to drive, nothing to raise


async def _two_confirms_one_unsizable(*, drive: bool, stores: RuntimeStores | None = None) -> Rig:
    """BTC (unsizable) and ETH (sizable) confirmed as a build WITHOUT the open check would have.

    The open check at CONFIRM and, when `drive` is False, the driver hook are switched off on the
    book, which reproduces a reservation written before this fix: it sits in the journal and
    cannot open.
    """
    trade = scripted_trade(SYMBOL) + scripted_trade(ETH)
    mark = scripted_mark(SYMBOL) + scripted_mark(ETH)
    funding = [
        FundingTick(s, T0 - timedelta(hours=2), Decimal("0.0001"), Decimal("50000"))
        for s in (SYMBOL, ETH)
    ]
    rig = Rig(
        stores=stores,
        public=FakePublic(trade=trade, mark=mark, funding=funding),
        constraints_for=_by_symbol({SYMBOL: UNSIZABLE, ETH: ETH_CONSTRAINTS}),
    )
    book = rig.coordinator.confirm_book
    book._recheck = None  # type: ignore[attr-defined]
    if not drive:
        book._on_confirmed = None  # type: ignore[attr-defined]
    await rig.alert(make_outcome(1, realized_risk="10"))
    await rig.alert(make_outcome(2, symbol=ETH, realized_risk="10"))
    shorts = [rig.buttons(i)[0][1].removeprefix("APR:") for i in (0, 1)]
    for index, short in enumerate(shorts):
        await rig.tap(f"APR:{short}", f"q-apr-{index}", at=T_APPROVE + MINUTE * index)
        await rig.tap(f"CNF:{short}", f"q-cnf-{index}", at=T_CONFIRM + MINUTE * index)
    if not drive:
        assert len(exposures(rig)) == 2, "both plans hold a reservation"
    return rig


async def test_a_reservation_that_cannot_open_is_refused_by_the_press_and_the_poll() -> None:
    code = _refusal_code()
    rig = await _two_confirms_one_unsizable(drive=True)

    # The press already tried to give the plan a driver and refused it without raising.
    (refused,) = rig.journal(EVENT_SHADOW_RESERVATION_REFUSED)
    assert payload(refused)["reason"] == code
    assert payload(refused)["plan_hash"] == "1" * 64
    assert [p.symbol for p in rig.coordinator.open_positions()] == [ETH]
    assert [s for s, _d, _r in exposures(rig)] == [ETH], "BTC was released"

    await poll_at(rig, after_minutes(3))  # the poller keeps running for the other plan
    assert len(rig.journal(EVENT_SHADOW_RESERVATION_REFUSED)) == 1


async def test_a_poll_step_refuses_a_stored_reservation_that_cannot_open_and_keeps_the_rest() -> (
    None
):
    code = _refusal_code()
    rig = await _two_confirms_one_unsizable(drive=False)
    assert rig.coordinator.open_positions() == ()

    await poll_at(rig, after_minutes(3))  # must not raise

    (refused,) = rig.journal(EVENT_SHADOW_RESERVATION_REFUSED)
    assert payload(refused)["reason"] == code
    assert [p.symbol for p in rig.coordinator.open_positions()] == [ETH]
    assert SYMBOL not in [s for s, _d, _r in exposures(rig)]


async def test_a_restore_releases_a_reservation_that_cannot_open_and_writes_nothing_twice() -> None:
    code = _refusal_code()
    rig = await _two_confirms_one_unsizable(drive=False)

    first = rig.restart(now=T_CONFIRM + 5 * MINUTE)
    await first.coordinator.restore()  # must not raise
    (refused,) = first.journal(EVENT_SHADOW_RESERVATION_REFUSED)
    assert payload(refused)["reason"] == code
    assert refused.occurred_at_utc == T_CONFIRM, "no restart wall clock in the event"
    assert [p.symbol for p in first.coordinator.open_positions()] == [ETH]
    assert [s for s, _d, _r in exposures(first)] == [ETH]

    second = first.restart(now=T_CONFIRM + 6 * MINUTE)
    await second.coordinator.restore()
    await poll_at(second, after_minutes(3))
    assert len(second.journal(EVENT_SHADOW_RESERVATION_REFUSED)) == 1
    assert [p.symbol for p in second.coordinator.open_positions()] == [ETH]


def _minutes_to_expiry(*, fill: bool) -> tuple[list[Kline], list[MarkKline]]:
    """Quiet minutes from 03:01, then (when `fill`) a touch at 06:58 and a fill at 06:59.

    The fill minute closes at 06:59:59.999, inside the plan (expiry 07:00); the script continues
    with a flat minute and a drop through the stop at 07:01.
    """
    quiet = Bar("50300", "50310", "50290", "50300")
    tail = list(SCRIPT) if fill else [quiet] * len(SCRIPT)
    quiet_minutes = int((PLAN_EXPIRY - FIRST_MINUTE) / MINUTE) - 2  # up to the 06:57 minute
    bars = [quiet] * quiet_minutes + tail
    trade: list[Kline] = []
    mark: list[MarkKline] = []
    for index, bar in enumerate(bars):
        opened = FIRST_MINUTE + MINUTE * index
        trade.append(
            Kline(
                SYMBOL,
                "1m",
                opened,
                _close(opened),
                Decimal(bar.open),
                Decimal(bar.high),
                Decimal(bar.low),
                Decimal(bar.close),
                Decimal("1"),
                Decimal("1"),
                1,
            )
        )
        mark.append(
            MarkKline(
                SYMBOL,
                "1m",
                opened,
                _close(opened),
                Decimal(bar.open),
                Decimal(bar.high),
                Decimal(bar.low),
                Decimal(bar.close),
                1,
            )
        )
    return trade, mark


async def test_a_fill_in_the_last_minute_before_expiry_is_not_an_unfilled_expiry() -> None:
    trade, mark = _minutes_to_expiry(fill=True)
    rig = Rig(public=FakePublic(trade=trade, mark=mark))
    await rig.approve_and_confirm()
    await poll_at(rig, PLAN_EXPIRY - timedelta(minutes=20))  # the quiet minutes
    assert exposures(rig) == [(SYMBOL, "LONG", Decimal("48"))]

    # The wall clock is past the expiry but the data horizon (now - 5 s) is not: the fill minute
    # (06:59, closing 06:59:59.999) is not settled yet.
    await poll_at(rig, PLAN_EXPIRY + timedelta(seconds=2))
    assert rig.journal(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED) == [], "no false expiry"
    assert exposures(rig) == [(SYMBOL, "LONG", Decimal("48"))], "still reserved"

    await poll_at(rig, PLAN_EXPIRY + timedelta(seconds=30))
    (opened,) = rig.journal(EVENT_SHADOW_POSITION_OPENED)
    assert payload(opened)["opened_at_utc"] == (PLAN_EXPIRY - timedelta(milliseconds=1)).isoformat()
    assert exposures(rig) == [(SYMBOL, "LONG", Decimal("48"))], "the exposure is registered"

    await poll_at(rig, PLAN_EXPIRY + timedelta(minutes=2, seconds=30))  # the stop, no ValueError
    (closed,) = rig.journal(EVENT_SHADOW_POSITION_CLOSED)
    assert payload(closed)["exit_kind"] == EXIT_SL
    assert exposures(rig) == []
    assert rig.journal(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED) == []


async def test_a_plan_without_a_fill_is_released_once_the_horizon_passed_its_expiry() -> None:
    trade, mark = _minutes_to_expiry(fill=False)
    rig = Rig(public=FakePublic(trade=trade, mark=mark))
    await rig.approve_and_confirm()
    await poll_at(rig, PLAN_EXPIRY - timedelta(minutes=20))

    await poll_at(rig, PLAN_EXPIRY + timedelta(seconds=2))  # horizon 06:59:57 < expiry
    assert rig.journal(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED) == []
    assert len(exposures(rig)) == 1

    await poll_at(rig, PLAN_EXPIRY + timedelta(seconds=30))  # horizon 07:00:25 >= expiry
    (expired,) = rig.journal(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)
    assert payload(expired)["reason"] == "PLAN_EXPIRED_UNFILLED"
    assert exposures(rig) == []
    await poll_at(rig, PLAN_EXPIRY + timedelta(minutes=2))
    assert len(rig.journal(EVENT_SHADOW_PLAN_EXPIRED_UNFILLED)) == 1
