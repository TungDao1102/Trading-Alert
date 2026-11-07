"""The Demo soak evaluator, over fixture journals built in the test (plan 25-07, criterion 3).

`scripts/evaluate_demo_soak.py` judges the live Demo soak from the journal: the registration hash,
the order-after-registration rule, the effective window with the restart rule, reconcile
divergence, positions without a stop, duplicate entries, alerts and health verdicts, and the owner
round trips. Every journal here is built from `JournalEvent` objects with the event names imported
from the modules that produce them; no journal file is typed by hand.

Evidence label: executed unit tests, SYNTHETIC journals. No Binance, no Telegram, no database.
Times are TEST_ONLY.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import evaluate_demo_soak as soak
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.protection import (
    BRANCH_B1_ENTRY_NOT_TERMINAL,
    BRANCH_B5_STOP_REJECTED,
    DIVERGENCE_KIND_DOUBLED_POSITION,
    DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
    DIVERGENCE_KIND_POSITION_WITHOUT_STOP,
    EVENT_CLOSE_REQUIRED,
    EVENT_PROTECTION_TRANSITION,
    REASON_FIRST_FILL_REST,
    REASON_FIRST_FILL_STREAM,
    REASON_STOP_LOST_AFTER_PROTECTED,
    ProtectionState,
)
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME
from src.live.health import VERDICT_EVENT_TYPE
from src.ops.alerts import EVENT_OPERATIONAL_ALERT
from src.reconcile.compare import DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID
from src.reconcile.loop import RECONCILE_TICK

T0 = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
COMMITTED_AT = T0 - timedelta(days=1)
NOW = datetime(2026, 12, 15, 9, 0, tzinfo=UTC)
IMAGE_COMMIT = "a" * 40
ALLOWED_DEGRADED = ["candle_freshness"]


def day(n: float) -> datetime:
    return T0 + timedelta(days=n)


def make_event(
    event_type: str,
    at: datetime,
    *,
    payload: dict[str, Any] | None = None,
    trade_plan_id: str | None = None,
    entity_id: str = "entity",
) -> JournalEvent:
    body = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="t",
            event_type=event_type,
            entity_id=f"{entity_id}|{trade_plan_id}",
            occurred_at_utc=at,
            payload_json=body,
        ),
        occurred_at_utc=at,
        event_type=event_type,
        entity_type="Test",
        entity_id=entity_id,
        correlation_id="corr",
        trade_plan_id=trade_plan_id,
        payload_json=body,
    )


def outcome(at: datetime, plan: str, *, no_trade: bool = False) -> JournalEvent:
    return make_event(
        EVENT_PLACEMENT_OUTCOME,
        at,
        payload={"is_no_trade": no_trade, "reason_code": "REFUSED" if no_trade else "PLACED"},
        trade_plan_id=plan,
        entity_id=f"approval-{plan}",
    )


def healthy(at: datetime, *, degraded: list[str] | None = None, failing: list[str] | None = None):
    return make_event(
        VERDICT_EVENT_TYPE,
        at,
        payload={"degraded": degraded or [], "failing": failing or [], "is_no_trade": False},
        entity_id="live_health",
    )


def tick(at: datetime, counts: dict[str, int] | None = None) -> JournalEvent:
    counts = counts or {}
    return make_event(
        RECONCILE_TICK,
        at,
        payload={
            "outcome": "COMPARED",
            "divergence_count": sum(counts.values()),
            "counts": counts,
            "safe_mode_reasons": [],
        },
        entity_id="reconcile",
    )


def transition(
    at: datetime, plan: str, *, to: ProtectionState, reason: str, previous: str = "NONE"
) -> JournalEvent:
    return make_event(
        EVENT_PROTECTION_TRANSITION,
        at,
        payload={
            "from": previous,
            "to": to.value,
            "reason": reason,
            "trade_plan_id": plan,
            "symbol": "BTCUSDT",
        },
        entity_id=f"hash-{plan}",
    )


def base_journal(days: float = 22) -> list[JournalEvent]:
    """A clean journal: a first and a last healthy verdict `days` apart, no orders."""
    return [healthy(T0), healthy(day(days))]


def registration(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "demo-soak-registration/1",
        "duration_days": 21,
        "symbols": ["BTCUSDT"],
        "trade_generation": {"owner_round_trips_per_week": None},
        "healthy": {"allowed_degraded_checks": list(ALLOWED_DEGRADED)},
        "account": "demo account A",
        "host": "soak host 1",
        "restart_policy": "restart: no, owner restarts after a defect",
        "pass_criteria": ["zero unexplained divergence", "zero position without a stop"],
        "restart_rule": "a defect restarts the clock at the fix time",
        "image_commit": IMAGE_COMMIT,
        "registered_at_utc": "2026-11-09T08:00:00Z",
    }
    document.update(overrides)
    return document


def write_registration(tmp_path: Path, document: dict[str, Any]) -> tuple[Path, Path]:
    text = "# Demo soak registration\n\n```json\n" + json.dumps(document, indent=2) + "\n```\n"
    reg = tmp_path / "SOAK-REGISTRATION.md"
    reg.write_bytes(text.encode("utf-8"))
    hash_file = tmp_path / "SOAK-REGISTRATION.sha256"
    digest = hashlib.sha256(reg.read_bytes()).hexdigest()
    hash_file.write_text(f"{digest}  SOAK-REGISTRATION.md\n", encoding="utf-8")
    return reg, hash_file


def write_journal(tmp_path: Path, events: list[JournalEvent], name: str = "journal.jsonl") -> Path:
    path = tmp_path / name
    path.write_bytes(b"".join(soak.event_to_jsonl(e) for e in events))
    return path


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.reg, self.hash_file = write_registration(tmp_path, registration())
        self.out = tmp_path / "report.json"

    def use_registration(self, document: dict[str, Any]) -> None:
        self.reg, self.hash_file = write_registration(self.tmp_path, document)

    def evaluate(
        self,
        events: list[JournalEvent],
        *,
        annotations: list[dict[str, Any]] | None = None,
        committed_at: datetime = COMMITTED_AT,
    ) -> tuple[int, dict[str, Any]]:
        journal = write_journal(self.tmp_path, events)
        argv = [
            "evaluate",
            "--registration",
            str(self.reg),
            "--hash-file",
            str(self.hash_file),
            "--registration-committed-at",
            committed_at.isoformat(),
            "--journal",
            str(journal),
            "--out",
            str(self.out),
        ]
        if annotations is not None:
            path = self.tmp_path / "annotations.md"
            path.write_text(
                "# Annotations\n\n```json\n" + json.dumps(annotations) + "\n```\n",
                encoding="utf-8",
            )
            argv += ["--annotations", str(path)]
        code = soak.main(argv, clock=lambda: NOW)
        report: dict[str, Any] = (
            json.loads(self.out.read_text(encoding="utf-8")) if (self.out.exists()) else {}
        )
        return code, report


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def criterion(report: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [c for c in report["criteria"] if c["name"] == name]
    assert len(matches) == 1, (
        f"criterion {name} missing from {[c['name'] for c in report['criteria']]}"
    )
    found: dict[str, Any] = matches[0]
    return found


def explained(event: JournalEvent, note: str = "owner: known and harmless") -> dict[str, Any]:
    return {"journal_event_id": event.journal_event_id, "kind": "explained", "note": note}


def defect(event: JournalEvent, fixed_at: datetime) -> dict[str, Any]:
    return {
        "journal_event_id": event.journal_event_id,
        "kind": "defect",
        "note": "owner: a real defect, fixed",
        "fixed_at_utc": fixed_at.isoformat(),
    }


# --------------------------------------------------------------------------- #
# Task 1: the registration, its hash, the order-after-registration rule, duplicates.
# --------------------------------------------------------------------------- #


def verify(reg: Path, hash_file: Path) -> int:
    return soak.main(
        ["verify-registration", "--registration", str(reg), "--hash-file", str(hash_file)],
        clock=lambda: NOW,
    )


def test_verify_registration_accepts_a_valid_registration_with_its_hash(rig: Rig) -> None:
    assert verify(rig.reg, rig.hash_file) == 0


def test_verify_registration_refuses_a_file_edited_after_its_hash_was_recorded(rig: Rig) -> None:
    rig.reg.write_bytes(rig.reg.read_bytes().replace(b"soak host 1", b"soak host 2"))

    assert verify(rig.reg, rig.hash_file) == 1


def test_verify_registration_accepts_a_bare_hex_hash_file(rig: Rig) -> None:
    digest = hashlib.sha256(rig.reg.read_bytes()).hexdigest()
    rig.hash_file.write_text(digest.upper() + "\n", encoding="utf-8")

    assert verify(rig.reg, rig.hash_file) == 0


def test_verify_registration_refuses_a_malformed_hash_file(rig: Rig) -> None:
    rig.hash_file.write_text("not-a-hash\n", encoding="utf-8")

    assert verify(rig.reg, rig.hash_file) == 1


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"duration_days": 20}, "duration_days"),
        ({"duration_days": True}, "duration_days"),
        ({"duration_days": 21.5}, "duration_days"),
        ({"image_commit": "abc"}, "image_commit"),
        ({"image_commit": "A" * 40}, "image_commit"),
        ({"schema": "demo-soak-registration/2"}, "schema"),
        ({"symbols": []}, "symbols"),
        ({"symbols": [""]}, "symbols"),
        ({"pass_criteria": []}, "pass_criteria"),
        ({"restart_rule": ""}, "restart_rule"),
        ({"host": 5}, "host"),
        ({"registered_at_utc": "2026-11-09T08:00:00"}, "registered_at_utc"),
        ({"trade_generation": {"owner_round_trips_per_week": -1}}, "owner_round_trips_per_week"),
        ({"trade_generation": {"owner_round_trips_per_week": "3"}}, "owner_round_trips_per_week"),
        ({"healthy": {"allowed_degraded_checks": "candle"}}, "allowed_degraded_checks"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_verify_registration_refuses_an_invalid_field(
    rig: Rig, capsys: pytest.CaptureFixture[str], override: dict[str, Any], fragment: str
) -> None:
    rig.use_registration(registration(**override))

    assert verify(rig.reg, rig.hash_file) == 1
    assert fragment in capsys.readouterr().err


def test_verify_registration_refuses_a_missing_field(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    document = registration()
    del document["restart_policy"]
    rig.use_registration(document)

    assert verify(rig.reg, rig.hash_file) == 1
    assert "restart_policy" in capsys.readouterr().err


@pytest.mark.parametrize("body", ["no block here\n", "```json\n{}\n```\n\n```json\n{}\n```\n"])
def test_verify_registration_needs_exactly_one_json_block(rig: Rig, body: str) -> None:
    rig.reg.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(rig.reg.read_bytes()).hexdigest()
    rig.hash_file.write_text(digest + "\n", encoding="utf-8")

    assert verify(rig.reg, rig.hash_file) == 1


def test_verify_registration_accepts_a_longer_soak_and_a_round_trip_number(rig: Rig) -> None:
    rig.use_registration(
        registration(duration_days=28, trade_generation={"owner_round_trips_per_week": 3})
    )

    assert verify(rig.reg, rig.hash_file) == 0


def test_evaluate_passes_a_clean_journal_with_one_outcome_per_plan(rig: Rig) -> None:
    events = [outcome(day(1), "plan-1"), outcome(day(2), "plan-2"), *base_journal()]

    code, report = rig.evaluate(events)

    assert code == 0
    assert report["verdict"] == "PASS"
    assert criterion(report, soak.CRIT_DUPLICATE_ENTRY)["status"] == "PASS"
    assert criterion(report, soak.CRIT_REGISTRATION_HASH)["status"] == "PASS"
    assert criterion(report, soak.CRIT_ORDER_AFTER_REGISTRATION)["status"] == "PASS"


def test_two_non_refused_outcomes_for_one_plan_fail_and_name_both_journal_ids(rig: Rig) -> None:
    first = outcome(day(1), "plan-1")
    second = outcome(day(1.5), "plan-1")

    code, report = rig.evaluate([first, second, *base_journal()])

    assert code == 1
    assert report["verdict"] == "FAIL"
    found = criterion(report, soak.CRIT_DUPLICATE_ENTRY)
    assert found["status"] == "FAIL"
    assert set(found["ids"]) == {first.journal_event_id, second.journal_event_id}
    assert found["count"] == 1


def test_a_refused_outcome_next_to_a_placed_one_is_not_a_duplicate(rig: Rig) -> None:
    refused = outcome(day(1), "plan-1", no_trade=True)
    placed = outcome(day(1.5), "plan-1")

    code, report = rig.evaluate([refused, placed, *base_journal()])

    assert code == 0
    assert criterion(report, soak.CRIT_DUPLICATE_ENTRY)["status"] == "PASS"


def test_an_order_before_the_registration_commit_fails(rig: Rig) -> None:
    early = outcome(COMMITTED_AT - timedelta(hours=1), "plan-1")

    code, report = rig.evaluate([early, *base_journal()])

    assert code == 1
    found = criterion(report, soak.CRIT_ORDER_AFTER_REGISTRATION)
    assert found["status"] == "FAIL"
    assert "order before registration" in found["note"]
    assert found["ids"] == [early.journal_event_id]


def test_an_order_at_the_exact_registration_commit_instant_fails(rig: Rig) -> None:
    same = outcome(COMMITTED_AT, "plan-1")

    code, report = rig.evaluate([same, *base_journal()])

    assert code == 1
    assert criterion(report, soak.CRIT_ORDER_AFTER_REGISTRATION)["status"] == "FAIL"


def test_a_journal_without_orders_has_no_order_to_judge_and_says_so(rig: Rig) -> None:
    code, report = rig.evaluate(base_journal())

    assert code == 0
    found = criterion(report, soak.CRIT_ORDER_AFTER_REGISTRATION)
    assert found["status"] == "PASS"
    assert "no order event" in found["note"]


def test_a_registration_that_does_not_match_its_hash_fails_the_evaluation(rig: Rig) -> None:
    rig.reg.write_bytes(rig.reg.read_bytes().replace(b"soak host 1", b"soak host 2"))

    code, report = rig.evaluate(base_journal())

    assert code == 1
    assert criterion(report, soak.CRIT_REGISTRATION_HASH)["status"] == "FAIL"


def test_the_report_is_create_only_sorted_lf_and_carries_the_input_hashes(rig: Rig) -> None:
    code, report = rig.evaluate(base_journal())
    assert code == 0
    raw = rig.out.read_bytes()

    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert raw.decode("utf-8") == json.dumps(report, indent=2, sort_keys=True) + "\n"
    manifest = report["manifest"]
    assert manifest["registration"]["sha256"] == hashlib.sha256(rig.reg.read_bytes()).hexdigest()
    assert manifest["hash_file"]["sha256"] == hashlib.sha256(rig.hash_file.read_bytes()).hexdigest()
    journal_bytes = (rig.tmp_path / "journal.jsonl").read_bytes()
    assert manifest["journal"]["sha256"] == hashlib.sha256(journal_bytes).hexdigest()
    assert report["evaluated_at_utc"] == NOW.isoformat()

    code_again, _ = rig.evaluate(base_journal())
    assert code_again == 2
    assert rig.out.read_bytes() == raw


def test_evaluate_exit_2_for_an_unusable_input(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    journal = rig.tmp_path / "journal.jsonl"
    journal.write_text("this is not json\n", encoding="utf-8")

    code = soak.main(
        [
            "evaluate",
            "--registration",
            str(rig.reg),
            "--hash-file",
            str(rig.hash_file),
            "--registration-committed-at",
            COMMITTED_AT.isoformat(),
            "--journal",
            str(journal),
            "--out",
            str(rig.out),
        ],
        clock=lambda: NOW,
    )

    assert code == 2
    assert "journal" in capsys.readouterr().err
    assert not rig.out.exists()


def test_a_journal_with_a_repeated_event_id_is_unusable(rig: Rig) -> None:
    event = healthy(T0)

    code, _ = rig.evaluate([event, event])

    assert code == 2


def test_a_naive_registration_commit_time_is_refused(rig: Rig) -> None:
    journal = write_journal(rig.tmp_path, base_journal())

    code = soak.main(
        [
            "evaluate",
            "--registration",
            str(rig.reg),
            "--hash-file",
            str(rig.hash_file),
            "--registration-committed-at",
            "2026-11-09T08:00:00",
            "--journal",
            str(journal),
            "--out",
            str(rig.out),
        ],
        clock=lambda: NOW,
    )

    assert code == 2


def test_help_names_the_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        soak.main(["--help"], clock=lambda: NOW)

    assert raised.value.code == 0
    text = capsys.readouterr().out
    for name in ("verify-registration", "evaluate"):
        assert name in text


# --------------------------------------------------------------------------- #
# Task 2: annotations, divergence, unprotected positions, duplicates, alerts, restart rule.
# --------------------------------------------------------------------------- #


def alert(at: datetime, *, reason: str = "SOMETHING") -> JournalEvent:
    return make_event(
        EVENT_OPERATIONAL_ALERT,
        at,
        payload={"event": "X", "severity": "HIGH", "subject": "s", "reason": reason},
        entity_id="alert-subject",
    )


def safe_mode_enter(at: datetime) -> JournalEvent:
    return make_event(
        soak.EVENT_SAFE_MODE_ENTER,
        at,
        payload={"reason": "FOREIGN_ORDER", "system_mode": "SAFE_MODE"},
        entity_id="SAFE_MODE",
    )


def test_an_annotation_for_an_unknown_journal_id_is_refused(rig: Rig) -> None:
    bogus = {"journal_event_id": "nope", "kind": "explained", "note": "x"}

    code, _ = rig.evaluate(base_journal(), annotations=[bogus])

    assert code == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(kind="waived"),
        lambda a: a.update(note=""),
        lambda a: a.pop("note"),
        lambda a: a.update(extra="x"),
        lambda a: a.update(fixed_at_utc=day(3).isoformat()),
        lambda a: a.update(kind="defect"),
        lambda a: a.update(kind="defect", fixed_at_utc="2026-11-12T00:00:00"),
        lambda a: a.update(kind="defect", fixed_at_utc=(T0 - timedelta(days=1)).isoformat()),
    ],
)
def test_a_malformed_annotation_is_refused(
    rig: Rig, mutate: Callable[[dict[str, Any]], object]
) -> None:
    noisy = alert(day(2))
    annotation = explained(noisy)
    mutate(annotation)

    code, _ = rig.evaluate([noisy, *base_journal()], annotations=[annotation])

    assert code == 2
    assert not rig.out.exists()


def test_a_duplicate_annotation_id_is_refused(rig: Rig) -> None:
    noisy = alert(day(2))

    code, _ = rig.evaluate(
        [noisy, *base_journal()], annotations=[explained(noisy), explained(noisy)]
    )

    assert code == 2


def test_annotations_need_exactly_one_json_list(rig: Rig) -> None:
    journal = write_journal(rig.tmp_path, base_journal())
    path = rig.tmp_path / "annotations.md"
    path.write_text("no block\n", encoding="utf-8")

    code = soak.main(
        [
            "evaluate",
            "--registration",
            str(rig.reg),
            "--hash-file",
            str(rig.hash_file),
            "--registration-committed-at",
            COMMITTED_AT.isoformat(),
            "--journal",
            str(journal),
            "--annotations",
            str(path),
            "--out",
            str(rig.out),
        ],
        clock=lambda: NOW,
    )

    assert code == 2


# ---- divergence ----


def test_a_reconcile_tick_with_a_divergence_fails_until_it_is_annotated(rig: Rig) -> None:
    diverged = tick(day(3), {"FOREIGN_ORDER": 1})
    events = [diverged, *base_journal()]

    code, report = rig.evaluate(events)
    assert code == 1
    found = criterion(report, soak.CRIT_DIVERGENCE)
    assert found["status"] == "FAIL"
    assert found["ids"] == [diverged.journal_event_id]

    rig.out.unlink()
    code, report = rig.evaluate(events, annotations=[explained(diverged)])
    assert code == 0
    assert criterion(report, soak.CRIT_DIVERGENCE)["status"] == "PASS"


def test_a_clean_reconcile_tick_needs_no_annotation(rig: Rig) -> None:
    code, report = rig.evaluate([tick(day(3)), *base_journal()])

    assert code == 0
    assert criterion(report, soak.CRIT_DIVERGENCE)["status"] == "PASS"


def test_an_unreadable_reconcile_tick_payload_fails_closed(rig: Rig) -> None:
    broken = make_event(RECONCILE_TICK, day(3), payload={"outcome": "COMPARED"})

    code, report = rig.evaluate([broken, *base_journal()])

    assert code == 1
    assert criterion(report, soak.CRIT_DIVERGENCE)["ids"] == [broken.journal_event_id]


def test_a_safe_mode_entry_fails_until_it_is_annotated(rig: Rig) -> None:
    entered = safe_mode_enter(day(4))
    events = [entered, *base_journal()]

    code, report = rig.evaluate(events)
    assert code == 1
    assert criterion(report, soak.CRIT_DIVERGENCE)["ids"] == [entered.journal_event_id]

    rig.out.unlink()
    code, _ = rig.evaluate(events, annotations=[explained(entered)])
    assert code == 0


# ---- positions without a stop ----


@pytest.mark.parametrize(
    "kind", [DIVERGENCE_KIND_POSITION_WITHOUT_STOP, DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE]
)
def test_a_position_without_a_stop_fails_even_when_annotated_explained(rig: Rig, kind: str) -> None:
    exposed = tick(day(3), {kind: 1})

    code, report = rig.evaluate([exposed, *base_journal()], annotations=[explained(exposed)])

    assert code == 1
    assert criterion(report, soak.CRIT_DIVERGENCE)["status"] == "PASS"
    found = criterion(report, soak.CRIT_POSITION_WITHOUT_STOP)
    assert found["status"] == "FAIL"
    assert found["ids"] == [exposed.journal_event_id]


def test_a_close_required_for_a_rejected_stop_fails_even_when_annotated(rig: Rig) -> None:
    closing = make_event(
        EVENT_CLOSE_REQUIRED,
        day(3),
        payload={"branch": BRANCH_B5_STOP_REJECTED, "symbol": "BTCUSDT"},
    )

    code, report = rig.evaluate([closing, *base_journal()], annotations=[explained(closing)])

    assert code == 1
    assert criterion(report, soak.CRIT_POSITION_WITHOUT_STOP)["ids"] == [closing.journal_event_id]


def test_a_close_that_kept_a_good_stop_is_not_a_position_without_a_stop(rig: Rig) -> None:
    closing = make_event(
        EVENT_CLOSE_REQUIRED,
        day(3),
        payload={
            "accepted_knowingly": "STOP_KEPT_ENTRY_CANCEL_SLOW",
            "branch": BRANCH_B1_ENTRY_NOT_TERMINAL,
        },
    )

    code, report = rig.evaluate([closing, *base_journal()])

    assert code == 0
    assert criterion(report, soak.CRIT_POSITION_WITHOUT_STOP)["status"] == "PASS"


def test_a_transition_into_close_required_for_an_unconfirmed_stop_fails(rig: Rig) -> None:
    moved = transition(
        day(3),
        "plan-1",
        to=ProtectionState.CLOSE_REQUIRED,
        reason=BRANCH_B5_STOP_REJECTED,
        previous="UNPROTECTED",
    )

    code, report = rig.evaluate([moved, *base_journal()], annotations=[explained(moved)])

    assert code == 1
    assert criterion(report, soak.CRIT_POSITION_WITHOUT_STOP)["ids"] == [moved.journal_event_id]


def test_a_lost_stop_after_protection_fails_but_a_first_fill_unprotected_step_does_not(
    rig: Rig,
) -> None:
    first_fill = transition(
        day(3),
        "plan-1",
        to=ProtectionState.UNPROTECTED,
        reason=REASON_FIRST_FILL_STREAM,
        previous="AWAITING_FILL",
    )
    lost = transition(
        day(4),
        "plan-1",
        to=ProtectionState.UNPROTECTED,
        reason=REASON_STOP_LOST_AFTER_PROTECTED,
        previous="PROTECTED",
    )

    code, report = rig.evaluate([first_fill, *base_journal()])
    assert code == 0

    rig.out.unlink()
    code, report = rig.evaluate([first_fill, lost, *base_journal()])
    assert code == 1
    assert criterion(report, soak.CRIT_POSITION_WITHOUT_STOP)["ids"] == [lost.journal_event_id]


# ---- duplicate entries ----


@pytest.mark.parametrize(
    "kind", [DIVERGENCE_KIND_DOUBLED_POSITION, DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID]
)
def test_a_doubled_position_or_duplicate_exchange_id_fails_even_when_annotated(
    rig: Rig, kind: str
) -> None:
    doubled = tick(day(3), {kind: 1})

    code, report = rig.evaluate([doubled, *base_journal()], annotations=[explained(doubled)])

    assert code == 1
    assert criterion(report, soak.CRIT_DUPLICATE_ENTRY)["ids"] == [doubled.journal_event_id]


def test_an_explained_annotation_never_excuses_a_duplicate_outcome(rig: Rig) -> None:
    first = outcome(day(1), "plan-1")
    second = outcome(day(1.5), "plan-1")

    code, report = rig.evaluate(
        [first, second, *base_journal()], annotations=[explained(first), explained(second)]
    )

    assert code == 1
    assert criterion(report, soak.CRIT_DUPLICATE_ENTRY)["status"] == "FAIL"


# ---- alerts and health ----


def test_every_operational_alert_needs_an_owner_annotation(rig: Rig) -> None:
    noisy = alert(day(2))
    events = [noisy, *base_journal()]

    code, report = rig.evaluate(events)
    assert code == 1
    assert criterion(report, soak.CRIT_ALERTS_EXPLAINED)["ids"] == [noisy.journal_event_id]

    rig.out.unlink()
    code, report = rig.evaluate(events, annotations=[explained(noisy)])
    assert code == 0
    assert criterion(report, soak.CRIT_ALERTS_EXPLAINED)["status"] == "PASS"


def test_an_unhealthy_verdict_needs_an_annotation_and_an_allowed_degraded_check_does_not(
    rig: Rig,
) -> None:
    allowed = healthy(day(1), degraded=["candle_freshness"])
    outside = healthy(day(2), degraded=["clock_drift"])
    failing = healthy(day(3), failing=["exchange_rest"])
    events = [allowed, outside, failing, *base_journal()]

    code, report = rig.evaluate(events)
    assert code == 1
    found = criterion(report, soak.CRIT_HEALTH_EXPLAINED)
    assert set(found["ids"]) == {outside.journal_event_id, failing.journal_event_id}

    rig.out.unlink()
    code, _ = rig.evaluate(events, annotations=[explained(outside), explained(failing)])
    assert code == 0


def test_a_health_verdict_without_its_lists_fails_closed(rig: Rig) -> None:
    unreadable = make_event(VERDICT_EVENT_TYPE, day(2), payload={"is_no_trade": False})

    code, report = rig.evaluate([unreadable, *base_journal()])

    assert code == 1
    assert criterion(report, soak.CRIT_HEALTH_EXPLAINED)["ids"] == [unreadable.journal_event_id]


# ---- the window and the restart rule ----


def test_the_effective_window_must_last_the_registered_days(rig: Rig) -> None:
    code, report = rig.evaluate(base_journal(days=20))
    assert code == 1
    found = criterion(report, soak.CRIT_DURATION)
    assert found["status"] == "FAIL"
    assert report["window"]["effective_days"].startswith("20")

    rig.out.unlink()
    code, report = rig.evaluate(base_journal(days=21))
    assert code == 0
    assert criterion(report, soak.CRIT_DURATION)["status"] == "PASS"


def test_a_defect_annotation_restarts_the_window_at_the_fix_time(rig: Rig) -> None:
    broken = alert(day(5))
    fixed_at = day(10)

    code, report = rig.evaluate(
        [broken, healthy(T0), healthy(day(25))], annotations=[defect(broken, fixed_at)]
    )
    assert code == 1
    assert criterion(report, soak.CRIT_DURATION)["status"] == "FAIL"
    assert report["window"]["window_start_utc"] == fixed_at.isoformat()
    assert report["window"]["effective_days"].startswith("15")
    assert criterion(report, soak.CRIT_ALERTS_EXPLAINED)["status"] == "PASS"

    rig.out.unlink()
    code, report = rig.evaluate(
        [broken, healthy(T0), healthy(day(31))], annotations=[defect(broken, fixed_at)]
    )
    assert code == 0
    assert criterion(report, soak.CRIT_DURATION)["status"] == "PASS"


def test_an_explained_annotation_does_not_restart_the_window(rig: Rig) -> None:
    noisy = alert(day(5))

    code, report = rig.evaluate([noisy, *base_journal(days=22)], annotations=[explained(noisy)])

    assert code == 0
    assert report["window"]["window_start_utc"] == T0.isoformat()


def test_the_latest_defect_fix_decides_the_window_start(rig: Rig) -> None:
    first = alert(day(2), reason="A")
    second = alert(day(6), reason="B")

    code, report = rig.evaluate(
        [first, second, *base_journal(days=40)],
        annotations=[defect(first, day(3)), defect(second, day(8))],
    )

    assert code == 0
    assert report["window"]["window_start_utc"] == day(8).isoformat()
    assert report["window"]["defect_count"] == 2


def test_a_defect_annotation_removes_the_row_it_names_from_the_stop_and_duplicate_criteria(
    rig: Rig,
) -> None:
    exposed = tick(day(3), {DIVERGENCE_KIND_POSITION_WITHOUT_STOP: 1})
    first = outcome(day(1), "plan-1")
    second = outcome(day(1.5), "plan-1")

    code, report = rig.evaluate(
        [exposed, first, second, *base_journal(days=40)],
        annotations=[defect(exposed, day(9)), defect(second, day(9))],
    )

    assert code == 0
    assert criterion(report, soak.CRIT_POSITION_WITHOUT_STOP)["status"] == "PASS"
    assert criterion(report, soak.CRIT_DUPLICATE_ENTRY)["status"] == "PASS"


def test_a_defect_does_not_hide_an_unannotated_row_of_another_cause(rig: Rig) -> None:
    broken = alert(day(5), reason="A")
    other = tick(day(4), {"FOREIGN_ORDER": 1})

    code, report = rig.evaluate(
        [broken, other, *base_journal(days=40)], annotations=[defect(broken, day(6))]
    )

    assert code == 1
    assert criterion(report, soak.CRIT_DIVERGENCE)["ids"] == [other.journal_event_id]


# ---- owner round trips ----


def round_trip(plan: str, filled: datetime, closed: datetime) -> list[JournalEvent]:
    return [
        transition(
            filled,
            plan,
            to=ProtectionState.UNPROTECTED,
            reason=REASON_FIRST_FILL_REST,
            previous="AWAITING_FILL",
        ),
        transition(
            closed,
            plan,
            to=ProtectionState.FLAT,
            reason="POSITION_CLOSED",
            previous="PROTECTED",
        ),
    ]


def test_a_null_round_trip_number_skips_the_criterion_with_a_note(rig: Rig) -> None:
    code, report = rig.evaluate(base_journal())

    assert code == 0
    found = criterion(report, soak.CRIT_ROUND_TRIPS)
    assert found["status"] == "SKIPPED"
    assert "null" in found["note"]


def test_the_registered_round_trips_per_full_week_are_required(rig: Rig) -> None:
    rig.use_registration(registration(trade_generation={"owner_round_trips_per_week": 2}))
    events = [
        *round_trip("p1", day(0.5), day(1)),
        *round_trip("p2", day(1.5), day(2)),
        *round_trip("p3", day(7.5), day(8)),
        *round_trip("p4", day(8.5), day(9)),
        *round_trip("p5", day(14.5), day(15)),
        *round_trip("p6", day(15.5), day(16)),
        *base_journal(days=22),
    ]

    code, report = rig.evaluate(events)

    assert code == 0
    assert criterion(report, soak.CRIT_ROUND_TRIPS)["status"] == "PASS"


def test_a_week_with_fewer_round_trips_than_registered_fails(rig: Rig) -> None:
    rig.use_registration(registration(trade_generation={"owner_round_trips_per_week": 2}))
    events = [
        *round_trip("p1", day(0.5), day(1)),
        *round_trip("p2", day(1.5), day(2)),
        *round_trip("p3", day(7.5), day(8)),
        *round_trip("p5", day(14.5), day(15)),
        *round_trip("p6", day(15.5), day(16)),
        *base_journal(days=22),
    ]

    code, report = rig.evaluate(events)

    assert code == 1
    found = criterion(report, soak.CRIT_ROUND_TRIPS)
    assert found["status"] == "FAIL"
    assert found["count"] == 1
    assert "week 2" in found["note"]


def test_a_fill_without_an_exit_is_not_a_completed_round_trip(rig: Rig) -> None:
    rig.use_registration(registration(trade_generation={"owner_round_trips_per_week": 1}))
    events = [
        *round_trip("p1", day(0.5), day(1)),
        *round_trip("p2", day(7.5), day(8)),
        transition(
            day(14.5),
            "p3",
            to=ProtectionState.UNPROTECTED,
            reason=REASON_FIRST_FILL_REST,
            previous="AWAITING_FILL",
        ),
        *base_journal(days=22),
    ]

    code, report = rig.evaluate(events)

    assert code == 1
    assert "week 3" in criterion(report, soak.CRIT_ROUND_TRIPS)["note"]


# ---- the event names come from the producers ----


def test_the_safe_mode_entry_event_name_matches_what_the_controller_journals() -> None:
    from src.reconcile.safe_mode import SafeModeController

    from tests.support.reconcile_doubles import RecordingJournal

    journal = RecordingJournal()
    controller = SafeModeController(adapter=object(), journal=journal)  # type: ignore[arg-type]

    controller.enter_safe_mode(reason="FOREIGN_ORDER", now_utc=T0)

    assert [e.event_type for e in journal.events] == [soak.EVENT_SAFE_MODE_ENTER]


def test_the_health_verdict_payload_keys_match_what_the_producer_writes() -> None:
    from src.live.health import _verdict_event

    verdict = SimpleNamespace(
        is_no_trade=False,
        reason_code="OK",
        mode=None,
        demo_degraded_allowed=True,
        degraded_names=("candle_freshness",),
        results=[],
    )

    event = _verdict_event(verdict, T0, {})  # type: ignore[arg-type]
    payload = json.loads(event.payload_json)

    assert event.event_type == VERDICT_EVENT_TYPE
    assert payload[soak.KEY_HEALTH_DEGRADED] == ["candle_freshness"]
    assert payload[soak.KEY_HEALTH_FAILING] == []


def test_the_script_imports_its_event_names_and_never_retypes_them() -> None:
    import ast

    path = Path(soak.__file__)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    producer_names = {
        EVENT_PLACEMENT_OUTCOME,
        EVENT_OPERATIONAL_ALERT,
        EVENT_CLOSE_REQUIRED,
        EVENT_PROTECTION_TRANSITION,
        RECONCILE_TICK,
        VERDICT_EVENT_TYPE,
    }
    docstring = ast.get_docstring(tree, clean=False)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value != docstring
    }

    assert literals.isdisjoint(producer_names)
    assert "from src." in text and "EVENT_OPERATIONAL_ALERT" in text and "RECONCILE_TICK" in text


# --------------------------------------------------------------------------- #
# Task 3: export never reveals the database URL (T-25-17); the database half is in
# tests/test_evaluate_demo_soak_pg.py.
# --------------------------------------------------------------------------- #

SENTINEL_URL = "postgresql+psycopg://soak_user:SENTINEL-pw-8841@db.invalid:5432/soak"
URL_ENV = "SOAK_EXPORT_TEST_URL"


def export_argv(out: Path, *, since: datetime = T0, until: datetime | None = None) -> list[str]:
    return [
        "export",
        "--database-url-env",
        URL_ENV,
        "--since",
        since.isoformat(),
        "--until",
        (until or day(30)).isoformat(),
        "--out",
        str(out),
    ]


def assert_no_secret(out: Path, *texts: str) -> None:
    if out.exists():
        texts = (*texts, out.read_text(encoding="utf-8"))
    for text in texts:
        assert SENTINEL_URL not in text
        assert "SENTINEL-pw-8841" not in text
        assert "soak_user" not in text


def test_export_with_a_missing_variable_exits_2_naming_only_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(URL_ENV, raising=False)
    out = tmp_path / "journal.jsonl"

    code = soak.main(export_argv(out), clock=lambda: NOW)

    assert code == 2
    assert URL_ENV in capsys.readouterr().err
    assert not out.exists()


def test_export_never_prints_the_url_when_the_connection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(URL_ENV, SENTINEL_URL)

    def refuse(url: str, **_: object) -> object:
        raise RuntimeError(f"could not connect to {url}")

    monkeypatch.setattr(soak, "make_sync_engine", refuse)
    out = tmp_path / "journal.jsonl"

    code = soak.main(export_argv(out), clock=lambda: NOW)

    captured = capsys.readouterr()
    assert code == 2
    assert "RuntimeError" in captured.err
    assert not out.exists()
    assert_no_secret(out, captured.out, captured.err)


def test_export_writes_the_rows_create_only_and_never_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(URL_ENV, SENTINEL_URL)
    events = [healthy(T0), outcome(day(1), "plan-1"), healthy(day(22))]
    seen: dict[str, Any] = {}

    def fake_fetch(url: str, since: datetime, until: datetime) -> list[JournalEvent]:
        seen.update(url=url, since=since, until=until)
        return events

    monkeypatch.setattr(soak, "fetch_events", fake_fetch)
    out = tmp_path / "journal.jsonl"

    code = soak.main(export_argv(out), clock=lambda: NOW)

    assert code == 0
    assert seen == {"url": SENTINEL_URL, "since": T0, "until": day(30)}
    raw = out.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert soak.parse_journal(raw) == sorted(
        events, key=lambda e: (e.occurred_at_utc, e.journal_event_id)
    )
    captured = capsys.readouterr()
    assert_no_secret(out, captured.out, captured.err)

    assert soak.main(export_argv(out), clock=lambda: NOW) == 2
    assert out.read_bytes() == raw


def test_export_refuses_an_empty_or_reversed_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(URL_ENV, SENTINEL_URL)
    monkeypatch.setattr(soak, "fetch_events", lambda *_: [])
    out = tmp_path / "journal.jsonl"

    assert soak.main(export_argv(out, since=day(5), until=day(5)), clock=lambda: NOW) == 2
    assert soak.main(export_argv(out, since=day(5), until=day(2)), clock=lambda: NOW) == 2
    assert soak.main(export_argv(out), clock=lambda: NOW) == 2
    assert not out.exists()


def test_help_names_export(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        soak.main(["--help"], clock=lambda: NOW)

    assert raised.value.code == 0
    assert "export" in capsys.readouterr().out
