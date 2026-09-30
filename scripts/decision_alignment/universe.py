"""Research-universe manifest gate (Phase 11, plan 11-03; D039, D-09).

Validates and hashes the point-in-time research universe manifest at
``docs/research/universe/research-universe-v1.toml``. While the manifest is DRAFT it
records the selection rule and slot count only; no symbol may be listed. Phase 13
freezes it once volume data exists.

``run()`` returns ``(name, ok, detail)`` tuples UN-01..UN-05.

Phase 13 handoff (freeze steps, in order):
  1. Rank all USDT perpetual contracts trading on the dataset start date by trailing
     30-day mean daily quote volume ending the day before the start date; contracts
     without a full 30-day window are ineligible.
  2. Take the top ``top_n`` contracts, including symbols delisted later.
  3. Fill ``symbols`` and ``selection_date`` and set ``status = "FROZEN"``.
  4. Set ``content_sha256`` to the output of
     ``python -m scripts.decision_alignment.universe <manifest path>``.
  5. Commit the frozen manifest before any evaluation runs.

Stdlib plus ``src.domain.canonical.sha256_hex`` only.
"""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

from src.domain.canonical import sha256_hex

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_DIR = REPO_ROOT / "docs" / "research" / "universe"
MANIFEST_PATH = UNIVERSE_DIR / "research-universe-v1.toml"
FORBIDDEN_PARAMS_DIR = REPO_ROOT / "params" / "universe"

SCHEMA = "research-universe/1"
STATUSES = ("DRAFT", "FROZEN")
TOP_N_MIN = 10
TOP_N_MAX = 15
SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_KEYS = (
    "schema",
    "status",
    "universe_id",
    "top_n",
    "contract_type",
    "quote_asset",
    "rank_metric",
    "rank_date_source",
    "include_delisted",
    "selection_date",
    "symbols",
    "freeze_owner",
    "live_universe_note",
    "content_sha256",
)

FIXED_VALUES = {
    "contract_type": "PERPETUAL",
    "quote_asset": "USDT",
    "rank_metric": "trailing_30d_mean_daily_quote_volume",
    "rank_date_source": "dataset_start_date",
}


def compute_content_sha256(doc: dict[str, Any]) -> str:
    """Hash the canonical payload; excludes status and content_sha256 themselves."""
    symbols = doc.get("symbols", [])
    payload: dict[str, Any] = {
        "schema": doc.get("schema"),
        "universe_id": doc.get("universe_id"),
        "contract_type": doc.get("contract_type"),
        "quote_asset": doc.get("quote_asset"),
        "rank_metric": doc.get("rank_metric"),
        "rank_date_source": doc.get("rank_date_source"),
        "top_n": doc.get("top_n"),
        "include_delisted": doc.get("include_delisted"),
        "selection_date": doc.get("selection_date"),
        "symbols": sorted(symbols) if isinstance(symbols, list) else symbols,
    }
    return sha256_hex(payload)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check_frozen(doc: dict[str, Any], top_n_ok: bool) -> list[str]:
    problems: list[str] = []
    symbols = doc["symbols"]
    if not isinstance(symbols, list):
        return ["symbols must be a list"]
    if not all(isinstance(s, str) and SYMBOL_RE.match(s) for s in symbols):
        bad = [s for s in symbols if not (isinstance(s, str) and SYMBOL_RE.match(s))]
        problems.append(f"invalid symbol(s) (uppercase *USDT expected): {bad!r}")
    if len(set(symbols)) != len(symbols):
        problems.append("duplicate symbols")
    if not TOP_N_MIN <= len(symbols) <= TOP_N_MAX:
        problems.append(f"FROZEN needs {TOP_N_MIN}-{TOP_N_MAX} symbols, got {len(symbols)}")
    if top_n_ok and len(symbols) != doc["top_n"]:
        problems.append(f"FROZEN symbol count {len(symbols)} differs from top_n {doc['top_n']}")
    if not _valid_iso_date(doc["selection_date"]):
        problems.append("FROZEN selection_date must be an ISO YYYY-MM-DD date")
    stored = doc["content_sha256"]
    if not isinstance(stored, str) or not HASH_RE.match(stored):
        problems.append("FROZEN content_sha256 must be 64 lowercase hex characters")
    else:
        try:
            matches = stored == compute_content_sha256(doc)
        except (TypeError, ValueError):
            matches = False
        if not matches:
            problems.append("content_sha256 does not match the canonical payload hash")
    return problems


