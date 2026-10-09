"""Measured approval delay and SHADOW attribution of paper records (Phase 16, plan 16-35).

D-15 and SC3: the approval delay of a SHADOW record with a real human action is the measured
`acted_at_utc - requested_at_utc` of the approval row, together with the confirm timestamps; the
fixed `APPROVAL_DELAY_LAG_SECONDS` stays only as the documented default for a record with no
human action. The new SHADOW fields are optional and omitted from the canonical output when
absent, so every pinned Phase 7 to 10 digest is unchanged (T-16-82).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS, AttributionKind
from src.paper.journal import (
    PaperRecord,
    assemble_paper_record,
    canonical_record_dict,
    paper_records_digest,
)

FIXTURES = Path(__file__).parent / "fixtures" / "phase7"

LEGACY_KEYS = (
    "attribution",
    "epoch_id",
    "strategy_id",
    "strategy_version",
    "parameter_set_id",
    "parameter_set_hash",
    "experiment_id",
    "symbol",
    "signal_id",
    "plan_hash",
    "reason_code",
    "signal_detected_at_utc",
    "approval_acted_at_utc",
    "order_submitted_at_utc",
    "fill_time_utc",
)


def _case(kind: str) -> tuple[str, dict[str, Any]]:
    doc = json.loads((FIXTURES / "attribution_split" / "input.json").read_text(encoding="utf-8"))
    case = next(c for c in doc["cases"] if c["kind"] == kind)
    return doc["epoch_id"], copy.deepcopy(case)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _detected(case: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(case["signal"]["detected_at_utc"]).astimezone(UTC)


def _human_approval(case: dict[str, Any], *, action: str = "APPROVE") -> dict[str, Any]:
    """A real human approval: requested 3 s after the signal, acted 47 s later."""
    requested = _detected(case) + timedelta(seconds=3)
    approval = dict(case["approval"])
    approval["action"] = action
    approval["actor_id"] = "tg-user-1"
    approval["requested_at_utc"] = _iso(requested)
    approval["acted_at_utc"] = _iso(requested + timedelta(seconds=47))
    return approval


def _confirm(case: dict[str, Any]) -> dict[str, str]:
    acted = datetime.fromisoformat(_human_approval(case)["acted_at_utc"])
    issued = acted + timedelta(seconds=1)
    return {
        "confirm_requested_at_utc": _iso(issued),
        "confirmed_at_utc": _iso(issued + timedelta(seconds=12)),
    }


def _assemble_shadow_filled(
    case: dict[str, Any], epoch_id: str, **overrides: Any
) -> list[PaperRecord]:
    kwargs: dict[str, Any] = {
        "epoch_id": epoch_id,
        "signal": case["signal"],
        "trade_plan": case["trade_plan"],
        "approval": _human_approval(case),
        "order": case["order"],
        "fill": case["fill"],
        "mode": "SHADOW",
        "confirm": _confirm(case),
    }
    kwargs.update(overrides)
    return assemble_paper_record(**kwargs)


# --------------------------------------------------------------------------- #
# Task 1 - tracer: the measured delay reaches the record.
# --------------------------------------------------------------------------- #


def test_a_shadow_record_with_a_real_approval_carries_the_measured_delay() -> None:
    epoch_id, case = _case("filled_simulation")
    records = _assemble_shadow_filled(case, epoch_id)
    sim = next(r for r in records if r.attribution == AttributionKind.USER_EXECUTED_SIM)
    approval = _human_approval(case)

    assert sim.mode == "SHADOW"
    assert sim.approval_requested_at_utc is not None
    assert sim.approval_acted_at_utc is not None
    assert sim.approval_acted_at_utc - sim.approval_requested_at_utc == timedelta(seconds=47)
    assert sim.approval_acted_at_utc == datetime.fromisoformat(approval["acted_at_utc"])
    confirm = _confirm(case)
    assert sim.confirm_requested_at_utc == datetime.fromisoformat(
        confirm["confirm_requested_at_utc"]
    )
    assert sim.confirmed_at_utc == datetime.fromisoformat(confirm["confirmed_at_utc"])
    # The engine row carries the mode but no approval or confirm timestamps.
    system = next(r for r in records if r.attribution == AttributionKind.SYSTEM)
    assert system.mode == "SHADOW"
    assert system.approval_requested_at_utc is None
    assert system.confirmed_at_utc is None


def test_the_measured_delay_is_not_overridden_by_signal_plus_the_constant() -> None:
    """Must fail on the old behaviour (T-16-81): a real timestamp is never replaced by the lag.

    The old assembler raised for any acted_at_utc other than signal + 30 s; the new one records
    the real value and the delay differs from the constant.
    """
    epoch_id, case = _case("filled_simulation")
    records = _assemble_shadow_filled(case, epoch_id)
    sim = records[1]
    constant = _detected(case) + timedelta(seconds=APPROVAL_DELAY_LAG_SECONDS)
    assert sim.approval_acted_at_utc != constant
    assert sim.approval_acted_at_utc == _detected(case) + timedelta(seconds=50)


def test_a_human_action_without_its_acted_timestamp_cannot_fall_back_to_the_constant() -> None:
    epoch_id, case = _case("filled_simulation")
    approval = _human_approval(case)
    approval["acted_at_utc"] = None
    with pytest.raises(ValueError, match="human action"):
        _assemble_shadow_filled(case, epoch_id, approval=approval)


def test_a_human_action_without_its_requested_timestamp_is_refused() -> None:
    epoch_id, case = _case("filled_simulation")
    approval = _human_approval(case)
    del approval["requested_at_utc"]
    with pytest.raises(ValueError, match="requested_at_utc"):
        _assemble_shadow_filled(case, epoch_id, approval=approval)


def test_an_acted_timestamp_before_the_request_is_refused() -> None:
    epoch_id, case = _case("filled_simulation")
    approval = _human_approval(case)
    approval["acted_at_utc"] = _iso(
        datetime.fromisoformat(approval["requested_at_utc"]) - timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="before"):
        _assemble_shadow_filled(case, epoch_id, approval=approval)


def test_a_filled_shadow_record_needs_the_confirm_timestamps() -> None:
    epoch_id, case = _case("filled_simulation")
    with pytest.raises(ValueError, match="confirm"):
        _assemble_shadow_filled(case, epoch_id, confirm=None)


def test_a_record_with_no_human_action_keeps_the_documented_constant() -> None:
    epoch_id, case = _case("filled_simulation")
    expected = _detected(case) + timedelta(seconds=APPROVAL_DELAY_LAG_SECONDS)

    # Same behaviour with and without the SHADOW mode: the approval row is the simulator's.
    for mode in (None, "SHADOW"):
        records = assemble_paper_record(
            epoch_id=epoch_id,
            signal=case["signal"],
            trade_plan=case["trade_plan"],
            approval=case["approval"],
            order=case["order"],
            fill=case["fill"],
            mode=mode,
        )
        assert records[1].approval_acted_at_utc == expected
        assert records[1].approval_requested_at_utc is None
        assert records[1].confirmed_at_utc is None

    # A disagreeing timestamp on a record with no human action is still refused.
    bad = dict(case["approval"])
    bad["acted_at_utc"] = _iso(expected + timedelta(seconds=1))
    with pytest.raises(ValueError, match="disagrees"):
        assemble_paper_record(
            epoch_id=epoch_id,
            signal=case["signal"],
            trade_plan=case["trade_plan"],
            approval=bad,
            order=case["order"],
            fill=case["fill"],
            mode="SHADOW",
        )


def test_the_new_fields_are_omitted_from_the_canonical_output_when_absent() -> None:
    epoch_id, case = _case("filled_simulation")
    legacy = assemble_paper_record(
        epoch_id=epoch_id,
        signal=case["signal"],
        trade_plan=case["trade_plan"],
        approval=case["approval"],
        order=case["order"],
        fill=case["fill"],
    )
    for record in legacy:
        assert tuple(canonical_record_dict(record)) == LEGACY_KEYS
        assert record.mode is None
        assert record.test_only is False

    shadow = _assemble_shadow_filled(case, epoch_id)
    keys = tuple(canonical_record_dict(shadow[1]))
    assert keys[: len(LEGACY_KEYS)] == LEGACY_KEYS
    assert set(keys[len(LEGACY_KEYS) :]) == {
        "mode",
        "approval_requested_at_utc",
        "confirm_requested_at_utc",
        "confirmed_at_utc",
    }
    assert paper_records_digest(list(shadow)) != paper_records_digest(list(legacy))


def test_test_only_is_written_only_when_true() -> None:
    epoch_id, case = _case("filled_simulation")
    production = _assemble_shadow_filled(case, epoch_id)
    marked = _assemble_shadow_filled(case, epoch_id, test_only=True)
    assert "test_only" not in canonical_record_dict(production[1])
    assert canonical_record_dict(marked[1])["test_only"] is True
    assert marked[0].test_only is True and marked[1].test_only is True


def test_paper_record_validates_the_new_fields() -> None:
    epoch_id, case = _case("filled_simulation")
    base = _assemble_shadow_filled(case, epoch_id)[1]
    fields = {
        name: getattr(base, name)
        for name in base.__dataclass_fields__  # noqa: SLF001 - field listing only
    }
    with pytest.raises(ValueError, match="mode"):
        PaperRecord(**{**fields, "mode": "LIVE"})
    with pytest.raises(ValueError, match="UTC"):
        PaperRecord(**{**fields, "confirmed_at_utc": datetime(2026, 9, 19, 9, 5)})
    with pytest.raises(ValueError, match="test_only"):
        PaperRecord(**{**fields, "test_only": "yes"})
