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
JSON_FIXTURES = ["symbol_config.json"]


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
    assert readme.count("RECORDED_DEMO") >= 2
    assert "not mainnet" in readme
    assert "ISOLATED" in readme  # the sentence that an ISOLATED answer was never recorded