def _check_draft(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if doc["symbols"] != []:
        problems.append("DRAFT manifest must list no symbols (no hand-picking, D-09)")
    if doc["selection_date"] != "":
        problems.append("DRAFT manifest must have an empty selection_date")
    if doc["content_sha256"] != "":
        problems.append("DRAFT manifest must have an empty content_sha256")
    return problems


def validate_manifest(doc: dict[str, Any]) -> list[str]:
    """Return human-readable problems; an empty list means valid."""
    missing = [k for k in REQUIRED_KEYS if k not in doc]
    if missing:
        return [f"missing key(s): {', '.join(missing)}"]
    problems: list[str] = []
    if doc["schema"] != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r}, got {doc['schema']!r}")
    if doc["status"] not in STATUSES:
        problems.append(f"status must be one of {STATUSES}, got {doc['status']!r}")
    top_n = doc["top_n"]
    top_n_ok = _is_int(top_n) and TOP_N_MIN <= top_n <= TOP_N_MAX
    if not top_n_ok:
        problems.append(f"top_n must be an int in {TOP_N_MIN}-{TOP_N_MAX}, got {top_n!r}")
    if doc["include_delisted"] is not True:
        problems.append("include_delisted must be true (D039)")
    for key, expected in FIXED_VALUES.items():
        if doc[key] != expected:
            problems.append(f"{key} must be {expected!r}, got {doc[key]!r}")
    note = doc["live_universe_note"]
    if not (isinstance(note, str) and "live-5" in note and "unchanged" in note):
        problems.append("live_universe_note must state the live-5 list is separate and unchanged")
    if doc["status"] == "DRAFT":
        problems.extend(_check_draft(doc))
    elif doc["status"] == "FROZEN":
        problems.extend(_check_frozen(doc, top_n_ok))
    return problems


def _result(name: str, problems: list[str], ok_detail: str) -> tuple[str, bool, str]:
    if problems:
        return (name, False, "; ".join(problems))
    return (name, True, ok_detail)


def run() -> list[tuple[str, bool, str]]:
    """Evaluate gates UN-01..UN-05 against the real repository manifest."""
    try:
        with MANIFEST_PATH.open("rb") as fh:
            doc: dict[str, Any] = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        detail = f"manifest unreadable: {exc}"
        return [(f"UN-0{i}", False, detail) for i in range(1, 6)]

    un01 = validate_manifest(doc)

    un02: list[str] = []
    status = doc.get("status")
    stored = doc.get("content_sha256")
    if status == "DRAFT" and stored != "":
        un02.append("DRAFT manifest carries a hash")
    if status == "FROZEN":
        try:
            if stored != compute_content_sha256(doc):
                un02.append("FROZEN hash does not match the canonical payload")
        except (TypeError, ValueError) as exc:
            un02.append(f"hash not computable: {exc}")
    if status not in STATUSES:
        un02.append(f"unknown status {status!r}")

    un03: list[str] = []
    if not MANIFEST_PATH.is_relative_to(UNIVERSE_DIR):
        un03.append("manifest is not under docs/research/universe")
    if FORBIDDEN_PARAMS_DIR.exists():
        un03.append("params/universe exists (would be read as a strategy family)")

    un04: list[str] = []
    if status == "DRAFT" and doc.get("symbols"):
        un04.append("DRAFT manifest lists symbols")

    note = doc.get("live_universe_note")
    un05: list[str] = []
    if not (isinstance(note, str) and "live-5" in note and "unchanged" in note):
        un05.append("live_universe_note must mention live-5 and unchanged")

    return [
        _result("UN-01", un01, f"manifest valid, status {status}"),
        _result("UN-02", un02, "status and hash consistent"),
        _result("UN-03", un03, "manifest under docs/research/universe, params/universe absent"),
        _result("UN-04", un04, "no symbol listed while DRAFT"),
        _result("UN-05", un05, "live-5 separation note present"),
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.decision_alignment.universe <manifest.toml>")
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"manifest not found: {path}", file=sys.stderr)
        return 1
    with path.open("rb") as fh:
        doc = tomllib.load(fh)
    print(compute_content_sha256(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
