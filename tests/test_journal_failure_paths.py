"""Controllers when the journal raises `StoreUnavailable` (Phase 17-08 pins, Phase 20-08 rule).

No PostgreSQL here: a `ToggleJournal` stands in for `PgJournalStore` during a database
outage. Phase 17 pinned the unsafe behavior; Phase 20 plan 20-08 (D-16, F-702) replaced it
with "act first, journal afterwards". Behaviors (a journal outage is the only fault injected):

  1. `SafeModeController.enter_safe_mode` sets the in-memory flag BEFORE journaling, so
     SAFE_MODE survives a journal outage, and the `StoreUnavailable` is NOT swallowed
     (T-17-22).
  2. `LiveEnablementController.disable` flips FIRST and journals afterwards (Phase 20 plan
     20-08, F-702): with a failing journal the controller is disabled and `AuditRecordLost`
     is raised after the flip (or the record waits in a local spill when one is configured).
  3. `expire_pending_entry` and `cancel_untriggered_protectives` act FIRST (plan 20-08):
     with a failing journal the exchange cancel is still issued, once per order, and
     `AuditRecordLost` is raised afterwards when there is no spill to hold the record.
  4. Consequently `emergency_manual_close` with a failing journal runs all four steps, issues
     all four exchange cancels, disables live orders and enters SAFE_MODE. It raises one
     `ExceptionGroup` holding the SAFE_MODE `StoreUnavailable` (SAFE_MODE journaling is not
     part of plan 20-08) and one `AuditRecordLost` per lost audit record.

  5. `SafeModeController.exit_safe_mode` journals the exit BEFORE clearing the flag
     (17-REVIEW WR-03, the opposite order to entering): with a failing journal the controller
     STAYS in SAFE_MODE and the error propagates, so a retry after recovery can still exit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from src.domain.enums import KillGateState
from src.execution.enablement import LiveEnablementController
from src.execution.manager import (
    cancel_untriggered_protectives,
    emergency_manual_close,
    expire_pending_entry,
)
from src.execution.order_ids import derive_client_order_id
from src.persistence.errors import StoreUnavailable
from src.reconcile.safe_mode import SafeModeController

NOW_UTC = datetime(2026, 9, 29, 10, 30, tzinfo=UTC)
PLAN_HASH = "4444444444444444444444444444444444444444444444444444444444444444"
SYMBOL = "BTCUSDT"
ENTRY_ID = derive_client_order_id(plan_hash=PLAN_HASH, role="ENTRY")


class ToggleJournal:
    """Records events while healthy; raises `StoreUnavailable` once `down` is set."""

    def __init__(self, *, down: bool = False) -> None:
        self.down = down
        self.events: list[Any] = []
        self.attempts = 0

    def record(self, event: Any) -> None:
        self.attempts += 1
        if self.down:
            raise StoreUnavailable("PostgreSQL unavailable during transaction (OperationalError)")
        self.events.append(event)


class RecordingCancelAdapter:
    """Records every cancel call; used to prove whether the exchange was reached."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def cancel_normal_order(self, **kwargs: Any) -> None:
        self.calls.append(("cancel_normal_order", kwargs))

    async def cancel_algo_order(self, **kwargs: Any) -> None:
        self.calls.append(("cancel_algo_order", kwargs))


def _passing_health_verdict() -> Any:
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    return run_health_checks(
        results=[
            HealthCheckResult(check_name=name, status="PASS", detail="ok", observed_at_utc=NOW_UTC)
            for name in ALL_CHECK_NAMES
        ]
    )


