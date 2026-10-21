"""Pure journal records for the user-data stream's first callers (plan 18-08, G4-034, D-08).

Pins `src.domain.stream_records`:

  - `ExitEvidence` is frozen and validated (source enum, non-empty reference and correlation id,
    UTC-aware observation time, optional detail of at most 200 characters);
  - `exit_evidence_event` is a pure function of its inputs: deterministic id built by
    `correlated_event_id`, sorted-key compact JSON payload with exactly five text keys, no
    Decimal, no wall clock, no credential-shaped reference;
  - `stream_anomaly_event` keys its id on (session, anomaly kind, payload hash), so a duplicate
    frame in one session is one record; `kind` is a plain string (no adapter import).
"""

from __future__ import annotations

import ast
import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from src.adapters.binance_userdata_events import StreamAnomalyKind
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.stream_records import (
    STREAM_ANOMALY,
    UNKNOWN_EXIT_EVIDENCE,
    USER_DATA_STREAM,
    EvidenceSource,
    ExitEvidence,
    exit_evidence_event,
    stream_anomaly_event,
)

T_OBS = datetime(2026, 9, 19, 12, 0, 1, 250000, tzinfo=UTC)
NOW = datetime(2026, 9, 19, 12, 0, 2, tzinfo=UTC)
ORDER_ID = "a" * 64

REPO_ROOT = Path(__file__).resolve().parent.parent


def evidence(**overrides: object) -> ExitEvidence:
    values: dict[str, object] = {
        "source": EvidenceSource.USER_DATA_EVENT,
        "observed_at_utc": T_OBS,
        "reference": "ORDER_TRADE_UPDATE:E=1726747201250:i=8389765",
        "correlation_id": "uds-session-1",
    }
    values.update(overrides)
    return ExitEvidence(**values)  # type: ignore[arg-type]


