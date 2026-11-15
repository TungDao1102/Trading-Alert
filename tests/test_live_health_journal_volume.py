"""R-25 (D-11, D-13): the health tick journals one verdict per tick and the checks on change only.

Evidence label: executed unit tests with fakes and a virtual clock. Nothing here touches Binance,
Telegram or a database. Every time and threshold is TEST_ONLY.

Before this rule `health_tick_once` wrote eleven rows every tick (ten `HEALTH_CHECK` plus one
`HEALTH_VERDICT`, about 63,000 rows a day at a 15 s cadence, 24-REVIEW IN-02). The verdict row
stays on every tick because every successful journal write refreshes `DbWriteTracker`, and on a
quiet Demo account the health rows are the only writes (25-RESEARCH Pitfall 5).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from src.adapters.binance_public import MarkPriceReading
from src.domain.journal import JournalEvent
from src.live.health import (
    DbWriteTracker,
    LiveHealthThresholds,
    health_tick_once,
)
from src.ops.health import (
    ALL_CHECK_NAMES,
    CHECK_DB_WRITES,
    CHECK_TELEGRAM_DELIVERY,
    HealthVerdict,
)

from tests.test_live_health import DIAGNOSTICS, NOW, SYMBOLS, Parts

CADENCE = timedelta(seconds=15)
DB_WRITE_MAX_AGE = timedelta(seconds=60)


class Rig:
    """A producer over the `Parts` fakes with a virtual clock and a tracked, recording journal."""

    def __init__(self) -> None:
        self.clock: datetime = NOW
        self.parts = Parts()
        self.parts.thresholds = LiveHealthThresholds(
            mark_price_max_age=timedelta(seconds=60),
            mark_clock_skew=timedelta(milliseconds=500),
            rest_max_error_rate=Decimal("0.05"),
            db_write_max_age=DB_WRITE_MAX_AGE,
        )
        self.parts.db = DbWriteTracker(clock=lambda: self.clock)
        self.parts.db.note_ok()  # the start sequence has written before the first health tick
        self.producer = self.parts.producer()
        self.rows: list[JournalEvent] = []
        self.write_fails = False
        self.fail_check_name: str | None = None
        self.record = self.parts.db.track(self._write)

    async def _write(self, event: JournalEvent) -> None:
        if self.write_fails:
            raise RuntimeError("journal unavailable")
        if (
            self.fail_check_name is not None
            and event.event_type == "HEALTH_CHECK"
            and event.entity_id == self.fail_check_name
        ):
            self.fail_check_name = None  # fails once
            raise RuntimeError("journal unavailable")
        self.rows.append(event)

    async def tick(self, *, advance: bool = True) -> HealthVerdict:
        """One health tick at the virtual time, with fresh marks; then the clock moves on."""
        for symbol in SYMBOLS:
            self.parts.marks.store(
                MarkPriceReading(
                    symbol=symbol,
                    mark_price=Decimal("50000"),
                    exchange_time_utc=self.clock - timedelta(seconds=5),
                )
            )
        try:
            return await health_tick_once(
                self.producer,
                now_utc=self.clock,
                record=self.record,
                diagnostics=lambda: DIAGNOSTICS,
            )
        finally:
            if advance:
                self.clock += CADENCE

    def of_type(self, event_type: str) -> list[JournalEvent]:
        return [row for row in self.rows if row.event_type == event_type]


def status_of(verdict: HealthVerdict, check_name: str) -> str:
    return next(r.status for r in verdict.results if r.check_name == check_name)


async def test_ten_idle_ticks_journal_ten_verdicts_and_the_ten_check_rows_once() -> None:
    rig = Rig()
    verdict: HealthVerdict | None = None
    for _ in range(10):
        verdict = await rig.tick()
    assert verdict is not None
    assert len(rig.of_type("HEALTH_VERDICT")) == 10
    checks = rig.of_type("HEALTH_CHECK")
    assert len(checks) == 10
    assert [row.entity_id for row in checks] == list(ALL_CHECK_NAMES)
    assert {row.occurred_at_utc for row in checks} == {NOW}  # all on the first tick
    assert status_of(verdict, CHECK_DB_WRITES) == "PASS"


async def test_a_status_flip_journals_one_extra_row_for_that_check_only() -> None:
    rig = Rig()
    per_tick: list[list[str]] = []
    for number in range(1, 9):
        if number == 4:
            rig.parts.telegram.note(ok=False)
        if number == 6:
            rig.parts.telegram.note(ok=True)
        before = len(rig.of_type("HEALTH_CHECK"))
        await rig.tick()
        per_tick.append([row.entity_id for row in rig.of_type("HEALTH_CHECK")[before:]])
    assert per_tick[0] == list(ALL_CHECK_NAMES)
    assert per_tick[3] == [CHECK_TELEGRAM_DELIVERY]  # PASS -> FAIL
    assert per_tick[5] == [CHECK_TELEGRAM_DELIVERY]  # FAIL -> PASS
    assert [rows for index, rows in enumerate(per_tick) if index not in (0, 3, 5)] == [[]] * 5
    assert len(rig.of_type("HEALTH_VERDICT")) == 8


async def test_a_failed_check_row_write_keeps_the_verdict_and_is_written_again_next_tick() -> None:
    rig = Rig()
    rig.fail_check_name = ALL_CHECK_NAMES[0]
    with pytest.raises(RuntimeError, match="journal unavailable"):
        await rig.tick()
    assert rig.producer.latest_verdict is not None  # stored before any write
    assert rig.rows == []
    await rig.tick()
    checks = rig.of_type("HEALTH_CHECK")
    # the failed write did not count as journaled: the first check is written again, in order
    assert [row.entity_id for row in checks][:1] == [ALL_CHECK_NAMES[0]]
    assert {row.entity_id for row in checks} == set(ALL_CHECK_NAMES)
    assert len(checks) == len(ALL_CHECK_NAMES)
    # the failed write cleared the tracker stamp, so db_writes read FAIL on tick 2 and PASS on
    # tick 3: that one flip is the only row tick 3 writes
    before = len(checks)
    await rig.tick()
    assert [row.entity_id for row in rig.of_type("HEALTH_CHECK")[before:]] == [CHECK_DB_WRITES]


async def test_a_journal_that_fails_for_over_a_minute_turns_db_writes_red() -> None:
    rig = Rig()
    rig.write_fails = True
    for _ in range(6):  # 75 virtual seconds, longer than DB_WRITE_MAX_AGE
        with pytest.raises(RuntimeError, match="journal unavailable"):
            await rig.tick()
    verdict = rig.producer.latest_verdict
    assert verdict is not None
    assert status_of(verdict, CHECK_DB_WRITES) == "FAIL"
    assert verdict.is_no_trade is True
    assert rig.parts.db.last_ok_utc is None  # failed writes never refresh the tracker
    assert rig.rows == []


async def test_a_stamp_older_than_the_limit_reads_stale_then_recovers_on_the_next_write() -> None:
    rig = Rig()
    await rig.tick()
    rig.clock += DB_WRITE_MAX_AGE + timedelta(seconds=1)  # nothing wrote for over a minute
    stale = await rig.tick()
    assert status_of(stale, CHECK_DB_WRITES) == "FAIL"
    fresh = await rig.tick()  # the previous tick's verdict row refreshed the stamp
    assert status_of(fresh, CHECK_DB_WRITES) == "PASS"


async def test_the_start_sequence_and_the_scheduled_call_share_the_producer() -> None:
    rig = Rig()
    await rig.tick(advance=False)  # the start-sequence health verdict
    assert len(rig.of_type("HEALTH_CHECK")) == len(ALL_CHECK_NAMES)
    await rig.tick()  # the first scheduled tick, nothing changed
    assert len(rig.of_type("HEALTH_CHECK")) == len(ALL_CHECK_NAMES)
    assert len(rig.of_type("HEALTH_VERDICT")) == 2
