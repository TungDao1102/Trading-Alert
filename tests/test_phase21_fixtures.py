"""The Phase 21 recorded-Demo fixtures are generated, secret-free and reproducible (plan 21-03).

`scripts/gen_phase21_fixtures.py` unflattens the owner-run Demo capture of 2026-10-22 into the
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
GENERATOR_PATH = REPO_ROOT / "scripts" / "gen_phase21_fixtures.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "phase21"
RECORDED = FIXTURE_ROOT / "recorded_demo"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_phase21_fixtures", GENERATOR_PATH)
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


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _walk_keys(item)
    return keys


def test_generator_rerun_is_byte_identical(tmp_path: Path) -> None:
    generator = _load_generator()
    first, second = tmp_path / "first", tmp_path / "second"
    assert generator.main(["--out", str(first)]) == 0
    assert generator.main(["--out", str(second)]) == 0
    assert _snapshot(first) == _snapshot(second)
    assert _snapshot(first)  # something was written
    assert all(b"\r" not in data for data in _snapshot(first).values())


def test_committed_account_information_equals_a_fresh_run(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    fresh = _json(tmp_path / "recorded_demo" / "account_information_v3.json")
    assert _json(RECORDED / "account_information_v3.json") == fresh


def test_the_generator_imports_nothing_from_src_or_tests() -> None:
    tree = ast.parse(GENERATOR_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"src", "tests", "binance_sdk_derivatives_trading_usds_futures"})


def test_recorded_demo_account_information_carries_the_capture_values() -> None:
    data = _json(RECORDED / "account_information_v3.json")
    assert data["totalMarginBalance"] == "4999.09343961"
    assert data["totalWalletBalance"] == "4999.09343961"
    assert data["totalUnrealizedProfit"] == "0.00000000"
    by_asset = {row["asset"]: row for row in data["assets"]}
    assert by_asset["USDT"]["marginBalance"] == "4999.09343961"
    assert by_asset["USDC"]["walletBalance"] == "5000.00000000"
    assert by_asset["BTC"]["walletBalance"] == "0.01000000"
    assert isinstance(by_asset["USDT"]["updateTime"], int)  # WIRE_TYPES gave it its JSON type


def test_unflatten_builds_lists_and_converts_wire_types() -> None:
    generator = _load_generator()
    mixed = generator.unflatten_summary(
        {"total": "1.50", "assets.1.asset": "B", "assets.0.asset": "A"}
    )
    assert mixed == {"total": "1.50", "assets": [{"asset": "A"}, {"asset": "B"}]}
    rows = generator.unflatten_summary({"1.asset": "B", "0.asset": "A", "0.updateTime": "12"})
    assert rows == [{"asset": "A", "updateTime": 12}, {"asset": "B"}]


def test_unflatten_rejects_a_gap_in_the_list_indices() -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match="gap"):
        generator.unflatten_summary({"0.asset": "A", "2.asset": "C"})


@pytest.mark.parametrize(
    ("field", "text"),
    [("updateTime", "abc"), ("updateTime", "1.5"), ("dualSidePosition", "yes"), ("canTrade", "1")],
)
def test_a_non_string_wire_field_with_foreign_text_raises(field: str, text: str) -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match=field):
        generator.unflatten_summary({field: text})


def test_the_alias_key_is_dropped_by_the_generator() -> None:
    generator = _load_generator()
    rows = generator.unflatten_summary(
        {f"0.{generator.ALIAS_FIELD}": "x", "0.asset": "USDT", "0.balance": "1.0"}
    )
    assert rows == [{"asset": "USDT", "balance": "1.0"}]


def test_every_generated_file_is_present_and_equals_a_fresh_run(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    fresh = {path.name: _json(path) for path in sorted((tmp_path / "recorded_demo").glob("*.json"))}
    assert sorted(fresh) == [
        "account_balance_v3.json",
        "account_config.json",
        "account_information_v3.json",
    ]
    for name, value in fresh.items():
        assert _json(RECORDED / name) == value
    assert sorted(path.name for path in RECORDED.glob("*.json")) == sorted(fresh)


def test_no_fixture_carries_the_account_alias_key_at_any_depth() -> None:
    generator = _load_generator()
    files = sorted(RECORDED.glob("*.json"))
    assert len(files) == 3
    for path in files:
        assert generator.ALIAS_FIELD not in _walk_keys(_json(path)), path.name
        assert generator.ALIAS_FIELD not in path.read_text(encoding="utf-8")


def test_recorded_demo_balance_rows_and_config_flags_carry_the_capture_values() -> None:
    rows = {row["asset"]: row for row in _json(RECORDED / "account_balance_v3.json")}
    assert rows["USDT"]["balance"] == "4999.09343961"
    assert rows["USDT"]["crossUnPnl"] == "0.00000000"
    assert rows["USDC"]["balance"] == "5000.00000000"
    assert rows["BTC"]["balance"] == "0.01000000"
    assert rows["USDT"]["marginAvailable"] is True
    config = _json(RECORDED / "account_config.json")
    assert config["multiAssetsMargin"] is False
    assert config["dualSidePosition"] is False
    assert config["feeTier"] == 0
    assert config["tradeGroupId"] == -1


def test_the_readme_lists_every_generated_fixture_with_the_recorded_demo_label() -> None:
    readme = (FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
    for path in sorted(RECORDED.glob("*.json")):
        assert f"`recorded_demo/{path.name}`" in readme
    assert readme.count("RECORDED_DEMO") >= 4
    assert "not mainnet" in readme
