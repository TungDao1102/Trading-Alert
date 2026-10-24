"""Live daily-loss service core (Phase 21, plan 21-13; D-03, D-06 to D-09, D-14, RISK-02).

``LiveDayRiskService`` joins four earlier plans into one object a later phase can tick:

* plan 21-05, the pure rules (``src.risk.daily_loss``): the fold, the sticky state, the day-open
  table and the blocked verdicts;
* plan 21-07, ``LiveEquitySource``: the fresh Binance equity read;
* plan 21-08, the adapter's paged ``userTrades`` and ``income`` reads;
* plan 21-09, ``PgDayRiskStore``: the persisted day base, latch and loss components.

Rules this module keeps:

* D-01 / D-08, the day base. A UTC day is opened only from a fresh REST equity read taken
  INSIDE that day, and only when ``day_open_action`` allows it (D-07): a stored row is used as
  is, a rollover from ANY stored earlier day (not only yesterday: an outage of two or more days
  leaves a gap, and an earlier row proves the store is intact, WR-08) or an exposure-free first
  start opens from a fresh read, and a missing state with exposure (or unknown exposure) blocks
  only on a store that never held a day. A failed or stale base
  read keeps the day blocked (NO_TRADE) until a read succeeds; nothing is written meanwhile.
* The clock is re-read AFTER ``equity.refresh()`` returns (D-03). ``refresh`` stamps the reading
  at its start, before the first request, so judging it with the caller's earlier ``now_utc``
  would give a negative age (stale by design). A read taken during a call is therefore never
  judged stale by that same call; only the reading's real age, measured on the injected clock
  after the reads finished, can make it stale. ``base_observed_at_utc`` keeps the stamp.
* D-09, the loss sources and the REST arbiter. ``backfill`` reads ``userTrades`` of every live
  symbol and the ``FUNDING_FEE`` income since 00:00 UTC; the rows become ``REST_USER_TRADES`` /
  ``REST_INCOME`` components. It also reads the whole-account ``REALIZED_PNL``, ``COMMISSION``
  and ``INSURANCE_CLEAR`` income (WR-09): a row of a symbol outside the configured ones, an
  account-level row, or any liquidation clearance fee is a loss the fold cannot see, so the loss
  stays unknown (``last_error_type`` is ``IncomeOutsideConfiguredSymbols``) instead of being
  understated. What stays unchecked: income types that are not losses (rebates, transfers) and the
  equality of the income totals with the folded fills (unverified on mainnet). A fill known to
  the stream and to REST counts once at the most adverse amount (``fold_daily_loss``). The day
  loss is known only after a backfill that completed in the CURRENT backfill generation: a
  failed read leaves it unknown (no retry, no sleep, no default), and the generation is bumped
  by the stream path of plan 21-16 (ACCOUNT_UPDATE, stream gaps, unusable fills), which makes
  the loss unknown again until the next backfill. ``_backfill_generation`` is that private counter.
* D-14, the latch. A newly derived DAILY_STOP is persisted (``latch_stop``) before the verdict is
  returned; a held latch stays DAILY_STOP for the rest of the UTC day, also after a restart and
  whatever the loss does. If the write fails the verdict is still DAILY_STOP (it only reduces
  risk: the caller cancels resting entries) and the stop is held in process and re-written on
  the next call (WR-01); a held latch also answers DAILY_STOP when the components cannot be
  read. A WARNING alert is stamped once per day (``mark_warning_alerted``).
* Fail closed. Any store, reader or equity failure gives a blocked verdict (NO_TRADE,
  UNCERTAIN_ACCOUNT_STATE with a blocked reason), never a default loss or a fresh day. Only the
  exception TYPE name is kept (``last_error_type``), never a message.
* Pitfall 6 and WR-06: a late open of the day (the first read comes after 00:00 UTC) takes the
  equity of that moment, but D033 measures the loss against the equity at the START of the day.
  After a morning loss the moment's equity is the smaller (conservative) base and is kept. After
  a morning GAIN it would be larger than the day-start equity and would raise every threshold by
  the gain, so the base is corrected to ``equity now - the day's net result`` (the most favorable
  amount per fill, ``net_pnl_upper_quote``). That needs the day's loss to be KNOWN when the day
  is opened: a day is not opened (BLOCKED_DAY_BASE_UNAVAILABLE, no equity read) until a backfill
  of the current generation has completed for it, and a stream gap or ACCOUNT_UPDATE before the
  open makes the caller backfill again. ``base_observed_at_utc`` is stored so the lateness is
  visible.
* The funding policy is a required constructor argument with no default (O-2 is the owner's,
  recorded by plan 21-01). The quote asset is a constructor argument.
* Not built here: the operator acknowledgement path for a missing day state with exposure
  (owner item, research Open Question 5), and retention of day rows (owner-open O-1: the service
  never deletes or rewrites a day row). Exposure is never derived here: the caller passes it from
  its REST snapshots and counted reservations, and ``None`` is treated as exposure.

Purity: stdlib and ``src.risk`` only. No ``src.adapters``, ``src.persistence`` or SDK import (the
reader, store and equity source are ports; their results are ``Any`` like the manager's), no
wall clock (every method takes ``now_utc``; the only other time source is the injected ``clock``,
re-read after ``refresh``), no order endpoint and no logging. Not wired in a running process
until Phase 24; the figures quoted in tests are synthetic or demo-observed, not mainnet.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from src.domain.enums import DailyState
from src.risk.daily_loss import (
    BLOCKED_DAY_BASE_UNAVAILABLE,
    BLOCKED_DAY_STATE_MISSING,
    BLOCKED_DAY_STATE_UNREADABLE,
    ComponentKind,
    ComponentSource,
    DayOpenAction,
    DayRiskState,
    DayStateVerdict,
    FundingPolicy,
    LossComponent,
    base_is_inside_day,
    blocked_verdict,
    day_open_action,
    evaluate_day_state,
    fold_daily_loss,
    utc_day_of,
    utc_day_start,
)

FUNDING_INCOME_TYPE = "FUNDING_FEE"
# WR-09: income types read only to prove the folded fills are the whole story. REALIZED_PNL and
# COMMISSION rows of a symbol outside ``symbols`` (or with no symbol) are fills the fold never
# saw; INSURANCE_CLEAR is the liquidation clearance fee, which has no component kind at all.
# Any such row makes the loss unknown (never an understated number); equality of the income
# totals with the folded fills is NOT asserted, its semantics are unverified on mainnet.
REALIZED_PNL_INCOME_TYPE = "REALIZED_PNL"
COMMISSION_INCOME_TYPE = "COMMISSION"
INSURANCE_CLEAR_INCOME_TYPE = "INSURANCE_CLEAR"
CROSS_CHECK_INCOME_TYPES = (
    REALIZED_PNL_INCOME_TYPE,
    COMMISSION_INCOME_TYPE,
    INSURANCE_CLEAR_INCOME_TYPE,
)
OUTSIDE_SYMBOLS_ERROR = "IncomeOutsideConfiguredSymbols"
# Why the stream path makes the loss unknown until the next backfill (plan 21-16): any
# ACCOUNT_UPDATE (FUNDING_FEE included) and every stream gap. Frames sent during a gap are not
# replayed (demo-observed, not mainnet), so a loss computed across a gap is never trusted.
INVALIDATION_REASONS = frozenset({"ACCOUNT_UPDATE", "STREAM_GAP"})
_OK = "OK"


class DayRiskReadPort(Protocol):
    """The two adapter reads ``backfill`` calls (async, REST, read-only, plan 21-08)."""

    async def user_trades_in_window(
        self, *, symbol: str, start_utc: datetime, end_utc: datetime
    ) -> Any: ...

    async def income_in_window(
        self, *, income_type: str, start_utc: datetime, end_utc: datetime
    ) -> Any: ...


class DayRiskStorePort(Protocol):
    """The store methods the service calls (``PgDayRiskStore``, plan 21-09)."""

    def get_day(self, utc_day: date) -> Any: ...

    def has_day(self, utc_day: date) -> Any: ...

    def has_earlier_day(self, utc_day: date) -> Any: ...

    def open_day(self, state: DayRiskState) -> Any: ...

    def latch_stop(self, *, utc_day: date, at_utc: datetime) -> Any: ...

    def mark_warning_alerted(self, *, utc_day: date, at_utc: datetime) -> Any: ...

    def add_components(self, components: Iterable[LossComponent]) -> Any: ...

    def list_components(self, utc_day: date) -> Any: ...


class EquityCheckPort(Protocol):
    """``LiveEquitySource`` as the service sees it (plan 21-07)."""

    async def refresh(self) -> None: ...

    def check(self, *, now_utc: datetime) -> Any: ...


def components_from_user_trade(row: Any) -> tuple[LossComponent, LossComponent]:
    """The two signed components of one ``UserTradeRow``: realized PnL and MINUS commission."""
    key = f"{row.symbol}:{row.order_id}:{row.trade_id}"
    event_time = row.time_utc
    day = utc_day_of(event_time)
    pnl = LossComponent(
        kind=ComponentKind.FILL_PNL,
        source=ComponentSource.REST_USER_TRADES,
        source_key=key,
        amount=row.realized_pnl,
        asset=row.margin_asset,
        event_time_utc=event_time,
        utc_day=day,
    )
    commission = LossComponent(
        kind=ComponentKind.FILL_COMMISSION,
        source=ComponentSource.REST_USER_TRADES,
        source_key=key,
        amount=-row.commission,
        asset=row.commission_asset,
        event_time_utc=event_time,
        utc_day=day,
    )
    return pnl, commission


def components_from_fill(fill: Any, *, quote_asset: str) -> tuple[LossComponent, ...] | None:
    """The two signed components of one stream ``FillEvent``, or None when it is unusable.

    Realized PnL is a quote-asset amount only for a symbol quoted in ``quote_asset`` (USD-M
    single-asset mode, enforced by the equity resolver); any other symbol carries the symbol as
    the asset, so the asset check of ``fold_daily_loss`` makes the loss unknown. Commission is
    MINUS the commission in ``commission_asset``. The key matches the REST row of the same trade
    (``symbol:orderId:tradeId``). None when commission, its asset or realized PnL is missing.
    """
    if fill.commission is None or fill.commission_asset is None or fill.realized_pnl is None:
        return None
    key = f"{fill.symbol}:{fill.order_id}:{fill.exchange_trade_id}"
    event_time = fill.fill_time_utc
    day = utc_day_of(event_time)
    pnl_asset = quote_asset if fill.symbol.endswith(quote_asset) else fill.symbol
    pnl = LossComponent(
        kind=ComponentKind.FILL_PNL,
        source=ComponentSource.USER_DATA_EVENT,
        source_key=key,
        amount=fill.realized_pnl,
        asset=pnl_asset,
        event_time_utc=event_time,
        utc_day=day,
    )
    commission = LossComponent(
        kind=ComponentKind.FILL_COMMISSION,
        source=ComponentSource.USER_DATA_EVENT,
        source_key=key,
        amount=-fill.commission,
        asset=fill.commission_asset,
        event_time_utc=event_time,
        utc_day=day,
    )
    return pnl, commission


def components_from_income(row: Any) -> LossComponent:
    """The FUNDING component of one ``IncomeRow``; any other income type is a ``ValueError``."""
    if row.income_type != FUNDING_INCOME_TYPE:
        raise ValueError(f"only {FUNDING_INCOME_TYPE} income rows are funding components")
    return LossComponent(
        kind=ComponentKind.FUNDING,
        source=ComponentSource.REST_INCOME,
        source_key=f"{row.symbol or 'ACCOUNT'}:{row.tran_id}",
        amount=row.income,
        asset=row.asset,
        event_time_utc=row.time_utc,
        utc_day=utc_day_of(row.time_utc),
    )


class LiveDayRiskService:
    """Opens and rolls the UTC day, keeps its loss, evaluates the sticky D033 state."""

    def __init__(
        self,
        *,
        reader: DayRiskReadPort,
        store: DayRiskStorePort,
        equity: EquityCheckPort,
        clock: Callable[[], datetime],
        symbols: Iterable[str],
        quote_asset: str,
        funding_policy: FundingPolicy,
        parameter_set: dict[str, Any],
    ) -> None:
        ordered = tuple(sorted(set(symbols)))
        if not ordered or any(not isinstance(name, str) or name == "" for name in ordered):
            raise ValueError("symbols must be a non-empty collection of non-empty strings")
        if not isinstance(quote_asset, str) or quote_asset.strip() == "":
            raise ValueError("quote_asset must be a non-empty string")
        if not isinstance(funding_policy, FundingPolicy):
            raise TypeError(
                f"funding_policy must be FundingPolicy, got {type(funding_policy).__name__}"
            )
        if not isinstance(parameter_set, dict):
            raise TypeError(f"parameter_set must be a dict, got {type(parameter_set).__name__}")
        self._reader = reader
        self._store = store
        self._equity = equity
        self._clock = clock
        self._symbols = ordered
        self._quote_asset = quote_asset
        self._funding_policy = funding_policy
        self._parameter_set = parameter_set
        # Plan 21-16 bumps this (ACCOUNT_UPDATE, stream gap, unusable fill): a backfill that
        # started under an older generation never makes the loss known.
        self._backfill_generation = 0
        self._trades_complete_for: tuple[date, int] | None = None
        self._funding_read_ok_for: tuple[date, int] | None = None
        self._last_error_type: str | None = None
        # Days opened by ``evaluate``; ``current_daily_loss_quote`` answers only for these.
        self._evaluated_days: set[date] = set()
        # Days whose newly derived DAILY_STOP could not be written (WR-01): day -> first stamp.
        self._unpersisted_stops: dict[date, datetime] = {}

    @property
    def last_error_type(self) -> str | None:
        """Type name of the last failure (backfill, store or equity); never a message."""
        return self._last_error_type

    # ------------------------------------------------------------------ backfill

    async def backfill(self, *, now_utc: datetime) -> None:
        """Read the day's trades and funding from REST and store them as components (D-09).

        Every symbol (sorted) is read once, then the income; nothing is retried. On success both
        completeness marks are set for this day, unless the generation moved during the reads.
        On any failure both marks are cleared and only the exception type name is kept.
        """
        day = utc_day_of(now_utc)
        start = utc_day_start(day)
        generation = self._backfill_generation
        try:
            components: list[LossComponent] = []
            outside = False
            for symbol in self._symbols:
                trades = await self._reader.user_trades_in_window(
                    symbol=symbol, start_utc=start, end_utc=now_utc
                )
                for trade in trades:
                    components.extend(components_from_user_trade(trade))
            income = await self._reader.income_in_window(
                income_type=FUNDING_INCOME_TYPE, start_utc=start, end_utc=now_utc
            )
            components.extend(components_from_income(row) for row in income)
            for income_type in CROSS_CHECK_INCOME_TYPES:
                rows = await self._reader.income_in_window(
                    income_type=income_type, start_utc=start, end_utc=now_utc
                )
                outside = outside or any(
                    self._is_unfolded_loss_row(row, income_type) for row in rows
                )
            self._store.add_components(tuple(components))
        except Exception as exc:  # noqa: BLE001 - any failed read or write leaves the loss unknown
            self._trades_complete_for = None
            self._funding_read_ok_for = None
            self._last_error_type = type(exc).__name__
            return
        if outside:
            self._trades_complete_for = None
            self._funding_read_ok_for = None
            self._last_error_type = OUTSIDE_SYMBOLS_ERROR
            return
        self._last_error_type = None
        if generation == self._backfill_generation:
            self._trades_complete_for = (day, generation)
            self._funding_read_ok_for = (day, generation)

    def _is_unfolded_loss_row(self, row: Any, requested_type: str) -> bool:
        """True for a cross-check income row the fold of the configured fills cannot account for."""
        if row.income_type != requested_type:
            return False
        if requested_type == INSURANCE_CLEAR_INCOME_TYPE:
            return True
        return row.symbol is None or row.symbol not in self._symbols

    # ------------------------------------------------------------------ the stream path

    def invalidate(self, *, reason: str) -> None:
        """Make the day loss unknown until a backfill completes AFTER this call (D-01, D-09).

        Called for any ACCOUNT_UPDATE (FUNDING_FEE included) and every stream gap (Phase 24 wires
        both). Bumping the generation also defeats a backfill already in flight: it started under
        the older generation, so it does not mark the loss known. The equity source is untouched.
        """
        if reason not in INVALIDATION_REASONS:
            raise ValueError(
                f"reason must be one of {sorted(INVALIDATION_REASONS)}, got {reason!r}"
            )
        self._mark_loss_incomplete()

    def ingest_fill(self, fill: Any) -> None:
        """Add one stream fill to the day loss between backfills; never raises (D-09, D-11).

        An unusable fill (no commission, commission asset or realized PnL) or a fill the store
        cannot write makes the loss unknown until the next backfill. Only the exception type name
        is kept. For the same trade key the most adverse of stream and REST counts once (fold).
        """
        try:
            components = components_from_fill(fill, quote_asset=self._quote_asset)
            if components is None:
                self._mark_loss_incomplete()
                return
            self._store.add_components(components)
        except Exception as exc:  # noqa: BLE001 - the stream router must never see a raise
            self._last_error_type = type(exc).__name__
            self._mark_loss_incomplete()

    def current_daily_loss_quote(self, utc_day: date) -> Decimal | None:
        """The known loss of ``utc_day`` now, or None (fail closed, D-11).

        Known only for a day ``evaluate`` has opened, while a backfill of the CURRENT generation
        completed for it (no invalidation, unusable fill or failed write since). The loss is
        folded from the stored components on each call, so a stream fill added after the last
        evaluate counts. This is the callable plan 21-15's ``make_reserving_save_atomic`` takes
        as ``daily_loss_quote``.

        Freshness limit (review WR-05, OWNER-OPEN): "known" has NO age bound. A loss source the
        stream never reports and that raises no gap (a manual trade in the exchange UI, a symbol
        outside ``symbols``, a dropped liquidation or ADL frame, a half-open socket) leaves the
        loss understated until the next ``backfill``. The equity has the owner bound
        ``account.max_equity_age_ms``; the loss has none because the number is the owner's and is
        not invented here. Until the owner sets a loss-age key, freshness is delegated to the
        Phase 20 feed checks (``stale_feed.max_user_data_silence_ms``) and to the caller, which
        should run ``backfill`` on a schedule and after any stream gap (Phase 24 composition).
        """
        if utc_day not in self._evaluated_days or not self._backfill_is_current(utc_day):
            return None
        try:
            loss = fold_daily_loss(
                components=tuple(self._store.list_components(utc_day)),
                utc_day=utc_day,
                quote_asset=self._quote_asset,
                trades_complete=True,
                funding_read_ok=True,
                funding_policy=self._funding_policy,
            )
        except Exception as exc:  # noqa: BLE001 - an unreadable or conflicting loss is unknown
            self._last_error_type = type(exc).__name__
            return None
        return loss.loss_quote

    def _mark_loss_incomplete(self) -> None:
        self._backfill_generation += 1
        self._trades_complete_for = None
        self._funding_read_ok_for = None

    # ------------------------------------------------------------------ the day

    def _blocked(self, day: date, reason: str, exc: BaseException | None = None) -> DayStateVerdict:
        if exc is not None:
            self._last_error_type = type(exc).__name__
        return blocked_verdict(utc_day=day, blocked_reason=reason)

    async def ensure_day(
        self, *, now_utc: datetime, exposure: bool | None
    ) -> DayRiskState | DayStateVerdict:
        """Today's persisted state, opening the day from a fresh REST base when allowed.

        Returns the ``DayRiskState`` to use, or a blocked ``DayStateVerdict``. The service never
        derives exposure: ``None`` means unknown and is treated as exposure (D-07).
        """
        day = utc_day_of(now_utc)
        try:
            today = self._store.get_day(day)
            earlier_present = False if today is not None else bool(self._store.has_earlier_day(day))
        except Exception as exc:  # noqa: BLE001 - an unreadable store is never a fresh day
            return self._blocked(day, BLOCKED_DAY_STATE_UNREADABLE, exc)
        action = day_open_action(
            today=today,
            earlier_day_present=earlier_present,
            exposure=exposure,
            store_readable=True,
        )
        if action is DayOpenAction.USE_STORED:
            assert isinstance(today, DayRiskState)
            return today
        if action is DayOpenAction.BLOCKED_MISSING_STATE:
            return self._blocked(day, BLOCKED_DAY_STATE_MISSING)
        if action is not DayOpenAction.OPEN_FROM_FRESH_BASE:
            return self._blocked(day, BLOCKED_DAY_STATE_UNREADABLE)
        return await self._open_from_fresh_base(day)

    def _known_net_pnl(self, day: date) -> Decimal | None:
        """The day's net result (favorable-most, positive = gain) or None when it is unknown."""
        if not self._backfill_is_current(day):
            return None
        try:
            loss = fold_daily_loss(
                components=tuple(self._store.list_components(day)),
                utc_day=day,
                quote_asset=self._quote_asset,
                trades_complete=True,
                funding_read_ok=True,
                funding_policy=self._funding_policy,
            )
        except Exception as exc:  # noqa: BLE001 - an unreadable or conflicting loss is unknown
            self._last_error_type = type(exc).__name__
            return None
        return loss.net_pnl_upper_quote

    async def _open_from_fresh_base(self, day: date) -> DayRiskState | DayStateVerdict:
        if not self._backfill_is_current(day):
            return self._blocked(day, BLOCKED_DAY_BASE_UNAVAILABLE)  # WR-06: no net result yet
        try:
            await self._equity.refresh()
            # Re-read AFTER refresh: the reading is stamped at the start of refresh(), so
            # judging it with the caller's earlier now_utc would give a negative age (stale).
            checked_at = self._clock()
            utc_day_of(checked_at)  # UTC-aware datetime or ValueError/TypeError
            check = self._equity.check(now_utc=checked_at)
            if check.reason_code != _OK or check.equity is None or check.observed_at_utc is None:
                return self._blocked(day, BLOCKED_DAY_BASE_UNAVAILABLE)
            if not base_is_inside_day(utc_day=day, observed_at_utc=check.observed_at_utc):
                return self._blocked(day, BLOCKED_DAY_BASE_UNAVAILABLE)
            # WR-06: read AFTER the equity refresh, so a generation bump during it is seen.
            net_pnl = self._known_net_pnl(day)
            if net_pnl is None:
                return self._blocked(day, BLOCKED_DAY_BASE_UNAVAILABLE)
            base = check.equity - net_pnl if net_pnl > 0 else check.equity
            if base <= 0:
                return self._blocked(day, BLOCKED_DAY_BASE_UNAVAILABLE)
            state = DayRiskState(
                utc_day=day,
                equity_at_day_start=base,
                base_observed_at_utc=check.observed_at_utc,
            )
        except Exception as exc:  # noqa: BLE001 - no usable base, the day stays blocked
            return self._blocked(day, BLOCKED_DAY_BASE_UNAVAILABLE, exc)
        try:
            stored = self._store.open_day(state)
        except Exception as exc:  # noqa: BLE001 - a day that cannot be stored is not opened
            return self._blocked(day, BLOCKED_DAY_STATE_UNREADABLE, exc)
        if not isinstance(stored, DayRiskState):
            return self._blocked(day, BLOCKED_DAY_STATE_UNREADABLE)
        return stored

    # ------------------------------------------------------------------ evaluate

    async def evaluate(self, *, now_utc: datetime, exposure: bool | None) -> DayStateVerdict:
        """The day's verdict: persisted latch first, then thresholds against the day-start base.

        A held latch answers DAILY_STOP whatever else fails (WR-01): an unreadable components
        read leaves the loss unknown but keeps the stop, and a stop whose latch write failed
        still answers DAILY_STOP (risk-reducing: the caller cancels resting entries) and is held
        in process until the write succeeds.
        """
        opened = await self.ensure_day(now_utc=now_utc, exposure=exposure)
        if isinstance(opened, DayStateVerdict):
            return opened
        day = opened.utc_day
        self._evaluated_days.add(day)
        opened = self._apply_unpersisted_stop(opened)
        latched = opened.stop_latched_at_utc is not None
        stored_components: tuple[LossComponent, ...] | None
        try:
            stored_components = tuple(self._store.list_components(day))
        except Exception as exc:  # noqa: BLE001 - unreadable components are an unknown loss
            if not latched:
                return self._blocked(day, BLOCKED_DAY_STATE_UNREADABLE, exc)
            self._last_error_type = type(exc).__name__
            stored_components = None  # the held latch still answers DAILY_STOP below
        known = stored_components is not None and self._backfill_is_current(day)
        try:
            loss = fold_daily_loss(
                components=stored_components or (),
                utc_day=day,
                quote_asset=self._quote_asset,
                trades_complete=known,
                funding_read_ok=known,
                funding_policy=self._funding_policy,
            )
        except (TypeError, ValueError) as exc:
            # Conflicting duplicates or a foreign-day component: the loss is unknown, but a held
            # latch must still answer DAILY_STOP, so fold again with the unknown flags.
            self._last_error_type = type(exc).__name__
            loss = fold_daily_loss(
                components=(),
                utc_day=day,
                quote_asset=self._quote_asset,
                trades_complete=False,
                funding_read_ok=False,
                funding_policy=self._funding_policy,
            )
        verdict = evaluate_day_state(day=opened, loss=loss, parameter_set=self._parameter_set)
        if verdict.latch_now:
            try:
                self._store.latch_stop(utc_day=day, at_utc=now_utc)
            except Exception as exc:  # noqa: BLE001 - the stop is kept, the write is retried
                # WR-01: the verdict stays DAILY_STOP (the caller cancels resting entries, which
                # only reduces risk) and the stop is held in process until the write succeeds.
                self._last_error_type = type(exc).__name__
                self._unpersisted_stops[day] = now_utc
        if DailyState.WARNING in verdict.alerts_due:
            try:
                self._store.mark_warning_alerted(utc_day=day, at_utc=now_utc)
            except Exception as exc:  # noqa: BLE001 - an unstamped alert is dropped, not repeated
                self._last_error_type = type(exc).__name__
                remaining = tuple(a for a in verdict.alerts_due if a is not DailyState.WARNING)
                verdict = dataclasses.replace(verdict, alerts_due=remaining)
        return verdict

    def _apply_unpersisted_stop(self, opened: DayRiskState) -> DayRiskState:
        """Re-try a latch write that failed earlier; hold the stop in process meanwhile (WR-01)."""
        stamp = self._unpersisted_stops.get(opened.utc_day)
        if stamp is None:
            return opened
        if opened.stop_latched_at_utc is not None:
            del self._unpersisted_stops[opened.utc_day]
            return opened
        try:
            self._store.latch_stop(utc_day=opened.utc_day, at_utc=stamp)
        except Exception as exc:  # noqa: BLE001 - still unpersisted, still a stop
            self._last_error_type = type(exc).__name__
        else:
            del self._unpersisted_stops[opened.utc_day]
        return dataclasses.replace(opened, stop_latched_at_utc=stamp)

    def _backfill_is_current(self, day: date) -> bool:
        """True when both completeness marks belong to ``day`` and the current generation."""
        expected = (day, self._backfill_generation)
        return self._trades_complete_for == expected and self._funding_read_ok_for == expected


__all__ = [
    "CROSS_CHECK_INCOME_TYPES",
    "FUNDING_INCOME_TYPE",
    "INVALIDATION_REASONS",
    "OUTSIDE_SYMBOLS_ERROR",
    "DayRiskReadPort",
    "DayRiskStorePort",
    "EquityCheckPort",
    "LiveDayRiskService",
    "components_from_fill",
    "components_from_income",
    "components_from_user_trade",
]
