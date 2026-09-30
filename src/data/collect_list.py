"""Collect list: which symbols the OI/funding collector polls (Phase 13, DATA-02).

The collect list is an OPERATIONAL input (D-01, D-02): the live-5 union the
top 15 TRADING USDT perpetuals by current 24h quote volume, with the date
they were chosen. It is deliberately not a research-universe manifest: it
has no FROZEN semantics and no content hash, and it lives under
`docs/research/universe`, never under `params/`.

Fail-closed posture: any defect (missing file, unreadable, invalid TOML,
missing key, empty list, malformed or duplicate symbol, a live-5 symbol
absent, bad date) raises `CollectListError`. Callers must refuse to start;
there is no fallback to the live-5 list, because a silent fallback would
quietly stop collecting OI for the wider universe (T-13-02).

The symbol and date patterns duplicate `scripts/decision_alignment/universe.py`
on purpose: `src/` must not import from `scripts/`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.data.backfill import LIVE_5

SCHEMA = "collect-list/1"
SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Relative to the working directory (repo root locally, /app in the image).
DEFAULT_COLLECT_LIST_PATH = (
    Path("docs") / "research" / "universe" / "collect-list-v1.toml"
)

_REQUIRED_KEYS = (
    "schema",
    "list_id",
    "chosen_on",
    "selection_rule",
    "top_n",
    "symbols",
)


class CollectListError(ValueError):
    """The collect list is missing, unreadable or invalid (fail closed)."""


@dataclass(frozen=True)
class CollectList:
    """A validated collect list; `symbols` is sorted ascending."""

    list_id: str
    chosen_on: date
    top_n: int
    selection_rule: str
    symbols: tuple[str, ...]


def _require_str(doc: dict[str, Any], key: str, path: Path) -> str:
    value = doc[key]
    if not isinstance(value, str) or not value.strip():
        raise CollectListError(f"{path}: '{key}' must be a non-empty string")
    return value


def _parse_chosen_on(raw: object, path: Path) -> date:
    if not isinstance(raw, str) or not DATE_RE.match(raw):
        raise CollectListError(
            f"{path}: 'chosen_on' must be a quoted ISO date YYYY-MM-DD, got {raw!r}"
        )
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise CollectListError(
            f"{path}: 'chosen_on' is not a real calendar date: {raw!r}"
        ) from exc


def _validate_symbols(raw: object, path: Path) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise CollectListError(f"{path}: 'symbols' must be a list of symbol strings")
    if not raw:
        raise CollectListError(f"{path}: 'symbols' is empty; refusing to collect nothing")
    seen: set[str] = set()
    for sym in raw:
        if not isinstance(sym, str) or not SYMBOL_RE.match(sym):
            raise CollectListError(
                f"{path}: invalid symbol {sym!r} (must match {SYMBOL_RE.pattern})"
            )
        if sym in seen:
            raise CollectListError(f"{path}: duplicate symbol {sym!r}")
        seen.add(sym)
    missing_live = [s for s in LIVE_5 if s not in seen]
    if missing_live:
        raise CollectListError(
            f"{path}: must be a superset of the live-5; missing {missing_live}"
        )
    return tuple(sorted(seen))


def load_collect_list(path: Path) -> CollectList:
    """Load and validate the collect list at `path` (raises `CollectListError`)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CollectListError(f"{path}: cannot read collect list: {exc}") from exc
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CollectListError(f"{path}: invalid TOML: {exc}") from exc

    for key in _REQUIRED_KEYS:
        if key not in doc:
            raise CollectListError(f"{path}: missing required key '{key}'")
    if doc["schema"] != SCHEMA:
        raise CollectListError(
            f"{path}: unsupported schema {doc['schema']!r}, expected {SCHEMA!r}"
        )
    list_id = _require_str(doc, "list_id", path)
    selection_rule = _require_str(doc, "selection_rule", path)
    chosen_on = _parse_chosen_on(doc["chosen_on"], path)
    top_n = doc["top_n"]
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
        raise CollectListError(f"{path}: 'top_n' must be an integer >= 1, got {top_n!r}")
    symbols = _validate_symbols(doc["symbols"], path)
    return CollectList(
        list_id=list_id,
        chosen_on=chosen_on,
        top_n=top_n,
        selection_rule=selection_rule,
        symbols=symbols,
    )
