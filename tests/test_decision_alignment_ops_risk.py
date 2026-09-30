"""Tests for the operations and risk document gate module (Phase 11, plan 11-04).

Positive tests feed the amended real documents; negative tests feed the pre-change text
from commit 679825c (skipped when that commit is not present in a shallow clone) and
inject each forbidden old line into otherwise good text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.decision_alignment import ops_risk

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "679825c"

SEC_OPS = "docs/operations/SECURITY_AND_OPERATIONS.md"
RUNBOOK = "docs/operations/RUNBOOK.md"
RISK = "docs/trading/RISK_MANAGEMENT.md"
DATA_MODEL = "docs/data/DATA_MODEL.md"
CONFIGURATION = "docs/configuration/CONFIGURATION.md"
ALERTS = "docs/trading/SIGNAL_AND_ALERTS.md"


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _old(rel: str) -> str:
    """Pre-change text of a document from the baseline commit."""
    proc = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{rel}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"baseline commit {BASELINE_COMMIT} unavailable")
    return proc.stdout


# --------------------------------------------------------------------------- Task 1


def test_or01_or02_or03_pass_on_real_docs() -> None:
    gates = {name: ok for name, ok, _ in ops_risk.run()}
    assert gates["OR-01"] is True
    assert gates["OR-02"] is True
    assert gates["OR-03"] is True


def test_run_returns_named_triples() -> None:
    for name, ok, detail in ops_risk.run():
        assert name.startswith("OR-")
        assert isinstance(ok, bool)
        assert isinstance(detail, str)


def test_safe_mode_sec_ops_positive() -> None:
    name, ok, detail = ops_risk.check_safe_mode_sec_ops(_read(SEC_OPS))
    assert ok, detail
    assert name.startswith("OR-01")


def test_safe_mode_runbook_positive() -> None:
    name, ok, detail = ops_risk.check_safe_mode_runbook(_read(RUNBOOK))
    assert ok, detail
    assert name.startswith("OR-01")


def test_secrets_positive() -> None:
    _, ok, detail = ops_risk.check_secrets(_read(SEC_OPS))
    assert ok, detail


def test_webhook_pointer_positive() -> None:
    _, ok, detail = ops_risk.check_webhook_pointer(_read(SEC_OPS))
    assert ok, detail


@pytest.mark.parametrize(
    ("func", "rel"),
    [
        ("check_safe_mode_sec_ops", SEC_OPS),
        ("check_safe_mode_runbook", RUNBOOK),
        ("check_secrets", SEC_OPS),
        ("check_webhook_pointer", SEC_OPS),
    ],
)
def test_pre_change_text_fails(func: str, rel: str) -> None:
    _, ok, _ = getattr(ops_risk, func)(_old(rel))
    assert ok is False


def test_sec_ops_old_ban_line_fails_even_with_good_text() -> None:
    text = _read(SEC_OPS) + "\n- no new live order placement;\n"
    _, ok, detail = ops_risk.check_safe_mode_sec_ops(text)
    assert ok is False
    assert "forbidden" in detail


def test_sec_ops_missing_phrase_fails() -> None:
    text = _read(SEC_OPS).replace("never wider", "sometimes wider")
    _, ok, detail = ops_risk.check_safe_mode_sec_ops(text)
    assert ok is False
    assert "never wider" in detail


@pytest.mark.parametrize(
    "old_line",
    [
        "2. Block new live orders.",
        "NO NEW ORDERS",
        "→ block new orders",
    ],
)
def test_runbook_old_lines_fail_even_with_good_text(old_line: str) -> None:
    text = _read(RUNBOOK) + "\n" + old_line + "\n"
    _, ok, detail = ops_risk.check_safe_mode_runbook(text)
    assert ok is False
    assert "forbidden" in detail


def test_runbook_new_entry_line_is_not_mistaken_for_old_line() -> None:
    text = _read(RUNBOOK)
    assert "NO NEW ENTRY ORDERS" in text
    _, ok, detail = ops_risk.check_safe_mode_runbook(text)
    assert ok, detail


def test_old_encrypt_line_fails_even_with_good_text() -> None:
    text = _read(SEC_OPS) + "\n- Encrypt secrets at rest.\n"
    _, ok, detail = ops_risk.check_secrets(text)
    assert ok is False
    assert "forbidden" in detail


def test_webhook_hmac_claim_fails() -> None:
    text = _read(SEC_OPS) + "\n- Webhook endpoints must verify the HMAC signature.\n"
    _, ok, detail = ops_risk.check_webhook_pointer(text)
    assert ok is False
    assert "signature" in detail


def test_normalisation_strips_emphasis_backticks_and_whitespace() -> None:
    assert ops_risk.normalise("**A**   `b`\n c") == "A b c"
