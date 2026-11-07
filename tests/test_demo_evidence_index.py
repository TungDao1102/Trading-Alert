"""The per-session evidence index of the Demo scenario campaign (plan 25-08, task 2).

TEST_ONLY: the inputs are evidence files written by `ScenarioRecorder` in `tmp_path`; nothing here
touches Binance. The index lists, per evidence file, the scenario, outcome, labels with step counts
and the order ids, and is scrubbed and create-only like the evidence itself (T-25-18).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios.evidence_index import write_session_index
from tests.support.demo_scenarios.harness import (
    DEMO_FAULT_INJECTED,
    DEMO_OBSERVED,
    SYNTHETIC,
    ScenarioRecorder,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
SECRETS = {
    "BINANCE_DEMO_API_KEY": "FAKE-API-KEY-SENTINEL-0001",
    "BINANCE_DEMO_API_SECRET": "FAKE-API-SECRET-SENTINEL-0002",
}


def _evidence(
    directory: Path,
    scenario_id: str,
    *,
    mode: dr.RunMode,
    labels: tuple[tuple[str, str], ...],
    started: datetime = NOW,
    order_ids: tuple[str, ...] = ("111",),
    client_ids: tuple[str, ...] = ("c-entry",),
    algo_ids: tuple[str, ...] = ("a-sl",),
    outcome: str = dr.OUTCOME_COMPLETE,
) -> Path:
    default = SYNTHETIC if mode is dr.RunMode.DRY_RUN else DEMO_OBSERVED
    recorder = ScenarioRecorder(
        scenario_id, mode=mode, clock=lambda: started, default_label=default
    )
    for index, (status, label) in enumerate(labels):
        if label == default:
            recorder.add_step(f"step{index}", status, "detail")
        else:
            recorder.add_labeled_step(f"step{index}", status, "detail", label=label)
    recorder.record_ids(
        "confirm_entry",
        order_ids=order_ids,
        client_order_ids=client_ids,
        algo_client_ids=algo_ids,
    )
    recorder.outcome = outcome
    return recorder.write(directory)


def _index(
    tmp_path: Path, files: list[Path], *, environ: dict[str, str] | None = None
) -> tuple[Path, dict[str, Any]]:
    path = write_session_index(
        tmp_path / "evidence",
        files,
        session_id="owner-session-1",
        clock=lambda: NOW + timedelta(hours=1),
        environ=environ or {},
    )
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_one_row_per_file_with_scenario_outcome_labels_and_order_ids(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    s01 = _evidence(
        evidence,
        "S01",
        mode=dr.RunMode.EXECUTE,
        labels=(("PASSED", DEMO_OBSERVED), ("PASSED", DEMO_OBSERVED)),
    )
    s04 = _evidence(
        evidence,
        "S04",
        mode=dr.RunMode.EXECUTE,
        labels=(("PASSED", DEMO_OBSERVED), ("PASSED", DEMO_FAULT_INJECTED)),
        outcome=dr.OUTCOME_COMPLETE_WITH_GAPS,
        order_ids=("222", "333"),
    )
    path, document = _index(tmp_path, [s04, s01])
    assert path.name == "25-DEMO-SESSION-INDEX-20261107T130000Z.json"
    assert document["schema"] == "demo-session-index/schema-1"
    assert document["session_id"] == "owner-session-1"
    first, second = document["rows"]
    assert first["scenario_id"] == "S01" and second["scenario_id"] == "S04"  # sorted by id
    assert first["file"] == s01.name and first["outcome"] == dr.OUTCOME_COMPLETE
    assert first["labels"] == {DEMO_OBSERVED: 2}
    assert second["labels"] == {DEMO_FAULT_INJECTED: 1, DEMO_OBSERVED: 1}
    assert second["outcome"] == dr.OUTCOME_COMPLETE_WITH_GAPS
    assert second["demo_order_ids"] == ["222", "333"]
    assert second["client_order_ids"] == ["c-entry"]
    assert second["algo_client_ids"] == ["a-sl"]


def test_a_sibling_markdown_table_has_one_row_per_file(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    s01 = _evidence(evidence, "S01", mode=dr.RunMode.DRY_RUN, labels=(("PASSED", SYNTHETIC),))
    path, _ = _index(tmp_path, [s01])
    table = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "\r" not in table
    rows = [line for line in table.splitlines() if line.startswith("| S01")]
    assert len(rows) == 1
    assert s01.name in rows[0] and "SYNTHETIC: 1" in rows[0] and "c-entry" in rows[0]


def test_a_file_that_is_not_scenario_evidence_is_listed_as_rejected(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    good = _evidence(evidence, "S01", mode=dr.RunMode.DRY_RUN, labels=(("PASSED", SYNTHETIC),))
    other = evidence / "09-DEMO-REHEARSAL-EVIDENCE-smoke-20261101T130050Z.json"
    other.write_text(json.dumps({"schema": "demo-rehearsal-evidence/schema-1"}), encoding="utf-8")
    broken = evidence / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    path, document = _index(tmp_path, [good, other, broken])
    rejected = [row for row in document["rows"] if row["status"] == "REJECTED"]
    assert sorted(row["file"] for row in rejected) == sorted([other.name, broken.name])
    assert all(row["reason"] for row in rejected)
    assert len(document["rows"]) == 3
    assert other.name in path.with_suffix(".md").read_text(encoding="utf-8")


def test_a_missing_file_is_rejected_not_dropped(tmp_path: Path) -> None:
    (tmp_path / "evidence").mkdir()
    _, document = _index(tmp_path, [tmp_path / "evidence" / "gone.json"])
    (row,) = document["rows"]
    assert row["status"] == "REJECTED" and row["file"] == "gone.json"


def test_an_existing_index_is_never_overwritten(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    s01 = _evidence(evidence, "S01", mode=dr.RunMode.DRY_RUN, labels=(("PASSED", SYNTHETIC),))
    first, _ = _index(tmp_path, [s01])
    before = first.read_bytes()
    second, _ = _index(tmp_path, [s01])
    third, _ = _index(tmp_path, [s01])
    assert len({first, second, third}) == 3
    assert second.name.endswith("-2.json") and third.name.endswith("-3.json")
    assert second.with_suffix(".md").exists() and third.with_suffix(".md").exists()
    assert first.read_bytes() == before


def test_a_secret_in_an_evidence_file_is_scrubbed_in_the_index(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    secret = SECRETS["BINANCE_DEMO_API_KEY"]
    hand_made = evidence / "25-DEMO-SCENARIO-EVIDENCE-S01-20261107T120000Z.json"
    hand_made.write_text(
        json.dumps(
            {
                "schema": "demo-scenario-evidence/schema-1",
                "scenario_id": "S01",
                "outcome": dr.OUTCOME_COMPLETE,
                "steps": [{"name": "a", "status": "PASSED", "detail": "d", "label": SYNTHETIC}],
                "details": {
                    "order_ids": [
                        {
                            "step": "x",
                            "demo_order_ids": [],
                            "client_order_ids": [f"id-{secret}"],
                            "algo_client_ids": [],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    path, _ = _index(tmp_path, [hand_made], environ=SECRETS)
    for target in (path, path.with_suffix(".md")):
        assert secret not in target.read_text(encoding="utf-8")


def test_the_json_is_lf_only_with_sorted_keys(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    s01 = _evidence(evidence, "S01", mode=dr.RunMode.DRY_RUN, labels=(("PASSED", SYNTHETIC),))
    path, document = _index(tmp_path, [s01])
    raw = path.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert list(document) == sorted(document)
    assert not list(path.parent.glob(".*.tmp"))


def test_a_file_that_fails_the_post_write_scan_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan is the last line of defence: a scrub that leaves a secret must not leave a file."""
    from src.ops import redaction

    evidence = tmp_path / "evidence"
    s01 = _evidence(evidence, "S01", mode=dr.RunMode.DRY_RUN, labels=(("PASSED", SYNTHETIC),))

    def unstable(self: Any, text: str) -> str:
        return text + "x"  # never a fixed point: the post-write scan always finds a change

    monkeypatch.setattr(redaction.Redactor, "scrub", unstable)
    with pytest.raises(RuntimeError, match="post-write"):
        _index(tmp_path, [s01])
    assert not list(evidence.glob("25-DEMO-SESSION-INDEX-*"))
