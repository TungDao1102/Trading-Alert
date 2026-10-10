"""Environment layer and exit-code table of the paper runtime (plan 16-22, D-01, D-13 layer 2).

Two things live here, both pure (stdlib only, no module-level side effects):

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
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum

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
