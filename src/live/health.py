"""The health producer of the live process (plan 24-22; D-26, D056, D058, research C-3, OPS-04).

`enable()` needs a verdict over all ten `ALL_CHECK_NAMES` results. Three of them describe a market
feed the live process does not own, so 24-01 Q5 gave them live-process meanings:

=========================  ==================================================================
check                      meaning in the live process
=========================  ==================================================================
market_feed_freshness      age of the REST mark price (`premiumIndex`) of the tracked symbols;
                           the OLDEST symbol decides, a missing one fails (D058)
ws_connection_state        the user-data stream is LIVE
user_data_stream_state     the stream is LIVE and its divergence source is not halted
last_closed_candle_time    DEGRADED "not applicable" (no candle feed in this process)
rest_error_rate            errors / calls of the REST-calling live tasks since the last tick
reconciliation_drift       the latest reconcile tick compared and agreed
db_writes                  age of the latest successful tracked store write
telegram_delivery          outcome of the latest real send (startup probe, alert drain)
unprotected_positions      ENTRY_WITHOUT_PROTECTIVE divergences of the last compared tick
orphaned_orders            ORPHAN_PROTECTIVE divergences of the last compared tick
=========================  ==================================================================

`health_tick_once` is the scheduler task body: it produces the ten results, judges them with
`run_health_checks(mode=..., demo_degraded_allowed=...)` (D056: in LIVE a DEGRADED result is never
OK, in DEMO only with the explicit flag, which can never be given to a LIVE producer), and journals
each result as `HEALTH_CHECK` plus one `HEALTH_VERDICT`, all carrying the mode, the Python version
and the application revision (OPS-04, D-31). R-25 (D-11, D-13): the `HEALTH_VERDICT` row is written
on every tick (each successful journal write refreshes `DbWriteTracker`, so an idle process keeps
the `db_writes` check fresh), while the ten `HEALTH_CHECK` rows are written on the first tick of a
producer and afterwards only for a check whose status differs from the status last journaled.

Owner numbers NOT set (recorded for the orchestrator): there is no limits key for the maximum REST
error rate or for the age of the latest database write, so `LiveHealthThresholds` takes them as
required arguments and has no default. The mark age and the clock skew come from ratified keys.

A tick never messages the owner: `telegram_delivery` reads the outcome of sends that happen anyway.
This module reads no clock (a clock is injected where one is needed) and calls no exchange.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog

from src.adapters.binance_client import Environment
from src.adapters.binance_limits import BinanceLimits
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.live.feeds import STATE_LIVE, LivenessSource, MarkBook
from src.ops.alerts import SendReport
from src.ops.health import (
    CHECK_LAST_CLOSED_CANDLE_TIME,
    STATUS_FAIL,
    STATUS_PASS,
    HealthCheckResult,
    HealthRuntimeMode,
    HealthVerdict,
    JournalLike,
    NotifierLike,
    check_db_writes,
    check_market_feed_freshness,
    check_not_applicable,
    check_orphaned_orders,
    check_reconciliation_drift,
    check_rest_error_rate,
    check_telegram_delivery,
    check_telegram_delivery_observed,
    check_unprotected_positions,
    check_user_data_stream_state,
    check_ws_connection_state,
    health_check_event,
    run_health_checks,
)
from src.reconcile.feed_freshness import clock_skew_from_drift
from src.reconcile.loop import TICK_COMPARED, TickReport

log = structlog.get_logger(__name__)

#: The detail of the DEGRADED candle check (fixed project text).
CANDLE_NOT_APPLICABLE_DETAIL = "not applicable: the live process has no candle feed"
#: The `HEALTH_VERDICT` journal event of one tick.
VERDICT_EVENT_TYPE = "HEALTH_VERDICT"

Record = Callable[[JournalEvent], Awaitable[None]]
Diagnostics = Callable[[], Mapping[str, str]]


class _DiscardJournal:
    """The probes journal through this; the tick journals the enriched events itself."""

    def record(self, event: Any) -> None:
        del event


# --------------------------------------------------------------------------- #
# Observers: the small state the ten checks read.
# --------------------------------------------------------------------------- #


class RestErrorCounter:
    """Calls and errors of the REST-calling live tasks, counted per health window.

    `wrap` decorates an async task body: a normal return counts one call, an exception counts one
    call and one error and is re-raised unchanged (cancellation counts nothing). `take_window`
    returns `(errors, total)` since the previous call and starts a new window, so the health tick
    judges one window of exactly one interval.
    """

    def __init__(self) -> None:
        self._errors = 0
        self._total = 0

    def record_ok(self) -> None:
        self._total += 1

    def record_error(self) -> None:
        self._errors += 1
        self._total += 1

    def wrap[**P, T](self, fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        async def counted(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                value = await fn(*args, **kwargs)
            except Exception:
                self.record_error()
                raise
            self.record_ok()
            return value

        return counted

    def take_window(self) -> tuple[int, int]:
        window = (self._errors, self._total)
        self._errors = 0
        self._total = 0
        return window


class DbWriteTracker:
    """The latest successful tracked store write; a failed latest write clears the stamp.

    `track` decorates an async store write (the `StoreExecutor` writer, the journal recorder).
    The clock is injected: this module reads no wall clock.
    """

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock
        self._last_ok: datetime | None = None
        self._last_failed = False

    def note_ok(self) -> None:
        self._last_ok = self._clock()
        self._last_failed = False

    def note_failure(self) -> None:
        self._last_failed = True

    @property
    def last_ok_utc(self) -> datetime | None:
        """The time of the latest successful write, None before one or after a failed one."""
        return None if self._last_failed else self._last_ok

    def track[**P, T](self, fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        async def tracked(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                value = await fn(*args, **kwargs)
            except Exception:
                self.note_failure()
                raise
            self.note_ok()
            return value

        return tracked


class ReconcileObserver:
    """The latest reconcile tick and the latest tick that actually compared."""

    def __init__(self) -> None:
        self._latest: TickReport | None = None
        self._compared: TickReport | None = None

    def note(self, report: TickReport) -> None:
        self._latest = report
        if report.outcome == TICK_COMPARED:
            self._compared = report

    @property
    def latest(self) -> TickReport | None:
        return self._latest

    @property
    def last_compared(self) -> TickReport | None:
        return self._compared

    @property
    def reconciled(self) -> bool:
        """The latest tick compared and the local and exchange views agreed."""
        latest = self._latest
        return latest is not None and latest.outcome == TICK_COMPARED and latest.agreement is True


class TelegramDeliveryObserver:
    """The outcome of the latest real Telegram send; None until one was observed."""

    def __init__(self) -> None:
        self._last_ok: bool | None = None

    @property
    def last_ok(self) -> bool | None:
        return self._last_ok

    def note(self, *, ok: bool) -> None:
        self._last_ok = ok

    def note_send_report(self, report: SendReport) -> None:
        """A drain with a failed send is a failure; one with only deliveries is a success."""
        if report.failed > 0:
            self._last_ok = False
        elif report.delivered > 0:
            self._last_ok = True

    async def probe(
        self,
        *,
        notifier: NotifierLike | None,
        chat_id: Any,
        probe_text: str,
        now_utc: datetime,
        journal: JournalLike,
    ) -> HealthCheckResult:
        """Send ONE message (the startup probe) and remember its outcome.

        Never called by a health tick: a tick must not message the owner.
        """
        result = await check_telegram_delivery(
            notifier=notifier,
            chat_id=chat_id,
            probe_text=probe_text,
            now_utc=now_utc,
            journal=journal,
        )
        self._last_ok = result.status == STATUS_PASS
        return result


# --------------------------------------------------------------------------- #
# Thresholds and the producer.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class LiveHealthThresholds:
    """The numbers the checks compare with (every field required, no default).

    `mark_price_max_age` and `mark_clock_skew` come from ratified keys (`from_limits`).
    `rest_max_error_rate` and `db_write_max_age` have no limits key yet: the composition passes an
    owner-confirmed value (open item for the orchestrator, see the module docstring).
    """

    mark_price_max_age: timedelta
    mark_clock_skew: timedelta
    rest_max_error_rate: Decimal
    db_write_max_age: timedelta

    def __post_init__(self) -> None:
        if self.mark_price_max_age <= timedelta(0):
            raise ValueError("mark_price_max_age must be positive")
        if self.mark_clock_skew < timedelta(0):
            raise ValueError("mark_clock_skew must not be negative")
        if not isinstance(self.rest_max_error_rate, Decimal) or not (
            Decimal(0) <= self.rest_max_error_rate <= Decimal(1)
        ):
            raise ValueError("rest_max_error_rate must be a Decimal between 0 and 1")
        if self.db_write_max_age <= timedelta(0):
            raise ValueError("db_write_max_age must be positive")

    @classmethod
    def from_limits(
        cls,
        execution_limits: ExecutionLimits,
        binance_limits: BinanceLimits,
        *,
        rest_max_error_rate: Decimal,
        db_write_max_age: timedelta,
    ) -> LiveHealthThresholds:
        """Mark age from `stale_feed.max_mark_price_age_ms`, skew from the ratified drift limits.

        Raises:
            ExecutionLimitsNotConfigured: `stale_feed.max_mark_price_age_ms` is unset.
        """
        mark_ms = execution_limits.stale_feed_max_mark_price_age_ms
        if mark_ms is None:
            raise ExecutionLimitsNotConfigured(("stale_feed.max_mark_price_age_ms",))
        return cls(
            mark_price_max_age=timedelta(milliseconds=mark_ms),
            mark_clock_skew=clock_skew_from_drift(binance_limits.drift),
            rest_max_error_rate=rest_max_error_rate,
            db_write_max_age=db_write_max_age,
        )


class LiveHealthProducer:
    """Produces the ten results and the D056 verdict from the composed observers."""

    def __init__(
        self,
        *,
        mode: Environment | HealthRuntimeMode | str,
        demo_degraded_allowed: bool,
        symbols: Iterable[str],
        marks: MarkBook,
        stream: LivenessSource,
        rest_errors: RestErrorCounter,
        reconcile: ReconcileObserver,
        db_writes: DbWriteTracker,
        telegram: TelegramDeliveryObserver,
        thresholds: LiveHealthThresholds,
        stream_halted_reason: Callable[[], str | None] | None = None,
    ) -> None:
        resolved = HealthRuntimeMode(mode)  # DEMO or LIVE only; TESTNET and anything else raise
        if not isinstance(demo_degraded_allowed, bool):
            raise TypeError("demo_degraded_allowed must be a bool")
        if demo_degraded_allowed and resolved is not HealthRuntimeMode.DEMO:
            raise ValueError("demo_degraded_allowed can only be set in DEMO mode (D056)")
        self._mode = resolved
        self._demo_degraded_allowed = demo_degraded_allowed
        self._symbols = tuple(dict.fromkeys(symbols))
        self._marks = marks
        self._stream = stream
        self._stream_halted = stream_halted_reason
        self._rest = rest_errors
        self._reconcile = reconcile
        self._db = db_writes
        self._telegram = telegram
        self._thresholds = thresholds
        self._latest: HealthVerdict | None = None
        # R-25: the status last JOURNALED per check (empty at construction); advanced only after
        # that check's row was written, so a failed write is retried on the next tick.
        self._journaled_status: dict[str, str] = {}

    @property
    def mode(self) -> HealthRuntimeMode:
        return self._mode

    @property
    def demo_degraded_allowed(self) -> bool:
        return self._demo_degraded_allowed

    @property
    def latest_verdict(self) -> HealthVerdict | None:
        """The verdict of the latest `health_tick_once`, None before the first tick."""
        return self._latest

    def _mark_reference_time(self, now_utc: datetime) -> datetime | None:
        """The time the mark-price check judges: the OLDEST tracked reading, None if any is missing.

        A reading ahead of now by more than the ratified skew is returned as it is (the check then
        fails it); one ahead within the skew counts as now.
        """
        if not self._symbols:
            return None
        oldest: datetime | None = None
        skew = self._thresholds.mark_clock_skew
        for symbol in self._symbols:
            reading = self._marks.reading(symbol)
            if reading is None:
                return None
            seen = reading.exchange_time_utc
            if seen - now_utc > skew:
                return seen
            if oldest is None or seen < oldest:
                oldest = seen
        if oldest is not None and oldest > now_utc:
            return now_utc
        return oldest

    def produce(self, *, now_utc: datetime) -> list[HealthCheckResult]:
        """The ten results in `ALL_CHECK_NAMES` order. Consumes the REST error window."""
        journal = _DiscardJournal()
        stream_live = self._stream.liveness().state == STATE_LIVE
        halted = self._stream_halted is not None and self._stream_halted() is not None
        errors, total = self._rest.take_window()
        compared = self._reconcile.last_compared
        divergences = () if compared is None else compared.divergences
        return [
            check_market_feed_freshness(
                last_market_event_at_utc=self._mark_reference_time(now_utc),
                now_utc=now_utc,
                staleness_threshold=self._thresholds.mark_price_max_age,
                journal=journal,
            ),
            check_not_applicable(
                check_name=CHECK_LAST_CLOSED_CANDLE_TIME,
                detail=CANDLE_NOT_APPLICABLE_DETAIL,
                now_utc=now_utc,
                journal=journal,
            ),
            check_ws_connection_state(connected=stream_live, now_utc=now_utc, journal=journal),
            check_user_data_stream_state(
                connected=stream_live and not halted, now_utc=now_utc, journal=journal
            ),
            check_rest_error_rate(
                error_count=errors,
                total_count=total,
                max_error_rate=self._thresholds.rest_max_error_rate,
                now_utc=now_utc,
                journal=journal,
            ),
            check_reconciliation_drift(
                positions_reconciled=self._reconcile.reconciled, now_utc=now_utc, journal=journal
            ),
            check_db_writes(
                last_db_write_at_utc=self._db.last_ok_utc,
                now_utc=now_utc,
                staleness_threshold=self._thresholds.db_write_max_age,
                journal=journal,
            ),
            check_telegram_delivery_observed(
                last_delivery_ok=self._telegram.last_ok, now_utc=now_utc, journal=journal
            ),
            check_unprotected_positions(divergences=divergences, now_utc=now_utc, journal=journal),
            check_orphaned_orders(divergences=divergences, now_utc=now_utc, journal=journal),
        ]

    def verdict(self, results: list[HealthCheckResult]) -> HealthVerdict:
        """The D056 verdict of `results` for this producer's mode and flag."""
        return run_health_checks(
            results=results,
            mode=self._mode,
            demo_degraded_allowed=self._demo_degraded_allowed,
        )


