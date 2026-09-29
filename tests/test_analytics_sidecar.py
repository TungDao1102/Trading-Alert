"""JSON sidecar, digest verification, file-name stem and Telegram pointer tests.

Phase 10, plan 10-11, Task 3 (D-04, GOV-01, JRN-01). RED first: authored before
`src/analytics/render_sidecar.py` exists. The sidecar is the machine-readable twin of the
Markdown report: sorted-key compact JSON, Decimals as strings, UTC ISO datetimes, the report
digest and the SHA-256 of the exact Markdown bytes; `verify_render` recomputes both.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType

import pytest
from src.analytics.render import render_markdown, render_telegram_pointer, report_file_stem
from src.analytics.render_sidecar import (
    SIDECAR_SCHEMA_VERSION,
    build_sidecar,
    markdown_sha256,
    sidecar_text,
    to_plain,
    verify_render,
)
from src.analytics.types import EvidenceKind

from tests.test_analytics_render import (
    ABSOLUTE_PATHS,
    ALLOWED_MARKDOWN_PHRASES,
    ALLOWED_SECRET_LIKE,
    HOSTNAME_LIKE,
    find_reserved,
    make_report,
    secret_like_hits,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "phase10" / "render_golden"
SIDECAR_GOLDEN = GOLDEN_DIR / "expected.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Color(Enum):
    RED = "red"


@dataclasses.dataclass(frozen=True)
class Inner:
    amount: Decimal
    when: datetime


@dataclasses.dataclass(frozen=True)
class Outer:
    name: str
    color: Color
    inner: Inner
    items: tuple[int, ...]
    lookup: Mapping[str, Decimal]
    flag: bool
    nothing: None


def make_outer() -> Outer:
    return Outer(
        name="x",
        color=Color.RED,
        inner=Inner(
            amount=Decimal("1.50"),
            when=datetime(2027, 4, 1, 7, 0, 0, tzinfo=timezone(timedelta(hours=7))),
        ),
        items=(3, 1, 2),
        lookup=MappingProxyType({"b": Decimal("2"), "a": Decimal("1E+1")}),
        flag=True,
        nothing=None,
    )


def build_pair():  # type: ignore[no-untyped-def]
    report = make_report()
    markdown = render_markdown(report)
    return report, markdown, sidecar_text(build_sidecar(report, markdown))


# --------------------------------------------------------------------------- #
# to_plain
# --------------------------------------------------------------------------- #


def test_to_plain_converts_dataclasses_enums_decimals_datetimes_and_mappings() -> None:
    plain = to_plain(make_outer())
    assert plain == {
        "name": "x",
        "color": "red",
        "inner": {"amount": "1.50", "when": "2027-04-01T00:00:00+00:00"},
        "items": [3, 1, 2],
        "lookup": {"a": "1E+1", "b": "2"},
        "flag": True,
        "nothing": None,
    }
    assert list(plain["lookup"]) == ["a", "b"]  # mapping keys sorted
    assert isinstance(plain["items"], list)  # tuple order preserved as a list


def test_to_plain_rejects_float_set_naive_datetime_bad_keys_and_unknown_types() -> None:
    with pytest.raises(TypeError):
        to_plain({"x": 1.5})
    with pytest.raises(TypeError):
        to_plain({"x": {1, 2}})
    with pytest.raises(TypeError):
        to_plain({"x": frozenset({1})})
    with pytest.raises(ValueError):
        to_plain({"x": datetime(2027, 1, 1)})
    with pytest.raises(TypeError):
        to_plain({1: "non-string key"})
    with pytest.raises(TypeError):
        to_plain({"x": Decimal("NaN")})
    with pytest.raises(TypeError):
        to_plain({"x": Path("a")})


# --------------------------------------------------------------------------- #
# Sidecar payload and text
# --------------------------------------------------------------------------- #


def test_sidecar_payload_fields_digest_and_markdown_hash() -> None:
    report, markdown, _ = build_pair()
    payload = build_sidecar(report, markdown)
    assert SIDECAR_SCHEMA_VERSION == "analytics-sidecar/1"
    assert set(payload) == {
        "schema_version",
        "report_digest",
        "markdown_sha256",
        "as_of_utc",
        "report",
    }
    assert payload["schema_version"] == "analytics-sidecar/1"
    assert payload["report_digest"] == report.digest()
    assert HEX64.match(payload["report_digest"])
    assert payload["markdown_sha256"] == hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    assert markdown_sha256(markdown) == payload["markdown_sha256"]
    assert payload["as_of_utc"] == "2027-04-01T00:00:00+00:00"
    assert payload["report"]["as_of_utc"] == "2027-04-01T00:00:00+00:00"
    assert payload["report"]["schema_version"] == report.schema_version


def test_sidecar_text_is_sorted_compact_ascii_with_one_trailing_lf() -> None:
    report, markdown, text = build_pair()
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "\r" not in text
    body = text[:-1]
    assert "\n" not in body
    assert body.isascii()
    parsed = json.loads(body)
    expected = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert body == expected
    assert body.startswith('{"as_of_utc":')
    assert ", " not in body and ": " not in body
    assert sidecar_text(build_sidecar(report, markdown)) == text  # deterministic
    # Decimals are strings, never JSON numbers; there are no floats anywhere.
    assert not re.search(r"[:\[,]-?\d+\.\d+[,\]}]", body)
    evidence = parsed["report"]["evidence"]
    assert [block["kind"] for block in evidence] == ["BACKTEST", "PAPER", "LIVE"]
    assert evidence[0]["core"]["mean_r"]["value"] == "0.8"
    assert isinstance(evidence[0]["core"]["n"], int)


def test_sidecar_carries_full_length_hashes_while_markdown_shows_prefixes() -> None:
    report, markdown, text = build_pair()
    experiment_id = report.provenance.experiments[0].experiment_id
    assert len(experiment_id) == 64
    assert experiment_id in text
    assert experiment_id not in markdown


# --------------------------------------------------------------------------- #
# Digest verification
# --------------------------------------------------------------------------- #


def test_verify_render_accepts_the_consistent_pair() -> None:
    report, markdown, text = build_pair()
    assert verify_render(markdown, text) == []
    assert verify_render(markdown, text, report=report) == []
    assert f"| Report digest | sha256:{report.digest()} |" in markdown


def test_verify_render_detects_one_byte_markdown_tampering() -> None:
    _, markdown, text = build_pair()
    at = markdown.index("Kill Gate")
    tampered = markdown[:at] + "Kill gate" + markdown[at + len("Kill Gate") :]
    assert tampered != markdown and len(tampered) == len(markdown)
    problems = verify_render(tampered, text)
    assert problems != []
    assert any("markdown_sha256" in problem for problem in problems)


def test_verify_render_detects_sidecar_digest_and_hash_tampering() -> None:
    report, markdown, text = build_pair()
    payload = json.loads(text)
    payload["report_digest"] = "0" * 64
    bad_digest = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    problems = verify_render(markdown, bad_digest)
    assert problems != [] and any("report_digest" in problem for problem in problems)
    payload = json.loads(text)
    payload["markdown_sha256"] = "f" * 64
    bad_hash = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    assert any("markdown_sha256" in problem for problem in verify_render(markdown, bad_hash))
    # A digest edited on both sides still fails the recomputation against the report.
    payload = json.loads(text)
    payload["report_digest"] = "1" * 64
    forged_header = markdown.replace(report.digest(), "1" * 64)
    payload["markdown_sha256"] = hashlib.sha256(forged_header.encode("utf-8")).hexdigest()
    forged = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    assert verify_render(forged_header, forged) == []  # self-consistent pair
    assert verify_render(forged_header, forged, report=report) != []


def test_verify_render_reports_unreadable_or_incomplete_sidecars() -> None:
    _, markdown, text = build_pair()
    assert verify_render(markdown, "not json") != []
    assert verify_render(markdown, "[]\n") != []
    payload = json.loads(text)
    del payload["markdown_sha256"]
    assert verify_render(markdown, json.dumps(payload)) != []
    payload = json.loads(text)
    payload["schema_version"] = "analytics-sidecar/0"
    assert any("schema_version" in p for p in verify_render(markdown, json.dumps(payload)))


# --------------------------------------------------------------------------- #
# File-name stem and Telegram pointer
# --------------------------------------------------------------------------- #


def test_report_file_stem_format_and_pinned_value() -> None:
    report = make_report()
    stem = report_file_stem(report)
    assert stem == "journal-depth-20270401T000000Z-" + report.digest()[:12]
    assert re.fullmatch(r"journal-depth-\d{8}T\d{6}Z-[0-9a-f]{12}", stem)
    assert stem == "journal-depth-20270401T000000Z-PINNED_DIGEST12"


def test_telegram_pointer_is_the_exact_plain_text_and_carries_no_decision_surface() -> None:
    report = make_report()
    name = report_file_stem(report) + ".md"
    text = render_telegram_pointer(report, name)
    assert text == (
        "Journal depth report ready. Kill gate: INSUFFICIENT_EDGE. "
        f"Digest {report.digest()[:12]}. File: {name}. "
        "Open the report to read it; this message is not a decision or approval.\n"
        "Display: Asia/Ho_Chi_Minh (UTC internally)"
    )
    lowered = text.lower()
    for word in ("button", "callback", "approve", "skip", "reply_markup", "http"):
        assert word not in lowered
    assert "\r" not in text
    hostile = render_telegram_pointer(report, "a\nb\r\nc.md")
    assert hostile.count("\n") == 1
    assert "File: a b  c.md." in hostile


def test_no_telegram_send_is_wired_into_the_renderer_modules() -> None:
    for name in ("render.py", "render_sidecar.py", "render_metrics.py"):
        source = (REPO_ROOT / "src" / "analytics" / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any("telegram" in module or "adapters" in module for module in modules), name
        assert "reply_markup" not in source and "send_message" not in source, name


# --------------------------------------------------------------------------- #
# Governance scans and goldens
# --------------------------------------------------------------------------- #


def string_values(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [item for child in node for item in string_values(child)]
    if isinstance(node, dict):
        return [item for child in node.values() for item in string_values(child)]
    return []


def test_governance_scans_over_markdown_and_sidecar() -> None:
    _, markdown, text = build_pair()
    for name, document in (("markdown", markdown), ("sidecar", text)):
        assert "\r" not in document, name
        for pattern in ABSOLUTE_PATHS:
            assert pattern.search(document) is None, (name, pattern.pattern)
        assert HOSTNAME_LIKE.search(document) is None, name
    scanned = markdown
    for phrase in ALLOWED_MARKDOWN_PHRASES:
        scanned = scanned.replace(phrase, "")
    assert secret_like_hits(scanned) == set()
    assert all(phrase in markdown for phrase in ALLOWED_MARKDOWN_PHRASES)  # not stale
    assert secret_like_hits(text) <= ALLOWED_SECRET_LIKE
    assert secret_like_hits(text) == ALLOWED_SECRET_LIKE  # the allow-list is not stale
    assert find_reserved("\n".join(string_values(json.loads(text)))) == []
    assert find_reserved("a winner is best") != []  # detector self-check


def test_scan_helpers_detect_planted_violations() -> None:
    assert secret_like_hits('{"api_secret":"x"}') == {'"api_secret"'}
    assert ABSOLUTE_PATHS[0].search("C:\\Users\\admin") is not None
    assert ABSOLUTE_PATHS[1].search("see /home/user/x") is not None
    assert HOSTNAME_LIKE.search("host build-01.example.com") is not None
    assert HOSTNAME_LIKE.search("adapter.rejected_rows") is None


def test_sidecar_golden_is_byte_exact() -> None:
    _, markdown, text = build_pair()
    expected = SIDECAR_GOLDEN.read_bytes()
    assert text.encode("utf-8") == expected
    assert b"\r" not in expected
    assert expected.endswith(b"\n") and not expected.endswith(b"\n\n")
    assert not expected.startswith(bytes([0xEF, 0xBB, 0xBF]))
    parsed = json.loads(expected)
    assert parsed["markdown_sha256"] == hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    assert parsed["report_digest"] == make_report().digest()


def test_evidence_kinds_stay_separate_in_the_sidecar() -> None:
    parsed = json.loads(build_pair()[2])
    kinds = [block["kind"] for block in parsed["report"]["evidence"]]
    assert kinds == [kind.value for kind in EvidenceKind]
