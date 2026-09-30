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

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
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


DEFAULT_LIST_ID = "collect-list-v1"
DEFAULT_TOP_N = 15
DEFAULT_SOURCE_NOTE = "GET /fapi/v1/ticker/24hr and GET /fapi/v1/exchangeInfo"


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


# --------------------------------------------------------------------------- #
# Proposer: deterministic selection from raw public exchange JSON.
# --------------------------------------------------------------------------- #


def _selection_rule(top_n: int) -> str:
    return (
        f"live-5 union top {top_n} TRADING USDT PERPETUAL by 24h quoteVolume "
        "(GET /fapi/v1/ticker/24hr)"
    )


def _is_eligible(record: Mapping[str, Any]) -> bool:
    symbol = record.get("symbol")
    return (
        record.get("contractType") == "PERPETUAL"
        and record.get("quoteAsset") == "USDT"
        and record.get("status") == "TRADING"
        and isinstance(symbol, str)
        and SYMBOL_RE.match(symbol) is not None
    )


def _parse_quote_volume(symbol: str, value: object) -> Decimal:
    try:
        volume = Decimal(str(value))
    except InvalidOperation as exc:
        raise CollectListError(
            f"ticker row for {symbol}: quoteVolume {value!r} is not a decimal"
        ) from exc
    if not volume.is_finite() or volume < 0:
        raise CollectListError(
            f"ticker row for {symbol}: quoteVolume {value!r} must be a finite "
            "non-negative decimal"
        )
    return volume


def propose_collect_list(
    ticker_rows: Sequence[Mapping[str, Any]],
    exchange_symbols: Sequence[Mapping[str, Any]],
    *,
    live_symbols: Sequence[str],
    top_n: int,
    chosen_on: date,
    list_id: str,
) -> CollectList:
    """Propose the collect list: live symbols union the top `top_n` by 24h volume.

    Inputs are the raw public JSON dicts (`/fapi/v1/ticker/24hr` rows and
    `/fapi/v1/exchangeInfo` symbol records); no SDK models are involved.
    Eligible symbols are TRADING PERPETUAL USDT contracts (TRADIFI_PERPETUAL,
    SETTLING, PENDING_TRADING, dated futures and non-USDT quotes are out).
    Ranking is by `Decimal(quoteVolume)` descending, ties broken by symbol
    ascending, so the same inputs always give the same list.
    """
    if isinstance(top_n, bool) or top_n < 1:
        raise CollectListError(f"top_n must be an integer >= 1, got {top_n!r}")
    records: dict[str, Mapping[str, Any]] = {}
    for record in exchange_symbols:
        name = record.get("symbol")
        if not isinstance(name, str):
            raise CollectListError(f"exchangeInfo record without a symbol: {record!r}")
        if name in records:
            raise CollectListError(f"exchangeInfo lists {name} more than once")
        records[name] = record
    for live in live_symbols:
        live_record = records.get(live)
        if live_record is None:
            raise CollectListError(f"live symbol {live} is missing from exchangeInfo")
        if not _is_eligible(live_record):
            raise CollectListError(
                f"live symbol {live} is not a TRADING PERPETUAL USDT contract "
                f"(contractType={live_record.get('contractType')!r}, "
                f"status={live_record.get('status')!r}, "
                f"quoteAsset={live_record.get('quoteAsset')!r})"
            )

    volumes: dict[str, Decimal] = {}
    for row in ticker_rows:
        symbol = row.get("symbol")
        if not isinstance(symbol, str):
            raise CollectListError(f"ticker row without a symbol: {row!r}")
        listed = records.get(symbol)
        if listed is None or not _is_eligible(listed):
            continue
        if symbol in volumes:
            raise CollectListError(f"ticker lists {symbol} more than once")
        volumes[symbol] = _parse_quote_volume(symbol, row.get("quoteVolume"))
    if len(volumes) < top_n:
        raise CollectListError(
            f"only {len(volumes)} eligible symbols have a ticker row, "
            f"fewer than top_n={top_n}"
        )
    ranked = sorted(volumes, key=lambda sym: (-volumes[sym], sym))
    chosen = set(ranked[:top_n]) | set(live_symbols)
    return CollectList(
        list_id=list_id,
        chosen_on=chosen_on,
        top_n=top_n,
        selection_rule=_selection_rule(top_n),
        symbols=tuple(sorted(chosen)),
    )


