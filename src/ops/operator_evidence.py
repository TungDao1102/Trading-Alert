"""Shared pieces of the connected-machine operator tools (Phase 18, plan 18-16, D-15).

Used by the user-data smoke (`scripts/user_data_smoke.py`, plan 18-16) and the Demo probe
(`scripts/demo_probe.py`, plans 18-17 and 18-23); those plans consume this module and do not
change it.

* Exit codes: 0 completed, 1 failed part-way (evidence written), 2 refused before any network
  call, 3 aborted before any order.
* `jsonable`: Decimal to plain text, aware datetime to UTC ISO text, Enum to its value,
  dataclass to a dict, mappings and sequences recursively. A float, a naive datetime or any
  other type raises: evidence carries no float and no ambiguous time.
* `write_evidence_atomic`: sorted-key ASCII JSON with LF newlines, scrubbed with the given
  redactor and with the process redactor (which carries every runtime-registered key, secret
  and listenKey) before the write, written to a temp file and moved with `os.replace` into a
  name that does not exist yet (`-2`, `-3` on a collision), then re-read and re-scanned; a file
  the scan still changes is deleted and the call raises.
* `confirm_execute`: the explicit go-ahead of a human on an interactive terminal, by typing an
  exact phrase.
* `DemoOrderLimits` and `load_demo_order_limits`: the owner-approved order size and waits of a
  Demo run, from a TOML file. Kind "smoke" (plan 18-16) and kind "probe" (plans 18-17, 18-23).
  Nothing has a default: every missing, unknown or malformed key refuses the file.
* `sha256_lf`: the sha256 of a text file with CRLF normalized to LF.

Standard library and `src.ops.redaction` only: no SDK, no adapter, no network.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from src.ops.redaction import scrub as process_scrub

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_ABORTED = 3


# --------------------------------------------------------------------------- #
# jsonable.
# --------------------------------------------------------------------------- #


def jsonable(value: Any) -> Any:
    """`value` as plain JSON data; refuses a float, a naive datetime and unknown types."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("a non-finite Decimal cannot be written as evidence")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("a naive datetime cannot be written as evidence")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return jsonable(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: jsonable(getattr(value, item.name)) for item in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {_key(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    raise TypeError(f"type {type(value).__name__} cannot be written as evidence")


def _key(key: object) -> str:
    if isinstance(key, Enum):
        key = key.value
    if not isinstance(key, str):
        raise TypeError("evidence mapping keys must be text")
    return key


# --------------------------------------------------------------------------- #
# Atomic, scrubbed evidence write.
# --------------------------------------------------------------------------- #


class TextScrubber(Protocol):
    """Anything with `scrub(text) -> text` (`src.ops.redaction.Redactor`)."""

    def scrub(self, text: str) -> str: ...


_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _scrub_both(text: str, redactor: TextScrubber) -> str:
    return process_scrub(redactor.scrub(text))


def write_evidence_atomic(
    directory: Path, stem: str, document: Mapping[str, Any], redactor: TextScrubber
) -> Path:
    """Write `document` as `<directory>/<stem>.json` (or `<stem>-N.json`); return the path.

    The text is scrubbed before the write and the written file is re-read and re-scanned; a
    file the scan would still change is deleted and `RuntimeError` is raised. An existing file
    is never overwritten.
    """
    if not _STEM_RE.fullmatch(stem) or stem in {".", ".."}:
        raise ValueError("the evidence file stem must be a plain file name")
    text = json.dumps(jsonable(document), sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    text = _scrub_both(text, redactor)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}.json"
    counter = 2
    while target.exists():
        target = directory / f"{stem}-{counter}.json"
        counter += 1
    handle, temp_name = tempfile.mkstemp(dir=directory, prefix=f".{target.name}.", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    written = target.read_bytes().decode("utf-8")
    if _scrub_both(written, redactor) != written:
        target.unlink()
        raise RuntimeError("evidence failed the post-write secret scan and was removed")
    return target


# --------------------------------------------------------------------------- #
# The typed confirmation.
# --------------------------------------------------------------------------- #


class ConfirmationRefused(Exception):  # noqa: N818 - a refusal, like the rehearsal's
    """The `--execute` confirmation failed (no terminal, no input, wrong phrase)."""


def confirm_execute(
    phrase: str, is_tty: Callable[[], bool], read_confirmation: Callable[[str], str]
) -> None:
    """Return only when a terminal is attached and the typed text equals `phrase` exactly."""
    if not is_tty():
        raise ConfirmationRefused("--execute needs an interactive terminal")
    try:
        typed = read_confirmation(f"Type exactly '{phrase}' to send real requests: ")
    except (EOFError, OSError):
        raise ConfirmationRefused("no confirmation was typed") from None
    if typed != phrase:
        raise ConfirmationRefused("the typed phrase did not match")


# --------------------------------------------------------------------------- #
# The owner's order limits of a Demo run.
# --------------------------------------------------------------------------- #

KIND_SMOKE = "smoke"
KIND_PROBE = "probe"

OPTIONAL_CASE_KEYS: tuple[str, ...] = (
    "explicit_time_in_force",
    "stream_gap",
    "market_lot_size_out_of_range",
)
_MARKET_LOT_CASE = "market_lot_size_out_of_range"
_MARKET_LOT_QUANTITY = "market_lot_probe_quantity"

# Per kind: section -> the keys it must carry (exactly).
_LAYOUT: Mapping[str, Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        KIND_SMOKE: MappingProxyType(
            {
                "order": ("symbol", "quantity", "far_price_fraction"),
                "waits": ("event_wait_seconds", "cleanup_timeout_seconds"),
            }
        ),
        KIND_PROBE: MappingProxyType(
            {
                "order": ("symbol", "quantity", "max_notional_quote", "far_price_fraction"),
                "waits": ("case_timeout_seconds", "cleanup_timeout_seconds"),
                "optional_cases": OPTIONAL_CASE_KEYS,
            }
        ),
    }
)

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
_PLAIN_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")


