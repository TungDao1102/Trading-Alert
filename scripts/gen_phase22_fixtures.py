"""Deterministic generator of the Phase 22 recorded-Demo configuration fixtures (plan 22-01, D-19).

Reads the owner-run Demo capture of 2026-10-22 (Phase 19 evidence, evidence commit 48a26473) and
writes, under `tests/fixtures/phase22/recorded_demo/`, the SDK wire shape of the configuration
reads the adapter parses (`GET /fapi/v1/symbolConfig`, `GET /fapi/v1/leverageBracket`). The
capture files hold the FLATTENED `observation.summary` map the probe wrote (keys such as
`0.leverage`, every value text), not raw responses. This script unflattens that map (digit
segments become list positions) and gives the non-string wire fields back their JSON type
(`WIRE_TYPES`). Nothing is typed by hand (AGENTS.md).

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
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "phase22"
RECORDED_SUBDIR = "recorded_demo"

# A plain non-negative decimal number: no sign, no exponent, no NaN or Infinity.
_NUMBER_TEXT = re.compile(r"\d+(?:\.\d+)?")

# Non-string SDK wire fields (per the installed SDK 17.4.0 models) and the JSON type they take.
# Any other recorded text for such a field is a ValueError. Every field not listed stays text.
# "number" is a JSON number: the SDK declares `maintMarginRatio` and `cum` StrictFloat or
# StrictInt, so the fixture must carry numbers, not text. The recorded text is written back as
# the same number ("0.004" -> 0.004, "0.0" -> 0.0, "50.0" -> 50.0, "7" -> 7).
WIRE_TYPES: dict[str, str] = {
    "isAutoAddMargin": "bool",
    "leverage": "int",
    "bracket": "int",
    "initialLeverage": "int",
    "notionalCap": "int",
    "notionalFloor": "int",
    "maintMarginRatio": "number",
    "cum": "number",
}

# (source capture file, output file) pairs written by `main`.
OUTPUTS: tuple[tuple[str, str], ...] = (
    (
        "account_read_only_capture-rest-004-symbol_config.json",
        "symbol_config.json",
    ),
    (
        "account_read_only_capture-rest-005-leverage_brackets.json",
        "leverage_brackets.json",
    ),
)


def _convert(field: str, text: Any) -> Any:
    """Give `field` its JSON wire type; plain text fields pass through unchanged."""
    kind = WIRE_TYPES.get(field)
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
    if kind == "number":
        if _NUMBER_TEXT.fullmatch(text) is None:
            raise ValueError(f"field {field}: recorded text is not a plain number")
        return float(text) if "." in text else int(text)
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

    Dotted keys become nested objects; digit segments become list positions. Non-string wire
    fields are converted by `WIRE_TYPES`.
    """
    root: dict[str, Any] = {}
    for key in sorted(summary):
        parts = key.split(".")
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
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the Phase 22 recorded-Demo fixtures.")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="Phase 19 capture directory")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output root directory")
    args = parser.parse_args(argv)
    written = write_all(args.src, args.out)
    print(f"Phase 22 fixtures written: {len(written)} files under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
