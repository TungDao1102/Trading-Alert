"""Validate the filled acceptance file of the soak host (Phase 16, plan 16-07, D042, D-34).

RUNBOOK section 19.3 lists one measurable acceptance check per D042 condition. The operator
runs each command on the new EC2 host and records the result in a JSON file:

    {
      "schema": "soak-host-acceptance/1",
      "conditions": {
        "REGION_PING_FAPI": {
          "status": "PASS",
          "command": "curl -sS -o /dev/null -w \\"%{http_code}\\" https://fapi.binance.com/fapi/v1/ping",
          "evidence": "HTTP 200",
          "checked_at": "2026-10-10T08:00:00Z"
        }
      }
    }

This script reads that file and checks it. It never contacts a host, AWS or the network, and it
never decides whether a check really passed: it only refuses a file in which a required
condition is missing, is not ``PASS`` or lacks its command, evidence or UTC time.

Exit codes: 0 every required condition is complete and ``PASS``; 1 the first required condition
(in ``REQUIRED_CONDITIONS`` order) that is missing, incomplete or not ``PASS`` is named; 2 the
input is unusable or holds a secret-looking value. A message names the condition and the field,
never the value, so a secret pasted into the file is not copied to a terminal or a log.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ops.redaction import Redactor  # noqa: E402

SCHEMA = "soak-host-acceptance/1"

EXIT_OK = 0
EXIT_CONDITION = 1
EXIT_INPUT = 2

# One id per D042 condition, in the order RUNBOOK 19.3 lists them (region ping first, 19.2).
REQUIRED_CONDITIONS: tuple[str, ...] = (
    "REGION_PING_FAPI",
    "ELASTIC_IP",
    "EBS_ENCRYPTED_BY_DEFAULT",
    "EBS_ROOT_VOLUME_ENCRYPTED",
    "S3_BUCKET_PRIVATE",
    "S3_DEFAULT_ENCRYPTION",
    "S3_VERSIONING",
    "HEARTBEAT_MONITOR_ALERT_RECEIVED",
    "CHRONY_SYNCED",
    "BUDGET_ALERT",
    "PAID_PLAN",
    "SSH_KEY_ONLY",
    "POSTGRES_NOT_PUBLIC",
    "ENV_FILE_MODE_0600",
    "SUDO_WITH_PASSWORD",  # WR-05 / D062
    "BACKUP_REAL_S3_GATE",  # D064
)

PASS = "PASS"
_ENTRY_FIELDS: tuple[str, ...] = ("status", "command", "evidence", "checked_at")
_UTC_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class InputProblem(Exception):
    """The file cannot be used; the message never carries a value from the file."""


def _utc_time_ok(text: str) -> bool:
    if not _UTC_TIME.match(text):
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return False
    return True


def _load(path: Path) -> tuple[str, Mapping[str, Any]]:
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputProblem(f"cannot read the acceptance file ({type(exc).__name__})") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputProblem("the acceptance file is not valid JSON") from exc
    if not isinstance(document, dict):
        raise InputProblem("the acceptance file must hold a JSON object")
    return raw, document


def _scan_for_secrets(document: Mapping[str, Any], redactor: Redactor) -> None:
    """Raise ``InputProblem`` naming the condition and field of the first secret-looking value.

    Every string leaf is scrubbed on its own with the shape rules of ``src.ops.redaction`` plus
    the values of secret-named environment variables of this process; a leaf the scrub would
    change is a finding. Only the condition id (a known constant) and the field name are used in
    the message, never the leaf.
    """
    top_level = {"schema", "conditions"}
    for key, value in document.items():
        if key not in top_level:
            raise InputProblem("the acceptance file has an unexpected top-level field")
        if isinstance(value, str) and redactor.scrub(value) != value:
            raise InputProblem(f"secret-looking value in top-level field '{key}'")
    conditions = document.get("conditions")
    if not isinstance(conditions, dict):
        return
    for condition_id, entry in conditions.items():
        label = condition_id if condition_id in REQUIRED_CONDITIONS else "<unknown condition>"
        if redactor.scrub(str(condition_id)) != str(condition_id):
            raise InputProblem("secret-looking value in a condition id")
        if not isinstance(entry, dict):
            continue
        for field, value in entry.items():
            if field not in _ENTRY_FIELDS:
                raise InputProblem(f"unexpected field in condition {label}")
            if isinstance(value, str) and redactor.scrub(value) != value:
                raise InputProblem(f"secret-looking value in condition {label}, field '{field}'")


def _first_problem(document: Mapping[str, Any]) -> str | None:
    if document.get("schema") != SCHEMA:
        return f"schema must be '{SCHEMA}'"
    conditions = document.get("conditions")
    if not isinstance(conditions, dict):
        return "'conditions' must be an object"
    for condition_id in REQUIRED_CONDITIONS:
        entry = conditions.get(condition_id)
        if entry is None:
            return f"{condition_id}: missing"
        if not isinstance(entry, dict):
            return f"{condition_id}: entry must be an object"
        status = entry.get("status")
        if status != PASS:
            return f"{condition_id}: status is not {PASS}"
        for field in ("command", "evidence"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                return f"{condition_id}: {field} is empty"
        checked_at = entry.get("checked_at")
        if not isinstance(checked_at, str) or not _utc_time_ok(checked_at):
            return f"{condition_id}: checked_at is not a UTC time (YYYY-MM-DDTHH:MM:SSZ)"
    return None


def validate(path: Path) -> tuple[int, str]:
    """Return ``(exit code, message)`` for one acceptance file."""
    try:
        _raw, document = _load(path)
        _scan_for_secrets(document, Redactor.from_environ(os.environ))
    except InputProblem as exc:
        return EXIT_INPUT, f"input error: {exc}"
    problem = _first_problem(document)
    if problem is not None:
        return EXIT_CONDITION, f"not accepted: {problem}"
    return EXIT_OK, f"accepted: {len(REQUIRED_CONDITIONS)} conditions PASS"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the filled soak host acceptance file (RUNBOOK 19.3)."
    )
    parser.add_argument("acceptance_file", type=Path)
    args = parser.parse_args(argv)
    code, message = validate(args.acceptance_file)
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