# --------------------------------------------------------------------------- #
# The scheduler task body.
# --------------------------------------------------------------------------- #


def _default_diagnostics() -> Mapping[str, str]:
    # Imported on use: the runtime module composes this one, not the reverse.
    from src.live.runtime import diagnostic_payload

    return diagnostic_payload()


def _verdict_event(
    verdict: HealthVerdict,
    now_utc: datetime,
    diagnostics: Mapping[str, str],
) -> JournalEvent:
    document: dict[str, Any] = {
        "is_no_trade": verdict.is_no_trade,
        "reason_code": verdict.reason_code,
        "mode": None if verdict.mode is None else verdict.mode.value,
        "demo_degraded_allowed": verdict.demo_degraded_allowed,
        "degraded": list(verdict.degraded_names),
        "failing": [r.check_name for r in verdict.results if r.status == STATUS_FAIL],
    }
    for key, value in diagnostics.items():
        document.setdefault(key, value)
    payload_json = json.dumps(document, separators=(",", ":"))
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="health_verdict",
            event_type=VERDICT_EVENT_TYPE,
            entity_id="live_health",
            occurred_at_utc=now_utc,
            payload_json=payload_json,
        ),
        occurred_at_utc=now_utc,
        event_type=VERDICT_EVENT_TYPE,
        entity_type="HealthVerdict",
        entity_id="live_health",
        correlation_id="execution_health",
        payload_json=payload_json,
    )


