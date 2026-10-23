"""Stop confirmation against the shapes Binance Demo showed on 2026-10-22 (plan 20-27).

Evidence: `.planning/phases/19-execution-plan-binding-price-check/evidence/
demo-probe-EVIDENCE-20261022T120055Z.json`, cases `algo_query_timing_after_new` and
`stop_query_absent_then_same_id` (Binance Demo, not mainnet). Right after placement a query of an
algo order BY CLIENT ID answered -2013 although the stop was NEW; the same-id re-place answered
-4116 (DUPLICATE_CLIENT_ID); the open-algo-orders listing showed the stop.

So `found=False` of the by-id query is not proof that a never-confirmed stop is absent. The
coordinator also reads the symbol's open-algo-orders listing in the same step: listed with an
ACTIVE status is REST-confirmed ACTIVE; ABSENT (and the B2/B3 same-id re-place) only when the
listing was read and lacks the id; an unreadable listing is UNREADABLE and never re-places; a -4116
answer to a placement means the id exists and is never a definitive rejection (B5) nor protection.
The user-data stream is not a confirmation source (D079). D077 is unchanged: a stop once
confirmed ACTIVE by its id and later lost is never re-placed.

Fakes only: the Phase 19 fake exchange wrapped to reproduce the Demo answers, virtual time and the
real closer. The wrapped answers are the Demo shapes, not a model of Binance.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.execution.protection import ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig

D = Decimal
MAX_UNPROTECTED_MS = 7777  # the TEST_ONLY value of tests/support/execution_limits.py


@dataclass
class DemoLag:
    """What the wrapped fake still gets wrong, as the Demo did.

    `by_id_absent`: that many by-client-id queries of the stop answer found=False (-2013 shape)
    although it rests NEW. `listing_hides`: that many listing reads omit the stop.
    """

    by_id_absent: int = 0
    listing_hides: int = 0


def install_demo_lag(rig: ProtectionRig, lag: DemoLag) -> None:
    query = rig.fake.query_algo_order_by_client
    listing = rig.fake.snapshot_open_algo_orders

    async def lagging_query(**kwargs: Any) -> Any:
        probe = await query(**kwargs)
        if lag.by_id_absent > 0 and probe.found and kwargs["client_algo_id"] == rig.stop_id:
            lag.by_id_absent -= 1
            return dataclasses.replace(probe, found=False, algo_status=None, update_time_utc=None)
        return probe

    async def lagging_listing(**kwargs: Any) -> Any:
        rows = await listing(**kwargs)
        if lag.listing_hides > 0:
            lag.listing_hides -= 1
            return [row for row in rows if row.client_algo_id != rig.stop_id]
        return rows

    rig.fake.query_algo_order_by_client = lagging_query  # type: ignore[method-assign]
    rig.fake.snapshot_open_algo_orders = lagging_listing  # type: ignore[method-assign]


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


def _tracked(rig: ProtectionRig) -> Any:
    return rig.coordinator._tracked[TEST_ONLY_PLAN_HASH]  # noqa: SLF001


def _places(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("place_algo_protective"))


def _listing_reads(rig: ProtectionRig) -> int:
    return len(rig.fake.calls_to("snapshot_open_algo_orders"))


def _events(rig: ProtectionRig, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in rig.journal.calls if e.event_type == event_type]


def _transition_reasons(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    return [
        (body["from"], body["to"], body["reason"]) for body in _events(rig, "PROTECTION_TRANSITION")
    ]


async def _first_fill_step(lag: DemoLag, **rig_kwargs: Any) -> ProtectionRig:
    """The entry fills and the first step places the stop (NEW) and cancels the remainder."""
    rig = await make_rig(real_closer=True, **rig_kwargs)
    install_demo_lag(rig, lag)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    assert _places(rig) == 1
    assert rig.stop_id in rig.fake.open_algos
    assert _state(rig) is ProtectionState.UNPROTECTED  # a placement is never protection
    return rig


# --------------------------------------------------------------------------- #
# The Demo sequence: by-id -2013, then the listing shows the stop NEW.
# --------------------------------------------------------------------------- #


async def test_by_id_absent_but_listed_new_is_rest_confirmed_active_without_a_replace() -> None:
    rig = await _first_fill_step(DemoLag(by_id_absent=1))

    await rig.coordinator.step()  # by id: -2013 shape; listing: the stop, NEW

    assert _state(rig) is ProtectionState.PROTECTED
    assert _places(rig) == 1  # never re-placed
    assert _listing_reads(rig) == 1
    assert rig.fake.calls_to("place_market_close") == []
    assert _tracked(rig).stop_confirmed_at is not None
    row = rig.stop_row()
    assert row.intent_status.value == "ACKED"
    assert row.exchange_status == "NEW"
    assert _events(rig, "PROTECTION_REST_FAILED") == []
    assert rig.alerts.alerts == []
    # The user-data stream is not a source of confirmation: only the two REST reads were used.
    assert {c["method"] for c in rig.fake.calls} <= {
        "place_entry",
        "place_algo_protective",
        "cancel_normal_order",
        "query_algo_order_by_client",
        "query_order_by_client",
        "snapshot_open_algo_orders",
        "snapshot_positions",
        "symbol_lot_filters",
        "get_mark_price",
        "get_last_price",
    }


async def test_a_by_id_answer_of_found_does_not_read_the_listing() -> None:
    rig = await _first_fill_step(DemoLag())

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.PROTECTED
    assert _listing_reads(rig) == 0
    assert _tracked(rig).stop_by_id_seen is True


async def test_a_listed_stop_with_a_status_that_is_not_active_is_not_protection() -> None:
    rig = await _first_fill_step(DemoLag(by_id_absent=3))
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"  # a class that never confirms

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.UNPROTECTED
    assert _tracked(rig).stop_confirmed_at is None
    assert _places(rig) == 1  # it exists: nothing is re-placed on a listed id


# --------------------------------------------------------------------------- #
# ABSENT only when the listing was read and lacks the id; an unreadable listing never re-places.
# --------------------------------------------------------------------------- #


async def test_by_id_absent_and_listing_read_without_the_id_replaces_once_under_the_same_id() -> (
    None
):
    rig = await make_rig(real_closer=True)
    rig.fake.fail_next("place_algo_protective", RuntimeError("scripted ambiguous failure"))
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()  # probe: absent; placement: ambiguous failure, nothing resting
    assert _places(rig) == 1 and rig.stop_id not in rig.fake.open_algos

    await rig.coordinator.step()  # by id: absent; listing read OK without the id: ABSENT

    assert _listing_reads(rig) == 1
    assert _places(rig) == 2
    assert rig.fake.calls_to("place_algo_protective")[-1]["kwargs"]["client_algo_id"] == rig.stop_id
    assert rig.stop_id in rig.fake.open_algos
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED
    assert _places(rig) == 2


async def test_an_unreadable_listing_is_unreadable_and_never_replaces() -> None:
    rig = await _first_fill_step(DemoLag(by_id_absent=1))
    rig.fake.fail_next("snapshot_open_algo_orders", RuntimeError("scripted listing failure"))

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.UNPROTECTED
    assert _places(rig) == 1  # never re-placed on an unreadable listing
    (failed,) = _events(rig, "PROTECTION_REST_FAILED")
    assert failed["call"] == "snapshot_open_algo_orders"
    assert failed["error_type"] == "RuntimeError"

    await rig.coordinator.step()  # the next step reads again; the by-id answer is back

    assert _state(rig) is ProtectionState.PROTECTED
    assert _places(rig) == 1


async def test_a_listing_that_is_not_a_list_is_unreadable() -> None:
    rig = await _first_fill_step(DemoLag(by_id_absent=1))

    async def not_a_list(**_kwargs: Any) -> Any:
        return None

    rig.fake.snapshot_open_algo_orders = not_a_list  # type: ignore[method-assign]

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.UNPROTECTED
    assert _places(rig) == 1


# --------------------------------------------------------------------------- #
# -4116: the id exists. Awaiting REST confirmation; never B5, never protection.
# --------------------------------------------------------------------------- #


async def test_a_4116_answer_to_the_replace_means_exists_and_the_next_listing_confirms() -> None:
    rig = await _first_fill_step(DemoLag(by_id_absent=2, listing_hides=1))

    await rig.coordinator.step()  # by id: -2013; listing hides the stop: ABSENT -> same-id re-place

    assert _places(rig) == 2
    (failed,) = _events(rig, "PROTECTION_STOP_PLACEMENT_FAILED")
    assert failed["category"] == "DUPLICATE_CLIENT_ID"
    (awaiting,) = _events(rig, "PROTECTION_STOP_EXISTS_AWAITING_REST")
    assert awaiting["category"] == "DUPLICATE_CLIENT_ID"
    assert _tracked(rig).stop_exists_unconfirmed is True
    # Not a definitive rejection (B5), not protection, no close, the intent is not REJECTED.
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.stop_row().intent_status.value != "REJECTED"
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.alerts.alerts == []

    await rig.coordinator.step()  # by id: -2013 again; the listing shows the stop NEW

    assert _state(rig) is ProtectionState.PROTECTED
    assert _places(rig) == 2  # not re-sent while the listing shows it
    assert _tracked(rig).stop_exists_unconfirmed is False
    reasons = [reason for _from, _to, reason in _transition_reasons(rig)]
    assert "B5_STOP_REJECTED" not in reasons


async def test_a_4116_answer_on_the_first_placement_is_exists_not_a_rejection() -> None:
    rig = await make_rig(real_closer=True)
    fill = rig.stream_fill(D("0.004"))
    # The stop already rests (for example an earlier process placed it) and the by-id probe lags.
    await rig.fake.place_algo_protective(
        symbol="BTCUSDT",
        side=rig.entry.exit_side,
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=rig.entry.sl_trigger_price,
        close_position=True,
        quantity=None,
        working_type=rig.entry.working_type,
        client_algo_id=rig.stop_id,
    )
    install_demo_lag(rig, DemoLag(by_id_absent=1))
    rig.coordinator.fill_sink(fill)

    await rig.coordinator.step()  # probe: -2013 shape; the placement answers -4116

    assert _tracked(rig).stop_exists_unconfirmed is True
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.stop_row().intent_status.value != "REJECTED"

    await rig.coordinator.step()

    assert _state(rig) is ProtectionState.PROTECTED
    assert _places(rig) == 1 + 1  # the test's own seed placement and the one -4116 attempt


async def test_when_neither_read_ever_shows_the_stop_there_is_one_attempt_per_step_then_b2() -> (
    None
):
    """The worst case: by-id and listing both keep denying a stop that rests. Bounded."""
    rig = await _first_fill_step(DemoLag(by_id_absent=99, listing_hides=99))
    attempts = [_places(rig)]
    for _ in range(3):
        await rig.coordinator.step()
        attempts.append(_places(rig))

    # Every step re-places at most once, under the same id and the plan price.
    assert [b - a for a, b in zip(attempts, attempts[1:], strict=False)] == [1, 1, 1]
    for call in rig.fake.calls_to("place_algo_protective"):
        assert call["kwargs"]["client_algo_id"] == rig.stop_id
        assert call["kwargs"]["trigger_price"] == rig.entry.sl_trigger_price
    assert _state(rig) is ProtectionState.UNPROTECTED
    assert rig.fake.calls_to("place_market_close") == []

    await rig.clock.advance(MAX_UNPROTECTED_MS / 1000)
    await rig.coordinator.step()  # the deadline: the existing B2 escalation, not B5

    assert _state(rig) is ProtectionState.CLOSE_REQUIRED
    assert _transition_reasons(rig)[-1] == ("UNPROTECTED", "CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED")
    assert all(reason != "B5_STOP_REJECTED" for *_rest, reason in _transition_reasons(rig))


# --------------------------------------------------------------------------- #
# D077 is unchanged; a stop confirmed only by the listing is not "lost" by a lagging by-id read.
# --------------------------------------------------------------------------- #


async def test_a_stop_confirmed_by_the_listing_is_not_lost_while_the_by_id_read_still_lags() -> (
    None
):
    rig = await _first_fill_step(DemoLag(by_id_absent=3))
    await rig.coordinator.step()  # confirmed by the listing
    assert _state(rig) is ProtectionState.PROTECTED
    assert _tracked(rig).stop_by_id_seen is False

    await rig.coordinator.step()  # supervision: by id -2013 shape, the listing still shows it

    assert _state(rig) not in (
        ProtectionState.UNPROTECTED,
        ProtectionState.CLOSE_REQUIRED,
        ProtectionState.CLOSE_FAILED,
    )
    assert rig.fake.calls_to("place_market_close") == []
    assert _tracked(rig).stop_lost_at is None
    stop_placements = [
        c
        for c in rig.fake.calls_to("place_algo_protective")
        if c["kwargs"]["client_algo_id"] == rig.stop_id
    ]
    assert len(stop_placements) == 1  # the stop is never re-placed


async def test_a_stop_confirmed_by_its_id_and_later_lost_is_never_replaced() -> None:
    """D077 (P6/B4): the crisp path is untouched; the listing is not even read for it."""
    rig = await make_rig(real_closer=True)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.coordinator.step()  # confirmed by id: found=True NEW
    assert _state(rig) in (ProtectionState.PROTECTED, ProtectionState.COMPLETE)
    assert _tracked(rig).stop_by_id_seen is True
    places_before = _places(rig)
    rig.fake.trigger_stop(rig.stop_id)  # the stop leaves the book (it fired)

    await rig.coordinator.step()

    assert _listing_reads(rig) == 0
    assert _places(rig) == places_before  # never re-placed
    assert _state(rig) is not ProtectionState.PROTECTED
    stop_placements = [
        c
        for c in rig.fake.calls_to("place_algo_protective")
        if c["kwargs"]["client_algo_id"] == rig.stop_id
    ]
    assert len(stop_placements) == 1
