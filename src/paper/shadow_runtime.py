"""The SHADOW chain in the running process (Phase 16, plan 16-31).

`ShadowCoordinator` is the object the paper loop hands its risk-passed bar outcomes to. It wires
the SHADOW pieces that were built and tested in isolation into one chain, in the process that
runs the loop:

    risk-passed outcome -> labelled alert (APR / SKP buttons) -> APPROVE -> confirmation card
    (D041) -> CONFIRM -> exposure reserved (Q-C) -> simulated plan -> live 1m trade and mark
    minutes (public REST, no credential) -> fill, exits, funding -> paper ledger -> the risk
    inputs of the NEXT bar's verdict.

Decisions consumed, never re-decided: D-12 (the label and mode are on every text, built only by
`render_shadow_message`), D-14 (Phase 14 fill semantics on live data through `ShadowFillDriver`),
D-16 (functional buttons through the existing callback pipeline and its replay), D-17 (the
simulated positions feed the next risk verdict), L-12 and D040 (no order adapter exists here),
L-13 and D041 (APPROVE never confirms), REV-12 (the approval expiry is the plan expiry), Q-B
`confirm-plus-one` (`eligibility_start_for`), Q-C `reserve-at-confirm` (`ShadowReservations`)
and Q-L `separate-bot` (one getUpdates consumer per bot token).

This module imports nothing from `src.execution`, no order adapter and nothing from `telegram`
(python-telegram-bot stays behind `src/adapters/`). Its only inputs from the exchange are the
credential-free public klines, mark-price klines and funding history. It sends no text itself:
every message leaves through `send_shadow_alert`, the confirm callbacks and the reply function,
all of which build their text with the one composer.

Threads: the event loop runs the Telegram application and the poller; every synchronous store
call of a press (`dispatch_callback`) and of a poll step runs through `asyncio.to_thread`.
`ShadowLedger` and `ShadowReservations` serialise on the ledger lock; the position table has its
own lock (the coordinator lock).

Lock order (plan 16-58, B2-CR-01): the ledger lock and the coordinator lock are never nested in
the coordinator-then-ledger order, and the CONFIRM section never calls back into the coordinator
while it holds the ledger lock. Concretely: `_ensure_drivers` snapshots the reservations under the
ledger lock alone and builds the missing drivers under the coordinator lock alone; the rebuild at
restart publishes its drivers after the ledger section ends; `ConfirmBook` calls `on_confirmed`
after it released its section. No I/O is added under either lock.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from src.adapters.binance_public import FundingTick
from src.adapters.telegram_callbacks import DispatchResult, ParsedCallback
from src.adapters.telegram_notify import TelegramTextBot
from src.backtest.costs import CostModel, build_cost_model, cost_slice
from src.backtest.funding import FundingCoverageError, FundingRow
from src.backtest.lifecycle import EVENT_FILL
from src.backtest.semantics import FUNDING_JITTER, FUNDING_MAX_CADENCE
from src.core.types import Candle
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, DailyState
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.attribution import (
    EVENT_CONFIRM_EXPIRED,
    EVENT_CONFIRMED,
    ShadowOutcome,
)
from src.paper.freeze import StreamEpoch
from src.paper.journal import SHADOW_MODE, PaperRecord, assemble_paper_record
from src.paper.live_minutes import LiveMinutePoller, LiveMinuteSource, PublicMinuteFeed
from src.paper.loop import BarOutcome
from src.paper.pipeline import PipelineResult
from src.paper.runtime_config import RuntimeConfig
from src.paper.shadow import (
    ALERT_CORRELATION_PREFIX,
    EVENT_APPROVAL_EXPIRED,
    EVENT_SHADOW_ALERT_PENDING,
    REASON_RUNTIME_RESTART,
    Mode,
    ShadowApprovalBook,
    ShadowSendOutcome,
    ShadowStores,
    approval_id_for,
    invalidate_pending_on_restart,
    make_shadow_reply_fn,
    require_shadow,
    send_shadow_alert,
)
from src.paper.shadow_confirm import (
    CONFIRM_TTL_SECONDS_DEFAULT,
    EVENT_SHADOW_CONFIRMED,
    TERMINAL_CONFIRM_EVENTS,
    ConfirmBook,
    ConfirmStores,
    make_confirm_callbacks,
)
from src.paper.shadow_fill import (
    FillEligibility,
    FundingHistory,
    ShadowFillDriver,
    eligibility_start_for,
)
from src.paper.shadow_ledger import (
    CORRELATION_PREFIX,
    EVENT_SHADOW_PLAN_EXPIRED_UNFILLED,
    EVENT_SHADOW_POSITION_OPENED,
    EVENT_SHADOW_RESERVATION_REFUSED,
    REASON_PLAN_EXPIRED_UNFILLED,
    PositionRecord,
    Reservation,
    ReservationBasis,
    ReservationStores,
    ShadowLedger,
    ShadowReservations,
    reservation_key,
)
from src.risk.types import ConstraintSnapshot, OpenPosition, PortfolioVerdict, SizedResult

log = structlog.get_logger()

_MINUTE: Final = timedelta(minutes=1)

# Journal event of a filled simulated position reaching its exit (plan 16-31). Written under the
# correlation of the approval (`shadow-confirm:<approval_id>`) like the reservation events of
# plan 16-23; none of the fixed-list consumers (terminal confirm events, reservation events)
# lists it. Its id and payload are pure functions of the position's data.
EVENT_SHADOW_POSITION_CLOSED: Final = "SHADOW_POSITION_CLOSED"

# The sizing context of an alerted plan (plan 16-31): the regime, the closed signal bar, the
# constraint snapshot the bar was sized with and the sized facts. A fill driver cannot be rebuilt
# after a restart without it, because none of these is on the approval, the plan or the
# reservation. Journaled once with the alert under `shadow-plan:<trade_plan_id>`.
EVENT_SHADOW_PLAN_CONTEXT: Final = "SHADOW_PLAN_CONTEXT"
PLAN_CONTEXT_CORRELATION: Final = "shadow-plan:"

# A risk-passed bar whose SHADOW signal, plan and alert never persisted before a crash (plan 16-57,
# B1-WR-03, L-11). Journaled once per (epoch, plan_hash) at the next start, before any new bar is
# evaluated, and never re-alerted: a late alert would be a late signal. It is not a strategy
# signal: it has no signal or plan row (the journal row carries no parent id), never becomes a
# paper record, and is counted apart (`ShadowCoordinator.lost_signals`).
EVENT_SHADOW_SIGNAL_LOST: Final = "SHADOW_SIGNAL_LOST"
SIGNAL_LOST_CORRELATION: Final = "shadow-lost:"
REASON_NOT_PERSISTED_BEFORE_RESTART: Final = "NOT_PERSISTED_BEFORE_RESTART"

# Q-L `separate-bot` (decisions/16-DEC-Q-L.md): the SHADOW bot is its own Telegram bot, so exactly
# one process polls getUpdates for its token. Logged at start and when Telegram reports a
# Conflict. The token itself is never logged.
BOT_TOKEN_RULE: Final = (
    "separate-bot: exactly one getUpdates consumer per bot token (16-DEC-Q-L, RUNBOOK 20.3)"
)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class ShadowRuntimeError(RuntimeError):
    """The SHADOW chain cannot continue safely (fail closed): the message is this module's own."""


