"""Environment layer and exit-code table of the paper runtime (plan 16-22, D-01, D-13 layer 2).

Three things live here, all free of module-level side effects (stdlib plus the pure
`HealthThresholds` of `src/paper/coverage.py`):

- The closed set of environment variable names the paper process may read
  (`ALLOWED_ENV_NAMES`) and the trade-key refusal (`refuse_trade_capable_env`): the paper
  process never holds a trade-capable credential, so a single variable whose name starts with
  `BINANCE_` refuses the start, even with an empty value (SC6, D040, T-16-50). Only names are
  ever reported, never values.
- The named exit-code table (`ExitCode`, `REFUSAL_CODES`) that guards against a restart loop
  (T-16-110). The compose restart policy `on-failure` restarts on any non-zero status and has
  no per-code exclusion list, so the table is what keeps a refusal from looping:

  * 0 (OK): a clean stop, or SKIPPED because the allowlist admits nothing. Not restarted.
  * 3 to 6 (refusals): trade-capable variable, configuration not ratified, no pinned epoch,
    admission or epoch mismatch. A refusal can never succeed on a retry, because only a human
    action (remove the variable, ratify the file, pin the epoch, fix the allowlist) changes the
    outcome. With `--hold-on-refusal` the process therefore stays up instead of exiting.
  * 7 (FAIL_CLOSED_RUNTIME) and 1 (the status of an uncaught exception): restartable. The
    process failed closed on a runtime condition (lost data, lost connection) that a restart
    can clear.
  * 2 (USAGE): a malformed command line, argparse's own status. Not restartable in practice
    (the command line does not change), but it is not a refusal of the start gate.

- The runtime configuration file (`RuntimeConfig`, `load_runtime_config`): every user-ratified
  value is required and none has a default in code (L-09, O-07, REV-07).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from pathlib import Path
from typing import Any

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


REFUSAL_CODES: frozenset[int] = frozenset(
    {
        int(ExitCode.TRADE_KEY_REFUSED),
        int(ExitCode.CONFIG_NOT_RATIFIED),
        int(ExitCode.NO_PINNED_EPOCH),
        int(ExitCode.ADMISSION_OR_EPOCH_MISMATCH),
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


# --------------------------------------------------------------------------- #
# The runtime configuration file: every user-ratified value is required (L-09, O-07, REV-07).
# --------------------------------------------------------------------------- #

CONFIG_VARIABLE = "PAPER_RUNTIME_CONFIG"

HEALTH_KEYS: tuple[str, ...] = (
    "max_ws_message_silence_seconds",
    "max_closed_bar_lateness_seconds",
    "continuous_uncovered_ceiling_seconds",
    "freeze_tick_grace_seconds",
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

# The only timing value that may be zero (a bar is read the instant it closes). Every other
# integer of the file is strictly positive.
_ZERO_ALLOWED = frozenset({"minute_close_lag_seconds"})


class ConfigNotRatified(Exception):
    """The runtime configuration is absent, unreadable or incomplete (exit code 4)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("runtime configuration not ratified: " + ", ".join(problems))


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

    health: HealthThresholds
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
        elif value < 0 or (value == 0 and key not in _ZERO_ALLOWED):
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
    no age or freshness key exists for them, so a file that carries one is refused.
    """
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
        health=HealthThresholds(**health),
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
    if path is None or path.strip() == "":
        raise ConfigNotRatified([CONFIG_VARIABLE])
    file = Path(path)
    if not file.is_file():
        raise ConfigNotRatified([f"{CONFIG_VARIABLE} names a file that does not exist"])
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        raise ConfigNotRatified(
            [f"{CONFIG_VARIABLE} names a file that is not valid TOML"]
        ) from None
    return parse_runtime_config(raw)
