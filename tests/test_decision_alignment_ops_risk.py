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


# --------------------------------------------------------------------------- Task 2


def test_or04_to_or08_pass_on_real_docs() -> None:
    gates = {name: ok for name, ok, _ in ops_risk.run()}
    for name in ("OR-04", "OR-05", "OR-06", "OR-07", "OR-08"):
        assert gates[name] is True, name


@pytest.mark.parametrize(
    "func",
    [
        "check_daily_loss",
        "check_margin",
        "check_quantization",
        "check_snapshot",
        "check_sl_and_compensation",
    ],
)
def test_risk_gates_positive_and_pre_change_negative(func: str) -> None:
    check = getattr(ops_risk, func)
    _, ok, detail = check(_read(RISK))
    assert ok, detail
    _, old_ok, _ = check(_old(RISK))
    assert old_ok is False


def test_quantization_synonym_fails() -> None:
    text = _read(RISK) + "\nReject with QUANTIZATION_REJECT.\n"
    _, ok, detail = ops_risk.check_quantization(text)
    assert ok is False
    assert "QUANTIZATION_REJECT" in detail


def test_quantization_order_swap_fails() -> None:
    text = _read(RISK)
    swapped = text.replace("min quantity", "TMPQ").replace("min notional", "min quantity")
    swapped = swapped.replace("TMPQ", "min notional")
    _, ok, detail = ops_risk.check_quantization(swapped)
    assert ok is False
    assert "order" in detail


def test_quantization_canonical_line_is_labelled() -> None:
    assert "Canonical order (D031):" in ops_risk.normalise(_read(RISK))


def test_no_numeric_liquidation_buffer() -> None:
    text = ops_risk.normalise(_read(RISK)).lower()
    assert "registry parameter" in text
    assert "buffer of" not in text
    assert "buffer =" not in text


def test_daily_loss_missing_phrase_fails() -> None:
    text = _read(RISK).replace("07:00 Asia/Ho_Chi_Minh", "07:00 local")
    _, ok, detail = ops_risk.check_daily_loss(text)
    assert ok is False
    assert "07:00 Asia/Ho_Chi_Minh" in detail


def test_margin_missing_resting_entry_fails() -> None:
    text = _read(RISK).replace("resting entry", "pending")
    _, ok, detail = ops_risk.check_margin(text)
    assert ok is False
    assert "resting entry" in detail


def test_snapshot_missing_field_fails() -> None:
    text = _read(RISK).replace("equity_used", "equity")
    _, ok, detail = ops_risk.check_snapshot(text)
    assert ok is False
    assert "equity_used" in detail


def test_sl_and_compensation_missing_fails() -> None:
    text = _read(RISK).replace("averaging down", "adding")
    _, ok, detail = ops_risk.check_sl_and_compensation(text)
    assert ok is False
    assert "averaging down" in detail


def test_hard_coded_liquidation_buffer_fails() -> None:
    text = _read(RISK).replace(
        "the buffer is a registry parameter", "the buffer is 1.5x SL distance"
    )
    _, ok, detail = ops_risk.check_margin(text)
    assert ok is False
    assert "forbidden" in detail
