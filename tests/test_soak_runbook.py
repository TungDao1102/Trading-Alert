"""RUNBOOK section 19 (soak host) and the acceptance-file validator (Phase 16, plan 16-07).

The runbook text is the instruction set for the user's weekend EC2 provisioning (D061, D-34).
These tests keep the text and the validator in step: every D042 acceptance condition has a
command in the text, every command the text names exists in the repository, and a filled
acceptance file is machine-checked without ever printing a secret-looking value.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from scripts import soak_host_acceptance as sha

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"

CHECKED_AT = "2026-10-10T08:00:00Z"


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8").replace("\r\n", "\n")


def _section19() -> str:
    match = re.search(r"^## 19\. [^\n]*\n(.*?)(?=^## \d+\. |\Z)", _runbook(), re.M | re.S)
    return match.group(0) if match else ""


def _subsection(number: str) -> str:
    match = re.search(
        rf"^### {re.escape(number)} [^\n]*\n(.*?)(?=^##|\Z)", _section19(), re.M | re.S
    )
    return match.group(0) if match else ""


def _entry(**override: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "status": "PASS",
        "command": "curl -sS -o /dev/null -w %{http_code} https://fapi.binance.com/fapi/v1/ping",
        "evidence": "HTTP 200",
        "checked_at": CHECKED_AT,
    }
    entry.update(override)
    return entry


def _filled(**per_condition: dict[str, Any]) -> dict[str, Any]:
    conditions = {name: _entry() for name in sha.REQUIRED_CONDITIONS}
    conditions.update(per_condition)
    return {"schema": sha.SCHEMA, "conditions": conditions}


def _write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- validator


def test_a_complete_all_pass_file_exits_0(tmp_path: Path) -> None:
    assert sha.main([str(_write(tmp_path, _filled()))]) == 0


def test_a_missing_or_non_pass_condition_exits_1_and_names_the_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _filled()
    del document["conditions"]["CHRONY_SYNCED"]
    document["conditions"]["ELASTIC_IP"] = _entry(status="FAIL")
    assert sha.main([str(_write(tmp_path, document))]) == 1
    out = capsys.readouterr()
    # the first condition in the required order that is wrong is the one named
    assert sha.REQUIRED_CONDITIONS.index("ELASTIC_IP") < sha.REQUIRED_CONDITIONS.index(
        "CHRONY_SYNCED"
    )
    assert "ELASTIC_IP" in out.err + out.out


def test_a_secret_looking_value_exits_2_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "AKIA" + "ABCDEFGHIJKLMNOP"
    document = _filled(S3_BUCKET_PRIVATE=_entry(evidence=f"key {secret} listed"))
    assert sha.main([str(_write(tmp_path, document))]) == 2
    out = capsys.readouterr()
    assert secret not in out.out + out.err
    assert "S3_BUCKET_PRIVATE" in out.out + out.err


# --------------------------------------------------------------------------- runbook text


def test_runbook_section_19_exists_and_the_region_ping_is_the_first_host_action() -> None:
    section = _section19()
    assert section, "RUNBOOK has no '## 19.' section"
    assert re.search(
        r"^## 19\. Soak host \(EC2\) provisioning, migration and data path$", _runbook(), re.M
    )
    first_action = _subsection("19.2")
    assert first_action, "section 19 has no 19.2"
    assert "public ping to fapi.binance.com" in first_action
    command = 'curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping'
    assert command in first_action
    assert "HTTP 200" in first_action
    assert "do not install anything" in first_action
