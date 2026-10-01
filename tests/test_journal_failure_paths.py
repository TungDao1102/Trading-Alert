"""Journal-first controllers when the journal raises `StoreUnavailable` (Phase 17-08, Pitfall 9).

No PostgreSQL here: a `ToggleJournal` stands in for `PgJournalStore` during a database
outage. The module PINS what the code does TODAY so that Phase 20 changes it deliberately;
it does not change any controller (controller fixes are Phase 20).

Pinned behaviors (a journal outage is the only fault injected):

  1. `SafeModeController.enter_safe_mode` sets the in-memory flag BEFORE journaling, so
     SAFE_MODE survives a journal outage, and the `StoreUnavailable` is NOT swallowed
     (T-17-22).
  2. `LiveEnablementController.disable` journals BEFORE flipping, so with a failing journal
     it raises and the controller STAYS ENABLED. This is the F-702 behavior, owned by
     Phase 20 (the disable must flip first, or be journaled by the caller afterwards).
  3. `expire_pending_entry` and `cancel_untriggered_protectives` journal the pre-image BEFORE
     the exchange call and sit outside their per-leg isolation, so with a failing journal
     NO exchange cancel is issued and the `StoreUnavailable` surfaces unwrapped.
  4. Consequently `emergency_manual_close` with a failing journal runs all four of its
     isolated steps (each failure is collected, none aborts a later step) but issues ZERO
     exchange cancels, leaves live orders enabled (via step 2) and enters SAFE_MODE (via
     step 1). It raises one `ExceptionGroup` holding four `StoreUnavailable`.

Behaviors 2-4 are UNSAFE gaps for an outage (see the 17-08 SUMMARY); they are pinned, not
fixed, here.
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


def test_disable_with_a_failing_journal_raises_and_the_controller_stays_enabled() -> None:
    journal = ToggleJournal()
    controller = _enabled_controller(journal)
    journal.down = True

    with pytest.raises(StoreUnavailable):
        controller.disable(operator_id="operator_alpha", now_utc=NOW_UTC)

    # F-702: the transition is journal-first, so the flag never flipped. Phase 20 changes this.
    assert controller.is_disabled is False
    assert controller.guard_placement(plan_hash=PLAN_HASH).is_no_trade is False


# --------------------------------------------------------------------------- #
# 3. Cancel steps journal before the exchange call.
# --------------------------------------------------------------------------- #


async def test_expire_pending_entry_issues_no_cancel_when_the_journal_is_down() -> None:
    journal = ToggleJournal(down=True)
    adapter = RecordingCancelAdapter()

    with pytest.raises(StoreUnavailable):
        await expire_pending_entry(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
            trigger_reason="operator_close",
        )

    assert adapter.calls == []


async def test_cancel_untriggered_protectives_issues_no_cancel_when_the_journal_is_down() -> None:
    journal = ToggleJournal(down=True)
    adapter = RecordingCancelAdapter()

    # The pre-image write sits outside the per-leg isolation: the outage surfaces
    # unwrapped on the first leg and no later leg is attempted.
    with pytest.raises(StoreUnavailable):
        await cancel_untriggered_protectives(
            plan_hash=PLAN_HASH,
            symbol=SYMBOL,
            adapter=adapter,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
        )

    assert adapter.calls == []
    assert journal.attempts == 1


# --------------------------------------------------------------------------- #
# 4. emergency_manual_close during a journal outage.
# --------------------------------------------------------------------------- #


async def test_emergency_close_with_a_failing_journal_runs_every_step_but_reaches_no_exchange() -> (
    None
):
    journal = ToggleJournal()
    enablement = _enabled_controller(journal)
    safe_mode = _safe_mode_controller(journal)
    adapter = RecordingCancelAdapter()
    journal.down = True
    attempts_before = journal.attempts

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

    # Every isolated step ran and failed on the journal (disable, SAFE_MODE, entry, protectives).
    failures = excinfo.value.exceptions
    assert len(failures) == 4
    assert all(isinstance(failure, StoreUnavailable) for failure in failures)
    assert journal.attempts - attempts_before == 4
    # SAFE_MODE was entered (flag set before journaling) ...
    assert safe_mode.in_safe_mode is True
    assert safe_mode.entered_reason == "MANUAL_CLOSE"
    # ... but live orders stay enabled (F-702) and the exchange was never asked to cancel.
    assert enablement.is_disabled is False
    assert adapter.calls == []


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
