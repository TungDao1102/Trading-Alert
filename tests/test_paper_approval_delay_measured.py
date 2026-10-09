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
from src.paper.attribution import (
    APPROVAL_DELAY_LAG_SECONDS,
    AttributionKind,
    ShadowOutcome,
    attribute_shadow_outcome,
)
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


# --------------------------------------------------------------------------- #
# Task 2 - attribution of every SHADOW outcome and loader acceptance.
# --------------------------------------------------------------------------- #


def _outcome(**kwargs: Any) -> ShadowOutcome:
    return ShadowOutcome(**kwargs)


@pytest.mark.parametrize(
    ("outcome", "kind", "reason"),
    [
        # APPROVE then CONFIRM.
        (
            _outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRMED"),
            AttributionKind.USER_EXECUTED_SIM,
            "",
        ),
        # SKIP.
        (_outcome(approval_action="SKIP_USER"), AttributionKind.OPPORTUNITY, "SKIP_USER"),
        (_outcome(approval_action="SKIP_BUSY"), AttributionKind.OPPORTUNITY, "SKIP_BUSY"),
        (_outcome(approval_action="CANCEL"), AttributionKind.OPPORTUNITY, "CANCEL"),
        # CANCEL at the confirm card.
        (
            _outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRM_CANCELLED"),
            AttributionKind.OPPORTUNITY,
            "SHADOW_CONFIRM_CANCELLED",
        ),
        # APPROVE after the plan expiry (REV-12): the press was refused.
        (
            _outcome(approval_action="APPROVE", approval_rejection_reason="APPROVAL_EXPIRED"),
            AttributionKind.OPPORTUNITY,
            "APPROVAL_EXPIRED",
        ),
        # Confirm past its TTL.
        (
            _outcome(
                approval_action="APPROVE",
                confirm_event="SHADOW_CONFIRM_EXPIRED",
                confirm_reason="CONFIRM_TTL_ELAPSED",
            ),
            AttributionKind.OPPORTUNITY,
            "SHADOW_CONFIRM_EXPIRED",
        ),
        # Card never delivered, restart, missing user id, gate refusal at CONFIRM: never executed.
        (
            _outcome(
                approval_action="APPROVE",
                confirm_event="SHADOW_CONFIRM_EXPIRED",
                confirm_reason="CARD_DELIVERY_FAILED",
            ),
            AttributionKind.OPPORTUNITY,
            "CARD_DELIVERY_FAILED",
        ),
        (
            _outcome(
                approval_action="APPROVE",
                confirm_event="SHADOW_CONFIRM_EXPIRED",
                confirm_reason="RUNTIME_RESTART",
            ),
            AttributionKind.OPPORTUNITY,
            "RUNTIME_RESTART",
        ),
        (
            _outcome(
                approval_action="APPROVE",
                confirm_event="SHADOW_CONFIRM_EXPIRED",
                confirm_reason="USER_ID_UNAVAILABLE",
            ),
            AttributionKind.OPPORTUNITY,
            "USER_ID_UNAVAILABLE",
        ),
        (
            _outcome(
                approval_action="APPROVE",
                confirm_event="SHADOW_CONFIRM_EXPIRED",
                confirm_reason="APPROVAL_EXPIRED",
            ),
            AttributionKind.OPPORTUNITY,
            "APPROVAL_EXPIRED",
        ),
        # Untouched plans: the PAPER-02 rule (07-CONTEXT D-03 line 24: "skipped/expired plans
        # retained with reason codes - never dropped"; assemble_paper_record Case 3 uses EXPIRED).
        (_outcome(plan_expired=True), AttributionKind.OPPORTUNITY, "EXPIRED"),
        (_outcome(plan_expired=False), AttributionKind.SYSTEM, ""),
    ],
)
def test_every_shadow_outcome_is_attributed(
    outcome: ShadowOutcome, kind: AttributionKind, reason: str
) -> None:
    assert attribute_shadow_outcome(outcome) == (kind, reason)


def test_an_approved_plan_that_was_not_confirmed_is_never_user_executed_sim() -> None:
    for reason in ("CONFIRM_TTL_ELAPSED", "CARD_DELIVERY_FAILED", "RUNTIME_RESTART", None):
        kind, _ = attribute_shadow_outcome(
            _outcome(
                approval_action="APPROVE",
                confirm_event="SHADOW_CONFIRM_EXPIRED",
                confirm_reason=reason,
            )
        )
        assert kind == AttributionKind.OPPORTUNITY


