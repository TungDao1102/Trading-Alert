"""JSON sidecar for the offline report and its digest verification (Phase 10, plan 10-11, D-04).

The sidecar is the machine-readable twin of the Markdown report: the whole report tree as
plain data, the report digest, and the SHA-256 of the exact Markdown bytes. The Markdown
cannot hold its own file hash, so the sidecar carries `markdown_sha256` while the Markdown
header carries `report_digest`; `verify_render` recomputes both and lists every mismatch.

Scalar rules are the project canonical ones (`src.domain.canonical.canonical_scalars`):
Decimal becomes a string with full precision, a datetime becomes UTC ISO text, an Enum becomes
its value, and a float or a set is refused. Dataclasses become dicts of their fields and
mappings become dicts; keys are sorted when the JSON text is dumped. Stored values are UTC
only and hashes are full length (the Markdown shows 12-hex prefixes).

Pure: no clock, no filesystem, no network, no ambient state.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from src.analytics.killgate_guard import NOT_CONCLUDED, RULE_REF, not_concluded_line
from src.analytics.report import JournalDepthReport
from src.domain.canonical import canonical_scalars

__all__ = [
    "SIDECAR_SCHEMA_VERSION",
    "build_sidecar",
    "markdown_sha256",
    "sidecar_text",
    "to_plain",
    "verify_render",
]

SIDECAR_SCHEMA_VERSION = "analytics-sidecar/1"

_REQUIRED_FIELDS = ("schema_version", "report_digest", "markdown_sha256", "as_of_utc", "report")
_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64


def _structural(value: Any) -> Any:
    """Dataclasses and mappings become dicts, sequences become lists; scalars pass through."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # A dataclass may name fields that are left out while they are zero (plan 16-36): the
        # SHADOW counters of a report without SHADOW evidence keep its sidecar byte for byte.
        omit_when_zero: tuple[str, ...] = getattr(type(value), "SIDECAR_OMIT_WHEN_ZERO", ())
        return {
            item.name: _structural(getattr(value, item.name))
            for item in dataclasses.fields(value)
            if not (item.name in omit_when_zero and getattr(value, item.name) == 0)
        }
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"mapping keys must be str, got {type(key).__name__}")
            converted[key] = _structural(child)
        return converted
    if isinstance(value, (list, tuple)):
        return [_structural(child) for child in value]
    if isinstance(value, Decimal) and not value.is_finite():
        raise TypeError("non-finite Decimal cannot be represented in the sidecar")
    return value


def _check_plain(value: Any) -> None:
    """Fail closed on anything that is not JSON-plain after canonical normalization."""
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, list):
        for child in value:
            _check_plain(child)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"mapping keys must be str, got {type(key).__name__}")
            _check_plain(child)
        return
    raise TypeError(f"{type(value).__name__} is not representable in the sidecar")


def to_plain(obj: Any) -> Any:
    """Convert a frozen report tree to JSON-plain data under the canonical scalar policy."""
    plain = canonical_scalars(_structural(obj))
    _check_plain(plain)
    return plain


def markdown_sha256(markdown_text: str) -> str:
    """SHA-256 hex digest of the exact UTF-8 bytes of the Markdown document."""
    return hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()


def _report_plain(report: JournalDepthReport, blocked_by: tuple[str, ...]) -> Any:
    """The report tree as plain data; with `blocked_by` the evaluated state is withheld."""
    plain = to_plain(report)
    if blocked_by:
        plain["kill_gate"]["verdict"]["state"] = NOT_CONCLUDED
    return plain


def build_sidecar(
    report: JournalDepthReport, markdown_text: str, blocked_by: tuple[str, ...] = ()
) -> dict[str, Any]:
    """The sidecar payload for one report and the Markdown rendered from it.

    With `blocked_by` (D061 F) the kill-gate state in the report body is replaced by
    NOT CONCLUDED and a `kill_gate_withheld` object names the blocking review items.
    """
    payload: dict[str, Any] = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "report_digest": report.digest(),
        "markdown_sha256": markdown_sha256(markdown_text),
        "as_of_utc": to_plain(report.as_of_utc),
        "report": _report_plain(report, blocked_by),
    }
    if blocked_by:
        payload["kill_gate_withheld"] = {"blocked_by": list(blocked_by), "rule_ref": RULE_REF}
    return payload


def sidecar_text(payload: Mapping[str, Any]) -> str:
    """Sorted-key compact ASCII JSON plus one trailing line feed (byte-stable)."""
    return (
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(char in _HEX_DIGITS for char in value)
    )


def verify_render(
    markdown_text: str,
    sidecar_value: str,
    *,
    report: JournalDepthReport | None = None,
    blocked_by: tuple[str, ...] = (),
) -> list[str]:
    """Problems found in a Markdown/sidecar pair; an empty list means they are consistent.

    Always recomputes the SHA-256 of the Markdown bytes and checks that the sidecar's report
    digest is the one in the Markdown header. When the report itself is supplied it also
    recomputes the report digest and compares the sidecar's report body with the tree.
    Problem strings are fixed vocabulary; parser error text is never echoed.
    """
    try:
        payload = json.loads(sidecar_value)
    except ValueError:
        return ["sidecar is not valid JSON"]
    if not isinstance(payload, dict):
        return ["sidecar is not a JSON object"]
    problems = [
        f"sidecar field missing: {name}" for name in _REQUIRED_FIELDS if name not in payload
    ]
    if problems:
        return problems
    if payload["schema_version"] != SIDECAR_SCHEMA_VERSION:
        problems.append(f"schema_version is not {SIDECAR_SCHEMA_VERSION}")
    if payload["markdown_sha256"] != markdown_sha256(markdown_text):
        problems.append("markdown_sha256 does not match the Markdown bytes")
    digest = payload["report_digest"]
    if not _is_digest(digest):
        problems.append("report_digest is not a 64-character lowercase hex digest")
    elif f"| Report digest | sha256:{digest} |" not in markdown_text.split("\n"):
        problems.append("report_digest is not the digest in the Markdown header")
    if report is not None:
        if digest != report.digest():
            problems.append("report_digest differs from the recomputed report digest")
        if payload["report"] != _report_plain(report, blocked_by):
            problems.append("report body differs from the report tree")
    if blocked_by:
        withheld = payload.get("kill_gate_withheld")
        if not isinstance(withheld, dict) or withheld.get("blocked_by") != list(blocked_by):
            problems.append("kill_gate_withheld does not name the blocking review items")
        if not_concluded_line(blocked_by) not in markdown_text:
            problems.append("the Markdown does not carry the NOT CONCLUDED marker")
    elif "kill_gate_withheld" in payload:
        problems.append("kill_gate_withheld is present without a blocking review item")
    return problems
