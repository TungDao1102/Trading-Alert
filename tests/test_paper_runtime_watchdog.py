"""Plan 16-56: the feed fails closed (review B1-CR-01, 16-DEC-WS-WATCHDOG).

Task 1 (tracer): an exhausted WebSocket rebuild still runs its REST backfill, then the process
fails closed with exit 7 and no RUNTIME_STOP, so the restart policy restarts it and the time is a
CRASH gap.

Everything runs through `main` with the real `_LiveLoop` over the SDK-shaped fake client of
`tests/paper_ws_fakes.py`; no network is touched and no tenacity wait is slept for real.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import tenacity
from src.paper.runtime_config import ExitCode
from src.paper.vocabulary import GapReason, RuntimeEventType

from tests.paper_ws_fakes import fresh_sdk_stream_map
from tests.test_paper_runtime_loop import PAST_OPEN, Live, live, wait_until

__all__ = ["live"]  # the imported fixture


@pytest.fixture(autouse=True)
def _isolated_sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_sdk_stream_map(monkeypatch)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ratified bounds stay in src; only the random wait between attempts is skipped."""
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )


async def until_the_failure_ends_the_run(timeout: float = 10.0) -> None:
    """Park the script until the loop's own failure cancels it.

    Bounded: if no failure comes, the script returns, the stop is clean and the exit is 0, so the
    test fails on its exit-code assertion instead of hanging.
    """
    await asyncio.sleep(timeout)


def _dead_factory(_configuration: object) -> Any:
    raise ConnectionError("ws dead")


# ---------------------------------------------------------------------------------------------- #
# Task 1: the exhaustion half of B1-CR-01.
# ---------------------------------------------------------------------------------------------- #


def test_an_exhausted_rebuild_backfills_then_fails_closed_with_exit_7(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=PAST_OPEN)
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 1)
        h.client.simulate_unsolicited_close()
        await until_the_failure_ends_the_run()

    code = live.start(script, ws_client_factory=_dead_factory)

    assert code == ExitCode.FAIL_CLOSED_RUNTIME == 7
    assert "rebuild" in capsys.readouterr().err
    assert live.records(RuntimeEventType.RUNTIME_STOP) == [], "a crash leaves START open"
    assert len(live.records(RuntimeEventType.WS_DISCONNECT)) == 1
    assert live.records(RuntimeEventType.WS_RECONNECT) == []
    disconnected = [
        g
        for g in live.records(RuntimeEventType.PAPER_GAP)
        if g.payload["reason"] == GapReason.WS_DISCONNECTED.value
    ]
    assert [(g.symbol, g.interval) for g in disconnected] == [("BTCUSDT", "1h")], (
        "the backfill ran and recorded the close it could not recover"
    )
    assert live.client.close_calls >= 1, "the failure still closes the SDK connection"
    assert all(h._unsubscribed == 1 for h in live.client.handles), "every stream is unsubscribed"
