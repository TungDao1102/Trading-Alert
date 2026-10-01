"""Enablement controller behavior tests (Phase 9, plan 09-04).

Per D-04 (09-03) + EXECUTION_SPEC.md section 11: `LiveEnablementController`
defaults `LIVE_ORDERS_DISABLED=true`, an explicit operator `enable()`
allows placement, and an operator `disable()` (the emergency
manual-close path) composes with `SafeModeController` to block new
entries on both surfaces simultaneously.

The behaviors pinned here:

  1. Default-disabled blocks placement (mirrors 09-03 Beh. 5, standalone
     in this new suite).
  2. Explicit `enable()` allows placement (`guard_placement` PASSes).
  3. Emergency manual-close (`disable()`) plus SAFE_MODE composition
     blocks new entries on both the enablement guard and the SAFE_MODE
     guard.
  4. Secret-free log scan: every journaled event (enablement
     transitions plus health-check probes) is free of key/secret/
     token/signature substrings.

The tests load the golden fixture pairs
(`tests/fixtures/phase9/enablement/{enabled,emergency}/{input,expected}.json`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain.enums import KillGateState

PHASE9_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase9"
ENABLEMENT_FIXTURES_DIR = PHASE9_FIXTURES_DIR / "enablement"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


class FakeJournal:
    """In-memory journal that records every event."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def _passing_health_verdict() -> Any:
    """A complete, all-PASS `HealthVerdict` (09-REVIEW WR-08)."""
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    observed = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    return run_health_checks(
        results=[
            HealthCheckResult(check_name=name, status="PASS", detail="ok", observed_at_utc=observed)
            for name in ALL_CHECK_NAMES
        ]
    )


# --------------------------------------------------------------------------- #
# Beh. 1 — default-disabled blocks placement.
# --------------------------------------------------------------------------- #


def test_default_disabled_blocks_placement() -> None:
    """Beh. 1: a default-constructed controller has LIVE_ORDERS_DISABLED
    true and blocks placement with reason code DISABLED.
    """
    from src.execution.enablement import LiveEnablementController

    journal = FakeJournal()
    controller = LiveEnablementController(journal=journal)

    assert controller.is_disabled is True
    verdict = controller.guard_placement(plan_hash="test_plan_hash")
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "DISABLED"


# --------------------------------------------------------------------------- #
# Beh. 2 — explicit enable allows placement.
# --------------------------------------------------------------------------- #


def test_explicit_enable_allows_placement() -> None:
    """Beh. 2: an explicit operator `enable()` flips the flag and
    `guard_placement` PASSes.
    """
    from src.execution.enablement import LiveEnablementController

    case_dir = ENABLEMENT_FIXTURES_DIR / "enabled"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    journal = FakeJournal()
    controller = LiveEnablementController(journal=journal)
    controller.enable(
        operator_id=case_input["operator_id"],
        now_utc=_parse_utc(case_input["enable_at_utc"]),
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )

    assert controller.is_disabled is False
    verdict = controller.guard_placement(plan_hash=case_input["plan_hash"])
    assert verdict.is_no_trade == expected["is_no_trade"]
    assert verdict.reason_code == expected["reason_code"]

    # The enable transition was journaled before the flag flipped.
    assert len(journal.events) == 1
    assert journal.events[0].event_type == "LIVE_ORDERS_ENABLED"


# --------------------------------------------------------------------------- #
# Beh. 3 — emergency manual-close plus SAFE_MODE blocks new entries.
# --------------------------------------------------------------------------- #


