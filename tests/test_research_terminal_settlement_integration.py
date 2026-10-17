"""Design tests 1 and 3 of the S-B-interval design through the real runner (nnl plan 06).

Design 16-DRAFT-S-B-interval-design.md section 4: "REEF terminal lies in Development, so
settlement uncertainty cannot reach G1-G5". This module proves it end to end:

* design test 1: two manifests that differ only in the settlement bound values (and the
  evidence bytes that prove them) give byte-equal Validation case dicts, trades, run summaries
  and experiment records, after removing exactly `experiment_id` and `data_manifest_hash` (both
  derive from the manifest hash by D067, which includes the bounds); the Development case differs
  only in `terminal_settlements`;
* the bound is not vacuous: an engine-level OPEN position at T settles at the bound;
* design test 3: the G1 counts and the plateau summaries are built from VALIDATION records only,
  the Development settlement is reported apart, and no other reader of the Development role
  exists in `src/research` and `src/analytics/gates.py` (explicit AST allowlist).

The synthetic store makes the strategy run without a trade (no_trade_counts only), so the
byte-equality of Validation trades is a statement about empty lists; the load-bearing equality is
that of the Validation CASE dicts (the simulator is deterministic, so equal inputs give equal
outputs) together with the engine-level guard that the bound does reach a settled trade.

Everything is synthetic and lives in tmp_path: the store, the constraint file, the evidence files,
the manifests and the experiment records. No production code is added by this plan. The terminal
symbol DELISTUSDT stands for a REEFUSDT-shaped symbol (the geometry of
tests/test_research_known_gap_reason.py); no real value is used.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from src.backtest import simulator
from src.backtest.experiment import CodeVersion, ExperimentRecord
from src.backtest.semantics import (
    EXIT_SETTLEMENT,
    TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
)
from src.data.case_input import ENGINE_SERIES, build_case_input_data
from src.research import run as research_run
from src.research.feasibility import feasibility_report, render_feasibility
from src.research.manifest import (
    DatasetManifest,
    EvidenceFile,
    GridPoint,
    ParameterGrid,
    TerminalDeclaration,
    TerminalSettlement,
    manifest_hash,
    research_splits,
)
from src.research.run import run_research

from tests.backtest_case_helpers import constraint_row
from tests.test_backtest_report import _gap_trade
from tests.test_backtest_terminal_settlement import run_settled, settled_case, settlement_row
from tests.test_case_input_builder import build_store
from tests.test_research_known_gap_reason import (
    CUT,
    DEV_END,
    HOLD_END,
    LONG,
    REASON,
    SOURCE_URL,
    STORE_START,
    TERM,
    VAL_END,
    _publish_terminal_symbol,
)
from tests.test_research_runner import FAKE_COMMIT, _authorization, _grid

REPO_ROOT = Path(__file__).resolve().parents[1]
D = Decimal
TICK = D("0.01")
WINDOW_START = CUT - timedelta(minutes=30)
INDEX_REL = "evidence/index_klines.json"
TRADE_REL = "evidence/trade_kline.json"
SUPPORT_REL = "evidence/support.json"
CONDITION = "synthetic test-only condition: the settlement price is an unverified assumption"
# Two disjoint synthetic intervals: base 95 gives [94, 96], base 105 gives [104, 106].
LOWER_BASE = D("95")
UPPER_BASE = D("105")


def _ms(value: Any) -> int:
    return int(value.timestamp() * 1000)


def _kline_row(open_ms: int, open_: Decimal, high: Decimal, low: Decimal) -> list[Any]:
    """One Binance kline row (12 items; prices are JSON strings)."""
    return [open_ms, str(open_), str(high), str(low), str(open_), "1", open_ms + 59_999, "1", 1]


def _write_evidence(root: Path, base: Decimal) -> dict[str, str]:
    """Write the three synthetic evidence files under `root`; return the sha256 per path.

    Index minutes: open = close = base, high = base + 0.5, low = base - 0.5 for all 30 minutes of
    [T - 30 min, T), so the nominal interval is exactly [base - 0.5, base + 0.5]. The trade
    candle opening at T: low = base - 1, high = base + 1. With the 0.01 tick the widened index
    interval is [base - 0.51, base + 0.51] and the union is [base - 1, base + 1].
    """
    index_rows = [
        _kline_row(_ms(WINDOW_START) + 60_000 * i, base, base + D("0.5"), base - D("0.5"))
        for i in range(30)
    ]
    trade_rows = [_kline_row(_ms(CUT), base, base + D("1"), base - D("1"))]
    bodies = {
        INDEX_REL: json.dumps(index_rows, separators=(",", ":")),
        TRADE_REL: json.dumps(trade_rows, separators=(",", ":")),
        SUPPORT_REL: json.dumps({"synthetic": str(base)}, separators=(",", ":")),
    }
    digests: dict[str, str] = {}
    for rel, text in bodies.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        target.write_bytes(raw)
        digests[rel] = hashlib.sha256(raw).hexdigest()
    return digests


def _fraction_text(value: Decimal) -> str:
    ratio = Fraction(value)
    return f"{ratio.numerator}/{ratio.denominator}"


def _settlement(base: Decimal, digests: dict[str, str]) -> TerminalSettlement:
    """The row for evidence written by `_write_evidence(base)`, every bound derived by hand."""
    return TerminalSettlement(
        symbol=TERM,
        kind=TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
        recorded_evaluation=TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
        bound_window_start_utc=WINDOW_START,
        samples_per_minute=60,
        nominal_lower=_fraction_text(base - D("0.5")),
        nominal_upper=_fraction_text(base + D("0.5")),
        price_tick_size=TICK,
        index_lower=base - D("0.51"),
        index_upper=base + D("0.51"),
        trade_candle_low=base - D("1"),
        trade_candle_high=base + D("1"),
        price_lower=base - D("1"),
        price_upper=base + D("1"),
        index_klines=EvidenceFile(INDEX_REL, digests[INDEX_REL]),
        trade_kline=EvidenceFile(TRADE_REL, digests[TRADE_REL]),
        supporting_evidence=(EvidenceFile(SUPPORT_REL, digests[SUPPORT_REL]),),
        condition=CONDITION,
        official_confirmation=None,
    )


@dataclass(frozen=True)
class World:
    store: Path
    constraint_path: Path
    constraint_source: str
    constraint_sha256: str
    dataset_id: str
    declaration: TerminalDeclaration


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    """A long-history symbol and a REEFUSDT-shaped symbol whose data stops at T in Development."""
    base_dir = tmp_path_factory.mktemp("settlement_integration")
    store = base_dir / "raw"
    build_store(store, start=STORE_START, end=VAL_END, symbols=(LONG,))
    _publish_terminal_symbol(store, TERM, STORE_START, CUT)
    observed = STORE_START - timedelta(days=30)
    constraints = base_dir / "constraints.json"
    constraints.write_text(
        json.dumps(
            {"constraint_history": [constraint_row(LONG, observed), constraint_row(TERM, observed)]}
        ),
        encoding="utf-8",
    )
    declaration = TerminalDeclaration(
        symbol=TERM, reason=REASON, terminal_at_utc=CUT, source_url=SOURCE_URL
    )
    dataset_id = build_case_input_data(
        store,
        symbols=[LONG, TERM],
        start_utc=STORE_START,
        end_utc=VAL_END,
        as_of_day_utc=VAL_END.date(),
        strategy_interval="1h",
        context_interval="4h",
        series=ENGINE_SERIES,
        terminal_declarations=(declaration,),
    ).dataset_id
    return World(
        store=store,
        constraint_path=constraints,
        constraint_source=constraints.name,
        constraint_sha256=hashlib.sha256(constraints.read_bytes()).hexdigest(),
        dataset_id=dataset_id,
        declaration=declaration,
    )


def _manifest(world: World, settlement: TerminalSettlement) -> DatasetManifest:
    return DatasetManifest(
        universe_id="research-universe-v1",
        symbols=(LONG, TERM),
        dataset_id=world.dataset_id,
        development_start_utc=STORE_START,
        development_end_utc=DEV_END,
        validation_start_utc=DEV_END,
        validation_end_utc=VAL_END,
        holdout_start_utc=VAL_END,
        holdout_end_utc=HOLD_END,
        strategy_interval="1h",
        context_interval="4h",
        data_source="binance-usdm-public",
        data_source_version="test-1",
        excluded_periods=(),
        known_gaps=(world.declaration,),
        equity=D("1000"),
        risk_rate=D("0.005"),
        constraint_source=world.constraint_source,
        constraint_sha256=world.constraint_sha256,
        terminal_settlements=(settlement,),
    )


@dataclass
class Captured:
    """What one run_research call fed to the simulator and what came back."""

    manifest: DatasetManifest
    records: tuple[ExperimentRecord, ...]
    cases: list[dict[str, Any]]
    outputs: list[dict[str, Any]]


def _run(world: World, tmp_path: Path, name: str, base: Decimal) -> Captured:
    """One authorized run over a manifest whose evidence lives under tmp_path/<name>/repo."""
    repo_root = tmp_path / name / "repo"
    digests = _write_evidence(repo_root, base)
    (repo_root / world.constraint_source).write_bytes(world.constraint_path.read_bytes())
    manifest = _manifest(world, _settlement(base, digests))
    grid = _grid()
    cases: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    real_run = simulator.run

    def spy_run(case_input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        cases.append(copy.deepcopy(case_input))
        output = real_run(case_input, **kwargs)
        outputs.append(copy.deepcopy(output))
        return output

    def fake_code_version(repo: Path) -> CodeVersion:
        return CodeVersion(commit=FAKE_COMMIT, dirty=False)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(simulator, "run", spy_run)
        patch.setattr(research_run, "read_code_version", fake_code_version)
        records = run_research(
            manifest=manifest,
            grid=grid,
            authorization=_authorization(manifest, grid),
            raw_root=world.store,
            output_dir=tmp_path / name / "experiments",
            repo_root=repo_root,
        )
    return Captured(manifest=manifest, records=records, cases=cases, outputs=outputs)


@pytest.fixture(scope="module")
def paired(world: World, tmp_path_factory: pytest.TempPathFactory) -> tuple[Captured, Captured]:
    """The same synthetic run under the lower and under the upper bound set."""
    base_dir = tmp_path_factory.mktemp("settlement_runs")
    return (
        _run(world, base_dir, "lower", LOWER_BASE),
        _run(world, base_dir, "upper", UPPER_BASE),
    )


def _text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _record_without_identity(record: ExperimentRecord) -> str:
    payload = record.to_dict()
    del payload["experiment_id"]
    del payload["data_manifest_hash"]
    return _text(payload)


# --------------------------------------------------------------------------- #
# Design test 1.
# --------------------------------------------------------------------------- #


def test_bounds_never_reach_validation_outputs_or_records(
    paired: tuple[Captured, Captured],
) -> None:
    lower, upper = paired
    windows = research_splits(lower.manifest)
    assert [w.role for w in windows] == ["DEVELOPMENT"] + ["VALIDATION"] * 4
    assert len(lower.cases) == len(upper.cases) == len(lower.records) == len(upper.records) == 5
    # The two manifests are different manifests with different bounds and different hashes.
    assert lower.manifest.terminal_settlements[0].price_lower == LOWER_BASE - 1
    assert upper.manifest.terminal_settlements[0].price_lower == UPPER_BASE - 1
    assert manifest_hash(lower.manifest) != manifest_hash(upper.manifest)

    # Development: the case carries the rows and differs in nothing else.
    dev_lower, dev_upper = lower.cases[0], upper.cases[0]
    assert dev_lower["terminal_settlements"] == [
        settlement_row(
            TERM,
            CUT,
            lower=str(LOWER_BASE - 1),
            upper=str(LOWER_BASE + 1),
        )
    ]
    assert dev_upper["terminal_settlements"] == [
        settlement_row(
            TERM,
            CUT,
            lower=str(UPPER_BASE - 1),
            upper=str(UPPER_BASE + 1),
        )
    ]
    assert dev_lower["terminal_settlements"] != dev_upper["terminal_settlements"]
    stripped_lower = {k: v for k, v in dev_lower.items() if k != "terminal_settlements"}
    stripped_upper = {k: v for k, v in dev_upper.items() if k != "terminal_settlements"}
    assert _text(stripped_lower) == _text(stripped_upper)

    # Validation: no key, byte-equal case dicts, trades and run summaries.
    for index in range(1, 5):
        assert "terminal_settlements" not in lower.cases[index]
        assert "terminal_settlements" not in upper.cases[index]
        assert _text(lower.cases[index]) == _text(upper.cases[index])
        assert _text(lower.outputs[index]["trades"]) == _text(upper.outputs[index]["trades"])
        assert _text(lower.outputs[index]["run_summary"]) == _text(
            upper.outputs[index]["run_summary"]
        )
        # The strategy really ran over the window (it only found nothing to trade) ...
        assert lower.outputs[index]["run_summary"]["no_trade_counts"]
        # ... and a Validation summary never grows the conditional key.
        assert "settlement_count" not in lower.outputs[index]["run_summary"]

    # Validation records: byte-equal except experiment_id and data_manifest_hash (D067).
    for index in range(1, 5):
        a, b = lower.records[index], upper.records[index]
        assert a.split_role == b.split_role == "VALIDATION"
        assert _record_without_identity(a) == _record_without_identity(b)
        assert a.experiment_id != b.experiment_id
        assert a.data_manifest_hash != b.data_manifest_hash
        assert a.data_manifest_hash == manifest_hash(lower.manifest)
        assert b.data_manifest_hash == manifest_hash(upper.manifest)
        # The data snapshot (the store files) is identical: only the manifest identity moves.
        assert a.data_snapshot_id == b.data_snapshot_id

    # Development: the case declares the settlement, so its summary carries the key.
    assert lower.outputs[0]["run_summary"]["settlement_count"] == 0
    assert upper.outputs[0]["run_summary"]["settlement_count"] == 0


def test_the_bound_reaches_development_output() -> None:
    """Guards against a vacuous test 1: an OPEN position at T settles at the bound it is given."""

    def settled_trade(lower: str, upper: str, direction: str = "LONG") -> dict[str, Any]:
        case = settled_case(direction=direction, rows=[settlement_row(lower=lower, upper=upper)])
        trades = run_settled(case).output["trades"]
        assert len(trades) == 1
        assert trades[0]["exit_kind"] == EXIT_SETTLEMENT
        return trades[0]

    low = settled_trade("90.5", "110.5")
    high = settled_trade("94.5", "112.5")
    assert Decimal(low["exit_price"]) == D("90.5")
    assert Decimal(high["exit_price"]) == D("94.5")
    assert low["exit_price"] != high["exit_price"]
    assert low["realized_pnl"] != high["realized_pnl"]
    # The adverse side follows the direction: a SHORT settles at the upper bound.
    short_low = settled_trade("90.5", "110.5", "SHORT")
    short_high = settled_trade("90.5", "112.5", "SHORT")
    assert Decimal(short_low["exit_price"]) == D("110.5")
    assert Decimal(short_high["exit_price"]) == D("112.5")
    assert short_low["realized_pnl"] != short_high["realized_pnl"]


# --------------------------------------------------------------------------- #
# Design test 3.
# --------------------------------------------------------------------------- #


def _two_point_grid() -> ParameterGrid:
    """Two grid points; only the ids and the per-point record blocks matter to the helpers."""
    first = _grid().points[0]
    second = GridPoint(
        parameter_set_id="baseline-v6",
        parameter_set_hash=first.parameter_set_hash,
        varied=(("minimum_rr", "3"),),  # helper input only: never run against the registry
    )
    return ParameterGrid(strategy_id="trend-pullback", points=(first, second))


def _settlement_trade(lower: str, upper: str, trade_id: str) -> dict[str, Any]:
    """A real engine-produced SETTLEMENT trade (an OPEN LONG closed at T at `lower`)."""
    trades = run_settled(settled_case(rows=[settlement_row(lower=lower, upper=upper)])).output[
        "trades"
    ]
    assert trades[0]["exit_kind"] == EXIT_SETTLEMENT
    return {**trades[0], "trade_id": trade_id}


def _closed_trades(prefix: str) -> list[dict[str, Any]]:
    return [
        _gap_trade(f"{prefix}-1", "0.20", "0.10", exit_kind="TP2"),
        _gap_trade(f"{prefix}-2", "-0.10", "0.10", exit_kind="SL"),
        _gap_trade(f"{prefix}-3", "0.40", "0.10", exit_kind="TP2"),
    ]


def _validation_folds() -> list[list[dict[str, Any]]]:
    """Four non-empty Validation fold lists (so equality below is not a statement about [])."""
    return [_closed_trades(f"fold{n}") for n in range(1, 5)]


def _blocks(
    run: Captured, development: list[dict[str, Any]]
) -> tuple[list[ExperimentRecord], list[list[dict[str, Any]]]]:
    """Records (the real ones of the run) and trade lists of a two-point grid.

    Records are in grid-point order, `research_splits` order within a point: DEVELOPMENT first,
    then four VALIDATION folds. Only the Development list changes between calls.
    """
    records: list[ExperimentRecord] = []
    trade_lists: list[list[dict[str, Any]]] = []
    for _ in range(2):
        folds = _validation_folds()
        for record in run.records:
            records.append(record)
            trade_lists.append(
                list(development) if record.split_role == "DEVELOPMENT" else folds.pop(0)
            )
    return records, trade_lists


def _g1_and_plateau(
    run: Captured, development: list[dict[str, Any]]
) -> tuple[list[str], dict[str, dict[str, object]]]:
    grid = _two_point_grid()
    records, trade_lists = _blocks(run, development)
    lines = research_run._feasibility_lines(run.manifest, grid, records, trade_lists)
    summaries = research_run._plateau_summaries(run.manifest, grid, records, trade_lists)
    return lines, summaries


def _validation_part(line: str) -> str:
    """The part of a G1 line from the pooled figure on: pooled, fold and end-of-data figures."""
    return line.partition("pooled_closed=")[2]


def test_g1_and_plateau_inputs_are_validation_records_only(
    paired: tuple[Captured, Captured],
) -> None:
    run = paired[0]
    at_lower = _settlement_trade("90.5", "110.5", "dev-settlement-1")
    at_upper = _settlement_trade("94.5", "112.5", "dev-settlement-2")
    assert at_lower["exit_price"] != at_upper["exit_price"]
    closed = _closed_trades("dev")

    reference_lines, reference_plateau = _g1_and_plateau(run, closed)
    assert sum("pooled_closed=12 " in line for line in reference_lines) == 2  # 4 folds x 3
    assert reference_plateau["baseline-v5"]["closed_trades"] == 12
    assert not any("development_settlement" in line for line in reference_lines)

    mutations = {
        "settlement at the lower bound": [*closed, at_lower],
        "settlement at the upper bound": [*closed, at_upper],
        "two settlements": [*closed, at_lower, at_upper],
        "only a settlement": [at_lower],
        "no Development trade at all": [],
        "settlement removed again": list(closed),
    }
    for label, development in mutations.items():
        lines, plateau = _g1_and_plateau(run, development)
        assert plateau == reference_plateau, label
        assert len(lines) == len(reference_lines), label
        for line, reference in zip(lines, reference_lines, strict=True):
            if "development_closed=" in line:
                assert _validation_part(line) == _validation_part(reference), label
            else:
                assert line == reference, label


def test_development_settlement_is_reported_apart_and_never_counted_closed(
    paired: tuple[Captured, Captured],
) -> None:
    run = paired[0]
    closed = _closed_trades("dev")
    settlement = _settlement_trade("90.5", "110.5", "dev-settlement-1")
    folds = _validation_folds()

    without = feasibility_report(folds, parameter_set_id="p", development_trades=closed)
    with_one = feasibility_report(
        folds, parameter_set_id="p", development_trades=[*closed, settlement]
    )
    assert without.development_settlement == 0
    assert with_one.development_settlement == 1
    assert with_one.development_closed == without.development_closed == len(closed)
    assert with_one.development_end_of_data == without.development_end_of_data == 0
    assert with_one.pooled_closed == without.pooled_closed == 12
    assert with_one.fold_closed == without.fold_closed
    assert with_one.shortfalls == without.shortfalls

    plain, reported = render_feasibility(without)[0], render_feasibility(with_one)[0]
    assert "development_settlement" not in plain
    assert "development_settlement=1 " in reported
    # It is a Development figure: it sits before the first Validation figure.
    assert reported.index("development_settlement=1") < reported.index("pooled_closed=")

    # The same through the runner helper, with the records of the real run.
    lines, _ = _g1_and_plateau(run, [*closed, settlement])
    development_lines = [line for line in lines if "development_closed=" in line]
    assert len(development_lines) == 2
    for line in development_lines:
        assert "development_closed=3 " in line
        assert "development_settlement=1 " in line


# --------------------------------------------------------------------------- #
# Design test 3, static half: who reads the DEVELOPMENT role.
# --------------------------------------------------------------------------- #

# (path, enclosing function or None for module level, node kind) -> number of mentions of the
# name or the string "DEVELOPMENT" that exist today, each with the reason it is allowed. A G2,
# G3 or G4 producer built after this plan that mentions the Development role fails the equality
# below until the new reader is written here with a reason a reviewer reads.
DEVELOPMENT_READERS: dict[tuple[str, str | None, str], int] = {
    # `DEVELOPMENT = "DEVELOPMENT"`: the role constant definition (the name).
    ("src/research/manifest.py", None, "Name"): 1,
    # the string of that definition plus the "DEVELOPMENT" entry of `__all__`.
    ("src/research/manifest.py", None, "Constant"): 2,
    # `research_splits` builds the Development window: the split list, not a figure.
    ("src/research/manifest.py", "research_splits", "Name"): 1,
    # `_feasibility_lines`: Development counts are printed apart and carry no floor (reporting).
    ("src/research/run.py", "_feasibility_lines", "Constant"): 1,
}


def _development_mentions(path: Path, root: Path) -> Counter[tuple[str, str | None, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    relative = path.relative_to(root).as_posix()
    found: Counter[tuple[str, str | None, str]] = Counter()

    def visit(node: ast.AST, function: str | None) -> None:
        name = node.name if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) else function
        if isinstance(node, ast.Name) and node.id == "DEVELOPMENT":
            found[(relative, function, "Name")] += 1
        if isinstance(node, ast.Constant) and node.value == "DEVELOPMENT":
            found[(relative, function, "Constant")] += 1
        for child in ast.iter_child_nodes(node):
            visit(child, name)

    visit(tree, None)
    return found


def test_no_g2_g3_g4_producer_reads_development() -> None:
    files = sorted((REPO_ROOT / "src" / "research").glob("*.py"))
    files.append(REPO_ROOT / "src" / "analytics" / "gates.py")
    assert len(files) > 5
    mentions: Counter[tuple[str, str | None, str]] = Counter()
    for path in files:
        mentions.update(_development_mentions(path, REPO_ROOT))
    assert dict(mentions) == DEVELOPMENT_READERS, (
        "the readers of the Development role changed; G1-G5 inputs must not use it "
        "(extend DEVELOPMENT_READERS only with a reviewed reason)"
    )
    # The runner's G1 and plateau helpers select VALIDATION records for every figure.
    source = (REPO_ROOT / "src" / "research" / "run.py").read_text(encoding="utf-8")
    assert source.count('records[i].split_role == "VALIDATION"') >= 2
