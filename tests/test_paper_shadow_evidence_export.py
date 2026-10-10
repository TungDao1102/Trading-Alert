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
    epoch_id: str,
    case: dict[str, Any],
    *,
    test_only: bool = False,
    tag: str = "",
    **kwargs: Any,
) -> ShadowRow:
    signal = dict(case["signal"])
    trade_plan = dict(case["trade_plan"])
    signal["signal_id"] += tag
    trade_plan["plan_hash"] += tag
    return ShadowRow(
        epoch_id=epoch_id, signal=signal, trade_plan=trade_plan, test_only=test_only, **kwargs
    )


def _shadow_rows(*, test_only: bool = False, tag: str = "") -> list[ShadowRow]:
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
            tag=tag,
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
            tag=tag,
            approval=_approval(skipped, "SKIP_USER"),
            shadow_outcome=ShadowOutcome(approval_action="SKIP_USER"),
        ),
        _row(
            epoch_id,
            expired,
            test_only=test_only,
            tag=tag,
            approval=_approval(expired, "APPROVE"),
            shadow_outcome=ShadowOutcome(approval_rejection_reason="APPROVAL_EXPIRED"),
        ),
        _row(epoch_id, untouched, test_only=test_only, tag=tag, shadow_outcome=ShadowOutcome()),
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


# --------------------------------------------------------------------------- #
# Task 2: measured labels and the test_only exclusion reach the report (REV-03).
# --------------------------------------------------------------------------- #

EXCLUDED_LINE = "test_only records excluded: {n} (D063 item 3)"
SYNTHETIC_LABEL = "SYNTHETIC LAG"


def _report_of(
    tmp_path: Path, name: str, rows: list[ShadowRow], capsys: pytest.CaptureFixture[str]
) -> tuple[dict[str, Any], str]:
    folder = tmp_path / name
    folder.mkdir()
    _, _, sidecar, markdown = _run_cli(folder, _write(folder, _export(rows)), capsys)
    return sidecar, markdown


def test_test_only_rows_are_excluded_from_every_paper_count_and_the_report_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    real = _shadow_rows()
    rehearsal = _shadow_rows(test_only=True, tag="-T")
    n_rehearsal_records = sum(
        len(r["paper"]) for r in [_export(rehearsal)]
    )  # system + user/opportunity rows
    assert n_rehearsal_records == 7

    base_sidecar, base_md = _report_of(tmp_path, "base", real, capsys)
    mixed_sidecar, mixed_md = _report_of(tmp_path, "mixed", [*real, *rehearsal], capsys)

    base_paper = _paper_block(base_sidecar)
    mixed_paper = _paper_block(mixed_sidecar)
    for section in ("approval_delay", "execution_quality", "no_trade", "core", "slices"):
        assert mixed_paper[section] == base_paper[section], section
    assert mixed_paper["has_data"] is True
    assert mixed_sidecar["report"]["provenance"] == base_sidecar["report"]["provenance"]
    assert EXCLUDED_LINE.format(n=7) in mixed_md
    assert "test_only records excluded" not in base_md


def test_only_test_only_rows_leave_the_paper_block_empty_but_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sidecar, markdown = _report_of(tmp_path, "only", _shadow_rows(test_only=True), capsys)
    paper = _paper_block(sidecar)
    assert paper["has_data"] is False
    assert paper["approval_delay"]["system"]["n_signals"] == 0
    assert EXCLUDED_LINE.format(n=7) in markdown


def test_measured_shadow_delays_are_not_labelled_synthetic_lag_in_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sidecar, markdown = _report_of(tmp_path, "measured", _shadow_rows(), capsys)
    paper = _paper_block(sidecar)
    assert paper["approval_delay"]["synthetic_lag_label"] is None
    assert paper["approval_delay"]["synthetic_lag_seconds"] is None
    assert paper["execution_quality"]["synthetic_lag_seconds"] is None
    assert SYNTHETIC_LABEL not in markdown


