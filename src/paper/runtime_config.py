"""Environment layer and exit-code table of the paper runtime (plan 16-22, D-01, D-13 layer 2).

Three things live here, all free of module-level side effects (stdlib plus the pure
`HealthThresholds` of `src/paper/coverage.py`):

- The closed set of environment variable names the paper process may read
  (`ALLOWED_ENV_NAMES`) and the trade-key refusal (`refuse_trade_capable_env`): the paper
  process never holds a trade-capable credential, so a single variable whose name starts with
  `BINANCE_` refuses the start, even with an empty value (SC6, D040, T-16-50). Only names are
  ever reported, never values.
- The named exit-code table (`ExitCode`, `REFUSAL_CODES`) that guards against a restart loop
  (T-16-110). A compose restart policy has no per-code exclusion list (`on-failure` restarts any
  non-zero status, `unless-stopped` restarts any exit that no `docker stop` preceded), so the
  table and the hold are what keep a refusal from looping:

  * 0 (OK): a stop the operator requested, the end of a hold, the one-shot `--pin-epoch`, the
    `--healthcheck` probe, or SKIPPED (the allowlist admits nothing) without `--hold-on-refusal`.
    No path of the service command relies on exit 0 to stay down (16-DEC-RESTART-POLICY).
  * 3 to 6 and 8 (refusals): trade-capable variable, configuration not ratified, no pinned epoch,
    admission or epoch mismatch, and another runtime holding the instance lease of this database
    (B1-WR-07). A refusal can never succeed on a retry, because only a human action (remove the
    variable, ratify the file, pin the epoch, fix the allowlist, stop the other runtime) changes
    the outcome. With `--hold-on-refusal` the process therefore stays up instead of exiting,
    held and non-operational: it writes no record, starts no loop and leaves an explicit held
    marker that makes the healthcheck report unhealthy (`src/paper/held_marker.py`). SKIPPED
    holds the same way under the flag (16-55 Q1 = A).
  * 7 (FAIL_CLOSED_RUNTIME) and 1 (the status of an uncaught exception): restartable. The
    process failed closed on a runtime condition (lost data, lost connection, a lost instance
    lease) that a restart can clear.
  * 2 (USAGE): a malformed command line, argparse's own status, or `--pin-epoch` together with
    `--hold-on-refusal` (the one-shot pin never holds). Not restartable in practice (the command
    line does not change), but it is not a refusal of the start gate.

- The runtime configuration file (`RuntimeConfig`, `load_runtime_config`): every user-ratified
  value is required and none has a default in code (L-09, O-07, REV-07). Every integer is
  strictly positive; `minute_close_lag_seconds` is no exception since plan 16-56 (owner decision
  16-DEC-CLOSE-LAG-ZERO, B1-WR-10: the loader and the minute poller accept one domain). The file in
  force is `config/paper/paper-runtime-v2.toml`, which adds the owner's
  `[health] feed_silence_timeout_seconds` (16-DEC-WS-WATCHDOG); `paper-runtime-v1.toml` is the
  historical version and is refused for the missing key.

- The configuration identity (plan 16-57, owner decision 16-DEC-CONFIG-PIN, option
  `refuse-on-value-change`): `config_identity` is the SHA-256 of the canonical form of the
  validated `RuntimeConfig`, never of the file bytes. The loader validates the complete schema
  first (a missing or unknown key, or an unknown section, refuses with exit 4 and never reaches
  the hash) and injects no default. Every key of every section is in the form; integers stay
  integers, decimals are their canonical text (`canonical_decimal_text`, so "0.005" and "0.0050"
  are one value), symbols keep their configured order, and the canonical serializer sorts the
  keys. A comment, whitespace, blank-line or key-order edit leaves the identity unchanged; any
  changed value changes it. The raw file SHA-256 is recorded beside it as provenance only
  (`ConfigProvenance`); the guard never compares it.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from pathlib import Path
from typing import Any

from src.domain.canonical import canonical_decimal_text, sha256_hex
from src.paper.coverage import HealthThresholds

TRADE_KEY_PREFIX = "BINANCE_"

ALLOWED_ENV_NAMES: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "DATABASE_URL_SYNC",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_AUTHORIZED_CHAT_ID",
        "TELEGRAM_AUTHORIZED_USER_IDS",
        "PAPER_RUNTIME_CONFIG",
        "PAPER_STRATEGY_ID",
        "PAPER_PARAMETER_SET_ID",
    }
)


class ExitCode(IntEnum):
    """Process exit statuses of `python -m src.paper.runtime` (see the module docstring)."""

    OK = 0
    USAGE = 2
    TRADE_KEY_REFUSED = 3
    CONFIG_NOT_RATIFIED = 4
    NO_PINNED_EPOCH = 5
    ADMISSION_OR_EPOCH_MISMATCH = 6
    FAIL_CLOSED_RUNTIME = 7
    INSTANCE_LEASE_HELD = 8


REFUSAL_CODES: frozenset[int] = frozenset(
    {
        int(ExitCode.TRADE_KEY_REFUSED),
        int(ExitCode.CONFIG_NOT_RATIFIED),
        int(ExitCode.NO_PINNED_EPOCH),
        int(ExitCode.ADMISSION_OR_EPOCH_MISMATCH),
        int(ExitCode.INSTANCE_LEASE_HELD),
    }
)


def refuse_trade_capable_env(environ: Mapping[str, str]) -> list[str]:
    """Names (sorted, never values) of every variable that starts with `BINANCE_`.

    Presence alone refuses: an empty value is still a trade-capable name in the paper
    environment (D-13 layer 2). The match is case-sensitive, like the environment on Linux.
    """
    return sorted(name for name in environ if name.startswith(TRADE_KEY_PREFIX))


def read_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The allowed variables of `environ`, nothing else (an unrelated variable is ignored)."""
    return {name: environ[name] for name in sorted(ALLOWED_ENV_NAMES) if name in environ}


