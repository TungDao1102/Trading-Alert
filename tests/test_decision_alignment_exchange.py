"""Tests for the exchange-facts document gate module (Phase 11, plan 11-05).

Positive tests feed the amended real documents; negative tests feed the pre-change text
from commit 679825c (skipped when that commit is not present in a shallow clone) and
remove or inject each required or forbidden phrase in otherwise good text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.decision_alignment import exchange

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "679825c"

EXECUTION_SPEC = "docs/trading/EXECUTION_SPEC.md"
SOURCES = "docs/SOURCES.md"


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


def _drop(text: str, phrase: str) -> str:
    """Remove every occurrence of ``phrase`` (matched after emphasis and backtick removal)."""
    return text.replace("`", "").replace("**", "").replace(phrase, "")


# --------------------------------------------------------------------------- Task 1


def test_run_returns_named_triples() -> None:
    for name, ok, detail in exchange.run():
        assert name.startswith("EX-")
        assert isinstance(ok, bool)
        assert isinstance(detail, str)


def test_algo_limit_positive() -> None:
    name, ok, detail = exchange.check_algo_limit(_read(EXECUTION_SPEC))
    assert ok, detail
    assert name == "EX-01"


def test_algo_limit_rejects_pre_change_spec() -> None:
    _, ok, detail = exchange.check_algo_limit(_old(EXECUTION_SPEC))
    assert not ok
    assert "200-open-conditional-order limit per symbol" in detail


@pytest.mark.parametrize("phrase", exchange.ALGO_LIMIT_PHRASES)
def test_algo_limit_requires_each_phrase(phrase: str) -> None:
    text = _drop(_read(EXECUTION_SPEC), phrase)
    _, ok, detail = exchange.check_algo_limit(text)
    assert not ok
    assert phrase in detail


def test_algo_limit_rejects_reintroduced_per_symbol_line() -> None:
    text = _read(EXECUTION_SPEC) + "\nA 200-open-conditional-order limit per symbol applies.\n"
    _, ok, detail = exchange.check_algo_limit(text)
    assert not ok
    assert "forbidden" in detail


def test_sources_positive() -> None:
    name, ok, detail = exchange.check_sources(_read(SOURCES))
    assert ok, detail
    assert name == "EX-06a"


def test_sources_rejects_pre_change_register() -> None:
    _, ok, detail = exchange.check_sources(_old(SOURCES))
    assert not ok
    assert "missing section" in detail


@pytest.mark.parametrize("phrase", [exchange.CHANGE_LOG_URL, exchange.FETCH_DATE, "WebFetch"])
def test_sources_requires_url_date_and_method(phrase: str) -> None:
    text = _read(SOURCES)
    body_start = text.index(exchange.SOURCES_SECTION_TITLE)
    mutated = text[:body_start] + text[body_start:].replace(phrase, "REDACTED")
    _, ok, detail = exchange.check_sources(mutated)
    assert not ok
    assert phrase in detail
