"""The test-only rehearsal of the SHADOW chain (Phase 16, plan 16-39, REV-03, D061 item D, D-19).

One clearly labelled test signal runs once through the SHADOW chain in a rehearsal window that is
separate from the soak: alert, APPROVE, confirmation card, CONFIRM, journal and state transitions
and a simulated position opened by the same fill driver. Every trace of it is marked test-only.

Everything here runs on fakes (the in-memory stores and the fake bot of `tests/shadow_fakes.py`
and the scripted public minutes of the rehearsal script's dry run). No network, no real
Telegram, no wall clock.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from scripts import shadow_rehearsal
from src.paper.evidence_export import evidence_file_bytes, export_shadow_evidence
from src.paper.shadow import SHADOW_LABEL
from src.paper.shadow_confirm import EVENT_SHADOW_CONFIRMED
from src.paper.shadow_ledger import EVENT_SHADOW_POSITION_OPENED

from tests.shadow_fakes import FakeBot
from tests.test_paper_shadow_evidence_export import (
    EXCLUDED_LINE,
    _backtest_part,
    _paper_block,
    _run_cli,
)
from tests.test_paper_shadow_runtime import RuntimeStores

EVIDENCE_KEYS = {
    "test_id",
    "label_seen",
    "approval_requested_at_utc",
    "approval_acted_at_utc",
    "confirm_requested_at_utc",
    "confirmed_at_utc",
    "measured_delay_seconds",
    "confirmed_within_ttl",
    "position_opened",
    "records_written",
    "records_test_only",
    "proof_class",
}


@pytest.fixture(autouse=True)
def _no_ambient_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _evidence(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _payload(event: Any) -> dict[str, Any]:
    loaded = json.loads(event.payload_json)
    assert isinstance(loaded, dict)
    return loaded


# --------------------------------------------------------------------------- #
# Task 1, test 1: the whole chain once, every trace test-only.
# --------------------------------------------------------------------------- #


def test_a_dry_run_takes_the_labelled_test_signal_through_the_whole_shadow_chain(
    tmp_path: Path,
) -> None:
    stores = RuntimeStores()
    bot = FakeBot()
    out = tmp_path / "rehearsal.json"

    code = shadow_rehearsal.main(
        ["--dry-run", "--out", str(out)], environ={}, stores=stores, bot=bot
    )

    assert code == 0
    # One alert with the SHADOW label and the TEST SIGNAL label; then the card edit and replies.
    assert bot.sent, "the alert should have been sent"
    alert = bot.sent[0].text
    assert SHADOW_LABEL in alert and "Mode: SHADOW" in alert
    assert "TEST SIGNAL" in alert
    assert len(bot.edited) == 1, "APPROVE turned the alert into the confirmation card"
    assert "Confirm this SHADOW plan? No real order will be placed." in bot.edited[0].text

    # APR then CNF went through the real callback pipeline: both journaled, one position opened.
    assert len(stores.journal_of_type(EVENT_SHADOW_CONFIRMED)) == 1
    assert len(stores.journal_of_type(EVENT_SHADOW_POSITION_OPENED)) == 1

    # Every row the rehearsal wrote carries test_only (ids with the TEST- prefix, journal
    # payloads with the flag).
    assert stores.signals and all(s.startswith("TEST-") for s in stores.signals)
    assert stores.plans and all(p.signal_id.startswith("TEST-") for p in stores.plans.values())
    assert stores.approvals and all(
        a.signal_id.startswith("TEST-") for a in stores.approvals.values()
    )
    assert stores.journal, "the chain should have journaled something"
    for event in stores.journal:
        assert _payload(event).get("test_only") is True, event.event_type


# --------------------------------------------------------------------------- #
# Task 1, test 2: the evidence file.
# --------------------------------------------------------------------------- #


def test_the_dry_run_evidence_has_exactly_the_agreed_keys_and_proof_class_fake(
    tmp_path: Path,
) -> None:
    out = tmp_path / "rehearsal.json"

    code = shadow_rehearsal.main(["--dry-run", "--out", str(out)], environ={})

    assert code == 0
    evidence = _evidence(out)
    assert set(evidence) == EVIDENCE_KEYS
    assert evidence["test_id"].startswith("TEST-")
    assert evidence["label_seen"] is True
    assert evidence["proof_class"] == "FAKE"
    assert evidence["position_opened"] is True
    assert evidence["confirmed_within_ttl"] is True
    assert evidence["measured_delay_seconds"] > 0
    for key in (
        "approval_requested_at_utc",
        "approval_acted_at_utc",
        "confirm_requested_at_utc",
        "confirmed_at_utc",
    ):
        assert datetime.fromisoformat(evidence[key]).utcoffset() is not None, key
    assert evidence["records_written"] > 0
    assert evidence["records_test_only"] == evidence["records_written"]


# --------------------------------------------------------------------------- #
# Task 1, test 3: the analytics path excludes and counts the rehearsal rows.
# --------------------------------------------------------------------------- #


async def test_exporting_the_rehearsal_rows_counts_no_signal_and_reports_the_exclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = await shadow_rehearsal.run_dry_rehearsal(tmp_path / "rehearsal.json")
    assert result.shadow_row is not None and result.shadow_row.test_only is True

    backtest, universe = _backtest_part()
    document = export_shadow_evidence(
        [result.shadow_row], research_universe=universe, backtest_entries=backtest
    )
    assert document["paper"] and all(r["test_only"] is True for r in document["paper"])
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(evidence_file_bytes(document))

    _, _, sidecar, markdown = _run_cli(tmp_path, evidence, capsys)

    paper = _paper_block(sidecar)
    assert paper["has_data"] is False
    assert paper["approval_delay"]["system"]["n_signals"] == 0
    assert EXCLUDED_LINE.format(n=len(document["paper"])) in markdown
