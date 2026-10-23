"""A standing SAFE_MODE divergence does not re-enter SAFE_MODE every tick (plan 20-28, WR-B1).

Before the fix, two standing reasons (a foreign order and a silent user-data feed) made the loop
call `enter_safe_mode` for each reason on every tick; the controller treated every change of the
stored reason as a re-entry, so each tick wrote two `SAFE_MODE_REENTER` journal rows, two state
saves (append-only `system_state_events` versions) and two `on_enter` calls, forever.

The rule pinned here: calls that carry one `now_utc` form one assertion round (the loop passes one
`now_utc` per tick). A reason that the previous round asserted writes nothing again; a reason that
is new records; once a round has written, its later reasons re-assert so the LAST reason of the
round (the most urgent one, the loop enters in ascending urgency) stays the persisted reason.

Evidence label: executed unit tests with fakes; nothing is [DEMO].
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from src.reconcile.feed_freshness import FeedReading
from src.reconcile.safe_mode import SafeModeController

from tests.support.reconcile_doubles import (
    InMemorySafeModeStore,
    RecordingJournal,
    make_open_order,
)
from tests.support.reconcile_rig import NOW, FakeFeedSource, build_rig

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
FEED = "STALE_FEED"
LOW = "FOREIGN_ORDER"
HIGH = "POSITION_WITHOUT_STOP"
OTHER = "UNSYNCED_POSITION"


class _Adapter:
    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]:
        return []


class _Rig:
    def __init__(self) -> None:
        self.journal = RecordingJournal()
        self.store = InMemorySafeModeStore()
        self.entered: list[tuple[str, datetime]] = []
        self.controller = SafeModeController(
            adapter=_Adapter(),
            journal=self.journal,
            state_store=self.store,
            on_enter=lambda reason, now: self.entered.append((reason, now)),
        )

    def tick(self, index: int, reasons: tuple[str, ...]) -> None:
        """One loop tick: every reason is entered with the tick's one `now_utc`, in order."""
        now = T0 + timedelta(seconds=10 * index)
        for reason in reasons:
            self.controller.enter_safe_mode(reason=reason, now_utc=now)

    def safe_mode_rows(self) -> list[str]:
        return [
            e.event_type
            for e in self.journal.events
            if e.event_type in ("SAFE_MODE_ENTER", "SAFE_MODE_REENTER")
        ]

    def counts(self) -> tuple[int, int, int]:
        return len(self.safe_mode_rows()), len(self.store.saved), len(self.entered)


def test_two_standing_reasons_write_nothing_after_the_first_tick() -> None:
    rig = _Rig()
    standing = (FEED, LOW, HIGH)

    rig.tick(0, standing)
    after_first = rig.counts()
    for index in range(1, 6):
        rig.tick(index, standing)

    assert after_first == (3, 3, 3)
    assert rig.counts() == after_first
    assert rig.safe_mode_rows() == ["SAFE_MODE_ENTER", "SAFE_MODE_REENTER", "SAFE_MODE_REENTER"]
    assert rig.controller.entered_reason == HIGH
    assert rig.store.saved[-1]["entered_reason"] == HIGH


def test_every_reason_is_in_the_journal_once() -> None:
    rig = _Rig()
    for index in range(4):
        rig.tick(index, (FEED, LOW, HIGH))

    reasons = [e.payload_json for e in rig.journal.events if "reason" in e.payload_json]
    for reason in (FEED, LOW, HIGH):
        assert sum(reason in payload for payload in reasons) == 1, reason


def test_a_new_reason_records_and_the_most_urgent_stays_persisted() -> None:
    rig = _Rig()
    standing = (LOW, HIGH)
    rig.tick(0, standing)
    rig.tick(1, standing)
    before = rig.counts()

    # A less urgent reason joins; the loop enters in ascending urgency, so it comes first.
    rig.tick(2, (LOW, OTHER, HIGH))

    rows, saves, notified = rig.counts()
    assert (rows, saves, notified) == (before[0] + 2, before[1] + 2, before[2] + 2)
    assert rig.controller.entered_reason == HIGH
    assert [reason for reason, _ in rig.entered[-2:]] == [OTHER, HIGH]

    after_change = rig.counts()
    rig.tick(3, (LOW, OTHER, HIGH))
    assert rig.counts() == after_change