def test_a_section_without_a_human_action_keeps_the_synthetic_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The filled simulation of the Phase 7 fixture: SIMULATE approval, no human action.
    epoch_id, cases = _cases()
    case = cases["filled_simulation"]
    row = ShadowRow(
        epoch_id=epoch_id,
        signal=case["signal"],
        trade_plan=case["trade_plan"],
        approval=case["approval"],
        order=case["order"],
        fill=case["fill"],
        shadow_outcome=ShadowOutcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRMED"),
    )
    with pytest.raises(ValueError):
        _export([row])  # a SIMULATE leg cannot be a SHADOW user-executed-sim record
    sidecar, markdown = _report_of(tmp_path, "system", _shadow_rows()[3:], capsys)
    delay = _paper_block(sidecar)["approval_delay"]
    assert delay["user_execution"]["n_signals"] == 0
    assert delay["synthetic_lag_label"] is not None
    assert SYNTHETIC_LABEL in markdown


# --------------------------------------------------------------------------- #
# Task 3: the report states the soak rule and no metric was added (D-18).
# --------------------------------------------------------------------------- #

SOAK_SENTENCE = "Soak evidence never feeds a value into trading logic (D-18)."
SHADOW_KEYS = (
    "mode",
    "approval_requested_at_utc",
    "confirm_requested_at_utc",
    "confirmed_at_utc",
    "test_only",
)
# Display counters of the PAPER block (plan 16-36): counts of rows, not metrics.
COUNTER_KEYS = {"shadow_records", "test_only_excluded"}


def _without_shadow_fields(document: dict[str, Any]) -> dict[str, Any]:
    stripped = copy.deepcopy(document)
    for record in stripped["paper"]:
        for key in SHADOW_KEYS:
            record.pop(key, None)
    return stripped


def _names(markdown: str) -> set[str]:
    """Section headings and table column names: the metric and section vocabulary of a report."""
    lines = markdown.split("\n")
    names = {line for line in lines if line.startswith("#")}
    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("| :---") or line.startswith("| ---"):
            names.add(lines[index - 1])
    return names


def _key_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        paths: set[str] = set()
        for key, child in value.items():
            paths.add(f"{prefix}/{key}")
            paths |= _key_paths(child, f"{prefix}/{key}")
        return paths
    if isinstance(value, list):
        paths = set()
        for child in value:
            paths |= _key_paths(child, f"{prefix}[]")
        return paths
    return set()


def test_a_report_of_shadow_evidence_states_the_soak_rule_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, markdown = _report_of(tmp_path, "shadow", _shadow_rows(), capsys)
    assert markdown.split("\n").count(SOAK_SENTENCE) == 1


def test_a_report_without_shadow_records_does_not_carry_the_sentence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _without_shadow_fields(_export(_shadow_rows()))
    _, _, _, markdown = _run_cli(tmp_path, _write(tmp_path, document), capsys)
    assert SOAK_SENTENCE not in markdown


def test_shadow_evidence_adds_no_metric_or_section_to_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shadow_dir = tmp_path / "shadow"
    plain_dir = tmp_path / "plain"
    shadow_dir.mkdir()
    plain_dir.mkdir()
    document = _export(_shadow_rows())
    _, _, shadow_sidecar, shadow_md = _run_cli(shadow_dir, _write(shadow_dir, document), capsys)
    plain_doc = _without_shadow_fields(document)
    _, _, plain_sidecar, plain_md = _run_cli(plain_dir, _write(plain_dir, plain_doc), capsys)

    assert _names(shadow_md) == _names(plain_md)
    shadow_paths = _key_paths(shadow_sidecar["report"])
    plain_paths = _key_paths(plain_sidecar["report"])
    only_shadow = {path.rsplit("/", 1)[-1] for path in shadow_paths - plain_paths}
    assert only_shadow <= COUNTER_KEYS
    assert plain_paths - shadow_paths == set()


def test_the_new_sentence_obeys_the_byte_rules_of_the_renderer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, markdown = _report_of(tmp_path, "bytes", _shadow_rows(), capsys)
    assert "\r" not in markdown
    assert markdown.endswith("\n") and not markdown.endswith("\n\n")
    line = next(line for line in markdown.split("\n") if line.startswith("Soak evidence"))
    assert line == line.rstrip()
    assert line == SOAK_SENTENCE
