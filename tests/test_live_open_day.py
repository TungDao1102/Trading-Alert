"""The live producer opens today's day state before any approval (first Demo run, 2026-11-01).

The reservation taken at APPROVE needs today's `daily_risk_days` row. `ensure_day` used to run only
while the placement inputs were assembled, after CONFIRM, so on a store that held no day every
APPROVE was refused UNCERTAIN_ACCOUNT_STATE. The rig's `prime` hid it by opening the day first.
"""

from __future__ import annotations

from src.live.risk_inputs import backfill_day_risk
from src.risk.daily_loss import utc_day_of

from tests.test_live_risk_input_producer import unit_parts


async def test_open_day_opens_the_day_on_a_flat_account_with_no_stored_day() -> None:
    parts, _signal, _plan = unit_parts()
    day = utc_day_of(parts.clock())
    assert parts.day_store.get_day(day) is None

    await backfill_day_risk(parts.day_risk, parts.clock())
    error = await parts.producer.open_day()

    assert error is None
    assert parts.day_store.get_day(day) is not None


async def test_open_day_makes_the_daily_loss_known_for_the_approve_reservation() -> None:
    # `make_reserving_save_atomic` reads the loss through `current_daily_loss_quote`; None there
    # refuses the APPROVE with UNCERTAIN_ACCOUNT_STATE even when the day row exists.
    parts, _signal, _plan = unit_parts()
    day = utc_day_of(parts.clock())

    await backfill_day_risk(parts.day_risk, parts.clock())
    await parts.producer.open_day()

    assert parts.day_risk.current_daily_loss_quote(day) is not None


async def test_open_day_without_a_current_backfill_leaves_the_day_unopened() -> None:
    parts, _signal, _plan = unit_parts()
    day = utc_day_of(parts.clock())

    error = await parts.producer.open_day()

    assert error is None
    assert parts.day_store.get_day(day) is None


async def test_open_day_with_an_unreadable_day_store_opens_nothing_and_raises_nothing() -> None:
    parts, _signal, _plan = unit_parts()
    parts.day_store.raise_next("get_day", RuntimeError("store down"))

    error = await parts.producer.open_day()

    assert error is None
    assert parts.day_store.get_day(utc_day_of(parts.clock())) is None
