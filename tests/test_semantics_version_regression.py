"""Design test 10: simulator semantics 2.2.0 moves only version-derived values (nnl-07, 16-60).

The terminal settlement (D070) moved SIMULATOR_SEMANTICS_VERSION from 2.0.0 to 2.1.0, and the
research warm-up (plan 16-60, D073) moved it from 2.1.0 to 2.2.0. For a case without
`terminal_settlements` and without warm-up input (the engine itself is unchanged by both bumps)
nothing but the version string and the ids hashed from it may move: every other trade field,
every counter and every note stays byte-identical, and the run summary gains no
`settlement_count` key.

The reference outputs are not stored: they are recomputed here with the constant patched back to
each earlier version in every module that binds it by name, and their sha256 is checked against
the values the approved regeneration inventories recorded before the bump
(`.planning/phases/16-paper-runtime-composition/evidence/16-S-B-interval-regen-inventory.md`,
section 3, for 2.0.0, and `.../16-60-regen-inventory.md`, section 3, for 2.1.0). The test reads
only committed case builders and those recorded hashes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

import pytest
from src.backtest import engine, experiment, records, semantics
from src.backtest.engine import simulate
from src.risk.gating import evaluate_risk

from tests.test_backtest_engine import tracer_case
from tests.test_backtest_engine_strategy import trigger_case

OLD_VERSION = "2.1.0"
NEW_VERSION = "2.2.0"

# sha256 of the output of an earlier version, serialized as json.dumps(sort_keys, (",", ":"),
# ensure_ascii), recorded in the approved inventory (section 3) before each constant bump.
INVENTORY_SHA256 = {
    "2.0.0": {
        "scripted_tracer": "be6cd8a6cbcf390de87bf14863e097974989907e9f3657d8c9d89f91123cfcf1",
        "strategy_trigger_no_declaration": (
            "4635c92d2456094adf96765fd6dfedd47d2f6a6cedab7c8f8c064562f78f9266"
        ),
    },
    "2.1.0": {
        "scripted_tracer": "8b9b0d596afb78d863e526dfd394e0f306c754871e27c3dff0272a4f6c76e320",
        "strategy_trigger_no_declaration": (
            "6130a3dd9102a16928a1692acde7c164f5a0b3b1e147a53f939f99801c2c1e87"
        ),
    },
}
EARLIER_VERSIONS = tuple(INVENTORY_SHA256)

# Every module that binds the constant by name (the inventory's patch list).
BINDING_MODULES = (semantics, records, engine, experiment)

CASES: dict[str, Callable[[], dict[str, Any]]] = {
    "scripted_tracer": tracer_case,
    "strategy_trigger_no_declaration": lambda: trigger_case()[0],
}


def _run(name: str) -> dict[str, Any]:
    case = CASES[name]()
    assert "terminal_settlements" not in case
    return simulate(case, risk_fn=evaluate_risk)


def _canonical_bytes(output: dict[str, Any]) -> bytes:
    return json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _run_under(monkeypatch: pytest.MonkeyPatch, version: str, name: str) -> dict[str, Any]:
    for module in BINDING_MODULES:
        monkeypatch.setattr(module, "SIMULATOR_SEMANTICS_VERSION", version)
    return _run(name)


def test_semantics_version_is_2_2_0() -> None:
    assert semantics.SIMULATOR_SEMANTICS_VERSION == NEW_VERSION
    for module in BINDING_MODULES:
        assert module.SIMULATOR_SEMANTICS_VERSION == NEW_VERSION


@pytest.mark.parametrize("old_version", EARLIER_VERSIONS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_no_declaration_output_differs_from_an_earlier_version_only_in_version_and_trade_ids(
    name: str, old_version: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _run(name)
    old = _run_under(monkeypatch, old_version, name)

    # The patched run reproduces the bytes the inventory recorded for that version.
    assert hashlib.sha256(_canonical_bytes(old)).hexdigest() == INVENTORY_SHA256[old_version][name]

    # Trades: equal key by key except trade_id, which moves because it hashes the version.
    assert len(current["trades"]) == len(old["trades"]) >= 1
    for new_trade, old_trade in zip(current["trades"], old["trades"], strict=True):
        assert new_trade.keys() == old_trade.keys()
        assert new_trade["trade_id"] != old_trade["trade_id"]
        for key in new_trade:
            if key != "trade_id":
                assert new_trade[key] == old_trade[key], key

    # Run summary: equal except the version; no settlement_count key on either side.
    new_summary, old_summary = current["run_summary"], old["run_summary"]
    assert new_summary.keys() == old_summary.keys()
    assert "settlement_count" not in new_summary
    assert new_summary["simulator_semantics_version"] == NEW_VERSION
    assert old_summary["simulator_semantics_version"] == old_version
    for key in new_summary:
        if key != "simulator_semantics_version":
            assert new_summary[key] == old_summary[key], key

    # Nothing else in the output moved (any further top-level key, in both directions).
    assert current.keys() == old.keys()
    for key in current:
        if key not in {"trades", "run_summary"}:
            assert current[key] == old[key], key


def test_trade_id_hashes_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same case and same state, two versions, two ids; the same version gives the same id."""
    first = _run_under(monkeypatch, OLD_VERSION, "scripted_tracer")["trades"][0]["trade_id"]
    again = _run_under(monkeypatch, OLD_VERSION, "scripted_tracer")["trades"][0]["trade_id"]
    other = _run_under(monkeypatch, NEW_VERSION, "scripted_tracer")["trades"][0]["trade_id"]
    assert first == again
    assert other != first
