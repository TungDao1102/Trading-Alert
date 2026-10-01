"""`.env.example` documents credential names and carries no real value (13.1-04, OPS-06, D-25).

Reuses the Redactor shape rules rather than duplicating the patterns, so a shape added there
is automatically enforced here. Failure messages report line numbers and variable names only,
never a value.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from src.ops.redaction import SHAPE_RULES

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

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
    "OFF_HOST_BACKUP_TARGET",
)


def _lines() -> list[str]:
    return ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()


def _assignments() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in _lines():
        match = _ASSIGNMENT.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _commented_names() -> set[str]:
    return {m.group(1) for line in _lines() if (m := _COMMENTED_ASSIGNMENT.match(line))}


def test_no_live_shaped_or_key_like_values() -> None:
    offenders: list[str] = []
    for number, line in enumerate(_lines(), start=1):
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
    for name, value in _assignments().items():
        if name.startswith(("BINANCE_", "BACKUP_")):
            assert value == "", f"{name} must be an empty assignment in the template"


def test_testnet_credentials_are_empty_active_assignments() -> None:
    assigned = _assignments()
    assert assigned.get("BINANCE_TESTNET_API_KEY") == ""
    assert assigned.get("BINANCE_TESTNET_API_SECRET") == ""


def test_live_credentials_appear_only_on_comment_lines() -> None:
    assigned = _assignments()
    assert not [name for name in assigned if "LIVE" in name and name.startswith("BINANCE_")]
    commented = _commented_names()
    assert "BINANCE_LIVE_API_KEY" in commented
    assert "BINANCE_LIVE_API_SECRET" in commented


def test_paper_and_live_credential_names_differ() -> None:
    names = set(_assignments()) | _commented_names()
    testnet = {n for n in names if n.startswith("BINANCE_TESTNET_")}
    live = {n for n in names if n.startswith("BINANCE_LIVE_")}
    assert testnet and live
    assert not testnet & live
    # No credential name without an environment qualifier (would be ambiguous, OPS-06).
    ambiguous = {n for n in names if n.startswith("BINANCE_") and n not in testnet | live}
    assert not ambiguous, f"unqualified Binance credential names: {sorted(ambiguous)}"


def test_backup_variable_names_present_as_active_assignments() -> None:
    assigned = _assignments()
    for name in BACKUP_NAMES:
        assert name in assigned, f"{name} missing"
    backup_lines = [line for line in _lines() if line.startswith(("BACKUP_S3_", "BACKUP_CRYPT_"))]
    assert len(backup_lines) == 8


def test_crypt_block_explains_obscure_offsite_passphrase_and_loss() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
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
    commented = _commented_names() | {
        line.strip("# ").split()[0] for line in _lines() if line.startswith("# TELEGRAM_")
    }
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_AUTHORIZED_CHAT_ID", "PAPER_DATABASE_URL"):
        assert name in text or name in commented


def test_real_env_file_stays_gitignored() -> None:
    proc = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