def order_event(ev: ExitEvidence | None = None, **overrides: object) -> JournalEvent:
    values: dict[str, object] = {
        "entity_type": "ORDER",
        "entity_id": ORDER_ID,
        "from_status": "UNKNOWN",
        "to_status": "FILLED",
        "evidence": ev if ev is not None else evidence(),
        "now_utc": NOW,
        "order_id": ORDER_ID,
    }
    values.update(overrides)
    return exit_evidence_event(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# ExitEvidence
# --------------------------------------------------------------------------- #


def test_evidence_sources_are_exactly_rest_reconcile_and_user_data_event() -> None:
    assert {s.value for s in EvidenceSource} == {"REST_RECONCILE", "USER_DATA_EVENT"}


def test_exit_evidence_is_frozen() -> None:
    ev = evidence()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.reference = "other"  # type: ignore[misc]


@pytest.mark.parametrize("source", ["USER_DATA_EVENT", "TIMEOUT", None])
def test_source_must_be_an_evidence_source_member(source: object) -> None:
    with pytest.raises(TypeError):
        evidence(source=source)


@pytest.mark.parametrize("field", ["reference", "correlation_id"])
@pytest.mark.parametrize("bad", ["", None, 7])
def test_reference_and_correlation_id_are_non_empty_strings(field: str, bad: object) -> None:
    with pytest.raises(ValueError):
        evidence(**{field: bad})


@pytest.mark.parametrize("field", ["reference", "correlation_id"])
def test_reference_and_correlation_id_fit_the_journal_columns(field: str) -> None:
    evidence(**{field: "r" * 128})
    with pytest.raises(ValueError):
        evidence(**{field: "r" * 129})


@pytest.mark.parametrize(
    "reference",
    [
        "listenKey=pqia91ma19a5s61cv6a81va65sdf19v8a65a1a5s61cv6a81va65sdf19v8a65a1",
        "apiKey:abc",
        "signature=deadbeef",
        "with space",
    ],
)
def test_reference_refuses_credential_shaped_or_free_text(reference: str) -> None:
    with pytest.raises(ValueError):
        evidence(reference=reference)


def test_observed_at_must_be_utc_aware() -> None:
    with pytest.raises(ValueError):
        evidence(observed_at_utc=datetime(2026, 9, 19, 12, 0))  # noqa: DTZ001
    with pytest.raises(ValueError):
        evidence(observed_at_utc=datetime(2026, 9, 19, 12, 0, tzinfo=timezone(timedelta(hours=7))))


def test_detail_is_optional_and_at_most_200_characters() -> None:
    assert evidence().detail is None
    assert evidence(detail="x" * 200).detail == "x" * 200
    with pytest.raises(ValueError):
        evidence(detail="x" * 201)
    with pytest.raises(ValueError):
        evidence(detail="")


# --------------------------------------------------------------------------- #
# exit_evidence_event
# --------------------------------------------------------------------------- #


def test_exit_evidence_event_id_is_the_correlated_event_id() -> None:
    event = order_event()
    assert event.journal_event_id == correlated_event_id(
        prefix="ev",
        correlation_id="uds-session-1",
        event_type=UNKNOWN_EXIT_EVIDENCE,
        entity_id=ORDER_ID,
        step="UNKNOWN->FILLED",
    )
    assert event.event_type == "UNKNOWN_EXIT_EVIDENCE"
    assert event.entity_type == "ORDER"
    assert event.entity_id == ORDER_ID
    assert event.correlation_id == "uds-session-1"
    assert event.order_id == ORDER_ID
    assert event.position_id is None
    assert event.occurred_at_utc == NOW


def test_exit_evidence_payload_is_sorted_compact_json_with_exactly_five_text_keys() -> None:
    event = order_event(evidence(detail="never journaled"))
    payload = json.loads(event.payload_json)
    assert payload == {
        "evidence_source": "USER_DATA_EVENT",
        "from_status": "UNKNOWN",
        "observed_at_utc": T_OBS.isoformat(),
        "reference": "ORDER_TRADE_UPDATE:E=1726747201250:i=8389765",
        "to_status": "FILLED",
    }
    assert all(isinstance(v, str) for v in payload.values())
    assert event.payload_json == json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_same_inputs_give_the_same_event() -> None:
    assert order_event() == order_event()


def test_distinct_steps_or_sources_give_distinct_records() -> None:
    base = order_event()
    other_step = order_event(to_status="CANCELED")
    rest = order_event(evidence(source=EvidenceSource.REST_RECONCILE))
    assert other_step.journal_event_id != base.journal_event_id
    # Same correlation, entity and step: same id, so a different source is a journal conflict
    # (never a silent second record for the same exit).
    assert rest.journal_event_id == base.journal_event_id
    assert rest.payload_json != base.payload_json


def test_position_event_sets_the_position_link() -> None:
    pos_id = "b" * 64
    event = order_event(
        entity_type="POSITION",
        entity_id=pos_id,
        to_status="CLOSED",
        order_id=None,
        position_id=pos_id,
    )
    assert event.entity_type == "POSITION"
    assert event.position_id == pos_id
    assert event.order_id is None


@pytest.mark.parametrize("entity_type", ["SIGNAL", "order", ""])
def test_only_order_and_position_have_unknown_exits(entity_type: str) -> None:
    with pytest.raises(ValueError):
        order_event(entity_type=entity_type)


def test_an_execution_intent_has_unknown_exits_too() -> None:
    """Plan 20-10 (D-11, D-12): an UNKNOWN ENTRY intent closed by a REST reconcile is journaled."""
    event = order_event(
        evidence(source=EvidenceSource.REST_RECONCILE, reference="x-clientorderid"),
        entity_type="EXECUTION_INTENT",
        entity_id="appr-1",
        to_status="REJECTED",
    )

    assert event.entity_type == "EXECUTION_INTENT"
    assert event.event_type == UNKNOWN_EXIT_EVIDENCE


def test_from_status_must_be_unknown_and_differ_from_to_status() -> None:
    with pytest.raises(ValueError):
        order_event(from_status="NEW")
    with pytest.raises(ValueError):
        order_event(to_status="UNKNOWN")


def test_now_utc_must_be_utc_aware() -> None:
    with pytest.raises(ValueError):
        order_event(now_utc=datetime(2026, 9, 19, 12, 0))  # noqa: DTZ001


def test_evidence_must_be_exit_evidence() -> None:
    with pytest.raises(TypeError):
        order_event(evidence=object())


def test_module_is_pure_stdlib_plus_domain_journal() -> None:
    source = (REPO_ROOT / "src" / "domain" / "stream_records.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    project = {name for name in imported if name.startswith("src")}
    assert project == {"src.domain.journal"}
    assert not any(name.split(".")[0] in {"sqlalchemy", "decimal", "time"} for name in imported)


# --------------------------------------------------------------------------- #
# stream_anomaly_event
# --------------------------------------------------------------------------- #

SHA = "0123456789abcdef" * 4


def anomaly(**overrides: object) -> JournalEvent:
    values: dict[str, object] = {
        "kind": "UNKNOWN_ORDER_STATUS",
        "event_name": "ORDER_TRADE_UPDATE",
        "field": "o.X",
        "detail": "o.X: unrecognised value (str)",
        "payload_sha256": SHA,
        "observed_at_utc": T_OBS,
        "session_id": "uds-session-1",
    }
    values.update(overrides)
    return stream_anomaly_event(**values)  # type: ignore[arg-type]


def test_stream_anomaly_event_identity_fields() -> None:
    event = anomaly()
    assert event.event_type == STREAM_ANOMALY == "STREAM_ANOMALY"
    assert event.entity_type == USER_DATA_STREAM == "USER_DATA_STREAM"
    assert event.entity_id == f"UNKNOWN_ORDER_STATUS:{SHA}"
    assert event.correlation_id == "uds-session-1"
    assert event.occurred_at_utc == T_OBS
    assert event.journal_event_id == correlated_event_id(
        prefix="sa",
        correlation_id="uds-session-1",
        event_type="STREAM_ANOMALY",
        entity_id=f"UNKNOWN_ORDER_STATUS:{SHA}",
        step=SHA,
    )
    assert (event.order_id, event.position_id, event.signal_id) == (None, None, None)


def test_stream_anomaly_payload_is_sorted_json_of_exactly_six_keys() -> None:
    event = anomaly()
    payload = json.loads(event.payload_json)
    assert payload == {
        "kind": "UNKNOWN_ORDER_STATUS",
        "event_name": "ORDER_TRADE_UPDATE",
        "field": "o.X",
        "detail": "o.X: unrecognised value (str)",
        "payload_sha256": SHA,
        "observed_at_utc": T_OBS.isoformat(),
    }
    assert event.payload_json == json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_optional_event_name_and_field_are_json_null() -> None:
    payload = json.loads(anomaly(event_name=None, field=None).payload_json)
    assert payload["event_name"] is None and payload["field"] is None


def test_duplicate_frame_in_one_session_is_one_record() -> None:
    first = anomaly()
    later = anomaly(observed_at_utc=T_OBS + timedelta(seconds=5))
    assert later.journal_event_id == first.journal_event_id


def test_other_session_kind_or_payload_is_another_record() -> None:
    base = anomaly().journal_event_id
    assert anomaly(session_id="uds-session-2").journal_event_id != base
    assert anomaly(kind="MALFORMED_PAYLOAD").journal_event_id != base
    assert anomaly(payload_sha256="f" * 64).journal_event_id != base


def test_every_stream_anomaly_kind_is_accepted_as_plain_text() -> None:
    for kind in StreamAnomalyKind:
        assert anomaly(kind=kind.value).entity_id == f"{kind.value}:{SHA}"


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": ""},
        {"kind": "lower_case"},
        {"kind": "K" * 65},
        {"payload_sha256": "F" * 64},
        {"payload_sha256": "0" * 63},
        {"detail": ""},
        {"detail": "d" * 201},
        {"event_name": ""},
        {"event_name": "e" * 65},
        {"field": "f" * 65},
        {"session_id": ""},
        {"session_id": "s" * 129},
        {"observed_at_utc": datetime(2026, 9, 19, 12, 0)},  # noqa: DTZ001
    ],
)
def test_stream_anomaly_event_validates_its_inputs(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        anomaly(**overrides)
