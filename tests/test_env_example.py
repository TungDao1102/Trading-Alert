"""`.env.example` documents credential names and carries no real value (13.1-04, OPS-06, D-25).

Reuses the Redactor shape rules rather than duplicating the patterns, so a shape added there
is automatically enforced here. Failure messages report line numbers and variable names only,
never a value.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from src.ops.redaction import SHAPE_RULES

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_LIVE_EXAMPLE = REPO_ROOT / ".env.live.example"
ENV_PAPER_EXAMPLE = REPO_ROOT / ".env.paper.example"
ENV_BACKUP_EXAMPLE = REPO_ROOT / ".env.backup.example"
ALL_EXAMPLES = (ENV_EXAMPLE, ENV_LIVE_EXAMPLE, ENV_PAPER_EXAMPLE, ENV_BACKUP_EXAMPLE)

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_COMMENTED_ASSIGNMENT = re.compile(r"^#\s*([A-Z][A-Z0-9_]*)=(.*)$")
_LONG_ALNUM_RUN = re.compile(r"[A-Za-z0-9]{20,}")

BACKUP_NAMES: tuple[str, ...] = (
    "BACKUP_S3_PROVIDER",
    "BACKUP_S3_ENDPOINT",
    "BACKUP_S3_REGION",
    "BACKUP_S3_BUCKET",
    "BACKUP_S3_ACCESS_KEY_ID",
    "BACKUP_S3_SECRET_ACCESS_KEY",
    "BACKUP_CRYPT_PASSWORD",
    "BACKUP_CRYPT_PASSWORD2",
)

EXISTING_NAMES: tuple[str, ...] = (
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "DATABASE_URL",
    "OI_POLL_INTERVAL_SECONDS",
)


def _lines(path: Path = ENV_EXAMPLE) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _assignments(path: Path = ENV_EXAMPLE) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in _lines(path):
        match = _ASSIGNMENT.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _commented_names(path: Path = ENV_EXAMPLE) -> set[str]:
    return {m.group(1) for line in _lines(path) if (m := _COMMENTED_ASSIGNMENT.match(line))}


@pytest.mark.parametrize("path", ALL_EXAMPLES, ids=lambda p: p.name)
def test_no_live_shaped_or_key_like_values(path: Path) -> None:
    offenders: list[str] = []
    for number, line in enumerate(_lines(path), start=1):
        if "change_me" in line:
            continue  # documented placeholder
        text = line
        match = _ASSIGNMENT.match(line) or _COMMENTED_ASSIGNMENT.match(line)
        value = match.group(2) if match else ""
        if any(
            "<" not in found.group(0)  # `<password>` style documentation placeholders
            for pattern, _ in SHAPE_RULES
            for found in pattern.finditer(text)
        ):
            offenders.append(f"line {number}: matches a redaction shape rule")
        if value and _LONG_ALNUM_RUN.search(value):
            offenders.append(f"line {number}: value looks like a key")
    assert not offenders, "; ".join(offenders)


def test_assigned_values_are_empty_or_documented_placeholders() -> None:
    for path in ALL_EXAMPLES:
        for name, value in _assignments(path).items():
            if name.startswith(("BINANCE_", "BACKUP_", "TELEGRAM_")):
                assert value == "", f"{name} must be an empty assignment in {path.name}"


def test_demo_credentials_are_empty_active_assignments_of_the_live_template() -> None:
    """Plan 24-30 (D-29): the Binance names moved out of the shared template to the live one."""
    assigned = _assignments(ENV_LIVE_EXAMPLE)
    assert assigned.get("BINANCE_DEMO_API_KEY") == ""
    assert assigned.get("BINANCE_DEMO_API_SECRET") == ""


def test_the_shared_template_carries_no_binance_or_live_bot_name() -> None:
    """C-8 / WR-06: a BINANCE_ name in the shared file stops the paper service and reaches the
    collector, so the shared template names none of the live-only variables."""
    names = set(_assignments()) | _commented_names()
    assert not {n for n in names if n.startswith("BINANCE_")}
    assert not names & {"TELEGRAM_LIVE_BOT_TOKEN", "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID"}
    assert "LIVE_RUNTIME_MODE" not in names


def test_the_shared_template_does_not_claim_more_than_the_split_delivers() -> None:
    """The old sentence said a paper process can never pick up a live credential; the template
    now states the per-service rule instead (plan 24-30)."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "can never pick up a live credential" not in text
    assert ".env.live" in text
    assert "tests/test_live_compose_env_split.py" in text


def test_no_testnet_credential_name_is_invented() -> None:
    # TESTNET stays NOT_CONFIGURED (O-18-01): neither template carries a BINANCE_TESTNET_ name.
    for path in (ENV_EXAMPLE, ENV_LIVE_EXAMPLE):
        names = set(_assignments(path)) | _commented_names(path)
        assert not {n for n in names if n.startswith("BINANCE_TESTNET_")}


