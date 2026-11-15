"""A single supervisor sleep on a timed REST pause is bounded (plan 20-30, WR-C3).

`_await_rest_allowed` slept for the whole remaining pause in one call, so a huge value parked the
recovery in one sleep. A sleep is now at most `reconnect_wait_max_seconds` (an existing
`StreamLimits` key, no new number) and the gate is asked again after each slice, so the wait still
ends exactly when the gate opens and nothing is sent in between. Virtual clock, no real sleep.
"""

from __future__ import annotations

import asyncio

from src.domain.exchange_errors import ExchangeErrorCategory

from tests.support.limits import TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS as CAP
from tests.test_userdata_supervisor import Rig, StreamState, limits_with

S = StreamState
_C = ExchangeErrorCategory


async def test_a_long_pause_is_slept_in_slices_of_at_most_the_reconnect_wait_max() -> None:
    rig = Rig(limits=limits_with())
    wait_max = rig.limits.reconnect_wait_max_seconds
    assert wait_max < CAP
    rig.gate.record(_C.RATE_LIMITED, CAP)  # a pause of CAP seconds

    starting = asyncio.ensure_future(rig.supervisor.start())
    await rig.vt.advance(1)
    assert rig.vt.sleeps[:1] == [wait_max]
    assert rig.listen_key_posts() == 0

    await rig.vt.advance(CAP - 1 - 1)  # one second short of the end of the pause
    assert max(rig.vt.sleeps) <= wait_max
    assert rig.listen_key_posts() == 0
    assert not starting.done()

    await rig.vt.advance(1)
    await asyncio.wait_for(starting, timeout=5)
    await rig.settle()
    assert rig.supervisor.state is S.LIVE
    assert rig.listen_key_posts() == 1
    await rig.stop()


async def test_a_short_pause_is_still_slept_in_one_piece() -> None:
    rig = Rig(limits=limits_with())
    rig.gate.record(_C.RATE_LIMITED, 5)

    starting = asyncio.ensure_future(rig.supervisor.start())
    await rig.vt.advance(1)
    assert rig.vt.sleeps[:1] == [5]
    await rig.vt.advance(4)
    await asyncio.wait_for(starting, timeout=5)
    await rig.settle()

    assert rig.supervisor.state is S.LIVE
    await rig.stop()
