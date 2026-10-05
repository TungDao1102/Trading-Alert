"""Local real-data smoke run of the v2 backtest simulator (Phase 14, plan 14-14).

Run from the repository root::

    .venv/Scripts/python scripts/smoke_backtest_realdata.py --symbol BTCUSDT --days 90 \\
        --end-day 2026-10-01 --constraints-json constraints.json

One symbol, one explicit closed-UTC-day window, one lazy ``ParquetMinuteSource``. The
case is built once, ``simulator.run`` is called twice on it, and each run prints
``key=value`` lines: ``runtime_seconds``, ``tracemalloc_peak_bytes`` (Python heap peak),
``rss_peak`` (OS peak resident set where the stdlib exposes it, else ``unavailable``),
``trade_count``, ``end_of_data_count``, ``no_trade_counts`` (compact JSON), ``dataset_id``
and ``digest`` (sha256 over ``json.dumps(output, sort_keys=True)``). Exit codes:

    0  both runs completed and the two digests match
    1  the digests differ (a determinism failure, D-26)
    2  usage error: bad or missing argument, or no constraint source (fail closed, D-17)
    3  the store, the constraint source or the run failed (exception type name only)

The window comes only from ``--end-day`` and ``--days``; this script never derives a data
window from the wall clock, so a rerun reads the same files (D-26). ``time.perf_counter``
measures durations only. Constraint history is either a JSON file (a list of rows, or an
object with a ``constraint_history`` list) or the database named by an environment variable
(``--database-url-env``). The URL is read once and is never printed: a database failure
prints the exception type name only (T-14-27). Reads no network other than that database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import tracemalloc
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.backtest import simulator  # noqa: E402
from src.backtest.costs import cost_slice  # noqa: E402
from src.data.case_input import build_case_input_data  # noqa: E402
from src.data.minute_source import SYMBOL_RE, ParquetMinuteSource  # noqa: E402
from src.domain.registry import load_parameter_set  # noqa: E402

EXIT_OK = 0
EXIT_DIGEST_MISMATCH = 1
EXIT_USAGE = 2
EXIT_FAILURE = 3

_RUNS = 2
DB_CONNECT_TIMEOUT_SECONDS = 10
_CONSTRAINT_KEYS = "constraint_history"


class _UsageError(Exception):
    """A bad argument or a missing constraint source (exit 2)."""


class _DatabaseError(Exception):
    """A database read failed; the message is the exception type name only (exit 3)."""


class _ArgumentParser(argparse.ArgumentParser):
    """argparse that raises instead of exiting, so `main` returns the exit code."""

    def error(self, message: str) -> Any:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="smoke_backtest_realdata.py",
        description="Local smoke run of the v2 backtest simulator on published data.",
    )
    parser.add_argument("--symbol", required=True, help="USDT-M symbol, for example BTCUSDT")
    parser.add_argument("--days", type=int, required=True, help="number of whole UTC days (>= 1)")
    parser.add_argument(
        "--end-day", required=True, help="last UTC day included, YYYY-MM-DD (never the clock)"
    )
    parser.add_argument("--raw-root", default="data/raw", help="published store root")
    parser.add_argument("--strategy-id", default="trend-pullback")
    parser.add_argument("--parameter-set-id", default="baseline-v5")
    parser.add_argument("--equity", default="1000", help="account equity, a Decimal string")
    parser.add_argument("--risk-rate", default="0.005", help="risk rate, a Decimal string")
    parser.add_argument("--constraints-json", default=None, help="exported constraint history")
    parser.add_argument(
        "--database-url-env",
        default=None,
        help="name of an environment variable that holds the database URL",
    )
    return parser


def _decimal(value: str, name: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise _UsageError(f"{name} is not a decimal number") from None
    if not parsed.is_finite() or parsed <= 0:
        raise _UsageError(f"{name} must be a positive finite decimal")
    return value


def _window(end_day: str, days: int) -> tuple[datetime, datetime, date]:
    """`(start_utc, end_utc, as_of_day)` for the `days` whole UTC days ending on `end_day`."""
    try:
        last = date.fromisoformat(end_day)
    except ValueError:
        raise _UsageError("--end-day must be a YYYY-MM-DD date") from None
    end_utc = datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=1)
    return end_utc - timedelta(days=days), end_utc, end_utc.date()


def _constraints_from_json(path: Path, symbol: str) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _UsageError(f"constraints file unreadable ({type(exc).__name__})") from None
    rows = loaded.get(_CONSTRAINT_KEYS) if isinstance(loaded, dict) else loaded
    if not isinstance(rows, list):
        raise _UsageError("constraints file must hold a list of rows")
    kept = [r for r in rows if isinstance(r, dict) and r.get("symbol") == symbol]
    if not kept:
        raise _UsageError(f"constraints file has no row for {symbol}")
    return kept


def _constraints_from_database(env_name: str, symbol: str) -> list[dict[str, str]]:
    """Read the constraint history; any failure reduces to its exception type name."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from src.data.metadata import read_constraint_history

    url = os.environ.get(env_name, "")
    if not url.strip():
        raise _UsageError("the database URL environment variable is unset or blank")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        engine = create_engine(
            url,
            connect_args={
                "options": "-c timezone=UTC",
                "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
            },
        )
        try:
            with Session(engine) as session:
                return read_constraint_history(session, [symbol])
        finally:
            engine.dispose()
    except Exception as exc:
        # A driver message can carry the URL (host, user, password): the type name only.
        raise _DatabaseError(f"database read failed ({type(exc).__name__})") from None


