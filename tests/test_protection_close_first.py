"""The emergency close goes out before the audit side effects (Phase 20 review WR-C8).

`_enter_close_required` used to write the CLOSE_REQUIRED journal row, enter SAFE_MODE (a journal
write and a state save) and queue the critical alerts (a journal write each) BEFORE it awaited the
reduce-only close. With the database down each of those blocked the event loop for the connect or
statement timeout, so the close of an unprotected position was held up by an audit row. Now the
plan state flips in memory first (so ``blocks_new_entries()`` is True at once), the close is
awaited, and the journal rows, SAFE_MODE and the alerts follow, whether the close succeeded,
failed or raised. A failing journal, SAFE_MODE controller or alert sink never stops the close.

Nothing here touches a network; the closer is the scripted double of the protection rig.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from src.domain.journal import JournalEvent
from src.execution.protection import ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig


def _instrument(rig: ProtectionRig, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Log every journal write, SAFE_MODE entry, alert and close call into one ordered list."""
    log: list[str] = []
    real_record = rig.journal.record
    real_enter = rig.safe_mode.enter_safe_mode
    real_critical = rig.alerts.critical
    real_close = rig.closer.close_position

    def record(event: JournalEvent) -> None:
        if event.event_type == "PROTECTION_TRANSITION":
            body = json.loads(event.payload_json)
            log.append(f"journal:{body['from']}->{body['to']}")
        else:
            log.append(f"journal:{event.event_type}")
        real_record(event)

    def enter(*, reason: str, now_utc: Any = None) -> None:
        log.append(f"safe_mode:{reason}")
        real_enter(reason=reason, now_utc=now_utc)

    def critical(**kwargs: Any) -> None:
        log.append(f"alert:{kwargs['event']}")
        real_critical(**kwargs)

    async def close(**kwargs: Any) -> bool:
        log.append("close")
        # At the moment of the close the plan already blocks new entries, in memory.
        assert rig.coordinator.blocks_new_entries() is True
        protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
        assert protection is not None
        assert protection.state is ProtectionState.CLOSE_REQUIRED
        return await real_close(**kwargs)

    monkeypatch.setattr(rig.journal, "record", record)
    monkeypatch.setattr(rig.safe_mode, "enter_safe_mode", enter)
    monkeypatch.setattr(rig.alerts, "critical", critical)
    monkeypatch.setattr(rig.closer, "close_position", close)
    return log


async def test_the_close_goes_out_before_the_journal_safe_mode_and_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await make_rig(closer_results=[False])
    log = _instrument(rig, monkeypatch)
    log.clear()

    result = await rig.coordinator.operator_close(plan_hash=TEST_ONLY_PLAN_HASH, operator_id="op-1")

    assert result.accepted is True
    close_at = log.index("close")
    assert close_at == 0, log  # nothing audit-shaped runs before the close
    assert "journal:AWAITING_FILL->CLOSE_REQUIRED" in log
    assert "safe_mode:CLOSE_REQUIRED" in log
    assert "alert:CLOSE_REQUIRED" in log
    # The alert follows the journal row of the transition and SAFE_MODE, all after the close.
    assert log.index("journal:AWAITING_FILL->CLOSE_REQUIRED") > close_at
    assert log.index("safe_mode:CLOSE_REQUIRED") > close_at
    assert log.index("alert:CLOSE_REQUIRED") > close_at
    assert rig.safe_mode.entered_reasons[0] == "CLOSE_REQUIRED"
    assert [a.event for a in rig.alerts.alerts] == ["CLOSE_REQUIRED"]


async def test_the_b5_branch_closes_first_and_still_raises_both_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await make_rig(real_closer=True)
    log = _instrument(rig, monkeypatch)
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))

    await rig.coordinator.step()

    assert [a.event for a in rig.alerts.alerts] == ["CLOSE_REQUIRED", "PROTECTIVE_REJECTED"]
    assert "journal:UNPROTECTED->CLOSE_REQUIRED" in log
    # The first thing that reached the closer is before the CLOSE_REQUIRED row and both alerts.
    first_close = log.index("close")
    assert log.index("journal:UNPROTECTED->CLOSE_REQUIRED") > first_close
    assert log.index("alert:CLOSE_REQUIRED") > first_close
    assert log.index("alert:PROTECTIVE_REJECTED") > first_close
    assert len(rig.fake.calls_to("place_market_close")) == 1


async def test_a_failing_journal_safe_mode_and_alert_sink_never_stop_the_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await make_rig(closer_results=[False])
    closes: list[int] = []
    real_close = rig.closer.close_position

    async def close(**kwargs: Any) -> bool:
        closes.append(1)
        return await real_close(**kwargs)

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("TEST_ONLY outage")

    monkeypatch.setattr(rig.closer, "close_position", close)
    monkeypatch.setattr(rig.journal, "record", boom)
    monkeypatch.setattr(rig.safe_mode, "enter_safe_mode", boom)
    monkeypatch.setattr(rig.alerts, "critical", boom)

    result = await rig.coordinator.operator_close(plan_hash=TEST_ONLY_PLAN_HASH, operator_id="op-1")

    assert result.accepted is True
    assert closes == [1]
    assert rig.coordinator.blocks_new_entries() is True  # fails closed for new entries
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.CLOSE_FAILED


async def test_an_exception_from_the_closer_still_records_safe_mode_and_the_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await make_rig(closer_results=[])
    log = _instrument(rig, monkeypatch)

    async def raising(**_kwargs: Any) -> bool:
        log.append("close")
        raise RuntimeError("TEST_ONLY closer failure")

    monkeypatch.setattr(rig.closer, "close_position", raising)
    log.clear()

    result = await rig.coordinator.operator_close(plan_hash=TEST_ONLY_PLAN_HASH, operator_id="op-1")

    assert result.accepted is True
    assert log[0] == "close"
    assert "safe_mode:CLOSE_REQUIRED" in log
    assert "alert:CLOSE_REQUIRED" in log
    assert "journal:AWAITING_FILL->CLOSE_REQUIRED" in log
    assert rig.coordinator.blocks_new_entries() is True
