"""Build the preregistered dataset manifest from the user's O-03b decision record (plan 16-37).

`python -m src.research.manifest --build --decision <record> --raw-root <root> --out <file>`
reads the `## Final values` block of the decision record (the values the user decided, nothing
else), the committed settlement evidence and the published day files, and writes the manifest
JSON. Nothing is chosen here: a missing or malformed value refuses the build, the stored
settlement bounds are recomputed from the committed evidence and must equal the bounds the
record names, and `dataset_id` is the identity the runner itself recomputes
(`run._check_manifest_against_store`). The build never freezes anything: the freeze is a commit
the user asks for, and it never reads the Holdout (the identity covers the research window only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath, PureWindowsPath

from src.backtest.semantics import (
    TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
)
from src.data.case_input import (
    ENGINE_SERIES,
    CaseInputError,
    TerminalDeclaration,
    build_case_input_data,
)
from src.domain.canonical import canonical_scalars
from src.research.manifest import (
    SAMPLES_PER_MINUTE,
    DatasetManifest,
    EvidenceFile,
    ManifestError,
    TerminalSettlement,
    load_manifest,
    manifest_hash,
)
from src.research.settlement_evidence import (
    SettlementEvidenceError,
    fraction_text,
    recompute_settlement_bounds,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VALUES_HEADING = "## Final values"
_BOUND_WINDOW = timedelta(minutes=30)
# The settlement condition text and the evidence file names are those the user decided for REEFUSDT
# (16-DEC-S-B-interval); any other symbol needs its own decision before it can be built here.
_SETTLEMENT_SYMBOLS = frozenset({"REEFUSDT"})
_EVIDENCE_ROOT = "docs/research/preregistration/evidence/terminal-settlement"
_INDEX_FILE = "B_indexPriceKlines_before_settlement.body.json"
_TRADE_FILE = "A_klines_after_settlement.body.json"
_SUPPORT_FILE = "F_indexklines_sample_day.body.json"

# The assumptions the user's S-B-interval decision records for the bounded settlement
# (16-DEC-S-B-interval.md); they are part of the hashed entry.
SETTLEMENT_CONDITION = (
    "unverified assumptions: settlement is the mean of per-second index values over "
    "08:30-09:00 UTC, 60 equal-weight samples per minute, klines serve unrevised history, "
    "rounding within one tick; the 09:00 trade candle (open = close = 0.000880, 102 trades) "
    "lies above the index bound and is not read as the settlement price"
)

REQUIRED_KEYS = (
    "universe_id",
    "symbols",
    "window_start_utc",
    "window_end_utc",
    "development_start_utc",
    "development_end_utc",
    "validation_start_utc",
    "validation_end_utc",
    "validation_folds",
    "holdout_start_utc",
    "holdout_end_utc",
    "strategy_interval",
    "context_interval",
    "data_source",
    "data_source_version",
    "excluded_periods",
    "equity",
    "risk_rate",
    "constraint_source",
    "constraint_sha256",
    "known_gaps",
)
_OPTIONAL_KEYS = ("terminal_settlements",)
_GAP_LINE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+), (?P<reason>[A-Z_]+), terminal_at_utc (?P<at>\S+), "
    r"source_url (?P<url>\S+)$"
)
_SETTLEMENT_LINE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+), price_lower (?P<lower>\S+), "
    r"price_upper (?P<upper>\S+?),?(?: \(.*\))?$"
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_decision_values(text: str) -> dict[str, str]:
    """The `key: value` lines of the first fenced block under `## Final values`.

    A repeated key, a line without `: ` or a missing block refuses the build.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip().startswith(_VALUES_HEADING))
    except StopIteration:
        raise ManifestError(f"the decision record has no {_VALUES_HEADING!r} section") from None
    fence_open = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("```")), None)
    if fence_open is None:
        raise ManifestError("the final values section has no fenced block")
    fence_close = next(
        (i for i in range(fence_open + 1, len(lines)) if lines[i].startswith("```")), None
    )
    if fence_close is None:
        raise ManifestError("the final values fenced block is not closed")
    values: dict[str, str] = {}
    for raw in lines[fence_open + 1 : fence_close]:
        if not raw.strip():
            continue
        key, separator, value = raw.partition(": ")
        if not separator or not key or key != key.strip():
            raise ManifestError(f"a final values line is not 'key: value': {raw[:60]!r}")
        if key in values:
            raise ManifestError(f"final values repeat the key {key!r}")
        values[key] = value.strip()
    return values


