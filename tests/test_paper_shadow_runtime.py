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
from src.domain.enums import DailyState
from src.domain.registry import load_parameter_set
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
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
    CHAT_ID,
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
) -> BarOutcome:
    """A bar outcome: the SHADOW fixture signal and plan of `n`, sized 0.08 for a risk of 48."""
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
        quantity=Decimal("0.08"),
        quantity_before_rounding=Decimal("0.08"),
        quantity_after_rounding=Decimal("0.08"),
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
    ) -> None:
        self.now = now
        self.stores = stores if stores is not None else RuntimeStores()
        self.public = public if public is not None else FakePublic()
        self.bot = bot if bot is not None else FakeBot()
        self.sleep = RecordingSleep()
        self.ledger = ShadowLedger(
            initial_equity=EQUITY, parameter_set_params=PARAMS, started_at_utc=LEDGER_START
        )
        self.confirm_ttl_seconds = confirm_ttl_seconds
        self.coordinator = self._build()

    def _build(self) -> ShadowCoordinator:
        return ShadowCoordinator(
            mode=Mode.SHADOW,
            stores=self.stores,
            bot=self.bot,
            chat_id=CHAT_ID,
            clock=lambda: self.now,
            ledger=self.ledger,
            public=self.public,
            fill=FillContext(
                cost_model=build_cost_model(dict(DEFAULT_COST_MODEL)),
                strategy_version="v1.0.0",
                parameter_set_hash="b" * 64,
                constraints_for=lambda symbol, at: CONSTRAINTS,
            ),
            minute_poll_interval_seconds=POLL_SECONDS,
            minute_close_lag_seconds=LAG_SECONDS,
            experiment_id="exp-test",
            epoch_id=EPOCH_ID,
            confirm_ttl_seconds=self.confirm_ttl_seconds,
            sleep=self.sleep,
        )

    def restart(self, *, now: datetime | None = None) -> Rig:
        other = Rig(
            stores=self.stores,
            public=self.public,
            bot=self.bot,
            now=self.now if now is None else now,
            confirm_ttl_seconds=self.confirm_ttl_seconds,
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
    assert [label for label, _ in rig.buttons()] == ["APPROVE", "SKIP"]
    short = rig.buttons()[0][1].removeprefix("APR:")
    assert rig.buttons()[1][1] == f"SKP:{short}"

    # APPROVE turns the alert into the confirmation card and confirms nothing (D041).
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    assert len(rig.bot.edited) == 1
    card = rig.bot.edited[0]
    assert "Confirm this SHADOW plan? No real order will be placed." in card.text
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
    rig.coordinator.expire_due()


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
        shadow=ShadowWiring(stores=stores, chat_id=CHAT_ID, bot=bot, sleep=RecordingSleep()),
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
        shadow=ShadowWiring(stores=RuntimeStores(), chat_id=CHAT_ID, bot=FakeBot()),
    )
    assert code == 0
    assert live.records(RuntimeEventType.RUNTIME_START)
