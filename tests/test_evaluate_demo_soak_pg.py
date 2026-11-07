"""The soak journal export and evaluation on a disposable PostgreSQL database (plan 25-07).

Rows recorded through `PgJournalStore` on a generated `t17_<hex>_test` clone are exported by
`scripts/evaluate_demo_soak.py export` (the URL comes from a named environment variable and is
never printed) and the file is judged by `evaluate`. The test database URL stays in the process
environment (`TEST_DATABASE_URL`, skipped when unset); nothing here touches Binance or Telegram.

Evidence label: executed tests on a disposable database, SYNTHETIC journal rows. Times are
TEST_ONLY.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from scripts import evaluate_demo_soak as soak
from sqlalchemy.engine import make_url
from src.domain.journal import JournalEvent
from src.persistence.engine import make_sync_engine
from src.persistence.journal import PgJournalStore
from src.persistence.uow import OperationalDatabase

from tests.support.pg_rows import hexid, insert_and_commit, make_plan, make_signal
from tests.test_evaluate_demo_soak import (
    COMMITTED_AT,
    NOW,
    T0,
    day,
    healthy,
    make_event,
    outcome,
    registration,
    write_registration,
)

URL_ENV = "SOAK_EXPORT_PG_TEST_URL"
PLAN_1 = hexid(0x1001)
PLAN_2 = hexid(0x1002)


def seed_plans(url: str) -> None:
    """The parent rows the journal foreign keys need: one signal and two trade plans."""
    engine = make_sync_engine(url)
    try:
        insert_and_commit(
            engine,
            make_signal(1),
            make_plan(1, 1, plan_hash="1" * 64),
            make_plan(2, 1, plan_hash="2" * 64),
        )
    finally:
        engine.dispose()


def record(url: str, events: list[JournalEvent]) -> None:
    engine = make_sync_engine(url)
    try:
        store = PgJournalStore(OperationalDatabase(engine))
        for event in events:
            store.record(event)
    finally:
        engine.dispose()


def run_export(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    out: Path,
    *,
    since: datetime,
    until: datetime,
) -> int:
    monkeypatch.setenv(URL_ENV, url)
    return soak.main(
        [
            "export",
            "--database-url-env",
            URL_ENV,
            "--since",
            since.isoformat(),
            "--until",
            until.isoformat(),
            "--out",
            str(out),
        ],
        clock=lambda: NOW,
    )


def evaluate_file(tmp_path: Path, journal: Path) -> tuple[int, dict[str, object]]:
    reg, hash_file = write_registration(tmp_path, registration())
    out = tmp_path / "report.json"
    code = soak.main(
        [
            "evaluate",
            "--registration",
            str(reg),
            "--hash-file",
            str(hash_file),
            "--registration-committed-at",
            COMMITTED_AT.isoformat(),
            "--journal",
            str(journal),
            "--out",
            str(out),
        ],
        clock=lambda: NOW,
    )
    report: dict[str, object] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    return code, report


def test_export_takes_the_half_open_window_in_occurred_then_id_order(
    pg_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    same_instant_a = make_event("TEST_A", day(2), entity_id="a")
    same_instant_b = make_event("TEST_B", day(2), entity_id="b")
    before = make_event("TEST_BEFORE", T0 - timedelta(seconds=1))
    first = make_event("TEST_FIRST", T0)
    at_until = make_event("TEST_AT_UNTIL", day(30))
    record(pg_db, [at_until, same_instant_b, before, same_instant_a, first])
    out = tmp_path / "journal.jsonl"

    code = run_export(monkeypatch, pg_db, out, since=T0, until=day(30))

    assert code == 0
    exported = soak.parse_journal(out.read_bytes())
    assert [e.event_type for e in exported[:1]] == ["TEST_FIRST"]
    assert {e.journal_event_id for e in exported} == {
        first.journal_event_id,
        same_instant_a.journal_event_id,
        same_instant_b.journal_event_id,
    }
    tied = sorted([same_instant_a.journal_event_id, same_instant_b.journal_event_id])
    assert [e.journal_event_id for e in exported[1:]] == tied
    lines = out.read_bytes().splitlines()
    ids_in_file = [json.loads(line)["journal_event_id"] for line in lines]
    assert ids_in_file == [e.journal_event_id for e in exported]
    assert b"\r" not in out.read_bytes()


def test_a_journal_recorded_in_postgresql_round_trips_through_export_and_evaluate(
    pg_db: str, pg_server_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_plans(pg_db)
    recorded = [
        healthy(T0),
        outcome(day(1), PLAN_1),
        outcome(day(2), PLAN_2),
        healthy(day(22)),
    ]
    record(pg_db, recorded)
    out = tmp_path / "journal.jsonl"

    code = run_export(monkeypatch, pg_db, out, since=T0, until=day(30))
    assert code == 0
    exported = soak.parse_journal(out.read_bytes())
    assert [e.journal_event_id for e in exported] == [
        e.journal_event_id for e in sorted(recorded, key=lambda e: e.occurred_at_utc)
    ]
    assert [e.payload_json for e in exported] == [
        e.payload_json for e in sorted(recorded, key=lambda e: e.occurred_at_utc)
    ]

    verdict_code, report = evaluate_file(tmp_path, out)

    assert verdict_code == 0
    assert report["verdict"] == "PASS"


def test_a_duplicate_entry_recorded_in_postgresql_fails_the_evaluation(
    pg_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = outcome(day(1), PLAN_1)
    second = outcome(day(1.5), PLAN_1)
    seed_plans(pg_db)
    record(pg_db, [healthy(T0), first, second, healthy(day(22))])
    out = tmp_path / "journal.jsonl"
    assert run_export(monkeypatch, pg_db, out, since=T0, until=day(30)) == 0

    verdict_code, report = evaluate_file(tmp_path, out)

    assert verdict_code == 1
    criteria = {c["name"]: c for c in report["criteria"]}  # type: ignore[attr-defined]
    assert set(criteria[soak.CRIT_DUPLICATE_ENTRY]["ids"]) == {
        first.journal_event_id,
        second.journal_event_id,
    }


def test_export_from_postgresql_never_prints_the_url_or_its_password(
    pg_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record(pg_db, [healthy(T0), healthy(day(1))])
    out = tmp_path / "journal.jsonl"

    code = run_export(monkeypatch, pg_db, out, since=T0, until=day(30))

    captured = capsys.readouterr()
    assert code == 0
    password = make_url(pg_db).password
    for text in (captured.out, captured.err, out.read_text(encoding="utf-8")):
        assert pg_db not in text
        if password:
            assert password not in text