@pytest.mark.parametrize(
    "outcome",
    [
        _outcome(approval_action="APPROVE"),  # no terminal confirm event yet
        _outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRM_ISSUED"),
        _outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRM_REJECTED"),
        _outcome(approval_action="SIMULATE"),
        _outcome(approval_action="SKIP_USER", confirm_event="SHADOW_CONFIRMED"),
        _outcome(confirm_event="SHADOW_CONFIRMED"),
    ],
)
def test_an_undecided_or_inconsistent_outcome_is_refused(outcome: ShadowOutcome) -> None:
    with pytest.raises(ValueError):
        attribute_shadow_outcome(outcome)


def test_the_attribution_literals_equal_their_source_vocabulary() -> None:
    from src.domain.enums import ApprovalAction, RejectionReason
    from src.paper import attribution as attr
    from src.paper import shadow_confirm as sc

    assert attr.EVENT_CONFIRMED == sc.EVENT_SHADOW_CONFIRMED
    assert attr.EVENT_CONFIRM_CANCELLED == sc.EVENT_SHADOW_CONFIRM_CANCELLED
    assert attr.EVENT_CONFIRM_EXPIRED == sc.EVENT_SHADOW_CONFIRM_EXPIRED
    assert attr.REASON_CONFIRM_TTL_ELAPSED == sc.REASON_CONFIRM_TTL_ELAPSED
    assert RejectionReason.APPROVAL_EXPIRED.value == "APPROVAL_EXPIRED"
    for action in ("APPROVE", "SKIP_USER", "SKIP_BUSY", "CANCEL"):
        assert ApprovalAction(action).value == action


def test_attribution_kind_values_are_unchanged_byte_for_byte() -> None:
    assert [kind.value for kind in AttributionKind] == [
        "system",
        "user-executed-sim",
        "opportunity",
    ]