class ShadowOpenRefused(ShadowRuntimeError):
    """The fill driver refused to open a confirmed plan (plan 16-58, B2-CR-03).

    Carries the reservation and the driver's reject code. A pending reservation is released with
    a journaled SHADOW_RESERVATION_REFUSED; it never stops the poller, `start` or `restore`.
    """

    def __init__(self, reservation: Reservation, reason_code: str) -> None:
        super().__init__(
            f"the confirmed plan {reservation.key} cannot rest as a simulated plan: {reason_code}"
        )
        self.reservation = reservation
        self.reason_code = reason_code


@dataclass(frozen=True)
class RiskPassedBar:
    """A PAPER_BAR_PROCESSED record of stage `risk_passed`, as the composition root reads it.

    The runtime passes these into `ShadowCoordinator.start` / `restore` (plan 16-57): this module
    never imports the runtime or reads the runtime state port itself.
    """

    symbol: str
    interval: str
    bar_close_utc: datetime
    signal_id: str
    plan_hash: str


# --------------------------------------------------------------------------- #
# Ports.
# --------------------------------------------------------------------------- #


class ShadowRuntimeStores(ShadowStores, ConfirmStores, ReservationStores, Protocol):
    """Every store call the running chain makes: the three ports plus three single-row readers."""

    def get_signal(self, signal_id: str) -> Signal | None: ...
    def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None: ...
    def get_approval(self, approval_id: str) -> Approval | None: ...


class ShadowPublicFeed(PublicMinuteFeed, Protocol):
    """The credential-free public adapter as the chain reads it (`BinancePublicMarketData`)."""

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]: ...


@dataclass(frozen=True)
class FillContext:
    """What a fill driver is built from, besides the plan: the cost model and the identity.

    `constraints_for(symbol, bar_close_utc)` returns the point-in-time exchange constraint
    snapshot the signal bar was sized with (the runtime passes `ConstraintProvider.snapshot_for`,
    the same call the bar context factory made).
    """

    cost_model: CostModel
    strategy_version: str
    parameter_set_hash: str
    constraints_for: Callable[[str, datetime], ConstraintSnapshot]


@dataclass(frozen=True)
class LedgerRiskInputs:
    """The `RiskInputsProvider` port (`market_inputs.py`) bound to a `ShadowLedger` (D-17).

    Built by `bind_risk_inputs`; the two members are functions over the ledger rather than
    methods, so there is no class in `src` that implements the port with invented state
    (`tests/test_paper_market_inputs.py` keeps asserting that).
    """

    open_positions: Callable[[datetime], Sequence[OpenPosition]]
    daily_loss_quote: Callable[[datetime], Decimal | None]


def bind_risk_inputs(ledger: ShadowLedger) -> LedgerRiskInputs:
    """The open positions (fills and still-valid reservations) and the simulated daily loss."""
    return LedgerRiskInputs(
        open_positions=lambda at_utc: tuple(ledger.risk_inputs(at_utc)[0]),
        daily_loss_quote=lambda at_utc: ledger.risk_inputs(at_utc)[1],
    )


@dataclass(frozen=True)
class PositionView:
    """A read-only view of one simulated plan the coordinator drives."""

    key: str
    approval_id: str
    trade_plan_id: str
    symbol: str
    eligibility_start_utc: datetime
    filled: bool
    closed: bool


@dataclass
class _PlanContext:
    """What the signal bar decided, kept in memory from the alert to the fill."""

    outcome: BarOutcome
    constraints: ConstraintSnapshot


@dataclass
class _Position:
    key: str
    reservation: Reservation
    driver: ShadowFillDriver
    eligibility: FillEligibility


class _BotProxy:
    """A forwarding `TelegramTextBot`: the real bot may exist only once the application does."""

    def __init__(self, bot: TelegramTextBot | None) -> None:
        self._bot = bot

    def bind(self, bot: TelegramTextBot) -> None:
        self._bot = bot

    @property
    def is_bound(self) -> bool:
        return self._bot is not None

    def _require(self) -> TelegramTextBot:
        if self._bot is None:
            raise ShadowRuntimeError("the Telegram bot is not bound yet")
        return self._bot

    async def send_message(
        self, *, chat_id: str | int, text: str, reply_markup: Any = None
    ) -> object:
        return await self._require().send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )

    async def edit_message_text(
        self, *, chat_id: str | int, message_id: int, text: str, reply_markup: Any = None
    ) -> object:
        return await self._require().edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )


def _approval_dict(approval: Approval) -> dict[str, str | None]:
    """The approval row as the paper record assembler reads it (the measured timestamps)."""
    return {
        "approval_id": approval.approval_id,
        "action": approval.action.value,
        "requested_at_utc": approval.requested_at_utc.isoformat(),
        "acted_at_utc": None
        if approval.acted_at_utc is None
        else approval.acted_at_utc.isoformat(),
    }


def _to_ms(value: datetime) -> int:
    return (value - _EPOCH) // timedelta(milliseconds=1)


def _adverse_entry(signal: Signal, plan: TradePlan) -> Decimal:
    """The adverse edge of the entry zone, the sizing basis (LONG entry_max, SHORT entry_min)."""
    if signal.direction == "LONG":
        return plan.entry_max_price
    if signal.direction == "SHORT":
        return plan.entry_min_price
    raise ValueError(f"unknown signal direction {signal.direction!r}")


# --------------------------------------------------------------------------- #
# The coordinator.
# --------------------------------------------------------------------------- #