def test_live_credentials_appear_only_on_comment_lines() -> None:
    assigned = _assignments(ENV_LIVE_EXAMPLE)
    assert not [name for name in assigned if "LIVE" in name and name.startswith("BINANCE_")]
    commented = _commented_names(ENV_LIVE_EXAMPLE)
    assert "BINANCE_LIVE_API_KEY" in commented
    assert "BINANCE_LIVE_API_SECRET" in commented


def test_paper_and_live_credential_names_differ() -> None:
    names = set(_assignments(ENV_LIVE_EXAMPLE)) | _commented_names(ENV_LIVE_EXAMPLE)
    demo = {n for n in names if n.startswith("BINANCE_DEMO_")}
    live = {n for n in names if n.startswith("BINANCE_LIVE_")}
    assert demo and live
    assert not demo & live
    # No credential name without an environment qualifier (would be ambiguous, OPS-06).
    ambiguous = {n for n in names if n.startswith("BINANCE_") and n not in demo | live}
    assert not ambiguous, f"unqualified Binance credential names: {sorted(ambiguous)}"


def test_backup_variable_names_present_as_active_assignments_of_the_backup_template() -> None:
    """Plan 24-36 (D-29): the BACKUP_ names moved out of the shared template."""
    assigned = _assignments(ENV_BACKUP_EXAMPLE)
    for name in BACKUP_NAMES:
        assert name in assigned, f"{name} missing"
    backup_lines = [
        line
        for line in _lines(ENV_BACKUP_EXAMPLE)
        if line.startswith(("BACKUP_S3_", "BACKUP_CRYPT_"))
    ]
    assert len(backup_lines) == 8
    assert "OFF_HOST_BACKUP_TARGET" in assigned
    assert "BACKUP_REMOTE" in assigned


def test_the_shared_template_carries_no_backup_or_shadow_telegram_name() -> None:
    names = set(_assignments()) | _commented_names()
    moved = sorted(n for n in names if n.startswith(("BACKUP_", "TELEGRAM_")))
    assert not moved, f"names that belong to a per-service template: {moved}"
    assert "OFF_HOST_BACKUP_TARGET" not in names
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert ".env.paper" in text and ".env.backup" in text


def test_the_paper_template_names_the_shadow_telegram_variables_without_a_value() -> None:
    assigned = _assignments(ENV_PAPER_EXAMPLE)
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_AUTHORIZED_CHAT_ID",
        "TELEGRAM_AUTHORIZED_USER_IDS",
    ):
        assert assigned.get(name) == "", f"{name} must be an empty active assignment"
    names = set(assigned) | _commented_names(ENV_PAPER_EXAMPLE)
    assert not {n for n in names if n.startswith("BINANCE_")}


def test_crypt_block_explains_obscure_offsite_passphrase_and_loss() -> None:
    text = ENV_BACKUP_EXAMPLE.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "rclone obscure" in lowered
    assert "off the vps" in lowered
    assert "unrecoverable" in lowered


def test_image_tag_and_bootstrap_note_present() -> None:
    assert _assignments().get("IMAGE_TAG") == "dev"
    head = "\n".join(_lines()[:15])
    assert "deploy/bootstrap.sh" in head
    assert "0600" in head


def test_existing_variable_names_are_unchanged() -> None:
    assigned = _assignments()
    for name in EXISTING_NAMES:
        assert name in assigned, f"{name} was removed or renamed"
    # the moved names are still documented, in the template of the service that reads them
    paper_text = ENV_PAPER_EXAMPLE.read_text(encoding="utf-8")
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_AUTHORIZED_CHAT_ID"):
        assert name in paper_text, f"{name} missing from .env.paper.example"
    assert "OFF_HOST_BACKUP_TARGET" in _assignments(ENV_BACKUP_EXAMPLE)


def test_the_user_allow_list_variable_is_named_without_a_value() -> None:
    """Phase 23 (D-02): the examples name TELEGRAM_AUTHORIZED_USER_IDS and carry no id."""
    assert _assignments(ENV_PAPER_EXAMPLE).get("TELEGRAM_AUTHORIZED_USER_IDS") == ""
    soak = (REPO_ROOT / "deploy" / "soak.env.example").read_text(encoding="utf-8").splitlines()
    assert "TELEGRAM_AUTHORIZED_USER_IDS=" in soak, "an empty assignment, never a value"


def test_real_env_file_stays_gitignored() -> None:
    proc = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        ".env.prod",
        ".env.live",
        ".env.paper",
        ".env.backup",
        "secrets.prod.env",
        "deploy/id_ed25519",
        "k/key.pem",
    ],
)
def test_env_variants_and_key_files_are_gitignored(name: str) -> None:
    """WR-07: a variant such as .env.live must not be addable with `git add -A`."""
    proc = subprocess.run(
        ["git", "check-ignore", "-q", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"{name} is not gitignored"


@pytest.mark.parametrize(
    "name", [".env.example", ".env.live.example", ".env.paper.example", ".env.backup.example"]
)
def test_the_env_templates_are_not_gitignored(name: str) -> None:
    proc = subprocess.run(
        ["git", "check-ignore", "-q", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