async def health_tick_once(
    producer: LiveHealthProducer,
    *,
    now_utc: datetime,
    record: Record,
    diagnostics: Diagnostics | None = None,
) -> HealthVerdict:
    """One health tick: produce, judge, remember, then journal the changed results and the verdict.

    The verdict is stored on the producer BEFORE anything is written, so a journal failure
    (which propagates to the scheduler, recorded by class name) never hides a RED reading.
    R-25: a `HEALTH_CHECK` row is journaled only on the producer's first tick or when that
    check's status differs from the one last journaled (a failed write does not count as
    journaled); the `HEALTH_VERDICT` row is journaled on every tick.
    `diagnostics` defaults to `src.live.runtime.diagnostic_payload` (Python version and
    application revision, OPS-04, D-31).
    """
    results = producer.produce(now_utc=now_utc)
    verdict = producer.verdict(results)
    producer._latest = verdict
    diag = dict((diagnostics or _default_diagnostics)())
    extra: dict[str, str | bool] = {
        **diag,
        "mode": producer.mode.value,
        "demo_degraded_allowed": producer.demo_degraded_allowed,
    }
    for result in results:
        if producer._journaled_status.get(result.check_name) == result.status:
            continue
        await record(health_check_event(result, extra=extra))
        producer._journaled_status[result.check_name] = result.status
    await record(_verdict_event(verdict, now_utc, diag))
    if verdict.is_no_trade:
        log.warning(
            "live.health.not_ok",
            failing=[r.check_name for r in results if r.status == STATUS_FAIL],
        )
    return verdict


__all__ = [
    "CANDLE_NOT_APPLICABLE_DETAIL",
    "VERDICT_EVENT_TYPE",
    "DbWriteTracker",
    "LiveHealthProducer",
    "LiveHealthThresholds",
    "ReconcileObserver",
    "RestErrorCounter",
    "TelegramDeliveryObserver",
    "health_tick_once",
]
