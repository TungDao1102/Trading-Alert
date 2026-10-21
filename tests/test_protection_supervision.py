"""Stop supervision after PROTECTED, COMPLETE and TP_UNAVAILABLE (plan 20-09; D-07, D-06, D077).

Before this plan a plan past PROTECTED never read its stop again: a stop cancelled or lost while
the position stayed open was invisible. Now each step of PROTECTED, COMPLETE and TP_UNAVAILABLE
reads the stop by its deterministic id. A stop that reads ABSENT or NOT_ACTIVE is decided by the
position as in D077 (the existing ``_on_stop_lost``): confirmed exposure is CLOSE_REQUIRED (B4) and
a reduce-only MARKET close, an unreadable position is UNPROTECTED with ``stop_lost_at`` set once,
flat on two reads with the entry terminal is FLAT. A stop confirmed ACTIVE and later lost is never
re-placed.

Every test runs offline against the stateful Phase 19 fake exchange, the real
``MarketEmergencyCloser`` and virtual time. The deadlines are the TEST_ONLY values of
``tests/support/execution_limits.py``, never a ratified number. Binance's behavior for a
``closePosition`` stop when the position closes (assumption A3) is NOT observed: both outcomes
(auto-cancelled, or left as an orphan and swept) are handled and tested against the fake [DESIGN];
no [DEMO] claim.
"""

from __future__ import annotations

import json
from collections import deque
from decimal import Decimal
from typing import Any

from src.execution.protection import PlanProtection, ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal

FULL_FILL = D("0.010")


def _view(rig: ProtectionRig) -> PlanProtection:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection


def _transitions(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    out = []
    for event in rig.journal.calls:
        if event.event_type == "PROTECTION_TRANSITION":
            body = json.loads(event.payload_json)
            out.append((body["from"], body["to"], body["reason"]))
    return out


def _states(rig: ProtectionRig) -> list[str]:
    return [to for _, to, _ in _transitions(rig)]


def _stop_reads(rig: ProtectionRig) -> int:
    """How many REST queries of the STOP_LOSS leg (by its deterministic id) were made."""
    return sum(
        1
        for call in rig.fake.calls_to("query_algo_order_by_client")
        if call["kwargs"]["client_algo_id"] == rig.stop_id
    )


def _close_required_alerts(rig: ProtectionRig) -> list[str]:
    return [a.reason for a in rig.alerts.alerts if a.event == "CLOSE_REQUIRED"]


async def _to_protected(rig: ProtectionRig, quantity: Decimal = FULL_FILL) -> None:
    """The entry fills by `quantity`; two steps later the stop is confirmed and the entry ended."""
    rig.coordinator.fill_sink(rig.stream_fill(quantity))
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.UNPROTECTED
    await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.PROTECTED


def _script_position_read_failures(rig: ProtectionRig, count: int) -> None:
    """The next `count` position reads raise (the stop reads stay real)."""
    script = deque([True] * count)
    original = rig.fake.snapshot_positions

    async def scripted(**kwargs: Any) -> Any:
        if script and script.popleft():
            rig.fake._record_call("snapshot_positions", kwargs)
            raise RuntimeError("scripted position read failure")
        return await original(**kwargs)

    rig.fake.snapshot_positions = scripted  # type: ignore[method-assign]


# --------------------------------------------------------------------------- #
# Task 1 (tracer): a PROTECTED plan whose stop is cancelled with exposure open.
# --------------------------------------------------------------------------- #


async def test_protected_stop_cancelled_with_exposure_closes_and_never_replaces() -> None:
    rig = await make_rig(real_closer=True)
    await _to_protected(rig)
    placements_before = len(rig.fake.calls_to("place_algo_protective"))
    assert placements_before == 1

    rig.fake.cancel_algo(rig.stop_id)  # the owner or an outage cancels the confirmed stop
    detected_at = rig.clock.now()
    reads_before = _stop_reads(rig)

    await rig.coordinator.step()

    assert _stop_reads(rig) - reads_before == 1, "one supervision read of the stop by its id"
    assert _transitions(rig)[-1] == ("PROTECTED", "CLOSE_REQUIRED", "B4_FILL_AFTER_STOP")
    assert _view(rig).stop_lost_at_utc == detected_at
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert _close_required_alerts(rig) == ["B4_FILL_AFTER_STOP"]
    assert [c["kwargs"]["quantity"] for c in rig.fake.calls_to("place_market_close")] == [FULL_FILL]
    assert rig.fake.calls_to("place_market_close")[0]["kwargs"]["side"] == "SELL"

    for _ in range(3):
        await rig.coordinator.step()
    assert _view(rig).state is ProtectionState.FLAT
    assert len(rig.fake.calls_to("place_algo_protective")) == placements_before
    assert "PROTECTED" not in _states(rig)[_states(rig).index("CLOSE_REQUIRED") :]
    assert _close_required_alerts(rig) == ["B4_FILL_AFTER_STOP"]
    assert len(rig.fake.calls_to("place_market_close")) == 1
