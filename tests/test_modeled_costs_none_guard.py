"""REV-09 guard: no report or metric reads a None `modeled_costs_per_unit` as zero cost.

Plan 16-18, D-29, REV-09 / D063 item 7; inherited D052-open (O-10). v2 filled TradeRecords carry
`modeled_costs_per_unit=None`. Restoring it is a separate user decision (O-10, plan 16-41); until
then the field must stay None and no consumer may turn None into a zero cost.

Two parts:
  * an AST audit over `src/` that pins every place the name is read (the consumer audit, also
    recorded in the plan SUMMARY) and fails when a new reader appears, and
  * a behavioural check per pinned reader that None stays None (or is refused), never zero.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters import analytics_files
from src.backtest import costs, experiment, records
from src.backtest import report as backtest_report
from src.backtest.semantics import REJECT
from src.research.report import summarize_trades
from src.risk import sizing
from src.risk.types import SizedResult

from tests.backtest_case_helpers import make_experiment_record

NAME = "modeled_costs_per_unit"
SRC = Path(__file__).resolve().parents[1] / "src"

# The consumer audit (REV-09). Each entry: (file, enclosing symbol, kind, detail) -> occurrences.
# Re-run at execution time of plan 16-18 (2026-10-09); the research S3 list held.
RECORD_READERS: Counter[tuple[str, str, str, str]] = Counter(
    {
        # Generic round-trip parse of a trade dict: None stays None (see the behavioural test).
        ("src/backtest/experiment.py", "<module>", "field_name_list", "_DECIMAL_TRADE_FIELDS"): 1,
        # Evidence-file validation: a None value is skipped, never parsed.
        (
            "src/adapters/analytics_files.py",
            "<module>",
            "field_name_list",
            "_TRADE_DECIMAL_FIELDS",
        ): 1,
    }
)
# The same name on values that are NOT TradeRecords (research S3): the SizedResult field, a
# parameter label, a kwargs refusal. They never see a v2 filled record.
UNRELATED_USES: Counter[tuple[str, str, str, str]] = Counter(
    {
        # SizedResult attribute passed on to REJECT records (engine reject paths).
        ("src/backtest/engine.py", "_Engine._size_and_register", "attribute_read", "sized"): 2,
        ("src/risk/types.py", "SizedResult.__post_init__", "loop_key_literal", ""): 1,
        ("src/risk/sizing.py", "size_position", "call_label", "_require_decimal"): 1,
        ("src/execution/manager.py", "execute_approved_plan", "key_membership", ""): 1,
    }
)
# Not reads: export lists and the one dict-literal writer of None on filled records.
EXPORTS_AND_WRITERS: Counter[tuple[str, str, str, str]] = Counter(
    {
        ("src/backtest/__init__.py", "<module>", "export_name", ""): 1,
        ("src/backtest/costs.py", "<module>", "export_name", ""): 1,
        ("src/backtest/records.py", "build_trade_record", "dict_key_write", "None"): 1,
    }
)
# Names holding the field-name lists, and the only functions allowed to iterate them.
FIELD_LIST_CONSUMERS: dict[str, set[tuple[str, str]]] = {
    "_DECIMAL_TRADE_FIELDS": {("src/backtest/experiment.py", "_trade_from_dict")},
    "_TRADE_DECIMAL_FIELDS": {("src/adapters/analytics_files.py", "_check_trade_fields")},
}


def _enclosing(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names: list[str] = []
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
    return ".".join(reversed(names)) or "<module>"


def _classify_constant(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> tuple[str, str]:
    parent = parents[node]
    grand = parents.get(parent)
    if isinstance(parent, ast.Dict) and node in parent.keys:
        value = parent.values[parent.keys.index(node)]
        return "dict_key_write", ast.unparse(value)
    if isinstance(parent, ast.Subscript):
        return "key_subscript", ""
    if isinstance(parent, ast.Call):
        func = parent.func
        if isinstance(func, ast.Attribute) and func.attr in {"get", "pop", "setdefault"}:
            return "key_get", func.attr
        if isinstance(func, ast.Name) and func.id == "getattr":
            return "getattr", ""
        return "call_label", ast.unparse(func)
    if isinstance(parent, ast.Compare):
        return "key_membership", ""
    if isinstance(parent, ast.Tuple | ast.List | ast.Set):
        if isinstance(grand, ast.For) and grand.iter is parent:
            return "loop_key_literal", ""
        if isinstance(grand, ast.Assign | ast.AnnAssign):
            targets = grand.targets if isinstance(grand, ast.Assign) else [grand.target]
            target = targets[0]
            if isinstance(target, ast.Name):
                if target.id == "__all__":
                    return "export_name", ""
                return "field_name_list", target.id
    return "other_string", ast.unparse(parent)[:60]


def scan_sources(root: Path = SRC) -> Counter[tuple[str, str, str, str]]:
    """Every attribute read and every string use of the field name under `root` (exact match)."""
    found: Counter[tuple[str, str, str, str]] = Counter()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if NAME not in text:
            continue
        rel = path.relative_to(root.parent).as_posix()
        tree = ast.parse(text)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == NAME:
                kind = "attribute_read" if isinstance(node.ctx, ast.Load) else "attribute_write"
                found[(rel, _enclosing(node, parents), kind, ast.unparse(node.value))] += 1
            elif isinstance(node, ast.Constant) and node.value == NAME:
                kind, detail = _classify_constant(node, parents)
                found[(rel, _enclosing(node, parents), kind, detail)] += 1
    return found


# --------------------------------------------------------------------------- #
# Test 3: the pinned consumer audit.
# --------------------------------------------------------------------------- #


def test_consumer_audit_is_pinned_and_fails_when_a_new_reader_appears() -> None:
    expected = RECORD_READERS + UNRELATED_USES + EXPORTS_AND_WRITERS
    found = scan_sources()
    assert found == expected, (
        "a new reader or writer of modeled_costs_per_unit appeared (or one moved): audit it "
        f"for a None-as-zero read, then update the pinned list. "
        f"found only: {found - expected}; missing: {expected - found}"
    )


def test_the_scan_detects_a_new_reader_in_a_synthetic_module(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    source = (
        "def total(record):\n"
        "    return record.modeled_costs_per_unit + 1\n"
        "def lookup(row):\n"
        "    return row['modeled_costs_per_unit'] or row.get('modeled_costs_per_unit')\n"
    )
    (root / "newreader.py").write_text(source, encoding="utf-8")
    found = scan_sources(root)
    assert found == Counter(
        {
            ("src/newreader.py", "total", "attribute_read", "record"): 1,
            ("src/newreader.py", "lookup", "key_subscript", ""): 1,
            ("src/newreader.py", "lookup", "key_get", "get"): 1,
        }
    )
    expected = RECORD_READERS + UNRELATED_USES + EXPORTS_AND_WRITERS
    assert found != expected


def test_the_field_name_lists_are_iterated_only_by_the_audited_functions() -> None:
    consumers: dict[str, set[tuple[str, str]]] = {name: set() for name in FIELD_LIST_CONSUMERS}
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not any(name in text for name in FIELD_LIST_CONSUMERS):
            continue
        rel = path.relative_to(SRC.parent).as_posix()
        tree = ast.parse(text)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in FIELD_LIST_CONSUMERS
            ):
                consumers[node.id].add((rel, _enclosing(node, parents)))
    assert consumers == FIELD_LIST_CONSUMERS


def test_filled_records_are_built_with_none_in_the_one_pinned_writer() -> None:
    writers = [k for k in scan_sources() if k[2] == "dict_key_write"]
    assert writers == [("src/backtest/records.py", "build_trade_record", "dict_key_write", "None")]


# --------------------------------------------------------------------------- #
# Test 4: the scan tells the record field from the unrelated same-named things.
# --------------------------------------------------------------------------- #


def test_scan_does_not_list_the_sized_result_field_or_the_cost_function_as_record_readers() -> None:
    record_reads = {key for key in scan_sources() if key in RECORD_READERS}
    assert {key[0] for key in record_reads} == {
        "src/backtest/experiment.py",
        "src/adapters/analytics_files.py",
    }
    # The costs.py function definition is a name, not a read of a record field.
    assert callable(costs.modeled_costs_per_unit)
    assert not any(
        k[0] == "src/backtest/costs.py" and k[2] != "export_name" for k in scan_sources()
    )
    # The engine's attribute reads are on the SizedResult bound from the portfolio verdict.
    engine_tree = ast.parse((SRC / "backtest" / "engine.py").read_text(encoding="utf-8"))
    assigns = [
        node
        for node in ast.walk(engine_tree)
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]) == "sized"
        and ast.unparse(node.value) == "verdict.sized"
    ]
    assert len(assigns) == 1
    assert "sized: SizedResult | None" in (SRC / "risk" / "types.py").read_text(encoding="utf-8")
    assert any(f.name == NAME for f in _dataclass_fields(SizedResult))


def _dataclass_fields(cls: type) -> list[Any]:
    import dataclasses

    return list(dataclasses.fields(cls))


# --------------------------------------------------------------------------- #
# Behavioural: for each pinned reader, None stays None or is refused, never zero.
# --------------------------------------------------------------------------- #


def _reject_dict() -> dict[str, Any]:
    record = records.build_reject_record(
        signal_id="sig",
        trade_plan_id="plan",
        symbol="BTCUSDT",
        direction="LONG",
        reason_code="MIN_QTY_REJECT",
        bar_close_utc=datetime(2026, 1, 5, 10, tzinfo=UTC),
        strategy_version="v2",
        parameter_set_hash="1" * 64,
        modeled_costs_per_unit=None,
    )
    assert record.entry_kind == REJECT
    return record.to_dict()


def test_round_trip_parse_keeps_none_as_none() -> None:
    raw = _reject_dict()
    assert raw[NAME] is None
    assert experiment._coerce_trade_decimal(None, NAME) is None
    rebuilt = experiment._trade_from_dict(raw)
    assert rebuilt.modeled_costs_per_unit is None
    assert rebuilt.modeled_costs_per_unit != Decimal("0")


def test_evidence_file_validation_skips_none_and_the_loaded_record_keeps_none() -> None:
    raw = _reject_dict()
    analytics_files._check_trade_fields({NAME: None}, "where")
    loaded = analytics_files._load_trades([raw], "where")
    assert loaded[0].modeled_costs_per_unit is None


def test_sized_result_field_accepts_none_and_sizing_refuses_none() -> None:
    sized = SizedResult(
        is_no_trade=True,
        quantity=None,
        quantity_before_rounding=Decimal("0"),
        quantity_after_rounding=Decimal("0"),
        quantization_decision="DEFERRED_TO_RISK",
        realized_risk=Decimal("0"),
        reason_code="OK",
        modeled_costs_per_unit=None,
    )
    assert sized.modeled_costs_per_unit is None
    with pytest.raises(TypeError):
        sizing._require_decimal(None, NAME)


def test_reject_record_writer_keeps_none_and_the_filled_writer_writes_none() -> None:
    assert _reject_dict()[NAME] is None
    source = (SRC / "backtest" / "records.py").read_text(encoding="utf-8")
    assert f'"{NAME}": None,' in source


# --------------------------------------------------------------------------- #
# No report or metric figure depends on the field at all (so None cannot act as zero).
# --------------------------------------------------------------------------- #


def _trade(trade_id: str, pnl: str, risk: str, costs_value: object) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "signal_id": "sig",
        "trade_plan_id": "plan",
        "strategy_version": "v2.0.0",
        "parameter_set_hash": "1" * 64,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_kind": "ENTRY_FILLED",
        "entry_price": "100.00",
        "entry_time_utc": "2026-01-15T10:00:00+00:00",
        "quantity": "0.1",
        "exit_kind": "TP2",
        "exit_price": "101.00",
        "exit_time_utc": "2026-01-15T11:00:00+00:00",
        "realized_pnl": pnl,
        "realized_risk": risk,
        "gross_pnl": pnl,
        "entry_fee": "0.001",
        "exit_fee": "0.001",
        "funding_amount": "0",
        "slippage_amount": "0.0001",
        NAME: costs_value,
        "coverage_note": None,
        "fallback_applied": False,
        "outcome_kind": "OK",
        "reason_code": "OK",
        "regime": "TREND_UP",
    }


def _trades(costs_value: object) -> list[dict[str, Any]]:
    return [
        _trade("t1", "0.50", "0.10", costs_value),
        _trade("t2", "-0.20", "0.10", costs_value),
        _trade("t3", "0.30", "0.10", costs_value),
    ]


@pytest.mark.parametrize("other", ["0", "0.0008", "5"])
def test_backtest_report_digest_does_not_move_with_the_cost_field(other: str) -> None:
    record = make_experiment_record(experiment_id="0" * 64)
    built_at = datetime(2026, 9, 26, 12, tzinfo=UTC)

    def digest(value: object) -> str:
        return backtest_report.build(
            experiment_record=record,
            trade_records=_trades(value),
            bootstrap_seed=7,
            built_at_utc=built_at,
            resamples=100,
        ).digest()

    assert digest(None) == digest(other)


@pytest.mark.parametrize("other", ["0", "0.0008", "5"])
def test_research_summary_does_not_move_with_the_cost_field(other: str) -> None:
    record = make_experiment_record(experiment_id="0" * 64)
    built_at = datetime(2026, 9, 26, 12, tzinfo=UTC)

    def summary(value: object) -> dict[str, object]:
        return summarize_trades(
            experiment_record=record, trade_records=_trades(value), built_at_utc=built_at
        )

    assert summary(None) == summary(other)
