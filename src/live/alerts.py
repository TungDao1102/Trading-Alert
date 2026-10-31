"""The operator alert path of the live process (plan 24-13; D-07, T-05, 20-DEFERRED).

Phases 20 to 23 built the pieces: a journal-first sink, a Telegram sender with a bounded MESSAGE
retry, the SAFE_MODE observer, the plain-word texts and the producers (the manager, the protection
coordinator, the emergency closer, the daily-state enforcement, the REST gate hook). Nothing
constructed them for a running process. `build_alerts` does, once, and the bundle it returns is
the only alert wiring of the live composition:

- ONE deque shared by `JournalFirstAlertSink(queue=q)` and `TelegramAlertSender(queue=q)`: what the
  sink journals and queues, the sender drains. No new queue, sender or retry is written here.
- `safe_mode_observer` is the `on_enter` of the `SafeModeController`; `sink` is the alert sink of
  `LivePlacementContext.alert_sink`, the protection coordinator, the emergency closer and the
  daily-state producers; `gate_alert` is the `on_gate_alert` of `build_exchange` (it receives a
  `GateAlert`, never the gate's text).
- `drain_once` is the body of the scheduler task that sends what is queued.
- `requeue_at_start` queues, once, the journaled alerts that have no delivery row, before the bot
  starts; the read of those rows belongs to the composition (src/ops/alerts.py).

An unset `alerts.dedupe_window_ms` refuses the build with `ExecutionLimitsNotConfigured` naming the
key (the sink's own refusal). The rehearsal sink of the demo script is never used here.

Known limits (recorded for the phase deferred list, 24-DEFERRED):

- The sink journals synchronously on the calling thread. Alerts are rare and the journal-first
  rule needs the row written before the message is queued, so this is deliberate; a slow journal
  delays the producer that alerts, which already treats an alert as best effort.
- W8 (20-VERIFICATION): one alert is raised when a REST gate pause or ban is entered and it names
  the deadline. A repeated alert during a long skip needs an owner number (a re-alert interval)
  and is NOT built. The sink's dedupe window may also suppress a ban that is extended inside it.
- WR-C6: a CRITICAL alert whose send failed is journaled `ALERT_SEND_FAILED` and is not queued
  again in the process; only a restart re-queues it. Unchanged here.

The module reads no clock: the clock for the gate hook is injected.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.execution.execution_limits import ExecutionLimits
from src.live.exchange import GateAlert
from src.ops.alerts import (
    AlertTextBot,
    JournalFirstAlertSink,
    OperationalAlert,
    RequeueReport,
    SafeModeAlertObserver,
    SendReport,
    TelegramAlertSender,
)
from src.ops.spill import LocalSpill

SleepFn = Callable[[float], Awaitable[None]]
Clock = Callable[[], datetime]


class AlertsAlreadyRequeued(RuntimeError):  # noqa: N818 - a composition error, not an exception family
    """`requeue_at_start` was called twice for one bundle (the restart re-queue runs once)."""


@dataclass(frozen=True, kw_only=True)
class AlertBundle:
    """The alert objects of the live process (every field required)."""

    queue: deque[OperationalAlert]
    sink: JournalFirstAlertSink
    sender: TelegramAlertSender
    safe_mode_observer: SafeModeAlertObserver
    gate_alert: Callable[[GateAlert], None]
    _requeued: list[bool] = field(default_factory=list, repr=False, compare=False)


def build_alerts(
    *,
    journal: Any,
    spill: LocalSpill | None,
    limits: ExecutionLimits,
    bot: AlertTextBot,
    chat_id: int | str,
    sleep: SleepFn,
    clock: Clock,
) -> AlertBundle:
    """Build the sink, the sender, the SAFE_MODE observer and the gate hook over one queue.

    Raises:
        ExecutionLimitsNotConfigured: `alerts.dedupe_window_ms` is unset (the sink refuses).
        TypeError: `clock` is not callable.
    """
    if not callable(clock):
        raise TypeError("clock must be callable")
    queue: deque[OperationalAlert] = deque()
    sink = JournalFirstAlertSink(journal=journal, spill=spill, limits=limits, queue=queue)
    sender = TelegramAlertSender(
        bot=bot,
        chat_id=chat_id,
        journal=journal,
        spill=spill,
        sleep=sleep,
        queue=queue,
    )

    def gate_alert(alert: GateAlert) -> None:
        sink.gate_alert(alert, now_utc=clock())

    return AlertBundle(
        queue=queue,
        sink=sink,
        sender=sender,
        safe_mode_observer=SafeModeAlertObserver(sink),
        gate_alert=gate_alert,
    )


async def drain_once(bundle: AlertBundle) -> SendReport:
    """Send what is queued (the scheduler task body); a send failure is journaled, not raised."""
    return await bundle.sender.drain()


def requeue_at_start(bundle: AlertBundle, rows: Iterable[Any]) -> RequeueReport:
    """Queue the journaled alerts without a delivery row, once, before the bot starts.

    `rows` are the journal rows of correlation `operational_alerts`, read by the composition. A
    delivered alert is not queued again; a row that cannot be rebuilt is reported, never queued.

    Raises:
        AlertsAlreadyRequeued: called a second time for the same bundle.
    """
    if bundle._requeued:
        raise AlertsAlreadyRequeued("the restart re-queue runs once per bundle")
    bundle._requeued.append(True)
    return bundle.sink.requeue_undelivered(rows)


__all__ = [
    "AlertBundle",
    "AlertsAlreadyRequeued",
    "build_alerts",
    "drain_once",
    "requeue_at_start",
]
