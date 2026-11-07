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