def test_emergency_manual_close_plus_safe_mode_blocks_new_entries() -> None:
    """Beh. 3: an emergency manual-close (`disable()`) composes with
    `SafeModeController.enter_safe_mode` to block new entries on both
    the enablement guard and the SAFE_MODE guard.
    """
    from src.execution.enablement import LiveEnablementController
    from src.reconcile.safe_mode import SafeModeController

    case_dir = ENABLEMENT_FIXTURES_DIR / "emergency"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    enablement_journal = FakeJournal()
    controller = LiveEnablementController(journal=enablement_journal)
    controller.enable(
        operator_id=case_input["operator_id"],
        now_utc=_parse_utc(case_input["enable_at_utc"]),
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    assert controller.is_disabled is False  # sanity: was enabled first

    # Operator performs an emergency manual close: disable live orders.
    controller.disable(
        operator_id=case_input["operator_id"],
        now_utc=_parse_utc(case_input["disable_at_utc"]),
    )

    enablement_verdict = controller.guard_placement(plan_hash=case_input["plan_hash"])
    assert enablement_verdict.is_no_trade == expected["enablement_is_no_trade"]
    assert enablement_verdict.reason_code == expected["enablement_reason_code"]

    # SAFE_MODE composition: the same emergency also forces SAFE_MODE,
    # which blocks new entries on the reconciler's guard independently.
    safe_mode_journal = FakeJournal()

    class _NoOpAdapter:
        async def snapshot_open_normal_orders(self, *, symbol=None):
            return []

        async def snapshot_open_algo_orders(self, *, symbol=None):
            return []

        async def snapshot_positions(self, *, symbol=None):
            return []

    safe_mode_controller = SafeModeController(adapter=_NoOpAdapter(), journal=safe_mode_journal)
    safe_mode_controller.enter_safe_mode(
        reason=case_input["safe_mode_reason"],
        now_utc=_parse_utc(case_input["disable_at_utc"]),
    )
    safe_mode_verdict = safe_mode_controller.guard_new_entries(trade_plan=None)
    assert safe_mode_verdict.is_no_trade == expected["safe_mode_is_no_trade"]
    assert safe_mode_verdict.reason_code == expected["safe_mode_reason_code"]


# --------------------------------------------------------------------------- #
# Beh. 4 — secret-free log scan across enablement + health-check journals.
# --------------------------------------------------------------------------- #


def test_secret_free_log_scan_across_enablement_and_health_events() -> None:
    """Beh. 4: every journaled event (enablement transitions plus
    health-check probes) is free of key/secret/token/signature
    substrings (T-9-15).
    """
    from datetime import timedelta

    from src.execution.enablement import LiveEnablementController
    from src.ops.health import check_market_feed_freshness, check_ws_connection_state

    now = datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC)
    journal = FakeJournal()

    controller = LiveEnablementController(journal=journal)
    controller.enable(
        operator_id="operator_alpha",
        now_utc=now,
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    controller.disable(operator_id="operator_alpha", now_utc=now + timedelta(minutes=1))

    check_market_feed_freshness(
        last_market_event_at_utc=now,
        now_utc=now,
        staleness_threshold=timedelta(seconds=60),
        journal=journal,
    )
    check_ws_connection_state(connected=True, now_utc=now, journal=journal)

    forbidden_substrings = ("key", "secret", "token", "signature")
    for event in journal.events:
        haystack = json.dumps(
            {
                "event_type": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "payload_json": event.payload_json,
            }
        ).lower()
        for substring in forbidden_substrings:
            assert substring not in haystack, (
                f"forbidden substring {substring!r} found in journal event "
                f"{event.journal_event_id!r}: {haystack!r}"
            )


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-08 — RED or unevaluated health blocks enablement.
# --------------------------------------------------------------------------- #


def test_enable_refuses_failing_missing_or_partial_health() -> None:
    import pytest
    from src.execution.enablement import LiveEnablementController
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    observed = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)

    def _result(name: str, status: str = "PASS") -> Any:
        return HealthCheckResult(
            check_name=name, status=status, detail="x", observed_at_utc=observed
        )

    failing = run_health_checks(
        results=[_result(n, "FAIL" if i == 0 else "PASS") for i, n in enumerate(ALL_CHECK_NAMES)]
    )
    partial = run_health_checks(results=[_result(ALL_CHECK_NAMES[2])])
    for verdict in (failing, partial, None):
        journal = FakeJournal()
        controller = LiveEnablementController(journal=journal)
        with pytest.raises(ValueError, match="passing health verdict"):
            controller.enable(
                operator_id="operator_alpha",
                now_utc=observed,
                health_verdict=verdict,
                kill_gate_state=KillGateState.WITHIN_BUDGET,
            )
        assert controller.is_disabled is True
        assert journal.events == []


