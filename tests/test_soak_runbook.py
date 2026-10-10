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


# --------------------------------------------------------------------------- 19.3 and 19.4


def _acceptance_rows() -> list[dict[str, str]]:
    """Rows of the 19.3 table whose header row starts with ``| Condition id |``."""
    lines = _subsection("19.3").split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.startswith("| Condition id |")), None)
    assert start is not None, "19.3 has no '| Condition id |' table"
    headers = [c.strip() for c in lines[start].strip().strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for ln in lines[start + 2 :]:
        if not ln.startswith("|"):
            break
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def test_19_3_names_a_command_and_a_pass_condition_for_every_required_condition() -> None:
    rows = _acceptance_rows()
    ids = [row["Condition id"].strip("`") for row in rows]
    assert ids == list(sha.REQUIRED_CONDITIONS), "19.3 must list the validator ids in order"
    for row in rows:
        name = row["Condition id"]
        assert row["Command"].strip("`"), f"{name}: no command"
        assert row["Pass condition"], f"{name}: no pass condition"
        assert row["Source"], f"{name}: no source"


def test_19_3_external_facts_carry_a_url_the_read_date_and_the_not_verified_label() -> None:
    cited = 0
    for row in _acceptance_rows():
        source = row["Source"]
        if "https://" in source:
            cited += 1
            assert "2026-10-08" in source, f"{row['Condition id']}: no read date"
            assert "not verified live" in source, f"{row['Condition id']}: no label"
    assert cited >= 4


def test_19_3_ebs_default_encryption_is_checked_because_the_initial_state_is_undocumented() -> None:
    body = _subsection("19.3")
    assert "aws ec2 get-ebs-encryption-by-default --region ap-southeast-1" in body
    assert "initial state" in body
    assert "not documented" in body


def test_19_3_chrony_uses_the_amazon_time_sync_service_line() -> None:
    body = _subsection("19.3")
    assert "server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4" in body
    assert "/etc/chrony/chrony.conf" in body
    assert "chronyc tracking" in body
    assert "chronyc sources" in body


def test_19_3_checks_sudo_asks_for_a_password_without_naming_a_bypass_rule() -> None:
    row = next(r for r in _acceptance_rows() if "SUDO_WITH_PASSWORD" in r["Condition id"])
    assert "sudo -k" in row["Command"]
    assert "sudo -v" in row["Command"]


def test_19_4_only_the_collector_moves_and_the_oi_gap_is_a_coverage_gap() -> None:
    body = _subsection("19.4")
    assert body, "section 19 has no 19.4"
    for phrase in (
        "only the collector moves",
        "deploy/migrate.sh",
        "coverage gap",
        "D059",
        "full history",
        "UAT 8",
        "UAT 9",
        "UAT 10",
        "section 13",
        "section 15",
    ):
        assert phrase in body, f"19.4 lacks: {phrase}"


def test_19_4_waits_for_the_real_s3_gate_and_a_restore_drill_before_the_long_soak() -> None:
    body = _subsection("19.4")
    assert "D064 real-S3 gate" in body
    assert "11.6" in body
    assert "before the long soak" in body
    assert "first real backup" in body


INSTANCE_TYPE = re.compile(r"\b[a-z]\d[a-z]?\.(?:nano|micro|small|medium|large|xlarge|\d+xlarge)\b")
SIZE_UNIT = re.compile(r"\d\s?(?:GB|GiB|TB|TiB)\b|\bGB\b")
CURRENCY = re.compile(r"\$\s?\d|\d\s?(?:USD|EUR)\b")


def test_section_19_fills_no_number_the_user_owns() -> None:
    section = _section19()
    assert "16-DEC-O-12" in section
    assert not INSTANCE_TYPE.findall(section), "an instance type name is written"
    assert not SIZE_UNIT.findall(section), "a storage size is written"
    for line in section.split("\n"):
        if CURRENCY.search(line):
            # the one cited price: public IPv4 per hour (G13), with its URL and read date
            assert "0.005" in line and "https://aws.amazon.com/vpc/pricing/" in line, line
            assert "2026-10-08" in line


def test_every_repository_path_section_19_names_exists() -> None:
    section = _section19()
    paths = set(re.findall(r"\b((?:deploy|scripts)/[\w.-]+\.(?:sh|py|ps1))\b", section))
    assert {"deploy/migrate.sh", "deploy/restore.sh", "scripts/soak_host_acceptance.py"} <= paths
    for relative in sorted(paths):
        assert (REPO_ROOT / relative).is_file(), f"section 19 names a missing file: {relative}"


# --------------------------------------------------------------------------- 19.5 to 19.7

BACKUP_CLI = REPO_ROOT / "src" / "ops" / "backup.py"
PULL_COMMAND = (
    "docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python "
    "-m src.ops.backup pull --dest /app/data/backup/pull-<UTC timestamp>"
)
COPY_COMMAND = (
    "docker compose --profile ops run --rm -T --no-deps ops /app/.venv/bin/python "
    "-m src.ops.backup restore --bundle-root /app/data/backup/pull-<UTC timestamp> "
    "--parquet-target /app/data/raw --skip-db --force"
)


def _backup_cli_source() -> str:
    return BACKUP_CLI.read_text(encoding="utf-8")


def test_19_5_gives_the_exact_pull_and_the_no_overwrite_copy_commands() -> None:
    body = _subsection("19.5")
    assert body, "section 19 has no 19.5"
    assert PULL_COMMAND in body
    assert COPY_COMMAND in body
    assert "--snapshot" in body
    assert "src.ops.backup verify --bundle-root /app/data/backup/pull-<UTC timestamp>" in body
    for phrase in (
        "BACKUP_",
        "section 11",
        "never overwrite",
        "raw files are immutable",
        "already exists in the target with different content",
    ):
        assert phrase in body, f"19.5 lacks: {phrase}"


def test_the_backup_cli_has_every_subcommand_and_flag_19_5_uses() -> None:
    source = _backup_cli_source()
    for subcommand in ("pull", "verify", "restore"):
        assert f'sub.add_parser(\n        "{subcommand}"' in source or (
            f'sub.add_parser("{subcommand}"' in source
        ), f"src/ops/backup.py has no subcommand {subcommand}"
    for flag in (
        "--dest",
        "--snapshot",
        "--bundle-root",
        "--parquet-target",
        "--skip-db",
        "--force",
    ):
        assert f'"{flag}"' in source, f"src/ops/backup.py has no flag {flag}"
    body = _subsection("19.5")
    for flag in re.findall(r"--[a-z][a-z-]*", body):
        allowed = {"--profile", "--rm", "--no-deps", "--dest", "--snapshot", "--bundle-root"}
        allowed |= {"--parquet-target", "--skip-db", "--force"}
        assert flag in allowed, f"19.5 uses an undeclared flag: {flag}"


def test_19_6_lists_the_rev_08_facts_each_with_url_and_read_date() -> None:
    body = _subsection("19.6")
    assert body, "section 19 has no 19.6"
    for phrase in (
        "S3 Versioning",
        "can be enabled on an existing bucket",
        "cannot be disabled",
        "GOVERNANCE",
        "COMPLIANCE",
        "bucket default retention",
        "per-object retention",
        "403",
        "Hashes are not stored for crypt",
        "BACKUP_CRYPT_PASSWORD",
        "BACKUP_CRYPT_PASSWORD2",
        "24 hour",
        "inference",
        "UNVERIFIED",
        "apply_retention",
        "push_snapshot",
        "rclone purge",
        "Git hashes do not make S3 immutable",
        "an Actions cache is never a source of truth",
    ):
        assert phrase in body, f"19.6 lacks: {phrase}"
    urls = re.findall(r"https://[^\s)]+", body)
    assert len(urls) >= 6
    assert body.count("read 2026-10-08") >= len(set(urls)) - 1
    assert body.rstrip().endswith("No option is selected here; the decision is O-01 (plan 16-30).")


def test_19_6_cites_functions_that_exist_in_the_backup_chain() -> None:
    source = (REPO_ROOT / "src" / "ops" / "backup_remote.py").read_text(encoding="utf-8")
    body = _subsection("19.6")
    for name in re.findall(r"`(\w+)`", body):
        if name in {"apply_retention", "push_snapshot", "check_sentinel", "init_sentinel"}:
            assert f"def {name}(" in source, f"19.6 names a missing function: {name}"


def test_19_7_points_to_the_real_host_only_list_in_section_17() -> None:
    body = _subsection("19.7")
    assert body, "section 19 has no 19.7"
    assert "section 17" in body
    assert "Only a real host can show" in body


# --------------------------------------------------------------------------- heartbeat (16-50)


def test_19_3_heartbeat_row_and_paragraph_describe_the_sender() -> None:
    row = next(
        r for r in _acceptance_rows() if "HEARTBEAT_MONITOR_ALERT_RECEIVED" in r["Condition id"]
    )
    assert "an alert from the external monitor reached the operator" in row["Pass condition"]
    assert "a recovery notice followed the start" in row["Pass condition"]
    assert "11.9" in row["Command"] + row["Source"]
    assert "https://" not in row["Source"], "the Source cell must not carry a URL"
    command = row["Command"]
    assert "/opt/trading" in command and "docker compose stop collector" in command
    assert "period plus" in command and "grace" in command and "16-DEC-O-12" in command
    body = _subsection("19.3")
    assert "This repository sends no heartbeat" not in body
    start = body.index("**Heartbeat monitor.**")
    paragraph = body[start : body.index("\n\n", start)]
    for phrase in (
        "healthchecks.io",
        "deploy/heartbeat.sh",
        "11.9",
        "scripts/soak_host_acceptance.py",
        "exits 2",
        "coverage gap",
        "16-DEC-O-12",
    ):
        assert phrase in paragraph, f"the Heartbeat monitor paragraph lacks: {phrase}"


def test_19_4_item_5_stores_the_ping_url_on_the_new_host_before_the_old_timer_goes() -> None:
    body = _subsection("19.4")
    item = next(ln for ln in body.splitlines() if ln.startswith("5. "))
    assert "11.9" in item and "--set-url" in item
    assert "before the old host's timer is disabled" in item
