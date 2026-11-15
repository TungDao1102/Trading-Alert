"""Cancelling `drain()` stops the send at once (Phase 20 review WR-C5).

tenacity's `AttemptManager.__exit__` stores any `BaseException` and returns True, and
`_is_retryable(CancelledError)` was True, so a `task.cancel()` or an `asyncio.timeout` around
`drain()` during shutdown was ignored for the whole retry budget (up to `NOTIFY_MAX_DELAY_SECONDS`)
and swallowed entirely when a later attempt succeeded. Only an `Exception` is retryable now; a
cancellation, `KeyboardInterrupt` or `SystemExit` is re-raised at once and the alert stays queued.

Evidence label: executed tests with a scripted bot and a recording sleep; no network.
"""

from __future__ import annotations

import asyncio

import pytest
from src.ops.alerts import _is_retryable

from tests.test_alerts import Harness, _close_required


async def test_a_cancellation_during_the_send_is_not_retried_and_keeps_the_alert_queued() -> None:
    h = Harness()
    _close_required(h.sink)
    h.bot.errors = [asyncio.CancelledError()]

    with pytest.raises(asyncio.CancelledError):
        await h.sender.drain()

    assert h.bot.attempts == 1  # no second attempt after the cancellation
    assert h.sleep.calls == []  # no backoff sleep either
    assert len(h.queue) == 1  # the alert is back at the head of the queue
    assert h.rows("ALERT_DELIVERED") == []


async def test_a_retry_after_the_cancelled_attempt_cannot_swallow_the_cancellation() -> None:
    h = Harness()
    _close_required(h.sink)
    h.bot.errors = [asyncio.CancelledError()]  # a second attempt would succeed

    with pytest.raises(asyncio.CancelledError):
        await h.sender.drain()

    assert h.bot.sent == []


def test_only_ordinary_exceptions_are_retryable() -> None:
    assert _is_retryable(RuntimeError("transient")) is True
    for exc in (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()):
        assert _is_retryable(exc) is False