def _rss_peak() -> str:
    """Peak resident set size from `resource` on POSIX, else `unavailable`."""
    try:
        import resource
    except ImportError:
        return "unavailable"
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS bytes; the unit is recorded in the key name.
    unit = "bytes" if sys.platform == "darwin" else "kib"
    return f"{peak}{unit}"


def _digest(output: dict[str, Any]) -> str:
    text = json.dumps(output, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _report(index: int, elapsed: float, peak: int, output: dict[str, Any]) -> str:
    summary = output["run_summary"]
    no_trade = json.dumps(summary["no_trade_counts"], sort_keys=True, separators=(",", ":"))
    lines = [
        f"run={index}",
        f"runtime_seconds={elapsed:.3f}",
        f"tracemalloc_peak_bytes={peak}",
        f"rss_peak={_rss_peak()}",
        f"trade_count={len(output['trades'])}",
        f"end_of_data_count={summary['end_of_data_count']}",
        f"no_trade_counts={no_trade}",
        f"dataset_id={summary['dataset_id']}",
        f"digest={_digest(output)}",
    ]
    return "\n".join(lines)


def _execute(args: argparse.Namespace) -> int:
    if not SYMBOL_RE.fullmatch(args.symbol):
        raise _UsageError("--symbol must match ^[A-Z0-9]+USDT$")
    if args.days < 1:
        raise _UsageError("--days must be at least 1")
    equity = _decimal(args.equity, "--equity")
    risk_rate = _decimal(args.risk_rate, "--risk-rate")
    start_utc, end_utc, as_of = _window(args.end_day, args.days)
    if (args.constraints_json is None) == (args.database_url_env is None):
        raise _UsageError(
            "pass exactly one constraint source: --constraints-json or --database-url-env"
        )

    if args.constraints_json is not None:
        constraints = _constraints_from_json(Path(args.constraints_json), args.symbol)
    else:
        constraints = _constraints_from_database(args.database_url_env, args.symbol)

    try:
        parameter_set = load_parameter_set(args.strategy_id, args.parameter_set_id)
        cost_model = {key: str(value) for key, value in cost_slice(parameter_set.params).items()}
    except Exception as exc:
        raise _UsageError(f"parameter set unusable ({type(exc).__name__})") from None

    raw_root = Path(args.raw_root)
    data = build_case_input_data(
        raw_root,
        symbols=[args.symbol],
        start_utc=start_utc,
        end_utc=end_utc,
        as_of_day_utc=as_of,
    )
    case = data.to_case_input(
        strategy_id=args.strategy_id,
        strategy_version=parameter_set.strategy_version,
        parameter_set_id=args.parameter_set_id,
        account_state={"equity": equity, "risk_rate": risk_rate},
        cost_model=cost_model,
        constraint_history=constraints,
    )
    source = ParquetMinuteSource(
        raw_root, symbols=[args.symbol], start_utc=start_utc, end_utc=end_utc
    )

    digests: list[str] = []
    tracemalloc.start()
    try:
        for index in range(1, _RUNS + 1):
            tracemalloc.reset_peak()
            started = time.perf_counter()
            output = simulator.run(case, minute_source=source)
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
            print(_report(index, elapsed, peak, output), flush=True)
            digests.append(_digest(output))
    finally:
        tracemalloc.stop()

    if len(set(digests)) != 1:
        print("digests_match=false", flush=True)
        return EXIT_DIGEST_MISMATCH
    print("digests_match=true", flush=True)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        return _execute(args)
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except _DatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except SystemExit as exc:  # argparse --help
        return int(exc.code) if isinstance(exc.code, int) else EXIT_OK
    except Exception as exc:
        # Store, case or engine failure: no secret flows through these messages.
        print(f"error: run failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
