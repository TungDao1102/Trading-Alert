"""The per-session evidence index of an owner Demo session (plan 25-08).

TEST_ONLY. One index per owner session lists, for every evidence file of the session, the scenario,
its outcome, the labels with step counts and the order ids (the Demo order ids, the client order ids
and the algo client ids), as `25-DEMO-SESSION-INDEX-<stamp>.json` and a sibling `.md` table the
results plan can copy. A file that is not `demo-scenario-evidence/schema-1` is listed as REJECTED
with its name, never silently dropped. The writer is create-only (a counter suffix, never an
overwrite), scrubs with the project `Redactor` and re-reads the written text with the same scan as
`EvidenceRecorder.write` (T-25-18); text is LF only and JSON keys are sorted.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import demo_rehearsal as dr
from src.ops.redaction import Redactor

from tests.support.demo_scenarios.harness import SCENARIO_EVIDENCE_SCHEMA

SESSION_INDEX_SCHEMA = "demo-session-index/schema-1"
STATUS_LISTED = "LISTED"
STATUS_REJECTED = "REJECTED"
_TABLE_HEADER = (
    "| Scenario | File | Outcome | Labels | Demo order ids | Client order ids | Algo client ids |"
)
_TABLE_RULE = "|---|---|---|---|---|---|---|"


def write_session_index(
    evidence_dir: Path,
    evidence_files: Sequence[Path],
    *,
    session_id: str,
    clock: Callable[[], datetime],
    environ: Mapping[str, str],
) -> Path:
    """Write the index and its `.md` table into `evidence_dir`; returns the JSON path."""
    rows = sorted(
        (_row(path) for path in evidence_files),
        key=lambda row: (row.get("scenario_id", "~"), row["file"]),
    )
    now = clock()
    document = {
        "schema": SESSION_INDEX_SCHEMA,
        "session_id": session_id,
        "generated_at_utc": dr._jsonable(now),
        "rows": rows,
    }
    json_text = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    table_text = _markdown(session_id, rows)
    redactor = Redactor.from_environ(environ)
    json_text = redactor.scrub(json_text)
    table_text = redactor.scrub(table_text)

    evidence_dir.mkdir(parents=True, exist_ok=True)
    stem = f"25-DEMO-SESSION-INDEX-{dr._utc_stamp(now)}"
    target = evidence_dir / f"{stem}.json"
    table_target = target.with_suffix(".md")
    counter = 2
    while target.exists() or table_target.exists():
        target = evidence_dir / f"{stem}-{counter}.json"
        table_target = target.with_suffix(".md")
        counter += 1
    written: list[Path] = []
    try:
        for path, text in ((target, json_text), (table_target, table_text)):
            _write_atomic(path, text)
            written.append(path)
        for path in written:
            on_disk = path.read_bytes().decode("utf-8")
            if redactor.scrub(on_disk) != on_disk:
                raise RuntimeError("index failed the post-write secret scan and was removed")
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return target


def _write_atomic(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temp, path)


def _row(path: Path) -> dict[str, Any]:
    name = path.name
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _rejected(name, "unreadable or not JSON")
    if not isinstance(document, dict) or document.get("schema") != SCENARIO_EVIDENCE_SCHEMA:
        return _rejected(name, f"not {SCENARIO_EVIDENCE_SCHEMA}")
    labels: dict[str, int] = {}
    for step in document.get("steps", []):
        label = str(step.get("label", "UNLABELED"))
        labels[label] = labels.get(label, 0) + 1
    order_ids: list[str] = []
    client_ids: list[str] = []
    algo_ids: list[str] = []
    for entry in document.get("details", {}).get("order_ids", []):
        _extend(order_ids, entry.get("demo_order_ids", ()))
        _extend(client_ids, entry.get("client_order_ids", ()))
        _extend(algo_ids, entry.get("algo_client_ids", ()))
    return {
        "scenario_id": str(document.get("scenario_id", "")),
        "file": name,
        "status": STATUS_LISTED,
        "outcome": str(document.get("outcome", "")),
        "labels": dict(sorted(labels.items())),
        "demo_order_ids": order_ids,
        "client_order_ids": client_ids,
        "algo_client_ids": algo_ids,
    }


def _rejected(name: str, reason: str) -> dict[str, Any]:
    return {"file": name, "status": STATUS_REJECTED, "reason": reason}


def _extend(target: list[str], values: Iterable[Any]) -> None:
    for value in values:
        text = str(value)
        if text not in target:
            target.append(text)


def _markdown(session_id: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"# Demo session index: {_cell(session_id)}", "", _TABLE_HEADER, _TABLE_RULE]
    for row in rows:
        if row["status"] == STATUS_REJECTED:
            lines.append(
                f"| REJECTED | {_cell(row['file'])} | {_cell(row['reason'])} | - | - | - | - |"
            )
            continue
        labels = ", ".join(f"{label}: {count}" for label, count in row["labels"].items())
        cells = [
            row["scenario_id"],
            row["file"],
            row["outcome"],
            labels,
            ", ".join(row["demo_order_ids"]),
            ", ".join(row["client_order_ids"]),
            ", ".join(row["algo_client_ids"]),
        ]
        lines.append("| " + " | ".join(_cell(cell) or "-" for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


__all__ = ["SESSION_INDEX_SCHEMA", "write_session_index"]
