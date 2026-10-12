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
own lock.
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
from src.domain.approval import Approval
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper.freeze import StreamEpoch
from src.paper.live_minutes import LiveMinutePoller, LiveMinuteSource, PublicMinuteFeed
from src.paper.loop import BarOutcome
from src.paper.pipeline import PipelineResult
from src.paper.runtime_config import RuntimeConfig
from src.paper.shadow import (
    Mode,
    ShadowApprovalBook,
    ShadowSendOutcome,
    ShadowStores,
    make_shadow_reply_fn,
    require_shadow,
    send_shadow_alert,
)
from src.paper.shadow_confirm import (
    CONFIRM_TTL_SECONDS_DEFAULT,
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
    Reservation,
    ReservationBasis,
    ReservationStores,
    ShadowLedger,
    ShadowReservations,
)
from src.risk.types import ConstraintSnapshot, OpenPosition

log = structlog.get_logger()

_MINUTE: Final = timedelta(minutes=1)

# Journal event of a filled simulated position reaching its exit (plan 16-31). Written under the
# correlation of the approval (`shadow-confirm:<approval_id>`) like the reservation events of
# plan 16-23; none of the fixed-list consumers (terminal confirm events, reservation events)
# lists it. Its id and payload are pure functions of the position's data.
EVENT_SHADOW_POSITION_CLOSED: Final = "SHADOW_POSITION_CLOSED"

# Q-L `separate-bot` (decisions/16-DEC-Q-L.md): the SHADOW bot is its own Telegram bot, so exactly
# one process polls getUpdates for its token. Logged at start and when Telegram reports a
# Conflict. The token itself is never logged.
BOT_TOKEN_RULE: Final = (
    "separate-bot: exactly one getUpdates consumer per bot token (16-DEC-Q-L, RUNBOOK 20.3)"
)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class ShadowRuntimeError(RuntimeError):
    """The SHADOW chain cannot continue safely (fail closed): the message is this module's own."""


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
        self._mode = mode
        self._stores = stores
        self._chat_id = chat_id
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
        self._poll_interval = minute_poll_interval_seconds
        self._application_factory = application_factory
        self._application: Any | None = None
        self._telegram_errors: dict[str, int] = {}
        self._conflict_logged = False

        self._book = ShadowApprovalBook(stores, clock=clock)
        self._reservations = ShadowReservations(ledger, stores, basis_for=self._basis_for)
        self._confirm = ConfirmBook(
            stores,
            clock=clock,
            ttl_seconds=confirm_ttl_seconds,
            mode=mode,
            mark_price=self._mark_price,
            on_confirmed=self._on_confirmed,
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
        is `authorized_chat_gate` (D-16); user-id authorization is Phase 23.
        """
        return {
            "authorized_chat_id": self._chat_id,
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
        now = self._clock()
        await self._refresh_mark(signal.symbol, now)
        reasons = [signal.setup_type]
        if outcome.regime:
            reasons.append(f"REGIME_{outcome.regime}")
        return await send_shadow_alert(
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
        """Give every reserved or filled plan without a driver one (idempotent)."""
        with self._lock:
            for reservation in (
                *self._reservations.pending_reservations(),
                *self._reservations.positions(),
            ):
                if reservation.key in self._positions:
                    continue
                self._positions[reservation.key] = self._build_position(reservation)

    def _build_position(self, reservation: Reservation) -> _Position:
        context = self._plans.get(reservation.plan_hash)
        if context is None:
            raise ShadowRuntimeError(
                f"no plan context for reservation {reservation.key}: the plan was not alerted by "
                "this process"
            )
        approval = self._stores.get_approval(reservation.approval_id)
        eligibility = eligibility_start_for(
            signal_close_utc=reservation.signal_close_utc,
            plan_expiry_utc=reservation.plan_expiry_utc,
            confirm_outcome="CONFIRMED",
            confirmed_at_utc=reservation.confirmed_at_utc,
            approved_at_utc=None if approval is None else approval.acted_at_utc,
        )
        driver = ShadowFillDriver(
            cost_model=self._fill.cost_model,
            constraint_snapshot=context.constraints,
            strategy_version=self._fill.strategy_version,
            parameter_set_hash=self._fill.parameter_set_hash,
            constraints_extrapolated=False,
        )
        opened = driver.open_confirmed(context.outcome, eligibility)
        if not opened.opened:
            raise ShadowRuntimeError(
                f"the confirmed plan {reservation.key} cannot rest as a simulated plan: "
                f"{opened.reason_code}"
            )
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
        tolerance = FUNDING_MAX_CADENCE + FUNDING_JITTER
        start = position.driver.eligibility_start_utc - 2 * tolerance
        ticks = await self._public.funding_rate(
            position.reservation.symbol,
            start_ms=_to_ms(start),
            end_ms=_to_ms(until),
            limit=1000,
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
        self._reservations.release_expired(now)
        self._confirm.expire_due(now)

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

    async def run_poller(self, stop: asyncio.Event) -> None:
        """Poll every `minute_poll_interval_seconds` until `stop` is set.

        A poll error ends the loop by propagating, so the caller can fail closed (a feed that
        cannot be read leaves the simulated positions unmanaged).
        """
        while not stop.is_set():
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

    async def start(self) -> None:
        """Start the Telegram application in this event loop (initialize, start, polling).

        Logs the one-consumer-per-token rule first (Q-L). No webhook is configured: getUpdates
        and a webhook are exclusive (research G6). Without an application factory the chain only
        sends (rehearsal and tests).
        """
        log.info("paper.shadow.bot_token_rule", rule=BOT_TOKEN_RULE)
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
    bot: TelegramTextBot | None = None
    confirm_ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


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
        )
    except ValueError as exc:
        raise ShadowRuntimeError(f"the SHADOW chain cannot be built: {exc}") from exc


__all__ = [
    "BOT_TOKEN_RULE",
    "EVENT_SHADOW_POSITION_CLOSED",
    "FillContext",
    "LedgerRiskInputs",
    "PositionView",
    "ShadowCoordinator",
    "ShadowPublicFeed",
    "ShadowRuntimeError",
    "ShadowRuntimeStores",
    "ShadowWiring",
    "SnapshotSource",
    "bind_risk_inputs",
    "build_coordinator",
]