def _enabled_controller(journal: ToggleJournal) -> LiveEnablementController:
    controller = LiveEnablementController(journal=journal)
    controller.enable(
        operator_id="operator_alpha",
        now_utc=NOW_UTC,
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    assert controller.is_disabled is False
    return controller


def _safe_mode_controller(journal: ToggleJournal) -> SafeModeController:
    return SafeModeController(adapter=object(), journal=journal)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. SAFE_MODE survives a journal outage.
# --------------------------------------------------------------------------- #


def test_safe_mode_is_entered_even_though_the_journal_is_down() -> None:
    journal = ToggleJournal(down=True)
    controller = _safe_mode_controller(journal)

    with pytest.raises(StoreUnavailable):
        controller.enter_safe_mode(reason="DIVERGENCE", now_utc=NOW_UTC)

    assert controller.in_safe_mode is True
    assert controller.entered_reason == "DIVERGENCE"
    assert journal.attempts == 1
    assert journal.events == []
    # The flag blocks new entries regardless of the journal.
    assert controller.guard_new_entries(trade_plan=None).is_no_trade is True


# --------------------------------------------------------------------------- #
# 2. disable() with a failing journal stays enabled (F-702, owned by Phase 20).
# --------------------------------------------------------------------------- #


def test_disable_with_a_failing_journal_flips_the_flag_and_raises_audit_record_lost() -> None:
    """Rewritten by Phase 20 plan 20-08 (F-702, D-16): disable acts first, journals afterwards.

    The Phase 17 pin (`..._raises_and_the_controller_stays_enabled`) said a database outage kept
    live orders enabled. With a journal that raises and no spill the flag now flips and
    `AuditRecordLost` is raised after it, naming the exception class only.
    """
    from src.ops.risk_first import AuditRecordLost

    journal = ToggleJournal()
    controller = _enabled_controller(journal)
    journal.down = True

    with pytest.raises(AuditRecordLost) as excinfo:
        controller.disable(operator_id="operator_alpha", now_utc=NOW_UTC)

    # F-702: the flag flipped before the journal was asked; the outage cannot keep live on.
    assert controller.is_disabled is True
    assert controller.guard_placement(plan_hash=PLAN_HASH).is_no_trade is True
    assert "StoreUnavailable" in str(excinfo.value)
    assert "PostgreSQL unavailable" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 3. Cancel steps act first (plan 20-08, F-702, D-16).
# --------------------------------------------------------------------------- #


async def test_expire_pending_entry_still_cancels_when_the_journal_is_down() -> None:
    """Rewritten by Phase 20 plan 20-08 (F-702): the cancel no longer waits for the journal.

    The Phase 17 pin (`..._issues_no_cancel_when_the_journal_is_down`) said a journal outage
    prevented the cancel. Now the cancel is issued once and, with no spill configured,
    `AuditRecordLost` is raised afterwards, naming exception classes only.
    """
    from src.ops.risk_first import AuditRecordLost

    journal = ToggleJournal(down=True)
    adapter = RecordingCancelAdapter()

    with pytest.raises(AuditRecordLost) as excinfo:
        await expire_pending_entry(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
            trigger_reason="operator_close",
        )

    assert [method for method, _ in adapter.calls] == ["cancel_normal_order"]
    assert "StoreUnavailable" in str(excinfo.value)
    assert "PostgreSQL unavailable" not in str(excinfo.value)


async def test_cancel_untriggered_protectives_cancels_every_leg_in_an_outage() -> None:
    """Rewritten by Phase 20 plan 20-08 (F-702): every leg is cancelled during an outage.

    The Phase 17 pin said the outage surfaced unwrapped on the first leg and no cancel was
    issued. Now all three legs are cancelled in SL -> TP1 -> TP2 order and each lost audit
    record is collected into the `ExceptionGroup` (one per leg).
    """
    from src.ops.risk_first import AuditRecordLost

    journal = ToggleJournal(down=True)
    adapter = RecordingCancelAdapter()

    with pytest.raises(ExceptionGroup) as excinfo:
        await cancel_untriggered_protectives(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
        )

    assert [method for method, _ in adapter.calls] == ["cancel_algo_order"] * 3
    assert [type(e) for e in excinfo.value.exceptions] == [AuditRecordLost] * 3
    assert journal.attempts == 6  # pre-image and post-image per leg, none withheld


# --------------------------------------------------------------------------- #
# 4. emergency_manual_close during a journal outage.
# --------------------------------------------------------------------------- #


async def test_emergency_close_in_an_outage_runs_every_step_and_reaches_the_exchange() -> None:
    """Rewritten by Phase 20 plan 20-08 (F-702): the whole sequence works during an outage.

    The Phase 17 pin said four `StoreUnavailable`, zero exchange cancels and live orders left
    enabled. Now live orders are disabled, SAFE_MODE is entered and all four cancels are issued.
    The group holds the SAFE_MODE `StoreUnavailable` (SAFE_MODE journaling is not part of this
    plan) and the lost audit records of the disable, the entry cancel and the protective cancels.
    """
    from src.ops.risk_first import AuditRecordLost

    journal = ToggleJournal()
    enablement = _enabled_controller(journal)
    safe_mode = _safe_mode_controller(journal)
    adapter = RecordingCancelAdapter()
    journal.down = True

    with pytest.raises(ExceptionGroup) as excinfo:
        await emergency_manual_close(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            enablement=enablement,
            safe_mode_controller=safe_mode,
            operator_id="operator_alpha",
            now_utc=NOW_UTC,
        )

    failures = excinfo.value.exceptions
    assert [type(failure) for failure in failures] == [
        AuditRecordLost,  # disable
        StoreUnavailable,  # SAFE_MODE enter (flag set first)
        AuditRecordLost,  # entry cancel
        ExceptionGroup,  # protective legs, one lost record per leg
    ]
    assert safe_mode.in_safe_mode is True
    assert safe_mode.entered_reason == "MANUAL_CLOSE"
    assert enablement.is_disabled is True
    assert [method for method, _ in adapter.calls] == [
        "cancel_normal_order",
        "cancel_algo_order",
        "cancel_algo_order",
        "cancel_algo_order",
    ]


async def test_emergency_close_cancels_run_once_the_journal_is_back() -> None:
    """Control: the same sequence with a healthy journal reaches the exchange."""
    journal = ToggleJournal()
    enablement = _enabled_controller(journal)
    safe_mode = _safe_mode_controller(journal)
    adapter = RecordingCancelAdapter()

    await emergency_manual_close(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=adapter,  # type: ignore[arg-type]
        journal=journal,
        enablement=enablement,
        safe_mode_controller=safe_mode,
        operator_id="operator_alpha",
        now_utc=NOW_UTC,
    )

    assert enablement.is_disabled is True
    assert safe_mode.in_safe_mode is True
    assert [method for method, _ in adapter.calls] == [
        "cancel_normal_order",
        "cancel_algo_order",
        "cancel_algo_order",
        "cancel_algo_order",
    ]
    assert adapter.calls[0][1] == {"symbol": SYMBOL, "orig_client_order_id": ENTRY_ID}


# --------------------------------------------------------------------------- #
# 5. exit_safe_mode is journal-first (17-REVIEW WR-03), so a journal outage fails closed.
# --------------------------------------------------------------------------- #


class _CleanTruthAdapter:
    """Exchange truth that always agrees with an empty local state."""

    async def snapshot_open_normal_orders(self, *, symbol: Any = None) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, *, symbol: Any = None) -> list[Any]:
        return []

    async def snapshot_positions(self, *, symbol: Any = None) -> list[Any]:
        return []


async def test_exit_safe_mode_with_a_failing_journal_stays_in_safe_mode_and_can_retry() -> None:
    journal = ToggleJournal()
    controller = SafeModeController(adapter=_CleanTruthAdapter(), journal=journal)  # type: ignore[arg-type]
    controller.enter_safe_mode(reason="DIVERGENCE", now_utc=NOW_UTC)
    journal.down = True

    with pytest.raises(StoreUnavailable):
        await controller.exit_safe_mode(now_utc=NOW_UTC)

    # Fail closed: the un-journaled exit did not happen, so entries stay blocked.
    assert controller.in_safe_mode is True
    assert controller.entered_reason == "DIVERGENCE"
    assert controller.entered_at_utc == NOW_UTC
    assert controller.guard_new_entries(trade_plan=None).is_no_trade is True
    assert [e.event_type for e in journal.events] == ["SAFE_MODE_ENTER"]

    # The retry after the journal recovers exits and records exactly one exit event.
    journal.down = False
    assert await controller.exit_safe_mode(now_utc=NOW_UTC) is True
    assert controller.in_safe_mode is False
    assert controller.entered_reason is None
    assert [e.event_type for e in journal.events] == ["SAFE_MODE_ENTER", "SAFE_MODE_EXIT"]