def test_a_reason_that_leaves_and_returns_records_again() -> None:
    rig = _Rig()
    rig.tick(0, (LOW, HIGH))
    rig.tick(1, (HIGH,))
    assert rig.counts() == (2, 2, 2)

    rig.tick(2, (LOW, HIGH))

    assert rig.counts() == (4, 4, 4)
    assert rig.controller.entered_reason == HIGH


def test_a_shrinking_set_writes_nothing() -> None:
    rig = _Rig()
    rig.tick(0, (LOW, HIGH))
    before = rig.counts()

    rig.tick(1, (HIGH,))
    rig.tick(2, (HIGH,))

    assert rig.counts() == before


def test_a_reentry_after_an_operator_exit_records_the_whole_set_again() -> None:
    rig = _Rig()
    rig.tick(0, (LOW, HIGH))
    rig.tick(1, (LOW, HIGH))
    # The operator exit is covered by the exit tests; here only the episode state matters.
    rig.controller._in_safe_mode = False
    rig.controller._entered_reason = None
    rig.controller._entered_at_utc = None
    before = rig.counts()

    rig.tick(2, (LOW, HIGH))

    assert rig.counts() == (before[0] + 2, before[1] + 2, before[2] + 2)
    assert rig.safe_mode_rows()[-2:] == ["SAFE_MODE_ENTER", "SAFE_MODE_REENTER"]


def test_a_failed_save_is_retried_by_the_next_unchanged_tick() -> None:
    rig = _Rig()
    real_save = rig.store.save
    failing = {"on": True}

    def save(state: Mapping[str, Any], *, now_utc: datetime) -> None:
        if failing["on"]:
            raise RuntimeError("store down")
        real_save(state, now_utc=now_utc)

    rig.store.save = save  # type: ignore[method-assign]
    try:
        rig.tick(0, (LOW,))
    except RuntimeError:
        pass
    assert rig.store.saved == []

    failing["on"] = False
    rig.tick(1, (LOW,))

    assert len(rig.store.saved) == 1
    assert rig.store.saved[0]["entered_reason"] == LOW
    # The retry is not a new entry: no second journal row, no second alert.
    assert rig.safe_mode_rows() == ["SAFE_MODE_ENTER"]
    assert len(rig.entered) == 1


def test_calls_with_other_timestamps_do_not_break_the_rule() -> None:
    """An outside caller (a different `now_utc`) costs at most one extra round of writes."""
    rig = _Rig()
    rig.tick(0, (LOW, HIGH))
    rig.controller.enter_safe_mode(reason="MANUAL_CLOSE", now_utc=T0 + timedelta(seconds=15))
    rig.tick(2, (LOW, HIGH))
    settled = rig.counts()

    rig.tick(3, (LOW, HIGH))
    rig.tick(4, (LOW, HIGH))

    assert rig.counts() == settled


# --------------------------------------------------------------------------- #
# The real loop: a foreign order plus a silent user-data feed (the review scenario).
# --------------------------------------------------------------------------- #


async def test_the_loop_with_two_standing_reasons_writes_nothing_after_the_first_tick() -> None:
    silent = FakeFeedSource(FeedReading(mark_price_at_utc={}, user_data_last_event_at_utc=None))
    rig = build_rig(normal=(make_open_order("manual-order-1", "BTCUSDT"),), feed=silent)
    journal = rig.safe_mode._journal  # type: ignore[attr-defined]
    store = rig.safe_mode._state_store  # type: ignore[attr-defined]

    def written() -> tuple[int, int]:
        rows = [e for e in journal.events if e.event_type.startswith("SAFE_MODE_")]
        return len(rows), len(store.saved)

    first = await rig.loop.tick(now_utc=NOW)
    after_first = written()
    for index in range(1, 5):
        await rig.loop.tick(now_utc=NOW + timedelta(seconds=10 * index))

    assert set(first.safe_mode_reasons) >= {"STALE_FEED", "FOREIGN_ORDER"}
    assert after_first == (2, 2)
    assert written() == after_first
    assert rig.safe_mode.entered_reason == "FOREIGN_ORDER"
