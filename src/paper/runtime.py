"""The paper process entrypoint: `python -m src.paper.runtime` (plan 16-22, D-01, L-05, D061 E).

Order of `main` (each step may end the process before the next one runs):

1. Configure redacted logging.
2. Trade-key refusal: any `BINANCE_*` name in the environment exits 3 (names only are printed).
3. Start gate: the approved allowlist is read through `allowlist_entries()` only. An empty
   allowlist logs "SKIPPED (allowlist empty)" and exits 0, before any adapter, database engine
   or Telegram application is constructed.
4. The admitted path (admission rule, epoch pin, runtime configuration) follows the user's
   decision Q-A and is not built yet.

Exit codes are the named table `ExitCode` in `src/paper/runtime_config.py`. With the opt-in
flag `--hold-on-refusal` (used by the compose service) a refusal does not exit: the process logs
it, stays up and returns the refusal code only after SIGTERM or SIGINT, so a restart policy can
never loop on a refusal. SKIPPED and restartable failures are never held.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from collections.abc import Callable, Mapping, Sequence

import structlog

from src.ops.redaction import configure_logging
from src.paper.freeze import allowlist_entries
from src.paper.runtime_config import ExitCode, refuse_trade_capable_env

SKIPPED_EVENT = "SKIPPED (allowlist empty)"


def build_parser() -> argparse.ArgumentParser:
    """The command line of the paper process (plan 16-32 parses the compose command with it)."""
    parser = argparse.ArgumentParser(
        prog="python -m src.paper.runtime",
        description="Paper runtime: once-per-process start gate, then the paper loop.",
    )
    parser.add_argument(
        "--hold-on-refusal",
        action="store_true",
        help=(
            "On a refusal (exit codes 3 to 6) log it and stay up until SIGTERM or SIGINT "
            "instead of exiting, so a restart policy cannot loop on it."
        ),
    )
    return parser


def wait_for_stop_signal() -> None:
    """Block until SIGTERM or SIGINT arrives (the production `wait_for_stop`)."""
    stop = threading.Event()

    def _handler(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    stop.wait()


def _refuse(
    code: ExitCode,
    reason: str,
    *,
    hold: bool,
    wait_for_stop: Callable[[], None],
) -> int:
    """Report a refusal on stderr and in the log; hold until stopped when asked to."""
    print(f"paper runtime refused (exit {int(code)}): {reason}", file=sys.stderr)
    structlog.get_logger().error("paper runtime refused", exit_code=int(code), reason=reason)
    if hold:
        wait_for_stop()
    return int(code)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    wait_for_stop: Callable[[], None] | None = None,
) -> int:
    """Run the paper process start gate; returns the process exit status."""
    args = build_parser().parse_args(argv)
    env: Mapping[str, str] = os.environ if environ is None else environ
    configure_logging(env)
    stopper = wait_for_stop if wait_for_stop is not None else wait_for_stop_signal

    trade_names = refuse_trade_capable_env(env)
    if trade_names:
        return _refuse(
            ExitCode.TRADE_KEY_REFUSED,
            "trade-capable variable present: " + ", ".join(trade_names),
            hold=args.hold_on_refusal,
            wait_for_stop=stopper,
        )

    if not allowlist_entries():
        structlog.get_logger().info(SKIPPED_EVENT)
        return int(ExitCode.OK)

    raise NotImplementedError(
        "admission, epoch pin and runtime configuration wait for the Q-A decision (plan 16-22)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