_USER_IDS_RULE = "TELEGRAM_AUTHORIZED_USER_IDS (must be comma-separated positive integers)"


def parse_authorized_user_ids(text: str) -> frozenset[int]:
    """The Telegram user allow-list of `TELEGRAM_AUTHORIZED_USER_IDS` (Phase 23, D-02).

    Comma-separated positive integers in plain ASCII digits: surrounding blanks are stripped, an
    empty item (leading, trailing or doubled comma), a sign, a leading zero, a non-ASCII digit, a
    decimal point or a duplicate refuses the whole value. The `ValueError` names the variable only,
    never the input (the list is secret-class configuration).
    """
    members: set[int] = set()
    for raw in text.split(","):
        item = raw.strip(" \t\r\n")
        if not item or not item.isascii() or not item.isdigit() or item.startswith("0"):
            raise ValueError(_USER_IDS_RULE)
        user_id = int(item)
        if user_id in members:
            raise ValueError(_USER_IDS_RULE)
        members.add(user_id)
    return frozenset(members)


# --------------------------------------------------------------------------- #
# The runtime configuration file: every user-ratified value is required (L-09, O-07, REV-07).
# --------------------------------------------------------------------------- #

CONFIG_VARIABLE = "PAPER_RUNTIME_CONFIG"

HEALTH_KEYS: tuple[str, ...] = (
    "max_ws_message_silence_seconds",
    "max_closed_bar_lateness_seconds",
    "continuous_uncovered_ceiling_seconds",
    "freeze_tick_grace_seconds",
    "feed_silence_timeout_seconds",
)
TIMING_KEYS: tuple[str, ...] = (
    "sibling_4h_wait_seconds",
    "constraint_snapshot_ttl_seconds",
    "exchange_info_refresh_seconds",
    "minute_poll_interval_seconds",
    "minute_close_lag_seconds",
    "healthcheck_max_bar_age_seconds",
    "rest_backfill_depth_bars",
)
ACCOUNT_KEYS: tuple[str, ...] = ("initial_equity", "risk_rate")
SCOPE_KEYS: tuple[str, ...] = ("symbols",)

REQUIRED_KEYS: Mapping[str, tuple[str, ...]] = {
    "health": HEALTH_KEYS,
    "timing": TIMING_KEYS,
    "account": ACCOUNT_KEYS,
    "scope": SCOPE_KEYS,
}