def _toml_str(value: str) -> str:
    """Render a TOML basic string; JSON string escaping is valid TOML here."""
    return json.dumps(value)


def render_collect_list_toml(collect_list: CollectList, *, source_note: str) -> str:
    """Render `collect_list` as TOML text that `load_collect_list` parses back."""
    header = [
        "# Collect list for the OI/funding collector (Phase 13, D-01, D-02).",
        "#",
        "# This file is an operational input for the OI/funding collector: the live-5",
        "# union the top N TRADING USDT perpetuals by 24h quote volume at the date it",
        "# was chosen. It has no FROZEN semantics and no content hash, and it is not",
        "# the research-universe manifest (research-universe-v1.toml). A later version",
        "# supersedes it without touching stored data.",
        "#",
        "# Regenerate: python -m src.data.collect_list propose --help",
        "#",
    ]
    header += [f"# Source: {line}" if line else "#" for line in source_note.splitlines()]
    body = [
        f"schema = {_toml_str(SCHEMA)}",
        f"list_id = {_toml_str(collect_list.list_id)}",
        f"chosen_on = {_toml_str(collect_list.chosen_on.isoformat())}",
        f"selection_rule = {_toml_str(collect_list.selection_rule)}",
        f"top_n = {collect_list.top_n}",
        "symbols = [",
        *(f"    {_toml_str(sym)}," for sym in collect_list.symbols),
        "]",
    ]
    return "\n".join([*header, "", *body]) + "\n"


# --------------------------------------------------------------------------- #
# CLI: python -m src.data.collect_list propose ...
# --------------------------------------------------------------------------- #


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CollectListError(f"{label} {path}: cannot read JSON: {exc}") from exc


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.data.collect_list",
        description="Collect list tooling (Phase 13, D-01, D-02).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser(
        "propose",
        help="Propose a collect list from saved public ticker/exchangeInfo JSON.",
    )
    propose.add_argument("--ticker-json", type=Path, required=True)
    propose.add_argument("--exchange-info-json", type=Path, required=True)
    propose.add_argument("--chosen-on", required=True, help="ISO date YYYY-MM-DD (UTC).")
    propose.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    propose.add_argument("--list-id", default=DEFAULT_LIST_ID)
    propose.add_argument(
        "--fetched-at",
        default=None,
        help="UTC fetch timestamp recorded in the file's source comment.",
    )
    propose.add_argument("--out", type=Path, required=True, help="Output path; must not exist.")
    return parser.parse_args(argv)


def _run_propose(args: argparse.Namespace) -> None:
    if not DATE_RE.match(args.chosen_on):
        raise CollectListError(f"--chosen-on must be YYYY-MM-DD, got {args.chosen_on!r}")
    try:
        chosen_on = date.fromisoformat(args.chosen_on)
    except ValueError as exc:
        raise CollectListError(f"--chosen-on is not a real date: {args.chosen_on!r}") from exc
    if args.out.exists():
        raise CollectListError(f"--out {args.out} already exists; refusing to overwrite")
    ticker = _load_json(args.ticker_json, "ticker json")
    exchange = _load_json(args.exchange_info_json, "exchangeInfo json")
    if isinstance(exchange, dict):
        exchange = exchange.get("symbols")
    if not isinstance(ticker, list) or not isinstance(exchange, list):
        raise CollectListError(
            "ticker json must be a list and exchangeInfo json must hold a 'symbols' list"
        )
    proposed = propose_collect_list(
        ticker,
        exchange,
        live_symbols=LIVE_5,
        top_n=args.top_n,
        chosen_on=chosen_on,
        list_id=args.list_id,
    )
    note = DEFAULT_SOURCE_NOTE
    if args.fetched_at:
        note += f"\nfetched {args.fetched_at} (UTC)"
    text = render_collect_list_toml(proposed, source_note=note)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise CollectListError(f"--out {args.out} already exists; refusing to overwrite") from exc
    print(f"collect-list: wrote {len(proposed.symbols)} symbols to {args.out}")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns 0 on success, 2 on usage or input errors."""
    args = _parse_args(argv)
    try:
        if args.command == "propose":
            _run_propose(args)
    except CollectListError as exc:
        print(f"collect-list: error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
