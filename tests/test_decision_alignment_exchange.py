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


# --------------------------------------------------------------------------- Task 2


def test_algo_status_positive() -> None:
    name, ok, detail = exchange.check_algo_status(_read(EXECUTION_SPEC))
    assert ok, detail
    assert name == "EX-02"


def test_algo_status_rejects_pre_change_spec() -> None:
    _, ok, detail = exchange.check_algo_status(_old(EXECUTION_SPEC))
    assert not ok
    assert "FINISHED does not mean filled" in detail


@pytest.mark.parametrize(
    "phrase",
    [p for p in exchange.ALGO_STATUS_PHRASES if p not in ("NEW", "FINISHED")],
)
def test_algo_status_requires_each_phrase(phrase: str) -> None:
    _, ok, detail = exchange.check_algo_status(_drop(_read(EXECUTION_SPEC), phrase))
    assert not ok
    assert phrase in detail


def test_position_mode_citation_positive() -> None:
    name, ok, detail = exchange.check_position_mode_citation(_read(EXECUTION_SPEC))
    assert ok, detail
    assert name == "EX-03"


def test_position_mode_citation_rejects_pre_change_spec() -> None:
    _, ok, detail = exchange.check_position_mode_citation(_old(EXECUTION_SPEC))
    assert not ok
    assert "New-Order" in detail


def test_position_mode_citation_rejects_new_order_link() -> None:
    text = _read(EXECUTION_SPEC).replace("rest-api/Change-Position-Mode", "rest-api/New-Order")
    _, ok, detail = exchange.check_position_mode_citation(text)
    assert not ok
    assert "New-Order" in detail


def test_orphan_reconciler_positive() -> None:
    name, ok, detail = exchange.check_orphan_reconciler(_read(EXECUTION_SPEC))
    assert ok, detail
    assert name == "EX-04"


def test_orphan_reconciler_rejects_pre_change_spec() -> None:
    _, ok, detail = exchange.check_orphan_reconciler(_old(EXECUTION_SPEC))
    assert not ok
    assert "not an orphan" in detail


@pytest.mark.parametrize("phrase", exchange.ORPHAN_PHRASES)
def test_orphan_reconciler_requires_each_phrase(phrase: str) -> None:
    _, ok, detail = exchange.check_orphan_reconciler(_drop(_read(EXECUTION_SPEC), phrase))
    assert not ok
    assert phrase in detail


def test_emergency_controls_positive() -> None:
    name, ok, detail = exchange.check_emergency_controls(_read(EXECUTION_SPEC))
    assert ok, detail
    assert name == "EX-05"


def test_emergency_controls_rejects_pre_change_spec() -> None:
    _, ok, detail = exchange.check_emergency_controls(_old(EXECUTION_SPEC))
    assert not ok
    assert "disable new live orders" in detail


def test_emergency_controls_rejects_reintroduced_wording() -> None:
    text = _read(EXECUTION_SPEC) + "\n- disable new live orders,\n"
    _, ok, detail = exchange.check_emergency_controls(text)
    assert not ok
    assert "forbidden" in detail


def test_source_register_positive() -> None:
    name, ok, detail = exchange.check_source_register(_read(EXECUTION_SPEC), _read(SOURCES))
    assert ok, detail
    assert name == "EX-06"


def test_source_register_rejects_unregistered_url() -> None:
    spec = (
        _read(EXECUTION_SPEC)
        + "\nSee [x](https://developers.binance.com/docs/unregistered-page).\n"
    )
    _, ok, detail = exchange.check_source_register(spec, _read(SOURCES))
    assert not ok
    assert "unregistered-page" in detail


def test_source_register_rejects_row_without_date() -> None:
    sources = _read(SOURCES)
    start = sources.index(exchange.SOURCES_SECTION_TITLE)
    mutated = sources[:start] + sources[start:].replace("| 2026-09-30 |", "| unknown |")
    _, ok, detail = exchange.check_source_register(_read(EXECUTION_SPEC), mutated)
    assert not ok
    assert "cited but not registered" in detail


def test_source_register_rejects_pre_change_register() -> None:
    _, ok, detail = exchange.check_source_register(_read(EXECUTION_SPEC), _old(SOURCES))
    assert not ok


def test_cited_urls_ignores_anchors_and_other_hosts() -> None:
    text = "[a](https://developers.binance.com/docs/x/#frag) https://example.com/y"
    assert exchange.cited_urls(text) == {"https://developers.binance.com/docs/x"}


def test_event_algo_order_update_row_states_method_and_reconfirmation() -> None:
    body = exchange._titled_section(_read(SOURCES), exchange.SOURCES_SECTION_TITLE)
    rows = [
        ln
        for ln in body.splitlines()
        if ln.startswith("| https://") and "/Event-Algo-Order-Update |" in ln
    ]
    assert len(rows) == 1
    normalised = exchange.normalise(rows[0])
    assert "SDK model" in normalised
    assert "official page could not be retrieved" in normalised
    assert "re-confirmation" in normalised