class DemoOrderLimitsRefused(Exception):  # noqa: N818 - a refusal of the owner's file
    """The order-limits file is missing or invalid; the message names keys, never a value."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("demo order limits refused: " + "; ".join(self.problems))


@dataclass(frozen=True, kw_only=True)
class DemoOrderLimits:
    """The owner-approved order size and waits of one Demo run. No field has a default.

    `kind` is "smoke" or "probe". A field the kind does not use is None (`max_notional_quote`,
    `market_lot_probe_quantity` and `case_timeout_seconds` for the smoke; `event_wait_seconds`
    for the probe); `optional_cases` is empty for the smoke. `market_lot_probe_quantity` is set
    exactly when the optional case `market_lot_size_out_of_range` is enabled.
    """

    kind: str
    symbol: str
    quantity: Decimal
    far_price_fraction: Decimal
    max_notional_quote: Decimal | None
    market_lot_probe_quantity: Decimal | None
    event_wait_seconds: int | None
    case_timeout_seconds: int | None
    cleanup_timeout_seconds: int
    optional_cases: Mapping[str, bool]

    @property
    def enabled_optional_cases(self) -> tuple[str, ...]:
        """The enabled optional cases, in `OPTIONAL_CASE_KEYS` order."""
        return tuple(key for key in OPTIONAL_CASE_KEYS if self.optional_cases.get(key) is True)


def _decimal(section: Mapping[str, Any], dotted: str, key: str, problems: list[str]) -> Decimal:
    value = section.get(key)
    if not isinstance(value, str) or not _PLAIN_DECIMAL_RE.fullmatch(value):
        problems.append(f"{dotted} (must be a plain decimal string)")
        return Decimal(0)
    try:
        parsed = Decimal(value)
    except InvalidOperation:  # pragma: no cover - the pattern admits only valid text
        problems.append(f"{dotted} (must be a plain decimal string)")
        return Decimal(0)
    if parsed <= 0:
        problems.append(f"{dotted} (must be positive)")
    return parsed


def _positive_int(section: Mapping[str, Any], dotted: str, key: str, problems: list[str]) -> int:
    value = section.get(key)
    if type(value) is not int or value <= 0:
        problems.append(f"{dotted} (must be a positive integer)")
        return 0
    return value


def _check_keys(
    raw: Mapping[str, Any],
    layout: Mapping[str, tuple[str, ...]],
    optional: Mapping[str, tuple[str, ...]],
    problems: list[str],
) -> dict[str, Mapping[str, Any]]:
    sections: dict[str, Mapping[str, Any]] = {}
    for name in sorted(set(raw) - set(layout)):
        problems.append(f"{name} (unknown section)")
    for name, keys in layout.items():
        body = raw.get(name)
        if body is None:
            problems.append(f"{name} (missing section)")
            body = {}
        elif not isinstance(body, dict):
            problems.append(f"{name} (must be a table)")
            body = {}
        allowed = set(keys) | set(optional.get(name, ()))
        for key in sorted(set(body) - allowed):
            problems.append(f"{name}.{key} (unknown key)")
        for key in keys:
            if key not in body:
                problems.append(f"{name}.{key} (missing key)")
        sections[name] = body
    return sections


def load_demo_order_limits(path: Path | str, *, kind: str) -> DemoOrderLimits:
    """Load the owner's order-limits file of `kind` ("smoke" or "probe").

    Raises:
        ValueError: `kind` is neither "smoke" nor "probe" (a wiring error).
        DemoOrderLimitsRefused: the file is missing, not TOML, or any key is missing,
            unknown or malformed.
    """
    if kind not in _LAYOUT:
        raise ValueError("kind must be 'smoke' or 'probe'")
    file = Path(path)
    if not file.is_file():
        raise DemoOrderLimitsRefused(["the order limits file does not exist"])
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        raise DemoOrderLimitsRefused(["the order limits file is not valid TOML"]) from None

    problems: list[str] = []
    optional_keys = {"order": (_MARKET_LOT_QUANTITY,)} if kind == KIND_PROBE else {}
    sections = _check_keys(raw, _LAYOUT[kind], optional_keys, problems)
    order = sections["order"]
    waits = sections["waits"]

    symbol = order.get("symbol")
    if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol):
        problems.append("order.symbol (must be an upper-case symbol such as a USD-M perpetual)")
        symbol = ""
    quantity = _decimal(order, "order.quantity", "quantity", problems)
    fraction = _decimal(order, "order.far_price_fraction", "far_price_fraction", problems)
    if fraction >= 1:
        problems.append("order.far_price_fraction (must be strictly between 0 and 1)")
    cleanup = _positive_int(
        waits, "waits.cleanup_timeout_seconds", "cleanup_timeout_seconds", problems
    )

    max_notional: Decimal | None = None
    lot_quantity: Decimal | None = None
    event_wait: int | None = None
    case_timeout: int | None = None
    optional_cases: dict[str, bool] = {}
    if kind == KIND_SMOKE:
        event_wait = _positive_int(
            waits, "waits.event_wait_seconds", "event_wait_seconds", problems
        )
    else:
        max_notional = _decimal(order, "order.max_notional_quote", "max_notional_quote", problems)
        case_timeout = _positive_int(
            waits, "waits.case_timeout_seconds", "case_timeout_seconds", problems
        )
        cases = sections["optional_cases"]
        for key in OPTIONAL_CASE_KEYS:
            value = cases.get(key)
            if key in cases and not isinstance(value, bool):
                problems.append(f"optional_cases.{key} (must be true or false)")
            optional_cases[key] = value is True
        if optional_cases[_MARKET_LOT_CASE]:
            if _MARKET_LOT_QUANTITY not in order:
                problems.append(
                    f"order.{_MARKET_LOT_QUANTITY} (missing key: required when "
                    f"optional_cases.{_MARKET_LOT_CASE} is true)"
                )
            else:
                lot_quantity = _decimal(
                    order, f"order.{_MARKET_LOT_QUANTITY}", _MARKET_LOT_QUANTITY, problems
                )
        elif _MARKET_LOT_QUANTITY in order:
            problems.append(
                f"order.{_MARKET_LOT_QUANTITY} (only allowed when "
                f"optional_cases.{_MARKET_LOT_CASE} is true)"
            )

    if problems:
        raise DemoOrderLimitsRefused(problems)
    return DemoOrderLimits(
        kind=kind,
        symbol=symbol,
        quantity=quantity,
        far_price_fraction=fraction,
        max_notional_quote=max_notional,
        market_lot_probe_quantity=lot_quantity,
        event_wait_seconds=event_wait,
        case_timeout_seconds=case_timeout,
        cleanup_timeout_seconds=cleanup,
        optional_cases=MappingProxyType(optional_cases),
    )


# --------------------------------------------------------------------------- #
# sha256 of a text file, line-ending independent.
# --------------------------------------------------------------------------- #


def sha256_lf(path: Path | str) -> str:
    """The sha256 hex digest of the file with every CRLF replaced by LF."""
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "EXIT_ABORTED",
    "EXIT_FAILED",
    "EXIT_OK",
    "EXIT_REFUSED",
    "KIND_PROBE",
    "KIND_SMOKE",
    "OPTIONAL_CASE_KEYS",
    "ConfirmationRefused",
    "DemoOrderLimits",
    "DemoOrderLimitsRefused",
    "TextScrubber",
    "confirm_execute",
    "jsonable",
    "load_demo_order_limits",
    "sha256_lf",
    "write_evidence_atomic",
]