def _require(values: Mapping[str, str]) -> None:
    allowed = set(REQUIRED_KEYS) | set(_OPTIONAL_KEYS)
    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        raise ManifestError(f"the decision record does not hold the value(s) {missing}")
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ManifestError(f"the decision record holds unregistered key(s) {unknown}")


def _instant(values: Mapping[str, str], key: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(values[key])
    except ValueError:
        raise ManifestError(f"{key} is not an ISO-8601 instant") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ManifestError(f"{key} must be a UTC instant")
    return parsed


def _decimal(values: Mapping[str, str], key: str) -> Decimal:
    try:
        return Decimal(values[key])
    except InvalidOperation:
        raise ManifestError(f"{key} is not a decimal") from None


def _declarations(values: Mapping[str, str]) -> tuple[TerminalDeclaration, ...]:
    text = values["known_gaps"]
    if text.strip().lower() in {"none", "[]"}:
        return ()
    out: list[TerminalDeclaration] = []
    for part in text.split(" | "):
        match = _GAP_LINE.match(part.strip())
        if match is None:
            raise ManifestError(
                "known_gaps must read 'SYMBOL, REASON, terminal_at_utc <instant>, source_url <url>'"
            )
        try:
            at = datetime.fromisoformat(match["at"])
            out.append(
                TerminalDeclaration(
                    symbol=match["symbol"],
                    reason=match["reason"],
                    terminal_at_utc=at,
                    source_url=match["url"],
                )
            )
        except (ValueError, CaseInputError) as exc:
            raise ManifestError(f"known_gaps entry refused: {exc}") from None
    return tuple(out)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ManifestError(f"evidence file unreadable ({type(exc).__name__})") from None


def build_terminal_settlement(
    *,
    declaration: TerminalDeclaration,
    tick: Decimal,
    expected_lower: Decimal,
    expected_upper: Decimal,
    repo_root: Path,
) -> TerminalSettlement:
    """The bounded settlement entry of one declared symbol, recomputed from committed evidence."""
    if declaration.symbol not in _SETTLEMENT_SYMBOLS:
        raise ManifestError(
            f"no settlement evidence or condition is decided for {declaration.symbol}"
        )
    base = f"{_EVIDENCE_ROOT}/{declaration.symbol}"
    index_path, trade_path, support_path = (
        f"{base}/{_INDEX_FILE}",
        f"{base}/{_TRADE_FILE}",
        f"{base}/{_SUPPORT_FILE}",
    )
    window_start = declaration.terminal_at_utc - _BOUND_WINDOW
    try:
        recomputed = recompute_settlement_bounds(
            index_klines=(repo_root / index_path).read_bytes(),
            trade_kline=(repo_root / trade_path).read_bytes(),
            window_start_utc=window_start,
            terminal_at_utc=declaration.terminal_at_utc,
            tick=tick,
        )
    except (OSError, SettlementEvidenceError) as exc:
        raise ManifestError(
            f"the committed evidence of {declaration.symbol} does not recompute: {exc}"
        ) from None
    if (recomputed.price_lower, recomputed.price_upper) != (expected_lower, expected_upper):
        raise ManifestError(
            f"the bounds recomputed from the evidence of {declaration.symbol} are "
            f"[{recomputed.price_lower}, {recomputed.price_upper}], not the "
            f"[{expected_lower}, {expected_upper}] the decision record names"
        )
    return TerminalSettlement(
        symbol=declaration.symbol,
        kind=TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
        recorded_evaluation=TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
        bound_window_start_utc=window_start,
        samples_per_minute=SAMPLES_PER_MINUTE,
        nominal_lower=fraction_text(recomputed.nominal_lower),
        nominal_upper=fraction_text(recomputed.nominal_upper),
        price_tick_size=tick,
        index_lower=recomputed.index_lower,
        index_upper=recomputed.index_upper,
        trade_candle_low=recomputed.trade_low,
        trade_candle_high=recomputed.trade_high,
        price_lower=recomputed.price_lower,
        price_upper=recomputed.price_upper,
        index_klines=EvidenceFile(index_path, _sha256(repo_root / index_path)),
        trade_kline=EvidenceFile(trade_path, _sha256(repo_root / trade_path)),
        supporting_evidence=(EvidenceFile(support_path, _sha256(repo_root / support_path)),),
        condition=SETTLEMENT_CONDITION,
        official_confirmation=None,
    )


def _require_relative_posix(path: str, name: str) -> None:
    """A clean repository-relative posix path: the same text must resolve on any machine."""
    parts = PurePosixPath(path).parts
    if (
        not path
        or "\\" in path
        or PurePosixPath(path).as_posix() != path
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or PureWindowsPath(path).drive != ""
        or ".." in parts
    ):
        raise ManifestError(f"{name} must be a clean posix path relative to the repository root")


def _constraint_ticks(constraint_file: Path, constraint_sha256: str) -> dict[str, Decimal]:
    try:
        raw = constraint_file.read_bytes()
    except OSError as exc:
        raise ManifestError(f"the constraint file is unreadable ({type(exc).__name__})") from None
    if hashlib.sha256(raw).hexdigest() != constraint_sha256:
        raise ManifestError("the constraint file bytes do not match the recorded constraint_sha256")
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ManifestError("the constraint file is not valid JSON") from None
    rows = loaded.get("constraint_history") if isinstance(loaded, dict) else loaded
    if not isinstance(rows, list):
        raise ManifestError("the constraint file must hold a list of rows")
    ticks: dict[str, Decimal] = {}
    for row in rows:
        if isinstance(row, dict) and "symbol" in row and "price_tick_size" in row:
            try:
                tick = Decimal(str(row["price_tick_size"]))
            except InvalidOperation:
                raise ManifestError("a constraint row has an invalid price_tick_size") from None
            if str(row["symbol"]) in ticks:
                raise ManifestError(f"the constraint file has two rows for {row['symbol']}")
            ticks[str(row["symbol"])] = tick
    return ticks


def build_manifest(*, decision_text: str, raw_root: Path, repo_root: Path) -> DatasetManifest:
    """Build the manifest of the decision record; every value comes from the record."""
    values = parse_decision_values(decision_text)
    _require(values)
    symbols = tuple(part.strip() for part in values["symbols"].split(","))
    if not all(symbols):
        raise ManifestError("symbols must be a comma separated list of names")
    if values["excluded_periods"] != "[]":
        raise ManifestError(
            "excluded_periods other than '[]' are not supported: the runner refuses them"
        )
    dev_start = _instant(values, "development_start_utc")
    dev_end = _instant(values, "development_end_utc")
    val_start = _instant(values, "validation_start_utc")
    val_end = _instant(values, "validation_end_utc")
    hold_start = _instant(values, "holdout_start_utc")
    hold_end = _instant(values, "holdout_end_utc")
    if (
        _instant(values, "window_start_utc") != dev_start
        or _instant(values, "window_end_utc") != hold_end
    ):
        raise ManifestError("the window must start at development start and end at holdout end")
    declarations = _declarations(values)
    intervals = (values["strategy_interval"], values["context_interval"])
    try:
        data = build_case_input_data(
            raw_root,
            symbols=list(symbols),
            start_utc=dev_start,
            end_utc=val_end,
            as_of_day_utc=val_end.date(),
            strategy_interval=intervals[0],
            context_interval=intervals[1],
            series=ENGINE_SERIES,
            terminal_declarations=declarations,
        )
    except CaseInputError as exc:
        raise ManifestError(f"the published day files do not build the window: {exc}") from None

    _require_relative_posix(values["constraint_source"], "constraint_source")
    ticks = _constraint_ticks(repo_root / values["constraint_source"], values["constraint_sha256"])
    absent = sorted(symbol for symbol in symbols if symbol not in ticks)
    if absent:
        raise ManifestError(f"the constraint file has no row for {absent}")
    settlements: list[TerminalSettlement] = []
    if "terminal_settlements" in values:
        declared = {d.symbol: d for d in declarations}
        for part in values["terminal_settlements"].split(" | "):
            match = _SETTLEMENT_LINE.match(part.strip())
            if match is None:
                raise ManifestError(
                    "terminal_settlements must read 'SYMBOL, price_lower <p>, price_upper <p>'"
                )
            symbol = match["symbol"]
            if symbol not in declared or symbol not in ticks:
                raise ManifestError(
                    f"terminal_settlements names {symbol} without a declaration in the universe"
                )
            try:
                expected = (Decimal(match["lower"]), Decimal(match["upper"]))
            except InvalidOperation:
                raise ManifestError("terminal_settlements prices must be decimals") from None
            settlements.append(
                build_terminal_settlement(
                    declaration=declared[symbol],
                    tick=ticks[symbol],
                    expected_lower=expected[0],
                    expected_upper=expected[1],
                    repo_root=repo_root,
                )
            )
    manifest = DatasetManifest(
        universe_id=values["universe_id"],
        symbols=symbols,
        dataset_id=data.dataset_id,
        development_start_utc=dev_start,
        development_end_utc=dev_end,
        validation_start_utc=val_start,
        validation_end_utc=val_end,
        holdout_start_utc=hold_start,
        holdout_end_utc=hold_end,
        strategy_interval=intervals[0],
        context_interval=intervals[1],
        data_source=values["data_source"],
        data_source_version=values["data_source_version"],
        excluded_periods=(),
        known_gaps=declarations,
        equity=_decimal(values, "equity"),
        risk_rate=_decimal(values, "risk_rate"),
        constraint_source=values["constraint_source"],
        constraint_sha256=values["constraint_sha256"],
        terminal_settlements=tuple(settlements),
    )
    _check_folds_line(values["validation_folds"], manifest)
    return manifest


def _check_folds_line(text: str, manifest: DatasetManifest) -> None:
    """The record's fold boundaries (every date in the line) must be the manifest's folds."""
    folds = manifest.validation_folds()
    expected = [folds[0][0].date().isoformat(), *(end.date().isoformat() for _, end in folds)]
    if _DATE.findall(text) != expected:
        raise ManifestError(
            f"the validation_folds line does not name the boundaries {expected} of the "
            "four equal folds"
        )


def manifest_json_text(manifest: DatasetManifest) -> str:
    """The file form of a manifest: its canonical content as JSON strings (Decimal-safe)."""
    payload = canonical_scalars(manifest.canonical())
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_manifest(manifest: DatasetManifest, out: Path) -> str:
    """Write the manifest file (never over an existing file) and return its hash after a reload.

    The text is written to a temporary file next to `out`, reloaded and compared by hash, and only
    then linked to `out` (a link fails when `out` exists); no failure leaves a file at `out`.
    """
    if out.exists():
        raise ManifestError("the output file exists: the build never overwrites a manifest")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(manifest_json_text(manifest))
        reloaded = load_manifest(temporary)
        if manifest_hash(reloaded) != manifest_hash(manifest):
            raise ManifestError("the written manifest does not reload to the same hash")
        try:
            os.link(temporary, out)
        except FileExistsError:
            raise ManifestError(
                "the output file exists: the build never overwrites a manifest"
            ) from None
    finally:
        temporary.unlink(missing_ok=True)
    return manifest_hash(manifest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.research.manifest",
        description="Build the dataset manifest from the O-03b decision record.",
    )
    parser.add_argument("--build", action="store_true", required=True)
    parser.add_argument("--decision", type=Path, required=True, help="16-DEC-O-03b.md")
    parser.add_argument("--raw-root", type=Path, required=True, help="published data root")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT, help="repository root")
    parser.add_argument("--out", type=Path, required=True, help="manifest JSON to create")
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(
            decision_text=args.decision.read_text(encoding="utf-8"),
            raw_root=args.raw_root,
            repo_root=args.repo_root,
        )
        digest = write_manifest(manifest, args.out)
    except (ValueError, OSError) as exc:  # ManifestError is a ValueError
        print(f"refused: {exc}")
        return 2
    print(f"manifest_hash={digest}")
    print(f"dataset_id={manifest.dataset_id}")
    print(f"wrote={args.out}")
    return 0
