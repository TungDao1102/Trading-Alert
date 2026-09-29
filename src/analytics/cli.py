"""Offline journal-depth report CLI (Phase 10, plan 10-12, D-01, D-03, D-04, D-05).

The single edge module of the analytics phase: it loads the evidence, decision and universe
files through `src.adapters.analytics_files`, composes the frozen `ReportInputs`, runs the pure
core (`build_journal_depth_report`, `render_markdown`, `sidecar_text`), verifies that the
Markdown and the sidecar agree, and writes exactly two files under the confined reports root.

Contract (UI-SPEC Interaction Contract):

- stdout on success is exactly four lines: `Report: <path>`, `Sidecar: <path>`,
  `Digest: sha256:<64 hex>` and `Kill gate: <STATE>`; exit 0, also for a terminal
  INSUFFICIENT_EDGE (a valid outcome, never an error).
- exit 1: the report could not be produced (nothing is written); exit 2: invalid arguments.
- The wall clock is read at most once, only when `--as-of` is omitted, inside
  `_resolve_as_of`. Every other instant is an injected argument.
- No network, no exchange access, no Telegram send, no float. Error output carries names and
  exception types only, never file contents or credentials.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import NoReturn

from src.adapters.analytics_files import (
    REPORTS_ROOT,
    BacktestEvidence,
    DecisionsFile,
    DecisionsFileError,
    EvidenceFile,
    EvidenceFileError,
    PathConfinementError,
    confine_output_dir,
    load_decisions_file,
    load_evidence_file,
    load_universe_file,
    read_protocol_text,
    scan_family_facts,
)
from src.adapters.analytics_store import read_candles
from src.analytics.clock import clock_start_from_protocol
from src.analytics.family import KillGateInputError
from src.analytics.inputs import normalize_backtest
from src.analytics.lifecycle import normalize_backtest_lifecycle, normalize_paper_lifecycle
from src.analytics.no_trade import no_trade_from_paper
from src.analytics.render import render_markdown, report_file_stem
from src.analytics.render_common import RenderError
from src.analytics.render_sidecar import build_sidecar, sidecar_text, verify_render
from src.analytics.report import (
    EvidenceInputs,
    InputNote,
    JournalDepthReport,
    ReportInputs,
    build_journal_depth_report,
)
from src.analytics.stats import r_value
from src.analytics.types import (
    DEFAULT_BASE_SEED,
    DEFAULT_RESAMPLES,
    MIN_RESAMPLES,
    AnalyticsInputError,
    EvidenceKind,
    OutcomeContext,
    TradeOutcome,
)
from src.backtest.simulator import TradeRecord
from src.core.types import Candle
from src.paper.journal import PaperRecord

__all__ = ["CliArgs", "main", "parse_args"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DECISIONS = _REPO_ROOT / "docs" / "research" / "kill_gate_decisions.json"
_DEFAULT_RAW_ROOT = _REPO_ROOT / "data" / "raw"
_DEFAULT_REPORTS_ROOT = _REPO_ROOT / REPORTS_ROOT
_SHEETS_ROOT = _REPO_ROOT / "docs" / "research" / "families"

_FAILURE_TAIL = (
    "No file was written. Fix the cause and re-run journal-report.ps1 with the same -AsOf."
)

ClockFn = Callable[[], datetime]


class _UsageError(Exception):
    """Invalid command-line arguments (exit code 2)."""


class _RenderVerificationError(Exception):
    """The Markdown and the sidecar disagree; carries fixed-vocabulary problem strings only."""


class _ArgumentParser(argparse.ArgumentParser):
    """argparse with an error handler that raises instead of exiting with a usage dump."""

    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


@dataclass(frozen=True)
class CliArgs:
    """Parsed command line; `as_of` is None when the clock must be read at the edge."""

    as_of: datetime | None
    out_dir: Path | None
    record: bool
    universe: Path | None
    evidence: Path | None
    decisions: Path
    raw_root: Path
    resamples: int
    seed: int
    no_db: bool
    reports_root: Path


# --------------------------------------------------------------------------- #
# Argument parsing (no clock, no environment)
# --------------------------------------------------------------------------- #


def _parse_as_of(text: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _UsageError("--as-of must be an ISO-8601 timestamp with a UTC offset") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _UsageError("--as-of must carry a UTC offset (a naive timestamp is refused)")
    return parsed.astimezone(UTC)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="python -m src.analytics.cli",
        description=(
            "Generate the offline journal-depth and kill-gate report (Markdown plus JSON "
            "sidecar) under the reports root. Read-only unless --record is given."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--as-of", dest="as_of", help="ISO-8601 timestamp with a UTC offset")
    parser.add_argument("--out-dir", dest="out_dir", type=Path, help="directory under the root")
    parser.add_argument("--record", action="store_true", help="append one KILL_GATE_EVALUATION")
    parser.add_argument("--universe", type=Path, help="research-universe file")
    parser.add_argument("--evidence", type=Path, help="analytics evidence file")
    parser.add_argument("--decisions", type=Path, default=_DEFAULT_DECISIONS)
    parser.add_argument("--raw-root", dest="raw_root", type=Path, default=_DEFAULT_RAW_ROOT)
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_BASE_SEED)
    parser.add_argument("--no-db", dest="no_db", action="store_true", help="never read a database")
    parser.add_argument(
        "--reports-root",
        dest="reports_root",
        type=Path,
        default=_DEFAULT_REPORTS_ROOT,
        help="confinement root for output (test hook; default <repo>/data/reports)",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CliArgs:
    """Parse `argv`; raises `_UsageError` (exit 2) on anything invalid."""
    namespace = _build_parser().parse_args(None if argv is None else list(argv))
    if namespace.resamples < MIN_RESAMPLES:
        raise _UsageError(f"--resamples must be an integer >= {MIN_RESAMPLES}")
    return CliArgs(
        as_of=None if namespace.as_of is None else _parse_as_of(namespace.as_of),
        out_dir=namespace.out_dir,
        record=namespace.record,
        universe=namespace.universe,
        evidence=namespace.evidence,
        decisions=namespace.decisions,
        raw_root=namespace.raw_root,
        resamples=namespace.resamples,
        seed=namespace.seed,
        no_db=namespace.no_db,
        reports_root=namespace.reports_root,
    )


def _resolve_as_of(args: CliArgs, now_fn: ClockFn | None) -> datetime:
    """The report instant: `--as-of`, else the one wall-clock read of the whole program."""
    if args.as_of is not None:
        return args.as_of
    moment = now_fn() if now_fn is not None else datetime.now(UTC)
    return moment.astimezone(UTC).replace(microsecond=0)


# --------------------------------------------------------------------------- #
# Input composition (pure functions over the loaded files)
# --------------------------------------------------------------------------- #


def _candles_for(
    outcomes: Sequence[TradeOutcome], raw_root: Path
) -> tuple[dict[str, tuple[Candle, ...]], tuple[InputNote, ...]]:
    """1m candles per symbol covering each outcome window, read from the immutable store."""
    windows: dict[str, tuple[datetime, datetime]] = {}
    for outcome in outcomes:
        if outcome.entry_time_utc is None or outcome.exit_time_utc is None:
            continue
        start, end = windows.get(outcome.symbol, (outcome.entry_time_utc, outcome.exit_time_utc))
        windows[outcome.symbol] = (
            min(start, outcome.entry_time_utc),
            max(end, outcome.exit_time_utc),
        )
    if not raw_root.is_dir():
        return {}, ()  # no store: the core reports NO_1M_COVERAGE; nothing is fabricated
    candles: dict[str, tuple[Candle, ...]] = {}
    notes: list[InputNote] = []
    for symbol in sorted(windows):
        start, end = windows[symbol]
        try:
            result = read_candles(raw_root, symbol, start, end)
        except ValueError:
            raise AnalyticsInputError("a trade symbol is not valid for a candle read") from None
        candles[symbol] = result.candles
        if result.rejected > 0:
            notes.append(InputNote(f"candles:{symbol}", "MALFORMED_ROW", result.rejected))
    return candles, tuple(notes)


def _backtest_inputs(entries: Sequence[BacktestEvidence], raw_root: Path) -> EvidenceInputs:
    ordered = sorted(entries, key=lambda entry: entry.experiment.experiment_id)
    experiment_ids = [entry.experiment.experiment_id for entry in ordered]
    if len(set(experiment_ids)) != len(experiment_ids):
        raise AnalyticsInputError("duplicate experiment_id across evidence entries")
    trades: list[TradeRecord] = []
    contexts: dict[str, OutcomeContext] = {}
    seen: set[str] = set()
    for entry in ordered:
        for trade in entry.trades:
            if trade.trade_id in seen:
                raise AnalyticsInputError(
                    f"duplicate trade_id {trade.trade_id!r} across experiments"
                )
            seen.add(trade.trade_id)
            trades.append(trade)
        contexts.update(entry.contexts)
    normalized = normalize_backtest(trades, contexts)
    realized_r: dict[str, Decimal] = {}
    for outcome in normalized.outcomes:
        value = r_value(outcome.realized_pnl, outcome.realized_risk)
        if outcome.signal_id is not None and value is not None:
            realized_r[outcome.signal_id] = value
    candles, notes = _candles_for(normalized.outcomes, raw_root)
    return EvidenceInputs(
        kind=EvidenceKind.BACKTEST,
        outcomes=normalized.outcomes,
        lifecycle=normalize_backtest_lifecycle(normalized.outcomes),
        no_trades=normalized.rejects,
        candles_by_symbol=candles,
        realized_r_by_signal=realized_r,
        experiments=tuple(entry.experiment for entry in ordered),
        notes=notes,
    )


def _paper_inputs(records: Sequence[PaperRecord]) -> EvidenceInputs:
    return EvidenceInputs(
        kind=EvidenceKind.PAPER,
        lifecycle=normalize_paper_lifecycle(records),
        no_trades=tuple(no_trade_from_paper(records)),
        paper_epoch_ids=tuple(sorted({record.epoch_id for record in records})),
    )


def _research_symbols(args: CliArgs, evidence: EvidenceFile | None) -> tuple[str, ...]:
    if args.universe is not None:
        return load_universe_file(args.universe)
    return () if evidence is None else evidence.research_universe


def _build_inputs(args: CliArgs, as_of: datetime) -> ReportInputs:
    decisions: DecisionsFile = load_decisions_file(args.decisions)
    evidence = None if args.evidence is None else load_evidence_file(args.evidence)
    entries = () if evidence is None else evidence.backtest
    scan = scan_family_facts(
        sheets_root=_SHEETS_ROOT,
        decisions=decisions,
        experiments=tuple(entry.experiment for entry in entries),
        flags_by_experiment={entry.experiment.experiment_id: entry.flags for entry in entries},
    )
    return ReportInputs(
        as_of_utc=as_of,
        backtest=_backtest_inputs(entries, args.raw_root),
        paper=_paper_inputs(() if evidence is None else evidence.paper),
        live=EvidenceInputs(kind=EvidenceKind.LIVE),
        clock=clock_start_from_protocol(read_protocol_text(_REPO_ROOT)),
        research_symbols=_research_symbols(args, evidence),
        families=scan.families,
        family_gate_facts=dict(scan.gate_facts),
        resets=decisions.resets,
    )


# --------------------------------------------------------------------------- #
# Rendering and the only file writes
# --------------------------------------------------------------------------- #


def _render_pair(report: JournalDepthReport) -> tuple[str, bytes, bytes]:
    """(file stem, Markdown bytes, sidecar bytes), verified to agree before any write."""
    markdown = render_markdown(report)
    sidecar = sidecar_text(build_sidecar(report, markdown))
    problems = verify_render(markdown, sidecar, report=report)
    if problems:
        raise _RenderVerificationError("; ".join(problems))
    return report_file_stem(report), markdown.encode("utf-8"), sidecar.encode("utf-8")


def _write_pair(out_dir: Path, stem: str, markdown: bytes, sidecar: bytes) -> tuple[Path, Path]:
    """Write both files as raw bytes; a failed write removes any file of this pair."""
    report_path = out_dir / f"{stem}.md"
    sidecar_path = out_dir / f"{stem}.json"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(markdown)
        sidecar_path.write_bytes(sidecar)
    except OSError:
        report_path.unlink(missing_ok=True)
        sidecar_path.unlink(missing_ok=True)
        raise
    return report_path, sidecar_path


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

_EXPECTED_FAILURES = (
    EvidenceFileError,
    DecisionsFileError,
    PathConfinementError,
    AnalyticsInputError,
    KillGateInputError,
    RenderError,
    _RenderVerificationError,
    OSError,
)


def _reason(exc: Exception) -> str:
    """One-line failure reason; file-system errors are reduced to their type name."""
    if isinstance(exc, OSError):
        return f"file access failed ({type(exc).__name__})"
    if isinstance(exc, _RenderVerificationError):
        return f"rendered output failed verification ({exc})"
    return " ".join(str(exc).split()).rstrip(".")


def _fail(reason: str) -> int:
    print(f"Report not produced: {reason}. {_FAILURE_TAIL}", file=sys.stderr)
    return 1


def _run(args: CliArgs, now_fn: ClockFn | None) -> int:
    if args.record:
        raise _UsageError("--record requires a database (DATABASE_URL set and --no-db absent)")
    as_of = _resolve_as_of(args, now_fn)
    out_dir = confine_output_dir(args.out_dir, args.reports_root).resolve()
    report = build_journal_depth_report(
        _build_inputs(args, as_of), base_seed=args.seed, resamples=args.resamples
    )
    stem, markdown, sidecar = _render_pair(report)
    report_path, sidecar_path = _write_pair(out_dir, stem, markdown, sidecar)
    print(f"Report: {report_path}")
    print(f"Sidecar: {sidecar_path}")
    print(f"Digest: sha256:{report.digest()}")
    print(f"Kill gate: {report.kill_gate.verdict.state.value}")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    now_fn: ClockFn | None = None,
    session_factory_fn: Callable[[str], object] | None = None,
) -> int:
    """Run the CLI; returns the process exit code (0 produced, 1 not produced, 2 usage)."""
    del session_factory_fn  # wired to the read-only database branch by the next task
    try:
        args = parse_args(argv)
        return _run(args, now_fn)
    except SystemExit as exc:  # argparse --help
        return exc.code if isinstance(exc.code, int) else 2
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except _EXPECTED_FAILURES as exc:
        return _fail(_reason(exc))


if __name__ == "__main__":
    raise SystemExit(main())