def test_journal_payload_records_the_post_transition_state() -> None:
    """WR-10: LIVE_ORDERS_ENABLED carries live_orders_disabled=false (the
    state it establishes) and the prior state explicitly."""
    from src.execution.enablement import LiveEnablementController

    journal = FakeJournal()
    controller = LiveEnablementController(journal=journal)
    now = datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC)
    controller.enable(
        operator_id="operator_alpha",
        now_utc=now,
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    controller.disable(operator_id="operator_alpha", now_utc=now)

    enabled, disabled = (json.loads(e.payload_json) for e in journal.events)
    assert journal.events[0].event_type == "LIVE_ORDERS_ENABLED"
    assert enabled["live_orders_disabled"] is False
    assert enabled["live_orders_disabled_before"] is True
    assert journal.events[1].event_type == "LIVE_ORDERS_DISABLED"
    assert disabled["live_orders_disabled"] is True
    assert disabled["live_orders_disabled_before"] is False


# --------------------------------------------------------------------------- #
# Phase 10 D-03 — the terminal kill-gate state refuses enablement before any side effect.
# --------------------------------------------------------------------------- #


def test_enable_refuses_insufficient_edge_before_journal_or_flag() -> None:
    import pytest
    from src.execution.enablement import LiveEnablementController

    now = datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC)
    journal = FakeJournal()
    controller = LiveEnablementController(journal=journal)
    with pytest.raises(ValueError, match="INSUFFICIENT_EDGE"):
        controller.enable(
            operator_id="operator_alpha",
            now_utc=now,
            health_verdict=_passing_health_verdict(),
            kill_gate_state=KillGateState.INSUFFICIENT_EDGE,
        )
    assert controller.is_disabled is True
    assert journal.events == []


def test_enable_refuses_unevaluated_or_non_state_kill_gate_values() -> None:
    import pytest
    from src.execution.enablement import LiveEnablementController

    now = datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC)
    for bad in (None, "INSUFFICIENT_EDGE", "WITHIN_BUDGET", 3):
        journal = FakeJournal()
        controller = LiveEnablementController(journal=journal)
        with pytest.raises(ValueError, match="evaluated kill-gate state"):
            controller.enable(
                operator_id="operator_alpha",
                now_utc=now,
                health_verdict=_passing_health_verdict(),
                kill_gate_state=bad,  # type: ignore[arg-type]
            )
        assert controller.is_disabled is True
        assert journal.events == []


def test_enable_permits_within_budget_and_passing_candidate() -> None:
    from src.execution.enablement import LiveEnablementController

    now = datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC)
    for state in (KillGateState.WITHIN_BUDGET, KillGateState.PASSING_CANDIDATE):
        journal = FakeJournal()
        controller = LiveEnablementController(journal=journal)
        controller.enable(
            operator_id="operator_alpha",
            now_utc=now,
            health_verdict=_passing_health_verdict(),
            kill_gate_state=state,
        )
        assert controller.is_disabled is False
        assert [e.event_type for e in journal.events] == ["LIVE_ORDERS_ENABLED"]


def test_enable_still_validates_operator_and_health_before_the_kill_gate() -> None:
    import pytest
    from src.execution.enablement import LiveEnablementController

    now = datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC)
    controller = LiveEnablementController(journal=FakeJournal())
    with pytest.raises(ValueError, match="passing health verdict"):
        controller.enable(
            operator_id="operator_alpha",
            now_utc=now,
            health_verdict=None,
            kill_gate_state=KillGateState.INSUFFICIENT_EDGE,
        )


def test_enable_journal_payload_key_set_is_unchanged_by_the_kill_gate_gate() -> None:
    from src.execution.enablement import LiveEnablementController

    journal = FakeJournal()
    controller = LiveEnablementController(journal=journal)
    controller.enable(
        operator_id="operator_alpha",
        now_utc=datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC),
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    payload = json.loads(journal.events[0].payload_json)
    assert set(payload) == {"operator_id", "live_orders_disabled", "live_orders_disabled_before"}
    assert "KillGate" not in journal.events[0].payload_json
    assert "kill_gate" not in journal.events[0].payload_json


def test_enablement_module_imports_no_analytics_or_heavy_dependencies() -> None:
    import ast

    source = (Path(__file__).parent.parent / "src" / "execution" / "enablement.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    assert "src.domain.enums" in imported
    for name in imported:
        assert not name.startswith("src.analytics"), name
        assert name.split(".")[0] not in {"sqlalchemy", "pydantic", "polars", "binance_sdk"}, name