def test_attribution_module_still_imports_only_the_standard_library() -> None:
    import ast

    source = (Path(__file__).parent.parent / "src" / "paper" / "attribution.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    modules |= {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert modules <= {"__future__", "dataclasses", "enum"}


def _shadow_unfilled(
    case: dict[str, Any], epoch_id: str, outcome: ShadowOutcome, **kw: Any
) -> list[PaperRecord]:
    kwargs: dict[str, Any] = {
        "epoch_id": epoch_id,
        "signal": case["signal"],
        "trade_plan": case["trade_plan"],
        "approval": None,
        "order": None,
        "fill": None,
        "mode": "SHADOW",
        "shadow_outcome": outcome,
    }
    kwargs.update(kw)
    return assemble_paper_record(**kwargs)


def test_the_assembler_applies_the_shadow_attribution() -> None:
    epoch_id, case = _case("filled_simulation")

    # APPROVE then CONFIRM, stated through the outcome.
    filled = _assemble_shadow_filled(
        case,
        epoch_id,
        shadow_outcome=_outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRMED"),
    )
    assert [r.attribution for r in filled] == [
        AttributionKind.SYSTEM,
        AttributionKind.USER_EXECUTED_SIM,
    ]

    # SKIP with a real requested / acted pair.
    skipped = _shadow_unfilled(
        case,
        epoch_id,
        _outcome(approval_action="SKIP_USER"),
        approval=_human_approval(case, action="SKIP_USER"),
    )
    assert [r.attribution for r in skipped] == [AttributionKind.SYSTEM, AttributionKind.OPPORTUNITY]
    assert skipped[1].reason_code == "SKIP_USER"
    assert skipped[1].approval_requested_at_utc is not None
    assert skipped[1].approval_acted_at_utc is not None
    assert skipped[1].approval_acted_at_utc - skipped[1].approval_requested_at_utc == timedelta(
        seconds=47
    )
    assert skipped[1].order_submitted_at_utc is None and skipped[1].fill_time_utc is None

    # Confirm cancelled: the card's issue time is kept, nothing was confirmed.
    cancelled = _shadow_unfilled(
        case,
        epoch_id,
        _outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRM_CANCELLED"),
        approval=_human_approval(case),
        confirm={"confirm_requested_at_utc": _confirm(case)["confirm_requested_at_utc"]},
    )
    assert cancelled[1].reason_code == "SHADOW_CONFIRM_CANCELLED"
    assert cancelled[1].confirm_requested_at_utc is not None
    assert cancelled[1].confirmed_at_utc is None

    # Card delivery failed: opportunity carrying that reason.
    failed = _shadow_unfilled(
        case,
        epoch_id,
        _outcome(
            approval_action="APPROVE",
            confirm_event="SHADOW_CONFIRM_EXPIRED",
            confirm_reason="CARD_DELIVERY_FAILED",
        ),
        approval=_human_approval(case),
    )
    assert failed[1].attribution == AttributionKind.OPPORTUNITY
    assert failed[1].reason_code == "CARD_DELIVERY_FAILED"

    # Untouched and expired, then untouched and still open.
    expired = _shadow_unfilled(case, epoch_id, _outcome(plan_expired=True))
    assert expired[1].reason_code == "EXPIRED"
    alone = _shadow_unfilled(case, epoch_id, _outcome())
    assert [r.attribution for r in alone] == [AttributionKind.SYSTEM]
    assert all(r.mode == "SHADOW" for r in (*skipped, *cancelled, *failed, *expired, *alone))


def test_the_assembler_refuses_inconsistent_shadow_inputs() -> None:
    epoch_id, case = _case("filled_simulation")
    # Legs for a non-executed outcome.
    with pytest.raises(ValueError, match="legs"):
        _shadow_unfilled(
            case,
            epoch_id,
            _outcome(approval_action="SKIP_USER"),
            approval=_human_approval(case, action="SKIP_USER"),
            order=case["order"],
            fill=case["fill"],
        )
    # An executed outcome without legs.
    with pytest.raises(ValueError, match="PARTIAL_LEG"):
        _shadow_unfilled(
            case,
            epoch_id,
            _outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRMED"),
        )
    # A confirmed timestamp on an opportunity.
    with pytest.raises(ValueError, match="confirmed"):
        _shadow_unfilled(
            case,
            epoch_id,
            _outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRM_CANCELLED"),
            approval=_human_approval(case),
            confirm=_confirm(case),
        )
    # shadow_outcome outside SHADOW mode.
    with pytest.raises(ValueError, match="SHADOW"):
        _shadow_unfilled(case, epoch_id, _outcome(plan_expired=True), mode=None)
    # A filled outcome with the simulator approval row (no human action).
    with pytest.raises(ValueError, match="human"):
        _assemble_shadow_filled(
            case,
            epoch_id,
            approval=case["approval"],
            shadow_outcome=_outcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRMED"),
        )


def _paper_row(**extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "attribution": "user-executed-sim",
        "epoch_id": "epoch-1",
        "strategy_id": "trend-pullback",
        "strategy_version": "v1",
        "parameter_set_id": "ps-1",
        "parameter_set_hash": "h" * 64,
        "experiment_id": "exp-1",
        "symbol": "BTCUSDT",
        "signal_id": "sig-1",
        "plan_hash": "p" * 64,
        "reason_code": "",
        "signal_detected_at_utc": "2026-02-01T08:00:00+00:00",
        "approval_acted_at_utc": "2026-02-01T08:00:50+00:00",
        "order_submitted_at_utc": "2026-02-01T08:01:00+00:00",
        "fill_time_utc": "2026-02-01T08:30:00+00:00",
    }
    row.update(extra)
    return row


def test_the_evidence_loader_accepts_the_optional_shadow_keys() -> None:
    from src.adapters.analytics_files import EvidenceFileError, _load_paper_record

    legacy = _load_paper_record(_paper_row(), 0)
    assert legacy.mode is None and legacy.test_only is False
    assert legacy.approval_requested_at_utc is None and legacy.confirmed_at_utc is None

    shadow = _load_paper_record(
        _paper_row(
            mode="SHADOW",
            approval_requested_at_utc="2026-02-01T08:00:03+00:00",
            confirm_requested_at_utc="2026-02-01T08:00:51+00:00",
            confirmed_at_utc="2026-02-01T08:01:03+00:00",
            test_only=True,
        ),
        0,
    )
    assert shadow.mode == "SHADOW" and shadow.test_only is True
    assert shadow.approval_acted_at_utc is not None
    assert shadow.approval_requested_at_utc is not None
    assert shadow.approval_acted_at_utc - shadow.approval_requested_at_utc == timedelta(seconds=47)

    # An explicit null is the same as absent.
    explicit = _load_paper_record(_paper_row(mode=None, confirmed_at_utc=None), 0)
    assert explicit.mode is None and explicit.confirmed_at_utc is None

    for bad in (
        {"unknown_key": 1},
        {"mode": "LIVE"},
        {"test_only": "yes"},
        {"confirmed_at_utc": "2026-02-01T08:01:03+07:00"},
        {"confirmed_at_utc": "not a date"},
    ):
        with pytest.raises(EvidenceFileError, match="paper"):
            _load_paper_record(_paper_row(**bad), 0)


def test_a_shadow_record_round_trips_through_its_canonical_dict_and_the_loader() -> None:
    from src.adapters.analytics_files import _load_paper_record

    epoch_id, case = _case("filled_simulation")
    for record in _assemble_shadow_filled(case, epoch_id, test_only=True):
        loaded = _load_paper_record(canonical_record_dict(record), 0)
        assert loaded == record
