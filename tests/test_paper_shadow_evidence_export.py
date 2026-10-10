"""SHADOW decision history through the analytics path (Phase 16, plan 16-36, D-18, REV-03).

The exporter turns SHADOW journal, approval and confirm rows into `analytics-evidence/2` paper
records that the existing analytics CLI reports as system, user-executed-sim and opportunity
outcomes. It defines no metric: the report only gets its inputs extended (D-18).
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.adapters.analytics_files import EVIDENCE_SCHEMA, load_evidence_file
from src.analytics.cli import main
from src.analytics.killgate_guard import EvidenceClass
from src.analytics.lifecycle import LifecyclePath, normalize_paper_lifecycle
from src.paper.attribution import AttributionKind, ShadowOutcome
from src.paper.evidence_export import (
    EVIDENCE_FILE_SCHEMA,
    ShadowRow,
    evidence_file_bytes,
    export_shadow_evidence,
)

REPO = Path(__file__).resolve().parents[1]
PHASE7 = REPO / "tests" / "fixtures" / "phase7" / "attribution_split" / "input.json"
EVIDENCE_FIXTURE = REPO / "tests" / "fixtures" / "phase10" / "loaders" / "evidence_sample.json"
AS_OF = "2027-04-01T00:00:00+00:00"
NOT_CONCLUDED_LINE = "Kill gate: NOT CONCLUDED (blocked by WR-01, WR-06, WR-12, WR-13; D061 F)"


@pytest.fixture(autouse=True)
def _no_ambient_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _cases() -> tuple[str, dict[str, dict[str, Any]]]:
    doc = json.loads(PHASE7.read_text(encoding="utf-8"))
    return doc["epoch_id"], {case["kind"]: copy.deepcopy(case) for case in doc["cases"]}


def _detected(case: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(case["signal"]["detected_at_utc"]).astimezone(UTC)


def _approval(case: dict[str, Any], action: str) -> dict[str, Any]:
    """A real human approval row: requested 3 s after the signal, acted 47 s later."""
    requested = _detected(case) + timedelta(seconds=3)
    row = dict(case["approval"] or {})
    row.update(
        {
            "action": action,
            "actor_id": "tg-user-1",
            "requested_at_utc": requested.isoformat(),
            "acted_at_utc": (requested + timedelta(seconds=47)).isoformat(),
        }
    )
    return row


def _confirm(case: dict[str, Any]) -> dict[str, str]:
    acted = _detected(case) + timedelta(seconds=50)
    issued = acted + timedelta(seconds=1)
    return {
        "confirm_requested_at_utc": issued.isoformat(),
        "confirmed_at_utc": (issued + timedelta(seconds=12)).isoformat(),
    }


def _row(
    epoch_id: str, case: dict[str, Any], *, test_only: bool = False, **kwargs: Any
) -> ShadowRow:
    return ShadowRow(
        epoch_id=epoch_id,
        signal=case["signal"],
        trade_plan=case["trade_plan"],
        test_only=test_only,
        **kwargs,
    )


def _shadow_rows(*, test_only: bool = False) -> list[ShadowRow]:
    """APPROVE then CONFIRM, a SKIP, an expired press and an untouched plan."""
    epoch_id, cases = _cases()
    filled = cases["filled_simulation"]
    skipped = cases["skipped"]
    expired = cases["expired"]
    untouched = copy.deepcopy(cases["skipped"])
    untouched["signal"]["signal_id"] = "sig_untouched_" + "0" * 40
    untouched["trade_plan"]["plan_hash"] = "plan_hash_untouched_" + "0" * 40
    return [
        _row(
            epoch_id,
            filled,
            test_only=test_only,
            approval=_approval(filled, "APPROVE"),
            order=filled["order"],
            fill=filled["fill"],
            confirm=_confirm(filled),
            shadow_outcome=ShadowOutcome(
                approval_action="APPROVE", confirm_event="SHADOW_CONFIRMED"
            ),
        ),
        _row(
            epoch_id,
            skipped,
            test_only=test_only,
            approval=_approval(skipped, "SKIP_USER"),
            shadow_outcome=ShadowOutcome(approval_action="SKIP_USER"),
        ),
        _row(
            epoch_id,
            expired,
            test_only=test_only,
            approval=_approval(expired, "APPROVE"),
            shadow_outcome=ShadowOutcome(approval_rejection_reason="APPROVAL_EXPIRED"),
        ),
        _row(epoch_id, untouched, test_only=test_only, shadow_outcome=ShadowOutcome()),
    ]


def _backtest_part() -> tuple[list[dict[str, Any]], list[str]]:
    document = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    return document["backtest"], document["research_universe"]


def _export(rows: list[ShadowRow]) -> dict[str, Any]:
    backtest, universe = _backtest_part()
    return export_shadow_evidence(rows, research_universe=universe, backtest_entries=backtest)


def _write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "evidence.json"
    path.write_bytes(evidence_file_bytes(document))
    return path


def _decisions_file(tmp_path: Path) -> Path:
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            {
                "schema": "kill-gate-decisions/1",
                "families": [],
                "resets": [],
                "recorded_terminal": None,
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_cli(
    tmp_path: Path, evidence: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, list[str], dict[str, Any], str]:
    capsys.readouterr()
    code = main(
        [
            "--as-of",
            AS_OF,
            "--evidence",
            str(evidence),
            "--decisions",
            str(_decisions_file(tmp_path)),
            "--raw-root",
            str(tmp_path / "raw"),
            "--reports-root",
            str(tmp_path / "reports"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    lines = captured.out.splitlines()
    report_path = Path(lines[0].removeprefix("Report: "))
    sidecar_path = Path(lines[1].removeprefix("Sidecar: "))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    return code, lines, sidecar, report_path.read_text(encoding="utf-8")


def _paper_block(sidecar: dict[str, Any]) -> dict[str, Any]:
    return next(b for b in sidecar["report"]["evidence"] if b["kind"] == "PAPER")


# --------------------------------------------------------------------------- #
# Task 1 - tracer: SHADOW rows export to an evidence file and come out of the CLI.
# --------------------------------------------------------------------------- #


def test_the_schema_literal_is_the_loader_schema() -> None:
    assert EVIDENCE_FILE_SCHEMA == EVIDENCE_SCHEMA == "analytics-evidence/2"


def test_shadow_rows_export_as_real_evidence_and_report_three_way_outcomes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _export(_shadow_rows())
    assert "evidence_class" not in document
    path = _write(tmp_path, document)

    evidence = load_evidence_file(path)
    assert evidence.evidence_class is EvidenceClass.REAL
    kinds = Counter(record.attribution for record in evidence.paper)
    assert kinds[AttributionKind.USER_EXECUTED_SIM] == 1
    assert kinds[AttributionKind.OPPORTUNITY] == 2
    assert kinds[AttributionKind.SYSTEM] == 4  # the engine emitted all four signals
    paths = Counter(r.path for r in normalize_paper_lifecycle(evidence.paper))
    assert paths[LifecyclePath.USER_EXECUTED] == 1
    assert paths[LifecyclePath.OPPORTUNITY] == 2
    assert paths[LifecyclePath.SYSTEM_ONLY] == 1

    _, _, sidecar, _ = _run_cli(tmp_path, path, capsys)
    delay = _paper_block(sidecar)["approval_delay"]
    assert delay["system"]["n_signals"] == 4
    assert delay["user_execution"]["n_signals"] == 1
    assert delay["opportunity"]["n_signals"] == 2


def test_the_kill_gate_stays_not_concluded_on_the_real_shadow_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _export(_shadow_rows()))
    _, lines, sidecar, markdown = _run_cli(tmp_path, path, capsys)
    assert lines[3] == NOT_CONCLUDED_LINE
    assert sidecar["kill_gate_withheld"]["blocked_by"] == ["WR-01", "WR-06", "WR-12", "WR-13"]
    assert "# Journal Depth + Kill-Gate Report" in markdown
    assert "## 5. Approval-Delay Impact" in markdown


def test_exporting_the_same_rows_twice_is_byte_identical_and_order_independent() -> None:
    rows = _shadow_rows()
    first = evidence_file_bytes(_export(rows))
    second = evidence_file_bytes(_export(rows))
    assert first == second
    assert evidence_file_bytes(_export(list(reversed(rows)))) == first
    assert first.endswith(b"\n")
    assert b"\r" not in first


def test_a_duplicate_signal_is_refused() -> None:
    rows = _shadow_rows()
    with pytest.raises(ValueError, match="duplicate signal"):
        _export([rows[0], rows[0]])


def test_measured_timestamps_and_the_test_only_flag_reach_the_file() -> None:
    document = _export(_shadow_rows(test_only=True))
    sim = next(r for r in document["paper"] if r["attribution"] == "user-executed-sim")
    assert sim["mode"] == "SHADOW"
    assert sim["approval_requested_at_utc"] is not None
    assert sim["confirmed_at_utc"] is not None
    assert all(r["test_only"] is True for r in document["paper"])
    plain = _export(_shadow_rows())
    assert all("test_only" not in r for r in plain["paper"])
