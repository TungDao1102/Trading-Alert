"""RUNBOOK section 19 (soak host) and the acceptance-file validator (Phase 16, plan 16-07).

The runbook text is the instruction set for the user's weekend EC2 provisioning (D061, D-34).
These tests keep the text and the validator in step: every D042 acceptance condition has a
command in the text, every command the text names exists in the repository, and a filled
acceptance file is machine-checked without ever printing a secret-looking value.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import soak_host_acceptance as sha

from tests.infra_helpers import find_bash, infra_skip

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


# --------------------------------------------------------------------------- ping URL guard (16-50)

FAKE_UUID = "00000000-1111-4222-8333-444444444444"  # FAKE, never a real check
PING_URL_VALUES = {
    "uuid-path": f"https://monitor.invalid/{FAKE_UUID}",
    "uuid-path-with-suffix": f"alert received after https://monitor.invalid/{FAKE_UUID}/fail",
    "uuid-http": f"http://monitor.invalid:8000/ping/{FAKE_UUID}",
    "ping-domain-slug": "https://hc-ping.com/FAKEPINGKEY0000/fake-slug",
    "ping-domain-subdomain": "curl -fsS https://eu.hc-ping.com/FAKEPINGKEY0000/fake-slug",
}


@pytest.mark.parametrize("name", sorted(PING_URL_VALUES))
@pytest.mark.parametrize("field", ["evidence", "command"])
def test_a_ping_url_shaped_value_exits_2_naming_the_condition_and_field_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, field: str
) -> None:
    value = PING_URL_VALUES[name]
    document = _filled(HEARTBEAT_MONITOR_ALERT_RECEIVED=_entry(**{field: value}))
    assert sha.main([str(_write(tmp_path, document))]) == 2
    out = capsys.readouterr()
    text = out.out + out.err
    assert "HEARTBEAT_MONITOR_ALERT_RECEIVED" in text and field in text
    for fragment in (FAKE_UUID, "FAKEPINGKEY0000", "fake-slug", "monitor.invalid"):
        assert fragment not in text


@pytest.mark.parametrize(
    "evidence",
    [
        f"arn:aws:kms:ap-southeast-1:123456789012:key/{FAKE_UUID}",
        "HTTP 200 from https://fapi.binance.com/fapi/v1/ping",
        "alert at 2026-10-11T08:00:00Z, recovery at 2026-10-11T08:09:00Z",
    ],
    ids=["aws-arn", "binance-ping", "times-only"],
)
def test_evidence_that_only_resembles_a_ping_url_still_passes(
    tmp_path: Path, evidence: str
) -> None:
    document = _filled(S3_DEFAULT_ENCRYPTION=_entry(evidence=evidence))
    assert sha.main([str(_write(tmp_path, document))]) == 0


# --------------------------------------------------------------------------- section 20 (16-33)

SECTION_20_HEADING = "## 20. Soak project operations"
SECTION_20_SUBSECTIONS = (
    "20.1 Project and wrapper",
    "20.2 Deploys during the trial soak",
    "20.3 Telegram bot",
    "20.4 Rehearsal before the trial",
    "20.5 Backups and restore drill before the long soak",
    "20.6 Image",
    "20.7 Exporting trial evidence",
)


def _section20() -> str:
    match = re.search(r"^## 20\. [^\n]*\n(.*?)(?=^## \d+\. |\Z)", _runbook(), re.M | re.S)
    return match.group(0) if match else ""


def _sub20(number: str) -> str:
    match = re.search(
        rf"^### {re.escape(number)} [^\n]*\n(.*?)(?=^##|\Z)", _section20(), re.M | re.S
    )
    return match.group(0) if match else ""


def _fenced_lines(text: str) -> list[str]:
    lines: list[str] = []
    inside = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append(line)
    return lines


def test_section_20_has_the_heading_and_subsections_20_1_to_20_6() -> None:
    assert re.search(rf"^{re.escape(SECTION_20_HEADING)}$", _runbook(), re.M)
    for title in SECTION_20_SUBSECTIONS:
        assert re.search(rf"^### {re.escape(title)}$", _section20(), re.M), title


def test_20_1_names_the_wrapper_and_forbids_down_with_volumes() -> None:
    body = _sub20("20.1")
    assert "deploy/compose-soak.sh" in body
    assert "trading-soak" in body
    assert "never" in body and "down -v" in body
    assert (REPO_ROOT / "deploy" / "compose-soak.sh").is_file()


def test_20_2_every_deploy_is_an_uncovered_planned_restart_with_the_derived_budget() -> None:
    body = _sub20("20.2")
    for phrase in (
        "PLANNED_RESTART",
        "never covered",
        "336",
        "95 percent",
        "16.8",
        "REV-01",
        "REV-17",
    ):
        assert phrase in body, f"20.2 lacks: {phrase}"
    assert "all uncovered time together" in body


def test_20_3_states_the_recorded_telegram_rule_and_holds_no_token() -> None:
    body = _sub20("20.3")
    decision = (
        REPO_ROOT / ".planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-L.md"
    ).read_text(encoding="utf-8")
    assert "option: separate-bot" in decision
    for phrase in ("16-DEC-Q-L", "separate bot", "BotFather", "never pasted"):
        assert phrase in body, f"20.3 lacks: {phrase}"
    assert not re.search(r"\d{6,}:[A-Za-z0-9_-]{20,}", body), "a token-shaped value is written"


def test_20_4_the_rehearsal_runs_in_its_own_project_before_the_trial() -> None:
    body = _sub20("20.4")
    for phrase in ("trading-rehearsal", "before the trial", "REV-03", "never in trading-soak"):
        assert phrase in body, f"20.4 lacks: {phrase}"


def test_20_5_requires_a_backup_and_a_restore_drill_into_a_scratch_target() -> None:
    body = _sub20("20.5")
    for phrase in (
        "11.4",
        "11.6",
        "before the long soak",
        "scratch",
        "never into the soak database",
    ):
        assert phrase in body, f"20.5 lacks: {phrase}"


def test_20_6_points_to_the_image_decision_record() -> None:
    body = _sub20("20.6")
    assert "decisions/16-DEC-Q-I.md" in body


def test_no_fenced_line_of_section_20_runs_down_with_volumes() -> None:
    lines = _fenced_lines(_section20())
    assert lines, "section 20 has no fenced command to scan"
    for line in lines:
        assert not re.search(r"\bdown\b.*(?:\s-\w*v\w*\b|--volumes)", line), line


def test_20_1_lists_every_exit_code_and_the_hold_on_refusal_rule() -> None:
    from src.paper.runtime_config import ExitCode

    body = _sub20("20.1")
    for member in ExitCode:
        row = next((ln for ln in body.split("\n") if f"`{member.name}`" in ln), None)
        assert row is not None, f"20.1 has no line for ExitCode.{member.name}"
        assert re.search(rf"\b{int(member)}\b", row), f"{member.name}: code {int(member)} missing"
        assert len(row.split("|")) >= 4 and row.split("|")[-2].strip(), f"{member.name}: no meaning"
    for phrase in (
        "--hold-on-refusal",
        "codes 3 to 6",
        "unhealthy",
        "container log",
        "stop the container before",
        "SKIPPED",
        "exits 0",
        "not restarted",
        "CRASH",
    ):
        assert phrase in body, f"20.1 lacks: {phrase}"


# --------------------------------------------------------------------------- 16-33 task 3
# Q-I decision (host-build-recorded): the soak image is built on the host at a recorded commit.


DECISION_Q_I = REPO_ROOT / ".planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-I.md"
SOAK_IMAGE_SCRIPT = REPO_ROOT / "deploy" / "soak-image.sh"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=60
    )
    return proc.stdout.strip()


def _recipe_repo(tmp_path: Path) -> Path:
    """A throwaway git repository holding copies of the deploy scripts, clean and committed."""
    repo = tmp_path / "checkout"
    (repo / "deploy").mkdir(parents=True)
    for name in ("soak-image.sh", "lib.sh", "compose-soak.sh"):
        source = REPO_ROOT / "deploy" / name
        assert source.is_file(), f"deploy/{name} does not exist"
        shutil.copyfile(source, repo / "deploy" / name)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _run_recipe(repo: Path, state_dir: Path) -> subprocess.CompletedProcess[str]:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DRY_RUN", "IMAGE_TAG", "COMPOSE_PROJECT_NAME", "TRADING_ENV_FILE"}
    }
    env["DRY_RUN"] = "1"
    env["TRADING_DEPLOY_STATE_DIR"] = state_dir.as_posix()
    return subprocess.run(
        [bash, (repo / "deploy" / "soak-image.sh").as_posix()],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )


def test_q_i_decision_is_recorded_by_the_user() -> None:
    text = DECISION_Q_I.read_text(encoding="utf-8")
    assert re.search(r"^option: host-build-recorded$", text, re.M)
    assert re.search(r"^decided by: user$", text, re.M)
    assert re.search(r"^date: \d{4}-\d{2}-\d{2}$", text, re.M)
    assert re.search(r"^words: .+", text, re.M)


def test_soak_image_dry_run_prints_the_commit_build_and_the_record(tmp_path: Path) -> None:
    repo = _recipe_repo(tmp_path)
    commit = _git(repo, "rev-parse", "HEAD")
    proc = _run_recipe(repo, tmp_path / "state")
    assert proc.returncode == 0, proc.stderr.strip()[:300]
    out = proc.stdout
    assert f"trading-alert:{commit}" in out
    assert f"trading-alert-ops:{commit}" in out
    assert "compose-soak.sh --profile ops build" in out
    assert "soak-image.env" in out
    assert f"GIT_SHA={commit}" in out
    assert "APP_IMAGE_ID=" in out and "OPS_IMAGE_ID=" in out
    assert not (tmp_path / "state").exists(), "a dry run must write nothing"


def test_soak_image_refuses_a_modified_tracked_file(tmp_path: Path) -> None:
    repo = _recipe_repo(tmp_path)
    with (repo / "deploy" / "lib.sh").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("# local edit\n")
    proc = _run_recipe(repo, tmp_path / "state")
    assert proc.returncode != 0
    assert "uncommitted" in proc.stderr
    assert "+ " not in proc.stdout, "nothing may be announced as run on a dirty tree"


def test_soak_image_refuses_an_untracked_file(tmp_path: Path) -> None:
    repo = _recipe_repo(tmp_path)
    (repo / "stray.py").write_text("x = 1\n", encoding="utf-8")
    proc = _run_recipe(repo, tmp_path / "state")
    assert proc.returncode != 0
    assert "uncommitted" in proc.stderr


def test_20_6_gives_the_recipe_commands_and_the_bind_mount_rule() -> None:
    body = _sub20("20.6")
    for phrase in (
        "decisions/16-DEC-Q-I.md",
        "host-build-recorded",
        "deploy/soak-image.sh",
        "soak-image.env",
        "IMAGE_TAG",
        "deploy/compose-soak.sh",
        "never runs from a working-tree bind mount",
        "refuses a dirty working tree",
        "not automatic fallbacks",
    ):
        assert phrase in body, f"20.6 lacks: {phrase}"
    assert (REPO_ROOT / "deploy" / "soak-image.sh").is_file()


def test_20_6_requires_a_rebuild_after_the_allowlist_commit_and_relates_update_sh() -> None:
    body = _sub20("20.6")
    for phrase in (
        "allowlist is a source constant",
        "O-04",
        "16-42",
        "rebuilt after the allowlist commit",
        "deploy/update.sh",
        "last-good.env",
    ):
        assert phrase in body, f"20.6 lacks: {phrase}"


# ----- 20.7 Exporting trial evidence (plan 16-47) ----------------------------------------


def _commands_20_7() -> list[list[str]]:
    """The fenced commands of 20.7 as argv lists (backslash continuations joined)."""
    import shlex

    joined = "\n".join(_fenced_lines(_sub20("20.7"))).replace("\\\n", " ")
    commands: list[list[str]] = []
    for line in joined.split("\n"):
        if line.strip():
            commands.append(shlex.split(line.strip(), posix=True))
    return commands


def test_20_7_gives_the_exact_export_publish_and_run_list_commands() -> None:
    body = _sub20("20.7")
    assert body, "RUNBOOK 20.7 does not exist"
    for phrase in (
        "scripts/export_soak_evidence.py",
        "--source pg",
        "--publish",
        "scripts/export_soak_evidence.py publish",
        "gh api repos/<owner>/<repo>/actions/workflows/paper_freeze_check.yml/runs --paginate",
        "gh run download",
        "registry-diff-",
        "scripts/evaluate_trial_soak.py",
        "never a source of truth",
        "Actions cache",
        "L-01",
    ):
        assert phrase in body, f"20.7 lacks: {phrase}"
    for path in ("scripts/export_soak_evidence.py", "scripts/evaluate_trial_soak.py"):
        assert (REPO_ROOT / path).is_file(), path


def test_20_7_export_and_publish_commands_use_flags_the_exporter_accepts() -> None:
    from scripts import export_soak_evidence as export

    seen_export = seen_publish = False
    for argv in _commands_20_7():
        if "scripts/export_soak_evidence.py" not in argv:
            continue
        tokens = ["x" if t.startswith("<") and t.endswith(">") else t for t in argv]
        rest = tokens[tokens.index("scripts/export_soak_evidence.py") + 1 :]
        if rest[:1] == ["publish"]:
            export._publish_parser().parse_args(rest[1:])
            seen_publish = True
        else:
            args = export._parser().parse_args(rest)
            assert args.source == "pg"
            seen_export = True
    assert seen_export and seen_publish, "20.7 must show both the export and the publish command"


def test_20_7_states_the_recorded_cron_reader_crypt_layer_and_loss_window() -> None:
    from tests.test_paper_freeze_workflow_pin_source import record

    body = _sub20("20.7")
    cron = record("16-DEC-Q-Q.md")["cron"]
    o01 = record("16-DEC-O-01.md")
    assert f"`{cron}`" in body, "the recorded cron is stated"
    for phrase in ("G15", "REV-18", "unproven", "EVIDENCE_GAP"):
        assert phrase in body, f"20.7 lacks: {phrase}"
    assert o01["reader_access"].split(" (")[0] in body, "the recorded reader is stated"
    assert "outside the backup crypt remote" in body, "the crypt layer is stated"
    assert "not ciphertext" in body, "no passphrase is needed to read it"
    assert o01["write_timing"].split(",")[0] in body, "the recorded write timing is stated"
    assert "loss window" in body and "hourly" in body and "at most" in body


def test_20_7_names_the_fixed_evidence_configuration_and_no_free_form_destination() -> None:
    from src.ops import evidence_remote as ev

    body = _sub20("20.7")
    for name in ev.EVIDENCE_VARIABLES:
        assert f"`{name}`" in body, f"20.7 lacks the name {name}"
    for phrase in ("deploy/evidence.env.example", ev.EVIDENCE_REMOTE, "no crypt layer"):
        assert phrase in body, f"20.7 lacks: {phrase}"
    assert "<remote:bucket/prefix>" not in body and "--destination" not in body
    assert "not the BACKUP_" in body, "the evidence names are separate from the BACKUP_ names"
    assert "never in argv" in body or "never in an argument" in body
    assert "soak.env" in body, "the shared paper environment file is told not to carry them"


def test_20_7_names_the_committed_pin_path_the_workflow_reads() -> None:
    from tests.test_paper_freeze_workflow_pin_source import COMMITTED_PIN_PATH

    assert COMMITTED_PIN_PATH in _sub20("20.7")


# ----- 16-55 Task 4: restart policy, the pin sequence, the soak backup unit, the drill -------

DRILL_HEADING = "20.8 Restart drill before the pin"
PIN_RUN = "deploy/compose-soak.sh --profile paper-pin run --rm paper-pin"
PAPER_UP = "deploy/compose-soak.sh --profile paper up -d --no-build paper"


def test_20_1_states_the_restart_policy_the_hold_and_its_marker() -> None:
    body = _sub20("20.1")
    for phrase in (
        "unless-stopped",
        "decisions/16-DEC-RESTART-POLICY.md",
        "daemon restart",
        "held marker",
        "INSTANCE_LEASE_HELD",
        "runtime-initiated exit 0",
    ):
        assert phrase in body, f"20.1 lacks: {phrase}"
    assert '"on-failure"' not in body and "policy is `on-failure`" not in body


def test_20_1_shows_the_pin_sequence_with_the_service_started_at_once() -> None:
    body = _sub20("20.1")
    fenced = _fenced_lines(body)
    pin = next((i for i, ln in enumerate(fenced) if PIN_RUN in ln), None)
    up = next((i for i, ln in enumerate(fenced) if PAPER_UP in ln), None)
    assert pin is not None and up is not None, "20.1 lacks the pin or the start command"
    assert up == pin + 1, "nothing may stand between the pin and the service start"
    for phrase in (
        "decisions/16-DEC-PIN-COMMAND.md",
        "exit 0",
        "next operational step",
        "900",
        "16-DEC-O-07",
    ):
        assert phrase in body, f"20.1 lacks: {phrase}"


def test_20_2_says_what_a_reboot_a_daemon_restart_and_a_requested_stop_do() -> None:
    body = _sub20("20.2")
    for phrase in (
        "host reboot",
        "Docker daemon restart",
        "comes back by itself",
        "deploy/compose-soak.sh stop paper",
        "stays stopped",
    ):
        assert phrase in body, f"20.2 lacks: {phrase}"


def test_20_5_gives_the_soak_project_its_own_backup_unit_and_bucket() -> None:
    body = _sub20("20.5")
    for phrase in (
        "trading-soak-backup.timer",
        "--install-soak-timer",
        "--soak-env-file",
        "its own bucket",
        "BACKUP_S3_BUCKET",
        "trading-backup",
        "--init-remote",
        "COMPOSE_PROJECT_NAME=trading-soak",
    ):
        assert phrase in body, f"20.5 lacks: {phrase}"
    assert (REPO_ROOT / "deploy" / "systemd" / "trading-soak-backup.service").is_file()


def test_the_restart_drill_lists_the_five_paths_with_commands_and_outcomes() -> None:
    body = _sub20("20.8")
    assert re.search(rf"^### {re.escape(DRILL_HEADING)}$", _section20(), re.M)
    fenced = "\n".join(_fenced_lines(body))
    for command in (
        "deploy/compose-soak.sh --profile paper up -d --no-build",
        "sudo systemctl restart docker",
        "sudo reboot",
        "docker inspect --format '{{.State.Pid}}'",
        "sudo kill -KILL",
        "deploy/compose-soak.sh stop paper",
    ):
        assert command in fenced, f"the drill lacks the command: {command}"
    for path in (
        "refused start",
        "Docker daemon restart",
        "host reboot",
        "process crash",
        "requested stop",
    ):
        assert path in body, f"the drill lacks the path: {path}"
    for phrase in (
        "NO_PINNED_EPOCH",
        "unhealthy",
        "UTC",
        "16-43",
        "must not happen until every path passed",
        "blocker",
    ):
        assert phrase in body, f"the drill lacks: {phrase}"
    assert "down -v" not in fenced and "--volumes" not in fenced
