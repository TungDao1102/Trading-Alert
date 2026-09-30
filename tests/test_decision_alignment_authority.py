"""Tests for the authority documents gate module (Phase 11, plan 11-06).

Positive tests feed the amended real documents; negative tests feed the pre-change text
from commit 679825c (skipped when that commit is not present in a shallow clone) and
inject drift into otherwise good text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.decision_alignment import authority

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "679825c"

STACK = ".planning/research/STACK.md"
PROJECT = ".planning/PROJECT.md"
AGENTS = "AGENTS.md"
TRADINGVIEW = "docs/integration/TRADINGVIEW.md"
RISK = "docs/trading/RISK_MANAGEMENT.md"
PROTOCOL = "docs/research/RESEARCH_PROTOCOL.md"


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


def test_au01_au02_au03_pass_on_real_repository() -> None:
    gates = {name: (ok, detail) for name, ok, detail in authority.run()}
    for name in ("AU-01", "AU-02", "AU-03"):
        assert gates[name][0], f"{name}: {gates[name][1]}"


def test_run_returns_named_triples() -> None:
    for name, ok, detail in authority.run():
        assert name.startswith("AU-")
        assert isinstance(ok, bool)
        assert isinstance(detail, str)


def test_au01_positive_on_amended_files() -> None:
    files = {STACK: _read(STACK), AGENTS: _read(AGENTS), PROJECT: _read(PROJECT)}
    assert authority.check_no_hmac_claim(files)[1]


@pytest.mark.parametrize("rel", [STACK, AGENTS])
def test_au01_fails_on_pre_change_text(rel: str) -> None:
    ok, detail = authority.check_no_hmac_claim({rel: _old(rel)})[1:]
    assert not ok
    assert rel in detail


def test_au01_fails_when_claim_is_wrapped_in_emphasis() -> None:
    text = "TradingView webhooks (**HMAC-checked**)"
    assert not authority.check_no_hmac_claim({"x.md": text})[1]


def test_au01_allows_the_word_hmac_alone() -> None:
    text = "TradingView cannot sign requests, so HMAC verification is not available."
    assert authority.check_no_hmac_claim({"x.md": text})[1]


def test_au02_positive_on_amended_tradingview() -> None:
    ok, detail = authority.check_tradingview_scheme(_read(TRADINGVIEW))[1:]
    assert ok, detail


def test_au02_fails_on_pre_change_tradingview() -> None:
    ok, detail = authority.check_tradingview_scheme(_old(TRADINGVIEW))[1:]
    assert not ok
    assert "cannot sign" in detail


@pytest.mark.parametrize("phrase", authority.TRADINGVIEW_PHRASES)
def test_au02_fails_when_a_required_phrase_is_removed(phrase: str) -> None:
    text = _read(TRADINGVIEW)
    assert phrase in authority.normalise(authority._section(text, 5))
    stripped = authority.normalise(text).replace(phrase, "REDACTED")
    section = "## 5. Webhook security\n\n" + stripped + "\n"
    ok, detail = authority.check_tradingview_scheme(section)[1:]
    assert not ok
    assert phrase in detail


def test_au02_ignores_phrases_outside_section_5() -> None:
    text = "## 1. Role\n\ncannot sign secret path segment\n\n## 5. Webhook security\n\nnothing\n"
    assert not authority.check_tradingview_scheme(text)[1]


def test_au03_positive_fastapi_row_equals_source() -> None:
    ok, detail = authority.check_generated_row(
        _read(STACK), _read(AGENTS), authority.FASTAPI_ROW_PREFIX
    )[1:]
    assert ok, detail


def test_au03_fails_when_generated_row_drifts_from_source() -> None:
    stack = _read(STACK)
    agents = _read(AGENTS).replace("secret URL path", "secret URL segment")
    assert agents != _read(AGENTS)
    ok, detail = authority.check_generated_row(stack, agents, authority.FASTAPI_ROW_PREFIX)[1:]
    assert not ok
    assert "differs" in detail


def test_au03_fails_on_pre_change_generated_block_against_amended_source() -> None:
    ok = authority.check_generated_row(_read(STACK), _old(AGENTS), authority.FASTAPI_ROW_PREFIX)[1]
    assert not ok


def test_au03_fails_when_a_side_has_no_row() -> None:
    assert not authority.check_generated_row("", "| FastAPI | x |", "| FastAPI |")[1]
    assert not authority.check_generated_row("| FastAPI | x |", "", "| FastAPI |")[1]


def test_au03_ignores_line_endings() -> None:
    row = "| FastAPI | a | b | c |"
    assert authority.check_generated_row(row + "\r\n", row + "\n", "| FastAPI |")[1]


# --------------------------------------------------------------------------- Task 2


def test_au04_au05_au06_pass_on_real_repository() -> None:
    gates = {name: (ok, detail) for name, ok, detail in authority.run()}
    assert len(gates) == 6
    for name in ("AU-04", "AU-05", "AU-06"):
        assert gates[name][0], f"{name}: {gates[name][1]}"


def test_au04_positive_on_all_four_locations() -> None:
    ok, detail = authority.check_quantization_agreement(
        _read(RISK), _read(PROTOCOL), _read(PROJECT), _read(AGENTS)
    )[1:]
    assert ok, detail


@pytest.mark.parametrize(
    ("swap", "label"),
    [
        (RISK, "RISK_MANAGEMENT"),
        (PROTOCOL, "RESEARCH_PROTOCOL"),
        (PROJECT, "PROJECT"),
        (AGENTS, "AGENTS"),
    ],
)
def test_au04_fails_when_one_location_is_pre_change(swap: str, label: str) -> None:
    texts = {
        RISK: _read(RISK),
        PROTOCOL: _read(PROTOCOL),
        PROJECT: _read(PROJECT),
        AGENTS: _read(AGENTS),
    }
    texts[swap] = _old(swap)
    ok, detail = authority.check_quantization_agreement(
        texts[RISK], texts[PROTOCOL], texts[PROJECT], texts[AGENTS]
    )[1:]
    assert not ok
    assert label in detail


def test_au04_fails_when_order_is_swapped() -> None:
    swapped = (
        "- **Quantization**: floor to stepSize -> reject below min notional -> "
        "reject below min quantity -> reject below minimum_risk_utilization_after_rounding"
    )
    assert not authority.check_quantization_order(swapped, "x")[1]


def test_au04_fails_when_utilization_check_comes_first() -> None:
    text = "floor to stepSize, minimum_risk_utilization_after_rounding, min quantity, min notional"
    assert not authority.check_quantization_order(text, "x")[1]


def test_au04_accepts_minimum_spelling() -> None:
    text = "stepSize, minimum quantity, minimum notional, minimum_risk_utilization_after_rounding"
    assert authority.check_quantization_order(text, "x")[1]


def test_au04_fails_on_empty_region() -> None:
    assert not authority.check_quantization_order("", "x")[1]


def test_au05_positive_bullet_equals_source() -> None:
    ok, detail = authority.check_generated_row(
        _read(PROJECT), _read(AGENTS), authority.QUANTIZATION_BULLET_PREFIX, "AU-05"
    )[1:]
    assert ok, detail


def test_au05_fails_when_agents_bullet_drifts() -> None:
    project = _read(PROJECT)
    agents = _read(AGENTS).replace("NO_TRADE preferred over round-up", "NO_TRADE")
    assert agents != _read(AGENTS)
    result = authority.check_generated_row(
        project, agents, authority.QUANTIZATION_BULLET_PREFIX, "AU-05"
    )
    assert result[0] == "AU-05"
    assert not result[1]


def test_au05_fails_on_pre_change_bullets_against_amended_source() -> None:
    assert not authority.check_generated_row(
        _read(PROJECT), _old(AGENTS), authority.QUANTIZATION_BULLET_PREFIX, "AU-05"
    )[1]


def test_au06_positive_on_amended_files() -> None:
    files = {AGENTS: _read(AGENTS), PROJECT: _read(PROJECT)}
    assert authority.check_no_old_order(files)[1]


@pytest.mark.parametrize("rel", [PROJECT, AGENTS])
def test_au06_fails_on_pre_change_text(rel: str) -> None:
    ok, detail = authority.check_no_old_order({rel: _old(rel)})[1:]
    assert not ok
    assert rel in detail


def test_au06_detects_old_phrase_with_ascii_arrow_and_wrapping() -> None:
    text = "realized-risk check (60% baseline)\n -> min-qty/notional reject"
    assert not authority.check_no_old_order({"x.md": text})[1]


def test_canonical_order_line_and_protocol_block_are_extracted() -> None:
    assert "stepSize" in authority.canonical_order_line(_read(RISK))
    assert authority.canonical_order_line("no label here") == ""
    block = authority.protocol_quantization_block(_read(PROTOCOL))
    assert "stepSize" in block
    assert "## " not in block
    assert authority.protocol_quantization_block("nothing") == ""
