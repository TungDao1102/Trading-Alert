"""The Phase 22 recorded-Demo fixtures are generated, secret-free and reproducible (plan 22-01).

`scripts/gen_phase22_fixtures.py` unflattens the owner-run Demo capture of 2026-10-22 into the
SDK wire shape. Demo values: demo-observed, not mainnet. Nothing here is typed by hand.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = REPO_ROOT / "scripts" / "gen_phase22_fixtures.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "phase22"
RECORDED = FIXTURE_ROOT / "recorded_demo"
JSON_FIXTURES = ["leverage_brackets.json", "symbol_config.json"]


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_phase22_fixtures", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_generator_rerun_is_byte_identical(tmp_path: Path) -> None:
    generator = _load_generator()
    first, second = tmp_path / "first", tmp_path / "second"
    assert generator.main(["--out", str(first)]) == 0
    assert generator.main(["--out", str(second)]) == 0
    assert _snapshot(first) == _snapshot(second)
    assert _snapshot(first)  # something was written
    assert all(b"\r" not in data for data in _snapshot(first).values())


def test_every_generated_file_is_present_and_equals_a_fresh_run(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    fresh = {path.name: _json(path) for path in sorted((tmp_path / "recorded_demo").glob("*.json"))}
    assert sorted(fresh) == JSON_FIXTURES
    for name, value in fresh.items():
        assert _json(RECORDED / name) == value
    assert sorted(path.name for path in RECORDED.glob("*.json")) == sorted(fresh)


def test_the_generator_imports_nothing_from_src_or_tests() -> None:
    tree = ast.parse(GENERATOR_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"src", "tests", "binance_sdk_derivatives_trading_usds_futures"})


def test_recorded_demo_symbol_config_carries_the_capture_values() -> None:
    data = _json(RECORDED / "symbol_config.json")
    assert data == [
        {
            "isAutoAddMargin": False,
            "leverage": 20,
            "marginType": "CROSSED",
            "maxNotionalValue": "20000000",
            "symbol": "BTCUSDT",
        }
    ]
    row = data[0]
    assert row["isAutoAddMargin"] is False  # a JSON boolean, not the recorded text
    assert type(row["leverage"]) is int  # a JSON integer, not the recorded text


def test_unflatten_builds_lists_and_converts_wire_types() -> None:
    generator = _load_generator()
    rows = generator.unflatten_summary(
        {"1.symbol": "B", "0.symbol": "A", "0.leverage": "12", "0.isAutoAddMargin": "true"}
    )
    assert rows == [{"symbol": "A", "leverage": 12, "isAutoAddMargin": True}, {"symbol": "B"}]


def test_unflatten_rejects_a_gap_in_the_list_indices() -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match="gap"):
        generator.unflatten_summary({"0.symbol": "A", "2.symbol": "C"})


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("leverage", "abc"),
        ("leverage", "1.5"),
        ("isAutoAddMargin", "yes"),
        ("isAutoAddMargin", "1"),
    ],
)
def test_a_non_string_wire_field_with_foreign_text_raises(field: str, text: str) -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match=field):
        generator.unflatten_summary({field: text})


def test_the_readme_lists_every_generated_fixture_with_the_recorded_demo_label() -> None:
    readme = (FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
    for path in sorted(RECORDED.glob("*.json")):
        assert f"`recorded_demo/{path.name}`" in readme
    assert readme.count("RECORDED_DEMO") >= 3
    assert "not mainnet" in readme
    assert "ISOLATED" in readme  # the sentence that an ISOLATED answer was never recorded


# ---------------------------------------------------------------- leverage brackets


def test_recorded_demo_leverage_brackets_carry_the_capture_values() -> None:
    data = _json(RECORDED / "leverage_brackets.json")
    assert len(data) == 1
    assert data[0]["symbol"] == "BTCUSDT"
    brackets = data[0]["brackets"]
    assert len(brackets) == 10
    first, fourth = brackets[0], brackets[3]
    assert first["initialLeverage"] == 125  # the Demo figure; the mainnet change-log says 150
    assert first["maintMarginRatio"] == 0.004 and first["cum"] == 0.0
    assert fourth == {
        "bracket": 4,
        "cum": 46300.0,
        "initialLeverage": 20,
        "maintMarginRatio": 0.025,
        "notionalCap": 20000000,
        "notionalFloor": 3000000,
    }
    for index, row in enumerate(brackets):
        assert row["bracket"] == index + 1
        for field in ("bracket", "initialLeverage", "notionalCap", "notionalFloor"):
            assert type(row[field]) is int, field  # JSON integers, not the recorded text
        for field in ("maintMarginRatio", "cum"):
            assert type(row[field]) is float, field  # JSON numbers, as the SDK models declare


def test_the_loaders_return_the_committed_fixtures() -> None:
    from tests.support.phase22_fixtures import load_leverage_brackets, load_symbol_config

    assert load_symbol_config() == _json(RECORDED / "symbol_config.json")
    assert load_leverage_brackets() == _json(RECORDED / "leverage_brackets.json")


@pytest.mark.parametrize("text", ["abc", "NaN", "Infinity", "-1", "1e5", "0.004 ", "", ".5", "1."])
@pytest.mark.parametrize("field", ["maintMarginRatio", "cum"])
def test_a_number_field_with_foreign_text_raises(field: str, text: str) -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match=field):
        generator.unflatten_summary({field: text})


def test_a_number_field_keeps_the_recorded_number() -> None:
    generator = _load_generator()
    rows = generator.unflatten_summary(
        {"0.maintMarginRatio": "0.004", "0.cum": "0.0", "1.cum": "7", "1.maintMarginRatio": "0.1"}
    )
    assert rows == [
        {"maintMarginRatio": 0.004, "cum": 0.0},
        {"maintMarginRatio": 0.1, "cum": 7},
    ]
    assert type(rows[1]["cum"]) is int


def test_no_production_code_reads_or_embeds_the_fixtures() -> None:
    """The fixtures are test inputs only (D-08): nothing under src/ names them."""
    needles = ("fixtures/phase22", "recorded_demo", "phase22_fixtures", "gen_phase22_fixtures")
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "src").rglob("*.py"))
        if any(needle in path.read_text(encoding="utf-8") for needle in needles)
    ]
    assert offenders == []