class ConfigNotRatified(Exception):
    """The runtime configuration is absent, unreadable or incomplete (exit code 4)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("runtime configuration not ratified: " + ", ".join(problems))


@dataclass(frozen=True)
class RuntimeHealthConfig(HealthThresholds):
    """The `[health]` section: the coverage thresholds plus the in-process watchdog bound.

    `feed_silence_timeout_seconds` (plan 16-56, 16-DEC-WS-WATCHDOG) is how long the live loop
    accepts no message on the market connection before it enters the bounded recovery, and,
    when no message has arrived when the bound expires again, fails closed. It is distinct from
    `max_ws_message_silence_seconds` (coverage evidence) and `healthcheck_max_bar_age_seconds`.
    Required, strictly positive, no default.
    """

    feed_silence_timeout_seconds: int

    def __post_init__(self) -> None:
        super().__post_init__()
        value = self.feed_silence_timeout_seconds
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("feed_silence_timeout_seconds must be a positive integer")


@dataclass(frozen=True)
class TimingConfig:
    """Seconds (and one bar count) the user owns for waits, polls and backfill (O-07, O-09)."""

    sibling_4h_wait_seconds: int
    constraint_snapshot_ttl_seconds: int
    exchange_info_refresh_seconds: int
    minute_poll_interval_seconds: int
    minute_close_lag_seconds: int
    healthcheck_max_bar_age_seconds: int
    rest_backfill_depth_bars: int


@dataclass(frozen=True)
class AccountConfig:
    """The paper account inputs of the risk verdict, as exact decimals (never floats)."""

    initial_equity: Decimal
    risk_rate: Decimal


@dataclass(frozen=True)
class RuntimeConfig:
    """Every value of the ratified runtime configuration file. No field has a default."""

    health: RuntimeHealthConfig
    timing: TimingConfig
    account: AccountConfig
    symbols: tuple[str, ...]


def _read_ints(
    section: Mapping[str, Any], name: str, keys: tuple[str, ...], problems: list[str]
) -> dict[str, int]:
    """Every key of `keys` as an integer; invalid or absent keys are added to `problems`."""
    out: dict[str, int] = {}
    for key in keys:
        label = f"{name}.{key}"
        if key not in section:
            problems.append(label)
            continue
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int):
            problems.append(f"{label} (must be an integer)")
        elif value <= 0:
            problems.append(f"{label} (must be a positive integer)")
        else:
            out[key] = value
    return out


def _read_decimal(section: Mapping[str, Any], key: str, problems: list[str]) -> Decimal | None:
    """A positive finite decimal written as a TOML string (a TOML float would lose digits)."""
    label = f"account.{key}"
    if key not in section:
        problems.append(label)
        return None
    value = section[key]
    if not isinstance(value, str):
        problems.append(f"{label} (must be a decimal written as a string)")
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        problems.append(f"{label} (not a decimal)")
        return None
    if not parsed.is_finite() or parsed <= 0:
        problems.append(f"{label} (must be a positive finite decimal)")
        return None
    return parsed


def _read_symbols(section: Mapping[str, Any], problems: list[str]) -> tuple[str, ...]:
    if "symbols" not in section:
        problems.append("scope.symbols")
        return ()
    raw = section["symbols"]
    valid = (
        isinstance(raw, list)
        and len(raw) > 0
        and all(isinstance(item, str) and item != "" and item.strip() == item for item in raw)
        and len(set(raw)) == len(raw)
    )
    if not valid:
        problems.append("scope.symbols (must be a non-empty list of distinct symbol names)")
        return ()
    return tuple(raw)


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = raw.get(name)
    return section if isinstance(section, dict) else {}


def _refuse_unknown_keys(raw: Mapping[str, Any], problems: list[str]) -> None:
    """A key no code reads is refused: an unused threshold is a value nobody ratified for a use.

    This is also how the recorded Q-D decision (REST backfill bars are history only) is honoured:
    no age or freshness key exists for them, so a file that carries one is refused. A top-level
    key or section outside the four sections is refused too (plan 16-57: nothing outside the
    schema is silently ignored, 16-DEC-CONFIG-PIN).
    """
    for name in sorted(set(raw) - set(REQUIRED_KEYS)):
        problems.append(f"{name} (unknown section or top-level key: nothing reads it)")
    for name, keys in REQUIRED_KEYS.items():
        for key in sorted(set(_section(raw, name)) - set(keys)):
            problems.append(f"{name}.{key} (unknown key: nothing reads it)")


def parse_runtime_config(raw: Mapping[str, Any]) -> RuntimeConfig:
    """Validate a parsed TOML document; every key of every section is required.

    A missing section makes each of its keys missing, so the error names exactly what the file
    still has to carry. A key that is not part of the contract is refused too.

    Raises:
        ConfigNotRatified: naming every missing or invalid `<section>.<key>`.
    """
    problems: list[str] = []
    health = _read_ints(_section(raw, "health"), "health", HEALTH_KEYS, problems)
    timing = _read_ints(_section(raw, "timing"), "timing", TIMING_KEYS, problems)
    account = _section(raw, "account")
    equity = _read_decimal(account, "initial_equity", problems)
    risk_rate = _read_decimal(account, "risk_rate", problems)
    symbols = _read_symbols(_section(raw, "scope"), problems)
    _refuse_unknown_keys(raw, problems)
    if problems or equity is None or risk_rate is None:
        raise ConfigNotRatified(problems)
    return RuntimeConfig(
        health=RuntimeHealthConfig(**health),
        timing=TimingConfig(**timing),
        account=AccountConfig(initial_equity=equity, risk_rate=risk_rate),
        symbols=symbols,
    )


def load_runtime_config(path: str | None) -> RuntimeConfig:
    """Load the ratified runtime configuration file named by `PAPER_RUNTIME_CONFIG`.

    There is no default file and no default value: an unset variable, a missing or unparseable
    file, or any absent or invalid key refuses the start.

    Raises:
        ConfigNotRatified: with the problems named (never the file contents).
    """
    config, _provenance = load_runtime_config_with_provenance(path)
    return config


# --------------------------------------------------------------------------- #
# The configuration identity (plan 16-57, 16-DEC-CONFIG-PIN, B1-WR-08, REV-07).
# --------------------------------------------------------------------------- #

CONFIG_IDENTITY_SCHEMA = "paper-runtime-config-identity/1"

# Payload keys of the configuration identity in EPOCH_PINNED and RUNTIME_START records.
CONFIG_IDENTITY_FIELD = "config_identity_sha256"
CONFIG_PROVENANCE_FIELD = "config_file_provenance"


def config_identity_payload(config: RuntimeConfig) -> dict[str, Any]:
    """The canonical form of every effective value, section by section, in schema key order.

    Built from the validated object only, never from the file: every key of `REQUIRED_KEYS` is
    present (no default can be injected, the loader refused any missing key), integers stay
    integers, decimals are their canonical text, and the symbols keep their configured order.
    """
    return {
        "schema": CONFIG_IDENTITY_SCHEMA,
        "health": {key: getattr(config.health, key) for key in HEALTH_KEYS},
        "timing": {key: getattr(config.timing, key) for key in TIMING_KEYS},
        "account": {
            key: canonical_decimal_text(getattr(config.account, key)) for key in ACCOUNT_KEYS
        },
        "scope": {"symbols": list(config.symbols)},
    }


def config_identity(config: RuntimeConfig) -> str:
    """SHA-256 (hex) of `config_identity_payload` under the canonical serializer.

    This is the comparison of the owner's rule (16-DEC-CONFIG-PIN): the pin and every start
    record it, and a start whose identity differs from the pinned one is refused with exit 6.
    """
    return sha256_hex(config_identity_payload(config))


@dataclass(frozen=True)
class ConfigProvenance:
    """What the pin and every start record about the configuration in force.

    `identity` is `config_identity` of the validated values (the guard compares it). `file_sha256`
    is the SHA-256 of the raw file bytes and `path` the value of `PAPER_RUNTIME_CONFIG`: both are
    forensic provenance only and are never compared.
    """

    identity: str
    file_sha256: str
    path: str

    def record_fields(self) -> dict[str, Any]:
        """The payload fields of EPOCH_PINNED and RUNTIME_START (provenance labelled apart)."""
        return {
            CONFIG_IDENTITY_FIELD: self.identity,
            CONFIG_PROVENANCE_FIELD: {"file_sha256": self.file_sha256, "path": self.path},
        }


def load_runtime_config_with_provenance(
    path: str | None,
) -> tuple[RuntimeConfig, ConfigProvenance]:
    """`load_runtime_config` plus the identity of its values and the raw-file provenance.

    The file is read once: the bytes that were parsed are the bytes hashed for provenance. The
    identity is computed from the validated object, after every refusal.

    Raises:
        ConfigNotRatified: with the problems named (never the file contents).
    """
    if path is None or path.strip() == "":
        raise ConfigNotRatified([CONFIG_VARIABLE])
    file = Path(path)
    if not file.is_file():
        raise ConfigNotRatified([f"{CONFIG_VARIABLE} names a file that does not exist"])
    try:
        data = file.read_bytes()
        raw = tomllib.loads(data.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        raise ConfigNotRatified(
            [f"{CONFIG_VARIABLE} names a file that is not valid TOML"]
        ) from None
    config = parse_runtime_config(raw)
    provenance = ConfigProvenance(
        identity=config_identity(config),
        file_sha256=hashlib.sha256(data).hexdigest(),
        path=path,
    )
    return config, provenance