class ShadowCoordinator:
    """Alert, approval, confirm, simulated fill, ledger and minute polling in one process.

    `mode` must be `Mode.SHADOW` (`require_shadow`, D-12: the only constructible mode). There is
    no parameter through which an order adapter or an exchange client could be passed (L-12).
    The poll cadence and the minute close lag are the user-ratified timing numbers of the
    runtime configuration (O-07) and have no default.
    """

    def __init__(
        self,
        *,
        mode: Mode,
        stores: ShadowRuntimeStores,
        bot: TelegramTextBot | None,
        chat_id: int,
        authorized_user_ids: frozenset[int],
        clock: Callable[[], datetime],
        ledger: ShadowLedger,
        public: ShadowPublicFeed,
        fill: FillContext,
        minute_poll_interval_seconds: int,
        minute_close_lag_seconds: int,
        experiment_id: str,
        epoch_id: str,
        confirm_ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        application_factory: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        require_shadow(mode)
        # Phase 23 (D-02): the allow-list is required and never allow-all. The members are never
        # put in the message.
        if (
            not isinstance(authorized_user_ids, frozenset)
            or not authorized_user_ids
            or any(isinstance(m, bool) or not isinstance(m, int) for m in authorized_user_ids)
        ):
            raise ValueError("authorized_user_ids must be a non-empty frozenset of int user ids")
        self._mode = mode
        self._stores = stores
        self._chat_id = chat_id
        self._authorized_user_ids = authorized_user_ids
        self._clock = clock
        self._ledger = ledger
        self._public = public
        self._fill = fill
        self._experiment_id = experiment_id
        self._epoch_id = epoch_id
        self._bot = _BotProxy(bot)
        self._lock = threading.RLock()
        self._plans: dict[str, _PlanContext] = {}
        self._positions: dict[str, _Position] = {}
        self._marks: dict[str, Decimal] = {}
        self._closed_journaled: set[str] = set()
        self._alert_order: list[str] = []
        self._experiment_id = experiment_id
        self._close_lag_seconds = minute_close_lag_seconds
        self._poll_interval = minute_poll_interval_seconds
        self._application_factory = application_factory
        self._application: Any | None = None
        self._telegram_errors: dict[str, int] = {}
        self._conflict_logged = False
        self._lost: list[str] = []

        self._book = ShadowApprovalBook(stores, clock=clock)
        self._reservations = ShadowReservations(ledger, stores, basis_for=self._basis_for)
        self._confirm = ConfirmBook(
            stores,
            clock=clock,
            ttl_seconds=confirm_ttl_seconds,
            mode=mode,
            mark_price=self._mark_price,
            on_confirmed=self._on_confirmed,
            recheck=self._open_check,
            reservations=self._reservations,
        )
        self._callbacks = make_confirm_callbacks(
            approvals=self._book, confirm=self._confirm, bot=self._bot, mode=mode, sleep=sleep
        )
        self._reply = make_shadow_reply_fn(
            self._bot, mode=mode, clock=clock, book=self._book, confirm_book=self._confirm
        )
        self._sleep = sleep
        self._source = LiveMinuteSource()
        self._poller = LiveMinutePoller(
            feed=public,
            source=self._source,
            poll_interval_seconds=minute_poll_interval_seconds,
            close_lag_seconds=minute_close_lag_seconds,
        )

    # ---- views ------------------------------------------------------------ #

    @property
    def risk_inputs(self) -> LedgerRiskInputs:
        """The risk-inputs port of the bar context factory, bound to this chain's ledger."""
        return bind_risk_inputs(self._ledger)

    @property
    def ledger(self) -> ShadowLedger:
        return self._ledger

    @property
    def confirm_book(self) -> ConfirmBook:
        return self._confirm

    def open_positions(self) -> tuple[PositionView, ...]:
        """The simulated plans being driven (waiting for a fill, filled or closed), key order."""
        with self._lock:
            return tuple(self._view(p) for _key, p in sorted(self._positions.items()))

    @staticmethod
    def _view(position: _Position) -> PositionView:
        return PositionView(
            key=position.key,
            approval_id=position.reservation.approval_id,
            trade_plan_id=position.reservation.trade_plan_id,
            symbol=position.reservation.symbol,
            eligibility_start_utc=position.driver.eligibility_start_utc,
            filled=any(e.kind == EVENT_FILL for e in position.driver.events),
            closed=position.driver.is_closed,
        )

    # ---- the callback pipeline ------------------------------------------- #

    def callback_kwargs(self) -> dict[str, Any]:
        """The keyword arguments of `on_callback` and `build_application` for this chain.

        The resolver, the dispatcher and the reply function are the SHADOW ones (16-04, 16-11);
        the dispatcher runs the synchronous `dispatch_callback` off the event loop. The chat gate
        is `authorized_chat_gate` (D-16); since Phase 23 the user and chat-type gate is
        `authorized_user_gate` over the required allow-list (D-01, D-02).
        """
        return {
            "authorized_chat_id": self._chat_id,
            "authorized_user_ids": self._authorized_user_ids,
            "binding_context_resolver": self._book.resolve,
            "dispatch": self._dispatch,
            "reply_text_fn": self._reply,
            "confirm_handler": self._callbacks.confirm_handler,
            "approved_handler": self._callbacks.approved_handler,
            "clock": self._clock,
        }

    async def _dispatch(self, parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        return await asyncio.to_thread(self._book.dispatch, parsed, **kwargs)

    # ---- from the paper loop ---------------------------------------------- #

    async def on_result(self, result: PipelineResult) -> list[ShadowSendOutcome]:
        """Hand every evaluated outcome of a pipeline tick over; returns the alerts it sent."""
        sent: list[ShadowSendOutcome] = []
        for outcome in result.evaluated:
            alert = await self.on_outcome(outcome)
            if alert is not None:
                sent.append(alert)
        return sent

    async def on_outcome(self, outcome: BarOutcome) -> ShadowSendOutcome | None:
        """A risk-passed outcome becomes a SHADOW alert; anything else sends nothing.

        Returns None for a NO_TRADE, strategy, planner or risk-stage outcome and for a plan that
        was already alerted by this process. The alert is journal-first (`send_shadow_alert`).
        """
        if outcome.stage != "risk_passed":
            return None
        signal, plan, verdict = outcome.signal, outcome.trade_plan, outcome.verdict
        if (
            signal is None
            or plan is None
            or verdict is None
            or verdict.is_no_trade
            or verdict.sized is None
            or verdict.sized.quantity is None
        ):
            raise ShadowRuntimeError(
                "a risk-passed outcome needs a signal, a plan and a sized verdict"
            )
        with self._lock:
            if plan.plan_hash in self._plans:
                return None
            constraints = self._fill.constraints_for(
                signal.symbol, outcome.closed_candle.close_time_utc
            )
            self._plans[plan.plan_hash] = _PlanContext(outcome=outcome, constraints=constraints)
            self._alert_order.append(plan.plan_hash)
        now = self._clock()
        await self._refresh_mark(signal.symbol, now)
        reasons = [signal.setup_type]
        if outcome.regime:
            reasons.append(f"REGIME_{outcome.regime}")
        sent = await send_shadow_alert(
            stores=self._stores,
            book=self._book,
            bot=self._bot,
            chat_id=self._chat_id,
            mode=self._mode,
            signal=signal,
            plan=plan,
            exposure_quote=verdict.sized.quantity * _adverse_entry(signal, plan),
            reason_codes=reasons,
            now_utc=now,
            sleep=self._sleep,
        )
        # The parents exist now (the alert persisted them first), so the context can be journaled.
        await asyncio.to_thread(self._journal_plan_context, signal, plan, outcome, constraints, now)
        return sent

    def _journal_plan_context(
        self,
        signal: Signal,
        plan: TradePlan,
        outcome: BarOutcome,
        constraints: ConstraintSnapshot,
        now_utc: datetime,
    ) -> None:
        sized = outcome.verdict.sized if outcome.verdict is not None else None
        if sized is None or sized.quantity is None:
            raise ShadowRuntimeError("a risk-passed outcome needs a sized verdict")
        candle = outcome.closed_candle
        correlation = f"{PLAN_CONTEXT_CORRELATION}{plan.trade_plan_id}"
        body = {
            "plan_hash": plan.plan_hash,
            "regime": outcome.regime,
            "closed_candle": {
                "symbol": candle.symbol,
                "interval": candle.interval,
                "open_time_utc": candle.open_time_utc.isoformat(),
                "close_time_utc": candle.close_time_utc.isoformat(),
                "open": str(candle.open),
                "high": str(candle.high),
                "low": str(candle.low),
                "close": str(candle.close),
                "volume": str(candle.volume),
            },
            "constraints": {
                "symbol": constraints.symbol,
                "price_tick_size": str(constraints.price_tick_size),
                "quantity_step_size": str(constraints.quantity_step_size),
                "min_quantity": str(constraints.min_quantity),
                "min_notional": str(constraints.min_notional),
                "metadata_observed_at_utc": constraints.metadata_observed_at_utc.isoformat(),
            },
            "sized": {"quantity": str(sized.quantity), "realized_risk": str(sized.realized_risk)},
            "mode": self._mode.value,
        }
        self._stores.record_journal(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix="shadow-ctx",
                    correlation_id=correlation,
                    event_type=EVENT_SHADOW_PLAN_CONTEXT,
                    entity_id=plan.trade_plan_id,
                    step="context",
                ),
                occurred_at_utc=now_utc,
                event_type=EVENT_SHADOW_PLAN_CONTEXT,
                entity_type="ShadowPlan",
                entity_id=plan.trade_plan_id,
                correlation_id=correlation,
                signal_id=signal.signal_id,
                trade_plan_id=plan.trade_plan_id,
                payload_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
            )
        )

    def _context_from_journal(self, reservation: Reservation) -> _PlanContext:
        """Rebuild the sizing context of a plan this process did not alert (after a restart)."""
        signal = self._stores.get_signal(reservation.signal_id)
        plan = self._stores.get_trade_plan(reservation.trade_plan_id)
        events = [
            e
            for e in self._stores.journal_for_correlation(
                f"{PLAN_CONTEXT_CORRELATION}{reservation.trade_plan_id}"
            )
            if e.event_type == EVENT_SHADOW_PLAN_CONTEXT
        ]
        if signal is None or plan is None or not events:
            raise ShadowRuntimeError(
                f"no plan context is journaled for {reservation.key}: the simulated plan cannot "
                "be rebuilt after the restart"
            )
        body = json.loads(events[0].payload_json)
        if body.get("plan_hash") != plan.plan_hash or plan.plan_hash != reservation.plan_hash:
            raise ShadowRuntimeError(f"the journaled plan context of {reservation.key} differs")
        c, k, s = body["closed_candle"], body["constraints"], body["sized"]
        candle = Candle(
            symbol=c["symbol"],
            interval=c["interval"],
            open_time_utc=datetime.fromisoformat(c["open_time_utc"]),
            close_time_utc=datetime.fromisoformat(c["close_time_utc"]),
            open=Decimal(c["open"]),
            high=Decimal(c["high"]),
            low=Decimal(c["low"]),
            close=Decimal(c["close"]),
            volume=Decimal(c["volume"]),
        )
        constraints = ConstraintSnapshot(
            symbol=k["symbol"],
            price_tick_size=Decimal(k["price_tick_size"]),
            quantity_step_size=Decimal(k["quantity_step_size"]),
            min_quantity=Decimal(k["min_quantity"]),
            min_notional=Decimal(k["min_notional"]),
            metadata_observed_at_utc=datetime.fromisoformat(k["metadata_observed_at_utc"]),
        )
        # The fill driver reads only the planned quantity and the sized risk of the verdict.
        sized = SizedResult(
            is_no_trade=False,
            quantity=Decimal(s["quantity"]),
            quantity_before_rounding=Decimal(s["quantity"]),
            quantity_after_rounding=Decimal(s["quantity"]),
            quantization_decision="ACCEPTED",
            realized_risk=Decimal(s["realized_risk"]),
        )
        outcome = BarOutcome(
            closed_candle=candle,
            stage="risk_passed",
            reason_code="OK",
            signal=signal,
            trade_plan=plan,
            verdict=PortfolioVerdict(False, sized, "OK", DailyState.NORMAL),
            regime=body.get("regime"),
        )
        return _PlanContext(outcome=outcome, constraints=constraints)

    # ---- the confirm book's hooks ----------------------------------------- #

    def _basis_for(self, signal: Signal, plan: TradePlan) -> ReservationBasis | None:
        """The sizing facts of the signal bar (None fails closed: nothing is reserved)."""
        context = self._plans.get(plan.plan_hash)
        if context is None:
            return None
        sized = context.outcome.verdict.sized if context.outcome.verdict is not None else None
        if sized is None or sized.quantity is None:
            return None
        return ReservationBasis(
            sized_realized_risk=sized.realized_risk, planned_quantity=sized.quantity
        )

    def _mark_price(self, symbol: str) -> Decimal | None:
        return self._marks.get(symbol)

    async def _refresh_mark(self, symbol: str, now: datetime) -> None:
        """Best effort: the newest closed 1m mark price for the card (None when unavailable)."""
        try:
            rows = await self._public.mark_klines(
                symbol, "1m", start_ms=None, end_ms=_to_ms(now), limit=2
            )
        except Exception as exc:  # noqa: BLE001 - a missing mark price is shown, not fatal
            log.warning("paper.shadow.mark_price_failed", error_class=type(exc).__name__)
            self._marks.pop(symbol, None)
            return
        closed = [r for r in rows if r.close_time_utc <= now]
        if closed:
            self._marks[symbol] = max(closed, key=lambda r: r.open_time_utc).close
        else:
            self._marks.pop(symbol, None)

    def _on_confirmed(
        self, approval: Approval, plan: TradePlan, confirmed_at_utc: datetime
    ) -> None:
        """A CONFIRM was journaled and its exposure reserved: start driving the simulated plan.

        This is the ONLY side effect of a successful CONFIRM (L-13): it builds a fill driver. It
        never raises into the press; a plan that could not get its driver now is picked up by the
        next poll step.
        """
        try:
            self._ensure_drivers()
        except Exception as exc:  # noqa: BLE001 - the CONFIRM stands; the poll retries
            log.error("paper.shadow.driver_failed", error_class=type(exc).__name__)

    # ---- drivers ------------------------------------------------------------ #

    def _ensure_drivers(self) -> None:
        """Give every reserved or filled plan without a driver one (idempotent).

        Lock order (B2-CR-01): the reservations are snapshotted under the ledger lock ALONE and
        the lock is released; only then is the coordinator lock taken to build the missing
        drivers. The coordinator lock is therefore never held while the ledger lock is waited for.
        """
        snapshot = self._reservations.active()
        refused: list[ShadowOpenRefused] = []
        with self._lock:
            for reservation in snapshot:
                if reservation.key in self._positions:
                    continue
                try:
                    self._positions[reservation.key] = self._build_position(reservation)
                except ShadowOpenRefused as exc:
                    refused.append(exc)
        # B2-CR-03: one plan the driver cannot open is released with a journaled refusal; it
        # never stops the poller or the other plans. Done outside the coordinator lock (the
        # release takes the ledger lock).
        for refusal in refused:
            released = self._reservations.refuse(refusal.reservation.key, refusal.reason_code)
            log.error(
                "paper.shadow.reservation_refused",
                plan_hash=refusal.reservation.plan_hash,
                reason=refusal.reason_code,
                released=released,
            )

    def _new_driver(self, context: _PlanContext) -> ShadowFillDriver:
        return ShadowFillDriver(
            cost_model=self._fill.cost_model,
            constraint_snapshot=context.constraints,
            strategy_version=self._fill.strategy_version,
            parameter_set_hash=self._fill.parameter_set_hash,
            constraints_extrapolated=False,
        )

    def _open_check(self, signal: Signal, plan: TradePlan, now_utc: datetime) -> str | None:
        """The CONFIRM-time re-check: could the fill driver open this plan? (B2-CR-03)

        Runs the same `open_confirmed` call `_build_position` makes, on a throw-away driver with
        the constraint snapshot the plan was sized with, before the reservation is accepted. None
        when it would open or when another check owns the refusal (no sizing context, a CONFIRM
        that is not fill-eligible); else the driver reject code.
        """
        context = self._plans.get(plan.plan_hash)
        if context is None:
            return None  # no sizing basis: the capacity check fails closed
        eligibility = eligibility_start_for(
            signal_close_utc=signal.source_candle_close_utc,
            plan_expiry_utc=plan.expiry_utc,
            confirm_outcome="CONFIRMED",
            confirmed_at_utc=now_utc,
        )
        if not eligibility.is_eligible:
            return None  # the reservation check refuses it with its own reason
        opened = self._new_driver(context).open_confirmed(context.outcome, eligibility)
        return None if opened.opened else opened.reason_code

    def _build_position(self, reservation: Reservation) -> _Position:
        context = self._plans.get(reservation.plan_hash)
        if context is None:
            context = self._context_from_journal(reservation)
            self._plans[reservation.plan_hash] = context
        approval = self._stores.get_approval(reservation.approval_id)
        eligibility = eligibility_start_for(
            signal_close_utc=reservation.signal_close_utc,
            plan_expiry_utc=reservation.plan_expiry_utc,
            confirm_outcome="CONFIRMED",
            confirmed_at_utc=reservation.confirmed_at_utc,
            approved_at_utc=None if approval is None else approval.acted_at_utc,
        )
        driver = self._new_driver(context)
        opened = driver.open_confirmed(context.outcome, eligibility)
        if not opened.opened:
            raise ShadowOpenRefused(reservation, opened.reason_code)
        return _Position(
            key=reservation.key, reservation=reservation, driver=driver, eligibility=eligibility
        )

    # ---- the poller --------------------------------------------------------- #

    async def poll_once(self) -> None:
        """One poll step: minutes, positions, ledger, expiry sweeps (in this order).

        `sync` runs after each `advance_to` and before `release_expired` on the same step, so a
        fill is journaled before an expiry sweep can release its reservation (plan 16-23).
        """
        now = self._clock()
        await asyncio.to_thread(self._ensure_drivers)
        with self._lock:
            active = [p for _k, p in sorted(self._positions.items()) if not p.driver.is_closed]
        settled: dict[str, datetime] = {}
        for symbol in sorted({p.reservation.symbol for p in active}):
            since = min(
                p.driver.eligibility_start_utc for p in active if p.reservation.symbol == symbol
            )
            result = await self._poller.poll_once(symbol, now_utc=now, since_utc=since)
            settled[symbol] = result.settled_through_utc
        for position in active:
            await self._advance(position, settled[position.reservation.symbol])
        await asyncio.to_thread(self._sweep, now)
        # The confirm book is driven by the callback handlers on this thread, so its TTL sweep runs
        # here too (its state is not shared with the worker thread).
        self._confirm.expire_due(now)

    async def _advance(self, position: _Position, horizon: datetime) -> None:
        symbol = position.reservation.symbol
        if (
            self._source.last_open_utc(symbol, "trade") is None
            or self._source.last_open_utc(symbol, "mark") is None
            or horizon <= position.driver.advanced_to_utc
        ):
            return
        try:
            await asyncio.to_thread(position.driver.advance_to, horizon, self._source, funding=None)
        except FundingCoverageError:
            funding = await self._funding_history(position, horizon)
            await asyncio.to_thread(
                position.driver.advance_to, horizon, self._source, funding=funding
            )

    async def _funding_history(self, position: _Position, until: datetime) -> FundingHistory:
        """The public funding history around the holding window (fails closed on a hole)."""
        return await self._funding_range(
            position.reservation.symbol, position.driver.eligibility_start_utc, until
        )

    async def _funding_range(
        self, symbol: str, since_utc: datetime, until: datetime
    ) -> FundingHistory:
        tolerance = FUNDING_MAX_CADENCE + FUNDING_JITTER
        start = since_utc - 2 * tolerance
        ticks = await self._public.funding_rate(
            symbol, start_ms=_to_ms(start), end_ms=_to_ms(until), limit=1000
        )
        rows = tuple(
            FundingRow(
                symbol=t.symbol,
                funding_time_utc=t.funding_time_utc,
                funding_rate=t.funding_rate,
                mark_price=t.mark_price,
            )
            for t in ticks
        )
        return FundingHistory(rows=rows, loaded_start_utc=start, loaded_end_utc=until)

    def _sweep(self, now: datetime) -> None:
        """Ledger sync of every driver, close records, then the expiry sweeps (worker thread)."""
        with self._lock:
            positions = dict(self._positions)
        self._reservations.sync_many({key: p.driver for key, p in positions.items()})
        for _key, position in sorted(positions.items()):
            self._journal_closed(position)
        # B2-CR-02: expiry follows the DATA horizon the drivers were advanced to (the same value
        # the minute poller settles through), never the raw wall clock. A fill in the last minutes
        # before the plan expiry is only booked once its minute is settled.
        self._reservations.release_expired(now - timedelta(seconds=self._close_lag_seconds))

    def _journal_closed(self, position: _Position) -> None:
        """Journal SHADOW_POSITION_CLOSED once for a filled position that reached its exit."""
        if position.key in self._closed_journaled or not position.driver.is_closed:
            return
        record = position.driver.trade_record()
        if record.exit_kind is None or record.exit_time_utc is None:
            # The plan ended without a fill (expiry, invalidation): nothing was held to close.
            self._closed_journaled.add(position.key)
            return
        reservation = position.reservation
        approval_id = reservation.approval_id
        correlation = f"{CORRELATION_PREFIX}{approval_id}"
        self._stores.record_journal(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix="shadow-pos",
                    correlation_id=correlation,
                    event_type=EVENT_SHADOW_POSITION_CLOSED,
                    entity_id=approval_id,
                    step="closed",
                ),
                occurred_at_utc=record.exit_time_utc,
                event_type=EVENT_SHADOW_POSITION_CLOSED,
                entity_type="ShadowPosition",
                entity_id=approval_id,
                correlation_id=correlation,
                signal_id=reservation.signal_id,
                trade_plan_id=reservation.trade_plan_id,
                approval_id=approval_id,
                payload_json=json.dumps(
                    {
                        "approval_id": approval_id,
                        "plan_hash": reservation.plan_hash,
                        "exit_kind": record.exit_kind,
                        "eligibility": position.eligibility.to_audit_dict(),
                        "trade": record.to_dict(),
                        "mode": self._mode.value,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        self._closed_journaled.add(position.key)

    # ---- restart (D-15, research Pitfall P13) -------------------------------- #

    async def restore(self, risk_passed: Sequence[RiskPassedBar] = ()) -> None:
        """Fail closed for what a restart cannot carry, and rebuild what it can.

        Raw approval and confirm tokens live in memory only, so every PENDING approval is decided
        EXPIRED and every outstanding confirm is expired, each journaled with reason
        RUNTIME_RESTART; a callback for one of them is rejected afterwards. Reserved and open
        simulated plans are rebuilt from the journal alone (Q-J), replayed over REST 1m history,
        and the poller continues them.

        `risk_passed` are the epoch's risk-passed heartbeats, read by the composition root (plan
        16-57, B1-WR-03). One whose alert never persisted is journaled once as
        `SHADOW_SIGNAL_LOST` and logged; it is never alerted and gets no approval (L-11).
        """
        now = self._clock()
        await asyncio.to_thread(self._journal_lost_signals, tuple(risk_passed), now)
        await asyncio.to_thread(invalidate_pending_on_restart, self._stores, now)
        await asyncio.to_thread(self._confirm.expire_on_restart, now)
        await self._restore_positions(now)

    def lost_signals(self) -> tuple[str, ...]:
        """The plan hashes of the epoch's lost risk-passed signals known at this start, sorted."""
        with self._lock:
            return tuple(sorted(self._lost))

    def _alert_persisted(self, bar: RiskPassedBar) -> bool:
        """True when the alert of this bar's plan was journaled after its parent rows.

        `send_shadow_alert` writes the signal, the plan, both approvals and the mapping first, then
        the SHADOW_ALERT_PENDING row; that row, naming a stored plan with this plan hash, is the
        proof that the alert's rows persisted. A send that failed afterwards is already journaled
        and its approvals are swept by `invalidate_pending_on_restart`.
        """
        events = self._stores.journal_for_correlation(f"{ALERT_CORRELATION_PREFIX}{bar.signal_id}")
        for event in events:
            if event.event_type != EVENT_SHADOW_ALERT_PENDING or event.trade_plan_id is None:
                continue
            plan = self._stores.get_trade_plan(event.trade_plan_id)
            if plan is not None and plan.plan_hash == bar.plan_hash:
                return True
        return False

    def _journal_lost_signals(self, risk_passed: tuple[RiskPassedBar, ...], now: datetime) -> None:
        """Journal one SHADOW_SIGNAL_LOST per risk-passed bar whose alert never persisted.

        The id is a pure function of the epoch and the plan hash, and the payload holds no
        wall-clock instant, so a second start finds the row and writes nothing (replay no-op). The
        row names no signal or plan id: those parent rows do not exist.
        """
        seen: set[str] = set()
        for bar in sorted(risk_passed, key=lambda b: (b.bar_close_utc, b.symbol, b.plan_hash)):
            if bar.plan_hash in seen or self._alert_persisted(bar):
                continue
            seen.add(bar.plan_hash)
            correlation = f"{SIGNAL_LOST_CORRELATION}{bar.plan_hash}"
            with self._lock:
                self._lost.append(bar.plan_hash)
            log.error(
                "paper.shadow.signal_lost",
                plan_hash=bar.plan_hash,
                symbol=bar.symbol,
                bar_close_utc=bar.bar_close_utc.isoformat(),
                reason=REASON_NOT_PERSISTED_BEFORE_RESTART,
            )
            if self._stores.journal_for_correlation(correlation):
                continue  # journaled by an earlier start
            body = {
                "epoch_id": self._epoch_id,
                "plan_hash": bar.plan_hash,
                "signal_id": bar.signal_id,
                "symbol": bar.symbol,
                "interval": bar.interval,
                "bar_close_utc": bar.bar_close_utc.isoformat(),
                "reason": REASON_NOT_PERSISTED_BEFORE_RESTART,
                "mode": self._mode.value,
            }
            self._stores.record_journal(
                JournalEvent(
                    journal_event_id=correlated_event_id(
                        prefix="shadow-lost",
                        correlation_id=correlation,
                        event_type=EVENT_SHADOW_SIGNAL_LOST,
                        entity_id=bar.plan_hash,
                        step=self._epoch_id,
                    ),
                    occurred_at_utc=now,
                    event_type=EVENT_SHADOW_SIGNAL_LOST,
                    entity_type="ShadowSignal",
                    entity_id=bar.plan_hash,
                    correlation_id=correlation,
                    payload_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
                )
            )

    async def _restore_positions(self, now: datetime) -> None:
        records = await asyncio.to_thread(self._reservations.load_records)
        for event in records:
            if event.event_type == EVENT_SHADOW_POSITION_CLOSED:
                body = json.loads(event.payload_json)
                self._closed_journaled.add(
                    reservation_key(str(body["plan_hash"]), str(body["approval_id"]))
                )
        opened = [
            Reservation.from_payload(json.loads(e.payload_json))
            for e in records
            if e.event_type == EVENT_SHADOW_POSITION_OPENED
        ]
        horizon = now - timedelta(seconds=self._close_lag_seconds)
        funding: dict[str, FundingHistory] = {}
        for symbol in sorted({r.symbol for r in opened}):
            since = min(r.eligibility_start_utc for r in opened if r.symbol == symbol)
            await self._poller.poll_once(symbol, now_utc=now, since_utc=since)
        for reservation in opened:
            funding[reservation.key] = await self._funding_range(
                reservation.symbol, reservation.eligibility_start_utc, horizon
            )

        rebuilt: dict[str, _Position] = {}

        def driver_for(record: PositionRecord) -> ShadowFillDriver:
            # Runs inside the ledger section of `rebuild_from_records`: the coordinator lock is
            # NOT taken here (B2-CR-01); the positions are published after the rebuild returns.
            position = self._build_position(record.reservation)
            rebuilt[position.key] = position
            return position.driver

        await asyncio.to_thread(
            self._reservations.rebuild_from_records,
            records,
            self._source if opened else None,
            now_utc=horizon,
            driver_for=driver_for,
            funding_for=lambda reservation: funding.get(reservation.key),
        )
        with self._lock:
            self._positions.update(rebuilt)
        await asyncio.to_thread(self._ensure_drivers)
        with self._lock:
            positions = sorted(self._positions.items())
        for _key, position in positions:
            await asyncio.to_thread(self._journal_closed, position)

    # ---- the paper records of the session (plan 16-35) ----------------------- #

    def paper_records(self, now_utc: datetime | None = None) -> dict[str, list[PaperRecord]]:
        """The paper records of every plan this process alerted, by signal id, in alert order.

        A plan whose outcome is not decided yet (an outstanding confirm card, a confirmed plan
        still waiting for its fill) has no entry: records are written at the terminal outcome.
        """
        out: dict[str, list[PaperRecord]] = {}
        with self._lock:
            alerted = [self._plans[h].outcome for h in self._alert_order]
        for outcome in alerted:
            if outcome.signal is None or outcome.trade_plan is None:
                continue
            records = self.records_for(outcome.signal, outcome.trade_plan, now_utc)
            if records:
                out[outcome.signal.signal_id] = records
        return out

    def records_for(
        self, signal: Signal, plan: TradePlan, now_utc: datetime | None = None
    ) -> list[PaperRecord]:
        """The attribution of one plan from the journaled approval and confirm rows (D-15).

        APPROVE then CONFIRM with a fill is user-executed-sim with the measured approval delay and
        the confirm timestamps; SKIP, CANCEL, a refused or expired approval, a confirm that ran
        out and a restart give an opportunity with the reason; a plan nobody touched is the
        engine row alone until it expires. An empty list means "not decided yet".
        """
        now = self._clock() if now_utc is None else now_utc
        approve = self._stores.get_approval(approval_id_for(plan, ApprovalAction.APPROVE))
        skip = self._stores.get_approval(approval_id_for(plan, ApprovalAction.SKIP_USER))
        signal_dict = {
            "strategy_id": signal.strategy_id,
            "strategy_version": signal.strategy_version,
            "parameter_set_id": signal.parameter_set_id,
            "parameter_set_hash": signal.parameter_set_hash,
            "experiment_id": self._experiment_id,
            "symbol": signal.symbol,
            "signal_id": signal.signal_id,
            "detected_at_utc": signal.detected_at_utc.isoformat(),
        }

        def assemble(
            outcome: ShadowOutcome,
            approval: Approval | None = None,
            *,
            confirm: dict[str, str] | None = None,
            order: dict[str, str] | None = None,
            fill: dict[str, str] | None = None,
        ) -> list[PaperRecord]:
            return assemble_paper_record(
                epoch_id=self._epoch_id,
                signal=signal_dict,
                trade_plan={"plan_hash": plan.plan_hash},
                approval=None if approval is None else _approval_dict(approval),
                order=order,
                fill=fill,
                mode=SHADOW_MODE,
                confirm=confirm,
                shadow_outcome=outcome,
            )

        if skip is not None and skip.status is ApprovalResult.SKIPPED:
            return assemble(ShadowOutcome(approval_action="SKIP_USER"), skip)
        if approve is not None and approve.status is ApprovalResult.APPROVED:
            return self._approved_records(plan, approve, assemble)
        if any(row is not None and row.status is ApprovalResult.EXPIRED for row in (approve, skip)):
            # The restart sweep decides ONE row of a plan EXPIRED (the database allows one decided
            # approval per plan); the sibling stays PENDING with a token nobody holds any more.
            return assemble(ShadowOutcome(approval_rejection_reason=REASON_RUNTIME_RESTART))
        for row in (approve, skip):
            if row is not None and any(
                e.event_type == EVENT_APPROVAL_EXPIRED
                for e in self._stores.journal_for_correlation(f"approval:{row.approval_id}")
            ):
                return assemble(
                    ShadowOutcome(approval_rejection_reason="APPROVAL_EXPIRED"), approve
                )
        return assemble(ShadowOutcome(plan_expired=now >= plan.expiry_utc))

    def _approved_records(
        self,
        plan: TradePlan,
        approve: Approval,
        assemble: Callable[..., list[PaperRecord]],
    ) -> list[PaperRecord]:
        events = self._stores.journal_for_correlation(f"{CORRELATION_PREFIX}{approve.approval_id}")
        terminal = [e for e in events if e.event_type in TERMINAL_CONFIRM_EVENTS]
        if not terminal:
            return []  # the confirm card is still outstanding
        event = terminal[0]
        body = json.loads(event.payload_json)
        requested = {"confirm_requested_at_utc": str(body["confirm_requested_at_utc"])}
        if event.event_type != EVENT_SHADOW_CONFIRMED:
            outcome = ShadowOutcome(
                approval_action="APPROVE",
                confirm_event=event.event_type,
                confirm_reason=body.get("reason"),
            )
            return assemble(outcome, approve, confirm=requested)
        position = self._positions.get(reservation_key(plan.plan_hash, approve.approval_id))
        fill_time = None
        if position is not None:
            fills = [e for e in position.driver.events if e.kind == EVENT_FILL]
            fill_time = fills[0].time_utc if fills else None
        if fill_time is None:
            refusals = [e for e in events if e.event_type == EVENT_SHADOW_RESERVATION_REFUSED]
            ended = (
                any(e.event_type == EVENT_SHADOW_PLAN_EXPIRED_UNFILLED for e in events)
                or bool(refusals)
                or (position is not None and position.driver.is_closed)
            )
            if not ended:
                return []  # confirmed and resting: nothing happened yet
            # A reservation the fill driver refused (plan 16-58) carries the driver reject code.
            reason = (
                str(json.loads(refusals[0].payload_json).get("reason"))
                if refusals
                else REASON_PLAN_EXPIRED_UNFILLED
            )
            outcome = ShadowOutcome(
                approval_action="APPROVE",
                confirm_event=EVENT_CONFIRM_EXPIRED,
                confirm_reason=reason,
            )
            return assemble(outcome, approve, confirm=requested)
        confirmed = str(body["confirmed_at_utc"])
        return assemble(
            ShadowOutcome(approval_action="APPROVE", confirm_event=EVENT_CONFIRMED),
            approve,
            confirm={**requested, "confirmed_at_utc": confirmed},
            order={"submitted_at_utc": confirmed},
            fill={"fill_time_utc": fill_time.isoformat()},
        )

    async def run_poller(
        self,
        stop: asyncio.Event,
        before_step: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Poll every `minute_poll_interval_seconds` until `stop` is set.

        A poll error ends the loop by propagating, so the caller can fail closed (a feed that
        cannot be read leaves the simulated positions unmanaged). `before_step`, when given, is
        awaited before every poll step and may raise to end the loop the same way (the runtime's
        instance-lease check, plan 16-55).
        """
        while not stop.is_set():
            if before_step is not None:
                await before_step()
            await self.poll_once()
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
            except TimeoutError:
                continue

    # ---- the Telegram application ------------------------------------------ #

    @property
    def telegram_error_counts(self) -> dict[str, int]:
        """Errors that escaped a handler or the polling loop, by exception class name."""
        return dict(self._telegram_errors)

    async def start(self, *, risk_passed: Sequence[RiskPassedBar] = ()) -> None:
        """Start the Telegram application in this event loop (initialize, start, polling).

        Logs the one-consumer-per-token rule first (Q-L). No webhook is configured: getUpdates
        and a webhook are exclusive (research G6). Without an application factory the chain only
        sends (rehearsal and tests). `risk_passed` goes to `restore` (plan 16-57).
        """
        log.info("paper.shadow.bot_token_rule", rule=BOT_TOKEN_RULE)
        # The restart steps run before polling begins: nothing is delivered until they are done.
        await self.restore(risk_passed)
        if self._application_factory is None:
            return
        application = self._application_factory(self.callback_kwargs())
        if not self._bot.is_bound and getattr(application, "bot", None) is not None:
            self._bot.bind(application.bot)
        application.add_error_handler(self.on_telegram_error)
        await application.initialize()
        try:
            await application.start()
            await application.updater.start_polling(
                allowed_updates=["callback_query"], error_callback=self._on_polling_error
            )
        except BaseException:
            await application.shutdown()
            raise
        self._application = application

    async def stop(self) -> None:
        """Stop the application in the reverse order of `start` (idempotent)."""
        application, self._application = self._application, None
        if application is None:
            return
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

    async def on_telegram_error(self, update: object, context: Any) -> None:
        """The application error handler: log the class, count it, change nothing.

        An exception that escaped a callback handler (`RetryAfter`, `BadRequest`,
        `NetworkError`, `Conflict`) never approves, confirms or cancels anything and never stops
        the runtime or the poller. Only the exception class is logged: never a token, callback
        data or message text.
        """
        self._record_telegram_error(getattr(context, "error", None))

    def _on_polling_error(self, error: BaseException) -> None:
        """The synchronous error callback of the updater's getUpdates loop."""
        self._record_telegram_error(error)

    def _record_telegram_error(self, error: BaseException | None) -> None:
        if error is None:
            return
        name = type(error).__name__
        self._telegram_errors[name] = self._telegram_errors.get(name, 0) + 1
        log.warning("paper.shadow.telegram_error", error_class=name)
        is_conflict = any(cls.__name__ == "Conflict" for cls in type(error).__mro__)
        if is_conflict and not self._conflict_logged:
            self._conflict_logged = True
            log.error("paper.shadow.bot_token_conflict", rule=BOT_TOKEN_RULE)

    def expire_due(self) -> list[str]:
        """Journal EXPIRED for every confirm past its TTL (reason CONFIRM_TTL_ELAPSED)."""
        return self._confirm.expire_due(self._clock())


class SnapshotSource(Protocol):
    """The point-in-time constraint source (`market_inputs.ConstraintProvider`)."""

    def snapshot_for(self, symbol: str, at_utc: datetime) -> ConstraintSnapshot: ...


@dataclass(frozen=True)
class ShadowWiring:
    """The seams `run_admitted` builds the SHADOW chain from (`LoopWiring.shadow`).

    Production fills them from the environment (the PostgreSQL stores and the Telegram bot of the
    authorized chat); tests pass fakes. `bot` may be None when the application provides it.
    """

    stores: ShadowRuntimeStores
    chat_id: int
    authorized_user_ids: frozenset[int]
    bot: TelegramTextBot | None = None
    confirm_ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    application_factory: Callable[[dict[str, Any]], Any] | None = None


def build_coordinator(
    wiring: ShadowWiring,
    *,
    epoch: StreamEpoch,
    config: RuntimeConfig,
    clock: Callable[[], datetime],
    parameter_set: ParameterSet,
    constraints: SnapshotSource,
    public: ShadowPublicFeed,
) -> ShadowCoordinator:
    """The chain of one paper epoch: its ledger starts at the epoch opening with the ratified
    initial equity (REV-07), its fill cost model is the registry slice of the pinned set.
    """
    ledger = ShadowLedger(
        initial_equity=config.account.initial_equity,
        parameter_set_params=parameter_set.params,
        started_at_utc=epoch.opened_at_utc,
    )
    fill = FillContext(
        cost_model=build_cost_model(cost_slice(parameter_set.params)),
        strategy_version=parameter_set.strategy_version,
        parameter_set_hash=epoch.parameter_set_hash,
        constraints_for=constraints.snapshot_for,
    )
    try:
        return ShadowCoordinator(
            mode=Mode.SHADOW,
            stores=wiring.stores,
            bot=wiring.bot,
            chat_id=wiring.chat_id,
            authorized_user_ids=wiring.authorized_user_ids,
            clock=clock,
            ledger=ledger,
            public=public,
            fill=fill,
            minute_poll_interval_seconds=config.timing.minute_poll_interval_seconds,
            minute_close_lag_seconds=config.timing.minute_close_lag_seconds,
            experiment_id=epoch.epoch_id,
            epoch_id=epoch.epoch_id,
            confirm_ttl_seconds=wiring.confirm_ttl_seconds,
            sleep=wiring.sleep,
            application_factory=wiring.application_factory,
        )
    except ValueError as exc:
        raise ShadowRuntimeError(f"the SHADOW chain cannot be built: {exc}") from exc


__all__ = [
    "BOT_TOKEN_RULE",
    "EVENT_SHADOW_PLAN_CONTEXT",
    "EVENT_SHADOW_POSITION_CLOSED",
    "EVENT_SHADOW_SIGNAL_LOST",
    "REASON_NOT_PERSISTED_BEFORE_RESTART",
    "SIGNAL_LOST_CORRELATION",
    "RiskPassedBar",
    "FillContext",
    "LedgerRiskInputs",
    "PositionView",
    "ShadowCoordinator",
    "ShadowOpenRefused",
    "ShadowPublicFeed",
    "ShadowRuntimeError",
    "ShadowRuntimeStores",
    "ShadowWiring",
    "SnapshotSource",
    "bind_risk_inputs",
    "build_coordinator",
]
