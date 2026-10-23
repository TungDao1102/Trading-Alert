"""Deterministic generator of the Phase 21 recorded-Demo account fixtures (plan 21-03, D-22).

Reads the owner-run Demo capture of 2026-10-22 (Phase 19 evidence, evidence commit 48a26473) and
writes, under `tests/fixtures/phase21/recorded_demo/`, the SDK wire shape of the three account
reads the adapter parses. The capture files hold the FLATTENED `observation.summary` map the
probe wrote (keys such as `assets.5.marginBalance`, every value text). This script unflattens
that map (digit segments become list positions) and gives the non-string wire fields back their
JSON type (`WIRE_TYPES`). Nothing is typed by hand (AGENTS.md).

The account alias field of the balance endpoint is dropped from every object: it is an account
identifier and must never reach a committed fixture (D-21). Its name appears in this file only
as the constant `ALIAS_FIELD`.

Plan 21-08 adds the REST trade rows (`user_trades_*.json`: the probe's `row_<n>_<field>` text map
mapped to SDK aliases and JSON types by fixed tables), the empty funding income answer
(`income_funding_empty.json`) and a byte-for-byte copy of the recorded ORDER_TRADE_UPDATE and
ACCOUNT_UPDATE stream frames (`frames/`) for the user-data tests.

Demo values: demo-observed, not mainnet. This script imports nothing from `src/` or `tests/`,
reads only committed files and makes no network call. Running it twice gives byte-identical
files (sorted keys, 2-space indent, LF line endings, no clock).
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "19-execution-plan-binding-price-check"
    / "evidence"
    / "fixtures"
)
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "phase21"
RECORDED_SUBDIR = "recorded_demo"

# The account identifier of the balance endpoint: dropped, never read, never written (D-21).
ALIAS_FIELD = "accountAlias"

# Non-string SDK wire fields (per the installed SDK 17.4.0 models) and the JSON type they take.
# Any other recorded text for such a field is a ValueError. Every field not listed stays text.
WIRE_TYPES: dict[str, str] = {
    "updateTime": "int",
    "feeTier": "int",
    "tradeGroupId": "int",
    "marginAvailable": "bool",
    "canDeposit": "bool",
    "canTrade": "bool",
    "canWithdraw": "bool",
    "dualSidePosition": "bool",
    "multiAssetsMargin": "bool",
}

# Plan 21-08: the trade rows. The probe wrote `row_<n>_<field>` text for the fields below; the
# table maps each probe field to its SDK alias (the SDK model `AccountTradeListResponseInner`).
TRADE_FIELD_MAP: dict[str, str] = {
    "buyer": "buyer",
    "commission": "commission",
    "commission_asset": "commissionAsset",
    "maker": "maker",
    "margin_asset": "marginAsset",
    "order_id": "orderId",
    "position_side": "positionSide",
    "price": "price",
    "qty": "qty",
    "quote_qty": "quoteQty",
    "realized_pnl": "realizedPnl",
    "side": "side",
    "time_ms": "time",
    "trade_id": "id",
}
TRADE_WIRE_TYPES: dict[str, str] = {
    "id": "int",
    "orderId": "int",
    "time": "int",
    "buyer": "bool",
    "maker": "bool",
}
# The probe summary carries no symbol. Both recorded cases ran on BTCUSDT (19-OWNER-GAPS.md
# section 2a): the symbol is a generator reconstruction, not a captured value.
TRADE_CASE_SYMBOL = "BTCUSDT"
TRADE_KEY = re.compile(r"row_(\d+)_(.+)")

# output file -> source capture files, in recorded order (a repeated trade id is kept once).
TRADE_OUTPUTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "user_trades_commission_case.json",
        (
            "commission_vs_realized_pnl-rest-005-user_trades.json",
            "commission_vs_realized_pnl-rest-006-user_trades.json",
        ),
    ),
    (
        "user_trades_triggered_bracket.json",
        ("triggered_close_position_bracket-rest-015-user_trades.json",),
    ),
)

# The recorded income reads (zero rows each): the generator checks the recorded count is "0".
INCOME_EMPTY_OUTPUT = "income_funding_empty.json"
INCOME_EMPTY_SOURCES: tuple[str, ...] = (
    "commission_vs_realized_pnl-rest-007-income_history.json",
    "commission_vs_realized_pnl-rest-008-income_history.json",
)

# Raw stream frames copied byte for byte (already scrubbed by the probe tool, never edited).
FRAMES_SUBDIR = "frames"
FRAME_CASES: tuple[str, ...] = ("triggered_close_position_bracket", "commission_vs_realized_pnl")
FRAME_KINDS: tuple[str, ...] = ("ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE")

# (source capture file, output file) pairs written by `main`.
OUTPUTS: tuple[tuple[str, str], ...] = (
    (
        "account_read_only_capture-rest-001-account_information.json",
        "account_information_v3.json",
    ),
    (
        "account_read_only_capture-rest-002-account_balance_all.json",
        "account_balance_v3.json",
    ),
    (
        "account_read_only_capture-rest-003-account_config.json",
        "account_config.json",
    ),
)


def _convert(field: str, text: Any, types: Mapping[str, str] = WIRE_TYPES) -> Any:
    """Give `field` its JSON wire type; plain text fields pass through unchanged."""
    kind = types.get(field)
    if kind is None:
        return text
    if not isinstance(text, str):
        raise ValueError(f"field {field}: recorded value is not text")
    if kind == "bool":
        if text == "true":
            return True
        if text == "false":
            return False
        raise ValueError(f"field {field}: recorded text is not a boolean")
    if kind == "int":
        digits = text[1:] if text.startswith("-") else text
        if not digits.isdigit():
            raise ValueError(f"field {field}: recorded text is not an integer")
        return int(text)
    raise ValueError(f"field {field}: unknown wire type")


def _listify(node: Any) -> Any:
    """Turn dicts whose keys are all digits into lists ordered by index (a gap raises)."""
    if not isinstance(node, dict):
        return node
    converted = {key: _listify(value) for key, value in node.items()}
    if converted and all(key.isdigit() for key in converted):
        indices = sorted(int(key) for key in converted)
        if indices != list(range(len(indices))):
            raise ValueError("recorded list has a gap in its indices")
        return [converted[str(index)] for index in indices]
    return converted


def unflatten_summary(summary: Mapping[str, Any]) -> Any:
    """Nested object (or list) of a flattened `observation.summary` map.

    Dotted keys become nested objects; digit segments become list positions. The alias field
    is dropped and non-string wire fields are converted by `WIRE_TYPES`.
    """
    root: dict[str, Any] = {}
    for key in sorted(summary):
        parts = key.split(".")
        if parts[-1] == ALIAS_FIELD:
            continue
        node = root
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError("recorded keys collide")
            node = child
        if parts[-1] in node:
            raise ValueError("recorded keys collide")
        node[parts[-1]] = _convert(parts[-1], summary[key])
    return _listify(root)


def render(value: Any) -> str:
    """The canonical text of one fixture: sorted keys, 2-space indent, final LF."""
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def _load_summary(path: Path) -> Mapping[str, Any]:
    capture = json.loads(path.read_text(encoding="utf-8"))
    observation = capture["observation"]
    if observation.get("ok") is not True or observation.get("error") is not None:
        raise ValueError(f"capture {path.name} is not a successful observation")
    summary = observation["summary"]
    if not isinstance(summary, dict):
        raise ValueError(f"capture {path.name} has no summary map")
    return summary


def trade_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """SDK-shaped trade rows of one flattened `user_trades` summary (plan 21-08).

    The summary holds `count` and `row_<n>_<field>` text. Probe fields are renamed to the SDK
    aliases by `TRADE_FIELD_MAP`, typed by `TRADE_WIRE_TYPES`, and `symbol` is added from
    `TRADE_CASE_SYMBOL`. A missing, unknown or extra field, a gap in the row indices or a count
    that disagrees with the rows raises `ValueError`.
    """
    count_text = summary.get("count")
    if not isinstance(count_text, str) or not count_text.isdigit():
        raise ValueError("recorded trade summary has no numeric count")
    rows: dict[int, dict[str, Any]] = {}
    for key in sorted(summary):
        if key == "count":
            continue
        match = TRADE_KEY.fullmatch(key)
        if match is None or match.group(2) not in TRADE_FIELD_MAP:
            raise ValueError("recorded trade summary has an unknown key")
        alias = TRADE_FIELD_MAP[match.group(2)]
        rows.setdefault(int(match.group(1)), {})[alias] = _convert(
            alias, summary[key], TRADE_WIRE_TYPES
        )
    if sorted(rows) != list(range(int(count_text))):
        raise ValueError("recorded trade summary count disagrees with its rows")
    out: list[dict[str, Any]] = []
    for index in sorted(rows):
        row = rows[index]
        if set(row) != set(TRADE_FIELD_MAP.values()):
            raise ValueError("recorded trade row is missing a field")
        row["symbol"] = TRADE_CASE_SYMBOL
        out.append(row)
    return out


def merged_trade_rows(src: Path, names: Sequence[str]) -> list[dict[str, Any]]:
    """Rows of several trade captures in recorded order; one row per trade id (a clash raises)."""
    seen: dict[int, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for name in names:
        for row in trade_rows(_load_summary(src / name)):
            known = seen.get(row["id"])
            if known is None:
                seen[row["id"]] = row
                ordered.append(row)
            elif known != row:
                raise ValueError("two recorded trade rows share an id but differ")
    return ordered


def _frame_sources(src: Path) -> list[Path]:
    """The recorded ORDER_TRADE_UPDATE and ACCOUNT_UPDATE frame files of `FRAME_CASES`."""
    found: list[Path] = []
    for case in FRAME_CASES:
        pattern = re.compile(
            rf"{re.escape(case)}-\d{{3}}-(?:{'|'.join(FRAME_KINDS)})(?:-\d+)?\.json"
        )
        matched = sorted(path for path in src.iterdir() if pattern.fullmatch(path.name))
        if not matched:
            raise ValueError(f"no recorded stream frame found for case {case}")
        found.extend(matched)
    return found


def _write_text(target: Path, text: str) -> None:
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_all(src: Path, out: Path) -> list[Path]:
    """Write every fixture under `<out>/recorded_demo/`; return the paths written."""
    target_dir = out / RECORDED_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for source_name, output_name in OUTPUTS:
        value = unflatten_summary(_load_summary(src / source_name))
        target = target_dir / output_name
        _write_text(target, render(value))
        written.append(target)
    for output_name, source_names in TRADE_OUTPUTS:
        target = target_dir / output_name
        _write_text(target, render(merged_trade_rows(src, source_names)))
        written.append(target)
    for name in INCOME_EMPTY_SOURCES:
        if _load_summary(src / name).get("count") != "0":
            raise ValueError(f"capture {name} is not an empty income answer")
    target = target_dir / INCOME_EMPTY_OUTPUT
    _write_text(target, render([]))
    written.append(target)
    frames_dir = target_dir / FRAMES_SUBDIR
    frames_dir.mkdir(parents=True, exist_ok=True)
    for source in _frame_sources(src):
        target = frames_dir / source.name
        target.write_bytes(source.read_bytes())
        written.append(target)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the Phase 21 recorded-Demo fixtures.")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="Phase 19 capture directory")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output root directory")
    args = parser.parse_args(argv)
    written = write_all(args.src, args.out)
    print(f"Phase 21 fixtures written: {len(written)} files under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
